"""网表语义 overlay 服务包装（aurora_r R-02 席位 AX-2，2026-11-10）。

:mod:`rfauto.core.netlist_semantic_overlay`（单源 overlay 内核）的规
则 4 JSON 进出薄包装——信封走 :mod:`rfauto.service.envelope` 构造器
（AU-2 契约，禁裸 dict 错误路径），零标注逻辑（三件套/覆盖率门全在
core 纯函数；铁律 7 不涉——overlay 只复述解析器既有推断并附出处，零
物理数字产出）。

三函数（SPICE 三格式与 Spectre 原生两解析面各一入口；无 CLI/MCP 叶
——本席任务书未含接线面，挂账处方：CLI 叶走
``rfauto spice parse``/``rfauto spectre parse`` 同款域内自注册形态，
消费本模块函数即可）：

- :func:`netlist_semantic_overlay_text`：网表文本 → overlay 信封
  （flavor 词表校验同 spice 服务口径）；
- :func:`netlist_semantic_overlay_file`：网表文件 → overlay 信封
  （文件 IO 收敛本层；读取口径 utf-8 + errors="replace" 同
  spice_netlist_service）；
- :func:`spectre_semantic_overlay_file`：Spectre 原生文件 → overlay
  信封（解码链 utf-8 优先 Latin-1 兜底同 spectre_service）。

覆盖率门语义：``overlay["coverage"]["low_coverage"]`` 如实标注（缺省
阈值 0.8，``min_coverage`` 参数透传）——门只出标注**不改 ok 语义**
（信封 ok 恒由解析成败决定，low_coverage=True 时 ok 仍 True）。

事实层不可变：overlay 构建纯读 parse 输出（core 内核深比较不变式有
测试钉）；本模块信封同时回传解析 ``diagnostics``（AX-6 结构化层）
供同笔判读。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——spef_service/spectre_service 同款先例，
新模块零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.netlist_semantic_overlay import build_netlist_overlay
from rfauto.core.spectre_parser import parse_spectre_text
from rfauto.core.spice_netlist_parser import (
    FLAVOR_AUTO,
    normalize_flavor,
    parse_spice_netlist_text,
)
from rfauto.service.envelope import error_envelope, ok_envelope

#: 覆盖率门缺省阈值（overlay 内核同款缺省的服务面单源声明）。
DEFAULT_MIN_COVERAGE = 0.8


def netlist_semantic_overlay_text(
    text: str,
    flavor: str = FLAVOR_AUTO,
    *,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> dict[str, Any]:
    """网表文本 → 语义 overlay 信封（程序化调用面单源）。"""
    try:
        flavor_norm = normalize_flavor(flavor)
    except ValueError as exc:
        return error_envelope([str(exc)], flavor_requested=str(flavor))
    parsed = parse_spice_netlist_text(text, flavor_norm)
    overlay = build_netlist_overlay(parsed, min_coverage=min_coverage)
    return ok_envelope(
        path=None,
        flavor=parsed["flavor"],
        flavor_requested=parsed["flavor_requested"],
        flavor_detected=parsed["flavor_detected"],
        overlay=overlay,
        diagnostics=parsed["diagnostics"],
    )


def netlist_semantic_overlay_file(
    path: str | Path,
    flavor: str = FLAVOR_AUTO,
    *,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> dict[str, Any]:
    """网表文件 → 语义 overlay 信封（文件 IO 收敛本层，零静默降级）。"""
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
    overlay = build_netlist_overlay(parsed, min_coverage=min_coverage)
    return ok_envelope(
        path=str(p),
        flavor=parsed["flavor"],
        flavor_requested=parsed["flavor_requested"],
        flavor_detected=parsed["flavor_detected"],
        overlay=overlay,
        diagnostics=parsed["diagnostics"],
    )


def spectre_semantic_overlay_file(
    path: str | Path,
    *,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> dict[str, Any]:
    """Spectre 原生网表文件 → 语义 overlay 信封（fail-soft 同源）。"""
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as exc:
        return error_envelope(f"Spectre 文件不可读: {exc}", path=str(p))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    doc = parse_spectre_text(text)
    overlay = build_netlist_overlay(doc, min_coverage=min_coverage)
    return ok_envelope(
        path=str(p),
        lang=doc["lang"],
        overlay=overlay,
        diagnostics=doc["diagnostics"],
    )
