"""fidelity_selection：保真选择形式化（OP-MF，round19 P2 前半，接口原型级）。

round19 原文决策规则：**若 ΔE[r_best]×P(改善) > λ×(c_high−c_low) 则升保真**
（严格大于；等号不升）。双先验来源（round19 同文）：

- **rank_flip 率作相关性先验**：P(改善) = (1−flip)·g(ρ)。flip=低保真/
  高保真排序的 Kendall 不一致对占比（调用方从回放/历史轨迹计算）；
- **ρ 因子 g(ρ)**：消费席5 已合流的
  ``optimization.surrogate.smt_mfk.SMTMultiFidelitySurrogate.
  fidelity_diagnostics``（OP-7）输出 dict（import 禁改，仅消费）——
  g = min(1, |ρ|/rho_warn_threshold)；ρ 缺测（rho_regr≠constant）该
  指标 g 如实 None（该指标不计因子，note 留痕，不编数）；
- **active_learning σ 作增益**：ΔE[r_best] 缺省走
  ``optimization.eipu.expected_improvement_min``（仓内 EI 闭式核，
  min 口径）由 (y_best, μ, σ) 合成——零新数值内核（硬规则 7）。

验收（round19 原文）：合成双谷 A/B 回放——A 谷低保真忠实（flip 小、
ρ 高）→ 升保真；B 谷低保真失真（flip 大、ρ≈0）→ 不升。同 EI 同成
本经济学的因果隔离回放见 tests/unit/test_fidelity_selection_service.py。

接口原型级：零真机、零 LLM 通道（#139）；λ/c 全部显式入参（决策论
旋钮，无隐含物理数字）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.optimization.eipu import expected_improvement_min
from rfauto.service.envelope import ok_envelope

_SOURCE = "rfauto.service.fidelity_selection_service"
_DIAG_SOURCE_NOTE = (
    "diagnostics 形态=optimization.surrogate.smt_mfk."
    "SMTMultiFidelitySurrogate.fidelity_diagnostics() 输出（OP-7 已合流，"
    "仅消费禁改）")


def _num(value: Any, name: str, *, positive: bool = False,
         nonneg: bool = False) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为数值，得到 {value!r}") from exc
    if not math.isfinite(v):
        raise ValueError(f"{name} 必须有限，得到 {v!r}")
    if positive and v <= 0:
        raise ValueError(f"{name} 必须 >0，得到 {v!r}")
    if nonneg and v < 0:
        raise ValueError(f"{name} 必须 ≥0，得到 {v!r}")
    return v


def rho_factors_from_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """fidelity_diagnostics 输出 → 逐指标 ρ 因子（g=min(1,|ρ|/阈值)）。

    ρ 缺测（rho_regr≠constant 或提取失败）的指标 g=None 如实（不计入
    聚合因子，note 留痕）；聚合 g=min(各指标 g)（保守口径）。
    """
    if not isinstance(diagnostics, dict) or \
            not isinstance(diagnostics.get("metrics"), dict):
        return {"ok": False, "source": _SOURCE,
                "reason": f"diagnostics 非法（{_DIAG_SOURCE_NOTE}）"}
    metrics = diagnostics["metrics"]
    if not metrics:
        return {"ok": False, "source": _SOURCE,
                "reason": "diagnostics.metrics 为空"}
    thr = _num(diagnostics.get("rho_warn_threshold", 0.1),
               "rho_warn_threshold", positive=True)
    per: dict[str, Any] = {}
    gs: list[float] = []
    skipped: list[str] = []
    for key, entry in metrics.items():
        rho = (entry or {}).get("rho")
        if rho is None:
            per[key] = {"g": None,
                        "note": "ρ 缺测（该指标不计因子，不编数）"}
            skipped.append(key)
            continue
        # ρ 可为负（低保真反相关是合法实测态）——|ρ| 进因子，不拒负值
        rho_f = abs(_num(rho, f"metrics.{key}.rho"))
        g = min(1.0, rho_f / thr)
        per[key] = {"g": g, "rho_abs": rho_f,
                    "warn": bool((entry or {}).get("warn"))}
        gs.append(g)
    agg = min(gs) if gs else None
    return ok_envelope(
        source=_SOURCE,
        per_metric=per,
        g_aggregate=agg,
        rho_warn=bool(diagnostics.get("warn")),
        skipped_metrics=skipped,
        note=("聚合 g=min(逐指标 g)（保守口径）；"
                     + f"缺测指标 {skipped} 不计因子") if skipped
                    else "聚合 g=min(逐指标 g)（保守口径）",
    )


def expected_gain_best(payload: dict[str, Any]) -> dict[str, Any]:
    """ΔE[r_best]：显式给 delta_e_best，或 (y_best, mu, sigma) 走仓内 EI 核。"""
    p = payload if isinstance(payload, dict) else {}
    if p.get("delta_e_best") is not None:
        return ok_envelope(delta_e_best=_num(p["delta_e_best"], "delta_e_best", nonneg=True), basis="explicit")
    try:
        y_best = _num(p["y_best"], "y_best")
        mu = _num(p["mu"], "mu")
        sigma = _num(p["sigma"], "sigma", nonneg=True)
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "source": _SOURCE,
                "reason": f"ΔE 入参非法（delta_e_best 或 y_best/mu/sigma）: {exc}"}
    xi = _num(p.get("xi", 0.01), "xi", nonneg=True)
    ei = float(expected_improvement_min([mu], [sigma], y_best, xi)[0])
    return ok_envelope(
        delta_e_best=ei,
        basis=f"expected_improvement_min(μ={mu:.6g}, σ={sigma:.6g}, "
                     f"y*={y_best:.6g}, ξ={xi:.6g})（rfauto.optimization."
                     f"eipu 闭式核，min 口径）",
    )


def fidelity_promote_decision(payload: dict[str, Any]) -> dict[str, Any]:
    """升保真判定：ΔE[r_best]×P(改善) > λ×(c_high−c_low)（严格大于）。

    Args（payload 键）:
        rank_flip_rate: [0,1]（Kendall 不一致对占比——相关性先验）；
        diagnostics?: fidelity_diagnostics 输出（ρ 因子；缺省 g=1）；
        ΔE: delta_e_best 或 y_best/mu/sigma(,xi)（见 expected_gain_best）；
        cost_low/cost_high: 低保真/高保真单点成本（≥0）；
        lambda: 成本效率阈值乘子（≥0，缺省 1.0）。

    Returns:
        {ok, decision: "promote"|"stay", gain, budget, p_improve, ...}。
    """
    p = payload if isinstance(payload, dict) else {}
    try:
        flip = _num(p.get("rank_flip_rate"), "rank_flip_rate", nonneg=True)
        if flip > 1.0:
            raise ValueError(f"rank_flip_rate 必须 ∈ [0,1]，得到 {flip}")
        c_lo = _num(p.get("cost_low"), "cost_low", nonneg=True)
        c_hi = _num(p.get("cost_high"), "cost_high", nonneg=True)
        lam = _num(p.get("lambda", 1.0), "lambda", nonneg=True)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "source": _SOURCE, "reason": f"入参非法: {exc}"}
    gain_rep = expected_gain_best(p)
    if not gain_rep.get("ok"):
        return {**gain_rep, "source": _SOURCE}
    delta_e = gain_rep["delta_e_best"]

    g_rep: dict[str, Any] = {"g": 1.0, "rho_warn": False, "note":
                             "diagnostics 未提供——g=1（仅 flip 先验）"}
    if p.get("diagnostics") is not None:
        g_rep = rho_factors_from_diagnostics(p["diagnostics"])
        if not g_rep.get("ok"):
            return {**g_rep, "source": _SOURCE}
    g = g_rep.get("g_aggregate", g_rep.get("g"))
    if g is None:
        return {"ok": False, "source": _SOURCE,
                "reason": "全部指标 ρ 缺测（g 不可计）——"
                          "rho_regr 改回 'constant' 或直接给 delta_e_best"}

    p_improve = (1.0 - flip) * g
    gain = delta_e * p_improve
    budget = lam * (c_hi - c_lo)
    decision = "promote" if gain > budget else "stay"
    return ok_envelope(
        **{
        "source": _SOURCE,
        "decision": decision,
        "delta_e_best": delta_e,
        "delta_e_basis": gain_rep.get("basis"),
        "rank_flip_rate": flip,
        "g_rho": g,
        "p_improve": p_improve,
        "gain": gain,
        "budget": budget,
        "lambda": lam,
        "cost_low": c_lo,
        "cost_high": c_hi,
        "rho_warn": g_rep.get("rho_warn", False),
        "rule": "ΔE[r_best]×P(改善) > λ×(c_high−c_low) 则升保真"
                    "（严格大于；P=(1−flip)·min(1,|ρ|/ρ_thr) 保守聚合）",
        },
    )
