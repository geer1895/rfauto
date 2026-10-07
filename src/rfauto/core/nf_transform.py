"""平面近场测量 → 远场变换确定性内核（DP-18 C10a）。

职责（铁律 7：数值只在确定性内核；本模块 = 纯 numpy/scipy 叶子，无业务依赖）：
- 平面近场 2D 复场（切向 E_x/E_y @ z=z₀ 均匀栅格）→ 加窗 FFT（Kaiser/Hann/
  none 可选）→ 平面波谱 → 远场方向图 E_θ/E_φ（幅度 dB 归一）；
- .ffs ASCII 逆工程 reader（HFSS 远场导出格式，真实样例逐段审计 #331）；
- SWE（球面波展开）第二口径（MS-6 落地）：出射波 h⁽²⁾ 基 TE/TM 模系数
  最小二乘反演 + 任意半径重构 + 远场渐近 + 一阶探头修正闭式。

物理口径（平面波谱/口径场法，Kerns NBS Monograph 162 口径族，e^{+jωt}）：
- 谱定义 S(kx,ky) = Σ E[m,n]·w[m,n]·e^{+j(kx x_m + ky y_n)}·Δx·Δy
  （Riemann 离散化，加窗抑制有限扫描面的空间截断绕射瓣）；
- 谱坐标 kx = k sinθcosφ，ky = k sinθsinφ，kz = √(k²−kx²−ky²)；
- 横向性 k·E=0 → 谱分量纵向幅度 Sz = −(kx Sx + ky Sy)/kz；
- 远场由平稳相位渐近导出（2026-09-24 开工推导定稿）：谱分量投影
  θ̂·A = cosφSx+sinφSy 除 cosθ，与平稳相位前置因子 ∝ cosθ **恰相消**：
      E_θ(θ,φ) ∝ cosφ·S_x + sinφ·S_y ；E_φ ∝ −sinφ·S_x + cosφ·S_y
  （共同标量 jk·e^{−jkr}/r 与常相位 kz·z₀ 不入幅度图）；
- 有效域 θ < 85°：有限扫描面空间截断→谱高角失真守卫（无 cosθ 奇点，
  截断误差随 θ→90° 增大），越域方向图如实 NaN 不外推；
- 采样要求：Δx、Δy ≤ λ/2.6 量级（谱支撑 |kx|≤π/Δx 须覆盖 k·sinθ_max）。

.ffs reader 审计（#331：先 dump 原文再定列义）：真实样例
pyaedt-main/tests/system/general/example_models/ff_test/test.ffs
（HFSS 76–77 GHz 三频块，2026-09-24 逐段审计）实测结构：
  ``// #Frequencies`` + 块数 N → ``// Radiated/Accepted/Stimulated Power ,
  Frequency`` 后 4×N 行（每频 Radiated/Accepted/Stimulated 功率 + 频率 Hz）
  → 每频块 ``// >> Total #phi samples, total #theta samples``（n_phi n_theta）
  + ``// >> Phi, Theta, Re(E_Theta), Im(E_Theta), Re(E_Phi), Im(E_Phi):``
  + n_phi×n_theta 数据行（phi 外层 0..360、theta 内层 0..180，角度度）。
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import scipy.special as sp

#: reader 版本（格式口径显式标注；真实样例审计来源见模块 docstring）
READER_VERSION = "ffs-ascii-hfss-audit-1"

#: 变换支持窗族（窗作用于两个扫描轴的可分离乘积）
WINDOW_CHOICES = ("kaiser", "hann", "none")

#: 远场有效域上限（度）：扫描面截断误差守卫，越域 NaN
FF_VALIDITY_MAX_DEG = 85.0

#: 真空波速（m/s，与仓内 openEMS 模板同源常数）
C0 = 299792458.0

_FFS_FREQ_HEADER = "// #Frequencies"
_FFS_POWER_HEADER = "// Radiated/Accepted/Stimulated Power"
_FFS_GRID_HEADER = "// >> Total #phi samples"
_FFS_COL_HEADER = "// >> Phi, Theta"


# ─── 平面近场 → 远场变换 ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class NearFieldGrid:
    """平面近场扫描栅格（切向复场，e^{+jωt} 峰值相量）。

    ex/ey 形状 (n_x, n_y)，ex[m,n] = E_x(x_m, y_n, z0)；坐标单位米、频率 Hz。
    """

    x_m: np.ndarray
    y_m: np.ndarray
    freq_hz: float
    ex: np.ndarray
    ey: np.ndarray
    z0_m: float = 0.0


def _window_1d(window: str, n: int, kaiser_beta: float) -> np.ndarray:
    if window == "none":
        return np.ones(n)
    if window == "hann":
        return np.hanning(n)
    if window == "kaiser":
        return np.kaiser(n, float(kaiser_beta))
    raise ValueError(f"window 须为 {WINDOW_CHOICES} 之一，收到 {window!r}")


def _bilinear(F: np.ndarray, ax0: np.ndarray, ax1: np.ndarray,
              q0: np.ndarray, q1: np.ndarray) -> np.ndarray:
    """双线性插值 F[i,j] 于 (ax0, ax1) 规则网格；越界点 NaN（复数保持复）。"""
    out = np.full(q0.shape, np.nan,
                  dtype=complex if np.iscomplexobj(F) else float)
    inside = ((q0 >= ax0[0]) & (q0 <= ax0[-1]) & (q1 >= ax1[0]) & (q1 <= ax1[-1]))
    if not inside.any():
        return out
    i0 = np.clip(np.searchsorted(ax0, q0[inside]) - 1, 0, ax0.size - 2)
    j0 = np.clip(np.searchsorted(ax1, q1[inside]) - 1, 0, ax1.size - 2)
    t0 = (q0[inside] - ax0[i0]) / (ax0[i0 + 1] - ax0[i0])
    t1 = (q1[inside] - ax1[j0]) / (ax1[j0 + 1] - ax1[j0])
    f00 = F[i0, j0]
    f10 = F[i0 + 1, j0]
    f01 = F[i0, j0 + 1]
    f11 = F[i0 + 1, j0 + 1]
    out[inside] = ((1 - t0) * (1 - t1) * f00 + t0 * (1 - t1) * f10
                   + (1 - t0) * t1 * f01 + t0 * t1 * f11)
    return out


def planar_nf_to_farfield(
    grid: NearFieldGrid,
    window: str = "kaiser",
    kaiser_beta: float = 6.0,
    theta_deg: np.ndarray | None = None,
    phi_deg: np.ndarray | None = None,
) -> dict[str, Any]:
    """平面近场 → 远场方向图（确定性，幅度 dB 归一）。

    theta_deg/phi_deg 缺省 = arange(0, 81, 1) / [0, 90, 180, 270]；返回
    (n_theta, n_phi) 网格的复 E_θ/E_φ 与峰值归一 dB 图。θ≥85° 方向如实 NaN；
    谱支撑（Nyquist）覆盖不到的方向（|k sinθ| > π/Δx 等频轴越界）如实 NaN。
    """
    x = np.asarray(grid.x_m, dtype=float)
    y = np.asarray(grid.y_m, dtype=float)
    ex = np.asarray(grid.ex, dtype=complex)
    ey = np.asarray(grid.ey, dtype=complex)
    if ex.shape != (x.size, y.size) or ey.shape != ex.shape:
        raise ValueError(
            f"ex/ey 形状须为 (n_x={x.size}, n_y={y.size})，收到 ex={ex.shape}")
    if x.size < 4 or y.size < 4:
        raise ValueError("扫描栅格每轴至少 4 个采样点（FFT 谱分辨率）")
    dx = float(np.median(np.diff(x)))
    dy = float(np.median(np.diff(y)))
    if dx <= 0 or dy <= 0:
        raise ValueError("扫描坐标须严格升序")

    wx = _window_1d(window, x.size, kaiser_beta)
    wy = _window_1d(window, y.size, kaiser_beta)
    w = wx[:, None] * wy[None, :]

    th = (np.arange(0.0, FF_VALIDITY_MAX_DEG + 0.5, 1.0)
          if theta_deg is None else np.asarray(theta_deg, dtype=float))
    ph = (np.array([0.0, 90.0, 180.0, 270.0])
          if phi_deg is None else np.asarray(phi_deg, dtype=float))
    if th.max() >= FF_VALIDITY_MAX_DEG:
        raise ValueError(
            f"theta 最大 {float(th.max())}° 越出有效域 "
            f"(θ < {FF_VALIDITY_MAX_DEG}°，扫描面截断守卫)")

    k_rad = 2.0 * np.pi * float(grid.freq_hz) / C0
    kx_axis = 2.0 * np.pi * np.fft.fftshift(np.fft.fftfreq(x.size, d=dx))
    ky_axis = 2.0 * np.pi * np.fft.fftshift(np.fft.fftfreq(y.size, d=dy))
    # ifftshift 输入侧：相位参考收敛到孔径中心。缺省 FFT 把线性相位
    # e^{+jkx·x0}（x0=轴起点，常为 −extent）带进谱——Δkx·|x0| 恰 ≈π 时相邻
    # bin 相位反相，复数插值逐点相消（2026-09-24 偶极子回归实测 12-19dB 假
    # 偏差抓出）；幅度图不设窗时同样受 interp 相位翻转之害，必须居中。
    sx = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(ex * w))) * dx * dy
    sy = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(ey * w))) * dx * dy

    th_r = np.deg2rad(th)[:, None]
    ph_r = np.deg2rad(ph)[None, :]
    kx_q = k_rad * np.sin(th_r) * np.cos(ph_r)
    ky_q = k_rad * np.sin(th_r) * np.sin(ph_r)

    spec_x = _bilinear(sx, kx_axis, ky_axis,
                       kx_q.ravel(), ky_q.ravel()).reshape(th.size, ph.size)
    spec_y = _bilinear(sy, kx_axis, ky_axis,
                       kx_q.ravel(), ky_q.ravel()).reshape(th.size, ph.size)
    cos_ph = np.cos(ph_r)
    sin_ph = np.sin(ph_r)
    e_theta = cos_ph * spec_x + sin_ph * spec_y
    e_phi = -sin_ph * spec_x + cos_ph * spec_y

    amp = np.hypot(np.abs(e_theta), np.abs(e_phi))
    peak = float(amp.max()) if amp.size and np.isfinite(amp).any() else 0.0
    pattern_db = (20.0 * np.log10(amp / peak + 1e-300) if peak > 0
                  else np.full(amp.shape, np.nan))
    return {
        "ok": True,
        "method": "planar_pws_fft",
        "window": window,
        "kaiser_beta": float(kaiser_beta) if window == "kaiser" else None,
        "freq_hz": float(grid.freq_hz),
        "z0_m": float(grid.z0_m),
        "theta_deg": th,
        "phi_deg": ph,
        "e_theta": e_theta,
        "e_phi": e_phi,
        "pattern_db": pattern_db,
        "validity_max_deg": FF_VALIDITY_MAX_DEG,
        "scan_span_m": (float(x[-1] - x[0]), float(y[-1] - y[0])),
        "k_rad_per_m": k_rad,
        "note": "幅度口径：|E_θ|²+|E_φ|² 相对峰值归一；θ≥85°/谱支撑外如实 NaN",
    }


def farfield_pattern_db(e_theta: np.ndarray, e_phi: np.ndarray) -> np.ndarray:
    """远场复分量 → 峰值归一 dB 幅度图（独立便捷入口，与变换同口径）。"""
    amp = np.hypot(np.abs(np.asarray(e_theta)), np.abs(np.asarray(e_phi)))
    peak = float(amp.max()) if amp.size else 0.0
    if peak <= 0.0 or not np.isfinite(peak):
        return np.full(amp.shape, np.nan)
    return 20.0 * np.log10(amp / peak + 1e-300)


# ─── SWE 球面波展开（MS-6 落地；出射波 h⁽²⁾ 基 + 一阶探头修正）───────────────
#
# 物理口径（Kerns NBS Monograph 162 / Hansen《Spherical Near-Field Antenna
# Measurements》Ch.2-3 标准矢量球谐展开，e^{+jωt}、出射波 e^{−jkr}）：
#   E_t(r,θ,φ) = Σ_lm [ Q_te,lm·h2_l(kr)·X_lm + Q_tm,lm·Rh2_l(kr)·Z_lm ]
#   h2_l(x)   = j_l(x) − j·y_l(x)（第二类球 Hankel，出射波唯一基）
#   Rh2_l(x)  = d/dx[x·h2_l]/x = h2_{l−1}(x) − (ell/x)·h2_l(x)（同一递推恒等式）
#   X_lm（TE 族切向基）＝（î_θ (jm/sinθ)Y_lm − î_φ ∂_θY_lm）/√(ell(ell+1))
#   Z_lm（TM 族切向基）＝（î_θ ∂_θY_lm + î_φ (jm/sinθ)Y_lm）/√(ell(ell+1))
# 归一化性质（测试以 GL×均匀积分数值钉）：每模 ∫(|Xθ|²+|Xφ|²)dΩ = 1；
#   TE/TM 族与不同 (ell,m) 相互正交——Q 系数与采样球半径无关（出射场）。
# 远场（x→∞ 渐近 h2_l ≈ j^{l+1}e^{−jx}/x）：
#   E_ff(θ,φ) = Σ_lm [ Q_te·j^{l+1}·X_lm + Q_tm·j^{l+2}·Z_lm ]
#   （e^{−jkr}/r 全局因子不入方向图；j=√−1。TE/TM 相对相位由渐近式定，
#   数值锚 = 大 kr 近场 × kr·e^{jkr} 收敛到同式，测试钉）。
# ∂_θY_lm 不用数值差分，用连带 Legendre 恒等式闭式：
#   ∂_θY_lm = cs·N_lm·[l·u·P_l^m − (ell+m)·P_{l−1}^m]/sinθ · e^{jmφ}，
#   u=cosθ、P 含 Condon–Shortley 相位（scipy lpmv 同约定），P_{m−1}^m≡0；
#   负阶 Y_{ell,−m}=(−1)^m·conj(Y_{ell,m})。极点 sinθ=0 处基奇异 → 显式拒绝。

_SQRT = math.sqrt


def _ylm(ell: int, m: int, theta_rad: np.ndarray, phi_rad: np.ndarray) -> np.ndarray:
    """标量球谐 Y_lm（Condon–Shortley 约定，正 m 与 scipy.special 一致）。"""
    mm = abs(m)
    u = np.cos(theta_rad)
    norm = _SQRT((2 * ell + 1) / (4.0 * math.pi)
                 * math.factorial(ell - mm) / math.factorial(ell + mm))
    base = ((-1.0) ** mm) * norm * sp.lpmv(mm, ell, u)
    if m >= 0:
        return base * np.exp(1j * m * phi_rad)
    return ((-1.0) ** mm) * np.conj(base) * np.exp(1j * m * phi_rad)


def _dylm_theta(ell: int, m: int, theta_rad: np.ndarray,
                phi_rad: np.ndarray) -> np.ndarray:
    """∂_θY_lm 闭式（恒等式见上；与数值差分 ≤1e-9 一致，测试钉）。"""
    mm = abs(m)
    u = np.cos(theta_rad)
    norm = _SQRT((2 * ell + 1) / (4.0 * math.pi)
                 * math.factorial(ell - mm) / math.factorial(ell + mm))
    p_prev = sp.lpmv(mm, ell - 1, u) if ell - 1 >= mm else 0.0
    dp_dtheta = (ell * u * sp.lpmv(mm, ell, u) - (ell + mm) * p_prev) / np.sin(theta_rad)
    base = ((-1.0) ** mm) * norm * dp_dtheta
    if m >= 0:
        return base * np.exp(1j * m * phi_rad)
    return ((-1.0) ** mm) * np.conj(base) * np.exp(1j * m * phi_rad)


def _swe_mode_list(l_max: int) -> tuple[np.ndarray, np.ndarray]:
    """模序（ell,m)：l=1..l_max、m=−l..l（l=0 无切向场，不进基）。"""
    ls: list[int] = []
    ms: list[int] = []
    for ell in range(1, l_max + 1):
        for m in range(-ell, ell + 1):
            ls.append(ell)
            ms.append(m)
    return np.asarray(ls), np.asarray(ms)


def _swe_tangential_basis(mode_l: np.ndarray, mode_m: np.ndarray,
                          theta_rad: np.ndarray,
                          phi_rad: np.ndarray) -> dict[str, np.ndarray]:
    """切向基 (n_s, n_modes) 四件：Xθ/Xφ/Zθ/Zφ（1/√(ell(ell+1)) 归一）。"""
    n_s = theta_rad.size
    n_m = mode_l.size
    out = {k: np.empty((n_s, n_m), dtype=complex)
           for k in ("x_theta", "x_phi", "z_theta", "z_phi")}
    sin_t = np.sin(theta_rad)
    for k_i, (ell, m) in enumerate(zip(mode_l.tolist(), mode_m.tolist(), strict=True)):
        root = math.sqrt(ell * (ell + 1))
        y = _ylm(ell, m, theta_rad, phi_rad)
        dy = _dylm_theta(ell, m, theta_rad, phi_rad)
        im_over_sin = (1j * m / sin_t) * y
        out["x_theta"][:, k_i] = im_over_sin / root
        out["x_phi"][:, k_i] = -dy / root
        out["z_theta"][:, k_i] = dy / root
        out["z_phi"][:, k_i] = im_over_sin / root
    return out


def _resolve_k_rad(freq_hz: float | None, k_rad_m: float | None) -> float:
    """freq_hz / k_rad_m 二选一（恰给其一），返回波数 rad/m。"""
    given = [v for v in (freq_hz, k_rad_m) if v is not None]
    if len(given) != 1:
        raise ValueError(
            "freq_hz 与 k_rad_m 恰须给其一（球面径向函数 h2_l(kr) 需要波数）")
    if freq_hz is not None:
        f = float(freq_hz)
        if f <= 0.0:
            raise ValueError(f"freq_hz 必须为正，实际 {f}")
        return 2.0 * math.pi * f / C0
    k_val = float(k_rad_m)  # type: ignore[arg-type]
    if k_val <= 0.0:
        raise ValueError(f"k_rad_m 必须为正，实际 {k_val}")
    return k_val


def _swe_radials(mode_l: np.ndarray, k_r: float) -> tuple[np.ndarray, np.ndarray]:
    """每模径向函数 (h2_l(kr), Rh2_l(kr))（kr 需 ≳ l_max 保证数值良态）。"""
    h2 = np.empty(mode_l.size, dtype=complex)
    rh2 = np.empty(mode_l.size, dtype=complex)
    for k_i, ell in enumerate(mode_l.tolist()):
        h2l = sp.spherical_jn(ell, k_r) - 1j * sp.spherical_yn(ell, k_r)
        h2_prev = (sp.spherical_jn(ell - 1, k_r) - 1j * sp.spherical_yn(ell - 1, k_r))
        h2[k_i] = h2l
        rh2[k_i] = h2_prev - (ell / k_r) * h2l
    return h2, rh2


def _swe_normalize_grid(
    theta_deg: np.ndarray, phi_deg: np.ndarray,
    e_theta: np.ndarray, e_phi: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, tuple[int, ...]]:
    """SWE 入参归一：网格（1-D 轴 × (nθ,nφ) 场）或逐点同形两种形态。

    Returns:
        (theta_deg_flat, phi_deg_flat, e_theta_flat, e_phi_flat, out_shape)
        —— flat 侧供基评估，out_shape 供输出重塑。
    """
    th = np.asarray(theta_deg, dtype=float)
    ph = np.asarray(phi_deg, dtype=float)
    et = np.asarray(e_theta, dtype=complex)
    ep = np.asarray(e_phi, dtype=complex)
    if th.ndim == 1 and ph.ndim == 1 and et.ndim == 2:
        expected = (th.size, ph.size)
        if et.shape != expected or ep.shape != expected:
            raise ValueError(
                f"网格场形状须为 (n_theta={th.size}, n_phi={ph.size})，得到 "
                f"{et.shape}/{ep.shape}")
        th_g, ph_g = np.meshgrid(th, ph, indexing="ij")
        return (th_g.ravel(), ph_g.ravel(), et.ravel(), ep.ravel(),
                (int(th.size), int(ph.size)))
    if not (th.shape == ph.shape == et.shape == ep.shape):
        raise ValueError(
            f"e_theta/e_phi/theta_deg/phi_deg 形状须一致（或场为 "
            f"(n_theta,n_phi) 网格配 1-D 轴），得到 {et.shape}/{ep.shape}/"
            f"{th.shape}/{ph.shape}")
    return th.ravel(), ph.ravel(), et.ravel(), ep.ravel(), th.shape


def spherical_wave_expansion(
    e_theta: np.ndarray,
    e_phi: np.ndarray,
    theta_deg: np.ndarray,
    phi_deg: np.ndarray,
    l_max: int,
    r_ref_m: float = 1.0,
    *,
    freq_hz: float | None = None,
    k_rad_m: float | None = None,
    h_theta: np.ndarray | None = None,
    h_phi: np.ndarray | None = None,
    eta_ohm: float = 376.730313668,
) -> dict[str, Any]:
    """球面采样复场 → 球面波模系数（TE/TM 出射波展开，MS-6 落地）。

    预声明契约（原占位签名保留，频率/H 场经 keyword 补入）：球面采样复场
    (n_theta, n_phi) 网格（θ 0..180 开区间、φ 覆盖 360°，轴向量外积语义）
    或与轴同形的逐点采样 → TE/TM 模系数（l=1..l_max、m=−l..l，每模各一
    复系数）+ 残差与谱能量审计。重构/远场/半径换算用
    :func:`swe_synthesize_nearfield` / :func:`swe_far_field`。

    物理口径见本节 docstring：出射波 h⁽²⁾ 基，系数与采样球半径无关
    （无源区）；一阶探头修正入口 :func:`first_order_probe_correction`。

    TE/TM 可分性（预声明，#118 审计结论）：**单球面纯切向 E 数据不足以
    唯一分离 TE/TM**——{X_lm} 与 {Z_lm} 各自都是切向场空间的完备正交基，
    E-only 反演欠定（非辐射"对偶电流"零空间）。唯一化两条路：
    - ``h_theta``/``h_phi`` 同时给入（Kerns E+H 四分量拟合，物理唯一，
      ``te_tm_split="kerns_eh"``）——推荐路径；
    - 缺省 E-only 最小范数解（``te_tm_split="e_only_min_norm"``）：
      场级重构/远场仍良定，但系数级 TE/TM 分配是约定产物，测试只钉
      场级往返不钉系数。

    Maxwell 自洽的 H 合成入口 :func:`swe_synthesize_magnetic`（出射波
    ∇×E=−jωμH 闭式，远场辐射条件 r̂×E 数值验证过，测试钉）。

    Args:
        e_theta/e_phi: 切向复 E。(n_theta, n_phi) 网格（配 1-D 轴向量，
            SNEA 惯例）或与 theta_deg/phi_deg 同形的逐点采样均可。
        h_theta/h_phi: 切向复 H（可选，Kerns 唯一化；与 E 同形，单位 A/m）。
        eta_ohm: 波阻抗 [Ω]（仅 H 路径用量纲配平）。
        theta_deg/phi_deg: 采样角（度）。θ 不许含 0/180 极点（基奇异显式拒）。
        l_max: 最高模阶（≥1）。
        r_ref_m: 采样球半径 [m]（与 freq_hz 或 k_rad_m 联合定 kr）。
        freq_hz / k_rad_m: 恰给其一。

    Returns:
        dict(ok, l_max, n_modes, mode_l, mode_m, a_te, b_tm, k_rad_m,
        r_ref_m, kr, residual_rms, energy_per_l, energy_total, n_samples,
        theta_deg, phi_deg, e_theta_fit, te_tm_split)
    """
    th, ph, et, ep, out_shape = _swe_normalize_grid(
        theta_deg, phi_deg, e_theta, e_phi)
    use_h = (h_theta is not None) or (h_phi is not None)
    if use_h and (h_theta is None or h_phi is None):
        raise ValueError("h_theta/h_phi 必须同时给入（Kerns E+H 四分量）")
    if use_h:
        _, _, ht, hp, hs = _swe_normalize_grid(theta_deg, phi_deg,
                                               h_theta, h_phi)
        if hs != out_shape:
            raise ValueError("H 场与 E 场网格形态不一致")
    if int(l_max) < 1:
        raise ValueError(f"l_max 须 ≥1，实际 {l_max}")
    r_ref = float(r_ref_m)
    if r_ref <= 0.0:
        raise ValueError(f"r_ref_m 必须为正，实际 {r_ref}")
    if th.min() <= 0.0 or th.max() >= 180.0:
        raise ValueError(
            "theta_deg 必须严格在开区间 (0°,180°)（极点 sinθ=0 处 "
            "m/sinθ 基奇异，SWE 采样惯例避开极点）")

    k_val = _resolve_k_rad(freq_hz, k_rad_m)
    kr = k_val * r_ref
    if kr < 0.5 * int(l_max):
        raise ValueError(
            f"kr={kr:.3f} ≲ l_max/2={0.5 * int(l_max)}：采样球过近，径向函数"
            "病态（出射场展开要求采样球在辐射区，惯例 kr ≳ l_max）")

    th_flat = np.deg2rad(th).ravel()
    ph_flat = np.deg2rad(ph).ravel()
    mode_l, mode_m = _swe_mode_list(int(l_max))
    basis = _swe_tangential_basis(mode_l, mode_m, th_flat, ph_flat)
    h2, rh2 = _swe_radials(mode_l, kr)

    n_m = mode_l.size
    # 列块：Q_te → [h2·X；E 行]、Q_tm → [rh2·Z；E 行]；H 行（η 配平）
    # H|TE = (j/η)·rh2·Z、H|TM = (j/η)·h2·X（∇×E=−jωμH；rhs 已 ×η，
    # 设计 H 行只 ×j——再乘 η 会双重计入波阻抗，残差 O(η)（实测钉）
    eta = float(eta_ohm)
    if eta <= 0.0:
        raise ValueError(f"eta_ohm 必须为正，实际 {eta}")
    e_blocks_te = [basis["x_theta"] * h2[None, :],
                   basis["x_phi"] * h2[None, :]]
    e_blocks_tm = [basis["z_theta"] * rh2[None, :],
                   basis["z_phi"] * rh2[None, :]]
    rows_te = list(e_blocks_te)
    rows_tm = list(e_blocks_tm)
    rhs_parts = [et.ravel(), ep.ravel()]
    if use_h:
        rows_te += [basis["z_theta"] * rh2[None, :] * 1j,
                    basis["z_phi"] * rh2[None, :] * 1j]
        rows_tm += [basis["x_theta"] * h2[None, :] * 1j,
                    basis["x_phi"] * h2[None, :] * 1j]
        rhs_parts += [ht.ravel() * eta, hp.ravel() * eta]
    design = np.hstack([np.vstack(rows_te), np.vstack(rows_tm)])
    rhs = np.concatenate(rhs_parts)
    coeffs, *_ , _sv, _cond = np.linalg.lstsq(design, rhs, rcond=None)
    a_te = coeffs[:n_m]
    b_tm = coeffs[n_m:]

    fit = design @ coeffs
    resid = float(np.sqrt(np.mean(np.abs(fit - rhs) ** 2))
                  / max(np.sqrt(np.mean(np.abs(rhs) ** 2)), 1e-300))
    energy_per_l = np.asarray(
        [float(np.sum(np.abs(a_te[mode_l == ell]) ** 2)
               + np.sum(np.abs(b_tm[mode_l == ell]) ** 2))
         for ell in range(1, int(l_max) + 1)])
    return {
        "ok": True,
        "method": "swe_outgoing_h2_lstsq",
        "te_tm_split": "kerns_eh" if use_h else "e_only_min_norm",
        "l_max": int(l_max),
        "n_modes": int(n_m),
        "mode_l": mode_l,
        "mode_m": mode_m,
        "a_te": a_te,
        "b_tm": b_tm,
        "k_rad_m": k_val,
        "r_ref_m": r_ref,
        "kr": float(kr),
        "residual_rms": resid,
        "energy_per_l": energy_per_l,
        "energy_total": float(energy_per_l.sum()),
        "n_samples": int(th_flat.size),
        "theta_deg": th,
        "phi_deg": ph,
        "e_theta_fit": fit[:et.size].reshape(out_shape),
    }


def _swe_pack_basis(swe: dict[str, Any], theta_deg: np.ndarray,
                    phi_deg: np.ndarray) -> tuple[dict[str, np.ndarray],
                                                  np.ndarray, np.ndarray,
                                                  tuple[int, ...]]:
    """展开结果 + 目标角 → 切向基、模表与输出形状（合成/远场共用）。

    1-D 轴向量 → 网格语义（输出 (n_theta, n_phi)）；同形采样 → 同形输出。
    """
    mode_l = np.asarray(swe["mode_l"])
    mode_m = np.asarray(swe["mode_m"])
    th = np.asarray(theta_deg, dtype=float)
    ph = np.asarray(phi_deg, dtype=float)
    if th.ndim == 1 and ph.ndim == 1:
        th_g, ph_g = np.meshgrid(th, ph, indexing="ij")
        out_shape = (int(th.size), int(ph.size))
    else:
        if th.shape != ph.shape:
            raise ValueError(
                f"theta_deg/phi_deg 形状须一致，得到 {th.shape}/{ph.shape}")
        th_g, ph_g = th, ph
        out_shape = th.shape
    basis = _swe_tangential_basis(mode_l, mode_m,
                                  np.deg2rad(th_g).ravel(),
                                  np.deg2rad(ph_g).ravel())
    return basis, mode_l, mode_m, out_shape


def swe_synthesize_nearfield(
    swe: dict[str, Any],
    theta_deg: np.ndarray,
    phi_deg: np.ndarray,
    r_ref_m: float | None = None,
) -> dict[str, np.ndarray]:
    """模系数 → 任意半径球面切向场重构（径向函数换半径即近场外推）。"""
    r_ref = float(swe["r_ref_m"] if r_ref_m is None else r_ref_m)
    if r_ref <= 0.0:
        raise ValueError(f"r_ref_m 必须为正，实际 {r_ref}")
    kr = float(swe["k_rad_m"]) * r_ref
    basis, mode_l, _mode_m, out_shape = _swe_pack_basis(swe, theta_deg, phi_deg)
    h2, rh2 = _swe_radials(mode_l, kr)
    a_te = np.asarray(swe["a_te"])
    b_tm = np.asarray(swe["b_tm"])
    e_theta = (basis["x_theta"] @ (h2 * a_te)
               + basis["z_theta"] @ (rh2 * b_tm))
    e_phi = (basis["x_phi"] @ (h2 * a_te)
             + basis["z_phi"] @ (rh2 * b_tm))
    return {"e_theta": e_theta.reshape(out_shape),
            "e_phi": e_phi.reshape(out_shape), "kr": float(kr)}


def swe_synthesize_magnetic(
    swe: dict[str, Any],
    theta_deg: np.ndarray,
    phi_deg: np.ndarray,
    r_ref_m: float | None = None,
    eta_ohm: float = 376.730313668,
) -> dict[str, np.ndarray]:
    """模系数 → 球面切向 H 场（∇×E=−jωμH 闭式；供 Kerns E+H 拟合语料）。

    模式关系：TE 模 E∝h2·X、H∝(j/η)·rh2·Z；TM 模 E∝rh2·Z、
    H∝(j/η)·h2·X。远场极限下自动满足辐射条件 H=(1/η)r̂×E（数值验证，
    测试钉：H_ff_θ=−E_ff_φ/η、H_ff_φ=E_ff_θ/η）。
    """
    r_ref = float(swe["r_ref_m"] if r_ref_m is None else r_ref_m)
    if r_ref <= 0.0:
        raise ValueError(f"r_ref_m 必须为正，实际 {r_ref}")
    eta = float(eta_ohm)
    if eta <= 0.0:
        raise ValueError(f"eta_ohm 必须为正，实际 {eta}")
    kr = float(swe["k_rad_m"]) * r_ref
    basis, mode_l, _mode_m, out_shape = _swe_pack_basis(swe, theta_deg, phi_deg)
    h2, rh2 = _swe_radials(mode_l, kr)
    a_te = np.asarray(swe["a_te"])
    b_tm = np.asarray(swe["b_tm"])
    h_theta = (basis["z_theta"] @ (rh2 * a_te)
               + basis["x_theta"] @ (h2 * b_tm)) * (1j / eta)
    h_phi = (basis["z_phi"] @ (rh2 * a_te)
             + basis["x_phi"] @ (h2 * b_tm)) * (1j / eta)
    return {"h_theta": h_theta.reshape(out_shape),
            "h_phi": h_phi.reshape(out_shape), "kr": float(kr)}


def swe_far_field(swe: dict[str, Any], theta_deg: np.ndarray,
                  phi_deg: np.ndarray) -> dict[str, np.ndarray]:
    """模系数 → 远场方向图（渐近式 E_ff = Σ Q_te·j^{l+1}X + Q_tm·j^{l+2}Z）。

    全局因子 e^{−jkr}/r 不含（幅度口径 = 出射渐近幅度；TE/TM 相对相位
    由渐近式固定，收敛性由测试以大 kr 近场外推对照钉）。
    """
    basis, mode_l, _mode_m, out_shape = _swe_pack_basis(swe, theta_deg, phi_deg)
    a_te = np.asarray(swe["a_te"])
    b_tm = np.asarray(swe["b_tm"])
    jl_factor = 1j ** (mode_l + 1)
    # d/dx[x·h2_l] = −j^{l+2}e^{−jx}（导数负号；数值验证：修前单模近场/远场
    # 比 TM→−1、TE→+1，修后全 +1，测试钉渐近收敛）
    jm_factor = -(1j ** (mode_l + 2))
    e_theta = basis["x_theta"] @ (jl_factor * a_te) \
        + basis["z_theta"] @ (jm_factor * b_tm)
    e_phi = basis["x_phi"] @ (jl_factor * a_te) \
        + basis["z_phi"] @ (jm_factor * b_tm)
    return {"e_theta": e_theta.reshape(out_shape),
            "e_phi": e_phi.reshape(out_shape)}


def _probe_weight(theta_deg: np.ndarray, probe_q: float,
                  like_shape: tuple[int, ...]) -> np.ndarray:
    """探头权重 c(θ)=cos^qθ；1-D θ 轴 × 2-D 场时按 (nθ,1) 广播到场形。"""
    th = np.asarray(theta_deg, dtype=float)
    c = np.cos(np.deg2rad(th)) ** float(probe_q)
    if th.ndim == 1 and len(like_shape) == 2:
        if like_shape[0] != th.size:
            raise ValueError(
                f"场第一维 {like_shape[0]} 与 theta 轴长度 {th.size} 不一致")
        c = c[:, None]
    return np.broadcast_to(c, like_shape)


def first_order_probe_response(
    e_theta: np.ndarray,
    e_phi: np.ndarray,
    theta_deg: np.ndarray,
    probe_q: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """一阶轴向对称探头的双正交取向响应（正模型，供修正的往返验证）。

    探头相对电压方向图 c(θ)=cos^q(θ)（q=1 典型矩形喇叭口径）：0° 取向测
    c(θ)·E_θ，90° 取向测 c(θ)·E_φ（极化旋转正交分解，一阶口径不含探头
    自身高阶球模——Wacker/Appel-Hansen 一阶修正的闭式核心）。
    """
    q = float(probe_q)
    if q < 0.0:
        raise ValueError(f"probe_q 必须非负，实际 {q}")
    et = np.asarray(e_theta)
    ep = np.asarray(e_phi)
    c = _probe_weight(theta_deg, q, et.shape)
    return c * et, c * ep


def first_order_probe_correction(
    e_probe_chi0: np.ndarray,
    e_probe_chi90: np.ndarray,
    theta_deg: np.ndarray,
    *,
    probe_q: float = 1.0,
    floor: float = 0.1,
) -> dict[str, Any]:
    """一阶探头修正（闭式）：双取向响应 ÷ 探头方向图 → E_θ/E_φ。

    判据（预声明）：c(θ)=cos^qθ 低于 ``floor``（缺省 0.1，q=1 时 θ≳84°）
    的掠射角区探头不敏感，修正值如实 NaN + 计数（不外推不夹持）。
    """
    q = float(probe_q)
    if q < 0.0:
        raise ValueError(f"probe_q 必须非负，实际 {q}")
    fl = float(floor)
    if not 0.0 < fl <= 1.0:
        raise ValueError(f"floor 须在 (0,1]，实际 {fl}")
    e0 = np.asarray(e_probe_chi0)
    e90 = np.asarray(e_probe_chi90)
    if e0.shape != e90.shape:
        raise ValueError(
            f"双取向响应形状须一致，得到 {e0.shape}/{e90.shape}")
    c = _probe_weight(theta_deg, q, e0.shape)
    valid = c >= fl
    e_theta = np.where(valid, e0 / np.where(valid, c, 1.0), np.nan + 0j)
    e_phi = np.where(valid, e90 / np.where(valid, c, 1.0), np.nan + 0j)
    n_tot = int(c.size)
    return {
        "ok": True,
        "e_theta": e_theta,
        "e_phi": e_phi,
        "probe_q": q,
        "floor": fl,
        "invalid_fraction": float((~valid).sum() / max(n_tot, 1)),
        "valid_mask": valid,
    }


# ─── .ffs ASCII 逆工程 reader（真实样例审计口径） ─────────────────────────────

def _ffs_data_block(lines: list[str], start: int, n_rows: int) -> np.ndarray:
    """从 start 行起收集 n_rows 个数据行 → (n_rows, 6) float。"""
    rows: list[str] = []
    i = start
    while i < len(lines) and len(rows) < n_rows:
        s = lines[i].strip()
        if s and not s.startswith("//"):
            rows.append(s)
        i += 1
    if len(rows) != n_rows:
        raise ValueError(
            f".ffs 数据行不足：期望 {n_rows} 行，实际 {len(rows)}（结构损坏）")
    try:
        block = np.loadtxt(io.StringIO("\n".join(rows)), dtype=float, ndmin=2)
    except ValueError as exc:
        raise ValueError(f".ffs 数据行解析失败：{exc}") from exc
    if block.shape != (n_rows, 6):
        raise ValueError(
            f".ffs 数据行列数异常：期望 (n_rows={n_rows}, 6)，收到 {block.shape}")
    return block


def _ffs_next_value(lines: list[str], start: int) -> tuple[str, int]:
    """start 起下一个非空非注释行 → (行文本, 行号)。"""
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if s and not s.startswith("//"):
            return s, i
    raise ValueError(".ffs 结构损坏：注释行后无数据行")


def read_ffs(path: str | Path, freq_index: int | None = None) -> dict[str, Any]:
    """解析 HFSS .ffs ASCII 远场文件（真实样例逆工程口径，见模块 docstring）。

    freq_index=None 返回全部频块（复矩阵 (n_freq, n_phi, n_theta)）；
    指定序号只回传该频块（(n_phi, n_theta)）。结构缺损显式 ValueError
    （不静默吞，#316 方向：坏结构宁可显式失败）。
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    hits = [i for i, ln in enumerate(lines)
            if ln.strip().startswith(_FFS_FREQ_HEADER)]
    if not hits:
        raise ValueError(f"{path}: 未找到 {_FFS_FREQ_HEADER} 头（非 .ffs ASCII？）")
    n_freq = int(float(_ffs_next_value(lines, hits[0] + 1)[0]))
    if n_freq < 1:
        raise ValueError(f"{path}: 频块数 {n_freq} 非法")

    pwr_hits = [i for i, ln in enumerate(lines)
                if ln.strip().startswith(_FFS_POWER_HEADER)]
    if not pwr_hits:
        raise ValueError(f"{path}: 未找到功率/频率头（{_FFS_POWER_HEADER}）")
    vals: list[float] = []
    i = pwr_hits[0] + 1
    while len(vals) < 4 * n_freq:
        s, i = _ffs_next_value(lines, i)
        try:
            vals.append(float(s))
        except ValueError as exc:
            raise ValueError(f".ffs 功率/频率行解析失败于 {s!r}") from exc
        i += 1
    power = np.asarray(vals, dtype=float).reshape(n_freq, 4)
    freqs_hz = power[:, 3]

    grid_hits = [i for i, ln in enumerate(lines)
                 if ln.strip().startswith(_FFS_GRID_HEADER)]
    if len(grid_hits) != n_freq:
        raise ValueError(
            f".ffs 网格头数量 {len(grid_hits)} ≠ 频块数 {n_freq}（结构损坏）")

    if freq_index is not None and not 0 <= int(freq_index) < n_freq:
        raise ValueError(f"freq_index={freq_index} 越界（共 {n_freq} 块）")
    want = range(n_freq) if freq_index is None else [int(freq_index)]
    e_th: dict[int, np.ndarray] = {}
    e_ph: dict[int, np.ndarray] = {}
    phi_ax = theta_ax = None
    for bi, gh in enumerate(grid_hits):
        size_line, _ = _ffs_next_value(lines, gh + 1)
        parts = size_line.split()
        if len(parts) != 2:
            raise ValueError(f".ffs 网格规模行异常：{size_line!r}")
        n_phi, n_theta = int(parts[0]), int(parts[1])
        col_hits = [j for j in range(gh + 1, len(lines))
                    if lines[j].strip().startswith(_FFS_COL_HEADER)]
        if not col_hits or col_hits[0] < gh:
            raise ValueError(f".ffs 列头缺失（频块 {bi}）")
        block = _ffs_data_block(lines, col_hits[0] + 1, n_phi * n_theta)
        pd = block[:, 0].reshape(n_phi, n_theta)
        td = block[:, 1].reshape(n_phi, n_theta)
        # 行序守卫（审计口径）：phi 外层（重塑后沿 theta 列恒定）、
        # theta 内层（沿 phi 行步进恒定）
        if not (np.allclose(pd, pd[:, :1]) and np.allclose(td, td[:1, :])):
            raise ValueError(".ffs 行序与审计口径不符（phi 外层/theta 内层）")
        ax_ph = np.asarray(np.unique(pd), dtype=float)
        ax_th = np.asarray(np.unique(td), dtype=float)
        if ax_ph.size != n_phi or ax_th.size != n_theta:
            raise ValueError(".ffs 角度轴去重后与网格规模不符（结构损坏）")
        if phi_ax is None:
            phi_ax, theta_ax = ax_ph, ax_th
        if bi in want:
            e_th[bi] = (block[:, 2] + 1j * block[:, 3]).reshape(n_phi, n_theta)
            e_ph[bi] = (block[:, 4] + 1j * block[:, 5]).reshape(n_phi, n_theta)
        if phi_ax is not None and not (np.allclose(ax_ph, phi_ax)
                                       and np.allclose(ax_th, theta_ax)):
            raise ValueError(".ffs 各频块角度轴不一致（结构损坏）")

    order = list(range(n_freq)) if freq_index is None else [int(freq_index)]
    e_theta = np.stack([e_th[k] for k in order]) if order else np.empty(0)
    e_phi = np.stack([e_ph[k] for k in order]) if order else np.empty(0)
    if freq_index is not None:
        e_theta = e_theta[0]
        e_phi = e_phi[0]
    out: dict[str, Any] = {
        "ok": True,
        "reader_version": READER_VERSION,
        "path": str(path),
        "n_freq": n_freq,
        "power_radiated_accepted_stimulated": power[:, :3].tolist(),
        "frequencies_hz": freqs_hz.tolist(),
        "phi_deg": phi_ax,
        "theta_deg": theta_ax,
        "row_order": "phi_outer_theta_inner",
        "freq_index": order,
        "e_theta": e_theta,
        "e_phi": e_phi,
        "units_note": ("功率单位样例未标注（样例为归一值 1.0/0.1/2.0）；场分量"
                       "为 HFSS 远场探针输出（r·E 类幅度），模式判读用，绝对"
                       "口径不虚标"),
    }
    return out
