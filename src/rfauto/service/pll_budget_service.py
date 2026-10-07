"""F-E 件 6 service 面：PLL 预算 JSON 信封（规则 4：服务层 JSON 进出）。

薄壳（零物理公式，全部数字出自 core/pll_budget.py 确定性内核，规则 7）。
单入口 :func:`pll_budget`，按 payload["model"] 三分派：

- "stability"：{k_phi, kvco_rad_s_v, n_div, r2_ohm, c_farad,
  pm_warning_threshold_deg?} → core.stability_budget（ωn/ζ/穿越/PM 双
  路径 + pm_warning 标志字段）；
- "jitter"：{f_edges_hz, omega_n, zeta, f_carrier_hz?, l_ref_dbc?,
  l_vco_dbc?, mash_order?, f_ref_hz?, mash_delta?, division_n?} →
  core.pll_jitter_budget（输出噪声合成 + 复用 clock_noise 积分器；
  噪声源至少其一，判缺失 is not None）；
- "crystal_l"：{osc_type, f_offset_hz, f_target_hz?} →
  core.crystal_l_dbc（晶振量级表查表 + 20log 载波换算）。

参数缺失/非法/model 不支持 → ok=False + errors（不抛出、不产数字）；
数值 0.0 合法（判缺失 is not None，#364④）。本服务 v1 不接 CLI/MCP
（域内约定，消费者为后续预算链）；法源与诚实边界见 core/pll_budget.py
docstring（Gardner/Banerjee 传函与稳定裕度口径、Riley 1993 ΣΔ 谱、
晶振表为公开手册量级带非实测）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core import pll_budget as pb

# F-13 批1：_num/_require_payload_dict 并入 service/_helpers 单源（别名
# import 保调用名/调用点零改动；本地副本按 #116 治理纪律删净防遮蔽；
# W2-G 批 1 语义冻结钉 tests/unit/test_w2_g_f13_batch1.py）。
from rfauto.service._helpers import parse_num as _num
from rfauto.service._helpers import require_payload_dict as _require_payload_dict
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
PLL_BUDGET_SERVICE_SCHEMA_VERSION = "1.0"

_MODE_STABILITY = "stability"
_MODE_JITTER = "jitter"
_MODE_CRYSTAL_L = "crystal_l"


# ─── payload 解析助手（字段错误收集进 errors，不抛出；同 clock_noise_service 口径）
# （_require_payload_dict/_num 已并入 service/_helpers 单源，F-13 批1）


def _num_list(value: Any, name: str, errors: list[str]) -> list[float] | None:
    """数值列表收敛（bool 元素拒收）。"""
    if value is None:
        errors.append(f"{name} 缺失")
        return None
    if not isinstance(value, (list, tuple)) or not value:
        errors.append(f"{name} 必须为非空数值列表")
        return None
    out: list[float] = []
    for idx, item in enumerate(value):
        v = _num(item, f"{name}[{idx}]", errors)
        if v is None:
            return None
        out.append(v)
    return out


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(list(errors))


def _dispatch_model(payload: dict[str, Any]) -> str:
    """model 键收敛（判缺失 is not None，缺省 stability）。"""
    model = payload.get("model")
    if model is None:
        return _MODE_STABILITY
    if model not in (_MODE_STABILITY, _MODE_JITTER, _MODE_CRYSTAL_L):
        raise ValueError(
            f"model={model!r} 不支持（'{_MODE_STABILITY}' | '{_MODE_JITTER}' "
            f"| '{_MODE_CRYSTAL_L}'）"
        )
    return str(model)


# ─── 三分派实现（core 调用包 try/except → ok=False，不产数字）────────────────


def _run_stability(p: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    k_phi = _num(p.get("k_phi"), "k_phi", errors, positive=True)
    kvco = _num(p.get("kvco_rad_s_v"), "kvco_rad_s_v", errors, positive=True)
    n_div = _num(p.get("n_div"), "n_div", errors, positive=True)
    r2 = _num(p.get("r2_ohm"), "r2_ohm", errors, positive=True)
    c_f = _num(p.get("c_farad"), "c_farad", errors, positive=True)
    thr: float | None = None
    if p.get("pm_warning_threshold_deg") is not None:
        thr = _num(p.get("pm_warning_threshold_deg"), "pm_warning_threshold_deg", errors)
    if errors or None in (k_phi, kvco, n_div, r2, c_f):
        return _err(errors)
    assert k_phi is not None and kvco is not None and n_div is not None  # 已过 None 门
    assert r2 is not None and c_f is not None
    if thr is not None:
        result = pb.stability_budget(k_phi, kvco, n_div, r2, c_f, thr)
    else:
        result = pb.stability_budget(k_phi, kvco, n_div, r2, c_f)
    return ok_envelope(schema_version=PLL_BUDGET_SERVICE_SCHEMA_VERSION, model=_MODE_STABILITY, result=result.to_dict())


def _run_jitter(p: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    f_edges = _num_list(p.get("f_edges_hz"), "f_edges_hz", errors)
    omega_n = _num(p.get("omega_n"), "omega_n", errors, positive=True)
    zeta = _num(p.get("zeta"), "zeta", errors, positive=True)
    f_carrier: float | None = None
    if p.get("f_carrier_hz") is not None:
        f_carrier = _num(p.get("f_carrier_hz"), "f_carrier_hz", errors, positive=True)
    l_ref: list[float] | None = None
    if p.get("l_ref_dbc") is not None:
        l_ref = _num_list(p.get("l_ref_dbc"), "l_ref_dbc", errors)
    l_vco: list[float] | None = None
    if p.get("l_vco_dbc") is not None:
        l_vco = _num_list(p.get("l_vco_dbc"), "l_vco_dbc", errors)
    mash_order: int | None = None
    if p.get("mash_order") is not None:
        mo = _num(p.get("mash_order"), "mash_order", errors)
        if mo is not None:
            if float(mo).is_integer() and int(mo) >= 1:
                mash_order = int(mo)
            else:
                errors.append(f"mash_order 必须为 ≥1 整数，实际 {mo!r}")
    f_ref: float | None = None
    if p.get("f_ref_hz") is not None:
        f_ref = _num(p.get("f_ref_hz"), "f_ref_hz", errors, positive=True)
    mash_delta: float | None = None
    if p.get("mash_delta") is not None:
        mash_delta = _num(p.get("mash_delta"), "mash_delta", errors, positive=True)
    division_n: float | None = None
    if p.get("division_n") is not None:
        division_n = _num(p.get("division_n"), "division_n", errors, positive=True)
    if errors or f_edges is None or omega_n is None or zeta is None:
        return _err(errors)
    if f_carrier is not None and f_carrier <= 0.0:
        return _err(errors)  # _num(positive=True) 已记错，此处兜底短路
    kwargs: dict[str, Any] = {}
    if l_ref is not None:
        kwargs["l_ref_dbc"] = l_ref
    if l_vco is not None:
        kwargs["l_vco_dbc"] = l_vco
    if mash_order is not None:
        kwargs["mash_order"] = mash_order
    if f_ref is not None:
        kwargs["f_ref_hz"] = f_ref
    if mash_delta is not None:
        kwargs["mash_delta"] = mash_delta
    if division_n is not None:
        kwargs["division_n"] = division_n
    result = pb.pll_jitter_budget(f_edges, f_carrier, omega_n, zeta, **kwargs)
    return ok_envelope(schema_version=PLL_BUDGET_SERVICE_SCHEMA_VERSION, model=_MODE_JITTER, result=result.to_dict())


def _run_crystal_l(p: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    osc_type = p.get("osc_type")
    if not isinstance(osc_type, str):
        errors.append(f"osc_type 必须是字符串，实际 {osc_type!r}")
    f_offsets = _num_list(p.get("f_offset_hz"), "f_offset_hz", errors)
    f_target: float | None = None
    if p.get("f_target_hz") is not None:
        f_target = _num(p.get("f_target_hz"), "f_target_hz", errors, positive=True)
    if errors or osc_type is None or f_offsets is None:
        return _err(errors)
    assert isinstance(osc_type, str) and f_offsets is not None  # 已过 None 门
    kwargs: dict[str, Any] = {}
    if f_target is not None:
        kwargs["f_target_hz"] = f_target
    l_vals = pb.crystal_l_dbc(f_offsets, osc_type, **kwargs)
    return ok_envelope(
        schema_version=PLL_BUDGET_SERVICE_SCHEMA_VERSION,
        model=_MODE_CRYSTAL_L,
        result={
            "osc_type": osc_type,
            "f_offset_hz": [float(v) for v in f_offsets],
            "l_dbc_hz": [float(v) for v in l_vals],
            "f_carrier_hz": float(pb.CRYSTAL_OSC_TABLE[osc_type]["f_carrier_hz"]),
            "f_target_hz": f_target,
            "note": str(pb.CRYSTAL_OSC_TABLE[osc_type]["note"]),
        },
    )


# ─── 单入口 ──────────────────────────────────────────────────────────────────


def pll_budget(payload: Any) -> dict[str, Any]:
    """PLL 预算 JSON 信封（三分派，见模块 docstring）。

    Returns:
        dict: ok=True 时 {"ok", "schema_version", "model", "result"}；
        参数缺失/非法/model 不支持 → ok=False + errors（不抛出、不产数字）。
    """
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])
    try:
        model = _dispatch_model(p)
    except ValueError as exc:
        return _err([str(exc)])
    errors: list[str] = []
    try:
        if model == _MODE_STABILITY:
            return _run_stability(p, errors)
        if model == _MODE_JITTER:
            return _run_jitter(p, errors)
        return _run_crystal_l(p, errors)
    except (ValueError, KeyError, TypeError) as exc:
        return _err([f"{model} 预算失败: {exc}"])
