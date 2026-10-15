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

stage 级 --remote 发射路由（E62 席 2026-10-08，E-06/PR-15 拆批余件）：
plan stage 键 ``"remote"``（或 plan 级 ``"remote"``/CLI ``--remote`` 作
战役级缺省，stage 声明优先）→ 派发层 ``_route_remote_stage`` 路由——
资源日历窗判定（维护窗 blocked）+ license 预检（fail-skip）+ 五步执行
通道单源复用 remote_service/remote_oe_service（零双实现）；产物/信封/
日志回拉落节点工作目录（座位目录）。SKIP=inconclusive（续跑重探）；
未声明=本机路径零行为变化。recipe-loop 远跑（tune 优化循环整段上服务
器）属 v1 未接线拆批余件（campaign_app/常驻队列/L2 sftp/ADS 远跑），
无座位载荷的 remote 声明如实 SKIP 不假绿。

stage 级 hfss_batch 双模路由缝（2026-10-08，HFSS one-shot batch）：
plan stage 键 ``"hfss_batch"``（str=工程路径 / dict 全参声明，详见
``stage_batch_decl``）→ 派发层 ``_route_batch_stage`` 走
adapters/hfss_batch 一次性批处理求解（每求解一个独立短命 ansysedt
进程，无长驻桌面会话）；未声明=既有会话路径零行为变化（路由缝整体
旁路）。路由顺序：remote 优先 → hfss_batch 次之 → executor 注册表。
"""

from __future__ import annotations

import contextlib
import hashlib
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
#: ge9 审查 P2-1 对账补键：report_html（_exec_report 显式落盘意图）、
#: shadow_selection（final_verify 影子点选择账本）、adapter_channel
#: （模块 docstring 明文"通道映射如实记入 stage 结果"）、yield_rate
#: （surrogate_yield_at 契约键；原白名单 yield_value 系 键名错记 的死键，
#: 意图即是持久化良率值）。
_STAGE_RESULT_KEYS = (
    "ok", "errors", "warning", "verdict", "run_id", "run_dir",
    "samples_path", "n_samples", "best_params", "best_cost", "best_metrics",
    "trials_completed", "rho", "selected", "n_selected", "shortfall",
    "elapsed_s", "candidates", "yield_value", "yield_rate", "tolerances",
    "study_name", "report_html", "shadow_selection", "adapter_channel",
    # E62 席 campaign --remote 路由（2026-10-08）：stage 级 remote 声明的
    # 发射记账键（信封瘦身落 stage_result；全量信封另落 remote_stage.json）。
    "remote", "license_preflight", "remote_exec", "solve_success",
    # HFSS 一次性批处理路由（one-shot batch，无长驻桌面会话）：stage 级
    # hfss_batch 声明的求解记账键（求解信封瘦身随 stage_result 走基座
    # manifest；声明缺席=既有会话路径零行为变化，本键恒缺席）。
    "hfss_batch",
)


#: stage 级远程座位文件名（节点工作目录=座位目录；发射信封全量落档）。
REMOTE_STAGE_FILE = "remote_stage.json"


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


def _campaign_study_name(extra: dict[str, Any], node: dict[str, Any]) -> str:
    """campaign tune 阶段的 Optuna study 名（战役实例指纹版，ge9 审查 P1-1）。

    study 名拼战役目录指纹（run_dir 绝对路径 sha1 前 8 位）——run_dir 是
    战役身份的天然锚（plan/run_dir 缺省同目录、resume 同参不变，指纹
    战役内稳定）。旧名 ``campaign-{model}-{stage}`` 只含 (model, stage)
    二元组，叠加全局单库 runs/.optuna/optuna.db + load_if_exists=True，
    同模型两战役/同战役改配方重跑共享 trial 历史——TPE 被他役数据条件
    化、best_params 可能出自别的战役并顺流污染 tolerance/final_verify
    （#273 "跨实验面共享历史必须显式声明身份"同族）。

    兼容注记：ge9 前的旧战役 plan 若 tune 节点未完成，resume 将按新名
    另起新 study（旧 trial 历史不迁移，如实从零起步）；已完成 stage 由
    基座 digest 复核零重执行，不受影响。
    """
    model = str(extra.get("campaign_model") or "campaign")
    stage = str(extra.get("campaign_stage", node.get("node_id")) or "")
    campaign_dir = str(extra.get("campaign_dir") or "")
    digest = (
        hashlib.sha1(str(Path(campaign_dir).resolve()).encode("utf-8"))
        .hexdigest()[:8] if campaign_dir else "nofp")
    return f"campaign-{model}-{stage}-{digest}"


def _exec_tune(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    extra = _stage_extra(node)
    recipe = str(extra.get("campaign_recipe") or "")
    if not recipe:
        return _exec_result(
            False, message="节点缺 campaign_recipe 指针（plan 注入面缺失）")
    adapter = str(extra.get("adapter") or "fake")
    channel = "hfss" if adapter == "hfss" else "fake"
    # S2-3/#364④ 端到端收口（审查 A3 P1-2）：plan 端已按 is not None
    # 尊显式 0（campaign_stage_budget={"stage_budget": 0}），执行端同批
    # is not None 判缺——旧 `or 30` 把显式 0 再顶回 30=修复 no-op。
    try:
        raw_budget = _stage_budget(node).get("stage_budget")
        max_trials = 30 if raw_budget is None else int(raw_budget)
    except (TypeError, ValueError):
        max_trials = 30
    study = _campaign_study_name(extra, node)
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
    yield_value = raw.get("yield_rate", raw.get("yield_value", "?"))
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

        # #117/#364④ 族（审查 A3 P3-3）：显式 0 是合法值，is not None 判缺
        raw_top_k = shadow_cfg.get("top_k")
        top_k = 1 if raw_top_k is None else int(raw_top_k)
        selection = select_shadow_points(
            points, n_points=n_points,
            top_k=top_k,
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


# ─── stage 级 --remote 发射路由（E62 席 2026-10-08；E-06/PR-15 拆批余件）─────
# 形态收敛（先例单源）：fd_oe_campaign/varactor 的座位级 --remote 路由 =
# 「license 预检 fail-closed → remote_oe_service 五步执行通道 → 产物回拉
# 判读」。本节把同一路由语义收敛到 campaign plan 的 stage 级声明：
# - 预检/执行通道**单源复用既有函数**（remote_service.license_preflight +
#   remote_oe_service.remote_oe_run——五步编排零双实现，此处只是薄包装，
#   fd_oe_campaign._license_preflight/_remote_oe_run 同款模块级形态便于
#   单测钉通道，#139）；
# - 发射窗查资源日历（remote_scheduler_service.calendar_launch_view，
#   UX-B8 机读化：维护窗 blocked=不硬打；备份窗 risk=落账放行）；
# - 信封/日志回拉落**座位目录**（节点工作目录：remote_stage.json 全量
#   信封 + stage_result.json 瘦身键 + campaign.log 一行）。
# 本机路径（stage 未声明 remote）零行为变化——声明面缺失=路由面整体旁路。

def _license_preflight(machine: str | None) -> dict:
    """license 预检薄包装（remote_service 单源；模块级便于单测钉通道，#139）。"""
    from rfauto.service.remote_service import license_preflight

    return license_preflight(machine)


def _remote_oe_run(machine: str | None, seat_spec: dict) -> dict:
    """远程 OE 执行通道薄包装（remote_oe_service 五步单源；#139 同上）。"""
    from rfauto.service.remote_oe_service import remote_oe_run

    return remote_oe_run(machine, seat_spec)


def _calendar_launch_view() -> dict:
    """资源日历发射窗判定薄包装（remote_scheduler_service 单源；#139 同上）。"""
    from rfauto.service.remote_scheduler_service import calendar_launch_view

    return calendar_launch_view()


def stage_remote_decl(node: dict[str, Any]) -> dict[str, Any] | None:
    """dag 节点 → 归一化 stage 级远程路由声明（None=本机路径零行为变化）。

    声明形态（plan stage 的 ``"remote"`` 键经 nodes_from_stages 自动收进
    stage_extra；plan 级 ``"remote"`` 键经 _inject_plan_context 注入
    ``campaign_remote_default`` 作战役级缺省——**stage 声明优先**）：

    - ``true`` → 缺省登记机器（注册表唯一机器语义，resolve_machine None）；
    - ``"sim_host"`` → 指名机器；
    - ``{"machine": ..., "wait_mode": ..., "keep_remote": ..., "seat": ...}``
      → dict 形态（machine 同上两态；seat 覆盖 stage_extra.remote_seat）；
    - ``false``/缺省/``""`` → 本机。

    座位载荷独立声明在 stage 键 ``remote_seat``（dict，形态=
    remote_oe_run 座位内容物：template/simulation_py/criteria_md/
    timeout_s[/campaign]——simulation_py/criteria_md 支持内联文本或相对
    campaign 目录的文件路径，见 _resolve_seat_payload）。
    """
    extra = _stage_extra(node)
    raw = extra.get("remote")
    if raw is None:
        raw = extra.get("campaign_remote_default")
    if raw is None or raw is False or raw == "":
        return None
    if raw is True:
        return {"machine": None}
    if isinstance(raw, str):
        return {"machine": raw.strip() or None}
    if isinstance(raw, dict):
        machine = raw.get("machine")
        decl: dict[str, Any] = {
            "machine": (machine.strip() or None
                        if isinstance(machine, str) else None)}
        if raw.get("wait_mode") is not None:
            decl["wait_mode"] = str(raw.get("wait_mode"))
        if raw.get("keep_remote") is not None:
            decl["keep_remote"] = bool(raw.get("keep_remote"))
        if raw.get("seat") is not None:
            decl["seat"] = raw.get("seat")
        return decl
    return {"machine": str(raw)}


def remote_stage_gate(
    decl: dict[str, Any],
    *,
    preflight_fn: Callable[[str | None], dict],
    calendar: dict[str, Any] | None = None,
    execute_fn: Callable[[str | None, dict], dict] | None = None,
    seat_spec: dict | None = None,
) -> dict[str, Any]:
    """stage 级远程发射门（fd_oe_campaign.remote_seat_gate 同构服务层形态，
    fail-closed 三态如实记账）：

    - 资源日历维护窗内 → SKIP（不预检不发射；备份窗=risk 只落账放行）；
    - license 预检未过 → SKIP（fail-skip 不硬打，续跑重探——inconclusive
      语义映射，hfss_window 波次"下波重探"先例同源）；
    - 通道/座位载荷缺 → SKIP 如实（不假绿；recipe-loop 远跑=v1 未接线，
      campaign_app/常驻队列/L2 sftp/ADS 远跑拆批余件）；
    - 通道 skipped（互斥候跑/凭据缺/env 门）→ SKIP（未发射）；
    - 通道失败（SSH/发射/回拉空/清理）→ FAIL（已发射如实记败不假绿）；
    - 通道 ok → solve_success=(exec_rc==0) 随增量落账，产物已回拉座位目录。

    返回 verdict 增量 dict（remote/license_preflight/calendar/remote_exec/
    status[/reason][/solve_success][/verdict]）。
    """
    machine = decl.get("machine")
    out: dict[str, Any] = {
        "remote": {"machine": machine, "routed": True,
                   "exec_channel": "remote_oe_service（campaign stage 级路由）"},
    }
    cal = calendar or {}
    cal_slim = {k: cal.get(k) for k in
                ("state", "launchable", "loaded", "windows_hit", "backup_risk")
                if k in cal}
    if cal_slim:
        out["calendar"] = cal_slim
    if cal.get("state") == "blocked":
        out["status"] = "SKIP"
        out["reason"] = (
            "fail-skip：资源日历维护窗内不可发射"
            f"（windows_hit={cal.get('windows_hit')}）——不硬打")
        return out
    envelope = preflight_fn(machine)
    out["license_preflight"] = envelope
    if envelope.get("verdict") != "PASS":
        out["status"] = "SKIP"
        out["reason"] = (
            f"fail-skip：license 预检未过（verdict={envelope.get('verdict')}，"
            f"reason={envelope.get('reason')}）——不硬打（续跑重探）")
        return out
    if execute_fn is None or seat_spec is None:
        out["status"] = "SKIP"
        out["reason"] = ("执行通道/座位载荷未提供（execute_fn/seat_spec 缺）"
                         "——如实 SKIP 不发射不假绿；recipe-loop 远跑=v1 "
                         "未接线（campaign_app/常驻队列/L2 sftp/ADS 远跑"
                         "拆批余件）")
        return out
    result = execute_fn(machine, seat_spec)
    out["remote_exec"] = {
        "ok": bool(result.get("ok")),
        "skipped": bool(result.get("skipped")),
        "launched": bool(result.get("launched")),
        **{k: result.get(k) for k in (
            "machine", "batch", "task_dir_remote", "out_dir_local",
            "exec_rc", "wait_mode", "verdict", "reason") if k in result},
    }
    if result.get("skipped"):
        out["status"] = "SKIP"
        out["reason"] = (f"远程通道未发射（候跑/前置不满足）："
                         f"{result.get('reason')}")
    elif not result.get("ok"):
        out["status"] = "FAIL"
        out["reason"] = f"远程执行通道失败：{result.get('reason')}"
    else:
        out["solve_success"] = result.get("exec_rc") == 0
        out["verdict"] = result.get("verdict")
    return out


def _read_seat_text(value: Any, base: Path) -> str:
    """座位载荷字段取文本：含换行=内联文本原样；否则视作路径（相对 base）
    存在即读入；都不成立=原样返回（交通道校验面判空/判非法）。"""
    text = str(value or "")
    if "\n" in text or not text.strip():
        return text
    cand = Path(text)
    if not cand.is_absolute():
        cand = base / cand
    if cand.is_file():
        try:
            return cand.read_text(encoding="utf-8")
        except OSError:
            return text
    return text


def _resolve_seat_payload(
    decl: dict[str, Any], node: dict[str, Any], ctx: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """stage 声明 → remote_oe_run 座位载荷（None=未声明或解析失败）。

    键优先级：decl["seat"]（dict 形态声明内嵌）> stage_extra.remote_seat
    （独立 stage 键）。simulation_py/criteria_md 支持「内联文本或相对
    campaign 目录的文件路径」两态（_read_seat_text）；timeout_s 缺省
    2400s（fd_oe_campaign 缺省档）；campaign 缺省=run 目录名（回拉镜像
    目录名，非法字符交 remote_oe_run 校验如实失败）。
    """
    extra = _stage_extra(node)
    raw = decl.get("seat")
    if raw is None:
        raw = extra.get("remote_seat")
    if not isinstance(raw, dict) or not raw:
        return None, None
    base = Path(str(extra.get("campaign_dir")
                     or ctx.get("run_dir") or "."))
    seat: dict[str, Any] = dict(raw)
    for key in ("simulation_py", "criteria_md"):
        if key in seat:
            seat[key] = _read_seat_text(seat.get(key), base)
    try:
        # #117/#364④ 族（审查 A3 P3-3）：显式 0 不顶缺省（is not None 判缺）
        raw_timeout = seat.get("timeout_s")
        timeout = 2400.0 if raw_timeout is None else float(raw_timeout)
    except (TypeError, ValueError):
        timeout = 2400.0
    seat["timeout_s"] = timeout
    if not str(seat.get("campaign") or "").strip():
        seat["campaign"] = Path(str(ctx.get("run_dir") or "campaign")).name \
            or "campaign"
    return seat, None


def _append_campaign_log(ctx: dict[str, Any], msg: str) -> None:
    """执行日志追加一行（best-effort，#105：观测面不阻塞发射主路径）。"""
    try:
        run_dir = Path(str(ctx.get("run_dir") or ""))
        if not run_dir.is_dir():
            return
        with open(run_dir / CAMPAIGN_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except OSError:
        pass


def _route_remote_stage(node: dict[str, Any],
                        ctx: dict[str, Any]) -> dict[str, Any] | None:
    """stage 级 remote 声明 → 远程路由执行（None=本机路径零行为变化）。

    门序：资源日历（维护窗 blocked）→ license 预检 → 通道/座位载荷。
    结果映射（ExecutorFn 契约）：SKIP=ok+inconclusive（节点 inconclusive→
    视图 pending，续跑重探/重试）；FAIL=ok=False（已发射记败）；通道 ok
    随信封 ok。全量信封落座位目录 remote_stage.json（best-effort #105），
    瘦身键随 stage_result.json 走基座 manifest，执行日志追加一行。
    """
    decl = stage_remote_decl(node)
    if decl is None:
        return None
    kind = campaign_kind_of(node)
    node_id = str(node.get("node_id") or "")
    work_dir = Path(ctx.get("work_dir") or ".")
    seat_spec, seat_err = _resolve_seat_payload(decl, node, ctx)
    try:
        calendar = _calendar_launch_view()
    except Exception as exc:  # #105：日历观测面异常降级恒可发不阻塞
        calendar = {"loaded": False, "state": "open", "launchable": True,
                    "reason": f"日历视图异常降级恒可发: {type(exc).__name__}"}
    gate = remote_stage_gate(
        decl, preflight_fn=_license_preflight, calendar=calendar,
        execute_fn=(_remote_oe_run if seat_spec is not None else None),
        seat_spec=seat_spec)
    if seat_err:
        gate["seat_error"] = seat_err
        if gate.get("status") == "SKIP" and "座位载荷" in str(gate.get("reason")):
            gate["reason"] = f"座位载荷解析失败: {seat_err}"
    # 全量信封落座位目录（#105 best-effort：落盘失败不翻执行结果）
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / REMOTE_STAGE_FILE).write_text(
            json.dumps(gate, ensure_ascii=False, indent=1, sort_keys=True,
                       default=str),
            encoding="utf-8")
    except OSError:
        pass
    status = str(gate.get("status") or "")
    reason = str(gate.get("reason") or "")
    outputs = [_write_stage_result(node, ctx, {
        "ok": status != "FAIL",
        "remote": gate.get("remote"),
        "license_preflight": gate.get("license_preflight"),
        "remote_exec": gate.get("remote_exec"),
        "solve_success": gate.get("solve_success"),
    }), REMOTE_STAGE_FILE]
    _append_campaign_log(
        ctx, f"[remote] {node_id} machine={decl.get('machine')} "
             f"status={status or 'OK'} reason={reason[:160]}")
    if status == "SKIP":
        return dict(ok=True, outputs=outputs, wall_s=0.0,
                    message=f"{kind} remote SKIP: {reason}",
                    inconclusive=True, inconclusive_reason=reason)
    if status == "FAIL":
        return _exec_result(False, outputs=outputs,
                            message=f"{kind} remote FAIL: {reason}")
    remote_exec = gate.get("remote_exec") or {}
    return _exec_result(
        bool(remote_exec.get("ok")), outputs=outputs,
        message=(f"{kind} remote 完成: verdict={gate.get('verdict')} "
                 f"exec_rc={remote_exec.get('exec_rc')} "
                 f"solve_success={gate.get('solve_success')} "
                 f"（machine={decl.get('machine')}，产物已回拉座位目录）"))


# ─── stage 级 hfss_batch 一次性求解路由（one-shot batch 双模缝）───────────────
# solver 双模路由缝（2026-10-08）：stage 声明 ``"hfss_batch"`` → 走
# adapters/hfss_batch 一次性批处理路径（每求解一个独立短命 ansysedt 进程，
# 无长驻桌面会话）；未声明 → 既有会话路径零行为变化（本节整体旁路）。
# 声明形态（stage_extra["hfss_batch"]）：
# - ``"path/to.aedt"``（str）= 工程路径（.aedt 文件优先，.aedb 目录回退）；
# - ``{"project": 必填, "design": ..., "setup": ..., "timeout_s": ...,
#    "logfile_dir": ..., "ansysedt_exe": ...}``（dict）= 全参声明；
# - ``false``/缺省/``""`` → None（会话路径）。
# 路由顺序：remote 声明优先（E62 语义不动），hfss_batch 次之，executor
# 注册表最后——三段互斥，先命中先返回。

def stage_batch_decl(node: dict[str, Any]) -> dict[str, Any] | None:
    """dag 节点 → 归一化 stage 级 HFSS 一次性批处理声明（None=会话路径）。

    归一只做形态收敛（str → {"project": str}；dict 原样透传，键语义由
    hfss_batch.solve_project_batch 契约解释），None/False/空串=未声明。
    """
    raw = _stage_extra(node).get("hfss_batch")
    if raw is None or raw is False or raw == "":
        return None
    if isinstance(raw, str):
        return {"project": raw}
    if isinstance(raw, dict):
        return dict(raw)
    return None


def _route_batch_stage(node: dict[str, Any],
                       ctx: dict[str, Any]) -> dict[str, Any] | None:
    """stage 级 hfss_batch 声明 → 一次性批处理执行（None=本机会话路径）。

    薄编排零数值面：solve_project_batch 的结构化信封原样瘦身落
    stage_result.json（键 hfss_batch + ok），执行日志追加一行，结果映射
    ExecutorFn 契约（ok=求解信封 ok；wall_s=elapsed_s）。求解通道异常
    =节点失败（不吞不猜，由 _dispatch 兜底捕获）。
    """
    decl = stage_batch_decl(node)
    if decl is None:
        return None
    from rfauto.adapters.hfss_batch import solve_project_batch

    kind = campaign_kind_of(node)
    node_id = str(node.get("node_id") or "")
    raw = solve_project_batch(**decl)
    outputs = [_write_stage_result(node, ctx, {
        "ok": bool(raw.get("ok")),
        "hfss_batch": {k: raw.get(k) for k in (
            "ok", "rc", "timed_out", "project", "project_kind",
            "ansysedt_exe", "logfile", "artifacts", "elapsed_s", "errors")
            if raw.get(k) is not None},
    })]
    logfile = str(raw.get("logfile") or "")
    if logfile:
        outputs.append(logfile)
    _append_campaign_log(
        ctx, f"[hfss_batch] {node_id} project={raw.get('project')} "
             f"rc={raw.get('rc')} timed_out={raw.get('timed_out')} "
             f"ok={raw.get('ok')}")
    status = "OK" if raw.get("ok") else "FAIL"
    return _exec_result(
        bool(raw.get("ok")), outputs=outputs,
        wall_s=float(raw.get("elapsed_s") or 0.0),
        message=(f"{kind} hfss_batch {status}: rc={raw.get('rc')} "
                 f"timed_out={raw.get('timed_out')} "
                 f"artifacts={len(raw.get('artifacts') or [])} "
                 f"（one-shot batch，logfile={logfile or '无'}）"))


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
            # stage 级 remote 声明优先路由（None=本机路径零行为变化）
            routed = _route_remote_stage(node, ctx)
        except NodeAbortedError:
            raise
        except Exception as exc:  # 路由面异常=节点失败（不吞不猜）
            return _exec_result(False, message=f"remote 路由异常: {exc}")
        if routed is not None:
            return routed
        try:
            # stage 级 hfss_batch 声明路由（None=既有会话路径零行为变化）
            batch_routed = _route_batch_stage(node, ctx)
        except NodeAbortedError:
            raise
        except Exception as exc:  # 求解通道异常=节点失败（不吞不猜）
            return _exec_result(False, message=f"hfss_batch 路由异常: {exc}")
        if batch_routed is not None:
            return batch_routed
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

    E62 席：plan 级 ``"remote"`` 旗标注入 ``campaign_remote_default``
    （stage 级声明优先——stage 键 "remote" 在场时 stage_remote_decl 直接
    消费 stage_extra.remote，不经本缺省键）。
    """
    remote_default = plan_v2.get("remote")
    for node in (plan_v2.get("dag") or {}).get("nodes") or []:
        from_stages = "stage_extra" in node
        extra = node.setdefault("stage_extra", {})
        extra.setdefault("campaign_recipe", str(plan_v2.get("recipe") or ""))
        extra.setdefault("campaign_model", str(plan_v2.get("model") or ""))
        extra.setdefault("campaign_dir", str(run_dir))
        extra.setdefault("campaign_stage", str(node.get("node_id") or ""))
        if remote_default is not None:
            extra.setdefault("campaign_remote_default", remote_default)
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
    remote: Any = None,
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
    - ``remote``：plan 级 ``--remote`` 旗标（E62 席 2026-10-08；E-06/PR-15
      拆批余件）——战役级缺省远程路由（True=缺省登记机器/机器名字符串/
      dict 声明），stage 级 ``"remote"`` 键在场时**逐 stage 声明优先**；
      缺省 None=本机路径零行为变化；
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

    if isinstance(remote, str) and remote.strip().lower() in ("true", "1",
                                                              "yes"):
        remote = True
    plan_v2 = wrap_campaign_plan(plan)
    if remote is not None and plan_v2.get("remote") is None:
        plan_v2["remote"] = remote
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
    # 运行前视图：verdict=RUNNING（UI 队列页对运行中战役显示 running 行）。
    # ge9 审查 P2-2：占锁拒绝/计划非法路径不得留幻影 running 行——记原
    # verdict，run 级失败（期刊未生成=零阶段执行）时回写还原。预写不能
    # 挪到 run_dag 之后：run_dag 是单次阻塞调用，执行期间磁盘可见
    # RUNNING 才有"运行中"队列语义（回写还原与"锁成功后才写"的可观测
    # 终态等价，且不新增执行循环）。
    prev_verdict = plan_v2.get("verdict")
    if prev_verdict != "RUNNING":
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
        # run 级失败（锁被占/计划非法）：期刊未动，如实透传锁路径（含 lock 字样）；
        # 幻影 RUNNING 回写还原（本调用未执行任何阶段，verdict 不该停留 RUNNING）
        if prev_verdict is None:
            plan_v2.pop("verdict", None)
        else:
            plan_v2["verdict"] = prev_verdict
        with contextlib.suppress(OSError):
            save_plan(plan_v2, plan_file.parent)
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
    "REMOTE_STAGE_FILE",
    "STAGE_RESULT_FILE",
    "campaign_kind_of",
    "remote_stage_gate",
    "run_campaign",
    "stage_remote_decl",
    "wrap_campaign_plan",
]
