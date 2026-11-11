"""SPEF 寄生解析服务包装（aurora_q Q-X60 席位，2026-11-07）。

:mod:`rfauto.core.spef_parser`（单源解析内核）的规则 4 JSON 进出薄
包装——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸
dict 错误路径），零数值逻辑（词法与 SPEF 结构语义、单位换算、拓扑
派生全在 core 确定性内核；铁律 7）。

三函数（无 MCP 面——本席任务书未含工具叶；CLI 薄壳见
cli/domains/spef.py，main.py 接线由主代合流统一）：

- :func:`parse_spef_file`：全结构化解析（头部+NAME_MAP 双向+PORTS+
  D_NET 四段+一致性三数字）——``spef parse --json`` 信封即本函数全
  量返回；
- :func:`spef_report`：拓扑摘要+耦合统计聚合（top_k 透传）——
  ``spef report --json`` 信封；
- :func:`spef_net_detail`：单 net 全量视图（名字不存在→error 信封带
  可用名录提示——消费方不猜）。

错误归一：文件不可读（OSError）/空文件或缺 *SPEF 头
（SpefParseError）→ error 信封（errors 恒 list[str]），CLI 层
exit 1。解码链=utf-8 优先、Latin-1 兜底（SPEF 正文为 ASCII 口径，
工具头注释偶发高位字节不炸读取——verilog_netlist_service/sdc_service
同款先例）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——verilog_netlist_service 同款先例，新模
块零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.parser_diagnostics import diagnostics_summary
from rfauto.core.spef_parser import (
    SpefParseError,
    parse_spef,
    spef_coupling_stats,
    spef_net_lookup,
    spef_topology_summary,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（SPEF 正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load_document(path: str | Path) -> dict[str, Any]:
    """读文件+解析两步合成（OSError/SpefParseError 由调用方分型捕获）。"""
    return parse_spef(_read_text(path))


def parse_spef_file(path: str | Path) -> dict[str, Any]:
    """SPEF 文件 → 全结构化信封（头部+NAME_MAP 双向+PORTS+D_NET 段）。

    信封：``{"ok": True, "path", "header", "name_map",
    "name_map_reverse", "ports", "nets", "stats", "warnings",
    "diagnostics", "value_continuations"}`` / error 信封（errors 恒
    list[str]）。后两键为 AX-6/数值扩展附加层（纯增量）。纯只读：不落
    盘、零网络、零真机。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"SPEF 文件不可读: {exc}")
    except SpefParseError as exc:
        return error_envelope(f"SPEF 解析失败: {exc}")
    return ok_envelope(
        path=str(path),
        header=doc["header"],
        name_map=doc["name_map"],
        name_map_reverse=doc["name_map_reverse"],
        ports=doc["ports"],
        nets=doc["nets"],
        stats=doc["stats"],
        warnings=doc["warnings"],
        diagnostics=doc["diagnostics"],
        value_continuations=doc["value_continuations"],
    )


def spef_report(path: str | Path, *, top_k: int = 5) -> dict[str, Any]:
    """SPEF 文件 → 拓扑摘要+耦合统计聚合信封（``spef report`` 消费面）。

    ``top_k`` 透传 :func:`rfauto.core.spef_parser.spef_coupling_stats`
    （最强耦合对条数，缺省 5）。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"SPEF 文件不可读: {exc}")
    except SpefParseError as exc:
        return error_envelope(f"SPEF 解析失败: {exc}")
    return ok_envelope(
        path=str(path),
        design=doc["header"].get("design"),
        units=doc["header"]["units"],
        topology=spef_topology_summary(doc),
        coupling=spef_coupling_stats(doc, top_k=top_k),
        stats=doc["stats"],
        warnings=doc["warnings"],
        diagnostics=doc["diagnostics"],
        diagnostics_summary=diagnostics_summary(doc["diagnostics"]),
    )


def spef_net_detail(path: str | Path, name: str) -> dict[str, Any]:
    """SPEF 文件 → 单 net 全量视图信封（按展开名查询）。

    ``name`` 不存在 → error 信封（可用 net 名录随 errors 给出——消费
    方不猜）；命中 → ``{"ok": True, "path", "net", "topology"}``，其中
    ``topology`` 为该 net 的拓扑摘要单条。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"SPEF 文件不可读: {exc}")
    except SpefParseError as exc:
        return error_envelope(f"SPEF 解析失败: {exc}")
    net = spef_net_lookup(doc, name)
    if net is None:
        names = [n["name"] for n in doc["nets"]]
        return error_envelope(
            f"网络 {name!r} 不存在（可用: {', '.join(names) or '无'}）")
    summary = spef_topology_summary(doc)
    topo = next(
        (t for t in summary["nets"] if t["name"] == name), None)
    return ok_envelope(
        path=str(path),
        net=net,
        topology=topo,
        warnings=doc["warnings"],
        diagnostics=doc["diagnostics"],
    )
