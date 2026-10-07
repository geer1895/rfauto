"""W6-C AD-5 五段模板批 2+批 3 门（runs/w6_phase6/criteria.md W6-C 节）。

W5-A 批 1（test_w5_a_ad5_gates.py）同构三面，扩到余量 106 工具：
  - Z-10b 五段 regex 门（批 2=52 件 <120 chars 组 / 批 3=54 件 ≥120 chars
    组——SK §3.3 分批口径；清单闭集冻结，不随并发席位新工具漂移）；
  - 签名冻结 + 载荷守卫（改 description 不碰 def 行；单工具 description
    增量 ≤120 chars/批 1 实测口径；批面 max ≤450 / 批面+批 1 median ≤200
    ——全量 median/max 由 W5-A 门 test_payload_guard_median_and_max 承担）；
  - Z-10a 转发型只读工具 Returns 键集运行时对拍（批 2 7 件+批 3 6 件，
    全部本地确定性通道零 LLM 零网络，#139 纪律）。

规格：runs/research_seats_20261004/sk_specs5/SPECS.md §三（AD-5）；批 1
先例 test_w5_a_ad5_gates.py。锚定快照=2026-10-05 批 2/3 改 docstring 前
（runs/w6_phase6/w6c/baseline.json，106 件签名+description 前长度）。
注记：并发席位（W6-B SN-16 optim.py 等）新增工具不在本席清单内（#228
门作用域限本项文件）。
"""

from __future__ import annotations

import asyncio
import inspect
import re
import statistics
import typing
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# ─── 批 2/批 3 实名清单（SK §3.3：<120 chars=批 2 / ≥120 chars=批 3）────────
BATCH2: tuple[str, ...] = (
    "adc_interleave_spurs", "agentbench_regression", "anchors_inspect",
    "bands_env_delta_t", "bands_env_list", "bands_env_uq_axis", "bands_list",
    "bands_spec_bounds", "cascade_budget", "cm_diagnose_q",
    "cm_extract_refine", "compare_runs", "compose_netlist", "create_run",
    "dataset_annotate_ground_truth", "dataset_coverage", "dataset_export_hf",
    "dataset_set_visibility", "db_init", "db_migrate", "db_reindex_runs",
    "db_status", "doctor", "explain_run", "export_report_pdf",
    "farfield_runs", "farfield_view", "goldset_regression", "if_plan_sweep",
    "import_solid_payload", "jitter_budget_snr", "kicad_extract",
    "kicad_optimize_cpw", "list_datasets", "metasurface_coding_pattern",
    "msl_floor_life_query", "nfmeas_cut_view", "poll_job",
    "rf_critique_point", "rf_propose_params", "rf_run_sampler",
    "rf_spec_cost", "robustness_report", "save_campaign_plan",
    "spur_search", "synthesize", "uq_design_center", "uq_temperature_zone",
    "uq_yield_at", "vna_offline_replay", "warm_start_optimize",
    "weave_style_info",
)

BATCH3: tuple[str, ...] = (
    "afs_plan", "aging_simulate", "aging_verdict", "autotune_self_verify",
    "cancel_job", "cm_cat_critique", "com_pam4_run", "create_run_async",
    "cryo_surface_estimate", "diagnose", "discover_workdir_runs",
    "dispersion_report", "draft_recipe_from_spec", "electrothermal_chain",
    "emc_cispr_band_params", "emc_cispr_detect", "emc_cm_radiated_budget",
    "emc_ground_spacing_check", "error_hints_lookup", "even_odd_report",
    "get_campaign_status", "get_guidelines_for", "get_model_3d",
    "get_run_artifacts", "humidity_uptake", "import_workdir_runs",
    "inverse_prefilter", "lake_pack_campaign", "list_calculators",
    "list_template_specs", "marchand_balun_design", "mcts_search",
    "metasurface_quant_loss_db", "mmt_solve", "parasitic_extract_rlc",
    "pdn_analyze", "pdn_select", "plan_campaign", "query_dataset",
    "read_hfss_touchstone_comments", "recommend_templates",
    "remote_machine_status", "remote_probe_machine",
    "render_constraint_check", "report_narrative", "run_campaign",
    "run_monitor", "self_heal_run", "si_channel_report", "synthesize_bpf",
    "topology_propose", "uq_rare_yield", "vna_en_report",
    "weave_skew_estimate",
)

BATCH23: tuple[str, ...] = BATCH2 + BATCH3

# 批 1 清单（W5-A 批，与本席批面拼合算 median 责任面）。
_BATCH1: tuple[str, ...] = (
    "correlate_measurement", "budget_analysis", "get_metrics",
    "validate_recipe", "nfc_coil_synthesize", "bands_find",
    "bands_env_find", "sar_analytic_plane_wave", "nfc_coil_q",
    "nfc_coil_evaluate", "bands_env_points", "nfmeas_ffs_info",
    "rag_query", "rag_explain", "search_knowledge", "rationale_recall",
    "rationale_checklist", "pdn_gate", "run_calculator",
    "list_composable_templates",
)

#: 批 2/3 改 docstring 前取证签名（baseline.json 快照，2026-10-05 pre-edit；
#: 描述批不得触碰 def 行——签名零变钉）。
BATCH23_SIGNATURES: dict[str, str] = {
    "adc_interleave_spurs": "(fs_mhz: 'float', fin_mhz: 'float', n_lanes: 'int', n_orders: 'int' = 4) -> 'dict[str, Any]'",
    "afs_plan": "(f_min_ghz: 'float', f_max_ghz: 'float', tol: 'float' = 0.01, max_points: 'int' = 96, n_init: 'int' = 7, max_rounds: 'int' = 12) -> 'dict[str, Any]'",
    "agentbench_regression": "(records: 'list[dict[str, Any]] | None' = None, public_path: 'str | None' = None, private_path: 'str | None' = None, runtime_tools: 'list[str] | None' = None, min_abstraction: 'float' = 0.9, min_execution: 'float' = 0.8, require_private: 'bool' = False, require_full_coverage: 'bool' = True) -> 'dict[str, Any]'",
    "aging_simulate": "(payload: 'dict[str, Any]') -> 'dict[str, Any]'",
    "aging_verdict": "(payload: 'dict[str, Any]') -> 'dict[str, Any]'",
    "anchors_inspect": "(anchor_id: 'str') -> 'dict[str, Any]'",
    "autotune_self_verify": "(recipe_path: 'str', budget_coarse: 'int' = 3, mesh_coarse_mm: 'float' = 1.0, mesh_fine_mm: 'float' = 0.5, f0_tolerance: 'float' = 0.15, rl_floor_db: 'float' = -8.0, max_step_pct: 'float' = 0.2, fine_epsilon: 'float' = 0.2, sandbox: 'bool' = True, board: 'bool' = True) -> 'dict[str, Any]'",
    "bands_env_delta_t": "(key: 'str', t_ref_c: 'float | None' = None) -> 'dict[str, Any]'",
    "bands_env_list": "(standard: 'str | None' = None, kind: 'str | None' = None) -> 'dict[str, Any]'",
    "bands_env_uq_axis": "(key: 'str', t_ref_c: 'float | None' = None, k_sigma: 'float' = 3.0) -> 'dict[str, Any]'",
    "bands_list": "(standard: 'str | None' = None, kind: 'str | None' = None, region: 'str | None' = None) -> 'dict[str, Any]'",
    "bands_spec_bounds": "(key: 'str') -> 'dict[str, Any]'",
    "cancel_job": "(job_id: 'str') -> 'dict[str, Any]'",
    "cascade_budget": "(stages: 'list[dict]', snr_min_db: 'float' = 10.0, rx_power_dbm: 'float | None' = None, bw_hz: 'float | None' = None) -> 'dict[str, Any]'",
    "cm_cat_critique": "(freq_ghz: 'list[float]', s21: 'list | None' = None, s11: 'list | None' = None, f0_ghz: 'float' = 0.0, fbw: 'float' = 0.0, target_matrix: 'list | None' = None, current_params: 'dict | None' = None, bounds: 'dict | None' = None, tol: 'float' = 0.1) -> 'dict[str, Any]'",
    "cm_diagnose_q": "(network_path: 'str | None' = None, freq_ghz: 'list[float] | None' = None, s11: 'list | None' = None, f0_hint_ghz: 'float | None' = None, q_e: 'list[float] | None' = None) -> 'dict[str, Any]'",
    "cm_extract_refine": "(network_path: 'str | None' = None, freq_ghz: 'list[float] | None' = None, s11: 'list | None' = None, s21: 'list | None' = None, order: 'int | None' = None, f0_ghz: 'float | None' = None, fbw: 'float | None' = None, topology: 'str' = 'folded', target_matrix: 'list | None' = None) -> 'dict[str, Any]'",
    "com_pam4_run": "(thru_s4p: 'str', preset: 'str' = '8023dj', fb_gbaud: 'float | None' = None, fext_s4p: 'list[str] | None' = None, next_s4p: 'list[str] | None' = None, g_dc_stride: 'int' = 8, g_dc2_stride: 'int' = 11, pinned_taps: 'list[float] | None' = None, opt_mode: 'str' = 'przf') -> 'dict[str, Any]'",
    "compare_runs": "(run_id_a: 'str', run_id_b: 'str') -> 'dict[str, Any]'",
    "compose_netlist": "(netlist: 'dict', out_dir: 'str | None' = None) -> 'dict[str, Any]'",
    "create_run": "(recipe_path: 'str', adapter: 'str' = 'fake') -> 'dict[str, Any]'",
    "create_run_async": "(recipe_path: 'str', adapter: 'str' = 'fake') -> 'dict[str, Any]'",
    "cryo_surface_estimate": "(payload: 'dict[str, Any]') -> 'dict[str, Any]'",
    "dataset_annotate_ground_truth": "(name: 'str', threshold: 'int' = 100, out_dir: 'str' = 'runs/datasets') -> 'dict[str, Any]'",
    "dataset_coverage": "(name: 'str', bins: 'int' = 10, out_dir: 'str' = 'runs/datasets') -> 'dict[str, Any]'",
    "dataset_export_hf": "(name: 'str', license: 'str' = '', allow_private: 'bool' = False, out_dir: 'str' = 'runs/datasets') -> 'dict[str, Any]'",
    "dataset_set_visibility": "(name: 'str', visibility: 'str', out_dir: 'str' = 'runs/datasets') -> 'dict[str, Any]'",
    "db_init": "(db_path: 'str | None' = None) -> 'dict[str, Any]'",
    "db_migrate": "(db_path: 'str | None' = None) -> 'dict[str, Any]'",
    "db_reindex_runs": "(runs_dir: 'str' = 'runs', db_path: 'str | None' = None) -> 'dict[str, Any]'",
    "db_status": "(db_path: 'str | None' = None) -> 'dict[str, Any]'",
    "diagnose": "(run_id: 'str') -> 'dict[str, Any]'",
    "discover_workdir_runs": "(runs_root: 'str' = 'runs', models: 'list[str] | None' = None) -> 'dict[str, Any]'",
    "dispersion_report": "(material: 'str', band_ghz: 'list[float] | None' = None, max_eps_r_drift: 'float' = 0.02) -> 'dict[str, Any]'",
    "doctor": "() -> 'dict[str, Any]'",
    "draft_recipe_from_spec": "(name: 'str', params: 'dict[str, Any] | None' = None) -> 'dict[str, Any]'",
    "electrothermal_chain": "(payload: 'dict[str, Any]') -> 'dict[str, Any]'",
    "emc_cispr_band_params": "(band: 'str') -> 'dict[str, Any]'",
    "emc_cispr_detect": "(samples: 'list[float]', fs_mhz: 'float', band: 'str', f_center_mhz: 'float | None' = None, unit_dbuv_ref: 'float | None' = None) -> 'dict[str, Any]'",
    "emc_cm_radiated_budget": "(f_mhz: 'float', length_m: 'float', distance_m: 'float', v_cm_v: 'float', c_pf: 'float | None' = None, coupling_area_cm2: 'float | None' = None, coupling_distance_mm: 'float | None' = None, l_path_nh: 'float' = 0.0, r_path_ohm: 'float' = 0.0, er: 'float' = 1.0, with_ground_image: 'bool' = True) -> 'dict[str, Any]'",
    "emc_ground_spacing_check": "(spacing_mm: 'float', f_mhz: 'float') -> 'dict[str, Any]'",
    "error_hints_lookup": "(message: 'str') -> 'dict[str, Any]'",
    "even_odd_report": "(template: 'str', params: 'dict[str, Any] | None' = None, freq_ghz: 'float | None' = None) -> 'dict[str, Any]'",
    "explain_run": "(run_dir: 'str', playbook_path: 'str | None' = None) -> 'dict[str, Any]'",
    "export_report_pdf": "(run_id: 'str', filename: 'str' = 'report.pdf', narrative: 'str | None' = None) -> 'dict[str, Any]'",
    "farfield_runs": "(limit: 'int' = 50) -> 'dict[str, Any]'",
    "farfield_view": "(run_id: 'str') -> 'dict[str, Any]'",
    "get_campaign_status": "(plan_path: 'str') -> 'dict[str, Any]'",
    "get_guidelines_for": "(topic: 'str') -> 'dict[str, Any]'",
    "get_model_3d": "(recipe_path: 'str') -> 'dict[str, Any]'",
    "get_run_artifacts": "(run_id: 'str') -> 'dict[str, Any]'",
    "goldset_regression": "(trajectories: 'list[dict[str, Any]] | None' = None, goldset_path: 'str | None' = None, runtime_tools: 'list[str] | None' = None, min_tsa: 'float' = 0.9, min_fca: 'float' = 0.9, min_pass3: 'float' = 0.0, require_full_coverage: 'bool' = True) -> 'dict[str, Any]'",
    "humidity_uptake": "(payload: 'dict[str, Any]') -> 'dict[str, Any]'",
    "if_plan_sweep": "(f_rf_hz: 'float', if_lo_hz: 'float', if_hi_hz: 'float', side: 'str' = 'low', n_points: 'int' = 201, if_bw_hz: 'float' = 0.0, max_order: 'int' = 7) -> 'dict[str, Any]'",
    "import_solid_payload": "(path: 'str', material: 'str' = 'metal') -> 'dict[str, Any]'",
    "import_workdir_runs": "(name: 'str', run_ids: 'list[str] | None' = None, runs_root: 'str' = 'runs', out_dir: 'str' = 'runs/datasets', models: 'list[str] | None' = None, health_gate: 'bool' = True, fmt: 'str' = 'parquet') -> 'dict[str, Any]'",
    "inverse_prefilter": "(recipe_path: 'str', target_metrics: 'dict[str, float]', n_corpus: 'int' = 400, k: 'int' = 20, jitter: 'float' = 0.03, seed: 'int' = 42) -> 'dict[str, Any]'",
    "jitter_budget_snr": "(rj_rms_ui: 'float', dj_ui: 'float', ber: 'float' = 1e-12) -> 'dict[str, Any]'",
    "kicad_extract": "(pcb_path: 'str', kicad_python: 'str | None' = None) -> 'dict[str, Any]'",
    "kicad_optimize_cpw": "(pcb_path: 'str', target_z0_ohm: 'float | None' = None, freq_ghz: 'float | None' = None, z0_tol_ohm: 'float | None' = None) -> 'dict[str, Any]'",
    "lake_pack_campaign": "(campaign_dir: 'str', out_path: 'str') -> 'dict[str, Any]'",
    "list_calculators": "(include_experimental: 'bool' = True) -> 'dict[str, Any]'",
    "list_datasets": "(visibility: 'str | None' = None, out_dir: 'str' = 'runs/datasets') -> 'dict[str, Any]'",
    "list_template_specs": "() -> 'dict[str, Any]'",
    "marchand_balun_design": "(f0_ghz: 'float', h_mm: 'float', er: 'float', w_slot_mm: 'float', tan_d: 'float' = 0.0037, z_msl_target: 'float' = 50.0) -> 'dict[str, Any]'",
    "mcts_search": "(samples_path: 'str', n_simulations: 'int' = 200, n_steps: 'int' = 6, step_size: 'float' = 0.1, kind: 'str' = 'poly_ridge', seed: 'int' = 42) -> 'dict[str, Any]'",
    "metasurface_coding_pattern": "(code_matrix: 'list[list[int]]', bits: 'int', period_um: 'float', f0_ghz: 'float', pad: 'int' = 4, normalize: 'bool' = True) -> 'dict[str, Any]'",
    "metasurface_quant_loss_db": "(n_elements: 'int', bits: 'int', u_beam: 'float', v_beam: 'float', period_um: 'float', f0_ghz: 'float', pad: 'int' = 8) -> 'dict[str, Any]'",
    "mmt_solve": "(sections: 'list[dict[str, Any]]', freqs_ghz: 'list[float] | None' = None, eps_r: 'float' = 1.0, tan_d: 'float' = 0.0, sigma_s_m: 'float | None' = None, mode_policy: 'dict[str, Any] | None' = None, z0_ref: 'float' = 50.0, freq_start_ghz: 'float | None' = None, freq_stop_ghz: 'float | None' = None, n_freq: 'int' = 41, work_dir: 'str | None' = None) -> 'dict[str, Any]'",
    "msl_floor_life_query": "(payload: 'dict[str, Any]') -> 'dict[str, Any]'",
    "nfmeas_cut_view": "(path: 'str', freq_index: 'int' = 0, phi_deg: 'float | None' = None, theta_deg: 'float | None' = None) -> 'dict[str, Any]'",
    "parasitic_extract_rlc": "(payload: 'dict[str, Any]') -> 'dict[str, Any]'",
    "pdn_analyze": "(payload: 'dict[str, Any]') -> 'dict[str, Any]'",
    "pdn_select": "(payload: 'dict[str, Any]') -> 'dict[str, Any]'",
    "plan_campaign": "(recipe_path: 'str', high_adapter: 'str' = 'hfss', mid_adapter: 'str' = 'openems', calibrate_samples: 'int' = 9, tune_budget: 'int | None' = None) -> 'dict[str, Any]'",
    "poll_job": "(job_id: 'str') -> 'dict[str, Any]'",
    "query_dataset": "(name: 'str', where: 'str | None' = None, columns: 'list[str] | None' = None, limit: 'int' = 100, model: 'str | None' = None, study_name: 'str | None' = None, out_dir: 'str' = 'runs/datasets') -> 'dict[str, Any]'",
    "read_hfss_touchstone_comments": "(path: 'str') -> 'dict[str, Any]'",
    "recommend_templates": "(f0_ghz: 'float', topology: 'str | None' = None, n_ports: 'int | None' = None, keywords: 'str | None' = None, top_k: 'int' = 5) -> 'dict[str, Any]'",
    "remote_machine_status": "(machine: 'str | None' = None) -> 'dict[str, Any]'",
    "remote_probe_machine": "(machine: 'str | None' = None) -> 'dict[str, Any]'",
    "render_constraint_check": "(config: 'dict[str, Any]') -> 'dict[str, Any]'",
    "report_narrative": "(run_id: 'str', narrative: 'str | None' = None, on_unauthorized: 'str' = 'reject') -> 'dict[str, Any]'",
    "rf_critique_point": "(metrics: 'dict[str, float]', objectives: 'list[dict[str, Any]]', valley_ghz: 'float | None' = None, bounds: 'dict[str, list[float]] | None' = None, current_params: 'dict[str, float] | None' = None) -> 'dict[str, Any]'",
    "rf_propose_params": "(bounds: 'dict[str, list[float]]', current_params: 'dict[str, float] | None' = None, fixes: 'list[dict[str, Any]] | None' = None) -> 'dict[str, Any]'",
    "rf_run_sampler": "(recipe_path: 'str', params: 'dict[str, float]', mesh_resolution_mm: 'float' = 0.0) -> 'dict[str, Any]'",
    "rf_spec_cost": "(metrics: 'dict[str, float]', objectives: 'list[dict[str, Any]]') -> 'dict[str, Any]'",
    "robustness_report": "(source: 'str', specs: 'list[dict[str, Any]]', profile: 'dict[str, Any] | None' = None, tolerances: 'dict[str, float] | None' = None, n_mc: 'int' = 100000, seed: 'int' = 42, kind: 'str' = 'poly_ridge', form_engine: 'str' = 'auto', persist: 'bool' = False, store_name: 'str | None' = None) -> 'dict[str, Any]'",
    "run_campaign": "(plan_path: 'str', dry_run: 'bool' = False, resume: 'bool' = False) -> 'dict[str, Any]'",
    "run_monitor": "(run_dir: 'str', cycle: 'bool' = False, nr_ts: 'int | None' = None) -> 'dict[str, Any]'",
    "save_campaign_plan": "(plan: 'dict[str, Any]', out_dir: 'str') -> 'dict[str, Any]'",
    "self_heal_run": "(run_id: 'str', retries: 'int' = 0) -> 'dict[str, Any]'",
    "si_channel_report": "(source: 'str', passivity_tol: 'float' = 0.01, causality_threshold: 'float' = 0.02, pre_cursor_guard_ns: 'float' = 1.0, tdr_window_ns: 'float' = 2.0, fext_paths: 'list[str] | None' = None, next_paths: 'list[str] | None' = None, markdown: 'bool' = False) -> 'dict[str, Any]'",
    "spur_search": "(f_rf_hz: 'float', f_lo_hz: 'float', if_center_hz: 'float | None' = None, if_bw_hz: 'float' = 0.0, rf_bw_hz: 'float' = 0.0, max_order: 'int' = 7) -> 'dict[str, Any]'",
    "synthesize": "(z0_target: 'float', freq_ghz: 'float' = 2.4, stackup: 'str' = 'rogers4350b_h0.508') -> 'dict[str, Any]'",
    "synthesize_bpf": "(order: 'int', f0_ghz: 'float', fbw: 'float', rl_db: 'float', transmission_zeros_ghz: 'list[float] | None' = None, topology: 'str' = 'folded') -> 'dict[str, Any]'",
    "topology_propose": "(spec: 'dict[str, Any]', proposer: 'str' = 'rule_based', campaign: 'bool' = False, n_trials: 'int' = 80, seed: 'int' = 20260914, sandbox_name: 'str | None' = None, promote: 'bool' = False) -> 'dict[str, Any]'",
    "uq_design_center": "(samples_path: 'str', tolerances: 'dict[str, float]', k_sigma: 'float' = 3.0, n_levels: 'int' = 3, max_iter: 'int' = 40, n_mc: 'int' = 2000, seed: 'int' = 42, kind: 'str' = 'poly_ridge') -> 'dict[str, Any]'",
    "uq_rare_yield": "(samples_path: 'str', tolerances: 'dict[str, float] | None' = None, threshold: 'float' = 0.0, n_is: 'int' = 5000, seed: 'int' = 0) -> 'dict[str, Any]'",
    "uq_temperature_zone": "(samples_path: 'str', env_key: 'str', tolerances: 'dict[str, float] | None' = None, t_ref_c: 'float | None' = None, k_sigma: 'float' = 3.0, n: 'int' = 10000, seed: 'int' = 42, kind: 'str' = 'poly_ridge') -> 'dict[str, Any]'",
    "uq_yield_at": "(samples_path: 'str', tolerances: 'dict[str, float]', nominal: 'dict[str, float]', n: 'int' = 10000, seed: 'int' = 42, kind: 'str' = 'poly_ridge') -> 'dict[str, Any]'",
    "vna_en_report": "(lab_s2p: 'str', ref_s2p: 'str', traces: 'list[str] | None' = None, delta_t_c: 'float | None' = None, anchor_uncertainty_db: 'float | None' = None, hfss_residual_db: 'float | None' = None, markdown_path: 'str | None' = None) -> 'dict[str, Any]'",
    "vna_offline_replay": "(measured_s2p: 'str', sim_s2p: 'str | None' = None, threshold_db: 'float' = 3.0, session_path: 'str | None' = None) -> 'dict[str, Any]'",
    "warm_start_optimize": "(recipe_path: 'str', dataset: 'str', model: 'str | None' = None, source_study: 'str | None' = None, adapter: 'str' = 'fake', max_trials: 'int' = 60) -> 'dict[str, Any]'",
    "weave_skew_estimate": "(payload: 'dict[str, Any]') -> 'dict[str, Any]'",
    "weave_style_info": "(payload: 'dict[str, Any] | None' = None) -> 'dict[str, Any]'",
}

#: 批 2/3 前描述长度（同上快照；载荷守卫增量 ≤120 chars/工具的基线）。
BATCH23_DESC_LEN_BEFORE: dict[str, int] = {
    "adc_interleave_spurs": 46,
    "afs_plan": 186,
    "agentbench_regression": 82,
    "aging_simulate": 235,
    "aging_verdict": 136,
    "anchors_inspect": 67,
    "autotune_self_verify": 213,
    "bands_env_delta_t": 84,
    "bands_env_list": 57,
    "bands_env_uq_axis": 48,
    "bands_list": 59,
    "bands_spec_bounds": 101,
    "cancel_job": 123,
    "cascade_budget": 58,
    "cm_cat_critique": 136,
    "cm_diagnose_q": 108,
    "cm_extract_refine": 57,
    "com_pam4_run": 257,
    "compare_runs": 47,
    "compose_netlist": 53,
    "create_run": 60,
    "create_run_async": 128,
    "cryo_surface_estimate": 189,
    "dataset_annotate_ground_truth": 103,
    "dataset_coverage": 66,
    "dataset_export_hf": 103,
    "dataset_set_visibility": 68,
    "db_init": 107,
    "db_migrate": 68,
    "db_reindex_runs": 115,
    "db_status": 54,
    "diagnose": 171,
    "discover_workdir_runs": 210,
    "dispersion_report": 259,
    "doctor": 119,
    "draft_recipe_from_spec": 124,
    "electrothermal_chain": 167,
    "emc_cispr_band_params": 252,
    "emc_cispr_detect": 131,
    "emc_cm_radiated_budget": 183,
    "emc_ground_spacing_check": 125,
    "error_hints_lookup": 210,
    "even_odd_report": 181,
    "explain_run": 99,
    "export_report_pdf": 63,
    "farfield_runs": 47,
    "farfield_view": 90,
    "get_campaign_status": 172,
    "get_guidelines_for": 310,
    "get_model_3d": 175,
    "get_run_artifacts": 167,
    "goldset_regression": 82,
    "humidity_uptake": 163,
    "if_plan_sweep": 50,
    "import_solid_payload": 45,
    "import_workdir_runs": 194,
    "inverse_prefilter": 156,
    "jitter_budget_snr": 51,
    "kicad_extract": 104,
    "kicad_optimize_cpw": 112,
    "lake_pack_campaign": 247,
    "list_calculators": 193,
    "list_datasets": 76,
    "list_template_specs": 205,
    "marchand_balun_design": 215,
    "mcts_search": 172,
    "metasurface_coding_pattern": 45,
    "metasurface_quant_loss_db": 149,
    "mmt_solve": 355,
    "msl_floor_life_query": 65,
    "nfmeas_cut_view": 41,
    "parasitic_extract_rlc": 171,
    "pdn_analyze": 129,
    "pdn_select": 197,
    "plan_campaign": 165,
    "poll_job": 56,
    "query_dataset": 156,
    "read_hfss_touchstone_comments": 239,
    "recommend_templates": 228,
    "remote_machine_status": 227,
    "remote_probe_machine": 176,
    "render_constraint_check": 177,
    "report_narrative": 136,
    "rf_critique_point": 74,
    "rf_propose_params": 58,
    "rf_run_sampler": 113,
    "rf_spec_cost": 56,
    "robustness_report": 104,
    "run_campaign": 282,
    "run_monitor": 179,
    "save_campaign_plan": 87,
    "self_heal_run": 217,
    "si_channel_report": 281,
    "spur_search": 52,
    "synthesize": 65,
    "synthesize_bpf": 138,
    "topology_propose": 215,
    "uq_design_center": 69,
    "uq_rare_yield": 177,
    "uq_temperature_zone": 85,
    "uq_yield_at": 44,
    "vna_en_report": 187,
    "vna_offline_replay": 91,
    "warm_start_optimize": 81,
    "weave_skew_estimate": 127,
    "weave_style_info": 50,
}

_FAILURE_KEYWORDS = ("ok=False", "errors", "异常", "UNKNOWN", "ok: False",
                     "报错")
_BOUNDARY_KEYWORDS = ("不用于", "无副作用", "只读", "UNKNOWN", "如实")


def _tool_modules() -> list[str]:
    pkg_dir = Path(__import__("rfauto.mcp_tools",
                              fromlist=["x"]).__file__).parent
    return sorted(p.stem for p in pkg_dir.glob("*.py")
                  if not p.name.startswith("_"))


_MODULE_CACHE: list[str] | None = None


def _modules() -> list[str]:
    global _MODULE_CACHE
    if _MODULE_CACHE is None:
        _MODULE_CACHE = _tool_modules()
    return _MODULE_CACHE


def _tool_fn(name: str):
    for mod in _modules():
        module = __import__(f"rfauto.mcp_tools.{mod}", fromlist=[name])
        fn = getattr(module, name, None)
        if fn is not None:
            return fn
    from rfauto import mcp_server
    return getattr(mcp_server, name)


def _docstring_of(name: str) -> str:
    return inspect.getdoc(_tool_fn(name)) or ""


def _split_description(doc: str) -> str:
    """FastMCP description 语义：docstring 中 Args: 段之前的全部文本。"""
    m = re.search(r"^\s*Args:\s*$", doc, flags=re.M)
    return doc[: m.start()] if m else doc


def _tool_map() -> dict[str, object]:
    from rfauto.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    return {t.name: t for t in tools}


def _schema_params_of(name: str) -> set[str]:
    try:
        tool = _tool_map()[name]
    except Exception:
        return set()
    return set((tool.parameters or {}).get("properties", {}))  # type: ignore


# ─── Z-10b：五段 regex 门（批 2/批 3 清单参数化）──────────────────────────────

@pytest.fixture(scope="module")
def tools_by_name() -> dict[str, object]:
    return _tool_map()


class TestZ10bFiveSegmentGate:
    def test_batch23_all_registered(self, tools_by_name):
        missing = [n for n in BATCH23 if n not in tools_by_name]
        assert not missing, f"批 2/3 清单工具未注册: {missing}"

    def test_lists_disjoint_and_frozen_size(self):
        assert not (set(BATCH2) & set(BATCH3)), "批 2/批 3 清单交集非空"
        assert len(BATCH2) == 52 and len(BATCH3) == 54, (
            "批清单尺寸漂移（52+54=106，W6-C 闭集）")

    @pytest.mark.parametrize("name", BATCH23)
    def test_segment1_first_line_within_80(self, name):
        doc = _docstring_of(name)
        desc = _split_description(doc)
        first = desc.splitlines()[0].strip() if desc.strip() else ""
        assert first, f"{name}: 段 1（一句功能）首行为空"
        assert len(first) <= 80, f"{name}: 段 1 首行 {len(first)} chars > 80"

    @pytest.mark.parametrize("name", BATCH23)
    def test_segment2_boundary_semantics(self, name):
        desc = _split_description(_docstring_of(name))
        assert any(k in desc for k in _BOUNDARY_KEYWORDS), (
            f"{name}: 段 2（边界/何时不用）语义缺失")

    @pytest.mark.parametrize("name", BATCH23)
    def test_failure_semantics_in_description(self, name):
        desc = _split_description(_docstring_of(name))
        assert any(k in desc for k in _FAILURE_KEYWORDS), (
            f"{name}: description 无失败语义关键词（ok=False/errors/异常）")

    @pytest.mark.parametrize("name", BATCH23)
    def test_args_and_returns_sections_exist(self, name):
        doc = _docstring_of(name)
        m_args = re.search(r"^\s*Args:\s*$", doc, flags=re.M)
        m_ret = re.search(r"^\s*Returns:\s*$", doc, flags=re.M)
        params = _schema_params_of(name)
        if params:
            assert m_args, f"{name}: 有参数但缺 Args: 段（段 3 必填）"
        assert m_ret, f"{name}: 缺 Returns: 段（段 4 必填）"
        if m_args:
            assert m_ret.start() > m_args.start(), f"{name}: Returns 段序非法"

    @pytest.mark.parametrize("name", BATCH23)
    def test_args_lines_well_formed(self, name):
        """参数行格式 + 续行容差：续行只要求保持缩进（零顶格逃逸）。"""
        doc = _docstring_of(name)
        in_args = False
        n_params = 0
        for line in doc.splitlines():
            if line.strip() == "Args:":
                in_args = True
                continue
            if in_args and re.match(r"^\s*Returns:\s*$", line):
                break
            if in_args:
                if not line.strip():
                    continue
                if re.match(r"^\s{4,}([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:",
                            line):
                    n_params += 1
                    continue
                assert line.startswith("    "), (
                    f"{name}: Args 块顶格行逃逸: {line!r}")
        if _schema_params_of(name):
            assert n_params >= 1, f"{name}: Args 段零参数行"

    def test_batch23_args_documentation_complete(self, tools_by_name):
        """批 2/3 的 Args 段全覆盖自有参数（phantom 门正向补钉）。"""
        for name in BATCH23:
            documented: set[str] = set()
            in_args = False
            for line in (_docstring_of(name) or "").splitlines():
                if line.strip() == "Args:":
                    in_args = True
                    continue
                if in_args and re.match(
                        r"^\s*(Returns|Raises|Notes|Examples?):\s*$", line):
                    break
                if in_args:
                    m = re.match(
                        r"^\s{4,}([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:", line)
                    if m:
                        documented.add(m.group(1))
            params = set((tools_by_name[name].parameters or {})
                         .get("properties", {}))  # type: ignore
            assert documented <= params, (
                f"{name}: Args 段幽灵参数 {sorted(documented - params)}")
            assert not (params - documented), (
                f"{name}: 参数 {sorted(params - documented)} 未入 Args 段")


# ─── 签名冻结 + 载荷守卫 ───────────────────────────────────────────────────────

class TestSignatureFreezeAndPayload:
    def test_batch23_signatures_unchanged(self):
        for name, expected in BATCH23_SIGNATURES.items():
            fn = _tool_fn(name)
            actual = str(inspect.signature(fn))
            assert actual == expected, (
                f"{name}: 签名漂移——描述批不碰 def 行\n  期望 {expected}\n"
                f"  实际 {actual}")

    def test_description_increment_within_120(self):
        for name, before in BATCH23_DESC_LEN_BEFORE.items():
            desc = _split_description(_docstring_of(name))
            delta = len(desc) - before
            assert delta <= 120, (
                f"{name}: description 增量 +{delta} > 120 chars（载荷守卫）")

    def test_batch_surface_max_within_450(self):
        lens = [len(_split_description(_docstring_of(n))) for n in BATCH23]
        assert max(lens) <= 450, (
            f"批 2/3 description max {max(lens)} > 450（批 1 实测口径）")

    def test_accountable_surface_median_within_200(self):
        """责任面（批 1+批 2+批 3 冻结 126 件）median ≤200（批 1 实测口径）。

        全量（含并发席位新工具）median/max 由 W5-A 门承担；本门只钉本席
        责任面，避免他轨在制工具起伏误伤（#228）。
        """
        names = list(_BATCH1) + list(BATCH23)
        lens = [len(_split_description(_docstring_of(n))) for n in names]
        med = statistics.median(lens)
        assert med <= 200, f"责任面 description median {med} > 200"


# ─── Z-10a：只读工具 Returns 键集运行时对拍（批 2 7 件+批 3 6 件）─────────────

def _returns_top_level_keys(doc: str) -> list[str]:
    """解析 docstring Returns 段首个顶层 {…} 的键名（深度感知，确定性）。"""
    m = re.search(r"^\s*Returns:\s*$", doc, flags=re.M)
    assert m, "Returns 段缺失（Z-10b 先行门管）"
    block = doc[m.end():]
    brace = block.find("{")
    if brace < 0:
        return []
    depth = 0
    end = -1
    for i, ch in enumerate(block[brace:], start=brace):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    inner = block[brace + 1: end]
    keys: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in inner + ",":
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        if ch == "," and depth == 0:
            part = "".join(current).strip()
            current = []
            token = re.match(r"(\w+)\s*(?:[:\[(]|$)", part)
            if token:
                keys.append(token.group(1))
        else:
            current.append(ch)
    return keys


class TestZ10aReturnsKeyRuntime:
    #: 转发型只读试点（tool → (service 模块, 函数, kwargs)）；全部本地确定性
    #: 通道（零 LLM 零网络零真机，#139 纪律）；批 2 ≥5 + 批 3 ≥5。
    PILOT_B2: typing.ClassVar[dict[str, tuple[str, str, dict]]] = {
        "bands_list": ("rfauto.service.bands_service", "bands_list", {}),
        "bands_spec_bounds": ("rfauto.service.bands_service",
                              "bands_spec_bounds", {"key": "gpp_n78"}),
        "db_status": ("rfauto.service.db_service", "db_status",
                      {"db_path": "__TMP__/w6c_probe.sqlite"}),
        "synthesize": ("rfauto.mcp_tools.synth", "synthesize",
                       {"z0_target": 50.0, "freq_ghz": 2.4,
                        "stackup": "rogers4350b_h0.508"}),
        "spur_search": ("rfauto.service.cascade_service",
                        "spur_search_report",
                        {"f_rf_hz": 2.4e9, "f_lo_hz": 1.8e9}),
        "msl_floor_life_query": ("rfauto.service.humidity_drift_service",
                                 "msl_floor_life_query", {"payload":
                                                          {"msl": "3"}}),
        "weave_style_info": ("rfauto.service.glass_weave_skew_service",
                             "weave_style_info", {"payload": None}),
    }

    PILOT_B3: typing.ClassVar[dict[str, tuple[str, str, dict]]] = {
        "error_hints_lookup": ("rfauto.service.error_hints_service",
                               "hint_for_message",
                               {"text": "OSError WinError 8"}),
        "list_template_specs": ("rfauto.service.template_spec_service",
                                "list_template_specs", {}),
        "list_calculators": ("rfauto.service.calculator_service",
                             "list_calculators",
                             {"include_experimental": True}),
        "emc_cispr_band_params": ("rfauto.service.emc_service",
                                  "cispr_band_params", {"band": "B"}),
        "emc_ground_spacing_check": ("rfauto.service.emc_service",
                                     "ground_spacing_check",
                                     {"spacing_m": 0.01, "f_mhz": 100.0}),
        "get_guidelines_for": ("rfauto.service.guidelines_service",
                               "get_guidelines_for", {"topic": "openems"}),
    }

    def _assert_subset(self, name: str, mod_name: str, fn_name: str,
                       kwargs: dict, tmp_path: Path) -> None:
        kwargs = {k: (str(tmp_path / Path(v).name)
                      if v == "__TMP__/w6c_probe.sqlite" else v)
                  for k, v in kwargs.items()}
        module = __import__(mod_name, fromlist=[fn_name])
        result = getattr(module, fn_name)(**kwargs)
        assert isinstance(result, dict) and result.get("ok"), (
            f"{name}: 试点调用未成功，对拍面失效")
        listed = _returns_top_level_keys(_docstring_of(name))
        assert listed, f"{name}: Returns 段未解析出顶层键"
        absent = [k for k in listed if k not in result]
        assert not absent, (
            f"{name}: docstring Returns 列举键 {absent} 不在实际返回键 "
            f"{sorted(result)} 中（Z-10a 单源锚失守）")

    @pytest.mark.parametrize("name", sorted(PILOT_B2))
    def test_batch2_returns_keys_subset_of_actual(self, name, tmp_path):
        mod_name, fn_name, kwargs = self.PILOT_B2[name]
        self._assert_subset(name, mod_name, fn_name, kwargs, tmp_path)

    @pytest.mark.parametrize("name", sorted(PILOT_B3))
    def test_batch3_returns_keys_subset_of_actual(self, name, tmp_path):
        mod_name, fn_name, kwargs = self.PILOT_B3[name]
        self._assert_subset(name, mod_name, fn_name, kwargs, tmp_path)
