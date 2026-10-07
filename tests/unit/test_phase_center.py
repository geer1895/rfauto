"""AP-2 相位中心估计锚测试（round17 §三 AP-2，2026-10-03）。

锚口径（#118/#300：≥2 独立基准/件，门值预声明；#122 不凑绿）：

- 平移定理合成（线性模型精确可解）：任意 F(û) 相位 +k·û·d₀ →
  恢复 d₀ rel<1e-9、残差 <1e-9 rad（模型恰为设计矩阵张成）。
- 独立物理路径：点源在 d₀ 的真实球面路径相位 −k|Rû−d₀|（不用
  平移定理）→ 估计误差 O(|d₀|²/R)，R=1e4λ 时 <2e-3λ，且随 R
  增大单调下降（曲率项 k|d₀|²/(2R) 预声明）。
- 原点偶极子（Eθ∝sinθ 实正、相位常数 0）→ |d|<1e-9λ、残差 ~1e-12。
- 单主平面切面（φ=0）：仅 (d_x,d_z) 可测（identifiable 掩码），
  d_y 最小范数置 0；(d_x,d_z) 精确恢复。
- 噪声钉：相位噪声 σ=0.05 rad → 残差 RMS≈σ（±30%），中心误差
  <0.05λ（残差语义=数据对模型的符合度）。
- 双源叠加（无单一相位中心）：残差 RMS 显著 >1e-6（1 rad 量级），
  与点源残差（~1e-12）分离——"残差=相位中心模型适配度"语义钉。
- 稳定度语义：视在相位中心随方向漂移的合成结构（Φ=k·û_z·d(θ)，
  d 从 0.2λ 漂到 0.8λ）→ spread_m >0.1λ；点源 spread <1e-9λ。
- 异常域：bool/NaN/欠定采样/非法 sign ValueError。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.phase_center import (
    estimate_phase_center,
    phase_center_stability,
)

C0 = 299792458.0
F_HZ = 10e9  # 10 GHz → λ = 3 cm
LAM = C0 / F_HZ


def _grid(n_theta: int = 61, n_phi: int = 4):
    """θ 全扇形 × 4 个 φ 切面（0/90/180/270°）的采样网格（展平）。"""
    theta = np.linspace(5.0, 175.0, n_theta)
    phis = np.array([0.0, 90.0, 180.0, 270.0])
    th = np.tile(theta, phis.size)
    ph = np.repeat(phis, theta.size)
    cuts = np.repeat(np.arange(phis.size), theta.size)
    return th, ph, cuts


def _directions(th_deg, ph_deg):
    t = np.radians(th_deg)
    p = np.radians(ph_deg)
    return np.stack([np.sin(t) * np.cos(p), np.sin(t) * np.sin(p),
                     np.cos(t)], axis=-1)


class TestSyntheticExact:
    def test_translation_theorem_exact_recovery(self):
        # 平移定理合成：phase = k·û·d0 + 2π 缠绕噪声（wrap）
        d0 = np.array([0.004, -0.007, 0.011])  # m（≈0.13λ,−0.23λ,0.37λ）
        th, ph, cuts = _grid()
        u = _directions(th, ph)
        k = 2.0 * math.pi * F_HZ / C0
        phase = k * (u @ d0)
        est = estimate_phase_center(th, ph, phase, F_HZ, cut_ids=cuts)
        assert est["center_m"] == pytest.approx(d0, rel=1e-9, abs=1e-12)
        assert est["residual_rms_rad"] < 1e-9
        assert est["identifiable"].all()

    def test_wrapped_phase_recovered_via_unwrap(self):
        # 大位移（0.9λ）→ 相位跨多圈，解缠+切面冗余未知量路径
        d0 = np.array([0.009, 0.0, 0.0])
        th, ph, cuts = _grid(n_theta=361)
        u = _directions(th, ph)
        k = 2.0 * math.pi * F_HZ / C0
        raw = k * (u @ d0)
        wrapped = (raw + math.pi) % (2.0 * math.pi) - math.pi
        est = estimate_phase_center(th, ph, wrapped, F_HZ, cut_ids=cuts)
        assert est["center_m"] == pytest.approx(d0, rel=1e-6, abs=1e-9)

    def test_sign_convention_flip(self):
        # sign=-1（e^{+jkr} 约定）：Φ = c − k·û·d0 → center 不变
        d0 = np.array([0.0, 0.005, -0.003])
        th, ph, cuts = _grid()
        u = _directions(th, ph)
        k = 2.0 * math.pi * F_HZ / C0
        phase = -k * (u @ d0)
        est = estimate_phase_center(th, ph, phase, F_HZ, cut_ids=cuts,
                                    sign=-1.0)
        assert est["center_m"] == pytest.approx(d0, rel=1e-9, abs=1e-12)


class TestIndependentPhysicalPath:
    def test_point_source_true_path_phase(self):
        # 独立路径：相位=−k|Rû−d0|（真实路径长，不用平移定理）
        d0 = np.array([0.0, 0.0, LAM])  # 1λ 轴向
        r_sphere = 1e4 * LAM
        th, ph, cuts = _grid(n_theta=181)
        u = _directions(th, ph)
        k = 2.0 * math.pi * F_HZ / C0
        dist = np.linalg.norm(r_sphere * u - d0, axis=1)
        phase = -k * dist
        est = estimate_phase_center(th, ph, phase, F_HZ, cut_ids=cuts)
        err = float(np.linalg.norm(est["center_m"] - d0))
        # 曲率项量级 k·|d0|²/(2R) → 位置误差 ~|d0|²/(2R) = 5e-5 λ
        assert err < 2e-3 * LAM

    def test_convergence_with_radius(self):
        # 误差随 R 单调下降（O(1/R) 曲率收敛，预声明）
        d0 = np.array([LAM * 0.5, 0.0, LAM * 0.5])
        th, ph, cuts = _grid(n_theta=181)
        u = _directions(th, ph)
        k = 2.0 * math.pi * F_HZ / C0
        errs = []
        for r_mult in (1e2, 1e3, 1e4):
            r_sphere = r_mult * LAM
            dist = np.linalg.norm(r_sphere * u - d0, axis=1)
            est = estimate_phase_center(th, ph, -k * dist, F_HZ,
                                        cut_ids=cuts)
            errs.append(float(np.linalg.norm(est["center_m"] - d0)))
        assert errs[2] < errs[1] < errs[0]
        assert errs[2] < 5e-3 * LAM


class TestClosedFormAnchors:
    def test_dipole_at_origin_zero_center(self):
        # 偶极子在原点：Eθ∝sinθ（θ∈(0,π) 非负实）→ 相位常数 0
        th, ph, cuts = _grid()
        phase = np.zeros_like(th)
        est = estimate_phase_center(th, ph, phase, F_HZ, cut_ids=cuts)
        assert float(np.linalg.norm(est["center_m"])) < 1e-9
        assert est["residual_rms_rad"] < 1e-9

    def test_single_principal_plane_cut(self):
        # φ=0 单切面：仅 x/z 可测，y 置 0（最小范数）
        d0 = np.array([0.006, 0.012, -0.008])  # d_y 不可测
        theta = np.linspace(5.0, 175.0, 171)
        u = _directions(theta, np.zeros_like(theta))
        k = 2.0 * math.pi * F_HZ / C0
        phase = k * (u @ d0)
        est = estimate_phase_center(theta, np.zeros_like(theta), phase, F_HZ)
        assert est["n_cuts"] == 1
        assert list(est["identifiable"]) == [True, False, True]
        assert est["center_m"][1] == pytest.approx(0.0, abs=1e-15)
        assert est["center_m"][0] == pytest.approx(d0[0], rel=1e-9)
        assert est["center_m"][2] == pytest.approx(d0[2], rel=1e-9)

    def test_amplitude_weights_noise_semantics(self):
        # 相位噪声 σ=0.05 rad：残差 RMS≈σ（±30%），中心误差 <0.05λ
        rng = np.random.default_rng(42)
        d0 = np.array([0.002, -0.003, 0.004])
        th, ph, cuts = _grid(n_theta=181)
        u = _directions(th, ph)
        k = 2.0 * math.pi * F_HZ / C0
        phase = k * (u @ d0) + rng.normal(0.0, 0.05, th.size)
        est = estimate_phase_center(th, ph, phase, F_HZ, cut_ids=cuts)
        assert est["residual_rms_rad"] == pytest.approx(0.05, rel=0.30)
        err = float(np.linalg.norm(est["center_m"] - d0))
        assert err < 0.05 * LAM


class TestNoSinglePhaseCenter:
    def test_two_source_interference_residual(self):
        # 双源叠加（不等幅，无单一相位中心）→ 残差 ≫ 点源级
        th, ph, cuts = _grid(n_theta=181)
        u = _directions(th, ph)
        r_sphere = 1e4 * LAM
        k = 2.0 * math.pi * F_HZ / C0
        d1 = np.array([0.75 * LAM, 0.0, 0.0])
        d2 = np.array([-0.75 * LAM, 0.0, 0.0])
        e = (np.exp(-1j * k * np.linalg.norm(r_sphere * u - d1, axis=1))
             + 0.3 * np.exp(-1j * k * np.linalg.norm(r_sphere * u - d2,
                                                     axis=1)))
        est = estimate_phase_center(th, ph, np.angle(e), F_HZ, cut_ids=cuts)
        assert est["residual_rms_rad"] > 0.05  # 点源锚 ~1e-12，两个量级余量


class TestStabilitySemantics:
    def test_point_source_stable(self):
        th, ph, cuts = _grid(n_theta=181)
        phase = np.zeros_like(th)
        st = phase_center_stability(th, ph, phase, F_HZ, cut_ids=cuts)
        assert st["n_valid_windows"] >= 3
        assert st["spread_m"] is not None and st["spread_m"] < 1e-9

    def test_drifting_apparent_center_flagged(self):
        # 视在中心随方向漂移的合成结构：Φ=k·û_z·d(θ)，d 从 0.2λ 漂到
        # 0.8λ。窗口加大 → 单中心模型残差单调变差（结构级语义钉）；
        # 窗间中心散布显著（spread>0.3λ，点源锚 <1e-9λ）。
        th, ph, cuts = _grid(n_theta=181)
        u = _directions(th, ph)
        k = 2.0 * math.pi * F_HZ / C0
        drift = LAM * (0.2 + 0.6 * th / 175.0)
        phase = k * u[:, 2] * drift
        st = phase_center_stability(
            th, ph, phase, F_HZ, cut_ids=cuts,
            cone_half_angles_deg=(30.0, 60.0, 90.0))
        assert st["spread_m"] is not None and st["spread_m"] > 0.3 * LAM
        res = [w["residual_rms_rad"] for w in st["windows"]]
        assert res[0] < res[1] < res[2]
        # 小窗残差仍低（窗内近似单中心），大窗显著恶化
        assert res[0] < 0.05 and res[2] > 0.1

    def test_insufficient_window_reported_invalid(self):
        th, ph, cuts = _grid(n_theta=181)
        st = phase_center_stability(
            th, ph, np.zeros_like(th), F_HZ, cut_ids=cuts,
            cone_half_angles_deg=(0.001, 90.0))
        assert st["windows"][0]["valid"] is False
        assert st["windows"][1]["valid"] is True


class TestValidation:
    def test_bool_and_nan_rejected(self):
        th, ph, cuts = _grid()
        with pytest.raises(ValueError):
            estimate_phase_center(th, ph, np.zeros_like(th), True)
        bad = np.zeros_like(th)
        bad[3] = np.nan
        with pytest.raises(ValueError):
            estimate_phase_center(th, ph, bad, F_HZ, cut_ids=cuts)
        with pytest.raises(ValueError):
            estimate_phase_center(th, ph, np.zeros_like(th), F_HZ,
                                  sign=2.0)

    def test_undersampled_design_rejected(self):
        # 6 样本 × 4 切面 → 设计列数 7 > 样本数 → 欠定显式拒绝
        theta = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
        phi = np.tile(np.array([0.0, 90.0, 180.0, 270.0]), 2)[:6]
        cuts = np.arange(6) % 4
        with pytest.raises(ValueError, match="欠定"):
            estimate_phase_center(theta, phi, np.zeros_like(theta), F_HZ,
                                  cut_ids=cuts)

    def test_shape_mismatch_rejected(self):
        th, ph, _cuts = _grid()
        with pytest.raises(ValueError):
            estimate_phase_center(th, ph[:-1], np.zeros_like(th), F_HZ)
