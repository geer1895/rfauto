"""MT-5 三阶 PLL 环路滤波器综合内核（round17 规格，T1/T2/T3 设计面闭式+峰值相位放置迭代）。

规格：研究扩充 round17 §二 MT-5（P1/S）：
「Banerjee SNAA106C（TI 免费）T1/T2/T3→C1/C2/R2/C3 闭式+相位裕度迭代。
验收：回代 open_loop_transfer 复现目标 f_c/PM」。

与 :mod:`rfauto.core.pll_budget` 互补：彼为二阶 II 型 (ωn, ζ) 分析/预算面，
本模块是三阶（CP+二阶 RC 主网络+附加 R3·C3 极点）**综合**面——给定环路带宽
f_c（开环穿越）与相位裕度 PM 反解元件值。pll_budget 既有语义零改动（规格
补强项「pll_budget 接 MT-5 综合入口」属消费侧接线，本模块不回改预算内核，
只做被接的综合面）。

设计面口径（Banerjee T 参数化，电荷泵/有源两拓扑同形）::

    Z(s) = (1 + s·T2) / (s·A0·(1 + s·T1)·(1 + s·T3))          滤波器阻抗
    G(s) = (Kφ·Kvco/(N·A0))·(1 + s·T2)/(s²·(1+s·T1)·(1+s·T3))  开环传函
    PM = atan(ωc·T2) − atan(ωc·T1) − atan(ωc·T3)              相位裕度闭式

放置约定（规格未钉的设计自由度，显式化为 r=T3/T1 极点比+峰值相位放置）：
把穿越频率放在相位曲线**峰值**处（dPM/dω|ωc = 0）——Gardner《Phaselock
Techniques》二阶几何中值放置 ωc²·T1·T2 = 1 的三阶推广（r→0⁺ 极限逐位回到
Gardner 式，锚树实测）。记 u=ωc·T1、v=ωc·T2、ωc·T3=r·u，两条件::

    ① 峰值条件  v/(1+v²) = u/(1+u²) + r·u/(1+r²u²)
    ② PM 条件   atan(v) = PM + atan(u) + atan(r·u)

以 u 为迭代变量解：c(u)=①右端在 (0, min(1, 1/r)) 单调增 →
v(u)=2c/(1−√(1−4c²))（有理化形，小 c 数值稳定，v≥1 零点在穿越之外分支）
唯一；g(u)=atan(v)−atan(u)−atan(r·u)−PM 在 (0, u*] 端点变号二分
（g(0⁺)→90°−PM>0；u* 为可达界 c(u*)=1/2，g(u*)<0 即窗内）。可达 PM 窗 =
(45°−atan(u*)−atan(r·u*), 90°)，窗外显式报错（诚实域守卫，负例钉）。
总电容 A0 由增益条件 |G(jωc)|=1 闭式回代::

    A0 = (Kφ·Kvco/(N·ωc²))·√(1+v²)/√((1+u²)·(1+r²u²))

元件值闭式（CP 无源形；二阶主网络精确反演+附加极点 R3·C3=T3）::

    C1 = A0·T1/T2,  C2 = A0·(T2−T1)/T2,  R2 = T2/C2,  C3·R3 = T3

（C3 缺省取 c3_frac·A0、R3=T3/C3；或显式 r3_ohm → C3=T3/R3。）

穿越唯一性（二分合法性，预声明证明）::

    d(ln|G|)/dω = ωT2²/(1+ω²T2²) − 2/ω − ωT1²/(1+ω²T1²) − ωT3²/(1+ω²T3²) < 0

（零点项 ≤ 2/ω 恒成立：等价于 0 ≤ 2+ω²T2²；极点项恒负）→ |G(jω)| 严格
单调降 → 穿越唯一，数值二分必收敛。

CP 噪声→输出相位传递（闭环低通整形）：电荷泵电流噪声 i_n 注入滤波器输入，
θ_out = [Kvco·Z/s/(1+G)]·i_n；折算输入相位口径 i_n/Kφ 后输出 =
(N/Kφ)·H(s)·i_n（H=G/(1+G)）——带内增益 N/Kφ 恒等、带外随 H 低通滚降；
参考/分频器相位噪声同形（带内 20log10(N) 抬升，Banerjee 噪声记账口径，
与 pll_budget pll_output_noise_l 的参考支一致）。

闭环恒等式（锚树裁判，|G(jωc)|=1 的纯数学推论）::

    |H(jωc)| = 1/(2·sin(PM/2))   （PM=60°→0dB、45°→+2.32dB 经典带内峰化）
    |H(0)| = 1                    （II 型 DC 单位增益）

引源（#118：口径回文献，数值锚不赌文献数字）：

- D. Banerjee, "PLL Performance, Simulation, and Design," 4th ed., TI
  （SNAA106C 免费公开）——T1/T2/T3 时间常数参数化、CP 滤波器元件闭式与
  环路噪声记账口径；
- F. M. Gardner, "Phaselock Techniques," 3rd ed.——II 型环路相位峰值放置
  （二阶几何中值 ωc²T1T2=1）与相位裕度定义；
- 规格未给数值算例（SNAA106C 指方法论）→ 数值锚全部用闭式恒等式
  （Gardner 极限逐位/|H(jωc)| 恒等/峰值条件零导数/元件重构恒等）。

诚实边界（预声明）：
1. T 形阻抗对**有源**滤波器（运放隔离级联）与二阶无源网络**精确**；三阶
   无源网络的 C3 对前级有加载（物理网络阻抗分子含 s² 项，与单零点 T 形
   不严格相等）——工程口径 C3 ≪ A0，偏离量级随 c3_loading_ratio =
   C3/(C1+C2) 报告供消费侧自查；规格验收（回代 open_loop_transfer 复现
   f_c/PM）在 T 设计面精确成立。
2. 理想模型：不含 PFD 死区/采样效应/Kvco 非线性/压控端附加极点——PM 为
   该模型口径（pll_budget 同款"上界口径"语义）。
3. 锁定时间规格未给（任务条件项"若规格给"）——不实现，不留半成品。
4. 可达 PM 窗随 r 收窄（r 越大窗下限越高）；解的唯一性在物理参数域内
   实测成立，解后做穿越/PM 复核（残差入结果字段，超差显式报错）。

接口：传函/噪声整形 numpy 一维复数组进出；综合入参数值、出
LoopFilterSynthesis dataclass（to_dict 全 float，JSON 可序列化无 None）；
单位钉在参数名（Hz、s、F、Ω、A/rad、Hz/V）；数值 0.0 合法（判缺失一律
is not None，#364④）；bool 显式拒收（df7+⑯）；纯算法零 IO；不进
calculators 注册表的传函面只走 core 直调（综合面单键注册，corona 先例）。
"""

from __future__ import annotations

import cmath
import dataclasses
import math
from typing import Any

import numpy as np

_TWO_PI = 2.0 * math.pi
_INV_SQRT2 = 1.0 / math.sqrt(2.0)


# ─── 入参守卫（#140：注解不等于调用方真的传了；pll_budget 同款口径）─────────


def _finite(value: Any, name: str) -> float:
    """入参收敛为有限 float，非法即显式报错（bool/字符串显式拒收）。"""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} 必须是数字，不接受 {type(value).__name__}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    """入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，实际 {out!r}")
    return out


def _freq_array(value: Any, name: str) -> np.ndarray:
    """频率数组收敛：一维、有限、全 >0（偏移频率口径；单调性不约束——求值逐点）。"""
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} 必须是数值序列")
    if np.asarray(value).dtype == bool:
        raise ValueError(f"{name} 不接受布尔数组")
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 1 or arr.size < 1:
        raise ValueError(f"{name} 必须是长度 ≥1 的一维数组，实际形状 {arr.shape}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含非有限值")
    if float(np.min(arr)) <= 0.0:
        raise ValueError(f"{name} 必须全 >0（频率口径）")
    return arr


def _loop_gains(kp_a_per_rad: Any, kvco_hz_per_v: Any, n_div: Any) -> tuple[float, float, float]:
    """环路增益三参数收敛：Kφ>0、Kvco>0、N≥1（分数 N 合法）。"""
    kp = _positive(kp_a_per_rad, "kp_a_per_rad")
    kv = _positive(kvco_hz_per_v, "kvco_hz_per_v")
    n = _positive(n_div, "n_div")
    if n < 1.0:
        raise ValueError(f"n_div 必须 ≥1（分频比），实际 {n!r}")
    return kp, kv, n


def _time_constants(t1_s: Any, t2_s: Any, t3_s: Any) -> tuple[float, float, float]:
    """T1/T2/T3 时间常数收敛（全 >0）。"""
    t1 = _positive(t1_s, "t1_s")
    t2 = _positive(t2_s, "t2_s")
    t3 = _positive(t3_s, "t3_s")
    return t1, t2, t3


# ─── 传函（numpy 一维复数组进出）─────────────────────────────────────────────


def loop_filter_impedance(freqs_hz: Any, a0_f: Any, t1_s: Any, t2_s: Any, t3_s: Any) -> np.ndarray:
    """三阶滤波器阻抗 Z(s) = (1+sT2)/(s·A0·(1+sT1)·(1+sT3))（复数组）。

    A0=总电容 F；T1/T2/T3=极点/零点/极点时间常数 s。f→0 时 Z ~ 1/(s·A0)
    （积分形），f→∞ 时 |Z| ~ T2/(A0·T1·T3·ω²)。
    """
    a0 = _positive(a0_f, "a0_f")
    t1, t2, t3 = _time_constants(t1_s, t2_s, t3_s)
    w = _TWO_PI * _freq_array(freqs_hz, "freqs_hz")
    s = 1j * w
    return (1.0 + s * t2) / (s * a0 * (1.0 + s * t1) * (1.0 + s * t3))


def open_loop_transfer(
    freqs_hz: Any,
    kp_a_per_rad: Any,
    kvco_hz_per_v: Any,
    n_div: Any,
    a0_f: Any,
    t1_s: Any,
    t2_s: Any,
    t3_s: Any,
) -> np.ndarray:
    """开环传函 G(s) = (Kφ·Kvco_rad/N)·Z(s)/s（复数组；规格验收回代面）。"""
    kp, kv, n = _loop_gains(kp_a_per_rad, kvco_hz_per_v, n_div)
    z = loop_filter_impedance(freqs_hz, a0_f, t1_s, t2_s, t3_s)
    w = _TWO_PI * _freq_array(freqs_hz, "freqs_hz")
    return kp * (_TWO_PI * kv) * z / (1j * w * n)


def closed_loop_transfer(
    freqs_hz: Any,
    kp_a_per_rad: Any,
    kvco_hz_per_v: Any,
    n_div: Any,
    a0_f: Any,
    t1_s: Any,
    t2_s: Any,
    t3_s: Any,
) -> np.ndarray:
    """闭环传函 H(s) = G/(1+G)（复数组；|H(0)|=1，|H(jωc)|=1/(2sin(PM/2))）。"""
    g = open_loop_transfer(freqs_hz, kp_a_per_rad, kvco_hz_per_v, n_div, a0_f, t1_s, t2_s, t3_s)
    return g / (1.0 + g)


def error_transfer(
    freqs_hz: Any,
    kp_a_per_rad: Any,
    kvco_hz_per_v: Any,
    n_div: Any,
    a0_f: Any,
    t1_s: Any,
    t2_s: Any,
    t3_s: Any,
) -> np.ndarray:
    """误差传函 E(s) = 1−H = 1/(1+G)（复数组；VCO 噪声高通整形口径）。"""
    g = open_loop_transfer(freqs_hz, kp_a_per_rad, kvco_hz_per_v, n_div, a0_f, t1_s, t2_s, t3_s)
    return 1.0 / (1.0 + g)


def cp_noise_to_out_transfer(
    freqs_hz: Any,
    kp_a_per_rad: Any,
    kvco_hz_per_v: Any,
    n_div: Any,
    a0_f: Any,
    t1_s: Any,
    t2_s: Any,
    t3_s: Any,
) -> np.ndarray:
    """电荷泵电流噪声→输出相位传递 T_cp(s) = (N/Kφ)·H(s)（rad/A，复数组）。

    带内增益 N/Kφ 恒等（|H(0)|=1）、带外随 H 低通滚降——CP 噪声整形面
    （参考/分频器相位噪声同形，带内 20log10(N) 抬升，Banerjee 记账口径）。
    """
    kp, kv, n = _loop_gains(kp_a_per_rad, kvco_hz_per_v, n_div)
    h = closed_loop_transfer(freqs_hz, kp, kv, n, a0_f, t1_s, t2_s, t3_s)
    return (n / kp) * h


# ─── 数值穿越/裕度（|G| 严格单调降 → 穿越唯一，二分合法）───────────────────


def _open_loop_mag(w: float, kp: float, kv_rad: float, n: float, a0: float,
                   t1: float, t2: float, t3: float) -> float:
    """|G(jω)| 标量（二分内部口径）。"""
    num = (kp * kv_rad / (n * a0)) * math.sqrt(1.0 + (w * t2) ** 2)
    den = (w * w) * math.sqrt((1.0 + (w * t1) ** 2) * (1.0 + (w * t3) ** 2))
    return num / den


def _pm_deg_at(w: float, t1: float, t2: float, t3: float) -> float:
    """PM(ω) = atan(ωT2) − atan(ωT1) − atan(ωT3)（deg，闭式；T 形精确）。"""
    return math.degrees(math.atan(w * t2) - math.atan(w * t1) - math.atan(w * t3))


def _arg_g(w: float, t1: float, t2: float, t3: float) -> float:
    """arg G(jω)（rad；atan 求和无卷绕，弱稳定设计可 < −π，复指数口径自洽）。"""
    return math.atan(w * t2) - math.pi - math.atan(w * t1) - math.atan(w * t3)


def _closed_loop_mag(w: float, kp: float, kv_rad: float, n: float, a0: float,
                     t1: float, t2: float, t3: float) -> float:
    """|H(jω)| = |G/(1+G)| 标量（−3dB 二分内部口径）。"""
    g = _open_loop_mag(w, kp, kv_rad, n, a0, t1, t2, t3) * cmath.exp(1j * _arg_g(w, t1, t2, t3))
    return abs(g / (1.0 + g))


def crossover_and_pm(
    kp_a_per_rad: Any,
    kvco_hz_per_v: Any,
    n_div: Any,
    a0_f: Any,
    t1_s: Any,
    t2_s: Any,
    t3_s: Any,
) -> tuple[float, float]:
    """数值增益穿越 f_c（|G(jωc)|=1，对数二分）与该点相位裕度（deg）。

    |G| 严格单调降（模块头预声明证明）→ 穿越唯一；括弧从 ω0=1/√(T1·T3)
    向外十倍程扩展（上限 120 个 decade，越界即显式报错）。PM 用 T 形闭式
    （arg G(jωc)+180°）。返回 (f_crossover_hz, pm_deg)。
    """
    kp, kv, n = _loop_gains(kp_a_per_rad, kvco_hz_per_v, n_div)
    a0 = _positive(a0_f, "a0_f")
    t1, t2, t3 = _time_constants(t1_s, t2_s, t3_s)
    kv_rad = _TWO_PI * kv
    w0 = math.sqrt(1.0 / (t1 * t3))
    lo = w0
    for _ in range(120):
        if _open_loop_mag(lo, kp, kv_rad, n, a0, t1, t2, t3) > 1.0:
            break
        lo *= 0.1
    else:
        raise RuntimeError("开环幅值括弧下探越界（120 decade 无穿越）——参数病态")
    hi = w0
    for _ in range(120):
        if _open_loop_mag(hi, kp, kv_rad, n, a0, t1, t2, t3) < 1.0:
            break
        hi *= 10.0
    else:
        raise RuntimeError("开环幅值括弧上探越界（120 decade 无穿越）——参数病态")
    for _ in range(100):
        mid = math.sqrt(lo * hi)
        if _open_loop_mag(mid, kp, kv_rad, n, a0, t1, t2, t3) > 1.0:
            lo = mid
        else:
            hi = mid
    wc = math.sqrt(lo * hi)
    return wc / _TWO_PI, _pm_deg_at(wc, t1, t2, t3)


def closed_loop_bw_3db(
    kp_a_per_rad: Any,
    kvco_hz_per_v: Any,
    n_div: Any,
    a0_f: Any,
    t1_s: Any,
    t2_s: Any,
    t3_s: Any,
) -> float:
    """闭环 −3dB 带宽（Hz）：|H| 自穿越点向上有唯一 −3dB 交越的括弧二分。

    |H(jωc)| = 1/(2sin(PM/2)) ≥ 1/√2（PM≤90°）恒成立 → 括弧 [ωc, ω_hi]
    合法；ω_hi 自 ωc 双倍扩展至 |H|<1/√2。
    """
    kp, kv, n = _loop_gains(kp_a_per_rad, kvco_hz_per_v, n_div)
    a0 = _positive(a0_f, "a0_f")
    t1, t2, t3 = _time_constants(t1_s, t2_s, t3_s)
    kv_rad = _TWO_PI * kv
    fc, _pm = crossover_and_pm(kp, kv, n, a0, t1, t2, t3)
    wc = _TWO_PI * fc
    hi = wc
    for _ in range(120):
        if _closed_loop_mag(hi, kp, kv_rad, n, a0, t1, t2, t3) < _INV_SQRT2:
            break
        hi *= 2.0
    else:
        raise RuntimeError("闭环 −3dB 括弧上探越界——参数病态")
    lo = wc
    for _ in range(100):
        mid = math.sqrt(lo * hi)
        if _closed_loop_mag(mid, kp, kv_rad, n, a0, t1, t2, t3) >= _INV_SQRT2:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi) / _TWO_PI


# ─── 峰值相位放置求解（设计面数学核；r>0 全域有效）─────────────────────────


def _c_of_u(u: float, r: float) -> float:
    """峰值条件右端 c(u) = u/(1+u²) + r·u/(1+r²u²)。"""
    return u / (1.0 + u * u) + r * u / (1.0 + (r * u) ** 2)


def _v_of_c(c: float) -> float:
    """v/(1+v²)=c 的 v≥1 分支：v = 2c/(1−√(1−4c²))（有理化形，小 c 稳定）。"""
    if not 0.0 < c <= 0.5:
        raise ValueError(f"峰值条件 c 必须落在 (0, 1/2]，实际 {c!r}")
    root = math.sqrt(max(0.0, 1.0 - 4.0 * c * c))
    return 2.0 * c / (1.0 - root)


def solve_peak_placement(phase_margin_deg: Any, t3_t1_ratio: Any) -> tuple[float, float]:
    """峰值相位放置求解：给定 PM 与极点比 r=T3/T1 → 无量纲 (u, v)=(ωcT1, ωcT2)。

    数学核对 r>0 全域有效（r<1 属重参数化不在综合面开放）；u 的可达上界
    u* 由 c(u*)=1/2 单调二分；g(u)=PM 闭合条件在 (0, u*] 端点变号二分
    （200 轮 → 机器精度）。g(u*)≥0 即目标 PM 不可达，显式报错并给出可达窗
    下限。返回 (u, v)。
    """
    pm_deg = _finite(phase_margin_deg, "phase_margin_deg")
    if not 0.0 < pm_deg < 90.0:
        raise ValueError(f"phase_margin_deg 必须落在开区间 (0, 90) deg，实际 {pm_deg!r}")
    r = _finite(t3_t1_ratio, "t3_t1_ratio")
    if r <= 0.0:
        raise ValueError(f"t3_t1_ratio 必须 >0（极点比 T3/T1），实际 {r!r}")
    pm_rad = math.radians(pm_deg)

    # 可达界 u*：c 单调增于 (0, min(1,1/r))，c(1/r) = 1/2 + r/(1+r²) > 1/2
    u_lo, u_hi = 1.0e-12, 1.0 / r
    for _ in range(200):
        mid = math.sqrt(u_lo * u_hi)
        if _c_of_u(mid, r) < 0.5:
            u_lo = mid
        else:
            u_hi = mid
    u_star = math.sqrt(u_lo * u_hi)

    def _g(u: float) -> float:
        v = _v_of_c(_c_of_u(u, r))
        return math.atan(v) - math.atan(u) - math.atan(r * u) - pm_rad

    g_hi = _g(u_star)
    if g_hi >= 0.0:
        pm_min = 45.0 - math.degrees(math.atan(u_star)) - math.degrees(math.atan(r * u_star))
        raise ValueError(
            f"目标 PM={pm_deg:g} deg 对极点比 r={r:g} 不可达"
            f"（可达窗下限 ≈ {pm_min:.2f} deg）——请减小 r 或放宽 PM")
    # g(0⁺) → 90°−PM > 0（PM<90 严格），端点变号 → 二分
    a_lo, a_hi = 1.0e-12, u_star
    for _ in range(200):
        mid = math.sqrt(a_lo * a_hi)
        if _g(mid) > 0.0:
            a_lo = mid
        else:
            a_hi = mid
    u = math.sqrt(a_lo * a_hi)
    return u, _v_of_c(_c_of_u(u, r))


# ─── 综合（规格主面）────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class LoopFilterSynthesis:
    """三阶环路滤波器综合结果（字段语义见 synthesize_loop_filter；全 float）。"""

    f_c_target_hz: float
    pm_target_deg: float
    kp_a_per_rad: float
    kvco_hz_per_v: float
    n_div: float
    t3_t1_ratio: float
    t1_s: float
    t2_s: float
    t3_s: float
    a0_f: float
    c1_f: float
    c2_f: float
    r2_ohm: float
    c3_f: float
    r3_ohm: float
    f_crossover_hz: float
    phase_margin_deg: float
    fc_rel_error: float
    pm_abs_error_deg: float
    pm_peak_residual_deg: float
    closed_loop_bw_3db_hz: float
    h_at_crossover_db: float
    c3_loading_ratio: float

    def to_dict(self) -> dict[str, float]:
        """JSON 可序列化 dict（全 float，无 None——service 出口契约）。"""
        return {
            f.name: float(getattr(self, f.name))
            for f in dataclasses.fields(self)
        }


def synthesize_loop_filter(
    f_c_hz: Any,
    phase_margin_deg: Any,
    kp_a_per_rad: Any,
    kvco_hz_per_v: Any,
    n_div: Any,
    t3_t1_ratio: float = 3.0,
    c3_frac: float = 0.1,
    r3_ohm: Any | None = None,
) -> LoopFilterSynthesis:
    """三阶 Type-II CP 环路滤波器综合：f_c/PM → T1/T2/T3/A0 → C1/C2/R2/C3/R3。

    放置=峰值相位（dPM/dω|ωc=0，模块头口径），r=T3/T1 为显式设计自由度
    （>1：附加极点在主极点之外）；A0 由 |G(jωc)|=1 闭式回代；元件闭式见
    模块头。解后回代 open_loop_transfer 复核（规格验收面），穿越/PM 残差
    与峰值放置残差入结果字段；复核超差显式报错（不静默）。

    :param c3_frac: C3 = c3_frac·A0（0<c≤0.5，缺省 0.1——C3≪A0 加载口径）；
        r3_ohm 给定时改走 C3=T3/R3 覆盖本参。
    :param r3_ohm: 显式第三极点电阻 Ω（>0）。
    """
    fc_t = _positive(f_c_hz, "f_c_hz")
    pm_t = _finite(phase_margin_deg, "phase_margin_deg")
    if not 0.0 < pm_t < 90.0:
        raise ValueError(f"phase_margin_deg 必须落在开区间 (0, 90) deg，实际 {pm_t!r}")
    kp, kv, n = _loop_gains(kp_a_per_rad, kvco_hz_per_v, n_div)
    r = _finite(t3_t1_ratio, "t3_t1_ratio")
    if r <= 1.0:
        raise ValueError(
            f"t3_t1_ratio 必须 >1（综合面约定附加极点在主极点之外；"
            f"放置数学核 solve_peak_placement 支持 r>0），实际 {r!r}")
    cf = _finite(c3_frac, "c3_frac")
    if not 0.0 < cf <= 0.5:
        raise ValueError(f"c3_frac 必须落在 (0, 0.5]（C3≪A0 加载口径），实际 {cf!r}")
    r3_in = None if r3_ohm is None else _positive(r3_ohm, "r3_ohm")

    u, v = solve_peak_placement(pm_t, r)
    wc = _TWO_PI * fc_t
    t1 = u / wc
    t2 = v / wc
    t3 = r * t1
    kv_rad = _TWO_PI * kv
    a0 = (
        (kp * kv_rad / (n * wc * wc))
        * math.sqrt(1.0 + v * v)
        / math.sqrt((1.0 + u * u) * (1.0 + (r * u) ** 2))
    )

    c1 = a0 * t1 / t2
    c2 = a0 * (t2 - t1) / t2
    r2 = t2 / c2
    if r3_in is None:
        c3 = cf * a0
        r3 = t3 / c3
    else:
        r3 = r3_in
        c3 = t3 / r3

    # 复核（规格验收面）：回代 open_loop_transfer 口径复现目标 f_c/PM
    fc_num, pm_num = crossover_and_pm(kp, kv, n, a0, t1, t2, t3)
    fc_rel = abs(fc_num - fc_t) / fc_t
    pm_err = abs(pm_num - pm_t)
    if fc_rel > 1.0e-6 or pm_err > 1.0e-4:
        raise RuntimeError(
            f"综合复核失败：穿越相对残差 {fc_rel:.3e}（门 1e-6）、"
            f"PM 绝对残差 {pm_err:.3e} deg（门 1e-4）——求解器病态，拒绝出参")
    d = 1.0e-3
    pm_res = _pm_deg_at(wc * (1.0 + d), t1, t2, t3) - _pm_deg_at(wc * (1.0 - d), t1, t2, t3)
    if abs(pm_res) > 1.0e-2:
        raise RuntimeError(
            f"峰值放置复核失败：PM 二阶差分 {pm_res:.3e} deg 超门 1e-2——"
            f"解落在相位谷而非峰，拒绝出参")

    bw = closed_loop_bw_3db(kp, kv, n, a0, t1, t2, t3)
    h_db = -20.0 * math.log10(2.0 * math.sin(math.radians(pm_num) / 2.0))
    return LoopFilterSynthesis(
        f_c_target_hz=fc_t,
        pm_target_deg=pm_t,
        kp_a_per_rad=kp,
        kvco_hz_per_v=kv,
        n_div=n,
        t3_t1_ratio=r,
        t1_s=t1,
        t2_s=t2,
        t3_s=t3,
        a0_f=a0,
        c1_f=c1,
        c2_f=c2,
        r2_ohm=r2,
        c3_f=c3,
        r3_ohm=r3,
        f_crossover_hz=fc_num,
        phase_margin_deg=pm_num,
        fc_rel_error=fc_rel,
        pm_abs_error_deg=pm_err,
        pm_peak_residual_deg=pm_res,
        closed_loop_bw_3db_hz=bw,
        h_at_crossover_db=h_db,
        c3_loading_ratio=c3 / (c1 + c2),
    )
