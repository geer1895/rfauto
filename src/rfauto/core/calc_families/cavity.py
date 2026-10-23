"""B3 腔体微扰频移（TE101 场积分 + 三角网格样品微扰）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动；aurora_j W4-S12 原位扩展 cavity_tm010_perturbation_shift TM010 圆柱腔键 2026-10-23）。

出处（一阶腔微扰定理，内核 core/material_characterization.py MA-2 转录）：
- cavity_perturbation_shift：一阶腔体微扰定理 εr′/tanδ 反演
  （Waldron/Harrington 标准式；二级转引 L. F. Chen et al.,
  Microwave Electronics: Measurement and Materials Characterization,
  2004 腔微扰测量章）。

─── cavity_tm010_perturbation_shift（aurora_j W4-S12，2026-10-23）─────────

TM010 圆柱腔介质测量键（轴上细杆样品正反解+Q 面）。物理口径（铁律 1c/
#300；式号级来源见键 docstring/source）：

- 空腔谐振：f0 = x01·c/(2πa)，x01=J0 第一零点=2.4048256（工程惯用圆整
  2.405；scipy jn_zeros 单源）。TM010 无 z 依赖（p=0），场 Ez=E0·J0
  (x01·r/a) 轴上极大。
- 一阶材料微扰定理（Slater 1946 Rev. Mod. Phys. 18:441 / Waldron 1960
  同族；Pozar §6.7 腔微扰同式）：
      Δf/f0 = −(εr′−1)/2 · ∫Vs|E0|²dV / ∫Vc|E0|²dV
- TM010 填充因子（本键精确式，超越"细杆轴上 E 场均匀"近似档）：
      ∫0^rs J0²(kr)·r·dr = (rs²/2)·[J0²(k·rs)+J1²(k·rs)]（Bessel 恒等
      式，k=x01/a）→ ∫Vs|E0|² = π·rs²·hs·[J0²(krs)+J1²(krs)]·E0²；
      ∫Vc|E0|² = π·a²·h·J1²(x01)·E0²
      → F = rs²·hs·[J0²(krs)+J1²(krs)] / (a²·h·J1²(x01))
  细杆极限 rs≪a → F ≈ (Vs/Vc)/J1²(x01)。J1²(x01)=0.269514、2J1²=0.539028
  ——文献通行 TM010 测量式的 0.269/0.539 几何常数即此（多源独立核实：
  Alekajbaf-Dancila 2024 Int. J. Microw. Wirel. Technol. 16(10):1665-1670
  DOI 10.1017/S1759078724000308 式(1)-(3) 逐字给出 ε′=1+0.539·(Vc/Vs)·
  (f0−fs)/f0、ε″=0.269·(Vc/Vs)·(1/QLs−1/QL)；MSI 工程页同值注记"0.539
  arises from Bessel function analysis"）。
- 正解：Δf/f0 = −(εr′−1)·F/2（εr′ 已知→频移）；反解：εr′ = 1 −
  2·(Δf/f0)/F（实测频移→εr′，Δf<0 必有 εr′>1）。f0/f_s 分母约定：
  分母取空腔 f0（二级源式(1) 同口径；Δf/f0≪1 时与 /fs 二阶等价），本键
  跟随。
- Q 面（介质损耗）：1/Qs − 1/Q0 = εr″·F（样品耗散/储能比能量恒等式推
  导，P_sample=(ωε0εr″/2)∫Vs|E|²）→ 正解 Qs = 1/(1/Q0 + εr′·tanδ·F)；
  反解 εr″ = (1/Qs−1/Q0)/F、tanδ = εr″/εr′。ε″ 式无 ε′ 因子（能量比
  恒等式，与文献 0.269 系数式逐字同构）。
- L.F. Chen et al. 2004 书页式号：公开源不可逐位核实（书不在手边、网
  源仅转引不带书内式号）——按 #df6-⑬ citation rot 纪律**不落书内式号**，
  以上述可核验二级源（DOI 逐字式+多源系数互证）落档；与既有
  cavity_perturbation_shift（TE101 矩形腔）同定理异几何，边界互指。"""

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
    "腔体微扰法：矩形腔 TE101 腔体微扰频移（Pozar §6.7 / Slater 定理一阶）：腔尺寸+样品"
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


# ─── TM010 圆柱腔介质测量键（aurora_j W4-S12，2026-10-23；物理口径与
# ─── 来源注记见模块 docstring「cavity_tm010_perturbation_shift」节）──────────

def _tm010_field_ratio(x01: float, a_m: float, h_m: float, rs_m: float,
                       hs_m: float) -> float:
    """TM010 填充因子 F=∫Vs|E0|²/∫Vc|E0|²（轴上同轴杆，Bessel 恒等式精确）。

    Ez=E0·J0(k·r)、k=x01/a；∫0^rs J0²(kr)·r·dr=(rs²/2)[J0²(krs)+J1²(krs)]；
    ∫Vc|E|²=πa²h·J1²(x01)·E0²。细杆极限 rs≪a 退化为 (Vs/Vc)/J1²(x01)。
    """
    from scipy.special import j0, j1

    kr = x01 / a_m * rs_m
    int_vs = math.pi * rs_m * rs_m * hs_m * (
        float(j0(kr)) ** 2 + float(j1(kr)) ** 2)
    int_vc = math.pi * a_m * a_m * h_m * float(j1(x01)) ** 2
    return int_vs / int_vc


@register_calculator(
    "cavity_tm010_perturbation_shift",
    "TM010 圆柱腔微扰介质测量：轴上细杆样品一阶微扰正反解（f0=x01·c/2πa、"
    "x01=2.4048；填充因子 F 含 J0²+J1² Bessel 恒等式精确场权，细杆极限="
    "文献 0.539/0.269 几何常数式）；εr′↔Δf 恰给其一（正解/反解互斥），"
    "Q 面可选（tanδ+Q0→Qs / Qs+Q0→εr″·tanδ）；εr′≤1 或 Δf≤0 非物理显式"
    "拒绝；与 cavity_perturbation_shift（TE101 矩形腔）同定理异几何",
    (("a_mm", "float mm 腔半径（>0）"),
     ("h_mm", "float mm 腔高（>0）"),
     ("sample_radius_mm", "float mm 轴上样品杆半径（0<rs<a）"),
     ("sample_height_mm", "float mm 样品高（0<hs≤h；TM010 无 z 依赖，"
      "取样体积即可）"),
     ("epsilon_r", "float - 样品相对介电常数（正解方向，>1；与 df_ghz "
      "恰给其一）"),
     ("df_ghz", "float GHz 实测频移 f_loaded−f_empty（反解方向，<0；与 "
      "epsilon_r 恰给其一）"),
     ("tan_delta", "float - 样品损耗正切（正解 Q 面，须配 q_empty；≥0）"),
     ("q_empty", "float - 空腔无载 Q（Q 面必配项，>0）"),
     ("q_sample", "float - 加载腔无载 Q（反解 Q 面，>0，与 tan_delta 恰"
      "给其一）")),
    required=("a_mm", "h_mm", "sample_radius_mm", "sample_height_mm"),
)
def cavity_tm010_perturbation_shift(
    a_mm: float, h_mm: float, sample_radius_mm: float,
    sample_height_mm: float, epsilon_r: float | None = None,
    df_ghz: float | None = None, tan_delta: float | None = None,
    q_empty: float | None = None, q_sample: float | None = None,
) -> dict:
    """TM010 腔微扰介质测量正反解（物理口径与式号级注记见模块 docstring
    TM010 节）。

    出处（一阶腔微扰定理 TM010 几何面）：
    文献通行 TM010 测量式 εr′=1+0.539·(Vc/Vs)·(f0−fs)/f0、ε″=0.269·
    (Vc/Vs)·(1/QLs−1/QL)——Alekajbaf-Dancila 2024 Int. J. Microw. Wirel.
    Technol. 16(10):1665-1670 式(1)-(3) DOI 10.1017/S1759078724000308
    逐字核对；一般定理同 Pozar Microwave Engineering §6.7/Slater 1946
    （既有 cavity_perturbation_shift 同源）；Chen et al. 2004 书页式号
    不可核按 #df6-⑬ 不落。
    """
    from scipy.special import j1, jn_zeros

    tag = "cavity_tm010_perturbation_shift"
    a = _finite(a_mm, f"{tag}.a_mm")
    h = _finite(h_mm, f"{tag}.h_mm")
    rs = _finite(sample_radius_mm, f"{tag}.sample_radius_mm")
    hs = _finite(sample_height_mm, f"{tag}.sample_height_mm")
    if a <= 0.0:
        raise ValueError(f"{tag}: a_mm 必须 >0，得到 {a_mm!r}")
    if h <= 0.0:
        raise ValueError(f"{tag}: h_mm 必须 >0，得到 {h_mm!r}")
    if not 0.0 < rs < a:
        raise ValueError(
            f"{tag}: sample_radius_mm 必须在 (0, a_mm)（样品须细杆在腔内），"
            f"得到 rs={rs!r}, a={a!r}")
    if not 0.0 < hs <= h:
        raise ValueError(
            f"{tag}: sample_height_mm 必须在 (0, h_mm]，得到 {hs!r}")
    if (epsilon_r is None) == (df_ghz is None):
        raise ValueError(
            f"{tag}: epsilon_r 与 df_ghz 必须恰给其一（正解/反解互斥；双给"
            "或缺给均显式拒绝）")

    a_m, h_m, rs_m, hs_m = a * 1e-3, h * 1e-3, rs * 1e-3, hs * 1e-3
    x01 = float(jn_zeros(0, 1)[0])
    j1_sq = float(j1(x01)) ** 2
    f0_ghz = C_MM_GHZ * x01 / (2.0 * math.pi * a)
    fill = _tm010_field_ratio(x01, a_m, h_m, rs_m, hs_m)
    out: dict[str, Any] = {
        "x01": round(x01, 15),
        "f0_ghz": round(f0_ghz, 12),
        "j1_sq_x01": round(j1_sq, 15),
        "two_j1_sq": round(2.0 * j1_sq, 15),
        "filling_factor": round(fill, 15),
        "sample_volume_mm3": round(math.pi * rs * rs * hs, 12),
        "cavity_volume_mm3": round(math.pi * a * a * h, 12),
        "route": None,
        "epsilon_r": None,
        "df_ghz": None,
        "df_over_f": None,
    }

    if epsilon_r is not None:
        eps = _finite(epsilon_r, f"{tag}.epsilon_r")
        if eps <= 1.0:
            raise ValueError(
                f"{tag}: epsilon_r 必须 >1（介质微扰；εr≤1 无微扰意义），"
                f"得到 {epsilon_r!r}")
        df_over_f = -(eps - 1.0) / 2.0 * fill
        out.update({"route": "forward_shift", "epsilon_r": eps,
                    "df_over_f": round(df_over_f, 18),
                    "df_ghz": round(f0_ghz * df_over_f, 15)})
    else:
        df = _finite(df_ghz, f"{tag}.df_ghz")
        if df >= 0.0:
            raise ValueError(
                f"{tag}: df_ghz 必须 <0（介质样品使谐振频率下降；df≥0 非"
                f"物理），得到 {df_ghz!r}")
        df_over_f = df / f0_ghz
        eps_inv = 1.0 - 2.0 * df_over_f / fill
        if eps_inv <= 1.0:
            raise ValueError(
                f"{tag}: 反解 epsilon_r={eps_inv!r} ≤1 非物理（频移量与填"
                "充因子不自洽——检查样品体积/频移测量），显式拒绝")
        out.update({"route": "inverse_eps_r",
                    "df_over_f": round(df_over_f, 18),
                    "df_ghz": round(df, 15), "epsilon_r": round(eps_inv, 15)})

    if (tan_delta is not None) and (q_sample is not None):
        raise ValueError(
            f"{tag}: tan_delta 与 q_sample 必须恰给其一（Q 面正解/反解互斥"
            "；双给显式拒绝）")
    if q_sample is not None and q_empty is None:
        raise ValueError(
            f"{tag}: q_sample 反解须同时给 q_empty（Δ(1/Q) 口径需要空腔基"
            "准），显式拒绝")
    if tan_delta is not None and q_empty is None:
        raise ValueError(
            f"{tag}: tan_delta 正解须同时给 q_empty（1/Qs=1/Q0+εr″F 口径"
            "需要空腔基准），显式拒绝")
    if q_empty is not None:
        q0 = _finite(q_empty, f"{tag}.q_empty")
        if q0 <= 0.0:
            raise ValueError(f"{tag}: q_empty 必须 >0，得到 {q_empty!r}")
        eps_for_q = (epsilon_r if epsilon_r is not None else eps_inv)
        if tan_delta is not None:
            td = _finite(tan_delta, f"{tag}.tan_delta")
            if td < 0.0:
                raise ValueError(
                    f"{tag}: tan_delta 必须 ≥0，得到 {tan_delta!r}")
            qs = 1.0 / (1.0 / q0 + eps_for_q * td * fill)
            out.update({"q_empty": q0, "tan_delta": td,
                        "q_sample": round(qs, 12),
                        "delta_inv_q": round(1.0 / qs - 1.0 / q0, 18)})
        elif q_sample is not None:
            qs = _finite(q_sample, f"{tag}.q_sample")
            if qs <= 0.0:
                raise ValueError(
                    f"{tag}: q_sample 必须 >0，得到 {q_sample!r}")
            d_inv = 1.0 / qs - 1.0 / q0
            if d_inv <= 0.0:
                raise ValueError(
                    f"{tag}: 1/q_sample−1/q_empty={d_inv!r} ≤0（加载腔 Q "
                    "不降非物理），显式拒绝")
            eps_dd = d_inv / fill
            out.update({"q_empty": q0, "q_sample": qs,
                        "epsilon_r_double": round(eps_dd, 18),
                        "tan_delta": round(eps_dd / eps_for_q, 18)})
        else:
            raise ValueError(
                f"{tag}: q_empty 单给无消费方向（Q 面须 tan_delta 或 "
                "q_sample 恰给其一），显式拒绝")

    out.update({
        "note": (
            "一阶材料微扰定理 TM010 面：Δf/f0=−(εr′−1)F/2、εr″=(1/Qs−"
            "1/Q0)/F（能量比恒等式）；F 为 J0²+J1² Bessel 恒等式精确场权"
            "（细杆极限=(Vs/Vc)/J1²(x01)，文献通行式 0.539=2J1²/0.269="
            "J1² 圆整）；分母频率按空腔 f0 口径（Δf/f0≪1 时与 /fs 二阶等"
            "价，文献式(1) 同）；正反解经计算器级 forward→inverse 回代自"
            "证（测试面合成样品回收钉）；与 "
            "cavity_perturbation_shift 边界=TE101 矩形腔场积分面（同定"
            "理异几何）；细杆近似有效性 rs≪a 守卫只做几何上限（场权精确"
            "式对粗杆亦自洽，微扰小量假设的定量判据留 followUp）"),
        "source": (
            "一阶腔微扰定理（Slater 1946 Rev. Mod. Phys. 18:441/Waldron "
            "1960 同族；Pozar Microwave Engineering §6.7 同式——既有 "
            "cavity_perturbation_shift 同源）；TM010 几何常数 0.539=2J1²"
            "(2.4048)/0.269=J1²：Alekajbaf-Dancila 2024 Int. J. Microw. "
            "Wirel. Technol. 16(10):1665-1670 式(1)-(3)（DOI "
            "10.1017/S1759078724000308）逐字核对+MSI 工程页同值注"
            "记；L.F. Chen et al. 2004 书页式号公开源不可逐位核实——"
            "#df6-⑬ 纪律不落书内式号如实登记"),
    })
    return out
