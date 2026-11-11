"""ODB++ 目录解析服务包装（aurora_q 席位 Q-X68，2026-11-08）。

:mod:`rfauto.core.odbpp_parser`（单源解析内核）的规则 4 JSON 进出薄
包装——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸
dict），零数值逻辑（词法与结构语义全在 core 确定性内核；铁律 7）。

两函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_odbpp_dir`：ODB++ 目录树 → 全结构化信封（matrix/
  steps/layers/cadnet/eda/symbols 五文件级解析）——``odbpp report
  --dir`` 消费形态；
- :func:`odbpp_report`：报告面（stack 对齐+net 库存统计聚合，含悬空
  pad/空 net 双清单）——``odbpp report`` 缺省消费形态（core 全量
  inventory 单次 + 派生聚合，不重复解析）。

错误归一：目录不存在/缺 matrix（OdbppParseError）→ error 信封；
文件面不可读已在 core fail-soft 消化（warning 如实登记，不判错）。
CLI 层 exit 1。本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——ipc356_service 同款先例，新模块零金快照
漂移）。

与本仓既有 ODB++ 面的边界（core/odbpp_parser docstring 同账）：本模块
是服务层第三面——adapters/layout_interchange（几何展开）与
format_overview_service（速览探测）不包装，零重叠。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.odbpp_parser import (
    OdbppParseError,
    odbpp_net_inventory,
    parse_odb_dir,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def parse_odbpp_dir(root: str | Path) -> dict[str, Any]:
    """ODB++ 目录树 → 全结构化信封（五文件级解析+全树统计）。

    信封：``{"ok": True, "kind": "odbpp", "root", **doc 全键}`` /
    error 信封（errors 恒 list[str]；目录不存在/缺 matrix）。纯只读：
    不落盘、零网络、零真机。
    """
    try:
        doc = parse_odb_dir(root)
    except OdbppParseError as exc:
        return error_envelope(f"ODB++ 目录解析失败: {exc}", kind="odbpp",
                              root=str(root))
    # doc 自带 root 键（core 解析产物），此处不再重复落 root
    return ok_envelope(kind="odbpp", **doc)


def odbpp_report(root: str | Path) -> dict[str, Any]:
    """ODB++ 目录 → 报告信封（stack 对齐+net 库存统计聚合）。

    ``odbpp report`` 缺省消费形态：全树单次解析 + net inventory 单次
    派生，聚合面=逐 step（层目录数/特征记录数/pad 引用/stack 对齐布尔
    +悬空 pad+空 net）+ 全树统计。信封
    ``{"ok": True, "kind": "odbpp_report", "root", "matrix", "steps",
    "inventory", "stats", "warnings"}`` / error 信封。
    """
    doc_env = parse_odbpp_dir(root)
    if not doc_env.get("ok"):
        return doc_env

    matrix = doc_env.get("matrix") or {}
    step_reports: list[dict[str, Any]] = []
    total_empty_nets: list[str] = []
    total_dangling: list[dict[str, Any]] = []
    for step_doc in doc_env.get("steps") or []:
        inv = odbpp_net_inventory(step_doc)
        stack = step_doc.get("stack_summary") or {}
        n_feature_records = sum(
            sum((layer_doc.get("features") or {}).get("records", {}).values())
            for layer_doc in step_doc.get("layers") or []
        )
        n_pad_refs = sum(
            (layer_doc.get("features") or {}).get("pad_refs", 0)
            for layer_doc in step_doc.get("layers") or []
        )
        step_reports.append({
            "name": step_doc.get("name"),
            "n_layers_on_disk": len(step_doc.get("layers") or []),
            "n_feature_records": n_feature_records,
            "n_pad_refs": n_pad_refs,
            "stack_aligned": bool(stack.get("aligned")),
            "stack_missing": list(stack.get("missing") or []),
            "stack_extra": list(stack.get("extra") or []),
            "n_nets": (step_doc.get("cadnet") or {}).get("stats", {}).get(
                "n_nets", 0),
            "n_net_points": (step_doc.get("cadnet") or {}).get(
                "stats", {}).get("n_points", 0),
            "n_eda_nets": (step_doc.get("eda_data") or {}).get(
                "stats", {}).get("n_nets", 0),
            "empty_nets": list(inv.get("empty_nets") or []),
            "dangling_pads": list(inv.get("dangling_pads") or []),
            "inventory_stats": inv.get("stats"),
        })
        total_empty_nets.extend(inv.get("empty_nets") or [])
        total_dangling.extend(inv.get("dangling_pads") or [])

    stats = doc_env.get("stats") or {}
    return ok_envelope(
        kind="odbpp_report",
        root=str(root),
        matrix_kind=matrix.get("kind"),
        n_layers_declared=stats.get("n_layers_declared"),
        n_layers_on_disk=stats.get("n_layers_on_disk"),
        steps=step_reports,
        n_steps=len(step_reports),
        empty_nets=total_empty_nets,
        n_empty_nets=len(total_empty_nets),
        dangling_pads=total_dangling,
        n_dangling_pads=len(total_dangling),
        model_units=doc_env.get("model_units"),
        stats=stats,
        warnings=doc_env.get("warnings"),
    )
