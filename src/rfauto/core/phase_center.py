"""AP-2 相位中心估计（round17 §三 AP-2，P2/S；2026-10-03）。

远场相位对方向余弦的线性 LS 拟合 → 相位中心位置 + 残差 + 多锥角窗
稳定度。**纯函数零 IO**、numpy 依赖、零求解器依赖。

物理口径与出处
--------------
- 远场平移定理（远场相位参考点平移）：时谐约定 e^{+jωt}、传播因子
  e^{−jkr} 下，把天线（其相位中心）从坐标原点平移到 d，远场方向图
  （以原点为相位参考）乘以 e^{+jk·û·d}（û 为观测方向单位矢量）。
  推导：观察点 R·û（R≫|d|）到源点 d 的距离 |Rû−d| = R − û·d +
  O(|d|²/R)，传播相位 −k|Rû−d| → −kR + k·û·d；−kR 并入公共常数。
  同一定理的阵列因子形态见 core/conformal_array.py 的
  AF=Σwₙ·e^{+jk·û·rₙ}（Balanis Ch.6 阵列理论元相位项）。
- 因此测量相位
      Φ(û) = Φ_pattern(û) + k·(d_x·u_x + d_y·u_y + d_z·u_z)，
  相位中心 = 使 Φ_pattern 为常数的 d。对方向余弦 (u_x,u_y,u_z) 的
  线性 LS 拟合（设计矩阵 [1, k·u_x, k·u_y, k·u_z]）给出 d 与常数项。
  IEEE Std 145-1983"相位中心"定义（远场相位在以该点为心的球面上
  恒定的等效点）口径与此一致；IEEE 条目逐字措辞本仓不持有文本，
  页码/逐字引用 UNVERIFIED 如实（#122），数学口径以上述平移定理
  （可独立推导+数值验证）承载。
- 相位解缠：沿切面（cut）内按采样序 np.unwrap；切面间任意 2π 整数
  偏移作为**冗余未知量**进设计矩阵（每切面一列指示列，去共秩），
  由跨切面共享的 (c, d) 解出——不做切面间启发式对齐。
- 可辨识性：采样方向集必须使设计矩阵满秩（单切面只能测切面内两
  分量；最小范数解把不可测分量置 0，返回 identifiable 掩码如实
  标注）。
- 稳定度：对以 axis 为轴、半锥角递增的窗口分别估计，窗口中心间的
  最大 pairwise 距离（spread_m）= 稳定度。真点源所有窗一致
  （spread≈0）；无单一相位中心的结构（如二元干涉）窗间发散。

锚（#118/#300，tests/unit/test_phase_center.py）
------------------------------------------------
1. 平移定理合成：任意方向图 F(û) 相位 +k·û·d₀ → 精确恢复 d₀
   （模型恰为线性，残差 ~1e-12）。
2. 独立物理路径（不用平移定理）：点源在 d₀ 于半径 R 球面的真实
   路径相位 −k|Rû−d₀| → 估计误差 O(k·|d₀|²/R)，随 R 增大单调收敛。
3. 原点偶极子（相位常数）→ |d|≈0。
4. 单主平面切面 → 切面内两分量可测、面外分量最小范数置 0。
5. 双源叠加（无单一相位中心）→ 窗间 spread 显著 > 点源。
6. 相位噪声 σ → 残差 RMS ≈ σ（残差语义钉）。
"""

from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np

__all__ = [
    "estimate_phase_center",
    "phase_center_stability",
]

_C0_M_S = 299792458.0
#: 最小采样数（设计矩阵 4+（n_cuts−1）列的稳健下界）。
_MIN_SAMPLES = 6


def _direction_cosines(
    theta_deg: np.ndarray, phi_deg: np.ndarray
) -> np.ndarray:
    """方向余弦矩阵 (n,3)：u=(sinθcosφ, sinθsinφ, cosθ)，θ/φ 度入参。"""
    th = np.radians(np.asarray(theta_deg, dtype=float))
    ph = np.radians(np.asarray(phi_deg, dtype=float))
    st = np.sin(th)
    return np.stack([st * np.cos(ph), st * np.sin(ph), np.cos(th)], axis=-1)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，得 {out}")
    return out


def estimate_phase_center(
    theta_deg: Any,
    phi_deg: Any,
    phase_rad: Any,
    freq_hz: Any,
    *,
    cut_ids: Any = None,
    weights: Any = None,
    unwrap: bool = True,
    sign: float = 1.0,
) -> dict[str, Any]:
    """远场相位 → 相位中心 LS 估计。

    参数
    ----
    theta_deg / phi_deg : (n,) 采样方向（度）。
    phase_rad : (n,) 以坐标原点为参考的远场相位（弧度，任意缠绕）。
    freq_hz : 频率 [Hz]（>0）。
    cut_ids : (n,) int，可选。切面编号（同一切面内相位连续可解缠，
        切面间未知 2π 偏移）。缺省 = 全部同一切面（此时相位须本身
        连续或已解缠）。
    weights : (n,) 非负权重（如 |E|²；相位仅在幅度显著处可信）。
    unwrap : 是否在切面内做 np.unwrap（数据已解缠可关）。
    sign : 平移定理符号，e^{−jkr} 传播约定取 +1（缺省）；
        e^{+jkr} 约定的引擎产物取 −1。返回的 center 已含符号。

    返回
    ----
    dict：center_m (3,) 估计相位中心位置 [m]；residual_rms_rad
    （去冗余偏移后的加权相位残差 RMS）；rank；n_samples；
    identifiable (3,) bool 掩码（True=该分量被方向集张成，False=
    最小范数置 0）；k_per_m；sign。
    """
    th = np.asarray(theta_deg, dtype=float)
    ph = np.asarray(phi_deg, dtype=float)
    phv = np.asarray(phase_rad, dtype=float)
    if th.ndim != 1 or th.shape != ph.shape or th.shape != phv.shape:
        raise ValueError("theta_deg/phi_deg/phase_rad 须为同长一维数组")
    n = th.size
    if n < _MIN_SAMPLES:
        raise ValueError(f"采样点须 ≥{_MIN_SAMPLES}，得 {n}")
    f = _finite(freq_hz, "freq_hz")
    if f <= 0.0:
        raise ValueError(f"freq_hz 必须为正，得 {f}")
    s = _finite(sign, "sign")
    if s not in (1.0, -1.0):
        raise ValueError(f"sign 只取 ±1，得 {s}")
    k = 2.0 * math.pi * f / _C0_M_S

    if np.any(~np.isfinite(phv)):
        raise ValueError("phase_rad 含 NaN/Inf")

    if cut_ids is None:
        cuts = np.zeros(n, dtype=int)
    else:
        cuts = np.asarray(cut_ids, dtype=int)
        if cuts.shape != (n,) or cuts.min() < 0:
            raise ValueError("cut_ids 须为 (n,) 非负整数数组")
    uniq = np.unique(cuts)
    n_cuts = uniq.size
    if unwrap:
        phu = np.empty_like(phv)
        for cid in uniq:
            m = cuts == cid
            idx = np.flatnonzero(m)
            phu[idx] = np.unwrap(phv[idx])
    else:
        phu = phv.copy()

    u = _direction_cosines(th, ph)
    # 设计矩阵：常数列 + k·u 三列 + 切面偏移指示列（去共秩留 1 参考）
    cols = [np.ones(n), s * k * u[:, 0], s * k * u[:, 1], s * k * u[:, 2]]
    for j in range(1, n_cuts):
        cols.append((cuts == uniq[j]).astype(float))
    a = np.stack(cols, axis=1)
    if n <= a.shape[1]:
        raise ValueError(
            f"采样数 {n} 须 > 设计矩阵列数 {a.shape[1]}"
            f"（4 基础列 + {n_cuts - 1} 切面偏移列），欠定不可估计")
    if weights is None:
        w = np.ones(n)
    else:
        w = np.asarray(weights, dtype=float)
        if w.shape != (n,) or np.any(~np.isfinite(w)) or np.any(w < 0.0):
            raise ValueError("weights 须为 (n,) 非负有限数组")
    sw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(a * sw[:, None], phu * sw, rcond=None)

    resid = a @ beta - phu
    denom = float(np.sum(w))
    rms = math.sqrt(float(np.sum(w * resid * resid)) / denom) if denom > 0 else math.inf
    rank = int(np.linalg.matrix_rank(a * sw[:, None]))
    # 可辨识性：去掉第 i 个方向余弦列后秩下降 ⇔ 该分量可测。
    # （"其余两列满秩"是错误判据——零列场景 u_y≡0 时其余两列满秩但
    #  u_y 本身不可测；秩差法对冗余偏移列同样成立。）
    weighted = a * sw[:, None]
    full_rank = rank
    ident = np.array(
        [int(np.linalg.matrix_rank(
            np.delete(weighted, 1 + i, axis=1))) < full_rank
         for i in range(3)]
    )
    center = np.array(beta[1:4], dtype=float)  # 列已含 s·k：βᵢ = dᵢ（sign 只进列）
    return {
        "center_m": center,
        "residual_rms_rad": rms,
        "rank": rank,
        "n_samples": int(n),
        "n_cuts": int(n_cuts),
        "identifiable": ident,
        "k_per_m": k,
        "sign": s,
    }


def phase_center_stability(
    theta_deg: Any,
    phi_deg: Any,
    phase_rad: Any,
    freq_hz: Any,
    *,
    cone_half_angles_deg: Any = (5.0, 10.0, 20.0, 45.0, 90.0),
    axis: Any = (0.0, 0.0, 1.0),
    cut_ids: Any = None,
    weights: Any = None,
    sign: float = 1.0,
    min_samples_per_window: int = _MIN_SAMPLES,
) -> dict[str, Any]:
    """多锥角窗口相位中心稳定度。

    对每个半锥角 α：取与 axis 夹角 ≤ α 的样本子集跑
    estimate_phase_center（切面信息按原 cut_ids 过滤保留）。返回
    逐窗中心/残差与窗间最大 pairwise 距离 spread_m [m]（有效窗
    <2 个时 spread=None 如实不判）。

    语义锚：真单相位中心（点源）→ spread≈0；无单一相位中心的
    结构（二元干涉）→ spread 显著非零。spread 单独不构成 PASS/
    FAIL 判据（#122：判据由调用方按口径定），本函数只产度量。
    """
    th = np.asarray(theta_deg, dtype=float)
    ph = np.asarray(phi_deg, dtype=float)
    phv = np.asarray(phase_rad, dtype=float)
    n = th.size
    ax = np.asarray(axis, dtype=float)
    if ax.shape != (3,) or float(np.linalg.norm(ax)) == 0.0:
        raise ValueError("axis 须为非零长度 3 矢量")
    ax = ax / float(np.linalg.norm(ax))
    u = _direction_cosines(th, ph)
    cosang = u @ ax
    cuts_all = (np.asarray(cut_ids, dtype=int) if cut_ids is not None
                else np.zeros(n, dtype=int))
    w_all = (np.asarray(weights, dtype=float) if weights is not None
             else None)

    windows: list[dict[str, Any]] = []
    for alpha in np.asarray(cone_half_angles_deg, dtype=float):
        m = cosang >= math.cos(math.radians(float(alpha)))
        n_sel = int(np.count_nonzero(m))
        if n_sel < min_samples_per_window:
            windows.append(
                {"half_angle_deg": float(alpha), "n_samples": n_sel,
                 "center_m": None, "residual_rms_rad": None,
                 "valid": False}
            )
            continue
        sel_cuts = cuts_all[m]
        # 窗内重编号切面（保持相对结构）
        uniq = np.unique(sel_cuts)
        remap = {int(c): i for i, c in enumerate(uniq)}
        sel_cuts_re = np.array([remap[int(c)] for c in sel_cuts], dtype=int)
        try:
            est = estimate_phase_center(
                th[m], ph[m], phv[m], freq_hz,
                cut_ids=sel_cuts_re,
                weights=(w_all[m] if w_all is not None else None),
                unwrap=True, sign=sign,
            )
            est["rank_ok"] = est["rank"] == est["n_cuts"] + 3
        except ValueError:
            est = {"center_m": None, "residual_rms_rad": None,
                   "rank_ok": False}
        windows.append(
            {"half_angle_deg": float(alpha), "n_samples": n_sel,
             "center_m": est.get("center_m"),
             "residual_rms_rad": est.get("residual_rms_rad"),
             "valid": bool(est.get("center_m") is not None and est["rank_ok"]),
             "full_rank": bool(est.get("rank_ok", False))}
        )

    centers = [w["center_m"] for w in windows
               if w["valid"] and w["center_m"] is not None]
    if len(centers) >= 2:
        spread = max(
            float(np.linalg.norm(np.asarray(a) - np.asarray(b)))
            for a, b in itertools.combinations(centers, 2)
        )
    else:
        spread = None
    return {
        "windows": windows,
        "n_valid_windows": len(centers),
        "spread_m": spread,
        "axis": ax,
    }
