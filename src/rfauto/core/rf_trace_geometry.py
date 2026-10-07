"""N14 KiCad RF 导出增强——RF 走线几何内核（taper/倒角弯/圆角弯多边形）。

spec 出处（盘点依据行）：
- 方案池 L158「N14 KiCad RF 导出增强
  （taper/圆角 footprint+寄生反查闭环）」（远期探索池登记项）；
- docs/audit/plan_gap_inventory_20260928.md §二 B5「N14 KiCad RF 导出增强
  （taper/圆角 footprint+寄生反查）| KiCad 子进程链」。

本件=N14 收尾全件：三个确定性走线基元（线性渐变段、45° 倒角 90° 弯、
圆角 90° 弯）的精确多边形化 + 寄生反查闭环（提取与闭式双源）+ KiCad
footprint 直发（.kicad_mod 文本面）——纯函数、毫米制（与 adapters/
layout_interchange 的 LayoutPolygon 同单位），测试侧演示经
layout_interchange Layout 消费与 GDSII 往返（core 不反向依赖 adapters，
分层 #3）。

**寄生反查闭环（收尾件①）**：提取侧（多边形 shoelace 面积 → 面积口径
等效展直长度 / 平行板口径电容）与闭式侧（设计参数代数，独立来源 #118）
双源对照——渐变段等效长度恒等式、倒角挖铜 c²/2、圆角中心线缩短
r·(2−π/2)。电容换算是平行板理想化（板级设计规则近似，非准静态精确解），
Gupta 类经验不连续系数需回原文逐位核对（#134），不在本件如实不做。

**KiCad footprint 直发（收尾件②）**：多边形 → .kicad_mod 文本（单个
custom pad 的 gr_poly 铜基元 + F.SilkS 板框线），零 pcbnew 子进程；语法
面按 KiCad 10.0.6 实测 FootprintSave 输出取证（version 20260206、
gr_poly、坐标尾部零剥离），裁判=文本结构解析（测试内建 s-expr 解析器，
无 KiCad 也全绿）+ 面积守恒往返。

精确判据（合成裁判，tests/unit/test_rf_trace_geometry.py）：
- 渐变段面积恒等式：A = L·(w1+w2)/2（shoelace 逐位）；
- 倒角弯面积恒等式：A = w·(L1+L2) − c²/2（方角扫掠 w(L1+L2) 减去
  直角三角形倒角块；shoelace 逐位）；
- 圆角弯：弧顶点严格落在 r±w/2 同心圆上（距离逐位）、切点连续、
  面积收敛到闭式 A = w(L1+L2) − r·w·(2−π/2)（弧离散 O(1/n²)）；
- 刚体运动不变：旋转 45° 后面积/边数不变。
"""

from __future__ import annotations

import math
from typing import Any

Point2D = tuple[float, float]


def _point(value: Any, name: str) -> Point2D:
    """坐标点收敛：长度 2 的 (x, y) 数值对（bool 拒收）。"""
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__") \
            or len(value) != 2:
        raise ValueError(f"{name} 必须是长度 2 的坐标对，收到 {value!r}")
    x, y = value
    for v in (x, y):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{name} 坐标必须是实数，收到 {value!r}")
    out = (float(x), float(y))
    if not all(math.isfinite(c) for c in out):
        raise ValueError(f"{name} 坐标必须有限，收到 {value!r}")
    return out


def _positive_width(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须 >0 且有限，收到 {value!r}")
    return out


def polygon_shoelace_area(points: list[Point2D] | tuple[Point2D, ...]) -> float:
    """鞋带公式多边形面积（顶点有序、不重复首点；自相交结果无意义）。"""
    n = len(points)
    if n < 3:
        raise ValueError(f"多边形至少 3 顶点，收到 {n}")
    total = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _unit_dir(a: Point2D, b: Point2D, name: str) -> tuple[Point2D, float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= 0.0:
        raise ValueError(f"{name} 两点重合（段长必须 >0）")
    return (dx / length, dy / length), length


def taper_polygon(
    start: Any,
    end: Any,
    width_start_mm: Any,
    width_end_mm: Any,
) -> tuple[Point2D, ...]:
    """线性渐变传输段多边形（梯形，端帽垂直于中心线）。

    面积恒等式 A = L·(w1+w2)/2（测试 shoelace 逐位钉）。
    """
    p0 = _point(start, "start")
    p1 = _point(end, "end")
    w1 = _positive_width(width_start_mm, "width_start_mm")
    w2 = _positive_width(width_end_mm, "width_end_mm")
    (ux, uy), _ = _unit_dir(p0, p1, "start→end")
    nx, ny = -uy, ux  # 左法向
    half1, half2 = w1 / 2.0, w2 / 2.0
    return (
        (p0[0] + nx * half1, p0[1] + ny * half1),
        (p1[0] + nx * half2, p1[1] + ny * half2),
        (p1[0] - nx * half2, p1[1] - ny * half2),
        (p0[0] - nx * half1, p0[1] - ny * half1),
    )


def _bend_frame(
    prev: Point2D, corner: Point2D, nxt: Point2D,
) -> tuple[Point2D, Point2D, float, float, float]:
    """90° 弯局部标架：e1=(u)、v=左法向；返回 (u, v, L1, L2, turn_sign)。

    turn_sign=+1 为左转（next 在 v 侧），−1 为右转。非垂直弯显式拒绝
    （本内核只做 90° 弯基元；任意角弯不在 N14 最小件范围，如实不假装）。
    """
    (u, L1) = _unit_dir(prev, corner, "prev→corner")
    (e2, L2) = _unit_dir(corner, nxt, "corner→next")
    dot = u[0] * e2[0] + u[1] * e2[1]
    if abs(dot) > 1e-9:
        raise ValueError(
            f"90° 弯要求两臂垂直（e1·e2={dot:.3e}≠0）；任意角弯不在本内核范围")
    v = (-u[1], u[0])
    cross = u[0] * e2[1] - u[1] * e2[0]
    turn_sign = 1.0 if cross > 0 else -1.0
    return (u, v, L1, L2, turn_sign)


def _to_world(
    prev: Point2D, u: Point2D, v: Point2D, local: tuple[float, float],
) -> Point2D:
    return (prev[0] + local[0] * u[0] + local[1] * v[0],
            prev[1] + local[0] * u[1] + local[1] * v[1])


def mitered_bend_polygon(
    prev: Any,
    corner: Any,
    nxt: Any,
    width_mm: Any,
    *,
    chamfer_mm: Any = None,
) -> tuple[Point2D, ...]:
    """90° 弯 45° 倒角（mitered）多边形。

    面积恒等式 A = w·(L1+L2) − c²/2（方角扫掠 w(L1+L2) 减倒角直角三角
    形 c²/2；c 缺省 w/2=50% 倒角，微带弯惯用档）。L1/L2=角点前/后臂长。
    """
    p_prev = _point(prev, "prev")
    p_corner = _point(corner, "corner")
    p_next = _point(nxt, "nxt")
    w = _positive_width(width_mm, "width_mm")
    c = w / 2.0 if chamfer_mm is None else _positive_width(chamfer_mm, "chamfer_mm")
    if c > w:
        raise ValueError(f"chamfer_mm 必须 ≤ 线宽 {w}，收到 {c}")
    u, v, l1, l2, s = _bend_frame(p_prev, p_corner, p_next)
    half = w / 2.0
    # 局部坐标（左转构型；右转按 y→−y 镜像）
    local = [
        (0.0, -half),                       # 臂1 外缘起点（端帽在 prev）
        (l1 + half - c, -half),             # 臂1 外缘终点（倒角起点）
        (l1 + half, -half + c),             # 倒角终点（外角切角）
        (l1 + half, l2),                    # 臂2 外缘（端帽在 next）
        (l1 - half, l2),                    # 臂2 端帽内点
        (l1 - half, half),                  # 内角（尖角保留）
        (0.0, half),                        # 臂1 内缘终点
    ]
    if s < 0:
        local = [(x, -y) for (x, y) in local]
    return tuple(_to_world(p_prev, u, v, pt) for pt in local)


def rounded_bend_polygon(
    prev: Any,
    corner: Any,
    nxt: Any,
    width_mm: Any,
    fillet_r_mm: Any,
    *,
    n_arc: int = 32,
) -> tuple[Point2D, ...]:
    """90° 弯圆角（fillet）多边形：中心线圆弧半径 r，切点连续。

    面积收敛到闭式 A = w(L1+L2) − r·w·(2−π/2)（弧离散 O(1/n²)，测试钉
    收敛而非逐位）；弧顶点严格落 r±w/2 同心圆。要求 fillet_r > w/2
    （内缘半径 r−w/2>0；r≤w/2 内缘自交退化，用 mitered_bend_polygon）。
    """
    p_prev = _point(prev, "prev")
    p_corner = _point(corner, "corner")
    p_next = _point(nxt, "nxt")
    w = _positive_width(width_mm, "width_mm")
    r = _positive_width(fillet_r_mm, "fillet_r_mm")
    if r <= w / 2.0:
        raise ValueError(
            f"fillet_r_mm 必须 > w/2={w / 2.0}（内缘半径非退化），收到 {r}")
    if isinstance(n_arc, bool) or not isinstance(n_arc, int) or n_arc < 2:
        raise ValueError(f"n_arc 必须是 ≥2 的整数，收到 {n_arc!r}")
    u, v, l1, l2, s = _bend_frame(p_prev, p_corner, p_next)
    if r > min(l1, l2):
        raise ValueError(
            f"fillet_r_mm={r} 超出短臂长（min(L1,L2)={min(l1, l2)}），切点越界")
    half = w / 2.0
    r_out, r_in = r + half, r - half
    # 局部坐标（左转构型）：弧心 (L1−r, r)，切点 T1=(L1−r, 0)、T2=(L1, r)
    local: list[tuple[float, float]] = [(0.0, -half)]
    for k in range(0, n_arc + 1):
        a = -math.pi / 2.0 + math.pi / 2.0 * k / n_arc
        local.append((l1 - r + r_out * math.cos(a), r + r_out * math.sin(a)))
    local.append((l1 + half, l2))
    local.append((l1 - half, l2))
    local.append((l1 - half, r))
    # 内缘弧：从切点 (l1−half, r)（角 0°）走到 (l1−r, half)（角 −90°）——
    # 角度单调递减遍历（反向=自相交多边形，shoelace 虚增面积）。
    for k in range(n_arc - 1, 0, -1):
        a = -math.pi / 2.0 + math.pi / 2.0 * k / n_arc
        local.append((l1 - r + r_in * math.cos(a), r + r_in * math.sin(a)))
    local.append((l1 - r, half))
    local.append((0.0, half))
    if s < 0:
        local = [(x, -y) for (x, y) in local]
    return tuple(_to_world(p_prev, u, v, pt) for pt in local)


# ─── 寄生反查闭环（收尾件①）：提取与闭式双源（#118 独立来源纪律） ──────────

#: 真空介电常数（CODATA 2018）：8.8541878128e-12 F/m = 8.8541878128e-15 F/mm。
EPSILON_0_F_PER_MM = 8.8541878128e-15

#: 90° 圆角弯角部挖去系数：角方 r² 挖去四分之一圆盘 πr²/4，按 r 归一得
#: 2−π/2——中心线缩短 r·系数、等宽铜面积减少 r·w·系数（同源恒等式，
#: test_rf_trace_geometry 面积×宽度=中心线长交叉钉）。
BEND_CORNER_SAVING_FACTOR = 2.0 - math.pi / 2.0


def equivalent_length_mm(
    points: list[Point2D] | tuple[Point2D, ...], width_ref_mm: Any,
) -> float:
    """面积口径等效展直长度（提取侧）：L_eq = A/w_ref。

    寄生反查的几何提取路径：任意本内核多边形 → shoelace 面积 → 等宽
    （w_ref）均匀线的等效长度。与 :func:`taper_equivalent_length_closed_form`
    构成提取/闭式双源对照。
    """
    w_ref = _positive_width(width_ref_mm, "width_ref_mm")
    return polygon_shoelace_area(points) / w_ref


def plate_capacitance_f(area_mm2: Any, er_eff: Any, height_mm: Any) -> float:
    """平行板理想化换算（板级设计规则近似）：C = ε0·ε_eff·A/h。

    **非准静态精确解**——把金属块面积按均匀平板对地理想化，用于设计规则
    级不连续电容估算与双源对照；Gupta 类经验不连续系数（step/bend 精确
    电容式）需回原文逐位核对后另行增量（#134，本件如实不做）。
    """
    if isinstance(area_mm2, bool) or not isinstance(area_mm2, (int, float)):
        raise ValueError(f"area_mm2 必须是实数，收到 {area_mm2!r}")
    a = float(area_mm2)
    if not math.isfinite(a) or a < 0.0:
        raise ValueError(f"area_mm2 必须 ≥0 且有限，收到 {area_mm2!r}")
    er = _positive_width(er_eff, "er_eff")
    h = _positive_width(height_mm, "height_mm")
    return EPSILON_0_F_PER_MM * er * a / h


def taper_equivalent_length_closed_form(
    length_mm: float, w_start_mm: float, w_end_mm: float, width_ref_mm: float,
) -> float:
    """渐变段等效长度闭式（设计参数代数，独立于多边形路径）：

    A = L·(w1+w2)/2（梯形恒等式）→ L_eq = A/w_ref = L·(w1+w2)/(2·w_ref)。
    """
    length = _positive_width(length_mm, "length_mm")
    w1 = _positive_width(w_start_mm, "w_start_mm")
    w2 = _positive_width(w_end_mm, "w_end_mm")
    w_ref = _positive_width(width_ref_mm, "width_ref_mm")
    return length * (w1 + w2) / (2.0 * w_ref)


def miter_chamfer_removed_area_mm2(chamfer_mm: float) -> float:
    """倒角挖铜闭式：外角等腰直角三角形 c²/2（45° 切角几何精确）。"""
    c = _positive_width(chamfer_mm, "chamfer_mm")
    return c * c / 2.0


def rounded_corner_saving_mm(fillet_r_mm: float) -> float:
    """圆角弯中心线缩短闭式：r·(2−π/2)（切点连续 90° 圆弧替换角点）。"""
    r = _positive_width(fillet_r_mm, "fillet_r_mm")
    return r * BEND_CORNER_SAVING_FACTOR


# ─── KiCad footprint 直发（收尾件②）：.kicad_mod 文本面，零 pcbnew 子进程 ──
# 语法面取证：本机 KiCad 10.0.6 PCB_IO_KICAD_SEXPR.FootprintSave 实测输出
# （version 20260206 / generator_version "10.0" / pad 基元 gr_poly / 坐标
# 尾部零剥离）；装载往返由 tests/unit/test_rf_trace_geometry.py 的结构解析
# 裁判钉（无 KiCad 全绿），另做一次性 pcbnew FootprintLoad 冒烟互证。

_KICAD_FMT_VERSION = "20260206"
_KICAD_GENERATOR = "rfauto.rf_trace_geometry"
#: custom pad 锚矩形边长（mm）：锚取最大面积多边形首顶点（边界上），
#: 越界半格 ≤ 0.0002mm² ——锚点必须在铜边界上的如实取舍（bbox 中心对
#: L 形/弯折轮廓落在铜外，会注入孤立铜块）。
_KICAD_ANCHOR_SIZE_MM = 0.02
_SX_FORBIDDEN_CHARS = ('"', "(", ")", "\\", "\n", "\r", "\t")


def _snap_nm(value: float) -> float:
    """KiCad 内部网格 1nm：毫米值 6 位小数量化。"""
    return round(float(value), 6)


def _fmt_mm(value: float) -> str:
    """KiCad 坐标文本：尾部零剥离（KiCad 10 实测 (xy 1 0) 形态），−0 归一。"""
    q = _snap_nm(value)
    if q == 0.0:
        return "0"
    return f"{q:.6f}".rstrip("0").rstrip(".")


def _sexpr_safe(text: Any, name: str) -> str:
    """s-expr 原子注入守卫：非空字符串、禁引号/括号/反斜杠/控制符。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{name} 必须是非空字符串，收到 {text!r}")
    for ch in _SX_FORBIDDEN_CHARS:
        if ch in text:
            raise ValueError(f"{name} 含 s-expr 非法字符 {ch!r}：{text!r}")
    return text


def _polys_norm(polys: Any) -> list[tuple[Point2D, ...]]:
    """多边形序列收敛：非空、逐点 _point 校验、逐个 ≥3 顶点。"""
    if isinstance(polys, (str, bytes)) or not hasattr(polys, "__len__"):
        raise ValueError(f"polys 必须是多边形序列，收到 {polys!r}")
    out: list[tuple[Point2D, ...]] = []
    for i, poly in enumerate(polys):
        try:
            pts = tuple(_point(pt, f"polys[{i}] 顶点") for pt in poly)
        except TypeError as exc:
            raise ValueError(f"polys[{i}] 必须是顶点序列，收到 {poly!r}") from exc
        if len(pts) < 3:
            raise ValueError(f"polys[{i}] 至少 3 顶点，收到 {len(pts)}")
        out.append(pts)
    if not out:
        raise ValueError("polys 不能为空")
    return out


def _bbox_of_polys(polys: list[tuple[Point2D, ...]]) -> tuple[float, float, float, float]:
    """并集包围盒 (x_min, y_min, x_max, y_max)。"""
    xs = [pt[0] for poly in polys for pt in poly]
    ys = [pt[1] for poly in polys for pt in poly]
    return min(xs), min(ys), max(xs), max(ys)


def kicad_footprint_text(
    polys: Any,
    *,
    name: str = "rf_trace",
    value: str = "RF_TRACE",
    copper_layer: str = "F.Cu",
    silk: bool = True,
    silk_width_mm: Any = 0.12,
    silk_margin_mm: Any = 0.5,
    origin: Any = None,
) -> str:
    """多边形 → .kicad_mod footprint 文本（零 pcbnew 子进程的直发面）。

    结构：单个 ``smd custom`` pad 承载全部铜多边形（每多边形一个
    ``gr_poly`` 基元，``fill yes``/``width 0``，KiCad 10 实测语法）+
    F.SilkS 板框 4 线段（并集 bbox 外扩 silk_margin_mm，闭合环）。
    Reference/Value 属性齐全、坐标按 1nm 网格量化、坐标变换=平移
    （面积/顶点序守恒，测试内建 s-expr 解析器往返钉）。

    Parameters
    ----------
    polys : 序列[序列[(x, y), ...]]
        铜多边形（本内核三基元输出或任意同制式多边形），毫米制。
    origin : (x, y) 或 None
        footprint 原点（世界坐标，nm 网格量化后取整）；None=并集 bbox
        中心（量化后），使坐标对称落位。

    Returns
    -------
    str
        可被 KiCad 解析的 .kicad_mod 文本（确定性：同入参逐字节相同）。
    """
    polys_n = _polys_norm(polys)
    name_s = _sexpr_safe(name, "name")
    value_s = _sexpr_safe(value, "value")
    layer_s = _sexpr_safe(copper_layer, "copper_layer")
    silk_w = _positive_width(silk_width_mm, "silk_width_mm")
    silk_m = _positive_width(silk_margin_mm, "silk_margin_mm")
    if not isinstance(silk, bool):
        raise ValueError(f"silk 必须是布尔，收到 {silk!r}")

    x_min, y_min, x_max, y_max = _bbox_of_polys(polys_n)
    if origin is None:
        ox = _snap_nm((x_min + x_max) / 2.0)
        oy = _snap_nm((y_min + y_max) / 2.0)
    else:
        o = _point(origin, "origin")
        ox, oy = _snap_nm(o[0]), _snap_nm(o[1])

    # 锚点=最大面积多边形首顶点（边界上；pad 局部原点）
    areas = [polygon_shoelace_area(poly) for poly in polys_n]
    anchor_poly = polys_n[areas.index(max(areas))]
    ax, ay = anchor_poly[0]

    lines: list[str] = []
    lines.append(f'(footprint "{name_s}"')
    lines.append(f'\t(version {_KICAD_FMT_VERSION})')
    lines.append(f'\t(generator "{_KICAD_GENERATOR}")')
    lines.append('\t(generator_version "1.0")')
    lines.append(f'\t(layer "{layer_s}")')
    lines.append('\t(descr "N14 RF trace geometry direct emit")')
    top_y = -(y_max - y_min) / 2.0 - silk_m - 1.0
    bot_y = (y_max - y_min) / 2.0 + silk_m + 1.0
    lines.append('\t(property "Reference" "REF**"')
    lines.append(f'\t\t(at 0 {_fmt_mm(top_y)} 0)')
    lines.append('\t\t(layer "F.SilkS")')
    lines.append('\t\t(effects (font (size 1 1) (thickness 0.15)))')
    lines.append('\t)')
    lines.append(f'\t(property "Value" "{value_s}"')
    lines.append(f'\t\t(at 0 {_fmt_mm(bot_y)} 0)')
    lines.append('\t\t(layer "F.Fab")')
    lines.append('\t\t(effects (font (size 1 1) (thickness 0.15)))')
    lines.append('\t)')
    lines.append('\t(attr exclude_from_pos_files exclude_from_bom)')
    lines.append('\t(pad "" smd custom')
    lines.append(f'\t\t(at {_fmt_mm(ax - ox)} {_fmt_mm(ay - oy)})')
    lines.append(f'\t\t(size {_KICAD_ANCHOR_SIZE_MM} {_KICAD_ANCHOR_SIZE_MM})')
    lines.append(f'\t\t(layers "{layer_s}")')
    lines.append('\t\t(options')
    lines.append('\t\t\t(clearance outline)')
    lines.append('\t\t\t(anchor rect)')
    lines.append('\t\t)')
    lines.append('\t\t(primitives')
    for poly in polys_n:
        # 基元坐标=pad 局部系（相对锚点）：KiCad 物化时做 pts+pad位置
        # （KiCad 10 实测：多减 origin 会得到 world−2·origin 的双移位），
        # origin 只作用于 pad 位置——铜随 footprint 整体平移的刚体语义。
        pts = " ".join(
            f"(xy {_fmt_mm(px - ax)} {_fmt_mm(py - ay)})"
            for (px, py) in poly
        )
        lines.append('\t\t\t(gr_poly')
        lines.append(f'\t\t\t\t(pts {pts})')
        lines.append('\t\t\t\t(width 0)')
        lines.append('\t\t\t\t(fill yes)')
        lines.append('\t\t\t)')
    lines.append('\t\t)')
    lines.append('\t)')
    if silk:
        sx0 = x_min - ox - silk_m
        sy0 = y_min - oy - silk_m
        sx1 = x_max - ox + silk_m
        sy1 = y_max - oy + silk_m
        corners = [(sx0, sy0), (sx1, sy0), (sx1, sy1), (sx0, sy1)]
        for i in range(4):
            (x0, y0), (x1, y1) = corners[i], corners[(i + 1) % 4]
            lines.append('\t(fp_line')
            lines.append(f'\t\t(start {_fmt_mm(x0)} {_fmt_mm(y0)})')
            lines.append(f'\t\t(end {_fmt_mm(x1)} {_fmt_mm(y1)})')
            lines.append('\t\t(stroke')
            lines.append(f'\t\t\t(width {_fmt_mm(silk_w)})')
            lines.append('\t\t\t(type default)')
            lines.append('\t\t)')
            lines.append('\t\t(layer "F.SilkS")')
            lines.append('\t)')
    lines.append(')')
    return "\n".join(lines) + "\n"
