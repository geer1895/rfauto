"""NX-3 近场 beamfocusing + OAM 环阵综合闭式面。

规格：研究扩充 round14 §四 NX-3——"聚焦相位
φₙ=−k·rₙ、Rayleigh 距离判据、环阵 OAM 激励 exp(jlφₙ)；aperture_holography
谱变换对拍"。来源 6G Near-field White Paper 2.0 / arXiv:2607.09479（口径
名，页码 UNVERIFIED 如实，#122）。纯闭式叶子，零 IO、不进 calculators。

模块面
------
- ``fraunhofer_distance_m``：d_F = 2D²/λ（远场判据；白皮书口径名
  "Rayleigh distance" 同值——文献中 Rayleigh 距离另有 D²/(2λ) 电抗区
  口径，本函数只承载 2D²/λ 判据并在返回 dict 附 conventional 注记）。
- ``focusing_phases``：近场聚焦相位 law φₙ = −k·|rₙ−p|（可选参考面
  补偿：阵心到焦点距离基准，使平均相位为零——纯数值位移不改动别处）。
- ``farfield_tilt_phases``：远场扫描相位 φₙ = −k·û·rₙ（单平面波指向）。
- ``focusing_farfield_limit_check``：焦点距离 d → ∞ 时聚焦相位与远场
  切向相位的一阶一致（|Δφ| → 0，判据 ∝ D²/d——球面波→平面波的退路）。
- ``focal_field_map``：给定阵元位置/激励，Free-space Green 求和
  E(r) = Σ wₙ·g(r−rₙ)（标量 Green，g=e^{−jkR}/(4πR)），输出网格复场
  （近场聚焦的裁判路：焦点处 N 元同相叠加、离焦衰减）。
- ``oam_ring_excitation``：环阵 OAM 模式 l 激励 wₙ = exp(j·l·φₙ)/√N。
- ``oam_axis_field``：轴上场 Σₙ wₙ·exp(jkR)→ l≠0 时解析为零
  （等比求和恒等式，逐位锚）。
- ``oam_mode_purity``：环采样场的 Fourier 模分解（DFT 幅值谱 → 模式
  纯度 = |a_l|²/Σ|a_m|²）；正交性 = DFT 酉性（结构锚）。
- ``phase_mode_count``：圆阵可用相位模数 N_pm ≈ floor(2kR)+1
  （Balanis Ch.6 口径名，页码 UNVERIFIED；NX-6 共形阵共用判据）。

物理口径（e^{+jωt}、前向波 e^{−jk·r}，与本仓 aperture_holography/
nf_transform/sra 一致；全 SI，k=2πf/c）
------------------------------------------------------------------
* 聚焦相位符号约定：激励相位取负路径相位（wₙ = e^{+jk|rₙ−p|}）使各元
  到焦点同相（补偿 e^{−jkR} 传播因子）。
* 设计约束：numpy 纯函数；非法输入显式 ValueError；dict 输出 JSON 可
  序列化（数组除外，注明）。

出处
----
1. round 文档：round14 §四 NX-3。
2. 6G Near-field White Paper 2.0（判据口径名）；arXiv:2607.09479（OAM
   环阵口径名）；Balanis "Antenna Theory" 4th Ch.6（相位模数口径名）。
   页码 UNVERIFIED 如实。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = [
    "C0_M_S",
    "NF_WP_SOURCE",
    "farfield_tilt_phases",
    "focal_field_map",
    "focusing_farfield_limit_check",
    "focusing_phases",
    "fraunhofer_distance_m",
    "oam_axis_field",
    "oam_mode_purity",
    "oam_ring_excitation",
    "phase_mode_count",
]

C0_M_S = 299792458.0
NF_WP_SOURCE = (
    "6G Near-field White Paper 2.0（d_F=2D²/λ 判据口径名）+ "
    "arXiv:2607.09479（OAM 环阵）+ Balanis 4th Ch.6（相位模数）；"
    "页码 UNVERIFIED（#122 如实）"
)


def _positive(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def _nonneg(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v < 0.0:
        raise ValueError(f"{name} 必须为非负有限数，实际 {x!r}")
    return v


def _wavenumber(f_hz: Any) -> float:
    f = _positive(f_hz, "f_hz")
    return 2.0 * math.pi * f / C0_M_S


def _positions_1d(positions_m: Any, name: str) -> np.ndarray:
    pos = np.asarray(positions_m, dtype=float)
    if pos.ndim != 2 or pos.shape[1] != 3:
        raise ValueError(f"{name} 须为 (N,3) 数组，实际形状 {pos.shape}")
    return pos


# ─── 距离判据 ────────────────────────────────────────────────────────────────
def fraunhofer_distance_m(aperture_d_m: Any, f_hz: Any) -> dict[str, float]:
    """远场判据距离 d_F = 2D²/λ + 电抗区口径注记。

    白皮书口径 "Rayleigh distance" = 2D²/λ（本函数主值）；文献中另有
    "reactive near-field boundary" ≈ 0.62√(D³/λ)（短偶极子口径）与
    "Rayleigh range" D²/(2λ)（高斯光学类比口径）——不混用，只报主值+
    注记。
    """
    d = _positive(aperture_d_m, "aperture_d_m")
    k = _wavenumber(f_hz)
    lam = 2.0 * math.pi / k
    return {
        "fraunhofer_distance_m": 2.0 * d * d / lam,
        "wavelength_m": lam,
        "convention_note": (
            "主值=2D^2/lambda（远场/Fraunhofer 判据，白皮书 Rayleigh "
            "distance 同值）；D^2/(2 lambda) 为高斯光学类比口径，不混用"
        ),
    }


# ─── 相位律 ──────────────────────────────────────────────────────────────────
def focusing_phases(positions_m: Any, focal_point_m: Any, f_hz: Any,
                    reference_compensate: bool = True) -> np.ndarray:
    """近场聚焦激励相位 wₙ = exp(+j·k·|rₙ−p|)（补偿 e^{−jkR} 传播）。

    reference_compensate=True 时再乘全局相位 exp(−jk|r_ref−p|)（参考点
    = 阵位置质心），只改全局相位不改动相对聚焦关系。
    返回复激励 (N,)。
    """
    pos = _positions_1d(positions_m, "positions_m")
    p = np.asarray(focal_point_m, dtype=float)
    if p.shape != (3,):
        raise ValueError("focal_point_m 须为长度 3")
    k = _wavenumber(f_hz)
    dist = np.linalg.norm(pos - p[None, :], axis=1)
    w = np.exp(1j * k * dist)
    if reference_compensate:
        ref = pos.mean(axis=0)
        w = w * np.exp(-1j * k * float(np.linalg.norm(ref - p)))
    return w


def farfield_tilt_phases(positions_m: Any, direction_m: Any, f_hz: Any) -> np.ndarray:
    """远场指向激励 wₙ = exp(−j·k·û·rₙ)（单位方向 û）。"""
    pos = _positions_1d(positions_m, "positions_m")
    u = np.asarray(direction_m, dtype=float)
    if u.shape != (3,):
        raise ValueError("direction_m 须为长度 3")
    norm = float(np.linalg.norm(u))
    if norm == 0.0:
        raise ValueError("direction_m 不得为零向量")
    u = u / norm
    k = _wavenumber(f_hz)
    return np.exp(-1j * k * (pos @ u))


def focusing_farfield_limit_check(positions_m: Any, f_hz: Any,
                                  direction_m: Any,
                                  d_list_m: Any) -> dict[str, Any]:
    """聚焦相位 → 远场切向相位的极限一致性检查。

    对焦点距离序列 d：聚焦相位 wₙ(d) vs 远场指向 wₙ(∞) 的最大相位差。
    判据（球面波前二阶展开）：max|Δφ| ≈ k·max|rₙ,⊥|²/(2d) ∝ 1/d。
    返回 {d_list_m, max_phase_diff_rad, first_order_prod}，其中
    first_order_prod = max|Δφ|·d / (k·r_perp_max²/2)（一阶常数 ≈1 的
    收敛性锚）。
    """
    pos = _positions_1d(positions_m, "positions_m")
    k = _wavenumber(f_hz)
    u = np.asarray(direction_m, dtype=float)
    u = u / float(np.linalg.norm(u))
    ref = pos.mean(axis=0)
    rel = pos - ref[None, :]
    perp = rel - np.outer(rel @ u, u)
    r_perp_max = float(np.max(np.linalg.norm(perp, axis=1)))
    wf = farfield_tilt_phases(pos, u, f_hz)
    ds = np.asarray(d_list_m, dtype=float)
    if ds.size == 0 or np.any(ds <= 0.0):
        raise ValueError("d_list_m 须为非空正距离序列")
    diffs = []
    prods = []
    p_axis = ref + np.outer(ds, u)
    for d_i, p_i in zip(ds, p_axis, strict=True):
        w_f = focusing_phases(pos, p_i, f_hz, reference_compensate=False)
        # 对齐全局相位（除以参考元相位）后比较
        a = w_f / w_f[0]
        b = wf / wf[0]
        phase_diff = np.abs(np.angle(a * np.conj(b)))
        md = float(np.max(np.minimum(phase_diff, 2.0 * math.pi - phase_diff)))
        diffs.append(md)
        scale = k * r_perp_max**2 / (2.0 * d_i)
        prods.append(md / scale if scale > 0.0 else math.inf)
    return {
        "d_list_m": [float(x) for x in ds],
        "max_phase_diff_rad": diffs,
        "first_order_prod": prods,
        "r_perp_max_m": r_perp_max,
    }


# ─── 场图（Green 求和裁判路）─────────────────────────────────────────────────
def focal_field_map(positions_m: Any, weights: Any, eval_points_m: Any,
                    f_hz: Any) -> np.ndarray:
    """标量 Green 场图 E(r) = Σ wₙ·e^{−jk|r−rₙ|}/(4π|r−rₙ|)。

    positions (N,3)、weights (N,) 复激励、eval_points (M,3) → 复场 (M,)。
    r=rₙ 奇异点显式 ValueError（评点不得与阵元重合）。
    """
    pos = _positions_1d(positions_m, "positions_m")
    w = np.asarray(weights, dtype=complex)
    if w.shape != (pos.shape[0],):
        raise ValueError("weights 须与 positions 同长 N")
    pts = _positions_1d(eval_points_m, "eval_points_m")
    k = _wavenumber(f_hz)
    diff = pts[:, None, :] - pos[None, :, :]
    r = np.linalg.norm(diff, axis=2)
    if float(r.min()) <= 0.0:
        raise ValueError("评点与阵元重合（Green 奇异）")
    field = (w[None, :] * np.exp(-1j * k * r) / (4.0 * math.pi * r)).sum(axis=1)
    return field


# ─── OAM 环阵 ────────────────────────────────────────────────────────────────
def oam_ring_excitation(n_elements: Any, mode_l: Any) -> np.ndarray:
    """环阵 OAM 激励 wₙ = exp(j·l·φₙ)/√N（φₙ=2πn/N）。

    返回 (N,) 复激励（√N 归一 → Σ|w|²=1）。
    """
    n = int(n_elements)
    if n < 2:
        raise ValueError("n_elements 必须 >=2")
    mode = int(mode_l)
    phi = 2.0 * math.pi * np.arange(n) / n
    return np.exp(1j * mode * phi) / math.sqrt(n)


def oam_axis_field(n_elements: Any, mode_l: Any, ring_radius_m: Any,
                   f_hz: Any, z_m: Any) -> dict[str, complex]:
    """环阵轴上 (0,0,z) 场：等比求和闭式。

    元等间隔环上：E(z) = Σₙ wₙ·g(Rₙ)，Rₙ=√(R²+z²) 与 n 无关 →
    E = g·Σ wₙ = g·√N·Σ exp(j·2πln/N)。等比求和：l ≢ 0 (mod N) → 0
    （解析零，逐位）；l ≡ 0 (mod N) → √N·g。
    """
    n = int(n_elements)
    if n < 2:
        raise ValueError("n_elements 必须 >=2")
    mode = int(mode_l)
    r_ring = _positive(ring_radius_m, "ring_radius_m")
    z = _nonneg(z_m, "z_m")
    k = _wavenumber(f_hz)
    r_n = math.sqrt(r_ring * r_ring + z * z)
    g = complex(np.exp(-1j * k * r_n)) / (4.0 * math.pi * r_n)
    # 等比求和闭式：Σ exp(j·2πln/N) = √N·(l≡0 mod N ? √N : 0)（解析零）
    s = math.sqrt(n) if (mode % n) == 0 else 0j
    return {"field": g * s, "green": g, "sum_excitation": complex(s)}


def oam_mode_purity(field_phasor_m: Any, mode_l: Any) -> dict[str, float]:
    """环采样场 DFT 模分解 → 模式 l 纯度 = |a_l|²/Σ|a_m|²。

    a_m = (1/N)·Σₙ E(φₙ)·e^{−j·m·φₙ}（DFT 酉性口径）。
    """
    e = np.asarray(field_phasor_m, dtype=complex)
    n = int(e.shape[0])
    if n < 2:
        raise ValueError("field_phasor_m 至少 2 点")
    mode = int(mode_l)
    spec = np.fft.fft(e) / n  # spec[m] = a_m（fft 索引 m ∈ [0,N)，负模折叠）
    power = np.abs(spec) ** 2
    total = float(power.sum())
    if total <= 0.0:
        raise ValueError("场全零，模式纯度无定义")
    idx = mode % n
    purity = float(power[idx]) / total
    return {
        "purity": purity,
        "a_l_abs": float(abs(spec[idx])),
        "total_power": total,
    }


def phase_mode_count(ring_radius_m: Any, f_hz: Any) -> dict[str, float]:
    """圆阵可用相位模数 N_pm = floor(2kR)+1（|m| ≤ kR 的相位模可用口径）。"""
    r = _positive(ring_radius_m, "ring_radius_m")
    k = _wavenumber(f_hz)
    return {
        "n_phase_modes": float(math.floor(2.0 * k * r) + 1),
        "k_per_m": k,
        "kR": k * r,
    }
