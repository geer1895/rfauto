"""Liberty (.lib) 解析服务包装（aurora_q Q-X34，2026-11-07）。

:mod:`rfauto.core.liberty_parser`（单源解析内核）的规则 4 JSON 进出薄
包装——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸
dict），零数值逻辑（查找表/插值全在 core 确定性内核；铁律 7）。

两函数（与 CLI/MCP 同源同名薄壳消费）：

- :func:`parse_liberty_file`：全结构化解析（cells/pins/timing 四张
  NLDM 查找表/internal_power/leakage_power/operating_conditions/
  lu_table_template）+ cell/pin 过滤 + timing/power 裁面开关 + stats
  计数（对返回视图计数）；
- :func:`list_liberty_cells`：库清单只读面（cell 名/面积/pin 数/表数
  + 模板与 operating_conditions 名录）。

错误归一：文件不可读/解码失败/语法违规（LibertyParseError）/过滤目标
不存在 → error 信封（errors 恒 list[str]），CLI 层 exit 1。解码链=
utf-8 优先、Latin-1 兜底（Liberty 规范正文为 ASCII，Latin-1 恒可解，
供应商库头注释偶发高位字节不炸读取）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——hfss_run_report_service 同款先例，新模块
零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.liberty_parser import (
    LIBERTY_POWER_TABLES,
    LIBERTY_TIMING_TABLES,
    PARSER_SCHEMA_VERSION,
    LibertyGroup,
    LibertyParseError,
    extract_library,
    parse_liberty,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（Liberty 正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load_library(path: str | Path) -> LibertyGroup:
    return parse_liberty(_read_text(path))


def _count_timing_tables(cell_entry: dict[str, Any]) -> int:
    n = 0
    for pin in cell_entry["pins"].values():
        for tg in pin.get("timing", {}).values():
            n += sum(1 for k in LIBERTY_TIMING_TABLES if tg.get(k) is not None)
    return n


def _count_power(cell_entry: dict[str, Any]) -> tuple[int, int]:
    """（internal_power 组数，功率表数）。"""
    n_groups = 0
    n_tables = 0
    for pin in cell_entry["pins"].values():
        for ip in pin.get("internal_power", []):
            n_groups += 1
            n_tables += sum(1 for k in LIBERTY_POWER_TABLES if ip.get(k) is not None)
    if cell_entry.get("leakage_power"):
        n_groups += len(cell_entry["leakage_power"])
    return n_groups, n_tables


def _stats(cells: dict[str, dict[str, Any]],
           templates: dict[str, Any]) -> dict[str, int]:
    n_pins = sum(len(c["pins"]) for c in cells.values())
    n_timing_groups = sum(
        len(p.get("timing", {})) for c in cells.values() for p in c["pins"].values())
    n_timing_tables = sum(_count_timing_tables(c) for c in cells.values())
    n_power_groups = 0
    n_power_tables = 0
    for c in cells.values():
        g, t = _count_power(c)
        n_power_groups += g
        n_power_tables += t
    n_leakage = sum(len(c.get("leakage_power") or []) for c in cells.values())
    return {
        "n_cells": len(cells),
        "n_pins": n_pins,
        "n_timing_groups": n_timing_groups,
        "n_timing_tables": n_timing_tables,
        "n_power_groups": n_power_groups,
        "n_power_tables": n_power_tables,
        "n_leakage_groups": n_leakage,
        "n_lu_templates": len(templates),
    }


def parse_liberty_file(
    path: str | Path,
    *,
    cell: str | None = None,
    pin: str | None = None,
    include_timing: bool = True,
    include_power: bool = True,
) -> dict[str, Any]:
    """Liberty 文件 → 结构化信封（cell/pin 过滤+timing/power 裁面）。

    - ``cell``：只保留同名 cell（未知名 → error 信封附可用清单）；
    - ``pin``：在 cell 过滤基础上只保留同名 pin（必须配合 ``cell``——
      pin 属于 cell，跨 cell 扫描会让同名 pin 归属歧义）；
    - ``include_timing/include_power=False``：剪对应面（stats 随视图
      同步缩），pin 元数据（direction/function/capacitance）不受影响；
    - ``stats``：对**返回视图**计数（过滤/裁面后），配 ``filtered``
      键如实声明过滤状态。

    信封：``{"ok": True, "schema", "path", "library", "file_version",
    "units", "cells", "operating_conditions", "lu_templates", "stats",
    "filters"}`` / error 信封（errors 恒 list[str]）。
    """
    if pin is not None and cell is None:
        return error_envelope("pin 过滤必须配合 cell（pin 属于某个 cell，"
                              "跨 cell 扫描会同名歧义）")
    try:
        library = _load_library(path)
    except OSError as exc:
        return error_envelope(f"Liberty 文件不可读: {exc}")
    except LibertyParseError as exc:
        return error_envelope(f"Liberty 解析失败: {exc}")
    data = extract_library(library, include_timing=include_timing,
                           include_power=include_power)
    cells = data["cells"]
    if cell is not None and cell not in cells:
        return error_envelope(
            f"cell 不存在: {cell}（可用: {', '.join(sorted(cells)) or '无'}）")
    if cell is not None:
        cells = {cell: cells[cell]}
    if pin is not None and cell is not None:
        entry = cells[cell]
        pins = entry["pins"]
        if pin not in pins:
            return error_envelope(
                f"pin 不存在: cell {cell} 无 pin {pin}（可用: "
                f"{', '.join(sorted(pins)) or '无'}）")
        entry["pins"] = {pin: pins[pin]}
    stats = _stats(cells, data["lu_templates"])
    return ok_envelope(
        path=str(path),
        # 自描述键（R-22 schema 升位批）：解析产物为组树（非 dict），
        # ``"<域>/<N.0>"`` 复合键由信封携带（skill_service 同款先例）。
        schema=f"liberty/{PARSER_SCHEMA_VERSION}",
        library=data["library"],
        file_version=data["file_version"],
        units=data["units"],
        cells=cells,
        operating_conditions=data["operating_conditions"],
        lu_templates=data["lu_templates"],
        stats=stats,
        filters={
            "cell": cell,
            "pin": pin,
            "include_timing": include_timing,
            "include_power": include_power,
        },
    )


def list_liberty_cells(path: str | Path) -> dict[str, Any]:
    """Liberty 文件 → 库清单只读信封（cell 名/面积/计数+模板/工况名录）。"""
    try:
        library = _load_library(path)
    except OSError as exc:
        return error_envelope(f"Liberty 文件不可读: {exc}")
    except LibertyParseError as exc:
        return error_envelope(f"Liberty 解析失败: {exc}")
    data = extract_library(library)  # 全量提取（清单只报计数不落表体）
    listing = []
    for name, entry in data["cells"].items():
        n_power_groups, _ = _count_power(entry)
        listing.append({
            "name": name,
            "area": entry["area"],
            "n_pins": len(entry["pins"]),
            "n_timing_groups": sum(len(p.get("timing", {}))
                                   for p in entry["pins"].values()),
            "n_timing_tables": _count_timing_tables(entry),
            "n_power_groups": n_power_groups,
        })
    return ok_envelope(
        path=str(path),
        library=data["library"],
        file_version=data["file_version"],
        cells=listing,
        lu_template_names=sorted(data["lu_templates"]),
        operating_condition_names=sorted(data["operating_conditions"]),
        stats=_stats(data["cells"], data["lu_templates"]),
    )
