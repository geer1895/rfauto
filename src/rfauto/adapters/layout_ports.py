"""F-I P2 端口三来源：标记层几何 / YAML 显式表 / 端点启发式 → 统一端口 schema。

方案依据：研究扩充 round5 §二 F-I 三段计划 P2——
"端口三来源（标记层/YAML/端点启发式——复用 compose pin 契约 schema）"；
spec §二 架构件 2："半自动：开路端点检测建议端口候选（几何启发式，确定性）"。

三路来源与优先级（显式 > 隐式，冲突不静默）
--------------------------------------------
- **marker（标记层几何）**：专用标记层上的 2 点线段=端口标记——第 1 点为
  端口位置、方向指向第 2 点（画向结构内部）、线宽=端口宽度；非 2 点线段 /
  其他几何项如实跳过计数（不猜）；
- **yaml（显式表）**：``{"ports": [{port_id, position_mm, direction,
  width_mm, ...}]}`` 结构化声明（JSON 进出友好， 规则 4 形态）；
- **heuristic（端点启发式）**：同层几何段集上做开路端点检测——路径端点
  若不落在（按点到线段距离、容差口径）任何非本径关联段上，即为开路候选；
  方向=沿本径指向内侧。启发式是**建议面**（半自动），单独启用时为权威来源
  并打 ``advisory`` 标，与显式来源共存时只做交叉验证报告，不做裁决。

优先级：``marker > yaml > heuristic``。两路**显式**来源同时给出端口且几何
不一致 → **显式 ValueError**（多来源给出不同端口不静默）；显式来源产生
0 端口且无启发式兜底 → 显式 ValueError。

契约对齐（读后对齐，零 import 耦合）
------------------------------------
统一端口 schema :class:`LayoutPort` 的 ``to_pin_dict`` 逐键对齐
``core/compose/layout_netlist`` docstring 钉的 pin 字典形态
（pin_id/position/direction/z_ref_ohm/ref_plane_offset_m/port_type/
n_modes/cross_section/width_m）——键集一致性由测试钉住（对齐不耦合：
adapters 不 import core）。

单位约定
--------
- 内部一律**米**（B2 Layout mm、YAML 表 mm 入口显式 ``×1e-3``，不隐式）；
- 方向存**单位向量**（构造期归一，确定性；零向量显式 ValueError）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from rfauto.adapters.layout_interchange import (
    Layout,
    LayoutCircle,
    LayoutPath,
    LayoutPolygon,
    LayoutVia,
    circle_to_polygon,
)

__all__ = [
    "COMPOSE_PIN_KEYS",
    "DIR_DOT_MIN",
    "PORT_SOURCES",
    "PORT_TYPES",
    "POSITION_TOL_M",
    "WIDTH_RTOL",
    "LayoutPort",
    "load_port_table",
    "port_table_from_records",
    "ports_from_marker_layer",
    "ports_from_open_ends",
    "resolve_ports",
]

#: 端口来源全集（优先级序：marker > yaml > heuristic）。
PORT_SOURCES: tuple[str, ...] = ("marker", "yaml", "heuristic")

#: 端口类型值域（compose PIN_PORT_TYPES 的发射器支持子集同口径；
#: waveguide/field 为 P3+ 预留，本模块显式拒绝）。
PORT_TYPES: tuple[str, ...] = ("lumped", "msl")

#: 两来源位置一致判据（米）：逐位交叉验证容差（同源数字经同式换算应逐位同，
#: 容差只吸收浮点表示噪声，#283 同口径 1e-9）。
POSITION_TOL_M = 1e-9

#: 宽度一致判据（相对）。
WIDTH_RTOL = 1e-9

#: 方向一致判据：单位向量点积下限（≈1−1e-12）。
DIR_DOT_MIN = 1.0 - 1e-12

#: compose pin 契约键集（core/compose/layout_netlist docstring 钉的形态；
#: to_pin_dict 输出键集与其全等，由测试双向钉住）。
COMPOSE_PIN_KEYS: tuple[str, ...] = (
    "pin_id",
    "position",
    "direction",
    "z_ref_ohm",
    "ref_plane_offset_m",
    "port_type",
    "n_modes",
    "cross_section",
    "width_m",
)

_MM_TO_M = 1e-3


def _require_number(value: Any, what: str) -> float:
    """数值收口：拒 bool（float(True)=1.0 静默污染，df7⑯）、拒非有限。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{what} 必须为数值: {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{what} 必须有限: {value!r}")
    return out


def _require_pair(value: Any, what: str) -> tuple[float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise ValueError(f"{what} 必须为二元序列: {value!r}")
    return (_require_number(value[0], f"{what}[0]"), _require_number(value[1], f"{what}[1]"))


# ---------------------------------------------------------------------------
# 统一端口 schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayoutPort:
    """统一端口定义（三来源归一产物；compose pin 契约的导入版形态）。

    ``direction`` 构造期归一为单位向量（零向量/非有限显式 ValueError）；
    ``source`` 记录裁决来源（marker|yaml|heuristic），交叉验证不改写来源。
    """

    port_id: str
    position_m: tuple[float, float]
    direction: tuple[float, float]
    width_m: float
    port_type: str = "lumped"
    z_ref_ohm: float = 50.0
    layer: str | None = None
    source: str = "marker"

    def __post_init__(self) -> None:
        if not isinstance(self.port_id, str) or not self.port_id:
            raise ValueError(f"port_id 必须为非空字符串: {self.port_id!r}")
        pos = (_require_number(self.position_m[0], "position_m[0]"),
               _require_number(self.position_m[1], "position_m[1]"))
        dx = _require_number(self.direction[0], "direction[0]")
        dy = _require_number(self.direction[1], "direction[1]")
        norm = math.hypot(dx, dy)
        if norm <= 0.0:
            raise ValueError(f"端口 {self.port_id!r} 方向为零向量——不猜朝向，显式给非零方向")
        width = _require_number(self.width_m, "width_m")
        if width <= 0.0:
            raise ValueError(f"端口 {self.port_id!r} width_m 必须为正: {self.width_m!r}")
        if self.port_type not in PORT_TYPES:
            raise ValueError(
                f"端口 {self.port_id!r} port_type 必须在 {PORT_TYPES} 内: {self.port_type!r}"
                "（waveguide/field 为 P3+ 预留）")
        z_ref = _require_number(self.z_ref_ohm, "z_ref_ohm")
        if z_ref <= 0.0:
            raise ValueError(f"端口 {self.port_id!r} z_ref_ohm 必须为正: {self.z_ref_ohm!r}")
        if self.source not in PORT_SOURCES:
            raise ValueError(f"端口 {self.port_id!r} source 必须在 {PORT_SOURCES} 内: {self.source!r}")
        if self.layer is not None and not isinstance(self.layer, str):
            raise ValueError(f"端口 {self.port_id!r} layer 必须为字符串或 None: {self.layer!r}")
        object.__setattr__(self, "position_m", pos)
        object.__setattr__(self, "direction", (dx / norm, dy / norm))
        object.__setattr__(self, "width_m", width)
        object.__setattr__(self, "z_ref_ohm", z_ref)

    def to_pin_dict(self) -> dict[str, Any]:
        """→ compose pin 契约形态 dict（键集 = COMPOSE_PIN_KEYS，测试双向钉）。

        ``ref_plane_offset_m`` v1 恒 0.0（参考面=端口面）、``n_modes`` 恒 1
        （准 TEM 口径）——字段在契约里占位，语义扩展属 P3。
        """
        return {
            "pin_id": self.port_id,
            "position": [self.position_m[0], self.position_m[1]],
            "direction": [self.direction[0], self.direction[1]],
            "z_ref_ohm": self.z_ref_ohm,
            "ref_plane_offset_m": 0.0,
            "port_type": self.port_type,
            "n_modes": 1,
            "cross_section": {"layer": self.layer} if self.layer is not None else {},
            "width_m": self.width_m,
        }


def _ports_agree(a: Sequence[LayoutPort], b: Sequence[LayoutPort]) -> bool:
    """两来源端口集一致性（几何+电学判据；来源标注/层名不参与——
    marker 层名与 YAML 手填层名天然可不同）。按 (x, y) 排序后逐对判：
    位置 Euclid ≤ POSITION_TOL_M、方向点积 ≥ DIR_DOT_MIN、宽度相对差
    ≤ WIDTH_RTOL、port_type/z_ref_ohm 全等。"""
    if len(a) != len(b):
        return False
    sa = sorted(a, key=lambda p: (p.position_m[0], p.position_m[1]))
    sb = sorted(b, key=lambda p: (p.position_m[0], p.position_m[1]))
    for pa, pb in zip(sa, sb, strict=True):
        if math.hypot(pa.position_m[0] - pb.position_m[0],
                      pa.position_m[1] - pb.position_m[1]) > POSITION_TOL_M:
            return False
        dot = pa.direction[0] * pb.direction[0] + pa.direction[1] * pb.direction[1]
        if dot < DIR_DOT_MIN:
            return False
        if abs(pa.width_m - pb.width_m) > WIDTH_RTOL * max(pa.width_m, pb.width_m):
            return False
        if pa.port_type != pb.port_type or pa.z_ref_ohm != pb.z_ref_ohm:
            return False
    return True


# ---------------------------------------------------------------------------
# 来源 A：标记层几何
# ---------------------------------------------------------------------------


def ports_from_marker_layer(
    layout: Layout,
    marker_layer: str,
    *,
    port_type: str = "lumped",
    z_ref_ohm: float = 50.0,
) -> tuple[list[LayoutPort], dict[str, Any]]:
    """标记层 2 点线段 → 端口列表（确定性；位置=第 1 点、方向→第 2 点）。

    标记层上非 2 点线段与其他几何项（多边形/圆/过孔）如实跳过计数，
    不猜不静默（stats["skipped"]）。产出按位置 (x, y) 升序、id ``P{n}``。
    """
    raw: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    skipped: list[dict[str, str]] = []
    for item in layout.items:
        layer = item.pad_layer if isinstance(item, LayoutVia) else item.layer
        if layer != marker_layer:
            continue
        if isinstance(item, LayoutPath):
            pts = item.points
            if len(pts) == 2 and pts[0] != pts[1]:
                raw.append((pts[0], pts[1], float(item.width_mm)))
                continue
            skipped.append({
                "kind": "path",
                "reason": f"点数={len(pts)}（v1 标记=2 点线段且两端不同）",
            })
        else:
            skipped.append({
                "kind": type(item).__name__,
                "reason": "项类型不构成端口标记（v1 标记=2 点线段）",
            })
    raw.sort(key=lambda t: (t[0][0], t[0][1]))
    ports = [
        LayoutPort(
            port_id=f"P{i + 1}",
            position_m=(p0[0] * _MM_TO_M, p0[1] * _MM_TO_M),
            direction=(p1[0] - p0[0], p1[1] - p0[1]),
            width_m=width * _MM_TO_M,
            port_type=port_type,
            z_ref_ohm=z_ref_ohm,
            layer=marker_layer,
            source="marker",
        )
        for i, (p0, p1, width) in enumerate(raw)
    ]
    return ports, {
        "n_marker_items": len(raw) + len(skipped),
        "n_ports": len(ports),
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# 来源 B：YAML 显式表
# ---------------------------------------------------------------------------


def port_table_from_records(
    records: Sequence[Mapping[str, Any]], *, default_port_type: str = "lumped"
) -> list[LayoutPort]:
    """端口表记录列表 → LayoutPort 列表（保持记录顺序；port_id 唯一性显错）。

    每条记录必填 ``port_id``/``position_mm``/``direction``/``width_mm``；
    可选 ``port_type``（缺省 ``default_port_type``）/``z_ref_ohm``（缺省
    50.0）/``layer``。缺字段/重复 id/零方向显式 ValueError，不猜。
    """
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError(f"端口表记录必须为列表: {type(records).__name__}")
    ports: list[LayoutPort] = []
    seen: set[str] = set()
    for i, rec in enumerate(records):
        if not isinstance(rec, Mapping):
            raise ValueError(f"端口表第 {i} 条必须是映射: {type(rec).__name__}")
        missing = [k for k in ("port_id", "position_mm", "direction", "width_mm") if k not in rec]
        if missing:
            raise ValueError(f"端口表第 {i} 条缺字段 {missing}")
        port_id = str(rec["port_id"])
        if not port_id:
            raise ValueError(f"端口表第 {i} 条 port_id 为空")
        if port_id in seen:
            raise ValueError(f"端口表 port_id 重复: {port_id!r}")
        seen.add(port_id)
        pos_mm = _require_pair(rec["position_mm"], f"端口 {port_id!r} position_mm")
        direction = _require_pair(rec["direction"], f"端口 {port_id!r} direction")
        width_mm = _require_number(rec["width_mm"], f"端口 {port_id!r} width_mm")
        port_type = rec.get("port_type", default_port_type)
        layer = rec.get("layer")
        ports.append(
            LayoutPort(
                port_id=port_id,
                position_m=(pos_mm[0] * _MM_TO_M, pos_mm[1] * _MM_TO_M),
                direction=direction,
                width_m=width_mm * _MM_TO_M,
                port_type=str(port_type),
                z_ref_ohm=_require_number(rec.get("z_ref_ohm", 50.0), f"端口 {port_id!r} z_ref_ohm"),
                layer=str(layer) if layer is not None else None,
                source="yaml",
            )
        )
    return ports


def load_port_table(path: str | Path, *, default_port_type: str = "lumped") -> list[LayoutPort]:
    """YAML 端口表文件 → LayoutPort 列表（顶层 ``{"ports": [...]}``，严格形态）。

    yaml 惰性导入（layout_stack.load_stackup 同惯例）；顶层非映射或缺
    ``ports`` 列表显式 ValueError。
    """
    import yaml  # 惰性导入：仅 YAML 端口表通道需要

    typed_path = Path(path)
    if not typed_path.exists():
        raise FileNotFoundError(f"端口表 YAML 不存在: {typed_path}")
    data = yaml.safe_load(typed_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("ports"), list):
        raise ValueError(
            f"端口表 YAML 顶层必须是 {{\"ports\": [...]}}: {typed_path}")
    return port_table_from_records(data["ports"], default_port_type=default_port_type)


# ---------------------------------------------------------------------------
# 来源 C：端点启发式（开路端点检测，确定性）
# ---------------------------------------------------------------------------


def _point_segment_distance_mm(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """点到线段距离（mm；标准参数化投影，端点截断）。"""
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    denom = abx * abx + aby * aby
    if denom == 0.0:
        return math.hypot(apx, apy)
    t = max(0.0, min(1.0, (apx * abx + apy * aby) / denom))
    return math.hypot(px - (ax + t * abx), py - (ay + t * aby))


def ports_from_open_ends(
    layout: Layout,
    *,
    tol_mm: float = 1e-6,
    layers: Sequence[str] | None = None,
    port_type: str = "lumped",
    z_ref_ohm: float = 50.0,
) -> tuple[list[LayoutPort], dict[str, Any]]:
    """开路端点检测 → 端口候选列表（几何启发式，确定性；合成几何可回收）。

    算法（v1 端点-线段口径）：

    - 线段集 = 同层 LayoutPath 折线段 + LayoutPolygon 边界环 + LayoutCircle
      内接多边形环（确定性圆离散同 B2 口径）；层过滤（``layers`` 为 None
      处理全部层；**建议只传导电层**——抑制判定为同层口径（跨层几何不互连），
      不过滤时标记层注记线两端会作为额外候选混入）；
    - 候选端点 = 每个 LayoutPath 的首/末端点；开路判据 = 该端点到同层
      除**本端关联段**（该端点所在的折线首/末段，即延续方向所在段）外
      任一线段的最小距离 ≤ ``tol_mm`` 则视为连接（抑制）；同径非关联段
      参与判据（折线自闭合端=自连接，不误报开路）；
    - 端口方向 = 沿本径指向内侧（相邻点 − 端点，归一）；宽度 = 路径宽度。

    v1 已知边界（如实登记）：端点落在多边形**内部**（埋入焊盘，不触边）的
    连接不被识别为抑制——此类结构请走显式来源（marker/yaml）。

    产出按位置 (x, y) 升序、id ``P{n}``、source="heuristic"。
    """
    layer_set = set(layers) if layers is not None else None
    segs_by_layer: dict[str, list[tuple[int, tuple[float, float], tuple[float, float]]]] = {}
    endpoints: list[dict[str, Any]] = []
    n_paths = 0
    n_degenerate = 0

    def add_ring(layer: str, path_key: int, pts: Sequence[tuple[float, float]], *, closed: bool) -> None:
        ring = list(pts)
        if closed and ring and ring[0] != ring[-1]:
            ring.append(ring[0])
        seg_list = segs_by_layer.setdefault(layer, [])
        for a, b in pairwise(ring):
            if a != b:
                seg_list.append((path_key, a, b))

    for item in layout.items:
        layer = item.pad_layer if isinstance(item, LayoutVia) else item.layer
        if layer_set is not None and layer not in layer_set:
            continue
        if isinstance(item, LayoutPath):
            n_paths += 1
            pts = list(item.points)
            path_key = id(item)
            add_ring(layer, path_key, pts, closed=False)
            for idx, nbr_idx, inc in (
                (0, 1, (path_key, pts[0], pts[1])),
                (len(pts) - 1, len(pts) - 2, (path_key, pts[-2], pts[-1])),
            ):
                end, nbr = pts[idx], pts[nbr_idx]
                if end == nbr:  # 退化零长路径：方向无定义，如实计数不猜
                    n_degenerate += 1
                    continue
                endpoints.append(
                    {"layer": layer, "path_key": path_key, "end": end, "nbr": nbr,
                     "width_mm": float(item.width_mm), "incident": inc})
        elif isinstance(item, LayoutPolygon):
            add_ring(layer, id(item), item.points, closed=True)
        elif isinstance(item, LayoutCircle):
            add_ring(layer, id(item), circle_to_polygon(item.center, item.radius_mm), closed=True)
        # LayoutVia：v1 不参与启发式（P1 桥同样跳过 via），如实不计数为段

    ports: list[LayoutPort] = []
    open_raw: list[tuple[float, float, float, float, float, str]] = []
    n_suppressed = 0
    for ep in endpoints:
        ex, ey = ep["end"]
        open_end = True
        for path_key, a, b in segs_by_layer.get(ep["layer"], []):
            if (path_key, a, b) == ep["incident"]:
                continue  # 本端关联段（延续段）豁免；同径其余段正常参与（自闭合=连接）
            if _point_segment_distance_mm(ex, ey, a[0], a[1], b[0], b[1]) <= tol_mm:
                open_end = False
                break
        if not open_end:
            n_suppressed += 1
            continue
        open_raw.append((ex, ey, ep["nbr"][0] - ex, ep["nbr"][1] - ey,
                         ep["width_mm"], ep["layer"]))
    open_raw.sort(key=lambda t: (t[0], t[1]))
    ports = [
        LayoutPort(
            port_id=f"P{i + 1}",
            position_m=(ex * _MM_TO_M, ey * _MM_TO_M),
            direction=(dx, dy),
            width_m=width * _MM_TO_M,
            port_type=port_type,
            z_ref_ohm=z_ref_ohm,
            layer=layer,
            source="heuristic",
        )
        for i, (ex, ey, dx, dy, width, layer) in enumerate(open_raw)
    ]
    stats = {
        "n_paths": n_paths,
        "n_endpoints": len(endpoints),
        "n_open": len(ports),
        "n_suppressed": n_suppressed,
        "n_degenerate": n_degenerate,
        "layers_processed": sorted(segs_by_layer),
    }
    return ports, stats


# ---------------------------------------------------------------------------
# 三来源裁决（优先级 + 冲突显错）
# ---------------------------------------------------------------------------


def resolve_ports(
    layout: Layout,
    *,
    marker_layer: str | None = None,
    port_table: Sequence[Mapping[str, Any]] | None = None,
    heuristic: bool = False,
    heuristic_layers: Sequence[str] | None = None,
    port_type: str = "lumped",
) -> dict[str, Any]:
    """三来源解析 → 统一端口（优先级 marker > yaml > heuristic；冲突显错）。

    裁决规则（全部显式，不静默）：

    - 未启用任何来源 → ValueError；
    - 两路**显式**来源都产生端口：几何+电学判据逐对一致 → 取 marker
      （优先级），``cross_check["marker_vs_yaml"]="agree"``（交叉验证逐位）；
      不一致 → **ValueError** 列出双端坐标/方向差（多来源给出不同端口
      不静默）；
    - 显式来源启用但都产生 0 端口：启发式启用 → 回落启发式（来源与
      ``advisory=True`` 如实标注）；否则 ValueError（声明了端口却得到空，
      多半是层名/几何配错，报错好过静默空端口集）；
    - 启发式与显式权威并存：只做交叉验证报告（候选/权威双向覆盖清单，
      ``consistent`` 布尔）——启发式是建议面，不做否决。

    返回::

        {"ports": [LayoutPort...], "source": str, "advisory": bool,
         "cross_check": {"marker_vs_yaml": "agree"|None,
                          "heuristic": {"n_candidates", "consistent",
                                         "unmatched_candidates", "uncovered"} | None},
         "stats": {...}}
    """
    enabled = {
        "marker": marker_layer is not None,
        "yaml": port_table is not None,
        "heuristic": bool(heuristic),
    }
    if not any(enabled.values()):
        raise ValueError(
            "端口三来源未启用任何一路——给 marker_layer / port_table / heuristic=True 至少其一")

    marker_stats: dict[str, Any] | None = None
    marker_ports: list[LayoutPort] = []
    if enabled["marker"]:
        marker_ports, marker_stats = ports_from_marker_layer(
            layout, marker_layer, port_type=port_type)
    yaml_ports = port_table_from_records(port_table) if enabled["yaml"] else []

    explicit: dict[str, list[LayoutPort]] = {}
    if marker_ports:
        explicit["marker"] = marker_ports
    if yaml_ports:
        explicit["yaml"] = yaml_ports

    cross_check: dict[str, Any] = {"marker_vs_yaml": None, "heuristic": None}
    if len(explicit) == 2:
        if not _ports_agree(explicit["marker"], explicit["yaml"]):
            raise ValueError(
                "端口来源冲突（marker vs yaml 几何/电学不一致，不静默）：marker="
                f"{[p.to_pin_dict() for p in explicit['marker']]}；"
                f"yaml={[p.to_pin_dict() for p in explicit['yaml']]}；"
                "判据：位置 Euclid≤1e-9 m、方向点积≥1−1e-12、宽度相对差≤1e-9、"
                "port_type/z_ref 全等")
        cross_check["marker_vs_yaml"] = "agree"

    if explicit:
        source = "marker" if "marker" in explicit else "yaml"
        ports = list(explicit[source])
        advisory = False
    else:
        empty_detail = (
            f"marker 层 {marker_layer!r} 无有效 2 点标记"
            if enabled["marker"] and marker_stats is not None
            else "YAML 端口表为空")
        if not enabled["heuristic"]:
            raise ValueError(
                f"显式端口来源产生 0 端口（{empty_detail}）且未启用启发式——不静默回退")
        source, ports, advisory = "heuristic", [], True

    if enabled["heuristic"]:
        candidates, heur_stats = ports_from_open_ends(
            layout, layers=heuristic_layers, port_type=port_type)
        if not ports and candidates:
            ports, source, advisory = candidates, "heuristic", True
        elif ports:
            sa = sorted(ports, key=lambda p: (p.position_m[0], p.position_m[1]))
            sb = sorted(candidates, key=lambda p: (p.position_m[0], p.position_m[1]))
            matched_b: set[int] = set()
            unmatched_candidates: list[dict[str, Any]] = []
            for cand in sb:
                hit = next(
                    (j for j, auth in enumerate(sa)
                     if j not in matched_b and _pair_agrees(auth, cand)),
                    None,
                )
                if hit is None:
                    unmatched_candidates.append(
                        {"position_mm": [cand.position_m[0] / _MM_TO_M,
                                         cand.position_m[1] / _MM_TO_M],
                         "direction": [cand.direction[0], cand.direction[1]]})
                else:
                    matched_b.add(hit)
            uncovered = [sa[j].port_id for j in range(len(sa)) if j not in matched_b]
            cross_check["heuristic"] = {
                "n_candidates": len(candidates),
                "consistent": not unmatched_candidates and not uncovered,
                "unmatched_candidates": unmatched_candidates,
                "uncovered": uncovered,
                "stats": heur_stats,
            }

    if not ports:
        raise ValueError(
            "三来源均未产生端口（启发式未发现开路端点）——0 端口不静默；"
            "检查 layers 过滤（应只含导电层）与版图连通性")

    stats: dict[str, Any] = {"enabled_sources": [k for k, on in enabled.items() if on]}
    if marker_stats is not None:
        stats["marker"] = marker_stats
    stats["n_ports"] = len(ports)
    return {
        "ports": ports,
        "source": source,
        "advisory": advisory,
        "cross_check": cross_check,
        "stats": stats,
    }


def _pair_agrees(a: LayoutPort, b: LayoutPort) -> bool:
    """单对端口一致性（_ports_agree 的逐对判据，复用同一组容差常量）。"""
    return _ports_agree([a], [b])
