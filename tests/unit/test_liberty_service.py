"""Liberty 解析服务+CLI 薄壳单测（aurora_q Q-X34 席位，2026-11-07）。

覆盖面（任务书 ≥20 条之服务/CLI 半边）：
- 服务信封正例：parse 全结构+stats 计数（对返回视图）、list 清单；
- 过滤面：--cell 命中/未知名 error 信封（附可用清单）、--pin 配合
  --cell（缺 cell 拒收）、pin 未知名 error；
- 裁面开关：include_timing=False 剪 timing、include_power=False 剪
  功率面（stats 同步缩）；
- 错误归一：文件不可读/语法违规 → error 信封（errors 恒 list[str]）；
- CLI ``rfauto liberty parse|list``：--json 信封、紧凑人读面、--timing
  展开、usage 类错误 exit 2（--json 下 JSON 信封，#ge1㉙ 契约）、失败
  exit 1；
- 计数链 grep 字面钉：域文件内两叶装饰器字面 + CLI 注册面恰 2 叶。

单测零网络零真机零 runs/ 湖写入（--json 落盘面为零写盘纯读）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.service.liberty_service import list_liberty_cells, parse_liberty_file

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "liberty" / "sample.lib"

runner = CliRunner()


# ── 服务信封正例 ────────────────────────────────────────────────────────────


class TestParseEnvelope:
    def test_full_parse_stats(self) -> None:
        result = parse_liberty_file(FIXTURE)
        assert result["ok"] is True
        assert result["library"] == "sample_lib_rfauto"
        assert result["file_version"] == "1.0"
        assert result["path"] == str(FIXTURE)
        stats = result["stats"]
        # pin: INVX1×2 + BUFX2×2 + DFFX1×3 = 7；timing 组 1+1+2 = 4；
        # timing 表 4×3 组 = 12；功率组 1 internal+2 leakage = 3，功率表 2
        assert stats == {
            "n_cells": 3, "n_pins": 7, "n_timing_groups": 4,
            "n_timing_tables": 12, "n_power_groups": 3, "n_power_tables": 2,
            "n_leakage_groups": 2, "n_lu_templates": 2,
        }

    def test_schema_keys_stable(self) -> None:
        result = parse_liberty_file(FIXTURE)
        assert {"ok", "path", "library", "file_version", "units", "cells",
                "operating_conditions", "lu_templates", "stats",
                "filters"} <= set(result)

    def test_operating_conditions_and_templates_exposed(self) -> None:
        result = parse_liberty_file(FIXTURE)
        assert "TYP_1V25_25C" in result["operating_conditions"]
        assert set(result["lu_templates"]) == {
            "delay_template_2x2", "power_template_2x2"}

    def test_cell_filter(self) -> None:
        result = parse_liberty_file(FIXTURE, cell="INVX1")
        assert result["ok"] is True
        assert set(result["cells"]) == {"INVX1"}
        assert result["stats"]["n_cells"] == 1
        assert result["stats"]["n_pins"] == 2
        assert result["filters"]["cell"] == "INVX1"

    def test_cell_filter_unknown_lists_available(self) -> None:
        result = parse_liberty_file(FIXTURE, cell="NOPE")
        assert result["ok"] is False
        assert "NOPE" in result["errors"][0]
        assert "INVX1" in result["errors"][0]  # 可用清单如实回显

    def test_pin_filter_requires_cell(self) -> None:
        result = parse_liberty_file(FIXTURE, pin="A")
        assert result["ok"] is False
        assert "cell" in result["errors"][0]

    def test_pin_filter_within_cell(self) -> None:
        result = parse_liberty_file(FIXTURE, cell="INVX1", pin="A")
        assert result["ok"] is True
        assert set(result["cells"]["INVX1"]["pins"]) == {"A"}
        assert result["stats"]["n_pins"] == 1
        assert result["stats"]["n_timing_groups"] == 0  # A pin 无 timing

    def test_pin_filter_unknown_lists_available(self) -> None:
        result = parse_liberty_file(FIXTURE, cell="INVX1", pin="ZZ")
        assert result["ok"] is False
        assert "ZZ" in result["errors"][0]
        assert "ZN" in result["errors"][0]

    def test_include_timing_false_strips_tables(self) -> None:
        result = parse_liberty_file(FIXTURE, cell="INVX1", include_timing=False)
        zn = result["cells"]["INVX1"]["pins"]["ZN"]
        assert "timing" not in zn
        assert zn["direction"] == "output"  # 元数据不受裁面影响
        assert result["stats"]["n_timing_groups"] == 0
        assert result["stats"]["n_timing_tables"] == 0
        assert result["stats"]["n_power_groups"] == 3  # 功率面仍在

    def test_include_power_false_strips_power(self) -> None:
        result = parse_liberty_file(FIXTURE, cell="INVX1", include_power=False)
        centry = result["cells"]["INVX1"]
        assert all("internal_power" not in p
                   for p in centry["pins"].values())
        assert "leakage_power" not in centry
        assert "cell_leakage_power" not in centry
        assert result["stats"]["n_power_tables"] == 0
        assert result["stats"]["n_timing_tables"] == 4  # timing 面仍在


class TestListEnvelope:
    def test_list_full(self) -> None:
        result = list_liberty_cells(FIXTURE)
        assert result["ok"] is True
        assert result["library"] == "sample_lib_rfauto"
        assert [c["name"] for c in result["cells"]] == ["INVX1", "BUFX2", "DFFX1"]
        assert result["cells"][0]["area"] == 4.5
        assert result["cells"][0]["n_pins"] == 2
        assert result["cells"][0]["n_timing_tables"] == 4
        assert result["cells"][2]["n_timing_groups"] == 2  # DFFX1 双沿
        assert result["lu_template_names"] == [
            "delay_template_2x2", "power_template_2x2"]
        assert result["operating_condition_names"] == ["TYP_1V25_25C"]
        assert result["stats"]["n_pins"] == 7

    def test_missing_file_error_envelope(self, tmp_path: Path) -> None:
        result = parse_liberty_file(tmp_path / "nope.lib")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert "不可读" in result["errors"][0]
        assert list_liberty_cells(tmp_path / "nope.lib")["ok"] is False

    def test_malformed_file_error_envelope(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.lib"
        bad.write_text("library (x) { cell (C) {", encoding="utf-8")
        result = parse_liberty_file(bad)
        assert result["ok"] is False
        assert "Liberty 解析失败" in result["errors"][0]
        assert list_liberty_cells(bad)["ok"] is False


# ── CLI 薄壳（liberty parse/list 两叶）─────────────────────────────────────


class TestCliLiberty:
    def test_parse_json_envelope(self) -> None:
        r = runner.invoke(app, ["liberty", "parse", str(FIXTURE), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["library"] == "sample_lib_rfauto"
        assert payload["stats"]["n_cells"] == 3

    def test_parse_default_compact_no_tables(self) -> None:
        # 缺省紧凑面：pin 元数据在、查找表体不在
        r = runner.invoke(app, ["liberty", "parse", str(FIXTURE), "--json"])
        payload = json.loads(r.output)
        zn = payload["cells"]["INVX1"]["pins"]["ZN"]
        assert zn["direction"] == "output"
        assert "timing" not in zn

    def test_parse_timing_flag_expands_tables(self) -> None:
        r = runner.invoke(
            app, ["liberty", "parse", str(FIXTURE), "--cell", "INVX1",
                  "--timing", "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        tg = payload["cells"]["INVX1"]["pins"]["ZN"]["timing"]["A"]
        assert tg["cell_rise"]["values"][0][0] == pytest.approx(0.0314605)
        assert payload["stats"]["n_timing_tables"] == 4

    def test_parse_power_flag_expands_power(self) -> None:
        r = runner.invoke(
            app, ["liberty", "parse", str(FIXTURE), "--cell", "INVX1",
                  "--power", "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["cells"]["INVX1"]["pins"]["ZN"]["internal_power"][0][
            "rise_power"] is not None
        assert len(payload["cells"]["INVX1"]["leakage_power"]) == 2

    def test_parse_human_output(self) -> None:
        r = runner.invoke(app, ["liberty", "parse", str(FIXTURE), "--cell", "INVX1"])
        assert r.exit_code == 0
        assert "INVX1" in r.output
        assert "sample_lib_rfauto" in r.output

    def test_parse_pin_without_cell_exit2(self) -> None:
        r = runner.invoke(app, ["liberty", "parse", str(FIXTURE), "--pin", "A"])
        assert r.exit_code == 2

    def test_parse_pin_without_cell_json_envelope(self) -> None:
        # #ge1㉙ 契约：usage 类错误在 --json 下必须出 JSON 信封（禁裸红字）
        r = runner.invoke(
            app, ["liberty", "parse", str(FIXTURE), "--pin", "A", "--json"])
        assert r.exit_code == 2
        payload = json.loads(r.output)
        assert payload["ok"] is False

    def test_parse_failure_exit1(self, tmp_path: Path) -> None:
        r = runner.invoke(app, ["liberty", "parse", str(tmp_path / "no.lib"), "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False

    def test_list_json_envelope(self) -> None:
        r = runner.invoke(app, ["liberty", "list", str(FIXTURE), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert len(payload["cells"]) == 3
        assert payload["cells"][1]["name"] == "BUFX2"

    def test_list_human_output(self) -> None:
        r = runner.invoke(app, ["liberty", "list", str(FIXTURE)])
        assert r.exit_code == 0
        assert "DFFX1" in r.output

    def test_help_hygiene(self) -> None:
        # --help 构建成功（#305 家族守卫面：typer help 字面可渲染）
        for args in (["liberty", "--help"], ["liberty", "parse", "--help"],
                     ["liberty", "list", "--help"]):
            r = runner.invoke(app, args)
            assert r.exit_code == 0, args


# ── 计数链 grep 字面钉（任务书第 5 项）────────────────────────────────────


class TestCountChainLiteralPins:
    def test_domain_file_has_exactly_two_leaves(self) -> None:
        # grep 字面钉：域文件恰两处 @liberty_app.command 装饰器（parse/list）
        src = (Path(__file__).resolve().parents[2] / "src" / "rfauto" / "cli"
               / "domains" / "liberty.py").read_text(encoding="utf-8")
        assert src.count("@liberty_app.command(") == 2
        assert '@liberty_app.command("parse")' in src
        assert '@liberty_app.command("list")' in src

    def test_domain_registered_as_liberty_group(self) -> None:
        # 注册面钉：liberty 顶层组恰 2 叶（parse/list），与计数链 delta 一致
        groups = {info.name: info.typer_instance for info in app.registered_groups}
        assert "liberty" in groups
        names = {cmd.name for cmd in groups["liberty"].registered_commands}
        assert names == {"parse", "list"}
