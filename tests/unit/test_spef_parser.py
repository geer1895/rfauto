"""SPEF（IEEE 1481 寄生交换格式）解析内核+服务+CLI 薄壳单测
（aurora_q Q-X60 席位，2026-11-07）。

覆盖面（任务书 ≥60 条）：

- 单位映射表驱动：spef_unit_factor 四族（c/r/l/t）大小写不敏感+未知
  单位/未知族 None；头部乘数×基准（``*C_UNIT 1000 FF``）；未知单位
  fail-closed（warning+系数 1.0 原值保留）；CAP 值→法拉换算表驱动；
- 头部：版本串（引号含空格不切碎）/design/date/vendor（引号内 ``//``
  保真）/design_flow 多串/dividers 与 bus_delimiters 缺省+自定义；
  *SCALE 如实登记；
- NAME_MAP 双向：id→name 主映射+name→id 反查往返；重复 id 后者覆盖+
  warning（反查一致）；重复名告警（反查首 id 胜出）；未映射 ``*id``
  保真展开 ``<*id>``（含尾段 ``<*id>:3``）；自定义 DELIMITER_CHAR；
- PORTS：方向 I/O/B；id 引用展开；词表外/缺方向 → None+warning；
- D_NET 四段：CONN（*P/*I direction-first 与 type-first 双形态、坐标/
  层注记、字段不足跳行）、CAP（两列对地/三列耦合分派、coupling 标志
  变体、非法列数/非整数序号/非数值跳行 warning）、RES/IND（换算+非法
  列数）、*END 缺失收口、段外子段关键词、未知指令、游离行、注释两形态；
- 总电容一致性三数字（total_cap_far/cap_sum_far/cap_rel_diff）：
  一致场景 0、构造失配场景 −0.5、零申报 None、非数值申报 None；
- 拓扑三函数：逐 net 节点/元件/连通分量（并查集）+孤立节点（仅 CONN
  声明零元件节点）、totals、全连通零孤立、不改 doc；耦合统计计数/
  总和/比值/top-k 截断/排序稳定性（并列按文档序）/对地零比值 None；
  net 按名查询命中/未命中/未映射名；
- 服务三函数信封契约（ok/error 两态；errors 恒 list[str]；不可读/空/
  无 *SPEF 头 → error；Latin-1 兜底；net 未命中带可用名录）；
- CLI（**局部父 Typer 自测**——共享 app 接线由主代合流统一，本席禁改
  cli/main.py）：parse/report --json 全结构+human 紧凑面+失败信封
  同构（exit 1）+缺 --file usage 错（exit 2）+--top-k 透传+--help
  真构建（#305）+help 字符卫生（裸 ``[``/未成对 ``%`` 零违例，D-06 门
  同判定面预检）+域叶形状钉。

单测零网络零真机；文件面一律 tmp_path（#144 run 湖零写入）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from rfauto.cli.domains.spef import spef_app
from rfauto.core.spef_parser import (
    PARSER_SCHEMA_VERSION,
    UNIT_SCALES,
    SpefParseError,
    parse_spef,
    spef_coupling_stats,
    spef_net_lookup,
    spef_topology_summary,
    spef_unit_factor,
)
from rfauto.service.spef_service import (
    parse_spef_file,
    spef_net_detail,
    spef_report,
)

# ── 夹具：头部全量+NAME_MAP 5 条+PORTS 3+两个 D_NET ─────────────────────
# net1（clk）：CONN 3 行（*P+两 *I）+CAP 对地 2+耦合 3（含 *C 标志变体）+
#   RES 3+IND 1；值按头部 C_UNIT=PF 口径书写（科学计数 5.0e-01 混写）。
# net2（data_a）：仅 1 对地电容+1 电阻；CONN 声明 u1:D 零元件=孤立节点构造。
SAMPLE_SPEF = """\
*SPEF "IEEE 1481-1998"
*DESIGN "top_block"
*DATE "2026-11-07"
*VENDOR "test_vendor"
*PROGRAM "test_extract"
*VERSION "1.0"
*DESIGN_FLOW "NETLIST_TYPE_VERILOG" "PIN_CAP NONE"
*DIVIDER /
*DELIMITER_CHAR :
*BUS_DELIMITER_CHAR [ ]
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY

*NAME_MAP
*10001 clk
*10002 data_a
*10003 data_b
*20001 u1
*20002 u1:CK

*PORTS
clk I
data_a I
data_b O

*D_NET *10001 1.5
*CONN
*P clk I
*I *20002 I *C 10.0 20.0 *L M1 M2
*I *20001:Q O
*CAP
1 *10001:1 5.0e-01
2 *10001:2 0.3
3 *10001:2 *10002:1 0.2
4 *10001:3 *20001:Q 0.1
5 *10001:3 *10002:2 0.4 *C
*RES
1 *10001:1 *10001:2 10.0
2 *10001:2 *10001:3 20.0
3 *10001:3 *10001:1 30.0
*IND
1 *10001:1 *10001:2 1.0e-9
*END

*D_NET *10002 0.2
*CONN
*I *20001:D I
*CAP
1 *10002:1 0.2
*RES
1 *10002:1 *10002:2 5.0
*END
"""

#: 最小头部（单测内联拼装用）。
MINI_HEAD = '*SPEF "IEEE 1481-1998"\n*DESIGN "mini"\n*C_UNIT 1 PF\n'

runner = CliRunner()


def _ap(expected: Any, rel: float = 1e-9, **kw: Any) -> Any:
    """严格近似比较：``abs`` 缺省 0。

    pytest.approx 缺省 abs=1e-12 的绝对容差会吞掉皮法/飞法量级数值
    （``3e-13 == approx(5e-13)`` 恒真=判据失效，#118 家族）——本文件全部
    SI 小量断言一律走本函数（相对容差口径）。
    """
    kw.setdefault("abs", 0.0)
    return pytest.approx(expected, rel=rel, **kw)


def _mini(body: str, head: str = MINI_HEAD) -> dict[str, Any]:
    """最小头部+正文 → 解析 doc（内联用例拼装器）。"""
    return parse_spef(head + body)


def _net_body(cap_lines: str = "", res_lines: str = "",
              total: str = "1.0") -> str:
    """单 D_NET 正文拼装（id=*1，未映射名=<*1>）。"""
    return (f"*D_NET *1 {total}\n*CAP\n{cap_lines}*RES\n{res_lines}*END\n")


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return parse_spef(SAMPLE_SPEF)


@pytest.fixture(scope="module")
def net1(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["nets"][0]


@pytest.fixture(scope="module")
def net2(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["nets"][1]


@pytest.fixture()
def spef_file(tmp_path: Path) -> Path:
    f = tmp_path / "sample.spef"
    f.write_text(SAMPLE_SPEF, encoding="utf-8")
    return f


@pytest.fixture(scope="module")
def local_app() -> typer.Typer:
    """局部父 Typer（共享 app 接线待主代合流；本席自测不经 cli/main）。"""
    parent = typer.Typer()
    parent.add_typer(spef_app, name="spef")
    return parent


# ── 单位映射表驱动 ──────────────────────────────────────────────────────


class TestUnitFactors:
    @pytest.mark.parametrize(("kind", "unit", "expected"), [
        ("c", "PF", 1e-12),
        ("c", "NF", 1e-9),
        ("c", "FF", 1e-15),
        ("c", "UF", 1e-6),
        ("c", "F", 1.0),
        ("r", "OHM", 1.0),
        ("r", "KOHM", 1e3),
        ("r", "MOHM", 1e6),
        ("l", "HENRY", 1.0),
        ("l", "MH", 1e-3),
        ("l", "UH", 1e-6),
        ("l", "NH", 1e-9),
        ("l", "PH", 1e-12),
        ("t", "NS", 1e-9),
        ("t", "PS", 1e-12),
    ])
    def test_unit_table(self, kind: str, unit: str, expected: float) -> None:
        assert spef_unit_factor(kind, unit) == _ap(expected, rel=1e-15)

    @pytest.mark.parametrize("unit", ["pf", "Pf", " PF "])
    def test_case_and_space_insensitive(self, unit: str) -> None:
        assert spef_unit_factor("c", unit) == _ap(1e-12)

    def test_unknown_unit_returns_none(self) -> None:
        assert spef_unit_factor("c", "XF") is None

    def test_unknown_kind_returns_none(self) -> None:
        assert spef_unit_factor("z", "PF") is None

    def test_table_has_four_kinds(self) -> None:
        assert set(UNIT_SCALES) == {"c", "r", "l", "t"}

    def test_strict_approx_oracle_can_fail(self) -> None:
        # 判据自检：皮法量级差异必须可见（缺省 approx 在此会假绿）
        assert _ap(5e-13) != 3e-13
        assert pytest.approx(5e-13) == 3e-13  # 缺省容差吞差异的反证

    def test_header_multiplier_times_base(self) -> None:
        # 乘数×基准：1000 FF = 1 pF；0.5 单位 → 0.5 pF = 5e-13 F
        d = _mini(_net_body("1 *1:1 0.5\n"),
                  head='*SPEF "x"\n*C_UNIT 1000 FF\n')
        assert d["header"]["units"]["c"]["factor_si"] == _ap(1e-12)
        assert d["nets"][0]["caps_gnd"][0]["value_far"] == _ap(5e-13)

    def test_unknown_unit_fail_closed_keeps_raw(self) -> None:
        d = _mini(_net_body("1 *1:1 0.5\n"),
                  head='*SPEF "x"\n*C_UNIT 1 XF\n')
        assert d["header"]["units"]["c"]["factor_si"] == 1.0
        assert d["nets"][0]["caps_gnd"][0]["value_far"] == _ap(0.5)
        assert any("未知C单位" in w for w in d["warnings"])

    @pytest.mark.parametrize(("c_unit", "raw", "expected_far"), [
        ("1 PF", "1.0", 1e-12),
        ("1 NF", "1.0", 1e-9),
        ("1 FF", "1.0", 1e-15),
        ("1 UF", "2.5", 2.5e-6),
        ("1 F", "3.0", 3.0),
        ("1 PF", "1.23450e-03", 1.2345e-15),
    ])
    def test_cap_value_to_farad(self, c_unit: str, raw: str,
                                expected_far: float) -> None:
        d = _mini(_net_body(f"1 *1:1 {raw}\n"),
                  head=f'*SPEF "x"\n*C_UNIT {c_unit}\n')
        assert d["nets"][0]["caps_gnd"][0]["value_far"] == _ap(
            expected_far, rel=1e-12)

    def test_r_unit_kohm_conversion(self) -> None:
        d = _mini(_net_body(res_lines="1 *1:1 *1:2 10\n"),
                  head='*SPEF "x"\n*R_UNIT 1 KOHM\n')
        assert d["nets"][0]["res"][0]["value_ohm"] == _ap(1e4)

    def test_l_unit_nh_conversion(self) -> None:
        body = "*D_NET *1 0\n*IND\n1 *1:1 *1:2 2.0\n*END\n"
        d = _mini(body, head='*SPEF "x"\n*L_UNIT 1 NH\n')
        assert d["nets"][0]["inds"][0]["value_henry"] == _ap(2e-9)


# ── 头部 ────────────────────────────────────────────────────────────────


class TestHeader:
    def test_version_string_with_space_intact(self, doc: dict) -> None:
        assert doc["header"]["spef_version"] == "IEEE 1481-1998"

    def test_design_and_meta_fields(self, doc: dict) -> None:
        h = doc["header"]
        assert h["design"] == "top_block"
        assert h["date"] == "2026-11-07"
        assert h["vendor"] == "test_vendor"
        assert h["program"] == "test_extract"
        assert h["version"] == "1.0"

    def test_design_flow_multi_quoted(self, doc: dict) -> None:
        assert doc["header"]["design_flow"] == [
            "NETLIST_TYPE_VERILOG", "PIN_CAP NONE"]

    def test_dividers_and_bus_delimiters(self, doc: dict) -> None:
        assert doc["header"]["dividers"] == {"divider": "/", "delimiter": ":"}
        assert doc["header"]["bus_delimiters"] == ["[", "]"]

    def test_defaults_when_undeclared(self) -> None:
        d = parse_spef('*SPEF "x"\n')
        assert d["header"]["dividers"] == {"divider": "/", "delimiter": ":"}
        assert d["header"]["bus_delimiters"] == ["[", "]"]
        assert d["header"]["units"] == {"r": None, "c": None, "l": None, "t": None}

    def test_units_all_four_declared(self, doc: dict) -> None:
        u = doc["header"]["units"]
        assert u["c"]["factor_si"] == _ap(1e-12)
        assert u["r"]["factor_si"] == _ap(1.0)
        assert u["l"]["factor_si"] == _ap(1.0)
        assert u["t"]["factor_si"] == _ap(1e-9)
        assert u["c"]["declared"] == "1 PF"

    def test_custom_bus_delimiters(self) -> None:
        d = parse_spef('*SPEF "x"\n*BUS_DELIMITER_CHAR < >\n')
        assert d["header"]["bus_delimiters"] == ["<", ">"]

    def test_quoted_double_slash_not_comment(self) -> None:
        d = parse_spef('*SPEF "x"\n*VENDOR "http://v.example" // tail\n')
        assert d["header"]["vendor"] == "http://v.example"
        assert d["warnings"] == []

    def test_scale_registered(self) -> None:
        d = parse_spef('*SPEF "x"\n*SCALE 1 1 NS PF\n')
        assert d["header"]["scale"] == ["1", "1", "NS", "PF"]
        assert d["warnings"] == []

    def test_schema_version_key(self, doc: dict) -> None:
        assert doc["schema"] == f"spef/{PARSER_SCHEMA_VERSION}"


# ── NAME_MAP 双向 ───────────────────────────────────────────────────────


class TestNameMap:
    def test_five_entries_id_to_name(self, doc: dict) -> None:
        assert doc["name_map"] == {
            "10001": "clk", "10002": "data_a", "10003": "data_b",
            "20001": "u1", "20002": "u1:CK",
        }

    def test_reverse_round_trip(self, doc: dict) -> None:
        rev = doc["name_map_reverse"]
        for map_id, name in doc["name_map"].items():
            assert rev[name] == map_id

    def test_duplicate_id_later_overrides_with_warning(self) -> None:
        d = parse_spef('*SPEF "x"\n*NAME_MAP\n*1 alpha\n*1 beta\n')
        assert d["name_map"] == {"1": "beta"}
        assert d["name_map_reverse"] == {"beta": "1"}
        assert any("重复 id" in w for w in d["warnings"])

    def test_duplicate_name_warns_first_id_wins(self) -> None:
        d = parse_spef('*SPEF "x"\n*NAME_MAP\n*1 same\n*2 same\n')
        assert d["name_map"] == {"1": "same", "2": "same"}
        assert d["name_map_reverse"] == {"same": "1"}
        assert any("重复名" in w for w in d["warnings"])

    def test_unmapped_bare_ref_fidelity(self) -> None:
        d = _mini(_net_body("1 *99999 0.1\n"))
        assert d["nets"][0]["caps_gnd"][0]["node"] == "<*99999>"

    def test_unmapped_ref_with_tail_fidelity(self) -> None:
        d = _mini(_net_body("1 *99999:3 0.1\n"))
        assert d["nets"][0]["caps_gnd"][0]["node"] == "<*99999>:3"

    def test_unmapped_dnet_name_fidelity(self) -> None:
        d = _mini(_net_body("1 *1:1 0.1\n"))
        assert d["nets"][0]["name"] == "<*1>"
        assert d["nets"][0]["id"] == "1"

    def test_literal_node_passthrough(self) -> None:
        d = _mini(_net_body("1 netA:1 0.1\n"))
        assert d["nets"][0]["caps_gnd"][0]["node"] == "netA:1"

    def test_id_plus_delimiter_form_resolves(self, net1: dict) -> None:
        # *20001:Q → u1 + : + Q
        assert net1["conn"][2]["node"] == "u1:Q"

    def test_whole_token_inst_pin_form_resolves(self, net1: dict) -> None:
        # *20002 → u1:CK（inst:pin 整名折叠形态）
        assert net1["conn"][1]["node"] == "u1:CK"

    def test_custom_delimiter_char(self) -> None:
        head = '*SPEF "x"\n*DELIMITER_CHAR .\n*C_UNIT 1 PF\n*NAME_MAP\n*7 sig\n'
        d = parse_spef(head + "*D_NET *7 0.1\n*CAP\n1 *7.2 0.1\n*END\n")
        assert d["nets"][0]["caps_gnd"][0]["node"] == "sig.2"


# ── PORTS ──────────────────────────────────────────────────────────────


class TestPorts:
    def test_three_ports_directions(self, doc: dict) -> None:
        assert doc["ports"] == [
            {"name": "clk", "direction": "I"},
            {"name": "data_a", "direction": "I"},
            {"name": "data_b", "direction": "O"},
        ]

    def test_port_id_ref_resolved(self) -> None:
        d = parse_spef('*SPEF "x"\n*NAME_MAP\n*5 pad\n*PORTS\n*5 B\n')
        assert d["ports"] == [{"name": "pad", "direction": "B"}]

    def test_unknown_direction_none_with_warning(self) -> None:
        d = parse_spef('*SPEF "x"\n*PORTS\np1 X\n')
        assert d["ports"][0]["direction"] is None
        assert any("PORTS 方向词表外" in w for w in d["warnings"])

    def test_missing_direction_none_with_warning(self) -> None:
        d = parse_spef('*SPEF "x"\n*PORTS\np1\n')
        assert d["ports"][0]["direction"] is None
        assert any("PORTS 行缺方向" in w for w in d["warnings"])


# ── CONN 段 ─────────────────────────────────────────────────────────────


class TestConn:
    def test_p_line(self, net1: dict) -> None:
        assert net1["conn"][0] == {"kind": "P", "node": "clk", "direction": "I"}

    def test_i_line_coords_and_layers(self, net1: dict) -> None:
        c = net1["conn"][1]
        assert c["kind"] == "I"
        assert c["direction"] == "I"
        assert c["coords"] == [10.0, 20.0]
        assert c["layers"] == ["M1", "M2"]
        assert "type" not in c  # direction-first 形态 type 缺席

    def test_type_first_form(self) -> None:
        d = _mini("*D_NET *1 0\n*CONN\n*I u2:A D I\n*END\n")
        c = d["nets"][0]["conn"][0]
        assert c == {"kind": "I", "node": "u2:A", "type": "D", "direction": "I"}

    def test_type_first_bad_direction_none(self) -> None:
        d = _mini("*D_NET *1 0\n*CONN\n*I u2:A D X\n*END\n")
        assert d["nets"][0]["conn"][0]["direction"] is None
        assert any("CONN 方向词表外" in w for w in d["warnings"])

    def test_short_conn_line_skipped(self) -> None:
        d = _mini("*D_NET *1 0\n*CONN\n*P clk\n*END\n")
        assert d["nets"][0]["conn"] == []
        assert any("CONN 行字段不足" in w for w in d["warnings"])

    def test_non_numeric_coords_warned(self) -> None:
        d = _mini("*D_NET *1 0\n*CONN\n*I u2:A I *C a b\n*END\n")
        assert "coords" not in d["nets"][0]["conn"][0]
        assert any("CONN 坐标非数值" in w for w in d["warnings"])


# ── CAP/RES/IND 段 ──────────────────────────────────────────────────────


class TestCapResInd:
    def test_ground_caps(self, net1: dict) -> None:
        nodes = [c["node"] for c in net1["caps_gnd"]]
        vals = [c["value_far"] for c in net1["caps_gnd"]]
        assert nodes == ["clk:1", "clk:2"]
        assert vals == _ap([5e-13, 3e-13])

    def test_coupling_caps_node_pairs(self, net1: dict) -> None:
        pairs = [(c["node1"], c["node2"]) for c in net1["caps_cpl"]]
        assert pairs == [("clk:2", "data_a:1"), ("clk:3", "u1:Q"),
                         ("clk:3", "data_a:2")]
        assert [c["value_far"] for c in net1["caps_cpl"]] == _ap(
            [2e-13, 1e-13, 4e-13])

    def test_coupling_flag_variant_recorded(self, net1: dict) -> None:
        assert net1["caps_cpl"][2]["flag"] == "*C"
        assert "flag" not in net1["caps_cpl"][0]

    def test_cap_illegal_column_count_skipped(self) -> None:
        d = _mini(_net_body("1 *1:1\n2 *1:1 0.1\n"))
        assert len(d["nets"][0]["caps_gnd"]) == 1
        assert any("CAP 行列数非法" in w for w in d["warnings"])

    def test_cap_five_data_columns_skipped(self) -> None:
        d = _mini(_net_body("1 a b c d 0.1\n"))
        assert d["nets"][0]["caps_gnd"] == []
        assert d["nets"][0]["caps_cpl"] == []
        assert any("CAP 行列数非法" in w for w in d["warnings"])

    def test_cap_non_integer_index_skipped(self) -> None:
        d = _mini(_net_body("x *1:1 0.1\n"))
        assert d["nets"][0]["caps_gnd"] == []
        assert any("CAP 序号非整数" in w for w in d["warnings"])

    def test_cap_non_numeric_value_skipped(self) -> None:
        d = _mini(_net_body("1 *1:1 abc\n"))
        assert d["nets"][0]["caps_gnd"] == []
        assert any("CAP 电容值非数值" in w for w in d["warnings"])

    def test_res_values_ohm(self, net1: dict) -> None:
        assert [r["value_ohm"] for r in net1["res"]] == _ap(
            [10.0, 20.0, 30.0])
        assert net1["res_count"] == 3

    def test_ind_value_henry(self, net1: dict) -> None:
        assert net1["inds"] == [
            {"node1": "clk:1", "node2": "clk:2", "value_henry": _ap(1e-9)}]
        assert net1["ind_count"] == 1

    def test_res_illegal_column_count_skipped(self) -> None:
        d = _mini(_net_body(res_lines="1 *1:1 10\n"))
        assert d["nets"][0]["res"] == []
        assert any("RES 行列数非法" in w for w in d["warnings"])

    def test_res_non_numeric_value_skipped(self) -> None:
        d = _mini(_net_body(res_lines="1 *1:1 *1:2 xyz\n"))
        assert d["nets"][0]["res"] == []
        assert any("RES 数值非数值" in w for w in d["warnings"])


# ── D_NET 状态机杂项 ────────────────────────────────────────────────────


class TestDNetStateMachine:
    def test_ids_names_and_order(self, doc: dict) -> None:
        assert [(n["id"], n["name"]) for n in doc["nets"]] == [
            ("10001", "clk"), ("10002", "data_a")]

    def test_total_cap_header_raw_and_farad(self, net1: dict) -> None:
        assert net1["total_cap_header"] == _ap(1.5)
        assert net1["total_cap_far"] == _ap(1.5e-12)

    def test_dnet_line_number(self, net1: dict) -> None:
        assert net1["line"] == SAMPLE_SPEF.splitlines().index(
            "*D_NET *10001 1.5") + 1

    def test_missing_end_finalizes_with_warning(self) -> None:
        d = _mini("*D_NET *1 0.1\n*CAP\n1 *1:1 0.1\n")
        assert d["nets"][0]["cap_sum_far"] == _ap(1e-13)
        assert any("*END 缺失" in w for w in d["warnings"])

    def test_short_dnet_line_warned(self) -> None:
        d = _mini("*D_NET *1\n*END\n")
        assert d["nets"] == []
        assert any("D_NET 行字段不足" in w for w in d["warnings"])

    def test_section_keyword_outside_dnet(self) -> None:
        d = _mini("*CAP\n")
        assert any("段外出现" in w for w in d["warnings"])

    def test_unknown_directive_warned(self) -> None:
        d = _mini("*FOO bar\n")
        assert any("未知指令 *FOO" in w for w in d["warnings"])

    def test_stray_data_line_warned(self) -> None:
        d = _mini("garbage line here\n")
        assert any("游离数据行" in w for w in d["warnings"])

    def test_comment_forms_ignored(self) -> None:
        body = ("// full line comment\n# hash comment variant\n"
                "*D_NET *1 0.1 // trailing\n*CAP\n1 *1:1 0.1\n*END\n")
        d = _mini(body)
        assert d["warnings"] == []
        assert len(d["nets"][0]["caps_gnd"]) == 1

    def test_trailing_hash_comment_ignored(self) -> None:
        # 前接空白的行尾 # 注释：不污染列数（否则 CAP 行会被判非法列数跳行）
        d = _mini(_net_body("1 *1:1 0.1 # extractor note\n"))
        assert d["warnings"] == []
        assert d["nets"][0]["caps_gnd"][0]["value_far"] == _ap(1e-13)

    def test_hash_inside_token_not_comment(self) -> None:
        # 词内 #（非空白前接）不是注释起点——如实保留为名字一部分
        d = _mini(_net_body("1 net#a:1 0.1\n"))
        assert d["nets"][0]["caps_gnd"][0]["node"] == "net#a:1"

    def test_empty_dnet_sections(self) -> None:
        d = _mini("*D_NET *1 0\n*END\n")
        n = d["nets"][0]
        assert n["conn"] == [] and n["caps_gnd"] == [] and n["res"] == []
        assert n["cap_sum_far"] == 0.0

    def test_sample_has_zero_warnings(self, doc: dict) -> None:
        assert doc["warnings"] == []

    def test_stats_counts(self, doc: dict) -> None:
        assert doc["stats"] == {
            "n_name_map": 5, "n_ports": 3, "n_nets": 2, "n_conn": 4,
            "n_caps_gnd": 3, "n_caps_cpl": 3, "n_res": 4, "n_ind": 1,
            "n_warnings": 0,
        }

    def test_missing_spef_header_raises(self) -> None:
        with pytest.raises(SpefParseError, match=r"\*SPEF"):
            parse_spef("*DESIGN x\n")

    def test_empty_text_raises(self) -> None:
        with pytest.raises(SpefParseError):
            parse_spef("")

    def test_deterministic_and_json_native(self) -> None:
        a = parse_spef(SAMPLE_SPEF)
        b = parse_spef(SAMPLE_SPEF)
        assert a == b
        assert json.loads(json.dumps(a)) == a  # 全 JSON 原生类型


# ── 总电容一致性三数字 ──────────────────────────────────────────────────


class TestCapSumConsistency:
    def test_consistent_sample_rel_diff_zero(self, net1: dict, net2: dict) -> None:
        assert net1["cap_sum_far"] == _ap(1.5e-12)
        assert net1["cap_rel_diff"] == _ap(0.0, abs=1e-12)
        assert net2["cap_rel_diff"] == _ap(0.0, abs=1e-12)

    def test_mismatch_reports_rel_diff(self) -> None:
        # 申报 1.0 PF、段内求和 0.5 PF → rel_diff=(0.5-1.0)/1.0=-0.5
        d = _mini(_net_body("1 *1:1 0.3\n2 *1:1 *1:2 0.2\n", total="1.0"))
        n = d["nets"][0]
        assert n["total_cap_far"] == _ap(1e-12)
        assert n["cap_sum_far"] == _ap(5e-13)
        assert n["cap_rel_diff"] == _ap(-0.5)

    def test_zero_reported_rel_diff_none(self) -> None:
        d = _mini(_net_body("1 *1:1 0.1\n", total="0"))
        assert d["nets"][0]["cap_rel_diff"] is None

    def test_non_numeric_total_rel_diff_none(self) -> None:
        d = _mini(_net_body("1 *1:1 0.1\n", total="n/a"))
        n = d["nets"][0]
        assert n["total_cap_header"] is None
        assert n["total_cap_far"] is None
        assert n["cap_rel_diff"] is None
        assert any("D_NET 总电容非数值" in w for w in d["warnings"])


# ── 拓扑摘要 ────────────────────────────────────────────────────────────


class TestTopologySummary:
    def test_net1_counts(self, doc: dict) -> None:
        t = spef_topology_summary(doc)["nets"][0]
        assert t["name"] == "clk"
        assert t["node_count"] == 8
        assert t["element_count"] == 9
        assert t["component_count"] == 3

    def test_net1_isolated_conn_only_nodes(self, doc: dict) -> None:
        # clk（*P 端口）与 u1:CK（*I）CONN 声明但零元件触碰；u1:Q 被耦合
        # 电容触碰→不算孤立（宁多报不误报口径的反例钉）
        t = spef_topology_summary(doc)["nets"][0]
        assert t["isolated_nodes"] == ["clk", "u1:CK"]

    def test_net2_isolated_node(self, doc: dict) -> None:
        t = spef_topology_summary(doc)["nets"][1]
        assert t["node_count"] == 3
        assert t["element_count"] == 2
        assert t["component_count"] == 2
        assert t["isolated_nodes"] == ["u1:D"]

    def test_totals(self, doc: dict) -> None:
        assert spef_topology_summary(doc)["totals"] == {
            "n_nets": 2, "n_nodes": 11, "n_elements": 11,
            "n_components": 5, "n_isolated": 3,
        }

    def test_fully_connected_zero_isolated(self) -> None:
        d = _mini("*D_NET *1 0\n*CONN\n*P a I\n*RES\n1 a b 1\n*END\n")
        t = spef_topology_summary(d)["nets"][0]
        assert t["isolated_nodes"] == []
        assert t["component_count"] == 1

    def test_disjoint_pairs_two_components(self) -> None:
        d = _mini(_net_body(res_lines="1 a b 1\n2 c d 1\n"))
        t = spef_topology_summary(d)["nets"][0]
        assert t["component_count"] == 2
        assert t["node_count"] == 4

    def test_no_nets_zero_totals(self) -> None:
        d = parse_spef('*SPEF "x"\n')
        s = spef_topology_summary(d)
        assert s["nets"] == []
        assert s["totals"]["n_nodes"] == 0

    def test_does_not_mutate_doc(self) -> None:
        d = parse_spef(SAMPLE_SPEF)
        before = copy.deepcopy(d)
        spef_topology_summary(d)
        spef_coupling_stats(d)
        assert d == before


# ── 耦合统计 ────────────────────────────────────────────────────────────


class TestCouplingStats:
    def test_counts_and_sums(self, doc: dict) -> None:
        s = spef_coupling_stats(doc)
        assert s["n_coupling"] == 3
        assert s["n_ground"] == 3
        assert s["coupling_sum_far"] == _ap(7e-13)
        assert s["ground_sum_far"] == _ap(1e-12)
        assert s["coupling_to_ground_ratio"] == _ap(0.7)

    def test_default_top_k_capped_and_sorted(self, doc: dict) -> None:
        top = spef_coupling_stats(doc)["top_pairs"]
        assert [p["value_far"] for p in top] == _ap(
            [4e-13, 2e-13, 1e-13])
        assert top[0] == {"net": "clk", "node1": "clk:3",
                          "node2": "data_a:2", "value_far": _ap(4e-13)}

    def test_top_k_truncates(self, doc: dict) -> None:
        assert len(spef_coupling_stats(doc, top_k=2)["top_pairs"]) == 2

    def test_top_k_zero_empty(self, doc: dict) -> None:
        assert spef_coupling_stats(doc, top_k=0)["top_pairs"] == []

    def test_tie_order_stable_by_document_order(self) -> None:
        caps = "1 a b 0.2\n2 c d 0.5\n3 e f 0.2\n4 g h 0.2\n"
        d = _mini(_net_body(caps))
        top = spef_coupling_stats(d, top_k=4)["top_pairs"]
        assert [p["node1"] for p in top] == ["c", "a", "e", "g"]

    def test_zero_ground_ratio_none(self) -> None:
        d = _mini(_net_body("1 a b 0.2\n"))
        s = spef_coupling_stats(d)
        assert s["ground_sum_far"] == 0.0
        assert s["coupling_to_ground_ratio"] is None


# ── net 查询 ────────────────────────────────────────────────────────────


class TestNetLookup:
    def test_found_returns_full_view(self, doc: dict) -> None:
        n = spef_net_lookup(doc, "clk")
        assert n is doc["nets"][0]
        assert n["id"] == "10001"

    def test_missing_returns_none(self, doc: dict) -> None:
        assert spef_net_lookup(doc, "ghost") is None

    def test_lookup_by_unmapped_fidelity_name(self) -> None:
        d = _mini(_net_body("1 *1:1 0.1\n"))
        assert spef_net_lookup(d, "<*1>") is d["nets"][0]


# ── 服务信封 ────────────────────────────────────────────────────────────

# 键集钉（aurora_r R-02 AX-6/数值扩展批 +3 附加键：diagnostics/
# value_continuations/diagnostics_summary——纯增量，既有键零变化）。
PARSE_KEYS = {"ok", "path", "header", "name_map", "name_map_reverse",
              "ports", "nets", "stats", "warnings",
              "diagnostics", "value_continuations"}
REPORT_KEYS = {"ok", "path", "design", "units", "topology", "coupling",
               "stats", "warnings", "diagnostics", "diagnostics_summary"}


class TestService:
    def test_parse_ok_envelope_keys(self, spef_file: Path) -> None:
        r = parse_spef_file(spef_file)
        assert r["ok"] is True
        assert set(r) == PARSE_KEYS
        assert r["path"] == str(spef_file)
        assert r["stats"]["n_nets"] == 2

    def test_parse_unreadable_error(self, tmp_path: Path) -> None:
        r = parse_spef_file(tmp_path / "no_such.spef")
        assert r["ok"] is False
        assert isinstance(r["errors"], list)
        assert "不可读" in r["errors"][0]

    def test_parse_empty_file_error(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.spef"
        f.write_text("", encoding="utf-8")
        r = parse_spef_file(f)
        assert r["ok"] is False
        assert "解析失败" in r["errors"][0]

    def test_parse_no_header_error(self, tmp_path: Path) -> None:
        f = tmp_path / "nohead.spef"
        f.write_text("*D_NET *1 0\n*END\n", encoding="utf-8")
        r = parse_spef_file(f)
        assert r["ok"] is False
        assert "*SPEF" in r["errors"][0]

    def test_latin1_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "latin.spef"
        f.write_bytes(b'// author: Jos\xe9\n*SPEF "IEEE 1481-1998"\n')
        r = parse_spef_file(f)
        assert r["ok"] is True
        assert r["header"]["spef_version"] == "IEEE 1481-1998"

    def test_report_envelope(self, spef_file: Path) -> None:
        r = spef_report(spef_file)
        assert r["ok"] is True
        assert set(r) == REPORT_KEYS
        assert r["design"] == "top_block"
        assert r["topology"]["totals"]["n_isolated"] == 3
        assert r["coupling"]["n_coupling"] == 3

    def test_report_top_k_plumbed(self, spef_file: Path) -> None:
        r = spef_report(spef_file, top_k=1)
        assert len(r["coupling"]["top_pairs"]) == 1

    def test_report_unreadable_error(self, tmp_path: Path) -> None:
        r = spef_report(tmp_path / "missing.spef")
        assert r["ok"] is False
        assert isinstance(r["errors"], list)

    def test_net_detail_found(self, spef_file: Path) -> None:
        r = spef_net_detail(spef_file, "data_a")
        assert r["ok"] is True
        assert r["net"]["id"] == "10002"
        assert r["topology"]["isolated_nodes"] == ["u1:D"]

    def test_net_detail_missing_lists_available(self, spef_file: Path) -> None:
        r = spef_net_detail(spef_file, "ghost")
        assert r["ok"] is False
        assert "ghost" in r["errors"][0]
        assert "clk" in r["errors"][0] and "data_a" in r["errors"][0]

    def test_net_detail_unreadable_error(self, tmp_path: Path) -> None:
        r = spef_net_detail(tmp_path / "missing.spef", "clk")
        assert r["ok"] is False
        assert "不可读" in r["errors"][0]


# ── CLI（局部父 Typer 自测；接线待合流）─────────────────────────────────


class TestCli:
    def test_parse_json_envelope(self, local_app: typer.Typer,
                                 spef_file: Path) -> None:
        r = runner.invoke(local_app, ["spef", "parse", "--file",
                                      str(spef_file), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert set(payload) == PARSE_KEYS
        assert [n["name"] for n in payload["nets"]] == ["clk", "data_a"]

    def test_parse_human_output(self, local_app: typer.Typer,
                                spef_file: Path) -> None:
        r = runner.invoke(local_app, ["spef", "parse", "--file", str(spef_file)])
        assert r.exit_code == 0, r.output
        assert "top_block" in r.output
        assert "clk" in r.output and "data_a" in r.output

    def test_parse_failure_json_exit1(self, local_app: typer.Typer,
                                      tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["spef", "parse", "--file",
                                      str(tmp_path / "nope.spef"), "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)
        assert len(payload["errors"]) == 1

    def test_parse_failure_human_exit1(self, local_app: typer.Typer,
                                       tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["spef", "parse", "--file",
                                      str(tmp_path / "nope.spef")])
        assert r.exit_code == 1
        assert "SPEF 解析失败" in r.output

    def test_parse_missing_file_option_exit2(self, local_app: typer.Typer) -> None:
        r = runner.invoke(local_app, ["spef", "parse"])
        assert r.exit_code == 2

    def test_report_json_envelope(self, local_app: typer.Typer,
                                  spef_file: Path) -> None:
        r = runner.invoke(local_app, ["spef", "report", "--file",
                                      str(spef_file), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert set(payload) == REPORT_KEYS
        assert len(payload["coupling"]["top_pairs"]) == 3

    def test_report_top_k_flag(self, local_app: typer.Typer,
                               spef_file: Path) -> None:
        r = runner.invoke(local_app, ["spef", "report", "--file", str(spef_file),
                                      "--top-k", "1", "--json"])
        assert r.exit_code == 0, r.output
        assert len(json.loads(r.output)["coupling"]["top_pairs"]) == 1

    def test_report_human_output(self, local_app: typer.Typer,
                                 spef_file: Path) -> None:
        r = runner.invoke(local_app, ["spef", "report", "--file", str(spef_file)])
        assert r.exit_code == 0, r.output
        assert "孤立节点" in r.output
        assert "u1:D" in r.output

    def test_report_failure_json_exit1(self, local_app: typer.Typer,
                                       tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["spef", "report", "--file",
                                      str(tmp_path / "nope.spef"), "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["ok"] is False

    @pytest.mark.parametrize(("leaf", "flag"), [
        ("parse", "--file"), ("report", "--top-k")])
    def test_help_real_build(self, local_app: typer.Typer, leaf: str,
                             flag: str) -> None:
        # #305：真构建 --help（帮助串含 % 会在展开期炸）
        r = runner.invoke(local_app, ["spef", leaf, "--help"])
        assert r.exit_code == 0, r.output
        assert flag in r.output

    def test_domain_leaf_shape(self, local_app: typer.Typer) -> None:
        from typer.main import get_command

        group = get_command(local_app).commands.get("spef")
        assert group is not None
        assert set(group.commands) == {"parse", "report"}

    def test_help_text_hygiene(self, local_app: typer.Typer) -> None:
        # D-06 门同判定面预检：命令 help/short_help 与参数 help 零裸 [、零
        # 未成对 %（合流后进全树门亦绿）
        from typer.main import get_command

        group = get_command(local_app).commands["spef"]
        texts = [group.help or ""]
        for cmd in group.commands.values():
            texts.extend([cmd.help or "", cmd.short_help or ""])
            texts.extend(getattr(p, "help", None) or "" for p in cmd.params)
        for text in texts:
            assert "[" not in text, text
            assert text.replace("%%", "").count("%") == 0, text
