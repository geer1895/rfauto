"""SPEF 扩展数值形态（三值/缩放乘积/D 阶码/续行）单测（aurora_r R-02，
2026-11-10）——Q-X60"三值数值（min:typ:max）未支持 warning 整行跳过"
已知限制转正的逐位验收。

覆盖面：

- parse_spef_value 表驱动：plain（含科学计数/显式正负号——历史 float()
  路径逐位同判）/d_exponent（``1.2D3``）/triple（min:typ:max，判定值=
  typ，min/typ/max 随行）/product（``A*B[*C…]``，全因子 Decimal 十进
  制精确乘积单次 float 舍入；任一因子带后缀 → units=absolute）；
- 失败 reason 表：裸后缀量纲两读（tier1）/三值段数非 3/段含后缀/乘积
  因子空缺/未知后缀（unparsed）；value_fail_tier 定档单源；
- **合成回收钉**（注入已知值→解析→逐位回收；数值链=测试内同构 float
  运算，== 为逐位断言非近似）：
  * ``1.2p*2.3`` → 2.76e-12（Decimal 精确积）逐位 == 字面 2.76e-12；
  * triple 总电容 ``1.234:2.345:3.456`` ×PF → total_cap_far ==
    2.345*1e-12（与解析器同构两步浮点乘链，逐位）；
  * 续行 ``8.0``+``4.0``×PF → (8.0*1e-12)+(4.0*1e-12) 逐位；
- 集成：D_NET 总电容 triple/product 键组；CAP 对地/耦合 triple 与
  suffixed product 条目键组（value_form/value_raw/value_min_far/…）；
  RES/IND 扩展形态；**plain 条目形状零变化**（无 value_form 键）；
- 续行：CAP 对地/耦合/RES/IND 四桶 +/− 链式续行；跨段族守卫（CAP 段
  续行撞 RES 锚=拒）；无前置元件/带后缀增量/triple 增量 → warning+
  tier 诊断（不再静默）；value_continuations 事件全量落档（含 net 级
  continuations 镜像）；
- 确定性：同输入两次解析逐键相等（json 逐字节）；clean 样本
  diagnostics/warnings 恒空。

单测零网络零真机。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from rfauto.core.parser_diagnostics import (
    TIER_UNPARSED,
    TIER_UNSUPPORTED_1,
    TIER_UNSUPPORTED_2,
)
from rfauto.core.spef_parser import parse_spef, parse_spef_value, value_fail_tier

_HEAD = '*SPEF "IEEE 1481-1998"\n*DESIGN "vals"\n*C_UNIT 1 PF\n'


def _mini(body: str, head: str = _HEAD) -> dict[str, Any]:
    return parse_spef(head + body)


# ── parse_spef_value 表驱动 ─────────────────────────────────────────────


class TestParseSpefValueForms:
    @pytest.mark.parametrize("token,expected", [
        ("1.5", 1.5),
        ("-2.5", -2.5),
        ("+1.5", 1.5),
        (".5", 0.5),
        ("1e3", 1000.0),
        ("1.5E-3", 0.0015),
        ("1_0", 10.0),  # Python float 字面（历史路径同判，零行为变化）
        ("1.2D3", 1200.0),
        ("1.5d-3", 0.0015),
        ("-2D+2", -200.0),
    ])
    def test_plain_and_d_exponent(self, token: str, expected: float) -> None:
        pv = parse_spef_value(token)
        assert pv["ok"] is True
        assert pv["value"] == expected
        assert pv["units"] == "header"
        assert pv["reason"] is None
        form = "d_exponent" if "d" in token.lower() and "e" not in token.lower() else "plain"
        assert pv["form"] == form

    def test_triple_basic(self) -> None:
        pv = parse_spef_value("1.0:1.5:2.0")
        assert pv["ok"] is True
        assert pv["form"] == "triple"
        assert pv["units"] == "header"
        assert (pv["min"], pv["typ"], pv["max"]) == (1.0, 1.5, 2.0)
        assert pv["value"] == 1.5  # 判定值=typ（中段）

    def test_triple_signed(self) -> None:
        pv = parse_spef_value("-1.0:0:1.0")
        assert pv["ok"] is True
        assert (pv["min"], pv["typ"], pv["max"]) == (-1.0, 0.0, 1.0)

    def test_triple_d_exponent_parts(self) -> None:
        pv = parse_spef_value("1D-3:2e-3:3E-3")
        assert pv["ok"] is True
        assert (pv["min"], pv["typ"], pv["max"]) == (0.001, 0.002, 0.003)

    def test_product_numeric_header_units(self) -> None:
        pv = parse_spef_value("1.2*2.3")
        assert pv["ok"] is True
        assert pv["form"] == "product"
        assert pv["units"] == "header"
        assert pv["suffixed"] is False
        assert pv["value"] == 2.76  # Decimal 精确积单次舍入 == 字面
        assert pv["factors"] == [1.2, 2.3]

    def test_product_chain_three_factors(self) -> None:
        pv = parse_spef_value("1.2*2.3*4.5")
        assert pv["ok"] is True
        assert pv["value"] == 12.42
        assert pv["factors"] == [1.2, 2.3, 4.5]

    def test_product_suffixed_absolute_si(self) -> None:
        pv = parse_spef_value("1.2p*2.3")
        assert pv["ok"] is True
        assert pv["form"] == "product"
        assert pv["units"] == "absolute"  # 后缀携带量纲，不再乘头部系数
        assert pv["suffixed"] is True
        # 回收钉：Decimal 精确积 → 逐位 == 字面 2.76e-12
        assert pv["value"] == 2.76e-12
        assert pv["factors"] == [1.2e-12, 2.3]

    def test_product_suffixed_commutative(self) -> None:
        assert parse_spef_value("2.3*1.2p")["value"] == 2.76e-12

    def test_product_mixed_suffix(self) -> None:
        pv = parse_spef_value("1p*2*3")
        assert pv["ok"] is True
        assert pv["units"] == "absolute"
        assert pv["value"] == 6e-12

    def test_product_exponent_factor(self) -> None:
        pv = parse_spef_value("1.5e2*2")
        assert pv["ok"] is True
        assert pv["value"] == 300.0
        assert pv["units"] == "header"

    @pytest.mark.parametrize("token,reason", [
        ("1.2p", "bare_suffix_dimension_ambiguous"),   # 量纲两读绝不猜
        ("1.2pf", "suffix_unrecognized"),  # 复合后缀不在闭集——不猜
        ("1.2:1.5", "triple_arity"),
        ("1.2:1.5:1.8:2.0", "triple_arity"),
        (":1.5:1.8", "triple_empty_part"),
        ("1.2p:1.5:1.8", "triple_part_suffixed_dimension_ambiguous"),
        ("1.2:1.5:x", "triple_part_unrecognized"),
        ("1.2**3", "product_empty_factor"),
        ("*2.3", "product_empty_factor"),
        ("1.2*", "product_empty_factor"),
        ("1.2*2.3q", "factor_suffix_unrecognized"),
        ("1.2*abc", "factor_unrecognized"),
        ("1.2q", "suffix_unrecognized"),
        ("abc", "unrecognized"),
        ("", "unrecognized"),
    ])
    def test_failures(self, token: str, reason: str) -> None:
        pv = parse_spef_value(token)
        assert pv["ok"] is False
        assert pv["value"] is None
        assert pv["reason"] == reason

    def test_value_fail_tier_mapping(self) -> None:
        # 裸后缀/段含后缀=已知方言语法量纲两读 → tier1；其余病态 → unparsed
        assert value_fail_tier("bare_suffix_dimension_ambiguous") == \
            TIER_UNSUPPORTED_1
        assert value_fail_tier(
            "triple_part_suffixed_dimension_ambiguous") == TIER_UNSUPPORTED_1
        assert value_fail_tier("triple_arity") == TIER_UNPARSED
        assert value_fail_tier("unrecognized") == TIER_UNPARSED
        assert value_fail_tier("anything_else") == TIER_UNPARSED


# ── 集成：值槽扩展形态 ──────────────────────────────────────────────────


class TestValueSlotIntegration:
    def test_dnet_total_triple(self) -> None:
        d = _mini("*D_NET *1 1.234:2.345:3.456\n*END\n")
        n = d["nets"][0]
        assert n["total_cap_header"] == 2.345  # 判定值=typ
        assert n["total_cap_form"] == "triple"
        assert n["total_cap_raw"] == "1.234:2.345:3.456"
        assert (n["total_cap_min"], n["total_cap_max"]) == (1.234, 3.456)
        # 回收钉：与解析器同构两步浮点乘链，逐位 ==
        assert n["total_cap_far"] == 2.345 * 1e-12

    def test_dnet_total_suffixed_product(self) -> None:
        d = _mini("*D_NET *1 1.2p*2.3\n*END\n")
        n = d["nets"][0]
        assert n["total_cap_header"] == 2.76e-12  # as-written 判定值
        assert n["total_cap_form"] == "product"
        assert n["total_cap_suffixed"] is True
        assert n["total_cap_far"] == 2.76e-12  # absolute：不再乘头部系数

    def test_cap_gnd_suffixed_product_entry_keys(self) -> None:
        d = _mini("*D_NET *1 0\n*CAP\n1 a 1.2p*2.3\n*END\n")
        c = d["nets"][0]["caps_gnd"][0]
        assert c["value_far"] == 2.76e-12  # 回收钉逐位
        assert c["value_form"] == "product"
        assert c["value_raw"] == "1.2p*2.3"
        assert c["value_factors"] == [1.2e-12, 2.3]
        assert c["value_suffixed"] is True

    def test_cap_cpl_triple_entry_keys(self) -> None:
        d = _mini("*D_NET *1 0\n*CAP\n1 a b 0.1:0.2:0.3\n*END\n")
        c = d["nets"][0]["caps_cpl"][0]
        assert c["value_far"] == 0.2 * 1e-12
        assert c["value_form"] == "triple"
        assert c["value_min_far"] == 0.1 * 1e-12
        assert c["value_max_far"] == 0.3 * 1e-12

    def test_res_product_header_units(self) -> None:
        d = _mini("*D_NET *1 0\n*RES\n1 a b 1.2*2.0\n*END\n")
        r = d["nets"][0]["res"][0]
        assert r["value_ohm"] == 2.4  # 无后缀乘积=header 口径（×R_UNIT 1.0）
        assert r["value_form"] == "product"
        assert "value_suffixed" not in r

    def test_ind_plain_entry_shape_unchanged(self) -> None:
        # e 阶码（1.0e-9）历史已支持=plain——条目形状零变化
        d = _mini('*SPEF "x"\n*L_UNIT 1 HENRY\n'
                  "*D_NET *1 0\n*IND\n1 a b 1.0e-9\n*END\n")
        ind = d["nets"][0]["inds"][0]
        assert ind["value_henry"] == 1e-9
        assert "value_form" not in ind

    def test_ind_suffix_then_d_exponent_rejected(self) -> None:
        # "1.0nD0"=后缀 n 在 D 阶码前——因子词法不容（后缀+阶码组合
        # 顺序不可判），本形态如实拒（不猜）
        d = _mini('*SPEF "x"\n*L_UNIT 1 HENRY\n'
                  "*D_NET *1 0\n*IND\n1 a b 1.0nD0\n*END\n")
        assert d["nets"][0]["inds"] == []

    def test_plain_entry_shape_unchanged(self) -> None:
        # plain 值条目零新键（既有条目形状逐键不变）
        d = _mini("*D_NET *1 1.5\n*CAP\n1 a 0.5\n*END\n")
        n = d["nets"][0]
        assert set(n["caps_gnd"][0]) == {"node", "value_far"}
        assert "total_cap_form" not in n
        assert n["total_cap_far"] == 1.5 * 1e-12  # 回收钉逐位

    def test_undeterminable_value_still_skipped_with_diag(self) -> None:
        # 裸后缀值：不可判定 → 保留跳行 + tier1 诊断（不再静默）
        d = _mini("*D_NET *1 0\n*CAP\n1 a 1.2p\n*END\n")
        assert d["nets"][0]["caps_gnd"] == []
        assert any("CAP 电容值非数值" in w for w in d["warnings"])
        assert any(
            x["tier"] == TIER_UNSUPPORTED_1
            and x["reason"] == "bare_suffix_dimension_ambiguous"
            and x["line"] == 6
            for x in d["diagnostics"])

    def test_garbage_value_unchanged_warning(self) -> None:
        # 既有垃圾值文案契约逐字节保持
        d = _mini("*D_NET *1 0\n*CAP\n1 a abc\n*END\n")
        assert d["nets"][0]["caps_gnd"] == []
        assert any("CAP 电容值非数值（第 6 行）: abc——跳过" in w
                   for w in d["warnings"])


# ── 续行 ────────────────────────────────────────────────────────────────


class TestContinuation:
    def test_cap_gnd_plus_minus_chain(self) -> None:
        d = _mini("*D_NET *1 0\n*CAP\n1 a 8.0\n+ 4.0\n- 2.0\n*END\n")
        c = d["nets"][0]["caps_gnd"][0]
        # 回收钉：与解析器同构浮点链逐位 ==
        assert c["value_far"] == (8.0 * 1e-12) + (4.0 * 1e-12) - (2.0 * 1e-12)
        conts = d["value_continuations"]
        assert [(e["op"], e["section"]) for e in conts] == [("+", "CAP"),
                                                            ("-", "CAP")]
        assert all(e["element_index"] == 0 for e in conts)
        assert conts[0]["delta_si"] == 4.0 * 1e-12
        assert conts[1]["delta_si"] == -(2.0 * 1e-12)
        assert conts[0]["raw"] == "+ 4.0"

    def test_cap_cpl_continuation(self) -> None:
        d = _mini("*D_NET *1 0\n*CAP\n1 a b 0.5\n+ 0.25\n*END\n")
        c = d["nets"][0]["caps_cpl"][0]
        assert c["value_far"] == (0.5 + 0.25) * 1e-12

    def test_res_and_ind_continuation(self) -> None:
        d = _mini("*D_NET *1 0\n*RES\n1 a b 10.0\n+ 5.0\n*IND\n1 a b 2.0\n"
                  "- 0.5\n*END\n")
        n = d["nets"][0]
        assert n["res"][0]["value_ohm"] == 15.0
        assert n["inds"][0]["value_henry"] == 1.5  # L_UNIT 缺省 1.0

    def test_second_element_anchor_moves(self) -> None:
        d = _mini("*D_NET *1 0\n*CAP\n1 a 1.0\n2 b 2.0\n+ 1.0\n*END\n")
        caps = d["nets"][0]["caps_gnd"]
        assert caps[0]["value_far"] == 1.0 * 1e-12
        assert caps[1]["value_far"] == 3.0 * 1e-12
        assert d["value_continuations"][0]["element_index"] == 1

    def test_d_exponent_delta(self) -> None:
        d = _mini("*D_NET *1 0\n*CAP\n1 a 1.0\n+ 5.0D-1\n*END\n")
        c = d["nets"][0]["caps_gnd"][0]
        assert c["value_far"] == (1.0 + 0.5) * 1e-12

    def test_numeric_product_delta_header(self) -> None:
        d = _mini("*D_NET *1 0\n*CAP\n1 a 1.0\n+ 2.0*0.5\n*END\n")
        c = d["nets"][0]["caps_gnd"][0]
        assert c["value_far"] == 2.0 * 1e-12

    def test_continuation_without_previous_warns(self) -> None:
        d = _mini("*D_NET *1 0\n*CAP\n+ 0.5\n*END\n")
        assert d["nets"][0]["caps_gnd"] == []
        assert any("续行无前置元件可续" in w for w in d["warnings"])
        assert any(
            x["reason"] == "continuation_without_previous_element"
            and x["tier"] == TIER_UNPARSED for x in d["diagnostics"])

    def test_bare_suffix_delta_rejected(self) -> None:
        # 裸后缀增量（"+ 1.2p"）→ parse_spef_value 判 bare_suffix 不可判
        # → 续行拒收（原值不动+tier1 诊断，不静默）
        d = _mini("*D_NET *1 0\n*CAP\n1 a 1.0\n+ 1.2p\n*END\n")
        c = d["nets"][0]["caps_gnd"][0]
        assert c["value_far"] == 1.0 * 1e-12  # 原值不动
        assert any("续行增量不可解析" in w for w in d["warnings"])
        assert any(
            x["tier"] == TIER_UNSUPPORTED_1
            and x["reason"] == "continuation_bare_suffix_dimension_ambiguous"
            for x in d["diagnostics"])

    def test_triple_delta_tier2(self) -> None:
        d = _mini("*D_NET *1 0\n*CAP\n1 a 1.0\n+ 1.0:1.5:2.0\n*END\n")
        c = d["nets"][0]["caps_gnd"][0]
        assert c["value_far"] == 1.0 * 1e-12
        assert any(
            x["tier"] == TIER_UNSUPPORTED_2
            and x["reason"] == "continuation_delta_triple_unimplemented"
            for x in d["diagnostics"])

    def test_cross_family_anchor_rejected(self) -> None:
        # 同 D_NET 内 CAP 续行撞 RES 锚=拒（段族守卫）——宁拒不误续
        d = _mini("*D_NET *1 0\n*CAP\n1 a 1.0\n*RES\n1 a b 10.0\n*CAP\n"
                  "+ 0.5\n*END\n")
        assert d["nets"][0]["caps_gnd"][0]["value_far"] == 1.0 * 1e-12
        assert any(
            x["reason"] == "continuation_without_previous_element"
            for x in d["diagnostics"])

    def test_three_token_plus_line_falls_to_legacy_path(self) -> None:
        # "+ 0.5 0.3" 非两词续行 → 常规病态行路径（既有文案+tier 诊断）
        d = _mini("*D_NET *1 0\n*CAP\n1 a 1.0\n+ 0.5 0.3\n*END\n")
        assert any("CAP 序号非整数" in w for w in d["warnings"])
        assert any(x["reason"] == "cap_index_not_integer"
                   for x in d["diagnostics"])

    def test_net_level_continuations_mirror(self) -> None:
        d = _mini("*D_NET *1 0\n*CAP\n1 a 1.0\n+ 0.5\n*END\n")
        net = d["nets"][0]
        assert net["continuations"] == d["value_continuations"]

    def test_no_continuation_keys_when_unused(self) -> None:
        d = _mini("*D_NET *1 0\n*CAP\n1 a 1.0\n*END\n")
        assert d["value_continuations"] == []
        assert "continuations" not in d["nets"][0]


# ── 确定性与零变化 ──────────────────────────────────────────────────────


class TestDeterminism:
    def test_parse_twice_identical(self) -> None:
        text = (_HEAD + "*D_NET *1 1.0:2.0:3.0\n*CAP\n1 a 1.2p*2.3\n"
                "+ 0.5\n2 a b 0.1\n*RES\n1 a b 1.2*2.0\n*END\n")
        d1 = parse_spef(text)
        d2 = parse_spef(text)
        assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)

    def test_clean_sample_zero_warnings_and_diags(self) -> None:
        d = _mini("*D_NET *1 1.0\n*CAP\n1 a 0.5\n*RES\n1 a b 10.0\n*END\n")
        assert d["warnings"] == []
        assert d["diagnostics"] == []

    def test_schema_version_unchanged(self) -> None:
        d = _mini("*D_NET *1 0\n*END\n")
        assert d["schema"] == "spef/1.0"  # 附加键扩展不升位
