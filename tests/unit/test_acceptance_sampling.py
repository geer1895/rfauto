"""PT-5 验收抽样内核单测（OC 曲线 + AQL/LTPD 反查 + 属性 SPRT）。

裁判独立性（#118）：OC 恒等式用 math.comb 暴力和（不经 scipy 二项路径）、
SPRT 用固定 seed 蒙特卡洛（α/β 经验值 + ASN 比值带，同 test_sprt.py 先例）、
文献数值例（c=0 计划 LTPD 10%/β 10% 档 n=22）由闭式恒等式 (1−p)^n ≤ β
自证——不依赖文献转抄（铁律 5/7：数值只在确定性内核，出处见内核 docstring）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core import acceptance_sampling as asamp

# ─── 独立裁判：math.comb 暴力和（不经 scipy 二项路径）────────────────────────


def _pa_brute(p: float, n: int, c: int) -> float:
    return sum(
        math.comb(n, k) * p**k * (1.0 - p) ** (n - k) for k in range(0, min(c, n) + 1)
    )


def _pa_hyper_brute(d: int, lot: int, n: int, c: int) -> float:
    total = math.comb(lot, n)
    acc = 0.0
    for k in range(max(0, n - (lot - d)), min(c, d) + 1):
        acc += math.comb(d, k) * math.comb(lot - d, n - k)
    return acc / total


class TestOcCurves:
    def test_binomial_matches_brute_force(self):
        for p, n, c in [(0.01, 89, 2), (0.05, 50, 1), (0.20, 12, 3), (0.5, 20, 10)]:
            assert abs(asamp.binomial_oc(p, n, c) - _pa_brute(p, n, c)) <= 1e-12

    def test_binomial_identities(self):
        assert asamp.binomial_oc(0.0, 89, 2) == 1.0
        assert asamp.binomial_oc(1.0, 89, 2) == 0.0
        assert asamp.binomial_oc(0.3, 5, 5) == 1.0  # c>=n 恒判收
        assert asamp.binomial_oc(0.3, 5, 7) == 1.0

    def test_poisson_independent_crosscheck(self):
        # 小 p 大 n：二项 OC ≈ 泊松近似 Σ e^{-np}(np)^k/k!（独立分布族裁判）
        p, n, c = 0.005, 89, 2
        lam = n * p
        pa_poisson = float(stats.poisson.cdf(c, lam))
        assert abs(asamp.binomial_oc(p, n, c) - pa_poisson) <= 1e-3

    def test_hypergeometric_matches_brute_force(self):
        for d, lot, n, c in [(4, 50, 10, 1), (10, 100, 20, 2), (1, 30, 8, 0)]:
            assert (
                abs(asamp.hypergeometric_oc(d, lot, n, c) - _pa_hyper_brute(d, lot, n, c))
                <= 1e-12
            )

    def test_hypergeometric_boundaries_and_binomial_convergence(self):
        assert asamp.hypergeometric_oc(0, 200, 20, 1) == 1.0
        assert asamp.hypergeometric_oc(200, 200, 20, 19) == 0.0  # 全不合格且 c<n
        # 大批低抽样比：超几何 → 二项（有限总体修正趋零）
        n, p = 50, 0.05
        lot = 100_000
        d = round(p * lot)
        assert abs(asamp.hypergeometric_oc(d, lot, n, 3) - asamp.binomial_oc(p, n, 3)) < 1e-3

    def test_oc_curve_binomial_and_hypergeometric_meta(self):
        r = asamp.oc_curve([0.0, 0.01, 0.05], 89, 2)
        assert r["kind"] == "binomial"
        assert r["p_accept"][0] == 1.0
        assert abs(r["p_accept"][2] - _pa_brute(0.05, 89, 2)) <= 1e-12
        r2 = asamp.oc_curve([0.05], 20, 1, lot_size=500)
        assert r2["kind"] == "hypergeometric"
        assert r2["defect_rule"] == "D = round(p * lot_size)"
        d = round(0.05 * 500)
        assert abs(r2["p_accept"][0] - _pa_hyper_brute(d, 500, 20, 1)) <= 1e-12

    def test_oc_curve_input_guards(self):
        with pytest.raises(ValueError, match="p_grid 不能为空"):
            asamp.oc_curve([], 10, 1)
        with pytest.raises(ValueError):
            asamp.binomial_oc(-0.1, 10, 1)
        with pytest.raises(ValueError):
            asamp.binomial_oc(True, 10, 1)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            asamp.hypergeometric_oc(60, 50, 10, 1)  # defects>lot
        with pytest.raises(ValueError):
            asamp.oc_curve([0.5], 10.5, 1)  # type: ignore[arg-type]


class TestDesignPlan:
    def test_c0_plan_identity_and_literature_anchor(self):
        # LTPD=10%、β=10%：n = ln0.1/ln0.9 = 21.85 → 22（零接受数计划表标准档）
        r = asamp.c0_plan(0.10, 0.10)
        assert r["n"] == 22
        assert r["c"] == 0
        # 恒等式自证：(1−p)^22 ≤ β 且 (1−p)^21 > β（最小性）
        assert (0.9**22) <= 0.10
        assert (0.9**21) > 0.10
        assert abs(r["p_accept_at_ltpd"] - 0.9**22) <= 1e-15
        assert r["beta_actual"] <= 0.10

    def test_design_plan_satisfies_both_risks(self):
        r = asamp.design_plan(0.01, 0.05, 0.05, 0.10)
        assert r["n"] is not None and r["c"] is not None
        n, c = r["n"], r["c"]
        pa_aql = _pa_brute(0.01, n, c)
        pa_ltpd = _pa_brute(0.05, n, c)
        assert pa_aql >= 0.95
        assert pa_ltpd <= 0.10
        assert abs(r["p_accept_at_aql"] - pa_aql) <= 1e-12
        assert abs(r["p_accept_at_ltpd"] - pa_ltpd) <= 1e-12
        assert r["alpha_actual"] <= 0.05
        assert r["beta_actual"] <= 0.10

    def test_design_plan_minimality_bruteforce(self):
        # 独立枚举裁判：任何 (c'<c) 或 (c'=c 且 n'<n) 均不可行
        aql, ltpd, alpha, beta = 0.02, 0.08, 0.05, 0.10
        r = asamp.design_plan(aql, ltpd, alpha, beta)
        assert r["n"] is not None and r["c"] is not None
        n, c = r["n"], r["c"]

        def feasible(nn, cc):
            return _pa_brute(aql, nn, cc) >= 1 - alpha and _pa_brute(ltpd, nn, cc) <= beta

        assert feasible(n, c)
        for cc in range(0, c):
            assert not feasible(n, cc)
        assert not feasible(n - 1, c)

    def test_design_plan_input_guards(self):
        with pytest.raises(ValueError, match="aql 必须 < ltpd"):
            asamp.design_plan(0.05, 0.05, 0.05, 0.10)
        with pytest.raises(ValueError, match="aql 必须 < ltpd"):
            asamp.design_plan(0.08, 0.02, 0.05, 0.10)
        with pytest.raises(ValueError):
            asamp.design_plan(0.01, 0.05, 0.0, 0.10)  # 风险必须开区间
        with pytest.raises(ValueError):
            asamp.design_plan(0.01, 0.05, True, 0.10)  # type: ignore[arg-type]


class TestSprtAttribute:
    def test_bounds_reuse_wald_single_source(self):
        # A = ln((1−β)/α)、B = ln(β/(1−α))；与 core/sprt.py 同源（复用不重写）
        r = asamp.sprt_attribute_run([], 0.2, 0.6, 0.05, 0.10)
        assert abs(r["a"] - math.log(0.90 / 0.05)) <= 1e-12
        assert abs(r["b"] - math.log(0.10 / 0.95)) <= 1e-12

    def test_bernoulli_llr_hand_values(self):
        assert abs(asamp.bernoulli_llr(1, 0.2, 0.6) - math.log(3.0)) <= 1e-12
        assert abs(asamp.bernoulli_llr(0, 0.2, 0.6) - math.log(0.5)) <= 1e-12

    def test_sprt_run_deterministic_trace(self):
        # p0=0.2, p1=0.6, α=0.05, β=0.10：手工轨迹（math.log 独立累加）
        seq = [0, 0, 1, 1, 1]
        expect = 0.0
        for x in seq:
            expect += math.log(3.0) if x == 1 else math.log(0.5)
        r = asamp.sprt_attribute_run(seq, 0.2, 0.6, 0.05, 0.10)
        assert r["decision"] == "continue"
        assert r["n_used"] == 5
        assert abs(r["llr"] - expect) <= 1e-12
        assert len(r["llr_trace"]) == 5

    def test_sprt_run_reject_and_accept_paths(self):
        # 连续不合格件：Λ 单调增穿 A → reject_lot
        r = asamp.sprt_attribute_run([0, 1, 1, 1, 1, 1], 0.2, 0.6, 0.05, 0.10)
        assert r["decision"] == "reject_lot"
        assert r["llr"] >= r["a"]
        assert r["n_used"] < 6
        # 连续合格件：Λ 单调降穿 B → accept_lot
        r2 = asamp.sprt_attribute_run([0] * 12, 0.2, 0.6, 0.05, 0.10)
        assert r2["decision"] == "accept_lot"
        assert r2["llr"] <= r2["b"]

    def test_sprt_run_input_guards(self):
        with pytest.raises(ValueError, match="p0 必须 < p1"):
            asamp.sprt_attribute_run([0], 0.6, 0.2, 0.05, 0.10)
        with pytest.raises(ValueError, match="只含 0"):
            asamp.sprt_attribute_run([0, 2], 0.2, 0.6, 0.05, 0.10)
        with pytest.raises(ValueError, match="只含 0"):
            asamp.sprt_attribute_run([0, True], 0.2, 0.6, 0.05, 0.10)  # type: ignore[list-item]
        with pytest.raises(ValueError):
            asamp.bernoulli_llr(0.5, 0.2, 0.6)

    def test_asn_closed_form_at_anchors(self):
        alpha, beta = 0.05, 0.10
        a = math.log((1 - beta) / alpha)
        b = math.log(beta / (1 - alpha))
        ez0 = 0.2 * math.log(3.0) + 0.8 * math.log(0.5)
        ez1 = 0.6 * math.log(3.0) + 0.4 * math.log(0.5)
        r0 = asamp.asn_attribute(0.2, 0.2, 0.6, alpha, beta)
        r1 = asamp.asn_attribute(0.6, 0.2, 0.6, alpha, beta)
        assert abs(r0["asn"] - ((1 - alpha) * b + alpha * a) / ez0) <= 1e-12
        assert abs(r1["asn"] - (beta * b + (1 - beta) * a) / ez1) <= 1e-12
        with pytest.raises(ValueError, match="只定义在"):
            asamp.asn_attribute(0.4, 0.2, 0.6, alpha, beta)

    def test_mc_alpha_beta_and_asn_band(self):
        # 固定 seed 蒙特卡洛独立裁判（经验 α/β 复现名义风险；ASN 比值带同
        # test_sprt.py 先例：一阶近似忽略过冲 → MC ≥ 闭式，容差带上限）
        rng = np.random.default_rng(20261003)
        p0, p1, alpha, beta = 0.10, 0.30, 0.05, 0.10
        cap = 500
        trials = 4000
        decide_h1_at_p0 = 0
        stop_lens_p0 = []
        for _ in range(trials):
            r = asamp.sprt_attribute_run(
                rng.binomial(1, p0, size=cap).tolist(), p0, p1, alpha, beta
            )
            if r["decision"] == "reject_lot":
                decide_h1_at_p0 += 1
                stop_lens_p0.append(r["n_used"])
            elif r["decision"] == "accept_lot":
                stop_lens_p0.append(r["n_used"])
            # continue（触 cap 未决）不计入停止样本
        # 经验 α（真值 p0 时误判拒收）∈ 名义 ±0.02
        assert abs(decide_h1_at_p0 / trials - alpha) <= 0.02
        # 停止样本 ASN：MC/闭式 ∈ [0.9, 1.4]（过冲高估为主，触 cap 略降）
        asn0 = asamp.asn_attribute(p0, p0, p1, alpha, beta)["asn"]
        ratio = float(np.mean(stop_lens_p0)) / asn0
        assert 0.9 <= ratio <= 1.4
        # β 侧：独立第二 MC（真值 p1 时误判接收）
        rng2 = np.random.default_rng(424242)
        acc = 0
        for _ in range(trials):
            rr = asamp.sprt_attribute_run(
                rng2.binomial(1, p1, size=cap).tolist(), p0, p1, alpha, beta
            )
            if rr["decision"] == "accept_lot":
                acc += 1
        assert abs(acc / trials - beta) <= 0.02
