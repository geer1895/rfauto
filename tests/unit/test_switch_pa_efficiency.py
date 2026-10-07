"""core/switch_pa_efficiency.py 单测（MT-6）。

判据（#118 双路径：闭式 vs 独立数值路径，不自证）：
- 导通角族：闭式 vs 余弦脉冲数值积分（梯形）逐位一致 + A/B/C 经典锚；
- Class D：能量平衡数值闭合 + 基波功率闭式；
- Class E：理想电路 ODE 打靶独立定值 vs Raab 闭式（五常数）；
- Class F：谷点双零/最平坦条件的波形数值核 + 方波极限；
- 谐波梯：方波 DFT 独立锚 + dBc 经典值；EVM 量化地板闭式与守卫。
"""

from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.switch_pa_efficiency import (
    class_d_efficiency,
    class_e_optimum,
    class_f_point,
    conduction_angle_efficiency,
    conduction_angle_relative_power,
    square_wave_harmonic_ladder,
    supply_quantization_evm,
)

# ─── 导通角族（A/AB/B/C） ────────────────────────────────────────────────

class TestConductionAngle:
    def test_classic_anchors(self):
        assert conduction_angle_efficiency(math.pi) == 0.5  # A 类逐位
        assert abs(conduction_angle_efficiency(math.pi / 2)
                   - math.pi / 4) < 1e-15  # B 类 = π/4
        # C 类极限 α→0 → η→1（小步长收敛，#118 数值锚）
        for alpha in (1e-2, 1e-3, 1e-4):
            assert conduction_angle_efficiency(alpha) > 1.0 - alpha

    def test_closed_form_vs_numeric_integration(self):
        """闭式 vs 余弦脉冲 i(θ)=max(cosθ−cosα,0) 数值积分（独立路径）。"""
        th = np.linspace(0.0, 2.0 * np.pi, 2_000_001)
        for alpha in (math.pi, 2.0 * math.pi / 3, math.pi / 2,
                      math.pi / 3, 0.35):
            current = np.maximum(np.cos(th) - math.cos(alpha), 0.0)
            i_dc = float(np.trapezoid(current, th)) / (2.0 * np.pi)
            i_1 = (float(np.trapezoid(current * np.cos(th), th)) * 2.0
                   / (2.0 * np.pi))
            eta_num = 0.5 * i_1 / i_dc  # 满摆幅 V1=Vdc 口径
            eta_closed = conduction_angle_efficiency(alpha)
            assert abs(eta_num - eta_closed) < 1e-8

    def test_relative_power(self):
        assert abs(conduction_angle_relative_power(math.pi / 2) - 1.0) < 1e-15
        # A 类 I1/I1B = π/(π/2) = 2 → P 比 = I1² 比 = 4（P ∝ I1²）
        assert abs(conduction_angle_relative_power(math.pi) - 4.0) < 1e-15

    def test_guards(self):
        for bad in (0.0, -0.1, math.pi + 0.1, float("nan")):
            try:
                conduction_angle_efficiency(bad)
            except ValueError:
                continue
            raise AssertionError(f"alpha={bad!r} 应报 ValueError")


# ─── Class D ─────────────────────────────────────────────────────────────

class TestClassD:
    def test_ideal_lossless(self):
        for bridge in ("half", "full"):
            r = class_d_efficiency(50.0, 0.0, bridge=bridge, vcc_v=28.0)
            assert r.efficiency == 1.0

    def test_closed_form_power_and_energy_balance(self):
        """P1 闭式逐位 + 能量守恒数值闭合（瞬时损耗数值平均）。"""
        vcc, r_l, r_on = 28.0, 50.0, 1.5
        th = np.linspace(0.0, 2.0 * np.pi, 1_000_001, endpoint=False)
        for bridge, n_r, v1 in (("half", 1, 2 * vcc / math.pi),
                                ("full", 2, 4 * vcc / math.pi)):
            r = class_d_efficiency(r_l, r_on, bridge=bridge, vcc_v=vcc)
            assert abs(r.fundamental_peak_v - v1) < 1e-15
            assert abs(r.p_fund_w - v1 * v1 / (2.0 * r_l)) < 1e-12
            i_pk = v1 / r_l
            current = i_pk * np.sin(th)
            # 瞬时导通损耗 = n_r·r_on·i²，数值平均 vs 闭式
            p_loss_num = float(np.trapezoid(
                n_r * r_on * current**2, th)) / (2.0 * np.pi)
            assert abs(p_loss_num - r.p_loss_w) < 1e-9
            # η = P1/(P1+P_loss) = R/(R+n_r·r)
            assert abs(r.efficiency - r_l / (r_l + n_r * r_on)) < 1e-15

    def test_bridge_guard(self):
        try:
            class_d_efficiency(50.0, 0.1, bridge="pushpull")
        except ValueError:
            return
        raise AssertionError("非法 bridge 应报 ValueError")


# ─── Class E：ODE 打靶独立定值（#118 裁判路径） ──────────────────────────

def _solve_class_e_shooting():
    """理想 Class E（Sokal 拓扑）50% 占空比打靶解。

    状态方程（OFF 半周 θ∈[0,π]，v 归一 Vcc=1、I_dc=1）：
        dx/dθ = κ·(1 − ρ·cos(θ+ψ))，
    约束：x(π)=0（ZVS）、x'(π)=0（ZdVS）、⟨v⟩=1（扼流圈伏秒平衡）。
    三未知数 (κ,ρ,ψ) 三约束——独立于 Raab 闭式的数值裁判。
    """
    from scipy.optimize import fsolve

    def integrate(p):
        kappa, rho, psi = p
        n = 20001
        th = np.linspace(0.0, math.pi, n)
        dx = kappa * (1.0 - rho * np.cos(th + psi))
        x = np.concatenate(
            [[0.0], np.cumsum((dx[1:] + dx[:-1]) * 0.5 * np.diff(th))])
        return th, x, dx

    def residual(p):
        th, x, dx = integrate(p)
        avg_v = np.trapezoid(x, th) / (2.0 * math.pi)
        return [x[-1], dx[-1], avg_v - 1.0]

    sol, _info, ier, msg = fsolve(residual, [2.0, 2.0, 0.5],
                                  full_output=True, xtol=1e-13)
    assert ier == 1, f"打靶未收敛: {msg}"
    th, x, _dx = integrate(sol)
    kappa, rho, psi = sol
    assert max(abs(v) for v in residual(sol)) < 1e-8

    # 全周期基波（峰值相量）：ON 半周 v=0
    xf = np.concatenate([x, np.zeros_like(th)])
    thf = np.concatenate([th, th + math.pi])
    c1 = np.trapezoid(xf * np.exp(-1j * thf), thf) / math.pi
    v1 = abs(c1)
    phi_total = math.atan2(c1.imag, c1.real) - psi
    # 能量平衡（Vcc=1, I_dc=1）：P = 0.5·V1·I1·cos(φ) 必须恰为 1
    p_balance = 0.5 * v1 * rho * math.cos(phi_total)
    r_opt = 2.0 * p_balance / rho**2          # P = I1_rms²·R
    omega_c_r = r_opt / kappa                 # ωC = I_dc/(κ·Vcc)
    x_over_r = math.tan(phi_total)
    v_max = float(x.max())
    th_on = np.linspace(math.pi, 2.0 * math.pi, 20001)
    i_sw_max = 1.0 - rho * float(np.cos(th_on + psi).min())  # max(1−ρcos)
    return {
        "p_balance": p_balance, "r_opt": r_opt, "omega_c_r": omega_c_r,
        "x_over_r": x_over_r, "v_max": v_max, "i_max": float(i_sw_max),
        "phi_deg": math.degrees(math.atan(x_over_r)),
    }


class TestClassE:
    def test_raab_constants_vs_independent_shooting(self):
        """Raab 闭式五常数 vs 理想电路打靶解（独立数值裁判，rel 1e-3 级）。"""
        num = _solve_class_e_shooting()
        opt = class_e_optimum(13.56e6, 28.0, 30.0)
        # 能量平衡自洽（打靶解内禀校验）
        assert abs(num["p_balance"] - 1.0) < 1e-8
        # R 恒等：打靶解 Vcc=1、P=1 → R 即 8/(π²+4)
        assert abs(num["r_opt"] - 8.0 / (math.pi**2 + 4.0)) < 1e-6
        assert abs(num["omega_c_r"]
                   - 8.0 / (math.pi * (math.pi**2 + 4.0))) < 1e-6
        assert abs(num["x_over_r"]
                   - math.pi * (math.pi**2 - 4.0) / 16.0) < 1e-6
        assert abs(num["phi_deg"] - opt.phi_deg) < 1e-4
        assert abs(num["v_max"] - 3.562) < 3.6e-3
        assert abs(num["i_max"] - 2.862) < 2.9e-3

    def test_optimum_identities(self):
        opt = class_e_optimum(13.56e6, 28.0, 30.0)
        # R_opt = 0.576801·Vcc²/P 逐位（闭式）
        assert abs(opt.r_opt_ohm
                   - 8.0 / (math.pi**2 + 4.0) * 28.0**2 / 30.0) < 1e-9
        # ωC·R = 0.18360 恒等
        omega = 2.0 * math.pi * opt.f_hz
        assert abs(omega * opt.c_shunt_f * opt.r_opt_ohm
                   - 8.0 / (math.pi * (math.pi**2 + 4.0))) < 1e-12
        # 应力锚 + 理想效率
        assert abs(opt.v_switch_peak_v - 3.562 * 28.0) < 1e-9
        assert abs(opt.i_switch_peak_a - 2.862 * (30.0 / 28.0)) < 1e-9
        assert opt.eta_ideal == 1.0
        d = opt.to_dict()
        assert d["eta_ideal"] == 1.0 and "UNVERIFIED" in d["provenance"]

    def test_guards(self):
        for args in ((0.0, 28.0, 30.0), (13.56e6, -1.0, 30.0),
                     (13.56e6, 28.0, 0.0)):
            try:
                class_e_optimum(*args)
            except ValueError:
                continue
            raise AssertionError(f"args={args!r} 应报 ValueError")


# ─── Class F ─────────────────────────────────────────────────────────────

class TestClassF:
    @staticmethod
    def _waveform_min(a, b, c=0.0):
        th = np.linspace(0.0, 2.0 * np.pi, 400_001, endpoint=False)
        v = 1.0 + a * np.sin(th) + b * np.sin(3.0 * th) + c * np.sin(5.0 * th)
        return float(v.min()), th[np.argmin(v)]

    def test_f3_optimum(self):
        """a=2/√3、b=1/(3√3)：谷点双零在 θ₀=5π/3，η=π/(2√3)。"""
        pt = class_f_point("f3_optimum")
        assert abs(pt.v1_over_vdc - 2.0 / math.sqrt(3.0)) < 1e-15
        assert abs(pt.b_sin3 - 1.0 / (3.0 * math.sqrt(3.0))) < 1e-15
        assert abs(pt.efficiency - math.pi / (2.0 * math.sqrt(3.0))) < 1e-15
        vmin, th_min = self._waveform_min(pt.v1_over_vdc, pt.b_sin3)
        assert abs(vmin) < 1e-9                     # 触零（无越限）
        assert abs(th_min - 5.0 * math.pi / 3.0) < 1e-3  # 谷点位置
        # a 再大即越限（最佳性数值核）
        vmin_over, _ = self._waveform_min(pt.v1_over_vdc * 1.001, pt.b_sin3)
        assert vmin_over < 0.0

    def test_f3_flat(self):
        pt = class_f_point("f3_flat")
        assert abs(pt.v1_over_vdc - 9.0 / 8.0) < 1e-15
        assert abs(pt.efficiency - math.pi / 4.0 * 9.0 / 8.0) < 1e-15
        vmin, _ = self._waveform_min(pt.v1_over_vdc, pt.b_sin3)
        assert abs(vmin) < 1e-9
        # 最平坦：v''(π/2) = −a − 9b·(−1)·? 数值二阶差分核 v''(π/2)=0
        h = 1e-4

        def flat_v(t: float) -> float:
            return (1.0 + pt.v1_over_vdc * math.sin(t)
                    + pt.b_sin3 * math.sin(3.0 * t))

        d2 = (flat_v(math.pi / 2 + h) - 2.0 * flat_v(math.pi / 2)
              + flat_v(math.pi / 2 - h)) / (h * h)
        assert abs(d2) < 1e-6

    def test_f5_flat_and_square_limit(self):
        pt = class_f_point("f5_flat")
        assert abs(pt.v1_over_vdc - 75.0 / 64.0) < 1e-15
        vmin, _ = self._waveform_min(pt.v1_over_vdc, pt.b_sin3, pt.c_sin5)
        assert abs(vmin) < 1e-9
        # 方波极限恒等：a=4/π → η=(π/4)(4/π)=1 逐位
        assert math.pi / 4.0 * (4.0 / math.pi) == 1.0
        d = pt.to_dict()
        assert d["mode"] == "f5_flat"

    def test_mode_guard(self):
        try:
            class_f_point("f7")
        except ValueError:
            return
        raise AssertionError("非法 mode 应报 ValueError")


# ─── 谐波梯 + EVM 寄生面 ─────────────────────────────────────────────────

class TestHarmonicsAndEvm:
    def test_ladder_vs_square_wave_fft(self):
        """dBc 经典值 + 独立 DFT 锚（整数周期方波，零泄漏）。"""
        lad = square_wave_harmonic_ladder(15)
        classic = {3: -9.5424, 5: -13.9794, 7: -16.902}
        for h in lad["harmonics"][:3]:
            assert abs(h["dbc"] - classic[h["n"]]) < 1e-4
        # 独立 DFT：±1 方波奇次谐波/基波 = 1/n
        n = 4096
        t = np.arange(n) / n
        sq = np.sign(np.sin(2.0 * math.pi * t))
        spec = np.abs(np.fft.rfft(sq)) * 2.0 / n
        for k in (1, 3, 5, 7, 9):
            amp = spec[k]
            # 1e-5：sign 零跨界采样（k=n/2 处 sin≈−ε）残留谱噪声地板
            assert abs(amp / spec[1] - 1.0 / k) < 1e-5
        # 奇次总功率比 = π²/8 − 1（Parseval 闭式 vs 直求和+尾界）
        # 尾界：Σ_{odd k>999} 1/k² < ∫_999^∞ dx/x² = 1/999 < 1.1e-3
        direct = sum(1.0 / (k * k) for k in range(3, 1000, 2))
        assert direct < lad["harmonic_power_over_fund"] < direct + 1.1e-3

    def test_evm_quantization_floor(self):
        r = supply_quantization_evm(9, 8.0, 1.0)
        assert abs(r["step_v"] - 1.0) < 1e-15
        assert abs(r["evm_rms"] - 1.0 / math.sqrt(12.0)) < 1e-12
        # 电平数↑ → 地板↓（单调）
        evms = [supply_quantization_evm(n, 8.0, 1.0)["evm_rms"]
                for n in (2, 3, 5, 9, 17)]
        assert all(x > y for x, y in itertools.pairwise(evms))
        # Δ²/12 统计闭式的数值积分锚（均匀误差分布方差）
        step = supply_quantization_evm(3, 2.0, 1.0)["step_v"]
        e = np.linspace(-step / 2, step / 2, 1_000_001)
        var = float(np.trapezoid(e**2, e)) / step
        assert abs(var - step**2 / 12.0) < 1e-12

    def test_evm_guards(self):
        for args in ((1, 8.0, 1.0), (0, 8.0, 1.0), (9, 0.0, 1.0),
                     (9, 8.0, 0.0)):
            try:
                supply_quantization_evm(*args)
            except ValueError:
                continue
            raise AssertionError(f"args={args!r} 应报 ValueError")
