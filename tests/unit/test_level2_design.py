"""§10.10 Level 2 端到端验收集测试：10 句自然语言设计任务。

全部离线（#139：socket 钉死 + LLM 通道 monkeypatch/stub 注入）、确定性、
零真机。覆盖：验收集结构（器件族语义/数值锚 provenance）、双集防污染、
design_chain 七环节链路契约、铁律 7（数值只出自确定性内核/网络，报告数字
全在白名单）、成功率门 ≥7/10 与防空转分支、CLI 薄壳；以及可选第 8 环节
"优化发起（kickoff）"：默认关时锚零漂移、开启时 run_surrogate_loop 被调
（stub 注入 + 一次真实小预算环）、异常/预算耗尽如实记不抛、门与 CLI 透传。
"""

from __future__ import annotations

import json
import socket

import pytest
import yaml
from typer.testing import CliRunner

from rfauto.service.level2_design import (
    ART_KICKOFF,
    DESIGN_FAMILIES,
    DESIGN_TOOLS,
    KICKOFF_MAX_REAL,
    KICKOFF_N_INIT,
    KICKOFF_REQUIREMENT_KEYS,
    KICKOFF_SEED,
    KICKOFF_STATUSES,
    TOOL_EVALUATE,
    TOOL_OPTIMIZE,
    TOOL_PARSE,
    TOOL_REPORT,
    TOOL_ROUTE,
    TOOL_SIMULATE,
    TOOL_SYNTHESIZE,
    default_level2_path,
    design_chain,
    evaluate_metrics,
    kickoff_bounds,
    kickoff_objectives,
    parse_design_intent,
    route_family,
    run_level2_acceptance,
    run_optimize_kickoff,
)

runner = CliRunner()

#: 验收集（tests/gold/level2_design_public.yaml）不随本仓分发（规划中的后续
#: 公开项，见 README 路线图）；缺集时依赖它的测试整体 skip，意图解析等
#: 合成语料测试照常运行。
_LEVEL2_PUBLIC_MISSING = not default_level2_path().exists()
requires_level2_set = pytest.mark.skipif(
    _LEVEL2_PUBLIC_MISSING,
    reason="level2 public validation set not distributed in this repo "
           "(see README roadmap)")

# 本模块绝大多数测试（验收门/设计链/kickoff/CLI）都直接或间接消费验收集，
# 缺集时整模块 skip（意图解析等合成语料测试一并跳过，代价可接受）。
pytestmark = requires_level2_set


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """零网络纪律（#139）：任何套接字创建即炸。"""

    def _boom(*args, **kwargs):
        raise AssertionError("level2 测试禁止任何网络访问")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)


@pytest.fixture(scope="module")
def reference_records():
    """确定性参考链全量记录（模块级跑一次，~1.5s，供验收门测试复用）。"""
    from rfauto.service.agent_bench import load_bench_set

    bench = load_bench_set(default_level2_path())
    assert bench["ok"], bench.get("errors")
    return [design_chain(task) for task in bench["tasks"]]


# ---------------------------------------------------------------------------
# 验收集结构（10 句 NL / ≥4 器件族 / 数值锚 provenance）
# ---------------------------------------------------------------------------

class TestGoldsetStructure:
    def test_loads_with_ten_nl_tasks(self):
        from rfauto.service.agent_bench import load_bench_set

        bench = load_bench_set(default_level2_path())
        assert bench["ok"], bench.get("errors")
        assert bench["n_tasks"] == 10
        assert all(str(t.get("prompt") or "").strip() for t in bench["tasks"])
        cjk = sum(1 for t in bench["tasks"]
                  if any("\u4e00" <= ch <= "\u9fff" for ch in t["prompt"]))
        assert cjk == 10, "验收集必须是中文自然语言任务"

    def test_covers_at_least_four_device_families(self):
        from rfauto.service.agent_bench import load_bench_set

        bench = load_bench_set(default_level2_path())
        families = {t["family"] for t in bench["tasks"]}
        assert len(families) >= 4, families
        assert families <= set(DESIGN_FAMILIES), families

    def test_family_semantics_is_device_family_not_operation(self):
        """§10.10 family=器件族，与 WP3.7 操作族区分，语义不得漂移。"""
        from rfauto.service.agent_bench import load_bench_set

        bench = load_bench_set(default_level2_path())
        families = {t["family"] for t in bench["tasks"]}
        operation_families = {"template_render", "fail_diagnosis", "port_fix",
                              "campaign", "guard"}
        assert not families & operation_families

    def test_every_numeric_anchor_has_provenance(self):
        from rfauto.service.agent_bench import load_bench_set

        bench = load_bench_set(default_level2_path())
        n_numeric = 0
        for t in bench["tasks"]:
            for item in (t.get("expected") or {}).get("numeric") or []:
                n_numeric += 1
                assert str(item.get("source") or "").strip(), \
                    f"{t['id']} 数值锚缺 provenance source"
        assert n_numeric >= 10

    def test_smoke_task_without_numeric_is_legal(self):
        """照 ab001 先例：冒烟任务不设数值锚（fake 响应非物理基准，#207）。"""
        from rfauto.service.agent_bench import load_bench_set

        bench = load_bench_set(default_level2_path())
        no_numeric = [t for t in bench["tasks"]
                      if not (t.get("expected") or {}).get("numeric")]
        assert len(no_numeric) >= 1

    def test_design_kind_marker(self):
        text = default_level2_path().read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        assert data.get("set_kind") == "public"
        assert data.get("design_kind") == "nl_design_level2"


# ---------------------------------------------------------------------------
# 双集防污染
# ---------------------------------------------------------------------------

class TestContamination:
    def test_level2_and_agentbench_ids_disjoint(self):
        from rfauto.service.level2_design import check_set_contamination

        c = check_set_contamination()
        assert c["ok"], c["errors"]
        assert c["overlap_ids"] == []
        assert all(str(t["id"]).startswith("l2d") for t in c["level2"]["tasks"])

    def test_level2_records_are_unknown_to_agentbench(self):
        """跨集泄漏防护：l2d 记录喂 agentbench 公开集必须落 unknown，不得混评。"""
        from rfauto.service.agent_bench import evaluate_agentbench

        report = evaluate_agentbench(
            [{"id": "l2d001_wilkinson_2g4", "trajectory": []}],
            private_path=None)
        assert report["ok"]
        assert "l2d001_wilkinson_2g4" in report["unknown_ids"]
        assert report["sets"]["public"]["n_scored"] == 0


# ---------------------------------------------------------------------------
# NL→spec 抽取与族路由
# ---------------------------------------------------------------------------

class TestIntentParsing:
    def test_wilkinson_prompt_extracts_f0_and_z0(self):
        intent = parse_design_intent(
            "帮我设计一个工作在 2.4GHz 的 Wilkinson 功分器，50 欧系统，"
            "先用综合内核出初值再离线验证响应。")
        assert intent.family == "wilkinson"
        assert intent.source == "keyword"
        assert intent.requirements["f0_ghz"] == 2.4
        assert intent.requirements["z0_ohm"] == 50.0

    def test_atten_prompt_extracts_atten_db(self):
        intent = parse_design_intent(
            "设计一个 6dB π 型衰减器，工作频率 2.5GHz，50 欧系统，验证平坦衰减。")
        assert intent.family == "atten_pi"
        assert intent.requirements["atten_db"] == 6.0
        assert intent.requirements["f0_ghz"] == 2.5

    def test_chinese_family_name_routes(self):
        assert route_family("设计 3.5GHz 威尔金森功分器，两路等分") == "wilkinson"
        assert route_family("来一个 5.2GHz branchline 耦合器") == "branchline"
        assert route_family("3.2GHz 贴片天线用于传感") == "patch"
        assert route_family("2.5GHz 均匀微带传输线") == "mline"

    def test_unknown_prompt_raises(self):
        with pytest.raises(ValueError):
            route_family("帮我写一首诗")

    def test_llm_channel_output_is_used(self):
        def channel(prompt):
            return {"family": "mline", "requirements": {"f0_ghz": 2.5}}

        intent = parse_design_intent("2.4GHz 贴片天线", channel)
        assert intent.source == "llm"
        assert intent.family == "mline"
        assert intent.requirements == {"f0_ghz": 2.5}

    def test_llm_channel_json_string_is_used(self):
        def channel(prompt):
            return json.dumps({"family": "patch", "requirements": {"f0_ghz": 3.2}})

        intent = parse_design_intent("任意", channel)
        assert intent.source == "llm"
        assert intent.family == "patch"

    @pytest.mark.parametrize("payload", [
        "not a json {{{",
        {"family": "slotline"},                       # 禁入族（openEMS 无端口原语）
        {"family": "mline", "requirements": {"f0_ghz": -1.0}},  # 非正需求值
        {"requirements": {}},                          # 缺 family
    ])
    def test_bad_llm_payload_falls_back_to_keyword(self, payload):
        def channel(prompt):
            return payload

        intent = parse_design_intent("2.4GHz Wilkinson 功分器，50 欧", channel)
        assert intent.source == "keyword_fallback"
        assert intent.family == "wilkinson"
        assert intent.requirements["f0_ghz"] == 2.4

    def test_raising_llm_channel_falls_back(self):
        def channel(prompt):
            raise RuntimeError("通道失灵")

        intent = parse_design_intent("2.4GHz 贴片天线", channel)
        assert intent.source == "keyword_fallback"
        assert intent.family == "patch"


# ---------------------------------------------------------------------------
# design_chain：七环节链路契约（零网络）
# ---------------------------------------------------------------------------

class TestDesignChain:
    def test_record_contract_and_trajectory(self):
        from rfauto.service.agent_bench import load_bench_set

        task = load_bench_set(default_level2_path())["tasks"][0]
        rec = design_chain(task)
        assert rec.get("error") is None, rec.get("error")
        assert rec["id"] == task["id"]
        assert [c["tool"] for c in rec["trajectory"]] == list(DESIGN_TOOLS)
        assert rec["trajectory"][0]["args"]["prompt"] == task["prompt"]
        assert rec["artifacts"] == ["design_intent", "synthesis_params",
                                    "s_params", "metrics", "design_report"]
        assert set(rec["numeric"]) == {"f_dip_ghz", "s11_db_min_in_band",
                                       "s21_db_at_dip"}
        assert rec["intent"]["source"] == "keyword"
        assert rec["template_params"] == ["series_w_mm", "shunt_w_mm",
                                          "arm_len_mm"]
        assert rec["provenance"], "provenance 环节缺产物"

    def test_chain_routes_family_from_nl_not_task_metadata(self):
        from rfauto.service.agent_bench import load_bench_set

        task = next(t for t in load_bench_set(default_level2_path())["tasks"]
                    if t["id"] == "l2d004_branchline_2g4")
        rec = design_chain({"id": task["id"], "prompt": task["prompt"]})
        route_call = next(c for c in rec["trajectory"]
                          if c["tool"] == TOOL_ROUTE)
        assert route_call["args"] == {"family": "branchline"}
        assert rec["family"] == "branchline"

    def test_llm_channel_steers_routing_end_to_end(self):
        """LLM 通道注入点：链路全程用通道给出的族（轨迹可复现、可审计）。"""
        from rfauto.service.agent_bench import load_bench_set

        task = next(t for t in load_bench_set(default_level2_path())["tasks"]
                    if t["id"] == "l2d006_patch_2g4")

        def channel(prompt):
            return {"family": "mline", "requirements": {"f0_ghz": 2.4}}

        rec = design_chain(task, channel)
        assert rec["intent"]["source"] == "llm"
        assert rec["family"] == "mline"
        assert rec["numeric"].keys() == {"s11_db_max_in_band",
                                         "s21_db_mean_in_band"}

    def test_step_failure_returns_partial_record_not_raise(self):
        """链路任一步异常 → 部分记录返回（评分时执行轴如实不满），不抛不凑。"""
        rec = design_chain({"id": "t_x", "prompt": "无法路由的一句话"})
        assert "error" in rec
        assert rec["trajectory"] == [{"tool": TOOL_PARSE,
                                      "args": {"prompt": "无法路由的一句话"}}]
        assert rec["artifacts"] == []

    def test_synthesis_params_are_kernel_products(self):
        """铁律 7：几何初值出自综合内核（非 NL 数字、非 LLM 编造）。"""
        from rfauto.core.synthesis import synthesize_wilkinson

        task = {"id": "t", "prompt": "2.4GHz Wilkinson 功分器，50 欧系统"}
        rec = design_chain(task)
        expect = synthesize_wilkinson(f0_ghz=2.4, z0_ohm=50.0).params
        for key, value in expect.items():
            assert rec["synthesis_params"][key] == pytest.approx(float(value))


# ---------------------------------------------------------------------------
# 铁律 7：数值只出自确定性内核/网络；报告数字全在白名单
# ---------------------------------------------------------------------------

class TestIronRule7:
    def test_metrics_track_network_not_intent(self):
        """指标随 S 参数网络走：合成一个 3.0GHz 谷的网络，谷位必须报 3.0。"""
        import numpy as np
        import skrf

        freq = skrf.Frequency(2.0, 4.0, 401, unit="GHz")
        f = freq.f / 1e9
        s11 = 0.7 - 0.6 / (1.0 + ((f - 3.0) / 0.05) ** 2)
        s = np.zeros((401, 2, 2), dtype=complex)
        s[:, 0, 0] = s11
        s[:, 1, 0] = s[:, 0, 1] = np.sqrt(np.maximum(1 - s11 ** 2, 0))
        net = skrf.Network(frequency=freq, s=s, z0=50)

        metrics = evaluate_metrics(net)
        assert metrics["f_dip_ghz"] == pytest.approx(3.0, abs=1e-6)
        assert metrics["s11_db_min_in_band"] == pytest.approx(
            20 * np.log10(0.1), abs=1e-3)
        # 带内包络/均值双变体恒产出（#195 谷深语义）
        assert metrics["s11_db_max_in_band"] > metrics["s11_db_min_in_band"]

    def test_record_numeric_comes_from_model_not_nl(self):
        """patch 谷位由 fake λ/2 反推（≠ NL 要求的 2.4GHz）——数字出自模型。"""
        from rfauto.service.agent_bench import load_bench_set

        task = next(t for t in load_bench_set(default_level2_path())["tasks"]
                    if t["id"] == "l2d006_patch_2g4")
        rec = design_chain(task)
        # f_res_ghz 是谷位键的 patch 侧别名（=metrics.f_dip_ghz），其余键直承 metrics
        assert set(rec["numeric"]) - {"f_res_ghz"} <= set(rec["metrics"])
        assert rec["numeric"]["f_res_ghz"] == pytest.approx(
            rec["metrics"]["f_dip_ghz"])
        assert rec["numeric"]["f_res_ghz"] != pytest.approx(
            rec["intent"]["requirements"]["f0_ghz"])

    def test_report_numbers_all_in_whitelist(self):
        from rfauto.service.report_narrative import audit_narrative, build_whitelist

        rec = design_chain({"id": "t", "prompt": "2.4GHz Wilkinson 功分器，50 欧"})
        data = {"model": rec["family"], "adapter": "fake",
                "metrics": rec["numeric"], "params": rec["synthesis_params"]}
        whitelist = build_whitelist(data, source="level2_design_chain")
        audit = audit_narrative(rec["report"], whitelist)
        assert audit["ok"], audit["violations"]
        assert audit["n_authorized"] >= 1

    def test_unauthorized_number_would_be_caught(self):
        """正控：白名单审计器对未授权数字确实亮红（证明上面的全绿有牙齿）。"""
        from rfauto.service.report_narrative import audit_narrative, build_whitelist

        data = {"metrics": {"f_dip_ghz": 2.3928}}
        whitelist = build_whitelist(data, source="t")
        audit = audit_narrative("谷位 9.877GHz 未经授权。", whitelist)
        assert not audit["ok"]
        assert audit["violations"]


# ---------------------------------------------------------------------------
# 成功率门（§10.10:671 ≥7/10）与防空转
# ---------------------------------------------------------------------------

class TestAcceptanceGate:
    def test_reference_chain_passes_with_margin(self, reference_records):
        r = run_level2_acceptance(records=reference_records)
        assert r["ok"], r["reasons"]
        assert r["gate"] == "PASS"
        assert r["n_tasks"] == 10
        assert r["n_pass"] == 10
        assert r["success_rate"] == pytest.approx(1.0)
        assert r["two_axis"]["abstraction"] == pytest.approx(1.0)
        assert r["two_axis"]["execution"] == pytest.approx(1.0)
        assert r["requirement_coverage"]["n_covered"] == 7
        assert r["families"] == sorted(set(r["families"]))
        assert len(r["families"]) >= 4

    def test_default_provider_path_passes(self):
        """缺省（不传 records）= 链内确定性参考链，全程零 LLM 零网络。"""
        r = run_level2_acceptance()
        assert r["ok"], r["reasons"]
        assert r["n_pass"] >= 7

    def test_min_success_threshold_enforced(self, reference_records):
        r = run_level2_acceptance(records=reference_records, min_success=11)
        assert not r["ok"]
        assert r["gate"] == "FAIL"
        assert any("成功率" in s for s in r["reasons"])
        assert r["per_task"] and len(r["per_task"]) == 10

    @staticmethod
    def _degrade(rec):
        bad = dict(rec)
        bad["artifacts"] = [a for a in rec["artifacts"] if a != "s_params"]
        bad["numeric"] = {}
        return bad

    def test_degraded_records_shrink_pass_count(self, reference_records):
        """3 个坏记录 → 恰好 7/10 过门；4 个坏 → 6/10 红门（无种子彩票）。"""
        records = list(reference_records)
        broken = [self._degrade(r) for r in records[:3]]
        r7 = run_level2_acceptance(records=broken + records[3:])
        assert r7["ok"] and r7["n_pass"] == 7
        records2 = list(reference_records)
        broken4 = [self._degrade(r) for r in records2[:4]]
        r6 = run_level2_acceptance(records=broken4 + records2[4:])
        assert not r6["ok"] and r6["n_pass"] == 6

    def test_wrong_routing_fails_that_task(self, reference_records):
        """路由错的记录：FCA 掉 + mline 数值对不上 wilkinson 锚 → 执行轴不满。"""
        records = list(reference_records)
        wrong = dict(records[0])
        wrong["trajectory"] = [
            {"tool": TOOL_PARSE, "args": {"prompt": "x"}},
            {"tool": TOOL_ROUTE, "args": {"family": "mline"}},
            {"tool": TOOL_SYNTHESIZE, "args": {"family": "mline", "f0_ghz": 2.4}},
            {"tool": TOOL_SIMULATE, "args": {"family": "mline", "adapter": "fake"}},
            {"tool": TOOL_EVALUATE, "args": {"family": "mline"}},
            {"tool": TOOL_REPORT, "args": {"family": "mline"}},
        ]
        wrong["numeric"] = {"s11_db_max_in_band": -80.0,
                            "s21_db_mean_in_band": -0.057}
        r = run_level2_acceptance(records=[wrong, *records[1:]])
        assert r["n_pass"] == 9 and r["ok"]
        row = next(p for p in r["per_task"] if p["id"] == records[0]["id"])
        assert not row["pass"]
        assert row["numeric_failed"]

    def test_unknown_id_rejected(self, reference_records):
        records = [*reference_records, {"id": "bogus_id", "trajectory": []}]
        r = run_level2_acceptance(records=records)
        assert not r["ok"]
        assert any("未知任务" in s for s in r["reasons"])

    def test_partial_coverage_rejected(self, reference_records):
        r = run_level2_acceptance(records=reference_records[:1])
        assert not r["ok"]
        assert any("未覆盖全部" in s for s in r["reasons"])

    def test_empty_records_rejected(self):
        r = run_level2_acceptance(records=[])
        assert not r["ok"]
        assert any("空跑" in s for s in r["reasons"])

    def test_broken_set_rejected(self, tmp_path):
        bad = tmp_path / "bad_level2.yaml"
        bad.write_text(yaml.safe_dump({"version": 1, "tasks": [
            {"id": "x1", "level": 1, "prompt": "p",
             "expected": {"calls": [{"tool": "t", "args": {}}]}},
            {"id": "x1", "level": 1, "prompt": "p",
             "expected": {"calls": [{"tool": "t", "args": {}}]}},
        ]}, allow_unicode=True), encoding="utf-8")
        r = run_level2_acceptance(records=[{"id": "x1", "trajectory": []}],
                                  set_path=bad)
        assert not r["ok"]
        assert r["reasons"], "结构坏集必须带错误清单"

    def test_contaminated_set_rejected(self, tmp_path):
        """与 agentbench 公开集 id 撞车 → 防污染硬 FAIL。"""
        from rfauto.service.agent_bench import load_bench_set

        ab_task = load_bench_set()["tasks"][0]
        bad = tmp_path / "contaminated.yaml"
        bad.write_text(yaml.safe_dump({"version": 1, "tasks": [
            {"id": ab_task["id"], "family": "wilkinson", "level": 1,
             "prompt": "p", "expected": {"calls": [{"tool": "t", "args": {}}]}},
        ]}, allow_unicode=True), encoding="utf-8")
        r = run_level2_acceptance(records=[{"id": ab_task["id"],
                                            "trajectory": []}], set_path=bad)
        assert not r["ok"]
        assert any("污染" in s or "加载失败" in s for s in r["reasons"])

    def test_coverage_matrix_anchors_exist_in_tree(self, reference_records):
        r = run_level2_acceptance(records=reference_records)
        repo_root = default_level2_path().parents[2]
        for row in r["requirement_coverage"]["links"]:
            assert row["covered"], row
            for anchor in row["anchors"]:
                path, symbol = anchor.rsplit(":", 1)
                assert (repo_root / path).exists(), anchor
                src = (repo_root / path).read_text(encoding="utf-8")
                # 方法级锚（A.b）按类名/def 双查；其余按字面
                leaf = symbol.split(".")[-1]
                assert (symbol in src or f"def {leaf}" in src
                        or f"class {leaf}" in src), anchor


# ---------------------------------------------------------------------------
# CLI 薄壳（bench level2）
# ---------------------------------------------------------------------------

class TestCliShell:
    def _invoke(self, *args):
        from rfauto.cli.bench_app import bench_app

        return runner.invoke(bench_app, ["level2", *args])

    def test_bench_level2_pass(self, reference_records):
        import tempfile

        with tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(reference_records, fh, ensure_ascii=False)
            path = fh.name
        result = self._invoke("--records", path)
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["gate"] == "PASS"
        assert payload["n_pass"] == 10

    def test_bench_level2_default_reference_chain(self):
        result = self._invoke()
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["gate"] == "PASS"
        assert payload["n_tasks"] == 10

    def test_bench_level2_threshold_exit_code(self, reference_records):
        import tempfile

        with tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(reference_records, fh, ensure_ascii=False)
            path = fh.name
        result = self._invoke("--records", path, "--min-success", "11")
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["gate"] == "FAIL"

    def test_bench_level2_missing_records_file(self):
        result = self._invoke("--records", "Z:/no/such/file.json")
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# 可选第 8 环节：优化发起（kickoff）——默认关锚零漂移 / 开启真实发起 / 不抛
# ---------------------------------------------------------------------------

_SEVEN_STEP_ARTIFACTS = ["design_intent", "synthesis_params", "s_params",
                         "metrics", "design_report"]
_LOOP_TARGET = "rfauto.optimization.surrogate_loop.run_surrogate_loop"


def _install_loop_stub(monkeypatch, *, best="auto", raise_exc=None):
    """把 run_surrogate_loop 钉成可计数 stub（零真跑）。

    best="auto" → 返回带 best 的正常返回体；best=None → 预算耗尽无 best；
    raise_exc → 调用即抛（模拟环内致命异常）。
    """
    calls: list[dict] = []

    def stub(bounds, objectives, evaluate_fn, **kw):
        calls.append({"bounds": dict(bounds), "objectives": list(objectives),
                      "evaluate_fn": evaluate_fn, "kw": dict(kw)})
        if raise_exc is not None:
            raise raise_exc
        best_val = best
        if best == "auto":
            first = next(iter(bounds))
            lo, hi = bounds[first]
            best_val = {"params": {first: (lo + hi) / 2.0},
                        "metrics": {"s11_db_min_in_band": -31.5}, "cost": 0.0}
        return {"ok": True, "algorithm": "surrogate_loop", "best": best_val,
                "n_real_used": int(kw.get("max_real", 0)), "stop_reason": "budget",
                "n_failures": 0, "real_cost_trace": [2.0, 1.0, 0.5]}

    monkeypatch.setattr(_LOOP_TARGET, stub)
    return calls


def _wilkinson_task():
    from rfauto.service.agent_bench import load_bench_set

    return next(t for t in load_bench_set(default_level2_path())["tasks"]
                if t["id"] == "l2d001_wilkinson_2g4")


class TestOptimizeKickoffDefaultOff:
    def test_default_record_is_byte_identical_seven_step_contract(self, monkeypatch):
        """默认关：轨迹/工件/键集与七环节版本完全相同，且环 stub 零调用。"""
        calls = _install_loop_stub(monkeypatch)
        rec = design_chain(_wilkinson_task())
        assert rec.get("error") is None
        assert [c["tool"] for c in rec["trajectory"]] == list(DESIGN_TOOLS)
        assert TOOL_OPTIMIZE not in {c["tool"] for c in rec["trajectory"]}
        assert rec["artifacts"] == _SEVEN_STEP_ARTIFACTS
        assert "kickoff" not in rec and "kickoff_status" not in rec
        assert "optimize_kickoff" not in rec["provenance"]
        assert "优化发起" not in rec["report"]
        assert calls == []

    def test_default_gate_anchor_unchanged_and_counts_absent(self, reference_records):
        """goldset 10/10 锚不变；optimize 汇总如实报 enabled=False / 全 absent。"""
        r = run_level2_acceptance(records=reference_records)
        assert r["ok"] and r["n_pass"] == 10 and r["n_tasks"] == 10
        assert r["requirement_coverage"]["n_covered"] == 7
        assert r["optimize"] == {"enabled": False, "kickoff_counts": {"absent": 10}}
        assert all(row["kickoff_status"] is None for row in r["per_task"])

    def test_optimize_tool_not_in_seven_step_vocabulary(self):
        """TOOL_OPTIMIZE 是可选环词汇，不得混入 goldset 裁判口径 DESIGN_TOOLS。"""
        assert TOOL_OPTIMIZE == "design.optimize"
        assert TOOL_OPTIMIZE not in DESIGN_TOOLS
        assert ART_KICKOFF not in _SEVEN_STEP_ARTIFACTS


class TestOptimizeKickoffEnabled:
    def test_enabled_calls_loop_once_with_fixed_seed_and_small_budget(self, monkeypatch):
        calls = _install_loop_stub(monkeypatch)
        rec = design_chain(_wilkinson_task(), enable_optimize=True)
        assert rec.get("error") is None
        assert len(calls) == 1
        kw = calls[0]["kw"]
        assert kw["seed"] == KICKOFF_SEED == 42
        assert kw["n_init"] == KICKOFF_N_INIT and kw["max_real"] == KICKOFF_MAX_REAL
        assert kw["n_init"] <= kw["max_real"] <= 10, "kickoff 必须是小预算"
        # 搜索域由综合初值确定性派生：键集 = 综合参数 − 需求量键，端点夹住初值
        design_vars = set(rec["synthesis_params"]) - set(KICKOFF_REQUIREMENT_KEYS)
        assert set(calls[0]["bounds"]) == design_vars
        assert "f0_ghz" not in calls[0]["bounds"], "需求量不可作为优化变量"
        for key, (lo, hi) in calls[0]["bounds"].items():
            assert lo < rec["synthesis_params"][key] < hi
        assert callable(calls[0]["evaluate_fn"])
        assert rec["kickoff"]["fixed_params"] == {
            k: v for k, v in rec["synthesis_params"].items() if k not in design_vars}

    def test_enabled_record_contract_appends_eighth_step(self, monkeypatch):
        _install_loop_stub(monkeypatch)
        rec = design_chain(_wilkinson_task(), enable_optimize=True)
        tools = [c["tool"] for c in rec["trajectory"]]
        assert tools == [*DESIGN_TOOLS, TOOL_OPTIMIZE], "第 8 环追加于七环节之后"
        assert rec["trajectory"][-1]["args"] == {
            "family": "wilkinson", "adapter": "fake", "seed": KICKOFF_SEED}
        assert rec["artifacts"] == [*_SEVEN_STEP_ARTIFACTS, ART_KICKOFF]
        assert rec["kickoff_status"] == "completed"
        assert rec["kickoff"]["kickoff_status"] == "completed"
        assert rec["kickoff"]["best"]["metrics"]["s11_db_min_in_band"] == -31.5
        assert rec["kickoff"]["n_real_used"] == KICKOFF_MAX_REAL
        prov = rec["provenance"]["optimize_kickoff"]
        assert prov["kickoff_status"] == "completed"
        assert prov["seed"] == KICKOFF_SEED and prov["algorithm"] == "surrogate_loop"
        assert prov["adapter"] == "fake" and prov["stop_reason"] == "budget"
        assert prov["real_cost_trace"] == [2.0, 1.0, 0.5]
        assert prov["artifact_path"] is None, "缺省不落盘（不污染 runs/）"
        assert "优化发起" in rec["report"] and "kickoff.best" in rec["report"]
        # 七环节数值锚不被 kickoff 触碰
        assert set(rec["numeric"]) == {"f_dip_ghz", "s11_db_min_in_band",
                                       "s21_db_at_dip"}

    def test_enabled_still_passes_two_axis_scoring(self, monkeypatch):
        """尾部追加第 8 环不破坏 goldset 子序列匹配：单任务两轴仍满分。"""
        from rfauto.service.agent_bench import score_agent_task

        _install_loop_stub(monkeypatch)
        task = _wilkinson_task()
        rec = design_chain(task, enable_optimize=True)
        scored = score_agent_task(task, rec)
        assert scored["tsa"] == 1 and scored["fca"] == 1
        assert scored["execution"] == pytest.approx(1.0)

    def test_enabled_report_stays_whitelist_clean(self, monkeypatch):
        """铁律 7：追加段零数字——按七环节白名单审计整份报告仍全绿。"""
        from rfauto.service.report_narrative import audit_narrative, build_whitelist

        _install_loop_stub(monkeypatch)
        rec = design_chain(_wilkinson_task(), enable_optimize=True)
        data = {"model": rec["family"], "adapter": "fake",
                "metrics": rec["numeric"], "params": rec["synthesis_params"]}
        audit = audit_narrative(rec["report"], build_whitelist(data, source="t"))
        assert audit["ok"], audit["violations"]

    def test_budget_exhausted_without_best_is_launched_not_completed(self, monkeypatch):
        """发起≠完成：环正常返回但无 best → launched（如实，不凑 completed）。"""
        _install_loop_stub(monkeypatch, best=None)
        rec = design_chain(_wilkinson_task(), enable_optimize=True)
        assert rec.get("error") is None
        assert rec["kickoff_status"] == "launched"
        assert rec["kickoff"]["best"] is None
        assert rec["kickoff"]["stop_reason"] == "budget"
        assert "发起不等于完成" in rec["report"]
        assert rec["artifacts"][-1] == ART_KICKOFF

    def test_loop_exception_is_recorded_not_raised(self, monkeypatch):
        """环内致命异常 → kickoff_status=failed + error 如实记录；链路其余七环节
        工件完整、record 不带 error（异常被隔离在第 8 环）。"""
        _install_loop_stub(monkeypatch, raise_exc=RuntimeError("代理拟合崩了"))
        rec = design_chain(_wilkinson_task(), enable_optimize=True)
        assert rec.get("error") is None
        assert rec["kickoff_status"] == "failed"
        assert "RuntimeError" in rec["kickoff"]["error"]
        assert "代理拟合崩了" in rec["kickoff"]["error"]
        assert rec["kickoff"]["best"] is None
        assert rec["provenance"]["optimize_kickoff"]["kickoff_status"] == "failed"
        assert "error" in rec["provenance"]["optimize_kickoff"]
        assert rec["artifacts"][:5] == _SEVEN_STEP_ARTIFACTS
        assert set(rec["numeric"]) == {"f_dip_ghz", "s11_db_min_in_band",
                                       "s21_db_at_dip"}
        assert "已如实记录" in rec["report"]

    def test_loop_reporting_ok_false_is_failed(self, monkeypatch):
        """环返回 ok=False（如搜索空间被拒）→ failed，errors 文本进 error。"""
        def stub(bounds, objectives, evaluate_fn, **kw):
            return {"ok": False, "errors": ["搜索空间为空（bounds 缺失）"]}

        monkeypatch.setattr(_LOOP_TARGET, stub)
        rec = design_chain(_wilkinson_task(), enable_optimize=True)
        assert rec["kickoff_status"] == "failed"
        assert "搜索空间为空" in rec["kickoff"]["error"]

    def test_enabled_but_chain_failed_upstream_is_skipped(self, monkeypatch):
        """链路前段失败（无法路由）→ 不发起：kickoff_status=skipped，环零调用。"""
        calls = _install_loop_stub(monkeypatch)
        rec = design_chain({"id": "t_x", "prompt": "帮我写一首诗"}, enable_optimize=True)
        assert "error" in rec
        assert rec["kickoff_status"] == "skipped"
        assert rec["kickoff"]["kickoff_status"] == "skipped"
        assert calls == []
        assert TOOL_OPTIMIZE not in {c["tool"] for c in rec["trajectory"]}

    def test_out_dir_persists_loop_result_and_records_path(self, monkeypatch, tmp_path):
        _install_loop_stub(monkeypatch)
        out_dir = tmp_path / "kick"
        rec = design_chain(_wilkinson_task(), enable_optimize=True,
                           optimize_out_dir=out_dir)
        path = rec["kickoff"]["artifact_path"]
        assert path and path.endswith("surrogate_kickoff_l2d001_wilkinson_2g4.json")
        assert (out_dir / "surrogate_kickoff_l2d001_wilkinson_2g4.json").exists()
        assert rec["provenance"]["optimize_kickoff"]["artifact_path"] == path
        payload = json.loads((out_dir / "surrogate_kickoff_l2d001_wilkinson_2g4.json")
                             .read_text(encoding="utf-8"))
        assert payload["kickoff"]["kickoff_status"] == "completed"
        assert payload["loop_result"]["stop_reason"] == "budget"
        assert "artifact_path" in rec["report"]

    def test_statuses_constant_covers_all_emitted_states(self):
        assert set(KICKOFF_STATUSES) == {"completed", "launched", "failed", "skipped"}


@pytest.mark.filterwarnings("ignore::sklearn.exceptions.ConvergenceWarning")
class TestOptimizeKickoffRealLoop:
    """一次真实小预算环（fake 采样器、零真机、秒级）：证明接环不是 stub 幻觉。

    ConvergenceWarning 来自环内 B-33 GP 代理质量报告对 ≤5 样本的核超参拟合
    （optimization 层既有行为，与本项无关），按类压制不改环。"""

    def test_real_loop_runs_within_budget_and_is_seed_reproducible(self, tmp_path):
        from rfauto.service.level2_design import synthesize_initial

        synth = synthesize_initial("wilkinson", {"f0_ghz": 2.4, "z0_ohm": 50.0})
        k1 = run_optimize_kickoff("wilkinson", synth, out_dir=tmp_path, tag="real_a")
        k2 = run_optimize_kickoff("wilkinson", synth)
        assert k1["kickoff_status"] in {"completed", "launched"}, k1.get("error")
        assert k1["kickoff_status"] in KICKOFF_STATUSES
        assert 1 <= k1["n_real_used"] <= KICKOFF_MAX_REAL
        assert len(k1["real_cost_trace"]) == k1["n_real_used"]
        design_vars = set(synth["params"]) - set(KICKOFF_REQUIREMENT_KEYS)
        assert set(k1["bounds"]) == design_vars
        assert set(k1["fixed_params"]) == set(synth["params"]) - design_vars
        assert (tmp_path / "surrogate_kickoff_real_a.json").exists()
        # seed 固定 → 同输入两次真跑逐字节复现（#158 配对实验语义）
        assert k2["real_cost_trace"] == k1["real_cost_trace"]
        assert k2["kickoff_status"] == k1["kickoff_status"]
        if k1["best"] is not None:
            assert set(k1["best"]["params"]) == design_vars
            for key, (lo, hi) in k1["bounds"].items():
                assert lo - 1e-9 <= k1["best"]["params"][key] <= hi + 1e-9
            assert k2["best"]["cost"] == pytest.approx(k1["best"]["cost"])

    def test_real_loop_atten_pi_fixes_requested_attenuation(self):
        """需求量固定不入搜索域：atten_pi 6dB 任务的 atten_db 进 fixed_params，
        目标区间按要求值落 [-7, -5]（环不能靠改需求量作弊）。"""
        from rfauto.service.level2_design import synthesize_initial

        synth = synthesize_initial("atten_pi", {"atten_db": 6.0, "f0_ghz": 2.5})
        k = run_optimize_kickoff("atten_pi", synth)
        assert k["kickoff_status"] in {"completed", "launched"}, k.get("error")
        assert "atten_db" not in k["bounds"]
        assert k["fixed_params"]["atten_db"] == 6.0
        assert k["objectives"][0]["value"] == [-7.0, -5.0]
        assert k["objectives"][0]["op"] == "mean_within"

    @pytest.mark.parametrize("family", DESIGN_FAMILIES)
    def test_bounds_and_objectives_are_deterministic_per_family(self, family):
        """护栏：搜索域端点单调夹住初值、剔除需求量/非正参数；目标按族取 #195
        谷深语义。"""
        from rfauto.core.objectives import MetricOp
        from rfauto.service.level2_design import synthesize_initial

        synth = synthesize_initial(family, {})
        params = dict(synth["params"])
        bounds = kickoff_bounds({**params, "neg": -1.0, "zero": 0.0})
        design_vars = set(params) - set(KICKOFF_REQUIREMENT_KEYS)
        assert design_vars, "每族至少有一个可优化的设计变量"
        assert set(bounds) == design_vars, "需求量/非正参数必须剔除"
        for key, (lo, hi) in bounds.items():
            assert 0.0 < lo < params[key] < hi
            assert lo == pytest.approx(params[key] * 0.8)
            assert hi == pytest.approx(params[key] * 1.2)
        objs = kickoff_objectives(family, 2.4, synth["effective_requirements"])
        assert len(objs) == 1
        obj = objs[0]
        if family in ("wilkinson", "branchline", "patch"):
            assert obj.metric == "s11_db_min" and obj.op == MetricOp.MAX_BELOW
        elif family == "atten_pi":
            assert obj.metric == "s21_db" and obj.op == MetricOp.MEAN_WITHIN
            atten = synth["effective_requirements"]["atten_db"]
            assert obj.value == [-(atten + 1.0), -(atten - 1.0)]
        else:
            assert obj.metric == "s11_db" and obj.op == MetricOp.MAX_BELOW
        assert obj.band[0] < 2.4 < obj.band[1]

    def test_bounds_rejects_bad_span_and_empty_input(self):
        with pytest.raises(ValueError):
            kickoff_bounds({"a_mm": 1.0}, rel_span=1.0)
        with pytest.raises(ValueError):
            kickoff_bounds({"a_mm": 1.0}, rel_span=0.0)
        assert kickoff_bounds({}) == {}
        assert kickoff_bounds({"f0_ghz": 2.4}) == {}


class TestOptimizeKickoffGateAndCli:
    def test_gate_passthrough_enables_kickoff_on_every_task(self, monkeypatch):
        calls = _install_loop_stub(monkeypatch)
        r = run_level2_acceptance(enable_optimize=True)
        assert r["ok"] and r["n_pass"] == 10
        assert r["requirement_coverage"]["n_covered"] == 7, "验收矩阵口径仍是七环节"
        assert r["optimize"] == {"enabled": True, "kickoff_counts": {"completed": 10}}
        assert all(row["kickoff_status"] == "completed" for row in r["per_task"])
        assert len(calls) == 10
        assert {c["kw"]["seed"] for c in calls} == {KICKOFF_SEED}

    def test_gate_with_external_records_does_not_rerun(self, monkeypatch, reference_records):
        """已成记录不重跑：enable_optimize 对 --records 路径无副作用。"""
        calls = _install_loop_stub(monkeypatch)
        r = run_level2_acceptance(records=reference_records, enable_optimize=True)
        assert r["ok"] and r["n_pass"] == 10
        assert r["optimize"]["enabled"] is True
        assert r["optimize"]["kickoff_counts"] == {"absent": 10}
        assert calls == []

    def test_gate_failed_kickoff_does_not_change_pass_verdict(self, monkeypatch):
        """kickoff 不参与 pass 判定：环全部异常，门仍按七环节判 10/10。"""
        _install_loop_stub(monkeypatch, raise_exc=RuntimeError("boom"))
        r = run_level2_acceptance(enable_optimize=True)
        assert r["ok"] and r["n_pass"] == 10
        assert r["optimize"]["kickoff_counts"] == {"failed": 10}

    def test_cli_enable_optimize_flag_passthrough(self, monkeypatch, tmp_path):
        from rfauto.cli.bench_app import bench_app

        calls = _install_loop_stub(monkeypatch)
        out_dir = tmp_path / "cli_kick"
        result = runner.invoke(bench_app, [
            "level2", "--enable-optimize", "--optimize-out-dir", str(out_dir)])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["gate"] == "PASS" and payload["n_pass"] == 10
        assert payload["optimize"] == {"enabled": True, "kickoff_counts": {"completed": 10}}
        assert len(calls) == 10
        assert len(list(out_dir.glob("surrogate_kickoff_*.json"))) == 10

    def test_cli_default_keeps_optimize_off(self, monkeypatch):
        from rfauto.cli.bench_app import bench_app

        calls = _install_loop_stub(monkeypatch)
        result = runner.invoke(bench_app, ["level2"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["optimize"] == {"enabled": False, "kickoff_counts": {"absent": 10}}
        assert calls == []
