"""DP-10 超表面/FSS 离线内核（P1：纯函数零 IO，规格 docs/plan_deepdive_specs_20260924.md §DP-10）。

四个子面（判据预声明 runs/df6_dp10ms/criteria.md，实现前冻结）：

1. LUT schema（MetasurfaceLUT）：单元波导模拟器扫频产物的统一载体，
   JSON（元数据+数组）+ CSV（长表）双载体互转；interp=pchip；
   run_dir provenance（#320 口径：真机行必须带产物目录指针，合成 LUT
   置空串并标 origin="synthetic"）。
2. 布局综合闭式（确定性内核，确定性内核铁律——物理数字只出在这里）：
   - 反射阵（点馈）：φ_mn = k0·(R_mn − r_mn·û_beam) mod 2π
     （Huang-Encinar《Reflectarray Antennas》空间相位延迟式；
     R_mn=馈相心到单元距离）；
   - 平面波照明（反射或透射/编码面统一）：φ_mn = k0·(û_in − û_out)·r_mn
     mod 2π（光栅条件；规格书透射式 φ_mn=−k0(r·û0) 是其法向入射特例，
     相位集合 mod 2π 等价）；
   - 逐单元 LUT 最近邻反查（圆周距离）+ b-bit 相位量化（取整到 2π/2^b 栅格）。
3. 量化口径：σ²=(π/2^b)²/3（副瓣基底）；增益损失 10·log10(sinc²(1/2^b))
   （均匀量化误差复相干因子 E[e^{jε}]² 的精确期望；文献带 1/2/3-bit≈
   3/0.6/0.2dB，J5=±1dB 带，两口径差异如实记档）。
4. Luukkonen/Costa EC 闭式（FSS 屏带心初值，arXiv:0705.3548 eq.3/4 +
   TM 栅阻抗换算）：贴片阵 C=(2D/π)·ε0·εeff·ln(csc(πg/2D))、线网
   L=μ0·D/(2π)·ln(csc(πw/2D))、εeff=(1+εr)/2；介质 TL+栅阻抗 ABCD 级联
   S 参数；JC 缝（带通口径）=shunt 支路 LC 并联（f0 呈开路→全透）。

名义尺寸闭式（#252/#1c，渲染与 TEMPLATE_NOMINAL 的单源）也收在本模块：
ms_patch Hammerstad εeff 不动点、ms_cross/ms_jcross λg 口径。本模块零
文件读写零环境依赖——真机 LUT 的 ingest 由 service 层另接（P3）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, fields
from typing import Any

import numpy as np
from scipy.interpolate import PchipInterpolator

#: LUT schema 版本（recipe_version/schema_version 双版本语义先例 #106：
#: 这是 LUT 载体版本，不是插件参数版本）
LUT_SCHEMA = "metasurface_lut/v1"
#: 相位插值口径（冻结于 criteria §1b）
LUT_INTERP = "pchip"
#: 真空波阻抗（方胞波导模拟器 TEM 口径的匹配参考，Ω）
ETA0_OHM = 376.730313668
C0_M_S = 299792458.0
EPS0_F_M = 8.854187817e-12
MU0_H_M = 4e-7 * math.pi

_J1B_PHASE_DEG_MAX = 10.0
_J1B_AMP_DB_MAX = 0.5
_J1_COVERAGE_DEG_MIN = 300.0


# ─── LUT schema ──────────────────────────────────────────────────────────────


@dataclass
class MetasurfaceLUT:
    """单元 LUT：cell_id/f0/substrate_key/params/provenance/freq 网格/|S|dB+解缠相位。

    数组形状统一 (n_sweep, n_freq)：s11_db=|S11| dB、s11_phase_deg=解缠
    相位（度，np.unwrap 口径）。sweep_values 严格升序；interp=pchip。
    """

    cell_id: str
    f0_ghz: float
    substrate_key: str
    sweep_key: str
    sweep_values: np.ndarray
    freq_ghz: np.ndarray
    s11_db: np.ndarray
    s11_phase_deg: np.ndarray
    params: dict[str, Any] = field(default_factory=dict)
    run_dir: str = ""
    origin: str = "synthetic"
    validity: dict[str, Any] = field(default_factory=dict)
    gate: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.sweep_values = np.asarray(self.sweep_values, dtype=float)
        self.freq_ghz = np.asarray(self.freq_ghz, dtype=float)
        self.s11_db = np.asarray(self.s11_db, dtype=float)
        self.s11_phase_deg = np.asarray(self.s11_phase_deg, dtype=float)

    # ── 校验 ──
    def validate(self) -> list[str]:
        """schema 校验，返回问题清单（空=合格）；不抛错由调用方裁决。"""
        problems: list[str] = []
        if not self.cell_id:
            problems.append("cell_id 为空")
        if self.sweep_values.ndim != 1 or self.sweep_values.size < 2:
            problems.append("sweep_values 需 ≥2 个的一维升序数组")
        elif bool(np.any(np.diff(self.sweep_values) <= 0)):
            problems.append("sweep_values 非严格升序")
        if self.freq_ghz.ndim != 1 or self.freq_ghz.size < 3:
            problems.append("freq_ghz 需 ≥3 个频点（pchip 需要区间内点）")
        shape = (self.sweep_values.size, self.freq_ghz.size)
        if self.s11_db.shape != shape:
            problems.append(f"s11_db 形状 {self.s11_db.shape} != {shape}")
        if self.s11_phase_deg.shape != shape:
            problems.append(f"s11_phase_deg 形状 {self.s11_phase_deg.shape} != {shape}")
        if self.interp != LUT_INTERP:
            problems.append(f"interp={self.interp!r} != {LUT_INTERP!r}")
        if self.origin not in ("synthetic", "openems_wg_sim", "hfss_floquet"):
            problems.append(f"origin={self.origin!r} 非法")
        if self.origin != "synthetic" and not self.run_dir:
            # #320：真机行必须带产物目录 provenance
            problems.append("非合成 LUT 缺 run_dir provenance")
        return problems

    @property
    def interp(self) -> str:
        return LUT_INTERP

    # ── JSON 载体 ──
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"schema": LUT_SCHEMA}
        for f in fields(self):
            v = getattr(self, f.name)
            d[f.name] = v.tolist() if isinstance(v, np.ndarray) else v
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=1, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MetasurfaceLUT:
        known = {f.name for f in fields(cls)}
        missing = known - set(d)
        if missing:
            raise ValueError(f"LUT dict 缺字段 {sorted(missing)}")
        extra = set(d) - known - {"schema"}
        if extra:
            raise ValueError(f"LUT dict 多余字段 {sorted(extra)}")
        if d.get("schema") != LUT_SCHEMA:
            raise ValueError(f"schema={d.get('schema')!r} != {LUT_SCHEMA!r}")
        return cls(
            cell_id=d["cell_id"],
            f0_ghz=float(d["f0_ghz"]),
            substrate_key=str(d["substrate_key"]),
            sweep_key=str(d["sweep_key"]),
            sweep_values=np.asarray(d["sweep_values"], dtype=float),
            freq_ghz=np.asarray(d["freq_ghz"], dtype=float),
            s11_db=np.asarray(d["s11_db"], dtype=float),
            s11_phase_deg=np.asarray(d["s11_phase_deg"], dtype=float),
            params=dict(d.get("params") or {}),
            run_dir=str(d.get("run_dir") or ""),
            origin=str(d.get("origin") or "synthetic"),
            validity=dict(d.get("validity") or {}),
            gate=dict(d.get("gate") or {}),
        )

    @classmethod
    def from_json(cls, text: str) -> MetasurfaceLUT:
        return cls.from_dict(json.loads(text))

    # ── CSV 长表载体（# key=value 注释头 + sweep,freq,db,phase 四列）──
    def to_csv(self) -> str:
        head = "#" + json.dumps(self.to_dict(), ensure_ascii=False,
                                sort_keys=True) + "\n"
        rows = ["sweep_value,freq_ghz,s11_db,s11_phase_deg"]
        for i, sv in enumerate(self.sweep_values):
            for j, fv in enumerate(self.freq_ghz):
                rows.append(f"{float(sv)!r},{float(fv)!r},"
                            f"{float(self.s11_db[i, j])!r},"
                            f"{float(self.s11_phase_deg[i, j])!r}")
        return head + "\n".join(rows) + "\n"

    @classmethod
    def from_csv(cls, text: str) -> MetasurfaceLUT:
        lines = text.strip().splitlines()
        if not lines or not lines[0].startswith("#"):
            raise ValueError("CSV 缺 # 注释头（双载体约定）")
        d = json.loads(lines[0][1:])
        header = lines[1].split(",")
        if header != ["sweep_value", "freq_ghz", "s11_db", "s11_phase_deg"]:
            raise ValueError(f"CSV 列头漂移: {header}")
        body = [ln.split(",") for ln in lines[2:] if ln.strip()]
        sv = sorted({float(r[0]) for r in body})
        fv = sorted({float(r[1]) for r in body})
        db = np.empty((len(sv), len(fv)))
        ph = np.empty((len(sv), len(fv)))
        si = {v: i for i, v in enumerate(sv)}
        fi = {v: i for i, v in enumerate(fv)}
        for r in body:
            i, j = si[float(r[0])], fi[float(r[1])]
            db[i, j] = float(r[2])
            ph[i, j] = float(r[3])
        d["sweep_values"], d["freq_ghz"], d["s11_db"], d["s11_phase_deg"] = (
            sv, fv, db, ph)
        return cls.from_dict(d)

    # ── 判据面 ──
    def phase_coverage_deg(self) -> float:
        """f0（取最近频点）处扫描覆盖的反射相位跨度（解缠域 min..max，度）。"""
        j = int(np.argmin(np.abs(self.freq_ghz - self.f0_ghz)))
        col = self.s11_phase_deg[:, j]
        return float(np.max(col) - np.min(col))

    def coverage_gate(self) -> dict[str, Any]:
        """J1c 覆盖门（≥300°，criteria §1c）：只算数值与判定，不跑仿真。"""
        cov = self.phase_coverage_deg()
        return {"phase_coverage_deg": cov,
                "threshold_deg": _J1_COVERAGE_DEG_MIN,
                "verdict": "PASS" if cov >= _J1_COVERAGE_DEG_MIN else "FAIL"}


# ── 相位处理原语 ─────────────────────────────────────────────────────────────


def unwrap_phase_deg(phases_deg: np.ndarray) -> np.ndarray:
    """解缠相位（度）：np.unwrap（弧度域）往返，跨 2π 跳变消除。"""
    return np.degrees(np.unwrap(np.radians(np.asarray(phases_deg, dtype=float))))


def lut_interp_pchip(lut: MetasurfaceLUT, sweep_value: float,
                     f0_ghz: float | None = None) -> tuple[float, float]:
    """pchip 插值单点 (|S|dB, 解缠相位 deg)：对扫描轴在 f0（缺省 LUT.f0）插值。"""
    j = int(np.argmin(np.abs(lut.freq_ghz - (lut.f0_ghz if f0_ghz is None
                                             else f0_ghz))))
    ph = PchipInterpolator(lut.sweep_values, lut.s11_phase_deg[:, j])
    db = PchipInterpolator(lut.sweep_values, lut.s11_db[:, j])
    return float(db(sweep_value)), float(ph(sweep_value))


def _circ_diff_deg(a: float, b: float) -> float:
    """相位圆周距离（度，0..180）。"""
    d = (a - b) % 360.0
    return min(d, 360.0 - d)


def lut_lookup_phase(lut: MetasurfaceLUT,
                     target_phase_deg: float) -> dict[str, float]:
    """逐单元最近邻反查：目标相位（mod 360 圆周距离）最近的 LUT 网格点。

    返回 {"sweep_value", "phase_deg"}——判据 J1a 的确定性定义：
    最近邻由圆周距离唯一决定（并列取 sweep 较小者，量化前的约定）。
    """
    j = int(np.argmin(np.abs(lut.freq_ghz - lut.f0_ghz)))
    col = lut.s11_phase_deg[:, j]
    dist = np.array([_circ_diff_deg(target_phase_deg, float(v)) for v in col])
    i = int(np.argmin(dist))
    return {"sweep_value": float(lut.sweep_values[i]),
            "phase_deg": float(col[i])}


def quantize_phase_deg(target_phase_deg: float, bits: int) -> float:
    """b-bit 相位量化（取整到 2π/2^b 栅格，度域）。bits≥1。"""
    if bits < 1:
        raise ValueError(f"bits={bits} 须 ≥1")
    step = 360.0 / (2 ** bits)
    return round(target_phase_deg / step) * step


# ─── 布局综合闭式（确定性内核，确定性内核铁律）──────────────────────────────


def _k0_rad_m(f0_ghz: float) -> float:
    return 2.0 * math.pi * (f0_ghz * 1e9) / C0_M_S


def required_phase_reflectarray(
    positions_m: np.ndarray,
    feed_pos_m: np.ndarray,
    u_beam: np.ndarray,
    f0_ghz: float,
) -> np.ndarray:
    """反射阵（点馈）所需单元反射相位（度，mod 360）。

    φ_mn = k0·(R_mn − r_mn·û_beam) mod 2π（Huang-Encinar 空间相位延迟式；
    R_mn=|r_mn−r_feed|，û_beam 单位主波束向量，反射侧）。positions_m
    (N,3) 单元位置（z=口径面），feed_pos_m (3,) 馈电相心。
    """
    pos = np.atleast_2d(np.asarray(positions_m, dtype=float))
    u = np.asarray(u_beam, dtype=float)
    u = u / float(np.linalg.norm(u))
    r = np.asarray(feed_pos_m, dtype=float)
    ranges = np.linalg.norm(pos - r, axis=1)
    phi = _k0_rad_m(f0_ghz) * (ranges - pos @ u)
    return np.degrees(phi) % 360.0


def required_phase_plane_wave(
    positions_m: np.ndarray,
    u_in: np.ndarray,
    u_out: np.ndarray,
    f0_ghz: float,
) -> np.ndarray:
    """平面波照明所需单元相位（度，mod 360）——反射/透射统一光栅条件。

    φ_mn = k0·(û_in − û_out)·r_mn mod 2π。透射编码面法向入射特例
    û_in=(0,0,−1)、û_out=(sinθcosφ, sinθsinφ, cosθ)：φ_mn=−k0·r·û_out+const
    （规格书口径 mod 2π 等价）；反射（û_out 反射侧）同式。本批软平面
    照明（û_in=(0,0,−1)，自 +z 向下）即用此式。
    """
    pos = np.atleast_2d(np.asarray(positions_m, dtype=float))
    ui = np.asarray(u_in, dtype=float)
    uo = np.asarray(u_out, dtype=float)
    ui = ui / float(np.linalg.norm(ui))
    uo = uo / float(np.linalg.norm(uo))
    phi = _k0_rad_m(f0_ghz) * ((ui - uo) * pos).sum(axis=1)
    return np.degrees(phi) % 360.0


def synthesize_layout(
    n_x: int,
    n_y: int,
    period_m: float,
    f0_ghz: float,
    lut: MetasurfaceLUT,
    *,
    feed_pos_m: np.ndarray | None = None,
    u_in: np.ndarray | None = None,
    u_beam: np.ndarray,
    bits: int = 0,
) -> list[dict[str, Any]]:
    """布局综合：闭式目标相位 →（可选 b-bit 量化）→ LUT 最近邻反查。

    返回逐单元参数表（cell_map 同构：i/j/x_m/y_m/px 目标相位/量化相位/
    反查值/反查相位）。bits=0 不量化。feed_pos_m 给出=点馈反射阵；
    否则平面波照明（u_in 缺省 (0,0,−1) 软平面口径）。纯函数零 IO。
    """
    if n_x < 1 or n_y < 1:
        raise ValueError(f"n_x/n_y 须 ≥1，得 {n_x}/{n_y}")
    if period_m <= 0:
        raise ValueError("period_m 须 >0")
    problems = lut.validate()
    if problems:
        raise ValueError(f"LUT 不合格: {problems}")
    if bits and lut.coverage_gate()["verdict"] != "PASS":
        # 量化要求 LUT 覆盖 0..360 全域；覆盖不足量化误差失控——显式拒绝
        raise ValueError("bits>0 要求 LUT 相位覆盖 ≥300°（J1c 门）")
    xs = (np.arange(n_x) - (n_x - 1) / 2.0) * period_m
    ys = (np.arange(n_y) - (n_y - 1) / 2.0) * period_m
    xx, yy = np.meshgrid(xs, ys, indexing="ij")
    pos = np.stack([xx.ravel(), yy.ravel(), np.zeros(n_x * n_y)], axis=1)
    if feed_pos_m is not None:
        phi = required_phase_reflectarray(pos, np.asarray(feed_pos_m, float),
                                          u_beam, f0_ghz)
    else:
        phi = required_phase_plane_wave(
            pos, np.asarray(u_in, float) if u_in is not None
            else np.array([0.0, 0.0, -1.0]), u_beam, f0_ghz)
    cells: list[dict[str, Any]] = []
    for k in range(pos.shape[0]):
        tgt = float(phi[k])
        q = quantize_phase_deg(tgt, bits) if bits else tgt
        hit = lut_lookup_phase(lut, q)
        cells.append({
            "i": int(k % n_x), "j": int(k // n_x),
            "x_m": float(pos[k, 0]), "y_m": float(pos[k, 1]),
            "phase_target_deg": tgt,
            "phase_quantized_deg": q if bits else None,
            "sweep_value": hit["sweep_value"],
            "phase_achieved_deg": hit["phase_deg"],
        })
    return cells


def phase_quantization_mse_rad2(bits: int) -> float:
    """b-bit 均匀量化的均方相位误差（rad²）= (π/2^b)²/3（副瓣基底口径，冻结）。"""
    if bits < 1:
        raise ValueError(f"bits={bits} 须 ≥1")
    return (math.pi / (2 ** bits)) ** 2 / 3.0


def quantization_loss_db(bits: int) -> float:
    """量化增益损失（正值 dB）= −10·log10(sinc²(1/2^b))（E[e^{jε}]² 精确期望）。

    文献带（规格书 §1）：1/2/3-bit≈3/0.6/0.2dB；本口径 3.92/0.91/0.22
    全落 ±1dB 带（J5）。sinc(x)=sin(πx)/(πx)。
    """
    if bits < 1:
        raise ValueError(f"bits={bits} 须 ≥1")
    x = 1.0 / (2 ** bits)
    sinc = math.sin(math.pi * x) / (math.pi * x)
    return -10.0 * math.log10(sinc * sinc)


# ─── 名义尺寸闭式（#252/#1c 单源；渲染与 TEMPLATE_NOMINAL 同源消费）──────────


def ms_patch_eps_eff(w_mm: float, er: float, h_mm: float) -> float:
    """Hammerstad 薄板 εeff 闭式（反射阵方贴片设计口径）。"""
    if w_mm <= 0 or er <= 1 or h_mm <= 0:
        raise ValueError(f"非法输入 w={w_mm} er={er} h={h_mm}")
    return (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 * h_mm / w_mm)


def ms_patch_resonant_len_mm(f0_ghz: float, er: float, h_mm: float) -> float:
    """方贴片谐振边长（mm）：λ0/(2√εeff(w)) 以 w=边长解不动点（2 次迭代收敛）。"""
    lam0_mm = C0_M_S / (f0_ghz * 1e9) * 1e3
    w = lam0_mm / (2 * math.sqrt((er + 1) / 2))
    for _ in range(16):
        w = lam0_mm / (2 * math.sqrt(ms_patch_eps_eff(w, er, h_mm)))
    return w


def ms_screen_eps_eff(er: float) -> float:
    """FSS 屏 εeff=(1+εr)/2（单侧基板加载，Luukkonen eq.3 口径）。"""
    return (1.0 + er) / 2.0


def ms_cross_arm_len_mm(f0_ghz: float, er: float) -> float:
    """十字偶极子臂长（中心→尖端，mm）：总跨=λ0/(2√εeff)（半波谐振）。"""
    lam0_mm = C0_M_S / (f0_ghz * 1e9) * 1e3
    return lam0_mm / (4.0 * math.sqrt(ms_screen_eps_eff(er)))


def ms_jcross_slot_dims_mm(f0_ghz: float, er: float) -> dict[str, float]:
    """Jerusalem cross 缝初值（mm）：主缝=λg/4、端枝=λg/8（λg=λ0/√εeff）。

    JC 缝=带通口径（缝隙谐振全透）：电长度初值按半波口径分配主缝+双端枝；
    真机带心修正（openEMS LUT 一轮）归 P3——EC 闭环见 fss_* 函数。
    """
    lam0_mm = C0_M_S / (f0_ghz * 1e9) * 1e3
    lamg_mm = lam0_mm / math.sqrt(ms_screen_eps_eff(er))
    return {"slot_len_mm": lamg_mm / 4.0, "stub_len_mm": lamg_mm / 8.0}


# ─── Luukkonen/Costa EC 闭式（FSS 屏带心初值）────────────────────────────────


def fss_patch_grid_capacitance_f(period_m: float, gap_m: float,
                                 eps_eff: float) -> float:
    """容性贴片阵等效电容（F/胞）：C=(2D/π)ε0εeff·ln(csc(πg/2D))。

    arXiv:0705.3548 eq.4 α=(k_eff·D/π)ln(csc) + TM 栅阻抗 Z=−jη_eff/2α
    换算（法向 TM）；eps_eff=(1+εr)/2（eq.3）。要求 g≪D（稠密栅有效域）。
    """
    if period_m <= 0 or not 0 < gap_m < period_m:
        raise ValueError(f"要求 0<gap<period，得 {gap_m}/{period_m}")
    x = math.pi * gap_m / (2 * period_m)
    return (2 * period_m / math.pi) * EPS0_F_M * eps_eff * math.log(1 / math.sin(x))


def fss_mesh_grid_inductance_h(period_m: float, wire_m: float) -> float:
    """感性线网等效电感（H/胞）：L=μ0·D/(2π)·ln(csc(πw/2D))（对偶口径）。"""
    if period_m <= 0 or not 0 < wire_m < period_m:
        raise ValueError(f"要求 0<wire<period，得 {wire_m}/{period_m}")
    x = math.pi * wire_m / (2 * period_m)
    return MU0_H_M * period_m / (2 * math.pi) * math.log(1 / math.sin(x))


def fss_screen_sparams(
    freq_hz: np.ndarray,
    grid_kind: str,
    period_m: float,
    eps_eff: float,
    *,
    gap_m: float | None = None,
    wire_m: float | None = None,
    parallel_lc: tuple[float, float] | None = None,
    slab_eps: float = 1.0,
    slab_h_m: float = 0.0,
) -> dict[str, np.ndarray]:
    """FSS 屏 S 参数（法向，ABCD 级联纯函数）：空气 TL − 栅 shunt − 基板 TL − 空气。

    grid_kind：'patch'（shunt Z=1/jωC，C 由 period+gap 闭式）| 'mesh'
    （shunt Z=jωL，L 由 period+wire 闭式）| 'parallel_lc'（JC 缝带通口径：
    shunt 支路=LC 并联，Z=(jωL)∥(1/jωC) 在 f0 呈开路→全透；实心屏 DC/
    高频呈短路→反射，(L,C) 由 parallel_lc 显式给出，
    fss_jcross_parallel_lc 定带心）。slab：基板 TL 段（eps_r=slab_eps、
    厚 slab_h_m；eps=1/h=0 退化无板）。返回 {"s11_db","s21_db","s21"}。
    口径注记（离线冒烟实证）：shunt 支路若用**串联** LC，谐振=短路=带阻
   陷（f0 处 S21 谷）——JC 缝是带通口径，必须并联谐振（shunt 开路）。
    """
    if grid_kind not in ("patch", "mesh", "parallel_lc"):
        raise ValueError(f"grid_kind={grid_kind!r} 非法")
    f = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    om = 2 * np.pi * f
    if grid_kind == "patch":
        if gap_m is None:
            raise ValueError("grid_kind='patch' 需 gap_m")
        c_f = fss_patch_grid_capacitance_f(period_m, gap_m, eps_eff)
        z = 1.0 / (1j * om * c_f)
    elif grid_kind == "mesh":
        if wire_m is None:
            raise ValueError("grid_kind='mesh' 需 wire_m")
        z = 1j * om * fss_mesh_grid_inductance_h(period_m, wire_m)
    else:
        if parallel_lc is None:
            raise ValueError("grid_kind='parallel_lc' 需 parallel_lc=(L,C)")
        l_h, c_f = parallel_lc
        z = (1j * om * l_h) * (1.0 / (1j * om * c_f)) / (
            1j * om * l_h + 1.0 / (1j * om * c_f))
    z0 = ETA0_OHM
    eta_sl = z0 / math.sqrt(slab_eps) if slab_eps > 0 else z0
    beta_sl = 2 * np.pi * f / C0_M_S * math.sqrt(slab_eps)
    s11 = np.empty(f.size, dtype=complex)
    s21 = np.empty(f.size, dtype=complex)
    for i in range(f.size):
        abcd = _abcd_tl(eta_sl, beta_sl[i], slab_h_m / 2)
        abcd = abcd @ _abcd_shunt(z[i])
        abcd = abcd @ _abcd_tl(eta_sl, beta_sl[i], slab_h_m / 2)
        den = (abcd[0, 0] + abcd[0, 1] / z0 + abcd[1, 0] * z0 + abcd[1, 1])
        s21[i] = 2.0 / den
        s11[i] = ((abcd[0, 0] + abcd[0, 1] / z0 - abcd[1, 0] * z0
                   - abcd[1, 1]) / den)
    with np.errstate(divide="ignore"):
        return {"s11_db": 20 * np.log10(np.abs(s11)),
                "s21_db": 20 * np.log10(np.abs(s21)),
                "s21": s21}


def _abcd_tl(z_c: float, beta_rad_m: float, d_m: float) -> np.ndarray:
    th = beta_rad_m * d_m
    return np.array([[math.cos(th), 1j * z_c * math.sin(th)],
                     [1j * math.sin(th) / z_c, math.cos(th)]], dtype=complex)


def _abcd_shunt(z: complex) -> np.ndarray:
    return np.array([[1.0, 0.0], [1.0 / z, 1.0]], dtype=complex)


def fss_jcross_parallel_lc(period_m: float, slot_w_m: float,
                           target_f0_hz: float) -> tuple[float, float]:
    """JC 缝带通 EC：L 由缝宽/周期线网闭式；C=1/(ω0²L) 定带心（初值口径）。

    返回 (L, C)：shunt 支路 LC **并联**，f0 处呈开路→全透（带通）；
    C→缝端枝几何的映射是真机 LUT 修正环（P3）的标定对象——本函数只钉
    带心初值的确定性来源。
    """
    l_h = fss_mesh_grid_inductance_h(period_m, slot_w_m)
    om0 = 2 * math.pi * target_f0_hz
    return l_h, 1.0 / (om0 * om0 * l_h)


def ec_resonance_peak_f(fss: dict[str, np.ndarray],
                        freq_hz: np.ndarray) -> float:
    """|S21| 峰位（Hz）——EC 自洽钉：设计带心的 L、C 级联后峰=f0。"""
    return float(freq_hz[int(np.argmax(fss["s21_db"]))])


def lut_summary(lut: MetasurfaceLUT) -> dict[str, Any]:
    """LUT 概要（gate 记录/判读报告面）：覆盖、门、来源 provenance。"""
    return {"cell_id": lut.cell_id, "f0_ghz": lut.f0_ghz,
            "substrate_key": lut.substrate_key, "origin": lut.origin,
            "run_dir": lut.run_dir, "n_sweep": int(lut.sweep_values.size),
            "n_freq": int(lut.freq_ghz.size), "interp": lut.interp,
            "validity": dict(lut.validity), "gate": dict(lut.gate)}
