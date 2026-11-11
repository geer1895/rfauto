"""原理图/BOM 实体级读入口（T-Q6，aurora_q Q-W7-1）——零生成、纯消费面。

两个读入口（实体级清单语义，非统计速览）：

1. :func:`schematic_overview`——``.kicad_sch`` s-expr 直读：图纸参数
   （version/generator/uuid/paper 原文）、符号实例清单（per-instance
   ref/value/lib_id/footprint/at）、网络连通（**复用 T-Q22 生成器的
   :func:`rfauto.adapters.kicad_sch_gen.readback_nets`**——union-find 按坐
   标连通，勿在本模块重写）、文本标签计数。**零生成**：本模块只读，与
   生成器（kicad_sch_service 渲染面）是分离的消费侧。

2. :func:`bom_overview`——``.kicad_pcb`` s-expr 直读（复用
   :func:`rfauto.adapters.kicad_sch_gen.parse_sexpr` 同一解析路径）：BOM
   语义聚合——per-ref 字段（value/footprint/lib_id）+ 按 value 分组计数 +
   总数。与 format_overview 的 kicad_pcb 速览互补（见下"关系判定"）。

与 format_overview_service 的关系判定（T-Q6 任务书要求落报告）：
    format_overview 的 kicad_pcb loader=**统计摘要**（n_footprints/n_tracks
    /层表/bbox 速览，footprints 只随 entities 概览）；T-Q6=**实体级读入
    口**（per-ref 字段聚合、per-instance 清单、per-net 连通集）——粒度与
    契约（schema_version 独立升位）都不同，故立独立 service 而非给冻结面
    （Q-W6-3 收官）扩 kind。format_overview 缺 schematic/gerber kind 之事
    如实登记不修（禁改清单）。

解析边界（如实声明，#331 族：观察工具不美化）：
- 嵌套/非常规位置的 footprint/symbol 不扫（根节点直系子节点口径，与
  format_overview 同）；未识别的顶层节点跳过，不猜语义；
- 连通性消费**局部 label**（生成器语义=同名 label 连通）；
  global_label/hierarchical_label 如实计数、不进连通（外部文件此类引脚
  会落 ``unnamed_pins``——如实信号非缺陷）；
- 实例 angle≠0 时 readback_nets 抛 ValueError（T-Q22 生成器边界：自产
  恒 0）——本入口原样转错误信封，不静默跳过；
- BOM 过滤语义（DNP/exclude_from_bom 属性）**不判**——原文直读字段清单，
  过滤是消费方职责（复杂语义登记边界，任务书"最小读入口"口径）；
- ``Reference`` 缺失的 footprint 以空串为键如实入列并计数，不猜名。

确定性：全部字段来自文件原文直读/声明聚合（计数直读+bbox 类聚合零算术
派生，铁律 7）；同输入两次调用结构逐键同（测试钉双跑逐字节同）。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from rfauto.adapters.kicad_sch_gen import parse_sexpr, readback_nets
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "BOM_OVERVIEW_SCHEMA_VERSION",
    "SCHEMATIC_OVERVIEW_SCHEMA_VERSION",
    "bom_overview",
    "schematic_overview",
]

#: schematic_overview 信封 schema 版本（字段只增不改形——只增纪律）。
SCHEMATIC_OVERVIEW_SCHEMA_VERSION = "1.0"
#: bom_overview 信封 schema 版本。
BOM_OVERVIEW_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# 私有 s-expr 访问助手（与 format_overview 同款口径的模块内私有副本；
# 三行级小助手不值得跨 service 共享耦合）
# ---------------------------------------------------------------------------


def _node(node: list, tag: str) -> list | None:
    for child in node[1:]:
        if isinstance(child, list) and child and child[0] == tag:
            return child
    return None


def _nodes(node: list | None, tag: str) -> list[list]:
    if node is None:
        return []
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == tag]


def _token(node: list | None, idx: int) -> str | None:
    if node is None or len(node) <= idx:
        return None
    return str(node[idx])


def _prop_value(node: list, name: str) -> str:
    for p in _nodes(node, "property"):
        if len(p) > 2 and p[1] == name:
            return str(p[2])
    return ""


def _read_root(path: Path, expect_root: str) -> tuple[list | None, str, list[str]]:
    """读文件+parse_sexpr+根节点校验 → (root 或 None, text, errors)。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, "", [f"文件不可读: {path}（{exc}）"]
    try:
        top = parse_sexpr(text)
    except ValueError as exc:
        return None, text, [f"s-expr 解析失败: {exc}"]
    if (len(top) != 1 or not isinstance(top[0], list) or not top[0]
            or top[0][0] != expect_root):
        return None, text, [f"根表达式不是 ({expect_root} ...)——非目标格式或文件损坏"]
    return top[0], text, []


# ---------------------------------------------------------------------------
# 读入口 1：.kicad_sch 实体级速览
# ---------------------------------------------------------------------------


def schematic_overview(sch_path: str | Path) -> dict[str, Any]:
    """``.kicad_sch`` → 实体级读信封（图纸参数/实例清单/网络连通/标签计数）。

    Returns:
        envelope：``{ok, kind: "kicad_sch", path, schema_version,
        sheet, instances, nets, unnamed_pins, labels, stats}``；

        - ``sheet``：version/generator/generator_version/uuid/paper
          （s-expr token 原文，缺项 None）；
        - ``instances``：符号实例清单（文件序）``{ref, value, lib_id,
          footprint, at}``——属性与坐标 token 原文直读，缺失=空串（不猜）；
        - ``nets``：net 名 → ``[[ref, pin], ...]`` 排序去重（复用
          readback_nets 的 union-find 连通，见模块 docstring 边界）；
        - ``unnamed_pins``：连通但无 label 的引脚（自产文件恒空——
          生成器每根引脚都带 label；非空即外部文件/生成器 bug 信号）；
        - ``labels``：``{n_local, n_global, n_hierarchical,
          local_by_name}``（local_by_name 键排序；连通只消费 local）；
        - ``stats``：n_instances/n_lib_symbols/n_wires/n_nets/
          n_unnamed_pins/n_labels_local 计数直读。

    坏文件（不可读/括号不配对/根节点不符/angle≠0 实例）→ error 信封。
    """
    path = Path(sch_path)
    root, text, errors = _read_root(path, "kicad_sch")
    if root is None:
        return error_envelope(errors, kind="kicad_sch", path=str(path))

    sheet = {
        "version": _token(_node(root, "version"), 1),
        "generator": _token(_node(root, "generator"), 1),
        "generator_version": _token(_node(root, "generator_version"), 1),
        "uuid": _token(_node(root, "uuid"), 1),
        "paper": _token(_node(root, "paper"), 1),
    }

    instances: list[dict[str, Any]] = []
    for sym in _nodes(root, "symbol"):
        at = _node(sym, "at")
        instances.append({
            "ref": _prop_value(sym, "Reference"),
            "value": _prop_value(sym, "Value"),
            "lib_id": _token(_node(sym, "lib_id"), 1) or "",
            "footprint": _prop_value(sym, "Footprint"),
            "at": [x for x in (_token(at, 1), _token(at, 2))
                   if x is not None],
        })

    try:
        rb = readback_nets(text)
    except ValueError as exc:
        return error_envelope([f"连通性回读失败: {exc}"], kind="kicad_sch",
                              path=str(path))

    local_labels = _nodes(root, "label")
    local_by_name = Counter(
        str(lab[1]) for lab in local_labels if len(lab) > 1)
    labels = {
        "n_local": len(local_labels),
        "n_global": len(_nodes(root, "global_label")),
        "n_hierarchical": len(_nodes(root, "hierarchical_label")),
        "local_by_name": dict(sorted(local_by_name.items())),
    }
    stats = {
        "n_instances": len(instances),
        "n_lib_symbols": len(_nodes(_node(root, "lib_symbols"), "symbol")),
        "n_wires": len(_nodes(root, "wire")),
        "n_nets": len(rb.nets),
        "n_unnamed_pins": len(rb.unnamed_pins),
        "n_labels_local": labels["n_local"],
    }
    return ok_envelope(
        kind="kicad_sch",
        path=str(path),
        schema_version=SCHEMATIC_OVERVIEW_SCHEMA_VERSION,
        sheet=sheet,
        instances=instances,
        nets={name: [[ref, pin] for ref, pin in pins]
              for name, pins in rb.nets.items()},
        unnamed_pins=[[ref, pin] for ref, pin in rb.unnamed_pins],
        labels=labels,
        stats=stats,
    )


# ---------------------------------------------------------------------------
# 读入口 2：BOM 清单（.kicad_pcb → per-ref 字段聚合）
# ---------------------------------------------------------------------------


def bom_overview(pcb_path: str | Path) -> dict[str, Any]:
    """``.kicad_pcb`` → BOM 语义聚合信封（per-ref 字段+按 value 分组+总数）。

    字段映射（声明，零猜测）：
        - ``value`` = footprint 节点 ``Value`` 属性原文（缺失=空串）；
        - ``lib_id`` = footprint 节点首 token（``(footprint "Lib:Name"``）；
        - ``footprint`` = ``Footprint`` 属性原文；.kicad_pcb 惯例无此属性
          → 回退 lib_id（板面 footprint 指派即节点 lib_id——映射声明于此，
          非几何/数值派生）。

    Returns:
        envelope：``{ok, kind: "bom", path, schema_version, per_ref,
        by_value, n_components, n_duplicate_refs, n_missing_reference}``；

        - ``per_ref``：``{ref: {value, footprint, lib_id}}``（文件序；
          同 ref 重复=首个保留+计数，不覆盖）；
        - ``by_value``：``{value: count}``（键排序；空 value 以空串键入组）；
        - ``n_duplicate_refs``/``n_missing_reference``：诊断计数直读。

    解析边界：DNP/exclude_from_bom 等 BOM 过滤属性**不判**（消费方过滤，
    模块 docstring）；只扫根节点直系 footprint（与 format_overview 同口径）。
    """
    path = Path(pcb_path)
    root, _text, errors = _read_root(path, "kicad_pcb")
    if root is None:
        return error_envelope(errors, kind="bom", path=str(path))

    per_ref: dict[str, dict[str, str]] = {}
    by_value: Counter[str] = Counter()
    n_duplicate_refs = 0
    n_missing_reference = 0
    for fp in _nodes(root, "footprint"):
        ref = _prop_value(fp, "Reference")
        value = _prop_value(fp, "Value")
        lib_id = _token(fp, 1) or ""
        if not ref:
            n_missing_reference += 1
        if ref in per_ref:
            n_duplicate_refs += 1
            continue
        per_ref[ref] = {
            "value": value,
            "footprint": _prop_value(fp, "Footprint") or lib_id,
            "lib_id": lib_id,
        }
        by_value[value] += 1
    return ok_envelope(
        kind="bom",
        path=str(path),
        schema_version=BOM_OVERVIEW_SCHEMA_VERSION,
        per_ref=per_ref,
        by_value=dict(sorted(by_value.items())),
        n_components=len(per_ref),
        n_duplicate_refs=n_duplicate_refs,
        n_missing_reference=n_missing_reference,
    )
