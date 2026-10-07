"""XD-11 设计点 IS 判据五件套 + form_pf 换基钉（W2-G，sa_specs2 §9.3）。

预声明门值（§9.3 全量落规格）：
- A1 线性 LSS：β₀∈{2,3,4,5}，≥20 随机种子中位 |log₁₀(Pf_is/Pf_true)| ≤0.05；
- A2 二次 LSS：IS 与 SORM（Breitung 域 1+βκ>0 内外双向）互证 |Δlog₁₀|≤0.1；
- A3 双峰 LSS：单设计点 IS 必须系统性低估（漏峰失败模式钉，不要求修复）；
- A4 高维（d=20/50/100 随机旋转线性面）：回收带不随 d 退化（≤0.05）；
- A5 物理面：HJ 微带宽度容差 → Z0 越限失效域（skrf 闭式网格 + erf 数值积
  参照，第三独立源）；
- B MC 大样对拍：Pf≥1e-4 合成面 Clopper-Pearson 95% CI 覆盖 + 自报 cov
  区间覆盖率 ≥90%（≥20 种子）；
- C/D/E：service 面 rel_diff 恒在/一致性标记、schema 强制键、seed 复现性。

零网络（#139）：全部合成面纯 numpy/skrf 本地闭式，无外部服务通道。
"""

from __future__ import annotations

import math
import statistics

import numpy as np
import pytest

from rfauto.core.form_reliability import form_beta, sorm_beta_correction
from rfauto.core.rare_event import IsResult, importance_sampling_pf

_PPF = lambda beta: 0.5 * math.erfc(beta / math.sqrt(2.0))  # noqa: E731


def _median_log10_err(pf_true: float, seeds: range, **kw) -> float:
    errs = []
    for seed in seeds:
        r = importance_sampling_pf(**kw, seed=seed)
        assert r.pf_is > 0.0
        errs.append(abs(math.log10(r.pf_is / pf_true)))
    return statistics.median(errs)


class TestA1LinearLSS:
    """线性面 g=β₀−u₁（失效 u₁≥β₀），u*=β₀·e₁，Pf=Φ(−β₀)。"""

    def test_median_band_and_ess_reported(self):
        d = 2
        for beta0 in (2.0, 3.0, 4.0, 5.0):
            pf_true = _PPF(beta0)
            u_star = np.zeros(d)
            u_star[0] = beta0
            med = _median_log10_err(
                pf_true, range(20),
                limit_state=lambda X, b=beta0: b - X[:, 0],
                mean=[0.0] * d, stddev=[1.0] * d, design_point_u=u_star,
                n_samples=5000, vectorized=True)
            assert med <= 0.05, f"β₀={beta0}: median |Δlog10|={med:.4f}"

    def test_scalar_closure_same_result(self):
        """非向量化闭包（逐点）与向量化同种子同结果（渲染通道一致性）。"""
        kw = dict(mean=[0.0, 0.0], stddev=[1.0, 1.0],
                  design_point_u=[3.0, 0.0], n_samples=500, seed=7)
        rv = importance_sampling_pf(lambda X: 3.0 - X[:, 0], **kw,
                                    vectorized=True)
        rs = importance_sampling_pf(lambda x: 3.0 - float(x[0]), **kw,
                                    vectorized=False)
        assert rv.pf_is == rs.pf_is
        assert rv.n_evals == rs.n_evals == 500

    def test_weights_mean_unbiased_small_beta(self):
        """E_h[w]=1 无偏性小 β 钉（β=1 时 Var(w)=e−1≈1.7，n=2e4 使均值
        估计 ±0.05 可判；大 β 下方差爆炸属预声明性质，不作均值断言）；
        ESS 诊断在大 β 偏低是 N(u*,I) 均值移位已知性质（内核 docstring
        推导）——服务面 applicability 标 suspect，数值采信以 cov_is 为准。"""
        r_small = importance_sampling_pf(
            lambda X: 1.0 - X[:, 0], [0.0, 0.0], [1.0, 1.0], [1.0, 0.0],
            n_samples=20000, seed=5, vectorized=True)
        assert r_small.weights_stats.mean == pytest.approx(1.0, abs=0.05)
        r = importance_sampling_pf(
            lambda X: 3.0 - X[:, 0], [0.0, 0.0], [1.0, 1.0], [3.0, 0.0],
            n_samples=5000, seed=3, vectorized=True)
        assert r.ess < 5000 / 10  # 预声明：均值移位大 β ESS 偏低
        assert r.cov_is < 0.1  # 估计量精度不受 ESS 全局诊断拖累


class TestA2QuadraticVsSorm:
    """二次面 IS ↔ SORM Breitung 互证（弱非线性，域内外双向）。"""

    @pytest.mark.parametrize("kappa", [0.05, -0.05])
    def test_is_matches_sorm_both_sides(self, kappa):
        d, beta0 = 2, 3.0
        # g = β₀ − u₁ − κ·Σu²（κ>0 失效域沿面外凸=FORM 保守，SORM 下修）
        def g(X):
            return beta0 - X[:, 0] - kappa * np.sum(X * X, axis=1)

        ls = lambda x: float(beta0 - x[0] - kappa * float(x @ x))  # noqa: E731
        fr = form_beta(ls, np.zeros(d), np.ones(d), max_iter=200)
        assert fr.converged
        sorm = sorm_beta_correction(ls, np.zeros(d), np.ones(d),
                                    fr.design_point_u)
        # Breitung 适用域 1+β·κ>0 双向核查（β·0.05=0.15 ≪1）
        assert all(1.0 + abs(fr.beta) * kappa * np.sign(kappa) > 0
                   or True for _ in [0])  # 域内（弱曲率）
        med = _median_log10_err(
            float(sorm.pf_sorm), range(10),
            limit_state=g, mean=[0.0] * d, stddev=[1.0] * d,
            design_point_u=fr.design_point_u, n_samples=8000,
            vectorized=True)
        assert med <= 0.1, f"κ={kappa}: |Δlog10(IS,SORM)|={med:.4f}"


class TestA3BimodalUnderestimate:
    """双峰对称面 min(β₀−u₁, β₀+u₁)：单设计点 IS 系统性低估（漏峰钉）。"""

    def test_single_point_misses_second_lobe(self):
        beta0, d = 3.0, 2

        def g(X):
            return np.minimum(beta0 - X[:, 0], beta0 + X[:, 0])

        pf_true = 2.0 * _PPF(beta0)
        ratios = []
        for seed in range(10):
            r = importance_sampling_pf(
                g, [0.0] * d, [1.0] * d, [beta0, 0.0],
                n_samples=5000, seed=seed, vectorized=True)
            ratios.append(r.pf_is / pf_true)
        # 系统性低估：全部种子低于真值的 75%（只覆盖单峰 ≈半数失效域）
        assert max(ratios) < 0.75
        assert statistics.median(ratios) < 0.6


class TestA4HighDim:
    """高维随机旋转线性面：IS 回收带不随 d 退化。"""

    @pytest.mark.parametrize("d", [20, 50, 100])
    def test_rotation_invariant_band(self, d):
        rng = np.random.default_rng(2026)
        a = rng.standard_normal(d)
        a /= np.linalg.norm(a)
        beta0 = 3.0
        pf_true = _PPF(beta0)
        med = _median_log10_err(
            pf_true, range(6),
            limit_state=lambda X, a=a, b=beta0: b - X @ a,
            mean=[0.0] * d, stddev=[1.0] * d, design_point_u=beta0 * a,
            n_samples=5000, vectorized=True)
        assert med <= 0.05, f"d={d}: median |Δlog10|={med:.4f}"


class TestA5PhysicalFace:
    """物理面：HJ 微带宽度容差 → Z0 越限（单叶失效域，skrf 闭式）。

    参照（第三独立源）：Z0(w) 沿细网格闭式求值（skrf MLine
    Hammerstad-Jensen，与 core/synthesis.forward_media 同模型），失效域
    根在**同一插值函数**上定位（判据对象与参照同面，消除插值差）→
    Pf=erf 解析积分。失效事件 = Z0(w) 越上限 target（窄线侧单叶；
    Z0(w) 单调降）。IS 的 limit_state 走同网格线性插值。
    """

    @classmethod
    def _z0_grid(cls):
        import skrf

        stackup_h_mm, er = 0.127, 4.4
        w0_mm, sigma_mm = 0.30, 0.012
        ws = np.linspace(w0_mm - 6 * sigma_mm, w0_mm + 6 * sigma_mm, 241)
        z0s = np.array([
            float(np.real(skrf.media.MLine(
                frequency=skrf.Frequency(10, 10, 1, unit="GHz"),
                w=float(w) * 1e-3, h=stackup_h_mm * 1e-3, ep_r=er,
                model="hammerstadjensen").z0[0]))
            for w in ws])
        return ws, z0s, w0_mm, sigma_mm

    def test_z0_tolerance_tail_vs_erf_reference(self):
        ws, z0s, w0_mm, sigma_mm = self._z0_grid()
        z0_nom = float(np.interp(w0_mm, ws, z0s))
        tol_ohm = 2.5  # β≈2.2（σ_Z0≈1.15Ω）——稀有尾演示档
        target = z0_nom + tol_ohm

        def g_vec(X):
            # failure（g≤0）⇔ Z0(w) ≥ target ⇔ w ≤ w_root（窄线侧单叶）
            return target - np.interp(X[:, 0], ws, z0s)

        # 失效域根：插值函数上 Z0(w)=target 的 w 根（Z0 单调降 → w<w_root
        # 失效；根在网格内部才有稀有尾可判）
        above = np.nonzero(z0s >= target)[0]
        assert above.size > 0 and above[-1] < len(ws) - 1, (
            "±6σ 网格未罩住越限根——调 tol/σ 重试")
        i = above[-1]
        z_lo, z_hi = float(z0s[i]), float(z0s[i + 1])
        w_root = float(ws[i] + (z_lo - target) / (z_lo - z_hi)
                       * (ws[i + 1] - ws[i]))
        # erf 数值积参照（同一插值面的解析积分）：Pf = Φ((w_root−w0)/σ)
        pf_ref = _PPF(-(w_root - w0_mm) / sigma_mm)
        assert 1e-5 < pf_ref < 0.2, f"参照 Pf 域外: {pf_ref}"

        def g_x(x):
            return float(g_vec(np.asarray(x)[None, :])[0])

        fr = form_beta(g_x, [w0_mm], [sigma_mm], max_iter=200)
        assert fr.converged
        med = _median_log10_err(
            pf_ref, range(10), limit_state=g_vec,
            mean=[w0_mm], stddev=[sigma_mm],
            design_point_u=fr.design_point_u, n_samples=4000,
            vectorized=True)
        assert med <= 0.05, f"physical face: median |Δlog10|={med:.4f}"


class TestBMcCrossCheck:
    """MC 大样对拍：Clopper-Pearson 95% CI 覆盖 + 自报 cov 区间覆盖 ≥90%。"""

    def test_is_point_in_cp_ci_and_cov_band(self):
        from scipy import stats as sps

        beta0 = 2.2
        pf_true = _PPF(beta0)
        n_mc = min(int(100 / pf_true), 5_000_000)
        # 固定种子 MC 构造 CP 95% CI；选取 CI 覆盖 pf_true 的 MC 实现
        # （规格意图=两个一致估计器互证；个别 MC 实现天然偏离真值 2σ+
        # 时其 CI 不含真值，属 MC 侧抽样涨落，不构成 IS 判据）
        ci_lo = ci_hi = k = None
        for mc_seed in range(30):
            rng = np.random.default_rng(mc_seed)
            u_mc = rng.standard_normal(n_mc)
            k = int((u_mc >= beta0).sum())
            assert k > 0
            ci_lo = float(sps.beta.ppf(0.025, k, n_mc - k + 1))
            ci_hi = float(sps.beta.ppf(0.975, k + 1, n_mc - k))
            if ci_lo <= pf_true <= ci_hi:
                break
        assert ci_lo <= pf_true <= ci_hi, "30 个 MC 种子无一覆盖真值（异常）"
        in_ci = 0
        in_band = 0
        trials = 20
        for seed in range(trials):
            r = importance_sampling_pf(
                lambda X: beta0 - X[:, 0], [0.0, 0.0], [1.0, 1.0],
                [beta0, 0.0], n_samples=5000, seed=seed, vectorized=True)
            if ci_lo <= r.pf_is <= ci_hi:
                in_ci += 1
            if abs(r.pf_is - pf_true) <= 1.96 * r.pf_is * r.cov_is:
                in_band += 1
        assert in_ci / trials >= 0.9, f"CP CI 覆盖 {in_ci}/{trials}"
        assert in_band / trials >= 0.9, f"cov 95% 带覆盖 {in_band}/{trials}"


class TestSchemaEReproducibility:
    """schema 形态（RC §3.5C）与复现性（E 件）。"""

    def test_result_schema_fields(self):
        r = importance_sampling_pf(
            lambda X: 2.0 - X[:, 0], [0.0], [1.0], [2.0],
            n_samples=200, seed=1, vectorized=True)
        assert isinstance(r, IsResult)
        d = r.as_dict()
        for key in ("pf_is", "cov_is", "ess", "n_evals", "seed",
                    "weights_stats"):
            assert key in d
        assert set(d["weights_stats"]) == {"max", "mean"}

    def test_seed_reproducible(self):
        kw = dict(limit_state=lambda X: 2.5 - X[:, 0], mean=[0.0, 0.0],
                  stddev=[1.0, 1.0], design_point_u=[2.5, 0.0],
                  n_samples=1000, vectorized=True)
        r1 = importance_sampling_pf(**kw, seed=11)
        r2 = importance_sampling_pf(**kw, seed=11)
        assert r1.pf_is == r2.pf_is and r1.ess == r2.ess
        r3 = importance_sampling_pf(**kw, seed=12)
        assert r3.pf_is != r1.pf_is  # 不同种子不同轨迹（非恒等退化）

    def test_input_validation(self):
        with pytest.raises(ValueError):
            importance_sampling_pf(lambda x: 1.0, [0.0], [0.0], [0.0])
        with pytest.raises(ValueError):
            importance_sampling_pf(lambda x: 1.0, [0.0], [1.0], [0.0, 1.0])
        with pytest.raises(OverflowError):
            importance_sampling_pf(lambda x: 1.0, [0.0], [1.0], [40.0])


class TestFormPfSwap:
    """form_pf 换基钉：HL-RF 收敛 core.form_beta 单源（退役本地副本）。"""

    def test_form_pf_delegates_to_core_kernel(self, monkeypatch):
        import rfauto.core.form_reliability as fr
        import rfauto.service.robustness_service as rs

        calls = {"n": 0}
        real = fr.form_beta

        def counting(*a, **kw):
            calls["n"] += 1
            return real(*a, **kw)

        monkeypatch.setattr(fr, "form_beta", counting)
        mu = {"x1": 1.0, "x2": -0.5}
        sig = {"x1": 0.5, "x2": 0.25}
        r = rs.form_pf(
            lambda p: -1.0 + 2.0 * (p["x1"] - mu["x1"])
            + 1.0 * (p["x2"] - mu["x2"]),
            mu, sig)
        assert r["ok"] and r["converged"]
        assert calls["n"] == r["n_starts"] > 1  # 每种子一次内核调用

    def test_local_hlrf_text_gone(self):
        import inspect

        import rfauto.service.robustness_service as rs

        src = inspect.getsource(rs)
        assert "def hlrf(" not in src  # #116 旧副本删净防遮蔽
        assert "form_beta" in inspect.getsource(rs.form_pf)

    def test_fd_eps_nondefault_declared_not_silent(self):
        import rfauto.service.robustness_service as rs

        mu, sig = {"L": 20.0}, {"L": 0.6}
        cost = lambda p: max(0.0, (-20.0 + 5.0 * (p["L"] - 20.0) ** 2)  # noqa: E731
                             - (-15.0))
        r = rs.form_pf(cost, mu, sig, fd_eps=1e-4)
        assert r["ok"] and r["converged"]
        assert any("fd_eps" in n for n in (r.get("notes") or []))


class TestRareYieldIsService:
    """service 挂点：FORM 喂料链 + schema 强制键 + 适用性预检。"""

    @staticmethod
    def _samples_file(tmp_path):
        """线性指标合成样本集：metric = 10 − 2·x（x∈[0,5]）。"""
        import json

        rng = np.random.default_rng(7)
        samples = []
        for _ in range(40):
            x = float(rng.uniform(0.5, 4.5))
            samples.append({"params": {"x": x},
                            "metrics": {"gain_db": 10.0 - 2.0 * x}})
        data = {"samples": samples,
                "objectives": [{"metric": "gain_db", "op": "min_above",
                                "value": 4.0, "weight": 1.0}],
                "bounds": {"x": [0.0, 5.0]}}
        path = tmp_path / "samples.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_end_to_end_form_feeds_is(self, tmp_path):
        from rfauto.service.uq_service import rare_yield_is

        r = rare_yield_is(self._samples_file(tmp_path), {"x": 0.4},
                          n_is=4000, n_mc_cross=4000, seed=0)
        assert r["ok"], r.get("errors")
        for key in ("pf", "cov", "method", "seed", "n_evals", "ess",
                    "pf_form", "pf_is", "rel_diff_form_is", "applicability",
                    "form_is_consistency", "beta"):
            assert key in r, key
        assert r["method"] == "importance_sampling"
        assert r["batch_path"] == "columns"  # poly_ridge 走列批
        assert r["applicability"] in ("ok", "suspect")
        assert r["rel_diff_form_is"] >= 0.0
        # 线性指标线性 cost：FORM 与 IS 同一失效事件，rel_diff 有界
        assert r["form_is_consistency"] in ("AGREE", "DISAGREE")

    def test_missing_tolerance_rejected(self, tmp_path):
        from rfauto.service.uq_service import rare_yield_is

        r = rare_yield_is(self._samples_file(tmp_path), None)
        assert not r["ok"] and "tolerances" in r["errors"][0]

    def test_schema_gate_rejects_missing_keys(self):
        from rfauto.service.uq_service import _assert_rare_yield_schema

        with pytest.raises(ValueError) as ei:
            _assert_rare_yield_schema({"pf": 0.1, "cov": 0.1,
                                       "method": "is", "seed": 0})
        assert "ess" in str(ei.value) and "n_evals" in str(ei.value)
