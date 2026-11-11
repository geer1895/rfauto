"""BSDL 边界扫描解析服务包装（aurora_q Q-X77 席位，2026-11-08）。

:mod:`rfauto.core.bsdl_parser`（单源解析内核）的规则 4 JSON 进出薄包装
——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸 dict
错误路径），零数值逻辑（词法、entity/port/属性面与边界寄存器解析及
查询派生全在 core 确定性内核；铁律 7）。

三函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_bsdl_file`：全结构化解析（entity/port/TAP/引脚映射/
  指令面/边界寄存器/一致性三数字）——``bsdl parse --json`` 信封即本
  函数全量返回；
- :func:`bsdl_report`：统计+TAP/指令/边界长度一致性聚合（``bsdl
  report --json`` 信封；指令表摘要+边界单元 function 分桶+三数字）；
- :func:`bsdl_boundary_detail`：边界单元清单查询（全量平坦清单或
  ``port`` 过滤关联视图——input 直接/output3 经控制链关联；port 未
  命中→error 信封带可用 port 名录——消费方不猜）。

错误归一：文件不可读（OSError）/空文件/无 entity/entity 未收口
（BsdlParseError）→ error 信封（errors 恒 list[str]），CLI 层 exit 1。
解码链=utf-8 优先、Latin-1 兜底（BSDL 正文为 ASCII 口径，工具头注释
偶发高位字节不炸读取——stil_service/verilog_netlist_service 同款先例）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——stil_service 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.bsdl_parser import (
    BsdlParseError,
    bsdl_boundary_cells,
    bsdl_cell_lookup,
    bsdl_instruction_table,
    parse_bsdl,
)
from rfauto.service.envelope import error_envelope, ok_envelope

#: detail 未命中提示名录的显示上限（超限截断+总数注记——大器件不炸报文）。
_DETAIL_NAME_CAP = 30


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（BSDL 正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load_document(path: str | Path) -> dict[str, Any]:
    """读文件+解析两步合成（OSError/BsdlParseError 由调用方分型捕获）。"""
    return parse_bsdl(_read_text(path))


def parse_bsdl_file(path: str | Path) -> dict[str, Any]:
    """BSDL 文件 → 全结构化信封（entity/port/TAP/引脚映射/指令/边界）。

    信封：``{"ok": True, "path", "entity_name", "n_entities", "generics",
    "ports", "tap_ports", "n_tap_present", "pin_map_ref",
    "pin_map_constant", "pins", "use_clauses", "instructions",
    "instruction_capture", "idcode_register", "idcode_length",
    "idcode_valid", "boundary_cells", "boundary_length_declared",
    "boundary_length_max_cell_plus_1", "boundary_length_rel_diff",
    "attributes_other", "constants", "stats", "warnings"}`` / error 信封
    （errors 恒 list[str]）。纯只读：不落盘、零网络、零真机。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"BSDL 文件不可读: {exc}")
    except BsdlParseError as exc:
        return error_envelope(f"BSDL 解析失败: {exc}")
    return ok_envelope(
        path=str(path),
        entity_name=doc["entity_name"],
        n_entities=doc["n_entities"],
        generics=doc["generics"],
        ports=doc["ports"],
        tap_ports=doc["tap_ports"],
        n_tap_present=doc["n_tap_present"],
        pin_map_ref=doc["pin_map_ref"],
        pin_map_constant=doc["pin_map_constant"],
        pins=doc["pins"],
        use_clauses=doc["use_clauses"],
        instructions=doc["instructions"],
        instruction_capture=doc["instruction_capture"],
        idcode_register=doc["idcode_register"],
        idcode_length=doc["idcode_length"],
        idcode_valid=doc["idcode_valid"],
        boundary_cells=doc["boundary_cells"],
        boundary_length_declared=doc["boundary_length_declared"],
        boundary_length_max_cell_plus_1=doc["boundary_length_max_cell_plus_1"],
        boundary_length_rel_diff=doc["boundary_length_rel_diff"],
        attributes_other=doc["attributes_other"],
        constants=doc["constants"],
        stats=doc["stats"],
        warnings=doc["warnings"],
    )


def bsdl_report(path: str | Path) -> dict[str, Any]:
    """BSDL 文件 → 统计+TAP/指令/边界一致性聚合信封。

    ``instruction_summary``=:func:`bsdl_instruction_table` 摘要（指令
    表+capture/idcode）；``boundary_summary``=单元 function 分桶计数+
    一致性三数字（length_declared/max_cell+1/rel_diff——SPEF cap sum
    同款口径，报告面不做硬门）；另带 ports/tap/pins 名录摘要。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"BSDL 文件不可读: {exc}")
    except BsdlParseError as exc:
        return error_envelope(f"BSDL 解析失败: {exc}")
    function_buckets: dict[str, int] = {}
    for cell in doc["boundary_cells"]:
        key = str(cell.get("function") or "unknown")
        function_buckets[key] = function_buckets.get(key, 0) + 1
    return ok_envelope(
        path=str(path),
        entity_name=doc["entity_name"],
        n_entities=doc["n_entities"],
        stats=doc["stats"],
        tap_ports=doc["tap_ports"],
        n_tap_present=doc["n_tap_present"],
        pins_summary=[
            {"pin": pin, "locations": locs}
            for pin, locs in doc["pins"].items()
        ],
        ports_summary=[
            {"name": name, "dir": info["dir"], "type": info["type"]}
            for name, info in doc["ports"].items()
        ],
        instruction_summary=bsdl_instruction_table(doc),
        boundary_summary={
            "n_cells": len(doc["boundary_cells"]),
            "function_buckets": function_buckets,
            "length_declared": doc["boundary_length_declared"],
            "length_max_cell_plus_1": doc["boundary_length_max_cell_plus_1"],
            "length_rel_diff": doc["boundary_length_rel_diff"],
        },
        warnings=doc["warnings"],
    )


def bsdl_boundary_detail(
    path: str | Path, port: str | None = None
) -> dict[str, Any]:
    """BSDL 文件 → 边界单元清单查询信封（全量或按 port 过滤）。

    ``port=None`` → 全量平坦清单（声明序文件序）；``port`` 给定 →
    :func:`bsdl_cell_lookup` 关联视图（input 直接/output3 经控制链），
    未命中 → error 信封（可用 port 名录随 errors 给出，显示上限 30 条
    +总数注记——消费方不猜）。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"BSDL 文件不可读: {exc}")
    except BsdlParseError as exc:
        return error_envelope(f"BSDL 解析失败: {exc}")
    if port is None:
        cells = bsdl_boundary_cells(doc)
        return ok_envelope(
            path=str(path),
            entity_name=doc["entity_name"],
            port=None,
            cells=cells,
            n_cells=len(cells),
            warnings=doc["warnings"],
        )
    hit = bsdl_cell_lookup(doc, port)
    if hit is None:
        all_ports = sorted({c["port"] for c in doc["boundary_cells"]
                            if c.get("port") is not None})
        shown = all_ports[:_DETAIL_NAME_CAP]
        suffix = ""
        if len(all_ports) > _DETAIL_NAME_CAP:
            suffix = f" …共 {len(all_ports)} 个"
        hint = ", ".join(shown) + suffix if shown else "无"
        return error_envelope(
            f"port {port!r} 无关联边界单元（可用: {hint}）")
    return ok_envelope(
        path=str(path),
        entity_name=doc["entity_name"],
        port=hit["port"],
        cells=hit["cells"],
        n_cells=hit["n_cells"],
        control_cells=hit["control_cells"],
        n_control_cells=hit["n_control_cells"],
        warnings=doc["warnings"],
    )
