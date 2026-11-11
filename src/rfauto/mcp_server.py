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
from rfauto.mcp_tools.report_bench import design_report as design_report
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
from rfauto.mcp_tools.resources import calculators_index_resource as calculators_index_resource
from rfauto.mcp_tools.resources import compat_matrix_resource as compat_matrix_resource
from rfauto.mcp_tools.resources import datasets_index_resource as datasets_index_resource
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
# T-Q3 接线席 Q-W5-2R（aurora_q 方向 B，2026-11-04）：动图渲染 agent 面
# （CLI anim render 同源同名 service 函数；166→167 计数链同笔）
from rfauto.mcp_tools.anim import anim_render as anim_render
# T-Q5 接线席 Q-W9-3（aurora_q 方向 C，2026-11-06）：格式速览 agent 面
# （T-Q5 批 3 "MCP 工具化"列项——速览层只读零副作用故不上 CLI 叶，
# Agent 直读面；167→171 计数链大合笔同笔）
from rfauto.mcp_tools.format_overview import format_overview as format_overview
# T-Q19 批 2 接线席 Q-W9-3（aurora_q，2026-11-06）：厂商帮助文档检索
# agent 面（Q-W6-4 service 三函数薄壳；build=显式 db_path 写索引库，
# search/audit 只读；167→171 计数链大合笔同笔）
from rfauto.mcp_tools.vendor_docs import vendor_docs_audit as vendor_docs_audit
from rfauto.mcp_tools.vendor_docs import vendor_docs_build as vendor_docs_build
from rfauto.mcp_tools.vendor_docs import vendor_docs_search as vendor_docs_search
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


# ─── edb 快车道工具组（CLI 出口同批，2026-10-08：+3 工具；append-only ────
# 金快照 diff 最小化惯例同 env_reliability/preflight 组（facade 尾=注册序
# 末尾；_normalize_tool_registration_order 按 from-import 源序自动收录）。
from rfauto.mcp_tools.edb import edb_build_solve as edb_build_solve
from rfauto.mcp_tools.edb import edb_emit_spec as edb_emit_spec
from rfauto.mcp_tools.edb import edb_status as edb_status

# edb 资源两件 re-export（2026-10-08：rfauto://edb/status 与
# rfauto://edb/datasets，@mcp.resource 挂本组模块随上三行首导注册；
# 不计入工具数，非工具组件归一化整块后置）。**禁前移**到上方 resources
# 组——from-import 源序=模块首导序，前移会把本组三工具注册序整体带前，
# 金快照 tool_names_order 即漂。
from rfauto.mcp_tools.edb import edb_datasets_resource as edb_datasets_resource
from rfauto.mcp_tools.edb import edb_status_resource as edb_status_resource

# ─── em 族五只读薄壳（aurora_l Wave-C C1，2026-10-23：+5 工具；append-only ──
# 金快照 diff 最小化惯例同 env_reliability/preflight/edb 组（facade 尾=注册
# 序末尾）。零逻辑转发 em_doctor/runs_verify/em_diff/em_metrics/em_sweep
# service 单源；sweep 执行面不上 MCP（v1 只读 plan 面，反馈 F5）。
from rfauto.mcp_tools.em_family import em_diff_runs as em_diff_runs
from rfauto.mcp_tools.em_family import em_doctor_check as em_doctor_check
from rfauto.mcp_tools.em_family import em_metrics_from_run as em_metrics_from_run
from rfauto.mcp_tools.em_family import em_sweep_plan as em_sweep_plan
from rfauto.mcp_tools.em_family import runs_verify as runs_verify

# ─── mo_run 多目标 BO 合成族环（aurora_n O1 接线席，2026-10-31：+1 工具；
# append-only 金快照 diff 最小化惯例同 env_reliability/preflight/edb/em 组
# （facade 尾=注册序末尾）。零数值逻辑转发 service/mo_bo_service（T-N13
# MultiObjectiveBO 运行时门——zero_wiring REGISTRY O1 欠账清偿）。
from rfauto.mcp_tools.mo import mo_run as mo_run

# ─── aurora_n MCP 接线补齐席（2026-10-31：+4 工具；append-only 金快照 ──
# diff 最小化惯例同 mo 组（facade 尾=注册序末尾）。zero_wiring 登记欠账
# 清偿：T-N20 ONNX 导出+代理 MC UQ（CLI surrogate 域同源，双入口组）+
# al_propose（O4 T-N9 采集三族运行时门）+ competition_run（O5 T-N5 标量
# 竞赛架运行时门；持久落盘面留 CLI 叶，MCP 零写盘）。零逻辑转发 service
# 单源：surrogate_export_service/uq_service/al_service/competition_service。
from rfauto.mcp_tools.al import al_propose as al_propose
from rfauto.mcp_tools.competition import competition_run as competition_run
from rfauto.mcp_tools.surrogate import (
    surrogate_export_onnx as surrogate_export_onnx)
from rfauto.mcp_tools.surrogate import surrogate_uq as surrogate_uq

# ─── ADS 前仿链 MCP 三工具（aurora_o 开放池席 o_ads 件4，2026-11-01： ──
# +2 工具 diagram/run；aurora_p 席 B2 2026-11-01 补 annotate 反标注面
# （§5.1 v2 扩展位落位）=3 工具；append-only 金快照 diff 最小化惯例同
# mo/aurora_n 组（facade 尾=注册序末尾）。T-O4_ADS_UX_SPEC §5.1——CLI
# ads-circuit 域同源三入口（diagram/run/annotate）。零逻辑转发 service/
# circuit_sim_service（信封同构；annotate 离线重放面）。
from rfauto.mcp_tools.ads import ads_circuit_diagram as ads_circuit_diagram
from rfauto.mcp_tools.ads import ads_circuit_run as ads_circuit_run
from rfauto.mcp_tools.ads import ads_circuit_annotate as ads_circuit_annotate


# ─── EDA 格式解析八域 MCP 工具组（aurora_q Q-X69 席位，2026-11-08：+8 ──
# 工具；append-only 金快照 diff 最小化惯例同 env_reliability/preflight/
# edb/em/ads 组（facade 尾=注册序末尾）。Q-X33..X36+Q-X46..X49 八域解析
# 器（SPICE/Liberty/CITI/SDC/IBIS/Verilog/DRC/LVS）service+CLI 双面已
# 交付、MCP 面本组补齐：零逻辑转发各域 service 单函数（只读零副作用，
# 信封进出在 service）；大输出裁面走 service 自带过滤/截断旋钮。在飞
# 九域（spef/lefdef/sdf/gdsii/fab/ipc356/touchstone/skill/vcd）不在本
# 组——归后续接线席。
from rfauto.mcp_tools.parser_formats import citi_info as citi_info
from rfauto.mcp_tools.parser_formats import drc_rules_parse as drc_rules_parse
from rfauto.mcp_tools.parser_formats import ibis_parse as ibis_parse
from rfauto.mcp_tools.parser_formats import liberty_parse as liberty_parse
from rfauto.mcp_tools.parser_formats import lvs_compare_files as lvs_compare_files
from rfauto.mcp_tools.parser_formats import sdc_parse as sdc_parse
from rfauto.mcp_tools.parser_formats import spice_netlist_parse as spice_netlist_parse
from rfauto.mcp_tools.parser_formats import verilog_netlist_parse as verilog_netlist_parse


# ─── CAD 制造/数字后端/波形十域 MCP 工具组（aurora_q Q-X73 席位， ──
# 2026-11-08：+10 工具；append-only 金快照 diff 最小化惯例同
# parser_formats/env_reliability/preflight/edb/em/ads 组（facade 尾=
# 注册序末尾）。Q-X73 二批：在飞九域（spef/lefdef/sdf/gdsii/fab/
# ipc356/touchstone/vcd）service+CLI 双面已交付、MCP 面本组补齐（照抄
# Q-X69 parser_formats.py 单组先例）：零逻辑转发各域 service 单函数
# （只读零副作用，信封进出在 service）；截断旋钮 spef_report top_k。
from rfauto.mcp_tools.cad_formats import gdsii_parse as gdsii_parse
from rfauto.mcp_tools.cad_formats import gerber_excellon_pair_check as gerber_excellon_pair_check
from rfauto.mcp_tools.cad_formats import ipc356_report as ipc356_report
from rfauto.mcp_tools.cad_formats import lef_def_parse as lef_def_parse
from rfauto.mcp_tools.cad_formats import sdf_parse as sdf_parse
from rfauto.mcp_tools.cad_formats import sdf_report as sdf_report
from rfauto.mcp_tools.cad_formats import spef_parse as spef_parse
from rfauto.mcp_tools.cad_formats import spef_report as spef_report
from rfauto.mcp_tools.cad_formats import touchstone_info as touchstone_info
from rfauto.mcp_tools.cad_formats import vcd_parse as vcd_parse


# ─── EDA 格式解析二线查询/校验 MCP 工具组（aurora_q Q-X76 席位， ──
# 2026-11-08：+8 工具；append-only 金快照 diff 最小化惯例同
# parser_formats/cad_formats 组（facade 尾=注册序末尾）。Q-X76 三批：
# 解析器集群二线只读 service 函数（查询/校验面）MCP 补齐、完成全集群
# 只读面收官（照抄 Q-X69/Q-X73 单组先例）：零逻辑转发各域 service 单
# 函数（只读零副作用，信封进出在 service）；截断旋钮 vcd_report top_n；
# gdsii_hierarchy/sdf_cell_detail/spef_net_detail/stil_pattern_detail
# 系 service 二线查询面（无 CLI 叶）首次 agent 面暴露。
from rfauto.mcp_tools.parser_queries import gdsii_hierarchy as gdsii_hierarchy
from rfauto.mcp_tools.parser_queries import gdsii_layers as gdsii_layers
from rfauto.mcp_tools.parser_queries import ipc356_fab_pair_check as ipc356_fab_pair_check
from rfauto.mcp_tools.parser_queries import lef_def_check as lef_def_check
from rfauto.mcp_tools.parser_queries import sdf_cell_detail as sdf_cell_detail
from rfauto.mcp_tools.parser_queries import spef_net_detail as spef_net_detail
from rfauto.mcp_tools.parser_queries import stil_pattern_detail as stil_pattern_detail
from rfauto.mcp_tools.parser_queries import vcd_report as vcd_report


# ─── 封装/测试封装域 MCP 三工具（aurora_q Q-X85 四批小席，2026-11-08： ──
# +3 工具（197→200）；append-only 金快照 diff 最小化惯例同
# parser_formats/cad_formats/parser_queries 组（facade 尾=注册序末尾）。
# odbpp/bsdl 两域（Q-X68/X77 交付）MCP 面补齐：零逻辑转发 service 单源
# （odbpp_service/bsdl_service，信封进出在 service）；与 CLI
# ``rfauto odbpp report``/``rfauto bsdl report`` 同源同名；
# bsdl_boundary_detail 系 service 二线查询面（无 CLI 叶）首次 agent 面
# 暴露。
from rfauto.mcp_tools.packaging_test import bsdl_boundary_detail as bsdl_boundary_detail
from rfauto.mcp_tools.packaging_test import bsdl_report as bsdl_report
from rfauto.mcp_tools.packaging_test import odbpp_report as odbpp_report

# ─── aedt_migrate 批量迁移通道 MCP 两薄壳（aurora_r AM-S4 席位， ──────────
# 2026-11-10：+2 工具（200→202）；append-only 金快照 diff 最小化惯例同
# packaging_test 组（facade 尾=注册序末尾）。S1 service docstring 挂账
# 处方原文落位：aedt_migrate_run（migrate_batch 编排，写 work_root，
# 注解 mutating_non_destructive）+ aedt_migrate_report（read_migration_
# report 报告全文只读）——与 CLI ``rfauto aedt-migrate run`` 同源。
from rfauto.mcp_tools.aedt_migrate import aedt_migrate_report as aedt_migrate_report
from rfauto.mcp_tools.aedt_migrate import aedt_migrate_run as aedt_migrate_run

# ─── EDA 格式解析五批扩展 MCP 工具组（aurora_r R-26 席位，2026-11-10：──
# +6 工具（202→208）；append-only 金快照 diff 最小化惯例同
# parser_formats/cad_formats/parser_queries/packaging_test 组（facade
# 尾=注册序末尾）。Q-X69 报告 §8 建议清单+交接书 §二-8 扩展池方向接地
# 差集：DRC validate 校验面锚（``rfauto drc validate`` 同源）+
# Verilog-A 单模块查询（veriloga 域 MCP 面零覆盖补齐）+SKILL 静态调用
# 图（Q-X69 九域清单 skill 域只读面二线查询锚，无 CLI 叶）+网表语义
# overlay 三件套（R-02 AX-2 三 service 函数零 agent 面）。全部复用既有
# service 函数零逻辑转发（只读零副作用，信封进出在 service）。
from rfauto.mcp_tools.parser_ext import drc_design_validate as drc_design_validate
from rfauto.mcp_tools.parser_ext import netlist_overlay_file as netlist_overlay_file
from rfauto.mcp_tools.parser_ext import netlist_overlay_text as netlist_overlay_text
from rfauto.mcp_tools.parser_ext import skill_call_graph as skill_call_graph
from rfauto.mcp_tools.parser_ext import spectre_overlay_file as spectre_overlay_file
from rfauto.mcp_tools.parser_ext import veriloga_module_detail as veriloga_module_detail

# ─── MCP 工具注解装配层注入（VB-1，aurora_r Wave2 席 R-10，2026-11-10）──
# 单源分类表 src/rfauto/mcp_tools/_annotations.py：四类（read_only /
# mutating_non_destructive / destructive / long_running）×两维（idempotent /
# open_world 可选）→ mcp ToolAnnotations。注入只写 annotations 字段——
# 工具名/注册序/描述/参数 schema 零触碰（注入函数内置前后元数据指纹自证，
# 漂移即 RuntimeError）；既有 20 个装饰器注解工具跳过保真。表覆盖与
# "未注解=0"棘轮由 tests/unit/test_mcp_annotations_readonly.py 裁决。
# 归位在 _normalize_tool_registration_order() 之后（注册幂等化先收敛，
# 注解对序零敏感）；import 置 facade 尾故 canon 序不变。
from rfauto.mcp_tools._annotations import (
    apply_tool_annotations as _apply_tool_annotations,
)

# ─── VB-6 SKILL 包 resources/prompts 暴露（aurora_r Wave2 席 R-13，──
# 2026-11-10）：skills/ 七包零新工具再暴露（提案源 runs/aurora_q/
# qx40_vbridge/PROPOSALS.md VB-6）。三件：①skill://<name>/SKILL.md 七
# 静态只读资源（@mcp.resource 装饰器行与 list_resources() 条目 1:1——
# R5-02 双口径同笔同移；包名字典序=注册序确定性）；②skill://{name}/
# references/{path*} 子路径模板（add_template 程序化注册——模板不进
# list_resources() 也不进 @mcp.resource 正则面，计数双口径零扰动）；
# ③三条工作流提示词（解析器集群使用流/EM bench 任务流/配方草稿捕获
# 流——既有工具调用序列固化，零物理数值字面量正则扫描钉）。
# 守卫单源 mcp_tools/_resources.py（穿越/越界/绝对路径/背斜杠/超 2MB/
# 缺失一律拒）；@mcp.tool 正则面零增量=工具数 200 不变。
from rfauto.mcp_tools._resources import em_bench_task_flow as em_bench_task_flow
from rfauto.mcp_tools._resources import list_skill_packages as list_skill_packages
from rfauto.mcp_tools._resources import read_skill_md as read_skill_md
from rfauto.mcp_tools._resources import read_skill_text as read_skill_text
from rfauto.mcp_tools._resources import (
    recipe_draft_capture_flow as recipe_draft_capture_flow,
)
from rfauto.mcp_tools._resources import resolve_skill_file as resolve_skill_file
from rfauto.mcp_tools._resources import (
    skill_md_rfauto_branchline_coupler_resource as skill_md_rfauto_branchline_coupler_resource,
)
from rfauto.mcp_tools._resources import (
    skill_md_rfauto_cpw_resource as skill_md_rfauto_cpw_resource,
)
from rfauto.mcp_tools._resources import (
    skill_md_rfauto_mline_synthesis_resource as skill_md_rfauto_mline_synthesis_resource,
)
from rfauto.mcp_tools._resources import (
    skill_md_rfauto_patch_antenna_resource as skill_md_rfauto_patch_antenna_resource,
)
from rfauto.mcp_tools._resources import (
    skill_md_rfauto_pifa_resource as skill_md_rfauto_pifa_resource,
)
from rfauto.mcp_tools._resources import (
    skill_md_rfauto_wilkinson_power_divider_resource as skill_md_rfauto_wilkinson_power_divider_resource,
)
from rfauto.mcp_tools._resources import (
    skill_md_veriloga_authoring_resource as skill_md_veriloga_authoring_resource,
)
from rfauto.mcp_tools._resources import (
    skill_parser_cluster_flow as skill_parser_cluster_flow,
)
from rfauto.mcp_tools._resources import (
    SkillResourceError as SkillResourceError,
)

# ─── VB-7 MCP 运行期护栏（aurora_r Wave2 席 R-14，2026-11-10）───────────────
# 单源 src/rfauto/mcp_tools/_ratelimit.py（提案源 runs/aurora_q/qx40_vbridge/
# PROPOSALS.md VB-7）：(a) StdioChannelPurityMiddleware——stdio 会话首个
# initialize 时（传输启动后，mcp 1.30.0 stdio_server 已自持
# sys.stdout.buffer 协议流）一次性把 Python 级 sys.stdout 指向 stderr，
# 工具执行期 print 不再污染 JSON-RPC 信道；(b) ToolRateLimitMiddleware——
# on_call_tool 钩子逐工具 60s 滑窗限流（单源表只列求解/发射类 11 工具，
# 只读工具永不在表；RFAUTO_MCP_UNLIMITED=1 解除；拒绝走 error_envelope
# 附合并调用文案）。两中间件由 main()（stdio 会话面）**run 期间挂载、
# 返回前摘除**——共享单例（cli/mcp_chat in-memory 通道、进程内消费者）
# 在 main 返回后零泄漏；每次会话拿新限流器实例；限流表内容与注解分类
# 一致性由 tests/unit/test_mcp_runtime_guardrails.py 裁决。
from rfauto.mcp_tools._ratelimit import (
    StdioChannelPurityMiddleware as StdioChannelPurityMiddleware,
)
from rfauto.mcp_tools._ratelimit import (
    ToolRateLimitMiddleware as ToolRateLimitMiddleware,
)


# ══ ge8d-D6 注册幂等化（2026-10-03，定位报告 runs/ge8d_mcp_order/）═══
# 根因：@mcp.tool 注册是工具组模块**首次 import** 的装饰器副作用——注册序
# =各工具组模块的首次执行序。金快照（tests/gold/mcp_registration_order.json）
# 钉的是本文件 from-import 语句顺序（facade 序；isort: skip_file 保证源序
# =执行序）。一旦任何代码在 facade 之前 import 了某个 rfauto.mcp_tools.*
# 子模块，该组工具即先于 facade 顺序落位、注册序偏离金快照——实测触发面=
# 测试收集期 test_mcp_longtask_wait.py 的模块级 ``from rfauto.mcp_tools
# import jobs``（b74ec8cc 2026-10-03 落地；pytest 收集阶段 eager import
# 全部测试模块，先于一切测试执行），症状即"组合跑红/单跑绿/同命令两轮
# 不同结果"的顺序敏感偶发（DEVLOG 八百二十二）。
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
_apply_tool_annotations()


def get_mcp_server() -> FastMCP:
    """获取 MCP Server 实例。"""
    return mcp


def _ensure_stdio_guardrails() -> None:
    """挂 VB-7 运行期两护栏中间件（幂等：按类型查重，重复调用不叠加）。

    只在 stdio 会话面（main）挂载：限流与 stdout 纯度面向外部 Agent
    会话；in-memory 通道（mcp_chat）保持零行为变化。
    """
    if not any(isinstance(m, ToolRateLimitMiddleware) for m in mcp.middleware):
        mcp.add_middleware(ToolRateLimitMiddleware())
    if not any(isinstance(m, StdioChannelPurityMiddleware) for m in mcp.middleware):
        mcp.add_middleware(StdioChannelPurityMiddleware())


def _remove_stdio_guardrails() -> None:
    """摘除两护栏中间件（main 返回时恢复单例面——进程内消费零泄漏）。"""
    mcp.middleware[:] = [
        m for m in mcp.middleware
        if not isinstance(m, (ToolRateLimitMiddleware, StdioChannelPurityMiddleware))
    ]


def main() -> None:
    """console script 入口（pyproject ``[project.scripts] rfauto-mcp``）：
    stdio 传输启动 MCP Server。与 ``python -m rfauto.mcp_server`` 同源。

    保持零参数、零 stdout 打印：stdio 传输把 stdout 当协议信道，任何
    额外输出都会污染 JSON-RPC 帧（F4 发布口径）。挂 VB-7 运行期两护栏
    （stdio 信道纯度 + 逐工具滑窗限流，见 _ratelimit.py 模块注）——run
    期间挂载、返回前摘除（共享单例零泄漏；每会话新限流器）。
    """
    _ensure_stdio_guardrails()
    try:
        mcp.run(transport="stdio")
    finally:
        _remove_stdio_guardrails()


if __name__ == "__main__":
    # 直接运行时启动 stdio 传输
    main()
