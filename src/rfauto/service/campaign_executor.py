"""campaign_executor：战役一键闭环执行器（VI-2，SN-2 修正案形态，Phase2 W2-A）。

薄编排层（规则 4 + 铁律 7）：本模块**零数值面**——所有物理数字只出自被
编排的既有确定性内核/求解通道（api/calibration/uq/nf2ff 面），执行循环、
断点续跑、CAS、watchdog、#261 互斥全部复用 pipeline.dag_runner 基座
（**不新写执行循环**，SN-2 修正案明文）。

关键约束（SP 席实测，规格 VI-2 明文）：campaign plan 的 stage entry 是
纸面命令串（campaign_manager 里 ``f"rfauto {kind} {path.name}"``，其 kind
**无对应 CLI 命令**）——本执行器**禁 shell 出 entry**，一律走
CAMPAIGN_EXECUTORS 内部 kind→executor 注册表。

状态机权威账本 = ``<run_dir>/dag.state.json``（节点八态 NODE_STATUSES）；
campaign stage status 是节点态的**映射视图**（防双账本漂移），每次
run_dag 收尾回写 campaign.plan.json（verdict/n_done/n_dead 同源重算）；
apply_event 语义零改动（既有 test_campaign_dag_v2 等全绿为门）。

执行器六件（ground 既有面，缺真机通道的 stage 走 fake 适配器离线演练，
通道映射如实记入 stage 结果不静默）：
- calibrate   → calibration_service.calibrate_surrogate（sampler=stage 适配
  通道映射，fake 系映射 "fake"）；
- prefilter   → inverse_prefilter.prefilter_candidates（目标指标取自配方
  objectives 的标量阈值）；
- tune        → api.start_tune（adapter：hfss 透传、其余→fake 离线演练）；
- tolerance   → uq_service.surrogate_yield_at（样本=上游 calibrate 产物，
  名义点=上游 tune best_params，公差剖面=stage_extra.tolerances 声明）；
- report      → v3_services.generate_enhanced_report（上游 tune run_id，
  best-effort）+ 战役级五要素概览 markdown（确定性、零数字）；
- final_verify（kind=tune+high_adapter）→ 名额内终验：shadow_points 经
  select_shadow_points 确定性消费 + api.run_once 名义终验（参数级影子点
  执行面 v1 未接——run_once 无参数覆盖通道，FU-15 同源，如实注记）。

数据总线：stage 间产物经各节点工作目录的 ``stage_result.json``（基座
artifact manifest 管辖，断点续跑 digest 复核自动覆盖）+ ctx["upstream"]。
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.pipeline.dag_runner import ExecutorFn
from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

#: campaign kind 六件（plan 阶段 kind 词表 + final_verify 修正案名目）。
CAMPAIGN_KINDS: tuple[str, ...] = (
    "calibrate", "prefilter", "tune", "tolerance", "report", "final_verify")

#: 节点工作目录内的阶段结果文件（stage 间数据总线 + 基座产物面载体）。
STAGE_RESULT_FILE = "stage_result.json"

#: journal 之外的人读执行日志（best-effort，#105）。
CAMPAIGN_LOG_FILE = "campaign.log"

#: fake 系适配通道（离线演练映射；映射如实记入 stage 结果，不静默）。
_FAKE_CHANNEL_ADAPTERS = ("fake", "surrogate", "local")

#: stage_result 白名单回写键（防大信封整包落盘；错误/警告原样保留）。
_STAGE_RESULT_KEYS = (
    "ok", "errors", "warning", "verdict", "run_id", "run_dir",
    "samples_path", "n_samples", "best_params", "best_cost", "best_metrics",
    "trials_completed", "rho", "selected", "n_selected", "shortfall",
    "elapsed_s", "candidates", "yield_value",
)


def campaign_kind_of(node: dict[str, Any]) -> str | None:
    """dag 节点 → campaign kind（禁 shell 出 entry 的分发判据，确定性）。

    优先级：node_id==final_verify（plan_campaign 的 entry kind 写 "tune"，
    修正案名目只能按阶段名识别）→ entry 命令串第二词（f"rfauto {kind}"
    固定形态，只解析不执行）→ node_id 本身 ∈ CAMPAIGN_KINDS。识别不出
    返回 None（dispatch 层如实失败，绝不 shell 出 entry）。
    """
    node_id = str(node.get("node_id") or "")
    if node_id == "final_verify":
        return "final_verify"
    tokens = str(node.get("cmd") or "").split()
    if len(tokens) >= 2 and tokens[0] == "rfauto" and tokens[1] in CAMPAIGN_KINDS:
        return tokens[1]
    if node_id in CAMPAIGN_KINDS:
        return node_id
    return None


# ─── stage 结果数据总线 ──────────────────────────────────────────────────────

def _stage_extra(node: dict[str, Any]) -> dict[str, Any]:
    extra = node.get("stage_extra")
    return extra if isinstance(extra, dict) else {}


def _stage_budget(node: dict[str, Any]) -> dict[str, Any]:
    return _stage_extra(node).get("campaign_stage_budget") or {}


def _write_stage_result(node: dict[str, Any], ctx: dict[str, Any],
                        payload: dict[str, Any]) -> str:
    """阶段结果落节点工作目录（基座 manifest 管辖；best-effort #105）。"""
    slim = {k: payload.get(k) for k in _STAGE_RESULT_KEYS
            if payload.get(k) is not None}
    slim.setdefault("stage", str(node.get("node_id") or ""))
    slim.setdefault("campaign_kind", campaign_kind_of(node))
    work_dir = Path(ctx.get("work_dir") or ".")
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / STAGE_RESULT_FILE
    path.write_text(
        json.dumps(slim, ensure_ascii=False, indent=1, sort_keys=True,
                   default=str),
        encoding="utf-8")
    return STAGE_RESULT_FILE


def _read_upstream_stage_result(ctx: dict[str, Any],
                                campaign_kind: str) -> dict[str, Any] | None:
    """读上游指定 campaign kind 节点的 stage_result（无如实返回 None）。

    ctx["upstream"] 是基座期刊条目（无节点原文），kind 识别按上游 node_id
    （campaign_kind_of 的 node_id 词表支路）；自定义阶段名识别不出=None，
    消费方如实失败不猜。
    """
    for dep, entry in (ctx.get("upstream") or {}).items():
        entry = entry if isinstance(entry, dict) else {}
        if campaign_kind_of({"node_id": str(dep), "cmd": ""}) != campaign_kind:
            continue
        base = Path(str(entry.get("artifact_run_dir") or ""))
        path = base / STAGE_RESULT_FILE
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


# ─── 执行器六件（ground 既有面；全部薄编排零数值面）───────────────────────────

def _exec_result(ok: bool, *, outputs: list[str] | None = None,
                 wall_s: float = 0.0, message: str = "") -> dict[str, Any]:
    """ExecutorFn 契约结果单一出口（dict() 构造——执行器协议面，非 service
    信封；消费方=基座 _normalize_executor_result）。"""
    return dict(ok=bool(ok), outputs=list(outputs or []),
                wall_s=float(wall_s or 0.0), message=str(message))


def _exec_calibrate(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    extra = _stage_extra(node)
    recipe = str(extra.get("campaign_recipe") or "")
    if not recipe:
        return _exec_result(
            False, message="节点缺 campaign_recipe 指针（plan 注入面缺失）")
    adapter = str(extra.get("adapter") or "fake")
    sampler = "fake" if adapter in _FAKE_CHANNEL_ADAPTERS else adapter
    from rfauto.service.calibration_service import calibrate_surrogate

    raw = calibrate_surrogate(recipe, sampler=sampler)
    outputs = [_write_stage_result(node, ctx, {**raw, "adapter_channel":
                                               f"{adapter}->{sampler}"})]
    return _exec_result(
        bool(raw.get("ok")), outputs=outputs,
        wall_s=float(raw.get("elapsed_s") or 0.0),
        message=(f"calibrate verdict={raw.get('verdict', '?')} "
                 f"n_samples={raw.get('n_samples', '?')} "
                 f"（通道 {adapter}->{sampler}）"))


def _exec_prefilter(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    extra = _stage_extra(node)
    recipe = str(extra.get("campaign_recipe") or "")
    if not recipe:
        return _exec_result(
            False, message="节点缺 campaign_recipe 指针（plan 注入面缺失）")
    import yaml

    with open(recipe, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f) or {}
    targets: dict[str, float] = {}
    for obj in recipe_data.get("objectives") or []:
        value = (obj or {}).get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            targets[str(obj.get("metric"))] = float(value)
    if not targets:
        return _exec_result(
            False, message="配方 objectives 无标量阈值，prefilter 无目标指标"
                           "（如实失败不硬凑）")
    from rfauto.service.inverse_prefilter import prefilter_candidates

    raw = prefilter_candidates(recipe, targets)
    n_candidates = raw.get("n_candidates", len(raw.get("candidates") or []))
    outputs = [_write_stage_result(node, ctx, {
        **raw,
        "candidates": [c.get("params") for c in (raw.get("candidates") or [])
                       if isinstance(c, dict)],
        "adapter_channel": f"{extra.get('adapter')}->fake",
    })]
    return _exec_result(bool(raw.get("ok")), outputs=outputs,
                        message=f"prefilter n_candidates={n_candidates}")


def _exec_tune(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    extra = _stage_extra(node)
    recipe = str(extra.get("campaign_recipe") or "")
    if not recipe:
        return _exec_result(
            False, message="节点缺 campaign_recipe 指针（plan 注入面缺失）")
    adapter = str(extra.get("adapter") or "fake")
    channel = "hfss" if adapter == "hfss" else "fake"
    try:
        max_trials = int(_stage_budget(node).get("stage_budget") or 30)
    except (TypeError, ValueError):
        max_trials = 30
    model = str(extra.get("campaign_model") or "campaign")
    study = f"campaign-{model}-{extra.get('campaign_stage', node.get('node_id'))}"
    from rfauto.service.api import start_tune

    raw = start_tune(recipe, adapter_name=channel, max_trials=max_trials,
                     study_name=study)
    outputs = [_write_stage_result(node, ctx, {**raw, "adapter_channel":
                                               f"{adapter}->{channel}"})]
    return _exec_result(
        bool(raw.get("ok")), outputs=outputs,
        wall_s=float(raw.get("elapsed_s") or 0.0),
        message=(f"tune best_cost={raw.get('best_cost', '?')} "
                 f"trials={raw.get('trials_completed', '?')} "
                 f"（通道 {adapter}->{channel}）"))


def _exec_tolerance(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    extra = _stage_extra(node)
    tolerances = {str(k): float(v) for k, v in
                  (extra.get("tolerances") or {}).items()
                  if isinstance(v, (int, float)) and not isinstance(v, bool)}
    calib = _read_upstream_stage_result(ctx, "calibrate") or {}
    samples_path = str(calib.get("samples_path")
                       or (Path(calib.get("run_dir") or "") / "calibration"
                           / "samples.json"))
    tune_res = _read_upstream_stage_result(ctx, "tune") or {}
    nominal = dict(tune_res.get("best_params") or {})
    if not Path(samples_path).is_file():
        return _exec_result(
            False, message=f"校准样本不存在: {samples_path}（上游 calibrate "
                           "产物缺失，如实失败）")
    if not nominal:
        return _exec_result(
            False, message="名义点为空（上游 tune 无 best_params，如实失败）")
    if not tolerances:
        return _exec_result(
            False, message="stage_extra.tolerances 未声明公差剖面（v1 不猜，"
                           "如实失败；声明形态=stage 附加字段 k=σ 值）")
    from rfauto.service.uq_service import surrogate_yield_at

    raw = surrogate_yield_at(samples_path, tolerances, nominal)
    outputs = [_write_stage_result(node, ctx, raw)]
    yield_value = raw.get("yield", raw.get("yield_value", "?"))
    return _exec_result(bool(raw.get("ok")), outputs=outputs,
                        message=f"tolerance yield={yield_value}")


def _exec_report(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    extra = _stage_extra(node)
    campaign_dir = Path(str(extra.get("campaign_dir") or "."))
    tune_res = _read_upstream_stage_result(ctx, "tune") or {}
    run_id = str(tune_res.get("run_id") or "")
    lines = ["# 战役报告（五要素概览）", "",
             f"- 战役目录: {campaign_dir}",
             f"- 精算 run_id: {run_id or '（不可得，如实标注）'}",
             "", "## ①收敛/②Pareto/③top-3 S 参数/④基线偏差",
             (f"  详见精算 run 报告: {run_id}" if run_id
              else "  精算 run 不可得（上游 tune 未交付 run_id），如实留空"),
             "", "## ⑤结论与档案",
             "- 战役阶段状态权威账本=本目录 dag.state.json（节点八态），",
             "  campaign.plan.json 的 stage status 为其映射视图。",
             ""]
    # best-effort 富报告（#105）：run_id 可得时挂既有五要素报告生成面
    html_path = ""
    if run_id:
        try:
            from rfauto.service.v3_services import generate_enhanced_report

            html_path = str(campaign_dir / "campaign_report.html")
            generate_enhanced_report(run_id, output=html_path)
        except Exception as exc:
            lines.append(f"- 富报告生成失败（不阻塞概览，#105）: {exc}")
    report_rel = "campaign_report.md"
    work_dir = Path(ctx.get("work_dir") or ".")
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / report_rel).write_text("\n".join(lines), encoding="utf-8")
    with contextlib.suppress(OSError):
        (campaign_dir / report_rel).write_text("\n".join(lines),
                                               encoding="utf-8")

    _write_stage_result(node, ctx, dict(ok=True, run_id=run_id,
                                        report_html=html_path))
    return _exec_result(True, outputs=[report_rel],
                        message=f"report 概览落盘（run_id={run_id or '无'}）")


def _exec_final_verify(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    extra = _stage_extra(node)
    recipe = str(extra.get("campaign_recipe") or "")
    adapter = str(extra.get("adapter") or "hfss")
    channel = "hfss" if adapter == "hfss" else "fake"
    shadow_cfg = dict(extra.get("shadow_points") or {})
    tune_res = _read_upstream_stage_result(ctx, "tune") or {}
    points: list[dict[str, Any]] = []
    if tune_res.get("best_params"):
        points.append({"params": tune_res["best_params"],
                       "cost": tune_res.get("best_cost")})
    n_points = int(shadow_cfg.get("n_points") or 0)
    selection: dict[str, Any] = {"n_points": n_points}
    if n_points > 0 and points:
        from rfauto.service.campaign_manager import select_shadow_points

        selection = select_shadow_points(
            points, n_points=n_points,
            top_k=int(shadow_cfg.get("top_k") or 1),
            min_norm_dist=float(shadow_cfg.get("min_norm_dist") or 0.3))
    raw: dict[str, Any] = {"ok": True, "adapter_channel": f"{adapter}->{channel}",
                           "shadow_selection": selection}
    note = ""
    if channel == "hfss":
        from rfauto.service.api import run_once

        raw = {**run_once(recipe, adapter_name="hfss"),
               "adapter_channel": f"{adapter}->hfss"}
        note = "（真机终验）"
    else:
        note = "（离线演练通道；参数级影子点复核执行面 v1 未接——run_once 无" \
               "参数覆盖通道，FU-15 同源，followUp 登记）"
    outputs = [_write_stage_result(node, ctx, raw)]
    n_shadow = selection.get("n_selected", 0)
    shortfall = selection.get("shortfall", 0)
    return _exec_result(
        bool(raw.get("ok")), outputs=outputs,
        wall_s=float(raw.get("elapsed_s") or 0.0),
        message=f"final_verify n_shadow={n_shadow} "
                f"shortfall={shortfall}{note}")


#: kind→executor 注册表（六件；测试/编排方可在 run_campaign(executors=)
#: 传同形 dict 整表覆盖——注入缝，缺省用本表）。
CAMPAIGN_EXECUTORS: dict[str, ExecutorFn] = {
    "calibrate": _exec_calibrate,
    "prefilter": _exec_prefilter,
    "tune": _exec_tune,
    "tolerance": _exec_tolerance,
    "report": _exec_report,
    "final_verify": _exec_final_verify,
}


# ─── DAG 派发层（campaign kind → dag kind 四类全覆盖）────────────────────────

def _dag_executors(campaign_executors: dict[str, ExecutorFn]
                   ) -> dict[str, ExecutorFn]:
    """dag 四类节点 kind → campaign dispatch（零 shell 出 entry）。"""

    def _dispatch(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        from rfauto.pipeline.dag_runner import NodeAbortedError

        kind = campaign_kind_of(node)
        impl = campaign_executors.get(kind) if kind else None
        if impl is None:
            return _exec_result(
                False, message=(f"无法识别 campaign kind（node_id="
                                f"{node.get('node_id')!r} cmd="
                                f"{str(node.get('cmd') or '')!r}）——entry 是"
                                "纸面命令串，禁 shell 出（规格 VI-2）"))
        try:
            return impl(node, ctx)
        except NodeAbortedError:
            raise
        except Exception as exc:  # 执行器异常=节点失败（不吞不猜，注记原因）
            return _exec_result(False, message=f"{kind} executor 异常: {exc}")

    from rfauto.core.compose.dag_schema import NODE_KINDS

    return {dag_kind: _dispatch for dag_kind in NODE_KINDS}


# ─── 计划上下文注入与状态视图映射 ─────────────────────────────────────────────

def _inject_plan_context(plan_v2: dict[str, Any], run_dir: Path) -> None:
    """把 plan 级指针注入各 dag 节点 stage_extra（executor 的数据来源）。

    另：nodes_from_stages 把 stage 预算数值放进 budget.timeout_s——其语义
    是"阶段预算"（trials/样本数）不是秒，此处显式搬移到 stage_extra.
    campaign_stage_budget 并把 timeout_s 置 None，防基座误当秒判 PARTIAL
    （仅对出自 stages 包装的节点生效：以 stage_extra 先在性判别）。
    """
    for node in (plan_v2.get("dag") or {}).get("nodes") or []:
        from_stages = "stage_extra" in node
        extra = node.setdefault("stage_extra", {})
        extra.setdefault("campaign_recipe", str(plan_v2.get("recipe") or ""))
        extra.setdefault("campaign_model", str(plan_v2.get("model") or ""))
        extra.setdefault("campaign_dir", str(run_dir))
        extra.setdefault("campaign_stage", str(node.get("node_id") or ""))
        if from_stages:
            budget = node.get("budget") or {}
            ts = budget.get("timeout_s")
            if isinstance(ts, (int, float)) and not isinstance(ts, bool):
                extra.setdefault("campaign_stage_budget", {"stage_budget": ts})
                budget["timeout_s"] = None
                node["budget"] = budget


#: 节点八态 → campaign stage 视图态（apply_event 词表；inconclusive 不是
#: 终态——续跑重执行给判定再机会，映射回 pending 如实注记）。
_NODE_TO_STAGE_VIEW: dict[str, str] = {
    "done": "done",
    "partial": "done",       # 超预算 PARTIAL 入库=结果采信（注记如实）
    "failed": "failed",
    "aborted": "aborted",
    "skipped": "skipped",
    "inconclusive": "pending",
    "running": "running",
    "pending": "pending",
}


def _stage_view_from_nodes(plan_v2: dict[str, Any],
                           node_entries: dict[str, Any]) -> list[dict[str, Any]]:
    """dag.state.json（权威账本）→ campaign stage status 映射视图。"""
    view: list[dict[str, Any]] = []
    for stage in plan_v2.get("stages") or []:
        name = str((stage or {}).get("stage") or "")
        entry = node_entries.get(name) or {}
        node_status = str(entry.get("status") or "pending")
        view_status = _NODE_TO_STAGE_VIEW.get(node_status, "pending")
        note = str(stage.get("note") or "")
        if node_status == "partial" and "超预算 PARTIAL 入库" not in note:
            note = (note + " | 超预算 PARTIAL 入库（视图=done，基座注记）").strip(" |")
        if node_status == "inconclusive":
            note = (note + " | 节点证据不可判（视图=pending，续跑重判定）").strip(" |")
        stage["status"] = view_status
        if note:
            stage["note"] = note
        view.append({"stage": name, "status": view_status,
                     "node_status": node_status})
    return view


def _recount_verdict(plan_v2: dict[str, Any], run_verdict: str) -> None:
    """视图回写 verdict/n_done/n_dead（词表与 apply_event 同源，零新态）。"""
    stages = plan_v2.get("stages") or []
    n_done = sum(1 for s in stages if s.get("status") == "done")
    n_dead = sum(1 for s in stages
                 if s.get("status") in ("failed", "aborted"))
    plan_v2["n_done"] = n_done
    plan_v2["n_dead"] = n_dead
    plan_v2["verdict"] = run_verdict


# ─── 主入口 ──────────────────────────────────────────────────────────────────

def run_campaign(
    plan_path: str,
    *,
    run_dir: str | None = None,
    dry_run: bool = False,
    detach: bool = False,
    resume: bool = False,
    executors: dict[str, ExecutorFn] | None = None,
    solve_lock_path: str | None = None,
    lock_max_wait_s: float = 0.0,
    cache_dir: str | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """战役一键闭环（load_plan→wrap_plan_v2→run_dag 基座→视图回写）。

    - run_dir 缺省=计划所在目录（期刊/锁/报告/计划视图同目录；resume 天然
      稳定——同 plan 同 run_dir，断点续跑由基座 _resume_decision 承担）；
    - ``resume`` 旗标为显式意图声明（续跑语义期刊内建，重调同参即续跑）；
    - ``lock_max_wait_s=0``：同 run_dir 并发第二实例占即拒（信封 errors 含
      锁路径 lock 字样，CLI rc≠0）；
    - ``executors``：kind→ExecutorFn 整表覆盖（编排方/测试注入缝），缺省
      CAMPAIGN_EXECUTORS 六件；entry 纸面命令串任何路径都不 shell 出。
    """
    from rfauto.service.campaign_manager import load_plan, save_plan

    loaded = load_plan(plan_path)
    if not loaded.get("ok"):
        return error_envelope(loaded.get("errors") or ["战役计划不可读"])
    plan = loaded["plan"]
    plan_file = Path(str(loaded.get("path") or ""))
    run_path = Path(run_dir) if run_dir else plan_file.parent
    run_path.mkdir(parents=True, exist_ok=True)

    plan_v2 = wrap_campaign_plan(plan)
    _inject_plan_context(plan_v2, run_path)

    if dry_run:
        return _dry_run_preview(plan_v2, run_path, solve_lock_path)

    if detach:
        # detach 后台通道 v1 如实降级（规格明示"可二步"；jobs 登记面+心跳
        # 自尽范式内化为 followUp，不静默不假装后台）。
        return skipped_envelope(
            "detach 后台通道 v1 未接线（followUp 登记：jobs 登记面+"
            "campaign_wait_launch 心跳自尽范式内化待批）；本调用未执行任何"
            "战役阶段（零副作用）",
            plan_path=str(plan_file), run_dir=str(run_path),
            resume=resume)

    table = dict(executors) if executors is not None else dict(CAMPAIGN_EXECUTORS)
    missing = sorted(set(CAMPAIGN_KINDS) - set(table))
    if missing:
        return error_envelope(
            [f"executor 注册表缺 kind: {missing}（六件必须全覆盖）"])
    unknown = sorted(set(table) - set(CAMPAIGN_KINDS))
    if unknown:
        return error_envelope(
            [f"executor 注册表含未知 kind: {unknown}（词表 "
             f"{list(CAMPAIGN_KINDS)}）"])

    from rfauto.pipeline.dag_runner import DAG_STATE_FILE, run_dag
    from rfauto.service.campaign_manager import PLAN_FILE_NAME

    log_fn = log or _make_run_log(run_path)
    # 运行前视图：verdict=RUNNING（UI 队列页对运行中战役显示 running 行）
    if plan_v2.get("verdict") not in ("RUNNING",):
        plan_v2["verdict"] = "RUNNING"
        with contextlib.suppress(OSError):
            save_plan(plan_v2, plan_file.parent)

    result = run_dag(
        plan_v2.get("dag") or {"nodes": []}, run_path, _dag_executors(table),
        cache_dir=cache_dir,
        solve_lock_path=(Path(solve_lock_path) if solve_lock_path else None),
        lock_max_wait_s=float(lock_max_wait_s),
        log=log_fn)
    if not (run_path / DAG_STATE_FILE).is_file():
        # run 级失败（锁被占/计划非法）：期刊未动，如实透传锁路径（含 lock 字样）
        errs = list(result.get("errors") or [])
        if not errs:
            errs = [f"DAG 期刊未生成（执行基座未落账本）: {run_path}"]
        return error_envelope(
            errs, run_dir=str(run_path), verdict=result.get("verdict", ""))

    # 权威账本（dag.state.json）→ stage 映射视图回写计划文件（防双账本）
    state = json.loads((run_path / DAG_STATE_FILE).read_text(encoding="utf-8"))
    view = _stage_view_from_nodes(plan_v2, state.get("nodes") or {})
    _recount_verdict(plan_v2, str(result.get("verdict") or "RUNNING"))
    save_plan(plan_v2, plan_file.parent)
    fields = dict(
        plan_path=str(plan_file), run_dir=str(run_path),
        state_path=str(run_path / DAG_STATE_FILE),
        plan_file_name=PLAN_FILE_NAME,
        verdict=plan_v2["verdict"],
        n_done=plan_v2["n_done"], n_dead=plan_v2["n_dead"],
        n_hit=result.get("n_hit"), n_recompute=result.get("n_recompute"),
        stage_view=view,
        statuses=result.get("statuses") or {},
        resume=resume)
    if not result.get("ok"):
        # 战役未完成（ABORTED/RUNNING）：词表与 apply_event 同源，rc≠0 面
        n_dead = int(plan_v2.get("n_dead") or 0)
        return error_envelope(
            [f"战役未完成: verdict={plan_v2['verdict']}"
             + (f"（failed/aborted 阶段 {n_dead} 个）" if n_dead else "")
             + f"——权威账本 {run_path / DAG_STATE_FILE}"],
            **fields)
    return ok_envelope(**fields)


def wrap_campaign_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """plan → v2 包装（薄转发 campaign_manager.wrap_plan_v2，显式点名）。"""
    from rfauto.service.campaign_manager import wrap_plan_v2

    return wrap_plan_v2(plan)


def _make_run_log(run_path: Path) -> Callable[[str], None]:
    path = run_path / CAMPAIGN_LOG_FILE

    def _log(msg: str) -> None:
        # 观测面 best-effort（#105）：日志写失败不阻塞执行主路径
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{msg}\n")
        except OSError:
            pass

    return _log


def _dry_run_preview(plan_v2: dict[str, Any], run_path: Path,
                     solve_lock_path: str | None) -> dict[str, Any]:
    """dry-run：拓扑序+各阶段预算+互斥预览（零执行：零子进程零 service 调用）。

    只读 core schema 的构造期解析（parse_dag，纯函数非执行面）+计划元数据
    拼装；任何 executor/service/子进程都不会被触达（探针测试钉）。
    """
    from rfauto.core.compose.dag_schema import parse_dag
    from rfauto.pipeline.dag_runner import (
        DAG_RUN_LOCK_NAME,
        default_solve_lock_path,
    )

    parsed = parse_dag(plan_v2.get("dag") or {"nodes": []})
    if not parsed.get("ok"):
        return error_envelope(list(parsed.get("errors") or ["DAG 计划非法"]))
    stages: list[dict[str, Any]] = []
    for stage in plan_v2.get("stages") or []:
        budget = stage.get("budget")
        stages.append({
            "stage": str(stage.get("stage") or ""),
            "kind": str(stage.get("kind") or ""),
            "adapter": str(stage.get("adapter") or ""),
            "budget": budget,
            "depends_on": [str(d) for d in (stage.get("depends_on") or [])],
            "license_gated": bool(stage.get("license_gated")),
        })
    lock = Path(solve_lock_path) if solve_lock_path else default_solve_lock_path()
    license_gated = [s["stage"] for s in stages if s["license_gated"]]
    return ok_envelope(
        dry_run=True, run_dir=str(run_path),
        order=list(parsed["order"]),
        stages=stages,
        license_gated_stages=license_gated,
        mutex_preview={
            "run_instance_lock": str(run_path / DAG_RUN_LOCK_NAME),
            "solve_machine_lock": str(lock),
            "policy": "同 run_dir 单实例占即拒；solve 类节点过机器互斥（#261）",
        },
        verdict="DRY_RUN")


__all__ = [
    "CAMPAIGN_EXECUTORS",
    "CAMPAIGN_KINDS",
    "CAMPAIGN_LOG_FILE",
    "STAGE_RESULT_FILE",
    "campaign_kind_of",
    "run_campaign",
    "wrap_campaign_plan",
]
