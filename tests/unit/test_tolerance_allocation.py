"""M-7 cost-aware 公差分配优化器单测（研究扩充 M-7 判据）。

裁判口径（#118，非推导自证）：
- 闭式裁判 = 测试内独立推导的 KKT 闭式（μ = 2(Σ(aᵢSᵢ)^(2/3)/C)³、
  δᵢ = (μaᵢ/(2Sᵢ²))^(1/3)），与内核 λ 二分数值解逐位对拍；
- 最优性裁判 = 随机可行扰动（保 Σc(δ)=C 逐点重解一支）2000 次无一次
  改进方差 + 预算模式随机 Dirichlet 剖分全不优于闭式；
- 对照法裁判 = greedy/proportional 同预算下 RSS ≥ 拉格朗日解；
- 已知例 = 两参数解析例（S=1,2 / a=1,1 / C=3，closed 数值独立手算）。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import tolerance_allocation as ta

# 两参数解析例（闭式手算钉）
SENS = {"a": 1.0, "b": 2.0}
COEFFS = {"a": 1.0, "b": 1.0}
C_BUDGET = 3.0
TOL_MIN, TOL_MAX = 1e-9, 1e9


def _closed_form_cost_budget(
    sens: dict[str, float], coeffs: dict[str, float], budget: float
) -> dict[str, float]:
    """独立闭式路径（与内核无共享代码）：p=1 inverse_power KKT 全解。"""
    s_sum = sum((coeffs[k] * abs(sens[k])) ** (2.0 / 3.0) for k in sens)
    mu = 2.0 * (s_sum / budget) ** 3
    return {k: (mu * coeffs[k] / (2.0 * sens[k] ** 2)) ** (1.0 / 3.0) for k in sens}


# ─── 1. A 模式（成本预算下最小方差）：闭式回收与约束激活 ─────────────────────


def test_cost_budget_closed_form_recovery():
    res = ta.allocate_cost_budget(SENS, COEFFS, C_BUDGET, tol_min=TOL_MIN, tol_max=TOL_MAX)
    ref = _closed_form_cost_budget(SENS, COEFFS, C_BUDGET)
    for k in SENS:
        assert res.tols[k] == pytest.approx(ref[k], rel=1e-9)
    assert res.feasible and res.method == ta.METHOD_COST_BUDGET


def test_cost_budget_constraint_active():
    res = ta.allocate_cost_budget(SENS, COEFFS, C_BUDGET, tol_min=TOL_MIN, tol_max=TOL_MAX)
    assert res.total_cost == pytest.approx(C_BUDGET, rel=1e-9)
    # 逐参数成本之和（独立重算）也对上
    total = sum(COEFFS[k] / res.tols[k] for k in SENS)
    assert total == pytest.approx(C_BUDGET, rel=1e-9)
    assert res.rss == pytest.approx(
        math.sqrt(sum((SENS[k] * res.tols[k]) ** 2 for k in SENS)), rel=1e-12
    )


def test_cost_budget_optimality_kkt_perturbation():
    """随机可行扰动裁判：2000 次保成本扰动无一次改进方差（#118 独立裁判）。"""
    res = ta.allocate_cost_budget(SENS, COEFFS, C_BUDGET, tol_min=TOL_MIN, tol_max=TOL_MAX)
    base_var = sum((SENS[k] * res.tols[k]) ** 2 for k in SENS)
    rng = np.random.default_rng(7)
    best_gain = 0.0
    for _ in range(2000):
        pert_a = res.tols["a"] * float(np.exp(rng.normal(0.0, 0.5)))
        rhs = C_BUDGET - COEFFS["a"] / pert_a
        if rhs <= 0.0:
            continue
        pert_b = COEFFS["b"] / rhs
        if pert_b <= 0.0:
            continue
        cand_var = (SENS["a"] * pert_a) ** 2 + (SENS["b"] * pert_b) ** 2
        best_gain = max(best_gain, base_var - cand_var)
    assert best_gain <= 1e-9 * base_var


def test_cost_budget_directionality():
    """方向性：贵参数更松、敏感参数更紧（等边际成本）。"""
    res = ta.allocate_cost_budget(
        {"a": 1.0, "b": 1.0}, {"a": 1.0, "b": 4.0}, 2.0, tol_min=TOL_MIN, tol_max=TOL_MAX
    )
    assert res.tols["b"] > res.tols["a"]  # b 贵 4 倍 → 更松
    res2 = ta.allocate_cost_budget(
        {"a": 1.0, "b": 4.0}, {"a": 1.0, "b": 1.0}, 2.0, tol_min=TOL_MIN, tol_max=TOL_MAX
    )
    assert res2.tols["b"] < res2.tols["a"]  # b 敏感 4 倍 → 更紧


def test_cost_budget_p2_exponential_grid_referee():
    """p=2 与 exponential（round1 缺省成本型）走粗网格独立复核。"""
    grid = np.geomspace(0.2, 5.0, 120)
    for model, kw in (
        (ta.COST_INVERSE_POWER, {"cost_power": 2.0}),
        (ta.COST_EXPONENTIAL, {"exp_scale": 0.5}),
    ):
        res = ta.allocate_cost_budget(
            SENS, COEFFS, 4.0, cost_model=model, tol_min=0.05, tol_max=10.0, **kw
        )
        assert res.feasible
        if model == ta.COST_EXPONENTIAL:
            cost = lambda t: sum(COEFFS[k] * math.exp(-t[k] / 0.5) for k in SENS)  # noqa: E731
        else:
            cost = lambda t: sum(COEFFS[k] / t[k] ** 2 for k in SENS)  # noqa: E731
        assert cost(res.tols) <= 4.0 + 1e-7  # 约束满足
        best_var = min(
            (
                (SENS["a"] * ga) ** 2 + (SENS["b"] * gb) ** 2
                for ga in grid
                for gb in grid
                if cost({"a": ga, "b": gb}) <= 4.0
            ),
            default=float("inf"),
        )
        assert res.rss**2 <= best_var + 1e-9  # 内核解不劣于网格最优


def test_cost_budget_infeasible_and_guards():
    res = ta.allocate_cost_budget(SENS, COEFFS, 1e-30, tol_min=TOL_MIN, tol_max=TOL_MAX)
    assert not res.feasible and res.tols == {} and "不可行" in res.note
    # 预算极宽松 → 约束不激活（全下限）
    slack = ta.allocate_cost_budget(SENS, COEFFS, 1e30, tol_min=1e-3, tol_max=1.0)
    assert slack.feasible and all(v == pytest.approx(1e-3) for v in slack.tols.values())
    for args in (
        (SENS, COEFFS, -1.0),
        (SENS, {"a": 1.0}, 1.0),  # 缺成本系数键
        ({"a": True}, COEFFS, 1.0),  # bool 拒收
        (SENS, COEFFS, float("nan")),
    ):
        with pytest.raises(ValueError):
            ta.allocate_cost_budget(*args)
    with pytest.raises(ValueError):
        ta.allocate_cost_budget(SENS, COEFFS, 1.0, cost_model="magic")
    with pytest.raises(ValueError):
        ta.allocate_cost_budget(SENS, COEFFS, 1.0, cost_model=ta.COST_EXPONENTIAL)  # 缺 exp_scale


# ─── 2. 预算模式（Σδ=T）：闭式与最优性 ───────────────────────────────────────


def test_budget_t_closed_form():
    total = 0.03
    res = ta.allocate_budget_t(SENS, total)
    inv = {k: 1.0 / v**2 for k, v in SENS.items()}
    den = sum(inv.values())
    for k in SENS:
        assert res.tols[k] == pytest.approx(total * inv[k] / den, rel=1e-12)
    assert sum(res.tols.values()) == pytest.approx(total, rel=1e-12)
    assert res.method == ta.METHOD_BUDGET_T


def test_budget_t_optimality_random_splits():
    """预算模式最优性：500 次随机可行剖分全不优于闭式（独立裁判）。"""
    total = 0.03
    res = ta.allocate_budget_t(SENS, total)
    base_var = sum((SENS[k] * res.tols[k]) ** 2 for k in SENS)
    rng = np.random.default_rng(11)
    for _ in range(500):
        w = rng.dirichlet(np.ones(2))
        split = {"a": total * float(w[0]), "b": total * float(w[1])}
        cand = sum((SENS[k] * split[k]) ** 2 for k in SENS)
        assert cand >= base_var - 1e-18


def test_budget_t_clamp_redistribution():
    # tol_max 钳位 + 剩余预算重分配，Σδ 仍 = T（T=0.009 ≤ Σtol_max=0.01 可行）
    res = ta.allocate_budget_t(SENS, 0.009, tol_max=0.005)
    assert res.feasible
    assert res.tols["a"] == pytest.approx(0.005)  # S 小（1/S² 大）份额大者先触顶
    assert res.tols["b"] == pytest.approx(0.004)  # 剩余预算归 b
    assert sum(res.tols.values()) == pytest.approx(0.009, rel=1e-9)
    assert "a" in res.clamped
    # 不可行：预算超不出全钳位上界和（0.9 > 2×0.1）
    res_bad = ta.allocate_budget_t({"a": 1.0, "b": 2.0}, 0.9, tol_max=0.1)
    assert not res_bad.feasible


# ─── 3. B 模式（方差目标下最小成本）与对偶恒等式 ─────────────────────────────


def test_min_cost_dual_identity():
    """对偶恒等式：对 A 模式解的 RSS 跑 B 模式 → 复得同一分配。"""
    res_a = ta.allocate_cost_budget(SENS, COEFFS, C_BUDGET, tol_min=TOL_MIN, tol_max=TOL_MAX)
    res_b = ta.allocate_min_cost(SENS, COEFFS, rss_max=res_a.rss, tol_min=TOL_MIN, tol_max=TOL_MAX)
    assert res_b.feasible
    assert res_b.method == ta.METHOD_MIN_COST
    for k in SENS:
        assert res_b.tols[k] == pytest.approx(res_a.tols[k], rel=1e-6)
    # B 模式约束激活：RSS == 目标
    assert res_b.rss == pytest.approx(res_a.rss, rel=1e-6)


def test_min_cost_infeasible_and_slack():
    res = ta.allocate_min_cost(SENS, COEFFS, rss_max=1e-12, tol_min=1e-3, tol_max=1.0)
    assert not res.feasible
    slack = ta.allocate_min_cost(SENS, COEFFS, rss_max=1e12, tol_min=1e-3, tol_max=1.0)
    assert slack.feasible and all(v == pytest.approx(1.0) for v in slack.tols.values())


# ─── 4. 对照法（greedy / proportional 基线）─────────────────────────────────


def test_greedy_vs_lagrangian():
    lag = ta.allocate_cost_budget(SENS, COEFFS, C_BUDGET, tol_min=1e-6, tol_max=10.0)
    g = ta.allocate_greedy_cost(
        SENS, COEFFS, C_BUDGET, tol_min=1e-6, tol_max=10.0, n_steps=2000
    )
    assert g.feasible and g.method == ta.METHOD_GREEDY
    assert g.total_cost <= C_BUDGET + 1e-9
    assert g.rss >= lag.rss - 1e-12  # 贪心不优于拉格朗日
    assert g.rss <= lag.rss * 1.05  # 离散化 gap 有界


def test_proportional_baseline_vs_lagrangian():
    lag = ta.allocate_cost_budget(SENS, COEFFS, C_BUDGET, tol_min=1e-6, tol_max=10.0)
    pr = ta.allocate_proportional_cost(SENS, COEFFS, C_BUDGET, tol_min=1e-6, tol_max=10.0)
    assert pr.feasible and pr.method == ta.METHOD_PROPORTIONAL
    assert pr.total_cost <= C_BUDGET + 1e-9
    assert len(set(pr.tols.values())) == 1  # 等公差基线本性
    assert pr.rss >= lag.rss  # 基线不优于拉格朗日（round1 判据第二门方向）


# ─── 5. 良率换算 / 数值差分敏感度 / Cpk / WCD ────────────────────────────────


def test_yield_to_output_sigma_identities():
    # 已知分位数：Y = Φ(2) = 0.9772498680518208 → σ = m/2
    sigma = ta.yield_to_output_sigma(2.0, 0.9772498680518208)
    assert sigma == pytest.approx(1.0, rel=1e-12)
    assert ta.yield_to_output_sigma(0.0, 0.5) == 0.0  # 零裕量零容差（逐位）
    with pytest.raises(ValueError):
        ta.yield_to_output_sigma(1.0, 1.0)  # Y 必须开区间
    with pytest.raises(ValueError):
        ta.yield_to_output_sigma(1.0, -0.1)


def test_sensitivities_from_callable_exact():
    # 线性/二次响应中央差分逐位精确
    sens = ta.sensitivities_from_callable(
        lambda d: 3.0 * d["x"] + 2.0 * d["y"], {"x": 1.0, "y": 2.0}
    )
    assert sens["x"] == pytest.approx(3.0, rel=1e-8)
    assert sens["y"] == pytest.approx(2.0, rel=1e-8)
    sens_q = ta.sensitivities_from_callable(
        lambda d: d["u"] ** 2, {"u": 0.5}
    )
    assert sens_q["u"] == pytest.approx(1.0, rel=1e-8)
    # keys 白名单与非法入参
    sens_k = ta.sensitivities_from_callable(
        lambda d: d["x"] + d["y"], {"x": 1.0, "y": 1.0}, keys=("x",)
    )
    assert set(sens_k) == {"x"}
    with pytest.raises(ValueError):
        ta.sensitivities_from_callable("not callable", {"x": 1.0})
    with pytest.raises(ValueError):
        ta.sensitivities_from_callable(lambda d: 1.0, {"x": 1.0}, keys=("z",))


def test_cpk_and_worst_case_identities():
    tols = {"a": 0.015, "b": 0.0075}
    rss = math.sqrt((SENS["a"] * tols["a"]) ** 2 + (SENS["b"] * tols["b"]) ** 2)
    sigma_y = rss / 3.0
    report = ta.cpk_from_tols(SENS, tols, usl=0.05, lsl=-0.05)
    assert report["cpk"] == pytest.approx(0.05 / (3.0 * sigma_y), rel=1e-12)
    one_sided = ta.cpk_from_tols(SENS, tols, usl=0.05)
    assert one_sided["cpk"] == pytest.approx(0.05 / (3.0 * sigma_y), rel=1e-12)
    assert ta.worst_case_of(SENS, tols) == pytest.approx(0.015 + 2.0 * 0.0075, rel=1e-12)
    # Cpk 重算（round1 输出面）：分配表直接出
    res = ta.allocate_cost_budget(SENS, COEFFS, C_BUDGET, tol_min=TOL_MIN, tol_max=TOL_MAX)
    rep2 = ta.cpk_from_tols(SENS, res.tols, usl=10.0)
    assert rep2["sigma_y"] == pytest.approx(res.rss / 3.0, rel=1e-12)


# ─── 6. 边界与守卫 ───────────────────────────────────────────────────────────


def test_zero_sensitivity_excluded():
    sens = {"a": 1.0, "b": 2.0, "c": 0.0}
    coeffs = {"a": 1.0, "b": 1.0, "c": 1.0}
    res = ta.allocate_cost_budget(sens, coeffs, 2.0, tol_min=1e-6, tol_max=2.0)
    assert res.feasible
    assert res.tols["c"] == pytest.approx(2.0)  # 零敏感参数不消耗紧公差
    assert res.tols["a"] < 2.0 and res.tols["b"] < 2.0
    res_t = ta.allocate_budget_t(sens, 0.03)
    assert res_t.tols["c"] == 0.0  # 预算模式：预算让给敏感参数
    assert res_t.rss > 0.0  # 零敏感参数不进 RSS 但不崩


def test_tol_bounds_respected():
    res = ta.allocate_cost_budget(
        SENS, COEFFS, 3.0, cost_power=2.0, tol_min=0.1, tol_max=1.0
    )
    assert res.feasible
    for v in res.tols.values():
        assert 0.1 - 1e-12 <= v <= 1.0 + 1e-12  # 箱约束不被突破
    assert res.total_cost <= 3.0 + 1e-9


def test_to_dict_and_rss_consistency():
    res = ta.allocate_cost_budget(SENS, COEFFS, C_BUDGET, tol_min=TOL_MIN, tol_max=TOL_MAX)
    d = res.to_dict()
    assert d["method"] == ta.METHOD_COST_BUDGET and d["feasible"] is True
    assert set(d["tols"]) == set(SENS)
    # to_dict 里的 rss/worst_case 与 tols 重算一致（JSON 面自洽）
    assert d["rss"] == pytest.approx(ta.rss_of(SENS, res.tols), rel=1e-12)
    assert d["worst_case"] == pytest.approx(ta.worst_case_of(SENS, res.tols), rel=1e-12)
    assert d["costs"]["a"] == pytest.approx(COEFFS["a"] / res.tols["a"], rel=1e-9)


def test_cost_of_and_scalar_guards():
    tols = {"a": 0.5, "b": 0.25}
    costs = ta.cost_of(tols, {"a": 2.0, "b": 1.0})
    assert costs["a"] == pytest.approx(4.0) and costs["b"] == pytest.approx(4.0)
    costs_p2 = ta.cost_of(tols, {"a": 2.0, "b": 1.0}, cost_power=2.0)
    assert costs_p2["a"] == pytest.approx(8.0)
    costs_e = ta.cost_of(tols, {"a": 2.0, "b": 1.0}, cost_model=ta.COST_EXPONENTIAL, exp_scale=0.5)
    assert costs_e["a"] == pytest.approx(2.0 * math.exp(-1.0), rel=1e-12)
    assert ta.cost_of(tols, {"a": 0.0, "b": 1.0})["a"] == 0.0  # 免费参数
    inf_cost = ta.cost_of({"a": 0.0, "b": 0.25}, {"a": 2.0, "b": 1.0})
    assert math.isinf(inf_cost["a"])  # δ=0 → inf（数学如实，不凑 0）
    with pytest.raises(ValueError):
        ta.rss_of(SENS, {"a": 0.1})  # 缺键


# ─── 7. service 薄壳（JSON 信封 ok=False 不抛）───────────────────────────────


def test_tolerance_service_allocate_ok():
    from rfauto.service.tolerance_allocation_service import tolerance_allocate

    out = tolerance_allocate(
        {
            "sensitivities": SENS,
            "cost_coeffs": COEFFS,
            "budget_c": C_BUDGET,
            "compare": True,
            "spec": {"usl": 10.0, "yield_target": 0.9772498680518208, "margin": 2.0},
        }
    )
    assert out["ok"] is True and out["mode"] == "cost_budget"
    alloc = out["allocation"]
    ref = _closed_form_cost_budget(SENS, COEFFS, C_BUDGET)
    for k in SENS:
        assert alloc["tols"][k] == pytest.approx(ref[k], rel=1e-6)
    assert out["comparison"]["rss_gap_greedy"] >= -1e-12
    assert out["comparison"]["rss_gap_proportional"] >= 0.0
    assert out["spec"]["cpk"]["sigma_y"] == pytest.approx(alloc["rss"] / 3.0, rel=1e-12)
    assert out["spec"]["sigma_for_yield"] == pytest.approx(1.0, rel=1e-12)
    # budget_t / min_cost 两模式走通
    out_t = tolerance_allocate(
        {"sensitivities": SENS, "cost_coeffs": COEFFS, "mode": "budget_t", "total_tol_t": 0.03}
    )
    assert out_t["ok"] is True and sum(out_t["allocation"]["tols"].values()) == pytest.approx(0.03)
    out_m = tolerance_allocate(
        {"sensitivities": SENS, "cost_coeffs": COEFFS, "mode": "min_cost", "rss_max": 0.5}
    )
    assert out_m["ok"] is True and out_m["allocation"]["rss"] <= 0.5 + 1e-9


def test_tolerance_service_envelope_errors():
    from rfauto.service.tolerance_allocation_service import tolerance_allocate

    for bad in (
        None,
        {},
        {"sensitivities": {"a": 1.0}},
        {"sensitivities": {"a": True}, "cost_coeffs": {"a": 1.0}},
        {"sensitivities": SENS, "cost_coeffs": {"a": 1.0, "b": 1.0}, "budget_c": 1e-30},
        {"sensitivities": SENS, "cost_coeffs": COEFFS, "budget_c": 3.0, "mode": "magic"},
        {"sensitivities": SENS, "cost_coeffs": COEFFS, "mode": "min_cost"},
        {
            "sensitivities": SENS,
            "cost_coeffs": COEFFS,
            "budget_c": 3.0,
            "cost_model": "exponential",
        },
    ):
        env = tolerance_allocate(bad)
        assert env["ok"] is False and env["errors"], f"应 ok=False: {bad!r}"
