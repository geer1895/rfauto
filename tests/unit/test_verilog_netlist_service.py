"""Verilog 网表解析服务包装+CLI 薄壳单测（aurora_q Q-X47 席位，2026-11-07）。

覆盖面（任务书 ≥20 条之服务/CLI 半边）：

- service 三函数信封形状（ok/error 两态；errors 恒 list[str]）；
- parse 信封 schema 键集（顶层+topology 按模块）+--no-topology
  派生字段如实 None（spice 家法）；
- 单模块视图（--module 过滤：modules/topology 只含目标模块；不存在
  模块 → error 信封带可用名录）；
- 清单只读面（module_names 序+modules_summary 逐模块计数/顶层候选/
  实例化边/外部单元类型）；
- 文件不可读/词法违规 → error 信封（CLI exit 1）；
- CLI：parse --json 全结构+缺省紧凑面+--module/--no-topology 分支、
  list --json+human、失败路径 JSON 信封同构（#ge1㉙ 契约）、usage 错
  exit 2（缺参数）；
- 计数链（本席不钉总数——绝对数锚归 test_check_numbers/test_cli
  权威共享面，本文件只断言 verilog 域叶数=2 防遮蔽回归）。

单测零网络零真机（夹具只读；错误路径用 tmp_path/不存在路径）。
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.service.verilog_netlist_service import (
    list_verilog_modules,
    parse_verilog_file,
    parse_verilog_module,
)

FIXTURE = Path(__file__).resolve().parents[1] / "unit" / "fixtures" / "verilog" / "sample.v"
runner = CliRunner()

PARSE_TOP_KEYS = {
    "ok", "path", "modules", "module_order", "top_modules",
    "instantiations", "external_instance_types", "directives",
    "warnings", "stats", "topology",
}
TOPOLOGY_KEYS = {
    "module", "net_count", "instance_count", "net_drivers", "net_readers",
    "instance_edges", "orphan_nets", "behavioral_skipped",
    "external_boundary_nets", "tree_depth",
}


# ── service：parse_verilog_file ────────────────────────────────────────────


class TestParseVerilogFile:
    def test_ok_envelope_schema(self) -> None:
        result = parse_verilog_file(FIXTURE)
        assert result["ok"] is True
        assert set(result) == PARSE_TOP_KEYS
        assert result["module_order"] == ["top", "adder", "dff_cell"]
        assert result["stats"]["n_modules"] == 3

    def test_topology_per_module(self) -> None:
        result = parse_verilog_file(FIXTURE)
        topo = result["topology"]
        assert set(topo) == {"top", "adder", "dff_cell"}
        assert set(topo["top"]) == TOPOLOGY_KEYS
        assert topo["top"]["tree_depth"]["depth"] == 4
        assert topo["top"]["orphan_nets"]["undriven"] == ["floating_net"]

    def test_no_topology_field_is_none(self) -> None:
        # --no-topology：派生字段缺席如实 None（非 {} 非 0）
        result = parse_verilog_file(FIXTURE, with_topology=False)
        assert result["ok"] is True
        assert result["topology"] is None

    def test_unreadable_file_error_envelope(self) -> None:
        result = parse_verilog_file("no_such_file.v")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert "不可读" in result["errors"][0]

    def test_lexical_error_envelope(self, tmp_path: Path) -> None:
        bad = tmp_path / "broken.v"
        bad.write_text("module m; /* never closed", encoding="utf-8")
        result = parse_verilog_file(bad)
        assert result["ok"] is False
        assert "块注释未闭合" in result["errors"][0]

    def test_latin1_fallback_decoding(self, tmp_path: Path) -> None:
        # 工具头注释偶发高位字节（非 utf-8）——Latin-1 兜底不炸读取
        f = tmp_path / "latin.v"
        f.write_bytes(
            b"// author: Jos\xe9\nmodule m (input a, output b);\n"
            b"  buf g (b, a);\nendmodule\n")
        result = parse_verilog_file(f)
        assert result["ok"] is True
        assert result["module_order"] == ["m"]


# ── service：parse_verilog_module ──────────────────────────────────────────


class TestParseVerilogModule:
    def test_single_module_view(self) -> None:
        result = parse_verilog_module(FIXTURE, "adder")
        assert result["ok"] is True
        assert result["module"] == "adder"
        assert list(result["modules"]) == ["adder"]
        # 单模块拓扑（非 {name: topo} 映射）
        assert result["topology"]["module"] == "adder"
        assert result["topology"]["tree_depth"]["depth"] == 0

    def test_missing_module_error_lists_available(self) -> None:
        result = parse_verilog_module(FIXTURE, "no_such")
        assert result["ok"] is False
        msg = result["errors"][0]
        assert "no_such" in msg
        assert "top" in msg and "adder" in msg

    def test_module_view_no_topology(self) -> None:
        result = parse_verilog_module(FIXTURE, "top", with_topology=False)
        assert result["ok"] is True
        assert result["topology"] is None


# ── service：list_verilog_modules ──────────────────────────────────────────


class TestListVerilogModules:
    def test_inventory_shape(self) -> None:
        result = list_verilog_modules(FIXTURE)
        assert result["ok"] is True
        assert result["module_names"] == ["top", "adder", "dff_cell"]
        assert result["top_modules"] == ["top", "dff_cell"]
        summary = {s["name"]: s for s in result["modules_summary"]}
        assert summary["top"]["n_instances"] == 8
        assert summary["top"]["n_ports"] == 4
        assert summary["adder"]["n_assigns"] == 3
        assert summary["adder"]["ansi_ports"] is False
        assert "adder" in summary["top"]["instance_types"]

    def test_list_error_envelope(self) -> None:
        result = list_verilog_modules("no_such_file.v")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)


# ── CLI 薄壳 ────────────────────────────────────────────────────────────────


class TestCli:
    def test_parse_json_full_envelope(self) -> None:
        r = runner.invoke(root_app, ["verilog", "parse", str(FIXTURE), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert set(payload) == PARSE_TOP_KEYS
        assert payload["topology"]["top"]["tree_depth"]["depth"] == 4

    def test_parse_human_compact(self) -> None:
        r = runner.invoke(root_app, ["verilog", "parse", str(FIXTURE)])
        assert r.exit_code == 0, r.output
        assert "Verilog" in r.output
        assert "top" in r.output
        assert "floating_net" in r.output  # 拓扑缺省开→孤立网展开

    def test_parse_module_filter_json(self) -> None:
        r = runner.invoke(root_app, [
            "verilog", "parse", str(FIXTURE), "--module", "adder", "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["module"] == "adder"
        assert list(payload["modules"]) == ["adder"]

    def test_parse_no_topology_flag(self) -> None:
        r = runner.invoke(root_app, [
            "verilog", "parse", str(FIXTURE), "--no-topology", "--json"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["topology"] is None

    def test_parse_failure_json_envelope_exit1(self) -> None:
        r = runner.invoke(root_app, ["verilog", "parse", "no_such_file.v",
                                     "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)
        assert len(payload["errors"]) == 1

    def test_parse_failure_human_exit1(self) -> None:
        r = runner.invoke(root_app, ["verilog", "parse", "no_such_file.v"])
        assert r.exit_code == 1
        assert "Verilog 解析失败" in r.output

    def test_parse_missing_module_exit1(self) -> None:
        r = runner.invoke(root_app, [
            "verilog", "parse", str(FIXTURE), "--module", "ghost", "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert "ghost" in payload["errors"][0]

    def test_parse_missing_argument_exit2(self) -> None:
        r = runner.invoke(root_app, ["verilog", "parse"])
        assert r.exit_code == 2

    def test_list_json_envelope(self) -> None:
        r = runner.invoke(root_app, ["verilog", "list", str(FIXTURE), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["module_names"] == ["top", "adder", "dff_cell"]

    def test_list_human_output(self) -> None:
        r = runner.invoke(root_app, ["verilog", "list", str(FIXTURE)])
        assert r.exit_code == 0, r.output
        assert "adder" in r.output
        assert "dff_cell" in r.output

    def test_list_failure_json_exit1(self) -> None:
        r = runner.invoke(root_app, ["verilog", "list", "no_such_file.v",
                                     "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["ok"] is False

    def test_verilog_leaves_in_tree(self) -> None:
        # 本席域形状钉（绝对总数归 test_check_numbers/test_cli 权威共享面；
        # 本钉防同域叶遮蔽/漂移回归）
        from typer.main import get_command

        cmd = get_command(root_app)
        group = cmd.commands.get("verilog")
        assert group is not None, "verilog 顶层域不在 CLI 树"
        assert set(group.commands) == {"parse", "list"}
