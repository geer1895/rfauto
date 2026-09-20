"""§10.4 D6 SI 垂直通道（core/si_channel.py）定向测试。

覆盖
----
- PRBS：最大长度序列的周期 2^n−1、0/1 平衡（2^(n−1) 个 1、2^(n−1)−1 个 0）、
  固定初值确定性、不同初值=同一序列的循环移位、非法阶数/零初值报错；
- 理想无色散通道：冲激响应=时延 δ（argmax=m、Σh=1）、群延迟恒为 τ、
  插损 0 dB、眼图完全张开（眼高=满幅、眼宽=1 UI、抖动=0）；
- 一阶 RC 通道：阶跃响应 vs 闭式 1−exp(−t/RC)、群延迟 vs 闭式 RC/(1+(ωRC)^2)、
  插损 vs 闭式 10log10(1+(ωRC)^2)、−3 dB 点 = 3.0103 dB；
- 眼图指标：RC 眼高随带宽单调上升；与闭式最坏情形眼高 1−2exp(−UI/RC) 对照；
  与**独立**时域模型（ZOH 精确一阶递推 y[n]=y[n−1]+(1−e^(−dt/RC))(u[n]−y[n−1])）
  互证；
- 预加重：有损通道上 1-tap FFE 提升眼高（且过加重会变差 → 非恒真）；
  理想通道上预加重不改变最坏情形眼高（对照"非恒真"）；
- FIR/去加重 dB 换算、NRZ 波形、时间轴；
- Touchstone .s2p 写→skrf 读回、f>0 网格 resample 到含直流网格；
- 非法输入显式报错；两次运行逐位一致（确定性）。

实测偏差（2026-09-12 本机，固定网格 baud=1 Gbps、sps=32、dt=31.25 ps、
4096 频点 0–16 GHz；命令 .venv\\Scripts\\python.exe -m pytest tests/unit/test_si_channel.py -q）
----------------------------------------------------------------------------
- RC 阶跃响应（fmax=200·f3、4096 点）：max|s−闭式| = 9.115e-3（在 t=dt 的带限
  吉布斯处），t=RC 处 3.794e-3；
- RC 群延迟：gd[0] 相对误差 7.94e-4（前向差分口径），全带 max/RC = 7.94e-4；
- RC 插损：与闭式 max 偏差 1.42e-14 dB；−3 dB 点插值 = 3.01030 dB；
- RC 眼高（眼高/满幅）实测 vs 闭式 vs ZOH 递推：
      f3=0.15 GHz  0.21276 / 0.22068 / 0.22242
      f3=0.25 GHz  0.57704 / 0.58424 / 0.58426
      f3=0.50 GHz  0.91533 / 0.91357 / 0.91357
      f3=1.00 GHz  1.00762 / 0.99627 / 0.99627
      f3=2.00 GHz  1.02209 / 0.99999 / 0.99999
      f3=4.00 GHz  1.04052 / 1.00000 / 1.00000
  ——高带宽端（f3→fmax/4）眼高被**带限吉布斯振铃**抬到满幅以上 +4%（h 在 t=0
  跳变、谱在 fmax 处未衰尽），故对照容差取 0.03，并在报告里如实记录；
- 预加重（f3=0.15 GHz）：α=0 → 0.2128，α=0.5 → 0.5387，α=1.0 → 0.5457，
  α=1.5 → 0.4618，α=2.0 → 0.3780（存在最优 α，过加重变差）。

诚实边界
--------
频率 IFFT 得到的冲激响应是带限+周期化版本：一阶 RC 的 h 在 t=0 有跳变，
带限重构在跳变处取半值并带吉布斯振铃，故"逐点等于闭式"不成立，测试只主张
上表的实测容差。眼图指标是本模块自定义的确定性口径（见 EyeMetrics docstring），
不对 BER/浴盆曲线标准负责。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import si_channel as si

#: 固定采样网格：dt = UI/sps → fmax = baud·sps/2 = 16 GHz、n_fft = 8190
BAUD = 1.0e9
SPS = 32
N_FFT = 8190
DT = 1.0 / (BAUD * SPS)
FREQS = np.fft.rfftfreq(N_FFT, d=DT)
BITS7 = si.prbs_bits(127, order=7)


def rc_freqs(f3_hz: float, n: int = 4096, factor: float = 200.0) -> np.ndarray:
    """step/指标对照用网格（fmax = factor·f3，含直流）。"""
    return np.linspace(0.0, factor * f3_hz, n)


def rc_channel(f3_hz: float) -> tuple[float, np.ndarray]:
    rc = 1.0 / (2.0 * np.pi * f3_hz)
    return rc, si.rc_lowpass_s21(FREQS, 1.0, rc)


def exact_zoh_rc(symbols: np.ndarray, sps: int, rc: float, dt: float) -> np.ndarray:
    """ZOH 精确一阶 RC 递推（独立于频域 IFFT 的时域模型）。"""
    a = 1.0 - np.exp(-dt / rc)
    u = np.repeat(symbols, sps)
    y = np.empty_like(u)
    prev = 0.0
    for n in range(u.size):
        prev += a * (u[n] - prev)
        y[n] = prev
    return y


def test_prbs_full_period_and_balance() -> None:
    for order in (7, 9, 11):
        per = (1 << order) - 1
        seq = si.prbs_bits(per, order=order)
        rep = si.prbs_bits(2 * per, order=order)
        assert np.array_equal(rep[:per], rep[per:]), order
        assert int(seq.sum()) == (per + 1) // 2
        assert int(np.count_nonzero(seq == 0)) == (per - 1) // 2
        assert set(np.unique(seq).tolist()) == {0, 1}


def test_prbs_deterministic_and_seed_dependent() -> None:
    a = si.prbs_bits(64, order=7)
    b = si.prbs_bits(64, order=7)
    assert np.array_equal(a, b)
    c = si.prbs_bits(64, order=7, seed=1)
    assert not np.array_equal(a, c)
    assert set(np.unique(c).tolist()) == {0, 1}


def test_ideal_delay_channel_impulse_and_metrics() -> None:
    m = 100
    tau = m * DT
    s21 = si.ideal_delay_s21(FREQS, tau)
    h, dt = si.impulse_response(FREQS, s21)
    assert dt == pytest.approx(DT, rel=1e-12)
    assert int(np.argmax(np.abs(h))) == m
    assert float(h.sum()) == pytest.approx(1.0, abs=1e-12)
    assert np.allclose(si.group_delay_s(FREQS, s21), tau, rtol=1e-9)
    assert np.max(np.abs(si.insertion_loss_db(FREQS, s21))) < 1e-10
    mt = si.run_channel_eye(BITS7, SPS, FREQS, s21, symbol_rate_baud=BAUD).metrics
    assert mt.eye_height == pytest.approx(1.0, abs=1e-9)
    assert mt.eye_width_ui == pytest.approx(1.0, abs=1e-12)
    assert mt.jitter_pp_ui == pytest.approx(0.0, abs=1e-12)
    assert mt.jitter_rms_ui == pytest.approx(0.0, abs=1e-12)


def test_rc_step_response_matches_closed_form() -> None:
    f3 = 0.5e9
    rc = 1.0 / (2.0 * np.pi * f3)
    f = rc_freqs(f3)
    st, dt = si.step_response(f, si.rc_lowpass_s21(f, 1.0, rc))
    t = np.arange(st.size) * dt
    err = np.abs(st - (1.0 - np.exp(-t / rc)))
    assert err.max() < 0.02
    assert err[round(rc / dt)] < 0.01
    assert st[-1] == pytest.approx(1.0, abs=1e-6)


def test_rc_group_delay_matches_closed_form() -> None:
    f3 = 0.5e9
    rc = 1.0 / (2.0 * np.pi * f3)
    f = rc_freqs(f3)
    gd = si.group_delay_s(f, si.rc_lowpass_s21(f, 1.0, rc))
    exact = rc / (1.0 + (2.0 * np.pi * f * rc) ** 2)
    assert abs(gd[0] - rc) / rc < 1e-3
    assert np.max(np.abs(gd - exact)) / rc < 1e-3


def test_rc_insertion_loss_matches_closed_form() -> None:
    f3 = 0.5e9
    rc = 1.0 / (2.0 * np.pi * f3)
    f = rc_freqs(f3)
    s21 = si.rc_lowpass_s21(f, 1.0, rc)
    il = si.insertion_loss_db(f, s21)
    exact = 10.0 * np.log10(1.0 + (2.0 * np.pi * f * rc) ** 2)
    assert np.max(np.abs(il - exact)) < 1e-9
    assert si.insertion_loss_at_db(f, s21, f3) == pytest.approx(3.0103, abs=1e-3)


def test_nyquist_frequency_and_loss() -> None:
    assert si.nyquist_frequency_hz(BAUD) == pytest.approx(0.5e9)
    rc, s21 = rc_channel(0.5e9)
    fq = si.nyquist_frequency_hz(BAUD)
    exact = 10.0 * np.log10(1.0 + (2.0 * np.pi * fq * rc) ** 2)
    assert si.insertion_loss_at_db(FREQS, s21, fq) == pytest.approx(exact, abs=1e-2)


def test_rc_eye_height_monotone_with_bandwidth() -> None:
    heights = []
    widths = []
    for f3 in (0.15e9, 0.25e9, 0.5e9, 1.0e9, 2.0e9, 4.0e9):
        _, s21 = rc_channel(f3)
        mt = si.run_channel_eye(BITS7, SPS, FREQS, s21, symbol_rate_baud=BAUD).metrics
        heights.append(mt.eye_height)
        widths.append(mt.eye_width_ui)
    assert np.all(np.diff(heights) > 0.0)
    assert np.all(np.diff(widths) >= 0.0)
    # 4 GHz（奈奎斯特损耗 0.07 dB）时应逼近满幅（带限振铃 +4%，容差 6%）
    assert heights[-1] == pytest.approx(1.0, abs=0.06)


@pytest.mark.parametrize("f3_hz,tol", [(0.25e9, 0.02), (0.5e9, 0.01), (1.0e9, 0.02)])
def test_rc_eye_agrees_with_analytic_worst_case(f3_hz: float, tol: float) -> None:
    rc, s21 = rc_channel(f3_hz)
    mt = si.run_channel_eye(BITS7, SPS, FREQS, s21, symbol_rate_baud=BAUD).metrics
    ui = 1.0 / BAUD
    # 闭式最坏情形：最优采样相位取 UI 末端 → 1 − 2·exp(−UI/RC)
    expected = 1.0 - 2.0 * np.exp(-ui / rc)
    assert mt.eye_height == pytest.approx(expected, abs=tol)


@pytest.mark.parametrize("f3_hz", [0.25e9, 0.5e9, 1.0e9])
def test_rc_eye_matches_exact_zoh_recursion(f3_hz: float) -> None:
    rc, s21 = rc_channel(f3_hz)
    reps = 3
    syms = si.preemphasis_symbols(BITS7, 0.0)
    y = exact_zoh_rc(np.tile(syms, reps), SPS, rc, DT)
    y_mid = y[BITS7.size * SPS : 2 * BITS7.size * SPS]
    ref = si.eye_metrics(y_mid, BITS7, SPS)
    mt = si.run_channel_eye(BITS7, SPS, FREQS, s21, symbol_rate_baud=BAUD).metrics
    assert abs(mt.eye_height - ref.eye_height) < 0.03
    assert abs(mt.eye_width_ui - ref.eye_width_ui) <= 1.0 / SPS + 1e-12


def test_preemphasis_improves_lossy_channel_eye() -> None:
    _, s21 = rc_channel(0.15e9)

    def h(alpha: float) -> float:
        return si.run_channel_eye(
            BITS7, SPS, FREQS, s21, symbol_rate_baud=BAUD, alpha=alpha
        ).metrics.eye_height

    h0, h05, h10, h20 = h(0.0), h(0.5), h(1.0), h(2.0)
    assert h05 > h0 + 0.1
    assert h10 > h0 + 0.1
    assert h20 < h10  # 过加重变差：预加重改善不是恒真


def test_preemphasis_not_tautological_on_ideal_channel() -> None:
    s21 = si.ideal_delay_s21(FREQS, 100 * DT)
    m0 = si.run_channel_eye(BITS7, SPS, FREQS, s21, symbol_rate_baud=BAUD).metrics
    m1 = si.run_channel_eye(
        BITS7, SPS, FREQS, s21, symbol_rate_baud=BAUD, alpha=1.0
    ).metrics
    # 理想通道：最坏情形眼高不变（仍为满幅），平均眼高被抬高
    assert m1.eye_height <= m0.eye_height + 1e-9
    assert m1.eye_height_mean > m0.eye_height_mean + 0.5


def test_fir_taps_and_deemphasis_db() -> None:
    for alpha in (0.0, 0.5, 1.0):
        taps = si.preemphasis_taps(alpha)
        assert taps.sum() == pytest.approx(1.0)
        assert taps[0] == pytest.approx(1.0 + alpha)
    alpha = si.deemphasis_db_to_alpha(6.0206)
    assert alpha == pytest.approx(1.0, abs=1e-3)
    assert si.alpha_to_deemphasis_db(alpha) == pytest.approx(6.0206, abs=1e-3)
    out = si.apply_fir(np.ones(8), si.preemphasis_taps(1.0))
    assert out.size == 9
    assert out.sum() == pytest.approx(8.0)  # 抽头和=1（直流增益）


def test_preemphasis_symbols_boosts_transitions_only() -> None:
    bits = np.array([0, 1, 1, 1, 0, 1, 0, 1])
    y = si.preemphasis_symbols(bits, alpha=1.0)
    assert y[0] == pytest.approx(0.0)
    assert y[1] == pytest.approx(2.0)  # 0→1 抬到 (1+α)×
    assert y[2] == pytest.approx(1.0)  # 连续 1 回到 1×
    assert y[3] == pytest.approx(1.0)
    assert y[4] == pytest.approx(-1.0)  # 1→0 反向
    assert np.array_equal(si.preemphasis_symbols(bits, alpha=0.0), bits.astype(float))


def test_nrz_waveform_and_time_axis() -> None:
    bits = np.array([0, 1, 0, 1])
    w = si.nrz_waveform(bits, 4, levels=(-1.0, 1.0))
    assert w.size == 16
    assert np.allclose(w[:4], -1.0)
    assert np.allclose(w[4:8], 1.0)
    t = si.impulse_time_axis_s(np.zeros(5), 2e-12)
    assert np.allclose(t, np.arange(5) * 2e-12)


def test_touchstone_roundtrip(tmp_path: Path) -> None:
    _, s21 = rc_channel(0.5e9)
    path = si.save_touchstone_s2p(tmp_path / "ch.s2p", FREQS, s21)
    f2, s2, z0 = si.load_touchstone_s2p(path)
    assert z0 == pytest.approx(50.0)
    assert np.allclose(f2, FREQS, rtol=0.0, atol=1.0)
    assert np.allclose(s2, s21, rtol=0.0, atol=1e-9)
    loaded = si.run_channel_eye(BITS7, SPS, f2, s2, symbol_rate_baud=BAUD).metrics
    direct = si.run_channel_eye(BITS7, SPS, FREQS, s21, symbol_rate_baud=BAUD).metrics
    assert loaded.eye_height == pytest.approx(direct.eye_height, abs=1e-3)


def test_resample_to_dc_grid() -> None:
    rc, _ = rc_channel(0.5e9)
    fsrc = FREQS[20:]
    ssrc = si.rc_lowpass_s21(fsrc, 1.0, rc)
    fg, sg = si.resample_s21(fsrc, ssrc, n_points=FREQS.size)
    assert fg[0] == 0.0
    assert fg.size == FREQS.size
    assert fg[-1] == pytest.approx(fsrc[-1])
    band = fg >= fsrc[0]
    assert np.max(np.abs(sg[band] - si.rc_lowpass_s21(fg[band], 1.0, rc))) < 1e-12
    # 0 Hz 用首点常数保持（带内低频近似，非物理外推）
    assert sg[0] == pytest.approx(ssrc[0])


def test_invalid_inputs_raise(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        si.impulse_response(FREQS[1:], np.ones(FREQS.size - 1, dtype=complex))
    with pytest.raises(ValueError):
        si.impulse_response(np.array([0.0, 1.0, 3.0, 4.0]), np.ones(4, dtype=complex))
    with pytest.raises(ValueError):
        si.impulse_response(FREQS, np.ones(FREQS.size - 1, dtype=complex))
    with pytest.raises(ValueError):
        si.prbs_bits(16, order=8)
    with pytest.raises(ValueError):
        si.prbs_bits(16, order=7, seed=0)
    with pytest.raises(ValueError):
        si.prbs_bits(0)
    with pytest.raises(ValueError):
        si.eye_metrics(np.ones(40), np.ones(5, dtype=int), 8)
    with pytest.raises(ValueError):
        si.eye_metrics(np.ones(40), np.array([0, 1, 0, 1, 1]), 1)
    with pytest.raises(ValueError):
        si.eye_metrics(np.ones(10), BITS7, SPS)
    with pytest.raises(ValueError):
        si.preemphasis_taps(-0.5)
    with pytest.raises(ValueError):
        si.deemphasis_db_to_alpha(-1.0)
    with pytest.raises(ValueError):
        si.rc_lowpass_s21(FREQS, -1.0, 1e-12)
    with pytest.raises(ValueError):
        si.resample_s21(FREQS[20:], np.ones(FREQS.size - 20, dtype=complex), fmax_hz=1e12)
    with pytest.raises(FileNotFoundError):
        si.load_touchstone_s2p(tmp_path / "missing.s2p")


def test_deterministic_repeatability() -> None:
    _, s21 = rc_channel(0.3e9)
    a = si.run_channel_eye(BITS7, SPS, FREQS, s21, symbol_rate_baud=BAUD, alpha=0.8)
    b = si.run_channel_eye(BITS7, SPS, FREQS, s21, symbol_rate_baud=BAUD, alpha=0.8)
    assert np.array_equal(a.waveform, b.waveform)
    assert np.array_equal(a.impulse, b.impulse)
    assert a.metrics == b.metrics
    assert a.to_dict() == b.to_dict()
    assert a.time_axis_s().size == a.waveform.size
