"""真 Marchand 两节对称耦合段电路级综合（2026-09-18）。

裁判分层（#118：不自证）：
- 耦合线四端口 Z 矩阵（core，偶/奇模叠加推导）→ S，逐点对照 adapters 的偶/奇模
  S 叠加实现 coupled_line_coupler_sparams（两份独立代码路径）+ Pozar 教科书
  θ=90° 闭式（|S31|=C、S11=S41=0）；
- 通用端口约束消元 reduce_z_network 对照单段 TL 短路/开路解析输入阻抗；
- Marchand f0 闭式（Z_in=2(Z0e·Z0o)²/((Z0e−Z0o)²·Z_t)）与数值网络求解互证：
  闭式设计点数值 S11(f0)=0，失谐点 S11≠0；文献常引常规设计点 C=1/√3、
  (Z0e,Z0o)=(96.59,25.88)Ω@50Ω 由本推导复现（非抄录）；
- 名义设计点（50Ω→280Ω 差分，RO4350B 60mil，缝 ≥0.1mm）：可达、KJ 回代、门 PASS；
  常规 50→100Ω 差分：边耦合微带不可达如实（realizable=False，不抛异常）。
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.slotline_transitions import (
    MARCHAND2_GATES,
    MARCHAND2_NOMINAL_INPUTS,
    MARCHAND_OPENEMS_BETA_DEV,
    MARCHAND_OPENEMS_W_DOMAIN_MM,
    MARCHAND_OPENEMS_Z0_DEV_CAL,
    MarchandTwoSectionDesign,
    coupled_line_z_matrix,
    coupled_microstrip_width_gap_from_even_odd,
    engine_z0_correction,
    even_odd_from_coupling,
    marchand_coupling_for_match,
    marchand_input_impedance_f0,
    marchand_two_section_metrics,
    marchand_two_section_nominal,
    marchand_two_section_sparams,
    reduce_to_s_matrix,
    reduce_z_network,
    synthesize_marchand_two_section,
    z_to_s,
)

C0 = 299792458.0


# ─── ① 耦合线 Z 矩阵：独立实现互证 ──────────────────────────────────────────────

def _tl_z2(z0: float, theta: float) -> np.ndarray:
    return -1j * z0 * np.array([[1 / math.tan(theta), 1 / math.sin(theta)],
                                [1 / math.sin(theta), 1 / math.tan(theta)]])


@pytest.mark.parametrize("theta_deg", [30.0, 60.0, 90.0, 120.0, 150.0])
def test_coupled_line_z_matrix_matches_adapters_even_odd_s(theta_deg):
    """core Z 矩阵→S 与 adapters 偶/奇模 S 叠加（独立代码路径）逐元素一致。"""
    from rfauto.adapters.openems_templates import coupled_line_coupler_sparams

    zee, zoo = 69.371, 36.038          # 10dB 耦合器（Pozar §7.6 设计点）
    f0 = 2.5
    len_mm = C0 / (f0 * 1e9) / 4.0 * 1e3   # εeff=1 下 λ/4
    f = f0 * theta_deg / 90.0
    s_ref = coupled_line_coupler_sparams([f], zee, zoo, len_mm, 1.0, 1.0,
                                         synchronous_tem=True, z_ref=50.0)[0]
    theta = math.radians(theta_deg)
    s_core = z_to_s(coupled_line_z_matrix(zee, zoo, theta), [50.0] * 4)
    assert np.max(np.abs(s_core - s_ref)) < 1e-9


def test_coupled_line_z_matrix_pozar_quarter_wave_closed_form():
    """θ=90°、全端口 Z_c=√(Z0e·Z0o) 端接：|S31|=C、S11=S41=0（Pozar (7.83)/(7.84)）。"""
    zee, zoo = 69.371, 36.038
    c = (zee - zoo) / (zee + zoo)
    zc = math.sqrt(zee * zoo)
    s = z_to_s(coupled_line_z_matrix(zee, zoo, math.pi / 2), [zc] * 4)
    assert abs(s[0, 0]) < 1e-12 and abs(s[3, 0]) < 1e-12
    assert abs(abs(s[2, 0]) - c) < 1e-12
    assert abs(abs(s[1, 0]) - math.sqrt(1.0 - c * c)) < 1e-12
    # 无耗互易
    assert np.max(np.abs(s.conj().T @ s - np.eye(4))) < 1e-12
    assert np.max(np.abs(s - s.T)) < 1e-12


def test_coupled_line_z_matrix_guards():
    with pytest.raises(ValueError):
        coupled_line_z_matrix(30.0, 50.0, 1.0)
    with pytest.raises(ValueError, match="奇异"):
        coupled_line_z_matrix(70.0, 36.0, math.pi)


# ─── ② 端口约束消元：解析对照 ───────────────────────────────────────────────────

@pytest.mark.parametrize("theta_deg", [20.0, 45.0, 70.0, 110.0])
def test_reduce_z_network_short_open_stub_analytic(theta_deg):
    """单段 TL：远端短路 Z_in=jZ0 tanθ；远端开路 Z_in=−jZ0 cotθ；内连两段=一段。"""
    z0, th = 73.0, math.radians(theta_deg)
    z2 = _tl_z2(z0, th)
    z_short = reduce_z_network(z2, external=(0,), shorts=(1,))
    z_open = reduce_z_network(z2, external=(0,), opens=(1,))
    assert abs(z_short[0, 0] - 1j * z0 * math.tan(th)) < 1e-9
    assert abs(z_open[0, 0] - (-1j * z0 / math.tan(th))) < 1e-9
    # 两段 θ/2 内连 → 与单段 θ 的二端口 Z 逐元素一致
    half = _tl_z2(z0, th / 2.0)
    z4 = np.zeros((4, 4), dtype=complex)
    z4[:2, :2] = half
    z4[2:, 2:] = half
    z_cas = reduce_z_network(z4, external=(0, 3), connections=((1, 2),))
    assert np.max(np.abs(z_cas - z2)) < 1e-9


def test_reduce_z_network_constraint_coverage_guard():
    z2 = _tl_z2(50.0, 1.0)
    with pytest.raises(ValueError, match="覆盖"):
        reduce_z_network(z2, external=(0,))
    with pytest.raises(ValueError, match="覆盖"):
        reduce_z_network(z2, external=(0,), shorts=(1,), opens=(1,))


@pytest.mark.parametrize("theta_deg", [30.0, 90.0, 135.0])
def test_reduce_to_s_matrix_matched_line_and_resonant_theta(theta_deg):
    """端接口径：匹配 TL 两端口 S21=e^{−jθ}、S11=0——含 θ=90°（开路激励口径在该处
    病态，reduce_z_network 文档警告；端接消元无此奇异）。"""
    z0, th = 50.0, math.radians(theta_deg)
    s = reduce_to_s_matrix(_tl_z2(z0, th), external=(0, 1), z_ref=(z0, z0))
    assert abs(s[0, 0]) < 1e-12 and abs(s[1, 1]) < 1e-12
    assert abs(s[1, 0] - np.exp(-1j * th)) < 1e-12
    with pytest.raises(ValueError, match="覆盖"):
        reduce_to_s_matrix(_tl_z2(z0, th), external=(0,), z_ref=(z0,))


def test_z_to_s_matched_load_and_reference_guard():
    assert abs(z_to_s(np.array([[50.0 + 0j]]), [50.0])[0, 0]) < 1e-15
    assert abs(z_to_s(np.array([[100.0 + 0j]]), [50.0])[0, 0] - 1.0 / 3.0) < 1e-12
    with pytest.raises(ValueError):
        z_to_s(np.array([[50.0 + 0j]]), [-50.0])


# ─── ③ Marchand f0 闭式 × 数值网络互证 ─────────────────────────────────────────

def test_conventional_design_point_reproduces_literature_numbers():
    """Z_s=Z_t=Z_c=50Ω → C=1/√3（−4.77dB）、(Z0e,Z0o)=(96.59,25.88)Ω（推导复现）。"""
    c = marchand_coupling_for_match(50.0, 50.0, 50.0)
    assert abs(c - 1.0 / math.sqrt(3.0)) < 1e-12
    assert abs(20.0 * math.log10(c) - (-4.7712)) < 1e-3
    ze, zo = even_odd_from_coupling(c, 50.0)
    assert abs(ze - 96.5926) < 1e-3 and abs(zo - 25.8819) < 1e-3
    assert abs(marchand_input_impedance_f0(ze, zo, 50.0) - 50.0) < 1e-9


@pytest.mark.parametrize("zs,zl,zc", [(50.0, 100.0, 50.0), (50.0, 280.0, 58.94),
                                      (75.0, 150.0, 40.0), (50.0, 100.0, 80.0)])
def test_closed_form_match_gives_numerical_s11_zero_at_f0(zs, zl, zc):
    """闭式匹配点：数值网络 S11(f0)=0、|S21|=|S31|=1/√2、相位差 180°、电流等幅反相。"""
    zt = zl / 2.0
    c = marchand_coupling_for_match(zs, zt, zc)
    ze, zo = even_odd_from_coupling(c, zc)
    s = marchand_two_section_sparams([2.5], 2.5, ze, zo, zs, zt)[0]
    assert abs(s[0, 0]) < 1e-9
    assert abs(abs(s[1, 0]) - 1 / math.sqrt(2)) < 1e-9
    assert abs(abs(s[2, 0]) - 1 / math.sqrt(2)) < 1e-9
    assert abs(s[1, 0] + s[2, 0]) < 1e-9            # 180° 反相
    assert np.max(np.abs(s.conj().T @ s - np.eye(3))) < 1e-9   # 无耗
    assert np.max(np.abs(s - s.T)) < 1e-9                       # 互易


def test_detuned_coupling_breaks_match():
    """匹配条件非平凡：C 偏离闭式值 20% → f0 处 |S11| 显著非零。"""
    zs, zt, zc = 50.0, 50.0, 50.0
    c = marchand_coupling_for_match(zs, zt, zc)
    ze, zo = even_odd_from_coupling(0.8 * c, zc)
    s = marchand_two_section_sparams([2.5], 2.5, ze, zo, zs, zt)[0]
    assert abs(s[0, 0]) > 0.05
    # 闭式 Z_in 与数值一致（失谐点也成立：Z_in 是恒等式而非匹配假设）
    z_in = marchand_input_impedance_f0(ze, zo, zt)
    gam = (z_in - zs) / (z_in + zs)
    assert abs(abs(s[0, 0]) - abs(gam)) < 1e-9


def test_marchand_sparams_guards():
    with pytest.raises(ValueError):
        marchand_two_section_sparams([0.0, 2.5], 2.5, 96.6, 25.9)
    with pytest.raises(ValueError):
        marchand_input_impedance_f0(25.0, 96.0, 50.0)
    with pytest.raises(ValueError):
        even_odd_from_coupling(1.0, 50.0)


# ─── ④ 几何：KJ 二维反解回代 ────────────────────────────────────────────────────

def test_kj_inverse_round_trip():
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    ze_t, zo_t = 95.214, 36.489
    w, s = coupled_microstrip_width_gap_from_even_odd(ze_t, zo_t, 2.5, 3.66, 1.524)
    ze, zo, _, _ = coupled_microstrip_even_odd_ohm(w, s, 2.5, 3.66, 1.524)
    assert abs(ze - ze_t) < 1e-5 and abs(zo - zo_t) < 1e-5
    with pytest.raises(ValueError):
        coupled_microstrip_width_gap_from_even_odd(30.0, 50.0, 2.5, 3.66, 1.524)
    # 常规 Marchand 点（96.59, 25.88）在 h=1.524 边耦合 KJ 域外 → 显式报错
    with pytest.raises(ValueError, match="可达域外"):
        coupled_microstrip_width_gap_from_even_odd(96.5926, 25.8819, 2.5, 3.66, 1.524)


# ─── ⑤ 综合：名义设计点 / 不可达如实 / 门 ─────────────────────────────────────

def test_nominal_design_realizable_and_passes_model_gates():
    d = marchand_two_section_nominal()
    assert isinstance(d, MarchandTwoSectionDesign)
    assert d.realizable is True
    assert d.s_mm >= MARCHAND2_NOMINAL_INPUTS["s_min_mm"]
    assert 0.5 < d.w_mm < 6.0
    assert abs(d.match_invariant_ohm - math.sqrt(50.0 * 140.0 / 2.0)) < 1e-9
    # KJ 严格回代
    assert abs(d.z0e_realized_ohm - d.z0e_ohm) < 1e-5
    assert abs(d.z0o_realized_ohm - d.z0o_ohm) < 1e-5
    m = d.model_metrics
    assert m["all_gates_pass"] is True
    assert m["band_max_s11_db"] <= MARCHAND2_GATES["band_max_s11_db_le"]
    assert m["band_max_abs_imbalance_db"] <= 0.1
    assert abs(m["s11_db_f0"]) > 80.0            # f0 精确匹配（数值底）
    assert abs(m["s21_db_f0"] - (-3.0103)) < 1e-3
    # 名义几何 4 位舍入且键集固定（渲染冒烟消费契约）
    nom = d.nominal_params()
    assert set(nom) == {"w_mm", "s_mm", "l_sect_mm", "w_feed_mm", "w_bal_line_mm",
                        "r_bal_se_ohm"}
    assert nom["l_sect_mm"] == round(d.l_sect_mm, 4)
    # 节长=λ/4@平均 εeff（闭式精算，#1c）
    lam = C0 / 2.5e9 / math.sqrt(0.5 * (d.ere_e + d.ere_o)) * 1e3
    assert abs(d.l_sect_mm - lam / 4.0) < 1e-9
    # 槽线平衡侧：Z_L=280Ω 越窄槽段可达范围（≈210Ω 上限）→ None 如实
    assert d.slot_balanced is None
    assert any("不可用" in n for n in d.notes)


def test_conventional_50_to_100_reported_unrealizable_not_raised():
    d = synthesize_marchand_two_section(2.5, 50.0, 100.0)
    assert d.realizable is False
    assert d.s_mm == pytest.approx(0.02)
    assert abs(d.coupling - 1.0 / math.sqrt(3.0)) < 1e-12
    assert d.z0o_realized_ohm > d.z0o_ohm          # 钳位点耦合弱于闭式所需
    assert "不可达" in d.notes[1]
    assert isinstance(d.model_metrics["all_gates_pass"], bool)


def test_slot_balanced_option_available_within_slotline_range():
    """Z_L=150Ω 落槽线闭式可达范围 → 槽宽+Roberts 过渡段参数回填（域内口径）。"""
    d = synthesize_marchand_two_section(2.5, 50.0, 150.0, s_min_mm=0.02)
    assert d.slot_balanced is not None
    opt = d.slot_balanced
    assert opt["z_slot_target_ohm"] == 150.0
    from rfauto.core.slotline import slotline_z0

    assert abs(slotline_z0(opt["w_slot_mm"], 1.524, 3.66, 2.5) - 150.0) < 0.05
    assert opt["transition"]["l_stub_mm"] > 0 and opt["transition"]["l_short_mm"] > 0


def test_synthesis_deterministic_and_explicit_zc():
    a = synthesize_marchand_two_section(2.5, 50.0, 280.0).to_dict()
    b = synthesize_marchand_two_section(2.5, 50.0, 280.0).to_dict()
    assert a == b
    d = synthesize_marchand_two_section(2.5, 50.0, 280.0, z_c_ohm=58.94)
    assert d.realizable is True and abs(d.z_c_ohm - 58.94) < 1e-12
    with pytest.raises(ValueError):
        synthesize_marchand_two_section(2.5, -50.0, 280.0)


def test_metrics_gate_keys_and_band():
    d = marchand_two_section_nominal()
    f = np.linspace(2.0, 3.0, 101)
    s3 = marchand_two_section_sparams(f, 2.5, d.z0e_ohm, d.z0o_ohm, 50.0, 140.0)
    m = marchand_two_section_metrics(f * 1e9, s3, (2.25, 2.75))
    assert set(m["gates"]) == {"band_max_s11_le_minus10db", "band_min_s21_ge_minus3p5db",
                               "band_min_s31_ge_minus3p5db", "amp_imbalance_le_1db",
                               "phase_error_le_10deg"}
    assert m["band_ghz"] == [2.25, 2.75]
    assert abs(m["phase_diff_deg_f0"]) == pytest.approx(180.0, abs=1e-6)


# ─── ⑥ 逐引擎修正（engine="reference"|"openems"，2026-09-18 marchand_line_calibration 标定）──

#: 改前基线 SHA256（本项改码前捕获）：缺省 reference 输出逐字节钉。
#: C6 开路支节符号修正（2026-09-21，l_stub λg/4+Δl→λg/4−Δl）后重算：slot_balanced
#: 路径两例哈希随 transition.l_stub_mm（18.3725→17.1253）与 notes 数值回显合法变更
#: （对拍 HEAD 实证全 dict 仅此两字段移动）；nominal/explicit_zc 不含 transition 档、
#: 哈希不变。
_REFERENCE_SHA256 = {
    "nominal": "f2f424575c678c0807bc576bfe703abcc721a5bc33f341aa96fc3f90ef85f073",
    "unreal_50to100": "fe3452d3d2185d263c65c90003f88c99e6190f19d7cf54145871d4e7051a07bf",
    "slot_50to150": "cb47100120264c45c14e6600fb8781f179a4c01082110c7571bbfdf424dec2da",
    "explicit_zc_58p94": "eb2211a9ac388c0317925454a1649a5c9561b59d0a63a8378f86eda733c2cb59",
}


def _design_sha256(design: MarchandTwoSectionDesign) -> str:
    payload = json.dumps(design.to_dict(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_reference_mode_output_sha256_unchanged():
    """缺省 reference 档 = 改前逐字节不变（SHA256 对拍改前基线，交付门）。"""
    cases = {
        "nominal": marchand_two_section_nominal(),
        "unreal_50to100": synthesize_marchand_two_section(2.5, 50.0, 100.0),
        "slot_50to150": synthesize_marchand_two_section(2.5, 50.0, 150.0, s_min_mm=0.02),
        "explicit_zc_58p94": synthesize_marchand_two_section(2.5, 50.0, 280.0, z_c_ohm=58.94),
    }
    for key, design in cases.items():
        assert _design_sha256(design) == _REFERENCE_SHA256[key], key


def test_engine_z0_correction_four_points_monotone_clamped():
    """修正曲线：4 点标定回代精确（PCHIP 过节点）；域内单调增且全负；域外钳端点；w≤0 报错。"""
    for w, dev in MARCHAND_OPENEMS_Z0_DEV_CAL:
        assert engine_z0_correction(w) == pytest.approx(dev, rel=1e-12, abs=1e-15)
    lo, hi = MARCHAND_OPENEMS_W_DOMAIN_MM
    ws = np.geomspace(lo, hi, 60)
    devs = [engine_z0_correction(float(w)) for w in ws]
    assert all(b > a for a, b in itertools.pairwise(devs))          # 窄线更负 → 随 w 单调回升
    assert all(d < 0.0 for d in devs)                          # 引擎全线偏低阻
    assert engine_z0_correction(0.05) == engine_z0_correction(lo)   # 域外钳制（不外推）
    assert engine_z0_correction(50.0) == engine_z0_correction(hi)
    with pytest.raises(ValueError):
        engine_z0_correction(0.0)


def test_marchand_engine_param_guard():
    with pytest.raises(ValueError, match="engine"):
        synthesize_marchand_two_section(2.5, 50.0, 280.0, engine="hfss")
    a = synthesize_marchand_two_section(2.5, 50.0, 280.0)
    b = synthesize_marchand_two_section(2.5, 50.0, 280.0, engine="reference")
    assert a.to_dict() == b.to_dict()


def test_marchand_openems_design_w_shift_hand_check():
    """openems 档设计 w 位移手算：前向 brentq 独立求根 + 定点定义前向回代
    （测试走 forward 模型，独立于 production 的 inverse_width 逆解定点路径）。"""
    from scipy.optimize import brentq

    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm
    from rfauto.core.synthesis import Stackup, forward_z0

    d_ref = synthesize_marchand_two_section(2.5, 50.0, 280.0, z_c_ohm=50.0)
    d_eng = synthesize_marchand_two_section(2.5, 50.0, 280.0, z_c_ohm=50.0,
                                            engine="openems")
    assert d_ref.realizable and d_eng.realizable
    # 引擎低阻偏置（dev<0）⇒ KJ 目标上抬 ⇒ 同 Z_c 下设计宽变窄、KJ 回代阻抗升高
    assert d_eng.w_mm < d_ref.w_mm
    assert d_eng.z0e_realized_ohm > d_ref.z0e_realized_ohm
    # 定点定义前向回代：KJ(w,s)·(1+dev(w)) ≈ 设计目标（引擎期望阻抗=目标）
    ze_kj, zo_kj, _, _ = coupled_microstrip_even_odd_ohm(
        d_eng.w_mm, d_eng.s_mm, 2.5, 3.66, 1.524)
    k = 1.0 + engine_z0_correction(d_eng.w_mm)
    assert ze_kj * k == pytest.approx(d_eng.z0e_ohm, rel=1e-6)
    assert zo_kj * k == pytest.approx(d_eng.z0o_ohm, rel=1e-6)
    # w_feed 位移手算：前向 brentq 求 engine(w)=Z_HJ(w)·(1+dev(w))=50Ω（独立代码路径）
    # stackup 必须与 production 同款（含 loss_tangent=0.0037，否则 tanδ 差异致 w 偏 ~0.005mm）
    stack = Stackup(name="marchand2", epsilon_r=3.66, thickness_mm=1.524,
                    loss_tangent=0.0037)
    w_feed_manual = brentq(
        lambda w: forward_z0(w, 2.5, stack)[0] * (1.0 + engine_z0_correction(w)) - 50.0,
        0.05, 20.0, xtol=1e-10)
    assert d_eng.w_feed_mm == pytest.approx(w_feed_manual, abs=1e-5)
    assert d_eng.w_feed_mm < d_ref.w_feed_mm
    # β 常数修正：节长=λ/4@平均 εeff ÷ (1+0.02)（β_engine=β_HJ·1.02 ⇒ 电长度更长）
    lam = C0 / 2.5e9 / math.sqrt(0.5 * (d_eng.ere_e + d_eng.ere_o)) * 1e3
    assert d_eng.l_sect_mm == pytest.approx(
        lam / 4.0 / (1.0 + MARCHAND_OPENEMS_BETA_DEV), rel=1e-9)
    # 扫描档：修正目标在 zc≈59 区需缝 <s_min → Z_c 推到更弱耦合点；门按引擎期望阻抗仍 PASS
    d_scan_ref = synthesize_marchand_two_section(2.5, 50.0, 280.0)
    d_scan_eng = synthesize_marchand_two_section(2.5, 50.0, 280.0, engine="openems")
    assert d_scan_eng.realizable is True
    assert d_scan_eng.z_c_ohm < d_scan_ref.z_c_ohm
    assert d_scan_eng.model_metrics["all_gates_pass"] is True
    assert d_scan_eng.model_metrics["s11_db_f0"] < -100.0
    # 注记：修正模型/适用域/外推声明/域外钳制（w_bal 修正落标定域下界外 0.187mm）
    joined = "；".join(d_scan_eng.notes)
    assert "openEMS 逐引擎修正" in joined
    assert "外推" in joined and "直微带单线" in joined
    assert "钳" in joined


def test_marchand_openems_unrealizable_and_explicit_zc_fallback():
    """不可达如实：50→100 openems 档仍 realizable=False；显式 zc=58.94 的修正目标需
    缝 <s_min → 钳位回退不做预畸变（注记声明，门 FAIL 如实不凑绿）。"""
    d = synthesize_marchand_two_section(2.5, 50.0, 100.0, engine="openems")
    assert d.realizable is False
    assert d.s_mm == pytest.approx(0.02)
    assert "未做预畸变" in d.notes[-1]
    d5894 = synthesize_marchand_two_section(2.5, 50.0, 280.0, z_c_ohm=58.94,
                                            engine="openems")
    assert d5894.realizable is False
    assert d5894.s_mm == pytest.approx(0.02)
    assert "未做预畸变" in d5894.notes[-1]
    assert d5894.model_metrics["all_gates_pass"] is False
