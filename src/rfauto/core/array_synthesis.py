"""阵列综合内核（单元方向图 × 阵列因子）。

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
  AF(θ,φ) = AF_x(u)·AF_y(v)，u = sinθcosφ、v = sinθsinφ（2×2 阵列裁判，
  加法式扩展 planar_array_factor）。
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

验收：对照解析/闭式——均匀阵 AF 闭式、HPBW 公式、栅瓣判据边界、
Chebyshev 副瓣电平达标、方向图积定理；全波小阵对照属后续工作，不在本模块。
"""
from __future__ import annotations

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
    "binomial_weights",
    "broadside_hpbw_deg",
    "broadside_hpbw_rad",
    "chebyshev_weights",
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
    "steering_direction_cosine",
    "synthesize_chebyshev",
    "synthesize_taylor",
    "taylor_weights",
    "uniform_af_closed_form",
    "uniform_weights",
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
    （2×2/矩形阵均匀或逐轴 Chebyshev 加权皆属此类）时
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
