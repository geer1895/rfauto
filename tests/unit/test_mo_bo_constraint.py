"""aurora_p E3 约束 c-EHVI 档单测（mo_bo 约束增量）。

预声明账本 runs/aurora_p/e3/DESIGN.md（形态/选型/与精确 c-EHVI 差距）与
BENCH.md（门数字冻结自探索轮 bench_explore.json；冻结后不调门，#122）。

裁判先行（#300/#118）：
- A1 可行概率 PF 手算锚：Φ(−2) 标准正态表值 + 独立 MC 判据（抽样频率）
  + 端点（σ=0/|z|=40 零 NaN 零 warning）+ "<="/">=" 互补恒等式；
- A2 退化协方差 c-EHVI = 手算 HI × {0,1}：前沿盒并集手算 0.47/0.4925 →
  HI=0.0225（矩形 [0.35,0.5]×[0.45,0.6] 面积直证），先钉 pareto_tools 单源
  裁判过手算基准，再钉 c-EHVI；
- A3 非退化 c-EHVI vs **独立联合 MC** E[HI(Z_f)·1{Z_c≤0}]（逐样本 HI 走
  pareto_tools.exact_hypervolume，与解析路径零共享代码）——本席模型
  （目标代理 ⊥ 约束代理）下乘权式精确，8 案对拍；
- B 行为钉（合成族 f1=1−x0,f2=1−x1,c=x0+x1−1.2≤0；无约束最优 (1,1) 违约
  0.8）：约束臂采集可行率 ≥0.75（探索轮 10/10 run 实测 1.000）且无约束臂
  ≤0.5（实测 0.083–0.333），逐 seed 严格更高；
- C 最优可行回收：约束臂末态可行前沿 HV ≥ 0.80×HV_true（HV_true=0.89
  手算，实测比 ≥0.911）；前沿逐点原始 c≤0；记账 feasible 与真值逐样本一致；
- D 无约束零变化：返回体键集/样本键集/info.kind 冻结（HEAD vs 工作树
  5 案逐位对拍证据 runs/aurora_p/e3/ab_zero_change.json；既有
  test_mo_bo*.py 零改动全绿为门）；
- E 确定性：同 seed 两次逐位（含 constraint_values/feasible/前沿违约量）；
- 负例：空规格/非法 op/非法 target/非序列、PF 负 σ/非有限/形状、约束缺测
  → UNKNOWN 如实降级（不进前沿、计 n_unknown）、全缺 → 显式报错、实例
  不可 deepcopy → 指引改传工厂。
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest
from scipy.stats import norm

from rfauto.optimization.mo_bo import (
    MultiObjectiveBO,
    constrained_expected_hv_improvement_2d,
    expected_hv_improvement_2d,
    hypervolume_improvement_2d,
    normalize_constraint_specs,
    probability_of_feasibility,
)
from rfauto.optimization.pareto_tools import (
    exact_hypervolume,
    nondominated_indices,
)
from rfauto.optimization.surrogate.multi_task_gp import MultiTaskGPSurrogate
from rfauto.optimization.surrogate.smt_kriging import SMTKrigingSurrogate

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

BOUNDS = {"x0": (0.0, 1.0), "x1": (0.0, 1.0)}
REF_2D = (1.5, 1.5)
FRONT_4 = [(0.1, 0.9), (0.3, 0.6), (0.5, 0.4), (0.8, 0.2)]
SPEC_C = normalize_constraint_specs(["c"])

#: 合成族（DESIGN §4）：ref 与手算 HV_true
BENCH_REF = (1.1, 1.1)
HV_TRUE = 0.89  # ∫₀^0.8(0.3+u)du + 0.3×1.1 = 0.56 + 0.33（手算，DESIGN §4）

#: 冻结门（BENCH.md；探索轮 bench_explore.json 实测后留余量冻结）
GATE_CONSTRAINED_RATE_MIN = 0.75   # 实测 1.000（10/10 run）
GATE_UNCONSTRAINED_RATE_MAX = 0.5  # 实测 0.083–0.333
GATE_HV_RATIO_MIN = 0.80           # 实测 ≥0.911


def _family(x: dict[str, float]) -> dict[str, float]:
    """f1=1−x0，f2=1−x1（最小化；无约束最优 (1,1)）；c=x0+x1−1.2 ≤0 可行。"""
    return {"f1": 1.0 - float(x["x0"]), "f2": 1.0 - float(x["x1"]),
            "c": float(x["x0"]) + float(x["x1"]) - 1.2}


def _family_obj_only(x: dict[str, float]) -> dict[str, float]:
    """无约束臂：不知 c（mt_gp 对多余键+内生噪声显式报错=既有契约，不喂）。"""
    return {"f1": 1.0 - float(x["x0"]), "f2": 1.0 - float(x["x1"])}


def _true_feasible(p: dict[str, float]) -> bool:
    return float(p["x0"]) + float(p["x1"]) - 1.2 <= 0.0


def _mt_gp_factory() -> MultiTaskGPSurrogate:
    return MultiTaskGPSurrogate(config={"bounds": BOUNDS, "seed": 20261029})


def _feasible_hv(samples: list[dict]) -> float:
    pts = [[s["metrics"]["f1"], s["metrics"]["f2"]] for s in samples
           if _true_feasible(s["params"])]
    if not pts:
        return 0.0
    keep = nondominated_indices(pts)
    return float(exact_hypervolume([pts[i] for i in keep], BENCH_REF))


def _joint_mc(mean, cov, front, ref, c_mean, c_std, n=40000, seed=11):
    """独立联合 MC：E[HI(Z_f)·1{Z_c≤0}]，HI 逐样本走 pareto_tools（裁判独立）。"""
    rng = np.random.default_rng(seed)
    chol = np.linalg.cholesky(np.asarray(cov, dtype=float))
    zf = np.asarray(mean, dtype=float) + rng.standard_normal((n, 2)) @ chol.T
    zc = c_mean + c_std * rng.standard_normal(n)
    ref_t = tuple(float(v) for v in ref)
    f_pts = [tuple(float(v) for v in p) for p in front]
    base = exact_hypervolume(f_pts, ref_t) if f_pts else 0.0
    acc = 0.0
    for f, c in zip(zf, zc, strict=True):
        if c <= 0.0:
            acc += exact_hypervolume([*f_pts, (float(f[0]), float(f[1]))],
                                     ref_t) - base
    return acc / n


# ─── A1：可行概率手算锚 ───────────────────────────────────────────────


class TestA1FeasibilityProbability:
    def test_phi_minus_two_table_value_and_mc_judge(self):
        # 标准正态表：Φ(2)=0.9772498680518208 → Φ(−2)=0.0227501319481792
        pf = probability_of_feasibility([[0.2]], [[0.1]], SPEC_C)
        assert pf.shape == (1,)
        assert abs(float(pf[0]) - 0.0227501319481792) < 1e-12
        # 独立 MC 判据：抽样频率（n=2e5，3σ≈1.0e-3）
        rng = np.random.default_rng(5)
        draws = 0.2 + 0.1 * rng.standard_normal(200000)
        mc = float(np.mean(draws <= 0.0))
        assert abs(mc - float(pf[0])) <= 1.5e-3, (mc, pf[0])
        print(f"A1 PF: closed={pf[0]:.10f} table=0.0227501319481792 mc={mc:.5f}")

    def test_le_ge_complement_identity(self):
        le = probability_of_feasibility(
            [[0.3]], [[0.2]], normalize_constraint_specs(
                [{"metric": "c", "op": "<=", "target": 0.1}]))
        ge = probability_of_feasibility(
            [[0.3]], [[0.2]], normalize_constraint_specs(
                [{"metric": "c", "op": ">=", "target": 0.1}]))
        assert abs(float(le[0]) + float(ge[0]) - 1.0) < 1e-15
        assert abs(float(le[0]) - float(norm.cdf((0.1 - 0.3) / 0.2))) < 1e-15

    def test_product_over_independent_constraints(self):
        specs = normalize_constraint_specs(["c1", "c2"])
        pf = probability_of_feasibility([[0.1, -0.2]], [[0.1, 0.1]], specs)
        single = (probability_of_feasibility([[0.1]], [[0.1]], specs[:1])[0]
                  * probability_of_feasibility([[-0.2]], [[0.1]], specs[1:])[0])
        assert abs(float(pf[0]) - float(single)) < 1e-15

    def test_endpoints_no_nan_no_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            pf = probability_of_feasibility(
                [[-0.1], [0.1], [0.0], [-40.0], [40.0]],
                [[0.0], [0.0], [0.0], [1.0], [1.0]], SPEC_C)
        assert pf.tolist() == [1.0, 0.0, 1.0, 1.0, 0.0]  # 边界 μ=target 可行

    def test_negative_cases(self):
        with pytest.raises(ValueError, match="负值"):
            probability_of_feasibility([[0.0]], [[-1.0]], SPEC_C)
        with pytest.raises(ValueError, match="非有限"):
            probability_of_feasibility([[np.nan]], [[1.0]], SPEC_C)
        with pytest.raises(ValueError, match="形状"):
            probability_of_feasibility([[0.0, 0.0]], [[1.0, 1.0]], SPEC_C)


# ─── A2：退化协方差 c-EHVI = 手算 HI × {0,1} ─────────────────────────


class TestA2DegenerateHandAnchor:
    FRONT = ((0.2, 0.6), (0.5, 0.3))
    REF = (1.0, 1.0)
    Z = (0.35, 0.45)

    def test_single_source_judge_passes_hand_hv(self):
        # 盒 [0.2,1]×[0.6,1]=0.32，[0.5,1]×[0.3,1]=0.35，交 [0.5,1]×[0.6,1]=0.20
        assert abs(exact_hypervolume(self.FRONT, self.REF) - 0.47) < 1e-12
        # 并入 z：新增恰为矩形 [0.35,0.5]×[0.45,0.6]=0.15×0.15=0.0225
        assert abs(exact_hypervolume([*self.FRONT, self.Z], self.REF)
                   - 0.4925) < 1e-12
        assert abs(hypervolume_improvement_2d(self.Z, self.FRONT, self.REF)
                   - 0.0225) < 1e-12

    def test_cehvi_degenerate_equals_hi_times_indicator(self):
        zero_cov = [[0.0, 0.0], [0.0, 0.0]]
        feas = constrained_expected_hv_improvement_2d(
            self.Z, zero_cov, [-0.1], [0.0], ["c"], self.FRONT, self.REF)
        infeas = constrained_expected_hv_improvement_2d(
            self.Z, zero_cov, [0.1], [0.0], ["c"], self.FRONT, self.REF)
        assert abs(feas - 0.0225) < 1e-12
        assert infeas == 0.0
        # 均值恰在边界（violation=0）= 可行
        edge = constrained_expected_hv_improvement_2d(
            self.Z, zero_cov, [0.0], [0.0], ["c"], self.FRONT, self.REF)
        assert abs(edge - 0.0225) < 1e-12


# ─── A3：非退化 c-EHVI vs 独立联合 MC（乘权式在本席模型下精确）──────


class TestA3FactorizationVsJointMc:
    CASES: ClassVar[dict[str, tuple[list[float], list[list[float]]]]] = {
        "corr+": ([0.3, 0.5], [[0.04, 0.0128], [0.0128, 0.04]]),
        "far": ([0.05, 0.1], [[0.04, 0.006], [0.006, 0.04]]),
    }

    def test_eight_cases_within_mc_gate(self):
        for name, (mean, cov) in self.CASES.items():
            for fr_name, front in (("multi4", FRONT_4), ("empty", [])):
                for c_mean in (-0.1, 0.05):
                    a = constrained_expected_hv_improvement_2d(
                        mean, cov, [c_mean], [0.1], ["c"], front, REF_2D)
                    pf = float(norm.cdf(-c_mean / 0.1))
                    # 乘权恒等：a = EHVI × PF（逐位）
                    assert a == expected_hv_improvement_2d(
                        mean, cov, front, REF_2D) * pf
                    mc = _joint_mc(mean, cov, front, REF_2D, c_mean, 0.1)
                    assert abs(a - mc) <= 1e-3 + 0.10 * abs(a), (
                        name, fr_name, c_mean, a, mc)
                    print(f"  A3 {name}/{fr_name}/c={c_mean}: closed={a:.6f} "
                          f"joint_mc={mc:.6f} "
                          f"rel={abs(a - mc) / max(abs(a), 1e-12):.2e}")

    def test_monotone_in_feasibility(self):
        mean, cov = self.CASES["corr+"]
        vals = [constrained_expected_hv_improvement_2d(
            mean, cov, [cm], [0.1], ["c"], FRONT_4, REF_2D)
            for cm in (-0.3, 0.0, 0.3)]
        assert vals[0] > vals[1] > vals[2] > 0.0

    def test_repeatable_bitwise(self):
        mean, cov = self.CASES["corr+"]
        a1 = constrained_expected_hv_improvement_2d(
            mean, cov, [0.05], [0.1], ["c"], FRONT_4, REF_2D)
        a2 = constrained_expected_hv_improvement_2d(
            mean, cov, [0.05], [0.1], ["c"], FRONT_4, REF_2D)
        assert a1 == a2


# ─── 规格归一化负例 ──────────────────────────────────────────────────


class TestSpecNormalization:
    def test_string_and_dict_forms(self):
        specs = normalize_constraint_specs(
            ["c", {"metric": "s11", "op": ">=", "target": -10}])
        assert specs == [
            {"metric": "c", "op": "<=", "target": 0.0},
            {"metric": "s11", "op": ">=", "target": -10.0}]

    @pytest.mark.parametrize("bad, pattern", [
        ([], "空序列"),
        ("c", "序列"),
        ([{"metric": "c", "op": "<"}], "op"),
        ([{"metric": ""}], "metric"),
        ([{"metric": "c", "target": "abc"}], "target"),
        ([{"metric": "c", "target": float("nan")}], "有限"),
        ([3.0], "字典"),
    ])
    def test_rejected(self, bad, pattern):
        with pytest.raises(ValueError, match=pattern):
            normalize_constraint_specs(bad)

    def test_loop_rejects_empty_constraints(self):
        with pytest.raises(ValueError, match="空序列"):
            MultiObjectiveBO(BOUNDS, ["f1", "f2"], _mt_gp_factory(),
                             constraints=[])


# ─── B/C：合成族行为钉 + 最优可行回收（门数字冻结自 BENCH.md）─────────


class TestBCConstrainedBehavior:
    CFG: ClassVar[dict[str, Any]] = {  # 与探索轮 bench_explore.py 同配置
        "ref_point": BENCH_REF, "n_init": 6, "n_iter": 12,
        "batch_size": 1, "n_candidates": 128}

    def test_feasible_rate_and_recovery_vs_unconstrained(self):
        rows = []
        for seed in (0, 1, 2):
            con = MultiObjectiveBO(BOUNDS, ["f1", "f2"], _mt_gp_factory,
                                   seed=seed, constraints=["c"],
                                   **self.CFG).run(_family)
            unc = MultiObjectiveBO(BOUNDS, ["f1", "f2"], _mt_gp_factory,
                                   seed=seed, **self.CFG).run(_family_obj_only)
            r_con = sum(_true_feasible(p) for p in con["acquisitions"]) / 12
            r_unc = sum(_true_feasible(p) for p in unc["acquisitions"]) / 12
            hv_con = _feasible_hv(con["samples"])
            hv_unc = _feasible_hv(unc["samples"])
            rows.append((seed, r_con, r_unc, hv_con, hv_unc))
            print(f"  B seed={seed}: feasible rate con={r_con:.3f} "
                  f"unc={r_unc:.3f} | feasible-front HV con={hv_con:.4f} "
                  f"({hv_con / HV_TRUE:.3f}×true) unc={hv_unc:.4f}")
            # B：可行率门（冻结）+ 逐 seed 严格更高
            assert r_con >= GATE_CONSTRAINED_RATE_MIN, (seed, r_con)
            assert r_unc <= GATE_UNCONSTRAINED_RATE_MAX, (seed, r_unc)
            assert r_con > r_unc
            # C：回收门（冻结）+ 前沿逐点真可行 + 记账一致
            assert con["n_feasible"] >= 1
            assert hv_con >= GATE_HV_RATIO_MIN * HV_TRUE, (seed, hv_con)
            assert hv_con > hv_unc
            assert abs(con["hv_curve"][-1] - hv_con) < 1e-12  # 曲线=可行前沿 HV
            for pt_params, cv in zip(con["front_params"],
                                     con["front_constraint_values"],
                                     strict=True):
                assert _true_feasible(pt_params)
                assert cv == [0.0]
            for s in con["samples"]:
                raw = s["metrics"]["c"]
                assert s["feasible"] is (raw <= 0.0)
                assert s["constraint_values"] == [max(raw, 0.0)]
            assert con["n_feasible"] == sum(
                1 for s in con["samples"] if _true_feasible(s["params"]))
            assert con["n_unknown_feasibility"] == 0
            assert con["info"]["kind"] == "mo_bo_cehvi_greedy"
            assert con["info"]["n_constraints"] == 1
            assert con["info"]["n_feasibility_fallback"] == 0  # 实测 0/10
            assert con["constraints"] == [
                {"metric": "c", "op": "<=", "target": 0.0}]
        print(f"B/C 门: 约束臂可行率 ≥{GATE_CONSTRAINED_RATE_MIN} 且无约束臂 "
              f"≤{GATE_UNCONSTRAINED_RATE_MAX}，可行前沿 HV ≥"
              f"{GATE_HV_RATIO_MIN}×{HV_TRUE}——3/3 seed 过")

    def test_ge_dict_spec_same_region(self):
        def fam_ge(x):
            out = _family_obj_only(x)
            out["slack"] = 1.2 - float(x["x0"]) - float(x["x1"])
            return out

        res = MultiObjectiveBO(
            BOUNDS, ["f1", "f2"], _mt_gp_factory, seed=0, n_init=6, n_iter=6,
            batch_size=1, n_candidates=64, ref_point=BENCH_REF,
            constraints=[{"metric": "slack", "op": ">=", "target": 0.0}],
        ).run(fam_ge)
        rate = sum(_true_feasible(p) for p in res["acquisitions"]) / 6
        assert rate >= GATE_CONSTRAINED_RATE_MIN, rate
        for s in res["samples"]:
            slack = s["metrics"]["slack"]
            assert s["constraint_values"] == [max(-slack, 0.0)]  # ">=" 违约

    def test_smt_kriging_arm_predict_with_std_path(self):
        res = MultiObjectiveBO(
            BOUNDS, ["f1", "f2"],
            lambda: SMTKrigingSurrogate(config={"bounds": BOUNDS,
                                                "theta0": 0.1}),
            seed=0, n_init=6, n_iter=6, batch_size=1, n_candidates=64,
            ref_point=BENCH_REF, constraints=["c"]).run(_family)
        rate = sum(_true_feasible(p) for p in res["acquisitions"]) / 6
        assert rate >= GATE_CONSTRAINED_RATE_MIN, rate
        assert res["n_feasible"] >= 1

    def test_batch_fantasy_gated_and_m3_mc_path(self):
        res = MultiObjectiveBO(
            BOUNDS, ["f1", "f2"], _mt_gp_factory, seed=1, n_init=6, n_iter=4,
            batch_size=2, n_candidates=48, ref_point=BENCH_REF,
            constraints=["c"]).run(_family)
        acq = res["acquisitions"]
        assert len(acq) == 8 and len(res["hv_curve"]) == 5
        for i in range(0, 8, 2):
            assert acq[i] != acq[i + 1]  # 批内不放回
        assert sum(_true_feasible(p) for p in acq) / 8 >= GATE_CONSTRAINED_RATE_MIN

        def fam3(x):
            out = _family(x)
            out["f3"] = abs(float(x["x0"]) - float(x["x1"]))
            return out

        res3 = MultiObjectiveBO(
            BOUNDS, ["f1", "f2", "f3"], _mt_gp_factory, seed=4, n_init=6,
            n_iter=3, batch_size=1, n_candidates=24, mc_samples=16,
            ref_point=(1.1, 1.1, 1.1), constraints=["c"]).run(fam3)
        assert res3["info"]["kind"] == "mo_bo_cehvi_greedy"
        assert res3["front"] and len(res3["front"][0]) == 3
        assert all(np.isfinite(v) for v in res3["hv_curve"])
        assert all(_true_feasible(p) for p in res3["front_params"])

    def test_instance_form_deepcopied_for_constraints(self):
        inst = MultiTaskGPSurrogate(config={"bounds": BOUNDS, "seed": 20261029})
        mo = MultiObjectiveBO(BOUNDS, ["f1", "f2"], inst, seed=2, n_init=6,
                              n_iter=3, batch_size=1, n_candidates=32,
                              ref_point=BENCH_REF, constraints=["c"])
        assert mo._constraint_surrogate_obj is not inst
        res = mo.run(_family)
        assert res["n_feasible"] >= 1
        assert "c" not in (inst.info_ or {}).get("metrics", [])  # 目标代理不吃约束键

    def test_explicit_constraint_noise_resolved(self):
        res = MultiObjectiveBO(
            BOUNDS, ["f1", "f2"], _mt_gp_factory, seed=8, n_init=6, n_iter=2,
            batch_size=1, n_candidates=32, ref_point=BENCH_REF,
            constraints=["c"],
            noise_variances={"f1": 1e-4, "f2": 1e-4, "c": 1e-3}).run(_family)
        assert res["info"]["constraint_noise_resolved_last"] == [1e-3]
        assert res["info"]["noise_resolved_last"] == [1e-4, 1e-4]


# ─── D：无约束零变化 ─────────────────────────────────────────────────


class TestDUnconstrainedZeroChange:
    RESULT_KEYS = frozenset({"ok", "samples", "hv_curve", "front",
                             "front_params", "ref_point", "acquisitions",
                             "n_evaluations", "info"})
    INFO_KEYS = frozenset({"kind", "n_init", "n_iter", "batch_size",
                           "n_candidates", "mc_samples", "fantasy", "seed",
                           "noise_resolved_last"})

    def test_result_and_sample_key_sets_frozen(self):
        res = MultiObjectiveBO(
            BOUNDS, ["f1", "f2"], _mt_gp_factory, seed=7, n_init=6, n_iter=2,
            batch_size=1, n_candidates=32, ref_point=REF_2D).run(
            _family_obj_only)
        assert frozenset(res) == self.RESULT_KEYS
        assert frozenset(res["info"]) == self.INFO_KEYS
        assert res["info"]["kind"] == "mo_bo_ehvi_greedy"
        assert all(frozenset(s) == {"params", "metrics"} for s in res["samples"])

    def test_constructor_defaults_unconstrained(self):
        mo = MultiObjectiveBO(BOUNDS, ["f1", "f2"], _mt_gp_factory)
        assert mo.constraints is None
        assert mo._constraint_keys == []
        assert mo._constraint_surrogate_obj is None


# ─── E：确定性 ────────────────────────────────────────────────────────


class TestEDeterminism:
    def test_constrained_loop_same_seed_bitwise(self):
        runs = [MultiObjectiveBO(
            BOUNDS, ["f1", "f2"], _mt_gp_factory, seed=7, n_init=6, n_iter=4,
            batch_size=1, n_candidates=48, ref_point=BENCH_REF,
            constraints=["c"]).run(_family) for _ in range(2)]
        a, b = runs
        assert a["hv_curve"] == b["hv_curve"]
        assert a["acquisitions"] == b["acquisitions"]
        assert a["samples"] == b["samples"]
        assert a["front"] == b["front"]
        assert a["front_constraint_values"] == b["front_constraint_values"]
        assert a["n_feasible"] == b["n_feasible"]


# ─── 负例：约束缺测如实降级 / 全缺显式报错 / 实例不可 deepcopy ──────────


class TestNegativeHonest:
    def test_missing_constraint_degrades_to_unknown(self):
        state = {"i": 0}

        def drop_c_sometimes(x, met):
            i = state["i"]
            state["i"] += 1
            out = dict(met)
            if np.random.default_rng([99, i]).uniform() < 0.3:
                out.pop("c", None)
            return out

        res = MultiObjectiveBO(
            BOUNDS, ["f1", "f2"], _mt_gp_factory, seed=3, n_init=8, n_iter=4,
            batch_size=1, n_candidates=48, ref_point=BENCH_REF,
            constraints=["c"]).run(_family, metric_observer=drop_c_sometimes)
        unknown = [s for s in res["samples"] if s["feasible"] is None]
        assert res["n_unknown_feasibility"] == len(unknown) >= 1
        assert all(s["constraint_values"] is None for s in unknown)
        assert all(s["params"] not in res["front_params"] for s in unknown)
        assert res["n_feasible"] + res["n_unknown_feasibility"] <= res[
            "n_evaluations"]
        # UNKNOWN 不冒充可行也不冒充不可行：三态计数自洽
        n_infeasible = sum(1 for s in res["samples"] if s["feasible"] is False)
        assert (res["n_feasible"] + res["n_unknown_feasibility"] + n_infeasible
                == res["n_evaluations"])

    def test_all_constraint_missing_raises_honest(self):
        with pytest.raises(ValueError, match="无任何有限观测"):
            MultiObjectiveBO(
                BOUNDS, ["f1", "f2"], _mt_gp_factory, seed=5, n_init=6,
                n_iter=2, n_candidates=16, ref_point=BENCH_REF,
                constraints=["c"]).run(
                _family, metric_observer=lambda x, m: {
                    k: v for k, v in m.items() if k != "c"})

    def test_instance_not_deepcopyable_points_to_factory(self):
        class Undeepcopyable:
            def fit(self, samples):  # pragma: no cover —— 构造期即拒绝
                return {}

            def __deepcopy__(self, memo):
                raise TypeError("cannot pickle")

        with pytest.raises(ValueError, match="工厂"):
            MultiObjectiveBO(BOUNDS, ["f1", "f2"], Undeepcopyable(),
                             constraints=["c"])
