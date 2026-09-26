"""DP-11 P1：IEEEP370 2x-thru AFR 夹具去嵌（criteria.md G3）。

- 合成回收：FIX**DUT**FIX + 2x-thru → deembed 恢复 D，
  |ΔS21| ≤ 1e-3 dB（规格书 §5②）；
- 语料构造沿 test_deembed_referee 同款合规口径（0.1–40 GHz/801 点/
  25mm 理想匹配线 FIX——IEEE370 合成判据 2x-thru ≥ 3λg）；
- 预检负例：非对称注入 → 预检 ok=False，不产出去嵌结果（如实失败）。
"""

from __future__ import annotations

import numpy as np
import pytest
import skrf

from rfauto.measurement.afr_2xthru import (
    DEFAULT_SMOOTH_TOL_DB,
    DEFAULT_SYM_TOL,
    check_2xthru_preconditions,
    deembed_2xthru,
    recovery_delta_s21_db,
)

C0 = 299_792_458.0


def _freq(n_points: int = 801) -> skrf.Frequency:
    return skrf.Frequency(0.1, 40.0, n_points, "GHz")


def _make_fix(freq: skrf.Frequency, length_m: float, eps_eff: float = 3.0,
              z0: float = 50.0) -> skrf.Network:
    """理想匹配线 fixture（γ=α+jβ 解析；端口参考恒 z0）。"""
    f = np.asarray(freq.f, dtype=float)
    gamma = 1j * 2.0 * np.pi * f * np.sqrt(eps_eff) / C0
    s = np.zeros((f.size, 2, 2), dtype=complex)
    t = np.exp(-gamma * length_m)
    s[:, 0, 1] = t
    s[:, 1, 0] = t
    return skrf.Network(frequency=freq, s=s, z0=z0)


def _make_dut(freq: skrf.Frequency, z0: float = 50.0, eps_eff: float = 2.25,
              length_m: float = 4e-3, c_farad: float = 0.3e-12
              ) -> skrf.Network:
    """合成 DUT：shunt C + 线 + shunt C（ABCD 独立构造 → a2s 换形）。"""
    from skrf.network import a2s

    f = np.asarray(freq.f, dtype=float)
    gl = 1j * 2.0 * np.pi * f * np.sqrt(eps_eff) / C0 * length_m
    ch, sh = np.cosh(gl), np.sinh(gl)
    abl = np.zeros((f.size, 2, 2), dtype=complex)
    abl[:, 0, 0] = ch
    abl[:, 0, 1] = z0 * sh
    abl[:, 1, 0] = sh / z0
    abl[:, 1, 1] = ch
    aby = np.zeros((f.size, 2, 2), dtype=complex)
    aby[:, 0, 0] = 1.0
    aby[:, 1, 0] = 1j * 2.0 * np.pi * f * c_farad
    aby[:, 1, 1] = 1.0
    ab = aby @ abl @ aby
    return skrf.Network(frequency=freq, s=a2s(ab, z0), z0=z0)


@pytest.fixture()
def ideal_corpus():
    freq = _freq()
    fix = _make_fix(freq, 25e-3)
    dut = _make_dut(freq)
    thru2x = fix ** fix
    fdf = fix ** dut ** fix
    return freq, dut, thru2x, fdf


class TestP370ImportPath:
    """审计 §1 注钉：P370 类在 calibration.deembedding 子模块。"""

    def test_import_path(self):
        from skrf.calibration.deembedding import IEEEP370_SE_NZC_2xThru

        assert IEEEP370_SE_NZC_2xThru is not None
        with pytest.raises(ImportError):
            from skrf.calibration import IEEEP370_SE_NZC_2xThru


class TestPrecheck:
    """2x-thru 预检：对称性 + |S21| dB 平滑性（判据预声明）。"""

    def test_ideal_2xthru_passes(self, ideal_corpus):
        _f, _dut, thru2x, _fdf = ideal_corpus
        pre = check_2xthru_preconditions(thru2x)
        assert pre.ok is True
        assert pre.symmetry_max <= DEFAULT_SYM_TOL
        assert pre.smoothness_max_db <= DEFAULT_SMOOTH_TOL_DB
        assert pre.failures == []

    def test_asymmetric_injection_fails(self, ideal_corpus):
        _f, _dut, thru2x, _fdf = ideal_corpus
        bad = thru2x.copy()
        bad.s[:, 0, 1] *= 0.9  # 非对称注入（S12 衰减 10%）
        pre = check_2xthru_preconditions(bad)
        assert pre.ok is False
        assert any("对称性" in f for f in pre.failures)

    def test_non_smooth_fails(self):
        """|S21| 带谐振尖峰（台阶）的 2x-thru → 平滑性预检 FAIL。"""
        freq = _freq(201)
        fix = _make_fix(freq, 25e-3)
        bad = fix.copy()
        # 注入窄带尖峰：中点频点 |S21| 压 -6 dB（二阶差分远超 0.5 dB）
        bad.s[100, 0, 1] *= 0.5
        bad.s[100, 1, 0] *= 0.5
        pre = check_2xthru_preconditions(bad)
        assert pre.ok is False
        assert any("平滑性" in f for f in pre.failures)

    def test_deep_valley_points_exempt_from_smoothness(self):
        """深谷（<−60dB）频点的 dB 抖动不参与平滑性（噪声非物理信息）。"""
        freq = _freq(101)
        net = _make_fix(freq, 25e-3)
        net.s[50, 0, 1] = 1e-9   # −180 dB 深谷
        net.s[50, 1, 0] = 1e-9
        net.s[50, 0, 0] = 1e-9
        net.s[50, 1, 1] = 1e-9
        pre = check_2xthru_preconditions(net)
        assert pre.ok is True


class TestDeembed:
    """AFR 去嵌：合成回收 + 如实失败路径。"""

    def test_recovery_within_1e3_db(self, ideal_corpus):
        _freq_ob, dut, thru2x, fdf = ideal_corpus
        out = deembed_2xthru(fdf, thru2x)
        assert out["ok"] is True
        assert out["network"] is not None
        delta = recovery_delta_s21_db(out["network"], dut)
        assert delta <= 1e-3, f"|ΔS21|={delta} dB 超 1e-3 门"

    def test_deterministic(self, ideal_corpus):
        _freq_ob, _dut, thru2x, fdf = ideal_corpus
        out1 = deembed_2xthru(fdf, thru2x)
        out2 = deembed_2xthru(fdf, thru2x)
        assert recovery_delta_s21_db(out1["network"], out2["network"]) == 0.0

    def test_precheck_failure_short_circuits(self, ideal_corpus):
        _freq_ob, _dut, thru2x, fdf = ideal_corpus
        bad = thru2x.copy()
        bad.s[:, 0, 1] *= 0.9
        out = deembed_2xthru(fdf, bad)
        assert out["ok"] is False
        assert out["network"] is None
        assert "预检不过" in out["error"]

    def test_freq_grid_mismatch_raises(self, ideal_corpus):
        _freq_ob, _dut, thru2x, _fdf = ideal_corpus
        other = _make_dut(_freq(101))
        with pytest.raises(ValueError, match="频率栅格不一致"):
            deembed_2xthru(other, thru2x)

    def test_type_and_port_guards(self):
        with pytest.raises(TypeError, match=r"skrf\.Network"):
            deembed_2xthru("not a network", "also not")
        freq = _freq(21)
        one_port = skrf.Network(
            frequency=freq, s=np.zeros((21, 1, 1), dtype=complex))
        with pytest.raises(ValueError, match="2 端口"):
            deembed_2xthru(one_port, one_port)
