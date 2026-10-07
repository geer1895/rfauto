"""twin_runtime：数字孪生运行时编排层（TW-1，round19 P2 前半，接口原型级）。

**接口原型级**（ge8c 席C5 口径）：状态机（测量→drift verdict→aging 前向
投影→三档建议）+ 建议器闭式判据表 + 时间线报告器；**离线演练模式**
（round19 原文"#328 约束下先离线演练"——本面零真机、零 LLM 通道 #139、
纯确定性）。

内核全部消费既有已合流件（硬规则 7：零新物理数字）：

1. **drift verdict**：``core.anchor_drift.anchor_drift_report``（QW-16，
   MK 趋势 + 分布指纹双线，verdict 语义见其 docstring）；
2. **aging 前向投影**：``core.aging.er_aging_drift``（Class-2 陶瓷 εr
   log-时间律）× ``service.aging_service.detune_pct_of_er_drift``
   （f0∝1/√εeff 一阶）× ``aging_eol_verdict``（失谐判据）；
3. **RUL**：log-律反解 d*：|detune(d*)|=spec → t* = t_ref·10^{d*}。
   **RUL 语义如实登记（round19 原文）**：仅 log-律外推——外推超出
   观测窗的结论只具趋势参考性，非认证寿命结论（aging_service 同口径
   免责）。k_log=0（零漂移率）RUL=∞ 如实不编数。

三档建议闭式判据表（_RECOMMEND_CRITERIA，优先级 换件>校准>观察，安全
优先排序）：换件=EOL FAIL 或剩余寿命耗尽；校准=drift warning/drifted
且 EOL PASS；观察=其余（stable/insufficient/no_data 且 EOL PASS）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.aging import er_aging_drift
from rfauto.core.anchor_drift import anchor_drift_report
from rfauto.service.aging_service import (
    aging_eol_verdict,
    detune_pct_of_er_drift,
)
from rfauto.service.envelope import ok_envelope

_SOURCE = "rfauto.service.twin_runtime_service"

#: RUL 反解搜索上界（decades；t_ref·10^12 h 远超器件实用域）
_RUL_MAX_DECADES = 12.0
#: RUL 反解二分相对容差
_RUL_TOL = 1e-10

#: 三档建议闭式判据表（round19：校准/换件/观察；优先级降序，安全优先）
_RECOMMEND_CRITERIA: tuple[dict[str, str], ...] = (
    {"action": "replace", "label": "换件",
     "criterion": "eol FAIL（投影地平线内 |detune|>spec）或 剩余寿命 ≤ "
                  "rul_lead_h（log-律 RUL 外推口径）"},
    {"action": "recalibrate", "label": "校准",
     "criterion": "drift verdict ∈ {warning, drifted} 且 eol PASS"},
    {"action": "observe", "label": "观察",
     "criterion": "其余（drift stable/insufficient/no_data 且 eol PASS）"},
)


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


def detune_of_decades(er0: float, k_log: float, decades: float,
                      fill_fraction: float = 1.0) -> float:
    """log-律 decades → 失谐 pct（复用 er_aging_drift+detune_pct_of_er_drift）。"""
    er_t = er_aging_drift(er0, k_log, 10.0 ** decades, 1.0)["er"]
    return detune_pct_of_er_drift(er0, er_t, fill_fraction)


def rul_log_law(er0: float, k_log: float, spec_pct: float,
                fill_fraction: float = 1.0) -> dict[str, Any]:
    """RUL log-律反解（|detune(d*)|=spec → t*=t_ref·10^{d*}，t_ref=1 h 惯例）。

    仅 log-律外推（round19 语义登记）：单调二分，超界如实 None 不编数。
    """
    if k_log == 0.0:
        return {"rul_h": None, "decades": None,
                "note": "k_log=0（零漂移率）：log 律零斜率，RUL=∞（无老化）"}
    lo, hi = 0.0, _RUL_MAX_DECADES
    if abs(detune_of_decades(er0, k_log, hi, fill_fraction)) < spec_pct:
        return {"rul_h": None, "decades": None,
                "note": f"搜索上界 10^{hi:g} h 内 |detune| 未达 spec "
                        f"（{spec_pct}%）——RUL 超出 log-律外推域，如实不判"}
    while hi - lo > max(lo, 1.0) * _RUL_TOL:
        mid = 0.5 * (lo + hi)
        if abs(detune_of_decades(er0, k_log, mid, fill_fraction)) < spec_pct:
            lo = mid
        else:
            hi = mid
    d = 0.5 * (lo + hi)
    return {"rul_h": 10.0 ** d, "decades": d,
            "note": "log-律外推（er(t)=er0(1+k·log10(t/t0)) 反解），"
                    "非认证寿命结论"}


def twin_step(payload: dict[str, Any]) -> dict[str, Any]:
    """孪生单步：测量残差 → drift verdict → aging 前向投影 → 三档建议。

    Args（payload 键）:
        residuals 或 snapshots: 锚残差序列 / 快照映射序列（透传
            anchor_drift_report 双口径）；
        aging: {er0, aging_frac_per_decade(k_log), spec_pct,
            fill_fraction?=1.0, t_now_h?=None（当前等效年龄）}；
        projection_h?: 前向投影地平线（小时；缺省=horizon_h 或 100·t_ref）；
        horizon_h?: 规划地平线（小时；rul 判换件的提前量基准），
            rul_lead_h?: 换件提前量（小时，缺省 0=剩余寿命耗尽才换）；
        drift 阈值透传: alpha?/mean_shift_rel_max?/std_ratio_max?。

    Returns:
        {ok, recommendation: {action,label,reasons[]}, drift, aging_eol,
        rul, criteria_table}；入参非法 ok=False（reason 如实）。
    """
    p = payload if isinstance(payload, dict) else {}
    series = p.get("residuals", p.get("snapshots"))
    aging = p.get("aging")
    if not isinstance(aging, dict):
        return {"ok": False, "source": _SOURCE,
                "reason": "aging 缺失或非 dict（{er0, aging_frac_per_decade, "
                          "spec_pct} 必填）"}
    try:
        er0 = _num(aging["er0"], "aging.er0", positive=True)
        k_log = _num(aging["aging_frac_per_decade"],
                     "aging.aging_frac_per_decade")
        spec_pct = _num(aging["spec_pct"], "aging.spec_pct", positive=True)
        fill = _num(aging.get("fill_fraction", 1.0), "aging.fill_fraction",
                    positive=True)
        if fill > 1.0:
            raise ValueError("aging.fill_fraction 必须 ∈ (0,1]")
        t_now = (None if aging.get("t_now_h") is None
                 else _num(aging["t_now_h"], "aging.t_now_h", nonneg=True))
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "source": _SOURCE, "reason": f"aging 入参非法: {exc}"}
    if fill <= 0.0:
        return {"ok": False, "source": _SOURCE,
                "reason": "aging.fill_fraction 必须 ∈ (0,1]"}

    drift = anchor_drift_report(
        series if series is not None else [],
        alpha=float(p.get("alpha", 0.05)),
        mean_shift_rel_max=float(p.get("mean_shift_rel_max", 0.5)),
        std_ratio_max=float(p.get("std_ratio_max", 2.0)))

    horizon = (None if p.get("horizon_h") is None
               else _num(p["horizon_h"], "horizon_h", positive=True))
    proj_h = (p["projection_h"] if p.get("projection_h") is not None
              else (horizon if horizon is not None else 100.0))
    try:
        proj_h = _num(proj_h, "projection_h", positive=True)
        proj_decades = math.log10(proj_h)  # t_ref=1 h 惯例
        er_proj = er_aging_drift(er0, k_log, 10.0 ** proj_decades, 1.0)["er"]
        detune_proj = detune_pct_of_er_drift(er0, er_proj, fill)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"ok": False, "source": _SOURCE,
                "reason": f"前向投影非法: {exc}"}
    eol = aging_eol_verdict({"detune_pct": detune_proj, "spec_pct": spec_pct})

    rul = rul_log_law(er0, k_log, spec_pct, fill)
    lead = _num(p.get("rul_lead_h", 0.0), "rul_lead_h", nonneg=True)

    # 三档建议（优先级 换件>校准>观察，安全优先）
    reasons: list[str] = []
    action = "observe"
    if eol["verdict"] == "FAIL":
        action = "replace"
        reasons.append(
            f"EOL FAIL：投影 {proj_h:.4g} h 失谐 |{abs(detune_proj):.4g}|% "
            f"> spec {spec_pct}%（闭式判据表第 1 条）")
    elif rul["rul_h"] is not None and t_now is not None \
            and rul["rul_h"] - t_now <= lead:
        action = "replace"
        reasons.append(
            f"剩余寿命耗尽：RUL {rul['rul_h']:.4g} h − t_now {t_now:.4g} h "
            f"≤ 提前量 {lead:.4g} h（log-律外推口径）")
    if action == "observe" and drift["verdict"] in ("warning", "drifted"):
        action = "recalibrate"
        reasons.append(
            f"drift verdict={drift['verdict']}（MK 趋势+指纹双线）且 EOL "
            f"PASS——先校准复锚（闭式判据表第 2 条）")
    if not reasons:
        reasons.append(
            f"drift verdict={drift['verdict']} 且 eol "
            f"{eol['verdict']}——按闭式判据表第 3 条观察")

    labels = {c["action"]: c["label"] for c in _RECOMMEND_CRITERIA}
    return ok_envelope(
        source=_SOURCE,
        recommendation={"action": action, "label": labels[action],
                               "reasons": reasons},
        drift=drift,
        aging_eol=eol,
        projection={"t_h": proj_h, "decades": proj_decades,
                           "er": er_proj, "detune_pct": detune_proj,
                           "spec_pct": spec_pct},
        rul=rul,
        criteria_table=[dict(c) for c in _RECOMMEND_CRITERIA],
        mode="offline_drill",
        disclaimer="RUL 仅 log-律外推（趋势参考），非认证寿命结论"
                          "（aging_service 同口径）",
    )


def twin_timeline(payload: dict[str, Any]) -> dict[str, Any]:
    """时间线报告器：按时间序回放多步 twin_step 结果（确定性 echo，不编数）。

    Args: {steps: [{at?, step: twin_step 结果 | step_payload: 现场单步}]}
    Returns: {ok, events[], lines[], summary}；step 非法如实 error 行不阻塞。
    """
    p = payload if isinstance(payload, dict) else {}
    steps = p.get("steps")
    if not isinstance(steps, list) or not steps:
        return {"ok": False, "source": _SOURCE,
                "reason": "steps 缺失或非非空列表（{at?, step|step_payload}）"}
    events: list[dict[str, Any]] = []
    lines: list[str] = []
    for i, item in enumerate(steps):
        if not isinstance(item, dict):
            events.append({"index": i, "status": "error",
                           "reason": "step 非法（非 dict）"})
            continue
        step = item.get("step")
        if step is None and item.get("step_payload") is not None:
            step = twin_step(item["step_payload"])
        if not isinstance(step, dict) or not step.get("ok"):
            events.append({"index": i, "at": item.get("at"),
                           "status": "error",
                           "reason": "step 结果非法或 ok=False（如实透传）"})
            continue
        rec = step.get("recommendation", {})
        ev = {"index": i, "at": item.get("at"),
              "status": "ok",
              "action": rec.get("action"),
              "label": rec.get("label"),
              "drift_verdict": (step.get("drift") or {}).get("verdict"),
              "eol_verdict": (step.get("aging_eol") or {}).get("verdict")}
        events.append(ev)
        lines.append(
            f"[{item.get('at', f'#{i}')}] {rec.get('label')} "
            f"(drift={ev['drift_verdict']}, eol={ev['eol_verdict']})")
    actions = [e.get("action") for e in events if e.get("status") == "ok"]
    summary = {
        "n_steps": len(steps), "n_ok": len(actions),
        "action_counts": {a: actions.count(a)
                          for a in sorted(set(actions))},
        "last_action": actions[-1] if actions else None,
    }
    return ok_envelope(source=_SOURCE, events=events, lines=lines, summary=summary, mode="offline_drill")
