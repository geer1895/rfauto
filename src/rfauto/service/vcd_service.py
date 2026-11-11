"""VCD 波形解析服务包装（aurora_q Q-X63 席位，2026-11-08）。

:mod:`rfauto.core.vcd_parser`（单源解析内核）的规则 4 JSON 进出薄包装
——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸 dict
错误路径），零数值逻辑（词法与 VCD 结构语义、timescale 换算、查询派生
全在 core 确定性内核；铁律 7）。

三函数（无 MCP 面——本席任务书未含工具叶；CLI 薄壳见
cli/domains/vcd.py，main.py 接线由主代合流统一）：

- :func:`parse_vcd_file`：全结构化解析（头部+scope 树+vars 表+事件流+
  dump 窗口+统计）——``vcd parse --json`` 信封即本函数全量返回；
- :func:`vcd_report`：头部+vars 计数+时间跨窗+信号 top 活跃度聚合
  （``vcd report --json`` 信封；top_n 透传）；
- :func:`vcd_var_detail`：按名查询 var 事件流（可选 scope 前缀过滤；
  名字不存在→error 信封带可用 var 全名清单提示——消费方不猜）。

错误归一：文件不可读（OSError）/空文件或缺 ``$enddefinitions`` 或
timescale 非法（VcdParseError）→ error 信封（errors 恒 list[str]），
CLI 层 exit 1。解码链=utf-8 优先、Latin-1 兜底（VCD 正文为 ASCII 口径，
工具头注释偶发高位字节不炸读取——spef_service/verilog_netlist_service
同款先例）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——spef_service 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.vcd_parser import (
    VcdParseError,
    parse_vcd,
    vcd_activity_top,
    vcd_time_windows,
    vcd_var_lookup,
)
from rfauto.service.envelope import error_envelope, ok_envelope

#: detail 未命中提示名录的显示上限（超限截断+总数注记——大文件不炸报文）。
_DETAIL_NAME_CAP = 30


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（VCD 正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load_document(path: str | Path) -> dict[str, Any]:
    """读文件+解析两步合成（OSError/VcdParseError 由调用方分型捕获）。"""
    return parse_vcd(_read_text(path))


def _full_name(v: dict[str, Any]) -> str:
    """var 层级全名：scope_path 点分 + name（无 scope 时裸名）。"""
    sp = v["scope_path"]
    return f"{sp}.{v['name']}" if sp else str(v["name"])


def parse_vcd_file(path: str | Path) -> dict[str, Any]:
    """VCD 文件 → 全结构化信封（头部+scope 树+vars+事件流+dump 窗口）。

    信封：``{"ok": True, "path", "header", "scopes", "vars", "events",
    "dump_regions", "stats", "comments", "warnings"}`` / error 信封
    （errors 恒 list[str]）。纯只读：不落盘、零网络、零真机。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"VCD 文件不可读: {exc}")
    except VcdParseError as exc:
        return error_envelope(f"VCD 解析失败: {exc}")
    return ok_envelope(
        path=str(path),
        header=doc["header"],
        scopes=doc["scopes"],
        vars=doc["vars"],
        events=doc["events"],
        dump_regions=doc["dump_regions"],
        stats=doc["stats"],
        comments=doc["comments"],
        warnings=doc["warnings"],
    )


def vcd_report(path: str | Path, *, top_n: int = 10) -> dict[str, Any]:
    """VCD 文件 → 头部+计数+时间跨窗+信号 top 活跃度聚合信封。

    ``top_n`` 透传 :func:`rfauto.core.vcd_parser.vcd_activity_top`
    （活跃度 top 条数，缺省 10；排序=事件数降序、id 升序并列稳定）。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"VCD 文件不可读: {exc}")
    except VcdParseError as exc:
        return error_envelope(f"VCD 解析失败: {exc}")
    return ok_envelope(
        path=str(path),
        header=doc["header"],
        stats=doc["stats"],
        time_windows=vcd_time_windows(doc),
        activity_top=vcd_activity_top(doc, top_n=top_n),
        warnings=doc["warnings"],
    )


def vcd_var_detail(
    path: str | Path, name: str, *, scope: str | None = None
) -> dict[str, Any]:
    """VCD 文件 → 按名查询 var 事件流信封（可选 scope 前缀过滤）。

    ``name`` 不存在（或 scope 过滤后无命中）→ error 信封（可用 var 全名
    清单随报文给出，显示上限 30 条+总数注记——消费方不猜）；命中 →
    ``{"ok": True, "path", "name", "scope", "matches", "n_matches",
    "warnings"}``，同名多 scope 全列如实。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"VCD 文件不可读: {exc}")
    except VcdParseError as exc:
        return error_envelope(f"VCD 解析失败: {exc}")
    matches = vcd_var_lookup(doc, name, scope=scope)
    if not matches:
        all_names = [_full_name(v) for v in doc["vars"].values()]
        shown = all_names[:_DETAIL_NAME_CAP]
        suffix = ""
        if len(all_names) > _DETAIL_NAME_CAP:
            suffix = f" …共 {len(all_names)} 个"
        hint = ", ".join(shown) + suffix if shown else "无"
        return error_envelope(
            f"信号 {name!r} 不存在"
            + (f"（scope={scope!r} 过滤后无命中）" if scope else "")
            + f"（可用: {hint}）")
    return ok_envelope(
        path=str(path),
        name=name,
        scope=scope,
        matches=matches,
        n_matches=len(matches),
        warnings=doc["warnings"],
    )
