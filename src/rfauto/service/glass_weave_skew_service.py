"""HS-1 P2：玻纤编织 skew service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/glass_weave_skew.py 内核（本服务零物理公式，全部数字出自
确定性内核，规则 7）。两入口：

- :func:`weave_style_info`：样式表查询（单样式或全表）+ MIT 参数值
  出处 provenance；
- :func:`weave_skew_estimate`：样式+方向+走线长+树脂 εr → 均匀化
  εeff 上下界 → 最坏/概率平均 skew（ps）→ zigzag 残余期望（可选 θ）
  → UI verdict（可选数据率）。

诚实边界（预声明）：本服务是闭式统计估计面——不含损耗/色散/线耦合；
er_resin 无缺省值（必须显式给，环氧典型域 ~3.0–3.8 见内核 docstring）；
全波截面验证（openEMS）是后续独立裁判。所有异常（含 payload 非对象、
内核 ValueError）收敛为 ok=False errors 信封，不向调用方抛出。
"""

from __future__ import annotations

from typing import Any

from rfauto.core import glass_weave_skew as gws
from rfauto.service._helpers import (
    err_envelope as _err,
)
from rfauto.service._helpers import (
    parse_num as _num,
)
from rfauto.service._helpers import (
    require_payload_dict as _require_payload_dict,
)
from rfauto.service.envelope import ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
GLASS_WEAVE_SKEW_SCHEMA_VERSION = "1.0"

#: 复用内核出处登记（WEAVE_STYLES MIT 参数值来源）
SOURCE_PROVENANCE = dict(gws.WEAVE_STYLES_PROVENANCE)

#: 残余 skew 期望口径措辞（内核 1/N 启发式近似，如实透出）
_RESIDUAL_NOTE = (
    "1/N 线性衰减闭式近似（均匀化平均意义，非统计严格结果）；"
    "phase_error_frac 为 n·pitch 偏移规则执行后的残余相位误差占比"
)

# S2-8 单源化（review_ge8e 2026-10-04）：_num/_require_payload_dict/_err
# 本地近逐字节拷贝已删净（#116），单源在 service._helpers（_err=err_envelope
# 别名直引，本服务无版本戳口径）。

# ─── 1. weave_style_info ─────────────────────────────────────────────────────


def weave_style_info(payload: Any = None) -> dict[str, Any]:
    """样式表查询：全部样式或单样式参数 + 出处 provenance。

    Args（payload 键，均可省）:
        style: 样式名（"1067"/"1080"/"2116"/"7628"）；缺省=全表。

    Returns:
        dict: {ok, schema_version, provenance, styles: {名: 参数 dict}}
        或 {ok: False, errors}（未知样式）。
    """
    try:
        p = _require_payload_dict(payload) if payload is not None else {}
        style = p.get("style")
        if style is None:
            return ok_envelope(
                schema_version=GLASS_WEAVE_SKEW_SCHEMA_VERSION,
                provenance=dict(SOURCE_PROVENANCE),
                styles={
                    name: gws.weave_style_spec(name).to_dict()
                    for name in sorted(gws.WEAVE_STYLES)
                },
            )
        if not isinstance(style, str):
            return _err([f"style 必须为 str，实际 {type(style).__name__}"])
        return ok_envelope(
            schema_version=GLASS_WEAVE_SKEW_SCHEMA_VERSION,
            provenance=dict(SOURCE_PROVENANCE),
            styles={style: gws.weave_style_spec(style).to_dict()},
        )
    except (ValueError, TypeError) as exc:
        return _err([str(exc)])


# ─── 2. weave_skew_estimate ──────────────────────────────────────────────────


def weave_skew_estimate(payload: Any) -> dict[str, Any]:
    """玻纤编织 skew 端到端估计（样式→εeff 界→skew→UI verdict）。

    Args（payload 键）:
        style: 样式名（必填，WEAVE_STYLES 之一）；
        direction: "x"|"y"（缺省 "x"；决定 pitch/纱宽取哪向）；
        length_m 或 length_mm: 走线长（二选一，>0）；
        er_resin: 树脂 εr（必填，>0，按叠层数据表给值——内核不内嵌缺省）；
        trace_width_mm: 走线宽（可选，mm）；
        theta_deg: zigzag 角（可选，(0,90]；给出则产出残余期望节）；
        phase_error_frac: n·pitch 偏移残余相位误差占比（缺省 1.0=未对齐
            上界，∈[0,1]）；
        coverage_delta: 概率平均口径 Δρ（缺省 None → 只出最坏口径；
            ∈[-1,1]）；
        data_rate_gbps: 数据率（可选，Gb/s；给出则产出 UI verdict 节）；
        ns_levels: 调制电平数（缺省 2=NRZ）；
        budget_frac: UI 预算占比（缺省 0.1）。

    Returns:
        dict: {ok, schema_version, style, provenance, geometry,
        er_bounds, skew_worst, skew_expected?, zigzag_residual?,
        ui_verdict?, disclaimer}；参数缺失/非法/未知样式 → ok=False
        errors（不抛出、不产数字）。
    """
    try:
        return _estimate_impl(payload)
    except (ValueError, TypeError) as exc:
        return _err([f"参数非法: {exc}"])


def _estimate_impl(payload: Any) -> dict[str, Any]:
    errors: list[str] = []
    p = _require_payload_dict(payload)

    style = p.get("style")
    if style is None:
        return _err(["style 缺失（WEAVE_STYLES 之一：1067/1080/2116/7628）"])
    if not isinstance(style, str):
        return _err([f"style 必须为 str，实际 {type(style).__name__}"])
    try:
        spec = gws.weave_style_spec(style)
    except ValueError as exc:
        return _err([str(exc)])

    direction = p.get("direction", "x")
    if direction not in ("x", "y"):
        return _err([f"direction 必须 'x' 或 'y'，实际 {direction!r}"])
    geo = gws.direction_geometry(spec, direction)

    length_m = p.get("length_m")
    length_mm = p.get("length_mm")
    if length_m is not None and length_mm is not None:
        return _err(["length_m 与 length_mm 二选一"])
    if length_m is not None:
        lm = _num(length_m, "length_m", errors, positive=True)
    elif length_mm is not None:
        lm_mm = _num(length_mm, "length_mm", errors, positive=True)
        lm = None if lm_mm is None else lm_mm / gws.MM_PER_M
    else:
        errors.append("length_m 与 length_mm 至少给一个")
        lm = None
    er_resin = _num(p.get("er_resin"), "er_resin", errors, positive=True)
    trace_width: float | None = None
    if p.get("trace_width_mm") is not None:
        trace_width = _num(p.get("trace_width_mm"), "trace_width_mm", errors, positive=True)
    if errors or lm is None or er_resin is None:
        return _err(errors or ["length 缺失"])

    theta_in = p.get("theta_deg")
    theta = _num(theta_in, "theta_deg", errors) if theta_in is not None else None
    phase_in = p.get("phase_error_frac", 1.0)
    phase = _num(phase_in, "phase_error_frac", errors)
    coverage_in = p.get("coverage_delta")
    coverage = _num(coverage_in, "coverage_delta", errors) if coverage_in is not None else None
    if errors:
        return _err(errors)

    try:
        bounds = gws.homogenize_er_bounds(
            geo["pitch_mm"],
            geo["yarn_width_mm"],
            spec.er_glass,
            er_resin,
            trace_width_mm=trace_width,
        )
        skew_worst = gws.weave_skew_ps(lm, bounds["er_upper"], bounds["er_lower"])
        skew_expected: dict[str, float] | None = None
        if coverage is not None:
            skew_expected = gws.weave_skew_expected_ps(
                lm, coverage, bounds["er_upper"], bounds["er_lower"]
            )
        zigzag: dict[str, float] | None = None
        if theta is not None:
            zigzag = gws.zigzag_residual_expected_ps(
                lm, geo["pitch_mm"], theta, phase, bounds["er_upper"], bounds["er_lower"]
            )
    except (ValueError, TypeError) as exc:
        return _err([f"内核计算失败: {exc}"])

    out: dict[str, Any] = ok_envelope(
        schema_version=GLASS_WEAVE_SKEW_SCHEMA_VERSION,
        style=spec.style,
        provenance=dict(SOURCE_PROVENANCE),
        geometry={
            "direction": direction,
            "pitch_mm": geo["pitch_mm"],
            "yarn_width_mm": geo["yarn_width_mm"],
            "length_m": lm,
            "trace_width_mm": trace_width,
            "style_params": spec.to_dict(),
        },
        er_bounds=bounds,
        skew_worst=skew_worst,
        disclaimer="闭式统计上界/期望估计（平行板串联混合口径），非全波结果；"
            "不含损耗/色散/差分耦合；er_resin 由调用方提供",
    )
    if skew_expected is not None:
        out["skew_expected"] = skew_expected
    if zigzag is not None:
        zigzag_out = dict(zigzag)
        zigzag_out["model_note"] = _RESIDUAL_NOTE
        out["zigzag_residual"] = zigzag_out

    rate_in = p.get("data_rate_gbps")
    if rate_in is not None:
        rate = _num(rate_in, "data_rate_gbps", errors, positive=True)
        ns_in = p.get("ns_levels", 2)
        ns = _num(ns_in, "ns_levels", errors) if ns_in is not None else 2.0
        budget = _num(p.get("budget_frac", 0.1), "budget_frac", errors)
        if errors:
            return _err(errors)
        try:
            verdict = gws.skew_ui_verdict(
                skew_worst["skew_ps"], rate, ns, budget
            )
        except (ValueError, TypeError) as exc:
            return _err([f"UI verdict 失败: {exc}"])
        out["ui_verdict"] = verdict
    return out
