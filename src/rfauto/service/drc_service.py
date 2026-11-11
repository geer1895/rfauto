"""DRC 解析与校验服务包装（aurora_q Q-X48，2026-11-07）。

:mod:`rfauto.core.drc_parser`（单源解析+判定内核）的规则 4 JSON 进出
薄包装——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁
裸 dict），零数值逻辑（词法/单位归一/方向判定/RF 检查全在 core 确定性
内核；铁律 7）。

两函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_drc_file`：规则文件全结构化解析（format/rules/groups/
  metadata/warnings）——``drc parse`` 叶 ``--json`` 信封即本函数全量
  返回；
- :func:`validate_design_file`：design JSON × 规则集校验（violations/
  summary/verdict）——规则缺省链=``--rules <file>``；未给规则且
  ``rf=True`` 走 core :data:`DEFAULT_RF_RULESET` 内置缺省档；两者皆缺
  = error 信封（无规则可校验是调用错误，不是 skipped）。``rf=False``
  时规则文件里的 RF 类型规则不判（RF 检查未启用 warning，如实计数）。

错误归一：文件不可读/解码失败/JSON 坏/词法或结构违规（DrcParseError）
→ error 信封（errors 恒 list[str]），CLI 层 exit 1。解码链=utf-8 优先、
Latin-1 兜底（供应商导出偶发高位字节不炸读取——liberty/sdc_service
同款先例）。纯只读：不落盘、零网络、零真机。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——hfss_run_report_service 同款先例，新模块
零金快照漂移）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.core.drc_parser import (
    DrcParseError,
    default_rf_rules,
    evaluate_drc_rules,
    extract_design_objects,
    parse_drc_rules,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def parse_drc_file(path: str | Path, *, fmt: str = "auto") -> dict[str, Any]:
    """DRC 规则文件 → 全结构化信封（format/rules/groups/metadata/warnings）。

    信封：``{"ok": True, "path", "format", "rules", "groups",
    "metadata", "warnings"}`` / error 信封（errors 恒 list[str]）。
    """
    try:
        text = _read_text(path)
    except OSError as exc:
        return error_envelope(f"DRC 规则文件不可读: {exc}")
    try:
        doc = parse_drc_rules(text, fmt=fmt)
    except DrcParseError as exc:
        return error_envelope(f"DRC 规则解析失败: {exc}")
    return ok_envelope(
        path=str(path),
        format=doc["format"],
        rules=doc["rules"],
        groups=doc["groups"],
        metadata=doc["metadata"],
        warnings=doc["warnings"],
    )


def validate_design_file(
    design_path: str | Path,
    rules_path: str | Path | None = None,
    *,
    rf: bool = False,
) -> dict[str, Any]:
    """design JSON × 规则集 → 校验信封（violations/summary/verdict）。

    规则缺省链：``rules_path`` 给定→解析该文件（format 自动检测）；
    未给定且 ``rf=True``→core 内置缺省 RF 规则集；两者皆缺→error
    信封。verdict：issues/attention/clean（core 语义，违规不算调用
    失败——ok=True 照常，消费面看 verdict）。
    """
    try:
        design_text = _read_text(design_path)
    except OSError as exc:
        return error_envelope(f"design 文件不可读: {exc}")
    try:
        design = json.loads(design_text)
    except ValueError as exc:
        return error_envelope(f"design JSON 解析失败: {exc}")
    try:
        objects, coord_unit, obj_warnings = extract_design_objects(design)
    except DrcParseError as exc:
        return error_envelope(f"design 结构非法: {exc}")
    rules: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = list(obj_warnings)
    fmt = "-"
    metadata: dict[str, Any] = {}
    groups: list[dict[str, Any]] = []
    if rules_path is not None:
        try:
            rules_text = _read_text(rules_path)
        except OSError as exc:
            return error_envelope(f"DRC 规则文件不可读: {exc}")
        try:
            doc = parse_drc_rules(rules_text)
        except DrcParseError as exc:
            return error_envelope(f"DRC 规则解析失败: {exc}")
        rules = doc["rules"]
        fmt = doc["format"]
        metadata = doc["metadata"]
        groups = doc["groups"]
        warnings.extend(doc["warnings"])
        rules_source = "file"
    elif rf:
        rules = default_rf_rules()
        rules_source = "default_rf"
        metadata = {"source_format": "builtin", "n_rules": len(rules)}
    else:
        return error_envelope(
            "未提供 --rules 且未启用 --rf（无规则可校验——给规则文件或"
            "用内置缺省 RF 规则集）")
    try:
        verdict_doc = evaluate_drc_rules(
            rules, objects, coord_unit=coord_unit, rf_checks=rf)
    except DrcParseError as exc:
        return error_envelope(f"DRC 校验失败: {exc}")
    warnings.extend(verdict_doc["warnings"])
    return ok_envelope(
        design_path=str(design_path),
        rules_path=(str(rules_path) if rules_path is not None else None),
        rules_source=rules_source,
        format=fmt,
        coordinate_unit=coord_unit,
        rules=rules,
        groups=groups,
        metadata=metadata,
        violations=verdict_doc["violations"],
        summary=verdict_doc["summary"],
        verdict=verdict_doc["verdict"],
        warnings=warnings,
    )
