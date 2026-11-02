"""T-N11 saas_gp 全后验档单测（aurora_n W2；预声明判据见
runs/aurora_n/w2_tn11/CRITERIA.md——本文件在任何实验数据前写定门）。

覆盖：后验正确性合成对照（已知稀疏长度尺度真值集中带 G1-G4）、确定性
钉（G7/G8 逐位）、负例（G9 数据退化显式报错）、缺省等价钉（G10 MAP
旧路径 golden 逐位，改前捕获）、采集面（平均 LCB/EI 两档语义）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import qmc

from rfauto.optimization.surrogate import surrogate_registry
from rfauto.optimization.surrogate.saas_gp import (
    SaasArdSurrogate,
    sample_saas_posterior,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# ── 后验正确性合成对照设置（CRITERIA §1，预声明） ────────────────────────────
D4 = 4
ELL_TRUE = np.array([0.15, 0.30, 6.0, 10.0])  # 2 开 2 关
ACTIVE_TRUE = {0, 1}


def _draw_gp_truth(n: int = 64, seed: int = 123) -> tuple[np.ndarray, np.ndarray]:
    """无噪声 GP 先验直抽：y ~ N(0, K(ℓ_true, amp=1))，matern52。"""
    from rfauto.optimization.surrogate.gp_det import matern52_ard_kernel

    u = qmc.LatinHypercube(d=D4, seed=3).random(n=n)
    k = matern52_ard_kernel(u, u, ELL_TRUE, 1.0)
    k[np.diag_indices(n)] += 1e-10
    rng = np.random.default_rng(seed)
    y = np.linalg.cholesky(k) @ rng.standard_normal(n)
    return u, y


def _posterior_on_truth():
    u, y = _draw_gp_truth()
    return sample_saas_posterior(
        u, y, kind="matern52", seed=7, burn=120, n_samples=96, thin=2)


class TestPosteriorCorrectness:
    """G1-G4：后验样本在真值邻域集中（合成对照，#118 闭式真值源）。"""

    def test_sparse_lengthscale_truth_recovery(self):
        res = _posterior_on_truth()
        ell = res["ell_samples"]
        assert ell.shape == (96, D4)
        med = np.median(ell, axis=0)
        # G1：活跃集回收（中位 < 阈值 2.0）
        active = {i for i in range(D4) if med[i] < 2.0}
        assert active == ACTIVE_TRUE
        # G2：开启维集中（因子 2 预声明带）
        for i in sorted(ACTIVE_TRUE):
            assert 0.5 * ELL_TRUE[i] <= med[i] <= 2.0 * ELL_TRUE[i], (
                f"dim{i}: median {med[i]} vs true {ELL_TRUE[i]}")
        # G3：关闭维分离（> 阈值且 ≥ 3× 开启维最大中位）
        max_on = max(med[i] for i in ACTIVE_TRUE)
        for i in range(D4):
            if i not in ACTIVE_TRUE:
                assert med[i] > 2.0 and med[i] >= 3.0 * max_on, (
                    f"off dim{i}: median {med[i]} vs max_on {max_on}")
        # G4：链健康探针
        assert 0.05 <= res["accept_rate"] <= 0.95

    def test_chain_archive_matches_contract(self):
        res = _posterior_on_truth()
        assert res["log_ell_samples"].shape == (96, D4)
        # 自然空间 = log 空间逐位取指（存档一致性）
        assert np.array_equal(res["ell_samples"],
                              np.exp(res["log_ell_samples"]))
        assert res["seed"] == 7 and res["n_samples"] == 96
        assert np.isfinite(res["amp"]) and res["nugget"] > 0.0
        assert np.all(res["map_ell"] > 0.0)


class TestDeterminism:
    """G7/G8：同 seed 链与采集序列逐位复现（C4）。"""

    def test_sampler_bitwise(self):
        u, y = _draw_gp_truth()
        r1 = sample_saas_posterior(u, y, seed=7, burn=40, n_samples=32,
                                   thin=2)
        r2 = sample_saas_posterior(u, y, seed=7, burn=40, n_samples=32,
                                   thin=2)
        assert np.array_equal(r1["log_ell_samples"], r2["log_ell_samples"])
        assert r1["accept_rate"] == r2["accept_rate"]

    def test_fit_and_acquisition_bitwise(self):
        rng = np.random.default_rng(5)
        samples = [{"params": {f"x{i}": float(v) for i, v in enumerate(row)},
                    "metrics": {"y": float(np.sin(2 * np.pi * row[0])
                                          + 0.1 * rng.standard_normal())}}
                   for row in qmc.LatinHypercube(
                       d=D4, seed=9).random(n=20)]
        post = {"seed": 11, "n_samples": 16, "burn": 20, "thin": 1}
        cands = [{f"x{i}": float(v) for i, v in enumerate(row)}
                 for row in qmc.LatinHypercube(
                     d=D4, seed=10).random(n=7)]
        m1 = SaasArdSurrogate(config={
            "bounds": {f"x{i}": (0.0, 1.0) for i in range(D4)},
            "posterior_samples": post})
        m2 = SaasArdSurrogate(config={
            "bounds": {f"x{i}": (0.0, 1.0) for i in range(D4)},
            "posterior_samples": post})
        m1.fit(samples)
        m2.fit(samples)
        assert np.array_equal(m1.lengthscale_samples_["y"],
                              m2.lengthscale_samples_["y"])
        assert m1.posterior_info_["y"]["accept_rate"] == \
            m2.posterior_info_["y"]["accept_rate"]
        assert m1.acquire_ei(cands) == m2.acquire_ei(cands)
        assert m1.acquire_lcb(cands) == m2.acquire_lcb(cands)


class TestDegenerateNegative:
    """G9：数据退化（n<维度）显式报错不静默（预声明负例）。"""

    def test_fit_raises_when_points_below_dims(self):
        samples = [{"params": {f"x{i}": float(0.1 * (j + 1) + 0.01 * i)
                               for i in range(D4)},
                    "metrics": {"y": float(j)}}
                   for j in range(3)]  # n=3 < d=4
        model = SaasArdSurrogate(config={
            "bounds": {f"x{i}": (0.0, 1.0) for i in range(D4)},
            "posterior_samples": {"seed": 1, "n_samples": 4, "burn": 2,
                                  "thin": 1}})
        with pytest.raises(ValueError, match="数据退化"):
            model.fit(samples)

    def test_sampler_direct_raises_below_dims(self):
        with pytest.raises(ValueError, match="n=2 < 维度 d=4"):
            sample_saas_posterior(
                np.array([[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]),
                np.array([1.0, 2.0]), seed=1, n_samples=4, burn=2)

    def test_bad_chain_config_raises(self):
        u, y = _draw_gp_truth(n=16)
        with pytest.raises(ValueError, match="链长非法"):
            sample_saas_posterior(u, y, seed=1, n_samples=0)
        with pytest.raises(ValueError, match="proposal_scale"):
            sample_saas_posterior(u, y, seed=1, proposal_scale=0.0)


# ── 缺省等价钉（G10）：改前捕获的 MAP 旧路径 golden（full-repr 逐位） ────────
D15 = 15
BOUNDS_15 = {f"x{i}": (0.0, 1.0) for i in range(D15)}
GOLDEN_LENGTHSCALES = {
    "x0": 2980.9579870417283, "x1": 2980.1299954433252,
    "x10": 2521.7529532824583, "x11": 2980.9579870417283,
    "x12": 2980.9579870417283, "x13": 2978.087093410085,
    "x14": 2980.9579870417283, "x2": 1.3588460902856534,
    "x3": 2980.9579870417283, "x4": 2979.2450095225417,
    "x5": 2980.9579870417283, "x6": 2980.828872943958,
    "x7": 1.456270008443687, "x8": 2980.9579870417283,
    "x9": 2980.9579870417283}
GOLDEN_ACTIVE = ["x2", "x7"]
GOLDEN_PRED5 = [0.22406593120649632, -0.3506139044354768,
                -0.9688206478053871, 0.6062204359536736,
                -0.37232993774864553]
GOLDEN_UNC5 = [0.011518408003381053, 0.010655519439615303,
               0.015156386850217524, 0.006762693979807104,
               0.009337823011203032]


def _samples15(n: int = 48, seed: int = 11) -> list[dict]:
    def f15(u: np.ndarray) -> float:
        return 0.6 * np.sin(2 * np.pi * u[2]) + 0.5 * np.sin(2 * np.pi * u[7])

    u_all = qmc.LatinHypercube(d=D15, seed=seed).random(n=n)
    return [{"params": {f"x{i}": float(u[i]) for i in range(D15)},
             "metrics": {"y": float(f15(u))}} for u in u_all]


class TestDefaultMapEquivalence:
    """G10：缺省（无 posterior_samples）= MAP 旧路径逐位不变。"""

    def test_golden_bitwise(self):
        model = SaasArdSurrogate(config={"bounds": BOUNDS_15})
        model.fit(_samples15())
        assert model.lengthscales_["y"] == GOLDEN_LENGTHSCALES
        assert model.active_dims_["y"] == GOLDEN_ACTIVE
        assert not model.posterior_mode
        assert model.lengthscale_samples_ == {}
        assert model.posterior_info_ == {}
        u_test = qmc.LatinHypercube(d=D15, seed=12).random(n=5)
        pts = [{f"x{i}": float(u[i]) for i in range(D15)} for u in u_test]
        assert [model.predict(p)["y"] for p in pts] == GOLDEN_PRED5
        assert [model.uncertainty(p)["y"] for p in pts] == GOLDEN_UNC5

    def test_registered(self):
        assert "saas_gp" in surrogate_registry.available()


class TestAcquisitionFaces:
    """采集面：平均 LCB/EI 两档语义 + 确定性 + 池 argmax 消费形态。"""

    def _fit(self, post=None):
        model = SaasArdSurrogate(config={
            "bounds": {f"x{i}": (0.0, 1.0) for i in range(D4)},
            "posterior_samples": post})
        samples = [{"params": {f"x{i}": float(v) for i, v in enumerate(row)},
                    "metrics": {"y": float(np.sin(2 * np.pi * row[0]))}}
                   for row in qmc.LatinHypercube(
                       d=D4, seed=22).random(n=20)]
        model.fit(samples)
        return model

    def test_map_mode_single_point_semantics(self):
        model = self._fit()
        cands = [{f"x{i}": 0.5 for i in range(D4)}]
        lcb = model.acquire_lcb(cands, beta=2.0)
        ei = model.acquire_ei(cands)
        assert len(lcb) == 1 and len(ei) == 1
        assert ei[0] >= 0.0  # EI 非负（极小化口径）
        mu = model.predict(cands[0])["y"]
        sig = model.uncertainty(cands[0])["y"]
        assert lcb[0] == pytest.approx(mu - 2.0 * sig, rel=1e-12)
        assert model.acquire_ei([]) == []
        with pytest.raises(ValueError, match="未知指标"):
            model.acquire_ei(cands, metric="ghost")

    def test_posterior_mode_averaging(self):
        model = self._fit(post={"seed": 3, "n_samples": 12, "burn": 16,
                                "thin": 1})
        cands = [{f"x{i}": float(v) for i, v in enumerate(row)}
                 for row in qmc.LatinHypercube(d=D4, seed=23).random(n=6)]
        lcb = model.acquire_lcb(cands)
        ei = model.acquire_ei(cands)
        assert len(lcb) == len(ei) == 6
        assert all(np.isfinite(v) for v in lcb + ei)
        assert all(v >= 0.0 for v in ei)
        m = model.lengthscale_samples_["y"]
        assert m.shape == (12, D4)
        info = model.posterior_info_["y"]
        assert set(info) == {"accept_rate", "seed", "n_samples", "burn",
                             "thin", "amp", "nugget"}
        # 平均 LCB == 混合 μ − β·(逐样本 σ 的平均)（逐位口径自证）
        mu_mix = model.predict(cands[0])["y"]
        rows = model._pool_rows([cands[0]])
        sig_bar = float(np.mean([
            np.sqrt(max(gp.predict(rows)[1][0], 0.0))
            for gp in model.sample_models_["y"]]))
        assert lcb[0] == pytest.approx(mu_mix - 2.0 * sig_bar, rel=1e-12)


# ── E2 档（aurora_p）：sampler="nuts" 升级位（缺省 mh 零变化的增量钉） ──────
from rfauto.optimization.surrogate.gp_det import (
    fit_map,
    gp_nll,
    matern52_ard_kernel,
    se_ard_kernel,
)
from rfauto.optimization.surrogate.saas_gp import (
    _kernel_dlog_ell,
    _saas_log_post_grad,
)


class TestNutsGradient:
    """E2 梯度面对拍（#118 家法：解析梯度必须有独立来源验证）。

    两次实战修正的回归钉：① Matérn 5/2 导数误乘核值因子（首版
    base×slope）；② 0.5 项符号反（MAP 点 FD≈0 是地面真相）。本类
    在**非驻点**（MAP 最优点梯度≈0，FD 相对误差判据失效）对拍。
    """

    def _data(self, n: int = 24):
        u = qmc.LatinHypercube(d=D4, seed=3).random(n=n)
        k = matern52_ard_kernel(u, u, ELL_TRUE, 1.0)
        k[np.diag_indices(n)] += 1e-10
        y = np.linalg.cholesky(k) @ np.random.default_rng(
            123).standard_normal(n)
        prior = {"log_ell_mean": 0.0, "log_ell_var": 100.0}
        map_res = fit_map(u, y, kind="matern52", prior=prior)
        return u, y, prior, map_res

    def _lpgrad(self, lg, u, y, prior, map_res):
        return _saas_log_post_grad(
            lg, u, y, "matern52", float(map_res["nugget"]), prior,
            float(np.log(float(map_res["amp"]))))

    def test_log_posterior_gradient_matches_finite_difference(self):
        u, y, prior, map_res = self._data()
        rng = np.random.default_rng(2026)
        h = 1e-4
        for _trial in range(5):
            lg = rng.uniform(-3.0, 3.0, D4)
            _, g = self._lpgrad(lg, u, y, prior, map_res)
            for j in range(D4):
                lg_p = lg.copy()
                lg_p[j] += h
                lg_m = lg.copy()
                lg_m[j] -= h
                lpp, _ = self._lpgrad(lg_p, u, y, prior, map_res)
                lpm, _ = self._lpgrad(lg_m, u, y, prior, map_res)
                fd = (lpp - lpm) / (2.0 * h)
                rel = abs(fd - g[j]) / max(abs(fd), abs(g[j]), 1e-8)
                assert rel < 1e-6, (
                    f"梯度对拍失败 dim{j}: analytic={g[j]} fd={fd} "
                    f"rel={rel}")

    def test_log_posterior_parity_with_mh_path(self):
        # NUTS 档 log p 与 MH 档（gp_nll 取负）同式同序——逐位一致钉
        u, y, prior, map_res = self._data()
        amp = float(map_res["amp"])
        nugget = float(map_res["nugget"])
        lg = np.log(np.maximum(
            np.asarray(map_res["ell"], dtype=float), 1e-300))
        lp_mh = -gp_nll(np.concatenate([lg, [np.log(amp)]]), u, y,
                        "matern52", nugget, prior)
        lp_nuts, _ = _saas_log_post_grad(lg, u, y, "matern52", nugget,
                                         prior, np.log(amp))
        assert lp_mh == lp_nuts

    def test_kernel_dlog_ell_matches_finite_difference(self):
        # 两核 ∂K/∂log ℓ_j 对中心差分（SE 精确式 k·z_j；Matérn 5/2
        # 修正式不含核值因子——首版回归钉）
        u, _, _, _ = self._data()
        rng = np.random.default_rng(7)
        ell = rng.uniform(0.2, 3.0, D4)
        amp = 1.3
        h = 1e-6
        for kind, kern in (("se", se_ard_kernel),
                           ("matern52", matern52_ard_kernel)):
            for j in range(D4):
                e_p = ell.copy()
                e_p[j] *= np.exp(h)
                e_m = ell.copy()
                e_m[j] *= np.exp(-h)
                fd = (kern(u, u, e_p, amp) - kern(u, u, e_m, amp)) / (
                    2.0 * h)
                an = _kernel_dlog_ell(u, ell, amp, kind, j)
                denom = max(float(np.abs(fd).max()), 1e-12)
                assert float(np.abs(fd - an).max()) / denom < 1e-5, (
                    f"{kind} dim{j} 核导数对拍失败")


class TestNutsPosteriorMode:
    """E2 sampler="nuts" 端到端：正确性/确定性/接口形态/负例。"""

    def _data64(self):
        return _draw_gp_truth(n=64, seed=123)

    def test_active_set_recovery_nuts(self):
        # 预声明判据（G1/G2 同款口径，nuts 档缺省 ε=0.10 小预算）：
        # 活跃集回收 + 开启维集中带 + 关闭维分离（seed 固定=确定性事实）
        u, y = self._data64()
        res = sample_saas_posterior(u, y, kind="matern52", seed=7,
                                    burn=80, n_samples=120, thin=1,
                                    sampler="nuts")
        ell = res["ell_samples"]
        assert ell.shape == (120, D4)
        assert res["sampler"] == "nuts"
        med = np.median(ell, axis=0)
        active = {i for i in range(D4) if med[i] < 2.0}
        assert active == ACTIVE_TRUE, f"活跃集未回收: {med}"
        for i in sorted(ACTIVE_TRUE):
            assert 0.5 * ELL_TRUE[i] <= med[i] <= 2.0 * ELL_TRUE[i], (
                f"dim{i}: median {med[i]} vs true {ELL_TRUE[i]}")
        max_on = max(med[i] for i in ACTIVE_TRUE)
        for i in range(D4):
            if i not in ACTIVE_TRUE:
                assert med[i] > 2.0 and med[i] >= 3.0 * max_on
        # 健康探针：漏斗形 GP 超参后验上小预算零发散（ε=0.10 档）
        assert res["n_divergent"] == 0
        assert res["move_rate"] >= 0.9
        assert 0 < res["tree_depth_mean"] <= 10
        assert res["leapfrog_total"] > 0
        assert res["step_size"] == 0.10

    def test_nuts_bitwise_deterministic(self):
        u, y = self._data64()
        kw = dict(seed=7, burn=20, n_samples=24, thin=1, sampler="nuts")
        r1 = sample_saas_posterior(u, y, **kw)
        r2 = sample_saas_posterior(u, y, **kw)
        assert np.array_equal(r1["log_ell_samples"],
                              r2["log_ell_samples"])
        assert r1["accept_rate"] == r2["accept_rate"]
        assert r1["leapfrog_total"] == r2["leapfrog_total"]

    def test_fit_nuts_mode_interface_shape(self):
        # 模型面：posterior_info_ 两档同形同 7 键（既有钉不破）；
        # posterior_diag_ 仅 nuts 档有诊断；采集面 nuts 档可用
        samples = [{"params": {f"x{i}": float(v)
                               for i, v in enumerate(row)},
                    "metrics": {"y": float(np.sin(2 * np.pi * row[0]))}}
                   for row in qmc.LatinHypercube(
                       d=D4, seed=9).random(n=20)]
        cands = [{"params": {f"x{i}": float(v)
                             for i, v in enumerate(row)}}
                 for row in qmc.LatinHypercube(
                     d=D4, seed=10).random(n=5)]
        m_nuts = SaasArdSurrogate(config={
            "bounds": {f"x{i}": (0.0, 1.0) for i in range(D4)},
            "posterior_samples": {"seed": 3, "n_samples": 8, "burn": 12,
                                  "thin": 1, "sampler": "nuts"}})
        m_nuts.fit(samples)
        m_mh = SaasArdSurrogate(config={
            "bounds": {f"x{i}": (0.0, 1.0) for i in range(D4)},
            "posterior_samples": {"seed": 3, "n_samples": 8, "burn": 12,
                                  "thin": 1}})
        m_mh.fit(samples)
        for m in (m_nuts, m_mh):  # 两档 posterior_info_ 严格同形
            assert set(m.posterior_info_["y"]) == {
                "accept_rate", "seed", "n_samples", "burn", "thin",
                "amp", "nugget"}
        assert set(m_nuts.posterior_diag_["y"]) == {
            "sampler", "move_rate", "tree_depth_mean", "n_divergent",
            "leapfrog_total", "step_size", "max_tree_depth"}
        assert m_nuts.posterior_diag_["y"]["sampler"] == "nuts"
        assert m_mh.posterior_diag_ == {}  # mh/MAP 档零变化
        # nuts 档采集面可用且确定性
        lcb1 = m_nuts.acquire_lcb(cands)
        lcb2 = m_nuts.acquire_lcb(cands)
        assert lcb1 == lcb2 and len(lcb1) == 5
        assert all(np.isfinite(v) for v in lcb1)
        ei = m_nuts.acquire_ei(cands)
        assert all(v >= 0.0 for v in ei)

    def test_unknown_sampler_raises(self):
        u, y = self._data64()
        with pytest.raises(ValueError, match="未知采样器档"):
            sample_saas_posterior(u, y, seed=1, n_samples=4, burn=2,
                                  sampler="ghost")
        with pytest.raises(ValueError, match="nuts_step_size"):
            sample_saas_posterior(u, y, seed=1, n_samples=4, burn=2,
                                  sampler="nuts", nuts_step_size=0.0)
        with pytest.raises(ValueError, match="nuts_max_depth"):
            sample_saas_posterior(u, y, seed=1, n_samples=4, burn=2,
                                  sampler="nuts", nuts_max_depth=13)
