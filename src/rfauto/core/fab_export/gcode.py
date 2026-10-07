"""2.5D CAM 刀路与 ISO G 代码内核（纯字符串渲染，写盘在 adapters.cam_io）.

安全假设：外轮廓+内腔+孔；刀具直径由参数给定；不做刀具库/碰撞检查（CAM 预检）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

Point = tuple[float, float]


@dataclass
class ToolSpec:
    number: int = 1
    dia: float = 6.0
    kind: str = "endmill"  # endmill | drill
    flute_len: float = 20.0


@dataclass
class ToolpathOp:
    name: str
    kind: str  # contour | pocket | drill
    points: list[Point] = field(default_factory=list)
    depth: float = 1.0
    stepdown: float = 0.5
    feed_xy: float = 400.0
    feed_z: float = 100.0
    safe_z: float = 5.0
    retract_z: float = 2.0
    tool: ToolSpec = field(default_factory=ToolSpec)


@dataclass
class GcodeProgram:
    ops: list[ToolpathOp] = field(default_factory=list)
    header: list[str] = field(default_factory=lambda: ["%", "G21", "G90", "G17", "G94"])
    footer: list[str] = field(default_factory=lambda: ["M05", "G0 Z50.", "M30", "%"])

    def render(self) -> str:
        lines = list(self.header)
        for op in self.ops:
            lines.append(f"(OP {op.name} {op.kind})")
            lines.append(f"T{op.tool.number} M06")
            lines.append("S3000 M03")
            if op.kind == "drill" and op.points:
                for x, y in op.points:
                    lines.append(f"G0 X{x:.4f} Y{y:.4f}")
                    lines.append(f"G0 Z{op.retract_z:.4f}")
                    lines.append(f"G1 Z{-abs(op.depth):.4f} F{op.feed_z:.1f}")
                    lines.append(f"G0 Z{op.safe_z:.4f}")
            else:
                if not op.points:
                    continue
                # 分层环绕（步进必须严格下降，防死循环）
                z = 0.0
                pts = [*op.points, op.points[0]]
                depth_abs = abs(op.depth)
                step = abs(op.stepdown) or max(depth_abs, 1.0)
                guard = 0
                while depth_abs > 0 and z > -depth_abs + 1e-9 and guard < 1000:
                    guard += 1
                    z_next = -depth_abs if z - step <= -depth_abs else z - step
                    if z_next >= z:  # 兜底：无法下降则停
                        break
                    lines.append(f"G0 Z{op.safe_z:.4f}")
                    x0, y0 = pts[0]
                    lines.append(f"G0 X{x0:.4f} Y{y0:.4f}")
                    lines.append(f"G1 Z{z_next:.4f} F{op.feed_z:.1f}")
                    for x, y in pts[1:]:
                        lines.append(f"G1 X{x:.4f} Y{y:.4f} F{op.feed_xy:.1f}")
                    z = z_next
            lines.append(f"G0 Z{op.safe_z:.4f}")
        lines += self.footer
        return "\n".join(lines) + "\n"


def contour_op(name: str, points: Sequence[Point], depth: float, tool: ToolSpec | None = None) -> ToolpathOp:
    return ToolpathOp(
        name=name,
        kind="contour",
        points=list(points),
        depth=depth,
        tool=tool or ToolSpec(number=1, dia=6.0),
    )


def pocket_op(name: str, points: Sequence[Point], depth: float, tool: ToolSpec | None = None) -> ToolpathOp:
    return ToolpathOp(name=name, kind="pocket", points=list(points), depth=depth, tool=tool or ToolSpec(number=2, dia=4.0))


def drill_op(name: str, points: Sequence[Point], depth: float, tool: ToolSpec | None = None) -> ToolpathOp:
    return ToolpathOp(
        name=name,
        kind="drill",
        points=list(points),
        depth=depth,
        tool=tool or ToolSpec(number=3, dia=3.2, kind="drill"),
    )


def build_wr90_program(
    *,
    length: float = 60.0,
    a: float = 22.86,
    wall: float = 1.27,
    flange_outer: float = 30.0,
    bolt_dia: float = 3.2,
    bolt_pcd: float = 25.4,
) -> GcodeProgram:
    """金样：法兰面外轮廓 + 内腔 + 螺栓孔."""
    A = a + 2 * wall
    outer = [(0.0, 0.0), (flange_outer, 0.0), (flange_outer, flange_outer), (0.0, flange_outer)]
    # 内腔矩形（中心对齐法兰）
    x0 = (flange_outer - a) / 2
    y0 = (flange_outer - A) / 2 if flange_outer > A else 0.0
    pocket = [(x0, y0), (x0 + a, y0), (x0 + a, y0 + min(A, flange_outer - 2)), (x0, y0 + min(A, flange_outer - 2))]
    d = bolt_pcd / 2
    c = flange_outer / 2
    holes = [(c - d, c - d), (c + d, c - d), (c + d, c + d), (c - d, c + d)]
    prog = GcodeProgram()
    prog.ops = [
        contour_op("flange_outer", outer, depth=6.0, tool=ToolSpec(1, 6.0)),
        pocket_op("waveguide_cavity", pocket, depth=min(length, 20.0), tool=ToolSpec(2, 4.0)),
        drill_op("bolt_holes", holes, depth=6.5, tool=ToolSpec(3, bolt_dia, kind="drill")),
    ]
    return prog


def render_cam_report(program: GcodeProgram) -> str:
    """CAM 刀路报告 Markdown 文本（写盘在 adapters.cam_io.write_cam_report）."""
    lines = ["# CAM 刀路报告", "", "| op | kind | points | depth | tool |", "|----|------|--------|-------|------|"]
    for op in program.ops:
        lines.append(f"| {op.name} | {op.kind} | {len(op.points)} | {op.depth:g} | T{op.tool.number} Ø{op.tool.dia:g} |")
    lines += [
        "",
        "## 预检清单",
        "- [ ] 材料毛坯与装夹（基准 A 法兰面）",
        "- [ ] 刀具直径与编程一致",
        "- [ ] 深腔分层/排屑",
        "- [ ] 首件单段试切",
        "- [ ] 关键尺寸按 critical_chars 检验",
    ]
    return "\n".join(lines) + "\n"
