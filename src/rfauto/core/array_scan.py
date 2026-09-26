"""DP-4 P1：阵列扫描/互耦确定性内核（纯函数，零 IO，continuation plan DP-4）。

职责（铁律 7：数值只在确定性内核；本模块 = 纯 numpy 叶子，无业务依赖、
**不进 core/calculators 注册表**——免 #231/#304 注册表消费者连动；本模块的
消费面只有 service/array_service.py 与 tests/unit/test_array_scan.py）：

- active_reflection：有源反射系数 Γ_act,n = Σ_m S_nm·(a_m/a_n)（定义式直译，
  行=观测口 n、列=激励口 m，与 openEMS 单激励装配矩阵（#208 逐列激励）一致）；
- scan_impedance / reflection_from_impedance：Z_scan = Z0·(1+Γ)/(1−Γ) 与逆变换；
- eep_superposition：F(û) = Σₙ aₙ·EEPₙ(û)——EEPₙ 为已积分的单元有源方向图
  （含全局原点位置相位），叠加只做复域加权求和；
- position_phase：EEP 合成的位置相位记账 exp(j·k0·r̂·r_n)（全局原点参考，
  nf2ff 口径）；
- surface_wave_beta：接地板介质基片表面波 TM0/TE1 色散超越方程的
  safeguarded Newton 解（Newton 步出括号即回退二分；方程与推导见函数文档）；
- blind_spot_screen：Floquet 谐波平行波数 k∥ = k0·sinθ + m·2π/dx + n·2π/dy
  与表面波 β_sw 相位匹配（|k∥−β_sw|/k0 < tol）或 |Γ_act|>阈值 打盲点旗
  （DP-4 规格书口径：Pozar & Schaubert 1984 / McGrath 1987）；
- tier_gate：快速档放行门——d≥0.5λ 且 |扫描角−侧射|≤45° 且无栅瓣且弱耦
  （max|S_nm|≤−10dB），超界/强耦强制升级并标 invalid_fast_tier。

约定
====
- S 矩阵行=观测口 n、列=激励口 m（S[n, m]，(N,N) 复方阵）；复激励 a_n 含
  幅度与扫描相位；Γ_act 除以自身口激励 a_n；
- 角度一律度；频率一律 Hz；长度一律 m（spacing_lambda=d/λ 无量纲除外）；
- 本模块只 import array_synthesis（零改动，只读复用其栅瓣判据，DP-4 §3）
  与 numpy。

出处：D. M. Pozar & D. H. Schaubert, "Scan blindness in infinite phased arrays
of printed antennas", Electron. Lett., 1984；D. T. McGrath, 1987（DP-4 规格书
口径）；表面波色散方程推导=接地介质板 TM/TE 边值问题（Balanis, Antenna
Theory 3rd ed. Ch.14 微带表面波节；Pozar, Microwave Engineering 介质板波导节），
本模块函数文档内含逐项推导。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core.array_synthesis import grating_lobe_direction_cosines

__all__ = [
    "C_M_S",
    "active_reflection",
    "blind_spot_screen",
    "eep_superposition",
    "position_phase",
    "reflection_from_impedance",
    "scan_impedance",
    "surface_wave_beta",
    "surface_wave_modes",
    "tier_gate",
]

#: 真空光速（m/s，SI 定义值）
C_M_S = 299792458.0

_TINY = 1e-12

_SURFACE_MODES = ("TM0", "TE1")


# ─── 有源反射 / 扫描阻抗 ─────────────────────────────────────────────────────

def active_reflection(s_matrix, excitations) -> np.ndarray:
    """有源反射系数（定义式直译）：Γ_act,n = Σ_m S_nm·(a_m/a_n)。

    参数
    ----
    s_matrix : (N,N) 复方阵，S[n, m] = 激励口 m → 观测口 n 的 S 参数
        （openEMS 单激励逐列装配的同一约定，#208）。
    excitations : (N,) 复激励（幅度×扫描相位），a_n 不得为零（除法定义）。

    返回 (N,) 复 Γ_act。无耗互易 S（幺正）下，任意激励的功率账由
    Σ|b|²=Σ|a|² 守恒钉住（tests/unit/test_array_scan.py::J2b）。
    """
    s = np.asarray(s_matrix, dtype=complex)
    a = np.asarray(excitations, dtype=complex)
    if s.ndim != 2 or s.shape[0] != s.shape[1]:
        raise ValueError(f"s_matrix 必须是方阵，收到 shape={s.shape}")
    if not np.all(np.isfinite(s.real)) or not np.all(np.isfinite(s.imag)):
        raise ValueError("s_matrix 含非有限值（nan/inf）")
    if a.ndim != 1 or a.size != s.shape[0]:
        raise ValueError(
            f"excitations 必须是一维且长度={s.shape[0]}，收到 shape={a.shape}")
    if not np.all(np.isfinite(a.real)) or not np.all(np.isfinite(a.imag)):
        raise ValueError("excitations 含非有限值（nan/inf）")
    if np.any(np.abs(a) <= _TINY):
        raise ValueError("excitations 存在近零分量（|a_n|≤1e-12），Γ_act 定义式除法不可用")
    return (s @ a) / a


def scan_impedance(gamma, z0: float = 50.0) -> np.ndarray:
    """扫描阻抗 Z_scan = Z0·(1+Γ)/(1−Γ)（逐元素）。

    |1−Γ| ≤ 1e-12（Γ→1，扫描盲点深反射）时元素取复无穷（物理：并联开路），
    服务层负责把非有限值翻译为 JSON None + 退化标记。
    """
    g = np.asarray(gamma, dtype=complex)
    z0f = float(z0)
    if not np.isfinite(z0f) or z0f <= 0.0:
        raise ValueError(f"z0 必须为正的有限值，收到 {z0!r}")
    denom = 1.0 - g
    safe = np.where(np.abs(denom) <= _TINY, 1.0, denom)
    out = z0f * (1.0 + g) / safe
    return np.where(np.abs(denom) <= _TINY, complex(np.inf, 0.0), out)


def reflection_from_impedance(z, z0: float = 50.0) -> np.ndarray:
    """阻抗 → 反射系数 Γ = (Z−Z0)/(Z+Z0)（scan_impedance 的逆变换）。"""
    zz = np.asarray(z, dtype=complex)
    z0f = float(z0)
    if not np.isfinite(z0f) or z0f <= 0.0:
        raise ValueError(f"z0 必须为正的有限值，收到 {z0!r}")
    return (zz - z0f) / (zz + z0f)


# ─── EEP 叠加 / 位置相位 ─────────────────────────────────────────────────────

def eep_superposition(eep_patterns, weights) -> np.ndarray:
    """嵌入单元方向图叠加：F(û) = Σₙ aₙ·EEPₙ(û)（复域加权求和）。

    参数
    ----
    eep_patterns : (N, ...) 复数组，第 n 行为单元 n 的 EEP（同一角网格采样；
        EEP 已含全局原点位置相位——nf2ff 以原点为参考免手工补偿，DP-4 §2c）。
    weights : (N,) 复激励 aₙ（幅度×扫描相位）。

    返回 (...) 复总方向图。无耦极限下 EEP_n = E_elem·位置相位，本函数与
    方向图积定理逐点一致（J3a 位置相位记账钉）。
    """
    eeps = np.asarray(eep_patterns, dtype=complex)
    w = np.asarray(weights, dtype=complex)
    if eeps.ndim < 1 or eeps.shape[0] != w.size:
        raise ValueError(
            f"eep_patterns 首维必须等于权重数 {w.size}，收到 shape={eeps.shape}")
    if not np.all(np.isfinite(eeps.real)) or not np.all(np.isfinite(eeps.imag)):
        raise ValueError("eep_patterns 含非有限值（nan/inf）")
    if not np.all(np.isfinite(w.real)) or not np.all(np.isfinite(w.imag)):
        raise ValueError("weights 含非有限值（nan/inf）")
    return np.tensordot(w, eeps, axes=([0], [0]))


def position_phase(positions_m, theta_deg, phi_deg, freq_hz: float) -> np.ndarray:
    """单元位置相位因子 exp(j·k0·(r̂·r_n))（全局原点参考，返回 (N, ...) 复数组）。

    positions_m : (N,3) 单元位置（m）；theta_deg/phi_deg 任意形状角网格（度）；
    freq_hz 工作频率。r̂ = (sinθcosφ, sinθsinφ, cosθ)。
    与 array_synthesis 的无量纲相位 2π(d/λ)(u−u0)n 是两条独立记账链，
    无耦极限下二者一致（J3a 钉的就是这条等式）。
    """
    pos = np.asarray(positions_m, dtype=float)
    if pos.ndim != 2 or pos.shape[1] != 3:
        raise ValueError(f"positions_m 必须是 (N,3)，收到 shape={pos.shape}")
    if not np.all(np.isfinite(pos)):
        raise ValueError("positions_m 含非有限值")
    freq = float(freq_hz)
    if not np.isfinite(freq) or freq <= 0.0:
        raise ValueError(f"freq_hz 必须为正的有限值，收到 {freq_hz!r}")
    th = np.radians(np.asarray(theta_deg, dtype=float))
    ph = np.radians(np.asarray(phi_deg, dtype=float))
    k0 = 2.0 * np.pi * freq / C_M_S
    st, ct = np.sin(th), np.cos(th)
    cp, sp = np.cos(ph), np.sin(ph)
    rdot = (pos[:, 0][:, None, None] * st[None] * cp[None]
            + pos[:, 1][:, None, None] * st[None] * sp[None]
            + pos[:, 2][:, None, None] * ct[None])
    return np.exp(1j * k0 * rdot)


# ─── 表面波色散（接地板介质基片 TM0/TE1）─────────────────────────────────────
#
# 接地介质板（z=0 PEC，0<z<h 介质 εr，z>h 空气），表面波沿面传播 β>k0：
#   介质内横向波数 k_d = √(εr·k0² − β²)，空气侧衰减常数 α = √(β² − k0²)。
# TE（E_y=A·sin(k_d z)，z=0 处切向 E=0）在 z=h 匹配 E_y/H_x：
#   k_d·cot(k_d·h) = −α ⟺ tan(k_d·h) = −k_d/α。
# TM（H_y=A·cos(k_d z)，z=0 处切向 E_x=∂H_y/∂z=0）匹配 H_y/E_x（(1/ε)∂zH_y）：
#   k_d·tan(k_d·h) = εr·α。
# 归一化 u = k_d·h、R = k0·h·√(εr−1)、v = α·h = √(R²−u²)（无量纲）：
#   TM0: F(u) = u·tan(u) − εr·v = 0，根 ∈ (0, min(R, π/2)]——无截止恒存在；
#   TE1: F(u) = −u·cot(u) − v = 0，根 ∈ [π/2, min(R, π)]——存在当且仅当
#        R > π/2，截止 f_c = c/(4h√(εr−1))。
# 左侧（u·tan u / −u·cot u）在对应区间单调增、右侧（εr·v / v）单调减 → 根唯一；
# 区间端点处 F 有限定号（tan/cot 的浮点值在大幅角处有限，无需奇点邻域摄动）。
# safeguarded Newton（rtsafe 口径）：牛顿步越出括号/导数退化即回退二分，
# 每次函数求值都按符号收缩括号，保证全局收敛。

_TM0 = "TM0"
_TE1 = "TE1"


def _newton_bracketed(func, dfunc, lo: float, hi: float,
                      *, tol: float = 1e-15, max_iter: int = 200) -> float:
    """safeguarded Newton：f(lo)<0<f(hi) 的单调根；牛顿越界/导数退化即二分。"""
    a, b = float(lo), float(hi)
    fa, fb = func(a), func(b)
    if fa > 0.0 or fb < 0.0:
        raise ValueError(f"bracket 未夹住根（f(lo)={fa:.3e}, f(hi)={fb:.3e}）")
    if fa == 0.0:
        return a
    if fb == 0.0:
        return b
    x = 0.5 * (a + b)
    fx = func(x)
    for _ in range(max_iter):
        if fx == 0.0 or (b - a) <= tol * max(1.0, abs(x)):
            break
        df = dfunc(x)
        xn = (0.5 * (a + b) if (df == 0.0 or not np.isfinite(df))
              else x - fx / df)
        if not (a < xn < b) or not np.isfinite(xn):
            xn = 0.5 * (a + b)  # 牛顿步越出括号 → 二分兜底
        fxn = func(xn)
        if fxn > 0.0:
            b = xn
        elif fxn < 0.0:
            a = xn
        else:
            return xn
        x, fx = xn, fxn
    return x


def surface_wave_beta(freq_hz: float, slab_thickness_m: float, eps_r: float,
                      mode: str = _TM0) -> dict[str, Any]:
    """接地板介质基片单一表面波模式的传播常数（safeguarded Newton 解）。

    参数
    ----
    freq_hz : 工作频率（Hz）；slab_thickness_m : 基片厚 h（m）；eps_r : 相对
    介电常数（>1）；mode : "TM0"（无截止恒存在）或 "TE1"（存在当且仅当
    f > f_c = c/(4h√(εr−1))）。

    返回 dict：{mode, exists, beta_rad_per_m, beta_over_k0, alpha_air_rad_per_m,
    kd_slab_rad_per_m, u_kdh, residual, cutoff_hz, k0_rad_per_m}。TE1 低于截止
    时 exists=False 且 beta_rad_per_m=None（如实不虚构，不抛错——调用方按
    存在性筛模式）。导波界：k0 ≤ β ≤ k0·√εr。色散方程推导见模块注释。
    """
    if mode not in _SURFACE_MODES:
        raise ValueError(f"mode 必须是 {_SURFACE_MODES} 之一，收到 {mode!r}")
    freq = float(freq_hz)
    h = float(slab_thickness_m)
    er = float(eps_r)
    if not np.isfinite(freq) or freq <= 0.0:
        raise ValueError(f"freq_hz 必须为正的有限值，收到 {freq_hz!r}")
    if not np.isfinite(h) or h <= 0.0:
        raise ValueError(f"slab_thickness_m 必须为正的有限值，收到 {slab_thickness_m!r}")
    if not np.isfinite(er) or er <= 1.0:
        raise ValueError(f"eps_r 必须 >1（导波需 εr>1），收到 {eps_r!r}")
    k0 = 2.0 * np.pi * freq / C_M_S
    big_r = k0 * h * float(np.sqrt(er - 1.0))
    cutoff_hz = 0.0 if mode == _TM0 else C_M_S / (4.0 * h * float(np.sqrt(er - 1.0)))

    def v_of(u: float) -> float:
        return float(np.sqrt(max(big_r * big_r - u * u, 0.0)))

    if mode == _TM0:
        # F(u)=u·tan u − εr·√(R²−u²)，根 ∈ (0, min(R, π/2)]
        upper = min(big_r, 0.5 * np.pi)
        if not (upper > 0.0):
            raise ValueError("R=k0·h·√(εr−1) 非正，TM0 无解（参数矛盾）")

        def f_res(u: float) -> float:
            return u * np.tan(u) - er * v_of(u)

        def df_res(u: float) -> float:
            v = max(v_of(u), _TINY)
            return float(np.tan(u) + u / np.cos(u) ** 2 + er * u / v)

        u = _newton_bracketed(f_res, df_res, 0.0, upper)
    else:
        # F(u)=−u·cot u − √(R²−u²)，根 ∈ [π/2, min(R, π)]，存在当且仅当 R>π/2
        if big_r <= 0.5 * np.pi:
            return {
                "mode": mode, "exists": False, "beta_rad_per_m": None,
                "beta_over_k0": None, "alpha_air_rad_per_m": None,
                "kd_slab_rad_per_m": None, "u_kdh": None, "residual": None,
                "cutoff_hz": cutoff_hz, "k0_rad_per_m": k0,
            }
        upper = min(big_r, np.pi)

        def f_res(u: float) -> float:
            return -u / np.tan(u) - v_of(u)

        def df_res(u: float) -> float:
            v = max(v_of(u), _TINY)
            s = np.sin(u)
            return float(-1.0 / np.tan(u) + u / (s * s) + u / v)

        u = _newton_bracketed(f_res, df_res, 0.5 * np.pi, upper)

    residual = float(abs(f_res(u)))
    kd = u / h
    beta = float(np.sqrt(max(er * k0 * k0 - kd * kd, 0.0)))
    alpha = float(np.sqrt(max(beta * beta - k0 * k0, 0.0)))
    return {
        "mode": mode,
        "exists": True,
        "beta_rad_per_m": beta,
        "beta_over_k0": beta / k0,
        "alpha_air_rad_per_m": alpha,
        "kd_slab_rad_per_m": kd,
        "u_kdh": float(u),
        "residual": residual,
        "cutoff_hz": cutoff_hz,
        "k0_rad_per_m": k0,
    }


def surface_wave_modes(freq_hz: float, slab_thickness_m: float, eps_r: float,
                       modes: tuple[str, ...] = _SURFACE_MODES) -> list[dict[str, Any]]:
    """逐模式求表面波并只保留存在的（blind_spot_screen 的 β_sw 收集口）。"""
    out = []
    for mode in modes:
        info = surface_wave_beta(freq_hz, slab_thickness_m, eps_r, mode=mode)
        if info["exists"]:
            out.append(info)
    return out


# ─── 盲点筛查 ────────────────────────────────────────────────────────────────

def blind_spot_screen(
    theta_deg,
    phi_deg,
    *,
    freq_hz: float,
    dx_m: float,
    dy_m: float,
    beta_sw_rad_per_m=None,
    slab_eps_r: float | None = None,
    slab_thickness_m: float | None = None,
    surface_modes: tuple[str, ...] = _SURFACE_MODES,
    gamma_act=None,
    tol: float = 0.02,
    gamma_threshold: float = 0.8,
    max_order: int = 2,
) -> dict[str, Any]:
    """相控阵扫描盲点筛查（Floquet 谐波-表面波相位匹配 + 有源反射双准则）。

    判据（DP-4 §2c，Pozar & Schaubert 1984 / McGrath 1987 口径）：
    - 相位匹配：栅格 Floquet 谐波平行波数
        k∥(m,n) = |(k0·sinθ·cosφ + m·2π/dx, k0·sinθ·sinφ + n·2π/dy)|
      （φ=0 时退化为规格书标量式 k0·sinθ + m·2π/dx 的绝对值口径）；
      min_{m,n,mode} |k∥(m,n) − β_sw| / k0 < tol → 打旗；
    - 反射：max_n |Γ_act,n| > gamma_threshold → 打旗。

    beta_sw_rad_per_m：显式 β_sw（标量或序列）优先；否则须给 slab_eps_r+
    slab_thickness_m（内部经 surface_wave_beta 逐模式求解，只留存在模式）；
    两者都缺 → ValueError。gamma_act：None / 标量 / 逐点一维（各扫描角的
    max_n|Γ_act,n|）/ (n_points, n_elem) 二维（自动取逐点最大）。
    返回逐点数组 dict（JSON 友好：全部转 Python 标量/列表）。
    """
    freq = float(freq_hz)
    if not np.isfinite(freq) or freq <= 0.0:
        raise ValueError(f"freq_hz 必须为正的有限值，收到 {freq_hz!r}")
    dx = float(dx_m)
    dy = float(dy_m)
    if dx <= 0.0 or dy <= 0.0 or not (np.isfinite(dx) and np.isfinite(dy)):
        raise ValueError(f"dx_m/dy_m 必须为正的有限值，收到 {dx_m!r}/{dy_m!r}")
    k0 = 2.0 * np.pi * freq / C_M_S

    if beta_sw_rad_per_m is not None:
        betas = np.atleast_1d(np.asarray(beta_sw_rad_per_m, dtype=float))
        beta_labels = [f"beta[{i}]" for i in range(betas.size)]
    elif slab_eps_r is not None and slab_thickness_m is not None:
        infos = surface_wave_modes(freq, slab_thickness_m, slab_eps_r, surface_modes)
        if not infos:
            raise ValueError(
                "给定基片参数下 TM0/TE1 均不存在（εr>1 时 TM0 恒存在——参数矛盾）")
        betas = np.asarray([info["beta_rad_per_m"] for info in infos], dtype=float)
        beta_labels = [str(info["mode"]) for info in infos]
    else:
        raise ValueError("须给 beta_sw_rad_per_m 或 (slab_eps_r, slab_thickness_m) 之一")
    if betas.size == 0:
        raise ValueError("beta_sw_rad_per_m 为空序列")

    th = np.atleast_1d(np.asarray(theta_deg, dtype=float))
    ph = np.atleast_1d(np.asarray(phi_deg, dtype=float))
    th, ph = np.broadcast_arrays(th, ph)
    n_pts = int(th.size)

    if gamma_act is None:
        g = None
    else:
        g = np.asarray(gamma_act, dtype=float)
        if g.ndim == 2:
            g = np.max(np.abs(g), axis=1)
        g = np.abs(g).astype(float).ravel()
        if g.size == 1:
            g = np.full(n_pts, float(g[0]))
        if g.size != n_pts:
            raise ValueError(f"gamma_act 点数 {g.size} 与角度点数 {n_pts} 不一致")

    orders = [int(v) for v in range(-int(max_order), int(max_order) + 1)]
    kx0 = k0 * np.sin(np.radians(th)) * np.cos(np.radians(ph))
    ky0 = k0 * np.sin(np.radians(th)) * np.sin(np.radians(ph))

    dist_min = np.full(n_pts, np.inf)
    best_m = np.zeros(n_pts, dtype=int)
    best_n = np.zeros(n_pts, dtype=int)
    best_mode: list[str] = [""] * n_pts
    for m in orders:
        kx = kx0 + m * 2.0 * np.pi / dx
        for n in orders:
            ky = ky0 + n * 2.0 * np.pi / dy
            kpar = np.hypot(kx, ky)
            for bi in range(betas.size):
                d = np.abs(kpar - betas[bi]) / k0
                upd = d < dist_min
                if np.any(upd):
                    dist_min = np.where(upd, d, dist_min)
                    best_m = np.where(upd, m, best_m)
                    best_n = np.where(upd, n, best_n)
                    best_mode = [beta_labels[bi] if u else lab
                                 for u, lab in zip(upd, best_mode, strict=True)]
    sw_blind = dist_min < float(tol)
    if g is None:
        gamma_max = np.full(n_pts, np.nan)
        gamma_blind = np.zeros(n_pts, dtype=bool)
    else:
        gamma_max = g
        gamma_blind = g > float(gamma_threshold)
    blind = sw_blind | gamma_blind
    blind_by = [
        "+".join(filter(None, (
            "surface_wave" if s else "",
            "gamma" if gm else "",
        )))
        for s, gm in zip(sw_blind, gamma_blind, strict=True)
    ]
    return {
        "theta_deg": th.tolist(),
        "phi_deg": ph.tolist(),
        "k0_rad_per_m": k0,
        "min_dist_over_k0": [float("inf") if not np.isfinite(d) else float(d)
                             for d in dist_min],
        "nearest_order_m": best_m.tolist(),
        "nearest_order_n": best_n.tolist(),
        "nearest_mode": best_mode,
        "betas_used_rad_per_m": betas.tolist(),
        "beta_labels": beta_labels,
        "gamma_act_max": [None if not np.isfinite(v) else float(v)
                          for v in gamma_max],
        "gamma_threshold": float(gamma_threshold),
        "tol_over_k0": float(tol),
        "blind": blind.tolist(),
        "blind_by": blind_by,
        "n_blind": int(np.count_nonzero(blind)),
    }


# ─── 快速档放行门 ────────────────────────────────────────────────────────────

def tier_gate(
    spacing_lambda: float,
    scan_from_broadside_deg: float,
    *,
    u0: float = 0.0,
    coupling_db: float | None = None,
    spacing_min_lambda: float = 0.5,
    scan_max_abs_deg: float = 45.0,
    coupling_limit_db: float = -10.0,
) -> dict[str, Any]:
    """快速档（孤立单元×AF）放行门——超界/强耦强制升级 invalid_fast_tier。

    参数
    ----
    spacing_lambda : d/λ（平面阵传 min(dx,dy)/λ；逐轴栅瓣门在服务层做两次合并）；
    scan_from_broadside_deg : 扫描角偏离侧射的绝对角度（ula z 轴=|θ0−90|，
        x/y 轴=|θ0|，平面阵=|θ0|；约定换算在服务层）；
    u0 : 扫描方向在阵轴上的方向余弦（栅瓣判据用，缺省 0=侧射）；
    coupling_db : max_{n≠m}|S_nm| 的 dB（无 S 数据传 None——不阻断，如实记录
        "unknown"，互耦未知不等于弱耦）。

    放行条件（全满足 → tier="fast"）：
    d/λ ≥ 0.5（密集阵互耦强、快档孤立单元假设失效）；|扫描角| ≤ 45°；可见区
    无栅瓣（array_synthesis.grating_lobe_direction_cosines 先行拦截，DP-4
    §2b）；max|S_nm| ≤ −10dB（给定时）。任一不满足 → tier="coupled" 且
    invalid_fast_tier=True、reasons 逐条可分辨。
    """
    spacing = float(spacing_lambda)
    if not np.isfinite(spacing) or spacing <= 0.0:
        raise ValueError(f"spacing_lambda 必须为正的有限值，收到 {spacing_lambda!r}")
    scan = float(scan_from_broadside_deg)
    if not np.isfinite(scan):
        raise ValueError(
            f"scan_from_broadside_deg 必须有限，收到 {scan_from_broadside_deg!r}")
    u0f = float(np.clip(float(u0), -1.0, 1.0))

    checks: dict[str, Any] = {}
    reasons: list[str] = []

    spacing_ok = spacing >= float(spacing_min_lambda) - 1e-12
    checks["spacing_min_lambda"] = {
        "limit": float(spacing_min_lambda), "value": spacing, "pass": spacing_ok}
    if not spacing_ok:
        reasons.append(
            f"spacing_below_min: d/λ={spacing:.6g} < {spacing_min_lambda:.6g}"
            "（密集阵互耦强，快档孤立单元假设失效）")

    scan_ok = abs(scan) <= float(scan_max_abs_deg) + 1e-12
    checks["scan_max_abs_deg"] = {
        "limit": float(scan_max_abs_deg), "value": scan, "pass": scan_ok}
    if not scan_ok:
        reasons.append(
            f"scan_out_of_range: |θ_scan−broadside|={abs(scan):.4g}° > "
            f"{scan_max_abs_deg:.4g}°")

    lobes = grating_lobe_direction_cosines(spacing, u0f)
    grating_ok = len(lobes) == 0
    checks["grating_lobe_free"] = {
        "u0": u0f, "lobes": list(lobes), "pass": grating_ok}
    if not grating_ok:
        reasons.append(
            f"grating_lobe_in_visible_region: u0={u0f:.4g} 时可见区栅瓣 {list(lobes)}")

    coupling_ok: bool | None
    if coupling_db is None:
        coupling_ok = None
        checks["coupling_db"] = {
            "limit": float(coupling_limit_db), "value": None, "pass": None}
    else:
        cdb = float(coupling_db)
        coupling_ok = cdb <= float(coupling_limit_db) + 1e-12
        checks["coupling_db"] = {
            "limit": float(coupling_limit_db), "value": cdb, "pass": coupling_ok}
        if not coupling_ok:
            reasons.append(
                f"strong_coupling: max|S_nm|={cdb:.2f}dB > {coupling_limit_db:.2f}dB")

    allowed = bool(spacing_ok and scan_ok and grating_ok
                   and (coupling_ok is not False))
    return {
        "tier": "fast" if allowed else "coupled",
        "allowed": allowed,
        "invalid_fast_tier": not allowed,
        "reasons": reasons,
        "checks": checks,
    }

