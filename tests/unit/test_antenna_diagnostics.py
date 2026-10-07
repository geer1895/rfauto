"""DG-1 天线诊断反演核测试（round19 P1：对偶注入验证，#340 合成回收钉）。

验收链（席6 任务书钉）：注入已知误差 → 远场幅相正变换 → IFFT 对偶反演 →
单元级定位对拍 + 残差门。注入器 = array_error_injection（正向对偶）。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.antenna_diagnostics import (
    aperture_to_far_field,
    build_diagnostic_report,
    diagnose_array_aperture,
    diagnose_with_injected_errors,
    far_field_to_aperture,
)

_F_HZ = 10.0e9
_D_PITCH = 0.03  # 0.03 m = λ（f=10 GHz）> λ/√2，全谱传播域


def test_farfield_aperture_roundtrip_exact() -> None:
    """正反变换往返恒等（全传播域，≤1e-12）：确定性随机场。"""
    rng = np.random.default_rng(7)
    w = (rng.standard_normal((8, 6)) + 1j * rng.standard_normal((8, 6)))
    ff = aperture_to_far_field(w, _D_PITCH, _D_PITCH, _F_HZ)
    assert ff["n_evanescent"] == 0  # λ 间距全谱传播
    inv = far_field_to_aperture(ff["sx"], None, _D_PITCH, _D_PITCH, _F_HZ)
    assert inv["n_evanescent_zeroed"] == 0
    np.testing.assert_allclose(inv["e_aperture"], w, rtol=0, atol=1e-10)


def test_sparse_faults_localized_exactly() -> None:
    """离散定点注入（2 死 + 1 增差 + 1 相差）→ 定位集合严格一致 + 残差门。"""
    w = np.ones((8, 8), dtype=complex)
    rep = diagnose_with_injected_errors(
        w, _D_PITCH, _F_HZ,
        dead_elements=[(1, 1), (5, 6)],
        fault_gain_db={(2, 3): -3.0},
        fault_phase_deg={(6, 2): 25.0})
    assert rep["roundtrip_residual_rel"] <= 1e-12
    assert rep["error_db_recovery_residual"] <= 1e-9
    assert rep["dead_localization_match"] is True
    assert sorted(rep["dead_elements"]) == [(1, 1), (5, 6)]
    assert rep["gain_elements"] == [(2, 3)]
    assert rep["phase_elements"] == [(6, 2)]
    assert rep["verdict"] == "faulty"


def test_clean_array_diagnosed_clean() -> None:
    """无注入 → verdict=clean、零故障元（误报钉）。"""
    rng = np.random.default_rng(99)
    w = 1.0 + 0.1 * (rng.standard_normal((6, 5))
                     + 1j * rng.standard_normal((6, 5)))
    rep = diagnose_with_injected_errors(w, _D_PITCH, _F_HZ)
    assert rep["verdict"] == "clean"
    assert rep["n_faulty"] == 0
    assert rep["roundtrip_residual_rel"] <= 1e-12


def test_stochastic_errors_recovered_bitwise() -> None:
    """随机幅相分量（σ=0.5 dB/5°，固定 seed）：注入实现逐位回收（#340 钉）。"""
    w = np.ones((6, 6), dtype=complex)
    rep = diagnose_with_injected_errors(
        w, _D_PITCH, _F_HZ, rng_seed=20261003,
        gain_sigma_db=0.5, phase_sigma_deg=5.0)
    assert rep["roundtrip_residual_rel"] <= 1e-12
    assert rep["error_db_recovery_residual"] <= 1e-9
    # 误差图与注入实现逐位一致（0.5 dB σ 高斯下部分元越 ±1 dB 门 →
    # verdict=faulty 是分类器的正确行为，回收面只钉「反演=注入真值」）
    from rfauto.core.array_error_injection import inject_errors
    gains = inject_errors(36, 20261003, amp_sigma_db=0.5,
                          phase_sigma_deg=5.0)["gains"].reshape(6, 6)
    expect_db = 20.0 * np.log10(np.abs(gains) + 1e-300)
    np.testing.assert_allclose(rep["error_db_map"], expect_db, atol=1e-9)
    # 同 seed 复跑逐位一致（确定性钉）
    rep2 = diagnose_with_injected_errors(
        w, _D_PITCH, _F_HZ, rng_seed=20261003,
        gain_sigma_db=0.5, phase_sigma_deg=5.0)
    np.testing.assert_array_equal(rep["error_db_map"], rep2["error_db_map"])


def test_pitch_guard_rejects_subhalfwave() -> None:
    """有效域守卫：间距 ≤ λ/2 与 ≤ λ/√2 显式拒绝（不虚报单元级反演）。"""
    w = np.ones((4, 4), dtype=complex)
    with pytest.raises(ValueError, match="λ/2"):
        diagnose_with_injected_errors(w, 0.012, _F_HZ)  # 0.4λ
    # 0.021 m = 0.70λ 落在 (λ/2, λ/√2] 渐逝区间 → 拒绝
    with pytest.raises(ValueError, match="λ/√2"):
        diagnose_with_injected_errors(w, 0.021, _F_HZ)
    # 0.022 m = 0.733λ > λ/√2 → 全传播域，通过
    ok = diagnose_with_injected_errors(w, 0.022, _F_HZ)
    assert ok["pitch_over_lambda"] == pytest.approx(0.7333, abs=1e-3)
    assert ok["roundtrip_residual_rel"] <= 1e-12


def test_reference_zero_elements_excluded_from_faults() -> None:
    """参考零权重元（理想死元）不参与故障判定；实测复权仍死 → healthy。"""
    w = np.ones((4, 4), dtype=complex)
    w[2, 2] = 0.0  # 理想死元
    rep = diagnose_with_injected_errors(w, _D_PITCH, _F_HZ)
    assert rep["verdict"] == "clean"


def test_diagnose_input_guards_and_reporter() -> None:
    """形状不一致/非法门值守卫 + 结构化报告器字段。"""
    with pytest.raises(ValueError, match="形状须一致"):
        diagnose_array_aperture(np.ones((4, 4), complex),
                                np.ones((4, 5), complex))
    with pytest.raises(ValueError, match="dead_floor"):
        diagnose_array_aperture(np.ones((4, 4), complex),
                                np.ones((4, 4), complex), dead_floor=1.5)
    rep = diagnose_with_injected_errors(
        np.ones((6, 6), dtype=complex), _D_PITCH, _F_HZ,
        dead_elements=[(0, 5)])
    report = build_diagnostic_report(rep)
    assert report["verdict"] == "faulty"
    assert report["dead_elements"] == [(0, 5)]
    assert report["worst_error_db"] is not None
    assert report["gates"]["gain_tol_db"] == 1.0
    assert report["dead_localization_match"] is True
