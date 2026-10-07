"""覆铜板复合层 DXF 写/读（ezdxf 惰性 import，重依赖不出本层）.

图层约定（源仓口径，逐字固定）：``M1`` 顶侧金属／``M2`` 底侧金属／
``sub`` 中间介质（含外形）／``patch`` 通孔（完整圆，不简化）。
ACI 颜色沿用源仓 build_laminates（M1=30/M2=140/sub=5/patch=1）。

读回端把逐层实体折成 (线段, 圆) 两类几何，供真值对照
（dxf_truth.compare_dxf_to_truth）与审计消费。
ARC 圆弧弦段折分（ge6 followUp F11 实现）：弧→N 段弦离散化（最大弦差
sagitta ≤ ``arc_sagitta_tol_mm`` 自适应段数）进 segments；圆心/半径不再
以整圆记入 circles——非整圆过渡弧/圆角曾以整圆冒充孔位产生幻影假差
（ge5 审查 F11 如实改口的几何缺口就此闭合）。
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rfauto.core.fab_export.composite_layer import COMPOSITE_LAYERS, CompositeObject, Point

#: DXF ACI 颜色（源仓 build_laminates 同款）
COMPOSITE_ACI = {"M1": 30, "M2": 140, "sub": 5, "patch": 1}

#: ARC 弦段折分缺省最大弦差（mm；10µm——对照容差 DEFAULT_TOL_MM=1µm 的
#: 10 倍，弦差对孔位/轮廓对照不可见量级）。
DEFAULT_ARC_SAGITTA_TOL_MM = 0.01


def _require_ezdxf():
    try:
        import ezdxf  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("复合层 DXF 需要 ezdxf：pip install rfauto[fab]") from e
    return ezdxf


def write_composite_dxf(
    layers: dict[str, Sequence[CompositeObject]],
    out_path: str | Path,
) -> Path:
    """四图层复合层 DXF 写出.

    layers: {"M1": [...], "M2": [...], "sub": [...], "patch": [...]}，
    值为 CompositeObject 列表（同侧多片=多对象全保留，合并是图层语义）。
    对象的 outlines 写闭合 LWPOLYLINE，circles 写完整 CIRCLE（通孔
    不简化——源仓 §2.10：圆孔漏写即缺陷）。
    """
    ezdxf = _require_ezdxf()
    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    for name in COMPOSITE_LAYERS:
        if name not in doc.layers:
            doc.layers.add(name, color=COMPOSITE_ACI.get(name, 7))

    for layer in COMPOSITE_LAYERS:
        for obj in layers.get(layer) or ():
            for pts in obj.outlines:
                if len(pts) < 3:
                    continue
                clean = list(pts)
                if clean[0] == clean[-1]:
                    clean = clean[:-1]  # 首尾重复点交给 close=True
                if len(clean) < 3:
                    continue
                msp.add_lwpolyline(clean, close=True, dxfattribs={"layer": layer})
            for center, radius in obj.circles:
                msp.add_circle(center, radius, dxfattribs={"layer": layer})

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(out))
    return out


def read_composite_dxf(
    path: str | Path,
    *,
    expand_insert: bool = True,
    layers: Sequence[str] | None = None,
    arc_sagitta_tol_mm: float = DEFAULT_ARC_SAGITTA_TOL_MM,
) -> dict[str, dict[str, list[Any]]]:
    """DXF 读回 → {layer: {"segments": [((x,y),(x,y)), ...], "circles": [((x,y),r), ...]}}.

    expand_insert=True 时块引用（INSERT）按虚拟实体展开（真值对照
    归一之一：手绘图常把轮廓装进块，不展开则逐实体对照全漏）。
    LWPOLYLINE/POLYLINE 折成相邻点对线段；CIRCLE 记圆（圆孔识别以
    CIRCLE 实体在档，源仓 §2.10）。
    ARC 圆弧弦段折分（ge6 followUp F11）：弧→N 段弦进 segments，段数按
    最大弦差自适应（单弦 sagitta = R(1−cos(φ/2)) ≤ ``arc_sagitta_tol_mm``
    → 单弦最大圆心角 φ_max = 2·arccos(1 − tol/R)，N = ⌈θ/φ_max⌉）；弦端点
    全落弧上、链首尾相接（ezdxf 角度制 CCW start→end 语义）。圆心/半径
    **不**进 circles——过渡弧/圆角不是孔，整圆记账曾产生幻影孔位假差
    （ge5 审查 F11）；真孔以 CIRCLE 实体在档为准。
    """
    ezdxf = _require_ezdxf()
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    want = set(layers or COMPOSITE_LAYERS)
    out: dict[str, dict[str, list[Any]]] = {
        name: {"segments": [], "circles": []} for name in want
    }

    def _ingest(e) -> None:
        layer = e.dxf.layer
        if layer not in out:
            return
        t = e.dxftype()
        if t == "LINE":
            p = (float(e.dxf.start.x), float(e.dxf.start.y))
            q = (float(e.dxf.end.x), float(e.dxf.end.y))
            out[layer]["segments"].append((p, q))
        elif t == "LWPOLYLINE":
            pts = [(float(p[0]), float(p[1])) for p in e.get_points("xy")]
            _polyline_to_segments(out[layer]["segments"], pts, closed=e.closed)
        elif t == "POLYLINE":
            pts = [
                (float(v.dxf.location.x), float(v.dxf.location.y))
                for v in e.vertices
            ]
            _polyline_to_segments(out[layer]["segments"], pts, closed=e.is_closed)
        elif t == "CIRCLE":
            c = e.dxf.center
            out[layer]["circles"].append(((float(c.x), float(c.y)), float(e.dxf.radius)))
        elif t == "ARC":
            # 圆弧段（F11 折分实现）：弦段进 segments；不记 circles（幻影
            # 孔位假差根除）。退化输入（R≤0/零跨度/容差≤0）→ 零几何（不
            # 臆造），由调用面人工核对原图。
            out[layer]["segments"].extend(_arc_chord_segments(
                (float(e.dxf.center.x), float(e.dxf.center.y)),
                float(e.dxf.radius),
                float(e.dxf.start_angle), float(e.dxf.end_angle),
                arc_sagitta_tol_mm,
            ))

    for e in msp:
        if e.dxftype() == "INSERT" and expand_insert:
            for virt in e.virtual_entities():
                _ingest(virt)
        else:
            _ingest(e)
    return out


def _arc_chord_segments(
    center: tuple[float, float],
    radius: float,
    start_deg: float,
    end_deg: float,
    sagitta_tol: float,
) -> list[tuple[Point, Point]]:
    """ARC → N 段弦离散化（最大弦差 sagitta ≤ ``sagitta_tol`` 自适应段数）.

    单弦 sagitta = R(1−cos(φ/2)) ≤ tol → 单弦最大圆心角
    φ_max = 2·arccos(1 − tol/R)；N = max(1, ⌈θ/φ_max⌉)。弦端点全部落在
    圆弧上，链首尾相接；角度制 CCW start→end（DXF ARC 语义，end<start 自
    动过 360° 绕回）。退化输入（R≤0 / 容差≤0 / 零跨度）→ 空列表（不臆造
    几何）。纯函数，零 ezdxf 依赖（直写 DXF 的测试同款可复算）。
    """
    r = float(radius)
    tol = float(sagitta_tol)
    span_deg = (float(end_deg) - float(start_deg)) % 360.0
    if r <= 0.0 or tol <= 0.0 or span_deg == 0.0:
        return []
    cx, cy = float(center[0]), float(center[1])
    theta = math.radians(span_deg)
    x = max(-1.0, min(1.0, 1.0 - tol / r))
    phi_max = min(2.0 * math.acos(x), 2.0 * math.pi)
    n = max(1, math.ceil(theta / phi_max)) if phi_max > 0.0 else 1
    pts: list[Point] = []
    a0 = math.radians(float(start_deg))
    for i in range(n + 1):
        ang = a0 + theta * i / n
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return [(pair[0], pair[1])
            for pair in itertools.pairwise(pts)]


def _polyline_to_segments(
    sink: list[tuple[Point, Point]],
    pts: Sequence[Point],
    *,
    closed: bool,
) -> None:
    n = len(pts)
    if n < 2:
        return
    last = n if closed else n - 1
    for i in range(last):
        sink.append((pts[i], pts[(i + 1) % n]))
