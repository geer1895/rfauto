"""NX-10 MIMO 信道容量/分集内核单测（core/mimo_capacity.py，round14 §四 :108）。

裁判 = 外部独立来源/独立数值路径（#118：不是被测实现的自我推导）：
  * 对角正交 2×2（H=diag(2,1)，λ=(4,1)）容量求和恒等：等功率
    C = log₂(1+6·4/2)+log₂(1+6·1/2) = log₂(52)（Telatar 1999 容量式
    + Tse & Viswanath 2005 §5.3 等功率口径，闭式手算回收）；
  * 规格原式独立路径：C=log₂det(I+γHH†)（round14 :108）用 np.linalg
    .slogdet（与特征值求和完全不同的数值路径）；口径恒等式
    equal(snr=S) ≡ logdet(γ=S/Nt)（两档写法同一物理量的换算钉）；
  * 秩亏退化：H=[[1,1],[1,1]] → rank 1、λ=(4,0)、等功率 log₂(7)@snr=3、
    注水全部功率入单模 log₂(13)、N_eff=1；H=0 → 全零容量/秩 0（诚实零）；
  * 注水闭式（Tse & Viswanath 2005 §5.4.3 活性模搜索）：λ=(4,1)、snr=2 →
    μ=1.625、p=(1.375, 0.625)、C=log₂(6.5·1.625)；截模例 λ=(10,0.5)、
    snr=1 → 弱模不入活性集、p=(1.0, 0)、C=log₂(11)；无序输入防御性
    重排（乱序谱注水不错分）；注水 ≥ 等功率（最优性，批量随机谱）+
    Σp=snr 恒等；
  * SISO 规格式：H=[[1]] → C=log₂(1+snr)（单流下两档与原式三数合一）；
  * i.i.d. Rayleigh Monte Carlo 均值 vs 解析（SISO 遍历容量经典结果）：
      E[log₂(1+γX)] = log₂(e)·e^{1/γ}·E₁(1/γ)，X~Exp(1)
    （分部积分+代换 t=x+1/γ；E₁=指数积分，测试以 scipy.special.exp1
    独立求值；出处 Tse & Viswanath 2005 §5.4.5 / Goldsmith 2005 Ch.5）。
    固定种子 n=2×10⁵，γ∈{1,10} 双点，rel 1%（MC 标准误 ~0.3% 带内）；
  * 负例：锯齿/空/非矩形矩阵、坏单元类型、非有限值、snr≤0、未知
    allocation、n_tx<1 显式拒绝；[re,im] 复数对输入与实矩阵同容。

确定性：无网络、无真机、无文件 IO；MC 用固定种子 numpy Generator
（20261002 字面钉死），重复运行逐位一致。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from scipy.special import exp1

from rfauto.core.mimo_capacity import (
    capacity_from_eigenvalues,
    effective_diversity_order,
    eigenvalues_hh,
    mimo_capacity,
    mimo_capacity_report,
    waterfilling_powers,
)

# ------------------------------------------------------------- 正交 2×2 锚


H_DIAG = [[2, 0], [0, 1]]
H_ONES = [[1, 1], [1, 1]]


class TestOrthogonal2x2:
    """对角正交信道容量求和恒等（规格公式 + 独立 slogdet 路径）。"""

    def test_equal_power_sum_identity_log2_52(self) -> None:
        # λ=(4,1)：C = log₂(1+12)+log₂(1+3) = log₂(52)（手算闭式）
        c = mimo_capacity(H_DIAG, 6.0, allocation="equal")
        assert c == pytest.approx(math.log2(52.0), rel=1e-12)

    def test_spec_logdet_independent_path(self) -> None:
        # 规格原式 log₂det(I+snr·HH†)（slogdet 路径）：λ=(4,1)、snr=6 →
        # log₂(25·7) = log₂(175)
        rep = mimo_capacity_report(H_DIAG, 6.0)
        assert rep["capacity_logdet_spec_form_bps_hz"] == pytest.approx(
            math.log2(175.0), rel=1e-12)

    def test_convention_identity_equal_vs_logdet(self) -> None:
        # 口径恒等：equal(总 snr=S) ≡ logdet(γ=S/Nt)——同一物理量两写法
        c_equal = mimo_capacity_report(H_DIAG, 6.0)["capacity_equal_bps_hz"]
        c_logdet = mimo_capacity_report(
            H_DIAG, 6.0 / 2.0)["capacity_logdet_spec_form_bps_hz"]
        assert c_equal == pytest.approx(c_logdet, rel=1e-12)

    def test_eigenvalues_and_singular_values_consistent(self) -> None:
        # 独立路径互证：σᵢ² ≡ λᵢ（SVD vs eigvalsh）
        rep = mimo_capacity_report(H_DIAG, 6.0)
        sv = np.asarray(rep["singular_values"])
        lam = np.asarray(rep["eigenvalues_hh"])
        assert np.allclose(sv**2, lam, rtol=1e-12)
        assert rep["rank"] == 2 and rep["n_tx"] == 2 and rep["n_rx"] == 2
        assert rep["effective_diversity_order"] == pytest.approx(
            25.0 / 17.0, rel=1e-12)


# ------------------------------------------------------------- 秩亏退化


class TestRankDeficient:
    """秩亏退化：单模承载 + 有效分集阶塌缩 + H=0 诚实零。"""

    def test_rank_one_capacities(self) -> None:
        rep = mimo_capacity_report(H_ONES, 3.0)
        assert rep["rank"] == 1
        assert rep["eigenvalues_hh"] == pytest.approx([4.0, 0.0])
        # 等功率：log₂(1+3·4/2) = log₂(7)
        assert rep["capacity_equal_bps_hz"] == pytest.approx(
            math.log2(7.0), rel=1e-12)
        # 注水：全部功率入单模 → log₂(1+3·4) = log₂(13) > 等功率
        assert rep["capacity_waterfilling_bps_hz"] == pytest.approx(
            math.log2(13.0), rel=1e-12)
        assert rep["waterfilling_gain_bps_hz"] > 0.0
        # 有效分集阶：(4)²/(4²+0²) = 1.0（秩 1 塌缩）
        assert rep["effective_diversity_order"] == pytest.approx(1.0)

    def test_zero_matrix_honest_zero(self) -> None:
        rep = mimo_capacity_report([[0, 0], [0, 0]], 3.0)
        assert rep["rank"] == 0
        assert rep["capacity_equal_bps_hz"] == 0.0
        assert rep["capacity_waterfilling_bps_hz"] == 0.0
        assert rep["capacity_logdet_spec_form_bps_hz"] == 0.0
        assert rep["effective_diversity_order"] == 0.0
        assert rep["water_level"] is None
        assert rep["power_waterfilling"] == [0.0, 0.0]

    def test_effective_diversity_order_bounds(self) -> None:
        # 满秩均匀谱 → 模数；秩 1 → 1；一般谱落在 [1, r]
        assert effective_diversity_order([3.0, 3.0]) == pytest.approx(2.0)
        assert effective_diversity_order([1.0]) == pytest.approx(1.0)
        neff = effective_diversity_order([4.0, 1.0])
        assert 1.0 < neff < 2.0


# ------------------------------------------------------------- 注水闭式


class TestWaterfilling:
    """注水活性模搜索：闭式回收 + 截模 + 最优性/守恒 + 防御重排。"""

    def test_two_mode_closed_form(self) -> None:
        # λ=(4,1)、snr=2：μ=(2+0.25+1)/2=1.625 → p=(1.375, 0.625)
        lam = np.array([4.0, 1.0])
        p = waterfilling_powers(lam, 2.0)
        assert p == pytest.approx([1.375, 0.625], rel=1e-12)
        c = capacity_from_eigenvalues(lam, 2.0, 2, allocation="waterfilling")
        assert c == pytest.approx(math.log2(1.625 * 4.0 * 1.625 * 1.0), rel=1e-12)

    def test_weak_mode_dropped(self) -> None:
        # λ=(10,0.5)、snr=1：双模 μ=1.55 < 1/0.5=2 → 弱模截除；
        # 单模 μ=1.1 → p=(1.0, 0)、C=log₂(1+10·1.0)=log₂(11)
        lam = np.array([10.0, 0.5])
        p = waterfilling_powers(lam, 1.0)
        assert p == pytest.approx([1.0, 0.0], rel=1e-12)
        c = capacity_from_eigenvalues(lam, 1.0, 2, allocation="waterfilling")
        assert c == pytest.approx(math.log2(11.0), rel=1e-12)

    def test_unsorted_input_defensive_resort(self) -> None:
        # 乱序谱不错分（防御性降序重排；输出与输入列对齐）
        p = waterfilling_powers(np.array([0.5, 10.0]), 1.0)
        assert p == pytest.approx([0.0, 1.0], rel=1e-12)

    def test_optimality_and_power_conservation_random(self) -> None:
        # 注水 ≥ 等功率（最优性）+ Σp=snr（守恒）+ p≥0——批量随机谱
        rng = np.random.default_rng(20261002)
        for _ in range(10):
            h = (rng.standard_normal((4, 4))
                 + 1j * rng.standard_normal((4, 4)))
            lam = eigenvalues_hh(h)
            snr = float(rng.uniform(0.1, 20.0))
            c_eq = capacity_from_eigenvalues(lam, snr, 4, allocation="equal")
            c_wf = capacity_from_eigenvalues(
                lam, snr, 4, allocation="waterfilling")
            assert c_wf >= c_eq - 1e-12
            p = waterfilling_powers(lam, snr)
            assert float(p.sum()) == pytest.approx(snr, rel=1e-9, abs=1e-12)
            assert np.all(p >= 0.0)

    def test_batched_shape(self) -> None:
        rng = np.random.default_rng(11)
        lam = np.sort(rng.uniform(0.1, 5.0, (5, 4)), axis=1)[:, ::-1]
        p = waterfilling_powers(lam, 2.0)
        assert p.shape == (5, 4)
        assert np.allclose(p.sum(axis=1), 2.0, rtol=1e-9)


# ------------------------------------------------------------- SISO/规格式


class TestSiso:
    """单流退化为规格原式的直接形式。"""

    def test_siso_log2_one_plus_snr(self) -> None:
        assert mimo_capacity([[1]], 7.0) == pytest.approx(3.0, rel=1e-12)
        rep = mimo_capacity_report([[1]], 7.0)
        # 单流：等功率=注水=规格原式（三数合一）
        assert rep["capacity_equal_bps_hz"] == pytest.approx(
            rep["capacity_waterfilling_bps_hz"], rel=1e-12)
        assert rep["capacity_equal_bps_hz"] == pytest.approx(
            rep["capacity_logdet_spec_form_bps_hz"], rel=1e-12)
        assert rep["singular_values"] == pytest.approx([1.0])

    def test_complex_pairs_input(self) -> None:
        # [re, im] 对输入：H=[[j,0],[0,−j]] → HH†=I → λ=(1,1)
        h_pairs = [[[0, 1], 0], [0, [0, -1]]]
        rep = mimo_capacity_report(h_pairs, 2.0)
        assert rep["rank"] == 2
        assert rep["capacity_equal_bps_hz"] == pytest.approx(2.0, rel=1e-12)


# ------------------------------------------- i.i.d. Rayleigh MC vs 解析


class TestMonteCarloIidRayleigh:
    """SISO i.i.d. Rayleigh 遍历容量：MC 均值 vs e^{1/γ}E₁(1/γ)·log₂e。

    公式出处（docstring 承诺）：E[ln(1+γX)] = e^{1/γ}E₁(1/γ)（X~Exp(1)；
    分部积分+代换 t=x+1/γ 的经典结果）——即 SISO Rayleigh 遍历容量
    （Tse & Viswanath 2005 §5.4.5；Goldsmith, Wireless Communications,
    2005 Ch.5）。E₁ 由 scipy.special.exp1 独立求值（被测实现零 scipy）。
    """

    N_SAMPLES = 200_000
    SEED = 20261002

    @pytest.mark.parametrize("gamma", [1.0, 10.0])
    def test_mc_mean_matches_closed_form(self, gamma: float) -> None:
        rng = np.random.default_rng(self.SEED)
        a = rng.standard_normal(self.N_SAMPLES)
        b = rng.standard_normal(self.N_SAMPLES)
        # H=(a+jb)/√2 → |H|² = (a²+b²)/2 ~ Exp(1)（标准 Rayleigh 谱）
        lam = ((a * a + b * b) / 2.0).reshape(-1, 1)
        c_mc = capacity_from_eigenvalues(lam, gamma, 1)
        mean_mc = float(np.mean(c_mc))
        analytic = math.log2(math.e) * math.exp(1.0 / gamma) * float(
            exp1(1.0 / gamma))
        # MC 标准误 ~0.2–0.3%（std/mean/√n 实测）→ rel 1% ≈ 3–4σ 带内
        assert mean_mc == pytest.approx(analytic, rel=1e-2)

    def test_mc_deterministic_rerun(self) -> None:
        rng = np.random.default_rng(self.SEED)
        lam = ((rng.standard_normal(1000) ** 2
                + rng.standard_normal(1000) ** 2) / 2.0).reshape(-1, 1)
        first = float(np.mean(capacity_from_eigenvalues(lam, 5.0, 1)))
        rng2 = np.random.default_rng(self.SEED)
        lam2 = ((rng2.standard_normal(1000) ** 2
                 + rng2.standard_normal(1000) ** 2) / 2.0).reshape(-1, 1)
        second = float(np.mean(capacity_from_eigenvalues(lam2, 5.0, 1)))
        assert first == second  # 固定种子逐位一致


# ------------------------------------------------------------- 报告合同/负例


class TestReportContractAndNegative:
    """JSON 安全 + 确定性 + 非法输入显式拒绝。"""

    def test_report_json_safe_and_deterministic(self) -> None:
        rep1 = mimo_capacity_report([[1, 0.3], [0.3, 1]], 8.0)
        text1 = json.dumps(rep1, allow_nan=False, sort_keys=True)
        rep2 = mimo_capacity_report([[1, 0.3], [0.3, 1]], 8.0)
        text2 = json.dumps(rep2, allow_nan=False, sort_keys=True)
        assert text1 == text2

    @pytest.mark.parametrize(
        "h, snr",
        [
            ([[1, 0], [0]], 10.0),  # 锯齿行（非矩形）
            ([], 10.0),  # 空矩阵
            ([[]], 10.0),  # 空行
            ([["x", 0], [0, 1]], 10.0),  # 坏单元类型
            ([[1, float("nan")], [0, 1]], 10.0),  # 非有限单元
            ([[1, 0, 5], [0, 1, 5]], 10.0),  # 合法但 2×3（应正常，见下）
        ],
    )
    def test_matrix_validation(self, h: list, snr: float) -> None:
        if h == [[1, 0, 5], [0, 1, 5]]:  # 非方阵合法（Nr≠Nt 可容）
            rep = mimo_capacity_report(h, snr)
            assert rep["n_tx"] == 3 and rep["n_rx"] == 2
        else:
            with pytest.raises(ValueError):
                mimo_capacity_report(h, snr)

    @pytest.mark.parametrize("snr", [0.0, -1.0, float("inf"), float("nan")])
    def test_snr_validation(self, snr: float) -> None:
        with pytest.raises(ValueError):
            mimo_capacity_report([[1, 0], [0, 1]], snr)

    def test_bad_allocation_and_ntx_rejected(self) -> None:
        lam = np.array([2.0, 1.0])
        with pytest.raises(ValueError, match="allocation"):
            capacity_from_eigenvalues(lam, 5.0, 2, allocation="bogus")
        with pytest.raises(ValueError, match="n_tx"):
            capacity_from_eigenvalues(lam, 5.0, 0)
