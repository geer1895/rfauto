r"""NX-1 MIMO 虚拟阵确定性内核（round14 §四 :88「TX×RX Kronecker 展开虚拟阵/
等效孔径/角分辨率闭式，接 sparse_array_cs」；B 流，2026-10-02）。

确定性纯函数、零 IO、零求解器、零新依赖（纯 numpy）；数值全部落在本内核，
LLM/agent 只解释（铁律 7）。

口径与法源（铁律 5：法源写 docstring；裁判=独立路径，#118）
================================================================

- **虚拟阵（sum co-array / Kronecker 展开）**：收发分置（co-located）MIMO
  雷达/阵的两路传播（Tx→目标、目标→Rx）在同方向远场目标上相位相加，
  收发联合导向矢量 = a(u) = a_tx(u) ⊗ a_rx(u)——等效为位于
  **p_v = p_tx + p_rx** 的"虚拟阵元"（sum co-array）。法源：
  J. Li & P. Stoica, "MIMO radar with colocated antennas", IEEE Signal
  Processing Magazine 24(5), 2007（§"virtual array"）；同作者专著
  "MIMO Radar Signal Processing", Wiley 2009, Ch.1。
- **等距收发 ULA 闭式**：Tx 的 M 元与 Rx 的 N 元同间距 d 的 ULA →
  虚拟阵 = M+N−1 元等间距 d 的 ULA，多重数（multiplicity）为三角分布
  {1,2,…,min(M,N),…,2,1}（round14 验收锚：EuRAD 2023 汽车雷达
  12×6 案例 → 虚拟 17 元 ULA）。
- **差孔径（difference co-array）**：p_i − p_j（带符号 Lag），协方差域
  DOA 处理的稀疏阵口径（Pal & Vaidyanathan, IEEE TSP 58(2), 2010 nested
  阵一族）——两路相位相减的口径，以 convention="difference" 提供；
  MIMO 虚拟阵主判口径 = convention="sum"（规格只钉 sum 语义，difference
  是同一"和/差孔径"谱系的伴生口径，如实分档不混用）。
- **等效孔径恒等式**：sum 口径下虚拟阵孔径 = Tx 孔径 + Rx 孔径
  （min/max 的可分离性：min(p_i+q_j)=min p+min q，max 同理——任意位置
  精确恒等，非近似；单测钉）。
- **角分辨率闭式（适用边界诚实标注）**：
  * 分组权重均匀的等距虚拟 ULA（如单 Tx 复制 Rx 阵、M=1、sum-distinct
    几何多重数全 1）：HPBW ≈ 0.886·λ/(N_v·d_λ)（Balanis 3ed §6.3 渐近式，
    复用 rfauto.core.array_synthesis.broadside_hpbw_rad——只读复用，不
    重复实现）、Rayleigh 首零 δu = 1/(N_v·d_λ)；
  * 两因子均为同距均匀 ULA（sum 口径，12×6 类自然虚拟阵）：乘积方向图
    零点=因子零点之并 → **首零分辨率 = 1/(max(M,N)·d_λ)**（精确恒等式，
    实测 12×6 → 1/6）；此时虚拟阵权重是三角锥削（多重数分布），均匀阵
    HPBW 闭式**不适用**（实测偏宽 ~29%），只给数值 HPBW；
  * 等效孔径增益 aperture_gain_vs_tx = L_virtual/L_tx 任意几何精确
    （孔径可加恒等式的比值）。
- **两路方向图恒等式（对拍裁判）**：乘积路径 AF_tx(u)·AF_rx(u) 与
  虚拟位置+成对权重分组的"等效物理阵"路径 Σ_k W_k e^{j2π s_k(u−u0)}
  对任意 u 逐点相等（Kronecker 结构的直接推论；独立代码路径双算，
  残差由报告输出、由测试钉到 1e-9 量级）。
- **接 sparse_array_cs**：虚拟位置（波长单位）+ u 网格与
  rfauto.core.sparse_array_cs.forward_matrix 的前向算子
  A[m,n]=exp(j·2π·p_n·(u_m−u0)) 同构——kron(A_tx, A_rx) @ (w_tx ⊗ w_rx)
  与 forward_matrix(虚拟位置, u) @ W_grouped 的逐位恒等由测试钉死
  （本模块不 import sparse_array_cs，接口同构由测试裁判，避免 core
  兄弟模块耦合）。

诚实边界（预声明，#122）
========================
- 虚拟阵 = ULA（M+N−1 元）**只在收发等距（同 d）且无位置偏移重排时
  成立**；收发间距不等时虚拟阵是非均匀格点（可能有碰撞合并），本内核
  如实输出 distinct 位置+多重数，uniform_spacing_lambda 返回 None。
- 收发同位恒等阵（monostatic 形态）sum 口径：虚拟阵=自和集
  {p_i+p_j}——N 元阵 → 2N−1 元、**孔径精确加倍**（span 2(N−1)d）；仅
  对角自发自收（单通道 monostatic 一对）时虚拟元在 2p。d=λ/2 物理阵的
  对角自收口径等效间距 d_v=2d=λ（栅瓣区）——单站 MIMO ULA 因此要求
  物理间距 ≤ λ/4；本内核只输出几何事实，栅瓣判定由调用方用
  array_synthesis.has_grating_lobe 复用（测试演示）。
- 本内核是远场/同方向目标口径（a_tx 与 a_rx 同 u）；双基地角分离
  （u_tx ≠ u_rx）的双基地虚拟阵超出本内核域，显式不支持。

设计约束：core 层（仅 numpy + 只读复用 array_synthesis），非法输入显式
ValueError，不静默兜底；输出 JSON 可序列化（PSLL 无副瓣时 None，不产
-inf——json allow_nan=False 兼容）。
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import numpy as np

from .array_synthesis import (
    broadside_hpbw_rad,
    peak_sidelobe_level_db,
)

__all__ = [
    "CONVENTIONS",
    "equivalent_physical_array_factor",
    "mimo_virtual_array_report",
    "virtual_array_elements",
    "virtual_array_factor",
]

CONVENTIONS = ("sum", "difference")
"""虚拟阵口径：sum=收发相位相加（MIMO 虚拟阵，主判）；difference=带符号
差 Lag（协方差 DOA 口径）。"""

_TINY = 1e-12


# ─── 输入校验 ──────────────────────────────────────────────────────────────────


def _reject_bool(arr: np.ndarray, name: str) -> None:
    if arr.dtype == bool:
        raise ValueError(f"{name} 不能是布尔数组")


def _validate_positions(positions: Any, name: str) -> np.ndarray:
    arr = np.asarray(positions)
    _reject_bool(arr, name)
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须是一维位置序列（波长单位），收到 shape={arr.shape}")
    if arr.size == 0:
        raise ValueError(f"{name} 不能为空")
    arr = arr.astype(float)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含非有限值（NaN/Inf）")
    return arr


def _validate_weights(weights: Any, n_expected: int, name: str) -> np.ndarray:
    if weights is None:
        return np.ones(n_expected, dtype=complex)
    arr = np.asarray(weights)
    _reject_bool(arr, name)
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须是一维权重序列")
    if arr.size != n_expected:
        raise ValueError(f"{name} 长度 {arr.size} != 位置数 {n_expected}")
    arr = arr.astype(complex)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含非有限值（NaN/Inf）")
    return arr


def _validate_convention(convention: str) -> str:
    if convention not in CONVENTIONS:
        raise ValueError(f"convention 必须是 {CONVENTIONS} 之一，收到 {convention!r}")
    return convention


def _validate_scan(scan_direction_cosine: float) -> float:
    u0 = float(scan_direction_cosine)
    if not np.isfinite(u0) or abs(u0) > 1.0 + 1e-9:
        raise ValueError(f"scan_direction_cosine 必须落在 [-1, 1]，收到 {scan_direction_cosine!r}")
    return u0


# ─── 虚拟阵几何 ────────────────────────────────────────────────────────────────


def virtual_array_elements(
    tx_positions_lambda,
    rx_positions_lambda,
    *,
    tx_weights=None,
    rx_weights=None,
    convention: str = "sum",
) -> dict[str, Any]:
    """Tx×Rx 成对位置 → 虚拟阵元（distinct 位置 + 多重数 + 成对权重分组）。

    sum 口径：s_k = p_i + q_j（两路相位相加，Kronecker 展开）；
    difference 口径：s_k = p_i − q_j（带符号差 Lag）。
    成对权重：W = w_tx_i · w_rx_j（sum）/ w_tx_i · conj(w_rx_j)（difference），
    同一虚拟位置的成对权重求和分组（W_grouped[k]）。

    返回 dict（JSON 可序列化；pair_weights 以 [re, im] 对输出）。
    """
    convention = _validate_convention(convention)
    p = _validate_positions(tx_positions_lambda, "tx_positions_lambda")
    q = _validate_positions(rx_positions_lambda, "rx_positions_lambda")
    w_tx = _validate_weights(tx_weights, p.size, "tx_weights")
    w_rx = _validate_weights(rx_weights, q.size, "rx_weights")

    if convention == "sum":
        s = (p[None, :] + q[:, None]).ravel()  # 行=tx、列=rx → s = p_i + q_j
        w_pair = (w_tx[None, :] * w_rx[:, None]).ravel()
    else:
        s = (p[None, :] - q[:, None]).ravel()
        w_pair = (w_tx[None, :] * np.conj(w_rx[:, None])).ravel()

    order = np.argsort(s, kind="stable")
    s_sorted = s[order]
    w_sorted = w_pair[order]
    # 容差聚簇（同位合并）：和/差的浮点路径噪声会把同一数学位置按 (i,j)
    # 路径分裂成 1 ulp 相隔的两点（2s'+3s' ≠ 1s'+4s'，物理 mm 输入实测
    # 复现）——np.unique 的精确判据会假分裂出零间距格点。判据与全仓
    # 等距检测同带：|Δ| ≤ 1e-9·max(1, |s|max)；簇代表值=算术平均
    # （确定性），多重数/成对权重逐簇求和。
    tol = 1e-9 * max(1.0, float(np.max(np.abs(s_sorted))))
    # 空差集（单对）时 nonzero 给空数组 → starts=[0] 自然退化，无需分支
    starts = np.concatenate(
        ([0], np.nonzero(np.diff(s_sorted) > tol)[0] + 1))
    counts = np.diff(np.append(starts, s_sorted.size))
    uniq = (np.add.reduceat(s_sorted, starts) / counts).astype(float)
    w_grouped = np.add.reduceat(w_sorted, starts)

    aper_tx = float(p.max() - p.min())
    aper_rx = float(q.max() - q.min())
    aper_virtual = float(uniq.max() - uniq.min())
    residual = abs(aper_virtual - (aper_tx + aper_rx)) if convention == "sum" else None

    uniform_spacing: float | None = None
    if uniq.size >= 2:
        diffs = np.diff(uniq)
        if np.allclose(diffs, diffs[0], rtol=1e-9, atol=1e-12):
            uniform_spacing = float(diffs[0])
    # （注：等距检测与 _uniform_spacing 同判据；此处保留局部实现以免
    # 报告路径重复做 unique——判据 rtol/atol 由测试跨两路径一致性钉住。）

    return {
        "convention": convention,
        "n_tx": int(p.size),
        "n_rx": int(q.size),
        "n_pairs": int(p.size * q.size),
        "n_virtual": int(uniq.size),
        "positions_lambda": [float(v) for v in uniq],
        "multiplicity": [int(c) for c in counts],
        "pair_weights": [[float(v.real), float(v.imag)] for v in w_grouped],
        "aperture_tx_lambda": aper_tx,
        "aperture_rx_lambda": aper_rx,
        "aperture_lambda": aper_virtual,
        "aperture_additivity_residual": residual,
        "uniform_spacing_lambda": uniform_spacing,
    }


# ─── 方向图（两条独立路径）─────────────────────────────────────────────────────


def _array_factor_positions(u, positions, weights, u0: float) -> np.ndarray:
    """Σ_n w_n exp(j·2π·p_n·(u−u0))（与 array_synthesis.array_factor 的
    非均匀位置推广同口径；sparse_array_cs.forward_matrix 行向量同构）。"""
    u_arr = np.atleast_1d(np.asarray(u, dtype=float))
    phase = np.exp(1j * 2.0 * np.pi * np.outer(u_arr - u0, positions))
    return phase @ weights


def virtual_array_factor(
    u,
    tx_positions_lambda,
    rx_positions_lambda,
    *,
    tx_weights=None,
    rx_weights=None,
    convention: str = "sum",
    scan_direction_cosine: float = 0.0,
    normalize: bool = True,
) -> np.ndarray:
    """两路乘积路径：AF(u) = AF_tx(u) · AF_rx(u)（sum）/ AF_tx(u)·conj(AF_rx(u))
    （difference）。normalize=True 时除以 (Σw_tx)·(Σw_rx)（sum）或
    (Σw_tx)·conj(Σw_rx)（difference），u=u0 处归一化到 1。

    零和权重（Σw=0，如带符号傅里叶综合激励）在 normalize=True 时显式
    拒绝——归一化无定义，不静默放行。
    """
    convention = _validate_convention(convention)
    u0 = _validate_scan(scan_direction_cosine)
    p = _validate_positions(tx_positions_lambda, "tx_positions_lambda")
    q = _validate_positions(rx_positions_lambda, "rx_positions_lambda")
    w_tx = _validate_weights(tx_weights, p.size, "tx_weights")
    w_rx = _validate_weights(rx_weights, q.size, "rx_weights")

    af_tx = _array_factor_positions(u, p, w_tx, u0)
    af_rx = _array_factor_positions(u, q, w_rx, u0)
    if convention == "sum":
        af = af_tx * af_rx
        scale = w_tx.sum() * w_rx.sum()
    else:
        af = af_tx * np.conj(af_rx)
        scale = w_tx.sum() * np.conj(w_rx.sum())
    if normalize:
        if abs(scale) < _TINY:
            raise ValueError("权重和为零（Σw_tx·Σw_rx=0），归一化无定义——传 normalize=False 或换权重")
        af = af / scale
    return af


def equivalent_physical_array_factor(
    u,
    elements: dict,
    *,
    scan_direction_cosine: float = 0.0,
    normalize: bool = True,
) -> np.ndarray:
    """等效物理阵路径：虚拟位置 + 分组权重 W_grouped 直接求和（独立代码
    路径，供与 virtual_array_factor 乘积路径对拍——两条路径对任意 u
    逐点相等是 Kronecker 结构恒等式）。"""
    _validate_scan(scan_direction_cosine)
    positions = np.asarray(elements["positions_lambda"], dtype=float)
    if positions.size == 0:
        raise ValueError("elements 无虚拟阵元（空几何）")
    w_pair = np.asarray(elements["pair_weights"], dtype=float)
    w = w_pair[:, 0] + 1j * w_pair[:, 1]
    af = _array_factor_positions(u, positions, w, float(scan_direction_cosine))
    if normalize:
        total = w.sum()
        if abs(total) < _TINY:
            raise ValueError("分组权重和为零，归一化无定义——传 normalize=False 或换权重")
        af = af / total
    return af


# ─── 报告（注册壳入口）─────────────────────────────────────────────────────────


def _numeric_hpbw_u(u_values: np.ndarray, magnitude: np.ndarray) -> float | None:
    """主瓣 −3 dB 宽度（u 域，线性插值过阈点）；无过阈（单点/退化）→ None。"""
    peak = float(magnitude.max())
    if peak <= 0.0:
        return None
    k_peak = int(np.argmax(magnitude))
    half = peak / np.sqrt(2.0)
    if magnitude[k_peak] < half:  # 不可达（peak<阈值不可能，守卫对称性）
        return None

    def _cross(indices: np.ndarray) -> float | None:
        for a, b in pairwise(indices):
            if magnitude[a] >= half > magnitude[b]:
                t = (magnitude[a] - half) / (magnitude[a] - magnitude[b])
                return float(u_values[a] + t * (u_values[b] - u_values[a]))
            if magnitude[b] >= half > magnitude[a]:
                t = (magnitude[b] - half) / (magnitude[b] - magnitude[a])
                return float(u_values[b] - t * (u_values[b] - u_values[a]))
        return None

    left = _cross(np.arange(k_peak, -1, -1))
    right = _cross(np.arange(k_peak, magnitude.size))
    if left is None or right is None:
        return None
    return float(right - left)


def _psll_safe(u_values: np.ndarray, magnitude: np.ndarray) -> float | None:
    psll = peak_sidelobe_level_db(magnitude, u_values)
    return float(psll) if np.isfinite(psll) else None


def mimo_virtual_array_report(
    tx_positions_lambda,
    rx_positions_lambda,
    *,
    tx_weights=None,
    rx_weights=None,
    convention: str = "sum",
    scan_direction_cosine: float = 0.0,
    u_points: int = 801,
) -> dict[str, Any]:
    """虚拟阵综合报告（几何 + 分辨率 + 方向图对拍残差，全部 JSON 可序列化）。

    分辨率闭式的适用边界（诚实标注，不越界外推）：
    - hpbw_broadside_u_closed_form（0.886/(N_v·d)）只对**分组权重均匀的
      等距虚拟 ULA** 精确成立（如单 Tx 复制 Rx、M=1、或 sum-distinct 几何
      使多重数全 1）——等距收发 ULA 的自然虚拟阵是三角锥削权重（乘积
      方向图比均匀 17 元阵宽 ~29%，实测 12×6），此时闭式不适用、返回
      None，只给数值 HPBW；
    - rayleigh_first_null_u_closed_form 对**两因子均为同距均匀 ULA**
      （sum 口径）成立：乘积方向图的零点=因子零点之并 → 首零
      = 1/(max(M,N)·d)（12×6 → 1/6，精确可钉）；
    - aperture_gain_vs_tx 是任意几何下精确的孔径恒等式比值。
    """
    elements = virtual_array_elements(
        tx_positions_lambda, rx_positions_lambda,
        tx_weights=tx_weights, rx_weights=rx_weights, convention=convention)
    u0 = _validate_scan(scan_direction_cosine)
    if not isinstance(u_points, int) or isinstance(u_points, bool) or u_points < 3:
        raise ValueError(f"u_points 至少为 3 的整数，收到 {u_points!r}")
    u_grid = np.linspace(-1.0, 1.0, int(u_points))

    p_tx = _validate_positions(tx_positions_lambda, "tx_positions_lambda")
    p_rx = _validate_positions(rx_positions_lambda, "rx_positions_lambda")
    w_tx = _validate_weights(tx_weights, elements["n_tx"], "tx_weights")

    af_virtual = virtual_array_factor(
        u_grid, tx_positions_lambda, rx_positions_lambda,
        tx_weights=tx_weights, rx_weights=rx_weights,
        convention=convention, scan_direction_cosine=u0, normalize=True)
    af_equiv = equivalent_physical_array_factor(
        u_grid, elements, scan_direction_cosine=u0, normalize=True)
    identity_residual = float(np.max(np.abs(af_virtual - af_equiv)))

    af_tx_norm = _array_factor_positions(u_grid, p_tx, w_tx, u0) / w_tx.sum()
    mag_virtual = np.abs(af_virtual)
    hpbw_numeric = _numeric_hpbw_u(u_grid, mag_virtual)
    hpbw_tx_numeric = _numeric_hpbw_u(u_grid, np.abs(af_tx_norm))

    n_v = elements["n_virtual"]
    d_v = elements["uniform_spacing_lambda"]
    w_pair = np.asarray(elements["pair_weights"], dtype=float)
    weights_uniform = bool(
        np.allclose(w_pair[:, 1], 0.0, atol=1e-12)
        and np.allclose(w_pair[:, 0], w_pair[0, 0], rtol=1e-9, atol=1e-12))

    hpbw_closed: float | None = None
    if d_v is not None and weights_uniform:
        hpbw_closed = broadside_hpbw_rad(n_v, d_v)

    first_null_closed: float | None = None
    if convention == "sum" and d_v is not None:
        d_tx = _uniform_spacing(p_tx)
        d_rx = _uniform_spacing(p_rx)
        # 等距同距判据用容差比较（求和路径 vs 原位置路径可差 1 ulp——
        # 精确 == 会把舍入物理输入误拒，实测 77GHz 12×6 复现）
        same_d = d_tx is not None and np.isclose(
            d_tx, d_v, rtol=1e-9, atol=1e-12)
        both_ula = d_rx is not None and (
            elements["n_tx"] == 1 or same_d)
        if both_ula:
            first_null_closed = 1.0 / (max(elements["n_tx"], elements["n_rx"]) * d_v)

    aper_tx = elements["aperture_tx_lambda"]
    aperture_gain = (
        float(elements["aperture_lambda"] / aper_tx) if aper_tx > _TINY else None)
    resolution_gain_numeric = (
        float(hpbw_tx_numeric / hpbw_numeric)
        if hpbw_numeric not in (None, 0.0) and hpbw_tx_numeric is not None else None)

    return {
        **elements,
        "weights_uniform": weights_uniform,
        "scan_direction_cosine": u0,
        "u_points": int(u_points),
        "pattern_identity_residual": identity_residual,
        "hpbw_u_numeric": hpbw_numeric,
        "hpbw_tx_only_u_numeric": hpbw_tx_numeric,
        "hpbw_broadside_u_closed_form": hpbw_closed,
        "hpbw_broadside_deg_closed_form": (
            float(np.degrees(hpbw_closed)) if hpbw_closed is not None else None),
        "rayleigh_first_null_u_closed_form": first_null_closed,
        "aperture_gain_vs_tx": aperture_gain,
        "resolution_gain_numeric_vs_tx": resolution_gain_numeric,
        "psll_virtual_db": _psll_safe(u_grid, mag_virtual),
        "psll_tx_only_db": _psll_safe(u_grid, np.abs(af_tx_norm)),
    }


def _uniform_spacing(positions: np.ndarray) -> float | None:
    """等距判据（sorted unique 位置差全等）；单点返回 None（无间距语义）。"""
    uniq = np.unique(np.asarray(positions, dtype=float))
    if uniq.size < 2:
        return None
    diffs = np.diff(uniq)
    if np.allclose(diffs, diffs[0], rtol=1e-9, atol=1e-12):
        return float(diffs[0])
    return None
