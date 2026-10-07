"""SV-6：solve_health 网格收敛因子（GCI 接线）单元测试。

接线语义钉（保护既有 9 因子报告面/顺序钉）：

1. **按需追加**：不提供 grid_convergence → 报告与既有形态逐字节同构
   （9 因子、无 grid_convergence 键）；提供 → 追加第 10 因子（位置在
   既有 9 因子之后）；
2. 判读分级（core/gci 语义 + #316 多报方向）：
   - 二阶收敛序列（解析锚：φ(h)=1+h²，h=0.1/0.2/0.4）→ p≈2、
     GCI 带 → PASS（rel ≤ 5% 门）；
   - 收敛但误差带超门（粗网格强曲率样例）→ WARN；
   - 无正收敛阶（差比 ≤1，如 φ(h)=1+h¹ᐟ²）→ FAIL；
   - 逐级零差 → WARN（已收敛与场死不可分辨——对照 excitation 因子）；
   - 输入不合规（<3 网格/缺键）→ UNKNOWN（检查项异常不传染，#105）；
3. verdict 联动：FAIL → unhealthy；WARN → suspect；
4. provenance 兜底路径与显式 kwargs 优先级；恒定比三元入口等价；
5. 既有 9 因子行为回归：无网格输入时 verdict 与因子清单不变。
"""

from __future__ import annotations

import pytest

from rfauto.core.solve_health import solve_health_check

H3 = [0.4, 0.2, 0.1]
F_QUAD = [1.16, 1.04, 1.01]        # φ=1+h²（细→粗序随 h 排序后 1+h²）
F_ORDER_ZERO = [1.2, 1.1, 1.0]     # 逐级等差（差比=1 → p=0 无正收敛阶）
F_ZERO = [2.0, 2.0, 2.0]


def _seq_inputs(h, f):
    return {"h_seq": list(h), "f_seq": list(f)}


class TestFactorPresence:
    def test_absent_input_keeps_nine_factors(self):
        report = solve_health_check()
        names = [f["factor"] for f in report["factors"]]
        assert "grid_convergence" not in names
        assert len(names) == 9
        # 全缺省=各因子 UNKNOWN（既有语义）：无 FAIL/WARN → healthy
        assert report["verdict"] == "healthy"

    def test_provided_input_appends_tenth_factor(self):
        report = solve_health_check(grid_convergence=_seq_inputs(H3, F_QUAD))
        names = [f["factor"] for f in report["factors"]]
        assert names[-1] == "grid_convergence"
        assert len(names) == 10

    def test_provenance_fallback(self):
        report = solve_health_check(
            provenance={"grid_convergence": _seq_inputs(H3, F_QUAD)})
        names = [f["factor"] for f in report["factors"]]
        assert "grid_convergence" in names

    def test_provenance_none_value_ignored(self):
        report = solve_health_check(provenance={"grid_convergence": None})
        assert "grid_convergence" not in [
            f["factor"] for f in report["factors"]]


class TestVerdictGrading:
    def test_convergent_second_order_pass(self):
        f = solve_health_check(
            grid_convergence=_seq_inputs(H3, F_QUAD))["factors"][-1]
        assert f["status"] == "PASS"
        ev = f["evidence"]
        assert ev["convergent"] is True
        assert ev["p"] == pytest.approx(2.0, rel=1e-6)
        assert ev["gci_fine_rel"] <= 0.05
        assert ev["band"] is not None and len(ev["band"]) == 2

    def test_nonpositive_order_fails(self):
        report = solve_health_check(
            grid_convergence=_seq_inputs(H3, F_ORDER_ZERO))
        f = report["factors"][-1]
        assert f["status"] == "FAIL"
        assert report["verdict"] == "unhealthy"
        assert f["evidence"]["convergent"] is False
        assert f["evidence"]["reason"] == "non_positive_observed_order"

    def test_zero_difference_warns(self):
        report = solve_health_check(
            grid_convergence=_seq_inputs(H3, F_ZERO))
        f = report["factors"][-1]
        assert f["status"] == "WARN"
        assert report["verdict"] == "suspect"
        assert "零差" in f["detail"]

    def test_bad_input_unknown_not_infectious(self):
        # 输入不合规（<3 网格）→ UNKNOWN，其余因子照常产出
        report = solve_health_check(
            grid_convergence={"h_seq": [0.1, 0.2], "f_seq": [1.0, 1.1]})
        f = report["factors"][-1]
        assert f["status"] == "UNKNOWN"
        assert f["factor"] == "grid_convergence"

    def test_missing_keys_unknown(self):
        report = solve_health_check(grid_convergence={"h_seq": [0.1, 0.2, 0.4]})
        f = report["factors"][-1]
        assert f["status"] == "UNKNOWN"


class TestTripleEntryAndThresholds:
    def test_constant_ratio_triple_entry(self):
        report = solve_health_check(grid_convergence={
            "f_fine": 1.01, "f_medium": 1.04, "f_coarse": 1.16, "r": 2.0})
        f = report["factors"][-1]
        assert f["status"] == "PASS"
        assert f["evidence"]["r_constant"] is True

    def test_rel_warn_threshold_override(self):
        # 收敛（p=1）但相对带超默认 5% 门：φ=1+0.5h →
        # GCI=1.25·0.05/1=0.0625，rel≈0.0595>0.05 → WARN
        seq = {"h_seq": [0.4, 0.2, 0.1], "f_seq": [1.20, 1.10, 1.05]}
        report = solve_health_check(grid_convergence=seq)
        f = report["factors"][-1]
        assert f["status"] == "WARN"
        # 放宽门到 50% → PASS
        report2 = solve_health_check(grid_convergence={
            **seq, "gci_rel_warn": 0.5})
        assert report2["factors"][-1]["status"] == "PASS"

    def test_explicit_kwargs_beats_provenance(self):
        report = solve_health_check(
            grid_convergence=_seq_inputs(H3, F_ZERO),
            provenance={"grid_convergence": _seq_inputs(H3, F_QUAD)})
        # 显式 kwargs（零差 → WARN）优先于 provenance（→ PASS）
        assert report["factors"][-1]["status"] == "WARN"
