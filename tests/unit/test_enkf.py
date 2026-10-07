"""core/enkf.py（EnKF/ES-MDA 数据同化内核，S3 回灌件）测试。

#340 合成已知量回收钉范式 + 双独立基准：
- 线性高斯闭式对拍：解析卡尔曼后验（closed_form_kf_update，定义式）；
- 合成参数回收：已知真值造观测，回灌后集合均值收敛真值；
- ES-MDA 线性等价性 / n_assim=1 与单步 EnKF 逐位一致；
- 确定性（seed 逐位）与形状守卫。

全离线零网络；小矩阵 numpy 运算不触 #258 规模。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.enkf import (
    closed_form_kf_update,
    enkf_analysis_step,
    es_mda,
)

N_ENS = 40000


# ---------------------------------------------------------------------------
# 闭式基准：closed_form_kf_update 自身的一致性（标量解析对照）
# ---------------------------------------------------------------------------

class TestClosedFormKF:
    def test_scalar_analytical_values(self):
        """标量系统 P=4, R=1, H=1：K=4/5、x_a=0.8、P_a=0.8（手算解析值）。"""
        mean, cov = closed_form_kf_update(
            prior_mean=0.0, prior_cov=4.0, h=1.0, r=1.0, obs=1.0)
        assert mean[0] == pytest.approx(0.8, abs=1e-12)
        assert cov[0, 0] == pytest.approx(0.8, abs=1e-12)

    def test_observation_exact_identity(self):
        """R→0 时后验均值→观测投影（数据完全可信的极限闭式）。"""
        mean, _ = closed_form_kf_update(
            prior_mean=[0.0, 0.0], prior_cov=np.diag([4.0, 4.0]),
            h=[[1.0, 0.0]], r=1e-12, obs=0.7)
        assert mean[0] == pytest.approx(0.7, abs=1e-6)

    def test_no_information_keeps_prior(self):
        """R→∞ 时后验≈先验（观测无信息极限）。"""
        mean, cov = closed_form_kf_update(
            prior_mean=[0.3, -0.4], prior_cov=np.diag([2.0, 3.0]),
            h=[[1.0, 0.0]], r=1e18, obs=100.0)
        assert mean[0] == pytest.approx(0.3, abs=1e-6)
        assert cov[0, 0] == pytest.approx(2.0, rel=1e-6)
        assert cov[1, 1] == pytest.approx(3.0, rel=1e-6)


# ---------------------------------------------------------------------------
# EnKF 分析步 vs 解析卡尔曼（同先验集合实现条件下的更新步对拍）
# ---------------------------------------------------------------------------

class TestEnkfVsClosedForm:
    def test_scalar_update_matches_closed_form(self):
        """同一先验集合实现下，EnKF 后验均值/协方差=解析卡尔曼（同 P 输入）。"""
        rng = np.random.default_rng(20261003)
        ens0 = rng.normal(0.0, 2.0, size=(N_ENS, 1))
        obs = np.array([1.0])
        ens1 = enkf_analysis_step(ens0, obs, h=1.0, r=1.0,
                                  rng=np.random.default_rng(7))
        # 用该实现的先验经验均值/协方差进解析式（同条件对拍，消先验采样差）
        prior_mean = np.array([ens0.mean()])
        prior_cov = np.array([[ens0.var(ddof=1)]])
        kf_mean, kf_cov = closed_form_kf_update(
            prior_mean, prior_cov, h=1.0, r=1.0, obs=obs)
        # 采样误差量级：均值 ~sqrt(P_a/N)，扰动观测加宽一档后取 4 倍余量
        assert ens1[:, 0].mean() == pytest.approx(kf_mean[0], abs=0.03)
        assert ens1[:, 0].var(ddof=1) == pytest.approx(kf_cov[0, 0], abs=0.05)

    def test_2d_parameter_recovery(self):
        """合成参数回收：真值 [1.0, −0.5]，回灌后集合均值收敛真值（#340 钉）。"""
        x_true = np.array([1.0, -0.5])
        rng = np.random.default_rng(42)
        ens0 = rng.normal(0.0, 3.0, size=(N_ENS, 2))
        ens1 = enkf_analysis_step(
            ens0, obs=x_true, h=np.eye(2),
            r=np.diag([0.25, 0.25]), seed=11)
        assert np.allclose(ens1.mean(axis=0), x_true, atol=0.05)
        # 数据压缩不确定性：后验逐维方差 ≪ 先验（9.0）
        assert np.all(ens1.var(axis=0, ddof=1) < 0.5)

    def test_partial_observability_information_structure(self):
        """只观测 x1：x1 被拉向观测，x2 后验方差≈先验（信息结构闭式性质）。"""
        rng = np.random.default_rng(5)
        ens0 = rng.normal(0.0, 3.0, size=(N_ENS, 2))
        ens1 = enkf_analysis_step(
            ens0, obs=[0.8], h=[[1.0, 0.0]], r=0.1, seed=13)
        assert ens1[:, 0].mean() == pytest.approx(0.8, abs=0.03)
        assert ens1[:, 1].var(ddof=1) == pytest.approx(9.0, rel=0.1)


# ---------------------------------------------------------------------------
# ES-MDA
# ---------------------------------------------------------------------------

class TestEsMda:
    def test_n_assim_one_is_bitwise_single_step(self):
        """n_assim=1 与单步 EnKF 同 seed 逐位一致（调度退化的自洽钉）。"""
        rng = np.random.default_rng(3)
        ens0 = rng.normal(0.0, 2.0, size=(5000, 2))
        out_mda = es_mda(ens0, obs=[1.0, -1.0], h=np.eye(2), r=1.0,
                         n_assim=1, seed=99)
        out_step = enkf_analysis_step(ens0, obs=[1.0, -1.0], h=np.eye(2),
                                      r=1.0, seed=99)
        assert np.array_equal(out_mda, out_step)

    def test_linear_es_mda_matches_single_step_posterior(self):
        """线性情形 ES-MDA（4 步弱同化）后验均值=单步强同化（Emerick 等价性）。"""
        obs = np.array([1.0, -0.5])
        rng = np.random.default_rng(21)
        ens0 = rng.normal(0.0, 3.0, size=(N_ENS, 2))
        out_mda = es_mda(ens0, obs=obs, h=np.eye(2),
                         r=np.diag([0.5, 0.5]), n_assim=4, seed=31)
        out_step = enkf_analysis_step(ens0, obs=obs, h=np.eye(2),
                                      r=np.diag([0.5, 0.5]), seed=37)
        assert np.allclose(out_mda.mean(axis=0), out_step.mean(axis=0),
                           atol=0.05)

    def test_determinism_same_seed_bitwise(self):
        """同 seed 逐位可复现；异 seed 统计同分布但逐位不同。"""
        ens0 = np.random.default_rng(1).normal(0.0, 2.0, size=(4000, 2))
        a = es_mda(ens0, obs=[0.5, 0.5], h=np.eye(2), r=1.0, seed=123)
        b = es_mda(ens0, obs=[0.5, 0.5], h=np.eye(2), r=1.0, seed=123)
        c = es_mda(ens0, obs=[0.5, 0.5], h=np.eye(2), r=1.0, seed=124)
        assert np.array_equal(a, b)
        assert not np.array_equal(a, c)

    def test_inflation_positive_guard(self):
        """inflation 非正拒绝（先验膨胀因子口径守卫）。"""
        with pytest.raises(ValueError, match="inflation"):
            enkf_analysis_step(np.zeros((10, 1)), obs=[0.0], h=1.0, r=1.0,
                               inflation=0.0, seed=1)


# ---------------------------------------------------------------------------
# 形状守卫
# ---------------------------------------------------------------------------

class TestGuards:
    def test_ensemble_too_small_rejected(self):
        with pytest.raises(ValueError, match="N>=2"):
            enkf_analysis_step(np.zeros((1, 2)), obs=[0.0], h=1.0, r=1.0,
                               seed=1)

    def test_h_state_dim_mismatch_rejected(self):
        ens = np.zeros((10, 2))
        with pytest.raises(ValueError, match="状态维"):
            enkf_analysis_step(ens, obs=[0.0], h=[[1.0, 0.0, 0.0]], r=1.0,
                               seed=1)

    def test_h_obs_dim_mismatch_rejected(self):
        ens = np.zeros((10, 2))
        with pytest.raises(ValueError, match="观测维"):
            enkf_analysis_step(ens, obs=[0.0, 0.0], h=[[1.0, 0.0]], r=1.0,
                               seed=1)

    def test_es_mda_n_assim_guard(self):
        ens = np.zeros((10, 2))
        with pytest.raises(ValueError, match="n_assim"):
            es_mda(ens, obs=[0.0], h=1.0, r=1.0, n_assim=0, seed=1)

    def test_closed_form_prior_cov_shape_guard(self):
        with pytest.raises(ValueError, match="方阵"):
            closed_form_kf_update([0.0], np.array([1.0, 2.0]), 1.0, 1.0, 1.0)
