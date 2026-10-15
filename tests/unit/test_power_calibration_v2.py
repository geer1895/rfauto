"""SB22-MS-1 v2 缆 S 参数级联失配定向门（SB22-RES 席，2026-10-13）。

v1 诚实边界①（缆自身 S 参数级联失配，Γ_s 随缆变换）闭合批。钉五类：
  1. 极限恒等——无损直通缆逐位退化回 v1 exact（缆=单位算子时两链同值）；
  2. 回收钉（#118 双裁判）——正向真值经**测试内独立波方程解算**（不复用
     内核级联式）产出功率计读数，v2 反演恢复真值残差 ≤1e-10 dB；
  3. 文献/教科书锚——10 dB 衰减器把负载反射在源平面削减恰 20 dB
     （|Γ_in|=|S12S21|·|Γ_l|，微波计量"垫整失配"惯用规则）；无损线
     闭式（Γ_in=Γ_l·e^{−2jβl}，Pozar §2.3 波分解逐项对拍）；
  4. band 精确最坏区间——500 相位随机扫，exact 恒落
     [point+20lg(1−ρ), point+20lg(1+ρ)] 内（对称 ±MU 下侧欠覆盖已由
     本扫证伪并改用精确区间，#122 如实声明）；
  5. 守卫——非 2×2/|S|>1/S21=0/未知模式/逐项有界但非无源矩阵
     （|Sij|≤1 不保证网络无源，|Γ_in|≥1 显式拒绝）。
v1 注册键面不动（test_power_calibration.py 25 例回归绿=缺省路径零漂移）。
"""

from __future__ import annotations

import cmath
import json
import math
import random

import pytest

from rfauto.core.power_calibration import (
    cable_input_gamma,
    calibrate_power_chain,
    calibrate_power_chain_sparams,
    cascade_transducer_gain_db,
    gamma_at_load_plane,
)

# 名义设计点（与 v1 测试同族量级：|Γs|=0.2，|Γl|≈0.111）
_GS = complex(0.17320508, 0.1)
_GL = complex(0.07856605, -0.07856605)

# 随机无源（逐项有界）缆：小反射+主传输项
_S_RAND = [[0.1 * cmath.exp(0.2j), 0.9 * cmath.exp(-0.5j)],
           [0.9 * cmath.exp(-0.5j), 0.12 * cmath.exp(0.9j)]]


def _wave_solve_read_dbm(p_avs_dbm: float, s_params, gs: complex,
                         gl: complex, eta: float) -> float:
    """独立波方程正向解算（测试内 #118 裁判路径，不复用内核级联式）。

    源波幅 |a_s|²=P_avs·(1−|Γ_s|²)；a1=a_s/(1−Γ_s·Γ_in)；
    b2=S21·a1/(1−S22·Γ_l)；P_del=|b2|²(1−|Γ_l|²)；读数=η·P_del。
    """
    (s11, s12), (s21, s22) = s_params
    g_in = s11 + s12 * s21 * gl / (1.0 - s22 * gl)
    p_avs_mw = 10.0 ** (p_avs_dbm / 10.0)
    a_s = math.sqrt(p_avs_mw * (1.0 - abs(gs) ** 2))
    a1 = a_s / (1.0 - gs * g_in)
    b2 = s21 * a1 / (1.0 - s22 * gl)
    p_del = abs(b2) ** 2 * (1.0 - abs(gl) ** 2)
    return 10.0 * math.log10(p_del * eta)


# ─── 极限恒等：退化回 v1 ─────────────────────────────────────────────────────


class TestDegenerateLimits:
    def test_through_line_matches_v1_bitwise(self):
        """无损直通缆（S11=S22=0, S12=S21=1）→ v2 exact 逐位 = v1 exact。"""
        through = [[0j, 1 + 0j], [1 + 0j, 0j]]
        v2 = calibrate_power_chain_sparams(
            -10.0, 0.9405, through, _GS, _GL, mismatch_mode="exact")
        v1 = calibrate_power_chain(
            -10.0, 0.9405, 0.0, gamma_source=_GS, gamma_load=_GL,
            mismatch_mode="exact")
        assert v2["p_available_dbm"] == v1["p_available_dbm"]

    def test_through_line_gamma_in_is_line_rotated_load(self):
        """直通缆 Γ_in=Γ_l（零长）且 Γ_out=Γ_s（对称口径退化为直通）。"""
        through = [[0j, 1 + 0j], [1 + 0j, 0j]]
        assert cable_input_gamma(through, _GL) == _GL
        assert gamma_at_load_plane(through, _GS) == _GS

    def test_matched_pad_insertion_only(self):
        """理想 6.0206 dB 衰减器+匹配负载（Γ_l=0）→ 补偿恰=插损
        （源交互项 |1−Γ_in·Γ_s|=|1−0|=1 消失：源平面看匹配）。"""
        r = 10.0 ** (-6.0206 / 20.0)
        pad = [[0j, r + 0j], [r + 0j, 0j]]
        out = calibrate_power_chain_sparams(
            -10.0, 1.0, pad, _GS, 0j, mismatch_mode="exact")
        delta = (out["p_available_dbm"]
                 - out["source_match_correction_db"] - (-10.0))
        assert delta == pytest.approx(6.0206, abs=1e-9)

    def test_transducer_gain_matches_insertion_at_matched_ends(self):
        """双端匹配 → G_T=|S21|²（Pozar §12.28 匹配极限）。"""
        pad = [[0j, 0.5 + 0j], [0.5 + 0j, 0j]]
        assert cascade_transducer_gain_db(pad, 0j, 0j) == pytest.approx(
            20.0 * math.log10(0.5), rel=1e-12)


# ─── 回收钉（#118：独立波解算 → 反演恢复真值）────────────────────────────────


class TestRecycleIndependent:
    def test_recycle_recovers_truth_through_random_cable(self):
        """随机无源缆：波解算造读数 → v2 exact 恢复真值，残差 ≤1e-10 dB。"""
        truth = -4.7
        reading = _wave_solve_read_dbm(truth, _S_RAND, _GS, _GL, eta=0.95)
        k_cal = 0.95 * (1.0 - abs(_GL) ** 2)
        out = calibrate_power_chain_sparams(
            reading, k_cal, _S_RAND, _GS, _GL, mismatch_mode="exact")
        assert out["p_available_dbm"] == pytest.approx(truth, abs=1e-10)

    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_recycle_grid_random_cable_load(self, seed):
        """多设计点回收（随机缆/负载/真值网格）：残差全 ≤1e-9 dB。"""
        rng = random.Random(seed)
        for _ in range(20):
            s11 = 0.15 * cmath.exp(1j * rng.uniform(0, 2 * math.pi))
            s22 = 0.15 * cmath.exp(1j * rng.uniform(0, 2 * math.pi))
            s21 = 10 ** (-rng.uniform(0.05, 2.0) / 20.0) * cmath.exp(
                1j * rng.uniform(0, 2 * math.pi))
            s12 = s21  # 互易惯例
            smat = [[s11, s12], [s21, s22]]
            gs = rng.uniform(0.05, 0.4) * cmath.exp(
                1j * rng.uniform(0, 2 * math.pi))
            gl = rng.uniform(0.05, 0.4) * cmath.exp(
                1j * rng.uniform(0, 2 * math.pi))
            truth = rng.uniform(-20.0, 0.0)
            reading = _wave_solve_read_dbm(truth, smat, gs, gl, eta=0.9)
            k_cal = 0.9 * (1.0 - abs(gl) ** 2)
            out = calibrate_power_chain_sparams(
                reading, k_cal, smat, gs, gl, mismatch_mode="exact")
            assert out["p_available_dbm"] == pytest.approx(
                truth, abs=1e-9)


# ─── 文献/教科书锚 ───────────────────────────────────────────────────────────


class TestLiteratureAnchors:
    def test_pad_reduces_load_reflection_by_20db(self):
        """10 dB 衰减器把负载反射在源平面削减恰 20 dB：
        |Γ_in|=|S12·S21|·|Γ_l|=0.1·|Γ_l|（微波计量"垫整失配"规则）。"""
        r = 10.0 ** (-10.0 / 20.0)
        pad = [[0j, r + 0j], [r + 0j, 0j]]
        gl = 0.5 * cmath.exp(0.3j)
        g_in = cable_input_gamma(pad, gl)
        assert abs(g_in) == pytest.approx(0.1 * abs(gl), rel=1e-12)

    def test_lossless_line_closed_form_rotation(self):
        """无损线 S=[[0,e^{-jβl}],[e^{-jβl},0]]：Γ_in=Γ_l·e^{−2jβl}
        （Pozar §2.3 波分解），v2 输出与手推闭式逐项一致。"""
        beta_l = 0.7  # 电长度 rad
        line = [[0j, cmath.exp(-1j * beta_l)], [cmath.exp(-1j * beta_l), 0j]]
        g_in = cable_input_gamma(line, _GL)
        assert g_in == pytest.approx(_GL * cmath.exp(-2j * beta_l),
                                     abs=1e-14)
        out = calibrate_power_chain_sparams(
            -12.0, 0.95, line, _GS, _GL, mismatch_mode="exact")
        # 手推（K_b<1 → 补偿为正，与 v1 同号）：P_avs = P_read −10lg K_b
        #   + src_corr(Γ_s) + 20lg|1−Γ_s·Γ_l·e^{−2jβl}|
        expect = (-12.0 - 10.0 * math.log10(0.95)
                  - 10.0 * math.log10(1.0 - abs(_GS) ** 2)
                  + 20.0 * math.log10(abs(
                      1.0 - _GS * _GL * cmath.exp(-2j * beta_l))))
        assert out["p_available_dbm"] == pytest.approx(expect, abs=1e-12)

    def test_band_budget_uses_vendor_symmetric_mu(self):
        """预算行半宽=厂商对称口径 MU=20lg(1+|Γ_s||Γ_in|)（AN 1449-3
        与 R&S 失配表同式，与 v1 可比）；U 形 u=MU/√2 进预算。"""
        r = 10.0 ** (-10.0 / 20.0)
        pad = [[0j, r + 0j], [r + 0j, 0j]]
        out = calibrate_power_chain_sparams(
            -10.0, 1.0, pad, _GS, _GL, mismatch_mode="band")
        mu = out["mismatch_half_width_db"]
        assert mu == pytest.approx(
            20.0 * math.log10(1.0 + abs(_GS) * 0.1 * abs(_GL)), rel=1e-12)
        rows = {row["name"]: row for row in out["budget"]}
        assert rows["mismatch_phase"]["u_db"] == pytest.approx(
            mu / math.sqrt(2.0), rel=1e-12)


# ─── band 精确最坏区间 ───────────────────────────────────────────────────────


class TestBandExactBracket:
    def test_band_brackets_exact_500_random_phases(self):
        """500 相位随机扫：exact 恒落精确区间
        [point+20lg(1−ρ), point+20lg(1+ρ)] 内（含端点留 1e-9 容差）。"""
        rng = random.Random(7)
        for _ in range(500):
            gs = 0.4 * cmath.exp(1j * rng.uniform(0, 2 * math.pi))
            ex = calibrate_power_chain_sparams(
                -8.0, 0.95, _S_RAND, gs, _GL,
                mismatch_mode="exact")["p_available_dbm"]
            bd = calibrate_power_chain_sparams(
                -8.0, 0.95, _S_RAND, gs, _GL, mismatch_mode="band")
            lo, hi = bd["mismatch_band_db"]
            assert lo - 1e-9 <= ex <= hi + 1e-9

    def test_band_point_equals_deterministic_terms(self):
        """band 点值=全部相位自由确定性项（含 src_corr；v1 band 不含），
        exact−band_point=源交互项（20lg|1−Γ_in·Γ_s|）。"""
        bd = calibrate_power_chain_sparams(
            -8.0, 0.95, _S_RAND, _GS, _GL, mismatch_mode="band")
        ex = calibrate_power_chain_sparams(
            -8.0, 0.95, _S_RAND, _GS, _GL, mismatch_mode="exact")
        assert ex["p_available_dbm"] - bd["p_available_dbm"] == pytest.approx(
            ex["source_interaction_db"], abs=1e-12)
        assert bd["source_interaction_db"] is None
        assert bd["source_match_correction_db"] == pytest.approx(
            ex["source_match_correction_db"], abs=1e-15)

    def test_none_mode_keeps_cable_deterministic_terms(self):
        """none 模式：失配项不做点修正、不进预算；确定性缆项（插损+
        负载交互）仍修正（平行 v1 none 保留缆损耗的语义）。"""
        out = calibrate_power_chain_sparams(
            -8.0, 0.95, _S_RAND, _GS, _GL, mismatch_mode="none")
        assert out["source_interaction_db"] is None
        assert out["budget"] == []
        assert out["insertion_loss_db"] == pytest.approx(
            -20.0 * math.log10(0.9), rel=1e-12)


# ─── 单调性与确定性 ──────────────────────────────────────────────────────────


class TestMonotonicityAndDeterminism:
    def test_more_loss_larger_recovery(self):
        """插损越大 → 反演出的源平面可用功率越大（补偿方向性）。"""
        r_small = 10 ** (-1.0 / 20.0)
        r_big = 10 ** (-6.0 / 20.0)
        s_small = [[0j, r_small + 0j], [r_small + 0j, 0j]]
        s_big = [[0j, r_big + 0j], [r_big + 0j, 0j]]
        out_small = calibrate_power_chain_sparams(
            -10.0, 1.0, s_small, _GS, 0j, mismatch_mode="exact")
        out_big = calibrate_power_chain_sparams(
            -10.0, 1.0, s_big, _GS, 0j, mismatch_mode="exact")
        assert (out_big["p_available_dbm"]
                > out_small["p_available_dbm"])

    def test_band_width_grows_with_source_gamma(self):
        """|Γ_s| 越大 → 精确带区间越宽（ρ 单调）。"""
        widths = []
        for mag in (0.05, 0.2, 0.5):
            gs = mag * cmath.exp(0.4j)
            out = calibrate_power_chain_sparams(
                -8.0, 1.0, _S_RAND, gs, _GL, mismatch_mode="band")
            lo, hi = out["mismatch_band_db"]
            widths.append(hi - lo)
        assert widths[0] < widths[1] < widths[2]

    def test_deterministic_json_roundtrip(self):
        """同参两次调用逐位一致 + JSON 可序列化（信封契约面）。"""
        first = calibrate_power_chain_sparams(
            -10.0, 0.9405, _S_RAND, _GS, _GL, mismatch_mode="band",
            u_components=[{"name": "sensor_cal", "half_width_db": 0.2,
                           "distribution": "rectangular"}])
        second = calibrate_power_chain_sparams(
            -10.0, 0.9405, _S_RAND, _GS, _GL, mismatch_mode="band",
            u_components=[{"name": "sensor_cal", "half_width_db": 0.2,
                           "distribution": "rectangular"}])
        assert json.dumps(first, sort_keys=True, allow_nan=False) == (
            json.dumps(second, sort_keys=True, allow_nan=False))


# ─── 守卫 ────────────────────────────────────────────────────────────────────


class TestGuards:
    def test_shape_and_domain_rejects(self):
        """非 2×2 / |S|>1 / S21=0 / 未知模式：显式 ValueError。"""
        with pytest.raises(ValueError):
            calibrate_power_chain_sparams(
                -10.0, 1.0, [[0j, 1 + 0j]], _GS, _GL)  # 非 2×2
        with pytest.raises(ValueError):
            calibrate_power_chain_sparams(
                -10.0, 1.0, [[0j, 1.2 + 0j], [1 + 0j, 0j]],
                _GS, _GL)  # |S12|>1
        with pytest.raises(ValueError):
            calibrate_power_chain_sparams(
                -10.0, 1.0, [[0j, 1 + 0j], [0j, 0j]], _GS, _GL)  # S21=0
        with pytest.raises(ValueError):
            cable_input_gamma([[0j, 0.5 + 0j], [0.5 + 0j, 0j]],
                              [1.0, 0.0])  # |Γ_l|=1 非无源
        with pytest.raises(ValueError):
            calibrate_power_chain_sparams(
                -10.0, 1.0, _S_RAND, _GS, _GL,
                mismatch_mode="bogus")

    def test_entrywise_bounded_but_active_matrix_rejected(self):
        """|Sij|≤1 逐项有界 ≠ 网络无源：S=[[0,1],[1,0.9]]（有源形态）
        配近端接负载会得 |Γ_in|≥1，显式拒绝不静默（守卫可达性实证）。"""
        active_like = [[0j, 1 + 0j], [1 + 0j, 0.9 + 0j]]
        with pytest.raises(ValueError, match="Γ_in"):
            cable_input_gamma(active_like, 0.9 + 0j)


# ─── v1 注册键面零漂移 ───────────────────────────────────────────────────────


class TestV1SurfaceUnchanged:
    def test_v1_chain_unchanged_on_nominal(self):
        """v1 链缺省路径零漂移：名义设计点结果与本批改前钉值一致。"""
        out = calibrate_power_chain(
            -10.0, 0.9405, 3.5, gamma_source=_GS, gamma_load=_GL,
            mismatch_mode="exact")
        # v1 exact = P_read −10lg K_b + L + src_corr + 相位项（手推闭式）
        expect = (-10.0 - 10.0 * math.log10(0.9405) + 3.5
                  - 10.0 * math.log10(1.0 - abs(_GS) ** 2)
                  + 20.0 * math.log10(abs(1.0 - _GS * _GL)))
        assert out["p_available_dbm"] == pytest.approx(expect, abs=1e-12)
