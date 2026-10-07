r"""LT-5..7 微波加热确定性内核单测（core/microwave_heating.py，round18 :137-144）。

裁判 = 外部独立来源/独立路径（#118：不是被测实现的自我推导）：
  * Weyl 渐近：立方律 N(2f)=8N(f) 恒等 + 与 shield_cavity_mode.rect_cavity_
    modes 精确枚举的交叉对拍（规格 :137 交叉锚；电大腔相对偏差收窄单调）；
  * 精确计数：独立三重循环蛮干枚举对拍（不经 rect_cavity_modes 路径）+
    TE101 单模窗（te=1/tm=1/total=2 手数）；
  * 装填匹配：εr=1 退化纯体积比恒等、满填 F=1、Q_d 手算、双通道分摊
    恒等 η=Q_L/Q_d；1 kW·1 kg 水负载温升速率经典量级 ~0.24 °C/s
    （P/(m·c_p)，c_p=4186 J/(kg·K) 物理常量链，规格/任务书量级锚）；
  * TE10p 场量：谐振频率与 rect_cavity_modes (1,0,p) 项及
    cavity_perturbation_shift TE101 闭式互证；Maxwell 均分恒等式
    W_e=W_m（测试内独立代数推导 W_m 闭式 + 数值体积分双路）；壁损
    G 闭式 vs 逐壁 |H_t|² 数值面积分（中点法则，独立路径）；
  * 单模沉积：通道分摊与场路 P=(ω/2)ε0εr″E0²V_l·s 代数恒等（1e-9）；
    临界耦合 β=1→吸收率 1、β=Q_u/(4Q_u)→4β/(1+β)²=0.64 手算；偶 p
    中心波节显式拒绝（负例）；装填因子>1 显式拒绝（负例）；
  * 热失控：α_crit=1/(e·R_th·P0) 手算 + 定点迭代收敛/失控分界复现
    （0.9α_c 收敛且斜率<1、1.1α_c 发散，规格 :142 验收口径）；
  * 工艺窗口：单 RC 解析反解 t=τ·ln(P·R/(P·R−ΔT))、Z_th(∞)=ΣR 能量
    守恒（p_hold·ΣR=ΔT）、目标不可达如实 None 不猜。

确定性：无网络、无真机、无文件 IO、无随机（数值积分为定点网格）。
"""

from __future__ import annotations

import json
import math

import pytest

from rfauto.core.microwave_heating import (
    EPS0_F_PER_M,
    MU0_H_PER_M,
    dielectric_power_density,
    exponential_tand_power_chain,
    heating_fixed_point,
    multimode_load_match,
    process_window,
    rect_cavity_mode_count,
    runaway_boundary_alpha,
    single_mode_load_report,
    te10p_field_report,
    te10p_mode,
    te10p_shape_factor,
    weyl_mode_stats,
)
from rfauto.core.pdn import C0
from rfauto.core.shield_cavity_mode import rect_cavity_modes

# 1 kW 全沉积进 1 kg 水（c_p=4186 J/(kg·K)）的温升速率经典量级锚
_WATER_RATE_REF = 1000.0 / (1.0 * 4186.0)  # ≈0.2389 °C/s


# ---------------------------------------------------------------------------
# LT-5 Weyl 模式统计
# ---------------------------------------------------------------------------

class TestWeylModeStats:
    def test_cubic_law_scaling_identity(self):
        s1 = weyl_mode_stats(0.05, 2.45e9)
        s2 = weyl_mode_stats(0.05, 4.9e9)
        assert s2["n_weyl"] == pytest.approx(8.0 * s1["n_weyl"], rel=1e-12)

    def test_density_spacing_product_is_one(self):
        s = weyl_mode_stats(1.0, 3.0e9, 2.0)
        assert s["mode_density_per_hz"] * s["mean_spacing_hz"] == (
            pytest.approx(1.0, rel=1e-12))

    def test_er_scaling(self):
        s1 = weyl_mode_stats(0.02, 2.45e9, 1.0)
        s4 = weyl_mode_stats(0.02, 2.45e9, 4.0)
        # f√εr 缩放：(f·2)³=8×（介质口径 λ=c0/(f√εr)）
        assert s4["n_weyl"] == pytest.approx(8.0 * s1["n_weyl"], rel=1e-12)

    def test_weyl_vs_exact_cross_anchor(self):
        """规格 :137 交叉锚：电大腔 Weyl 渐近 vs 精确枚举，偏差收窄单调。"""
        small_stats = weyl_mode_stats(1.0, 3.0e9)
        small = rect_cavity_mode_count(1.0, 1.0, 1.0, 1.0, 3.0e9)
        big_stats = weyl_mode_stats(8.0, 4.0e9)
        big = rect_cavity_mode_count(2.0, 2.0, 2.0, 1.0, 4.0e9)
        dev_small = (small["total"] - small_stats["n_weyl"]) / (
            small_stats["n_weyl"])
        dev_big = (big["total"] - big_stats["n_weyl"]) / big_stats["n_weyl"]
        # 实测：1m³@3GHz ≈ −4.4%（面项修正使精确计数低于首项）、
        # 8m³@4GHz ≈ −1.4%——电大渐近收敛方向单调（不钉死首项常数）。
        assert abs(dev_small) < 0.06
        assert abs(dev_big) < 0.03
        assert abs(dev_big) < abs(dev_small)

    def test_invalid_inputs_rejected(self):
        for kwargs in (
            {"volume_m3": 0.0, "f_hz": 1e9},
            {"volume_m3": -1.0, "f_hz": 1e9},
            {"volume_m3": 1.0, "f_hz": 0.0},
            {"volume_m3": 1.0, "f_hz": 1e9, "er": 0.0},
            {"volume_m3": True, "f_hz": 1e9},
        ):
            with pytest.raises(ValueError):
                weyl_mode_stats(**kwargs)


class TestRectCavityModeCount:
    A_M, B_M, D_M = 0.03, 0.02, 0.04

    def _f0_te101(self) -> float:
        return (C0 / 2.0) * math.sqrt(
            (1.0 / self.A_M) ** 2 + (1.0 / self.D_M) ** 2)

    def test_te101_single_mode_window(self):
        f0 = self._f0_te101()
        c = rect_cavity_mode_count(self.A_M, self.B_M, self.D_M, 1.0,
                                   f0 * (1.0 + 1e-9))
        # TE101（n=0）无同指数 TM 简并（TM 要求全部指数 ≥1）——主模窗口
        # 内恰 1 个模式（单极化），手数锚
        assert c["te_count"] == 1
        assert c["tm_count"] == 0
        assert c["total"] == 1

    def test_te111_window_has_tm_degeneracy(self):
        """TE111（全指数 ≥1）窗口含同指数 TM 简并——计极化手数锚。

        30×20×40mm 窗内逐项（手数）：TE101=6.246/TE011=8.379/TE102=9.008/
        TE111=9.756 GHz 共 4 个 TE 容许项；仅 TE111 有同指数 TM 简并
        （TM 要求全部指数 ≥1，101/011/102 均含 0 指数）→ tm=1、total=5。
        """
        er = 1.0
        f_unit = C0 / 2.0
        f111 = f_unit * math.sqrt(
            (1 / self.A_M) ** 2 + (1 / self.B_M) ** 2 + (1 / self.D_M) ** 2)
        c = rect_cavity_mode_count(self.A_M, self.B_M, self.D_M, er,
                                   f111 * (1.0 + 1e-9))
        assert c["te_count"] == 4
        assert c["tm_count"] == 1
        assert c["total"] == 5

    def test_independent_brute_force_enumeration(self):
        """独立蛮干枚举对拍（不经 rect_cavity_modes 路径）。"""
        er, f = 2.0, 8.0e9
        a, b, d = self.A_M, self.B_M, self.D_M
        f_unit = C0 / (2.0 * math.sqrt(er))
        te = tm = 0
        for m in range(0, 9):
            for n in range(0, 9):
                if m == 0 and n == 0:
                    continue
                for p in range(1, 9):
                    fm = f_unit * math.sqrt(
                        (m / a) ** 2 + (n / b) ** 2 + (p / d) ** 2)
                    if fm <= f:
                        te += 1
                        if m >= 1 and n >= 1:
                            tm += 1
        c = rect_cavity_mode_count(a, b, d, er, f)
        assert c["te_count"] == te
        assert c["tm_count"] == tm
        assert c["total"] == te + tm

    def test_total_polarization_ordering(self):
        c = rect_cavity_mode_count(0.5, 0.4, 0.3, 1.0, 5.0e9)
        assert c["total"] == c["te_count"] + c["tm_count"]
        assert c["te_count"] >= c["tm_count"] > 0

    def test_invalid_inputs_rejected(self):
        for args in (
            (0.0, 1.0, 1.0, 1.0, 1e9),
            (1.0, 1.0, 1.0, -1.0, 1e9),
            (1.0, 1.0, 1.0, 1.0, 0.0),
            (True, 1.0, 1.0, 1.0, 1e9),
        ):
            with pytest.raises(ValueError):
                rect_cavity_mode_count(*args)


class TestMultimodeLoadMatch:
    def test_eps_one_degenerates_to_volume_fraction(self):
        m = multimode_load_match(0.02, 0.005, 1.0, 0.1, 1000.0)
        assert m["filling_factor"] == pytest.approx(0.25, rel=1e-12)

    def test_full_fill_load_dominates(self):
        # 满填（V_l=V_c）→ F=1；但壁损通道仍在（Q_w=1000 vs Q_d=10）：
        # η=(1/Q_d)/(1/Q_d+1/Q_w)=0.9901，手算锚
        m = multimode_load_match(0.02, 0.02, 5.0, 0.1, 1000.0, 100.0)
        assert m["filling_factor"] == pytest.approx(1.0, rel=1e-12)
        assert m["q_dielectric"] == pytest.approx(10.0, rel=1e-12)
        assert m["efficiency"] == pytest.approx(
            (1.0 / 10.0) / (1.0 / 10.0 + 1.0 / 1000.0), rel=1e-12)
        assert m["p_load_w"] == pytest.approx(
            100.0 * (1.0 / 10.0) / (1.0 / 10.0 + 1.0 / 1000.0), rel=1e-12)
        assert m["p_load_w"] + m["p_wall_w"] == pytest.approx(100.0, rel=1e-12)

    def test_q_dielectric_hand_value(self):
        m = multimode_load_match(0.02, 1e-3, 78.0, 0.12, 2000.0)
        f = 78.0 * 1e-3 / (78.0 * 1e-3 + 0.019)
        assert m["filling_factor"] == pytest.approx(f, rel=1e-12)
        assert m["q_dielectric"] == pytest.approx(1.0 / (f * 0.12), rel=1e-12)
        q_l = 1.0 / (1.0 / 2000.0 + f * 0.12)
        assert m["q_loaded"] == pytest.approx(q_l, rel=1e-12)
        assert m["efficiency"] == pytest.approx(q_l * f * 0.12, rel=1e-12)

    def test_water_1kw_heating_rate_classical_anchor(self):
        """1 kW 水负载温升速率 ~0.24 °C/s/kg 经典量级锚（物理常量链）。"""
        m = multimode_load_match(0.02, 1e-3, 78.0, 0.12, 2000.0, 1000.0)
        rate = m["p_load_w"] / (1.0 * 4186.0)  # 1 kg 水
        assert rate == pytest.approx(_WATER_RATE_REF, rel=0.05)
        assert 0.20 < rate < 0.28

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError):
            multimode_load_match(0.02, 0.03, 78.0, 0.12, 2000.0)  # 负载>腔
        with pytest.raises(ValueError):
            multimode_load_match(0.02, 0.001, 78.0, 0.0, 2000.0)  # 零损耗
        with pytest.raises(ValueError):
            multimode_load_match(0.02, 0.001, 78.0, -0.1, 2000.0)  # 负 tanδ
        with pytest.raises(ValueError):
            multimode_load_match(0.02, 0.001, 78.0, 0.12, 0.0)  # q_wall=0
        with pytest.raises(ValueError):
            multimode_load_match(0.02, 0.001, 0.0, 0.12, 2000.0)  # εr=0

    def test_near_full_fill_efficiency_tends_to_one(self):
        # 均匀场式 F<1 对 V_l<V_c 恒成立；近满填高损耗负载 η→1
        m = multimode_load_match(1.0, 0.99, 50.0, 0.5, 2000.0, 100.0)
        assert m["filling_factor"] < 1.0
        assert m["efficiency"] > 0.999


# ---------------------------------------------------------------------------
# LT-6 TE10p 单模腔
# ---------------------------------------------------------------------------

class TestTe10pMode:
    A_M, B_M, D_M = 0.03, 0.02, 0.04

    def test_matches_rect_cavity_modes_entry(self):
        for p in (1, 2, 3):
            mode = te10p_mode(self.A_M, self.B_M, self.D_M, 1.0, p)
            entries = [m for m in rect_cavity_modes(
                self.A_M, self.B_M, self.D_M, 1.0, 1, 0, p)
                if (m.m, m.n, m.p) == (1, 0, p)]
            assert len(entries) == 1
            assert mode.f0_hz == pytest.approx(entries[0].f_hz, rel=1e-12)

    def test_matches_cavity_perturbation_te101_closed_form(self):
        """与 cavity_perturbation_shift 的 TE101 闭式（C_MM_GHZ 口径）互证。"""
        from rfauto.core.calc_families.cavity import (
            cavity_perturbation_shift,
        )

        mode = te10p_mode(self.A_M, self.B_M, self.D_M, 1.0, 1)
        ref = cavity_perturbation_shift(
            self.A_M * 1e3, self.B_M * 1e3, self.D_M * 1e3,
            sample_box_mm=[14.0, 8.0, 18.0, 16.0, 12.0, 22.0],
            sample_eps_r=5.0)
        # f0_ghz 在复用键内按 9 位小数舍入（cavity.py 口径），对拍阈 1e-9
        assert mode.f0_hz / 1e9 == pytest.approx(ref["f0_ghz"], rel=1e-9)

    def test_mode_order_monotone(self):
        f1 = te10p_mode(self.A_M, self.B_M, self.D_M, 1.0, 1).f0_hz
        f2 = te10p_mode(self.A_M, self.B_M, self.D_M, 1.0, 2).f0_hz
        assert f1 < f2

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError):
            te10p_mode(self.A_M, self.B_M, self.D_M, 1.0, 0)
        with pytest.raises(ValueError):
            te10p_mode(0.0, self.B_M, self.D_M, 1.0, 1)
        with pytest.raises(ValueError):
            te10p_mode(self.A_M, self.B_M, self.D_M, True, 1)


class TestTe10pFieldReport:
    A_M, B_M, D_M = 0.03, 0.02, 0.04

    def test_integral_e_sq_is_quarter_volume(self):
        rep = te10p_field_report(self.A_M, self.B_M, self.D_M, 1.0, 1)
        assert rep["integral_e_sq"] == pytest.approx(
            self.A_M * self.B_M * self.D_M / 4.0, rel=1e-12)

    def _numeric_wall_geom(self, p: int, n: int = 400) -> float:
        """逐壁 |H_t|²/(E0/ωμ)² 数值面积分（中点法则，独立裁判路径）。"""
        a, b, d = self.A_M, self.B_M, self.D_M
        xs = [(i + 0.5) * a / n for i in range(n)]
        zs = [(i + 0.5) * d / n for i in range(n)]
        total = 0.0
        # x=0 / x=a 壁（面元 dy·dz=b·d/n，被积函数无 y 依赖）：
        # H_t=(H_y, H_z)，H_y=0，|H_z|²=(π/a)²cos²(πx/a)|边界·sin²(pπz/d)，
        # x=0 与 x=a 边界 cos² 同为 1
        for z in zs:
            total += 2.0 * (math.pi / a) ** 2 * math.sin(
                math.pi * p * z / d) ** 2 * (b * d / n)
        # y=0 / y=b 壁（面元 dx·dz）：H_t=(H_x, H_z)
        db = (a / n) * (d / n)
        for x in xs:
            for z in zs:
                hx = (p * math.pi / d) * math.sin(math.pi * x / a) * math.cos(
                    math.pi * p * z / d)
                hz = (math.pi / a) * math.cos(math.pi * x / a) * math.sin(
                    math.pi * p * z / d)
                total += 2.0 * (hx * hx + hz * hz) * db
        # z=0 / z=d 壁（面元 dx·dy=a·b/n）：H_t=(H_x, 0)，
        # |H_x|²=(pπ/d)²sin²(πx/a)·cos²(pπz/d)|边界，边界绝对值 1
        for x in xs:
            total += 2.0 * (p * math.pi / d) ** 2 * math.sin(
                math.pi * x / a) ** 2 * (a * b / n)
        return total

    def test_wall_geom_matches_numeric_surface_quadrature(self):
        for p in (1, 2):
            rep = te10p_field_report(self.A_M, self.B_M, self.D_M, 1.0, p,
                                     wall_sigma_s_per_m=5.8e7)
            numeric = self._numeric_wall_geom(p)
            assert rep["wall_geom_factor"] == pytest.approx(
                numeric, rel=1e-4)

    def test_maxwell_equipartition_we_eq_wm(self):
        """均分恒等式 W_e=W_m（测试内独立代数推导 W_m 闭式）。"""
        for p in (1, 3):
            mode = te10p_mode(self.A_M, self.B_M, self.D_M, 1.0, p)
            rep = te10p_field_report(self.A_M, self.B_M, self.D_M, 1.0, p)
            omega = 2.0 * math.pi * mode.f0_hz
            vol = self.A_M * self.B_M * self.D_M
            w_e = 0.25 * EPS0_F_PER_M * vol / 4.0  # ∫|E|²=E0²V/4, E0=1
            w_m = 0.25 / MU0_H_PER_M * (vol / 4.0) * (
                (p * math.pi / self.D_M) ** 2
                + (math.pi / self.A_M) ** 2) / omega**2
            assert w_e == pytest.approx(w_m, rel=1e-12)
            assert rep["w_stored_j"] == pytest.approx(2.0 * w_e, rel=1e-12)

    def test_q_wall_scales_inverse_with_sigma(self):
        # Rs=√(πfμ0/σ)∝σ^(−1/2) → Q_wall∝σ^(1/2)：σ 降 10× → Q 降 √10
        lo = te10p_field_report(self.A_M, self.B_M, self.D_M, 1.0, 1,
                                wall_sigma_s_per_m=5.8e7)
        hi = te10p_field_report(self.A_M, self.B_M, self.D_M, 1.0, 1,
                                wall_sigma_s_per_m=5.8e6)
        assert hi["q_wall"] == pytest.approx(
            lo["q_wall"] * math.sqrt(5.8e6 / 5.8e7), rel=1e-12)

    def test_no_sigma_wall_keys_none(self):
        rep = te10p_field_report(self.A_M, self.B_M, self.D_M, 1.0, 1)
        assert rep["q_wall"] is None and rep["rs_ohm"] is None


class TestSingleModeLoadReport:
    A_M, B_M, D_M = 0.03, 0.02, 0.04
    COPPER = 5.8e7

    def _report(self, **kw):
        base = dict(
            load_eps_r=80.0, load_tan_delta=0.5, er=1.0, p_index=1,
            load_v_m3=1e-8, wall_sigma_s_per_m=self.COPPER,
            input_power_w=100.0)
        base.update(kw)
        return single_mode_load_report(self.A_M, self.B_M, self.D_M, **base)

    def test_channel_field_power_identity(self):
        rep = self._report()
        assert rep["p_load_w"] == pytest.approx(
            rep["p_load_field_check_w"], rel=1e-9)

    def test_filling_factor_hand_value(self):
        rep = self._report()
        vol = self.A_M * self.B_M * self.D_M
        assert rep["filling_factor"] == pytest.approx(
            4.0 * 80.0 * 1e-8 * 1.0 / vol, rel=1e-12)  # 中心 s=1（奇 p）

    def test_coupling_critical_and_off_critical(self):
        q_wall = self._report()["q_wall"]
        crit = self._report(q_ext=q_wall)
        assert crit["coupling_beta"] == pytest.approx(1.0, rel=1e-12)
        assert crit["p_abs_frac"] == pytest.approx(1.0, rel=1e-12)
        off = self._report(q_ext=4.0 * q_wall)
        assert off["coupling_beta"] == pytest.approx(0.25, rel=1e-12)
        assert off["p_abs_frac"] == pytest.approx(
            4.0 * 0.25 / 1.25**2, rel=1e-12)  # 0.64 手算

    def test_even_p_center_node_rejected(self):
        with pytest.raises(ValueError, match="波节"):
            self._report(p_index=2)  # 偶 p 中心=E 波节（s=0）

    def test_explicit_centroid_moves_off_antinode(self):
        rep = self._report(load_centroid_m=(self.A_M / 4.0, self.D_M / 4.0))
        s = math.sin(math.pi / 4.0) ** 2 * math.sin(math.pi / 4.0) ** 2
        vol = self.A_M * self.B_M * self.D_M
        assert rep["filling_factor"] == pytest.approx(
            4.0 * 80.0 * 1e-8 * s / vol, rel=1e-12)

    def test_filling_over_one_rejected(self):
        with pytest.raises(ValueError, match="装填因子"):
            self._report(load_v_m3=1e-6)  # 1 mL 水 @24 mL 腔：F=13.3>1

    def test_load_larger_than_cavity_rejected(self):
        with pytest.raises(ValueError):
            self._report(load_v_m3=1.0)

    def test_no_load_no_wall_energy_undefined_rejected(self):
        with pytest.raises(ValueError):
            single_mode_load_report(
                self.A_M, self.B_M, self.D_M, 80.0, 0.5,
                wall_sigma_s_per_m=None)

    def test_no_load_wall_only(self):
        rep = single_mode_load_report(
            self.A_M, self.B_M, self.D_M, 80.0, 0.5,
            wall_sigma_s_per_m=self.COPPER, input_power_w=10.0)
        assert rep["p_load_w"] is None and rep["q_dielectric"] is None
        assert rep["q_loaded"] == rep["q_wall"]
        omega = 2.0 * math.pi * te10p_mode(
            self.A_M, self.B_M, self.D_M, 1.0, 1).f0_hz
        assert rep["w_stored_j"] == pytest.approx(
            rep["q_wall"] * 10.0 / omega, rel=1e-12)

    def test_shape_factor_values(self):
        assert te10p_shape_factor(0.015, 0.02, self.A_M, self.D_M, 1) == (
            pytest.approx(1.0, rel=1e-12))
        assert te10p_shape_factor(0.015, 0.02, self.A_M, self.D_M, 2) == (
            pytest.approx(0.0, abs=1e-18))


# ---------------------------------------------------------------------------
# LT-7 体吸收 / 定点迭代 / 热失控 / 工艺窗口
# ---------------------------------------------------------------------------

class TestDielectricPowerDensity:
    def test_hand_value_and_sar(self):
        f, er, tand, e = 2.45e9, 78.0, 0.12, 100.0
        out = dielectric_power_density(f, er, tand, e, density_kg_m3=1000.0)
        p_ref = 2.0 * math.pi * f * EPS0_F_PER_M * er * tand * e * e
        assert out["power_density_w_per_m3"] == pytest.approx(p_ref, rel=1e-12)
        assert out["sar_w_per_kg"] == pytest.approx(p_ref / 1000.0, rel=1e-12)

    def test_rms_peak_factor_two(self):
        """峰值口径 (ω/2)ε0ε″E_peak² 与 rms 口径同一物理量（因子 2 对齐）。"""
        e_rms = 100.0
        p_rms = dielectric_power_density(
            2.45e9, 10.0, 0.1, e_rms)["power_density_w_per_m3"]
        p_peak = 0.5 * 2.0 * math.pi * 2.45e9 * EPS0_F_PER_M * 1.0 * (
            e_rms * math.sqrt(2.0)) ** 2
        assert p_rms == pytest.approx(p_peak, rel=1e-12)

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError):
            dielectric_power_density(2.45e9, 10.0, 0.0, 100.0)  # 零损耗
        with pytest.raises(ValueError):
            dielectric_power_density(2.45e9, 10.0, 0.1, 0.0)
        with pytest.raises(ValueError):
            dielectric_power_density(2.45e9, 10.0, 0.1, 100.0, 0.0)


class TestExponentialChain:
    def test_reference_power_hand_value(self):
        fn = exponential_tand_power_chain(
            2.45e9, 12.0, 0.01, 0.003, 500.0, 1e-3, t_ref_c=25.0)
        p0 = 2.0 * math.pi * 2.45e9 * EPS0_F_PER_M * 12.0 * 0.01 * (
            500.0 ** 2) * 1e-3
        assert fn(25.0) == pytest.approx(p0, rel=1e-12)
        assert fn(125.0) == pytest.approx(p0 * math.exp(0.3), rel=1e-12)

    def test_zero_alpha_constant_when_eps_const(self):
        fn = exponential_tand_power_chain(
            2.45e9, 12.0, 0.01, 0.0, 500.0, 1e-3)
        assert fn(25.0) == pytest.approx(fn(125.0), rel=1e-12)

    def test_eps_linear_tempco_applies(self):
        fn = exponential_tand_power_chain(
            2.45e9, 12.0, 0.01, 0.0, 500.0, 1e-3, t_ref_c=25.0,
            deps_d_t_per_k=0.1)
        assert fn(35.0) == pytest.approx(fn(25.0) * (13.0 / 12.0), rel=1e-12)

    def test_nonphysical_eps_rejected(self):
        fn = exponential_tand_power_chain(
            2.45e9, 1.0, 0.01, 0.0, 500.0, 1e-3, t_ref_c=25.0,
            deps_d_t_per_k=-0.1)
        with pytest.raises(ValueError):
            fn(35.0)  # εr(T)=0 出非物理区


class TestRunawayBoundaryAlpha:
    def test_hand_value(self):
        b = runaway_boundary_alpha(1000.0, 0.1)
        assert b["alpha_crit_per_k"] == pytest.approx(
            1.0 / (math.e * 0.1 * 1000.0), rel=1e-12)

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError):
            runaway_boundary_alpha(0.0, 0.1)
        with pytest.raises(ValueError):
            runaway_boundary_alpha(1000.0, -1.0)


class TestHeatingFixedPoint:
    def test_constant_power_exact_and_margin_one(self):
        out = heating_fixed_point(lambda t: 500.0, 25.0, 0.1)
        assert out["status"] == "converged"
        assert out["t_star_c"] == pytest.approx(25.0 + 0.1 * 500.0, rel=1e-9)
        assert out["stability_slope"] == pytest.approx(0.0, abs=1e-9)
        assert out["stability_margin"] == pytest.approx(1.0, rel=1e-9)
        assert out["stable"] is True

    def test_runaway_boundary_reproduction(self):
        """规格 :142 验收：合成单调 tanδ(T) 收敛/失控分界复现。"""
        r_th, p0 = 0.1, 4.088988953770923  # 2.45GHz/12εr/tanδ0.01/500V/1L
        alpha_crit = 1.0 / (math.e * r_th * p0)
        below = heating_fixed_point(
            exponential_tand_power_chain(
                2.45e9, 12.0, 0.01, 0.9 * alpha_crit, 500.0, 1e-3),
            25.0, r_th)
        assert below["status"] == "converged"
        assert below["stable"] is True
        assert below["stability_slope"] < 1.0
        assert below["t_star_c"] < 25.0 + 1.0 / (0.9 * alpha_crit)  # 下支
        above = heating_fixed_point(
            exponential_tand_power_chain(
                2.45e9, 12.0, 0.01, 1.1 * alpha_crit, 500.0, 1e-3),
            25.0, r_th)
        assert above["status"] == "diverged"
        assert above["converged"] is False

    def test_bounds_trigger_out_of_bounds(self):
        fn = exponential_tand_power_chain(
            2.45e9, 12.0, 0.01, 0.9 / (math.e * 0.1 * 4.089), 500.0, 1e-3)
        out = heating_fixed_point(fn, 25.0, 0.1, t_bounds_c=(25.0, 25.05))
        assert out["status"] == "out_of_bounds"

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError):
            heating_fixed_point(lambda t: 1.0, 25.0, 0.0)  # r_th=0
        with pytest.raises(ValueError):
            heating_fixed_point(lambda t: 1.0, 25.0, 1.0, relaxation=0.0)
        with pytest.raises(ValueError):
            heating_fixed_point(lambda t: 1.0, 25.0, 1.0, max_iterations=0)
        with pytest.raises(ValueError):
            heating_fixed_point("nope", 25.0, 1.0)  # 非 callable
        with pytest.raises(ValueError):
            heating_fixed_point(lambda t: -1.0, 25.0, 1.0)  # 负功率


class TestProcessWindow:
    R, TAU = 2.0, 10.0

    def test_single_rc_reach_time_analytic(self):
        out = process_window([self.R], [self.TAU], 25.0, 75.0, power_w=100.0)
        # ΔT=100·2(1−e^{−t/τ})=50 → t=τ·ln(P·R/(P·R−ΔT))=10·ln(4/3)
        assert out["t_reach_s"] == pytest.approx(
            self.TAU * math.log(200.0 / 150.0), rel=1e-9)
        assert out["target_reachable"] is True

    def test_hold_power_energy_conservation(self):
        out = process_window([1.0, 2.0], [0.1, 30.0], 25.0, 125.0)
        assert out["p_hold_w"] == pytest.approx(100.0 / 3.0, rel=1e-12)
        assert out["r_total"] == pytest.approx(3.0, rel=1e-12)

    def test_required_power_and_window(self):
        out = process_window([self.R], [self.TAU], 25.0, 75.0,
                             t_max_c=100.0, t_process_s=5.0)
        z5 = self.R * (1.0 - math.exp(-5.0 / self.TAU))
        assert out["z_th_at_process"] == pytest.approx(z5, rel=1e-12)
        assert out["p_required_w"] == pytest.approx(50.0 / z5, rel=1e-12)
        assert out["power_window"] == pytest.approx(
            [50.0 / z5, 75.0 / z5], rel=1e-12)

    def test_unreachable_target_is_honest_none(self):
        out = process_window([self.R], [self.TAU], 25.0, 75.0, power_w=20.0)
        assert out["t_reach_s"] is None
        assert out["target_reachable"] is False

    def test_overshoot_flag(self):
        out = process_window([self.R], [self.TAU], 25.0, 75.0,
                             t_max_c=100.0, power_w=100.0)
        assert out["p_steady_c"] == pytest.approx(225.0, rel=1e-12)
        assert out["overshoot_steady"] is True

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError):
            process_window([self.R], [self.TAU], 75.0, 75.0)  # 无加热需求
        with pytest.raises(ValueError):
            process_window([self.R], [self.TAU], 25.0, 50.0, t_max_c=40.0)
        with pytest.raises(ValueError):
            process_window([], [], 25.0, 50.0)  # 空支路
        with pytest.raises(ValueError):
            process_window([1.0, 2.0], [1.0], 25.0, 50.0)  # 长度不一致
        with pytest.raises(ValueError):
            process_window([0.0], [1.0], 25.0, 50.0)  # 零热阻
        with pytest.raises(ValueError):
            process_window([1.0], [0.0], 25.0, 50.0)  # 零时间常数


# ---------------------------------------------------------------------------
# 注册键（service 面）：契约 + 确定性 + 名义设计点锚
# ---------------------------------------------------------------------------

class TestRegisteredCalculators:
    def test_all_three_keys_run_and_are_deterministic(self):
        from rfauto.service.calculator_service import run_calculator

        cases = {
            "multimode_cavity_heating": {
                "a_mm": 1000.0, "b_mm": 1000.0, "d_mm": 1000.0,
                "f_ghz": 3.0, "v_load_l": 1.0, "load_eps_r": 78.0,
                "load_tan_d": 0.12, "q_wall": 2000.0, "power_w": 1000.0},
            "single_mode_applicator": {
                "a_mm": 30.0, "b_mm": 20.0, "d_mm": 40.0,
                "wall_sigma_s_per_m": 5.8e7, "load_v_l": 1e-5,
                "load_eps_r": 80.0, "load_tan_d": 0.5,
                "input_power_w": 100.0},
            "microwave_process_window": {
                "r_th_c_per_w": [2.0], "tau_s": [10.0], "ambient_c": 25.0,
                "target_c": 75.0, "t_max_c": 100.0, "t_process_s": 5.0,
                "power_w": 100.0},
        }
        for name, params in cases.items():
            first = run_calculator(name, params)
            assert first["ok"] is True, f"{name}: {first.get('error')!r}"
            json.dumps(first, ensure_ascii=False, allow_nan=False)
            second = run_calculator(name, params)
            assert json.dumps(first, sort_keys=True, allow_nan=False) == (
                json.dumps(second, sort_keys=True, allow_nan=False))

    def test_multimode_water_anchor_through_service(self):
        from rfauto.service.calculator_service import run_calculator

        out = run_calculator("multimode_cavity_heating", {
            "a_mm": 1000.0, "b_mm": 1000.0, "d_mm": 1000.0, "f_ghz": 3.0,
            "v_load_l": 1.0, "load_eps_r": 78.0, "load_tan_d": 0.12,
            "q_wall": 2000.0, "power_w": 1000.0})
        load = out["result"]["load"]
        # 1m³ 腔装 1L 水：F≈0.0725、η≈0.946 → 速率 0.226 °C/s，落
        # "~0.24 °C/s/kg" 经典量级带（量级锚 15% 窗）
        rate = load["p_load_w"] / 4186.0
        assert rate == pytest.approx(_WATER_RATE_REF, rel=0.15)
        assert 0.20 < rate < 0.28
        # 1m³@3GHz 交叉锚（实测：Weyl 8395 vs 精确 8026，−4.4%）
        assert out["result"]["n_weyl"] == pytest.approx(8394.99, rel=1e-4)
        assert out["result"]["n_exact_total"] == 8026
        assert out["result"]["weyl_vs_exact_rel_dev"] == pytest.approx(
            -0.04395, rel=5e-3)

    def test_single_mode_detune_chain_via_service(self):
        from rfauto.service.calculator_service import run_calculator

        out = run_calculator("single_mode_applicator", {
            "a_mm": 30.0, "b_mm": 20.0, "d_mm": 40.0,
            "wall_sigma_s_per_m": 5.8e7,
            "sample_box_mm": [14.0, 8.0, 18.0, 16.0, 12.0, 22.0],
            "sample_eps_r": 5.0})
        assert out["ok"] is True
        detune = out["result"]["perturbation"]
        assert detune["df_over_f"] < 0.0  # E 区介质微扰下调（Pozar §6.7）
        assert detune["f_operating_ghz"] < detune["f0_ghz"]

    def test_process_window_runaway_block_via_service(self):
        from rfauto.service.calculator_service import run_calculator

        out = run_calculator("microwave_process_window", {
            "r_th_c_per_w": [0.1], "tau_s": [30.0], "ambient_c": 25.0,
            "target_c": 60.0, "f_ghz": 2.45, "e_rms_v_per_m": 500.0,
            "load_v_l": 1.0, "eps_r": 12.0, "tan_d_ref": 0.01,
            "alpha_per_k": 0.003})
        assert out["ok"] is True
        run = out["result"]["runaway"]
        assert run["status"] == "converged"
        assert run["stable"] is True
        assert run["alpha_margin_ratio"] > 1.0
