"""DRC 服务包装+CLI 薄壳单测（aurora_q Q-X48 席位，2026-11-07）。

覆盖面（任务书 ≥20 条之服务/CLI 半边）：
- service 两函数信封形状（ok/error 三态；errors 恒 list[str]）；
- parse 信封 schema 键集（path/format/rules/groups/metadata/warnings）；
- validate 信封 schema 键集（violations/summary/verdict/rules_source/
  coordinate_unit）+ verdict 三态（clean/issues/attention）+ 规则缺省
  链（--rules 文件 / rf 内置缺省 RF 规则集 / 双缺 error）；
- design 结构负例（缺 objects/坏 JSON/不可读）→ error 信封；
- CLI：parse --json 全结构+缺省紧凑面+--rules/--rf human 展开、
  validate --json/违规 human 面（verdict=issues 仍 exit 0——违规≠调用
  失败）、失败路径 JSON 信封同构（#ge1㉙ 契约）+exit 1、usage 错
  exit 2；
- 计数链（本席不钉总数——绝对数锚归 test_check_numbers/test_cli
  权威共享面，本文件只断言 drc 域叶数=2 防遮蔽回归）。

单测零网络零真机（夹具只读；design/rules 负例写 tmp_path，不落仓）。
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.service.drc_service import parse_drc_file, validate_design_file

FIXTURE = Path(__file__).resolve().parents[1] / "unit" / "fixtures" / "drc" / "sample_rules.json"
runner = CliRunner()

PARSE_TOP_KEYS = {
    "ok", "path", "format", "rules", "groups", "metadata", "warnings",
}
VALIDATE_TOP_KEYS = {
    "ok", "design_path", "rules_path", "rules_source", "format",
    "coordinate_unit", "rules", "groups", "metadata", "violations",
    "summary", "verdict", "warnings",
}

CLEAN_DESIGN = {
    "name": "board_a",
    "coordinate_unit": "mm",
    "objects": [
        {"name": "TL1", "type": "trace", "layer": "F.Cu", "rf": True,
         "metrics": {"width": 0.3, "impedance": 50.2}, "x": 0.0, "y": 0.0},
        {"name": "P1", "type": "pad", "layer": "F.Cu", "x": 0.0, "y": 0.0},
        {"name": "P2", "type": "pad", "layer": "F.Cu", "x": 3.0, "y": 0.0},
        {"name": "VG1", "type": "via", "layer": "F.Cu", "net": "GND",
         "x": 0.5, "y": 0.0},
        {"name": "VG2", "type": "via", "layer": "F.Cu", "net": "GND",
         "x": 0.9, "y": 0.0},
        {"name": "SH1", "type": "shield", "layer": "MECH", "x": 10.0,
         "y": 0.0, "w": 2.0, "h": 4.0},
    ],
}
VIOLATION_DESIGN = {
    "coordinate_unit": "mm",
    "objects": [
        {"name": "BAD1", "type": "trace", "layer": "F.Cu",
         "metrics": {"width": 0.1}},
    ],
}


def _write_json(tmp_path: Path, name: str, data: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# ── service：parse_drc_file ────────────────────────────────────────────────


class TestParseDrcFile:
    def test_ok_envelope_schema(self) -> None:
        result = parse_drc_file(FIXTURE)
        assert result["ok"] is True
        assert set(result) == PARSE_TOP_KEYS
        assert result["format"] == "json"
        assert result["metadata"]["n_rules"] == 12

    def test_parse_failure_unreadable_error_envelope(self) -> None:
        result = parse_drc_file("no_such_rules.json")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert len(result["errors"]) == 1
        assert "不可读" in result["errors"][0]

    def test_parse_failure_bad_json_error_envelope(
        self, tmp_path: Path,
    ) -> None:
        bad = tmp_path / "broken.json"
        bad.write_text("{not json", encoding="utf-8")
        result = parse_drc_file(bad)
        assert result["ok"] is False
        assert "JSON 解析失败" in result["errors"][0]

    def test_parse_failure_structure_error_envelope(
        self, tmp_path: Path,
    ) -> None:
        bad = tmp_path / "norules.json"
        bad.write_text("{}", encoding="utf-8")
        result = parse_drc_file(bad)
        assert result["ok"] is False
        assert "缺 rules" in result["errors"][0]


# ── service：validate_design_file ──────────────────────────────────────────


class TestValidateDesignFile:
    def test_validate_clean_with_fixture_rules(self, tmp_path: Path) -> None:
        design = _write_json(tmp_path, "clean.json", CLEAN_DESIGN)
        result = validate_design_file(design, FIXTURE, rf=True)
        assert result["ok"] is True
        assert set(result) == VALIDATE_TOP_KEYS
        assert result["rules_source"] == "file"
        assert result["coordinate_unit"] == "mm"
        # 标准规则缺测项（clearance/via_style/annular 等）→ attention 如实
        assert result["verdict"] == "attention"
        assert result["violations"] == []
        assert result["summary"]["n_rf_skipped"] == 0

    def test_validate_violation_shape(self, tmp_path: Path) -> None:
        design = _write_json(tmp_path, "bad.json", VIOLATION_DESIGN)
        result = validate_design_file(design, FIXTURE)
        assert result["ok"] is True
        assert result["verdict"] == "issues"
        v = result["violations"][0]
        assert set(v) == {"rule", "objects", "actual", "expected", "unit"}
        assert v["rule"] == "min_width_sig"
        assert v["objects"] == ["BAD1"]
        assert v["actual"] == 0.1
        assert v["expected"] == ">= 0.15 mm"

    def test_validate_rf_default_ruleset(self, tmp_path: Path) -> None:
        design = _write_json(tmp_path, "clean.json", CLEAN_DESIGN)
        result = validate_design_file(design, None, rf=True)
        assert result["ok"] is True
        assert result["rules_source"] == "default_rf"
        assert result["rules_path"] is None
        assert len(result["rules"]) == 4
        rf_types = {r["type"] for r in result["rules"]}
        assert rf_types == {
            "rf_impedance", "rf_pad_clearance",
            "rf_ground_via_fence", "rf_shield_clearance"}

    def test_validate_no_rules_no_rf_error_envelope(
        self, tmp_path: Path,
    ) -> None:
        design = _write_json(tmp_path, "clean.json", CLEAN_DESIGN)
        result = validate_design_file(design, None, rf=False)
        assert result["ok"] is False
        assert len(result["errors"]) == 1
        assert "--rules" in result["errors"][0]

    def test_validate_rf_skipped_without_flag(self, tmp_path: Path) -> None:
        design = _write_json(tmp_path, "clean.json", CLEAN_DESIGN)
        result = validate_design_file(design, FIXTURE, rf=False)
        assert result["ok"] is True
        assert result["summary"]["n_rf_skipped"] == 4

    def test_validate_bad_design_missing_objects(
        self, tmp_path: Path,
    ) -> None:
        design = _write_json(tmp_path, "noobj.json", {"name": "x"})
        result = validate_design_file(design, FIXTURE)
        assert result["ok"] is False
        assert "缺 objects" in result["errors"][0]

    def test_validate_bad_design_not_object(self, tmp_path: Path) -> None:
        path = tmp_path / "arr.json"
        path.write_text("[1, 2]", encoding="utf-8")
        result = validate_design_file(str(path), FIXTURE)
        assert result["ok"] is False

    def test_validate_bad_design_broken_json(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{oops", encoding="utf-8")
        result = validate_design_file(str(path), FIXTURE)
        assert result["ok"] is False
        assert "JSON 解析失败" in result["errors"][0]

    def test_validate_rules_file_unreadable(self, tmp_path: Path) -> None:
        design = _write_json(tmp_path, "clean.json", CLEAN_DESIGN)
        result = validate_design_file(design, "no_such_rules.json")
        assert result["ok"] is False
        assert "不可读" in result["errors"][0]


# ── CLI：drc parse / drc validate ──────────────────────────────────────────


class TestCliDrc:
    def test_parse_json_full_envelope(self) -> None:
        r = runner.invoke(root_app, ["drc", "parse", str(FIXTURE), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert set(payload) == PARSE_TOP_KEYS
        assert payload["metadata"]["n_rules"] == 12
        assert payload["metadata"]["n_rf_rules"] == 4

    def test_parse_default_compact_output(self) -> None:
        r = runner.invoke(root_app, ["drc", "parse", str(FIXTURE)])
        assert r.exit_code == 0, r.output
        assert "min_width_sig" not in r.output  # 紧凑面不展开规则表
        assert "rules=12" in r.output
        assert "rf_rules=4" in r.output

    def test_parse_rules_flag_expands_table(self) -> None:
        r = runner.invoke(root_app, ["drc", "parse", str(FIXTURE), "--rules"])
        assert r.exit_code == 0, r.output
        assert "min_width_sig" in r.output
        assert "imp_band_rf" in r.output

    def test_parse_rf_flag_expands_checkers(self) -> None:
        r = runner.invoke(root_app, ["drc", "parse", str(FIXTURE), "--rf"])
        assert r.exit_code == 0, r.output
        assert "rf_impedance" in r.output
        assert "屏蔽罩间距" in r.output
        assert "rf_imp_50" in r.output  # 命中规则名

    def test_parse_failure_json_envelope_exit1(self) -> None:
        r = runner.invoke(root_app, ["drc", "parse", "no_such.json", "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)
        assert len(payload["errors"]) == 1

    def test_parse_failure_human_exit1(self) -> None:
        r = runner.invoke(root_app, ["drc", "parse", "no_such.json"])
        assert r.exit_code == 1
        assert "DRC 规则解析失败" in r.output

    def test_parse_missing_argument_exit2(self) -> None:
        r = runner.invoke(root_app, ["drc", "parse"])
        assert r.exit_code == 2

    def test_validate_json_clean(self, tmp_path: Path) -> None:
        design = _write_json(tmp_path, "clean.json", CLEAN_DESIGN)
        r = runner.invoke(root_app, [
            "drc", "validate", design, "--rules", str(FIXTURE), "--rf",
            "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert set(payload) == VALIDATE_TOP_KEYS
        assert payload["verdict"] == "attention"
        assert payload["violations"] == []
        assert payload["summary"]["n_rf_skipped"] == 0

    def test_validate_violation_human_exit0(self, tmp_path: Path) -> None:
        design = _write_json(tmp_path, "bad.json", VIOLATION_DESIGN)
        r = runner.invoke(root_app, [
            "drc", "validate", design, "--rules", str(FIXTURE)])
        assert r.exit_code == 0, r.output  # 违规≠调用失败
        assert "verdict=issues" in r.output
        assert "min_width_sig" in r.output
        assert "BAD1" in r.output

    def test_validate_default_rf_human(self, tmp_path: Path) -> None:
        design = _write_json(tmp_path, "clean.json", CLEAN_DESIGN)
        r = runner.invoke(root_app, ["drc", "validate", design, "--rf"])
        assert r.exit_code == 0, r.output
        assert "verdict=" in r.output

    def test_validate_no_rules_human_error_exit1(self, tmp_path: Path) -> None:
        design = _write_json(tmp_path, "clean.json", CLEAN_DESIGN)
        r = runner.invoke(root_app, ["drc", "validate", design])
        assert r.exit_code == 1
        assert "无规则可校验" in r.output

    def test_validate_no_rules_json_envelope_exit1(
        self, tmp_path: Path,
    ) -> None:
        design = _write_json(tmp_path, "clean.json", CLEAN_DESIGN)
        r = runner.invoke(root_app, ["drc", "validate", design, "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)

    def test_validate_unreadable_design_exit1(self) -> None:
        r = runner.invoke(root_app, [
            "drc", "validate", "no_such_design.json", "--rules",
            str(FIXTURE), "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert "不可读" in payload["errors"][0]

    def test_validate_missing_argument_exit2(self) -> None:
        r = runner.invoke(root_app, ["drc", "validate"])
        assert r.exit_code == 2

    def test_drc_leaves_in_tree(self) -> None:
        # 本席域形状钉（绝对总数归 test_check_numbers/test_cli 权威共享面；
        # 本钉防同域叶遮蔽/漂移回归）
        from typer.main import get_command

        cmd = get_command(root_app)
        drc_group = cmd.commands.get("drc")
        assert drc_group is not None, "drc 顶层域不在 CLI 树"
        assert set(drc_group.commands) == {"parse", "validate"}
