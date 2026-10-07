"""KD-4 失败知识注入查询面测试（round16 P1，J 流）。

锚树（任务书口径；查询面=core/failure_knowledge.py，消费点=campaign_manager
预检——round16 原文"rationale checklist 在 campaign_manager 预检强制调用"）：
- 检索确定性：同输入两次逐位一致（JSON sort_keys 往返）+ 别名归一同输出；
- task_kind 过滤正确：命中条目全部来自该类库（跨类关键词不串库）；
- 关键词交集排序：(-交集数, 可能性档, mode_id) 确定性全序（钉值锚）；
- top_k 截断：缺省 5 / 显式 2 / 0 → 空；
- 空结果如实空表：关键词全不命中 → hits=[]（不回退全量、markdown 空串）；
- 负例：未知 task_kind ValueError（沿 premortem 口径，不静默降级）；
- 坑号溯源：每条命中 lesson_refs 全 '#' 开头非空（=mitigation_ref 解析）；
- 注入注记格式：checklist item = mode_id（坑号）+ 一句话 + 缓解引用
  （与 rationale_memory.recall_for checklist 风格对齐）；
- 同库对偶：查询面只读消费 premortem 库（调用前后库逐位不变）；
- 消费挂点：campaign_manager.plan_campaign 附带 plan["failure_knowledge"]
  （best-effort #105：生成失败不阻塞战役计划本体，同 XN-1 premortem 挂点）。
"""

from __future__ import annotations

import json

import pytest
import yaml

from rfauto.core.failure_knowledge import (
    DEFAULT_TOP_K,
    FAILURE_KNOWLEDGE_SCHEMA,
    failure_knowledge_for,
    keywords_from_campaign,
    normalize_keywords,
    render_failure_knowledge_markdown,
)
from rfauto.core.premortem import (
    _LIKELIHOOD_RANK,
    FAILURE_MODE_LIBRARY,
    LIKELIHOOD_BANDS,
    TASK_KINDS,
)

#: 命中条目的键契约（JSON 消费面稳定钉）。
HIT_DICT_KEYS = {
    "mode_id", "lesson_refs", "score", "matched", "likelihood_band",
    "summary", "early_signals", "detection_probe", "probe_question",
    "mitigation_ref", "source",
}

#: 注入注记条目的键契约。
CHECKLIST_DICT_KEYS = {
    "item", "mode_id", "lesson_refs", "question", "mitigation_ref",
}


# ---------------------------------------------------------------------------
# 锚 1：检索确定性（同输入逐位一致 + 别名归一）
# ---------------------------------------------------------------------------


class TestRetrievalDeterminism:
    def test_same_input_twice_bitwise(self):
        a = json.dumps(failure_knowledge_for("real_solve", ["网格", "dt"]),
                       ensure_ascii=False, sort_keys=True)
        b = json.dumps(failure_knowledge_for("real_solve", ["网格", "dt"]),
                       ensure_ascii=False, sort_keys=True)
        assert a == b

    def test_alias_normalization_same_output(self):
        c = json.dumps(failure_knowledge_for("真机", ["网格"]),
                       ensure_ascii=False, sort_keys=True)
        d = json.dumps(failure_knowledge_for("real_solve", ["网格"]),
                       ensure_ascii=False, sort_keys=True)
        assert c == d

    def test_keyword_normalization_dedup_sorted(self):
        r = failure_knowledge_for("real_solve", ["dt", " 网格 ", "dt", ""])
        assert r["keywords"] == ["dt", "网格"]

    def test_library_readonly_after_query(self):
        snapshot = {k: [fm.mode_id for fm in v]
                    for k, v in FAILURE_MODE_LIBRARY.items()}
        failure_knowledge_for("param_sweep", ["cost"])
        after = {k: [fm.mode_id for fm in v]
                 for k, v in FAILURE_MODE_LIBRARY.items()}
        assert snapshot == after  # 只读消费，零突变


# ---------------------------------------------------------------------------
# 锚 2：task_kind 过滤正确（跨类关键词不串库）
# ---------------------------------------------------------------------------


class TestTaskKindFilter:
    def test_hits_all_from_requested_kind(self):
        for kind in TASK_KINDS:
            r = failure_knowledge_for(kind, ["cost", "study", "网格", "探针"])
            valid_ids = {fm.mode_id for fm in FAILURE_MODE_LIBRARY[kind]}
            assert r["task_kind"] == kind
            assert all(h["mode_id"] in valid_ids for h in r["hits"]), kind

    def test_cross_kind_keyword_not_leaked(self):
        # "study" 同时命中 param_sweep(PS-03) 与 calibration(CA-06)：
        # param_sweep 查询不得带出 CA-06（串库=过滤失效）
        r = failure_knowledge_for("param_sweep", ["study"])
        assert r["n_hits"] >= 1
        assert all(h["mode_id"].startswith("PS-") for h in r["hits"])

    def test_label_follows_kind(self):
        assert failure_knowledge_for("calibration")["task_kind_label"] == "校准"


# ---------------------------------------------------------------------------
# 锚 3：关键词交集排序（(-交集数, 可能性档, mode_id) 确定性全序）
# ---------------------------------------------------------------------------


class TestKeywordIntersectionOrder:
    def test_pinned_order_score_desc_then_band_then_id(self):
        # real_solve 实测钉值（库内检索文本）：RS-02/RS-03 双关键词交集=2，
        # RS-04/RS-10 单关键词=1——交集数优先于可能性档与 mode_id。
        r = failure_knowledge_for("real_solve", ["网格", "dt"])
        got = [(h["mode_id"], h["score"]) for h in r["hits"]]
        assert got == [("RS-02", 2), ("RS-03", 2), ("RS-04", 1), ("RS-10", 1)]
        assert [h["matched"] for h in r["hits"][:2]] == [
            ["dt", "网格"], ["dt", "网格"]]
        assert r["hits"][2]["matched"] == ["dt"]
        assert r["hits"][3]["matched"] == ["网格"]

    def test_band_tiebreak_within_same_score(self):
        # param_sweep：PS-01/PS-03 同分(1)且同 high 档 → mode_id 序；
        # PS-07 同分但 medium 档排在 high 之后。
        r = failure_knowledge_for("param_sweep", ["cost", "study"])
        got = [(h["mode_id"], h["likelihood_band"], h["score"])
               for h in r["hits"]]
        assert got == [("PS-01", "high", 1), ("PS-03", "high", 1),
                       ("PS-07", "medium", 1)]
        rank = {b: i for i, b in enumerate(LIKELIHOOD_BANDS)}
        keys = [(-h["score"], rank[h["likelihood_band"]], h["mode_id"])
                for h in r["hits"]]
        assert keys == sorted(keys)

    def test_min_score_raises_bar(self):
        base = failure_knowledge_for("real_solve", ["网格", "dt"])
        strict = failure_knowledge_for("real_solve", ["网格", "dt"],
                                       min_score=2)
        assert all(h["score"] >= 2 for h in strict["hits"])
        assert len(strict["hits"]) < len(base["hits"])

    def test_none_keywords_degrades_to_full_spread(self):
        # 无关键词 = 不过滤：全库按可能性档铺开截 top_k（退化即 XN-1 视图）
        r = failure_knowledge_for("calibration")
        assert r["keywords"] == []
        assert r["n_hits"] == min(DEFAULT_TOP_K, r["n_modes_total"])
        assert all(h["score"] == 0 and h["matched"] == [] for h in r["hits"])
        # 档序与 premortem 同源：calibration 首条 = CA-01（high 档最小 id）
        assert r["hits"][0]["mode_id"] == "CA-01"
        keys = [(_LIKELIHOOD_RANK[h["likelihood_band"]], h["mode_id"])
                for h in r["hits"]]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# 锚 4：top_k 截断 / 空结果如实空表 / 负例契约
# ---------------------------------------------------------------------------


class TestTopKAndEmptyAndNegative:
    def test_default_top_k_is_5(self):
        r = failure_knowledge_for("template_registration")
        assert r["top_k"] == DEFAULT_TOP_K == 5
        assert r["n_hits"] == 5

    def test_top_k_override_and_zero(self):
        assert len(failure_knowledge_for("calibration", top_k=2)["hits"]) == 2
        z = failure_knowledge_for("calibration", top_k=0)
        assert z["hits"] == [] and z["checklist"] == []

    def test_no_match_honest_empty(self):
        r = failure_knowledge_for("param_sweep", ["不存在的词xx"])
        assert r["ok"] is True
        assert r["n_hits"] == 0 and r["hits"] == [] and r["checklist"] == []
        # 不回退全量：top_k 帽内本可有 5 条
        assert render_failure_knowledge_markdown(r) == ""

    @pytest.mark.parametrize("bad", ["bogus", "", "  ", None, 42,
                                     ["real_solve"]])
    def test_unknown_task_kind_valueerror(self, bad):
        with pytest.raises(ValueError, match="未知 task_kind"):
            failure_knowledge_for(bad)  # type: ignore[arg-type]

    def test_schema_and_contract_keys(self):
        r = failure_knowledge_for("real_solve", ["网格"])
        assert r["ok"] and r["schema"] == FAILURE_KNOWLEDGE_SCHEMA
        assert set(r) >= {"ok", "schema", "task_kind", "task_kind_label",
                          "keywords", "n_modes_total", "n_hits", "top_k",
                          "min_score", "hits", "checklist"}
        for h in r["hits"]:
            assert set(h) == HIT_DICT_KEYS
        for c in r["checklist"]:
            assert set(c) == CHECKLIST_DICT_KEYS


# ---------------------------------------------------------------------------
# 锚 5：坑号溯源 + 注入注记格式（recall_for checklist 风格对齐）
# ---------------------------------------------------------------------------


class TestTraceabilityAndChecklistFormat:
    def test_lesson_refs_parse_from_mitigation_ref(self):
        for kind in TASK_KINDS:
            r = failure_knowledge_for(kind)
            assert r["ok"]
            for h in r["hits"]:
                assert h["lesson_refs"], h["mode_id"]
                assert all(ref.startswith("#") for ref in h["lesson_refs"])
                assert h["lesson_refs"] == [
                    t for t in h["mitigation_ref"].split("/")
                    if t.startswith("#")]

    def test_checklist_item_carries_id_refs_summary(self):
        r = failure_knowledge_for("real_solve", ["NrTS"])
        assert r["n_hits"] == 1 and r["hits"][0]["mode_id"] == "RS-02"
        item = r["checklist"][0]
        assert item["item"] == (
            "RS-02 [high] NrTS/FC 时窗截断：脉冲未跑完即触顶，"
            "|S11|>1 非物理假象（#262、#343、#312）")
        assert item["mode_id"] == "RS-02"
        assert item["lesson_refs"] == ["#262", "#343", "#312"]
        assert item["mitigation_ref"] == "#262/#343/#312"
        assert item["question"] == r["hits"][0]["probe_question"]
        assert item["question"].endswith("？")

    def test_checklist_order_follows_hits(self):
        r = failure_knowledge_for("real_solve", ["网格", "dt"])
        assert [c["mode_id"] for c in r["checklist"]] == \
            [h["mode_id"] for h in r["hits"]]

    def test_render_markdown_injection_block(self):
        r = failure_knowledge_for("real_solve", ["网格", "dt"])
        text = render_failure_knowledge_markdown(r)
        assert text.startswith("## 失败知识注入（真机求解）")
        assert "关键词：dt、网格" in text
        assert "生成预演" in text and "注入既有失败库" in text  # 同库对偶声明
        for token in ("RS-02", "#262", "症状指纹", "检测探针", "缓解引用"):
            assert token in text
        # 注记行格式：- [ ] id [档] 一句话（坑号）
        assert "- [ ] RS-02 [high]" in text and "（#262、#343、#312）" in text

    def test_render_empty_for_not_ok(self):
        assert render_failure_knowledge_markdown({"ok": False}) == ""


# ---------------------------------------------------------------------------
# 锚 6：normalize_keywords / keywords_from_campaign（战役声明面提词）
# ---------------------------------------------------------------------------


class TestKeywordExtraction:
    def test_normalize_keywords_none_str_sequence(self):
        assert normalize_keywords(None) == []
        assert normalize_keywords("  ") == []
        assert normalize_keywords("网格") == ["网格"]
        assert normalize_keywords(["b", " a ", "b", ""]) == ["a", "b"]

    def test_campaign_keywords_deterministic_sorted(self):
        objs = [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below"}]
        a = keywords_from_campaign("wilkinson_power_divider", objs,
                                   "recipe.yaml")
        b = keywords_from_campaign("wilkinson_power_divider", objs,
                                   "recipe.yaml")
        assert a == b
        assert a == ("max_below", "recipe", "s11_db",
                     "wilkinson_power_divider", "yaml")
        assert list(a) == sorted(a)  # 确定性全序

    def test_campaign_keywords_cjk_and_empty(self):
        # 连续 CJK 段为单 token（与 rationale_memory._TOKEN 同口径切分）
        assert "真机求解" in keywords_from_campaign("真机求解", None, "")
        assert keywords_from_campaign("", None, "") == ()
        assert keywords_from_campaign(None, None, None) == ()


# ---------------------------------------------------------------------------
# 锚 7：消费挂点——campaign_manager 预检强制调用（best-effort #105）
# ---------------------------------------------------------------------------


@pytest.fixture
def recipe_path(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "limits": {"max_trials": 12},
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe, allow_unicode=True), encoding="utf-8")
    return path


def _write_same_recipe(tmp_path, name: str):
    d = tmp_path / name
    d.mkdir()
    path = d / "recipe.yaml"
    path.write_text(yaml.safe_dump({
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "limits": {"max_trials": 12},
    }, allow_unicode=True), encoding="utf-8")
    return path


class TestCampaignKickoffHook:
    def test_plan_attaches_failure_knowledge_additive(self, recipe_path):
        from rfauto.service.campaign_manager import plan_campaign

        plan = plan_campaign(recipe_path)
        assert plan["ok"]
        blk = plan["failure_knowledge"]
        assert blk["ok"] and blk["task_kind"] == "param_sweep"
        assert blk["task_kind_label"] == "参数扫描战役"
        assert blk["keywords"]  # 战役声明面提词非空（诚实空也须显式）
        assert blk["keywords_source"] == \
            "campaign_declaration(model/objectives/recipe)"
        for h in blk["hits"]:
            assert all(ref.startswith("#") for ref in h["lesson_refs"])
        # markdown 注入块与 hits 一致（空命中=空串，不产占位噪声）
        assert (blk["markdown"] != "") == (blk["n_hits"] > 0)
        # 既有面不受影响（XN-1 premortem / 调度 / 阶段队列照旧）
        assert plan["premortem"]["ok"]
        assert plan["scheduling"]["ok"]
        assert [s["stage"] for s in plan["stages"]][:5] == [
            "calibrate", "prefilter", "tune", "tolerance", "report"]

    def test_plan_failure_knowledge_deterministic(self, tmp_path):
        from rfauto.service.campaign_manager import plan_campaign

        blocks = [plan_campaign(_write_same_recipe(tmp_path, f"case{i}"))[
            "failure_knowledge"] for i in range(2)]
        a = json.dumps(blocks[0], ensure_ascii=False, sort_keys=True)
        b = json.dumps(blocks[1], ensure_ascii=False, sort_keys=True)
        assert a == b

    def test_plan_failure_knowledge_best_effort_on_failure(
            self, recipe_path, monkeypatch):
        from rfauto.service import campaign_manager

        def _boom(*_a, **_k):
            raise RuntimeError("检索故障")

        monkeypatch.setattr(
            "rfauto.core.failure_knowledge.failure_knowledge_for", _boom)
        plan = campaign_manager.plan_campaign(recipe_path)
        assert plan["ok"]  # #105：不阻塞战役计划本体
        assert plan["stages"]
        blk = plan["failure_knowledge"]
        assert blk["ok"] is False and "warning" in blk
        assert "#105" in blk["warning"]

    def test_save_load_plan_roundtrip_keeps_failure_knowledge(
            self, recipe_path, tmp_path):
        from rfauto.service.campaign_manager import (
            load_plan,
            plan_campaign,
            save_plan,
        )

        plan = plan_campaign(recipe_path)
        out_dir = tmp_path / "camp"
        save_plan(plan, out_dir)
        loaded = load_plan(out_dir)
        assert loaded["ok"]
        assert loaded["plan"]["failure_knowledge"] == plan["failure_knowledge"]
