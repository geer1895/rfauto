"""封装/测试封装域 MCP 工具组单测（aurora_q Q-X85 四批小席，2026-11-08）。

覆盖面（任务书预声明：每工具 ≥2 测=成功+路径不存在）：
- 信封成功路径：经 fastmcp call_tool 真调用（#270 家法：死壳只在调用
  期才炸），全部夹具 tmp_path 内程序化合成（ODB++ 目录树 builder 只读
  借用 tests/unit/test_odbpp_parser.py 的 build_odb_tree 构造函数；
  BSDL 内嵌小文本照抄 test_bsdl_parser.py SAMPLE_BSDL 主夹具最小版
  ——#144 家法零 runs/ 湖写入）；
- 查询未命中错误路径：bsdl_boundary_detail 不存在 port——ok=False
  errors 信封随附可用 port 名录零抛出；
- port 过滤旋钮：bsdl_boundary_detail port="out_b"（output3 经控制链
  关联 control_cells）vs port=None（全量平坦清单）；
- 错误路径：文件/目录不存在（3 工具全覆盖）——ok=False errors 信封
  零抛出；
- 注册面健全性（不计数的轻量钉：名字在册、Args 与签名对齐）。

工具注册序/计数锚不修（197→200 计数链归主代合流统一——本文件零计数
断言，只测行为；171 锚锤+金快照为 Q-W9-3 时点已知锚红，aurora_q 各
批如实挂账）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

#: ODB++ 目录树 builder（只读借用既有夹具构造函数——Q-X68 同源语料：
#: matrix 5 层声明/pcb 单 step/cadnet 3 net 4 点/NC_NET 空 net 命名面）。
from tests.unit.test_odbpp_parser import build_odb_tree

# ── BSDL 主夹具（照抄 tests/unit/test_bsdl_parser.py SAMPLE_BSDL 最小
#    版：entity DEMO_IC/TAP 5/指令 4/边界 8 单元含 output3 控制链） ────────

SAMPLE_BSDL = """\
-- demo BSDL: aurora_q Q-X77 fixture
entity DEMO_IC is
  generic (PHYSICAL_PIN_MAP : string := "PKG_A");

  port (
    TCK  : in bit;
    TMS  : in bit;
    TDI  : in bit;
    TDO  : out bit;
    TRST : in bit;
    clk, en : in bit;
    data : inout bit_vector(0 to 1);
    out_a, out_b : out bit
  );

  use STD_1149_1_1994.all;

  attribute COMPONENT_CONFORMANCE of DEMO_IC : entity is "STD_1149_1_1993";
  attribute PIN_MAP of DEMO_IC : entity is PHYSICAL_PIN_MAP;

  constant PKG_A : PIN_MAP_STRING :=
    "TCK:1, data:(P2,P3), clk:J1, vdd:(A1,B1)";

  attribute TAP_SCAN_CLOCK of TCK : signal is (20.0e6, BOTH);
  attribute INSTRUCTION_LENGTH of DEMO_IC : entity is 4;
  attribute INSTRUCTION_OPCODE of DEMO_IC : entity is
    "EXTEST=0000, SAMPLE=0001, IDCODE=0010, BYPASS=1111";
  attribute INSTRUCTION_CAPTURE of DEMO_IC : entity is "0001";
  attribute IDCODE_REGISTER of DEMO_IC : entity is
    "0001" &
    "0101010101010101" &
    "00000110111" &
    "1";
  attribute REGISTER_ACCESS of DEMO_IC : entity is
    "BOUNDARY (EXTEST, SAMPLE), DEVICE_ID (IDCODE)";
  attribute BOUNDARY_LENGTH of DEMO_IC : entity is 8;
  attribute BOUNDARY_REGISTER of DEMO_IC : entity is
    "0 (BC_1, *, controlr, 0), " &
    "1 (BC_4, clk, input, X), " &
    "2 (BC_4, en, input, X), " &
    "3 (BC_1, out_a, output3, X, 0, 1, Z), " &
    "4 (BC_1, *, control, 1), " &
    "5 (BC_1, out_b, output3, X, 4, 0, Z), " &
    "6 (BC_7, data(0), bidir, X, 4, 0, Z), " &
    "7 (BC_0, *, internal, X)";
end DEMO_IC;
"""


# ── 基建（test_mcp_parser_queries 同款） ────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_cwd(isolated):
    """cwd 隔离（#144 家法，前三批同款）：查询工具按显式路径直读文件本
    不触 runs/，隔离体单源化防未来任何 cwd 相对路径面。"""


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


# ── ODB++ 报告（目录树成功面+目录不存在） ───────────────────────────────────


class TestOdbppReport:
    def test_ok_envelope_full_tree(self, mcp_server, tmp_path):
        root = build_odb_tree(tmp_path / "job")
        data = _call(mcp_server, "odbpp_report", {"dir_path": str(root)})
        assert data["ok"] is True, data.get("errors")
        assert "errors" not in data  # AU-1 信封合规：成功面不带 errors 键
        assert data["kind"] == "odbpp_report"
        assert data["matrix_kind"] == "steps"
        assert data["n_layers_declared"] == 5
        assert data["n_layers_on_disk"] == 5
        assert data["model_units"] == "MM"
        assert data["n_steps"] == 1
        step = data["steps"][0]
        assert step["name"] == "pcb"
        assert step["stack_aligned"] is True
        assert step["n_pad_refs"] == 2  # f.cu P 2（b.cu/edge.cuts 零 P 记录）
        assert step["n_nets"] == 3
        assert step["n_net_points"] == 4
        assert data["empty_nets"] == ["NC_NET"]  # 空 net 双清单聚合
        assert data["n_empty_nets"] == 1

    def test_missing_dir_error_envelope(self, mcp_server, tmp_path):
        data = _call(mcp_server, "odbpp_report",
                     {"dir_path": str(tmp_path / "nope_job")})
        assert data["ok"] is False
        assert isinstance(data["errors"], list)
        assert data["errors"] and "解析失败" in data["errors"][0]


# ── BSDL 报告（聚合成功面+文件不存在） ──────────────────────────────────────


class TestBsdlReport:
    def test_ok_envelope_aggregates(self, mcp_server, tmp_path):
        path = tmp_path / "sample.bsd"
        path.write_text(SAMPLE_BSDL, encoding="utf-8")
        data = _call(mcp_server, "bsdl_report", {"path": str(path)})
        assert data["ok"] is True, data.get("errors")
        assert data["entity_name"] == "DEMO_IC"
        assert data["n_entities"] == 1
        assert data["stats"]["n_boundary_cells"] == 8
        assert data["n_tap_present"] == 5
        inst = data["instruction_summary"]
        assert inst["n_instructions"] == 4
        assert inst["capture"] == "0001"
        assert inst["idcode_valid"] is True
        bnd = data["boundary_summary"]
        assert bnd["n_cells"] == 8
        assert bnd["function_buckets"]["output3"] == 2
        assert bnd["function_buckets"]["input"] == 2
        assert bnd["length_declared"] == 8
        assert bnd["length_rel_diff"] == 0.0  # 一致性三数字（报告面不硬门）

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        data = _call(mcp_server, "bsdl_report",
                     {"path": str(tmp_path / "nope.bsd")})
        assert data["ok"] is False
        assert isinstance(data["errors"], list)
        assert data["errors"] and "不可读" in data["errors"][0]


# ── BSDL 边界单元查询（全量/port 过滤/未命中名录/文件不存在） ───────────────


class TestBsdlBoundaryDetail:
    def test_all_cells_flat_list(self, mcp_server, tmp_path):
        path = tmp_path / "sample.bsd"
        path.write_text(SAMPLE_BSDL, encoding="utf-8")
        data = _call(mcp_server, "bsdl_boundary_detail", {"path": str(path)})
        assert data["ok"] is True, data.get("errors")
        assert data["port"] is None
        assert data["n_cells"] == 8
        assert [c["num"] for c in data["cells"]] == list(range(8))
        assert "control_cells" not in data  # 全量形态不带控制链键

    def test_port_filter_control_chain(self, mcp_server, tmp_path):
        path = tmp_path / "sample.bsd"
        path.write_text(SAMPLE_BSDL, encoding="utf-8")
        data = _call(mcp_server, "bsdl_boundary_detail",
                     {"path": str(path), "port": "out_b"})
        assert data["ok"] is True, data.get("errors")
        assert data["cells"][0]["num"] == 5  # output3 单元
        assert data["control_cells"][0]["num"] == 4  # 经控制链关联
        assert data["n_control_cells"] == 1

    def test_unknown_port_error_lists_available(self, mcp_server, tmp_path):
        path = tmp_path / "sample.bsd"
        path.write_text(SAMPLE_BSDL, encoding="utf-8")
        data = _call(mcp_server, "bsdl_boundary_detail",
                     {"path": str(path), "port": "ghost_port"})
        assert data["ok"] is False
        assert "ghost_port" in data["errors"][0]
        assert "out_a" in data["errors"][0]  # 可用名录如实回显（消费方不猜）

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        data = _call(mcp_server, "bsdl_boundary_detail", {
            "path": str(tmp_path / "nope.bsd"), "port": "out_a"})
        assert data["ok"] is False
        assert data["errors"] and "不可读" in data["errors"][0]


# ── 注册面健全性（不计数的轻量钉：名字在册、Args 与签名对齐） ────────────────


PACKAGING_TOOLS = ["odbpp_report", "bsdl_report", "bsdl_boundary_detail"]


class TestPackagingRegistration:
    def test_three_tools_registered(self, mcp_server):
        tools = asyncio.run(mcp_server.list_tools())
        names = {t.name for t in tools}
        assert set(PACKAGING_TOOLS) <= names

    @pytest.mark.parametrize("tool_name", PACKAGING_TOOLS)
    def test_docstring_args_match_signature(self, mcp_server, tool_name):
        """Args 段覆盖全部真实参数且无幽灵参数（一致性门同款口径）。"""
        from tests.unit.test_mcp_tool_consistency import (
            _documented_args,
            _schema_params,
        )
        tools = asyncio.run(mcp_server.list_tools())
        tool = {t.name: t for t in tools}[tool_name]
        documented = set(_documented_args(tool.fn))
        assert documented == _schema_params(tool), (tool_name, documented)
