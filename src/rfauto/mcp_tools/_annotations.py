"""MCP 工具注解单源分类表 + 装配层注入（VB-1，aurora_r Wave2）。

职责（单源）：
- 全部 MCP 工具（以实测注册面为准，208 个 @ mcp_server facade）逐工具标注四类：
  read_only / mutating_non_destructive / destructive / long_running；
- 四类 → ``mcp.types.ToolAnnotations`` 的派生映射（下 ``_DERIVED_HINTS``）；
- ``apply_tool_annotations()`` 在装配层（mcp_server facade，``_normalize_
  tool_registration_order`` 之后）对**未注解**工具原地挂 ToolAnnotations：
  只写 ``annotations`` 字段，名称/描述/参数 schema/注册序零触碰（注入前后
  指纹自证，见函数体）；已有装饰器注解的 20 个工具一律跳过（保真既有
  hints，跨检一致性由 tests/unit/test_mcp_annotations_readonly.py 钉住）。

分类依据（逐工具实读消费面后判定，非机械全标）：
- read_only：消费的 service 函数纯读/纯计算——零写文件、零子进程发射、
  零删除、零装依赖（静态互证见测试；已知例外仅 kicad_extract /
  kicad_optimize_cpw 的 KiCad 自带 Python 子进程只读解析，AGENTS 规则 2）；
- mutating_non_destructive：写文件/建目录/DB upsert/注册表状态变更，
  不删除既有产物（import/annotate/export/render/save/cancel 类）；
- destructive：可删除/重建既有产物（vendor_docs rebuild 的 rmtree、
  run_campaign 既有装饰器已声明 destructiveHint=True）；
- long_running：发射求解/模拟器/优化战役（run_once/run_sweep/hpeesofsim/
  pyaedt build+solve/qucsator 通道）——hints 上与 mutating 同形（非只读、
  非破坏），类别区分供 VB-7 限流表等消费方使用。

两维可选叠加：idempotent（同参重放无附加效果）、open_world（触外部实体）。
openWorldHint 仅 remote 两探针为 True（SSH 触外部主机）；idempotent 只在
判定明确时给出（read_only 恒 True；DEST/LR 恒 False；MND 留空不臆断）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.types import ToolAnnotations

from rfauto.mcp_tools._core import mcp as _mcp

# ─── 类别 ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Cat:
    key: str


READ_ONLY = _Cat("read_only")
MUTATING_NON_DESTRUCTIVE = _Cat("mutating_non_destructive")
DESTRUCTIVE = _Cat("destructive")
LONG_RUNNING = _Cat("long_running")


@dataclass(frozen=True)
class _Entry:
    category: _Cat
    reason: str
    idempotent: bool | None = None
    open_world: bool | None = None


def _derived_hints(entry: _Entry) -> dict[str, Any]:
    """类别 → ToolAnnotations 字段（只派生四 hint，不加 title）。"""
    cat = entry.category
    if cat is READ_ONLY:
        return {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True if entry.idempotent is None else entry.idempotent,
            "openWorldHint": entry.open_world,
        }
    if cat is DESTRUCTIVE:
        return {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False if entry.idempotent is None else entry.idempotent,
            "openWorldHint": entry.open_world,
        }
    # mutating_non_destructive / long_running：非只读、非破坏
    return {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": entry.idempotent,
        "openWorldHint": entry.open_world,
    }


# ─── 单源分类表（200 工具，按注册序= facade import 序排列）─────────────────

_TOOLS: dict[str, _Entry] = {
    # basic（环境/配方只读面）
    "doctor": _Entry(
        READ_ONLY, "api.doctor 环境只读体检：注册表/安装目录/版本探针纯读，零子进程零写"
    ),
    "list_models": _Entry(READ_ONLY, "api.list_models 模型注册表枚举，纯读"),
    "validate_recipe": _Entry(READ_ONLY, "api.validate_recipe 配方加载+校验，零写"),
    # jobs（任务注册表）
    "create_run": _Entry(LONG_RUNNING, "api.run_once 同步求解一点：建 run 目录+写 meta+发射 adapter 求解"),
    "create_run_async": _Entry(LONG_RUNNING, "run_once_async 后台线程执行 run_once 全部动作（发射求解）"),
    "poll_job": _Entry(READ_ONLY, "api.poll_job job 注册表状态读"),
    "cancel_job": _Entry(
        MUTATING_NON_DESTRUCTIVE, "job_registry.cancel 置取消事件改注册表状态，不杀线程不删数据"
    ),
    "wait_job": _Entry(READ_ONLY, "循环 poll_job 阻塞等终态，纯读（time.sleep 轮询）"),
    "get_metrics": _Entry(READ_ONLY, "api.get_metrics runs/<id>/metrics 只读"),
    # synth（闭式综合/链路预算，纯计算）
    "synthesize": _Entry(READ_ONLY, "core.synthesis.synthesize_mline 闭式综合，零 I/O"),
    "synthesize_bpf": _Entry(READ_ONLY, "core.synthesis.synthesize_bpf_model 闭式综合，零 I/O"),
    "budget_analysis": _Entry(READ_ONLY, "DeviceCatalog+LinkBudget 预算计算，读 catalog 纯计算"),
    "cascade_budget": _Entry(READ_ONLY, "cascade_service.cascade_budget_report 级联预算计算"),
    "spur_search": _Entry(READ_ONLY, "cascade_service.spur_search_report 交调搜索纯计算"),
    "if_plan_sweep": _Entry(READ_ONLY, "cascade_service.if_plan_report 中频计划纯计算"),
    # diagnose（耦合矩阵诊断，纯计算）
    "cm_diagnose_q": _Entry(READ_ONLY, "diagnosis_service.diagnose_q 纯计算/读 Touchstone"),
    "cm_extract_refine": _Entry(READ_ONLY, "diagnosis_service.diagnose_cm 耦合矩阵提取纯计算"),
    "cm_cat_critique": _Entry(READ_ONLY, "diagnosis_service.diagnose_cat 评判纯计算"),
    "correlate_measurement": _Entry(READ_ONLY, "api.correlate_files 读两文件比对，零写"),
    # runs（run 湖只读判读面）
    "diagnose": _Entry(READ_ONLY, "api.get_metrics+infra.diagnosis 规则判读，runs/ 只读"),
    "compare_runs": _Entry(READ_ONLY, "api.compare_runs 读两 run 比对+新鲜度标注"),
    "run_monitor": _Entry(READ_ONLY, "runtime_monitor_service 运行面只读监控"),
    "get_run_artifacts": _Entry(READ_ONLY, "ui_service.run_detail 产物清单只读"),
    "get_model_3d": _Entry(READ_ONLY, "ui_service.model3d_for_recipe 配方几何只读重建"),
    "list_calculators": _Entry(READ_ONLY, "calculator_service 注册表枚举"),
    "run_calculator": _Entry(READ_ONLY, "calculator_service 确定性计算器单点计算，零盘写"),
    # specs_campaign（战役域）
    "list_template_specs": _Entry(READ_ONLY, "template_spec_service 模板 specs 枚举"),
    "draft_recipe_from_spec": _Entry(READ_ONLY, "template_spec_service 配方草稿纯合成，零写盘"),
    "recommend_templates": _Entry(READ_ONLY, "gallery_service 模板推荐纯读（既有注解 idempotent=True 相容）"),
    "plan_campaign": _Entry(READ_ONLY, "campaign_manager.plan_campaign 计划计算，零写盘"),
    "save_campaign_plan": _Entry(
        MUTATING_NON_DESTRUCTIVE, "campaign_manager.save_plan 计划 YAML 落盘（mkdir+写文件）"
    ),
    "get_campaign_status": _Entry(READ_ONLY, "campaign_manager.load_plan 计划文件只读"),
    "run_campaign": _Entry(
        DESTRUCTIVE,
        "campaign_executor 执行战役（新建/续跑 run 产物）；既有装饰器已声明 destructiveHint=True，镜像保持",
    ),
    # datasets（数据集域）
    "list_datasets": _Entry(READ_ONLY, "dataset_insights.list_datasets 目录枚举只读"),
    "query_dataset": _Entry(READ_ONLY, "dataset_service.query_dataset sqlite 只读查询"),
    "discover_workdir_runs": _Entry(READ_ONLY, "dataset_service 目录扫描候选发现，零写"),
    "import_workdir_runs": _Entry(
        MUTATING_NON_DESTRUCTIVE, "dataset_service.import_workdir_runs 物化数据集（mkdir+写 parquet）"
    ),
    # bands（频段库，纯查）
    "bands_list": _Entry(READ_ONLY, "bands_service 频段库查询"),
    "bands_get": _Entry(READ_ONLY, "bands_service 频段查询"),
    "bands_find": _Entry(READ_ONLY, "bands_service 频率定位查询"),
    "bands_spec_bounds": _Entry(READ_ONLY, "bands_service 规范界查询"),
    "bands_env_list": _Entry(READ_ONLY, "bands_service 环境库查询"),
    "bands_env_get": _Entry(READ_ONLY, "bands_service 环境条目查询"),
    "bands_env_find": _Entry(READ_ONLY, "bands_service 温度定位查询"),
    "bands_env_delta_t": _Entry(READ_ONLY, "bands_service 温差换算"),
    "bands_env_uq_axis": _Entry(READ_ONLY, "bands_service UQ 轴换算"),
    "bands_env_points": _Entry(READ_ONLY, "bands_service 环境点集生成"),
    # report_bench（报告/回归）
    "warm_start_optimize": _Entry(
        LONG_RUNNING, "warm_start_data 优化战役（多 trial 发射 adapter 求解）"
    ),
    "export_report_pdf": _Entry(MUTATING_NON_DESTRUCTIVE, "infra.report PDF 落盘（写文件）"),
    "goldset_regression": _Entry(READ_ONLY, "goldset_service 基线回归判读计算，零写"),
    "agentbench_regression": _Entry(READ_ONLY, "agent_bench 回归判读计算，零写"),
    "design_report": _Entry(
        MUTATING_NON_DESTRUCTIVE, "design_replay_report.generate_design_report 报告落盘（mkdir+write）"
    ),
    # agent（多 agent/自验证环，发射求解）
    "rf_propose_params": _Entry(READ_ONLY, "call_kernel_tool 确定性提议内核，纯计算无写"),
    "rf_run_sampler": _Entry(LONG_RUNNING, "call_kernel_tool('rf_run_sampler') 发射单点求解"),
    "rf_critique_point": _Entry(READ_ONLY, "call_kernel_tool 确定性评判内核，纯计算"),
    "rf_spec_cost": _Entry(READ_ONLY, "call_kernel_tool 确定性代价内核，纯计算"),
    "multi_agent_run": _Entry(LONG_RUNNING, "multi_agent_service 多轮环（每轮发射求解）"),
    "autotune_self_verify": _Entry(LONG_RUNNING, "autotune_service.self_verify_loop 粗/细网格发射求解"),
    # metasurface（超表面闭式计算）
    "metasurface_coding_pattern": _Entry(READ_ONLY, "metasurface_service 编码图样统计纯计算"),
    "metasurface_quant_loss_db": _Entry(READ_ONLY, "metasurface_service 量化损耗闭式计算"),
    # uq（不确定度）
    "uq_yield_at": _Entry(READ_ONLY, "uq_service MC 良率计算，samples 读"),
    "robustness_report": _Entry(
        MUTATING_NON_DESTRUCTIVE,
        "source=run_id 时 materialize_dataset 物化写盘+persist 存储写——有写面，不标只读",
    ),
    "uq_design_center": _Entry(READ_ONLY, "uq_service.yield_design_center 迭代计算，零写"),
    "uq_temperature_zone": _Entry(READ_ONLY, "uq_service.temperature_zone_yield 温区良率计算"),
    "uq_rare_yield": _Entry(READ_ONLY, "uq_service.rare_yield_is 重要性抽样计算"),
    # farfield_kicad
    "farfield_runs": _Entry(READ_ONLY, "nf2ff_service runs 远场产物枚举只读"),
    "farfield_view": _Entry(READ_ONLY, "nf2ff_service.farfield_view 远场产物只读解析"),
    "kicad_extract": _Entry(
        READ_ONLY,
        "KiCad 自带 Python 子进程只读解析 .kicad_pcb（AGENTS 规则 2；静态互证白名单唯一子进程例外）",
        open_world=True,
    ),
    "kicad_optimize_cpw": _Entry(
        READ_ONLY, "extract（子进程只读解析）+闭式寻优，零写", open_world=True
    ),
    # multiphysics
    "electrothermal_chain": _Entry(READ_ONLY, "core.thermal_iteration 进程内定点迭代，零 I/O"),
    "parasitic_extract_rlc": _Entry(READ_ONLY, "parasitic_service 闭式 RLC 提取，零 I/O"),
    "topology_propose": _Entry(
        MUTATING_NON_DESTRUCTIVE, "topology_service 沙箱草稿写盘+可选 promote（走既有 Gate）"
    ),
    # datasets_ops
    "dataset_coverage": _Entry(READ_ONLY, "dataset_insights 覆盖统计，数据集只读"),
    "dataset_annotate_ground_truth": _Entry(
        MUTATING_NON_DESTRUCTIVE, "annotate_ground_truth 数据集 meta 写（既有注解 idempotent=True 相容）"
    ),
    "dataset_set_visibility": _Entry(
        MUTATING_NON_DESTRUCTIVE, "set_dataset_visibility 数据集 meta 写（既有注解相容）"
    ),
    "dataset_export_hf": _Entry(
        MUTATING_NON_DESTRUCTIVE, "export_hf_dataset 导出写盘（mkdir+copyfile+write_text）"
    ),
    # vna
    "vna_offline_replay": _Entry(
        MUTATING_NON_DESTRUCTIVE, "session_path 给定时 save_session 写会话 JSONL"
    ),
    "vna_en_report": _Entry(
        MUTATING_NON_DESTRUCTIVE, "markdown_path 给定时报告 markdown 落盘"
    ),
    "report_narrative": _Entry(READ_ONLY, "report_narrative_for_run 只读叙述生成，零写"),
    # rationale / rag
    "rationale_recall": _Entry(READ_ONLY, "rationale_memory 记忆检索只读"),
    "rationale_checklist": _Entry(READ_ONLY, "rationale_memory 清单生成只读"),
    "rag_query": _Entry(READ_ONLY, "rag_service 语料检索纯读（BM25 词法/语义）"),
    "rag_explain": _Entry(READ_ONLY, "rag_service.explain_corpus 检索解释纯读"),
    # ops
    "self_heal_run": _Entry(READ_ONLY, "docstring 明示零副作用只诊断+建议，不改配方"),
    "log_digest": _Entry(READ_ONLY, "self_heal_service 日志读+摘要"),
    "dispersion_report": _Entry(READ_ONLY, "dispersion_service 材料色散fitness报告纯计算"),
    # db（注册表数据库）
    "db_init": _Entry(MUTATING_NON_DESTRUCTIVE, "db_service.db_init 建 SQLite 注册表文件"),
    "db_migrate": _Entry(MUTATING_NON_DESTRUCTIVE, "db_service.db_migrate schema 迁移写"),
    "db_status": _Entry(READ_ONLY, "db_service.db_status 注册表状态只读"),
    "db_reindex_runs": _Entry(
        MUTATING_NON_DESTRUCTIVE, "reindex_runs 扫 meta.json upsert 重建 runs 表（幂等 upsert，不删）"
    ),
    "db_query": _Entry(READ_ONLY, "db_query_safe 只读 SELECT 白名单+参数绑定"),
    "db_analytics_attach": _Entry(READ_ONLY, "duckdb ATTACH 零拷贝直读注册表"),
    # slotline（闭式综合，纯计算）
    "slotline_analysis": _Entry(READ_ONLY, "slotline_service 闭式分析"),
    "slotline_synthesis": _Entry(READ_ONLY, "slotline_service 闭式综合"),
    "msl_slot_transition_design": _Entry(READ_ONLY, "slotline_service 过渡设计闭式"),
    "marchand_balun_design": _Entry(READ_ONLY, "slotline_service balun 设计闭式"),
    "marchand_two_section_synthesis": _Entry(READ_ONLY, "slotline_service 两节综合闭式"),
    # guidelines
    "get_guidelines_for": _Entry(READ_ONLY, "guidelines_service 静态指南表查"),
    # mmt
    "mmt_solve": _Entry(MUTATING_NON_DESTRUCTIVE, "solve_mmt 进程内模式匹配求解+work_dir 工件落盘"),
    "compose_netlist": _Entry(
        MUTATING_NON_DESTRUCTIVE, "compose_write(out_dir) 写组合产物；无 out_dir 分支纯计算"
    ),
    # nfmeas（近场测量解析面，纯计算）
    "nfmeas_ffs_info": _Entry(READ_ONLY, "nf_measurement_service ffs 文件只读"),
    "nfmeas_cut_view": _Entry(READ_ONLY, "nf_measurement_service 切面只读"),
    "nfc_coil_evaluate": _Entry(READ_ONLY, "nfc_coil_service 闭式评估"),
    "nfc_coil_synthesize": _Entry(READ_ONLY, "nfc_coil_service 闭式综合"),
    "nfc_coil_q": _Entry(READ_ONLY, "nfc_coil_service Q 值闭式"),
    "sar_analytic_plane_wave": _Entry(READ_ONLY, "sar_service 解析式 SAR"),
    # explain
    "explain_run": _Entry(READ_ONLY, "explain_run run 日志面读+解释，零写"),
    "list_composable_templates": _Entry(READ_ONLY, "compose_service 模板枚举"),
    "error_hints_lookup": _Entry(READ_ONLY, "error_hints_service 提示表查"),
    # anchors
    "anchors_list": _Entry(READ_ONLY, "anchors_service 锚注册表读"),
    "anchors_inspect": _Entry(READ_ONLY, "anchors_service 单锚只读"),
    # anim
    "anim_render": _Entry(MUTATING_NON_DESTRUCTIVE, "anim_render_service 动图渲染落盘（mkdir+write_bytes）"),
    # format_overview
    "format_overview": _Entry(READ_ONLY, "format_overview_service 文件只读速览"),
    # vendor_docs（厂商帮助文档检索）
    "vendor_docs_build": _Entry(
        DESTRUCTIVE, "build_vendor_index 写索引库；rebuild=True 先 rmtree 旧索引——有删除面"
    ),
    "vendor_docs_search": _Entry(READ_ONLY, "search_vendor_docs 索引只读查询"),
    "vendor_docs_audit": _Entry(READ_ONLY, "zero_ingest_audit 索引审计只读"),
    # si_lake
    "si_channel_report": _Entry(READ_ONLY, "si_channel_service 通道分析只读"),
    "lake_query_runs": _Entry(READ_ONLY, "lake_service runs 索引只读查询"),
    "lake_pack_campaign": _Entry(MUTATING_NON_DESTRUCTIVE, "pack_campaign 打包归档写 out_path"),
    "com_pam4_run": _Entry(READ_ONLY, "COM/PAM4 计算纯读 s4p"),
    # certify
    "render_constraint_check": _Entry(READ_ONLY, "render_constraint_service 约束评估纯计算"),
    "import_solid_payload": _Entry(READ_ONLY, "solid_import_service 实体文件只读解析"),
    "certify_design": _Entry(READ_ONLY, "certify_design 样本容差认证纯计算"),
    "port_gate": _Entry(READ_ONLY, "port_gate_service 端口门纯计算"),
    # knowledge
    "search_knowledge": _Entry(READ_ONLY, "knowledge_service 知识库检索只读"),
    # pdn
    "pdn_analyze": _Entry(READ_ONLY, "pdn_service 阻抗分析纯计算"),
    "pdn_select": _Entry(READ_ONLY, "pdn_service 电容选型纯计算"),
    "pdn_gate": _Entry(READ_ONLY, "pdn_service 门判纯计算"),
    # aging
    "aging_simulate": _Entry(READ_ONLY, "aging_service 老化仿真闭式计算"),
    "aging_verdict": _Entry(READ_ONLY, "aging_service EOL 判定计算"),
    "aging_report": _Entry(READ_ONLY, "aging_service 报告计算"),
    # afs_interop
    "afs_plan": _Entry(READ_ONLY, "afs_service 扫频计划纯计算"),
    "read_hfss_touchstone_comments": _Entry(READ_ONLY, "interop_service 注释块直读"),
    # remote（多机探活，触外部主机）
    "remote_probe_machine": _Entry(
        READ_ONLY, "remote_service SSH/命令探活只读，触外部主机→openWorld", open_world=True
    ),
    "remote_machine_status": _Entry(
        READ_ONLY, "remote_service 机器状态查询只读，触外部主机→openWorld", open_world=True
    ),
    # agent2
    "even_odd_report": _Entry(READ_ONLY, "even_odd_service 偶奇模拆分报告纯计算"),
    "mcts_search": _Entry(READ_ONLY, "mcts_search samples 读+搜索计算，零写"),
    "inverse_prefilter": _Entry(READ_ONLY, "inverse_prefilter 语料筛选纯计算"),
    # adc
    "adc_interleave_spurs": _Entry(READ_ONLY, "adc_budget_service 交调表纯计算"),
    "jitter_budget_snr": _Entry(READ_ONLY, "adc_budget_service 抖动预算纯计算"),
    # emc
    "emc_cispr_band_params": _Entry(READ_ONLY, "emc_service CISPR 频段查表"),
    "emc_cispr_detect": _Entry(READ_ONLY, "emc_service 检波计算"),
    "emc_ground_spacing_check": _Entry(READ_ONLY, "emc_service 间距判据计算"),
    "emc_cm_radiated_budget": _Entry(READ_ONLY, "emc_service 共模辐射预算计算"),
    # env_reliability（环境可靠性）
    "fault_tree_report": _Entry(READ_ONLY, "fault_tree_service 树构建+割集计算"),
    "build_datasheet": _Entry(READ_ONLY, "datasheet_service 渲染内容进信封，零盘写"),
    "netlist_goldset_replay": _Entry(
        LONG_RUNNING, "build_simulator_channel+replay 发射 qucsator 等模拟器子进程"
    ),
    "humidity_uptake": _Entry(READ_ONLY, "humidity_drift_service 吸湿计算"),
    "msl_floor_life_query": _Entry(READ_ONLY, "humidity_drift_service 车间寿命查询"),
    "weave_style_info": _Entry(READ_ONLY, "glass_weave_skew_service 布纹查表"),
    "weave_skew_estimate": _Entry(READ_ONLY, "glass_weave_skew_service 偏斜估计"),
    "cryo_surface_estimate": _Entry(READ_ONLY, "cryo_materials_service 低温表面估计"),
    # preflight
    "preflight_run": _Entry(READ_ONLY, "preflight_service 检查项纯计算"),
    # optim（优化战役）
    "start_tune": _Entry(LONG_RUNNING, "api.start_tune_async 发射 Optuna 调优战役（多 trial 求解）"),
    "run_sweep": _Entry(LONG_RUNNING, "sweep_backend.run_sweep 发射参数扫描战役"),
    # edb
    "edb_emit_spec": _Entry(MUTATING_NON_DESTRUCTIVE, "edb_lane_service spec 落盘（mkdir+write）"),
    "edb_build_solve": _Entry(LONG_RUNNING, "edb_lane_service pyaedt 建 EDB+发射 AEDT 求解"),
    "edb_status": _Entry(READ_ONLY, "edb_lane_service 状态只读"),
    # em_family（EM 族判读，runs/ 只读）
    "em_doctor_check": _Entry(READ_ONLY, "em_doctor_service manifest 只读体检"),
    "runs_verify": _Entry(READ_ONLY, "runs_verify_service 产物新鲜度校验只读"),
    "em_diff_runs": _Entry(READ_ONLY, "em_diff_service 双 run 差异只读"),
    "em_metrics_from_run": _Entry(READ_ONLY, "em_metrics_service 指标提取只读"),
    "em_sweep_plan": _Entry(READ_ONLY, "em_sweep_service 扫频计划纯计算"),
    # mo / al / competition / surrogate
    "mo_run": _Entry(
        READ_ONLY, "mo_bo_service 合成族 BO 环进程内纯计算零落盘（既有注解 readOnlyHint 未声明，相容）"
    ),
    "al_propose": _Entry(
        MUTATING_NON_DESTRUCTIVE, "al_service.al_propose 候选集 tmp 文件落盘（write_text）"
    ),
    "competition_run": _Entry(
        READ_ONLY, "competition_service 合成问题竞赛评估纯计算零落盘"
    ),
    "surrogate_export_onnx": _Entry(
        MUTATING_NON_DESTRUCTIVE, "surrogate_export_service ONNX 模型文件落盘"
    ),
    "surrogate_uq": _Entry(
        READ_ONLY, "uq_service.surrogate_yield MC 计算纯读 samples"
    ),
    # ads（ADS 前仿链）
    "ads_circuit_diagram": _Entry(
        MUTATING_NON_DESTRUCTIVE, "circuit_sim_service.generate_circuit_diagram 网表/原理图文件写出"
    ),
    "ads_circuit_run": _Entry(
        LONG_RUNNING, "circuit_sim_service.circuit_sim_run 写工作目录+发射 hpeesofsim 求解"
    ),
    "ads_circuit_annotate": _Entry(
        MUTATING_NON_DESTRUCTIVE, "circuit_sim_service.annotate_circuit_diagram 反标注文件写出"
    ),
    # parser_formats（格式解析，只读）
    "spice_netlist_parse": _Entry(READ_ONLY, "spice_netlist_service 网表只读解析"),
    "liberty_parse": _Entry(READ_ONLY, "liberty_service 时序库只读解析"),
    "citi_info": _Entry(READ_ONLY, "citi_service 文件只读"),
    "sdc_parse": _Entry(READ_ONLY, "sdc_service 约束只读解析"),
    "ibis_parse": _Entry(READ_ONLY, "ibis_service 模型只读解析"),
    "verilog_netlist_parse": _Entry(READ_ONLY, "verilog_netlist_service 只读解析"),
    "drc_rules_parse": _Entry(READ_ONLY, "drc_service 规则只读解析"),
    "lvs_compare_files": _Entry(READ_ONLY, "lvs_compare_service 双网表比对只读"),
    # cad_formats（CAD 格式解析，只读）
    "spef_parse": _Entry(READ_ONLY, "spef_service 寄生只读解析"),
    "spef_report": _Entry(READ_ONLY, "spef_service 报告只读"),
    "lef_def_parse": _Entry(READ_ONLY, "lef_def_service 只读解析"),
    "sdf_parse": _Entry(READ_ONLY, "sdf_service 时序只读解析"),
    "sdf_report": _Entry(READ_ONLY, "sdf_service 报告只读"),
    "gdsii_parse": _Entry(READ_ONLY, "gdsii_service 版图只读解析"),
    "gerber_excellon_pair_check": _Entry(READ_ONLY, "fab_gerber_service 配对校验只读"),
    "ipc356_report": _Entry(READ_ONLY, "ipc356_service 报告只读"),
    "touchstone_info": _Entry(READ_ONLY, "touchstone_service 文件只读"),
    "vcd_parse": _Entry(READ_ONLY, "vcd_service 波形只读解析"),
    # parser_queries（解析后查询，只读）
    "gdsii_layers": _Entry(READ_ONLY, "gdsii_service 层报告只读"),
    "gdsii_hierarchy": _Entry(READ_ONLY, "gdsii_service 层级报告只读"),
    "vcd_report": _Entry(READ_ONLY, "vcd_service 报告只读"),
    "sdf_cell_detail": _Entry(READ_ONLY, "sdf_service 单元明细只读"),
    "spef_net_detail": _Entry(READ_ONLY, "spef_service 网络明细只读"),
    "ipc356_fab_pair_check": _Entry(READ_ONLY, "ipc356_service 制造配对校验只读"),
    "lef_def_check": _Entry(READ_ONLY, "lef_def_service 校验只读"),
    "stil_pattern_detail": _Entry(READ_ONLY, "stil_service 图案明细只读"),
    # packaging_test（封装测试报告，只读）
    "odbpp_report": _Entry(READ_ONLY, "odbpp_service 报告只读"),
    "bsdl_report": _Entry(READ_ONLY, "bsdl_service 报告只读"),
    "bsdl_boundary_detail": _Entry(READ_ONLY, "bsdl_service 边界明细只读"),
    # aedt_migrate（aurora_r AM-S4，老版本 .aedt 批量迁移通道）
    "aedt_migrate_run": _Entry(
        MUTATING_NON_DESTRUCTIVE,
        "migrate_batch 落 inventory+reports 写 work_root（原 .aedt 只读，零删除既有产物）",
    ),
    "aedt_migrate_report": _Entry(READ_ONLY, "read_migration_report 报告文件只读"),
    # parser_ext（aurora_r R-26 解析五批扩展，只读）
    "drc_design_validate": _Entry(READ_ONLY, "drc_service 校验只读"),
    "veriloga_module_detail": _Entry(READ_ONLY, "veriloga_service 模块明细只读"),
    "skill_call_graph": _Entry(READ_ONLY, "skill_service 调用图只读"),
    "netlist_overlay_file": _Entry(READ_ONLY, "netlist_overlay_service 语义标注只读"),
    "spectre_overlay_file": _Entry(READ_ONLY, "netlist_overlay_service Spectre 语义标注只读"),
    "netlist_overlay_text": _Entry(READ_ONLY, "netlist_overlay_service 文本语义标注只读"),
}


# ─── 装配层注入 ─────────────────────────────────────────────────────────────


def readonly_tool_names() -> list[str]:
    """声明 read_only 的工具名（排序返回；静态互证测试的判定面）。"""
    return sorted(n for n, e in _TOOLS.items() if e.category is READ_ONLY)


def classification_snapshot() -> dict[str, str]:
    """全部工具的类别名快照（测试/报表消费；键排序）。"""
    return {n: e.category.key for n, e in sorted(_TOOLS.items())}


def _tool_components() -> dict[str, Any]:
    """name → FunctionTool 组件（fastmcp LocalProvider 注册表，key=tool:<name>@）。"""
    comps = getattr(getattr(_mcp, "_local_provider", None), "_components", None)
    if not isinstance(comps, dict):
        return {}
    out: dict[str, Any] = {}
    for key, comp in comps.items():
        if isinstance(key, str) and key.startswith("tool:") and "@" in key:
            out[key[len("tool:") :].split("@", 1)[0]] = comp
    return out


def apply_tool_annotations() -> dict[str, Any]:
    """给未注解工具原地挂 ToolAnnotations（装配层调用；幂等）。

    - 只写 ``annotations`` 字段：注入前后对 (name, description, parameters,
      output_schema) 全量指纹自证，不一致即 RuntimeError（零行为变化守卫）；
    - 已有装饰器注解（20 个）跳过不覆盖；表中无对应组件的陈旧条目与组件
      无表条目的缺登**均不在此处 raise**（保持 import 零炸），由
      tests/unit/test_mcp_annotations_readonly.py 的棘轮/覆盖钉裁决。
    """
    comps = _tool_components()
    before = {
        name: (
            getattr(c, "name", None),
            getattr(c, "description", None),
            repr(getattr(c, "parameters", None)),
            repr(getattr(c, "output_schema", None)),
        )
        for name, c in comps.items()
    }
    injected: list[str] = []
    skipped_preannotated: list[str] = []
    missing_in_table: list[str] = []
    for name, comp in comps.items():
        entry = _TOOLS.get(name)
        if entry is None:
            missing_in_table.append(name)
            continue
        if getattr(comp, "annotations", None) is not None:
            skipped_preannotated.append(name)
            continue
        comp.annotations = ToolAnnotations(**_derived_hints(entry))
        injected.append(name)
    after = {
        name: (
            getattr(c, "name", None),
            getattr(c, "description", None),
            repr(getattr(c, "parameters", None)),
            repr(getattr(c, "output_schema", None)),
        )
        for name, c in comps.items()
    }
    drifted = sorted(n for n in before if before[n] != after[n])
    if drifted:
        raise RuntimeError(
            "apply_tool_annotations 注入前后工具元数据漂移（禁改面被触碰）: "
            f"{drifted[:10]}"
        )
    stale = sorted(n for n in _TOOLS if n not in comps)
    return {
        "n_components": len(comps),
        "n_table": len(_TOOLS),
        "injected": injected,
        "skipped_preannotated": skipped_preannotated,
        "missing_in_table": missing_in_table,
        "stale_table_entries": stale,
        "meta_drift": [],
    }
