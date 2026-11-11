"""Verilog 网表解析服务包装（aurora_q Q-X47，2026-11-07）。

:mod:`rfauto.core.verilog_netlist_parser`（单源解析内核）的规则 4
JSON 进出薄包装——信封走 :mod:`rfauto.service.envelope` 构造器
（AU-2 契约，禁裸 dict），零数值逻辑（词法与 Verilog 结构语义全在
core 确定性内核；铁律 7）。

三函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_verilog_file`：全结构化解析（modules 五桶+顶层关系面+
  拓扑三件套）——``verilog parse --json`` 信封即本函数全量返回；
- :func:`parse_verilog_module`：单模块视图（``--module`` 过滤面）+
  单模块拓扑（--topology 缺省开）；
- :func:`list_verilog_modules`：清单只读面（模块名录+逐模块计数、
  顶层候选、实例化边、外部单元类型）——``verilog list`` 叶的紧凑
  消费形态。

错误归一：文件不可读/解码失败/词法或结构违规（VerilogParseError）→
error 信封（errors 恒 list[str]），CLI 层 exit 1。解码链=utf-8 优先、
Latin-1 兜底（Verilog 网表正文为 ASCII 口径，工具头注释偶发高位字节
不炸读取——sdc_service/liberty_service 同款先例）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——sdc_service 同款先例，新模块零金快照
漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.verilog_netlist_parser import (
    VerilogParseError,
    extract_module_topology,
    parse_verilog,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（Verilog 正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load_document(path: str | Path) -> dict[str, Any]:
    """读文件+解析两步合成（OSError/VerilogParseError 由调用方分型捕获）。"""
    return parse_verilog(_read_text(path))


def parse_verilog_file(
    path: str | Path, *, with_topology: bool = True
) -> dict[str, Any]:
    """Verilog 网表文件 → 全结构化信封（modules 五桶+拓扑三件套）。

    信封：``{"ok": True, "path", "modules", "module_order",
    "top_modules", "instantiations", "external_instance_types",
    "directives", "warnings", "stats", "topology"}``，其中
    ``topology`` = ``{module_name: 拓扑dict}``（``with_topology=False``
    时如实 None——派生字段缺席非零值，spice --no-topology 家法）/
    error 信封（errors 恒 list[str]）。纯只读：不落盘、零网络、零真机。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"Verilog 文件不可读: {exc}")
    except VerilogParseError as exc:
        return error_envelope(f"Verilog 解析失败: {exc}")
    topology: dict[str, Any] | None = None
    if with_topology:
        topology = {
            name: extract_module_topology(doc, name)
            for name in doc["module_order"]
        }
    return ok_envelope(
        path=str(path),
        modules=doc["modules"],
        module_order=doc["module_order"],
        top_modules=doc["top_modules"],
        instantiations=doc["instantiations"],
        external_instance_types=doc["external_instance_types"],
        directives=doc["directives"],
        warnings=doc["warnings"],
        stats=doc["stats"],
        topology=topology,
    )


def parse_verilog_module(
    path: str | Path,
    module: str,
    *,
    with_topology: bool = True,
) -> dict[str, Any]:
    """Verilog 网表文件 → 单模块视图信封（``--module`` 过滤面）。

    ``module`` 不存在 → error 信封（可用模块名录随 errors 给出——
    消费方不猜）。信封键与 :func:`parse_verilog_file` 同形，唯
    ``modules`` 只含目标模块、``topology`` 只含单模块拓扑。
    """
    result = parse_verilog_file(path, with_topology=False)
    if not result.get("ok"):
        return result
    modules = result["modules"]
    if module not in modules:
        return error_envelope(
            f"模块 {module!r} 不存在（可用: {', '.join(result['module_order']) or '无'}）")
    topology = None
    if with_topology:
        topology = extract_module_topology(result, module)
    result["modules"] = {module: modules[module]}
    result["topology"] = topology
    result["module"] = module
    return result


def list_verilog_modules(path: str | Path) -> dict[str, Any]:
    """Verilog 网表文件 → 清单只读信封（模块名录+逐模块计数/顶层候选/
    实例化边/外部单元类型）。

    ``verilog list`` 叶的紧凑消费形态：不做拓扑展开（孤立网/深度是
    parse 叶的活），只给结构盘点五元组。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"Verilog 文件不可读: {exc}")
    except VerilogParseError as exc:
        return error_envelope(f"Verilog 解析失败: {exc}")
    modules_summary = []
    for name in doc["module_order"]:
        body = doc["modules"][name]
        modules_summary.append({
            "name": name,
            "n_ports": len(body["ports"]),
            "n_wires": len(body["wires"]),
            "n_assigns": len(body["assigns"]),
            "n_instances": len(body["instances"]),
            "n_parameters": len(body["parameters"]),
            "n_defparams": len(body["defparams"]),
            "n_warnings": len(body["warnings"]),
            "ansi_ports": body["ansi_ports"],
            "instance_types": sorted({i["type"] for i in body["instances"]}),
        })
    return ok_envelope(
        path=str(path),
        module_names=doc["module_order"],
        modules_summary=modules_summary,
        top_modules=doc["top_modules"],
        instantiations=doc["instantiations"],
        external_instance_types=doc["external_instance_types"],
        directives=doc["directives"],
        warnings=doc["warnings"],
        stats=doc["stats"],
    )
