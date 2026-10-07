"""CAM G 代码/刀路报告写盘（渲染在 core.gcode，写盘在此）."""

from __future__ import annotations

from pathlib import Path

from rfauto.core.fab_export.gcode import GcodeProgram, build_wr90_program, render_cam_report


def write_gcode(path: str | Path, program: GcodeProgram | None = None) -> Path:
    prog = program or build_wr90_program()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(prog.render(), encoding="utf-8")
    return p


def write_cam_report(path: str | Path, program: GcodeProgram) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_cam_report(program), encoding="utf-8")
    return p
