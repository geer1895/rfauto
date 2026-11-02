"""T-N13 模型驱动多目标 BO（Noise-Aware EHVI 贪心）单测。

验收门预声明账本：runs/aurora_n/w2_tn13/CRITERIA.md（本文件测试编号
G0a-G0g/G1/G2/G3/G4 与之一一对应，门红如实 FAIL 不调门，#122）。
裁判口径（#118 裁判独立三重对拍）：解析 EHVI（本席 Genz 积分+Tallis
截断矩闭式）的裁判 = ①MC 蒙特卡洛逐样本 HI 走 pareto_tools
.exact_hypervolume 现成实现（与解析路径零共享代码）②scipy dblquad
原式二重积分 ③scipy mvn cdf 外部参照。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest
from scipy import integrate
from scipy.stats import multivariate_normal

from rfauto.optimization.mo_bo import (
    MultiObjectiveBO,
    bivariate_normal_cdf,
    ehvi_monte_carlo,
    expected_box_moment,
    expected_hv_improvement_2d,
    hypervolume_improvement_2d,
    staircase_2d,
)
from rfauto.optimization.multiobj_backend import MultiObjBackend
from rfauto.optimization.pareto_tools import exact_hypervolume
from rfauto.optimization.surrogate.multi_task_gp import MultiTaskGPSurrogate
from rfauto.optimization.surrogate.smt_kriging import SMTKrigingSurrogate

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

BOUNDS = {"x0": (0.0, 1.0), "x1": (0.0, 1.0)}
REF_2D = (1.5, 1.5)
FRONT_1 = [(0.4, 0.6)]
FRONT_4 = [(0.1, 0.9), (0.3, 0.6), (0.5, 0.4), (0.8, 0.2)]

#: G0c 候选后验 (μ, Σ) 案（2 维，单位尺度）
_MUCOVS = {
    "far": ([0.05, 0.1], [[0.04, 0.006], [0.006, 0.04]]),
    "near": ([0.45, 0.55], [[0.01, 0.0], [0.0, 0.01]]),
    "corr+": ([0.3, 0.5], [[0.04, 0.0128], [0.0128, 0.04]]),  # ρ=0.8
    "corr-": ([0.3, 0.5], [[0.04, -0.0128], [-0.0128, 0.04]]),  # ρ=−0.8
}


def _zdt1(x: dict[str, float]) -> dict[str, float]:
    """ZDT1 缩配版（2 变量；最小化；解析前沿 f2=1−√f1 于 x1=0）。"""
    f1 = float(x["x0"])
    g = 1.0 + 9.0 * float(x["x1"])
    return {"f1": f1, "f2": float(g * (1.0 - np.sqrt(f1 / g)))}


def _zdt1_np(x: np.ndarray) -> np.ndarray:
    f1 = float(x[0])
    g = 1.0 + 9.0 * float(x[1])
    return np.array([f1, g * (1.0 - np.sqrt(f1 / g))])


def _mt_gp_factory() -> MultiTaskGPSurrogate:
    return MultiTaskGPSurrogate(config={"bounds": BOUNDS, "seed": 20261029})


def _masked_observer(mask_seed: int, rate: float):
    """异位缺测观测模型：按 eval 序号派生掩码（两臂掩码模式逐位相同）。"""
    state = {"i": 0}

    def observe(x: dict[str, float], met: dict[str, float]) -> dict[str, float]:
        i = state["i"]
        state["i"] += 1
        if np.random.default_rng([mask_seed, i]).uniform() < rate:
            out = dict(met)
            out.pop("f2", None)
            return out
        return dict(met)

    return observe


# ─── G0a：Φ₂ vs scipy mvn cdf（外部参照）─────────────────────────────


class TestG0aBivariateCdf:
    def test_matches_scipy_mvn(self):
        worst = 0.0
        for u in (-2.0, -0.5, 0.3, 1.7):
            for m in (-1.8, 0.0, 1.2):
                for rho in (-0.9, -0.4, 0.0, 0.5, 0.95):
                    mine = float(bivariate_normal_cdf(u, m, rho))
                    ref = float(multivariate_normal(
                        mean=[0.0, 0.0],
                        cov=[[1.0, rho], [rho, 1.0]]).cdf([u, m]))
                    assert np.isclose(mine, ref, rtol=1e-6, atol=1e-9), (
                        u, m, rho, mine, ref)
                    worst = max(worst, abs(mine - ref)
                                / max(abs(ref), 1e-9))
        print(f"G0a Φ₂ vs scipy mvn: 60 案全过 isclose(1e-6,1e-9)，"
              f"最差 atol 标度差 {worst:.2e}")

    def test_rho_zero_factorizes(self):
        for u, m in ((0.7, 1.3), (-1.1, 0.4), (2.0, -0.8)):
            mine = float(bivariate_normal_cdf(u, m, 0.0))
            ref = float(multivariate_normal(
                mean=[0.0, 0.0], cov=np.eye(2)).cdf([u, m]))
            assert abs(mine - ref) < 1e-12


# ─── G0b：Q 闭式 vs dblquad 原式二重积分 ─────────────────────────────


class TestG0bQClosedForm:
    @staticmethod
    def _q_numeric(u, m, mu1, s1, mu2, s2, rho):
        mvn = multivariate_normal(
            mean=[mu1, mu2],
            cov=[[s1 * s1, rho * s1 * s2], [rho * s1 * s2, s2 * s2]])

        def integrand(z1, z2):
            return (max(m - z2, 0.0) * max(u - z1, 0.0)) * mvn.pdf([z1, z2])

        val, _ = integrate.dblquad(
            integrand, mu2 - 12 * s2, min(m + 12 * s2, mu2 + 12 * s2),
            mu1 - 12 * s1, min(u + 12 * s1, mu1 + 12 * s1),
            epsabs=1e-11, epsrel=1e-9)
        return val

    def test_q_matches_dblquad(self):
        cases = [
            (0.6, 1.1, 0.2, 0.5, 0.9, 0.4, 0.0),
            (1.4, 0.8, 0.5, 0.6, 0.4, 0.5, 0.7),
            (0.2, 0.2, 0.6, 0.4, 0.7, 0.3, -0.7),
            (1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.3),
        ]
        for u, m, mu1, s1, mu2, s2, rho in cases:
            mine = expected_box_moment(
                u, m, [mu1, mu2],
                [[s1 * s1, rho * s1 * s2], [rho * s1 * s2, s2 * s2]])
            ref = self._q_numeric(u, m, mu1, s1, mu2, s2, rho)
            assert abs(mine - ref) <= 1e-8 + 1e-4 * abs(ref), (
                u, m, rho, mine, ref)
            print(f"  Q({u},{m};ρ={rho}): closed={mine:.10f} "
                  f"dblquad={ref:.10f}")

    def test_q_product_identity_rho_zero(self):
        from scipy.stats import norm
        for u, m in ((0.7, 1.3), (-1.1, 0.4)):
            mine = expected_box_moment(u, m, [0.0, 0.0], np.eye(2))
            ref = ((u * norm.cdf(u) + norm.pdf(u))
                   * (m * norm.cdf(m) + norm.pdf(m)))
            assert abs(mine - ref) < 1e-12


# ─── G0c：EHVI 解析 vs MC-over-pareto_tools（裁判独立主门）──────────


class TestG0cEhviAnalyticVsMc:
    def test_general_cases(self):
        for fname, front in (("single", FRONT_1), ("multi4", FRONT_4)):
            for mname in ("far", "near", "corr+", "corr-"):
                mu, cov = _MUCOVS[mname]
                a = expected_hv_improvement_2d(mu, cov, front, REF_2D)
                mc = ehvi_monte_carlo(mu, cov, front, REF_2D,
                                      n_samples=25000, seed=123)
                assert a >= 0.0 and mc >= 0.0
                if fname == "multi4" and mname == "near":
                    continue  # 唯一 |解析|<0.05 案归小值组（绝对门）
                assert abs(a - mc) <= 1e-3 + 0.10 * abs(a), (
                    fname, mname, a, mc)
                print(f"  EHVI {fname}/{mname}: analytic={a:.6f} "
                      f"mc={mc:.6f} rel={abs(a - mc) / max(abs(a), 1e-12):.2e}")

    def test_small_value_cases(self):
        mu, cov = _MUCOVS["near"]
        a = expected_hv_improvement_2d(mu, cov, FRONT_4, REF_2D)
        mc = ehvi_monte_carlo(mu, cov, FRONT_4, REF_2D,
                              n_samples=40000, seed=123)
        assert 0.0 < a < 0.05  # 预声明：本组为小 EHVI 案
        assert abs(a - mc) <= 5e-3, (a, mc)
        print(f"  EHVI multi4/near: analytic={a:.6f} mc={mc:.6f} "
              f"abs={abs(a - mc):.2e}（门 5e-3）")

    def test_dominated_point_invariance_and_nonneg(self):
        mu, cov = _MUCOVS["far"]
        base = expected_hv_improvement_2d(mu, cov, FRONT_4, REF_2D)
        with_dom = expected_hv_improvement_2d(
            mu, cov, [*FRONT_4, (0.35, 0.7)], REF_2D)  # (0.35,0.7) 被 (0.3,0.6) 支配
        assert base == with_dom  # 阶梯不变 → 解析逐位不变
        assert base >= 0.0
        assert staircase_2d(
            [*FRONT_4, (0.35, 0.7)], REF_2D) == staircase_2d(FRONT_4, REF_2D)

    def test_degenerate_cov_falls_back_to_hi_at_mean(self):
        mu, _ = _MUCOVS["far"]
        hi_mean = hypervolume_improvement_2d(mu, FRONT_4, REF_2D)
        tiny = expected_hv_improvement_2d(
            mu, [[1e-24, 0.0], [0.0, 1e-24]], FRONT_4, REF_2D)
        assert abs(tiny - hi_mean) <= 1e-9, (tiny, hi_mean)
        zero = expected_hv_improvement_2d(
            mu, [[0.0, 0.0], [0.0, 0.0]], FRONT_4, REF_2D)
        assert abs(zero - hi_mean) <= 1e-12 + 1e-9 * hi_mean


# ─── M>2 MC 路径数值性质（CRITERIA §3 诚实边界）──────────────────────


class TestMcMultiObjectiveProperties:
    FRONT_3D: ClassVar[list[tuple[float, float, float]]] = [
        (0.1, 0.9, 0.5), (0.3, 0.6, 0.8), (0.7, 0.3, 0.4)]
    REF_3D: ClassVar[tuple[float, float, float]] = (1.5, 1.5, 1.5)

    def test_mc_m3_nonneg_and_dominated_invariance(self):
        mu, cov = [0.2, 0.4, 0.6], np.diag([0.04, 0.04, 0.04])
        base = ehvi_monte_carlo(mu, cov, self.FRONT_3D, self.REF_3D,
                                n_samples=4000, seed=5)
        assert base >= 0.0
        with_dom = ehvi_monte_carlo(
            mu, cov, [*self.FRONT_3D, (0.35, 0.7, 0.9)], self.REF_3D,
            n_samples=4000, seed=5)
        # 被支配点对 HV 无贡献；切分坐标变化允许 ulp 级浮点差
        assert abs(base - with_dom) <= 1e-12 + 1e-12 * abs(base)

    def test_mc_m3_zero_cov_close_to_hi_at_mean(self):
        hi_mean = exact_hypervolume(
            [*self.FRONT_3D, tuple(self.FRONT_3D[0])], self.REF_3D) \
            - exact_hypervolume(self.FRONT_3D, self.REF_3D)
        val = ehvi_monte_carlo(list(self.FRONT_3D[0]),
                               np.zeros((3, 3)), self.FRONT_3D, self.REF_3D,
                               n_samples=2000, seed=5)
        assert abs(val - hi_mean) <= 1e-4, (val, hi_mean)


# ─── G3：负例（退化标量显式拒绝）+ 构造校验 ──────────────────────────


class TestG3Negative:
    def test_single_metric_rejected_with_sbo_pointer(self):
        with pytest.raises(ValueError, match="surrogate_loop"):
            MultiObjectiveBO(BOUNDS, ["f1"], _mt_gp_factory())

    def test_zero_metric_rejected(self):
        with pytest.raises(ValueError):
            MultiObjectiveBO(BOUNDS, [], _mt_gp_factory())

    def test_duplicate_metric_rejected(self):
        with pytest.raises(ValueError, match="重复"):
            MultiObjectiveBO(BOUNDS, ["f1", "f1"], _mt_gp_factory())

    def test_ref_point_length_mismatch(self):
        with pytest.raises(ValueError, match="ref_point"):
            MultiObjectiveBO(BOUNDS, ["f1", "f2"], _mt_gp_factory(),
                             ref_point=(1.0, 1.0, 1.0))

    def test_bad_bounds_rejected(self):
        with pytest.raises(ValueError, match="bounds"):
            MultiObjectiveBO({"x0": (1.0, 0.0)}, ["f1", "f2"],
                             _mt_gp_factory())

    def test_batch_larger_than_candidates_rejected(self):
        with pytest.raises(ValueError, match="batch_size"):
            MultiObjectiveBO(BOUNDS, ["f1", "f2"], _mt_gp_factory(),
                             batch_size=4, n_candidates=2)


# ─── G4：确定性钉（同 seed 逐位）─────────────────────────────────────


class TestG4Determinism:
    def test_analytic_ehvi_repeatable(self):
        mu, cov = _MUCOVS["corr+"]
        a1 = expected_hv_improvement_2d(mu, cov, FRONT_4, REF_2D)
        a2 = expected_hv_improvement_2d(mu, cov, FRONT_4, REF_2D)
        assert a1 == a2  # 逐位

    def test_loop_same_seed_bitwise(self):
        runs = []
        for _ in range(2):
            mo = MultiObjectiveBO(
                BOUNDS, ["f1", "f2"], _mt_gp_factory(), ref_point=REF_2D,
                n_init=6, n_iter=4, batch_size=1, n_candidates=48, seed=7)
            runs.append(mo.run(_zdt1))
        assert runs[0]["hv_curve"] == runs[1]["hv_curve"]  # 逐位 ==
        assert runs[0]["acquisitions"] == runs[1]["acquisitions"]
        assert [s["params"] for s in runs[0]["samples"]] == \
            [s["params"] for s in runs[1]["samples"]]


# ─── G1：ZDT1 同预算对照 NSGA-II（验收①）────────────────────────────


class TestG1Zdt1VsNsga2:
    def test_ehvi_loop_not_worse_majority_seeds(self):
        rows = []
        for seed in (0, 1, 2):
            mo = MultiObjectiveBO(
                BOUNDS, ["f1", "f2"], _mt_gp_factory(), ref_point=REF_2D,
                n_init=6, n_iter=14, batch_size=1, n_candidates=256,
                seed=seed)
            r1 = mo.run(_zdt1)
            hv1 = exact_hypervolume(r1["front"], REF_2D)
            backend = MultiObjBackend(
                n_objectives=2, n_variables=2,
                bounds=(np.zeros(2), np.ones(2)))
            r2 = backend.optimize(_zdt1_np, n_gen=2, pop_size=10, seed=seed)
            hv2 = exact_hypervolume(r2["pareto_front"], REF_2D)
            assert r1["n_evaluations"] == 20
            assert r2["n_evaluations"] == 20  # 同预算
            rows.append((seed, hv1, hv2))
            print(f"  seed={seed}: EHVI-BO HV={hv1:.5f}  "
                  f"NSGA-II HV={hv2:.5f}  diff={hv1 - hv2:+.5f}")
        wins = sum(1 for _s, a, b in rows if a >= b)
        print(f"G1 门: {wins}/3 seed EHVI-BO ≥ NSGA-II（预声明 ≥2/3）")
        assert wins >= 2


# ─── G2：跨指标相关利用（验收②）─────────────────────────────────────


class TestG2CorrelationExploitation:
    @staticmethod
    def _objective(x: dict[str, float]) -> dict[str, float]:
        h = (0.8 * np.sin(2 * np.pi * float(x["x0"]))
             * np.cos(np.pi * float(x["x1"])) + 0.3 * float(x["x0"]))
        return {"f1": float(1.0 + h),
                "f2": float(0.9 * h + 0.1 * float(x["x1"]) + 1.0)}

    def test_mt_gp_beats_independent_under_masking(self):
        ref = (2.6, 3.0)
        arms = {
            "mt_gp": _mt_gp_factory(),
            "smt": SMTKrigingSurrogate(
                config={"bounds": BOUNDS, "theta0": 0.1}),
        }
        hvs: dict[str, list[float]] = {}
        for name, surrogate in arms.items():
            hvs[name] = []
            for seed in (0, 1, 2):
                mo = MultiObjectiveBO(
                    BOUNDS, ["f1", "f2"], surrogate, ref_point=ref,
                    n_init=6, n_iter=8, batch_size=1, n_candidates=192,
                    seed=seed)
                res = mo.run(self._objective,
                             metric_observer=_masked_observer(777, 0.40))
                hv = exact_hypervolume(res["front"], ref)
                hvs[name].append(hv)
                n_f2 = sum(1 for s in res["samples"] if "f2" in s["metrics"])
                print(f"  {name} seed={seed}: HV={hv:.5f}  "
                      f"f2 observed {n_f2}/{res['n_evaluations']}")
        mean_mt = sum(hvs["mt_gp"]) / 3.0
        mean_smt = sum(hvs["smt"]) / 3.0
        strict = sum(1 for a, b in zip(hvs["mt_gp"], hvs["smt"],
                                       strict=True) if a > b)
        print(f"G2 门: mt_gp mean={mean_mt:.5f} > smt mean={mean_smt:.5f} "
              f"(Δ={mean_mt - mean_smt:+.5f})，严格胜 {strict}/3"
              "（预声明：mean 严格更大 且 ≥2/3 严格胜）")
        assert mean_mt > mean_smt
        assert strict >= 2


# ─── 环级行为：批采集/M>2 通路/缺测守卫 ──────────────────────────────


class TestLoopBehavior:
    def test_batch_greedy_distinct_and_budget(self):
        mo = MultiObjectiveBO(
            BOUNDS, ["f1", "f2"], _mt_gp_factory(), ref_point=REF_2D,
            n_init=6, n_iter=3, batch_size=2, n_candidates=32, seed=3)
        res = mo.run(_zdt1)
        assert res["n_evaluations"] == 6 + 3 * 2
        assert len(res["acquisitions"]) == 6
        assert len(res["hv_curve"]) == 1 + 3
        for i in range(0, 6, 2):  # 批内不放回：两两互异
            assert res["acquisitions"][i] != res["acquisitions"][i + 1]

    def test_m3_mc_path_runs(self):
        def obj3(x):
            return {"f1": float(x["x0"]) + float(x["x1"]),
                    "f2": float(x["x0"]) + 2.0 * float(x["x1"]),
                    "f3": 1.0 + abs(float(x["x0"]) - float(x["x1"]))}

        mo = MultiObjectiveBO(
            BOUNDS, ["f1", "f2", "f3"], _mt_gp_factory(),
            ref_point=(2.5, 3.5, 2.0), n_init=6, n_iter=2, batch_size=1,
            n_candidates=24, seed=4, mc_samples=16)
        res = mo.run(obj3)
        assert res["ok"] and len(res["hv_curve"]) == 3
        assert all(np.isfinite(v) for v in res["hv_curve"])
        assert res["info"]["mc_samples"] == 16

    def test_all_masked_metric_raises_honest(self):
        def drop_f2(x, met):
            out = dict(met)
            out.pop("f2", None)
            return out

        mo = MultiObjectiveBO(
            BOUNDS, ["f1", "f2"], _mt_gp_factory(), ref_point=REF_2D,
            n_init=6, n_iter=2, n_candidates=16, seed=5)
        with pytest.raises(ValueError, match="可建模"):
            mo.run(_zdt1, metric_observer=drop_f2)

    def test_default_ref_point_frozen(self):
        mo = MultiObjectiveBO(
            BOUNDS, ["f1", "f2"], _mt_gp_factory(), n_init=6, n_iter=1,
            n_candidates=16, seed=6)
        res = mo.run(_zdt1)
        assert len(res["ref_point"]) == 2
        assert all(v > 1.0 for v in res["ref_point"])  # 缺省 = 最差+余量
