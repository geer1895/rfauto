"""QW-10 Schiffman 移相器 + QW-11 屏蔽效能计算器单测（组合小件批，2026-09-26）。

数值断言口径（#118 教训：锚值先独立实测/独立公式复算，不赌推导）：
- QW-10：综合-正算恒等式（Δφ(f0)=90°，实测残差 ~1.8e-9°）；均匀介质极限
  对照 Schiffman 1958 经典 arccos 闭式（实测 max|Δ|~4e-6°）；平坦度方向性
  锚（紧 75/34 → 4.88°、松 52.5/47.5 → 20.44°，KJ 真实 εeff 对实测）。
- QW-11：铜 1 MHz/t=1 mm 手算锚（δ=66.0855 µm——σ=5.8e7 口径；任务书
  "65.2 µm" 对应 σ=5.96e7，同量级）；SE=A+R+B 与独立 ABCD 级联双路互证
  （实测 |Δ|≤3.4e-10 dB，恒等精确非近似拼合）。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.calculators import shielding_effectiveness
from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm
from rfauto.core.synthesis import schiffman_delta_phase, synthesize_schiffman
from rfauto.service.calculator_service import run_calculator

# ─── QW-10 Schiffman 移相器 ──────────────────────────────────────────────────

_ER = 3.66
_H_M = 0.508e-3
_F0 = 2.5
_TIGHT = (75.0, 34.0)      # ρ≈2.21（紧耦合）
_LOOSE = (52.5, 47.5)      # ρ≈1.11（松耦合）


def test_schiffman_synthesis_forward_identity():
    """综合→正算恒等式：Δφ(f0)=90° 逐位（实测残差 ~1.8e-9°）。"""
    syn = synthesize_schiffman(*_TIGHT, _ER, _H_M, _F0, delta_phase_deg=90.0)
    fwd = float(schiffman_delta_phase(
        np.array([_F0]), syn["coupled_length_m"], _TIGHT[0], _TIGHT[1],
        _ER, _H_M, l_reference_m=syn["reference_length_m"])[0])
    assert abs(fwd - 90.0) <= 1e-6
    assert syn["delta_phase_at_f0_deg"] == pytest.approx(90.0, abs=1e-6)


def test_schiffman_geometry_inversion_and_backsubstitution():
    """几何反解联动 KJ 面：回代 |ΔZ|≤0.05Ω；紧耦合缝 < 松耦合缝（物理序）。"""
    syn_t = synthesize_schiffman(*_TIGHT, _ER, _H_M, _F0)
    syn_l = synthesize_schiffman(*_LOOSE, _ER, _H_M, _F0)
    for syn, (z0e, z0o) in ((syn_t, _TIGHT), (syn_l, _LOOSE)):
        w = syn["geometry_mm"]["w_mm"]
        s = syn["geometry_mm"]["s_mm"]
        assert 0.0 < w < 20.0 * 0.508 and 0.0 < s < 100.0 * 0.508
        z_e, z_o, eps_e, eps_o = coupled_microstrip_even_odd_ohm(
            w, s, _F0, er=_ER, h_mm=0.508)
        assert abs(z_e - z0e) <= 0.05 and abs(z_o - z0o) <= 0.05
        assert eps_e > eps_o  # 微带偶/奇模 εeff 物理序
    assert syn_t["geometry_mm"]["s_mm"] < syn_l["geometry_mm"]["s_mm"]
    # 反解不可达组合（ρ=3 超出该基板耦合范围）显式拒绝，不外推
    with pytest.raises(ValueError, match="可达域外"):
        synthesize_schiffman(86.6, 28.9, _ER, _H_M, _F0)


def test_schiffman_classic_arccos_limit():
    """均匀介质极限退化为 Schiffman 1958 经典 arccos 式（实测 ~4e-6°）。"""
    rho = 86.6 / 28.9
    eps_h = 2.2
    l_aux = 1e-3
    theta = np.linspace(0.05, 1.5, 200)
    f_ghz = theta * 299792458.0 / (2.0 * np.pi * math.sqrt(eps_h) * l_aux) / 1e9
    # L_ref→0（1e-30 m）⟹ Δφ = β_ref·L_ref − Φ_c ≈ −Φ_c
    phi_c_num = -schiffman_delta_phase(
        f_ghz, l_aux, 86.6, 28.9, _ER, _H_M, l_reference_m=1e-30,
        eps_eff_even=eps_h, eps_eff_odd=eps_h)
    mask = theta < math.pi / 2 - 0.05  # arccos 主支只在 θ<90° 与连续支重合
    phi_c_ref = np.degrees(np.arccos(
        (rho - np.tan(theta[mask]) ** 2) / (rho + np.tan(theta[mask]) ** 2)))
    assert float(np.max(np.abs(phi_c_num[mask] - phi_c_ref))) <= 1e-4


def test_schiffman_length_doubling_homogeneous():
    """L 翻倍→Δφ 翻倍（λ/4→λ/2 全通锚点 180°→360°，实测 5.7e-14°）。

    口径登记：器件差分相移的翻倍线性在 λ/4→λ/2 锚点处对均匀介质口径
    精确成立；全带内 Δφ(L) 非线性（arccos 型全通相位本性），Schiffman
    平坦度机理正源于该非线性——任务书"β_e·L−β_o·L"的模差分相位线性
    由综合层 θ0=ratio·90° 定义面（L_c ∝ ratio 精确线性）承载。
    """
    eps_h = 2.2
    l_c = 299792458.0 / (4.0 * _F0 * 1e9 * math.sqrt(eps_h))
    d1 = float(schiffman_delta_phase(
        np.array([_F0]), l_c, 86.6, 28.9, _ER, _H_M,
        eps_eff_even=eps_h, eps_eff_odd=eps_h)[0])
    d2 = float(schiffman_delta_phase(
        np.array([_F0]), 2.0 * l_c, 86.6, 28.9, _ER, _H_M,
        l_reference_m=6.0 * l_c,
        eps_eff_even=eps_h, eps_eff_odd=eps_h)[0])
    assert d1 == pytest.approx(90.0, abs=1e-6)
    assert d2 == pytest.approx(2.0 * d1, abs=1e-6)


def test_schiffman_flatness_directional():
    """平坦度方向性：紧耦合带内平坦 / 松耦合偏差大（实测 4.88° vs 20.44°）。"""
    tight = synthesize_schiffman(*_TIGHT, _ER, _H_M, _F0)
    loose = synthesize_schiffman(*_LOOSE, _ER, _H_M, _F0)
    dev_t = tight["phase_flatness"]["max_abs_deviation_deg"]
    dev_l = loose["phase_flatness"]["max_abs_deviation_deg"]
    assert dev_t <= 8.0
    assert dev_l >= 15.0
    assert dev_l > 2.0 * dev_t


def test_schiffman_notes_declare_quasistatic_eps():
    """εeff 常数化口径注记存在（禁虚构声明面）。"""
    syn = synthesize_schiffman(*_TIGHT, _ER, _H_M, _F0)
    notes = "".join(syn["notes"])
    assert "准静态" in notes and "色散" in notes
    assert syn["eps_eff"]["even"] > syn["eps_eff"]["odd"] > 1.0
    assert syn["reference_length_m"] > syn["coupled_length_m"]
    flat = syn["phase_flatness"]
    assert flat["band_ghz"][0] < _F0 < flat["band_ghz"][1]
    assert flat["n_points"] >= 5


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"delta_phase_deg": 0.0}, "非零有限"),
        ({"coupling_length_ratio": 0.0}, "正有限"),
        ({"coupling_length_ratio": 2.5}, "越域"),
        ({"bw_frac": 1.5}, "bw_frac"),
    ],
)
def test_schiffman_synthesis_guards(kwargs, match):
    with pytest.raises(ValueError, match=match):
        synthesize_schiffman(*_TIGHT, _ER, _H_M, _F0, **kwargs)


def test_schiffman_forward_guards():
    with pytest.raises(ValueError, match="Z0e 须大于 Z0o"):
        schiffman_delta_phase(np.array([2.5]), 0.02, 40.0, 50.0, _ER, _H_M)
    with pytest.raises(ValueError, match="成对给出"):
        schiffman_delta_phase(np.array([2.5]), 0.02, 75.0, 34.0, _ER, _H_M,
                              eps_eff_even=2.9)
    with pytest.raises(ValueError, match="f=0 显式拒绝"):
        schiffman_delta_phase(np.array([0.0]), 0.02, 75.0, 34.0, _ER, _H_M)


# ─── QW-11 屏蔽效能 ──────────────────────────────────────────────────────────

def _se_abcd_independent(f_hz: float, t_m: float, sigma: float,
                         mu_r: float) -> float:
    """独立裁判路：屏蔽体有耗 TL 段 ABCD 嵌入 Z_w 系统的 −20lg|S21|。

    与内核 A+R+B 分解完全不同源（#118：裁判必须是独立来源）。
    """
    mu = 4.0e-7 * math.pi * mu_r
    omega = 2.0 * math.pi * f_hz
    delta = math.sqrt(2.0 / (omega * mu * sigma))
    gamma = (1.0 + 1j) / delta
    z_s = np.sqrt(1j * omega * mu / sigma)
    z_w = 376.730313668
    s21 = 2.0 / (2.0 * np.cosh(gamma * t_m)
                 + (z_s / z_w + z_w / z_s) * np.sinh(gamma * t_m))
    return -20.0 * math.log10(abs(s21))


def test_shielding_copper_1mhz_1mm_hand_anchor():
    """铜 1 MHz/t=1 mm 手算锚：δ=66.0855 µm、A=131.43、R=108.14、B→0。

    δ 用闭式独立复算逐位对（量级 65–66 µm；任务书 65.2 µm 对应 σ=5.96e7，
    本表 σ=5.8e7 与 Stackup.rho=1.724e-8 同源）。
    """
    out = run_calculator("shielding_effectiveness", {
        "frequency_hz": 1.0e6, "thickness_m": 1.0e-3,
        "conductivity_s_per_m": 5.8e7})
    assert out["ok"] is True
    res = out["result"]
    f_hz, sigma, mu_r = 1.0e6, 5.8e7, 1.0
    delta_ref = math.sqrt(2.0 / (2.0 * math.pi * f_hz * 4.0e-7 * math.pi
                                 * mu_r * sigma))
    assert res["skin_depth_m"][0] == pytest.approx(delta_ref, abs=1e-12)
    assert 65.0e-6 <= res["skin_depth_m"][0] <= 67.0e-6  # 任务书量级锚
    assert res["se_absorption_db"][0] == pytest.approx(131.4341, abs=0.05)
    assert res["se_reflection_db"][0] == pytest.approx(108.1398, abs=0.05)
    assert abs(res["se_multiple_db"][0]) <= 1e-6  # t≫δ：多次反射修正→0
    assert res["se_total_db"][0] == pytest.approx(239.5739, abs=0.1)


@pytest.mark.parametrize(
    "f_hz,t_m,mu_r",
    [(1.0e6, 1.0e-3, 1.0), (1.0e5, 0.5e-3, 1.0),
     (1.0e7, 1.0e-3, 200.0), (1.0e9, 0.5e-3, 1.0)],
)
def test_shielding_identity_abcd_exact(f_hz, t_m, mu_r):
    """SE=A+R+B ≡ −20lg|S21_ABCD| 恒等式（独立双路，实测 |Δ|≤3.4e-10 dB）。"""
    out = run_calculator("shielding_effectiveness", {
        "frequency_hz": f_hz, "thickness_m": t_m,
        "conductivity_s_per_m": 5.8e7, "mu_r": mu_r})
    assert out["ok"] is True
    se_tl = _se_abcd_independent(f_hz, t_m, 5.8e7, mu_r)
    assert out["result"]["se_total_db"][0] == pytest.approx(se_tl, abs=1e-8)


def test_shielding_thin_shield_negative_multiple_reflection():
    """薄屏蔽 t≪δ：多次反射修正为负贡献（实测 B=−27.50 dB @1 µm）。"""
    out = run_calculator("shielding_effectiveness", {
        "frequency_hz": 1.0e6, "thickness_m": 1.0e-6,
        "conductivity_s_per_m": 5.8e7})
    res = out["result"]
    assert res["se_multiple_db"][0] <= -20.0
    assert res["se_total_db"][0] < (res["se_absorption_db"][0]
                                    + res["se_reflection_db"][0])
    assert res["se_total_db"][0] == pytest.approx(80.7694, abs=0.1)


def test_shielding_monotonic_in_frequency():
    """SE 随 f 单调增（吸收段 ∝√f 主导；f_axis 数组路径）。"""
    out = run_calculator("shielding_effectiveness", {
        "f_axis_hz": [1.0e5, 1.0e6, 1.0e7, 1.0e8, 1.0e9],
        "thickness_m": 1.0e-3, "conductivity_s_per_m": 5.8e7})
    se = out["result"]["se_total_db"]
    assert all(se[i] < se[i + 1] for i in range(len(se) - 1))
    assert len(out["result"]["skin_depth_m"]) == 5


def test_shielding_material_table_path():
    """材料表路径（D15 同款 provenance 格式）：命中取表值、未知显式拒绝。"""
    out = run_calculator("shielding_effectiveness", {
        "frequency_hz": 1.0e6, "thickness_m": 1.0e-3, "material": "copper"})
    assert out["ok"] is True
    assert out["result"]["material"] == "copper"
    assert out["result"]["conductivity_s_per_m"] == 5.8e7
    assert out["result"]["mu_r"] == 1.0
    bad = run_calculator("shielding_effectiveness", {
        "frequency_hz": 1.0e6, "thickness_m": 1.0e-3, "material": "unobtainium"})
    assert bad["ok"] is False and bad.get("error")


def test_shielding_guards_explicit():
    """域守卫：二选一/f=0/σ=0/t=0/近场未实现/bool 拒收，全部显式报错。"""
    base = {"thickness_m": 1.0e-3, "conductivity_s_per_m": 5.8e7}
    cases = [
        ({**base, "frequency_hz": 1.0e6, "f_axis_hz": [1.0e6]}, "二选一"),
        ({"thickness_m": 1.0e-3, "conductivity_s_per_m": 5.8e7}, "二选一"),
        ({**base, "frequency_hz": 0.0}, "f=0 显式拒绝"),
        ({**base, "frequency_hz": 1.0e6, "conductivity_s_per_m": 0.0}, "σ=0"),
        ({**base, "frequency_hz": 1.0e6, "thickness_m": 0.0}, "thickness_m"),
        ({**base, "frequency_hz": 1.0e6, "source": "near_field"}, "近场"),
    ]
    for params, match in cases:
        out = run_calculator("shielding_effectiveness", params)
        assert out["ok"] is False, params
        assert match in (out.get("error") or ""), (params, out.get("error"))
    with pytest.raises(ValueError, match="不接受 bool"):
        shielding_effectiveness(frequency_hz=True, thickness_m=1.0e-3,
                                conductivity_s_per_m=5.8e7)
