"""NX-6 共形阵（柱面/球面切平面）阵因子闭式面。

规格：研究扩充 round14 §四 NX-6——"柱/球面
局部切平面+模式展开（Balanis Ch.6）"。纯闭式叶子，零 IO、不进
calculators。

模块面
------
- ``cylindrical_positions``：柱面（圆环带）阵元布点（z 向排 + 方位向排，
  元法向=径向）。
- ``spherical_cap_positions``：球冠阵元布点（θ-φ 网格截断，元法向=径向）。
- ``conformal_array_factor``：共形阵因子——逐元切平面近似：
  AF(û) = Σ wₙ·EF_n(û)·exp(j·k·û·rₙ)，EF_n = max(0, cos ψ)^q
  （cos^q 元方向图，ψ = û 与元法向夹角；ψ>90° 元被遮挡置零——局部
  切平面口径的标准处理，Balanis Ch.6 口径名）。
- ``planar_degeneracy_af``：平面阵参照（同点集、法向=+z）——R→∞ 时
  共形阵与平面阵一致（结构锚）。
- ``phase_mode_count``：圆环可用相位模数 N_pm = floor(2kR)+1（模式
  展开/模数口径；与 nf_focusing_oam.phase_mode_count 同式异消费——
  本模块自实现 + 单测跨模块互证）。
- ``ring_mode_decomposition``：环激励的相位模 DFT 分解（模式展开面）。

物理口径（e^{+jωt}、前向波 e^{−jk·r}；全 SI）
------------------------------------------------
* 切平面近似：曲面上元视为切平面上的元，方向图以元局部法向定义；
  忽略元间曲率耦合与极化旋转（一阶口径，如实声明）。
* 设计约束：numpy 纯函数；非法输入显式 ValueError；dict 输出 JSON 可
  序列化（数组注明）。

出处
----
1. round 文档：round14 §四 NX-6。
2. Balanis "Antenna Theory" 4th ed. Ch.6（阵列/柱面阵与模式展开口径名，
   页码 UNVERIFIED 如实，#122）。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = [
    "BALANIS_SOURCE",
    "C0_M_S",
    "conformal_array_factor",
    "cylindrical_positions",
    "phase_mode_count",
    "planar_degeneracy_af",
    "ring_mode_decomposition",
    "spherical_cap_positions",
]

C0_M_S = 299792458.0
BALANIS_SOURCE = (
    "Balanis Antenna Theory 4th Ch.6（柱面阵切平面/相位模口径名）；"
    "页码 UNVERIFIED（#122 如实）"
)


def _wavenumber(f_hz: Any) -> float:
    f = float(f_hz)
    if not math.isfinite(f) or f <= 0.0:
        raise ValueError(f"f_hz 必须为正有限数，实际 {f_hz!r}")
    return 2.0 * math.pi * f / C0_M_S


def _check_z_extent(z_extent_m: Any) -> float:
    z = float(z_extent_m)
    if not math.isfinite(z) or z <= 0.0:
        raise ValueError(f"z_extent_m 必须为正有限数，实际 {z_extent_m!r}")
    return z


def cylindrical_positions(radius_m: Any, n_az: Any, n_z: Any,
                          z_extent_m: Any, f_hz: Any,
                          az_start_rad: Any = 0.0,
                          az_span_rad: Any = 2.0 * math.pi) -> dict[str, Any]:
    """柱面阵元布点：方位向 n_az × z 向 n_z，元法向=径向外。

    az_span=2π 全环（含首尾重合去重：末点=首点+span 时末点去除）；
    部分弧（span<2π）含两端点。z 向均匀 [-z/2, +z/2]。
    返回 {positions_m:(N,3), normals_m:(N,3), radius_m, k_per_m}。
    """
    r = float(radius_m)
    if not math.isfinite(r) or r <= 0.0:
        raise ValueError(f"radius_m 必须为正有限数，实际 {radius_m!r}")
    n_a, n_zi = int(n_az), int(n_z)
    if n_a < 2 or n_zi < 1:
        raise ValueError("n_az>=2 且 n_z>=1")
    z_ext = _check_z_extent(z_extent_m)
    k = _wavenumber(f_hz)
    span = float(az_span_rad)
    if not (0.0 < span <= 2.0 * math.pi + 1e-15):
        raise ValueError("az_span_rad 须 (0, 2π]")
    az = 2.0 * math.pi * np.arange(n_a) / n_a \
        if span >= 2.0 * math.pi - 1e-15 else np.linspace(0.0, span, n_a)
    az = az + float(az_start_rad)
    zs = np.linspace(-z_ext / 2.0, z_ext / 2.0, n_zi)
    aa, zz = np.meshgrid(az, zs, indexing="ij")
    pos = np.stack([r * np.cos(aa), r * np.sin(aa), zz], axis=-1).reshape(-1, 3)
    normals = np.stack([np.cos(aa), np.sin(aa), np.zeros_like(aa)],
                       axis=-1).reshape(-1, 3)
    return {"positions_m": pos, "normals_m": normals, "radius_m": r,
            "k_per_m": k}


def spherical_cap_positions(radius_m: Any, theta_max_rad: Any, n_theta: Any,
                            n_phi: Any, f_hz: Any) -> dict[str, Any]:
    """球冠阵元布点：θ∈[0,θ_max]、φ 全环，元法向=径向外。

    返回 {positions_m:(N,3), normals_m:(N,3), radius_m, k_per_m}。
    """
    r = float(radius_m)
    if not math.isfinite(r) or r <= 0.0:
        raise ValueError(f"radius_m 必须为正有限数，实际 {radius_m!r}")
    tmax = float(theta_max_rad)
    if not (0.0 < tmax <= math.pi):
        raise ValueError("theta_max_rad 须 (0, π]")
    n_t, n_p = int(n_theta), int(n_phi)
    if n_t < 1 or n_p < 2:
        raise ValueError("n_theta>=1 且 n_phi>=2")
    k = _wavenumber(f_hz)
    th = np.linspace(0.0, tmax, n_t)
    ph = 2.0 * math.pi * np.arange(n_p) / n_p
    tt, pp = np.meshgrid(th, ph, indexing="ij")
    st, ct = np.sin(tt), np.cos(tt)
    pos = np.stack([r * st * np.cos(pp), r * st * np.sin(pp), r * ct],
                   axis=-1).reshape(-1, 3)
    normals = np.stack([st * np.cos(pp), st * np.sin(pp), ct],
                       axis=-1).reshape(-1, 3)
    return {"positions_m": pos, "normals_m": normals, "radius_m": r,
            "k_per_m": k}


def conformal_array_factor(positions_m: Any, normals_m: Any, weights: Any,
                           direction_m: Any, f_hz: Any,
                           element_pattern_exp: Any = 1.0) -> dict[str, Any]:
    """共形阵因子（切平面 + cos^q 元方向图 + 90° 遮挡）。

    AF(û) = Σ wₙ·max(0, cosψₙ)^q·exp(j k û·rₙ)，ψₙ=∠(û, 法向ₙ)；
    cosψₙ≤0（背向）置零。q=0 → 全向元（不置零背向？不——遮挡语义
    保留：q=0 时背向元贡献 0^0=1 但仍被遮挡规则置零，与 q 语义独立）。
    返回 {af_complex, af_abs, n_active, n_total}。
    """
    pos = np.asarray(positions_m, dtype=float)
    nor = np.asarray(normals_m, dtype=float)
    w = np.asarray(weights, dtype=complex)
    if pos.ndim != 2 or pos.shape[1] != 3:
        raise ValueError("positions_m 须为 (N,3)")
    if nor.shape != pos.shape:
        raise ValueError("normals_m 须与 positions_m 同形 (N,3)")
    if w.shape != (pos.shape[0],):
        raise ValueError("weights 须与 positions_m 同长")
    q = float(element_pattern_exp)
    if q < 0.0:
        raise ValueError("element_pattern_exp 须非负")
    u = np.asarray(direction_m, dtype=float)
    if u.shape != (3,):
        raise ValueError("direction_m 须为长度 3")
    norm = float(np.linalg.norm(u))
    if norm == 0.0:
        raise ValueError("direction_m 不得为零向量")
    u = u / norm
    k = _wavenumber(f_hz)
    cos_psi = nor @ u
    active = cos_psi > 0.0
    ef = np.where(active, np.maximum(cos_psi, 0.0) ** q, 0.0)
    af = complex(np.sum(w * ef * np.exp(1j * k * (pos @ u))))
    return {
        "af_complex": af,
        "af_abs": abs(af),
        "n_active": int(np.count_nonzero(active)),
        "n_total": int(pos.shape[0]),
    }


def planar_degeneracy_af(positions_m: Any, weights: Any, direction_m: Any,
                         f_hz: Any) -> complex:
    """平面阵参照 AF（法向全 +z、无遮挡）：Σ wₙ exp(jkû·rₙ)（互证锚用）。"""
    pos = np.asarray(positions_m, dtype=float)
    w = np.asarray(weights, dtype=complex)
    if pos.ndim != 2 or pos.shape[1] != 3:
        raise ValueError("positions_m 须为 (N,3)")
    if w.shape != (pos.shape[0],):
        raise ValueError("weights 须与 positions_m 同长")
    u = np.asarray(direction_m, dtype=float)
    if u.shape != (3,):
        raise ValueError("direction_m 须为长度 3")
    norm = float(np.linalg.norm(u))
    if norm == 0.0:
        raise ValueError("direction_m 不得为零向量")
    u = u / norm
    k = _wavenumber(f_hz)
    return complex(np.sum(w * np.exp(1j * k * (pos @ u))))


def phase_mode_count(ring_radius_m: Any, f_hz: Any) -> dict[str, float]:
    """圆环可用相位模数 N_pm = floor(2kR)+1（|m|≤kR 相位模可用口径）。"""
    r = float(ring_radius_m)
    if not math.isfinite(r) or r <= 0.0:
        raise ValueError(f"ring_radius_m 必须为正有限数，实际 {ring_radius_m!r}")
    k = _wavenumber(f_hz)
    return {"n_phase_modes": float(math.floor(2.0 * k * r) + 1.0),
            "k_per_m": k, "kR": k * r}


def ring_mode_decomposition(ring_weights: Any) -> np.ndarray:
    """环激励相位模 DFT 分解 a_m = (1/N)·Σₙ wₙ·e^{−j2πmn/N}（酉 DFT 口径）。"""
    w = np.asarray(ring_weights, dtype=complex)
    if w.ndim != 1 or w.size < 2:
        raise ValueError("ring_weights 须为长度>=1 的一维数组")
    return np.fft.fft(w) / w.size
