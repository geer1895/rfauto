"""XN-1 Pre-mortem 失败预演测试（第十九轮 P1，G 流）。

锚树（任务书口径）：
- 规则库完整性：每类 ≥5 条封闭断言 + 类×条数显式钉死（扩库=显式改锚，
  #231 注册表消费者文化）+ 字段完备/坑号可溯 + 探针↔模式无孤儿；
- 生成确定性：同输入两次逐位一致（JSON sort_keys 往返）；
- 探针可执行性：全注册表 {} 上下文可执行 + declares/forbids/in 三检查类
  分支 + falsy 不算已声明（#364④ 纪律）+ 纯函数（无 I/O 同输入同输出）；
- 负例：未知 task_kind ValueError（不静默降级）；
- 消费挂点：service 薄壳 JSON 进出 + campaign_manager.plan_campaign 开工
  附带块（best-effort #105，生成失败不阻塞战役计划本体）。
"""

from __future__ import annotations

import json

import pytest
import yaml

from rfauto.core.premortem import (
    DEFAULT_TOP_K,
    FAILURE_MODE_LIBRARY,
    KIND_PREFIX,
    LIKELIHOOD_BANDS,
    MIN_MODES_PER_KIND,
    PROBE_REGISTRY,
    TASK_KINDS,
    ProbeSpec,
    detection_probes,
    premortem,
    render_premortem_markdown,
    run_probe,
)
from rfauto.service.premortem_service import (
    campaign_premortem_block,
    premortem_for_context,
    premortem_report,
    premortem_task_kinds,
    save_premortem_report,
)

#: 类×条数显式钉（扩库必须显式改此锚——防"顺手加一条"不审出处）。
EXPECTED_KIND_COUNTS: dict[str, int] = {
    "real_solve": 10,
    "param_sweep": 10,
    "calibration": 9,
    "synthesis_registration": 7,
    "template_registration": 10,
}

#: 失败模式 dict 的键契约（JSON 消费面稳定钉）。
MODE_DICT_KEYS = {
    "mode_id", "task_kind", "mode", "likelihood_band", "early_signals",
    "detection_probe", "probe_question", "mitigation_ref", "source",
    "schema_version",
}


# ---------------------------------------------------------------------------
# 锚 1：规则库完整性
# ---------------------------------------------------------------------------


class TestModeLibraryIntegrity:
    def test_five_kinds_exact_coverage(self):
        assert set(FAILURE_MODE_LIBRARY) == set(TASK_KINDS)
        assert set(KIND_PREFIX) == set(TASK_KINDS)
        assert len(TASK_KINDS) == 5

    def test_per_kind_min_and_pinned_counts(self):
        for kind, expected_n in EXPECTED_KIND_COUNTS.items():
            modes = FAILURE_MODE_LIBRARY[kind]
            assert len(modes) >= MIN_MODES_PER_KIND, kind
            assert len(modes) == expected_n, (
                f"{kind} 条数 {len(modes)} ≠ 钉值 {expected_n}（扩库显式改锚）")

    def test_entry_fields_complete_and_traceable(self):
        for kind, modes in FAILURE_MODE_LIBRARY.items():
            for fm in modes:
                assert fm.mode_id and fm.mode
                assert fm.task_kind == kind
                assert fm.likelihood_band in LIKELIHOOD_BANDS
                assert fm.early_signals and all(fm.early_signals)
                # 缓解引用必须带坑号（可溯）；出处非空
                assert "#" in fm.mitigation_ref, fm.mode_id
                assert fm.source, fm.mode_id

    def test_mode_ids_unique_and_prefixed(self):
        seen: set[str] = set()
        for kind, modes in FAILURE_MODE_LIBRARY.items():
            prefix = KIND_PREFIX[kind]
            for fm in modes:
                assert fm.mode_id not in seen, fm.mode_id
                seen.add(fm.mode_id)
                assert fm.mode_id.startswith(f"{prefix}-"), fm.mode_id

    def test_probe_mode_bijection_no_orphans(self):
        referenced: set[str] = set()
        for kind, modes in FAILURE_MODE_LIBRARY.items():
            probe_ids = {fm.detection_probe for fm in modes}
            referenced |= probe_ids
            # detection_probes 返回该类去重探针集，与模式引用一致
            assert {p.probe_id for p in detection_probes(kind)} == probe_ids
        assert referenced == set(PROBE_REGISTRY)  # 无孤儿探针
        assert all(p in PROBE_REGISTRY for p in referenced)  # 无未注册引用

    def test_probe_specs_wellformed(self):
        for pid, spec in PROBE_REGISTRY.items():
            assert spec.probe_id == pid
            assert spec.question
            if spec.check_kind == "declares":
                assert spec.question.endswith("？")
            assert spec.check_kind in ("declares", "forbids", "in")
            assert spec.keys and all(spec.keys)
            assert all(ref.startswith("#") for ref in spec.lesson_refs)


# ---------------------------------------------------------------------------
# 锚 2：premortem 生成（排序/top-k/确定性/核对表/探针报告）
# ---------------------------------------------------------------------------


class TestPremortemGeneration:
    @pytest.mark.parametrize("bad", ["bogus", "", "  ", None, 42, ["real_solve"]])
    def test_unknown_task_kind_valueerror(self, bad):
        with pytest.raises(ValueError, match="未知 task_kind"):
            premortem(bad)

    @pytest.mark.parametrize(("alias", "expected"), [
        ("真机求解", "real_solve"),
        ("真跑", "real_solve"),
        ("Campaign", "param_sweep"),
        ("参数扫描战役", "param_sweep"),
        ("CALIBRATE", "calibration"),
        ("综合注册", "synthesis_registration"),
        ("模板", "template_registration"),
    ])
    def test_alias_normalization(self, alias, expected):
        assert premortem(alias)["task_kind"] == expected

    def test_default_top10_and_likelihood_order(self):
        r = premortem("real_solve")
        assert r["ok"] and r["n_modes_total"] == 10
        assert len(r["failure_modes"]) == min(DEFAULT_TOP_K, 10)
        rank = {b: i for i, b in enumerate(LIKELIHOOD_BANDS)}
        keys = [(rank[m["likelihood_band"]], m["mode_id"])
                for m in r["failure_modes"]]
        assert keys == sorted(keys)  # high 档在前，同档按 mode_id
        assert r["failure_modes"][0]["mode_id"] == "RS-01"

    def test_short_kind_returns_all_and_top_k_override(self):
        r = premortem("synthesis_registration")
        assert r["n_modes_total"] == EXPECTED_KIND_COUNTS[
            "synthesis_registration"]
        assert len(r["failure_modes"]) == r["n_modes_total"]  # 7 < top-k 10
        assert len(premortem("calibration", top_k=3)["failure_modes"]) == 3
        assert premortem("calibration", top_k=0)["failure_modes"] == []

    def test_determinism_bitwise_same_input_twice(self):
        ctx = {"model_audit_first": "declared", "recipe": "r.yaml"}
        a = json.dumps(premortem("calibration", ctx),
                       ensure_ascii=False, sort_keys=True)
        b = json.dumps(premortem("calibration", ctx),
                       ensure_ascii=False, sort_keys=True)
        assert a == b
        c = json.dumps(premortem("真机求解"),
                       ensure_ascii=False, sort_keys=True)
        d = json.dumps(premortem("real_solve"),
                       ensure_ascii=False, sort_keys=True)
        assert c == d  # 别名归一后同库同输出

    def test_checklist_dedup_by_probe_with_merged_refs(self):
        r = premortem("param_sweep")
        probe_ids = [m["detection_probe"] for m in r["failure_modes"]]
        assert len(r["checklist"]) == len(set(probe_ids))  # 按探针去重
        for item in r["checklist"]:
            assert item["item"] == item["question"]
            assert item["probe_id"] in PROBE_REGISTRY
            assert item["source_refs"]  # 归并了缓解引用

    def test_probe_report_mapping_context_and_full_declare_closure(self):
        kind = "real_solve"
        empty = premortem(kind, {})
        assert empty["n_probes_open"] == len(empty["probe_report"]) > 0
        # 全量声明（每个探针第一个键置真值）→ 全闭合
        declared = {spec.keys[0]: "yes"
                    for spec in detection_probes(kind)}
        full = premortem(kind, declared)
        assert full["n_probes_open"] == 0
        assert all(p["ok"] for p in full["probe_report"])

    def test_no_probe_report_when_context_none(self):
        assert "probe_report" not in premortem("calibration", None)
        assert "probe_report" not in premortem("calibration")

    def test_mode_dict_key_contract(self):
        for m in premortem("template_registration")["failure_modes"]:
            assert set(m) == MODE_DICT_KEYS

    def test_render_markdown_contains_modes_and_gate(self):
        text = render_premortem_markdown(premortem("template_registration", {}))
        assert text.startswith("## Pre-mortem 失败预演（模板注册）")
        assert "症状指纹" in text and "检测探针" in text
        assert "#304" in text and "开工前核对表" in text
        assert "0/10 闭合" in text  # 空 context：探针全开
        assert render_premortem_markdown({"ok": False}) == ""


# ---------------------------------------------------------------------------
# 锚 3：检测探针可执行性
# ---------------------------------------------------------------------------


class TestDetectionProbesExecutable:
    def test_detection_probes_sorted_registered_tuple(self):
        for kind in TASK_KINDS:
            probes = detection_probes(kind)
            assert isinstance(probes, tuple)
            ids = [p.probe_id for p in probes]
            assert ids == sorted(ids)  # 确定性 probe_id 序
            assert all(pid in PROBE_REGISTRY for pid in ids)

    def test_detection_probes_unknown_kind_valueerror(self):
        with pytest.raises(ValueError, match="未知 task_kind"):
            detection_probes("nope")

    @pytest.mark.parametrize("bad_probe", ["nope", 123, None])
    def test_run_probe_unknown_valueerror(self, bad_probe):
        with pytest.raises(ValueError, match="未知检测探针"):
            run_probe(bad_probe)  # type: ignore[arg-type]

    def test_declares_falsy_is_not_declared(self):
        # #364④ 纪律：0/""/None 等 falsy 不算"已声明"
        assert run_probe("launch_isolated", {"background_launch": True})["ok"]
        assert run_probe("launch_isolated", {"background_launch": "harness"})["ok"]
        assert not run_probe("launch_isolated", {"background_launch": 0})["ok"]
        assert not run_probe("launch_isolated", {"background_launch": ""})["ok"]
        assert not run_probe("launch_isolated", {"background_launch": None})["ok"]
        assert not run_probe("launch_isolated", {})["ok"]

    def test_forbids_branch_inline_spec(self):
        spec = ProbeSpec(probe_id="t-forbid", question="前台裸跑在案？",
                         check_kind="forbids", keys=("inline_bare",))
        assert not run_probe(spec, {"inline_bare": True})["ok"]
        assert run_probe(spec, {"other": True})["ok"]
        assert run_probe(spec, {})["ok"]

    def test_in_branch_inline_spec_value_domain(self):
        spec = ProbeSpec(probe_id="t-domain", question="发射形态在值域？",
                         check_kind="in", keys=("launch_mode",),
                         value=("background", "wait_launcher"))
        assert run_probe(spec, {"launch_mode": "background"})["ok"]
        assert not run_probe(spec, {"launch_mode": "inline"})["ok"]
        assert not run_probe(spec, {})["ok"]

    def test_unknown_check_kind_valueerror(self):
        spec = ProbeSpec(probe_id="t-bad", question="?", check_kind="quantum",
                         keys=("k",))
        with pytest.raises(ValueError, match="未知检查类"):
            run_probe(spec, {"k": 1})

    def test_all_registered_probes_executable_and_pure(self):
        for pid in PROBE_REGISTRY:
            a = run_probe(pid, {})
            b = run_probe(pid, {})
            assert a == b  # 纯函数：同输入同输出
            assert a["probe_id"] == pid and a["detail"]
            assert a["ok"] is False  # 空 context 全未声明


# ---------------------------------------------------------------------------
# 锚 4：service 薄封装（JSON 进出）
# ---------------------------------------------------------------------------


class TestPremortemService:
    def test_report_ok_with_markdown(self):
        r = premortem_report("template_registration", {})
        assert r["ok"] and r["task_kind"] == "template_registration"
        assert r["markdown"].startswith("## Pre-mortem")
        assert "#304" in r["markdown"]
        twice = json.dumps(premortem_report("template_registration", {}),
                           ensure_ascii=False, sort_keys=True)
        assert twice == json.dumps(r, ensure_ascii=False, sort_keys=True)

    def test_report_unknown_kind_ok_false_no_raise(self):
        r = premortem_report("bogus")
        assert r["ok"] is False and r["errors"]

    def test_pitfall_notes_deterministic_best_effort(self, monkeypatch):
        """F-16/S3（X6 坑账消费第一接线）：premortem_report 尾附
        pitfall_notes——真索引在场时逐位确定（两次调用 JSON 相等）；
        索引面炸掉时静默 skip（无该键、主路径不阻塞，#105）。"""
        import json as _json

        r1 = premortem_report("real_solve", {"background_launch": True})
        r2 = premortem_report("real_solve", {"background_launch": True})
        assert _json.dumps(r1, ensure_ascii=False, sort_keys=True) ==             _json.dumps(r2, ensure_ascii=False, sort_keys=True)
        if "pitfall_notes" in r1:
            assert isinstance(r1["pitfall_notes"], list)
            assert r1["pitfall_notes"]
            assert all(isinstance(s, str) and s
                       for s in r1["pitfall_notes"])

        import rfauto.service.pitfall_index_service as pis

        def _boom(*a, **kw):
            raise RuntimeError("index exploded")

        monkeypatch.setattr(pis, "load_pitfall_index", _boom)
        r3 = premortem_report("real_solve", {"background_launch": True})
        assert r3["ok"] is True  # 主路径不被增强面故障阻塞
        assert "pitfall_notes" not in r3

    def test_task_kinds_listing(self):
        r = premortem_task_kinds()
        assert r["ok"] and r["n_kinds"] == 5
        assert set(r["task_kinds"]) == set(TASK_KINDS)

    def test_campaign_block_shape_and_open_probes(self):
        blk = campaign_premortem_block(model="wilkinson", recipe="r.yaml")
        assert blk["ok"] and blk["task_kind"] == "param_sweep"
        assert len(blk["top_modes"]) == 10
        assert blk["checklist"] and blk["open_probes"]
        assert blk["n_open_probes"] == len(blk["open_probes"])
        twice = json.dumps(campaign_premortem_block(model="wilkinson",
                                                    recipe="r.yaml"),
                           ensure_ascii=False, sort_keys=True)
        assert twice == json.dumps(blk, ensure_ascii=False, sort_keys=True)

    def test_for_context_kind_inference(self):
        assert premortem_for_context(
            {"task_kind": "calibration"})["task_kind"] == "calibration"
        assert premortem_for_context({"kind": "模板"})[
            "task_kind"] == "template_registration"
        assert premortem_for_context({})["task_kind"] == "param_sweep"  # 缺省战役面

    def test_save_report_roundtrip(self, tmp_path):
        r = premortem_report("real_solve", {"background_launch": True})
        out = tmp_path / "sub" / "premortem.json"
        saved = save_premortem_report(r, out)
        assert saved["ok"] and out.exists()
        back = json.loads(out.read_text(encoding="utf-8"))
        assert back == r


# ---------------------------------------------------------------------------
# 锚 5：消费挂点——campaign_manager.plan_campaign 开工附带块（best-effort）
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
    """同名配方落两个目录（premortem 块只含 recipe 文件名 → 可逐字节比对）。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "limits": {"max_trials": 12},
    }
    d = tmp_path / name
    d.mkdir()
    path = d / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe, allow_unicode=True), encoding="utf-8")
    return path


class TestCampaignKickoffHook:
    def test_plan_attaches_premortem_additive(self, recipe_path):
        from rfauto.service.campaign_manager import (
            CAMPAIGN_SCHEMA,
            plan_campaign,
        )

        plan = plan_campaign(recipe_path)
        assert plan["ok"] and plan["campaign_schema"] == CAMPAIGN_SCHEMA
        blk = plan["premortem"]
        assert blk["ok"] and blk["task_kind"] == "param_sweep"
        assert blk["task_kind_label"] == "参数扫描战役"
        assert len(blk["top_modes"]) == 10
        assert blk["checklist"] and blk["open_probes"]
        # 既有面不受影响（scheduling/阶段队列照旧）
        assert plan["scheduling"]["ok"]
        assert [s["stage"] for s in plan["stages"]][:5] == [
            "calibrate", "prefilter", "tune", "tolerance", "report"]

    def test_plan_premortem_deterministic(self, tmp_path):
        from rfauto.service.campaign_manager import plan_campaign

        blocks = [plan_campaign(_write_same_recipe(tmp_path, f"case{i}"))[
            "premortem"] for i in range(2)]
        a = json.dumps(blocks[0], ensure_ascii=False, sort_keys=True)
        b = json.dumps(blocks[1], ensure_ascii=False, sort_keys=True)
        assert a == b

    def test_plan_premortem_best_effort_on_failure(self, recipe_path, monkeypatch):
        from rfauto.service import campaign_manager

        def _boom(*_a, **_k):
            raise RuntimeError("生成器故障")

        monkeypatch.setattr(
            "rfauto.service.premortem_service.campaign_premortem_block", _boom)
        plan = campaign_manager.plan_campaign(recipe_path)
        assert plan["ok"]  # #105：不阻塞战役计划本体
        assert plan["stages"]
        blk = plan["premortem"]
        assert blk["ok"] is False and "warning" in blk

    def test_save_load_plan_roundtrip_keeps_premortem(self, recipe_path, tmp_path):
        from rfauto.service.campaign_manager import load_plan, plan_campaign, save_plan

        plan = plan_campaign(recipe_path)
        out_dir = tmp_path / "camp"
        save_plan(plan, out_dir)
        loaded = load_plan(out_dir)
        assert loaded["ok"]
        assert loaded["plan"]["premortem"] == plan["premortem"]
