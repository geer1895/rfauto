"""openEMS MSLPort 端口语义单源发射器（aurora_l Wave-E E2，R1 #1）。

用户 P12 反馈（HFSS 侧"aperture 不含金属→0.135nH 假结果"）在 openEMS 侧的
同款病灶：MSLPort/CPWPort 裸调（如 render_hairpin.py 的 MSLPort 构造）无
aperture/落格/积分线断言——内核立规注记 坑账 #347 原文记录过同一病灶（MSLPort 的
MeasPlaneShift 与 FeedShift 接近时探针落激励盒近场：β 偏 10×、Z_ref≈9Ω、
|Γ|>1）。本模块把五判据收敛为**单源纯几何校验器**，渲染器在 MSLPort 构造
前调用（违例 ValueError 建模期炸——K7 哲学：建模期直接报错而不是解出
0.135nH 假结果）。

五判据（每条带病灶人话，编号=内核立规注记 坑账出处）：
  c1  |MeasPlaneShift−FeedShift| ≥ 4·NEAR
      （#347：u/i 探针落激励盒近场→β 偏 10×、Z_ref≈9Ω、|Γ|>1）
  c2  端口盒横向跨度 > 0 且 ≥ 导带（馈线盒）横向跨度
      （#340④：盒写零宽=探针同位，S11/S21 双≈0dB 非物理）
  c3  激励截面（端口盒横/激励轴截面）全含导带截面
      （#253 反向：激励域内缩≥2·BASE——激励截面缺金属/悬空时延迟开启
      瞬态激起零模 DC 漂移，15ns 内涨到信号 10 倍）
  c4  端口盒各边与网格线重合（mesh_mm 整数倍，相对容差 1e-6）
      （#283：盒边不落网格线→探针吸附盒角=单棱积分，跨轮偏差中位 1.9%；
      mesh_mm=None 时降级为登记态——终网格线集渲染期不可知，盒边=结构线
      由 grid._near_points #198 精确入网保证、域缘由 AddLine 保证，逐位
      落位全量守卫留在生成脚本网格段，render_siw #283 先例）
  c5  端口盒 z 向含导带（MSLPort 端口金属面=start 的 exc 坐标，
      openEMS ports.py L346-349 口径）且导带高于盒 z 底 ≥2 格
      （#283：z 柱体 <2 格→u/i 探针塌缩单棱积分；v1 纯几何 z 格距=
      z_span/4，官方 substrate_cells=4 口径，_sub_cells 旋钮消费留后续）

**单位契约**：port_box/feed_box/meas_plane_shift/feed_shift/near 一律米
（渲染器 SI 口径，MSLPort start/stop 同源）；mesh_mm 毫米（名字即单位）。

**v1 范围**：纯几何校验器，非完整 planner。端口盒形态判定口径：exc 轴固
定 z（全仓 MSLPort 调用面 exc_dir="z" 实测），prop 轴=port_box 最长横轴，
横向轴=余下之一。首批接线三渲染器（hairpin/hairpin_alt、varactor_bpf、
c4 族三模板）——其余渲染器余量登记见席位交付报告，不做全量 26 渲染器。
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["assert_msl_port_geometry", "validate_msl_port_geometry"]

#: 判据边界相对浮点余量（恰等不炸；仓内 #347 守卫 3.9·NEAR 口径同源动机）
_FLT_EPS = 1e-9
#: c4 格点量化相对容差（HJ 综合 4 位小数几何对显式 mesh 的容差面）
_LATTICE_EPS = 1e-6

_CHECK_IDS = (
    "c1_meas_feed_sep_4near",
    "c2_port_spans_conductor",
    "c3_excitation_contains_conductor",
    "c4_box_edges_on_grid",
    "c5_z_pillar_two_cells",
)


def _box3(box: Any, name: str) -> tuple[list[float], list[float],
                                        list[float], list[float]]:
    """(start, stop) 二元组 → (start, stop, lo, hi) 三个 3 元列表（米）。"""
    if not isinstance(box, tuple) or len(box) != 2:
        raise ValueError(
            f"{name} 须为 (start, stop) 二元组（MSLPort start/stop 同形），"
            f"得 {type(box).__name__}")
    start = [float(v) for v in box[0]]
    stop = [float(v) for v in box[1]]
    if len(start) != 3 or len(stop) != 3:
        raise ValueError(f"{name} 每 endpoint 须 3 元（x, y, z），得 "
                         f"{len(start)}/{len(stop)} 元")
    if not all(math.isfinite(v) for v in start + stop):
        raise ValueError(f"{name} 含非有限坐标")
    lo = [min(a, b) for a, b in zip(start, stop, strict=True)]
    hi = [max(a, b) for a, b in zip(start, stop, strict=True)]
    return start, stop, lo, hi


def validate_msl_port_geometry(*, port_box: Any, feed_box: Any,
                               meas_plane_shift: float, feed_shift: float,
                               near: float, mesh_mm: float | None) -> dict[
                               str, Any]:
    """MSLPort 端口语义五判据纯几何校验（违例不抛错，返回结构化判定）。

    参数：port_box=MSLPort(start, stop) 的端口盒（米，2×3 序列）；feed_box=
    导带馈线盒（米，手画段或 layout 馈段——导带截面参照）；meas_plane_shift/
    feed_shift=MSLPort 同名参数（米）；near=NEAR 近场格距（米）；
    mesh_mm=网格 base（毫米）或 None（c4 降级登记，见模块 docstring）。

    返回 {"ok": bool, "checks": [{"id","ok","detail"}...],
    "violations": [str...]}；ok=False 时 violations 带每条病灶人话。
    ok 聚合口径：任一判据 ok is False 即 False；c4 降级（ok=None）不否决。
    """
    if not (math.isfinite(near) and near > 0.0):
        raise ValueError(f"near 须为正有限（米），得 {near!r}")
    if mesh_mm is not None and not (math.isfinite(mesh_mm) and mesh_mm > 0.0):
        raise ValueError(f"mesh_mm 须为正有限（毫米）或 None，得 {mesh_mm!r}")
    meas_plane_shift = float(meas_plane_shift)
    feed_shift = float(feed_shift)
    if not (math.isfinite(meas_plane_shift) and math.isfinite(feed_shift)):
        raise ValueError("MeasPlaneShift/FeedShift 须有限（米）")

    p_start, _p_stop, p_lo, p_hi = _box3(port_box, "port_box")
    _f_start, _f_stop, f_lo, f_hi = _box3(feed_box, "feed_box")
    span = [hi_v - lo_v
            for lo_v, hi_v in zip(p_lo, p_hi, strict=True)]
    # exc 轴固定 z（全仓 MSLPort exc_dir="z" 口径）；prop=最长横轴；横向=余轴
    prop_ax = 0 if span[0] >= span[1] else 1
    trans_ax = 1 - prop_ax
    coord_scale = max(abs(v) for v in p_lo + p_hi + [near]) or 1.0
    mm = meas_plane_shift
    fsh = feed_shift
    nr = near

    checks: list[dict[str, Any]] = []
    violations: list[str] = []

    # ── c1（#347）：|MeasPlaneShift−FeedShift| ≥ 4·NEAR ──────────────────
    sep = abs(mm - fsh)
    ok1 = sep >= 4.0 * nr * (1.0 - _FLT_EPS)
    detail1 = (f"|MeasPlaneShift−FeedShift|={sep * 1e3:.6g}mm，4·NEAR="
               f"{4.0 * nr * 1e3:.6g}mm（NEAR={nr * 1e3:.6g}mm）")
    if not ok1:
        violations.append(
            f"c1(#347) {detail1}——u/i 探针落激励盒近场：β 偏 10×、Z_ref≈9Ω、"
            "|Γ|>1（加大去嵌面距/馈段长，或收紧 NEAR）")
    checks.append({"id": _CHECK_IDS[0], "ok": ok1, "detail": detail1})

    # ── c2（#340④）：端口盒横向跨度 > 0 且 ≥ 导带横向跨度 ────────────────
    span_p = span[trans_ax]
    span_f = f_hi[trans_ax] - f_lo[trans_ax]
    ok2 = span_p > 0.0 and span_p >= span_f * (1.0 - _FLT_EPS)
    detail2 = (f"端口盒横向（轴{'xy'[trans_ax]}）跨度={span_p * 1e3:.6g}mm，"
               f"导带（feed_box）横向跨度={span_f * 1e3:.6g}mm")
    if not ok2:
        violations.append(
            f"c2(#340④) {detail2}——端口盒零宽/未跨导带：u 探针与导带同位，"
            "S11/S21 双≈0dB 非物理（盒对角必须横跨导带 ±W/2）")
    checks.append({"id": _CHECK_IDS[1], "ok": ok2, "detail": detail2})

    # ── c3（#253）：激励截面全含导带截面（横/激励两轴区间包含）──────────
    tol_c = _FLT_EPS * max(1.0, coord_scale)
    contain_fail = [ax for ax in (trans_ax, 2)
                    if f_lo[ax] < p_lo[ax] - tol_c or f_hi[ax] > p_hi[ax] + tol_c]
    ok3 = not contain_fail
    detail3 = (f"导带截面（轴{'xy'[trans_ax]}/z）="
               f"[{f_lo[trans_ax] * 1e3:.6g}, {f_hi[trans_ax] * 1e3:.6g}]、"
               f"[{f_lo[2] * 1e3:.6g}, {f_hi[2] * 1e3:.6g}]mm ⊆ 端口盒截面="
               f"[{p_lo[trans_ax] * 1e3:.6g}, {p_hi[trans_ax] * 1e3:.6g}]、"
               f"[{p_lo[2] * 1e3:.6g}, {p_hi[2] * 1e3:.6g}]mm"
               f"（越界轴：{''.join('xy'[a] for a in contain_fail) or '无'}）；"
               "#253 反向面（激励盒不得跨满吸收边界，内缩≥2·BASE）需域边界"
               "参数，纯几何 v1 不判、登记后续")
    if not ok3:
        violations.append(
            f"c3(#253) {detail3}——激励截面未全含导带截面：激励部分悬空/缺金属，"
            "延迟开启瞬态激起零模 DC 漂移（15ns 内涨到信号 10 倍）")
    checks.append({"id": _CHECK_IDS[2], "ok": ok3, "detail": detail3})

    # ── c4（#283）：端口盒各边与网格线重合（mesh_mm 整数倍）──────────────
    faces = [v for ax in range(3) for v in (p_lo[ax], p_hi[ax])]
    if mesh_mm is None:
        ok4: bool | None = None
        detail4 = ("mesh_mm=None——终网格线集渲染期不可知，本处降级登记："
                   "盒边=结构线由 grid._near_points #198 精确入网保证、域缘由 "
                   "AddLine 保证；逐位落位全量守卫留在生成脚本网格段"
                   "（render_siw #283 先例）")
    else:
        mesh_m = mesh_mm * 1e-3
        off = [f for f in faces
               if abs(f / mesh_m - round(f / mesh_m)) > _LATTICE_EPS]
        ok4 = not off
        detail4 = (f"端口盒 6 面对 mesh_mm={mesh_mm:.6g}mm 格点量化，"
                   f"离格面 {len(off)}/6"
                   + (f"：{[f'{v * 1e3:.6g}mm' for v in off]}" if off else ""))
        if not ok4:
            violations.append(
                f"c4(#283) {detail4}——盒边不落网格线：探针吸附盒角=单棱积分，"
                "装配矩阵跨轮偏差中位 1.9%（边坐标取 mesh 整数倍或显式入网）")
    checks.append({"id": _CHECK_IDS[3], "ok": ok4, "detail": detail4})

    # ── c5（#283/#340④）：z 向含导带 + 导带高于盒 z 底 ≥2 格 ─────────────
    z_lo, z_hi = p_lo[2], p_hi[2]
    z_span = z_hi - z_lo
    conductor_z = p_start[2]  # MSLPort 端口金属面=start 的 exc 坐标（z）
    # v1 纯几何 z 格距=z_span/4（官方 substrate_cells=4；_sub_cells 旋钮留后续）
    z_cell = z_span / 4.0
    ok5 = (z_span > 0.0
           and z_lo - tol_c <= conductor_z <= z_hi + tol_c
           and conductor_z - z_lo >= 2.0 * z_cell * (1.0 - _FLT_EPS))
    detail5 = (f"导带 z={conductor_z * 1e3:.6g}mm ∈ 盒 z=[{z_lo * 1e3:.6g}, "
               f"{z_hi * 1e3:.6g}]mm，柱高={conductor_z * 1e3:.6g}mm，"
               f"2 格={2.0 * z_cell * 1e3:.6g}mm（z_span/4 格距）")
    if not ok5:
        violations.append(
            f"c5(#283) {detail5}——端口盒 z 向零高/不含导带/接地柱体 <2 格："
            "u/i 探针塌缩单棱积分，装配矩阵跨轮漂移（#340④ 同族：盒写零宽="
            "探针同位）")
    checks.append({"id": _CHECK_IDS[4], "ok": ok5, "detail": detail5})

    ok = all(c["ok"] is not False for c in checks)
    return {"ok": ok, "checks": checks, "violations": violations}


def assert_msl_port_geometry(*, context: str, **kwargs: Any) -> dict[str, Any]:
    """校验器 + 违例 ValueError 一体的建模期发射器（渲染器接线点消费）。

    kwargs 直通 validate_msl_port_geometry；ok=False 时 raise
    ValueError（K7：建模期直接报错而不是解出假结果），context 标明
    模板/端口便于定位。
    """
    result = validate_msl_port_geometry(**kwargs)
    if not result["ok"]:
        raise ValueError(
            f"{context}: MSLPort 端口语义五判据违例（建模期 K7 直接报错）——"
            + "；".join(result["violations"]))
    return result
