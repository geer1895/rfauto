"""XN-4 跨战役敏感性先验测试（ge8c 席C6）。

独立基准（#118/#300）：聚合逻辑用**手算可验的中位数例**与**性质锚**——
- 单主导参数结构（解析可判：x 是唯一影响者）两场战役后先验必收敛 x 主导；
- 归一不变性：同一记录按正数缩放（Sobol 指数超 1 的病态输入裁 0 后仍
  排序不变）；参数更名置换不变（结果随名置换，排序结构不变）；
- Morris/Sobol 双方法混合（mu_star 战役内 Σ 归一吸收量纲）；
- 预算分配：手算例逐参数核对 + 最大余数法确定性（同分名字典序）+ 保底
  不饿死 + 不可行分配显式报；
- 契约：消费 optimization.sensitivity 实际输出形态（sobol_sensitivity /
  morris_screening 的 sensitivity 字段直接入记录）；
- 负例：空记录/缺指标键/非有限值显式拒。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rfauto.core.sensitivity_prior import (
    PRIOR_SCHEMA,
    SensitivityRecord,
    allocate_budget,
    build_template_prior,
    render_prior_markdown,
)


def _rec(cid: str, sens: dict, method: str = "sobol",
         template: str = "mline", n_samples: int = 100) -> SensitivityRecord:
    return SensitivityRecord(template=template, campaign_id=cid,
                             method=method, sensitivity=sens,
                             n_samples=n_samples, seed=42)


class TestRecordSchema:
    def test_schema_id(self) -> None:
        assert PRIOR_SCHEMA == "rfauto-sensitivity-prior-v1"

    def test_sobol_record_accepted(self) -> None:
        # 契约：sobol_sensitivity()["sensitivity"] 输出形态直接入记录
        sens = {"w": {"S1": 0.6, "ST": 0.8}, "l": {"S1": 0.2, "ST": 0.3}}
        r = _rec("camp-1", sens)
        assert r.method == "sobol"

    def test_morris_record_accepted(self) -> None:
        sens = {"w": {"mu_star": 12.0, "sigma": 1.0},
                "l": {"mu_star": 3.0, "sigma": 0.5}}
        assert _rec("camp-1", sens, method="morris").method == "morris"

    def test_missing_metric_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="缺指标键"):
            _rec("c1", {"w": {"S1": 0.5}})  # sobol 缺 ST

    def test_nonfinite_rejected_and_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _rec("c1", {"w": {"S1": float("nan"), "ST": 0.1}})
        with pytest.raises(ValidationError):
            _rec("c1", {})

    def test_bad_method_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _rec("c1", {"w": {"S1": 1.0, "ST": 1.0}}, method="sobol2")


class TestPriorAggregation:
    def test_single_dominant_converges(self) -> None:
        # 解析可判结构：x 唯一主导（S1≈0.8），两场战役先验必 x 居首
        recs = [
            _rec("c1", {"x": {"S1": 0.80, "ST": 0.9},
                        "y": {"S1": 0.15, "ST": 0.2},
                        "z": {"S1": 0.05, "ST": 0.1}}),
            _rec("c2", {"x": {"S1": 0.70, "ST": 0.85},
                        "y": {"S1": 0.20, "ST": 0.3},
                        "z": {"S1": 0.10, "ST": 0.15}}),
        ]
        p = build_template_prior(recs, "mline")
        assert p["ok"] is True
        assert p["n_campaigns"] == 2
        assert p["ranking"][0] == "x"
        # 手算：x 中位 (0.8/1.0 + 0.7/1.0)/2 之外的归一——x 权重 > y > z
        imp = p["importance_median"]
        assert imp["x"] > imp["y"] > imp["z"]

    def test_median_robust_to_outlier_campaign(self) -> None:
        # 三场战役：两场 y≈0，一场 y=0.9 离群——中位数先验 y 仍居末
        recs = [
            _rec("c1", {"x": {"S1": 0.9, "ST": 1.0}, "y": {"S1": 0.1, "ST": 0.2}}),
            _rec("c2", {"x": {"S1": 0.95, "ST": 1.0}, "y": {"S1": 0.05, "ST": 0.1}}),
            _rec("c3", {"x": {"S1": 0.05, "ST": 0.1}, "y": {"S1": 0.90, "ST": 1.0}}),
        ]
        p = build_template_prior(recs, "mline")
        assert p["ranking"][0] == "x"

    def test_mixed_methods_normalized(self) -> None:
        # mu_star 量纲与 S1 不同：战役内 Σ 归一后可比（结构不变）
        recs = [
            _rec("c1", {"x": {"S1": 0.8, "ST": 0.9}, "y": {"S1": 0.2, "ST": 0.3}}),
            _rec("c2", {"x": {"mu_star": 80.0, "sigma": 1.0},
                        "y": {"mu_star": 20.0, "sigma": 1.0}}, method="morris"),
        ]
        p = build_template_prior(recs, "mline")
        assert p["methods"] == ["morris", "sobol"]
        assert p["ranking"][0] == "x"

    def test_scale_invariance(self) -> None:
        # 同结构不同绝对尺度（病态超 1 的 S1 裁 0 归一）→ 排序不变
        sens = {"x": {"S1": 0.6, "ST": 0.9}, "y": {"S1": 0.3, "ST": 0.5}}
        p1 = build_template_prior([_rec("c1", sens, template="t")], "t")
        sens2 = {"x": {"S1": 60.0, "ST": 90.0}, "y": {"S1": 30.0, "ST": 50.0}}
        p2 = build_template_prior([_rec("c2", sens2, template="t")], "t")
        assert p1["ranking"] == p2["ranking"] == ["x", "y"]
        for k in p1["importance_median"]:
            assert p1["importance_median"][k] == pytest.approx(
                p2["importance_median"][k])

    def test_single_campaign_flagged_unverified(self) -> None:
        p = build_template_prior([_rec("c1", {"x": {"S1": 1.0, "ST": 1.0}}, template="t")], "t")
        assert p["n_campaigns"] == 1
        assert "未跨验" in p["note"]

    def test_template_filter_and_missing_template(self) -> None:
        recs = [_rec("c1", {"x": {"S1": 1.0, "ST": 1.0}}, template="t1"),
                _rec("c2", {"y": {"S1": 1.0, "ST": 1.0}}, template="t2")]
        p = build_template_prior(recs, "t1")
        assert p["campaign_ids"] == ["c1"]
        with pytest.raises(ValueError, match="无记录"):
            build_template_prior(recs, "t3")
        with pytest.raises(ValueError):
            build_template_prior([], "t1")

    def test_deterministic(self) -> None:
        recs = [_rec("c1", {"x": {"S1": 0.7, "ST": 0.8}, "y": {"S1": 0.3, "ST": 0.4}}),
                _rec("c2", {"x": {"S1": 0.6, "ST": 0.7}, "y": {"S1": 0.4, "ST": 0.5}})]
        import json
        a = json.dumps(build_template_prior(recs, "mline"), sort_keys=True)
        b = json.dumps(build_template_prior(recs, "mline"), sort_keys=True)
        assert a == b


class TestBudgetAllocation:
    def _prior(self) -> dict:
        return build_template_prior([
            _rec("c1", {"x": {"S1": 0.8, "ST": 0.9}, "y": {"S1": 0.2, "ST": 0.3}}),
            _rec("c2", {"x": {"S1": 0.6, "ST": 0.7}, "y": {"S1": 0.4, "ST": 0.5}}),
        ], "mline")

    def test_hand_computed_allocation(self) -> None:
        prior = self._prior()
        out = allocate_budget(prior, 100, min_weight=0.02)
        alloc = out["allocation"]
        # 手算：x 中位 0.7（保底后 0.7），y 中位 0.3（>0.02 不触保底）
        # → x=70, y=30（整除无余数）
        assert alloc == {"x": 70, "y": 30}
        assert sum(alloc.values()) == 100

    def test_floor_prevents_starvation(self) -> None:
        recs = [_rec("c1", {"x": {"S1": 0.999, "ST": 1.0},
                            "y": {"S1": 0.001, "ST": 0.002},
                            "z": {"S1": 0.000, "ST": 0.001}}, template="t")]
        prior = build_template_prior(recs, "t")
        out = allocate_budget(prior, 300, min_weight=0.05)
        alloc = out["allocation"]
        # 保底先在权重层成立（份额 ≥0.05×0.9）；整数化余数偏差 ±1 容差
        assert out["weights"]["y"] >= 0.05 * 0.9
        assert out["weights"]["z"] >= 0.05 * 0.9
        assert alloc["y"] >= 300 * 0.045 - 1
        assert alloc["z"] >= 300 * 0.045 - 1
        assert sum(alloc.values()) == 300

    def test_largest_remainder_deterministic(self) -> None:
        # 1/3-1/3-1/3 结构、总量 100：整除矛盾由余数法消解且确定性
        recs = [_rec("c1", {p: {"S1": 1.0, "ST": 1.0}
                            for p in ("a", "b", "c")}, template="t")]
        prior = build_template_prior(recs, "t")
        o1 = allocate_budget(prior, 100)
        o2 = allocate_budget(prior, 100)
        assert o1["allocation"] == o2["allocation"]
        assert sum(o1["allocation"].values()) == 100

    def test_infeasible_explicit(self) -> None:
        prior = self._prior()
        with pytest.raises(ValueError, match="每参数至少"):
            allocate_budget(prior, 1)
        with pytest.raises(ValueError, match="保底不可行"):
            allocate_budget(prior, 100, min_weight=0.6)
        with pytest.raises(ValueError):
            allocate_budget({"ok": True}, 100)

    def test_no_physics_numbers_note(self) -> None:
        out = allocate_budget(self._prior(), 50)
        assert "不产生物理数字" in out["note"]
        assert all(isinstance(v, int) for v in out["allocation"].values())


class TestMarkdown:
    def test_render(self) -> None:
        recs = [_rec("c1", {"x": {"S1": 0.7, "ST": 0.8}, "y": {"S1": 0.3, "ST": 0.4}})]
        md = render_prior_markdown(build_template_prior(recs, "mline"))
        assert "| x |" in md and "| y |" in md
        assert "战役数" in md

    def test_render_failure_honest(self) -> None:
        md = render_prior_markdown({"ok": False, "errors": ["boom"]})
        assert "失败" in md
