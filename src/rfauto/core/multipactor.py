r"""MP-3 multipactor 微放电击穿阈值确定性内核（round15 §三 :84
「Vaughan 二次发射+20-gap 串接+N 载波等效功率（IEEE 10904461 2025）」）。

确定性纯函数、零 IO、JSON 可序列化；数值全部落在本内核，LLM/agent 只解释
（铁律 7）。本文件是 core/high_power.py 的 multipactor 伴生模块：high_power
的 ECSS f·d 实验包络（ecss_multipactor_fd）既有语义零改动且仍是工程仲裁
口径，本模块落机制面（渡越谐振闭式 + SEY 参数面 + 级联/多载波换算）。

出处等级（如实标注，#118 裁判独立来源）
----------------------------------------
- 渡越时间谐振闭式（平行板一阶理论）：本仓可复算推导——均匀场
  E(t)=E0·sin(ωt+φ0)、零初速发射，x(t)=(eE0/mω²)[sin φ0−sin(φ0+θ)+θ·cos φ0]、
  v(t)=(eE0/mω)[cos φ0−cos(φ0+θ)]。经典 Hatch-Williams/Vaughan 一阶口径
  （Vaughan, "Multipactor", IEEE Trans. Plasma Sci. PS-16(2):183, 1988；
  Hatch & Williams, J. Appl. Phys. 25:417, 1954；转引语境另见
  arXiv:2507.17881 §2.1 的 (V, f·d) 相似标度律口径，2026-10-02 实取）。
  封闭周期轨道要求到达相位=发射相位+(2n−1)π（奇数半周期，反向半周到达，
  次级电子被反向加速回来）；可飞域 φ0∈[0, π/2]。序 n 带边：
      V_lo(n) = K/√(4+(2n−1)²π²)      （最优相位 φ0*=arctan(2/((2n−1)π))）
      V_hi    = K/2                    （φ0=π/2，全序共边）
      V_res(n) = K/((2n−1)π)           （φ0=0 谐振线，带内）
  其中 K = m_e·ω²·d²/e = 4π²(m_e/e)(f·d)² [V]（f·d 相似标度）。
  已知局限（如实声明）：零初速理想化——带边轨道为碰撞速度→0 的边际轨道
  （SEY→0），真实带因有限发射速度展宽；高序带下探更低电压，本模型对
  低压侧偏"乐观窄带"，工程判定仍以 ECSS 实验包络（high_power.multipactor_fd_check）
  为仲裁，本模块 verdict 语义仅对本模型自洽（见 multipactor_susceptibility_check）。
- SEY crossover 窗口判据（增长要求 δ(E_imp)>1 ⟺ E_imp∈(E1,E2)）：VERIFIED——
  Kishek & Lau, PAC97 (7P061) "The secondary electron yield is above unity
  only for impact energies in between the two crossover points"（2026-10-02
  实取）；另 arXiv:2507.17881 §2.5 转引 Rosario & Edén (2012) "multipactor
  threshold is directly governed by the first and second crossover energies"。
- SEY 材料参数面 M1–M6（δmax0/Emax0/E1/E2）：VERIFIED——
  Iqbal, Verboncoeur & Zhang, arXiv:2507.17881v1 Table 1（2026-10-02 实取，
  PIC 模拟口径材料集；非特定真实金属的实测标定）。
- Vaughan 角依赖 δmax(θ)/Emax(θ)：VERIFIED-转引——arXiv:1710.01636 §II
  引 Vaughan (1988)：δmax(θ)=δmax0·(1+k_s·θ²/(2π))、
  Emax(θ)=Emax0·(1+k_s·θ²/π)（θ rad；归一化系数各文献转引有差异，本内核
  取该转引版；域限 [0, π/2]）。
- Vaughan 普适产额曲线 δ(E)=δmax·(v·e^{1−v})^{k_s}（v=E/Emax）：UNVERIFIED——
  原文（Vaughan, IEEE Trans. Electron Devices 36:1963, 1989 与 40:830, 1993）
  付费墙未逐字核对；本实现取该普适形状（构造恒等式自检
  δ(Emax)=δmax、δ(0)=0、crossover 由 v·e^{1−v}=δmax^{−1/k_s} 解出），
  仅作形状/插值面；判定面不消费曲线，只消费 crossover 窗口（上条 VERIFIED）。
- N 载波等效功率：ECSS 惯例双口径——非相干 RSS（P_eq=ΣPi，与
  ecss_multipactor_fd 现行 carrier_powers_w 口径一致）与相干最坏相位
  （V_pk=Σ√(2Pi·Z0) ⟺ P_eq=(Σ√Pi)²）。IEEE 10904461 (2025) 付费墙未读，
  其 N 载波/级联细节本内核未逐字实现（不编造）。
- 20-gap 串接：ASSUMPTION——串联分压工程口径 V_chain=N_g·V_gap
  （同频同相、等分压、各 gap 独立起燃）；"20" 取规格字面为 n_gaps 缺省语义
  由调用方给值，本内核不钉 20。

设计约束：core 叶子层（仅 import math），非法输入显式 ValueError，
不静默兜底。电压口径：本模块所有电压=峰值（rms 应用需调用方自行换算）。
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "DEFAULT_DELTA_MAX",
    "DEFAULT_EMAX_EV",
    "DEFAULT_K_S",
    "E_CHARGE_C",
    "M_E_KG",
    "SEY_MATERIALS",
    "multi_carrier_equivalent_power_w",
    "multipactor_susceptibility_check",
    "orbit_impact_energy_ev",
    "order_sustainable_band_v",
    "series_gap_chain_threshold_v",
    "sey_crossover_energies_ev",
    "susceptibility_band_v",
    "susceptibility_scale_v",
    "transit_resonance_voltage_v",
    "vaughan_angle_adjusted",
    "vaughan_yield",
]

# ---------------------------------------------------------------------------
# 常量（出处见模块 docstring；单位缀在名字里）
# ---------------------------------------------------------------------------

# CODATA 2018 电子质量 / SI 精确定义元电荷
M_E_KG = 9.1093837015e-31
E_CHARGE_C = 1.602176634e-19

# SEY 缺省参数面（UNVERIFIED——规格未给值；量级取常用金属典型带的居中值，
# 仅形状面；判定面 crossover 由此派生并随输出如实标注 UNVERIFIED）
DEFAULT_DELTA_MAX = 2.0
DEFAULT_EMAX_EV = 300.0
DEFAULT_K_S = 1.0

# Iqbal/Verboncoeur/Zhang arXiv:2507.17881v1 Table 1（VERIFIED 2026-10-02 实取）：
# 六组 PIC 模拟口径 SEY 材料参数集（δmax0 / Emax0 [eV] / E1 [eV] / E2 [eV]）
SEY_MATERIALS: dict[str, dict[str, float]] = {
    "M1": {"delta_max": 2.09, "emax_ev": 165.0, "e1_ev": 18.0, "e2_ev": 1900.0},
    "M2": {"delta_max": 2.09, "emax_ev": 277.5, "e1_ev": 42.0, "e2_ev": 3056.0},
    "M3": {"delta_max": 2.09, "emax_ev": 400.0, "e1_ev": 44.0, "e2_ev": 4604.0},
    "M4": {"delta_max": 1.2, "emax_ev": 277.5, "e1_ev": 109.5, "e2_ev": 759.5},
    "M5": {"delta_max": 1.2, "emax_ev": 400.0, "e1_ev": 158.0, "e2_ev": 1094.0},
    "M6": {"delta_max": 3.2, "emax_ev": 400.0, "e1_ev": 19.0, "e2_ev": 1550.0},
}


# ---------------------------------------------------------------------------
# 输入收敛（非法输入显式 ValueError，不静默兜底）
# ---------------------------------------------------------------------------

def _finite(value: Any, name: str) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


def _finite_pos(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，收到 {value!r}")
    return out


def _positive_int(value: Any, name: str) -> int:
    out = int(value)
    if out != value or out < 1:
        raise ValueError(f"{name} 必须为 >=1 的整数，收到 {value!r}")
    return out


# ---------------------------------------------------------------------------
# 1) 渡越时间谐振（平行板一阶理论：谐振线 + 序 n 几何带）
# ---------------------------------------------------------------------------

def susceptibility_scale_v(freq_hz: Any, gap_m: Any) -> float:
    """(f·d)² 相似标度电压尺度 K = m_e·ω²·d²/e [V]（f·d 相似标度律）。"""
    f = _finite_pos(freq_hz, "freq_hz")
    d = _finite_pos(gap_m, "gap_m")
    omega = 2.0 * math.pi * f
    return M_E_KG * omega * omega * d * d / E_CHARGE_C


def _order(order: Any) -> int:
    out = _positive_int(order, "order")
    return out


def transit_resonance_voltage_v(freq_hz: Any, gap_m: Any, order: Any = 1) -> float:
    """序 n 渡越谐振线电压 [V]（φ0=0 零交越发射的封闭周期轨道）。

    V_n = K/((2n−1)π)，K = m_e·ω²·d²/e；n=1 即经典"半周期渡越"。
    封闭性：次级电子在反向半周被加速回 first plate，周期轨道闭合
    （推导见模块 docstring）。
    """
    n = _order(order)
    k = susceptibility_scale_v(freq_hz, gap_m)
    return k / ((2.0 * n - 1.0) * math.pi)


def susceptibility_band_v(freq_hz: Any, gap_m: Any, order: Any = 1) -> dict[str, Any]:
    """序 n 几何敏感带（一阶理想化）：[K/√(4+x²), K/2]，x=(2n−1)π。

    带内每个电压对应唯一 φ0∈[0, π/2] 封闭轨道（V(φ0)=K/(2sin φ0+x·cos φ0)）。
    带边为碰撞速度→0 的边际轨道（零初速理想化局限，见 docstring）。
    """
    n = _order(order)
    x = (2.0 * n - 1.0) * math.pi
    k = susceptibility_scale_v(freq_hz, gap_m)
    v_lo = k / math.sqrt(4.0 + x * x)
    return {
        "order": n,
        "scale_v": round(k, 9),
        "v_resonance_v": round(k / x, 9),
        "band_low_v": round(v_lo, 9),
        "band_high_v": round(k / 2.0, 9),
        "phase_at_low_rad": round(math.atan2(2.0, x), 12),
        "convention": "峰值；φ0 为发射相位（场零交越起量）",
    }


def orbit_impact_energy_ev(
    voltage_v: Any,
    freq_hz: Any,
    gap_m: Any,
    phase_rad: Any,
) -> float:
    """封闭轨道碰撞能量 [eV]：E_imp = 2·V²·cos²φ0 / K（K 同上，单位 V）。

    由 v(τ)=(2eE0/mω)·cos φ0 与 E_imp=½mv² 换算（模块 docstring 推导）。
    phase_rad 为发射相位 φ0（场零交越起量，弧度）。
    """
    v_app = _finite_pos(voltage_v, "voltage_v")
    k = susceptibility_scale_v(freq_hz, gap_m)
    phase = _finite(phase_rad, "phase_rad")
    cos_p = math.cos(phase)
    return 2.0 * v_app * v_app * cos_p * cos_p / k


# ---------------------------------------------------------------------------
# 2) Vaughan SEY 参数面（曲线 UNVERIFIED / crossover 窗口 VERIFIED）
# ---------------------------------------------------------------------------

def vaughan_yield(
    energy_ev: Any,
    delta_max: Any,
    emax_ev: Any,
    k_s: Any = DEFAULT_K_S,
) -> float:
    """Vaughan 普适形状产额曲线 δ(E)=δmax·(v·e^{1−v})^{k_s}，v=E/Emax。

    UNVERIFIED 出处等级（原文付费墙，见模块 docstring）；构造恒等式：
    δ(Emax)=δmax、δ(0)=0、峰值唯一。判定面不消费本曲线。

    Raises:
        ValueError: delta_max ≤ 1（无 δ>1 窗口，与 multipactor 无关）、
            emax/k_s 非正、能量为负。
    """
    dm = _finite(delta_max, "delta_max")
    if dm <= 1.0:
        raise ValueError(f"delta_max 必须 >1（无 δ>1 窗口），收到 {delta_max!r}")
    emax = _finite_pos(emax_ev, "emax_ev")
    ks = _finite_pos(k_s, "k_s")
    energy = _finite(energy_ev, "energy_ev")
    if energy < 0.0:
        raise ValueError(f"energy_ev 必须 >=0，收到 {energy_ev!r}")
    v = energy / emax
    base = 0.0 if v == 0.0 else v * math.exp(1.0 - v)
    return dm * base ** ks


def sey_crossover_energies_ev(
    delta_max: Any,
    emax_ev: Any,
    k_s: Any = DEFAULT_K_S,
) -> dict[str, Any]:
    """Vaughan 曲线的两个 crossover 能量（δ=1 交点）[eV]。

    解 v·e^{1−v} = δmax^{−1/k_s}：左支 v1∈(0,1)（单调升）、右支 v2∈(1,∞)
    （单调降），二分法求至 1e-15 相对收敛（确定性核）。
    E1 = v1·Emax、E2 = v2·Emax。
    """
    dm = _finite(delta_max, "delta_max")
    if dm <= 1.0:
        raise ValueError(f"delta_max 必须 >1（无 δ>1 窗口），收到 {delta_max!r}")
    emax = _finite_pos(emax_ev, "emax_ev")
    ks = _finite_pos(k_s, "k_s")
    target = dm ** (-1.0 / ks)

    def f(v: float) -> float:
        return v * math.exp(1.0 - v)

    # 左支 (0,1)
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1.0e-15 * hi:
            break
    v1 = 0.5 * (lo + hi)
    # 右支 (1, ∞)：先扩张上界
    hi = 2.0
    while f(hi) > target and hi < 1.0e12:
        hi *= 2.0
    lo = 1.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if f(mid) > target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1.0e-15 * hi:
            break
    v2 = 0.5 * (lo + hi)
    return {
        "delta_max": dm,
        "emax_ev": emax,
        "k_s": ks,
        "v1": round(v1, 15),
        "v2": round(v2, 15),
        "e1_ev": round(v1 * emax, 9),
        "e2_ev": round(v2 * emax, 9),
        "curve_provenance": "UNVERIFIED（Vaughan 原文付费墙；普适形状构造）",
    }


def vaughan_angle_adjusted(
    incidence_rad: Any,
    delta_max: Any,
    emax_ev: Any,
    k_s: Any = DEFAULT_K_S,
) -> dict[str, Any]:
    """Vaughan 角依赖修正（斜入射使 δmax 与 Emax 增大）。

    δmax(θ)=δmax0·(1+k_s·θ²/2π)、Emax(θ)=Emax0·(1+k_s·θ²/π)（θ rad，
    VERIFIED-转引 arXiv:1710.01636 §II；域限 [0, π/2]）。

    Raises:
        ValueError: θ <0 或 >π/2（转引公式校准域外不外推）。
    """
    theta = _finite(incidence_rad, "incidence_rad")
    if theta < 0.0 or theta > math.pi / 2.0:
        raise ValueError(
            f"incidence_rad={theta!r} 超出转引公式域 [0, π/2]，不外推")
    dm = _finite_pos(delta_max, "delta_max")
    emax = _finite_pos(emax_ev, "emax_ev")
    ks = _finite_pos(k_s, "k_s")
    t2 = theta * theta
    dm_theta = dm * (1.0 + ks * t2 / (2.0 * math.pi))
    emax_theta = emax * (1.0 + ks * t2 / math.pi)
    return {
        "incidence_rad": round(theta, 12),
        "delta_max": round(dm_theta, 12),
        "emax_ev": round(emax_theta, 12),
        "k_s": ks,
        "provenance": "VERIFIED-转引（arXiv:1710.01636 §II 引 Vaughan 1988）",
    }


# ---------------------------------------------------------------------------
# 3) SEY 窗口门控后的序 n 可持续带（起始阈值面）
# ---------------------------------------------------------------------------

def order_sustainable_band_v(
    freq_hz: Any,
    gap_m: Any,
    order: Any,
    e1_ev: Any,
    e2_ev: Any | None = None,
) -> dict[str, Any]:
    """SEY 窗口（E_imp∈(E1,E2)）门控后的序 n 可持续电压带 [V]。

    一阶轨道碰撞能量 E_imp = 2K/(2t+x)²，t=tan φ0 ≥ 0、x=(2n−1)π
    （cos²φ0=1/(1+t²) 代入 orbit_impact_energy_ev，与 V(t)=K√(1+t²)/(2t+x)
    联立消 V）。于是：
        E_imp ≥ E1 ⟺ t ≤ (√(2K/E1) − x)/2 =: t1
        E_imp ≤ E2 ⟺ t ≥ (√(2K/E2) − x)/2 =: t2（e2 缺省不约束）
    可持续带 = V(t) 在 t∈[max(0,t2), t1] 上的像（V(t) U 形，极小在 t*=2/x）。
    t1<0 ⟺ 带内最大碰撞能量 2K/x² < E1 → 整带不可持续（empty）。

    Returns:
        dict：sustainable=False 时给 empty_reason；否则给 band_low_v /
        band_high_v / tan 窗 / 碰撞能量窗。
    """
    n = _order(order)
    e1 = _finite_pos(e1_ev, "e1_ev")
    e2 = None if e2_ev is None else _finite_pos(e2_ev, "e2_ev")
    if e2 is not None and e2 <= e1:
        raise ValueError(f"e2_ev 必须 > e1_ev，收到 {e2_ev!r} <= {e1_ev!r}")
    x = (2.0 * n - 1.0) * math.pi
    k = susceptibility_scale_v(freq_hz, gap_m)
    # E_imp 随 t 单调降：E1 门切高 t 侧（t ≤ t1）、E2 门切低 t 侧（t ≥ t2）；
    # E1 < E2 ⟹ t2 < t1 恒成立，唯一空带情形是 t1 < 0（整带碰撞能量 < E1）
    t1 = (math.sqrt(2.0 * k / e1) - x) / 2.0
    t2 = (math.sqrt(2.0 * k / e2) - x) / 2.0 if e2 is not None else -1.0
    t_lo = max(0.0, t2)
    t_hi = t1
    if t_hi < 0.0:
        return {
            "order": n,
            "sustainable": False,
            "empty_reason": "impact_below_first_crossover",
            "impact_energy_max_ev": round(2.0 * k / (x * x), 9),
            "e1_ev": e1,
        }

    def v_of_t(t: float) -> float:
        return k * math.sqrt(1.0 + t * t) / (2.0 * t + x)

    candidates = [v_of_t(t_lo), v_of_t(t_hi)]
    t_star = 2.0 / x
    if t_lo <= t_star <= t_hi:
        candidates.append(v_of_t(t_star))
    return {
        "order": n,
        "sustainable": True,
        "band_low_v": round(min(candidates), 9),
        "band_high_v": round(max(candidates), 9),
        "tan_phase_window": [round(t_lo, 12), round(t_hi, 12)],
        "impact_energy_ev_window": [
            round(2.0 * k / (2.0 * t_hi + x) ** 2, 9),
            round(2.0 * k / (2.0 * t_lo + x) ** 2, 9),
        ],
        "e1_ev": e1,
        "e2_ev": e2,
    }


# ---------------------------------------------------------------------------
# 4) N 载波等效功率 与 20-gap 串接换算
# ---------------------------------------------------------------------------

def multi_carrier_equivalent_power_w(
    powers_w: Any,
    *,
    coherent: bool = False,
    z0_ohm: Any = 50.0,
) -> dict[str, Any]:
    """N 载波等效功率/峰值电压（双口径，ECSS 惯例）。

    非相干（RSS，缺省；与 ecss_multipactor_fd 现行 carrier_powers_w 口径
    一致）：P_eq=ΣPi，V_pk=√(2·P_eq·Z0)。
    相干最坏相位（全部载波峰同时对齐）：V_pk=Σ√(2Pi·Z0) ⟺
    P_eq=(Σ√Pi)² ≥ ΣPi（相干恒不小于非相干，测试钉）。

    Raises:
        ValueError: 空表/含负或非有限功率/Z0 非正。
    """
    z0 = _finite_pos(z0_ohm, "z0_ohm")
    powers = [float(p) for p in powers_w]
    if not powers:
        raise ValueError("powers_w 须为非空功率列表")
    for idx, p in enumerate(powers):
        if not math.isfinite(p) or p < 0.0:
            raise ValueError(f"powers_w[{idx}] 必须为非负有限数，收到 {p!r}")
    total = math.fsum(powers)
    if coherent:
        root_sum = math.sqrt(2.0 * z0) * math.fsum(math.sqrt(p) for p in powers)
        v_pk = root_sum
        p_eq = v_pk * v_pk / (2.0 * z0)
        convention = "coherent_worst_phase"
    else:
        p_eq = total
        v_pk = math.sqrt(2.0 * total * z0)
        convention = "incoherent_rss"
    return {
        "n_carriers": len(powers),
        "powers_w": powers,
        "total_power_w": round(total, 12),
        "convention": convention,
        "equivalent_power_w": round(p_eq, 12),
        "peak_voltage_v": round(v_pk, 12),
        "z0_ohm": z0,
        "voltage_convention": "峰值",
    }


def series_gap_chain_threshold_v(
    threshold_single_gap_v: Any,
    n_gaps: Any,
) -> float:
    """串联 gap 链（如 20-gap 串接）的链级击穿阈值 [V]（ASSUMPTION 口径）。

    V_chain = N_g·V_gap_single：同频同相、各 gap 等分压、各 gap 独立满足
    渡越谐振时的链级总电压阈值。规格出处（IEEE 10904461, 2025）付费墙未读，
    本式为串联分压工程口径、如实标注 ASSUMPTION（见模块 docstring）。

    Raises:
        ValueError: 单隙阈值非正；n_gaps 非 >=1 整数。
    """
    thr = _finite_pos(threshold_single_gap_v, "threshold_single_gap_v")
    n = _positive_int(n_gaps, "n_gaps")
    return thr * n


# ---------------------------------------------------------------------------
# 5) 合成判据报告（注册计算器面：multipactor_susceptibility_check）
# ---------------------------------------------------------------------------

def multipactor_susceptibility_check(
    freq_hz: Any,
    gap_m: Any,
    *,
    voltage_v: Any | None = None,
    power_w: Any | None = None,
    z0_ohm: Any = 50.0,
    carrier_powers_w: list | None = None,
    carrier_coherent: bool = False,
    delta_max: Any = DEFAULT_DELTA_MAX,
    emax_ev: Any = DEFAULT_EMAX_EV,
    e1_ev: Any | None = None,
    e2_ev: Any | None = None,
    k_s: Any = DEFAULT_K_S,
    order_max: Any = 10,
    required_margin_db: Any = 6.0,
) -> dict[str, Any]:
    """MP-3 multipactor 三面合成报告（机制敏感带 × SEY 窗口 × 级联/多载波换算）。

    判定链：对每序 n=1..order_max 求 SEY 门控可持续带（order_sustainable_band_v，
    窗口 crossover 由显式 e1_ev/e2_ev 或 Vaughan 曲线派生），施加峰值电压
    落带内即"模型敏感"。verdict 语义仅对本一阶理想化模型自洽——真实阈值
    以 ECSS 实验包络（high_power.multipactor_fd_check / ecss_multipactor_fd）
    为工程仲裁，本报告 notes 固定带此指向。

    pass 语义：施加点距最近可持续区边缘的裕量 ≥ required_margin_db——
    低压侧 margin=20log10(onset/V)；落带内 pass=False；高于全部可持续带
    margin=20log10(V/region_high)（模型域外注记见上）。

    Raises:
        ValueError: 频率/间隙/电压非正；载波表非法；e1/e2 只给其一；
            e2 ≤ e1；delta_max ≤ 1；order_max 非 >=1 整数。
    """
    f = _finite_pos(freq_hz, "freq_hz")
    d = _finite_pos(gap_m, "gap_m")
    n_ord_max = _positive_int(order_max, "order_max")
    req_db = _finite(required_margin_db, "required_margin_db")
    dm = _finite(delta_max, "delta_max")
    if dm <= 1.0:
        raise ValueError(f"delta_max 必须 >1（无 δ>1 窗口），收到 {delta_max!r}")
    _finite_pos(emax_ev, "emax_ev")
    _finite_pos(k_s, "k_s")
    if (e1_ev is None) != (e2_ev is None):
        raise ValueError("e1_ev/e2_ev 须成对给出或同时缺省（缺省走曲线派生）")
    if e1_ev is not None:
        e1 = _finite_pos(e1_ev, "e1_ev")
        e2 = _finite_pos(e2_ev, "e2_ev")
        if e2 <= e1:
            raise ValueError(f"e2_ev 必须 > e1_ev，收到 {e2!r} <= {e1!r}")
        sey_provenance = "explicit_input"
        curve = None
    else:
        curve = sey_crossover_energies_ev(dm, emax_ev, k_s)
        e1 = float(curve["e1_ev"])
        e2 = float(curve["e2_ev"])
        sey_provenance = "derived_vaughan_curve_UNVERIFIED"

    # 施加峰值电压（与 ecss_multipactor_fd 同优先级：电压 > 载波表 > 单功率）
    carrier_report: dict[str, Any] | None = None
    if voltage_v is not None:
        v_app = _finite_pos(voltage_v, "voltage_v")
    elif carrier_powers_w is not None:
        carrier_report = multi_carrier_equivalent_power_w(
            carrier_powers_w, coherent=carrier_coherent, z0_ohm=z0_ohm)
        v_app = float(carrier_report["peak_voltage_v"])
    elif power_w is not None:
        p = _finite_pos(power_w, "power_w")
        z0 = _finite_pos(z0_ohm, "z0_ohm")
        v_app = math.sqrt(2.0 * p * z0)
    else:
        raise ValueError("需提供 voltage_v / power_w / carrier_powers_w 之一")

    orders: list[dict[str, Any]] = []
    susceptible_orders: list[int] = []
    band_lows: list[float] = []
    band_highs: list[float] = []
    for n in range(1, n_ord_max + 1):
        band = order_sustainable_band_v(f, d, n, e1, e2)
        if band["sustainable"]:
            lo = float(band["band_low_v"])
            hi = float(band["band_high_v"])
            in_band = lo <= v_app <= hi
            entry = dict(band)
            entry["in_band"] = in_band
            band_lows.append(lo)
            band_highs.append(hi)
            if in_band:
                susceptible_orders.append(n)
        else:
            entry = dict(band)
            entry["in_band"] = False
        orders.append(entry)

    susceptible = bool(susceptible_orders)
    onset_v = min(band_lows) if band_lows else None
    region_high = max(band_highs) if band_highs else None

    margin_to_onset_db: float | None = None
    margin_above_db: float | None = None
    if onset_v is not None:
        margin_to_onset_db = round(20.0 * math.log10(onset_v / v_app), 9)
    if region_high is not None and v_app > region_high:
        margin_above_db = round(20.0 * math.log10(v_app / region_high), 9)

    notes = [
        "一阶理想化模型（零初速发射）verdict 仅自洽于本模型；工程仲裁走 "
        "high_power.multipactor_fd_check 的 ECSS-E-ST-20-01C 实验包络",
        "SEY 窗口判据 VERIFIED（Kishek & Lau PAC97；Rosario & Edén 2012 转引）；"
        "Vaughan 产额曲线形状 UNVERIFIED（原文付费墙），判定面只消费 crossover",
    ]
    if margin_above_db is not None:
        notes.append("施加点高于全部可持续带（模型域内无封闭周期轨道）；"
                     "单表面/介质窗 multipactor 未建模，勿据此免检")
    if onset_v is None:
        notes.append("order_max 内无可持续轨道（碰撞能量全窗 < E1）——"
                     "可加大 order_max 复核或视为模型域内安全")

    if margin_above_db is not None:
        pass_ = margin_above_db >= req_db
    elif onset_v is None:
        pass_ = True
    else:
        pass_ = margin_to_onset_db >= req_db

    return {
        "freq_hz": f,
        "gap_m": d,
        "fxd_ghz_mm": round(f * d / 1.0e9 / 1.0e-3, 12),
        "applied_voltage_v": round(v_app, 12),
        "voltage_convention": "峰值",
        "carrier": carrier_report,
        "sey": {
            "delta_max": dm,
            "emax_ev": emax_ev,
            "k_s": k_s,
            "e1_ev": e1,
            "e2_ev": e2,
            "provenance": sey_provenance,
        },
        "order_max": n_ord_max,
        "orders": orders,
        "susceptible": susceptible,
        "susceptible_orders": susceptible_orders,
        "onset_threshold_v": None if onset_v is None else round(onset_v, 9),
        "sustainable_region_high_v": (
            None if region_high is None else round(region_high, 9)),
        "margin_to_onset_db": margin_to_onset_db,
        "margin_above_bands_db": margin_above_db,
        "required_margin_db": req_db,
        "pass": bool(pass_),
        "notes": notes,
    }
