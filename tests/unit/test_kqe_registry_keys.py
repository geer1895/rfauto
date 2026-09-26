"""k_split_pair / qe_group_delay 注册键测试（df6 A1 R4 产品化接线）。

合成回收（裁判独立于实现 #118）+ 与 runner 提取内核跨实现互证钉
（同输入逐位——双实现漂移防护）。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.calculators import CALCULATOR_REGISTRY

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import df6_a1_r4_runner as runner


def _two_peak_s21(f1_ghz: float, f2_ghz: float, n: int = 801):
    """合成双峰 |S21|（洛伦兹双峰+浅纹波），2.40-2.60GHz 栅格。"""
    f = np.linspace(2.40e9, 2.60e9, n)
    g1 = 1.0 / (1.0 + ((f / 1e9 - f1_ghz) / 0.01) ** 2)
    g2 = 1.0 / (1.0 + ((f / 1e9 - f2_ghz) / 0.01) ** 2)
    mag = 0.3 + 0.65 * np.maximum(g1, g2)   # 线性幅度（峰 0.95/谷 0.325）
    return f, mag * np.exp(1j * -np.linspace(0, 8, n))


class TestKSplitPair:
    def test_registry_key_present(self):
        assert "k_split_pair" in CALCULATOR_REGISTRY.names()

    def test_exact_formula_recovery(self):
        f, s21 = _two_peak_s21(2.45, 2.55)
        out = CALCULATOR_REGISTRY.get("k_split_pair").func(freq_hz=f, s21=s21)
        assert out["quality"] == "resolved"
        k_exact = (2.55**2 - 2.45**2) / (2.55**2 + 2.45**2)
        assert out["k_raw"] == pytest.approx(k_exact, abs=1e-4)
        assert out["k_narrowband"] == pytest.approx(
            2 * 0.1 / 5.0, abs=1e-3)

    def test_unresolvable_single_peak_none(self):
        f = np.linspace(2.40e9, 2.60e9, 401)
        s21 = 0.5 * np.exp(1j * -np.linspace(0, 4, 401)) * np.ones(401)
        out = CALCULATOR_REGISTRY.get("k_split_pair").func(freq_hz=f, s21=s21)
        assert out["k_raw"] is None and out["quality"] == "single_peak"

    def test_bias_invert_monotone_loglog(self):
        f, s21 = _two_peak_s21(2.45, 2.55)
        raw = np.array([0.02, 0.04, 0.08])
        true = np.array([0.018, 0.0375, 0.077])
        out = CALCULATOR_REGISTRY.get("k_split_pair").func(freq_hz=f, s21=s21,
                                      bias_raw_grid=raw, bias_true_grid=true)
        expect = float(np.exp(np.interp(np.log(out["k_raw"]),
                                        np.log(raw), np.log(true))))
        assert out["k_corr"] == pytest.approx(expect, rel=1e-12)

    def test_cross_impl_with_runner(self):
        """注册键 vs runner 提取内核同输入逐位（跨实现漂移防护）。"""
        rng = np.random.default_rng(7)
        f = np.linspace(2.40e9, 2.60e9, 801)
        base = 0.35 + 0.5 / (1.0 + ((f / 1e9 - 2.47) / 0.012) ** 2)
        db = base + 0.05 * np.sin(f / 1e7) + rng.normal(0, 0.002, f.size)
        s21 = 10.0 ** (db / 20.0)
        out_reg = CALCULATOR_REGISTRY.get("k_split_pair").func(freq_hz=f, s21=s21)
        out_run = runner.mode_split_k(f, s21)
        assert out_reg["k_raw"] == out_run["k_raw"]
        assert out_reg["f1_ghz"] == out_run["f1_ghz"]
        assert out_reg["f2_ghz"] == out_run["f2_ghz"]
        assert out_reg["quality"] == out_run["pair"]["quality"]


class TestQeGroupDelay:
    def test_registry_key_present(self):
        assert "qe_group_delay" in CALCULATOR_REGISTRY.names()

    def _single_pole_s11(self, qe: float, f0_ghz: float = 2.5):
        """无耗单端口 Z_in=J²Z_res 反射合成：τmax=4Qe/ω0（C=4 口径）。"""
        f = np.linspace(2.40e9, 2.60e9, 4000)   # 偶数点避开 x=0 精确零
        x = 2.0 * qe * (f - f0_ghz * 1e9) / (f0_ghz * 1e9)
        # 短路桩反射相位过谐振递减（τ=−dφ/dω>0）；runner 合成链同号
        phase = 2.0 * np.arctan(1.0 / x) - np.pi
        return f, np.exp(1j * phase)

    def test_c4_exact_recovery(self):
        qe = 200.0
        f, s11 = self._single_pole_s11(qe)
        out = CALCULATOR_REGISTRY.get("qe_group_delay").func(freq_hz=f, s11=s11)
        assert out["qe"] == pytest.approx(qe, rel=2e-3)
        assert out["c"] == 4.0

    def test_cross_impl_with_runner(self):
        qe = 300.0
        f, s11 = self._single_pole_s11(qe)
        out_reg = CALCULATOR_REGISTRY.get("qe_group_delay").func(freq_hz=f,
                                          s11=s11, c=4.0)
        out_run = runner.extract_qe_point(f, s11, 4.0)
        assert out_reg["qe"] == out_run["qe_s11"]
        assert out_reg["a_fit_s"] == out_run["a_fit_s"]
        assert out_reg["f_res_ghz"] == out_run["f_res_ghz"]

    def test_c_knob_scales(self):
        qe = 150.0
        f, s11 = self._single_pole_s11(qe)
        o4 = CALCULATOR_REGISTRY.get("qe_group_delay").func(freq_hz=f, s11=s11,
                                     c=4.0)
        o2 = CALCULATOR_REGISTRY.get("qe_group_delay").func(freq_hz=f, s11=s11,
                                     c=2.0)
        assert o2["qe"] == pytest.approx(2.0 * o4["qe"], rel=1e-9)
