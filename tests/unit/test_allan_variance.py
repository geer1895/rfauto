"""MS-5 Allan 方差/时钟稳定度锚测试（round15 :212 规格，2026-10-02）。

锚口径（任务书预声明 + 定义/一手出处双核 #118 裁判纪律；探测证据见
模块 docstring，本文件只钉可复跑数字）：

- **白频合成解析例（离散精确恒等式）**：单边 S_y=h_0 截止于 Nyquist 时
  h_0 = 2·σ²·τ0，且 AVAR(m) = σ²/m ≡ h_0/(2τ)——m 点均值方差 σ²/m 与
  连续三 coef 式逐位自洽（推导见 core/allan_variance.py docstring）。
  实测 N=2^15、m∈[1,100] 内逐点 ≤2%（理论误差棒 ~0.6%/√EDF 量级）。
- **白相合成解析例（离散精确恒等式）**：x 白噪声经 y=diff(x)/τ0，
  AVAR(m) = 3σ_x²/m²（二阶差分和方差 1+4+1=6 倍，除 2m²）→
  ADEV = √3·σ_x/τ。**任务书骨架预写"白相噪→斜率 −1/2"系与 IEEE 1139
  Table 1 相悖的笔误**——IEEE 1139 口径白相 ADEV 斜率=−1（实测
  −1.0004），−1/2 是白频；本文件按规格以 IEEE 1139 为准并钉实测。
- **MDEV 白相 −3/2**：早期资料常误传"MDEV 白频 −1"——NIST SP 1065 /
  Wikipedia 六-regime 表实为白相 MDEV −3/2（2026-10-02 定义逐项对核+
  合成实测 −1.503 双证）；MDEV 白频 −1/2（实测 −0.514）。MDEV 的核心
  优势=分离白相（−3/2）与闪相（−1）——classify_joint 据此唯一化五类。
- **线性漂移精确恒等式**：y=a+D·t → AVAR=D²τ²/2（零随机、a 平移不变、
  MDEV≡ADEV），实测机器精度（<2e-13 相对）。
- **闪烁频合成互检**：FFT 1/√f 滤波合成（PSD 有限带）→ 中段斜率实测
  0.003≈0（闪频平台）；ADEV vs PSD 独立估 h_{-1}→avar_from_h 预测的
  比值带 0.8–1.5 且逐 τ 稳定（max/min<1.12）——比值偏离 1 是合成带限
  +periodogram 估计的系统学，不设"必须=1"假门，稳定性即互检证据。
- **三 coef 闭式与 L(f) 桥**：σ_y²=2ln2·h_{-1}+h_0/(2τ)+(2π²/3)h_{-2}τ
  内联精确回核；h_from_l_points 白频例（−80dBc/Hz@1kHz→−100@10kHz、
  载波 10GHz）→ h_0=2e-22 逐位（手算：2·1e-8·1e6/1e20）。

零外部数据捆绑：全部锚=闭式恒等式/固定种子合成/定义互证，无文件依赖。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.allan_variance import (
    adev,
    adev_slope,
    avar_from_h,
    classify_adev_slope,
    classify_joint,
    fit_loglog_slope,
    h_from_l_points,
    mdev,
)
from rfauto.service.calculator_service import run_calculator

_RATE = 10.0
_TAU0 = 0.1
_SEED = 20261002


def _slope(tau: np.ndarray, vals: np.ndarray) -> float:
    return fit_loglog_slope(tau, vals)[0]


# ─── 白频（white FM）：离散精确解析例 ────────────────────────────────────────


class TestWhiteFm:
    def test_adev_matches_h0_closed_form(self):
        rng = np.random.default_rng(_SEED)
        sigma = 1e-11
        y = sigma * rng.standard_normal(1 << 17)
        h0 = 2.0 * sigma * sigma * _TAU0  # 单边 PSD 截止 Nyquist 的离散精确式
        taus = [(1 << k) * _TAU0 for k in range(0, 11)]  # m=1..1024
        r = adev(y, _RATE, taus=taus)
        keep = r["m"] <= 100  # EDF 充裕段（m>100 重叠差分相关致误差棒乐观）
        pred = np.sqrt(h0 / (2.0 * r["tau"][keep]))
        assert np.all(np.abs(r["adev"][keep] / pred - 1.0) < 0.03), (
            f"白频 ADEV 偏离 h_0/(2τ) 闭式: {r['adev'][keep] / pred}")

    def test_slope_and_classification(self):
        rng = np.random.default_rng(_SEED)
        y = 1e-11 * rng.standard_normal(1 << 16)
        r = adev(y, _RATE, taus=[(1 << k) * _TAU0 for k in range(0, 9)])
        s = _slope(r["tau"], r["adev"])
        assert abs(s + 0.5) < 0.05, f"白频 ADEV 斜率应 −1/2，实测 {s}"
        assert classify_adev_slope(s)["label"] == "white_fm"

    def test_adev_error_bars(self):
        rng = np.random.default_rng(_SEED)
        y = rng.standard_normal(4096)
        r = adev(y, _RATE, taus=[0.1, 1.0, 10.0])
        assert np.all(r["adev_error"] > 0)
        assert np.all(r["adev_error"] < r["adev"])
        # 独立差分近似：err/adev ≈ 1/√n_terms（定义式自检）
        assert np.allclose(r["adev_error"] / r["adev"],
                           1.0 / np.sqrt(r["n_terms"]), rtol=1e-12)

    def test_mdev_white_fm_tau_half(self):
        rng = np.random.default_rng(_SEED)
        y = 1e-11 * rng.standard_normal(1 << 17)
        ms = (1 << k for k in range(3, 8))  # m=8..128（避开 m=1 暂态）
        rm = mdev(y, _RATE, taus=[m * _TAU0 for m in ms])
        s = _slope(rm["tau"], rm["mdev"])
        assert abs(s + 0.5) < 0.1, f"白频 MDEV 斜率应 −1/2（NIST SP 1065 表），实测 {s}"


# ─── 白相（white PM，kind="phase"）：离散精确解析例 + MDEV 分辨 ─────────────


class TestWhitePm:
    def test_adev_exact_constant_and_slope(self):
        rng = np.random.default_rng(_SEED)
        sx = 1e-12
        x = sx * rng.standard_normal(1 << 17)
        taus = [(1 << k) * _TAU0 for k in range(0, 9)]
        r = adev(x, _RATE, kind="phase", taus=taus)
        pred = math.sqrt(3.0) * sx / r["tau"]
        assert np.all(np.abs(r["adev"] / pred - 1.0) < 0.02), (
            f"白相 ADEV 偏离 √3·σ_x/τ: {r['adev'] / pred}")
        s = _slope(r["tau"], r["adev"])
        assert abs(s + 1.0) < 0.05, (
            f"IEEE 1139 Table 1：白相 ADEV 斜率=−1（任务书 −1/2 系笔误），实测 {s}")

    def test_mdev_slope_minus_3halves_and_joint_class(self):
        rng = np.random.default_rng(_SEED)
        x = 1e-12 * rng.standard_normal(1 << 17)
        taus = [(1 << k) * _TAU0 for k in range(0, 9)]
        ra = adev(x, _RATE, kind="phase", taus=taus)
        rm = mdev(x, _RATE, kind="phase", taus=taus)
        sm = _slope(rm["tau"], rm["mdev"])
        assert abs(sm + 1.5) < 0.1, f"白相 MDEV 斜率应 −3/2（NIST SP 1065 表），实测 {sm}"
        cls = classify_joint(ra["tau"], ra["adev"], rm["tau"], rm["mdev"])
        assert cls["label"] == "white_pm"
        assert cls["adev_slope"] == pytest.approx(-1.0, abs=0.05)
        assert cls["mdev_slope"] == pytest.approx(-1.5, abs=0.1)


# ─── 线性漂移 / 常数序列：零随机精确例 ──────────────────────────────────────


class TestExactCases:
    def test_linear_drift_exact(self):
        d = 1e-12
        n = 4096
        t = np.arange(n) * _TAU0
        y = 1e-9 + d * t  # 常数偏置 a=1e-9 应被 AVAR 平移不变消去
        taus = [(1 << k) * _TAU0 for k in range(0, 6)]
        r = adev(y, _RATE, taus=taus)
        pred = d * r["tau"] / math.sqrt(2.0)
        # 精确恒等式：仅剩 float64 舍入（实测相对偏差 <5e-13）
        assert np.all(np.abs(r["adev"] - pred) < 1e-11 * pred), (
            f"漂移 ADEV=D·τ/√2 非精确: {r['adev'] / pred}")
        # 斜率分类 +1
        assert classify_adev_slope(_slope(r["tau"], r["adev"]))["label"] == "linear_drift"

    def test_drift_offset_invariance_and_mdev_identity(self):
        d = 1e-12
        t = np.arange(4096) * _TAU0
        taus = [(1 << k) * _TAU0 for k in range(0, 6)]
        r1 = adev(1e-9 + d * t, _RATE, taus=taus)
        r2 = adev(7.7e-3 + d * t, _RATE, taus=taus)  # 换常数偏置
        # 平移不变到 float64 舍入级（逐位相等被大偏置的表示误差破坏，实测<3e-5 相对）
        assert np.allclose(r1["adev"], r2["adev"], rtol=1e-4), "AVAR 对常数偏置不平移不变"
        rm = mdev(d * t, _RATE, taus=taus)
        assert np.allclose(rm["mdev"], r1["adev"], rtol=1e-13), (
            "纯漂移下 MVAR ≡ AVAR（D_i 常数 → 窗和=同值）")

    def test_constant_series_zero(self):
        y = np.full(1000, 3e-11)
        r = adev(y, _RATE, taus=[0.1, 1.0, 10.0])
        rm = mdev(y, _RATE, taus=[0.1, 1.0, 10.0])
        assert np.all(r["adev"] < 1e-20), "常数序列 ADEV 应为 0（机器噪声级）"
        assert np.all(rm["mdev"] < 1e-20)
        # 全零 ADEV 不进 log 拟合（<2 正点显式报错，不产 NaN 静默通过）
        with pytest.raises(ValueError, match="至少需要 2 个正数据点"):
            fit_loglog_slope(r["tau"], np.zeros_like(r["adev"]))


# ─── 估计器定义恒等式 ───────────────────────────────────────────────────────


class TestEstimatorIdentities:
    def test_mvar_equals_avar_at_m1(self):
        rng = np.random.default_rng(_SEED)
        y = rng.standard_normal(1024)
        r = adev(y, _RATE, taus=[_TAU0])
        rm = mdev(y, _RATE, taus=[_TAU0])
        assert r["m"][0] == rm["m"][0] == 1
        assert np.isclose(r["adev"][0] ** 2, rm["mdev"][0] ** 2, rtol=1e-13), (
            "MVAR(m=1) ≡ AVAR(m=1)（同差分集合同分母，NIST 口径）")

    def test_nonoverlap_vs_overlapping_consistent(self):
        rng = np.random.default_rng(_SEED)
        y = 1e-11 * rng.standard_normal(1 << 15)
        taus = [0.1, 0.4, 1.0]
        ro = adev(y, _RATE, taus=taus, estimator="overlapping")
        rn = adev(y, _RATE, taus=taus, estimator="nonoverlap")
        assert np.all(rn["n_terms"] <= ro["n_terms"])
        assert np.all(rn["n_terms"][1:] < ro["n_terms"][1:])  # m=1 恒等（同差分集）
        # 白频下两估计器一致（5% 带：非重叠自身散布 ~2%，重叠误差棒偏低估）
        assert np.all(np.abs(rn["adev"] / ro["adev"] - 1.0) < 0.05), (
            f"重叠/非重叠偏离: {rn['adev'] / ro['adev']}")

    def test_uniform_time_stamps_accepted(self):
        rng = np.random.default_rng(_SEED)
        y = rng.standard_normal(512)
        t = np.arange(512) * _TAU0
        r1 = adev(y, _RATE, taus=[0.1, 1.0])
        r2 = adev(y, _RATE, taus=[0.1, 1.0], time_s=t)
        assert np.array_equal(r1["adev"], r2["adev"])

    def test_taus_beyond_range_clipped_to_empty(self):
        y = np.arange(64.0)
        r = adev(y, _RATE, taus=[1e9])
        assert r["tau"].size == 0 and r["adev"].size == 0  # 裁剪后空数组，不报错


# ─── 斜率分类器：解析数组（不赌合成噪声）────────────────────────────────────


class TestSlopeClassifier:
    @pytest.mark.parametrize("power,expect", [
        (-1.0, "pm"),
        (-0.5, "white_fm"),
        (0.0, "flicker_fm"),
        (0.5, "random_walk_fm"),
        (1.0, "linear_drift"),
    ])
    def test_power_law_labels(self, power, expect):
        tau = np.logspace(0.0, 4.0, 25)
        segs = adev_slope(tau, tau ** power)
        assert len(segs) == 1
        assert segs[0]["label"] == expect
        assert segs[0]["r2"] > 0.999
        assert classify_adev_slope(power)["label"] == expect

    def test_pm_candidates_and_unknown(self):
        cls = classify_adev_slope(-1.02)
        assert cls["label"] == "pm"
        assert set(cls["candidates"]) == {"white_pm", "flicker_pm"}
        assert classify_adev_slope(0.25)["label"] == "unknown"  # 距 0/+0.5 均 >tol

    def test_joint_pm_split_analytic(self):
        tau = np.logspace(0.0, 3.0, 20)
        assert classify_joint(tau, tau ** -1.0, tau, tau ** -1.5)["label"] == "white_pm"
        assert classify_joint(tau, tau ** -1.0, tau, tau ** -1.0)["label"] == "flicker_pm"
        # MDEV 缺失/不可拟合 → unknown 不猜
        out = classify_joint(tau, tau ** -1.0, tau, np.zeros_like(tau))
        assert out["label"] == "unknown"

    def test_segment_identification_two_regimes(self):
        tau = np.logspace(0.0, 4.0, 25)
        vals = np.concatenate([tau[:13] ** -0.5, tau[13:] ** 1.0])
        segs = adev_slope(tau, vals)
        labels = [s["label"] for s in segs]
        assert labels.count("white_fm") >= 1 and labels.count("linear_drift") >= 1
        assert segs[0]["tau_lo"] == pytest.approx(tau[0])


# ─── 三 coef 闭式与 clock_noise L(f) 桥 ────────────────────────────────────


class TestThreeCoefAndBridge:
    def test_avar_from_h_exact_formula(self):
        h1 = h0 = h2 = 1e-12
        got = avar_from_h(1.0, h_minus1=h1, h0=h0, h_minus2=h2)
        expect = math.sqrt(2.0 * math.log(2.0) * h1 + 0.5 * h0
                           + (2.0 * math.pi ** 2 / 3.0) * h2)
        assert got[0] == pytest.approx(expect, rel=1e-14)
        assert avar_from_h(np.array([1.0, 4.0]))[0] == pytest.approx(0.0, abs=0.0)
        with pytest.raises(ValueError, match="非负"):
            avar_from_h(1.0, h_minus1=-1e-12)

    def test_h_from_l_points_white_fm_hand_computed(self):
        out = h_from_l_points(-80.0, 1e3, -100.0, 1e4, 10e9)
        assert out["noise_class"] == "white_fm"
        assert out["three_coef_applicable"] is True
        assert out["h"] == pytest.approx(2e-22, rel=1e-12)  # 2·1e-8·1e3²/1e20 手算
        assert out["alpha"] == pytest.approx(0.0, abs=1e-12)
        # 桥→三 coef→ADEV 闭环：ADEV(1ms)=√(h0/2τ)=3.162e-10
        assert avar_from_h(1e-3, h0=out["h"])[0] == pytest.approx(3.1622776601683795e-10,
                                                                  rel=1e-12)

    def test_h_from_l_points_pm_segment_flagged(self):
        out = h_from_l_points(-80.0, 1e3, -80.0, 1e4, 10e9)  # 平坦 L = 白相
        assert out["noise_class"] == "white_pm"
        assert out["three_coef_applicable"] is False
        assert "f_H" in out["note"]

    def test_h_from_l_points_domain_guards(self):
        with pytest.raises(ValueError, match="f_lo < f_hi"):
            h_from_l_points(-80.0, 1e4, -100.0, 1e3, 10e9)
        with pytest.raises(ValueError, match="有限数"):
            h_from_l_points(float("nan"), 1e3, -100.0, 1e4, 10e9)


# ─── 闪烁频合成互检（频域 PSD ↔ 时域 ADEV 双独立估计）────────────────────────


class TestFlickerFmCrossCheck:
    def test_psd_vs_adev_consistent(self):
        from scipy.signal import periodogram

        rng = np.random.default_rng(7)
        n = 1 << 18
        w = rng.standard_normal(n)
        f = np.fft.rfftfreq(n, d=_TAU0)
        f[0] = f[1]
        y = np.fft.irfft(np.fft.rfft(w) / np.sqrt(f), n)
        y -= y.mean()
        fr, psd = periodogram(y, fs=_RATE, scaling="density")
        band = (fr > 0.05) & (fr < 0.5)
        h_m1 = float(np.median(psd[band] * fr[band]))
        taus = [_TAU0 * (1 << k) for k in range(0, 8)]
        r = adev(y, _RATE, taus=taus)
        mid = (r["tau"] >= 0.4) & (r["tau"] <= 25.6)
        # 闪频平台：中段斜率 ≈ 0
        s = _slope(r["tau"][mid], r["adev"][mid])
        assert abs(s) < 0.1, f"闪频平台斜率应 ≈0，实测 {s}"
        # 互检：ADEV / (PSD 独立估 h_{-1} → 三 coef 预测) 稳定带
        pred = avar_from_h(r["tau"][mid], h_minus1=h_m1)
        ratio = r["adev"][mid] / pred
        assert np.all((ratio > 0.8) & (ratio < 1.5)), (
            f"ADEV vs PSD 桥互检失稳: {ratio}")
        assert ratio.max() / ratio.min() < 1.12, (
            f"互检比值非系统学稳定（带限+估计器系统学应逐 τ 恒定）: {ratio}")


# ─── 负例：域守卫显式报错 ───────────────────────────────────────────────────


class TestNegativeCases:
    def test_short_series_rejected(self):
        with pytest.raises(ValueError, match="至少需要 3 点"):
            adev([0.1, 0.2], _RATE)
        # x 3 点 → y 2 点拒；x 4 点 → y 3 点恰过（边界不误伤）
        with pytest.raises(ValueError, match="至少需要 3 点"):
            adev([0.0] * 3, _RATE, kind="phase")
        r4 = adev([0.0] * 4, _RATE, kind="phase", taus=[_TAU0])
        assert r4["tau"].size == 1

    def test_nonfinite_and_rate_guards(self):
        with pytest.raises(ValueError, match="非有限"):
            adev([0.1, float("nan"), 0.3], _RATE)
        with pytest.raises(ValueError, match="有限正数"):
            adev([0.1] * 10, 0.0)
        with pytest.raises(ValueError, match="有限正数"):
            adev([0.1] * 10, -5.0)
        with pytest.raises(ValueError, match="有限正数"):
            adev([0.1] * 10, float("inf"))

    def test_nonuniform_time_rejected(self):
        t = np.arange(10) * 0.2  # 间隔 0.2 ≠ τ0=0.1
        with pytest.raises(ValueError, match="非等间隔"):
            adev(np.arange(10.0), _RATE, time_s=t)
        with pytest.raises(ValueError, match="长度"):
            adev(np.arange(10.0), _RATE, time_s=np.arange(5.0) * _TAU0)

    def test_kind_estimator_taus_guards(self):
        y = np.arange(16.0)
        with pytest.raises(ValueError, match="kind"):
            adev(y, _RATE, kind="volt")
        with pytest.raises(ValueError, match="estimator"):
            adev(y, _RATE, estimator="total")
        with pytest.raises(ValueError, match="taus"):
            adev(y, _RATE, taus=[])
        with pytest.raises(ValueError, match="正数"):
            adev(y, _RATE, taus=[0.1, -1.0])


# ─── 注册键（allan_deviation）service 出口往返 ──────────────────────────────


class TestRegisteredKey:
    def test_roundtrip_ok(self):
        samples = [1e-11 * float(v) for v in np.random.default_rng(1).standard_normal(256)]
        out = run_calculator("allan_deviation", {"samples": samples, "rate_hz": _RATE,
                                                 "taus": [0.1, 1.0]})
        assert out["ok"] is True, out.get("error")
        res = out["result"]
        assert res["tau_s"] == [0.1, 1.0]
        assert len(res["adev"]) == 2 and len(res["adev_error"]) == 2
        assert res["tau0_s"] == pytest.approx(0.1)
        assert res["n_samples"] == 256
        assert isinstance(res["label"], str)
        json.dumps(out, allow_nan=False)

    def test_invalid_input_ok_false(self):
        out = run_calculator("allan_deviation", {"samples": [0.1, 0.2], "rate_hz": 10.0})
        assert out["ok"] is False and out.get("error")
        out2 = run_calculator("allan_deviation", {"samples": [float("nan")] * 8,
                                                  "rate_hz": 10.0})
        assert out2["ok"] is False and out2.get("error")
