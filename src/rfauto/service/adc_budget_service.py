"""F-E.1 ADC 噪声预算 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

只包 core/adc_budget.py 内核（零物理公式，全部数字出自确定性内核，规则 7）：
payload 可选字段 f_in_hz/sigma_jitter_s/n_bits/drive_fraction_k/t_kelvin/
capacitance_f/v_fs_rms → adc_noise_budget → ok 信封。字段错误收集进 errors
不抛异常（_err 信封模式同 aging_service）；内核 ValueError（成对/成组约束、
数值域）同样转 ok=False。

W7 台账①态接线扩面（2026-10-04，零消费内核 interleave_spurs）：
- ``interleave_spur_table_compute``：M 路时间交错 ADC 失配杂散表
  （core/interleave_spurs.interleave_spur_table 薄消费）；
- ``jitter_budget_compute``：JESD204C 确定性抖动预算 TJ=Q(BER)·RJ+DJ →
  等效 SNR（core/interleave_spurs.total_jitter_snr 薄消费）。
两函数同 _err 信封纪律：payload 非对象/字段非法/内核 ValueError 全进
errors 不抛异常；service 层零物理公式（规则 7，数值只在内核）。

字段语义（与内核一致）：
- 缺键或 JSON null = 不计该源（f_in_hz 与 sigma_jitter_s 成对、kT/C 三字段
  成组，缺伴字段由内核转 ok=False）；
- drive_fraction_k 缺省/null → 1.0（无修正项）；
- sigma_jitter_s = 0.0 合法（无抖动极限，result.snr_jitter_db = +inf 原样
  透传——严格 JSON 消费方应传 null；ok 信封内非有限浮点仅此退化档）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import adc_budget, interleave_spurs
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
ADC_BUDGET_SERVICE_SCHEMA_VERSION = "1.0"

#: 内核法源（provenance 透出，字符串常量避免每次拼接）
_PROVENANCE_SOURCES = (
    "ADI MT-001 (quantization SNR 6.02N+1.76) / MT-007 (aperture jitter SNR)"
)

#: 交错杂散/抖动预算内核法源（W7 台账①态接线扩面）
_INTERLEAVE_PROVENANCE = {
    "kernel": "rfauto.core.interleave_spurs",
    "sources": (
        "round16 DR-10（k·fs/M±fin 交错杂散族 + JESD204C TJ=Q(BER)·RJ+DJ，"
        "Q=√2·erfcinv(2·BER) scipy 数值权威）"
    ),
}


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(list(errors))


def _opt_num(
    value: Any,
    name: str,
    errors: list[str],
    *,
    positive: bool = False,
    nonneg: bool = False,
) -> float | None:
    """可选数值字段收敛：缺键/None=不计该源；bool 拒收（df7+⑯）；错误进 errors。"""
    if value is None:
        return None
    if isinstance(value, bool):
        errors.append(f"{name} 不接受 bool（float(True)=1.0 静默污染）")
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        errors.append(f"{name} 必须是数字，实际 {value!r}")
        return None
    if not math.isfinite(val):
        errors.append(f"{name} 必须为有限数，实际 {val!r}")
        return None
    if positive and val <= 0.0:
        errors.append(f"{name} 必须 >0，实际 {val!r}")
        return None
    if nonneg and val < 0.0:
        errors.append(f"{name} 必须 >=0，实际 {val!r}")
        return None
    return val


def adc_budget_compute(payload: Any) -> dict[str, Any]:
    """ADC 噪声预算：payload（JSON 对象）→ ok 信封 + to_dict() 结果。

    成功：{"ok": True, "schema_version", "result"（AdcNoiseBudgetResult.
    to_dict()）, "provenance"}。失败：{"ok": False, "errors": [str, ...]}，
    不抛异常（payload 非对象/字段非法/内核 ValueError 全走信封）。
    """
    if not isinstance(payload, dict):
        return _err([f"payload 必须是 JSON 对象，实际 {type(payload).__name__}"])
    errors: list[str] = []
    f_in_hz = _opt_num(payload.get("f_in_hz"), "f_in_hz", errors, positive=True)
    sigma_jitter_s = _opt_num(
        payload.get("sigma_jitter_s"), "sigma_jitter_s", errors, nonneg=True
    )
    n_bits = _opt_num(payload.get("n_bits"), "n_bits", errors)
    drive_k = _opt_num(
        payload.get("drive_fraction_k"), "drive_fraction_k", errors, positive=True
    )
    t_kelvin = _opt_num(payload.get("t_kelvin"), "t_kelvin", errors, positive=True)
    capacitance_f = _opt_num(
        payload.get("capacitance_f"), "capacitance_f", errors, positive=True
    )
    v_fs_rms = _opt_num(payload.get("v_fs_rms"), "v_fs_rms", errors, positive=True)
    if errors:
        return _err(errors)
    try:
        result = adc_budget.adc_noise_budget(
            f_in_hz=f_in_hz,
            sigma_jitter_s=sigma_jitter_s,
            n_bits=n_bits,
            drive_fraction_k=1.0 if drive_k is None else drive_k,
            t_kelvin=t_kelvin,
            capacitance_f=capacitance_f,
            v_fs_rms=v_fs_rms,
        )
    except ValueError as exc:
        return _err([str(exc)])
    return ok_envelope(
        schema_version=ADC_BUDGET_SERVICE_SCHEMA_VERSION,
        result=result.to_dict(),
        provenance={
            "kernel": "rfauto.core.adc_budget",
            "sources": _PROVENANCE_SOURCES,
        },
    )


def _req_num(
    value: Any,
    name: str,
    errors: list[str],
    *,
    positive: bool = False,
    nonneg: bool = False,
) -> float | None:
    """必填数值字段收敛：缺键/None=契约错误；bool 拒收（df7+⑯）；错误进 errors。"""
    if value is None:
        errors.append(f"{name} 必填（缺键或 null）")
        return None
    return _opt_num(value, name, errors, positive=positive, nonneg=nonneg)


def interleave_spur_table_compute(payload: Any) -> dict[str, Any]:
    """M 路交错 ADC 失配杂散表：payload（JSON 对象）→ ok 信封 + 杂散行列表。

    payload 字段：fs_hz（采样率 Sa/s，必填 >0）、fin_hz（输入频率 Hz，
    必填 >0 且 <fs/2）、n_lanes（交错路数 M，必填 ≥2 整数）、n_orders
    （谐波阶上限，可选缺省 4）。杂散 f=|k·fs/M±fin| 折叠进第一奈奎斯特区，
    按频率升序；字段语义全在内核（core/interleave_spurs），本函数零公式。

    成功：{"ok": True, "schema_version", "result", "provenance"}；
    失败：{"ok": False, "errors": [str, ...]}，不抛异常。
    """
    if not isinstance(payload, dict):
        return _err([f"payload 必须是 JSON 对象，实际 {type(payload).__name__}"])
    errors: list[str] = []
    fs_hz = _req_num(payload.get("fs_hz"), "fs_hz", errors, positive=True)
    fin_hz = _req_num(payload.get("fin_hz"), "fin_hz", errors, positive=True)
    n_lanes_raw = payload.get("n_lanes")
    if n_lanes_raw is None:
        errors.append("n_lanes 必填（缺键或 null）")
    elif isinstance(n_lanes_raw, bool):
        errors.append("n_lanes 不接受 bool（float(True)=1.0 静默污染）")
    else:
        try:
            n_lanes_val = float(n_lanes_raw)
        except (TypeError, ValueError):
            n_lanes_val = None
            errors.append(f"n_lanes 必须是数字，实际 {n_lanes_raw!r}")
    n_orders = payload.get("n_orders")
    if n_orders is None:
        n_orders_val: int | None = None
    elif isinstance(n_orders, bool) or not isinstance(n_orders, int):
        errors.append(f"n_orders 必须是整数，实际 {n_orders!r}")
        n_orders_val = None
    else:
        n_orders_val = int(n_orders)
    if errors:
        return _err(errors)
    try:
        result = interleave_spurs.interleave_spur_table(
            fs_hz, fin_hz, n_lanes_val, n_orders=4 if n_orders_val is None else n_orders_val
        )
    except ValueError as exc:
        return _err([str(exc)])
    return ok_envelope(
        schema_version=ADC_BUDGET_SERVICE_SCHEMA_VERSION,
        result=result,
        provenance=dict(_INTERLEAVE_PROVENANCE),
    )


def jitter_budget_compute(payload: Any) -> dict[str, Any]:
    """JESD204C 确定性抖动预算：payload（JSON 对象）→ ok 信封 + TJ/SNR。

    payload 字段：rj_rms_ui（RJ rms，UI 域，必填 ≥0）、dj_ui（DJ，UI 域，
    必填 ≥0）、ber（可选缺省 1e-12，须 <0.5）。TJ=Q(BER)·RJ+DJ（204C 一致性
    口径闭式），等效 SNR=20log10(1/(2·TJ))；公式全在内核，本函数零计算。

    成功：{"ok": True, "schema_version", "result", "provenance"}；
    失败：{"ok": False, "errors": [str, ...]}，不抛异常。
    """
    if not isinstance(payload, dict):
        return _err([f"payload 必须是 JSON 对象，实际 {type(payload).__name__}"])
    errors: list[str] = []
    rj_ui = _req_num(payload.get("rj_rms_ui"), "rj_rms_ui", errors, nonneg=True)
    dj_ui = _req_num(payload.get("dj_ui"), "dj_ui", errors, nonneg=True)
    ber = payload.get("ber")
    ber_val = None if ber is None else _opt_num(ber, "ber", errors, positive=True)
    if errors:
        return _err(errors)
    try:
        result = interleave_spurs.total_jitter_snr(
            rj_ui, dj_ui, 1e-12 if ber_val is None else ber_val
        )
    except ValueError as exc:
        return _err([str(exc)])
    return ok_envelope(
        schema_version=ADC_BUDGET_SERVICE_SCHEMA_VERSION,
        result=result,
        provenance=dict(_INTERLEAVE_PROVENANCE),
    )
