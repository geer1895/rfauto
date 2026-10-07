"""M-6 bias tee 直流馈电网络内核单测（研究扩充 M-6 判据）。

裁判口径（#118 双路径）：S 面裁判 = 测试内独立 ABCD 级联路径（与内核的
节点导纳 stamping 完全不同代码路径），恒等式 |S21(f_corner)| = 1/√2 由
ABCD 手推逐位钉死（f_c 处 Zc=−jZ0、扼流支路 Z0+jZ0，Δ=Z0(2−2j)）；
泄漏带缘恒等式 f_lo≈f_c/100、f_hi≈100f_c（高频渐近 |S_dc,rf|≈Z0/ωL，
低频渐近 ≈ωC·Z0，修正 O(0.01²)≈1e-4，断言 rel=0.02 容纳网格插值）。
"""
from __future__ import annotations

import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import bias_tee as bt

FC = 100e6  # 设计拐点 100 MHz
Z0 = 50.0
SYN = bt.synthesize_bias_tee(FC, Z0)


# ─── 独立裁判路径：2 端口 ABCD（rf→comb，dc 端接 Z0）────────────────────────


def _abcd_face(f_hz: float, l_h: float, c_f: float, par: bt.BiasTeeParasitics, z0: float):
    """测试内独立推导的 ABCD 面（公式与内核 stamping 无共享代码）。"""
    w = 2.0 * math.pi * f_hz
    zc = par.block_esr_ohm + 1.0 / (1j * w * c_f) + 1j * w * par.block_esl_h
    z_ser = par.choke_esr_ohm + 1j * w * l_h
    if par.choke_cp_f > 0.0:
        z_par = 1.0 / (1j * w * par.choke_cp_f)
        zl = z_ser * z_par / (z_ser + z_par)
    else:
        zl = z_ser
    yb = 1.0 / (zl + z0)
    a, b, c, d = (1.0 + zc * yb), zc, yb, 1.0
    delta = a * z0 + b + c * z0 * z0 + d * z0
    s21 = 2.0 * z0 / delta
    s11 = (a * z0 + b - c * z0 * z0 - d * z0) / delta
    return s11, s21


# ─── 1. 综合闭式：解析回收钉 ─────────────────────────────────────────────────


def test_synth_closed_form_recycle():
    assert SYN.l_choke_h == pytest.approx(Z0 / (2.0 * math.pi * FC), rel=1e-12)
    assert SYN.c_block_f == pytest.approx(1.0 / (2.0 * math.pi * Z0 * FC), rel=1e-12)
    # 第二组参数防复制粘贴
    syn2 = bt.synthesize_bias_tee(2.4e9, 75.0)
    assert syn2.l_choke_h == pytest.approx(75.0 / (2.0 * math.pi * 2.4e9), rel=1e-12)
    assert syn2.c_block_f == pytest.approx(1.0 / (2.0 * math.pi * 75.0 * 2.4e9), rel=1e-12)


def test_synth_corner_impedance_identities():
    # 恒等式①②：1/(2π√(LC)) == f_corner、√(L/C) == Z0（docstring 设计方程）
    for fc, z0 in ((1e6, 50.0), (100e6, 50.0), (2.4e9, 75.0), (10e3, 300.0)):
        syn = bt.synthesize_bias_tee(fc, z0)
        corner = 1.0 / (2.0 * math.pi * math.sqrt(syn.l_choke_h * syn.c_block_f))
        assert corner == pytest.approx(fc, rel=1e-12)
        assert math.sqrt(syn.l_choke_h / syn.c_block_f) == pytest.approx(z0, rel=1e-12)


def test_synth_dc_current_selection():
    syn = bt.synthesize_bias_tee(FC, Z0, dc_current_a=0.5, isat_margin=0.2)
    assert syn.required_isat_a == pytest.approx(0.6, rel=1e-12)
    assert syn.dc_current_a == 0.5
    syn_none = bt.synthesize_bias_tee(FC, Z0)
    assert syn_none.required_isat_a is None and syn_none.dc_current_a is None  # 判缺失 is not None 口径
    with pytest.raises(ValueError):
        bt.synthesize_bias_tee(FC, Z0, dc_current_a=0.0)
    with pytest.raises(ValueError):
        bt.synthesize_bias_tee(FC, Z0, dc_current_a=True)  # bool 拒收（df7+⑯）


def test_synth_input_guards():
    for args in ((0.0, Z0), (-1.0, Z0), (float("nan"), Z0), (FC, 0.0), (FC, -50.0)):
        with pytest.raises(ValueError):
            bt.synthesize_bias_tee(*args)
    with pytest.raises(ValueError):
        bt.synthesize_bias_tee(True, Z0)


# ─── 2. 三端口 S 面：酉性/互易性/无源性 ──────────────────────────────────────


def test_s_unitary_lossless():
    freqs = np.logspace(6, 10, 41)
    s = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f)
    for i in range(freqs.size):
        err = np.max(np.abs(s[i].conj().T @ s[i] - np.eye(3)))
        assert err < 1e-10, f"非酉 @ {freqs[i]:.3g} Hz: {err}"


def test_s_reciprocal_with_parasitics():
    par = bt.BiasTeeParasitics(
        choke_esr_ohm=0.5, choke_cp_f=0.3e-12, block_esr_ohm=0.05, block_esl_h=0.2e-9
    )
    freqs = np.array([1e6, 1e7, 1e8, 1e9, 1e10])
    s = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f, par)
    assert np.max(np.abs(s - np.swapaxes(s, 1, 2))) < 1e-12


def test_s_passive_with_esr():
    par = bt.BiasTeeParasitics(choke_esr_ohm=1.0, block_esr_ohm=0.5)
    freqs = np.logspace(6, 10, 25)
    s = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f, par)
    norms = np.sum(np.abs(s) ** 2, axis=1)  # 逐激励端口行功率
    assert float(np.max(norms)) <= 1.0 + 1e-12
    assert float(np.max(norms)) < 1.0 - 1e-6  # 有耗 → 严格无源


# ─── 3. 极限行为（物理恒等式）────────────────────────────────────────────────


def test_low_freq_limits():
    s = bt.bias_tee_s(np.array([FC * 1e-4]), SYN.l_choke_h, SYN.c_block_f)[0]
    assert abs(abs(s[0, 0]) - 1.0) < 1e-6  # rf 口：隔直开路 → 全反射 |Γ|=1
    assert abs(s[2, 0]) < 1e-3  # rf→comb 被阻断（渐近 ≈2ωC·Z0=2e-4）
    assert abs(abs(s[2, 1]) - 1.0) < 1e-6  # dc→comb：扼流短路直通
    assert abs(s[1, 1]) < 1e-7  # dc 口匹配
    assert abs(s[1, 0]) < 1e-3  # rf→dc 泄漏被隔直电容阻挡（渐近 ≈ωC·Z0=1e-4）


def test_high_freq_limits():
    s = bt.bias_tee_s(np.array([FC * 1e4]), SYN.l_choke_h, SYN.c_block_f)[0]
    assert abs(abs(s[2, 0]) - 1.0) < 1e-6  # rf→comb 直通（扼流开路）
    assert abs(s[0, 0]) < 1e-7  # rf 口匹配
    assert abs(s[2, 1]) < 1e-3  # dc→comb 被扼流阻断（渐近 ≈2Z0/ωL=2e-4）
    assert abs(abs(s[1, 1]) - 1.0) < 1e-6  # dc 口全反射（开路）
    assert abs(s[1, 0]) < 1e-3  # rf→dc 泄漏被扼流阻挡（渐近 ≈Z0/ωL=1e-4）


# ─── 4. 双路径对拍（#118）：内核 stamping vs 独立 ABCD ───────────────────────


def test_dual_path_abcd_grid_ideal():
    factors = np.array([0.01, 0.1, 0.5, 1.0, 2.0, 10.0, 100.0])
    freqs = factors * FC
    s = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f)
    for i, f in enumerate(freqs):
        s11_ref, s21_ref = _abcd_face(float(f), SYN.l_choke_h, SYN.c_block_f, bt.BiasTeeParasitics(), Z0)
        assert s[i, 2, 0] == pytest.approx(s21_ref, abs=1e-9)
        assert s[i, 0, 0] == pytest.approx(s11_ref, abs=1e-9)


def test_corner_exact_insertion_loss_identity():
    # 手推恒等式：f_c 处 Zc=−jZ0、扼流支路 Z0+jZ0 → |S21| = 1/√2（−3.01 dB）
    s = bt.bias_tee_s(np.array([FC]), SYN.l_choke_h, SYN.c_block_f)
    assert abs(s[0, 2, 0]) == pytest.approx(1.0 / math.sqrt(2.0), rel=1e-10)


def test_dual_path_abcd_grid_parasitics():
    par = bt.BiasTeeParasitics(
        choke_esr_ohm=0.8, choke_cp_f=0.25e-12, block_esr_ohm=0.03, block_esl_h=0.1e-9
    )
    factors = np.array([0.05, 0.3, 1.0, 5.0, 50.0])
    freqs = factors * FC
    s = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f, par)
    for i, f in enumerate(freqs):
        _, s21_ref = _abcd_face(float(f), SYN.l_choke_h, SYN.c_block_f, par, Z0)
        assert s[i, 2, 0] == pytest.approx(s21_ref, abs=1e-9)


# ─── 5. DC 端口 RF 泄漏 −40dB 带恒等式（任务书判据）─────────────────────────


def test_leakage_band_edge_identity():
    f_lo_t = FC / 1e4
    f_hi_t = FC * 1e4
    freqs = np.logspace(math.log10(f_lo_t), math.log10(f_hi_t), 8001)
    s = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f)
    band = bt.leakage_band(freqs, s, 40.0)
    assert band["f_lo_edge_hz"] == pytest.approx(FC / 100.0, rel=0.02)
    assert band["f_hi_edge_hz"] == pytest.approx(FC * 100.0, rel=0.02)
    assert band["n_satisfied"] > 0
    # 解析式独立通道：rf_dc_isolation_high_corner = 10^(40/20)·Z0/(2πL) = 100·f_c
    assert bt.rf_dc_isolation_high_corner(SYN.l_choke_h, Z0, 40.0) == pytest.approx(
        FC * 100.0, rel=1e-12
    )


def test_leakage_band_unresolved_sides_none():
    # 网格只覆盖泄漏峰区（中段）→ 两侧带不在网格内，如实 None（不硬凑）
    freqs = np.logspace(math.log10(FC / 3.0), math.log10(FC * 3.0), 201)
    s = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f)
    band = bt.leakage_band(freqs, s, 40.0)
    assert band["f_lo_edge_hz"] is None
    assert band["f_hi_edge_hz"] is None
    assert band["n_satisfied"] == 0
    assert band["peak_isolation_db"] < 40.0
    # 峰值隔离（最低泄漏的反面）落在网格边缘——该区间隔离度最差处应在 f_c 附近，
    # 用隔离度最小值位置核对（argmin face_db）
    iso = bt.face_db(s, "rf", "dc")
    assert freqs[int(np.argmin(iso))] == pytest.approx(FC, rel=0.05)


def test_leakage_band_input_guard():
    freqs = np.array([FC, 2 * FC])
    s = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f)
    with pytest.raises(ValueError):
        bt.leakage_band(freqs, s, float("nan"))  # 非有限 threshold 拒收
    with pytest.raises(ValueError):
        bt.leakage_band(freqs, s, True)  # bool 拒收（df7+⑯）
    with pytest.raises(ValueError):
        bt.leakage_band(np.array([0.0, 1.0]), s, 40.0)
    with pytest.raises(ValueError):
        bt.leakage_band(True, s, 40.0)


# ─── 6. 寄生敏感性（M-6 判据：S21 高端滚降 vs SRF 单调）──────────────────────


def test_choke_srf_monotonicity():
    # 扼流 Cp 减（SRF 升）→ 同一高频探针 |S21| 严格单调改善
    probe = np.array([8e9])
    mags = []
    for srf in (1e9, 2e9, 4e9, 8e9):
        cp = 1.0 / ((2.0 * math.pi * srf) ** 2 * SYN.l_choke_h)
        par = bt.BiasTeeParasitics(choke_cp_f=cp)
        assert bt.choke_srf_hz(SYN.l_choke_h, cp) == pytest.approx(srf, rel=1e-12)
        s = bt.bias_tee_s(probe, SYN.l_choke_h, SYN.c_block_f, par)
        mags.append(abs(s[0, 2, 0]))
    assert all(b > a for a, b in pairwise(mags))


def test_block_esl_high_end_rolloff():
    # 隔直 ESL 增（电容 SRF 降）→ 高端 |S21| 严格单调恶化（自谐振限制高端）
    probe = np.array([5e9])
    mags = []
    for srf in (1e9, 2e9, 4e9, 8e9):
        esl = 1.0 / ((2.0 * math.pi * srf) ** 2 * SYN.c_block_f)
        par = bt.BiasTeeParasitics(block_esl_h=esl)
        assert bt.block_srf_hz(SYN.c_block_f, esl) == pytest.approx(srf, rel=1e-12)
        s = bt.bias_tee_s(probe, SYN.l_choke_h, SYN.c_block_f, par)
        mags.append(abs(s[0, 2, 0]))
    assert all(b > a for a, b in pairwise(mags))  # srf 升序=ESL 降序 → S21 单调升


def test_esr_degradation_faces():
    # 隔直 ESR 串在 rf 路径 → 插损只恶化（串联电阻单调性）
    par_block = bt.BiasTeeParasitics(block_esr_ohm=1.0)
    freqs = np.logspace(6, 10, 61)
    s_ideal = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f)
    s_esr = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f, par_block)
    il_ideal = bt.face_db(s_ideal, "rf", "comb")
    il_esr = bt.face_db(s_esr, "rf", "comb")
    assert float(np.min(il_esr - il_ideal)) > -1e-9  # ESR 只恶化插损
    assert float(np.max(il_esr - il_ideal)) > 0.05  # 且在带内严格可见
    # 扼流 ESR 进入 DC 馈通路径 → 低频 |S[comb,dc]| < 1（DC 串联电阻如实呈现）
    par_choke = bt.BiasTeeParasitics(choke_esr_ohm=2.0)
    s_low = bt.bias_tee_s(np.array([FC * 1e-4]), SYN.l_choke_h, SYN.c_block_f, par_choke)[0]
    assert abs(s_low[2, 1]) < 1.0 - 1e-6
    assert abs(s_low[2, 1]) > 0.9  # ESR=2Ω 对 50Ω 系统仍是小损耗


# ─── 7. vendor 联动（选型/寄生反推）──────────────────────────────────────────


def _candidates():
    return (
        bt.InductorCandidate("L1", l_h=10e-9, isat_a=0.2, esr_ohm=0.1, srf_hz=2e9),
        bt.InductorCandidate("L2", l_h=80e-9, isat_a=1.0, esr_ohm=0.3, srf_hz=1e9),
        bt.InductorCandidate("L3", l_h=100e-9, isat_a=0.4, esr_ohm=0.4, srf_hz=0.5e9),
    )


def test_select_choke_filter_and_nearest():
    # SYN.l_choke_h ≈ 79.6 nH；isat ≥ 0.5 A → 只有 L2 合格
    sel = bt.select_choke(list(_candidates()), SYN.l_choke_h, min_isat_a=0.5)
    assert sel.part_id == "L2"
    assert sel.log_deviation == pytest.approx(abs(math.log(80e-9 / SYN.l_choke_h)), rel=1e-12)
    # 放宽电流 → 数量级最近（L3 100nH vs L2 80nH：|log(80/79.6)| < |log(100/79.6)|）
    sel2 = bt.select_choke(list(_candidates()), SYN.l_choke_h, min_isat_a=0.3)
    assert sel2.part_id == "L2"
    # 电流要求无人满足 → part_id None + reason（不硬凑）
    sel3 = bt.select_choke(list(_candidates()), SYN.l_choke_h, min_isat_a=10.0)
    assert sel3.part_id is None and "isat_a" in sel3.reason
    assert bt.select_choke([], SYN.l_choke_h).part_id is None


def test_select_block_cap_and_parasitics_from_parts():
    caps = (
        bt.CapacitorCandidate("C1", c_f=10e-12, rated_v=50.0, esr_ohm=0.01, srf_hz=4e9),
        bt.CapacitorCandidate("C2", c_f=100e-12, rated_v=16.0, esr_ohm=0.02, srf_hz=2e9),
    )
    sel = bt.select_block_cap(list(caps), SYN.c_block_f, min_rated_v=25.0)
    assert sel.part_id == "C1"  # C2 耐压不足被滤除
    choke = bt.InductorCandidate("L2", l_h=80e-9, isat_a=1.0, esr_ohm=0.3, srf_hz=1e9)
    par = bt.parasitics_from_parts(choke, caps[1])
    # SRF→寄生反推与 vendor_passives 同式：Cp = 1/((2πf_srf)²L)、ESL = 1/((2πf_srf)²C)
    assert par.choke_cp_f == pytest.approx(1.0 / ((2.0 * math.pi * 1e9) ** 2 * 80e-9), rel=1e-12)
    assert par.block_esl_h == pytest.approx(1.0 / ((2.0 * math.pi * 2e9) ** 2 * 100e-12), rel=1e-12)
    assert par.choke_esr_ohm == 0.3 and par.block_esr_ohm == 0.02
    # SRF 缺失（None）→ 寄生记 0 如实（未知不虚构）
    par_none = bt.parasitics_from_parts(
        bt.InductorCandidate("Lx", l_h=1e-6), bt.CapacitorCandidate("Cx", c_f=1e-9)
    )
    assert par_none.choke_cp_f == 0.0 and par_none.block_esl_h == 0.0


# ─── 8. 级联消费面与打包 ─────────────────────────────────────────────────────


def test_two_port_face_and_cascade_chain():
    # M-6 判据③的核内最小形态：(rf, comb) 2 端口面可与链上级联。
    # 双路径：交互式公式 vs 测试内 S→ABCD 转换 + emi_filter 矩阵级联 → S。
    from rfauto.core.emi_filter import abcd_cascade, abcd_series, abcd_to_s

    def s_to_abcd(s_mat: np.ndarray) -> np.ndarray:
        """测试内独立 S→ABCD（等实 z0，Pozar §4.4 逆变换）。"""
        out = np.zeros((*s_mat.shape[:-2], 2, 2), dtype=complex)
        s11, s12 = s_mat[..., 0, 0], s_mat[..., 0, 1]
        s21, s22 = s_mat[..., 1, 0], s_mat[..., 1, 1]
        den = 2.0 * s21
        out[..., 0, 0] = ((1 + s11) * (1 - s22) + s12 * s21) / den
        out[..., 0, 1] = Z0 * ((1 + s11) * (1 + s22) - s12 * s21) / den
        out[..., 1, 0] = ((1 - s11) * (1 - s22) - s12 * s21) / (den * Z0)
        out[..., 1, 1] = ((1 - s11) * (1 + s22) + s12 * s21) / den
        return out

    freqs = np.array([1e8, 1e9])
    s3 = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f)
    face = bt.two_port_face(s3)
    assert face.shape == (2, 2, 2)
    rf, comb = bt.port_index("rf"), bt.port_index("comb")
    assert np.array_equal(face[:, 0, 0], s3[:, rf, rf])
    assert np.array_equal(face[:, 1, 0], s3[:, comb, rf])
    # 与后级串联元件级联：路径 1 = 交互式公式 S21_tot = S21A·S21B/(1−S22A·S11B)
    zs = 20.0 + 5j
    b_series = abcd_series(np.full(freqs.shape, zs))
    s_b = abcd_to_s(b_series, Z0, Z0)
    expect = face[:, 1, 0] * s_b[:, 1, 0] / (1.0 - face[:, 1, 1] * s_b[:, 0, 0])
    # 路径 2 = S→ABCD → 矩阵级联 → S
    s_tot = abcd_to_s(abcd_cascade(s_to_abcd(face), b_series), Z0, Z0)
    assert np.max(np.abs(s_tot[:, 1, 0] - expect)) < 1e-10


def test_port_index_and_face_db_guards():
    with pytest.raises(ValueError):
        bt.port_index("antenna")
    with pytest.raises(ValueError):
        bt.bias_tee_s(np.array([-1.0]), 1e-8, 1e-11)
    with pytest.raises(ValueError):
        bt.bias_tee_s(True, 1e-8, 1e-11)
    with pytest.raises(ValueError):
        bt.bias_tee_s(np.array([1e6]), 0.0, 1e-11)
    with pytest.raises(ValueError):
        bt.bias_tee_s(np.array([1e6]), 1e-8, 0.0)
    with pytest.raises(ValueError):
        bt.bias_tee_s(np.array([1e6]), 1e-8, 1e-11, z0_ohm=0.0)
    with pytest.raises(ValueError):
        bt.bias_tee_s(np.array([1e6]), 1e-8, 1e-11, parasitics="bad")
    with pytest.raises(ValueError):
        bt.face_db(np.zeros((2, 4, 4)), "rf", "dc")


def test_to_dict_roundtrip():
    d = SYN.to_dict()
    assert d["l_choke_h"] == SYN.l_choke_h and d["required_isat_a"] is None
    par = bt.BiasTeeParasitics(choke_esr_ohm=0.1, block_esl_h=1e-10)
    par2 = bt.BiasTeeParasitics.from_dict(par.to_dict())
    assert par2 == par
    resp = bt.bias_tee_response(np.array([1e6, 1e8, 1e10]), SYN.l_choke_h, SYN.c_block_f)
    rd = resp.to_dict(max_points=2)
    assert rd["port_order"] == ["rf", "dc", "comb"]
    assert len(rd["f_ghz"]) <= 3 and len(rd["s_db"]) == len(rd["f_ghz"])
    sel = bt.select_choke(list(_candidates()), SYN.l_choke_h, min_isat_a=0.5).to_dict()
    assert sel["part_id"] == "L2"


# ─── 9. service 薄壳（JSON 信封 ok=False 不抛）───────────────────────────────


def test_bias_tee_service_report_ok():
    from rfauto.service.bias_tee_service import bias_tee_report

    out = bias_tee_report({"f_corner_hz": FC})
    assert out["ok"] is True
    # 理想回收恒等式经 service 面仍逐位（两比值恒 1）
    assert out["identity"]["corner_ratio"] == pytest.approx(1.0, rel=1e-12)
    assert out["identity"]["impedance_ratio"] == pytest.approx(1.0, rel=1e-12)
    assert len(out["faces"]["f_ghz"]) <= 400
    assert out["leakage_band"]["f_hi_edge_hz"] == pytest.approx(FC * 100.0, rel=0.05)
    assert out["analytic_hi_corner_hz"] == pytest.approx(FC * 100.0, rel=1e-12)
    # 带 DC 电流选型下界
    out2 = bias_tee_report({"f_corner_hz": FC, "dc_current_a": 0.5})
    assert out2["synthesis"]["required_isat_a"] == pytest.approx(0.6, rel=1e-12)


def test_bias_tee_service_envelope_errors():
    from rfauto.service.bias_tee_service import bias_tee_report

    for bad in (
        None,
        {},
        {"f_corner_hz": -1.0},
        {"f_corner_hz": True},
        {"f_corner_hz": FC, "freq_span": [1.0, 2.0]},
        {"f_corner_hz": FC, "freq_span": [10.0, 2.0, 101]},
        {"f_corner_hz": FC, "threshold_db": float("nan")},
        {"f_corner_hz": FC, "parasitics": {"choke_esr_ohm": -1.0}},
    ):
        out = bias_tee_report(bad)
        assert out["ok"] is False and out["errors"], f"应 ok=False: {bad!r}"


# ─── 10. mutmut 盲区补测（wf:mutmut-fix：负分支/缺省实参/序列化契约）─────────
#
# 口径三条（#118）：断言钉行为不钉实现；期望值独立于被测分支推导；
# 小值比值断言替代 pytest.approx 裸 rel（其含隐式 abs=1e-12 地板，
# 对 <1e-12 的寄生量纲会放过"值被换成 0"的回归——本节一律 /期望值 比值化）。


def _iso_s(iso_db, frm: str = "rf", to: str = "dc") -> np.ndarray:
    """合成 S 面：使 face_db(s, frm, to) 恰等于 iso_db 序列（其余条目置 1）。

    10^(-40/20)=0.01 经 np.log10 回程恰为 40.0（10 的整数次幂对数逐位
    精确，venv 预检实测），故阈值边界语义可用精确相等探针。
    """
    iso = np.asarray(iso_db, dtype=float)
    s = np.ones((iso.size, 3, 3), dtype=complex)
    s[:, bt.port_index(to), bt.port_index(frm)] = 10.0 ** (-iso / 20.0)
    return s


def test_default_arguments_contract():
    """缺省实参即契约：threshold_db=40、esr/cp/esl=0、parasitics=None 逐位钉。"""
    # leakage_band / rf_dc_isolation_high_corner 缺省 40 dB 与显式传参逐键一致
    freqs = np.logspace(math.log10(FC / 1e4), math.log10(FC * 1e4), 801)
    s = bt.bias_tee_s(freqs, SYN.l_choke_h, SYN.c_block_f)
    assert bt.leakage_band(freqs, s) == bt.leakage_band(freqs, s, 40.0)
    assert bt.rf_dc_isolation_high_corner(SYN.l_choke_h, Z0) == pytest.approx(
        FC * 100.0, rel=1e-12
    )
    # choke/block 阻抗缺省 esr=0、cp/esl=0 → 纯电抗闭式（实部恒 0、虚部同式）
    f = np.array([1e6, 1e8])
    z_ch = bt.choke_impedance(f, SYN.l_choke_h)
    assert np.all(z_ch.real == 0.0)
    assert z_ch.imag == pytest.approx(2.0 * np.pi * f * SYN.l_choke_h, rel=1e-15)
    z_bl = bt.block_impedance(f, SYN.c_block_f)
    assert np.all(z_bl.real == 0.0)
    assert z_bl.imag == pytest.approx(-1.0 / (2.0 * np.pi * f * SYN.c_block_f), rel=1e-15)


def test_freq_array_convergence():
    """频率轴收敛契约：int 入参收敛 float64、标量升 (n,)、(0,1] Hz 合法。"""
    arr = bt._freq_array([1, 2, 3])  # int 列表必须收敛 float（下游 ω 运算口径）
    assert arr.dtype == np.float64
    assert np.array_equal(arr, np.array([1.0, 2.0, 3.0]))
    assert bt._freq_array(1e9).shape == (1,)
    assert float(bt._freq_array(np.array([0.5]))[0]) == 0.5  # 正有限即可，无 1 Hz 下限
    for bad in (np.array([0.0]), np.array([-1.0]), np.array([]), True, float("nan")):
        with pytest.raises(ValueError):
            bt._freq_array(bad)


def test_parasitics_dict_contract():
    """Parasitics 序列化契约：四键全非零 roundtrip + 缺省键/显式 0.0/负值分支。"""
    par = bt.BiasTeeParasitics(
        choke_esr_ohm=0.1, choke_cp_f=0.2e-12, block_esr_ohm=0.3, block_esl_h=0.4e-9
    )
    d = par.to_dict()
    assert set(d) == {"choke_esr_ohm", "choke_cp_f", "block_esr_ohm", "block_esl_h"}
    for k, v in d.items():
        assert v == getattr(par, k)
    assert bt.BiasTeeParasitics.from_dict(d) == par  # 四字段全非零才算真 roundtrip
    # 缺省键 = 全零理想元件；None 同
    assert bt.BiasTeeParasitics.from_dict({}) == bt.BiasTeeParasitics()
    assert bt.BiasTeeParasitics.from_dict(None) == bt.BiasTeeParasitics()
    # 0.0 是合法值（#364④）：显式 0.0 不得被 or-缺省/真值分支顶替成非零
    par_zero = bt.BiasTeeParasitics.from_dict({"choke_esr_ohm": 0.0, "block_esl_h": 0.0})
    assert par_zero.choke_esr_ohm == 0.0
    assert par_zero.block_esl_h == 0.0
    with pytest.raises(ValueError):
        bt.BiasTeeParasitics.from_dict({"choke_cp_f": -1.0})


def test_synthesis_to_dict_contract():
    """Synthesis 序列化契约：七键集合 + 有/无 dc_current 两路的字段逐键钉。"""
    syn = bt.synthesize_bias_tee(FC, Z0, dc_current_a=0.5, isat_margin=0.2)
    d = syn.to_dict()
    assert set(d) == {
        "l_choke_h", "c_block_f", "f_corner_hz", "z0_ohm",
        "dc_current_a", "required_isat_a", "isat_margin",
    }
    for k, v in d.items():
        assert v == getattr(syn, k)
    assert d["f_corner_hz"] == FC and d["z0_ohm"] == Z0  # 选型路字段此前零断言
    assert d["isat_margin"] == 0.2
    # 无 dc_current 路：f_corner/z0 逐位 + 三选型字段 None（判缺失 is not None 口径）
    d2 = SYN.to_dict()
    assert set(d2) == set(d)
    assert d2["f_corner_hz"] == FC and d2["z0_ohm"] == Z0
    assert d2["dc_current_a"] is None and d2["required_isat_a"] is None
    assert d2["isat_margin"] is None


def test_response_to_dict_contract_and_sampling():
    """Response.to_dict：键集/字段透传 + 抽样契约（n=150/201/401 三态 + max_points=1）。"""
    L, C = SYN.l_choke_h, SYN.c_block_f
    freqs = np.linspace(1e6, 1e8, 201)
    rd = bt.bias_tee_response(freqs, L, C).to_dict()
    assert set(rd) == {
        "port_order", "z0_ohm", "l_choke_h", "c_block_f", "n_freq", "f_ghz", "s_db",
    }
    assert rd["port_order"] == ["rf", "dc", "comb"]
    assert rd["n_freq"] == 201
    assert rd["z0_ohm"] == Z0 and rd["l_choke_h"] == L and rd["c_block_f"] == C
    # n=201 > 缺省 max_points=200：步长 2、末点恰为网格末点 → 101 点
    assert len(rd["f_ghz"]) == 101
    assert rd["f_ghz"][0] == pytest.approx(1e6 / 1e9, rel=1e-15)  # 首点保留
    assert rd["f_ghz"][-1] == pytest.approx(1e8 / 1e9, rel=1e-15)  # 末点强制补齐
    # s_db 与 20log10(|S|+1e-300) 在首/末抽样点逐位（dB 换算系数与防零哨兵契约）
    s_ref = bt.bias_tee_s(freqs, L, C)
    for k, i in ((0, 0), (100, 200)):
        ref = 20.0 * np.log10(np.abs(s_ref[i]) + 1e-300)
        assert float(np.max(np.abs(np.asarray(rd["s_db"][k]) - ref))) == pytest.approx(
            0.0, abs=1e-9
        )
    # n=401：步长 3、range 末点 399 ≠ 400 → 尾点 append 生效 → 135 点且末点为真端点
    rd2 = bt.bias_tee_response(np.linspace(1e6, 1e8, 401), L, C).to_dict()
    assert len(rd2["f_ghz"]) == 135
    assert rd2["f_ghz"][-1] == pytest.approx(1e8 / 1e9, rel=1e-15)
    # n=150 ≤ 200：不抽样，全量 150 点
    rd3 = bt.bias_tee_response(np.linspace(1e6, 1e8, 150), L, C).to_dict()
    assert len(rd3["f_ghz"]) == 150
    assert rd3["f_ghz"][0] == pytest.approx(1e6 / 1e9, rel=1e-15)
    # max_points=1：步长 = n → 首点+尾点两点
    rd4 = bt.bias_tee_response(np.linspace(1e6, 1e8, 4), L, C).to_dict(max_points=1)
    assert len(rd4["f_ghz"]) == 2
    assert rd4["f_ghz"][0] == pytest.approx(1e6 / 1e9, rel=1e-15)
    assert rd4["f_ghz"][-1] == pytest.approx(1e8 / 1e9, rel=1e-15)


def test_response_to_dict_zero_entry_no_nan():
    """|S| 恰为 0 的条目 → 20·log10(1e-300) = −6000 dB，不得 NaN（防零哨兵契约）。"""
    s = np.ones((3, 3, 3), dtype=complex)
    s[1, 1, 1] = 0.0
    resp = bt.BiasTeeResponse(
        freqs_hz=np.array([1e6, 2e6, 3e6]),
        s=s, z0_ohm=Z0, l_choke_h=SYN.l_choke_h, c_block_f=SYN.c_block_f,
    )
    val = resp.to_dict()["s_db"][1][1][1]
    assert val == pytest.approx(20.0 * math.log10(1e-300), rel=1e-9)
    assert math.isfinite(val)


def test_response_packaging_passthrough():
    """打包入口透传契约：parasitics 与 z0 必须真的进 S 面、字段逐位进 dataclass。"""
    freqs = np.array([1e6, 1e8])
    L, C = SYN.l_choke_h, SYN.c_block_f
    par = bt.BiasTeeParasitics(choke_esr_ohm=1.0)
    resp = bt.bias_tee_response(freqs, L, C, par, 75.0)
    assert resp.z0_ohm == 75.0
    assert resp.l_choke_h == L and resp.c_block_f == C
    assert np.array_equal(resp.s, bt.bias_tee_s(freqs, L, C, par, 75.0))
    # 非酉佐证：寄生确实进了面（理想面此断言必红）
    err = np.max(np.abs(resp.s[1].conj().T @ resp.s[1] - np.eye(3)))
    assert err > 1e-6


def test_face_db_nan_inf_no_warning():
    """face_db 边际契约：|S|=0 → +inf 且无警告泄漏；NaN 面 → +inf；2 端口面守卫。"""
    import warnings

    s = np.ones((2, 3, 3), dtype=complex)
    s[0, 1, 0] = 0.0
    s[1, 1, 0] = float("nan")
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # divide 警告必须被 errstate 吞掉
        out = bt.face_db(s, "rf", "dc")
    assert out[0] == np.inf
    assert out[1] == np.inf  # NaN 走 isnan→inf 哨兵，不得透传 NaN
    with pytest.raises(ValueError):
        bt.two_port_face(np.zeros((2, 4, 4)))


def test_leakage_band_threshold_semantics():
    """隔离度恰等于阈值的网格点属于满足（>= 语义）；插值缘与峰值定位。"""
    freqs = np.array([1.0, 10.0, 100.0])
    band = bt.leakage_band(freqs, _iso_s([40.0, 40.0, 20.0]), 40.0)
    assert band["n_satisfied"] == 2
    # 低缘：i_a=40（恰等阈值）→ frac=0 → 插值缘恰为 10.0
    assert band["f_lo_edge_hz"] == 10.0
    assert band["f_hi_edge_hz"] is None
    assert band["peak_isolation_db"] == 40.0
    assert band["peak_freq_hz"] == 1.0


def test_leakage_band_single_boundary_point():
    """唯一满足点压在网格首点：仍走插值缘（不走全无满足的早退分支）。"""
    freqs = np.array([1.0, 10.0, 100.0])
    band = bt.leakage_band(freqs, _iso_s([60.0, 20.0, 20.0]), 40.0)
    assert band["n_satisfied"] == 1
    assert band["f_lo_edge_hz"] == pytest.approx(10.0 ** 0.5, rel=1e-12)
    assert band["f_hi_edge_hz"] is None
    assert band["peak_isolation_db"] == 60.0 and band["peak_freq_hz"] == 1.0


def test_leakage_band_all_satisfied():
    """全网格满足：两侧带缘=网格端点（无插值），不触发穿越定位分支。"""
    freqs = np.array([1.0, 10.0, 100.0])
    band = bt.leakage_band(freqs, _iso_s([60.0, 50.0, 45.0]), 40.0)
    assert band["n_satisfied"] == 3
    assert band["f_lo_edge_hz"] == 1.0
    assert band["f_hi_edge_hz"] == 100.0


def test_leakage_band_hi_side_interp():
    """高缘 log10(f) 域线性插值：30→60 dB 穿越 40 dB 在 10^(4/3) Hz。"""
    freqs = np.array([1.0, 10.0, 100.0])
    band = bt.leakage_band(freqs, _iso_s([20.0, 30.0, 60.0]), 40.0)
    assert band["n_satisfied"] == 1
    assert band["f_lo_edge_hz"] is None
    assert band["f_hi_edge_hz"] == pytest.approx(10.0 ** (4.0 / 3.0), rel=1e-12)
    assert band["peak_isolation_db"] == 60.0 and band["peak_freq_hz"] == 100.0


def test_leakage_band_lo_side_interp_two_point():
    """两点网格低缘插值：50→30 dB 穿越 40 dB 恰在几何中点 10.0 Hz。"""
    freqs = np.array([1.0, 100.0])
    band = bt.leakage_band(freqs, _iso_s([50.0, 30.0]), 40.0)
    assert band["n_satisfied"] == 1
    assert band["f_lo_edge_hz"] == pytest.approx(10.0, rel=1e-12)
    assert band["f_hi_edge_hz"] is None
    assert band["peak_freq_hz"] == 1.0


def test_leakage_band_result_keys_both_paths():
    """返回键集契约：全无满足早退与主路径同构八键，端口/阈值字段回读。"""
    freqs = np.array([1.0, 10.0, 100.0])
    expected = {
        "threshold_db", "port_from", "port_to",
        "f_lo_edge_hz", "f_hi_edge_hz", "n_satisfied",
        "peak_isolation_db", "peak_freq_hz",
    }
    band0 = bt.leakage_band(freqs, _iso_s([20.0, 30.0, 10.0]), 40.0)  # 早退分支
    band1 = bt.leakage_band(freqs, _iso_s([60.0, 50.0, 45.0]), 40.0)  # 主路径
    assert set(band0) == expected
    assert set(band1) == expected
    assert band0["threshold_db"] == 40.0 and band1["threshold_db"] == 40.0
    assert band0["port_from"] == "rf" and band0["port_to"] == "dc"
    assert band1["port_from"] == "rf" and band1["port_to"] == "dc"


def _choke_candidates_wide():
    return (
        bt.InductorCandidate("LA", l_h=10e-9, isat_a=0.5, esr_ohm=0.1, srf_hz=2e9),
        bt.InductorCandidate("LB", l_h=80e-9, isat_a=1.0, esr_ohm=0.3, srf_hz=1e9),
        bt.InductorCandidate("LC", l_h=100e-9, isat_a=None, esr_ohm=0.4, srf_hz=0.5e9),
    )


def test_select_choke_negative_branches():
    """扼流选型负分支：缺省不过筛、未知 isat 不筛、恰等门槛合格、空表/无人满足 reason。"""
    cands = _choke_candidates_wide()
    # min_isat_a 缺省 None → 不过筛（LC 的 isat=None 仍合格）→ 数量级最近 LB
    sel = bt.select_choke(list(cands), SYN.l_choke_h)
    assert sel.part_id == "LB"
    assert sel.value == pytest.approx(80e-9, rel=1e-15)
    assert sel.log_deviation == pytest.approx(abs(math.log(80e-9 / SYN.l_choke_h)), rel=1e-15)
    assert sel.reason == "ok"
    # isat=None 的候选在设门槛时按未知不筛（不报错、不落选）；LB 仍最近
    sel_f = bt.select_choke(list(cands), SYN.l_choke_h, min_isat_a=0.5)
    assert sel_f.part_id == "LB"
    # isat 恰等于门槛 → 合格（>= 语义），且按值最近胜出
    sel_eq = bt.select_choke(
        [bt.InductorCandidate("LX", l_h=79e-9, isat_a=0.5),
         bt.InductorCandidate("LY", l_h=200e-9, isat_a=1.0)],
        SYN.l_choke_h, min_isat_a=0.5,
    )
    assert sel_eq.part_id == "LX" and sel_eq.value == 79e-9
    # 无人满足：三字段全 None + 精确 reason（门槛与计数如实回显）
    sel_none = bt.select_choke(
        [bt.InductorCandidate("LX", l_h=79e-9, isat_a=0.5),
         bt.InductorCandidate("LY", l_h=200e-9, isat_a=1.0)],
        SYN.l_choke_h, min_isat_a=10.0,
    )
    assert sel_none.part_id is None
    assert sel_none.value is None and sel_none.log_deviation is None
    assert sel_none.reason == "无满足 isat_a>=10.0 的候选（共 2 条，rating 缺失按未知不筛）"
    # 空候选表：reason 钉死、log_deviation 不被串位
    sel0 = bt.select_choke([], SYN.l_choke_h)
    assert sel0.part_id is None and sel0.value is None
    assert sel0.log_deviation is None and sel0.reason == "候选表为空"


def test_select_block_cap_negative_branches():
    """隔直选型负分支：与扼流同构（rated_v 门槛/未知不筛/恰等合格/reason 契约）。"""
    caps = (
        bt.CapacitorCandidate("CA", c_f=10e-12, rated_v=50.0),
        bt.CapacitorCandidate("CB", c_f=100e-12, rated_v=16.0),
        bt.CapacitorCandidate("CC", c_f=90e-12, rated_v=None),
    )
    # 缺省 min_rated_v=None → 不过筛 → 90 pF 数量级最近（SYN.c_block_f≈31.8 pF）
    sel = bt.select_block_cap(list(caps), SYN.c_block_f)
    assert sel.part_id == "CC"
    assert sel.value == 90e-12 and sel.reason == "ok"
    # 设门槛：CB 耐压不足被筛除，CC 未知耐压不筛仍合格且最近
    sel_f = bt.select_block_cap(list(caps), SYN.c_block_f, min_rated_v=25.0)
    assert sel_f.part_id == "CC"
    # 恰等门槛合格（>= 语义），且按值最近胜出（30 pF 对 31.8 pF 目标远比 100 pF 近）
    sel_eq = bt.select_block_cap(
        [bt.CapacitorCandidate("CX", c_f=30e-12, rated_v=25.0),
         bt.CapacitorCandidate("CY", c_f=100e-12, rated_v=30.0)],
        SYN.c_block_f, min_rated_v=25.0,
    )
    assert sel_eq.part_id == "CX"
    # 无人满足：精确 reason（rating 名与门槛回显）
    sel_none = bt.select_block_cap(
        [bt.CapacitorCandidate("CX", c_f=30e-12, rated_v=25.0),
         bt.CapacitorCandidate("CY", c_f=100e-12, rated_v=30.0)],
        SYN.c_block_f, min_rated_v=100.0,
    )
    assert sel_none.part_id is None and sel_none.log_deviation is None
    assert sel_none.reason == "无满足 rated_v>=100.0 的候选（共 2 条，rating 缺失按未知不筛）"
    sel0 = bt.select_block_cap([], SYN.c_block_f)
    assert sel0.log_deviation is None and sel0.reason == "候选表为空"


def test_part_selection_to_dict_contract():
    """PartSelection.to_dict 键集合契约（value/log_deviation/reason 此前零键断言）。"""
    sel = bt.select_choke(list(_choke_candidates_wide()), SYN.l_choke_h)
    d = sel.to_dict()
    assert set(d) == {"part_id", "value", "log_deviation", "reason"}
    for k, v in d.items():
        assert v == getattr(sel, k)


def test_parasitics_from_parts_overrides():
    """ESR 显式覆盖优先于候选值；SRF 反推比值断言；ESR/SRF 双缺失 → 全零如实。"""
    choke = bt.InductorCandidate("L1", l_h=80e-9, esr_ohm=0.3, srf_hz=1e9)
    block = bt.CapacitorCandidate("C1", c_f=100e-12, esr_ohm=0.02, srf_hz=2e9)
    par = bt.parasitics_from_parts(choke, block, choke_esr_ohm=9.0, block_esr_ohm=7.0)
    assert par.choke_esr_ohm == 9.0  # 覆盖分支：不得回落候选值
    assert par.block_esr_ohm == 7.0
    # SRF→寄生反推同 vendor 式（比值断言规避 approx 隐式 abs 地板）
    assert par.choke_cp_f / (1.0 / ((2.0 * math.pi * 1e9) ** 2 * 80e-9)) == pytest.approx(
        1.0, rel=1e-15
    )
    assert par.block_esl_h / (1.0 / ((2.0 * math.pi * 2e9) ** 2 * 100e-12)) == pytest.approx(
        1.0, rel=1e-15
    )
    # SRF 缺失 → 寄生 0；候选 ESR 也缺失 → ESR 0（未知不虚构，#364④ 零值合法）
    par_none = bt.parasitics_from_parts(
        bt.InductorCandidate("Lx", l_h=1e-6), bt.CapacitorCandidate("Cx", c_f=1e-9)
    )
    assert par_none.choke_cp_f == 0.0 and par_none.block_esl_h == 0.0
    assert par_none.choke_esr_ohm == 0.0 and par_none.block_esr_ohm == 0.0
