"""GDSII 解析服务包装（aurora_q 席位 Q-X58，2026-11-07）。

:mod:`rfauto.core.gdsii_parser`（单源解析内核）的规则 4 JSON 进出薄
包装——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸
dict），零数值逻辑（字节级记录流与 GDSII 结构语义全在 core 确定性内
核；铁律 7）。

三函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_gdsii_file`：全结构化解析（lib/version/units + 结构六桶
  + stats）——``gdsii parse --json`` 信封即本函数全量返回；
- :func:`gdsii_layer_report`：层汇总报告（逐 (layer,datatype) 元素计数
  + 包围盒）——``gdsii layers --json`` 消费面；
- :func:`gdsii_hierarchy_report`：层级报告（引用计数/未定义引用/孤儿
  结构双桶）——拓扑只读面。

错误归一（任务书口径）：文件不存在/不可读/垃圾流（GdsiiParseError）/
**流中截断**（truncated=True——fail-soft 已收面随 errors 诊断字段如实
带回，不冒充完整文档）→ error 信封（errors 恒 list[str]），CLI 层
exit 1。纯只读：不落盘、零网络、零真机。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——verilog_netlist_service 同款先例，新模块
零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.gdsii_parser import (
    GdsiiParseError,
    gdsii_hierarchy_stats,
    gdsii_layer_summary,
    parse_gdsii_bytes,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def _load_doc(
    path: str | Path,
) -> tuple[dict[str, Any], None] | tuple[None, dict[str, Any]]:
    """读+解析 → (doc, None) 或 (None, error_envelope)。

    错误分型（任务书口径）：不存在/不可读（OSError）/垃圾流
    （GdsiiParseError）/流中截断（truncated=True，已收面计数随诊断字段
    带回）→ error 信封；citi_service._load_packages 同款两步合成。
    """
    p = Path(path)
    if not p.exists():
        return None, error_envelope(f"GDSII 文件不存在: {p}")
    try:
        data = p.read_bytes()
    except OSError as exc:
        return None, error_envelope(f"GDSII 文件不可读: {exc}")
    try:
        doc = parse_gdsii_bytes(data)
    except GdsiiParseError as exc:
        return None, error_envelope(f"GDSII 解析失败: {exc}")
    if doc["truncated"]:
        return None, error_envelope(
            f"GDSII 流截断：已收 {len(doc['structures'])} 个结构后在记录"
            "边界停止（不冒充完整文档）",
            warnings=doc["warnings"],
            n_structures_parsed=len(doc["structures"]),
        )
    return doc, None


def parse_gdsii_file(path: str | Path) -> dict[str, Any]:
    """GDSII 文件 → 全结构化信封（lib/version/units + 结构六桶 + stats）。

    信封：``{"ok": True, "path", "lib_name", "version", "units",
    "units_raw", "structures", "stats", "warnings"}`` / error 信封
    （errors 恒 list[str]）。纯只读：不落盘、零网络、零真机。
    """
    doc, err = _load_doc(path)
    if err is not None:
        return err
    return ok_envelope(
        path=str(path),
        lib_name=doc["lib_name"],
        version=doc["version"],
        units=doc["units"],
        units_raw=doc["units_raw"],
        structures=doc["structures"],
        stats=doc["stats"],
        warnings=doc["warnings"],
    )


def gdsii_layer_report(path: str | Path) -> dict[str, Any]:
    """GDSII 文件 → 层汇总信封（逐 (layer,datatype) 元素计数+包围盒）。

    ``gdsii layers`` 叶消费面；层键面与 bbox 口径全在 core
    :func:`rfauto.core.gdsii_parser.gdsii_layer_summary`（DBU 原值落键，
    DBU→µm 走 core 显式换算函数）。
    """
    doc, err = _load_doc(path)
    if err is not None:
        return err
    summary = gdsii_layer_summary(doc)
    return ok_envelope(
        path=str(path),
        layers=summary["layers"],
        n_layer_keys=summary["n_layer_keys"],
        warnings=doc["warnings"],
    )


def gdsii_hierarchy_report(path: str | Path) -> dict[str, Any]:
    """GDSII 文件 → 层级报告信封（引用计数/未定义引用/孤儿双桶）。

    ``宁多报不误报`` 口径：孤儿（零引用零元素）与零引用（含非空叶/
    顶层）双桶都如实给出；未定义引用带逐名引用次数。
    """
    doc, err = _load_doc(path)
    if err is not None:
        return err
    stats = gdsii_hierarchy_stats(doc)
    return ok_envelope(
        path=str(path),
        reference_counts=stats["reference_counts"],
        undefined_references=stats["undefined_references"],
        orphan_structures=stats["orphan_structures"],
        unreferenced_structures=stats["unreferenced_structures"],
        warnings=doc["warnings"],
    )
