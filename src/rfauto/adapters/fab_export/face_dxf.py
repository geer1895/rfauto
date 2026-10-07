"""2.5D 面轮廓 DXF（闭合 LWPOLYLINE，图层约定；ezdxf 惰性 import）."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

Point = tuple[float, float]

LAYER_OUT = "OUT"
LAYER_POCKET = "POCKET"
LAYER_HOLE = "HOLE"
LAYER_ENGRAVE = "ENGRAVE"
LAYER_CENTER = "CENTER"
LAYER_DIM = "DIM"
LAYER_TEXT = "TEXT"

FAB_LAYERS = (LAYER_OUT, LAYER_POCKET, LAYER_HOLE, LAYER_ENGRAVE, LAYER_CENTER, LAYER_DIM, LAYER_TEXT)


def write_face_dxf(
    out_path: str | Path,
    loops: Sequence[tuple[str, Sequence[Point]]],
    *,
    circles: Sequence[tuple[str, Point, float]] | None = None,
    closed: bool = True,
) -> Path:
    """写出加工面 DXF.

    loops: [(layer, [(x,y), ...]), ...]  建议 OUT/POCKET
    circles: [(layer, (cx,cy), radius), ...]  建议 HOLE
    """
    try:
        import ezdxf  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("face_dxf 需要 ezdxf：pip install rfauto[fab]") from e

    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    for name in FAB_LAYERS:
        if name not in doc.layers:
            doc.layers.add(name, color=_aci(name))

    for layer, pts_in in loops:
        pts = list(pts_in)
        if len(pts) < 2:
            continue
        if closed and pts[0] == pts[-1]:
            # 首尾重复点交给 close=True（审查项 R5：原型的先 append 再裁
            # 是无效往返，直接去重）
            pts = pts[:-1]
        msp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer})

    for layer, center, radius in circles or ():
        msp.add_circle(center, radius, dxfattribs={"layer": layer})

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(out))
    return out


def _aci(layer: str) -> int:
    return {
        LAYER_OUT: 7,
        LAYER_POCKET: 2,
        LAYER_HOLE: 1,
        LAYER_ENGRAVE: 4,
        LAYER_CENTER: 1,
        LAYER_DIM: 3,
        LAYER_TEXT: 7,
    }.get(layer, 7)


def rect_loop(x: float, y: float, w: float, h: float) -> list[Point]:
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def wr90_outer_loop(length: float, *, a: float = 22.86, b: float = 10.16, wall: float = 1.27) -> list[Point]:
    """WR-90 外廓矩形：宽 A=a+2t，长=length."""
    A = a + 2 * wall
    return rect_loop(0, 0, A, length)


def wr90_inner_loop(length: float, *, a: float = 22.86, b: float = 10.16) -> list[Point]:
    return rect_loop((25.4 - a) / 2, 0, a, length)
