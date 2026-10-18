"""aurora_e W2-S9：EC-2 multiline TRL εr/tan_d 不确定度传播单测。

mtrl_er_tand_uncertainty（calc_families/mtrl_uncertainty.py）。

裁判口径（#118 双来源；预声明判据见模块 docstring，先写后跑 #122）：

- **名义链合成回收**：已知 (4.4, 0.02) → 正向 → GUM 链名义值逐位回代
  （er_eff=(βc/ω)² 恒等 + er/tanδ 反演回收机器精度）；
- **εeff 通道精确恒等式**：长度通道 u(εeff)/εeff = 2·u_ΔL/ΔL 逐位；
  噪声通道 = 2·σ_Δφ/(β·ΔL) 本文件独立重算；
- **支配渐近式**：纯公差（σ_S=0）→ dominant=length 逐频；纯噪声
  （u_L=0）→ dominant=noise 逐频；
- **单调/守卫**：u_er 随 u_lengths 与 sigma_s 单调增（线性一阶的直接
  后果）；n_mc=0 的 GUM-only 档可用且 envelope 无 mc 键数值；
- **G4-MC 门**：k=2 GUM 区间对 MC 抽样覆盖率 ≥95%（JCGM 101）+
  GUM/MC 标准差比 ∈ [1.0, 4.0]（保守方向声明，实测 1.4~3.5）——
  固定 seed 完全可复现；
- **噪声标度**：σ_S×2 → GUM 噪声通道 ×2（一阶线性）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calc_families.mtrl_uncertainty import (
    mtrl_er_tand_gum,
    mtrl_er_tand_montecarlo,
    mtrl_er_tand_uncertainty,
)

W_MM, H_MM, ER, TAND = 0.6, 0.254, 4.4, 0.02
LENGTHS = [0.005, 0.045]
FREQS = [2.0, 5.0, 10.0]


def _gum(**kw):
    f_hz = kw.pop("f_hz", [f * 1e9 for f in FREQS])
    return mtrl_er_tand_gum(
        f_hz, kw.pop("w_mm", W_MM), kw.pop("h_mm", H_MM),
        kw.pop("er", ER), kw.pop("tan_d", TAND),
        kw.pop("line_lengths_m", LENGTHS),
        kw.pop("u_lengths_m", 5e-5), kw.pop("sigma_s", 1e-3), **kw)


class TestNominalChain:
    def test_er_eff_exact_identity(self) -> None:
        """εeff = (βc/ω)² 平方律恒等（链内逐位自洽）。"""
        g = _gum()
        for i, f in enumerate(FREQS):
            er_eff_ref = (g["beta_rad_m"][i] * 299792458.0
                          / (2 * math.pi * f * 1e9)) ** 2
            assert g["er_eff"][i] == pytest.approx(er_eff_ref, rel=1e-12)
        # 名义 εeff 与微带物理带一致（Wheeler 粗核：q∈(0.5,1)）
        assert 1.0 + 0.5 * (ER - 1) < g["er_eff"][0] \
            < 1.0 + 0.95 * (ER - 1)

    def test_mc_nominal_recovery_machine_precision(self) -> None:
        """MC 夹具名义回收：er/tanδ 回代真值（1e-6 内，G1 同款）。"""
        mc = mtrl_er_tand_montecarlo(
            FREQS, W_MM, H_MM, ER, TAND, LENGTHS, [0.0, 0.0], 0.0,
            n_mc=4, seed=1)
        assert np.allclose(mc["er_mc_mean"], ER, rtol=1e-6)
        assert np.allclose(mc["tan_d_mc_mean"], TAND, atol=1e-9)


class TestChannelIdentities:
    def test_length_channel_exact(self) -> None:
        """长度通道 u(εeff)/εeff = 2·u_ΔL/ΔL 逐位（平方律精确恒等式）。"""
        g = _gum(sigma_s=0.0)
        u_rel_ref = 2.0 * math.sqrt(2.0) * 5e-5 / 0.04
        for v in g["u_eps_eff_rel_length"]:
            assert v == pytest.approx(u_rel_ref, rel=1e-12)

    def test_noise_channel_independent_recompute(self) -> None:
        """噪声通道 u(εeff)/εeff = 2·σ_Δφ/(β·ΔL) 本文件独立重算。"""
        sigma_s = 1e-3
        g = _gum(u_lengths_m=[0.0, 0.0], sigma_s=sigma_s)
        for i in range(len(FREQS)):
            alpha = g["alpha_np_m"][i]
            beta = g["beta_rad_m"][i]
            sigma_dphi = sigma_s * math.sqrt(
                math.exp(2 * alpha * LENGTHS[0])
                + math.exp(2 * alpha * LENGTHS[1]))
            ref = 2.0 * sigma_dphi / (beta * 0.04)
            assert g["u_eps_eff_rel_noise"][i] == pytest.approx(
                ref, rel=1e-12)

    def test_dominant_channel_asymptotes(self) -> None:
        """单误差项支配渐近：纯公差→length、纯噪声→noise 逐频。"""
        g_len = _gum(sigma_s=0.0)
        assert set(g_len["dominant_channel"]) == {"length"}
        g_n = _gum(u_lengths_m=[0.0, 0.0], sigma_s=1e-3)
        assert set(g_n["dominant_channel"]) == {"noise"}


class TestMonotonicityAndEnvelope:
    def test_u_er_scales_with_inputs(self) -> None:
        """u_er 对 u_lengths 与 sigma_s 一阶线性单调增。"""
        base = np.array(_gum()["u_er_gum"])
        d1 = np.array(_gum(u_lengths_m=1e-4)["u_er_gum"])
        d2 = np.array(_gum(sigma_s=2e-3)["u_er_gum"])
        assert np.all(d1 > base) and np.all(d2 > base)
        # 噪声通道线性：σ×2 → 噪声分量 ×2（公差通道不变）
        n1 = np.array(_gum(u_lengths_m=[0.0, 0.0],
                           sigma_s=1e-3)["u_er_gum"])
        n2 = np.array(_gum(u_lengths_m=[0.0, 0.0],
                           sigma_s=2e-3)["u_er_gum"])
        assert np.allclose(n2, 2.0 * n1, rtol=1e-12)

    def test_gum_only_envelope(self) -> None:
        """n_mc=0：GUM-only 档可用，mc 键=None，锚 gate 注记在场。"""
        r = mtrl_er_tand_uncertainty(
            freq_ghz=FREQS, w_mm=W_MM, h_mm=H_MM, er=ER, tan_d=TAND,
            line_lengths_m=LENGTHS, u_lengths_m=5e-5, sigma_s=1e-3,
            n_mc=0)
        assert r["mc"] is None and "u_er_gum" in r
        assert "anchor_gate_note" in r

    def test_guards(self) -> None:
        """单线/同长/负 σ/u 非法显式拒绝。"""
        with pytest.raises(ValueError, match="至少"):
            _gum(line_lengths_m=[0.005])
        with pytest.raises(ValueError, match="互异"):
            _gum(line_lengths_m=[0.01, 0.01])
        with pytest.raises(ValueError, match="sigma_s"):
            _gum(sigma_s=-1.0)
        with pytest.raises(ValueError, match="不确定度"):
            _gum(u_lengths_m=-1e-5)


    def test_mc_freq_guard_rejects_nonfinite(self) -> None:
        """MC 独立入口 freq 验证补 isfinite（W6-S26 P2-3，与 GUM 通道
        :178-180 同款；NaN 恰好溜过 `<=0` 判据，组合入口经 GUM 前置拦截，
        本钉=独立入口同防）。"""
        for bad in ([2.0, float("nan")], [float("inf")]):
            with pytest.raises(ValueError, match="有限"):
                mtrl_er_tand_montecarlo(
                    bad, W_MM, H_MM, ER, TAND, LENGTHS, 5e-5, 1e-3,
                    n_mc=4, seed=1)


class TestG4MonteCarloGate:
    def test_coverage_and_ratio_domain(self) -> None:
        """G4-MC：覆盖率 ≥95% + 比率 ∈[1.0,4.0]（预声明；固定 seed）。"""
        r = mtrl_er_tand_uncertainty(
            freq_ghz=FREQS, w_mm=W_MM, h_mm=H_MM, er=ER, tan_d=TAND,
            line_lengths_m=LENGTHS, u_lengths_m=5e-5, sigma_s=1e-3,
            n_mc=150, seed=20261018)
        assert r["mc_pass"] is True
        mc = r["mc"]
        assert mc["coverage_er_pass"] and mc["coverage_tand_pass"]
        for v in mc["coverage_er_k2"] + mc["coverage_tand_k2"]:
            assert v >= 0.95
        for v in mc["gum_over_mc_ratio_er"] + mc["gum_over_mc_ratio_tand"]:
            assert 1.0 <= v <= 4.0
        # 保守方向：GUM 带不窄于 MC 经验 std（锚 gate 安全方向）
        for ratio_val in mc["gum_over_mc_ratio_er"]:
            assert ratio_val >= 1.0

    def test_determinism_fixed_seed(self) -> None:
        """同 seed 逐位一致（确定性核 G15 口径）。"""
        kw = dict(freq_ghz=FREQS, w_mm=W_MM, h_mm=H_MM, er=ER, tan_d=TAND,
                  line_lengths_m=LENGTHS, u_lengths_m=5e-5, sigma_s=1e-3,
                  n_mc=20, seed=7)
        import json
        r1 = json.dumps(mtrl_er_tand_uncertainty(**kw), sort_keys=True)
        r2 = json.dumps(mtrl_er_tand_uncertainty(**kw), sort_keys=True)
        assert r1 == r2

    def test_mc_std_small_vs_band(self) -> None:
        """MC 经验带窄于 GUM 带（保守方向的数值面，供紧带消费）。"""
        mc = mtrl_er_tand_montecarlo(
            FREQS, W_MM, H_MM, ER, TAND, LENGTHS, 5e-5, 1e-3,
            n_mc=60, seed=42)
        g = _gum()
        assert np.all(mc["er_mc_std"] <= np.array(g["u_er_gum"]))


class TestRegisteredKey:
    def test_service_run_envelope(self) -> None:
        from rfauto.service.calculator_service import run_calculator
        res = run_calculator("mtrl_er_tand_uncertainty", {
            "freq_ghz": FREQS, "w_mm": W_MM, "h_mm": H_MM, "er": ER,
            "tan_d": TAND, "line_lengths_m": LENGTHS,
            "u_lengths_m": 5e-5, "sigma_s": 1e-3, "n_mc": 0})
        assert res["ok"] and res["result"]["mc"] is None
        res2 = run_calculator("mtrl_er_tand_uncertainty", {
            "freq_ghz": FREQS, "w_mm": W_MM, "h_mm": H_MM, "er": ER,
            "tan_d": TAND, "line_lengths_m": LENGTHS,
            "u_lengths_m": 5e-5, "sigma_s": 1e-3})
        assert res2["ok"] and res2["result"]["mc"]["n_mc"] == 120
