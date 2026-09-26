"""DP-9 P1/P2：rfauto-dag-v1 schema 内核测试（零真机零网络）。

覆盖：节点校验（构造期拒绝）、拓扑排序+环检测、线性链降级（判据 ⑤）、
campaign stage→node 确定性映射。
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from rfauto.core.compose.dag_schema import (
    DAG_SCHEMA,
    DEFAULT_RERUN_TRIGGERS,
    NODE_KINDS,
    STAGE_KIND_MAP,
    DagSchemaError,
    linear_chain_recipe,
    nodes_from_stages,
    normalize_node,
    parse_dag,
    topo_order,
)


def _node(node_id: str, kind: str = "render", deps: list[str] | None = None,
          **kw: object) -> dict:
    raw = {"node_id": node_id, "kind": kind, "depends_on": deps or []}
    raw.update(kw)
    return raw


# ─── 节点校验（构造期拒绝）───────────────────────────────────────────────────

def test_normalize_node_defaults_all_on_triggers() -> None:
    node = normalize_node(_node("r1", "render"))
    assert node["rerun_triggers"] == list(DEFAULT_RERUN_TRIGGERS)
    assert node["retries"] == 0
    assert node["escalation"] == [{"budget_x": 1.5}, {"mesh_tier": "next"}]
    assert node["inputs"] == {"files": [], "params": {}}
    assert node["outputs"] == []
    assert node["budget"] == {}


def test_normalize_node_rejects_bad_kind_and_empty_id() -> None:
    with pytest.raises(DagSchemaError, match="kind"):
        normalize_node(_node("r1", "teleport"))
    with pytest.raises(DagSchemaError, match="node_id"):
        normalize_node({"kind": "render", "node_id": ""})
    with pytest.raises(DagSchemaError, match="node_id"):
        normalize_node({"kind": "render"})


def test_normalize_node_rejects_self_dep_and_bad_triggers() -> None:
    with pytest.raises(DagSchemaError, match="自依赖"):
        normalize_node(_node("r1", deps=["r1"]))
    with pytest.raises(DagSchemaError, match="rerun_triggers"):
        normalize_node(_node("r1", rerun_triggers=["mtime"]))
    with pytest.raises(DagSchemaError, match="rerun_triggers"):
        normalize_node(_node("r1", rerun_triggers=[]))
    with pytest.raises(DagSchemaError, match="retries"):
        normalize_node(_node("r1", retries=-1))
    with pytest.raises(DagSchemaError, match=r"not a dict|不是 dict"):
        normalize_node("render")


# ─── 拓扑排序与环检测 ────────────────────────────────────────────────────────

def test_topo_order_deterministic_and_lexicographic_within_layer() -> None:
    nodes = [_node("b"), _node("a"), _node("c", deps=["a", "b"]),
             _node("d", deps=["a"])]
    # 同层（a,b 同批就绪；c,d 在 a,b 后同批就绪）按 node_id 字典序
    assert topo_order(nodes) == ["a", "b", "c", "d"]


def test_topo_rejects_cycle_and_unknown_dep_and_dupe() -> None:
    with pytest.raises(DagSchemaError, match="依赖环"):
        topo_order([_node("a", deps=["b"]), _node("b", deps=["a"])])
    with pytest.raises(DagSchemaError, match="未知节点"):
        topo_order([_node("a", deps=["ghost"])])
    with pytest.raises(DagSchemaError, match="重复"):
        topo_order([_node("a"), _node("a", kind="solve")])


def test_parse_dag_error_shape_is_json_style() -> None:
    bad = parse_dag({"nodes": [_node("a", deps=["a"])]})
    assert bad["ok"] is False and bad["errors"]
    assert parse_dag("nope")["ok"] is False
    assert parse_dag({"nodes": "nope"})["ok"] is False
    good = parse_dag({"nodes": [_node("r"), _node("s", "solve", ["r"])]})
    assert good["ok"] is True
    assert good["schema"] == DAG_SCHEMA
    assert good["order"] == ["r", "s"]
    assert all(n["kind"] in NODE_KINDS for n in good["nodes"])


# ─── 线性链降级（判据 ⑤：旧配方无 dag 键零改动可跑）─────────────────────────

def test_linear_chain_degrades_old_recipe() -> None:
    recipe = {"model": "wilkinson", "params": {"w": 0.5, "er": 4.4},
              "objectives": [{"metric": "s11_db"}]}
    dag = linear_chain_recipe(recipe)
    assert dag["ok"] is True
    order = dag["order"]
    assert len(order) == 4
    nodes = {n["node_id"]: n for n in dag["nodes"]}
    # 线性链：render→solve→postprocess→judge 串联
    for prev, nxt in pairwise(order):
        assert nodes[prev]["node_id"] in nodes[nxt]["depends_on"]
        assert nodes[nxt]["depends_on"] == [nodes[prev]["node_id"]]
    kinds = [nodes[n]["kind"] for n in order]
    assert kinds == ["render", "solve", "postprocess", "judge"]
    # 配方 params 原样进 render 节点（参数面不丢）
    assert nodes[order[0]]["inputs"]["params"] == {"w": 0.5, "er": 4.4}
    assert "wilkinson" in order[0]


# ─── campaign stage→node 映射（wrap 兼容链的地基）───────────────────────────

def test_nodes_from_stages_preserves_deps_and_extras() -> None:
    stages = [
        {"stage": "calibrate", "kind": "calibrate", "depends_on": [],
         "budget": 9, "entry": "rfauto calibrate x.yaml", "status": "pending",
         "note": "n"},
        {"stage": "prefilter", "kind": "prefilter",
         "depends_on": ["calibrate"], "budget": 30},
        {"stage": "final_verify", "kind": "tune", "depends_on": ["tune"],
         "budget": 5, "shadow_points": {"n_points": 3, "status": "pending"}},
    ]
    nodes = nodes_from_stages(stages)
    by_id = {n["node_id"]: n for n in nodes}
    assert by_id["calibrate"]["kind"] == "solve"      # STAGE_KIND_MAP
    assert by_id["prefilter"]["kind"] == "postprocess"
    assert by_id["final_verify"]["kind"] == "solve"
    assert by_id["prefilter"]["depends_on"] == ["calibrate"]
    assert by_id["final_verify"]["budget"] == {"timeout_s": 5}
    # shadow_points 等阶段扩展字段收进 stage_extra（不丢字段）
    assert by_id["final_verify"]["stage_extra"]["shadow_points"] == {
        "n_points": 3, "status": "pending"}
    assert by_id["calibrate"]["cmd"] == "rfauto calibrate x.yaml"


def test_stage_kind_map_covers_campaign_stages() -> None:
    for stage_kind in ("calibrate", "prefilter", "tune", "tolerance",
                       "report", "final_verify"):
        assert stage_kind in STAGE_KIND_MAP
    for mapped in STAGE_KIND_MAP.values():
        assert mapped in NODE_KINDS
