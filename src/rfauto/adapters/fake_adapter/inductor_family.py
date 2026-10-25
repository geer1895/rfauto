"""octagonal_spiral fake 家族（aurora_k K11，反馈 F1）。

一阶集总电感单端口模型：几何 → core Mohan current_sheet 闭式 L →
core 匝间寄生电容一阶估计 C_par → 并联寄生谐振（SRF）自洽 S11。
代码体独立成件（slotline_family 承载 coil_nfc 的先例——家族文件按
物理域命名，本件=集总无源电感族首件）。
"""

from __future__ import annotations

from typing import Any


def _octagonal_spiral_sparams(freq_ghz: Any, n_turns: int = 5,
                              din_um: float = 80.0, w_um: float = 10.0,
                              s_um: float = 5.0, z0: float = 50.0,
                              t_um: float = 3.0, er: float = 12.9,
                              **_: Any) -> Any:
    """octagonal_spiral fake：一阶集总电感单端口（L 闭式 + SRF 并联谐振）。

    **未标定注记（如实）**：本模型为「几何 → core/nfc_coil Mohan
    current_sheet 闭式 L → core/calc_families.spiral_inductor 匝间寄生
    C_par 一阶估计 → 并联寄生谐振」的电路级一阶裁判，未对标任何真机/
    全波引擎（octagonal_spiral 真机对拍留登记 内部证据档）。
    仅作优化环闭环裁判面，不作为引擎偏差裁判；趋肤/邻近损耗为一阶
    R_dc 档（未标定），衬底涡流/地平面镜像不在模型内（如实声明）。

    电路模型：Zin(ω)=(R_dc+jωL)/(1−ω²LC_par+jωR_dc·C_par)——串联 RL
    支路与绕组匝间寄生 C_par 并联；SRF=1/(2π√(L·C_par)) 处 |Zin| 峰
    （并联谐振），S11=(Zin−z0)/(Zin+z0)。参数变化有真实响应：n/din/
    w/s 变 → L 与 C_par 同变 → 低频阻抗与 SRF 双移。

    L 单源=core/nfc_coil.spiral_inductance("octagon","current_sheet")
    （d_out=d_in+2nW+2(n−1)S 闭式导出，CALC 键 octagonal_spiral_
    inductance 同语义 #154）；R_dc=coil_track_dc_resistance（t_um 厚金
    档）；C_par=winding_parasitic_capacitance_f（平行板匝间一阶，
    uncalibrated）。
    """
    import math

    import numpy as np

    from rfauto.core.nfc_coil import (
        CoilGeometry,
        coil_track_dc_resistance,
        spiral_inductance,
        winding_parasitic_capacitance_f,
    )

    n = float(n_turns)
    din_m = float(din_um) * 1e-6
    w_m = float(w_um) * 1e-6
    s_m = float(s_um) * 1e-6
    if not (n >= 1.0):
        raise ValueError(f"_octagonal_spiral_sparams: n_turns 须 ≥1，收到 {n_turns!r}")
    for name, v in (("din_um", din_m), ("w_um", w_m), ("s_um", s_m)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(
                f"_octagonal_spiral_sparams: {name} 须为正有限，收到 {v!r}")
    d_out_m = din_m + 2.0 * n * w_m + 2.0 * (n - 1.0) * s_m
    geom = CoilGeometry("octagon", n, d_out_m, w_m, s_m)
    geom.validate()
    l_h = spiral_inductance(geom, "current_sheet")
    r_dc = coil_track_dc_resistance(
        geom, float(t_um) * 1e-6,
        resistivity_ohm_m=2.44e-8)   # 金（IPD 厚金档，CALC 缺省同源）
    c_par = winding_parasitic_capacitance_f(geom, float(t_um) * 1e-6,
                                            float(er))
    freqs = np.asarray(freq_ghz, dtype=float) * 1e9
    out = np.empty((freqs.size, 1, 1), dtype=complex)   # (nf, nports, nports)
    for i, f_hz in enumerate(freqs):
        omega = 2.0 * math.pi * f_hz
        denom = 1.0 - omega * omega * l_h * c_par \
            + 1j * omega * r_dc * c_par
        z_in = complex(r_dc, omega * l_h) / denom
        out[i, 0, 0] = (z_in - complex(z0)) / (z_in + complex(z0))
    return out
