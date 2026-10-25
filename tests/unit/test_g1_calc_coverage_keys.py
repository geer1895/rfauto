"""aurora_l G1 教科书覆盖缺口六键锚树（2026-10-23）。

六键：line_input_impedance / stub_tuner_single / butterworth_prototype /
branchline_coupler_design / leeson_phase_noise / twoport_matrix_convert。

裁判口径（#118 不自证 / #340 合成回收家法）：
- 教科书表值锚（Butterworth g 值、3dB 分支线臂阻抗、r=2 Smith 图经典
  档、Leeson 热噪地板恒等式）——与注册键不同代数路径的独立常数；
- 双路径互证锚（Γ_in 相位旋转 vs (Zin−Z0)/(Zin+Z0)、梯形 ABCD vs
  10lg(1+ω^{2n}) 多项式、λ/4 线正反往返）——构造级恒等式；
- 合成回收钉（随机负载 ABCD 回代 |Γ_in|→0、随机互易网络表示往返）；
- 闭式推导链 内部证据档（一次性探针，账面留痕）。

三禁遵守：不 commit、不写账本、不跑全量门（定向文件清单见交付报告）。
"""

from __future__ import annotations

import cmath
import math
from typing import Any

import pytest

from rfauto.core.calc_families.branchline_coupler import (
    branchline_coupler_design,
)
from rfauto.core.calc_families.filter_prototype import (
    butterworth_prototype,
    g_maxflat,
)
from rfauto.core.calc_families.network_convert import twoport_matrix_convert
from rfauto.core.calc_families.oscillator_leeson import leeson_phase_noise
from rfauto.core.calc_families.registry import CALCULATOR_REGISTRY
from rfauto.core.calc_families.stub_tuner import stub_tuner_single
from rfauto.core.calc_families.terminated_line import line_input_impedance

Z0 = 50.0


def _cx(pair: list[float]) -> complex:
    return complex(pair[0], pair[1])


# ─── 键 1：line_input_impedance ──────────────────────────────────────────

class TestLineInputImpedance:
    def test_quarter_wave_inverts(self) -> None:
        """θ=90° → Zin=Z0²/Z_L（教科书极限锚）。"""
        zl = complex(100.0, 30.0)
        out = line_input_impedance(100.0, 30.0, 90.0)
        assert abs(_cx(out["z_in"]) - Z0**2 / zl) < 1e-9 * abs(Z0**2 / zl)

    def test_half_wave_recovers_load(self) -> None:
        out = line_input_impedance(100.0, 30.0, 180.0)
        assert abs(_cx(out["z_in"]) - complex(100.0, 30.0)) < 1e-6

    def test_short_line_is_jz0_tan(self) -> None:
        out = line_input_impedance(0.0, 0.0, 22.5)
        expect = 1j * Z0 * math.tan(math.radians(22.5))
        assert abs(_cx(out["z_in"]) - expect) < 1e-9

    def test_matched_load_invariant(self) -> None:
        out = line_input_impedance(50.0, 0.0, 37.7)
        assert abs(_cx(out["z_in"]) - Z0) < 1e-9
        assert out["vswr"] == 1.0

    def test_gamma_phase_rotation_identity(self) -> None:
        """Γ_in=Γ_L·e^{−j2θ} 与 (Zin−Z0)/(Zin+Z0) 双路径恒等（构造级）。"""
        theta = 71.3
        out = line_input_impedance(30.0, -80.0, theta)
        assert out["gamma_phase_rotation_identity_rel_dev"] < 1e-12
        g_l = (complex(30.0, -80.0) - Z0) / (complex(30.0, -80.0) + Z0)
        g_in = _cx(out["gamma_in"])
        # Γ_in=Γ_L·e^{−j2θ}：模不变+相位旋转（分别断言）
        assert abs(abs(g_in) - abs(g_l)) < 1e-12
        rot = g_in / g_l
        assert abs(rot - cmath.exp(-2j * math.radians(theta))) < 1e-9

    def test_pure_reactive_vswr_null_and_active_rejected(self) -> None:
        out = line_input_impedance(0.0, 20.0, 30.0)
        assert out["vswr"] is None and out["return_loss_db"] is None
        with pytest.raises(ValueError):
            line_input_impedance(-5.0, 0.0, 30.0)

    def test_random_recovery_round_trip(self) -> None:
        """随机负载：λ/4 正变换→以 Zin 为新负载反解，回收原负载（合成回收
        钉——反演 Z_L=Z0(Zin−jZ0tanθ)/(Z0−jZin·tanθ) 独立代数路径）。"""
        rng_vals = [(11.0, 3.0), (97.0, -42.0), (5.0, 120.0), (143.0, 0.0)]
        for rl, xl in rng_vals:
            out = line_input_impedance(rl, xl, 41.0)
            zin = _cx(out["z_in"])
            th = math.radians(41.0)
            zl_back = Z0 * (zin - 1j * Z0 * math.tan(th)) / (
                Z0 - 1j * zin * math.tan(th))
            assert abs(zl_back - complex(rl, xl)) < 1e-6 * max(
                1.0, abs(complex(rl, xl)))


# ─── 键 2：stub_tuner_single ─────────────────────────────────────────────

class TestStubTunerSingle:
    def test_r2_classic_smith_chart_solution(self) -> None:
        """z_L=2（r=100Ω@50Ω）经典档：d=0.152λ（54.736°）+开路支节
        0.402λ（144.736°）；第二解 0.348λ/0.098λ（双解如实并列）。"""
        out = stub_tuner_single(100.0, 0.0)
        assert out["solvable"] and out["matched"]
        sols = {s["theta1_over_lambda"]: s for s in out["solutions"]}
        assert abs(min(sols) - 0.152044) < 1e-4
        near = sols[min(sols)]
        assert abs(near["stub_len_over_lambda"] - 0.402044) < 1e-4
        assert abs(abs(near["b_stub_norm"]) - 1 / math.sqrt(2)) < 1e-9
        assert near["nearest_180"] is True
        assert out["gamma_in_abs"] < 1e-9

    def test_discriminant_always_nonnegative(self) -> None:
        """判别式=g[b²+(g−1)²]≥0：任意无源负载恒有双解（单支节无禁区，
        与双支节 csc²(βd) 禁区成族对照）。"""
        cases = [(10.0, 10.0), (5.0, -200.0), (300.0, 150.0)]
        for rl, xl in cases:
            for st in ("open", "short"):
                out = stub_tuner_single(rl, xl, 50.0, st)
                assert out["solvable"] and out["n_solutions"] == 2
                assert out["matched"]
                assert out["gamma_in_abs"] < 1e-9

    def test_unit_circle_degenerate_single_solution(self) -> None:
        """|z_L|=Z0 退化族（A=b²+g²−g≡0 数学精确）：单有限根+无限远处
        根非解——n_solutions=1 如实（50−0.5j 名义档）。"""
        out = stub_tuner_single(50.0, -0.5)
        assert out["solvable"] and out["matched"]
        assert out["n_solutions"] == 1
        assert out["gamma_in_abs"] == 0.0

    def test_degenerate_unit_circle_load(self) -> None:
        """|z_L|=1 负载（A=0 退化档）：g²+b²=g，线性根路径。"""
        # z_L=1+j0 → g=1,b=0 已匹配平凡解
        out = stub_tuner_single(50.0, 0.0)
        assert out["solvable"] and out["solutions"][0]["b_stub_norm"] == 0.0

    def test_guards(self) -> None:
        with pytest.raises(ValueError):
            stub_tuner_single(0.0, 60.0)
        with pytest.raises(ValueError):
            stub_tuner_single(100.0, 0.0, 0.0)
        with pytest.raises(ValueError):
            stub_tuner_single(100.0, 0.0, 50.0, "series")


# ─── 键 3：butterworth_prototype ─────────────────────────────────────────

class TestButterworthPrototype:
    @pytest.mark.parametrize("n, ref", [
        (2, [1.4142, 1.4142]),
        (3, [1.0, 2.0, 1.0]),
        (4, [0.7654, 1.8478, 1.8478, 0.7654]),
        (5, [0.6180, 1.6180, 2.0000, 1.6180, 0.6180]),
        (7, [0.4450, 1.2470, 1.8019, 2.0000, 1.8019, 1.2470, 0.4450]),
    ])
    def test_pozar_table83_values(self, n: int, ref: list[float]) -> None:
        """g_k=2sin[(2k−1)π/2n] 闭式 = 教科书表值（Pozar Table 8.3 最平坦
        列独立常数锚）。"""
        body = g_maxflat(n)[1:-1]
        assert max(abs(a - b) for a, b in zip(body, ref, strict=True)) < 1e-3
        out = butterworth_prototype(order=n)
        assert out["g0"] == 1.0 and out["g_n_plus_1"] == 1.0
        assert abs(out["s21_at_band_edge_db"] + 3.0103) < 1e-3

    def test_order_estimation_self_consistent(self) -> None:
        """RL=0.5dB/RS=30dB@ωs=2 → n=7、ωc=1.1621、ωs 处 −33.01dB；
        梯形 ABCD 与 10lg(1+ω^{2n}) 多项式双路径同值（独立代数路径）。"""
        out = butterworth_prototype(order=None, rl_db=0.5, rs_db=30.0,
                                    omega_s=2.0)
        assert out["order"] == 7
        assert abs(out["cutoff_omega_c"] - 1.1621) < 1e-3
        assert out["stopband_atten_db"] <= -30.0
        assert abs(out["stopband_atten_db"]
                   - out["stopband_poly_db"]) < 1e-6

    def test_rl_above_3db_no_predistortion(self) -> None:
        out = butterworth_prototype(order=None, rl_db=3.5, rs_db=30.0,
                                    omega_s=2.0)
        assert out["cutoff_omega_c"] is None
        assert out["stopband_atten_db"] <= -30.0

    def test_guards(self) -> None:
        for kwargs in ({"order": 0}, {"order": 32}, {"order": None},
                       {"order": None, "rl_db": -1.0, "rs_db": 30.0,
                        "omega_s": 2.0},
                       {"order": None, "rl_db": 0.5, "rs_db": 0.2,
                        "omega_s": 2.0},
                       {"order": None, "rl_db": 0.5, "rs_db": 30.0,
                        "omega_s": 0.5}):
            with pytest.raises(ValueError):
                butterworth_prototype(**kwargs)


# ─── 键 4：branchline_coupler_design ─────────────────────────────────────

class TestBranchlineCouplerDesign:
    def test_3db_textbook_arms(self) -> None:
        """3dB：串联臂 Z0/√2、并联臂 Z0（教科书经典值；与模板级
        synthesize_branchline 的 35.35/50Ω 同值互证）。"""
        out = branchline_coupler_design()
        assert abs(out["series_arm_z_ohm"] - Z0 / math.sqrt(2)) < 1e-9
        assert abs(out["shunt_arm_z_ohm"] - Z0) < 1e-9
        assert out["arm_theta_deg"] == 90.0
        assert abs(out["through_db"] - 3.010299957) < 1e-6
        assert abs(out["coupled_db"] - 3.010299957) < 1e-6

    def test_3db_ideal_s_matrix_pattern(self) -> None:
        """S21=−j/√2（直通 −90°）、S31=−1/√2（耦合 180°）、S14=0；
        幺正性/互易性构造级。"""
        out = branchline_coupler_design()
        flat = out["s_matrix"]
        s_mat = [[_cx(flat[4 * i + j]) for j in range(4)] for i in range(4)]
        assert abs(s_mat[0][1] + 1j / math.sqrt(2)) < 1e-12
        assert abs(s_mat[0][2] + 1 / math.sqrt(2)) < 1e-12
        assert abs(s_mat[0][3]) < 1e-12
        assert abs(s_mat[0][0]) < 1e-12
        assert abs(s_mat[1][2]) < 1e-12  # 直通/耦合两输出互相隔离
        assert abs(s_mat[1][3] + 1 / math.sqrt(2)) < 1e-12  # 2-4 对角耦合
        # 幺正/互易主判=键内未舍入场（unitarity_max_dev）；12 位舍入输出
        # 重构残差地板 ~1e-12，放宽到 1e-11 只作输出契约自洽
        assert out["unitarity_max_dev"] < 1e-14
        assert out["reciprocity_max_dev"] < 1e-14
        for i in range(4):
            for j in range(4):
                col = sum(s_mat[k][i].conjugate() * s_mat[k][j]
                          for k in range(4))
                expect = 1.0 if i == j else 0.0
                assert abs(col - expect) < 1e-11
                assert abs(s_mat[i][j] - s_mat[j][i]) < 1e-11

    @pytest.mark.parametrize("c_v", [0.3, 0.5, 0.9, 0.99])
    def test_general_coupling_closed_form(self, c_v: float) -> None:
        """一般耦合闭式 Z1=c·Z0、Z2=Z0·c/√(1−c²)：|S21|=c、|S31|=√(1−c²)、
        匹配+隔离机器精度（fsolve 四组独立数值解互证的家法落盘）。"""
        out = branchline_coupler_design(coupling_c=c_v)
        assert abs(out["series_arm_z_ohm"] - c_v * Z0) < 1e-9
        assert abs(out["shunt_arm_z_ohm"]
                   - Z0 * c_v / math.sqrt(1 - c_v * c_v)) < 1e-9
        assert abs(out["matched_residual"]) < 1e-12
        assert abs(out["isolated_residual"]) < 1e-12
        assert out["unitarity_max_dev"] < 1e-12
        assert abs(out["through_db"] + 20.0 * math.log10(c_v)) < 1e-9
        assert abs(out["coupled_db"]
                   + 10.0 * math.log10(1.0 - c_v * c_v)) < 1e-9

    def test_guards(self) -> None:
        for bad in (0.0, 1.0, -0.5, True):
            with pytest.raises(ValueError):
                branchline_coupler_design(coupling_c=bad)
        with pytest.raises(ValueError):
            branchline_coupler_design(z0_ohm=0.0)


# ─── 键 5：leeson_phase_noise ────────────────────────────────────────────

class TestLeesonPhaseNoise:
    def test_thermal_floor_identity(self) -> None:
        """NF=0/Ps=0dBm/T=290K 的平地板=10lg(kT/2mW)=−176.985 dBc/Hz
        （经典 −174+3 恒等式，独立常数锚）。"""
        floor_identity = 10.0 * math.log10(1.380649e-23 * 290.0 / 2e-3)
        out = leeson_phase_noise(1e12, 1e10, 50.0, 0.0)
        assert abs(out["floor_dbc_hz"] - floor_identity) < 1e-9
        assert abs(out["l_dbc_hz"] - floor_identity) < 1e-3  # res 残留档
        assert out["region"] == "thermal_floor"

    def test_half_power_point_plus_3db(self) -> None:
        """f_m=f0/(2Q_L) → 谐振项恰 +3.01dB。"""
        out = leeson_phase_noise(1e8, 1e10, 50.0, 1e3)
        assert abs(out["l_dbc_hz"] - out["floor_dbc_hz"] - 3.0103) < 1e-3
        assert abs(out["half_power_offset_hz"] - 1e8) < 1e-3

    def test_flicker_and_resonance_slopes(self) -> None:
        """flicker 项 10×→+10dB；谐振区 decade→+20dB/dec（斜率档位级）。"""
        va = leeson_phase_noise(1e7 / 99, 1e10, 1e9, 1e7)
        vb = leeson_phase_noise(1e7 / 9, 1e10, 1e9, 1e7)
        assert abs((va["l_dbc_hz"] - vb["l_dbc_hz"]) - 10.0) < 1e-6
        v1 = leeson_phase_noise(1e6, 1e10, 50.0, 0.0)
        v2 = leeson_phase_noise(1e5, 1e10, 50.0, 0.0)
        assert abs((v2["l_dbc_hz"] - v1["l_dbc_hz"]) - 20.0) < 0.01
        assert v2["region"] == "resonance"

    def test_nf_and_power_offsets(self) -> None:
        """NF=+3dB→+3dB；Ps×10→−10dB（定义级恒等）。"""
        base = leeson_phase_noise(1e6, 1e10, 1e5, 1e3, 0.0, 0.0)
        with_nf = leeson_phase_noise(1e6, 1e10, 1e5, 1e3, 3.0, 0.0)
        with_p = leeson_phase_noise(1e6, 1e10, 1e5, 1e3, 0.0, 10.0)
        assert abs((with_nf["l_dbc_hz"] - base["l_dbc_hz"]) - 3.0) < 1e-9
        assert abs((with_p["l_dbc_hz"] - base["l_dbc_hz"]) + 10.0) < 1e-9

    def test_guards(self) -> None:
        bad_cases: list[dict[str, Any]] = [
            {"f_offset_hz": 0.0, "f0_hz": 1e10, "q_loaded": 50.0},
            {"f_offset_hz": 1e6, "f0_hz": -1.0, "q_loaded": 50.0},
            {"f_offset_hz": 1e6, "f0_hz": 1e10, "q_loaded": 0.0},
            {"f_offset_hz": 1e6, "f0_hz": 1e10, "q_loaded": 50.0,
             "nf_db": -3.0},
            {"f_offset_hz": 1e6, "f0_hz": 1e10, "q_loaded": 50.0,
             "t_kelvin": 0.0},
        ]
        for kwargs in bad_cases:
            with pytest.raises(ValueError):
                leeson_phase_noise(**kwargs)


# ─── 键 6：twoport_matrix_convert ────────────────────────────────────────

def _abcd(name: str) -> list[list[list[float]]]:
    if name == "lambda4":  # λ/4 50Ω 线：[0 jZ0; j/Z0 0]
        return [[[0.0, 0.0], [0.0, 50.0]], [[0.0, 0.02], [0.0, 0.0]]]
    if name == "series":  # 串联 30+j10
        return [[[1.0, 0.0], [30.0, 10.0]], [[0.0, 0.0], [1.0, 0.0]]]
    if name == "pi_net":  # Π：Y=[[0.04,−0.02],[−0.02,0.02]]
        return [[[0.04, 0.0], [-0.02, 0.0]], [[-0.02, 0.0], [0.02, 0.0]]]
    raise AssertionError(name)


def _mat_diff(a: list, b: list) -> float:
    return max(abs(_cx(x) - _cx(y)) for ra, rb in zip(a, b, strict=True)
               for x, y in zip(ra, rb, strict=True))


class TestTwoportMatrixConvert:
    def test_lambda4_line_from_abcd(self) -> None:
        """λ/4 50Ω 线：S11=S22=0、S21=S12=−j、det(ABCD)=1、互易。"""
        out = twoport_matrix_convert(_abcd("lambda4"), "ABCD")
        s_mat = out["s_matrix"]
        assert abs(_cx(s_mat[0][0])) < 1e-12
        assert abs(_cx(s_mat[1][0]) + 1j) < 1e-9
        assert abs(_cx(s_mat[0][1]) + 1j) < 1e-9
        assert out["det_abcd_unit"] and out["reciprocal_sst"]
        assert out["z_matrix"] is not None and out["y_matrix"] is not None

    def test_series_element_closed_forms(self) -> None:
        """串联 z=30+j10：S11=z/(2Z0+z)、S21=2Z0/(2Z0+z)；Y=[[1/z,−1/z],
        [−1/z,1/z]] 闭式；Z 表示天然奇异→如实 null+原因。"""
        z_el = complex(30.0, 10.0)
        out = twoport_matrix_convert(_abcd("series"), "ABCD")
        den = 2 * Z0 + z_el
        assert abs(_cx(out["s_matrix"][0][0]) - z_el / den) < 1e-12
        assert abs(_cx(out["s_matrix"][1][0]) - 2 * Z0 / den) < 1e-12
        assert out["z_matrix"] is None
        assert out["missing_representations"]
        y_mat = out["y_matrix"]
        assert abs(_cx(y_mat[0][0]) - 1 / z_el) < 1e-9
        assert abs(_cx(y_mat[0][1]) + 1 / z_el) < 1e-9
        # S→ABCD 回收串联 z（合成回收钉）
        back = twoport_matrix_convert(out["s_matrix"], "S")
        assert abs(_cx(back["abcd_matrix"][0][1]) - z_el) < 1e-9

    def test_pi_network_abcd_y_agreement(self) -> None:
        """Π 网络（shunt 50Ω+series 50Ω）：Y 输入 S11=−0.2（ABCD 独立
        手算路径锚 2/5 值域）；三表示往返 ≤1e-9。"""
        out = twoport_matrix_convert(_abcd("pi_net"), "Y")
        assert abs(_cx(out["s_matrix"][0][0]) + 0.2) < 1e-9
        assert abs(_cx(out["s_matrix"][1][0]) - 0.4) < 1e-9
        for rep in ("s_matrix", "abcd_matrix"):
            back = twoport_matrix_convert(out[rep],
                                          "S" if rep == "s_matrix" else "ABCD")
            assert _mat_diff(out["y_matrix"], back["y_matrix"]) < 1e-9

    def test_lossy_reciprocal_round_trips(self) -> None:
        """有耗互易网络 Z 表示 → S/Y/ABCD 三路往返回收（≤1e-8）。"""
        z_in = [[[80.0, 3.0], [10.0, 4.0]], [[10.0, 4.0], [95.0, -2.0]]]
        out = twoport_matrix_convert(z_in, "Z")
        for rep, ftype in (("s_matrix", "S"), ("y_matrix", "Y"),
                           ("abcd_matrix", "ABCD")):
            back = twoport_matrix_convert(out[rep], ftype)
            assert _mat_diff(out["z_matrix"], back["z_matrix"]) < 1e-8

    def test_one_port_limits(self) -> None:
        """1 端口极限口径：Γ=−1（短路）→Z=0；Γ=0（匹配）→Z=Z0（对角
        单口自证同族恒等）。"""
        short = twoport_matrix_convert([[[-1.0, 0.0], [0.0, 0.0]],
                                        [[0.0, 0.0], [0.0, 0.0]]], "S")
        assert abs(_cx(short["z_matrix"][0][0])) < 1e-9
        matched = twoport_matrix_convert([[[0.0, 0.0], [0.0, 0.0]],
                                          [[0.0, 0.0], [0.0, 0.0]]], "S")
        assert abs(_cx(matched["z_matrix"][0][0]) - Z0) < 1e-9

    def test_guards(self) -> None:
        with pytest.raises(ValueError):
            twoport_matrix_convert([[[1.0, 2.0]]], "S")
        with pytest.raises(ValueError):
            twoport_matrix_convert(_abcd("lambda4"), "Q")
        with pytest.raises(ValueError):
            twoport_matrix_convert(_abcd("lambda4"), "S", 0.0)
        # S21=0：ABCD 表示缺席（1/S21 奇异）→如实 null+原因，主表示恒在
        out = twoport_matrix_convert([[[0.0, 0.0], [1.0, 0.0]],
                                      [[0.0, 0.0], [0.0, 0.0]]], "S")
        assert out["s_matrix"] is not None
        assert out["abcd_matrix"] is None
        assert any(m.startswith("ABCD") for m in out["missing_representations"])


# ─── 注册面一致性（与 registry/EXPECTED 解耦的本地自检）──────────────────

def test_six_keys_registered_with_groups() -> None:
    expected_groups = {
        "line_input_impedance": "传输线正反解",
        "stub_tuner_single": "匹配·功分·衰减·耦合",
        "butterworth_prototype": "滤波器与耦合矩阵",
        "branchline_coupler_design": "匹配·功分·衰减·耦合",
        "leeson_phase_noise": "收发链路·频综",
        "twoport_matrix_convert": "测量与校准",
    }
    for name, group in expected_groups.items():
        spec = CALCULATOR_REGISTRY.get(name)
        assert spec is not None
        assert spec.reciprocal is True
        assert CALCULATOR_REGISTRY.describe.__self__ is CALCULATOR_REGISTRY
        rows = {r["name"]: r["group"]
                for r in CALCULATOR_REGISTRY.describe()}
        assert rows[name] == group
