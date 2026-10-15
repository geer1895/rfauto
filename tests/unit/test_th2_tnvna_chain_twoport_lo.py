"""SB22-TH-2 尾程席（TH-2 余量）定向门：N>2 带链式拼接 + 二端口八项
闭式修正 + LO 泄漏语义（函数级 API，无新 CALC 键，2026-10-08）。

四类钉（预声明）：
① 极限=理想箱 M=S 恒等/一端口退化精确退回三项模型/正向-修正回收恒等/
   链式拼接常值场+接缝 C0 端点+σ 链闭式逐点核对/LO 零泄漏与三角界端点；
② 单调=链式 budget σ 随带 σ 递增、LO 污染区间宽随泄漏递增；
③ 文献=WR-10/WR-8/WR-6.5 带缘三带链（rw_tables 同源 WR 表）+八项级联
   闭式 vs 8×8 直接信号流方程解（#118 独立数值裁判）+LO 泄漏
   directivity 同族语义（Pozar mixer 隔离度规格+Pozar VNA 校准章双源）；
④ 守卫=链 bands<2/二缝异栅格/非 dict 项、e21 零点/修正行列式奇异/
   误差箱点数不符、LO 负输入显式拒绝（函数级 ValueError，无 CALC
   信封——键面不加）。

边界（#122 如实声明）：TRL/SOLT 原始测量→误差箱提取属调用方校准引擎，
不在本内核；跨栅插值/重采样仍为登记 followUp（异栅格显式拒绝）。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from rfauto.core.rw_tables import wr_lookup
from rfauto.core.thz_vna import (
    band_stitch_chain,
    band_stitch_two,
    extender_correct_oneport,
    extender_correct_twoport,
    extender_forward_oneport,
    extender_forward_twoport,
    lo_leakage_budget,
)


def _c1(z: complex) -> list[float]:
    return [float(np.real(z)), float(np.imag(z))]


def _cbox(b: dict[str, complex]) -> dict[str, list[float]]:
    return {k: _c1(v) for k, v in b.items()}


def _band(f0: float, f1: float, step: float, s_const: complex,
          sigma: float, name: str) -> dict:
    n = round((f1 - f0) / step) + 1
    freq = [f0 + step * i for i in range(n)]
    return {"freq_hz": freq, "s": [[s_const.real, s_const.imag]] * n,
            "sigma": sigma, "name": name}


# ══════════════════ 一、N>2 带链式拼接 ══════════════════
class TestChainStitchLimitNails:
    """①极限：常值场恒等、接缝 C0 端点、σ 链闭式、并集长度。"""

    def _three_bands(self) -> list[dict]:
        return [
            _band(75e9, 110e9, 5e9, 0.10 + 0.0j, 0.01, "WR-10"),
            _band(90e9, 140e9, 5e9, 0.20 + 0.0j, 0.02, "WR-8"),
            _band(110e9, 170e9, 5e9, 0.30 + 0.0j, 0.03, "WR-6.5"),
        ]

    def test_constant_field_union_and_seam_c0(self):
        out = band_stitch_chain(self._three_bands(), 0.2)
        assert out["n_bands"] == 3 and out["n_seams"] == 2
        assert out["overall_verdict"] == "consistent"
        # 并集 = 75..110 ∪ 90..140 ∪ 110..170（步 5 GHz）= 20 点
        f = out["freq_hz"]
        assert len(f) == 20
        assert f[0] == pytest.approx(75e9) and f[-1] == pytest.approx(170e9)
        s = np.asarray([v[0] + 1j * v[1] for v in out["s"]])
        # 接缝 C0：90=纯 WR-10、110=纯 WR-8（缝 1 终点=缝 2 起点同值）、
        # 140=纯 WR-6.5
        for fq, val in ((90e9, 0.10), (110e9, 0.20), (140e9, 0.30),
                        (75e9, 0.10), (170e9, 0.30)):
            assert s[f.index(fq)] == pytest.approx(val, abs=1e-15)

    def test_sigma_chain_closed_form(self):
        """σ 链式传播闭式逐点核对：σ_seam=sqrt((w·σ_merged)²+((1−w)·σ)²)。"""
        out = band_stitch_chain(self._three_bands(), 0.2)
        f = out["freq_hz"]
        sig = out["sigma"]
        assert sig[f.index(75e9)] == pytest.approx(0.01, abs=1e-15)
        assert sig[f.index(170e9)] == pytest.approx(0.03, abs=1e-15)
        # 100 GHz：缝 1 中点 w=0.5，σ12=sqrt((0.5·0.01)²+(0.5·0.02)²)，
        # 不在缝 2 内 → σ=σ12
        sig12 = float(np.sqrt((0.5 * 0.01) ** 2 + (0.5 * 0.02) ** 2))
        assert sig[f.index(100e9)] == pytest.approx(sig12, rel=1e-14)
        # 125 GHz：缝 2 中点 w=0.5，σ_merged=0.02（缝 1 外纯 WR-8 区）
        sig125 = float(np.sqrt((0.5 * 0.02) ** 2 + (0.5 * 0.03) ** 2))
        assert sig[f.index(125e9)] == pytest.approx(sig125, rel=1e-14)
        assert out["budget"]["sigma_max_linear"] == pytest.approx(0.03)
        assert out["budget"]["sigma_edge_start_linear"] == \
            pytest.approx(0.01)
        assert out["budget"]["sigma_edge_end_linear"] == pytest.approx(0.03)

    def test_input_order_independent(self):
        a = band_stitch_chain(self._three_bands(), 0.2)
        b = band_stitch_chain(
            [self._three_bands()[1], self._three_bands()[2],
             self._three_bands()[0]], 0.2)
        assert a["freq_hz"] == b["freq_hz"]
        assert np.max(np.abs(np.asarray(a["s"]) - np.asarray(b["s"]))) == 0.0
        assert a["bands"] == ["WR-10", "WR-8", "WR-6.5"]

    def test_result_json_safe(self):
        out = band_stitch_chain(self._three_bands(), 0.2)
        json.dumps(out, ensure_ascii=False, allow_nan=False)


class TestChainStitchMonotonicNails:
    """②单调：budget σ 随带 σ 递增；verdict 阈值调用方可翻（#122）。"""

    def test_budget_monotone_in_band_sigma(self):
        budgets = []
        for s3 in (0.01, 0.05, 0.09):
            bands = [
                _band(75e9, 110e9, 5e9, 0.1 + 0.0j, 0.01, "WR-10"),
                _band(90e9, 140e9, 5e9, 0.1 + 0.0j, 0.01, "WR-8"),
                _band(110e9, 170e9, 5e9, 0.1 + 0.0j, s3, "WR-6.5"),
            ]
            out = band_stitch_chain(bands, 0.5)
            budgets.append(out["budget"]["sigma_max_linear"])
        assert budgets == sorted(budgets)
        assert budgets[0] < budgets[-1]

    def test_overall_verdict_flips_with_caller_tol(self):
        bands = [
            _band(75e9, 110e9, 5e9, 0.10 + 0.0j, 0.01, "WR-10"),
            _band(90e9, 140e9, 5e9, 0.20 + 0.0j, 0.02, "WR-8"),
            _band(110e9, 170e9, 5e9, 0.30 + 0.0j, 0.03, "WR-6.5"),
        ]
        loose = band_stitch_chain(bands, 0.2)
        tight = band_stitch_chain(bands, 0.05)
        assert loose["overall_verdict"] == "consistent"
        assert tight["overall_verdict"] == "inconsistent"
        # 两缝 max|ΔS| 同为 0.10（常值场接缝差）
        for seam in tight["seams"]:
            assert seam["max_ds_linear"] == pytest.approx(0.10, abs=1e-12)


class TestChainStitchLiteratureNails:
    """③文献：WR-10/WR-8/WR-6.5 带缘三带链（rw_tables 同源 WR 表）。"""

    def test_wr_band_edge_three_band_chain(self):
        wr10, wr8, wr65 = (wr_lookup("WR-10"), wr_lookup("WR-8"),
                           wr_lookup("WR-6.5"))
        assert (wr65.f_start_ghz, wr65.f_end_ghz) == (110.0, 170.0)
        assert (wr8.f_start_ghz, wr8.f_end_ghz) == (90.0, 140.0)
        assert (wr10.f_start_ghz, wr10.f_end_ghz) == (75.0, 110.0)
        # 缝 1 = WR-10∩WR-8 = 90..110；缝 2 = WR-8∩WR-6.5 = 110..140
        seam1 = [90e9 + 5e9 * i for i in range(5)]
        seam2 = [110e9 + 5e9 * i for i in range(7)]
        b1 = {"freq_hz": [wr10.f_start_ghz * 1e9, *seam1],
              "s": [[0.2, 0.01]] * 6, "sigma": 0.01, "name": "WR-10"}
        b2 = {"freq_hz": [*seam1, *seam2[1:]],
              "s": [[0.2, 0.01]] * 11, "sigma": 0.01, "name": "WR-8"}
        b3 = {"freq_hz": [*seam2, wr65.f_end_ghz * 1e9],
              "s": [[0.2, 0.01]] * 8, "sigma": 0.01, "name": "WR-6.5"}
        out = band_stitch_chain([b1, b2, b3], 0.01)
        assert out["overall_verdict"] == "consistent"
        s1, s2 = out["seams"]
        assert s1["f_lo_hz"] == pytest.approx(90e9)
        assert s1["f_hi_hz"] == pytest.approx(110e9)
        assert s1["n_points"] == 5
        assert s2["f_lo_hz"] == pytest.approx(110e9)
        assert s2["f_hi_hz"] == pytest.approx(140e9)
        assert s2["n_points"] == 7
        assert s1["low_band"] == "WR-10" and s1["high_band"] == "WR-8"
        assert s2["low_band"] == "WR-8" and s2["high_band"] == "WR-6.5"
        # 缝 2 起点(110 GHz)=缝 1 终点值（链式 C0 连续，非重复点）
        assert len(out["freq_hz"]) == 6 + 11 + 8 - 5 - 7


class TestChainStitchGuardNails:
    """④守卫：bands<2 / 二缝异栅格 / 非 dict 项显式拒绝。"""

    def test_single_band_rejected(self):
        with pytest.raises(ValueError, match=">=2"):
            band_stitch_chain([_band(75e9, 110e9, 5e9, 0.1, 0.01, "a")], 0.1)

    def test_second_seam_heterogrid_rejected(self):
        good = _band(90e9, 140e9, 5e9, 0.1 + 0.0j, 0.01, "WR-8")
        bad = {"freq_hz": [110e9 + 6e9 * i for i in range(6)],
               "s": [[0.3, 0.0]] * 6, "sigma": 0.01, "name": "WR-6.5"}
        with pytest.raises(ValueError, match="栅格"):
            band_stitch_chain(
                [_band(75e9, 110e9, 5e9, 0.1, 0.01, "WR-10"), good, bad], 0.5)

    def test_non_dict_item_rejected(self):
        with pytest.raises(ValueError, match="dict"):
            band_stitch_chain(
                [_band(75e9, 110e9, 5e9, 0.1, 0.01, "a"), "not-a-band"], 0.1)

    def test_two_band_kernel_unchanged_shape(self):
        """两带核重构（抽 _stitch_pair）后 band_stitch_two 输出面不变。"""
        out = band_stitch_two(
            {"freq_hz": [75e9, 90e9, 110e9], "s": [[0.1, 0.0]] * 3,
             "sigma": 0.01, "name": "a"},
            {"freq_hz": [90e9, 110e9, 140e9], "s": [[0.2, 0.0]] * 3,
             "sigma": 0.02, "name": "b"},
            0.5)
        assert out["overlap"]["verdict"] == "consistent"
        assert out["overlap"]["n_points"] == 2
        assert set(out) == {"freq_hz", "s", "s_db", "low_band", "high_band",
                            "overlap", "budget"}


# ══════════════════ 二、二端口八项误差模型 ══════════════════
_IDEAL = {"ed": [0.0, 0.0], "es": [0.0, 0.0],
          "e12": [1.0, 0.0], "e21": [1.0, 0.0]}


def _rand_series_s(rng: np.random.Generator, n: int,
                   mag: float = 0.6) -> np.ndarray:
    return (mag * rng.normal(size=(n, 2, 2))
            + 1j * mag * rng.normal(size=(n, 2, 2)))


def _rand_box_pair(rng: np.random.Generator,
                   mags1: tuple = (0.05, 0.12, 0.9, 1.2),
                   mags2: tuple = (0.06, 0.12, 1.1, 0.9)) -> tuple[dict, dict]:
    """随机复数误差箱对（幅值×均匀相位）。"""

    def one(mags: tuple) -> dict:
        def z(mag: float) -> complex:
            return mag * np.exp(1j * rng.uniform(0, 2 * np.pi))
        return {"ed": z(mags[0]), "es": z(mags[1]),
                "e12": z(mags[2]), "e21": z(mags[3])}

    return _cbox(one(mags1)), _cbox(one(mags2))


class TestTwoPortLimitNails:
    """①极限：理想箱恒等、正反演回收、广播一致。"""

    def test_ideal_boxes_identity(self):
        rng = np.random.default_rng(20261008)
        s = _rand_series_s(rng, 6, 0.7)
        m = extender_forward_twoport(s, _IDEAL, _IDEAL)
        assert np.max(np.abs(m - s)) < 1e-15
        s2 = extender_correct_twoport(m, _IDEAL, _IDEAL)
        assert np.max(np.abs(s2 - s)) < 1e-15

    def test_forward_inverse_roundtrip_recovery(self):
        rng = np.random.default_rng(75110)
        s = _rand_series_s(rng, 8, 0.6)
        box1, box2 = _rand_box_pair(rng)
        m = extender_forward_twoport(s, box1, box2)
        rec = extender_correct_twoport(m, box1, box2)
        assert np.max(np.abs(rec - s)) < 1e-10

    def test_scalar_matrix_broadcast_equals_perpoint(self):
        rng = np.random.default_rng(2026)
        s = _rand_series_s(rng, 4, 0.5)
        # 逐点恒值 == 标量广播（广播语义恒等）
        per_const = {"ed": [[0.02, 0.01]] * 4, "es": [0.1, 0.0],
                     "e12": [0.9, 0.05], "e21": [1.1, 0.0]}
        uni = {"ed": [0.02, 0.01], "es": [0.1, 0.0], "e12": [0.9, 0.05],
               "e21": [1.1, 0.0]}
        m_per = extender_forward_twoport(s, per_const, _IDEAL)
        m_uni = extender_forward_twoport(s, uni, _IDEAL)
        assert np.max(np.abs(m_per - m_uni)) < 1e-15
        # 逐点变异真生效（per-point 通道不是恒等摆设）
        per_var = {"ed": [[0.02, 0.01], [0.03, 0.01], [0.04, 0.01],
                          [0.05, 0.01]],
                   "es": [0.1, 0.0], "e12": [0.9, 0.05], "e21": [1.1, 0.0]}
        m_var = extender_forward_twoport(s, per_var, _IDEAL)
        assert np.max(np.abs(m_var - m_uni)) > 1e-6


class TestTwoPortLiteratureNails:
    """③文献/互证：一端口退化=三项模型精确；级联闭式 vs 8×8 直接信号流
    方程解（#118 独立数值裁判）。"""

    def test_oneport_reduction_matches_three_term(self):
        """箱 2 理想、S=[[Γ,0],[0,0]] → M11 精确退回 Ed+ErΓ/(1−EsΓ)。"""
        rng = np.random.default_rng(75110)
        gam = 0.6 * rng.normal(size=5) + 0.6j * rng.normal(size=5)
        ed = 0.02 - 0.01j
        es = 0.1 * np.exp(0.7j)
        er = 1.05 * np.exp(-0.2j)
        box1 = _cbox({"ed": ed, "es": es, "e12": er, "e21": 1.0 + 0.0j})
        s = np.zeros((5, 2, 2), dtype=complex)
        s[:, 0, 0] = gam
        m = extender_forward_twoport(s, box1, _IDEAL)
        expect = extender_forward_oneport(gam, ed, es, er)
        assert np.max(np.abs(m[:, 0, 0] - expect)) < 1e-13
        assert np.max(np.abs(m[:, 0, 1])) < 1e-13
        assert np.max(np.abs(m[:, 1, 0])) < 1e-13
        assert np.max(np.abs(m[:, 1, 1])) < 1e-13
        # 修正侧同退化：Γ_corr 精确
        g2 = extender_correct_twoport(m, box1, _IDEAL)[:, 0, 0]
        expect_g = extender_correct_oneport(expect, ed, es, er)
        assert np.max(np.abs(g2 - expect_g)) < 1e-12

    @staticmethod
    def _direct_flow_m(s_mat: np.ndarray, b1: dict, b2: dict) -> np.ndarray:
        """8×8 直接信号流方程解（独立推导）：未知 x=[a1,b1,a2,b2,bm1,am1,
        bm2,am2]，箱方程+DUT 方程+单源归一（激励端 am=1、对端 am=0）。
        每激励新建矩阵（跨激励不得残留源归一行）。"""
        cols = []
        for src in (0, 1):
            A = np.zeros((8, 8), dtype=complex)
            y = np.zeros(8, dtype=complex)
            A[0, 1], A[0, 0], A[0, 2] = 1.0, -s_mat[0, 0], -s_mat[0, 1]
            A[1, 3], A[1, 0], A[1, 2] = 1.0, -s_mat[1, 0], -s_mat[1, 1]
            A[2, 4], A[2, 5], A[2, 1] = 1.0, -b1["ed"], -b1["e12"]
            A[3, 0], A[3, 5], A[3, 1] = 1.0, -b1["e21"], -b1["es"]
            A[4, 6], A[4, 7], A[4, 3] = 1.0, -b2["ed"], -b2["e12"]
            A[5, 2], A[5, 7], A[5, 3] = 1.0, -b2["e21"], -b2["es"]
            if src == 0:
                A[6, 5], y[6] = 1.0, 1.0   # am1 = 1
                A[7, 7], y[7] = 1.0, 0.0   # am2 = 0
            else:
                A[6, 7], y[6] = 1.0, 1.0   # am2 = 1
                A[7, 5], y[7] = 1.0, 0.0   # am1 = 0
            cols.append(np.linalg.solve(A, y))
        return np.array([
            [cols[0][4], cols[1][4]],
            [cols[0][6], cols[1][6]],
        ])  # 归一 am=1（列 0 除 am1、列 1 除 am2，均=1）

    def test_cascade_closed_form_matches_direct_signal_flow(self):
        rng = np.random.default_rng(314159)
        for _ in range(6):
            b1, b2 = _rand_box_pair(rng)
            b1_c = {k: complex(v[0], v[1]) for k, v in b1.items()}
            b2_c = {k: complex(v[0], v[1]) for k, v in b2.items()}
            s0 = _rand_series_s(rng, 1, 0.6)[0]
            m_kernel = extender_forward_twoport(s0.reshape(1, 2, 2), b1, b2)[0]
            m_direct = self._direct_flow_m(s0, b1_c, b2_c)
            assert np.max(np.abs(m_kernel - m_direct)) < 1e-10


class TestTwoPortGuardNails:
    """④守卫：e21 零点 / 修正行列式奇异 / 误差箱点数不符显式拒绝。"""

    def test_e21_zero_rejected(self):
        bad = {"ed": [0.0, 0.0], "es": [0.0, 0.0], "e12": [1.0, 0.0],
               "e21": [0.0, 0.0]}
        with pytest.raises(ValueError, match="e21"):
            extender_correct_twoport(
                np.zeros((1, 2, 2), dtype=complex), _IDEAL, bad)

    def test_singular_correction_matrix_rejected(self):
        # e12·e21 = Ed·Es 精确（二进制无误差：0.25·0.5=0.125）→ X01=0；
        # M=0 → det(M·G−E)=0（近奇异病态不设容差门，与一端口核同口径）
        b = _cbox({"ed": 0.25 + 0.0j, "es": 0.5 + 0.0j,
                   "e12": 0.125 + 0.0j, "e21": 1.0 + 0.0j})
        with pytest.raises(ValueError, match="奇异"):
            extender_correct_twoport(
                np.zeros((1, 2, 2), dtype=complex), b, b)

    def test_series_box_single_matrix_rejected(self):
        """系列误差箱 + 单矩阵输入 → 点数不符显式拒绝（W1.6 席 TH-2 缺陷
        回归钉：修复前箱列静默误广播到 n=1 后 reshape 崩 cannot reshape）。"""
        box3 = {"ed": [[0.01, 0.001], [0.02, 0.001], [0.03, 0.001]],
                "es": [[0.01, 0.0]] * 3, "e12": [[0.9, 0.05]] * 3,
                "e21": [[0.9, 0.0]] * 3}
        s1 = np.array([[0.5 + 0.1j, 0.02 + 0.01j],
                       [0.02 + 0.01j, 0.4 - 0.05j]])
        with pytest.raises(ValueError, match="点数须为 1"):
            extender_forward_twoport(s1, box3, _IDEAL)
        with pytest.raises(ValueError, match="点数须为 1"):
            extender_correct_twoport(s1, box3, _IDEAL)

    def test_series_box_series_matrix_roundtrip(self):
        """系列误差箱（逐点变异）+ 同点数系列矩阵 → 照常工作：正向-修正
        回收恒等 + 逐点变异真生效（≠ 单点常值箱广播结果）。"""
        n = 3
        rng = np.random.default_rng(75111)
        s = _rand_series_s(rng, n, 0.5)
        box1 = {"ed": [[0.01 + 0.002 * i, 0.001] for i in range(n)],
                "es": [[0.10 + 0.01 * i, 0.0] for i in range(n)],
                "e12": [[0.9, 0.05 + 0.01 * i] for i in range(n)],
                "e21": [[1.1, 0.01 * i] for i in range(n)]}
        box2 = {"ed": [[0.02 + 0.003 * i, 0.001] for i in range(n)],
                "es": [[0.11 + 0.005 * i, 0.0] for i in range(n)],
                "e12": [[0.8, 0.04 + 0.008 * i] for i in range(n)],
                "e21": [[0.95, -0.006 * i] for i in range(n)]}
        m = extender_forward_twoport(s, box1, box2)
        assert m.shape == (n, 2, 2)
        rec = extender_correct_twoport(m, box1, box2)
        assert np.max(np.abs(rec - s)) < 1e-10
        # 逐点变异箱 ≠ 首点常值广播箱（per-point 通道不是恒等摆设）
        const1 = {k: v[0] for k, v in box1.items()}
        m_var = extender_forward_twoport(s, box1, _IDEAL)
        m_const = extender_forward_twoport(s, const1, _IDEAL)
        assert np.max(np.abs(m_var - m_const)) > 1e-6


# ══════════════════ 三、LO 泄漏语义 ══════════════════
class TestLoLeakageNails:
    """①极限+②单调+③反解闭式+④守卫（#122：ε 调用方给入）。"""

    def test_triangle_bounds_exact(self):
        out = lo_leakage_budget(0.5, 0.1, 0.05)
        assert out["meas_mag_bound_uncorrected"] == \
            pytest.approx([0.4, 0.6], abs=1e-15)
        assert out["suppression_ratio_linear"] == pytest.approx(5.0)
        assert out["leak_relative_db"] == pytest.approx(-20.0 * np.log10(5.0))

    def test_required_suppression_backsolve_exact(self):
        out = lo_leakage_budget(0.5, 0.1, 0.05, 0.02)
        assert out["required_suppression_uncorrected"] == pytest.approx(10.0)
        assert out["required_suppression_corrected"] == pytest.approx(25.0)
        assert out["worst_error_abs_corrected"] == pytest.approx(0.02)

    def test_verdict_three_states(self):
        assert lo_leakage_budget(0.5, 0.03, 0.05)["verdict"] == \
            "meets_uncorrected"
        assert lo_leakage_budget(0.5, 0.10, 0.05, 0.02)["verdict"] == \
            "meets_corrected_only"
        assert lo_leakage_budget(0.5, 0.5, 0.05, 0.3)["verdict"] == \
            "unachievable"

    def test_bound_width_monotone_in_leakage(self):
        widths = []
        for lev in (0.05, 0.1, 0.2, 0.4):
            out = lo_leakage_budget(0.5, lev, 0.05)
            lo, hi = out["meas_mag_bound_uncorrected"]
            widths.append(hi - lo)
        assert widths == sorted(widths)

    def test_zero_leakage_degenerate(self):
        out = lo_leakage_budget(0.5, 0.0, 0.05)
        assert out["suppression_ratio_linear"] is None
        assert out["meas_mag_bound_uncorrected"] == \
            pytest.approx([0.5, 0.5], abs=1e-15)
        assert out["verdict"] == "meets_uncorrected"
        assert out["leak_relative_db"] is None

    def test_negative_input_rejected(self):
        with pytest.raises(ValueError, match="s_level"):
            lo_leakage_budget(-0.1, 0.0, 0.05)
        with pytest.raises(ValueError, match="required_accuracy"):
            lo_leakage_budget(0.5, 0.1, -0.05)
