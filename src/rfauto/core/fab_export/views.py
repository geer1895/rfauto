"""参数化多视图几何：主视/俯视/全剖 A-A/局部放大（iris）.

从 dims + standards 生成 2D 轮廓（非测量 STEP），供 ezdxf 布图。
"""

from __future__ import annotations

from dataclasses import dataclass

from .standards import get_flange, get_waveguide


@dataclass
class ViewGeometry:
    name: str  # front | top | section | detail
    loops: list[tuple[str, list[tuple[float, float]]]]
    circles: list[tuple[str, tuple[float, float], float]]
    texts: list[tuple[str, float, float]]


def rect(x: float, y: float, w: float, h: float) -> list[tuple[float, float]]:
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _get(dims_values: dict[str, float], *names: str, default: float) -> float:
    for n in names:
        if n in dims_values:
            return float(dims_values[n])
        for k, v in dims_values.items():
            if k.lower() == n.lower():
                return float(v)
    return default


def build_wr90_views(
    dims_values: dict[str, float],
    *,
    wg_name: str = "WR-90",
    flange_name: str = "FBP100",
    origin: tuple[float, float] = (30.0, 30.0),
) -> list[ViewGeometry]:
    """金样族：直波导+法兰 的四视图轮廓."""
    wg = get_waveguide(wg_name)
    fl = get_flange(flange_name)
    L = _get(dims_values, "L", "length", default=60.0)
    a = _get(dims_values, "a", default=wg.a)
    b = _get(dims_values, "b", default=wg.b)
    wall = _get(dims_values, "wall", "t_wall", default=wg.t)
    A, B = a + 2 * wall, b + 2 * wall
    ox, oy = origin

    views: list[ViewGeometry] = []

    # 主视图：法兰正视（外廓+内腔+螺栓孔）
    fw, fh = fl.outer, fl.outer
    circles: list[tuple[str, tuple[float, float], float]] = []
    dx = fl.bolt_pcd_x / 2
    dy = fl.bolt_pcd_y / 2
    for sx in (-1, 1):
        for sy in (-1, 1):
            circles.append(("HOLE", (ox + fw / 2 + sx * dx, oy + fh / 2 + sy * dy), fl.bolt_dia / 2))
    # 销孔
    for sx in (-1, 1):
        circles.append(("HOLE", (ox + fw / 2 + sx * (fl.bolt_pcd_x / 2 - 2), oy + fh / 2), fl.pin_dia / 2))
    views.append(
        ViewGeometry(
            "front",
            [
                ("OUT", rect(ox, oy, fw, fh)),
                ("POCKET", rect(ox + (fw - a) / 2, oy + (fh - b) / 2, a, b)),
            ],
            circles,
            [("主视", ox + fw / 2 - 8, oy + fh + 8)],
        )
    )

    # 俯视图：长度方向外廓 + 内腔
    ox2, oy2 = ox + fw + 40, oy
    views.append(
        ViewGeometry(
            "top",
            [
                ("OUT", rect(ox2, oy2, L, A)),
                ("POCKET", rect(ox2, oy2 + (A - b) / 2, L, b)),
            ],
            [],
            [("俯视", ox2 + L / 2 - 8, oy2 + A + 8)],
        )
    )

    # 全剖 A-A：沿长度，显示腔高 b 与壁厚（审查项 R10 修复：原型外廓误用
    # 外宽 A、内腔用 `a*0+(A-2·wall)`=a，与"腔高"标注矛盾——正确为外高 B
    # 与腔高 b；原 `a*0` 死算术一并清理）
    ox3, oy3 = ox, oy - 60
    views.append(
        ViewGeometry(
            "section",
            [
                ("OUT", rect(ox3, oy3, L, B)),
                ("POCKET", rect(ox3, oy3 + wall, L - 2 * wall, b)),
            ],
            [],
            [("A-A 全剖", ox3 + 10, oy3 + B + 8)],
        )
    )

    # 局部放大：iris（若无 iris 用内腔一角）
    iris_w = _get(dims_values, "iris_w", "w_iris", default=4.0)
    iris_t = _get(dims_values, "iris_t", "t_iris", default=1.2)
    ox4, oy4 = ox + fw + 40, oy - 60
    views.append(
        ViewGeometry(
            "detail",
            [
                ("OUT", rect(ox4, oy4, iris_t + 6, iris_w + 6)),
                ("POCKET", rect(ox4 + 3, oy4 + 3, iris_t, iris_w)),
            ],
            [],
            [(f"放大 iris w={iris_w:g} t={iris_t:g}", ox4, oy4 + iris_w + 10)],
        )
    )
    return views


def flange_hole_table(flange_name: str = "FBP100") -> list[dict]:
    """法兰孔系表（给图纸/检验）."""
    fl = get_flange(flange_name)
    rows = []
    dx, dy = fl.bolt_pcd_x / 2, fl.bolt_pcd_y / 2
    for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (1, 1), (-1, 1)], 1):
        rows.append({
            "id": f"B{i}",
            "type": "bolt",
            "dia": fl.bolt_dia,
            "x": sx * dx,
            "y": sy * dy,
        })
    for i, sx in enumerate([-1, 1], 1):
        rows.append({
            "id": f"P{i}",
            "type": "pin",
            "dia": fl.pin_dia,
            "x": sx * (fl.bolt_pcd_x / 2 - 2),
            "y": 0.0,
            "fit": "H7",
        })
    return rows
