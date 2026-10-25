"""aurora_h W3-K 池件批锚树：四键三域（超导 Rs/能隙提升核+电小天线 Q
提升核+Weibull 概率纸提升核；R2_core_tier5 §⑤ 池件 P3 清偿 1/2/3 号
——MP-7/T1-A-04/XD-15 同笔清偿）。

数值断言口径（#118 锚先独立实测再写死——测试内表达式路径独立于键内
实现：原始构造/常数内联（mu0=4e-7π、k_B 走 scipy.constants 裁判而非
内核常数）、不消费模块中间量；Weibull 两点手算走纯 python 逐标量链与
实现内 numpy 向量化不同源；#122 residual Rs/文献数值表不入不凑）：

- superconductor_rs：①Nb@5GHz/4.2K 与小比值一阶恒等 (σ₁/2σ₂)·ωμ0λ
  相对差 <1e-7（σ₁/σ₂≈5.3e-5 → 展开余项 O(ε²)≈3e-9）；②局部极限
  f² 幂律（f 减半 → Rs×¼）；③t→0⁺ λ_L(T)→λ_L0 逐位退化+σ₁=t⁴
  恒等（t=1e-6 → σ₁/σn=1e-24）；④σ₂=1/(μ0ωλ²) 独立常数互证。
- superconductor_gap：①t=0 → Δ0=1.764·k_B·Tc（k_B 由 scipy.constants
  独立裁判，非内核常数）；②t→Tc GL 极限 1.74Δ0√(1−t) 相对差 <1e-3
  （tanh 小宗量 x³/3 余量 5e-5 实测）；③Al Δ0=0.1824meV 与材料表带值
  0.182meV 互洽 ≤0.5%；④Δ(T) 单调递减+Δ(t=0) 恒等。
- antenna_q_yaghjian_best：①串联 RLC（R=50Ω/f0=1GHz/Q=40）合成采样
  → q 机器精度回收 ω0L/R（rel 1e-8）、FBW_hp=2/Q=0.05、
  FBW_S(S=2)=1/(√2·Q)；②Γ(f) 数值宽度第三方法（反应抗 X(f)=±2R
  二分求根，与换算式两推导路径独立，rel 1e-6）；③FBW_hp=FBW_S|
  _{S=(1+√2)²} 自洽恒等（(S−1)/√S=2）；④ka=π/2 → Q_min=8/π³+2/π
  =0.8946320478 手算锚（A-01 勘误后口径）+Q=40 reachable；
  ⑤Q=0.1 合成 → unreachable（低于无耗下界判物理不可能）；⑥圆极化
  减半判据翻转（Q=0.5：linear→unreachable / circular→reachable）。
- weibull_paper_fit：①精确 Weibull 分位样本（β=2.5/η=800/n=8，
  Benard 位独立复算）→ β̂/η̂ 机器精度回收（残差≈0、r²=1）；
  ②Benard 对称恒等式 p_i+p_{n+1−i}=1；③n=2 两点手算逐位（OLS 过
  两点 slope=(y₂−y₁)/(x₂−x₁)，纯 python 链）；④β=1 指数退化锚；
  ⑤乱序输入与升序输入同结果（排序守卫）；⑥n=1/t≤0/全同 t 显式拒绝。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.calc_families.antenna_q import antenna_q_yaghjian_best
from rfauto.core.calc_families.probability_paper import weibull_paper_fit
from rfauto.core.calc_families.quantum_cryo import (
    superconductor_gap,
    superconductor_rs,
)

_MU0 = 4.0e-7 * math.pi  # 原始 SI 定义值（不消费模块常量——#118）
_Q_MIN_CHU_KA_PI_2 = 8.0 / math.pi**3 + 2.0 / math.pi  # =0.8946320478…


# ─── superconductor_rs（量子读出域，MP-7）────────────────────────────────────

class TestSuperconductorRs:
    def test_nb_5ghz_first_order_ratio_identity(self):
        """Nb@5GHz/4.2K：Rs 与一阶恒等 (σ₁/2σ₂)·ωμ0λ 相对差 <1e-7。"""
        res = superconductor_rs("Nb", 5.0e9, 4.2)
        t = 4.2 / 9.25
        sigma_n = 1.0 / (5.0e-8)  # ρn=5µΩ·cm=5e-8Ω·m → σn=2e7 S/m
        s1 = sigma_n * t**4
        lam = 39.0e-9 / math.sqrt(1.0 - t**4)
        w = 2.0 * math.pi * 5.0e9
        s2 = 1.0 / (_MU0 * w * lam * lam)
        ratio = (s1 / (2.0 * s2)) * w * _MU0 * lam
        # 独立数值锚（本席实测写死）：σ₁/σ₂≈5.331e-5、ratio≈4.1941e-8Ω
        assert s1 / s2 == pytest.approx(5.3310435175e-05, rel=1e-6)
        assert ratio == pytest.approx(4.194093432646011e-08, rel=1e-9)
        assert res["sigma1_over_sigma2"] == pytest.approx(s1 / s2,
                                                          rel=1e-12)
        assert res["lambda_l_t_nm"] == pytest.approx(lam * 1e9, rel=1e-12)
        assert res["sigma2_s_per_m"] == pytest.approx(s2, rel=1e-12)
        # Rs（精确复根）vs 一阶恒等：小比值域余项 O(ε²)≈3e-9
        assert res["rs_ohm"] == pytest.approx(ratio, rel=1e-7)
        assert res["ratio_approx_ohm"] == pytest.approx(ratio, rel=1e-12)
        # Zs 虚部=纯感应主项 ωμ0λ（Re 主项小 4 个量级）
        assert res["zs_imag_ohm"] == pytest.approx(w * _MU0 * lam,
                                                   rel=1e-8)
        assert abs(res["zs_imag_ohm"]) > 1.0e4 * res["rs_ohm"]

    def test_local_limit_f_squared_law(self):
        """局部极限 f² 幂律：f 减半 → Rs×¼（σ₁/σ₂ 同比缩小，余项更小）。"""
        rs_hi = superconductor_rs("Nb", 5.0e9, 4.2)["rs_ohm"]
        rs_lo = superconductor_rs("Nb", 2.5e9, 4.2)["rs_ohm"]
        assert rs_hi / rs_lo == pytest.approx(4.0, rel=1e-6)

    def test_low_temperature_limits(self):
        """t→0⁺：λ_L(T)→λ_L0 逐位退化；σ₁/σn=t⁴ 恒等（t=1e-6）。"""
        res = superconductor_rs("Nb", 1.0e9, 9.25e-6)
        assert res["lambda_l_t_nm"] == pytest.approx(39.0, rel=1e-12)
        t = 9.25e-6 / 9.25
        assert res["sigma1_s_per_m"] == pytest.approx(
            2.0e7 * t**4, rel=1e-9)
        assert res["sigma1_s_per_m"] / res["sigma_n_s_per_m"] == (
            pytest.approx(1.0e-24, rel=1e-6))

    def test_nbtin_material_row_resolution(self):
        """NbTiN 档参数行正确解析（λ_L0=360nm 文献带中心）。"""
        res = superconductor_rs("NbTiN", 5.0e9, 4.2)
        t = 4.2 / 14.5
        assert res["lambda_l0_nm"] == pytest.approx(360.0, rel=1e-15)
        assert res["tc_k"] == pytest.approx(14.5, rel=1e-15)
        assert res["lambda_l_t_nm"] == pytest.approx(
            360.0 / math.sqrt(1.0 - t**4), rel=1e-12)

    def test_domain_rejections(self):
        """正常态/零温/未知材料/非正频率显式拒绝。"""
        with pytest.raises(ValueError, match="T>=Tc"):
            superconductor_rs("Nb", 5.0e9, 9.25)
        with pytest.raises(ValueError, match="t_k 必须 >0"):
            superconductor_rs("Nb", 5.0e9, 0.0)
        with pytest.raises(ValueError, match="material"):
            superconductor_rs("Cu", 5.0e9, 4.2)
        with pytest.raises(ValueError, match="f_hz"):
            superconductor_rs("Nb", -1.0, 4.2)


# ─── superconductor_gap（量子读出域，MP-7）───────────────────────────────────

class TestSuperconductorGap:
    def test_zero_temperature_bcs_constant(self):
        """t=0：Δ0=1.764·k_B·Tc（k_B 走 scipy.constants 独立裁判）。"""
        from scipy import constants

        kb_ev = constants.Boltzmann / constants.elementary_charge
        res = superconductor_gap("Nb", 0.0)
        assert res["delta0_ev"] == pytest.approx(
            1.764 * kb_ev * 9.25, rel=1e-12)
        assert res["delta0_meV"] == pytest.approx(1.406090268361, rel=1e-10)
        assert res["bcs_gap_ratio"] == 1.764

    def test_gl_limit_near_tc(self):
        """t→Tc：Δ(T) 与 GL 极限 1.74Δ0√(1−t) 相对差 <1e-3（tanh 小宗量）。"""
        res = superconductor_gap("Nb", 0.9999 * 9.25)
        assert res["delta_t_ev"] == pytest.approx(
            res["gl_near_tc_ev"], rel=1e-3)
        # GL 字段本身即独立闭式：1.74·Δ0·√(1−t)
        d0 = 1.764 * 8.617333262e-5 * 9.25
        assert res["gl_near_tc_ev"] == pytest.approx(
            1.74 * d0 * math.sqrt(1.0 - 0.9999), rel=1e-12)

    def test_al_table_band_consistency(self):
        """Al Δ0=0.1824meV 与材料表带值 0.182meV 互洽 ≤0.5%（弱耦合
        一致性；NbTiN 强耦合偏离显著=band 注记语义）。"""
        res = superconductor_gap("Al", 0.0)
        assert res["delta0_meV"] == pytest.approx(0.18241171049, rel=1e-9)
        assert abs(res["delta0_meV"] / res["table_delta0_meV"] - 1.0) < 0.005
        res_nbn = superconductor_gap("NbTiN", 0.0)
        # NbTiN 强耦合：比值差记录在 band 注记语义内（不做硬门，只锚
        # 表值透传正确）
        assert res_nbn["table_delta0_meV"] == 2.20

    def test_monotonic_decrease_and_identity(self):
        """Δ(T) 随 T 单调下降；t=0 恒等 Δ0。"""
        res0 = superconductor_gap("Nb", 0.0)
        res_mid = superconductor_gap("Nb", 4.2)
        res_near = superconductor_gap("Nb", 9.0)
        assert res_mid["delta_t_ev"] < res0["delta0_ev"]
        assert res_near["delta_t_ev"] < res_mid["delta_t_ev"]
        assert res_near["delta_t_ev"] > 0.0

    def test_domain_rejections(self):
        """T≥Tc/负温显式拒绝。"""
        with pytest.raises(ValueError, match="T>=Tc"):
            superconductor_gap("NbTiN", 15.0)
        with pytest.raises(ValueError, match="t_k"):
            superconductor_gap("Al", -1.0)
        with pytest.raises(ValueError, match="material"):
            superconductor_gap("YBCO", 77.0)


# ─── antenna_q_yaghjian_best（天线域，T1-A-04）───────────────────────────────

def _series_rlc_z(f_hz: list[float], r_ohm: float, f0_hz: float,
                  q: float) -> list[complex]:
    """串联 RLC 阻抗独立合成（原始构造，不消费键内中间量）。"""
    w0 = 2.0 * math.pi * f0_hz
    l_h = q * r_ohm / w0
    c_f = 1.0 / (w0 * w0 * l_h)
    return [complex(r_ohm,
                    2.0 * math.pi * f * l_h - 1.0 / (2.0 * math.pi * f * c_f))
            for f in f_hz]


def _freq_grid(f0_hz: float, n_half: int = 4,
               step: float = 2e-6) -> list[float]:
    return [f0_hz * (1.0 + k * step) for k in range(-n_half, n_half + 1)]


class TestAntennaQYaghjianBest:
    def test_series_rlc_q_recovery(self):
        """串联 RLC（50Ω/1GHz/Q=40）：q/FBW 机器精度回收。"""
        f0 = 1.0e9
        grid = _freq_grid(f0)
        z = _series_rlc_z(grid, 50.0, f0, 40.0)
        res = antenna_q_yaghjian_best(
            grid, [v.real for v in z], [v.imag for v in z])
        assert res["f0_hz"] == pytest.approx(f0, rel=1e-9)
        assert res["r0_ohm"] == pytest.approx(50.0, rel=1e-12)
        assert res["q"] == pytest.approx(40.0, rel=1e-8)
        assert res["fbw_half_power"] == pytest.approx(0.05, rel=1e-9)
        assert res["fbw_vswr"] == pytest.approx(
            1.0 / (math.sqrt(2.0) * 40.0), rel=1e-9)
        assert res["verdict_chu"] is None  # 未给 ka 不产判定

    def test_gamma_numeric_width_third_method(self):
        """Γ(f) 数值宽度第三方法：X(f)=±2R 二分求根 → FBW 与换算式
        互证（两推导路径独立）。"""
        f0 = 1.0e9
        grid = _freq_grid(f0)
        z = _series_rlc_z(grid, 50.0, f0, 40.0)
        res = antenna_q_yaghjian_best(
            grid, [v.real for v in z], [v.imag for v in z])

        w0 = 2.0 * math.pi * f0
        l_h = 40.0 * 50.0 / w0
        c_f = 1.0 / (w0 * w0 * l_h)

        def x_of(f: float) -> float:
            w = 2.0 * math.pi * f
            return w * l_h - 1.0 / (w * c_f)

        def bisect(g, a: float, b: float) -> float:
            for _ in range(200):
                m = 0.5 * (a + b)
                if g(a) * g(m) <= 0.0:
                    b = m
                else:
                    a = m
            return 0.5 * (a + b)

        f_hi = bisect(lambda f: x_of(f) - 2.0 * 50.0,
                      f0 * 1.005, f0 * 1.05)
        f_lo = bisect(lambda f: x_of(f) + 2.0 * 50.0,
                      f0 * 0.95, f0 * 0.995)
        fbw_num = (f_hi - f_lo) / f0
        assert res["fbw_half_power"] == pytest.approx(fbw_num, rel=1e-6)

    def test_half_power_vswr_self_consistency(self):
        """FBW_hp = FBW_S|_{S=(1+√2)²}（(S−1)/√S=2 恒等）。"""
        f0 = 1.0e9
        grid = _freq_grid(f0)
        z = _series_rlc_z(grid, 50.0, f0, 40.0)
        s_hp = (1.0 + math.sqrt(2.0)) ** 2
        res = antenna_q_yaghjian_best(
            grid, [v.real for v in z], [v.imag for v in z], vswr=s_hp)
        assert res["fbw_vswr"] == pytest.approx(
            res["fbw_half_power"], rel=1e-12)

    def test_chu_verdict_hand_anchor(self):
        """ka=π/2：Q_min=8/π³+2/π=0.8946320478（A-01 勘误后口径）；
        Q=40 → reachable，margin_ratio 手算互证。"""
        f0 = 1.0e9
        grid = _freq_grid(f0)
        z = _series_rlc_z(grid, 50.0, f0, 40.0)
        res = antenna_q_yaghjian_best(
            grid, [v.real for v in z], [v.imag for v in z],
            ka=math.pi / 2)
        assert res["q_min_chu"] == pytest.approx(_Q_MIN_CHU_KA_PI_2,
                                                 rel=1e-12)
        assert res["verdict_chu"] == "reachable"
        assert res["margin_ratio_chu"] == pytest.approx(
            (40.0 - _Q_MIN_CHU_KA_PI_2) / _Q_MIN_CHU_KA_PI_2, rel=1e-9)

    def test_chu_unreachable_low_q(self):
        """Q=0.1 合成 → unreachable（低于无耗下界=物理不可能提示）。"""
        f0 = 1.0e9
        grid = _freq_grid(f0, n_half=8, step=1e-4)
        z = _series_rlc_z(grid, 50.0, f0, 0.1)
        res = antenna_q_yaghjian_best(
            grid, [v.real for v in z], [v.imag for v in z],
            ka=math.pi / 2)
        assert res["q"] == pytest.approx(0.1, rel=1e-6)
        assert res["verdict_chu"] == "unreachable"

    def test_circular_polarization_halving_flips_verdict(self):
        """圆极化界减半判据翻转：Q=0.5 → linear unreachable /
        circular reachable（0.5 高于 0.894632/2=0.4473 的 1.05 倍余量）。"""
        f0 = 1.0e9
        grid = _freq_grid(f0, n_half=8, step=1e-4)
        z = _series_rlc_z(grid, 50.0, f0, 0.5)
        lin = antenna_q_yaghjian_best(
            grid, [v.real for v in z], [v.imag for v in z],
            ka=math.pi / 2, polarization="linear")
        cir = antenna_q_yaghjian_best(
            grid, [v.real for v in z], [v.imag for v in z],
            ka=math.pi / 2, polarization="circular")
        assert lin["verdict_chu"] == "unreachable"
        assert cir["verdict_chu"] == "reachable"
        assert cir["q_min_chu"] == pytest.approx(
            lin["q_min_chu"] / 2.0, rel=1e-12)

    def test_domain_rejections(self):
        """无过零/点数不足/长度失配/R≤0 谐振/坏档显式拒绝。"""
        grid = _freq_grid(1.0e9)
        z = _series_rlc_z(grid, 50.0, 1.0e9, 40.0)
        with pytest.raises(ValueError, match="过零"):
            antenna_q_yaghjian_best(
                grid, [50.0] * 9, [abs(v.imag) + 1.0 for v in z])
        with pytest.raises(ValueError, match="3 个频点"):
            antenna_q_yaghjian_best([1e9, 1.1e9], [50.0, 50.0],
                                    [-1.0, 1.0])
        with pytest.raises(ValueError, match="长度须一致"):
            antenna_q_yaghjian_best(grid, [50.0] * 5, [v.imag for v in z])
        with pytest.raises(ValueError, match="vswr"):
            antenna_q_yaghjian_best(
                grid, [v.real for v in z], [v.imag for v in z], vswr=1.0)
        with pytest.raises(ValueError, match="polarization"):
            antenna_q_yaghjian_best(
                grid, [v.real for v in z], [v.imag for v in z],
                polarization="elliptical")


# ─── weibull_paper_fit（热·功率·可靠性域，XD-15）─────────────────────────────

def _benard(n: int) -> list[float]:
    """Benard 中位秩独立复算（原始构造）。"""
    return [(i - 0.3) / (n + 0.4) for i in range(1, n + 1)]


class TestWeibullPaperFit:
    def test_exact_weibull_quantile_recovery(self):
        """精确 Weibull 分位样本（β=2.5/η=800/n=8）→ β̂/η̂ 机器精度
        回收（残差≈0、r²=1）。"""
        beta, eta = 2.5, 800.0
        n = 8
        times = [eta * (-math.log(1.0 - p)) ** (1.0 / beta)
                 for p in _benard(n)]
        res = weibull_paper_fit(times)
        assert res["n"] == n
        assert res["slope_beta"] == pytest.approx(beta, rel=1e-9)
        assert res["eta_hat"] == pytest.approx(eta, rel=1e-9)
        assert res["r_squared"] == pytest.approx(1.0, abs=1e-12)
        assert res["residual_rms"] <= 1e-9
        assert res["residual_max_abs"] <= 1e-9

    def test_benard_symmetry_identity(self):
        """Benard 对称恒等式 p_i+p_{n+1−i}=1。"""
        res = weibull_paper_fit([100.0, 250.0, 420.0, 700.0, 1100.0,
                                 1800.0])
        p = res["benard_p"]
        assert len(p) == 6
        for i in range(3):
            assert p[i] + p[5 - i] == pytest.approx(1.0, abs=1e-15)
        assert p[0] == pytest.approx(0.7 / 6.4, rel=1e-15)

    def test_two_point_hand_computation(self):
        """n=2 两点手算逐位：slope=(y₂−y₁)/(x₂−x₁)、η̂=exp(−b/m)
        （纯 python 逐标量链，与实现 numpy 向量化不同源）。"""
        res = weibull_paper_fit([100.0, 400.0])
        p1, p2 = 0.7 / 2.4, 1.7 / 2.4
        y1 = math.log(-math.log(1.0 - p1))
        y2 = math.log(-math.log(1.0 - p2))
        x1, x2 = math.log(100.0), math.log(400.0)
        slope = (y2 - y1) / (x2 - x1)
        intercept = y1 - slope * x1
        eta = math.exp(-intercept / slope)
        assert res["slope_beta"] == pytest.approx(
            0.918584714688236, rel=1e-10)
        assert res["slope_beta"] == pytest.approx(slope, rel=1e-12)
        assert res["eta_hat"] == pytest.approx(eta, rel=1e-12)

    def test_exponential_degenerate_beta_one(self):
        """β=1 指数退化：t_i=η(−ln(1−p_i)) → 斜率回收 1。"""
        eta = 500.0
        times = [eta * (-math.log(1.0 - p)) for p in _benard(6)]
        res = weibull_paper_fit(times)
        assert res["slope_beta"] == pytest.approx(1.0, rel=1e-9)
        assert res["eta_hat"] == pytest.approx(eta, rel=1e-9)

    def test_unsorted_input_sorted_equivalence(self):
        """乱序输入自动排序：与升序输入同结果（逐位相等）。"""
        asc = [100.0, 250.0, 420.0, 700.0, 1100.0, 1800.0]
        shuffled = [700.0, 100.0, 1800.0, 420.0, 1100.0, 250.0]
        a = weibull_paper_fit(asc)
        b = weibull_paper_fit(shuffled)
        assert a["slope_beta"] == b["slope_beta"]
        assert a["eta_hat"] == b["eta_hat"]
        assert a["residual_rms"] == b["residual_rms"]
        assert a["benard_p"] == b["benard_p"]

    def test_domain_rejections(self):
        """n=1/含非正值/全同 t（回归退化）显式拒绝。"""
        with pytest.raises(ValueError, match="n≥2"):
            weibull_paper_fit([100.0])
        with pytest.raises(ValueError, match=">0"):
            weibull_paper_fit([100.0, -5.0])
        with pytest.raises(ValueError, match="退化"):
            weibull_paper_fit([100.0, 100.0])
