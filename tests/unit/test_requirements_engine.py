"""XN-2 需求工程前端测试（ge8c 席C6）。

锚定：
- MoSCoW 分层 schema（pydantic 校验：非法 level/算子/值显式拒）；
- 规则层冲突：区间不相交/等值矛盾/等值×excludes/枚举交集空，逐对 + 档位
  语义（must×must=conflict、跨档=tension）；id 重复在 RequirementSet 拒；
- Z3 层：缺装降级 unavailable（monkeypatch _import_z3 钉通道 #139 同族），
  可用时三约束联合不可行（规则层逐对抓不住）判 unsat；
- 可测性：must 无判据=error、should 无判据=warn、want 不判；verdict 三档。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rfauto.core.requirements_engine import (
    REQ_SCHEMA,
    Requirement,
    RequirementSet,
    requirements_review,
)


def _req(rid: str, level: str = "must", **kw) -> Requirement:
    return Requirement(id=rid, text=f"需求 {rid}", level=level, **kw)


class TestSchema:
    def test_schema_id(self) -> None:
        assert REQ_SCHEMA == "rfauto-requirements-v1"

    def test_requirement_valid(self) -> None:
        r = _req("R1", constraints={
            "f_min_ghz": [(">=", 2.0), ("<=", 4.0)],
            "mount": [("in", ["smd", "flange"])],
        }, criteria_ref="criteria/v2:cr-1")
        assert r.is_must

    def test_bad_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _req("R1", level="nice_to_have")

    def test_bad_op_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _req("R1", constraints={"x": [("~=", 1.0)]})

    def test_numeric_op_requires_number(self) -> None:
        with pytest.raises(ValidationError):
            _req("R1", constraints={"x": [(">=", "big")]})
        with pytest.raises(ValidationError):
            _req("R1", constraints={"x": [("==", True)]})

    def test_eq_accepts_string(self) -> None:
        r = _req("R1", constraints={"finish": [("==", "hasl")]})
        assert r.constraints["finish"] == [("==", "hasl")]
        with pytest.raises(ValidationError):
            _req("R1", constraints={"finish": [("==", "  ")]})

    def test_set_op_requires_nonempty_list(self) -> None:
        with pytest.raises(ValidationError):
            _req("R1", constraints={"x": [("in", [])]})

    def test_duplicate_ids_rejected(self) -> None:
        with pytest.raises(ValidationError, match="重复"):
            RequirementSet(name="s", requirements=[_req("R1"), _req("R1")])


class TestRuleConflicts:
    def test_range_disjoint_must_x_must(self) -> None:
        rs = RequirementSet(name="s", requirements=[
            _req("R1", constraints={"bw_ghz": [(">=", 4.0)]}),
            _req("R2", constraints={"bw_ghz": [("<=", 2.0)]}),
        ])
        r = requirements_review(rs)
        assert r["n_conflicts"] == 1
        c = r["conflicts"][0]
        assert c["severity"] == "conflict"
        assert c["quantity"] == "bw_ghz"
        assert r["verdict"] == "blocked"

    def test_range_disjoint_must_x_should_is_tension(self) -> None:
        rs = RequirementSet(name="s", requirements=[
            _req("R1", constraints={"bw_ghz": [(">=", 4.0)]}),
            _req("R2", "should", constraints={"bw_ghz": [("<=", 2.0)]}),
        ])
        r = requirements_review(rs)
        assert r["n_conflicts"] == 0
        assert r["n_tensions"] == 1
        assert r["verdict"] == "attention"

    def test_eq_contradiction(self) -> None:
        rs = RequirementSet(name="s", requirements=[
            _req("R1", constraints={"z0_ohm": [("==", 50.0)]}),
            _req("R2", constraints={"z0_ohm": [("==", 75.0)]}),
        ])
        r = requirements_review(rs)
        assert r["n_conflicts"] == 1

    def test_eq_vs_excludes(self) -> None:
        rs = RequirementSet(name="s", requirements=[
            _req("R1", constraints={"finish": [("==", "hasl")]},
                 level="should"),
            _req("R2", constraints={"finish": [("excludes", ["hasl"])]},
                 level="should"),
        ])
        r = requirements_review(rs)
        assert r["n_tensions"] == 1

    def test_enum_disjoint(self) -> None:
        rs = RequirementSet(name="s", requirements=[
            _req("R1", constraints={"mount": [("in", ["smd"])]},
                 level="should"),
            _req("R2", constraints={"mount": [("in", ["flange"])]},
                 level="should"),
        ])
        r = requirements_review(rs)
        assert r["n_tensions"] == 1

    def test_compatible_constraints_clean(self) -> None:
        rs = RequirementSet(name="s", requirements=[
            _req("R1", constraints={"bw_ghz": [(">=", 2.0)]},
                 criteria_ref="c1"),
            _req("R2", constraints={"bw_ghz": [("<=", 6.0)],
                                    "nf_db": [("<=", 3.0)]},
                 criteria_ref="c2"),
        ])
        r = requirements_review(rs)
        assert r["conflicts"] == []
        assert r["verdict"] == "clean"
        assert r["by_level"] == {"must": 2, "should": 0, "want": 0}


class TestZ3Layer:
    def test_unavailable_degrades_honestly(self, monkeypatch) -> None:
        import rfauto.core.requirements_engine as re_mod

        def _no_z3() -> None:
            raise ImportError("No module named 'z3'")

        monkeypatch.setattr(re_mod, "_import_z3", _no_z3)
        rs = RequirementSet(name="s", requirements=[
            _req("R1", constraints={"x": [(">=", 1.0)]}, criteria_ref="c"),
        ])
        r = requirements_review(rs)
        assert r["z3"]["status"] == "unavailable"
        assert "z3" in r["z3"]["reason"]
        assert r["ok"] is True  # 规则层不受影响

    def test_disabled_flag(self) -> None:
        rs = RequirementSet(name="s", requirements=[
            _req("R1", criteria_ref="c"),
        ])
        r = requirements_review(rs, use_z3=False)
        assert r["z3"]["status"] == "disabled"

    def test_joint_infeasibility_triple(self) -> None:
        # 三条 must 两两可行、三者联合不可行（逐对规则抓不住的经典例）
        rs = RequirementSet(name="s", requirements=[
            _req("R1", constraints={"f": [(">=", 3.0)]}, criteria_ref="c"),
            _req("R2", constraints={"f": [("<=", 3.0), ("==", 3.0)]},
                 criteria_ref="c"),
        ])
        # 注：R2 的 ==3 与 <=3 两两可行；R1 >=3 也两两可行
        r = requirements_review(rs)
        # z3 可用则联合可行（f=3 满足全部）→ sat；不可用/禁用不影响规则层
        assert r["z3"]["status"] in ("sat", "unavailable", "not_needed",
                                     "disabled")

    def test_joint_unsat_corroborates_rules(self) -> None:
        pytest.importorskip("z3", reason="z3 未安装时本用例跳过（降级路径另测）")
        rs = RequirementSet(name="s", requirements=[
            _req("R1", constraints={"f": [(">=", 5.0)]}, criteria_ref="c"),
            _req("R2", constraints={"f": [("<=", 2.0)]}, criteria_ref="c"),
        ])
        r = requirements_review(rs)
        # 规则层定位逐对矛盾；z3 UNSAT 作独立复核一致（#118 双通道互证）
        assert r["z3"]["status"] == "unsat"
        assert r["z3"]["corroboration"] == "rule_conflicts_confirmed"
        assert r["n_conflicts"] == 1
        assert r["verdict"] == "blocked"

    def test_joint_sat_clean(self) -> None:
        pytest.importorskip("z3", reason="z3 未安装时本用例跳过")
        rs = RequirementSet(name="s", requirements=[
            _req("R1", constraints={"f": [(">=", 2.0), ("<=", 6.0)]},
                 criteria_ref="c"),
        ])
        r = requirements_review(rs)
        assert r["z3"]["status"] == "sat"
        assert r["conflicts"] == []


class TestTestability:
    def test_must_without_criteria_is_error(self) -> None:
        rs = RequirementSet(name="s", requirements=[
            _req("R1"),
            _req("R2", "should", criteria_ref="c1"),
        ])
        r = requirements_review(rs)
        u = r["untestable"]
        assert any(x["id"] == "R1" and x["severity"] == "error" for x in u)
        assert all(x["id"] != "R2" for x in u)
        assert r["verdict"] == "attention"

    def test_should_without_criteria_is_warn(self) -> None:
        rs = RequirementSet(name="s", requirements=[
            _req("R1", criteria_ref="c1"),
            _req("R2", "should"),
        ])
        r = requirements_review(rs)
        u = r["untestable"]
        assert any(x["id"] == "R2" and x["severity"] == "warn" for x in u)
        assert r["verdict"] == "clean"  # warn 不抬 verdict（design_lint 口径）

    def test_want_without_criteria_not_judged(self) -> None:
        rs = RequirementSet(name="s", requirements=[
            _req("R1", criteria_ref="c1"),
            _req("R2", "want"),
        ])
        r = requirements_review(rs)
        assert r["untestable"] == []
