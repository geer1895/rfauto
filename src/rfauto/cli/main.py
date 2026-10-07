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
# status（py-spy 可用性探测）/ run（py-spy record 封装，火焰图落 runs/profile）
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


# ─── dag（VI-4/SN-1 接线，Phase2 W2-A：DAG 执行基座两叶；stats/firmware ──
# 同款：域内自注册 cli/domains/dag.py 模块级 add_typer——此处只 re-export
# （二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 `dag` 域
# （#df6① 冲突检查 2026-10-05：全 CLI 树零撞名，SP 席 VI-4 接地复核）。

from rfauto.cli.domains.dag import dag_app as dag_app
from rfauto.cli.domains.dag import dag_run as dag_run
from rfauto.cli.domains.dag import dag_run_cmd as dag_run_cmd
from rfauto.cli.domains.dag import dag_status as dag_status
from rfauto.cli.domains.dag import dag_status_cmd as dag_status_cmd


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


if __name__ == "__main__":
    app()
