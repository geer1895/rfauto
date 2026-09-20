"""Q3D 寄生提取通道适配器（PCB 无源/互连 RLC，AEDT/pyaedt）。

定位：Q3D/SIwave 寄生提取
首案例——**直条微带走线 RLC 提取 + 闭式锚对照**；本项落地 Q3D 主路，
SIwave EDB 全板链路为后续项（如实不虚报）。

通道纪律：
- **延迟 import**：`ansys.aedt.core` 只在 adapter 方法内引入（延迟 import 纪律，
  同 icepak_adapter）——未装 AEDT/pyaedt 的环境可安全 import 本模块；
- **pyaedt API 名（本地 pyaedt-main 实证，不凭想象）**：
  `ansys.aedt.core.Q3d(project, design, version, non_graphical, new_desktop)`、
  `modeler.create_box`、`assign_net(objects, net_name, net_type="Signal"/"Ground")`
  （q3d.py:1865，底层 AssignSignalNet/AssignGroundNet）、
  `source(obj, direction, name, net_name)` / `sink(...)`（q3d.py:1917/1971，
  direction 0..5 = 轴 min×3 + 轴 max×3，faces 由 _get_faceid_on_axis 选）、
  `create_setup(name)`（SetupQ3D，ac_rl_enabled/capacitance_enabled 开关）、
  `analyze(setup)`、`export_matrix_data(file_name, problem_type="AC RL"/"C",
  r_unit, l_unit, c_unit, freq, ...)`（q3d.py:547，底层 oDesign.ExportMatrixData）；
- **版本钉扎**：AEDT 2025.1（与 hfss/icepak 同池；license 探测
  q3d_desktop=exists + Q3D.dll/Q3DCOMENGINE.exe 齐）；
- **闭式锚（裁判=独立来源 #118）**：提取的每长度 L/C 对
  core/parasitic.interconnect_rlc_anchor（传输线恒等式 L=Z0·√εeff/c0、
  C=√εeff/(Z0·c0)，Z0/εeff=skrf MLine HJ）做门判 ≤5%；R（DC/AC 参考）
  只报告不判门（趋肤/粗糙度模型单向偏差，如实声明）；
- **真机实证**：connect→几何→网络→source/sink→setup→
  solve（58s）→save 全链通；但本机 AEDT 2025.1（无 Service Pack，
  pyaedt 连接时警告缺 SP）gRPC 桥的**矩阵导出族命令全部失败**——
  export_matrix_data / 裸 oDesign.ExportMatrixData（6 组参数×图形/非图形）、
  oanalysis.ExportCircuit（WElement/Spice）、AlphaNumericMatrix（返回
  None）逐一实证（探针日志与 case_result.json 存档）。solve 本身成功（RL/CG/DC RL 三张 Table 均出解），
  数值取不出的阻塞点在工具桥不在建模；装 SP/升级 AEDT 后按本适配器
  原路径复跑即可；
- 显式单位字符串（#218 同法）；非法输入显式 ValueError；失败一律
  success=False + 明确 message（best-effort #105），不抛异常、不伪造结果。
"""

from __future__ import annotations

import logging
import math
import re
import time
from pathlib import Path
from typing import Any, ClassVar

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    EMSolverType,
    SolverCapabilities,
    get_global_registry,
)
from rfauto.core.parasitic import interconnect_rlc_anchor

logger = logging.getLogger(__name__)

#: 首案例模板名（直条微带走线 RLC 提取）
TEMPLATE_PARASITIC_MSTRIP = "pcb_interconnect_microstrip"

#: AEDT 版本钉扎（本机 v251 = 2025.1，hfss/icepak 同池，#191 口径）
DEFAULT_AEDT_VERSION = "2025.1"

#: L/C 每长度锚真机验收门（相对偏差；HJ 闭式 vs Q3D 准静态典型 ~1-3%）
ANCHOR_TOLERANCE = 0.05

#: 默认提取参数（RO4350B 50Ω 量级直条微带：50.6Ω 锚；SI 内核 mm 几何）
TRACE_DEFAULTS: dict[str, float] = {
    "trace_len_mm": 50.0,
    "trace_w_mm": 1.09,
    "trace_t_mm": 0.035,
    "sub_h_mm": 0.508,
    "sub_eps_r": 3.66,
    "sub_tan_d": 0.0037,
    "sub_margin_mm": 10.0,
    "gnd_t_mm": 0.035,
    "solution_freq_ghz": 1.0,
    "max_passes": 10,
}

VALID_PROBLEM_TYPES = ("C", "AC RL", "DC RL")

#: 矩阵种类头（如 `"L"(nH)` / `R(ohm)`）；白名单外（Matrix(...) 包裹行等）忽略
_MATRIX_KIND_RE = re.compile(r'^\s*"?([A-Za-z][A-Za-z0-9]*)"?\s*\(([^)]*)\)\s*$')
_ACCEPTED_MATRIX_KINDS = frozenset({"L", "C", "R", "G", "Rdc", "Rac", "Rs"})


def normalize_trace_params(params: dict[str, Any] | None) -> dict[str, float]:
    """提取参数规范化：补默认、转 float、正数/整数校验（不静默兜底）。"""
    spec = dict(TRACE_DEFAULTS)
    for key, value in (params or {}).items():
        if key not in spec:
            raise ValueError(f"未知提取参数 {key!r}（允许: {sorted(spec)}）")
        spec[key] = value
    try:
        max_passes = int(spec["max_passes"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"max_passes 必须是正整数，得到 {spec['max_passes']!r}") from exc
    if max_passes < 1:
        raise ValueError(f"max_passes 必须 >=1，得到 {max_passes}")
    spec["max_passes"] = max_passes
    for key, value in spec.items():
        if key == "max_passes":
            continue
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"提取参数 {key} 必须是实数，得到 {value!r}") from exc
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"提取参数 {key} 必须为正数，得到 {value!r}")
        spec[key] = value
    return spec


def anchor_for_spec(spec: dict[str, float]) -> dict[str, Any]:
    """按（规范化后）提取参数给 RLC 闭式锚（core 单一实现）。"""
    return interconnect_rlc_anchor(
        length_mm=spec["trace_len_mm"],
        w_mm=spec["trace_w_mm"],
        t_mm=spec["trace_t_mm"],
        h_mm=spec["sub_h_mm"],
        eps_r=spec["sub_eps_r"],
        freq_ghz=spec["solution_freq_ghz"],
        loss_tangent=spec["sub_tan_d"],
    )


def pyaedt_installed() -> bool:
    """ansys.aedt.core 可 import 即认为 SDK 面 OK（license 由真机 connect 决定）。"""
    try:
        import ansys.aedt.core  # noqa: F401
    except Exception:
        return False
    return True


# ─── 矩阵导出解析（AEDT ExportMatrixData 文本，容错式）────────────────────────

def _strip_quotes(token: str) -> str:
    return token.strip().strip('"').strip("'")


def _is_number(token: str) -> bool:
    try:
        float(token)
        return True
    except ValueError:
        return False


def _parse_matrix_export(text: str) -> dict[str, dict[str, Any]]:
    """解析 Q3D export_matrix_data 导出文本 → {kind: {unit, names, elements}}。

    容错式（导出格式随 AEDT 版本/选项略有差异）：扫描行流，
    - 矩阵种类头：``"L"(nH)`` / ``R(ohm)`` 形态（白名单 L/C/R/G/Rdc/Rac/Rs，
      跳过 `Matrix("Original")` 等包裹行）；
    - 列名行：全为带引号 token（无数值）→ 当前矩阵的 net 名表；
    - 数值行：首 token 为行名，其余为浮点 → elements[(行名, 列名)]。
    空行/注释行（#/%/Design Name 等）跳过。
    """
    out: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "%", ";")):
            continue
        lowered = line.lower()
        if lowered.startswith(("design name", "begin", "end matrix", "end of")):
            continue
        match = _MATRIX_KIND_RE.match(line)
        if match and match.group(1) in _ACCEPTED_MATRIX_KINDS:
            current = {
                "unit": _strip_quotes(match.group(2)),
                "names": [],
                "elements": {},
            }
            out[match.group(1)] = current
            continue
        if current is None:
            continue
        tokens = [_strip_quotes(tok) for tok in line.split()]
        if not tokens:
            continue
        numeric_tail = [tok for tok in tokens[1:] if _is_number(tok)]
        if not numeric_tail:
            # 全为名字 → 列名行
            current["names"] = tokens
            continue
        row_name = tokens[0]
        for col_name, value in zip(current["names"], numeric_tail, strict=False):
            try:
                current["elements"][(row_name, col_name)] = float(value)
            except ValueError:
                continue
    return out


def _diagonal_total(
    parsed: dict[str, dict[str, Any]],
    kind: str,
    net_name: str,
) -> float | None:
    """取 kind 矩阵中信号 net 的对角元（未约减时退化为唯一起始 net 对角元）。"""
    section = parsed.get(kind)
    if section is None:
        return None
    names = section.get("names") or []
    elements = section["elements"]
    if net_name in names:
        return elements.get((net_name, net_name))
    if len(names) == 1:
        return elements.get((names[0], names[0]))
    return None


class Q3dAdapter(EMSolverAdapter):
    """Q3D 寄生提取通道适配器（本项：直条微带走线 RLC 首案例）。

    用法::

        cfg = EMSolverConfig(solver_type=EMSolverType.Q3D,
                             working_dir="runs/wp44b_q3d")
        solver = Q3dAdapter(cfg)
        solver.build_geometry({})      # 默认 RO4350B 50Ω 直条微带
        result = solver.solve()        # 真机提取 + 闭式锚对照
        result.field_data["verdict"]   # L/C 每长度 ≤5% 门
    """

    #: A5 能力声明（如实，逐条对代码；Q3D 产出 RLC 矩阵而非 S 参数/场）：
    #:   - 端口/S 参数：寄生通道不产 S 参数 → 全 False；
    #:   - 场导出/收敛报告：本适配器未实现 → False（不虚报）；
    #:   - Touchstone：Q3D 原生导出 RLC 矩阵文本 → False；
    #:   - headless：non_graphical gRPC → True；license：AEDT 池 → True。
    CAPABILITIES: ClassVar[SolverCapabilities] = SolverCapabilities(
        solver_type="q3d",
        supports_wave_port=False,
        supports_lumped_port=False,
        supports_field_export=False,
        supports_convergence_report=False,
        supports_touchstone_export=False,
        supports_headless_solve=True,
        supports_optimetrics=False,
        dimension="3d",
        material_models=("pec", "lossless_dielectric"),
        parallel_backends=(),
        supports_sar=False,
        supports_nf2ff=False,
        supports_lumped_elements=False,
        supported_templates=(TEMPLATE_PARASITIC_MSTRIP,),
        requires_license=True,
        availability_gate="pyaedt",
    )

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)
        extra = config.extra_params or {}
        self._desktop_version: str = str(extra.get("desktop_version",
                                                   DEFAULT_AEDT_VERSION))
        self._save_project: bool = bool(extra.get("save_project", True))
        self._q3d: Any = None
        self._spec: dict[str, float] | None = None
        self._project_path: Path | None = None
        self._built = False
        self._last_message = ""
        self._setup_name = "rfauto_q3d_setup"

    # ── 生命周期 ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """pyaedt SDK 可 import 即 True；license/桌面级检查在 connect 真做。"""
        return pyaedt_installed()

    def connect(self) -> bool:
        """启动/连接 AEDT Desktop 并创建 Q3D Extractor 设计（non_graphical）。

        真机实证（探针脚本 + 三轮
        case_result.json）：``Q3d(project="<不存在路径>")`` 会走
        ``oProject.Rename``，在 AEDT 2025.1 gRPC 下**确定性失败**
        （非 #191 瞬态抖动，3 次整轮重试同错）——改为 project=None
        走默认新建工程（无 Rename），connect 后 save_project 落盘到
        目标路径（save ok 0.2s 实测）。
        失败返回 False（best-effort #105），不抛异常。
        """
        if self._q3d is not None:
            return True
        if not pyaedt_installed():
            self._last_message = "pyaedt 不可用：无法 import ansys.aedt.core"
            logger.warning(self._last_message)
            return False
        workdir = self._resolve_working_dir()
        self._project_path = Path(workdir) / "wp44b_parasitic.aedt"
        try:
            from ansys.aedt.core import Q3d

            self._q3d = Q3d(
                project=None,
                design="rfauto_q3d",
                version=self._desktop_version,
                non_graphical=True,
                new_desktop=True,
            )
            self._q3d.save_project(str(self._project_path))
            self._connected = True
            return True
        except Exception as exc:
            self._last_message = f"连接 AEDT/Q3D 失败: {exc}"
            logger.warning(self._last_message)
            self._q3d = None
            self._connected = False
            return False

    def _resolve_working_dir(self) -> Path:
        raw = self._config.working_dir or "runs/wp44b_q3d"
        workdir = Path(raw).resolve()  # 绝对路径（SaveAs 相对路径真机实测失败）
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir

    def use_design(self, design_name: str) -> bool:
        """在当前工程内插入并切换到新设计（多工况逐设计隔离）。

        失败返回 False（best-effort #105）。
        """
        if self._q3d is None:
            self._last_message = "未连接：先 connect()"
            return False
        try:
            self._q3d.insert_design(design_name)
            return True
        except Exception as exc:
            self._last_message = f"insert_design({design_name!r}) 失败: {exc}"
            logger.warning(self._last_message)
            return False

    # ── 几何 / 网络 / 激励 ──────────────────────────────────────────────────

    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        """构建直条微带提取模型（介质板 + 参考地 + 铜走线条，显式单位字符串）。

        参数经 normalize_trace_params 校验。调用顺序：connect → 本方法
        → solve。层叠（z 向）：gnd（pec，z∈[0,gnd_t]）→ 介质板
        （z∈[gnd_t, gnd_t+h]）→ 走线条（copper，贴介质板顶面）；
        走线沿 x 铺设，source/sink 分别在 ±x 端面（direction 0/3）。
        """
        if self._q3d is None:
            self._last_message = "未连接：先 connect()"
            return False
        try:
            spec = normalize_trace_params(geometry)
        except ValueError as exc:
            self._last_message = str(exc)
            return False

        mm = lambda v: f"{v}mm"  # noqa: E731 —— 几何一律显式单位（#218）
        try:
            modeler = self._q3d.modeler
            sub_l = spec["trace_len_mm"] + 2.0 * spec["sub_margin_mm"]
            sub_w = spec["trace_w_mm"] + 2.0 * spec["sub_margin_mm"]
            # 参考地（z∈[0, gnd_t]）
            modeler.create_box(
                origin=["0mm", "0mm", "0mm"],
                sizes=[mm(sub_l), mm(sub_w), mm(spec["gnd_t_mm"])],
                name="rfauto_gnd",
                material="pec",
            )
            # 介质板（z∈[gnd_t, gnd_t+h]）
            modeler.create_box(
                origin=["0mm", "0mm", mm(spec["gnd_t_mm"])],
                sizes=[mm(sub_l), mm(sub_w), mm(spec["sub_h_mm"])],
                name="rfauto_sub",
                material=self._make_dielectric(spec),
            )
            # 走线条（沿 x，贴介质板顶面）
            x0 = (sub_l - spec["trace_len_mm"]) / 2.0
            y0 = (sub_w - spec["trace_w_mm"]) / 2.0
            z_top = spec["gnd_t_mm"] + spec["sub_h_mm"]
            modeler.create_box(
                origin=[mm(x0), mm(y0), mm(z_top)],
                sizes=[mm(spec["trace_len_mm"]), mm(spec["trace_w_mm"]),
                       mm(spec["trace_t_mm"])],
                name="rfauto_trace",
                material="copper",
            )
            # 网络指派：走线=Signal，地=Ground（Q3D 自动以 Ground 为参考）
            if not self._assign_nets():
                return False
        except Exception as exc:
            self._last_message = f"构建几何失败: {exc}"
            logger.warning(self._last_message)
            return False
        self._spec = spec
        self._built = True
        return True

    def _make_dielectric(self, spec: dict[str, float]) -> str:
        """确保介质材料存在并返回名字（幂等；已有同名则改介电常数）。"""
        name = "rfauto_sub_mat"
        materials = self._q3d.materials
        props = {
            "permittivity": spec["sub_eps_r"],
            "dielectric_loss_tangent": spec["sub_tan_d"],
        }
        if name not in materials.material_keys:
            materials.add_material(name, properties=props)
        else:
            materials.material_keys[name].permittivity = props["permittivity"]
            materials.material_keys[name].dielectric_loss_tangent = \
                props["dielectric_loss_tangent"]
        return name

    def _assign_nets(self) -> bool:
        """信号/地网络 + source/sink（±x 端面，direction 0/3）。"""
        net_trace = self._q3d.assign_net(
            "rfauto_trace", net_name="trace", net_type="Signal")
        net_gnd = self._q3d.assign_net(
            "rfauto_gnd", net_name="gnd", net_type="Ground")
        if net_trace is None or net_gnd is None:
            self._last_message = "assign_net 失败（见返回值）"
            return False
        src = self._q3d.source(
            "rfauto_trace", direction=0, name="rfauto_src", net_name="trace")
        snk = self._q3d.sink(
            "rfauto_trace", direction=3, name="rfauto_snk", net_name="trace")
        if src is None or snk is None:
            self._last_message = "source/sink 创建失败"
            return False
        return True

    # ── 求解 / 提取 ─────────────────────────────────────────────────────────

    def solve(self, timeout_s: float | None = None) -> EMSolverResult:
        """提取求解 → RLC 矩阵导出 → 闭式锚对照（L/C 每长度门 ≤5%）。

        流程：create_setup（AC RL + C 开）→ analyze → export_matrix_data
        （"AC RL" 与 "C" 两份）→ 解析对角元 → 每长度换算 → 锚判。
        失败一律 success=False + 明确 message（best-effort #105）。
        """
        started = time.perf_counter()
        if self._q3d is None or not self._built or self._spec is None:
            return EMSolverResult(success=False,
                                  message="未连接或未建模：先 connect()+build_geometry()")
        spec = self._spec
        workdir = self._resolve_working_dir()
        rl_path = workdir / "matrix_acrl.txt"
        c_path = workdir / "matrix_c.txt"
        applied_props: list[str] = []
        try:
            setup = self._q3d.create_setup(self._setup_name)
            # AC RL / C 求解开关（SetupQ3D 文档化属性）
            setup.ac_rl_enabled = True
            setup.capacitance_enabled = True
            # 自适应频率/最大迭代次数：prop 键随版本差异，best-effort 不阻塞主路径
            for key, value in (("AdaptiveFreq",
                                f"{spec['solution_freq_ghz']}GHz"),
                               ("MaxPass", int(spec["max_passes"]))):
                try:
                    setup.props[key] = value
                    applied_props.append(key)
                except Exception as exc:  # pragma: no cover - 版本差异兜底
                    logger.warning("setup.props[%r] 未生效（忽略）: %s", key, exc)
            self._q3d.analyze(self._setup_name)
            ok_rl = self._q3d.export_matrix_data(
                file_name=str(rl_path), problem_type="AC RL",
                r_unit="ohm", l_unit="nH", c_unit="pF",
                freq=f"{spec['solution_freq_ghz']}GHz")
            ok_c = self._q3d.export_matrix_data(
                file_name=str(c_path), problem_type="C",
                r_unit="ohm", l_unit="nH", c_unit="pF",
                freq=f"{spec['solution_freq_ghz']}GHz")
            if not ok_rl or not ok_c:
                return EMSolverResult(
                    success=False, wall_time_s=time.perf_counter() - started,
                    message=(f"矩阵导出失败（AC RL={ok_rl}, C={ok_c}）——"
                             f"analyze 已完成；本机 2025.1 gRPC 导出族命令"
                             f"阻断见模块 docstring 真机实证"))
        except Exception as exc:
            return EMSolverResult(success=False,
                                  wall_time_s=time.perf_counter() - started,
                                  message=f"Q3D 求解失败: {exc}")
        wall = time.perf_counter() - started

        parsed_rl = _parse_matrix_export(rl_path.read_text(encoding="utf-8",
                                                           errors="replace"))
        parsed_c = _parse_matrix_export(c_path.read_text(encoding="utf-8",
                                                         errors="replace"))
        l_total = _diagonal_total(parsed_rl, "L", "trace")
        r_total = _diagonal_total(parsed_rl, "R", "trace")
        c_total = _diagonal_total(parsed_c, "C", "trace")
        if l_total is None or c_total is None:
            return EMSolverResult(
                success=False, wall_time_s=wall,
                message=(f"RLC 提取失败：L={l_total!r}, C={c_total!r}"
                         f"（矩阵解析，见 {rl_path.name}/{c_path.name}）"))
        length = spec["trace_len_mm"]
        anchor = anchor_for_spec(spec)
        l_per_mm = l_total / length
        c_per_mm = c_total / length
        l_dev = abs(l_per_mm - anchor["l_nh_per_mm"]) / anchor["l_nh_per_mm"]
        c_dev = abs(c_per_mm - anchor["c_pf_per_mm"]) / anchor["c_pf_per_mm"]
        verdict = {
            "l_extracted_nh_per_mm": l_per_mm,
            "c_extracted_pf_per_mm": c_per_mm,
            "l_anchor_nh_per_mm": anchor["l_nh_per_mm"],
            "c_anchor_pf_per_mm": anchor["c_pf_per_mm"],
            "l_rel_dev": l_dev,
            "c_rel_dev": c_dev,
            "pass_5pct": bool(l_dev <= ANCHOR_TOLERANCE
                              and c_dev <= ANCHOR_TOLERANCE),
        }
        message = (f"Q3D 提取成功：L={l_total:.4f}nH（{l_per_mm:.4f}/mm, "
                   f"Δ={l_dev * 100:.2g}%），C={c_total:.4f}pF"
                   f"（{c_per_mm:.4f}/mm, Δ={c_dev * 100:.2g}%）"
                   + (f"，R={r_total:.6g}Ω（参考）" if r_total is not None else ""))
        field_data: dict[str, Any] = {
            "spec": dict(spec),
            "extracted": {
                "l_total_nh": l_total,
                "c_total_pf": c_total,
                "r_total_ohm": r_total,
                "l_nh_per_mm": l_per_mm,
                "c_pf_per_mm": c_per_mm,
            },
            "anchor": anchor,
            "verdict": verdict,
            "matrix_files": {"rl": str(rl_path), "c": str(c_path)},
            "setup_props_applied": applied_props,
        }
        return EMSolverResult(success=True, wall_time_s=wall,
                              field_data=field_data, message=message)

    def get_sparams(self) -> tuple[Any, Any]:
        """寄生通道不产出 S 参数（显式报错，不返回伪数据）。"""
        raise NotImplementedError("Q3dAdapter 是寄生提取通道，不产出 S 参数")

    def close(self) -> None:
        """保存（可选）并释放桌面（best-effort，不抛异常）。

        pyaedt 1.4.0 Design.release_desktop 签名为
        (close_projects=True, close_desktop=True)（同 icepak_adapter 真机实证）。
        """
        if self._q3d is None:
            return
        try:
            if self._save_project:
                self._q3d.save_project()
            self._q3d.release_desktop(close_projects=False, close_desktop=True)
        except Exception as exc:
            logger.warning("关闭 AEDT 失败（忽略）: %s", exc)
        finally:
            self._q3d = None
            self._connected = False


# ── 注册（把 Q3D 通道接入全局注册表）──────────────────────────────────────

def register_q3d_adapter(registry: Any | None = None) -> None:
    """向求解器注册表注册 Q3D 通道（调用方显式调用，同 Icepak/Elmer 通道）。"""
    reg = registry or get_global_registry()
    reg.register(EMSolverType.Q3D, Q3dAdapter)
