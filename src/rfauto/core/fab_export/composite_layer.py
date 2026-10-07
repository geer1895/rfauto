"""覆铜板复合层组板（L0 纯领域：零文件 IO、零 ezdxf/OCC 依赖）.

核心规范（自 E:\\协助调研\\cad导出\\改动总结-复合层DXF导出.md §1.1/§2.3/
§2.4 吸收，ge5 Goal Wave3 F 组）：

- **复合层 = 介质板 + 与之 Z 向贴合的金属层**（常见顶铜+介质+底铜），
  按「物理贴合」自动组板，不是「HFSS 对象 = 一块板」；
- DXF 图层固定 4 个：``M1``（顶侧金属，同侧多片合并语义）／``M2``
  （底侧金属）／``sub``（中间介质，含外形）／``patch``（通孔，完整
  不简化）；
- 无依托通孔物理过滤：板外／骑边悬空孔删除，删除留痕清单随结果返回
  （骑边槽孔按工艺调 ``keep_edge_mm``）。

对象名语义（仅用于分类溯源，图层命名不依赖对象名）：``sub*`` 介质、
``G*``/``M*`` 金属、``via*``/``chao*`` 过孔圆柱。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

Point = tuple[float, float]

#: DXF 四图层固定命名（与源仓口径逐字一致）
COMPOSITE_LAYERS = ("M1", "M2", "sub", "patch")

#: Z 向贴合判定容差（mm，源仓 ADJ_TOL）
ADJ_TOL_MM = 1e-3

_SUB_PREFIXES = ("sub", "SUB", "Sub")
_VIA_PREFIXES = ("via", "chao")
_METAL_PREFIXES = ("g", "m")


@dataclass
class CompositeObject:
    """单个几何对象的 XY 投影 + Z 范围描述（纯几何，零引擎依赖）.

    outlines 为 XY 外形环列表（mm；多环时按 even-odd 解释内外，
    板的开槽/开孔即内环）；circles 为 (圆心, 半径) 圆孔/圆柱投影。
    """

    name: str
    material: str  # "metal" | "dielectric"
    z0: float  # 底面 z（mm）
    z1: float  # 顶面 z（mm）
    outlines: list[list[Point]] = field(default_factory=list)
    circles: list[tuple[Point, float]] = field(default_factory=list)

    @property
    def thickness(self) -> float:
        return self.z1 - self.z0


@dataclass
class CompositeLayers:
    """组板结果：四图层对象分组 + 未归属留痕（多报不放过，#316 方向）."""

    M1: list[CompositeObject] = field(default_factory=list)
    M2: list[CompositeObject] = field(default_factory=list)
    sub: list[CompositeObject] = field(default_factory=list)
    patch: list[CompositeObject] = field(default_factory=list)
    unassigned: list[CompositeObject] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def layer_of(self, key: str) -> list[CompositeObject]:
        return getattr(self, key)

    def as_dict(self) -> dict[str, list[str]]:
        """图层 → 对象名列表（JSON 进出/审计留痕用）."""
        return {
            "M1": [o.name for o in self.M1],
            "M2": [o.name for o in self.M2],
            "sub": [o.name for o in self.sub],
            "patch": [o.name for o in self.patch],
            "unassigned": [o.name for o in self.unassigned],
        }


def classify_object(obj: CompositeObject) -> str:
    """对象 → 图层类别（"M1"/"M2"/"sub"/"patch"/"metal"/"dielectric"）.

    先按对象名语义（via*/chao* → patch；sub* → sub），无语义命中再按
    材质字段（metal/dielectric），M1/M2 侧别留给组板阶段按 Z 贴合定。
    """
    low = obj.name.lower()
    if low.startswith(_VIA_PREFIXES):
        return "patch"
    if low.startswith(_SUB_PREFIXES):
        return "sub"
    mat = obj.material.strip().lower()
    if mat.startswith("diel"):
        return "sub"
    if "metal" in mat or mat in ("copper", "cu", "pec", "copper_ann"):
        return "metal"
    if low.startswith(_METAL_PREFIXES):
        return "metal"
    return mat or "unknown"


def _touches(a0: float, a1: float, b: float, tol: float) -> bool:
    return abs(a0 - b) <= tol or abs(a1 - b) <= tol


def group_composite_layers(
    objects: Sequence[CompositeObject],
    *,
    adj_tol_mm: float = ADJ_TOL_MM,
) -> CompositeLayers:
    """按 Z 向物理贴合把对象列表组为复合层（源仓 §2.3 规范）.

    规则：
    - ``sub``：全部介质对象（介质=板；多块介质各自保留，多层叠板场景
      每块一块板）；
    - ``patch``：via*/chao* 语义或 classify 为过孔的圆柱——本组板层只认
      名义语义（几何级圆柱识别属 B-rep 投影面，见 brep_projection_spec）；
    - ``M1``/``M2``：金属贴到某块介质的**顶面**（z0≈board.z1）→ M1、
      **底面**（z1≈board.z0）→ M2；同侧多片各自保留（合并是 DXF 图层
      语义，不是几何并集）；嵌在板厚内部的金属按距上/下表面近者归属并
      留 note（如实提示，不静默丢弃）；
    - 贴不到任何介质面的金属/未知对象 → ``unassigned``（不进任何图层）。
    """
    layers = CompositeLayers()
    boards = [o for o in objects if classify_object(o) == "sub"]
    vias = [o for o in objects if classify_object(o) == "patch"]

    layers.sub = list(boards)
    layers.patch = list(vias)

    board_ids = {id(b) for b in boards}
    via_ids = {id(v) for v in vias}
    for obj in objects:
        if id(obj) in board_ids or id(obj) in via_ids:
            continue
        kind = classify_object(obj)
        if kind == "sub":
            continue
        if kind != "metal":
            # 非金属非介质非过孔（材质未知等）→ unassigned，不冒充归类
            layers.unassigned.append(obj)
            continue
        side = _metal_side(obj, boards, adj_tol_mm, layers.notes)
        if side == "M1":
            layers.M1.append(obj)
        elif side == "M2":
            layers.M2.append(obj)
        else:
            layers.unassigned.append(obj)
    return layers


def _metal_side(
    obj: CompositeObject,
    boards: Sequence[CompositeObject],
    tol: float,
    notes: list[str],
) -> str:
    """金属 → 侧别：顶贴 M1 / 底贴 M2 / 内嵌按近侧 / 不贴 ""."""
    top_touch = any(_touches(obj.z0, obj.z1, b.z1, tol) for b in boards)
    bot_touch = any(_touches(obj.z0, obj.z1, b.z0, tol) for b in boards)
    if top_touch and not bot_touch:
        # 金属底面贴板顶面 → 顶侧金属
        return "M1"
    if bot_touch and not top_touch:
        # 金属顶面贴板底面 → 底侧金属
        return "M2"
    if top_touch and bot_touch:
        # 两板之间的键合金属：四图层模型无内层，按惯例归 M1 并留痕
        notes.append(
            f"bonding metal '{obj.name}' touches boards on both z sides; "
            "assigned M1 (no inner layer in M1/M2/sub/patch model)"
        )
        return "M1"
    # 内嵌：金属 z 范围落在某块板厚内部
    best: tuple[float, str] | None = None
    for b in boards:
        if b.z0 <= obj.z0 and obj.z1 <= b.z1:
            d_top = abs(b.z1 - obj.z1)
            d_bot = abs(obj.z0 - b.z0)
            cand = ("M1", d_top) if d_top <= d_bot else ("M2", d_bot)
            if best is None or cand[1] < best[1]:
                best = cand
    if best is not None:
        notes.append(
            f"embedded metal '{obj.name}' assigned to {best[0]} by nearest face "
            f"(distance {best[1]:.6g} mm)"
        )
        return best[0]
    return ""


# ─── 无依托通孔物理过滤（源仓 §2.4 physics_filter 规范） ────────────────


@dataclass
class RemovedHole:
    """被过滤孔留痕（删除清单随导出交付，审计可回溯）."""

    name: str
    center: Point
    radius: float
    reason: str  # "outside" 板外 | "edge" 骑边/边距不足


def _point_in_loops(px: float, py: float, loops: Sequence[Sequence[Point]]) -> bool:
    """even-odd 规则：点在环集内部（跨全部环射线计数为奇）."""
    inside = False
    for pts in loops:
        n = len(pts)
        j = n - 1
        for i in range(n):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi + 1e-30) + xi:
                inside = not inside
            j = i
    return inside


def _dist_point_to_loop_edges(px: float, py: float, loops: Sequence[Sequence[Point]]) -> float:
    mind = math.inf
    for pts in loops:
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            dx, dy = x2 - x1, y2 - y1
            if dx == 0 and dy == 0:
                d = math.hypot(px - x1, py - y1)
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
                d = math.hypot(px - x1 - t * dx, py - y1 - t * dy)
            mind = min(mind, d)
    return mind


def filter_unsupported_holes(
    holes: Sequence[tuple[str, Point, float]],
    board_loops: Sequence[Sequence[Sequence[Point]]],
    *,
    keep_edge_mm: float = 0.1,
) -> dict:
    """无依托通孔物理过滤（板外/骑边悬空孔删除+留痕）.

    board_loops：**逐板**外形环组（板 → 该板的环列表 → 点列）；单板
    多环时板内 even-odd 解释内外（外形开槽=内环）。孔被**任一单板**
    even-odd 包含即有依托（ge5 审查 F8 修复：多板 XY 重叠叠层不得把
    各板奇偶计数混在一起——偶数块重叠板会把板内合法孔抵消成"板外"
    全删）；clearance 取全部依托板边距的最小值。

    keep_edge_mm：孔缘到介质外形的最小留边（mm）——圆整落在介质内且
    留边 ≥ keep_edge_mm 才保留；缺省 0.1 mm 保守值（常规最小环宽量级）。
    骑边槽孔若工艺允许保留，调大 0（贴边即留）或按工艺值放宽。

    返回 {kept, removed, counts}；removed 为留痕清单（#316 方向：
    删了什么必须可回溯）。
    """
    kept: list[tuple[str, Point, float]] = []
    removed: list[RemovedHole] = []
    boards = [[list(p) for p in board if len(p) >= 3] for board in board_loops]
    boards = [b for b in boards if b]
    if not boards:
        # 无外形可依托：全删并留痕（无依托即无支撑，多报不放过）
        for name, c, r in holes:
            removed.append(RemovedHole(name=name, center=c, radius=r, reason="outside"))
        return {
            "kept": [],
            "removed": removed,
            "counts": {"kept": 0, "removed": len(removed), "total": len(holes)},
            "rule": "no-outline",
        }
    for name, (cx, cy), r in holes:
        clearances = [
            _dist_point_to_loop_edges(cx, cy, board) - r
            for board in boards
            if _point_in_loops(cx, cy, board)
        ]
        if not clearances:
            removed.append(RemovedHole(name=name, center=(cx, cy), radius=r, reason="outside"))
            continue
        if min(clearances) < keep_edge_mm:
            removed.append(
                RemovedHole(name=name, center=(cx, cy), radius=r, reason="edge")
            )
            continue
        kept.append((name, (cx, cy), r))
    return {
        "kept": kept,
        "removed": removed,
        "counts": {"kept": len(kept), "removed": len(removed), "total": len(holes)},
        "rule": f"keep_edge_mm={keep_edge_mm:g}",
    }
