"""d5-array: 阵列综合内核（单元方向图 × 阵列因子，续跑计划 §10.4 D5）。

权威口径
========
- C. A. Balanis, Antenna Theory: Analysis and Design, 3rd ed., Wiley, Ch. 6
  ("Arrays: Linear, Planar, and Circular")：
  * 均匀直线阵（ULA）阵列因子闭式 |sin(N*psi/2) / (N*sin(psi/2))|（§6.3）；
  * 方向图积定理 F_total(theta, phi) = F_element(theta, phi) * AF(theta, phi)
    （"Multiplication of Patterns"）；
  * 侧射阵半功率波束宽度渐近式 HPBW ~ 0.886 * lambda / (N*d) rad（大阵）；
  * 栅瓣判据：扫描方向余弦 u0 下 d/lambda <= 1/(1+|u0|)（可见区 |u|<=1）；
  * Dolph-Chebyshev 非均匀加权：T_{N-1}(x0*cos(psi/2))，
    x0 = cosh(acosh(R)/(N-1))，R = 10^(-SLL_dB/20)（等副瓣）；
  * 二项式（binomial）加权：权重取二项式系数，d=lambda/2 时无副瓣。
- C. L. Dolph, "A Current Distribution for Broadside Arrays Which Optimizes the
  Relationship Between Beam Width and Side-Lobe Level", Proc. IRE, 1946.
- Balanis Ch. 6 §6.10 平面阵（"Planar Array"）：矩形栅格平面阵的阵列因子可分离
  AF(θ,φ) = AF_x(u)·AF_y(v)，u = sinθcosφ、v = sinθsinφ（C2 阵列族 2×2 裁判，
  2026-09-15 加法式扩展 planar_array_factor）。
- Balanis Ch. 14 微带天线腔模型（"Microstrip Antennas", 传输线/腔模型双缝口径）：
  矩形贴片 = 两条平行的等效磁流缝（长 W、厚 h，相距 L，同相），置于无限大
  地面上（镜像加倍、仅上半空间 θ∈[0°,90°]）；单元方向图闭式
  patch_element_field（E 面 ∝ cos((k0L/2)sinθ)、H 面 ∝ cosθ·sinc((k0W/2)sinθ)，
  见函数文档的矢量推导）。

本模块只做确定性闭式/多项式代数（纯 numpy），不含求解器、无网络、无真机；
单元方向图由调用方以闭式或实测数据给出（本模块附半波振子闭式与矩形贴片
腔模型闭式作单元）。

约定
====
- 所有距离以波长为单位（spacing_lambda = d/lambda），避免 lambda 显式出现；
- 方向余弦 u：z 轴阵 u = cos(theta)；x 轴阵 u = sin(theta)cos(phi)；
  y 轴阵 u = sin(theta)sin(phi)；
- 扫描相位折算为 u0（例如 z 轴扫描到 theta0 时 u0 = cos(theta0)），
  阵列因子 AF = sum_n w_n * exp(j*2*pi*(d/lambda)*(u-u0)*n)；
- 权重按阵列几何顺序给出；合成加权（uniform/binomial/chebyshev）为对称分布，
  归一化到 max|w| = 1。

验收（§10.4 D5）：对照解析/闭式——均匀阵 AF 闭式、HPBW 公式、栅瓣判据边界、
Chebyshev 副瓣电平达标、方向图积定理；全波小阵对照属后续工作，不在本模块。
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from math import comb

import numpy as np
from numpy.polynomial import chebyshev as _cheb
from numpy.polynomial import polynomial as _poly

__all__ = [
    "AXES",
    "ChebyshevDesign",
    "TaylorDesign",
    "aperture_to_n_elements",
    "array_factor",
    "array_factor_angles",
    "bayliss_weights",
    "binomial_weights",
    "broadside_hpbw_deg",
    "broadside_hpbw_rad",
    "chebyshev_weights",
    "difference_array_factor",
    "difference_pattern_psll_db",
    "direction_cosine",
    "field_db",
    "grating_lobe_direction_cosines",
    "grating_lobe_free_max_spacing",
    "half_wave_dipole_field",
    "has_grating_lobe",
    "patch_element_field",
    "pattern_multiplication",
    "peak_sidelobe_level_db",
    "planar_array_factor",
    "schelkunoff_nulls",
    "series_feed_array_factor",
    "series_feed_beam_direction_cosine",
    "series_feed_excitations",
    "series_feed_progressive_phase",
    "steering_direction_cosine",
    "synthesize_chebyshev",
    "synthesize_taylor",
    "taylor_weights",
    "uniform_af_closed_form",
    "uniform_weights",
    "villeneuve_weights",
]

AXES = ("z", "x", "y")
"""支持的线阵取向：u 为 theta/phi 函数的方向余弦映射。"""

_TINY = 1e-12


# ─── 输入校验 ──────────────────────────────────────────────────────────────────

def _validate_axis(axis: str) -> str:
    if axis not in AXES:
        raise ValueError(f"axis 必须是 {AXES} 之一，收到 {axis!r}")
    return axis


def _validate_weights(weights) -> np.ndarray:
    w = np.asarray(weights, dtype=float)
    if w.ndim != 1:
        raise ValueError(f"weights 必须是一维数组，收到 shape={w.shape}")
    if w.size < 1:
        raise ValueError("weights 至少需要 1 个单元")
    if not np.all(np.isfinite(w)):
        raise ValueError("weights 含非有限值（nan/inf）")
    if abs(float(w.sum())) <= _TINY:
        raise ValueError("weights 之和为 0，无法归一化")
    return w


def _validate_spacing(spacing_lambda: float) -> float:
    s = float(spacing_lambda)
    if not np.isfinite(s) or s <= 0.0:
        raise ValueError(f"spacing_lambda 必须为正的有限值，收到 {spacing_lambda!r}")
    return s


def _validate_scan(scan_direction_cosine: float) -> float:
    u0 = float(scan_direction_cosine)
    if not np.isfinite(u0):
        raise ValueError(f"scan_direction_cosine 必须有限，收到 {scan_direction_cosine!r}")
    if abs(u0) > 1.0 + 1e-9:
        raise ValueError(f"方向余弦必须落在 [-1, 1]，收到 {scan_direction_cosine!r}")
    return min(1.0, max(-1.0, u0))


# ─── 方向余弦 / 扫描 ───────────────────────────────────────────────────────────

def direction_cosine(theta_deg, phi_deg=0.0, axis: str = "z") -> np.ndarray:
    """把角度 (theta, phi)（度）映射为线阵的方向余弦 u。

    z 轴阵 u=cos(theta)；x 轴阵 u=sin(theta)cos(phi)；y 轴阵 u=sin(theta)sin(phi)。
    """
    ax = _validate_axis(axis)
    theta = np.radians(np.asarray(theta_deg, dtype=float))
    phi = np.radians(np.asarray(phi_deg, dtype=float))
    if ax == "z":
        return np.cos(theta)
    transverse = np.sin(theta)
    if ax == "x":
        return transverse * np.cos(phi)
    return transverse * np.sin(phi)


def steering_direction_cosine(scan_deg: float, scan_phi_deg: float = 0.0, axis: str = "z") -> float:
    """扫描角 -> 方向余弦 u0（作为 array_factor 的扫描变量）。"""
    return float(direction_cosine(scan_deg, scan_phi_deg, axis))


# ─── 加权 ─────────────────────────────────────────────────────────────────────

def uniform_weights(n_elements: int) -> np.ndarray:
    """均匀加权（全部 1）。"""
    n = int(n_elements)
    if n < 1:
        raise ValueError(f"n_elements 至少为 1，收到 {n_elements!r}")
    return np.ones(n, dtype=float)


def binomial_weights(n_elements: int) -> np.ndarray:
    """二项式加权：第 k 个权重 = C(N-1, k)（归一化到 max|w|=1）。

    d=lambda/2 时阵列因子单调无副瓣（Balanis Ch. 6，binomial array）。
    """
    n = int(n_elements)
    if n < 1:
        raise ValueError(f"n_elements 至少为 1，收到 {n_elements!r}")
    w = np.array([comb(n - 1, k) for k in range(n)], dtype=float)
    return w / w.max()


def _chebyshev_power(k: int) -> np.ndarray:
    """T_k(x) 的幂基系数（升幂）。"""
    return _cheb.cheb2poly(np.eye(1, k + 1, k).ravel())


def _half_cosine_basis(m: int) -> list[np.ndarray]:
    """V_k(c) = cos((k-1/2)*psi)/cos(psi/2)，c=cos(psi)，k=1..m 的幂基系数。

    递推 V_{k+1} = 2c*V_k - V_{k-1}，V_1 = 1，V_2 = 2c-1。
    """
    basis = [np.array([1.0])]
    if m >= 2:
        basis.append(np.array([-1.0, 2.0]))
    for k in range(2, m):
        current = basis[k - 1]
        previous = basis[k - 2]
        nxt = np.convolve(np.array([0.0, 2.0]), current)
        nxt[: previous.size] -= previous
        basis.append(nxt)
    return basis


def chebyshev_weights(n_elements: int, sidelobe_level_db: float) -> np.ndarray:
    """Dolph-Chebyshev 加权（闭式多项式代数），给定副瓣电平目标。

    构造 T_{N-1}(x0*cos(psi/2))，x0 = cosh(acosh(R)/(N-1))，
    R = 10^(-SLL_dB/20)：峰值=R、全部副瓣=1（即 -SLL_dB），等副瓣。

    N 为奇数时把偶 Chebyshev 多项式写成 cos(psi) 的幂、再转 Chebyshev 基
    （poly2cheb）直接读出权重；N 为偶数时把奇多项式分解为
    cos(psi/2) * W(cos psi) 并在半角余弦基 V_k 上求解三角系数。
    返回对称权重，归一化到 max|w| = 1。
    """
    n = int(n_elements)
    if n < 2:
        raise ValueError("Chebyshev 加权要求 n_elements >= 2（N-1 阶多项式）")
    sll = float(sidelobe_level_db)
    if not np.isfinite(sll) or sll >= 0.0:
        raise ValueError(f"sidelobe_level_db 必须为负的有限值（dB），收到 {sidelobe_level_db!r}")
    ratio = 10.0 ** (-sll / 20.0)
    if ratio <= 1.0:
        raise ValueError("副瓣电平目标对应的电压比必须 > 1")
    x0 = float(np.cosh(np.arccosh(ratio) / (n - 1)))
    half_sq = 0.5 * x0 * x0
    substitution = _poly.Polynomial([half_sq, half_sq])  # s = x0^2*(1+c)/2
    if n % 2 == 1:
        m = (n - 1) // 2
        even = _chebyshev_power(2 * m)[0::2].copy()  # T_{2m}(t) 的偶次项 -> s 多项式
        coeffs = _cheb.poly2cheb(_poly.Polynomial(even)(substitution).coef)
        w = np.empty(n, dtype=float)
        w[m] = coeffs[0]
        idx = np.arange(1, m + 1)
        w[m - idx] = coeffs[idx] / 2.0
        w[m + idx] = coeffs[idx] / 2.0
    else:
        m = n // 2
        odd = _chebyshev_power(2 * m - 1)[1::2].copy()  # T_{2m-1}(t)/t 的 s 多项式
        target = _poly.Polynomial(odd)(substitution).coef
        basis = _half_cosine_basis(m)
        matrix = np.zeros((m, m), dtype=float)
        for k, v in enumerate(basis):
            matrix[: v.size, k] = v
        coeffs = np.linalg.solve(matrix, target)
        w = np.empty(n, dtype=float)
        idx = np.arange(1, m + 1)
        w[m - idx] = coeffs / 2.0
        w[m + idx - 1] = coeffs / 2.0
    return w / np.abs(w).max()


def taylor_weights(n_elements: int, sidelobe_level_db: float,
                   nbar: int = 4) -> np.ndarray:
    """Taylor n-bar 加权（连续线源口径的离散采样），给定副瓣电平目标。

    口径（T. T. Taylor 1955；Carrara & Goodman & Majewski, "Spotlight
    Synthetic Aperture Radar", 1995, pp.512-513）：等纹波近主瓣副瓣
    （近主瓣 nbar 个副瓣 ≈ 目标电平）+ 远区副瓣按 1/u 滚降——与
    Dolph-Chebyshev 的全等副瓣形成区分。

    构造（零新依赖，纯 numpy）：
        R = 10^(-SLL_dB/20)（电压比）, A = acosh(R)/π,
        σ = nbar / sqrt(A² + (nbar−1/2)²)（零点展宽因子）,
        F_m (m=1..nbar−1) 由零点 z_n = σ·sqrt(A² + (n−1/2)²) 的乘积式给出，
        w_k = 1 + 2·Σ_m F_m·cos(2πm(k − N/2 + 1/2)/N)，k=0..N−1。
    实现与 scipy.signal.windows.taylor（norm=False，DC 增益=1）逐权同值，
    再归一化到 max|w| = 1（本模块统一约定，同 chebyshev/binomial）。

    sidelobe_level_db 为负的有限 dB（同 chebyshev_weights 约定）；
    nbar≥1（nbar=1 时 F_m 空 → 均匀加权退化）；nbar>n 直接拒绝（近主瓣
    等纹波副瓣数超过单元数属构造性退化，不给垃圾结果）。
    """
    n = int(n_elements)
    if n < 1:
        raise ValueError(f"n_elements 至少为 1，收到 {n_elements!r}")
    nb = int(nbar)
    if nb < 1:
        raise ValueError(f"nbar 至少为 1，收到 {nbar!r}")
    if nb > n:
        raise ValueError(f"nbar（{nb}）不得超过 n_elements（{n}）")
    sll = float(sidelobe_level_db)
    if not np.isfinite(sll) or sll >= 0.0:
        raise ValueError(f"sidelobe_level_db 必须为负的有限值（dB），收到 {sidelobe_level_db!r}")
    ratio = 10.0 ** (-sll / 20.0)
    if ratio <= 1.0:
        raise ValueError("副瓣电平目标对应的电压比必须 > 1")
    big_a = float(np.arccosh(ratio)) / np.pi
    sigma2 = nb * nb / (big_a * big_a + (nb - 0.5) ** 2)
    ma = np.arange(1, nb, dtype=float)
    fm = np.empty(ma.size, dtype=float)
    for i, m in enumerate(ma):
        sign = 1.0 if i % 2 == 0 else -1.0
        numer = sign * float(np.prod(
            1.0 - m * m / sigma2 / (big_a * big_a + (ma - 0.5) ** 2)))
        others = np.delete(ma * ma, i)
        denom = 2.0 * float(np.prod(1.0 - m * m / others))
        fm[i] = numer / denom
    k = np.arange(n, dtype=float)
    taper = fm @ np.cos(
        2.0 * np.pi * ma[:, np.newaxis] * (k - n / 2.0 + 0.5) / n)
    w = 1.0 + 2.0 * taper
    return w / np.abs(w).max()


# ─── 阵列因子 ──────────────────────────────────────────────────────────────────

def array_factor(
    direction_cosines,
    weights,
    *,
    spacing_lambda: float = 0.5,
    scan_direction_cosine: float = 0.0,
    normalize: bool = True,
) -> np.ndarray:
    """线阵阵列因子 AF(u) = sum_n w_n * exp(j*2*pi*(d/lambda)*(u-u0)*n)。

    参数
    ----
    direction_cosines : 方向余弦 u（标量或任意形状数组）
    weights : 一维单元权重（按几何顺序）
    spacing_lambda : 单元间距 d/lambda
    scan_direction_cosine : 扫描方向余弦 u0（z 轴阵 = cos(theta0)）
    normalize : True 时除以 sum(w)，使侧射峰值（u=u0）为 1

    返回复阵列因子，形状与 direction_cosines 一致。
    """
    w = _validate_weights(weights)
    spacing = _validate_spacing(spacing_lambda)
    u0 = _validate_scan(scan_direction_cosine)
    u = np.asarray(direction_cosines, dtype=float)
    psi = 2.0 * np.pi * spacing * (u - u0)
    phase = np.exp(1j * np.expand_dims(psi, -1) * np.arange(w.size))
    af = phase @ w
    if normalize:
        af = af / float(w.sum())
    return af


def array_factor_angles(
    theta_deg,
    weights,
    *,
    phi_deg=0.0,
    spacing_lambda: float = 0.5,
    scan_deg: float = 90.0,
    scan_phi_deg: float = 0.0,
    axis: str = "z",
    normalize: bool = True,
) -> np.ndarray:
    """角度域的阵列因子：array_factor(direction_cosine(theta, phi), ...)。

    默认 z 轴、扫描角 scan_deg=90°（侧射，u0=0）。
    """
    u = direction_cosine(theta_deg, phi_deg, axis)
    u0 = steering_direction_cosine(scan_deg, scan_phi_deg, axis)
    return array_factor(
        u, weights, spacing_lambda=spacing_lambda, scan_direction_cosine=u0, normalize=normalize
    )


def uniform_af_closed_form(psi, n_elements: int) -> np.ndarray:
    """均匀阵 AF 的解析闭式（归一化幅度）：|sin(N*psi/2)/(N*sin(psi/2))|。

    psi = 2*pi*(d/lambda)*(u-u0)；psi -> 2*pi*m 处取极限 N/N = 1（返回 1）。
    """
    n = int(n_elements)
    if n < 1:
        raise ValueError(f"n_elements 至少为 1，收到 {n_elements!r}")
    psi_arr = np.asarray(psi, dtype=float)
    half = 0.5 * psi_arr
    den = np.sin(half)
    safe_den = np.where(np.abs(den) < _TINY, 1.0, den)
    value = np.where(np.abs(den) < _TINY, float(n), np.sin(n * half) / safe_den)
    return np.abs(value) / n


def peak_sidelobe_level_db(
    magnitude,
    direction_cosines,
    *,
    main_lobe_direction_cosine: float = 0.0,
) -> float:
    """图案的峰值副瓣电平（dB，相对主瓣峰值；主瓣取最靠近给定 u 的局部极大）。

    用于综合验收：Chebyshev 加权后实测副瓣应等于目标 dB。
    """
    mag = np.abs(np.asarray(magnitude, dtype=float))
    u = np.asarray(direction_cosines, dtype=float)
    if mag.shape != u.shape:
        raise ValueError(f"magnitude 与 direction_cosines 形状不一致：{mag.shape} vs {u.shape}")
    if mag.size < 3:
        raise ValueError("至少需要 3 个采样点才能定位副瓣")
    peak = float(mag.max())
    if peak <= 0.0:
        raise ValueError("图案峰值为 0，无法计算副瓣电平")
    interior = np.nonzero((mag[1:-1] >= mag[:-2]) & (mag[1:-1] >= mag[2:]))[0] + 1
    edges = []
    if mag[0] >= mag[1]:
        edges.append(0)
    if mag[-1] >= mag[-2]:
        edges.append(mag.size - 1)
    candidates = np.unique(np.concatenate((np.asarray(edges, dtype=int), interior)))
    main_peak = int(candidates[np.argmin(np.abs(u[candidates] - main_lobe_direction_cosine))])
    sidelobes = candidates[candidates != main_peak]
    if sidelobes.size == 0:
        return float("-inf")
    return 20.0 * np.log10(float(mag[sidelobes].max()) / peak)


# ─── 栅瓣 / 波束宽度 ───────────────────────────────────────────────────────────

def grating_lobe_free_max_spacing(scan_direction_cosine: float = 0.0) -> float:
    """无栅瓣的最大单元间距 d/lambda = 1/(1+|u0|)（可见区 |u|<=1）。

    恰在此间距时首个栅瓣落在 u=±1（可见区边界）；侧射 u0=0 -> 1.0，
    端射 |u0|=1 -> 0.5。
    """
    u0 = _validate_scan(scan_direction_cosine)
    return 1.0 / (1.0 + abs(u0))


def grating_lobe_direction_cosines(
    spacing_lambda: float,
    scan_direction_cosine: float = 0.0,
) -> tuple[float, ...]:
    """可见区内的栅瓣方向余弦（不含主瓣），按升序返回。

    栅瓣位于 u = u0 + m*(lambda/d)，m=±1,±2,...，保留 |u| <= 1 者。
    """
    spacing = _validate_spacing(spacing_lambda)
    u0 = _validate_scan(scan_direction_cosine)
    period = 1.0 / spacing
    max_order = int(np.floor((1.0 + abs(u0)) / period + 1e-9))
    lobes: list[float] = []
    for m in range(1, max_order + 1):
        for sign in (1.0, -1.0):
            u = u0 + sign * m * period
            if abs(u) <= 1.0 + 1e-9:
                lobes.append(float(np.clip(u, -1.0, 1.0)))
    return tuple(sorted(lobes))


def has_grating_lobe(spacing_lambda: float, scan_direction_cosine: float = 0.0) -> bool:
    """可见区内是否存在栅瓣。"""
    return len(grating_lobe_direction_cosines(spacing_lambda, scan_direction_cosine)) > 0


def broadside_hpbw_rad(n_elements: int, spacing_lambda: float = 0.5) -> float:
    """侧射均匀阵半功率波束宽度渐近式（rad）：0.886*lambda/(N*d)。"""
    n = int(n_elements)
    if n < 2:
        raise ValueError(f"n_elements 至少为 2，收到 {n_elements!r}")
    spacing = _validate_spacing(spacing_lambda)
    return 0.886 / (n * spacing)


def broadside_hpbw_deg(n_elements: int, spacing_lambda: float = 0.5) -> float:
    """侧射均匀阵 HPBW（度）。"""
    return float(np.degrees(broadside_hpbw_rad(n_elements, spacing_lambda)))


# ─── 方向图积 / 单元方向图 ─────────────────────────────────────────────────────

def pattern_multiplication(element_pattern, array_factor_values) -> np.ndarray:
    """方向图积定理：F_total = F_element * AF（逐点相乘，numpy 广播）。"""
    element = np.asarray(element_pattern)
    af = np.asarray(array_factor_values)
    try:
        return np.broadcast_arrays(element, af)[0] * af
    except ValueError as exc:  # numpy 广播失败时给中文提示
        raise ValueError(f"单元方向图与阵列因子无法广播：{element.shape} vs {af.shape}") from exc


def half_wave_dipole_field(theta_deg) -> np.ndarray:
    """半波振子 E 面场方向图闭式 cos((pi/2)cos(theta))/sin(theta)。

    端点 theta=0/180 取极限 0，避免除零。
    """
    theta = np.radians(np.asarray(theta_deg, dtype=float))
    sine = np.sin(theta)
    numerator = np.cos(0.5 * np.pi * np.cos(theta))
    safe = np.where(np.abs(sine) < _TINY, 1.0, sine)
    return np.where(np.abs(sine) < _TINY, 0.0, numerator / safe)


_C_MM_GHZ = 299.792458
"""真空光速（mm·GHz），贴片单元闭式的 k0 = 2π f/c。"""

_PATCH_AXES = ("x", "y")


def _sinc(x: np.ndarray) -> np.ndarray:
    """sin(x)/x，x→0 取 1（非 numpy.sinc 的 π 归一化口径）。"""
    safe = np.where(np.abs(x) < _TINY, 1.0, x)
    return np.where(np.abs(x) < _TINY, 1.0, np.sin(safe) / safe)


def patch_element_field(
    theta_deg,
    phi_deg=0.0,
    *,
    len_mm: float,
    width_mm: float,
    freq_ghz: float,
    h_mm: float = 0.508,
    axis: str = "x",
    component: str = "total",
) -> np.ndarray:
    """矩形贴片单元方向图闭式（腔模型双缝，Balanis Ch. 14；归一化天顶=1）。

    模型（理论核验轮 2026-09-15，自行矢量推导并与教科书主平面闭式互证）：
    贴片谐振轴 L 沿 ``axis``（"x" 或 "y"），宽 W 沿另一面内轴，基板厚 h，
    置于 z=0 无限大 PEC 地面上、向 +z 半空间辐射。两条辐射边（x=±L/2，
    以 axis="x" 叙述）的边缘场等效为**同相**磁面流（λ/2 开-开谐振器两端电压
    同时达峰），磁流方向沿 W 轴、面片尺寸 W×h；地面镜像使幅度加倍、仅上
    半空间有场。磁矢位 F ∝ ∫M e^{jk0 r̂·r'}dS' 给出各缝的两个 sinc 因子，
    远场 E ∝ F×r̂ 投影到 (θ̂, φ̂)：

        e_θ = cosφ · Sh · Sw · A2,   e_φ = −cosθ·sinφ · Sh · Sw · A2
        Sh = sinc((k0 h/2)·u_L),  Sw = sinc((k0 W/2)·u_W),  A2 = cos((k0 L/2)·u_L)
        u_L = sinθcosφ（沿 L 轴方向余弦）,  u_W = sinθsinφ（沿 W 轴）

    主平面退化即教科书闭式：E 面（φ=0，含 L 轴）|E| = Sh·cos((k0L/2)sinθ)；
    H 面（φ=90°，含 W 轴）|E| = cosθ·sinc((k0W/2)sinθ)（薄基板 Sh≈1）。
    axis="y" 为坐标旋转 90°（φ→φ−90°）：u_L=sinθsinφ、u_W=sinθcosφ、
    e_θ = sinφ·(...)、e_φ = +cosθcosφ·(...)。

    返回 ``component``="total" 时的 √(e_θ²+e_φ²)（天顶恒为 1，无需再归一化），
    或 "theta"/"phi" 单分量（带符号）。θ 须落在 [−90°, 90°]（地面下无场；
    负 θ 由偶对称等价于 φ+180° 的镜像切面，便于主平面 ±θ 作图）。
    """
    if axis not in _PATCH_AXES:
        raise ValueError(f"axis 必须是 {_PATCH_AXES} 之一，收到 {axis!r}")
    if component not in ("total", "theta", "phi"):
        raise ValueError(f"component 须为 total/theta/phi，收到 {component!r}")
    for label, value in (("len_mm", len_mm), ("width_mm", width_mm),
                         ("freq_ghz", freq_ghz), ("h_mm", h_mm)):
        v = float(value)
        if not np.isfinite(v) or v <= 0.0:
            raise ValueError(f"{label} 必须为正的有限值，收到 {value!r}")
    theta = np.asarray(theta_deg, dtype=float)
    if np.any(np.abs(theta) > 90.0 + 1e-9):
        raise ValueError("θ 须落在 [−90°, 90°]（地面上半空间；地面下无场）")
    th = np.radians(theta)
    ph = np.radians(np.asarray(phi_deg, dtype=float))
    th, ph = np.broadcast_arrays(th, ph)
    k0 = 2.0 * np.pi * float(freq_ghz) / _C_MM_GHZ   # rad/mm
    sin_t, cos_t = np.sin(th), np.cos(th)
    cos_p, sin_p = np.cos(ph), np.sin(ph)
    if axis == "x":
        u_l, u_w = sin_t * cos_p, sin_t * sin_p
        pol_theta, pol_phi = cos_p, -cos_t * sin_p
    else:
        u_l, u_w = sin_t * sin_p, sin_t * cos_p
        pol_theta, pol_phi = sin_p, cos_t * cos_p
    common = (_sinc(0.5 * k0 * float(h_mm) * u_l)
              * _sinc(0.5 * k0 * float(width_mm) * u_w)
              * np.cos(0.5 * k0 * float(len_mm) * u_l))
    e_theta = pol_theta * common
    e_phi = pol_phi * common
    if component == "theta":
        return e_theta
    if component == "phi":
        return e_phi
    return np.sqrt(e_theta ** 2 + e_phi ** 2)


def planar_array_factor(
    theta_deg,
    phi_deg,
    weights_x,
    weights_y,
    *,
    spacing_x_lambda: float = 0.5,
    spacing_y_lambda: float = 0.5,
    scan_u_x: float = 0.0,
    scan_u_y: float = 0.0,
    normalize: bool = True,
) -> np.ndarray:
    """矩形栅格平面阵阵列因子（可分离积，Balanis Ch. 6 §6.10）。

    阵元位于 x-y 平面栅格 (m·d_x, n·d_y)，权重可分离 w_mn = w_x[m]·w_y[n]
    （C2 2×2/矩形阵均匀或逐轴 Chebyshev 加权皆属此类）时
        AF(θ,φ) = AF_x(u)·AF_y(v)，u = sinθcosφ，v = sinθsinφ，
    两个因子各为线阵 array_factor（含各自扫描方向余弦 u0/v0）。normalize=True
    时各因子分别归一化，侧射（u=u0,v=v0）峰值为 1。返回复阵列因子，形状为
    theta/phi 广播后的形状。
    """
    theta = np.asarray(theta_deg, dtype=float)
    phi = np.asarray(phi_deg, dtype=float)
    theta, phi = np.broadcast_arrays(theta, phi)
    u = direction_cosine(theta, phi, "x")
    v = direction_cosine(theta, phi, "y")
    af_x = array_factor(u, weights_x, spacing_lambda=spacing_x_lambda,
                        scan_direction_cosine=scan_u_x, normalize=normalize)
    af_y = array_factor(v, weights_y, spacing_lambda=spacing_y_lambda,
                        scan_direction_cosine=scan_u_y, normalize=normalize)
    return af_x * af_y


def field_db(pattern, *, reference=None, floor_db: float = -60.0) -> np.ndarray:
    """场幅度归一化转 dB，峰值 0 dB，低于 floor_db 者截断（默认 -60 dB）。"""
    mag = np.abs(np.asarray(pattern, dtype=float))
    ref = float(mag.max()) if reference is None else float(reference)
    if not np.isfinite(ref) or ref <= 0.0:
        raise ValueError("参考幅度必须为正的有限值")
    floor = 10.0 ** (float(floor_db) / 20.0)
    return 20.0 * np.log10(np.maximum(mag / ref, floor))


# ─── 综合（给定副瓣电平 -> 加权）──────────────────────────────────────────────

@dataclass(frozen=True)
class ChebyshevDesign:
    """Dolph-Chebyshev 线阵综合结果（确定性闭式）。"""

    n_elements: int
    spacing_lambda: float
    sidelobe_level_db: float
    scan_deg: float
    weights: np.ndarray
    aperture_lambda: float
    broadside_hpbw_deg: float
    grating_lobe_free: bool
    grating_lobes: tuple[float, ...]


def aperture_to_n_elements(aperture_lambda: float, spacing_lambda: float = 0.5) -> int:
    """由口径长度 L/lambda 与间距 d/lambda 求单元数：round(L/d) + 1（>=2）。"""
    aperture = float(aperture_lambda)
    spacing = _validate_spacing(spacing_lambda)
    if not np.isfinite(aperture) or aperture <= 0.0:
        raise ValueError(f"aperture_lambda 必须为正的有限值，收到 {aperture_lambda!r}")
    return max(2, round(aperture / spacing) + 1)


def synthesize_chebyshev(
    n_elements: int,
    sidelobe_level_db: float,
    *,
    spacing_lambda: float = 0.5,
    scan_deg: float = 90.0,
    scan_phi_deg: float = 0.0,
    axis: str = "z",
) -> ChebyshevDesign:
    """给定副瓣电平目标，闭式求 Dolph-Chebyshev 加权并汇总口径指标。

    口径（aperture）= (N-1)*d；同时给出侧射 HPBW 渐近值与可见区栅瓣清单，
    便于综合时判断间距是否满足栅瓣约束。
    """
    n = int(n_elements)
    spacing = _validate_spacing(spacing_lambda)
    weights = chebyshev_weights(n, sidelobe_level_db)
    u0 = steering_direction_cosine(scan_deg, scan_phi_deg, axis)
    lobes = grating_lobe_direction_cosines(spacing, u0)
    return ChebyshevDesign(
        n_elements=n,
        spacing_lambda=spacing,
        sidelobe_level_db=float(sidelobe_level_db),
        scan_deg=float(scan_deg),
        weights=weights,
        aperture_lambda=(n - 1) * spacing,
        broadside_hpbw_deg=broadside_hpbw_deg(n, spacing) if n >= 2 else float("nan"),
        grating_lobe_free=len(lobes) == 0,
        grating_lobes=lobes,
    )


@dataclass(frozen=True)
class TaylorDesign:
    """Taylor n-bar 线阵综合结果（连续线源口径离散采样）。"""

    n_elements: int
    spacing_lambda: float
    sidelobe_level_db: float
    nbar: int
    scan_deg: float
    weights: np.ndarray
    aperture_lambda: float
    broadside_hpbw_deg: float
    grating_lobe_free: bool
    grating_lobes: tuple[float, ...]


def synthesize_taylor(
    n_elements: int,
    sidelobe_level_db: float,
    *,
    nbar: int = 4,
    spacing_lambda: float = 0.5,
    scan_deg: float = 90.0,
    scan_phi_deg: float = 0.0,
    axis: str = "z",
) -> TaylorDesign:
    """给定副瓣电平目标，求 Taylor n-bar 加权并汇总口径指标（同
    synthesize_chebyshev 的汇总口径；HPBW 仍为均匀阵渐近式，Taylor 主瓣
    略宽，展示口径不参与判据）。"""
    n = int(n_elements)
    spacing = _validate_spacing(spacing_lambda)
    weights = taylor_weights(n, sidelobe_level_db, nbar=nbar)
    u0 = steering_direction_cosine(scan_deg, scan_phi_deg, axis)
    lobes = grating_lobe_direction_cosines(spacing, u0)
    return TaylorDesign(
        n_elements=n,
        spacing_lambda=spacing,
        sidelobe_level_db=float(sidelobe_level_db),
        nbar=int(nbar),
        scan_deg=float(scan_deg),
        weights=weights,
        aperture_lambda=(n - 1) * spacing,
        broadside_hpbw_deg=broadside_hpbw_deg(n, spacing) if n >= 2 else float("nan"),
        grating_lobe_free=len(lobes) == 0,
        grating_lobes=lobes,
    )


# ─── 串馈行波阵相位递推（2026-09-26 df7 C10d 加法式扩展，既有 API 逐字节不动）──
# 口径：串馈（series-fed）阵的馈线行波以渐进相位逐元递推——第 n 元激励相位
# φₙ = −n·Δφ，Δφ = 元内反相 (π，λ/2 贴片两辐射边场反相的 C2 相位账，
# openems_templates §10.3 C2 patch_array_series 段同源) + 馈线行波相位 βg·s
# （s=相邻元馈电点间馈线长，βg=2π/λg 导波相位常数）。主波束方向余弦由
# 相位匹配 k0·u0·d = Δφ (mod 2π) 给出（d=元中心距），主分支 m=round(Δφ/2π)
# 保证 s=λg/2（Δφ=2π）时 u0=0 侧射——与 C2 谐振式串馈的相位账连续。
# 本节保持本模块"纯 numpy、量纲无关、零求解器依赖"契约：βg/k0/长度同单位制
# （rad/长度），微带 λg 的 skrf HJ 精算住在模板段（openems_templates），
# 不进入本文件。

def series_feed_progressive_phase(
    link_len: float,
    beta_g: float,
    *,
    element_flip: bool = True,
) -> float:
    """相邻元馈电点间行波渐进相位 Δφ = flip·π + βg·s（wrap 到 (−π, π]）。

    link_len=s：馈线互联长；beta_g：导波相位常数（rad/同长度单位）；
    element_flip：λ/2 贴片两辐射边场反相贡献的 π（C2 相位账；非贴片抽头
    （如直接缝耦合）可关）。
    """
    s = float(link_len)
    bg = float(beta_g)
    if not (np.isfinite(s) and s >= 0.0):
        raise ValueError(f"link_len 须为非负有限值，收到 {link_len!r}")
    if not (np.isfinite(bg) and bg > 0.0):
        raise ValueError(f"beta_g 须为正的有限值，收到 {beta_g!r}")
    delta = (math.pi if element_flip else 0.0) + bg * s
    wrapped = (delta + math.pi) % (2.0 * math.pi) - math.pi
    return float(wrapped if abs(wrapped) > _TINY else 0.0)


def series_feed_beam_direction_cosine(
    element_pitch: float,
    k0: float,
    link_len: float,
    beta_g: float,
    *,
    element_flip: bool = True,
) -> float:
    """串馈阵主波束方向余弦（设计主分支）：

        u0 = (Δφ − 2π·m) / (k0·d)，d = 元中心距、m = round(Δφ/2π)。

    m 取主分支使 s=λg/2 时 u0=0（C2 极限锚）。|u0|>1 时主波束落在可见区外
    （栅瓣域/无可见主瓣），显式 ValueError——设计点无效不静默外推。
    """
    d = float(element_pitch)
    wavenumber = float(k0)
    if not (np.isfinite(d) and d > 0.0):
        raise ValueError(f"element_pitch 须为正的有限值，收到 {element_pitch!r}")
    if not (np.isfinite(wavenumber) and wavenumber > 0.0):
        raise ValueError(f"k0 须为正的有限值，收到 {k0!r}")
    s = float(link_len)
    bg = float(beta_g)
    if not (np.isfinite(s) and s >= 0.0 and np.isfinite(bg) and bg > 0.0):
        raise ValueError("link_len 须非负有限且 beta_g 须正")
    delta_raw = (math.pi if element_flip else 0.0) + bg * s
    m = round(delta_raw / (2.0 * math.pi))
    u0 = (delta_raw - 2.0 * math.pi * m) / (wavenumber * d)
    if abs(u0) > 1.0 + 1e-9:
        raise ValueError(
            f"串馈设计点主波束落在可见区外：u0={u0:.6g}（Δφ={delta_raw:.6g} rad、"
            f"m={m}、k0·d={wavenumber * d:.6g}）——调 s/d 或检查栅瓣")
    return float(min(1.0, max(-1.0, u0)))


def series_feed_excitations(
    n_elements: int,
    element_pitch: float,
    k0: float,
    link_len: float,
    beta_g: float,
    *,
    attenuation_np_per_length: float = 0.0,
    element_flip: bool = True,
) -> np.ndarray:
    """串馈行波阵逐元复激励权重 wₙ = exp(−α·n·d)·exp(−j·n·Δφ_raw)。

    相位递推用**原始（非 wrap）**Δφ_raw = flip·π + βg·s（e^{+jωt} 参考下
    行波延迟为负相移）；幅度为行波一阶衰减（可选）：α=attenuation_np_per_
    length（Np/长度，幅度奈培），α=0 缺省=无损渐进。权重按几何顺序返回、
    w[0]=1（首元参考）；波束指向与 α 无关（幅度锥化不改相位匹配，见
    series_feed_beam_direction_cosine）。与 array_factor/planar_array_factor
    的 weights 入参直接互喂（方向图积定理抽查用 patch_element_field）。
    """
    n = int(n_elements)
    if n < 1:
        raise ValueError(f"n_elements 至少为 1，收到 {n_elements!r}")
    d = float(element_pitch)
    wavenumber = float(k0)
    s = float(link_len)
    bg = float(beta_g)
    alpha = float(attenuation_np_per_length)
    if not (np.isfinite(d) and d > 0.0 and np.isfinite(wavenumber)
            and wavenumber > 0.0):
        raise ValueError("element_pitch/k0 须为正的有限值")
    if not (np.isfinite(s) and s >= 0.0 and np.isfinite(bg) and bg > 0.0):
        raise ValueError("link_len 须非负有限且 beta_g 须正")
    if not (np.isfinite(alpha) and alpha >= 0.0):
        raise ValueError(f"attenuation_np_per_length 须非负有限，收到 {alpha!r}")
    idx = np.arange(n, dtype=float)
    delta_raw = (math.pi if element_flip else 0.0) + bg * s
    taper = np.exp(-alpha * d * idx)
    return taper * np.exp(-1j * delta_raw * idx)


def series_feed_array_factor(
    direction_cosines,
    weights,
    element_pitch: float,
    k0: float,
) -> np.ndarray:
    """串馈阵复权阵列因子 AF(u) = Σₙ wₙ·exp(j·k0·u·n·d)（**复数权重**口径）。

    本模块既有 ``array_factor`` 的 weights 入参经 ``_validate_weights`` 收敛为
    实幅度（复数输入静默丢弃虚部——行波渐进相位恰是虚部，不可经其消费）；
    本函数为串馈复权专用求值（与 array_factor 的复指数核同式，仅不做实化），
    u0=0 侧射基准。lossless 互检：等幅复权（α=0）等价于
    ``array_factor(u, uniform_weights(N), spacing_lambda=d/λ0,
    scan_direction_cosine=Δφ/(k0·d))``——两路径复数逐位一致（单测钉）。
    """
    w = np.asarray(weights, dtype=complex)
    if w.ndim != 1 or w.size < 1:
        raise ValueError(f"weights 须为一维非空数组，收到 shape={w.shape}")
    if not np.all(np.isfinite(w)):
        raise ValueError("weights 含非有限值（nan/inf）")
    d = float(element_pitch)
    wavenumber = float(k0)
    if not (np.isfinite(d) and d > 0.0 and np.isfinite(wavenumber)
            and wavenumber > 0.0):
        raise ValueError("element_pitch/k0 须为正的有限值")
    u = np.asarray(direction_cosines, dtype=float)
    phase = np.exp(1j * np.expand_dims(
        2.0 * np.pi * (wavenumber * d / (2.0 * np.pi)) * u, -1)
        * np.arange(w.size))
    return phase @ w


# ─── 差波束/离散修正综合三法（2026-10-05 Phase3 W3-E，RB-ALG-1 加法式扩展，
# ── 既有 API 逐字节不动）───────────────────────────────────────────────────────
# 口径：单脉冲差波束经典综合（Bayliss 四参数闭式）与和波束离散零点修正
# （Villeneuve）+ Schelkunoff 单位圆零点置放。数值只在确定性内核（纯 numpy，
# 铁律 7）。文献锚（出处逐字）：
# - E. T. Bayliss, "Design of monopulse antenna difference patterns with low
#   sidelobes", Bell Syst. Tech. J. 47(4):623-650, 1968（原文数表）；
#   数表转载复核源 = A. W. Doerry, D. L. Bickel, "Notes on Bayliss Taper for
#   Monopulse Radar", SAND-2025-07335, Sandia National Laboratories, 2025
#   （OSTI 2585548，Table 1 = Bayliss 原文 Fig.4 参数多项式系数转载；
#   #df6-⑬ citation-rot 防御：双源互证——A(30dB)=1.64127 与
#   ξ1(30dB)=2.07086 两处独立验算锚逐位复现，落 test_w3_e_array_synth.py）。
# - A. T. Villeneuve, "Taylor patterns for discrete arrays", IEEE Trans.
#   Antennas Propag. 32(10):1089-1093, 1984（和波束零点离散修正）。
# - S. A. Schelkunoff, "A mathematical theory of linear arrays", Bell Syst.
#   Tech. J. 22(1):80-107, 1943（单位圆零点置放）。
# 差波束约定：2N 元偶数阵、奇对称实权 w=[a_N..a_1, −a_1..−a_N]（broadside
# 深零为差波束定义恒等式）；归一化 max|w|=1 与本模块 chebyshev/taylor 一致。

_BAYLISS_PARAM_POLY: dict[str, tuple[float, float, float, float, float]] = {
    # Bayliss 1968 Fig.4 参数多项式系数（Doerry SAND-2025-07335 Table 1 转载，
    # 双源锚定求值约定 Parameter(S) = Σ_k C_k·(−S)^k，S=正 dB）：
    # 锚1 A(30)=+1.64127、锚2 ξ1(30)=+2.07086（PMC12115648 §Table2 验算值
    # 1.6413/2.0708 逐位复现，test_w3_e_array_synth.py 钉死）。
    "A": (0.30387530, -0.05042922, -0.00027989, -0.00000343, -0.00000002),
    "xi1": (0.98583020, -0.03338850, 0.00014064, 0.00000190, 0.00000001),
    "xi2": (2.00337487, -0.01141548, 0.00041590, 0.00000373, 0.00000001),
    "xi3": (3.00636321, -0.00683394, 0.00029281, 0.00000161, 0.00000000),
    "xi4": (4.00518423, -0.00501795, 0.00021735, 0.00000088, 0.00000000),
}
"""Bayliss 参数（A、设计零点 ξ1..ξ4）对副瓣电平 S 的四次多项式系数。

转录源：Doerry SAND-2025-07335 Table 1（=Bayliss 1968 原文 Fig.4 拟合多项
式）；求值约定 Parameter(S)=Σ C_k·(−S)^k（S 为正 dB）由两处独立验算锚定
（见测试常量）。p0（峰位参数）不参与权向量构造，故不转录。
"""


def _bayliss_parameter(name: str, sidelobe_db_positive: float) -> float:
    c = _BAYLISS_PARAM_POLY[name]
    s = float(sidelobe_db_positive)
    return float(c[0] + c[1] * (-s) + c[2] * s * s + c[3] * (-s) ** 3
                 + c[4] * s ** 4)


def _bayliss_zeros_and_bm(sll_db: float, nbar: int,
                          refine_scale: float = 1.0) -> np.ndarray:
    """Bayliss 孔径 Fourier 系数 B_m（零点=数表零点×σ×refine_scale）。

    零点表（Bayliss 1968；Doerry eq.19）：Z_0=0；Z_n=±ξ_n（n=1..4，移动过的
    设计零点）；Z_n=±√(n²+A²)（n≥5，理想模型自然零点）。基础膨胀因子
    σ=Z_{N+1}/Z_N（Doerry eq.21，Taylor 式边界匹配）；refine_scale 为兑现
    "PSLL 回收=声明电平"门的确定性精化标量（见 bayliss_weights docstring）。
    B_m（Doerry eq.36，(−1)^m 相位按实测形态定案——probe 2026-10-05：无
    (−1)^m 时孔径退化为单调瓣、方向图无等纹波结构）。**B_m 必须随最终零点
    集重算**（零点缩放与 B_m 脱钩会使精化失效，probe_scale2 实证）。
    """
    s = abs(float(sll_db))
    big_a = _bayliss_parameter("A", s)
    xi = [_bayliss_parameter(f"xi{i}", s) for i in range(1, 5)]
    big_n = int(nbar)
    # Z[1..N]：设计零点（n≤4 取 ξ_n，n≥5 取自然零点）；Z[N+1] 为边界匹配点
    zeros = [xi[i - 1] if i <= 4 else math.sqrt(i * i + big_a * big_a)
             for i in range(1, big_n + 1)]
    z_next = (math.sqrt((big_n + 1) ** 2 + big_a * big_a) if big_n + 1 > 4
              else xi[big_n])
    sigma = z_next / zeros[-1]
    zd = np.asarray(zeros, dtype=float) * (sigma * float(refine_scale))
    m = np.arange(big_n, dtype=float)
    u_m = m + 0.5
    numer = np.prod(1.0 - u_m[:, None] ** 2 / zd[None, :] ** 2, axis=1)
    l_idx = np.arange(big_n, dtype=float) + 0.5
    denom = np.array([
        np.prod(1.0 - u_m[i] ** 2 / np.delete(l_idx, i) ** 2)
        for i in range(big_n)])
    b_m = (u_m ** 2) * numer / denom * ((-1.0) ** m)
    return zd, b_m


def difference_pattern_psll_db(weights: np.ndarray,
                               n_points: int = 60001) -> float:
    """差波束 PSLL（dB，相对差主瓣峰）：|AF| 在 u∈(0,1] 的局部峰中，
    距 broadside 零点最近的峰=差主瓣（差波束定义），其余峰取最大。

    直接求值核（与 difference_array_factor 同式）：差波束权和恒为 0，
    不可经 ``array_factor``（其校验拒绝零和权）。
    """
    w = np.asarray(weights, dtype=float)
    u = np.linspace(1e-6, 1.0, n_points)
    phase = np.exp(1j * np.expand_dims(np.pi * u, -1) * np.arange(w.size))
    mag = np.abs(phase @ w)
    idx = np.nonzero((mag[1:-1] >= mag[:-2]) & (mag[1:-1] >= mag[2:]))[0] + 1
    if idx.size < 2:
        raise ValueError("差波束在可见区不足两个瓣（无法定义副瓣），"
                         "增大 n_elements")
    main = float(mag[idx[0]])
    if main <= 0.0:
        raise ValueError("差主瓣峰值为 0")
    return float(20.0 * np.log10(float(mag[idx[1:]].max()) / main))


def difference_array_factor(direction_cosines, weights) -> np.ndarray:
    """差波束阵列因子（直接求值核，**零和权**专用）。

    差波束权向量为奇对称（权和恒为 0），被 ``array_factor`` 的
    ``_validate_weights`` 零和守卫拒绝——本函数为差波束专用求值（与
    ``array_factor`` 复指数核同式：AF(u)=Σ wₙ·exp(jπu·n)，d=λ/2 口径、
    u 为方向余弦、不归一），并校验奇对称性（w[−k]=−w[k]，容差 1e-10）。
    """
    w = np.asarray(weights, dtype=float)
    if w.ndim != 1 or w.size < 2 or w.size % 2 != 0:
        raise ValueError(
            f"差波束权重须为偶数长度一维数组（2N 元），收到 shape={w.shape}")
    if not np.all(np.isfinite(w)):
        raise ValueError("weights 含非有限值（nan/inf）")
    half = w[: w.size // 2]
    if not np.allclose(w[w.size // 2:], -half[::-1], atol=1e-10):
        raise ValueError("差波束权重不满足奇对称 w[-k]=-w[k]")
    u = np.asarray(direction_cosines, dtype=float)
    phase = np.exp(1j * np.expand_dims(np.pi * u, -1) * np.arange(w.size))
    return phase @ w


def bayliss_weights(
    n_elements: int,
    sidelobe_level_db: float,
    *,
    nbar: int | None = None,
) -> np.ndarray:
    """Bayliss 差波束权向量（2N 元偶数阵，奇对称实权，max|w|=1）。

    四参数闭式（Bayliss 1968）：参数 A 与设计零点 ξ1..ξ4 由副瓣电平的四次
    拟合多项式给出（数表内嵌 ``_BAYLISS_PARAM_POLY``，双源验算锚见测试）；
    零点表 Z_0=0、±ξ_n(n≤4)、±√(n²+A²)(n≥5)，膨胀 σ=Z_{N+1}/Z_N，孔径
    Fourier 系数 B_m 按零点乘积式构造，2N 元阵取孔径采样并奇对称化。

    与原文 σ 取法的偏差（如实声明）：原文 σ=Z_{N+1}/Z_N 使**渐近包络**的
    等纹波=设计电平；有限 nbar 的离散实现 PSLL 系统性偏深（nbar=10@−30dB
    实测 −31.2dB，probe 2026-10-05）。为兑现"PSLL 回收=声明电平"的预声明
    门（spec §7.3-1），本实现将**单一膨胀标量**做确定性二分精化（约 40 轮
    一维单调求根，无随机性），使离散方向图实测 PSLL=声明值（±0.05dB 收敛
    带）；零点位置的 Bayliss 数表出处与相对形状不变。

    参数
    ----
    n_elements : 偶数（≥8）；差波束要求奇对称、中心无单元。
    sidelobe_level_db : 负 dB（相对差主瓣峰的副瓣电平声明值）。
    nbar : 等纹波零点对数 N（Bayliss/Doerry 的 N）；None=自动 min(7, n//2)；
      须 4 ≤ nbar ≤ n_elements//2。

    返回
    ----
    长度 n_elements 的一维实数组 [a_N..a_1, −a_1..−a_N]，max|w|=1。
    """
    n = int(n_elements)
    if n < 8 or n % 2 != 0:
        raise ValueError(
            f"n_elements 须为 ≥8 的偶数（差波束奇对称 2N 元阵），收到 {n_elements!r}")
    sll = float(sidelobe_level_db)
    if not np.isfinite(sll) or sll >= 0.0:
        raise ValueError(
            f"sidelobe_level_db 必须为负的有限值（dB），收到 {sidelobe_level_db!r}")
    half = n // 2
    big_n = int(min(7, half)) if nbar is None else int(nbar)
    if big_n < 4 or big_n > half:
        raise ValueError(
            f"nbar 须落在 [4, n_elements//2={half}]，收到 {nbar!r}")
    s = abs(sll)

    def build(scale: float) -> np.ndarray:
        _, b_m = _bayliss_zeros_and_bm(s, big_n, refine_scale=scale)
        j = np.arange(1, half + 1, dtype=float)
        half_w = b_m @ np.sin(
            np.pi * (np.arange(big_n, dtype=float)[:, None] + 0.5)
            * (j[None, :] - 0.5) / half)
        w = np.concatenate([half_w[::-1], -half_w])
        return w / np.abs(w).max()

    # 单调二分：膨胀越大零点越外推、副瓣越深（probe 2026-10-05 实测单调）。
    lo, hi = 0.75, 1.6
    scale = 1.0
    for _ in range(48):
        scale = 0.5 * (lo + hi)
        realized = difference_pattern_psll_db(build(scale))
        if realized > sll:      # 偏浅 -> 零点再外推
            lo = scale
        else:                   # 偏深 -> 零点回拉
            hi = scale
    return build(scale)


def villeneuve_weights(
    n_elements: int,
    sidelobe_level_db: float,
    nbar: int = 4,
) -> np.ndarray:
    """Villeneuve 和波束权向量（Taylor 零点的离散阵精确修正，max|w|=1）。

    口径（Villeneuve 1984）：均匀阵多项式 z^N−1 的零点 ψ_k=2πk/N 成对
    ±ψ_k（偶 N 另有 ψ=π 单零点）；内侧 k=1..nbar−1 对零点按 Taylor 零点
    公式重置：ψ_k = (2π/N)·σ·√(A²+(k−½)²)，A=acosh(R)/π、
    σ=nbar/√(A²+(nbar−½)²)（nbar-th 零点与自然零点边界匹配，k≥nbar 保持
    自然零点）。权向量=阵列多项式 Π(z−z_k) 系数（共轭零点对→实系数），
    归一化 max|w|=1。

    nbar=1 时无内侧重置 → 退化为均匀阵（自然锚，test_w3_e_array_synth
    钉死）。n_elements ≥ 2·nbar（内侧修正零点须落在阵列多项式阶数内）。
    """
    n = int(n_elements)
    if n < 2:
        raise ValueError(f"n_elements 至少为 2，收到 {n_elements!r}")
    nb = int(nbar)
    if nb < 1:
        raise ValueError(f"nbar 至少为 1，收到 {nbar!r}")
    if nb * 2 > n:
        raise ValueError(
            f"nbar（{nb}）须满足 2·nbar ≤ n_elements（{n}）")
    sll = float(sidelobe_level_db)
    if not np.isfinite(sll) or sll >= 0.0:
        raise ValueError(
            f"sidelobe_level_db 必须为负的有限值（dB），收到 {sidelobe_level_db!r}")
    ratio = 10.0 ** (-sll / 20.0)
    big_a = float(np.arccosh(ratio)) / np.pi
    sigma = nb / math.sqrt(big_a * big_a + (nb - 0.5) ** 2)
    n_pairs = (n - 1) // 2
    angles: list[float] = []
    for k in range(1, n_pairs + 1):
        psi = ((2.0 * math.pi / n) * sigma
               * math.sqrt(big_a * big_a + (k - 0.5) ** 2)
               if k < nb else 2.0 * math.pi * k / n)
        if abs(psi) >= math.pi:
            raise ValueError(
                f"设计零点 ψ={psi:.4f} 越出单位圆主区间（nbar/n_elements 过大）")
        angles.append(psi)
    roots = [cmath.exp(1j * psi) for psi in angles]
    roots += [cmath.exp(-1j * psi) for psi in angles]
    if n % 2 == 0:
        roots.append(complex(-1.0, 0.0))     # 偶 N 的 ψ=π 单零点
    coeffs = np.poly(roots)
    w = np.real(coeffs)
    if np.abs(w).max() <= 0.0 or not np.all(np.isfinite(w)):
        raise ValueError("Villeneuve 多项式系数退化（数值溢出），减小 nbar")
    return w / np.abs(w).max()


def schelkunoff_nulls(
    n_elements: int,
    null_positions,
    *,
    spacing_lambda: float = 0.5,
) -> np.ndarray:
    """Schelkunoff 单位圆零点置放：给定 n−1 个零方向，返回权向量。

    口径（Schelkunoff 1943）：阵列多项式 E(z)=Σ w_m z^m 的零点放在单位圆
    z_k=exp(jψ_k) 上，ψ_k=2π·(d/λ)·u_k（u_k 为方向余弦，任意实数、按
    2π wrap 到 (−π,π]；|u_k|>1 的零点为不可见区续延，与多项式恒等式无碍）。
    多项式系数即激励；零点共轭对称（±ψ 成对）时系数为实，否则为复——
    实/复自动判定（max|Im| ≤ 1e-8·max|Re| 取实）。归一化 max|w|=1。

    恒等式锚（test_w3_e_array_synth 钉死）：给全 (n−1) 个均匀阵自然零点
    u_k=k·λ/(N·d)（d=λ/2 时 u_k=2k/N）→ 权向量=uniform（多项式恒等
    z^{N−1}+…+1）；含 u=0 零点 → broadside 深零。
    """
    n = int(n_elements)
    if n < 2:
        raise ValueError(f"n_elements 至少为 2，收到 {n_elements!r}")
    spacing = _validate_spacing(spacing_lambda)
    u = np.asarray(null_positions, dtype=float).ravel()
    if u.size != n - 1:
        raise ValueError(
            f"null_positions 须含 n−1={n - 1} 个零方向，收到 {u.size}")
    if not np.all(np.isfinite(u)):
        raise ValueError("null_positions 含非有限值（nan/inf）")
    psi = 2.0 * math.pi * spacing * u
    psi = (psi + math.pi) % (2.0 * math.pi) - math.pi
    roots = np.exp(1j * psi)
    coeffs = np.poly(roots)
    re_max = float(np.abs(np.real(coeffs)).max())
    if re_max <= 0.0 or not np.all(np.isfinite(coeffs)):
        raise ValueError("Schelkunoff 多项式系数退化（数值溢出）")
    w = (np.real(coeffs) if float(np.abs(np.imag(coeffs)).max())
         <= 1e-8 * re_max else coeffs)
    return w / np.abs(w).max()
