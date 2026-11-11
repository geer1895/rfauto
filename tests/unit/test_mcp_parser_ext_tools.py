"""EDA 格式解析五批扩展 MCP 工具组单测（aurora_r R-26 席位，2026-11-10）。

覆盖面（任务书预声明：每工具 ok/error 双路信封钉+desc 门+schema
additionalProperties:false）：
- 信封成功路径：经 fastmcp call_tool 真调用（#270 家法：死壳只在调用
  期才炸），夹具全 tmp_path 内联合成（DRC design JSON 照抄
  test_drc_service.py CLEAN/VIOLATION 最小版；Verilog-A/SKILL/SPICE/
  Spectre 逐域最小语料——#144 家法零 runs/ 湖写入）；
- 查询未命中错误路径：veriloga_module_detail 不存在 module——ok=False
  errors 信封随附可用模块名录零抛出；
- 裁面/旋钮：drc rf 内置缺省 RF 规则集链、overlay min_coverage 阈值
  （low_coverage=True 只标注不改 ok 语义）、overlay text 面 path=None
  如实哨兵；
- 错误路径：文件不存在（6 工具全覆盖）、drc 双缺规则（usage 级）、
  flavor 词表外、SKILL 括号失衡——全部 ok=False errors 信封零抛出；
- 注册面健全性：六工具在册、Args 段与 schema 参数逐工具对齐（一致性
  门同款口径）、inputSchema additionalProperties=False 逐工具钉、
  注解注入 read_only 逐工具钉。

工具注册序/计数锚不修（202→208 计数链五钉随本席同笔重钉，见
test_mcp_server/test_mcp_tool_consistency/test_mcp_em_family/
test_cli_registration_order——本文件零计数断言，只测行为）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE_DRC_RULES = (
    Path(__file__).resolve().parent / "fixtures" / "drc" / "sample_rules.json"
)

PARSER_EXT_TOOLS = [
    "drc_design_validate",
    "veriloga_module_detail",
    "skill_call_graph",
    "netlist_overlay_file",
    "spectre_overlay_file",
    "netlist_overlay_text",
]

# ── 夹具（逐域最小语料，全 tmp_path 落盘） ────────────────────────────────

#: DRC design JSON（照抄 test_drc_service.py CLEAN_DESIGN 最小版）。
_CLEAN_DESIGN = {
    "name": "board_a",
    "coordinate_unit": "mm",
    "objects": [
        {"name": "TL1", "type": "trace", "layer": "F.Cu", "rf": True,
         "metrics": {"width": 0.3, "impedance": 50.2}, "x": 0.0, "y": 0.0},
        {"name": "P1", "type": "pad", "layer": "F.Cu", "x": 0.0, "y": 0.0},
        {"name": "P2", "type": "pad", "layer": "F.Cu", "x": 3.0, "y": 0.0},
    ],
}

#: DRC 违规 design（照抄 test_drc_service.py VIOLATION_DESIGN）。
_VIOLATION_DESIGN = {
    "coordinate_unit": "mm",
    "objects": [
        {"name": "BAD1", "type": "trace", "layer": "F.Cu",
         "metrics": {"width": 0.1}},
    ],
}

#: Verilog-A 双模块最小语料（test_veriloga_parser.py SAMPLE_VA 缩版）。
_SAMPLE_VA = """\
// Verilog-A minimal sample (R-26 MCP ext fixture)
module rdiv (p, n);
  input p, n;
  electrical p, n;
  parameter real R = 50 from [0:inf);
  analog begin
    V(p, n) <+ R * I(p, n);
  end
endmodule

module rc_lp (in, out);
  input in;
  output out;
  electrical in, out;
  analog begin
    V(out) <+ V(in);
  end
endmodule
"""

#: SKILL 最小语料（defun 内调用+外部调用，test_skill_parser.py
#: SKILL_MAIN 缩版——caller/callee/external 三面各有落点；外部调用走
#: 前缀形态——中缀表达式首操作数计 generic 调用、尾操作数是实参不是
#: 调用，Q-X62 已知限制如实）。
_SAMPLE_SKILL = """\
; R-26 MCP ext fixture
defun( filterGain (g f0)
    let( ( omega (* 2 PI f0) )
        cond(
            ( (g > 10) (ocnPrint ?num g) )
            ( t (hiShowWindow win) )
        )
    )
)
define( (kDouble x) (* x 2) )
defun( top (n)
    filterGain( n 1.0 )
    kDouble( n )
    kFactor( n )
)
"""

#: SPICE 网表最小语料（test_netlist_semantic_overlay.py _SPICE_DECK 缩版）。
_SPICE_DECK = """\
RC divider top
V1 in gnd DC 5
R1 in out 1k
C1 out gnd 1n
X1 out amp_out buffer
.subckt buffer a y
Rin a 0 1meg
.ends
.end
"""

#: Spectre 原生最小语料（test_spectre_parser.py 内联同款）。
_SPECTRE_DECK = "simulator lang=spectre\nR1 (a b) resistor r=1k\n"


# ── 基建（test_mcp_packaging_tools 同款） ──────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_cwd(isolated):
    """cwd 隔离（#144 家法，前四批同款）：工具按显式路径直读文件本不触
    runs/，隔离体单源化防未来任何 cwd 相对路径面。"""


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


def _write_json(tmp_path: Path, name: str, data: dict) -> str:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


# ── DRC validate（``rfauto drc validate`` 同源校验面锚） ───────────────────


class TestDrcDesignValidate:
    def test_ok_rules_file_clean_verdict(self, mcp_server, tmp_path):
        design = _write_json(tmp_path, "clean.json", _CLEAN_DESIGN)
        result = _call(mcp_server, "drc_design_validate", {
            "design_path": design, "rules_path": str(FIXTURE_DRC_RULES),
        })
        assert result["ok"] is True
        assert result["rules_source"] == "file"
        assert result["verdict"] in ("issues", "attention", "clean")
        assert result["coordinate_unit"] == "mm"
        assert isinstance(result["violations"], list)
        assert isinstance(result["summary"], dict)

    def test_ok_rf_default_ruleset(self, mcp_server, tmp_path):
        design = _write_json(tmp_path, "clean.json", _CLEAN_DESIGN)
        result = _call(mcp_server, "drc_design_validate", {
            "design_path": design, "rf": True,
        })
        assert result["ok"] is True
        assert result["rules_source"] == "default_rf"
        assert result["rules_path"] is None

    def test_violation_verdict_issues(self, mcp_server, tmp_path):
        design = _write_json(tmp_path, "bad.json", _VIOLATION_DESIGN)
        result = _call(mcp_server, "drc_design_validate", {
            "design_path": design, "rules_path": str(FIXTURE_DRC_RULES),
        })
        assert result["ok"] is True  # 违规≠调用失败（ok 语义看解析成败）
        assert result["verdict"] == "issues"
        assert len(result["violations"]) >= 1

    def test_missing_rules_and_rf_error_envelope(self, mcp_server, tmp_path):
        """双缺规则（usage 级错误）：无规则可校验是调用错误不是 skipped。"""
        design = _write_json(tmp_path, "clean.json", _CLEAN_DESIGN)
        result = _call(mcp_server, "drc_design_validate", {
            "design_path": design,
        })
        assert result["ok"] is False
        assert isinstance(result["errors"], list) and result["errors"]

    def test_missing_design_error_envelope(self, mcp_server, tmp_path):
        result = _call(mcp_server, "drc_design_validate", {
            "design_path": str(tmp_path / "no_such_design.json"),
            "rf": True,
        })
        assert result["ok"] is False
        assert "不可读" in result["errors"][0]


# ── Verilog-A 单模块查询（veriloga 域 MCP 面零覆盖补齐） ──────────────────


class TestVerilogaModuleDetail:
    def test_ok_module_summary(self, mcp_server, tmp_path):
        va = _write(tmp_path, "sample.va", _SAMPLE_VA)
        result = _call(mcp_server, "veriloga_module_detail", {
            "path": va, "module": "rdiv",
        })
        assert result["ok"] is True
        assert result["module"] == "rdiv"
        assert result["summary"]["module"] == "rdiv"
        assert result["summary"]["n_params"] == 1
        assert result["summary"]["n_ports"] == 2

    def test_unknown_module_lists_available(self, mcp_server, tmp_path):
        """查询未命中是查询答案：ok=False errors 随附可用模块名录。"""
        va = _write(tmp_path, "sample.va", _SAMPLE_VA)
        result = _call(mcp_server, "veriloga_module_detail", {
            "path": va, "module": "nope",
        })
        assert result["ok"] is False
        assert isinstance(result["errors"], list) and result["errors"]
        blob = "".join(result["errors"])
        assert "rdiv" in blob and "rc_lp" in blob

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        result = _call(mcp_server, "veriloga_module_detail", {
            "path": str(tmp_path / "no_such.va"), "module": "rdiv",
        })
        assert result["ok"] is False
        assert isinstance(result["errors"], list) and result["errors"]


# ── SKILL 静态调用图（Q-X69 九域清单 skill 域只读面二线查询锚） ──────────


class TestSkillCallGraph:
    def test_ok_edges_external_and_recursive_shape(self, mcp_server, tmp_path):
        sk = _write(tmp_path, "sample.il", _SAMPLE_SKILL)
        result = _call(mcp_server, "skill_call_graph", {"path": sk})
        assert result["ok"] is True
        assert "filterGain" in result["defined_names"]
        assert "kDouble" in result["defined_names"]
        # top→filterGain / top→kDouble 两条内部边（符号名匹配同名 define）
        edges = {(e["caller"], e["callee"]) for e in result["edges"]}
        assert ("top", "filterGain") in edges
        assert ("top", "kDouble") in edges
        assert result["n_edges"] == len(result["edges"])
        # kFactor 无同名定义 → external 如实（逐条 {name, count} 形态）
        assert any(e["name"] == "kFactor" for e in result["external"])
        assert result["n_external"] == len(result["external"])

    def test_unbalanced_parens_error_envelope(self, mcp_server, tmp_path):
        sk = _write(tmp_path, "bad.il", "defun( f (x)\n  (+ x 1)\n")
        result = _call(mcp_server, "skill_call_graph", {"path": sk})
        assert result["ok"] is False
        assert isinstance(result["errors"], list) and result["errors"]

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        result = _call(mcp_server, "skill_call_graph", {
            "path": str(tmp_path / "no_such.il"),
        })
        assert result["ok"] is False
        assert isinstance(result["errors"], list) and result["errors"]


# ── 网表语义 overlay 三件套（R-02 AX-2 零 agent 面补齐） ─────────────────


class TestNetlistOverlayFile:
    def test_ok_overlay_schema_and_flavor(self, mcp_server, tmp_path):
        deck = _write(tmp_path, "deck.cir", _SPICE_DECK)
        result = _call(mcp_server, "netlist_overlay_file", {"path": deck})
        assert result["ok"] is True
        assert result["path"] == deck
        assert result["overlay"]["schema"] == "netlist_overlay/1.0"
        assert result["flavor_detected"]  # auto 探测如实回显
        cov = result["overlay"]["coverage"]
        assert "low_coverage" in cov and "threshold" in cov
        assert isinstance(result["diagnostics"], list)

    def test_bad_flavor_error_envelope(self, mcp_server, tmp_path):
        deck = _write(tmp_path, "deck.cir", _SPICE_DECK)
        result = _call(mcp_server, "netlist_overlay_file", {
            "path": deck, "flavor": "banana",
        })
        assert result["ok"] is False
        assert isinstance(result["errors"], list) and result["errors"]

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        result = _call(mcp_server, "netlist_overlay_file", {
            "path": str(tmp_path / "no_such.cir"),
        })
        assert result["ok"] is False
        assert isinstance(result["errors"], list) and result["errors"]


class TestSpectreOverlayFile:
    def test_ok_overlay_lang(self, mcp_server, tmp_path):
        deck = _write(tmp_path, "deck.scs", _SPECTRE_DECK)
        result = _call(mcp_server, "spectre_overlay_file", {"path": deck})
        assert result["ok"] is True
        assert result["path"] == deck
        assert result["overlay"]["schema"] == "netlist_overlay/1.0"
        assert isinstance(result["diagnostics"], list)

    def test_missing_file_error_envelope(self, mcp_server, tmp_path):
        result = _call(mcp_server, "spectre_overlay_file", {
            "path": str(tmp_path / "no_such.scs"),
        })
        assert result["ok"] is False
        assert isinstance(result["errors"], list) and result["errors"]


class TestNetlistOverlayText:
    def test_ok_path_none_sentinel(self, mcp_server):
        """文本面无来源文件：path 恒 None 如实哨兵（非 "" 非缺席）。"""
        result = _call(mcp_server, "netlist_overlay_text", {
            "text": _SPICE_DECK,
        })
        assert result["ok"] is True
        assert result["path"] is None
        assert result["overlay"]["schema"] == "netlist_overlay/1.0"

    def test_min_coverage_flags_not_rejects(self, mcp_server):
        """覆盖率门只标注不改 ok 语义：min_coverage=1.0 收紧触发降位。"""
        result = _call(mcp_server, "netlist_overlay_text", {
            "text": _SPICE_DECK, "min_coverage": 1.0,
        })
        assert result["ok"] is True  # low_coverage=True 时 ok 仍 True
        cov = result["overlay"]["coverage"]
        assert cov["threshold"] == 1.0
        if cov.get("ratio") is not None and cov["ratio"] < 1.0:
            assert cov["low_coverage"] is True

    def test_bad_flavor_error_envelope(self, mcp_server):
        result = _call(mcp_server, "netlist_overlay_text", {
            "text": _SPICE_DECK, "flavor": "banana",
        })
        assert result["ok"] is False
        assert isinstance(result["errors"], list) and result["errors"]


# ── 注册面健全性（不计数的轻量钉） ────────────────────────────────────────


class TestParserExtRegistration:
    def test_six_tools_registered(self, mcp_server):
        tools = asyncio.run(mcp_server.list_tools())
        names = {t.name for t in tools}
        assert set(PARSER_EXT_TOOLS) <= names

    @pytest.mark.parametrize("tool_name", PARSER_EXT_TOOLS)
    def test_docstring_args_match_signature(self, mcp_server, tool_name):
        """Args 段覆盖全部真实参数且无幽灵参数（desc 门 dim2/5 同款口径）。"""
        from tests.unit.test_mcp_tool_consistency import (
            _documented_args,
            _schema_params,
        )
        tools = asyncio.run(mcp_server.list_tools())
        tool = {t.name: t for t in tools}[tool_name]
        documented = set(_documented_args(tool.fn))
        assert documented == _schema_params(tool), (tool_name, documented)

    @pytest.mark.parametrize("tool_name", PARSER_EXT_TOOLS)
    def test_schema_additional_properties_false(self, mcp_server, tool_name):
        """inputSchema additionalProperties=False 逐工具钉（封闭 schema）。"""
        tools = asyncio.run(mcp_server.list_tools())
        tool = {t.name: t for t in tools}[tool_name]
        assert tool.parameters.get("additionalProperties") is False

    @pytest.mark.parametrize("tool_name", PARSER_EXT_TOOLS)
    def test_annotations_read_only(self, mcp_server, tool_name):
        """注解注入 read_only 逐工具钉（readOnlyHint=True+非破坏）。"""
        tools = asyncio.run(mcp_server.list_tools())
        tool = {t.name: t for t in tools}[tool_name]
        ann = tool.annotations
        assert ann is not None and ann.readOnlyHint is True
        assert ann.destructiveHint is False
