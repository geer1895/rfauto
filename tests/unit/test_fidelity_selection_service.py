"""OP-MF（round19 P2）保真选择形式化 单元测试——合成双谷 A/B 回放。

判据预声明（#118 双基准，零真机零 LLM——#139）：

1. **EI 闭式核恒等**（基准①）：ΔE(y*,μ,σ) 与 optimization.eipu.
   expected_improvement_min 直调逐位一致；σ=0 确定性分支
   ΔE=max(0, y*−ξ−μ) 手算；
2. **双谷 A/B 回放**（round19 验收原文）：f_hi 双谷（A 深谷@0.3、
   B 浅谷@0.7）；A 臂低保真=f_hi+小扰动（实测 flip=0.071、
   Pearson ρ=0.995）→ 升保真；B 臂低保真=去相关摆动（实测
   flip=0.464、ρ=0.017<阈值→warn）→ 不升。**同 ΔE 同成本经济学**
   （EI≈0.802、budget=0.5）——判定翻转纯由 (flip, ρ) 因子驱动，
   因果隔离；
3. **ρ 因子手算**：g=min(1,|ρ|/0.1)；|ρ|=2→1、0.05→0.5、缺测→None
   不编数；
4. **SMT 端到端消费**（基准②，importorskip smt——可选依赖诚实）：
   真实 SMTMultiFidelitySurrogate.fidelity_diagnostics（OP-7 已合流，
   消费禁改）产出的 ρ 进决策链——相关族 ρ≈2→promote、去相关族
   |ρ|<0.1→stay（同经济学）。
"""

from __future__ import annotations

import math

import pytest

from rfauto.optimization.eipu import expected_improvement_min
from rfauto.service.fidelity_selection_service import (
    fidelity_promote_decision,
    rho_factors_from_diagnostics,
)

_ECON = {"cost_low": 1.0, "cost_high": 1.5, "lambda": 1.0}  # budget=0.5
_EI_INPUT = {"y_best": 1.0, "mu": 0.2, "sigma": 0.5, "xi": 0.01}


def _f_hi(x: float) -> float:
    return (1.0 * math.exp(-((x - 0.3) / 0.05) ** 2)
            + 0.8 * math.exp(-((x - 0.7) / 0.15) ** 2))


def _f_lo_faithful(x: float) -> float:
    return _f_hi(x) + 0.05 * math.sin(20.0 * x)


def _f_lo_misleading(x: float) -> float:
    return (0.05 * math.exp(-((x - 0.7) / 0.15) ** 2)
            * math.cos(30.0 * (x - 0.7)) + 0.2 * math.sin(40.0 * x))


def _arm_stats(f_lo, region: tuple[float, float]) -> tuple[float, float]:
    """低保真 vs 高保真在谷区 8 点：Kendall 不一致占比 + Pearson ρ。"""
    pts = [region[0] + (region[1] - region[0]) * i / 7 for i in range(8)]
    hi = [_f_hi(x) for x in pts]
    lo = [f_lo(x) for x in pts]
    rank_lo = {v: i for i, v in enumerate(sorted(lo))}
    rank_hi = {v: i for i, v in enumerate(sorted(hi))}
    disc = total = 0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            agree = (rank_lo[lo[i]] < rank_lo[lo[j]]) == \
                    (rank_hi[hi[i]] < rank_hi[hi[j]])
            total += 1
            disc += 0 if agree else 1
    mx, my = sum(lo) / 8, sum(hi) / 8
    cov = sum((a - mx) * (b - my) for a, b in zip(lo, hi, strict=True))
    vx = sum((a - mx) ** 2 for a in lo)
    vy = sum((b - my) ** 2 for b in hi)
    return disc / total, cov / math.sqrt(vx * vy)


def _diag(rho: float | None, thr: float = 0.1) -> dict:
    """fidelity_diagnostics 同形态合成（SMT 产出面由 SMT 集成用例覆盖）。"""
    warn = rho is not None and abs(rho) < thr
    return {"metrics": {"f": {"rho": rho, "sigma2_rho": None,
                              "warn": warn, "warning": None}},
            "warn": warn, "rho_warn_threshold": thr}


class TestEiBaseline:
    def test_ei_kernel_identity(self):
        """基准①：ΔE 与 eipu.expected_improvement_min 直调逐位一致。"""
        rep = fidelity_promote_decision({**_EI_INPUT, "rank_flip_rate": 0.0,
                                         **_ECON})
        direct = float(expected_improvement_min([0.2], [0.5], 1.0, 0.01)[0])
        assert rep["ok"] is True
        assert rep["delta_e_best"] == direct
        assert rep["delta_e_basis"].startswith("expected_improvement_min")

    def test_sigma_floor_deterministic_branch(self):
        rep = fidelity_promote_decision({"y_best": 1.0, "mu": 0.6,
                                         "sigma": 0.0, "xi": 0.01,
                                         "rank_flip_rate": 0.0, **_ECON})
        assert rep["delta_e_best"] == pytest.approx(0.39, abs=1e-12)

    def test_explicit_delta_e_path(self):
        rep = fidelity_promote_decision({"delta_e_best": 2.0,
                                         "rank_flip_rate": 0.0, **_ECON})
        assert rep["delta_e_basis"] == "explicit"
        assert rep["decision"] == "promote"  # gain=2.0 > 0.5


class TestTwoValleyABReplay:
    def test_arm_stats_measured_not_assumed(self):
        """回放先验是构造函数的实测统计（flip/ρ 不是拍的）。"""
        flip_a, rho_a = _arm_stats(_f_lo_faithful, (0.15, 0.45))
        flip_b, rho_b = _arm_stats(_f_lo_misleading, (0.55, 0.85))
        assert flip_a < 0.15 and abs(rho_a) > 0.9
        assert flip_b > 0.3 and abs(rho_b) < 0.1

    def test_faithful_arm_promotes(self):
        flip, rho = _arm_stats(_f_lo_faithful, (0.15, 0.45))
        rep = fidelity_promote_decision({**_EI_INPUT,
                                         "rank_flip_rate": flip,
                                         "diagnostics": _diag(rho),
                                         **_ECON})
        assert rep["decision"] == "promote"
        assert rep["gain"] == pytest.approx(
            rep["delta_e_best"] * (1 - flip) * rep["g_rho"], rel=1e-9)
        assert rep["gain"] > rep["budget"]

    def test_misleading_arm_stays_causal_isolation(self):
        """同 ΔE 同 budget——判定翻转纯由 (flip, ρ) 驱动（因果隔离）。"""
        flip, rho = _arm_stats(_f_lo_misleading, (0.55, 0.85))
        rep = fidelity_promote_decision({**_EI_INPUT,
                                         "rank_flip_rate": flip,
                                         "diagnostics": _diag(rho),
                                         **_ECON})
        assert rep["decision"] == "stay"
        assert rep["rho_warn"] is True
        assert rep["g_rho"] < 0.5
        assert rep["gain"] < rep["budget"]

    def test_strict_inequality_tie_stays(self):
        """gain==budget（等号）不升——round19 规则严格大于口径。"""
        rep = fidelity_promote_decision({"delta_e_best": 0.5,
                                         "rank_flip_rate": 0.0, **_ECON})
        assert rep["gain"] == pytest.approx(rep["budget"], abs=1e-12)
        assert rep["decision"] == "stay"


class TestRhoFactors:
    def test_hand_g_values(self):
        rep = rho_factors_from_diagnostics(_diag(2.0))
        assert rep["per_metric"]["f"]["g"] == 1.0  # min(1, 2/0.1) 截顶
        rep = rho_factors_from_diagnostics(_diag(0.05))
        assert rep["per_metric"]["f"]["g"] == pytest.approx(0.5)
        assert rep["g_aggregate"] == 0.5

    def test_rho_none_honest_skip(self):
        rep = rho_factors_from_diagnostics(_diag(None))
        assert rep["ok"] is True
        assert rep["per_metric"]["f"]["g"] is None
        assert rep["skipped_metrics"] == ["f"]
        assert rep["g_aggregate"] is None
        assert "缺测" in rep["note"]

    def test_multi_metric_min_aggregate(self):
        diag = {"metrics": {"f1": {"rho": 0.9, "warn": False},
                            "f2": {"rho": 0.03, "warn": True}},
                "warn": True, "rho_warn_threshold": 0.1}
        rep = rho_factors_from_diagnostics(diag)
        assert rep["g_aggregate"] == pytest.approx(0.3)  # min(1, 0.9) vs 0.3

    def test_bad_shape_honest(self):
        assert rho_factors_from_diagnostics({})["ok"] is False
        assert rho_factors_from_diagnostics(
            {"metrics": {}})["ok"] is False


class TestHonestyAndSmtEndToEnd:
    def test_bad_flip_and_costs_honest(self):
        assert fidelity_promote_decision({**_EI_INPUT,
                                          "rank_flip_rate": 1.5,
                                          **_ECON})["ok"] is False
        assert fidelity_promote_decision({"delta_e_best": 1.0,
                                          "rank_flip_rate": 0.1,
                                          "cost_low": 1.0,
                                          "cost_high": "x"})["ok"] is False

    def test_all_rho_missing_honest(self):
        rep = fidelity_promote_decision({**_EI_INPUT, "rank_flip_rate": 0.1,
                                         "diagnostics": _diag(None),
                                         **_ECON})
        assert rep["ok"] is False and "缺测" in rep["reason"]

    def test_smt_producer_consumer_chain(self):
        """基准②端到端：真实 smt_mfk.fidelity_diagnostics（禁改，仅消费）。"""
        pytest.importorskip("smt")
        from rfauto.optimization.surrogate.smt_mfk import (
            SMTMultiFidelitySurrogate,
        )

        def fit(low_scale, noise, seed=0):
            xh = [i / 5 for i in range(6)]
            yh = [(v - 0.5) ** 2 for v in xh]
            xl = [i / 19 for i in range(20)]
            rng = pytest.importorskip("numpy").random.default_rng(seed)
            yl = [low_scale * (v - 0.5) ** 2 + 0.05
                  + noise * float(rng.standard_normal()) for v in xl]
            hi = [{"params": {"x": v}, "metrics": {"f": y}}
                  for v, y in zip(xh, yh, strict=True)]
            lo = [{"params": {"x": v}, "metrics": {"f": y}}
                  for v, y in zip(xl, yl, strict=True)]
            m = SMTMultiFidelitySurrogate(
                config={"bounds": {"x": (0.0, 1.0)},
                        "low_fi_samples": lo})
            m.fit(hi)
            return m.fidelity_diagnostics()

        good = fit(0.5, 0.0)     # 结构对齐族 → ρ≈2（OP-7 已锚）
        bad = fit(1.0, 2.0, 1)   # 无关噪声族 → |ρ|<0.1（OP-7 已锚）
        econ = {"cost_low": 1.0, "cost_high": 1.1, "lambda": 1.0}
        rep_good = fidelity_promote_decision(
            {**_EI_INPUT, "rank_flip_rate": 0.1, "diagnostics": good,
             "cost_low": 1.0, "cost_high": 1.1, "lambda": 1.0})
        rep_bad = fidelity_promote_decision(
            {**_EI_INPUT, "rank_flip_rate": 0.1, "diagnostics": bad,
             **econ})
        assert rep_good["ok"] and rep_good["g_rho"] == 1.0
        assert rep_good["decision"] == "promote"  # gain≈EI·0.9 > 0.1
        assert rep_bad["rho_warn"] is True
        assert rep_bad["g_rho"] < 0.5
        assert rep_bad["decision"] == "stay"
