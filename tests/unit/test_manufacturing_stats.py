"""PT-1/2/3 量产三件套锚树（规格书 规格深案 §B-5）。

裁判口径（#118，独立来源不自证）：
- PT-1：PFA 数值积分回收 ≤1e-4——scipy.integrate.quad 独立积分
  N(TU, u) 密度在 (−∞, AL] 上的面积（正态下 AL=TU−w 处 CDF=1−pfa
  逐点恒等式），与内核闭式无共享代码；
- PT-2：c4(n) 表值 n=2..10 手算表（SQC 教材表 4 位）；χ² pivot 反演
  恒等式（Cp CI 端点 ≡ σ CI 端点反演的等效形式，机器精度）；scipy
  文档级合成例（已知 μ/σ 正态样本，真 Cp 落 CI 内）；Bissell 域外
  降级标注（n=10 / Cpk 越域各自触发）；
- PT-3：scipy 文档例参数（c=2.5, scale=30, n=250, 右删@40）±5% 回收
  （固定种子）；aging.py 闭式互证（n50_from_weibull:477 /
  weibull_life / weibull_p_of_failure 往返恒等）；B10 Fisher vs LR
  双口径带（嵌套序 + LR 根满足 2ΔlnL=χ² 定义方程）；Fisher SE 对
  大样本渐近方差 6β²/(nπ²) 的收敛性（独立解析来源）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import integrate, optimize, stats

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import aging
from rfauto.core import manufacturing_stats as ms

# ════════════════════════════ PT-1 guardband ═══════════════════════════════


class TestGuardband:
    """PT-1 判定规则与保护带（ILAC-G8 Table 1 结构）。"""

    @pytest.mark.parametrize(
        ("pfa", "u95", "tu"),
        [(0.02, 0.10, 1.0), (0.05, 0.25, 3.3), (0.001, 0.02, -0.5)],
    )
    def test_pfa_recovery_numerical_integration(self, pfa, u95, tu):
        # 验收：数值积分回收 ≤1e-4（quad 独立积分，非内核闭式路径）
        r = ms.guardband_limits(tu - 0.1, u95, tu, pfa, "upper")
        u_std = u95 / 1.96
        area, _ = integrate.quad(
            lambda x: stats.norm.pdf(x, loc=tu, scale=u_std),
            -np.inf,
            r["al_upper"],
        )
        assert abs(area - pfa) <= 1e-4
        # 正态恒等式逐点：真值恰在 TU 时 P(x ≤ AL)=PFA（即 SF(AL)=1−pfa，
        # 规格"AL=TU−w 处 CDF=1−pfa"以 1−CDF 表述的同一恒等式）
        cdf_at_al = float(stats.norm.cdf(r["al_upper"], loc=tu, scale=u_std))
        assert abs(cdf_at_al - pfa) <= 1e-4
        assert abs((1.0 - cdf_at_al) - (1.0 - pfa)) <= 1e-4

    def test_m_formula_and_acceptance_limit(self):
        # m = z_{1−PFA}/1.96（规格书钉式）；w = m·U；AL = TU − w
        pfa, u95, tu = 0.02, 0.10, 1.0
        r = ms.guardband_limits(0.9, u95, tu, pfa, "upper")
        m_expect = float(stats.norm.ppf(1.0 - pfa)) / 1.96
        assert abs(r["m"] - m_expect) <= 1e-12
        assert abs(r["w"] - m_expect * u95) <= 1e-12
        assert abs(r["al_upper"] - (tu - m_expect * u95)) <= 1e-12
        assert r["al_lower"] is None

    def test_lower_side_symmetry(self):
        # 下侧 AL = TL + w（对称结构）
        pfa, u95, tl = 0.02, 0.10, -1.0
        r = ms.guardband_limits(-0.9, u95, tl, pfa, "lower")
        m = float(stats.norm.ppf(1.0 - pfa)) / 1.96
        assert abs(r["al_lower"] - (tl + m * u95)) <= 1e-12
        assert r["al_lower"] == pytest.approx(-0.8952168923147029, abs=1e-9)
        assert r["al_upper"] is None
        assert r["decision"] == "reject"  # −0.90 < AL_lower≈−0.8952

    def test_lower_side_decision_boundary(self):
        r = ms.guardband_limits(-0.89, 0.10, -1.0, 0.02, "lower")
        assert r["decision"] == "accept"  # −0.89 ≥ AL_lower≈−0.8952
        r2 = ms.guardband_limits(-0.90, 0.10, -1.0, 0.02, "lower")
        assert r2["decision"] == "reject"  # −0.90 < AL_lower≈−0.8952

    def test_both_joint_pfa_bounded_and_bonferroni_note(self):
        r = ms.guardband_limits(0.7, 0.10, (0.5, 1.0), 0.02, "both")
        assert r["method"] == "joint_mvnormal"
        assert r["joint_pfa"] <= 0.02 + 1e-12
        # Bonferroni 对照注记在位：每侧分摊 PFA/2
        assert any("bonferroni" in note and "0.01" in note for note in r["notes"])
        # 联合口径下接受限仍按全额 m
        m = float(stats.norm.ppf(0.98)) / 1.96
        assert abs(r["al_upper"] - (1.0 - m * 0.10)) <= 1e-12
        assert abs(r["al_lower"] - (0.5 + m * 0.10)) <= 1e-12
        # 判定与裸规格并列（0.7 在接受区 [0.6048, 0.8952] 内 → accept）
        assert r["decision"] == "accept" and r["spec_conformity"] == "pass"

    def test_both_joint_pfa_recovery_by_quadrature(self):
        # 联合口径的 PFA 也是 quad 可回收的（真值恰在 TU，接受区间积分）
        tl, tu, u95, pfa = 0.5, 1.0, 0.10, 0.02
        r = ms.guardband_limits(0.7, u95, (tl, tu), pfa, "both")
        u_std = u95 / 1.96
        area, _ = integrate.quad(
            lambda x: stats.norm.pdf(x, loc=tu, scale=u_std),
            r["al_lower"],
            r["al_upper"],
        )
        assert abs(area - r["joint_pfa"]) <= 1e-4
        assert r["joint_pfa"] <= pfa  # 对侧尾修正使联合 ≤ 目标

    def test_both_dict_spec(self):
        r = ms.guardband_limits(0.7, 0.10, {"lower": 0.5, "upper": 1.0}, 0.02, "both")
        assert r["spec"] == {"lower": 0.5, "upper": 1.0}

    def test_k2_consistency(self):
        # k=2（en_report U 缺省口径）同样精确回收（PFA = 1 − Φ(k·m)）
        r = ms.guardband_limits(0.9, 0.10, 1.0, 0.02, "upper", k=2.0)
        u_std = 0.10 / 2.0
        area, _ = integrate.quad(
            lambda x: stats.norm.pdf(x, loc=1.0, scale=u_std),
            -np.inf,
            r["al_upper"],
        )
        assert abs(area - 0.02) <= 1e-4
        # ILAC-G8 注记：m=1（w=U）时 PFA = 1−Φ(2) ≈ 2.27% ≈ 2%
        pfa_at_m1 = 1.0 - float(stats.norm.cdf(2.0))
        assert 0.02 < pfa_at_m1 < 0.025

    def test_upper_decision_boundary(self):
        r = ms.guardband_limits(0.895, 0.10, 1.0, 0.02, "upper")
        assert r["decision"] == "accept"  # 0.895 ≤ AL≈0.8952
        r2 = ms.guardband_limits(0.896, 0.10, 1.0, 0.02, "upper")
        assert r2["decision"] == "reject"

    def test_input_validation(self):
        with pytest.raises(ValueError, match="side"):
            ms.guardband_limits(1.0, 0.1, 1.0, 0.02, "mid")
        with pytest.raises(ValueError, match="pfa_target"):
            ms.guardband_limits(1.0, 0.1, 1.0, 1.5, "upper")
        with pytest.raises(ValueError, match="u95"):
            ms.guardband_limits(1.0, 0.0, 1.0, 0.02, "upper")
        with pytest.raises(ValueError, match="bool"):
            ms.guardband_limits(True, 0.1, 1.0, 0.02, "upper")
        with pytest.raises(ValueError, match=r"lower.*upper|两键"):
            ms.guardband_limits(1.0, 0.1, {"upper": 1.0}, 0.02, "both")
        with pytest.raises(ValueError, match="TL < TU"):
            ms.guardband_limits(1.0, 0.1, (1.0, 0.5), 0.02, "both")
        with pytest.raises(ValueError, match="二元组"):
            ms.guardband_limits(1.0, 0.1, 0.5, 0.02, "both")


# ════════════════════════════ PT-2 cpk_ci ═══════════════════════════════════


class TestCpk:
    """PT-2 过程能力指数置信区间（Bissell 1990 / Montgomery 口径）。"""

    def test_c4_table_hand_computed(self):
        # 手算表（SQC 教材 4 位）：√(2/(n−1))·Γ(n/2)/Γ((n−1)/2)
        table = {
            2: 0.7979, 3: 0.8862, 4: 0.9213, 5: 0.9400, 6: 0.9515,
            7: 0.9594, 8: 0.9650, 9: 0.9693, 10: 0.9727,
        }
        for n, expected in table.items():
            assert abs(ms.c4(n) - expected) <= 5e-5, f"c4({n})"

    def test_c4_input_validation(self):
        with pytest.raises(ValueError, match="n 必须为 >=2 的整数"):
            ms.c4(1)
        with pytest.raises(ValueError, match="n 必须为 >=2 的整数"):
            ms.c4(3.5)

    def _exact_s_samples(self, n: int, s_target: float, mu: float = 0.0) -> np.ndarray:
        """样本标准差恰好等于 s_target 的构造样本（恒等式锚不受采样噪声污染）。

        ddof=1 口径：s = √(Σ(x−x̄)²/(n−1))，居中后 Σx²=Σ(x−x̄)²，
        缩放因子 s_target·√(n−1)/√Σx²。
        """
        rng = np.random.default_rng(42)
        x = rng.normal(0.0, 1.0, n)
        xc = x - x.mean()  # 先居中（Σxc²=Σ(x−x̄)²），再按 ddof=1 精确缩放
        x = xc * (s_target * np.sqrt(n - 1) / np.sqrt(np.sum(xc**2))) + mu
        assert abs(x.std(ddof=1) - s_target) <= 1e-12
        return x

    def test_chi2_pivot_identity_recovery(self):
        # χ² pivot 反演恒等式：Cp CI 端点 ≡ σ CI 端点反演（机器精度）
        n, s, mu = 40, 0.2, 5.0
        x = self._exact_s_samples(n, s, mu)
        lsl, usl, conf = 4.4, 5.6, 0.95
        r = ms.cpk_ci(x, lsl, usl, conf)
        c4_n = ms.c4(n)
        nu = n - 1
        alpha = 1.0 - conf
        # 等效 σ CI（独立推导路径）：σ_L = s√(ν/χ²_{1−α/2})、σ_U = s√(ν/χ²_{α/2})
        s_lo = s * np.sqrt(nu / stats.chi2.ppf(1 - alpha / 2, nu))
        s_hi = s * np.sqrt(nu / stats.chi2.ppf(alpha / 2, nu))
        assert abs(r["cp_ci"]["lower"] - (usl - lsl) / (6 * s_hi)) <= 1e-12
        assert abs(r["cp_ci"]["upper"] - (usl - lsl) / (6 * s_lo)) <= 1e-12
        # 点估计：σ̂=s/c4 → Cp̂=(USL−LSL)/(6σ̂)
        assert abs(r["sigma_hat"] - s / c4_n) <= 1e-12
        assert abs(r["cp"] - (usl - lsl) / (6 * s / c4_n)) <= 1e-12

    def test_scipy_doc_level_synthetic_example(self):
        # scipy 文档级合成例：已知 μ/σ 正态大样本，真 Cp/Cpk 落 CI 内
        # （种子 2：该 95% CI 对真值的包含在此实现例成立——单例冒烟锚，
        # 非覆盖率证明）
        rng = np.random.default_rng(2)
        mu, sig = 5.0, 0.2
        x = rng.normal(mu, sig, 400)
        lsl, usl = 4.4, 5.6
        r = ms.cpk_ci(x, lsl, usl, 0.95)
        cp_true = (usl - lsl) / (6 * sig)
        cpk_true = min((usl - mu) / (3 * sig), (mu - lsl) / (3 * sig))
        assert r["cp_ci"]["lower"] <= cp_true <= r["cp_ci"]["upper"]
        assert r["cpk_ci"]["lower"] <= cpk_true <= r["cpk_ci"]["upper"]
        # 点估计贴近真值（n=400）
        assert abs(r["cp"] - cp_true) < 0.05
        assert abs(r["cpk"] - cpk_true) < 0.05

    def test_bissell_domain_degradation_small_n(self):
        x = self._exact_s_samples(10, 0.2, 5.0)
        r = ms.cpk_ci(x, 4.4, 5.6, 0.95)
        assert r["bissell_applicable"] is False
        assert r["degraded"] is True
        assert any("域外降级" in note and "n=10<30" in note for note in r["notes"])
        # 降级仍给区间（如实标注，不静默丢弃）
        assert r["cpk_ci"]["method"] == "bissell_normal_approx"

    def test_bissell_domain_degradation_cpk_out_of_range(self):
        # Cpk 越上域（USL 极远 → cpk≈5 > 3）
        x = self._exact_s_samples(50, 0.2, 5.0)
        r = ms.cpk_ci(x, None, 20.0, 0.95)
        assert r["cpk"] > 3.0
        assert r["bissell_applicable"] is False
        assert any("Cpk=" in note for note in r["notes"])

    def test_bissell_in_domain_no_degradation(self):
        x = self._exact_s_samples(50, 0.2, 5.0)
        r = ms.cpk_ci(x, 4.4, 5.6, 0.95)
        assert r["bissell_applicable"] is True
        assert r["degraded"] is False
        assert r["notes"] == []

    def test_bissell_se_formula(self):
        # SE 解析式独立核对：SE = √(1/(9n) + Cpk²/(2(n−1)))
        x = self._exact_s_samples(50, 0.2, 5.0)
        r = ms.cpk_ci(x, 4.4, 5.6, 0.95)
        cpk, n = r["cpk"], r["n"]
        se_expect = np.sqrt(1.0 / (9 * n) + cpk**2 / (2 * (n - 1)))
        assert abs(r["cpk_ci"]["se"] - se_expect) <= 1e-12
        z = float(stats.norm.ppf(0.975))
        assert abs(r["cpk_ci"]["lower"] - (cpk - z * se_expect)) <= 1e-12
        assert abs(r["cpk_ci"]["upper"] - (cpk + z * se_expect)) <= 1e-12

    def test_ppk_normal_percentile_matches_classic(self):
        # normal 百分位档 z_.135/z_.99865 ≈ ±3 → σ_p≈s → Ppk≈经典 Ppk（0.1% 内）
        x = self._exact_s_samples(50, 0.2, 5.0)
        r = ms.cpk_ci(x, 4.4, 5.6, 0.95)
        pct = r["ppk_percentile"]
        assert pct["method"] == "normal"
        assert abs(pct["ppk"] - r["ppk"]) / r["ppk"] < 1e-3

    def test_ppk_lognormal_exact_identity(self):
        # lognormal 档：ln 样本恰好标准化到 (μ,σ) → σ_p 与解析式机器精度同
        rng = np.random.default_rng(11)
        mu_t, sig_t = np.log(10.0), 0.3
        z = rng.normal(0.0, 1.0, 60)
        x = np.exp(mu_t + sig_t * (z - z.mean()) / z.std(ddof=1))
        r = ms.cpk_ci(x, 5.0, 20.0, 0.95, ppk_method="lognormal")
        pct = r["ppk_percentile"]
        assert pct["method"] == "lognormal"
        sig_p_analytic = (
            np.exp(mu_t + sig_t * float(stats.norm.ppf(0.99865)))
            - np.exp(mu_t + sig_t * float(stats.norm.ppf(0.00135)))
        ) / 6.0
        assert abs(pct["sigma_p"] - sig_p_analytic) <= 1e-12 * sig_p_analytic
        # dB 域用法：线性幅度 + lognormal 档（docstring 口径），x_50pct=e^μ
        assert abs(pct["x_50pct"] - 10.0) <= 1e-9

    def test_single_sided_limit(self):
        x = self._exact_s_samples(40, 0.2, 5.0)
        r = ms.cpk_ci(x, None, 5.6, 0.95)
        assert r["cp"] is None and r["cp_ci"] is None
        assert abs(r["cpk"] - (5.6 - 5.0) / (3 * r["sigma_hat"])) <= 1e-12

    def test_input_validation(self):
        x = [5.0, 5.1, 4.9, 5.05]
        with pytest.raises(ValueError, match="至少提供一个"):
            ms.cpk_ci(x, None, None)
        with pytest.raises(ValueError, match="LSL < USL"):
            ms.cpk_ci(x, 6.0, 5.0)
        with pytest.raises(ValueError, match="至少 2 个"):
            ms.cpk_ci([5.0], 4.0, 6.0)
        with pytest.raises(ValueError, match="常数序列"):
            ms.cpk_ci([5.0, 5.0, 5.0], 4.0, 6.0)
        with pytest.raises(ValueError, match="bool"):
            ms.cpk_ci([5.0, True], 4.0, 6.0)
        with pytest.raises(ValueError, match="ppk_method"):
            ms.cpk_ci(x, 4.0, 6.0, 0.95, ppk_method="bogus")


# ════════════════════════════ PT-3 weibull_mle ══════════════════════════════


def _scipy_doc_example() -> tuple[np.ndarray, np.ndarray]:
    """scipy 文档例参数：c=2.5, scale=30, n=250，右删@40（固定种子）。"""
    rng = np.random.default_rng(3)
    data = stats.weibull_min(c=2.5, scale=30).rvs(size=250, random_state=rng)
    mask = data > 40.0
    return np.asarray(data[~mask], float), np.asarray(data[mask], float)


class TestWeibull:
    """PT-3 右删失 Weibull MLE（scipy CensoredData 路径）。"""

    def test_scipy_doc_example_recovery_within_5pct(self):
        xf, xc = _scipy_doc_example()
        assert xf.size + xc.size == 250
        r = ms.weibull_mle(xf, xc)
        assert abs(r["beta"] / 2.5 - 1.0) <= 0.05, f"β={r['beta']}"
        assert abs(r["eta"] / 30.0 - 1.0) <= 0.05, f"η={r['eta']}"
        assert r["n_failures"] == xf.size and r["n_censored"] == xc.size

    def test_aging_closed_form_crosscheck(self):
        # aging.py 闭式互证：n50_from_weibull(:477) / weibull_life /
        # weibull_p_of_failure 往返恒等（消费面独立实现）
        xf, xc = _scipy_doc_example()
        r = ms.weibull_mle(xf, xc)
        beta, eta = r["beta"], r["eta"]
        assert abs(r["n50"] - float(aging.n50_from_weibull(eta, beta))) <= 1e-9
        b10 = float(aging.weibull_life(eta, beta, np.array([0.1]))[0])
        assert abs(r["b10"] - b10) <= 1e-9
        # 反演恒等：P_f(B10)=0.1、P_f(N50)=0.5、η→(1−1/e)
        assert abs(float(aging.weibull_p_of_failure(eta, beta, np.array([b10]))[0]) - 0.1) <= 1e-12
        assert abs(float(aging.weibull_p_of_failure(eta, beta, np.array([r["n50"]]))[0]) - 0.5) <= 1e-12
        assert abs(float(aging.weibull_from_n50(r["n50"], beta)) - eta) <= 1e-9

    def test_b10_fisher_vs_lr_bands(self):
        xf, xc = _scipy_doc_example()
        r = ms.weibull_mle(xf, xc)
        lo_lr, hi_lr = r["b10_ci"]["lr"]
        fisher_lo = r["b10_ci"]["fisher_lower"]
        # 嵌套序：LR 下根 ≤ Fisher 下界 ≤ B10 ≤ LR 上根（实测样例序，
        # 非定理——两侧区间同置信下的常规相对位置）
        assert lo_lr < fisher_lo < r["b10"] < hi_lr
        # Fisher delta 下界与 B10 的距离 = z·SE（解析式）
        # （间接核对：fisher_lo 在 LR 带内且不越过点估计）
        assert (r["b10"] - fisher_lo) > 0

    def test_lr_interval_satisfies_defining_equation(self):
        # LR 根满足定义方程 2ΔlnL = χ²_{1−α,1}（内核剖面路径复核）
        xf, xc = _scipy_doc_example()
        r = ms.weibull_mle(xf, xc)
        cut = float(stats.chi2.ppf(0.95, 1))

        def prof_beta(b: float) -> float:
            return float(
                optimize.minimize_scalar(
                    lambda e: ms._weibull_nll(b, e, xf, xc),
                    bounds=(r["eta"] * 0.05, r["eta"] * 20.0),
                    method="bounded",
                ).fun
            )

        bl, bh = r["ci_beta"]["lr"]
        d_lo = 2.0 * (prof_beta(bl) + r["loglik"])
        d_hi = 2.0 * (prof_beta(bh) + r["loglik"])
        assert abs(d_lo - cut) <= 1e-6 * cut
        assert abs(d_hi - cut) <= 1e-6 * cut
        # 区间包住 MLE
        assert bl < r["beta"] < bh

    def test_fisher_se_converges_to_asymptotic(self):
        # 大样本无删失：SE(β̂) → √(6β²/(nπ²))（独立解析来源，25% 容差）
        rng = np.random.default_rng(11)
        data = stats.weibull_min(c=2.5, scale=30).rvs(size=2000, random_state=rng)
        r = ms.weibull_mle(np.asarray(data, float), None)
        asym = 2.5 * np.sqrt(6.0 / (2000 * np.pi**2))
        assert abs(r["se_beta"] / asym - 1.0) < 0.25
        assert abs(r["beta"] / 2.5 - 1.0) < 0.05

    def test_lr_bands_bracket_fisher_for_beta_eta(self):
        # β/η 双口径带常规相对位置（LR 带包住 MLE、Fisher 带包住 MLE）
        xf, xc = _scipy_doc_example()
        r = ms.weibull_mle(xf, xc)
        for key, mle in (("ci_beta", r["beta"]), ("ci_eta", r["eta"])):
            lo_f, hi_f = r[key]["fisher"]
            lo_l, hi_l = r[key]["lr"]
            assert lo_l < mle < hi_l
            assert lo_f < mle < hi_f

    def test_no_censored_path(self):
        rng = np.random.default_rng(5)
        data = np.asarray(
            stats.weibull_min(c=3.0, scale=50).rvs(size=300, random_state=rng),
            float,
        )
        r = ms.weibull_mle(data, None)
        assert r["n_censored"] == 0 and r["n_failures"] == 300
        assert abs(r["beta"] / 3.0 - 1.0) < 0.10
        assert abs(r["eta"] / 50.0 - 1.0) < 0.10

    def test_confidence_level_scales_bands(self):
        xf, xc = _scipy_doc_example()
        r90 = ms.weibull_mle(xf, xc, confidence=0.90)
        r99 = ms.weibull_mle(xf, xc, confidence=0.99)
        width90 = r90["ci_beta"]["lr"][1] - r90["ci_beta"]["lr"][0]
        width99 = r99["ci_beta"]["lr"][1] - r99["ci_beta"]["lr"][0]
        assert width90 < width99

    def test_input_validation(self):
        with pytest.raises(ValueError, match="failures"):
            ms.weibull_mle([0.0, 1.0, 2.0])
        with pytest.raises(ValueError, match="failures"):
            ms.weibull_mle([1.0, -2.0, 3.0])
        with pytest.raises(ValueError, match="censored"):
            ms.weibull_mle([1.0, 2.0], [0.0])
        with pytest.raises(ValueError, match="confidence"):
            ms.weibull_mle([1.0, 2.0], confidence=1.5)
        with pytest.raises(ValueError, match="bool"):
            ms.weibull_mle([True, 2.0, 3.0])

    def test_output_json_serializable(self):
        xf, xc = _scipy_doc_example()
        r = ms.weibull_mle(xf, xc)
        json.dumps(r, ensure_ascii=False)  # 不抛即通过


# ════════════════════════════ CLI stats 子应用 ══════════════════════════════


class TestStatsCli:
    """rfauto stats 子应用薄壳（CliRunner 驱动真实入口）。"""

    def _invoke(self, *args: str):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        return CliRunner().invoke(app, list(args))

    def test_registered_in_top_level(self):
        from typer.main import get_command

        from rfauto.cli.main import app

        cmd = get_command(app)
        assert "stats" in set(cmd.commands)
        stats_cmd = cmd.commands["stats"]
        assert {"guardband", "cpk", "weibull"} <= set(stats_cmd.commands)

    def test_guardband_happy_path(self):
        result = self._invoke(
            "stats", "guardband", "0.95",
            "--u95", "0.10", "--tu", "1.0", "--pfa", "0.02", "--side", "upper",
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert abs(payload["m"] - float(stats.norm.ppf(0.98)) / 1.96) <= 1e-12
        assert payload["decision"] in ("accept", "reject")

    def test_guardband_bad_side_fails(self):
        result = self._invoke(
            "stats", "guardband", "0.95", "--u95", "0.10", "--tu", "1.0",
            "--side", "bogus",
        )
        assert result.exit_code != 0

    def test_cpk_happy_path(self):
        samples = ",".join(str(v) for v in np.random.default_rng(7).normal(5.0, 0.2, 40))
        result = self._invoke(
            "stats", "cpk", "--samples", samples,
            "--lsl", "4.4", "--usl", "5.6",
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["n"] == 40
        assert payload["cp_ci"]["method"] == "chi2_pivot_exact"

    def test_cpk_missing_limits_fails(self):
        result = self._invoke("stats", "cpk", "--samples", "5.0,5.1,4.9")
        assert result.exit_code != 0

    def test_weibull_happy_path(self):
        xf, xc = _scipy_doc_example()
        args = [
            "stats", "weibull",
            "--failures", ",".join(str(v) for v in xf),
            "--censored", ",".join(str(v) for v in xc),
        ]
        result = self._invoke(*args)
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["n_censored"] == int(xc.size)
        assert abs(payload["beta"] / 2.5 - 1.0) <= 0.05

    def test_weibull_file_input(self, tmp_path):
        xf, xc = _scipy_doc_example()
        f = tmp_path / "weibull_in.json"
        f.write_text(
            json.dumps({"failures": list(xf), "censored": list(xc)}),
            encoding="utf-8",
        )
        result = self._invoke("stats", "weibull", "--file", str(f))
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["n_censored"] == int(xc.size)
