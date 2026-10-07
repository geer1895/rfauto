"""MT-4 接收机损伤三件套锚测试（round17 MT-4 规格，2026-10-02）。

锚口径（#118 裁判纪律：每件至少一条**独立代数排布/独立裁判路径**）：

- **IRR 极限退化**：ε=1 → IRR=cot²(φ/2)（独立三角恒等式手算）；
  φ=0 → IRR=((1+ε)/|1−ε|)²（完全平方因式分解，独立排布）；任意点 →
  复数模形式 IRR=|1+εe^{jφ}|²/|1−εe^{jφ}|²（复幅度路径，与实数三角
  式代数不同源）；evm_rms²=1/IRR 恒等自洽。
- **相噪 EVM**：平谱 L=−100 dBc/Hz@[1kHz,10MHz] → σ_φ=√(2·10⁻¹⁰·
  (10⁷−10³)) 手算逐位（实现消费 clock_noise 积分——同一公式不在本面
  重复实现，锚检验的是消费链+口径转换）。
- **倒易混频/desense**：线性域 mW 算术独立路径（N_floor_mW=kTB·F、
  desense=10log10((N_floor+N_rm)/N_floor)，与实现的 dB 域对数差排布
  不同源）；(2,2) 教科书杂散落带（与 core/cascade docstring 钉值同源）
  + (2,1) 高危落带翻 spur_ok。
- **P1dB 裕量**：p1db_in=−20 dBm（OP1dB=0 经 −7dB 混频折算）手算，
  blocker ±10 dB 翻转 p1db_ok。

零外部数据捆绑：全部锚=闭式恒等式/独立排布手算，无文件依赖。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.rx_impairments import (
    blocking_budget,
    iq_imbalance_irr,
    phase_noise_evm,
)
from rfauto.service.calculator_service import run_calculator

# 名义接收链（OP1dB=0 dBm@LNA 输出口径 p1db_dbm=该级输出 1dB 压缩点）
STAGES_RX = [
    {"type": "amp", "gain_db": 20.0, "nf_db": 2.0, "p1db_dbm": 0.0},
    {"type": "mixer", "gain_db": -7.0, "nf_db": 8.0},
]


# ─── 件 1：IQ 失衡 IRR ───────────────────────────────────────────────────────


class TestIqImbalanceIrr:
    def test_pure_phase_cot_half_angle(self):
        # ε=1 → IRR = cot²(φ/2)（独立三角恒等式）
        r = iq_imbalance_irr(0.0, 5.0)
        expect = 10.0 * math.log10(
            1.0 / math.tan(math.radians(2.5)) ** 2)
        assert r["irr_db"] == pytest.approx(expect, rel=1e-12)
        assert r["irr_db"] == pytest.approx(27.19813778868883, rel=1e-12)

    def test_pure_gain_perfect_square(self):
        # φ=0 → IRR = ((1+ε)/|1−ε|)²（完全平方分解，独立排布）
        r = iq_imbalance_irr(1.0, 0.0)
        eps = 10.0 ** 0.05
        expect = 20.0 * math.log10((1.0 + eps) / (eps - 1.0))
        assert r["irr_db"] == pytest.approx(expect, rel=1e-12)
        assert r["irr_db"] == pytest.approx(24.80647274592972, rel=1e-12)

    def test_generic_point_complex_form(self):
        # 任意点 → 复数模形式 |1+εe^{jφ}|²/|1−εe^{jφ}|²（与实数三角式不同源）
        a, d = 0.5, 3.0
        r = iq_imbalance_irr(a, d)
        e = 10.0 ** (a / 20.0)
        ph = complex(math.cos(math.radians(d)), math.sin(math.radians(d)))
        expect = 10.0 * math.log10(abs(1 + e * ph) ** 2 / abs(1 - e * ph) ** 2)
        assert r["irr_db"] == pytest.approx(expect, rel=1e-12)

    def test_evm_identity_and_monotonic(self):
        r = iq_imbalance_irr(0.5, 3.0)
        assert r["evm_rms"] ** 2 == pytest.approx(1.0 / r["irr_linear"],
                                                  rel=1e-12)
        assert r["evm_db"] == pytest.approx(-r["irr_db"], rel=1e-12)
        worse = iq_imbalance_irr(0.5, 10.0)
        assert worse["irr_db"] < r["irr_db"]
        # 符号对称：IRR 同值
        assert iq_imbalance_irr(0.5, -3.0)["irr_db"] == pytest.approx(
            r["irr_db"], rel=1e-15)

    def test_perfect_balance_and_full_image(self):
        r0 = iq_imbalance_irr(0.0, 0.0)
        assert r0["irr_db"] is None and r0["balanced"] is True
        assert r0["evm_rms"] == 0.0
        r180 = iq_imbalance_irr(0.0, 180.0)
        assert r180["full_image"] is True
        assert r180["irr_linear"] == 0.0
        assert r180["irr_db"] is None and r180["evm_rms"] is None

    def test_phase_domain_guard(self):
        with pytest.raises(ValueError, match="180"):
            iq_imbalance_irr(0.5, 200.0)


# ─── 件 2：相噪 → 积分 EVM ───────────────────────────────────────────────────


class TestPhaseNoiseEvm:
    def test_flat_spectrum_hand_integral(self):
        # σ_φ = √(2·10^(L/10)·(f2−f1))：平谱闭式手算
        r = phase_noise_evm([1e3, 1e7], [-100.0, -100.0])
        expect = math.sqrt(2.0 * 1e-10 * (1e7 - 1e3))
        assert r["sigma_phi_rad"] == pytest.approx(expect, rel=1e-12)
        assert r["evm_rms"] == pytest.approx(expect, rel=1e-12)
        assert r["evm_percent"] == pytest.approx(100.0 * expect, rel=1e-12)
        assert r["evm_db"] == pytest.approx(20.0 * math.log10(expect),
                                            rel=1e-12)
        assert r["small_angle_ok"] is True

    def test_small_angle_flag(self):
        # 大积分量：σ_φ 明显超 0.5 rad → 旗标翻 False（不静默）
        r = phase_noise_evm([1e2, 1e7], [-60.0, -60.0])
        assert r["sigma_phi_rad"] > 0.5
        assert r["small_angle_ok"] is False

    def test_jitter_passthrough(self):
        r = phase_noise_evm([1e3, 1e7], [-100.0, -100.0], f_carrier_hz=1e10)
        assert r["jitter_s"] == pytest.approx(
            r["sigma_phi_rad"] / (2.0 * math.pi * 1e10), rel=1e-12)

    def test_freq_edges_guard(self):
        with pytest.raises(ValueError):
            phase_noise_evm([1e7, 1e3], [-100.0, -100.0])


# ─── 件 3：blocking / 信道选择性预算 ─────────────────────────────────────────


class TestBlockingBudget:
    def _budget(self, **kw):
        base = dict(stages=STAGES_RX, bw_hz=1e4, blocker_dbm=-30.0,
                    f_blocker_hz=2.4e9, f_lo_hz=2.1e9,
                    lo_phase_noise_dbc_hz=-100.0, f_rx_hz=2.7e9,
                    filter_rejection_db=20.0, max_order=4)
        base.update(kw)
        return blocking_budget(**base)

    def test_desense_independent_mw_arithmetic(self):
        # 线性域 mW 算术独立路径（与实现 dB 域对数差排布不同源）
        b = self._budget()
        k_tb_mw_per_hz = 1.380649e-23 * 290.0 * 1e3
        f_lin = 10.0 ** 0.2 + (10.0 ** 0.8 - 1.0) / 100.0  # 20dB+(-7dB) Friis
        n_floor_mw = k_tb_mw_per_hz * 1e4 * f_lin
        n_rm_mw = 10.0 ** ((-50.0 - 100.0 + 40.0) / 10.0)
        assert b["n_floor_dbm"] == pytest.approx(
            10.0 * math.log10(n_floor_mw), rel=1e-12)
        assert b["n_floor_dbm"] == pytest.approx(-131.8320775789494,
                                                 rel=1e-12)
        assert b["n_recip_mix_dbm"] == pytest.approx(-110.0, abs=1e-12)
        assert b["desense_db"] == pytest.approx(
            10.0 * math.log10((n_floor_mw + n_rm_mw) / n_floor_mw), rel=1e-12)
        assert b["desense_db"] == pytest.approx(21.860466985217375, rel=1e-12)
        assert b["desense_ok"] is False and b["pass"] is False

    def test_rejection_monotonic(self):
        b20 = self._budget()
        b30 = self._budget(filter_rejection_db=30.0)
        assert b30["desense_db"] < b20["desense_db"]
        assert b30["blocker_at_mixer_dbm"] == pytest.approx(-60.0, abs=1e-12)

    def test_weak_blocker_no_desense(self):
        # 阻塞远低于噪声底 → desense→0（数值零）
        b = self._budget(blocker_dbm=-200.0)
        assert b["desense_db"] == pytest.approx(0.0, abs=1e-9)
        assert b["desense_ok"] is True

    def test_p1db_margin_hand_calc_and_flip(self):
        # p1db_in = OP1dB(0) + G_after(−7) − G_tot(13) = −20 dBm（手算）
        b = self._budget()
        assert b["p1db_margin_db"] == pytest.approx(10.0, abs=1e-12)
        assert b["p1db_ok"] is True
        b_hot = self._budget(blocker_dbm=-10.0)
        assert b_hot["p1db_margin_db"] == pytest.approx(-10.0, abs=1e-12)
        assert b_hot["p1db_ok"] is False and b_hot["pass"] is False

    def test_spur_textbook_inband_medium(self):
        # (2,2,−) 落带（与 core/cascade docstring 教科书钉值同源）：medium
        b = self._budget()
        assert b["if_center_hz"] == pytest.approx(600e6, abs=1e-6)
        assert b["n_in_band_spurs"] == 1
        s = b["in_band_spurs"][0]
        assert (s["m"], s["n"], s["side"]) == (2, 2, "-")
        assert s["hazard"] == "medium" and b["spur_ok"] is True

    def test_spur_high_hazard_fails(self):
        # blocker=1.2 GHz / LO=2.1 GHz → (2,1) 3 阶产物 |2·1.2−2.1|=0.3GHz
        # 正落期望 IF=|1.8−2.1|=300MHz → high 落带 → spur_ok False
        b = self._budget(f_blocker_hz=1.2e9, f_rx_hz=1.8e9, bw_hz=1e5,
                         filter_rejection_db=0.0,
                         lo_phase_noise_dbc_hz=-150.0)
        assert b["spur_ok"] is False and b["pass"] is False
        assert any(s["hazard"] == "high" for s in b["in_band_spurs"])

    def test_desense_limit_flip(self):
        b = self._budget(lo_phase_noise_dbc_hz=-300.0)
        assert b["desense_ok"] is True
        b_tight = self._budget(lo_phase_noise_dbc_hz=-300.0,
                               desense_limit_db=0.0)
        # 限值 0 时任何 >0 的 desense 都判负（边界语义 ≤ 判过）
        assert b_tight["desense_ok"] == (b_tight["desense_db"] <= 0.0)

    def test_if_resolution_guard(self):
        with pytest.raises(ValueError, match="IF"):
            blocking_budget(STAGES_RX, 1e4, -30.0, 2.4e9, 2.1e9, -100.0)

    def test_rejection_negative_rejected(self):
        with pytest.raises(ValueError, match=">=0"):
            self._budget(filter_rejection_db=-1.0)


# ─── 注册键 service 出口往返（三件逐键）─────────────────────────────────────


class TestRegisteredKeys:
    def test_iq_imbalance_irr_roundtrip(self):
        out = run_calculator("iq_imbalance_irr",
                             {"amp_imbalance_db": 0.5,
                              "phase_imbalance_deg": 3.0})
        assert out["ok"] is True, out.get("error")
        json.dumps(out, allow_nan=False)
        assert out["result"]["irr_db"] == pytest.approx(28.199699722224715,
                                                        rel=1e-12)

    def test_phase_noise_evm_roundtrip(self):
        out = run_calculator("phase_noise_evm", {
            "f_edges": [1e3, 1e6, 1e7],
            "l_dbc": [-80.0, -95.0, -110.0]})
        assert out["ok"] is True, out.get("error")
        json.dumps(out, allow_nan=False)
        # dB 线性插值口径抽查：恒等式 evm_db=20log10(evm_rms)
        res = out["result"]
        assert res["evm_db"] == pytest.approx(
            20.0 * math.log10(res["evm_rms"]), rel=1e-12)

    def test_blocking_budget_roundtrip(self):
        out = run_calculator("blocking_budget", {
            "stages": STAGES_RX, "bw_hz": 1e4, "blocker_dbm": -40.0,
            "f_blocker_hz": 2.45e9, "f_rx_hz": 2.4e9, "f_lo_hz": 2.1e9,
            "filter_rejection_db": 20.0, "lo_phase_noise_dbc_hz": -110.0})
        assert out["ok"] is True, out.get("error")
        json.dumps(out, allow_nan=False)

    def test_invalid_inputs_ok_false(self):
        out = run_calculator("iq_imbalance_irr",
                             {"amp_imbalance_db": 0.5,
                              "phase_imbalance_deg": 200.0})
        assert out["ok"] is False and out.get("error")
        out2 = run_calculator("phase_noise_evm",
                              {"f_edges": [1e6, 1e3],
                               "l_dbc": [-90.0, -100.0]})
        assert out2["ok"] is False and out2.get("error")
        out3 = run_calculator("blocking_budget", {
            "stages": STAGES_RX, "bw_hz": 0.0, "blocker_dbm": -40.0,
            "f_blocker_hz": 2.45e9, "f_lo_hz": 2.1e9,
            "lo_phase_noise_dbc_hz": -110.0})
        assert out3["ok"] is False and out3.get("error")
