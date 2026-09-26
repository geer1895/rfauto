"""DP-4 P1 阵列扫描内核单测（core/array_scan.py，J2/J3 全合成判据）。

裁判=独立解析/闭式/独立解法器（runs/df6_dp4af/criteria.md 预声明）：
- J2a Γ_act 定义式逐位（显式循环对照 S@a/a）；
- J2b 无耗互易（幺正 S）功率守恒 Σ|b|²=Σ|a|²；
- J2c Z↔Γ 往返 ≤1e-12；
- J2d 表面波色散方程：残差/导波界/物理单位 β 域二分独立解法器对拍/TE1
  截止公式与存在性/物理单调性；
- J3a EEP 位置相位记账钉（position_phase+eep_superposition vs 方向图积定理）；
- J3b 盲点合成例（相位匹配阶打界 + Γ 准则 + 离开匹配角零误报）；
- J3c farfield3d_cplx.csv round-trip + 向前兼容 + 缺列显式报错；
- J1c（core 层）tier_gate 四边界：栅瓣打界/间距/扫描/耦合。
全部确定性、无网络、无真机。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.array_scan import (
    C_M_S,
    active_reflection,
    blind_spot_screen,
    eep_superposition,
    position_phase,
    reflection_from_impedance,
    scan_impedance,
    surface_wave_beta,
    surface_wave_modes,
    tier_gate,
)
from rfauto.core.array_synthesis import (
    array_factor,
    half_wave_dipole_field,
    pattern_multiplication,
    uniform_weights,
)
from rfauto.core.farfield import (
    parse_farfield_3d_cplx_csv,
    parse_farfield_3d_csv,
    write_farfield_3d_cplx_csv,
)

F_0 = 10e9


def _synthetic_s_matrix() -> np.ndarray:
    """4×4 近邻耦合注入的互易 S（对角 0.2−0.1j、近邻 0.15+0.02j、次近邻 0.03）。"""
    s = np.zeros((4, 4), dtype=complex)
    np.fill_diagonal(s, 0.2 - 0.1j)
    for i in range(3):
        s[i, i + 1] = s[i + 1, i] = 0.15 + 0.02j
    s[0, 3] = s[3, 0] = 0.03
    return s


# ─── J2a：Γ_act 定义式逐位 ───────────────────────────────────────────────────

def test_j2a_active_reflection_matches_definition():
    rng = np.random.default_rng(20260924)
    s = _synthetic_s_matrix()
    a = rng.normal(size=4) + 1j * rng.normal(size=4)
    gamma = active_reflection(s, a)
    ref = np.asarray([
        sum(s[n, m] * a[m] for m in range(4)) / a[n] for n in range(4)
    ], dtype=complex)
    assert np.allclose(gamma, ref, rtol=1e-14, atol=1e-18)
    # 无耦合列 → Γ_act 退化为对角元（解析极限）
    diag_only = np.diag(np.diag(s))
    assert np.allclose(active_reflection(diag_only, a), np.diag(s), atol=1e-15)


def test_j2a_active_reflection_rejects_bad_inputs():
    s = _synthetic_s_matrix()
    with pytest.raises(ValueError, match="方阵"):
        active_reflection(s[:3], np.ones(3, dtype=complex))
    with pytest.raises(ValueError, match="近零分量"):
        active_reflection(s, np.array([1, 1, 0, 1], dtype=complex))
    with pytest.raises(ValueError, match="非有限"):
        active_reflection(s, np.array([1, 1, np.nan, 1], dtype=complex))


# ─── J2b：无耗互易功率守恒 ───────────────────────────────────────────────────

def test_j2b_unitary_power_conservation():
    rng = np.random.default_rng(42)
    a_rand = rng.normal(size=(8, 8)) + 1j * rng.normal(size=(8, 8))
    s_unitary, _ = np.linalg.qr(a_rand)  # 无耗互易的合成代表（幺正）
    assert np.allclose(s_unitary.conj().T @ s_unitary, np.eye(8), atol=1e-12)
    for seed in range(3):
        rng2 = np.random.default_rng(seed)
        a = rng2.normal(size=8) + 1j * rng2.normal(size=8)
        b = s_unitary @ a
        pa = float(np.sum(np.abs(a) ** 2))
        pb = float(np.sum(np.abs(b) ** 2))
        assert abs(pb - pa) / pa <= 1e-12


# ─── J2c：Z↔Γ 往返 ──────────────────────────────────────────────────────────

def test_j2c_impedance_reflection_round_trip():
    rng = np.random.default_rng(7)
    raw = rng.normal(100) + 1j * rng.normal(100)
    gamma = 0.98 * raw / np.abs(raw)
    z0 = 50.0
    z = scan_impedance(gamma, z0)
    gamma2 = reflection_from_impedance(z, z0)
    assert float(np.max(np.abs(gamma - gamma2))) <= 1e-12
    # 物理锚：Γ=0 → Z=Z0；Γ=−1（短路面）→ Z=0
    assert complex(scan_impedance(np.asarray(0.0), z0)) == pytest.approx(z0)
    assert abs(complex(scan_impedance(np.asarray(-1.0), z0))) <= 1e-12
    # 盲点深反射（Γ→1）→ 退化复无穷（如实标注不虚构有限值）
    z_degen = complex(scan_impedance(np.asarray(1.0), z0))
    assert not np.isfinite(z_degen)


# ─── J2d：表面波色散超越方程 ─────────────────────────────────────────────────

def _bisect_beta(f, lo: float, hi: float, iters: int = 300) -> float:
    """物理单位 β 域独立二分法（与 core 的 u 域 safeguarded Newton 互为独立）。"""
    flo = f(lo)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if flo * fm <= 0.0:
            hi = mid
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


def _tm0_residual_beta(beta, freq, h, er):
    k0 = 2.0 * np.pi * freq / C_M_S
    kd = np.sqrt(er * k0 * k0 - beta * beta)
    alpha = np.sqrt(beta * beta - k0 * k0)
    return kd * np.tan(kd * h) - er * alpha


def _te1_residual_beta(beta, freq, h, er):
    k0 = 2.0 * np.pi * freq / C_M_S
    kd = np.sqrt(er * k0 * k0 - beta * beta)
    alpha = np.sqrt(beta * beta - k0 * k0)
    return kd / np.tan(kd * h) + alpha


@pytest.mark.parametrize("freq,h,er,mode,res_fn", [
    (10e9, 1.575e-3, 2.2, "TM0", _tm0_residual_beta),   # R=0.361<π/2
    (3e9, 3e-3, 12.0, "TM0", _tm0_residual_beta),        # R=0.625<π/2
    (10e9, 3e-3, 12.0, "TE1", _te1_residual_beta),       # R=2.084∈(π/2,π)
])
def test_j2d_surface_wave_matches_independent_bisection(freq, h, er, mode, res_fn):
    info = surface_wave_beta(freq, h, er, mode=mode)
    assert info["exists"]
    k0 = info["k0_rad_per_m"]
    # 残差（无量纲归一方程）与导波界 k0 < β < k0·√εr
    assert info["residual"] <= 1e-12
    assert k0 < info["beta_rad_per_m"] < k0 * np.sqrt(er)
    assert info["beta_over_k0"] == pytest.approx(info["beta_rad_per_m"] / k0)
    # 独立裁判：β 域二分法（同一方程的物理单位表达）
    eps = 1e-10
    bis = _bisect_beta(lambda b: res_fn(b, freq, h, er),
                       k0 * (1 + eps), k0 * np.sqrt(er) * (1 - eps))
    assert info["beta_rad_per_m"] == pytest.approx(bis, rel=1e-10)


def test_j2d_te1_existence_and_cutoff_formula():
    # TE1 截止 f_c = c/(4h√(εr−1))
    h, er = 3e-3, 12.0
    fc = C_M_S / (4.0 * h * np.sqrt(er - 1.0))
    below = surface_wave_beta(0.7 * fc, h, er, mode="TE1")
    above = surface_wave_beta(1.3 * fc, h, er, mode="TE1")
    assert below["exists"] is False and below["beta_rad_per_m"] is None
    assert below["cutoff_hz"] == pytest.approx(fc, rel=1e-15)
    assert above["exists"]
    # 薄低 εr 基片：10GHz@1.575mm/2.2 → TE1 不存在（fc≈43.4GHz）
    thin = surface_wave_beta(10e9, 1.575e-3, 2.2, mode="TE1")
    assert thin["exists"] is False
    assert thin["cutoff_hz"] == pytest.approx(43.44e9, rel=0.01)
    # TM0 恒存在（无截止）
    tm0 = surface_wave_beta(1e6, 1e-4, 2.2, mode="TM0")
    assert tm0["exists"] and tm0["cutoff_hz"] == 0.0
    # 物理单调性：增厚/增 εr → β_sw/k0 增（束缚更强）
    r_thin = surface_wave_beta(10e9, 0.5e-3, 2.2)["beta_over_k0"]
    r_thick = surface_wave_beta(10e9, 3e-3, 2.2)["beta_over_k0"]
    assert r_thin < r_thick < np.sqrt(2.2)
    assert surface_wave_beta(10e9, 1.575e-3, 2.2)["beta_over_k0"] \
        < surface_wave_beta(10e9, 1.575e-3, 4.4)["beta_over_k0"]
    # surface_wave_modes 只保留存在模式
    modes = surface_wave_modes(10e9, 1.575e-3, 2.2)
    assert [m["mode"] for m in modes] == ["TM0"]
    modes_hi = surface_wave_modes(10e9, 3e-3, 12.0)
    assert [m["mode"] for m in modes_hi] == ["TM0", "TE1"]


def test_j2d_surface_wave_input_validation():
    with pytest.raises(ValueError, match="eps_r"):
        surface_wave_beta(10e9, 1e-3, 1.0, mode="TM0")
    with pytest.raises(ValueError, match="mode"):
        surface_wave_beta(10e9, 1e-3, 2.2, mode="TM2")
    with pytest.raises(ValueError, match="freq_hz"):
        surface_wave_beta(-1.0, 1e-3, 2.2)


# ─── J3a：EEP 位置相位记账钉 ────────────────────────────────────────────────

def test_j3a_eep_superposition_equals_pattern_multiplication():
    """合成 EEP=闭式单元×位置相位：叠加 vs 方向图积定理（无耦极限）逐点一致。

    两条独立相位记账链：k0=2πf/c 物理单位（position_phase）vs
    2π(d/λ)(u−u0)n 无量纲（array_factor）——判据 ≤1e-12（浮点界）。
    """
    freq = 10e9
    lam0 = C_M_S / freq
    n_elem, dx = 4, 0.5 * lam0
    positions = np.stack([np.arange(n_elem) * dx, np.zeros(n_elem),
                          np.zeros(n_elem)], axis=1)
    theta = np.linspace(0.0, 180.0, 91)
    phi = np.linspace(0.0, 360.0, 73)
    th2, ph2 = np.meshgrid(theta, phi, indexing="ij")
    # 闭式单元（半波振子，z 向）作公共因子
    elem = np.asarray(half_wave_dipole_field(th2), dtype=float)
    # EEP_n = E_elem × 位置相位（nf2ff 全局原点口径）
    phase = position_phase(positions, th2, ph2, freq)
    eeps = elem[None, :, :] * phase
    # 扫描激励：θ0=30°、φ0=0 → u0=sin30°=0.5（幅度均匀）
    u0 = np.sin(np.radians(30.0))
    a = np.exp(-1j * 2.0 * np.pi * freq / C_M_S * positions[:, 0] * u0)
    f_super = eep_superposition(eeps, a)
    # 参照：方向图积定理（同一单元 × 无量纲 AF）
    u = np.sin(np.radians(th2)) * np.cos(np.radians(ph2))
    af = array_factor(u, uniform_weights(n_elem), spacing_lambda=dx / lam0,
                      scan_direction_cosine=u0, normalize=False)
    f_ref = pattern_multiplication(elem, af)
    scale = float(np.max(np.abs(f_ref)))
    assert scale > 0.0
    assert float(np.max(np.abs(f_super - f_ref))) / scale <= 1e-12


# ─── J3b：盲点合成例 ────────────────────────────────────────────────────────

def test_j3b_blind_spot_surface_wave_phase_match_hit():
    # dx=2λ 使 (m=+1,n=0) Floquet 阶在 θ_hit=arcsin(ρ−0.5) 恰与 TM0 匹配。
    # y 向取无周期大间距（等效一维筛查）：若给真实的 dy=λ 二维栅格，
    # (m,−1) 阶 kpar=√(kx²+k0²) 会在整段角域贴近 β_sw≈k0·ρ——那是二维栅格
    # 的真实盲点带（Pozar/McGrath 现象），不属于本例的单阶解析构造。
    info = surface_wave_beta(10e9, 1.575e-3, 2.2, mode="TM0")
    rho = info["beta_over_k0"]
    lam0 = C_M_S / 10e9
    dx = 2.0 * lam0
    dy_none = 1e6 * lam0  # 无 y 周期：n≠0 阶坍缩至 n=0
    sin_hit = rho - 0.5
    assert 0.0 < sin_hit < 1.0
    theta_hit = float(np.degrees(np.arcsin(sin_hit)))
    slab_kw = dict(slab_eps_r=2.2, slab_thickness_m=1.575e-3)
    hit = blind_spot_screen(theta_hit, 0.0, freq_hz=10e9, dx_m=dx,
                            dy_m=dy_none, **slab_kw)
    assert hit["n_blind"] == 1
    assert hit["blind"][0] is True
    assert hit["blind_by"][0] == "surface_wave"
    assert hit["nearest_order_m"][0] == 1 and hit["nearest_order_n"][0] == 0
    assert hit["nearest_mode"][0] == "TM0"
    assert hit["min_dist_over_k0"][0] < 1e-9
    # 离开匹配角 ±5°：无相位匹配、无 Γ → 零误报
    for dth in (-5.0, 5.0):
        away = blind_spot_screen(theta_hit + dth, 0.0, freq_hz=10e9,
                                 dx_m=dx, dy_m=dy_none, **slab_kw)
        assert away["blind"][0] is False
        assert away["min_dist_over_k0"][0] > 0.05
    # Γ 准则独立打旗（盲点深反射 |Γ_act|>0.8），blind_by 可分辨
    gm = blind_spot_screen(theta_hit - 20.0, 0.0, freq_hz=10e9, dx_m=dx,
                           dy_m=dy_none, gamma_act=0.9, **slab_kw)
    assert gm["blind"][0] is True and gm["blind_by"][0] == "gamma"
    # 二维广播 + 显式 β（绕开基片参数）一致性
    two = blind_spot_screen([theta_hit, theta_hit + 10.0], [0.0, 0.0],
                            freq_hz=10e9, dx_m=dx, dy_m=dy_none,
                            beta_sw_rad_per_m=info["beta_rad_per_m"])
    assert two["blind"] == [True, False]
    # 显式 β 传入无模式信息 → 标签按 beta[i] 契约
    assert two["nearest_mode"] == ["beta[0]", "beta[0]"]
    with pytest.raises(ValueError, match="beta_sw_rad_per_m 或"):
        blind_spot_screen(30.0, 0.0, freq_hz=10e9, dx_m=dx, dy_m=lam0)


# ─── J3c：3D 复数 dump 解析 ─────────────────────────────────────────────────

def test_j3c_farfield_3d_cplx_round_trip(tmp_path):
    rng = np.random.default_rng(11)
    th = np.arange(0.0, 181.0, 45.0)
    ph = np.arange(0.0, 181.0, 90.0)
    et = rng.normal(size=(th.size, ph.size)) + 1j * rng.normal(size=(th.size, ph.size))
    ep = rng.normal(size=(th.size, ph.size)) + 1j * rng.normal(size=(th.size, ph.size))
    path = tmp_path / "farfield3d_cplx.csv"
    write_farfield_3d_cplx_csv(path, th, ph, et, ep)
    th2, ph2, et2, ep2 = parse_farfield_3d_cplx_csv(path)
    assert np.array_equal(th2, th) and np.array_equal(ph2, ph)
    assert float(np.max(np.abs(et2 - et))) <= 1e-15
    assert float(np.max(np.abs(ep2 - ep))) <= 1e-15
    # 复数 nan 填充缺采样点（删除 θ=0、φ=180 的行后解析，该网格点 NaN）
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    del lines[3]  # 首个数据行块：theta_deg=0 的第 3 个 φ 采样
    partial = tmp_path / "partial.csv"
    partial.write_text("".join(lines), encoding="utf-8")
    _, _, et3, ep3 = parse_farfield_3d_cplx_csv(partial)
    assert et3.shape == (5, 3)
    assert np.isnan(et3[0, 2]) and np.isnan(ep3[0, 2])
    assert not np.isnan(et3[0, 0]) and not np.isnan(et3[-1, -1])


def test_j3c_farfield_3d_cplx_forward_compat_and_errors(tmp_path):
    path = tmp_path / "extra_col.csv"
    rows = [["theta_deg", "phi_deg", "re_e_theta", "im_e_theta",
             "re_e_phi", "im_e_phi", "future_col"]]
    rows.append([10.0, 0.0, 1.0, 2.0, 3.0, -1.0, "ignored"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    th, ph, et, ep = parse_farfield_3d_cplx_csv(path)
    assert th.tolist() == [10.0] and ph.tolist() == [0.0]
    assert et[0, 0] == complex(1.0, 2.0) and ep[0, 0] == complex(3.0, -1.0)
    # 缺必需列 → 显式报错并列出缺失列名
    bad = tmp_path / "bad.csv"
    bad.write_text("theta_deg,phi_deg,re_e_theta,re_e_phi\n1,2,3,4\n",
                   encoding="utf-8")
    with pytest.raises(ValueError, match="im_e_theta"):
        parse_farfield_3d_cplx_csv(bad)
    # 旧格式解析器零改动回归（farfield3d.csv dB 口径仍可用）
    old = tmp_path / "farfield3d.csv"
    old.write_text("theta_deg,phi_deg,e_norm_db\n0,0,0.0\n90,90,-3.0\n",
                   encoding="utf-8")
    th_old, ph_old, grid_old = parse_farfield_3d_csv(old)
    assert th_old.tolist() == [0.0, 90.0] and ph_old.tolist() == [0.0, 90.0]
    assert grid_old[0, 0] == 0.0 and grid_old[1, 1] == -3.0


# ─── J1c（core 层）：tier_gate 边界 ─────────────────────────────────────────

def test_j1c_grating_boundary_exact():
    """d = λ/(1+|u0|) 打界：内侧放行、外侧栅瓣拦截（恰值按保守计数）。"""
    u0 = float(np.sin(np.radians(45.0)))
    d_free = 1.0 / (1.0 + abs(u0))
    inside = tier_gate(d_free * (1 - 1e-6), 45.0, u0=u0)
    assert inside["tier"] == "fast" and not inside["invalid_fast_tier"]
    outside = tier_gate(d_free * (1 + 1e-6), 45.0, u0=u0)
    assert outside["tier"] == "coupled" and outside["invalid_fast_tier"]
    assert any("grating_lobe" in r for r in outside["reasons"])
    # 侧射 d/λ=0.586 介于两者：45° 扫描有瓣、侧射无瓣
    assert tier_gate(d_free, 0.0, u0=0.0)["tier"] == "fast"


def test_j1c_three_boundaries_independent_reasons():
    # 间距下界 d<0.5λ
    g1 = tier_gate(0.49, 0.0)
    assert g1["invalid_fast_tier"] and any(
        "spacing_below_min" in r for r in g1["reasons"])
    # 扫描界 |θ−broadside|>45°（恰 45 放行）
    assert tier_gate(0.5, 45.0)["tier"] == "fast"
    g2 = tier_gate(0.5, 45.1)
    assert g2["invalid_fast_tier"] and any(
        "scan_out_of_range" in r for r in g2["reasons"])
    # 耦合界：−9dB>−10dB 强耦拦截；−11dB 放行；None（无 S 数据）不阻断
    g3 = tier_gate(0.5, 0.0, coupling_db=-9.0)
    assert g3["invalid_fast_tier"] and any(
        "strong_coupling" in r for r in g3["reasons"])
    assert tier_gate(0.5, 0.0, coupling_db=-11.0)["tier"] == "fast"
    g4 = tier_gate(0.5, 0.0, coupling_db=None)
    assert g4["tier"] == "fast" and g4["checks"]["coupling_db"]["pass"] is None
    # 多重违例 reasons 可分辨
    g5 = tier_gate(0.4, 60.0, coupling_db=-5.0)
    assert len(g5["reasons"]) == 3
