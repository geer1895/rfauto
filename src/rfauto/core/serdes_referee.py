"""DR-2/DR-3 高速串行裁判核：IEEE370 ERL/ILD 度量 + TDR/TDT 双路裁判。

规格（round16 DR-2/DR-3；席6 任务书 DR-2/DR-3）：

**DR-2 ILD（插入损耗偏差）**：ILD(f) = IL(f) − IL_fit(f)，IL_fit 为判据
频带内 IL(dB) 对频率的**线性最小二乘拟合**（802.3 系口径的 ILD 参考线
定义）；报告 max/min/RMS。定义式为判据本身的定义（fit 形态=最小二乘
直线），数学性质（纯直线信道 ILD≡0、均零微扰精确回收）测试钉。

**DR-2 ERL（有效回损）**：
    ERL = −10·log10( Σ_k w_k·|r_k|² / Σ_k w_k ),  w_k = |t_k|²
（通带加权反射能量口径——OIF CEI/802.3ck 公开材料引用的定义族；本批
 未能在线核对原文数值门限，权重归一化与门限值不 ship，数学性质测试
 钉：恒定 |r| 时 ERL=RL；通带加权 ≤ 无权 RL）。**诚实边界（#122）**：
 判据频带与门限数值须调用方给入（正式门原文核对后回填）。

**DR-3 TDR/TDT 双路裁判**：阻抗剖面双实现互证 + 解析锚：
- 路线 A（频域阻抗→时域）：ρ(f)=S11(f)，Z(f)=Z0(1+ρ)/(1−ρ)，时域阶跃
  剖面 Z(t) 经 IFFT（窗可选）；
- 路线 B（阶跃反射直接合成）：ρ(t)=IFFT(S11)→r(t) 阶跃响应（积分域
  重构）→ Z(t)=Z0(1+r(t))/(1−r(t))；
- 解析锚（#118）：匹配线全程 Z=Z0；末端负载 Z(t→末端)=Z_L；双段线在
  段延迟处阶跃 Z0→Z2（无损线 TDR 经典结论，闭式）。
**口径勘误（round16 实测）**：skrf 2.1.0 的 ``Network`` **无**
``z_time_step`` 属性（round16 "skrf z_time_step 现成"口径过时，2026-10-03
实测 hasattr=False）——双路均为本仓自实现，以上述解析锚互证。

全部确定性：纯 numpy/scipy 叶子；输入 skrf.Network 或 (freq, s11) 数组。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

_C0 = 299792458.0


def _coerce_s11(net: Any) -> tuple[np.ndarray, np.ndarray]:
    """skrf.Network 或 (freq_hz, s11 数组) 二态入参归一。"""
    if hasattr(net, "s") and hasattr(net, "f"):
        return (np.asarray(net.f, dtype=float),
                np.asarray(net.s[:, 0, 0], dtype=complex))
    freq, s11 = net
    freq = np.asarray(freq, dtype=float)
    s11 = np.asarray(s11, dtype=complex)
    if s11.shape != freq.shape:
        raise ValueError(
            f"freq/s11 形状须一致，得到 {freq.shape}/{s11.shape}")
    return freq, s11


# ── DR-2 ILD ─────────────────────────────────────────────────────────────────


def insertion_loss_deviation(
    s21: Any, freq_hz: Any, *,
    band: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """ILD(f) = IL(f) − 线性最小二乘拟合线（802.3 系 ILD 口径）。

    Args:
        s21: S21 复数组（或 skrf.Network，取 s[:,1,0]）。 freq_hz: 频率轴
            [Hz]。 band: 判据频带 (f_lo, f_hi)；None=全带。
    """
    if hasattr(s21, "s") and hasattr(s21, "f"):
        freq_hz, s21 = np.asarray(s21.f, float), np.asarray(
            s21.s[:, 1, 0], complex)
    f = np.asarray(freq_hz, dtype=float)
    s = np.asarray(s21, dtype=complex)
    if s.shape != f.shape:
        raise ValueError(f"freq/s21 形状须一致，得到 {f.shape}/{s.shape}")
    il_db = -20.0 * np.log10(np.abs(s) + 1e-300)
    sel = np.ones(f.size, dtype=bool)
    if band is not None:
        sel = (f >= float(band[0])) & (f <= float(band[1]))
        if int(sel.sum()) < 2:
            raise ValueError("判据频带内不足 2 点")
    f_b, il_b = f[sel], il_db[sel]
    slope, icpt = np.polyfit(f_b, il_b, 1)
    ild = il_db - (slope * f + icpt)
    return {
        "ok": True,
        "freq_hz": f,
        "ild_db": ild,
        "fit_slope_db_per_hz": float(slope),
        "fit_intercept_db": float(icpt),
        "ild_max_db": float(np.max(ild[sel])),
        "ild_min_db": float(np.min(ild[sel])),
        "ild_rms_db": float(np.sqrt(np.mean(ild[sel] ** 2))),
        "band": band,
        "n_band_points": int(sel.sum()),
    }


def effective_return_loss(
    s11: Any, s21: Any, freq_hz: Any, *,
    band: tuple[float, float] | None = None,
    floor_lin: float = 1e-6,
) -> dict[str, Any]:
    """ERL = −10log10( Σw|r|²/Σw ), w=|t|²（通带加权反射能量，定义见 docstring）。

    floor_lin：权重地板（|t|² 低于该值的深谷频点不参与加权——权重趋零
    处反射信息物理无关；显式丢弃并计数，不静默）。
    """
    f = np.asarray(freq_hz, dtype=float)
    r = np.abs(np.asarray(s11, dtype=complex))
    t2 = np.abs(np.asarray(s21, dtype=complex)) ** 2
    if not (r.shape == t2.shape == f.shape):
        raise ValueError("freq/s11/s21 形状须一致")
    sel = np.ones(f.size, dtype=bool)
    if band is not None:
        sel = (f >= float(band[0])) & (f <= float(band[1]))
    w = t2[sel]
    keep = w >= float(floor_lin)
    if not keep.any():
        raise ValueError("判据频带内全部频点 |S21|² 低于权重地板")
    num = float(np.sum(w[keep] * r[sel][keep] ** 2))
    den = float(np.sum(w[keep]))
    erl_db = -10.0 * math.log10(num / den + 1e-300)
    rl_flat = -20.0 * math.log10(
        float(np.sqrt(np.mean(r[sel][keep] ** 2))) + 1e-300)
    return {
        "ok": True,
        "erl_db": erl_db,
        "unweighted_rl_db": rl_flat,
        "n_weighted_points": int(keep.sum()),
        "n_dropped_low_t": int(sel.sum() - keep.sum()),
        "band": band,
    }


# ── DR-3 TDR 双路裁判 ────────────────────────────────────────────────────────


def tdr_impedance_profile(
    s11: Any, *,
    z_ref_ohm: float = 50.0,
    window: str = "hann",
) -> dict[str, Any]:
    """TDR 阻抗剖面双路互证（路线定义与解析锚见模块 docstring）。

    路线 1（FFT 路线）：半谱共轭偶对称展开 → irfft → 实冲激响应 ρ(t) →
    阶跃响应 r(t)=∫ρ（cumsum×dt）→ Z(t)=Z0(1+r)/(1−r)。
    路线 2（显式余弦和路线）：r(t_k) 逐点实值余弦和直接求和（与 FFT 实现
    独立的第二计算路径，#118 双路互证）。
    频域参考：Z(f)=Z0(1+ρ)/(1−ρ)（|ρ|<0.98 有效域，缺失留痕）。

    Returns:
        dict(t_s, z_fft_ohm, z_csum_ohm, z_freq_ref_ohm（频域参考，含 NaN）,
        freq_hz_valid, n_rho_valid, z_final_ohm, r_step_final, window,
        z_ref_ohm, dt_s)
    """
    freq, s11 = _coerce_s11(s11)
    z0 = float(z_ref_ohm)
    n = s11.size
    if n < 4:
        raise ValueError("S11 至少 4 点（时域分辨率）")
    if not (freq[1] > freq[0]):
        raise ValueError("频率轴须严格升序")
    win = {"none": np.ones(n), "hann": np.hanning(n),
           "kaiser": np.kaiser(n, 6.0)}[window]
    sw = s11 * win
    # ── 路线 1：irfft（半谱共轭偶对称 → 实冲激响应）──────────────────────
    full = np.concatenate([sw, np.conj(sw[-2:0:-1])])
    n_full = full.size                      # 2(n−1)
    df = freq[1] - freq[0]
    dt = 1.0 / (n_full * df)
    # 无量纲阶跃标度：ρ 采样 = irfft（其 [0] 项=DC 权重），阶跃 = cumsum
    # （dt·(N·df)=1 的恒等已在推导中吸收——乘 dt 会使阶跃终值缩没 ~0，
    # 2026-10-03 实测钉：S11≡−1 时 Z(∞) 必须给 0 而非 Z0）
    rho_t = np.fft.irfft(full, n=n_full)
    step_fft = np.cumsum(rho_t)
    z_fft = z0 * (1.0 + step_fft) / (1.0 - step_fft + 1e-300)
    # ── 路线 2：显式余弦和（实现独立第二路；实信号逆 DFT 闭式：
    # x[m]=(X0 + 2Σ_{k=1}^{N/2−1}(Xk·e) + X_Nyq·cos(πm))/N，Nyquist 不加倍）──
    t_idx = np.arange(n_full)
    phase = 2.0 * np.pi * np.outer(t_idx, np.arange(n)) / n_full
    half = n - 1  # Nyquist 列号（n 为正频点数，含 Nyquist）
    main = 2.0 * (np.cos(phase[:, 1:half]) * sw.real[None, 1:half]
                  - np.sin(phase[:, 1:half]) * sw.imag[None, 1:half]).sum(axis=1)
    nyq_term = sw.real[half] * np.cos(math.pi * t_idx)
    rho_csum = (sw.real[0] + main + nyq_term) / n_full
    step_csum = np.cumsum(rho_csum)
    z_csum = z0 * (1.0 + step_csum) / (1.0 - step_csum + 1e-300)
    # ── 频域参考 ──────────────────────────────────────────────────────────
    rho_mag = np.abs(s11)
    valid = rho_mag < 0.98
    z_f = np.where(valid,
                   z0 * (1.0 + s11) / np.where(valid, 1.0 - s11, 1.0),
                   np.nan + 0j)
    t_axis = np.arange(n_full) * dt
    return {
        "ok": True,
        "t_s": t_axis,
        "dt_s": float(dt),
        "z_fft_ohm": z_fft,
        "z_csum_ohm": z_csum,
        "z_freq_ref_ohm": z_f,
        "freq_hz_valid": freq[valid],
        "n_rho_valid": int(valid.sum()),
        "z_final_ohm": float(z_fft[-1]),
        "r_step_final": float(step_fft[-1]),
        "window": window,
        "z_ref_ohm": z0,
    }


def tdr_two_route_disagreement(prof_a: np.ndarray, prof_b: np.ndarray,
                               *,
                               rel_floor_ohm: float = 1.0) -> float:
    """双路剖面相对分歧：max|A−B|/max(|median(B)|, floor)（裁判口径）。"""
    a = np.asarray(prof_a, dtype=float)
    b = np.asarray(prof_b, dtype=float)
    if a.shape != b.shape:
        raise ValueError(
            f"双路剖面形状须一致，得到 {a.shape}/{b.shape}")
    denom = max(abs(float(np.median(b))), float(rel_floor_ohm))
    return float(np.max(np.abs(a - b)) / denom)
