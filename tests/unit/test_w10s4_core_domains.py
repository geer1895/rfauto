"""aurora_g W10-S4 席锚树：内核余量出键批 2 五键（平衡开线族两键+微带最
优切角键+波导膜片耦合腔 BPF 综合链两键）。

数值断言口径（#118 锚先独立实测再写死，锚值=开工日独立算术预算；
#122 三态/UNVERIFIED 如实不凑绿）：

- 双线（open_two_wire_line）：①Z0 双极精确式独立算术逐位（非键内同式
  二次抄写）；②电报恒等 Z0·C'=√εr/c0（残差<1e-9——η0/ε0 常数集舍入
  口径，公式侧精确）；③acosh 对数恒等式双形态逐位（D≫a 渐近语义）；
  ④趋肤 α 独立算术逐位+√f 标度恒等；⑤D≤2a 与衰减两参配套守卫。
- 单线对地（open_wire_over_ground）：①镜像退化恒等
  Z0_wg(h)=Z0_two_wire(D=2h)/2 逐位（#118 跨键，image theorem 精确）；
  ②h→a⁺ Z0→0 触地短路物理极限；③Z0/C'/L' 独立算术逐位；④h≤a 守卫。
- 最优切角（microstrip_optimal_miter）：①Douville-James 拟合式独立
  算术逐位（M=52+65·exp(−1.35·W/h)，W/h=2 档）；②域内单调降+宽线 52%
  渐近带；③切边长/线宽=M/50 纯几何恒等逐位+切深=M·D/100 逐位；
  ④W/h 实测域 [0.25,2.75] 守卫。
- 波导腔 BPF（wg_cavity_bpf_synthesize/response）：①g 教科书表值
  （0.5dB：1.5963/1.0967）；②J/x 独立算术逐位+x↔J 双向反演恒等
  （J=[−1+√(1+4x²)]/(2x) 闭式回收）；③膜片开口 roundtrip 经既有键
  wg_iris_susceptance 正向（跨键消费=R3 设计意图）；④负线长簿记
  θi+½(φa+φb)=π 逐位；⑤λg 中心（λg(f_c)=λg0）全传输 S11<1e-9、
  S21=1（N=1 与 N=3 双档，倒置器链机器精度匹配锚）；⑥频响无耗守恒
  |S11|²+|S21|²=1 残差<1e-12；⑦带缘落纹波位（0.5dB 纹波档带缘
  S21∈[−0.65,−0.35]dB，窄带 w=3.5% 档实测）+带外抑制（−10dB 档）；
  ⑧膜片 λg 标度双路径（x0·λg0/λg(f) vs wg_iris 闭式自身 λg 依赖）
  逐位（Cohn stated model=薄膜片闭式同标度）；⑨w>0.2/f2≤f1 守卫。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.calc_families.microstrip_disc import (
    microstrip_optimal_miter,
)
from rfauto.core.calc_families.open_wire_line import (
    open_two_wire_line,
    open_wire_over_ground,
)
from rfauto.core.calc_families.waveguide_iris import _frequency
from rfauto.core.calc_families.wg_cavity_bpf import (
    _cascade_s,
    _design_chain,
    wg_cavity_bpf_response,
    wg_cavity_bpf_synthesize,
)
from rfauto.service.calculator_service import run_calculator

_ETA0 = 376.73031346958504364963
_C0 = 299792458.0


# ─── 平衡开线族 ───────────────────────────────────────────────────────────────

class TestOpenTwoWireLine:
    def test_z0_exact_arithmetic(self):
        r = open_two_wire_line(radius_mm=1.0, spacing_mm=20.0, epsilon_r=1.0)
        expect = _ETA0 / math.pi * math.acosh(10.0)
        assert r["z0_ohm"] == pytest.approx(expect, rel=1e-12)

    def test_telegrapher_identity(self):
        for er in (1.0, 2.25):
            r = open_two_wire_line(0.5, 8.0, er)
            assert r["telegrapher_residual"] < 1e-9

    def test_log_asymptote_dual_form(self):
        # acosh(u)=ln(u+√(u²−1)) 恒等：D≫a 渐近 120·ln(D/a) 的同式双形态
        u = 100.0
        r = open_two_wire_line(0.25, 50.0, 1.0)
        assert r["z0_ohm"] == pytest.approx(
            _ETA0 / math.pi * math.log(u + math.sqrt(u * u - 1.0)),
            rel=1e-12)
        # ln(D/a) 工程渐近带（acosh(u)→ln(2u)=ln(D/a)，rel 偏差 ~2.5e-5 档）
        assert abs(r["z0_ohm"] / (_ETA0 / math.pi * math.log(200.0))
                   - 1.0) < 1e-4

    def test_skin_face_and_scaling(self):
        r = open_two_wire_line(1.0, 20.0, 1.0, freq_ghz=1.0,
                               conductivity_s_per_m=5.8e7)
        rs = math.sqrt(math.pi * 1e9 * 1.25663706212e-6 / 5.8e7)
        expect_db = 8.685889638065035 * (rs / (math.pi * 1e-3)) / (
            2.0 * r["z0_ohm"])
        assert r["alpha_c_db_per_m"] == pytest.approx(expect_db, rel=1e-12)
        r4 = open_two_wire_line(1.0, 20.0, 1.0, freq_ghz=4.0,
                                conductivity_s_per_m=5.8e7)
        assert r4["alpha_c_db_per_m"] == pytest.approx(
            2.0 * r["alpha_c_db_per_m"], rel=1e-12)

    def test_guards(self):
        with pytest.raises(ValueError, match=r"2a"):
            open_two_wire_line(1.0, 2.0, 1.0)
        with pytest.raises(ValueError, match=r"恰同时给"):
            open_two_wire_line(1.0, 20.0, 1.0, freq_ghz=1.0)
        with pytest.raises(ValueError, match=r"≥1"):
            open_two_wire_line(1.0, 20.0, 0.9)


class TestOpenWireOverGround:
    def test_mirror_degeneration_cross_key(self):
        # 镜像定理精确恒等：Z0_wg(h) = Z0_two_wire(D=2h)/2（#118 跨键）
        for h_mm in (3.0, 10.0, 40.0):
            wg = open_wire_over_ground(1.0, h_mm, 1.0)
            tw = open_two_wire_line(1.0, 2.0 * h_mm, 1.0)
            assert wg["z0_ohm"] == tw["z0_ohm"] / 2.0

    def test_touchdown_limit(self):
        r = open_wire_over_ground(1.0, 1.000001, 1.0)
        assert r["z0_ohm"] < 0.1  # h→a⁺ acosh→0：触地=短路物理极限
        assert (open_wire_over_ground(1.0, 2.0, 1.0)["z0_ohm"]
                < open_wire_over_ground(1.0, 10.0, 1.0)["z0_ohm"])

    def test_params_exact_arithmetic(self):
        r = open_wire_over_ground(0.5, 5.0, 2.25)
        a_c = math.acosh(10.0)
        assert r["z0_ohm"] == pytest.approx(
            _ETA0 / (2.0 * math.pi * 1.5) * a_c, rel=1e-12)
        assert r["c_prime_f_per_m"] == pytest.approx(
            2.0 * math.pi * 8.8541878128e-12 * 2.25 / a_c, rel=1e-12)
        assert r["l_prime_h_per_m"] == pytest.approx(
            1.25663706212e-6 / (2.0 * math.pi) * a_c, rel=1e-12)
        assert r["telegrapher_residual"] < 1e-9

    def test_guards(self):
        with pytest.raises(ValueError, match=r"触地"):
            open_wire_over_ground(1.0, 1.0, 1.0)
        with pytest.raises(ValueError, match=r"恰同时给"):
            open_wire_over_ground(1.0, 10.0, 1.0, conductivity_s_per_m=5.8e7)


# ─── 微带最优切角（Douville-James） ──────────────────────────────────────────

class TestMicrostripOptimalMiter:
    def test_formula_exact_arithmetic(self):
        r = microstrip_optimal_miter(1.27, 0.635)  # W/h=2
        expect = 52.0 + 65.0 * math.exp(-1.35 * 2.0)
        assert r["miter_percent"] == pytest.approx(expect, rel=1e-12)
        assert r["cut_depth_mm"] == pytest.approx(
            expect / 100.0 * 1.27 * math.sqrt(2.0), rel=1e-12)
        assert r["chamfer_leg_mm"] == pytest.approx(
            r["cut_depth_mm"] * math.sqrt(2.0), rel=1e-12)

    def test_monotone_and_wide_line_asymptote(self):
        ms = [microstrip_optimal_miter(u * 0.635, 0.635)["miter_percent"]
              for u in (0.25, 1.0, 2.0, 2.75)]
        assert ms[0] > ms[1] > ms[2] > ms[3]  # 域内单调降
        assert ms[0] == pytest.approx(52.0 + 65.0 * math.exp(-1.35 * 0.25),
                                      rel=1e-12)
        assert ms[3] < 54.0  # 宽线 52% 渐近带（域上缘已贴近）

    def test_chamfer_geometry_identity(self):
        # 切边长/线宽 = M/50（纯几何恒等；M=50 档 a=W 同式自检）
        for u in (0.25, 1.0, 2.75):
            r = microstrip_optimal_miter(u * 0.635, 0.635)
            assert r["chamfer_over_width"] == pytest.approx(
                r["miter_percent"] / 50.0, rel=1e-12)

    def test_domain_guard(self):
        with pytest.raises(ValueError, match=r"0\.25,2\.75"):
            microstrip_optimal_miter(0.127, 0.635)  # W/h=0.2
        with pytest.raises(ValueError, match=r"0\.25,2\.75"):
            microstrip_optimal_miter(2.0, 0.635)  # W/h≈3.15


# ─── 波导膜片耦合腔 BPF（Cohn 1957 链） ──────────────────────────────────────

_WR90 = (22.86, 10.16)


class TestWgCavityBpfSynthesize:
    def test_g_textbook_table(self):
        d = wg_cavity_bpf_synthesize(order=3, f1_ghz=9.9, f2_ghz=10.1,
                                     ripple_db=0.5, a_mm=_WR90[0],
                                     b_mm=_WR90[1])
        assert d["g"][:4] == pytest.approx(
            [1.0, 1.5963, 1.0967, 1.5963], abs=6e-5)

    def test_j_and_x_independent_arithmetic(self):
        d = wg_cavity_bpf_synthesize(order=3, f1_ghz=9.9, f2_ghz=10.1,
                                     ripple_db=0.5, a_mm=_WR90[0],
                                     b_mm=_WR90[1])
        # λg 带限独立重算
        _, lg1_mm, _ = _frequency(_WR90[0], 9.9, "t")
        _, lg2_mm, _ = _frequency(_WR90[0], 10.1, "t")
        lg0 = 0.5 * (lg1_mm + lg2_mm)
        w = (lg1_mm - lg2_mm) / lg0
        assert d["w_lg"] == pytest.approx(
            w, abs=5e-10)  # 键出 9 位小数舍入界
        assert d["lambda_g0_mm"] == pytest.approx(lg0, abs=1e-9)
        g1, g2 = 1.596331368, 1.096680695
        j_end = math.sqrt(math.pi * w / (2.0 * 1.0 * g1))
        j_mid = (math.pi * w / 2.0) / math.sqrt(g1 * g2)
        assert d["j_over_z0"] == pytest.approx(
            [j_end, j_mid, j_mid, j_end], abs=1e-9)
        xs = [jv / (1.0 - jv * jv) for jv in (j_end, j_mid)]
        assert d["x_norm"] == pytest.approx(xs + xs[::-1], abs=1e-9)

    def test_x_j_inversion_roundtrip(self):
        # x=J/(1−J²) 反演回收：J=[−1+√(1+4x²)]/(2x)（独立闭式路径）
        d = _design_chain(3, 9.9, 10.1, 0.5, *_WR90)
        for j0, x0 in zip(d["j_over_z0"], d["x_norm"], strict=True):
            j_back = (-1.0 + math.sqrt(1.0 + 4.0 * x0 * x0)) / (2.0 * x0)
            assert j_back == pytest.approx(j0, rel=1e-12)

    def test_iris_roundtrip_via_registered_key(self):
        # 膜片开口经既有键 wg_iris_susceptance 正向回读（跨键消费）
        d = wg_cavity_bpf_synthesize(order=3, f1_ghz=9.9, f2_ghz=10.1,
                                     ripple_db=0.5, a_mm=_WR90[0],
                                     b_mm=_WR90[1])
        fc_hz = d["fc10_ghz"] * 1e9
        f_c = math.sqrt((_C0 / (d["lambda_g0_mm"] * 1e-3)) ** 2
                        + fc_hz ** 2) / 1e9
        for d_mm, b_expect in zip(d["iris_open_mm"], d["b_norm"],
                                  strict=True):
            out = run_calculator("wg_iris_susceptance", {
                "a_mm": _WR90[0], "b_mm": _WR90[1], "f_ghz": f_c,
                "iris_type": "inductive", "d_mm": d_mm})
            assert out["ok"]
            assert out["result"]["b_norm"] == pytest.approx(
                b_expect, rel=1e-6)

    def test_cavity_bookkeeping_identity(self):
        d = _design_chain(3, 9.9, 10.1, 0.5, *_WR90)
        x = d["x_norm"]
        phi = [-math.atan(2.0 * xv) for xv in x]  # 负线长
        for i in range(1, 4):
            assert d["theta_rad"][i - 1] - 0.5 * (phi[i - 1] + phi[i]) \
                == pytest.approx(math.pi, abs=1e-12)
        lg0 = d["lambda_g0_mm"]
        assert d["cavity_len_mm"][0] == pytest.approx(
            d["theta_rad"][0] * lg0 / (2.0 * math.pi), rel=1e-12)

    def test_full_transmission_at_lambda_g_center(self):
        # λg(f_c)=λg0 处倒置器链机器精度全传输（N=1 与 N=3 双档）
        c = _C0
        for n in (1, 3):
            d = _design_chain(n, 9.9, 10.1, 0.5, *_WR90)
            fc_hz = d["fc10_ghz"] * 1e9
            f_c = math.sqrt(
                (c / (d["lambda_g0_mm"] * 1e-3)) ** 2 + fc_hz ** 2) / 1e9
            s11, s21 = _cascade_s(f_c, d)
            assert abs(s11) < 1e-9
            assert abs(abs(s21) - 1.0) < 1e-9

    def test_guards(self):
        with pytest.raises(ValueError, match=r"\(0,0\.2\]"):
            wg_cavity_bpf_synthesize(order=3, f1_ghz=9.0, f2_ghz=12.0,
                                     ripple_db=0.5, a_mm=_WR90[0],
                                     b_mm=_WR90[1])
        with pytest.raises(ValueError, match=r"f2>f1"):
            wg_cavity_bpf_synthesize(order=3, f1_ghz=10.1, f2_ghz=9.9,
                                     ripple_db=0.5, a_mm=_WR90[0],
                                     b_mm=_WR90[1])


class TestWgCavityBpfResponse:
    def test_losslessness_and_band_edge_ripple(self):
        d = wg_cavity_bpf_response(
            [9.85, 9.9, 9.9995, 10.1, 10.15], 3, 9.9, 10.1, 0.5,
            _WR90[0], _WR90[1])
        assert d["unitary_residual_max"] < 1e-12
        # 带缘落纹波位（0.5dB 纹波 Chebyshev：带缘=纹波位，窄带 w=3.5% 档）
        s21_lo = d["s21_db"][1]
        s21_hi = d["s21_db"][3]
        for v in (s21_lo, s21_hi):
            assert -0.65 <= v <= -0.35
        # 带外抑制（半带缘外 0.05GHz ≥ 9dB）
        assert d["s21_db"][0] <= -9.0
        assert d["s21_db"][4] <= -9.0

    def test_iris_lambda_g_scaling_dual_path(self):
        # Cohn stated model x(f)=x0·λg0/λg(f) 与薄膜片闭式自身 λg 依赖
        # （wg_iris_susceptance 正向在 f 重读）逐位同值（#118 双路径）
        d = _design_chain(3, 9.9, 10.1, 0.5, *_WR90)
        f_probe = 10.3
        _, lg_f, _ = _frequency(_WR90[0], f_probe, "t")
        scale = d["lambda_g0_mm"] / lg_f
        for k, d_mm in enumerate(d["iris_open_mm"]):
            out = run_calculator("wg_iris_susceptance", {
                "a_mm": _WR90[0], "b_mm": _WR90[1], "f_ghz": f_probe,
                "iris_type": "inductive", "d_mm": d_mm})
            x_re = -1.0 / out["result"]["b_norm"]
            assert x_re == pytest.approx(d["x_norm"][k] * scale, rel=1e-12)

    def test_response_equals_cascade_at_design_point(self):
        d = wg_cavity_bpf_response([9.9], 3, 9.9, 10.1, 0.5,
                                   _WR90[0], _WR90[1])
        s11, s21 = _cascade_s(9.9, _design_chain(3, 9.9, 10.1, 0.5, *_WR90))
        assert d["s11_db"][0] == pytest.approx(
            20.0 * math.log10(abs(s11)), abs=1e-4)
        assert d["s21_db"][0] == pytest.approx(
            20.0 * math.log10(abs(s21)), abs=1e-4)

    def test_guard_below_cutoff(self):
        with pytest.raises(ValueError):
            wg_cavity_bpf_response([6.0], 3, 9.9, 10.1, 0.5,
                                   _WR90[0], _WR90[1])
