"""SPICE 网表深度解析服务（Q-X33 aurora_q T-Q22——JSON 进出规则 4 单源）。

core.spice_netlist_parser（三格式统一五维度解析纯函数）的服务包装：
文件/文本入参 → 信封（service/envelope 三构造器；AU-2 契约）出。

- ``parse_netlist_file``：网表文件路径 → ok/error 信封（文件 IO 收敛在
  本层——core 纯函数零文件依赖）；
- ``parse_netlist_text``：网表文本 → 信封（程序化调用面/测试钉同源）。

信封字段（ok=True）：``schema``/``flavor``（解析实际采用）/``flavor_
requested``/``flavor_detected``/``path``（text 入口恒 None）/``title``/
五维度 ``elements``/``subckts``/``controls``/``models``/``topology``/
``summary``/``structural_errors``/``warnings``。``include_topology=False``
时 ``topology=None`` 且 summary 的拓扑派生字段（n_nodes/mna_size 族）=
None（如实空缺非 0——0 是合法计数，缺失哨兵恒 None，#117 同族纪律）。

失败语义（#105/#122：显式不静默）：
- flavor 词表外 → error 信封（CLI 层对 ``--flavor`` 先行 usage 校验
  exit 2，本层为直调面兜底同口径）；

- 文件不存在/不可读 → error 信封（零静默降级）；
- 解析本体 fail-soft：结构错误进 ``structural_errors`` 不失败（解析器
  契约——诊断面如实回传，调用方按需判定）。

只消费既有 validate 面（Q-X20 冻结 spicy_service/fit_macromodel 不触碰
——本模块零 import core.macromodel，解析器独立成面）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.parser_diagnostics import diagnostics_summary
from rfauto.core.spice_netlist_parser import (
    FLAVOR_AUTO,
    PARSER_SCHEMA_VERSION,
    normalize_flavor,
    parse_spice_netlist_text,
)
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "PARSER_SCHEMA_VERSION",
    "SPICE_FLAVORS",
    "parse_netlist_file",
    "parse_netlist_text",
]

#: flavor 词表（CLI --flavor usage 校验与本层兜底单源；与
#: core.spice_netlist_parser._KNOWN_FLAVORS 同口径）。
SPICE_FLAVORS = (FLAVOR_AUTO, "ngspice", "hspice", "spectre")

#: include_topology=False 时 summary 中置 None 的拓扑派生字段（缺失哨兵
#: 恒 None 非 0——0 是合法计数；#117 同族纪律单源）。
_TOPOLOGY_SUMMARY_KEYS = (
    "n_nodes",
    "n_non_ground_nodes",
    "mna_size",
    "n_x_instances",
)


def parse_netlist_text(
    text: str,
    flavor: str = FLAVOR_AUTO,
    *,
    include_topology: bool = True,
) -> dict[str, Any]:
    """网表文本 → 解析信封（ok/error 同构；程序化调用面单源）。"""
    try:
        flavor_norm = normalize_flavor(flavor)
    except ValueError as exc:
        return error_envelope([str(exc)], flavor_requested=str(flavor))
    parsed = parse_spice_netlist_text(text, flavor_norm)
    return _ok_envelope_from_parsed(parsed, path=None,
                                    include_topology=include_topology)


def parse_netlist_file(
    path: str | Path,
    flavor: str = FLAVOR_AUTO,
    *,
    include_topology: bool = True,
) -> dict[str, Any]:
    """网表文件 → 解析信封（文件 IO 收敛本层；core 纯函数零文件依赖）。

    读取口径：utf-8 + errors="replace"（SPICE 网表通常 ASCII；非 UTF-8
    字节如实替换不炸——与 core.macromodel.validate_spice_subcircuit 同
    口径）。目录/不存在 → error 信封零静默。
    """
    p = Path(path)
    try:
        flavor_norm = normalize_flavor(flavor)
    except ValueError as exc:
        return error_envelope([str(exc)], path=str(p),
                              flavor_requested=str(flavor))
    if not p.is_file():
        return error_envelope([f"网表文件不存在: {p}"], path=str(p),
                              flavor_requested=flavor_norm)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return error_envelope([f"网表文件不可读: {exc}"], path=str(p),
                              flavor_requested=flavor_norm)
    parsed = parse_spice_netlist_text(text, flavor_norm)
    return _ok_envelope_from_parsed(parsed, path=str(p),
                                    include_topology=include_topology)


def _ok_envelope_from_parsed(
    parsed: dict[str, Any],
    *,
    path: str | None,
    include_topology: bool,
) -> dict[str, Any]:
    """解析结果 → ok 信封（include_topology=False 时拓扑字段如实空缺）。"""
    summary = dict(parsed["summary"])
    topology: Any = parsed["topology"]
    if not include_topology:
        topology = None
        for key in _TOPOLOGY_SUMMARY_KEYS:
            summary[key] = None
    return ok_envelope(
        schema=parsed["schema"],
        parser_schema_version=PARSER_SCHEMA_VERSION,
        path=path,
        flavor=parsed["flavor"],
        flavor_requested=parsed["flavor_requested"],
        flavor_detected=parsed["flavor_detected"],
        title=parsed["title"],
        elements=parsed["elements"],
        subckts=parsed["subckts"],
        controls=parsed["controls"],
        models=parsed["models"],
        topology=topology,
        summary=summary,
        structural_errors=parsed["structural_errors"],
        warnings=parsed["warnings"],
        diagnostics=parsed["diagnostics"],
        diagnostics_summary=diagnostics_summary(parsed["diagnostics"]),
        include_topology=bool(include_topology),
    )
