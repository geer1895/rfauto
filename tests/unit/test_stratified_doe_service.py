"""OP-DOE2（round19 P2）分层采样 DOE 单元测试。

判据预声明（#118 多基准，全合成确定性）：

1. **配额算术恒等**（基准①）：层配额和==n_points、层叉积计数一致；
2. **qmc 分层均匀性**（基准②）：层内连续维 bins=4 各配额/4 点
   （Latin Hypercube 每维一元性质，quota 整除时逐 bin 相等）；
3. **round19 验收原文**：4 维含 2 条件支、bins=4 → 覆盖率 ≥95%
   （LHS/Sobol 双 sampler、多 seed 实测 36/36=100%）；
4. **Sobol×点序相关回归钉**：离散条件若按点序轮转赋值，与 Sobol 首坐
   标（=点序 radical inverse）结构性相关 → 覆盖率塌到 0.556 伪象
   （本席实测）——钉住独立 qmc 坐标赋值后 sobol 覆盖 ≥95%；
5. **条件语义**：非激活层点条件参数=None（inactive_assignments=
   条件参数数×非激活层点数）、激活层点值域合法；
6. **诚实校验**：未知 kind/high≤low/重复名/active_if 引用未声明父或
   父值越界/n_points 非正整数 → ok=False+errors（不抛不静默）。
"""

from __future__ import annotations

import pytest

from rfauto.service.stratified_doe_service import (
    doe_grid_coverage,
    stratified_doe,
    validate_param_spec,
)

#: round19 验收规格：4 维含 2 条件支（条件连续 + 条件离散各一支）
SPEC_4D = [
    {"name": "kind", "kind": "categorical", "values": ["stub", "direct"]},
    {"name": "w_mm", "kind": "continuous", "low": 0.2, "high": 2.0},
    {"name": "stub_len_mm", "kind": "conditional", "low": 1.0,
     "high": 10.0, "active_if": {"kind": "stub"}},
    {"name": "stub_shape", "kind": "conditional", "values": ["rect", "taper"],
     "active_if": {"kind": "stub"}},
]


class TestQuotaAndStratification:
    @pytest.mark.parametrize("n_points", [256, 100, 7])
    def test_quota_arithmetic_identity(self, n_points):
        """基准①：sum(quotas)==n_points（余数前置层）。"""
        rep = stratified_doe(SPEC_4D, n_points, seed=0)
        assert rep["ok"] is True
        d = rep["design"]
        assert len(rep["points"]) == sum(d["quotas"]) == n_points
        assert d["n_layers"] == 2 and len(d["quotas"]) == 2
        assert d["quotas"][0] - d["quotas"][1] in (0, 1)  # 余数前置

    def test_lhs_per_dim_bin_balance(self):
        """基准②：层内连续维每 bin 恰 quota/4 点（LHS 一元性质）。"""
        rep = stratified_doe(SPEC_4D, 256, seed=3)
        stub_pts = [p for p in rep["points"] if p["kind"] == "stub"]
        for dim, lo, hi in (("w_mm", 0.2, 2.0), ("stub_len_mm", 1.0, 10.0)):
            bins = [min(3, int((p[dim] - lo) / (hi - lo) * 4))
                    for p in stub_pts]
            assert bins.count(0) == bins.count(1) == \
                bins.count(2) == bins.count(3) == 32

    def test_no_categorical_single_layer(self):
        spec = [{"name": "x", "kind": "continuous", "low": 0.0,
                 "high": 1.0}]
        rep = stratified_doe(spec, 16, seed=0)
        assert rep["design"]["quotas"] == [16]

    def test_determinism_and_seed_sensitivity(self):
        a = stratified_doe(SPEC_4D, 32, seed=5)["points"]
        b = stratified_doe(SPEC_4D, 32, seed=5)["points"]
        c = stratified_doe(SPEC_4D, 32, seed=6)["points"]
        assert a == b and a != c


class TestConditionalSemantics:
    def test_inactive_none_active_in_range(self):
        rep = stratified_doe(SPEC_4D, 64, seed=1)
        stub = [p for p in rep["points"] if p["kind"] == "stub"]
        direct = [p for p in rep["points"] if p["kind"] == "direct"]
        assert all(p["stub_len_mm"] is None and p["stub_shape"] is None
                   for p in direct)
        assert all(1.0 <= p["stub_len_mm"] <= 10.0
                   and p["stub_shape"] in ("rect", "taper") for p in stub)
        # 逐条件参数×逐点计数（2 条件 × 32 非激活点）
        assert rep["design"]["inactive_assignments"] == 64

    def test_both_shape_values_present(self):
        rep = stratified_doe(SPEC_4D, 64, seed=2)
        shapes = {p["stub_shape"] for p in rep["points"]
                  if p["kind"] == "stub"}
        assert shapes == {"rect", "taper"}


class TestCoverageAcceptance:
    @pytest.mark.parametrize("sampler,seed", [
        ("lhs", 0), ("lhs", 7), ("lhs", 42),
        ("sobol", 0), ("sobol", 7), ("sobol", 42),
    ])
    def test_round19_acceptance_ge_95(self, sampler, seed):
        """round19 验收：4 维 2 条件支覆盖 ≥95%（实测 36/36）。"""
        rep = stratified_doe(SPEC_4D, 256, seed=seed, sampler=sampler)
        cov = doe_grid_coverage(rep["points"], SPEC_4D, bins=4)
        assert cov["ok"] is True
        assert cov["n_cells_applicable"] == 36  # 2层×[4×4×2 + 4×1]
        assert cov["coverage"] >= 0.95

    def test_sobol_index_correlation_regression_pin(self):
        """回归钉：sobol+点序轮转曾塌 0.556（首坐标=点序 radical
        inverse）——独立 qmc 坐标赋值后必须 ≥0.95。"""
        rep = stratified_doe(SPEC_4D, 256, seed=7, sampler="sobol")
        cov = doe_grid_coverage(rep["points"], SPEC_4D, bins=4)
        assert cov["coverage"] >= 0.95

    def test_coverage_bad_points_counted(self):
        rep = stratified_doe(SPEC_4D, 32, seed=0)
        bad_points = [{**p, "stub_len_mm": 5.0}
                      for p in rep["points"] if p["kind"] == "direct"][:1]
        cov = doe_grid_coverage(rep["points"] + bad_points, SPEC_4D, bins=4)
        assert cov["n_bad_points"] == 1


class TestValidationHonesty:
    def test_unknown_kind(self):
        chk = validate_param_spec([{"name": "x", "kind": "quantum"}])
        assert chk["ok"] is False and any("未知 kind" in e
                                          for e in chk["errors"])

    def test_bad_bounds(self):
        chk = validate_param_spec([{"name": "x", "kind": "continuous",
                                    "low": 1.0, "high": 0.0}])
        assert chk["ok"] is False and any("high>low" in e
                                          for e in chk["errors"])

    def test_active_if_parent_not_declared_or_unknown_value(self):
        chk = validate_param_spec([
            {"name": "y", "kind": "conditional", "values": ["a"],
             "active_if": {"ghost": "v"}}])
        assert chk["ok"] is False and any("须在其之前声明" in e
                                          for e in chk["errors"])
        chk = validate_param_spec([
            {"name": "k", "kind": "categorical", "values": ["a"]},
            {"name": "y", "kind": "conditional", "values": ["a"],
             "active_if": {"k": "nope"}}])
        assert chk["ok"] is False and any("不在 k 的 values" in e
                                          for e in chk["errors"])

    def test_duplicate_and_empty(self):
        chk = validate_param_spec([
            {"name": "x", "kind": "categorical", "values": ["a"]},
            {"name": "x", "kind": "categorical", "values": ["b"]}])
        assert chk["ok"] is False and any("重复" in e for e in chk["errors"])
        assert validate_param_spec([])["ok"] is False
        assert validate_param_spec([{"name": "x", "kind": "categorical",
                                     "values": []}])["ok"] is False

    def test_doe_level_errors_not_raised(self):
        assert stratified_doe(SPEC_4D, 0)["ok"] is False
        assert stratified_doe(SPEC_4D, 10, sampler="halton")["ok"] is False
        assert stratified_doe([{"name": "x", "kind": "quantum"}], 10) \
            ["ok"] is False
        # 畸形点逐点计数（n_bad_points 如实）而非整报告翻红
        cov = doe_grid_coverage([{}], SPEC_4D)
        assert cov["ok"] is True
        assert cov["n_bad_points"] == 1 and cov["coverage"] == 0.0
        # 真 spec 错误才翻红
        assert doe_grid_coverage([], SPEC_4D)["ok"] is False
