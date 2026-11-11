"""CLI 入口（§6）—— typer 子命令。薄壳层，零业务逻辑（军规 10）。

用法：
    rfauto doctor
    rfauto models list [--schema NAME]
    rfauto run <recipe.yaml>
    rfauto sweep <recipe.yaml>
    rfauto tune <recipe.yaml> [--watch|--detach]
    rfauto refine <run_id>
    rfauto jobs [status|cancel] JOB_ID
    rfauto cache clear [--model NAME]
    rfauto link <run_id> --to-ads
    rfauto report <run_id> [-o out.html]
    rfauto export-report-pdf <run_id> [-o out.pdf]
    rfauto replay <run_id>
    rfauto datasets materialize --name X [--runs id1,id2]
    rfauto datasets discover-workdir|import-workdir --name X          (工作目录形态导入器)
    rfauto datasets query <name> [--where "..."] [--columns a,b]
    rfauto datasets coverage|annotate|visibility|export-hf <name>   (WP2.4 余量)
    rfauto bands list|get|find|spec-bounds|env-*                    (D9 十接口)
    rfauto campaign plan|status|event|list                          (战役状态机)
    rfauto template-spec list|draft <name> [-p k=v]                 (E2 模板库)
    rfauto uq yield-at|design-center|temp-zone <samples.json>       (WP4.2 良率)
    rfauto autotune <recipe.yaml> --self-verify                     (WP3.5 自验证环)
    rfauto bench goldset|agentbench                                 (WP3.7 回归门)
    rfauto farfield list|view <run_id>                              (WP4.1 nf2ff)
    rfauto kicad extract|optimize <board.kicad_pcb>                 (B6 stage-2)
    rfauto electrothermal|parasitic <payload.json>                  (WP4.4a/b)
    rfauto pdn analyze|select|gate <payload.json>                   (F-B PI/PDN)
    rfauto fault-tree report|datasheet build                        (F-10 壳接线 W3-D)
    rfauto humidity uptake|msl / weave styles|estimate / cryo surface  (F-10 同批)
    rfauto topology --f0 2.5 --fbw 0.05 [--campaign]                (WP4.6 E10)
    rfauto vna-replay <measured.s2p> [--sim sim.s2p]                (补强17 离线回放)
    rfauto report-narrative <run_id> [--text "..."]                 (F9 叙述位)
    rfauto rationale recall|checklist|search                        (F11/F2 经验记忆)
    rfauto self-heal run <run_id>                                   (F5 自愈环只读诊断)
    rfauto logs digest <path>                                       (WP3.6 LogDistiller)
    rfauto materials dispersion-report <material> [f_lo f_hi]       (D1 色散适应性)
"""

from __future__ import annotations

# ══ AU-1 巨石拆分 facade（2026-09-30 批3）════════════════════════
# 本文件原为 5.8k 行巨石，实现拆分至 cli/domains/ 包（_core/system/
# workflow/…/remote）。此处逐名显式 re-export 全部模块级名（公开面快照
# 钉：拆分前后 dir() 逐名相等；redundant-alias=PEP 484 显式 re-export
# 惯例，ruff F401 不咬）。
#
# 注册顺序=下面 re-export from-import 语句顺序（首条 from-import 触发域
# 模块导入即注册；bench/fab 两个 add_typer 原文块按原位置穿插其间）——
# isort 会按字母重排致注册序漂移，故本文件 isort: skip_file。
# isort: skip_file
# ruff: noqa: E402

import contextlib as contextlib  # facade：保持原模块公开面（快照钉）
import json as json
import sys as sys
from pathlib import Path as Path

import typer as typer
from rich.console import Console as Console
from rich.table import Table as Table

from rfauto.cli.bench_app import bench_app as bench_app
from rfauto.cli.fab_app import fab_app as fab_app
from rfauto.cli.profile_app import profile_app as profile_app

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _force_utf8_stdio as _force_utf8_stdio
from rfauto.cli.domains._core import _kv_floats as _kv_floats
from rfauto.cli.domains._core import _load_json_file as _load_json_file
from rfauto.cli.domains._core import _main_callback as _main_callback
from rfauto.cli.domains._core import _setup_logging_from_env as _setup_logging_from_env
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

from rfauto.cli.domains.system import doctor as doctor
from rfauto.cli.domains.system import models_app as models_app
from rfauto.cli.domains.system import models_docs as models_docs
from rfauto.cli.domains.system import models_list as models_list
from rfauto.cli.domains.workflow import autotune as autotune
from rfauto.cli.domains.workflow import refine as refine
from rfauto.cli.domains.workflow import run as run
from rfauto.cli.domains.workflow import sweep as sweep
from rfauto.cli.domains.workflow import tolerance as tolerance
from rfauto.cli.domains.workflow import tune as tune
from rfauto.cli.domains.jobs import cache_app as cache_app
from rfauto.cli.domains.jobs import cache_clear as cache_clear
from rfauto.cli.domains.jobs import export_report_pdf_cmd as export_report_pdf_cmd
from rfauto.cli.domains.jobs import jobs_app as jobs_app
from rfauto.cli.domains.jobs import jobs_cancel as jobs_cancel
from rfauto.cli.domains.jobs import jobs_status as jobs_status
from rfauto.cli.domains.jobs import link as link
from rfauto.cli.domains.jobs import replay as replay
from rfauto.cli.domains.jobs import report as report
from rfauto.cli.domains.jobs import validate as validate
from rfauto.cli.domains.synth import _load_array_request as _load_array_request
from rfauto.cli.domains.synth import _load_stage_list as _load_stage_list
from rfauto.cli.domains.synth import array_app as array_app
from rfauto.cli.domains.synth import array_pattern_cmd as array_pattern_cmd
from rfauto.cli.domains.synth import array_scan_cmd as array_scan_cmd
from rfauto.cli.domains.synth import array_synthesize_cmd as array_synthesize_cmd
from rfauto.cli.domains.synth import budget_app as budget_app
from rfauto.cli.domains.synth import budget_run as budget_run
from rfauto.cli.domains.synth import cascade_app as cascade_app
from rfauto.cli.domains.synth import cascade_budget_cmd as cascade_budget_cmd
from rfauto.cli.domains.synth import cascade_plan_cmd as cascade_plan_cmd
from rfauto.cli.domains.synth import cascade_spur_cmd as cascade_spur_cmd
from rfauto.cli.domains.synth import syn_app as syn_app
from rfauto.cli.domains.synth import syn_bpf as syn_bpf
from rfauto.cli.domains.synth import syn_branchline as syn_branchline
from rfauto.cli.domains.synth import syn_mline as syn_mline
from rfauto.cli.domains.synth import syn_patch as syn_patch
from rfauto.cli.domains.synth import syn_wilkinson as syn_wilkinson
from rfauto.cli.domains.diagnose import _diagnose_emit as _diagnose_emit
from rfauto.cli.domains.diagnose import _load_json_value as _load_json_value
from rfauto.cli.domains.diagnose import _render_diagnose_cat as _render_diagnose_cat
from rfauto.cli.domains.diagnose import _render_diagnose_cm as _render_diagnose_cm
from rfauto.cli.domains.diagnose import _render_diagnose_q as _render_diagnose_q
from rfauto.cli.domains.diagnose import correlate as correlate
from rfauto.cli.domains.diagnose import diagnose_app as diagnose_app
from rfauto.cli.domains.diagnose import diagnose_cat_cmd as diagnose_cat_cmd
from rfauto.cli.domains.diagnose import diagnose_cm_cmd as diagnose_cm_cmd
from rfauto.cli.domains.diagnose import diagnose_detective_cmd as diagnose_detective_cmd
from rfauto.cli.domains.diagnose import diagnose_q_cmd as diagnose_q_cmd
from rfauto.cli.domains.anchors import _anchors_emit as _anchors_emit
from rfauto.cli.domains.anchors import _render_anchors_drift as _render_anchors_drift
from rfauto.cli.domains.anchors import _render_anchors_inspect as _render_anchors_inspect
from rfauto.cli.domains.anchors import _render_anchors_list as _render_anchors_list
from rfauto.cli.domains.anchors import _render_anchors_stale as _render_anchors_stale
from rfauto.cli.domains.anchors import _render_anchors_validate as _render_anchors_validate
from rfauto.cli.domains.anchors import anchors_app as anchors_app
from rfauto.cli.domains.anchors import anchors_drift_cmd as anchors_drift_cmd
from rfauto.cli.domains.anchors import anchors_inspect_cmd as anchors_inspect_cmd
from rfauto.cli.domains.anchors import anchors_list_cmd as anchors_list_cmd
from rfauto.cli.domains.anchors import anchors_stale_cmd as anchors_stale_cmd
from rfauto.cli.domains.anchors import anchors_validate_cmd as anchors_validate_cmd
from rfauto.cli.domains.surrogate import _datasets_families as _datasets_families
from rfauto.cli.domains.surrogate import _datasets_json as _datasets_json
from rfauto.cli.domains.surrogate import datasets_annotate as datasets_annotate
from rfauto.cli.domains.surrogate import datasets_app as datasets_app
from rfauto.cli.domains.surrogate import datasets_coverage as datasets_coverage
from rfauto.cli.domains.surrogate import datasets_discover_workdir as datasets_discover_workdir
from rfauto.cli.domains.surrogate import datasets_export_hf as datasets_export_hf
from rfauto.cli.domains.surrogate import datasets_import_workdir as datasets_import_workdir
from rfauto.cli.domains.surrogate import datasets_materialize as datasets_materialize
from rfauto.cli.domains.surrogate import datasets_query as datasets_query
from rfauto.cli.domains.surrogate import datasets_visibility as datasets_visibility
from rfauto.cli.domains.surrogate import runs_app as runs_app
from rfauto.cli.domains.surrogate import runs_compare as runs_compare
from rfauto.cli.domains.surrogate import runs_health as runs_health
from rfauto.cli.domains.surrogate import surrogate_analyze as surrogate_analyze
from rfauto.cli.domains.surrogate import surrogate_app as surrogate_app
from rfauto.cli.domains.surrogate import surrogate_uq as surrogate_uq
from rfauto.cli.domains.agent_kicad import agent_app as agent_app
from rfauto.cli.domains.agent_kicad import agent_apply_cmd as agent_apply_cmd
from rfauto.cli.domains.agent_kicad import agent_propose_cmd as agent_propose_cmd
from rfauto.cli.domains.agent_kicad import hfss_import_cmd as hfss_import_cmd
from rfauto.cli.domains.agent_kicad import kicad_app as kicad_app
from rfauto.cli.domains.agent_kicad import kicad_drc_cmd as kicad_drc_cmd
from rfauto.cli.domains.agent_kicad import kicad_extract_cmd as kicad_extract_cmd
from rfauto.cli.domains.agent_kicad import kicad_optimize_cmd as kicad_optimize_cmd
from rfauto.cli.domains.agent_kicad import kicad_pcb as kicad_pcb
from rfauto.cli.domains.recipe import recipe_app as recipe_app
from rfauto.cli.domains.recipe import recipe_migrate_cmd as recipe_migrate_cmd
from rfauto.cli.domains.recipe import recipe_skill_cmd as recipe_skill_cmd
from rfauto.cli.domains.recipe import repro_cmd as repro_cmd
from rfauto.cli.domains.recipe import repro_manifest_cmd as repro_manifest_cmd
from rfauto.cli.domains.recipe import repro_verify_cmd as repro_verify_cmd
from rfauto.cli.domains.chain_study import audit_cmd as audit_cmd
from rfauto.cli.domains.chain_study import chain_app as chain_app
from rfauto.cli.domains.chain_study import chain_lna_cmd as chain_lna_cmd
from rfauto.cli.domains.chain_study import chain_loadpull_cmd as chain_loadpull_cmd
from rfauto.cli.domains.chain_study import even_odd_cmd as even_odd_cmd
from rfauto.cli.domains.chain_study import p0_cmd as p0_cmd
from rfauto.cli.domains.chain_study import sensitivity_cmd as sensitivity_cmd
from rfauto.cli.domains.chain_study import study_app as study_app
from rfauto.cli.domains.chain_study import study_inject_cmd as study_inject_cmd
from rfauto.cli.domains.chain_study import tuning_report_cmd as tuning_report_cmd
from rfauto.cli.domains.solvers import chat_cmd as chat_cmd
from rfauto.cli.domains.solvers import inbox_cmd as inbox_cmd
from rfauto.cli.domains.solvers import simci_cmd as simci_cmd
from rfauto.cli.domains.solvers import solvers_add as solvers_add
from rfauto.cli.domains.solvers import solvers_app as solvers_app
from rfauto.cli.domains.solvers import solvers_list as solvers_list
from rfauto.cli.domains.solvers import solvers_qucsator_mline as solvers_qucsator_mline
from rfauto.cli.domains.solvers import solvers_viz as solvers_viz
from rfauto.cli.domains.calc_vna import _coerce_param as _coerce_param
from rfauto.cli.domains.calc_vna import calc_app as calc_app
from rfauto.cli.domains.calc_vna import calc_list as calc_list
from rfauto.cli.domains.calc_vna import calc_run as calc_run
from rfauto.cli.domains.calc_vna import oracle_app as oracle_app
from rfauto.cli.domains.calc_vna import oracle_check_all_cmd as oracle_check_all_cmd
from rfauto.cli.domains.calc_vna import oracle_check_cmd as oracle_check_cmd
from rfauto.cli.domains.calc_vna import oracle_list_cmd as oracle_list_cmd
from rfauto.cli.domains.calc_vna import sparams_compare_cmd as sparams_compare_cmd
from rfauto.cli.domains.calc_vna import vna_app as vna_app
from rfauto.cli.domains.calc_vna import vna_calibrate_cmd as vna_calibrate_cmd
from rfauto.cli.domains.calc_vna import vna_en_report_cmd as vna_en_report_cmd
from rfauto.cli.domains.calc_vna import vna_measure_cmd as vna_measure_cmd
from rfauto.cli.domains.calc_vna import vna_replay_offline_cmd as vna_replay_offline_cmd
from rfauto.cli.domains.ui import ui_cmd as ui_cmd
from rfauto.cli.domains.ui import warm_start_cmd as warm_start_cmd


# ─── bench（WP3.7/F6 回归门；0bs① 一行注册上线，bench_app 在文件头导入） ─────
app.add_typer(bench_app, name="bench")
from rfauto.cli.domains.bands_uq import bands_app as bands_app
from rfauto.cli.domains.bands_uq import bands_env_delta_t_cmd as bands_env_delta_t_cmd
from rfauto.cli.domains.bands_uq import bands_env_find_cmd as bands_env_find_cmd
from rfauto.cli.domains.bands_uq import bands_env_get_cmd as bands_env_get_cmd
from rfauto.cli.domains.bands_uq import bands_env_list_cmd as bands_env_list_cmd
from rfauto.cli.domains.bands_uq import bands_env_points_cmd as bands_env_points_cmd
from rfauto.cli.domains.bands_uq import bands_env_uq_axis_cmd as bands_env_uq_axis_cmd
from rfauto.cli.domains.bands_uq import bands_find_cmd as bands_find_cmd
from rfauto.cli.domains.bands_uq import bands_get_cmd as bands_get_cmd
from rfauto.cli.domains.bands_uq import bands_list_cmd as bands_list_cmd
from rfauto.cli.domains.bands_uq import bands_spec_bounds_cmd as bands_spec_bounds_cmd
from rfauto.cli.domains.bands_uq import campaign_app as campaign_app
from rfauto.cli.domains.bands_uq import campaign_event_cmd as campaign_event_cmd
from rfauto.cli.domains.bands_uq import campaign_list_cmd as campaign_list_cmd
from rfauto.cli.domains.bands_uq import campaign_plan_cmd as campaign_plan_cmd
from rfauto.cli.domains.bands_uq import campaign_status_cmd as campaign_status_cmd
from rfauto.cli.domains.bands_uq import farfield_app as farfield_app
from rfauto.cli.domains.bands_uq import farfield_list_cmd as farfield_list_cmd
from rfauto.cli.domains.bands_uq import farfield_view_cmd as farfield_view_cmd
from rfauto.cli.domains.bands_uq import template_spec_app as template_spec_app
from rfauto.cli.domains.bands_uq import template_spec_draft_cmd as template_spec_draft_cmd
from rfauto.cli.domains.bands_uq import template_spec_list_cmd as template_spec_list_cmd
from rfauto.cli.domains.bands_uq import uq_app as uq_app
from rfauto.cli.domains.bands_uq import uq_design_center_cmd as uq_design_center_cmd
from rfauto.cli.domains.bands_uq import uq_robustness_cmd as uq_robustness_cmd
from rfauto.cli.domains.bands_uq import uq_temp_zone_cmd as uq_temp_zone_cmd
from rfauto.cli.domains.bands_uq import uq_yield_at_cmd as uq_yield_at_cmd
from rfauto.cli.domains.scattered import _rag_scope_dirs as _rag_scope_dirs
from rfauto.cli.domains.scattered import electrothermal_cmd as electrothermal_cmd
from rfauto.cli.domains.scattered import logs_app as logs_app
from rfauto.cli.domains.scattered import logs_digest_cmd as logs_digest_cmd
from rfauto.cli.domains.scattered import materials_app as materials_app
from rfauto.cli.domains.scattered import materials_dispersion_report_cmd as materials_dispersion_report_cmd
from rfauto.cli.domains.scattered import parasitic_cmd as parasitic_cmd
from rfauto.cli.domains.scattered import rag_app as rag_app
from rfauto.cli.domains.scattered import rag_explain_cmd as rag_explain_cmd
from rfauto.cli.domains.scattered import rag_index_cmd as rag_index_cmd
from rfauto.cli.domains.scattered import rag_query_cmd as rag_query_cmd
from rfauto.cli.domains.scattered import rationale_app as rationale_app
from rfauto.cli.domains.scattered import rationale_checklist_cmd as rationale_checklist_cmd
from rfauto.cli.domains.scattered import rationale_recall_cmd as rationale_recall_cmd
from rfauto.cli.domains.scattered import rationale_search_cmd as rationale_search_cmd
from rfauto.cli.domains.scattered import report_narrative_cmd as report_narrative_cmd
from rfauto.cli.domains.scattered import self_heal_app as self_heal_app
from rfauto.cli.domains.scattered import self_heal_run_cmd as self_heal_run_cmd
from rfauto.cli.domains.scattered import topology_cmd as topology_cmd
from rfauto.cli.domains.scattered import vna_replay_cmd as vna_replay_cmd
from rfauto.cli.domains.db import _DB_PATH_HELP as _DB_PATH_HELP
from rfauto.cli.domains.db import db_analytics_attach_cmd as db_analytics_attach_cmd
from rfauto.cli.domains.db import db_app as db_app
from rfauto.cli.domains.db import db_init_cmd as db_init_cmd
from rfauto.cli.domains.db import db_league_rebuild_cmd as db_league_rebuild_cmd
from rfauto.cli.domains.db import db_league_report_cmd as db_league_report_cmd
from rfauto.cli.domains.db import db_migrate_cmd as db_migrate_cmd
from rfauto.cli.domains.db import db_query_cmd as db_query_cmd
from rfauto.cli.domains.db import db_reindex_runs_cmd as db_reindex_runs_cmd
from rfauto.cli.domains.db import db_status_cmd as db_status_cmd
from rfauto.cli.domains.db import explain_run_cmd as explain_run_cmd
from rfauto.cli.domains.slotline import _SLOT_ER_HELP as _SLOT_ER_HELP
from rfauto.cli.domains.slotline import _SLOT_H_HELP as _SLOT_H_HELP
from rfauto.cli.domains.slotline import _print_transition_design as _print_transition_design
from rfauto.cli.domains.slotline import slotline_analyze_cmd as slotline_analyze_cmd
from rfauto.cli.domains.slotline import slotline_app as slotline_app
from rfauto.cli.domains.slotline import slotline_synth_cmd as slotline_synth_cmd
from rfauto.cli.domains.slotline import transitions_app as transitions_app
from rfauto.cli.domains.slotline import transitions_marchand2_cmd as transitions_marchand2_cmd
from rfauto.cli.domains.slotline import transitions_marchand_balun_cmd as transitions_marchand_balun_cmd
from rfauto.cli.domains.slotline import transitions_msl_slot_cmd as transitions_msl_slot_cmd
from rfauto.cli.domains.report_mmt import compose_cmd as compose_cmd
from rfauto.cli.domains.report_mmt import compose_templates_cmd as compose_templates_cmd
from rfauto.cli.domains.report_mmt import mmt_app as mmt_app
from rfauto.cli.domains.report_mmt import mmt_solve as mmt_solve
from rfauto.cli.domains.report_mmt import nfc_app as nfc_app
from rfauto.cli.domains.report_mmt import nfc_evaluate_cmd as nfc_evaluate_cmd
from rfauto.cli.domains.report_mmt import nfc_q_cmd as nfc_q_cmd
from rfauto.cli.domains.report_mmt import nfc_synth_cmd as nfc_synth_cmd
from rfauto.cli.domains.report_mmt import nfmeas_app as nfmeas_app
from rfauto.cli.domains.report_mmt import nfmeas_ffs_info_cmd as nfmeas_ffs_info_cmd
from rfauto.cli.domains.report_mmt import nfmeas_nf2ff_cmd as nfmeas_nf2ff_cmd
from rfauto.cli.domains.report_mmt import report_app as report_app
from rfauto.cli.domains.report_mmt import report_render_cmd as report_render_cmd
from rfauto.cli.domains.report_mmt import sar_app as sar_app
from rfauto.cli.domains.report_mmt import sar_report_cmd as sar_report_cmd
from rfauto.cli.domains.report_mmt import si_app as si_app
from rfauto.cli.domains.report_mmt import si_mixed_cmd as si_mixed_cmd
from rfauto.cli.domains.report_mmt import si_report_cmd as si_report_cmd
from rfauto.cli.domains.lake import certify_cmd as certify_cmd
from rfauto.cli.domains.lake import constraints_app as constraints_app
from rfauto.cli.domains.lake import constraints_check_cmd as constraints_check_cmd
from rfauto.cli.domains.lake import lake_app as lake_app
from rfauto.cli.domains.lake import lake_export_parquet_cmd as lake_export_parquet_cmd
from rfauto.cli.domains.lake import lake_index_cmd as lake_index_cmd
from rfauto.cli.domains.lake import lake_pack_cmd as lake_pack_cmd
from rfauto.cli.domains.lake import lake_query_cmd as lake_query_cmd
from rfauto.cli.domains.lake import lake_restore_cmd as lake_restore_cmd
from rfauto.cli.domains.lake import lake_sweep_cmd as lake_sweep_cmd
from rfauto.cli.domains.lake import lake_verify_cmd as lake_verify_cmd
from rfauto.cli.domains.lake import port_gate_cmd as port_gate_cmd
from rfauto.cli.domains.lake import runs_export_tracking_cmd as runs_export_tracking_cmd
from rfauto.cli.domains.lake import runs_stats_cmd as runs_stats_cmd
from rfauto.cli.domains.lake import solid_import_cmd as solid_import_cmd
from rfauto.cli.domains.pdn_aging import _afs_band_from_ghz as _afs_band_from_ghz
from rfauto.cli.domains.pdn_aging import _afs_emit_summary as _afs_emit_summary
from rfauto.cli.domains.pdn_aging import _afs_sweep_summary as _afs_sweep_summary
from rfauto.cli.domains.pdn_aging import afs_app as afs_app
from rfauto.cli.domains.pdn_aging import afs_plan_cmd as afs_plan_cmd
from rfauto.cli.domains.pdn_aging import afs_sweep_cmd as afs_sweep_cmd
from rfauto.cli.domains.pdn_aging import aging_app as aging_app
from rfauto.cli.domains.pdn_aging import aging_report_cmd as aging_report_cmd
from rfauto.cli.domains.pdn_aging import aging_simulate_cmd as aging_simulate_cmd
from rfauto.cli.domains.pdn_aging import aging_verdict_cmd as aging_verdict_cmd
from rfauto.cli.domains.pdn_aging import pdn_analyze_cmd as pdn_analyze_cmd
from rfauto.cli.domains.pdn_aging import pdn_app as pdn_app
from rfauto.cli.domains.pdn_aging import pdn_gate_cmd as pdn_gate_cmd
from rfauto.cli.domains.pdn_aging import pdn_select_cmd as pdn_select_cmd
from rfauto.cli.domains.interop import _render_lint_table as _render_lint_table
from rfauto.cli.domains.interop import interop_app as interop_app
from rfauto.cli.domains.interop import interop_hfss_comments_cmd as interop_hfss_comments_cmd
from rfauto.cli.domains.interop import interop_ts21_write_cmd as interop_ts21_write_cmd
from rfauto.cli.domains.interop import lint_cmd as lint_cmd


# ─── fab（T43：HFSS → 可机加交付包；子应用文件 cli/fab_app.py 零逻辑转发） ──
# go/pipeline/snapshot/draw/audit/pack/rules/catalog/export 九命令薄壳，
# JSON 信封走 service/fab_export_service（审计 FAIL=退出 1 禁止发图）；
# 顶层无同名 `fab` 命令（#df6① 冲突检查 2026-09-29：仅 design_lint 的
# "fab" 检查名/mcp scope 字符串，非 CLI 命令）。

app.add_typer(fab_app, name="fab")
from rfauto.cli.domains.remote import remote_app as remote_app
from rfauto.cli.domains.remote import remote_probe_cmd as remote_probe_cmd
from rfauto.cli.domains.remote import remote_status_cmd as remote_status_cmd


# ─── stats（§B-5 PT-1/2/3 量产三件套薄壳；synth 先例：纯计算命令域内 ──
# 惰性 import core/manufacturing_stats 直连，JSON 信封直出）：
# guardband（ILAC-G8 保护带）/ cpk（Bissell CI）/ weibull（删失 MLE）
# 三命令。注册在 cli/domains/stats.py 模块级 add_typer（remote.py 同款
# 域内自注册——此处只 re-export，二次 add_typer 会双注册打红 zero-shadow
# 钉，2026-10-02 实证）；顶层无同名 `stats` 命令（#df6① 冲突检查
# 2026-10-02：仅 lake 的 "runs stats" 子命令路径，非顶层）。

from rfauto.cli.domains.stats import stats_app as stats_app
from rfauto.cli.domains.stats import stats_cpk_cmd as stats_cpk_cmd
from rfauto.cli.domains.stats import stats_guardband_cmd as stats_guardband_cmd
from rfauto.cli.domains.stats import stats_weibull_cmd as stats_weibull_cmd


# ─── firmware（§B-6 PT-6 固件工件三出口薄壳；stats 同款：纯计算命令域内 ──
# 惰性 import core/firmware_export 直连，JSON 信封直出）：
# beam（波束码字表 CSV+C 头+回代判据）/ varactor（DAC 偏置表+单调/饱和
# 审计）/ dpd（Q 定点表+NMSE 门+溢出告警）三命令。注册在
# cli/domains/firmware.py 模块级 add_typer（stats.py 同款域内自注册——
# 此处只 re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；
# 顶层无同名 `firmware` 命令（#df6① 冲突检查 2026-10-02：全 CLI 树无撞名）。

from rfauto.cli.domains.firmware import firmware_app as firmware_app
from rfauto.cli.domains.firmware import firmware_beam_cmd as firmware_beam_cmd
from rfauto.cli.domains.firmware import firmware_dpd_cmd as firmware_dpd_cmd
from rfauto.cli.domains.firmware import firmware_varactor_cmd as firmware_varactor_cmd


# ─── preflight（XC-F 统一预检薄壳；stats/firmware 同款：域内自注册 ──
# 此处只 re-export（二次 add_typer 会双注册打红 zero-shadow 钉）；
# 顶层无同名 preflight 命令（#df6① 冲突检查 2026-10-03：全 CLI 树零撞名）。

from rfauto.cli.domains.preflight import preflight_app as preflight_app
from rfauto.cli.domains.preflight import preflight_run_cmd as preflight_run_cmd
from rfauto.cli.domains.preflight import preflight_gates_cmd as preflight_gates_cmd


# ─── profile（PR-8 剖析入口；bench 同款子应用文件 cli/profile_app.py 零逻辑转发） ──
# status（py-spy 可用性探测）/ run（py-spy record 封装，火焰图落 runs/profile/）
# 两命令薄壳转发 service/profile_service；py-spy 为可选依赖（未装 status 如实
# available=false，run 显错退出 1）。X2 席 2026-10-04：宏图 PR-8 的 CLI 面
# 落地（ge8b Wave B 席B2 当时收窄为 UI 面 /api/profile，CLI 为真缺口）；
# 顶层无同名 `profile` 命令（#df6① 冲突检查 2026-10-04：全 CLI 树零撞名）。

app.add_typer(profile_app, name="profile")


# ─── layout（SO-1 孤儿接线批 W1-B：VI-1 表行 2-8 版图家族八叶薄壳；stats/ ──
# firmware 同款：域内自注册 cli/domains/layout.py 模块级 add_typer——
# 此处只 re-export（二次 add_typer 会双注册打红 zero-shadow 钉）；
# 顶层无同名 `layout` 命令（#df6① 冲突检查 2026-10-05：全 CLI 树零撞名，
# scattered.py 的 layout_interchange import 是 adapters 面非命令）。

from rfauto.cli.domains.layout import layout_app as layout_app
from rfauto.cli.domains.layout import layout_assemble_cmd as layout_assemble_cmd
from rfauto.cli.domains.layout import layout_build_cmd as layout_build_cmd
from rfauto.cli.domains.layout import layout_diff_cmd as layout_diff_cmd
from rfauto.cli.domains.layout import layout_lvs_cmd as layout_lvs_cmd
from rfauto.cli.domains.layout import layout_panelize_cmd as layout_panelize_cmd
from rfauto.cli.domains.layout import layout_simulate_cmd as layout_simulate_cmd
from rfauto.cli.domains.layout import layout_stencil_cmd as layout_stencil_cmd
from rfauto.cli.domains.layout import layout_step_cmd as layout_step_cmd


# ─── teaching（SO-1 孤儿接线批 W1-C 单元 14：教学卡两叶；stats/firmware ──
# 同款：域内自注册 cli/domains/teaching.py 模块级 add_typer——此处只
# re-export（二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
# `teaching` 命令（#df6① 冲突检查 2026-10-05：全 CLI 树零撞名）。

from rfauto.cli.domains.teaching import teaching_app as teaching_app
from rfauto.cli.domains.teaching import teaching_index_cmd as teaching_index_cmd
from rfauto.cli.domains.teaching import teaching_show_cmd as teaching_show_cmd


# ─── zenodo（SO-1 孤儿接线批 W1-C 单元 15c：CITATION.cff 导出+校验两叶， ──
# PR-11 零网络；stats/firmware 同款域内自注册——此处只 re-export
# （二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 `zenodo`
# 命令（#df6① 冲突检查 2026-10-05：全 CLI 树零撞名）。

from rfauto.cli.domains.zenodo import zenodo_app as zenodo_app
from rfauto.cli.domains.zenodo import zenodo_export_cmd as zenodo_export_cmd
from rfauto.cli.domains.zenodo import zenodo_validate_cmd as zenodo_validate_cmd


# ─── few-shot（SO-1 孤儿接线批 W1-C 单元 15：成功会话挖掘→精选→注入节， ──
# AD-3 单命令子应用（spec VI-1 表行 15 "单命令"，命令文法=rfauto
# few-shot build）；#df6① 冲突检查 2026-10-05：`few-shot` 带连字符，
# 全 CLI 树零撞名）。

from rfauto.cli.domains.few_shot import few_shot_app as few_shot_app
from rfauto.cli.domains.few_shot import few_shot_build_cmd as few_shot_build_cmd


# ─── hints（SO-1 孤儿接线批 W1-A 单元 13：错误提示规则面只读叶；stats/ ──
# firmware 同款：域内自注册 cli/domains/hints.py 模块级 add_typer——
# 此处只 re-export（二次 add_typer 会双注册打红 zero-shadow 钉）；
# 顶层无同名 `hints` 命令（#df6① 冲突检查 2026-10-05：全 CLI 树零撞名）。

from rfauto.cli.domains.hints import hints_app as hints_app
from rfauto.cli.domains.hints import hints_list_cmd as hints_list_cmd


# ─── pitfalls（aurora_d KB-B 席 2026-10-14：坑账结构化检索面两叶；hints ──
# 同款：域内自注册 cli/domains/pitfalls.py 模块级 add_typer——此处只
# re-export（二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
# `pitfalls` 命令（#df6① 冲突检查 2026-10-14：全 CLI 树零撞名，grep 实测）。
# 数据面=knowledge/pitfalls_index_full.json（scripts/pitfall_index.py 全量
# 解析 AGENTS.md 踩坑速查）；索引加载/校验零逻辑转发
# service/pitfall_index_service 只读面。

from rfauto.cli.domains.pitfalls import pitfalls_app as pitfalls_app
from rfauto.cli.domains.pitfalls import pitfalls_get_cmd as pitfalls_get_cmd
from rfauto.cli.domains.pitfalls import pitfalls_search_cmd as pitfalls_search_cmd


# ─── dag（VI-4/SN-1 接线，Phase2 W2-A：DAG 执行基座两叶；stats/firmware ──
# 同款：域内自注册 cli/domains/dag.py 模块级 add_typer——此处只 re-export
# （二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 `dag` 域
# （#df6① 冲突检查 2026-10-05：全 CLI 树零撞名，SP 席 VI-4 接地复核）。

from rfauto.cli.domains.dag import dag_app as dag_app
from rfauto.cli.domains.dag import dag_run as dag_run
from rfauto.cli.domains.dag import dag_run_cmd as dag_run_cmd
from rfauto.cli.domains.dag import dag_status as dag_status
from rfauto.cli.domains.dag import dag_status_cmd as dag_status_cmd


# ─── anim（T-Q3 接线席 Q-W5-2R aurora_q 方向 B：动图渲染一叶；dag ──
# 同款：域内自注册 cli/domains/anim.py 模块级 add_typer——此处只 re-export
# （二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 `anim` 域
# （#df6① 冲突检查 2026-11-04：全 CLI 树零撞名）。

from rfauto.cli.domains.anim import anim_app as anim_app
from rfauto.cli.domains.anim import anim_render_cmd as anim_render_cmd


# ─── vendor-docs（T-Q19 批 2 接线席 Q-W9-3，aurora_q 方向 E：厂商帮助 ──
# 文档检索三叶 build/search/audit；dag/loop/anim 同款：域内自注册
# cli/domains/vendor_docs.py 模块级 add_typer——此处只 re-export（二次
# add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 `vendor-docs` 域
# （#df6① 冲突检查 2026-11-06：全 CLI 树零撞名，唯一近名 db 域语义=
# 注册表数据库非厂商语料）。--db 三叶必填不落缺省库位（#144 同族）。
# append-only 注册序尾。

from rfauto.cli.domains.vendor_docs import vendor_docs_app as vendor_docs_app
from rfauto.cli.domains.vendor_docs import vendor_docs_audit_cmd as vendor_docs_audit_cmd
from rfauto.cli.domains.vendor_docs import vendor_docs_build_cmd as vendor_docs_build_cmd
from rfauto.cli.domains.vendor_docs import vendor_docs_search_cmd as vendor_docs_search_cmd


# ─── env_reliability（F-10 六服务壳接线批 W3-D，Phase 3：五子应用七叶； ──
# stats/firmware/layout 同款：域内自注册 cli/domains/env_reliability.py
# 模块级 add_typer——此处只 re-export（二次 add_typer 会双注册打红
# zero-shadow 钉）；批B 第六件 netlist-goldset 落 bench_app（上方 bench
# 块 import 序内自动注册）；顶层无同名 fault-tree/datasheet/humidity/
# weave/cryo 命令（#df6① 冲突检查 2026-10-05：click 树实测零撞名）。

from rfauto.cli.domains.env_reliability import cryo_app as cryo_app
from rfauto.cli.domains.env_reliability import cryo_surface_cmd as cryo_surface_cmd
from rfauto.cli.domains.env_reliability import datasheet_app as datasheet_app
from rfauto.cli.domains.env_reliability import datasheet_build_cmd as datasheet_build_cmd
from rfauto.cli.domains.env_reliability import fault_tree_app as fault_tree_app
from rfauto.cli.domains.env_reliability import fault_tree_report_cmd as fault_tree_report_cmd
from rfauto.cli.domains.env_reliability import humidity_app as humidity_app
from rfauto.cli.domains.env_reliability import humidity_msl_cmd as humidity_msl_cmd
from rfauto.cli.domains.env_reliability import humidity_uptake_cmd as humidity_uptake_cmd
from rfauto.cli.domains.env_reliability import weave_app as weave_app
from rfauto.cli.domains.env_reliability import weave_estimate_cmd as weave_estimate_cmd
from rfauto.cli.domains.env_reliability import weave_styles_cmd as weave_styles_cmd


# ─── goal（DS-3 用户 Goal 工作模式四叶，Phase 5 W5-C：持久目标+自动续轮； ──
# dag/env_reliability 同款：域内自注册 cli/domains/goal.py 模块级
# add_typer——此处只 re-export（二次 add_typer 会双注册打红 zero-shadow
# 钉）；顶层无同名 `goal` 域（#df6① 冲突检查 2026-10-05：全 CLI 树零撞名）。

from rfauto.cli.domains.goal import goal_advance as goal_advance
from rfauto.cli.domains.goal import goal_advance_cmd as goal_advance_cmd
from rfauto.cli.domains.goal import goal_app as goal_app
from rfauto.cli.domains.goal import goal_list as goal_list
from rfauto.cli.domains.goal import goal_list_cmd as goal_list_cmd
from rfauto.cli.domains.goal import goal_set as goal_set
from rfauto.cli.domains.goal import goal_set_cmd as goal_set_cmd
from rfauto.cli.domains.goal import goal_status as goal_status
from rfauto.cli.domains.goal import goal_status_cmd as goal_status_cmd


# ─── dev（SO-审查 §7 P5 维护者脚手架两叶，Phase 6 W6-D；stats/firmware ──
# 同款：域内自注册 cli/domains/dev.py 模块级 add_typer——此处只 re-export
# （二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 `dev` 域
# （#df6① 冲突检查 2026-10-05：全 CLI 树零撞名）。

from rfauto.cli.domains.dev import dev_app as dev_app
from rfauto.cli.domains.dev import dev_new_calculator_cmd as dev_new_calculator_cmd
from rfauto.cli.domains.dev import dev_new_template_cmd as dev_new_template_cmd


# ─── design / sandbox（SN-3 / SN-17，Phase 6 W6-A；dev 同款：域内自注册 ──
# add_typer——此处只 re-export；顶层无同名 `design`/`sandbox` 域（零撞名
# 自查 2026-10-06：全 CLI 树 `design` 仅 cli/domains/design.py 新域）。

from rfauto.cli.domains.design import design_app as design_app
from rfauto.cli.domains.design import design_close_cmd as design_close_cmd
from rfauto.cli.domains.design import design_kickoff_cmd as design_kickoff_cmd
from rfauto.cli.domains.sandbox import sandbox_app as sandbox_app
from rfauto.cli.domains.sandbox import sandbox_diff_cmd as sandbox_diff_cmd
from rfauto.cli.domains.sandbox import sandbox_list_cmd as sandbox_list_cmd
from rfauto.cli.domains.sandbox import sandbox_promote_cmd as sandbox_promote_cmd


# ─── pool-patrol（Z-11 池登记项新鲜度巡检器工具化，2026-10-08；dev 同款：
# 域内自注册 @app.command——此处只 re-export；顶层无同名 `pool-patrol`
# 命令（零撞名自查 2026-10-08：全 CLI 树无 pool 前缀命令）。

from rfauto.cli.domains.pool_patrol import pool_patrol_cmd as pool_patrol_cmd


# ─── edb（EDB 快车道 CLI 出口，2026-10-08：build/solve/status 三叶；
# stats/firmware 同款域内自注册 add_typer——此处只 re-export（二次
# add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 `edb` 域
# （#df6① 冲突检查 2026-10-08：全 CLI 树零撞名）。

from rfauto.cli.domains.edb import edb_app as edb_app
from rfauto.cli.domains.edb import edb_build_cmd as edb_build_cmd
from rfauto.cli.domains.edb import edb_solve_cmd as edb_solve_cmd
from rfauto.cli.domains.edb import edb_status_cmd as edb_status_cmd


# ─── recast（RECAST 判据重放 CLI 出口，2026-10-11 aurora36 W2-D：
# status/replay 两只读叶；stats/firmware/edb 同款域内自注册 add_typer——
# 此处只 re-export（二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无
# 同名 `recast` 域（#df6① 冲突检查 2026-10-11：全 CLI 树零撞名）。

from rfauto.cli.domains.recast import recast_app as recast_app
from rfauto.cli.domains.recast import recast_replay_cmd as recast_replay_cmd
from rfauto.cli.domains.recast import recast_status_cmd as recast_status_cmd


# ─── rest（aurora_d REST-B：REST 面 schema 导出只读叶，2026-10-14；
# recast 同款域内自注册 add_typer——此处只 re-export（二次 add_typer 会
# 双注册打红 zero-shadow 钉）；顶层无同名 `rest` 命令（#df6① 冲突检查
# 2026-10-14：全 CLI 树零撞名，唯一近名是 lake 的 restore 子命令）。

from rfauto.cli.domains.rest import rest_app as rest_app
from rfauto.cli.domains.rest import rest_schema_cmd as rest_schema_cmd


# ─── templates（EC-8 模板 golden 几何回归仓 CLI 出口，2026-10-18 aurora_e
# W2-S8：golden-diff 单叶；rest 同款域内自注册 add_typer——此处只 re-export
# （二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 `templates` 域
# （#df6① 冲突检查 2026-10-18：全 CLI 树零撞名，唯一近名 `template-spec`
# 是 bands 域 TemplateSpec 注册表子应用，语义不同）。

from rfauto.cli.domains.templates import templates_app as templates_app
from rfauto.cli.domains.templates import templates_golden_diff_cmd as templates_golden_diff_cmd


# ─── em（自定义 EM 模型语义检查 CLI 出口，2026-10-23 aurora_k K5：
# doctor 单叶（P12/F8：模型清单驱动的 pre-solve 几何/端口语义体检）；
# templates 同款域内自注册 add_typer——此处只 re-export（二次 add_typer
# 会双注册打红 zero-shadow 钉）；顶层无同名 `em` 域（零撞名自查
# 2026-10-23：全 CLI 树唯一 em 前缀词是 empty 词面，无 em 命令/组）。

from rfauto.cli.domains.em import em_app as em_app
from rfauto.cli.domains.em import em_doctor_cmd as em_doctor_cmd


# ─── mo（多目标寻优 MO-BO CLI 出口，2026-10-31 aurora_n O1：run 单叶 ────
# （内置合成族 T-N13 EHVI 内核运行时门——zero_wiring REGISTRY O1 欠账
# 清偿）。templates/em 同款域内自注册 add_typer——此处只 re-export（二次
# add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 mo 域（零撞名自查
# 2026-10-31：全 CLI 树无 mo/mo_ 前缀命令或组）。append-only 注册序尾。

from rfauto.cli.domains.mo import mo_app as mo_app
from rfauto.cli.domains.mo import mo_run_cmd as mo_run_cmd


# ─── competition（单目标优化器族竞赛持久门 CLI 出口，2026-10-31 aurora_n
# O5：run 单叶（T-N5 标量竞赛架运行时门——zero_wiring REGISTRY O5 欠账
# 清偿；同预算同 seed 组竞赛，AUC 两阶段+达标次数三套排名，内置合成 4 族
# 与首榜同源，botorch_ei 显式点名 opt-in）。templates/em 同款域内自注册
# add_typer——此处只 re-export（二次 add_typer 会双注册打红 zero-shadow
# 钉）；顶层无同名 competition 域（零撞名自查 2026-10-31：全 CLI 树无
# competition/comp_ 前缀命令或组）。append-only 注册序尾。

from rfauto.cli.domains.competition import (
    competition_app as competition_app,
    competition_run_cmd as competition_run_cmd,
)


# ─── al（主动学习采样提议 CLI 出口，2026-10-31 aurora_n O4：propose 单叶 ──
# （T-N9 宿主 propose_next_points 运行时门——zero_wiring REGISTRY O4 旧面
# 欠账清偿）。templates/em 同款域内自注册 add_typer——此处只 re-export（二次
# add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 al 域（零撞名自查
# 2026-10-31：全 CLI 树无 al/al_ 前缀命令或组）。append-only 注册序尾。

from rfauto.cli.domains.al import al_app as al_app
from rfauto.cli.domains.al import al_propose_cmd as al_propose_cmd


# ─── diagram（电路图绘制 CLI 出口，2026-10-31 aurora_o T-O1：link 单叶）──
# （"算画同源"第一件——RF 链路框图 .drawio 原生可编辑工程图，每级标
# 增益/NF+级联累计（Friis），数字=内核单源 core/budget.py LinkBudget）。
# templates/em 同款域内自注册 add_typer——此处只 re-export（二次 add_typer
# 会双注册打红 zero-shadow 钉）；顶层无同名 diagram 域（零撞名自查
# 2026-10-31：全 CLI 树无 diagram/diagram_ 前缀命令或组）。append-only
# 注册序尾。

from rfauto.cli.domains.diagram import diagram_app as diagram_app
from rfauto.cli.domains.diagram import diagram_link_cmd as diagram_link_cmd


# ─── design-report（设计回放与总结报告 CLI 出口，2026-11-01 aurora_o T-O5）──
# （六节 md 单文件：目标摘要/轨迹回放/最终设计与门表/电路图/敏感性/复现
# 命令——优化族 run 此前无报告出口，本叶补主缺口）。scattered 同款顶层
# 连字叶（design 顶层名已被 level2 design 链占用——cli/domains/design.py
# 实测；连字形态同 export-report-pdf 先例）；顶层无同名 design-report 域
# （零撞名自查 2026-11-01：全 CLI 树无 design-report/design_report 前缀
# 命令或组）。append-only 注册序尾。

from rfauto.cli.domains.design_report import design_report_cmd as design_report_cmd


# ─── ads-circuit（ADS 前仿链人机回路 CLI 出口，2026-11-01 aurora_o T-O4：──
# diagram/run/annotate 三叶——用户核心需求"画电路图→带入 ADS 仿真→人工
# 调参回路"（J1 出图 UserObject 三件组 → J2 draw.io Edit Data 改值 → J3
# 读图→三态合参→渲染→hpeesofsim→解析→指标→对拍 → J4 反标注 annot_sim
# 层上图 → J5 迭代）。diagram 同款域内自注册 add_typer——此处只 re-export
# （二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 ads-circuit
# 域（零撞名自查 2026-11-01：全 CLI 树无 ads-circuit/ads_circuit 前缀命令
# 或组，唯一近名 jobs link --to-ads 语义不同）。append-only 注册序尾。

from rfauto.cli.domains.ads_circuit import ads_circuit_app as ads_circuit_app
from rfauto.cli.domains.ads_circuit import ads_circuit_annotate_cmd as ads_circuit_annotate_cmd
from rfauto.cli.domains.ads_circuit import ads_circuit_diagram_cmd as ads_circuit_diagram_cmd
from rfauto.cli.domains.ads_circuit import ads_circuit_run_cmd as ads_circuit_run_cmd


# ─── watchdog（seat 粒度三证判活 CLI 出口，2026-11-02 aurora_p F2）────
# （T-O12 service/watchdog_service 的常驻形态接线：watch 单叶双形态——
# 一次性视图=缺省动作（零后台线程零文件写，逐字节同 service 直调），
# --watch 常驻循环显式开启（jsonl 落白名单 runs/watchdog/，Ctrl+C 优雅
# 停；轮间隔下限复用 speculative_watch_service.MIN_INTERVAL_S 单源）。
# templates/diagram 同款域内自注册 add_typer——此处只 re-export（二次
# add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 watchdog 域（零撞
# 名自查 2026-11-02：全 CLI 树无 watchdog/watchdog_ 前缀命令或组，唯一
# 近名 jobs watch/runs watch 为组内叶且语义=job 轮询非 seat 判活）。
# append-only 注册序尾。

from rfauto.cli.domains.watchdog import watchdog_app as watchdog_app
from rfauto.cli.domains.watchdog import watchdog_watch_cmd as watchdog_watch_cmd


# ─── cal-wizard（TRL 校准件设计向导 CLI 出口，2026-11-02 aurora_p G1）──
# （方向 G 候选线索"TRL/校准件设计的用户向导面（当前只有内核+CLI）"的
# 闭合：trl 单叶——频带+介质三口径 → Thru/Reflect/Line 设计单（λg/4
# Line、8:1 覆盖三态核算、多 Line 分带、Reflect 短路/开路建议）；
# --out-dir 给定时落盘设计单 JSON/calkit 定义 YAML/测试连接图 .drawio
# 三件固定名。设计数学=新建 core/trl_design（教科书锚+εeff 走 synthesis
# 单源在内核）；连接图=既有 diagram_testsetup_service 装配内核复用；
# 零数值逻辑转发新建 service/cal_wizard_service，带 --json。
# templates/diagram 同款域内自注册 add_typer——此处只 re-export（二次
# add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 cal-wizard 域
# （零撞名自查 2026-11-02：全 CLI 树无 cal-wizard/cal_wizard 前缀命令
# 或组，唯一近名 calc/vna calibrate 语义=执行校准非设计校准件）。
# append-only 注册序尾。）

from rfauto.cli.domains.cal_wizard import cal_wizard_app as cal_wizard_app
from rfauto.cli.domains.cal_wizard import cal_wizard_trl_cmd as cal_wizard_trl_cmd


# ─── liberty（T-Q34 席位 Q-X34 2026-11-07，aurora_q 数字自动化借鉴方向：
# Liberty (.lib) 时序库结构化解析两叶 parse/list——cells/pins/timing 四张
# NLDM 查找表/internal_power/leakage_power/operating_conditions/
# lu_table_template 结构化输出，缺省紧凑面+--timing/--power 展开；
# dag/loop/anim/vendor-docs 同款：域内自注册 cli/domains/liberty.py
# 模块级 add_typer——此处只 re-export（二次 add_typer 会双注册打红
# zero-shadow 钉）；顶层无同名 `liberty` 域（零撞名自查 2026-11-07：全
# CLI 树零 liberty 前缀组/命令；单源=core/liberty_parser+service/
# liberty_service，不落盘零网络零真机纯读面）。append-only 注册序尾。

from rfauto.cli.domains.liberty import liberty_app as liberty_app
from rfauto.cli.domains.liberty import liberty_list_cmd as liberty_list_cmd
from rfauto.cli.domains.liberty import liberty_parse_cmd as liberty_parse_cmd


# ─── spice（T-Q22 席位 Q-X33 2026-11-07，aurora_q 方向 F 仿真格式域：──
# SPICE 网表深度解析单叶 parse——ngspice/HSPICE/Spectre 三格式统一五维度
# 结构化输出（elements/subckts/controls/models/topology：元件实例端口对+
# 单位提取、子电路层次树、控制语句+扫描步进、模型卡、MNA 维度+节点双向
# 图+孤立节点检测+接地归一）；--flavor auto 内容启发式判定，--topology
# 三态缺省开（#277 家法）；零数值逻辑转发新建 service/spice_netlist_
# service（解析纯函数 core/spice_netlist_parser 单源——core 零外部依赖，
# 不触碰 Q-X20 冻结面 spice_service/fit_macromodel），带 --json；
# liberty 同款域内自注册 add_typer——此处只 re-export（二次 add_typer 会
# 双注册打红 zero-shadow 钉）；顶层无同名 `spice` 域（零撞名自查
# 2026-11-07：全 CLI 树零 spice 前缀组/命令，唯一近名=adapters/
# spice_netlist 渲染器（非 CLI 面）与 ads_circuit 域语义不同）。
# append-only 注册序尾。

from rfauto.cli.domains.spice import spice_app as spice_app
from rfauto.cli.domains.spice import spice_parse_cmd as spice_parse_cmd


# ─── skill（SKILL 代码模板生成 CLI 出口，2026-11-07 aurora_q T-Q27）────
# （Virtuoso-Bridge-lite 核心模式借鉴化用——Python 侧模板化生成 SKILL 代码
# 字符串，输出 .il 供用户在本地 Virtuoso 加载执行，零 Cadence 依赖零真机
# 调用：list=模板目录只读视图/render=模板+变量直出（--var k=v 可多次，
# 值按 JSON 字面量解析失败回退字符串；--out 落盘+--force 防覆盖）/
# lint=SKILL 语法守卫（括号配对/引号闭合/let 绑定/函数名白名单，error 级
# 退出码 1）。内核=新建 core/skill_template_engine（Jinja2 形态自制微实现
# 零新依赖）+core/skill_templates 5 模板注册表（cell_layout/
# schematic_instance/aedt_run_simulation/waveform_export/layer_setup）；
# 零数值逻辑转发新建 service/skill_template_service，全叶带 --json。
# spice/liberty 同款域内自注册 add_typer——此处只 re-export（二次 add_typer
# 会双注册打红 zero-shadow 钉）；顶层无同名 `skill` 域（零撞名自查
# 2026-11-07：全 CLI 树唯一近名 `recipe skill` 为组内叶语义=配方→SKILL.md
# agent 格式导出，非 Cadence SKILL 代码生成）。append-only 注册序尾。

from rfauto.cli.domains.skill import skill_app as skill_app
from rfauto.cli.domains.skill import skill_lint_cmd as skill_lint_cmd
from rfauto.cli.domains.skill import skill_list_cmd as skill_list_cmd
from rfauto.cli.domains.skill import skill_render_cmd as skill_render_cmd


# ─── sdc（T-Q36 席位 Q-X36 2026-11-07，aurora_q 数字自动化借鉴方向）──
# SDC（Synopsys Design Constraints，Tcl 语法子集）约束结构化解析两叶
# parse/list——create_clock/create_generated_clock（period/waveform/
# divide_by/multiply_by）+IO 延迟（input/output min/max）+路径例外
# （false_path/max_delay/min_delay/multicycle）+负载/驱动/扇出/案例
# 分析+时钟网络（latency/uncertainty）结构化输出；--clocks/--timing/
# --paths/--constraints 四旗标 human 分支展开，--json 恒全结构信封。
# skill/liberty 同款域内自注册 cli/domains/sdc.py 模块级 add_typer——
# 此处只 re-export（二次 add_typer 会双注册打红 zero-shadow 钉）；顶层
# 无同名 `sdc` 域（零撞名自查 2026-11-07：全 CLI 树零 sdc 前缀组/命令，
# 唯一近名是 knowledge 术语表 Sdc 混模 S 参数词条语义无关）。单源=
# core/sdc_parser（Tcl 词法+SDC 语义确定性内核）+service/sdc_service，
# 不落盘零网络零真机纯读面。append-only 注册序尾。

from rfauto.cli.domains.sdc import sdc_app as sdc_app
from rfauto.cli.domains.sdc import sdc_list_cmd as sdc_list_cmd
from rfauto.cli.domains.sdc import sdc_parse_cmd as sdc_parse_cmd


# ─── exploded-view（版图 3D 爆炸视图 CLI 出口，2026-11-07 aurora_q Q-X37
# T-Q37：render 单叶——layered_stack spec / KiCad .kicad_pcb s-expr →
# SVG/JSON/PNG 三形态 + geometry_lint 六检查零 ERROR 闭环（lint 报告随信封
# 与 <stem>_lint.json 同落；铁律 7：渲染坐标=layout 单源直通+explode_factor
# 声明参数）。anim/cal-wizard 同款域内自注册 add_typer——此处只 re-export
# （二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 exploded-view
# 域（#df6① 冲突检查 2026-11-07：全 CLI 树零撞名，唯一近名 diagram 域
# 语义=工程图绘制非 3D 渲染）。append-only 注册序尾。

from rfauto.cli.domains.exploded_view import exploded_view_app as exploded_view_app
from rfauto.cli.domains.exploded_view import exploded_view_render_cmd as exploded_view_render_cmd


# ─── layer-3d（版图分层 3D 渲染导出 CLI 出口，2026-11-07 aurora_q Q-X39）──
# （逐层 PNG+叠层合成预览 PNG/SVG：铜层/阻焊层/丝印层/钻孔（Edge.Cuts）
# 每层独立 3D 场景+mplot3d 合成（Agg OO 零 GUI 零真机零 license，纯文本
# s-expr 直读——零 pcbnew 零 KiCad 安装依赖）；glb/step=接口预留 skipped
# 信封如实。exploded-view/cal-wizard 同款域内自注册 add_typer——此处只
# re-export（二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
# layer-3d 域（#df6① 冲突检查 2026-11-07：全 CLI 树零撞名，唯一近名
# exploded-view 语义=爆炸视图单场景渲染非逐层导出、layout 语义=互格式
# 面）。append-only 注册序尾。

from rfauto.cli.domains.layer_3d import layer_3d_app as layer_3d_app
from rfauto.cli.domains.layer_3d import layer_3d_render_cmd as layer_3d_render_cmd


# ─── drc（DRC 规则文件结构化解析 CLI 出口，2026-11-07 aurora_q Q-X48）──
# （DRC 自动化借鉴方向：规则文件 JSON/CSV/自由文本三形态统一解析到内部
# schema（name/type/layer_scope/value/unit/priority/enabled+groups+
# metadata）+validate 面 design×规则集→violations/verdict+RF 特化检查
# 器四件（rf_impedance 阻抗精度/rf_pad_clearance 焊盘间距/
# rf_ground_via_fence 地过孔隔离度/rf_shield_clearance 屏蔽罩间距，
# --rf 启用；无 --rules 时内置缺省 RF 规则集）；--rules/--rf human 分支
# 展开+--json 恒全结构信封；违规≠exit 1（verdict 语义，exit 1 保留调用
# 失败）。sdc 同款域内自注册 cli/domains/drc.py 模块级 add_typer——
# 此处只 re-export（二次 add_typer 会双注册打红 zero-shadow 钉）；顶层
# 无同名 `drc` 域（零撞名自查 2026-11-07：全 CLI 树唯一近名 `kicad drc`
# 叶=KiCad 真机 DRC 运行面语义≠规则文件解析）。单源=core/drc_parser
# （文法+单位归一+方向判定+RF 检查确定性内核）+service/drc_service，
# 不落盘零网络零真机纯读面。append-only 注册序尾。

from rfauto.cli.domains.drc import drc_app as drc_app
from rfauto.cli.domains.drc import drc_parse_cmd as drc_parse_cmd
from rfauto.cli.domains.drc import drc_validate_cmd as drc_validate_cmd


# ─── lvs（Q-X49 席位 2026-11-07，aurora_q LVS 网表对照域）────────────
# LVS（Layout vs Schematic）网表拓扑一致性对照单叶 compare——两份网表
# （SPICE 三格式/Verilog 门级子集）归一统一图表示→图同构（1-WL 颜色
# 精化+回溯）→missing/extra/mismatched 差异清单+参数容差比对+--rf 特化
# （S 参数端口数量/序号/阻抗+传输线串联/并联/耦合线分类）→
# {verdict, score, differences, summary} 报告信封；verdict 拦截退出码
# MATCH=0/其余=1（layout lvs LVS_FLAG 同族），usage 错 exit 2；零数值
# 逻辑转发新建 service/lvs_compare_service（netgen 思想借鉴化用自研，
# SPICE 消费 Q-X33 冻结面 core/spice_netlist_parser 只读），带 --json；
# drc 同款域内自注册 cli/domains/lvs.py 模块级 add_typer——此处只
# re-export（二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
# `lvs` 域（零撞名自查 2026-11-07：全 CLI 树唯一近名 `layout lvs` 叶=
# 几何网表 flag 级对照语义≠两份网表全图同构比对）。append-only 注册序尾。

from rfauto.cli.domains.lvs import lvs_app as lvs_app
from rfauto.cli.domains.lvs import lvs_compare_cmd as lvs_compare_cmd


# ─── ibis（T-Q46 席位 Q-X46 2026-11-07，aurora_q 数字自动化借鉴方向）──
# IBIS（Input/Output Buffer Information Specification，数字 IO buffer
# 行业标准格式）结构化解析两叶 parse/list——[IBIS Ver/File Rev/Date/
# Source]/[Component]/[Manufacturer]/[Package]/[Pin]/[Model]/
# [Model Selector]/[Pullup]/[Pulldown]/[GND Clamp]/[POWER Clamp]/[Ramp]/
# [Rising Waveform]/[Falling Waveform]+[End] → 结构化输出
# {header, components, models, model_selectors, pins}；IV 查找表
# （Voltage→Current）+暂态表（time→voltage）+线性插值在 core 确定性内
# 核（铁律 7）；--component/--model 过滤+--tables 表体展开，--json 恒
# 全结构信封。skill/sdc 同款域内自注册 cli/domains/ibis.py 模块级
# add_typer——此处只 re-export（二次 add_typer 会双注册打红 zero-shadow
# 钉）；顶层无同名 `ibis` 域（零撞名自查 2026-11-07：全 CLI 树零 ibis
# 前缀组/命令，唯一近名 liberty/spice 语义=其他 EDA 格式解析面）。单源
# =core/ibis_parser+service/ibis_service，不落盘零网络零真机纯读面。
# append-only 注册序尾。

from rfauto.cli.domains.ibis import ibis_app as ibis_app
from rfauto.cli.domains.ibis import ibis_list_cmd as ibis_list_cmd
from rfauto.cli.domains.ibis import ibis_parse_cmd as ibis_parse_cmd


# ─── verilog（T-Q47 席位 Q-X47 2026-11-07，aurora_q 数字自动化借鉴方向）
# Verilog HDL（IEEE 1364）结构子集——数字后端 gate-level netlist 标准
# 交接格式——结构化解析两叶 parse/list：module（ANSI 2001 头内全声明与
# 1995 体内方向声明双形态统一）/wire/reg/assign（连续赋值多目标+延迟）/
# instance（门级原语 LRM 14 章全集 26 键注册表 GATE_PRIMITIVES 位置→
# 命名归一 out/inN/ctrl+模块实例 named/positional 双形态）/parameter/
# localparam/defparam 结构化输出+拓扑三件套（instance→driven nets→
# driving instances 三层关系+孤立网 undriven/unloaded 双桶检测——reg
# 与行为块跳过盲区如实豁免不凑报+实例级 DAG 树深度 longest-chain 含
# 组合环检测 cyclic 如实置 None）；--module 单模块过滤+--topology/
# --no-topology 三态缺省开（#277 家法），--json 恒全结构信封。
# sdc/liberty 同款域内自注册 cli/domains/verilog.py 模块级 add_typer——
# 此处只 re-export（二次 add_typer 会双注册打红 zero-shadow 钉）；顶层
# 无同名 `verilog` 域（零撞名自查 2026-11-07：全 CLI 树零 verilog 前缀
# 组/命令，唯一近名=fl1_sg13g2 脚本注释"零 Verilog-A"语义无关）。单源
# =core/verilog_netlist_parser+service/verilog_netlist_service，不落
# 盘零网络零真机纯读面。append-only 注册序尾。

from rfauto.cli.domains.verilog import verilog_app as verilog_app
from rfauto.cli.domains.verilog import verilog_list_cmd as verilog_list_cmd
from rfauto.cli.domains.verilog import verilog_parse_cmd as verilog_parse_cmd


# ─── 批量接线合流（aurora_q §二-1 主代合流笔 2026-11-10；蓝图=runs/aurora_q/
# qx74_audit/FINAL_AUDIT.md §二A+Q-X77/79/80/86/88 五域收官接线）。两种形态：
# ①独立根 14 域=citi/sdf/gdsii/touchstone/ipc356/lefdef/stil/skill_parse/
#   odbpp/bsdl/spectre/veriloga/stdf/ibis_ami——re-export + _core.app
#   add_typer（各域 docstring 处方两步式；此处共用已导入的 `app` 单别名，
#   与各域处方 `_X_reg_app` 同对象同语义）；skill_parse 注册名带下划线、
#   ibis_ami 注册名带连字符（Q-X62/Q-X86 处方原文，零撞名自查各席已做）。
# ②域内自注册 2 域=spef/vcd——模块级已 add_typer，main 只 re-export
#   （二次 add_typer 会双注册打红 zero-shadow 钉）。append-only 注册序尾。

# citi（Q-X35，CITIfile 仪器数据三叶 info/segments/network，独立根）
from rfauto.cli.domains.citi import citi_app as citi_app

app.add_typer(citi_app, name="citi")

# sdf（Q-X61，SDF 标准延迟两叶 parse/report，独立根）
from rfauto.cli.domains.sdf import sdf_app as sdf_app

app.add_typer(sdf_app, name="sdf")

# gdsii（Q-X58，GDSII 二进制两叶 parse/layers，独立根）
from rfauto.cli.domains.gdsii import gdsii_app as gdsii_app

app.add_typer(gdsii_app, name="gdsii")

# touchstone（Q-X64，Touchstone 统一解析一叶 info，独立根）
from rfauto.cli.domains.touchstone import touchstone_app as touchstone_app

app.add_typer(touchstone_app, name="touchstone")

# ipc356（Q-X65，IPC-D-356A 裸板测试网表一叶 report，独立根）
from rfauto.cli.domains.ipc356 import ipc356_app as ipc356_app

app.add_typer(ipc356_app, name="ipc356")

# lefdef（Q-X57，LEF/DEF 5.8 子集两叶 parse/check，独立根三步入）
from rfauto.cli.domains.lefdef import lefdef_app as lefdef_app

app.add_typer(lefdef_app, name="lefdef")

# stil（Q-X72，IEEE 1450 测试向量两叶 parse/report，独立根）
from rfauto.cli.domains.stil import stil_app as stil_app

app.add_typer(stil_app, name="stil")

# skill_parse（Q-X62，SKILL/OCEAN 语言两叶 parse/report，独立根；
# 注册名 skill_parse≠skill——skill 域（Q-X32 模板生成）已占顶名）
from rfauto.cli.domains.skill_parse import skill_parse_app as skill_parse_app

app.add_typer(skill_parse_app, name="skill_parse")

# odbpp（Q-X68，ODB++ 制造数据一叶 report，独立根）
from rfauto.cli.domains.odbpp import odbpp_app as odbpp_app

app.add_typer(odbpp_app, name="odbpp")

# bsdl（Q-X77，IEEE 1149.1 边界扫描描述两叶 parse/report，独立根）
from rfauto.cli.domains.bsdl import bsdl_app as bsdl_app

app.add_typer(bsdl_app, name="bsdl")

# spectre（Q-X79r，Cadence Spectre 网表两叶 parse/report，独立根）
from rfauto.cli.domains.spectre import spectre_app as spectre_app

app.add_typer(spectre_app, name="spectre")

# veriloga（Q-X80r，Verilog-A 行为级两叶 parse/report，独立根）
from rfauto.cli.domains.veriloga import veriloga_app as veriloga_app

app.add_typer(veriloga_app, name="veriloga")

# stdf（Q-X88r，STDF V4 半导体测试数据两叶 parse/report，独立根）
from rfauto.cli.domains.stdf import stdf_app as stdf_app

app.add_typer(stdf_app, name="stdf")

# ibis_ami（Q-X86r，IBIS-AMI 参数两叶 parse/report，独立根；注册名 ibis-ami）
from rfauto.cli.domains.ibis_ami import ibis_ami_app as ibis_ami_app

app.add_typer(ibis_ami_app, name="ibis-ami")

# spef（Q-X60，SPEF 寄生网表两叶 parse/report，域内自注册→只 re-export）
from rfauto.cli.domains.spef import spef_app as spef_app
from rfauto.cli.domains.spef import spef_parse_cmd as spef_parse_cmd
from rfauto.cli.domains.spef import spef_report_cmd as spef_report_cmd

# vcd（Q-X63，VCD 波形两叶 parse/report，域内自注册→只 re-export）
from rfauto.cli.domains.vcd import vcd_app as vcd_app
from rfauto.cli.domains.vcd import vcd_parse_cmd as vcd_parse_cmd
from rfauto.cli.domains.vcd import vcd_report_cmd as vcd_report_cmd

# tri_view（Q-X38，原理图↔版图↔3D 三视图联动一叶 link，独立根；
# aurora_r M-10 接线清偿 Q-X38 挂账——域 docstring"合流契约"两步式）
from rfauto.cli.domains.tri_view import tri_view_app as tri_view_app

app.add_typer(tri_view_app, name="tri-view")


# ─── aedt_migrate（aurora_r AM-S4 席位 2026-11-10，老版本 .aedt 批量迁移 ──
# 通道）。AEDT 版本迁移三叶 run/status/report（设计稿
# aedt_migrate_design_handoff §1 五阶段决策树：直开→体检→对比→桥接→
# 抢救，每工程产出结构化迁移报告；verdict 9 枚举诚实终态，CLI 层零重
# 试零凑绿 #122；run 零逻辑转发 service/aedt_migrate_service.migrate_
# batch，status/report 消费 read_migration_report——S1 service docstring
# 挂账处方原文落位；三叶全带 --json，路径参数 str 注解 #269）。citi 同
# 款独立根 re-export + _core.app add_typer（两步式）；顶层无同名
# `aedt-migrate` 域（零撞名自查 2026-11-10：全 CLI 树无该前缀组/命令，
# 唯一近名 hfss-import=工程导入器语义≠版本迁移通道）。append-only 注
# 册序尾。

from rfauto.cli.domains.aedt_migrate import aedt_migrate_app as aedt_migrate_app

app.add_typer(aedt_migrate_app, name="aedt-migrate")


# ─── help 按域分组（aurora_n wave_ui_c D1，审计 P2-4：--help 119 命令 ──
# 平铺→8 域 rich 面板）。只对注册完的 CommandInfo/GroupInfo 补挂
# rich_help_panel 渲染注记——注册面（顺序/计数/命名）零变化：注册序金
# 快照/leaf 计数/zero-shadow 三钉不受影响；未入表新命令回落缺省 Commands
# 面板（不炸不隐藏），覆盖完整性由 test_aurora_n_wave_ui_c 集合断言守。
# 名字走下划线前缀（_help_groups/_n_panels）——本模块公开名面（AU-1
# facade re-export 显式别名序）不因本席变化。
import rfauto.cli.help_groups as _help_groups

_n_panels = _help_groups.apply_help_panels(app)


if __name__ == "__main__":
    app()
