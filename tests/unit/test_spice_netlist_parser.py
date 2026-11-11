"""Q-X33（aurora_q T-Q22）——SPICE 网表深度解析器单测（三格式统一五维度）。

覆盖面（任务书 ≥20 条，实际 33 条）：
- ngspice ≥6：元件抽取（节点/值/单位/后缀缩放）、注释与续行、子电路
  定义+X 引用层次、模型卡、控制卡+扫描、.control 交互块收编、显式 flavor；
- HSPICE ≥5：方言判定（; 注释/.option post/.step）、c= 参数化主值、
  括号 pin 子电路、.tran sweep 与 .step 步进、$ 注释剥离；
- Spectre ≥7：lang 显式判定、命名块元件、model 语句+设备 kind 关键词、
  subckt/ends+实例、分析块归一、sweep 语句、注释三形态；
- 拓扑 ≥6：双向图、接地归一（0/gnd/GND!）、孤立节点检测+warning、
  MNA 维度（非地节点+V/E/H 分支增广）、嵌套层次+环截断、子电路体不进
  顶层拓扑；
- 负例与统一 schema ≥7：未知首字母结构错误、.subckt 不闭合、孤立 .ends、
  三 flavor 统一键集+JSON 安全、非法 flavor 显式 ValueError、表达式值
  保留原文、F/H 控制源三令牌、K 互感。

零网络零真机（任务书硬约束 5）；纯文本 fixture 内联。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.core.spice_netlist_parser import (
    PARSER_SCHEMA_VERSION,
    SPICE_LETTER_KINDS,
    detect_flavor,
    normalize_flavor,
    parse_spice_netlist_text,
    parse_spice_number,
)

FIVE_KEYS = ("elements", "subckts", "controls", "models", "topology")

_NGSPICE_RC = """* RC lowpass divider circuit
V1 in 0 DC 0 AC 1 0
R1 in out 1k
C1 out 0 1u
Rload out gnd 2meg $ load resistor
+ temp=27
.control
ac dec 10 1k 100meg
.endc
.end
"""

_HSPICE_BP = """.OPTION POST probe
* HSPICE bandpass with notch
V1 1 0 AC 1
R1 1 2 50
C1 2 0 c=10p $ shunt cap
L1 2 3 10n
.subckt notch (a b) w=2
Rn a b 100
Cn a b 1p
.ends notch
Xnotch 2 3 notch w=2
.tran 10p 5n sweep temp -40 125 5
.step param=vdd list 1.8 3.3
.end
"""

_SPECTRE_BP = """// Spectre bandpass netlist
simulator lang=spectre
parameters f0=1G
subckt lpf (in out)
R1 (in out) resistor r=1k
C1 (out 0) capacitor c=1p
ends lpf
model mynmos bsim4 type=nmos version=3.3 level=14
M1 (d g s 0) mynmos w=2u l=180n
Vd (d 0) vsource dc=1.8
Xlpf (a b) lpf
tran1 tran stop=1u
ac1 ac dec 10 1k 100meg
sw1 sweep dev=Vd lin 5 0 1.8
"""


def _el_by_name(result: dict, name: str) -> dict:
    return next(e for e in result["elements"] if e["name"] == name)


# ── ngspice ──────────────────────────────────────────────────────────────────


class TestNgspiceFlavor:
    def test_basic_rc_extraction(self):
        r = parse_spice_netlist_text(_NGSPICE_RC)
        assert r["flavor"] == "ngspice"
        r1 = _el_by_name(r, "R1")
        assert r1["kind"] == "R"
        assert r1["nodes"] == ["in", "out"]
        assert r1["value"] == 1000.0
        assert r1["unit"] == "ohm"
        c1 = _el_by_name(r, "C1")
        assert c1["value"] == 1e-6
        assert c1["unit"] == "farad"
        v1 = _el_by_name(r, "V1")
        assert v1["nodes"] == ["in", "0"]
        assert v1["source_spec"] == {"type": "DC", "raw": "DC 0 AC 1 0"}
        assert v1["unit"] == "volt"

    def test_comments_and_continuation(self):
        r = parse_spice_netlist_text(_NGSPICE_RC)
        rl = _el_by_name(r, "Rload")
        # $ 行内注释剥离（"load resistor" 不入令牌）+ 续行 temp=27 并入
        assert rl["value"] == 2e6
        assert rl["params"] == {"temp": 27.0}
        assert rl["nodes"] == ["out", "0"]  # gnd → 接地归一
        assert r["structural_errors"] == []
        assert r["controls"][0]["name"] == "control_block"
        assert r["controls"][0]["args"] == ["ac dec 10 1k 100meg"]

    def test_number_suffix_scaling(self):
        assert parse_spice_number("1k") == 1000.0
        assert parse_spice_number("2meg") == 2e6
        assert parse_spice_number("3.3u") == pytest.approx(3.3e-6)
        assert parse_spice_number("100n") == pytest.approx(1e-7)
        assert parse_spice_number("47p") == pytest.approx(4.7e-11)
        assert parse_spice_number("2T") == 2e12
        assert parse_spice_number("5mil") == 5 * 25.4e-6
        assert parse_spice_number("1ohm") == 1.0  # 纯字母尾巴按惯例忽略
        assert parse_spice_number("vdd") is None
        assert parse_spice_number("{1k*2}") is None
        assert parse_spice_number("0") == 0.0  # 0.0 合法值非缺失

    def test_subckt_definition_and_x_reference(self):
        deck = """nested example deck
X1 in out lpf
.subckt lpf a b
Ra a b 1k
Ca b 0 1n
.ends lpf
.end
"""
        r = parse_spice_netlist_text(deck)
        sub = r["subckts"][0]
        assert sub["name"] == "lpf"
        assert sub["pins"] == ["a", "b"]
        assert sub["element_names"] == ["Ra", "Ca"]
        assert sub["instances_in"] == ["X1"]
        assert sub["end_line_no"] is not None
        x1 = _el_by_name(r, "X1")
        assert x1["kind"] == "X"
        assert x1["subckt_ref"] == "lpf"
        assert x1["nodes"] == ["in", "out"]
        assert r["topology"]["hierarchy"][0]["name"] == "lpf"

    def test_model_card(self):
        deck = """* diode with model
D1 a k DMOD 1.0
.model DMOD D Is=1e-14 N=1.05 level=3
.end
"""
        r = parse_spice_netlist_text(deck)
        m = r["models"][0]
        assert m["name"] == "DMOD"
        assert m["type"] == "D"
        assert m["level"] == 3.0
        assert m["params"]["Is"] == 1e-14
        assert m["params"]["N"] == 1.05
        d1 = _el_by_name(r, "D1")
        assert d1["model"] == "DMOD"
        assert d1["nodes"] == ["a", "k"]
        assert d1["value"] == 1.0  # 面积位置值

    def test_control_cards_and_sweep(self):
        deck = """* analysis cards
.tran 1n 100n
.ac dec 10 1k 100meg
.dc V1 0 1 0.1
.op
.four 1k v(out)
.include other.inc
.end
"""
        r = parse_spice_netlist_text(deck)
        names = [c["name"] for c in r["controls"]]
        assert names == ["tran", "ac", "dc", "op", "four", "include"]
        dc = r["controls"][2]
        assert dc["sweep"]["kind"] == "dc"
        assert dc["sweep"]["source"] == "V1"
        assert dc["sweep"]["start"] == 0.0
        assert dc["sweep"]["stop"] == 1.0
        assert dc["sweep"]["step"] == 0.1
        tran = r["controls"][0]
        assert tran["args"] == ["1n", "100n"]
        assert tran["sweep"] is None

    def test_explicit_flavor_flag(self):
        r = parse_spice_netlist_text(_NGSPICE_RC, "ngspice")
        assert r["flavor"] == "ngspice"
        assert r["flavor_requested"] == "ngspice"
        assert r["flavor_detected"] is False


# ── HSPICE ───────────────────────────────────────────────────────────────────


class TestHspiceFlavor:
    def test_detection_semicolon_and_option_post(self):
        assert detect_flavor(_HSPICE_BP) == "hspice"
        deck = "R1 1 2 50 ; inline semicolon comment\n.end\n"
        assert detect_flavor(deck) == "hspice"
        r = parse_spice_netlist_text(deck)
        assert r["flavor"] == "hspice"
        assert r["elements"][0]["value"] == 50.0
        assert r["elements"][0]["params"] == {}

    def test_param_style_main_value(self):
        r = parse_spice_netlist_text(_HSPICE_BP, "hspice")
        c1 = _el_by_name(r, "C1")
        assert c1["value"] == 1e-11  # c=10p → 主值回填
        assert c1["params"]["c"] == 1e-11
        assert c1["unit"] == "farad"
        assert _el_by_name(r, "L1")["value"] == 1e-8

    def test_paren_pin_subckt(self):
        r = parse_spice_netlist_text(_HSPICE_BP, "hspice")
        sub = r["subckts"][0]
        assert sub["name"] == "notch"
        assert sub["pins"] == ["a", "b"]  # 括号 pin 形态
        assert sub["params"] == {"w": 2.0}
        assert sub["instances_in"] == ["Xnotch"]
        x = _el_by_name(r, "Xnotch")
        assert x["subckt_ref"] == "notch"
        assert x["params"] == {"w": 2.0}

    def test_tran_sweep_and_step_directives(self):
        r = parse_spice_netlist_text(_HSPICE_BP, "hspice")
        by_name = {c["name"]: c for c in r["controls"]}
        tran = by_name["tran"]
        # args=全令牌原文（含 sweep 段）；sweep 段另由 sweep 字段承载
        assert tran["args"][:3] == ["10p", "5n", "sweep"]
        assert tran["sweep"]["kind"] == "tran"
        assert tran["sweep"]["source"] == "temp"
        assert tran["sweep"]["raw_args"] == ["temp", "-40", "125", "5"]
        step = by_name["step"]
        assert step["sweep"]["kind"] == "step"
        assert step["sweep"]["source"] == "vdd"  # param=vdd → 扫描变量
        assert step["sweep"]["params"] == {"param": "vdd"}

    def test_dollar_comment_tokens_not_leaking(self):
        deck = "R1 1 2 1k $ trailing note\nC1 2 0 1p\n.end\n"
        r = parse_spice_netlist_text(deck, "hspice")
        assert len(r["elements"]) == 2
        assert r["elements"][0]["params"] == {}
        assert r["elements"][0]["nodes"] == ["1", "2"]


# ── Spectre ──────────────────────────────────────────────────────────────────


class TestSpectreFlavor:
    def test_lang_directive_detection(self):
        assert detect_flavor(_SPECTRE_BP) == "spectre"
        r = parse_spice_netlist_text(_SPECTRE_BP)
        assert r["flavor"] == "spectre"
        assert r["flavor_detected"] is True
        assert r["title"] is None  # Spectre 无标题行惯例

    def test_block_form_elements(self):
        r = parse_spice_netlist_text(_SPECTRE_BP)
        r1 = _el_by_name(r, "R1")
        assert r1["kind"] == "R"
        assert r1["nodes"] == ["in", "out"]
        assert r1["value"] == 1000.0  # resistor r= → 主值
        assert r1["unit"] == "ohm"
        assert r1["model"] == "resistor"
        c1 = _el_by_name(r, "C1")
        assert c1["value"] == 1e-12
        vd = _el_by_name(r, "Vd")
        assert vd["kind"] == "V"
        assert vd["value"] == 1.8  # vsource dc= → 主值

    def test_model_statement_and_device_kind(self):
        r = parse_spice_netlist_text(_SPECTRE_BP)
        m = r["models"][0]
        assert m["name"] == "mynmos"
        assert m["type"] == "bsim4"
        assert m["level"] == 14.0
        assert m["params"]["type"] == "nmos"
        assert m["params"]["master"] == "bsim4"
        m1 = _el_by_name(r, "M1")
        assert m1["kind"] == "M"  # bsim4 关键词 → MOSFET（bsim 名不落 B 类）
        assert m1["model"] == "mynmos"
        assert m1["params"]["w"] == 2e-6
        assert m1["params"]["l"] == pytest.approx(1.8e-7)

    def test_subckt_ends_and_instance(self):
        r = parse_spice_netlist_text(_SPECTRE_BP)
        sub = r["subckts"][0]
        assert sub["name"] == "lpf"
        assert sub["pins"] == ["in", "out"]
        assert sub["element_names"] == ["R1", "C1"]  # 子电路体元素归属 owner
        assert sub["instances_in"] == ["Xlpf"]
        assert sub["end_line_no"] is not None
        x = _el_by_name(r, "Xlpf")
        assert x["kind"] == "X"
        assert x["subckt_ref"] == "lpf"
        assert x["model"] is None  # X 类 model 恒空（subckt_ref 承载）

    def test_analysis_blocks_normalized(self):
        r = parse_spice_netlist_text(_SPECTRE_BP)
        by_name = {c["name"]: c for c in r["controls"] if "instance" in c}
        tran = by_name["tran"]
        assert tran["instance"] == "tran1"  # 命名分析块实例名
        assert tran["params"] == {"stop": 1e-6}
        ac = by_name["ac"]
        assert ac["args"] == ["dec", "10", "1k", "100meg"]
        params_ctrl = next(c for c in r["controls"] if c["name"] == "parameters")
        assert params_ctrl["params"]["f0"] == 1e9

    def test_sweep_statement(self):
        r = parse_spice_netlist_text(_SPECTRE_BP)
        sw = next(c for c in r["controls"] if c["name"] == "sweep")
        assert sw["instance"] == "sw1"
        assert sw["sweep"]["kind"] == "sweep"
        assert sw["sweep"]["declared"] is True
        assert sw["params"]["dev"] == "Vd"

    def test_comment_styles(self):
        deck = """// line comment
/* block
   comment */
R1 (a b) resistor r=1k // trailing
C1 (b 0) capacitor c=1p
"""
        r = parse_spice_netlist_text(deck, "spectre")
        assert len(r["elements"]) == 2
        assert r["elements"][0]["nodes"] == ["a", "b"]
        assert r["structural_errors"] == []


# ── 拓扑 ─────────────────────────────────────────────────────────────────────


class TestTopology:
    def test_bidirectional_graph(self):
        r = parse_spice_netlist_text(_NGSPICE_RC)
        topo = r["topology"]
        assert topo["node_elements"]["in"] == ["V1", "R1"]
        assert topo["node_elements"]["out"] == ["R1", "C1", "Rload"]
        assert topo["element_nodes"]["R1"] == ["in", "out"]
        # 双向一致性：node→elements 与 element→nodes 互逆（计数守恒）
        n_fwd = sum(len(v) for v in topo["node_elements"].values())
        n_bwd = sum(len(v) for v in topo["element_nodes"].values())
        assert n_fwd == n_bwd

    def test_ground_normalization(self):
        deck = """* ground aliases
V1 a gnd 1
R1 a GND 2
R2 a gnd! 3
R3 a 0 4
.end
"""
        r = parse_spice_netlist_text(deck)
        assert r["topology"]["ground_nodes"] == ["0"]
        assert all(e["nodes"][-1] == "0" for e in r["elements"])
        assert r["topology"]["n_non_ground_nodes"] == 1  # 仅 a

    def test_isolated_node_detection(self):
        deck = """* floating node
V1 a 0 0
R1 a b 1k
R2 c 0 2k
.end
"""
        r = parse_spice_netlist_text(deck)
        # a 双连接（V1+R1）非孤立；b/c 皆单连接（b: R1 一条；c: R2 一条）
        assert sorted(r["topology"]["isolated_nodes"]) == ["b", "c"]
        assert any("孤立节点" in w for w in r["warnings"])

    def test_mna_dimension(self):
        deck = """* mna branches: V/E/H 增广分支电流
V1 a 0 1
E1 b 0 a 0 2
H1 c 0 V1 3
R1 a b 1k
R2 b c 2k
.end
"""
        r = parse_spice_netlist_text(deck)
        topo = r["topology"]
        assert topo["n_non_ground_nodes"] == 3  # a b c
        assert topo["n_branches"] == 3  # V1/E1/H1
        assert topo["mna_size"] == 6

    def test_hierarchy_nested_and_recursive(self):
        deck = """two-level chain and self referencing subckt
Xtop in 0 lv1
.subckt lv1 a b
Xmid a b lv2
.ends lv1
.subckt lv2 a b
Xself a b lv2
Rd a b 1k
.ends lv2
.end
"""
        r = parse_spice_netlist_text(deck)
        tree = r["topology"]["hierarchy"]
        assert tree[0]["name"] == "lv1"
        assert tree[0]["children"][0]["name"] == "lv2"
        # 自引用环截断：lv2 的 children 中 self 引用记 recursive 不穷举
        kids = tree[0]["children"][0]["children"]
        assert kids[0]["name"] == "lv2"
        assert kids[0]["recursive"] is True
        assert kids[0]["children"] == []

    def test_subckt_body_excluded_from_top_level(self):
        r = parse_spice_netlist_text(_HSPICE_BP, "hspice")
        topo = r["topology"]
        # 子电路体元素（Rn/Cn）与体节点（a/b）不进顶层拓扑
        assert "Rn" not in topo["element_nodes"]
        assert "a" not in topo["node_elements"]
        assert set(topo["element_nodes"]) == {
            "V1", "R1", "C1", "L1", "Xnotch",
        }
        assert topo["scope_note"].startswith("top-level only")


# ── 负例与统一 schema ────────────────────────────────────────────────────────


class TestNegativesAndUniform:
    def test_unknown_letter_structural_error(self):
        # 首行=标题（SPICE 惯例）；数字开头令牌不可为元件名 → 结构错误
        deck = "bad element deck\n9dummy a b 1k\nR1 a b 2k\n.end\n"
        r = parse_spice_netlist_text(deck)
        assert len(r["structural_errors"]) == 1
        assert "未知元件类型" in r["structural_errors"][0]
        assert r["title"] == "bad element deck"
        assert r["summary"]["n_structural_errors"] == 1
        # fail-soft：合法元件仍解析
        assert _el_by_name(r, "R1")["value"] == 2000.0

    def test_unbalanced_subckt_error(self):
        deck = ".subckt broken a b\nRa a b 1k\n.end\n"
        r = parse_spice_netlist_text(deck)
        assert any("未关闭" in e and ".ends" in e for e in r["structural_errors"])
        assert r["subckts"][0]["end_line_no"] is None

    def test_ends_without_subckt_error(self):
        deck = "R1 a 0 1k\n.ends\n.end\n"
        r = parse_spice_netlist_text(deck)
        assert any("无匹配" in e for e in r["structural_errors"])

    @pytest.mark.parametrize("text,flavor", [
        (_NGSPICE_RC, "ngspice"),
        (_HSPICE_BP, "hspice"),
        (_SPECTRE_BP, "spectre"),
    ])
    def test_unified_schema_keys_all_flavors(self, text, flavor):
        r = parse_spice_netlist_text(text, flavor)
        assert r["schema"] == f"spice_netlist/{PARSER_SCHEMA_VERSION}"
        for key in FIVE_KEYS:
            assert key in r
            assert r[key] is not None
        assert set(FIVE_KEYS).issubset(r.keys())
        assert {"flavor", "flavor_requested", "flavor_detected",
                "summary", "structural_errors", "warnings"} <= set(r.keys())
        assert r["summary"]["n_elements"] == len(r["elements"])
        # 全 JSON 原生类型（服务层信封直出的前提）
        json.dumps(r)

    def test_invalid_flavor_raises(self):
        with pytest.raises(ValueError, match="不在词表"):
            normalize_flavor("spectre!")
        with pytest.raises(ValueError, match="不在词表"):
            parse_spice_netlist_text("R1 a 0 1k\n.end\n", "pads")
        assert normalize_flavor("AUTO") == "auto"  # 大小写归一

    def test_expression_value_preserved_raw(self):
        deck = "R1 a b {1k*2}\nC1 a b '2p*3'\n.end\n"
        r = parse_spice_netlist_text(deck)
        r1 = _el_by_name(r, "R1")
        assert r1["value"] is None  # 表达式不代入（解析器契约）
        assert r1["value_raw"] == "{1k*2}"
        c1 = _el_by_name(r, "C1")
        assert c1["value_raw"] == "'2p*3'"

    def test_f_h_control_source_tokens(self):
        deck = """* current controlled sources: 第 3 令牌=控制源名非 node
F1 n1 n2 V1 0.99
H1 n3 n4 V1 50
.end
"""
        r = parse_spice_netlist_text(deck)
        f1 = _el_by_name(r, "F1")
        assert f1["nodes"] == ["n1", "n2"]  # 端口对
        assert f1["control_source"] == "V1"
        assert f1["value"] == 0.99
        h1 = _el_by_name(r, "H1")
        assert h1["control_source"] == "V1"
        assert h1["value"] == 50.0
        assert h1["kind_desc"] == "ccvs"

    def test_k_mutual_inductance(self):
        deck = "L1 a b 1u\nL2 c d 2u\nK1 L1 L2 0.95\n.end\n"
        r = parse_spice_netlist_text(deck)
        k1 = _el_by_name(r, "K1")
        assert k1["kind"] == "K"
        assert k1["nodes"] == []
        assert k1["params"] == {"inductors": ["L1", "L2"]}
        assert k1["value"] == 0.95

    def test_spice_letter_kinds_table_complete(self):
        # 26 ASCII 字母全覆盖（未知首字母仅非字母/数字可达——负例守卫口径）
        import string
        assert frozenset(string.ascii_uppercase) == SPICE_LETTER_KINDS

    def test_empty_and_comment_only_deck(self):
        r = parse_spice_netlist_text("* only a title comment\n* another\n")
        assert r["elements"] == []
        assert r["controls"] == []
        assert r["summary"]["n_elements"] == 0
        assert r["topology"]["n_nodes"] == 0
        assert r["structural_errors"] == []
