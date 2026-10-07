"""F-H 件 3 振动/冲击 SRS service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/vibration_srs.py 内核（本服务零物理公式，全部数字出自确定性
内核，规则 7）。两入口：

- :func:`vibration_srs_report`：Miles 随机振动 + 半正弦冲击 SRS（闭式/
  数值/渐近三路径摘要）+ 振动→频移/相噪边带 组合报告（各段可选）；
- :func:`g_sensitivity_query`：器件族 g-灵敏度查表（UNVERIFIED 如实
  透传，不构成器件背书）。

诚实边界（透传内核 docstring）：g-灵敏度表全部 UNVERIFIED 单源/工程
量级；Miles/SRS 为单自由度单模上界工具（板级多模需 Elmer 特征值真跑
面，本服务不做）；边带换算限小指数 FM（Δφ>0.5 内核显式拒绝）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core import vibration_srs as vsrs
from rfauto.service.envelope import ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
VIBRATION_SRS_SERVICE_SCHEMA_VERSION = "1.0"

_PROVENANCE = {
    "miles": "J.W. Miles (1954) + Sandia 随机振动教程（round4 来源 [13]）；PSD 单边 g²/Hz 口径",
    "half_sine_srs": "单自由度冲击谱分段解析（Tuma 收录，round4 [13]）+ Duhamel 数值路径（本仓独立实现）",
    "g_sensitivity": "round4 来源 [14]（mwrf/NIST/White Rose）；全表 UNVERIFIED 单源/工程量级",
    "sideband": "小指数 FM 推导（NIST 振动相噪口径，round4 [14]）；有效域 Δφ≤0.5 rad",
}


def g_sensitivity_query(family: str) -> dict[str, Any]:
    """器件族 g-灵敏度查表（JSON 进出；UNVERIFIED 标记透传）。"""
    entry = vsrs.g_sensitivity_lookup(family)
    return ok_envelope(
        schema_version=VIBRATION_SRS_SERVICE_SCHEMA_VERSION,
        entry=entry.to_dict(),
        provenance={"g_sensitivity": _PROVENANCE["g_sensitivity"]},
        disclaimer="UNVERIFIED 单源/工程量级锚，消费前须按器件实测复核",
    )


def vibration_srs_report(
    f_n_hz: float,
    q: float,
    psd_g2_hz: float,
    *,
    pulse_a_g: float | None = None,
    pulse_t_s: float | None = None,
    srs_q: float | None = None,
    f0_hz: float | None = None,
    gamma_family: str | None = None,
    gamma_per_g: float | None = None,
    vib_a_g: float | None = None,
    vib_f_v_hz: float | None = None,
) -> dict[str, Any]:
    """振动/冲击组合报告（各段可选，缺省只出 Miles 段）。

    - Miles 段（必出）：f_n/Q/W(f_n) → G_rms、3σ 界、谐振位移 RMS；
    - 半正弦 SRS 段（pulse_a_g+pulse_t_s 给定时）：闭式（无阻尼）、
      数值（srs_q，缺省复用 Miles 的 q）、渐近 regime 三路径摘要；
    - 边带段（f0_hz+γ（族名或显值）+vib_a_g+vib_f_v_hz 给定时）：
      Δf 与 L(f_v)（小指数有效域由内核守卫）。
    """
    miles = vsrs.miles_response(f_n_hz, q, psd_g2_hz)
    report: dict[str, Any] = ok_envelope(
        schema_version=VIBRATION_SRS_SERVICE_SCHEMA_VERSION,
        miles=miles.to_dict(),
        half_sine_srs=None,
        sideband=None,
        provenance=dict(_PROVENANCE),
        disclaimer="单自由度单模上界工具（板级多模需模态叠加/特征值真跑面）；"
            "g-灵敏度 UNVERIFIED 单源/工程量级，非认证数据",
    )

    if pulse_a_g is not None and pulse_t_s is not None:
        q_eff = miles.q if srs_q is None else srs_q
        exact = vsrs.srs_half_sine_exact_undamped(f_n_hz, pulse_a_g, pulse_t_s)
        numeric = vsrs.srs_half_sine_numerical(f_n_hz, pulse_a_g, pulse_t_s, q=q_eff)
        asymptotic = vsrs.srs_half_sine_asymptotic(pulse_a_g, pulse_t_s, f_n_hz)
        report["half_sine_srs"] = {
            "pulse_a_g": pulse_a_g,
            "pulse_t_s": pulse_t_s,
            "alpha": exact.alpha,
            "closed_form_undamped": exact.to_dict(),
            "numerical_damped": numeric.to_dict(),
            "asymptotic_regime": asymptotic["regime"],
            "asymptotic_amplification": asymptotic["amplification"],
            "asymptotic_note": asymptotic["note"],
        }

    if f0_hz is not None and vib_a_g is not None and vib_f_v_hz is not None:
        gamma_value = (
            vsrs.g_sensitivity_lookup(gamma_family).gamma_per_g
            if gamma_family is not None
            else gamma_per_g
        )
        if gamma_value is None:
            raise ValueError("gamma_family 与 gamma_per_g 必须二选一提供")
        df = vsrs.freq_shift_hz(f0_hz, gamma_value, vib_a_g)
        l_dbc = vsrs.vibration_sideband_dbc(f0_hz, gamma_value, vib_a_g, vib_f_v_hz)
        report["sideband"] = {
            "f0_hz": f0_hz,
            "gamma_per_g": gamma_value,
            "gamma_source_family": gamma_family,
            "vib_a_g": vib_a_g,
            "vib_f_v_hz": vib_f_v_hz,
            "delta_f_hz": df,
            "sideband_dbc_hz": l_dbc,
        }

    return report
