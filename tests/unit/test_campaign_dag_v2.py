"""DP-9 P2：campaign plan v1.1 → v2 包装兼容钉测试（判据 ⑤）。

- wrap_plan_v2：原字段逐字节保留（stages/shadow_points/goal/recipe）、
  campaign_schema 升 v2、新增 dag 键（rfauto-dag-v1 节点集）、不 mutate
  输入、幂等；
- plan_campaign 缺省发射仍为 v1.1（既有兼容钉 test_fidelity_shadow /
  test_mcp_wp33_tools 的断言不被动）；
- v2 计划的 dag 节点可被 core.compose.parse_dag 消费（拓扑序合法）。

零真机零网络（recipes 走 tmp 配方文件）。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from rfauto.core.compose.dag_schema import DAG_SCHEMA, parse_dag
from rfauto.service.campaign_manager import (
    CAMPAIGN_SCHEMA,
    CAMPAIGN_SCHEMA_V2,
    apply_event,
    plan_campaign,
    save_plan,
    wrap_plan_v2,
)


def _write_recipe(tmp_path: Path) -> Path:
    recipe = {
        "model": "wilkinson_pd",
        "objectives": [{"metric": "s11_db", "op": "<", "value": -10,
                        "band": [2.3, 2.5]}],
        "params": {"w": {"value": 0.5, "unit": "mm"}},
        "limits": {"max_trials": 12},
    }
    path = tmp_path / "recipe_v2wrap.yaml"
    path.write_text(yaml.safe_dump(recipe, allow_unicode=True),
                    encoding="utf-8")
    return path


def test_plan_campaign_default_schema_stays_v1_1(tmp_path) -> None:
    """兼容钉：plan_campaign 缺省发射 v1.1（Z2 shadow_points 兼容链不动）。"""
    plan = plan_campaign(_write_recipe(tmp_path))
    assert plan["ok"] is True
    assert plan["campaign_schema"] == CAMPAIGN_SCHEMA      # v1.1
    assert "dag" not in plan
    fv = [s for s in plan["stages"] if s["stage"] == "final_verify"]
    assert fv and fv[0]["shadow_points"]["n_points"] == 3  # Z2 面原样


def test_wrap_plan_v2_preserves_fields_and_adds_dag(tmp_path) -> None:
    """判据 ⑤：v2 包装 = 原字段逐字节保留 + schema 升 v2 + dag 键。"""
    plan = plan_campaign(_write_recipe(tmp_path))
    stages_before = json.dumps(plan["stages"], sort_keys=True,
                               ensure_ascii=False)
    wrapped = wrap_plan_v2(plan)
    # 原 stages 逐字节不变（状态机 apply_event 继续消费）
    assert json.dumps(wrapped["stages"], sort_keys=True,
                      ensure_ascii=False) == stages_before
    assert wrapped["campaign_schema"] == CAMPAIGN_SCHEMA_V2
    assert wrapped["dag"]["schema"] == DAG_SCHEMA
    # 非 stages 字段（goal/recipe/scheduling/shadow_points）全保留
    assert wrapped["goal"] == plan["goal"]
    assert wrapped["recipe"] == plan["recipe"]
    assert wrapped["model"] == plan["model"]
    fv = [s for s in wrapped["stages"] if s["stage"] == "final_verify"]
    assert fv[0]["shadow_points"]["n_points"] == 3
    # 不 mutate 输入
    assert plan["campaign_schema"] == CAMPAIGN_SCHEMA and "dag" not in plan
    # 节点与 stage 一一同构：node_id=stage 名，depends_on 逐位保留
    stage_names = [s["stage"] for s in plan["stages"]]
    node_ids = [n["node_id"] for n in wrapped["dag"]["nodes"]]
    assert node_ids == stage_names
    by_id = {n["node_id"]: n for n in wrapped["dag"]["nodes"]}
    for stage in plan["stages"]:
        assert by_id[stage["stage"]]["depends_on"] == list(
            stage["depends_on"])


def test_wrap_plan_v2_idempotent(tmp_path) -> None:
    plan = plan_campaign(_write_recipe(tmp_path))
    once = wrap_plan_v2(plan)
    twice = wrap_plan_v2(once)
    assert twice is once                    # 已是 v2 → 原样返回（幂等）


def test_wrap_plan_v2_dag_parseable_and_shadow_points_in_node(
        tmp_path) -> None:
    plan = plan_campaign(_write_recipe(tmp_path))
    wrapped = wrap_plan_v2(plan)
    parsed = parse_dag(wrapped["dag"])
    assert parsed["ok"] is True
    order = parsed["order"]
    # 节点集与 stage 集一一对应；拓扑序合法（依赖先于下游；
    # report 与 final_verify 同层，字典序不作为语义断言）
    assert set(order) == {s["stage"] for s in plan["stages"]}
    pos = {nid: i for i, nid in enumerate(order)}
    for n in parsed["nodes"]:
        for d in n["depends_on"]:
            assert pos[d] < pos[n["node_id"]]
    by_id = {n["node_id"]: n for n in parsed["nodes"]}
    # Z2 shadow_points 收进节点 stage_extra（v2 链不丢字段）
    assert by_id["final_verify"]["stage_extra"]["shadow_points"][
        "n_points"] == 3


def test_state_machine_still_works_on_v2_plan(tmp_path) -> None:
    """v2 计划的 stages 状态机语义不变（failed→aborted 递归传播照旧）。"""
    plan = plan_campaign(_write_recipe(tmp_path))
    wrapped = wrap_plan_v2(plan)
    res = apply_event(wrapped, "calibrate", "stage_failed", detail="x")
    assert res["ok"] is True
    statuses = {s["stage"]: s["status"] for s in res["plan"]["stages"]}
    assert statuses["calibrate"] == "failed"
    assert statuses["final_verify"] == "aborted"   # 下游递归放弃
    assert res["verdict"] == "ABORTED"


def test_v2_plan_save_and_load_roundtrip(tmp_path) -> None:
    plan = plan_campaign(_write_recipe(tmp_path))
    wrapped = wrap_plan_v2(plan)
    out = tmp_path / "camp"
    save_plan(wrapped, out)
    text = (out / "campaign.plan.json").read_text(encoding="utf-8")
    loaded = json.loads(text)
    assert loaded["campaign_schema"] == CAMPAIGN_SCHEMA_V2
    assert loaded["dag"]["schema"] == DAG_SCHEMA
    # 旧 load_plan 读面兼容（ok=True，stages 可消费）
    from rfauto.service.campaign_manager import load_plan
    found = load_plan(out)
    assert found["ok"] is True
    assert found["plan"]["campaign_schema"] == CAMPAIGN_SCHEMA_V2
