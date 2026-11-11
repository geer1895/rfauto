"""网表语义 overlay 层（aurora_r R-02 席位 AX-2，2026-11-10）。

netlist-crawler（MIT，思想级重写零搬运——本实现未读其源码，仅按调研
纪要的机制要点自写）的**注释 overlay 三件套**思想：每个推断结论携带
``{source(规则 id), confidence(high/medium/low), evidence(行号+原文
片段)}`` 三件套；**事实层不可变**（本模块纯读 parse 输出 dict，零改
写零追加——doc 深比较不变式有测试钉）；覆盖率门如实标注 low_coverage
（不改 ok 语义）。

覆盖面（**仓内已有推断多少算多少，零新造语义检测器**）：

SPICE 三格式（:mod:`rfauto.core.spice_netlist_parser` 输出）：

- ``spice.kind.*``：器件 kind 推断——SPICE 两方言=首字母闭表（high）；
  Spectre 形态按解析器判定序复判 provenance（subckt 引用=high / 内建
  master 表=high / model 关键词启发=medium / 首字母兜底与 N 兜底=
  low）；
- ``spice.node.ground_alias``：接地别名归一（0/gnd/gnd! 大小写不敏感
  →0；从 raw 行重推别名 token，避免把字面 ``0`` 误报为归一）；
- ``spice.hierarchy.x_reference``：X 实例→子电路引用边（本文件命中=
  high；外部未定义=low——名称推断外部定义未知）；
- ``spice.topology.single_connection_suspicion``：顶层单连接节点浮空
  嫌疑（解析层判据非电气结论——low，宁多报不误报同解析器口径）；
- ``spice.source.spec_keyword``：V/I 源规格关键字（DC/SIN/PULSE…，
  显式关键字=high）；
- ``spice.flavor.heuristic_detection``：auto 模式 flavor 判定本身是推
  断（medium；行锚不可得 evidence=None——覆盖率门如实降位）。

Spectre 原生（:mod:`rfauto.core.spectre_parser` 输出）：

- ``spectre.type.*``：device_type 判定序复判（master 命中本文件
  subckt=high / X 首字母惯例=medium / 首字母闭表=high / unknown 桶=
  low）+ ``spectre.type.model_ref``（显式 model 成员=high）；
- ``spectre.ref.word_boundary_match``：参数引用点（词边界文本匹配、
  作用域遮蔽不解析——medium）；
- ``spectre.hierarchy.cycle_detection``：层次环检测（全图判定，
  evidence=None——覆盖率门如实降位）。

**模拟语义规则缺席如实声明**：netlist-crawler 的差分对/电流镜/
cascode/有源负载/尾电流源五类图模式检测器 rfauto **零实现**——本批
不新造（任务口径），:data:`ABSENT_SEMANTIC_RULES` 如实挂在
``rule_inventory`` 供后续席位挂账。

覆盖率门（报告面单源）：``覆盖率 = evidence 行锚在档的结论数 / 结论
总数``；无行锚结论（flavor 统计判定/层次环全图判定）计入总数不入标
注数——门如实反映证据完备度；``low_coverage = ratio < min_coverage``
（缺省 0.8）；结论总数为零 → ratio=None、low_coverage=False（无可覆
盖面，空缺非零——#117 哨兵口径）。门只出标注**不改 ok 语义**（信封
层 ok 恒由解析成败决定）。

confidence 分档（单源）——high=闭表成员/显式声明命中；medium=确定性
启发（关键词/统计判定/词边界文本匹配）；low=兜底桶/外部未定义/嫌疑
面。本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——spef_parser/spectre_parser 同款先例）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.spectre_parser import (
    DEVICE_TYPE_UNKNOWN,
    spectre_param_refs,
)
from rfauto.core.spice_netlist_parser import (
    _SPECTRE_MASTER_KIND,
    FLAVOR_SPECTRE,
    GROUND_ALIASES,
)

#: overlay 输出 schema 版本（键集/字段形状变更时升位）。
OVERLAY_SCHEMA_VERSION = "1.0"

#: confidence 分档闭集（单源）。
CONFIDENCE_LEVELS = ("high", "medium", "low")

#: 模拟语义规则缺席清单（netlist-crawler 五类图模式检测器 rfauto 零实
#: 现——如实挂账，本批零新造；后续席位实现后从此处移出）。
ABSENT_SEMANTIC_RULES: tuple[str, ...] = (
    "differential_pair",
    "current_mirror",
    "cascode",
    "active_load",
    "tail_current_source",
)

def _annotation(
    target_kind: str,
    target_id: str,
    scope: list[str],
    line: int | None,
    snippet: str | None,
    source: str,
    confidence: str,
    conclusion: dict[str, Any],
) -> dict[str, Any]:
    """单条 overlay 标注（三件套标准形状；事实层零触碰）。"""
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(
            f"confidence={confidence!r} 不在分档 {list(CONFIDENCE_LEVELS)}")
    return {
        "target": {"kind": target_kind, "id": target_id, "scope": scope},
        "conclusion": conclusion,
        "source": source,
        "confidence": confidence,
        "evidence": {"line": line, "snippet": snippet},
    }


def _coverage(annotations: list[dict[str, Any]],
              min_coverage: float) -> dict[str, Any]:
    """覆盖率门（报告面单源）：行锚在档结论数/结论总数；门只标注不改语义。"""
    total = len(annotations)
    annotated = sum(
        1 for a in annotations if a["evidence"]["line"] is not None)
    ratio: float | None = None if total == 0 else annotated / total
    return {
        "conclusion_total": total,
        "annotated": annotated,
        "ratio": ratio,
        "threshold": float(min_coverage),
        "low_coverage": bool(ratio is not None and ratio < min_coverage),
    }


def _rule_inventory(annotations: list[dict[str, Any]]) -> dict[str, Any]:
    """规则清单（按 source 计数+缺席语义规则如实声明——确定性排序）。"""
    by_source: dict[str, int] = {}
    for a in annotations:
        by_source[a["source"]] = by_source.get(a["source"], 0) + 1
    return {
        "by_source": dict(sorted(by_source.items())),
        "absent_semantic_rules": list(ABSENT_SEMANTIC_RULES),
    }


# --------------------------------------------------------------------------- #
# SPICE 三格式 overlay
# --------------------------------------------------------------------------- #


def _spice_element_kind_rule(el: dict[str, Any], flavor: str,
                             model_names: set[str]) -> tuple[str, str]:
    """器件 kind 推断 provenance 复判（按解析器判定序；返回 (source, confidence)）。"""
    kind = el["kind"]
    if kind == "X":
        return "spice.kind.subckt_reference", "high"
    if flavor != FLAVOR_SPECTRE:
        return "spice.kind.first_letter_table", "high"
    # Spectre 形态：master 解析序复判（subckt → model → 内建表 → 首字母 → N）
    model = el.get("model")
    if model is not None and model in model_names:
        return "spectre.kind.model_keyword", "medium"
    if model is not None and model.lower() in _SPECTRE_MASTER_KIND:
        return "spectre.kind.master_builtin_map", "high"
    if model is not None:
        return "spectre.kind.first_letter_fallback", "low"
    return "spectre.kind.unknown_fallback", "low"


def _ground_alias_tokens(el: dict[str, Any]) -> list[str]:
    """从 raw 行重推被归一的接地别名 token（位置对齐节点区；诚实放弃形态）。

    节点数=归一后 ``nodes`` 长度（归一是一对一改名，计数不变）；取元件
    名后 ``n`` 个词为节点区。括号形态（``X1 (a gnd) sub``）词位漂移——
    如实放弃重推（宁缺不误报）；``0`` 字面不算别名归一。
    """
    raw = el.get("raw") or ""
    tokens = raw.split()
    n = len(el.get("nodes") or [])
    if n == 0 or len(tokens) < 1 + n:
        return []
    head = tokens[:1 + n]
    if any("(" in t or ")" in t for t in head):
        return []
    region = [t.strip(",") for t in tokens[1:1 + n]]
    return [t for t in region if t and t.lower() in GROUND_ALIASES and t != "0"]


def _overlay_spice(doc: dict[str, Any],
                   min_coverage: float) -> dict[str, Any]:
    """SPICE 三格式 parse 输出 → overlay（纯读；事实层不可变）。"""
    flavor = doc["flavor"]
    model_names = {m["name"] for m in doc["models"] if m.get("name")}
    subckt_names = {s["name"] for s in doc["subckts"]}
    annotations: list[dict[str, Any]] = []
    for el in doc["elements"]:
        scope = list(el.get("scope") or [])
        line = el.get("line_no")
        snippet = el.get("raw")
        # 器件 kind 推断（每元件一结论）
        source, confidence = _spice_element_kind_rule(el, flavor, model_names)
        annotations.append(_annotation(
            "element", el["name"], scope, line, snippet, source, confidence,
            {"device_kind": el["kind"], "kind_desc": el.get("kind_desc")}))
        # 接地别名归一（从 raw 节点区重推别名 token——字面 0 不算归一）
        for tok in _ground_alias_tokens(el):
            annotations.append(_annotation(
                "element_node", f"{el['name']}:{tok}", scope, line,
                snippet, "spice.node.ground_alias", "high",
                {"alias_token": tok, "normalized": "0"}))
        # X→子电路引用边
        ref = el.get("subckt_ref")
        if el["kind"] == "X" and ref:
            resolved = ref in subckt_names
            annotations.append(_annotation(
                "element", el["name"], scope, line, snippet,
                "spice.hierarchy.x_reference",
                "high" if resolved else "low",
                {"subckt_ref": ref, "resolved": resolved}))
        # 源规格关键字（显式关键字）
        spec = el.get("source_spec")
        if spec:
            annotations.append(_annotation(
                "element", el["name"], scope, line, snippet,
                "spice.source.spec_keyword", "high",
                {"source_spec_type": spec.get("type")}))
    # 顶层单连接节点浮空嫌疑（解析层判据非电气结论）
    topo = doc.get("topology") or {}
    node_elements = topo.get("node_elements") or {}
    elements_by_name = {el["name"]: el for el in doc["elements"]}
    for node in topo.get("isolated_nodes") or []:
        connected = list(node_elements.get(node) or [])
        witness = elements_by_name.get(connected[0]) if connected else None
        annotations.append(_annotation(
            "node", node, [], None if witness is None else witness.get("line_no"),
            None if witness is None else witness.get("raw"),
            "spice.topology.single_connection_suspicion", "low",
            {"node": node, "suspicion": "floating_candidate",
             "connected_elements": connected}))
    # auto 模式 flavor 判定本身是推断（行锚不可得——门如实降位）
    if doc.get("flavor_detected"):
        annotations.append(_annotation(
            "document", "", [], None, None,
            "spice.flavor.heuristic_detection", "medium",
            {"flavor": flavor}))
    return {
        "schema": f"netlist_overlay/{OVERLAY_SCHEMA_VERSION}",
        "parser_schema": doc["schema"],
        "flavor": flavor,
        "annotations": annotations,
        "coverage": _coverage(annotations, min_coverage),
        "rule_inventory": _rule_inventory(annotations),
    }


# --------------------------------------------------------------------------- #
# Spectre 原生 overlay
# --------------------------------------------------------------------------- #


def _spectre_type_rule(inst: dict[str, Any],
                       subckt_names: set[str]) -> tuple[str, str]:
    """device_type 判定序 provenance 复判（resolve_device_types 同序）。"""
    master = inst.get("master")
    if master is not None and master in subckt_names:
        return "spectre.type.subckt_ref", "high"
    if (inst.get("name") or " ")[:1].upper() == "X":
        return "spectre.type.letter_x_convention", "medium"
    if inst.get("device_type") not in (DEVICE_TYPE_UNKNOWN,):
        return "spectre.type.letter_map", "high"
    return "spectre.type.unknown_bucket", "low"


def _overlay_spectre(doc: dict[str, Any],
                     min_coverage: float) -> dict[str, Any]:
    """Spectre 原生 parse 输出 → overlay（纯读；事实层不可变）。"""
    subckt_names = set(doc.get("subckts") or {})
    annotations: list[dict[str, Any]] = []
    instances: list[dict[str, Any]] = list(doc.get("top_instances") or [])
    for sub in (doc.get("subckts") or {}).values():
        instances.extend(sub.get("instances") or [])
    for inst in instances:
        scope = list(inst.get("scope") or [])
        line = inst.get("line_no")
        snippet = inst.get("raw")
        source, confidence = _spectre_type_rule(inst, subckt_names)
        conclusion: dict[str, Any] = {"device_type": inst.get("device_type")}
        if inst.get("subckt_ref"):
            conclusion["subckt_ref"] = inst["subckt_ref"]
        annotations.append(_annotation(
            "instance", inst.get("name") or "", scope, line, snippet,
            source, confidence, conclusion))
        if inst.get("model_ref"):
            annotations.append(_annotation(
                "instance", inst.get("name") or "", scope, line, snippet,
                "spectre.type.model_ref", "high",
                {"model_ref": inst["model_ref"]}))
    # 参数引用点（词边界文本匹配——medium）
    refs = spectre_param_refs(doc)
    for name in sorted(refs):
        for record in refs[name]["consumers"]:
            annotations.append(_annotation(
                "param_ref", f"{name}@{record.get('site')}", [], record.get("line_no"),
                record.get("value_raw"),
                "spectre.ref.word_boundary_match", "medium",
                {"param": name, "site": record.get("site"),
                 "site_id": {k: v for k, v in record.items()
                             if k in ("instance", "subckt", "param", "scope")}}))
    # 层次环检测（全图判定——行锚不可得，门如实降位）
    if (doc.get("stats") or {}).get("has_hierarchy_cycle"):
        annotations.append(_annotation(
            "document", "", [], None, None,
            "spectre.hierarchy.cycle_detection", "high",
            {"has_cycle": True}))
    return {
        "schema": f"netlist_overlay/{OVERLAY_SCHEMA_VERSION}",
        "parser_schema": doc["schema"],
        "lang": doc.get("lang"),
        "annotations": annotations,
        "coverage": _coverage(annotations, min_coverage),
        "rule_inventory": _rule_inventory(annotations),
    }


def build_netlist_overlay(doc: dict[str, Any], *,
                          min_coverage: float = 0.8) -> dict[str, Any]:
    """网表 parse 输出 → 语义 overlay 层（纯函数；事实层不可变）。

    按 ``doc["schema"]`` 分派：``spice_netlist/*`` → SPICE 三格式规则；
    ``spectre_netlist/*`` → Spectre 原生规则；其他 schema 显式
    ValueError（不猜）。``min_coverage`` 为覆盖率门阈值（缺省 0.8），
    门只出 ``coverage.low_coverage`` 标注——**不改解析 ok 语义**。
    """
    schema = str(doc.get("schema") or "")
    if schema.startswith("spice_netlist/"):
        return _overlay_spice(doc, min_coverage)
    if schema.startswith("spectre_netlist/"):
        return _overlay_spectre(doc, min_coverage)
    raise ValueError(
        f"doc schema={schema!r} 不在 overlay 支持面"
        "（spice_netlist/*/spectre_netlist/*）")
