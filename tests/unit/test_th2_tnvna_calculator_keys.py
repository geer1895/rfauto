"""SB22-TH-2 TNVNA 扩频键面定向门（TH2 储备池席，2026-10-08）。

注册薄壳（calc_families/thz_vna.py）的键面回归钉；内核 core/thz_vna.py。
四类钉（预声明）：①极限=理想误差项恒等回收/零预算/重叠带缘权重端点/butt
对接；②单调=σ_Γ 随 σEs 递增、重叠预算随带 σ 递增；③文献=WR-10/WR-8
带缘（core/rw_tables 2src-thz 行：VDI 频段表+Spinner TD-00036 双源）重叠
90–110 GHz+一端口误差模型正反演恒等（Pozar 一端口校准同款闭式，
Hesler ISSTT 2010 按带标定语义）；④守卫=|Er|=0/奇异分母/非升频/长度
不配/异栅格/负 σ 显式拒绝。

灵敏度互证（#118：裁判=独立数值来源）：一阶偏导闭式由复参数实方向中心
差分独立复算（解析函数方向无关性），rtol 2e-5。
"""

from __future__ import annotations

import typing

import numpy as np
import pytest

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.core.rw_tables import wr_lookup
from rfauto.core.thz_vna import (
    extender_correct_oneport,
    extender_forward_oneport,
)
from rfauto.service.calculator_service import run_calculator

NEW_KEYS = ("tnvna_extender_error_model", "tnvna_band_stitch")


def _pairs(arr: np.ndarray) -> list[list[float]]:
    return [[float(v.real), float(v.imag)] for v in np.asarray(arr)]


def _toc(pairs: list[list[float]]) -> np.ndarray:
    a = np.asarray(pairs, dtype=float)
    return a[:, 0] + 1j * a[:, 1]


class TestRegistrySurface:
    def test_new_keys_registered_not_experimental(self):
        names = set(CALCULATOR_REGISTRY.names())
        assert set(NEW_KEYS) <= names
        for k in NEW_KEYS:
            assert CALCULATOR_REGISTRY.get(k).experimental is False

    def test_describe_json_ready(self):
        import json
        rows = CALCULATOR_REGISTRY.describe(include_experimental=True)
        by = {r["name"]: r for r in rows}
        for k in NEW_KEYS:
            json.dumps(by[k], ensure_ascii=False, allow_nan=False)


class TestLimitNails:
    """①极限：理想误差项恒等、零预算、带缘权重端点、butt 对接。"""

    def test_ideal_terms_exact_identity(self):
        g_true = np.array([0.3 + 0.1j, -0.5 + 0.2j, 0.0 + 0.0j])
        out = run_calculator("tnvna_extender_error_model", {
            "freq_hz": [75e9, 90e9, 110e9], "measured": _pairs(g_true),
            "ed": [0, 0], "es": [0, 0], "er": [1, 0]})
        assert out["ok"] is True, out
        assert np.max(np.abs(_toc(out["result"]["gamma_corr"]) - g_true)) \
            == pytest.approx(0.0, abs=1e-15)

    def test_zero_sigma_zero_budget(self):
        out = run_calculator("tnvna_extender_error_model", {
            "freq_hz": [75e9, 110e9], "measured": [[0.2, 0.0], [0.1, 0.1]],
            "ed": [0.01, 0.0], "es": [0.02, 0.0], "er": [1.0, 0.0]})
        assert out["ok"] is True
        assert out["result"]["sigma_gamma"] == [0.0, 0.0]

    def test_forward_inverse_roundtrip_exact(self):
        rng = np.random.default_rng(20261008)
        g = 0.4 * rng.normal(size=6) + 0.4j * rng.normal(size=6)
        ed = 0.03 * (1 + 1j)
        es = 0.05 + 0.02j
        er = 1.0 + 0.05j
        m = extender_forward_oneport(g, ed, es, er)
        rec = extender_correct_oneport(m, ed, es, er)
        assert np.max(np.abs(rec - g)) < 1e-12

    def test_stitch_edge_weights_endpoint_exact(self):
        """重叠区带缘权重端点：w(起点)=1 全低带、w(终点)=0 全高带（C0）。"""
        fa = [75e9 + 5e9 * i for i in range(8)]   # 75..110 GHz
        fb = [90e9 + 5e9 * i for i in range(11)]  # 90..140 GHz
        s_lo = [[0.10, 0.0]] * 8
        s_hi = [[0.30, 0.0]] * 11
        out = run_calculator("tnvna_band_stitch", {
            "band_a": {"freq_hz": fa, "s": s_lo, "sigma": 0.01,
                       "name": "WR-10"},
            "band_b": {"freq_hz": fb, "s": s_hi, "sigma": 0.02,
                       "name": "WR-8"},
            "tol_abs_linear": 0.5})
        assert out["ok"] is True, out
        r = out["result"]
        f, s = r["freq_hz"], _toc(r["s"])
        i0 = f.index(90e9)
        i1 = f.index(110e9)
        # 重叠起点=纯低带值、终点=纯高带值
        assert s[i0] == pytest.approx(0.10 + 0.0j, abs=1e-15)
        assert s[i1] == pytest.approx(0.30 + 0.0j, abs=1e-15)
        # 带外段原值直通
        assert s[f.index(75e9)] == pytest.approx(0.10 + 0.0j, abs=1e-15)
        assert s[f.index(140e9)] == pytest.approx(0.30 + 0.0j, abs=1e-15)
        assert len(f) == 8 + 11 - 5  # 全集 − 重叠重复

    def test_no_overlap_butt_join_reported(self):
        fa = [75e9, 85e9]
        fb = [110e9, 120e9]
        out = run_calculator("tnvna_band_stitch", {
            "band_a": {"freq_hz": fa, "s": [[0.1, 0.0], [0.1, 0.0]]},
            "band_b": {"freq_hz": fb, "s": [[0.2, 0.0], [0.2, 0.0]]},
            "tol_abs_linear": 0.01})
        assert out["ok"] is True
        assert out["result"]["overlap"]["verdict"] == "no_overlap"
        assert len(out["result"]["freq_hz"]) == 4

    def test_touching_point_degenerate_overlap_equal_weight(self):
        """恰共点=退化单点重叠：width=0 → 等权 0.5/0.5 合并（docstring 口径）；
        两带在该点分歧时一致性判据如实报 inconsistent（ΔS=0.11>tol）。"""
        fa = [75e9, 110e9]
        fb = [110e9, 140e9]
        out = run_calculator("tnvna_band_stitch", {
            "band_a": {"freq_hz": fa, "s": [[0.1, 0.0], [0.11, 0.0]]},
            "band_b": {"freq_hz": fb, "s": [[0.22, 0.0], [0.2, 0.0]]},
            "tol_abs_linear": 0.01})
        assert out["ok"] is True
        r = out["result"]
        assert r["overlap"]["verdict"] == "inconsistent"
        assert r["overlap"]["n_points"] == 1
        assert len(r["freq_hz"]) == 3
        i = r["freq_hz"].index(110e9)
        assert _toc(r["s"])[i] == pytest.approx(0.165 + 0.0j, abs=1e-15)


class TestMonotonicNails:
    """②单调：预算随残余 σ 递增、随带 σ 递增。"""

    _BASE: typing.ClassVar[dict] = {
        "freq_hz": [75e9, 90e9, 110e9],
        "measured": [[0.3, 0.1], [0.0, 0.0], [-0.5, 0.2]],
        "ed": [0.01, 0.003], "es": [0.05, -0.02], "er": [1.02, 0.01]}

    def test_sigma_gamma_monotone_in_sigma_es(self):
        sigmas = []
        for s_es in (0.0, 0.005, 0.02, 0.05):
            out = run_calculator("tnvna_extender_error_model",
                                 {**self._BASE, "sigma_m": 0.01,
                                  "sigma_es": s_es, "sigma_er": 0.01})
            assert out["ok"] is True, out
            sigmas.append(max(out["result"]["sigma_gamma"]))
        assert sigmas == sorted(sigmas)
        assert sigmas[0] < sigmas[-1]

    def test_overlap_budget_monotone_in_band_sigma(self):
        fa = [75e9 + 5e9 * i for i in range(8)]
        fb = [90e9 + 5e9 * i for i in range(11)]
        budgets = []
        for s_b in (0.01, 0.03, 0.06):
            out = run_calculator("tnvna_band_stitch", {
                "band_a": {"freq_hz": fa, "s": [[0.1, 0.0]] * 8,
                           "sigma": 0.01},
                "band_b": {"freq_hz": fb, "s": [[0.1, 0.0]] * 11,
                           "sigma": s_b},
                "tol_abs_linear": 0.05})
            assert out["ok"] is True
            budgets.append(out["result"]["budget"]["sigma_max_linear"])
        assert budgets == sorted(budgets)

    def test_consistency_verdict_threshold_is_caller_supplied(self):
        """#122：同一 max|ΔS|，阈值调用方可翻 verdict（内核不 ship 门限）。"""
        fa = [75e9 + 5e9 * i for i in range(8)]
        fb = [90e9 + 5e9 * i for i in range(11)]
        bands = {
            "band_a": {"freq_hz": fa, "s": [[0.10, 0.0]] * 8, "sigma": 0.01},
            "band_b": {"freq_hz": fb, "s": [[0.12, 0.0]] * 11, "sigma": 0.02},
        }
        out_loose = run_calculator("tnvna_band_stitch",
                                   {**bands, "tol_abs_linear": 0.05})
        out_tight = run_calculator("tnvna_band_stitch",
                                   {**bands, "tol_abs_linear": 0.001})
        assert out_loose["result"]["overlap"]["verdict"] == "consistent"
        assert out_tight["result"]["overlap"]["verdict"] == "inconsistent"
        ds = out_loose["result"]["overlap"]["max_ds_linear"]
        assert ds == pytest.approx(0.02, abs=1e-12)


class TestLiteratureNails:
    """③文献：WR 带缘（rw_tables 2src-thz 双源）+误差模型闭式恒等。"""

    def test_band_edges_from_rw_tables_dual_source(self):
        """重叠区=WR-10/WR-8 带缘交集（VDI+Spinner 双源行，TH-1 同表）。"""
        wr10 = wr_lookup("WR-10")
        wr8 = wr_lookup("WR-8")
        assert (wr10.f_start_ghz, wr10.f_end_ghz) == (75.0, 110.0)
        assert (wr8.f_start_ghz, wr8.f_end_ghz) == (90.0, 140.0)
        ov_lo = max(wr10.f_start_ghz, wr8.f_start_ghz)
        ov_hi = min(wr10.f_end_ghz, wr8.f_end_ghz)
        assert (ov_lo, ov_hi) == (90.0, 110.0)
        n = 9  # 90..110 GHz 每 2.5 GHz 同栅
        freqs = [ov_lo * 1e9 + (ov_hi - ov_lo) * 1e9 * i / (n - 1)
                 for i in range(n)]
        fa = [wr10.f_start_ghz * 1e9, *freqs]
        fb = [*freqs, wr8.f_end_ghz * 1e9]
        out = run_calculator("tnvna_band_stitch", {
            "band_a": {"freq_hz": fa, "s": [[0.2, 0.01]] * len(fa),
                       "sigma": 0.01, "name": "WR-10"},
            "band_b": {"freq_hz": fb, "s": [[0.2, 0.01]] * len(fb),
                       "sigma": 0.01, "name": "WR-8"},
            "tol_abs_linear": 0.01})
        assert out["ok"] is True, out
        r = out["result"]
        assert r["overlap"]["n_points"] == n
        assert r["overlap"]["verdict"] == "consistent"
        assert r["overlap"]["f_lo_hz"] == pytest.approx(90e9)
        assert r["overlap"]["f_hi_hz"] == pytest.approx(110e9)
        assert len(r["freq_hz"]) == len(fa) + len(fb) - n

    def test_oneport_error_model_closed_form_identity(self):
        """正反演恒等：M=Ed+ErΓ/(1−EsΓ) ⇔ Γ=(M−Ed)/(Er+Es(M−Ed))。"""
        rng = np.random.default_rng(75110)
        g = 0.6 * rng.normal(size=12) + 0.6j * rng.normal(size=12)
        ed = 0.02 - 0.01j      # directivity ≈ −34 dB 量级
        es = 0.1 * np.exp(0.7j)  # source match ≈ −20 dB
        er = 1.05 * np.exp(-0.2j)  # tracking
        m = extender_forward_oneport(g, ed, es, er)
        rec = extender_correct_oneport(m, ed, es, er)
        assert np.max(np.abs(rec - g)) < 1e-13

    def test_directivity_null_cancels_offset(self):
        """只测得 Ed（接匹配负载）⇒ 修正后 Γ=0（directivity 消除）。"""
        ed = [0.05, -0.01]
        out = run_calculator("tnvna_extender_error_model", {
            "freq_hz": [90e9], "measured": [ed],
            "ed": ed, "es": [0.03, 0.01], "er": [1.0, 0.0]})
        assert out["ok"] is True
        assert np.max(np.abs(_toc(out["result"]["gamma_corr"]))) \
            == pytest.approx(0.0, abs=1e-15)


class TestSensitivityCrossCheck:
    """一阶偏导闭式 vs 实方向中心差分（#118 独立数值裁判）。"""

    def test_budget_matches_finite_difference(self):
        g0 = np.array([0.3 + 0.1j])
        ed = np.array([0.02 - 0.01j])
        es = np.array([0.1 * np.exp(0.7j)])
        er = np.array([1.05 * np.exp(-0.2j)])
        sm, sd, ss, sr = 0.01, 0.004, 0.005, 0.01
        out = run_calculator("tnvna_extender_error_model", {
            "freq_hz": [90e9], "measured": _pairs(
                extender_forward_oneport(g0, ed, es, er)),
            "ed": _pairs(ed)[0], "es": _pairs(es)[0], "er": _pairs(er)[0],
            "sigma_m": sm, "sigma_ed": sd, "sigma_es": ss, "sigma_er": sr})
        assert out["ok"] is True, out
        sigma_kernel = out["result"]["sigma_gamma"][0]

        def corr(m_val, ed_val, es_val, er_val):
            return extender_correct_oneport(
                np.atleast_1d(m_val), np.atleast_1d(ed_val),
                np.atleast_1d(es_val), np.atleast_1d(er_val))[0]

        m0 = extender_forward_oneport(g0, ed, es, er)[0]
        h = 1e-7
        # 实方向中心差分 |∂Γ/∂x|（解析函数方向无关）
        d_m = abs((corr(m0 + h, ed[0], es[0], er[0])
                   - corr(m0 - h, ed[0], es[0], er[0])) / (2 * h))
        d_ed = abs((corr(m0, ed[0] + h, es[0], er[0])
                    - corr(m0, ed[0] - h, es[0], er[0])) / (2 * h))
        d_es = abs((corr(m0, ed[0], es[0] + h, er[0])
                    - corr(m0, ed[0], es[0] - h, er[0])) / (2 * h))
        d_er = abs((corr(m0, ed[0], es[0], er[0] + h)
                    - corr(m0, ed[0], es[0], er[0] - h)) / (2 * h))
        sigma_fd = float(np.sqrt(d_m**2 * sm**2 + d_ed**2 * sd**2
                                 + d_es**2 * ss**2 + d_er**2 * sr**2))
        assert sigma_kernel == pytest.approx(sigma_fd, rel=2e-5)


class TestGuardNails:
    """④守卫：域外显式拒绝（ok=False 信封，不抛出）。"""

    def test_er_zero_rejected(self):
        out = run_calculator("tnvna_extender_error_model", {
            "freq_hz": [75e9, 90e9], "measured": [[0.3, 0.1], [0.0, 0.0]],
            "ed": [0, 0], "es": [0, 0], "er": [0.0, 0.0]})
        assert out["ok"] is False and "er" in out["error"]

    def test_singular_denominator_rejected(self):
        # 构造 M 使 D=Er+Es(M−Ed)=0：Es=0.5、Er=1、Ed=0、M=−2 ⇒ D=0
        out = run_calculator("tnvna_extender_error_model", {
            "freq_hz": [90e9], "measured": [[-2.0, 0.0]],
            "ed": [0, 0], "es": [0.5, 0.0], "er": [1.0, 0.0]})
        assert out["ok"] is False and "奇异" in out["error"]

    def test_measured_length_mismatch_rejected(self):
        out = run_calculator("tnvna_extender_error_model", {
            "freq_hz": [75e9, 90e9], "measured": [[0.3, 0.1]],
            "ed": [0, 0], "es": [0, 0], "er": [1, 0]})
        assert out["ok"] is False

    def test_freq_not_increasing_rejected(self):
        out = run_calculator("tnvna_extender_error_model", {
            "freq_hz": [90e9, 75e9], "measured": [[0.3, 0.1], [0.0, 0.0]],
            "ed": [0, 0], "es": [0, 0], "er": [1, 0]})
        assert out["ok"] is False

    def test_negative_sigma_rejected(self):
        out = run_calculator("tnvna_extender_error_model", {
            "freq_hz": [90e9], "measured": [[0.3, 0.1]],
            "ed": [0, 0], "es": [0, 0], "er": [1, 0], "sigma_m": -0.1})
        assert out["ok"] is False

    def test_stitch_grid_mismatch_rejected(self):
        """重叠区异栅格：v1 如实拒绝（不静默插值）。"""
        out = run_calculator("tnvna_band_stitch", {
            "band_a": {"freq_hz": [75e9 + 5e9 * i for i in range(8)],
                       "s": [[0.1, 0.0]] * 8, "sigma": 0.01},
            "band_b": {"freq_hz": [90e9 + 4e9 * i for i in range(13)],
                       "s": [[0.1, 0.0]] * 13, "sigma": 0.02},
            "tol_abs_linear": 0.05})
        assert out["ok"] is False and "栅格" in out["error"]

    def test_stitch_bad_freq_rejected(self):
        out = run_calculator("tnvna_band_stitch", {
            "band_a": {"freq_hz": [90e9, 75e9],
                       "s": [[0.1, 0.0]] * 2, "sigma": 0.01},
            "band_b": {"freq_hz": [110e9, 140e9],
                       "s": [[0.1, 0.0]] * 2, "sigma": 0.01},
            "tol_abs_linear": 0.05})
        assert out["ok"] is False

    def test_stitch_negative_tol_rejected(self):
        out = run_calculator("tnvna_band_stitch", {
            "band_a": {"freq_hz": [75e9, 110e9],
                       "s": [[0.1, 0.0]] * 2, "sigma": 0.01},
            "band_b": {"freq_hz": [110e9, 140e9],
                       "s": [[0.1, 0.0]] * 2, "sigma": 0.01},
            "tol_abs_linear": -1.0})
        assert out["ok"] is False
