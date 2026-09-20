"""E7a DRC/DFM gate 单元测试。"""

from __future__ import annotations

import json

import pytest

from rfauto.adapters.kicad_drc import (
    C_MM_GHZ,
    DEFAULT_RF_RULES,
    RF_RULE_GROUND_STITCH_INTEGRITY,
    RF_RULE_REFERENCE_PLANE_SLOT,
    RF_RULE_TRACE_CLEARANCE,
    RF_RULE_VIA_STITCH_PITCH,
    Conductor,
    DRCResult,
    DRCRule,
    DRCViolation,
    PlaneSlot,
    RFDRCConfig,
    RFDRCResult,
    RFGeometry,
    Via,
    check_ground_stitch_integrity,
    check_reference_plane_slot,
    check_trace_clearance,
    check_via_stitch_pitch,
    generate_drc_report,
    guided_wavelength_mm,
    max_via_pitch_mm,
    merge_drc_results,
    run_drc_kicad,
    run_rf_drc,
)


class TestDRCRule:
    def test_rule_creation(self):
        rule = DRCRule(
            name="min_width",
            rule_type="min_width",
            value=0.1,
            unit="mm",
        )
        assert rule.name == "min_width"
        assert rule.value == 0.1

    def test_to_dict(self):
        rule = DRCRule(name="test", rule_type="min_width", value=0.1)
        d = rule.to_dict()
        assert d["name"] == "test"
        assert d["value"] == 0.1


class TestDRCViolation:
    def test_violation_creation(self):
        violation = DRCViolation(
            rule_name="min_width",
            severity="error",
            message="线宽太小",
            actual_value=0.05,
            expected_value=0.1,
        )
        assert violation.severity == "error"
        assert violation.actual_value == 0.05

    def test_to_dict(self):
        violation = DRCViolation(
            rule_name="test",
            severity="warning",
            message="test",
        )
        d = violation.to_dict()
        assert d["severity"] == "warning"


class TestDRCResult:
    def test_result_creation(self):
        result = DRCResult(
            pcb_file="test.kicad_pcb",
            passed=True,
            violations=[],
            rules_checked=DEFAULT_RF_RULES,
        )
        assert result.passed
        assert result.n_errors == 0

    def test_to_dict(self):
        result = DRCResult(
            pcb_file="test.kicad_pcb",
            passed=False,
            violations=[DRCViolation(
                rule_name="test",
                severity="error",
                message="test",
            )],
            rules_checked=DEFAULT_RF_RULES,
            n_errors=1,
        )
        d = result.to_dict()
        assert not d["passed"]
        assert d["n_errors"] == 1


class TestDefaultRules:
    def test_default_rules_count(self):
        assert len(DEFAULT_RF_RULES) == 3

    def test_default_rules_types(self):
        types = {r.rule_type for r in DEFAULT_RF_RULES}
        assert "min_width" in types
        assert "min_spacing" in types
        assert "impedance_tolerance" in types


class TestRunDRCKiCad:
    def test_nonexistent_file(self):
        result = run_drc_kicad("/nonexistent/file.kicad_pcb")
        assert not result.passed
        assert result.n_errors > 0

    def test_with_custom_rules(self):
        rules = [DRCRule(name="test", rule_type="min_width", value=0.1)]
        result = run_drc_kicad("/nonexistent/file.kicad_pcb", rules=rules)
        assert not result.passed


class TestGenerateDRCReport:
    def test_pass_report(self, tmp_path):
        result = DRCResult(
            pcb_file="test.kicad_pcb",
            passed=True,
            violations=[],
            rules_checked=DEFAULT_RF_RULES,
        )
        report = generate_drc_report(result, tmp_path / "report.md")
        assert "PASS" in report
        assert "No violations found" in report

    def test_fail_report(self, tmp_path):
        result = DRCResult(
            pcb_file="test.kicad_pcb",
            passed=False,
            violations=[DRCViolation(
                rule_name="min_width",
                severity="error",
                message="线宽太小",
                actual_value=0.05,
                expected_value=0.1,
            )],
            rules_checked=DEFAULT_RF_RULES,
            n_errors=1,
        )
        report = generate_drc_report(result)
        assert "FAIL" in report
        assert "线宽太小" in report



# ─── RF-DRC（§10.2 B4 几何自动验证扩充） ──────────────────────────────────────

def _config(**overrides):
    base = {"freq_ghz": 1.0, "eps_eff": 1.0}
    base.update(overrides)
    return RFDRCConfig(**base)


def _rf_trace(net="RF", y=0.0, x0=0.0, x1=10.0, width=0.2, sensitive=True):
    return Conductor(net=net, points=[(x0, y), (x1, y)], width_mm=width, sensitive=sensitive)


class TestGuidedWavelength:
    def test_formula_value(self):
        assert guided_wavelength_mm(1.0, 4.0) == pytest.approx(C_MM_GHZ / 2.0)
        assert guided_wavelength_mm(1.0, 4.0) == pytest.approx(149.896229, abs=1e-6)

    def test_inverse_frequency_scaling(self):
        assert guided_wavelength_mm(2.0, 4.0) == pytest.approx(guided_wavelength_mm(1.0, 4.0) / 2.0)

    def test_sqrt_eps_scaling(self):
        assert guided_wavelength_mm(1.0, 9.0) == pytest.approx(guided_wavelength_mm(1.0, 1.0) / 3.0)

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_invalid_frequency_raises(self, bad):
        with pytest.raises(ValueError):
            guided_wavelength_mm(bad, 4.0)

    @pytest.mark.parametrize("bad", [0.0, 0.5, -2.0])
    def test_invalid_eps_eff_raises(self, bad):
        with pytest.raises(ValueError):
            guided_wavelength_mm(1.0, bad)


class TestViaStitchPitch:
    def test_within_limit_passes(self):
        cfg = _config(eps_eff=4.0)
        assert check_via_stitch_pitch([Via(0.0, 0.0), Via(10.0, 0.0)], cfg) == []

    def test_exceeds_limit_flags(self):
        cfg = _config(eps_eff=4.0)
        out = check_via_stitch_pitch([Via(0.0, 0.0), Via(20.0, 0.0)], cfg)
        assert len(out) == 1
        violation = out[0]
        assert violation.rule_name == RF_RULE_VIA_STITCH_PITCH
        assert violation.severity == "error"
        assert violation.actual_value == pytest.approx(20.0)
        assert violation.expected_value == pytest.approx(max_via_pitch_mm(cfg))
        assert violation.location == pytest.approx([10.0, 0.0])
        assert "pitch" in violation.message

    def test_boundary_exact_pitch_passes(self):
        cfg = _config(eps_eff=4.0)
        pitch = max_via_pitch_mm(cfg)
        assert check_via_stitch_pitch([Via(0.0, 0.0), Via(pitch, 0.0)], cfg) == []

    def test_boundary_just_over_pitch_fails(self):
        cfg = _config(eps_eff=4.0)
        pitch = max_via_pitch_mm(cfg)
        assert len(check_via_stitch_pitch([Via(0.0, 0.0), Via(pitch + 1e-6, 0.0)], cfg)) == 1

    def test_override_threshold_configurable(self):
        cfg = _config(eps_eff=4.0, via_pitch_override_mm=5.0)
        assert max_via_pitch_mm(cfg) == pytest.approx(5.0)
        assert check_via_stitch_pitch([Via(0.0, 0.0), Via(5.0, 0.0)], cfg) == []
        out = check_via_stitch_pitch([Via(0.0, 0.0), Via(5.5, 0.0)], cfg)
        assert len(out) == 1
        assert out[0].expected_value == pytest.approx(5.0)

    def test_non_ground_vias_ignored(self):
        cfg = _config(eps_eff=4.0)
        vias = [Via(0.0, 0.0, net="RF"), Via(100.0, 0.0, net="RF")]
        assert check_via_stitch_pitch(vias, cfg) == []

    def test_eps_eff_tightens_limit(self):
        wide = max_via_pitch_mm(_config(eps_eff=1.0))
        tight = max_via_pitch_mm(_config(eps_eff=9.0))
        assert tight == pytest.approx(wide / 3.0)


class TestGroundStitchIntegrity:
    def test_full_coverage_passes(self):
        cfg = _config(stitch_band_mm=2.0, stitch_gap_max_mm=1.0)
        vias = [Via(x, y) for x in range(0, 11, 2) for y in (1.0, -1.0)]
        assert check_ground_stitch_integrity([_rf_trace()], vias, cfg) == []

    def test_gap_detected(self):
        cfg = _config(stitch_band_mm=1.25, stitch_gap_max_mm=2.0)
        vias = [Via(2.0, 1.0), Via(8.0, 1.0), Via(2.0, -1.0), Via(8.0, -1.0)]
        out = check_ground_stitch_integrity([_rf_trace()], vias, cfg)
        assert len(out) == 2
        for violation in out:
            assert violation.rule_name == RF_RULE_GROUND_STITCH_INTEGRITY
            assert violation.severity == "error"
            assert violation.actual_value == pytest.approx(4.5)
            assert "ground-stitch break" in violation.message

    def test_gap_boundary_equal_threshold_passes(self):
        cfg = _config(stitch_band_mm=1.25, stitch_gap_max_mm=4.5)
        vias = [Via(2.0, 1.0), Via(8.0, 1.0), Via(2.0, -1.0), Via(8.0, -1.0)]
        assert check_ground_stitch_integrity([_rf_trace()], vias, cfg) == []

    def test_gap_boundary_just_over_threshold_fails(self):
        cfg = _config(stitch_band_mm=1.25, stitch_gap_max_mm=4.49)
        vias = [Via(2.0, 1.0), Via(8.0, 1.0), Via(2.0, -1.0), Via(8.0, -1.0)]
        assert len(check_ground_stitch_integrity([_rf_trace()], vias, cfg)) == 2

    def test_missing_side_detected(self):
        cfg = _config(stitch_band_mm=2.0, stitch_gap_max_mm=1.0)
        vias = [Via(x, 1.0) for x in range(0, 11, 2)]
        out = check_ground_stitch_integrity([_rf_trace()], vias, cfg)
        assert len(out) == 1
        assert "right" in out[0].message
        assert out[0].actual_value == pytest.approx(0.0)

    def test_min_vias_per_side_configurable(self):
        cfg = _config(stitch_band_mm=1.25, stitch_gap_max_mm=100.0, stitch_min_vias_per_side=2)
        vias = [Via(2.0, 1.0), Via(2.0, -1.0)]
        out = check_ground_stitch_integrity([_rf_trace()], vias, cfg)
        assert len(out) == 2
        assert all("stitching vias" in violation.message for violation in out)

    def test_non_sensitive_trace_ignored(self):
        cfg = _config()
        assert check_ground_stitch_integrity([_rf_trace(sensitive=False)], [], cfg) == []

    def test_invalid_single_point_trace_raises(self):
        bad = Conductor(net="RF", points=[(0.0, 0.0)], sensitive=True)
        with pytest.raises(ValueError):
            check_ground_stitch_integrity([bad], [], _config())


class TestTraceClearance:
    def test_too_close_to_ground_flags(self):
        cfg = _config(min_gap_to_ground_mm=0.2)
        ground = Conductor(net="GND", points=[(0.0, 0.3), (10.0, 0.3)], width_mm=0.2)
        out = check_trace_clearance([_rf_trace(), ground], [], cfg)
        assert len(out) == 1
        assert out[0].rule_name == RF_RULE_TRACE_CLEARANCE
        assert out[0].severity == "error"
        assert out[0].actual_value == pytest.approx(0.1)

    def test_clear_of_ground_passes(self):
        cfg = _config(min_gap_to_ground_mm=0.2)
        ground = Conductor(net="GND", points=[(0.0, 0.6), (10.0, 0.6)], width_mm=0.2)
        assert check_trace_clearance([_rf_trace(), ground], [], cfg) == []

    def test_other_net_clearance(self):
        cfg = _config(min_gap_to_other_mm=0.2)
        other = Conductor(net="VCC", points=[(0.0, 0.3), (10.0, 0.3)], width_mm=0.2)
        out = check_trace_clearance([_rf_trace(), other], [], cfg)
        assert len(out) == 1
        assert "VCC" in out[0].message

    def test_same_net_ignored(self):
        cfg = _config(min_gap_to_ground_mm=0.5, min_gap_to_other_mm=0.5)
        same = Conductor(net="RF", points=[(0.0, 0.05), (10.0, 0.05)], width_mm=0.2)
        assert check_trace_clearance([_rf_trace(), same], [], cfg) == []

    def test_threshold_configurable(self):
        ground = Conductor(net="GND", points=[(0.0, 0.3), (10.0, 0.3)], width_mm=0.2)
        assert check_trace_clearance([_rf_trace(), ground], [], _config(min_gap_to_ground_mm=0.05)) == []
        assert len(check_trace_clearance([_rf_trace(), ground], [], _config(min_gap_to_ground_mm=0.2))) == 1

    def test_ground_via_clearance(self):
        cfg = _config(min_gap_to_ground_mm=0.2)
        out = check_trace_clearance([_rf_trace()], [Via(5.0, 0.3, net="GND", diameter_mm=0.3)], cfg)
        assert len(out) == 1
        assert out[0].actual_value == pytest.approx(0.05)


class TestReferencePlaneSlot:
    def test_crossing_detected(self):
        slot = PlaneSlot(x_min=4.0, y_min=-1.0, x_max=6.0, y_max=1.0)
        out = check_reference_plane_slot([_rf_trace()], [slot], _config())
        assert len(out) == 1
        assert out[0].rule_name == RF_RULE_REFERENCE_PLANE_SLOT
        assert out[0].severity == "error"
        assert out[0].location == pytest.approx([5.0, 0.0])

    def test_not_crossing(self):
        slot = PlaneSlot(x_min=4.0, y_min=2.0, x_max=6.0, y_max=3.0)
        assert check_reference_plane_slot([_rf_trace()], [slot], _config()) == []

    def test_invalid_slot_raises(self):
        bad = PlaneSlot(x_min=4.0, y_min=1.0, x_max=4.0, y_max=2.0)
        with pytest.raises(ValueError):
            check_reference_plane_slot([_rf_trace()], [bad], _config())

    def test_disabled_by_config(self):
        cfg = _config(check_reference_plane_slot=False)
        slot = PlaneSlot(x_min=4.0, y_min=-1.0, x_max=6.0, y_max=1.0)
        result = run_rf_drc(RFGeometry(conductors=[_rf_trace()], slots=[slot]), cfg)
        assert all(v.rule_name != RF_RULE_REFERENCE_PLANE_SLOT for v in result.violations)


class TestRunRFDRCAndMerge:
    def test_aggregates_rules_and_lambda(self):
        cfg = _config(eps_eff=4.0)
        geom = RFGeometry(
            conductors=[_rf_trace()],
            vias=[Via(x, y) for x in range(0, 11, 2) for y in (1.0, -1.0)],
        )
        result = run_rf_drc(geom, cfg)
        assert isinstance(result, RFDRCResult)
        assert result.lambda_g_mm == pytest.approx(149.896229, abs=1e-6)
        assert {r.rule_type for r in result.rules_checked} == {
            RF_RULE_VIA_STITCH_PITCH,
            RF_RULE_GROUND_STITCH_INTEGRITY,
            RF_RULE_TRACE_CLEARANCE,
            RF_RULE_REFERENCE_PLANE_SLOT,
        }
        assert "violations" in result.to_dict()

    def test_invalid_config_raises(self):
        with pytest.raises(ValueError):
            run_rf_drc(RFGeometry(), RFDRCConfig(freq_ghz=0.0))

    def test_invalid_geometry_type_raises(self):
        with pytest.raises(TypeError):
            run_rf_drc("not-geometry")

    def test_deterministic(self):
        cfg = _config(eps_eff=4.0, stitch_band_mm=1.25)
        geom = RFGeometry(
            conductors=[_rf_trace()],
            vias=[Via(2.0, 1.0), Via(8.0, 1.0), Via(2.0, -1.0), Via(8.0, -1.0)],
            slots=[PlaneSlot(x_min=4.0, y_min=-1.0, x_max=6.0, y_max=1.0)],
        )
        first = run_rf_drc(geom, cfg).to_dict()
        second = run_rf_drc(geom, cfg).to_dict()
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_merge_with_conventional_drc(self):
        base = DRCResult(pcb_file="t.kicad_pcb", passed=True, violations=[], rules_checked=DEFAULT_RF_RULES)
        rf = run_rf_drc(RFGeometry(vias=[Via(0.0, 0.0), Via(50.0, 0.0)]), _config(eps_eff=4.0))
        assert rf.n_errors >= 1
        merged = merge_drc_results(base, rf)
        assert merged.passed is False
        assert merged.n_errors == base.n_errors + rf.n_errors
        assert len(merged.rules_checked) == len(DEFAULT_RF_RULES) + len(rf.rules_checked)
        assert len(merged.violations) == len(rf.violations)

    def test_report_contains_rf_section(self):
        base = DRCResult(pcb_file="t.kicad_pcb", passed=True, violations=[], rules_checked=DEFAULT_RF_RULES)
        rf = run_rf_drc(RFGeometry(vias=[Via(0.0, 0.0), Via(50.0, 0.0)]), _config(eps_eff=4.0))
        report = generate_drc_report(base, rf_result=rf)
        assert "## RF-DRC" in report
        assert "lambda_g" in report
        assert RF_RULE_VIA_STITCH_PITCH in report
        assert "## RF-DRC" not in generate_drc_report(base)

    def test_report_writes_rf_section_to_file(self, tmp_path):
        base = DRCResult(pcb_file="t.kicad_pcb", passed=True, violations=[], rules_checked=DEFAULT_RF_RULES)
        rf = run_rf_drc(RFGeometry(), _config())
        out_path = tmp_path / "rf_report.md"
        report = generate_drc_report(base, out_path, rf_result=rf)
        assert out_path.read_text(encoding="utf-8") == report
        assert "## RF-DRC" in report
