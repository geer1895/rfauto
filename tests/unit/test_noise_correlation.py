"""MT-1 噪声相关矩阵级联锚测试（round17 MT-1 规格，2026-10-02）。

锚口径（#118 裁判纪律：解析锚=独立代数排布/独立裁判路径，不与被测实现
同源）：

- **Friis 退化（ρ=0/None）**：与 core/cascade.cascade_budget（既有 Friis
  内核，只读消费）在两级/三级上对拍 rel 1e-12——匹配级联退化 Friis 是
  round17 规格验收第一条。
- **ρ=±1 两极限闭式**：两级 F = 1+(√f₁±√(f₂/G₁))²（加性噪声相量相干
  合成/相消的独立代数排布，测试内手算）。
- **蒙特卡洛独立裁判**：Cholesky 合成相关样本 u（synthesize_correlated）
  → 经验 F = 1+mean((Σ√(wᵢfᵢ)·uᵢ)²) 回收解析 F_tot（ρ=0.5，N=4e5，
  实测偏差 ~0.07%，门 1%）——合成路径与闭式路径完全独立，#118 族。
- **fet_noise 对拍（双管级联）**：两级 Pospieszalski 四噪声参数
  （50Ω 匹配源 F(Γs=0)）过相关级联管道 → ρ=0 与 Friis 恒等、ρ=+1 与
  极限闭式恒等（round17 验收第二条"双管级联对拍 fet_noise"）。
- **Cholesky**：L·L†=C 逐位回收（单位对角恢复 rel 1e-12）；|ρ|=1 奇异
  极限显式报错（消息带实测 min_eig）；合成样本经验相关矩阵 ≈ C（4e5
  样本，rel 门 2%）。
- **PSD 守卫负例**：逐对 |ρ|≤1 但三对不一致的组合（非 PSD）显式拒绝；
  PSD ⇒ F≥1 解析保证（随机合法 ρ 集合扫描 F_total_linear ≥ 1）。
- **combine_noise_power 极限**：ρ=0→Σv、ρ=+1→(Σ√v)²、ρ=−1→
  (√v₁−√v₂)²=0、纯虚 ρ 实部为零→Σv（相噪相关性语义的极限形态）。

零外部数据捆绑：全部锚=闭式恒等式/固定种子合成，无文件依赖。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.cascade import cascade_budget
from rfauto.core.fet_noise import (
    FetSmallSignal,
    noise_figure_at,
    pospieszalski_noise_params,
)
from rfauto.core.noise_correlation import (
    cholesky_factor,
    combine_noise_power,
    correlation_matrix,
    correlation_min_eigenvalue,
    synthesize_correlated,
)
from rfauto.service.calculator_service import run_calculator

# 名义级表（钉值与 test_cascade 锚同源的典型 LNA 链量级）
STAGES2 = [{"gain_db": 20.0, "nf_db": 2.0}, {"gain_db": 15.0, "nf_db": 3.0}]
STAGES3 = [*STAGES2, {"gain_db": 10.0, "nf_db": 4.5}]
_F1 = 10.0 ** (2.0 / 10.0) - 1.0
_F2 = 10.0 ** (3.0 / 10.0) - 1.0
_F3 = 10.0 ** (4.5 / 10.0) - 1.0
_G1 = 100.0
_G1G2 = 100.0 * 10.0 ** 1.5


def _cascade(stages, rhos=None, name="correlated_cascade_nf"):
    out = run_calculator(name, {"stages": stages, "rhos": [
        {"i": i, "j": j, "rho": v} for (i, j), v in (rhos or {}).items()
    ]} if rhos else {"stages": stages})
    assert out["ok"] is True, out.get("error")
    return out["result"]


def _core(stages, rhos=None):
    from rfauto.core.noise_correlation import cascade_noise_factor
    return cascade_noise_factor(stages, rhos)


# ─── 锚 1：匹配级联退化 Friis（ρ=0 ↔ cascade_budget 对拍）───────────────────


class TestFriisDegeneration:
    def test_two_stage_matches_cascade_budget(self):
        r = _core(STAGES2)
        cb = cascade_budget([dict(s, type="amp") for s in STAGES2], bw_hz=1e6)
        assert r["nf_total_db"] == pytest.approx(cb["nf_total_db"], rel=1e-12)
        # 独立手算（Friis 显式式）
        assert r["f_total_linear"] == pytest.approx(
            1.0 + _F1 + _F2 / _G1, rel=1e-12)
        assert r["nf_total_db"] == pytest.approx(2.0271870327650774, rel=1e-12)

    def test_three_stage_matches_cascade_budget(self):
        r = _core(STAGES3)
        cb = cascade_budget([dict(s, type="amp") for s in STAGES3], bw_hz=1e6)
        assert r["nf_total_db"] == pytest.approx(cb["nf_total_db"], rel=1e-12)
        assert r["f_total_linear"] == pytest.approx(
            1.0 + _F1 + _F2 / _G1 + _F3 / _G1G2, rel=1e-12)

    def test_explicit_rho_zero_equals_none(self):
        r0 = _core(STAGES2)
        rz = _core(STAGES2, {(0, 1): 0.0})
        assert r0["f_total_linear"] == pytest.approx(
            rz["f_total_linear"], rel=1e-15)
        assert rz["cross_terms"] == []

    def test_delta_nf_zero_when_independent(self):
        r = _core(STAGES3)
        assert r["delta_nf_db"] == pytest.approx(0.0, abs=1e-12)
        assert r["nf_friis_db"] == pytest.approx(r["nf_total_db"], abs=1e-12)


# ─── 锚 2：ρ=±1 两极限闭式 ──────────────────────────────────────────────────


class TestFullyCorrelatedLimits:
    def test_rho_plus_one_closed_form(self):
        r = _core(STAGES2, {(0, 1): 1.0})
        assert r["f_total_linear"] == pytest.approx(
            1.0 + (math.sqrt(_F1) + math.sqrt(_F2 / _G1)) ** 2, rel=1e-12)
        assert r["nf_total_db"] == pytest.approx(2.424021921420173, rel=1e-12)
        assert r["delta_nf_db"] > 0.0  # 正相关抬高 NF

    def test_rho_minus_one_closed_form(self):
        r = _core(STAGES2, {(0, 1): -1.0})
        assert r["f_total_linear"] == pytest.approx(
            1.0 + (math.sqrt(_F1) - math.sqrt(_F2 / _G1)) ** 2, rel=1e-12)
        assert r["nf_total_db"] == pytest.approx(1.5904113650911076, rel=1e-12)
        assert r["nf_total_db"] < r["nf_friis_db"]  # 相消低于独立假设

    def test_negative_correlation_never_below_thermal_floor(self):
        # PSD ⇒ F>=1 解析保证：相消极限也不越 1（1 级独立 + 2 级全消）
        r = _core([{"gain_db": 20.0, "nf_db": 2.0},
                   {"gain_db": 15.0, "nf_db": 2.0}], {(0, 1): -1.0})
        f1 = 10.0 ** 0.2 - 1.0
        assert r["f_total_linear"] == pytest.approx(
            1.0 + (math.sqrt(f1) - math.sqrt(f1 / 100.0)) ** 2, rel=1e-12)
        assert r["f_total_linear"] >= 1.0

    def test_complex_rho_re_part_enters(self):
        # ρ=0.5j：实部为 0 → 交叉项为 0，与独立一致；ρ=0.5 → 抬升
        rj = _core(STAGES2, {(0, 1): 0.5j})
        r0 = _core(STAGES2)
        assert rj["f_total_linear"] == pytest.approx(
            r0["f_total_linear"], rel=1e-12)
        rr = _core(STAGES2, {(0, 1): 0.5})
        assert rr["f_total_linear"] > r0["f_total_linear"]
        # [re, im] 注册面形态与 core complex 直调一致
        rj_shell = _cascade(STAGES2, {(0, 1): [0.0, 0.5]})
        assert rj_shell["f_total_linear"] == pytest.approx(
            rj["f_total_linear"], rel=1e-15)


# ─── 锚 3：蒙特卡洛独立裁判（合成样本回收解析 F_tot）────────────────────────


class TestMonteCarloReferee:
    def test_empirical_f_recovers_analytic(self):
        rho = 0.5
        r = _core(STAGES2, {(0, 1): rho})
        c = correlation_matrix(2, {(0, 1): rho})
        u = synthesize_correlated(c, 400_000, seed=20261002)
        a = [math.sqrt(_F1), math.sqrt(_F2 / _G1)]  # w₁=1, w₂=1/G₁
        f_emp = 1.0 + float(np.mean((a[0] * u[0] + a[1] * u[1]) ** 2))
        assert f_emp == pytest.approx(r["f_total_linear"], rel=0.01)

    def test_synthesis_recovers_correlation(self):
        c = correlation_matrix(2, {(0, 1): 0.5})
        u = synthesize_correlated(c, 400_000, seed=7)
        emp = float(np.corrcoef(u)[0, 1])
        assert emp == pytest.approx(0.5, abs=0.01)


# ─── 锚 4：fet_noise 对拍（双管级联，round17 验收第二条）────────────────────


class TestFetNoiseTwoTube:
    def _two_tube(self):
        """两只 Pospieszalski 管 @2GHz、50Ω 匹配源 → Fᵢ（dB）+ 设定级增益。

        级增益为设定值（对拍对象是相关级联/Friis 管道一致性，不是增益
        模型——F 全部来自 fet_noise 真器件四噪声参数）。
        """
        mA = FetSmallSignal(cgs_f=0.5e-12, ri_ohm=1.5, gm_s=0.05, gds_s=0.002)
        mB = FetSmallSignal(cgs_f=0.75e-12, ri_ohm=2.0, gm_s=0.08, gds_s=0.003)
        pA = pospieszalski_noise_params(mA, 2e9, 300.0, 400.0)
        pB = pospieszalski_noise_params(mB, 2e9, 290.0, 500.0)
        nf_a = noise_figure_at(pA, 0j)
        nf_b = noise_figure_at(pB, 0j)
        return [{"gain_db": 18.0, "nf_db": nf_a},
                {"gain_db": 12.0, "nf_db": nf_b}]

    def test_independent_matches_friis_hand_calc(self):
        stages = self._two_tube()
        f_a = 10.0 ** (stages[0]["nf_db"] / 10.0) - 1.0
        f_b = 10.0 ** (stages[1]["nf_db"] / 10.0) - 1.0
        r = _core(stages)
        assert r["f_total_linear"] == pytest.approx(
            1.0 + f_a + f_b / 10.0 ** 1.8, rel=1e-12)
        assert r["nf_total_db"] == pytest.approx(0.11951238391026062,
                                                 rel=1e-9)

    def test_fully_correlated_twin_tube_limit(self):
        stages = self._two_tube()
        f_a = 10.0 ** (stages[0]["nf_db"] / 10.0) - 1.0
        f_b = 10.0 ** (stages[1]["nf_db"] / 10.0) - 1.0
        r = _core(stages, {(0, 1): 1.0})
        assert r["f_total_linear"] == pytest.approx(
            1.0 + (math.sqrt(f_a) + math.sqrt(f_b / 10.0 ** 1.8)) ** 2,
            rel=1e-12)
        assert r["nf_total_db"] == pytest.approx(0.14938143293651068,
                                                 rel=1e-9)


# ─── 锚 5：Cholesky / 相关矩阵守卫 ──────────────────────────────────────────


class TestCholeskyAndGuards:
    def test_cholesky_recovers_matrix(self):
        c = correlation_matrix(3, {(0, 1): 0.3, (0, 2): -0.4, (1, 2): 0.2})
        l_fac = cholesky_factor(c)
        np.testing.assert_allclose(l_fac @ l_fac.conj().T, c,
                                   rtol=1e-12, atol=1e-14)

    def test_singular_limit_rejected_with_min_eig(self):
        c = correlation_matrix(2, {(0, 1): 1.0})  # 极限相关=奇异
        with pytest.raises(ValueError, match="非正定"):
            cholesky_factor(c)

    def test_pairwise_valid_but_non_psd_set_rejected(self):
        with pytest.raises(ValueError, match="半正定"):
            correlation_matrix(3, {(0, 1): 0.9, (0, 2): 0.9, (1, 2): -0.9})

    def test_rho_out_of_range_rejected(self):
        with pytest.raises(ValueError, match="<=1"):
            correlation_matrix(2, {(0, 1): 1.5})

    def test_bad_keys_rejected(self):
        with pytest.raises(ValueError, match="i < j"):
            correlation_matrix(2, {(1, 0): 0.5})
        with pytest.raises(ValueError, match="i < j"):
            correlation_matrix(2, {(0, 0): 0.5})
        with pytest.raises(ValueError, match="i < j"):
            correlation_matrix(2, {(0, 2): 0.5})

    def test_min_eigenvalue_diagnostic(self):
        assert correlation_min_eigenvalue(
            correlation_matrix(2, {(0, 1): 0.5})) == pytest.approx(0.5)

    def test_f_never_below_one_for_random_psd_sets(self):
        # 随机构造合法相关集合（等相关矩阵 PSD 域 ρ≥−1/(n−1)=−0.5，取
        # [−0.45, 0.6] 保证合法）→ F>=1 扫描；越域 ρ（如 −0.52）由守卫拒绝
        rng = np.random.default_rng(42)
        for _ in range(20):
            rho = float(rng.uniform(-0.45, 0.6))
            r = _core(STAGES3, {(0, 1): rho, (1, 2): rho, (0, 2): rho})
            assert r["f_total_linear"] >= 1.0

    def test_psd_guard_catches_out_of_domain_equicorrelation(self):
        # 负例再钉：等相关 ρ=−0.52 越出 n=3 的 PSD 域（ρ≥−0.5）→ 显式拒绝
        with pytest.raises(ValueError, match="半正定"):
            _core(STAGES3, {(0, 1): -0.52, (1, 2): -0.52, (0, 2): -0.52})


# ─── 锚 6：combine_noise_power 两极限 ───────────────────────────────────────


class TestCombineNoisePower:
    def test_limits(self):
        ind = combine_noise_power([1.0, 1.0])
        assert ind["total_variance"] == pytest.approx(2.0)
        coh = combine_noise_power([1.0, 1.0], {(0, 1): 1.0})
        assert coh["total_variance"] == pytest.approx(4.0)  # (1+1)²
        canc = combine_noise_power([1.0, 1.0], {(0, 1): -1.0})
        assert canc["total_variance"] == pytest.approx(0.0)  # (1−1)²
        imag = combine_noise_power([1.0, 1.0], {(0, 1): 0.5j})
        assert imag["total_variance"] == pytest.approx(2.0)

    def test_general_rho_hand_calc(self):
        r = combine_noise_power([4.0, 9.0], {(0, 1): 0.5})
        assert r["total_variance"] == pytest.approx(
            13.0 + 2 * 0.5 * 6.0, rel=1e-14)

    def test_single_source_and_negative_rejected(self):
        assert combine_noise_power([2.5])["total_variance"] == pytest.approx(2.5)
        with pytest.raises(ValueError, match=">=0"):
            combine_noise_power([1.0, -0.5])


# ─── 注册键（correlated_cascade_nf）service 出口往返 ────────────────────────


class TestRegisteredKey:
    def test_roundtrip_ok_and_json_safe(self):
        out = run_calculator("correlated_cascade_nf", {
            "stages": STAGES2,
            "rhos": [{"i": 0, "j": 1, "rho": 0.3}],
        })
        assert out["ok"] is True, out.get("error")
        json.dumps(out, allow_nan=False)
        assert out["result"]["delta_nf_db"] > 0.0

    def test_rhos_optional_defaults_friis(self):
        out = run_calculator("correlated_cascade_nf", {"stages": STAGES2})
        assert out["ok"] is True
        assert out["result"]["nf_total_db"] == pytest.approx(
            2.0271870327650774, rel=1e-12)

    def test_invalid_input_ok_false(self):
        out = run_calculator("correlated_cascade_nf", {
            "stages": STAGES2,
            "rhos": [{"i": 0, "j": 1, "rho": 1.5}]})
        assert out["ok"] is False and out.get("error")
        out2 = run_calculator("correlated_cascade_nf", {
            "stages": STAGES2,
            "rhos": [{"i": 1, "j": 0, "rho": 0.3}]})
        assert out2["ok"] is False and out2.get("error")
        out3 = run_calculator("correlated_cascade_nf", {"stages": []})
        assert out3["ok"] is False and out3.get("error")
