"""B5 参数化版图生成器：参数 → Layout，经 B2 出口输出 GDSII/DXF/IPC-2581/ODB++。

方案依据： B5「参数化版图输出」，验收「与 B2 合并验收」（往返无损）。
生成器是纯确定性内核（数值只出自本文件的确定性规则，LLM 只给参数），
产出 adapters/layout_interchange.Layout，统一走 export_layout 输出制造文件。

放杆规则（钉在单测）：
- via fence：沿折线每段从 offset（默认 0）起、每 pitch 一个过孔，s ≤ seg_len
 计入；跨段共享端点按 1nm 格点去重。
- 板框：无显式 board 时按几何 + margin 自动外扩。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from itertools import pairwise
from typing import Any

from rfauto.adapters.layout_interchange import (
  Layout,
  LayoutCircle,
  LayoutLayer,
  LayoutPath,
  LayoutPolygon,
  LayoutVia,
  assign_gds_layers,
)

#: 生成器注册表（键=生成器名，值=params dict → Layout 的纯函数）。
LAYOUT_GENERATORS: dict[str, Callable[[Mapping[str, Any]], Layout]] = {}


def register_layout_generator(kind: str, fn: Callable[[Mapping[str, Any]], Layout]) -> None:
  """注册生成器（新器件族版图 = 一个纯函数 + 一次注册）。"""
  if kind in LAYOUT_GENERATORS:
    raise ValueError(f"版图生成器已注册: {kind}")
  LAYOUT_GENERATORS[kind] = fn


def generate_layout(kind: str, params: Mapping[str, Any]) -> Layout:
  """按注册名调生成器。未知名 ValueError 列出可用注册。"""
  fn = LAYOUT_GENERATORS.get(kind)
  if fn is None:
    raise ValueError(f"未知版图生成器: {kind!r}；可用: {sorted(LAYOUT_GENERATORS)}")
  return fn(params)


def _board_layers(edge_layer: str, extra: Sequence[str]) -> tuple[LayoutLayer, ...]:
  return assign_gds_layers([edge_layer, *extra])


def generate_microstrip(params: Mapping[str, Any]) -> Layout:
  """参数化微带线版图：板框 + 馈线 + 可选端焊盘 + 可选地过孔栅栏。

  params:
    width_mm: 线宽 (mm)
    length_mm: 线长 (mm)
    margin_mm: 线到板缘留白（默认 2.5mm），用于自动板框
    board_width_mm / board_height_mm: 显式板框（给了则不自动外扩）
    trace_layer: 默认 "F.Cu"
    edge_layer: 默认 "Edge.Cuts"
    end_pad_diameter_mm: 可选，两端焊盘直径（默认 0=不画）
    via_fence: 可选 dict(pitch_mm, pad_diameter_mm, drill_diameter_mm,
      offset_mm=0.0, inset_mm=1.0)——沿馈线两侧 inset 处布地过孔栅栏
  """
  width = float(params["width_mm"])
  length = float(params["length_mm"])
  margin = float(params.get("margin_mm", 2.5))
  board_w = float(params.get("board_width_mm", length + 2.0 * margin))
  board_h = float(params.get("board_height_mm", width + 2.0 * margin))
  trace_layer = str(params.get("trace_layer", "F.Cu"))
  edge_layer = str(params.get("edge_layer", "Edge.Cuts"))

  items: list[LayoutPath | LayoutPolygon | LayoutCircle | LayoutVia] = [
    LayoutPolygon(points=((0.0, 0.0), (board_w, 0.0), (board_w, board_h), (0.0, board_h)), layer=edge_layer)
  ]
  y_mid = board_h / 2.0
  x0 = (board_w - length) / 2.0
  items.append(
    LayoutPath(points=((x0, y_mid), (x0 + length, y_mid)), width_mm=width, layer=trace_layer)
  )
  end_pad = float(params.get("end_pad_diameter_mm", 0.0))
  if end_pad > 0.0:
    for cx in (x0, x0 + length):
      items.append(
        LayoutCircle(center=(cx, y_mid), radius_mm=end_pad / 2.0, layer=trace_layer)
      )

  fence = params.get("via_fence")
  if fence:
    rail_points = [(x0, y_mid), (x0 + length, y_mid)]
    inset = float(fence.get("inset_mm", 1.0))
    for sign in (-1.0, 1.0):
      rail = [(px, py + sign * inset) for px, py in rail_points]
      items += via_fence_items(
        points=rail,
        pitch_mm=float(fence["pitch_mm"]),
        pad_diameter_mm=float(fence["pad_diameter_mm"]),
        drill_diameter_mm=float(fence["drill_diameter_mm"]),
        pad_layer=trace_layer,
        offset_mm=float(fence.get("offset_mm", 0.0)),
      )
  return Layout(
    name=str(params.get("name", "microstrip")),
    layers=_board_layers(edge_layer, [trace_layer]),
    items=tuple(items),
  )


def generate_patch_antenna(params: Mapping[str, Any]) -> Layout:
  """参数化贴片天线版图：板框 + 贴片矩形 + 底馈。

  params:
    patch_width_mm / patch_length_mm: 贴片宽（x）/长（y）
    feed_width_mm: 馈线宽
    feed_length_mm: 馈线长（从板缘 y=0 到贴片下缘）
    margin_mm: 贴片到板缘留白（默认 3.0mm，x 向与上缘）
    trace_layer / edge_layer
  """
  patch_w = float(params["patch_width_mm"])
  patch_l = float(params["patch_length_mm"])
  feed_w = float(params["feed_width_mm"])
  feed_l = float(params["feed_length_mm"])
  margin = float(params.get("margin_mm", 3.0))
  trace_layer = str(params.get("trace_layer", "F.Cu"))
  edge_layer = str(params.get("edge_layer", "Edge.Cuts"))

  board_w = patch_w + 2.0 * margin
  board_h = feed_l + patch_l + margin
  cx = board_w / 2.0
  items: list[LayoutPath | LayoutPolygon | LayoutCircle | LayoutVia] = [
    LayoutPolygon(points=((0.0, 0.0), (board_w, 0.0), (board_w, board_h), (0.0, board_h)), layer=edge_layer),
    LayoutPolygon(
      points=(
        (cx - patch_w / 2.0, feed_l),
        (cx + patch_w / 2.0, feed_l),
        (cx + patch_w / 2.0, feed_l + patch_l),
        (cx - patch_w / 2.0, feed_l + patch_l),
      ),
      layer=trace_layer,
    ),
    LayoutPath(points=((cx, 0.0), (cx, feed_l)), width_mm=feed_w, layer=trace_layer),
  ]
  return Layout(
    name=str(params.get("name", "patch")),
    layers=_board_layers(edge_layer, [trace_layer]),
    items=tuple(items),
  )


def via_fence_items(
  points: Sequence[tuple[float, float]],
  pitch_mm: float,
  pad_diameter_mm: float,
  drill_diameter_mm: float,
  pad_layer: str = "F.Cu",
  offset_mm: float = 0.0,
) -> list[LayoutVia]:
  """沿折线布地过孔栅栏（B5 放杆规则内核，独立可测）。

  每段从 offset 起每 pitch 一个，s ≤ seg_len + 1e-12 计入；跨段共享端点按
  1nm 格点去重（先到先得）。
  """
  if pitch_mm <= 0.0:
    raise ValueError(f"pitch 必须为正: {pitch_mm}")
  if pad_diameter_mm <= drill_diameter_mm:
    raise ValueError(
      f"焊盘直径 {pad_diameter_mm} 必须大于钻孔直径 {drill_diameter_mm}"
    )
  vias: list[LayoutVia] = []
  seen: set[tuple[int, int]] = set()
  for (x1, y1), (x2, y2) in pairwise(points):
    seg_len = math.hypot(x2 - x1, y2 - y1)
    if seg_len <= 0.0:
      continue
    if seg_len < offset_mm:
      continue
    ux, uy = (x2 - x1) / seg_len, (y2 - y1) / seg_len
    n_posts = math.floor((seg_len - offset_mm) / pitch_mm + 1e-12) + 1
    for k in range(n_posts):
      s = offset_mm + k * pitch_mm
      if s > seg_len + 1e-12:
        break
      px, py = x1 + ux * s, y1 + uy * s
      key = (round(px * 1e6), round(py * 1e6))
      if key in seen:
        continue
      seen.add(key)
      vias.append(
        LayoutVia(
          position=(px, py),
          pad_diameter_mm=pad_diameter_mm,
          drill_diameter_mm=drill_diameter_mm,
          pad_layer=pad_layer,
        )
      )
  return vias


def generate_via_fence(params: Mapping[str, Any]) -> Layout:
  """参数化过孔栅栏版图（板框可选）。

  params: points（折线 [[x,y],...]）、pitch_mm、pad_diameter_mm、
    drill_diameter_mm、offset_mm=0.0、pad_layer="F.Cu"、
    edge_layer=None（给则画 0,0-board 外扩 2mm 板框? 否——board_width/height 显式给）
  """
  points = [(float(x), float(y)) for x, y in params["points"]]
  pitch = float(params["pitch_mm"])
  pad_d = float(params["pad_diameter_mm"])
  drill_d = float(params["drill_diameter_mm"])
  pad_layer = str(params.get("pad_layer", "F.Cu"))
  edge_layer = str(params.get("edge_layer", "Edge.Cuts"))
  vias = via_fence_items(
    points=points,
    pitch_mm=pitch,
    pad_diameter_mm=pad_d,
    drill_diameter_mm=drill_d,
    pad_layer=pad_layer,
    offset_mm=float(params.get("offset_mm", 0.0)),
  )
  items: list[LayoutPath | LayoutPolygon | LayoutCircle | LayoutVia] = list(vias)
  board_w = params.get("board_width_mm")
  board_h = params.get("board_height_mm")
  if board_w is not None and board_h is not None:
    items.insert(
      0,
      LayoutPolygon(
        points=((0.0, 0.0), (float(board_w), 0.0), (float(board_w), float(board_h)), (0.0, float(board_h))),
        layer=edge_layer,
      ),
    )
  return Layout(
    name=str(params.get("name", "via_fence")),
    layers=_board_layers(edge_layer, [pad_layer]),
    items=tuple(items),
  )


def generate_pad_array(params: Mapping[str, Any]) -> Layout:
  """参数化焊盘阵列：rows×cols 网格圆盘。

  params: rows, cols, pitch_mm, pad_diameter_mm, origin=(x0,y0)（阵列中心），
    pad_layer="F.Cu", edge_layer/板框可选
  """
  rows = int(params["rows"])
  cols = int(params["cols"])
  pitch = float(params["pitch_mm"])
  pad_d = float(params["pad_diameter_mm"])
  x0, y0 = (float(v) for v in params.get("origin", (0.0, 0.0)))
  pad_layer = str(params.get("pad_layer", "F.Cu"))
  edge_layer = str(params.get("edge_layer", "Edge.Cuts"))
  if rows < 1 or cols < 1:
    raise ValueError(f"rows/cols 必须 ≥1: {rows}x{cols}")
  items: list[LayoutPath | LayoutPolygon | LayoutCircle | LayoutVia] = [
    LayoutCircle(
      center=(x0 + (c - (cols - 1) / 2.0) * pitch, y0 + (r - (rows - 1) / 2.0) * pitch),
      radius_mm=pad_d / 2.0,
      layer=pad_layer,
    )
    for r in range(rows)
    for c in range(cols)
  ]
  board_w = params.get("board_width_mm")
  board_h = params.get("board_height_mm")
  if board_w is not None and board_h is not None:
    items.insert(
      0,
      LayoutPolygon(
        points=((0.0, 0.0), (float(board_w), 0.0), (float(board_w), float(board_h)), (0.0, float(board_h))),
        layer=edge_layer,
      ),
    )
  return Layout(
    name=str(params.get("name", "pad_array")),
    layers=_board_layers(edge_layer, [pad_layer]),
    items=tuple(items),
  )


register_layout_generator("microstrip", generate_microstrip)
register_layout_generator("patch_antenna", generate_patch_antenna)
register_layout_generator("via_fence", generate_via_fence)
register_layout_generator("pad_array", generate_pad_array)
