"""F-H 件 3 振动/冲击 SRS 内核单测（研究扩充 round4 F-H 件 3）。

裁判口径（#118，独立来源/独立推导，不自证）：
- Miles：解析钉值 sqrt(5π)=3.9633272976060（venv 实测复核）+ PSD 频响
  数值积分（洛伦兹半功率积分路径，rel ≤5% 预声明）双路径互证；
- 半正弦 SRS：闭式路径的锚点由**手工独立推导**给出——α=0.5 共振分支
  maximax=π/2（|sin u−u·cos u|/2 在 u∈[0,π] 单调升，max@u=π）、α=1 时
  maximax=√3（驻点 t=2π/(ω+ω_n) 处 |sin−ρ·sin|/(1−ρ²)=1.299/0.75）；
  数值 vs 闭式双路径 rel ≤1e-6；渐近式（R=4α）仅在预声明深覆盖段
  （α ≤ 5e-4，渐近领先修正 ~−0.93·α² ≤ 2.3e-7）用 rel ≤1e-6 判；
  有阻尼数值路径由测试内 FOH（斜坡不变）状态空间递推（scipy expm，
  独立算法）作裁判 rel ≤1e-6——ZOH（零阶保持）有半步迟差 O(ω·dt)
  （实测 7e-4@res 5e-4）达不到 1e-6，故裁判必须用 FOH；
- 边带换算：小指数 FM 推导的往返恒等式 10^(L/20)·√2·f_v = f0·Γ·a
  （rel 1e-12）+ 逐参数 dB 线性（用例全部收在 Δφ ≤ 0.5 有效域内）；
- g-灵敏度表只验 schema（UNVERIFIED 如实登记），**不验物理数值**——
  数值锚为单源/工程量级（模块 docstring 诚实边界 1）。

分辨率预算（数值路径，预声明）：res_rad=5e-4 → 峰值欠采样 ~(res)²/8
≈3e-8、梯形求积 ~(res)²/12 ≈2e-8；深渐近段（α ≤ 5e-4，两尺度网格）
用 res_rad=1e-3 + ring_periods=0.75（残余峰必在脉冲后前半周期内，
误差预算：渐近 2.3e-7 + 求积/欠采样 ~2e-7 → ≤1e-6）。
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

from rfauto.core import vibration_srs as vsrs

G0 = 9.80665


# ─── 1. Miles：解析钉值 + 恒等式 ─────────────────────────────────────────────


def test_miles_formula_analytic_pin():
    # 手算：sqrt((π/2)·100·10·0.01) = sqrt(5π) = 3.9633272976060（venv 复核）
    g = vsrs.miles_rms_g(100.0, 10.0, 0.01)
    assert g == pytest.approx(math.sqrt(5.0 * math.pi), rel=1e-12)
    assert g == pytest.approx(3.9633272976060, rel=1e-11)
    # W=0 → 0.0 合法（数值 0 合法面，#364④）
    assert vsrs.miles_rms_g(100.0, 10.0, 0.0) == 0.0


def test_miles_vs_psd_integration_within_5pct():
    # 数值路径：G² = ∫|H|²·W df（梯形，频带 ±50 倍频程覆盖洛伦兹尾）
    fn, q, w_level = 100.0, 10.0, 0.01
    f = np.arange(fn / 50.0, 50.0 * fn, fn / 2000.0)
    psd = np.full(f.shape, w_level)
    g_num = vsrs.broadband_grms_from_psd(f, psd, fn, q)
    g_miles = vsrs.miles_rms_g(fn, q, w_level)
    assert abs(g_num / g_miles - 1.0) <= 0.05  # 预声明门（实测 ~0.2%）
    # 第二组：Q=5 同门
    g_num5 = vsrs.broadband_grms_from_psd(f, psd, fn, 5.0)
    g_miles5 = vsrs.miles_rms_g(fn, 5.0, w_level)
    assert abs(g_num5 / g_miles5 - 1.0) <= 0.05


def test_miles_scaling_and_result_identities():
    r = vsrs.miles_response(100.0, 10.0, 0.01)
    # 幂次标度：W×4→G×2、Q×4→G×2、f_n×4→G×2（解析恒等，rel 1e-15）
    assert vsrs.miles_rms_g(100.0, 10.0, 0.04) == pytest.approx(2.0 * r.g_rms, rel=1e-15)
    assert vsrs.miles_rms_g(100.0, 40.0, 0.01) == pytest.approx(2.0 * r.g_rms, rel=1e-15)
    assert vsrs.miles_rms_g(400.0, 10.0, 0.01) == pytest.approx(2.0 * r.g_rms, rel=1e-15)
    # 3σ 恒等 + 位移恒等 x_rms = G_rms·g0/ω_n²（Miles 内禀推论）
    assert r.g_3sigma == 3.0 * r.g_rms
    w_n = 2.0 * math.pi * 100.0
    assert r.disp_rms_m == pytest.approx(r.g_rms * G0 / (w_n * w_n), rel=1e-15)


def test_transmissibility_peak_and_dc():
    f = np.array([0.0, 50.0, 100.0, 200.0, 1000.0])
    h = vsrs.sdof_transmissibility_sq(f, 100.0, 10.0)
    assert h[2] == pytest.approx(100.0, rel=1e-9)  # |H(f_n)|² = Q²
    assert h[0] == pytest.approx(1.0, rel=1e-12)  # 静态增益 1


def test_miles_input_validation():
    with pytest.raises(ValueError, match="bool"):
        vsrs.miles_rms_g(True, 10.0, 0.01)
    with pytest.raises(ValueError, match="f_n_hz"):
        vsrs.miles_rms_g(-1.0, 10.0, 0.01)
    with pytest.raises(ValueError, match="有限"):
        vsrs.miles_rms_g(float("nan"), 10.0, 0.01)
    with pytest.raises(ValueError, match="q"):
        vsrs.miles_rms_g(100.0, 0.0, 0.01)
    with pytest.raises(ValueError, match="psd_g2_hz"):
        vsrs.miles_rms_g(100.0, 10.0, -0.01)


# ─── 2. 半正弦 SRS：闭式锚 + 双路径 ──────────────────────────────────────────


def test_srs_exact_resonance_alpha_half_is_pi_over_2():
    # 手工推导锚：α=0.5（ω=ω_n）共振分支 maximax = π/2
    r = vsrs.srs_half_sine_exact_undamped(100.0, 20.0, 0.5 / 100.0)
    assert r.amplification == pytest.approx(math.pi / 2.0, rel=1e-12)
    assert r.accel_peak_g == pytest.approx(20.0 * math.pi / 2.0, rel=1e-12)
    # 数值路径同锚（独立算法，网格误差 ~3e-8）
    n = vsrs.srs_half_sine_numerical(100.0, 20.0, 0.5 / 100.0)
    assert n.amplification == pytest.approx(math.pi / 2.0, rel=5e-7)


def test_srs_exact_alpha_one_is_sqrt3():
    # 手工推导锚：α=1（ρ=0.5）驻点 t=2π/(ω+ω_n) 处 amp=(sin+0.5·0.866·2)/0.75=√3
    # 残余幅值 4/3 < √3 → maximax=√3
    r = vsrs.srs_half_sine_exact_undamped(200.0, 5.0, 1.0 / 200.0)
    assert r.amplification == pytest.approx(math.sqrt(3.0), rel=1e-12)


def test_srs_numerical_vs_exact_grid_rel_1e6():
    # 双路径主判据（预声明）：全 α 网格数值 vs 闭式 rel ≤1e-6
    fn = 100.0
    for alpha in (0.05, 0.2, 1.0, 2.0, 5.0, 10.0):
        exact = vsrs.srs_half_sine_exact_undamped(fn, 1.0, alpha / fn)
        num = vsrs.srs_half_sine_numerical(fn, 1.0, alpha / fn)
        rel = abs(num.amplification / exact.amplification - 1.0)
        assert rel <= 1e-6, f"alpha={alpha}: num={num.amplification} exact={exact.amplification} rel={rel}"


def test_srs_asymptote_deep_coverage_rel_1e6():
    # 渐近覆盖段（预声明：α ≤ 5e-4，渐近领先修正 ~−0.93·α² ≤ 2.3e-7）：
    # 数值 vs 渐近 R=4α rel ≤1e-6。两尺度网格：res_rad=1e-3 +
    # ring_periods=0.75 控制规模（误差预算见文件头）。
    fn = 1000.0
    for alpha in (5e-4, 2e-4):
        t_s = alpha / fn
        asy = vsrs.srs_half_sine_asymptotic(1.0, t_s, fn)
        assert asy["regime"] == vsrs.REGIME_IMPULSE
        num = vsrs.srs_half_sine_numerical(
            fn, 1.0, t_s, res_rad=1e-3, ring_periods=0.75
        )
        rel = abs(num.amplification / float(asy["amplification"]) - 1.0)
        assert rel <= 1e-6, f"alpha={alpha}: num={num.amplification} asy={asy['amplification']} rel={rel}"


def test_srs_asymptote_regime_tags_and_transition_honesty():
    # 冲量段：amp=4α 精确式（α=f_n·T=1e-5）
    lo = vsrs.srs_half_sine_asymptotic(1.0, 1e-6, 10.0)
    assert lo["regime"] == vsrs.REGIME_IMPULSE
    assert lo["amplification"] == pytest.approx(4.0 * 1e-5, rel=1e-12)
    # 准静态段：amp=1.0 + 带宽注记
    hi = vsrs.srs_half_sine_asymptotic(1.0, 1.0, 50.0)  # α=50
    assert hi["regime"] == vsrs.REGIME_QUASI_STATIC
    assert hi["amplification"] == 1.0
    # 过渡段：如实 None（不凑数）
    mid = vsrs.srs_half_sine_asymptotic(1.0, 1e-3, 1000.0)  # α=1
    assert mid["regime"] == vsrs.REGIME_TRANSITION
    assert mid["amplification"] is None
    assert mid["accel_peak_g"] is None


def test_srs_quasistatic_band():
    # α=20/50 无阻尼数值：R∈(1, 1+1/(2α)+裕度]（预声明带宽）
    for alpha in (20.0, 50.0):
        num = vsrs.srs_half_sine_numerical(100.0, 1.0, alpha / 100.0)
        assert 1.0 < num.amplification <= 1.0 + 0.5 / alpha + 2e-3
        exact = vsrs.srs_half_sine_exact_undamped(100.0, 1.0, alpha / 100.0)
        assert num.amplification == pytest.approx(exact.amplification, rel=1e-6)


def test_srs_damped_state_space_referee_rel_1e6():
    # 有阻尼数值路径裁判：测试内 FOH（斜坡不变）状态空间递推——
    # 独立算法（矩阵指数传播 vs Duhamel 卷积）；ZOH 半步迟差 O(ω·dt)
    # 实测 7e-4 达不到 1e-6，必须 FOH（误差 O(dt²)）。
    from scipy.linalg import expm

    fn, q, a_g, alpha = 100.0, 10.0, 15.0, 1.0
    t_s = alpha / fn
    ref = 5e-4
    got = vsrs.srs_half_sine_numerical(fn, a_g, t_s, q=q, res_rad=ref)
    w_n = 2.0 * math.pi * fn
    zeta = 1.0 / (2.0 * q)
    dt = ref / w_n
    a_mat = np.array([[0.0, 1.0], [-w_n * w_n, -2.0 * zeta * w_n]])
    b_vec = np.array([[0.0], [1.0]])
    # FOH（斜坡不变）精确步进：x+ = Ad x + S·u_k + R·c（c=段内斜率），
    # S = A⁻¹(Ad−I)B（单位阶跃步进）、R = A⁻¹(S−dt·B)（单位斜坡步进）
    aug = expm(np.block([[a_mat * dt, b_vec * dt], [np.zeros((1, 3))]]))
    ad = aug[:2, :2]
    a_inv = np.linalg.inv(a_mat)
    s_step = a_inv @ (ad - np.eye(2)) @ b_vec
    r_ramp = a_inv @ (s_step - dt * b_vec)
    n_total = math.ceil((t_s + 2.0 * q / fn) / dt) + 1
    t = np.arange(n_total) * dt
    u = np.where(t <= t_s, a_g * G0 * np.sin(math.pi * np.minimum(t, t_s) / t_s), 0.0)
    state = np.zeros((2, 1))
    peak = 0.0
    for k in range(n_total):
        slope = (u[k + 1] - u[k]) / dt if k + 1 < n_total else 0.0
        state = ad @ state + s_step * float(u[k]) + r_ramp * float(slope)
        peak = max(peak, abs(float(state[0, 0])))
    amp_ref = w_n * w_n * peak / G0 / a_g
    assert got.amplification == pytest.approx(amp_ref, rel=1e-6)


def test_srs_damped_reduces_peak_and_validation():
    # 阻尼降峰（方向性）+ q 下限守卫
    undamped = vsrs.srs_half_sine_numerical(100.0, 1.0, 0.01)
    damped = vsrs.srs_half_sine_numerical(100.0, 1.0, 0.01, q=10.0)
    assert damped.amplification < undamped.amplification - 0.02
    assert damped.accel_peak_g > 0.0
    with pytest.raises(ValueError, match="q"):
        vsrs.srs_half_sine_numerical(100.0, 1.0, 0.01, q=0.4)


def test_srs_input_validation_and_grid_guard():
    with pytest.raises(ValueError, match="a_g"):
        vsrs.srs_half_sine_exact_undamped(100.0, 0.0, 1e-3)
    with pytest.raises(ValueError, match="bool"):
        vsrs.srs_half_sine_numerical(100.0, 1.0, True)
    with pytest.raises(ValueError, match="有限"):
        vsrs.srs_half_sine_exact_undamped(float("inf"), 1.0, 1e-3)
    with pytest.raises(ValueError, match="res_rad"):
        vsrs.srs_half_sine_numerical(100.0, 1.0, 1e-3, res_rad=0.0)
    with pytest.raises(ValueError, match="上限"):
        vsrs.srs_half_sine_numerical(100.0, 1.0, 1e-3, res_rad=1e-12)
    with pytest.raises(ValueError, match="ring_periods"):
        vsrs.srs_half_sine_numerical(100.0, 1.0, 1e-3, ring_periods=-1.0)


def test_srs_table_rows_schema():
    # f_n=[40,200,800] Hz × T=1e-3 s → α=0.04（冲量段）/0.2/0.8（过渡段）
    rows = vsrs.srs_half_sine_table(10.0, 1e-3, [40.0, 200.0, 800.0], q=None)
    assert len(rows) == 3
    assert rows[0]["alpha"] == pytest.approx(0.04, rel=1e-12)
    assert rows[0]["regime_asymptotic"] == vsrs.REGIME_IMPULSE
    assert rows[0]["amplification_asymptotic"] == pytest.approx(4.0 * 0.04, rel=1e-12)
    # 冲量段：数值 vs 渐近 4α（α=0.04 领先修正 −0.93·α²≈−1.5e-3，门 5e-3）
    assert rows[0]["amplification_numeric"] == pytest.approx(0.16, rel=5e-3)
    for row in rows[1:]:
        assert row["regime_asymptotic"] == vsrs.REGIME_TRANSITION
        assert row["amplification_asymptotic"] is None  # 过渡段如实不产数字
    # 过渡段物理形态（实测钉）：α=0.2 处于半正弦 SRS 谷（响应<脉冲幅值），
    # α=0.8 已过 1.0 接近经典峰肩（~1.77）
    assert rows[1]["amplification_numeric"] == pytest.approx(0.770492, rel=1e-5)
    assert rows[1]["amplification_numeric"] < 1.0
    assert rows[2]["amplification_numeric"] == pytest.approx(1.768327, rel=1e-5)
    assert rows[2]["amplification_numeric"] > 1.0
    for row in rows:
        assert row["accel_peak_g_numeric"] == pytest.approx(
            10.0 * float(row["amplification_numeric"]), rel=1e-12
        )


# ─── 3. g-灵敏度 + 边带换算 ──────────────────────────────────────────────────


def test_freq_shift_linear_identity():
    df = vsrs.freq_shift_hz(10e9, 1e-9, 5.0)
    assert df == pytest.approx(10e9 * 1e-9 * 5.0, rel=1e-15)  # 50 Hz 手算
    assert vsrs.freq_shift_hz(10e9, 1e-9, 10.0) == 2.0 * df
    assert vsrs.freq_shift_hz(10e9, 1e-9, 0.0) == 0.0
    with pytest.raises(ValueError, match="bool"):
        vsrs.freq_shift_hz(True, 1e-9, 5.0)


def test_sideband_roundtrip_identity():
    # 往返恒等式（小指数 FM 推导的自洽钉）：10^(L/20)·√2·f_v = Δf = f0·Γ·a
    # 用例全部收在小指数有效域 Δφ ≤ 0.5 内（末例恰在边界）
    cases = [(10e9, 1e-9, 5.0, 100.0), (1e9, 5e-9, 3.0, 55.0), (20e9, 1e-8, 1.0, 400.0)]
    for f0, gamma, a, fv in cases:
        l_db = vsrs.vibration_sideband_dbc(f0, gamma, a, fv)
        df = vsrs.freq_shift_hz(f0, gamma, a)
        assert 10.0 ** (l_db / 20.0) * math.sqrt(2.0) * fv == pytest.approx(df, rel=1e-12)


def test_sideband_db_linearity():
    # 基准 Δφ=0.05（有效域深区），Γ×10 后恰到 0.5 边界仍可算
    base = vsrs.vibration_sideband_dbc(10e9, 1e-9, 0.5, 100.0)
    assert base == pytest.approx(20.0 * math.log10(0.05 / math.sqrt(2.0)), rel=1e-12)
    # Γ×10 → +20 dB；a×2 → +6.0206 dB；f_v×2 → −6.0206 dB
    assert vsrs.vibration_sideband_dbc(10e9, 1e-8, 0.5, 100.0) == pytest.approx(
        base + 20.0, rel=1e-12
    )
    assert vsrs.vibration_sideband_dbc(10e9, 1e-9, 1.0, 100.0) == pytest.approx(
        base + 20.0 * math.log10(2.0), rel=1e-12
    )
    assert vsrs.vibration_sideband_dbc(10e9, 1e-9, 0.5, 200.0) == pytest.approx(
        base - 20.0 * math.log10(2.0), rel=1e-12
    )


def test_sideband_small_index_guard_and_validation():
    # 边界内（Δφ=0.5）可算；越界（Δφ>0.5）显式拒判不产伪数字
    phi = 0.5
    a_boundary = phi * 100.0 / (10e9 * 1e-9)  # Δφ = f0·Γ·a/f_v = 0.5
    assert vsrs.vibration_sideband_dbc(10e9, 1e-9, a_boundary, 100.0) == pytest.approx(
        20.0 * math.log10(0.5 / math.sqrt(2.0)), rel=1e-12
    )
    with pytest.raises(ValueError, match="小指数"):
        vsrs.vibration_sideband_dbc(10e9, 1e-9, a_boundary * 1.001, 100.0)
    with pytest.raises(ValueError, match="a_g"):
        vsrs.vibration_sideband_dbc(10e9, 1e-9, 0.0, 100.0)
    with pytest.raises(ValueError, match="f_v_hz"):
        vsrs.vibration_sideband_dbc(10e9, 1e-9, 5.0, -1.0)


def test_g_sensitivity_table_registry():
    required = {"quartz_oscillator", "tcxo", "dro", "sapphire"}
    assert required.issubset(vsrs.G_SENSITIVITY_TABLE)
    for family, entry in vsrs.G_SENSITIVITY_TABLE.items():
        assert entry.family == family
        assert entry.unverified is True  # 全表 UNVERIFIED 如实登记
        assert entry.band_low_per_g < entry.gamma_per_g < entry.band_high_per_g
        assert isinstance(entry.source, str) and len(entry.source) > 10
    entry = vsrs.g_sensitivity_lookup("sapphire")
    assert entry.gamma_per_g == pytest.approx(5e-9, rel=1e-12)  # round4 [14] 登记值
    with pytest.raises(ValueError, match="可用族"):
        vsrs.g_sensitivity_lookup("nonexistent")


def test_to_dict_json_serializable():
    miles = vsrs.miles_response(100.0, 10.0, 0.01).to_dict()
    exact = vsrs.srs_half_sine_exact_undamped(100.0, 1.0, 0.01).to_dict()
    num = vsrs.srs_half_sine_numerical(100.0, 1.0, 0.01, q=10.0).to_dict()
    asy = vsrs.srs_half_sine_asymptotic(1.0, 1e-3, 100.0)
    entry = vsrs.g_sensitivity_lookup("dro").to_dict()
    for payload in (miles, exact, num, asy, entry):
        json.dumps(payload, ensure_ascii=False, allow_nan=False)  # 非有限值即炸
    assert set(miles) == {"f_n_hz", "q", "psd_g2_hz", "g_rms", "g_3sigma", "disp_rms_m"}
    assert set(exact) == set(num)
    assert num["q"] == 10.0 and exact["q"] is None
    assert asy["amplification"] is None  # 过渡段 None → JSON null
