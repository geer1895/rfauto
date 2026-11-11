"""Verilog-A 解析服务包装（aurora_q Q-X80，2026-11-08）。

:mod:`rfauto.core.veriloga_parser`（单源解析内核）的规则 4 JSON 进出薄
包装——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸
dict 错误路径），零数值逻辑（词法、module/analog 结构与表达式归一全在
core 确定性内核；铁律 7）。

三函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_veriloga_file`：全结构化解析（modules/参数/analog 三面）
  ——``veriloga parse --json`` 信封即本函数全量返回；
- :func:`veriloga_report`：统计聚合（逐模块计数摘要+全模块参数表+全部
  贡献对平坦清单）——``veriloga report --json`` 信封；
- :func:`veriloga_module_detail`：单模块查询（端口/net/参数/analog 汇总
  视图；不存在 → error 信封带可用模块名录——消费方不猜）。

错误归一：文件不可读（OSError）/空文件/词法违规（VerilogAParseError）/
**无 module 声明** → error 信封（errors 恒 list[str]），CLI 层 exit 1。
endmodule 缺失=warning 不拒（core fail-soft，信封 ok=True 携 warnings）。
解码链=utf-8 优先、Latin-1 兜底（Verilog-A 正文为 ASCII 口径，工具头
注释偶发高位字节不炸读取——verilog_netlist_service/stil_service 同款
先例）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——verilog_netlist_service 同款先例，新模块
零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.veriloga_parser import (
    VerilogAParseError,
    parse_veriloga,
    veriloga_contribution_pairs,
    veriloga_module_summary,
    veriloga_param_table,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（Verilog-A 正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load_document(path: str | Path) -> dict[str, Any]:
    """读文件+解析两步合成（OSError/VerilogAParseError 由调用方分型捕获）。

    解析成功但**无 module 声明** → :class:`VerilogAParseError`（错误
    信息带 "无 module" 字样——服务层单源判定，CLI 信封同文）。
    """
    doc = parse_veriloga(_read_text(path))
    if not doc["module_order"]:
        raise VerilogAParseError("无 module 声明（空文档或纯注释）")
    return doc


def parse_veriloga_file(path: str | Path) -> dict[str, Any]:
    """Verilog-A 文件 → 全结构化信封（modules/参数/analog 三面）。

    信封：``{"ok": True, "path", "modules", "module_order", "disciplines",
    "attributes", "warnings", "stats"}`` / error 信封（errors 恒
    list[str]）。endmodule 缺失=warning 不拒（ok=True 携 warnings）。
    纯只读：不落盘、零网络、零真机。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"Verilog-A 文件不可读: {exc}")
    except VerilogAParseError as exc:
        return error_envelope(f"Verilog-A 解析失败: {exc}")
    return ok_envelope(
        path=str(path),
        modules=doc["modules"],
        module_order=doc["module_order"],
        disciplines=doc["disciplines"],
        attributes=doc["attributes"],
        warnings=doc["warnings"],
        stats=doc["stats"],
    )


def veriloga_report(path: str | Path) -> dict[str, Any]:
    """Verilog-A 文件 → 统计聚合信封（逐模块摘要+参数表+贡献对清单）。

    ``modules_summary``=逐模块 ``{"name", "n_ports", "n_nets", "n_params",
    "stmt_counts", "n_contributions", "n_events"}``（module_order 插入序
    ——确定性）；``param_table``=全模块参数平坦表；
    ``contribution_pairs``=全部 ``{module, lhs, rhs_prefix_tree}`` 对
    （行为模型端口 I-V 关系的结构化入口）。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"Verilog-A 文件不可读: {exc}")
    except VerilogAParseError as exc:
        return error_envelope(f"Verilog-A 解析失败: {exc}")
    modules_summary = []
    for name in doc["module_order"]:
        body = doc["modules"][name]
        analog = body["analog"]
        modules_summary.append({
            "name": name,
            "n_ports": len(body["ports"]),
            "n_nets": sum(len(n["names"]) for n in body["nets"]),
            "n_params": len(body["params"]),
            "stmt_counts": dict(analog["stmt_counts"]),
            "n_contributions": len(analog["contributions"]),
            "n_events": len(analog["events"]),
        })
    return ok_envelope(
        path=str(path),
        module_names=doc["module_order"],
        modules_summary=modules_summary,
        param_table=veriloga_param_table(doc),
        contribution_pairs=veriloga_contribution_pairs(doc),
        disciplines=doc["disciplines"],
        warnings=doc["warnings"],
        stats=doc["stats"],
    )


def veriloga_module_detail(path: str | Path, module: str) -> dict[str, Any]:
    """Verilog-A 文件 → 单模块查询信封（汇总视图）。

    ``module`` 不存在 → error 信封（可用模块名录随 errors 给出——消费
    方不猜）；命中 → ``{"ok": True, "path", "module", "summary",
    "warnings"}``。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"Verilog-A 文件不可读: {exc}")
    except VerilogAParseError as exc:
        return error_envelope(f"Verilog-A 解析失败: {exc}")
    try:
        summary = veriloga_module_summary(doc, module)
    except KeyError as exc:
        return error_envelope(str(exc.args[0]))
    return ok_envelope(
        path=str(path),
        module=module,
        summary=summary,
        warnings=doc["warnings"],
    )
