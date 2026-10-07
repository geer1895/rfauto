"""core/loadpull_efficiency_circles.py 单测（MT-7 等效率圆）。

判据（#118 双路径）：
- η_max 经典锚（膝点折减）+ η(Γ_opt)=η_max；
- 恒效率≡恒功率定理（网格逐点恒等式）；
- 圆闭式 vs 平面采样独立核（Γ 圆上的点映回 Z 必落在解析轨迹上）；
- 结点与 active_chain Yt 平面结点互证；极限锚（p→1 塌缩/p→0 全图）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.active_chain import (
    LoadPullDevice,
    cripps_contour_locus,
    load_pull_power_dbm,
)
from rfauto.core.loadpull_efficiency_circles import (
    class_b_efficiency_ray,
    constant_efficiency_circle,
    drain_efficiency,
    efficiency_contour,
    fundamental_current_amplitude,
    max_efficiency,
    output_power_w,
)

DEV = LoadPullDevice(vdd_v=28.0, imax_a=2.0, cout_f=0.0, vknee_v=1.0)
F_HZ = 3.5e9
Z0 = 50.0


def _yt_to_gamma(y_t: complex, cout_f: float = 0.0,
                 z0: float = Z0) -> complex:
    """Yt 平面点 → Γ_L（C_out=0：Y_L=Y_t；与 active_chain 同 Möbius 式）。"""
    y_l = y_t - 1j * 2.0 * math.pi * F_HZ * cout_f
    zz = (1.0 / y_l) if abs(y_l) > 1e-15 else complex(math.inf)
    return (zz - z0) / (zz + z0)


class TestMaxEfficiency:
    def test_classic_values_with_knee_derating(self):
        assert abs(max_efficiency(DEV, "A") - 0.5 * 27.0 / 28.0) < 1e-15
        assert abs(max_efficiency(DEV, "B")
                   - math.pi / 4.0 * 27.0 / 28.0) < 1e-15
        # 零膝点 → 经典 1/2 与 π/4
        dev0 = LoadPullDevice(vdd_v=28.0, imax_a=2.0, cout_f=0.0,
                              vknee_v=0.0)
        assert max_efficiency(dev0, "A") == 0.5
        assert abs(max_efficiency(dev0, "B") - math.pi / 4.0) < 1e-15

    def test_guard(self):
        for bad in ("AB", "c", ""):
            try:
                max_efficiency(DEV, bad)
            except ValueError:
                continue
            raise AssertionError(f"pa_class={bad!r} 应报 ValueError")


class TestEfficiencyFace:
    def test_eta_at_class_optimum_is_max(self):
        """B 类最优在 R_opt；A 类线性不削波 → 自身最优在 2·R_opt（经典）。"""
        g_opt_b = DEV.optimal_gamma(F_HZ, Z0)
        eta_b = drain_efficiency(g_opt_b, DEV, F_HZ, "B", Z0)
        assert abs(eta_b - max_efficiency(DEV, "B")) < 1e-12
        r_opt = 1.0 / DEV.gopt_s
        z_a = 2.0 * r_opt  # A 类负载线两倍
        g_opt_a = complex((z_a - Z0) / (z_a + Z0))
        eta_a = drain_efficiency(g_opt_a, DEV, F_HZ, "A", Z0)
        assert abs(eta_a - max_efficiency(DEV, "A")) < 1e-12
        # A 类在 B 类最优点 = η_max,A/2（3 dB 回退的几何后果）
        eta_a_at_b = drain_efficiency(g_opt_b, DEV, F_HZ, "A", Z0)
        assert abs(eta_a_at_b - max_efficiency(DEV, "A") / 2.0) < 1e-12

    def test_theorem_class_a_full_plane(self):
        """A 类 P_dc 恒定 → η/η_max = P/P_max 全域逐点（Cripps 线性简化）。"""
        rng = np.random.default_rng(20261003)
        gammas = 0.85 * np.exp(1j * 2 * math.pi * rng.random(400))
        eta_max = max_efficiency(DEV, "A")
        p_max_w = 0.5 * (DEV.imax_a / 2.0) * DEV.vsw_v  # A 类峰值功率
        for g in gammas[:250]:
            p_w = output_power_w(complex(g), DEV, F_HZ, "A", Z0)
            eta = drain_efficiency(complex(g), DEV, F_HZ, "A", Z0)
            if p_w is None or eta is None:
                continue
            assert abs(eta / eta_max - p_w / p_max_w) < 1e-9

    def test_theorem_class_b_current_limited_branch(self):
        """B 类定理只在电流限支（I1=Isw → P_dc 支内恒定）成立。"""
        rng = np.random.default_rng(11)
        gammas = 0.85 * np.exp(1j * 2 * math.pi * rng.random(400))
        eta_max = max_efficiency(DEV, "B")
        p_max_w = 0.5 * DEV.imax_a * DEV.vsw_v
        n_checked = 0
        for g in gammas[:250]:
            i1 = fundamental_current_amplitude(DEV, F_HZ, complex(g), Z0,
                                               pa_class="B")
            if abs(i1 - DEV.imax_a) > 1e-12:  # 只取电流限支样本
                continue
            p_w = output_power_w(complex(g), DEV, F_HZ, "B", Z0)
            eta = drain_efficiency(complex(g), DEV, F_HZ, "B", Z0)
            assert p_w is not None and eta is not None
            assert abs(eta / eta_max - p_w / p_max_w) < 1e-9
            n_checked += 1
        assert n_checked > 20

    def test_class_b_voltage_limited_ray(self):
        """B 类电压限支：η 只依赖 G/|Yt| → 等效率线=恒功率因数射线。"""
        e = 0.5
        ray = class_b_efficiency_ray(DEV, e)
        g_opt = DEV.gopt_s
        assert abs(ray["junction_g"] - e * g_opt) < 1e-12
        assert abs(ray["junction_bt"]
                   - g_opt * math.sqrt(1.0 - e * e)) < 1e-12
        # 射线上采样（|Yt| ≤ G_opt）：η/η_max 恒 = e 逐点
        for scale in (0.25, 0.5, 0.75, 0.999):
            yt = scale * g_opt
            g = e * yt
            b = yt * math.sqrt(1.0 - e * e)
            gamma = _yt_to_gamma(g + 1j * b)
            eta = drain_efficiency(gamma, DEV, F_HZ, "B", Z0)
            assert eta is not None
            assert abs(eta / max_efficiency(DEV, "B") - e) < 1e-9
        # 窄于等功率弦：射线端 |Bt| = G_opt√(1−e²) 与功率弦结点同点，
        # 但弦上 (G=e·G_opt, |Bt| 更小处) 效率 ≠ e（分族实证）
        bt_inner = 0.5 * g_opt * math.sqrt(1.0 - e * e)
        gamma_chord = _yt_to_gamma(e * g_opt + 1j * bt_inner)
        eta_chord = drain_efficiency(gamma_chord, DEV, F_HZ, "B", Z0)
        assert eta_chord is not None
        assert abs(eta_chord / max_efficiency(DEV, "B") - e) > 1e-3

    def test_class_b_ray_junction_continuity(self):
        """Norton 圆（层级 e）与射线在 |Yt|=G_opt, G=e·G_opt 连续相接。"""
        e = 0.4
        ray = class_b_efficiency_ray(DEV, e)
        g_opt = DEV.gopt_s
        # 射线闭式的结点即两支共点：取结点两侧微小偏移点核 η 连续
        bt_j = float(ray["junction_bt"])
        g_j = float(ray["junction_g"])
        for bt in (bt_j * (1.0 - 1e-9), bt_j * (1.0 + 1e-9)):
            gamma = _yt_to_gamma(g_j + 1j * bt)
            eta = drain_efficiency(gamma, DEV, F_HZ, "B", Z0)
            assert eta is not None
            assert abs(eta / max_efficiency(DEV, "B") - e) < 1e-6
        # 电流限支 Norton 圆在结点处的 B_t = ray 闭式（圆方程联立解）
        g0 = g_opt / (2.0 * e)
        assert abs(float(ray["junction_bt"])
                   - math.sqrt(max(g0 * g0 - (g_j - g0) ** 2, 0.0))) < 1e-9

    def test_class_b_power_face_matches_active_chain_kernel(self):
        """B 类功率面与 active_chain.load_pull_power_dbm 全网格互证（消费核验）。"""
        rng = np.random.default_rng(7)
        for g in 0.95 * np.exp(1j * 2 * math.pi * rng.random(300)):
            p_kernel = 10.0 ** (load_pull_power_dbm(complex(g), DEV, F_HZ, Z0)
                                / 10.0) * 1e-3
            p_local = output_power_w(complex(g), DEV, F_HZ, "B", Z0)
            if not math.isfinite(p_kernel):
                assert p_local is None
                continue
            assert p_local is not None
            assert abs(p_local - p_kernel) / p_kernel < 1e-9

    def test_class_b_dc_is_load_dependent(self):
        """B 类 P_dc=VDD·2I1/π 随负载变（与 A 类恒 P_dc 的机制差异实证）。"""
        g_opt = DEV.optimal_gamma(F_HZ, Z0)
        # 电流限区点：|Yt|>G_opt → I1=Isw 恒 → 与 Γ_opt 同 P_dc
        z_low = DEV.optimal_load_impedance(F_HZ, Z0).real / 2.0  # R=Ropt/2
        gamma_low = (z_low - Z0) / (z_low + Z0)
        p_opt = 10.0 ** (load_pull_power_dbm(g_opt, DEV, F_HZ, Z0) / 10.0)
        p_low = 10.0 ** (load_pull_power_dbm(gamma_low, DEV, F_HZ, Z0) / 10.0)
        assert p_low < p_opt  # R<Ropt 侧电流限：P ∝ R < P_opt
        eta_low = drain_efficiency(gamma_low, DEV, F_HZ, "B", Z0)
        assert eta_low is not None
        assert abs(eta_low / max_efficiency(DEV, "B")
                   - p_low / p_opt) < 1e-9

    def test_invalid_gamma_returns_none(self):
        assert drain_efficiency(1.0 + 0j, DEV, F_HZ, "B", Z0) is None


class TestCircles:
    def test_voltage_limited_branch_gamma_circle_sampling(self):
        """Γ 圆采样点映回 Z 必落在 (R−c)²+X²=c² 上（1e-9）。"""
        for p in (0.9, 0.5, 0.25, 0.05):
            r_opt = 1.0 / DEV.gopt_s
            circ = constant_efficiency_circle(p, r_opt, "voltage_limited", Z0)
            th = np.linspace(-0.45 * math.pi, 0.45 * math.pi, 200)
            g = (circ.gamma_center_re + circ.gamma_radius
                 * np.exp(1j * th))
            z = Z0 * (1.0 + g) / (1.0 - g)
            c = circ.z_center_re
            resid = np.abs(np.abs(z - c) - circ.z_radius)
            assert float(np.max(resid)) < 1e-8, (p, float(np.max(resid)))

    def test_current_limited_branch_line_sampling(self):
        for p in (0.9, 0.5, 0.25):
            r_opt = 1.0 / DEV.gopt_s
            circ = constant_efficiency_circle(p, r_opt, "current_limited", Z0)
            # θ∈[0.1π,1.9π] 避开 Γ=1（直线无穷远端的像，Z 反演奇异点）
            th = np.linspace(0.1 * math.pi, 1.9 * math.pi, 400)
            g = circ.gamma_center_re + circ.gamma_radius * np.exp(1j * th)
            z = Z0 * (1.0 + g) / (1.0 - g)
            resid = np.abs(z.real - circ.z_line_re)
            assert float(np.max(resid)) < 1e-8, (p, float(np.max(resid)))

    def test_junctions_coincide_and_match_active_chain(self):
        """两支结点重合 |Z_j|=R_opt，且与 active_chain Yt 平面结点互证。"""
        r_opt = 1.0 / DEV.gopt_s
        for p in (0.9, 0.5, 0.25):
            cv = constant_efficiency_circle(p, r_opt, "voltage_limited", Z0)
            cl = constant_efficiency_circle(p, r_opt, "current_limited", Z0)
            for zv, zl in zip(cv.junction_z, cl.junction_z, strict=True):
                assert abs(zv - zl) < 1e-12
                assert abs(abs(zv) - r_opt) < 1e-12
            # active_chain 结点：Bt = ±G_opt√(1−p²)（cout=0 → Yt=YL）
            g_opt = DEV.gopt_s
            bt_ref = g_opt * math.sqrt(1.0 - p * p)
            y_j = 1.0 / cv.junction_z[0]
            assert abs(abs(y_j.imag) - bt_ref) < 1e-9
            # cripps_contour_locus 报告的 junction_bt 一致（消费互证）
            bo = -10.0 * math.log10(p)
            locus = cripps_contour_locus(DEV, F_HZ, bo, Z0)
            assert abs(locus["junction_bt"] - bt_ref) < 1e-9

    def test_limit_anchors(self):
        r_opt = 1.0 / DEV.gopt_s  # = V_sw/I_sw = 13.5 Ω
        # p→1：电压限圆过 Γ(Z_opt)（Z_opt=R_opt 时 (Ropt−Z0)/(Ropt+Z0)）
        c1 = constant_efficiency_circle(1.0, r_opt, "voltage_limited", Z0)
        gamma_opt = (r_opt - Z0) / (r_opt + Z0)
        assert abs(abs(gamma_opt - c1.gamma_center_re) - c1.gamma_radius) \
            < 1e-12
        c1l = constant_efficiency_circle(1.0, r_opt, "current_limited", Z0)
        assert abs(abs(gamma_opt - c1l.gamma_center_re) - c1l.gamma_radius) \
            < 1e-12
        # p→0⁺：两圆均 → 单位圆（圆心→0、半径→1，覆盖全图；收敛 O(p)）
        p0 = 1e-4
        c0v = constant_efficiency_circle(p0, r_opt, "voltage_limited", Z0)
        c0l = constant_efficiency_circle(p0, r_opt, "current_limited", Z0)
        assert abs(c0v.gamma_center_re) < 1e-3
        assert abs(c0v.gamma_radius - 1.0) < 1e-3
        # 电流限圆心闭式 = R_line/(R_line+Z0)，R_line=p·R_opt（小 p → 0）
        r_line = p0 * r_opt
        assert abs(c0l.gamma_center_re - r_line / (r_line + Z0)) < 1e-15
        assert abs(c0l.gamma_radius - Z0 / (r_line + Z0)) < 1e-15
        assert c0l.gamma_radius > 0.99

    def test_guards(self):
        r_opt = 1.0 / DEV.gopt_s
        for bad_p in (0.0, -0.1, 1.5):
            for br in ("voltage_limited", "current_limited"):
                try:
                    constant_efficiency_circle(bad_p, r_opt, br, Z0)
                except ValueError:
                    continue
                raise AssertionError(f"p={bad_p!r} 应报 ValueError")
        try:
            constant_efficiency_circle(0.5, r_opt, "side", Z0)
        except ValueError:
            pass
        else:
            raise AssertionError("非法 branch 应报 ValueError")


class TestEfficiencyContour:
    def test_level_mapping_and_consumption(self):
        eta_max_b = max_efficiency(DEV, "B")
        target = eta_max_b * 0.5
        rep = efficiency_contour(DEV, F_HZ, "B", target, Z0)
        assert abs(rep["p_ratio"] - 0.5) < 1e-12
        assert abs(rep["backoff_db"] - 10.0 * math.log10(2.0)) < 1e-9
        # 产核消费：power_locus 即 active_chain.cripps_contour_locus
        locus = cripps_contour_locus(DEV, F_HZ, rep["backoff_db"], Z0)
        assert locus["level_dbm"] == rep["power_locus"]["level_dbm"]
        assert locus["p_ratio"] == rep["power_locus"]["p_ratio"]

    def test_eta_above_max_raises(self):
        try:
            efficiency_contour(DEV, F_HZ, "B", 0.99, Z0)
        except ValueError:
            return
        raise AssertionError("η>η_max 应报 ValueError（线性模型无此等效率线）")
