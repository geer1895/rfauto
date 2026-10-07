"""MS-6 SWE 球面波展开 + 一阶探头修正测试（round15 MS-6 落地面）。

验证链（#118/#300：独立锚 ≥2）：
1. 系数往返：合成模场 → 展开 → 系数逐位回收（GL×均匀网格精确求积）；
2. 半径无关性：出射场系数在两个采样球上反演同值（径向函数正确性）；
3. 远场渐近：大 kr 近场 × kr·e^{jkr} 收敛到远场式（TE/TM 相对相位闭式）；
4. 物理锚：z 向 Hertzian 偶极子 = 纯 TM(l=1,m=0)（其余模能量 ≤1e-12）；
5. 探头修正：cos^q 探头正模型 → 修正回收（有效域 ≤1e-12）+ 掠射 NaN。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.nf_transform import (
    first_order_probe_correction,
    first_order_probe_response,
    spherical_wave_expansion,
    swe_far_field,
    swe_synthesize_magnetic,
    swe_synthesize_nearfield,
)


def _gl_grid(l_max: int) -> tuple[np.ndarray, np.ndarray]:
    """Gauss–Legendre(cosθ)×均匀 φ 网格（球面积分对 l≤2N−1 精确）。"""
    x, _w = np.polynomial.legendre.leggauss(l_max + 2)
    theta = np.rad2deg(np.arccos(x))
    phi = np.rad2deg(np.linspace(0.0, 360.0, 2 * (2 * l_max + 1) + 1,
                                 endpoint=False))
    return theta, phi


def _synthetic_modes(l_max: int, seed: int) -> tuple[np.ndarray, np.ndarray,
                                                     np.ndarray, np.ndarray]:
    """确定性合成模系数（固定 seed；谱随 l 衰减避免病态）。"""
    rng = np.random.default_rng(seed)
    mode_l, mode_m = [], []
    for ell in range(1, l_max + 1):
        for m in range(-ell, ell + 1):
            mode_l.append(ell)
            mode_m.append(m)
    mode_l = np.asarray(mode_l)
    mode_m = np.asarray(mode_m)
    scale = 1.0 / (1.0 + mode_l.astype(float))
    a_te = (rng.standard_normal(mode_l.size)
            + 1j * rng.standard_normal(mode_l.size)) * scale
    b_tm = (rng.standard_normal(mode_l.size)
            + 1j * rng.standard_normal(mode_l.size)) * scale
    return a_te, b_tm, mode_l, mode_m


def _pack(a_te: np.ndarray, b_tm: np.ndarray, mode_l: np.ndarray,
          mode_m: np.ndarray, k: float, r: float) -> dict:
    return {"mode_l": mode_l, "mode_m": mode_m, "a_te": a_te, "b_tm": b_tm,
            "k_rad_m": k, "r_ref_m": r}


def test_swe_coefficient_roundtrip_exact() -> None:
    """系数往返（Kerns E+H 唯一化）：合成场 → 反演 → 系数回收（≤1e-10）。"""
    l_max, k, r = 6, 12.0, 1.0
    a_te, b_tm, mode_l, mode_m = _synthetic_modes(l_max, 20261003)
    theta, phi = _gl_grid(l_max)
    swe_src = _pack(a_te, b_tm, mode_l, mode_m, k, r)
    ef = swe_synthesize_nearfield(swe_src, theta, phi, r_ref_m=r)
    hf = swe_synthesize_magnetic(swe_src, theta, phi, r_ref_m=r)
    out = spherical_wave_expansion(
        ef["e_theta"], ef["e_phi"], theta, phi, l_max, r, k_rad_m=k,
        h_theta=hf["h_theta"], h_phi=hf["h_phi"])
    assert out["ok"]
    assert out["te_tm_split"] == "kerns_eh"
    assert out["residual_rms"] <= 1e-10
    np.testing.assert_allclose(out["a_te"], a_te, rtol=0, atol=1e-10)
    np.testing.assert_allclose(out["b_tm"], b_tm, rtol=0, atol=1e-10)
    # 场级往返独立核验（重构场 = 输入场）
    refit = swe_synthesize_nearfield(out, theta, phi, r_ref_m=r)
    np.testing.assert_allclose(refit["e_theta"], ef["e_theta"], atol=1e-9)


def test_swe_e_only_min_norm_field_roundtrip() -> None:
    """E-only 路径（诚实口径）：场级往返成立；系数级只对 TE/TM 混合量。

    预声明：单球 E-only 欠定（X/Z 两族各自完备），系数回收钉不了——
    本测试只钉（1）拟合残差小、（2）重构场与输入一致、（3）标记如实。
    """
    l_max, k, r = 5, 12.0, 1.0
    a_te, b_tm, mode_l, mode_m = _synthetic_modes(l_max, 42)
    theta, phi = _gl_grid(l_max)
    src = _pack(a_te, b_tm, mode_l, mode_m, k, r)
    ef = swe_synthesize_nearfield(src, theta, phi, r_ref_m=r)
    out = spherical_wave_expansion(
        ef["e_theta"], ef["e_phi"], theta, phi, l_max, r, k_rad_m=k)
    assert out["te_tm_split"] == "e_only_min_norm"
    assert out["residual_rms"] <= 1e-9
    refit = swe_synthesize_nearfield(out, theta, phi, r_ref_m=r)
    np.testing.assert_allclose(refit["e_theta"], ef["e_theta"], rtol=0,
                               atol=1e-9)
    np.testing.assert_allclose(refit["e_phi"], ef["e_phi"], rtol=0, atol=1e-9)


def test_swe_h_missing_half_rejected() -> None:
    """只给 H 之一 → 显式拒绝（Kerns 路径要求成对）。"""
    theta = np.array([30.0, 60.0])
    e = np.ones(2, dtype=complex)
    with pytest.raises(ValueError, match="同时给入"):
        spherical_wave_expansion(e, e, theta, theta, 3, 1.0, k_rad_m=9.0,
                                 h_theta=e)


def test_swe_radius_independence_of_outgoing_coefficients() -> None:
    """出射场系数与采样球半径无关：r=0.8 与 r=1.5 两球反演同值（≤1e-8）。"""
    l_max, k = 6, 14.0
    a_te, b_tm, mode_l, mode_m = _synthetic_modes(l_max, 77)
    theta, phi = _gl_grid(l_max)
    src = _pack(a_te, b_tm, mode_l, mode_m, k, 1.0)
    ef1 = swe_synthesize_nearfield(src, theta, phi, r_ref_m=0.8)
    hf1 = swe_synthesize_magnetic(src, theta, phi, r_ref_m=0.8)
    out_r1 = spherical_wave_expansion(
        ef1["e_theta"], ef1["e_phi"], theta, phi, l_max, 0.8, k_rad_m=k,
        h_theta=hf1["h_theta"], h_phi=hf1["h_phi"])
    ef2 = swe_synthesize_nearfield(src, theta, phi, r_ref_m=1.5)
    hf2 = swe_synthesize_magnetic(src, theta, phi, r_ref_m=1.5)
    out_r2 = spherical_wave_expansion(
        ef2["e_theta"], ef2["e_phi"], theta, phi, l_max, 1.5, k_rad_m=k,
        h_theta=hf2["h_theta"], h_phi=hf2["h_phi"])
    np.testing.assert_allclose(out_r1["a_te"], a_te, rtol=0, atol=1e-8)
    np.testing.assert_allclose(out_r2["a_te"], a_te, rtol=0, atol=1e-8)
    np.testing.assert_allclose(out_r2["b_tm"], b_tm, rtol=0, atol=1e-8)


def test_swe_farfield_asymptotic_convergence() -> None:
    """大 kr 近场外推收敛到远场式：误差 O(1/kr)，翻倍 kr 误差减半量级。"""

    def rel_err(kr_big: float) -> float:
        l_max = 6
        a_te, b_tm, mode_l, mode_m = _synthetic_modes(l_max, 5)
        theta, phi = _gl_grid(l_max)
        src = _pack(a_te, b_tm, mode_l, mode_m, 1.0, 1.0)
        ef = swe_synthesize_nearfield(src, theta, phi, r_ref_m=kr_big)
        # 渐近关系：E_near ≈ e^{-jkr}/kr · E_ff（切向两分量同标度）
        scaled_th = ef["e_theta"] * kr_big * np.exp(1j * kr_big)
        scaled_ph = ef["e_phi"] * kr_big * np.exp(1j * kr_big)
        ff = swe_far_field(src, theta, phi)
        num = np.linalg.norm(scaled_th - ff["e_theta"]) ** 2 \
            + np.linalg.norm(scaled_ph - ff["e_phi"]) ** 2
        den = np.linalg.norm(ff["e_theta"]) ** 2 \
            + np.linalg.norm(ff["e_phi"]) ** 2
        return float(np.sqrt(num / den))

    e1 = rel_err(900.0)
    e2 = rel_err(1800.0)
    # 渐近首修 O(l(l+1)/2kr)：l_max=6 → kr=900 时 ~2e-3 量级，门留余量
    assert e1 <= 2e-2, f"kr=900 渐近相对误差 {e1:.2e} 超门"
    assert e2 < e1, f"加密未收敛：kr=1800 误差 {e2:.2e} 不小于 {e1:.2e}"


def test_swe_hertzian_dipole_pure_tm10() -> None:
    """物理锚（Balanis 闭式双源）：Hertzian 偶极子全场 = 纯 TM(l=1,m=0)。

    独立出处（不经过本模块合成链）：z 向 Hertzian 偶极子精确场（Balanis
    Ch.4 口径，e^{+jωt}、e^{−jkr}）：E_θ=Cη sinθ(1+1/(jkr)−1/(kr)²)e^{−jkr}/r、
    H_φ=C sinθ(1+1/(jkr))e^{−jkr}/r——本模块合成路径与该闭式逐角比值恒定
    （1e-15 级，开工数值验证）；此处直接用闭式作反演输入。
    """
    k, r = 10.0, 1.0
    kr = k * r
    theta, phi = _gl_grid(8)
    t2, _p2 = np.meshgrid(np.deg2rad(theta), np.deg2rad(phi), indexing="ij")
    common = np.exp(-1j * kr) / r
    # Balanis E_θ 含物理 η 因子（E_θ = jηkIl/(4πr)·sinθ·(...)——漏掉 η 会使
    # 数据 E/H≈1 违反 Maxwell（H/E=1/η），反演必不一致（实测残差 ~1.0）
    eta = 376.730313668
    e_th = eta * np.sin(t2) * (1.0 + 1.0 / (1j * kr) - 1.0 / kr ** 2) * common
    h_ph = np.sin(t2) * (1.0 + 1.0 / (1j * kr)) * common
    out = spherical_wave_expansion(
        e_th, np.zeros_like(t2), theta, phi, 8, r, k_rad_m=k,
        h_theta=np.zeros_like(t2), h_phi=h_ph)
    assert out["residual_rms"] <= 1e-12
    # 全部能量在 l=1，且 TE(1,0) 为零、TM(1,0) 独占
    assert out["energy_per_l"][0] >= 0.999 * out["energy_total"]
    idx = {int(ell): [] for ell in range(1, 9)}
    for i, (ell, _m) in enumerate(zip(out["mode_l"], out["mode_m"],
                                      strict=True)):
        idx[int(ell)].append(i)
    te10 = abs(out["a_te"][idx[1][list(out["mode_m"][idx[1]]).index(0)]])
    assert te10 <= 1e-10, f"TE(1,0) 应为零，实际 {te10:.2e}"
    other = [abs(out["b_tm"][i]) for i, (ell, m) in
             enumerate(zip(out["mode_l"], out["mode_m"], strict=True))
             if not (ell == 1 and m == 0)]
    assert max(other) <= 1e-10, f"非 TM(1,0) 模泄漏 {max(other):.2e}"


def test_probe_correction_roundtrip_and_grazing_nan() -> None:
    """一阶探头修正：正模型 → 修正回收（有效域 ≤1e-12）；掠射区如实 NaN。"""
    l_max, k, r = 5, 12.0, 1.0
    a_te, b_tm, mode_l, mode_m = _synthetic_modes(l_max, 1234)
    theta, phi = _gl_grid(l_max)
    src = _pack(a_te, b_tm, mode_l, mode_m, k, r)
    ef = swe_synthesize_nearfield(src, theta, phi, r_ref_m=r)
    u0, u90 = first_order_probe_response(
        ef["e_theta"], ef["e_phi"], theta, probe_q=1.0)
    corr = first_order_probe_correction(u0, u90, theta, probe_q=1.0)
    assert corr["ok"]
    # GL 网格覆盖全球面，cosθ<floor 的掠射区按掩码如实失效
    expect_valid = np.cos(np.deg2rad(theta)) >= 0.1
    np.testing.assert_array_equal(
        corr["valid_mask"],
        np.broadcast_to(expect_valid[:, None], corr["valid_mask"].shape))
    np.testing.assert_allclose(corr["e_theta"][expect_valid],
                               ef["e_theta"][expect_valid], rtol=0, atol=1e-12)
    np.testing.assert_allclose(corr["e_phi"][expect_valid],
                               ef["e_phi"][expect_valid], rtol=0, atol=1e-12)
    assert np.all(np.isnan(corr["e_theta"][~expect_valid]))
    # 掠射守卫：θ 接近 90° 时 c=floor 以下 → NaN + 计数
    th_wide = np.array([10.0, 45.0, 88.0, 89.5])
    corr2 = first_order_probe_correction(
        np.ones(4, dtype=complex), np.ones(4, dtype=complex), th_wide,
        probe_q=1.0, floor=0.1)
    assert corr2["invalid_fraction"] == pytest.approx(0.5)
    assert np.isnan(corr2["e_theta"][-1])
    assert np.isfinite(corr2["e_theta"][0])


def test_swe_input_guards() -> None:
    """守卫：极点采样 / 双频率入参 / kr 过近 / 形状不匹配 → 显式拒绝。"""
    theta = np.array([0.0, 45.0, 90.0])
    phi = np.array([0.0, 120.0, 240.0])
    e = np.ones(3, dtype=complex)
    with pytest.raises(ValueError, match="极点"):
        spherical_wave_expansion(e, e, theta, phi, 4, 1.0, k_rad_m=10.0)
    th_ok = np.array([30.0, 60.0, 90.0])
    with pytest.raises(ValueError, match="恰须给其一"):
        spherical_wave_expansion(e, e, th_ok, phi, 4, 1.0)
    with pytest.raises(ValueError, match="恰须给其一"):
        spherical_wave_expansion(e, e, th_ok, phi, 4, 1.0,
                                 freq_hz=1e9, k_rad_m=10.0)
    with pytest.raises(ValueError, match="辐射区"):
        spherical_wave_expansion(e, e, th_ok, phi, 8, 1.0, k_rad_m=1.0)
    with pytest.raises(ValueError, match="形状须一致"):
        spherical_wave_expansion(e, e, th_ok, phi[:2], 4, 1.0, k_rad_m=10.0)
