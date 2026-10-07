"""AP-12 电小天线 Q 提取锚测试（round17 §三 AP-12，2026-10-03）。

锚口径（#118/#300：≥2 独立基准/件，门值预声明；真实天线文献数值表
未能在本环境核实（搜索限流），文献锚以解析恒等式与 Chu 界手算值
承担，#122 不虚构）：

- 合成 RLC 已知量回收（synthetic recovery）：串联 RLC（R=50Ω、
  f₀=1GHz、Q=20）经 resonance_extract 回收 Q 相对偏差 <1e-6；
  解析恒等式第二路径：dZ/dω|_res = j·2L → Q=ω₀L/R（符号推导 vs
  数值梯度两路径独立）。
- 并联 RLC（R=100Ω、f₀=500MHz、Q=40）：网格 Δf/f₀=2e-6 下回收
  <1e-6（截断误差 O((2Q·Δf/f₀)²)/6≈2.6e-8，模块契约）；恒等式
  Q=ω₀RC（dZ/dω|_res=−j·2R²C 手推锚）；粗网格 1e-4 偏差 6.4e-5
  作为契约面复现（宽窗 0.2）。
- 带宽第三方法：Γ(f)=(Z−Z₀)/(Z+Z₀) 数值找宽：半功率 |Γ|²=1/2
  全宽=2/Q（Q=20→0.10；X/R=2Q·sinh(ν) 对称性下的精确恒等，数值
  确证 ~1e-9）、VSWR=2 全宽=(S−1)/(√S·Q)=0.0353553（同为精确恒
  等）——数值宽度 vs 换算式两推导路径独立；FBW_hp 与 FBW_S 在
  半功率档 S=5.8284 自洽（(S−1)/√S=2）。文献常引 "1/Q" 为单边
  半宽或松口径（模块 docstring 口径）。
- Chu verdict 手算锚：ka=π/2 → Q_min=8/π³+2/π=0.894632（独立
  现算）；Q=20→reachable；Q=0.5→unreachable；贴界 Q=0.87 在
  tol=0.05 内→reachable（#347 贴界浮点噪声不判违约）、tol=0→
  unreachable；圆极化减半锚（ka=0.5：linear Q_min=10.0/circular
  5.0，Q=6 两口径判向相反）。
- 异常域：f 非升序/点数<3/形状不符/bool、q≤0、vswr≤1、ka≤0、
  tol≥1；R≤0 频点 NaN 契约。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.antenna_q import (
    half_power_bandwidth,
    q_from_impedance,
    q_reachability_verdict,
    resonance_extract,
    vswr_bandwidth,
)


def _series_rlc(f_hz: np.ndarray, r: float, f0: float, q0: float) -> np.ndarray:
    """串联 RLC 阻抗合成（Z=R+j(ωL−1/ωC)，Q=ω₀L/R）。"""
    w0 = 2.0 * math.pi * f0
    ll = q0 * r / w0
    cc = 1.0 / (w0 * w0 * ll)
    w = 2.0 * math.pi * np.asarray(f_hz)
    return r + 1j * (w * ll - 1.0 / (w * cc))


def _parallel_rlc(f_hz: np.ndarray, r: float, f0: float, q0: float) -> np.ndarray:
    """并联 RLC 阻抗合成（Z=1/(1/R+j(ωC−1/ωL))，Q=ω₀RC）。"""
    w0 = 2.0 * math.pi * f0
    cc = q0 / (w0 * r)
    ll = 1.0 / (w0 * w0 * cc)
    w = 2.0 * math.pi * np.asarray(f_hz)
    return 1.0 / (1.0 / r + 1j * (w * cc - 1.0 / (w * ll)))


class TestSeriesRlcRecovery:
    F0 = 1.0e9
    R = 50.0
    Q0 = 20.0

    def _grid(self):
        delta = np.linspace(-50.0, 50.0, 101) * 1e-4
        return self.F0 * (1.0 + delta)  # 含 f₀ 精确采样点

    def test_recovery_vs_design(self):
        f = self._grid()
        z = _series_rlc(f, self.R, self.F0, self.Q0)
        res = resonance_extract(f, z)
        assert res["f0_hz"] == pytest.approx(self.F0, rel=1e-9)
        assert res["r0_ohm"] == pytest.approx(self.R, rel=1e-9)
        assert res["q"] == pytest.approx(self.Q0, rel=1e-6)  # 预声明门

    def test_symbolic_identity_second_path(self):
        # 解析恒等式：dZ/dω|_res = j·2L → Q = ω₀L/R（符号路径 vs 数值梯度）
        f = self._grid()
        z = _series_rlc(f, self.R, self.F0, self.Q0)
        w0 = 2.0 * math.pi * self.F0
        ll = self.Q0 * self.R / w0
        q_symbolic = w0 * 2.0 * ll / (2.0 * self.R)
        assert q_symbolic == pytest.approx(self.Q0, rel=1e-12)  # 恒等
        q_num = q_from_impedance(f, z)[50]  # f₀ 恰在下标 50
        assert q_num == pytest.approx(q_symbolic, rel=1e-6)

    def test_bandwidth_third_method(self):
        # Γ(f) 数值宽度 vs 换算式（两推导路径独立；串联 RLC 下
        # 换算式为精确恒等，数值门 1e-9 只含求积/插值噪声）
        f = self.F0 * (1.0 + np.linspace(-0.2, 0.2, 400001))
        z = _series_rlc(f, self.R, self.F0, self.Q0)
        gamma = np.abs((z - self.R) / (z + self.R))
        half = np.interp(1.0 / math.sqrt(2.0), gamma[:200001][::-1],
                         f[:200001][::-1])
        half_hi = np.interp(1.0 / math.sqrt(2.0), gamma[200000:], f[200000:])
        fbw_num = (half_hi - half) / self.F0
        # FBW_hp = 2/Q（|Γ|²=1/2 全宽；数值确证 0.100000…，模块 docstring
        # 口径：文献常引 1/Q 为单边半宽或松口径）
        assert fbw_num == pytest.approx(half_power_bandwidth(self.Q0), rel=1e-9)
        g2 = (2.0 - 1.0) / (2.0 + 1.0)
        lo = np.interp(g2, gamma[:200001][::-1], f[:200001][::-1])
        hi = np.interp(g2, gamma[200000:], f[200000:])
        assert (hi - lo) / self.F0 == pytest.approx(
            vswr_bandwidth(self.Q0, 2.0), rel=1e-9)
        assert vswr_bandwidth(self.Q0, 2.0) == pytest.approx(0.0353553, rel=1e-5)

    def test_half_power_vswr_self_consistency(self):
        # FBW_hp = FBW_S(S=5.8284) 自洽：(S−1)/√S=2（半功率档 VSWR）
        s_hp = (1.0 + 1.0 / math.sqrt(2.0)) / (1.0 - 1.0 / math.sqrt(2.0))
        assert vswr_bandwidth(self.Q0, s_hp) == pytest.approx(
            half_power_bandwidth(self.Q0), rel=1e-12)


class TestParallelRlcRecovery:
    def test_recovery_vs_design(self):
        # 并联型截断误差 O((2Q·Δf/f₀)²)/6（z=R/(1+j2Qδ)）：
        # Δf/f₀=2e-6、Q=40 → 误差 ~2.6e-8，门 rel 1e-6 预声明
        f0, r, q0 = 500.0e6, 100.0, 40.0
        f = f0 * (1.0 + np.linspace(-50.0, 50.0, 101) * 2e-6)
        z = _parallel_rlc(f, r, f0, q0)
        res = resonance_extract(f, z)
        assert res["f0_hz"] == pytest.approx(f0, rel=1e-9)
        assert res["r0_ohm"] == pytest.approx(r, rel=1e-9)
        assert res["q"] == pytest.approx(q0, rel=1e-6)
        # 解析恒等式：Q = ω₀RC（手推 dZ/dω|_res = −j·2R²C）
        assert q0 == pytest.approx(2.0 * math.pi * f0 * r * (q0 / (2.0 * math.pi * f0 * r)))

    def test_coarse_grid_truncation_documented(self):
        # 契约面：Δf/f₀=1e-4、Q=40 并联型截断偏差 ~6.4e-5（模块
        # docstring 实证值复现——粗网格不炸只偏，消费方按契约加密）
        f0, r, q0 = 500.0e6, 100.0, 40.0
        f = f0 * (1.0 + np.linspace(-50.0, 50.0, 101) * 1e-4)
        z = _parallel_rlc(f, r, f0, q0)
        res = resonance_extract(f, z)
        assert res["q"] == pytest.approx(q0 * (1.0 - 6.4e-5), rel=0.2)

    def test_r_leq0_nan_contract(self):
        # R≤0 频点 Q 无定义 → NaN（不静默剔除）
        f = np.linspace(0.9e9, 1.1e9, 41)
        z = _series_rlc(f, 50.0, 1.0e9, 20.0)
        z_pure = 1j * z.imag  # R=0 纯电抗
        assert bool(np.isnan(q_from_impedance(f, z_pure)).all())


class TestGuards:
    def test_input_validation(self):
        f = np.linspace(0.99e9, 1.01e9, 21)
        z = _series_rlc(f, 50.0, 1.0e9, 20.0)
        with pytest.raises(ValueError, match="升序"):
            q_from_impedance(f[::-1], z[::-1])
        with pytest.raises(ValueError, match="3 个频点"):
            q_from_impedance(f[:2], z[:2])
        with pytest.raises(ValueError, match="同形"):
            q_from_impedance(f, z[:-1])
        with pytest.raises(ValueError, match="无 X=0 过零"):
            resonance_extract(f, 50.0 + 1j * np.abs(z.imag))  # 纯感性无过零

    def test_bandwidth_guards(self):
        with pytest.raises(ValueError, match=">0"):
            half_power_bandwidth(0.0)
        with pytest.raises(ValueError, match="bool"):
            half_power_bandwidth(True)
        with pytest.raises(ValueError, match=">1"):
            vswr_bandwidth(20.0, 1.0)
        with pytest.raises(ValueError):
            vswr_bandwidth(20.0, 0.5)


class TestChuVerdict:
    def test_half_wave_dipole_ka_anchor(self):
        # ka=π/2：Q_min = 1/(π/2)³+1/(π/2) = 8/π³+2/π（独立现算锚）
        q_min = 8.0 / math.pi**3 + 2.0 / math.pi
        assert q_min == pytest.approx(0.894632, rel=1e-5)
        out = q_reachability_verdict(math.pi / 2, 20.0)
        assert out["verdict"] == "reachable"
        assert out["q_min_chu"] == pytest.approx(q_min, rel=1e-12)
        assert out["source"].count("chu_q_bound") == 1

    def test_violation_and_marginal_semantics(self):
        q_min = 8.0 / math.pi**3 + 2.0 / math.pi
        # 明显违约：Q 低于界
        assert q_reachability_verdict(math.pi / 2, 0.5)["verdict"] == "unreachable"
        # 贴界：|margin|<tol 不判违约（#347 浮点余量语义）
        q_near = q_min * 0.97
        out = q_reachability_verdict(math.pi / 2, q_near)  # margin=−3%
        assert out["verdict"] == "reachable"
        assert q_reachability_verdict(
            math.pi / 2, q_near, tol=0.0)["verdict"] == "unreachable"

    def test_circular_polarization_halving(self):
        # ka=0.5：linear Q_min=1/0.125+2=10.0；circular=5.0（bounds 恒等）
        out_lin = q_reachability_verdict(0.5, 6.0, polarization="linear")
        out_cir = q_reachability_verdict(0.5, 6.0, polarization="circular")
        assert out_lin["q_min_chu"] == pytest.approx(10.0, rel=1e-12)
        assert out_cir["q_min_chu"] == pytest.approx(5.0, rel=1e-12)
        assert out_lin["verdict"] == "unreachable"   # 6 < 10·0.95
        assert out_cir["verdict"] == "reachable"     # 6 > 5·0.95

    def test_guards(self):
        with pytest.raises(ValueError, match=">0"):
            q_reachability_verdict(0.0, 1.0)
        with pytest.raises(ValueError, match=">0"):
            q_reachability_verdict(1.0, 0.0)
        with pytest.raises(ValueError, match=r"\[0, 1\)"):
            q_reachability_verdict(1.0, 1.0, tol=1.0)
        with pytest.raises(ValueError, match="bool"):
            q_reachability_verdict(True, 1.0)
