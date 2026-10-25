"""mim_cap / interdigital_cap fake 家族（aurora_k K12，反馈 F1）。

集总电容一阶模型（电容族首件，inductor_family K11 同款分层）：
- mim_cap：1 端口并联口径——Zin(ω)=R_s+jωL_s+1/(jωC)（串联寄生一阶：
  双极板 DC 电阻+平行板线电感 core/ipc_cap 单源），S11=(Zin−z0)/
  (Zin+z0)；SRF=Im(Zin) 过零=1/(2π√(L_s·C))（串联谐振）。
- interdigital_cap：2 端口串联口径——理想串联阻抗 Z(ω)=R_s+jωL_s+
  1/(jωC) 接双 50Ω 端口（ABCD=[1,Z;0,1] 解析 S：S11=Z/(Z+2z0)、
  S21=2z0/(Z+2z0)）；低频段 Z=2·z0·(1−S21)/S21→C=−1/(ω·Im(Z))，
  与用户 K8 Z12 去嵌提取链同口径（IDC 集总 C=去嵌后 173.5fF）。

**未标定注记（如实）**：本模型为「几何 → core/ipc_cap 闭式 C → 一阶
串联寄生 → 自洽 S 参数」的电路级一阶裁判，未对标任何真机/全波引擎
（真机对拍留登记 内部证据档）。仅作优化环闭环裁判面，不作为
引擎偏差裁判；衬底涡流/辐射损耗不在模型内（如实声明）。
"""

from __future__ import annotations

from typing import Any


def _mim_cap_sparams(freq_ghz: Any, w_um: float = 20.0, l_um: float = 20.0,
                     d_um: float = 0.2, er_diel: float = 7.5,
                     t_um: float = 3.0, z0: float = 50.0, **_: Any) -> Any:
    """mim_cap fake：1 端口并联口径（C 闭式 + 串联寄生自洽 S11）。

    电路模型：Zin(ω)=R_s+jωL_s+1/(jωC)——C=mim_capacitance_report
    平行板精确式（core/ipc_cap 单源，core/package_interconnect 复用）；
    R_s=mim_series_resistance_ohm（双板 DC 一阶）、L_s=mim_series_
    inductance_h（平行板线电感一阶）。SRF=1/(2π√(L_s·C))（串联谐振，
    Im(Zin) 过零）。参数变化有真实响应：w/l/d/er_diel 变 → C 与寄生
    同变 → 低频阻抗与 SRF 双移。
    """
    import math

    import numpy as np

    from rfauto.core.ipc_cap import (
        mim_capacitance_report,
        mim_series_inductance_h,
        mim_series_resistance_ohm,
    )

    w_m = float(w_um) * 1e-6
    l_m = float(l_um) * 1e-6
    d_m = float(d_um) * 1e-6
    for name, v in (("w_um", w_m), ("l_um", l_m), ("d_um", d_m)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"_mim_cap_sparams: {name} 须为正有限，收到 {v!r}")
    rep = mim_capacitance_report(w_m, l_m, d_m, float(er_diel))
    c_f = float(rep["c_f"])
    r_s = mim_series_resistance_ohm(w_m, l_m, float(t_um) * 1e-6, 2.44e-8)
    l_ser = mim_series_inductance_h(w_m, l_m, d_m)
    freqs = np.asarray(freq_ghz, dtype=float) * 1e9
    out = np.empty((freqs.size, 1, 1), dtype=complex)   # (nf, nports, nports)
    for i, f_hz in enumerate(freqs):
        omega = 2.0 * math.pi * f_hz
        z_in = complex(r_s, omega * l_ser) + 1.0 / (1j * omega * c_f)
        out[i, 0, 0] = (z_in - complex(z0)) / (z_in + complex(z0))
    return out


def _interdigital_cap_sparams(freq_ghz: Any, n_fingers: int = 24,
                              lf_um: float = 220.0, wf_um: float = 5.0,
                              sf_um: float = 5.0, e_tip_um: float = 15.0,
                              t_um: float = 3.0, er_sub: float = 12.9,
                              z0: float = 50.0, **_: Any) -> Any:
    """interdigital_cap fake：2 端口串联口径（C 闭式 + 串联寄生自洽）。

    电路模型：理想串联阻抗 Z(ω)=R_s+jωL_s+1/(jωC) 接双 z0 端口——
    C=interdigital_capacitance_f 侧壁 sum-of-capacitances 一阶（core/
    ipc_cap 单源，±50% 精度类如实声明）；R_s=interdigital_series_
    resistance_ohm（齿排并联+汇流排 DC 一阶）、L_s=双排齿组 Greenhouse
    并联电感一阶。S 解析（ABCD=[1,Z;0,1]）：S11=Z/(Z+2z0)、
    S21=2z0/(Z+2z0)；低频段 Z=2·z0·(1−S21)/S21→C=−1/(ω·Im(Z))（K8
    Z12 链同口径）。参数变化有真实响应：n/lf/w/s/e_tip 变 → C 与寄生
    同变 → S21 谷深/低频相位双移。
    """
    import math

    import numpy as np

    from rfauto.core.ipc_cap import (
        interdigital_bank_inductance_h,
        interdigital_capacitance_f,
        interdigital_series_resistance_ohm,
    )

    n = int(n_fingers)
    if n < 2 or n % 2 != 0:
        raise ValueError(
            f"_interdigital_cap_sparams: n_fingers 须为 ≥2 偶数，收到 {n_fingers!r}")
    lf_m = float(lf_um) * 1e-6
    wf_m = float(wf_um) * 1e-6
    sf_m = float(sf_um) * 1e-6
    e_tip_m = float(e_tip_um) * 1e-6
    for name, v in (("lf_um", lf_m), ("wf_um", wf_m), ("sf_um", sf_m)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(
                f"_interdigital_cap_sparams: {name} 须为正有限，收到 {v!r}")
    rep = interdigital_capacitance_f(n, lf_m, wf_m, sf_m,
                                     float(t_um) * 1e-6, float(er_sub),
                                     e_tip_m=e_tip_m)
    c_f = float(rep["c_f"])
    n_a = (n + 1) // 2
    n_b = n // 2
    l_ser = (interdigital_bank_inductance_h(lf_m, wf_m, sf_m,
                                            float(t_um) * 1e-6, n_a)
             + interdigital_bank_inductance_h(lf_m, wf_m, sf_m,
                                              float(t_um) * 1e-6, n_b))
    r_s = interdigital_series_resistance_ohm(
        lf_m, wf_m, float(t_um) * 1e-6, 2.44e-8, n, wf_m,
        n * (wf_m + sf_m) - sf_m)
    freqs = np.asarray(freq_ghz, dtype=float) * 1e9
    out = np.empty((freqs.size, 2, 2), dtype=complex)   # (nf, 2, 2)
    for i, f_hz in enumerate(freqs):
        omega = 2.0 * math.pi * f_hz
        z = complex(r_s, omega * l_ser) + 1.0 / (1j * omega * c_f)
        s11 = z / (z + 2.0 * complex(z0))
        s21 = 2.0 * complex(z0) / (z + 2.0 * complex(z0))
        out[i, 0, 0] = s11
        out[i, 0, 1] = s21
        out[i, 1, 0] = s21      # 互易（对称串联元）
        out[i, 1, 1] = s11
    return out
