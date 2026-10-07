"""LC-DFT 可测试性规则族测试（ge8c 席C6）。

独立基准（#118）：几何判定全部手算可验——
- 间距：两点 1.0mm 距离 vs min_pitch 1.27mm（标准探针间距）→ 违规；
  异面对不判（探针不相碰语义）；等距边界值（恰等）不违规；
- 禁布区：点到矩形边距离（角点/边中点/内部点）手算核对；
- 可达率：3/5=0.6 vs min_rate 手算核对；min_points 不足如实 n_too_small；
  accessible 缺省 False（不声明不可达）；
- 负例：坏 side/非有限坐标/零面积障碍/重复 rule_id 显式报错；
- 聚合：多规则 FAIL 不短路。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rfauto.core.dft_testability import (
    DFT_SCHEMA,
    AccessibilityRule,
    DftRuleSet,
    ProbeKeepoutRule,
    ProbeSpacingRule,
    check_accessibility,
    check_keepout,
    check_probe_spacing,
    review_testability,
)


def _pt(x, y, side="bottom", accessible=False):
    return {"x_mm": x, "y_mm": y, "side": side, "accessible": accessible}


class TestSchema:
    def test_schema_id(self) -> None:
        assert DFT_SCHEMA == "rfauto-dft-testability/v1"

    def test_rule_families_closed(self) -> None:
        rs = DftRuleSet(name="ict", rules=[
            ProbeSpacingRule(rule_id="r1", min_pitch_mm=1.27),
            ProbeKeepoutRule(rule_id="r2", keepout_mm=0.5),
            AccessibilityRule(rule_id="r3", min_rate=0.9),
        ])
        assert {type(r).__name__ for r in rs.rules} == {
            "ProbeSpacingRule", "ProbeKeepoutRule", "AccessibilityRule"}

    def test_duplicate_rule_ids_rejected(self) -> None:
        with pytest.raises(ValidationError, match="重复"):
            DftRuleSet(name="s", rules=[
                ProbeSpacingRule(rule_id="r", min_pitch_mm=1.0),
                ProbeSpacingRule(rule_id="r", min_pitch_mm=2.0),
            ])

    def test_bad_pitch_and_rate(self) -> None:
        with pytest.raises(ValidationError):
            ProbeSpacingRule(rule_id="r", min_pitch_mm=0.0)
        with pytest.raises(ValidationError):
            AccessibilityRule(rule_id="r", min_rate=1.5)


class TestSpacing:
    def test_hand_computed_violation(self) -> None:
        rule = ProbeSpacingRule(rule_id="sp", min_pitch_mm=1.27)
        # 3-4-5 直角三角形：0.6+0.8=1.0mm < 1.27 → 违规
        r = check_probe_spacing(rule, [_pt(0.0, 0.0), _pt(0.6, 0.8)])
        assert r["verdict"] == "fail"
        assert r["n_violations"] == 1
        assert r["min_dist_mm"] == pytest.approx(1.0)

    def test_exact_boundary_passes(self) -> None:
        rule = ProbeSpacingRule(rule_id="sp", min_pitch_mm=1.27)
        r = check_probe_spacing(rule, [_pt(0.0, 0.0), _pt(1.27, 0.0)])
        assert r["verdict"] == "pass"
        assert r["n_violations"] == 0

    def test_opposite_sides_exempt(self) -> None:
        rule = ProbeSpacingRule(rule_id="sp", min_pitch_mm=5.0)
        r = check_probe_spacing(rule, [_pt(0.0, 0.0, "bottom"),
                                       _pt(0.1, 0.1, "top")])
        assert r["verdict"] == "pass"
        assert r["min_dist_mm"] is None  # 异面对不进统计

    def test_bad_inputs(self) -> None:
        rule = ProbeSpacingRule(rule_id="sp", min_pitch_mm=1.0)
        with pytest.raises(ValueError, match="side 非法"):
            check_probe_spacing(rule, [_pt(0, 0, "left")])
        with pytest.raises(ValueError, match="非有限"):
            check_probe_spacing(rule, [_pt(float("nan"), 0.0)])


class TestKeepout:
    def test_rect_distance_hand_computed(self) -> None:
        rule = ProbeKeepoutRule(rule_id="ko", keepout_mm=0.5)
        rect = (0.0, 0.0, 2.0, 1.0)  # 2×1 矩形于原点
        # 边中点外 0.3mm → 违规；角点外对角 0.3+0.4=0.5mm 恰等 → 不违规
        r = check_keepout(rule, [_pt(1.0, 1.3), _pt(2.3, 1.4)], [rect])
        assert r["n_violations"] == 1
        assert r["violations"][0]["dist_mm"] == pytest.approx(0.3)
        assert r["verdict"] == "fail"

    def test_point_inside_obstacle_zero_distance(self) -> None:
        rule = ProbeKeepoutRule(rule_id="ko", keepout_mm=0.1)
        r = check_keepout(rule, [_pt(1.0, 0.5)], [(0.0, 0.0, 2.0, 1.0)])
        assert r["violations"][0]["dist_mm"] == 0.0

    def test_zero_area_obstacle_rejected(self) -> None:
        rule = ProbeKeepoutRule(rule_id="ko", keepout_mm=0.1)
        with pytest.raises(ValueError, match="正面积"):
            check_keepout(rule, [_pt(0, 0)], [(0.0, 0.0, 0.0, 1.0)])


class TestAccessibility:
    def test_rate_hand_computed(self) -> None:
        rule = AccessibilityRule(rule_id="acc", side="bottom", min_rate=0.5)
        pts = [_pt(0, 0, accessible=True), _pt(1, 0),
               _pt(2, 0, accessible=True), _pt(3, 0), _pt(4, 0)]
        r = check_accessibility(rule, pts)
        assert r["rate"] == pytest.approx(0.4)
        assert r["verdict"] == "fail"

    def test_boundary_rate_passes(self) -> None:
        rule = AccessibilityRule(rule_id="acc", min_rate=0.6)
        pts = [_pt(i * 1.0, 0, accessible=(i < 3)) for i in range(5)]
        r = check_accessibility(rule, pts)
        assert r["rate"] == pytest.approx(0.6)
        assert r["verdict"] == "pass"

    def test_n_too_small_honest(self) -> None:
        rule = AccessibilityRule(rule_id="acc", min_rate=0.9, min_points=5)
        r = check_accessibility(rule, [_pt(0, 0), _pt(1, 0)])
        assert r["verdict"] == "n_too_small"
        assert r["rate"] is None
        assert "如实未判" in r["note"]

    def test_accessible_defaults_false(self) -> None:
        rule = AccessibilityRule(rule_id="acc", min_rate=0.0, min_points=2)
        pts = [{"x_mm": 0.0, "y_mm": 0.0, "side": "bottom"},
               {"x_mm": 1.0, "y_mm": 0.0, "side": "bottom"}]
        r = check_accessibility(rule, pts)
        assert r["n_accessible"] == 0  # 不声明 = 不可达
        assert r["verdict"] == "pass"  # min_rate=0 恒过


class TestAggregate:
    def test_review_all_rules_no_short_circuit(self) -> None:
        rs = DftRuleSet(name="ict", rules=[
            ProbeSpacingRule(rule_id="sp", min_pitch_mm=2.0),
            ProbeKeepoutRule(rule_id="ko", keepout_mm=1.0),
            AccessibilityRule(rule_id="acc", min_rate=0.9, min_points=3),
        ])
        pts = [_pt(0.0, 0.0), _pt(0.5, 0.0),  # 间距违规
               _pt(5.0, 0.5), _pt(5.0, 3.0),  # (5,0.5) 落障碍 keepout
               _pt(9.0, 0.0)]  # 5 点全不可达
        r = review_testability(rs, test_points=pts,
                               obstacles=[(4.5, 0.0, 1.0, 1.0)])
        assert r["ok"] is True
        by_id = {x["rule_id"]: x for x in r["results"]}
        assert by_id["sp"]["verdict"] == "fail"
        assert by_id["ko"]["verdict"] == "fail"
        assert by_id["acc"]["verdict"] == "fail"
        assert r["n_fail"] == 3
        assert r["verdict"] == "fail"

    def test_review_pass(self) -> None:
        rs = DftRuleSet(name="ict", rules=[
            ProbeSpacingRule(rule_id="sp", min_pitch_mm=1.0),
            AccessibilityRule(rule_id="acc", min_rate=0.5, min_points=4),
        ])
        pts = [_pt(i * 2.0, float(i), accessible=True) for i in range(4)]
        r = review_testability(rs, test_points=pts)
        assert r["verdict"] == "pass"
        assert "LC-5/LC-7" in r["note"]

    def test_deterministic(self) -> None:
        import json
        rs = DftRuleSet(name="ict", rules=[
            ProbeSpacingRule(rule_id="sp", min_pitch_mm=1.0)])
        pts = [_pt(0.0, 0.0), _pt(0.5, 0.5)]
        a = json.dumps(review_testability(rs, test_points=pts), sort_keys=True)
        b = json.dumps(review_testability(rs, test_points=pts), sort_keys=True)
        assert a == b
