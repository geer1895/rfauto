"""DP-1 P2：自研 RWG/SIW 解析模基 MMT（GSM）适配器（EMSolverRegistry 通道）。

定位（规格 = docs/plan_deepdive_specs_20260924.md DP-1 §3）：保真梯级中
"秒级有物理"档——优化内环预筛/耦合矩阵初值/校准 GT 快速扩充。纯 numpy
零外部进程零 license（#261 免役/#246 免标），is_available() 恒 True。

数学口径全部在 core/rwg_mmt.py（P1，commit b337908，只读复用禁改）；
本模块只做三件事：
1. build_geometry 吃 JSON 段表（uniform/hstep/iris 三型，mm 口径；
   SIW 膜片/阶梯的 w_eff 由调用方经 core.calculators.siw_effective_width_mm
   单源折算后传入，本模块不抄毫米数，#1c）；
2. solve() = solve_chain（端口 TE10 模阻抗基）→ renormalize_2port 到
   50Ω（功率波 Z 矩阵中转，#250/#292 口径）→ skrf Network → openEMS
   同构产物落盘（sparams.csv 5 列掩码契约 + mmt.s2p + mmt_meta.json）；
3. 注册进全局 EMSolverRegistry（EMSolverType.MMT，导入即注册）。

诚实边界（P1 判据 runs/df6_dp1mmt/criteria.md §0 全额继承）：
- 膜片/阶梯的绝对 S 值 UNDECIDABLE 待 G1 HFSS 仲裁（P3）——meta 携带
  absolute_s_note，不冒充已认证；
- undetermined 频点（近截止 ±5%·fc10 / 端口过传）S=NaN 如实不外推，
  产物只写 determined 行；
- 无辐射/无场导出/无 nf2ff/SAR（槽线/共面/辐射族仍走 FDTD/FEM 通道）。

分层：adapters，import core.rwg_mmt；供 service.mmt_service 编排调用。
"""

from __future__ import annotations

import csv
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    SolverCapabilities,
)
from rfauto.core.rwg_mmt import (
    HStepJunction,
    InductiveIris,
    ModePolicy,
    UniformSection,
    Waveguide,
    renormalize_2port,
    solve_chain,
)

logger = logging.getLogger(__name__)

#: v1 模板面：段表直连（无模板机制，模板族仍走 openEMS/HFSS 通道）。
SUPPORTED_TEMPLATES: tuple[str, ...] = ("chain",)

_TOUCHSTONE_NAME = "mmt.s2p"
_SPARAMS_CSV_NAME = "sparams.csv"
_META_NAME = "mmt_meta.json"

#: openEMS 同构 5 列 schema（health_service._parse_sparams_csv_masked 零改动
#: 可消费；≥9 列会被该解析器当 3 端口部分矩阵误读，故 CSV 面按 5 列契约走，
#: 全 2×2 在 Touchstone 与 meta 承载——criteria §0）。
_SPARAMS_CSV_HEADER = ("freq_hz", "re_S11", "im_S11", "re_S21", "im_S21")

_ABSOLUTE_S_NOTE = (
    "膜片/阶梯的绝对 S 值 UNDECIDABLE（P1 判据 runs/df6_dp1mmt/criteria.md "
    "§0）：连续性/无源/互易/×2 收敛门已过，绝对值归 G1 HFSS 仲裁（P3）"
)
_PORT_BASIS_NOTE = (
    "2×2 输出经端口 TE10 模阻抗基 renormalize 到 z0_ref（功率波 Z 矩阵中转，"
    "#250/#292 口径）；undetermined 频点 S=NaN 不外推"
)


class MmtError(ValueError):
    """MMT 段表/求解参数显式错误（JSON 契约违反、几何非法；不静默）。"""


# --------------------------------------------------------------------------- #
# JSON 段表解析（mm 口径 → core 构件；纯函数供测试/服务复用）
# --------------------------------------------------------------------------- #


def _req_f(spec: dict[str, Any], key: str, ctx: str) -> float:
    """取必填有限数值字段（mm 口径不在此做正负校验——交给 core 构件）。"""
    if key not in spec:
        raise MmtError(f"{ctx}: 缺必填字段 {key}")
    try:
        v = float(spec[key])
    except (TypeError, ValueError) as exc:
        raise MmtError(f"{ctx}: 字段 {key}={spec[key]!r} 不是有限数") from exc
    if not math.isfinite(v):
        raise MmtError(f"{ctx}: 字段 {key}={spec[key]!r} 不是有限数")
    return v


def _opt_f(spec: dict[str, Any], key: str, default: float | None = None) -> float | None:
    """可选有限数值字段；缺省/None → default；非法显式报错。"""
    if key not in spec or spec[key] is None:
        return default
    v = float(spec[key])
    if not math.isfinite(v):
        raise MmtError(f"字段 {key}={spec[key]!r} 不是有限数")
    return v


def waveguide_from_json(spec: dict[str, Any], defaults: dict[str, Any],
                        ctx: str) -> Waveguide:
    """段规格（+顶层材质缺省）→ Waveguide（SI 单位；eps_r/tan_d/sigma_s_m
    可段内覆盖）。"""
    eps_r = _opt_f(spec, "eps_r", float(defaults.get("eps_r", 1.0)))
    tan_d = _opt_f(spec, "tan_d", float(defaults.get("tan_d", 0.0)))
    sigma = _opt_f(spec, "sigma_s_m", defaults.get("sigma_s_m"))
    try:
        return Waveguide(
            a=_req_f(spec, "a_mm", ctx) * 1e-3,
            b=_req_f(spec, "b_mm", ctx) * 1e-3,
            eps_r=float(eps_r),
            tan_d=float(tan_d),
            sigma=(float(sigma) if sigma is not None else None),
        )
    except ValueError as exc:
        raise MmtError(f"{ctx}: {exc}") from exc


def section_from_json(spec: dict[str, Any], defaults: dict[str, Any],
                      idx: int) -> UniformSection | HStepJunction | InductiveIris:
    """单段 JSON → core 构件（uniform/hstep/iris 三型；未知型显式报错）。"""
    if not isinstance(spec, dict):
        raise MmtError(f"sections[{idx}]: 必须为对象，得到 {type(spec).__name__}")
    stype = str(spec.get("type", ""))
    ctx = f"sections[{idx}]({stype or '?'})"
    if stype == "uniform":
        try:
            return UniformSection(
                wg=waveguide_from_json(spec, defaults, ctx),
                length_m=_req_f(spec, "length_mm", ctx) * 1e-3,
            )
        except ValueError as exc:
            raise MmtError(f"{ctx}: {exc}") from exc
    if stype == "hstep":
        # 逐侧材质覆盖（介质阶梯：材料过渡合法地属于结面两侧——右侧材质
        # 必须与后继 uniform 一致，否则 core 相邻段校验显式拒绝）
        mat_l = dict(defaults)
        mat_r = dict(defaults)
        for key in ("eps_r", "tan_d", "sigma_s_m"):
            if spec.get(f"{key}_left") is not None:
                mat_l[key] = spec[f"{key}_left"]
            if spec.get(f"{key}_right") is not None:
                mat_r[key] = spec[f"{key}_right"]
        wg_left = waveguide_from_json(
            {"a_mm": _req_f(spec, "a_left_mm", ctx),
             "b_mm": _req_f(spec, "b_left_mm", ctx)},
            mat_l, ctx + ".left")
        wg_right = waveguide_from_json(
            {"a_mm": _req_f(spec, "a_right_mm", ctx),
             "b_mm": _req_f(spec, "b_right_mm", ctx)},
            mat_r, ctx + ".right")
        aperture = _opt_f(spec, "aperture_mm")
        x0 = _opt_f(spec, "x0_mm")
        try:
            if x0 is None:
                # 缺省几何居中（HStepJunction.centered_step 自动配偏移侧）
                return HStepJunction.centered_step(
                    wg_left, wg_right,
                    aperture_m=(aperture * 1e-3 if aperture is not None else None))
            return HStepJunction(wg_left, wg_right,
                                 x0_m=x0 * 1e-3,
                                 aperture_m=(aperture * 1e-3 if aperture is not None
                                             else None))
        except ValueError as exc:
            raise MmtError(f"{ctx}: {exc}") from exc
    if stype == "iris":
        wg = waveguide_from_json(
            {"a_mm": _req_f(spec, "a_mm", ctx), "b_mm": _req_f(spec, "b_mm", ctx)},
            defaults, ctx)
        try:
            return InductiveIris(
                wg=wg,
                aperture_m=_req_f(spec, "aperture_mm", ctx) * 1e-3,
                thickness_m=(_opt_f(spec, "thickness_mm", 0.0) or 0.0) * 1e-3,
            )
        except ValueError as exc:
            raise MmtError(f"{ctx}: {exc}") from exc
    raise MmtError(f"sections[{idx}]: 未知段类型 {stype!r}"
                   "（支持 uniform/hstep/iris）")


def parse_sections(sections: list[Any], defaults: dict[str, Any]) -> list[Any]:
    """段表 JSON 列表 → core 构件列表（空表显式报错）。"""
    if not isinstance(sections, list) or not sections:
        raise MmtError("sections 必须为非空列表")
    return [section_from_json(s, defaults, i) for i, s in enumerate(sections)]


def mode_policy_from_json(spec: dict[str, Any] | None) -> ModePolicy:
    """mode_policy JSON → core.ModePolicy（未知键忽略宽容、非法值显式报错）。"""
    spec = dict(spec or {})
    override_raw = spec.get("n_modes_override")
    override: dict[int, int] | None = None
    if override_raw is not None:
        if not isinstance(override_raw, dict):
            raise MmtError("mode_policy.n_modes_override 必须为对象")
        override = {int(k): int(v) for k, v in override_raw.items()}
    try:
        return ModePolicy(
            n_modes_ref=int(spec.get("n_modes_ref", 15)),
            n_modes_max=int(spec.get("n_modes_max", 120)),
            n_doublings_max=int(spec.get("n_doublings_max", 3)),
            convergence_tol=float(spec.get("convergence_tol", 0.01)),
            evanescent_decay_min=float(spec.get("evanescent_decay_min", 3.0)),
            strict_truncation_guard=bool(spec.get("strict_truncation_guard", True)),
            n_modes_override=override,
            ratio_tolerance=float(spec.get("ratio_tolerance", 0.25)),
        )
    except ValueError as exc:
        raise MmtError(f"mode_policy: {exc}") from exc


def freqs_from_json(payload: dict[str, Any], config: EMSolverConfig) -> np.ndarray:
    """频网解析：显式 freqs_ghz 优先，缺省 freq_start/stop/n_freq → 均匀网格。

    频点必须为正且严格递增（Touchstone/β 分支契约；负例显式报错）。
    """
    fs = payload.get("freqs_ghz")
    if fs is not None:
        if not isinstance(fs, list) or len(fs) < 2:
            raise MmtError("freqs_ghz 必须为 ≥2 点列表")
        freqs = np.asarray([float(f) for f in fs], dtype=float)
    else:
        n = int(payload.get("n_freq", 41))
        lo, hi = payload.get("freq_start_ghz"), payload.get("freq_stop_ghz")
        if lo is None or hi is None:
            lo, hi = config.freq_range_ghz
        freqs = np.linspace(float(lo), float(hi), n)
    if np.any(~np.isfinite(freqs)) or np.any(freqs <= 0):
        raise MmtError(f"频点必须为正有限数: {freqs[:5].tolist()}")
    if np.any(np.diff(freqs) <= 0):
        raise MmtError(f"频点网格须严格递增: {freqs[:5].tolist()}")
    return freqs * 1e9


def cplx_to_json(v: complex | np.complexfloating[Any, Any]) -> list[float] | None:
    """复数 → [re, im]；非有限（NaN undetermined）→ None（不外推，criteria §0）。"""
    c = complex(v)
    if not (math.isfinite(c.real) and math.isfinite(c.imag)):
        return None
    return [c.real, c.imag]


def _normalized_sections_echo(chain: list[Any]) -> list[dict[str, Any]]:
    """解析后构件 → mm 口径回显（meta 用；与输入 JSON 同构，实测值为准）。"""
    out: list[dict[str, Any]] = []
    for item in chain:
        if isinstance(item, UniformSection):
            out.append({"type": "uniform", "a_mm": item.wg.a * 1e3,
                        "b_mm": item.wg.b * 1e3, "length_mm": item.length_m * 1e3,
                        "eps_r": item.wg.eps_r, "tan_d": item.wg.tan_d,
                        "sigma_s_m": item.wg.sigma})
        elif isinstance(item, HStepJunction):
            x0, w, off_l, off_r = item.resolved()
            out.append({"type": "hstep",
                        "a_left_mm": item.wg_left.a * 1e3,
                        "b_left_mm": item.wg_left.b * 1e3,
                        "a_right_mm": item.wg_right.a * 1e3,
                        "b_right_mm": item.wg_right.b * 1e3,
                        "x0_mm": x0 * 1e3, "aperture_mm": w * 1e3,
                        "offset_left_mm": off_l * 1e3,
                        "offset_right_mm": off_r * 1e3})
        elif isinstance(item, InductiveIris):
            out.append({"type": "iris", "a_mm": item.wg.a * 1e3,
                        "b_mm": item.wg.b * 1e3,
                        "aperture_mm": item.aperture_m * 1e3,
                        "thickness_mm": item.thickness_m * 1e3})
    return out


# canonicalize_chain 已删除（P1 core 根治后清理，followUp 闭合）：
# 曾为 solve_chain ``id()`` 反查 guide 表的适配器侧权宜（iris 预展开 + 值相等
# Waveguide 归一实例）。core/rwg_mmt 现按值语义去重+按值反查（frozen dataclass
# 值哈希，_guide_list 契约），JSON 段表逐段新造实例直连可解；iris 展开本就由
# core._guide_list 内建。行为等价钉：tests/unit/test_mmt_adapter.py
# ::TestSectionParsing::test_json_chain_value_equal_instances_solve。


# --------------------------------------------------------------------------- #
# 适配器
# --------------------------------------------------------------------------- #


class MmtAdapter(EMSolverAdapter):
    """RWG/SIW 解析模基 MMT（GSM）适配器（秒级段表求解，openEMS 同构产物）。"""

    # A5 能力声明（如实，2026-09-24 逐条核对；模匹配通道不虚报 EM 仿真面）：
    #   - 端口：TE10 模端口为方法内建（非 wave/lumped 边界端口）→ 两 False；
    #   - 材料：波导壁 PEC（sigma=None）或有限电导（sigma 微扰损耗）、
    #     填充 εr/tanδ（无耗/有耗介质）；
    #   - Touchstone：export_touchstone 有实现（skrf，z0=z0_ref）→ True；
    #   - 场导出/收敛报告（×2 门是求解内禀量非引擎报告）/optimetrics/
    #     nf2ff/SAR：无对应实现 → False（无辐射族，模匹配不产方向图）；
    #   - dimension："2d"（H 面 TE_{m0} 单族横截面模匹配）；
    #   - 模板：段表直连无模板机制 → ("chain",)；license：纯仓内 → False；
    #   - availability_gate：""（零 exe 零配置，is_available 恒 True）。
    CAPABILITIES: ClassVar[SolverCapabilities] = SolverCapabilities(
        solver_type="mmt",
        supports_wave_port=False,
        supports_lumped_port=False,
        supports_field_export=False,
        supports_convergence_report=False,
        supports_touchstone_export=True,
        supports_headless_solve=True,
        supports_optimetrics=False,
        dimension="2d",
        material_models=("pec", "lossless_dielectric", "lossy_dielectric"),
        parallel_backends=(),
        supports_sar=False,
        supports_nf2ff=False,
        supports_lumped_elements=False,
        supported_templates=SUPPORTED_TEMPLATES,
        requires_license=False,
        availability_gate="",
    )

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)
        self._chain: list[Any] = []
        self._freqs_hz: np.ndarray | None = None
        self._policy: ModePolicy | None = None
        self._z0_ref: float = 50.0
        self._sections_echo: list[dict[str, Any]] = []
        self._network: Any | None = None  # skrf.Network（determined 行，z0_ref 基）
        self._last_meta: dict[str, Any] | None = None
        self._last_s_full: np.ndarray | None = None  # 全网格 50Ω S（undetermined=NaN）
        self._last_error: str | None = None

    # ── 生命周期（纯仓内算法：恒可用）────────────────────────────────────────

    def connect(self) -> bool:
        self._connected = True
        return True

    def is_available(self) -> bool:
        return True  # 纯 numpy 零外部进程零 license，无可用性门

    # ── 配置生成 ────────────────────────────────────────────────────────────

    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        """解析 JSON 段表（mm 口径）到 core 构件（不落盘；solve 时消费）。

        geometry 契约（criteria §0）：
            sections: [uniform|hstep|iris, ...]   —— 必填，mm 口径三型
            freqs_ghz: [f1, ...]                  —— ≥2 点严格递增（或
                freq_start_ghz/freq_stop_ghz/n_freq 缺省均匀网格）
            eps_r / tan_d / sigma_s_m             —— 可选顶层材质缺省（段内覆盖）
            mode_policy: {n_modes_ref, ...}       —— 可选（core.ModePolicy 同名键）
            z0_ref: float                         —— 可选端口参考阻抗（缺省 50）
        """
        self._last_error = None
        try:
            if not isinstance(geometry, dict):
                raise MmtError("geometry 必须为对象")
            defaults = {"eps_r": geometry.get("eps_r", 1.0),
                        "tan_d": geometry.get("tan_d", 0.0),
                        "sigma_s_m": geometry.get("sigma_s_m")}
            chain = parse_sections(geometry.get("sections") or [], defaults)
            freqs = freqs_from_json(geometry, self._config)
            policy = mode_policy_from_json(geometry.get("mode_policy"))
            z0_ref = float(geometry.get("z0_ref", 50.0))
            if not (math.isfinite(z0_ref) and z0_ref > 0.0):
                raise MmtError(f"z0_ref 必须为正实数，得到 {z0_ref!r}")
        except (MmtError, ValueError) as exc:
            self._last_error = f"MMT 段表解析失败: {exc}"
            logger.error("%s", self._last_error)
            return False
        self._sections_echo = _normalized_sections_echo(chain)  # 输入契约回显（iris 保持 iris 形态）
        self._chain = chain  # 求解直连 core（值语义单源在 core._guide_list，无适配器侧规范化）
        self._freqs_hz = freqs
        self._policy = policy
        self._z0_ref = z0_ref
        return True

    # ── 求解与产物 ──────────────────────────────────────────────────────────

    def solve(self) -> EMSolverResult:
        """段表 → solve_chain（TE10 模阻抗基）→ renormalize z0_ref → 产物落盘。

        undetermined 频点：s_params 全网格保留 NaN 行（如实），Touchstone/
        sparams.csv 只写 determined 行，meta 列 undetermined_freqs_ghz。
        """
        if not self._chain or self._freqs_hz is None or self._policy is None:
            return EMSolverResult(success=False,
                                  message="build_geometry() 未解析段表")
        t0 = time.time()
        try:
            res = solve_chain(self._chain, self._freqs_hz, self._policy)
        except ValueError as exc:
            return EMSolverResult(success=False,
                                  message=f"MMT solve_chain 失败: {exc}")
        freqs_hz = res.freqs_hz
        s50 = np.full((*freqs_hz.shape, 2, 2), np.nan + 1j * np.nan, dtype=complex)
        for i in range(freqs_hz.size):
            if res.undetermined[i]:
                continue  # 近截止/过传：如实 NaN 不外推（criteria §0）
            z0_from = (float(np.real(res.z_te_ports[i, 0])),
                       float(np.real(res.z_te_ports[i, 1])))
            if min(z0_from) <= 0.0:
                return EMSolverResult(
                    success=False, wall_time_s=round(time.time() - t0, 3),
                    message=f"端口 TE10 模阻抗非正实 @f={freqs_hz[i] / 1e9:g}GHz"
                            "（determined 点不应出现，契约破坏）")
            s50[i] = renormalize_2port(res.s2x2[i], z0_from,
                                       (self._z0_ref, self._z0_ref))
        wall = round(time.time() - t0, 3)
        det = ~res.undetermined
        self._last_s_full = s50
        if det.any():
            import skrf

            self._network = skrf.Network(
                frequency=skrf.Frequency.from_f(freqs_hz[det], unit="Hz"),
                s=s50[det], z0=self._z0_ref,
            )
        else:
            self._network = None
        workdir = Path(self._config.working_dir or ".")
        meta = self._write_products(workdir, res, s50, wall)
        self._last_meta = meta
        message = (f"MMT solve ok（{int(det.sum())}/{freqs_hz.size} 频点 determined，"
                   f"converged={res.converged}）；{_ABSOLUTE_S_NOTE}")
        return EMSolverResult(
            success=True, freq_ghz=freqs_hz / 1e9, s_params=s50,
            field_data={
                "z_pv_ports": res.z_pv_ports,
                "beta_te10_ports": res.beta_te10_ports,
                "undetermined": res.undetermined,
                "converged": res.converged,
                "n_modes": list(res.n_modes),
                "warnings": list(res.warnings),
            },
            convergence_iterations=0,  # 无引擎迭代收敛报告概念（×2 门见 field_data.converged）
            wall_time_s=wall, message=message,
        )

    def _write_products(self, workdir: Path, res: Any, s50: np.ndarray,
                        wall: float) -> dict[str, Any]:
        """openEMS 同构产物落盘（best-effort 观测面不阻塞主路，#105）：
        sparams.csv（5 列掩码契约）+ mmt.s2p（skrf）+ mmt_meta.json。"""
        workdir.mkdir(parents=True, exist_ok=True)
        det = ~res.undetermined
        freqs_hz = res.freqs_hz
        und_ghz = [float(f) / 1e9 for f in freqs_hz[res.undetermined]]
        # sparams.csv：openEMS 5 列 schema，只写 determined 行
        try:
            with open(workdir / _SPARAMS_CSV_NAME, "w", newline="",
                      encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(_SPARAMS_CSV_HEADER)
                for i in np.flatnonzero(det):
                    w.writerow([freqs_hz[i], s50[i, 0, 0].real, s50[i, 0, 0].imag,
                                s50[i, 1, 0].real, s50[i, 1, 0].imag])
        except OSError as exc:
            logger.warning("sparams.csv 写出失败（S 主路保留）: %s", exc)
        # Touchstone：determined 行全 2×2（skrf ri 形式）
        if self._network is not None:
            try:
                self._network.write_touchstone(str(workdir / _TOUCHSTONE_NAME),
                                               form="ri")
            except Exception as exc:  # 观测性面：TS 失败不回滚 CSV/meta（#105）
                logger.warning("Touchstone 导出失败（CSV/meta 保留）: %s", exc)
        meta = {
            "schema": "rfauto-mmt/v1",
            "solver": "mmt",
            "adapter": "mmt",
            "sections": self._sections_echo,
            "freqs_ghz": [float(f) / 1e9 for f in freqs_hz],
            "z0_ref": self._z0_ref,
            "mode_policy": {
                "n_modes_ref": self._policy.n_modes_ref,
                "n_modes_max": self._policy.n_modes_max,
                "n_doublings_max": self._policy.n_doublings_max,
                "convergence_tol": self._policy.convergence_tol,
                "strict_truncation_guard": self._policy.strict_truncation_guard,
            },
            "n_modes": list(res.n_modes),
            "n_modes_tested": [list(lv) for lv in res.n_modes_tested],
            "converged": bool(res.converged),
            "n_determined": int(det.sum()),
            "n_undetermined": int(res.undetermined.sum()),
            "undetermined_freqs_ghz": und_ghz,
            "s11": [cplx_to_json(v) for v in s50[:, 0, 0]],
            "s21": [cplx_to_json(v) for v in s50[:, 1, 0]],
            "s12": [cplx_to_json(v) for v in s50[:, 0, 1]],
            "s22": [cplx_to_json(v) for v in s50[:, 1, 1]],
            "z_pv_ports": [[cplx_to_json(res.z_pv_ports[i, 0]),
                            cplx_to_json(res.z_pv_ports[i, 1])]
                           for i in range(freqs_hz.size)],
            "beta_te10_ports": [[cplx_to_json(res.beta_te10_ports[i, 0]),
                                 cplx_to_json(res.beta_te10_ports[i, 1])]
                                for i in range(freqs_hz.size)],
            "warnings": list(res.warnings),
            "wall_time_s": wall,
            "port_basis_note": _PORT_BASIS_NOTE,
            "absolute_s_note": _ABSOLUTE_S_NOTE,
        }
        try:
            (workdir / _META_NAME).write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("mmt_meta.json 写出失败: %s", exc)
        return meta

    # ── 读取面 ──────────────────────────────────────────────────────────────

    def get_sparams(self) -> tuple[np.ndarray, np.ndarray]:
        """S 参数（EMSolver 面契约：(freq_ghz, s(n,2,2))；50Ω 基，undetermined
        行=NaN 如实；未求解则先 solve）。"""
        if self._last_s_full is None or self._freqs_hz is None:
            result = self.solve()
            if not result.success:
                raise RuntimeError(result.message)
        return self._freqs_hz / 1e9, self._last_s_full

    def get_meta(self) -> dict[str, Any] | None:
        """最近一次 solve 的 meta（mmt_meta.json 内容；未求解 None）。"""
        return self._last_meta

    def export_touchstone(self, path: str | Path, contract: Any = None) -> Path:
        """导出最近一次求解的 Touchstone（determined 行，z0_ref 基）。"""
        if self._network is None:
            raise RuntimeError("尚未求解，请先调用 solve()")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._network.write_touchstone(str(path), form="ri")
        return path

    def close(self) -> None:
        self._connected = False
        self._chain = []
        self._freqs_hz = None
        self._policy = None
        self._network = None
        self._last_meta = None
        self._last_s_full = None

    # ── 6g 产物视图协议 ────────────────────────────────────────────────────

    def visualizations(self) -> list[dict[str, Any]]:
        workdir = self._config.working_dir or "."
        return [
            {"kind": "sparams",
             "spec": {"file": str(Path(workdir) / _SPARAMS_CSV_NAME)}},
            {"kind": "circuit",
             "spec": {"file": str(Path(workdir) / _META_NAME),
                      "format": "mmt-chain-json"}},
        ]

    def supported_output_formats(self) -> list[str]:
        return ["touchstone", "csv"]


# --------------------------------------------------------------------------- #
# 注册（EMSolverType.MMT 已由本批合入 em_solver_base；导入即注册，同
# comsol/elmer/ngsolve 先例。注册失败不阻塞 import（#105 观测性纪律）。
# --------------------------------------------------------------------------- #

def register_mmt(registry: Any = None) -> None:
    """注册到全局/指定 EMSolverRegistry（导入即注册模式）。"""
    from rfauto.adapters.em_solver_base import EMSolverType, get_global_registry

    target = registry if registry is not None else get_global_registry()
    target.register(EMSolverType.MMT, MmtAdapter)


try:  # 注册失败只 warning 不阻塞 import（#105）
    register_mmt()
except Exception:  # pragma: no cover —— 防御性（注册表面异常）
    logger.warning("MmtAdapter 全局注册失败", exc_info=True)
