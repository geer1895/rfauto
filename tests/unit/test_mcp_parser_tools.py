"""EDA 格式解析八域 MCP 工具组单测（aurora_q Q-X69 席位，2026-11-08）。

覆盖面（任务书预声明：逐工具 ≥2 测=入参校验+信封成功路径；路径不存在
错误路径全覆盖 8 工具）：
- 信封成功路径：经 fastmcp call_tool 真调用（#270 家法：死壳只在调用
  期才炸），复用仓内既有 fixtures（liberty/citi/sdc/ibis/verilog/drc
  六域）+ 内联最小 SPICE/LVS 网表（tmp_path 落盘，#144 家法零 runs/
  湖写入）；
- 裁面/过滤旋钮：liberty cell/pin、ibis component、verilog
  with_topology、citi max_values 截断显式声明、spice include_topology；
- 错误路径：文件不存在（8 工具全覆盖）、词表外 flavor/fmt、LVS 单侧
  缺失与负容差、liberty pin 缺 cell——全部 ok=False errors 信封零抛出；
- 与 CLI 同源对拍（可选面抽一）：spice MCP 透传结果与 service 直调
  逐字节相等（零逻辑转发钉）。

工具注册序/计数锚不修（171→179 计数链归主代合流统一——本文件零计数
断言，只测行为）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

REPO_TESTS = Path(__file__).resolve().parents[1]
UNIT_FIXTURES = Path(__file__).resolve().parent / "fixtures"

FIXTURE_LIBERTY = REPO_TESTS / "fixtures" / "liberty" / "sample.lib"
FIXTURE_CITI = UNIT_FIXTURES / "citi" / "sample_citi.cti"
FIXTURE_SDC = UNIT_FIXTURES / "sdc" / "sample.sdc"
FIXTURE_IBIS = UNIT_FIXTURES / "ibis" / "sample.ibs"
FIXTURE_VERILOG = UNIT_FIXTURES / "verilog" / "sample.v"
FIXTURE_DRC = UNIT_FIXTURES / "drc" / "sample_rules.json"

#: 最小 ngspice RC 低通（与 test_spice_netlist_service 同源口径）。
_NGSPICE_RC = """RC lowpass divider
V1 in 0 DC 0 AC 1
R1 in out 1k
C1 out 0 1u
.end
"""

#: LVS MATCH 对（layout 与 schematic 同一电路，逐字节相同）。
_LVS_A = """RC ladder
P1 in 0 port=1 z0=50
R1 in n1 1k
C1 n1 0 2p
.end
"""


@pytest.fixture(autouse=True)
def _isolated_cwd(isolated):
    """cwd 隔离（#144 家法，test_mcp_server 同款）：解析工具按显式路径
    直读文件本不触 runs/，隔离体单源化防未来任何 cwd 相对路径面。"""


@pytest.fixture()
def mcp_server():
    from rfauto.mcp_server import mcp
    return mcp


def _extract_result(tool_result) -> dict[str, Any]:
    """从 fastmcp ToolResult 提取 dict（test_mcp_server 同款分流）。"""
    if hasattr(tool_result, "structured_content") and tool_result.structured_content is not None:
        return tool_result.structured_content
    if hasattr(tool_result, "content") and tool_result.content:
        return json.loads(tool_result.content[0].text)
    return json.loads(str(tool_result))


def _call(mcp_server, tool_name: str, arguments: dict) -> dict[str, Any]:
    """经 fastmcp call_tool 真调用（#270：死壳只在调用期才炸）。"""
    return _extract_result(
        asyncio.run(mcp_server.call_tool(tool_name, arguments)))


def _write(tmp_path: Path, name: str, text: str) -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── SPICE ───────────────────────────────────────────────────────────────────


class TestSpiceNetlistParse:
    def test_ok_envelope_structured_view(self, mcp_server, tmp_path):
        path = _write(tmp_path, "rc_lpf.cir", _NGSPICE_RC)
        data = _call(mcp_server, "spice_netlist_parse", {"path": path})
        assert data["ok"] is True, data.get("errors")
        assert data["schema"] == "spice_netlist/1.0"
        assert data["flavor"] == "ngspice"
        assert data["flavor_detected"] is True
        assert data["summary"]["n_elements"] == 3
        assert data["path"] == path
        assert data["topology"] is not None
        # AU-2 信封合规：成功面不带 errors 键
        assert "errors" not in data

    def test_bad_flavor_error_envelope(self, mcp_server, tmp_path):
        path = _write(tmp_path, "rc.cir", _NGSPICE_RC)
        data = _call(mcp_server, "spice_netlist_parse",
                     {"path": path, "flavor": "ltspice"})
        assert data["ok"] is False
        assert data["errors"]
        assert "flavor" in data["errors"][0]

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        data = _call(mcp_server, "spice_netlist_parse",
                     {"path": str(tmp_path / "nope.cir")})
        assert data["ok"] is False
        assert isinstance(data["errors"], list)
        assert "不存在" in data["errors"][0]

    def test_passthrough_matches_service_direct_call(
            self, mcp_server, tmp_path):
        """零逻辑转发钉：MCP 透传结果与 service 直调逐键相等。"""
        from rfauto.service.spice_netlist_service import parse_netlist_file
        path = _write(tmp_path, "rc.cir", _NGSPICE_RC)
        via_mcp = _call(mcp_server, "spice_netlist_parse",
                        {"path": path, "include_topology": False})
        via_service = parse_netlist_file(path, include_topology=False)
        assert via_mcp == via_service
        assert via_mcp["topology"] is None
        assert via_mcp["summary"]["mna_size"] is None  # 缺席哨兵 None 非 0


# ── Liberty ─────────────────────────────────────────────────────────────────


class TestLibertyParse:
    def test_ok_envelope_library_view(self, mcp_server):
        data = _call(mcp_server, "liberty_parse", {"path": str(FIXTURE_LIBERTY)})
        assert data["ok"] is True, data.get("errors")
        assert data["library"] == "sample_lib_rfauto"
        assert set(data["cells"]) == {"INVX1", "BUFX2", "DFFX1"}
        assert data["stats"]["n_cells"] == 3
        assert data["filters"] == {"cell": None, "pin": None,
                                   "include_timing": True,
                                   "include_power": True}

    def test_cell_pin_filter_view(self, mcp_server):
        data = _call(mcp_server, "liberty_parse", {
            "path": str(FIXTURE_LIBERTY), "cell": "INVX1", "pin": "A"})
        assert data["ok"] is True
        assert set(data["cells"]) == {"INVX1"}
        assert set(data["cells"]["INVX1"]["pins"]) == {"A"}
        assert data["stats"]["n_pins"] == 1

    def test_pin_without_cell_error_envelope(self, mcp_server):
        data = _call(mcp_server, "liberty_parse", {
            "path": str(FIXTURE_LIBERTY), "pin": "A"})
        assert data["ok"] is False
        assert data["errors"]
        assert "pin" in data["errors"][0]

    def test_unknown_cell_error_lists_available(self, mcp_server):
        data = _call(mcp_server, "liberty_parse", {
            "path": str(FIXTURE_LIBERTY), "cell": "NOPE"})
        assert data["ok"] is False
        assert "NOPE" in data["errors"][0]
        assert "INVX1" in data["errors"][0]  # 可用清单如实回显

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        data = _call(mcp_server, "liberty_parse",
                     {"path": str(tmp_path / "nope.lib")})
        assert data["ok"] is False
        assert data["errors"]


# ── CITI ────────────────────────────────────────────────────────────────────


class TestCitiInfo:
    def test_ok_envelope_packages(self, mcp_server):
        data = _call(mcp_server, "citi_info", {"path": str(FIXTURE_CITI)})
        assert data["ok"] is True, data.get("errors")
        assert data["n_packages"] == 1
        assert data["summary"][0]["segment_names"] == ["S[1,1]", "PortZ[1]"]
        seg = data["packages"][0]["segments"][0]
        assert len(seg["dependent_vars"][0]["values"]) == 5
        assert "values_truncated" not in seg["dependent_vars"][0]

    def test_max_values_truncation_declared(self, mcp_server):
        data = _call(mcp_server, "citi_info",
                     {"path": str(FIXTURE_CITI), "max_values": 2})
        assert data["ok"] is True
        dep = data["packages"][0]["segments"][0]["dependent_vars"][0]
        assert len(dep["values"]) == 2
        assert dep["values_truncated"] is True  # 截断显式声明不冒充完整
        full = _call(mcp_server, "citi_info", {"path": str(FIXTURE_CITI)})
        assert len(
            full["packages"][0]["segments"][0]["dependent_vars"][0][
                "values"]) == 5  # 全量计数对照

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        data = _call(mcp_server, "citi_info",
                     {"path": str(tmp_path / "nope.cti")})
        assert data["ok"] is False
        assert "不存在" in data["errors"][0]


# ── SDC ─────────────────────────────────────────────────────────────────────


class TestSdcParse:
    def test_ok_envelope_constraint_view(self, mcp_server):
        data = _call(mcp_server, "sdc_parse", {"path": str(FIXTURE_SDC)})
        assert data["ok"] is True, data.get("errors")
        assert data["stats"]["n_clocks"] == 4
        assert set(data) >= {"ok", "path", "clocks", "delays", "paths",
                             "constraints", "objects", "variables",
                             "commands", "warnings", "stats"}
        assert data["constraints"]["false_paths"]

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        data = _call(mcp_server, "sdc_parse",
                     {"path": str(tmp_path / "nope.sdc")})
        assert data["ok"] is False
        assert data["errors"] and "不可读" in data["errors"][0]


# ── IBIS ────────────────────────────────────────────────────────────────────


class TestIbisParse:
    def test_ok_envelope_buffer_view(self, mcp_server):
        data = _call(mcp_server, "ibis_parse", {"path": str(FIXTURE_IBIS)})
        assert data["ok"] is True, data.get("errors")
        assert data["components"][0]["name"] == "SAMPLE_SOC"
        assert "PD_MODEL" in data["models"]
        assert data["stats"]["n_components"] == 1

    def test_component_filter_narrows_pins(self, mcp_server):
        data = _call(mcp_server, "ibis_parse", {
            "path": str(FIXTURE_IBIS), "component": "SAMPLE_SOC"})
        assert data["ok"] is True
        assert data["stats"]["n_components"] == 1
        assert data["filters"]["component"] == "SAMPLE_SOC"

    def test_unknown_component_error_envelope(self, mcp_server):
        data = _call(mcp_server, "ibis_parse", {
            "path": str(FIXTURE_IBIS), "component": "NOPE"})
        assert data["ok"] is False
        assert "NOPE" in data["errors"][0]
        assert "SAMPLE_SOC" in data["errors"][0]  # 可用清单如实回显

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        data = _call(mcp_server, "ibis_parse",
                     {"path": str(tmp_path / "nope.ibs")})
        assert data["ok"] is False
        assert data["errors"]


# ── Verilog ─────────────────────────────────────────────────────────────────


class TestVerilogNetlistParse:
    def test_ok_envelope_modules_and_topology(self, mcp_server):
        data = _call(mcp_server, "verilog_netlist_parse",
                     {"path": str(FIXTURE_VERILOG)})
        assert data["ok"] is True, data.get("errors")
        assert data["module_order"] == ["top", "adder", "dff_cell"]
        assert set(data["topology"]) == {"top", "adder", "dff_cell"}
        assert data["stats"]["n_modules"] == 3

    def test_with_topology_false_none_sentinel(self, mcp_server):
        data = _call(mcp_server, "verilog_netlist_parse", {
            "path": str(FIXTURE_VERILOG), "with_topology": False})
        assert data["ok"] is True
        assert data["topology"] is None  # 派生字段缺席哨兵 None 非 0

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        data = _call(mcp_server, "verilog_netlist_parse",
                     {"path": str(tmp_path / "nope.v")})
        assert data["ok"] is False
        assert data["errors"]


# ── DRC ─────────────────────────────────────────────────────────────────────


class TestDrcRulesParse:
    def test_ok_envelope_rules_view(self, mcp_server):
        data = _call(mcp_server, "drc_rules_parse",
                     {"path": str(FIXTURE_DRC)})
        assert data["ok"] is True, data.get("errors")
        assert data["format"] == "json"
        assert data["metadata"]["n_rules"] == 12
        assert data["rules"] and data["rules"][0]["name"]

    def test_bad_fmt_error_envelope(self, mcp_server):
        data = _call(mcp_server, "drc_rules_parse",
                     {"path": str(FIXTURE_DRC), "fmt": "yaml"})
        assert data["ok"] is False
        assert data["errors"]

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        data = _call(mcp_server, "drc_rules_parse",
                     {"path": str(tmp_path / "nope.json")})
        assert data["ok"] is False
        assert data["errors"]


# ── LVS ─────────────────────────────────────────────────────────────────────


class TestLvsCompareFiles:
    def test_identical_pair_match_verdict(self, mcp_server, tmp_path):
        layout = _write(tmp_path, "layout.cir", _LVS_A)
        schematic = _write(tmp_path, "schematic.cir", _LVS_A)
        data = _call(mcp_server, "lvs_compare_files", {
            "layout_path": layout, "schematic_path": schematic})
        assert data["ok"] is True, data.get("errors")
        assert data["verdict"] == "MATCH"
        assert data["score"] == pytest.approx(1.0)
        assert data["layout"]["path"] == layout
        assert data["schematic"]["path"] == schematic

    def test_param_tolerance_echo(self, mcp_server, tmp_path):
        layout = _write(tmp_path, "l.cir", _LVS_A)
        schematic = _write(tmp_path, "s.cir", _LVS_A)
        data = _call(mcp_server, "lvs_compare_files", {
            "layout_path": layout, "schematic_path": schematic,
            "tolerance": 0.05, "rf": True})
        assert data["ok"] is True
        assert data["params"] == {"tolerance": 0.05, "rf": True,
                                  "format": "auto",
                                  "iso_step_budget": data["params"][
                                      "iso_step_budget"]}

    def test_negative_tolerance_error_envelope(self, mcp_server, tmp_path):
        layout = _write(tmp_path, "l.cir", _LVS_A)
        schematic = _write(tmp_path, "s.cir", _LVS_A)
        data = _call(mcp_server, "lvs_compare_files", {
            "layout_path": layout, "schematic_path": schematic,
            "tolerance": -1.0})
        assert data["ok"] is False
        assert data["errors"] and "tolerance" in data["errors"][0]

    def test_missing_one_side_error_attributed(self, mcp_server, tmp_path):
        """单侧缺失：errors 带 side 归属（layout/schematic 如实点名）。"""
        schematic = _write(tmp_path, "s.cir", _LVS_A)
        data = _call(mcp_server, "lvs_compare_files", {
            "layout_path": str(tmp_path / "nope.cir"),
            "schematic_path": schematic})
        assert data["ok"] is False
        assert data["errors"] and "layout" in data["errors"][0]

    def test_bad_fmt_error_envelope(self, mcp_server, tmp_path):
        layout = _write(tmp_path, "l.cir", _LVS_A)
        schematic = _write(tmp_path, "s.cir", _LVS_A)
        data = _call(mcp_server, "lvs_compare_files", {
            "layout_path": layout, "schematic_path": schematic,
            "fmt": "edif"})
        assert data["ok"] is False
        assert data["errors"]


# ── 注册面健全性（不计数的轻量钉：名字在册、Args 与签名对齐） ────────────────


class TestParserToolsRegistration:
    def test_eight_tools_registered(self, mcp_server):
        import asyncio
        tools = asyncio.run(mcp_server.list_tools())
        names = {t.name for t in tools}
        assert {
            "spice_netlist_parse", "liberty_parse", "citi_info", "sdc_parse",
            "ibis_parse", "verilog_netlist_parse", "drc_rules_parse",
            "lvs_compare_files",
        } <= names

    @pytest.mark.parametrize("tool_name", [
        "spice_netlist_parse", "liberty_parse", "citi_info", "sdc_parse",
        "ibis_parse", "verilog_netlist_parse", "drc_rules_parse",
        "lvs_compare_files",
    ])
    def test_docstring_args_match_signature(self, mcp_server, tool_name):
        """Args 段覆盖全部真实参数且无幽灵参数（一致性门同款口径）。"""
        import asyncio

        from tests.unit.test_mcp_tool_consistency import (
            _documented_args,
            _schema_params,
        )
        tools = asyncio.run(mcp_server.list_tools())
        tool = {t.name: t for t in tools}[tool_name]
        documented = set(_documented_args(tool.fn))
        assert documented == _schema_params(tool), (tool_name, documented)
