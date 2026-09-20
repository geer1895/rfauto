"""SI 垂直通道（通道 S 参数 → 脉冲响应 → 眼图 → 预加重）确定性内核。

定位
----
信号完整性（Signal Integrity）里的"通道"是发射机到接收机之间的互连（PCB 走线、
过孔、连接器、线缆）。本模块把"通道 S 参数 → 时域脉冲/阶跃响应 → NRZ 眼图 →
通道损耗/群延迟指标 → 发送端预加重（FFE）前后对比"这条链做成纯确定性
numpy/skrf 内核：无随机（PRBS 由固定初值 LFSR 产生）、无网络、无全局状态、
不引入新依赖。

口径来源（SI 教科书/标准，非本仓自造）
--------------------------------------
- 一阶 RC 低通（"RC 通道"）：H(jω) = 1/(1 + jωRC)；−3 dB 带宽
  f_3dB = 1/(2πRC)；直流群延迟 τ_g(0) = RC；单位阶跃响应
  s(t) = 1 − exp(−t/RC)。见 Johnson & Graham《High-Speed Digital Design》
  关于 RC 集总模型与上升时间/带宽关系；Hall & Heck《Advanced Signal
  Integrity for High-Speed Digital Designs》第 1 章的频域/时域通道表征。
- 理想无色散通道：H(jω) = g·exp(−jωτ)，插损 0 dB、群延迟恒为 τ，
  冲激响应是时延 τ 的 δ（"无损耗传输线"极限）。
- 插损/群延迟：IL(f) = −20·log10|S21(f)|（正数=损耗）；τ_g = −dφ/dω。
  NRZ 的奈奎斯特频率 = 码元速率 / 2（Bogatin《Signal and Power Integrity –
  Simplified》"Nyquist frequency = bit rate / 2"）。
- 眼图：把一个 UI 内的通道输出叠加成余辉图；眼高 = 判决门限处的垂直张开，
  眼宽 = 门限处水平张开，抖动 = 过门限时刻相对理想时钟的偏差。本模块给出
  **确定性**定义（见 EyeMetrics docstring），不用 BER/浴盆曲线统计口径。
- 预加重/去加重：发送端 1-tap FFE  y[n] = (1+α)·x[n] − α·x[n−1]
  （直流增益恒为 1：连续位回到 1×，过渡位被抬到 (1+α)×）；去加重电平比
  换算 α = 10^(D/20) − 1。Hall & Heck 的 TX FFE / de-emphasis。
- PRBS：ITU-T O.150 / XAPP052 口径的最大长度序列（Fibonacci LFSR +
  本原多项式抽头表，周期 2^n − 1）；固定初值 → 完全确定性。

频域→时域的实现约定（重要）
----------------------------
impulse_response 用 Hermitian 对称 + irfft：N 点、间隔 Δf、覆盖
0…(N−1)Δf 的单边谱 H[k] 给出长度 n_fft = 2(N−1) 的**离散冲激响应** h[m]，
时间步 dt = 1/(n_fft·Δf)（时间记录长 1/Δf，Δf 越小尾巴越长）。h[m] 满足
"直接与离散信号卷积即得物理输出"（数值上等于连续冲激响应 × dt），因此
单位阶跃响应 = cumsum(h)（收敛到 H(0) = 直流增益）。本模块要求频率网格
从 0 Hz 起、等间隔，否则显式 ValueError；真实 .s2p 常从 f>0 起——先用
resample_s21 重采样到含直流网格（线性插值，显式近似）。

诚实边界
--------
- 频域 IFFT 得到的冲激响应是**带限 + 以 1/Δf 周期化**的版本：RC 通道
  解析指数尾巴会被折叠。测试里给实测偏差（见 test_si_channel.py 文档串），
  不声称"逐点等于闭式"。
- 眼图指标只对**本模块定义的确定性口径**负责，不对任何 BER/浴盆曲线标准
  负责；有限长 PRBS 的图案相关抖动（DDJ）随序列长度/图案变化。
- 预加重能否改善眼高取决于通道、码率、α 的组合，**不是恒真**；本模块只算，
  不预设方向（测试里同时给"改善"与"不改善"两个实例）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import skrf

__all__ = [
    "ChannelEyeResult",
    "EyeMetrics",
    "alpha_to_deemphasis_db",
    "apply_fir",
    "deemphasis_db_to_alpha",
    "eye_metrics",
    "group_delay_s",
    "ideal_delay_s21",
    "impulse_response",
    "impulse_time_axis_s",
    "insertion_loss_at_db",
    "insertion_loss_db",
    "load_touchstone_s2p",
    "nrz_waveform",
    "nyquist_frequency_hz",
    "prbs_bits",
    "preemphasis_symbols",
    "preemphasis_taps",
    "rc_lowpass_bandwidth_hz",
    "rc_lowpass_s21",
    "resample_s21",
    "run_channel_eye",
    "save_touchstone_s2p",
    "step_response",
]

_TWO_PI = 2.0 * np.pi

#: PRBS 本原多项式抽头（Fibonacci/LFSR，抽头位置从最低位 0 起算）。
#: 对应多项式：n=7: x^7+x^6+1；9: x^9+x^5+1；11: x^11+x^9+1；
#: 15: x^15+x^14+1；23: x^23+x^18+1；31: x^31+x^28+1（ITU-T O.150 / XAPP052）。
_PRBS_TAPS: dict[int, tuple[int, ...]] = {
    7: (6, 5),
    9: (8, 4),
    11: (10, 8),
    15: (14, 13),
    23: (22, 17),
    31: (30, 27),
}


# ---------------------------------------------------------------------------
# 入参守卫（#140：注解不等于调用方真的传了）
# ---------------------------------------------------------------------------

def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise TypeError(f"{label} 必须是实数，实际 {type(value).__name__}: {value!r}")
    out = float(value)
    if not np.isfinite(out):
        raise ValueError(f"{label} 必须是有限实数，实际 {out!r}")
    return out


def _positive_float(value: Any, label: str) -> float:
    out = _finite_float(value, label)
    if out <= 0.0:
        raise ValueError(f"{label} 必须 > 0，实际 {out!r}")
    return out


def _validate_levels(levels: Any) -> tuple[float, float]:
    if isinstance(levels, (str, bytes)) or len(levels) != 2:
        raise ValueError("levels 必须是 (低电平, 高电平) 二元组")
    lo = _finite_float(levels[0], "levels[0]")
    hi = _finite_float(levels[1], "levels[1]")
    if hi <= lo:
        raise ValueError(f"levels 必须满足 levels[1] > levels[0]，实际 {levels!r}")
    return lo, hi


def _validate_bits(bits: Any) -> np.ndarray:
    b = np.asarray(bits)
    if b.ndim != 1 or b.size < 4:
        raise ValueError("bits 必须是一维、长度 ≥4 的序列")
    if not np.all(np.isin(b, (0, 1))):
        raise ValueError("bits 只能含 0/1")
    if b.min() == b.max():
        raise ValueError("bits 必须同时含 0 与 1（眼图口径）")
    return b.astype(np.int8)


def _validate_sps(samples_per_symbol: Any) -> int:
    if isinstance(samples_per_symbol, bool) or not isinstance(samples_per_symbol, (int, np.integer)):
        raise TypeError(f"samples_per_symbol 必须是整数，实际 {type(samples_per_symbol).__name__}")
    sps = int(samples_per_symbol)
    if sps < 2:
        raise ValueError(f"samples_per_symbol 必须 ≥2（眼图相位分辨率），实际 {sps}")
    return sps


def _uniform_frequency_grid(freqs_hz: Any) -> tuple[np.ndarray, float]:
    """校验单边频率网格：一维、严格递增、等间隔、从直流起。"""
    f = np.asarray(freqs_hz, dtype=float)
    if f.ndim != 1 or f.size < 3:
        raise ValueError("freqs_hz 必须是长度 ≥3 的一维数组")
    if not np.all(np.isfinite(f)):
        raise ValueError("freqs_hz 含非有限值")
    d = np.diff(f)
    if not np.all(d > 0):
        raise ValueError("freqs_hz 必须严格单调递增")
    df = float(d[0])
    if not np.allclose(d, df, rtol=1e-6, atol=1e-9 * max(1.0, abs(df))):
        raise ValueError("freqs_hz 必须等间隔（IFFT 口径）")
    if abs(float(f[0])) > 1e-6 * df:
        raise ValueError(
            "freqs_hz 必须从 0 Hz（直流）起；真实 .s2p 先用 resample_s21(...) 重采样到含直流网格"
        )
    return f, df


def _check_s21(freqs: np.ndarray, s21: Any) -> np.ndarray:
    s = np.asarray(s21, dtype=complex)
    if s.shape != freqs.shape:
        raise ValueError(f"s21 形状 {s.shape} 与 freqs_hz 形状 {freqs.shape} 不一致")
    if not np.all(np.isfinite(s)):
        raise ValueError("s21 含非有限值")
    return s


# ---------------------------------------------------------------------------
# 解析通道模型（裁判来源）
# ---------------------------------------------------------------------------

def rc_lowpass_s21(freqs_hz: Any, r_ohm: Any, c_farad: Any) -> np.ndarray:
    """一阶 RC 低通：H(jω) = 1 / (1 + jωRC)（SI 教科书 RC 通道口径）。"""
    r = _positive_float(r_ohm, "r_ohm")
    c = _positive_float(c_farad, "c_farad")
    f = np.asarray(freqs_hz, dtype=float)
    if not np.all(np.isfinite(f)):
        raise ValueError("freqs_hz 含非有限值")
    return 1.0 / (1.0 + 1j * _TWO_PI * f * r * c)


def rc_lowpass_bandwidth_hz(r_ohm: Any, c_farad: Any) -> float:
    """RC 低通 −3 dB 带宽 f_3dB = 1/(2πRC)。"""
    r = _positive_float(r_ohm, "r_ohm")
    c = _positive_float(c_farad, "c_farad")
    return 1.0 / (_TWO_PI * r * c)


def ideal_delay_s21(freqs_hz: Any, delay_s: Any, gain: Any = 1.0) -> np.ndarray:
    """理想无色散通道：H(jω) = gain·exp(−jω·delay)（0 dB、群延迟恒为 delay）。"""
    tau = _finite_float(delay_s, "delay_s")
    if tau < 0.0:
        raise ValueError(f"delay_s 必须 ≥0，实际 {tau!r}")
    g = _finite_float(gain, "gain")
    f = np.asarray(freqs_hz, dtype=float)
    if not np.all(np.isfinite(f)):
        raise ValueError("freqs_hz 含非有限值")
    return g * np.exp(-1j * _TWO_PI * f * tau)


def nyquist_frequency_hz(symbol_rate_baud: Any) -> float:
    """NRZ 奈奎斯特频率 = 码元速率 / 2。"""
    r = _positive_float(symbol_rate_baud, "symbol_rate_baud")
    return 0.5 * r


# ---------------------------------------------------------------------------
# 频域指标
# ---------------------------------------------------------------------------

def insertion_loss_db(freqs_hz: Any, s21: Any) -> np.ndarray:
    """插损 IL(f) = −20·log10|S21|（dB，正数=损耗）。"""
    f = np.asarray(freqs_hz, dtype=float)
    if f.ndim != 1:
        raise ValueError("freqs_hz 必须是一维数组")
    s = _check_s21(f, s21)
    mag = np.maximum(np.abs(s), np.finfo(float).tiny)
    return -20.0 * np.log10(mag)


def insertion_loss_at_db(freqs_hz: Any, s21: Any, f_query_hz: Any) -> float:
    """查 f_query 处的插损（np.interp 线性插值，两端做常数外推）。"""
    f = np.asarray(freqs_hz, dtype=float)
    il = insertion_loss_db(f, s21)
    q = _finite_float(f_query_hz, "f_query_hz")
    return float(np.interp(q, f, il))


def group_delay_s(freqs_hz: Any, s21: Any) -> np.ndarray:
    """群延迟 τ_g(f) = −dφ/dω（相位先 unwrap，np.gradient 数值微分）。"""
    f = np.asarray(freqs_hz, dtype=float)
    if f.ndim != 1 or f.size < 3:
        raise ValueError("freqs_hz 必须是长度 ≥3 的一维数组")
    s = _check_s21(f, s21)
    phase = np.unwrap(np.angle(s))
    return -np.gradient(phase, _TWO_PI * f)


# ---------------------------------------------------------------------------
# 频域 → 时域
# ---------------------------------------------------------------------------

def impulse_response(freqs_hz: Any, s21: Any) -> tuple[np.ndarray, float]:
    """单边 S21 → 离散冲激响应 (h, dt)。

    约定：h[m] 已按 dt 加权——与任意离散激励直接 np.convolve 即得物理输出；
    单位阶跃响应 = np.cumsum(h)。dt = 1/(n_fft·Δf)，n_fft = 2(N−1)。
    """
    f, df = _uniform_frequency_grid(freqs_hz)
    s = _check_s21(f, s21)
    n_fft = 2 * (f.size - 1)
    h = np.fft.irfft(s, n=n_fft)
    dt = 1.0 / (n_fft * df)
    return h, dt


def impulse_time_axis_s(h: Any, dt: Any) -> np.ndarray:
    """冲激响应时间轴 t[m] = m·dt。"""
    arr = np.asarray(h)
    if arr.ndim != 1:
        raise ValueError("h 必须是一维数组")
    step = _positive_float(dt, "dt")
    return np.arange(arr.size, dtype=float) * step


def step_response(freqs_hz: Any, s21: Any) -> tuple[np.ndarray, float]:
    """单位阶跃响应 (s, dt)，s = cumsum(h)，末端收敛到 H(0)（直流增益）。"""
    h, dt = impulse_response(freqs_hz, s21)
    return np.cumsum(h), dt


def resample_s21(
    freqs_hz: Any,
    s21: Any,
    *,
    fmax_hz: Any = None,
    n_points: Any = None,
) -> tuple[np.ndarray, np.ndarray]:
    """把（可能不含直流的）S21 线性插值到含直流等间隔网格。

    这是**显式近似**：0 Hz 处用首点常数保持；fmax 默认取源网格末端，
    且不得超出源末端（不外推、不编造）。实部/虚部分别插值。
    """
    f = np.asarray(freqs_hz, dtype=float)
    if f.ndim != 1 or f.size < 3:
        raise ValueError("freqs_hz 必须是长度 ≥3 的一维数组")
    if not np.all(np.isfinite(f)):
        raise ValueError("freqs_hz 含非有限值")
    if not np.all(np.diff(f) > 0):
        raise ValueError("freqs_hz 必须严格单调递增")
    s = _check_s21(f, s21)
    fmax = float(f[-1]) if fmax_hz is None else _positive_float(fmax_hz, "fmax_hz")
    if fmax > f[-1] * (1.0 + 1e-9):
        raise ValueError(f"fmax_hz={fmax} 超出源网格末端 {f[-1]}，不做事后外推")
    npts = f.size if n_points is None else int(n_points)
    if npts < 3:
        raise ValueError(f"n_points 必须 ≥3，实际 {npts}")
    grid = np.linspace(0.0, fmax, npts)
    real = np.interp(grid, f, s.real)
    imag = np.interp(grid, f, s.imag)
    return grid, real + 1j * imag


# ---------------------------------------------------------------------------
# PRBS / NRZ / 预加重
# ---------------------------------------------------------------------------

def prbs_bits(n_bits: Any, order: Any = 7, seed: Any = None) -> np.ndarray:
    """最大长度伪随机比特序列（LFSR 口径，固定初值 → 确定性）。

    参数：order ∈ {7, 9, 11, 15, 23, 31}（本原多项式抽头表）；seed 为初值
    （缺省=全 1），必须非零。输出 0/1 的 int8 序列，周期 2^order − 1。
    """
    if isinstance(n_bits, bool) or not isinstance(n_bits, (int, np.integer)):
        raise TypeError(f"n_bits 必须是整数，实际 {type(n_bits).__name__}")
    n = int(n_bits)
    if n <= 0:
        raise ValueError(f"n_bits 必须 > 0，实际 {n}")
    if order not in _PRBS_TAPS:
        raise ValueError(f"order 必须 ∈ {sorted(_PRBS_TAPS)}，实际 {order!r}")
    taps = _PRBS_TAPS[order]
    mask = (1 << order) - 1
    if seed is None:
        state = mask
    else:
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise TypeError(f"seed 必须是整数或 None，实际 {type(seed).__name__}")
        state = int(seed) & mask
    if state == 0:
        raise ValueError("seed 不能为 0（全零状态是 LFSR 的死锁态）")
    out = np.empty(n, dtype=np.int8)
    for i in range(n):
        out[i] = (state >> (order - 1)) & 1
        fb = 0
        for t in taps:
            fb ^= (state >> t) & 1
        state = ((state << 1) | fb) & mask
    return out


def nrz_waveform(bits: Any, samples_per_symbol: Any, levels: Any = (0.0, 1.0)) -> np.ndarray:
    """NRZ 零阶保持波形：每个比特重复 samples_per_symbol 个采样。"""
    b = _validate_bits(bits)
    sps = _validate_sps(samples_per_symbol)
    lo, hi = _validate_levels(levels)
    return np.repeat(np.where(b > 0, hi, lo).astype(float), sps)


def preemphasis_taps(alpha: Any) -> np.ndarray:
    """1-tap FFE 抽头 [c0, c_-1] = [1+α, −α]（直流增益 = 1）。"""
    a = _finite_float(alpha, "alpha")
    if a < 0.0:
        raise ValueError(f"alpha 必须 ≥0（本模块只做正抽头预加重），实际 {a!r}")
    return np.array([1.0 + a, -a], dtype=float)


def deemphasis_db_to_alpha(db: Any) -> float:
    """去加重电平（dB，正数）→ α：α = 10^(db/20) − 1。"""
    d = _finite_float(db, "db")
    if d < 0.0:
        raise ValueError(f"db 必须 ≥0，实际 {d!r}")
    return float(10.0 ** (d / 20.0) - 1.0)


def alpha_to_deemphasis_db(alpha: Any) -> float:
    """α → 去加重电平（dB）：20·log10(1+α)。"""
    a = _finite_float(alpha, "alpha")
    if a < 0.0:
        raise ValueError(f"alpha 必须 ≥0，实际 {a!r}")
    return float(20.0 * np.log10(1.0 + a))


def apply_fir(signal: Any, taps: Any) -> np.ndarray:
    """通用因果 FIR：full 卷积 y = x * taps（长度 len(x)+len(taps)−1）。"""
    x = np.asarray(signal, dtype=float)
    t = np.asarray(taps, dtype=float)
    if x.ndim != 1 or x.size == 0:
        raise ValueError("signal 必须是非空一维数组")
    if t.ndim != 1 or t.size == 0:
        raise ValueError("taps 必须是非空一维数组")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(t)):
        raise ValueError("signal/taps 含非有限值")
    return np.convolve(x, t, mode="full")


def preemphasis_symbols(bits: Any, alpha: Any = 0.0, levels: Any = (0.0, 1.0)) -> np.ndarray:
    """按符号率做 1-tap 预加重：y[n] = (1+α)x[n] − αx[n−1]（首符号按已稳定处理）。

    连续位（x[n]=x[n−1]）回到 1×；过渡位被抬到 (1+α)×。α=0 为恒等。
    """
    b = _validate_bits(bits)
    a = _finite_float(alpha, "alpha")
    if a < 0.0:
        raise ValueError(f"alpha 必须 ≥0，实际 {a!r}")
    lo, hi = _validate_levels(levels)
    x = np.where(b > 0, hi, lo).astype(float)
    y = np.empty_like(x)
    y[0] = x[0]
    y[1:] = (1.0 + a) * x[1:] - a * x[:-1]
    return y


# ---------------------------------------------------------------------------
# 眼图
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EyeMetrics:
    """确定性眼图指标（本模块口径）。

    - level_one / level_zero：全局 1/0 比特输出的均值（两条电平轨）；
    - eye_height：**最坏情形垂直张开** = max_p { min(1 比特样本) − max(0 比特样本) }
      （峰值失真口径；≤0 表示眼闭合）；
    - eye_height_mean：同相位下的平均电平差 max_p { mean1[p] − mean0[p] }；
    - eye_width_ui：以最优相位为中心、worst-case 张开 > 0 的连续相位跨度 / sps
      （0 边限口径；理想通道 = 1.0 UI）；
    - jitter_pp_ui / jitter_rms_ui：每个 0↔1 跳变处过判决门限时刻相对理想
      符号边界的偏差，峰峰/均方根（单位 UI；确定性抖动 DJ，含 DDJ）；
    - optimal_phase_ui：最优采样相位（UI，0 = 符号边界）；
    - eye_height_frac：eye_height / (levels[1]−levels[0])。
    """
    eye_height: float
    eye_height_mean: float
    eye_height_frac: float
    eye_width_ui: float
    jitter_pp_ui: float
    jitter_rms_ui: float
    optimal_phase_ui: float
    level_one: float
    level_zero: float
    n_ones: int
    n_zeros: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "eye_height": self.eye_height,
            "eye_height_mean": self.eye_height_mean,
            "eye_height_frac": self.eye_height_frac,
            "eye_width_ui": self.eye_width_ui,
            "jitter_pp_ui": self.jitter_pp_ui,
            "jitter_rms_ui": self.jitter_rms_ui,
            "optimal_phase_ui": self.optimal_phase_ui,
            "level_one": self.level_one,
            "level_zero": self.level_zero,
            "n_ones": self.n_ones,
            "n_zeros": self.n_zeros,
        }


def _crossing_offset_samples(y: np.ndarray, boundary: int, vmid: float, half_window: int) -> float | None:
    lo = max(0, boundary - half_window)
    hi = min(y.size - 1, boundary + half_window)
    w = y[lo : hi + 1] - vmid
    sign_change = np.where(np.sign(w[:-1]) * np.sign(w[1:]) < 0)[0]
    if sign_change.size == 0:
        return None
    cand = lo + sign_change
    k = int(cand[np.argmin(np.abs(cand - boundary))])
    y0 = float(y[k])
    y1 = float(y[k + 1])
    frac = 0.0 if y1 == y0 else (vmid - y0) / (y1 - y0)
    return (k + frac) - boundary


def eye_metrics(
    waveform: Any,
    bits: Any,
    samples_per_symbol: Any,
    levels: Any = (0.0, 1.0),
    *,
    edge_guard_symbols: Any = 0,
) -> EyeMetrics:
    """从一个 UI 折叠的通道输出算确定性眼图指标（定义见 EyeMetrics）。"""
    y = np.asarray(waveform, dtype=float)
    if y.ndim != 1 or not np.all(np.isfinite(y)):
        raise ValueError("waveform 必须是一维有限数组")
    b = _validate_bits(bits)
    sps = _validate_sps(samples_per_symbol)
    lo, hi = _validate_levels(levels)
    if isinstance(edge_guard_symbols, bool) or not isinstance(edge_guard_symbols, (int, np.integer)):
        raise TypeError("edge_guard_symbols 必须是整数")
    guard = int(edge_guard_symbols)
    if guard < 0:
        raise ValueError("edge_guard_symbols 必须 ≥0")
    if guard * 2 >= b.size - 1:
        raise ValueError("edge_guard_symbols 过大，剩余符号不足")
    if y.size < b.size * sps:
        raise ValueError(
            f"waveform 长度 {y.size} < bits×sps = {b.size * sps}，无法折叠为眼图"
        )
    bb = b[guard : b.size - guard]
    yy = y[guard * sps : (b.size - guard) * sps]
    n = bb.size
    seg = yy.reshape(n, sps)
    ones = bb > 0
    n_ones = int(np.count_nonzero(ones))
    n_zeros = int(n - n_ones)
    if n_ones == 0 or n_zeros == 0:
        raise ValueError("折叠窗口内必须同时含 0 与 1 比特")
    min1 = seg[ones].min(axis=0)
    max0 = seg[~ones].max(axis=0)
    mean1 = seg[ones].mean(axis=0)
    mean0 = seg[~ones].mean(axis=0)
    open_worst = min1 - max0
    open_mean = mean1 - mean0
    best = int(np.argmax(open_worst))
    eye_height = float(open_worst[best])
    swing = hi - lo
    left = best
    while left - 1 >= 0 and open_worst[left - 1] > 0.0:
        left -= 1
    right = best
    while right + 1 < sps and open_worst[right + 1] > 0.0:
        right += 1
    eye_width = (right - left + 1) / float(sps) if eye_height > 0.0 else 0.0

    level_one = float(seg[ones].mean())
    level_zero = float(seg[~ones].mean())
    vmid = 0.5 * (level_one + level_zero)
    half_window = max(1, sps)
    offsets = []
    for i in range(1, n):
        if bb[i] == bb[i - 1]:
            continue
        off = _crossing_offset_samples(yy, i * sps, vmid, half_window)
        if off is not None:
            offsets.append(off)
    if offsets:
        arr = np.asarray(offsets, dtype=float)
        jitter_pp = float(arr.max() - arr.min()) / sps
        jitter_rms = float(arr.std()) / sps
    else:
        jitter_pp = 0.0
        jitter_rms = 0.0

    return EyeMetrics(
        eye_height=eye_height,
        eye_height_mean=float(open_mean[best]),
        eye_height_frac=eye_height / swing,
        eye_width_ui=float(eye_width),
        jitter_pp_ui=jitter_pp,
        jitter_rms_ui=jitter_rms,
        optimal_phase_ui=best / float(sps),
        level_one=level_one,
        level_zero=level_zero,
        n_ones=n_ones,
        n_zeros=n_zeros,
    )


@dataclass(frozen=True)
class ChannelEyeResult:
    """一次通道仿真 + 眼图折叠的完整结果（数组不参与 to_dict）。"""
    metrics: EyeMetrics
    waveform: np.ndarray
    bits: np.ndarray
    samples_per_symbol: int
    dt: float
    impulse: np.ndarray
    tx_symbols: np.ndarray

    def time_axis_s(self) -> np.ndarray:
        return np.arange(self.waveform.size, dtype=float) * self.dt

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "samples_per_symbol": self.samples_per_symbol,
            "dt_s": self.dt,
            "n_bits": int(self.bits.size),
            "impulse_samples": int(self.impulse.size),
        }
        out.update(self.metrics.to_dict())
        return out


def run_channel_eye(
    bits: Any,
    samples_per_symbol: Any,
    freqs_hz: Any,
    s21: Any,
    *,
    symbol_rate_baud: Any = None,
    alpha: Any = 0.0,
    levels: Any = (0.0, 1.0),
    n_periods: Any = 3,
    edge_guard_symbols: Any = 0,
) -> ChannelEyeResult:
    """通道 S 参数 + 比特序列 → 眼图指标（确定性）。

    比特序列按 n_periods 次重复（缺省 3）以消除起止瞬态；只对**中间一份**
    做眼图折叠（稳态周期激励）。通道冲激响应按**主响应到达时刻**对齐到符号
    时钟（start = argmax|h|，即传播时延）。注意：不能用冲激响应质心对齐——
    一阶 RC 的 h 在 t=0 有跳变，带限重构的 Gibbs 振铃长尾会把质心拉成负值
    （本模块实测 centroid≈-3.6 samples，argmax≈1）。
    symbol_rate_baud 目前只用于调用方换算（本函数指标均以 UI 为单位）。
    """
    b = _validate_bits(bits)
    sps = _validate_sps(samples_per_symbol)
    if symbol_rate_baud is not None:
        _positive_float(symbol_rate_baud, "symbol_rate_baud")
    if isinstance(n_periods, bool) or not isinstance(n_periods, (int, np.integer)):
        raise TypeError("n_periods 必须是整数")
    reps = int(n_periods)
    if reps < 1:
        raise ValueError(f"n_periods 必须 ≥1，实际 {reps}")
    tx = preemphasis_symbols(b, alpha, levels)
    wave_ext = np.repeat(np.tile(tx, reps), sps)
    h, dt = impulse_response(freqs_hz, s21)
    peak = int(np.argmax(np.abs(h)))
    if not np.isfinite(h[peak]) or abs(float(h[peak])) < 1e-300:
        raise ValueError("冲激响应全零，无法定位主响应到达时刻")
    start = peak
    y_full = np.convolve(wave_ext, h)
    y_aligned = y_full[start : start + wave_ext.size]
    if y_aligned.size < wave_ext.size:
        raise ValueError("时域记录不足（频点数太少），无法对齐输出")
    k0 = (reps // 2) * b.size
    y_mid = y_aligned[k0 * sps : (k0 + b.size) * sps]
    if y_mid.size < b.size * sps:
        raise ValueError("中间周期样本不足，增大 n_periods 或频点数")
    m = eye_metrics(y_mid, b, sps, levels, edge_guard_symbols=edge_guard_symbols)
    return ChannelEyeResult(
        metrics=m,
        waveform=y_mid,
        bits=b,
        samples_per_symbol=sps,
        dt=dt,
        impulse=h,
        tx_symbols=tx,
    )


# ---------------------------------------------------------------------------
# Touchstone .s2p 读写（真实通道数据入口）
# ---------------------------------------------------------------------------

def save_touchstone_s2p(
    path: Any,
    freqs_hz: Any,
    s21: Any,
    *,
    s11: Any = None,
    z0: Any = 50.0,
) -> Path:
    """写标准 Touchstone v1（# HZ S RI R z0）2 端口文件。

    默认 S11=S22=0（理想匹配）、S12=S21（互易）——只描述通道的 S21 口径。
    """
    f = np.asarray(freqs_hz, dtype=float)
    if f.ndim != 1 or f.size == 0:
        raise ValueError("freqs_hz 必须是非空一维数组")
    if not np.all(np.isfinite(f)) or not np.all(np.diff(f) > 0):
        raise ValueError("freqs_hz 必须有限且严格单调递增")
    s = _check_s21(f, s21)
    ref = _positive_float(z0, "z0")
    if s11 is None:
        s11_arr = np.zeros(f.size, dtype=complex)
    else:
        s11_arr = np.asarray(s11, dtype=complex)
        if s11_arr.shape != f.shape:
            raise ValueError("s11 形状与 freqs_hz 不一致")
    p = Path(path)
    lines = [
        "! rfauto core/si_channel.py 合成 2 端口通道（S11=S22=0，S12=S21）",
        f"# HZ S RI R {ref}",
    ]
    for k in range(f.size):
        lines.append(
            f"{f[k]:.10e} {s11_arr[k].real:.10e} {s11_arr[k].imag:.10e} "
            f"{s[k].real:.10e} {s[k].imag:.10e} {s[k].real:.10e} {s[k].imag:.10e} "
            f"{s11_arr[k].real:.10e} {s11_arr[k].imag:.10e}"
        )
    p.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    return p


def load_touchstone_s2p(path: Any) -> tuple[np.ndarray, np.ndarray, float]:
    """读 2 端口 Touchstone（skrf），返回 (freqs_hz, s21, z0)。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"找不到 Touchstone 文件：{p}")
    ntwk = skrf.Network(str(p))
    if ntwk.nports < 2:
        raise ValueError(f"需要 ≥2 端口文件，实际 {ntwk.nports} 端口：{p}")
    f = np.asarray(ntwk.f, dtype=float)
    s21 = np.asarray(ntwk.s[:, 1, 0], dtype=complex)
    return f, s21, float(np.real(np.asarray(ntwk.z0).ravel()[0]))
