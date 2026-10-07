"""F-E 件 6：PLL 预算内核（二阶 II 型闭环传函 + 稳定裕度 + ΣΔ 谱 + 抖动预算）。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立来源，不自证，#118）：

- 二阶 II 型 PLL（PFD+电荷泵/有源环路滤波器，环路增益系数口径）：开环
  G(s) = (Kφ·Kvco/N)·(1+s·R2·C)/s²；闭环
  H(s) = (2ζωn·s+ωn²)/(s²+2ζωn·s+ωn²)、误传函 E(s) = 1−H(s) =
  s²/(s²+2ζωn·s+ωn²)；ωn = √(Kφ·Kvco/N)、ζ = R2·C·ωn/2。
  F.M. Gardner《Phaselock Techniques》3rd ed. Ch.3 标准形式（II 型=
  环路双积分+滤波器零点）；V. Wolaver《Phase-Locked Loop Circuit
  Design》同构；D. Banerjee《PLL Performance, Simulation, and Design》
  电荷泵环路同式（其电荷泵增益 Kcp[A/rad] 与滤波电容 C 合并后
  Kφ = Kcp/C 即本模块口径——任务书 F-E 表件 6 公式逐字一致；有源
  滤波器口径 Kφ = Kφ_pfd/(R1·C) 同理。调用方持电荷泵电流 Icp 时请以
  Kφ = Icp/C 传入）。
- 相位裕度：增益穿越 ωc 满足 |G(jωc)|=1，闭式
  ωc = ωn·√(2ζ²+√(1+4ζ⁴))（对 |G| 求根的 Gardner 标准结果），
  PM = atan(ωc·R2·C)（即 arg G(jωc)+180°）。本模块同时提供数值路径
  （|G(jω)| 严格单调降——d(ln|G|)/dω = −2/ω+ωT²/(1+ω²T²) ≤ −1/ω < 0
  ——故穿越唯一，对数二分 + arg 数值求 PM），双路径互为裁判；文献
  sanity 带（ζ=0.5→PM≈52°、ζ=1/√2→PM≈65.5°）只作 ±3° 带断言，钉值
  以双路径数值互证为准（任务书预声明口径）。
- ΣΔ 量化噪声谱（T. Riley et al., "Techniques for Multi-Stage Noise
  Shaping (MASH) Delta-Sigma Modulators for Fractional-N Synthesizers",
  IEEE CSS 1993）：m 阶 MASH 相位误差谱
  S_φ(f) = (2π)²·Δ²/(12·f_ref)·(2·sin(π·f/f_ref))^(2(m−1))，m=3（MASH
  1-1-1）即 ∝f⁴ 谱（40 dB/dec）。任务书"1/f^6"提法与所给公式（指数
  2(m−1)=4）矛盾——以公式与直接差分数值模拟双路径一致的 **f⁴** 为准，
  如实登记。谱为除法器相位偏差口径（VCO 相位；rad²/Hz）；绝对电平
  依赖 Riley 白化假设（量化误差白、均匀、方差 Δ²/12）。
  **量纲口径注（模拟裁判实测钉，预声明）**：上式（Riley 引文形式，记
  S_R）在 Riley/Banerjee 文献用法中直接作 SSB 相噪 L_lin(f)（1/Hz）
  使用；与 MT-008 一致的**单边带相位 PSD** 为 S_φ,1 = 2·S_R（模拟
  裁判实测系数 2.00=3.01 dB，白噪声标定过的 Hann 周期图估计器实测；
  本模块 mash_sd_phi_psd_rad2_per_hz 返回 2·S_R 供合成记账，
  mash_sd_psd_rad2_per_hz 返回任务书原式 S_R）。
- PLL 输出噪声记账（Banerjee ΣΔ 章标准口径）：输出相位谱
  S_out = N²·|H|²·S_ref + |1−H|²·S_vco + |H|²·S_ΣΔ,1
  ——参考/晶振噪声带内经 H 低通并按 20log10(N) 抬升；VCO 噪声经
  误传函高通塑形；ΣΔ 单边带谱 S_ΣΔ,1 = 2·S_R 为 VCO 口径不再乘 N²、
  仅经 H 低通（等价于 L_ΣΔ = 10log10(|H|²·S_R) 的 Banerjee 用法）。
- 抖动积分复用 :mod:`rfauto.core.clock_noise`（σ_φ² = 2∫10^(L/10)df，
  ADI MT-008 口径；Hajimiri-Lee 幂律谱同模块）：本模块只合成输出
  L(f)，积分调 :func:`clock_noise.phase_jitter_from_l`——不重复实现
  积分器（任务书钉；同式双实现分叉防患，#112 家族）。

接口：传函/谱求值函数 numpy 一维数组进出（复数传函/实数谱注明）；
预算结果 dataclass 带 to_dict（JSON 可序列化 float/str/bool）；单位
钉在参数名（Hz、rad/s、rad/s/V、Ω、F、dBc/Hz、rad²/Hz）。数值 0.0
合法（判缺失一律 is not None，#364④）；bool 显式拒收（df7+⑯）。纯
算法零 IO；不进 calculators 注册表（F-E 域内约定，消费者是 service
层与预算链）。

晶振量级表（CRYSTAL_OSC_TABLE）：XO/TCXO/OCXO 典型相噪@偏频
（10/100/1k/10k/100k Hz）与温漂/老化量级——**公开数据手册典型值带，
量级参考非实测**（未附具体型号出处，关键设计须实测供应商数据）。
载波换算 L(f; f_c2) = L(f; f_c1) + 20log10(f_c2/f_c1) 为标准近似口径
（振荡器相位噪声随载波频率 20log 标度）。

诚实边界（预声明）：
1. 传函为理想 II 型二阶模型（理想积分器+单零点），不含采样/PFD 死区/
   环路延迟/附加高阶极点——真实电荷泵 PLL 的附加极点会压低 PM，本
   内核 PM 是**上界口径**；
2. pll_output_noise_l 的输入 L 表按逐频点塑形（分段常数谱假设），是
   与 clock_noise 的 dB 线性/常数两口径同源的**显式近似**——合成谱
   保真度受输入网格分辨率限制，不外推；
3. ΣΔ 谱绝对电平依赖方差 Δ²/12 的白化假设；无抖动小数场景的分数
   杂散（spur）不在本连续谱内；
4. 晶振表是量级参考不是供应商数据（表内 note 逐条标注）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from rfauto.core import clock_noise as _cn

__all__ = [
    "CRYSTAL_OFFSETS_HZ",
    "CRYSTAL_OSC_TABLE",
    "DEFAULT_PM_WARNING_THRESHOLD_DEG",
    "LoopConstants",
    "StabilityResult",
    "closed_loop_transfer",
    "crystal_l_dbc",
    "error_transfer",
    "gain_crossover_closed_form",
    "gain_crossover_numeric",
    "loop_constants",
    "mash_sd_phi_psd_rad2_per_hz",
    "mash_sd_psd_db",
    "mash_sd_psd_rad2_per_hz",
    "open_loop_transfer",
    "phase_margin_closed_form",
    "phase_margin_numeric",
    "pll_jitter_budget",
    "pll_output_noise_l",
    "stability_budget",
]

_TWO_PI = 2.0 * math.pi

#: PM warning 阈值缺省口径（deg）：PM 低于此值置告警标志字段（不抛异常）
DEFAULT_PM_WARNING_THRESHOLD_DEG = 30.0

#: 晶振表支持的偏频点（Hz）
CRYSTAL_OFFSETS_HZ = (10.0, 100.0, 1.0e3, 1.0e4, 1.0e5)


# ─── 入参守卫（#140：注解不等于调用方真的传了）───────────────────────────────


def _finite(value: Any, name: str) -> float:
    """入参收敛为有限 float，非法即显式报错（bool 显式拒收 df7+⑯；字符串拒收）。"""
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
        raise ValueError(f"{name} 必须全 >0（相噪偏移频率口径）")
    return arr


def _l_array(value: Any, name: str, expect: int) -> np.ndarray:
    """L(f) 数组收敛：一维、有限、定长；符号/单调不做约束（诚实边界②）。"""
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} 必须是数值序列")
    if np.asarray(value).dtype == bool:
        raise ValueError(f"{name} 不接受布尔数组")
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 1 or arr.size != expect:
        raise ValueError(f"{name} 必须是长度 {expect} 的一维数组，实际长度 {arr.size}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含非有限值")
    return arr


def _order_int(value: Any, name: str) -> int:
    """MASH 阶数收敛：整数（int 或整值 float）、≥1；bool 显式拒收。"""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 不接受 bool")
    if isinstance(value, (int, np.integer)) or (
        isinstance(value, float) and float(value).is_integer()
    ):
        m = int(value)
    else:
        raise ValueError(f"{name} 必须为整数，实际 {value!r}")
    if m < 1:
        raise ValueError(f"{name} 必须 ≥1（MASH 阶数），实际 {m}")
    return m


# ─── 1. 环路常数与传函（Gardner/Banerjee 二阶 II 型标准口径）──────────────────


@dataclass(frozen=True)
class LoopConstants:
    """(Kφ,Kvco,N,R2,C) → 环路自然频率/阻尼/零点时间常数（字段语义见 loop_constants）。"""

    k_phi: float
    kvco_rad_s_v: float
    n_div: float
    r2_ohm: float
    c_farad: float
    omega_n_rad_s: float
    zeta: float
    tau_zero_s: float
    f_n_hz: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "k_phi": self.k_phi,
            "kvco_rad_s_v": self.kvco_rad_s_v,
            "n_div": self.n_div,
            "r2_ohm": self.r2_ohm,
            "c_farad": self.c_farad,
            "omega_n_rad_s": self.omega_n_rad_s,
            "zeta": self.zeta,
            "tau_zero_s": self.tau_zero_s,
            "f_n_hz": self.f_n_hz,
        }


def loop_constants(
    k_phi: float, kvco_rad_s_v: float, n_div: float, r2_ohm: float, c_farad: float
) -> LoopConstants:
    """环路五参数 → (ωn, ζ, 零点时间常数)。

    k_phi：环路增益系数（rad⁻¹·s⁻¹ 量纲；Banerjee 电荷泵口径 Kcp/C、
    有源滤波器口径 Kφ_pfd/(R1·C)——见模块 docstring 换算注）；>0。
    kvco_rad_s_v：VCO 压控灵敏度（rad/s/V，**弧度制**）；>0。
    n_div：分频比（>0；frac-N 有效分频比允许小数）。
    r2_ohm / c_farad：环路滤波器零点支路（Ω / F）；>0。

    ωn = √(Kφ·Kvco/N)（rad/s）；ζ = R2·C·ωn/2；τ_zero = R2·C（s）；
    f_n = ωn/2π（Hz，便利字段）。
    """
    kp = _positive(k_phi, "k_phi")
    kv = _positive(kvco_rad_s_v, "kvco_rad_s_v")
    nd = _positive(n_div, "n_div")
    r2 = _positive(r2_ohm, "r2_ohm")
    cf = _positive(c_farad, "c_farad")
    omega_n = math.sqrt(kp * kv / nd)
    tau = r2 * cf
    zeta = tau * omega_n / 2.0
    return LoopConstants(
        k_phi=kp,
        kvco_rad_s_v=kv,
        n_div=nd,
        r2_ohm=r2,
        c_farad=cf,
        omega_n_rad_s=omega_n,
        zeta=zeta,
        tau_zero_s=tau,
        f_n_hz=omega_n / _TWO_PI,
    )


def _tau_zero(zeta: float, omega_n: float) -> float:
    """零点时间常数 T = R2·C = 2ζ/ωn（由 ζ 反解，传函内部口径）。"""
    return 2.0 * zeta / omega_n


def open_loop_transfer(freqs_hz: Any, omega_n: float, zeta: float) -> np.ndarray:
    """开环传函 G(jω) = ωn²·(1+jωT)/(jω)²，T = 2ζ/ωn（复数 ndarray 进出）。

    freqs_hz：偏移频率数组（Hz，一维、有限、>0）。ωn>0、ζ>0。
    """
    wn = _positive(omega_n, "omega_n")
    z = _positive(zeta, "zeta")
    f = _freq_array(freqs_hz, "freqs_hz")
    w = _TWO_PI * f
    t = _tau_zero(z, wn)
    jw = 1j * w
    return wn * wn * (1.0 + jw * t) / (jw * jw)


def closed_loop_transfer(freqs_hz: Any, omega_n: float, zeta: float) -> np.ndarray:
    """闭环传函 H(s) = (2ζωn·s+ωn²)/(s²+2ζωn·s+ωn²)，s = j2πf（复数 ndarray 进出）。

    H(0)=1（II 型 DC 增益恒等，单测钉）；高频 |H| ≈ 2ζωn/ω（−20 dB/dec
    单零点渐近）。ωn>0、ζ>0。
    """
    wn = _positive(omega_n, "omega_n")
    z = _positive(zeta, "zeta")
    f = _freq_array(freqs_hz, "freqs_hz")
    s = 1j * _TWO_PI * f
    return (2.0 * z * wn * s + wn * wn) / (s * s + 2.0 * z * wn * s + wn * wn)


def error_transfer(freqs_hz: Any, omega_n: float, zeta: float) -> np.ndarray:
    """误传函 E(s) = 1−H(s) = s²/(s²+2ζωn·s+ωn²)（复数 ndarray 进出）。

    恒等式 E+H=1 逐频点成立（单测钉）；E(0)=0（DC 无静差，II 型）；
    高频 |E|→1（VCO 噪声直通域）。ωn>0、ζ>0。
    """
    wn = _positive(omega_n, "omega_n")
    z = _positive(zeta, "zeta")
    f = _freq_array(freqs_hz, "freqs_hz")
    s = 1j * _TWO_PI * f
    return (s * s) / (s * s + 2.0 * z * wn * s + wn * wn)


# ─── 2. 相位裕度：闭式与数值双路径（互为裁判，任务书口径）─────────────────────


def gain_crossover_closed_form(omega_n: float, zeta: float) -> float:
    """增益穿越闭式 ωc = ωn·√(2ζ²+√(1+4ζ⁴))（rad/s；Gardner |G| 求根标准结果）。

    与数值二分穿越互为裁判（单测双路径钉）。ωn>0、ζ>0。
    """
    wn = _positive(omega_n, "omega_n")
    z = _positive(zeta, "zeta")
    return wn * math.sqrt(2.0 * z * z + math.sqrt(1.0 + 4.0 * z**4))


def phase_margin_closed_form(zeta: float) -> float:
    """相位裕度闭式 PM = atan(ωc·T)（deg），ωc·T = 2ζ·√(2ζ²+√(1+4ζ⁴))。

    ζ>0 → PM ∈ (0°, 90°)；单调递增（单测钉）。与数值路径互为裁判。
    """
    z = _positive(zeta, "zeta")
    wc_t = 2.0 * z * math.sqrt(2.0 * z * z + math.sqrt(1.0 + 4.0 * z**4))
    return math.degrees(math.atan(wc_t))


def _open_loop_mag(w: float, omega_n: float, zeta: float) -> float:
    """|G(jω)| = (ωn²/ω²)·√(1+ω²T²)（标量，二分内部口径）。"""
    t = _tau_zero(zeta, omega_n)
    return (omega_n * omega_n / (w * w)) * math.sqrt(1.0 + (w * t) ** 2)


def gain_crossover_numeric(omega_n: float, zeta: float) -> float:
    """增益穿越数值路径：|G(jω)| 对数二分（rad/s）。

    |G| 严格单调降（d(ln|G|)/dω = −2/ω + ωT²/(1+ω²T²) ≤ −1/ω < 0）故
    穿越唯一；括弧 [ωn·1e−9, ωn·1e9] 两端 |G| 分别 ≫1/≪1（必含穿越）。
    100 轮对数二分 → 相对精度 ~1e−28 上限（浮点即机器精度）。
    """
    wn = _positive(omega_n, "omega_n")
    z = _positive(zeta, "zeta")
    lo = wn * 1e-9
    hi = wn * 1e9
    for _ in range(100):
        mid = math.sqrt(lo * hi)
        if _open_loop_mag(mid, wn, z) > 1.0:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


def phase_margin_numeric(omega_n: float, zeta: float) -> float:
    """相位裕度数值路径：PM = arg G(jωc_numeric) + 180°（deg）。

    arg ∈ (−180°,−90°)（ζ>0）故无需卷绕；与闭式互为裁判（单测钉）。
    """
    wn = _positive(omega_n, "omega_n")
    z = _positive(zeta, "zeta")
    wc = gain_crossover_numeric(wn, z)
    g = open_loop_transfer(np.array([wc / _TWO_PI]), wn, z)
    return math.degrees(float(np.angle(g[0]))) + 180.0


@dataclass(frozen=True)
class StabilityResult:
    """环路稳定裕度预算结果（字段语义见 stability_budget）。"""

    omega_n_rad_s: float
    zeta: float
    tau_zero_s: float
    f_n_hz: float
    f_crossover_hz: float
    f_crossover_closed_hz: float
    pm_deg: float
    pm_deg_numeric: float
    stable: bool
    pm_warning: bool
    pm_warning_threshold_deg: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "omega_n_rad_s": self.omega_n_rad_s,
            "zeta": self.zeta,
            "tau_zero_s": self.tau_zero_s,
            "f_n_hz": self.f_n_hz,
            "f_crossover_hz": self.f_crossover_hz,
            "f_crossover_closed_hz": self.f_crossover_closed_hz,
            "pm_deg": self.pm_deg,
            "pm_deg_numeric": self.pm_deg_numeric,
            "stable": self.stable,
            "pm_warning": self.pm_warning,
            "pm_warning_threshold_deg": self.pm_warning_threshold_deg,
        }


def stability_budget(
    k_phi: float,
    kvco_rad_s_v: float,
    n_div: float,
    r2_ohm: float,
    c_farad: float,
    pm_warning_threshold_deg: float = DEFAULT_PM_WARNING_THRESHOLD_DEG,
) -> StabilityResult:
    """(Kφ,Kvco,N,R2,C) → ωn/ζ/穿越频率/PM 双路径 + 告警标志（任务书判据 3）。

    pm_warning：pm_deg < pm_warning_threshold_deg（缺省 30°，恰等不算）
    时 True——**标志字段不抛异常**，处置留给调用方。stable：pm_deg>0
    （ζ>0 时恒 True——二阶 II 型两极点在原点+单零点恒稳，字段为调用方
    一致性检查占位）。双路径一致性（f_crossover 两路径、pm 两路径）由
    单测钉，字段双列供调用方旁证。
    """
    thr = _positive(pm_warning_threshold_deg, "pm_warning_threshold_deg")
    lc = loop_constants(k_phi, kvco_rad_s_v, n_div, r2_ohm, c_farad)
    wn = lc.omega_n_rad_s
    z = lc.zeta
    wc = gain_crossover_numeric(wn, z)
    wc_closed = gain_crossover_closed_form(wn, z)
    pm_closed = phase_margin_closed_form(z)
    pm_num = phase_margin_numeric(wn, z)
    return StabilityResult(
        omega_n_rad_s=wn,
        zeta=z,
        tau_zero_s=lc.tau_zero_s,
        f_n_hz=lc.f_n_hz,
        f_crossover_hz=wc / _TWO_PI,
        f_crossover_closed_hz=wc_closed / _TWO_PI,
        pm_deg=pm_closed,
        pm_deg_numeric=pm_num,
        stable=pm_closed > 0.0,
        pm_warning=pm_closed < thr,
        pm_warning_threshold_deg=thr,
    )


# ─── 3. ΣΔ 量化噪声谱（Riley 1993 MASH 口径）─────────────────────────────────


def mash_sd_psd_rad2_per_hz(
    freqs_hz: Any, f_ref_hz: float, order: int = 3, delta: float = 1.0
) -> np.ndarray:
    """m 阶 MASH ΣΔ 量化噪声谱（Riley 1993 引文形式 S_R，任务书原式）。

    S_R(f) = (2π)²·Δ²/(12·f_ref)·(2·sin(π·f/f_ref))^(2(m−1))。
    order：MASH 阶数 m（≥1；缺省 3 = MASH 1-1-1，谱 ∝f⁴）；delta：量化
    步长 Δ（>0，整数分频 Δ=1）。f ∈ (0, f_ref/2] 离散谱有效域之外为
    连续谱外推口径（调用方自行限带；本函数照算不拦）。

    量纲口径（模块 docstring 量纲注）：S_R 在 Riley/Banerjee 用法中直接
    作 SSB 相噪 L_lin（1/Hz）；MT-008 一致的单边带相位 PSD 是
    :func:`mash_sd_phi_psd_rad2_per_hz` = 2·S_R。
    """
    f = _freq_array(freqs_hz, "freqs_hz")
    fref = _positive(f_ref_hz, "f_ref_hz")
    m = _order_int(order, "order")
    d2 = _positive(delta, "delta") ** 2
    x = np.pi * f / fref
    return (2.0 * math.pi) ** 2 * d2 / (12.0 * fref) * (2.0 * np.sin(x)) ** (2 * (m - 1))


def mash_sd_phi_psd_rad2_per_hz(
    freqs_hz: Any, f_ref_hz: float, order: int = 3, delta: float = 1.0
) -> np.ndarray:
    """单边带相位 PSD S_φ,1 = 2·S_R（rad²/Hz，MT-008 换算口径）。

    与直接差分模拟裁判（白噪声标定 Hann 周期图）逐带一致的量（系数
    2.00 = 3.01 dB 实测钉，见模块 docstring 量纲注）；pll_output_noise_l
    的合成记账消费本量。
    """
    return 2.0 * mash_sd_psd_rad2_per_hz(freqs_hz, f_ref_hz, order=order, delta=delta)


def mash_sd_psd_db(
    freqs_hz: Any, f_ref_hz: float, order: int = 3, delta: float = 1.0
) -> np.ndarray:
    """mash_sd_psd_rad2_per_hz 的 dB 形式（10·log10，dB re rad²/Hz，任务书 dB 接口）。"""
    psd = mash_sd_psd_rad2_per_hz(freqs_hz, f_ref_hz, order=order, delta=delta)
    return 10.0 * np.log10(psd)


# ─── 4. PLL 输出噪声合成与抖动预算（复用 clock_noise 积分器）──────────────────


def pll_output_noise_l(
    freqs_hz: Any,
    omega_n: float,
    zeta: float,
    l_ref_dbc: Any | None = None,
    l_vco_dbc: Any | None = None,
    mash_order: int | None = None,
    f_ref_hz: float | None = None,
    mash_delta: float = 1.0,
    division_n: float | None = None,
) -> np.ndarray:
    """PLL 输出相噪合成 L_out(f)（dBc/Hz，逐频点塑形，诚实边界②口径）。

    S_out = N²·|H|²·S_ref + |1−H|²·S_vco + |H|²·S_ΣΔ（Banerjee 记账，
    模块 docstring）；L_out = 10·log10(S_out/2)。输入 L 表与 freqs_hz
    同长（分段常数谱假设）；至少给一个噪声源（全 None → ValueError，
    判缺失 is not None——L=0.0 合法）；mash_order 给出时 f_ref_hz 必须
    同给；division_n None → 1.0（不抬升；N>1 时参考项按 N² 抬升、
    ΣΔ 项为 VCO 口径不抬升，模块 docstring 记账注）。
    """
    wn = _positive(omega_n, "omega_n")
    z = _positive(zeta, "zeta")
    f = _freq_array(freqs_hz, "freqs_hz")
    nfac = 1.0
    if division_n is not None:
        nfac = _positive(division_n, "division_n") ** 2
    total = np.zeros(f.shape)
    found = False
    if l_ref_dbc is not None:
        arr = _l_array(l_ref_dbc, "l_ref_dbc", f.size)
        s_ref = 2.0 * 10.0 ** (arr / 10.0)
        h2 = np.abs(closed_loop_transfer(f, wn, z)) ** 2
        total += nfac * h2 * s_ref
        found = True
    if l_vco_dbc is not None:
        arr = _l_array(l_vco_dbc, "l_vco_dbc", f.size)
        s_vco = 2.0 * 10.0 ** (arr / 10.0)
        e2 = np.abs(error_transfer(f, wn, z)) ** 2
        total += e2 * s_vco
        found = True
    if mash_order is not None:
        if f_ref_hz is None:
            raise ValueError("mash_order 给出时 f_ref_hz 必须同给（ΣΔ 谱依赖参考频率）")
        psd = mash_sd_phi_psd_rad2_per_hz(f, f_ref_hz, order=mash_order, delta=mash_delta)
        h2 = np.abs(closed_loop_transfer(f, wn, z)) ** 2
        total += h2 * psd
        found = True
    if not found:
        raise ValueError("至少需要一个噪声源（l_ref_dbc / l_vco_dbc / mash_order 之一）")
    if not bool(np.all(total > 0.0)):
        raise ValueError("合成谱出现非正值（f>0 时 |H|²>0 恒成立，疑似数值下溢）")
    return 10.0 * np.log10(total / 2.0)


def pll_jitter_budget(
    f_edges_hz: Any,
    f_carrier_hz: float | None,
    omega_n: float,
    zeta: float,
    l_ref_dbc: Any | None = None,
    l_vco_dbc: Any | None = None,
    mash_order: int | None = None,
    f_ref_hz: float | None = None,
    mash_delta: float = 1.0,
    division_n: float | None = None,
) -> _cn.PhaseJitterResult:
    """PLL 输出 rms 抖动预算：合成 L(f) → clock_noise 积分器（复用，任务书钉）。

    合成 L 在 f_edges_hz 边界点求值、段间 dB 线性（INTERP_DB_LINEAR——
    网格分辨率决定塑形保真度，诚实边界②）；积分/抖动换算全权委托
    :func:`clock_noise.phase_jitter_from_l`（σ_φ²=2∫10^(L/10)df，ADI
    MT-008；f_carrier None → jitter_s None）。返回
    clock_noise.PhaseJitterResult（不重复包装）。
    """
    f = _freq_array(f_edges_hz, "f_edges_hz")
    l_out = pll_output_noise_l(
        f,
        omega_n,
        zeta,
        l_ref_dbc=l_ref_dbc,
        l_vco_dbc=l_vco_dbc,
        mash_order=mash_order,
        f_ref_hz=f_ref_hz,
        mash_delta=mash_delta,
        division_n=division_n,
    )
    carrier: float | None = None
    if f_carrier_hz is not None:
        carrier = _positive(f_carrier_hz, "f_carrier_hz")
    return _cn.phase_jitter_from_l(f, l_out, interp=_cn.INTERP_DB_LINEAR, f_carrier=carrier)


# ─── 5. 晶振量级表（公开手册典型值带，量级参考非实测）─────────────────────────
#
# 数值为公开数据手册/应用笔记的典型值带中值口径（未附具体型号，诚实边界④）：
# 相噪按常见 10-100 MHz 级器件量级；温漂/老化取手册规范带端点。载波换算走
# crystal_l_dbc 的 20log10 标度近似。

CRYSTAL_OSC_TABLE: dict[str, dict[str, Any]] = {
    "xo": {
        "f_carrier_hz": 26.0e6,
        "l_dbc_hz": {10.0: -90.0, 100.0: -118.0, 1.0e3: -138.0, 1.0e4: -146.0, 1.0e5: -150.0},
        "temp_stability_ppm": (-50.0, 50.0),
        "aging_ppm_per_year": (-5.0, 5.0),
        "note": "普通晶体振荡器（XO，~26 MHz 级）：公开数据手册典型值带，"
        "量级参考非实测；温漂 ±20~±50 ppm 全温、老化 ±3~±5 ppm/yr 量级。",
    },
    "tcxo": {
        "f_carrier_hz": 10.0e6,
        "l_dbc_hz": {
            10.0: -100.0,
            100.0: -125.0,
            1.0e3: -140.0,
            1.0e4: -150.0,
            1.0e5: -153.0,
        },
        "temp_stability_ppm": (-2.0, 2.0),
        "aging_ppm_per_year": (-3.0, 3.0),
        "note": "温补晶体振荡器（TCXO，~10 MHz 级）：公开数据手册典型值带，"
        "量级参考非实测；温漂 ±0.5~±2 ppm 全温、老化 ±1~±3 ppm/yr 量级。",
    },
    "ocxo": {
        "f_carrier_hz": 10.0e6,
        "l_dbc_hz": {
            10.0: -110.0,
            100.0: -130.0,
            1.0e3: -145.0,
            1.0e4: -152.0,
            1.0e5: -155.0,
        },
        "temp_stability_ppm": (-0.05, 0.05),
        "aging_ppm_per_year": (-0.2, 0.2),
        "note": "恒温晶体振荡器（OCXO，~10 MHz 级）：公开数据手册典型值带，"
        "量级参考非实测；温漂 ±5e-3~±5e-2 ppm 全温、老化 ±5e-2~±2e-1 ppm/yr 量级。",
    },
}


def crystal_l_dbc(
    f_offset_hz: Any, osc_type: str, f_target_hz: float | None = None
) -> np.ndarray:
    """晶振表相噪查表 L(f)（dBc/Hz，ndarray 进出）。

    f_offset_hz：偏移频率（须逐点等于表内偏频点 CRYSTAL_OFFSETS_HZ——
    本内核不做偏频插值，不外推，诚实边界④）；osc_type：xo/tcxo/ocxo；
    f_target_hz：目标载波（Hz，可选）——给定则按 20log10(f_target/
    f_carrier) 平移（振荡器相位噪声载波标度近似，模块 docstring 口径）；
    判缺失 is not None。未知类型/偏频 → ValueError。
    """
    if not isinstance(osc_type, str) or osc_type not in CRYSTAL_OSC_TABLE:
        raise ValueError(f"osc_type={osc_type!r} 不在晶振表 {sorted(CRYSTAL_OSC_TABLE)}")
    entry = CRYSTAL_OSC_TABLE[osc_type]
    f = _freq_array(f_offset_hz, "f_offset_hz")
    l_map: dict[float, float] = entry["l_dbc_hz"]
    out = np.empty(f.shape, dtype=float)
    for i, fv in enumerate(f):
        key = float(fv)
        if not any(key == off for off in CRYSTAL_OFFSETS_HZ) or key not in l_map:
            raise ValueError(f"f_offset={key!r} 不在晶振表偏频点 {list(CRYSTAL_OFFSETS_HZ)}")
        out[i] = l_map[key]
    if f_target_hz is not None:
        ft = _positive(f_target_hz, "f_target_hz")
        out = out + 20.0 * math.log10(ft / float(entry["f_carrier_hz"]))
    return out
