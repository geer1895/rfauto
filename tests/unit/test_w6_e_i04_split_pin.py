"""W6-E I-04 test_hfss_window_driver 拆分恒等钉（Phase 6 批，2026-10-06）。

判据（ra_criteria SPECS §五 5.2 预声明，W9 拆分对拍口径）：
- collect 恒等：拆分后节点集与拆分前冻结清单 sorted 逐位一致
  （拆前实测 138 节点；冻结清单存证 runs/w6_phase6/w6e_i04_nodes_split_before.txt）；
- 纯搬运钉：主文件零本地 fake/helper def（#116 遮蔽治理）；fakes
  模块承载 _Fake 三件+_mmf+_load 与契约镜像 banner（SPECS §5.2 判据④）；
- 单例钉：主文件与 fakes 模块的驱动模块对象同一（_load 单例搬移后
  不得二次 exec——二次加载会让 monkeypatch 面分裂）。
"""

from __future__ import annotations

from pathlib import Path

from tests.unit import _hfss_window_driver_fakes as fh
from tests.unit import test_hfss_window_driver as main_mod

NL = chr(10)

_FILE = Path(main_mod.__file__)
_FAKES = Path(fh.__file__)

# 模块级 def/class 锚（col-0；测试函数体内同名局部 fake 不误伤）
_MODULE_LEVEL_MARKERS = tuple(
    NL + m for m in (
        "def _load(", "def _gate(", "def _synth_wilkinson_like(",
        "def _arr_rects_single_source(", "class _FakeObject:",
        "def _mmf(", "class _FakeModeler:", "class _FakeHfss:",
        "def _setup_h(", "def _patch_remote_pipeline(",
        "def _patch_remote_session(", "class _FakeProc:",
        "def _patch_registry_transport(", "def _stepped_s21(",
        "def _coupled_censored_sparams_csv(",
    )
)


_FROZEN_NODE_NAMES = (
    'test_all_extractors_require_measured_semantics_consistent',
    'test_apply_pads_creates_area_overlap',
    'test_assign_ports_matches_partition',
    'test_assign_seat_ports_wave_reuse',
    'test_audit_connectivity_orphan_detection',
    'test_audit_geometry_ports_and_floating',
    'test_audit_lumped_bridge_191',
    'test_branchline_layout_ring_and_ports',
    'test_build_seat_geometry_fake_executable_face',
    'test_builder_completion_faces',
    'test_bw3db_main_lobe_non_truncated_returns_width',
    'test_bw3db_main_lobe_selected_over_wider_edge_truncated_lobe',
    'test_cleanup_remote_grpcsrv_fingerprint_no_mutual_kill',
    'test_cleanup_remote_grpcsrv_no_match_and_failure',
    'test_cli_default_local_zero_registry_read',
    'test_cli_dry_run_end_to_end',
    'test_cli_help_and_list',
    'test_cli_remote_conflicts_and_errors',
    'test_cli_remote_routing',
    'test_cli_requires_seat_or_all',
    'test_convergence_record_two_states',
    'test_coupled_f_peak_extractor_declares_band_center_kind',
    'test_edge_touch_pads_semantics',
    'test_ensure_remote_project_dir_cmd_mkdir',
    'test_extract_metrics_bw3db_and_none',
    'test_extract_metrics_censored_structured_fields',
    'test_extract_metrics_first_pass_locators_honor_mask',
    'test_extract_metrics_mask_semantics',
    'test_extract_metrics_recovers_known_values',
    'test_f_peak_3db_center_plateau_stable_vs_argmax_drift',
    'test_g11_health_full_and_masked',
    'test_gate_values_frozen',
    'test_gysel_layout_single_source_and_loads',
    'test_implementation_notes_reach_verdict',
    'test_is_license_error_fingerprint_variants',
    'test_judge_diff_zero_gate_boundary_is_pass',
    'test_judge_metric_four_states',
    'test_judge_metric_le_window_and_no_window',
    'test_key_vs_info_gates',
    'test_ladder_pick_extraction_failed_not_usable',
    'test_ladder_pick_topped_and_saturation',
    'test_launch_order_matches_readme',
    'test_launch_remote_grpcsrv_missing_exe_and_ssh_down',
    'test_launch_remote_grpcsrv_per_port_vbs_and_task',
    'test_launch_remote_grpcsrv_port_busy_fail_closed',
    'test_launch_remote_grpcsrv_silent_vbs_semantics',
    'test_lesson1_band_symmetry_negative_pins',
    'test_lesson1_band_symmetry_runseat_fail_closed',
    'test_lesson1_band_symmetry_spec_integrity',
    'test_lesson2_weak_feature_downgrade_both_directions',
    'test_lesson3_valley_map_and_compare_patch2x2',
    'test_marchand_build_records_lumped_ports',
    'test_marchand_layout_mirror_semantics',
    'test_marchand_port_form_cli_guards',
    'test_marchand_port_form_dispatch_faces',
    'test_marchand_wave2mode_build_fake_records_modes2',
    'test_marchand_wave2mode_dry_end_to_end',
    'test_marchand_wave2mode_layout_and_audit',
    'test_oe_branchline_fallback_note_present',
    'test_oe_refs_branchline_touchstone',
    'test_oe_refs_closed_form_fallback_caps_agree_hfss',
    'test_oe_refs_coupled_line_wideband',
    'test_oe_refs_gysel_verdict_fields',
    'test_oe_refs_marchand_constants',
    'test_oe_refs_wilkinson_from_real_artifact',
    'test_oe_resolve_paths_carry_notes_and_censored',
    'test_open_remote_hfss_bootstrap_fail_closed',
    'test_open_remote_hfss_grpc_port_override',
    'test_open_remote_hfss_switches_active_at_construction',
    'test_parse_verdict_lines_refuses_dryrun_prefix',
    'test_parse_verdict_lines_rejects_legacy_prefixless_fake_wall',
    'test_partition_waves_shapes',
    'test_patch_array_2x2_mirror_semantics',
    'test_patch_array_layouts_consume_single_source',
    'test_read_touchstone_rejects_im_zero_synthetic',
    'test_run_all_default_serial_zero_change',
    'test_run_all_exit_code_semantics',
    'test_run_all_parallel_launch_fail_fail_closed',
    'test_run_all_parallel_local_has_no_license_gate',
    'test_run_all_parallel_local_residue_preflight',
    'test_run_all_parallel_remote_license_gate_blocks_wave',
    'test_run_all_parallel_remote_ports_launch_cleanup',
    'test_run_all_parallel_two_waves_dry_mock',
    'test_run_all_parallel_verdict_missing_fail_closed',
    'test_run_all_remote_parallel_capped_by_registry',
    'test_run_all_remote_parallel_registry_unreadable_no_cap',
    'test_run_seat_all_extraction_failed_is_fail_closed',
    'test_run_seat_ansysedt_residue_blocks',
    'test_run_seat_budget_overtime_marks_partial',
    'test_run_seat_dry_all_seats_produce_verdicts[branchline]',
    'test_run_seat_dry_all_seats_produce_verdicts[coupled_line]',
    'test_run_seat_dry_all_seats_produce_verdicts[gysel]',
    'test_run_seat_dry_all_seats_produce_verdicts[marchand_balun]',
    'test_run_seat_dry_all_seats_produce_verdicts[patch_array_1x4]',
    'test_run_seat_dry_all_seats_produce_verdicts[patch_array_2x2]',
    'test_run_seat_dry_all_seats_produce_verdicts[stepped_impedance]',
    'test_run_seat_dry_all_seats_produce_verdicts[wilkinson]',
    'test_run_seat_dry_bw_detail_lands_in_verdict',
    'test_run_seat_dry_censored_structured_both_sides',
    'test_run_seat_dry_end_to_end',
    'test_run_seat_dry_progress_lines_carry_dryrun_prefix',
    'test_run_seat_fail_closed_connect_error',
    'test_run_seat_grpc_port_forwarded_and_recorded',
    'test_run_seat_license_error_maps_to_skip',
    'test_run_seat_local_and_dry_never_preflight',
    'test_run_seat_partial_extraction_failed_keeps_usable_rung',
    'test_run_seat_remote_export_fetch_fail_is_fail',
    'test_run_seat_remote_preflight_fail_skips',
    'test_run_seat_remote_preflight_pass_records_envelope',
    'test_run_seat_residue_check_gate',
    'test_run_seat_skeleton_rearm_fail_closed',
    'test_seat_argv_carries_port_form',
    'test_seat_argv_wiring',
    'test_seat_frozen_values_vs_criteria',
    'test_seat_layouts_audit_pass',
    'test_seat_spec_has_all_criteria_sections[branchline]',
    'test_seat_spec_has_all_criteria_sections[coupled_line]',
    'test_seat_spec_has_all_criteria_sections[gysel]',
    'test_seat_spec_has_all_criteria_sections[marchand_balun]',
    'test_seat_spec_has_all_criteria_sections[patch_array_1x4]',
    'test_seat_spec_has_all_criteria_sections[patch_array_2x2]',
    'test_seat_spec_has_all_criteria_sections[stepped_impedance]',
    'test_seat_spec_has_all_criteria_sections[wilkinson]',
    'test_solve_timeout_default_3600_when_env_unset',
    'test_solve_timeout_env_invalid_falls_back_to_3600[   ]',
    'test_solve_timeout_env_invalid_falls_back_to_3600[-1]',
    'test_solve_timeout_env_invalid_falls_back_to_3600[0]',
    'test_solve_timeout_env_invalid_falls_back_to_3600[]',
    'test_solve_timeout_env_invalid_falls_back_to_3600[abc]',
    'test_solve_timeout_env_invalid_falls_back_to_3600[inf]',
    'test_solve_timeout_env_invalid_falls_back_to_3600[nan]',
    'test_solve_timeout_env_override_7200',
    'test_spec_notes_present',
    'test_synthetic_s_finite_and_disagree_moves_valley',
    'test_total_verdict_cap_and_undecidable',
    'test_wave_port_sheet_bbox_all_seats',
    'test_wilkinson_layout_matches_geometry_spec_single_source',
    'test_x_ref_windows_frozen',
)

class TestCollectIdentity:
    def test_collect_count_equals_frozen_138(self):
        """collect 数恒等：本文件节点数=拆分前实测 138 且名单逐位一致。"""
        import subprocess
        import sys

        r = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/unit/test_hfss_window_driver.py", "--collect-only", "-q"],
            capture_output=True, text=True, timeout=300)
        ids = [ln.split("::", 1)[1] for ln in r.stdout.splitlines()
               if ln.startswith("tests/unit/test_hfss_window_driver.py::")]
        assert len(ids) == 138
        assert sorted(ids) == sorted(_FROZEN_NODE_NAMES)

    def test_frozen_names_all_have_defs_in_main(self):
        """冻结清单逐名在主文件源码有 def（防静默改名/丢测试；参数化名取
        方括号前段）。"""
        src = _FILE.read_text(encoding="utf-8")
        missing = []
        for n in _FROZEN_NODE_NAMES:
            base = n.split("[")[0]
            if f"def {base}(" not in src:
                missing.append(n)
        assert missing == []


class TestPureMovePins:
    def test_main_has_no_local_fake_defs(self):
        """#116：主文件模块级零本地 fake/patch/助手 def（全部改引 fakes；
        测试函数体内的同名局部 mock 面不属搬运面，col-0 锚不误伤）。"""
        src = _FILE.read_text(encoding="utf-8")
        for marker in _MODULE_LEVEL_MARKERS:
            assert marker not in src, marker.strip()

    def test_fakes_has_moved_defs_and_contract_banner(self):
        """fakes 承载全部搬入件；_FakeHfss 契约镜像 banner 随迁不丢。"""
        src = _FAKES.read_text(encoding="utf-8")
        for marker in _MODULE_LEVEL_MARKERS:
            assert marker in src, marker.strip()
        assert "builder 可执行面（_FakeHfss 契约镜像，零真机）" in src

    def test_verbatim_spans_hit(self):
        """verbatim 子串校验（SPECS §5.2 判据②代表锚：逐字节命中）。"""
        src = _FAKES.read_text(encoding="utf-8")
        unite_block = NL.join([
            "    def unite(self, names):",
            "        self.unite_calls.append(list(names))",
            "        keep = names[0]",
            "",
        ])
        assert unite_block in src          # #310 保首名（逐字节）
        step_block = NL.join([
            "def _stepped_s21(fg: np.ndarray, segments: list[tuple[float, float, float]],",
            "                 floor_db: float = -6.0) -> np.ndarray:",
        ])
        assert step_block in src
        assert ("FREQ = np.linspace(2.0e9, 3.0e9, 401)" + NL) in src

    def test_driver_module_single_instance(self):
        """单例钉：主文件 mod 与 fakes.mod 同一对象（_load 搬移零二次 exec）。"""
        assert main_mod.mod is fh.mod
        assert main_mod.FREQ is fh.FREQ

    def test_pytest_does_not_collect_fakes_module(self):
        """下划线前缀=非收集目标（_hfss_window_driver_fakes 零测试节点）。"""
        import subprocess
        import sys

        r = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/unit/_hfss_window_driver_fakes.py", "--collect-only", "-q"],
            capture_output=True, text=True, timeout=300)
        assert "no tests collected" in (r.stdout + r.stderr)
