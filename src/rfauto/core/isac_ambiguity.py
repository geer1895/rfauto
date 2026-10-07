"""NX-2 雷达/ISAC 指标闭式面：距离/多普勒分辨率 + 模糊函数（Woodward 口径）。

规格：研究扩充 round14 §四 NX-2——"ΔR=c/2B、
Δv=λ/2T、LFM/码片模糊函数（Woodward 性质对拍）；ISAC 只做指标口径不做
处理链（尊重 L819-821 no-go）"。来源 TR 38.768（V19.2.0 免费）/
arXiv:2512.03506（口径名，页码 UNVERIFIED 如实）。

模块面
------
- ``range_resolution_m``：ΔR = c/(2B)（LFM 匹配滤波 -3dB 主瓣半宽口径）。
- ``doppler_resolution_hz``：Δf = 1/T_coh（相干积累时间倒数）。
- ``velocity_resolution_m_s``：Δv = λ/(2T_coh) = c/(2 f_c T_coh)。
- ``unambiguous_range_m`` / ``unambiguous_velocity_m_s``：
  R_ua = c/(2·PRF)、v_ua = λ·PRF/4（奈奎斯特面）。
- ``lfm_ambiguity``：LFM 矩形包络脉冲模糊函数解析式
  |χ(τ,ν)| = (1−|τ|/T)·|sinc((ν−μτ)(T−|τ|))|，|τ|≤T，μ=B/T（斜率）；
  sinc(x)=sin(πx)/(πx)（归一化 sinc）。峰值 1@原点。
- ``pulse_ambiguity``：矩形脉冲（无调制）模糊函数
  |χ(τ,ν)| = (1−|τ|/T)·|sinc(ν(T−|τ|))|。
- ``chip_code_ambiguity``：任意相位码（Barker/M 序列等）码片级模糊函数
  数值闭式（码片重叠求和式，非 FFT 路径——独立裁判路）。
- ``woodward_volume_invariant``：Woodward 体积不变性
  ∫∫|χ(τ,ν)|²dτdν = |χ(0,0)|² = 1（归一化能量口径）——数值积分核验。

物理口径（全 SI）
------------------
* 模糊函数定义（Woodward）：χ(τ,ν) = ∫ s(t)·s*(t+τ)·e^{+j2πνt} dt（本模块
  约定 e^{+j2πνt}；|χ| 与符号约定无关）。s 能量归一化 → |χ(0,0)|=1。
* 码片级求和式（码片宽 t_c、码长 N、T=N·t_c）：τ 落在码片对齐网格内时
  χ(τ,ν) = Σ_k c_k c*_{k+m}·∫_overlap e^{j2πνt}dt——整数延迟格点
  τ=m·t_c 处退化为 aperiodic 自相关 × sinc(ν t_c(1−|m|/N)) 权重；
  本实现按连续 τ 的部分重叠解析积分（每对码片梯形窗 × 相位因子）。
* 解析 LFM 式推导：s(t)=1/√T·e^{jπμt²}·rect(t/T)，直接代入积分
  （τ>0 支换元 t'→t'+τ/2 折半）得上式；测试以数值积分模糊函数
  （同一定义数值路）对拍解析式（#118：双路互证）。
* 设计约束：纯标准库+numpy（数值路 numpy 网格积分）；非法输入显式
  ValueError；dict/数组输出有限数。

出处
----
1. round 文档：round14 §四 NX-2（本文首段引用）。
2. Woodward, "Probability and Information Theory with Applications to
   Radar" (1953)（模糊函数定义与体积不变性，口径名）；TR 38.768
   （ISAC 场景指标口径名）。页码 UNVERIFIED 如实（#122）。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = [
    "C0_M_S",
    "WOODWARD_SOURCE",
    "chip_code_ambiguity",
    "doppler_resolution_hz",
    "lfm_ambiguity",
    "numeric_ambiguity",
    "pulse_ambiguity",
    "range_resolution_m",
    "sinc_norm",
    "unambiguous_range_m",
    "unambiguous_velocity_m_s",
    "velocity_resolution_m_s",
    "woodward_volume_invariant",
]

C0_M_S = 299792458.0
WOODWARD_SOURCE = (
    "Woodward (1953) 模糊函数定义/体积不变性；TR 38.768 ISAC 指标口径名；"
    "页码 UNVERIFIED（#122 如实）"
)


def _positive(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def sinc_norm(x: Any) -> Any:
    """归一化 sinc：sin(πx)/(πx)，x=0 → 1（numpy 向量化）。"""
    xa = np.asarray(x, dtype=float)
    out = np.ones_like(xa)
    nz = np.abs(xa) > 1e-12
    out[nz] = np.sin(np.pi * xa[nz]) / (np.pi * xa[nz])
    return out if np.ndim(x) else float(out)


# ─── 分辨率/不模糊指标闭式 ───────────────────────────────────────────────────
def range_resolution_m(bandwidth_hz: Any) -> float:
    """距离分辨率 ΔR = c/(2B)（-3dB 主瓣口径，LFM/Pulse 压缩通用工程式）。"""
    b = _positive(bandwidth_hz, "bandwidth_hz")
    return C0_M_S / (2.0 * b)


def doppler_resolution_hz(coherent_time_s: Any) -> float:
    """多普勒分辨率 Δf = 1/T_coh（矩形窗 -3dB 口径）。"""
    t = _positive(coherent_time_s, "coherent_time_s")
    return 1.0 / t


def velocity_resolution_m_s(wavelength_m: Any, coherent_time_s: Any) -> float:
    """速度分辨率 Δv = λ/(2T_coh)。"""
    lam = _positive(wavelength_m, "wavelength_m")
    t = _positive(coherent_time_s, "coherent_time_s")
    return lam / (2.0 * t)


def unambiguous_range_m(prf_hz: Any) -> float:
    """最大不模糊距离 R_ua = c/(2·PRF)。"""
    prf = _positive(prf_hz, "prf_hz")
    return C0_M_S / (2.0 * prf)


def unambiguous_velocity_m_s(wavelength_m: Any, prf_hz: Any) -> float:
    """最大不模糊速度 v_ua = λ·PRF/4（±对称半程口径）。"""
    lam = _positive(wavelength_m, "wavelength_m")
    prf = _positive(prf_hz, "prf_hz")
    return lam * prf / 4.0


# ─── 解析模糊函数 ────────────────────────────────────────────────────────────
def lfm_ambiguity(tau_s: Any, nu_hz: Any, pulse_s: Any,
                  bandwidth_hz: Any) -> Any:
    """LFM 矩形包络脉冲模糊函数 |χ(τ,ν)|（解析式）。

    |χ(τ,ν)| = (1−|τ|/T)·|sinc((ν−μτ)(T−|τ|))|，|τ|≤T；μ=B/T。
    |τ|>T → 0。tau_s/nu_hz 标量或 ndarray（广播）。
    """
    t = _positive(pulse_s, "pulse_s")
    b = _positive(bandwidth_hz, "bandwidth_hz")
    mu = b / t
    tau = np.asarray(tau_s, dtype=float)
    nu = np.asarray(nu_hz, dtype=float)
    at = np.abs(tau)
    inside = at <= t
    with np.errstate(all="ignore"):
        tri = np.where(inside, 1.0 - at / t, 0.0)
        arg = (nu - mu * tau) * (t - at)
        val = tri * np.abs(sinc_norm(arg))
    val = np.where(inside, val, 0.0)
    if np.ndim(tau_s) == 0 and np.ndim(nu_hz) == 0:
        return float(val)
    return val


def pulse_ambiguity(tau_s: Any, nu_hz: Any, pulse_s: Any) -> Any:
    """矩形无调制脉冲模糊函数 |χ(τ,ν)| = (1−|τ|/T)|sinc(ν(T−|τ|))|，|τ|≤T。"""
    t = _positive(pulse_s, "pulse_s")
    tau = np.asarray(tau_s, dtype=float)
    nu = np.asarray(nu_hz, dtype=float)
    at = np.abs(tau)
    inside = at <= t
    with np.errstate(all="ignore"):
        tri = np.where(inside, 1.0 - at / t, 0.0)
        arg = nu * (t - at)
        val = tri * np.abs(sinc_norm(arg))
    val = np.where(inside, val, 0.0)
    if np.ndim(tau_s) == 0 and np.ndim(nu_hz) == 0:
        return float(val)
    return val


# ─── 码片码模糊函数（连续 τ 部分重叠解析求和）────────────────────────────────
def chip_code_ambiguity(tau_s: float, nu_hz: float, chips: Any,
                        chip_s: float) -> complex:
    """相位码序列的模糊函数 χ(τ,ν)（连续 τ 解析求和，复值）。

    码片 c_k ∈ {e^{jφ}}（|c_k|=1），码片宽 t_c，码长 N。定义
    χ(τ,ν) = (1/N)·Σ_k Σ_{k'} c_k c*_{k'}·I_kk'(τ,ν)，
    I_kk' = ∫ s(t) s*(t+τ) e^{j2πνt} dt 的码片对贡献——连续 τ 时只有
    延迟 |m| ≤ N−1 的码片对重叠，重叠区积分 = 梯形窗 × 线性相位因子，
    闭式：
      对 m>0（s(t+τ) 落后 m 格）：重叠长 w = t_c−frac，跨 k=m..N−1，
      ∫_{k·t_c+frac}^{(k+1)t_c} e^{j2πνt} dt · c_k c*_{k−m}
    归一化 1/N 使 χ(0,0)=1。τ<0 用共轭对称 χ(−τ,ν)=χ*(τ,−ν) 恒等式折返
    （测试钉）。只接受单个标量 τ（网格场景外层循环）。
    """
    c = np.asarray(chips, dtype=complex)
    n = int(c.shape[0])
    if n < 1:
        raise ValueError("chips 不得为空")
    tc = _positive(chip_s, "chip_s")
    tau = float(tau_s)
    nu = float(nu_hz)
    if not (math.isfinite(tau) and math.isfinite(nu)):
        raise ValueError("tau_s/nu_hz 必须有限")

    def _sum_delay(m: int, frac: float) -> complex:
        """τ = m·t_c + frac（m≥0, frac∈[0,t_c)）的求和。"""
        w = tc - frac
        if w <= 0.0:
            return 0j
        # ∫_{t0}^{t0+w} e^{j2πνt} dt = e^{j2πν(t0+w/2)}·w·sinc(νw)
        total = 0j
        for k in range(m, n):
            c_pair = c[k] * np.conj(c[k - m])
            if abs(c_pair) == 0.0:
                continue
            t0 = k * tc + frac
            integ = (math.cos(2.0 * math.pi * nu * (t0 + w / 2.0))
                     + 1j * math.sin(2.0 * math.pi * nu * (t0 + w / 2.0))
                     ) * w * float(sinc_norm(nu * w))
            total += complex(c_pair) * integ
        return total

    if tau >= 0.0:
        m = math.floor(tau / tc)
        if m > n - 1:
            return 0j
        frac = tau - m * tc
        return _sum_delay(m, frac) / (n * tc)
    # τ<0：χ(−τ,ν) = conj(χ(τ,−ν))（定义直接推论，测试钉）
    return np.conj(chip_code_ambiguity(-tau, -nu, c, tc))


def numeric_ambiguity(sig: Any, fs_hz: Any, tau_grid: Any,
                      nu_grid: Any) -> Any:
    """任意复基带信号的模糊函数数值路：|χ(τ,ν)| 网格（Riemann 积分）。

    χ(τ,ν) = Σ_t s(t)·s*(t+τ)·e^{j2πνt}/fs（能量不归一——测试侧先归一
    s 再调用）。s 为均匀采样复基带（fs_hz 采样率）。τ<0 走恒等式
    χ(−τ,ν)=χ*(τ,−ν)（定义级）；|τ|≥信号时长 → 0（截断不回绕）。
    独立裁判路（#118）：与 lfm_ambiguity/chip_code_ambiguity 解析式对拍。
    """
    s = np.asarray(sig, dtype=complex)
    fs = _positive(fs_hz, "fs_hz")
    taus = np.atleast_1d(np.asarray(tau_grid, dtype=float))
    nus = np.atleast_1d(np.asarray(nu_grid, dtype=float))
    out = np.empty((taus.size, nus.size), dtype=float)
    n = s.size
    t_axis = np.arange(n) / fs

    def _eval_one(tau: float, nu: float) -> float:
        shift = round(tau * fs)
        if abs(shift) >= n:
            return 0.0
        if shift < 0:
            # χ(−τ,ν) = χ*(τ,−ν)
            return _eval_one(-tau, -nu)
        seg1 = s[: n - shift]
        seg2 = np.conj(s[shift:])
        integral = float(np.sum(
            np.real(seg1 * seg2 * np.exp(2j * np.pi * nu * t_axis[: seg1.size]))
        )) / fs
        imag = float(np.sum(
            np.imag(seg1 * seg2 * np.exp(2j * np.pi * nu * t_axis[: seg1.size]))
        )) / fs
        return math.hypot(integral, imag)

    for i, tau in enumerate(taus):
        for j, nu in enumerate(nus):
            out[i, j] = _eval_one(float(tau), float(nu))
    return out


def woodward_volume_invariant(sig: Any, fs_hz: Any, tau_max_s: Any,
                              nu_max_hz: Any, n_tau: int = 201,
                              n_nu: int = 201) -> dict[str, float]:
    """Woodward 体积不变性数值核验：∫∫|χ|²dτdν ≈ |χ(0,0)|²（能量归一 s）。

    有限网格截断误差如实报告（residual 就是核验量）；解析信号族
    （LFM/矩形脉冲）的截断主导项 O(窗宽比) 在测试按容差判定。
    返回 {volume_integral, chi00_sq, relative_residual}。
    """
    taus = np.linspace(-tau_max_s, tau_max_s, n_tau)
    nus = np.linspace(-nu_max_hz, nu_max_hz, n_nu)
    mag = numeric_ambiguity(sig, fs_hz, taus, nus)
    d_tau = float(taus[1] - taus[0])
    d_nu = float(nus[1] - nus[0])
    vol = float(np.sum(mag**2) * d_tau * d_nu)
    chi00 = float(np.sum(np.asarray(sig, dtype=complex)
                         * np.conj(np.asarray(sig, dtype=complex))) / fs_hz)
    chi00_sq = abs(chi00) ** 2
    rel = abs(vol - chi00_sq) / chi00_sq if chi00_sq > 0.0 else math.inf
    return {
        "volume_integral": vol,
        "chi00_sq": chi00_sq,
        "relative_residual": rel,
    }
