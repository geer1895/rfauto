"""SDF 时序标注解析服务包装（aurora_q Q-X61，2026-11-07）。

:mod:`rfauto.core.sdf_parser`（单源解析内核）的规则 4 JSON 进出薄包装——
信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸 dict 错误
路径），零数值逻辑（S 表达式词法、SDF 语义、TIMESCALE 换算、查询派生与
celltype 汇总全在 core 确定性内核；铁律 7）。

三函数（无 MCP 面——本席任务书未含工具叶；CLI 薄壳见
cli/domains/sdf.py，main.py 接线由主代合流统一）：

- :func:`parse_sdf_file`：全结构化解析（header+cells 19 桶+celltypes+
  stats+warnings）——``sdf parse --json`` 信封即本函数全量返回；
- :func:`sdf_report`：头部+CELL 计数（逐 celltype 汇总）+TIMINGCHECK 十二
  类摘要聚合——``sdf report --json`` 信封；
- :func:`sdf_cell_detail`：按 CELLTYPE+实例查询（匹配规则见 core
  :func:`~rfauto.core.sdf_parser.sdf_cell_lookup`）+命中 CELL 的
  IOPATH/INTERCONNECT 平坦清单；未命中 → error 信封带可用 celltype/实例
  清单提示（消费方不猜）。

错误归一：文件不存在/不可读（OSError）/空文件/无 DELAYFILE 头/词法结构
违规/未知 TIMESCALE（SdfParseError，ValueError 子类 fail-closed）→ error
信封（errors 恒 list[str]），CLI 层 exit 1。解码链=utf-8-sig 优先（BOM
剥离）、Latin-1 兜底（SDF 正文为 ASCII 口径，工具头注释偶发高位字节不炸
读取——spef/verilog_netlist/sdc service 同款先例）。纯只读：不落盘、零
网络、零真机。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——verilog_netlist_service/gdsii_service 同款
先例，新模块零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.sdf_parser import (
    SdfParseError,
    parse_sdf,
    sdf_cell_lookup,
    sdf_celltype_summary,
    sdf_delay_paths,
    sdf_timing_check_summary,
)
from rfauto.service.envelope import error_envelope, ok_envelope

#: 未命中提示的清单截断（错误文本预览/信封字段上限——大网表单 celltype
#: 可有十万级实例，提示面只给前若干+总数，不撑爆信封）。
_PREVIEW_LIMIT = 20
_AVAILABLE_LIMIT = 50


def _read_text(path: Path) -> str:
    """读文件文本：utf-8-sig 优先（BOM 剥离），Latin-1 兜底。"""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load_doc(
    path: str | Path,
) -> tuple[dict[str, Any], None] | tuple[None, dict[str, Any]]:
    """读+解析 → (doc, None) 或 (None, error_envelope)。

    错误分型（任务书口径）：不存在 / 不可读（OSError）/ 空文件（含纯空白）
    / 解析失败（SdfParseError：无 DELAYFILE 头、括号失配、未知 TIMESCALE
    等）→ error 信封；gdsii_service._load_doc 同款两步合成。
    """
    p = Path(path)
    if not p.exists():
        return None, error_envelope(f"SDF 文件不存在: {p}")
    try:
        text = _read_text(p)
    except OSError as exc:
        return None, error_envelope(f"SDF 文件不可读: {exc}")
    if not text.strip():
        return None, error_envelope(f"SDF 文件为空: {p}")
    try:
        doc = parse_sdf(text)
    except SdfParseError as exc:
        return None, error_envelope(f"SDF 解析失败: {exc}")
    return doc, None


def _preview(names: list[str]) -> str:
    """名录预览文本（前 _PREVIEW_LIMIT 个 + 总数注记）。"""
    if not names:
        return "无"
    head = ", ".join(names[:_PREVIEW_LIMIT])
    if len(names) > _PREVIEW_LIMIT:
        head += f" …等 {len(names)} 个"
    return head


def _instance_label(cell: dict[str, Any]) -> str:
    """实例显示标签：top-level=<top>，通配/具体名=原文。"""
    if cell["instance"] is None:
        return "<top>"
    return str(cell["instance"])


def parse_sdf_file(path: str | Path) -> dict[str, Any]:
    """SDF 文件 → 全结构化信封（header+cells+celltypes+stats+warnings）。

    信封：``{"ok": True, "path", "schema", "header", "cells", "celltypes",
    "stats", "warnings"}`` / error 信封（errors 恒 list[str]）。纯只读：
    不落盘、零网络、零真机。
    """
    doc, err = _load_doc(path)
    if err is not None:
        return err
    return ok_envelope(
        path=str(path),
        schema=doc["schema"],
        header=doc["header"],
        cells=doc["cells"],
        celltypes=doc["celltypes"],
        stats=doc["stats"],
        warnings=doc["warnings"],
    )


def sdf_report(path: str | Path) -> dict[str, Any]:
    """SDF 文件 → 报告信封（头部+逐 celltype 计数+TIMINGCHECK 摘要）。

    ``sdf report`` 叶消费面：不回传 cells 全量（紧凑面），计数与最坏值
    口径全在 core（:func:`~rfauto.core.sdf_parser.sdf_celltype_summary` /
    :func:`~rfauto.core.sdf_parser.sdf_timing_check_summary`）。
    """
    doc, err = _load_doc(path)
    if err is not None:
        return err
    return ok_envelope(
        path=str(path),
        schema=doc["schema"],
        header=doc["header"],
        stats=doc["stats"],
        celltypes=doc["celltypes"],
        celltype_counts=sdf_celltype_summary(doc),
        timing_check_summary=sdf_timing_check_summary(doc),
        warnings=doc["warnings"],
    )


def sdf_cell_detail(
    path: str | Path, celltype: str, instance: str | None = None
) -> dict[str, Any]:
    """SDF 文件 → 单 CELLTYPE(+实例) 查询信封（命中 CELL+延迟路径平坦清单）。

    匹配规则见 core ``sdf_cell_lookup``（instance=None 只命中 top-level；
    ``*`` 只命中通配；具体名=精确相等+该 celltype 通配条目）。未命中 →
    error 信封：celltype 不存在时带 ``available_celltypes``；celltype 存在
    但无该实例时另带 ``available_instances``（前 50 个，``<top>`` 标记
    top-level）+``n_available_instances``——消费方不猜。
    """
    doc, err = _load_doc(path)
    if err is not None:
        return err
    matches = sdf_cell_lookup(doc, celltype, instance)
    if not matches:
        known = doc["celltypes"]
        if celltype not in known:
            return error_envelope(
                f"CELLTYPE {celltype!r} 不存在（可用 celltype: {_preview(known)}）",
                available_celltypes=known,
            )
        instances = [_instance_label(cell) for cell in doc["cells"]
                     if cell["celltype"] == celltype]
        wanted = "<top>" if instance is None else instance
        return error_envelope(
            f"CELLTYPE {celltype!r} 无实例 {wanted!r} 的条目"
            f"（该 celltype 可用实例: {_preview(instances)}）",
            available_celltypes=known,
            available_instances=instances[:_AVAILABLE_LIMIT],
            n_available_instances=len(instances),
        )
    matched = {cell["index"] for cell in matches}
    paths = [row for row in sdf_delay_paths(doc, celltype)
             if row["cell_index"] in matched]
    return ok_envelope(
        path=str(path),
        celltype=celltype,
        instance=instance,
        n_matches=len(matches),
        matches=matches,
        delay_paths=paths,
        warnings=doc["warnings"],
    )
