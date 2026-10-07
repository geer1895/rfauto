"""LC-3 RF 保护结构生成套件（round15 §四 LC-3）。

规格原文（研究扩充 round15 §四 LC 系列）：
"LC-3 RF 保护结构生成套件（P1/M）：任意折线 via fence/CPW 共面地+缝合带/
缝合网格/地板开窗 统一'生成器+return_path_check 复验'闭环。验收：生成→
R1/R2 零违规自检用例。"

套件清单（四族生成器 + 一个统一复验闭环）：
- ``via_fence_polyline``   任意折线接地护墙（via fence；closed=True 即护环）
- ``via_fence_ring``       矩形闭合护环（折线特例糖衣，PCell 内核落点）
- ``cpw_ground_stitch``    CPW 共面地 + 缝合带（两侧地内缝合孔排）
- ``stitch_mesh``          缝合网格（矩形孔阵）
- ``ground_void``          地板开窗（可选护窗栅栏）
- ``guard_return_path_check``  统一复验闭环：生成产物 → return_path_check
  R1/R2 复验（本函数零规则逻辑，规则判定 100% 出 core/return_path_check
  单一裁判源）

口径：
- 单位一律 mm（参数名带 _mm；与 layout_interchange.Layout 内部口径一致，
  LC-2 PCell 渲染桥零换算直出；本模块不 import adapters——layout_generator
  的直线 via fence 在 adapters 层，本模块按同口径自含实现任意折线版，
  core 叶不得反向依赖上层）；
- 数值只在确定性内核（铁律 7）：纯几何闭式生成，零仿真零网络零文件 I/O；
- via fence 放孔口径（与 adapters/layout_generator.via_fence_items 同口径）：
  每段从 offset 起每 pitch 一个，s ≤ seg_len + 1e-12 计入；跨段共享端点按
  1nm 格点去重（先到先得）；零长段跳过（显式闭合点传入即自然跳过）；
- 折线自相交不判（护墙沿自交路径放孔几何上无害，不做拓扑检查——如实声明
  NO-GO 边界）。

消费面：pcell_dsl.KERNEL_REGISTRY 的 guard_* 四内核（LC-2 注册表生态，
rfauto pcell list/show/eval/render 自动可达）；复验闭环供测试/服务层按
"生成 → 复验"直接装配。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from rfauto.core.return_path_check import (
    ReturnPathReport,
    SplitRegion,
    TraceSpec,
    ViaSpec,
    check_return_path,
)

__all__ = [
    "CpwGroundStitch",
    "GroundVoid",
    "GuardVia",
    "StitchMesh",
    "cpw_ground_stitch",
    "ground_void",
    "guard_return_path_check",
    "stitch_mesh",
    "via_fence_polyline",
    "via_fence_ring",
]

#: 平面点（mm，与 return_path_check 同型）
Point = tuple[float, float]

#: 跨段共享端点去重格点（1nm，与 layout_generator.via_fence_items 同口径）
_DEDUP_GRID_PER_MM = 1e6

#: 距离比较容差（mm；恰等不 flag/不警口径的浮点余量）
_TOL_MM = 1e-9


# ─── 数值守卫（bool 显式拒收，df7+⑯；判缺失 is not None，#364④） ────────────


def _num(value: Any, name: str) -> float:
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


def _pos(value: Any, name: str) -> float:
    out = _num(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，收到 {out!r}")
    return out


def _nonneg(value: Any, name: str) -> float:
    out = _num(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 ≥0，收到 {out!r}")
    return out


def _pt(pt: Any, name: str) -> Point:
    try:
        x, y = pt
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: 点必须是 (x, y) 二元组") from exc
    return (_num(x, f"{name}.x"), _num(y, f"{name}.y"))


def _polyline(points: Any, name: str, min_pts: int = 2) -> tuple[Point, ...]:
    """折线校验+归一（≥min_pts 个 (x,y)，坐标有限），违规 ValueError。"""
    if points is None:
        raise ValueError(f"{name}: 折线缺失")
    try:
        raw = list(points)
    except TypeError as exc:
        raise ValueError(f"{name}: 折线必须是点序列") from exc
    if len(raw) < min_pts:
        raise ValueError(f"{name}: 至少 {min_pts} 个点，得到 {len(raw)}")
    return tuple(_pt(p, f"{name}[{i}]") for i, p in enumerate(raw))


def _rect_polygon(x0: float, y0: float, x1: float, y1: float
                  ) -> tuple[Point, ...]:
    """轴对齐矩形四角（闭合不重复首点，逆时针）。"""
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


# ─── 产物数据模型 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GuardVia:
    """护墙/缝合过孔（mm）：位置 + 焊盘/钻孔直径 + 焊盘层。"""

    name: str
    position: Point
    pad_diameter_mm: float
    drill_diameter_mm: float
    pad_layer: str = "F.Cu"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": [self.position[0], self.position[1]],
            "pad_diameter_mm": self.pad_diameter_mm,
            "drill_diameter_mm": self.drill_diameter_mm,
            "pad_layer": self.pad_layer,
        }

    def to_flat(self) -> dict[str, Any]:
        """pcell kernel 面直出形状（pcell_dsl._via_geom_from_flat 消费）。"""
        return {
            "pad_layer": self.pad_layer,
            "name": self.name,
            "position": [self.position[0], self.position[1]],
            "pad_diameter": self.pad_diameter_mm,
            "drill_diameter": self.drill_diameter_mm,
        }


@dataclass(frozen=True)
class CpwGroundStitch:
    """CPW 共面地+缝合带产物：中心带/两侧地多边形 + 缝合孔排（mm）。"""

    center_trace: tuple[Point, ...]
    ground_left: tuple[Point, ...]
    ground_right: tuple[Point, ...]
    vias: tuple[GuardVia, ...]
    gap_edge_offset_mm: float  # w/2+gap：缝合带基准线到中心线的距离

    def to_dict(self) -> dict[str, Any]:
        return {
            "center_trace": [list(p) for p in self.center_trace],
            "ground_left": [list(p) for p in self.ground_left],
            "ground_right": [list(p) for p in self.ground_right],
            "vias": [v.to_dict() for v in self.vias],
            "gap_edge_offset_mm": self.gap_edge_offset_mm,
        }


@dataclass(frozen=True)
class StitchMesh:
    """缝合网格产物：矩形孔阵（行主序命名，mm）。"""

    origin: Point
    n_x: int
    n_y: int
    pitch_x_mm: float
    pitch_y_mm: float
    vias: tuple[GuardVia, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": [self.origin[0], self.origin[1]],
            "n_x": self.n_x,
            "n_y": self.n_y,
            "pitch_x_mm": self.pitch_x_mm,
            "pitch_y_mm": self.pitch_y_mm,
            "vias": [v.to_dict() for v in self.vias],
        }


@dataclass(frozen=True)
class GroundVoid:
    """地板开窗产物：平面/开窗多边形 + 可选护窗栅栏（mm）。

    void_polygon 即 return_path_check 的 SplitRegion 载体（R1 的分割区）；
    fence_vias 即缝合孔载体（R2 的过孔回流通道）。
    """

    plane_polygon: tuple[Point, ...]
    void_polygon: tuple[Point, ...]
    fence_vias: tuple[GuardVia, ...]
    fence_offset_mm: float | None
    fence_path: tuple[Point, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plane_polygon": [list(p) for p in self.plane_polygon],
            "void_polygon": [list(p) for p in self.void_polygon],
            "fence_vias": [v.to_dict() for v in self.fence_vias],
            "fence_offset_mm": self.fence_offset_mm,
            "fence_path": [list(p) for p in self.fence_path],
        }


# ─── 生成器 1：任意折线 via fence ────────────────────────────────────────────


def via_fence_polyline(
    points: Sequence[Sequence[float]],
    pitch_mm: float,
    pad_diameter_mm: float,
    drill_diameter_mm: float,
    *,
    offset_mm: float = 0.0,
    pad_layer: str = "F.Cu",
    closed: bool = False,
    name_prefix: str = "guard_via",
) -> tuple[GuardVia, ...]:
    """沿任意折线放接地护墙孔（LC-3 头牌；closed=True 即闭合护环）。

    放孔口径：每段从 offset 起每 pitch 一个，s ≤ seg_len + 1e-12 计入；
    跨段共享端点按 1nm 格点去重（先到先得）；零长段跳过（显式闭合点
    传入即自然跳过）。折线自相交不判（NO-GO 边界，见模块 docstring）。
    """
    pitch = _pos(pitch_mm, "pitch_mm")
    pad = _pos(pad_diameter_mm, "pad_diameter_mm")
    drill = _pos(drill_diameter_mm, "drill_diameter_mm")
    if not pad > drill:
        raise ValueError(
            f"焊盘直径 {pad} 必须大于钻孔直径 {drill}")
    off = _nonneg(offset_mm, "offset_mm")
    pts = _polyline(points, "points", 2)
    path: list[Point] = list(pts)
    if closed and path[0] != path[-1]:
        path.append(path[0])
    vias: list[GuardVia] = []
    seen: set[tuple[int, int]] = set()
    for (x1, y1), (x2, y2) in pairwise(path):
        seg_len = math.hypot(x2 - x1, y2 - y1)
        if seg_len <= 0.0:
            continue
        if seg_len < off:
            continue
        ux, uy = (x2 - x1) / seg_len, (y2 - y1) / seg_len
        n_posts = math.floor((seg_len - off) / pitch + 1e-12) + 1
        for k in range(n_posts):
            s = off + k * pitch
            if s > seg_len + 1e-12:
                break
            px, py = x1 + ux * s, y1 + uy * s
            key = (round(px * _DEDUP_GRID_PER_MM), round(py * _DEDUP_GRID_PER_MM))
            if key in seen:
                continue
            seen.add(key)
            vias.append(GuardVia(
                name=f"{name_prefix}_{len(vias) + 1:03d}",
                position=(px, py),
                pad_diameter_mm=pad,
                drill_diameter_mm=drill,
                pad_layer=str(pad_layer),
            ))
    return tuple(vias)


def via_fence_ring(
    width_mm: float,
    height_mm: float,
    pitch_mm: float,
    pad_diameter_mm: float,
    drill_diameter_mm: float,
    *,
    x0_mm: float = 0.0,
    y0_mm: float = 0.0,
    pad_layer: str = "F.Cu",
    name_prefix: str = "ring_via",
) -> tuple[GuardVia, ...]:
    """矩形闭合护环（折线特例糖衣）：孔中心落在 (x0,y0) 起的 w×h 周长上。"""
    w = _pos(width_mm, "width_mm")
    h = _pos(height_mm, "height_mm")
    x0 = _num(x0_mm, "x0_mm")
    y0 = _num(y0_mm, "y0_mm")
    corners = _rect_polygon(x0, y0, x0 + w, y0 + h)
    return via_fence_polyline(
        corners, pitch_mm, pad_diameter_mm, drill_diameter_mm,
        pad_layer=pad_layer, closed=True, name_prefix=name_prefix)


# ─── 生成器 2：CPW 共面地 + 缝合带 ───────────────────────────────────────────


def cpw_ground_stitch(
    length_mm: float,
    w_mm: float,
    gap_mm: float,
    ground_width_mm: float,
    strap_pitch_mm: float,
    pad_diameter_mm: float,
    drill_diameter_mm: float,
    *,
    inset_mm: float = 0.5,
    x0_mm: float = 0.0,
    y0_mm: float = 0.0,
    pad_layer: str = "F.Cu",
) -> CpwGroundStitch:
    """CPW 共面地+缝合带：中心带沿 +x（y=y0 对称），两侧地内缝合孔排。

    几何：缝缘在 y = y0 ± (w/2+gap)；地矩形从缝缘向外延伸 ground_width；
    缝合带每侧一排，孔心距缝缘 inset，x 从 x0+pad/2 起每 strap_pitch 一个、
    孔焊盘完整落在地矩形内（含边界，1e-9 容差）——首孔焊盘与地矩形起边
    相切即计入。守卫（非物理律、建模卫生，违规显式报错）：
    inset ≥ pad/2（焊盘不越缝缘）且 inset + pad/2 ≤ ground_width（焊盘
    不越地外缘）；length ≥ pad（缝合带至少放下一孔）。
    """
    length = _pos(length_mm, "length_mm")
    w = _pos(w_mm, "w_mm")
    gap = _pos(gap_mm, "gap_mm")
    gw = _pos(ground_width_mm, "ground_width_mm")
    strap_pitch = _pos(strap_pitch_mm, "strap_pitch_mm")
    pad = _pos(pad_diameter_mm, "pad_diameter_mm")
    drill = _pos(drill_diameter_mm, "drill_diameter_mm")
    if not pad > drill:
        raise ValueError(f"焊盘直径 {pad} 必须大于钻孔直径 {drill}")
    inset = _nonneg(inset_mm, "inset_mm")
    if inset < pad / 2.0 - _TOL_MM:
        raise ValueError(
            f"缝合孔内缩 inset={inset} 必须 ≥pad/2={pad / 2.0}"
            "（焊盘不得越缝缘）")
    if inset + pad / 2.0 > gw + _TOL_MM:
        raise ValueError(
            f"缝合孔内缩 inset={inset} + pad/2={pad / 2.0} 不得超过地宽 "
            f"ground_width={gw}（焊盘须完整落在地内）")
    if length < pad - _TOL_MM:
        raise ValueError(
            f"线长 length={length} 必须 ≥焊盘直径 {pad}（缝合带至少放下一孔）")
    x0 = _num(x0_mm, "x0_mm")
    y0 = _num(y0_mm, "y0_mm")
    layer = str(pad_layer)

    edge = w / 2.0 + gap  # 缝缘到中心线距离
    center = _rect_polygon(x0, y0 - w / 2.0, x0 + length, y0 + w / 2.0)
    gnd_left = _rect_polygon(x0, y0 + edge, x0 + length, y0 + edge + gw)
    gnd_right = _rect_polygon(x0, y0 - edge - gw, x0 + length, y0 - edge)

    n_straps = math.floor((length - pad) / strap_pitch + 1e-12) + 1
    vias: list[GuardVia] = []
    for k in range(n_straps):
        sx = x0 + pad / 2.0 + k * strap_pitch
        for sy in (y0 + edge + inset, y0 - edge - inset):
            vias.append(GuardVia(
                name=f"strap_{k + 1:03d}_{'p' if sy > y0 else 'm'}",
                position=(sx, sy),
                pad_diameter_mm=pad,
                drill_diameter_mm=drill,
                pad_layer=layer))
    return CpwGroundStitch(
        center_trace=center, ground_left=gnd_left, ground_right=gnd_right,
        vias=tuple(vias), gap_edge_offset_mm=edge)


# ─── 生成器 3：缝合网格 ──────────────────────────────────────────────────────


def stitch_mesh(
    width_mm: float,
    height_mm: float,
    pitch_x_mm: float,
    pitch_y_mm: float,
    pad_diameter_mm: float,
    drill_diameter_mm: float,
    *,
    x0_mm: float = 0.0,
    y0_mm: float = 0.0,
    pad_layer: str = "F.Cu",
) -> StitchMesh:
    """缝合网格：矩形孔阵，n_x×n_y = (floor(w/px)+1)×(floor(h/py)+1)。

    孔位 (x0+i·px, y0+j·py)，行主序命名 mesh_r{row}c{col}（row 沿 y、
    col 沿 x，均自 1 起）。
    """
    w = _pos(width_mm, "width_mm")
    h = _pos(height_mm, "height_mm")
    px = _pos(pitch_x_mm, "pitch_x_mm")
    py = _pos(pitch_y_mm, "pitch_y_mm")
    pad = _pos(pad_diameter_mm, "pad_diameter_mm")
    drill = _pos(drill_diameter_mm, "drill_diameter_mm")
    if not pad > drill:
        raise ValueError(f"焊盘直径 {pad} 必须大于钻孔直径 {drill}")
    x0 = _num(x0_mm, "x0_mm")
    y0 = _num(y0_mm, "y0_mm")
    n_x = math.floor(w / px + 1e-12) + 1
    n_y = math.floor(h / py + 1e-12) + 1
    vias: list[GuardVia] = []
    for j in range(n_y):
        for i in range(n_x):
            vias.append(GuardVia(
                name=f"mesh_r{j + 1:03d}c{i + 1:03d}",
                position=(x0 + i * px, y0 + j * py),
                pad_diameter_mm=pad,
                drill_diameter_mm=drill,
                pad_layer=str(pad_layer)))
    return StitchMesh(
        origin=(x0, y0), n_x=n_x, n_y=n_y, pitch_x_mm=px, pitch_y_mm=py,
        vias=tuple(vias))


# ─── 生成器 4：地板开窗 ──────────────────────────────────────────────────────


def ground_void(
    plane_width_mm: float,
    plane_height_mm: float,
    void_cx_mm: float,
    void_cy_mm: float,
    void_w_mm: float,
    void_h_mm: float,
    *,
    x0_mm: float = 0.0,
    y0_mm: float = 0.0,
    fence_offset_mm: float | None = None,
    fence_pitch_mm: float = 1.0,
    fence_pad_mm: float = 0.6,
    fence_drill_mm: float = 0.3,
    pad_layer: str = "F.Cu",
) -> GroundVoid:
    """地板开窗：平面内矩形挖铜窗 + 可选护窗栅栏（闭合计一圈）。

    守卫：开窗必须严格落在平面内部（四边留正余量；贴边即与平面边界合并
    成非简单分割，显式报错）。fence_offset_mm is not None 时沿开窗四周
    外扩 fence_offset 的闭合矩形放护窗栅栏（孔心距开窗边界恰 = offset），
    栅栏路径同样须严格落在平面内。
    """
    pw = _pos(plane_width_mm, "plane_width_mm")
    ph = _pos(plane_height_mm, "plane_height_mm")
    vw = _pos(void_w_mm, "void_w_mm")
    vh = _pos(void_h_mm, "void_h_mm")
    cx = _num(void_cx_mm, "void_cx_mm")
    cy = _num(void_cy_mm, "void_cy_mm")
    x0 = _num(x0_mm, "x0_mm")
    y0 = _num(y0_mm, "y0_mm")
    plane = _rect_polygon(x0, y0, x0 + pw, y0 + ph)
    vx0, vy0 = cx - vw / 2.0, cy - vh / 2.0
    vx1, vy1 = cx + vw / 2.0, cy + vh / 2.0
    if (vx0 <= x0 + _TOL_MM or vx1 >= x0 + pw - _TOL_MM
            or vy0 <= y0 + _TOL_MM or vy1 >= y0 + ph - _TOL_MM):
        raise ValueError(
            f"开窗 [{vx0}, {vy0}]-[{vx1}, {vy1}] 必须严格落在平面 "
            f"[{x0}, {y0}]-[{x0 + pw}, {y0 + ph}] 内部（贴边即退化）")
    void = _rect_polygon(vx0, vy0, vx1, vy1)

    fence_vias: tuple[GuardVia, ...] = ()
    fence_path: tuple[Point, ...] = ()
    fence_offset: float | None = None
    if fence_offset_mm is not None:
        fence_offset = _pos(fence_offset_mm, "fence_offset_mm")
        fx0, fy0 = vx0 - fence_offset, vy0 - fence_offset
        fx1, fy1 = vx1 + fence_offset, vy1 + fence_offset
        if (fx0 <= x0 + _TOL_MM or fx1 >= x0 + pw - _TOL_MM
                or fy0 <= y0 + _TOL_MM or fy1 >= y0 + ph - _TOL_MM):
            raise ValueError(
                f"护窗栅栏路径 [{fx0}, {fy0}]-[{fx1}, {fy1}] 必须严格落在"
                f" 平面 [{x0}, {y0}]-[{x0 + pw}, {y0 + ph}] 内部")
        fence_path = _rect_polygon(fx0, fy0, fx1, fy1)
        fence_vias = via_fence_polyline(
            fence_path, fence_pitch_mm, fence_pad_mm, fence_drill_mm,
            pad_layer=pad_layer, closed=True, name_prefix="void_fence")
    return GroundVoid(
        plane_polygon=plane, void_polygon=void, fence_vias=fence_vias,
        fence_offset_mm=fence_offset, fence_path=fence_path)


# ─── 统一复验闭环（LC-3 验收面：生成 → R1/R2 零违规自检） ────────────────────


def guard_return_path_check(
    *,
    plane: Sequence[Sequence[float]],
    traces: Sequence[TraceSpec],
    splits: Sequence[Any] = (),
    stitch_vias: Sequence[GuardVia | ViaSpec] = (),
    layer_change_vias: Sequence[GuardVia | ViaSpec] = (),
    via_return_distance_h_mm: float | None = None,
    edge_margin_widths: float = 3.0,
) -> ReturnPathReport:
    """统一复验闭环：护墙/缝合/开窗产物 → return_path_check R1/R2 复验。

    纯装配薄层：R1/R2/R3 判定 100% 出 check_return_path（单一裁判源），
    本函数只把生成产物（GroundVoid.void_polygon / 护墙缝合孔 GuardVia）
    确定性转成裁判入参。splits 元素接受 SplitRegion 或多边形点列（后者
    自动命名 guard_split_{i}）；via 槽位接受 GuardVia 或 ViaSpec。
    """
    plane_poly = tuple(_pt(p, f"plane[{i}]") for i, p in enumerate(plane))
    split_list: list[SplitRegion] = []
    for i, sp in enumerate(splits):
        if isinstance(sp, SplitRegion):
            split_list.append(sp)
            continue
        poly = tuple(_pt(p, f"splits[{i}][{j}]")
                     for j, p in enumerate(sp))
        split_list.append(SplitRegion(f"guard_split_{i}", poly))

    def _via(v: GuardVia | ViaSpec) -> ViaSpec:
        if isinstance(v, ViaSpec):
            return v
        return ViaSpec(v.name, v.position[0], v.position[1])

    return check_return_path(
        traces=list(traces),
        splits=split_list,
        plane=plane_poly,
        layer_change_vias=[_via(v) for v in layer_change_vias],
        stitch_vias=[_via(v) for v in stitch_vias],
        via_return_distance_h_mm=(
            None if via_return_distance_h_mm is None
            else _pos(via_return_distance_h_mm,
                      "via_return_distance_h_mm")),
        edge_margin_widths=edge_margin_widths,
    )
