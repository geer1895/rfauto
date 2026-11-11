"""IBIS 解析服务+CLI 薄壳单测（aurora_q Q-X46 席位，2026-11-07）。

覆盖面（任务书 ≥20 条之服务/CLI 半边）：
- 服务信封正例：parse 全结构+stats 计数（对返回视图——liberty 同款
  口径）、list 清单（component/model/选择器名录+计数）；
- 过滤面：--component 命中（pins 同步收窄）/未知名 error 信封（附可用
  清单）、--model 命中/未知名 error；
- 裁面开关：include_tables=False 剪表体（stats 同步归零、元数据保留、
  filters 如实声明）；
- 错误归一：文件不可读/语法违规 → error 信封（errors 恒 list[str]）；
- CLI ``rfauto ibis parse|list``：--json 信封、紧凑人读面、--tables
  展开、失败 exit 1（--json 下 JSON 信封，#ge1㉙ 契约）、--help 卫生；
- 计数链 grep 字面钉：域文件内两叶装饰器字面 + CLI 注册面恰 2 叶 +
  help 面板全覆盖（aurora_n wave_ui_c 集合断言同源）。

单测零网络零真机零 runs/ 湖写入（--json 纯读零落盘）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.service.ibis_service import list_ibis_inventory, parse_ibis_file

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ibis" / "sample.ibs"

runner = CliRunner()


# ── 服务信封正例 ────────────────────────────────────────────────────────────


class TestParseEnvelope:
    def test_full_parse_stats(self) -> None:
        result = parse_ibis_file(FIXTURE)
        assert result["ok"] is True
        assert result["path"] == str(FIXTURE)
        assert result["header"]["ibis_ver"] == "3.2"
        # IV 表 1+3+1=5 张 28 行；暂态 2+1=3 张 16 行；共 44 行；
        # n_warnings=R-22 schema 升位批补键（warnings 随视图透传不裁面）
        assert result["stats"] == {
            "n_components": 1, "n_pins": 6, "n_models": 3,
            "n_model_selectors": 1, "n_iv_tables": 5, "n_waveforms": 3,
            "n_table_rows": 44, "n_ramp": 1, "n_warnings": 1,
        }

    def test_schema_keys_stable(self) -> None:
        result = parse_ibis_file(FIXTURE)
        assert {"ok", "path", "header", "components", "models",
                "model_selectors", "pins", "warnings", "stats",
                "filters"} <= set(result)

    def test_warnings_passthrough(self) -> None:
        result = parse_ibis_file(FIXTURE)
        assert len(result["warnings"]) == 1
        assert "OEM" in result["warnings"][0]

    def test_component_filter(self) -> None:
        result = parse_ibis_file(FIXTURE, component="SAMPLE_SOC")
        assert result["ok"] is True
        assert [c["name"] for c in result["components"]] == ["SAMPLE_SOC"]
        assert result["stats"]["n_pins"] == 6
        assert result["filters"]["component"] == "SAMPLE_SOC"

    def test_component_filter_unknown_lists_available(self) -> None:
        result = parse_ibis_file(FIXTURE, component="NOPE")
        assert result["ok"] is False
        assert "NOPE" in result["errors"][0]
        assert "SAMPLE_SOC" in result["errors"][0]

    def test_model_filter(self) -> None:
        result = parse_ibis_file(FIXTURE, model="IO_FAST")
        assert result["ok"] is True
        assert set(result["models"]) == {"IO_FAST"}
        assert result["stats"]["n_models"] == 1
        assert result["stats"]["n_iv_tables"] == 3
        assert result["stats"]["n_waveforms"] == 2

    def test_model_filter_unknown_lists_available(self) -> None:
        result = parse_ibis_file(FIXTURE, model="ZZ")
        assert result["ok"] is False
        assert "ZZ" in result["errors"][0]
        assert "IO_SLOW" in result["errors"][0]

    def test_component_and_model_filter_combined(self) -> None:
        result = parse_ibis_file(
            FIXTURE, component="SAMPLE_SOC", model="PD_MODEL")
        assert result["ok"] is True
        assert set(result["models"]) == {"PD_MODEL"}
        assert result["stats"]["n_iv_tables"] == 1

    def test_include_tables_false_strips_bodies(self) -> None:
        result = parse_ibis_file(FIXTURE, include_tables=False)
        m = result["models"]["IO_FAST"]
        assert "tables" not in m
        assert "waveforms" not in m
        assert "ramp" not in m
        assert m["model_type"] == "Output"  # 元数据保留
        assert result["stats"]["n_iv_tables"] == 0  # 对返回视图计数
        assert result["stats"]["n_table_rows"] == 0
        assert result["filters"]["tables"] is False

    def test_default_includes_tables(self) -> None:
        result = parse_ibis_file(FIXTURE)
        t = result["models"]["IO_FAST"]["tables"]["pulldown"]
        assert t["voltage"][0] == -1.5
        assert result["filters"]["tables"] is True


class TestListEnvelope:
    def test_list_full(self) -> None:
        result = list_ibis_inventory(FIXTURE)
        assert result["ok"] is True
        assert result["components"][0] == {
            "name": "SAMPLE_SOC", "manufacturer": "rfauto", "n_pins": 6}
        rows = {m["name"]: m for m in result["models"]}
        assert set(rows) == {"PD_MODEL", "IO_FAST", "IO_SLOW"}
        assert rows["PD_MODEL"]["model_type"] == "Input"
        assert rows["PD_MODEL"]["table_names"] == ["gnd_clamp"]
        assert rows["IO_FAST"]["table_names"] == [
            "pullup", "pulldown", "power_clamp"]
        assert rows["IO_FAST"]["n_waveforms"] == 2
        assert rows["IO_FAST"]["n_table_rows"] == 30  # 18 IV + 12 波形
        assert rows["IO_SLOW"]["n_table_rows"] == 8  # 4 IV + 4 波形
        assert rows["IO_FAST"]["has_ramp"] is True
        assert rows["IO_SLOW"]["has_ramp"] is False
        assert result["model_selector_names"] == ["IO_SEL"]
        assert result["stats"]["n_table_rows"] == 44

    def test_missing_file_error_envelope(self, tmp_path: Path) -> None:
        result = parse_ibis_file(tmp_path / "nope.ibs")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert "不可读" in result["errors"][0]
        assert list_ibis_inventory(tmp_path / "nope.ibs")["ok"] is False

    def test_malformed_file_error_envelope(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.ibs"
        bad.write_text(
            "[Component] C\n[Model] M\nModel_type Input\n",
            encoding="utf-8")  # 缺 [End]
        result = parse_ibis_file(bad)
        assert result["ok"] is False
        assert "IBIS 解析失败" in result["errors"][0]
        assert list_ibis_inventory(bad)["ok"] is False


# ── CLI 薄壳（ibis parse/list 两叶）────────────────────────────────────────


class TestCliIbis:
    def test_parse_json_envelope(self) -> None:
        r = runner.invoke(app, ["ibis", "parse", str(FIXTURE), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["header"]["file_name"] == "sample.ibs"
        assert payload["stats"]["n_models"] == 3

    def test_parse_default_compact_no_table_bodies(self) -> None:
        # 缺省紧凑面：模型元数据在、查找表体不在
        r = runner.invoke(app, ["ibis", "parse", str(FIXTURE), "--json"])
        payload = json.loads(r.output)
        assert "tables" not in payload["models"]["IO_FAST"]
        assert payload["models"]["IO_FAST"]["model_type"] == "Output"

    def test_parse_tables_flag_expands_bodies(self) -> None:
        r = runner.invoke(
            app, ["ibis", "parse", str(FIXTURE), "--model", "IO_FAST",
                  "--tables", "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        t = payload["models"]["IO_FAST"]["tables"]["pulldown"]
        assert t["n_rows"] == 7
        assert t["typ"][-1] == pytest.approx(0.078)
        assert payload["stats"]["n_iv_tables"] == 3

    def test_parse_component_filter_json(self) -> None:
        r = runner.invoke(
            app, ["ibis", "parse", str(FIXTURE), "--component", "SAMPLE_SOC",
                  "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["components"][0]["name"] == "SAMPLE_SOC"

    def test_parse_human_output(self) -> None:
        r = runner.invoke(app, ["ibis", "parse", str(FIXTURE)])
        assert r.exit_code == 0
        assert "SAMPLE_SOC" in r.output
        assert "IO_FAST" in r.output
        assert "sample.ibs" in r.output

    def test_parse_human_tables_flag(self) -> None:
        r = runner.invoke(app, ["ibis", "parse", str(FIXTURE), "--tables"])
        assert r.exit_code == 0
        assert "rows=7" in r.output

    def test_parse_failure_exit1_json_envelope(self, tmp_path: Path) -> None:
        # #ge1㉙ 契约：--json 下失败路径必须输出 JSON 信封（禁裸红字）
        r = runner.invoke(app, ["ibis", "parse", str(tmp_path / "no.ibs"),
                                "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False

    def test_parse_unknown_model_exit1(self) -> None:
        r = runner.invoke(app, ["ibis", "parse", str(FIXTURE), "--model",
                                "NOPE", "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert "NOPE" in payload["errors"][0]

    def test_list_json_envelope(self) -> None:
        r = runner.invoke(app, ["ibis", "list", str(FIXTURE), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert len(payload["models"]) == 3
        assert payload["models"][1]["name"] == "IO_FAST"
        assert payload["model_selector_names"] == ["IO_SEL"]

    def test_list_human_output(self) -> None:
        r = runner.invoke(app, ["ibis", "list", str(FIXTURE)])
        assert r.exit_code == 0
        assert "IO_SLOW" in r.output
        assert "IO_SEL" in r.output

    def test_list_failure_exit1(self, tmp_path: Path) -> None:
        r = runner.invoke(app, ["ibis", "list", str(tmp_path / "no.ibs")])
        assert r.exit_code == 1

    def test_help_hygiene(self) -> None:
        # --help 构建成功（#305 家族守卫面：typer help 字面可渲染）
        for args in (["ibis", "--help"], ["ibis", "parse", "--help"],
                     ["ibis", "list", "--help"]):
            r = runner.invoke(app, args)
            assert r.exit_code == 0, args


# ── 计数链 grep 字面钉（任务书第 5 项）────────────────────────────────────


class TestCountChainLiteralPins:
    def test_domain_file_has_exactly_two_leaves(self) -> None:
        # grep 字面钉：域文件恰两处 @ibis_app.command 装饰器（parse/list）
        src = (Path(__file__).resolve().parents[2] / "src" / "rfauto" / "cli"
               / "domains" / "ibis.py").read_text(encoding="utf-8")
        assert src.count("@ibis_app.command(") == 2
        assert '@ibis_app.command("parse")' in src
        assert '@ibis_app.command("list")' in src

    def test_domain_registered_as_ibis_group(self) -> None:
        # 注册面钉：ibis 顶层组恰 2 叶（parse/list），与计数链 delta 一致
        groups = {info.name: info.typer_instance for info in app.registered_groups}
        assert "ibis" in groups
        names = {cmd.name for cmd in groups["ibis"].registered_commands}
        assert names == {"parse", "list"}

    def test_help_panel_registered(self) -> None:
        # aurora_n wave_ui_c 全覆盖断言同源：新顶层命令必须挂面板（否则
        # test_apply_panels_idempotent_and_rendered 的"未挂面板"红）
        from rfauto.cli.help_groups import HELP_PANEL_OF

        assert HELP_PANEL_OF.get("ibis") == "数据与知识"
