"""HS-4 回流路径不连续几何检测器（flag 级 100% 几何，零仿真零 I/O）。

法源与口径（研究扩充 round4 中件包一 HS-4 原文）：
"回流路径不连续几何检测器：走线∩平面分割多边形=确定性求交+换层过孔-
缝合孔距离检查；J(d)∝1/(1+(d/h)²) 文档化；flag 级 100% 几何，量化级
NO-GO"。物理背景：高速信号换参考平面/跨分割时，回流电流被迫绕行分割缝
或经缝合孔（stitching via）换层，绕行环路面积增大 → 环路电感与 EMI 辐射
上升（Bogatin《Signal and Power Integrity》回流电流分布口径，round4 §
引文 [23]）。

规则码表（severity 与 code 一一对应，聚合方按 FLAG_CODES/WARNING_CODES 分离）：

=== ==================== ======== ==========================================
规则 code               级别     语义
=== ==================== ======== ==========================================
R1  TRACE_CROSS_SPLIT    flag     走线矩形与平面分割多边形相交（非空，含
                                  接触）→ 回流被分割缝打断
R2  VIA_STITCH_DISTANCE  flag     换层过孔到最近回流参考（缝合孔或平面边
                                  缘）的距离 d > 门限 h → 环路面积超标
R2a VIA_OUTSIDE_PLANE     flag     换层过孔不在参考平面多边形内（含边界）→
                                  该过孔下方根本没有回流平面（R2 的可定义
                                  性守卫：只有过孔在平面内，"到平面边缘
                                  距离"才有回流语义）
R3  TRACE_EDGE_MARGIN    warning  走线到分割边缘距离 d < edge_margin_widths
                                  × w（3w 惯例，倍数显式传参）→ 邻边回流
                                  通道拥挤；warning 不改 verdict
=== ==================== ======== ==========================================

边界口径（全部钉死并有测试钉）：
- R1 相交判定：边相交或包含，**接触（共享点/共线重叠）算相交**——回流
  电流在分割边界即被迫改道；
- R2 距离规则：flag 当且仅当 ``d > h``（**恰等 d == h 不 flag**，边界
  容忍口径）；d = min(到最近缝合孔， 到平面边缘)，缝合孔与平面都没给时
  R2 无从评估 → ValueError fail-fast（不静默放行）；
- R3 距离规则：warning 当且仅当 ``d < edge_margin_widths × w``（**恰等
  不警**，严格小于口径）；走线与分割相交（R1 已 flag）时该对不再重复报
  R3——同一物理缺陷不双报；
- 过孔在平面边上的判定：含边界（inclusive，容差 1e-9 mm）——贴边过孔
  回流可直接经平面边缘换层，不算 outside。
- 门限参数语义：h（via_return_distance_h_mm）无普适惯例值（随上升时间/
  叠层变化）→ 给了换层过孔就**必须显式给 h**，缺省即 ValueError；
  3w 倍数有行业惯例 → 缺省 3.0 但参数显式可覆盖（惯例参数显式）。

J(d) 文档化面（NO-GO 边界，round4 原文钉死）：回流电流密度经验式
``J(d) ∝ 1/(1+(d/h)^2)``（Bogatin）**只以注释字段+公式字符串**随报告
返回（见 :data:`RETURN_CURRENT_MODEL_FORMULA`/:data:`RETURN_CURRENT_MODEL_NOTE`
与报告 j_model 字段），**不产量化电流密度数字**——量化级（电流密度分布
求解/积分）为 NO-GO，本模块 flag 级 100% 几何。

数值只在确定性内核：纯几何闭式判定，零仿真零网络零
文件 I/O；单位统一 mm（参数名带 _mm 或 checked.units 显式记录）；判缺失
一律 ``is not None``（#364④）；数值入参显式拒收 bool（df7+⑯）。分层：
core 叶（不 import 上层）；JSON 进出门面见
service/return_path_check_service.py（薄壳，本模块不做）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

__all__ = [
    "FLAG_CODES",
    "RETURN_CURRENT_MODEL_FORMULA",
    "RETURN_CURRENT_MODEL_NOTE",
    "RULE_CODES",
    "SEVERITY_FLAG",
    "SEVERITY_WARNING",
    "WARNING_CODES",
    "ReturnPathIssue",
    "ReturnPathReport",
    "SplitRegion",
    "TraceSpec",
    "ViaSpec",
    "check_return_path",
    "point_distance",
    "point_in_polygon",
    "point_in_polygon_inclusive",
    "point_polygon_boundary_closest",
    "point_polygon_boundary_distance",
    "point_polygon_distance",
    "point_segment_closest",
    "polygons_distance",
    "polygons_intersect",
    "segments_intersect",
    "trace_rectangle",
]

#: 平面点（mm）
Point = tuple[float, float]

# ─── 规则码表 ────────────────────────────────────────────────────────────────

RULE_CODES = (
    "TRACE_CROSS_SPLIT",
    "VIA_STITCH_DISTANCE",
    "VIA_OUTSIDE_PLANE",
    "TRACE_EDGE_MARGIN",
)
#: flag 级码（任一出现 → verdict FAIL）
FLAG_CODES = ("TRACE_CROSS_SPLIT", "VIA_STITCH_DISTANCE", "VIA_OUTSIDE_PLANE")
#: warning 级码（不FAIL，只提示）
WARNING_CODES = ("TRACE_EDGE_MARGIN",)

SEVERITY_FLAG = "flag"
SEVERITY_WARNING = "warning"

# ─── J(d) 文档化面（NO-GO 边界：只文档化，不产量化数字） ─────────────────────

#: 回流电流密度经验式（Bogatin，round4 HS-4 原文口径）——仅公式字符串
RETURN_CURRENT_MODEL_FORMULA = "J(d) ∝ 1 / (1 + (d/h)^2)"

RETURN_CURRENT_MODEL_NOTE = (
    "回流电流密度分布经验式（Bogatin《Signal and Power Integrity》口径，"
    "研究扩充 round4 HS-4 引文[23]）：d=换层过孔到"
    "最近回流参考（缝合孔或平面边缘）的距离，h=与叠层相关的特征距离（本模块"
    "即 via_return_distance_h_mm 门限）。NO-GO 边界（round4 原文钉死）：本模块"
    "flag 级 100% 几何，J(d) 只文档化不产量化电流密度数字；量化级"
    "（电流密度分布求解/积分）不在本模块范围。"
)

#: 含边界判定的边界容差（mm；构造精确几何下重合点距离恰 0，容差只兜旋转
#: 场景的浮点 ulp 误差）
_ON_BOUNDARY_TOL_MM = 1e-9


# ─── 数值守卫（bool 显式拒收，df7+⑯；判缺失 is not None，#364④） ────────────


def _finite(value: Any, name: str) -> float:
    """入参收敛为有限 float，非法即显式报错。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染）")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 数值非法 {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    """入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，收到 {out!r}")
    return out


# ─── 几何原语（纯函数；单位 mm） ─────────────────────────────────────────────


def _signed_area(poly: tuple[Point, ...]) -> float:
    """鞋带公式有向面积（>0 逆时针）。"""
    total = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return 0.5 * total


def _validate_polygon(points: Any, name: str) -> tuple[Point, ...]:
    """多边形校验+归一（≥3 点、坐标有限、无零长边、面积非零），违规 ValueError。"""
    if points is None:
        raise ValueError(f"{name}: 多边形缺失")
    try:
        raw = list(points)
    except TypeError as exc:
        raise ValueError(f"{name}: 多边形必须是点序列") from exc
    if len(raw) < 3:
        raise ValueError(f"{name}: 退化多边形（{len(raw)} 点 < 3）")
    pts: list[Point] = []
    for i, pt in enumerate(raw):
        try:
            x, y = pt
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}[{i}]: 点必须是 (x, y) 二元组") from exc
        pts.append((_finite(x, f"{name}[{i}].x"), _finite(y, f"{name}[{i}].y")))
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        if x0 == x1 and y0 == y1:
            raise ValueError(f"{name}: 退化多边形（顶点 {i} 与后续顶点重合，零长边）")
    if _signed_area(tuple(pts)) == 0.0:
        raise ValueError(f"{name}: 退化多边形（共线/零面积）")
    return tuple(pts)


def _orient(a: Point, b: Point, c: Point) -> float:
    """叉积 (b−a)×(c−a)：>0 左逆时针，<0 顺时针，==0 共线。"""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Point, b: Point, p: Point) -> bool:
    """已知 p 与 a−b 共线（_orient==0）时的包围盒判定；端点接触算在段上。"""
    return (
        min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    )


def segments_intersect(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    """线段相交判定（边界口径：接触/共线重叠/端点触碰都算相交）。

    标准定向跨立试验 + 四个端点在段上的退化分支（CLRS 口径）。
    """
    d1 = _orient(b0, b1, a0)
    d2 = _orient(b0, b1, a1)
    d3 = _orient(a0, a1, b0)
    d4 = _orient(a0, a1, b1)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True
    if d1 == 0.0 and _on_segment(b0, b1, a0):
        return True
    if d2 == 0.0 and _on_segment(b0, b1, a1):
        return True
    if d3 == 0.0 and _on_segment(a0, a1, b0):
        return True
    return d4 == 0.0 and _on_segment(a0, a1, b1)


def _segment_intersection_point(
    a0: Point, a1: Point, b0: Point, b1: Point
) -> Point | None:
    """两线段交点（参数法）；平行或不相交返回 None（仅用于 R1 位置报告）。"""
    x0, y0 = a0
    x1, y1 = a1
    x2, y2 = b0
    x3, y3 = b1
    den = (x1 - x0) * (y3 - y2) - (y1 - y0) * (x3 - x2)
    if den == 0.0:
        return None
    t = ((x2 - x0) * (y3 - y2) - (y2 - y0) * (x3 - x2)) / den
    u = ((x2 - x0) * (y1 - y0) - (y2 - y0) * (x1 - x0)) / den
    eps = 1e-12
    if -eps <= t <= 1.0 + eps and -eps <= u <= 1.0 + eps:
        return (x0 + t * (x1 - x0), y0 + t * (y1 - y0))
    return None


def point_in_polygon(p: Point, poly: tuple[Point, ...]) -> bool:
    """射线法严格内部判定（边界点归属不定——含边界口径用
    :func:`point_in_polygon_inclusive`）。poly 须为简单多边形（已校验）。"""
    px, py = p
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py):
            x_cross = (xj - xi) * (py - yi) / (yj - yi) + xi
            if px < x_cross:
                inside = not inside
        j = i
    return inside


def point_segment_closest(p: Point, a: Point, b: Point) -> tuple[float, Point]:
    """点到线段最近距离与垂足（参数钳位 t∈[0,1]）。"""
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0.0:
        d = math.hypot(px - ax, py - ay)
        return d, (ax, ay)
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len2
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy), (cx, cy)


def point_polygon_boundary_closest(
    p: Point, poly: tuple[Point, ...]
) -> tuple[float, Point]:
    """点到多边形边界的最近距离与最近点（各边垂足取最小）。"""
    best_d = math.inf
    best_pt: Point = poly[0]
    n = len(poly)
    for i in range(n):
        d, cp = point_segment_closest(p, poly[i], poly[(i + 1) % n])
        if d < best_d:
            best_d, best_pt = d, cp
    return best_d, best_pt


def point_polygon_boundary_distance(p: Point, poly: tuple[Point, ...]) -> float:
    """点到多边形边界的最近距离（mm）。"""
    return point_polygon_boundary_closest(p, poly)[0]


def point_in_polygon_inclusive(p: Point, poly: tuple[Point, ...]) -> bool:
    """含边界的内部判定（边界或距边界 ≤ 容差都算在内）。"""
    if point_in_polygon(p, poly):
        return True
    return point_polygon_boundary_distance(p, poly) <= _ON_BOUNDARY_TOL_MM


def point_polygon_distance(p: Point, poly: tuple[Point, ...]) -> float:
    """点到多边形区域的距离（内部/边界为 0，外部为到边界最近距离）。"""
    if point_in_polygon_inclusive(p, poly):
        return 0.0
    return point_polygon_boundary_distance(p, poly)


def polygons_intersect(pa: tuple[Point, ...], pb: tuple[Point, ...]) -> bool:
    """两简单多边形是否相交（非空，含接触）。

    双路判定：任一边对相交（含接触）或一方顶点落入另一方内部（纯包含
    场景无边交）。
    """
    na, nb = len(pa), len(pb)
    for i in range(na):
        a0 = pa[i]
        a1 = pa[(i + 1) % na]
        for j in range(nb):
            if segments_intersect(a0, a1, pb[j], pb[(j + 1) % nb]):
                return True
    return any(point_in_polygon(v, pb) for v in pa) or any(
        point_in_polygon(v, pa) for v in pb
    )


def _polygons_distance_and_point(
    pa: tuple[Point, ...], pb: tuple[Point, ...]
) -> tuple[float, Point | None]:
    """两多边形最近距离与 pb 侧最近点（相交 → (0.0, None)）。

    不相交简单多边形的最近距离必在"一方顶点到另一方边"的垂足处取得
    （边-边最小在浮点下同样归结到端点垂足），双向顶点-边扫描即精确。
    """
    if polygons_intersect(pa, pb):
        return 0.0, None
    best_d = math.inf
    best_pt: Point | None = None
    na, nb = len(pa), len(pb)
    for v in pa:
        for j in range(nb):
            d, cp = point_segment_closest(v, pb[j], pb[(j + 1) % nb])
            if d < best_d:
                best_d, best_pt = d, cp
    for v in pb:
        for i in range(na):
            d, _ = point_segment_closest(v, pa[i], pa[(i + 1) % na])
            if d < best_d:
                best_d, best_pt = d, v
    return best_d, best_pt


def polygons_distance(pa: tuple[Point, ...], pb: tuple[Point, ...]) -> float:
    """两多边形最近距离（mm；相交为 0.0）。"""
    return _polygons_distance_and_point(pa, pb)[0]


def point_distance(a: Point, b: Point) -> float:
    """两点欧氏距离（缝合孔距离原语；d(a,b)=d(b,a) 对称恒等）。"""
    ax = _finite(a[0], "a.x")
    ay = _finite(a[1], "a.y")
    bx = _finite(b[0], "b.x")
    by = _finite(b[1], "b.y")
    return math.hypot(ax - bx, ay - by)


def trace_rectangle(
    p0: Point, p1: Point, width_mm: float
) -> tuple[Point, Point, Point, Point]:
    """走线段 p0→p1 加宽 width_mm → 细长矩形四角（垂直方向对称加宽）。

    走线段=细长矩形的统一编码（HS-4 规格原语）；零长度段/非正宽度
    ValueError（退化尺寸守卫）。
    """
    w = _positive(width_mm, "width_mm")
    x0 = _finite(p0[0], "p0.x")
    y0 = _finite(p0[1], "p0.y")
    x1 = _finite(p1[0], "p1.x")
    y1 = _finite(p1[1], "p1.y")
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length <= 0.0:
        raise ValueError("走线段长度必须 >0（p0 == p1 零长度退化）")
    half_w = w / 2.0
    nx, ny = -dy / length * half_w, dx / length * half_w
    return (
        (x0 + nx, y0 + ny),
        (x1 + nx, y1 + ny),
        (x1 - nx, y1 - ny),
        (x0 - nx, y0 - ny),
    )


# ─── 输入规格（dataclass，构造期校验） ───────────────────────────────────────


@dataclass(frozen=True)
class TraceSpec:
    """走线段规格（mm）：p0→p1 加宽 width_mm 的细长矩形。"""

    trace_id: str
    x0: float
    y0: float
    x1: float
    y1: float
    width_mm: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", str(self.trace_id))
        for name in ("x0", "y0", "x1", "y1"):
            object.__setattr__(self, name, _finite(getattr(self, name), f"TraceSpec.{name}"))
        object.__setattr__(self, "width_mm", _positive(self.width_mm, "TraceSpec.width_mm"))

    @property
    def p0(self) -> Point:
        return (self.x0, self.y0)

    @property
    def p1(self) -> Point:
        return (self.x1, self.y1)

    def polygon(self) -> tuple[Point, ...]:
        """走线矩形四角（垂直加宽，调用期现算）。"""
        return trace_rectangle(self.p0, self.p1, self.width_mm)


@dataclass(frozen=True)
class SplitRegion:
    """平面分割区规格（mm）：简单多边形（槽/洞/另一参考域的边界）。

    构造期校验：≥3 点、坐标有限、无零长边、面积非零（退化 ValueError）。
    """

    split_id: str
    polygon: tuple[Point, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "split_id", str(self.split_id))
        object.__setattr__(
            self,
            "polygon",
            _validate_polygon(self.polygon, f"SplitRegion({self.split_id}).polygon"),
        )


@dataclass(frozen=True)
class ViaSpec:
    """过孔规格（mm 平面坐标）。"""

    via_id: str
    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "via_id", str(self.via_id))
        object.__setattr__(self, "x", _finite(self.x, "ViaSpec.x"))
        object.__setattr__(self, "y", _finite(self.y, "ViaSpec.y"))

    def point(self) -> Point:
        return (self.x, self.y)


# ─── 违规项与报告 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReturnPathIssue:
    """单条违规/警示（fab_check._violation 同族口径，dataclass+to_dict）。"""

    code: str
    severity: str
    rule: str
    element_id: str
    detail: str
    related_id: str | None = None
    position: Point | None = None
    value_mm: float | None = None
    limit_mm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "rule": self.rule,
            "element_id": self.element_id,
            "related_id": self.related_id,
            "position": None
            if self.position is None
            else [round(self.position[0], 9), round(self.position[1], 9)],
            "value_mm": None if self.value_mm is None else round(self.value_mm, 9),
            "limit_mm": None if self.limit_mm is None else round(self.limit_mm, 9),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ReturnPathReport:
    """回流路径检查报告（flag 级 verdict + 违规清单 + J(d) 文档化面）。"""

    verdict: str
    issues: list[ReturnPathIssue]
    counts: dict[str, Any]
    checked: dict[str, Any]
    j_model: dict[str, Any]

    @property
    def ok(self) -> bool:
        """flag 级无违规（warning 不影响）。"""
        return self.verdict == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "verdict": self.verdict,
            "issues": [i.to_dict() for i in self.issues],
            "counts": dict(self.counts),
            "checked": dict(self.checked),
            "j_model": dict(self.j_model),
        }


# ─── 主入口 ──────────────────────────────────────────────────────────────────


def _cross_position(
    tr_poly: tuple[Point, ...], sp_poly: tuple[Point, ...]
) -> Point:
    """R1 违规位置：第一条真交边对的交点；包含/纯接触场景回退到落入分割
    内部的首个走线顶点，再回退走线首顶点（确定性报告口径）。"""
    nt, ns = len(tr_poly), len(sp_poly)
    for i in range(nt):
        for j in range(ns):
            pt = _segment_intersection_point(
                tr_poly[i], tr_poly[(i + 1) % nt], sp_poly[j], sp_poly[(j + 1) % ns]
            )
            if pt is not None:
                return pt
    for v in tr_poly:
        if point_in_polygon(v, sp_poly):
            return v
    return tr_poly[0]


def check_return_path(
    *,
    traces: list[TraceSpec],
    splits: list[SplitRegion] | None = None,
    plane: list[Point] | tuple[Point, ...] | None = None,
    layer_change_vias: list[ViaSpec] | None = None,
    stitch_vias: list[ViaSpec] | None = None,
    via_return_distance_h_mm: float | None = None,
    edge_margin_widths: float = 3.0,
) -> ReturnPathReport:
    """回流路径不连续几何检查（flag 级 100% 几何；规则码表见模块 docstring）。

    Args:
        traces: 走线段清单（TraceSpec，mm）。
        splits: 平面分割区清单（可选；缺省无分割 → R1/R3 零违规恒等）。
        plane: 参考平面多边形（可选；R2 的平面边缘回流通道）。
        layer_change_vias: 换层过孔清单（可选；非空则 h 必须显式给出）。
        stitch_vias: 缝合孔清单（可选；R2 的过孔回流通道）。
        via_return_distance_h_mm: R2 距离门限 h（mm，>0；换层过孔非空时必填）。
        edge_margin_widths: R3 的 3w 惯例倍数（缺省 3.0，显式可覆盖）。

    Returns:
        ReturnPathReport（verdict=PASS|FAIL 按 flag 级；warning 不改判）。

    Raises:
        ValueError: 退化几何（<3 点/共线/零长边/零长度或非正宽走线）、
            NaN/bool 入参、给了换层过孔但缺 h、给了换层过孔但既无平面
            又无缝合孔（R2 无从评估）。
    """
    if not isinstance(traces, list) or any(not isinstance(t, TraceSpec) for t in traces):
        raise ValueError("traces 必须为 TraceSpec 列表")
    split_list = list(splits) if splits is not None else []
    if any(not isinstance(s, SplitRegion) for s in split_list):
        raise ValueError("splits 必须为 SplitRegion 列表")
    plane_poly = None if plane is None else _validate_polygon(plane, "plane")
    via_list = list(layer_change_vias) if layer_change_vias is not None else []
    if any(not isinstance(v, ViaSpec) for v in via_list):
        raise ValueError("layer_change_vias 必须为 ViaSpec 列表")
    stitch_list = list(stitch_vias) if stitch_vias is not None else []
    if any(not isinstance(v, ViaSpec) for v in stitch_list):
        raise ValueError("stitch_vias 必须为 ViaSpec 列表")
    margin = _positive(edge_margin_widths, "edge_margin_widths")
    h: float | None = None
    if via_list:
        if via_return_distance_h_mm is None:
            raise ValueError(
                "给了 layer_change_vias 但缺 via_return_distance_h_mm"
                "（h 门限无普适惯例值，必须显式给出）"
            )
        h = _positive(via_return_distance_h_mm, "via_return_distance_h_mm")
        if plane_poly is None and not stitch_list:
            raise ValueError(
                "R2 无从评估：layer_change_vias 给了但既无 plane 也无 "
                "stitch_vias（无可量测回流参考）"
            )

    issues: list[ReturnPathIssue] = []
    # R1 + R3：走线 × 分割逐对评估（R1 flag 优先，同对不再报 R3——不双报）
    for tr in traces:
        tr_poly = tr.polygon()
        for sp in split_list:
            sp_poly = sp.polygon
            if polygons_intersect(tr_poly, sp_poly):
                issues.append(
                    ReturnPathIssue(
                        code="TRACE_CROSS_SPLIT",
                        severity=SEVERITY_FLAG,
                        rule="R1",
                        element_id=tr.trace_id,
                        related_id=sp.split_id,
                        position=_cross_position(tr_poly, sp_poly),
                        detail=(
                            f"走线 {tr.trace_id} 与平面分割 {sp.split_id} 相交"
                            "（回流被分割缝打断，flag 级）"
                        ),
                    )
                )
                continue
            d, closest = _polygons_distance_and_point(tr_poly, sp_poly)
            threshold = margin * tr.width_mm
            if d < threshold:
                issues.append(
                    ReturnPathIssue(
                        code="TRACE_EDGE_MARGIN",
                        severity=SEVERITY_WARNING,
                        rule="R3",
                        element_id=tr.trace_id,
                        related_id=sp.split_id,
                        position=closest,
                        value_mm=d,
                        limit_mm=threshold,
                        detail=(
                            f"走线 {tr.trace_id} 距分割 {sp.split_id} 边缘 "
                            f"{d:.6g}mm < {margin:g}w={threshold:.6g}mm"
                            f"（3w 惯例，w={tr.width_mm:g}mm），warning 级"
                        ),
                    )
                )
    # R2：换层过孔 → 最近回流参考距离
    for via in via_list:
        vp = via.point()
        if plane_poly is not None and not point_in_polygon_inclusive(vp, plane_poly):
            issues.append(
                ReturnPathIssue(
                    code="VIA_OUTSIDE_PLANE",
                    severity=SEVERITY_FLAG,
                    rule="R2",
                    element_id=via.via_id,
                    related_id=None,
                    position=vp,
                    detail=(
                        f"换层过孔 {via.via_id} 在参考平面多边形外（含边界口径"
                        "判定）——下方无回流平面，flag 级"
                    ),
                )
            )
            continue
        d_edge = (
            None
            if plane_poly is None
            else point_polygon_boundary_distance(vp, plane_poly)
        )
        d_stitch: float | None = None
        nearest_stitch: str | None = None
        if stitch_list:
            d_stitch = math.inf
            for sv in stitch_list:
                dd = point_distance(vp, sv.point())
                if dd < d_stitch:
                    d_stitch, nearest_stitch = dd, sv.via_id
        if d_stitch is not None and (d_edge is None or d_stitch <= d_edge):
            d, source = d_stitch, nearest_stitch
        elif d_edge is not None:
            d, source = d_edge, "plane_edge"
        else:  # 入口校验已拦，防御分支
            raise ValueError(f"换层过孔 {via.via_id} 无任何回流参考可量测")
        if h is not None and d > h:
            issues.append(
                ReturnPathIssue(
                    code="VIA_STITCH_DISTANCE",
                    severity=SEVERITY_FLAG,
                    rule="R2",
                    element_id=via.via_id,
                    related_id=source,
                    position=vp,
                    value_mm=d,
                    limit_mm=h,
                    detail=(
                        f"换层过孔 {via.via_id} 到最近回流参考（{source}）距离 "
                        f"{d:.6g}mm > 门限 h={h:.6g}mm（环路面积超标，flag 级）"
                    ),
                )
            )

    n_flag = sum(1 for i in issues if i.severity == SEVERITY_FLAG)
    counts: dict[str, Any] = {
        "total": len(issues),
        "flag": n_flag,
        "warning": len(issues) - n_flag,
    }
    for code in RULE_CODES:
        counts[code] = sum(1 for i in issues if i.code == code)
    checked: dict[str, Any] = {
        "units": "mm",
        "n_traces": len(traces),
        "n_splits": len(split_list),
        "plane_given": plane_poly is not None,
        "n_layer_change_vias": len(via_list),
        "n_stitch_vias": len(stitch_list),
        "via_return_distance_h_mm": h,
        "edge_margin_widths": margin,
        "edge_margin_rule": "warning iff d < edge_margin_widths*w（恰等不警）",
        "via_distance_rule": "flag iff d > h（恰等不 flag）；d=min(最近缝合孔,平面边缘)",
    }
    j_model: dict[str, Any] = {
        "formula": RETURN_CURRENT_MODEL_FORMULA,
        "note": RETURN_CURRENT_MODEL_NOTE,
        "quantitative": False,
    }
    return ReturnPathReport(
        verdict="FAIL" if n_flag else "PASS",
        issues=issues,
        counts=counts,
        checked=checked,
        j_model=j_model,
    )
