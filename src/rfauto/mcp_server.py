"""MCP Server（§7.7）—— fastmcp 首版 7 个核心工具。

设计红线：
- mutating 工具必须显式描述副作用
- 不提供 delete 类破坏性工具
- 所有工具返回 {ok, data|error} 信封
- input schema 直接复用 pydantic 生成的 JSON Schema
- 写操作受 JobRegistry/单写约束；长仿真用 create_run_async（C3 修复）
"""

# ══ AU-1 巨石拆分 facade（2026-09-30 批3）════════════════════════
# 本文件原为 3.4k 行巨石，实现拆分至 mcp_tools/ 包（_core/basic/jobs/
# …/agent2）。此处逐名显式 re-export 全部模块级名（公开面快照钉：拆分
# 前后 dir() 逐名相等；redundant-alias=PEP 484 显式 re-export 惯例）。
#
# 注册顺序=下面 re-export from-import 语句顺序（首条 from-import 触发
# 工具组模块导入即注册 @mcp.tool）——isort 会按字母重排致注册序漂移，
# 故本文件 isort: skip_file。
# isort: skip_file

from __future__ import annotations

import json as json  # facade：保持原模块公开面（快照钉）
from collections.abc import AsyncIterator as AsyncIterator
from contextlib import asynccontextmanager as asynccontextmanager
from pathlib import Path as Path
from typing import Any as Any

from fastmcp import FastMCP as FastMCP

from rfauto.service.envelope import error_envelope as error_envelope
from rfauto.service.envelope import ok_envelope as ok_envelope

from rfauto.mcp_tools._core import _run_model_name as _run_model_name
from rfauto.mcp_tools._core import _server_lifespan as _server_lifespan
from rfauto.mcp_tools._core import _silence_pyaedt_screen_logs as _silence_pyaedt_screen_logs
from rfauto.mcp_tools._core import mcp as mcp

from rfauto.mcp_tools.basic import doctor as doctor
from rfauto.mcp_tools.basic import list_models as list_models
from rfauto.mcp_tools.basic import validate_recipe as validate_recipe
from rfauto.mcp_tools.jobs import cancel_job as cancel_job
from rfauto.mcp_tools.jobs import create_run as create_run
from rfauto.mcp_tools.jobs import create_run_async as create_run_async
from rfauto.mcp_tools.jobs import get_metrics as get_metrics
from rfauto.mcp_tools.jobs import poll_job as poll_job
from rfauto.mcp_tools.jobs import wait_job as wait_job
from rfauto.mcp_tools.synth import budget_analysis as budget_analysis
from rfauto.mcp_tools.synth import cascade_budget as cascade_budget
from rfauto.mcp_tools.synth import if_plan_sweep as if_plan_sweep
from rfauto.mcp_tools.synth import spur_search as spur_search
from rfauto.mcp_tools.synth import synthesize as synthesize
from rfauto.mcp_tools.synth import synthesize_bpf as synthesize_bpf
from rfauto.mcp_tools.diagnose import cm_cat_critique as cm_cat_critique
from rfauto.mcp_tools.diagnose import cm_diagnose_q as cm_diagnose_q
from rfauto.mcp_tools.diagnose import cm_extract_refine as cm_extract_refine
from rfauto.mcp_tools.diagnose import correlate_measurement as correlate_measurement
from rfauto.mcp_tools.runs import compare_runs as compare_runs
from rfauto.mcp_tools.runs import diagnose as diagnose
from rfauto.mcp_tools.runs import get_model_3d as get_model_3d
from rfauto.mcp_tools.runs import get_run_artifacts as get_run_artifacts
from rfauto.mcp_tools.runs import list_calculators as list_calculators
from rfauto.mcp_tools.runs import run_calculator as run_calculator
from rfauto.mcp_tools.specs_campaign import draft_recipe_from_spec as draft_recipe_from_spec
from rfauto.mcp_tools.specs_campaign import get_campaign_status as get_campaign_status
from rfauto.mcp_tools.specs_campaign import list_template_specs as list_template_specs
from rfauto.mcp_tools.specs_campaign import plan_campaign as plan_campaign
from rfauto.mcp_tools.specs_campaign import run_campaign as run_campaign
from rfauto.mcp_tools.specs_campaign import save_campaign_plan as save_campaign_plan
from rfauto.mcp_tools.datasets import discover_workdir_runs as discover_workdir_runs
from rfauto.mcp_tools.datasets import import_workdir_runs as import_workdir_runs
from rfauto.mcp_tools.datasets import list_datasets as list_datasets
from rfauto.mcp_tools.datasets import query_dataset as query_dataset
from rfauto.mcp_tools.bands import bands_env_delta_t as bands_env_delta_t
from rfauto.mcp_tools.bands import bands_env_find as bands_env_find
from rfauto.mcp_tools.bands import bands_env_get as bands_env_get
from rfauto.mcp_tools.bands import bands_env_list as bands_env_list
from rfauto.mcp_tools.bands import bands_env_points as bands_env_points
from rfauto.mcp_tools.bands import bands_env_uq_axis as bands_env_uq_axis
from rfauto.mcp_tools.bands import bands_find as bands_find
from rfauto.mcp_tools.bands import bands_get as bands_get
from rfauto.mcp_tools.bands import bands_list as bands_list
from rfauto.mcp_tools.bands import bands_spec_bounds as bands_spec_bounds
from rfauto.mcp_tools.report_bench import agentbench_regression as agentbench_regression
from rfauto.mcp_tools.report_bench import export_report_pdf as export_report_pdf
from rfauto.mcp_tools.report_bench import goldset_regression as goldset_regression
from rfauto.mcp_tools.report_bench import warm_start_optimize as warm_start_optimize
from rfauto.mcp_tools.agent import autotune_self_verify as autotune_self_verify
from rfauto.mcp_tools.agent import multi_agent_run as multi_agent_run
from rfauto.mcp_tools.agent import rf_critique_point as rf_critique_point
from rfauto.mcp_tools.agent import rf_propose_params as rf_propose_params
from rfauto.mcp_tools.agent import rf_run_sampler as rf_run_sampler
from rfauto.mcp_tools.agent import rf_spec_cost as rf_spec_cost
from rfauto.mcp_tools.uq import robustness_report as robustness_report
from rfauto.mcp_tools.uq import uq_design_center as uq_design_center
from rfauto.mcp_tools.uq import uq_temperature_zone as uq_temperature_zone
from rfauto.mcp_tools.uq import uq_yield_at as uq_yield_at
from rfauto.mcp_tools.farfield_kicad import farfield_runs as farfield_runs
from rfauto.mcp_tools.farfield_kicad import farfield_view as farfield_view
from rfauto.mcp_tools.farfield_kicad import kicad_extract as kicad_extract
from rfauto.mcp_tools.farfield_kicad import kicad_optimize_cpw as kicad_optimize_cpw
from rfauto.mcp_tools.multiphysics import electrothermal_chain as electrothermal_chain
from rfauto.mcp_tools.multiphysics import parasitic_extract_rlc as parasitic_extract_rlc
from rfauto.mcp_tools.multiphysics import topology_propose as topology_propose
from rfauto.mcp_tools.datasets_ops import dataset_annotate_ground_truth as dataset_annotate_ground_truth
from rfauto.mcp_tools.datasets_ops import dataset_coverage as dataset_coverage
from rfauto.mcp_tools.datasets_ops import dataset_export_hf as dataset_export_hf
from rfauto.mcp_tools.datasets_ops import dataset_set_visibility as dataset_set_visibility
from rfauto.mcp_tools.vna import report_narrative as report_narrative
from rfauto.mcp_tools.vna import vna_en_report as vna_en_report
from rfauto.mcp_tools.vna import vna_offline_replay as vna_offline_replay
from rfauto.mcp_tools.rationale import rag_explain as rag_explain
from rfauto.mcp_tools.rationale import rag_query as rag_query
from rfauto.mcp_tools.rationale import rationale_checklist as rationale_checklist
from rfauto.mcp_tools.rationale import rationale_recall as rationale_recall
from rfauto.mcp_tools.ops import dispersion_report as dispersion_report
from rfauto.mcp_tools.ops import log_digest as log_digest
from rfauto.mcp_tools.ops import self_heal_run as self_heal_run
from rfauto.mcp_tools.db import db_analytics_attach as db_analytics_attach
from rfauto.mcp_tools.db import db_init as db_init
from rfauto.mcp_tools.db import db_migrate as db_migrate
from rfauto.mcp_tools.db import db_query as db_query
from rfauto.mcp_tools.db import db_reindex_runs as db_reindex_runs
from rfauto.mcp_tools.db import db_status as db_status
from rfauto.mcp_tools.slotline import marchand_balun_design as marchand_balun_design
from rfauto.mcp_tools.slotline import marchand_two_section_synthesis as marchand_two_section_synthesis
from rfauto.mcp_tools.slotline import msl_slot_transition_design as msl_slot_transition_design
from rfauto.mcp_tools.slotline import slotline_analysis as slotline_analysis
from rfauto.mcp_tools.slotline import slotline_synthesis as slotline_synthesis
from rfauto.mcp_tools.guidelines import get_guidelines_for as get_guidelines_for
from rfauto.mcp_tools.resources import compat_matrix_resource as compat_matrix_resource
from rfauto.mcp_tools.resources import materials_resource as materials_resource
from rfauto.mcp_tools.resources import runs_index_resource as runs_index_resource
from rfauto.mcp_tools.resources import terminology_resource as terminology_resource
from rfauto.mcp_tools.resources import toolsets_definition_resource as toolsets_definition_resource
from rfauto.mcp_tools.mmt import compose_netlist as compose_netlist
from rfauto.mcp_tools.mmt import mmt_solve as mmt_solve
from rfauto.mcp_tools.nfmeas import nfc_coil_evaluate as nfc_coil_evaluate
from rfauto.mcp_tools.nfmeas import nfc_coil_q as nfc_coil_q
from rfauto.mcp_tools.nfmeas import nfc_coil_synthesize as nfc_coil_synthesize
from rfauto.mcp_tools.nfmeas import nfmeas_cut_view as nfmeas_cut_view
from rfauto.mcp_tools.nfmeas import nfmeas_ffs_info as nfmeas_ffs_info
from rfauto.mcp_tools.nfmeas import sar_analytic_plane_wave as sar_analytic_plane_wave
from rfauto.mcp_tools.explain import explain_run as explain_run
from rfauto.mcp_tools.explain import list_composable_templates as list_composable_templates
from rfauto.mcp_tools.anchors import anchors_inspect as anchors_inspect
from rfauto.mcp_tools.anchors import anchors_list as anchors_list
from rfauto.mcp_tools.si_lake import lake_pack_campaign as lake_pack_campaign
from rfauto.mcp_tools.si_lake import lake_query_runs as lake_query_runs
from rfauto.mcp_tools.si_lake import si_channel_report as si_channel_report
from rfauto.mcp_tools.certify import certify_design as certify_design
from rfauto.mcp_tools.certify import import_solid_payload as import_solid_payload
from rfauto.mcp_tools.certify import port_gate as port_gate
from rfauto.mcp_tools.certify import render_constraint_check as render_constraint_check
from rfauto.mcp_tools.knowledge import search_knowledge as search_knowledge
from rfauto.mcp_tools.pdn import pdn_analyze as pdn_analyze
from rfauto.mcp_tools.pdn import pdn_gate as pdn_gate
from rfauto.mcp_tools.pdn import pdn_select as pdn_select
from rfauto.mcp_tools.aging import aging_report as aging_report
from rfauto.mcp_tools.aging import aging_simulate as aging_simulate
from rfauto.mcp_tools.aging import aging_verdict as aging_verdict
from rfauto.mcp_tools.afs_interop import afs_plan as afs_plan
from rfauto.mcp_tools.afs_interop import read_hfss_touchstone_comments as read_hfss_touchstone_comments
from rfauto.mcp_tools.remote import remote_machine_status as remote_machine_status
from rfauto.mcp_tools.remote import remote_probe_machine as remote_probe_machine
from rfauto.mcp_tools.agent2 import even_odd_report as even_odd_report
from rfauto.mcp_tools.agent2 import inverse_prefilter as inverse_prefilter
from rfauto.mcp_tools.agent2 import mcts_search as mcts_search
from rfauto.mcp_tools.adc import adc_interleave_spurs as adc_interleave_spurs
from rfauto.mcp_tools.adc import jitter_budget_snr as jitter_budget_snr
from rfauto.mcp_tools.emc import emc_cm_radiated_budget as emc_cm_radiated_budget
from rfauto.mcp_tools.emc import emc_cispr_band_params as emc_cispr_band_params
from rfauto.mcp_tools.emc import emc_cispr_detect as emc_cispr_detect
from rfauto.mcp_tools.emc import emc_ground_spacing_check as emc_ground_spacing_check
from rfauto.mcp_tools.metasurface import metasurface_coding_pattern as metasurface_coding_pattern
from rfauto.mcp_tools.metasurface import metasurface_quant_loss_db as metasurface_quant_loss_db
from rfauto.mcp_tools.si_lake import com_pam4_run as com_pam4_run

# ─── env_reliability 工具组（F-10 六服务壳接线批 W3-D，Phase 3：+8 工具； ──
# aging.py 单组先例一文件承载；追加于 facade 尾=注册序末尾（append-only
# 金快照 diff 最小化；_normalize_tool_registration_order 按 from-import
# 源序自动收录新模块，无需改 canon 逻辑）。
from rfauto.mcp_tools.env_reliability import build_datasheet as build_datasheet
from rfauto.mcp_tools.env_reliability import cryo_surface_estimate as cryo_surface_estimate
from rfauto.mcp_tools.env_reliability import fault_tree_report as fault_tree_report
from rfauto.mcp_tools.env_reliability import humidity_uptake as humidity_uptake
from rfauto.mcp_tools.env_reliability import msl_floor_life_query as msl_floor_life_query
from rfauto.mcp_tools.env_reliability import netlist_goldset_replay as netlist_goldset_replay
from rfauto.mcp_tools.env_reliability import weave_skew_estimate as weave_skew_estimate
from rfauto.mcp_tools.env_reliability import weave_style_info as weave_style_info

# ─── preflight 工具（D-07 MCP 面挂点，W6-E：+1 工具；追加于 facade 尾= ──────
# 注册序末尾（append-only 金快照 diff 最小化惯例同 env_reliability 组）。
from rfauto.mcp_tools.preflight import preflight_run as preflight_run

# ─── tune/sweep 主优化入口（SN-16，W6-A：+2 工具；append-only 同上惯例）────
from rfauto.mcp_tools.optim import run_sweep as run_sweep
from rfauto.mcp_tools.optim import start_tune as start_tune



# ══ ge8d-D6 注册幂等化（2026-10-03，定位报告 runs/ge8d_mcp_order）═══
# 根因：@mcp.tool 注册是工具组模块**首次 import** 的装饰器副作用——注册序
# =各工具组模块的首次执行序。金快照（tests/gold/mcp_registration_order.json）
# 钉的是本文件 from-import 语句顺序（facade 序；isort: skip_file 保证源序
# =执行序）。一旦任何代码在 facade 之前 import 了某个 rfauto.mcp_tools.*
# 子模块，该组工具即先于 facade 顺序落位、注册序偏离金快照——实测触发面=
# 测试收集期 test_mcp_longtask_wait.py 的模块级 ``from rfauto.mcp_tools
# import jobs``（b74ec8cc 2026-10-03 落地；pytest 收集阶段 eager import
# 全部测试模块，先于一切测试执行），症状即"组合跑红/单跑绿/同命令两轮
# 不同结果"的顺序敏感偶发。
# 对策：facade import 收尾按本文件 from-import 语句序对工具做**稳定重排**
# （注册幂等化）——任意 import 顺序收敛到同一 facade 注册序；组内工具相对
# 序由稳定排序保持；非工具组件（resource/prompt/template）整块后置且相互
# 相对序不变（list_resources/list_prompts 按类型过滤，跨类相对位无消费
# 者）。干净路径（facade 先行 import，生产入口恒如此）排序结果=原序，
# 逐位 no-op。金快照断言不动（test_cli_registration_order 断言语义禁改）。

def _normalize_tool_registration_order() -> None:
    """按 facade from-import 语句序稳定重排工具注册序（注册幂等化）。"""
    import ast

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    canon: list[str] = []
    for node in tree.body:  # 模块体顶层 from-import（源序=执行序）
        if (isinstance(node, ast.ImportFrom) and node.module
                and node.module.startswith("rfauto.mcp_tools.")
                and node.module not in canon):
            canon.append(node.module)
    comps = getattr(getattr(mcp, "_local_provider", None), "_components", None)
    if not canon or not isinstance(comps, dict):
        return  # fastmcp 内部结构变更→退化为修复前行为（金快照门兜底）
    n_canon = len(canon)

    def _order(item: tuple[str, Any]) -> tuple[int, int]:
        key, comp = item
        if key.startswith("tool:"):
            mod = getattr(getattr(comp, "fn", None), "__module__", "")
            return (0, canon.index(mod) if mod in canon else n_canon)
        return (1, 0)  # 非工具组件：整块后置，组内相对序由稳定排序保持

    ordered = sorted(comps.items(), key=_order)
    comps.clear()
    comps.update(ordered)


_normalize_tool_registration_order()


def get_mcp_server() -> FastMCP:
    """获取 MCP Server 实例。"""
    return mcp


def main() -> None:
    """console script 入口（pyproject ``[project.scripts] rfauto-mcp``）：
    stdio 传输启动 MCP Server。与 ``python -m rfauto.mcp_server`` 同源。

    保持零参数、零 stdout 打印：stdio 传输把 stdout 当协议信道，任何
    额外输出都会污染 JSON-RPC 帧（F4 发布口径）。
    """
    mcp.run(transport="stdio")


if __name__ == "__main__":
    # 直接运行时启动 stdio 传输
    main()
