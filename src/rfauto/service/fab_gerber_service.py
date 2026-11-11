"""Gerber/Excellon 制造面解析服务包装（aurora_q 席位 Q-X59，2026-11-07）。

:mod:`rfauto.core.gerber_parser` 与 :mod:`rfauto.core.excellon_parser`
（单源解析内核）的规则 4 JSON 进出薄包装——信封走
:mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸 dict），零数值
逻辑（词法与几何语义全在 core 确定性内核；铁律 7）。

四函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_gerber_file`：Gerber RS-274X 文件 → 全结构化信封
  （``fab parse --gerber`` 消费）；
- :func:`parse_excellon_file`：Excellon 钻孔文件 → 全结构化信封
  （``fab parse --drill`` 消费）；
- :func:`summarize_gerber`：层摘要消费面（``fab summary --gerber``）；
- :func:`gerber_excellon_pair_check`：一对 gerber+drill 交叉校验
  （``fab parse --gerber --drill`` 消费）：孔位是否落板 bbox 内
  （越界列表）+ 孔数汇总（n_hits/n_tools vs 全零文件等基本健康面）。

错误归一：文件不可读/解码失败（OSError/UnicodeDecodeError）→ error
信封；词法文件级违规（GerberParseError/ExcellonParseError）→ error
信封（errors 恒 list[str]），CLI 层 exit 1。解码链=utf-8 优先、
Latin-1 兜底（制造文件正文 ASCII 口径，工具头注释偶发高位字节不炸
读取——sdc_service/liberty_service 同款先例）。

pair_check 判定口径（如实三分）：孔位坐标任一轴 None（单位未声明等
fail-soft 面）→ skip 列表（不判越界不凑绿，#122 口径）；越界=两轴
均已知且任一轴出 bbox（bbox None=无几何参照，全表 skip 如实）；bbox
元素含 None（单位缺失）→ skip 全表 + note。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——verilog_netlist_service 同款先例，新模块
零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.excellon_parser import ExcellonParseError, parse_excellon
from rfauto.core.gerber_parser import GerberParseError, parse_gerber
from rfauto.service.envelope import error_envelope, ok_envelope


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（制造文件正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def parse_gerber_file(path: str | Path) -> dict[str, Any]:
    """Gerber RS-274X 文件 → 全结构化信封（指令级解析+几何落地面）。

    信封：``{"ok": True, "kind": "gerber", "path", **doc 全键}`` /
    error 信封（errors 恒 list[str]）。纯只读：不落盘、零网络、零真机。
    """
    try:
        text = _read_text(path)
    except OSError as exc:
        return error_envelope(f"Gerber 文件不可读: {exc}", kind="gerber",
                              path=str(path))
    try:
        doc = parse_gerber(text)
    except GerberParseError as exc:
        return error_envelope(f"Gerber 解析失败: {exc}", kind="gerber",
                              path=str(path))
    return ok_envelope(kind="gerber", path=str(path), **doc)


def parse_excellon_file(path: str | Path) -> dict[str, Any]:
    """Excellon 钻孔文件 → 全结构化信封（刀具/孔/槽/统计面）。

    信封：``{"ok": True, "kind": "excellon", "path", **doc 全键}`` /
    error 信封。纯只读。
    """
    try:
        text = _read_text(path)
    except OSError as exc:
        return error_envelope(f"Excellon 文件不可读: {exc}", kind="excellon",
                              path=str(path))
    try:
        doc = parse_excellon(text)
    except ExcellonParseError as exc:
        return error_envelope(f"Excellon 解析失败: {exc}", kind="excellon",
                              path=str(path))
    return ok_envelope(kind="excellon", path=str(path), **doc)


def summarize_gerber(path: str | Path) -> dict[str, Any]:
    """Gerber 文件 → 层摘要信封（``fab summary --gerber`` 消费面）。

    ``parse_gerber_file`` 全量解析（确定性内核单次）+ 摘要三件套
    （per_dcode 分组计数/per_shape aperture 类型统计/包络盒），信封
    ``{"ok": True, "kind": "gerber_summary", "path", "summary", "bbox",
    "arc_notes", "stats"}`` / error 信封。
    """
    result = parse_gerber_file(path)
    if not result.get("ok"):
        return result
    from rfauto.core.gerber_parser import (
        arc_chord_warning,
        gerber_bbox,
        gerber_layer_summary,
    )

    summary = gerber_layer_summary(result)
    bbox = gerber_bbox(result)
    return ok_envelope(
        kind="gerber_summary",
        path=str(path),
        units=result.get("units"),
        format_spec=result.get("format_spec"),
        summary=summary,
        bbox=bbox,
        arc_notes=arc_chord_warning(result),
        stats=result.get("stats"),
        truncated=result.get("truncated"),
        warnings=result.get("warnings"),
    )


def gerber_excellon_pair_check(gerber_path: str | Path,
                               drill_path: str | Path) -> dict[str, Any]:
    """Gerber+Excellon 一对文件交叉校验信封（孔位越界列表+孔数汇总）。

    判定口径（如实三分，#122 不凑绿）：
    - 孔位两轴已知 + gerber bbox 已知 → 逐孔判定，任一轴出 bbox 即
      ``out_of_bounds`` 条目 ``{index, tool, x_mm, y_mm, axis, value}``；
    - 孔位任一轴 None（单位缺失 fail-soft 面）或 bbox None/含 None
      （无几何参照）→ ``skipped`` 计数如实（不判越界）。

    信封：``{"ok": True, "kind": "pair_check", "gerber_path",
    "drill_path", "bbox_mm", "n_hits", "n_slots", "n_tools",
    "per_tool_counts", "n_out_of_bounds", "out_of_bounds", "n_skipped",
    "notes"}``；两文件任一解析失败 → error 信封（首错优先，errors 恒
    list[str]）。
    """
    g = parse_gerber_file(gerber_path)
    if not g.get("ok"):
        return g
    d = parse_excellon_file(drill_path)
    if not d.get("ok"):
        return d

    bbox = g.get("outline_bbox_mm")
    notes: list[str] = []
    bbox_usable = (isinstance(bbox, (list, tuple)) and len(bbox) == 4
                   and all(v is not None for v in bbox))
    if bbox is None:
        notes.append("Gerber 层无几何元素（bbox=None），越界判定全表 skip")
    elif not bbox_usable:
        notes.append("Gerber 包络盒含 None（单位缺失 fail-soft 面），"
                     "越界判定全表 skip")

    out_of_bounds: list[dict[str, Any]] = []
    n_skipped = 0
    for idx, h in enumerate(d.get("hits") or []):
        x = h.get("x_mm")
        y = h.get("y_mm")
        if x is None or y is None:
            n_skipped += 1
            continue
        if not bbox_usable:
            n_skipped += 1
            continue
        xmin, ymin, xmax, ymax = bbox
        for axis, val, lo, hi in (("x", x, xmin, xmax), ("y", y, ymin, ymax)):
            if val < lo or val > hi:
                out_of_bounds.append({
                    "index": idx,
                    "tool": h.get("tool"),
                    "x_mm": x,
                    "y_mm": y,
                    "axis": axis,
                    "value_mm": val,
                })
                break

    return ok_envelope(
        kind="pair_check",
        gerber_path=str(gerber_path),
        drill_path=str(drill_path),
        bbox_mm=list(bbox) if bbox is not None else None,
        n_hits=d.get("stats", {}).get("n_hits"),
        n_slots=d.get("stats", {}).get("n_slots"),
        n_tools=d.get("stats", {}).get("n_tools"),
        per_tool_counts=d.get("stats", {}).get("per_tool_counts"),
        n_out_of_bounds=len(out_of_bounds),
        out_of_bounds=out_of_bounds,
        n_skipped=n_skipped,
        notes=notes,
    )
