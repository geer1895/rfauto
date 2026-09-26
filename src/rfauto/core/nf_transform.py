"""平面近场测量 → 远场变换确定性内核（DP-18 C10a）。

职责（铁律 7：数值只在确定性内核；本模块 = 纯 numpy 叶子，无业务依赖）：
- 平面近场 2D 复场（切向 E_x/E_y @ z=z₀ 均匀栅格）→ 加窗 FFT（Kaiser/Hann/
  none 可选）→ 平面波谱 → 远场方向图 E_θ/E_φ（幅度 dB 归一）；
- .ffs ASCII 逆工程 reader（HFSS 远场导出格式，真实样例逐段审计 #331）；
- SWE（球面波展开）第二口径接口（本批契约占位，显式 NotImplementedError，
  不虚报实现）。

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

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


# ─── SWE 第二口径接口（本批契约占位，不虚报实现） ─────────────────────────────

def spherical_wave_expansion(
    e_theta: np.ndarray,
    e_phi: np.ndarray,
    theta_deg: np.ndarray,
    phi_deg: np.ndarray,
    l_max: int,
    r_ref_m: float = 1.0,
) -> dict[str, Any]:
    """SWE（球面波展开）第二口径——**接口占位，本批不实现**。

    预声明契约（DP 后续批实现时按此签名落地）：球面采样复场
    (n_theta, n_phi)（θ 0..180、φ 覆盖 360°，r=r_ref 球面）→ 球面波模系数
    （TE/TM 各 (l_max+1)² 项）→ 任意半径重构/远场外推 + 模系数能量审计。
    本批调用显式 NotImplementedError，不虚报数值能力。
    """
    raise NotImplementedError(
        "SWE 第二口径为接口占位（DP 后续批），本批不提供数值；"
        "平面近场路径请用 planar_nf_to_farfield")


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
