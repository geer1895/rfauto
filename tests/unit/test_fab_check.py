"""DP-7 P1：fab 剖面 schema 钉 + 纯几何 DFM 门正反例分类（零仿真）。

判据预声明：runs/df6_dp7fab/criteria.md C1/C2。
- C1 字段一致性钉：两个剖面 YAML 必填字段 schema 校验 + 枚举值域 +
  逐字段来源注记必须带核对状态标记（verified-web 或
  registered-pending-review——不虚构核对状态）。
- C2 合成几何正反例（细线/窄缝/未知板材/缺铜厚档……）100% 分类正确。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rfauto.core.fab_check import (
    FabProfileError,
    best_effort_dfm_for_design,
    check_board_thickness,
    check_copper,
    check_drill,
    check_gaps,
    check_geometry,
    check_material,
    check_surface_finish,
    check_trace_widths,
    load_profile,
)

PROFILES_DIR = Path(__file__).resolve().parents[2] / "knowledge" / "fab_profiles"
PROFILE_NAMES = ("jlcpcb", "huaqiu")

#: 表面处理枚举全域（新档位加入剖面时必须同步扩此处值域钉）
SURFACE_FINISH_UNIVERSE = {
    "hasl_lead", "hasl_leadfree", "enig", "osp", "electrolytic_ni_au",
}
#: 核对状态标记全域（来源注记二选一，禁止无标记裸数值）
SOURCE_MARKERS = ("verified-web", "registered-pending-review")


# ── C1 字段一致性钉 ──────────────────────────────────────────

@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_profile_schema_required_fields(name: str) -> None:
    prof = load_profile(name, profiles_dir=PROFILES_DIR)
    assert prof.name == name
    assert prof.profile_version
    assert prof.source_url.startswith("https://")
    assert prof.retrieved_date == "2026-09-24"
    assert prof.trace_tol_pct == pytest.approx(20.0)
    assert prof.impedance_tol_pct == pytest.approx(10.0)
    assert prof.copper_rules and 1.0 in prof.copper_rules
    for rule in prof.copper_rules.values():
        assert rule.min_trace_mm > 0.0
        assert rule.min_gap_mm > 0.0
    assert prof.board_thickness_min_mm < prof.board_thickness_max_mm
    assert prof.min_drill_mm > 0.0
    assert prof.min_via_pad_mm > prof.min_drill_mm
    assert 0.0 < prof.min_via_annular_ring_mm < prof.min_drill_mm
    assert prof.min_annular_ring_mm > 0.0
    assert prof.min_solder_mask_dam_mm > 0.0
    assert prof.surface_finishes
    assert prof.supported_materials


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_profile_raw_source_annotations(name: str) -> None:
    """逐字段来源注记必须带核对状态标记（防虚构 verified）。"""
    raw = yaml.safe_load(
        (PROFILES_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    # 区块级来源：trace/impedance/board_thickness 必须有 source_note
    for section in ("trace", "impedance", "board_thickness"):
        note = str(raw[section].get("source_note", ""))
        assert any(m in note for m in SOURCE_MARKERS), (
            f"{name}.{section}.source_note 缺核对状态标记: {note!r}")
    # 铜厚档逐档 source_note
    for key, entry in raw["copper_rules"].items():
        note = str(entry.get("source_note", ""))
        assert any(m in note for m in SOURCE_MARKERS), (
            f"{name}.copper_rules[{key}].source_note 缺标记: {note!r}")
    # 板材逐 token source_note
    for entry in raw["supported_materials"]:
        note = str(entry.get("source_note", ""))
        assert any(m in note for m in SOURCE_MARKERS), (
            f"{name}.supported_materials[{entry.get('token')}] 缺标记: {note!r}")
    # 孔径/阻焊桥/表面处理注记
    for key in ("drill_source_note", "solder_mask_dam_note",
                "surface_finishes_note", "materials_note"):
        note = str(raw.get(key, ""))
        assert any(m in note for m in SOURCE_MARKERS), (
            f"{name}.{key} 缺标记: {note!r}")


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_profile_enum_domains(name: str) -> None:
    prof = load_profile(name, profiles_dir=PROFILES_DIR)
    assert set(prof.surface_finishes) <= SURFACE_FINISH_UNIVERSE
    assert len(set(prof.surface_finishes)) == len(prof.surface_finishes)
    assert len(set(prof.supported_materials)) == len(prof.supported_materials)


def test_jlcpcb_copper_rules_match_capability_page() -> None:
    """JLCPCB 1oz/2oz 档=能力页实查值（verified-web 钉）。"""
    prof = load_profile("jlcpcb", profiles_dir=PROFILES_DIR)
    assert prof.copper_rules[1.0].min_trace_mm == pytest.approx(0.10)
    assert prof.copper_rules[1.0].min_gap_mm == pytest.approx(0.10)
    assert prof.copper_rules[2.0].min_trace_mm == pytest.approx(0.16)
    assert prof.min_drill_mm == pytest.approx(0.15)
    assert prof.min_via_annular_ring_mm == pytest.approx(0.05)
    assert prof.board_thickness_min_mm == pytest.approx(0.4)
    assert prof.board_thickness_max_mm == pytest.approx(4.5)


def test_huaqiu_inner_layer_rows_match_capability_page() -> None:
    """华秋 1oz 档=官方页内层 3.0/3.0mil verified + 外层取严登记值。"""
    prof = load_profile("huaqiu", profiles_dir=PROFILES_DIR)
    assert prof.copper_rules[1.0].min_trace_mm == pytest.approx(0.0889)
    assert prof.copper_rules[0.5].min_trace_mm == pytest.approx(0.0635)
    assert prof.copper_rules[0.5].min_gap_mm == pytest.approx(0.0762)
    assert prof.impedance_tol_pct == pytest.approx(10.0)


# ── schema 负例（FabProfileError 带字段名）────────────────────

def _write_profile(tmp_path: Path, overrides: dict) -> Path:
    base = yaml.safe_load(
        (PROFILES_DIR / "jlcpcb.yaml").read_text(encoding="utf-8"))
    for key, value in overrides.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump(base, allow_unicode=True),
                    encoding="utf-8")
    return path


def test_schema_missing_required_field_raises(tmp_path: Path) -> None:
    path = _write_profile(tmp_path, {"min_drill_mm": None})
    with pytest.raises(FabProfileError, match="min_drill_mm"):
        load_profile(path)


def test_schema_bad_copper_key_raises(tmp_path: Path) -> None:
    path = _write_profile(tmp_path, {"copper_rules": {"abc": {
        "min_trace_mm": 0.1, "min_gap_mm": 0.1}}})
    with pytest.raises(FabProfileError, match="copper_rules"):
        load_profile(path)


def test_schema_nonpositive_tolerance_raises(tmp_path: Path) -> None:
    path = _write_profile(tmp_path, {"trace": {
        "tolerance_pct": -5.0, "source_note": "x"}})
    with pytest.raises(FabProfileError, match="tolerance_pct"):
        load_profile(path)


def test_schema_missing_profile_raises() -> None:
    with pytest.raises(FabProfileError, match="不存在"):
        load_profile("nonexistent-fab", profiles_dir=PROFILES_DIR)


# ── C2 合成几何正反例（100% 分类正确）────────────────────────

JLC = load_profile("jlcpcb", profiles_dir=PROFILES_DIR)


def test_positive_mline_nominal_geometry_passes() -> None:
    """正例：mline 名义 w=1.113/cpw 缝 0.2/rogers4350b/1oz 全部通过。"""
    report = check_geometry(
        JLC,
        traces_mm=[1.113, 1.113],
        gaps_mm=[0.2],
        copper_oz=1.0,
        material="rogers4350b_h0.508",
    )
    assert report.ok, report.violations
    assert report.violations == []


def test_negative_thin_trace_triggers_trace_below_min() -> None:
    """细线：0.12mm×(1−20%)=0.096 < 0.10 → TRACE_BELOW_MIN。"""
    violations = check_trace_widths([0.12], JLC, copper_oz=1.0)
    assert len(violations) == 1
    assert violations[0]["code"] == "TRACE_BELOW_MIN"
    assert violations[0]["limit"] == pytest.approx(0.10)
    # 同侧邻点不触发（0.13×0.8=0.104 ≥ 0.10）——分类边界正确
    assert check_trace_widths([0.13], JLC, copper_oz=1.0) == []


def test_negative_tolerance_shrinks_margin() -> None:
    """线宽下限判据吃容差：1.0mm 名义在 tol=95% 下触红（0.05 < 0.10）。"""
    assert check_trace_widths([1.0], JLC, copper_oz=1.0,
                              trace_tol_pct=95.0)[0]["code"] == "TRACE_BELOW_MIN"
    assert check_trace_widths([1.0], JLC, copper_oz=1.0,
                              trace_tol_pct=20.0) == []


def test_negative_narrow_gap_triggers_gap_below_min() -> None:
    """窄缝：0.09 < min_gap 0.10 → GAP_BELOW_MIN（无容差折扣）。"""
    violations = check_gaps([0.09], JLC, copper_oz=1.0)
    assert len(violations) == 1
    assert violations[0]["code"] == "GAP_BELOW_MIN"


def test_negative_unknown_material_triggers_material_unsupported() -> None:
    violations = check_material("ro9999_h0.5", JLC)
    assert len(violations) == 1
    assert violations[0]["code"] == "MATERIAL_UNSUPPORTED"
    # 前缀匹配正例（materials.yaml 键形态）
    assert check_material("rogers4350b_h0.508", JLC) == []
    assert check_material("fr4_h1.6", JLC) == []


def test_negative_missing_copper_weight_triggers_copper_unsupported() -> None:
    """缺铜厚档：3.0oz 不在 JLC 档位（有 2.5/3.5 无 3.0）→ COPPER_UNSUPPORTED。"""
    violations = check_copper(3.0, JLC)
    assert len(violations) == 1
    assert violations[0]["code"] == "COPPER_UNSUPPORTED"
    # 缺档时线宽检查不误报细线（转报缺档本身）
    violations = check_trace_widths([1.113], JLC, copper_oz=3.0)
    assert [v["code"] for v in violations] == ["COPPER_UNSUPPORTED"]


def test_negative_drill_and_annular_ring() -> None:
    violations = check_drill([0.10], [0.19], JLC)
    codes = {v["code"] for v in violations}
    assert codes == {"DRILL_BELOW_MIN", "VIA_ANNULAR_RING_BELOW_MIN"}
    # 环宽恰在下限（0.20−0.10)/2=0.05：严格 < 比较，只报孔径违规
    violations = check_drill([0.10], [0.20], JLC)
    assert {v["code"] for v in violations} == {"DRILL_BELOW_MIN"}
    # 合规过孔（0.15 孔/0.25 盘 → 环宽 0.05）通过
    assert check_drill([0.15], [0.25], JLC) == []


def test_negative_board_thickness_and_surface_finish() -> None:
    assert check_board_thickness(5.0, JLC)[0]["code"] == \
        "BOARD_THICKNESS_OUT_OF_RANGE"
    assert check_board_thickness(1.6, JLC) == []
    assert check_surface_finish("enepeg", JLC)[0]["code"] == \
        "SURFACE_FINISH_UNSUPPORTED"
    assert check_surface_finish("ENIG", JLC) == []  # 大小写归一


def test_classification_100pct_over_case_matrix() -> None:
    """合成例矩阵逐例精确断言违规码集合（含空集）——100% 分类正确。"""
    cases = [
        # (描述, check_geometry kwargs, 期望违规码集合)
        ({"traces_mm": [1.113], "gaps_mm": [0.2], "copper_oz": 1.0,
          "material": "rogers4350b_h0.508"}, set()),
        ({"traces_mm": [0.11], "copper_oz": 1.0}, {"TRACE_BELOW_MIN"}),
        ({"gaps_mm": [0.08], "copper_oz": 1.0}, {"GAP_BELOW_MIN"}),
        ({"copper_oz": 3.0}, {"COPPER_UNSUPPORTED"}),
        ({"material": "ro9999"}, {"MATERIAL_UNSUPPORTED"}),
        ({"drills_mm": [0.1], "pad_diams_mm": [0.19]},
         {"DRILL_BELOW_MIN", "VIA_ANNULAR_RING_BELOW_MIN"}),
        ({"board_thickness_mm": 5.0}, {"BOARD_THICKNESS_OUT_OF_RANGE"}),
        ({"surface_finish": "hard_gold"}, {"SURFACE_FINISH_UNSUPPORTED"}),
        # 多违规叠加：细线+窄缝+未知板材同时逐项列出
        ({"traces_mm": [0.11], "gaps_mm": [0.08], "copper_oz": 1.0,
          "material": "ro9999"},
         {"TRACE_BELOW_MIN", "GAP_BELOW_MIN", "MATERIAL_UNSUPPORTED"}),
    ]
    for kwargs, expected in cases:
        report = check_geometry(JLC, **kwargs)
        codes = {v["code"] for v in report.violations}
        assert codes == expected, f"kwargs={kwargs}: {codes} != {expected}"
        assert report.ok == (not expected)


# ── best-effort 包装（#105）─────────────────────────────────

def test_best_effort_design_report_and_failure_trace() -> None:
    good = {"traces": [{"width": 1.113}], "vias": [{"drill": 0.15, "pad": 0.25}]}
    out = best_effort_dfm_for_design(good, profile_name="jlcpcb")
    assert out["ran"] is True and out["ok"] is True

    bad = {"traces": [{"width": 0.08}]}
    out = best_effort_dfm_for_design(bad, profile_name="jlcpcb")
    assert out["ran"] is True and out["ok"] is False
    assert any(v["code"] == "TRACE_BELOW_MIN" for v in out["violations"])

    missing = best_effort_dfm_for_design(good, profile_name="nonexistent-fab")
    assert missing["ran"] is False and missing["ok"] is None
    assert "reason" in missing
