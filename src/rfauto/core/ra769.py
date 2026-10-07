"""LT-2 射电天文有害干扰门限核（RA.769 口径：判据链闭式 + 干扰几何）。

规格（round18 LT-2 / ge8b 席6 任务书 LT-3）：PFD→接收功率 + 角离轴旁瓣
包络判 detrimental。

**诚实边界（#122，预声明）**：RA.769-2 原表（逐带 T_sys/Δf/τ/PFD 门限
数值）在本批执行环境不可达（itu.int PDF 404、镜像 404、检索限流，
2026-10-03 实测）——**本模块不 ship 原表数值**（不凑绿）；交付：
1. 判据链闭式核：RA.769 定义式（有害干扰=使系统噪声温度恶化 10% 的
   干扰，τ=2000 s 口径）由辐射计方程闭式导出门限功率/PFD；
2. PFD↔接收功率几何（有效口径 A_e=Gλ²/4π）；
3. 角离轴旁瓣包络（ITU 式三段包络，常数由调用方按所适用的 ITU-R 规则
   版本给入——S.465/RA.769 各版常数不同，本核不钉死）；
4. 干扰几何 margin 链（EIRP−FSPL+G_off(θ) vs 门限 → margin/verdict）。

原表数值接线：调用方以逐带参数 (t_sys_k, delta_f_hz, tau_s) 或显式
pfd_dbw_m2 阈值给入（原文核对后回填 constants——重开条件见汇报）。
k_B 取 SI 2019 精确值 1.380649e-23 J/K（CODATA 精确常数，双源无虞）。

出处：ITU-R RA.769-2《Protection criteria used for radio astronomical
measurements》（定义式：10% 判据 + 辐射计方程；原文表格数值本批不可达，
见诚实边界）；辐射计方程为教科书级（Dicke 1946 族）闭式。
"""

from __future__ import annotations

import math
from typing import Any

#: 玻尔兹曼常数（SI 2019 精确值，J/K）
K_B = 1.380649e-23

#: 真空波速（m/s，与仓内 nf_transform 同源常数）
_C0 = 299792458.0


def _finite(x: Any, name: str, *, positive: bool = False) -> float:
    v = float(x)
    if not math.isfinite(v):
        raise ValueError(f"{name} 必须有限，实际 {x!r}")
    if positive and v <= 0.0:
        raise ValueError(f"{name} 必须为正，实际 {x!r}")
    return v


def detrimental_power_dbw(t_sys_k: Any, delta_f_hz: Any, tau_s: Any, *,
                          fraction: float = 0.1) -> dict[str, Any]:
    """RA.769 判据链闭式：有害干扰功率门限（dBW）。

    定义式（RA.769 的 10% 判据 + 辐射计方程 ΔT=T_sys/√(Δf·τ)）：
    有害干扰 = 使系统噪声温度恶化 ``fraction``（缺省 10%）的干扰功率：

        P_H = fraction · k_B · T_sys · √(Δf / τ)   [W]

    Args:
        t_sys_k: 系统噪声温度 [K]（>0）。 delta_f_hz: 判据带宽 [Hz]（>0）。
        tau_s: 积分时间 [s]（>0；RA.769 口径 2000 s，由调用方给入）。
        fraction: 恶化分数（缺省 0.1=10%，RA.769 定义）。

    Returns:
        dict(p_limit_dbw, delta_t_k, fraction, delta_f_hz, tau_s,
        provenance)
    """
    t_sys = _finite(t_sys_k, "t_sys_k", positive=True)
    df = _finite(delta_f_hz, "delta_f_hz", positive=True)
    tau = _finite(tau_s, "tau_s", positive=True)
    frac = _finite(fraction, "fraction", positive=True)
    p_limit_w = frac * K_B * t_sys * math.sqrt(df / tau)
    return {
        "p_limit_dbw": 10.0 * math.log10(p_limit_w),
        "delta_t_k": frac * t_sys,
        "fraction": frac,
        "delta_f_hz": df,
        "tau_s": tau,
        "provenance": ("radiometer-equation closed form (RA.769 10% "
                       "criterion); per-band T_sys/delta_f/tau from "
                       "caller-supplied RA.769-2 table values"),
    }


def effective_area(gain_dbi: Any, freq_hz: Any) -> float:
    """口径定理：A_e = G·λ²/(4π) [m²]（无耗天线定理，闭式）。"""
    g_lin = 10.0 ** (_finite(gain_dbi, "gain_dbi") / 10.0)
    f = _finite(freq_hz, "freq_hz", positive=True)
    lam = _C0 / f
    return g_lin * lam * lam / (4.0 * math.pi)


def pfd_to_received_power(pfd_dbw_m2: Any, gain_dbi: Any,
                          freq_hz: Any) -> float:
    """PFD [dBW/m²] → 接收功率 [dBW]（经口径定理，闭式）。"""
    ae = effective_area(gain_dbi, freq_hz)
    return _finite(pfd_dbw_m2, "pfd_dbw_m2") + 10.0 * math.log10(ae)


def received_power_to_pfd(p_rx_dbw: Any, gain_dbi: Any,
                          freq_hz: Any) -> float:
    """接收功率 → PFD（口径定理逆变换；与 pfd_to_received_power 互逆）。"""
    ae = effective_area(gain_dbi, freq_hz)
    return _finite(p_rx_dbw, "p_rx_dbw") - 10.0 * math.log10(ae)


def off_axis_gain_envelope(
    theta_deg: Any, *,
    g_max_dbi: Any, theta_break_deg: Any,
    slope_db_per_decade: Any, floor_dbi: Any,
) -> float:
    """角离轴旁瓣包络 [dBi]（三段式，常数调用方给入）。

    G(θ) = G_max                                  (θ < θ_break)
         = max(G_max − slope·log10(θ/θ_break), floor)  (θ ≥ θ_break)

    常数按所适用 ITU-R 规则版本给入（如 S.465 系/RA.769 引用的各版包络
    常数不同，本核不钉死——见模块 docstring 诚实边界）。
    """
    th = _finite(theta_deg, "theta_deg", positive=True)
    g_max = _finite(g_max_dbi, "g_max_dbi")
    th_b = _finite(theta_break_deg, "theta_break_deg", positive=True)
    slope = _finite(slope_db_per_decade, "slope_db_per_decade", positive=True)
    floor = _finite(floor_dbi, "floor_dbi")
    if th <= th_b:
        return g_max
    return max(g_max - slope * math.log10(th / th_b), floor)


def interference_margin(
    eirp_dbw: Any, distance_m: Any, freq_hz: Any,
    off_axis_deg: Any, rx_gain_dbi: Any,
    p_limit_dbw: Any, *,
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """干扰几何 margin 链：EIRP − FSPL + G_rx(θ_off) vs 门限 → margin。

    envelope=None 时按主瓣增益直射（θ_off=0 的保守上界分支）；给入时
    用 :func:`off_axis_gain_envelope` 判离轴旁瓣（"角离轴旁瓣包络判
    detrimental"）。margin = P_limit − P_rx（正=合规）。
    """
    eirp = _finite(eirp_dbw, "eirp_dbw")
    dist = _finite(distance_m, "distance_m", positive=True)
    f = _finite(freq_hz, "freq_hz", positive=True)
    th = _finite(off_axis_deg, "off_axis_deg")
    if th < 0.0:
        raise ValueError(f"off_axis_deg 必须 ≥0，实际 {th}")
    p_lim = _finite(p_limit_dbw, "p_limit_dbw")
    lam = _C0 / f
    fspl_db = 20.0 * math.log10(4.0 * math.pi * dist / lam)
    if envelope is None:
        if th > 0.0:
            raise ValueError(
                "envelope=None 仅支持主瓣直射（off_axis_deg=0）；离轴判"
                "定请给入 envelope 常数表")
        g_rx = _finite(rx_gain_dbi, "rx_gain_dbi")
        g_note = "mainlobe_direct"
    else:
        g_rx = off_axis_gain_envelope(th, **envelope)
        g_note = "off_axis_envelope"
    p_rx = eirp - fspl_db + g_rx
    margin_db = p_lim - p_rx
    return {
        "p_rx_dbw": p_rx,
        "fspl_db": fspl_db,
        "rx_gain_dbi": g_rx,
        "gain_path": g_note,
        "margin_db": margin_db,
        "verdict": ("compliant" if margin_db >= 0.0 else "detrimental"),
        "p_limit_dbw": p_lim,
        "wavelength_m": lam,
    }
