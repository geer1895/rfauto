"""LEF/DEF 解析服务包装（aurora_q Q-X57，2026-11-07）。

:mod:`rfauto.core.lef_def_parser`（单源解析内核）的规则 4 JSON 进出薄
包装——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸
dict），零数值逻辑（词法与 LEF/DEF 结构语义全在 core 确定性内核；铁律 7）。

三函数（与 CLI 薄壳同源消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_lef_file`：LEF 文件 → 全结构信封（层/via/viarule/site/
  macro+引脚几何+warnings/stats）；
- :func:`parse_def_file`：DEF 文件 → 全结构信封（die/行/轨道/组件/引脚/
  网+走线/特殊网/via+节计数对账+warnings/stats；坐标 DBU 原值+µm 换算）；
- :func:`lef_def_check`：LEF（可多份：科技 LEF+单元 LEF）× DEF 交叉校验
  聚合——单元闭合/网连接度/引脚名对齐三件套+``summary`` 计数+``verdict``。

外加组合薄层 :func:`parse_lef_def`：``lefdef parse`` 叶 ``--lef``（可重复）/
``--def`` 可选组合的拼装（逐文件委托上两函数，零新逻辑——CLI 保持零逻辑
转发，规则 4）。

错误归一：文件不可读（不存在/目录/权限）→ error 信封；**空文件**（无任何
语句：零字节/纯空白/纯注释）→ error 信封；缺输入 → error 信封。errors 恒
list[str]，失败信封与成功信封同键（值置空/None，消费方按同一 schema 读），
CLI 层 exit 1。解码链=utf-8 优先、Latin-1 兜底（verilog/sdc 同款先例）。
内核 fail-soft：内容层面的结构违规不是调用错误——进 warnings 带行号如实
披露，信封 ok=True。

verdict 口径（drc validate 同家法：违规≠调用失败，ok=True 照常）：
``issues``=闭合缺 macro/连接引用未知组件或顶层 PIN/引脚引用未知网/实例
引脚名缺席/top-level 引脚缺席或方向不一致；``attention``=无 issues 但有
悬空网或解析警告；``clean``=全零。驱动/负载方向判定不做（LEF/DEF 无方向
语义网表，宁不报不误报）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——verilog_netlist_service 同款先例，新模块
零金快照漂移）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from rfauto.core.lef_def_parser import (
    def_component_macro_closure,
    def_net_connectivity,
    def_pin_lef_alignment,
    parse_def,
    parse_lef,
)
from rfauto.service.envelope import error_envelope, ok_envelope

#: verdict=issues 的 summary 计数键（任一非零即 issues）。
ISSUE_KEYS = (
    "missing_models",
    "unknown_component_refs",
    "unknown_toplevel_pin_refs",
    "pins_with_unknown_net",
    "unknown_pin_refs",
    "top_level_missing_in_lef",
    "top_level_missing_in_def",
    "direction_mismatches",
)


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（LEF/DEF 正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load(
    path: str | Path, parse_fn: Callable[[str], dict[str, Any]], kind: str
) -> tuple[dict[str, Any] | None, str | None]:
    """读+解析两步合成 → (文档, None) / (None, 错误文本)。

    空文件判据=词法零 token（零字节/纯空白/纯注释）——内核对空文本返回
    全空文档不抛，"空"是服务层的调用错误语义。
    """
    try:
        text = _read_text(path)
    except OSError as exc:
        return None, f"{kind} 文件不可读: {exc}"
    doc = parse_fn(text)
    if doc["stats"]["n_tokens"] == 0:
        return None, f"{kind} 文件为空（无任何语句）: {path}"
    return doc, None


def _as_paths(paths: str | Path | Iterable[str | Path] | None) -> list[str | Path]:
    """路径入参归一为列表（None→[]；单路径→[p]）。"""
    if paths is None:
        return []
    if isinstance(paths, (str, Path)):
        return [paths]
    return list(paths)


def parse_lef_file(path: str | Path) -> dict[str, Any]:
    """LEF 文件 → 全结构信封。

    信封：``{"ok": True, "path", "schema_version", "format": "LEF",
    "version", "bus_bit_chars", "divider_char", "units",
    "manufacturing_grid_um", "layers", "vias", "viarules", "sites",
    "macros", "macro_order", "skipped_blocks", "other_statements",
    "ended", "warnings", "stats"}`` / error 信封（``path``+``format``
    同键）。纯只读：不落盘、零网络、零真机。
    """
    doc, err = _load(path, parse_lef, "LEF")
    if err is not None or doc is None:
        return error_envelope(err or "LEF 解析失败", path=str(path), format="LEF")
    return ok_envelope(path=str(path), **doc)


def parse_def_file(path: str | Path) -> dict[str, Any]:
    """DEF 文件 → 全结构信封。

    信封：``{"ok": True, "path", "schema_version", "format": "DEF",
    "version", "design_name", "divider_char", "bus_bit_chars",
    "technology", "units", "die_area", "rows", "tracks", "components",
    "pins", "nets", "specialnets", "vias", "section_counts",
    "skipped_sections", "other_statements", "ended", "warnings",
    "stats"}``（``*_um`` = ``*_dbu`` ÷ ``units.distance_microns``）/
    error 信封（``path``+``format`` 同键）。
    """
    doc, err = _load(path, parse_def, "DEF")
    if err is not None or doc is None:
        return error_envelope(err or "DEF 解析失败", path=str(path), format="DEF")
    return ok_envelope(path=str(path), **doc)


def parse_lef_def(
    lef_paths: str | Path | Iterable[str | Path] | None = None,
    def_path: str | Path | None = None,
) -> dict[str, Any]:
    """``lefdef parse`` 组合面：``{"ok", "lef": [LEF 信封...], "def": DEF
    信封 | None}``。

    任一文件失败 → error 信封（errors 汇总各文件错误，``lef``/``def``
    键保留逐文件信封供定位）；两类输入都缺 → error 信封。
    """
    paths = _as_paths(lef_paths)
    if not paths and def_path is None:
        return error_envelope("至少给出一个 LEF（--lef）或 DEF（--def）输入",
                              **{"lef": [], "def": None})
    lef_envs = [parse_lef_file(p) for p in paths]
    def_env = parse_def_file(def_path) if def_path is not None else None
    errors = [e for env in [*lef_envs, def_env]
              if env is not None and not env["ok"] for e in env["errors"]]
    if errors:
        return error_envelope(errors, **{"lef": lef_envs, "def": def_env})
    return ok_envelope(**{"lef": lef_envs, "def": def_env})


def lef_def_check(
    lef_paths: str | Path | Iterable[str | Path] | None,
    def_path: str | Path | None,
    *,
    macro: str | None = None,
) -> dict[str, Any]:
    """LEF（可多份）× DEF 交叉校验聚合信封。

    信封：``{"ok": True, "lef_paths", "def_path", "design_name",
    "units": {lef_database_microns: [逐 LEF], def_distance_microns},
    "closure", "connectivity", "alignment", "summary", "verdict",
    "warnings": {"lef": [{path, warnings}], "def": [...]}}``——三件套
    原样来自 core 拓扑函数（:func:`def_component_macro_closure`/
    :func:`def_net_connectivity`/:func:`def_pin_lef_alignment`）；
    ``macro`` 覆盖 top-level 对齐目标（缺省=DEF DESIGN 名）。缺输入/
    文件不可读/空文件 → error 信封（同键置空）。
    """
    paths = _as_paths(lef_paths)
    base: dict[str, Any] = {
        "lef_paths": [str(p) for p in paths],
        "def_path": None if def_path is None else str(def_path),
    }
    empty: dict[str, Any] = {
        "design_name": None, "units": None, "closure": None,
        "connectivity": None, "alignment": None, "summary": None,
        "verdict": None, "warnings": None,
    }
    missing: list[str] = []
    if not paths:
        missing.append("缺 LEF 输入（--lef，可重复给出）")
    if def_path is None:
        missing.append("缺 DEF 输入（--def）")
    if missing:
        return error_envelope(missing, **base, **empty)
    errors: list[str] = []
    lef_docs: list[tuple[str, dict[str, Any]]] = []
    for p in paths:
        doc, err = _load(p, parse_lef, "LEF")
        if err is not None or doc is None:
            errors.append(err or f"LEF 解析失败: {p}")
        else:
            lef_docs.append((str(p), doc))
    def_doc, err = _load(def_path, parse_def, "DEF")
    if err is not None or def_doc is None:
        errors.append(err or f"DEF 解析失败: {def_path}")
    if errors or def_doc is None:
        return error_envelope(errors, **base, **empty)
    docs = [doc for _, doc in lef_docs]
    closure = def_component_macro_closure(def_doc, docs)
    connectivity = def_net_connectivity(def_doc)
    alignment = def_pin_lef_alignment(def_doc, docs, macro=macro)
    top = alignment["top_level"]
    summary = {
        "missing_models": len(closure["missing_models"]),
        "components_missing_model": closure["n_components_missing_model"],
        "unknown_component_refs": len(connectivity["unknown_component_refs"]),
        "unknown_toplevel_pin_refs": len(connectivity["unknown_toplevel_pin_refs"]),
        "pins_with_unknown_net": len(connectivity["pins_with_unknown_net"]),
        "unknown_pin_refs": len(alignment["instance_pins"]["unknown_pin_refs"]),
        "top_level_missing_in_lef": len(top["missing_in_lef"]),
        "top_level_missing_in_def": len(top["missing_in_def"]),
        "direction_mismatches": len(top["direction_mismatches"]),
        "dangling_nets": len(connectivity["dangling_nets"]),
        "parse_warnings": sum(len(doc["warnings"]) for doc in docs)
        + len(def_doc["warnings"]),
    }
    if any(summary[k] for k in ISSUE_KEYS):
        verdict = "issues"
    elif summary["dangling_nets"] or summary["parse_warnings"]:
        verdict = "attention"
    else:
        verdict = "clean"
    return ok_envelope(
        **base,
        design_name=def_doc["design_name"],
        units={
            "lef_database_microns": [doc["units"].get("database_microns")
                                     for doc in docs],
            "def_distance_microns": def_doc["units"]["distance_microns"],
        },
        closure=closure,
        connectivity=connectivity,
        alignment=alignment,
        summary=summary,
        verdict=verdict,
        warnings={
            "lef": [{"path": p, "warnings": doc["warnings"]} for p, doc in lef_docs],
            "def": def_doc["warnings"],
        },
    )
