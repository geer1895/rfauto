"""B3 腔体微扰频移（TE101 场积分 + 三角网格样品微扰）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

# ─── B3 腔体微扰频移（Pozar §6.7 材料微扰 + Slater 形状微扰）──────────────────
# 口径（铁律 1c：Pozar《Microwave Engineering》§6.7 Cavity Perturbations，
# Slater 定理一阶式；腔体微扰法测 εr 的标准式）：
#   TE101 矩形腔（腔体 [0,a]×[0,b]×[0,d]，n=0 无 y 依赖）：
#     f0 = (c/2)·√(1/a² + 1/d²)，Vc = a·b·d
#     E_y ∝ sin(πx/a)·sin(πz/d)（E 极大在 (a/2, d/2)），
#     |H|² = [sin²(πx/a)cos²(πz/d) + (d/a)²cos²(πx/a)sin²(πz/d)]/(1+(d/a)²)
#       （由 ∇×E 与 Z_TE²=1+(d/a)²（ε0=μ0=1 归一）导出；能量等式
#        ∫μ|H|²dV = ∫ε|E|²dV = ε·Vc/4 在该归一下精确成立）
#   材料微扰（小介质样品，一阶）：Δf/f0 = −(εr−1)/2 · ∫Vs|E0|²dV / ∫Vc|E0|²dV
#   形状微扰（Slater 小金属样品）：Δf/f0 = ½·(∫Vs μ|H0|² − ε|E0|²)dV/∫Vc ε|E0|²dV
#   小样品极限（几何体积表述，∫Vc|E|²=Vc/4 折算）：
#     E 极大点介质样品 → −2(εr−1)·Vs/Vc；金属样品 → −2·Vs/Vc（频率下降）；
#     H 极大区金属样品 → 符号翻正（频率上升）。→ 位移法测 εr / 调谐螺钉
#     「E 区下压、H 区上抬」的标准结论。
# 判据（#118 双裁判）：有限盒样品走 sin²/cos² 原函数解析积分（精确）；
#   任意网格样品走体素奇偶性内点积分，测试做步长收敛 + 小样品极限对照。

def _te101_field_integrals_box(a_mm: float, b_mm: float, d_mm: float,
                               lo: list[float], hi: list[float]) -> dict[str, float]:
    """盒样品的 TE101 场权积分（sin²/cos² 原函数，解析精确）。

    x 向周期 a、z 向周期 d（各自独立），y 向无场变化 → 乘样品 y 长度
    （不是腔高 b——b 只进 ∫Vc 归一）。
    """
    pi = math.pi

    def anti_s(x: float, period: float) -> float:  # ∫sin²(πx/L)dx
        return x / 2.0 - period / (4.0 * pi) * math.sin(2.0 * pi * x / period)

    def anti_c(x: float, period: float) -> float:  # ∫cos²(πx/L)dx
        return x / 2.0 + period / (4.0 * pi) * math.sin(2.0 * pi * x / period)

    sx = anti_s(hi[0], a_mm) - anti_s(lo[0], a_mm)
    cx = anti_c(hi[0], a_mm) - anti_c(lo[0], a_mm)
    sz = anti_s(hi[2], d_mm) - anti_s(lo[2], d_mm)
    cz = anti_c(hi[2], d_mm) - anti_c(lo[2], d_mm)
    y_ext = hi[1] - lo[1]
    i_e = y_ext * sx * sz                         # ∫Vs wE dV
    i_hx = y_ext * sx * cz                        # ∫Vs sin²(x)cos²(z) dV
    i_hz = y_ext * cx * sz                        # ∫Vs cos²(x)sin²(z) dV
    ratio = (d_mm / a_mm) ** 2
    i_h = (i_hx + ratio * i_hz) / (1.0 + ratio)   # ∫Vs |H|² dV（归一）
    return {"i_e": i_e, "i_h": i_h, "sample_volume_mm3":
            (hi[0] - lo[0]) * y_ext * (hi[2] - lo[2])}


def _points_inside_mesh(points: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """体素中心 → 内点掩码（+x 射线 Möller–Trumbore 奇偶性；须水密网格）。

    共享边/顶点命中去重：射线恰穿两三角的公共边时两者在同一 t 命中，
    按 t 去重只计一次穿面（否则奇偶翻转 → 内点误判，实测盒对角线夹具
    8 体素错 4 个）。
    """
    v0 = tris[:, 0, :]
    e1 = tris[:, 1, :] - v0
    e2 = tris[:, 2, :] - v0
    direction = np.array([1.0, 0.0, 0.0])
    h = np.cross(direction, e2)                     # (T,3)，与查询点无关
    a_vec = np.einsum("tk,tk->t", e1, h)            # (T,)：行列式，与点无关
    scale = max(float(np.max(np.abs(tris))), 1.0)
    eps = 1e-12 * scale
    t_tol = 1e-9 * scale
    valid = np.abs(a_vec) > eps
    inv_a = np.where(valid, 1.0 / np.where(valid, a_vec, 1.0), 0.0)
    counts = np.zeros(points.shape[0], dtype=np.int64)
    chunk = 4096
    for start in range(0, points.shape[0], chunk):
        p = points[start:start + chunk]
        s_vec = p[:, None, :] - v0[None, :, :]      # (m,T,3)
        u = np.einsum("mtk,tk->mt", s_vec, h) * inv_a[None, :]
        q = np.cross(s_vec, e1[None, :, :])
        v = q[..., 0] * inv_a[None, :]              # q·direction = q_x
        t = np.einsum("mtk,tk->mt", q, e2) * inv_a[None, :]
        crossing = (valid[None, :] & (u >= 0.0) & (u <= 1.0)
                    & (v >= 0.0) & (u + v <= 1.0) & (t > eps))
        sentinel = 1e30 * scale  # 大有限哨兵（inf 的 diff 会出 nan 告警）
        t_hit = np.sort(np.where(crossing, t, sentinel), axis=1)
        hit_first = t_hit[:, 0] < sentinel
        # 不同 t 的有限命中数 = 1 + 「有限值之间的」跳变数（到哨兵的跳变不算）
        finite_to_finite = t_hit[:, 1:] < sentinel
        distinct_extra = (np.diff(t_hit, axis=1) > t_tol) & finite_to_finite
        counts[start:start + chunk] = (
            hit_first.astype(np.int64) + distinct_extra.sum(axis=1))
    return counts % 2 == 1


@register_calculator(
    "cavity_perturbation_shift",
    "矩形腔 TE101 腔体微扰频移（Pozar §6.7 / Slater 定理一阶）：腔尺寸+样品"
    "（轴对齐盒精确解析，或任意三角网格体素积分）→ f0、Δf/f0。小样品极限："
    "E 极大点介质 −2(εr−1)Vs/Vc、金属 −2Vs/Vc（下调）；H 极大区金属符号翻正",
    (("a_mm", "float mm 腔 x 边长（>0）"),
     ("b_mm", "float mm 腔 y 高（>0，进 Vc 与场权积分）"),
     ("d_mm", "float mm 腔 z 长（>0）"),
     ("sample_box_mm", "array [x0,y0,z0,x1,y1,z1] 轴对齐样品盒（mm，腔内）"),
     ("sample_triangles_mm", "array (n,3,3) 样品水密三角网格（mm，体素路线）"),
     ("sample_eps_r", "float - 样品相对介电常数（>1；缺省=金属微扰路线）"),
     ("voxel_mm", "float mm 体素步长上限（网格路线；缺省自动=样品最大边/24）")),
    required=("a_mm", "b_mm", "d_mm"),
)
def cavity_perturbation_shift(a_mm: float, b_mm: float, d_mm: float,
                              sample_box_mm: list | None = None,
                              sample_triangles_mm: list | None = None,
                              sample_eps_r: float | None = None,
                              voxel_mm: float | None = None) -> dict:
    a = _finite(a_mm, "a_mm")
    b = _finite(b_mm, "b_mm")
    d = _finite(d_mm, "d_mm")
    if a <= 0 or b <= 0 or d <= 0:
        raise ValueError("腔尺寸 a/b/d 必须为正")
    if (sample_box_mm is None) == (sample_triangles_mm is None):
        raise ValueError("sample_box_mm 与 sample_triangles_mm 恰给其一")
    if sample_eps_r is not None:
        eps_r = _finite(sample_eps_r, "sample_eps_r")
        if eps_r <= 1.0:
            raise ValueError("sample_eps_r 必须 >1（介质微扰；εr≤1 无微扰意义）")
        perturbation = "dielectric"
    else:
        eps_r = None
        perturbation = "metal"
    cavity = np.array([a, b, d])
    tol = 1e-9 * max(a, b, d)

    if sample_box_mm is not None:
        raw = [float(v) for v in sample_box_mm]
        if len(raw) != 6 or any(not math.isfinite(v) for v in raw):
            raise ValueError("sample_box_mm 须为 6 个有限数 [x0,y0,z0,x1,y1,z1]")
        lo = [min(raw[0], raw[3]), min(raw[1], raw[4]), min(raw[2], raw[5])]
        hi = [max(raw[0], raw[3]), max(raw[1], raw[4]), max(raw[2], raw[5])]
        if any(hi[k] - lo[k] <= 0.0 for k in range(3)):
            raise ValueError("样品盒三向尺寸必须为正")
        if any(lo[k] < -tol or hi[k] > cavity[k] + tol for k in range(3)):
            raise ValueError(
                f"样品出腔：盒 [{lo}, {hi}] 超出腔 [0, {a}]×[0, {b}]×[0, {d}]")
        integ = _te101_field_integrals_box(a, b, d, lo, hi)
        route = "analytic_box"
        voxel_info: dict[str, Any] = {}
    else:
        from rfauto.core.solid_mesh import solid_mesh_from_triangles

        mesh = solid_mesh_from_triangles(sample_triangles_mm)
        if not mesh.is_watertight:
            raise ValueError("网格路线要求水密样品网格（奇偶性内点判定需闭合面）")
        lo, hi = mesh.bbox_mm
        if any(lo[k] < -tol or hi[k] > cavity[k] + tol for k in range(3)):
            raise ValueError(
                f"样品出腔：网格 bbox [{list(lo)}, {list(hi)}] 超出腔 "
                f"[0, {a}]×[0, {b}]×[0, {d}]")
        extent = np.asarray(hi) - np.asarray(lo)
        if voxel_mm is None:
            step = float(np.max(extent)) / 24.0
        else:
            step = _finite(voxel_mm, "voxel_mm")
            if step <= 0:
                raise ValueError("voxel_mm 必须 >0")
        steps = extent / np.maximum(
            np.ceil(extent / step - 1e-12), 1.0)
        n_cells = np.maximum(np.ceil(extent / step - 1e-12).astype(int), 1)
        if int(np.prod(n_cells)) > 4_000_000:
            raise ValueError(
                f"体素数 {int(np.prod(n_cells))} 超上限 4e6：调大 voxel_mm")
        axes = [lo[k] + (np.arange(n_cells[k]) + 0.5) * steps[k]
                for k in range(3)]
        gx, gy, gz = np.meshgrid(*axes, indexing="ij")
        points = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)
        inside = _points_inside_mesh(points, np.asarray(sample_triangles_mm,
                                                        dtype=float))
        if not bool(np.any(inside)):
            raise ValueError("体素判定网格内部为空（网格退化或步长过粗）")
        pts_in = points[inside]
        i_e = float(np.sum(np.sin(np.pi * pts_in[:, 0] / a) ** 2
                           * np.sin(np.pi * pts_in[:, 2] / d) ** 2)
                    * np.prod(steps))
        ratio2 = (d / a) ** 2
        i_h = float(np.sum(
            (np.sin(np.pi * pts_in[:, 0] / a) ** 2
             * np.cos(np.pi * pts_in[:, 2] / d) ** 2)
            + ratio2 * (np.cos(np.pi * pts_in[:, 0] / a) ** 2
                        * np.sin(np.pi * pts_in[:, 2] / d) ** 2))
            * np.prod(steps) / (1.0 + ratio2))
        sample_volume = float(np.sum(inside) * np.prod(steps))
        mesh_volume = mesh.volume_mm3
        voxel_info = {
            "voxel_mm": round(float(np.max(steps)), 12),
            "voxel_count": int(np.sum(inside)),
            "voxel_vs_mesh_volume_rel_err": round(
                abs(sample_volume - mesh_volume)
                / max(mesh_volume, 1e-30), 9),
        }
        integ = {"i_e": i_e, "i_h": i_h, "sample_volume_mm3": sample_volume}
        route = "voxel_mesh"

    f0_ghz = (C_MM_GHZ / 2.0) * math.sqrt(1.0 / (a * a) + 1.0 / (d * d))
    vc = a * b * d
    weight_cavity = vc / 4.0  # ∫Vc|E0|²dV（E0=E 极大幅值归一）
    if perturbation == "dielectric":
        df_over_f = -(eps_r - 1.0) / 2.0 * integ["i_e"] / weight_cavity
        extra = {"eps_r": eps_r}
    else:
        df_over_f = 0.5 * (integ["i_h"] - integ["i_e"]) / weight_cavity
        extra = {}
    return {"f0_ghz": round(f0_ghz, 9),
            "df_over_f": round(df_over_f, 15),
            "df_ghz": round(f0_ghz * df_over_f, 15),
            "sample_volume_mm3": round(integ["sample_volume_mm3"], 12),
            "cavity_volume_mm3": round(vc, 12),
            "field_weight_ratio": round(integ["i_e"] / weight_cavity, 12),
            "perturbation": perturbation,
            "route": route,
            **extra,
            **voxel_info,
            "note": "口径：Pozar《Microwave Engineering》§6.7 腔体微扰"
                    "（材料微扰式）+ Slater 形状微扰一阶式；TE101 场权 "
                    "sin²(πx/a)sin²(πz/d)，∫Vc|E|²=Vc/4。金属形状因子"
                    "（球/针极化率修正）不在一阶式内（followUp）。"}
