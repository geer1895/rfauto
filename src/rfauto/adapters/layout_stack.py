"""F-I P1 核心段：RF 叠层（LayerStack）schema + B2 Layout→渲染原语桥 + 斜段矩形化。

方案依据：研究扩充 round5 §二 F-I 三段计划 P1——
"斜段矩形化 + Layout→渲染桥（层名→金属/介质映射+图元转换纯函数）+ RF-LayerStack
schema（source 层选择器/zmin/thickness/material/kind/mesh_hint）"。

边界（P1 核心段，勿越界）
-------------------------
- 本模块是**纯函数面**：不调 CSXCAD、不写 render_script——渲染执行/叠层多层化/
  端口三来源/通用网格生成器/CLI·MCP 暴露属 P2 与接线批。
- 产出渲染原语为 plain dict（形态契约见 polygon_to_render_primitives），P2 的
  渲染器按 {kind: "polygon", coords, layer, ...} 消费并翻译成
  ``AddPolygon((xs, ys), norm_dir="z", elevation=z, priority=...)`` 字面量
  （openems_templates msl_top 锥形多边形同款惯例，本模块不 import 之）。

单位约定
--------
- B2 版图（layout_interchange.Layout）内部一律**毫米**；本模块桥接输出
  （primitives 的 coords/holes）一律**米**——openEMS 渲染字面量米制
  （kicad_board_render._m 同口径）。桥内显式 ``×1e-3``，不隐式。
- RFStackup 的 zmin_m/thickness_m 按任务书为**米**；mesh_hint_mm 为毫米
  （网格生成器 P2 的口径）。矩形化/校验函数本身单位无关（同一长度单位即可）。

依赖纪律
--------
- klayout=GPL-3 不进核心；shapely（BSD，venv 实测在装）用于有效性守卫与面积
  审计；gdstk 仅测试 fixture 链使用（本模块零 import，B2 已有惰性导入惯例）。
- 分层契约：adapters 层不 import service/cli/mcp_server（import-linter 强制）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

from rfauto.adapters.layout_interchange import (
    Layout,
    LayoutCircle,
    LayoutItem,
    LayoutLayer,
    LayoutPath,
    LayoutPolygon,
    LayoutVia,
    circle_to_polygon,
)

__all__ = [
    "LAYER_KINDS",
    "PRIMITIVE_SCHEMA_VERSION",
    "RFRouteLayer",
    "RFStackup",
    "bridge_layout_to_stackup",
    "dump_stackup",
    "load_stackup",
    "polygon_to_render_primitives",
    "rectangularize_segment",
    "stackup_from_dict",
    "stackup_to_dict",
    "validate_polygon",
]

#: 层作用全集（判据：金属/介质映射正确性的唯一口径）。
LAYER_KINDS: tuple[str, ...] = ("signal", "ground", "dielectric")

LayerKind = Literal["signal", "ground", "dielectric"]

#: 渲染原语 dict 形态版本（P2 渲染器消费时的兼容锚）。
PRIMITIVE_SCHEMA_VERSION = 1

#: B2 版图（mm）→ 渲染原语（m）的显式换算因子。
_MM_TO_M = 1e-3


# ---------------------------------------------------------------------------
# RF 叠层 schema（dataclass，跟随 B2 layout_interchange 惯例）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RFRouteLayer:
    """单层定义：层选择器 + z/厚度/材料/作用 + 网格提示。

    层选择器二态（严格口径，不猜）：
    - ``gds_layer`` 非 None → GDS 层号选择器：按 (gds_layer, gds_datatype) 匹配，
      ``gds_datatype`` 为 None 时对该 layer 号任意 datatype 通配；
    - ``gds_layer`` 为 None → 层名选择器：按 ``name`` 与版图层名全等匹配。
    """

    name: str
    zmin_m: float
    thickness_m: float
    material: str
    kind: LayerKind
    gds_layer: int | None = None
    gds_datatype: int | None = None
    mesh_hint_mm: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(f"层名必须为非空字符串: {self.name!r}")
        if not isinstance(self.material, str) or not self.material:
            raise ValueError(f"层 {self.name!r} 材料必须为非空字符串: {self.material!r}")
        if self.kind not in LAYER_KINDS:
            raise ValueError(
                f"层 {self.name!r} kind 必须在 {LAYER_KINDS} 内: {self.kind!r}"
            )
        for field_name in ("zmin_m", "thickness_m"):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"层 {self.name!r} {field_name} 必须为数值: {value!r}")
            if not math.isfinite(float(value)):
                raise ValueError(f"层 {self.name!r} {field_name} 必须有限: {value!r}")
        if float(self.thickness_m) < 0.0:
            raise ValueError(
                f"层 {self.name!r} thickness_m 必须非负（0=零厚金属片合法）: {self.thickness_m!r}"
            )
        if self.mesh_hint_mm is not None:
            hint = self.mesh_hint_mm
            if not isinstance(hint, (int, float)) or isinstance(hint, bool):
                raise ValueError(f"层 {self.name!r} mesh_hint_mm 必须为数值或 None: {hint!r}")
            if not math.isfinite(float(hint)) or float(hint) <= 0.0:
                raise ValueError(f"层 {self.name!r} mesh_hint_mm 必须为正有限值: {hint!r}")
        if self.gds_layer is not None and (
            not isinstance(self.gds_layer, int) or isinstance(self.gds_layer, bool)
        ):
            raise ValueError(f"层 {self.name!r} gds_layer 必须为整数或 None: {self.gds_layer!r}")
        if self.gds_datatype is not None and self.gds_layer is None:
            raise ValueError(
                f"层 {self.name!r} 指定了 gds_datatype 但未指定 gds_layer——"
                "datatype 通配只在 GDS 层号选择器下有意义"
            )

    def matches(self, gds_layer: int, gds_datatype: int, layer_name: str) -> bool:
        """层选择器匹配（严格二态，见类 docstring）。"""
        if self.gds_layer is not None:
            if gds_layer != self.gds_layer:
                return False
            return self.gds_datatype is None or gds_datatype == self.gds_datatype
        return layer_name == self.name


@dataclass
class RFStackup:
    """RF 叠层：有序层表（zmin/thickness 定义 z 域，P2 叠层多层化的输入）。"""

    name: str = "stackup"
    layers: tuple[RFRouteLayer, ...] = ()

    def layer_names(self) -> list[str]:
        return [layer.name for layer in self.layers]

    def require_layer(self, name: str) -> RFRouteLayer:
        for layer in self.layers:
            if layer.name == name:
                return layer
        raise KeyError(f"叠层 {self.name!r} 不含层 {name!r}；现有层: {self.layer_names()}")

    def find_layer(self, gds_layer: int, gds_datatype: int, layer_name: str) -> RFRouteLayer | None:
        """按层选择器找第一个匹配层；无匹配返回 None（桥接端显式跳过计数）。"""
        for layer in self.layers:
            if layer.matches(gds_layer, gds_datatype, layer_name):
                return layer
        return None


def stackup_to_dict(stackup: RFStackup) -> dict[str, Any]:
    """叠层 → 可 YAML 序列化 dict（字段名即键，None 字段显式落盘）。"""
    return {
        "name": stackup.name,
        "layers": [
            {
                "name": layer.name,
                "zmin_m": layer.zmin_m,
                "thickness_m": layer.thickness_m,
                "material": layer.material,
                "kind": layer.kind,
                "gds_layer": layer.gds_layer,
                "gds_datatype": layer.gds_datatype,
                "mesh_hint_mm": layer.mesh_hint_mm,
            }
            for layer in stackup.layers
        ],
    }


def stackup_from_dict(data: dict[str, Any]) -> RFStackup:
    """dict → 叠层（load 侧；字段校验由 RFRouteLayer.__post_init__ 承担）。"""
    if not isinstance(data, dict):
        raise ValueError(f"叠层定义必须是映射: {type(data).__name__}")
    name = data.get("name", "stackup")
    raw_layers = data.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise ValueError(f"叠层 {name!r} 必须含非空 layers 列表")
    layers = []
    for i, raw in enumerate(raw_layers):
        if not isinstance(raw, dict):
            raise ValueError(f"叠层 {name!r} 第 {i} 层必须是映射: {type(raw).__name__}")
        missing = [k for k in ("name", "zmin_m", "thickness_m", "material", "kind") if k not in raw]
        if missing:
            raise ValueError(f"叠层 {name!r} 第 {i} 层缺字段 {missing}")
        layers.append(
            RFRouteLayer(
                name=str(raw["name"]),
                zmin_m=float(raw["zmin_m"]),
                thickness_m=float(raw["thickness_m"]),
                material=str(raw["material"]),
                kind=raw["kind"],
                gds_layer=int(raw["gds_layer"]) if raw.get("gds_layer") is not None else None,
                gds_datatype=int(raw["gds_datatype"]) if raw.get("gds_datatype") is not None else None,
                mesh_hint_mm=float(raw["mesh_hint_mm"]) if raw.get("mesh_hint_mm") is not None else None,
            )
        )
    return RFStackup(name=str(name), layers=tuple(layers))


def load_stackup(yaml_path: str | Path) -> RFStackup:
    """从 YAML 读入叠层（safe_load；惰性导入与 em_solver_base 同惯例）。"""
    import yaml  # 惰性导入：仅叠层 IO 通道需要

    typed_path = Path(yaml_path)
    if not typed_path.exists():
        raise FileNotFoundError(f"叠层 YAML 不存在: {typed_path}")
    with typed_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data:
        raise ValueError(f"叠层 YAML 为空: {typed_path}")
    return stackup_from_dict(data)


def dump_stackup(stackup: RFStackup, yaml_path: str | Path) -> Path:
    """叠层 → YAML（safe_dump，sort_keys=False 保持字段书写序；UTF-8 显式）。"""
    import yaml  # 惰性导入

    typed_path = Path(yaml_path)
    typed_path.parent.mkdir(parents=True, exist_ok=True)
    with typed_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(stackup_to_dict(stackup), f, allow_unicode=True, sort_keys=False)
    return typed_path


# ---------------------------------------------------------------------------
# 斜段矩形化（阶梯化）
# ---------------------------------------------------------------------------


def _dedupe_ring(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """点列去连续重复点（与 B2 _dedupe_closed 同口径；不要求闭合）。"""
    out: list[tuple[float, float]] = []
    for pt in points:
        if not out or (pt[0], pt[1]) != (out[-1][0], out[-1][1]):
            out.append((pt[0], pt[1]))
    return out


def _rect_ring(xmin: float, ymin: float, xmax: float, ymax: float) -> list[tuple[float, float]]:
    """轴对齐矩形 → 4 角逆时针环（退化矩形零面积时由调用方过滤）。"""
    return [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]


def rectangularize_segment(
    points: Sequence[tuple[float, float]],
    width_m: float,
    max_step_m: float | None = None,
) -> list[list[tuple[float, float]]]:
    """带宽度折线 → 轴对齐矩形阶梯多边形序列（斜段的正交阶梯化）。

    算法（L 形步进扫掠）
    --------------------
    - 水平/垂直段：单矩形直通（精确，无阶梯）；
    - 斜段：沿段方向以步长 ``step``（缺省 = ``width/2``）取 n = ceil(L/step) 个
      采样点，每步发出一支水平矩形（沿 Δx，高度 width）+ 一支垂直矩形（沿
      Δy，宽度 width）的 L 形扫掠；段两端各补一个 width×width 方块，保证
      倾斜端面（轴对齐方块必含 45° 端面）被完整覆盖——RF 端口连通性依赖。

    精度-步数折衷
    -------------
    步长越小阶梯越贴真实斜带（角部偏差 O(step)），矩形数 ≈ 2·L/step 线性增长；
    缺省 width/2 是面积误差与图元数的经验折中（45° 实测联合面积偏差 ≤~10%，
    面积守恒容差 = step×width×段数，见测试）。步长过小会放大 P2 网格/渲染
    图元量，无下限守卫但有 >0 守卫。

    单位无关：``points`` 与 ``width_m``/``max_step_m`` 须同一长度单位（桥接层
    以米传入；B2 毫米调用方自行换算）。字段名 ``width_m`` 沿任务书命名。

    Raises
    ------
    ValueError
        去重后点数 <2、width 非正/非有限、max_step 非正/非有限。
    """
    if not isinstance(width_m, (int, float)) or isinstance(width_m, bool):
        raise ValueError(f"宽度必须为数值: {width_m!r}")
    if not math.isfinite(float(width_m)) or float(width_m) <= 0.0:
        raise ValueError(f"宽度必须为正有限值: {width_m!r}")
    if max_step_m is not None:
        if not isinstance(max_step_m, (int, float)) or isinstance(max_step_m, bool):
            raise ValueError(f"步长必须为数值或 None: {max_step_m!r}")
        if not math.isfinite(float(max_step_m)) or float(max_step_m) <= 0.0:
            raise ValueError(f"步长必须为正有限值: {max_step_m!r}")
    pts = _dedupe_ring([(float(p[0]), float(p[1])) for p in points])
    if len(pts) < 2:
        raise ValueError(f"折线去重后至少需要 2 个点: {len(pts)}")
    step = float(width_m) / 2.0 if max_step_m is None else float(max_step_m)
    half = float(width_m) / 2.0
    rects: list[list[tuple[float, float]]] = []

    for (x0, y0), (x1, y1) in pairwise(pts):
        dx, dy = x1 - x0, y1 - y0
        seg_len = math.hypot(dx, dy)
        if seg_len == 0.0:  # 防御：_dedupe_ring 后理论不可达
            continue
        if dx == 0.0 or dy == 0.0:
            # 轴对齐直通：单矩形精确承载（端面即垂直/水平切面，天然完整）
            rects.append(
                _rect_ring(min(x0, x1) - (half if dy else 0.0), min(y0, y1) - (half if dx else 0.0),
                           max(x0, x1) + (half if dy else 0.0), max(y0, y1) + (half if dx else 0.0))
            )
            continue
        # 斜段：L 形步进扫掠
        n = max(1, math.ceil(seg_len / step))
        for k in range(n):
            ax, ay = x0 + dx * k / n, y0 + dy * k / n
            bx, by = x0 + dx * (k + 1) / n, y0 + dy * (k + 1) / n
            if ax != bx:  # 水平支：沿 Δx、高 width，中心线在 y=ay
                rects.append(_rect_ring(min(ax, bx), ay - half, max(ax, bx), ay + half))
            if ay != by:  # 垂直支：沿 Δy、宽 width，中心线在 x=bx
                rects.append(_rect_ring(bx - half, min(ay, by), bx + half, max(ay, by)))
        # 端面方块：倾斜端面的轴对齐包络覆盖（RF 端口连通性）
        rects.append(_rect_ring(x0 - half, y0 - half, x0 + half, y0 + half))
        rects.append(_rect_ring(x1 - half, y1 - half, x1 + half, y1 + half))
    return [r for r in rects if (r[1][0] - r[0][0]) > 0.0 and (r[2][1] - r[1][1]) > 0.0]


# ---------------------------------------------------------------------------
# 多边形有效性守卫与渲染原语转换
# ---------------------------------------------------------------------------


def validate_polygon(ring: Sequence[tuple[float, float]]) -> Any:
    """环坐标 → 有效 shapely 多边形（make_valid + 去重守卫；判据⑤）。

    行为：
    - 去连续重复点与首尾闭合重复点；去重后 <3 点 → ValueError；
    - 已有效且面积为正 → 原样返回（Polygon）；
    - 自相交/退化：make_valid 修复；修复出多个面片 → 返回 MultiPolygon
      （docstring 如实声明，调用方 polygon_to_render_primitives 接受）；
    - make_valid 后仍无面积>0 的多边形部分（如全共线零面积环）→
      **显式 ValueError**（判据⑤负例：不静默放行渲染）。

    坐标环语义（shapely）：第一个环=外边界；带洞输入走
    shapely.Polygon(shell, holes) 构造后直接交本模块的消费者。
    """
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.geometry.base import BaseGeometry
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    pts = _dedupe_ring([(float(p[0]), float(p[1])) for p in ring])
    # 闭合重复点（末点==首点）去除
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        raise ValueError(f"多边形环去重后至少需要 3 个点: {len(pts)}")
    geom: BaseGeometry = Polygon(pts)
    if geom.is_valid and geom.area > 0.0:
        return geom
    repaired = make_valid(geom)
    parts = [g for g in _polygonal_parts(repaired) if g.area > 0.0]
    if not parts:
        raise ValueError(
            f"多边形环经 make_valid 后仍无有效面片（面积 0 或非面）：{len(pts)} 点，"
            "拒绝进入渲染（判据⑤负例）"
        )
    merged = unary_union(parts) if len(parts) > 1 else parts[0]
    if isinstance(merged, Polygon):
        return merged
    if isinstance(merged, MultiPolygon):
        return merged
    return MultiPolygon(parts)


def _polygonal_parts(geom: Any) -> list[Any]:
    """几何对象 → 多边形部件列表（Polygon/MultiPolygon/GeometryCollection）。"""
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.geometry.collection import GeometryCollection

    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    if isinstance(geom, GeometryCollection):
        out: list[Any] = []
        for g in geom.geoms:
            out.extend(_polygonal_parts(g))
        return out
    return []


def polygon_to_render_primitives(
    geom: Any,
    layer: RFRouteLayer,
) -> list[dict[str, Any]]:
    """有效多边形 → 渲染原语 dict 列表（P2 渲染器的输入契约）。

    形态契约（PRIMITIVE_SCHEMA_VERSION=1）::

        {"kind": "polygon",          # 原语类型（P2 翻译成 AddPolygon 字面量）
         "coords": [(x, y), ...],    # 外环，米，末点不重复首点
         "holes": [[(x, y), ...]],   # 内环列表（无洞为 []）
         "layer": <RFRouteLayer.name>,
         "layer_kind": "signal"|"ground"|"dielectric",
         "material": <str>,
         "zmin_m": <float>,          # 层底（P2 决定 elevation/拉伸）
         "thickness_m": <float>,     # 0=零厚片（openEMS AddPolygon 惯例）
         "mesh_hint_mm": <float|None>}

    不直接调 CSXCAD——执行面（elevation/priority/材料→介质映射）是 P2。
    geom 接受 shapely Polygon/MultiPolygon（或 GeometryCollection，取其面片），
    亦接受原始坐标环（内部先 validate_polygon）。坐标按**米**原样透传。
    """
    from shapely.geometry import MultiPolygon, Polygon

    if not isinstance(geom, (Polygon, MultiPolygon)):
        geom = validate_polygon(geom)
    parts = [geom] if isinstance(geom, Polygon) else list(geom.geoms)
    primitives: list[dict[str, Any]] = []
    for part in parts:
        exterior = [(float(x), float(y)) for x, y in part.exterior.coords[:-1]]
        holes = [
            [(float(x), float(y)) for x, y in interior.coords[:-1]] for interior in part.interiors
        ]
        primitives.append(
            {
                "kind": "polygon",
                "coords": exterior,
                "holes": holes,
                "layer": layer.name,
                "layer_kind": layer.kind,
                "material": layer.material,
                "zmin_m": float(layer.zmin_m),
                "thickness_m": float(layer.thickness_m),
                "mesh_hint_mm": layer.mesh_hint_mm,
            }
        )
    return primitives


# ---------------------------------------------------------------------------
# B2 Layout → RFStackup 渲染原语桥
# ---------------------------------------------------------------------------


def bridge_layout_to_stackup(layout_obj: Layout, stackup: RFStackup) -> dict[str, Any]:
    """B2 版图（毫米）→ 叠层映射 → 渲染原语（米）+ 如实跳过统计。

    映射口径（不猜）：
    - 版图层（layout_interchange.LayoutLayer）逐层经 ``RFRouteLayer.matches``
      找叠层选择器匹配；命不中的层：其全部几何项跳过，层名进
      ``unmatched_layers``、项数进 ``stats["skipped_unmatched_items"]``；
    - 未注册层表但被几何项引用的层名同样按 unmatched 处理（B2 导出侧会
      KeyError，桥接侧宽松计数以支撑部分导入）；
    - via 的钻孔/柱体渲染属 P2/P3 z 维语义，v1 显式跳过并计数
      ``stats["skipped_vias"]``；
    - 叠层中从未被任何版图层命中的层：进 ``stats["stackup_layers_unused"]``
      （双层核对：叠层写错层号也能被看见）。

    几何分发：Path→rectangularize_segment（斜段阶梯化；毫米→米）；
    Polygon→validate_polygon→primitives（带洞保留）；Circle→确定性内接
    多边形（B2 circle_to_polygon 同源口径）；Via→跳过计数。

    Returns
    -------
    dict
        ``{"primitives": [...], "unmatched_layers": [层名...],
        "stats": {...}}``；stats 含 n_items/n_primitives/skipped_vias/
        skipped_unmatched_items/matched_layers/stackup_layers_unused。
    """
    layout_layers: dict[str, LayoutLayer] = {lay.name: lay for lay in layout_obj.layers}
    matched: dict[str, RFRouteLayer] = {}
    unmatched_layers: set[str] = set()
    matched_names: dict[str, str] = {}
    stats: dict[str, Any] = {
        "n_items": 0,
        "n_primitives": 0,
        "skipped_vias": 0,
        "skipped_unmatched_items": 0,
        "matched_layers": {},
        "stackup_layers_unused": [],
    }
    primitives: list[dict[str, Any]] = []

    def resolve(item: LayoutItem) -> RFRouteLayer | None:
        layer_name = item.pad_layer if isinstance(item, LayoutVia) else item.layer
        if layer_name in matched:
            return matched[layer_name]
        lay = layout_layers.get(layer_name)
        hit: RFRouteLayer | None = None
        if lay is not None:
            hit = stackup.find_layer(lay.gds_layer, lay.gds_datatype, lay.name)
        else:
            # 未注册层表：无 gds 层号可用，仅按层名选择器匹配（不猜层号）
            for cand in stackup.layers:
                if cand.gds_layer is None and cand.name == layer_name:
                    hit = cand
                    break
        if hit is None:
            unmatched_layers.add(layer_name)
            return None
        matched[layer_name] = hit
        matched_names[layer_name] = hit.name
        return hit

    for item in layout_obj.items:
        stats["n_items"] += 1
        layer = resolve(item)
        if layer is None:
            stats["skipped_unmatched_items"] += 1
            continue
        if isinstance(item, LayoutVia):
            stats["skipped_vias"] += 1
            continue
        if isinstance(item, LayoutPath):
            pts_m = [(x * _MM_TO_M, y * _MM_TO_M) for x, y in item.points]
            for rect in rectangularize_segment(pts_m, item.width_mm * _MM_TO_M):
                primitives.extend(polygon_to_render_primitives(rect, layer))
        elif isinstance(item, LayoutPolygon):
            ring_m = [(x * _MM_TO_M, y * _MM_TO_M) for x, y in item.points]
            primitives.extend(polygon_to_render_primitives(ring_m, layer))
        elif isinstance(item, LayoutCircle):
            ring_m = [
                (x * _MM_TO_M, y * _MM_TO_M)
                for x, y in circle_to_polygon(item.center, item.radius_mm)
            ]
            primitives.extend(polygon_to_render_primitives(ring_m, layer))
        else:  # 防御：未知项类型如实计数，不静默
            stats["skipped_unmatched_items"] += 1
            continue
    stats["n_primitives"] = len(primitives)
    stats["matched_layers"] = dict(sorted(matched_names.items()))
    used_stackup = set(matched_names.values())
    stats["stackup_layers_unused"] = [lay.name for lay in stackup.layers if lay.name not in used_stackup]
    return {
        "primitives": primitives,
        "unmatched_layers": sorted(unmatched_layers),
        "stats": stats,
    }
