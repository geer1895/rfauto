"""SAR 合规后处理确定性内核（DP-18 C10c）。

职责（铁律 7：数值只在确定性内核；纯 numpy 叶子，无业务依赖）：
- 点值 SAR = σ|E|²/(2ρ)（IEC/IEEE 62704-1 / IEEE 1528 口径，E=**峰值**
  相量 V/m——RMS 输入由调用方自折 √2，本契约显式标注不两可）；
- 固定质量立方平均（1g/10g）：棱长 a=(m/ρ)^{1/3}（1g@1000 kg/m³→10.0 mm、
  10g→21.544 mm），体素中心包含式 SAR_avg=Σ(SARᵢρᵢVᵢ)/Σ(ρᵢVᵢ)，
  积分图（summed-area table）O(N) 实现全网格扫描；
- 立方出体（边界截断）→ 纳入质量<目标，coverage=纳入质量/目标质量如实
  报告。IEEE 62704-1 全量表面"延伸立方补质量"规程本批**简化**（均匀
  phantom/远离体表场景数值等价；体表峰值合规判定需全量规程时如实标注
  简化档，不虚构合规结论）；
- 峰值定位（1g/10g 平均图 argmax）+ 分布分位数（p50/p95/p99）报告面；
- phantom 支持：均匀 / z 向分层简单模型；**Virtual Family 人体模型需
  IT'IS 许可——资产边界：不支持**（显式常量 + 拒绝路径，不虚构兼容）。

与仓内求解器路径的分工：openEMS 已有内联 CalcSAR mass=1g（DumpType 29
原始 dump + IEEE_62704 内联积分，openems_templates 渲染块）；本模块是
**离线后处理**补位——消费 DumpType 29 的 E 场/σ/ρ 体素数据（或任何合成
场），给 1g/10g 双档+峰值定位+分布，不替代求解器内联路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

#: 标准平均质量档（kg）：1g / 10g（IEEE 1528 / IEC 62704-1）
STANDARD_MASS_KG = {"1g": 1e-3, "10g": 1e-2}

#: Virtual Family 人体模型资产边界（IT'IS 许可）——本仓不支持，显式常量
VIRTUAL_FAMILY_SUPPORTED = False

#: 分布分位数码
DISTRIBUTION_PERCENTILES = (50.0, 95.0, 99.0)


# ─── phantom（均匀/分层简单模型；Virtual Family 拒绝）────────────────────────

@dataclass(frozen=True)
class UniformPhantom:
    """均匀 phantom（σ S/m、ρ kg/m³，全局常量）。"""

    sigma: float
    rho: float
    name: str = "uniform"


@dataclass(frozen=True)
class LayeredPhantom:
    """z 向分层 phantom：layers = [(z_lo_m, z_hi_m, sigma, rho, name), ...]。

    分段沿 z 轴左闭右开 [z_lo, z_hi)；覆盖区间外的点显式 ValueError
    （不静默外推）。
    """

    layers: tuple[tuple[float, float, float, float, str], ...]

    def validate(self) -> None:
        if not self.layers:
            raise ValueError("分层 phantom 至少一层")
        for i, (z_lo, z_hi, sigma, rho, _name) in enumerate(self.layers):
            if not (z_hi > z_lo):
                raise ValueError(f"layer[{i}] 空层（z_hi={z_hi} ≤ z_lo={z_lo}）")
            if sigma <= 0.0 or rho <= 0.0:
                raise ValueError(
                    f"layer[{i}] σ/ρ 须为正，收到 σ={sigma}, ρ={rho}")

    def props_on_z(self, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """逐 z 值 σ/ρ（覆盖外点 NaN，由调用方显式拒绝）。"""
        sigma = np.full(np.shape(z), np.nan)
        rho = np.full(np.shape(z), np.nan)
        for z_lo, z_hi, s_v, r_v, _name in self.layers:
            inside = (z >= z_lo) & (z < z_hi)
            sigma[inside] = s_v
            rho[inside] = r_v
        return sigma, rho


def build_phantom(spec: dict[str, Any]) -> UniformPhantom | LayeredPhantom:
    """phantom 规格字典 → 对象（Virtual Family 显式拒绝路径）。"""
    kind = str(spec.get("kind", "")).lower()
    if kind in ("virtual_family", "virtual-family", "vf"):
        raise ValueError(
            "Virtual Family 人体模型需 IT'IS 许可——本仓资产边界不支持"
            "（用 uniform/layered 简单 phantom）")
    if kind == "uniform":
        return UniformPhantom(sigma=float(spec["sigma"]),
                              rho=float(spec["rho"]),
                              name=str(spec.get("name", "uniform")))
    if kind == "layered":
        layers = tuple(
            (float(lo), float(hi), float(s), float(r), str(name))
            for lo, hi, s, r, name in spec["layers"])
        ph = LayeredPhantom(layers=layers)
        ph.validate()
        return ph
    raise ValueError(
        f"phantom kind 须为 uniform/layered/Virtual Family（拒绝），"
        f"收到 {kind!r}")


def phantom_props_grid(
    phantom: UniformPhantom | LayeredPhantom,
    shape: tuple[int, ...],
    z_axis_m: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """网格化 σ/ρ（均匀=常数阵；分层=只随最后一维 z 变化的分段常数阵）。

    z_axis_m：最后一维（z）各体素的物理坐标（m），len == shape[2]——分层
    层界按真实 z 坐标对齐（体素索引不携带物理单位，隐式假设已被否证）。
    覆盖外的 z（层间隙/越界）显式 ValueError（不静默 NaN 不外推）。
    """
    if len(shape) != 3:
        raise ValueError(f"phantom 网格须 3D，收到 shape={shape}")
    if isinstance(phantom, UniformPhantom):
        sigma = np.full(shape, float(phantom.sigma))
        rho = np.full(shape, float(phantom.rho))
        return sigma, rho
    if z_axis_m is None:
        raise ValueError(
            "分层 phantom 必须给 z_axis_m（各 z 体素物理坐标，m）——"
            "层界按真实坐标对齐，不猜索引尺度")
    z = np.asarray(z_axis_m, dtype=float)
    if z.shape != (shape[2],):
        raise ValueError(
            f"z_axis_m 长度 {z.shape} ≠ shape[2]={shape[2]}")
    if not (np.diff(z) > 0).all():
        raise ValueError("z_axis_m 须严格升序")
    sigma_z, rho_z = phantom.props_on_z(z)
    if np.isnan(sigma_z).any():
        bad = int(np.flatnonzero(np.isnan(sigma_z))[0])
        raise ValueError(
            f"z={z[bad]:.6g} m 未被任何层覆盖（分层间隙/越界显式拒绝，"
            "不外推）")
    lead = (1, 1)
    sigma = np.broadcast_to(sigma_z.reshape((*lead, z.size)), shape).copy()
    rho = np.broadcast_to(rho_z.reshape((*lead, z.size)), shape).copy()
    return sigma, rho


# ─── 点值 SAR ────────────────────────────────────────────────────────────────

def sar_pointwise(sigma: np.ndarray, e_peak: np.ndarray,
                  rho: np.ndarray) -> np.ndarray:
    """点值 SAR = σ|E|²/(2ρ)（W/kg）。

    e_peak：峰值相量幅度（V/m）——复相量或实幅度均可（取 |·|²）；
    σ/ρ 广播对齐 E 网格。ρ≤0 处除零 → 如实 Inf/NaN（调用方网格治理）。
    """
    s = np.asarray(sigma, dtype=float)
    e2 = np.abs(np.asarray(e_peak)) ** 2
    r = np.asarray(rho, dtype=float)
    return s * e2 / (2.0 * r)


# ─── 固定质量立方平均（体素中心包含式 + 积分图 O(N)）─────────────────────────

def cube_side_m(mass_kg: float, rho: float) -> float:
    """固定质量立方棱长 a=(m/ρ)^{1/3}（m）。1g@1000→0.010、10g→0.021544..."""
    if mass_kg <= 0.0:
        raise ValueError(f"mass_kg 须为正，收到 {mass_kg}")
    if rho <= 0.0:
        raise ValueError(f"rho 须为正，收到 {rho}")
    return (mass_kg / rho) ** (1.0 / 3.0)


def _sat(arr: np.ndarray) -> np.ndarray:
    """summed-area table（含前导零行/列，便于差分取窗和）。"""
    pad = np.zeros((arr.shape[0] + 1, arr.shape[1] + 1, arr.shape[2] + 1))
    pad[1:, 1:, 1:] = arr
    return pad.cumsum(0).cumsum(1).cumsum(2)


def _win_sums(w_num: np.ndarray, w_den: np.ndarray, nx: int, ny: int,
              nz: int) -> tuple[np.ndarray, np.ndarray]:
    """3D 全网格"中心包含立方"窗和（分子 Σ sar·ρ·V、分母 Σ ρ·V）。

    边界截断：立方超出网格侧截到网格内（纳入质量语义，coverage<1 如实）。
    实现：前缀和差分（8 角点容斥），O(N)。与 sar_cube_average 的切片
    路径同口径（同起算规则 lo=max(0,i−nx//2)），测试以暴力重扫互证。
    """
    sn = _sat(w_num)
    sd = _sat(w_den)
    ni, nj, nk = w_num.shape

    def _diff(s: np.ndarray) -> np.ndarray:
        i0 = np.clip(np.arange(ni) - nx // 2, 0, ni)
        i1 = np.minimum(i0 + nx, ni)
        j0 = np.clip(np.arange(nj) - ny // 2, 0, nj)
        j1 = np.minimum(j0 + ny, nj)
        k0 = np.clip(np.arange(nk) - nz // 2, 0, nk)
        k1 = np.minimum(k0 + nz, nk)
        a = i0[:, None, None]
        b = i1[:, None, None]
        c = j0[None, :, None]
        d = j1[None, :, None]
        e = k0[None, None, :]
        f = k1[None, None, :]
        # 容斥（[a,b)×[c,d)×[e,f) 窗和，SAT 差分 8 角点）
        return (s[b, d, f] - s[a, d, f] - s[b, c, f] - s[b, d, e]
                + s[a, c, f] + s[a, d, e] + s[b, c, e] - s[a, c, e])

    return _diff(sn), _diff(sd)


def sar_average_map(sar: np.ndarray, rho: np.ndarray,
                    voxel_m: tuple[float, float, float] | float,
                    mass_kg: float) -> dict[str, Any]:
    """全网格固定质量立方平均图（1g/10g 扫描平均主入口）。

    voxel_m：各轴体素尺寸（标量=各向同性）；棱长 a=(mass/ρ̄)^{1/3} 以网格
    多数 ρ 计（均匀 phantom 精确；分层场景 a 用全局中位 ρ——与 62704 的
    逐点密度立方差异在注记中显式说明）；窗体素数 max(1, round(a/Δ))。
    返回 {avg, coverage, included_mass_kg, side_m, n_voxels}（coverage=
    峰值点纳入质量/目标质量，最坏体素语义）。
    """
    sar_g = np.asarray(sar, dtype=float)
    rho_g = np.asarray(rho, dtype=float)
    if sar_g.shape != rho_g.shape or sar_g.ndim != 3:
        raise ValueError(
            f"sar/rho 须同形 3D，收到 {sar_g.shape} vs {rho_g.shape}")
    if not (mass_kg > 0.0):
        raise ValueError(f"mass_kg 须为正，收到 {mass_kg}")
    if np.isscalar(voxel_m):
        vx = vy = vz = float(voxel_m)  # type: ignore[arg-type]
    else:
        vx, vy, vz = (float(v) for v in voxel_m)  # type: ignore[misc]
    if min(vx, vy, vz) <= 0.0:
        raise ValueError("体素尺寸须为正")
    rho_med = float(np.median(rho_g))
    side = cube_side_m(mass_kg, rho_med)
    nx = max(1, round(side / vx))
    ny = max(1, round(side / vy))
    nz = max(1, round(side / vz))
    voxel_v = vx * vy * vz
    w_num = sar_g * rho_g * voxel_v
    w_den = rho_g * voxel_v
    s_num, s_den = _win_sums(w_num, w_den, nx, ny, nz)
    with np.errstate(invalid="ignore", divide="ignore"):
        avg = s_num / s_den
    # coverage：分母质量 / 目标质量（最坏=全场最小纳入质量点）
    mass_map = s_den
    coverage_min = float(mass_map.min()) / mass_kg
    return {
        "avg": avg,
        "side_m": (nx * vx, ny * vy, nz * vz),
        "n_voxels": (nx, ny, nz),
        "coverage_min": coverage_min,
        "target_mass_kg": float(mass_kg),
        "rho_ref_kg_m3": rho_med,
    }


def sar_cube_average(sar: np.ndarray, rho: np.ndarray,
                     voxel_m: tuple[float, float, float] | float,
                     center: tuple[int, int, int],
                     mass_kg: float) -> dict[str, Any]:
    """单点固定质量立方平均（与 sar_average_map 同口径，切片直算）。"""
    sar_g = np.asarray(sar, dtype=float)
    rho_g = np.asarray(rho, dtype=float)
    if sar_g.shape != rho_g.shape or sar_g.ndim != 3:
        raise ValueError("sar/rho 须同形 3D")
    if np.isscalar(voxel_m):
        vx = vy = vz = float(voxel_m)  # type: ignore[arg-type]
    else:
        vx, vy, vz = (float(v) for v in voxel_m)  # type: ignore[misc]
    rho_med = float(np.median(rho_g))
    side = cube_side_m(mass_kg, rho_med)
    nx = max(1, round(side / vx))
    ny = max(1, round(side / vy))
    nz = max(1, round(side / vz))
    ci, cj, ck = (int(v) for v in center)
    lo = (max(0, ci - nx // 2), max(0, cj - ny // 2), max(0, ck - nz // 2))
    hi = (min(sar_g.shape[0], lo[0] + nx),
          min(sar_g.shape[1], lo[1] + ny),
          min(sar_g.shape[2], lo[2] + nz))
    box_n = sar_g[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
    box_d = rho_g[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
    v_ = vx * vy * vz
    den = float((box_d * v_).sum())
    num = float((box_n * box_d * v_).sum())
    avg = num / den if den > 0.0 else float("nan")
    return {
        "avg": avg,
        "included_mass_kg": den,
        "coverage": den / mass_kg,
        "side_m": (nx * vx, ny * vy, nz * vz),
        "n_voxels": (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]),
        "target_mass_kg": float(mass_kg),
    }


# ─── 峰值定位 + 分布报告面 ────────────────────────────────────────────────────

def sar_report(sar: np.ndarray, rho: np.ndarray,
               voxel_m: tuple[float, float, float] | float,
               mass_kg_list: tuple[float, ...] = (1e-3, 1e-2),
               voxel_origin_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
               ) -> dict[str, Any]:
    """SAR 合规后处理报告（点值 + 各质量档 1g/10g 平均 + 峰值定位 + 分布）。

    返回 JSON 可序列化 dict（数值已转 Python 标量/列表）：
    {pointwise:{max,location_voxel,location_m}, masses:[{mass_kg,
    sar_max_avg,location_voxel,location_m,coverage_at_peak,...}],
    distribution:{p50,p95,p99,max}}。
    """
    sar_g = np.asarray(sar, dtype=float)
    rho_g = np.asarray(rho, dtype=float)
    if sar_g.shape != rho_g.shape or sar_g.ndim != 3:
        raise ValueError("sar/rho 须同形 3D")
    if sar_g.size == 0:
        raise ValueError("空网格")
    if np.isscalar(voxel_m):
        vx = vy = vz = float(voxel_m)  # type: ignore[arg-type]
    else:
        vx, vy, vz = (float(v) for v in voxel_m)  # type: ignore[misc]
    idx = np.unravel_index(int(np.argmax(sar_g)), sar_g.shape)
    point = {
        "max": float(sar_g[idx]),
        "location_voxel": [int(v) for v in idx],
        "location_m": [voxel_origin_m[0] + vx * idx[0],
                       voxel_origin_m[1] + vy * idx[1],
                       voxel_origin_m[2] + vz * idx[2]],
    }
    masses: list[dict[str, Any]] = []
    for mass_kg in mass_kg_list:
        m = sar_average_map(sar_g, rho_g, (vx, vy, vz), mass_kg)
        avg = m["avg"]
        mi = np.unravel_index(int(np.nanargmax(avg)), avg.shape)
        masses.append({
            "mass_kg": float(mass_kg),
            "sar_max_avg": float(avg[mi]),
            "location_voxel": [int(v) for v in mi],
            "location_m": [voxel_origin_m[0] + vx * mi[0],
                           voxel_origin_m[1] + vy * mi[1],
                           voxel_origin_m[2] + vz * mi[2]],
            "side_m": list(m["side_m"]),
            "n_voxels": list(m["n_voxels"]),
            "coverage_at_peak": float(
                sar_cube_average(sar_g, rho_g, (vx, vy, vz), mi,
                                 mass_kg)["coverage"]),
        })
    finite = sar_g[np.isfinite(sar_g)]
    dist = {f"p{p:g}": float(np.percentile(finite, p))
            for p in DISTRIBUTION_PERCENTILES}
    dist["max"] = float(finite.max()) if finite.size else float("nan")
    return {
        "pointwise": point,
        "masses": masses,
        "distribution": dist,
        "conventions": {
            "e_input": "peak phasor (V/m)；RMS 输入请先 ×√2",
            "pointwise": "SAR = σ|E|²/(2ρ)",
            "averaging": "fixed-mass cube, voxel-center inclusion "
                         "(IEEE 1528 / IEC 62704-1 简化档：体表延伸补质量"
                         "规程未实现，coverage 如实报告)",
            "virtual_family": "NOT SUPPORTED（IT'IS 许可资产边界）",
        },
    }
