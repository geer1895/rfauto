"""版图服务层：JSON 进出的生成/导出/读入/往返报告薄壳（服务层薄壳）。

CLI/MCP 若要暴露版图互操作，直接消费本模块的 *_payload 函数；
数值与几何全部来自确定性内核（adapters/layout_generator、
adapters/layout_interchange），本层只做编解码与编排。
"""

from __future__ import annotations

import json
import logging
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rfauto.adapters.layout_generator import LAYOUT_GENERATORS, generate_layout
from rfauto.adapters.layout_interchange import (
    FORMAT_ROUNDTRIP_CAPABILITIES,
    LAYOUT_INTERCHANGE_FORMATS,
    Layout,
    LayoutCircle,
    LayoutLayer,
    LayoutPath,
    LayoutPolygon,
    LayoutVia,
    import_layout,
    round_trip_delta,
    verify_round_trip,
)

logger = logging.getLogger(__name__)

#: 注记键：服务层载荷中标注布局来源。
PAYLOAD_SOURCE_KEY = "source"


def layout_to_payload(layout: Layout) -> dict[str, Any]:
    """Layout → JSON 可序列化 dict。"""
    return {
        "name": layout.name,
        "layers": [
            {"name": lay.name, "gds_layer": lay.gds_layer, "gds_datatype": lay.gds_datatype}
            for lay in layout.layers
        ],
        "items": [_item_to_payload(item) for item in layout.items],
        "annotations": dict(layout.annotations),
    }


def _item_to_payload(item: LayoutPath | LayoutPolygon | LayoutCircle | LayoutVia) -> dict[str, Any]:
    if isinstance(item, LayoutPath):
        return {
            "kind": "path",
            "points": [[x, y] for x, y in item.points],
            "width_mm": item.width_mm,
            "layer": item.layer,
        }
    if isinstance(item, LayoutPolygon):
        return {"kind": "polygon", "points": [[x, y] for x, y in item.points], "layer": item.layer}
    if isinstance(item, LayoutCircle):
        return {
            "kind": "circle",
            "center": [item.center[0], item.center[1]],
            "radius_mm": item.radius_mm,
            "layer": item.layer,
        }
    return {
        "kind": "via",
        "position": [item.position[0], item.position[1]],
        "pad_diameter_mm": item.pad_diameter_mm,
        "drill_diameter_mm": item.drill_diameter_mm,
        "pad_layer": item.pad_layer,
    }


def layout_from_payload(payload: dict[str, Any]) -> Layout:
    """JSON dict → Layout（缺注记/层表时按内容兜底）。"""
    items = [_item_from_payload(node) for node in payload.get("items", [])]
    layers = payload.get("layers")
    if layers is None:
        from rfauto.adapters.layout_interchange import assign_gds_layers

        names = sorted(
            {
                node["layer"] if node["kind"] != "via" else node["pad_layer"]
                for node in payload.get("items", [])
            }
        )
        layers = [
            {"name": lay.name, "gds_layer": lay.gds_layer, "gds_datatype": lay.gds_datatype}
            for lay in assign_gds_layers(names)
        ]
    return Layout(
        name=str(payload.get("name", "layout")),
        layers=tuple(
            LayoutLayer(
                name=str(node["name"]),
                gds_layer=int(node["gds_layer"]),
                gds_datatype=int(node.get("gds_datatype", 0)),
            )
            for node in layers
        ),
        items=tuple(items),
        annotations={str(k): str(v) for k, v in payload.get("annotations", {}).items()},
    )


def _item_from_payload(node: dict[str, Any]) -> LayoutPath | LayoutPolygon | LayoutCircle | LayoutVia:
    kind = node["kind"]
    if kind == "path":
        return LayoutPath(
            points=tuple((float(x), float(y)) for x, y in node["points"]),
            width_mm=float(node["width_mm"]),
            layer=str(node["layer"]),
        )
    if kind == "polygon":
        return LayoutPolygon(
            points=tuple((float(x), float(y)) for x, y in node["points"]),
            layer=str(node["layer"]),
        )
    if kind == "circle":
        return LayoutCircle(
            center=(float(node["center"][0]), float(node["center"][1])),
            radius_mm=float(node["radius_mm"]),
            layer=str(node["layer"]),
        )
    if kind == "via":
        return LayoutVia(
            position=(float(node["position"][0]), float(node["position"][1])),
            pad_diameter_mm=float(node["pad_diameter_mm"]),
            drill_diameter_mm=float(node["drill_diameter_mm"]),
            pad_layer=str(node["pad_layer"]),
        )
    raise ValueError(f"未知版图项 kind: {kind!r}")


def generate_layout_payload(
    kind: str,
    params: dict[str, Any],
    *,
    fmt: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """参数化生成版图（B5），可选直接导出（B2 出口）。JSON 进出。"""
    layout = generate_layout(kind, params)
    result: dict[str, Any] = {
        "kind": kind,
        "layout": layout_to_payload(layout),
        "exported_path": None,
    }
    if fmt is not None:
        if output_path is None:
            raise ValueError("fmt 给出时必须同时给 output_path")
        result["exported_path"] = str(Path(output_path))
        export_layout_payload(result["layout"], output_path, fmt)
        result["exported_format"] = fmt
    return result


def export_layout_payload(layout_payload: dict[str, Any], path: str, fmt: str) -> dict[str, Any]:
    """版图载荷 → 互操作文件。返回 {"path", "fmt", "n_items"}。"""
    layout = layout_from_payload(layout_payload)
    out = import_export_path(layout, path, fmt)
    return {"path": str(out), "fmt": fmt.lower(), "n_items": len(layout.items)}


def import_export_path(layout: Layout, path: str, fmt: str) -> Path:
    """导出并返回 Path（薄层转发，集中 Path 归一）。"""
    from rfauto.adapters.layout_interchange import export_layout

    return export_layout(layout, Path(path), fmt)


def laymap_conflicts(mapping: Mapping[Any, Any]) -> list[str]:
    """laymap 冲突盘点（告警级校验内核，P2⑳ 批登记 followUp）——不 raise、只描述。

    两族静默冲突（键/值均按 ``str(int(key))`` 归一口径检重）：

    - 键归一冲突：两个原始键归一后同键（如 ``"01"`` 与 ``1``），构造结果
      dict 时后者静默覆盖前者，被覆盖方无从察觉；
    - 值冲突（登记主项）：多个 GDS 层号映射到同一目标层名——adapters 层
      ``_apply_laymap`` 按名改层，两个不同 GDS 层会静默合并为同一 KiCad
      层（几何归属改变），可能是有意合层也可能是笔误，故只告警不阻塞。

    返回人可读、可定位的冲突描述列表；无冲突返回空列表。非层号键跳过
    （由 :func:`load_laymap` 的 ValueError 负责，此处不重复报错）。
    """
    by_norm_key: dict[str, list[Any]] = {}
    by_value: dict[str, list[str]] = {}
    for key, value in mapping.items():
        try:
            norm = str(int(key))
        except (TypeError, ValueError):
            continue
        by_norm_key.setdefault(norm, []).append(key)
        by_value.setdefault(str(value), []).append(norm)
    conflicts: list[str] = []
    for norm, raw_keys in by_norm_key.items():
        if len(raw_keys) > 1:
            conflicts.append(
                f"键归一冲突: {[str(k) for k in raw_keys]} 均归一为 {norm!r}"
                "（构造结果时后者静默覆盖前者）")
    for value, keys in sorted(by_value.items()):
        if len(keys) > 1:
            conflicts.append(
                f"值冲突: 层号 {keys} 均映射到 {value!r}"
                "（多个 GDS 层将合并为同一目标层）")
    return conflicts


def load_laymap(path: str | Path) -> dict[str, str]:
    """读外部 laymap 层名映射文件：{GDS 层号串: 模板层名}。

    按后缀分派：``.json``（stdlib json）/ ``.yaml``、``.yml``（惰性 import yaml，
    循 service/api.py validate_recipe 惯例）。键统一 ``str(int(key))`` 归一
    （YAML 整型键坑：YAML 里 ``1:`` 会解析成 int 键）；未知后缀 ValueError、
    缺文件 FileNotFoundError、顶层非映射或键非层号 ValueError。

    值冲突告警级校验（P2⑳ 批登记 followUp，TODO C24）：键归一冲突/多键
    同目标值不 raise、不改变返回语义（键冲突保持"后者覆盖"），只
    ``warnings.warn`` 给出可定位清单——合层可能是用户本意，判读留给人。
    """
    typed_path = Path(path)
    if not typed_path.exists():
        raise FileNotFoundError(f"laymap 文件不存在: {typed_path}")
    suffix = typed_path.suffix.lower()
    if suffix == ".json":
        raw: Any = json.loads(typed_path.read_text(encoding="utf-8"))
    elif suffix in (".yaml", ".yml"):
        import yaml  # 惰性导入：仅 YAML laymap 通道需要

        raw = yaml.safe_load(typed_path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"不支持的 laymap 文件后缀: {suffix!r}；支持 .json/.yaml/.yml")
    if not isinstance(raw, dict):
        raise ValueError(f"laymap 文件顶层必须是 层号→层名 映射: {typed_path}")
    result: dict[str, str] = {}
    for key, value in raw.items():
        try:
            layer_key = str(int(key))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"laymap 键必须是 GDS 层号（整数）: {key!r}（{typed_path}）") from exc
        result[layer_key] = str(value)
    conflicts = laymap_conflicts(raw)
    if conflicts:
        warnings.warn(
            f"laymap 冲突（告警级，不阻塞导入）: {typed_path}；" + "；".join(conflicts),
            stacklevel=2,
        )
    return result


def import_layout_payload(
    path: str, fmt: str, laymap_path: str | None = None
) -> dict[str, Any]:
    """互操作文件 → 版图载荷。

    ``laymap_path``（可选）：外部 laymap 层名映射文件，语义仅 gdsii
    （GDS 层号→模板层名，消费 adapters 层 import_gdsii 的 laymap 参数）；
    缺省 None 读回层号串名，JSON 进出契约不变、payload 不加新键。
    """
    laymap = load_laymap(laymap_path) if laymap_path is not None else None
    return layout_to_payload(import_layout(Path(path), fmt, laymap=laymap))


def round_trip_report(
    layout_payload: dict[str, Any],
    workdir: str,
    formats: list[str] | None = None,
) -> dict[str, Any]:
    """对指定格式集合做导出→读回→裁判，返回逐格式 delta 与无损判定。"""
    layout = layout_from_payload(layout_payload)
    fmt_list = list(formats or LAYOUT_INTERCHANGE_FORMATS)
    unknown = [f for f in fmt_list if f.lower() not in LAYOUT_INTERCHANGE_FORMATS]
    if unknown:
        raise ValueError(f"不支持的版图互操作格式: {unknown}；支持 {LAYOUT_INTERCHANGE_FORMATS}")
    per_format: dict[str, Any] = {}
    for fmt in fmt_list:
        verdict = verify_round_trip(layout, fmt, Path(workdir))
        caps = FORMAT_ROUNDTRIP_CAPABILITIES[fmt.lower()]
        verdict["carries_drill"] = bool(caps["drill_carried"])
        verdict["carries_annotations"] = bool(caps["annotations_carried"])
        per_format[fmt.lower()] = verdict
    return {
        "name": layout.name,
        "n_items": len(layout.items),
        "all_lossless": all(v["lossless"] for v in per_format.values()),
        "formats": per_format,
        "generators_registered": sorted(LAYOUT_GENERATORS),
    }


def round_trip_delta_payload(
    origin_payload: dict[str, Any], roundtripped_payload: dict[str, Any], fmt: str
) -> float:
    """两份版图载荷在 fmt 口径下的往返差（mm；0=无损，inf=结构不一致）。"""
    return round_trip_delta(
        layout_from_payload(origin_payload), layout_from_payload(roundtripped_payload), fmt
    )
