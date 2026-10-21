"""架构批 W7-A 席锚树：pa_arch 三键（平衡对+Doherty 网络+效率曲线）
+ qubit_readout 三键（色散位移+读出 S21+读出 SNR）。

数值断言口径（#118 不自证——闭式/恒等独立回收，不用自身推导互证）：
- 平衡对：①同管 S11,bal 逐位 0（反射对消恒等式严格路径）；②异管
  (S11a−S11b)/2、(S21a+S21b)/2 测试侧复数重算逐位回收；③单管失效
  （|Γ|=1、另一管匹配）→ |S11,bal|=1/2 → RL=6.0206 dB、增益
  −6.0206 dB；④相位容差 Γ=0.2/target 20dB → Δφ_max=60°，边界
  Δφ=60° 处 |S11,bal|=0.2·sin30°=0.1 逐位（RL 恰 20dB）。
- Doherty 网络：①R_opt=100 → R_L=50/Z_T=100/Z_BO=200（测试侧
  r_opt/2、r_opt、2r_opt 独立算术）；②ABCD 级联（A=D=cosθ=0、
  B=jZ_T sinθ、C=j sinθ/Z_T，θ=90°）对任意复负载回代 Z_T²/Z_L，
  与网络键 Z_BO 及 core.quarter_wave_invert 三方逐位互证（λ/4 反演
  ADS 域回代同式）；③合并点回退 10·log10(4)=6.0206 dB；④非经典
  backoff_db 显式拒绝。
- 效率曲线：①η(PBO=6.0206dB)=π/4 与 η(0)=π/4 双拐点逐位；②网格
  区域 II 凹陷 ≈2π/9 @ PBO≈3.5218dB（测试侧独立求导
  d/dσ[σ²/(3σ−1)]=σ(3σ−2)/(3σ−1)²=0 → σ=2/3）；③η ≥ 单管 B 类
  逐点；④区域 I 线性律 η=(π/2)σ 测试侧抽点回收。
- 色散位移：①远失谐 |Δ|≫κ → χ→g²/Δ（rel<1e-6）；②奇对称
  χ(−Δ)=−χ(Δ) 逐位；③Δ→0⁺ 序列单调 →0；④ncrit/Γ_P 测试侧独立
  重算；⑤判据旗标（|2χ|≥κ resolved、|g/Δ|≤0.1）边界自洽。
- 读出 S21：①临界耦合 κe=κ/2 → 态谐振点 |S21| 逐位 0（深谷归一）；
  ②欠耦合 κe=κ/4 → 0.5、过耦合 κe=κ → |S21|=1；③χ=0 双态曲线
  逐点相同（连续性）；④带缘 |S21|→1；⑤曲线点测试侧独立复数重算
  逐点回收（单源口径：双态差异只经 ±χ 进入）。
- 读出 SNR：①τ×4 → SNR×2（√τ 律，rel 1e-9）；②量子极限缺省
  （t_n_k=None → n_sys=1.0）；③T_n=h·f_r/k_B → n_sys=1、SNR 与
  缺省路径逐位一致；④T_n×4 → SNR÷2；⑤d_IQ 测试侧独立复数重算
  回收；⑥SNR=d_IQ·√(κe·n̄·τ/n_sys) 整式测试侧重算。
"""

from __future__ import annotations

import cmath
import math
import sys
from itertools import pairwise
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

ETA_B = math.pi / 4.0  # 理想 B 类峰值效率（测试侧独立常量，同 core 锚值）


# ─── 公共小工具 ──────────────────────────────────────────────────────────────


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _reject(key: str, params: dict, needle: str | None = None) -> None:
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 越界输入未拒绝: {params!r}"
    if needle is not None:
        assert needle in str(out.get("error")), (
            f"{key} 拒绝语义不符: {out.get('error')!r}")


def _polar(mag: float, deg: float) -> complex:
    """测试侧独立 (幅值, 相位 deg) → 复数（cmath 路径，与实现无关）。"""
    return cmath.rect(mag, math.radians(deg))


def _abcd_quarter_wave(z_load: complex, z_t: float) -> complex:
    """测试侧独立 λ/4 ABCD 级联回代：Z_in=(A·Z_L+B)/(C·Z_L+D)。

    θ=90°：A=D=cosθ=0、B=j·Z_T·sinθ=jZ_T、C=j·sinθ/Z_T=j/Z_T——
    ADS 域回代同一恒等式形态（解析上应严格给 Z_T²/Z_L）。
    """
    a = 0.0 + 0.0j
    b = 1j * z_t
    c = 1j / z_t
    d = 0.0 + 0.0j
    return (a * z_load + b) / (c * z_load + d)


# ─── balanced_pair_sparams：对消恒等式 / 失效容忍 / 相位容差 ─────────────────


def test_balanced_pair_identical_devices_exact_cancellation():
    """同管平衡对：S11,bal 逐位 0（反射对消恒等式严格路径）+增益=单管。"""
    r = _run("balanced_pair_sparams",
             {"s11a_mag": 0.2, "s21a_db": 20.0, "s11a_deg": 30.0,
              "s21a_deg": 10.0})
    assert r["s11_bal"]["re"] == 0.0 and r["s11_bal"]["im"] == 0.0
    assert r["s11_bal"]["rl_db"] is None  # 完美对消显式语义
    assert r["identical_devices"] is True
    # S21,bal = (S21a+S21b)/2 = S21a（同管）：增益 20dB（6 位舍入）、相位 10°
    assert r["gain_bal_db"] == pytest.approx(20.0, abs=1e-6)
    assert r["s21_bal"]["deg"] == pytest.approx(10.0, abs=1e-9)
    # 输出侧镜像口径：S22,bal 同恒等式 → 同样逐位 0
    assert r["s22_bal"]["re"] == 0.0 and r["s22_bal"]["im"] == 0.0
    assert r["s22_source"] == "mirrored_from_s11"


def test_balanced_pair_synthesis_identity_unequal_devices():
    """异管合成恒等式：(S11a−S11b)/2 与 (S21a+S21b)/2 测试侧复数重算。"""
    params = {"s11a_mag": 0.2, "s11a_deg": 30.0, "s21a_db": 20.0,
              "s21a_deg": 10.0,
              "s11b_mag": 0.15, "s11b_deg": -45.0, "s21b_db": 19.0,
              "s21b_deg": -20.0}
    r = _run("balanced_pair_sparams", params)
    s11a = _polar(0.2, 30.0)
    s11b = _polar(0.15, -45.0)
    s21a = _polar(10.0 ** (20.0 / 20.0), 10.0)
    s21b = _polar(10.0 ** (19.0 / 20.0), -20.0)
    exp_s11 = (s11a - s11b) / 2.0
    exp_s21 = (s21a + s21b) / 2.0
    assert r["s11_bal"]["re"] == pytest.approx(exp_s11.real, abs=1e-9)
    assert r["s11_bal"]["im"] == pytest.approx(exp_s11.imag, abs=1e-9)
    assert r["s21_bal"]["re"] == pytest.approx(exp_s21.real, abs=1e-9)
    assert r["s21_bal"]["im"] == pytest.approx(exp_s21.imag, abs=1e-9)
    # gain_bal_db 输出保留 6 位 → 容差 1e-6（舍入口径）
    assert r["gain_bal_db"] == pytest.approx(
        20.0 * math.log10(abs(exp_s21)), abs=1e-6)
    assert r["identical_devices"] is False


def test_balanced_pair_failed_device_tolerance():
    """单管失效容忍：|Γ|=1 vs 匹配 → |S11,bal|=1/2 → RL=6.0206dB；"""
    """增益 −6.0206dB（S21,bal=S21/2）——平衡架构经典失效容忍口径。"""
    r = _run("balanced_pair_sparams",
             {"s11a_mag": 0.0, "s21a_db": 20.0,
              "s11b_mag": 1.0, "s21b_db": -40.0})
    assert r["s11_bal"]["mag"] == pytest.approx(0.5, abs=1e-12)
    assert r["s11_bal"]["rl_db"] == pytest.approx(6.0205999, abs=1e-4)
    assert r["mismatch_tolerance"]["failed_device_rl_db"] == pytest.approx(
        6.0205999, abs=1e-4)
    assert r["gain_bal_db"] == pytest.approx(
        20.0 * math.log10((10.0 + 0.01) / 2.0), abs=1e-6)
    assert r["mismatch_tolerance"]["failed_device_gain_drop_db"] == (
        pytest.approx(-6.0205999, abs=1e-4))


def test_balanced_pair_phase_mismatch_tolerance_boundary():
    """相位容差边界：Γ=0.2/RL=20dB → Δφ_max=60°；边界处 0.2·sin30°
    =0.1 → RL 恰 20dB（|S11,bal|=Γ·|sin(Δφ/2)| 恒等式逐位）。"""
    r = _run("balanced_pair_sparams",
             {"s11a_mag": 0.2, "s21a_db": 20.0,
              "s11b_mag": 0.2, "target_rl_db": 20.0})
    assert r["mismatch_tolerance"]["max_phase_mismatch_deg"] == (
        pytest.approx(60.0, abs=1e-6))
    # 边界复核：Δφ=60°（相位 −30°/30°）→ |S11,bal|=0.1 → RL=20dB
    rb = _run("balanced_pair_sparams",
              {"s11a_mag": 0.2, "s11a_deg": 30.0, "s21a_db": 20.0,
               "s11b_mag": 0.2, "s11b_deg": -30.0})
    assert rb["s11_bal"]["mag"] == pytest.approx(0.1, abs=1e-12)
    assert rb["s11_bal"]["rl_db"] == pytest.approx(20.0, abs=1e-9)
    # Γ=0 → 相位容差无上界（None + note）
    r0 = _run("balanced_pair_sparams", {"s11a_mag": 0.0, "s21a_db": 20.0})
    assert r0["mismatch_tolerance"]["max_phase_mismatch_deg"] is None
    assert "任意相位" in r0["mismatch_tolerance"]["phase_note"]


def test_balanced_pair_hybrid_loss_and_guards():
    """混合器插损增益修正（−2×IL）+ 反射幅值/IL/目标回损域守卫。"""
    r = _run("balanced_pair_sparams",
             {"s11a_mag": 0.2, "s21a_db": 20.0, "hybrid_il_db": 0.3})
    assert r["gain_bal_db"] == pytest.approx(20.0 - 0.6, abs=1e-6)
    _reject("balanced_pair_sparams",
            {"s11a_mag": 1.5, "s21a_db": 20.0}, needle="[0,1]")
    _reject("balanced_pair_sparams",
            {"s11a_mag": 0.2, "s21a_db": 20.0, "hybrid_il_db": -1.0})
    _reject("balanced_pair_sparams",
            {"s11a_mag": 0.2, "s21a_db": 20.0, "target_rl_db": 0.0})
    _reject("balanced_pair_sparams", {"s11a_mag": 0.2}, needle="必需")


# ─── doherty_combining_network：λ/4 网络综合 + ABCD 回代 ─────────────────────


def test_doherty_network_classic_impedance_set():
    """经典 2-Way 等功率设计集：R_L=R_opt/2、Z_T=R_opt、Z_BO=2R_opt。"""
    r = _run("doherty_combining_network", {"r_opt_ohm": 100.0})
    assert r["r_load_ohm"] == pytest.approx(50.0, abs=1e-9)
    assert r["z_t_ohm"] == pytest.approx(100.0, abs=1e-9)
    assert r["z_backoff_carrier_ohm"]["mag"] == pytest.approx(200.0, abs=1e-9)
    assert r["abcd_roundtrip"]["matches"] is True
    assert r["identities"]["z_t_eq_2r_load"] is True
    assert r["identities"]["r_load_eq_r_opt_half"] is True
    assert r["combine_backoff_db"] == pytest.approx(
        10.0 * math.log10(4.0), abs=1e-5)
    assert r["power_split_carrier_pct"] == 50.0
    assert r["power_split_peak_pct"] == 50.0
    # 归一化展示面：R_opt=100/Z0=50 → Z_BO 归一恰 4（4:1 阻抗比）
    r50 = _run("doherty_combining_network", {"r_opt_ohm": 100.0,
                                             "z0_ohm": 50.0})
    assert r50["z_backoff_carrier_ohm"]["mag"] / 50.0 == pytest.approx(
        4.0, abs=1e-12)


def test_doherty_network_abcd_roundtrip_independent():
    """λ/4 反演 ADS 域回代：测试侧独立 ABCD 级联（θ=90°）对任意复负载
    与网络键 Z_BO 及 core.quarter_wave_invert 三方逐位互证。"""
    from rfauto.core.pa_architectures import quarter_wave_invert

    z_t = 100.0
    for z_load in (complex(50.0, 0.0), complex(30.0, 17.0),
                   complex(1e3, -220.0)):
        by_abcd = _abcd_quarter_wave(z_load, z_t)
        by_core = quarter_wave_invert(z_load, z_t)
        expected = z_t * z_t / z_load
        assert by_abcd == pytest.approx(expected, rel=1e-12)
        assert by_core == pytest.approx(expected, rel=1e-12)
    # 网络键回退点：Z_BO = Z_T²/R_L，R_L=R_opt/2 → 2R_opt（测试侧算术）
    r_opt = 100.0
    z_bo = _abcd_quarter_wave(complex(r_opt / 2.0, 0.0), r_opt)
    assert z_bo == pytest.approx(complex(2.0 * r_opt, 0.0), rel=1e-12)


def test_doherty_network_guards():
    """非经典 backoff/非正 r_opt/z0 显式拒绝（非等功率口径不外推）。"""
    _reject("doherty_combining_network",
            {"r_opt_ohm": 100.0, "backoff_db": 8.0}, needle="显式拒绝")
    r_ok = run_calculator("doherty_combining_network",
                          {"r_opt_ohm": 100.0, "backoff_db": 6.02})
    assert r_ok["ok"] is True  # 容差带内（0.05dB）放行
    _reject("doherty_combining_network", {"r_opt_ohm": 0.0})
    _reject("doherty_combining_network", {"r_opt_ohm": -5.0})
    _reject("doherty_combining_network", {"r_opt_ohm": 100.0, "z0_ohm": 0.0})
    _reject("doherty_combining_network", {}, needle="必需")


# ─── doherty_efficiency_curve：双拐点 / 凹陷 / 对比列 ────────────────────────


def test_doherty_curve_double_knee_identity():
    """双拐点恒等：η(0dB)=η(6.0206dB)=π/4 逐位（曲线与解析锚双路径）。"""
    r = _run("doherty_efficiency_curve",
             {"n_points": 41, "pbo_max_db": 10.0})
    assert r["eta_peak"] == pytest.approx(ETA_B, abs=1e-12)
    assert r["eta_knee"] == pytest.approx(ETA_B, abs=1e-12)
    assert r["flags"]["knee_identity_ok"] is True
    # 曲线端点与拐点回收：pbo=0 → σ=1 → π/4；构造轴 0/6.0206/12.0412
    # 三点栅格（pbo_max=2×6.0206、n=3）使拐点恰落栅格点 → η 逐位 π/4
    assert r["eta"][0] == pytest.approx(ETA_B, abs=1e-12)
    r_knee = _run("doherty_efficiency_curve",
                  {"n_points": 3, "pbo_max_db": 2.0 * 10.0 * math.log10(4.0)})
    assert r_knee["pbo_db"][1] == pytest.approx(10.0 * math.log10(4.0),
                                                abs=1e-9)
    assert r_knee["eta"][1] == pytest.approx(ETA_B, abs=1e-12)


def test_doherty_curve_dip_independent_calculus():
    """中段凹陷：测试侧独立求导 d/dσ[σ²/(3σ−1)]=σ(3σ−2)/(3σ−1)²=0
    → σ=2/3（PBO≈3.5218dB）、min η=2π/9；网格凹陷落解析锚邻域。"""
    # 独立求导锚：临界点手解
    sigma_dip = 2.0 / 3.0
    eta_dip_analytic = (math.pi * sigma_dip ** 2
                        / (2.0 * (3.0 * sigma_dip - 1.0)))
    assert eta_dip_analytic == pytest.approx(2.0 * math.pi / 9.0, rel=1e-12)
    r = _run("doherty_efficiency_curve",
             {"n_points": 481, "pbo_max_db": 10.0})
    assert r["eta_dip_min"] == pytest.approx(2.0 * math.pi / 9.0, rel=1e-9)
    assert r["dip_pbo_db"] == pytest.approx(
        -20.0 * math.log10(sigma_dip), abs=1e-5)
    assert r["dip_in_span"] is True
    assert r["dip_grid_eta"] == pytest.approx(2.0 * math.pi / 9.0, abs=5e-5)
    assert r["dip_grid_pbo_db"] == pytest.approx(3.5218, abs=0.01)
    # η 全域 ≤ π/4（凹陷不超峰）且 ≥ 单管 B 类逐点
    assert max(r["eta"]) <= ETA_B + 1e-12
    assert r["flags"]["eta_bounds_ok"] is True
    assert r["flags"]["doherty_ge_class_b"] is True
    for e, cb in zip(r["eta"], r["class_b_eta"], strict=True):
        assert e >= cb - 1e-12


def test_doherty_curve_region1_linear_law():
    """区域 I 线性律 η=(π/2)σ 测试侧抽点回收（σ=0.25 → π/8≈39.27%）。"""
    r2 = _run("doherty_efficiency_curve",
              {"n_points": 161, "pbo_max_db": 16.0})
    i = min(range(len(r2["pbo_db"])),
            key=lambda j: abs(r2["pbo_db"][j] - 12.0412))
    sigma = 10.0 ** (-r2["pbo_db"][i] / 20.0)
    assert sigma == pytest.approx(0.25, abs=2e-3)
    assert r2["eta"][i] == pytest.approx((math.pi / 2.0) * sigma, rel=1e-3)
    assert r2["eta"][i] == pytest.approx(math.pi / 8.0, abs=2e-3)


def test_doherty_curve_guards():
    """点数/回退轴域守卫。"""
    _reject("doherty_efficiency_curve", {"n_points": 1})
    _reject("doherty_efficiency_curve", {"n_points": 0.5})
    _reject("doherty_efficiency_curve", {"pbo_max_db": 0.0})
    _reject("doherty_efficiency_curve", {"pbo_max_db": 31.0})


# ─── qubit_dispersive_shift：远失谐极限 / 奇对称 / 判据 ──────────────────────


def test_chi_far_detuned_reduces_to_g2_over_delta():
    """远失谐 |Δ|≫κ → χ→g²/Δ（Blais 色散支教科书极限，rel<1e-6）。"""
    g, kappa = 50.0, 10.0
    r = _run("qubit_dispersive_shift",
             {"g_mhz": g, "delta_mhz": 5000.0, "kappa_mhz": kappa})
    chi = r["chi_mhz"]
    expected = g * g / 5000.0
    # 有限 κ 修正在 (κ/2Δ)² ≈ 1e-6 量级——极限残差容差 3e-6
    assert chi == pytest.approx(expected, rel=3e-6)
    # 精确闭式复核：χ = g²Δ/((κ/2)²+Δ²)
    exact = g * g * 5000.0 / ((kappa / 2.0) ** 2 + 5000.0 ** 2)
    assert chi == pytest.approx(exact, rel=1e-12)


def test_chi_odd_symmetry_and_continuity():
    """奇对称 χ(−Δ)=−χ(Δ) 逐位；Δ→0⁺ 序列单调 →0（连续性锚）。"""
    g, kappa = 50.0, 10.0
    r_plus = _run("qubit_dispersive_shift",
                  {"g_mhz": g, "delta_mhz": 200.0, "kappa_mhz": kappa})
    r_minus = _run("qubit_dispersive_shift",
                   {"g_mhz": g, "delta_mhz": -200.0, "kappa_mhz": kappa})
    assert r_plus["chi_mhz"] == pytest.approx(-r_minus["chi_mhz"],
                                              abs=1e-12)
    chis = []
    for d in (10.0, 1.0, 0.1, 0.01, 0.001, 1e-6):
        rr = _run("qubit_dispersive_shift",
                  {"g_mhz": g, "delta_mhz": d, "kappa_mhz": kappa})
        chis.append(rr["chi_mhz"])
    assert all(c > 0.0 for c in chis)
    assert all(a > b for a, b in pairwise(chis))
    assert chis[-1] < 1e-3  # Δ→0⁺ χ→0 连续（g²Δ/(κ/2)² 线性小极限）
    _reject("qubit_dispersive_shift",
            {"g_mhz": g, "delta_mhz": 0.0, "kappa_mhz": kappa},
            needle="简并点")


def test_chi_auxiliary_faces_and_regime_flags():
    """ncrit/Γ_P/有效线宽测试侧独立重算；判据旗标边界自洽。"""
    g, delta, kappa, g1 = 100.0, 200.0, 5.0, 0.001
    r = _run("qubit_dispersive_shift",
             {"g_mhz": g, "delta_mhz": delta, "kappa_mhz": kappa,
              "gamma1_mhz": g1})
    chi = g * g * delta / ((kappa / 2.0) ** 2 + delta ** 2)
    assert r["chi_mhz"] == pytest.approx(chi, rel=1e-12)
    assert r["ncrit"] == pytest.approx(delta ** 2 / (4.0 * g * g), rel=1e-12)
    assert r["purcell_mhz"] == pytest.approx((g / delta) ** 2 * kappa,
                                             rel=1e-12)
    assert r["gamma_eff_mhz"] == pytest.approx(g1 + r["purcell_mhz"],
                                               rel=1e-12)
    assert r["two_chi_over_kappa"] == pytest.approx(2.0 * abs(chi) / kappa,
                                                    rel=1e-12)
    # 本名义点 |2χ|≈100≫κ=5 → resolved；|g/Δ|=0.5 → 近似旗标 False
    assert r["regime"]["resolved_strong_dispersive"] is True
    assert r["regime"]["dispersive_approx_valid"] is False
    # 弱色散点：g/Δ=0.05 → 有效；|2χ|≪κ → 未分辨
    r_weak = _run("qubit_dispersive_shift",
                  {"g_mhz": 5.0, "delta_mhz": 100.0, "kappa_mhz": 10.0})
    assert r_weak["regime"]["dispersive_approx_valid"] is True
    assert r_weak["regime"]["resolved_strong_dispersive"] is False
    # 守卫：g/κ 非正、Γ1 负、bool 拒收
    _reject("qubit_dispersive_shift",
            {"g_mhz": 0.0, "delta_mhz": 100.0, "kappa_mhz": 10.0})
    _reject("qubit_dispersive_shift",
            {"g_mhz": 50.0, "delta_mhz": 100.0, "kappa_mhz": -1.0})
    _reject("qubit_dispersive_shift",
            {"g_mhz": 50.0, "delta_mhz": 100.0, "kappa_mhz": 10.0,
             "gamma1_mhz": -1.0})


# ─── qubit_readout_s21：临界耦合深谷 / 单源双态 / 连续性 ─────────────────────


def test_s21_critical_coupling_deep_notch():
    """临界耦合 κe=κ/2 → 态谐振点 |S21|=1−κe/(κ/2) 逐位 0（深谷归一）。"""
    r = _run("qubit_readout_s21",
             {"f_r_ghz": 6.0, "kappa_mhz": 2.0, "kappa_e_mhz": 1.0,
              "chi_mhz": 1.5})
    assert r["coupling_regime"] == "critical"
    assert r["dip_mag_state_resonance"] == pytest.approx(0.0, abs=1e-12)
    # 欠耦合/过耦合锚：1−2κe/κ
    r_u = _run("qubit_readout_s21",
               {"f_r_ghz": 6.0, "kappa_mhz": 2.0, "kappa_e_mhz": 0.5,
                "chi_mhz": 0.0})
    assert r_u["coupling_regime"] == "undercoupled"
    assert r_u["dip_mag_state_resonance"] == pytest.approx(0.5, abs=1e-12)
    r_o = _run("qubit_readout_s21",
               {"f_r_ghz": 6.0, "kappa_mhz": 2.0, "kappa_e_mhz": 2.0,
                "chi_mhz": 0.0})
    assert r_o["coupling_regime"] == "overcoupled"
    assert r_o["dip_mag_state_resonance"] == pytest.approx(1.0, abs=1e-12)
    _reject("qubit_readout_s21",
            {"f_r_ghz": 6.0, "kappa_mhz": 2.0, "kappa_e_mhz": 3.0})
    _reject("qubit_readout_s21",
            {"f_r_ghz": 6.0, "kappa_mhz": 2.0, "kappa_e_mhz": 0.0})


def test_s21_curves_single_source_and_continuity():
    """χ=0 双态曲线逐点相同（连续性）；χ≠0 曲线点测试侧独立复数重算
    逐点回收（双态差异只经 ±χ 进入——单源口径）。"""
    common = {"f_r_ghz": 6.0, "kappa_mhz": 2.0, "kappa_e_mhz": 1.0,
              "span_mhz": 10.0, "n_points": 41}
    r0 = _run("qubit_readout_s21", dict(common, chi_mhz=0.0))
    assert r0["s21_state0"] == r0["s21_state1"]
    assert r0["mag_db_state0"] == r0["mag_db_state1"]
    assert r0["two_chi_over_kappa"] == 0.0

    chi = 1.5
    r = _run("qubit_readout_s21", dict(common, chi_mhz=chi))
    fr, kappa, ke = 6000.0, 2.0, 1.0
    for i, f in enumerate(r["freq_mhz"]):
        s0 = 1.0 - ke / complex(kappa / 2.0, (f - fr) - (+chi))
        s1 = 1.0 - ke / complex(kappa / 2.0, (f - fr) - (-chi))
        assert r["s21_state0"][i]["re"] == pytest.approx(s0.real, abs=1e-9)
        assert r["s21_state0"][i]["im"] == pytest.approx(s0.imag, abs=1e-9)
        assert r["s21_state1"][i]["re"] == pytest.approx(s1.real, abs=1e-9)
        assert r["s21_state1"][i]["im"] == pytest.approx(s1.imag, abs=1e-9)
    # 带缘 |S21|→1（|δ|=5κ...：κe=κ/2、|δ−shift|=6.5×(κ/2)，测试侧
    # 独立重算幅值锚）
    edge = abs(1.0 - ke / complex(kappa / 2.0, -5.0 - chi))
    got = abs(complex(r["s21_state0"][0]["re"], r["s21_state0"][0]["im"]))
    assert got == pytest.approx(edge, rel=1e-9)
    assert got > 0.98
    # 态频移方向：state0 谷在 f_r+χ（约定写死）；栅格恰含 6001.5MHz
    # 点（步长 0.25MHz）→ 临界耦合态谐振点幅值逐位 0 → mag_db=None
    i0 = min(range(len(r["freq_mhz"])),
             key=lambda j: abs(r["freq_mhz"][j] - (fr + chi)))
    assert r["s21_state0"][i0] == {"re": 0.0, "im": 0.0}
    assert r["mag_db_state0"][i0] is None
    assert sum(v is None for v in r["mag_db_state0"]) == 1  # 唯一精确零点
    # 栅格/跨度守卫
    _reject("qubit_readout_s21", dict(common, n_points=1))
    _reject("qubit_readout_s21", dict(common, span_mhz=0.0))
    _reject("qubit_readout_s21", dict(common, kappa_mhz=0.0))


# ─── qubit_readout_snr：√τ 律 / 量子极限 / IQ 分离回收 ───────────────────────


_SNR_COMMON = {"chi_mhz": 1.0, "kappa_mhz": 2.0, "kappa_e_mhz": 1.0,
               "n_bar": 50.0, "f_r_ghz": 6.0}


def test_snr_sqrt_tau_law():
    """SNR ∝ √τ 恒等回收：τ×4 → SNR×2（rel 1e-9）；n̄×4 → SNR×2。"""
    r1 = _run("qubit_readout_snr", dict(_SNR_COMMON, tau_us=1.0))
    r4 = _run("qubit_readout_snr", dict(_SNR_COMMON, tau_us=4.0))
    assert r4["snr"] == pytest.approx(2.0 * r1["snr"], rel=1e-9)
    rn4 = _run("qubit_readout_snr", dict(_SNR_COMMON, tau_us=1.0,
                                         n_bar=200.0))
    assert rn4["snr"] == pytest.approx(2.0 * r1["snr"], rel=1e-9)
    # τ₁ 面自洽：SNR(τ₁)=1（snr ∝ √τ 反解）
    tau1 = _run("qubit_readout_snr", dict(_SNR_COMMON,
                                          tau_us=r1["tau_for_snr1_us"]))
    assert tau1["snr"] == pytest.approx(1.0, rel=1e-9)


def test_snr_quantum_limit_and_noise_scaling():
    """量子极限：缺省 t_n_k → n_sys=1；T_n=h·f_r/k_B → 与缺省逐位一致；
    T_n×4 → SNR÷2（n_sys 线性进 √ 号）。"""
    r_default = _run("qubit_readout_snr", dict(_SNR_COMMON, tau_us=1.0))
    assert r_default["quantum_limited"] is True
    assert r_default["n_sys"] == 1.0
    t_q = 0.287954584402  # h·6GHz/k_B（测试侧独立常量见下行重算）
    t_q_exact = 6.62607015e-34 * 6.0e9 / 1.380649e-23
    assert t_q == pytest.approx(t_q_exact, abs=1e-9)
    assert r_default["t_q_k"] == pytest.approx(t_q_exact, rel=1e-12)
    r_q = _run("qubit_readout_snr", dict(_SNR_COMMON, tau_us=1.0,
                                         t_n_k=t_q_exact))
    assert r_q["n_sys"] == pytest.approx(1.0, rel=1e-9)
    assert r_q["snr"] == pytest.approx(r_default["snr"], rel=1e-9)
    r_hot = _run("qubit_readout_snr", dict(_SNR_COMMON, tau_us=1.0,
                                           t_n_k=4.0 * t_q_exact))
    assert r_hot["n_sys"] == pytest.approx(4.0, rel=1e-9)
    assert r_hot["snr"] == pytest.approx(0.5 * r_default["snr"], rel=1e-9)
    _reject("qubit_readout_snr", dict(_SNR_COMMON, tau_us=1.0, t_n_k=0.0))
    _reject("qubit_readout_snr", dict(_SNR_COMMON, tau_us=0.0))


def test_snr_iq_separation_independent_recompute():
    """d_IQ 与整式 SNR 测试侧独立复数重算回收；χ=0 零信号显式拒绝。"""
    r = _run("qubit_readout_snr", dict(_SNR_COMMON, tau_us=1.0,
                                       detune_mhz=0.5))
    chi, kappa, ke = 1.0e6, 2.0e6, 1.0e6
    detune = 0.5e6
    s0 = 1.0 - ke / complex(kappa / 2.0, detune - (+chi))
    s1 = 1.0 - ke / complex(kappa / 2.0, detune - (-chi))
    d_iq = abs(s0 - s1)
    assert r["d_iq"] == pytest.approx(d_iq, rel=1e-9)
    snr_expected = d_iq * math.sqrt(ke * 50.0 * 1.0e-6 / 1.0)
    assert r["snr"] == pytest.approx(snr_expected, rel=1e-9)
    # Γ_m 参考面：8χ²n̄/κ（测试侧独立重算；仅参考不进 SNR 主路径）
    assert r["gamma_m_per_s"] == pytest.approx(
        8.0 * (1.0e6 ** 2) * 50.0 / 2.0e6, rel=1e-9)
    _reject("qubit_readout_snr", dict(_SNR_COMMON, chi_mhz=0.0,
                                      tau_us=1.0), needle="零信号")
    _reject("qubit_readout_snr", dict(_SNR_COMMON, n_bar=0.0, tau_us=1.0))


# ─── 注册面归属（S 面分类封闭清单消费侧自证） ─────────────────────────────────


def test_w7a_keys_registered_and_classified():
    """六键全注册且在 _NO_S_PLANE_KEYS 封闭清单（标量/曲线产出，无 S 矩阵）。"""
    from tests.unit.test_physics_invariants import _NO_S_PLANE_KEYS

    for key in ("balanced_pair_sparams", "doherty_combining_network",
                "doherty_efficiency_curve", "qubit_dispersive_shift",
                "qubit_readout_s21", "qubit_readout_snr"):
        spec = CALCULATOR_REGISTRY.get(key)
        assert spec.reciprocal is True
        assert key in _NO_S_PLANE_KEYS
