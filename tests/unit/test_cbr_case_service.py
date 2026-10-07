"""KD-9 CBR 案例库测试（round16 P3，J 流）。

锚树：
- 五元组形态：每案例 problem/context/solution/outcome/provenance 五键
  齐备，坑号可溯（case_id=FK-<mode_id>，lesson_refs '#' 开头）；
- **复用不重写**：检索语义与 KD-4 逐位同——同 (task_kind, keywords)
  下 CBR cases 与 failure_knowledge_for hits 一一对应（同序同分同
  mode_id 集）；调用前后 FAILURE_MODE_LIBRARY 逐位不变（库只读）；
- 检索确定性：同输入两次 JSON 逐位一致；query_text 分词提关键词；
  显式 keywords 与 query_text 并集；
- 未命中如实空表；未知 task_kind ValueError（KD-4 负例契约沿用）；
- 摘要面：库计数=premortem FAILURE_MODE_LIBRARY 逐类计数（同源核对）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

from rfauto.core.failure_knowledge import failure_knowledge_for
from rfauto.core.premortem import FAILURE_MODE_LIBRARY, _normalize_task_kind
from rfauto.service.cbr_case_service import (
    CBR_CASE_SCHEMA,
    DEFAULT_TOP_K_CASES,
    case_base_summary,
    find_similar_cases,
    render_case_report,
)


class TestCaseShape:
    def test_five_tuple_complete_and_traceable(self):
        r = find_similar_cases("real_solve", "求解进程 整树 消失 网格 dt")
        assert r["ok"] and r["n_cases"] >= 1
        for c in r["cases"]:
            for key in ("problem", "context", "solution", "outcome",
                        "provenance"):
                assert key in c, key
            assert c["case_id"].startswith("FK-")
            assert c["context"] == "real_solve"
            refs = c["provenance"]["lesson_refs"]
            assert all(str(x).startswith("#") for x in refs), refs
            assert c["provenance"]["mode_id"] == c["case_id"][3:]

    def test_default_top_k_cap(self):
        r = find_similar_cases("real_solve", None, keywords=None,
                               min_score=0, top_k=2)
        assert r["n_cases"] <= 2
        assert DEFAULT_TOP_K_CASES == 5

    def test_schema_pinned(self):
        r = find_similar_cases("real_solve", None, min_score=0)
        assert r["schema"] == CBR_CASE_SCHEMA


class TestReuseNotRewrite:
    """检索核与 KD-4 同源：同输入下 cases 与 hits 一一对应。"""

    def test_cases_mirror_failure_knowledge_hits(self):
        kws = ["网格", "dt"]
        fk = failure_knowledge_for("real_solve", kws, top_k=10, min_score=1)
        r = find_similar_cases("real_solve", None, keywords=kws,
                               top_k=10, min_score=1)
        assert [c["case_id"][3:] for c in r["cases"]] == \
            [h["mode_id"] for h in fk["hits"]]
        assert [c["score"] for c in r["cases"]] == [h["score"] for h in fk["hits"]]
        assert r["n_cases_total"] == fk["n_modes_total"]

    def test_library_untouched_after_calls(self):
        before = {k: [repr(f) for f in v]
                  for k, v in FAILURE_MODE_LIBRARY.items()}
        find_similar_cases("calibration", "S 参数 互易 掩码")
        find_similar_cases("param_sweep", "TPE warm start")
        after = {k: [repr(f) for f in v]
                 for k, v in FAILURE_MODE_LIBRARY.items()}
        assert before == after

    def test_kind_filter_no_cross_library_leak(self):
        r = find_similar_cases("calibration", "互易 掩码 S 参数")
        kind = _normalize_task_kind("calibration")
        for c in r["cases"]:
            assert c["context"] == kind
            assert any(c["case_id"][3:] == fm.mode_id
                       for fm in FAILURE_MODE_LIBRARY[kind])


class TestRetrievalSemantics:
    def test_deterministic(self):
        a = json.dumps(find_similar_cases("real_solve", "dt 网格 时间步"),
                       sort_keys=True, ensure_ascii=False)
        b = json.dumps(find_similar_cases("real_solve", "dt 网格 时间步"),
                       sort_keys=True, ensure_ascii=False)
        assert a == b

    def test_query_text_tokenization_feeds_retrieval(self):
        r = find_similar_cases("real_solve", "openEMS 网格 dt 时间步")
        assert r["query_keywords"]  # 分词非空
        assert any("dt" in k or "网格" in k for k in r["query_keywords"])

    def test_no_hit_is_honest_empty(self):
        r = find_similar_cases("real_solve", "zzzzqqqq", min_score=1)
        assert r["ok"] and r["n_cases"] == 0 and r["cases"] == []

    def test_unknown_task_kind_valueerror(self):
        with pytest.raises(ValueError):
            find_similar_cases("not-a-kind", "anything")

    def test_explicit_keywords_union_with_query_text(self):
        r = find_similar_cases("real_solve", "网格", keywords=["dt"])
        assert "dt" in r["query_keywords"] and "网格" in r["query_keywords"]


class TestSummaryAndRender:
    def test_summary_matches_library_counts(self):
        s = case_base_summary()
        assert s["ok"] and s["schema"] == CBR_CASE_SCHEMA
        assert s["n_cases"] == sum(len(v) for v in FAILURE_MODE_LIBRARY.values())
        for kind, n in s["per_task_kind"].items():
            assert n == len(FAILURE_MODE_LIBRARY[kind])

    def test_render_lists_cases_with_refs(self):
        r = find_similar_cases("real_solve", "整树 进程 消失 存活 探针",
                               min_score=0, top_k=3)
        md = render_case_report(r)
        assert r["cases"], "测试前提：real_solve 库非空"
        assert "相似案例" in md
        for c in r["cases"]:
            assert c["case_id"] in md

    def test_render_empty_and_not_ok(self):
        assert render_case_report({"ok": True, "cases": []}) == ""
        assert render_case_report({"ok": False}) == ""
