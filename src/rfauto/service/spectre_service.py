"""Spectre 网表解析服务包装（aurora_q 席位 Q-X79，2026-11-08）。

:mod:`rfauto.core.spectre_parser`（单源解析内核）的规则 4 JSON 进出薄包装
——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸 dict），
零数值逻辑（词法与 Spectre 结构语义全在 core 确定性内核；铁律 7）。

三函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_spectre_file`：全结构化解析（parameters 声明表+subckt 层次
  表+顶层实例+选项块/引用登记+层次统计）——``spectre parse --json`` 信封
  即本函数全量返回；
- :func:`spectre_report`：统计聚合视图（器件类型×计数+参数键频次 top+层次
  深度+引用/选项块计数+警告全清单）——``spectre report`` 叶的紧凑消费
  形态；
- :func:`spectre_subckt_detail`：单子电路视图（端口/形参/体内实例+被谁实
  例化+子树片段）——``name`` 不存在 → error 信封（可用子电路名录随
  errors 给出——消费方不猜）。

错误归一：文件不可读 → error 信封（errors 恒 list[str]），CLI 层 exit 1。
解析本体 fail-soft 零致命（空文件/缺 lang 声明/未闭合 subckt 均 warning
不拒——ok 信封照常返回）。解码链=utf-8 优先、Latin-1 兜底（网表正文为
ASCII 口径，工具头注释偶发高位字节不炸读取——sdc_service/verilog 同款
先例）。纯只读：不落盘、零网络、零真机。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——verilog_netlist_service/stil_service 同款
先例，新模块零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.parser_diagnostics import diagnostics_summary
from rfauto.core.spectre_parser import (
    parse_spectre_text,
    spectre_device_inventory,
    spectre_param_refs,
    spectre_subckt_tree,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（网表正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def parse_spectre_file(path: str | Path) -> dict[str, Any]:
    """Spectre 网表文件 → 全结构化信封（schema=spectre_netlist/1.0 全量）。

    信封：``{"ok": True, "path", "lang", "lang_switches", "parameters",
    "subckts", "top_instances", "models", "options_blocks", "includes",
    "foreign_segments", "stats", "warnings", "diagnostics"}``（末键为
    AX-6 附加层，纯增量）/ error 信封（errors 恒 list[str]）。fail-soft
    口径：空文件/缺 lang 声明/结构病态均 warning 不拒（ok=True 照常返
    回）。
    """
    try:
        text = _read_text(path)
    except OSError as exc:
        return error_envelope(f"Spectre 文件不可读: {exc}")
    doc = parse_spectre_text(text)
    return ok_envelope(
        path=str(path),
        lang=doc["lang"],
        lang_switches=doc["lang_switches"],
        parameters=doc["parameters"],
        subckts=doc["subckts"],
        top_instances=doc["top_instances"],
        models=doc["models"],
        options_blocks=doc["options_blocks"],
        includes=doc["includes"],
        foreign_segments=doc["foreign_segments"],
        stats=doc["stats"],
        warnings=doc["warnings"],
        diagnostics=doc["diagnostics"],
    )


def spectre_report(path: str | Path, *, top_keys: int = 20) -> dict[str, Any]:
    """Spectre 网表文件 → 统计聚合信封（``spectre report`` 叶消费形态）。

    聚合：器件类型×计数+master×计数+参数键频次 top（``top_keys`` 上限）+
    子电路层次树摘要（根/深度/未实例化定义）+参数引用点计数+引用/选项块/
    外来段计数+警告全清单（fail-soft 诊断面不截断）。
    """
    try:
        text = _read_text(path)
    except OSError as exc:
        return error_envelope(f"Spectre 文件不可读: {exc}")
    doc = parse_spectre_text(text)
    inventory = spectre_device_inventory(doc, top=top_keys)
    tree = spectre_subckt_tree(doc)
    refs = spectre_param_refs(doc)
    return ok_envelope(
        path=str(path),
        lang=doc["lang"],
        inventory=inventory,
        hierarchy={
            "n_subckts": tree["n_subckts"],
            "max_depth": tree["max_depth"],
            "max_instantiated_depth": tree["max_instantiated_depth"],
            "roots": [r["name"] for r in tree["roots"]],
            "uninstantiated": tree["uninstantiated"],
            "has_cycle": tree["has_cycle"],
        },
        n_parameters=doc["stats"]["n_parameters"],
        param_refs={name: {"n_definitions": len(entry["definitions"]),
                           "n_consumers": entry["n_consumers"]}
                    for name, entry in refs.items()},
        n_includes=len(doc["includes"]),
        n_options_blocks=len(doc["options_blocks"]),
        n_foreign_segments=len(doc["foreign_segments"]),
        stats=doc["stats"],
        warnings=doc["warnings"],
        diagnostics=doc["diagnostics"],
        diagnostics_summary=diagnostics_summary(doc["diagnostics"]),
    )


def spectre_subckt_detail(path: str | Path, name: str) -> dict[str, Any]:
    """单子电路视图信封（端口/形参/体内实例+被谁实例化+子树片段）。

    ``name`` 不存在 → error 信封，可用子电路名录随 errors 文案与结构化
    ``available`` 字段双给（消费方不猜）；存在 → ``{"ok": True, "path",
    "subckt", "n_body_instances", "referenced_subckts", "instantiated_by",
    "subtree", "warnings"}``。
    """
    try:
        text = _read_text(path)
    except OSError as exc:
        return error_envelope(f"Spectre 文件不可读: {exc}")
    doc = parse_spectre_text(text)
    subckts = doc["subckts"]
    if name not in subckts:
        return error_envelope(
            f"子电路 {name!r} 不存在（可用: {', '.join(subckts) or '无'}）",
            available=list(subckts))
    sub = subckts[name]
    referenced: list[str] = []
    for inst in sub["instances"]:
        ref = inst.get("subckt_ref")
        if ref and ref not in referenced:
            referenced.append(ref)
    instantiated_by: list[dict[str, Any]] = []
    for inst in doc["top_instances"]:
        if inst.get("subckt_ref") == name:
            instantiated_by.append({"scope": [], "name": inst["name"], "line_no": inst["line_no"]})
    for sname, other in subckts.items():
        if sname == name:
            continue
        for inst in other["instances"]:
            if inst.get("subckt_ref") == name:
                instantiated_by.append({"scope": [sname], "name": inst["name"],
                                        "line_no": inst["line_no"]})
    tree = spectre_subckt_tree(doc)

    def subtree(node: dict[str, Any]) -> dict[str, Any] | None:
        if node["name"] == name:
            return node
        for child in node["children"]:
            found = subtree(child)
            if found is not None:
                return found
        return None

    fragment: dict[str, Any] | None = None
    for root in tree["roots"]:
        fragment = subtree(root)
        if fragment is not None:
            break
    return ok_envelope(
        path=str(path),
        subckt=sub,
        n_body_instances=len(sub["instances"]),
        referenced_subckts=referenced,
        instantiated_by=instantiated_by,
        subtree=fragment,
        warnings=doc["warnings"],
        diagnostics=doc["diagnostics"],
    )
