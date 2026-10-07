"""XN-9 提示注入对抗测试集测试（ge8c 席C6）。

锚定：
- 语料确定性（笛卡尔积，无随机；同输入逐字节复现）；
- 类别/算子覆盖：7 类种子 × 8 算子封闭断言（扩库=显式改锚）；
- 检测器面（#139）：缺省走 agent_safety 确定性正则（零网络零 LLM）；
  detector_fn 可注入（mock 模型检测器两态：全中/全漏）；
- 回归钉：真实正则面对 plain 基线 100% 命中；变异逃逸如实入账；
  corpus_gate PASS/FAIL 双态（阈值语义 + 逃逸清单随门带出）；
- 诚实语义：逃逸不隐藏（报告含逃逸清单标题）。
"""

from __future__ import annotations

import json

import pytest

from rfauto.service.injection_corpus import (
    INJECTION_CORPUS_SCHEMA,
    MUTATION_OPERATORS,
    SEED_PAYLOADS,
    build_corpus,
    corpus_gate,
    evaluate_corpus,
    render_corpus_report,
)

_EXPECTED_CATEGORIES = {
    "instruction_override", "system_prompt_leak", "command_execution",
    "role_play", "tool_call_syntax", "concealment", "delimiter_escape",
}
_EXPECTED_OPERATORS = {"plain", "ws_pad", "case_flip", "fence", "ext_data",
                       "benign_prefix", "duplicate", "zh_punct"}


class TestCorpus:
    def test_schema_and_shape(self) -> None:
        c = build_corpus()
        assert c["ok"] is True
        assert c["schema"] == INJECTION_CORPUS_SCHEMA
        assert c["n_seeds"] == 10
        assert c["n_variants"] == 80  # 10 种子 × 8 算子（扩库=显式改锚）
        assert all("text" in v and v["expected"] == "flagged"
                   for v in c["variants"])

    def test_category_coverage_closed(self) -> None:
        cats = {s["category"] for s in SEED_PAYLOADS}
        assert cats == _EXPECTED_CATEGORIES
        # 与 agent_safety 规则族词表对齐（对偶面一致性）
        import rfauto.service.agent_safety as as_mod
        rule_cats = {r["category"] for r in as_mod._INJECTION_RULES}
        assert cats <= rule_cats

    def test_operator_coverage_closed(self) -> None:
        assert {o for o, _, _ in MUTATION_OPERATORS} == _EXPECTED_OPERATORS

    def test_deterministic(self) -> None:
        a = json.dumps(build_corpus(), ensure_ascii=False, sort_keys=True)
        b = json.dumps(build_corpus(), ensure_ascii=False, sort_keys=True)
        assert a == b

    def test_seed_subset_and_unknown_operator(self) -> None:
        c = build_corpus(operators=("plain", "fence"))
        assert c["n_variants"] == 20  # 10 × 2
        with pytest.raises(ValueError, match="未知变异算子"):
            build_corpus(operators=("yolo",))

    def test_mutations_actually_mutate(self) -> None:
        # 英文种子上三算子必互异（中文种子上 ws_pad/case_flip 是合法 no-op）
        c = build_corpus(
            seeds=(next(s for s in SEED_PAYLOADS if s["id"] == "S01"),),
            operators=("plain", "ws_pad", "case_flip"))
        texts = [v["text"] for v in c["variants"]]
        assert len(set(texts)) == 3  # 每算子产出不同文本


class TestEvaluate:
    def test_plain_baseline_full_hit(self) -> None:
        # 回归钉核心：原样基线必须 100% 命中（规则面退化即红）
        c = build_corpus(operators=("plain",))
        e = evaluate_corpus(c)
        assert e["n_escape"] == 0
        assert e["flag_rate"] == 1.0

    def test_mock_detector_all_hit(self) -> None:
        c = build_corpus(operators=("plain", "fence"))

        def all_flag(t: str) -> dict:
            return {"flagged": True, "reasons": [{"rule": "mock"}]}

        e = evaluate_corpus(c, detector_fn=all_flag)
        assert e["n_flagged"] == e["n_variants"] == 20
        assert all("mock" in r["rules_hit"] for r in e["results"])

    def test_mock_detector_all_miss_escapes_honest(self) -> None:
        c = build_corpus(operators=("plain",))

        def all_miss(_t: str) -> dict:
            return {"flagged": False, "reasons": []}

        e = evaluate_corpus(c, detector_fn=all_miss)
        assert e["n_flagged"] == 0
        assert e["n_escape"] == e["n_variants"]
        assert e["escape_by_operator"] == {"plain": e["n_variants"]}
        assert len(e["escapes"]) == e["n_variants"]

    def test_ext_data_variants_caught_by_default(self) -> None:
        # 定界符逃逸面：外部数据块包裹后正则面仍应命中（规则不因包裹失效）
        c = build_corpus(seeds=tuple(s for s in SEED_PAYLOADS
                                     if s["category"] != "delimiter_escape"),
                         operators=("ext_data",))
        e = evaluate_corpus(c)
        assert e["flag_rate"] >= 0.5  # 包裹不天然致盲（如实门槛，缺口会亮出）


class TestGate:
    def test_pass_and_fail(self) -> None:
        c = build_corpus(operators=("plain",))
        good = evaluate_corpus(c)
        g = corpus_gate(good, min_flag_rate=0.9)
        assert g["verdict"] == "PASS"
        bad = evaluate_corpus(c, detector_fn=lambda _t: {"flagged": False})
        g2 = corpus_gate(bad, min_flag_rate=0.9)
        assert g2["verdict"] == "FAIL"
        assert len(g2["escapes"]) == bad["n_variants"]
        assert g2["escapes"]  # 逃逸清单随门带出

    def test_gate_threshold_semantics(self) -> None:
        c = build_corpus(operators=("plain",))
        e = evaluate_corpus(c, detector_fn=lambda _t: {"flagged": False})
        g = corpus_gate(e, min_flag_rate=0.0)
        assert g["verdict"] == "PASS"  # 阈值 0 恒过（显式放宽语义）


class TestReport:
    def test_report_contains_escape_section(self) -> None:
        c = build_corpus(operators=("plain",))
        e = evaluate_corpus(c, detector_fn=lambda _t: {"flagged": False})
        md = render_corpus_report(e)
        assert "逃逸清单" in md
        assert "flag_rate=0.0000" in md

    def test_report_failure_honest(self) -> None:
        md = render_corpus_report({"ok": False, "errors": ["x"]})
        assert "失败" in md

    def test_default_detector_is_deterministic(self) -> None:
        c = build_corpus(operators=("plain",))
        e1 = evaluate_corpus(c)
        e2 = evaluate_corpus(c)
        assert json.dumps(e1, sort_keys=True) == json.dumps(e2, sort_keys=True)
