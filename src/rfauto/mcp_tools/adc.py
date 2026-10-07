"""adc_interleave_spurs/jitter_budget_snr（ADC 交错杂散 + JESD204C 抖动预算薄壳）。

W7 台账①态接线批 X3（2026-10-04）：零逻辑转发 adc_budget_service（同域
ADC 噪声预算面扩口，零消费内核 core/interleave_spurs 的查询面）。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp


@mcp.tool()
def adc_interleave_spurs(
    fs_mhz: float, fin_mhz: float, n_lanes: int, n_orders: int = 4
) -> dict[str, Any]:
    """ADC 交错杂散表（adc 域）：fs/fin/路数 → 失配杂散清单（折叠第一奈区）。

    只读无副作用；杂散频率出自闭式 f=|k·fs/M±fin| 枚举，不用于杂散幅度
    预测（无幅度模型）。非法入参 → ok=False + errors 如实。只读无时序约束。

    Args:
        fs_mhz: 采样率 MHz（>0）
        fin_mhz: 输入频率 MHz（>0，须 < fs/2 第一奈奎斯特区内）
        n_lanes: 交错路数 M（≥2 整数）
        n_orders: 谐波阶上限（± 侧，缺省 4）

    Returns:
        {ok, schema_version, result: {fs_hz, fin_hz, n_lanes, nyquist_hz,
        spurs: [{freq_hz, raw_hz, k, sign, label}], n_spurs}, provenance}；
        非法入参 → ok=False + errors 列表（不抛异常）。
    """
    from rfauto.service.adc_budget_service import interleave_spur_table_compute
    return interleave_spur_table_compute({
        "fs_hz": fs_mhz * 1e6,
        "fin_hz": fin_mhz * 1e6,
        "n_lanes": n_lanes,
        "n_orders": n_orders,
    })


@mcp.tool()
def jitter_budget_snr(
    rj_rms_ui: float, dj_ui: float, ber: float = 1e-12
) -> dict[str, Any]:
    """抖动预算 SNR（adc 域）：RJ/DJ/BER → TJ 与等效 SNR（UI 域闭式）。

    只读无副作用；TJ=Q(BER)·RJ+DJ 闭式对照面，不用于实测抖动分解。
    非法入参 → ok=False + errors 如实。只读无时序约束。

    Args:
        rj_rms_ui: 随机抖动 RJ rms（UI，≥0）
        dj_ui: 确定性抖动 DJ（UI，≥0）
        ber: 目标误码率（<0.5，缺省 1e-12）

    Returns:
        {ok, schema_version, result: {q_factor, tj_ui, snr_db, ber,
        rj_rms_ui, dj_ui}, provenance}；非法入参 → ok=False + errors。
    """
    from rfauto.service.adc_budget_service import jitter_budget_compute
    return jitter_budget_compute({
        "rj_rms_ui": rj_rms_ui,
        "dj_ui": dj_ui,
        "ber": ber,
    })
