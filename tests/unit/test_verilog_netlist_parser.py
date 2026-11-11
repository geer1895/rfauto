"""Verilog 网表解析内核单测（aurora_q Q-X47 席位，2026-11-07）。

覆盖面（任务书 ≥20 条之解析内核半边——构造面各 ≥2+词法正负例）：

- 夹具正例：ANSI 2001 端口（方向/范围/标量）、1995 体内方向声明
  回填、wire/reg 声明范围、门级原语位置→注册表命名归一（and/not/
  buf 多输出/xor/bufif1 三态/pullup）、模块实例 named/positional
  双形态（尾逗号=末位未连接）、assign 位选拼接 lhs+位宽字面量+
  裸 #delay、parameter/localparam、defparam、编译器指令名录、
  always 跳过+warning、顶层候选、实例化边；
- 词法面（内联）：块注释/行注释、字符串转义、转义标识符、层次名、
  位宽字面量数值回收（含 x/z 位 has_xz）、位分隔下划线、多字符运算
  符最大吞噬、编译器指令续行；
- 语法负例（VerilogParseError）：块注释未闭合、字符串未闭合；
- fail-soft 面：病态实例降级警告不炸文档、1995 形态方向回填；
- 拓扑面：三层关系（net_drivers/net_readers）、实例边表、孤立网
  undriven/unloaded 双桶（reg 与外部边界豁免）、树深度 longest
  chain+关键路径、组合环检测 cyclic、behavioral_skipped 盲区标注。

单测零网络零真机零写盘（夹具只读；负例用内联字符串）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.core.verilog_netlist_parser import (
    DIRECTIONS,
    GATE_PRIMITIVES,
    PARSER_SCHEMA_VERSION,
    WELL_KNOWN_CELL_TYPES,
    GatePrimitive,
    VerilogParseError,
    extract_module_topology,
    parse_verilog,
    parse_verilog_number,
    tokenize_verilog,
)

FIXTURE = Path(__file__).resolve().parents[1] / "unit" / "fixtures" / "verilog" / "sample.v"


@pytest.fixture(scope="module")
def doc() -> dict:
    return parse_verilog(FIXTURE.read_text(encoding="utf-8"))


# ── 词法面（内联）──────────────────────────────────────────────────────────


class TestLexer:
    def test_comments_and_strings(self) -> None:
        toks = tokenize_verilog(
            "// line\n/* block\nspan */ \"a\\\"b\" x")
        assert [t.text for t in toks] == ['"a\\"b"', "x"]

    def test_unclosed_block_comment_raises(self) -> None:
        with pytest.raises(VerilogParseError, match="块注释未闭合"):
            tokenize_verilog("a /* never closed")

    def test_unclosed_string_raises(self) -> None:
        with pytest.raises(VerilogParseError, match="字符串未闭合"):
            tokenize_verilog('"never closed')

    def test_escaped_identifier_and_hierarchy(self) -> None:
        # 转义标识符到空白止整体成一词（含 '.'/'<' 等非常规字符）
        toks = tokenize_verilog(r"\bus.enable<0> x.y.z")
        assert toks[0].kind == "id"
        assert toks[0].text == "bus.enable<0>"
        # 层次名在词法层是 id/'.'/id 分词，表达式重建层再合成（见
        # test_hierarchical_name_rebuilt_in_connection）
        assert [t.text for t in toks[1:]] == ["x", ".", "y", ".", "z"]

    def test_hierarchical_name_rebuilt_in_connection(self) -> None:
        doc = parse_verilog(
            "module m (input a, output b);\n"
            "  buf g (b, top.u1.n);\nendmodule\n")
        conns = doc["modules"]["m"]["instances"][0]["connections"]
        assert conns["in"] == "top.u1.n"

    def test_multichar_operator_maximal_munch(self) -> None:
        toks = tokenize_verilog("a <= b === c != d && e")
        ops = [t.text for t in toks if t.kind == "punct"]
        assert ops == ["<=", "===", "!=", "&&"]

    def test_directive_with_continuation(self) -> None:
        toks = tokenize_verilog("`define FOO bar \\\n  baz\nx")
        assert [t.text for t in toks] == ["define", "x"]

    def test_sized_literal_tokens(self) -> None:
        toks = tokenize_verilog("8'hFF 3'b0x0 12'd135")
        nums = [t.text for t in toks if t.kind == "num"]
        assert nums == ["8", "'hFF", "3", "'b0x0", "12", "'d135"]


class TestParseNumber:
    def test_plain_decimal(self) -> None:
        assert parse_verilog_number("42")["value"] == 42
        assert parse_verilog_number("1_000")["value"] == 1000

    def test_sized_literals(self) -> None:
        assert parse_verilog_number("8'hFF") == {
            "value": 255, "bits": 8, "base": "h",
            "has_xz": False, "raw": "8'hFF"}
        assert parse_verilog_number("12'd135")["value"] == 135
        assert parse_verilog_number("4'b0101")["value"] == 5

    def test_xz_bits_flagged_not_guessed(self) -> None:
        r = parse_verilog_number("1'bx")
        assert r["has_xz"] is True
        assert r["bits"] == 1
        # x 位按 0 计位权如实标注，不猜未知位语义
        assert r["value"] == 0

    def test_expression_returns_none(self) -> None:
        assert parse_verilog_number("W - 1") is None
        assert parse_verilog_number("abc") is None


# ── 门级原语注册表（AGENTS 规则 3 面钉）─────────────────────────────────────


class TestGatePrimitiveRegistry:
    def test_registry_is_registry_kit_with_lrm14_full_set(self) -> None:
        from rfauto.core.registry_kit import RegistryKit
        assert isinstance(GATE_PRIMITIVES, RegistryKit)
        # LRM 14 章全集 26 键（and 族 6+buf/not 2+三态 4+MOS 6+tran 族 6
        # +pull 2）
        assert len(GATE_PRIMITIVES) == 26
        for name in ("and", "nand", "or", "nor", "xor", "xnor", "buf",
                     "not", "bufif0", "bufif1", "notif0", "notif1",
                     "nmos", "pmos", "rnmos", "rpmos", "cmos", "rcmos",
                     "tran", "rtran", "tranif0", "tranif1",
                     "rtranif0", "rtranif1", "pullup", "pulldown"):
            assert name in GATE_PRIMITIVES

    def test_gate_direction_metadata_shape(self) -> None:
        prim = GATE_PRIMITIVES.get("and")
        assert isinstance(prim, GatePrimitive)
        assert prim.output_ports == ("out",)
        assert prim.n_inputs is None  # 可变输入变体
        tri = GATE_PRIMITIVES.get("bufif1")
        assert tri.input_ports == ("in", "ctrl")
        assert GATE_PRIMITIVES.get("tran").bidirectional is True
        assert GATE_PRIMITIVES.get("pullup").input_ports == ()

    def test_well_known_cell_catalog_shape(self) -> None:
        # mux/dff/latch 类是单元库类型（非门级原语）——任务书点名面在
        # WELL_KNOWN_CELL_TYPES 名录，不进方向注册表
        assert {"mux", "dff", "latch"} <= WELL_KNOWN_CELL_TYPES
        assert "and" not in WELL_KNOWN_CELL_TYPES


# ── 夹具解析面 ──────────────────────────────────────────────────────────────


class TestFixtureModules:
    def test_schema_version_and_module_inventory(self, doc: dict) -> None:
        assert doc["schema"] == f"verilog_netlist/{PARSER_SCHEMA_VERSION}"
        # 注册序=声明序；adder 被 top 实例化→非顶层；dff_cell 未被实
        # 例化→顶层候选（外部单元库引用的代表形态）
        assert doc["module_order"] == ["top", "adder", "dff_cell"]
        assert doc["top_modules"] == ["top", "dff_cell"]

    def test_ansi_ports_direction_width(self, doc: dict) -> None:
        ports = doc["modules"]["top"]["ports"]
        assert [(p["name"], p["direction"]) for p in ports] == [
            ("clk", "input"), ("d", "input"),
            ("q", "output"), ("co", "output")]
        assert all(p["direction"] in DIRECTIONS for p in ports)
        width_by_name = {p["name"]: p["width"] for p in ports}
        assert width_by_name["d"] == {"msb": "3", "lsb": "0", "span": 4}
        assert width_by_name["clk"]["span"] == 1
        assert doc["modules"]["top"]["ansi_ports"] is True

    def test_1995_body_direction_backfill(self, doc: dict) -> None:
        adder = doc["modules"]["adder"]
        assert adder["ansi_ports"] is False
        assert [(p["name"], p["direction"]) for p in adder["ports"]] == [
            ("a", "input"), ("b", "input"),
            ("s", "output"), ("cout", "output")]
        # 参数化位宽 [W-1:0]：msb/lsb 表达式原文保真，span 数值化尽力
        # （W 非纯数值→span None 不猜）
        assert adder["ports"][0]["width"]["msb"] == "W - 1"
        assert adder["ports"][0]["width"]["span"] is None

    def test_dff_cell_body_decl_shape(self, doc: dict) -> None:
        ports = doc["modules"]["dff_cell"]["ports"]
        assert [(p["name"], p["direction"]) for p in ports] == [
            ("d", "input"), ("clk", "input"), ("q", "output")]

    def test_wires_with_kind_and_width(self, doc: dict) -> None:
        wires = {w["name"]: w for w in doc["modules"]["top"]["wires"]}
        assert wires["n1"]["kind"] == "wire"
        assert wires["n1"]["width"]["span"] == 4
        assert wires["r_q"]["kind"] == "reg"
        assert wires["floating_net"]["width"]["span"] == 1
        assert "scratch" in wires

    def test_gate_instances_positional_to_named(self, doc: dict) -> None:
        insts = {i["name"]: i for i in doc["modules"]["top"]["instances"]}
        assert insts["g1"]["primitive"] is True
        assert insts["g1"]["connections"] == {
            "out": "carry_orphan", "in1": "d[0]", "in2": "d[1]"}
        assert insts["g1"]["connection_style"] == "positional"
        # not：单出单入变体（位置 1=out1、位置 2=in）
        assert insts["g2"]["connections"] == {"out1": "n1[0]", "in": "d[2]"}
        # buf 多输出：out1/out2/in
        assert insts["b1"]["connections"] == {
            "out1": "q[0]", "out2": "q[1]", "in": "n2[0]"}
        # 三态：out/in/ctrl
        assert insts["tri1"]["connections"] == {
            "out": "n2[2]", "in": "n2[3]", "ctrl": "clk"}
        assert insts["pu"]["connections"] == {"out": "co"}
        assert insts["pu"]["primitive"] is True

    def test_module_instances_named_and_positional(self, doc: dict) -> None:
        insts = {i["name"]: i for i in doc["modules"]["top"]["instances"]}
        assert insts["u_add"]["primitive"] is False
        assert insts["u_add"]["connections"] == {
            "a": "d", "b": "n1", "s": "n2", "cout": "co"}
        assert insts["u_add"]["connection_style"] == "named"
        # 位置连接按序号键保序；尾逗号=末位 cout 未连接（3 项非 4 项）
        assert insts["u_scratch"]["connections"] == {
            "1": "scratch", "2": "d[1:0]", "3": "scratch"}
        assert insts["u_scratch"]["connection_style"] == "positional"
        # adder 在 WELL_KNOWN_CELL_TYPES 名录内（归类提示元数据，不参与
        # 连接方向判定——方向由文档内 adder 模块端口声明决定）
        assert insts["u_add"]["well_known_cell"] is True
        assert insts["u_add"]["primitive"] is False
        x1 = insts["x1"]
        assert x1["type"] == "xor"

    def test_assigns_with_delay_and_concat(self, doc: dict) -> None:
        assigns = doc["modules"]["top"]["assigns"]
        assert assigns[0] == {"lhs": "n1[3:1]", "rhs": "3'b000",
                              "delay": "#2"}
        assert assigns[1]["lhs"] == "{q[3], q[0]}"
        assert assigns[1]["rhs"] == "{n2[3], n2[2]}"
        assert assigns[1]["delay"] is None
        # adder 模块体三条连续赋值（位选 lhs）
        adder_assigns = {a["lhs"] for a in doc["modules"]["adder"]["assigns"]}
        assert adder_assigns == {"full", "s", "cout"}

    def test_parameters_localparams_defparams(self, doc: dict) -> None:
        top = doc["modules"]["top"]
        assert top["parameters"] == {"W": "4"}
        assert top["localparams"] == {"HALF": "W / 2"}
        assert top["defparams"] == [
            {"target": "u_add", "param": "W", "value": "8"}]
        assert doc["modules"]["adder"]["parameters"] == {"W": "4"}

    def test_directives_and_header_params(self, doc: dict) -> None:
        assert doc["directives"] == ["timescale", "default_nettype"]
        assert doc["modules"]["top"]["header_params_raw"] is None
        # adder 无头参数口
        assert doc["modules"]["adder"]["header_params_raw"] is None

    def test_behavioral_block_skipped_with_warning(self, doc: dict) -> None:
        warns = doc["modules"]["top"]["warnings"]
        assert [w["name"] for w in warns] == ["always"]
        assert warns[0]["line"] > 0
        assert doc["stats"]["n_warnings"] >= 1

    def test_instantiations_and_external_types(self, doc: dict) -> None:
        assert len(doc["instantiations"]) == 8
        assert doc["instantiations"][0] == {
            "parent": "top", "child": "adder", "instance": "u_add"}
        # 门级原语类型不算外部单元（文档无 and 模块定义）
        assert doc["external_instance_types"] == []

    def test_stats_shape(self, doc: dict) -> None:
        stats = doc["stats"]
        assert stats["n_modules"] == 3
        # adder/dff_cell 无实例——top 8 只（u_add/g1/g2/b1/x1/tri1/pu/
        # u_scratch）
        assert stats["n_instances"] == 8
        assert stats["n_defparams"] == 1
        assert stats["n_modules"] == len(doc["modules"])


# ── fail-soft 面（内联）─────────────────────────────────────────────────────


class TestFailSoft:
    def test_malformed_instance_degrades_to_warning(self) -> None:
        text = """
module m (input a, output b);
  and g1 (b, a;
  or g2 (b, a, a);
endmodule
"""
        doc = parse_verilog(text)
        # g1 缺右括号降级警告跳语句，g2 正常收编
        insts = [i["name"] for i in doc["modules"]["m"]["instances"]]
        assert insts == ["g2"]
        assert any(w["name"] == "instance_parse_failed"
                   for w in doc["warnings"])

    def test_unterminated_module_fallback(self) -> None:
        doc = parse_verilog("module m (input a);\n  wire x;\n")
        assert "m" in doc["modules"]
        assert any(w["name"] == "unterminated_module"
                   for w in doc["warnings"])

    def test_unknown_construct_skipped_with_warning(self) -> None:
        doc = parse_verilog(
            "module m (input a, output b);\n"
            "  $display(\"x\");\n"
            "  and g1 (b, a, a);\n"
            "endmodule\n")
        assert [i["name"] for i in doc["modules"]["m"]["instances"]] == ["g1"]

    def test_generate_block_fully_skipped(self) -> None:
        doc = parse_verilog(
            "module m (input a, output b);\n"
            "  generate\n"
            "    if (1) begin : u1\n"
            "      and g (b, a, a);\n"
            "    end\n"
            "  endgenerate\n"
            "  buf b1 (b, a);\n"
            "endmodule\n")
        names = [i["name"] for i in doc["modules"]["m"]["instances"]]
        assert names == ["b1"]  # generate 内实例不收（块级跳过如实）
        assert any(w["name"] == "generate"
                   for w in doc["modules"]["m"]["warnings"])


# ── 拓扑面 ──────────────────────────────────────────────────────────────────


class TestTopology:
    @pytest.fixture(scope="class")
    def topo(self, doc: dict) -> dict:
        return extract_module_topology(doc, "top")

    def test_three_layer_relations(self, doc: dict, topo: dict) -> None:
        # n2：u_add.s 驱动 → b1.in/x1.in1/tri1.in/always 消费
        assert {"kind": "instance", "name": "u_add"} \
            in topo["net_drivers"]["n2"]
        assert {"kind": "instance", "name": "b1"} \
            in topo["net_readers"]["n2"]
        # 模块 input 端口是边界驱动源
        assert {"kind": "port", "name": "clk"} \
            in topo["net_drivers"]["clk"]
        # assign lhs 是驱动源
        assert any(d["kind"] == "assign"
                   for d in topo["net_drivers"]["n1"])

    def test_instance_edges(self, topo: dict) -> None:
        assert ["u_add", "b1"] in topo["instance_edges"]
        assert ["g2", "u_add"] in topo["instance_edges"]
        assert ["u_add", "tri1"] in topo["instance_edges"]

    def test_orphan_nets_two_buckets(self, topo: dict) -> None:
        # undriven：floating_net（无驱动无读者）；reg 与 input 边界豁免
        assert topo["orphan_nets"]["undriven"] == ["floating_net"]
        # unloaded：carry_orphan（有驱动无读者）+ floating_net + r_q
        # （reg 过程读者不可见=behavioral 盲区嫌疑面如实）
        assert topo["orphan_nets"]["unloaded"] == [
            "carry_orphan", "floating_net", "r_q"]
        assert topo["behavioral_skipped"] is True

    def test_reg_not_flagged_undriven(self, topo: dict) -> None:
        # r_q 由 always 过程赋值驱动（被跳过）——reg 不判 undriven
        assert "r_q" not in topo["orphan_nets"]["undriven"]

    def test_tree_depth_critical_path(self, topo: dict) -> None:
        # 最长链 g2→u_add→tri1→b1（n1 交给 adder、n2 三态转缓冲）
        assert topo["tree_depth"]["depth"] == 4
        assert topo["tree_depth"]["critical_path"] == [
            "g2", "u_add", "tri1", "b1"]
        assert topo["tree_depth"]["cyclic"] is False
        assert topo["tree_depth"]["cyclic_instances"] == []

    def test_external_boundary_exemption(self, doc: dict) -> None:
        # 外部单元库实例（类型未定义）连接网进豁免面不判孤立
        text = """
module m (input a, output b);
  ext_cell u1 (.x(b), .y(unknown_net));
  wire orphan2;
  buf g1 (orphan2, a);
endmodule
"""
        d = parse_verilog(text)
        assert d["external_instance_types"] == ["ext_cell"]
        t = extract_module_topology(d, "m")
        assert "unknown_net" in t["external_boundary_nets"]
        # unknown_net 驱动方向不可判→不进 undriven（宁不报不误报）
        assert "unknown_net" not in t["orphan_nets"]["undriven"]
        assert t["orphan_nets"]["undriven"] == []

    def test_positional_module_instance_port_mapping(self, doc: dict) -> None:
        # u_scratch 位置连接按 adder 端口声明序（a,b,s,cout）对位：
        # pos3=s(output) 驱动 scratch、pos1=a(input) 读 scratch
        topo = extract_module_topology(doc, "top")
        assert {"kind": "instance", "name": "u_scratch"} \
            in topo["net_drivers"]["scratch"]

    def test_cycle_detection(self) -> None:
        text = """
module m (input a, output b);
  wire x, y;
  not g1 (x, y);
  not g2 (y, x);
  buf g3 (b, x);
endmodule
"""
        doc = parse_verilog(text)
        t = extract_module_topology(doc, "m")
        assert t["tree_depth"]["cyclic"] is True
        assert t["tree_depth"]["depth"] is None  # 环上 depth 如实置 None
        assert set(t["tree_depth"]["cyclic_instances"]) == {"g1", "g2"}

    def test_acyclic_chain_depth_counts_instances(self) -> None:
        text = """
module m (input a, output b);
  wire n1, n2, n3;
  buf u1 (n1, a);
  buf u2 (n2, n1);
  buf u3 (n3, n2);
  buf u4 (b, n3);
endmodule
"""
        doc = parse_verilog(text)
        t = extract_module_topology(doc, "m")
        assert t["tree_depth"]["depth"] == 4
        assert t["tree_depth"]["critical_path"] == ["u1", "u2", "u3", "u4"]

    def test_unknown_module_raises_keyerror(self, doc: dict) -> None:
        with pytest.raises(KeyError, match="no_such"):
            extract_module_topology(doc, "no_such")

    def test_long_chain_beyond_recursion_limit(self) -> None:
        # 门级缓冲链可达数千级——迭代式 DFS 不撞 Python 递归上限
        # （默认 1000；3000 级链递归实现必 RecursionError）
        n = 3000
        lines = ["module m (input a, output b);"]
        lines.append("  wire " + ", ".join(f"n{k}" for k in range(n)) + ";")
        lines.append("  buf u0 (n0, a);")
        for k in range(1, n):
            lines.append(f"  buf u{k} (n{k}, n{k - 1});")
        lines.append(f"  buf uout (b, n{n - 1});")
        lines.append("endmodule")
        doc = parse_verilog("\n".join(lines))
        t = extract_module_topology(doc, "m")
        assert t["tree_depth"]["depth"] == n + 1
        cp = t["tree_depth"]["critical_path"]
        assert cp[0] == "u0" and cp[-1] == "uout" and len(cp) == n + 1

    def test_zero_instance_module_depth_zero(self) -> None:
        doc = parse_verilog(
            "module m (input a, output b);\n  assign b = a;\nendmodule\n")
        t = extract_module_topology(doc, "m")
        # None 专属"组合环"语义；零实例如实 0
        assert t["tree_depth"]["depth"] == 0
        assert t["tree_depth"]["critical_path"] == []
        assert t["tree_depth"]["cyclic"] is False


# ── 门级原语元数据归一面（合成回收钉 #340 家法）──────────────────────────────


class TestGateNamedMapping:
    def _inst(self, doc: dict, name: str) -> dict:
        return {i["name"]: i for i in doc["modules"]["m"]["instances"]}[name]

    def _doc(self, body: str) -> dict:
        return parse_verilog(
            f"module m (input a, b, c, output o1, o2);\n{body}\nendmodule\n")

    def test_and_3input_keys(self) -> None:
        doc = self._doc("  and g (o1, a, b, c);")
        assert self._inst(doc, "g")["connections"] == {
            "out": "o1", "in1": "a", "in2": "b", "in3": "c"}

    def test_buf_multi_output_keys(self) -> None:
        doc = self._doc("  buf g (o1, o2, a);")
        assert self._inst(doc, "g")["connections"] == {
            "out1": "o1", "out2": "o2", "in": "a"}

    def test_cmos_four_terminal_keys(self) -> None:
        doc = self._doc("  cmos g (o1, a, b, c);")
        assert self._inst(doc, "g")["connections"] == {
            "out": "o1", "in": "a", "nctrl": "b", "pctrl": "c"}

    def test_tran_bidirectional_keys(self) -> None:
        doc = self._doc("  tranif1 g (a, b, c);")
        assert self._inst(doc, "g")["connections"] == {
            "a": "a", "b": "b", "ctrl": "c"}

    def test_gate_delay_captured(self) -> None:
        doc = self._doc("  and #(1, 2) g (o1, a, b);")
        inst = self._inst(doc, "g")
        assert inst["delay"] == "#(1, 2)"
        assert inst["params"] is None

    def test_module_instance_params_named_and_positional(self) -> None:
        text = """
module m (input a, output b);
  adder #(.W(8)) u1 (b, a);
  adder #(8, 4) u2 (b, a);
endmodule
"""
        doc = parse_verilog(text)
        insts = {i["name"]: i for i in doc["modules"]["m"]["instances"]}
        assert insts["u1"]["params"] == {"W": "8"}
        assert insts["u1"]["delay"] is None
        assert insts["u2"]["params"] == {"1": "8", "2": "4"}
