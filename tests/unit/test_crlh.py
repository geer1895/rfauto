"""MM-4 CRLH 内核单测（core/crlh.py，round17 §五 :146）。

裁判 = 外部独立来源（#118：不是被测实现的自我推导）：
  * 锚值独立落盘：runs/mm4/anchor_derivation.py（不 import 被测实现的
    独立闭式+skrf 级联现写实现，输出 runs/mm4/anchor_output.txt，本文件
    逐值写死）；
  * 闭式恒等式：平衡点 β 过零 = ω_se = ω_sh = ZOR（scipy.brentq 数值
    求根对拍）、平衡 Z_CRLH ≡ √(L_R/C_R)（Caloz-Itoh 经典结果）、
    深阻带 Bloch 相位 Re β = −π/d（周期结构理论精确值）、
    ZOR 规格公式 1/√(L_L·C_R) 直接回收；
  * skrf 独立级联仿真（spec 验收口径 ≤0.1 dB / 1°）：T 单元原语
    （L_R/2 串 2C_L —— 并 C_R、并 L_L —— 重复）经 skrf.Network 的
    ** 级联、双端镜像阻抗终接，对拍闭式 S21=exp(−jβNd)——实测
    |Δ|≈1e-14 dB / 1e-13°（12 个量级余量）。对拍限定传播频段：skrf
    a2s 是 power-wave 口径（S21∝√(Re z01·Re z02)），阻带镜像阻抗纯虚
    时无定义；阻带面由闭式锚（Re β=0、Im β<0、|Z|→∞ 高阻极限）钉。

确定性：无网络、无真机、无文件 IO、无随机（skrf 级联为纯内存构造）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.crlh import (
    SPEED_OF_LIGHT_M_PER_S,
    crlh_beta,
    crlh_bloch_impedance,
    crlh_image_impedance_t,
    crlh_s21_closed_form,
    crlh_skrf_cascade_s21,
    crlh_unit_cell_report,
    imbalance_parameter,
    leaky_wave_angle_deg,
    series_resonance_omega,
    shunt_resonance_omega,
    zeroth_order_resonance_omega,
)
from rfauto.service.calculator_service import run_calculator

# ── 名义例（runs/mm4/anchor_derivation.py 同参）─────────────────────────
# 平衡：L_R=L_L=10 nH、C_L=C_R=2.5 pF、d=5 mm
L_R = 10.0e-9
C_L = 2.5e-12
L_L_BAL = 10.0e-9
C_R = 2.5e-12
D = 5.0e-3
# 非平衡：仅 L_L 改 4 nH → f_sh=1.59155 GHz > f_se=1.00658 GHz
L_L_UNBAL = 4.0e-9

W0 = 1.0 / math.sqrt(L_R * C_L)  # 6.324555320336759e9 rad/s
F0 = W0 / (2 * math.pi)  # 1.0065842420897408 GHz
Z0_BAL = math.sqrt(L_R / C_R)  # 63.24555320336759 Ω


# ── 1) 谐振对与平衡条件 ──────────────────────────────────────────────────

class TestResonancesAndBalance:
    def test_resonance_formulas_exact(self) -> None:
        assert series_resonance_omega(L_R, C_L) == pytest.approx(W0)
        assert shunt_resonance_omega(L_L_BAL, C_R) == pytest.approx(W0)
        # 平衡 ⇔ L_R·C_L = L_L·C_R → f_se = f_sh
        assert series_resonance_omega(L_R, C_L) == pytest.approx(
            shunt_resonance_omega(L_L_BAL, C_R))

    def test_balance_identity_values(self) -> None:
        imb = imbalance_parameter(L_R, C_L, L_L_BAL, C_R)
        assert imb["imbalance"] == pytest.approx(0.0, abs=1e-15)
        assert imb["balance_ratio"] == pytest.approx(1.0)

    def test_imbalance_signed_anchor(self) -> None:
        # 非平衡独立锚：δ=−0.4502964531088276、比值=0.6324555320336759
        imb = imbalance_parameter(L_R, C_L, L_L_UNBAL, C_R)
        assert imb["imbalance"] == pytest.approx(-0.4502964531088276)
        assert imb["balance_ratio"] == pytest.approx(0.6324555320336759)
        # 符号带向：f_se<f_sh → 负
        assert imb["imbalance"] < 0.0

    def test_negative_lc_rejected(self) -> None:
        with pytest.raises(ValueError, match="必须为正"):
            crlh_beta(2 * math.pi * 1e9, -L_R, C_L, L_L_BAL, C_R, D)
        with pytest.raises(ValueError, match="必须为正"):
            crlh_bloch_impedance(2 * math.pi * 1e9, L_R, -C_L,
                                 L_L_BAL, C_R)
        with pytest.raises(ValueError, match="必须为正"):
            imbalance_parameter(L_R, C_L, 0.0, C_R)
        with pytest.raises(ValueError, match="必须为正"):
            crlh_unit_cell_report(L_R, C_L, L_L_BAL, C_R, 1e9, -D)

    def test_zero_omega_rejected(self) -> None:
        with pytest.raises(ValueError, match="omega_rad_s"):
            crlh_beta(0.0, L_R, C_L, L_L_BAL, C_R, D)
        with pytest.raises(ValueError, match="omega_rad_s"):
            crlh_bloch_impedance(-1.0, L_R, C_L, L_L_BAL, C_R)


# ── 2) 平衡点恒等（β 过零 = 平衡点，数值求根对拍）────────────────────────

class TestBalancePointIdentity:
    def test_beta_zero_crossing_equals_balance_point(self) -> None:
        from scipy.optimize import brentq

        def re_beta(f: float) -> float:
            return float(np.real(crlh_beta(
                2 * math.pi * f, L_R, C_L, L_L_BAL, C_R, D)))

        # 左手段负、右手端正（过零存在性由符号变号保证）
        assert re_beta(0.9e9) < 0.0
        assert re_beta(1.2e9) > 0.0
        root = brentq(re_beta, 0.9e9, 1.2e9, xtol=1e-3)
        # 恒等式：β 过零频率 = f_se = f_sh（独立锚 1.0065842420171 GHz，
        # brentq 默认 xtol 给 rel 7e-11；容差 1e-6 覆盖求根离散）
        assert root == pytest.approx(F0, rel=1e-6)

    def test_beta_sign_semantics(self) -> None:
        # 左手频段 β<0（相位超前符号钉）：独立锚 −344.23119405244427
        b_lh = crlh_beta(2 * math.pi * 0.5e9, L_R, C_L, L_L_BAL, C_R, D)
        assert float(np.real(b_lh)) == pytest.approx(-344.23119405244427)
        assert float(np.real(b_lh)) < 0.0
        assert float(np.imag(b_lh)) == pytest.approx(0.0, abs=1e-9)
        # 右手频段 β>0：独立锚 +334.30780156626344
        b_rh = crlh_beta(2 * math.pi * 2.0e9, L_R, C_L, L_L_BAL, C_R, D)
        assert float(np.real(b_rh)) == pytest.approx(334.30780156626344)
        assert float(np.real(b_rh)) > 0.0

    def test_unbalanced_propagating_and_stopband(self) -> None:
        # 非平衡传播频段（LH 带 (0.7118,1.0066) GHz / RH 带
        # (1.5915,2.2508) GHz）：β 实、左手负/右手正
        b = crlh_beta(2 * math.pi * 0.9e9, L_R, C_L, L_L_UNBAL, C_R, D)
        assert float(np.real(b)) == pytest.approx(-133.07591482782465)
        assert float(np.imag(b)) == pytest.approx(0.0, abs=1e-9)
        b = crlh_beta(2 * math.pi * 1.8e9, L_R, C_L, L_L_UNBAL, C_R, D)
        assert float(np.real(b)) == pytest.approx(141.42755598839813)
        assert float(np.imag(b)) == pytest.approx(0.0, abs=1e-9)
        # 阻带 1.3 GHz（介于 f_se 与 f_sh）：Re=0、Im<0（无源衰减）
        b = crlh_beta(2 * math.pi * 1.3e9, L_R, C_L, L_L_UNBAL, C_R, D)
        assert float(np.real(b)) == pytest.approx(0.0, abs=1e-9)
        assert float(np.imag(b)) == pytest.approx(-113.9018921061866)

    def test_deep_stopband_bloch_phase_minus_pi_over_d(self) -> None:
        # 周期结构理论：深阻带 Bloch 相位 = ±π/d（精确恒等式）。
        # 非平衡例 0.5 GHz 在 LH 带下缘（f_CL≈0.7118 GHz）之下 → Re β=−π/d
        b = crlh_beta(2 * math.pi * 0.5e9, L_R, C_L, L_L_UNBAL, C_R, D)
        assert float(np.real(b)) == pytest.approx(
            -math.pi / D, rel=1e-9)  # 独立锚 −628.3185307179587
        assert float(np.imag(b)) < 0.0

    def test_passivity_im_beta_nonpositive(self) -> None:
        # 全频段扫描：无源口径 Im β ≤ 0（e^{+jωt}/e^{−jβz} 约定）
        f = np.linspace(0.05e9, 4e9, 400)
        b = crlh_beta(2 * math.pi * f, L_R, C_L, L_L_UNBAL, C_R, D)
        assert np.all(np.imag(b) <= 1e-9)


# ── 3) ZOR（规格口径）恒等 ───────────────────────────────────────────────

class TestZorIdentity:
    def test_zor_spec_formula_recovery(self) -> None:
        # 规格公式 ω_ZOR = 1/√(L_L·C_R)（round17 :146）直接回收
        assert zeroth_order_resonance_omega(
            L_L_UNBAL, C_R) == pytest.approx(1.0 / math.sqrt(L_L_UNBAL * C_R))
        # 独立锚：f_ZOR = 1.5915494309189535 GHz
        assert zeroth_order_resonance_omega(
            L_L_UNBAL, C_R) / (2 * math.pi) == pytest.approx(
            1.5915494309189535e9)

    def test_balanced_zor_equals_beta_zero_crossing(self) -> None:
        # 平衡时 ZOR = ω_se = ω_sh = β 过零频率（三线合一）
        assert zeroth_order_resonance_omega(
            L_L_BAL, C_R) == pytest.approx(series_resonance_omega(L_R, C_L))
        assert zeroth_order_resonance_omega(
            L_L_BAL, C_R) == pytest.approx(shunt_resonance_omega(
                L_L_BAL, C_R))
        assert pytest.approx(1.0065842420897408e9) == F0


# ── 4) Z_CRLH 阻抗 ───────────────────────────────────────────────────────

class TestZCrlh:
    def test_balanced_frequency_independent(self) -> None:
        # Caloz-Itoh 经典结果：平衡时 Z_CRLH ≡ √(L_R/C_R)，与频率无关
        for f in (0.5e9, 1.5e9, 2.0e9, 3.5e9):
            z = crlh_bloch_impedance(2 * math.pi * f, L_R, C_L,
                                     L_L_BAL, C_R)
            assert complex(z) == pytest.approx(Z0_BAL + 0j, rel=1e-9,
                                               abs=1e-9)

    def test_stopband_purely_imaginary_anchor(self) -> None:
        # 阻带 1.3 GHz：Z 纯虚，独立锚 (0, +56.66761876532746)——
        # 阻带支路规范化 +j√|ratio|（np.sqrt 主支 +0j 口径；直接 z/y
        # 相除会得 −0.0j 浮点尘给出 −j√ 分支伪象，见锚脚本注）
        z = crlh_bloch_impedance(2 * math.pi * 1.3e9, L_R, C_L,
                                 L_L_UNBAL, C_R)
        assert float(np.real(z)) == pytest.approx(0.0, abs=1e-9)
        assert float(np.imag(z)) == pytest.approx(56.66761876532746)

    def test_stopband_high_impedance_limit(self) -> None:
        # 阻带高阻极限：ω→ω_sh（并联谐振 Y→0 开路）|Z|→∞
        f_sh = shunt_resonance_omega(L_L_UNBAL, C_R) / (2 * math.pi)
        z1 = abs(complex(crlh_bloch_impedance(
            2 * math.pi * 0.99 * f_sh, L_R, C_L, L_L_UNBAL, C_R)))
        z2 = abs(complex(crlh_bloch_impedance(
            2 * math.pi * 0.999 * f_sh, L_R, C_L, L_L_UNBAL, C_R)))
        # 独立锚：|Z|@0.999·f_sh = 1093.8922708155637 Ω，且单调增长
        assert z2 == pytest.approx(1093.8922708155637, rel=1e-9)
        assert z2 > z1 > Z0_BAL

    def test_propagating_positive_real(self) -> None:
        # 传播频段取正实根
        z = crlh_bloch_impedance(2 * math.pi * 0.5e9, L_R, C_L,
                                 L_L_BAL, C_R)
        assert float(np.real(z)) > 0.0
        assert float(np.imag(z)) == pytest.approx(0.0, abs=1e-9)

    def test_image_impedance_t_matches_bloch_at_omega0(self) -> None:
        # 平衡单元 ω=ω_0（Z=0）处 Z_T = Z_CRLH = √(L_R/C_R)
        zt = crlh_image_impedance_t(W0, L_R, C_L, L_L_BAL, C_R)
        assert complex(zt) == pytest.approx(Z0_BAL + 0j, rel=1e-9, abs=1e-9)


# ── 5) 漏波角闭式 ────────────────────────────────────────────────────────

class TestLeakyWaveAngle:
    def test_backward_beam_negative_angle(self) -> None:
        # 左手频段近平衡点（β<0、|β|<k0）：负角（后向辐射）
        # 独立锚：β=−3.4259490967463995、k0=20.916533319077786、
        # θ=−9.42703391857233°
        assert leaky_wave_angle_deg(
            -3.4259490967463995, 0.998e9) == pytest.approx(
            -9.42703391857233)

    def test_forward_beam_positive_angle(self) -> None:
        # 右手频段对称点：正角（前向辐射），独立锚 +9.007238464903727°
        assert leaky_wave_angle_deg(
            3.330457696753083, 1.015e9) == pytest.approx(9.007238464903727)

    def test_slow_wave_no_radiation_none(self) -> None:
        # |Re β| ≥ k0 → 快波条件不满足 → None（不外推）
        assert leaky_wave_angle_deg(-344.23119405244427, 0.5e9) is None
        assert leaky_wave_angle_deg(334.30780156626344, 2.0e9) is None
        # 恰好 |β|=k0 → 边界 None（开区间口径）
        k0 = 2 * math.pi * 1e9 / SPEED_OF_LIGHT_M_PER_S
        assert leaky_wave_angle_deg(k0, 1e9) is None


# ── 6) skrf 级联对拍（spec 验收：闭式 vs skrf ≤0.1 dB / 1°）──────────────

class TestSkrfCascadeAcceptance:
    N_CELLS = 8
    F_PTS = np.array([0.5e9, 1.5e9, 2.0e9])  # 全在传播频段

    def _cascade(self) -> tuple[np.ndarray, np.ndarray]:
        res = crlh_skrf_cascade_s21(
            self.F_PTS, L_R, C_L, L_L_BAL, C_R, self.N_CELLS)
        closed = crlh_s21_closed_form(
            2 * math.pi * self.F_PTS, L_R, C_L, L_L_BAL, C_R, D,
            self.N_CELLS)
        return np.asarray(res["s21"]), closed

    def test_image_matched_s11_is_zero(self) -> None:
        # 镜像阻抗终接 → S11=0（匹配证明，独立锚 ~1e-16）
        res = crlh_skrf_cascade_s21(
            self.F_PTS, L_R, C_L, L_L_BAL, C_R, self.N_CELLS)
        assert np.all(np.abs(np.asarray(res["s11"])) < 1e-9)

    def test_closed_form_vs_skrf_within_spec(self) -> None:
        s21, closed = self._cascade()
        # 幅度差 ≤0.1 dB（实测 ~1e-14 dB）
        db = 20.0 * np.log10(np.abs(s21) / np.abs(closed))
        assert np.all(np.abs(db) <= 0.1)
        # 相位差 ≤1°（实测 ~1e-13°；两支独立计算的相位差）
        deg = np.degrees(np.angle(s21 * np.conj(closed)))
        assert np.all(np.abs(deg) <= 1.0)
        # 且整体逐位一致（机器精度）
        np.testing.assert_allclose(s21, closed, atol=1e-12)

    def test_lh_band_phase_advance_in_s21(self) -> None:
        # 左手频段 S21 相位为正（相位超前，β<0 的独立电路仿真互证）
        s21, _ = self._cascade()
        assert np.angle(s21[0]) > 0.0  # 0.5 GHz ∈ LH 带

    def test_stopband_z0_rejected_explicitly(self) -> None:
        # 阻带镜像阻抗纯虚 → power-wave S 无定义 → 显式 ValueError 不外推
        with pytest.raises(ValueError, match="传播频段"):
            crlh_skrf_cascade_s21(
                1.3e9, L_R, C_L, L_L_UNBAL, C_R, self.N_CELLS)

    def test_negative_n_cells_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_cells"):
            crlh_skrf_cascade_s21(1e9, L_R, C_L, L_L_BAL, C_R, 0)


# ── 7) 点分析报告（注册键内核面）─────────────────────────────────────────

class TestUnitCellReport:
    def test_balanced_report_band_and_json(self) -> None:
        r = crlh_unit_cell_report(L_R, C_L, L_L_BAL, C_R, 0.5e9, D)
        assert r["band"] == "left_hand"
        assert r["balanced"] is True
        assert r["z_crlh_abs_ohm"] == pytest.approx(Z0_BAL)
        assert r["beta_rad_per_m"][0] == pytest.approx(-344.23119405244427)
        assert r["leaky_wave_angle_deg"] is None  # |β|>k0
        # JSON 可序列化（None→null、无复数/数组溢出）
        json.dumps(r, allow_nan=False)

    def test_unbalanced_stopband_report(self) -> None:
        r = crlh_unit_cell_report(L_R, C_L, L_L_UNBAL, C_R, 1.3e9, D)
        assert r["band"] == "stopband"
        assert r["balanced"] is False
        assert r["beta_rad_per_m"] == pytest.approx(
            [0.0, -113.9018921061866])
        assert r["z_crlh_ohm"] == pytest.approx([0.0, 56.66761876532746])
        assert r["attenuation_np_per_m"] == pytest.approx(113.9018921061866)
        # dB/单元 = α·d·8.6859（独立锚 4.94669632200564）
        assert r["attenuation_db_per_cell"] == pytest.approx(4.94669632200564)
        assert r["leaky_wave_angle_deg"] is None  # 阻带不辐射（伪边射钉）

    def test_transition_band_label_balanced(self) -> None:
        # 平衡单元在 f_se=f_sh 处为无缝过渡点（非 stopband）
        r = crlh_unit_cell_report(L_R, C_L, L_L_BAL, C_R, F0, D)
        assert r["band"] == "transition"

    def test_right_hand_band(self) -> None:
        r = crlh_unit_cell_report(L_R, C_L, L_L_BAL, C_R, 2.0e9, D)
        assert r["band"] == "right_hand"
        assert r["beta_rad_per_m"][0] == pytest.approx(334.30780156626344)

    def test_leaky_angle_forward_report(self) -> None:
        r = crlh_unit_cell_report(L_R, C_L, L_L_BAL, C_R, 1.015e9, D)
        assert r["leaky_wave_angle_deg"] == pytest.approx(9.007238464903727)
        assert r["band"] == "right_hand"


# ── 8) 注册键（mm/GHz/pF/nH 壳 + service JSON 面）────────────────────────

class TestRegisteredKey:
    KEY = "crlh_unit_cell_report"

    def test_registry_has_key(self) -> None:
        from rfauto.core.calculators import CALCULATOR_REGISTRY

        assert self.KEY in CALCULATOR_REGISTRY.names()

    def test_unit_conversion_chain(self) -> None:
        # mm/GHz/pF/nH 壳换算链：10nH/2.5pF 平衡例 0.5 GHz 复现内核锚
        r = run_calculator(self.KEY, {
            "l_r_nh": 10.0, "c_l_pf": 2.5, "l_l_nh": 10.0,
            "c_r_pf": 2.5, "f_ghz": 0.5, "cell_len_mm": 5.0,
        })
        assert r["ok"] is True, r.get("error")
        res = r["result"]
        assert res["z_crlh_abs_ohm"] == pytest.approx(Z0_BAL)
        assert res["f_se_hz"] == pytest.approx(F0)
        assert res["band"] == "left_hand"

    def test_negative_l_ok_false(self) -> None:
        r = run_calculator(self.KEY, {
            "l_r_nh": -1.0, "c_l_pf": 2.5, "l_l_nh": 10.0,
            "c_r_pf": 2.5, "f_ghz": 0.5,
        })
        assert r["ok"] is False and r.get("error")

    def test_missing_required_ok_false(self) -> None:
        r = run_calculator(self.KEY, {"l_r_nh": 10.0, "f_ghz": 0.5})
        assert r["ok"] is False and "缺少必需参数" in r.get("error", "")
