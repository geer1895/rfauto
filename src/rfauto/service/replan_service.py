"""replan_service：R3 AQE 分段重规划多保真路由（Spark AQE 机制翻译）。

分段语义（docs/plan_expansion_pool_20260924.md R3）：
    fake 批=stage1，产出即查 cost 分布是否退化（#195/#207 常数陷阱）→
    退化换判据/采样器而非烧真机；openEMS 首批点回来按实测
    「代理误差/真机耗时」成本模型重规划是否升 HFSS。
    计划=带 checkpoint 的一等对象，可解释可回放。

铁律落地：
- 数值只在确定性内核（确定性内核铁律）：全部判定由纯函数从输入数值确定性
  产出，无 LLM、无网络、无墙钟进决策；
- 判据/决策表/成本模型阈值全部预声明于 runs/df7_r3aqe/criteria.md，
  本模块常量与其逐字对应，不得单侧改数（#122：门值与放行语义不可改）；
- 判据统计量匹配响应形态（#195/#197）：值列提取优先显式统计量口径
  （s11_db_min_in_band），退化判定同时看相对标准差与唯一值占比，
  常数陷阱（std=0）与近常数病态（#207 平底碗）都拦得住；
- JSON 进出（服务层契约）：输入/输出均为可 JSON 化 dict，路径入参
  第一行 Path() 收敛（#140）。

幂等重放：assessment/route/cost model 输出只依赖输入数值；checkpoint
文件内容不含墙钟（sort_keys 定序），同输入重复 save 逐字节相同。
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

# ─── 预声明阈值（criteria.md §一/§二/§三，逐字对应） ─────────────────────────

#: 最少样本数：n<3 不判退化（空/单点 ok=False 交决策表 hold）。
MIN_POINTS_FOR_ASSESSMENT = 3

#: 判据 A：相对标准差阈值（rel_std < 0.05 → 退化；#195/#207 量级依据见 criteria）。
COST_REL_STD_THRESHOLD = 0.05

#: 判据 A 绝对分支：|mean| ≤ 1e-9 时以绝对 std 判（全零常数 → 退化）。
COST_MEAN_EPS = 1e-9
COST_ABS_STD_FLOOR = 1e-9

#: 判据 B：唯一值占比阈值（unique_ratio ≤ 0.5 → 退化）。
COST_UNIQUE_RATIO_THRESHOLD = 0.5

#: 直方图箱数（证据面摘要，非判据）。
HISTOGRAM_BINS = 5

#: 升保真判据 1：代理相对误差地板（≤5% 升 HFSS 无信息增益，严 >）。
SURR_ERR_REL_MIN = 0.05

#: 升保真判据 2：收益倍数（benefit_multiple ≥ 3.0，≥ 宽松界）。
HFSS_GAIN_MULTIPLE = 3.0

#: 升保真判据 3：最小可负担 HFSS 点数（孤点不成路由）。
HFSS_MIN_POINTS = 3

#: checkpoint schema 标识与版本。
CHECKPOINT_SCHEMA = "rfauto.replan_checkpoint"
CHECKPOINT_VERSION = 1

#: 值列提取优先级说明（criteria §一）：cost > metrics.s11_db_min_in_band >
#: 顶层 s11_db_min > metrics.cost。
_VALUE_SOURCES = (
    ("cost", lambda p: p.get("cost")),
    ("metrics.s11_db_min_in_band", lambda p: (p.get("metrics") or {}).get(
        "s11_db_min_in_band")),
    ("s11_db_min", lambda p: p.get("s11_db_min")),
    ("metrics.cost", lambda p: (p.get("metrics") or {}).get("cost")),
)


def _is_finite_number(v: Any) -> bool:
    """bool 不算数值列（True 会被 float() 吃成 1.0，静默污染统计）。"""
    if isinstance(v, bool):
        return False
    return isinstance(v, (int, float)) and math.isfinite(float(v))


def extract_cost_value(point: dict[str, Any]) -> tuple[float, str] | None:
    """按预声明优先级提取单点 cost 值列，返回 (值, 来源名) 或 None。"""
    for source_name, getter in _VALUE_SOURCES:
        v = getter(point)
        if _is_finite_number(v):
            return float(v), source_name
    return None


# ─── ① cost 分布退化判定（stage1 fake 批产出即查） ───────────────────────────

def assess_cost_degeneration(points: list[dict[str, Any]]) -> dict[str, Any]:
    """cost 值列退化判定（确定性，无墙钟无随机）。

    判据（criteria §一）：degenerate = A(rel_std < 0.05，含绝对分支)
    or B(unique_ratio ≤ 0.5)。空/单点 ok=False 不崩；无数值列的点计入
    n_missing 如实报，不猜测回退。
    """
    points = list(points or [])
    extracted: list[tuple[float, str]] = []
    n_missing = 0
    for p in points:
        got = extract_cost_value(p if isinstance(p, dict) else {})
        if got is None:
            n_missing += 1
        else:
            extracted.append(got)

    n = len(extracted)
    if n < MIN_POINTS_FOR_ASSESSMENT:
        return {
            "ok": False,
            "degenerate": None,
            "n": n,
            "n_missing": n_missing,
            "min_required": MIN_POINTS_FOR_ASSESSMENT,
            "errors": [f"样本不足：有效值列 {n} < {MIN_POINTS_FOR_ASSESSMENT}，"
                       f"缺失 {n_missing} 点（criteria §一，判 hold 不瞎动）"],
        }

    values = [v for v, _ in extracted]
    sources = {s for _, s in extracted}
    # 混合来源不合法：同一值列必须同口径（#121：跨源比较先归一），如实报
    if len(sources) > 1:
        return {
            "ok": False,
            "degenerate": None,
            "n": n,
            "n_missing": n_missing,
            "min_required": MIN_POINTS_FOR_ASSESSMENT,
            "errors": [f"值列来源混用 {sorted(sources)}（跨口径比较禁止，"
                       "criteria §一值列优先级要求单口径）"],
        }
    value_source = sources.pop()

    mean = statistics.fmean(values)
    std = statistics.pstdev(values)  # 总体标准差（ddof=0，预声明）
    mean_abs = abs(mean)
    rel_std: float | None = None
    if mean_abs > COST_MEAN_EPS:
        rel_std = std / mean_abs
        rule_a = rel_std < COST_REL_STD_THRESHOLD
        rule_a_detail = (f"rel_std={rel_std:.6f} < 阈值 "
                         f"{COST_REL_STD_THRESHOLD}（近常数/常数陷阱指纹）")
    else:
        rule_a = std <= COST_ABS_STD_FLOOR
        rule_a_detail = (f"|mean|={mean_abs:.3e} ≤ {COST_MEAN_EPS} 走绝对分支："
                         f"std={std:.3e} {'≤' if rule_a else '>'} "
                         f"{COST_ABS_STD_FLOOR}（{'全零常数' if rule_a else '近零有起伏'}）")

    unique_vals = _unique_preserve(values)
    unique_ratio = len(unique_vals) / n
    rule_b = unique_ratio <= COST_UNIQUE_RATIO_THRESHOLD
    rule_b_detail = (f"unique_ratio={unique_ratio:.4f} "
                     f"({'≤' if rule_b else '>'} 阈值 "
                     f"{COST_UNIQUE_RATIO_THRESHOLD}，n_unique={len(unique_vals)})")

    degenerate = bool(rule_a or rule_b)
    return {
        "ok": True,
        "degenerate": degenerate,
        "n": n,
        "n_missing": n_missing,
        "value_source": value_source,
        "evidence": {
            "min": min(values),
            "max": max(values),
            "mean": mean,
            "std": std,
            "rel_std": rel_std,
            "unique_ratio": unique_ratio,
            "unique_values": unique_vals[:10],
            "histogram": _histogram(values),
        },
        "rules": {
            "A_rel_std": {"triggered": rule_a, "detail": rule_a_detail},
            "B_unique_ratio": {"triggered": rule_b, "detail": rule_b_detail},
        },
        "errors": [],
    }


def _unique_preserve(values: list[float]) -> list[float]:
    """保序去重（-0.0 与 0.0 视为同值，输出 0.0）。"""
    seen: dict[float, None] = {}
    for v in values:
        seen.setdefault(v + 0.0, None)
    return list(seen)


def _histogram(values: list[float]) -> list[dict[str, Any]]:
    """min-max 区间等宽 5 箱计数（常数分布退化为单箱，如实不画）。"""
    lo, hi = min(values), max(values)
    if hi <= lo:
        return [{"bin": f"[{lo:g}]", "count": len(values)}]
    width = (hi - lo) / HISTOGRAM_BINS
    counts = [0] * HISTOGRAM_BINS
    for v in values:
        idx = min(int((v - lo) / width), HISTOGRAM_BINS - 1)
        counts[idx] += 1
    return [{"bin": f"[{lo + i * width:.6g},{lo + (i + 1) * width:.6g})",
             "count": c} for i, c in enumerate(counts)]


# ─── ② 重规划决策表（criteria §二，按序评估先命中先走） ──────────────────────

def replan_route(assessment: dict[str, Any],
                 context: dict[str, Any] | None = None) -> dict[str, Any]:
    """按预声明决策表产出路由动作 + 逐条可解释 reasons。

    context 键（全部可选）：stage（"fake_batch"/"openems_first_batch"/…）、
    metric_explicit_available（当前口径外是否可换显式统计量）、cost_model
    （escalate_cost_model 的返回值，stage=openems_first_batch 时消费其
    escalate 布尔）。
    """
    context = dict(context or {})
    reasons: list[str] = []
    action = _decide(assessment, context, reasons)
    return {
        "ok": True,
        "action": action,
        "reasons": reasons,
        "stage": context.get("stage"),
        "degenerate": assessment.get("degenerate"),
    }


def _decide(assessment: dict[str, Any], context: dict[str, Any],
            reasons: list[str]) -> str:
    # D1：assessment 本身不 ok → hold（样本不足/口径混用，不瞎动）
    if not assessment.get("ok"):
        for err in assessment.get("errors") or []:
            reasons.append(f"D1 hold：{err}")
        return "hold"

    # D2：openEMS 首批点已回 + 成本模型判升 → 升保真
    if context.get("stage") == "openems_first_batch":
        cost_model = context.get("cost_model") or {}
        if cost_model.get("escalate") is True:
            reasons.append(
                "D2 escalate_fidelity：openEMS 首批点实测成本模型判升"
                f"（benefit_multiple={cost_model.get('benefit_multiple')}）")
            return "escalate_fidelity"
        reasons.append("D2 未触发：stage=openems_first_batch 但成本模型未判升"
                       f"（escalate={cost_model.get('escalate')}），继续代理路由")

    # D3：分布健康 → 继续
    if not assessment.get("degenerate"):
        ev = assessment.get("evidence") or {}
        reasons.append(
            "D3 proceed：cost 分布非退化"
            f"（rel_std={ev.get('rel_std')}，unique_ratio="
            f"{ev.get('unique_ratio')}，n={assessment.get('n')}）")
        return "proceed"

    # D4：口径不是显式统计量名且有显式替代 → 先换判据（零真机成本）
    source = assessment.get("value_source")
    explicit = source in ("metrics.s11_db_min_in_band", "s11_db_min")
    if not explicit and context.get("metric_explicit_available"):
        rules = assessment.get("rules") or {}
        detail = "; ".join(
            f"{k}={v['detail']}" for k, v in rules.items() if v.get("triggered"))
        reasons.append(
            f"D4 switch_metric：value_source={source} 非显式统计量口径，"
            f"退化最可能是统计量口径错（#195 带内 max 陷阱）；触发证据：{detail}；"
            "换 s11_db_min_in_band 显式指标，零真机成本")
        return "switch_metric"

    # D5：口径已显式（或无显式替代）仍退化 → 换采样器
    why = ("值列已走显式统计量口径" if explicit
           else "无可换显式指标（metric_explicit_available 未声明）")
    reasons.append(
        f"D5 switch_sampler：{why}仍退化 = 采样器塌缩在平坦区（#207 平底碗族），"
        "换采样器（如 TPE→LHS 加探索）而非烧真机")
    return "switch_sampler"


# ─── ③ 升保真一阶成本模型（criteria §三） ────────────────────────────────────

def escalate_cost_model(surr_err_rel: float, oe_cost_s: float,
                        hfss_cost_s: float,
                        budget_remaining_s: float) -> dict[str, Any]:
    """一阶成本模型：预期收益=误差缩减×剩余预算 vs HFSS 单点成本。

    escalate 当且仅当三条件全满足（criteria §三）：
    1. surr_err_rel > 0.05（严 >）；
    2. benefit_multiple ≥ 3.0（≥ 宽松界）；
    3. n_affordable ≥ 3。
    另有路由矛盾守卫：hfss_cost_s ≤ oe_cost_s（升到更便宜的 oracle 无意义）。
    """
    errors: list[str] = []
    vals = {"surr_err_rel": surr_err_rel, "oe_cost_s": oe_cost_s,
            "hfss_cost_s": hfss_cost_s, "budget_remaining_s": budget_remaining_s}
    for name, v in vals.items():
        if not _is_finite_number(v):
            errors.append(f"{name}={v!r} 非有限数值")
        elif float(v) < 0:
            errors.append(f"{name}={v!r} 为负")
    if errors:
        return {"ok": False, "escalate": None, "errors": errors}

    err = float(surr_err_rel)
    oe_s = float(oe_cost_s)
    hfss_s = float(hfss_cost_s)
    budget_s = float(budget_remaining_s)

    if hfss_s <= 0:
        return {"ok": False, "escalate": None,
                "errors": [f"hfss_cost_s={hfss_s} ≤ 0，无法构成成本模型"]}

    benefit = err * budget_s
    benefit_multiple = benefit / hfss_s
    n_affordable = int(budget_s // hfss_s)

    cond_err = err > SURR_ERR_REL_MIN
    cond_gain = benefit_multiple >= HFSS_GAIN_MULTIPLE
    cond_afford = n_affordable >= HFSS_MIN_POINTS
    guard_oe = hfss_s <= oe_s if oe_s > 0 else False

    escalate = cond_err and cond_gain and cond_afford and not guard_oe
    reasons = [
        f"判据1 误差地板：surr_err_rel={err:.4f} "
        f"{'>' if cond_err else '≤'} {SURR_ERR_REL_MIN}"
        f"{'' if cond_err else '（代理误差小，升 HFSS 无信息增益）'}",
        f"判据2 收益倍数：benefit=err×budget={benefit:.1f}s，"
        f"benefit_multiple={benefit_multiple:.2f} "
        f"{'≥' if cond_gain else '<'} {HFSS_GAIN_MULTIPLE}",
        f"判据3 可负担批：n_affordable=floor({budget_s:.0f}/{hfss_s:.0f})"
        f"={n_affordable} {'≥' if cond_afford else '<'} {HFSS_MIN_POINTS}",
    ]
    if guard_oe:
        reasons.append(f"守卫否决：hfss_cost_s={hfss_s} ≤ oe_cost_s={oe_s}，"
                       "升到更便宜的 oracle 是路由矛盾")
    if escalate:
        reasons.append("结论 escalate=True：三条件全满足且守卫未触发，"
                       "升 HFSS 路由（预期收益覆盖 ≥3× 单点成本）")
    else:
        reasons.append("结论 escalate=False：继续 openEMS 代理路由")
    return {
        "ok": True,
        "escalate": escalate,
        "evidence": {
            "benefit_s": benefit,
            "benefit_multiple": benefit_multiple,
            "n_affordable_hfss": n_affordable,
            "oe_cost_s": oe_s,
            "hfss_cost_s": hfss_s,
            "budget_remaining_s": budget_s,
            "conditions": {"error_floor": cond_err, "gain_multiple": cond_gain,
                           "affordable": cond_afford, "guard_oe_cheaper": guard_oe},
        },
        "reasons": reasons,
        "errors": [],
    }


# ─── ④ checkpoint 一等对象（幂等重放，criteria §四） ─────────────────────────

def save_replan_checkpoint(path: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    """决策落 JSON 盘（无墙钟/无随机序 → 同 decision 逐字节同文件）。"""
    path = Path(path)  # #140：PathLike 入参第一行收敛
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "version": CHECKPOINT_VERSION,
        "decision": decision,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1),
            encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "path": str(path), "errors": [f"写入失败: {exc}"]}
    return {"ok": True, "path": str(path), "errors": []}


def load_replan_checkpoint(path: str | Path) -> dict[str, Any]:
    """读回 checkpoint；不存在/损坏/schema 不符一律 ok=False 不抛。"""
    path = Path(path)  # #140
    if not path.exists():
        return {"ok": False, "errors": [f"checkpoint 不存在: {path}"]}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "errors": [f"checkpoint 读取/解析失败: {exc}"]}
    if not isinstance(payload, dict) or payload.get("schema") != CHECKPOINT_SCHEMA:
        return {"ok": False, "errors": ["checkpoint schema 不符（非 "
                                        f"{CHECKPOINT_SCHEMA}）"]}
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        return {"ok": False, "errors": ["checkpoint 缺 decision 对象"]}
    return {"ok": True, "decision": decision, "errors": []}
