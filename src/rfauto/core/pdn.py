"""F-B.1 电源完整性（PI/PDN）AC 阻抗域确定性内核（research_expansion §F-B P1 离线段）。

纯算法闭式族（分立 RLGC 阶梯口径，数值只在确定性内核，铁律 7）；参照
core/rwg_mmt.py 先例不进 @register_calculator（免 #231 注册表消费者三表同步），
导出函数供 service 层直接调。判据预声明 = 研究扩充
§F-B 第 4 节（先写后跑，#122）；本文件交付判据 1-5（第 6 条真机面 P3 不在本批）。

模块面（与方案 §F-B 第 2/3 节一一对应）：
- 目标阻抗：target_impedance（恒定口径 Z=V_ripple/ΔI）+ target_impedance_freq
  （频率依赖分段包络，Smith/Novak 谱系：低频平坦+高频 −20dB/dec，拐点频率为参数）。
- decap 模型：decap_impedance（C+ESR+ESL+安装电感单电容复阻抗）+
  mount_inductance（安装电感工程闭式：过孔对回路+径向扩张两贡献项）。
- VRM：vrm_model 四元件两支路模型（低频支路 R0+jωL0 主导、高频支路 R1+jωL1
  接管；实现取两支路并联口径，docstring 写明——分段开关口径不连续故不取）。
- 平面腔体谐振：plane_cavity_modes（矩形电源对腔模频率闭式筛查，v1 不做全场
  TMM）+ mount_position_clearance（安装位置离腔模波腹的避让判据，返回
  verdict+余量）。
- DC-bias：dc_bias_effective_c（折减查表+线性插值；无曲线如实标 no_derating，
  不虚构曲线，铁律 7）。
- 整网合成：pdn_impedance_profile（VRM 与全部电容的并联导纳求和 Y=Σ1/Zᵢ）。
- 选型优化：greedy_decap_select（确定性贪心：每步选"超标频段改善/成本比"最大
  的电容；全加完仍超标→显式 infeasible，不凑解）。

数值口径：时谐约定 e^{+jωt}；阻抗 Z=ESR+j(ωL−1/(ωC))；并联一律导纳求和
（Z→Y→倒数，复数除法数值稳定）；全频段无任何支路时 Y=0 → Z=∞ 显式处理
（numpy 除零警告在函数内抑制，返回 inf+0j，不静默吞）。

出处（公式与出处一一对应，#1c/#300 纪律）：
- 目标阻抗法奠基：L. D. Smith, R. E. Anderson, D. W. Forehand, T. J. Pelc,
  T. Roy, "Power distribution system design methodology and capacitor
  selection for modern CMOS technology," IEEE Trans. Adv. Packag., vol. 22,
  no. 3, pp. 284-291, Aug. 1999（doi 10.1109/6040.784476）；频率依赖目标
  阻抗分段包络为 Smith/Novak 后续专利族口径（低频平坦+拐点后 −20dB/dec）。
- 去耦网络方法论：K. Kundert, "Power supply noise reduction,"
  designers-guide.org/design/bypassing.pdf（2006）——C+ESR+ESL 三件模型、
  多电容并联导纳求和、反谐振（anti-resonance）峰机理。
- 安装电感：过孔对回路项用双线传输线闭式（E. B. Rosa / F. Grover,
  "Inductance Calculations," 1946——L'=μ0/π·arcosh(s/2r)）按 Archambeault
  安装回路分解口径（B. Archambeault, PCB Design for Real-World EMI
  Control, Kluwer，2011 印次：安装电感=过孔贡献+焊盘/扩张贡献）组装；
  径向扩张项用平行板径向流扩张电感闭式（I. Novak, J. R. Miller,
  "Frequency-Domain Characterization of Power Distribution Networks,"
  Artech House 2007：L_spread=μ0·h_d/(2π)·ln(r2/r1)）。两者均为工程简化
  模型（忽略有限长端部效应与过孔焊盘回 流不对称），量级用于选型筛查非精算。
- VRM 四元件模型：Sandler《Power Integrity》McGraw-Hill 2014 与 Smith 1999
  的 VRM 宏模型谱系（理想源+两支路输出阻抗），本实现取 (R0+jωL0)∥(R1+jωL1)
  两支路口径（见 vrm_model docstring）。
- 矩形平面腔模：f_mn=c/(2√εr)·√((m/a)²+(n/b)²)（矩形谐振腔 TM 闭式标准式，
  Pozar《Microwave Engineering》腔体谐振器章同形口径；v1 仅频率筛查）。

decap 库 schema（DecapSpec + load_decap_library）：默认库
configs/decap_library.yaml；provenance 字段强制（铁律 7：首批条目一律
typical_engineering_value 标注，禁止虚构 vendor 实测数字；vendor 实测
曲线入 dc_bias_curve 键并带出处）。加载入口沿用 core.vendor_passives
read_catalog 先例：单条不合法即 ValueError 硬错（provenance 门不是
#105 观测性）。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

C0 = 299792458.0
MU0 = 4.0e-7 * math.pi
DEFAULT_LIBRARY_PATH = Path(__file__).resolve().parents[3] / "configs" / "decap_library.yaml"

_PROFILES = ("flat", "smith")
TYPICAL_PROVENANCE_PREFIX = "typical_engineering_value"


def _freq_array(f: float | Sequence[float] | np.ndarray) -> np.ndarray:
    """频率入参收敛为一维正 float 数组（#140：注解写了不代表调用方传的是）。"""
    arr = np.atleast_1d(np.asarray(f, dtype=float))
    if arr.ndim != 1:
        raise ValueError(f"f 必须是一维频率序列，实际 shape {arr.shape}")
    if np.any(arr <= 0.0) or not np.all(np.isfinite(arr)):
        raise ValueError(f"f 必须全为正有限数，实际 {arr}")
    return arr


def _require_finite_nonneg(name: str, value: float) -> float:
    val = float(value)
    if not math.isfinite(val) or val < 0.0:
        raise ValueError(f"{name} 必须为非负有限数，实际 {value!r}")
    return val


# ─── 目标阻抗 ────────────────────────────────────────────────────────────────


def target_impedance(v_ripple_v: float, delta_i_a: float) -> float:
    """恒定口径目标阻抗 Z_target = V_ripple / ΔI（Smith 1999 IEEE TAP 口径）。

    Args:
        v_ripple_v: 允许纹波幅度（V，正数）。
        delta_i_a: 瞬态电流阶跃（A，正数）。

    Returns:
        目标阻抗（Ω）。
    """
    vr = float(v_ripple_v)
    di = float(delta_i_a)
    if not math.isfinite(vr) or vr <= 0.0:
        raise ValueError(f"v_ripple_v 必须为正有限数，实际 {v_ripple_v!r}")
    if not math.isfinite(di) or di <= 0.0:
        raise ValueError(f"delta_i_a 必须为正有限数，实际 {delta_i_a!r}")
    return vr / di


def target_impedance_freq(
    f: float | Sequence[float] | np.ndarray,
    v_ripple_v: float,
    delta_i_a: float,
    profile: str = "flat",
    corner_freq_hz: float | None = None,
) -> np.ndarray:
    """频率依赖目标阻抗包络 Z_target(f)。

    口径（Smith/Novak 谱系，出处见模块 docstring）：
    - profile="flat"：全带恒定 Z0 = V_ripple/ΔI。
    - profile="smith"：低频（f ≤ f_corner）平坦 Z0；高频（f > f_corner）
      按 −20dB/dec 下降，即 Z0·f_corner/f（1/f 斜率段）。拐点频率
      corner_freq_hz 为显式参数（由调用方按 VRM 带宽/散装电容决定），本内核
      不替用户发明缺省拐点。

    Args:
        f: 频率（Hz，正数标量或一维数组）。
        v_ripple_v: 允许纹波幅度（V）。
        delta_i_a: 瞬态电流阶跃（A）。
        profile: "flat" | "smith"。
        corner_freq_hz: smith 口径拐点频率（Hz，正数）；flat 口径必须省略或为 None。

    Returns:
        与 f 同长的 Z_target 数组（Ω）。
    """
    freqs = _freq_array(f)
    z0 = target_impedance(v_ripple_v, delta_i_a)
    if profile == "flat":
        if corner_freq_hz is not None:
            raise ValueError("profile='flat' 不接受 corner_freq_hz（拐点是 smith 口径参数）")
        return np.full(freqs.shape, z0)
    if profile == "smith":
        if corner_freq_hz is None:
            raise ValueError("profile='smith' 必须显式给 corner_freq_hz（拐点频率为参数，不发明缺省）")
        fc = float(corner_freq_hz)
        if not math.isfinite(fc) or fc <= 0.0:
            raise ValueError(f"corner_freq_hz 必须为正有限数，实际 {corner_freq_hz!r}")
        return np.where(freqs <= fc, z0, z0 * fc / freqs)
    raise ValueError(f"profile 必须是 {_PROFILES} 之一，实际 {profile!r}")


# ─── decap 单体模型 ──────────────────────────────────────────────────────────


def decap_impedance(
    c_f: float,
    esr_ohm: float,
    esl_h: float,
    mount_l_h: float,
    f: float | Sequence[float] | np.ndarray,
) -> np.ndarray:
    """单电容复阻抗 Z(f) = ESR + j(ω(L_esl+L_mount) − 1/(ωC))（Kundert 2006 口径）。

    安装电感与 ESL 串联同权进入感性支路（安装回路与器件寄生串联，物理口径）。

    Args:
        c_f: 电容量（F，正数）。
        esr_ohm: 等效串联电阻（Ω，非负）。
        esl_h: 等效串联电感（H，非负）。
        mount_l_h: 安装电感（H，非负；板级贡献，典型 0.2-2 nH 量级）。
        f: 频率（Hz）。

    Returns:
        复阻抗数组（Ω），与 f 同长。
    """
    cap = float(c_f)
    if not math.isfinite(cap) or cap <= 0.0:
        raise ValueError(f"c_f 必须为正有限数，实际 {c_f!r}")
    esr = _require_finite_nonneg("esr_ohm", esr_ohm)
    l_total = _require_finite_nonneg("esl_h", esl_h) + _require_finite_nonneg("mount_l_h", mount_l_h)
    freqs = _freq_array(f)
    omega = 2.0 * np.pi * freqs
    return esr + 1j * (omega * l_total - 1.0 / (omega * cap))


def mount_inductance(
    board_thickness_m: float,
    via_radius_m: float,
    via_pair_spacing_m: float,
    plane_gap_m: float = 0.0,
    spread_radius_m: float = 0.0,
) -> float:
    """安装电感工程闭式（简化模型，出处与简化声明见模块 docstring）。

    按 Archambeault 安装回路分解口径组装两项标准闭式：
    - 过孔对回路项（双线闭式）：电流经电源过孔下行、地过孔回流，板厚 h 内
      构成双线回路，单位长回路电感 L' = (μ0/π)·arcosh(s/(2r))（Grover 1946
      双线口径），乘板厚 h 得 L_via_pair。
    - 径向扩张项（可选）：电流从过孔半径 r 扩张到 spread_radius_m 的径向流
      在平面介质厚 h_d 上的扩张电感 L_spread = μ0·h_d/(2π)·ln(r_spread/r)
      （Novak-Miller 2007 径向扩张闭式）。缺省（plane_gap_m=0 或
      spread_radius_m ≤ via_radius_m）不贡献。

    Args:
        board_thickness_m: 板厚（m，正数）。
        via_radius_m: 过孔半径（m，正数）。
        via_pair_spacing_m: 电源/地过孔对心距（m，> 2·via_radius_m）。
        plane_gap_m: 平面对介质厚度（m；0 表示不计扩张项）。
        spread_radius_m: 扩张半径（m；≤ via_radius_m 时不计扩张项）。

    Returns:
        安装电感（H）。
    """
    h = float(board_thickness_m)
    r = float(via_radius_m)
    s = float(via_pair_spacing_m)
    if not math.isfinite(h) or h <= 0.0:
        raise ValueError(f"board_thickness_m 必须为正有限数，实际 {board_thickness_m!r}")
    if not math.isfinite(r) or r <= 0.0:
        raise ValueError(f"via_radius_m 必须为正有限数，实际 {via_radius_m!r}")
    if not math.isfinite(s) or s <= 2.0 * r:
        raise ValueError(f"via_pair_spacing_m 必须大于 2·via_radius_m（arcosh 定义域），实际 {s!r} vs 2r={2.0 * r!r}")
    l_total = (MU0 / math.pi) * h * math.acosh(s / (2.0 * r))
    gap = float(plane_gap_m)
    spread = float(spread_radius_m)
    if gap > 0.0 and spread > r:
        l_total += (MU0 * gap / (2.0 * math.pi)) * math.log(spread / r)
    return l_total


# ─── VRM 模型 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VrmModel:
    """VRM 四元件两支路输出阻抗模型（见 vrm_model）。"""

    r0: float
    l0: float
    r1: float
    l1: float


def vrm_model(f: float | Sequence[float] | np.ndarray, r0: float, l0: float, r1: float, l1: float) -> np.ndarray:
    """VRM 输出阻抗 Z(f)，四元件两支路模型。

    实现口径（"两段 RL"的连续化实现，docstring 写明）：低频支路 Z_low=R0+jωL0
    与高频支路 Z_high=R1+jωL1 **并联**：
        Z(f) = Z_low·Z_high/(Z_low+Z_high)。
    参数惯例 R0 ≪ R1 且 L0 ≫ L1：低频段两支路均近阻性、并联趋近 R0（稳压器
    环路刚硬）；频率上升后大电感 L0 把低频支路"扼断"，阻抗交给 R1+jωL1 支路
    （高频段近 jωL1 感性上升）。两支路口径全程连续可微；任务书所述"低频段
    R0+L0、高频段 R1+L1"的分段开关口径在切换点不连续，故不取（如实偏离，
    测试以并联闭式逐位钉）。
    出处：Sandler《Power Integrity》2014 / Smith 1999 的 VRM 宏模型谱系
    （理想源+两支路输出阻抗），见模块 docstring。

    Args:
        f: 频率（Hz）。
        r0: 低频支路电阻（Ω，非负）。
        l0: 低频支路电感（H，非负，惯例远大于 l1）。
        r1: 高频支路电阻（Ω，非负）。
        l1: 高频支路电感（H，非负，惯例远小于 l0）。

    Returns:
        复输出阻抗数组（Ω）。
    """
    r0v = _require_finite_nonneg("r0", r0)
    l0v = _require_finite_nonneg("l0", l0)
    r1v = _require_finite_nonneg("r1", r1)
    l1v = _require_finite_nonneg("l1", l1)
    if r0v + l0v + r1v + l1v <= 0.0:
        raise ValueError("VRM 四元件全零：Z(f) 处处除零，拒绝退化模型")
    freqs = _freq_array(f)
    omega = 2.0 * np.pi * freqs
    z_low = r0v + 1j * omega * l0v
    z_high = r1v + 1j * omega * l1v
    return z_low * z_high / (z_low + z_high)


# ─── 平面腔体谐振 ────────────────────────────────────────────────────────────


class CavityMode:
    """矩形平面腔模 (m, n) 及其谐振频率（轻量记录，排序按 f_hz 升序）。"""

    __slots__ = ("f_hz", "m", "n")

    def __init__(self, m: int, n: int, f_hz: float) -> None:
        self.m = int(m)
        self.n = int(n)
        self.f_hz = float(f_hz)

    def __repr__(self) -> str:
        return f"CavityMode(m={self.m}, n={self.n}, f_hz={self.f_hz!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CavityMode):
            return NotImplemented
        return (self.m, self.n, self.f_hz) == (other.m, other.n, other.f_hz)


def plane_cavity_modes(a_m: float, b_m: float, er: float, m_max: int, n_max: int) -> list[CavityMode]:
    """矩形电源对腔模频率闭式筛查（v1 仅频率筛查，不做全场 TMM）。

    f_mn = c0/(2·√εr)·√((m/a)² + (n/b)²)，(0,0) 直流模排除；返回按 f_hz
    升序的 CavityMode 列表。域守卫：仅矩形完整平面成立（#F-B 风险③）——
    非矩形/分割平面由上层标 unsupported，本函数只管矩形。

    Args:
        a_m: 平面 a 边长（m，正数）。
        b_m: 平面 b 边长（m，正数）。
        er: 相对介电常数（正数，取有效介电常数的责任在上层）。
        m_max: x 方向最高模阶（非负整数）。
        n_max: y 方向最高模阶（非负整数）。

    Returns:
        CavityMode 列表（按 f_hz 升序）。
    """
    a = float(a_m)
    b = float(b_m)
    eps = float(er)
    if not math.isfinite(a) or a <= 0.0:
        raise ValueError(f"a_m 必须为正有限数，实际 {a_m!r}")
    if not math.isfinite(b) or b <= 0.0:
        raise ValueError(f"b_m 必须为正有限数，实际 {b_m!r}")
    if not math.isfinite(eps) or eps <= 0.0:
        raise ValueError(f"er 必须为正有限数，实际 {er!r}")
    mm = int(m_max)
    nn = int(n_max)
    if mm < 0 or nn < 0:
        raise ValueError(f"m_max/n_max 必须为非负整数，实际 ({m_max!r}, {n_max!r})")
    modes: list[CavityMode] = []
    for m in range(mm + 1):
        for n in range(nn + 1):
            if m == 0 and n == 0:
                continue
            f_hz = C0 / (2.0 * math.sqrt(eps)) * math.sqrt((m / a) ** 2 + (n / b) ** 2)
            modes.append(CavityMode(m, n, f_hz))
    modes.sort(key=lambda mode: mode.f_hz)
    return modes


@dataclass(frozen=True)
class ClearanceVerdict:
    """安装位置避让判据结果（verdict + 全部中间量，不替用户放宽判据）。"""

    verdict: str  # "clear" | "too_close"
    distance_m: float  # 到最近波腹的欧氏距离
    required_m: float  # 避让半径要求 = threshold_frac·λ_eff
    margin_m: float  # distance − required（负=违约量）
    m: int
    n: int
    f_hz: float  # λ_eff 的评估频率
    wavelength_m: float  # λ_eff = c0/(f·√εr)
    antinode_x_m: float
    antinode_y_m: float


def mount_position_clearance(
    x_m: float,
    y_m: float,
    a_m: float,
    b_m: float,
    er: float,
    m: int,
    n: int,
    f_hz: float | None = None,
    threshold_frac: float = 0.5,
) -> ClearanceVerdict:
    """安装位置离腔模 (m,n) 电压波腹的避让判据（返回 verdict+余量）。

    腔模 (m,n) 的电压驻波 |cos(mπx/a)·cos(nπy/b)| 在波腹网格
    x=k·a/m（k=0..m）、y=l·b/n（l=0..n）取极大（m=0/n=0 时该轴方向波腹
    连续，取该轴距离贡献为 0）。判据：位置到最近波腹的欧氏距离 ≥
    threshold_frac·λ_eff（缺省半波长口径 threshold_frac=0.5，任务书 F-B
    判据口径；λ_eff=c0/(f·√εr)）。

    如实声明（不替用户放宽）：对腔模自身谐振频率 f_mn 而言 λ_eff/2 恰等于
    波腹间距，故**任何**位置到最近波腹距离 < λ_eff/2，缺省口径下低阶模
    几乎必然 too_close——判读时应关注关心的扰动频率（如时钟谐波，用 f_hz
    显式给更高频率）或显式放宽 threshold_frac；本函数忠实实现判据并暴露
    全部中间量（distance/required/margin），裁决权在调用方。

    Args:
        x_m: 安装位置 x（m，应落在 [0, a] 内，越界如实计算不截断）。
        y_m: 安装位置 y（m）。
        a_m / b_m / er / m / n: 平面尺寸、介电常数与模阶（同 plane_cavity_modes）。
        f_hz: λ_eff 评估频率（Hz）；None 时取模自身谐振频率 f_mn。
        threshold_frac: 避让半径系数（缺省 0.5=半波长口径）。

    Returns:
        ClearanceVerdict（verdict="clear" 当 distance ≥ required，否则 "too_close"）。
    """
    if not (math.isfinite(float(threshold_frac)) and float(threshold_frac) > 0.0):
        raise ValueError(f"threshold_frac 必须为正有限数，实际 {threshold_frac!r}")
    a = float(a_m)
    b = float(b_m)
    eps = float(er)
    mi = int(m)
    ni = int(n)
    if mi < 0 or ni < 0 or (mi == 0 and ni == 0):
        raise ValueError(f"模阶 (m,n) 必须非负且不全零，实际 ({m!r}, {n!r})")
    f_mode = C0 / (2.0 * math.sqrt(eps)) * math.sqrt((mi / a) ** 2 + (ni / b) ** 2)
    f_eval = f_mode if f_hz is None else float(f_hz)
    if not math.isfinite(f_eval) or f_eval <= 0.0:
        raise ValueError(f"f_hz 必须为正有限数，实际 {f_hz!r}")
    lam = C0 / (f_eval * math.sqrt(eps))
    required = float(threshold_frac) * lam

    xs = [k * a / mi for k in range(mi + 1)] if mi > 0 else [float(x_m)]
    ys = [jy * b / ni for jy in range(ni + 1)] if ni > 0 else [float(y_m)]
    distance = math.inf
    best_x = xs[0]
    best_y = ys[0]
    for ax in xs:
        for ay in ys:
            d = math.hypot(float(x_m) - ax, float(y_m) - ay)
            if d < distance:
                distance = d
                best_x = ax
                best_y = ay
    margin = distance - required
    verdict = "clear" if distance >= required else "too_close"
    return ClearanceVerdict(
        verdict=verdict,
        distance_m=distance,
        required_m=required,
        margin_m=margin,
        m=mi,
        n=ni,
        f_hz=f_eval,
        wavelength_m=lam,
        antinode_x_m=best_x,
        antinode_y_m=best_y,
    )


# ─── DC-bias 折减 ────────────────────────────────────────────────────────────


def dc_bias_effective_c(
    c_nominal: float,
    v_bias: float,
    curve_v: Sequence[float] | np.ndarray | None,
    curve_c: Sequence[float] | np.ndarray | None,
) -> tuple[float, str]:
    """DC-bias 有效电容查表+线性插值（不虚构曲线，铁律 7）。

    状态标记（第二返回值，如实降级不虚构）：
    - "no_derating"：curve_v/curve_c 任一缺失 → 原样返回 c_nominal；
    - "no_bias"：v_bias ≤ 0（无偏压无需折减）；
    - "derated"：曲线查表线性插值（np.interp，端点外**夹持**不外推——
      超出曲线电压范围时如实夹到端点值）。

    Args:
        c_nominal: 名义电容（F）。
        v_bias: 直流偏压（V）。
        curve_v: 曲线电压栅格（V，严格升序），或 None。
        curve_c: 曲线对应有效电容（F，正数），或 None。

    Returns:
        (c_effective, status) 二元组。
    """
    vb = float(v_bias)
    if not math.isfinite(vb):
        # fail-closed 顺序：入参校验先于降级路径（审查轨 A P2-7）
        raise ValueError(f"v_bias 必须为有限数，实际 {v_bias!r}")
    if curve_v is None or curve_c is None:
        return float(c_nominal), "no_derating"
    if vb <= 0.0:
        return float(c_nominal), "no_bias"
    vv = np.asarray(curve_v, dtype=float)
    cc = np.asarray(curve_c, dtype=float)
    if vv.ndim != 1 or cc.ndim != 1 or vv.shape != cc.shape or vv.size < 2:
        raise ValueError(f"dc_bias 曲线必须是一维等长（≥2 点）数组，实际 v {np.shape(curve_v)} c {np.shape(curve_c)}")
    if np.any(np.diff(vv) <= 0.0):
        raise ValueError(f"curve_v 必须严格升序，实际 {vv}")
    if np.any(cc <= 0.0) or not np.all(np.isfinite(cc)):
        raise ValueError(f"curve_c 必须全为正有限数，实际 {cc}")
    effective = float(np.interp(vb, vv, cc))
    return effective, "derated"


# ─── decap 库 schema ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DecapSpec:
    """decap 库单条规格（schema 与 provenance 纪律见模块 docstring）。

    Attributes:
        part: 器件描述名（库键为 part_id）。
        c_f: 名义电容（F，正数）。
        esr_ohm: 等效串联电阻（Ω，非负）。
        esl_h: 等效串联电感（H，非负）。
        provenance: 数据出处（强制非空；首批条目一律
            "typical_engineering_value: 待 vendor 实测替换" 开头，铁律 7）。
        mount_l_h: 板级安装电感典型值（H，非负；库条目可填典型量级或由
            service 按板参数用 mount_inductance 精算后覆盖）。
        dc_bias_curve: DC-bias 折减曲线 ((v, c) 对序列，v 严格升序) 或 None
            （缺曲线如实 no_derating，不虚构）。
        cost: 选型成本权重（greedy_decap_select 的成本口径；1.0=每颗等价，
            可按 BOM 价/占板面积自定义）。
        notes: 备注。
    """

    part: str
    c_f: float
    esr_ohm: float
    esl_h: float
    provenance: str
    mount_l_h: float = 0.0
    dc_bias_curve: tuple[tuple[float, float], ...] | None = None
    cost: float = 1.0
    notes: str = ""

    def __post_init__(self) -> None:
        part = str(self.part)
        if not part:
            raise ValueError("DecapSpec.part 必须非空")
        cap = float(self.c_f)
        if not math.isfinite(cap) or cap <= 0.0:
            raise ValueError(f"DecapSpec {part!r}: c_f 必须为正有限数，实际 {self.c_f!r}")
        esr = float(self.esr_ohm)
        if not math.isfinite(esr) or esr < 0.0:
            raise ValueError(f"DecapSpec {part!r}: esr_ohm 必须为非负有限数，实际 {self.esr_ohm!r}")
        esl = float(self.esl_h)
        if not math.isfinite(esl) or esl < 0.0:
            raise ValueError(f"DecapSpec {part!r}: esl_h 必须为非负有限数，实际 {self.esl_h!r}")
        mount = float(self.mount_l_h)
        if not math.isfinite(mount) or mount < 0.0:
            raise ValueError(f"DecapSpec {part!r}: mount_l_h 必须为非负有限数，实际 {self.mount_l_h!r}")
        provenance = str(self.provenance)
        if not provenance.strip():
            # provenance 门（铁律 7）：无出处的参数不得入库
            raise ValueError(f"DecapSpec {part!r}: provenance 强制非空（typical_engineering_value: 待 vendor 实测替换）")
        curve = self.dc_bias_curve
        if curve is not None:
            curve_t = tuple(curve)
            if len(curve_t) < 2:
                raise ValueError(f"DecapSpec {part!r}: dc_bias_curve 至少 2 点，实际 {len(curve_t)}")
            for v, c in curve_t:
                if not math.isfinite(float(v)) or not math.isfinite(float(c)) or float(c) <= 0.0:
                    raise ValueError(f"DecapSpec {part!r}: dc_bias_curve 点 (v={v!r}, c={c!r}) 非法（需有限且 c>0）")
            vs = [float(v) for v, _ in curve_t]
            if any(vs[i + 1] <= vs[i] for i in range(len(vs) - 1)):
                raise ValueError(f"DecapSpec {part!r}: dc_bias_curve 电压必须严格升序，实际 {vs}")
            object.__setattr__(self, "dc_bias_curve", curve_t)
        cost = float(self.cost)
        if not math.isfinite(cost) or cost <= 0.0:
            raise ValueError(f"DecapSpec {part!r}: cost 必须为正有限数，实际 {self.cost!r}")

    @property
    def curve_v(self) -> tuple[float, ...] | None:
        return None if self.dc_bias_curve is None else tuple(v for v, _ in self.dc_bias_curve)

    @property
    def curve_c(self) -> tuple[float, ...] | None:
        return None if self.dc_bias_curve is None else tuple(c for _, c in self.dc_bias_curve)

    def effective_c(self, v_bias: float) -> tuple[float, str]:
        """按 DC-bias 曲线返回 (有效电容, 状态标记)，无曲线 no_derating。"""
        return dc_bias_effective_c(self.c_f, v_bias, self.curve_v, self.curve_c)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 yaml 兼容字典（dc_bias_curve 为 {"v": [...], "c": [...]}）。"""
        payload: dict[str, Any] = {
            "part": self.part,
            "c_f": self.c_f,
            "esr_ohm": self.esr_ohm,
            "esl_h": self.esl_h,
            "provenance": self.provenance,
        }
        if self.mount_l_h != 0.0:
            payload["mount_l_h"] = self.mount_l_h
        if self.dc_bias_curve is not None:
            payload["dc_bias_curve"] = {"v": list(self.curve_v or ()), "c": list(self.curve_c or ())}
        if self.cost != 1.0:
            payload["cost"] = self.cost
        if self.notes:
            payload["notes"] = self.notes
        return payload

    @classmethod
    def from_dict(cls, part_id: str, raw: dict[str, Any]) -> DecapSpec:
        """从库条目字典构建（单条不合法即 ValueError 硬错，provenance 门）。"""
        if not isinstance(raw, dict):
            raise ValueError(f"decap 库条目 {part_id!r} 必须是映射，实际 {type(raw).__name__}")
        missing = [key for key in ("part", "c_f", "esr_ohm", "esl_h", "provenance") if raw.get(key) is None]
        if missing:
            raise ValueError(f"decap 库条目 {part_id!r} 缺必填字段: {missing}")
        curve_raw = raw.get("dc_bias_curve")
        curve: tuple[tuple[float, float], ...] | None = None
        if curve_raw is not None:
            if isinstance(curve_raw, dict):
                try:
                    curve = tuple((float(v), float(c)) for v, c in zip(curve_raw["v"], curve_raw["c"], strict=True))
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"dc_bias_curve dict 形须含 v/c 数值列表: {exc}") from None
            else:
                curve = tuple((float(v), float(c)) for v, c in curve_raw)
        return cls(
            part=str(raw["part"]),
            c_f=float(raw["c_f"]),
            esr_ohm=float(raw["esr_ohm"]),
            esl_h=float(raw["esl_h"]),
            provenance=str(raw["provenance"]),
            mount_l_h=float(raw.get("mount_l_h", 0.0)),
            dc_bias_curve=curve,
            cost=float(raw.get("cost", 1.0)),
            notes=str(raw.get("notes", "")),
        )


def load_decap_library(path: str | Path | None = None) -> dict[str, DecapSpec]:
    """加载 decap 库 yaml → {part_id: DecapSpec}（单条不合法即 ValueError 硬错）。

    缺省库 = configs/decap_library.yaml（DEFAULT_LIBRARY_PATH）。provenance
    门：条目 provenance 必须非空（铁律 7）。
    """
    lib_path = Path(path) if path is not None else DEFAULT_LIBRARY_PATH
    if not lib_path.exists():
        raise KeyError(f"decap 库不存在: {lib_path}")
    import yaml

    data = yaml.safe_load(lib_path.read_text(encoding="utf-8")) or {}
    raw_entries = data.get("decap_library") or {}
    if not isinstance(raw_entries, dict):
        raise ValueError(f"decap 库结构必须是 decap_library: {{part_id: ...}}: {lib_path}")
    if not raw_entries:
        raise ValueError(f"decap 库为空: {lib_path}")
    return {str(pid): DecapSpec.from_dict(str(pid), raw) for pid, raw in raw_entries.items()}


# ─── 整网合成 ────────────────────────────────────────────────────────────────


def _branch_impedance(item: DecapSpec | tuple[float, ...], freqs: np.ndarray) -> np.ndarray:
    """电容支路归一化：DecapSpec 或 (c, esr, esl[, mount_l]) 元组 → 复阻抗。"""
    if isinstance(item, DecapSpec):
        return decap_impedance(item.c_f, item.esr_ohm, item.esl_h, item.mount_l_h, freqs)
    tup = tuple(float(x) for x in item)
    if len(tup) == 3:
        return decap_impedance(tup[0], tup[1], tup[2], 0.0, freqs)
    if len(tup) == 4:
        return decap_impedance(tup[0], tup[1], tup[2], tup[3], freqs)
    raise ValueError(f"电容支路必须是 (c, esr, esl[, mount_l]) 三/四元组或 DecapSpec，实际长度 {len(tup)}")


def _parallel_impedance(y_sum: np.ndarray) -> np.ndarray:
    """导纳 → 阻抗（Y=0 → Z=∞+0j 显式处理，除零警告抑制不静默吞）。"""
    z = np.empty_like(y_sum, dtype=complex)
    zero = y_sum == 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        z_nonzero = 1.0 / np.where(zero, 1.0, y_sum)
    z[~zero] = z_nonzero[~zero]
    z[zero] = np.inf + 0.0j
    return z


def pdn_impedance_profile(
    vrm: VrmModel | None,
    bulk_caps: Iterable[DecapSpec | tuple[float, ...]] | None,
    decaps: Iterable[DecapSpec | tuple[float, ...]] | None,
    f: float | Sequence[float] | np.ndarray,
) -> np.ndarray:
    """整网 PDN 阻抗谱：Z(f) = 1/Y(f)，Y = 1/Z_vrm + Σ 1/Z_capᵢ（并联导纳求和）。

    全频段无任何支路（vrm=None 且无电容）时 Y≡0 → Z≡∞（显式 inf，不静默）。

    Args:
        vrm: VRM 模型（VrmModel 或 None）。
        bulk_caps: 散装电容序列（DecapSpec 或 (c, esr, esl[, mount_l]) 元组）或 None。
        decaps: 去耦电容序列（同上）或 None。
        f: 频率（Hz）。

    Returns:
        复阻抗数组（Ω），与 f 同长。
    """
    freqs = _freq_array(f)
    y_total = np.zeros(freqs.shape, dtype=complex)
    if vrm is not None:
        y_total += 1.0 / vrm_model(freqs, vrm.r0, vrm.l0, vrm.r1, vrm.l1)
    for item in bulk_caps or ():
        y_total += 1.0 / _branch_impedance(item, freqs)
    for item in decaps or ():
        y_total += 1.0 / _branch_impedance(item, freqs)
    return _parallel_impedance(y_total)


# ─── 贪心选型 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GreedyResult:
    """greedy_decap_select 结果（选中列表+逐频裕量+infeasible 标记，不凑解）。"""

    selected_indices: tuple[int, ...]
    selected: tuple[DecapSpec, ...]
    total_cost: float
    z_profile: np.ndarray  # 最终整网复阻抗（含 baseline）
    z_target: np.ndarray  # 与 f 同长的目标阻抗
    margin_db: np.ndarray  # 逐频裕量 20log10(Z_target/|Z|)（正=达标；Z=∞ → −inf）
    excess: float  # 剩余超标量 Σ max(0, |Z|−Z_target)（0=全带达标）
    budget: float
    feasible: bool

    @property
    def infeasible(self) -> bool:
        """显式 infeasible 标记（全加完仍超标=True，不凑解）。"""
        return not self.feasible

    @property
    def n_selected(self) -> int:
        return len(self.selected_indices)


def _excess(z: np.ndarray, z_target: np.ndarray) -> float:
    """超标量：Σ_violating max(0, |Z|−Z_target)（线性域，inf 参与比较良定义）。"""
    violation = np.abs(z) - z_target
    return float(np.sum(np.maximum(violation, 0.0)))


def greedy_decap_select(
    candidates: Sequence[DecapSpec],
    z_target: float | Sequence[float] | np.ndarray,
    f: float | Sequence[float] | np.ndarray,
    budget: float,
    baseline_vrm: VrmModel | None = None,
    baseline_caps: Iterable[DecapSpec | tuple[float, ...]] | None = None,
) -> GreedyResult:
    """确定性贪心 decap 选型（每步选"超标频段改善/成本比"最大的电容）。

    口径：
    - 目标：全带 Z(f) ≤ Z_target(f)（线性域逐频比较）。
    - 每步在"预算可负担且未选"的候选里，选 improvement/cost 最大者，
      improvement = 超标量减少值 = excess(前) − excess(后)（excess=Σ 违标频点
      max(0,|Z|−Z_target)）；并列时取索引最小者（确定性，无随机性）。
    - 停止：全带达标 / 预算耗尽 / 无任何候选能再改善（improvement ≤ 0）。
    - 全部加完（或提前无改善）仍超标 → feasible=False（显式 infeasible，
      不凑解：结果保留已达的最优贪心态+剩余 excess 如实上报）。
    - 成本单调性（同等条件下加预算不劣化）：当预算约束不改变逐步可达集
      （如同质 cost=1 候选池+整数预算）时，贪心路径呈前缀包含关系，超标量
      沿路径单调不增——该实现性质由单测钉（同 cost 候选池两档预算）。

    注意：candidates 的 mount_l_h/dc_bias_curve 参与阻抗合成（DC-bias 折减
    由调用方先经 effective_c 生成等效候选，本函数不做偏压语义假设）；
    baseline 为空且无任何支路时初值 Z=∞，首步所有候选 improvement=∞ 并列、
    按索引 tie-break——正式使用建议给 baseline_vrm/baseline_caps 使初值有限。

    Args:
        candidates: 候选电容池（DecapSpec 序列；同一 spec 允许重复出现=多颗）。
        z_target: 目标阻抗（标量或与 f 同长序列）。
        f: 频率（Hz）。
        budget: 成本预算（float；Σcost 上限）。
        baseline_vrm: 基线 VRM（可 None）。
        baseline_caps: 基线已装电容序列（可 None）。

    Returns:
        GreedyResult。
    """
    freqs = _freq_array(f)
    zt = np.asarray(z_target, dtype=float)
    if zt.ndim == 0:
        zt = np.full(freqs.shape, float(zt))
    if zt.shape != freqs.shape:
        raise ValueError(f"z_target 与 f 长度不一致：{zt.shape} vs {freqs.shape}")
    if np.any(zt <= 0.0) or not np.all(np.isfinite(zt)):
        raise ValueError("z_target 必须全为正有限数")
    budget_left = float(budget)
    if not math.isfinite(budget_left) or budget_left < 0.0:
        raise ValueError(f"budget 必须为非负有限数，实际 {budget!r}")

    y_now = np.zeros(freqs.shape, dtype=complex)
    if baseline_vrm is not None:
        y_now += 1.0 / vrm_model(freqs, baseline_vrm.r0, baseline_vrm.l0, baseline_vrm.r1, baseline_vrm.l1)
    for item in baseline_caps or ():
        y_now += 1.0 / _branch_impedance(item, freqs)
    z_candidate_cache = [1.0 / _branch_impedance(spec, freqs) for spec in candidates]

    selected_indices: list[int] = []
    selected_set: set[int] = set()
    selected_specs: list[DecapSpec] = []
    total_cost = 0.0
    excess_now = _excess(_parallel_impedance(y_now), zt)

    while excess_now > 0.0 and budget_left > 0.0:
        best_idx = -1
        best_ratio = 0.0
        best_y = y_now
        best_excess = excess_now
        best_cost = 0.0
        for i, spec in enumerate(candidates):
            if i in selected_set:
                continue  # 池内同一槽位只选一次（多颗=池内重复出现同 spec）
            cost_i = float(spec.cost)
            if cost_i > budget_left:
                continue
            y_try = y_now + z_candidate_cache[i]
            excess_try = _excess(_parallel_impedance(y_try), zt)
            improvement = excess_now - excess_try
            if improvement <= 0.0:
                continue
            ratio = improvement / cost_i
            if ratio > best_ratio:
                best_idx = i
                best_ratio = ratio
                best_y = y_try
                best_excess = excess_try
                best_cost = cost_i
        if best_idx < 0:
            break  # 无候选可再改善：如实停（不凑解）
        selected_indices.append(best_idx)
        selected_set.add(best_idx)
        selected_specs.append(candidates[best_idx])
        total_cost += best_cost
        budget_left -= best_cost
        y_now = best_y
        excess_now = best_excess

    z_final = _parallel_impedance(y_now)
    with np.errstate(divide="ignore"):
        margin_db = 20.0 * np.log10(zt / np.abs(z_final))
    return GreedyResult(
        selected_indices=tuple(selected_indices),
        selected=tuple(selected_specs),
        total_cost=total_cost,
        z_profile=z_final,
        z_target=zt,
        margin_db=margin_db,
        excess=excess_now,
        budget=float(budget),
        feasible=bool(excess_now <= 0.0),
    )
