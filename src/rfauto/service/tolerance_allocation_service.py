"""M-7 公差分配 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/tolerance_allocation.py 内核（拉格朗日闭式/二分 + 对照法 + Cpk
重算），本服务零物理公式，全部数字出自确定性内核（规则 7）。

- :func:`tolerance_allocate`：敏感度表 + 成本系数表 + 目标（预算 C / 公差
  和 T / RSS 上限，经 mode 分派）→ 逐参数公差建议表 + 总成本/RSS/WCD；
  compare=True 附 greedy/proportional 两对照法（round1 判据基线臂）与
  Cpk 重算。
- 优化不可行 → ok=False envelope（内核 feasible=False 透传，不抛）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import tolerance_allocation as ta
from rfauto.service.envelope import error_envelope, ok_envelope

TOLERANCE_SERVICE_SCHEMA_VERSION = "1.0"

_MODES = ("cost_budget", "budget_t", "min_cost")


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(list(errors))


def _num_map(value: Any, name: str, errors: list[str]) -> dict[str, float] | None:
    """{str: number} 收敛（bool 显式拒收 df7+⑯；None/缺失键如实报缺）。"""
    if not isinstance(value, dict) or not value:
        errors.append(f"{name} 必须是非空 JSON 对象")
        return None
    out: dict[str, float] = {}
    for key, raw in value.items():
        if isinstance(raw, bool) or raw is None:
            errors.append(f"{name}[{key!r}] 必须是数字（bool/null 拒收）")
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            errors.append(f"{name}[{key!r}] 必须是数字，实际 {raw!r}")
            continue
        if not math.isfinite(val):
            errors.append(f"{name}[{key!r}] 必须为有限数")
            continue
        out[str(key)] = val
    return out or None


def _opt_num(value: Any, name: str, errors: list[str]) -> float | None:
    """可选数值：None 合法（判缺失 is not None，#364④）；存在但非法即报。"""
    if value is None:
        return None
    if isinstance(value, bool):
        errors.append(f"{name} 不接受 bool")
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        errors.append(f"{name} 必须是数字，实际 {value!r}")
        return None
    if not math.isfinite(val):
        errors.append(f"{name} 必须为有限数")
        return None
    return val


def tolerance_allocate(payload: Any) -> dict[str, Any]:
    """cost-aware 公差分配。

    Args（payload 键）:
        sensitivities: {参数: ∂y/∂x}（必填）；
        cost_coeffs: {参数: 成本系数}（与 sensitivities 同键，必填）；
        mode: "cost_budget"（min Σ(Sδ)² s.t. Σc≤C，缺省）| "budget_t"
            （min Σ(Sδ)² s.t. Σδ≤T）| "min_cost"（min Σc s.t. RSS≤R）；
        budget_c / total_tol_t / rss_max: 目标（按 mode 三选一）；
        cost_model: "inverse_power"（缺省）| "exponential"（round1 缺省成本型）；
        cost_power: inverse_power 的 p（缺省 1）；exp_scale: exponential δ_c；
        tol_min / tol_max: 箱约束（缺省 1e-6 / 1.0）；
        compare: true 时附 greedy/proportional 对照与 RSS 差距；
        spec: {usl, lsl?, mean?, yield_target?} 可选 → Cpk 重算 + 良率换算
            参考 σ（round1 输出面）。

    Returns:
        dict: {ok, schema_version, mode, allocation, comparison?, spec?}。
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return _err([f"payload 必须是 JSON 对象，实际 {type(payload).__name__}"])

    sens = _num_map(payload.get("sensitivities"), "sensitivities", errors)
    coeffs = _num_map(payload.get("cost_coeffs"), "cost_coeffs", errors)
    if errors or sens is None or coeffs is None:
        return _err(errors or ["sensitivities/cost_coeffs 缺失"])
    missing = [k for k in sens if k not in coeffs]
    if missing:
        return _err([f"cost_coeffs 缺键: {missing}"])

    mode = payload.get("mode", "cost_budget")
    if mode not in _MODES:
        return _err([f"mode 必须是 {_MODES} 之一，实际 {mode!r}"])

    cost_model = payload.get("cost_model", ta.COST_INVERSE_POWER)
    cost_power = _opt_num(payload.get("cost_power"), "cost_power", errors)
    exp_scale = _opt_num(payload.get("exp_scale"), "exp_scale", errors)
    tol_min = _opt_num(payload.get("tol_min", 1e-6), "tol_min", errors)
    tol_max = _opt_num(payload.get("tol_max", 1.0), "tol_max", errors)
    if errors:
        return _err(errors)

    target: float | None
    if mode == "cost_budget":
        target = _opt_num(payload.get("budget_c"), "budget_c", errors)
    elif mode == "budget_t":
        target = _opt_num(payload.get("total_tol_t"), "total_tol_t", errors)
    else:
        target = _opt_num(payload.get("rss_max"), "rss_max", errors)
    if errors:
        return _err(errors)
    if target is None:
        key = {"cost_budget": "budget_c", "budget_t": "total_tol_t", "min_cost": "rss_max"}[mode]
        return _err([f"{key} 缺失（mode={mode}）"])

    kwargs: dict[str, Any] = {
        "cost_model": cost_model,
        "tol_min": 1e-6 if tol_min is None else tol_min,
        "tol_max": 1.0 if tol_max is None else tol_max,
    }
    if cost_power is not None and cost_model == ta.COST_INVERSE_POWER:
        kwargs["cost_power"] = cost_power
    if exp_scale is not None and cost_model == ta.COST_EXPONENTIAL:
        kwargs["exp_scale"] = exp_scale

    try:
        if mode == "cost_budget":
            res = ta.allocate_cost_budget(sens, coeffs, target, **kwargs)
        elif mode == "budget_t":
            res = ta.allocate_budget_t(sens, target, tol_max=kwargs["tol_max"])
        else:
            res = ta.allocate_min_cost(sens, coeffs, target, **kwargs)
    except ValueError as exc:
        return _err([str(exc)])
    if not res.feasible:
        return _err([f"优化不可行: {res.note}"])

    out: dict[str, Any] = ok_envelope(schema_version=TOLERANCE_SERVICE_SCHEMA_VERSION, mode=mode, allocation=res.to_dict())

    if bool(payload.get("compare")) and mode in ("cost_budget",):
        greedy = ta.allocate_greedy_cost(sens, coeffs, target, **kwargs)
        prop = ta.allocate_proportional_cost(sens, coeffs, target, **kwargs)
        out["comparison"] = {
            "greedy": greedy.to_dict(),
            "proportional": prop.to_dict(),
            "rss_gap_greedy": greedy.rss - res.rss,
            "rss_gap_proportional": prop.rss - res.rss,
            "note": "对照法 RSS ≥ 拉格朗日解（round1 判据：Σcost < 等公差基线方向）",
        }

    spec_in = payload.get("spec")
    if isinstance(spec_in, dict):
        usl = _opt_num(spec_in.get("usl"), "spec.usl", errors)
        if usl is None:
            return _err(errors or ["spec.usl 缺失"])
        lsl = _opt_num(spec_in.get("lsl"), "spec.lsl", errors)
        mean = _opt_num(spec_in.get("mean", 0.0), "spec.mean", errors)
        if errors:
            return _err(errors)
        spec_out: dict[str, Any] = {
            "cpk": ta.cpk_from_tols(sens, res.tols, usl=usl, lsl=lsl, mean=mean or 0.0)
        }
        margin = _opt_num(spec_in.get("margin"), "spec.margin", errors)
        yield_target = _opt_num(spec_in.get("yield_target"), "spec.yield_target", errors)
        if errors:
            return _err(errors)
        if margin is not None and yield_target is not None:
            try:
                spec_out["sigma_for_yield"] = ta.yield_to_output_sigma(margin, yield_target)
            except ValueError as exc:
                return _err([str(exc)])
        out["spec"] = spec_out
    return out
