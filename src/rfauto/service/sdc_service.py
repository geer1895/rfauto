"""SDC 解析服务包装（aurora_q Q-X36，2026-11-07）。

:mod:`rfauto.core.sdc_parser`（单源解析内核）的规则 4 JSON 进出薄包装
——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸
dict），零数值逻辑（Tcl 词法与 SDC 命令语义全在 core 确定性内核；
铁律 7）。

两函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_sdc_file`：全结构化解析（clocks/delays/paths/
  constraints 八桶/objects/variables/commands/warnings/stats 全结构）
  ——``--json`` 信封即本函数全量返回；
- :func:`list_sdc_commands`：清单只读面（命令名录+计数、时钟名录、
  对象 pattern 计数、变量终态）——``sdc list`` 叶的紧凑消费形态。

错误归一：文件不可读/解码失败/词法或结构违规（SdcParseError）→
error 信封（errors 恒 list[str]），CLI 层 exit 1。解码链=utf-8 优先、
Latin-1 兜底（SDC 正文为 ASCII 口径，供应商头注释偶发高位字节不炸
读取——liberty_service 同款先例）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——hfss_run_report_service 同款先例，新模块
零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.sdc_parser import SdcParseError, parse_sdc
from rfauto.service.envelope import error_envelope, ok_envelope

#: constraints 结构化八桶（schema 钉；与 core._new_document 键集同源）
CONSTRAINT_BUCKETS = (
    "loads",
    "driving_cells",
    "fanout_loads",
    "case_analyses",
    "false_paths",
    "multicycles",
    "clock_latency",
    "clock_uncertainty",
)


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（SDC 正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load_document(path: str | Path) -> dict[str, Any]:
    """读文件+解析两步合成（OSError/SdcParseError 由调用方分型捕获）。"""
    return parse_sdc(_read_text(path))


def parse_sdc_file(path: str | Path) -> dict[str, Any]:
    """SDC 文件 → 全结构化信封（clocks/delays/paths/constraints/…）。

    信封：``{"ok": True, "path", "clocks", "delays", "paths",
    "constraints", "objects", "variables", "commands", "warnings",
    "stats"}`` / error 信封（errors 恒 list[str]）。纯只读：不落盘、
    零网络、零真机。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"SDC 文件不可读: {exc}")
    except SdcParseError as exc:
        return error_envelope(f"SDC 解析失败: {exc}")
    return ok_envelope(
        path=str(path),
        clocks=doc["clocks"],
        delays=doc["delays"],
        paths=doc["paths"],
        constraints=doc["constraints"],
        objects=doc["objects"],
        variables=doc["variables"],
        commands=doc["commands"],
        warnings=doc["warnings"],
        stats=doc["stats"],
    )


def list_sdc_commands(path: str | Path) -> dict[str, Any]:
    """SDC 文件 → 清单只读信封（命令名录+计数/时钟名录/对象/变量）。"""
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"SDC 文件不可读: {exc}")
    except SdcParseError as exc:
        return error_envelope(f"SDC 解析失败: {exc}")
    # 命令名录：按注册序去重 + 逐名计数（sdc list 紧凑清单主面）
    command_names: list[str] = []
    command_counts: dict[str, int] = {}
    for entry in doc["commands"]:
        name = entry["name"]
        if name not in command_counts:
            command_names.append(name)
        command_counts[name] = command_counts.get(name, 0) + 1
    clocks = [
        {
            "name": c["name"],
            "kind": c["kind"],
            "auto_named": c.get("auto_named", False),
            "period": c.get("period"),
            "divide_by": c.get("divide_by"),
            "multiply_by": c.get("multiply_by"),
        }
        for c in doc["clocks"]
    ]
    counts = {
        "commands": len(doc["commands"]),
        "clocks": len(doc["clocks"]),
        "delays": len(doc["delays"]),
        "paths": len(doc["paths"]),
        "warnings": len(doc["warnings"]),
    }
    counts.update(
        {bucket: len(doc["constraints"][bucket]) for bucket in CONSTRAINT_BUCKETS}
    )
    object_counts = {k: len(v) for k, v in doc["objects"].items()}
    return ok_envelope(
        path=str(path),
        command_names=command_names,
        command_counts=command_counts,
        clocks=clocks,
        counts=counts,
        object_counts=object_counts,
        variables=doc["variables"],
        warnings=doc["warnings"],
        stats=doc["stats"],
    )
