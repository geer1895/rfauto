"""AD-N4 数据侦探叙事测试（ge8c 席C6）。

锚定：
- 四段式齐全（findings/hypotheses/evidence/conclusion 固定序段名）；
- 数字白名单强制（F9 纪律复用）：注入 llm_fn 产出未授权数字 → fallback
  回模板且 violations 保留 / reject 则 ok=False；模板路径零未授权数字；
- #139 通道钉：不注入 llm_fn 时绝不触发（哨兵函数炸即红）；
- 负例：explain not-ok 转错误信封；非法 on_unauthorized 抛 ValueError；
- 确定性：同输入两次 JSON sort_keys 往返逐字节一致。
"""

from __future__ import annotations

import json

import pytest

from rfauto.service.data_detective import (
    DATA_DETECTIVE_SCHEMA,
    DETECTIVE_SECTIONS,
    data_detective_report,
    render_detective_markdown,
)

#: 构造的 explain_run 输出（契约形状按 explain_run 实测钉）。
_FAKE_EXPLAIN: dict = {
    "ok": True,
    "run_dir": "runs/fake_run",
    "playbook": {"path": "knowledge/diagnostics/playbook.yaml",
                 "schema": "rfauto-diag-playbook-v1", "n_rules": 10},
    "meta": {"model": "mline"},
    "health_verdict": "FAIL",
    "fingerprints": {
        "sparam_passivity_violation": {"evidence": ["meta: max|S|=1.04"]},
        "fdtd_tail_not_decayed": {"tail_ratio": 0.31,
                                  "et_path": "runs/fake_run/fdtd/et"},
    },
    "matched_rules": [
        {"id": "fdtd_truncation_artifact",
         "root_cause_family": "fdtd_truncation_artifact",
         "matched_fingerprints": ["sparam_passivity_violation",
                                  "fdtd_tail_not_decayed"],
         "evidence": {},
         "forensic_commands": ["看 et 尾段：tail -n 5 <run>/fdtd/et"],
         "pit_refs": ["#262"],
         "notes": "窄 FC 窗截断长脉冲"},
    ],
    "candidates": ["fdtd_truncation_artifact"],
    "skipped_rules": [],
    "overall": "candidates",
}

class TestFourSections:
    def test_sections_complete_and_ordered(self) -> None:
        r = data_detective_report(_FAKE_EXPLAIN)
        assert r["ok"] is True
        assert tuple(r["sections"].keys()) == DETECTIVE_SECTIONS
        assert r["schema"] == DATA_DETECTIVE_SCHEMA

    def test_findings_echo_detector_output(self) -> None:
        r = data_detective_report(_FAKE_EXPLAIN)
        fps = {f["fingerprint"] for f in r["sections"]["findings"]}
        assert fps == {"sparam_passivity_violation", "fdtd_tail_not_decayed"}
        refs = r["sections"]["findings"][0]["artifact_refs"]
        assert any("fdtd/et" in x for x in refs)

    def test_hypotheses_and_evidence_chain(self) -> None:
        r = data_detective_report(_FAKE_EXPLAIN)
        h = r["sections"]["hypotheses"]
        assert h[0]["root_cause_family"] == "fdtd_truncation_artifact"
        assert h[0]["pit_refs"] == ["#262"]
        e = r["sections"]["evidence"]
        assert "tail -n 5" in e[0]["forensic_commands"][0]

    def test_no_hit_shape(self) -> None:
        empty = dict(_FAKE_EXPLAIN, fingerprints={}, matched_rules=[],
                     candidates=[], overall="no_hit")
        r = data_detective_report(empty)
        assert r["ok"] is True
        assert r["overall"] == "no_hit"
        assert r["n_findings"] == 0 and r["n_candidates"] == 0


class TestNumberWhitelist:
    def test_template_conclusion_whitelisted(self) -> None:
        r = data_detective_report(_FAKE_EXPLAIN)
        assert r["ok"] is True
        # 模板结论里的数字（计数）全部来自白名单 canonical 审计
        assert len(r["audit"]["violations"]) == 0
        assert r["audit"]["n_authorized"] >= 1

    def test_injected_llm_unauthorized_fallback(self) -> None:
        def bad_llm(_p: str) -> str:
            return "结论：峰值为 123.456 未授权单位 db。"

        r = data_detective_report(_FAKE_EXPLAIN, llm_fn=bad_llm,
                                  on_unauthorized="fallback")
        assert r["ok"] is True
        concl = r["sections"]["conclusion"]
        assert concl["used_template"] is True
        assert concl["fallback_reason"] == "unauthorized_numbers"
        assert len(concl["violations"]) == 1

    def test_injected_llm_unauthorized_reject(self) -> None:
        def bad_llm(_p: str) -> str:
            return "总计 999 处异常。"

        r = data_detective_report(_FAKE_EXPLAIN, llm_fn=bad_llm,
                                  on_unauthorized="reject")
        assert r["ok"] is False
        assert any("unauthorized number" in e for e in r["errors"])

    def test_injected_llm_clean_output_kept(self) -> None:
        def good_llm(_p: str) -> str:
            # 只引用白名单内的数字（n_findings=2 的 canonical 形态）
            return "发现合计 2 项，候选族 1 项；结论以确定性指纹为准。"

        r = data_detective_report(_FAKE_EXPLAIN, llm_fn=good_llm,
                                  on_unauthorized="reject")
        assert r["ok"] is True
        assert r["sections"]["conclusion"]["used_template"] is False

    def test_llm_channel_not_touched_by_default(self) -> None:
        # #139：缺省（llm_fn=None）走模板，无任何 LLM 通道可触
        r = data_detective_report(_FAKE_EXPLAIN)
        assert r["ok"] is True
        assert r["sections"]["conclusion"]["used_template"] is True


class TestNegativesAndDeterminism:
    def test_explain_not_ok_wraps_error(self) -> None:
        bad = {"ok": False, "reason": "playbook 不存在: x"}
        r = data_detective_report(bad)
        assert r["ok"] is False
        assert any("explain failed" in e for e in r["errors"])

    def test_missing_inputs_error(self) -> None:
        r = data_detective_report(None)
        assert r["ok"] is False

    def test_bad_on_unauthorized(self) -> None:
        with pytest.raises(ValueError):
            data_detective_report(_FAKE_EXPLAIN, on_unauthorized="yolo")

    def test_non_mapping_input(self) -> None:
        r = data_detective_report(["not", "a", "mapping"])  # type: ignore[arg-type]
        assert r["ok"] is False

    def test_deterministic_bytes(self) -> None:
        a = json.dumps(data_detective_report(_FAKE_EXPLAIN),
                       ensure_ascii=False, sort_keys=True)
        b = json.dumps(data_detective_report(_FAKE_EXPLAIN),
                       ensure_ascii=False, sort_keys=True)
        assert a == b


class TestMarkdown:
    def test_render_sections(self) -> None:
        md = render_detective_markdown(data_detective_report(_FAKE_EXPLAIN))
        for head in ("一、发现", "二、根因假设", "三、证据链", "四、结论"):
            assert head in md
        assert "#262" in md

    def test_render_failure_honest(self) -> None:
        md = render_detective_markdown({"ok": False, "errors": ["boom"]})
        assert "失败" in md and "boom" in md
