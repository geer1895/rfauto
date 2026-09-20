"""E13 定向单元测试：确定性稀疏符号归纳内核（无网络、无真机、无随机数）。

覆盖验证点：
1. 候选基函数库列名/复杂度代价/数值/域守卫（sqrt/log/倒数）；
2. 合成已知公式 y = 3·x1/x2 + 2·sqrt(x3) 的**精确恢复**（项集合 + 系数 + 误差）；
3. 单变量幂律 f = 5/z 的单步恢复；
4. 常数目标与公式串渲染（符号/空格/零系数省略）；
5. OMP 诊断工具：首选项正确 + 可重复；
6. 最优子集搜索：k=2 命中生成项、训练误差随复杂度单调不增、可重复；
7. 复杂度惩罚有效（噪声下不选多余项）；
8. 留出选择：无 mask 报错；有 mask 时选最简单模型且留出误差为 0；
9. Pareto 前沿单调性 + 被支配点剔除；
10. 谐振谷位提取：最低频 vs 最深、谷深门过滤数值纹波、非法输入报错；
11. 独立闭式裁判：与 core.synthesis.synthesize_patch 反解一致（两条独立代码路径）；
12. 裁判对**HJ 一致数据**的归纳式偏差 <=2%（E13 验收口径的机制自证）；
13. 同输入两次归纳逐字节一致（json.dumps sort_keys 比对）+ 变量字典序无关。

实测（2026-09-12 本机 .venv）：
- 精确恢复 rmse = 2.81e-15（阈值 1e-12）；系数 2.0/3.0 误差 <=5e-15。
- HJ 一致合成数据（L∈[35,45]×W∈[40,60] 网格 55 点）2 项式 max|dev| = 0.098%。
- 裁判与 synthesize_patch 反解相对误差 <=1.4e-4（后者 params 四舍五入到 0.01mm）。
"""

from __future__ import annotations

import json
from itertools import pairwise

import numpy as np
import pytest

from rfauto.core.symbolic_fit import (
    BasisConfig,
    CandidateFormula,
    build_library,
    fit_symbolic,
    format_formula,
    omp_order,
    pareto_front,
    patch_resonance_hj_ghz,
    resonance_dip,
    select_subsets,
)
from rfauto.core.synthesis import synthesize_patch

X1 = np.array([1.3, 2.7, 3.1, 4.6, 5.2, 6.4, 7.1, 8.8])
X2 = np.array([2.2, 3.9, 4.1, 5.7, 6.3, 7.8, 8.2, 9.5])
X3 = np.array([0.5, 1.7, 3.3, 4.9, 6.2, 8.1, 9.4, 11.3])
VARS3 = {"x1": X1, "x2": X2, "x3": X3}
Y_EXACT = 3.0 * X1 / X2 + 2.0 * np.sqrt(X3)

# 确定性"噪声"序列（不用 RNG：跨平台逐位可复现）。
NOISE20 = np.array([0.11, -0.23, 0.37, -0.41, 0.53, -0.67, 0.71, -0.83, 0.97,
                    -1.01, 1.13, -1.27, 1.31, -1.43, 1.53, -1.61, 1.73, -1.81,
                    1.93, -2.03])


def _evaluate(fit, variables):
    """按项名重建基函数列并求值（与被测拟合路径独立的最小复算）。"""
    names, phi, _ = build_library(variables)
    index = [names.index(term) for term in fit.best.terms]
    return phi[:, index] @ np.asarray(fit.best.coefficients)


def _subset_mse(phi, y, subset):
    cols = phi[:, list(subset)]
    coef, *_ = np.linalg.lstsq(cols, y, rcond=None)
    return float(np.mean((y - cols @ coef) ** 2))


def test_build_library_names_costs_and_domain_guards():
    names, phi, costs = build_library({"a": np.arange(1.0, 6.0), "b": np.arange(2.0, 7.0)})
    assert names[0] == "1"
    for expected in ("a", "a^2", "sqrt(a)", "1/a", "log(a)", "a/b", "b/a", "a*b"):
        assert expected in names
    cost_of = dict(zip(names, costs, strict=True))
    assert cost_of["a"] == 1
    assert cost_of["a^2"] == 2
    assert cost_of["sqrt(a)"] == 2
    assert cost_of["a/b"] == 3
    assert cost_of["a*b"] == 3
    a = np.arange(1.0, 6.0)
    b = np.arange(2.0, 7.0)
    np.testing.assert_allclose(phi[:, names.index("a/b")], a / b)
    assert phi.shape == (5, len(names))

    # 域守卫：含负值时 sqrt/log 列确定性跳过，倒数保留。
    guarded_names, _, _ = build_library({"c": np.array([-2.0, -1.0, 3.0, 4.0])})
    assert "sqrt(c)" not in guarded_names
    assert "log(c)" not in guarded_names
    assert "1/c" in guarded_names

    # 配置开关可关闭整族特征。
    only_power, _, _ = build_library({"a": a}, BasisConfig(
        allow_inverse=False, allow_sqrt=False, allow_log=False,
        allow_ratios=False, allow_products=False, allow_constant=False,
    ))
    assert only_power == ["a", "a^2"]


def test_build_library_rejects_invalid_input():
    with pytest.raises(ValueError):
        build_library({})
    with pytest.raises(ValueError):
        build_library({"a": [1.0, 2.0], "b": [1.0]})
    with pytest.raises(ValueError):
        build_library({"a": [1.0, float("nan")]})
    with pytest.raises(ValueError):
        build_library({"a": [1.0, 2.0]}, BasisConfig(max_power=0))
    with pytest.raises(ValueError):
        build_library({"a": [1.0, 2.0]}, BasisConfig(min_abs=0.0))


def test_recover_exact_two_term_formula():
    fit = fit_symbolic(VARS3, Y_EXACT)
    assert set(fit.best.terms) == {"x1/x2", "sqrt(x3)"}
    coef = dict(zip(fit.best.terms, fit.best.coefficients, strict=True))
    assert coef["x1/x2"] == pytest.approx(3.0, abs=1e-9)
    assert coef["sqrt(x3)"] == pytest.approx(2.0, abs=1e-9)
    assert fit.best.rmse_train < 1e-12
    assert fit.best.r2_train == pytest.approx(1.0, abs=1e-12)
    # 选中档必须是 2 项（容差口径不会因数值噪声多选）。
    assert fit.best.n_terms == 2
    assert fit.best.formula() == "y = 2*sqrt(x3) + 3*x1/x2"


def test_recover_single_term_power_law():
    z = np.linspace(1.0, 5.0, 8)
    fit = fit_symbolic({"z": z}, 5.0 / z, max_terms=1)
    assert fit.best.terms == ("1/z",)
    assert fit.best.coefficients[0] == pytest.approx(5.0, rel=1e-12)
    assert fit.best.rmse_train < 1e-12


def test_constant_target_selects_constant_feature():
    fit = fit_symbolic({"a": np.arange(1.0, 7.0)}, np.full(6, 4.25), max_terms=1)
    assert fit.best.terms == ("1",)
    assert fit.best.coefficients[0] == pytest.approx(4.25, rel=1e-12)
    assert fit.best.formula() == "y = 4.25"
    assert fit.best.mse_train < 1e-20


def test_omp_order_first_pick_and_repeatability():
    names, phi, _ = build_library(VARS3)
    target = 3.0 * X1 / X2
    first = omp_order(phi, target, max_terms=2)
    assert first[0] == names.index("x1/x2")
    assert omp_order(phi, target, max_terms=2) == first
    assert len(omp_order(phi, target, max_terms=1)) <= 1
    with pytest.raises(ValueError):
        omp_order(phi, target, max_terms=-1)
    with pytest.raises(ValueError):
        omp_order(phi, target[:-1])


def test_select_subsets_hits_generative_pair_and_is_monotone():
    names, phi, _ = build_library(VARS3)
    subsets = select_subsets(phi, Y_EXACT, max_terms=3, exhaustive_max_terms=2)
    assert len(subsets) == 3
    assert {names[i] for i in subsets[1]} == {"x1/x2", "sqrt(x3)"}
    mses = [_subset_mse(phi, Y_EXACT, subset) for subset in subsets]
    assert mses[0] >= mses[1] > mses[2]
    assert select_subsets(phi, Y_EXACT, max_terms=3, exhaustive_max_terms=2) == subsets
    # 组合数上限会把穷举档压缩到 0，但结果仍确定性且单调。
    capped = select_subsets(phi, Y_EXACT, max_terms=2, exhaustive_max_terms=2, max_combinations=1)
    assert len(capped) <= 2
    with pytest.raises(ValueError):
        select_subsets(phi, Y_EXACT, max_combinations=0)


def test_complexity_penalty_rejects_spurious_terms():
    x = np.linspace(1.0, 4.0, 20)
    noisy = 3.0 * x + NOISE20
    fit = fit_symbolic({"a": x}, noisy, penalty=0.5, select_by="penalty", max_terms=4)
    assert fit.best.n_terms == 1
    assert fit.best.terms == ("a",)
    assert fit.best.coefficients[0] == pytest.approx(3.0, abs=0.05)
    # 更多项的候选确实存在（只是被复杂度惩罚淘汰）。
    assert len(fit.candidates) >= 3
    assert max(c.n_terms for c in fit.candidates) >= 3
    with pytest.raises(ValueError):
        fit_symbolic({"a": x}, noisy, penalty=-0.1, select_by="penalty")


def test_holdout_selection_requires_mask_and_prefers_parsimony():
    x = np.linspace(1.0, 4.0, 20)
    y = 3.0 * x
    with pytest.raises(ValueError):
        fit_symbolic({"a": x}, y, select_by="holdout")
    mask = (np.arange(x.size) % 5) == 0
    fit = fit_symbolic(
        {"a": x, "b": np.cos(3.0 * x)}, y, select_by="holdout", holdout_mask=mask, max_terms=3
    )
    assert fit.best.n_terms == 1
    assert fit.best.mse_holdout == pytest.approx(0.0, abs=1e-20)
    with pytest.raises(ValueError):
        fit_symbolic({"a": x}, y, holdout_mask=np.zeros(x.size, dtype=bool))
    with pytest.raises(ValueError):
        fit_symbolic({"a": x}, y, holdout_mask=np.ones(x.size, dtype=bool))
    with pytest.raises(ValueError):
        fit_symbolic({"a": x}, y, holdout_mask=np.zeros(3, dtype=bool))


def test_pareto_front_monotone_and_dominated_removed():
    x = np.linspace(1.0, 4.0, 20)
    fit = fit_symbolic({"a": x}, 3.0 * x + NOISE20, max_terms=5)
    pareto = list(fit.pareto)
    assert len(pareto) >= 2
    complexities = [c.complexity for c in pareto]
    rmses = [c.rmse_train for c in pareto]
    assert complexities == sorted(complexities)
    assert all(b < a for a, b in pairwise(rmses))

    def cand(complexity, mse):
        return CandidateFormula(
            terms=("a",), coefficients=(1.0,), complexity=complexity,
            mse_train=mse, rmse_train=mse**0.5, r2_train=0.0,
        )

    front = pareto_front([cand(1, 0.5), cand(2, 0.5), cand(3, 0.2), cand(4, 0.4)])
    assert [(c.complexity, c.mse_train) for c in front] == [(1, 0.5), (3, 0.2)]


def test_format_formula_signs_and_rendering():
    assert format_formula(["x1/x2", "sqrt(x3)"], [3.0, -2.0]) == "y = 3*x1/x2 - 2*sqrt(x3)"
    assert format_formula(["1", "L"], [5.0, 1.0]) == "y = 5 + L"
    assert format_formula(["L"], [-1.0]) == "y = -L"
    assert format_formula(["L", "W"], [0.0, 2.0]) == "y = 2*W"
    assert format_formula(["1"], [0.0]) == "y = 0"
    assert format_formula(["1"], [1.0], name="f0") == "f0 = 1"
    with pytest.raises(ValueError):
        format_formula(["L"], [1.0, 2.0])
    with pytest.raises(ValueError):
        format_formula(["L"], [float("nan")])
    with pytest.raises(ValueError):
        format_formula(["L"], [1.0], precision=0)


def test_resonance_dip_lowest_deepest_and_depth_gate():
    freq = np.arange(1.0, 3.0 + 1e-9, 0.005)
    shallow = 1.0 - 0.5 * np.exp(-(((freq - 1.8) / 0.03) ** 2))
    deep = 1.0 - 0.9 * np.exp(-(((freq - 2.4) / 0.03) ** 2))
    # 1.4GHz 附近叠加 ~0.17dB 的数值纹波：谷深门必须把它当噪声过滤掉，
    # 否则 mode="lowest" 会锁到纹波而不是 1.8GHz 的真谷。
    mag = np.minimum(shallow, deep) - 0.02 * np.sin((freq - 1.0) * 60.0) * np.exp(
        -(((freq - 1.4) / 0.05) ** 2)
    )
    lowest = resonance_dip(freq, mag, f_min=1.0, f_max=2.8, min_depth_db=3.0, mode="lowest")
    deepest = resonance_dip(freq, mag, f_min=1.0, f_max=2.8, min_depth_db=3.0, mode="deepest")
    assert lowest is not None and deepest is not None
    assert lowest.freq == pytest.approx(1.8, abs=0.01)
    assert deepest.freq == pytest.approx(2.4, abs=0.01)
    assert lowest.depth_db < -3.0
    assert resonance_dip(freq, mag, f_min=1.0, f_max=2.8, min_depth_db=25.0) is None
    assert resonance_dip(freq, mag, f_min=0.2, f_max=0.9) is None

    with pytest.raises(ValueError):
        resonance_dip(freq[::-1], mag)
    with pytest.raises(ValueError):
        resonance_dip(freq, mag[:-1])
    with pytest.raises(ValueError):
        resonance_dip(freq, -mag)
    with pytest.raises(ValueError):
        resonance_dip(freq, mag, mode="widest")
    with pytest.raises(ValueError):
        resonance_dip(freq[:2], mag[:2])
    with pytest.raises(ValueError):
        resonance_dip(freq, mag, f_min=2.0, f_max=1.0)


def test_closed_form_judge_agrees_with_existing_patch_synthesis():
    # 两条独立代码路径：core/synthesis.synthesize_patch (f0→L,W) 反解 vs
    # core/symbolic_fit.patch_resonance_hj_ghz (L,W→f0)。params 四舍五入到
    # 0.01mm，故用 5e-4 相对容差。
    for f0 in (2.0, 2.4, 3.0):
        result = synthesize_patch(f0_ghz=f0, er=3.66, h_mm=0.508)
        length = result.params["patch_len_mm"]
        width = result.params["patch_w_mm"]
        recovered = patch_resonance_hj_ghz(length, width, 3.66, 0.508)
        assert recovered == pytest.approx(f0, rel=5e-4)

    with pytest.raises(ValueError):
        patch_resonance_hj_ghz(40.0, 45.0, 1.0, 0.508)
    with pytest.raises(ValueError):
        patch_resonance_hj_ghz(-40.0, 45.0, 3.66, 0.508)
    with pytest.raises(ValueError):
        patch_resonance_hj_ghz(40.0, 45.0, 3.66, float("nan"))


def test_closed_form_recovery_within_acceptance_threshold():
    # E13 验收口径的机制自证：数据真的服从 HJ 闭式时，本管线归纳式必须 <=2%。
    length = np.linspace(35.0, 45.0, 11)
    width = np.linspace(40.0, 60.0, 5)
    grid_l, grid_w = np.meshgrid(length, width)
    flat_l = grid_l.ravel()
    flat_w = grid_w.ravel()
    target = np.array(
        [patch_resonance_hj_ghz(a, b, 3.66, 0.508) for a, b in zip(flat_l, flat_w, strict=True)]
    )
    variables = {"L_mm": flat_l, "W_mm": flat_w}
    fit = fit_symbolic(variables, target, max_terms=3)
    deviation = np.abs(_evaluate(fit, variables) - target) / target * 100.0
    assert deviation.max() <= 2.0
    assert fit.best.r2_train > 0.9999


def test_fit_is_byte_identical_and_order_invariant():
    fit_a = fit_symbolic(VARS3, Y_EXACT)
    fit_b = fit_symbolic({"x3": X3, "x1": X1, "x2": X2}, Y_EXACT)
    dump_a = json.dumps(fit_a.to_dict(), sort_keys=True, allow_nan=False)
    dump_b = json.dumps(fit_b.to_dict(), sort_keys=True, allow_nan=False)
    assert dump_a == dump_b
    assert fit_a.feature_names == fit_b.feature_names
    assert fit_a.best.terms == fit_b.best.terms
    np.testing.assert_array_equal(fit_a.best.coefficients, fit_b.best.coefficients)
