"""NX-11 WPT 效率包络 + rectenna 链闭式面。

规格：研究扩充 round14 §四 NX-11——"nfc_coil
补 Qi2/Qi2.2 15/25W 效率包络；远场 Friis+整流效率-功率曲线（Ph5 溢出池
rectenna 件具体化）"。纯闭式叶子，零 IO、不进 calculators。

模块面
------
- ``link_max_efficiency``：谐振感应链最大效率 η_max = χ/(1+√(1+χ))²，
  χ = k²·Q1·Q2（磁共振耦合标准闭式，Kurs 2007 口径名）——与全电路
  数值求效率的最大化互证（#118 双路）。
- ``optimal_load``：R_L,opt = ω·L2·√(1+χ)/Q2（同口径闭式）。
- ``link_efficiency_vs_load``：给定 R_L 的链效率（全电路 2×2 线性系统
  解，独立裁判路）。
- ``qi_power_envelope``：Qi2/Qi2.2 功率级登记面（15 W 基线/25 W 扩展）
  + 典型 coil k/Q 带下的 η_max 包络（band+single_source：WPC 规范
  专有，只登记公开新闻稿级事实，不冒充规范值）。
- ``friis_received_power``：P_rx = P_tx·G_t·G_r·(λ/4πd)²·η_pol·η_misc。
- ``rectifier_efficiency_curve``：整流效率-输入功率 S 曲线参数面
  （band+single_source：文献带参数化，饱和 η_pk/膝点功率登记带）。
- ``rectenna_dc_budget``：Friis + rectifier 链端到端 DC 预算。

物理口径（全 SI）
------------------
* 链效率模型：串联谐振两网孔（L1-R1-C1 ‖ M ‖ L2-R2-C2-R_L），谐振
  调谐 ω=1/√(L1C1)=1/√(L2C2)；η = P_L/P_in（P_in=实部 V1·I1*）。
  χ=k²Q1Q2、Q_i=ωL_i/R_i。
* 设计约束：numpy/cmath 纯函数；非法输入显式 ValueError；dict 有限数。

出处
----
1. round 文档：round14 §四 NX-11。
2. Kurs et al., Science 317, 83 (2007)（η_max 闭式口径名）；WPC Qi2/
   Qi2.2 公开新闻稿级事实（15 W/25 W，规范专有不抄，UNVERIFIED 如实）；
   rectifier 效率带（2.45 GHz 整流文献带，single_source band）。
"""
from __future__ import annotations

import math
from typing import Any

__all__ = [
    "C0_M_S",
    "QI2_POWER_REGISTER",
    "WPT_SOURCE",
    "friis_received_power",
    "link_efficiency_vs_load",
    "link_max_efficiency",
    "optimal_load",
    "qi_power_envelope",
    "rectenna_dc_budget",
    "rectifier_efficiency_curve",
]

C0_M_S = 299792458.0
WPT_SOURCE = (
    "Kurs et al. Science 317 (2007)（η_max 闭式口径名）；WPC Qi2/Qi2.2 "
    "公开级事实（功率级登记，规范专有不抄，UNVERIFIED 如实）；rectifier "
    "效率文献带（single_source band，#122）"
)

#: Qi2/Qi2.2 功率级登记（公开新闻稿级事实；规范值 UNVERIFIED 不冒充）
QI2_POWER_REGISTER: dict[str, Any] = {
    "Qi2_BPP_MPP_baseline_w": 15.0,
    "Qi2_2_extended_w": 25.0,
    "frequency_band_hz": (1.0e5, 2.2e6),  # Qi 基线频段（公开级）
    "source": (
        "WPC 公开新闻稿级事实（Qi2=15W MPP 基线、Qi2.2=25W 扩展）；"
        "规范正文专有——UNVERIFIED 如实，#122 不冒充规范值"
    ),
}


def _positive(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def _nonneg(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v < 0.0:
        raise ValueError(f"{name} 必须为非负有限数，实际 {x!r}")
    return v


def _coupling_coefficient(m_h: Any, l1_h: Any, l2_h: Any) -> float:
    m = _positive(m_h, "m_h")
    l1 = _positive(l1_h, "l1_h")
    l2 = _positive(l2_h, "l2_h")
    k = m / math.sqrt(l1 * l2)
    if k > 1.0:
        raise ValueError(f"耦合系数 k=M/√(L1L2)={k:.3f}>1（非物理）")
    return k


def link_max_efficiency(k: Any, q1: Any, q2: Any) -> dict[str, float]:
    """谐振感应链最大效率闭式：η_max = χ/(1+√(1+χ))²，χ=k²Q1Q2。

    极限锚：χ→0 → η≈χ/4；χ→∞ → η→1−2/√χ（渐近）。Q 必须 ≥1（数值
    语义；Q<1 显式 ValueError——非谐振口径不在此语义内）。
    """
    kk = _nonneg(k, "k")
    if kk > 1.0:
        raise ValueError(f"k 须 ∈ [0,1]，实际 {k!r}")
    q1 = _positive(q1, "q1")
    q2 = _positive(q2, "q2")
    if q1 < 1.0 or q2 < 1.0:
        raise ValueError("Q1/Q2 须 >=1（谐振语义，非谐振口径不在此内）")
    chi = kk * kk * q1 * q2
    root = math.sqrt(1.0 + chi)
    eta = chi / (1.0 + root) ** 2
    return {"eta_max": eta, "chi": chi}


def optimal_load(omega_rad_s: Any, l2_h: Any, q2: Any, k: Any,
                 q1: Any) -> dict[str, float]:
    """最佳负载 R_L,opt = ω·L2·√(1+χ)/Q2（η_max 对应的负载闭式）。"""
    w = _positive(omega_rad_s, "omega_rad_s")
    l2 = _positive(l2_h, "l2_h")
    q2v = _positive(q2, "q2")
    out = link_max_efficiency(k, q1, q2v)
    chi = out["chi"]
    r_opt = w * l2 * math.sqrt(1.0 + chi) / q2v
    return {"r_load_opt_ohm": r_opt, "chi": chi}


def link_efficiency_vs_load(v_source_v: Any, r_source_ohm: Any,
                            l1_h: Any, c1_f: Any, r1_ohm: Any,
                            l2_h: Any, c2_f: Any, r2_ohm: Any,
                            m_h: Any, r_load_ohm: Any,
                            f_hz: Any) -> dict[str, float]:
    """两网孔串联谐振链效率（全电路 2×2 线性系统，独立裁判路）。

    Z1 = R1 + j(ωL1−1/ωC1)、Z2 = R2 + R_L + j(ωL2−1/ωC2)；
    [V; 0] = [[Z1, jωM], [jωM, Z2]]·[I1; I2] → η = |I2|²R_L/Re(V·I1*)。
    """
    vs = _positive(v_source_v, "v_source_v")
    _ = _positive(r_source_ohm, "r_source_ohm")
    l1 = _positive(l1_h, "l1_h")
    c1 = _positive(c1_f, "c1_f")
    r1 = _nonneg(r1_ohm, "r1_ohm")
    l2 = _positive(l2_h, "l2_h")
    c2 = _positive(c2_f, "c2_f")
    r2 = _nonneg(r2_ohm, "r2_ohm")
    m = _positive(m_h, "m_h")
    rl = _positive(r_load_ohm, "r_load_ohm")
    f = _positive(f_hz, "f_hz")
    _ = _coupling_coefficient(m, l1, l2)
    w = 2.0 * math.pi * f
    z1 = complex(r1, w * l1 - 1.0 / (w * c1))
    z2 = complex(r2 + rl, w * l2 - 1.0 / (w * c2))
    z_m = complex(0.0, w * m)
    det = z1 * z2 - z_m * z_m
    i1 = vs * z2 / det
    i2 = -vs * z_m / det
    p_in = (vs * i1.conjugate()).real
    p_load = abs(i2) ** 2 * rl
    if p_in <= 0.0:
        raise ValueError("输入有功功率 ≤0（参数组合非法）")
    return {"eta": p_load / p_in, "p_in_w": p_in, "p_load_w": p_load,
            "i1_a": abs(i1), "i2_a": abs(i2)}


def qi_power_envelope(k: Any, q_coil: Any) -> dict[str, Any]:
    """Qi2/Qi2.2 效率包络登记面：功率级 + 给定 k/Q 下的 η_max 包络。

    q_coil：两圈同 Q 的工程口径（Q1=Q2=q_coil）。返回三功率点的
    端到端上限语义（η_max 是链上限，DC-DC/整流损耗另计——如实声明）。
    """
    q = _positive(q_coil, "q_coil")
    out = link_max_efficiency(k, q, q)
    register = dict(QI2_POWER_REGISTER)
    register.update({
        "k": k,
        "q_coil": q,
        "chi": out["chi"],
        "eta_max_link": out["eta_max"],
        "note": ("η_max 为链上限；整流/整流前匹配损耗另计（如实声明）"),
    })
    return register


def friis_received_power(p_tx_w: Any, g_tx: Any, g_rx: Any, f_hz: Any,
                         distance_m: Any, pol_mismatch: Any = 1.0,
                         misc_eff: Any = 1.0) -> dict[str, float]:
    """Friis 接收功率：P_rx = P_tx·G_t·G_r·(λ/4πd)²·η_pol·η_misc。"""
    ptx = _positive(p_tx_w, "p_tx_w")
    gt = _positive(g_tx, "g_tx")
    gr = _positive(g_rx, "g_rx")
    f = _positive(f_hz, "f_hz")
    d = _positive(distance_m, "distance_m")
    pol = _nonneg(pol_mismatch, "pol_mismatch")
    misc = _nonneg(misc_eff, "misc_eff")
    if pol > 1.0 or misc > 1.0:
        raise ValueError("pol_mismatch/misc_eff 须 ∈ [0,1]")
    lam = C0_M_S / f
    prx = ptx * gt * gr * (lam / (4.0 * math.pi * d)) ** 2 * pol * misc
    return {"p_rx_w": prx, "lambda_m": lam,
            "path_loss_db": -10.0 * math.log10(
                (lam / (4.0 * math.pi * d)) ** 2)}


def rectifier_efficiency_curve(p_in_w: Any, eta_peak: Any = 0.80,
                               p_knee_w: Any = 1.0e-4,
                               p_sat_w: Any = 1.0e-1) -> dict[str, float]:
    """整流效率-输入功率 S 曲面（参数化 band，single_source 如实）。

    η(p) = η_pk·(1−exp(−p/p_knee))·1/(1+p/p_sat)——低功率指数膝 +
    高功率饱和/退化乘子；参数带（η_pk 0.7–0.85、p_knee 1e-5–1e-3 W、
    p_sat 0.05–0.2 W）为 2.45 GHz 整流文献带（band+single_source，
    #122 不冒充实测）。
    """
    p = _nonneg(p_in_w, "p_in_w")
    epk = _positive(eta_peak, "eta_peak")
    pk = _positive(p_knee_w, "p_knee_w")
    ps = _positive(p_sat_w, "p_sat_w")
    if epk > 1.0:
        raise ValueError("eta_peak 须 ≤1")
    eta = epk * (1.0 - math.exp(-p / pk)) / (1.0 + p / ps)
    return {"eta_rf_dc": eta, "p_dc_w": p * eta, "p_in_w": p}


def rectenna_dc_budget(p_tx_w: Any, g_tx: Any, g_rx: Any, f_hz: Any,
                       distance_m: Any, rect_params: dict[str, Any] | None = None
                       ) -> dict[str, Any]:
    """rectenna 端到端：Friis → 整流 → DC（链预算面）。"""
    fr = friis_received_power(p_tx_w, g_tx, g_rx, f_hz, distance_m)
    params = rect_params or {}
    rect = rectifier_efficiency_curve(fr["p_rx_w"], **params)
    return {
        "p_rx_w": fr["p_rx_w"],
        "path_loss_db": fr["path_loss_db"],
        "eta_rf_dc": rect["eta_rf_dc"],
        "p_dc_w": rect["p_dc_w"],
        "note": ("rectifier 参数为文献带（single_source）；判据面只做"
                 "预算不替代实测"),
    }
