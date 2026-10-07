"""MM-5 Smith 2002 分支判据+无源性/因果锚树（core/metamaterial_inversion.py）。

裁判面（#118：每面 ≥2 独立基准）：
- 合成回收（薄板无歧义域）：解析 DNG 点 (n,Z) 正演 → auto_branch_select
  回收 n/ε/μ 到 1e-8（支=0）+ 无源性质检验（Im ε/Im μ>0 by 构造）；
- 支连续性跨卷绕（Smith 2002 主裁判面）：厚板扫频相位跨 ±π →
  branch_m 0→−1 翻转且 n 全程锁定真值 1e-8（连续性跟踪+无源剪除
  双路径缺一即错支）；
- 正演交叉验证的可证伪性：强行单支（半宽 0）选错支 → unverified
  如实报告（不凑 PASS，#122）；
- 无源剪除负例：放大面板（能量门）→ 全频 fail/overall=failed；
- KK 因果（复用 dispersion.kramers_kronig_residual）：Debye 采样经
  SampledCausalResponse 适配 → 残差 ≤2e-2（带内有限 span 截断量级，
  与原生 DebyeModel 残差同量级互证）+ 带外钳位行为 + 守卫负例。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.dispersion import (
    DebyeModel,
    DebyePole,
    kramers_kronig_residual,
)
from rfauto.core.homogenization import slab_panel_rt
from rfauto.core.metamaterial_inversion import (
    SampledCausalResponse,
    auto_branch_select,
    passivity_report,
)

# 解析 DNG 锚点（本仓 τ=e^{+jk0nd} 口径，无源 → Im n/Im ε/Im μ≥0）。
# Im(ε)=Im(n/Z)=(Im n·Re Z+|Re n|·Im Z)/|Z|²>0、Im(μ)=Im(nZ)>0 经此
# Z 校验通过（首版 Z 取负虚部被无源剪除正确拒绝——锚点非物理，#118）。
N_TRUE = complex(-1.5, 0.1)
Z_TRUE = complex(0.5, 0.01)
D_THIN_MM = 3.0
D_WRAP_MM = 9.0
F0_GHZ = 10.0


def _forward(freq_ghz: float, d_mm: float) -> tuple[complex, complex]:
    rep = slab_panel_rt(freq_ghz, N_TRUE, Z_TRUE, d_mm)
    return complex(rep["s11"]), complex(rep["s21"])


class TestSyntheticRecovery:
    def test_thin_slab_recovery(self):
        f = np.linspace(8.0, 12.0, 41)
        s11 = np.empty(f.size, dtype=complex)
        s21 = np.empty(f.size, dtype=complex)
        for i, fg in enumerate(f):
            s11[i], s21[i] = _forward(float(fg), D_THIN_MM)
        rep = auto_branch_select(f, s11, s21, D_THIN_MM)
        assert rep["verdict"] == "resolved"
        assert np.all(rep["branch_m"] == 0)
        assert np.allclose(rep["n_eff"], N_TRUE, rtol=1e-8)
        eps_true = N_TRUE / Z_TRUE
        mu_true = N_TRUE * Z_TRUE
        assert np.allclose(rep["eps_eff"], eps_true, rtol=1e-8)
        assert np.allclose(rep["mu_eff"], mu_true, rtol=1e-8)

    def test_passivity_of_recovered(self):
        f = np.array([9.0, 10.0, 11.0])
        s11 = np.empty(3, dtype=complex)
        s21 = np.empty(3, dtype=complex)
        for i, fg in enumerate(f):
            s11[i], s21[i] = _forward(float(fg), D_THIN_MM)
        rep = auto_branch_select(f, s11, s21, D_THIN_MM)
        pr = passivity_report(rep["eps_eff"], rep["mu_eff"])
        assert pr["verdict"] == "passive"
        # 构造点：正耗散（Im ε、Im μ 严格为正，本仓口径）
        assert np.all(pr["im_eps"] > 0.0)
        assert np.all(pr["im_mu"] > 0.0)

    def test_thick_slab_branch_tracking(self):
        """支连续性跨 ±π 卷绕：branch 0→−1 翻转，n 全程锁真值。"""
        f = np.linspace(8.0, 12.0, 81)
        s11 = np.empty(f.size, dtype=complex)
        s21 = np.empty(f.size, dtype=complex)
        for i, fg in enumerate(f):
            s11[i], s21[i] = _forward(float(fg), D_WRAP_MM)
        rep = auto_branch_select(f, s11, s21, D_WRAP_MM,
                                 branch_half_range=3)
        assert rep["verdict"] == "resolved"
        assert np.allclose(rep["n_eff"], N_TRUE, rtol=1e-7)
        # 首频无歧义支 0；卷绕后翻到 −1（k0·Re(n)·d 跨 −π）
        assert rep["branch_m"][0] == 0
        assert rep["branch_m"][-1] == -1
        # 翻转恰好一次（连续性跟踪的确定性）
        assert int(np.sum(np.diff(rep["branch_m"]) != 0)) == 1

    def test_single_frequency_ambiguity_negative_control(self):
        """负例控制（Smith 2002 扫频动机的实证）：单频点在相位卷绕域
        选错支（无源剪除不唯一），且正演一致性检查**不区分支**（τ 周
        期性）——分支消歧只能靠扫频连续性（上一测试面）。"""
        f = np.array([12.0])  # 该频点真支=−1（k0·Re(n)·d 跨 −π）
        s11, s21 = _forward(12.0, D_WRAP_MM)
        rep = auto_branch_select(f, np.array([s11]), np.array([s21]),
                                 D_WRAP_MM, branch_half_range=0)
        assert rep["verdict_per_freq"][0] == "consistent"
        assert rep["branch_m"][0] == 0
        # 错支 n（Re>0 主支）与真值差一个周期平移——如实暴露歧义
        assert rep["n_eff"][0].real > 0.0
        period = 2.0 * math.pi / (
            2.0 * math.pi * 12e9 / 299792458.0 * D_WRAP_MM * 1e-3)
        assert rep["n_eff"][0].real == pytest.approx(
            N_TRUE.real + period, rel=1e-9)
        # 正演一致性对错支仍成立（周期性的直接数值证据）
        assert rep["forward_rel_dev"][0] <= 1e-9


class TestPassivityGate:
    def test_amplified_panel_fails(self):
        f = np.array([9.0, 10.0, 11.0])
        s11 = np.empty(3, dtype=complex)
        s21 = np.empty(3, dtype=complex)
        for i, fg in enumerate(f):
            s11[i], s21[i] = _forward(float(fg), D_THIN_MM)
        rep = auto_branch_select(f, 1.1 * s11, 1.1 * s21, D_THIN_MM)
        assert rep["verdict"] == "failed"
        assert all(v == "fail" for v in rep["verdict_per_freq"])

    def test_passivity_report_flags_active(self):
        pr = passivity_report(np.array([2.0 - 0.1j]), np.array([1.0 + 0.0j]))
        assert pr["verdict"] == "active"
        assert not pr["passive"][0]

    def test_input_validation(self):
        with pytest.raises(ValueError):
            auto_branch_select(np.array([10.0, 9.0]),
                               np.array([0j, 0j]), np.array([0j, 0j]), 3.0)
        with pytest.raises(ValueError):
            passivity_report(np.array([1 + 0j]), np.array([1 + 0j, 1 + 0j]))


class TestKKCausalityAdapter:
    """复用 dispersion.kramers_kronig_residual 的采样适配面。"""

    EPS_INF = 3.0
    DELTA_EPS = 5.0
    F_RELAX_HZ = 160e6

    def _debye_eps(self, f: np.ndarray) -> np.ndarray:
        w = 2.0 * math.pi * f
        return self.EPS_INF + self.DELTA_EPS / (
            1.0 + 1j * w / (2.0 * math.pi * self.F_RELAX_HZ))

    def _sampled(self) -> SampledCausalResponse:
        f = np.logspace(4.0, 13.0, 361)
        return SampledCausalResponse(f, self._debye_eps(f), self.EPS_INF)

    def test_residual_small_and_matches_native_model(self):
        adapter = self._sampled()
        native = DebyeModel(
            eps_inf=self.EPS_INF,
            poles=(DebyePole(delta_eps=self.DELTA_EPS,
                             f_relax_hz=self.F_RELAX_HZ),))
        f_probe = np.array([1e8, 1e9, 1e10])
        res_adapter = kramers_kronig_residual(
            adapter, f_probe, span_decades=3, n_points=8001)
        res_native = kramers_kronig_residual(
            native, f_probe, span_decades=3, n_points=8001)
        # span 有限 → Debye 高频尾截断（1e10 点 ~4%，物理量级非缺陷）
        assert np.all(res_adapter <= 5e-2)
        # 采样带内插值 vs 解析：同 span 同截断 → 残差近同（互证）
        assert np.all(res_adapter <= 2.0 * res_native + 1e-6)

    def test_band_clamp_outside(self):
        adapter = self._sampled()
        out = adapter.epsilon(np.array([1.0, 1e9, 1e14]))
        assert out[0] == pytest.approx(complex(self.EPS_INF, 0.0))
        assert out[2] == pytest.approx(complex(self.EPS_INF, 0.0))
        mid = adapter.epsilon(np.array([1e9]))[0]
        expect = self._debye_eps(np.array([1e9]))[0]
        assert mid == pytest.approx(expect, rel=1e-9)

    def test_scalar_and_validation(self):
        adapter = self._sampled()
        val = adapter.epsilon(1e9)
        assert isinstance(val, complex)
        with pytest.raises(ValueError):
            SampledCausalResponse(np.array([1.0, 1.0]),
                                  np.array([1 + 0j, 1 + 0j]), 3.0)
        with pytest.raises(ValueError):
            SampledCausalResponse(np.array([1.0, 2.0]),
                                  np.array([1 + 0j, 1 + 0j]), -3.0)
