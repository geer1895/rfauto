"""反标回路（P6）单测——审查 D1-5 回归钉：单例 mapping 规则不跨调用污染。

原缺陷：ads_to_hfss_params 把传入 mapping_rules 直接合并进 self.mapping，
get_back_annotator 是进程级单例 → 第一次调用的自定义规则永久留存，
第二次调用（不带规则）仍被第一次的规则污染。
修法：合并作用于调用内局部副本，不回写单例状态（优先级 = 传入规则 >
构造期 mapping > DEFAULT_MAPPING）。
"""

from __future__ import annotations

import sys
from pathlib import Path

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import pytest

from rfauto.linkage.back_annotation import BackAnnotator, back_annotate, get_back_annotator

RULE_A = [{
    "ads_component": "capacitor_pf",
    "hfss_variable": "shunt_w_custom_a",
    "transform": "linear",
    "reference": {"cap": 1.0, "width": 2.0},
}]
RULE_B = [{
    "ads_component": "capacitor_pf",
    "hfss_variable": "shunt_w_custom_b",
    "transform": "linear",
    "reference": {"cap": 1.0, "width": 3.0},
}]


class TestSingletonRulePollution:
    """D1-5 主钉：两次调用不同 rules，第二次结果不受第一次污染。"""

    def test_back_annotate_rules_do_not_leak_across_calls(self):
        first = back_annotate({"capacitor_pf": 2.0}, mapping_rules=RULE_A)
        assert first == {"shunt_w_custom_a": 4.0}
        # 第二次不带规则：不得再看到第一次注入的 shunt_w_custom_a
        second = back_annotate({"capacitor_pf": 2.0})
        assert "shunt_w_custom_a" not in second
        assert second == {"shunt_w": 0.55}  # DEFAULT_MAPPING：inverse_linear 1.0*1.10/2.0


class TestInverseLinearZeroGuard:
    """B-9/S3：inverse_linear 在 ads_value=0 显式报错（1/W 映射不可反推）。"""

    def test_zero_ads_value_raises_value_error(self):
        with pytest.raises(ValueError, match=r"inverse_linear.*无定义"):
            back_annotate({"capacitor_pf": 0.0})

    def test_zero_via_explicit_annotator(self):
        annotator = get_back_annotator()
        with pytest.raises(ValueError, match="ads_value=0"):
            annotator.ads_to_hfss_params({"capacitor_pf": 0.0})

    def test_nonzero_still_maps(self):
        assert back_annotate({"capacitor_pf": 2.0}) == {"shunt_w": 0.55}

    def test_different_rules_second_call_not_polluted(self):
        back_annotate({"capacitor_pf": 1.0}, mapping_rules=RULE_A)
        second = back_annotate({"capacitor_pf": 2.0}, mapping_rules=RULE_B)
        assert second == {"shunt_w_custom_b": 6.0}
        assert "shunt_w_custom_a" not in second

    def test_singleton_state_untouched(self):
        annotator = get_back_annotator()
        snapshot = dict(annotator.mapping)
        back_annotate({"capacitor_pf": 1.0}, mapping_rules=RULE_A)
        back_annotate({"capacitor_pf": 1.0}, mapping_rules=RULE_B)
        assert annotator.mapping == snapshot
        assert "shunt_w_custom_a" not in annotator.mapping
        assert "shunt_w_custom_b" not in annotator.mapping

    def test_rules_override_base_within_call_only(self):
        annotator = get_back_annotator()
        out = annotator.ads_to_hfss_params(
            {"capacitor_pf": 2.0}, mapping_rules=RULE_A)
        assert out == {"shunt_w_custom_a": 4.0}
        # 调用后同实例再走缺省路径 → DEFAULT_MAPPING 语义
        out2 = annotator.ads_to_hfss_params({"capacitor_pf": 2.0})
        assert out2 == {"shunt_w": 0.55}

    def test_default_mapping_dict_not_mutated(self):
        """类级 DEFAULT_MAPPING 也不得被调用污染（浅拷贝面）。"""
        before = dict(BackAnnotator.DEFAULT_MAPPING)
        annotator = BackAnnotator()
        annotator.ads_to_hfss_params({"capacitor_pf": 1.0}, mapping_rules=RULE_B)
        assert before == BackAnnotator.DEFAULT_MAPPING
        assert annotator.mapping == before

    def test_third_party_key_from_rules_does_not_persist(self):
        """规则注入的全新 ads_component 键同样不跨调用留存。"""
        rule_new = [{
            "ads_component": "resistor_ohm",
            "hfss_variable": "feed_w",
            "transform": "linear",
            "reference": {"r": 1.0, "w": 0.5},
        }]
        out1 = back_annotate({"resistor_ohm": 10.0}, mapping_rules=rule_new)
        assert out1 == {"feed_w": 5.0}
        out2 = back_annotate({"resistor_ohm": 10.0})
        assert out2 == {}  # 键未进缺省映射 → 第二次无映射结果
