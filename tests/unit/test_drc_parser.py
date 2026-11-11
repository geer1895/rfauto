"""DRC 规则解析内核单测（aurora_q Q-X48 席位，2026-11-07）。

覆盖面（任务书 ≥20 条之解析/判定内核半边）：
- JSON 形态：夹具 schema 键集+计数链（12 规则/11 启用/1 停用/4 RF/
  2 组/2 警告）、裸列表、缺 rules/缺 name/缺 type 负例、未知类型/
  未知单位如实保留（不判不炸）；
- CSV 形态：表头必填列、range/enum/enabled/priority/layer_scope、
  空行跳过、缺列负例；
- 自由文本行语法：注释/组头/五字段/扩展 key=value/连写单位/range/
  枚举、面外扩展键与缺字段负例；
- 格式检测：内容 sniff 三态+后缀优先；
- 优先级压制：同 (type, layer_scope) 高优先级生效低优先级 superseded、
  异 scope 互不压制；
- 通用方向判定：min/max/range/enum 违规形状（rule/objects/actual/
  expected/unit）、mil→mm 归一、worst 实际值、单位族不匹配 unknown、
  缺测 unknown、层 scope 过滤；
- RF 四检查器：阻抗精度（边界含等号）、焊盘间距最近对/跨层忽略/
  scope 过滤、GND 过孔围栏（网名匹配/缺半径）、屏蔽罩间距（矩形
  距离/罩内零距离）、--rf 未启用跳过；
- dfm_rule_schema 桥：长度归一/ohm range/count 跳过原因、内置缺省
  RF 规则集自洽。

单测零网络零真机零写盘（夹具只读；负例用内联字符串）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.core.dfm_rule_schema import validate_rule
from rfauto.core.drc_parser import (
    DEFAULT_RF_RULESET,
    RF_RULE_TYPES,
    DrcParseError,
    default_rf_rules,
    detect_format,
    evaluate_drc_rules,
    extract_design_objects,
    length_to_mm,
    normalize_rule,
    parse_drc_rules,
    to_dfm_rule,
)

FIXTURE = Path(__file__).resolve().parents[1] / "unit" / "fixtures" / "drc" / "sample_rules.json"

RULE_KEYS = {
    "name", "type", "layer_scope", "value", "unit", "priority", "enabled",
    "group", "direction", "object_types", "tolerance_pct", "radius_mm",
    "notes", "line", "source_format",
}


@pytest.fixture(scope="module")
def doc() -> dict:
    return parse_drc_rules(FIXTURE.read_text(encoding="utf-8"))


def _design(*objects: dict, coord: str = "mm") -> dict:
    return {"coordinate_unit": coord, "objects": list(objects)}


def _run(rules: list[dict], design: dict, *, rf: bool = False) -> dict:
    objects, coord_unit, _w = extract_design_objects(design)
    return evaluate_drc_rules(rules, objects, coord_unit=coord_unit, rf_checks=rf)


def _rules(*specs: dict) -> list[dict]:
    warnings: list[dict] = []
    return [normalize_rule(s, source_format="json", line=i,
                           warnings=warnings, index=i)
            for i, s in enumerate(specs, 1)]


# ── JSON 形态 ──────────────────────────────────────────────────────────────


class TestParseJson:
    def test_fixture_counts_and_format(self, doc: dict) -> None:
        assert doc["format"] == "json"
        meta = doc["metadata"]
        assert meta["n_rules"] == 12
        assert meta["n_enabled"] == 11
        assert meta["n_disabled"] == 1
        assert meta["n_rf_rules"] == 4
        assert meta["n_groups"] == 2
        assert meta["n_warnings"] == 2
        assert meta["title"] == "sample RF DRC ruleset"  # 声明元数据透传

    def test_rule_schema_keys(self, doc: dict) -> None:
        assert len(doc["rules"]) == 12
        for rule in doc["rules"]:
            assert set(rule) == RULE_KEYS

    def test_fixture_rule_field_values(self, doc: dict) -> None:
        by_name = {r["name"]: r for r in doc["rules"]}
        min_w = by_name["min_width_sig"]
        assert min_w["direction"] == "min"
        assert min_w["value"] == 0.15
        assert min_w["unit"] == "mm"
        assert min_w["priority"] == 5
        assert min_w["layer_scope"] == ["F.Cu", "B.Cu"]
        assert min_w["group"] == "rf_general"
        assert min_w["source_format"] == "json"
        imp = by_name["imp_band_rf"]
        assert imp["direction"] == "range"
        assert imp["value"] == [49.0, 51.0]
        assert imp["unit"] == "ohm"
        via = by_name["via_style_std"]
        assert via["direction"] == "enum"
        assert via["value"] == ["through", "blind"]
        assert via["unit"] == "token"
        fence = by_name["rf_gnd_fence"]
        assert fence["unit"] == "count"
        assert fence["value"] == 2.0
        assert fence["radius_mm"] == 1.0
        assert by_name["rf_imp_50"]["tolerance_pct"] == 5.0
        assert by_name["min_drill_std"]["enabled"] is False

    def test_fixture_groups(self, doc: dict) -> None:
        groups = {g["name"]: g for g in doc["groups"]}
        assert groups["rf_general"]["n_rules"] == 3
        assert groups["rf_general"]["n_enabled"] == 3
        assert groups["empty_group"]["rule_names"] == []  # 空组如实保留
        assert groups["rf_general"]["rule_names"][0] == "min_width_sig"

    def test_bare_list_json(self) -> None:
        doc = parse_drc_rules('[{"name": "a", "type": "min_width", "value": 0.1}]')
        assert doc["format"] == "json"
        assert doc["metadata"]["n_rules"] == 1
        assert doc["rules"][0]["unit"] == "mm"  # 缺省单位按类型注册表

    def test_json_missing_rules_raises(self) -> None:
        with pytest.raises(DrcParseError, match="缺 rules"):
            parse_drc_rules('{"metadata": {}}')

    def test_json_rule_missing_name_raises(self) -> None:
        with pytest.raises(DrcParseError, match="缺 name"):
            parse_drc_rules('{"rules": [{"type": "min_width", "value": 1}]}')

    def test_json_rule_missing_type_raises(self) -> None:
        with pytest.raises(DrcParseError, match="缺 type"):
            parse_drc_rules('{"rules": [{"name": "a", "value": 1}]}')

    def test_json_rule_bad_direction_raises(self) -> None:
        with pytest.raises(DrcParseError, match="direction 非法"):
            parse_drc_rules(
                '{"rules": [{"name": "a", "type": "min_width", '
                '"value": 1, "direction": "sideways"}]}')

    def test_unknown_type_kept_with_warning(self, doc: dict) -> None:
        exotic = {r["name"]: r for r in doc["rules"]}["exotic_custom"]
        assert exotic["direction"] is None  # 面外类型保留不判
        notes = " ".join(w["note"] for w in doc["warnings"])
        assert "未知规则类型" in notes
        assert "exotic_unknown" in notes

    def test_unknown_unit_kept_raw_with_warning(self, doc: dict) -> None:
        weird = {r["name"]: r for r in doc["rules"]}["weird_unit_rule"]
        assert weird["unit"] == "furlong"  # 原词保留（不静默换缺省）
        notes = " ".join(w["note"] for w in doc["warnings"])
        assert "未知单位" in notes

    def test_range_inverted_raises(self) -> None:
        with pytest.raises(DrcParseError, match="lo<=hi"):
            parse_drc_rules(
                '{"rules": [{"name": "a", "type": "impedance", '
                '"value": [51, 49]}]}')


# ── CSV 形态 ───────────────────────────────────────────────────────────────

_CSV = (
    "name,type,value,unit,layer_scope,priority,enabled\n"
    "w1,min_width,0.15,mm,F.Cu;B.Cu,5,on\n"
    "imp,impedance,49-51,ohm,F.Cu,10,true\n"
    'vs,via_style,"through,blind",token,*,0,off\n'
    "\n"
)


class TestParseCsv:
    def test_csv_basic_parse(self) -> None:
        doc = parse_drc_rules(_CSV)
        assert doc["format"] == "csv"
        rules = {r["name"]: r for r in doc["rules"]}
        assert doc["metadata"]["n_rules"] == 3  # 尾空行跳过
        assert rules["w1"]["layer_scope"] == ["F.Cu", "B.Cu"]
        assert rules["w1"]["priority"] == 5
        assert rules["w1"]["enabled"] is True
        assert rules["w1"]["line"] == 2  # reader.line_num 行号
        assert rules["imp"]["value"] == [49.0, 51.0]
        assert rules["vs"]["value"] == ["through", "blind"]
        assert rules["vs"]["enabled"] is False
        assert rules["vs"]["layer_scope"] == ["*"]

    def test_csv_missing_required_column_raises(self) -> None:
        with pytest.raises(DrcParseError, match="缺必填列"):
            parse_drc_rules("name,type\na,min_width\n")

    def test_csv_disabled_row_counted(self) -> None:
        doc = parse_drc_rules(_CSV)
        assert doc["metadata"]["n_disabled"] == 1


# ── 自由文本行语法 ─────────────────────────────────────────────────────────

_TEXT = (
    "# 注释行\n"
    "; 分号注释\n"
    "[rf_general]\n"
    "min_w | min_width | 0.15mm | F.Cu,B.Cu | 5 | on\n"
    "imp | impedance | 49-51 ohm | F.Cu | 10\n"
    "vs | via_style | through,blind\n"
    "fence | rf_ground_via_fence | 2 count | * | 0 | off | "
    "radius_mm=1.0 | notes=围栏\n"
)  # fence 行=第 7 行（字符串拼接仍是一行文本）


class TestParseText:
    def test_text_full_grammar(self) -> None:
        doc = parse_drc_rules(_TEXT)
        assert doc["format"] == "text"
        rules = {r["name"]: r for r in doc["rules"]}
        assert doc["metadata"]["n_rules"] == 4
        assert doc["groups"][0]["name"] == "rf_general"
        assert doc["groups"][0]["n_rules"] == 4  # 组头后续规则全归组
        assert doc["groups"][0]["n_enabled"] == 3  # fence=off
        assert rules["min_w"]["value"] == 0.15
        assert rules["min_w"]["unit"] == "mm"  # 连写单位 0.15mm
        assert rules["min_w"]["layer_scope"] == ["F.Cu", "B.Cu"]
        assert rules["min_w"]["priority"] == 5
        assert rules["min_w"]["enabled"] is True
        assert rules["imp"]["value"] == [49.0, 51.0]
        assert rules["imp"]["unit"] == "ohm"
        assert rules["vs"]["value"] == ["through", "blind"]
        assert rules["vs"]["layer_scope"] == ["*"]  # 缺省全层
        assert rules["fence"]["enabled"] is False
        assert rules["fence"]["radius_mm"] == 1.0
        assert rules["fence"]["notes"] == "围栏"
        assert rules["fence"]["line"] == 7

    def test_text_extra_kv_tolerance(self) -> None:
        doc = parse_drc_rules(
            "z | rf_impedance | 50 ohm | * | 0 | on | tolerance_pct=5\n")
        rule = doc["rules"][0]
        assert rule["tolerance_pct"] == 5.0
        assert rule["value"] == 50.0

    def test_text_unknown_extra_key_raises(self) -> None:
        with pytest.raises(DrcParseError, match="扩展字段"):
            parse_drc_rules("a | min_width | 0.1 | | | | foo=1\n")

    def test_text_too_few_fields_raises(self) -> None:
        with pytest.raises(DrcParseError, match="三字段"):
            parse_drc_rules("onlyname | min_width\n")

    def test_text_bad_value_raises(self) -> None:
        with pytest.raises(DrcParseError, match="有限数"):
            parse_drc_rules("a | min_width | wide\n")

    def test_text_bad_range_raises(self) -> None:
        with pytest.raises(DrcParseError, match="range"):
            parse_drc_rules("a | impedance | 49-51-60\n")


# ── 格式检测 ───────────────────────────────────────────────────────────────


class TestDetectFormat:
    def test_sniff_json_bare_list(self) -> None:
        assert detect_format('[{"name": "a"}]') == "json"

    def test_sniff_csv_header(self) -> None:
        assert detect_format("name,type,value\na,min_width,0.1\n") == "csv"

    def test_sniff_text_fallback(self) -> None:
        assert detect_format("a | min_width | 0.1\n") == "text"

    def test_suffix_priority(self) -> None:
        assert detect_format("a | min_width | 0.1\n", "x.json") == "json"
        assert detect_format('{"rules": []}', "x.csv") == "csv"

    def test_comment_lines_ignored_in_sniff(self) -> None:
        assert detect_format("# 头注释\na | min_width | 0.1\n") == "text"


# ── 优先级压制 ─────────────────────────────────────────────────────────────


class TestSuppression:
    def test_same_scope_higher_priority_wins(self) -> None:
        rules = _rules(
            {"name": "low", "type": "min_width", "value": 0.1,
             "layer_scope": ["*"], "priority": 1},
            {"name": "high", "type": "min_width", "value": 0.2,
             "layer_scope": ["*"], "priority": 5},
        )
        design = _design({"name": "T1", "type": "trace", "layer": "F.Cu",
                          "metrics": {"width": 0.15}})
        out = _run(rules, design)
        assert out["summary"]["n_superseded"] == 1
        # low 被 high 压制：0.15 只判 high（violation），low 不判
        assert out["verdict"] == "issues"
        assert len(out["violations"]) == 1
        assert out["violations"][0]["rule"] == "high"
        notes = " ".join(w["note"] for w in out["warnings"])
        assert "压制" in notes and "low" in notes

    def test_different_scope_both_active(self) -> None:
        rules = _rules(
            {"name": "all", "type": "min_width", "value": 0.1,
             "layer_scope": ["*"], "priority": 0},
            {"name": "fcu", "type": "min_width", "value": 0.2,
             "layer_scope": ["F.Cu"], "priority": 0},
        )
        design = _design(
            {"name": "TF", "type": "trace", "layer": "F.Cu",
             "metrics": {"width": 0.15}},
            {"name": "TB", "type": "trace", "layer": "B.Cu",
             "metrics": {"width": 0.15}},
        )
        out = _run(rules, design)
        assert out["summary"]["n_superseded"] == 0
        assert len(out["violations"]) == 1
        assert out["violations"][0]["rule"] == "fcu"
        assert out["violations"][0]["objects"] == ["TF"]

    def test_priority_tie_first_in_file_wins(self) -> None:
        rules = _rules(
            {"name": "first", "type": "min_width", "value": 0.3,
             "layer_scope": ["*"], "priority": 0},
            {"name": "second", "type": "min_width", "value": 0.1,
             "layer_scope": ["*"], "priority": 0},
        )
        design = _design({"name": "T1", "type": "trace", "layer": "F.Cu",
                          "metrics": {"width": 0.2}})
        out = _run(rules, design)
        assert out["violations"][0]["rule"] == "first"


# ── 通用方向判定 ───────────────────────────────────────────────────────────


class TestEvaluateStandard:
    def test_min_width_violation_shape(self) -> None:
        rules = _rules({"name": "w", "type": "min_width", "value": 0.15})
        design = _design({"name": "T1", "type": "trace", "layer": "F.Cu",
                          "metrics": {"width": 0.1}})
        out = _run(rules, design)
        assert out["verdict"] == "issues"
        v = out["violations"][0]
        assert set(v) == {"rule", "objects", "actual", "expected", "unit"}
        assert v["rule"] == "w"
        assert v["objects"] == ["T1"]
        assert v["actual"] == 0.1
        assert v["expected"] == ">= 0.15 mm"
        assert v["unit"] == "mm"
        assert out["summary"]["n_violation_rules"] == 1
        assert out["summary"]["n_object_checks"] == 1

    def test_min_width_pass_mil_normalization(self) -> None:
        rules = _rules({"name": "w_mil", "type": "min_width", "value": 6,
                        "unit": "mil"})
        design = _design({"name": "T1", "type": "trace", "layer": "F.Cu",
                          "metrics": {"width": {"value": 0.2, "unit": "mm"}}})
        out = _run(rules, design)
        assert out["verdict"] == "clean"  # 6 mil=0.1524mm <= 0.2mm
        assert out["violations"] == []
        assert length_to_mm(6.0, "mil") == pytest.approx(0.1524)

    def test_min_width_worst_actual(self) -> None:
        rules = _rules({"name": "w", "type": "min_width", "value": 0.15})
        design = _design(
            {"name": "T1", "type": "trace", "layer": "F.Cu",
             "metrics": {"width": 0.1}},
            {"name": "T2", "type": "trace", "layer": "F.Cu",
             "metrics": {"width": 0.12}},
        )
        out = _run(rules, design)
        assert out["violations"][0]["objects"] == ["T1", "T2"]
        assert out["violations"][0]["actual"] == 0.1  # min 取最小

    def test_max_width_violation(self) -> None:
        rules = _rules({"name": "wmax", "type": "max_width", "value": 0.5})
        design = _design({"name": "T1", "type": "trace", "layer": "F.Cu",
                          "metrics": {"width": 0.8}})
        out = _run(rules, design)
        assert out["violations"][0]["expected"] == "<= 0.5 mm"
        assert out["violations"][0]["actual"] == 0.8

    def test_impedance_range_pass_and_violation(self) -> None:
        rules = _rules({"name": "imp", "type": "impedance",
                        "value": [49, 51], "unit": "ohm"})
        ok_design = _design({"name": "T1", "type": "trace", "layer": "F.Cu",
                             "metrics": {"impedance": 50.0}})
        assert _run(rules, ok_design)["verdict"] == "clean"
        bad_design = _design({"name": "T1", "type": "trace", "layer": "F.Cu",
                              "metrics": {"impedance": 52.0}})
        out = _run(rules, bad_design)
        assert out["violations"][0]["expected"] == "in [49, 51] ohm"
        assert out["violations"][0]["actual"] == 52.0

    def test_via_style_enum_violation(self) -> None:
        rules = _rules({"name": "vs", "type": "via_style",
                        "value": ["through", "blind"]})
        design = _design({"name": "V1", "type": "via", "layer": "F.Cu",
                          "metrics": {"via_style": "buried"}})
        out = _run(rules, design)
        assert out["violations"][0]["actual"] == "buried"
        assert out["violations"][0]["expected"] == "in {through, blind}"

    def test_unit_family_mismatch_unknown(self) -> None:
        rules = _rules({"name": "w", "type": "min_width", "value": 0.15})
        design = _design({"name": "T1", "type": "trace", "layer": "F.Cu",
                          "metrics": {"width": {"value": 50, "unit": "ohm"}}})
        out = _run(rules, design)
        assert out["verdict"] == "attention"
        assert out["violations"] == []
        assert out["summary"]["n_unknown_rules"] == 1
        notes = " ".join(w["note"] for w in out["warnings"])
        assert "不匹配" in notes

    def test_missing_metric_unknown(self) -> None:
        rules = _rules({"name": "w", "type": "min_width", "value": 0.15})
        design = _design({"name": "T1", "type": "trace", "layer": "F.Cu"})
        out = _run(rules, design)
        assert out["verdict"] == "attention"
        assert out["summary"]["n_unknown_rules"] == 1
        assert out["summary"]["n_evaluated"] == 0

    def test_disabled_and_unknown_type_not_evaluated(self) -> None:
        warnings: list[dict] = []
        rules = [
            normalize_rule({"name": "off", "type": "min_width", "value": 0.1,
                            "enabled": False}, source_format="json", line=1,
                           warnings=warnings, index=1),
            normalize_rule({"name": "weird", "type": "mystery", "value": 1},
                           source_format="json", line=2,
                           warnings=warnings, index=2),
        ]
        design = _design({"name": "T1", "type": "trace", "layer": "F.Cu",
                          "metrics": {"width": 0.05}})
        out = _run(rules, design)
        assert out["summary"]["n_evaluated"] == 0
        assert out["verdict"] == "attention"

    def test_layer_scope_filtering(self) -> None:
        rules = _rules({"name": "w", "type": "min_width", "value": 0.15,
                        "layer_scope": ["F.Cu"]})
        design = _design(
            {"name": "TB", "type": "trace", "layer": "B.Cu",
             "metrics": {"width": 0.05}},  # scope 外不判
            {"name": "TF", "type": "trace", "layer": "F.Cu",
             "metrics": {"width": 0.1}},
        )
        out = _run(rules, design)
        assert out["violations"][0]["objects"] == ["TF"]
        assert out["summary"]["n_object_checks"] == 1

    def test_empty_scope_no_objects_unknown(self) -> None:
        rules = _rules({"name": "w", "type": "min_width", "value": 0.15})
        out = _run(rules, _design())
        assert out["verdict"] == "attention"
        assert out["summary"]["n_unknown_rules"] == 1


# ── RF 特化检查器 ──────────────────────────────────────────────────────────

_RF_BOARD = _design(
    {"name": "TL1", "type": "trace", "layer": "F.Cu", "rf": True,
     "metrics": {"impedance": 50.2}, "x": 0.0, "y": 0.0},
    {"name": "P1", "type": "pad", "layer": "F.Cu", "x": 0.0, "y": 0.0},
    {"name": "P2", "type": "pad", "layer": "F.Cu", "x": 3.0, "y": 0.0},
    {"name": "VG1", "type": "via", "layer": "F.Cu", "net": "GND",
     "x": 0.5, "y": 0.0},
    {"name": "VG2", "type": "via", "layer": "F.Cu", "net": "GND",
     "x": 0.9, "y": 0.0},
    {"name": "VS1", "type": "via", "layer": "F.Cu", "net": "SIG",
     "x": 0.1, "y": 0.0},
    {"name": "SH1", "type": "shield", "layer": "MECH",
     "x": 10.0, "y": 0.0, "w": 2.0, "h": 4.0},
)


class TestRfCheckers:
    def test_rf_board_all_pass_with_fixture_rules(self, doc: dict) -> None:
        out = _run(doc["rules"], _RF_BOARD, rf=True)
        assert out["summary"]["n_rf_skipped"] == 0
        rf_rules = [r for r in doc["rules"] if r["type"] in RF_RULE_TYPES]
        assert len(rf_rules) == 4
        # 四 RF 检查器全过（阻抗 50.2 在带内/焊盘 3mm/围栏 2 孔/屏蔽 9mm）
        for r in rf_rules:
            assert r["name"] not in {v["rule"] for v in out["violations"]}
            assert r["name"] not in {w.get("rule") for w in out["warnings"]}

    def test_rf_rules_skipped_without_flag(self, doc: dict) -> None:
        out = _run(doc["rules"], _RF_BOARD, rf=False)
        assert out["summary"]["n_rf_skipped"] == 4
        notes = " ".join(w["note"] for w in out["warnings"])
        assert "RF 检查未启用" in notes

    def test_rf_impedance_boundary_inclusive(self) -> None:
        rules = _rules({"name": "z", "type": "rf_impedance", "value": 50,
                        "tolerance_pct": 5})
        at_band = _design({"name": "T", "type": "trace", "layer": "F.Cu",
                           "rf": True, "metrics": {"impedance": 47.5}})
        assert _run(rules, at_band, rf=True)["verdict"] == "clean"  # dev=band 不违规
        beyond = _design({"name": "T", "type": "trace", "layer": "F.Cu",
                          "rf": True, "metrics": {"impedance": 47.4}})
        out = _run(rules, beyond, rf=True)
        assert out["violations"][0]["rule"] == "z"
        assert out["violations"][0]["actual"] == 47.4
        assert out["violations"][0]["expected"] == "50 ohm ±5%"

    def test_rf_impedance_missing_tolerance_unknown(self) -> None:
        rules = _rules({"name": "z", "type": "rf_impedance", "value": 50})
        design = _design({"name": "T", "type": "trace", "layer": "F.Cu",
                          "rf": True, "metrics": {"impedance": 60.0}})
        out = _run(rules, design, rf=True)
        assert out["verdict"] == "attention"
        assert out["summary"]["n_unknown_rules"] == 1
        assert "tolerance_pct" in out["warnings"][0]["note"]

    def test_rf_impedance_non_rf_trace_ignored(self) -> None:
        rules = _rules({"name": "z", "type": "rf_impedance", "value": 50,
                        "tolerance_pct": 5})
        design = _design({"name": "T", "type": "trace", "layer": "F.Cu",
                          "metrics": {"impedance": 60.0}})  # 无 rf 旗标
        out = _run(rules, design, rf=True)
        assert out["summary"]["n_unknown_rules"] == 1

    def test_rf_pad_clearance_violation_closest_pair(self) -> None:
        rules = _rules({"name": "pg", "type": "rf_pad_clearance",
                        "value": 0.2})
        design = _design(
            {"name": "PA", "type": "pad", "layer": "F.Cu", "x": 0, "y": 0},
            {"name": "PB", "type": "pad", "layer": "F.Cu", "x": 5, "y": 0},
            {"name": "PC", "type": "pad", "layer": "F.Cu", "x": 0.1, "y": 0},
        )
        out = _run(rules, design, rf=True)
        assert out["violations"][0]["objects"] == ["PA", "PC"]  # 最近对
        assert out["violations"][0]["actual"] == pytest.approx(0.1)
        assert out["violations"][0]["expected"] == ">= 0.2 mm"

    def test_rf_pad_clearance_cross_layer_ignored(self) -> None:
        rules = _rules({"name": "pg", "type": "rf_pad_clearance",
                        "value": 0.2})
        design = _design(
            {"name": "PF", "type": "pad", "layer": "F.Cu", "x": 0, "y": 0},
            {"name": "PB", "type": "pad", "layer": "B.Cu", "x": 0.05, "y": 0},
        )
        out = _run(rules, design, rf=True)
        assert out["violations"] == []  # 跨层对不参与同层间距
        assert out["summary"]["n_unknown_rules"] == 1  # 无同层对=unknown

    def test_rf_pad_clearance_pass(self) -> None:
        rules = _rules({"name": "pg", "type": "rf_pad_clearance",
                        "value": 0.2})
        design = _design(
            {"name": "PA", "type": "pad", "layer": "F.Cu", "x": 0, "y": 0},
            {"name": "PB", "type": "pad", "layer": "F.Cu", "x": 0.25, "y": 0},
        )
        assert _run(rules, design, rf=True)["verdict"] == "clean"

    def test_rf_ground_via_fence_violation(self) -> None:
        rules = _rules({"name": "f", "type": "rf_ground_via_fence",
                        "value": 2, "radius_mm": 1.0})
        design = _design(
            {"name": "TL", "type": "trace", "layer": "F.Cu", "rf": True,
             "x": 0.0, "y": 0.0},
            {"name": "VG", "type": "via", "layer": "F.Cu", "net": "GND",
             "x": 5.0, "y": 0.0},  # 半径外
            {"name": "VS", "type": "via", "layer": "F.Cu", "net": "SIG",
             "x": 0.1, "y": 0.0},  # 信号孔不计数
        )
        out = _run(rules, design, rf=True)
        v = out["violations"][0]
        assert v["rule"] == "f"
        assert v["objects"] == ["TL"]
        assert v["actual"] == 0
        assert v["expected"] == ">= 2 GND via within 1 mm"
        assert v["unit"] == "count"

    def test_rf_ground_via_fence_net_variants_count(self) -> None:
        rules = _rules({"name": "f", "type": "rf_ground_via_fence",
                        "value": 2, "radius_mm": 1.0})
        design = _design(
            {"name": "TL", "type": "trace", "layer": "F.Cu", "rf": True,
             "x": 0.0, "y": 0.0},
            {"name": "V1", "type": "via", "net": "GND_1",
             "x": 0.3, "y": 0.0},
            {"name": "V2", "type": "via", "net": "agnd",
             "x": 0.6, "y": 0.0},
        )
        out = _run(rules, design, rf=True)
        assert out["verdict"] == "clean"  # GND_1/agnd 网名变体都计数

    def test_rf_ground_via_fence_missing_radius_unknown(self) -> None:
        rules = _rules({"name": "f", "type": "rf_ground_via_fence",
                        "value": 2})
        design = _design({"name": "TL", "type": "trace", "layer": "F.Cu",
                          "rf": True, "x": 0, "y": 0})
        out = _run(rules, design, rf=True)
        assert out["summary"]["n_unknown_rules"] == 1
        assert "radius_mm" in out["warnings"][0]["note"]

    def test_rf_ground_via_fence_missing_coords_unknown(self) -> None:
        rules = _rules({"name": "f", "type": "rf_ground_via_fence",
                        "value": 2, "radius_mm": 1.0})
        design = _design({"name": "TL", "type": "trace", "layer": "F.Cu",
                          "rf": True})
        out = _run(rules, design, rf=True)
        assert out["summary"]["n_unknown_rules"] == 1

    def test_rf_shield_clearance_violation_and_pass(self) -> None:
        rules = _rules({"name": "sg", "type": "rf_shield_clearance",
                        "value": 0.5})
        shield = {"name": "SH", "type": "shield", "layer": "MECH",
                  "x": 10.0, "y": 0.0, "w": 2.0, "h": 4.0}

        def board(px: float) -> dict:
            return _design(
                {"name": "TL", "type": "trace", "layer": "F.Cu", "rf": True,
                 "x": px, "y": 0.0}, shield)

        out = _run(rules, board(8.8), rf=True)  # 距罩缘 0.2mm
        assert out["violations"][0]["objects"] == ["TL", "SH"]
        assert out["violations"][0]["actual"] == pytest.approx(0.2)
        assert _run(rules, board(8.0), rf=True)["verdict"] == "clean"  # 距 1.0mm

    def test_rf_shield_inside_rect_zero_distance(self) -> None:
        rules = _rules({"name": "sg", "type": "rf_shield_clearance",
                        "value": 0.5})
        design = _design(
            {"name": "TL", "type": "trace", "layer": "F.Cu", "rf": True,
             "x": 10.0, "y": 0.0},  # 罩内
            {"name": "SH", "type": "shield", "x": 10.0, "y": 0.0,
             "w": 2.0, "h": 4.0},
        )
        out = _run(rules, design, rf=True)
        assert out["violations"][0]["actual"] == 0.0

    def test_rf_shield_missing_side_unknown(self) -> None:
        rules = _rules({"name": "sg", "type": "rf_shield_clearance",
                        "value": 0.5})
        design = _design({"name": "TL", "type": "trace", "layer": "F.Cu",
                          "rf": True, "x": 0, "y": 0})
        out = _run(rules, design, rf=True)
        assert out["verdict"] == "attention"
        assert out["summary"]["n_unknown_rules"] == 1

    def test_coordinate_unit_mil_normalization(self) -> None:
        rules = _rules({"name": "pg", "type": "rf_pad_clearance",
                        "value": 0.2})
        design = _design(
            {"name": "PA", "type": "pad", "layer": "F.Cu",
             "x": 0.0, "y": 0.0},
            {"name": "PB", "type": "pad", "layer": "F.Cu",
             "x": 9.842519685039370, "y": 0.0},  # ≈0.24999 mm
            coord="mil",
        )
        out = _run(rules, design, rf=True)
        assert out["verdict"] == "clean"  # mil 坐标归一 mm 后 ≈0.25 >= 0.2


# ── dfm_rule_schema 桥 + 缺省 RF 规则集 ────────────────────────────────────


class TestToDfmBridge:
    def test_to_dfm_min_length_conversion(self) -> None:
        rules = _rules({"name": "w", "type": "min_width", "value": 4,
                        "unit": "mil"})
        dfm, reason = to_dfm_rule(rules[0])
        assert reason is None
        assert dfm["id"] == "w"
        assert dfm["direction"] == "min"
        assert dfm["quantity"] == "length_mm"
        assert dfm["value"] == pytest.approx(0.1016)
        assert dfm["ipc_ref"] == "UNVERIFIED_doc_anchor"  # 诚实口径不臆造锚
        validate_rule(dfm)  # 映射产物过 dfm schema 校验（单源闭环）

    def test_to_dfm_range_ohm(self) -> None:
        rules = _rules({"name": "imp", "type": "impedance",
                        "value": [49, 51], "unit": "ohm"})
        dfm, reason = to_dfm_rule(rules[0])
        assert reason is None
        assert dfm["quantity"] == "impedance_ohm"
        assert dfm["direction"] == "range"
        assert dfm["value"] == [49.0, 51.0]
        validate_rule(dfm)

    def test_to_dfm_count_skipped_with_reason(self) -> None:
        rules = _rules({"name": "f", "type": "rf_ground_via_fence",
                        "value": 2, "unit": "count"})
        dfm, reason = to_dfm_rule(rules[0])
        assert dfm is None
        assert reason is not None and "count" in reason

    def test_to_dfm_unknown_direction_skipped(self) -> None:
        warnings: list[dict] = []
        rule = normalize_rule({"name": "x", "type": "mystery", "value": 1},
                              source_format="json", line=1,
                              warnings=warnings, index=1)
        dfm, reason = to_dfm_rule(rule)
        assert dfm is None and reason is not None

    def test_default_rf_ruleset_normalized(self) -> None:
        rules = default_rf_rules()
        assert len(DEFAULT_RF_RULESET) == 4
        assert len(rules) == 4
        names = [r["name"] for r in rules]
        assert len(set(names)) == 4  # 名唯一
        for rule in rules:
            assert rule["type"] in RF_RULE_TYPES
            assert rule["direction"] is not None
            assert rule["enabled"] is True
            assert rule["source_format"] == "builtin"
