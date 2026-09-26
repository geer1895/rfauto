"""rfauto-dag-v1：配方 DAG 化的确定性 schema 内核（DP-9 P2，规格 §2）。

分层（分层铁律）：core 只做确定性内核，零 I/O 依赖——节点 schema 校验、
构造期拓扑排序+环检测、旧配方/旧计划的兼容包装全在这里；键计算与 CAS
落盘在 infra.dag_cache，执行与断点续跑在 pipeline.dag_runner。

节点形态（rfauto-dag-v1）::

    {
      "node_id": "render_main",          # 非空，DAG 内唯一
      "kind": "render",                  # render|solve|postprocess|judge
      "inputs": {"files": [...], "params": {...}},
      "outputs": ["results/sparams.csv", ...],
      "cmd": "rfauto render ...",        # 声明性命令串（执行层解释）
      "budget": {"timeout_s": 3600, "nrts": 100000, "mesh_tier": "mid"},
      "retries": 1,
      "escalation": [{"budget_x": 1.5}, {"mesh_tier": "next"}],
      "rerun_triggers": ["code", "params", "env", "budget"],  # 缺省全开
    }

边=depends_on（节点字段）。旧 recipes/ YAML 无 ``dag`` 键 → 线性链降级；
campaign plan v1/v1.1 的 stages → 节点映射（STAGE_KIND_MAP 确定性表）。
"""

from __future__ import annotations

import json
from typing import Any

#: schema 版本串（节点集 JSON 载体 + plan v2 的 dag.schema 字段）。
DAG_SCHEMA = "rfauto-dag-v1"

#: 合法节点类型（规格 §2 固定四类）。
NODE_KINDS: tuple[str, ...] = ("render", "solve", "postprocess", "judge")

#: 节点/阶段状态（复用 campaign 状态机语义：failed→aborted 递归传播）。
NODE_STATUSES: tuple[str, ...] = (
    "pending", "running", "done", "failed", "aborted", "partial", "skipped")

#: rerun-triggers 分级（规格 §4：code/params/env/budget；缺省全开；
#: mtime 类不可靠触发器不采用——#325/#329 实证 mtime 语义不可靠）。
RERUN_TRIGGER_CATEGORIES: tuple[str, ...] = ("code", "params", "env", "budget")
DEFAULT_RERUN_TRIGGERS: tuple[str, ...] = RERUN_TRIGGER_CATEGORIES

#: 资源递增重试缺省阶梯（规格 §2 escalation[{budget×1.5},{mesh:下一档}]）。
DEFAULT_ESCALATION: tuple[dict[str, Any], ...] = (
    {"budget_x": 1.5}, {"mesh_tier": "next"})
BUDGET_X_DEFAULT = 1.5          # SAFETY_BUDGET=1.5 先例（c3_fullcurve_runner）

#: campaign stage kind → dag node kind（确定性映射表；campaign_manager
#: 的五阶段 + final_verify 全覆盖，未知 kind 落 "solve" 保守可执行）。
STAGE_KIND_MAP: dict[str, str] = {
    "calibrate": "solve",
    "prefilter": "postprocess",
    "tune": "solve",
    "tolerance": "postprocess",
    "report": "judge",
    "final_verify": "solve",
}

#: 线性链降级的节点序（旧配方无 dag 键时，规格 §2"自动降级线性链"）。
LINEAR_CHAIN_KINDS: tuple[str, ...] = ("render", "solve", "postprocess", "judge")


class DagSchemaError(ValueError):
    """DAG 构造期拒绝（schema 非法 / 未知依赖 / 环）——显式报错不静默。"""


def canonical(obj: Any) -> str:
    """稳定 JSON 串（sort_keys、无空格）——schema 内哈希/比对统一口径。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


#: normalize_node 的已知字段；其余键作为扩展键原样透传（schema 前向
#: 兼容——stage_extra/shadow_points 等扩展不丢，wrap_plan_v2 依赖）。
_KNOWN_NODE_FIELDS: frozenset[str] = frozenset({
    "node_id", "kind", "depends_on", "inputs", "outputs", "cmd", "budget",
    "retries", "escalation", "rerun_triggers",
})


def normalize_node(raw: Any, *, index: int = 0) -> dict[str, Any]:
    """校验并归一化单节点（构造期拒绝，DagSchemaError 带字段定位）。

    宽进严出：inputs/outputs/budget 缺省给空值（judge 节点可以只有 cmd）；
    但 node_id/kind/depends_on/rerun_triggers/retries/escalation 的类型
    与取值域强制——非法节点在构造期炸而不是跑到一半炸。
    """
    if not isinstance(raw, dict):
        raise DagSchemaError(f"节点 #{index} 不是 dict: {type(raw).__name__}")
    where = f"节点[{raw.get('node_id', f'#{index}')}]" if isinstance(
        raw.get("node_id"), str) else f"节点 #{index}"

    node_id = raw.get("node_id")
    if not isinstance(node_id, str) or not node_id.strip():
        raise DagSchemaError(f"{where}: node_id 必须是非空字符串")
    where = f"节点[{node_id}]"

    kind = raw.get("kind")
    if kind not in NODE_KINDS:
        raise DagSchemaError(
            f"{where}: kind={kind!r} 非法，可选 {list(NODE_KINDS)}")

    depends_on = raw.get("depends_on", [])
    if not isinstance(depends_on, list) or not all(
            isinstance(d, str) and d for d in depends_on):
        raise DagSchemaError(f"{where}: depends_on 必须是非空字符串列表")
    if node_id in depends_on:
        raise DagSchemaError(f"{where}: 自依赖（node_id 出现在 depends_on）")

    inputs = raw.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise DagSchemaError(f"{where}: inputs 必须是 dict")
    outputs = raw.get("outputs") or []
    if not isinstance(outputs, list) or not all(isinstance(o, str) for o in outputs):
        raise DagSchemaError(f"{where}: outputs 必须是字符串列表（相对路径）")

    budget = raw.get("budget") or {}
    if not isinstance(budget, dict):
        raise DagSchemaError(f"{where}: budget 必须是 dict（timeout_s/nrts/mesh_tier）")

    retries = raw.get("retries", 0)
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise DagSchemaError(f"{where}: retries 必须是 ≥0 整数")

    escalation = raw.get("escalation")
    if escalation is None:
        escalation = [dict(step) for step in DEFAULT_ESCALATION]
    if not isinstance(escalation, list) or not all(
            isinstance(step, dict) for step in escalation):
        raise DagSchemaError(f"{where}: escalation 必须是 dict 列表")

    triggers = raw.get("rerun_triggers")
    if triggers is None:
        triggers = list(DEFAULT_RERUN_TRIGGERS)
    if (not isinstance(triggers, list) or not triggers
            or not set(triggers).issubset(RERUN_TRIGGER_CATEGORIES)):
        raise DagSchemaError(
            f"{where}: rerun_triggers 必须是 {list(RERUN_TRIGGER_CATEGORIES)}"
            f" 的非空子集，收到 {triggers!r}")

    return {
        "node_id": node_id,
        "kind": kind,
        "depends_on": list(depends_on),
        "inputs": {"files": list(inputs.get("files") or []),
                   "params": dict(inputs.get("params") or {})},
        "outputs": list(outputs),
        "cmd": str(raw.get("cmd", "")),
        "budget": dict(budget),
        "retries": retries,
        "escalation": [dict(step) for step in escalation],
        "rerun_triggers": list(triggers),
        # 扩展键透传（stage_extra 等；不覆盖已知字段）
        **{k: v for k, v in raw.items() if k not in _KNOWN_NODE_FIELDS},
    }


def topo_order(nodes: list[dict[str, Any]]) -> list[str]:
    """Kahn 拓扑排序（确定性：同层按 node_id 字典序）。

    未知依赖 / 环 → DagSchemaError（环成员显式列出）。
    """
    ids = [n["node_id"] for n in nodes]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise DagSchemaError(f"node_id 重复: {dup}")
    known = set(ids)
    deps = {n["node_id"]: [d for d in n["depends_on"] if d in known]
            for n in nodes}
    unknown = {n["node_id"]: [d for d in n["depends_on"] if d not in known]
               for n in nodes}
    bad = {k: v for k, v in unknown.items() if v}
    if bad:
        raise DagSchemaError(f"depends_on 引用未知节点: {bad}")

    order: list[str] = []
    remaining = dict(deps)
    while remaining:
        ready = sorted(k for k, ds in remaining.items() if not ds)
        if not ready:
            cycle = sorted(remaining)
            raise DagSchemaError(f"依赖环（构造期拒绝）: {cycle}")
        for k in ready:
            order.append(k)
            remaining.pop(k)
        for ds in remaining.values():
            ds[:] = [d for d in ds if d not in ready]  # type: ignore[union-attr]
    return order


def parse_dag(raw: Any) -> dict[str, Any]:
    """解析 rfauto-dag-v1 节点集 → 归一化节点表 + 拓扑序。

    raw = {"nodes": [...]}；非法/环/未知依赖 → ok=False + errors
    （不抛出——service JSON 进出口径，与 campaign_manager.load_plan 一致）。
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), list):
        return {"ok": False,
                "errors": [f"dag 载体必须是 {{nodes: [...]}}，收到 "
                           f"{type(raw).__name__}"]}
    try:
        nodes = [normalize_node(r, index=i) for i, r in enumerate(raw["nodes"])]
        order = topo_order(nodes)
    except DagSchemaError as exc:
        return {"ok": False, "errors": [str(exc)]}
    return {"ok": True, "schema": DAG_SCHEMA, "nodes": nodes, "order": order}


def linear_chain_recipe(recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    """旧配方（无 dag 键）→ 线性链降级（规格 §2：旧 YAML 零改动可跑）。

    产出 render→solve→postprocess→judge 四节点线性链，节点间以 depends_on
    串联（判据 ⑤：与既有 campaign 阶段序列同构）。配方 params 原样进
    render 节点 inputs.params；cmd 保留声明性占位（执行层解释）。
    """
    recipe = recipe or {}
    model = str(recipe.get("model", "") or "")
    params = dict(recipe.get("params") or {})
    nodes: list[dict[str, Any]] = []
    prev = ""
    for kind in LINEAR_CHAIN_KINDS:
        node: dict[str, Any] = {
            "node_id": f"{kind}_main" if not model else f"{kind}_{model}",
            "kind": kind,
            "depends_on": [prev] if prev else [],
            "inputs": {"files": [], "params": params if kind == "render" else {}},
            "outputs": [],
            "cmd": "",
        }
        prev = node["node_id"]
        nodes.append(node)
    return parse_dag({"nodes": nodes})


def nodes_from_stages(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """campaign plan v1/v1.1 的 stages → dag 节点（STAGE_KIND_MAP 确定性映射）。

    stage 名即 node_id（depends_on 引用 stage 名，wrap 后依赖关系逐位保留）；
    shadow_points 等阶段扩展字段收进节点扩展键 ``stage_extra``（不丢字段，
    wrap_plan_v2 的 v2 兼容链依赖这一点）。
    """
    nodes: list[dict[str, Any]] = []
    for stage in stages:
        stage = stage or {}
        name = str(stage.get("stage", "") or "")
        if not name:
            continue
        kind = STAGE_KIND_MAP.get(str(stage.get("kind", "") or ""), "solve")
        budget = stage.get("budget")
        node: dict[str, Any] = {
            "node_id": name,
            "kind": kind,
            "depends_on": [d for d in (stage.get("depends_on") or []) if d],
            "inputs": {"files": [], "params": {}},
            "outputs": [],
            "cmd": str(stage.get("entry", "") or ""),
            "budget": ({"timeout_s": None} if budget is None
                       else {"timeout_s": budget}),
            "retries": 0,
        }
        extra = {k: v for k, v in stage.items() if k not in (
            "stage", "kind", "depends_on", "entry", "budget", "status", "note")}
        if extra:
            node["stage_extra"] = extra
        nodes.append(node)
    return nodes
