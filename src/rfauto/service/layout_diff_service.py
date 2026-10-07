"""LC-6 版图 diff/版本化：层/图元/端口三面语义 diff（纯确定性，JSON 进出）。

规格=研究扩充 round15 §四 LC-6："层/图元/端口
三面语义 diff（借 gdsfactory 快照机制不抄依赖）"。本模块不引入 gdsfactory，
diff 语义自实现：

- **层面**：层名集合增删 + 同名层 GDS 层号/datatype 变更（版本化注册层
  表漂移是 KiCad 重导常见漂移源，单列不与图元混算）；
- **图元面**：逐项规范化指纹（kind+层+量化坐标）多重集差——added/removed/
  n_common；量化栅格缺省 1 nm（layout_interchange 往返裁判同量级，只吸收
  浮点表示噪声，不吞真实几何改动）；同指纹共现计数对消（同形重复图元
  复制 N→N-1 只报 removed 1 条）；
- **端口面**（opt-in）：resolve_ports 三来源同参解析两侧（显式不静默——
  解析失败=error 信封，不退化为"无端口"），按量化位置配对后比 id/宽度/
  方向/类型/参考阻抗，改名/改几何分列。

零 I/O 零全局态：Layout 载荷进出（layout_service 同款 JSON 契约），
CLI/MCP/UI 若要暴露直接消费 :func:`diff_layout_payload`。
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from rfauto.adapters.layout_interchange import (
    Layout,
    LayoutCircle,
    LayoutItem,
    LayoutPath,
    LayoutPolygon,
    LayoutVia,
)
from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.layout_service import layout_from_payload

__all__ = [
    "DEFAULT_TOL_NM",
    "diff_layout_payload",
    "item_fingerprint",
]

#: 图元/端口几何量化栅格（nm）：同 layout_interchange 往返裁判量级
#: （gdstk nm 整数存储 1-ulp 舍入口径），只吸收浮点噪声。
DEFAULT_TOL_NM = 1.0

#: 端口配对位置容差（mm）＝量化栅格换算；方向/宽度比较用相对判据。
_PORT_POS_TOL_MM = DEFAULT_TOL_NM * 1e-6


def _bucket(value: float, grid_mm: float) -> float:
    """量化桶索引（整数格）；非有限值原样透传（由指纹比较如实报不同）。

    指纹存桶索引不存回乘值：divide-round-multiply 回乘会把恰在半界的
    值放大成不同栅格点（15.0+0.5nm 案），整数索引比较对两侧对称稳定。
    """
    if not math.isfinite(value):
        return value
    return round(value / grid_mm)


def _dequant(bucket: float, grid_mm: float) -> float:
    """桶索引 → mm 显示值（仅 JSON 展出面用；指纹比较只看桶索引）。"""
    if isinstance(bucket, int):
        return round(bucket * grid_mm, 9)
    return bucket


def item_fingerprint(item: LayoutItem, grid_mm: float) -> tuple:
    """图元语义指纹（kind+层+量化几何桶索引；多重集差的最小单元）。

    量化只作用于坐标/尺寸标量（整数桶索引，见 :func:`_bucket`）；层名与
    kind 全等比较（层改名=层面 diff 的职责，图元面如实报增删，不做跨层
    模糊匹配）。
    """
    if isinstance(item, LayoutPath):
        return (
            "path", item.layer, _bucket(item.width_mm, grid_mm),
            tuple((_bucket(x, grid_mm), _bucket(y, grid_mm)) for x, y in item.points),
        )
    if isinstance(item, LayoutPolygon):
        return (
            "polygon", item.layer,
            tuple((_bucket(x, grid_mm), _bucket(y, grid_mm)) for x, y in item.points),
        )
    if isinstance(item, LayoutCircle):
        return (
            "circle", item.layer,
            _bucket(item.center[0], grid_mm), _bucket(item.center[1], grid_mm),
            _bucket(item.radius_mm, grid_mm),
        )
    if isinstance(item, LayoutVia):
        return (
            "via", item.pad_layer,
            _bucket(item.position[0], grid_mm), _bucket(item.position[1], grid_mm),
            _bucket(item.pad_diameter_mm, grid_mm), _bucket(item.drill_diameter_mm, grid_mm),
        )
    raise ValueError(f"未知版图项类型: {type(item).__name__}")


def _fingerprint_to_dict(fp: tuple, grid_mm: float) -> dict[str, Any]:
    """指纹 → JSON 可序列化 dict（桶索引回乘 mm 仅展示；与 payload 键同形）。"""
    kind = fp[0]
    if kind == "path":
        return {"kind": "path", "layer": fp[1], "width_mm": _dequant(fp[2], grid_mm),
                "points": [[_dequant(x, grid_mm), _dequant(y, grid_mm)] for x, y in fp[3]]}
    if kind == "polygon":
        return {"kind": "polygon", "layer": fp[1],
                "points": [[_dequant(x, grid_mm), _dequant(y, grid_mm)] for x, y in fp[2]]}
    if kind == "circle":
        return {"kind": "circle", "layer": fp[1],
                "center": [_dequant(fp[2], grid_mm), _dequant(fp[3], grid_mm)],
                "radius_mm": _dequant(fp[4], grid_mm)}
    return {"kind": "via", "pad_layer": fp[1],
            "position": [_dequant(fp[2], grid_mm), _dequant(fp[3], grid_mm)],
            "pad_diameter_mm": _dequant(fp[4], grid_mm),
            "drill_diameter_mm": _dequant(fp[5], grid_mm)}


def _layer_face(a: Layout, b: Layout) -> dict[str, Any]:
    names_a = {lay.name: lay for lay in a.layers}
    names_b = {lay.name: lay for lay in b.layers}
    added = sorted(names_b.keys() - names_a.keys())
    removed = sorted(names_a.keys() - names_b.keys())
    changed = []
    for name in sorted(names_a.keys() & names_b.keys()):
        la, lb = names_a[name], names_b[name]
        if la.gds_layer != lb.gds_layer or la.gds_datatype != lb.gds_datatype:
            changed.append({
                "name": name,
                "a": {"gds_layer": la.gds_layer, "gds_datatype": la.gds_datatype},
                "b": {"gds_layer": lb.gds_layer, "gds_datatype": lb.gds_datatype},
            })
    return {"added": added, "removed": removed, "changed": changed}


def _items_face(a: Layout, b: Layout, grid_mm: float) -> dict[str, Any]:
    fa = Counter(item_fingerprint(it, grid_mm) for it in a.items)
    fb = Counter(item_fingerprint(it, grid_mm) for it in b.items)
    common = fa & fb  # 逐指纹计数对消：同形项 min(count) 为共现
    added = fb - fa
    removed = fa - fb
    kinds_a = Counter(fp[0] for fp in fa.elements())
    kinds_b = Counter(fp[0] for fp in fb.elements())
    return {
        "added": [_fingerprint_to_dict(fp, grid_mm) for fp in sorted(added.elements(), key=repr)],
        "removed": [_fingerprint_to_dict(fp, grid_mm) for fp in sorted(removed.elements(), key=repr)],
        "n_common": sum(common.values()),
        "counts": {
            "a_total": len(a.items), "b_total": len(b.items),
            "by_kind_a": dict(sorted(kinds_a.items())),
            "by_kind_b": dict(sorted(kinds_b.items())),
        },
    }


def _port_face(
    a: Layout, b: Layout, port_kwargs: dict[str, Any] | None
) -> dict[str, Any] | None:
    if port_kwargs is None:  # 显式 None=未启用；空 dict 走 resolve_ports 显错（#117 falsy 陷阱）
        return None
    from rfauto.adapters.layout_ports import resolve_ports

    ra = resolve_ports(a, **port_kwargs)
    rb = resolve_ports(b, **port_kwargs)
    pa, pb = ra["ports"], rb["ports"]

    def _key(port):  # 量化位置配对键（同图元栅格口径）
        return (round(port.position_m[0] * 1000.0 / _PORT_POS_TOL_MM),
                round(port.position_m[1] * 1000.0 / _PORT_POS_TOL_MM))

    ka, kb = {p.port_id: _key(p) for p in pa}, {p.port_id: _key(p) for p in pb}
    pos_a = {_key(p): p for p in pa}
    pos_b = {_key(p): p for p in pb}
    renamed = []
    changed = []
    for key in sorted(set(ka.values()) & set(kb.values())):
        id_a = next(i for i, k in ka.items() if k == key)
        id_b = next(i for i, k in kb.items() if k == key)
        x = pos_a[key]
        y = pos_b[key]
        if id_a != id_b:
            renamed.append({"position_mm": [x.position_m[0] * 1000.0,
                                             x.position_m[1] * 1000.0],
                            "a": id_a, "b": id_b})
        if (abs(x.width_m - y.width_m) > 1e-12
                or x.port_type != y.port_type or x.z_ref_ohm != y.z_ref_ohm):
            changed.append({"a": id_a, "b": id_b,
                            "width_m": [x.width_m, y.width_m],
                            "port_type": [x.port_type, y.port_type],
                            "z_ref_ohm": [x.z_ref_ohm, y.z_ref_ohm]})
    ids_a, ids_b = set(ka), set(kb)
    return {
        "added": sorted(ids_b - ids_a),
        "removed": sorted(ids_a - ids_b),
        "renamed": renamed,
        "changed": changed,
        "source": [ra["source"], rb["source"]],
    }


def diff_layout_payload(
    a_payload: dict[str, Any],
    b_payload: dict[str, Any],
    *,
    port_kwargs: dict[str, Any] | None = None,
    tol_nm: float = DEFAULT_TOL_NM,
) -> dict[str, Any]:
    """两份版图载荷三面语义 diff（JSON 进出；ok/False=error 信封）。

    Args:
        a_payload / b_payload: layout_service 契约的版图载荷（a=基线，b=新）。
        port_kwargs: 端口面 opt-in——layout_ports.resolve_ports 的同参 dict
            （``{"marker_layer": "Ports"}`` / ``{"port_table": [...]}`` /
            ``{"heuristic": True, "heuristic_layers": ["F.Cu"]}``）；None=
            端口面跳过（``ports: None`` 如实标注，不猜端口）。
        tol_nm: 量化栅格（nm，缺省 1）——只吸收浮点表示噪声。
    """
    if tol_nm <= 0:
        return error_envelope([f"tol_nm 必须为正: {tol_nm!r}"])
    try:
        a = layout_from_payload(a_payload)
        b = layout_from_payload(b_payload)
    except (KeyError, TypeError, ValueError) as exc:
        return error_envelope([f"版图载荷解析失败: {exc}"])
    try:
        layers = _layer_face(a, b)
        items = _items_face(a, b, tol_nm * 1e-6)
        ports = _port_face(a, b, port_kwargs)
    except ValueError as exc:
        # resolve_ports 冲突/空端口等显式错误如实上报（不静默退化）
        return error_envelope([f"端口面解析失败: {exc}"])
    identical = (
        not layers["added"] and not layers["removed"] and not layers["changed"]
        and not items["added"] and not items["removed"]
        and (ports is None or (
            not ports["added"] and not ports["removed"]
            and not ports["renamed"] and not ports["changed"]))
    )
    return ok_envelope(
        name_a=a.name, name_b=b.name, tol_nm=tol_nm,
        identical=identical,
        layers=layers,
        items=items,
        ports=ports,
    )
