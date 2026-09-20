"""D2 导体损耗口径单测（§10.4 D2）：Huray / Hammerstad 粗糙度 + 电镀厚度。

裁判口径（不得自证，#118）：
- 光滑铜 Rs = sqrt(omega*mu/(2*sigma))、delta = sqrt(2/(omega*mu*sigma))：
  Pozar, Microwave Engineering, 4th ed., §1.7.1；已刊点 Cu @1 GHz
  delta ~ 2.06 um / Rs ~ 8.25 mohm/sq、@10 GHz Rs ~ 26.1 mohm/sq。
- Huray/Hall-Huray 闭式
  K = A_matte/A_flat + (3/2) sum f_i/(1 + delta/r_i + delta^2/(2 r_i^2))：
  FlexCompute Tidy3D 文档 tidy3d.rf.HuraySurfaceRoughness（= Ansys HFSS/SIwave
  Hall-Huray 口径）；参数点取 Ansys SIwave 系统内置 r = 0.5 um、SR = 1/3/6。
- Hammerstad K = 1 + (RF-1)*(2/pi)*arctan(1.4*(Rq/delta)^2)：
  Hammerstad-Jensen 1980；RF = 2 为经典式（FlexCompute HammerstadSurfaceRoughness）。
- 有限厚度 K_t = Re[(1+j)/(sigma*delta)*coth((1+j)t/delta)]：
  Ramo-Whinnery-Van Duzer §5.5（用 cmath 复 coth 作独立裁判）。

全部测试确定性、无网络、无求解器、无真机。
"""

from __future__ import annotations

import cmath
import itertools
import math

import numpy as np
import pytest

from rfauto.core.conductor_loss import (
    MU0,
    ROUGHNESS_MODELS,
    ConductorLossResult,
    conductor_surface_resistance,
    finite_thickness_factor,
    finite_thickness_surface_resistance,
    hall_huray_surface_ratio,
    hammerstad_roughness_factor,
    huray_factor_from_nodules,
    huray_roughness_factor,
    roughness_gain,
    skin_depth,
    smooth_surface_resistance,
)

#: 铜电导率 [S/m]（教科书 / Ansys 常用值）
SIGMA_CU = 5.8e7

#: Pozar §1.7.1 已刊铜点（1 GHz）
DELTA_CU_1GHZ_LITERATURE_M = 2.06e-6
RS_CU_1GHZ_LITERATURE_OHM = 8.25e-3
#: 铜 Rs @10 GHz 已刊点
RS_CU_10GHZ_LITERATURE_OHM = 26.1e-3

#: Ansys SIwave 系统内置 Huray 参数：r = 0.5 um，Hall-Huray surface ratio = 1/3/6
HURAY_NODULE_RADIUS_M = 0.5e-6
HURAY_SURFACE_RATIOS = (1.0, 3.0, 6.0)

#: FlexCompute/Tidy3D Huray 闭式在 SR=1/3/6 处的手算参考（delta 取皮肤深度闭式）
HURAY_REF_1GHZ = {
    1.0: 1.1078035515314004,
    3.0: 1.323410654594201,
    6.0: 1.646821309188402,
}
HURAY_REF_10GHZ = {
    1.0: 1.4694588328319664,
    3.0: 2.4083764984958993,
    6.0: 3.8167529969917986,
}

#: Hammerstad 闭式（RF = 2）手算参考
HAMMERSTAD_REF = {
    0.5: 1.2143338468798748,
    1.0: 1.6051369134225069,
    2.0: 1.8875036482733578,
}

#: K_t(x = t/delta = 1) 手算参考
KT_AT_X1 = 1.0856357047503278


def _huray_closed_form(surface_ratio: float, delta_m: float) -> float:
    """FlexCompute/Tidy3D 闭式的测试内独立实现（1 族铜瘤、A_matte/A_flat = 1）。"""
    r = HURAY_NODULE_RADIUS_M
    return 1.0 + 1.5 * surface_ratio / (1.0 + delta_m / r + delta_m * delta_m / (2.0 * r * r))


# ─── 光滑铜基准 ───────────────────────────────────────────────────────────────

class TestSmoothCopper:
    """光滑半无限铜：delta / Rs 闭式与已刊点。"""

    @pytest.mark.parametrize("freq_hz", [1.0e9, 2.4e9, 10.0e9, 40.0e9])
    def test_skin_depth_closed_form(self, freq_hz):
        """delta 与 sqrt(2/(omega*mu*sigma)) 逐值一致。"""
        omega = 2.0 * math.pi * freq_hz
        expected = math.sqrt(2.0 / (omega * MU0 * SIGMA_CU))
        assert skin_depth(freq_hz, SIGMA_CU) == pytest.approx(expected, rel=1e-14)

    @pytest.mark.parametrize("freq_hz", [1.0e9, 2.4e9, 10.0e9, 40.0e9])
    def test_surface_resistance_closed_form(self, freq_hz):
        """Rs 与 sqrt(omega*mu/(2*sigma)) 一致，且等于 1/(sigma*delta)。"""
        omega = 2.0 * math.pi * freq_hz
        expected = math.sqrt(omega * MU0 / (2.0 * SIGMA_CU))
        rs = smooth_surface_resistance(freq_hz, SIGMA_CU)
        assert rs == pytest.approx(expected, rel=1e-14)
        delta = skin_depth(freq_hz, SIGMA_CU)
        assert rs == pytest.approx(1.0 / (SIGMA_CU * delta), rel=1e-13)

    def test_literature_points_copper(self):
        """已刊铜点：1 GHz delta ~ 2.06 um / Rs ~ 8.25 mohm；10 GHz Rs ~ 26.1 mohm。"""
        assert skin_depth(1.0e9, SIGMA_CU) == pytest.approx(DELTA_CU_1GHZ_LITERATURE_M, rel=0.02)
        assert smooth_surface_resistance(1.0e9, SIGMA_CU) == pytest.approx(
            RS_CU_1GHZ_LITERATURE_OHM, rel=0.01
        )
        assert smooth_surface_resistance(10.0e9, SIGMA_CU) == pytest.approx(
            RS_CU_10GHZ_LITERATURE_OHM, rel=0.01
        )

    def test_mu_r_scaling(self):
        """delta 按 1/sqrt(mu_r) 缩小、Rs 按 sqrt(mu_r) 放大。"""
        f = 1.0e9
        assert skin_depth(f, SIGMA_CU, 2.0) == pytest.approx(
            skin_depth(f, SIGMA_CU) / math.sqrt(2.0), rel=1e-14
        )
        assert smooth_surface_resistance(f, SIGMA_CU, 2.0) == pytest.approx(
            smooth_surface_resistance(f, SIGMA_CU) * math.sqrt(2.0), rel=1e-14
        )

    def test_rs_increases_with_frequency(self):
        """Rs 随频率单调增（sqrt(f)）。"""
        freqs = [1.0e9, 2.0e9, 5.0e9, 10.0e9, 20.0e9]
        values = [smooth_surface_resistance(f, SIGMA_CU) for f in freqs]
        assert all(b > a for a, b in itertools.pairwise(values))


# ─── Hammerstad 粗糙度 ───────────────────────────────────────────────────────

class TestHammerstad:
    """修改版 Hammerstad 增益（RF 参数化）。"""

    def test_flat_baseline_is_unity(self):
        """平坦基准：RF = 1 或 Rq = 0 -> 增益恒等 1。"""
        for rq in (0.0, 1e-9, 1e-6, 1e-3):
            for delta in (1e-7, 1e-6, 1e-5):
                assert hammerstad_roughness_factor(rq, delta, roughness_factor=1.0) == pytest.approx(1.0)
        for delta in (1e-7, 1e-6, 1e-5):
            assert hammerstad_roughness_factor(0.0, delta, roughness_factor=2.0) == pytest.approx(1.0)

    @pytest.mark.parametrize("ratio,expected", list(HAMMERSTAD_REF.items()))
    def test_reference_values(self, ratio, expected):
        """Hammerstad 闭式在 Rq/delta = 0.5 / 1 / 2 处的手算参考。"""
        delta = 1.0e-6
        assert hammerstad_roughness_factor(ratio * delta, delta) == pytest.approx(expected, rel=1e-12)

    def test_saturation_to_roughness_factor(self):
        """Rq >> delta 时饱和到 RF（arctan -> pi/2）。"""
        assert hammerstad_roughness_factor(1.0e3 * 1e-6, 1.0e-6, 2.0) == pytest.approx(2.0, rel=1e-6)
        assert hammerstad_roughness_factor(1.0e3 * 1e-6, 1.0e-6, 3.5) == pytest.approx(3.5, rel=1e-6)

    def test_monotone_in_roughness(self):
        """Rq 增大 -> 增益严格单调增。"""
        delta = 1.0e-6
        rqs = np.linspace(0.0, 5.0e-6, 40)
        gains = [hammerstad_roughness_factor(float(rq), delta) for rq in rqs]
        assert all(b > a for a, b in itertools.pairwise(gains))

    def test_gain_bounded_by_roughness_factor(self):
        """增益始终落在 [1, RF]。"""
        delta = 1.0e-6
        for rq in np.linspace(0.0, 1.0e-4, 50):
            g = hammerstad_roughness_factor(float(rq), delta, 2.0)
            assert 1.0 <= g <= 2.0


# ─── Huray / Hall-Huray 雪球模型 ─────────────────────────────────────────────

class TestHuray:
    """Hall-Huray 增益：平坦基准、已刊参数点、单调性、极限。"""

    def test_flat_baseline_is_unity(self):
        """无铜瘤 + 哑光面积比 1 -> 增益恒等 1。"""
        for delta in (1e-8, 1e-6, 1e-4):
            assert huray_roughness_factor(delta, ()) == pytest.approx(1.0)
            assert huray_roughness_factor(delta, None) == pytest.approx(1.0)
            assert huray_roughness_factor(delta, [], 1.0) == pytest.approx(1.0)

    @pytest.mark.parametrize("surface_ratio", HURAY_SURFACE_RATIOS)
    def test_reference_values_siwave_parameters(self, surface_ratio):
        """Ansys SIwave 已刊参数 r = 0.5 um、SR = 1/3/6 在 1/10 GHz 的闭式参考。"""
        delta_1g = skin_depth(1.0e9, SIGMA_CU)
        delta_10g = skin_depth(10.0e9, SIGMA_CU)
        assert huray_roughness_factor(delta_1g, [(surface_ratio, HURAY_NODULE_RADIUS_M)]) == pytest.approx(
            HURAY_REF_1GHZ[surface_ratio], rel=1e-12
        )
        assert huray_roughness_factor(delta_10g, [(surface_ratio, HURAY_NODULE_RADIUS_M)]) == pytest.approx(
            HURAY_REF_10GHZ[surface_ratio], rel=1e-12
        )
        assert _huray_closed_form(surface_ratio, delta_1g) == pytest.approx(
            HURAY_REF_1GHZ[surface_ratio], rel=1e-12
        )

    def test_surface_ratio_definition(self):
        """SR = N * 4*pi*r^2 / A_flat，且按几何构造与直接给 f 等价。"""
        r = HURAY_NODULE_RADIUS_M
        n = 8.0
        area = 4.0e-12
        expected = n * 4.0 * math.pi * r * r / area
        assert hall_huray_surface_ratio(r, n, area) == pytest.approx(expected, rel=1e-15)
        delta = 1.0e-6
        assert huray_factor_from_nodules(delta, r, n, area) == pytest.approx(
            huray_roughness_factor(delta, [(expected, r)]), rel=1e-14
        )

    def test_monotone_in_surface_ratio(self):
        """SR 增大 -> 增益严格单调增。"""
        delta = 1.0e-6
        ratios = np.linspace(0.0, 10.0, 40)
        gains = [huray_roughness_factor(delta, [(float(s), HURAY_NODULE_RADIUS_M)]) for s in ratios]
        assert all(b > a for a, b in itertools.pairwise(gains))

    def test_monotone_in_nodule_radius(self):
        """铜瘤半径增大 -> 增益严格单调增（f 与场衰减几何同时增大）。"""
        delta = 1.0e-6
        radii = np.linspace(0.05e-6, 2.0e-6, 40)
        gains = [huray_factor_from_nodules(delta, float(r), 6.0, 1.0e-12) for r in radii]
        assert all(b > a for a, b in itertools.pairwise(gains))

    def test_higher_frequency_higher_gain(self):
        """同参数下频率升高（delta 减小）-> 增益升高。"""
        prev = -1.0
        for freq in (1.0e9, 5.0e9, 10.0e9, 40.0e9):
            g = huray_roughness_factor(skin_depth(freq, SIGMA_CU), [(3.0, HURAY_NODULE_RADIUS_M)])
            assert g > prev
            prev = g

    def test_high_frequency_limit(self):
        """delta -> 0 时 K -> 1 + (3/2)*SR。"""
        for sr in HURAY_SURFACE_RATIOS:
            g = huray_roughness_factor(1.0e-18, [(sr, HURAY_NODULE_RADIUS_M)])
            assert g == pytest.approx(1.0 + 1.5 * sr, rel=1e-9)

    def test_multi_family_sum(self):
        """多族铜瘤按 (3/2)*sum 线性叠加。"""
        delta = 1.0e-6
        coeffs = [(1.0, 0.3e-6), (2.5, 0.6e-6), (0.7, 1.2e-6)]
        expected = 1.0 + sum(
            1.5 * f / (1.0 + delta / r + delta * delta / (2.0 * r * r)) for f, r in coeffs
        )
        assert huray_roughness_factor(delta, coeffs) == pytest.approx(expected, rel=1e-14)

    def test_relative_matte_area_scales(self):
        """哑光面积比按加性常数平移增益。"""
        delta = 1.0e-6
        base = huray_roughness_factor(delta, [(2.0, HURAY_NODULE_RADIUS_M)], 1.0)
        shifted = huray_roughness_factor(delta, [(2.0, HURAY_NODULE_RADIUS_M)], 1.25)
        assert shifted - base == pytest.approx(0.25, rel=1e-14)


# ─── 电镀 / 有限铜厚 ─────────────────────────────────────────────────────────

class TestFiniteThickness:
    """有限铜厚修正 K_t 的极限、参考点与复 coth 独立裁判。"""

    def test_semi_infinite_limit(self):
        """t >> delta -> K_t -> 1（趋近半无限）。"""
        delta = 1.0e-6
        for factor in (10.0, 20.0, 100.0):
            assert finite_thickness_factor(factor * delta, delta) == pytest.approx(1.0, rel=1e-8)

    def test_thin_film_limit(self):
        """t << delta -> K_t -> delta/t，Rs -> 1/(sigma*t)（薄层直流面电阻）。"""
        delta = 1.0e-6
        for factor in (1.0e3, 1.0e4):
            t = delta / factor
            assert finite_thickness_factor(t, delta) == pytest.approx(factor, rel=1e-10)
            rs = finite_thickness_surface_resistance(1.0e9, SIGMA_CU, t)
            assert rs == pytest.approx(1.0 / (SIGMA_CU * t), rel=1e-9)

    def test_reference_at_delta(self):
        """x = t/delta = 1 处的手算参考。"""
        delta = 1.0e-6
        assert finite_thickness_factor(delta, delta) == pytest.approx(KT_AT_X1, rel=1e-12)

    @pytest.mark.parametrize("x", [0.1, 0.45, 0.7, 1.0, 1.5, 3.0, 8.0])
    def test_matches_complex_coth(self, x):
        """独立裁判：Re[(1+j)*coth((1+j)x)]（复 coth 定义，Ramo-Whinnery-Van Duzer §5.5）。"""
        z = complex(1.0, 1.0) * x
        expected = ((1.0 + 1.0j) / cmath.tanh(z)).real
        assert finite_thickness_factor(x * 1.0e-6, 1.0e-6) == pytest.approx(expected, rel=1e-11)

    def test_small_x_series_avoids_cancellation(self):
        """极小 x 用级数展开：K_t 与 delta/t 的相对误差 < 1e-12。"""
        delta = 1.0e-6
        x = 1.0e-4
        assert finite_thickness_factor(x * delta, delta) == pytest.approx(1.0 / x, rel=1e-12)

    def test_monotone_in_thin_regime(self):
        """薄铜区（t < delta）：厚度增大 -> K_t 单调减。"""
        delta = 1.0e-6
        ts = np.linspace(0.02e-6, 0.5e-6, 40)
        gains = [finite_thickness_factor(float(t), delta) for t in ts]
        assert all(b < a for a, b in itertools.pairwise(gains))
        assert gains[0] > gains[-1] > 1.0

    def test_approaches_semi_infinite(self):
        """t >> delta：K_t 趋近 1（阻尼振荡包络，偏差 < 1e-6）。"""
        delta = 1.0e-6
        for factor in (10.0, 20.0, 50.0):
            kt = finite_thickness_factor(factor * delta, delta)
            assert kt == pytest.approx(1.0, abs=1e-6)


# ─── 组合口径 + 校验 + 确定性 ────────────────────────────────────────────────

class TestCombineAndValidation:
    """combinator、非法输入、确定性。"""

    def test_no_roughness_no_thickness_equals_smooth(self):
        """默认（smooth、半无限）结果即光滑 Rs。"""
        res = conductor_surface_resistance(10.0e9, SIGMA_CU)
        assert isinstance(res, ConductorLossResult)
        assert res.roughness_gain == 1.0
        assert res.thickness_gain == 1.0
        assert res.rs_effective_ohm == pytest.approx(smooth_surface_resistance(10.0e9, SIGMA_CU), rel=1e-15)
        assert res.total_gain == pytest.approx(1.0, rel=1e-15)

    def test_flat_baseline_hammerstad_rf1_is_smooth(self):
        """平坦基准（RF = 1，任意 Rq）不改变 Rs。"""
        res = conductor_surface_resistance(
            5.0e9, SIGMA_CU, model="hammerstad", rq_m=1.0e-6, roughness_factor=1.0
        )
        assert res.rs_effective_ohm == pytest.approx(res.rs_smooth_ohm, rel=1e-15)

    def test_combined_multiplicative(self):
        """Rs_eff = Rs_smooth * K_rough * K_thick。"""
        freq, sigma, rq, t = 10.0e9, SIGMA_CU, 0.8e-6, 2.0e-6
        res = conductor_surface_resistance(
            freq, sigma, model="hammerstad", rq_m=rq, thickness_m=t
        )
        delta = skin_depth(freq, sigma)
        expected = (
            smooth_surface_resistance(freq, sigma)
            * hammerstad_roughness_factor(rq, delta)
            * finite_thickness_factor(t, delta)
        )
        assert res.rs_effective_ohm == pytest.approx(expected, rel=1e-14)
        assert res.total_gain == pytest.approx(expected / res.rs_smooth_ohm, rel=1e-14)
        assert res.model == "hammerstad"

    def test_combinator_huray_via_nodules(self):
        """combinator 的 huray 分支（几何参数）与直接调用一致。"""
        freq, sigma = 5.0e9, SIGMA_CU
        res = conductor_surface_resistance(
            freq,
            sigma,
            model="huray",
            nodule_radius_m=HURAY_NODULE_RADIUS_M,
            nodules_per_cell=6.0,
            cell_area_m2=1.0e-12,
            relative_matte_area=1.0,
            thickness_m=3.0e-6,
        )
        delta = skin_depth(freq, sigma)
        expected = (
            smooth_surface_resistance(freq, sigma)
            * huray_factor_from_nodules(delta, HURAY_NODULE_RADIUS_M, 6.0, 1.0e-12)
            * finite_thickness_factor(3.0e-6, delta)
        )
        assert res.rs_effective_ohm == pytest.approx(expected, rel=1e-14)
        assert res.roughness_gain > 1.0
        assert res.thickness_gain >= 1.0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"freq_hz": 0.0, "sigma_s_per_m": SIGMA_CU},
            {"freq_hz": -1.0e9, "sigma_s_per_m": SIGMA_CU},
            {"freq_hz": float("nan"), "sigma_s_per_m": SIGMA_CU},
            {"freq_hz": float("inf"), "sigma_s_per_m": SIGMA_CU},
            {"freq_hz": 1.0e9, "sigma_s_per_m": 0.0},
            {"freq_hz": 1.0e9, "sigma_s_per_m": -1.0},
            {"freq_hz": 1.0e9, "sigma_s_per_m": SIGMA_CU, "mu_r": 0.0},
        ],
    )
    def test_bad_frequency_or_conductivity_raise(self, kwargs):
        """非正/非有限频率、电导率、相对磁导率抛 ValueError。"""
        with pytest.raises(ValueError):
            conductor_surface_resistance(**kwargs)

    def test_roughness_gain_dispatch_errors(self):
        """未知模型 / 缺参 -> ValueError。"""
        with pytest.raises(ValueError):
            roughness_gain("nope", delta_m=1.0e-6)
        with pytest.raises(ValueError):
            roughness_gain("hammerstad", delta_m=1.0e-6)
        with pytest.raises(ValueError):
            roughness_gain("huray", delta_m=1.0e-6)
        with pytest.raises(ValueError):
            conductor_surface_resistance(1.0e9, SIGMA_CU, model="gross")

    def test_bad_hammerstad_inputs_raise(self):
        """Rq < 0、delta <= 0、RF < 1 -> ValueError。"""
        with pytest.raises(ValueError):
            hammerstad_roughness_factor(-1.0e-6, 1.0e-6)
        with pytest.raises(ValueError):
            hammerstad_roughness_factor(1.0e-6, 0.0)
        with pytest.raises(ValueError):
            hammerstad_roughness_factor(1.0e-6, 1.0e-6, roughness_factor=0.5)

    def test_bad_huray_inputs_raise(self):
        """非法 Huray 参数 -> ValueError（含非二元组元素）。"""
        with pytest.raises(ValueError):
            huray_roughness_factor(0.0, [(1.0, 0.5e-6)])
        with pytest.raises(ValueError):
            huray_roughness_factor(1.0e-6, [(-1.0, 0.5e-6)])
        with pytest.raises(ValueError):
            huray_roughness_factor(1.0e-6, [(1.0, 0.0)])
        with pytest.raises(ValueError):
            huray_roughness_factor(1.0e-6, [(1.0, 0.5e-6)], relative_matte_area=0.0)
        with pytest.raises(ValueError):
            huray_roughness_factor(1.0e-6, [(1.0,)])
        with pytest.raises(ValueError):
            huray_roughness_factor(1.0e-6, [(1.0, 0.5e-6, 2.0)])
        with pytest.raises(ValueError):
            huray_roughness_factor(1.0e-6, ["ab"])
        with pytest.raises(ValueError):
            hall_huray_surface_ratio(0.0, 1.0, 1.0e-12)
        with pytest.raises(ValueError):
            hall_huray_surface_ratio(0.5e-6, -1.0, 1.0e-12)
        with pytest.raises(ValueError):
            hall_huray_surface_ratio(0.5e-6, 1.0, 0.0)

    def test_bad_thickness_raise(self):
        """厚度 <= 0 或非有限 -> ValueError。"""
        with pytest.raises(ValueError):
            finite_thickness_factor(0.0, 1.0e-6)
        with pytest.raises(ValueError):
            finite_thickness_factor(-1.0e-6, 1.0e-6)
        with pytest.raises(ValueError):
            finite_thickness_factor(1.0e-6, 0.0)
        with pytest.raises(ValueError):
            conductor_surface_resistance(1.0e9, SIGMA_CU, thickness_m=0.0)

    def test_determinism(self):
        """同输入两次调用逐位一致（标量 + 组合结果）。"""
        args = dict(
            freq_hz=10.0e9,
            sigma_s_per_m=SIGMA_CU,
            model="huray",
            huray_coeffs=[(3.0, HURAY_NODULE_RADIUS_M)],
            thickness_m=2.0e-6,
        )
        a = conductor_surface_resistance(**args)
        b = conductor_surface_resistance(**args)
        assert a == b
        assert a.rs_effective_ohm == b.rs_effective_ohm
        delta = skin_depth(args["freq_hz"], SIGMA_CU)
        assert huray_roughness_factor(delta, args["huray_coeffs"]) == huray_roughness_factor(
            delta, args["huray_coeffs"]
        )
        assert ROUGHNESS_MODELS == ("smooth", "hammerstad", "huray")
