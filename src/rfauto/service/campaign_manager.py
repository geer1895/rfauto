"""campaign_manager：设计战役管理器（阶段 7.1 首片，SDL 范式【近】项）。

从自主实验室（Self-Driving Lab）借的核心机制：研究目标 → 实验队列，
AI 调度、动态重排、自动放弃死胡同分支。rfauto 翻译为"设计战役"：
输入配方 + 目标口径，确定性拆解为 校准→粗筛→精算→公差→报告 的
多阶段队列（现在的 p0/tune 都是单发任务，缺战役层）。

首片范围（确定性内核， #7）：
- plan_campaign：配方 → 类型化阶段队列（依赖/预算/通道/license 门槛）；
- apply_event：状态机推进（stage_done/stage_failed；校准失败=死胡同
  分支自动放弃，后续阶段标 aborted）。
HFSS 精算阶段标 license_gated（license-aware 调度的占位，接 watchdog
license_backoff 雏形）。执行接线（真实调度循环）属后续增量。

F2⑤（G13 调度接进生产路径）：plan_campaign 在阶段队列成形后、派发前经
service.orchestration_wiring.schedule_campaign_jobs 过 G13 确定性调度
（predictor 分档预测 / budget_gate 预算准入均为可注入项，生产缺省 None），
调度决策挂 plan["scheduling"]，save_plan 同步落 <out_dir>/schedule.json。
best-effort（#105）：调度器异常只落 warning，不阻塞战役。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

logger = logging.getLogger(__name__)

_STAGE_ORDER = ("calibrate", "prefilter", "tune", "tolerance", "report")

SCHEDULE_FILE_NAME = "schedule.json"
_SCHEDULE_SCHEMA = "rfauto-campaign-schedule-v1"

#: DP-13 Z2：plan v1→v1.1（final_verify 阶段新增 shadow_points 字段；
#: 旧 v1 plan 无该字段照常 load/apply——读面零 schema 强制）。
CAMPAIGN_SCHEMA = "rfauto-campaign-plan-v1.1"

#: DP-9 P2：plan v2 = v1.1 + dag 键（rfauto-dag-v1 节点集，wrap_plan_v2
#: 显式包装产出）。plan_campaign 缺省发射仍为 v1.1（兼容钉：既有测试
#: 断言 v1.1 往返），v2 只在 DAG 化消费点显式升级——平滑升轨。
CAMPAIGN_SCHEMA_V2 = "rfauto-campaign-plan-v2"

#: 影子点选择器缺省配置（Z2；预算从 final_verify 名额内划扣，n_points
#: 硬帽 = 阶段 budget，超帽截断不越名额）。
SHADOW_POINTS_DEFAULT = {"top_k": 1, "min_norm_dist": 0.3}
FINAL_VERIFY_BUDGET = 5
SHADOW_POINTS_DEFAULT_N = 3


def params_hash(params: dict[str, float]) -> str:
    """设计点指纹（canonical JSON sha256 前 16 位，league 表幂等键成分）。"""
    import hashlib
    import json as _json

    canonical = _json.dumps(
        {k: float(params[k]) for k in sorted(params)},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def select_shadow_points(
    points: list[dict[str, Any]],
    *,
    n_points: int,
    top_k: int = 1,
    min_norm_dist: float = 0.3,
    bounds: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """影子点选择器（Z2，确定性纯函数）：cost top + 归一化空间 spread 补点。

    - top_k：cost 升序前 top_k 必选（同 cost 平局按参数规范 JSON 键序决，
      逐字节可复现）；top_k 硬帽 = n_points（超量请求截断不越名额——
      影子点预算语义，S2-2/W1b 越量交付反证）；
    - spread 补点：剩余实测点中贪心取"到已选集归一化最小距离"最大者，
      距离 ≥ min_norm_dist 才收（sample_design 归一化距离思想——候选全部
      过近则如实 shortfall，不硬凑）；
    - bounds 缺省用候选集逐参数 min/max 归一（自洽）；候选参数键不一致时
      以并集为准、缺失坐标按 0.5 处理并如实记 n_irregular；
    - n_points ≤ 0 → 空（ok=False 如实）。
    """
    if n_points <= 0:
        return error_envelope([f"n_points 必须 ≥1，收到: {n_points}"], selected=[], n_selected=0)
    if not points:
        return ok_envelope(selected=[], n_selected=0, shortfall=int(n_points), n_irregular=0)

    def sort_key(p: dict[str, Any]) -> tuple:
        cost = p.get("cost")
        cost_f = float("inf") if cost is None else float(cost)
        return (cost_f, params_hash(p.get("params") or {}))

    ordered = sorted(points, key=sort_key)
    # S2-2 预算硬帽：top_k 超过 n_points 时截断，影子点不越名额
    # （W1b 反证：原 `[:max(1, int(top_k))]` 在 top_k>n_points 时越量交付、
    # shortfall 恒 0；对照 plan_campaign 内 n_points 已有 min(·, FINAL_VERIFY_BUDGET) 帽）
    top = ordered[:min(max(1, int(top_k)), int(n_points))]
    pool = ordered[len(top):]

    # 归一化空间：显式 bounds 优先，否则候选集 min/max（含已选点）
    param_names = sorted({k for p in points for k in (p.get("params") or {})})
    if bounds is None:
        bounds = {}
        for n in param_names:
            vals = [float((p.get("params") or {}).get(n, 0.0)) for p in points]
            lo, hi = min(vals), max(vals)
            bounds[n] = (lo, hi if hi > lo else lo + 1e-12)

    def norm(p: dict[str, Any]) -> dict[str, float]:
        params = p.get("params") or {}
        return {
            n: (float(params.get(n, sum(bounds[n]) / 2)) - bounds[n][0])
            / (bounds[n][1] - bounds[n][0])
            for n in bounds
        }

    def dist_to_selected(pn: dict[str, float],
                         sel_norm: list[dict[str, float]]) -> float:
        if not sel_norm:
            return float("inf")
        return min(
            sum((pn[n] - q.get(n, pn[n])) ** 2 for n in pn) ** 0.5
            for q in sel_norm)

    selected = list(top)
    sel_norm = [norm(p) for p in selected]
    n_irregular = sum(
        1 for p in points
        if set(p.get("params") or {}) != set(param_names))
    while len(selected) < int(n_points) and pool:
        best_i, best_d = None, -1.0
        for i, cand in enumerate(pool):
            d = dist_to_selected(norm(cand), sel_norm)
            if d > best_d:
                best_i, best_d = i, d
        if best_i is None or best_d < float(min_norm_dist):
            break  # 候选全部过近：如实 shortfall，不硬凑
        picked = pool.pop(best_i)
        selected.append(picked)
        sel_norm.append(norm(picked))

    shortfall = max(0, int(n_points) - len(selected))
    return ok_envelope(
        selected=selected,
        n_selected=len(selected),
        shortfall=shortfall,
        n_irregular=n_irregular,
        bounds_used={n: list(bounds[n]) for n in sorted(bounds)},
    )


def schedule_plan_jobs(
    plan: dict[str, Any],
    *,
    campaign_id: str = "",
    predictor: Any | None = None,
    budget_gate: Any | None = None,
    stage_durations: dict[str, float] | None = None,
    config: Any | None = None,
) -> dict[str, Any]:
    """G13 调度前置步（F2⑤）：战役阶段作业派发前经 B-29 接线跑确定性调度。

    参数原样透传 orchestration_wiring.schedule_campaign_jobs：
    - predictor：pipeline.quota_guard.TieredDurationPredictor（分档时长预测，
      未申报作业填充 + 同刻 SJF）；None 时申报时长、输入序（排程逐字节稳定）；
    - budget_gate：quota_guard.budget_admission_gate 构造的准入门；None 时不拒绝
      （预算配置键落地前生产缺省）；
    - stage_durations：按阶段名申报时长（秒）；config：SchedulerConfig 容量。

    best-effort（#105）：调度器任何异常都不阻塞战役发起——如实返回
    ok=False + warning（同结构空清单），计划本体不受影响。
    """
    from rfauto.service.orchestration_wiring import schedule_campaign_jobs

    try:
        return schedule_campaign_jobs(
            plan, campaign_id=campaign_id, predictor=predictor,
            budget_gate=budget_gate, stage_durations=stage_durations,
            config=config)
    except Exception as exc:  # 观测性 best-effort（#105）：宁缺勿阻塞
        logger.warning("campaign G13 调度前置步失败（不阻塞战役）: %s", exc)
        return {
            "ok": False,
            "schema": _SCHEDULE_SCHEMA,
            "campaign_id": str(campaign_id),
            "model": str(plan.get("model", "") or ""),
            "n_jobs": len(plan.get("stages") or []),
            "predictor_used": predictor is not None,
            "budget_gate_used": budget_gate is not None,
            "dispatch": [],
            "assignments": [],
            "unassigned": [],
            "rejected": [],
            "decision_log": [],
            "audit": {"ok": False, "issues": [f"调度器异常: {exc}"]},
            "seat_occupancy": {},
            "warning": f"G13 调度前置步失败（不阻塞战役，#105）: {exc}",
        }


def plan_campaign(
    recipe_path: str | Path,
    *,
    high_adapter: str = "hfss",
    mid_adapter: str = "openems",
    calibrate_samples: int = 9,
    tune_budget: int | None = None,
    shadow_points: int | None = None,
) -> dict[str, Any]:
    """把配方战役确定性拆解为类型化阶段队列。

    Z2（DP-13）：``shadow_points`` 为 final_verify 阶段的影子验证点数
    （多保真影子验证：中保真最优点在 HFSS 名额内复核）。缺省
    SHADOW_POINTS_DEFAULT_N=3；硬帽 = final_verify 名额（FINAL_VERIFY_
    BUDGET=5），超帽截断不越名额；0/None 语义：None→缺省 3，0→显式关闭。
    """
    import yaml

    path = Path(recipe_path)
    if not path.exists():
        return error_envelope([f"配方不存在: {path}"])
    with open(path, encoding="utf-8") as f:
        recipe = yaml.safe_load(f) or {}
    model = recipe.get("model", "")
    objectives = recipe.get("objectives") or []
    if not objectives:
        return error_envelope(["配方无 objectives，无法立战役"])
    limits = recipe.get("limits") or {}
    # S2-3/#364④：显式判缺 is not None——tune_budget=0 是合法显式值
    # （0=显式零预算，同 259 行 shadow_points 的 is None 写法收敛双标；
    # 旧 `or` 惯语会把显式 0 顶替成缺省 30）
    budget = int(tune_budget if tune_budget is not None
                 else (limits.get("max_trials") or 30))

    def _stage(name: str, kind: str, adapter: str, depends: list[str],
               budget: int | None = None, note: str = "") -> dict[str, Any]:
        return {
            "stage": name, "kind": kind, "adapter": adapter,
            "depends_on": depends, "status": "pending",
            "budget": budget,
            "license_gated": adapter == "hfss",
            "entry": f"rfauto {kind} {path.name}",
            "note": note,
        }

    stages = [
        _stage("calibrate", "calibrate", mid_adapter, [],
               calibrate_samples,
               "代理校准（surrogate 预筛通道的地基，v1 收官口径）"),
        _stage("prefilter", "prefilter", "surrogate", ["calibrate"],
               budget,
               "校准代理粗筛（v1 拍板：预筛通道=校准代理，fake 降级）"),
        _stage("tune", "tune", mid_adapter, ["prefilter"], budget,
               "中保真精算；HFSS 终验由 high_adapter 阶段承接"),
        _stage("tolerance", "tolerance", "surrogate", ["tune"], 1000,
               "公差/良率（Monte Carlo，代理免费）"),
        _stage("report", "report", "local", ["tolerance"], None,
               "五要素报告 + 战役档案"),
    ]
    if high_adapter not in ("none",):
        stage = _stage("final_verify", "tune", high_adapter,
                       ["tolerance"], FINAL_VERIFY_BUDGET,
                       "HFSS 终验（license 稀缺，最小预算）")
        # Z2 影子验证：预算从 final_verify 名额内划扣（n_points ≤ budget 硬帽）
        n_shadow = SHADOW_POINTS_DEFAULT_N if shadow_points is None \
            else int(shadow_points)
        n_shadow = max(0, n_shadow)
        stage["shadow_points"] = {
            "n_points": min(n_shadow, FINAL_VERIFY_BUDGET),
            "top_k": SHADOW_POINTS_DEFAULT["top_k"],
            "min_norm_dist": SHADOW_POINTS_DEFAULT["min_norm_dist"],
            "status": "pending",
            "capped": n_shadow > FINAL_VERIFY_BUDGET,
        }
        stages.append(stage)
    plan = ok_envelope(
        recipe=str(path).replace("\\", "/"),
        model=model,
        goal={"objectives": objectives,
                 "max_wall_hours": limits.get("max_wall_hours")},
        stages=stages,
        campaign_schema=CAMPAIGN_SCHEMA,
    )
    # F2⑤ G13 调度前置步：派发前过确定性调度。缺省 predictor/budget_gate
    # 均 None（申报时长、输入序、不拒绝），调度器异常只落 warning（#105），
    # 计划本体（阶段/依赖/状态机）逐字节不变。
    plan["scheduling"] = schedule_plan_jobs(plan)
    # XN-1 Pre-mortem（第十九轮 P1）：战役开工前自动生成失败模式+检测探针。
    # best-effort（#105）：生成失败只落 warning，不阻塞战役计划本体。
    plan["premortem"] = _campaign_premortem(model=model, recipe=path.name)
    # KD-4 失败知识注入（round16 P1）：预检强制调用——campaign 声明面提关键词
    # → 既有失败库（premortem FAILURE_MODE_LIBRARY，同库对偶不重复建库）定向
    # 检索出坑号可溯的失败模式子集注入开工 context。best-effort（#105）：
    # 检索失败只落 warning，不阻塞战役计划本体。
    plan["failure_knowledge"] = _campaign_failure_knowledge(
        model=model, recipe=path.name, objectives=objectives)
    return plan


def _campaign_premortem(*, model: str, recipe: str) -> dict[str, Any]:
    """XN-1 战役开工失败预演（param_sweep 主类；best-effort #105）。"""
    try:
        from rfauto.service.premortem_service import campaign_premortem_block

        return campaign_premortem_block(model=model, recipe=recipe)
    except Exception as exc:  # 观测性 best-effort（#105）：宁缺勿阻塞
        logger.warning("战役开工 premortem 生成失败（不阻塞战役）: %s", exc)
        return {"ok": False, "warning": f"premortem 生成失败（#105）: {exc}"}


def _campaign_failure_knowledge(*, model: str, recipe: str,
                                objectives: Any) -> dict[str, Any]:
    """KD-4 失败知识注入块（round16：campaign_manager 预检强制调用）。

    战役=param_sweep 主类；关键词从战役声明面（模型名/objectives/配方名）
    确定性提取，对 premortem 失败模式库（XN-1 同库，只读消费）做交集检索，
    坑号可溯子集注入开工 context。best-effort（#105）：检索任何异常都不
    阻塞战役计划——如实 ok=False+warning。
    """
    try:
        from rfauto.core.failure_knowledge import (
            failure_knowledge_for,
            keywords_from_campaign,
            render_failure_knowledge_markdown,
        )

        keywords = list(keywords_from_campaign(model, objectives, recipe))
        block = failure_knowledge_for("param_sweep", keywords or None)
        block["keywords_source"] = "campaign_declaration(model/objectives/recipe)"
        block["markdown"] = render_failure_knowledge_markdown(block)
        return block
    except Exception as exc:  # 观测性 best-effort（#105）：宁缺勿阻塞
        logger.warning("战役开工失败知识注入失败（不阻塞战役）: %s", exc)
        return {"ok": False, "warning": f"失败知识注入失败（#105）: {exc}"}


def _deposit_skill_on_complete(run_id: str | None,
                               output_dir: str | Path | None) -> None:
    """战役 COMPLETE 收官的 skill 自动沉淀钩子（ge8e W2/A4，best-effort #105）。

    F8 已在 api.run_once 单 run 收官点接线 auto_deposit_hook；本函数补
    战役级收官路径（apply_event 判定 COMPLETE 的同位分支——批次全部
    阶段终态 done 的落档点）。campaign 级 run_id 走钩子的 run_id 路径
    （health_check_run 判定，verdict 非 HEALTHY 如实不沉淀），幂等由
    钩子内 _DEPOSITED_RUN_IDS 承担（同 campaign 只沉淀一次）；run_id
    缺省 None 时无沉淀锚点直接跳过（既有调用方零感知）。钩子任何异常
    只落 warning，不阻断战役结果（#105）。
    """
    if not run_id:
        return
    try:
        from rfauto.service.skill_autopilot import auto_deposit_hook

        auto_deposit_hook(run_id=str(run_id),
                          output_dir=Path(output_dir) if output_dir
                          else "skills")
    except Exception as exc:  # 观测性 best-effort（#105）：宁缺勿阻塞
        logger.warning("战役 skill 自动沉淀钩子失败（非阻断）: %s", exc)


def apply_event(plan: dict[str, Any], stage: str, event: str,
                *, detail: str = "", run_id: str | None = None,
                skill_output_dir: str | Path | None = None) -> dict[str, Any]:
    """战役状态机推进（确定性）。

    event ∈ stage_done | stage_failed | skip。stage_failed 时所有依赖
    它的未完成阶段递归标 aborted（死胡同分支自动放弃——SDL 核心行为）。

    run_id / skill_output_dir（ge8e W2/A4，可选）：战役收官（全部阶段
    done → verdict=COMPLETE）时把 campaign 级 run_id 交给 skill 自动沉淀
    钩子（auto_deposit_hook，沉淀产物落 skill_output_dir——惯例
    <campaign 目录>/skills，不污染仓根技能库）；两者缺省 None 时零感知
    （不触发钩子），best-effort 语义见 _deposit_skill_on_complete。
    """
    stages = {s["stage"]: s for s in plan.get("stages", [])}
    if stage not in stages:
        return error_envelope([f"未知阶段: {stage}"])
    if event not in ("stage_done", "stage_failed", "skip"):
        return error_envelope([f"未知事件: {event}"])

    target = stages[stage]
    if event == "stage_done":
        target["status"] = "done"
    elif event == "skip":
        target["status"] = "skipped"
    else:
        target["status"] = "failed"
        target["note"] = (target.get("note", "") + f" | failed: {detail}").strip()

    # 依赖传播：被放弃阶段的下游递归 aborted
    if event == "stage_failed":
        changed = True
        while changed:
            changed = False
            for s in stages.values():
                if s["status"] != "pending":
                    continue
                if any(stages[d]["status"] in ("failed", "aborted")
                       for d in s["depends_on"] if d in stages):
                    s["status"] = "aborted"
                    changed = True

    done = sum(1 for s in stages.values() if s["status"] == "done")
    dead = sum(1 for s in stages.values()
               if s["status"] in ("failed", "aborted"))
    if dead:
        verdict = "ABORTED" if any(s["status"] == "failed"
                                   for s in stages.values()) else "PARTIAL"
    elif done == len(stages):
        verdict = "COMPLETE"
    else:
        verdict = "RUNNING"
    plan["verdict"] = verdict
    plan["n_done"] = done
    plan["n_dead"] = dead
    if verdict == "COMPLETE":
        # A4 战役级 skill 自动沉淀（ge8e W2，best-effort #105）：批次全部
        # 阶段终态 done（战役收官落档点）接线 auto_deposit_hook——
        # campaign 级 run_id 走钩子内 health 判定，幂等由 _DEPOSITED_RUN_
        # IDS 承担；异常只落 warning 不阻断战役结果。
        _deposit_skill_on_complete(run_id, skill_output_dir)
    return ok_envelope(verdict=verdict, plan=plan)


def save_plan(plan: dict[str, Any], out_dir: str | Path) -> Path:
    """战役计划落盘（campaign.plan.json，幂等覆盖）。

    计划含 scheduling（F2⑤ G13 调度前置步）时同步落 <out_dir>/schedule.json
    （排序键规范化 JSON：派发顺序、预测时长与来源、拒绝清单、审计事件），
    作为 runs/<campaign>/ 下的调度可审计副本。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / "campaign.plan.json"
    # 原子替换（审查 P2-1，2026-10-05）：kill 窗口内直写可截断 campaign.plan.json
    # 致 resume 断链——tmp 同目录 + os.replace 原子落盘。
    _atomic_write_text(p, json.dumps(plan, ensure_ascii=False, indent=1,
                                     default=str))
    scheduling = plan.get("scheduling")
    if isinstance(scheduling, dict):
        s = out / SCHEDULE_FILE_NAME
        _atomic_write_text(s, json.dumps(scheduling, ensure_ascii=False,
                                         indent=1, sort_keys=True, default=str))
    return p


def _atomic_write_text(target: Path, text: str) -> None:
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


PLAN_FILE_NAME = "campaign.plan.json"


def load_plan(plan_path: str | Path) -> dict[str, Any]:
    """读回已落盘的战役计划（save_plan 的对称查询口，WP3.3 战役状态）。

    plan_path 允许两种形态：campaign.plan.json 文件本身，或包含它的目录
    （自动补全文件名）。JSON 进出、显式报错语义（与 calculator_service
    一致）：路径不存在 / 文件名不对 / JSON 损坏一律 ok=False + errors
    （不抛出），CLI/MCP 薄壳零逻辑直接渲染。
    """
    path = Path(plan_path)
    if path.is_dir():
        path = path / PLAN_FILE_NAME
    if not path.exists():
        return error_envelope(
            [f"战役计划不存在: {path}"
                           f"（先 plan_campaign + save_campaign_plan 落盘）"],
        )
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return error_envelope([f"战役计划读取失败: {exc}"])
    if not isinstance(plan, dict) or not isinstance(plan.get("stages"), list):
        return error_envelope([f"{path} 不是战役计划（缺 stages 列表）"])
    return ok_envelope(path=str(path), plan=plan)


def wrap_plan_v2(plan: dict[str, Any]) -> dict[str, Any]:
    """plan v1/v1.1 → v2 包装（DP-9 P2：旧计划读入即包装 v2，旧配方零改动）。

    确定性：stages → dag 节点（core.compose.dag_schema.nodes_from_stages
    的 STAGE_KIND_MAP 映射，depends_on 逐位保留）；原字段全部浅拷贝保留
    （shadow_points 等扩展字段不丢），仅 campaign_schema 升 v2 + 新增
    "dag" 键。**不 mutate 输入**（返回新 dict）；已是 v2 的 plan 原样返回
    （幂等）。stages 本体保留在 v2 计划中（状态机 apply_event 继续消费）。
    """
    if plan.get("campaign_schema") == CAMPAIGN_SCHEMA_V2:
        return plan
    from rfauto.core.compose.dag_schema import DAG_SCHEMA, nodes_from_stages

    nodes = nodes_from_stages(plan.get("stages") or [])
    wrapped = dict(plan)
    wrapped["campaign_schema"] = CAMPAIGN_SCHEMA_V2
    wrapped["dag"] = {"schema": DAG_SCHEMA, "nodes": nodes}
    return wrapped


def list_campaign_plans(root: str | Path = "runs") -> dict[str, Any]:
    """扫 root 下全部已落盘战役计划（战役状态总览，供薄壳列表渲染）。

    只按 PLAN_FILE_NAME 精确匹配（不递归通配兜底），逐条用 load_plan
    读取——损坏文件逐条记 ok=False 不拖垮整表（观测 best-effort，#105）。
    """
    root_path = Path(root)
    items: list[dict[str, Any]] = []
    if root_path.is_dir():
        for d in sorted(p for p in root_path.iterdir() if p.is_dir()):
            found = load_plan(d)
            if found.get("ok"):
                plan = found["plan"]
                items.append({
                    "path": found["path"],
                    "model": plan.get("model", ""),
                    "verdict": plan.get("verdict", ""),
                    "n_done": plan.get("n_done"),
                    "n_dead": plan.get("n_dead"),
                    "n_stages": len(plan.get("stages") or []),
                })
    return ok_envelope(root=str(root_path), campaigns=items, n_campaigns=len(items))
