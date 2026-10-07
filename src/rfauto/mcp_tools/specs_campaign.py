"""list_template_specs/draft_recipe_from_spec/plan_campaign/save_campaign_plan/get_campaign_status（模板库+战役状态机）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope, ok_envelope

# ─── WP3.3 MCP 工具面全量开放：从 service 注册表自动生成工具清单 ─────────────
# 四域（方案 §4 WP3.3 行）：calculators（上两个工具已有）/模板库/战役状态/
# 数据集查询；bands 十接口为 D9 行归口 WP3.3 的 MCP 薄壳。全部只做参数
# 转发的薄壳（规则 4），数值只在确定性内核（铁律 7）——清单由注册表
# describe() 自动生成，无手工静态名单。


# ─── 17. 模板库（E2 TemplateSpec 注册表） ─────────────────────────────────────

@mcp.tool
def list_template_specs() -> dict[str, Any]:
    """模板 spec 清单（specs 域）：注册表 → 组件齐备性/meta/physics_roles。

    注册表自动生成清单（无手工静态名单）；只读台账零副作用，不用于渲染
    或综合执行（走 draft_recipe_from_spec）。纯清单面恒 ok=True（无
    ok=False 分支），空注册如实回空清单。只读无时序约束。

    Returns:
        dict: {ok, templates: [{name, components, meta_keys, physics_roles}]}
    """
    from rfauto.service.template_spec_service import list_template_specs as _list
    return _list()


@mcp.tool
def draft_recipe_from_spec(
    name: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """配方草稿综合（specs 域）：模板名+入口参数 → recipe_draft（零求解）。

    零求解零 license；线宽等几何数值由确定性综合内核（core/synthesis，
    skrf HJ）精算，本工具不产生任何物理数字（铁律 7）；不用于名义参数
    手算替代。未知模板/非法参数 → ok=False error 如实。只读无时序约束。

    Args:
        name: 模板名（如 "mline"、"wilkinson"）
        params: 综合入口参数（如 {"z0_ohm": 50, "freq_ghz": 2.5}）；
            缺省用各参数默认值

    Returns:
        dict: {ok, template, recipe_draft} 或 {ok: False, error}
    """
    from rfauto.service.template_spec_service import draft_recipe_from_spec as _draft
    return _draft(name, params)


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": True,
    }
)
def recommend_templates(
    f0_ghz: float,
    topology: str | None = None,
    n_ports: int | None = None,
    keywords: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """模板推荐（specs 域）：f0/族/端口数/关键词 → filter+rank 推荐表。

    确定性检索（零 LLM 零物理数字产出）；只检索模板注册表元数据：
    filter=topology 族匹配/n_ports 相等/f0 带内（±30% 缺省容差）/keywords
    子串（name/topology/param_semantics）；rank 主键=f0 贴近度、次键=
    param_semantics 覆盖数、三键=闭式预览通道命中、并列=模板名字典序
    （全序确定性）。坏值不抛——degraded=True+degrade_reason 如实降级
    （非 ok=False 信封）；零命中如实回空。无副作用可安全调用，只读无
    时序约束。

    Args:
        f0_ghz: 查询中心频率 GHz（正有限）
        topology: 族键（line/filter/coupler/antenna/transition/fss/material）、
            族中文标签或 topology 文本子串（如 "bpf"、"喇叭"）
        n_ports: 端口数相等过滤
        keywords: 子串过滤词（空格分词，AND 语义）
        top_k: 返回条数（缺省 5）

    Returns:
        dict: {ok, query, n_candidates, recommendations: [{name, family,
        topology, f0_ghz, n_ports, docs_link, preview, rank}], provider,
        reranked, degraded, degrade_reason}
    """
    from rfauto.service.gallery_service import recommend_templates as _rec
    return _rec(f0_ghz=f0_ghz, topology=topology, n_ports=n_ports,
                keywords=keywords, top_k=top_k)


# ─── 18. 战役状态（campaign_manager 确定性状态机） ────────────────────────────

@mcp.tool
def plan_campaign(
    recipe_path: str,
    high_adapter: str = "hfss",
    mid_adapter: str = "openems",
    calibrate_samples: int = 9,
    tune_budget: int | None = None,
) -> dict[str, Any]:
    """战役计划编制（specs 域）：配方 → 阶段队列（依赖/预算/license 门）。

    calibrate→prefilter→tune→tolerance→report→final_verify 确定性拆解。
    无副作用（只返回内存计划）；要跨调用持久先 save_campaign_plan 落盘，
    之后 get_campaign_status 查询；配方缺失 → ok=False 如实。时序：
    plan → save → run 三步，勿跳过落盘直接执行。

    Args:
        recipe_path: 配方文件路径（YAML）
        high_adapter: 终验适配器（"hfss"；"none" 则不加终验阶段）
        mid_adapter: 中保真精算适配器（默认 "openems"）
        calibrate_samples: 校准阶段样本预算
        tune_budget: tune 阶段预算；缺省取配方 limits.max_trials，再缺省 30

    Returns:
        dict: {ok, recipe, model, stages: [...], high_adapter, mid_adapter}
    """
    from rfauto.service.campaign_manager import plan_campaign as _plan
    return _plan(
        recipe_path,
        high_adapter=high_adapter,
        mid_adapter=mid_adapter,
        calibrate_samples=calibrate_samples,
        tune_budget=tune_budget,
    )


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": True,
    }
)
def save_campaign_plan(plan: dict[str, Any], out_dir: str) -> dict[str, Any]:
    """战役计划落盘（specs 域）：plan dict → <out_dir>/campaign.plan.json。

    副作用：创建 out_dir 目录并写入 campaign.plan.json（幂等覆盖）；只收
    plan_campaign 产出的计划形态，异形 plan → ok=False errors 如实。
    时序：plan_campaign 之后、run_campaign 之前调用。

    Args:
        plan: plan_campaign 返回的计划 dict
        out_dir: 落盘目录（通常 runs/<campaign_id>）

    Returns:
        dict: {ok, path} 或 {ok: False, errors}
    """
    from rfauto.service.campaign_manager import save_plan as _save
    try:
        path = _save(plan, out_dir)
    except (TypeError, OSError) as exc:
        return error_envelope([f"战役计划落盘失败: {exc}"])
    return ok_envelope(path=str(path))


@mcp.tool
def get_campaign_status(plan_path: str) -> dict[str, Any]:
    """战役状态读回（specs 域）：plan_path → verdict/各阶段 status/计数。

    无副作用，可安全调用；plan_path 可为 campaign.plan.json 文件或其所在
    目录，只读不推进状态（推进走 CLI rfauto campaign 同源服务层
    apply_event）。计划不存在/损坏 → ok=False errors 如实。只读无时序
    约束。

    Args:
        plan_path: campaign.plan.json 文件路径或其父目录

    Returns:
        dict: {ok, path, plan} 或 {ok: False, errors}
    """
    from rfauto.service.campaign_manager import load_plan as _load
    return _load(plan_path)


@mcp.tool(
    annotations={
        "destructiveHint": True,
        "idempotentHint": False,
    }
)
def run_campaign(
    plan_path: str,
    dry_run: bool = False,
    resume: bool = False,
) -> dict[str, Any]:
    """战役闭环执行（specs 域）：已落盘计划 → 逐阶段执行（VI-2 基座）。

    calibrate→…→report→final_verify。执行基座=pipeline.dag_runner（断点
    续跑/CAS/#261 互斥内建；断点续跑由状态期刊承担，resume 为显式意图
    声明）。entry 纸面命令串不 shell 出，全部走
    service.campaign_executor.CAMPAIGN_EXECUTORS 内部注册表。
    dry_run=True 只返回拓扑序+预算+互斥预览，零执行；detach 不走 MCP
    （后台通道 v1 未接线，CLI 面如实 skipped）。计划缺失 → ok=False
    errors。时序：真机求解长任务，建议先 dry_run 预览再全跑。

    Args:
        plan_path: campaign.plan.json 文件路径或其父目录
        dry_run: True=零执行预览（拓扑序/预算/互斥）
        resume: 断点续跑显式意图声明（重调同参即续跑）

    Returns:
        dict: {ok, verdict, n_done, n_dead, stage_view, run_dir, state_path}
        或 {ok: False, errors}
    """
    from rfauto.service.campaign_executor import run_campaign as _run
    return _run(plan_path, dry_run=dry_run, resume=resume)
