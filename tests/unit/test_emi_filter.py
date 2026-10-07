"""ME-1 core/emi_filter 合成回收钉（方案书判据：skrf 直算逐位对拍 + LISN 元件值对照）。

独立实现（本模块 numpy ABCD）vs 库实现（skrf.media 分立元件 + skrf.network.a2s）
互证（#118：数值裁判必须独立来源）；LISN 值面钉公开可达源表（Tekbox 手册实测
下载 + Ajou 论文表，出处见 emi_filter.LISN_PROVENANCE）；FCC 限值线钉 eCFR 现行
文本双源核对值（Cornell LII + govinfo，检索 2026-09-26）。
"""

import numpy as np
import pytest
import skrf
import skrf.network as sn
from skrf.media import DefinedGammaZ0

from rfauto.core import emi_filter as ef

# ── 对拍工具（skrf 侧独立路径）────────────────────────────────────────────────


def _media(f: np.ndarray) -> DefinedGammaZ0:
    fr = skrf.Frequency.from_f(np.asarray(f, dtype=float), unit="Hz")
    return DefinedGammaZ0(frequency=fr, z0=50.0)


def _il_from_abcd(a: np.ndarray, z0_src: float, z0_load: float) -> np.ndarray:
    """skrf a2s 口径 IL = −20·log10|S21|（伪波，逐端口 z0）。"""
    z0 = np.broadcast_to(np.array([z0_src, z0_load], dtype=float), (a.shape[0], 2))
    s = sn.a2s(np.asarray(a, dtype=complex), z0)
    return -20.0 * np.log10(np.abs(s[:, 1, 0]))


F_GRID = np.logspace(3, 9, 241)  # 1 kHz – 1 GHz
L1, C1 = 1e-6, 1e-7


# ── ABCD 基本件 vs skrf ──────────────────────────────────────────────────────


def test_abcd_series_inductor_matches_skrf():
    m = _media(F_GRID)
    a_skrf = np.asarray(m.inductor(L1).a)
    a_mine = ef.abcd_series(1j * 2 * np.pi * F_GRID * L1)
    assert np.allclose(a_mine, a_skrf, rtol=1e-10, atol=1e-7)  # skrf media 带 ~1e-9 级浮点噪声@1GHz


def test_abcd_parallel_shunt_cap_matches_skrf():
    m = _media(F_GRID)
    a_skrf = np.asarray(m.shunt_capacitor(C1).a)
    a_mine = ef.abcd_parallel(1j * 2 * np.pi * F_GRID * C1)
    assert np.allclose(a_mine, a_skrf, rtol=1e-10, atol=1e-7)


def test_abcd_series_resistor_matches_skrf():
    m = _media(F_GRID)
    a_skrf = np.asarray(m.resistor(25.0).a)
    a_mine = ef.abcd_series(25.0 + 0j)
    assert np.allclose(a_mine, a_skrf, rtol=1e-12, atol=1e-10)


def test_abcd_cascade_matches_skrf_star_operator():
    m = _media(F_GRID)
    net = m.inductor(L1) ** m.shunt_capacitor(C1) ** m.inductor(L1)
    a_mine = ef.abcd_cascade(
        ef.abcd_series(1j * 2 * np.pi * F_GRID * L1),
        ef.abcd_cascade(ef.abcd_parallel(1j * 2 * np.pi * F_GRID * C1), ef.abcd_series(1j * 2 * np.pi * F_GRID * L1)),
    )
    assert np.allclose(a_mine, np.asarray(net.a), rtol=1e-9, atol=1e-7)  # 1GHz 处乘积元素 ~1e10，噪声按比例


def test_abcd_cascade_shape_guard():
    with pytest.raises(ValueError, match="2, 2"):
        ef.abcd_cascade(np.zeros((3, 2)), np.zeros((2, 2)))
    with pytest.raises(ValueError, match="ABCD"):
        ef.abcd_cascade(np.zeros((3, 2, 2)), np.zeros((3, 3)))


# ── ABCD→S vs skrf a2s（等/不等端接）─────────────────────────────────────────


def test_abcd_to_s_matches_skrf_a2s_equal_z0():
    m = _media(F_GRID)
    a = np.asarray(m.inductor(L1).a)
    s_mine = ef.abcd_to_s(a, 50.0, 50.0)
    s_skrf = sn.a2s(a, 50.0)
    assert np.allclose(s_mine, s_skrf, rtol=0, atol=1e-14)


def test_abcd_to_s_matches_skrf_a2s_unequal_z0():
    m = _media(F_GRID)
    a = np.asarray(m.inductor(L1).a)
    z0 = np.broadcast_to(np.array([0.1, 100.0]), (F_GRID.size, 2))
    s_mine = ef.abcd_to_s(a, 0.1, 100.0)
    assert np.allclose(s_mine, sn.a2s(a, z0), rtol=0, atol=1e-14)


def test_abcd_to_s_identity_and_series_resistor_analytic():
    """手算锚：等网络接不等参考阻抗线的伪波反射 (Z2−Z1)/(Z1+Z2)；串联 25Ω@50Ω 系统解析值。"""
    ident = np.tile(np.eye(2, dtype=complex), (3, 1, 1))
    s = ef.abcd_to_s(ident, 50.0, 75.0)
    assert np.allclose(s[:, 0, 0], (75.0 - 50.0) / (75.0 + 50.0))  # S11=0.2
    assert np.allclose(s[:, 1, 1], (50.0 - 75.0) / (50.0 + 75.0))  # S22=-0.2
    expect_t = 2.0 * np.sqrt(50.0 * 75.0) / 125.0
    assert np.allclose(np.abs(s[:, 1, 0]), expect_t)
    assert np.allclose(np.abs(s[:, 0, 1]), expect_t)  # det=1 → S12=S21
    s_ser = ef.abcd_to_s(ef.abcd_series(np.full(3, 25.0 + 0j)), 50.0, 50.0)
    assert np.allclose(s_ser[:, 1, 0], 0.8)  # 手算 2·50/(50+25+50)
    assert np.allclose(s_ser[:, 0, 0], 0.2)  # Γ=(75−50)/(75+50)


def test_abcd_to_s_rejects_bad_inputs():
    a = np.eye(2, dtype=complex)
    with pytest.raises(ValueError, match="abcd 必须"):
        ef.abcd_to_s(np.zeros((2, 3)), 50.0, 50.0)
    with pytest.raises(ValueError, match="z0_src"):
        ef.abcd_to_s(a, -1.0, 50.0)
    with pytest.raises(ValueError, match="z0_load"):
        ef.abcd_to_s(a, 50.0, True)
    with pytest.raises(ValueError, match="z0_src"):
        ef.abcd_to_s(a, np.array([50.0, np.nan]), 50.0)


# ── lc_filter_il：skrf 三/四拓扑合成回收 ─────────────────────────────────────


def _skrf_lc_abcd(topology: str, l_h: float, c_f: float) -> np.ndarray:
    m = _media(F_GRID)
    a_l = np.asarray(m.inductor(l_h).a)
    a_c = np.asarray(m.shunt_capacitor(c_f).a)

    def mul(x, y):
        return np.matmul(x, y)

    if topology == "L":
        return mul(a_l, a_c)
    if topology == "C":
        return mul(a_c, a_l)
    if topology == "pi":
        return mul(a_c, mul(a_l, a_c))
    return mul(a_l, mul(a_c, a_l))


@pytest.mark.parametrize("topology", ["L", "C", "pi", "t"])
def test_lc_filter_il_matches_skrf_bitwise_5050(topology):
    il_mine = ef.lc_filter_il(F_GRID, topology, L1, C1)
    il_skrf = _il_from_abcd(_skrf_lc_abcd(topology, L1, C1), 50.0, 50.0)
    assert il_mine.shape == il_skrf.shape
    assert np.allclose(il_mine, il_skrf, rtol=0, atol=1e-10)


def test_lc_filter_l_section_band_edge_closed_form():
    """手推闭式（独立双路径）：f_c 处 |S21|²=4/(3+L/(Z0²C)+Z0²C/L)。"""
    fc = 1.0 / (2.0 * np.pi * np.sqrt(L1 * C1))
    z0 = 50.0
    hand = 10.0 * np.log10((3.0 + L1 / (z0**2 * C1) + z0**2 * C1 / L1) / 4.0)
    mod = float(ef.lc_filter_il(np.array([fc]), "L", L1, C1)[0])
    assert mod == pytest.approx(hand, abs=1e-9)
    # 通带形态：f_c/100 处近零插损
    low = float(ef.lc_filter_il(np.array([fc / 100.0]), "L", L1, C1)[0])
    assert low < 0.1
    # 渐近 40 dB/dec（100·f_c → 1000·f_c 已入 x²=ω⁴L²C² 主导段）
    va = float(ef.lc_filter_il(np.array([100.0 * fc]), "L", L1, C1)[0])
    vb = float(ef.lc_filter_il(np.array([1000.0 * fc]), "L", L1, C1)[0])
    assert vb - va == pytest.approx(40.0, abs=0.3)


def test_lc_filter_l_and_c_orientation_identical_matched_terminations():
    """等端接下两 L 节朝向 Δ 恒等式（手推：Δ 同式）→ IL 逐位一致。"""
    il_l = ef.lc_filter_il(F_GRID, "L", L1, C1)
    il_c = ef.lc_filter_il(F_GRID, "C", L1, C1)
    assert np.allclose(il_l, il_c, rtol=0, atol=1e-12)


def test_lc_filter_orientation_differs_under_mismatch():
    """失配端接下朝向不再等价（差异显著=失配口径敏感性证据）。"""
    il_l = ef.lc_filter_il(F_GRID, "L", L1, C1, source_r=0.1, load_r=100.0)
    il_c = ef.lc_filter_il(F_GRID, "C", L1, C1, source_r=0.1, load_r=100.0)
    assert np.max(np.abs(il_l - il_c)) > 10.0


def test_lc_filter_guards():
    f = np.array([1e6])
    for bad_l in (-1e-6, True, 0.0, float("nan")):
        with pytest.raises(ValueError):
            ef.lc_filter_il(f, "L", bad_l, C1)
    for bad_c in (-1e-7, True, 0.0):
        with pytest.raises(ValueError):
            ef.lc_filter_il(f, "L", L1, bad_c)
    with pytest.raises(ValueError, match="topology"):
        ef.lc_filter_il(f, "ll", L1, C1)
    with pytest.raises(ValueError, match="topology"):
        ef.lc_filter_il(f, None, L1, C1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ef.lc_filter_il(f, "L", L1, C1, source_r=0.0)
    with pytest.raises(ValueError):
        ef.lc_filter_il(np.array([0.0, 1e6]), "L", L1, C1)


# ── CISPR-17 三端接三口径 ─────────────────────────────────────────────────────


@pytest.mark.parametrize("topology", ["L", "pi"])
def test_three_terminations_match_skrf_bitwise(topology):
    a = _skrf_lc_abcd(topology, L1, C1)
    tri = ef.il_three_terminations(F_GRID, a)
    assert sorted(tri.keys()) == ["0.1_100", "100_0.1", "50_50"]
    for key, (rs, rl) in ef.CISPR17_TERMINATIONS.items():
        assert np.allclose(tri[key], _il_from_abcd(a, rs, rl), rtol=0, atol=1e-10)


def test_three_terminations_mismatch_difference_is_significant():
    """失配口径与 50/50 口径在滤波段差异显著；不对称滤波器两失配朝向彼此不同。"""
    a_sym = _skrf_lc_abcd("pi", L1, C1)  # 对称 π：0.1/100 与 100/0.1 互易镜像下等价
    tri_sym = ef.il_three_terminations(F_GRID, a_sym)
    assert np.max(np.abs(tri_sym["50_50"] - tri_sym["0.1_100"])) > 3.0
    assert np.all(np.isfinite(tri_sym["50_50"]))
    a_asym = _skrf_lc_abcd("L", L1, C1)  # 不对称 L 节：两失配朝向不再等价
    tri = ef.il_three_terminations(F_GRID, a_asym)
    assert np.max(np.abs(tri["50_50"] - tri["0.1_100"])) > 3.0
    assert np.max(np.abs(tri["50_50"] - tri["100_0.1"])) > 3.0
    assert np.max(np.abs(tri["0.1_100"] - tri["100_0.1"])) > 0.5


# ── CM 扼流圈 ────────────────────────────────────────────────────────────────


def test_cm_choke_dm_il_vanishes_as_k_approaches_one():
    out = ef.cm_choke_il(np.array([1e6]), 10e-3, k_coupling=1.0 - 1e-9)
    # 理想共模抑制恒等式：k→1 ⇒ L_leak=L(1−k)→0 ⇒ 差模 IL→0（−20log10|S21| 口径）
    assert float(out["dm_il_db"][0]) < 1e-4
    # 共模支路手算锚：L(1+k)≈20 mH@1 MHz → jX=j1.2566e5 Ω → IL=20log10(|100+jX|/100)≈62.0 dB
    x_l = 2 * np.pi * 1e6 * 0.02
    assert float(out["cm_il_db"][0]) == pytest.approx(20.0 * np.log10(np.hypot(100.0, x_l) / 100.0), abs=0.05)


def test_cm_choke_explicit_leak_overrides_k_for_dm():
    f = np.logspace(4, 7, 61)
    a = ef.cm_choke_il(f, 10e-3, k_coupling=0.5, l_leak_h=1e-9)
    b = ef.cm_choke_il(f, 10e-3, k_coupling=0.99, l_leak_h=1e-9)
    assert float(a["l_leak_h_used"]) == 1e-9
    assert np.allclose(a["dm_il_db"], b["dm_il_db"], rtol=0, atol=0.0)
    # 与显式串联电感 1 nH 的两口 IL 逐位一致（skrf 交叉核对）
    m = _media(f)
    il_series = _il_from_abcd(np.asarray(m.inductor(1e-9).a), 50.0, 50.0)
    assert np.allclose(a["dm_il_db"], il_series, rtol=0, atol=1e-12)


def test_cm_choke_cm_path_is_l_times_1_plus_k():
    f = np.logspace(4, 7, 61)
    out = ef.cm_choke_il(f, 10e-3, k_coupling=0.9)
    m = _media(f)
    il_series = _il_from_abcd(np.asarray(m.inductor(10e-3 * 1.9).a), 50.0, 50.0)
    assert np.allclose(out["cm_il_db"], il_series, rtol=0, atol=1e-12)
    assert out["l_cm_path_h"] == pytest.approx(19e-3)
    assert out["l_leak_h_used"] == pytest.approx(1.0e-3)  # 10 mH·(1−0.9)


def test_cm_choke_guards():
    f = np.array([1e6])
    with pytest.raises(ValueError, match="k_coupling"):
        ef.cm_choke_il(f, 10e-3, k_coupling=1.5)
    with pytest.raises(ValueError, match="k_coupling"):
        ef.cm_choke_il(f, 10e-3, k_coupling=True)
    with pytest.raises(ValueError, match="k_coupling"):
        ef.cm_choke_il(f, 10e-3, k_coupling=-0.1)
    with pytest.raises(ValueError):
        ef.cm_choke_il(f, -1.0)
    with pytest.raises(ValueError):
        ef.cm_choke_il(f, 10e-3, l_leak_h=-1e-9)


# ── 馈通 C-π ─────────────────────────────────────────────────────────────────


def test_feedthrough_ideal_equals_pi_topology_and_skrf():
    f = np.logspace(4, 8, 81)
    il_ft = ef.feedthrough_il(f, 1e-8, 1e-6)
    il_pi = ef.lc_filter_il(f, "pi", 1e-6, 1e-8)
    assert np.allclose(il_ft, il_pi, rtol=0, atol=1e-12)
    m = _media(f)
    a = np.matmul(
        np.asarray(m.shunt_capacitor(1e-8).a),
        np.matmul(np.asarray(m.inductor(1e-6).a), np.asarray(m.shunt_capacitor(1e-8).a)),
    )
    assert np.allclose(il_ft, _il_from_abcd(a, 50.0, 50.0), rtol=0, atol=1e-12)


def test_feedthrough_parasitics_direction():
    f = np.array([1.0 / (2 * np.pi * np.sqrt(1e-8 * 1e-6))])  # 自谐振点
    base = float(ef.feedthrough_il(f, 1e-8, 1e-6)[0])
    with_esr = float(ef.feedthrough_il(f, 1e-8, 1e-6, esr=0.5)[0])
    assert with_esr > base  # ESR 在谐振支路加损耗 → IL 升
    f_hi = np.array([100e6])
    base_hi = float(ef.feedthrough_il(f_hi, 1e-8, 1e-6)[0])
    with_esl = float(ef.feedthrough_il(f_hi, 1e-8, 1e-6, esl=10e-9)[0])
    assert with_esl < base_hi  # ESL 削弱高频并联分流 → IL 降
    with pytest.raises(ValueError):
        ef.feedthrough_il(f_hi, 1e-8, 1e-6, esr=-1.0)
    with pytest.raises(ValueError):
        ef.feedthrough_il(f_hi, 1e-8, 1e-6, esl=True)


# ── LISN 双型 ────────────────────────────────────────────────────────────────


def test_lisn_cispr25_component_values_pinned():
    """元件值钉公开可达源表（Tekbox TBL0550-1 V1.4 Picture 1；防手滑改值）。"""
    assert ef.CISPR25_5UH_VALUES == {
        "l_main_h": 5e-6,
        "c_source_f": 1e-6,
        "c_couple_f": 0.1e-6,
        "r_bleed_ohm": 1000.0,
        "r_recv_ohm": 50.0,
    }
    f = np.logspace(4, 8, 41)
    net = ef.lisn_network("cispr25_5uh", f)
    assert net["component_values"] == ef.CISPR25_5UH_VALUES
    assert net["abcd"].shape == (41, 2, 2)
    src = net["provenance"]["secondary"]  # type: ignore[index]
    assert any("TBL0550-1" in str(s) for s in src)


def test_lisn_cispr25_impedance_matches_independent_hand_formula():
    """EUT 口阻抗 vs 测试内独立手排公式（并联两支路），逐位级回收。"""
    f = np.logspace(4, 8, 41)
    net = ef.lisn_network("cispr25_5uh", f)
    w = 2 * np.pi * f
    r_rf = 1000.0 * 50.0 / 1050.0
    z_recv = 1.0 / (1j * w * 0.1e-6) + r_rf
    z_path = 1j * w * 5e-6 + 1.0 / (1j * w * 1e-6)
    z_hand = z_recv * z_path / (z_recv + z_path)
    assert np.allclose(net["z_eut_ohm"], z_hand, rtol=1e-12, atol=1e-12)  # type: ignore[arg-type]
    # 高频段 |Z|→47.6 Ω（1k∥50 口径），量级锚
    mag = np.abs(np.asarray(net["z_eut_ohm"]))  # type: ignore[arg-type]
    assert 40.0 < mag[-1] < 52.0


def test_lisn_cispr16_component_values_pinned():
    """元件值钉公开可达源表（Tekbox TBLC08 V1.6 Fig.2 + Ajou 论文表，主口径单扼流型）。"""
    assert ef.CISPR16_50UH_VALUES == {
        "l_main_h": 50e-6,
        "c_damp_f": 8e-6,
        "r_damp_ohm": 5.0,
        "c_couple_f": 0.25e-6,
        "r_bleed_ohm": 1000.0,
        "r_recv_ohm": 50.0,
        "r_other_phase_ohm": 50.0,
    }
    src = ef.LISN_PROVENANCE["cispr16_50uh"]["secondary"]  # type: ignore[index]
    assert any("TBLC08" in str(s) for s in src)
    assert any("Ajou" in str(s) for s in src)
    note = str(ef.LISN_PROVENANCE["cispr16_50uh"]["variant_note"])
    assert "版本差异" in note
    assert "250" in note and "4 µF" in note  # 全带型变体（250µH+4µF/10Ω）注记双列
    assert "EUT 侧" in note  # 阻尼支路位置约束如实注记


def test_lisn_cispr16_impedance_designation_anchor():
    """designation 锚：150 kHz 处 |Z_eut| ≈ |50 ∥ (50µH + 5Ω)|（3 Ω 容差）。"""
    f = np.array([150e3, 1e6, 10e6])
    net = ef.lisn_network("cispr16_50uh", f)
    mag = np.abs(np.asarray(net["z_eut_ohm"]))  # type: ignore[arg-type]
    w = 2 * np.pi * 150e3
    z_ideal = 50.0 * (5.0 + 1j * w * 50e-6) / (50.0 + 5.0 + 1j * w * 50e-6)
    assert abs(mag[0] - abs(z_ideal)) < 3.0
    assert 40.0 < mag[1] < 55.0
    assert 40.0 < mag[2] < 55.0


def test_lisn_source_port_impedance_and_guards():
    f = np.logspace(4, 8, 41)
    for kind in ("cispr16_50uh", "cispr25_5uh"):
        net = ef.lisn_network(kind, f)
        assert np.all(np.isfinite(np.asarray(net["z_source_ohm"])))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="kind"):
        ef.lisn_network("vde_58uh", f)
    with pytest.raises(ValueError):
        ef.lisn_network("cispr25_5uh", np.array([0.0, 1e6]))


# ── FCC Part 15 §15.107 限值线 ───────────────────────────────────────────────


def test_fcc_class_b_quasi_peak_piecewise_values():
    lim = ef.fcc_limits_part15(class_b=True)
    assert lim["paragraph"] == "15.107(a)"
    segs = lim["segments_qp"]  # type: ignore[index]
    assert ef._eval_fcc_line(segs, np.array([0.15]))[0] == pytest.approx(66.0)
    assert ef._eval_fcc_line(segs, np.array([0.30]))[0] == pytest.approx(
        66.0 + (56.0 - 66.0) * np.log10(0.30 / 0.15) / np.log10(0.5 / 0.15), abs=1e-9
    )
    assert ef._eval_fcc_line(segs, np.array([0.5]))[0] == pytest.approx(56.0)
    assert ef._eval_fcc_line(segs, np.array([1.0]))[0] == pytest.approx(56.0)
    assert ef._eval_fcc_line(segs, np.array([5.0]))[0] == pytest.approx(56.0)  # 边界取下限
    assert ef._eval_fcc_line(segs, np.array([30.0]))[0] == pytest.approx(60.0)
    assert np.isnan(ef._eval_fcc_line(segs, np.array([0.1]))[0])  # 带外 NaN
    assert np.isnan(ef._eval_fcc_line(segs, np.array([50.0]))[0])


def test_fcc_class_b_average_line_is_10db_below_qp():
    lim = ef.fcc_limits_part15(class_b=True)
    f = np.array([0.15, 0.2, 0.5, 1.0, 5.0, 30.0])
    qp = ef._eval_fcc_line(lim["segments_qp"], f)  # type: ignore[index]
    avg = ef._eval_fcc_line(lim["segments_avg"], f)  # type: ignore[index]
    assert np.allclose(qp - avg, 10.0, atol=1e-12)


def test_fcc_class_a_values_and_difference():
    lim = ef.fcc_limits_part15(class_b=False)
    assert lim["paragraph"] == "15.107(b)"
    f = np.array([0.15, 0.5, 30.0])
    assert np.allclose(ef._eval_fcc_line(lim["segments_qp"], f), [79.0, 73.0, 73.0])  # type: ignore[index]
    assert np.allclose(ef._eval_fcc_line(lim["segments_avg"], f), [66.0, 60.0, 60.0])  # type: ignore[index]
    lim_b = ef.fcc_limits_part15(class_b=True)
    assert ef._eval_fcc_line(lim["segments_qp"], np.array([1.0]))[0] == pytest.approx(73.0)
    assert ef._eval_fcc_line(lim_b["segments_qp"], np.array([1.0]))[0] == pytest.approx(56.0)


def test_fcc_provenance_fields():
    lim = ef.fcc_limits_part15()
    assert "15.107" in str(lim["source"])
    assert "2026-09-26" in str(lim["source"])
    assert lim["retrieved"] == "2026-09-26"
    assert any("bands.py" in str(n) for n in lim["notes"])  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="class_b"):
        ef.fcc_limits_part15(class_b=1)  # type: ignore[arg-type]


# ── margin_report ────────────────────────────────────────────────────────────


def _meas_grid() -> tuple[np.ndarray, dict]:
    f_mhz = np.array([0.15, 0.3, 1.0, 10.0, 30.0])
    f_hz = f_mhz * 1e6
    lim = ef.fcc_limits_part15(class_b=True)
    return f_hz, lim


def test_margin_report_pass_case():
    f_hz, lim = _meas_grid()
    limit = ef._eval_fcc_line(lim["segments_avg"], f_hz / 1e6)  # type: ignore[index]
    rep = ef.margin_report(f_hz, limit - 10.0, lim)
    assert rep["verdict"] == "PASS"
    assert rep["min_margin_db"] == pytest.approx(10.0, abs=1e-9)
    assert rep["first_violation_f_hz"] is None
    assert rep["n_violations"] == 0
    assert rep["n_out_of_band"] == 0
    assert rep["detector"] == "avg_envelope"


def test_margin_report_fail_case():
    f_hz, lim = _meas_grid()
    rep = ef.margin_report(f_hz, np.full(5, 80.0), lim)
    assert rep["verdict"] == "FAIL"
    assert rep["first_violation_f_hz"] == pytest.approx(f_hz[0])
    assert rep["min_margin_db"] < 0.0
    assert rep["n_violations"] == 5


def test_margin_report_mixed_and_out_of_band():
    f_hz, lim = _meas_grid()
    f_full = np.concatenate([[50e3], f_hz])  # 50 kHz 带外（<0.15 MHz）
    # 带内限值（Avg 包络）=[56, 50.24, 46, 50, 50]；72@0.15M 与 65@30M 两点违限
    meas = np.array([200.0, 72.0, 40.0, 40.0, 40.0, 65.0])
    rep = ef.margin_report(f_full, meas, lim)
    assert rep["n_out_of_band"] == 1
    assert rep["verdict"] == "FAIL"
    assert rep["first_violation_f_hz"] == pytest.approx(0.15e6)
    assert rep["n_violations"] == 2
    assert np.isnan(rep["margin_db"][0])  # 带外 200 dBµV 不计入判读


def test_margin_report_array_limits_and_guards():
    f_hz = np.array([1e6, 2e6])
    rep = ef.margin_report(f_hz, np.array([50.0, 55.0]), np.array([54.0, 54.0]))
    assert rep["verdict"] == "FAIL"
    assert rep["detector"] == "array"
    assert rep["first_violation_f_hz"] == pytest.approx(2e6)
    with pytest.raises(ValueError, match="长度"):
        ef.margin_report(f_hz, np.array([50.0]), np.array([54.0, 54.0]))
    with pytest.raises(ValueError, match="limits"):
        ef.margin_report(f_hz, np.array([50.0, 55.0]), {"no_segments": 1})
    with pytest.raises(ValueError, match="长度"):
        ef.margin_report(f_hz, np.array([50.0, 55.0]), np.array([54.0]))
    with pytest.raises(ValueError, match="有限"):
        ef.margin_report(f_hz, np.array([np.nan, 55.0]), np.array([54.0, 54.0]))
