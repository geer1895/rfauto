"""W4-C P13：Lorentz 振子 + 多极 Debye/D-S 向量拟合面锚测试。

引源核对证据（#1c，2026-10-05）：
- Lorentz 模型（标准振子口径，与模块既有 Debye/DS 同时间约定）+ 引擎接口
  单源 = vendor openEMS ``CalcLorentzMaterial.m`` / ``AddLorentzMaterial.m``
  （本地 vendor 树逐行读式，见模块 docstring）：
      eps = eps_r − eps_r·Σ(2π f_p)²/(ω²−(2π f_L)²−jω·ω_r) − jκ/(ωε0)
  测试内独立重抄该公式作为引擎对拍裁判（ε(f) 逐点 rel 1e-12）与
  to_openems 导出回代裁判。
- 闭式点锚（独立推导）：ε(0)=ε∞+ΣΔε；谐振点损耗 ε″(ω0)=Δε·ω0/γ。
- 拟合面裁判（#118 合成回收先行）：已知模型采样 → 拟合 → 回收
  （ε(f) 曲线偏差门，非极点身份——nnls 极点可置换）；真实数据锚 =
  仓内 Gabriel 1996 Table 1（tissue_dielectric.gabriel1996_table1.csv，
  原文 Table 1 逐格转录在档）经 cole_cole_eps 合成频谱 → Debye 向量拟合。
"""

from __future__ import annotations

import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.dispersion import (
    EPS0,
    DebyeModel,
    DebyePole,
    DjordjevicSarkar,
    LorentzModel,
    LorentzPole,
    epsilon_analytic_ds,
    fit_debye_multipoles,
    fit_djordjevic_sarkar_band,
    kramers_kronig_residual,
)
from rfauto.core.tissue_dielectric import cole_cole_eps, load_gabriel1996

# ─── LorentzModel：闭式点锚 ──────────────────────────────────────────────────

M1 = LorentzModel(
    eps_inf=2.5,
    poles=(LorentzPole(delta_eps=3.0, f0_hz=10e9, gamma_hz=1.0e9),
           LorentzPole(delta_eps=1.5, f0_hz=40e9, gamma_hz=4.0e9)),
)


def test_static_limit_identity():
    """ε(0) = ε∞ + ΣΔε（闭式恒等，逐位级）。"""
    got = complex(M1.epsilon(1.0))  # 近 DC（1 Hz，σ=0 无 DC 奇异）
    assert got.real == pytest.approx(2.5 + 3.0 + 1.5, rel=1e-9)
    assert got.imag == pytest.approx(0.0, abs=1e-8)


def test_resonance_loss_peak_closed_form():
    """ε″(f0) = Δε·f0/γ 闭式点锚（f-form 分母在 f0 塌缩到 jf0γ；单极模型免
    第二极点尾量污染）。"""
    m = LorentzModel(eps_inf=2.0, poles=(LorentzPole(delta_eps=3.0, f0_hz=10e9, gamma_hz=1.0e9),))
    eps = complex(m.epsilon(10e9))
    assert -eps.imag == pytest.approx(3.0 * 10e9 / 1.0e9, rel=1e-12)
    assert eps.real == pytest.approx(2.0, rel=1e-12)


def test_resonance_loss_peak_location_near_f0():
    """高 Q（γ≪f0）时 ε″ 峰位≈f0（±1% 窗）。"""
    m = LorentzModel(eps_inf=1.5, poles=(LorentzPole(delta_eps=4.0, f0_hz=10e9, gamma_hz=0.2e9),))
    fs = np.geomspace(5e9, 20e9, 4001)
    eps_pp = -np.imag(m.epsilon(fs))
    assert float(fs[int(np.argmax(eps_pp))]) == pytest.approx(10e9, rel=0.01)


def test_multipoles_additivity():
    """多极 = 单极叠加（与 Debye 面同款结构锚）。"""
    single = [LorentzModel(M1.eps_inf, (p,)) for p in M1.poles]
    f = np.array([1e9, 10e9, 25e9, 40e9])
    total = M1.epsilon(f)
    manual = np.full(f.shape, complex(M1.eps_inf))
    for s in single:
        manual = manual + (s.epsilon(f) - M1.eps_inf)
    assert np.allclose(total, manual, rtol=1e-12)


# ─── openEMS 引擎对拍（vendor CalcLorentzMaterial 独立重抄裁判）───────────────

def _calc_lorentz_vendor(f, eps_inf, kappa, f_plasma, f_lor_pole, t_relax):
    """vendor CalcLorentzMaterial.m 逐式重抄（独立裁判路径）。"""
    f = np.atleast_1d(np.asarray(f, dtype=float))
    eps = np.full(f.shape, float(eps_inf), dtype=complex) - 1j * kappa / (2 * np.pi * f) / EPS0
    w = 2 * np.pi * f
    for fp, fl, tr in zip(f_plasma, f_lor_pole, t_relax, strict=True):
        w_r = 1.0 / tr if tr > 0 else 0.0
        eps = eps - float(eps_inf) * (2 * np.pi * fp) ** 2 / (
            w ** 2 - (2 * np.pi * fl) ** 2 - 2j * np.pi * f * w_r)
    return eps


def test_matches_openems_calc_lorentz_reference():
    """模型 vs vendor 公式逐点对拍（rel 1e-12，含多极与 σ_DC）。"""
    m = LorentzModel(
        eps_inf=2.5,
        poles=(LorentzPole(delta_eps=3.0, f0_hz=10e9, gamma_hz=1.0e9),
               LorentzPole(delta_eps=1.2, f0_hz=40e9, gamma_hz=4.0e9)),
        sigma_dc=0.01,
    )
    payload = m.to_openems()
    f = np.geomspace(1e8, 100e9, 97)
    ref = _calc_lorentz_vendor(
        f, payload["epsilon"], payload["kappa"],
        [p["f_plasma_hz"] for p in payload["poles"]],
        [p["f0_hz"] for p in payload["poles"]],
        [p["relax_time_s"] for p in payload["poles"]],
    )
    assert np.allclose(m.epsilon(f), ref, rtol=1e-12)


def test_to_openems_plasma_frequency_mapping():
    """f_plasma = f0·sqrt(Δε/ε∞)（vendor 公式 ε∞ω_p²↔Δεω0² 恒等变换的导出）。"""
    payload = M1.to_openems()
    assert payload["model"] == "lorentz"
    p0 = payload["poles"][0]
    assert p0["f_plasma_hz"] == pytest.approx(
        10e9 * np.sqrt(3.0 / 2.5), rel=1e-15)
    assert p0["relax_time_s"] == pytest.approx(1.0 / (2 * np.pi * 1.0e9), rel=1e-15)


def test_lorentz_kramers_kronig_residual():
    """K-K 因果性自检对 LorentzModel 直接适用（rel < 1e-6；共振结构比 Debye
    窗松一档，resonance 尾在 ±20 decade 窗内数值收敛实测钉）。"""
    m = LorentzModel(eps_inf=2.0, poles=(LorentzPole(delta_eps=3.0, f0_hz=10e9, gamma_hz=1.0e9),))
    residual = kramers_kronig_residual(m, np.array([1.0e8, 1.0e9, 1.0e10]))
    assert np.all(np.asarray(residual) < 1e-6)


def test_lorentz_guards():
    with pytest.raises(ValueError, match="f0_hz"):
        LorentzPole(1.0, 0.0, 1e9)
    with pytest.raises(ValueError, match="gamma_hz"):
        LorentzPole(1.0, 10e9, -1e9)
    with pytest.raises(ValueError, match="delta_eps"):
        LorentzPole(-1.0, 10e9, 1e9)
    with pytest.raises(TypeError, match="LorentzPole"):
        LorentzModel(2.0, (DebyePole(1.0, 1e9),))
    with pytest.raises(ValueError, match="eps_inf"):
        LorentzModel(0.0, ())


# ─── fit_debye_multipoles：合成回收（#118 先行）───────────────────────────────

def _sample(model, f):
    return np.asarray(model.epsilon(f), dtype=complex)


def test_debye_multipole_fit_synthetic_recovery():
    """已知 3 极 Debye 采样 → 8 极 nnls 拟合 → ε(f) 曲线回收（≤1% 逐点）。

    实测口径注记：固定对数极点栅 + nnls 的回收精度随 n_poles 非单调
    （5 极 2.8%、8 极 0.49%、10 极 1.03%——约束 LSQ 的栅-真值干涉），
    门按 8 极实测 0.49% 钉 1%；极点身份不锚（可置换）。
    """
    truth = DebyeModel(
        eps_inf=3.2,
        poles=(DebyePole(delta_eps=4.0, f_relax_hz=0.5e9),
               DebyePole(delta_eps=2.0, f_relax_hz=5e9),
               DebyePole(delta_eps=1.0, f_relax_hz=30e9)),
    )
    f = np.geomspace(50e6, 120e9, 61)
    data = _sample(truth, f)
    fitted = fit_debye_multipoles(f, data, n_poles=8)
    dev = np.abs(fitted.epsilon(f) - data) / np.abs(data)
    assert float(np.max(dev)) < 0.01
    assert fitted.eps_inf == pytest.approx(truth.eps_inf, rel=0.02)
    # 无源性结构条件：nnls 解 Δε_i ≥ 0（剪枝后仅存正极点）
    assert all(p.delta_eps > 0.0 for p in fitted.poles)


def test_debye_fit_with_sigma_dc_recovery():
    """σ_DC 项开启时 DC 电导支路可回收（合成含 σ 数据 → σ 门内回收）。"""
    truth = DebyeModel(eps_inf=3.0, poles=(DebyePole(delta_eps=2.0, f_relax_hz=2e9),),
                       sigma_dc=0.02)
    f = np.geomspace(1e6, 40e9, 41)
    data = _sample(truth, f)
    fitted = fit_debye_multipoles(f, data, n_poles=8, sigma_dc=True,
                                  weights="relative")
    assert fitted.sigma_dc == pytest.approx(0.02, rel=0.05)
    dev = np.abs(fitted.epsilon(f) - data) / np.abs(data)
    assert float(np.max(dev)) < 0.01
    # 对照面：绝对残差（缺省）下 σ 尾支配拟合，ε∞ 系统性偏低（如实锚）
    naive = fit_debye_multipoles(f, data, n_poles=8, sigma_dc=True)
    assert naive.eps_inf < fitted.eps_inf  # 相对加权修复中高频约束力
    assert naive.sigma_dc == pytest.approx(0.02, rel=0.05)


def test_debye_fit_quality_gate_fail_loud():
    """欠极点拟合撞质量门 → ValueError 带实测残差（#1b fail-loud）。"""
    truth = DebyeModel(
        eps_inf=3.0,
        poles=(DebyePole(delta_eps=5.0, f_relax_hz=1e9),
               DebyePole(delta_eps=5.0, f_relax_hz=50e9)),
    )
    f = np.geomspace(1e7, 100e9, 41)
    data = _sample(truth, f)
    with pytest.raises(ValueError, match="拟合质量门"):
        fit_debye_multipoles(f, data, n_poles=1, max_rel_residual=1e-4)


def test_debye_fit_guards():
    f = np.geomspace(1e6, 1e10, 20)
    data = np.full(20, 3.5 + 0.1j)
    with pytest.raises(ValueError, match="n_poles"):
        fit_debye_multipoles(f, data, n_poles=0)
    with pytest.raises(ValueError, match="等长"):
        fit_debye_multipoles(f[:-1], data, n_poles=2)
    with pytest.raises(ValueError, match="n_poles\\+2"):
        fit_debye_multipoles(f[:3], data[:3], n_poles=4)
    with pytest.raises(ValueError, match="拟合带"):
        fit_debye_multipoles(f, data, n_poles=2, f_max_hz=1e9)


def test_debye_fit_gabriel_blood_real_data_anchor():
    """真实数据锚：Gabriel 1996 blood（四极 Cole-Cole 参数在档）合成频谱 →
    多极 Debye 向量拟合（质量门 0.05 内、曲线回收 ≤2%）。"""
    table = load_gabriel1996()
    f = np.geomspace(1e6, 100e9, 81)
    rows = [cole_cole_eps("blood", float(x), table) for x in f]
    # cole_cole_eps 语义：ε* = ε′ − jε″（eps_r_imag 为正的 ε″）
    data = np.array([complex(r["eps_r_real"], -r["eps_r_imag"]) for r in rows])
    fitted = fit_debye_multipoles(f, data, n_poles=8, sigma_dc=True,
                                  weights="relative")
    dev = np.abs(fitted.epsilon(f) - data) / np.abs(data)
    assert float(np.max(dev)) < 0.05
    # DC 侧电导回收（σ=0.7 S/m 血液，Gabriel Table 1 在档值）
    assert fitted.sigma_dc == pytest.approx(0.7, rel=0.1)


# ─── fit_djordjevic_sarkar_band：回收与门 ────────────────────────────────────

def test_ds_band_fit_recovers_sampled_model():
    """已知 D-S 模型采样 → 频带两参数拟合 → 机器精度回收。"""
    truth = DjordjevicSarkar.from_single_point(
        eps_r=4.4, loss_tangent=0.02, f_meas_hz=10e9, f1_hz=1e6, f2_hz=100e9)
    f = np.geomspace(1e6, 100e9, 33)
    data = _sample(truth, f)
    fitted = fit_djordjevic_sarkar_band(f, data, 1e6, 100e9)
    assert fitted.eps_inf == pytest.approx(truth.eps_inf, rel=1e-9)
    assert fitted.delta_eps == pytest.approx(truth.delta_eps, rel=1e-9)
    assert np.allclose(fitted.epsilon(f), data, rtol=1e-9)


def test_ds_band_fit_matches_epsilon_analytic_crosscheck():
    """DS 频带拟合 vs 独立解析闭式（epsilon_analytic_ds）交叉一致。"""
    f1, f2 = 1e7, 60e9
    truth_eps_inf, truth_de = 3.8, 1.1
    f = np.geomspace(f1 * 1.3, f2 / 1.3, 29)
    data = epsilon_analytic_ds(truth_eps_inf, truth_de, f1, f2, f)
    fitted = fit_djordjevic_sarkar_band(f, np.asarray(data), f1, f2)
    assert fitted.eps_inf == pytest.approx(truth_eps_inf, rel=1e-8)
    assert fitted.delta_eps == pytest.approx(truth_de, rel=1e-8)


def test_ds_band_fit_guards():
    f = np.geomspace(1e6, 1e10, 12)
    data = np.full(12, 3.0 + 0.05j)
    with pytest.raises(ValueError, match="f1_hz < f2_hz"):
        fit_djordjevic_sarkar_band(f, data, 1e10, 1e6)
    with pytest.raises(ValueError, match="≥4"):
        fit_djordjevic_sarkar_band(f[:3], data[:3], 1e6, 1e10)
    with pytest.raises(ValueError, match="拟合质量门"):
        # σ_DC 与数据不一致 → 门拦
        fit_djordjevic_sarkar_band(f, data, 1e6, 1e10, sigma_dc=5.0,
                                   max_rel_residual=1e-6)


# ─── 结构回归：既有面零变化 ───────────────────────────────────────────────────

def test_existing_models_unaffected():
    """既有 DebyeModel/DjordjevicSarkar 接口回归钉（本批纯增量）。"""
    d = DebyeModel(eps_inf=3.0, poles=(DebyePole(delta_eps=2.0, f_relax_hz=1e9),))
    assert complex(d.epsilon(1.0)).real == pytest.approx(5.0, rel=1e-9)
    ds = DjordjevicSarkar.from_single_point(4.4, 0.02, 10e9, 1e6, 100e9)
    assert ds.epsilon_r(10e9) == pytest.approx(4.4, rel=1e-9)
    assert ds.loss_tangent(10e9) == pytest.approx(0.02, rel=1e-9)


def test_lorentz_tail_recovery_above_resonance():
    """高频尾回收锚：f ≥ 3f0 后 ε′ 从下方单调升向 ε∞（f>f0 时极点实部贡献
    恒负——Re 符号=sign(f0²−f²)<0，可证；单调性 30-300 GHz 实测钉）。
    注记：欠阻尼 Lorentz 在 f0 两侧有正常/反常色散的尖峰-塌缩结构，ε′ 并非
    单边单调（与纯弛豫 Debye 的 S 曲线不同），不设单边单调锚。"""
    m = LorentzModel(2.5, (LorentzPole(3.0, 10e9, 0.3e9),))
    f = np.geomspace(30e9, 300e9, 80)
    er = np.asarray(m.epsilon_r(f))
    assert all(u < v for u, v in pairwise(er.tolist()))
    assert np.all(er < 2.5)
