"""B6 stage-2 深化：KiCad 板级事实 → CSXCAD 几何代码块（全要素渲染）。

输入 service.kicad_em_service.board_facts_from_extract 的 facts dict
（全 mm），输出可嵌入 openems_templates 渲染脚本 body 的 Python 代码
文本（米）。渲染脚本作用域约定（render_script 头部已定义）：CSX
（ContinuousStructure）、sub（基板 Material 属性）、H_SUB（基板厚度，
米）。代码块插在 substrate_block 之后、FDTD.Run 之前（_cpw_lines 尾部）。

几何映射：板坐标 mm → 域坐标 m **恒等平移**（demo 板 0..60×0..30mm 落
在 cpw 模板 ±60mm 方形域内）。要素（0cb⑤ pad/via 全要素）：
- F.Cu GND 填充外轮廓 → b6_gnd.AddPolygon(norm_dir="z", elevation=H_SUB)；
- 填充孔洞 → sub.AddPolygon 同面更高 priority 多边形切除（CSXCAD
  多边形原语不支持孔洞，用 priority 覆盖语义刻除金属）；
- B.Cu GND 填充 → 同法 elevation=0.0（域底 PEC 边界面，模板口径
  "地面=z-min PEC" 即 B.Cu 平面位置）；
- 过孔 → AddCylindricalShell（pad⌀/drill → 桶壁：z 0..H_SUB；CSXCAD
  shell 口径 radius=**中径** (r_pad+r_drill)/2、shell_width=壁厚
  r_pad−r_drill，壁占 radius ± shell_width/2，外缘恰=pad 半径）；
- 焊盘 → AddBox（z=H_SUB 零厚面）；主线折线逐段 AddBox（轴对齐段）
  或 AddPolygon（斜段矩形，法向偏置 ±w/2）。

priority 口径：B6_PRIORITY_RF=12 > B6_PRIORITY_CUT=11 > 模板既有 10 >
B6_PRIORITY_GND=5。板级实测走廊切除（11）刻得穿模板名义地（10）——
叠加场景下 RF 走廊仍是缝隙；RF 金属（12）盖过切除——走廊内 RF 保真；
板级地（5）低于名义地——共存区名义地主导（同为地金属，语义无冲突）。

叠加语义（本项冻结口径）：b6_board 块是**审计/验证叠加层**——cpw
模板的名义中心带/两侧地/CPWPort 照常渲染，端口激励不动；真机共仿真
需先解决名义地与板级地的替换策略（followUp，#25 B6 autotune 真跑腿）。

确定性纪律：本模块只做 mm→m 换算与代码文本拼装，所有几何数值出自
KiCad 提取事实（facts），无任何物理数字臆造（铁律 7）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: RF 金属（走线/焊盘/信号过孔）priority：盖过孔洞切除
B6_PRIORITY_RF = 12
#: 孔洞切除（基板材料同面多边形）priority：刻穿模板名义地(10)
B6_PRIORITY_CUT = 11
#: 板级地金属 priority：低于模板既有 10（共存区名义地主导）
B6_PRIORITY_GND = 5


def _m(x_mm: Any) -> str:
    """mm 数值 → 米字面量（repr 保浮点往返）。"""
    return repr(float(x_mm) * 1e-3)


def _polygon_args(pts_mm: list[list[float]]) -> str:
    """闭合多边形点列 → AddPolygon 的 (xs, ys) 参数字面量（米）。"""
    xs = "[" + ", ".join(_m(p[0]) for p in pts_mm) + "]"
    ys = "[" + ", ".join(_m(p[1]) for p in pts_mm) + "]"
    return f"({xs}, {ys})"


def _trace_rect(pts: list[list[float]], width_mm: float) -> list[list[float]]:
    """折线段 → 矩形四角（法向 ±w/2；仅支持轴对齐段，斜段报错）。

    轴对齐判定：dx==0 或 dy==0（KiCad 走线通常轴对齐；demo 板为水平段）。
    """
    (x1, y1), (x2, y2) = pts[0], pts[1]
    if not (x1 == x2 or y1 == y2):
        raise ValueError(
            f"折线斜段暂不支持矩形化（段 {pts[0]}→{pts[1]}）；"
            "斜段走线需 AddPolygon 法向偏置，留 followUp")
    half = float(width_mm) / 2.0
    if y1 == y2:
        lo_y, hi_y = y1 - half, y1 + half
        return [[min(x1, x2), lo_y], [max(x1, x2), lo_y],
                [max(x1, x2), hi_y], [min(x1, x2), hi_y]]
    lo_x, hi_x = x1 - half, x1 + half
    return [[lo_x, min(y1, y2)], [hi_x, min(y1, y2)],
            [hi_x, max(y1, y2)], [lo_x, max(y1, y2)]]


def board_geometry_lines(facts: Mapping[str, Any]) -> str:
    """facts（board_facts_from_extract 产物）→ CSX 几何代码块文本。

    Raises ValueError：facts 缺关键事实（无 F.Cu GND 填充纹理、无主线
    折线、孔洞多边形顶点 <3、过孔 pad⌀ ≤ drill）。
    """
    fill_f = list(facts.get("gnd_fill_f") or [])
    if not fill_f:
        raise ValueError(
            "facts.gnd_fill_f 为空（无 F.Cu GND 填充纹理）：板级地无法渲染，"
            "请确认板已填充（build_demo_cpwg_pcb(fill_zones=True) / KiCad GUI）")
    trace = facts.get("trace")
    if not isinstance(trace, Mapping) or not trace.get("points_mm"):
        raise ValueError("facts.trace 缺失（主线折线无来源）")
    ground_nets = tuple(facts.get("ground_nets") or ("GND",))
    rf_net = str(facts.get("net", ""))

    lines: list[str] = [
        "# ── B6 stage-2 板级事实叠加（KiCad extract→EM；板坐标 mm→m，"
        "恒等映射）──",
        "b6_gnd = CSX.AddMetal(\"b6_gnd\")",
    ]
    # F.Cu 填充外轮廓 + 孔洞切除
    n_holes_f = 0
    for pi, poly in enumerate(fill_f):
        pm = poly if isinstance(poly, Mapping) else {}
        outer = list(pm.get("outer_mm") or [])
        if len(outer) < 3:
            raise ValueError(f"facts.gnd_fill_f[{pi}].outer_mm 顶点 <3")
        lines.append(
            f"b6_gnd.AddPolygon({_polygon_args(outer)}, norm_dir=\"z\", "
            f"elevation=H_SUB, priority={B6_PRIORITY_GND})"
            f"  # F.Cu GND fill poly {pi}")
        for hi, hole in enumerate(pm.get("holes_mm") or []):
            if len(hole) < 3:
                raise ValueError(
                    f"facts.gnd_fill_f[{pi}].holes_mm[{hi}] 顶点 <3")
            lines.append(
                f"sub.AddPolygon({_polygon_args(list(hole))}, "
                f"norm_dir=\"z\", elevation=H_SUB, "
                f"priority={B6_PRIORITY_CUT})"
                f"  # F.Cu fill hole {pi}.{hi}（基板同面切除）")
            n_holes_f += 1
    # B.Cu 填充（域底 PEC 面）
    for pi, poly in enumerate(facts.get("gnd_fill_b") or []):
        pm = poly if isinstance(poly, Mapping) else {}
        outer = list(pm.get("outer_mm") or [])
        if len(outer) < 3:
            continue  # B.Cu 非必需事实：异常轮廓跳过不阻塞
        lines.append(
            f"b6_gnd.AddPolygon({_polygon_args(outer)}, norm_dir=\"z\", "
            f"elevation=0.0, priority={B6_PRIORITY_GND})"
            f"  # B.Cu GND fill poly {pi}")
    # 过孔桶壁（GND 过孔归 b6_via，信号过孔归 b6_rf_via）
    via_lines: list[str] = []
    rf_via_lines: list[str] = []
    for vi, via in enumerate(facts.get("vias") or []):
        vm = via if isinstance(via, Mapping) else {}
        pad_d = float(vm.get("pad_diameter_mm") or 0.0)
        drill = float(vm.get("drill_mm") or 0.0)
        if pad_d <= 0.0:
            continue
        if pad_d <= drill:
            raise ValueError(
                f"facts.vias[{vi}] pad⌀({pad_d}) ≤ drill({drill})：桶壁宽非正")
        is_gnd = str(vm.get("net", "")) in ground_nets
        prop = "b6_via" if is_gnd else "b6_rf_via"
        # CSXCAD CylindricalShell 口径（绑定实测：radius=1.0/shell_width=0.2
        # → 包围盒 ±1.1）：radius 是**桶壁中径**、壁占 radius ± shell_width/2。
        # 桶壁外缘=pad 半径、内缘=钻孔半径 → 中径=(r_pad+r_drill)/2、
        # 壁厚=r_pad−r_drill。
        r_pad, r_drill = pad_d / 2.0, drill / 2.0
        radius = (r_pad + r_drill) / 2.0
        shell = r_pad - r_drill
        x, y = _m(vm.get("x_mm")), _m(vm.get("y_mm"))
        line = (
            f"{prop}.AddCylindricalShell([{x}, {y}, 0.0], "
            f"[{x}, {y}, H_SUB], {_m(radius)}, {_m(shell)}, "
            f"priority={B6_PRIORITY_GND if is_gnd else B6_PRIORITY_RF})"
            f"  # via {vm.get('net', '')} @({vm.get('x_mm')},"
            f"{vm.get('y_mm')})mm")
        (via_lines if is_gnd else rf_via_lines).append(line)
    if via_lines:
        lines.append("b6_via = CSX.AddMetal(\"b6_via\")")
        lines.extend(via_lines)
    if rf_via_lines:
        lines.append("b6_rf_via = CSX.AddMetal(\"b6_rf_via\")")
        lines.extend(rf_via_lines)
    # 焊盘（GND 焊盘归 b6_gnd，信号焊盘归 b6_rf）
    lines.append("b6_rf = CSX.AddMetal(\"b6_rf\")")
    for pad in facts.get("pads") or []:
        pm_ = pad if isinstance(pad, Mapping) else {}
        w = float(pm_.get("w_mm") or 0.0)
        h = float(pm_.get("h_mm") or 0.0)
        if w <= 0.0 or h <= 0.0:
            continue
        x, y = float(pm_.get("x_mm") or 0.0), float(pm_.get("y_mm") or 0.0)
        is_rf = str(pm_.get("net", "")) == rf_net
        prop = "b6_rf" if is_rf else "b6_gnd"
        prio = B6_PRIORITY_RF if is_rf else B6_PRIORITY_GND
        lines.append(
            f"{prop}.AddBox([{_m(x - w / 2)}, {_m(y - h / 2)}, H_SUB], "
            f"[{_m(x + w / 2)}, {_m(y + h / 2)}, H_SUB], "
            f"priority={prio})"
            f"  # pad {pm_.get('number', '')} {pm_.get('net', '')} "
            f"@({x},{y}) {w}x{h}mm")
    # 主线折线逐段（轴对齐矩形）
    width = float(trace.get("width_mm") or 0.0)
    if width <= 0.0:
        raise ValueError("facts.trace.width_mm 非正")
    pts_mm = list(trace.get("points_mm") or [])
    for si in range(len(pts_mm) - 1):
        seg = [list(pts_mm[si]), list(pts_mm[si + 1])]
        rect = _trace_rect(seg, width)
        lines.append(
            f"b6_rf.AddPolygon({_polygon_args(rect)}, norm_dir=\"z\", "
            f"elevation=H_SUB, priority={B6_PRIORITY_RF})"
            f"  # trace {rf_net} seg {si}")
    lines.append(f"# B6 facts: net={rf_net} F.Cu fill polys={len(fill_f)} "
                 f"holes={n_holes_f}")
    return "\n".join(lines) + "\n"
