"""架构批 W3-CORE6：移相器补口+DOA CRB+多工器四键单测。

loaded_line_phaser / switched_line_phaser（calc_families/phase_shifter.py）/
doa_crb_ula（calc_families/doa_crb.py）/ multiplexer_channel_plan
（calc_families/multiplexer.py）。

裁判口径（#118 双路径：实现路线=各键闭式；独立第二路线=本文件不同
算法重算——numpy ABCD 矩阵级联/投影器 Fisher 信息/恒等式回代，实现前
独立复算（内部证据目录 轨迹）后写死）：

- **loaded-line**：numpy ABCD 独立级联第二路线（[1,0;jb,1]·线·同左）；
  匹配设计 S11→0（<1e-12）、|S21|=1（机器精度）；差分相移恒等式
  Δφ=2·arctan(b/2)；等效匹配线 θ'=arccos(−cosθ)=180°−θ；设计→分析
  route roundtrip；dphi 数值=设计目标；失配面（b≠2cotθ）S11>0 如实。
- **switched-line**：电长度恒等式 Δφ=360°·Δl·√εeff·f/c0（c0=注册表单源
  C_MM_GHZ）；λg/4→90°、λg/2→180° 精确位；TTD 倍频恒等 Δφ(2f₀)=
  2Δφ(f₀)（unwrapped）；群时延恒等 Δt=Δl√εeff/c0=Δφ/(360°f)——
  λg/4 位 @10GHz ↔ Δt=1/(4f)=25ps 独立恒等式；roundtrip 双向。
- **doa CRB**：numpy 投影器第二路线 J=2·T·SNR·d'ᴴP_a^⊥d'（数值导向
  矢量+投影矩阵，不用闭式 N(N²−1)/12）→ 1/J vs 闭式（rel<1e-12）；
  标度律 ×2T→恰 1/2、SNR+3.0103dB→恰 1/2、N 8→16 因子=8·63/(16·255)、
  1/cos²θ 角标度、端fire 单调发散；θ=0°/±θ 偶对称。
- **multiplexer**：等分数三恒等式（交越=几何中点 √(fc_k·fc_{k+1})/
  对称 fc_k·fc_{N−1−k}=f1·f2/Σ道带宽=总带）；交越损耗常数=
  −10log10(1/2)=3.0102999566398125；等绝对口径算术中点+逐道等宽；
  频段倒序/N=1/非法档显式拒绝（service ok=False）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calc_families.doa_crb import doa_crb_ula
from rfauto.core.calc_families.multiplexer import multiplexer_channel_plan
from rfauto.core.calc_families.phase_shifter import (
    loaded_line_phaser,
    switched_line_phaser,
)
from rfauto.core.calc_families.registry import C_MM_GHZ
from rfauto.service.calculator_service import run_calculator

# ─── 独立第二路线算子（实现前复算，不同算法）────────────────────────────────


def _abcd_shunt_line_shunt(b: float, theta_rad: float) -> np.ndarray:
    """加载线格胞 ABCD：numpy 矩阵级联（独立于键内标量闭式推导）。"""
    shunt = np.array([[1.0, 0.0], [1j * b, 1.0]])
    line = np.array([[math.cos(theta_rad), 1j * math.sin(theta_rad)],
                     [1j * math.sin(theta_rad), math.cos(theta_rad)]])
    return shunt @ line @ shunt


def _abcd_s(m: np.ndarray) -> tuple[complex, complex]:
    """等实参考（归一化）ABCD→S。"""
    a, b, c, d = m[0, 0], m[0, 1], m[1, 0], m[1, 1]
    den = a + b + c + d
    return (a + b - c - d) / den, 2.0 / den


def _crb_numeric(n: int, t_snap: int, snr_lin: float, d_lam: float,
                 theta_rad: float) -> float:
    """投影器 Fisher 信息第二路线：J=2T·SNR·d'ᴴP_a^⊥d' → CRB=1/J。"""
    m_idx = np.arange(n, dtype=float)
    a_vec = np.exp(1j * (2.0 * math.pi * d_lam * math.sin(theta_rad)) * m_idx)
    d_vec = 1j * (2.0 * math.pi * d_lam * math.cos(theta_rad)) * m_idx * a_vec
    proj = np.eye(n) - np.outer(a_vec, a_vec.conj()) / n
    fisher = 2.0 * t_snap * snr_lin * (d_vec.conj() @ proj @ d_vec).real
    return 1.0 / fisher


# ─── loaded_line_phaser ───────────────────────────────────────────────────────

PHI_DEG = 45.0
F_GHZ = 10.0
EREFF = 3.0
Z0 = 50.0
# 实现前手工复算锚（六位+写死；#118 第一路线独立值）
B_45 = 0.828427124746190          # 2·tan(22.5°)
THETA_45 = 67.5                   # 90 − 45/2
LAMBDA_G_10_3 = 17.308525632732   # c0/(10·√3) mm
SPACING_MM_45 = 3.245348556137    # (67.5/360)·λg
C_PF_45 = 0.263696543790          # b/(2πfZ0)·1e3


class TestLoadedLinePhaser:
    def test_design_anchor_values(self):
        r = loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                               delta_phi_deg=PHI_DEG, z0_ohm=Z0)
        assert r["susceptance_norm"] == pytest.approx(B_45, rel=1e-12)
        assert r["spacing_deg"] == pytest.approx(THETA_45, rel=1e-12)
        assert r["spacing_mm"] == pytest.approx(SPACING_MM_45, rel=1e-9)
        assert r["lambda_g_mm"] == pytest.approx(LAMBDA_G_10_3, rel=1e-9)
        assert r["shunt_C_pf"] == pytest.approx(C_PF_45, rel=1e-9)
        assert r["shunt_L_nH"] is None
        assert r["state_loaded_deg"] == pytest.approx(112.5)
        assert r["state_reference_deg"] == pytest.approx(67.5)
        assert r["delta_phi_deg"] == pytest.approx(PHI_DEG, rel=1e-9)
        assert r["matched"] is True
        assert r["route"] == "design_from_delta_phi"

    def test_matched_design_machine_precision(self):
        """匹配设计 S11→0 / |S21|=1（机器精度；匹配面 ABCD 恒等式）。"""
        r = loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                               delta_phi_deg=90.0)
        assert r["s11_mag"] < 1e-12
        assert r["s21_mag"] == pytest.approx(1.0, rel=1e-12)
        assert r["insertion_loss_db"] == pytest.approx(0.0, abs=1e-9)

    def test_numpy_abcd_second_route(self):
        """第二路线：numpy ABCD 级联重算 S/相位（不同算法）。"""
        r = loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                               delta_phi_deg=PHI_DEG)
        m = _abcd_shunt_line_shunt(r["susceptance_norm"],
                                   math.radians(r["spacing_deg"]))
        s11, s21 = _abcd_s(m)
        assert abs(s11) == pytest.approx(r["s11_mag"], rel=1e-9, abs=1e-15)
        assert abs(s21) == pytest.approx(r["s21_mag"], rel=1e-12)
        phi_loaded = (-math.degrees(math.atan2(s21.imag, s21.real))) % 360.0
        assert phi_loaded == pytest.approx(r["state_loaded_deg"], rel=1e-9)

    def test_delta_phi_arctan_identity(self):
        """Δφ=2·arctan(b/2) 恒等式（位态扫 22.5..157.5 全档）。"""
        for phi in (22.5, 45.0, 67.5, 90.0, 112.5, 135.0, 157.5):
            r = loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                                   delta_phi_deg=phi)
            assert 2.0 * math.degrees(
                math.atan(r["susceptance_norm"] / 2.0)) == pytest.approx(
                phi, rel=1e-9)
            assert r["delta_phi_deg"] == pytest.approx(phi, rel=1e-9)
            assert r["equivalent_line_deg"] == pytest.approx(
                180.0 - r["spacing_deg"], rel=1e-9)

    def test_route_roundtrip(self):
        """设计→分析 route roundtrip：同 b/θ 反演回同差分相移。"""
        d = loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                               delta_phi_deg=67.5)
        a = loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                               susceptance_norm=d["susceptance_norm"],
                               spacing_deg=d["spacing_deg"])
        assert a["route"] == "analysis_from_b_theta"
        assert a["delta_phi_deg"] == pytest.approx(67.5, rel=1e-9)
        assert a["matched"] is True

    def test_mismatch_shows_s11(self):
        """失配面：b 偏离 2cotθ → S11>0 如实输出（不静默装匹配）。"""
        a = loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                               susceptance_norm=1.0, spacing_deg=67.5)
        assert a["matched"] is False
        assert a["s11_mag"] > 1e-3
        assert a["match_deviation"] != pytest.approx(0.0)
        # 能量守恒：|S11|²+|S21|²=1（无耗格胞恒等式，第二路线）
        assert a["s11_mag"] ** 2 + a["s21_mag"] ** 2 == pytest.approx(
            1.0, rel=1e-12)

    def test_inductive_susceptance_design(self):
        """感性档（b<0）分析路线：|S| 面仍能量守恒、匹配条件不满足如实。"""
        a = loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                               susceptance_norm=-0.82842712474619,
                               spacing_deg=67.5)
        assert a["s11_mag"] ** 2 + a["s21_mag"] ** 2 == pytest.approx(
            1.0, rel=1e-12)

    def test_domain_rejections(self):
        with pytest.raises(ValueError, match="180"):
            loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                               delta_phi_deg=180.0)
        with pytest.raises(ValueError, match="0"):
            loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF, delta_phi_deg=0.0)
        with pytest.raises(ValueError, match="二选一"):
            loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF, delta_phi_deg=45.0,
                               susceptance_norm=1.0, spacing_deg=45.0)
        with pytest.raises(ValueError, match="全缺"):
            loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF)
        with pytest.raises(ValueError, match="spacing_deg"):
            loaded_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                               susceptance_norm=1.0, spacing_deg=90.0)
        with pytest.raises(ValueError, match="ereff"):
            loaded_line_phaser(f_ghz=F_GHZ, ereff=0.9, delta_phi_deg=45.0)


# ─── switched_line_phaser ─────────────────────────────────────────────────────


class TestSwitchedLinePhaser:
    def test_design_anchor_values(self):
        r = switched_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                                 delta_phi_deg=90.0)
        assert r["delay_line_mm"] == pytest.approx(
            LAMBDA_G_10_3 / 4.0, rel=1e-12)
        assert r["delta_phi_deg"] == pytest.approx(90.0, rel=1e-12)
        assert r["delta_phi_unwrapped_deg"] == pytest.approx(90.0)
        assert r["ref_len_mm"] == pytest.approx(LAMBDA_G_10_3 / 4.0,
                                                rel=1e-12)
        assert r["ref_len_convention"] == "lambda_g_over_4"
        assert r["delay_arm_len_mm"] == pytest.approx(LAMBDA_G_10_3 / 2.0,
                                                      rel=1e-12)

    def test_lambda_g_quarter_is_90_deg(self):
        """Δl=λg/4 → 90°、λg/2 → 180° 精确位（电长度恒等式）。"""
        for bits, expect in ((4.0, 90.0), (2.0, 180.0)):
            dl = LAMBDA_G_10_3 / bits
            r = switched_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                                     delay_line_mm=dl)
            assert r["delta_phi_deg"] == pytest.approx(expect, rel=1e-12)
            assert r["route"] == "analysis_from_delay_line"

    def test_identity_closed_form(self):
        """Δφ=360°·Δl·√εeff·f/c0 恒等式（c0=注册表单源 C_MM_GHZ）。"""
        dl = 7.77
        r = switched_line_phaser(f_ghz=F_GHZ, ereff=EREFF, delay_line_mm=dl)
        expect = 360.0 * dl * math.sqrt(EREFF) * F_GHZ / C_MM_GHZ
        assert r["delta_phi_unwrapped_deg"] == pytest.approx(expect,
                                                             rel=1e-12)
        assert r["delay_line_electrical_deg"] == pytest.approx(
            expect, rel=1e-12)

    def test_ttd_frequency_doubling(self):
        """TTD 恒等：Δφ(2f₀)=2Δφ(f₀)（unwrapped 线性外推零相差误差）。"""
        r1 = switched_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                                  delta_phi_deg=37.0)
        assert r1["ttd_phase_at_2f0_deg"] == pytest.approx(74.0, rel=1e-9)
        r2 = switched_line_phaser(f_ghz=2.0 * F_GHZ, ereff=EREFF,
                                  delay_line_mm=r1["delay_line_mm"])
        assert r2["delta_phi_unwrapped_deg"] == pytest.approx(
            74.0, rel=1e-9)

    def test_group_delay_identity(self):
        """群时延恒等 Δt=Δl√εeff/c0=Δφ/(360°·f)；λg/4@10GHz ↔ 25ps。"""
        r = switched_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                                 delta_phi_deg=90.0)
        assert r["group_delay_ps"] == pytest.approx(25.0, rel=1e-9)
        assert r["group_delay_ns"] == pytest.approx(
            1.0 / (4.0 * F_GHZ), rel=1e-9)  # 1/(4f) 独立恒等式
        assert r["group_delay_ns"] == pytest.approx(
            90.0 / (360.0 * F_GHZ), rel=1e-9)

    def test_route_roundtrip_and_explicit_ref(self):
        d = switched_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                                 delta_phi_deg=45.0, ref_len_mm=5.0)
        assert d["ref_len_convention"] == "explicit"
        assert d["delay_arm_len_mm"] == pytest.approx(
            5.0 + d["delay_line_mm"], rel=1e-12)
        a = switched_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                                 delay_line_mm=d["delay_line_mm"])
        assert a["delta_phi_deg"] == pytest.approx(45.0, rel=1e-9)

    def test_domain_rejections(self):
        with pytest.raises(ValueError, match="360"):
            switched_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                                 delta_phi_deg=360.0)
        with pytest.raises(ValueError, match="二选一"):
            switched_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                                 delta_phi_deg=90.0, delay_line_mm=1.0)
        with pytest.raises(ValueError, match="全缺"):
            switched_line_phaser(f_ghz=F_GHZ, ereff=EREFF)
        with pytest.raises(ValueError, match="delay_line_mm"):
            switched_line_phaser(f_ghz=F_GHZ, ereff=EREFF,
                                 delay_line_mm=-1.0)


# ─── doa_crb_ula ──────────────────────────────────────────────────────────────

N_EL, T_SNAP, SNR_DB, D_LAM = 8, 256, 15.0, 0.5
CRB_VAR_20DEG = 1.6873662969041694e-07   # 实现前闭式复算（rad²）
CRB_STD_DEG_20 = 0.023535710727047972
SNR_DOUBLE_DB = 10.0 * math.log10(2.0)   # 3.0102999566398125


class TestDoaCrbUla:
    def test_anchor_value_and_fields(self):
        r = doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP, snr_db=SNR_DB,
                        spacing_lambda=D_LAM, angle_deg=20.0)
        assert r["crb_var_rad2"] == pytest.approx(CRB_VAR_20DEG, rel=1e-12)
        assert r["crb_std_deg"] == pytest.approx(CRB_STD_DEG_20, rel=1e-12)
        assert r["crb_std_rad"] == pytest.approx(
            math.sqrt(CRB_VAR_20DEG), rel=1e-12)
        assert r["aperture_factor"] == pytest.approx(
            N_EL * (N_EL**2 - 1) / 12.0)
        assert r["fisher_information_per_rad2"] == pytest.approx(
            1.0 / CRB_VAR_20DEG, rel=1e-12)

    def test_numeric_projector_second_route(self):
        """第二路线：numpy 投影器 Fisher 信息（不同算法，全角域）。"""
        for ang in (-60.0, -20.0, 0.0, 30.0, 75.0):
            r = doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP,
                            snr_db=SNR_DB, spacing_lambda=D_LAM,
                            angle_deg=ang)
            num = _crb_numeric(N_EL, T_SNAP, 10.0 ** (SNR_DB / 10.0),
                               D_LAM, math.radians(ang))
            assert r["crb_var_rad2"] == pytest.approx(num, rel=1e-12)

    def test_scaling_laws(self):
        """标度律：×2T→恰 1/2；SNR+3.0103dB→恰 1/2；N 因子精确；1/cos²θ。"""
        base = doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP,
                           snr_db=SNR_DB, spacing_lambda=D_LAM,
                           angle_deg=0.0)["crb_var_rad2"]
        assert doa_crb_ula(n_elements=N_EL, snapshots=2 * T_SNAP,
                           snr_db=SNR_DB, spacing_lambda=D_LAM,
                           angle_deg=0.0)["crb_var_rad2"] == pytest.approx(
            base / 2.0, rel=1e-12)
        assert doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP,
                           snr_db=SNR_DB + SNR_DOUBLE_DB,
                           spacing_lambda=D_LAM,
                           angle_deg=0.0)["crb_var_rad2"] == pytest.approx(
            base / 2.0, rel=1e-12)
        n16 = doa_crb_ula(n_elements=16, snapshots=T_SNAP, snr_db=SNR_DB,
                          spacing_lambda=D_LAM, angle_deg=0.0)["crb_var_rad2"]
        assert n16 / base == pytest.approx(
            (N_EL * (N_EL**2 - 1)) / (16 * (16**2 - 1)), rel=1e-12)
        ang = doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP, snr_db=SNR_DB,
                          spacing_lambda=D_LAM,
                          angle_deg=30.0)["crb_var_rad2"]
        assert ang / base == pytest.approx(1.0 / math.cos(math.radians(30.0))
                                           ** 2, rel=1e-12)

    def test_broadside_minimum_and_even_symmetry(self):
        r0 = doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP, snr_db=SNR_DB,
                         spacing_lambda=D_LAM, angle_deg=0.0)["crb_var_rad2"]
        for ang in (10.0, 45.0, 80.0):
            assert doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP,
                               snr_db=SNR_DB, spacing_lambda=D_LAM,
                               angle_deg=ang)["crb_var_rad2"] > r0
        assert doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP, snr_db=SNR_DB,
                           spacing_lambda=D_LAM,
                           angle_deg=-25.0)["crb_var_rad2"] == pytest.approx(
            doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP, snr_db=SNR_DB,
                        spacing_lambda=D_LAM,
                        angle_deg=25.0)["crb_var_rad2"], rel=1e-15)

    def test_n2_hand_value(self):
        """N=2 手工锚：aperture=1/2 → CRB=1/(2·T·SNR·aperture·k²)。"""
        r = doa_crb_ula(n_elements=2, snapshots=100, snr_db=10.0,
                        spacing_lambda=0.5, angle_deg=0.0)
        k = 2.0 * math.pi * 0.5
        expect = 1.0 / (2.0 * 100.0 * 10.0 * 0.5 * k * k)
        assert r["crb_var_rad2"] == pytest.approx(expect, rel=1e-12)
        assert r["crb_var_rad2"] == pytest.approx(
            12.0 / (2.0 * 100.0 * 10.0 * 6.0 * k * k), rel=1e-12)
        assert r["aperture_factor"] == pytest.approx(0.5)

    def test_service_envelope_and_domain(self):
        params = {"n_elements": N_EL, "snapshots": T_SNAP, "snr_db": SNR_DB,
                  "spacing_lambda": D_LAM, "angle_deg": 20.0}
        env = run_calculator("doa_crb_ula", params)
        assert env["ok"] is True
        env2 = run_calculator("doa_crb_ula", params)
        import json
        assert json.dumps(env, sort_keys=True) == json.dumps(env2,
                                                             sort_keys=True)
        for bad in ({"n_elements": 1}, {"snapshots": 0},
                    {"angle_deg": 90.0}, {"spacing_lambda": 1.5},
                    {"angle_deg": 90.5}):
            out = run_calculator("doa_crb_ula", {**params, **bad})
            assert out["ok"] is False, f"{bad} 未显式拒绝"


# ─── multiplexer_channel_plan ─────────────────────────────────────────────────

MUX_ANCHOR_FC = (2.378414230005442, 3.363585661014858,
                 4.756828460010884, 6.727171322029716)
MUX_ANCHOR_XO = (2.8284271247461903, 4.0, 5.656854249492381)
CROSSOVER_LOSS_DB = 3.0102999566398125


class TestMultiplexerChannelPlan:
    def test_equal_fractional_anchor(self):
        r = multiplexer_channel_plan(f_start_ghz=2.0, f_stop_ghz=8.0,
                                     n_channels=4)
        fc = [ch["f_center_ghz"] for ch in r["channels"]]
        xo = r["crossover_points_ghz"]
        for got, expect in zip(fc, MUX_ANCHOR_FC, strict=True):
            assert got == pytest.approx(expect, rel=1e-12)
        for got, expect in zip(xo, MUX_ANCHOR_XO, strict=True):
            assert got == pytest.approx(expect, rel=1e-12)
        assert r["crossover_loss_db"] == pytest.approx(CROSSOVER_LOSS_DB,
                                                       rel=1e-15)
        assert r["band_utilization"] == pytest.approx(1.0, rel=1e-12)
        assert r["spacing"] == "equal_fractional"

    def test_geometric_identities(self):
        """等分数三恒等式：交越=几何中点/对称 fc_k·fc_{N−1−k}=f1·f2/Σ=带。"""
        r = multiplexer_channel_plan(f_start_ghz=2.0, f_stop_ghz=8.0,
                                     n_channels=5)
        fc = [ch["f_center_ghz"] for ch in r["channels"]]
        xo = r["crossover_points_ghz"]
        for i in range(len(xo)):
            assert xo[i] == pytest.approx(math.sqrt(fc[i] * fc[i + 1]),
                                          rel=1e-12)
        for k in range(len(fc)):
            assert fc[k] * fc[-1 - k] == pytest.approx(2.0 * 8.0, rel=1e-12)
        assert math.fsum(ch["bandwidth_ghz"]
                         for ch in r["channels"]) == pytest.approx(
            6.0, rel=1e-12)
        # 分数带宽统一定义 (hi−lo)/center（等分数口径逐道数学同值，
        # 浮点尾差 ≤1e-15 相对量）
        fr = [ch["fractional_bw"] for ch in r["channels"]]
        assert all(v == pytest.approx(fr[0], rel=1e-12) for v in fr)
        assert fr[0] == pytest.approx(4.0 ** (1.0 / 10) - 4.0 ** (-1.0 / 10),
                                      rel=1e-12)

    def test_equal_absolute_anchor(self):
        r = multiplexer_channel_plan(f_start_ghz=2.0, f_stop_ghz=8.0,
                                     n_channels=4, spacing="equal_absolute")
        fc = [ch["f_center_ghz"] for ch in r["channels"]]
        assert fc == pytest.approx([2.75, 4.25, 5.75, 7.25], rel=1e-12)
        assert r["crossover_points_ghz"] == pytest.approx(
            [3.5, 5.0, 6.5], rel=1e-12)
        for ch in r["channels"]:
            assert ch["bandwidth_ghz"] == pytest.approx(1.5, rel=1e-12)
        for i, x in enumerate(r["crossover_points_ghz"]):
            assert x == pytest.approx((fc[i] + fc[i + 1]) / 2.0, rel=1e-12)

    def test_service_envelope_and_domain(self):
        env = run_calculator("multiplexer_channel_plan",
                             {"f_start_ghz": 2.0, "f_stop_ghz": 8.0,
                              "n_channels": 4})
        assert env["ok"] is True
        for bad in ({"f_start_ghz": 8.0, "f_stop_ghz": 2.0},
                    {"f_start_ghz": 2.0, "f_stop_ghz": 2.0},
                    {"f_start_ghz": 0.0, "f_stop_ghz": 8.0},
                    {"n_channels": 1},
                    {"n_channels": 129},
                    {"spacing": "geometric"}):
            out = run_calculator("multiplexer_channel_plan",
                                 {"f_start_ghz": 2.0, "f_stop_ghz": 8.0,
                                  "n_channels": 4, **bad})
            assert out["ok"] is False, f"{bad} 未显式拒绝"

    def test_domain_rejections_direct(self):
        with pytest.raises(ValueError, match="n_channels"):
            multiplexer_channel_plan(f_start_ghz=2.0, f_stop_ghz=8.0,
                                     n_channels=True)
        with pytest.raises(ValueError, match="spacing"):
            multiplexer_channel_plan(f_start_ghz=2.0, f_stop_ghz=8.0,
                                     n_channels=4, spacing="log")
