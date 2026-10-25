"""振荡器相位噪声 Leeson 模型 CALC 键（aurora_l G1，2026-10-23）。

一键：leeson_phase_noise（Leeson 1966 线性时不变谐振器相噪模型：给定
载波频率/有载 Q/闪烁角/噪声系数/载波功率 → 单边带相位噪声 L(f_m)
dBc/Hz；#222 triple-grep 证据：``leeson`` src/tests 三面零命中，
phase_noise_evm=相噪→EVM 消费面（MT-4 口径），振荡器相噪**产生面**
（L(f_m) 谱形）独立键面空白）。

物理口径（#1c/#300 出处纪律；docstring 写死）
--------------------------------------------------------
- Leeson 单边带相位噪声谱（D. B. Leeson, "A Simple Model of Feedback
  Oscillator Noise Spectrum", Proc. IEEE 54(2):329-330, 1966；Pozar
  《Microwave Engineering》§10 振荡器噪声同族通行形态）：

      L(f_m) = [F·k·T / (2·Ps)] · (1 + f_c/f_m) · (1 + (f0/(2·Q_L·f_m))²)

  三个因子：热噪地板 FkT/(2Ps)（SSB 口径含 1/2）、闪烁角 f_c 以下
  +10dB/dec（1+f_c/f_m 项）、谐振器半功率点 f0/(2Q_L) 以下 +20dB/dec
  （1+(f0/(2Q_L f_m))² 项——高 Q 谐振器把白噪声折带到近载波）。
- 频段结构（测试钉）：f_m≫f0/2Q_L 且 f_m≫f_c → 平地板=kT/(2Ps)+NF
  （NF=0、Ps=0dBm → −176.985 dBc/Hz=10lg(kT290/(2mW)，经典 −174+3
  口径）；半功率点 f_m=f0/2Q_L → 谐振项恰 +3.01dB；f_c/f_m 主导区
  flicker 10×→+10dB；谐振区 decade→+20dB/dec。
- 精度类：**半经验**（Leeson 模型为线性近似，F/Q_L/f_c 依赖实测或
  经验取值；模型对 VCO 推压/幅度-相位转换等效应不覆盖——如实声明）。

守卫：f_offset_hz>0；f0_hz>0；q_loaded>0；f_flicker_hz≥0；nf_db 有限
（≥0 允许 0=理想无噪）；p_carrier_dbm 有限任意（Ps=10^(dBm/10) mW）；
t_kelvin>0；bool 入参显式拒收（df7+⑯）。

接口：纯函数零 IO；math 为主；无 ``__all__``（公开 API 快照口径）。

出处：
- leeson_phase_noise：反馈振荡器噪声谱线性模型（Leeson 1966 Proc.
  IEEE 54(2):329-330 原始文献；Pozar Microwave Engineering §10 振荡
  器噪声节同族通行形态，章节级转引）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

_K_BOLTZMANN = 1.380649e-23  # J/K（SI 定义值）


@register_calculator(
    "leeson_phase_noise",
    "振荡器相位噪声 Leeson 模型：L(f_m)=[F·kT/(2Ps)]·"
    "(1+f_c/f_m)·(1+(f0/(2Q_L f_m))²) dBc/Hz——热噪地板（NF=0/Ps=0dBm →"
    " −176.985=−174+3 经典口径）+闪烁角以下 +10dB/dec+谐振器半功率点 "
    "f0/2Q_L 以下 +20dB/dec；输出地板/半功率点/flicker 角三特征频率与"
    "所在频段标注。半经验模型如实声明（F/Q_L/f_c 依赖实测）。相噪→EVM"
    "消费面=phase_noise_evm 不撞",
    (("f_offset_hz", "float Hz 偏移频率 f_m（>0）"),
     ("f0_hz", "float Hz 载波频率（>0）"),
     ("q_loaded", "float 谐振器有载 Q（>0）"),
     ("f_flicker_hz", "float Hz 闪烁角 f_c（≥0，缺省 0=无闪烁项）"),
     ("nf_db", "float dB 噪声系数（≥0，缺省 0=理想）"),
     ("p_carrier_dbm", "float dBm 载波功率 Ps（缺省 0=1mW）"),
     ("t_kelvin", "float K 等效噪声温度（>0，缺省 290）")),
    required=("f_offset_hz", "f0_hz", "q_loaded"),
)
def leeson_phase_noise(f_offset_hz: float, f0_hz: float, q_loaded: float,
                       f_flicker_hz: float = 0.0, nf_db: float = 0.0,
                       p_carrier_dbm: float = 0.0,
                       t_kelvin: float = 290.0) -> dict[str, Any]:
    """Leeson 相噪谱：单点偏移频率 L(f_m) + 特征频率面。"""
    tag = "leeson_phase_noise"
    f_m = _finite(f_offset_hz, f"{tag}.f_offset_hz")
    f0 = _finite(f0_hz, f"{tag}.f0_hz")
    q_l = _finite(q_loaded, f"{tag}.q_loaded")
    f_c = _finite(f_flicker_hz, f"{tag}.f_flicker_hz")
    nf = _finite(nf_db, f"{tag}.nf_db")
    p_dbm = _finite(p_carrier_dbm, f"{tag}.p_carrier_dbm")
    t_k = _finite(t_kelvin, f"{tag}.t_kelvin")
    if f_m <= 0.0:
        raise ValueError(f"{tag}: f_offset_hz 必须 >0，得到 {f_offset_hz!r}")
    if f0 <= 0.0:
        raise ValueError(f"{tag}: f0_hz 必须 >0，得到 {f0_hz!r}")
    if q_l <= 0.0:
        raise ValueError(f"{tag}: q_loaded 必须 >0，得到 {q_loaded!r}")
    if f_c < 0.0:
        raise ValueError(
            f"{tag}: f_flicker_hz 必须 ≥0，得到 {f_flicker_hz!r}")
    if nf < 0.0:
        raise ValueError(f"{tag}: nf_db 必须 ≥0，得到 {nf_db!r}")
    if t_k <= 0.0:
        raise ValueError(f"{tag}: t_kelvin 必须 >0，得到 {t_kelvin!r}")

    f_lin = 10.0 ** (nf / 10.0)
    p_s_w = 10.0 ** (p_dbm / 10.0) * 1e-3  # dBm → W
    floor = f_lin * _K_BOLTZMANN * t_k / (2.0 * p_s_w)
    flicker = 1.0 + f_c / f_m
    half_power_hz = f0 / (2.0 * q_l)
    reson = 1.0 + (half_power_hz / f_m) ** 2
    l_linear = floor * flicker * reson
    l_dbc = 10.0 * math.log10(l_linear)

    if f_m < f_c and f_m < half_power_hz:
        region = "flicker_resonance"  # −30dB/dec（f_c 与 f0/2Q_L 之下）
    elif f_m < f_c:
        region = "flicker_floor"      # −10dB/dec
    elif f_m < half_power_hz:
        region = "resonance"          # −20dB/dec
    else:
        region = "thermal_floor"      # 平地板
    return {
        "f_offset_hz": f_m,
        "f0_hz": f0,
        "q_loaded": q_l,
        "f_flicker_hz": f_c,
        "nf_db": nf,
        "p_carrier_dbm": p_dbm,
        "t_kelvin": t_k,
        "l_dbc_hz": round(l_dbc, 9),
        "floor_dbc_hz": round(10.0 * math.log10(floor), 9),
        "half_power_offset_hz": round(half_power_hz, 9),
        "flicker_factor": round(flicker, 15),
        "resonance_factor": round(reson, 15),
        "region": region,
        "note": (
            "Leeson 线性时不变谐振器相噪模型（半经验——F/Q_L/f_c 依赖实"
            "测或经验取值，VCO 推压/幅度相位转换不覆盖，如实声明）；频段"
            "结构：f_m≫max(f_c, f0/2Q_L) 平地板（NF=0、Ps=1mW、T=290K →"
            " 10lg(kT/2mW)=−176.985 dBc/Hz 经典 −174+3 口径）、f_c 与 "
            "f0/2Q_L 之下 −30dB/dec、其间各 −10/−20dB/dec；SSB 口径含 "
            "1/2 因子（FkT/(2Ps)）；相噪→EVM 积分消费面=phase_noise_evm"),
        "source": (
            "D. B. Leeson, 'A Simple Model of Feedback Oscillator Noise "
            "Spectrum', Proc. IEEE 54(2):329-330, 1966（原始文献）；"
            "Pozar Microwave Engineering §10 振荡器噪声节同族通行形态"
            "（章节级转引）"),
    }
