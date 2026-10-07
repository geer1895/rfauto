"""LT-11 微波光子 IMDD 链路闭式三件套（Cox 口径：MZM/增益/NF/SFDR）。

规格（round18 LT-11 / ge8b 席6 任务书 LT-4）：MZM 贝塞尔传递 + 正交/零
偏置；链路增益；NF=RIN/散粒/热三源；SFDR 复用（与 cascade IP3 同式）。

**诚实边界（#122，预声明）**：Cox《Analog Optical Links》书页码锚本批
不可达（网络限流，2026-10-03 实测）——公式按第一性推导闭式落档（推导
见各函数 docstring），内部锚四件（Bessel 恒等/scipy 对拍、正交偏置偶次
谐波归零、零偏置奇次归零、无耗极限 NF=1）测试钉死；Cox 书数值例锚
**pending（网络门）**，回填后如出现系数分歧以书为准重开。

物理口径（e^{+jωt}）：MZM 双臂干涉强度传递
    P_out(t) = P_in/2 · [1 + cos(φ_b + m·cos(ωt))],  m = π·v/V_π
    φ_b = π·V_bias/V_π（正交偏置 φ_b=π/2 即 V_bias=V_π/2；零偏置=传输
    零点 φ_b=π 即 V_bias=V_π）。
谐波展开（Bessel 恒等式）：cos(φ_b+m·cosθ) 的 n 次谐波幅度
    偶次 n=2k: |2·J_{2k}(m)·cosφ_b|；奇次 n=2k+1: |2·J_{2k+1}(m)·sinφ_b|
    （J_n 第一类贝塞尔）。正交偏置 cosφ_b=0 → 偶次全零；零点偏置
    sinφ_b=0 → 奇次全零（MZM 经典性质，测试钉）。

小信号链路增益（匹配源 R_s 驱动 MZM 电极 R_m=R_s，光电二极管负载 R_L）：
    斜率效率 s = R_d·π·P_0/(2V_π)  [A/V]（正交偏置 |dP/dV| 最大点）
    v_electrode = v_s/2（匹配分压）
    G = s²·R_s·R_L/2
NF 三源（输出端功率谱密度，单边带，匹配负载）：
    热源入射：G·kT；负载热：kT；散粒：q·I_pd·R_L/2；RIN：RIN·I_pd²·R_L/4
    NF = (G·kT + kT + q·I_pd·R_L/2 + RIN·I_pd²·R_L/4) / (G·kT)
    无耗极限检查（G=1、无光噪声）：NF=1（无耗匹配网络 NF=1，测试钉）。
SFDR（三阶无杂散动态范围，dB·Hz^{2/3} 口径）：SFDR = (2/3)·(OIP3−N_out)
    （与 core/cascade.cascade_budget 的 sfdr_db 同式族）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import scipy.special as sp

_K_B = 1.380649e-23
_Q_E = 1.602176634e-19   # 元电荷（SI 2019 精确值）
_T_REF = 290.0           # IEEE 口径参考噪声温度 [K]


def _pos(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def _nonneg(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v < 0.0:
        raise ValueError(f"{name} 必须非负有限数，实际 {x!r}")
    return v


def mzm_power_transfer(v_drive_v: Any, v_pi_v: Any,
                       bias_v: Any, p_in_w: Any) -> Any:
    """MZM 强度传递 P_out = P_in/2·[1+cos(π(V_b+v)/V_π)]（可广播，含谐波）。"""
    v_pi = _pos(v_pi_v, "v_pi_v")
    p_in = _pos(p_in_w, "p_in_w")
    v = np.asarray(v_drive_v, dtype=float)
    phi = math.pi * (float(bias_v) + v) / v_pi
    return 0.5 * p_in * (1.0 + np.cos(phi))


def mzm_harmonic_amplitudes(v_peak_v: Any, v_pi_v: Any, bias_v: Any,
                            n_harmonics: int) -> dict[str, Any]:
    """MZM 输出谐波幅度表（贝塞尔展开，相对 P_in 归一）。

    n=0 为直流项幅度 |J_0(m)·cosφ_b|/2·...（含直流偏置项 1/2）；交流 n 次
    谐波幅度按模块 docstring 恒等式（|2J_n·cos/sinφ_b|/2 相对 P_in）。
    """
    v_pi = _pos(v_pi_v, "v_pi_v")
    m = math.pi * _nonneg(v_peak_v, "v_peak_v") / v_pi
    phi_b = math.pi * float(bias_v) / v_pi
    n_max = int(n_harmonics)
    if n_max < 0:
        raise ValueError("n_harmonics 必须 ≥0")
    amps = np.zeros(n_max + 1)
    for n in range(n_max + 1):
        if n == 0:
            amps[0] = 0.5 * (1.0 + sp.jv(0, m) * math.cos(phi_b))
        elif n % 2 == 0:
            amps[n] = abs(sp.jv(n, m) * math.cos(phi_b))
        else:
            amps[n] = abs(sp.jv(n, m) * math.sin(phi_b))
    return {
        "modulation_index": m,
        "bias_phase_rad": phi_b,
        "amplitudes_rel_pin": amps,
        "n_harmonics": n_max,
    }


def imdd_link_gain(p_opt_w: Any, v_pi_v: Any, responsivity_a_per_w: Any,
                   r_source_ohm: Any, r_load_ohm: Any) -> dict[str, Any]:
    """IMDD 小信号链路增益 G = (R_d·π·P_0/(2V_π))²·R_s·R_L/2（推导见模块 docstring）。"""
    p0 = _pos(p_opt_w, "p_opt_w")
    vpi = _pos(v_pi_v, "v_pi_v")
    rd = _pos(responsivity_a_per_w, "responsivity_a_per_w")
    rs = _pos(r_source_ohm, "r_source_ohm")
    rl = _pos(r_load_ohm, "r_load_ohm")
    slope = rd * math.pi * p0 / (2.0 * vpi)
    g = slope * slope * rs * rl / 2.0
    return {
        "gain_linear": g,
        "gain_db": 10.0 * math.log10(g) if g > 0.0 else -math.inf,
        "slope_efficiency_a_per_v": slope,
        "i_pd_dc_a": rd * p0,
    }


def imdd_noise_figure(p_opt_w: Any, v_pi_v: Any, responsivity_a_per_w: Any,
                      r_source_ohm: Any, r_load_ohm: Any, *,
                      rin_per_hz: Any = 0.0, temp_k: Any = _T_REF,
                      bandwidth_hz: Any = 1.0) -> dict[str, Any]:
    """NF 三源闭式（热/散粒/RIN，推导见模块 docstring；带宽内总噪声与输出）。"""
    g_dict = imdd_link_gain(p_opt_w, v_pi_v, responsivity_a_per_w,
                            r_source_ohm, r_load_ohm)
    g = float(g_dict["gain_linear"])
    i_pd = float(g_dict["i_pd_dc_a"])
    rl = _pos(r_load_ohm, "r_load_ohm")
    rin = _nonneg(rin_per_hz, "rin_per_hz")
    tk = _pos(temp_k, "temp_k")
    bw = _pos(bandwidth_hz, "bandwidth_hz")
    n_in_thermal = g * _K_B * tk          # 输入热噪 ×G
    n_load_thermal = _K_B * tk            # 负载热噪（匹配，可用功率 kT）
    n_shot = _Q_E * i_pd * rl / 2.0       # 散粒（单边带交付负载）
    n_rin = rin * i_pd * i_pd * rl / 4.0  # RIN（单边带交付负载）
    n_out = n_in_thermal + n_load_thermal + n_shot + n_rin
    nf = n_out / (g * _K_B * tk)
    return {
        "nf_linear": nf,
        "nf_db": 10.0 * math.log10(nf),
        "noise_out_w_per_hz": {"thermal_in": n_in_thermal,
                               "thermal_load": n_load_thermal,
                               "shot": n_shot, "rin": n_rin,
                               "total": n_out},
        "noise_out_total_w": n_out * bw,
        "gain_linear": g,
        "gain_db": g_dict["gain_db"],
        "i_pd_dc_a": i_pd,
    }


def imdd_sfdr(oip3_dbm: Any, noise_out_dbm: Any) -> float:
    """SFDR（dB·Hz^{2/3} 口径）：SFDR = (2/3)·(OIP3 − N_out)（cascade 同式族）。"""
    oip3 = float(oip3_dbm)
    n_out = float(noise_out_dbm)
    return (2.0 / 3.0) * (oip3 - n_out)
