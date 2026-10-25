"""CTLE 连续时间线性均衡器独立面（aurora_g W4-S4 席，R2 边际池点名件）。

出处（通用连续时间搁架均衡器零极点代数；无 802.3 规格表依赖——规格
常数不进键面，详见下节物理口径）：
- ctle_nyquist_gain/ctle_gain_at：1 零 2 极传输函数 H(f)=g(1+jf/f_z)/
  [(1+jf/f_p1)(1+jf/f_p2)] 的闭式评估（通用零极点代数，第一性推导；
  802.3 COM CTLE 每级拓扑同构见 pychopmarg/com_pam4 消费面）。
- ctle_pole_from_boost：目标 Nyquist 增益反解主极点（同构代数反解；
  achievability 区间由域盒自然导出）。

三键：ctle_nyquist_gain（1 零 2 极 CTLE 的 Nyquist 增益/内禀峰值闭式）/
ctle_pole_from_boost（由目标 Nyquist 增益反解主极点——独立综合档）/
ctle_gain_at（任意频点复增益评估：幅度 dB+相位）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``\\bctle\\b`` 命中仅 com_pam4.py（pychopmarg COM 包裹：g_DC/g_DC2 档
直积扫描——规格档位**消费**面）与 si_channel_service（COM 流程注记）：
**独立零极点闭式评估/综合键面零**（R2_core_tier4 §② 方向 4 判据原文
"独立 CTLE 双二阶零极点→Nyquist 峰值增益闭式综合零命中"复跑同判）。
si_channel.eye_metrics=眼图统计面、jitter_budget=抖动面、gd_equalizer=
微波全通群时延面、com_pam4=COM 规格包裹面——均无零极点传输函数闭式
键位。本族=纯零极点代数（通用连续时间搁架均衡器数学，无 802.3 规格表
依赖——R2"数据源薄"风险经口径选择消解：只做传输函数代数与反解，不做
规格档位产生）。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
CTLE 一阶形态（1 零 + 2 极 + 直流增益；802.3 COM 的 CTLE 每级拓扑
同构，本族按**通用零极点代数**实现，规格常数不进键面）：

    H(f) = g·(1 + j·f/f_z) / [(1 + j·f/f_p1)(1 + j·f/f_p2)]
    |H(f)|² = g²·(1+(f/f_z)²) / [(1+(f/f_p1)²)(1+(f/f_p2)²)]

域约定：0 < f_z ≤ f_p1 ≤ f_p2（boost CTLE：零在极点前）；f_p2 缺省
None = 单极档（1 零 1 极，增益单调升至渐近台 g·f_p1/f_z，无内禀峰）。

- 内禀峰值（双极档，|H|² 对 u=f² 求导：1/(u+z²) = 1/(u+p1²)+1/(u+p2²)
  → u² + 2z²u + z²(p1²+p2²) − p1²p2² = 0）：

      u* = √((p1²−z²)(p2²−z²)) − z²，f_peak = √(u*)

  u* > 0 才有内禀峰（z 深低于 p1 时成立）；u* ≤ 0 → 单调降，峰值=DC。
  重极对退化：p1=p2=p → u* = p²−2z² → f_peak = √(p²−2z²)（闭式 p1=p2
  代入档，逐位锚；真 1 零 1 极无内禀峰——增益单调升至渐近台）。
- 反解主极点（给定目标 |H(f_nyq)| = b）：

      1+(f/p1)² = (1+(f/z)²)·g² / (b²·K)，K = 1（单极）或 1+(f/p2)²
      f_p1 = f / √(RHS − 1)

  RHS ≤ 1 → 目标超过纯零点增益上限（极点须为虚数）显式 ValueError；
  解得 f_p1 < f_z → 目标低于 boost 域下限（需切割拓扑）显式 ValueError
  （achievability 区间 [g/√K, g·√((1+(f/z)²)/K)] 由域盒自然导出）。

边界防撞（#222 triple-grep，2026-10-19 实测）
--------------------------------------------------------
- com_pam4=COM 规格包裹（pychopmarg 数值权威，g_DC 档位扫描——本族不
  做 COM 语义、不产生规格档位）；si_channel.preemphasis_taps=Tx FFE
  时域抽头面（本族=Rx CTLE 频域零极点面）；gd_equalizer=群时延全通
  （幅度平坦，本族=幅度搁架）；stepped_impedance/coupled_line_bpf=
  微波滤波器面不撞。

数值锚（#118 独立来源；锚树 tests/unit/test_w4s4_core_margin.py）
--------------------------------------------------------
- |H(0)| = g 逐位、相位 0 逐位；单极档 p1=p2=p：f_peak=√(p²−z²) 独立
  算术逐位；
- roundtrip：pole_from_boost(boost) → f_p1 回灌 nyquist_gain/gain_at
  复现 boost（<1e-9 相对）；
- 一致性：gain_at(f_nyq) 与 nyquist_gain 同参同值（<1e-12）；
- 守卫族：f_z>f_p1、非正频率、RHS≤1（超上限）、f_p1<f_z（低于下限）
  显式拒绝。
"""

from __future__ import annotations

import cmath
import math

from .registry import register_calculator


def _ctle_terms(
    f_z_hz: float,
    f_p1_hz: float,
    f_p2_hz: float | None,
    g_dc: float,
    key: str,
) -> tuple[float, float, float | None, float]:
    z = float(f_z_hz)
    p1 = float(f_p1_hz)
    g = float(g_dc)
    for name, v in (("f_z_hz", z), ("f_p1_hz", p1)):
        if not v > 0.0:
            raise ValueError(f"{key}: {name} 必须 >0，得 {v!r}")
    if not g > 0.0:
        raise ValueError(f"{key}: g_dc 必须 >0，得 {g_dc!r}")
    if p1 < z:
        raise ValueError(
            f"{key}: 要求 f_z ≤ f_p1（boost CTLE 零在极点前），得 "
            f"z={z}/p1={p1}")
    p2: float | None = None
    if f_p2_hz is not None:
        p2 = float(f_p2_hz)
        if not p2 > 0.0:
            raise ValueError(f"{key}: f_p2_hz 必须 >0 或 None，得 {f_p2_hz!r}")
        if p2 < p1:
            raise ValueError(
                f"{key}: 要求 f_p1 ≤ f_p2，得 p1={p1}/p2={p2}")
    return z, p1, p2, g


def _ctle_h(z: float, p1: float, p2: float | None, g: float,
            f: float) -> complex:
    """复增益 H(f)（纯零极点代数单源；p2=None 即单极档）。"""
    h = g * (1.0 + 1j * f / z) / (1.0 + 1j * f / p1)
    if p2 is not None:
        h /= 1.0 + 1j * f / p2
    return h


@register_calculator(
    "ctle_nyquist_gain",
    "CTLE Nyquist增益：1 零 2 极连续时间搁架均衡器闭式评估（通用零极点"
    "代数，802.3 COM CTLE 每级拓扑同构、规格常数不进键面）：H=g(1+jf/"
    "f_z)/[(1+jf/f_p1)(1+jf/f_p2)]，输出 Nyquist 增益 dB/DC 增益/内禀"
    "峰值频率与增益（u*=√((p1²−z²)(p2²−z²))−z²、f_peak=√u*；u*≤0 无内"
    "禀峰记峰值=DC；f_p2=None 单极档增益单调升至台 g·f_p1/f_z）。域："
    "0<f_z≤f_p1≤f_p2",
    (("f_z_hz", "float Hz 零点频率（>0）"),
     ("f_p1_hz", "float Hz 主极点频率（≥f_z）"),
     ("f_p2_hz", "float Hz 次极点频率（≥f_p1；None=单极档）"),
     ("g_dc", "float - 直流增益（线性，>0，缺省 1.0）"),
     ("f_nyq_hz", "float Hz Nyquist 频率（>0）")),
    required=("f_z_hz", "f_p1_hz", "f_nyq_hz"),
)
def ctle_nyquist_gain(f_z_hz: float, f_p1_hz: float, f_nyq_hz: float,
                      f_p2_hz: float | None = None,
                      g_dc: float = 1.0) -> dict:
    key = "ctle_nyquist_gain"
    z, p1, p2, g = _ctle_terms(f_z_hz, f_p1_hz, f_p2_hz, g_dc, key)
    fnyq = float(f_nyq_hz)
    if not fnyq > 0.0:
        raise ValueError(f"{key}: f_nyq_hz 必须 >0，得 {f_nyq_hz!r}")
    h_nyq = _ctle_h(z, p1, p2, g, fnyq)
    if p2 is None:
        f_peak: float | None = None
        peak_db = 20.0 * math.log10(g * p1 / z)
        peak_note = "single_pole_plateau"
    else:
        u = math.sqrt((p1 * p1 - z * z) * (p2 * p2 - z * z)) - z * z
        if u > 0.0:
            f_peak = math.sqrt(u)
            peak_db = 20.0 * math.log10(abs(_ctle_h(z, p1, p2, g, f_peak)))
            peak_note = "interior_peak"
        else:
            f_peak = None
            peak_db = 20.0 * math.log10(g)
            peak_note = "dc_peak_monotone_decreasing"
    return {
        "gain_nyquist_db": 20.0 * math.log10(abs(h_nyq)),
        "gain_dc_db": 20.0 * math.log10(g),
        "boost_db": 20.0 * math.log10(abs(h_nyq)) - 20.0 * math.log10(g),
        "peak_gain_db": peak_db,
        "f_peak_hz": f_peak,
        "peak_note": peak_note,
        "f_z_hz": z,
        "f_p1_hz": p1,
        "f_p2_hz": p2,
        "g_dc": g,
        "f_nyq_hz": fnyq,
    }


@register_calculator(
    "ctle_pole_from_boost",
    "CTLE极点反解：由目标 Nyquist 增益反解主极点 f_p1（独立综合档，通用 "
    "零极点代数反解）：1+(f/f_p1)²=(1+(f/f_z)²)·g²/(b²·K) → f_p1=f/√("
    "RHS−1)，K=1（单极）或 1+(f/f_p2)²。RHS≤1（目标超纯零点增益上限）/"
    "解得 f_p1<f_z（低于 boost 域下限）显式拒绝。roundtrip 锚：回灌 "
    "ctle_nyquist_gain 复现目标 boost",
    (("boost_db", "float dB 目标 Nyquist 增益 |H(f_nyq)|（有限值）"),
     ("f_z_hz", "float Hz 零点频率（>0）"),
     ("f_nyq_hz", "float Hz Nyquist 频率（>0）"),
     ("f_p2_hz", "float Hz 次极点频率（≥解得 f_p1；None=单极档）"),
     ("g_dc", "float - 直流增益（线性，>0，缺省 1.0）")),
    required=("boost_db", "f_z_hz", "f_nyq_hz"),
)
def ctle_pole_from_boost(boost_db: float, f_z_hz: float, f_nyq_hz: float,
                         f_p2_hz: float | None = None,
                         g_dc: float = 1.0) -> dict:
    key = "ctle_pole_from_boost"
    b_db = float(boost_db)
    if b_db != b_db or b_db in (float("inf"), float("-inf")):
        raise ValueError(f"{key}: boost_db 必须有限，得 {boost_db!r}")
    z, _p1_ignored, p2, g = _ctle_terms(f_z_hz, f_z_hz, f_p2_hz, g_dc, key)
    fnyq = float(f_nyq_hz)
    if not fnyq > 0.0:
        raise ValueError(f"{key}: f_nyq_hz 必须 >0，得 {f_nyq_hz!r}")
    b = 10.0 ** (b_db / 20.0)
    k = 1.0 if p2 is None else 1.0 + (fnyq / p2) ** 2
    rhs = (1.0 + (fnyq / z) ** 2) * g * g / (b * b * k)
    if rhs <= 1.0:
        raise ValueError(
            f"{key}: 目标 boost 超过纯零点增益上限（f_p1→∞ 亦不可达），"
            f"得 boost={b_db}dB/上限="
            f"{20.0 * math.log10(g * math.sqrt(1.0 + (fnyq / z) ** 2) / math.sqrt(k)):.6f}dB")
    fp1 = fnyq / math.sqrt(rhs - 1.0)
    if fp1 < z:
        raise ValueError(
            f"{key}: 目标 boost 低于 boost 域下限（需 f_p1<f_z 切割拓扑，"
            f"域外），得 f_p1={fp1}/f_z={z}")
    if p2 is not None and fp1 > p2:
        raise ValueError(
            f"{key}: 解得 f_p1 > f_p2（域要求 f_p1 ≤ f_p2），得 "
            f"p1={fp1}/p2={p2}")
    return {
        "f_p1_hz": fp1,
        "boost_db": b_db,
        "f_z_hz": z,
        "f_p2_hz": p2,
        "g_dc": g,
        "f_nyq_hz": fnyq,
    }


@register_calculator(
    "ctle_gain_at",
    "CTLE频点增益：任意频点复增益评估（幅度 dB+相位 °，通用零极点代数）："
    "H=g(1+jf/f_z)/[(1+jf/f_p1)(1+jf/f_p2)]、∠H=atan(f/f_z)−atan(f/"
    "f_p1)−atan(f/f_p2)（单极档无末项）。f=0 → |H|=g/相位 0 逐位；与 "
    "ctle_nyquist_gain 同参一致性锚",
    (("f_z_hz", "float Hz 零点频率（>0）"),
     ("f_p1_hz", "float Hz 主极点频率（≥f_z）"),
     ("f_hz", "float Hz 评估频率（>0）"),
     ("f_p2_hz", "float Hz 次极点频率（≥f_p1；None=单极档）"),
     ("g_dc", "float - 直流增益（线性，>0，缺省 1.0）")),
    required=("f_z_hz", "f_p1_hz", "f_hz"),
)
def ctle_gain_at(f_z_hz: float, f_p1_hz: float, f_hz: float,
                 f_p2_hz: float | None = None,
                 g_dc: float = 1.0) -> dict:
    key = "ctle_gain_at"
    z, p1, p2, g = _ctle_terms(f_z_hz, f_p1_hz, f_p2_hz, g_dc, key)
    f = float(f_hz)
    if not f > 0.0:
        raise ValueError(f"{key}: f_hz 必须 >0，得 {f_hz!r}")
    h = _ctle_h(z, p1, p2, g, f)
    phase_rad = (cmath.phase(1.0 + 1j * f / z)
                 - cmath.phase(1.0 + 1j * f / p1))
    if p2 is not None:
        phase_rad -= cmath.phase(1.0 + 1j * f / p2)
    return {
        "gain_db": 20.0 * math.log10(abs(h)),
        "phase_deg": math.degrees(phase_rad),
        "gain_linear": abs(h),
        "f_hz": f,
        "f_z_hz": z,
        "f_p1_hz": p1,
        "f_p2_hz": p2,
        "g_dc": g,
    }
