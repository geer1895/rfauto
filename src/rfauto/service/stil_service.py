"""STIL 测试向量解析服务包装（aurora_q Q-X72 席位，2026-11-08）。

:mod:`rfauto.core.stil_parser`（单源解析内核）的规则 4 JSON 进出薄包装
——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸 dict
错误路径），零数值逻辑（词法、块状态机、WFC 波形表与查询派生全在 core
确定性内核；铁律 7）。

三函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_stil_file`：全结构化解析（头部版本+signals/groups/timing/
  patterns/登记面+统计）——``stil parse --json`` 信封即本函数全量返回；
- :func:`stil_report`：统计+timing/pattern 清单聚合（``stil report
  --json`` 信封；逐 wft 逐 pattern 摘要行）；
- :func:`stil_pattern_detail`：单 pattern 查询（向量平坦清单+Loop/Shift/
  Ann 账目；不存在→error 信封带可用 pattern 清单——消费方不猜）。

错误归一：文件不可读（OSError）/空文件/无 ``STIL <版本>;`` 头/brace 失
衡（报行号）/嵌套超深（StilParseError）→ error 信封（errors 恒
list[str]），CLI 层 exit 1。解码链=utf-8 优先、Latin-1 兜底（STIL 正文
为 ASCII 口径，工具头注释偶发高位字节不炸读取——vcd_service/
verilog_netlist_service 同款先例）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——vcd_service 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.stil_parser import (
    StilParseError,
    parse_stil,
    stil_pattern_vectors,
)
from rfauto.service.envelope import error_envelope, ok_envelope

#: detail 未命中提示名录的显示上限（超限截断+总数注记——大文件不炸报文）。
_DETAIL_NAME_CAP = 30


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（STIL 正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load_document(path: str | Path) -> dict[str, Any]:
    """读文件+解析两步合成（OSError/StilParseError 由调用方分型捕获）。"""
    return parse_stil(_read_text(path))


def parse_stil_file(path: str | Path) -> dict[str, Any]:
    """STIL 文件 → 全结构化信封（版本+signals/groups/timing/patterns）。

    信封：``{"ok": True, "path", "header_version", "signals", "groups",
    "timing", "patterns", "imports", "procedures", "pattern_execs",
    "stats", "warnings"}`` / error 信封（errors 恒 list[str]）。纯只读：
    不落盘、零网络、零真机。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"STIL 文件不可读: {exc}")
    except StilParseError as exc:
        return error_envelope(f"STIL 解析失败: {exc}")
    return ok_envelope(
        path=str(path),
        header_version=doc["header_version"],
        signals=doc["signals"],
        groups=doc["groups"],
        timing=doc["timing"],
        patterns=doc["patterns"],
        imports=doc["imports"],
        procedures=doc["procedures"],
        pattern_execs=doc["pattern_execs"],
        stats=doc["stats"],
        warnings=doc["warnings"],
    )


def stil_report(path: str | Path) -> dict[str, Any]:
    """STIL 文件 → 统计+timing/pattern 清单聚合信封。

    ``timing_summary``=逐 wft ``{"name", "period", "n_waveform_groups"}``；
    ``patterns_summary``=逐 pattern ``{"burst", "name", "wft",
    "n_vectors", "n_loop", "n_shift"}``（burst 插入序+pattern 插入序——
    确定性）；另带 signals/groups 名录与方向/成员数摘要。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"STIL 文件不可读: {exc}")
    except StilParseError as exc:
        return error_envelope(f"STIL 解析失败: {exc}")
    timing_summary = [
        {
            "name": name,
            "period": wft.get("period"),
            "n_waveform_groups": len(wft.get("waveforms") or {}),
        }
        for name, wft in doc["timing"].items()
    ]
    patterns_summary: list[dict[str, Any]] = []
    for burst, bdata in doc["patterns"].items():
        for pname, pentry in bdata["patterns"].items():
            patterns_summary.append({
                "burst": burst,
                "name": pname,
                "wft": pentry["wft"],
                "n_vectors": len(pentry["vectors"]),
                "n_loop": pentry["n_loop"],
                "n_shift": pentry["n_shift"],
            })
    return ok_envelope(
        path=str(path),
        header_version=doc["header_version"],
        stats=doc["stats"],
        signals_summary=[
            {"name": name, "dir": sig["dir"], "wfcs": sig["wfcs"]}
            for name, sig in doc["signals"].items()
        ],
        groups_summary=[
            {"name": name, "members": members}
            for name, members in doc["groups"].items()
        ],
        timing_summary=timing_summary,
        patterns_summary=patterns_summary,
        warnings=doc["warnings"],
    )


def stil_pattern_detail(path: str | Path, pattern: str) -> dict[str, Any]:
    """STIL 文件 → 单 pattern 查询信封（向量平坦清单+账目）。

    ``pattern`` 不存在 → error 信封（可用 pattern 名录随 errors 给出，
    显示上限 30 条+总数注记——消费方不猜）；命中 → ``{"ok": True,
    "path", "pattern", "burst", "wft", "vectors", "n_vectors", "n_loop",
    "n_shift", "anns", "warnings"}``。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"STIL 文件不可读: {exc}")
    except StilParseError as exc:
        return error_envelope(f"STIL 解析失败: {exc}")
    vectors = stil_pattern_vectors(doc, pattern)
    if vectors is None:
        all_names = [
            f"{burst}.{pname}" if burst else pname
            for burst, bdata in doc["patterns"].items()
            for pname in bdata["patterns"]
        ]
        shown = all_names[:_DETAIL_NAME_CAP]
        suffix = ""
        if len(all_names) > _DETAIL_NAME_CAP:
            suffix = f" …共 {len(all_names)} 个"
        hint = ", ".join(shown) + suffix if shown else "无"
        return error_envelope(
            f"Pattern {pattern!r} 不存在（可用: {hint}）")
    hit_burst = ""
    hit_entry: dict[str, Any] = {}
    for burst, bdata in doc["patterns"].items():
        if pattern in bdata["patterns"]:
            hit_burst = burst
            hit_entry = bdata["patterns"][pattern]
            break
    return ok_envelope(
        path=str(path),
        pattern=pattern,
        burst=hit_burst,
        wft=hit_entry.get("wft"),
        vectors=vectors,
        n_vectors=len(vectors),
        n_loop=hit_entry.get("n_loop", 0),
        n_shift=hit_entry.get("n_shift", 0),
        anns=hit_entry.get("anns", []),
        warnings=doc["warnings"],
    )
