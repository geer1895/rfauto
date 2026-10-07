"""TF-3 短路 stub / K-inverter 耦合族综合内核：Richards 变换 + 倒置器闭式 + λ/4 实现。

法源（铁律 5：来源写 docstring；裁判=独立来源不自证，#118）：

- Richards 变换 Ω = tan(θ0·f/f0)/tan(θ0)：P.I. Richards (1948),
  "Resistor-Transmission-Line Circuits", Proc. IRE 36(2):217-220
  （doi:10.1109/JRPROC.1948.229621，付费墙；教科书转述见 Hong &
  Lancaster《Microstrip Filters for RF/Microwave Applications》Wiley
  2001, Ch.5——本文以"分布参数网络在 Ω 域呈集总行为"为准，恒等式由
  tan/atan 往返与 θ 线性度数值钉死）。缺省 θ0 = π/4@f0（commensurate
  单位元 λ/8@f0 口径）；λ/4@f0 短路 stub 的电长度映射另由
  stub_elec_length 给出（θ = π·f/(2·f0)，f0 处恰 π/2）。
- K/J-inverter 经典式（低通 g_k → 带通倒置器值）：J_01/Y0 =
  sqrt(π·FBW/(2·g0·g1))、J_j,j+1/Y0 = (π·FBW/2)/sqrt(g_j·g_{j+1})、
  J_n,n+1/Y0 = sqrt(π·FBW/(2·g_n·g_{n+1}))：Hong & Lancaster 2001
  eq.(5.32)（原书 §5.2；MYJ《Microwave Filters, Impedance-Matching
  Networks, and Coupling Structures》McGraw-Hill 1964 §8.03 同族）。
  K 视角（串联谐振器对偶）与 J 值同数值（K_01/Z0 = J_01/Y0），本模块
  统一以归一化倒置器值 j̄ = J/Y0 = K/Z0 输出。
- 并联电纳 ↔ K-inverter 精确等效（本文件自推导，ABCD 逐元素展开，
  tests 钉 ≤1e-12）：并联电纳 b̄（b̄ = B·Z0，线路阻抗 Z0）等效为两侧
  各 −θ/2 负电长度线 + 理想 K 倒置器，其中 tan(θ) = 2/b̄、K/Z0 =
  tan(θ/2)（**带符号**，恒等式所需；幅值口径 |K/Z0| 为文献常引形）。
  反演 b̄ = 1/k − k（对带符号 k 成立）。与 MYJ §8.03
  "电抗 + 负电长度 ↔ 倒置器"同口径（MYJ 原式按对偶/符号约定转述常
  见出入，本文以 ABCD 代数恒等式为准，不受转述歧义影响）。
- λ/4 变压器实现（倒置器 → 物理网表）：λ/4 线在 f0 处恰为 K = Z_line
  的理想倒置器（Pozar《Microwave Engineering》4th ed. §8.6 口径），
  连接线阻抗 Z_c,j = Z0/j̄_j；谐振器 = λ/4 短路并联 stub，其电纳斜率
  参数 b̄_stub = (ω0/2)·dB/dω = π/(4·Z_S)。与倒置器式组自洽要求
  b̄ = (π/2)·Y0（MYJ 电纳斜率参数口径）→ 全部 stub 阻抗
  Z_S = Z0/2（tests 钉逐位）。
- 频响验证面（声明近似源）：ABCD 级联（传输线矩阵自实现，纯 numpy）
  对照理想带通原型 |S21|² = 1/(1+ω_lp^{2N})，ω_lp = (f/f0 − f0/f)/FBW
  为**窄带近似映射**——本实现的 stub 网络精确活在 Richards Ω = cot(θ)
  域，与常规映射间存在 O(FBW) 固有差（非代码缺陷，如实登记）。
  实测（butter N=5、FBW=0.05）：−3dB 带宽 rel 误差 −3.7%（≤5% 预声明
  门）、带边位置 ≤0.12%、内带（|ω_lp|≤0.8）偏差 ≤0.1dB（tests 钉）。
  chebyshev（0.1dB、N=3）内带偏差 ≤0.05dB。FBW→0 时误差单调收敛
  （窄带收敛性 tests 钉）。

纯算法零 IO；不进 calculators 注册表（域内约定，消费者是 service 层）。
数值 0.0 合法，判缺失一律 is not None（#364④）；bool 显式拒收
（df7+⑯）。单位钉在参数名（Hz/Ω）。g_k 序列由调用方供给（可来自
core/lc_filter.cauer_ladder_gk——本模块不 import，保持测试双路径独立）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "DEFAULT_THETA0",
    "SIR_STUB_SLOPE",
    "StubFilter",
    "band_edges_3db",
    "inverter_table",
    "k_to_shunt_b",
    "richards_omega",
    "richards_omega_inverse",
    "shunt_b_to_k",
    "shunt_b_to_neg_length",
    "stub_elec_length",
    "stub_filter_design",
    "stub_filter_sparams",
]

#: commensurate 单位元缺省电长度（λ/8@f0 口径）
DEFAULT_THETA0 = math.pi / 4.0
#: 倒置器式组自洽的 stub 电纳斜率参数（归一，b̄ = (π/2)·Y0 口径）
SIR_STUB_SLOPE = math.pi / 2.0


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


# ─── 1. Richards 变换 ────────────────────────────────────────────────────────


def richards_omega(f_hz: float, f0_hz: float, theta0: float = DEFAULT_THETA0) -> float:
    """Richards 变换 Ω = tan(θ0·f/f0)/tan(θ0)（f0 处 Ω = 1，逐位）。

    f_hz：物理频率（>=0）；f0_hz：参考频率（>0）；theta0：commensurate
    单位元在 f0 的电长度（(0, π/2)，缺省 π/4 = λ/8@f0）。恒等式：
    Ω(f0) == 1.0 逐位；Ω(0) == 0.0 逐位；f→Ω→f 往返逐位（tests 钉）。
    """
    f = _finite(f_hz, "f_hz")
    if f < 0.0:
        raise ValueError(f"f_hz 必须 >=0，实际 {f}")
    f0 = _positive(f0_hz, "f0_hz")
    t0 = _finite(theta0, "theta0")
    if not (0.0 < t0 < math.pi / 2.0):
        raise ValueError(f"theta0 必须落在 (0, π/2)，实际 {t0}")
    return math.tan(t0 * f / f0) / math.tan(t0)


def richards_omega_inverse(
    omega: float, f0_hz: float, theta0: float = DEFAULT_THETA0
) -> float:
    """Richards 逆变换 f = f0·atan(Ω·tanθ0)/θ0（Ω>=0，主支）。

    omega：Richards 变量（>=0）；返回物理频率（Hz）。Ω<0 无物理频率
    对应（主支），显式 ValueError。
    """
    w = _finite(omega, "omega")
    if w < 0.0:
        raise ValueError(f"omega 必须 >=0（主支），实际 {w}")
    f0 = _positive(f0_hz, "f0_hz")
    t0 = _finite(theta0, "theta0")
    if not (0.0 < t0 < math.pi / 2.0):
        raise ValueError(f"theta0 必须落在 (0, π/2)，实际 {t0}")
    return f0 * math.atan(w * math.tan(t0)) / t0


def stub_elec_length(f_hz: float, f0_hz: float) -> float:
    """λ/4@f0 短路 stub 的电长度映射 θ(f) = π·f/(2·f0)（f0 处恰 π/2，逐位）。

    这是全部 stub/连接线共用的 commensurate 电长度律（StubFilter 网表
    的唯一频率依赖）。
    """
    f = _finite(f_hz, "f_hz")
    if f < 0.0:
        raise ValueError(f"f_hz 必须 >=0，实际 {f}")
    f0 = _positive(f0_hz, "f0_hz")
    return math.pi * f / (2.0 * f0)


# ─── 2. 并联电纳 ↔ K-inverter 精确等效 ───────────────────────────────────────


def shunt_b_to_neg_length(b_norm: float) -> float:
    """归一并联电纳 b̄ = B·Z0 → 等效负电长度 θ：tan(θ) = 2/b̄（自推导恒等式）。

    b̄ ≠ 0（b̄=0 即无并联元件，等效退化，显式 ValueError）。b̄>0 给
    θ∈(0,π/2)、b̄<0 给 θ∈(−π/2,0)（负长度语义：实现时从相邻 90° 线
    中扣除）。等效网络 = [−θ/2 线][K 倒置器][−θ/2 线]（K 由
    shunt_b_to_k 给出），ABCD 与单个并联元件逐元素相等（tests 钉
    ≤1e-12）。
    """
    b = _finite(b_norm, "b_norm")
    if b == 0.0:
        raise ValueError("b_norm=0 即无并联元件，K 等效退化（显式拒绝）")
    return math.atan(2.0 / b)


def shunt_b_to_k(b_norm: float) -> float:
    """归一并联电纳 → 等效倒置器 **带符号** K/Z0 = tan(θ/2)（θ 由 tan(θ)=2/b̄）。

    恒等式（自推导，ABCD 代数）：[并联 jB] == [−θ/2 线][K][−θ/2 线]，
    展开后 A=D=1、B 项=0、C 项恰为 jb̄——该恒等式要求 K 矩阵取
    **带符号** k = tan(θ/2)（b̄>0 → k>0；b̄<0 → k<0；ABCD 等效 tests 钉
    ≤1e-12）。文献常引的幅值口径 |K/Z0| = |tan(θ/2)| 是其绝对值，取幅
    值时等效网络整体差一符号（−1 级联不变量），设计阻抗量级不受影响。
    反演闭式 b̄ = 1/k − k（对带符号 k 同样成立，k_to_shunt_b）。
    """
    theta = shunt_b_to_neg_length(b_norm)
    return math.tan(theta / 2.0)


def k_to_shunt_b(k_norm: float) -> float:
    """带符号倒置器 K/Z0 → 等效归一并联电纳 b̄ = 1/k − k（shunt_b_to_k 逆）。

    k 非（0 的）有限数即 ValueError；带符号 k 均可（b̄<0 ↔ k<0）。
    """
    k = _finite(k_norm, "k_norm")
    if k == 0.0:
        raise ValueError("k_norm=0 无定义（1/k 发散），显式拒绝")
    return 1.0 / k - k


# ─── 3. g_k → 倒置器表（Hong-Lancaster eq. 5.32 口径）────────────────────────


def inverter_table(g: list[float], fbw: float) -> list[float]:
    """低通原型 g_k → 归一化倒置器值表 [j̄_01, j̄_12, ..., j̄_n,n+1]。

    g = [g0, g1, ..., gn, gn+1]（全正，等端接口径 g0=gn+1=1 时不强制）；
    fbw：分数带宽（(0,1)）。闭式（Hong & Lancaster 2001 eq. 5.32）：
    j̄_01 = sqrt(π·FBW/(2·g0·g1))；j̄_j,j+1 = (π·FBW/2)/sqrt(g_j·g_{j+1})；
    j̄_n,n+1 = sqrt(π·FBW/(2·g_n·g_{n+1}))。返回 n+1 个值（n = len(g)−2 ≥ 1）。
    倒置器实现（λ/4 变压器）的连接线阻抗 Z_c,j = Z0/j̄_j 见
    stub_filter_design。
    """
    if not isinstance(g, (list, tuple)) or len(g) == 0:
        raise ValueError("g 必须为非空序列 [g0, g1, ..., gn, gn+1]")
    gvals = [_positive(v, f"g[{i}]") for i, v in enumerate(g)]
    if len(gvals) < 3:
        raise ValueError(f"g 至少含 [g0, g1, g2]（n>=1），实际 len={len(gvals)}")
    f = _finite(fbw, "fbw")
    if not (0.0 < f < 1.0):
        raise ValueError(f"fbw 必须落在 (0,1)，实际 {f}")
    n = len(gvals) - 2
    out = [math.sqrt(math.pi * f / (2.0 * gvals[0] * gvals[1]))]
    for j in range(1, n):
        out.append(math.pi * f / (2.0 * math.sqrt(gvals[j] * gvals[j + 1])))
    out.append(math.sqrt(math.pi * f / (2.0 * gvals[n] * gvals[n + 1])))
    return out


# ─── 4. 短路 stub 滤波器网表（λ/4 变压器实现）────────────────────────────────


@dataclass
class StubFilter:
    """短路 stub 带通滤波器网表（λ/4 变压器实现，全部线 f0 处 90°）。

    结构：[line_0][stub_1][line_1]...[stub_n][line_n]——n 个 λ/4 短路
    并联 stub（阻抗 stub_impedances[k]，全部 Z0/2）与 n+1 段 λ/4 连接
    线（阻抗 line_impedances[j] = Z0/j̄_j，两端接 z0_ohm）。euler_pi2 =
    π/2（全部元件 f0 处电长度，逐位常数）。口径：n>=2（N=1 时两端
    外部耦合使 −3dB 带宽 = 2×FBW，与标准式组的内点 k 口径不自洽，
    显式拒绝——见 stub_filter_design）。
    """

    order: int  # n（stub 数）
    fbw: float
    f0_hz: float
    z0_ohm: float
    stub_impedances: list[float]  # n 项（全部 = z0/2）
    line_impedances: list[float]  # n+1 项（Z0/j̄_j，源端→负载端序）
    inverter_values: list[float]  # n+1 项归一化倒置器值 j̄
    g_values: list[float]  # 原型 g_k（透传存档）
    euler_pi2: float = math.pi / 2.0
    sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": int(self.order),
            "fbw": self.fbw,
            "f0_hz": self.f0_hz,
            "z0_ohm": self.z0_ohm,
            "stub_impedances": list(self.stub_impedances),
            "line_impedances": list(self.line_impedances),
            "inverter_values": list(self.inverter_values),
            "g_values": list(self.g_values),
            "euler_pi2": self.euler_pi2,
            "sources": dict(self.sources),
        }


def stub_filter_design(
    g: list[float], fbw: float, f0_hz: float, z0_ohm: float = 50.0
) -> StubFilter:
    """由低通 g_k 综合短路 stub 带通滤波器网表（λ/4 变压器实现）。

    谐振器：全部 λ/4 短路并联 stub，阻抗 Z_S = 1/(2·Y0) = z0/2（由
    倒置器式组的自洽斜率 b̄ = (π/2)·Y0 与 b̄_stub = π/(4·Z_S) 闭式，
    tests 钉逐位）。连接线：λ/4，阻抗 Z0/j̄_j（λ/4 线在 f0 恰为
    K = Z_c 理想倒置器，Pozar 4th §8.6 口径）。

    判据（#122 先行）：n < 2（N=1 口径不自洽）/ fbw ∉ (0,1) / g 非法 /
    f0、z0 非正 → ValueError。响应面精度与近似源声明见模块 docstring。
    """
    jbar = inverter_table(g, fbw)
    n = len(jbar) - 1
    if n < 2:
        raise ValueError(
            "短路 stub 实现要求 n>=2（N=1 两端皆外部耦合，−3dB 带宽"
            "=2×FBW 与标准式组不自洽；口径见模块 docstring）"
        )
    z0 = _positive(z0_ohm, "z0_ohm")
    f0 = _positive(f0_hz, "f0_hz")
    gvals = [_positive(v, f"g[{i}]") for i, v in enumerate(g)]
    zs = z0 / 2.0  # b̄_stub = π/(4 Z_S) = (π/2)·Y0 ⇒ Z_S = 1/(2 Y0)
    return StubFilter(
        order=n,
        fbw=float(fbw),
        f0_hz=f0,
        z0_ohm=z0,
        stub_impedances=[zs] * n,
        line_impedances=[z0 / j for j in jbar],
        inverter_values=list(jbar),
        g_values=gvals,
        sources={
            "inverter_formulas": "Hong & Lancaster 2001 eq.(5.32); MYJ 1964 §8.03",
            "realization": "quarter-wave transformer lines (Pozar 4th ed. §8.6) "
            "+ short-circuited shunt stubs Zs=Z0/2 (slope b=(pi/2)Y0, MYJ)",
            "response_referee": "narrow-band bandpass mapping (declared approximation; "
            "exact domain is Richards Omega=cot(theta))",
        },
    )


# ─── 5. ABCD 频响面 ──────────────────────────────────────────────────────────


def _tl_line_abcd(theta: np.ndarray, z_ohm: float) -> tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray
]:
    """传输线 ABCD（复数组四元组）：[[cosθ, jZ sinθ],[j sinθ/Z, cosθ]]。"""
    c = np.cos(theta)
    s = np.sin(theta)
    return c, 1j * z_ohm * s, 1j * s / z_ohm, c


def _shunt_stub_abcd(theta: np.ndarray, z_ohm: float) -> tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray
]:
    """λ/4 短路并联 stub 的 ABCD：Y_in = −j·cot(θ)/Z_S → [[1,0],[Y,1]]。"""
    with np.errstate(divide="ignore", invalid="ignore"):
        cot = np.cos(theta) / np.sin(theta)
    return (
        np.ones_like(theta),
        np.zeros_like(theta),
        -1j * cot / z_ohm,
        np.ones_like(theta),
    )


def stub_filter_sparams(
    net: StubFilter, freqs_hz: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """网表频响：ABCD 级联 → (S11, S21) 复数组（端接 net.z0_ohm）。

    元件序：[line_0][stub_1][line_1]...[stub_n][line_n]，全部按
    θ = π·f/(2·f0) commensurate 律取电长度。
    """
    freqs = np.atleast_1d(np.asarray(freqs_hz, dtype=float))
    theta = np.pi * freqs / (2.0 * net.f0_hz)
    a = np.ones_like(freqs, dtype=complex)
    b = np.zeros_like(freqs, dtype=complex)
    c = np.zeros_like(freqs, dtype=complex)
    d = np.ones_like(freqs, dtype=complex)
    lines = net.line_impedances
    stubs = net.stub_impedances
    for j in range(net.order):
        la, lb, lc, ld = _tl_line_abcd(theta, lines[j])
        a, b, c, d = a * la + b * lc, a * lb + b * ld, c * la + d * lc, c * lb + d * ld
        sa, sb, sc, sd = _shunt_stub_abcd(theta, stubs[j])
        a, b, c, d = a * sa + b * sc, a * sb + b * sd, c * sa + d * sc, c * sb + d * sd
    la, lb, lc, ld = _tl_line_abcd(theta, lines[net.order])
    a, b, c, d = a * la + b * lc, a * lb + b * ld, c * la + d * lc, c * lb + d * ld
    z0 = net.z0_ohm
    den = a + b / z0 + c * z0 + d
    s21 = 2.0 / den
    s11 = (a + b / z0 - c * z0 - d) / den
    return s11, s21


def band_edges_3db(
    freqs_hz: np.ndarray, s21: np.ndarray, level: float = 0.5
) -> tuple[float | None, float | None]:
    """在频网格上找 |S21|² 首末次跌破 level（缺省 −3.0103dB 即 0.5）的频率。

    返回 (f_lo, f_hi)（Hz，线性插值）；网格须覆盖整条通带（从阻带起）。
    任一侧无交越 → 该侧 None（调用方自行处置，不凑值）。
    """
    freqs = np.asarray(freqs_hz, dtype=float)
    p = np.abs(np.asarray(s21, dtype=complex)) ** 2
    f_lo: float | None = None
    f_hi: float | None = None
    for i in range(1, freqs.size):
        up = p[i - 1] < level <= p[i]
        dn = p[i - 1] >= level > p[i]
        if up and f_lo is None:
            frac = (level - p[i - 1]) / (p[i] - p[i - 1])
            f_lo = float(freqs[i - 1] + frac * (freqs[i] - freqs[i - 1]))
        if dn:
            frac = (p[i - 1] - level) / (p[i - 1] - p[i])
            f_hi = float(freqs[i - 1] + frac * (freqs[i] - freqs[i - 1]))
    return f_lo, f_hi
