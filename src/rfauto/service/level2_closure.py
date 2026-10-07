"""level2_closure：level2 设计链链尾闭环三步接线（AD-8，round15 §五）。

规格：「level2 链尾接 certify 证书 + 锚注册回写 + 失败 replan 重路由」
（P1/L）。现状（调研 §五）：certify_design 623 行独立未进主链、replan
只服务升保真、锚回写无通道——本模块把三步接成链尾闭包包络，消费
design_chain 的 record（JSON 契约），自身零数值产出（铁律 7）：

  ① certify 证书：以链 record 的综合参数为中心，构造公差盒样本集
     （fake 闭式评估，确定性 seed），委托 service.certify_design 区间
     传播内核出三值证书（PASS/FAIL/UNKNOWN）。certify_design 只支持
     单阈值 op（max_below/min_above）——MEAN_WITHIN 目标（atten_pi）
     按 [lo,hi] 区间语义**忠实分解为同指标的两条单阈证书**（≥lo 且 ≤hi），
     不改 certify 内核、不引入第三种判据。
  ② 锚注册回写草案：锚注册表**运行时只读**（infra/anchors_store 头注：
     落盘回填走人工 commit，Agent 写面隔离铁律 6）——本步只把链内锚
     修正证据整理成 anchors/v1 形态的回填**草案**落 runs/（人类可
     diff/commit），并守卫拒绝写向 knowledge/ 注册表目录。
  ③ 失败 replan 重路由：链 error → 确定性重跑路由（keyword 回退通道）；
     kickoff 成本轨迹 ≥3 点 → 复用 replan_service 的退化判定+决策表
     （判据单源，不另立阈值）；其余如实 hold。

写面纪律：本模块全部落盘只在 runs/level2_closure/（或调用方显式
out_dir），不触碰 src/、knowledge/、configs/；best-effort 单步失败
不拖垮其余两步（#105，envelope 逐步留 errors）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.level2_design import (
    _RESONANT_FAMILIES,
    KICKOFF_ATTEN_TOL_DB,
    KICKOFF_REQUIREMENT_KEYS,
    KICKOFF_RL_TARGET_DB,
    kickoff_evaluate_fn,
)

CLOSURE_SCHEMA = "rfauto-level2-closure-v1"

#: 缺省落盘目录（runs/ 实验区；调用方可显式覆盖）。
CLOSURE_DIR = Path("runs") / "level2_closure"

#: 公差盒样本数（certify_design 下限 5；9 点=中心+LHS 8 点，秒级零负担）。
CERTIFY_N_SAMPLES_DEFAULT = 9

#: 谐振/平坦族公差盒相对半宽（与 certify_design tolerance_pct 同量纲基准：
#: 盒=中心 ×(1±tolerance_pct)，certify 调用侧 tolerance_pct=1.0 使
#: Δx 恰为整盒半宽——区间传播不缩水）。
CERTIFY_TOLERANCE_PCT_DEFAULT = 0.02


# ─── ① certify 证书 ──────────────────────────────────────────────────────────

def certify_objectives(family: str, f0_ghz: float,
                       requirements: Mapping[str, float] | None = None,
                       ) -> list[dict[str, Any]]:
    """族 spec → certify 兼容目标（全部单阈值 op； atten_pi 区间二分解）。"""
    from rfauto.service.level2_design import _freq_span

    band = list(_freq_span(family, float(f0_ghz))[:2])
    if family in _RESONANT_FAMILIES:
        return [{"metric": "s11_db_min", "op": "max_below",
                 "value": KICKOFF_RL_TARGET_DB, "band": band}]
    if family == "atten_pi":
        req = dict(requirements or {})
        atten = float(req.get("atten_db") or 10.0)
        return [
            {"metric": "s21_db", "op": "min_above",
             "value": -(atten + KICKOFF_ATTEN_TOL_DB), "band": band},
            {"metric": "s21_db", "op": "max_below",
             "value": -(atten - KICKOFF_ATTEN_TOL_DB), "band": band},
        ]
    return [{"metric": "s11_db", "op": "max_below",
             "value": KICKOFF_RL_TARGET_DB, "band": band}]


def build_certify_samples(record: Mapping[str, Any], *,
                          tolerance_pct: float = CERTIFY_TOLERANCE_PCT_DEFAULT,
                          n_samples: int = CERTIFY_N_SAMPLES_DEFAULT,
                          seed: int = 42) -> dict[str, Any]:
    """链 record → certify_design 样本集 JSON（确定性，零真机）。

    公差盒 = 非需求量综合参数 ×(1±tolerance_pct)（需求量键剔除，同
    KICKOFF_REQUIREMENT_KEYS 口径：用户要求的量不是设计变量）；样本 =
    中心 + LHS（include 中心，seed 固定逐位可复现），指标/成本全部出自
    fake 闭式评估与 SpecEvaluator（铁律 7）。
    """
    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.optimization.sample_design import lhs_points

    family = str(record.get("family") or "")
    if not family:
        return error_envelope(["record 缺 family"])
    params = {str(k): float(v) for k, v in
              (record.get("synthesis_params") or {}).items()}
    if not params:
        return error_envelope(["record 缺 synthesis_params"])
    requirements = dict((record.get("intent") or {}).get("requirements")
                        or {})
    f0 = float(params.get("f0_ghz") or requirements.get("f0_ghz") or 0.0)
    if f0 <= 0:
        return error_envelope(["f0_ghz 不可得（params/requirements 均缺）"])
    center = {k: v for k, v in params.items()
              if k not in KICKOFF_REQUIREMENT_KEYS and v > 0}
    if not center:
        return error_envelope(["无可认证参数（剔除需求量键后为空）"])
    tol = float(tolerance_pct)
    if not (0.0 < tol < 1.0):
        return error_envelope([f"tolerance_pct 须在 (0,1)：{tol}"])
    bounds = {k: (v * (1.0 - tol), v * (1.0 + tol)) for k, v in center.items()}
    fixed = {k: v for k, v in params.items() if k in KICKOFF_REQUIREMENT_KEYS}
    obj_dicts = certify_objectives(family, f0, requirements)
    objectives = [Objective(**o) for o in obj_dicts]
    evaluate = kickoff_evaluate_fn(family, f0, objectives, fixed)
    points = lhs_points(bounds, max(int(n_samples), 5), seed=int(seed),
                        include=[dict(center)])["points"]
    samples: list[dict[str, Any]] = []
    failures: list[str] = []
    for pt in points:
        try:
            metrics = evaluate(dict(pt))
        except Exception as exc:  # 单点失败留痕不计样本（fake 闭式不应发生）
            failures.append(f"{type(exc).__name__}: {exc}")
            continue
        samples.append({
            "params": {k: float(v) for k, v in pt.items()},
            "metrics": {k: float(v) for k, v in metrics.items()
                        if isinstance(v, (int, float))},
            "cost": float(SpecEvaluator.evaluate_objectives(metrics, objectives)),
        })
    if len(samples) < 5:
        return error_envelope(
            [f"可用样本不足 5（失败 {len(failures)}）",
                                        *failures[:3]],
        )
    return ok_envelope(
        family=family,
        f0_ghz=f0,
        samples=samples,
        bounds={k: [float(lo), float(hi)] for k, (lo, hi) in bounds.items()},
        objectives=obj_dicts,
        tolerance_pct=tol,
        seed=int(seed),
        n_failures=len(failures),
        errors=[],
    )


def certify_chain_design(record: Mapping[str, Any], *,
                         tolerance_pct: float = CERTIFY_TOLERANCE_PCT_DEFAULT,
                         n_samples: int = CERTIFY_N_SAMPLES_DEFAULT,
                         seed: int = 42,
                         out_dir: str | Path | None = None,
                         ) -> dict[str, Any]:
    """链尾①：公差盒样本集 → certify_design 三值证书（委托确定性内核）。

    certify_design 的 tolerance_pct 以其样本 bounds 跨度为基准——本步
    bounds 已是公差盒，故传 1.0 让 Δx 恰为整盒半宽（区间不缩水）。
    out_dir 给定时样本集落 <out_dir>/certify_samples_<task>.json 留证。
    """
    from rfauto.service.certify_design import certify_design

    built = build_certify_samples(record, tolerance_pct=tolerance_pct,
                                  n_samples=n_samples, seed=seed)
    if not built.get("ok"):
        return {"ok": False, "step": "certify",
                "errors": list(built.get("errors") or [])}
    samples_path: Path | None = None
    if out_dir is not None:
        target = Path(out_dir)
        target.mkdir(parents=True, exist_ok=True)
        tag = str(record.get("id") or built["family"])
        samples_path = target / f"certify_samples_{tag}.json"
        samples_path.write_text(
            json.dumps({k: built[k] for k in
                        ("samples", "bounds", "objectives")},
                       ensure_ascii=False, indent=1, default=str),
            encoding="utf-8")
    params_all = {str(pk): float(pv) for pk, pv in
                  (record.get("synthesis_params") or {}).items()}
    center = {k: v for k, v in params_all.items() if k in built["bounds"]}
    path_used = samples_path or _samples_tmp(built)
    try:
        certificate = certify_design(path_used, center, tolerance_pct=1.0)
    finally:
        if samples_path is None:
            Path(path_used).unlink(missing_ok=True)  # 临时样本集即用即清
    return {"ok": bool(certificate.get("ok")), "step": "certify",
            "family": built["family"], "f0_ghz": built["f0_ghz"],
            "n_samples": len(built["samples"]),
            "tolerance_pct": built["tolerance_pct"], "seed": built["seed"],
            "samples_path": str(samples_path) if samples_path else None,
            "certificate": certificate, "errors": []}


def _samples_tmp(built: Mapping[str, Any]) -> str:
    """无 out_dir 时样本集走临时文件（certify_design 只收路径入参）。"""
    import tempfile

    path = Path(tempfile.gettempdir()) / (
        f"rfauto_level2_certify_{id(built):x}.json")
    path.write_text(
        json.dumps({k: built[k] for k in ("samples", "bounds", "objectives")},
                   ensure_ascii=False, default=str),
        encoding="utf-8")
    return str(path)


# ─── ② 锚注册回写草案 ────────────────────────────────────────────────────────

def _knowledge_root() -> Path:
    """锚注册表所在目录（守卫基准；来自 infra 单源，不硬编码）。"""
    from rfauto.infra.anchors_store import default_anchors_path

    return Path(default_anchors_path()).parent.resolve()


def anchor_writeback_draft(record: Mapping[str, Any], *,
                           out_dir: str | Path | None = None,
                           ) -> dict[str, Any]:
    """链尾②：锚修正证据 → anchors/v1 形态回填草案（runs/ 落盘，人工 commit）。

    草案动作只两态：update_last_verified（链内锚修正命中且有可算残差）/
    not_applicable（未命中或证据不足，reason 如实）。predicted/residual
    只在 constant_over_f0 注入模式下计算（预测=锚值/注入后键值，残差=
    实测谷位−预测）；其余模式无同量纲预测，证据只留 Δ 包络（不猜）。
    """
    correction = record.get("anchor_correction")
    if not isinstance(correction, Mapping) or not correction.get("applied"):
        reason = (str((correction or {}).get("reason"))
                  if isinstance(correction, Mapping) else
                  "record 无 anchor_correction（enable_anchor_correction 未开）")
        return ok_envelope(
            step="anchor_writeback",
            action="not_applicable",
            reason=reason,
            draft=None,
            draft_path=None,
            errors=[],
        )

    injection = correction.get("injection") or None
    metrics = record.get("metrics") or {}
    measured = metrics.get("f_dip_ghz")
    predicted = None
    if injection and correction.get("value") and injection.get("new_value"):
        predicted = float(correction["value"]) / float(injection["new_value"])
    residual = (float(measured) - predicted
                if predicted is not None and measured is not None else None)
    evidence: dict[str, Any] = {
        "source_task": record.get("id"),
        "measured_f_dip_ghz": measured,
        "predicted_f_dip_ghz": predicted,
        "residual_ghz": residual,
        "correction": {k: correction.get(k) for k in
                       ("anchor_id", "version", "value", "unit", "delta",
                        "delta_kind", "band", "band_rel", "domain_ok")},
    }
    entry: dict[str, Any] = {
        "anchor_id": correction.get("anchor_id"),
        "current_version": correction.get("version"),
        "proposed_action": "update_last_verified",
        "evidence": evidence,
        "generated_by": "service/level2_closure.anchor_writeback_draft",
        "status": "draft_pending_human_review",
    }
    draft = {
        "schema": "anchors/v1",
        "draft": True,
        "draft_note": "锚注册表运行时只读（infra/anchors_store 口径）：本草案"
                      "只落 runs/ 供人工 diff/commit，注册表本体零写入",
        "anchors": [entry],
    }
    draft_path: str | None = None
    if out_dir is not None:
        out = Path(out_dir)
        resolved = out.resolve()
        kroot = _knowledge_root()
        if kroot == resolved or kroot in resolved.parents:
            return {"ok": False, "step": "anchor_writeback",
                    "errors": [f"out_dir 不得指向锚注册表目录（{kroot}）"]}
        out.mkdir(parents=True, exist_ok=True)
        import yaml

        tag = str(record.get("id") or record.get("family") or "task")
        path = out / f"anchor_writeback_{tag}.draft.yaml"
        path.write_text(
            yaml.safe_dump(draft, allow_unicode=True, sort_keys=True),
            encoding="utf-8")
        draft_path = str(path)
    return ok_envelope(step="anchor_writeback", action="update_last_verified", draft=draft, draft_path=draft_path, errors=[])


# ─── ③ 失败 replan 重路由 ────────────────────────────────────────────────────

def replan_after_chain(record: Mapping[str, Any], *,
                       context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """链尾③：失败/退化 → 确定性重路由（判据单源复用 replan_service）。

    分支（预声明）：
    - record.error → rerun_chain（keyword 回退通道重跑；链内 parse 已内建
      回退，此路由针对上游通道故障恢复后的重放）；
    - kickoff 成本轨迹 ≥3 点 → assess_cost_degeneration + replan_route
      （switch_metric/switch_sampler/proceed/escalate_fidelity/hold 全沿
      replan_service 决策表，本层不另立阈值）；
    - 其余（kickoff failed 无轨迹等）→ inspect_kickoff_error/hold 如实。
    """
    from rfauto.service.replan_service import (
        assess_cost_degeneration,
        replan_route,
    )

    error = record.get("error")
    if error:
        return ok_envelope(
            step="replan",
            action="rerun_chain",
            channel="keyword_fallback",
            reasons=[f"链路 error（{error}）——确定性重跑路由："
                            "keyword 回退通道（LLM 通道失灵不阻塞重设计）"],
            errors=[],
        )
    kickoff = record.get("kickoff") or {}
    trace = [float(c) for c in (kickoff.get("real_cost_trace") or [])
             if isinstance(c, (int, float))]
    if len(trace) >= 3:
        assessment = assess_cost_degeneration([{"cost": c} for c in trace])
        ctx = {"stage": "level2_closure", "metric_explicit_available": True,
               **dict(context or {})}
        route = replan_route(assessment, ctx)
        return ok_envelope(
            step="replan",
            action=route["action"],
            reasons=list(route["reasons"]),
            degenerate=assessment.get("degenerate"),
            value_source=assessment.get("value_source"),
            errors=[],
        )
    status = kickoff.get("kickoff_status")
    if status == "failed":
        return ok_envelope(
            step="replan",
            action="inspect_kickoff_error",
            reasons=["kickoff_status=failed 且无成本轨迹——先读 "
                            "kickoff.error 定位（不盲重跑）"],
            errors=[],
        )
    action = "proceed" if record.get("numeric") else "hold"
    return ok_envelope(
        step="replan",
        action=action,
        reasons=[f"无 error 且成本轨迹 {len(trace)} 点（<3 不判退化）——"
                        f"按 record 数值面路由 {action}"],
        errors=[],
    )


# ─── 链尾闭包包络 ────────────────────────────────────────────────────────────

def close_level2_chain(record: Mapping[str, Any], *,
                       out_dir: str | Path | None = CLOSURE_DIR,
                       certify: bool = True,
                       anchor_writeback: bool = True,
                       replan: bool = True,
                       tolerance_pct: float = CERTIFY_TOLERANCE_PCT_DEFAULT,
                       n_samples: int = CERTIFY_N_SAMPLES_DEFAULT,
                       seed: int = 42,
                       ) -> dict[str, Any]:
    """AD-8 三步链尾闭环：design_chain record → {certify, anchor_writeback,
    replan} 包络（单步失败不拖垮其余，envelope 逐步留 errors，永不抛）。

    out_dir 缺省 runs/level2_closure/（样本集与锚回填草案落盘留证）；
    传 None 全程零落盘。三步可用开关单独关闭（缺省全开）。
    """
    envelope: dict[str, Any] = ok_envelope(
        schema_version=CLOSURE_SCHEMA,
        task_id=record.get("id"),
        family=record.get("family"),
        certify=None,
        anchor_writeback=None,
        replan=None,
        errors=[],
    )
    steps: list[tuple[str, bool, Any]] = [
        ("certify", certify, lambda: certify_chain_design(
            record, tolerance_pct=tolerance_pct, n_samples=n_samples,
            seed=seed, out_dir=out_dir)),
        ("anchor_writeback", anchor_writeback, lambda: anchor_writeback_draft(
            record, out_dir=out_dir)),
        ("replan", replan, lambda: replan_after_chain(record)),
    ]
    for name, enabled, fn in steps:
        if not enabled:
            continue
        try:
            envelope[name] = fn()
        except Exception as exc:  # 单步失败留痕不拖垮（#105）
            envelope[name] = {"ok": False, "step": name,
                              "errors": [f"{type(exc).__name__}: {exc}"]}
        if not (envelope[name] or {}).get("ok", False):
            envelope["errors"].append(
                f"{name}: " + "; ".join(
                    str(e) for e in (envelope[name] or {}).get("errors")
                    or ["未启用或无结果"]))
    envelope["ok"] = all(
        (envelope[s] or {}).get("ok", False)
        for s, enabled, _ in steps if enabled)
    return envelope
