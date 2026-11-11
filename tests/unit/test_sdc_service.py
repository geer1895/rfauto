"""SDC 解析服务包装+CLI 薄壳单测（aurora_q Q-X36 席位，2026-11-07）。

覆盖面（任务书 ≥20 条之服务/CLI 半边）：
- service 两函数信封形状（ok/error 三态；errors 恒 list[str]）；
- parse 信封 schema 键集（顶层+constraints 八桶+objects 五类）；
- 清单只读面（command_names 序+command_counts/clocks/counts/
  object_counts/variables）；
- 文件不可读/词法违规 → error 信封（CLI exit 1）；
- CLI：parse --json 全结构+缺省紧凑面+四展开旗标 human 分支、list
  --json+human、失败路径 JSON 信封同构（#ge1㉙ 契约）、usage 错
  exit 2（缺参数）；
- 计数链（本席不钉总数——绝对数锚归 test_check_numbers/test_cli 权威
  共享面，本文件只断言 sdc 域叶数=2 防遮蔽回归）。

单测零网络零真机（夹具只读；错误路径用内联/不存在路径，不写盘）。
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.service.sdc_service import (
    CONSTRAINT_BUCKETS,
    list_sdc_commands,
    parse_sdc_file,
)

FIXTURE = Path(__file__).resolve().parents[1] / "unit" / "fixtures" / "sdc" / "sample.sdc"
runner = CliRunner()

PARSE_TOP_KEYS = {
    "ok", "path", "clocks", "delays", "paths", "constraints",
    "objects", "variables", "commands", "warnings", "stats",
}


# ── service：parse_sdc_file ────────────────────────────────────────────────


class TestParseSdcFile:
    def test_ok_envelope_schema(self) -> None:
        result = parse_sdc_file(FIXTURE)
        assert result["ok"] is True
        assert set(result) == PARSE_TOP_KEYS
        assert set(result["constraints"]) == set(CONSTRAINT_BUCKETS)
        assert result["stats"]["n_clocks"] == 4

    def test_constraints_buckets_populated(self) -> None:
        result = parse_sdc_file(FIXTURE)
        cons = result["constraints"]
        assert len(cons["loads"]) == 2
        assert len(cons["driving_cells"]) == 1
        assert len(cons["fanout_loads"]) == 1
        assert len(cons["case_analyses"]) == 2
        assert len(cons["false_paths"]) == 1
        assert len(cons["multicycles"]) == 1
        assert len(cons["clock_latency"]) == 1
        assert len(cons["clock_uncertainty"]) == 1

    def test_missing_file_error_envelope(self, tmp_path: Path) -> None:
        result = parse_sdc_file(tmp_path / "nope.sdc")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert len(result["errors"]) == 1
        assert "SDC 文件不可读" in result["errors"][0]

    def test_syntax_error_error_envelope(self, tmp_path: Path) -> None:
        bad = tmp_path / "broken.sdc"
        bad.write_text('create_clock -name "unclosed', encoding="utf-8")
        result = parse_sdc_file(bad)
        assert result["ok"] is False
        assert "SDC 解析失败" in result["errors"][0]
        assert "引号词未闭合" in result["errors"][0]

    def test_latin1_fallback_readable(self, tmp_path: Path) -> None:
        data = b"set x caf\xc3\xa9" + b"\xff\xfe"
        p = tmp_path / "latin.sdc"
        p.write_bytes(data)  # 高位字节非 utf-8 序列 → Latin-1 兜底
        result = parse_sdc_file(p)
        assert result["ok"] is True


# ── service：list_sdc_commands ─────────────────────────────────────────────


class TestListSdcCommands:
    def test_list_envelope_shape(self) -> None:
        result = list_sdc_commands(FIXTURE)
        assert result["ok"] is True
        assert set(result) >= {
            "path", "command_names", "command_counts", "clocks", "counts",
            "object_counts", "variables", "warnings", "stats",
        }

    def test_list_command_inventory(self) -> None:
        result = list_sdc_commands(FIXTURE)
        counts = result["command_counts"]
        assert counts["create_clock"] == 2
        assert counts["create_generated_clock"] == 2
        assert counts["set_input_delay"] == 3
        assert counts["set_output_delay"] == 2
        assert counts["set_case_analysis"] == 2
        assert counts["current_design"] == 1
        # 名录按注册序去重
        names = result["command_names"]
        assert len(names) == len(counts)
        assert names[0] == "set"

    def test_list_counts_and_objects(self) -> None:
        result = list_sdc_commands(FIXTURE)
        counts = result["counts"]
        assert counts["clocks"] == 4
        assert counts["delays"] == 5
        assert counts["paths"] == 3
        assert counts["warnings"] == 1
        # objects 桶=顶层独立访问器命令（每命令一条 spec；内联访问器归
        # 各约束条目自带的 objects spec，不进桶）
        assert result["object_counts"]["ports"] == 1

    def test_list_missing_file_error(self, tmp_path: Path) -> None:
        result = list_sdc_commands(tmp_path / "nope.sdc")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)


# ── CLI：sdc parse / sdc list ──────────────────────────────────────────────


class TestCliSdc:
    def test_parse_json_full_envelope(self) -> None:
        r = runner.invoke(root_app, ["sdc", "parse", str(FIXTURE), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert set(payload) == PARSE_TOP_KEYS
        assert payload["clocks"][0]["name"] == "sys_clk"
        assert payload["stats"]["n_delays"] == 5

    def test_parse_default_compact_output(self) -> None:
        r = runner.invoke(root_app, ["sdc", "parse", str(FIXTURE)])
        assert r.exit_code == 0, r.output
        assert "sys_clk" not in r.output  # 紧凑面不展开节
        assert "commands=25" in r.output

    def test_parse_section_flags_expand_human(self) -> None:
        r = runner.invoke(root_app, [
            "sdc", "parse", str(FIXTURE),
            "--clocks", "--timing", "--paths", "--constraints"])
        assert r.exit_code == 0, r.output
        assert "sys_clk" in r.output
        assert "BUFX4" in r.output
        assert "false_path" in r.output
        assert "multicycle" in r.output

    def test_parse_failure_json_envelope_exit1(self) -> None:
        r = runner.invoke(root_app, ["sdc", "parse", "no_such_file.sdc",
                                     "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)
        assert len(payload["errors"]) == 1

    def test_parse_failure_human_exit1(self) -> None:
        r = runner.invoke(root_app, ["sdc", "parse", "no_such_file.sdc"])
        assert r.exit_code == 1
        assert "SDC 解析失败" in r.output

    def test_parse_missing_argument_exit2(self) -> None:
        r = runner.invoke(root_app, ["sdc", "parse"])
        assert r.exit_code == 2

    def test_parse_syntax_error_json_envelope_exit1(self, tmp_path: Path) -> None:
        bad = tmp_path / "broken.sdc"
        bad.write_text("create_clock {unclosed", encoding="utf-8")
        r = runner.invoke(root_app, ["sdc", "parse", str(bad), "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert "花括号词未闭合" in payload["errors"][0]

    def test_list_json_envelope(self) -> None:
        r = runner.invoke(root_app, ["sdc", "list", str(FIXTURE), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["counts"]["clocks"] == 4
        assert payload["command_counts"]["create_clock"] == 2

    def test_list_human_output(self) -> None:
        r = runner.invoke(root_app, ["sdc", "list", str(FIXTURE)])
        assert r.exit_code == 0, r.output
        assert "sys_clk" in r.output
        assert "div2_clk" in r.output

    def test_sdc_leaves_in_tree(self) -> None:
        # 本席域形状钉（绝对总数归 test_check_numbers/test_cli 权威共享面；
        # 本钉防同域叶遮蔽/漂移回归）
        from typer.main import get_command

        cmd = get_command(root_app)
        sdc_group = cmd.commands.get("sdc")
        assert sdc_group is not None, "sdc 顶层域不在 CLI 树"
        assert set(sdc_group.commands) == {"parse", "list"}
