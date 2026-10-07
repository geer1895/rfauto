"""PCB 制造交付面 service 薄壳（W1-A 孤儿接线单元1，2026-10-05；规则 4）。

core/gerber_export.export_gerber_x2 的层序适配（cli→service→core，分层
契约 import-linter 口径）：信封形态由 core 契约给出（ok/pcb/out_dir/
files/job_file/drill_files/x2_attributes/missing_x2/gerbonara/errors），
本层零计算零改形，仅维持分层接线与命名入口。KiCad 环境缺失不抛——core
返回 ok=False 信封（errors 首条=环境缺失原因），CLI/MCP 信封直通，
不静默 skip。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.gerber_export import export_gerber_x2 as _export_core

__all__ = ["export_pcb_gerber_x2"]


def export_pcb_gerber_x2(
    pcb_path: str,
    out_dir: str,
    *,
    kicad_python: str | None = None,
) -> dict[str, Any]:
    """KiCad 板 → Gerber X2 + Excellon 导出（薄转发 core，KiCad 子进程规则 2）。

    Args:
        pcb_path: .kicad_pcb 板文件路径。
        out_dir: Gerber 产物输出目录。
        kicad_python: KiCad 自带 Python 显式路径（缺省走 env
            ``RFAUTO_KICAD_PYTHON`` 与缺省位解析，见 core.resolve_kicad_python）。

    Returns:
        dict: core 契约信封原样（ok=False 时 errors 带逐条原因）。
    """
    return _export_core(pcb_path, out_dir, kicad_python=kicad_python)
