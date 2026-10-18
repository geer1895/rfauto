"""EC-24：单元胞互耦→阵列级传播确定性内核（纯函数，零 IO）。

职责（铁律 3/7：core 纯叶子、数值只在确定性内核；消费面只有
service/array_coupling_service.py 与 tests/unit/test_array_coupling.py；
**不进 core/calculators 注册表**——免 #231/#304 注册表消费者连动，
core/array_scan.py DP-4 同款划界）。与 DP-4 的关系：array_scan 的
active_reflection/eep_superposition 消费**已装配的** S/EEP（重轨，逐端口
真机轮）；本模块补**参数化传播链**——单元胞级两两互耦模型 c(d) → 任意
几何 N×N 耦合矩阵合成 → 一阶多重散射嵌入方向图 → 扫 d/扫描角传播
（ecosystem EC-24"扫 d/扫描角→耦合矩阵→嵌入方向图，与 EC-20 单胞快档
衔接"口径）。

模型口径（一阶多重散射/激励溢出，Steinberg 式一阶展开）：
- 阵元 m 的总出射激励 = 直射 a_m + 从各邻元耦合来的份额 Σ_n S_mn·a_n，
  即 a_eff = (I+S)·a；
- 嵌入方向图 F(û) = E_iso(û)·Σ_m a_eff,m·exp(j·k0·r̂·r_m)——孤立单元
  方向图 ×（a_eff 激励的阵因子）；S→0 时精确退化为快档孤立元×AF
  （J3a 位置相位记账恒等同型）；
- 有源反射/扫描阻抗不在此重算——消费方直接调 core.array_scan
  （active_reflection/scan_impedance，行=观测口列=激励口 #208 同约定）。

出处：互耦一阶传播=W. R. Stone/H. Steyskal 一阶散射展开与 Mailloux
《Phased Array Antenna Handbook》互耦章的标准一阶口径；近邻耦合指数衰减
形态=印刷阵元近场耦合的经验包络（本仓默认参数非任何器件标定值，拟合面
fit_exponential_coupling 从实测 S 提取）；EC-24 条目=docs/
research_expansion_20261004_ecosystem_benchmark.md §二。
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from rfauto.core.array_scan import C_M_S

__all__ = [
    "C_M_S",
    "CouplingFit",
    "coupled_array_pattern",
    "coupling_matrix_from_positions",
    "effective_excitations",
    "exponential_coupling",
    "fit_exponential_coupling",
    "tabulated_coupling",
]

_TINY = 1e-12


# ─── 两两互耦模型 c(d)（单元胞级：|S21| 随间距衰减+衬底导波相位）─────────────

def exponential_coupling(
    d_m,
    *,
    freq_hz: float,
    c0: float,
    decay_len_m: float,
    eps_eff_phase: float,
) -> np.ndarray:
    """指数互耦模型：c(d) = c0·exp(−d/ξ)·exp(−j·k_sub·d)（逐元素）。

    c0：d→0 幅度外推（无量纲 S 参数幅度，[0,1)）；ξ：衰减长度（m，>0）；
    eps_eff_phase：相位用衬底有效介电常数（≥1；k_sub=2πf·√εeff/c）。
    纯参数化经验形态——参数须经 fit_exponential_coupling 从实测 S 提取
    或由调用方给 provenance，本函数不做任何器件断言。
    """
    d = np.asarray(d_m, dtype=float)
    if np.any(~np.isfinite(d)) or np.any(d < 0.0):
        raise ValueError(f"d_m 必须非负有限，收到 {d_m!r}")
    f = float(freq_hz)
    if not np.isfinite(f) or f <= 0.0:
        raise ValueError(f"freq_hz 必须为正的有限值，收到 {freq_hz!r}")
    c0f = float(c0)
    if not (0.0 <= c0f < 1.0):
        raise ValueError(f"c0 须在 [0,1)（无量纲幅度），收到 {c0!r}")
    xi = float(decay_len_m)
    if not np.isfinite(xi) or xi <= 0.0:
        raise ValueError(f"decay_len_m 必须为正的有限值，收到 {decay_len_m!r}")
    ee = float(eps_eff_phase)
    if not np.isfinite(ee) or ee < 1.0:
        raise ValueError(f"eps_eff_phase 必须 ≥1，收到 {eps_eff_phase!r}")
    k_sub = 2.0 * np.pi * f * float(np.sqrt(ee)) / C_M_S
    return c0f * np.exp(-d / xi) * np.exp(-1j * k_sub * d)


def tabulated_coupling(
    d_m,
    *,
    d_samples_m: Sequence[float],
    mag_samples: Sequence[float],
    phase_deg_samples: Sequence[float],
) -> tuple[np.ndarray, np.ndarray]:
    """表值互耦模型：单元胞扫距样本 (d, |c|, φ) 线性插值（端点截断）。

    返回 (mag, phase_rad) 逐元素数组；样本须按 d 升序、≥2 点；查询点越出
    样本域取端点值（截断而非外推——外推属器件断言，调用方自担）。单元胞
    仿真/实测扫距（如 EC-20 单胞快档两两 S21(d)）的直读入口。
    """
    d = np.asarray(d_m, dtype=float)
    ds = np.asarray(d_samples_m, dtype=float)
    ms = np.asarray(mag_samples, dtype=float)
    ps = np.asarray(phase_deg_samples, dtype=float)
    if ds.ndim != 1 or ds.size < 2 or np.any(np.diff(ds) <= 0.0):
        raise ValueError(
            f"d_samples_m 须为严格升序 ≥2 点，收到 {d_samples_m!r}")
    if not (ds.size == ms.size == ps.size):
        raise ValueError(
            f"表值三列长度须一致，收到 {ds.size}/{ms.size}/{ps.size}")
    if np.any(ms < 0.0) or np.any(~np.isfinite(ms)) or np.any(~np.isfinite(ps)):
        raise ValueError("表值含负幅度/非有限值")
    if np.any(~np.isfinite(d)) or np.any(d < 0.0):
        raise ValueError(f"d_m 必须非负有限，收到 {d_m!r}")
    mag = np.interp(d, ds, ms)   # np.interp 缺省即端点截断
    phase_rad = np.deg2rad(np.interp(d, ds, ps))
    return mag, phase_rad


# ─── 耦合矩阵合成（任意几何）────────────────────────────────────────────────

def coupling_matrix_from_positions(
    positions_m,
    coupling_of_d: Callable[[np.ndarray], np.ndarray] | np.ndarray,
    *,
    s11_diag: complex | np.ndarray = 0.0j,
) -> np.ndarray:
    """位置集 → (N,N) 复互耦矩阵（互易对称：S[n,m]=S[m,n]=c(d_nm)）。

    positions_m : (N,2) 或 (N,3) 元心位置（m；平面阵 z 缺省 0）；
    coupling_of_d : 纯量函数（exponential_coupling 偏函数/表值插值闭包，
        输入距离数组返回复数组）或 (N,N) 预置矩阵直通；
    s11_diag : 对角元（孤立单元反射系数；标量复或逐元 (N,) 复数组）——
        互耦模型只描述非对角两两耦合面。

    返回 (N,N) 复矩阵；对角线=s11_diag，非对角=pairwise 模型。
    """
    pos = np.asarray(positions_m, dtype=float)
    if pos.ndim != 2 or pos.shape[0] < 1 or pos.shape[1] not in (2, 3):
        raise ValueError(
            f"positions_m 须为 (N,2)|(N,3)，收到 shape={pos.shape}")
    n = int(pos.shape[0])
    if pos.shape[1] == 2:
        pos = np.concatenate([pos, np.zeros((n, 1))], axis=1)
    if np.any(~np.isfinite(pos)):
        raise ValueError("positions_m 含非有限值")
    diff = pos[:, None, :] - pos[None, :, :]      # (N,N,3)
    dist = np.linalg.norm(diff, axis=-1)          # (N,N)
    if callable(coupling_of_d):
        off_diag = np.asarray(coupling_of_d(dist), dtype=complex)
        if off_diag.shape != (n, n):
            raise ValueError(
                f"coupling_of_d 须返回 (N,N)=({n},{n})，收到 {off_diag.shape}")
    else:
        m = np.asarray(coupling_of_d, dtype=complex)
        if m.shape != (n, n):
            raise ValueError(
                f"预置矩阵须为 (N,N)=({n},{n})，收到 {m.shape}")
        off_diag = m
    diag = np.asarray(s11_diag, dtype=complex)
    if diag.ndim == 0:
        diag = np.full(n, complex(diag))
    if diag.shape != (n,):
        raise ValueError(f"s11_diag 须为标量或 (N,)，收到 {diag.shape}")
    out = np.array(off_diag, dtype=complex, copy=True)
    np.fill_diagonal(out, diag)
    return out


# ─── 一阶多重散射嵌入方向图 ─────────────────────────────────────────────────

def effective_excitations(excitations, s_matrix) -> np.ndarray:
    """一阶有效激励 a_eff = (I+S)·a（直射+一次耦合溢出；模型名面）。"""
    a = np.asarray(excitations, dtype=complex)
    s = np.asarray(s_matrix, dtype=complex)
    if a.ndim != 1 or s.ndim != 2 or s.shape[0] != s.shape[1] != a.size:
        raise ValueError(
            f"激励/矩阵维度不一致：a{a.shape} vs S{s.shape}")
    if (np.any(~np.isfinite(a.real)) or np.any(~np.isfinite(a.imag))
            or np.any(~np.isfinite(s.real)) or np.any(~np.isfinite(s.imag))):
        raise ValueError("激励/矩阵含非有限值")
    return a + s @ a


def coupled_array_pattern(
    positions_m,
    excitations,
    *,
    elem_pattern_theta,
    elem_pattern_phi,
    theta_deg,
    phi_deg,
    freq_hz: float,
    s_matrix=None,
) -> np.ndarray:
    """阵列总方向图（θ/φ 分量元组网格上复合成）。

    F_theta = E_θ(û)·Σ_m a_eff,m·P_m(û)、F_phi 同构，其中
    P_m = exp(j·k0·r̂·r_m)（core.array_scan.position_phase 同口径，
    全局原点参考）；s_matrix=None 时 a_eff=a（零耦极限=孤立元×AF，
    与 array_synthesis.planar_array_factor 的 J3a 恒等面同型）。

    elem_pattern_theta/phi : (n_th,n_ph) 实/复单元方向图网格（孤立单元，
        全阵共享同一单元形态——非均匀元阵不适用，如实限制）；
    positions_m : (N,2)|(N,3)（m）；excitations : (N,) 复；
    theta_deg/phi_deg : 1D 角网格（度，与单元方向图网格对齐）；
    s_matrix : None（无耦）或 (N,N) 复耦合矩阵。

    返回 (F_theta, F_phi) 复数组元组，各 (n_th,n_ph)。
    """
    pos = np.asarray(positions_m, dtype=float)
    if pos.ndim != 2 or pos.shape[0] < 1 or pos.shape[1] not in (2, 3):
        raise ValueError(
            f"positions_m 须为 (N,2)|(N,3)，收到 shape={pos.shape}")
    n = int(pos.shape[0])
    if pos.shape[1] == 2:
        pos = np.concatenate([pos, np.zeros((n, 1))], axis=1)
    th = np.asarray(theta_deg, dtype=float)
    ph = np.asarray(phi_deg, dtype=float)
    if th.ndim != 1 or ph.ndim != 1:
        raise ValueError("theta_deg/phi_deg 须为一维角网格（度）")
    et = np.asarray(elem_pattern_theta)
    ep = np.asarray(elem_pattern_phi)
    grid = (th.size, ph.size)
    if et.shape != grid or ep.shape != grid:
        raise ValueError(
            f"单元方向图须为 {grid} 网格，收到 {et.shape}/{ep.shape}")
    a = np.asarray(excitations, dtype=complex)
    if a.ndim != 1 or a.size != n:
        raise ValueError(f"excitations 须为 (N,)={n}，收到 {a.shape}")
    if s_matrix is None:
        s = np.zeros((n, n), dtype=complex)
    else:
        s = np.asarray(s_matrix, dtype=complex)
        if s.shape != (n, n):
            raise ValueError(f"s_matrix 须为 ({n},{n})，收到 {s.shape}")
    f = float(freq_hz)
    if not np.isfinite(f) or f <= 0.0:
        raise ValueError(f"freq_hz 必须为正的有限值，收到 {freq_hz!r}")
    a_eff = effective_excitations(a, s)
    # 位置相位记账 (N, n_th, n_ph)——与 core.array_scan.position_phase 同式
    from rfauto.core.array_scan import position_phase

    p = position_phase(pos, th[:, None], ph[None, :], f)   # (N,n_th,n_ph)
    f_theta = np.tensordot(a_eff, et * p, axes=([0], [0]))
    f_phi = np.tensordot(a_eff, ep * p, axes=([0], [0]))
    return f_theta, f_phi


# ─── 互耦模型拟合（实测 S → 指数模型参数；确定性 LS）────────────────────────

@dataclass(frozen=True)
class CouplingFit:
    """指数互耦模型拟合结果（ln|c|-d 线性 LS + 相位斜率 LS）。"""

    c0: float
    decay_len_m: float
    k_eff_rad_per_m: float
    eps_eff_implied: float
    mag_resid_max_abs: float        # ln|c| 残差最大绝对值
    phase_resid_max_rad: float
    n_pairs: int
    distances_m: tuple[float, ...]  # 唯一距离档（升序）
    degenerate: bool                # 距离档 <2 → 幅度拟合欠定（构造性）


def fit_exponential_coupling(
    s_matrix,
    positions_m,
    *,
    freq_hz: float,
    z0: float = 50.0,
) -> CouplingFit:
    """从实测/装配 S 矩阵提取指数互耦模型参数（EC-24 拟合面）。

    非对角元 (n≠m) 取 |S_nm| 与相位 φ_nm=angle(S_nm)，对距离做
    ln|c| = ln c0 − d/ξ（二参线性 LS）与 φ = −k_eff·d（一参相位相干度
    网格搜——缠绕数据免 unwrap，见实现注）；
    eps_eff_implied = (k_eff·c/(2πf))²（衬底有效介电常数反演读数）。
    对角元不进拟合（孤立反射面非两两互耦）。

    degenerate：唯一距离档 <2 时幅度拟合零自由度（参数可辨识但残差恒 0
    属构造性，非验证）——2x2 阵恰两档距离（邻位/对角）为最小可拟合例；
    如实标记，消费方判读时不得把零残差当拟合质量证据。
    """
    s = np.asarray(s_matrix, dtype=complex)
    if s.ndim != 2 or s.shape[0] != s.shape[1] or s.shape[0] < 2:
        raise ValueError(f"s_matrix 须为 (N,N) N≥2，收到 shape={s.shape}")
    pos = np.asarray(positions_m, dtype=float)
    if pos.ndim != 2 or pos.shape[0] != s.shape[0]:
        raise ValueError(
            f"positions_m 须为 (N,{s.shape[0]})，收到 shape={pos.shape}")
    f = float(freq_hz)
    if not np.isfinite(f) or f <= 0.0:
        raise ValueError(f"freq_hz 必须为正的有限值，收到 {freq_hz!r}")
    _ = float(z0)   # 口径占位：S 参数已按 z0 归一（装配链同基），不重归一
    n = s.shape[0]
    if pos.shape[1] == 2:
        pos = np.concatenate([pos, np.zeros((n, 1))], axis=1)
    dist = np.linalg.norm(pos[:, None, :] - pos[None, :, :], axis=-1)
    mask = ~np.eye(n, dtype=bool)
    d = dist[mask]
    mag = np.abs(s[mask])
    phase = np.angle(s[mask])
    if np.any(mag <= _TINY):
        raise ValueError(
            "非对角元含近零幅度（|S|≤1e-12），ln 拟合不可用——先核装配面")
    uniq = np.unique(np.round(d, 12))
    degenerate = uniq.size < 2

    # 幅度：ln|c| = ln c0 − d/ξ（线性 LS；斜率恒负约束由数据自然满足，
    # 反号（增益型耦合）如实输出不夹持）
    y = np.log(mag)
    slope, intercept = np.polyfit(d, y, 1)
    decay = -1.0 / slope if slope < 0.0 else np.inf
    c0 = float(np.exp(intercept))
    mag_resid = float(np.max(np.abs(y - (slope * d + intercept))))

    # 相位：φ = −k_eff·d（过原点）——缠绕数据下用相位相干度粗网格全局
    # 搜 + 局部细化（确定性，无优化器依赖）：k_eff = argmax_k
    # |Σ exp(j(φ_m + k·d_m))|/n；搜索域 (0, 3·k0]（覆盖 εeff≤9 衬底导波，
    # 超域属非物理参数化如实越界）。残差按主值折叠报告。
    k0 = 2.0 * np.pi * f / C_M_S
    k_hi = 3.0 * k0
    grid = np.linspace(0.0, k_hi, 4001)

    def _coherence(k_arr: np.ndarray) -> np.ndarray:
        ph = phase[None, :] + np.asarray(k_arr)[:, None] * d[None, :]
        return np.abs(np.exp(1j * ph).sum(axis=1)) / d.size

    coh = _coherence(grid)
    i_pk = int(np.argmax(coh))
    lo = grid[max(i_pk - 1, 0)]
    hi = grid[min(i_pk + 1, grid.size - 1)]
    fine = np.linspace(lo, hi, 2001)
    k_eff = float(fine[int(np.argmax(_coherence(fine)))])
    phase_resid = np.angle(np.exp(1j * (phase + k_eff * d)))
    phase_resid_max = float(np.max(np.abs(phase_resid)))
    eps_implied = (k_eff * C_M_S / (2.0 * np.pi * f)) ** 2
    return CouplingFit(
        c0=c0,
        decay_len_m=float(decay),
        k_eff_rad_per_m=k_eff,
        eps_eff_implied=float(eps_implied),
        mag_resid_max_abs=mag_resid,
        phase_resid_max_rad=phase_resid_max,
        n_pairs=int(d.size),
        distances_m=tuple(float(v) for v in uniq),
        degenerate=bool(degenerate),
    )
