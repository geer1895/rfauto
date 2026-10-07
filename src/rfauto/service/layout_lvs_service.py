"""LC-7 LVS 最小面：shapely 连通分量 → 几何网表 vs 参考连接表对照（flag 级）。

规格=研究扩充 round15 §四 LC-7："shapely 连通
分量→网表 vs compose layout_netlist 对照 flag 级"。本模块是**最小面**：

- 几何侧：单导电层图元（path=线宽/2 buffer、polygon/circle=本体）做
  shapely unary_union → 连通分量=网；端口（三来源解析或显式表）按位置
  落网；分量按 bounds (min_x, min_y) 确定性排序编号 N1..；
- 参考侧：pin 级连接表 ``{"connections": [[a, b], ...], "ports": [...]}``；
  :func:`expected_from_compose_netlist` 把 rfauto-netlist-v1 的
  connections/exposed_ports 折叠成 pin 级（实例维不参与几何对照——Layout
  无实例概念，折叠只取 pin_id，同 pin 多连接去重保序）；
- 对照 flag 级：逐期望连接 agree/disagree（disagree 带两侧网号诊断）、
  期望端口缺网/未落网、几何多出的端口如实列出不参与裁决；verdict=
  ``LVS_MATCH``（全部 agree 且无缺端口）/ ``LVS_FLAG``（其余）——不凑绿
  不静默（#122 口径）。

边界（如实登记）：v1 单层口径（via 跨层连接不在最小面内——pad 盘只按
pad_layer 参与）；layer 缺省=全部图元层的并集做 union（跨层几何天然被
union 判连，等价"所有层短接"口径，语义与单层不同——**要严格单层必须
显式传 layer**，错传时结果保守方向是"多判连接"，flag 级对照不会静默
漏接）。

shapely 为可选依赖（ extras 声明见汇报：``layout = ["gdstk>=1.0",
"shapely>=2.0"]``）；缺装显式 error 信封给安装提示，不裸 traceback。
"""

from __future__ import annotations

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
    "DEFAULT_JOIN_TOL_MM",
    "expected_from_compose_netlist",
    "lvs_check",
]

#: 端口点落网容差（mm）：端口面与导体边界的浮点接触余量。
DEFAULT_JOIN_TOL_MM = 1e-6


def expected_from_compose_netlist(netlist: dict[str, Any]) -> dict[str, Any]:
    """rfauto-netlist-v1 → pin 级参考连接表（折叠实例维；schema 钉校验）。

    connections ``[a, b]``（各为 ``[实例, pin]``）→ ``(a.pin, b.pin)``；
    exposed_ports ``{instance, pin}`` → pin id 列表。同 pin 多连接去重保序；
    空/缺 connections 合法（=0 期望连接，全靠端口落网裁决——LVS 参考面
    不做 compose 发射期的非空要求，故不走 normalize_netlist 的严格形态校验，
    只钉 schema 串与字段形态）。
    """
    from rfauto.core.compose.layout_netlist import COMPOSE_NETLIST_SCHEMA

    if not isinstance(netlist, dict):
        raise ValueError(f"netlist 必须为 dict: {type(netlist).__name__}")
    if str(netlist.get("schema")) != COMPOSE_NETLIST_SCHEMA:
        raise ValueError(
            f"netlist schema 必须为 {COMPOSE_NETLIST_SCHEMA!r}，得到 "
            f"{netlist.get('schema')!r}")
    conns_raw = netlist.get("connections") or []
    if not isinstance(conns_raw, list):
        raise ValueError("connections 必须为列表")
    pairs: list[list[str]] = []
    seen: set[tuple[str, str]] = set()
    for conn in conns_raw:
        a, b = str(conn["a"][1]), str(conn["b"][1])
        if (a, b) not in seen and (b, a) not in seen and a != b:
            seen.add((a, b))
            pairs.append([a, b])
    ports: list[str] = []
    for p in netlist.get("exposed_ports") or []:
        pin = str(p["pin"])
        if pin not in ports:
            ports.append(pin)
    return {"connections": pairs, "ports": ports}


def _item_geometry(item: LayoutItem):
    """图元 → shapely 几何（惰性 import；退化项返回 None 如实跳过）。"""
    from shapely.geometry import LineString, Point, Polygon

    if isinstance(item, LayoutPath):
        if len(item.points) < 2:
            return None
        line = LineString(item.points)
        if line.length <= 0.0:
            return None
        return line.buffer(item.width_mm / 2.0)
    if isinstance(item, LayoutPolygon):
        pts = list(item.points)
        if len(pts) < 3:
            return None
        poly = Polygon(pts)
        if poly.is_empty:
            return None
        return poly
    if isinstance(item, LayoutCircle):
        if item.radius_mm <= 0.0:
            return None
        return Point(item.center).buffer(item.radius_mm)
    if isinstance(item, LayoutVia):
        if item.pad_diameter_mm <= 0.0:
            return None
        return Point(item.position).buffer(item.pad_diameter_mm / 2.0)
    raise ValueError(f"未知版图项类型: {type(item).__name__}")


def _assign_nets(layout: Layout):
    """几何 → (分量清单, 统计)。分量按 bounds 确定性排序（N 编号的唯一依据）。"""
    from shapely.ops import unary_union

    geoms = []
    n_items = 0
    n_skipped = 0
    for item in layout.items:
        n_items += 1
        g = _item_geometry(item)
        if g is None or g.is_empty:
            n_skipped += 1
            continue
        geoms.append(g)
    union = unary_union(geoms) if geoms else None
    parts = []
    if union is not None and not union.is_empty:
        if union.geom_type == "Polygon":
            parts = [union]
        elif union.geom_type == "MultiPolygon":
            parts = list(union.geoms)
        elif union.geom_type == "GeometryCollection":
            parts = [g for g in union.geoms if g.geom_type == "Polygon"]
            multis = [g for g in union.geoms if g.geom_type == "MultiPolygon"]
            for m in multis:
                parts.extend(m.geoms)
    parts.sort(key=lambda p: (round(p.bounds[0], 9), round(p.bounds[1], 9),
                              round(p.bounds[2], 9), round(p.bounds[3], 9)))
    return parts, {"n_items": n_items, "n_degenerate_skipped": n_skipped,
                   "n_parts": len(parts)}


def lvs_check(
    layout_payload: dict[str, Any],
    expected: dict[str, Any],
    *,
    ports: list[dict[str, Any]] | None = None,
    port_kwargs: dict[str, Any] | None = None,
    layer: str | None = None,
    join_tol_mm: float = DEFAULT_JOIN_TOL_MM,
) -> dict[str, Any]:
    """几何网表 vs 参考连接表 flag 级对照（JSON 进出）。

    Args:
        layout_payload: 版图载荷（layout_service 契约）。
        expected: pin 级参考 ``{"connections": [[a,b],...], "ports": [...],
            ...}``；compose netlist 走 :func:`expected_from_compose_netlist`
            折叠后传入。缺 ``ports`` 键=只对照 connections（不查端口覆盖）。
        ports: 显式端口记录（layout_ports ``port_table_from_records`` 同款，
            ``{port_id, position_mm, direction, width_mm}``）；
        port_kwargs: 或三来源解析参数（resolve_ports 同参）——与 ``ports``
            二选一，都缺=只对照 connections、端口覆盖面 skipped 如实标注。
        layer: 导电层过滤（严格单层口径必须显式给；None=全层并集口径，
            见模块 docstring 边界说明）。
        join_tol_mm: 端口点落网容差（mm）。
    """
    try:
        import shapely  # noqa: F401  存在性探测（几何构造在 _item_geometry 内惰性）
    except ImportError as exc:
        return error_envelope(
            [f"shapely 未安装（LC-7 LVS 最小面依赖）：{exc}；"
             "安装：pip install rfauto[layout]（gdstk+shapely）"])

    try:
        layout = layout_from_payload(layout_payload)
    except (KeyError, TypeError, ValueError) as exc:
        return error_envelope([f"版图载荷解析失败: {exc}"])

    layer_set = {str(layer)} if layer is not None else None
    scoped = Layout(
        name=layout.name,
        layers=layout.layers,
        items=tuple(
            it for it in layout.items
            if layer_set is None
            or (it.pad_layer if isinstance(it, LayoutVia) else it.layer) in layer_set
        ),
        annotations=dict(layout.annotations),
    )
    if layer_set is not None and not scoped.items:
        return error_envelope(
            [f"层过滤后 0 图元（layer={layer!r}，版图现有层 "
             f"{sorted({(it.pad_layer if isinstance(it, LayoutVia) else it.layer) for it in layout.items})}）——"
             "检查层名，不猜"])

    try:
        parts, geom_stats = _assign_nets(scoped)
    except ValueError as exc:
        return error_envelope([str(exc)])

    # 端口来源：显式记录 > 三来源解析 > skipped
    ports_skipped_reason: str | None = None
    port_points: list[tuple[str, tuple[float, float]]] = []
    if ports is not None:
        from rfauto.adapters.layout_ports import port_table_from_records

        try:
            resolved = port_table_from_records(ports)
        except ValueError as exc:
            return error_envelope([f"显式端口记录解析失败: {exc}"])
        port_points = [(p.port_id, (p.position_m[0] * 1000.0,
                                    p.position_m[1] * 1000.0)) for p in resolved]
    elif port_kwargs is not None:
        from rfauto.adapters.layout_ports import resolve_ports

        try:
            res = resolve_ports(scoped, **port_kwargs)
        except ValueError as exc:
            return error_envelope([f"端口三来源解析失败: {exc}"])
        port_points = [(p.port_id, (p.position_m[0] * 1000.0,
                                    p.position_m[1] * 1000.0)) for p in res["ports"]]
    else:
        ports_skipped_reason = "未给 ports/port_kwargs——端口覆盖面不参与裁决"

    # 端口落网：Point.buffer(tol) 与分量的交非空即落网（先到先得，分量已排序）
    from shapely.geometry import Point

    net_of_port: dict[str, int] = {}
    unassigned: list[str] = []
    for port_id, (px, py) in port_points:
        probe = Point(px, py).buffer(join_tol_mm)
        hit = next((i for i, part in enumerate(parts) if part.intersects(probe)), None)
        if hit is None:
            unassigned.append(port_id)
        else:
            net_of_port[port_id] = hit

    connections = [(str(a), str(b)) for a, b in
                   (expected.get("connections") or [])]
    conn_flags = []
    all_agree = True
    for a, b in connections:
        na, nb = net_of_port.get(a), net_of_port.get(b)
        if na is not None and na == nb:
            conn_flags.append({"pair": [a, b], "flag": "agree", "net": f"N{na + 1}"})
        else:
            all_agree = False
            conn_flags.append({
                "pair": [a, b], "flag": "disagree",
                "net_a": None if na is None else f"N{na + 1}",
                "net_b": None if nb is None else f"N{nb + 1}",
                "detail": ("端口未落网" if na is None or nb is None
                           else "两端口落在不同连通分量"),
            })

    expected_ports = expected.get("ports")
    missing_ports: list[str] = []
    if expected_ports is not None:
        for pid in (str(p) for p in expected_ports):
            if pid not in net_of_port:
                missing_ports.append(pid)
                all_agree = False
    geometry_port_ids = [pid for pid, _ in port_points]
    extra_ports = sorted(set(geometry_port_ids)
                         - {str(p) for p in (expected_ports or [])}
                         - set(unassigned)) if expected_ports is not None else []

    verdict = "LVS_MATCH" if (all_agree and not unassigned) else "LVS_FLAG"
    return ok_envelope(
        verdict=verdict,
        layer=layer,
        nets=[{"net": f"N{i + 1}",
               "bounds_mm": [round(v, 9) for v in parts[i].bounds]}
              for i in range(len(parts))],
        ports_assigned={pid: f"N{ni + 1}" for pid, ni in sorted(net_of_port.items())},
        ports_unassigned=sorted(unassigned),
        connections=conn_flags,
        missing_ports=missing_ports,
        extra_geometry_ports=extra_ports,
        ports_face=ports_skipped_reason,
        geometry=geom_stats,
    )
