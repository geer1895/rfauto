"""IBIS-AMI（.ami）参数文件解析服务包装（aurora_q Q-X86，2026-11-08）。

:mod:`rfauto.core.ibis_ami_parser`（单源解析内核）的规则 4 JSON 进出
薄包装——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁
裸 dict），零数值逻辑（词法/节嵌套/type 分派/bounds 结构化全在 core
确定性内核；铁律 7）。

三函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_ibis_ami_file`：全结构化解析（ami_version/reserved/
  missing_reserved/model_specific/dll_refs/stats/warnings 七键）——
  ``ibis-ami parse --json`` 信封即本函数全量返回；
- :func:`ibis_ami_report`：统计报告面（保留参数行/参数行/DLL·SoC 引用/
  必备键缺失清单+stats）——``ibis-ami report`` 叶的紧凑消费形态；
- :func:`ami_param_detail`：单参数查询面（core :func:`ami_param_lookup`
  同源；Model_Specific 优先、RESERVED 回落）——未命中 → error 信封
  **带可用参数清单**（消费方不猜）。

错误归一：文件不可读/解码失败/文件身份级致命（AmiParseError——空文件/
仅注释空白）→ error 信封（errors 恒 list[str]），CLI 层 exit 1；解析
期病态（括号失衡/type 非法等）在 core 已降级为 warnings，不走 error。
解码链=utf-8-sig 优先（吞 BOM）、Latin-1 兜底（AMI 正文 ASCII 口径，
供应商文件头注释偶发高位字节不炸读取——ibis_service 同款先例）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——ibis_service 同款先例，新模块零金快照
漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.ibis_ami_parser import (
    AmiParseError,
    ami_param_lookup,
    parse_ami,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8-sig 优先（吞 BOM），Latin-1 兜底（正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load_document(path: str | Path) -> dict[str, Any]:
    """读文件+解析两步合成（OSError/AmiParseError 由调用方分型捕获）。"""
    return parse_ami(_read_text(path))


def parse_ibis_ami_file(path: str | Path) -> dict[str, Any]:
    """AMI 参数文件 → 全结构化信封（core :func:`parse_ami` 七键直出）。

    信封：``{"ok": True, "path", "ami_version", "reserved",
    "missing_reserved", "model_specific", "dll_refs", "stats",
    "warnings"}`` / error 信封（errors 恒 list[str]）。纯只读：不落盘、
    零网络、零真机。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"AMI 文件不可读: {exc}")
    except AmiParseError as exc:
        return error_envelope(f"AMI 解析失败: {exc}")
    return ok_envelope(
        path=str(path),
        ami_version=doc["ami_version"],
        reserved=doc["reserved"],
        missing_reserved=doc["missing_reserved"],
        model_specific=doc["model_specific"],
        dll_refs=doc["dll_refs"],
        stats=doc["stats"],
        warnings=doc["warnings"],
    )


def ibis_ami_report(path: str | Path) -> dict[str, Any]:
    """AMI 参数文件 → 统计报告信封（保留参数行+参数行+DLL·SoC 引用+
    必备键缺失清单；行视图=core 结构记录的扁平投影，零二次解析）。

    ``ibis-ami report`` 叶的紧凑消费形态：reserved 行 ``{name, value}``；
    参数行 ``{name, describe, type, default_raw, default_typed,
    bounds_raw, usage}``（嵌套 bounds 结构体不落报告行——raw 恒在
    bounds_raw，结构体走 parse 叶全量信封）。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"AMI 文件不可读: {exc}")
    except AmiParseError as exc:
        return error_envelope(f"AMI 解析失败: {exc}")
    reserved_rows = [
        {"name": k, "value": v} for k, v in doc["reserved"].items()
    ]
    model_rows = [
        {
            "name": name,
            "describe": rec.get("describe"),
            "type": rec.get("type"),
            "default_raw": rec.get("default_raw"),
            "default_typed": rec.get("default_typed"),
            "bounds_raw": rec.get("bounds_raw"),
            "usage": rec.get("usage"),
        }
        for name, rec in doc["model_specific"].items()
    ]
    return ok_envelope(
        path=str(path),
        ami_version=doc["ami_version"],
        stats=doc["stats"],
        reserved_rows=reserved_rows,
        model_rows=model_rows,
        dll_refs=doc["dll_refs"],
        missing_reserved=doc["missing_reserved"],
        warnings=doc["warnings"],
    )


def ami_param_detail(path: str | Path, name: str) -> dict[str, Any]:
    """AMI 参数文件 → 单参数查询信封（core :func:`ami_param_lookup` 同源）。

    Model_Specific 优先、RESERVED 回落（大小写不敏感）；未命中 →
    error 信封 **附可用参数清单**（model_specific 参数名录+reserved
    键名录，errors 文本与 ``available`` 字段双路给全——消费方不猜）。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"AMI 文件不可读: {exc}")
    except AmiParseError as exc:
        return error_envelope(f"AMI 解析失败: {exc}")
    rec = ami_param_lookup(doc, name)
    if rec is None:
        model_names = sorted(doc["model_specific"])
        reserved_names = sorted(doc["reserved"])
        available = model_names + reserved_names
        return error_envelope(
            f"参数 {name!r} 不存在（可用: "
            f"{', '.join(available) or '无'}）",
            available=available,
        )
    return ok_envelope(
        path=str(path),
        requested=str(name),
        **rec,
    )
