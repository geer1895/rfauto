"""LC-8 拼板闭式面：板阵列/工艺边/V-cut（V 型槽）/邮票孔（mouse bite）参数
计算 + 面板利用率 + 全局基准标记（fiducial）布局。

规格=研究扩充 round15 §四 LC-8"拼板器+基准标记
（P3/M）"；席D3 任务书口径："panelization 闭式（板阵列间距/工艺边/V-cut 或
邮票孔参数计算+利用率）"。纯闭式几何（零 IO 零求解器），JSON 进出信封
（规则 4；AU-2 信封构造器）。

出处（双源，#118/#300：数值判据 ≥2 独立来源；检索时点 2026-10-03）：

- V 槽元件避让：V-cut 边到元件 ≥0.075 in（=1.905 mm）、连接桥（tab）边
  到元件 ≥0.125 in（=3.175 mm）——VSE《Eight Important PCB Panelization
  Guidelines to Know》原文抓取（2026-10-03 WebFetch 实测）；
- V 槽剩余 web ≈ 板厚 1/3——HopetimePCB V-score 说明页（检索摘要钉值）+
  行业指南普遍口径（检索交叉印证）；V 槽面开口/切深三角闭式为本模块
  导出式（自明几何，见 :func:`vcut_geometry` docstring）；
- 工艺边（传送边）缺省 5 mm——多厂指南普遍缺省（ALLPCB/PCBGogo 检索
  摘要交叉印证）；登记级经验值，随 fab 能力可调；
- 邮票孔缺省（孔径 0.6 mm/5 孔/tab 桥长 5 mm/板间隙 0.5 mm）——行业
  典型值（检索摘要"0.6 mm 常见、5–8 孔、tab 5–8 mm"）；登记级经验值；
- 基准标记：全局 3 点非共线（对角+不对称防反插），铜点 Ø1.0 mm、阻焊
  开窗 ≥2× 点径、点周 keepout ≈ 点径——IPC 系设计指南通行口径（检索
  摘要多源交叉）；登记级经验值，精确条款本执行环境未达原文（如实）。

边界（如实登记）：本面只算**几何**（尺寸/间距/开口/利用率/落点坐标），
不产出 Gerber/钻孔等制造文件（fab_export 面职责）；分板强度/翘曲、
V 槽跨铜影响等工艺可行性不在闭式内（如实不做）。
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "DEFAULT_EDGE_RAIL_MM",
    "TAB_HOLES_DEFAULT",
    "TAB_HOLE_DIA_MM",
    "TAB_LEN_MM_DEFAULT",
    "TAB_MIN_COMPONENT_CLEARANCE_MM",
    "VSCORE_DEFAULT_ANGLE_DEG",
    "VSCORE_MIN_COMPONENT_CLEARANCE_MM",
    "VSCORE_WEB_RATIO",
    "fiducial_layout",
    "panelize",
    "vcut_geometry",
]

#: 工艺边（传送 rail）缺省宽度 [mm]（行业典型值，登记级）。
DEFAULT_EDGE_RAIL_MM = 5.0

#: V 槽剩余 web 占板厚比缺省（≈1/3，HopetimePCB+行业指南）。
VSCORE_WEB_RATIO = 1.0 / 3.0

#: V 槽槽角缺省 [deg]（30/45/60 常见；缺省 30，登记级经验值）。
VSCORE_DEFAULT_ANGLE_DEG = 30.0

#: V-cut 边到元件最小避让 [mm]（=0.075 in，VSE 原文）。
VSCORE_MIN_COMPONENT_CLEARANCE_MM = 0.075 * 25.4

#: 邮票孔/连接桥边到元件最小避让 [mm]（=0.125 in，VSE 原文）。
TAB_MIN_COMPONENT_CLEARANCE_MM = 0.125 * 25.4

#: 邮票孔孔径缺省 [mm]（行业典型值，登记级）。
TAB_HOLE_DIA_MM = 0.6

#: 每 tab 桥邮票孔数缺省（行业典型值 5–8，登记级）。
TAB_HOLES_DEFAULT = 5

#: tab 桥长（沿板边占位）缺省 [mm]（行业典型值 5–8，登记级）。
TAB_LEN_MM_DEFAULT = 5.0

_IN_TO_MM = 25.4


def _pos_f(value: Any, name: str) -> float:
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {value!r}")
    return v


def _nonneg_f(value: Any, name: str) -> float:
    v = float(value)
    if not math.isfinite(v) or v < 0.0:
        raise ValueError(f"{name} 必须为非负有限数，实际 {value!r}")
    return v


def vcut_geometry(
    board_thickness_mm: Any,
    *,
    web_ratio: float = VSCORE_WEB_RATIO,
    angle_deg: float = VSCORE_DEFAULT_ANGLE_DEG,
) -> dict[str, float]:
    """V 槽几何闭式：剩余 web/单侧切深/面开口宽。

    几何（自明三角关系，导出式）：板厚 ``t``，上下对称 V 槽各切深
    ``d``，剩余 web ``w = t − 2d``；槽含角 ``θ`` 时面开口宽
    ``s = 2·d·tan(θ/2)``。

    Args:
        board_thickness_mm: 板厚 [mm]（>0）。
        web_ratio: 剩余 web/板厚比（缺省 1/3，出处见模块 docstring）。
        angle_deg: 槽含角 [deg]（0<θ<180）。

    Returns:
        dict：web_mm / depth_per_side_mm / surface_opening_mm /
        web_ratio / angle_deg。
    """
    t = _pos_f(board_thickness_mm, "board_thickness_mm")
    r = _nonneg_f(web_ratio, "web_ratio")
    if r >= 1.0:
        raise ValueError(f"web_ratio 须 <1，实际 {web_ratio!r}")
    th = math.radians(_pos_f(angle_deg, "angle_deg"))
    if not 0.0 < th < math.pi:
        raise ValueError(f"angle_deg 须 (0,180)，实际 {angle_deg!r}")
    d = t * (1.0 - r) / 2.0
    s = 2.0 * d * math.tan(th / 2.0)
    return {
        "web_mm": t * r,
        "depth_per_side_mm": d,
        "surface_opening_mm": s,
        "web_ratio": r,
        "angle_deg": float(angle_deg),
    }


def fiducial_layout(
    panel_w_mm: Any,
    panel_h_mm: Any,
    *,
    dot_dia_mm: float = 1.0,
    mask_open_mm: float = 3.0,
    inset_mm: float = 3.0,
) -> list[dict[str, float]]:
    """全局基准标记 3 点布局（非共线+不对称防反插）。

    落点（面板坐标，mm）：(inset, inset)、(W−inset, inset)、
    (inset, H−inset)——占三邻角、缺右下角=不对称（防面板反插，行业
    指南口径）；非共线由三点取位保证（inset<H−inset 恒成立）。

    Args:
        panel_w_mm/panel_h_mm: 面板尺寸 [mm]。
        dot_dia_mm: 铜点直径 [mm]（缺省 1.0，登记级经验值）。
        mask_open_mm: 阻焊开窗直径 [mm]（缺省 3.0=2× 点径+余量）。
        inset_mm: 标记中心距面板边 [mm]。
    """
    w = _pos_f(panel_w_mm, "panel_w_mm")
    h = _pos_f(panel_h_mm, "panel_h_mm")
    ins = _nonneg_f(inset_mm, "inset_mm")
    if not 2.0 * ins < min(w, h):
        raise ValueError("inset_mm 过大：2×inset 须小于面板短边")
    pts = [
        (ins, ins),
        (w - ins, ins),
        (ins, h - ins),
    ]
    return [
        {
            "x_mm": round(x, 6),
            "y_mm": round(y, 6),
            "dot_dia_mm": _pos_f(dot_dia_mm, "dot_dia_mm"),
            "mask_open_mm": _pos_f(mask_open_mm, "mask_open_mm"),
        }
        for x, y in pts
    ]


def _rail(value: Any, name: str) -> float:
    return _nonneg_f(value, name)


def panelize(
    board_w_mm: Any,
    board_h_mm: Any,
    *,
    cols: int = 1,
    rows: int = 1,
    separation: str = "vcut",
    edge_rail_mm: Any = DEFAULT_EDGE_RAIL_MM,
    board_gap_mm: Any = 0.0,
    board_thickness_mm: Any = 1.6,
    web_ratio: float = VSCORE_WEB_RATIO,
    vcut_angle_deg: float = VSCORE_DEFAULT_ANGLE_DEG,
    tab_hole_dia_mm: float = TAB_HOLE_DIA_MM,
    tab_holes: int = TAB_HOLES_DEFAULT,
    tab_len_mm: float = TAB_LEN_MM_DEFAULT,
    tabs_per_edge: int = 3,
    fiducials: bool = True,
    fiducial_inset_mm: float = 3.0,
) -> dict[str, Any]:
    """拼板闭式：板阵列 → 面板尺寸/分板规格/利用率/基准标记（信封）。

    几何（X/Y 同构）::

        panel_dim = rail + Σ_{i}(board) + (n−1)·gap + rail

    - ``separation="vcut"``：相邻板共 V 槽线，行/列间距
      ``board_gap_mm`` 缺省 0（V 槽不占额外间距——槽线即共享边界）；
      分板规格含 :func:`vcut_geometry` 三量。
    - ``separation="tab"``：邮票孔/连接桥分板，行/列间距
      ``board_gap_mm`` 为板间铣削通道宽（缺省 0.5 mm 行业典型值，
      显式传参覆盖；本函数不代填缺省 0——tab 面 gap=0 无铣刀通道，
      显式校验拒绝）。
    - 元件避让指导值随分板方式给出（V 槽 1.905 mm/tab 3.175 mm，
      VSE 原文）——只报告要求值，不裁剪用户几何（如实边界）。

    Returns:
        ok 信封：panel（宽高/面积）、n_boards、board_area_mm2、
        utilization（=板面积和/面板面积，0-1）、board_origins（左下角
        网格坐标列表）、separation_spec（分板参数）、clearance_required_
        mm、fiducials（:func:`fiducial_layout` 三点）。参数非法走
        error 信封（errors 列表，逐项诊断）。
    """
    from rfauto.service.envelope import error_envelope, ok_envelope

    errors: list[str] = []
    try:
        bw = _pos_f(board_w_mm, "board_w_mm")
        bh = _pos_f(board_h_mm, "board_h_mm")
    except ValueError as exc:
        errors.append(str(exc))
        bw = bh = 0.0
    if not (isinstance(cols, int) and isinstance(rows, int)) or isinstance(
        cols, bool
    ) or isinstance(rows, bool):
        errors.append(f"cols/rows 必须为整数: {cols!r}/{rows!r}")
        cols = rows = 0
    elif cols < 1 or rows < 1:
        errors.append(f"cols/rows 须 ≥1: {cols!r}/{rows!r}")
        cols = rows = 0
    sep = str(separation).lower()
    if sep not in ("vcut", "tab"):
        errors.append(f"separation 须 'vcut'|'tab'，实际 {separation!r}")
    if isinstance(edge_rail_mm, dict):
        rail = {
            k: _try_rail(edge_rail_mm.get(k, DEFAULT_EDGE_RAIL_MM), k, errors)
            for k in ("left", "right", "top", "bottom")
        }
    else:
        r0 = _try_rail(edge_rail_mm, "edge_rail_mm", errors)
        rail = {"left": r0, "right": r0, "top": r0, "bottom": r0}
    gap = _try_nonneg(board_gap_mm, "board_gap_mm", errors)
    if errors:
        return error_envelope(errors)

    n = cols * rows
    panel_w = rail["left"] + cols * bw + (cols - 1) * gap + rail["right"]
    panel_h = rail["bottom"] + rows * bh + (rows - 1) * gap + rail["top"]

    origins: list[list[float]] = []
    for j in range(rows):
        for i in range(cols):
            origins.append([
                round(rail["left"] + i * (bw + gap), 6),
                round(rail["bottom"] + j * (bh + gap), 6),
            ])

    board_area = bw * bh
    panel_area = panel_w * panel_h
    utilization = n * board_area / panel_area

    spec: dict[str, Any]
    if sep == "vcut":
        try:
            vg = vcut_geometry(
                board_thickness_mm, web_ratio=web_ratio,
                angle_deg=vcut_angle_deg)
        except ValueError as exc:
            return error_envelope(str(exc))
        vcut_xs = [
            round(rail["left"] + i * (bw + gap) - gap / 2.0, 6)
            for i in range(1, cols)
        ]
        vcut_ys = [
            round(rail["bottom"] + j * (bh + gap) - gap / 2.0, 6)
            for j in range(1, rows)
        ]
        spec = {
            "method": "vcut",
            "vcut_lines_x_mm": vcut_xs,
            "vcut_lines_y_mm": vcut_ys,
            **vg,
        }
        clearance = VSCORE_MIN_COMPONENT_CLEARANCE_MM
    else:
        if gap <= 0.0:
            return error_envelope(
                "separation='tab' 要求 board_gap_mm>0（铣削通道）")
        try:
            hd = _pos_f(tab_hole_dia_mm, "tab_hole_dia_mm")
            tl = _pos_f(tab_len_mm, "tab_len_mm")
        except ValueError as exc:
            return error_envelope(str(exc))
        if not (isinstance(tab_holes, int) and not isinstance(
            tab_holes, bool)) or tab_holes < 1:
            return error_envelope(f"tab_holes 须 ≥1 整数: {tab_holes!r}")
        if not (isinstance(tabs_per_edge, int) and not isinstance(
            tabs_per_edge, bool)) or tabs_per_edge < 1:
            return error_envelope(
                f"tabs_per_edge 须 ≥1 整数: {tabs_per_edge!r}")
        holes = _tab_hole_positions(
            bw, bh, rail, cols, rows, gap, tabs_per_edge, tl, tab_holes)
        spec = {
            "method": "tab",
            "boards_gap_mm": gap,
            "tab_len_mm": tl,
            "hole_dia_mm": hd,
            "n_holes_per_tab": tab_holes,
            "tabs_per_edge": tabs_per_edge,
            "hole_centers_mm": holes,
        }
        clearance = TAB_MIN_COMPONENT_CLEARANCE_MM

    fid = fiducial_layout(panel_w, panel_h, inset_mm=fiducial_inset_mm) \
        if fiducials else []

    return ok_envelope(
        panel={"w_mm": panel_w, "h_mm": panel_h, "area_mm2": panel_area},
        n_boards=n,
        board_area_mm2=board_area,
        utilization=utilization,
        board_origins=origins,
        separation_spec=spec,
        clearance_required_mm=clearance,
        fiducials=fid,
    )


def _tab_hole_positions(
    bw: float,
    bh: float,
    rail: dict[str, float],
    cols: int,
    rows: int,
    gap: float,
    tabs_per_edge: int,
    tab_len_mm: float,
    n_holes: int,
) -> list[list[float]]:
    """邮票孔孔心坐标闭式（面板坐标，mm）。

    每条内部缝（竖/横）上、每对相邻板共享边 ``tabs_per_edge`` 个桥
    （沿边等分位，避开板角），桥长 ``tab_len_mm`` 内 ``n_holes`` 个孔
    均布、孔心落在缝中线上（缝 = 两板间隙的几何中线）。
    """
    centers: list[list[float]] = []
    for i in range(1, cols):
        x = rail["left"] + i * bw + (i - 1) * gap + gap / 2.0
        for j in range(rows):
            y0 = rail["bottom"] + j * (bh + gap)
            for k in range(tabs_per_edge):
                yc = y0 + bh * (k + 1) / (tabs_per_edge + 1)
                for m in range(n_holes):
                    yh = yc - tab_len_mm / 2.0 + tab_len_mm * (m + 0.5) / n_holes
                    centers.append([round(x, 6), round(yh, 6)])
    for j in range(1, rows):
        y = rail["bottom"] + j * bh + (j - 1) * gap + gap / 2.0
        for i in range(cols):
            x0 = rail["left"] + i * (bw + gap)
            for k in range(tabs_per_edge):
                xc = x0 + bw * (k + 1) / (tabs_per_edge + 1)
                for m in range(n_holes):
                    xh = xc - tab_len_mm / 2.0 + tab_len_mm * (m + 0.5) / n_holes
                    centers.append([round(xh, 6), round(y, 6)])
    return centers


def _try_rail(value: Any, name: str, errors: list[str]) -> float:
    try:
        return _rail(value, name)
    except ValueError as exc:
        errors.append(str(exc))
        return 0.0


def _try_nonneg(value: Any, name: str, errors: list[str]) -> float:
    try:
        return _nonneg_f(value, name)
    except ValueError as exc:
        errors.append(str(exc))
        return 0.0
