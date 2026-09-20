"""B2 版图互操作内核：GDSII / DXF / IPC-2581 / ODB++ 读写 + 往返无损裁判。

方案依据： B2「GDSII/DXF 导入导出 + IPC-2581/ODB++ 互操作（KiCad 8+ 原生
导出 IPC-2581）」，验收列「往返无损」；B5「参数化版图输出」与 B2 合并验收
（生成器见 adapters/layout_generator.py，本模块提供其统一出口）。

坐标与单位约定
--------------
内部表示一律毫米（float）。GDSII 以 unit=1mm / precision=1nm 写出（KiCad nm
整数格点同源）。各格式的"无损"口径（round_trip_delta 按格式自动采用）：

- ``gdsii``：**nm 数据库格点无损**——坐标/线宽按 ``round(x*1e6)`` 量子化后
 逐点相等（gdstk 以 nm 整数存坐标，12.345 读回 12.344999999999999 属 1-ulp
 舍入，格点差=0）。层归属按 GDS 层号比较（读回层名为层号的字符串形式）。
 圆以固定段数内接正多边形确定性承载（circle_to_polygon）；via 钻孔在 GDSII
 无原生载体，按其焊盘圆承载（声明丢失，见 FORMAT_ROUNDTRIP_CAPABILITIES）。
- ``dxf``：DXF R12 子集（LAYER 表 + POLYLINE/CIRCLE），``.17g`` 文本位精确；
 圆 CIRCLE 原生承载；多边形=闭合 POLYLINE；路径=带全局宽度的开放 POLYLINE；
 钻孔不可承载（声明丢失）。外部任意 DXF 只承诺本子集可读，未知实体跳过并计数。
- ``ipc2581``：IPC-2581 rev C **子集骨架** XML（Content/Layer/StepData/Step/
 FeatureLayer 命名照 IPC-2581 惯例），``.17g`` 位精确；圆与 via 钻孔全承载。
 读取同时兼容 KiCad 8+/10 原生导出的 rev C 全 schema（带命名空间
 ``http://webstds.ipc.org/2581``，几何在 Step/LayerFeature/Set，走线为
 DictionaryUser 多边形轮廓，焊盘经 DictionaryStandard 图元字典）——见
 import_ipc2581。
- ``odbpp``：ODB++ 风格**子集目录**（matrix/matrix + steps/*/layers/*，UNITS=MM，
 L/OB/L/OC/P 记录），``.17g`` 位精确；圆与钻孔全承载。读取同时兼容 KiCad 10
 原生导出的真实 ODB++ 目录（块式 matrix `LAYER {...}`、层 features 文件
 `$<idx>` 符号表、S/OB/OS/OE/SE 表面记录）——见 import_odbpp。

自包含（无 ezdxf/klayout 依赖）；GDSII 走 venv 已装的 gdstk（惰性导入）。
"""

from __future__ import annotations

import logging
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from rfauto.adapters.kicad_pcell import PCBDesign

logger = logging.getLogger(__name__)

#: B2 互操作格式全集（export_layout/import_layout 的 fmt 取值）。
LAYOUT_INTERCHANGE_FORMATS = ("gdsii", "dxf", "ipc2581", "odbpp")

#: 各格式的往返承载能力（round_trip_delta 的裁判口径由此驱动）。
#: grid_nm：坐标比较格点（0=双精度位精确）；circle_as_polygon：圆读回变多边形；
#: drill_carried：via 钻孔可承载；annotations_carried：注记可承载（几何裁判之外
#: 的承载项，单独用例钉住）。
FORMAT_ROUNDTRIP_CAPABILITIES: dict[str, dict[str, Any]] = {
  "gdsii": {
    "grid_nm": 1.0,
    "circle_as_polygon": True,
    "drill_carried": False,
    "annotations_carried": False,
  },
  "dxf": {
    "grid_nm": 0.0,
    "circle_as_polygon": False,
    "drill_carried": False,
    "annotations_carried": False,
  },
  "ipc2581": {
    "grid_nm": 0.0,
    "circle_as_polygon": False,
    "drill_carried": True,
    "annotations_carried": True,
  },
  "odbpp": {
    "grid_nm": 0.0,
    "circle_as_polygon": False,
    "drill_carried": True,
    "annotations_carried": True,
  },
}

#: GDSII 单位口径：unit=1mm、precision=1nm（KiCad nm 整数格点同源）。
GDS_UNIT_M = 1e-3
GDS_PRECISION_M = 1e-9

#: 圆→多边形确定性内接段数（整 2π），GDSII 承载圆的唯一口径。
CIRCLE_POLYGON_SEGMENTS = 64

#: 浮点位精确文本口径（IEEE-754 double 往返）。
_FMT = ".17g"


def _fmt(value: float) -> str:
  return format(float(value), _FMT)


def _parse_float(token: str) -> float:
  return float(token)


def _q(value: float, grid_nm: float) -> float:
  """按格点量子化：grid_nm>0 时取 nm 格点（round(x*1e6)），否则原值位精确。"""
  if grid_nm <= 0.0:
    return value
  return round(value * 1e6) / 1e6


def _safe_name(name: str) -> str:
  cleaned = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
  return cleaned or "layout"


def _ns_local(node: ET.Element) -> str:
  """去 XML 命名空间：``{uri}local`` → ``local``（KiCad 原生导出带命名空间）。"""
  return node.tag.rsplit("}", 1)[-1]


def _dedupe_closed(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
  """闭合轮廓点去重：去连续重复点与首尾闭合重复点（末点==首点）。"""
  out: list[tuple[float, float]] = []
  for pt in pts:
    if not out or pt != out[-1]:
      out.append(pt)
  if len(out) >= 2 and out[0] == out[-1]:
    out.pop()
  return out


# ---------------------------------------------------------------------------
# 版图数据模型（内部 mm）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayoutLayer:
  """版图层：name 为任意字符串键；gds_layer/gds_datatype 为 GDSII 层号。"""

  name: str
  gds_layer: int
  gds_datatype: int = 0


@dataclass(frozen=True)
class LayoutPath:
  """描边路径：中心线折线 + 恒定线宽。"""

  points: tuple[tuple[float, float], ...]
  width_mm: float
  layer: str


@dataclass(frozen=True)
class LayoutPolygon:
  """填充多边形（闭合边界，末点不重复首点）。"""

  points: tuple[tuple[float, float], ...]
  layer: str


@dataclass(frozen=True)
class LayoutCircle:
  """实心圆（焊盘/过孔盘）。"""

  center: tuple[float, float]
  radius_mm: float
  layer: str


@dataclass(frozen=True)
class LayoutVia:
  """过孔：焊盘圆 + 钻孔（钻孔仅 IPC-2581/ODB++ 可承载）。"""

  position: tuple[float, float]
  pad_diameter_mm: float
  drill_diameter_mm: float
  pad_layer: str


LayoutItem = LayoutPath | LayoutPolygon | LayoutCircle | LayoutVia


@dataclass
class Layout:
  """版图：层表 + 几何项 + 注记。B5 生成器与 B2 互操作的统一交换单元。"""

  name: str = "layout"
  layers: tuple[LayoutLayer, ...] = ()
  items: tuple[LayoutItem, ...] = ()
  annotations: dict[str, str] = field(default_factory=dict)

  def layer_names(self) -> list[str]:
    return [layer.name for layer in self.layers]

  def require_layer(self, name: str) -> LayoutLayer:
    for layer in self.layers:
      if layer.name == name:
        return layer
    raise KeyError(f"版图 {self.name!r} 不含层 {name!r}；现有层: {self.layer_names()}")


def assign_gds_layers(names) -> tuple[LayoutLayer, ...]:
  """为层名确定性分配 GDS 层号：F.Cu=1、B.Cu=2、Edge.Cuts=20，其余按名排序自 100 起。"""
  preferred = {"F.Cu": 1, "B.Cu": 2, "Edge.Cuts": 20}
  layers: list[LayoutLayer] = []
  next_id = 100
  for name in sorted(dict.fromkeys(names)):
    if name in preferred:
      layers.append(LayoutLayer(name=name, gds_layer=preferred[name]))
    else:
      layers.append(LayoutLayer(name=name, gds_layer=next_id))
      next_id += 1
  return tuple(layers)


def circle_to_polygon(
  center: tuple[float, float],
  radius_mm: float,
  segments: int = CIRCLE_POLYGON_SEGMENTS,
) -> tuple[tuple[float, float], ...]:
  """圆的确定性内接正多边形（GDSII 承载圆的唯一口径，export/import 两侧同源）。"""
  if segments < 3:
    raise ValueError(f"多边形段数必须 ≥3: {segments}")
  if radius_mm <= 0.0:
    raise ValueError(f"圆半径必须为正: {radius_mm}")
  cx, cy = center
  return tuple(
    (
      cx + radius_mm * math.cos(2.0 * math.pi * k / segments),
      cy + radius_mm * math.sin(2.0 * math.pi * k / segments),
    )
    for k in range(segments)
  )


def _item_layer(item: LayoutItem) -> str:
  return item.pad_layer if isinstance(item, LayoutVia) else item.layer


# ---------------------------------------------------------------------------
# 通用调度出口/入口
# ---------------------------------------------------------------------------


def export_layout(layout: Layout, path: str | Path, fmt: str) -> Path:
  """按格式标识导出版图（B2/B5 统一出口）。

  Raises
  ------
  ValueError
    fmt 不在 LAYOUT_INTERCHANGE_FORMATS 内。
  """
  fmt_key = fmt.lower()
  exporters: dict[str, Callable[[Layout, Path], Path]] = {
    "gdsii": export_gdsii,
    "dxf": export_dxf,
    "ipc2581": export_ipc2581,
    "odbpp": export_odbpp,
  }
  if fmt_key not in exporters:
    raise ValueError(f"不支持的版图互操作格式: {fmt!r}；支持 {LAYOUT_INTERCHANGE_FORMATS}")
  return exporters[fmt_key](layout, Path(path))


def import_layout(path: str | Path, fmt: str, laymap: Mapping[str, str] | None = None) -> Layout:
  """按格式标识读入版图（B2 统一入口）。

  ``laymap``（P2⑳ 可选）：{GDS 层号串: 模板层名} 外部层名映射，语义仅 gdsii；
  fmt 非 gdsii 时给出 laymap 显式 ValueError（静默忽略不可取）。

  Raises
  ------
  ValueError
    fmt 不在 LAYOUT_INTERCHANGE_FORMATS 内；或 laymap 给出而 fmt 非 gdsii。
  FileNotFoundError
    路径不存在。
  """
  fmt_key = fmt.lower()
  if fmt_key not in LAYOUT_INTERCHANGE_FORMATS:
    raise ValueError(f"不支持的版图互操作格式: {fmt!r}；支持 {LAYOUT_INTERCHANGE_FORMATS}")
  if laymap is not None and fmt_key != "gdsii":
    raise ValueError(f"laymap 语义仅适用于 gdsii（GDS 层号→层名映射），fmt={fmt!r} 不支持")
  typed_path = Path(path)
  if not typed_path.exists():
    raise FileNotFoundError(f"版图文件不存在: {typed_path}")
  readers: dict[str, Callable[[Path], Layout]] = {
    "gdsii": lambda typed: import_gdsii(typed, laymap=laymap),
    "dxf": import_dxf,
    "ipc2581": import_ipc2581,
    "odbpp": import_odbpp,
  }
  return readers[fmt_key](typed_path)


# ---------------------------------------------------------------------------
# 往返无损裁判
# ---------------------------------------------------------------------------


def _canonical_point(pt: tuple[float, float], grid_nm: float) -> tuple[float, float]:
  return (_q(pt[0], grid_nm), _q(pt[1], grid_nm))


def _layer_key_fn(layout: Layout, fmt: str) -> Callable[[str], Any]:
  """层归属键：gdsii 用 GDS 层号比较（读回层名为层号串）；其余格式用层名。"""
  if fmt.lower() == "gdsii":
    mapping = {layer.name: layer.gds_layer for layer in layout.layers}

    def key(name: str) -> Any:
      gds_id = mapping.get(name)
      return gds_id if gds_id is not None else f"?{name}"

    return key
  return lambda name: name


def _canonical_items(
  layout: Layout, caps: dict[str, Any], layer_key: Callable[[str], Any]
) -> tuple[tuple[Any, ...], ...]:
  """版图项规范成可比元组集合（排序后逐项比较；格点/圆多边形化按格式能力）。"""
  grid_nm = caps["grid_nm"]
  circle_as_polygon = caps["circle_as_polygon"]
  drill_carried = caps["drill_carried"]
  rows: list[tuple[Any, ...]] = []
  for item in layout.items:
    if isinstance(item, LayoutPath):
      rows.append(
        (
          "path",
          layer_key(item.layer),
          _q(item.width_mm, grid_nm),
          tuple(_canonical_point(pt, grid_nm) for pt in item.points),
        )
      )
    elif isinstance(item, LayoutPolygon):
      rows.append(
        ("poly", layer_key(item.layer), tuple(_canonical_point(pt, grid_nm) for pt in item.points))
      )
    elif isinstance(item, LayoutCircle):
      if circle_as_polygon:
        rows.append(
          (
            "poly",
            layer_key(item.layer),
            tuple(
              _canonical_point(pt, grid_nm)
              for pt in circle_to_polygon(item.center, item.radius_mm)
            ),
          )
        )
      else:
        rows.append(
          (
            "circle",
            layer_key(item.layer),
            _canonical_point(item.center, grid_nm),
            _q(item.radius_mm, grid_nm),
          )
        )
    elif isinstance(item, LayoutVia):
      pad_radius = item.pad_diameter_mm / 2.0
      if circle_as_polygon:
        rows.append(
          (
            "poly",
            layer_key(item.pad_layer),
            tuple(
              _canonical_point(pt, grid_nm)
              for pt in circle_to_polygon(item.position, pad_radius)
            ),
          )
        )
      elif drill_carried:
        rows.append(
          (
            "via",
            layer_key(item.pad_layer),
            _canonical_point(item.position, grid_nm),
            _q(item.pad_diameter_mm, grid_nm),
            _q(item.drill_diameter_mm, grid_nm),
          )
        )
      else:
        rows.append(
          (
            "circle",
            layer_key(item.pad_layer),
            _canonical_point(item.position, grid_nm),
            _q(pad_radius, grid_nm),
          )
        )
    else: # pragma: no cover - 防御分支
      raise TypeError(f"未知版图项类型: {type(item).__name__}")
  return tuple(sorted(rows, key=repr))


def round_trip_delta(origin: Layout, roundtripped: Layout, fmt: str) -> float:
  """往返无损裁判：两版图在 ``fmt`` 承载能力口径下的最大几何差（mm）。

  无损 ⇔ 返回 0.0。结构不一致（项数/类型/层归属不同）返回 ``math.inf``。
  gdsii 按 nm 格点比较（GDSII 数据库格点无损口径）；其余格式位精确。
  注记（annotations）不进几何裁判，承载性单独按 FORMAT_ROUNDTRIP_CAPABILITIES
  的 annotations_carried 用例钉住。
  """
  fmt_key = fmt.lower()
  caps = FORMAT_ROUNDTRIP_CAPABILITIES[fmt_key]
  left = _canonical_items(origin, caps, _layer_key_fn(origin, fmt_key))
  right = _canonical_items(roundtripped, caps, _layer_key_fn(roundtripped, fmt_key))
  if len(left) != len(right):
    return math.inf
  max_delta = 0.0
  for a, b in zip(left, right, strict=True):
    if a[0] != b[0] or a[1] != b[1]:
      return math.inf
    max_delta = max(max_delta, _row_delta(a, b))
  return max_delta


def _row_delta(a: tuple[Any, ...], b: tuple[Any, ...]) -> float:
  """单个规范项内的数值差上界（逐坐标/宽度/半径）。"""
  if len(a) != len(b):
    return math.inf
  delta = 0.0
  for va, vb in zip(a[2:], b[2:], strict=True):
    if isinstance(va, tuple):
      if not va:
        continue
      if isinstance(va[0], (int, float)): # 单点 (x, y)
        delta = max(delta, abs(float(va[0]) - float(vb[0])), abs(float(va[1]) - float(vb[1])))
      else: # 点序列（长度不同按结构不一致处理）
        if len(va) != len(vb):
          return math.inf
        for (xa, ya), (xb, yb) in zip(va, vb, strict=True):
          delta = max(delta, abs(xa - xb), abs(ya - yb))
    elif isinstance(va, (int, float)):
      delta = max(delta, abs(float(va) - float(vb)))
  return delta


def verify_round_trip(layout: Layout, fmt: str, workdir: str | Path) -> dict[str, Any]:
  """导出→读回→裁判，返回 {"delta": float, "path": str, "lossless": bool}。"""
  workdir = Path(workdir)
  workdir.mkdir(parents=True, exist_ok=True)
  suffix = {"gdsii": "gds", "dxf": "dxf", "ipc2581": "xml"}.get(fmt.lower())
  path = (
    workdir / _safe_name(layout.name)
    if suffix is None # odbpp：目录
    else workdir / f"{_safe_name(layout.name)}.{suffix}"
  )
  export_layout(layout, path, fmt)
  roundtripped = import_layout(path, fmt)
  delta = round_trip_delta(layout, roundtripped, fmt)
  return {"delta": delta, "path": str(path), "lossless": delta == 0.0}


# ---------------------------------------------------------------------------
# GDSII（gdstk）
# ---------------------------------------------------------------------------


def export_gdsii(layout: Layout, path: str | Path) -> Path:
  """导出 GDSII（unit=1mm / precision=1nm；路径为 GDS PATH 记录，圆为内接多边形）。"""
  import gdstk  # 惰性导入：仅 GDSII 通道需要

  path = Path(path)
  path.parent.mkdir(parents=True, exist_ok=True)
  lib = gdstk.Library(name=_safe_name(layout.name), unit=GDS_UNIT_M, precision=GDS_PRECISION_M)
  cell = gdstk.Cell(_safe_name(layout.name))
  layer_ids = {layer.name: (layer.gds_layer, layer.gds_datatype) for layer in layout.layers}
  for item in layout.items:
    layer_id = layer_ids.get(_item_layer(item))
    if layer_id is None:
      raise KeyError(f"项引用了未注册层 {_item_layer(item)!r}；层表: {list(layer_ids)}")
    if isinstance(item, LayoutPath):
      cell.add(
        gdstk.FlexPath(
          [tuple(pt) for pt in item.points],
          item.width_mm,
          layer=layer_id[0],
          datatype=layer_id[1],
          simple_path=True,
        )
      )
    else:
      if isinstance(item, LayoutPolygon):
        pts: tuple[tuple[float, float], ...] = item.points
      elif isinstance(item, LayoutCircle):
        pts = circle_to_polygon(item.center, item.radius_mm)
      else: # LayoutVia：钻孔不可承载，按焊盘圆承载
        pts = circle_to_polygon(item.position, item.pad_diameter_mm / 2.0)
      cell.add(
        gdstk.Polygon([tuple(pt) for pt in pts], layer=layer_id[0], datatype=layer_id[1])
      )
  lib.add(cell)
  lib.write_gds(str(path))
  logger.info("导出 GDSII: %s（%d 项，%d 层）", path, len(layout.items), len(layout.layers))
  return path


def _apply_laymap(layout: Layout, laymap: Mapping[str, str] | None) -> Layout:
  """外部 laymap（P2⑳）：{GDS 层号串: 模板层名} 应用到版图——纯改名，零几何改动。

  命中层号者重命名层表项与项层（Via 走 pad_layer），未命中层号保持层号串名
  （真实 GDS 文件层多，宽松不炸）。键按 ``str(int(key))`` 归一（容忍 JSON/YAML
  整型键与补零写法）。gds_layer/gds_datatype 与几何不动，故 round_trip_delta
  对 gdsii 仍按 _layer_key_fn 各侧自身 name→层号表解析比较——改名对裁判中性。
  laymap 为 None/空映射时原样返回（默认行为与无映射完全一致）。
  """
  if not laymap:
    return layout
  rename = {str(int(key)): str(value) for key, value in laymap.items()}
  layers = tuple(
    replace(lay, name=rename[lay.name]) if lay.name in rename else lay
    for lay in layout.layers
  )
  items = tuple(
    replace(item, pad_layer=rename.get(item.pad_layer, item.pad_layer))
    if isinstance(item, LayoutVia)
    else replace(item, layer=rename.get(item.layer, item.layer))
    for item in layout.items
  )
  return Layout(name=layout.name, layers=layers, items=items, annotations=layout.annotations)


def import_gdsii(path: str | Path, laymap: Mapping[str, str] | None = None) -> Layout:
  """读入 GDSII（gdstk）；路径/多边形逐项还原，圆以多边形形式返回（承载口径）。

  读回层名为 GDS 层号的字符串形式（GDSII 不携带层名）；round_trip_delta 对
  gdsii 按层号比较归属。可选 ``laymap``（P2⑳）：{GDS 层号串: 模板层名} 外部
  层名映射（文件读取走服务层 load_laymap），命中层号者改名、未命中保持层号
  串名；laymap=None（默认）行为与无映射完全一致。
  """
  import gdstk  # 惰性导入

  typed_path = Path(path)
  if not typed_path.exists():
    raise FileNotFoundError(f"GDSII 文件不存在: {typed_path}")
  lib = gdstk.read_gds(str(typed_path))
  top_cells = lib.top_level()
  if not top_cells:
    raise ValueError(f"GDSII 无顶层单元: {typed_path}")
  cell = top_cells[0]
  layer_tbl: dict[tuple[int, int], LayoutLayer] = {}
  items: list[LayoutItem] = []

  def remember(gds_layer: int, gds_datatype: int) -> None:
    layer_tbl.setdefault(
      (gds_layer, gds_datatype),
      LayoutLayer(name=str(gds_layer), gds_layer=gds_layer, gds_datatype=gds_datatype),
    )

  for pp in cell.paths:
    gds_layer, gds_datatype = int(pp.layers[0]), int(pp.datatypes[0])
    widths = pp.widths()
    width = float(max(row[0] for row in widths)) if len(widths) else 0.0
    points = tuple((float(x), float(y)) for x, y in pp.path_spines()[0])
    items.append(LayoutPath(points=points, width_mm=width, layer=str(gds_layer)))
    remember(gds_layer, gds_datatype)
  for poly in cell.polygons:
    gds_layer, gds_datatype = int(poly.layer), int(poly.datatype)
    points = tuple((float(x), float(y)) for x, y in poly.points)
    items.append(LayoutPolygon(points=points, layer=str(gds_layer)))
    remember(gds_layer, gds_datatype)
  return _apply_laymap(
    Layout(name=cell.name, layers=tuple(layer_tbl.values()), items=tuple(items)), laymap
  )


# ---------------------------------------------------------------------------
# DXF R12 子集
# ---------------------------------------------------------------------------


def export_dxf(layout: Layout, path: str | Path) -> Path:
  """导出 DXF R12 子集：LAYER 表 + POLYLINE（路径带全局宽度/多边形闭合）+ CIRCLE。"""
  path = Path(path)
  path.parent.mkdir(parents=True, exist_ok=True)
  lines: list[str] = ["999", "rfauto B2 layout export (DXF R12 subset)"]
  lines += ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "0", "ENDSEC"]
  lines += ["0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", str(len(layout.layers))]
  for layer in layout.layers:
    lines += ["0", "LAYER", "2", layer.name, "70", "0", "62", "7", "6", "CONTINUOUS"]
  lines += ["0", "ENDTAB", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]

  def emit_polyline(layer_name: str, pts, width_mm: float, closed: bool) -> None:
    lines.extend(
      [
        "0", "POLYLINE",
        "8", layer_name,
        "66", "1",
        "70", "1" if closed else "0",
        "40", _fmt(width_mm),
        "41", _fmt(width_mm),
      ]
    )
    for x, y in pts:
      lines.extend(["0", "VERTEX", "8", layer_name, "10", _fmt(x), "20", _fmt(y)])
    lines.extend(["0", "SEQEND"])

  def emit_circle(layer_name: str, cx: float, cy: float, radius: float) -> None:
    lines.extend(
      ["0", "CIRCLE", "8", layer_name, "10", _fmt(cx), "20", _fmt(cy), "40", _fmt(radius)]
    )

  for item in layout.items:
    if isinstance(item, LayoutPath):
      emit_polyline(item.layer, item.points, item.width_mm, closed=False)
    elif isinstance(item, LayoutPolygon):
      emit_polyline(item.layer, item.points, 0.0, closed=True)
    elif isinstance(item, LayoutCircle):
      emit_circle(item.layer, item.center[0], item.center[1], item.radius_mm)
    elif isinstance(item, LayoutVia):
      # 钻孔在 DXF 无原生载体：按焊盘圆承载（声明丢失）。
      emit_circle(item.pad_layer, item.position[0], item.position[1], item.pad_diameter_mm / 2.0)
  lines += ["0", "ENDSEC", "0", "EOF"]
  path.write_text("\n".join(lines) + "\n", encoding="ascii")
  logger.info("导出 DXF: %s（%d 项）", path, len(layout.items))
  return path


def import_dxf(path: str | Path) -> Layout:
  """读入 DXF R12 子集；未知实体跳过计数（数量进 annotations，best-effort）。

  跳过计数只统计 ENTITIES 节内的未知实体；层表按几何引用重建（无几何的
  图层不保留）。
  """
  typed_path = Path(path)
  if not typed_path.exists():
    raise FileNotFoundError(f"DXF 文件不存在: {typed_path}")
  tokens = _read_dxf_tokens(typed_path)
  items: list[LayoutItem] = []
  skipped = 0
  in_entities = False
  pending_section = False
  idx = 0
  n = len(tokens)
  while idx < n - 1:
    code, value = tokens[idx]
    if code != "0":
      if pending_section and code == "2":
        in_entities = value.upper() == "ENTITIES"
        pending_section = False
      idx += 1
      continue
    record = value.upper()
    if record == "SECTION":
      pending_section = True
      idx += 1
      continue
    if record == "ENDSEC":
      in_entities = False
      pending_section = False
      idx += 1
      continue
    if not in_entities or record not in ("POLYLINE", "CIRCLE"):
      if in_entities:
        skipped += 1
      idx += 1
      continue
    body: list[tuple[str, str]] = []
    idx += 1
    while idx < n - 1 and tokens[idx][0] != "0":
      body.append(tokens[idx])
      idx += 1
    if record == "CIRCLE":
      parsed = _parse_dxf_circle(body)
      if parsed is None:
        skipped += 1
      else:
        items.append(parsed)
    else:
      parsed = _parse_dxf_polyline(body, tokens, idx)
      if parsed is None:
        skipped += 1
      else:
        item, idx = parsed
        items.append(item)
  layer_names = sorted({_item_layer(item) for item in items})
  layout = Layout(name=typed_path.stem, layers=assign_gds_layers(layer_names), items=tuple(items))
  if skipped:
    layout.annotations["dxf_skipped_entities"] = str(skipped)
  return layout


def _read_dxf_tokens(path: Path) -> list[tuple[str, str]]:
  """DXF 组码/值成对读取（UTF-8 兜底解码，剥离行尾空白）。"""
  tokens: list[tuple[str, str]] = []
  with path.open("r", encoding="utf-8-sig", errors="replace") as fid:
    while True:
      code_line = fid.readline()
      if not code_line:
        break
      value_line = fid.readline()
      if not value_line:
        raise ValueError(f"DXF 组码无配对值行（文件截断）: {path}")
      tokens.append((code_line.strip(), value_line.strip()))
  return tokens


def _dxf_body_get(body: list[tuple[str, str]], code: str, default: str | None = None) -> str | None:
  for c, v in body:
    if c == code:
      return v
  return default


def _parse_dxf_polyline(
  body: list[tuple[str, str]], tokens: list[tuple[str, str]], start_idx: int
) -> tuple[LayoutPath | LayoutPolygon, int] | None:
  """解析 POLYLINE：body 为 POLYLINE 头组码，顶点跟随其后直到 SEQEND。

  返回 (item, 下一索引)；无顶点返回 None。
  """
  closed = (_dxf_body_get(body, "70", "0") or "0").strip() == "1"
  width = _parse_float(_dxf_body_get(body, "40", "0") or "0")
  layer = _dxf_body_get(body, "8", "0") or "0"
  pts: list[tuple[float, float]] = []
  idx = start_idx
  n = len(tokens)
  while idx < n - 1:
    code, value = tokens[idx]
    if code == "0" and value.upper() == "VERTEX":
      vertex_body: list[tuple[str, str]] = []
      idx += 1
      while idx < n - 1 and tokens[idx][0] != "0":
        vertex_body.append(tokens[idx])
        idx += 1
      x = _dxf_body_get(vertex_body, "10")
      y = _dxf_body_get(vertex_body, "20")
      if x is None or y is None:
        return None
      pts.append((_parse_float(x), _parse_float(y)))
      continue
    if code == "0" and value.upper() == "SEQEND":
      idx += 1
      while idx < n - 1 and tokens[idx][0] != "0": # SEQEND 残余组码
        idx += 1
      break
    idx += 1
  if not pts:
    return None
  if closed:
    return LayoutPolygon(points=tuple(pts), layer=layer), idx
  return LayoutPath(points=tuple(pts), width_mm=width, layer=layer), idx


def _parse_dxf_circle(body: list[tuple[str, str]]) -> LayoutCircle | None:
  cx = _dxf_body_get(body, "10")
  cy = _dxf_body_get(body, "20")
  radius = _dxf_body_get(body, "40")
  layer = _dxf_body_get(body, "8", "0") or "0"
  if cx is None or cy is None or radius is None:
    return None
  return LayoutCircle(
    center=(_parse_float(cx), _parse_float(cy)), radius_mm=_parse_float(radius), layer=layer
  )


# ---------------------------------------------------------------------------
# IPC-2581 子集骨架
# ---------------------------------------------------------------------------

_IPC2581_ROOT = "IPC-2581"


def export_ipc2581(layout: Layout, path: str | Path) -> Path:
  """导出 IPC-2581 rev C 子集骨架 XML（读取契约=import_ipc2581）。"""
  path = Path(path)
  path.parent.mkdir(parents=True, exist_ok=True)
  root = ET.Element(_IPC2581_ROOT, {"revision": "C"})
  content = ET.SubElement(root, "Content")
  ET.SubElement(content, "EcadName").text = layout.name
  for layer in layout.layers:
    ET.SubElement(
      content,
      "Layer",
      {
        "name": layer.name,
        "gdsLayer": str(layer.gds_layer),
        "gdsDatatype": str(layer.gds_datatype),
      },
    )
  if layout.annotations:
    ann_root = ET.SubElement(content, "Annotations")
    for key, value in sorted(layout.annotations.items()):
      ET.SubElement(ann_root, "Annotation", {"name": key}).text = value
  step_data = ET.SubElement(content, "StepData")
  step = ET.SubElement(step_data, "Step", {"name": _safe_name(layout.name)})
  by_layer: dict[str, list[LayoutItem]] = {}
  for item in layout.items:
    by_layer.setdefault(_item_layer(item), []).append(item)
  for layer_name, layer_items in by_layer.items():
    feature_layer = ET.SubElement(step, "FeatureLayer", {"name": layer_name})
    for item in layer_items:
      if isinstance(item, LayoutPath):
        node = ET.SubElement(feature_layer, "PathFeature", {"width": _fmt(item.width_mm)})
        for x, y in item.points:
          ET.SubElement(node, "Point", {"x": _fmt(x), "y": _fmt(y)})
      elif isinstance(item, LayoutPolygon):
        node = ET.SubElement(feature_layer, "PolygonFeature")
        for x, y in item.points:
          ET.SubElement(node, "Point", {"x": _fmt(x), "y": _fmt(y)})
      elif isinstance(item, LayoutCircle):
        ET.SubElement(
          feature_layer,
          "CircleFeature",
          {
            "cx": _fmt(item.center[0]),
            "cy": _fmt(item.center[1]),
            "r": _fmt(item.radius_mm),
          },
        )
      elif isinstance(item, LayoutVia):
        ET.SubElement(
          feature_layer,
          "ViaFeature",
          {
            "padDiameter": _fmt(item.pad_diameter_mm),
            "drillDiameter": _fmt(item.drill_diameter_mm),
            "cx": _fmt(item.position[0]),
            "cy": _fmt(item.position[1]),
          },
        )
  ET.indent(root, space=" ")
  ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)
  logger.info("导出 IPC-2581: %s（%d 项）", path, len(layout.items))
  return path


def import_ipc2581(path: str | Path) -> Layout:
  """读入 IPC-2581 XML，自动识别两种形态：

  - **子集骨架**（与 export_ipc2581 互为逆操作）：Content/Layer +
   StepData/Step/FeatureLayer/{Path|Polygon|Circle|Via}Feature。
  - **KiCad 8+/10 原生 rev C 全 schema**（带命名空间 ``http://webstds.ipc.org/2581``）：
   Ecad/CadData/Layer 层表 + Step/LayerFeature[@layerRef]/Set 几何——
   Set/Pad（Location + StandardPrimitiveRef→DictionaryStandard）→焊盘
   RectCenter 矩形/Circle 圆；Set/Features 的 UserPrimitiveRef→
   DictionaryUser 的 Contour/Polygon 多边形（走线填充轮廓）与直挂
   UserSpecial（板框等）。TEXT 笔画集与不可解析图元如实跳过并计数进
   annotations["ipc2581_skipped"]（best-effort，不阻塞读取）。
  """
  typed_path = Path(path)
  if not typed_path.exists():
    raise FileNotFoundError(f"IPC-2581 文件不存在: {typed_path}")
  root = ET.parse(str(typed_path)).getroot()
  if _ns_local(root) != _IPC2581_ROOT:
    raise ValueError(f"根元素不是 {_IPC2581_ROOT}: {root.tag}")
  content = root.find("{*}Content")
  if content is None:
    raise ValueError(f"IPC-2581 缺 Content 节: {typed_path}")
  if content.find("{*}StepRef") is not None or root.find(".//{*}CadData") is not None:
    return _import_ipc2581_full(root, typed_path)
  name = (content.findtext("{*}EcadName") or typed_path.stem).strip()
  layers = tuple(
    LayoutLayer(
      name=node.get("name", ""),
      gds_layer=int(node.get("gdsLayer", "0")),
      gds_datatype=int(node.get("gdsDatatype", "0")),
    )
    for node in content.findall("{*}Layer")
  )
  ann_node = content.find("{*}Annotations")
  annotations: dict[str, str] = (
    {node.get("name", ""): (node.text or "") for node in ann_node.findall("{*}Annotation")}
    if ann_node is not None
    else {}
  )
  items: list[LayoutItem] = []
  for feature_layer in content.findall("{*}StepData/{*}Step/{*}FeatureLayer"):
    layer_name = feature_layer.get("name", "")
    for node in feature_layer:
      if node.tag == "PathFeature":
        items.append(
          LayoutPath(
            points=tuple(
              (_parse_float(pt.get("x", "0")), _parse_float(pt.get("y", "0")))
              for pt in node.findall("Point")
            ),
            width_mm=_parse_float(node.get("width", "0")),
            layer=layer_name,
          )
        )
      elif node.tag == "PolygonFeature":
        items.append(
          LayoutPolygon(
            points=tuple(
              (_parse_float(pt.get("x", "0")), _parse_float(pt.get("y", "0")))
              for pt in node.findall("Point")
            ),
            layer=layer_name,
          )
        )
      elif node.tag == "CircleFeature":
        items.append(
          LayoutCircle(
            center=(_parse_float(node.get("cx", "0")), _parse_float(node.get("cy", "0"))),
            radius_mm=_parse_float(node.get("r", "0")),
            layer=layer_name,
          )
        )
      elif node.tag == "ViaFeature":
        items.append(
          LayoutVia(
            position=(_parse_float(node.get("cx", "0")), _parse_float(node.get("cy", "0"))),
            pad_diameter_mm=_parse_float(node.get("padDiameter", "0")),
            drill_diameter_mm=_parse_float(node.get("drillDiameter", "0")),
            pad_layer=layer_name,
          )
        )
  return Layout(name=name, layers=layers, items=tuple(items), annotations=annotations)


# ---------------------------------------------------------------------------
# IPC-2581 rev C 全 schema（KiCad 8+/10 原生导出）
# ---------------------------------------------------------------------------


def _import_ipc2581_full(root: ET.Element, typed_path: Path) -> Layout:
  """KiCad 原生 rev C 全 schema：Ecad/CadData/Layer + Step/LayerFeature/Set。

  坐标单位 mm（IPC-2581 惯例，KiCad 实证）；层表无 GDS 层号，按
  assign_gds_layers 兜底编号。TEXT 笔画集与不可解析图元跳过计数
  （annotations["ipc2581_skipped"]，best-effort）。
  """
  content = root.find("{*}Content")
  if content is None: # pragma: no cover - 调用方已校验
    raise ValueError(f"IPC-2581 缺 Content 节: {typed_path}")
  step_ref = content.find("{*}StepRef")
  steps = root.findall(".//{*}Step")
  name = ""
  if step_ref is not None and step_ref.get("name"):
    name = step_ref.get("name")
  elif steps and steps[0].get("name"):
    name = steps[0].get("name")
  name = name.strip() or typed_path.stem

  std_prims: dict[str, ET.Element] = {}
  dict_std = content.find("{*}DictionaryStandard")
  if dict_std is not None:
    for entry in dict_std.findall("{*}EntryStandard"):
      std_prims[entry.get("id", "")] = entry
  user_prims: dict[str, ET.Element] = {}
  dict_user = content.find("{*}DictionaryUser")
  if dict_user is not None:
    for entry in dict_user.findall("{*}EntryUser"):
      user_prims[entry.get("id", "")] = entry

  items: list[LayoutItem] = []
  skipped = 0
  for step in steps:
    for layer_feature in step.findall("{*}LayerFeature"):
      layer_name = layer_feature.get("layerRef", "")
      for set_node in layer_feature.findall("{*}Set"):
        taken, skipped_in_set = _ipc2581_consume_set(
          set_node, layer_name, std_prims, user_prims
        )
        items.extend(taken)
        skipped += skipped_in_set
  layer_names = [lay.get("name", "") for lay in root.findall(".//{*}CadData/{*}Layer")]
  layout = Layout(name=name, layers=assign_gds_layers(layer_names), items=tuple(items))
  if skipped:
    layout.annotations["ipc2581_skipped"] = str(skipped)
  return layout


def _ipc2581_consume_set(
  set_node: ET.Element,
  layer_name: str,
  std_prims: dict[str, ET.Element],
  user_prims: dict[str, ET.Element],
) -> tuple[list[LayoutItem], int]:
  """单个 LayerFeature/Set → 版图项：直挂 UserSpecial + Features 容器 + Pad 实例。

  返回 (项列表, 跳过计数)。TEXT 笔画集整集跳过（字符笔画库非结构几何）。
  """
  if (set_node.get("geometryUsage") or "").upper() == "TEXT":
    return [], 1
  items: list[LayoutItem] = []
  skipped = 0
  for special in set_node.findall("{*}UserSpecial"):
    polys, skipped_curved = _ipc2581_user_special_polygons(special, (0.0, 0.0), layer_name)
    items.extend(polys)
    skipped += skipped_curved
  features = set_node.find("{*}Features")
  if features is not None:
    loc = features.find("{*}Location")
    offset = (
      (float(loc.get("x", "0")), float(loc.get("y", "0"))) if loc is not None else (0.0, 0.0)
    )
    for child in features:
      local = _ns_local(child)
      if local == "Location":
        continue
      if local == "UserPrimitiveRef":
        prim = user_prims.get(child.get("id", ""))
        special = prim.find("{*}UserSpecial") if prim is not None else None
        if special is None:
          skipped += 1
          continue
        polys, skipped_curved = _ipc2581_user_special_polygons(
          special, offset, layer_name
        )
        items.extend(polys)
        skipped += skipped_curved
      elif local == "UserSpecial":
        # 板框/用户绘图形态：UserSpecial 直挂 Features（KiCad 10 实证）
        polys, skipped_curved = _ipc2581_user_special_polygons(
          child, offset, layer_name
        )
        items.extend(polys)
        skipped += skipped_curved
      else:
        skipped += 1
  for pad in set_node.findall("{*}Pad"):
    loc = pad.find("{*}Location")
    prim_ref = pad.find("{*}StandardPrimitiveRef")
    prim = std_prims.get(prim_ref.get("id", "")) if prim_ref is not None else None
    if loc is None or prim is None:
      skipped += 1
      continue
    item = _ipc2581_pad_item(prim, float(loc.get("x", "0")), float(loc.get("y", "0")), layer_name)
    if item is None:
      skipped += 1
    else:
      items.append(item)
  return items, skipped


def _ipc2581_user_special_polygons(
  special: ET.Element, offset: tuple[float, float], layer_name: str
) -> tuple[list[LayoutItem], int]:
  """UserSpecial 几何展开：Contour/Polygon→闭合 LayoutPolygon、Line→LayoutPath。

  PolyBegin/PolyStepSegment 逐点取值（闭合末点==首点去重）；Line
  （startX/startY/endX/endY + LineDesc.lineWidth，mm）为描边线段（KiCad 板框
  口径）；弧段 PolyStepCurve 无内接口径，如实跳过该轮廓并计数。
  """
  polys: list[LayoutItem] = []
  skipped = 0
  for polygon in special.findall("{*}Contour/{*}Polygon"):
    pts: list[tuple[float, float]] = []
    curved = False
    for node in polygon:
      local = _ns_local(node)
      if local in ("PolyBegin", "PolyStepSegment"):
        pts.append((float(node.get("x", "0")) + offset[0], float(node.get("y", "0")) + offset[1]))
      elif local == "PolyStepCurve":
        curved = True
        break
      # LineDescRef 等修饰节点忽略
    if curved:
      skipped += 1
      continue
    pts = _dedupe_closed(pts)
    if len(pts) >= 3:
      polys.append(LayoutPolygon(points=tuple(pts), layer=layer_name))
  for line in special.findall("{*}Line"):
    desc = line.find("{*}LineDesc")
    width = float(desc.get("lineWidth", "0")) if desc is not None else 0.0
    polys.append(
      LayoutPath(
        points=(
          (float(line.get("startX", "0")) + offset[0], float(line.get("startY", "0")) + offset[1]),
          (float(line.get("endX", "0")) + offset[0], float(line.get("endY", "0")) + offset[1]),
        ),
        width_mm=width,
        layer=layer_name,
      )
    )
  return polys, skipped


def _ipc2581_pad_item(
  prim: ET.Element, x: float, y: float, layer_name: str
) -> LayoutItem | None:
  """DictionaryStandard 图元 → 焊盘项：RectCenter→矩形（位精确）、
  Circle→圆；Oval/Donut/Thermal 等无声明口径，返回 None（跳过计数）。"""
  for child in prim:
    local = _ns_local(child)
    if local == "RectCenter":
      w = float(child.get("width", "0"))
      h = float(child.get("height", "0"))
      return LayoutPolygon(
        points=((x - w / 2.0, y - h / 2.0), (x + w / 2.0, y - h / 2.0), (x + w / 2.0, y + h / 2.0), (x - w / 2.0, y + h / 2.0)),
        layer=layer_name,
      )
    if local == "Circle":
      return LayoutCircle(
        center=(x, y), radius_mm=float(child.get("diameter", "0")) / 2.0, layer=layer_name
      )
  return None


# ---------------------------------------------------------------------------
# ODB++ 风格子集目录
# ---------------------------------------------------------------------------


def export_odbpp(layout: Layout, path: str | Path) -> Path:
  """导出 ODB++ 风格子集目录（matrix/matrix + steps/<step>/layers/*，UNITS=MM）。"""
  path = Path(path)
  step_name = _safe_name(layout.name)
  layers_dir = path / "steps" / step_name / "layers"
  matrix_dir = path / "matrix"
  layers_dir.mkdir(parents=True, exist_ok=True)
  matrix_dir.mkdir(parents=True, exist_ok=True)

  by_layer: dict[str, list[LayoutItem]] = {}
  for item in layout.items:
    by_layer.setdefault(_item_layer(item), []).append(item)

  matrix_rows = ["MATRIX"]
  for idx, (layer_name, layer_items) in enumerate(sorted(by_layer.items())):
    file_stem = _safe_name(layer_name)
    matrix_rows.append(f"{idx} 0 {layer_name} {file_stem} SIGNAL")
    lines = ["UNITS=MM"]
    lines += [f"#ANN {k}={v}" for k, v in sorted(layout.annotations.items())]
    for item in layer_items:
      if isinstance(item, LayoutPath):
        coords = " ".join(f"{_fmt(x)} {_fmt(y)}" for x, y in item.points)
        lines.append(f"L {coords} w={_fmt(item.width_mm)}")
      elif isinstance(item, LayoutPolygon):
        first, *rest = item.points
        lines.append(f"OB {_fmt(first[0])} {_fmt(first[1])}")
        for x, y in rest:
          lines.append(f"L {_fmt(x)} {_fmt(y)}")
        lines.append("OC")
      elif isinstance(item, LayoutCircle):
        lines.append(
          f"P {_fmt(item.center[0])} {_fmt(item.center[1])} CIRCLE r={_fmt(item.radius_mm)}"
        )
      elif isinstance(item, LayoutVia):
        lines.append(
          f"P {_fmt(item.position[0])} {_fmt(item.position[1])} CIRCLE "
          f"r={_fmt(item.pad_diameter_mm / 2.0)} d={_fmt(item.drill_diameter_mm)}"
        )
    (layers_dir / file_stem).write_text("\n".join(lines) + "\n", encoding="ascii")
  matrix_rows.append("UNITS=MM")
  (matrix_dir / "matrix").write_text("\n".join(matrix_rows) + "\n", encoding="ascii")
  logger.info("导出 ODB++ 子集: %s（%d 层文件）", path, len(by_layer))
  return path


def import_odbpp(path: str | Path) -> Layout:
  """读入 ODB++ 目录，自动识别两种形态：

  - **子集目录**（与 export_odbpp 互为逆操作）：matrix 行格式
   ``<row> 0 <layer_name> <file_stem> SIGNAL``。
  - **KiCad 10 原生真实 ODB++**：块式 matrix ``LAYER {...}``（NAME 大写、
   层目录为小写名、几何在各层 ``features`` 文件）——L 线段/P 焊盘
   （``$<idx>`` 符号表，KiCad 实证尺寸数字=µm）/S..OB..OS..OE..SE 表面。
   非 MM 单位与不支持符号如实跳过计数（annotations["odbpp_skipped"]）。
  """
  typed_path = Path(path)
  matrix_file = typed_path / "matrix" / "matrix"
  if not matrix_file.exists():
    raise FileNotFoundError(f"ODB++ 子集缺少 matrix/matrix: {typed_path}")
  matrix_text = matrix_file.read_text(encoding="utf-8", errors="replace")
  if _is_odbpp_full_matrix(matrix_text):
    return _import_odbpp_full(typed_path, matrix_text)
  # matrix 行格式：<row> 0 <layer_name> <file_stem> SIGNAL
  layer_map: dict[str, str] = {}
  annotations: dict[str, str] = {}
  for raw in matrix_text.splitlines():
    line = raw.strip()
    if not line or line == "MATRIX" or line.startswith("UNITS="):
      continue
    parts = line.split()
    if len(parts) >= 4:
      layer_map[parts[3]] = parts[2]

  items: list[LayoutItem] = []
  steps_dir = typed_path / "steps"
  step_dirs = sorted(steps_dir.iterdir()) if steps_dir.is_dir() else []
  for step_dir in step_dirs:
    layers_dir = step_dir / "layers"
    if not layers_dir.is_dir():
      continue
    for layer_file in sorted(layers_dir.iterdir()):
      layer_name = layer_map.get(layer_file.name, layer_file.name)
      items += _parse_odbpp_layer_file(layer_file, layer_name, annotations)
  layer_names = sorted({_item_layer(item) for item in items})
  return Layout(
    name=step_dirs[0].name if step_dirs else typed_path.name,
    layers=assign_gds_layers(layer_names),
    items=tuple(items),
    annotations=annotations,
  )


def _parse_odbpp_layer_file(
  layer_file: Path, layer_name: str, annotations: dict[str, str]
) -> list[LayoutItem]:
  """解析单层记录：L 路径 / OB..L..OC 多边形 / P 焊盘圆（d= 钻孔）。"""
  items: list[LayoutItem] = []
  in_outline = False
  outline_pts: list[tuple[float, float]] = []
  for raw in layer_file.read_text(encoding="ascii").splitlines():
    line = raw.strip()
    if not line or line.startswith("UNITS="):
      continue
    if line.startswith("#ANN "):
      key_value = line[len("#ANN "):]
      if "=" in key_value:
        key, value = key_value.split("=", 1)
        annotations[key.strip()] = value.strip()
      continue
    tokens = line.split()
    head = tokens[0]
    if head == "L":
      if in_outline:
        outline_pts.append((_parse_float(tokens[1]), _parse_float(tokens[2])))
      else:
        coord_tokens = [t for t in tokens[1:] if not t.startswith(("w=", "d=", "r="))]
        width_token = next((t for t in tokens if t.startswith("w=")), None)
        width = _parse_float(width_token[2:]) if width_token else 0.0
        pts = [
          (_parse_float(coord_tokens[i]), _parse_float(coord_tokens[i + 1]))
          for i in range(0, len(coord_tokens) - 1, 2)
        ]
        if len(pts) >= 2:
          items.append(LayoutPath(points=tuple(pts), width_mm=width, layer=layer_name))
    elif head == "OB":
      in_outline = True
      outline_pts = [(_parse_float(tokens[1]), _parse_float(tokens[2]))]
    elif head == "OC":
      in_outline = False
      if len(outline_pts) >= 3:
        items.append(LayoutPolygon(points=tuple(outline_pts), layer=layer_name))
    elif head == "P":
      pos = (_parse_float(tokens[1]), _parse_float(tokens[2]))
      radius_token = next((t for t in tokens if t.startswith("r=")), None)
      drill_token = next((t for t in tokens if t.startswith("d=")), None)
      if radius_token is None:
        continue
      radius = _parse_float(radius_token[2:])
      if drill_token is not None:
        items.append(
          LayoutVia(
            position=pos,
            pad_diameter_mm=radius * 2.0,
            drill_diameter_mm=_parse_float(drill_token[2:]),
            pad_layer=layer_name,
          )
        )
      else:
        items.append(LayoutCircle(center=pos, radius_mm=radius, layer=layer_name))
  return items


# ---------------------------------------------------------------------------
# ODB++ 真实格式（KiCad 10 原生导出）
# ---------------------------------------------------------------------------


def _is_odbpp_full_matrix(matrix_text: str) -> bool:
  """块式 matrix（``STEP {`` / ``LAYER {``）判定；子集行格式为单行空格分隔。"""
  for raw in matrix_text.splitlines():
    line = raw.strip()
    if line in ("STEP {", "LAYER {"):
      return True
    if line and not line.startswith(("#", "UNITS=", "MATRIX")):
      return False
  return False


def _iter_odbpp_blocks(matrix_text: str):
  """块式 matrix 解析器：yield (块类型, 字段字典)——``STEP {`` / ``LAYER {``。"""
  kind: str | None = None
  fields: dict[str, str] = {}
  for raw in matrix_text.splitlines():
    line = raw.strip()
    if kind is None:
      if line.endswith("{") and line[:-1].strip() in ("STEP", "LAYER"):
        kind = line[:-1].strip()
        fields = {}
      continue
    if line == "}":
      yield kind, fields
      kind = None
      continue
    if "=" in line:
      key, value = line.split("=", 1)
      fields[key.strip()] = value.strip()


_ODBPP_SYMBOL_PATTERNS = (
  (re.compile(r"rect([\d.]+)x([\d.]+)"), "rect"),
  (re.compile(r"oval([\d.]+)x([\d.]+)"), "oval"),
  (re.compile(r"r([\d.]+)"), "round"),
)


def _odbpp_symbol_size(name: str) -> tuple[str, float, float] | None:
  """KiCad ODB++ 符号名 → (形状, 宽mm, 高mm)。

  KiCad 10 实证：符号名尺寸数字=µm（``rect612.14x612.14`` ↔ IPC-2581 导出
  同焊盘 0.612140mm；``r304.80`` ↔ 板内 0.3048mm 描边线宽，r 语义=直径）。
  其余符号族（octagon/donut/thermal 等）无实证口径，返回 None 跳过计数。
  """
  for pattern, shape in _ODBPP_SYMBOL_PATTERNS:
    matched = pattern.fullmatch(name)
    if matched is None:
      continue
    w_um = float(matched.group(1))
    h_um = float(matched.group(2)) if pattern.groups == 2 else w_um
    return (shape, w_um / 1000.0, h_um / 1000.0)
  return None


def _import_odbpp_full(typed_path: Path, matrix_text: str) -> Layout:
  """KiCad 10 原生 ODB++：块式 matrix 层名映射 + 各层 features 记录。"""
  step_names: list[str] = []
  layer_map: dict[str, str] = {} # 层目录名（小写）→ matrix NAME
  for kind, fields in _iter_odbpp_blocks(matrix_text):
    name = fields.get("NAME", "").strip()
    if not name:
      continue
    if kind == "STEP":
      step_names.append(name)
    elif kind == "LAYER":
      layer_map[name.lower()] = name

  items: list[LayoutItem] = []
  annotations: dict[str, str] = {}
  steps_dir = typed_path / "steps"
  step_dirs = sorted(d for d in steps_dir.iterdir() if d.is_dir()) if steps_dir.is_dir() else []
  for step_dir in step_dirs:
    layers_dir = step_dir / "layers"
    if not layers_dir.is_dir():
      continue
    for layer_dir in sorted(layers_dir.iterdir()):
      features_file = layer_dir / "features"
      if not layer_dir.is_dir() or not features_file.exists():
        continue
      layer_name = layer_map.get(layer_dir.name.lower(), layer_dir.name)
      items += _parse_odbpp_features_file(features_file, layer_name, annotations)
  layer_names = sorted({_item_layer(item) for item in items})
  return Layout(
    name=step_names[0] if step_names else (step_dirs[0].name if step_dirs else typed_path.name),
    layers=assign_gds_layers(layer_names),
    items=tuple(items),
    annotations=annotations,
  )


def _parse_odbpp_features_file(
  features_file: Path, layer_name: str, annotations: dict[str, str]
) -> list[LayoutItem]:
  """解析真实 ODB++ 层 features 文件：L 线段 / P 焊盘 / S..OB..OS..OE..SE 表面。

  - 线段：``L x1 y1 x2 y2 <sym> [P|C n]``——线宽=符号直径（KiCad 实证）。
  - 焊盘：``P x y <sym> [P <drill_sym> ...]``——rect→矩形、round→圆；
   钻孔符号为 round 时升级为 LayoutVia，``0``/非 round=无钻孔。
  - 表面：每岛（OB..OE）一个闭合 LayoutPolygon（连续重复点与闭合末点去重）。
  - 非 MM 单位整层跳过并计数；弧（C/A）与不支持符号如实跳过计数。
  """
  items: list[LayoutItem] = []
  skipped = 0
  units = "MM"
  symbols: dict[str, str] = {}
  in_features = False
  island_pts: list[tuple[float, float]] = []

  def flush_island() -> None:
    nonlocal island_pts
    pts = _dedupe_closed(island_pts)
    island_pts = []
    if len(pts) >= 3:
      items.append(LayoutPolygon(points=tuple(pts), layer=layer_name))

  for raw in features_file.read_text(encoding="ascii", errors="replace").splitlines():
    line = raw.strip()
    if not line or line.startswith("UNITS="):
      if line.startswith("UNITS="):
        units = line[len("UNITS="):].strip().upper()
      continue
    if line.startswith("$"):
      parts = line.split(None, 1)
      if len(parts) == 2:
        symbols[parts[0][1:]] = parts[1].strip()
      continue
    if line.startswith("#"):
      if line.startswith("#Layer features"):
        in_features = True
      continue
    if not in_features:
      continue
    if units != "MM":
      skipped += 1 # 非 MM 实证口径，如实计数不猜换算
      continue
    toks = line.split()
    head = toks[0]
    if head == "L" and len(toks) >= 6:
      size = _odbpp_symbol_size(symbols.get(toks[5], ""))
      if size is None:
        skipped += 1
        continue
      items.append(
        LayoutPath(
          points=((float(toks[1]), float(toks[2])), (float(toks[3]), float(toks[4]))),
          width_mm=size[1],
          layer=layer_name,
        )
      )
    elif head == "P" and len(toks) >= 4:
      size = _odbpp_symbol_size(symbols.get(toks[3], ""))
      if size is None:
        skipped += 1
        continue
      shape, w_mm, h_mm = size
      pos = (float(toks[1]), float(toks[2]))
      drill_mm = _odbpp_pad_drill_mm(toks[4:], symbols)
      if drill_mm is not None:
        items.append(
          LayoutVia(
            position=pos,
            pad_diameter_mm=w_mm,
            drill_diameter_mm=drill_mm,
            pad_layer=layer_name,
          )
        )
      elif shape == "round":
        items.append(LayoutCircle(center=pos, radius_mm=w_mm / 2.0, layer=layer_name))
      else:
        items.append(
          LayoutPolygon(
            points=(
              (pos[0] - w_mm / 2.0, pos[1] - h_mm / 2.0),
              (pos[0] + w_mm / 2.0, pos[1] - h_mm / 2.0),
              (pos[0] + w_mm / 2.0, pos[1] + h_mm / 2.0),
              (pos[0] - w_mm / 2.0, pos[1] + h_mm / 2.0),
            ),
            layer=layer_name,
          )
        )
    elif head == "OB" and len(toks) >= 3:
      if island_pts:
        flush_island()
      island_pts = [(float(toks[1]), float(toks[2]))]
    elif head == "OS" and len(toks) >= 3:
      island_pts.append((float(toks[1]), float(toks[2])))
    elif head in ("OE", "SE"):
      flush_island()
    elif head == "S":
      pass # 表面起始（极性/填充标记），无几何
    else:
      skipped += 1 # 弧（C/A）等未摄记录如实计数
  if island_pts:
    flush_island()
  if skipped:
    prev = int(annotations.get("odbpp_skipped", "0"))
    annotations["odbpp_skipped"] = str(prev + skipped)
  return items


def _odbpp_pad_drill_mm(rest: list[str], symbols: dict[str, str]) -> float | None:
  """P 记录的钻孔子组（``P <drill_sym> ...``）→ 钻孔直径 mm；无/不适用= None。

  KiCad 对无钻孔焊盘写 ``P 0``；仅当钻孔符号可解析且为 round 时返回直径。
  """
  if len(rest) < 2 or rest[0] != "P" or rest[1] == "0":
    return None
  size = _odbpp_symbol_size(symbols.get(rest[1], ""))
  if size is None or size[0] != "round":
    return None
  return size[1]


# ---------------------------------------------------------------------------
# B1 桥：kicad_pcell.PCBDesign → Layout（B2 依赖 B1 的接入面）
# ---------------------------------------------------------------------------


def layout_from_pcb_design(design: PCBDesign, name: str = "pcb_design") -> Layout:
  """把 B1 的 PCBDesign（kicad_pcell）转成 Layout：trace→Path、via→Via、pad→Circle/Polygon。"""
  items: list[LayoutItem] = []
  layer_names: list[str] = ["Edge.Cuts"] if design.board_size else []
  if design.board_size:
    w, h = design.board_size
    items.append(LayoutPolygon(points=((0.0, 0.0), (w, 0.0), (w, h), (0.0, h)), layer="Edge.Cuts"))
  for trace in design.traces:
    items.append(
      LayoutPath(
        points=((trace.start[0], trace.start[1]), (trace.end[0], trace.end[1])),
        width_mm=trace.width,
        layer=trace.layer,
      )
    )
    layer_names.append(trace.layer)
  for via in design.vias:
    pad_layer = via.layers[0] if via.layers else "F.Cu"
    items.append(
      LayoutVia(
        position=(via.position[0], via.position[1]),
        pad_diameter_mm=via.pad,
        drill_diameter_mm=via.drill,
        pad_layer=pad_layer,
      )
    )
    layer_names.append(pad_layer)
  for pad in design.pads:
    pw, ph = pad.size
    if pad.shape == "rect":
      items.append(
        LayoutPolygon(
          points=(
            (pad.position[0] - pw / 2.0, pad.position[1] - ph / 2.0),
            (pad.position[0] + pw / 2.0, pad.position[1] - ph / 2.0),
            (pad.position[0] + pw / 2.0, pad.position[1] + ph / 2.0),
            (pad.position[0] - pw / 2.0, pad.position[1] + ph / 2.0),
          ),
          layer=pad.layer,
        )
      )
    else: # oval/circle → 圆（半径取短边/2，声明口径）
      items.append(
        LayoutCircle(
          center=(pad.position[0], pad.position[1]),
          radius_mm=min(pw, ph) / 2.0,
          layer=pad.layer,
        )
      )
    layer_names.append(pad.layer)
  return Layout(name=name, layers=assign_gds_layers(layer_names), items=tuple(items))
