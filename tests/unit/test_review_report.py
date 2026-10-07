"""EP-1 审查报告生成器锚树（round18 规格研究扩充 round18
§二 EP-1；纯函数零真机零网络，铁律 7——报告只聚合输入行携带的数字，本测试
钉住「生成器不产生物理数字」与全部判级/分区/waiver 语义）。

锚面（任务书口径）：
- 报告字段逐项：合成 verdict 集（design_lint 形 checks + anchor 形单 verdict
  + criteria 引用）→ 门表/verdict 链/summary 逐键断言；
- 缺产物如实 UNKNOWN 不编：unknown 词/不可识别词→UNKNOWN、阈值实测缺→None；
- 门红+数据坏分区：FAIL 只进门红，坏 JSON/畸形条目只进数据坏，互不串；
- Markdown 渲染含全部 section（空门表恒在）；
- EP-1 验收语义：waiver 过期自动翻 FAIL（有效豁免→不拦且判级 PARTIAL；
  过期/畸形→FAIL 拦下；advisory 降级不拦；info 记录不判）；
- 负例：空输入 ValueError；checklist 程序性错误 ValueError；
- 确定性：同输入（注入 now）两次逐位一致 + JSON sort_keys 往返一致；
- write_review_report 双出文件可读回。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rfauto.core.review_report import (
    GRADES,
    REVIEW_REPORT_SCHEMA,
    SEVERITIES,
    generate_review_report,
    normalize_grade,
    render_markdown,
    write_review_report,
)

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
ALL_SECTIONS = ("## 摘要", "## 门表", "## verdict 链", "## 检查清单",
                "## 异常", "### 门红", "### 数据坏", "## 证据路径")

LINT_ISSUES = {
    "ok": True, "verdict": "issues",
    "checks": [
        {"name": "constraints", "status": "fail", "detail": "UNSAT",
         "source": "rfauto.service.render_constraint_service"},
        {"name": "fab", "status": "warn", "detail": "保守扫描",
         "source": "rfauto.service.fab_service"},
        {"name": "bounds", "status": "info", "detail": "ka=1.2 信息界",
         "source": "rfauto.core.bounds"},
        {"name": "pdn", "status": "pass", "detail": "门 PASS",
         "source": "rfauto.service.pdn_service"},
        {"name": "stub", "status": "unknown", "detail": "参数不足",
         "source": "rfauto.core.fab_check"},
    ],
}
ANCHOR_PASS = {"name": "mline_dual_anchor", "verdict": "PASS",
               "criteria_ref": "runs/x/criteria_a.md"}


# ─── 判级归一词表钉 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,grade,info", [
    ("pass", "PASS", False), ("healthy", "PASS", False), ("clean", "PASS", False),
    ("sat", "PASS", False), ("info", "PASS", True),
    ("fail", "FAIL", False), ("issues", "FAIL", False),
    ("unhealthy", "FAIL", False), ("unsat", "FAIL", False),
    ("partial", "PARTIAL", False), ("warn", "PARTIAL", False),
    ("suspect", "PARTIAL", False), ("attention", "PARTIAL", False),
    ("unknown", "UNKNOWN", False), ("undecided", "UNKNOWN", False),
    ("undecidable", "UNKNOWN", False), ("error", "UNKNOWN", False),
    ("skipped", "UNKNOWN", False),
    # 前缀族（带尾注串，项目既存形态：criteria.md 里 FAIL(insufficient_data)）
    ("FAIL(insufficient_data)", "FAIL", False),
    ("AGREE_OPENEMS", "PASS", False), ("CERTIFIED_HFSS_V1", "PASS", False),
    ("UNDECIDABLE_no_pairing", "UNKNOWN", False),
    (True, "PASS", False), (False, "FAIL", False),
    ("mystery_token", "UNKNOWN", False), (3, "UNKNOWN", False),
])
def test_normalize_grade_vocabulary(raw, grade, info):
    assert normalize_grade(raw) == (grade, info)


def test_grade_set_constants():
    assert GRADES == ("PASS", "FAIL", "PARTIAL", "UNKNOWN")
    assert SEVERITIES == ("block", "advisory", "info")


# ─── 报告字段逐项 ────────────────────────────────────────────────────────────


def test_report_fields_itemized():
    report = generate_review_report(verdicts=[LINT_ISSUES, ANCHOR_PASS], now=NOW)
    assert report["schema"] == REVIEW_REPORT_SCHEMA
    assert report["generated_utc"] == NOW.isoformat()
    # 门表逐行：design_lint checks 平铺 + 单 verdict 自成门
    gates = {g["name"]: g for g in report["gates_table"]}
    assert set(gates) == {"constraints", "fab", "bounds", "pdn", "stub",
                          "mline_dual_anchor"}
    assert gates["constraints"]["grade"] == "FAIL"
    assert gates["constraints"]["severity"] == "block"  # 无 checklist 缺省=fail-safe
    assert gates["constraints"]["origin"] == "rfauto.service.render_constraint_service"
    assert gates["fab"]["grade"] == "PARTIAL"
    assert gates["bounds"]["grade"] == "PASS" and gates["bounds"]["informational"]
    assert gates["stub"]["grade"] == "UNKNOWN"
    assert gates["mline_dual_anchor"]["criteria_ref"] == "runs/x/criteria_a.md"
    # 阈值/实测缺 → 如实 None 不编
    assert gates["constraints"]["threshold"] is None
    assert gates["constraints"]["measured"] is None
    # verdict 链：本体行 + criteria 引用透传
    chain = {c["name"]: c for c in report["verdicts"]}
    assert chain["mline_dual_anchor"]["grade"] == "PASS"
    assert chain["mline_dual_anchor"]["criteria_ref"] == "runs/x/criteria_a.md"
    lint_row = next(c for c in report["verdicts"] if c["n_gates"] == 5)
    assert lint_row["verdict_raw"] == "issues" and lint_row["grade"] == "FAIL"
    # summary 逐键
    s = report["summary"]
    assert s["verdict"] == "FAIL"  # block 级门红拦
    assert (s["n_gates"], s["pass"], s["fail"], s["partial"], s["unknown"],
            s["n_info"]) == (6, 2, 1, 1, 1, 1)
    assert s["n_anomalies_gate"] == 1 and s["n_anomalies_data"] == 0
    assert s["n_checklist"] == 0
    # 证据路径：内存输入无文件 → 空（如实，不编路径）
    assert report["evidence_paths"] == []
    assert report["anomalies"]["data_quality"] == []


def test_threshold_measured_passthrough_from_gates_block():
    payload = {"gates": {
        "G1": {"verdict": "FAIL", "threshold": -10.0, "measured": -6.2},
        "G2": {"status": "pass", "result": {"limit_value": 1.02,
                                            "measured_value": 1.001}},
        "G3": "PASS",
    }}
    report = generate_review_report(verdicts=payload, now=NOW)
    rows = {g["name"]: g for g in report["gates_table"]}
    assert rows["G1"]["grade"] == "FAIL"
    assert rows["G1"]["threshold"] == -10.0 and rows["G1"]["measured"] == -6.2
    assert rows["G2"]["grade"] == "PASS"
    assert rows["G2"]["threshold"] == 1.02 and rows["G2"]["measured"] == 1.001
    assert rows["G3"]["grade"] == "PASS" and rows["G3"]["verdict_raw"] == "PASS"
    assert report["summary"]["verdict"] == "FAIL"


def test_mapping_and_list_verdict_forms():
    mapping = {"a": {"verdict": "PASS"}, "b": {"verdict": "FAIL"}}
    listing = [{"verdict": "PARTIAL"}]
    report = generate_review_report(verdicts=[mapping, listing], now=NOW)
    names = [g["name"] for g in report["gates_table"]]
    # 内层批：外层位置 i + 内层序 j（verdict_1[0]），确定性命名可溯源
    assert names == ["a", "b", "verdict_1[0]"]
    assert report["summary"]["verdict"] == "FAIL"


# ─── 缺产物如实 UNKNOWN 不编 ────────────────────────────────────────────────


def test_unknown_honesty_no_fabrication():
    payload = {"gates": {
        "g_unknown": {"verdict": "UNKNOWN"},
        "g_weird": {"status": "完全不可识别的词"},
        "g_missing": {"detail": "连判级键都没有的行"},
    }}
    report = generate_review_report(verdicts=payload, now=NOW)
    rows = {g["name"]: g for g in report["gates_table"]}
    assert rows["g_unknown"]["grade"] == "UNKNOWN"
    assert rows["g_weird"]["grade"] == "UNKNOWN"
    assert rows["g_weird"]["verdict_raw"] == "完全不可识别的词"  # raw 保留不编
    # 缺判级键的子行不进门表（数据坏留痕），也不冒充任何判级
    assert "g_missing" not in rows
    kinds = [a["kind"] for a in report["anomalies"]["data_quality"]]
    assert kinds == ["malformed_check_row"]
    assert report["summary"]["verdict"] == "UNKNOWN"  # 未判≠干净
    assert report["summary"]["unknown"] == 2


def test_zero_gates_report_is_unknown_not_pass():
    report = generate_review_report(verdicts=[{}], now=NOW)
    assert report["gates_table"] == []
    assert report["summary"]["verdict"] == "UNKNOWN"
    assert report["summary"]["n_anomalies_data"] == 1


def test_info_only_report_is_pass():
    payload = {"checks": [
        {"name": "bounds", "status": "info", "source": "svc"},
        {"name": "ok_check", "status": "pass", "source": "svc"},
    ]}
    report = generate_review_report(verdicts=payload, now=NOW)
    assert report["summary"]["verdict"] == "PASS"  # info 不设门（design_lint 同语义）
    assert report["summary"]["n_info"] == 1


# ─── 门红 + 数据坏分区 ───────────────────────────────────────────────────────


def test_partition_gate_red_vs_data_bad(tmp_path: Path):
    good = tmp_path / "stage1"
    good.mkdir()
    (good / "stage1_verdict.json").write_text(
        json.dumps({"verdict": "FAIL", "criteria": "runs/c/criteria_a.md",
                    "detail": "三模判读门红"}, ensure_ascii=False),
        encoding="utf-8")
    (tmp_path / "stage2_verdict.json").write_text("{corrupt!!", encoding="utf-8")
    (tmp_path / "weird_health.json").write_text("123", encoding="utf-8")
    report = generate_report_from_dir(tmp_path)
    # 门红分区：只收 FAIL 门
    reds = report["anomalies"]["gate_failures"]
    assert len(reds) == 1
    assert reds[0]["name"] == "stage1_verdict"
    assert reds[0]["grade"] == "FAIL"
    assert reds[0]["criteria_ref"] == "runs/c/criteria_a.md"
    # 数据坏分区：坏 JSON + 形状坏，互不串
    bad = report["anomalies"]["data_quality"]
    assert [a["kind"] for a in bad] == ["corrupt_json", "bad_shape"]
    assert all("stage1_verdict" not in (a.get("path") or "") for a in bad)
    # 证据路径逐条在案（含坏文件——异常证据也是证据）
    assert len(report["evidence_paths"]) == 3
    assert any(p.endswith("stage2_verdict.json") for p in report["evidence_paths"])
    assert report["summary"]["verdict"] == "FAIL"
    assert report["summary"]["n_anomalies_gate"] == 1
    assert report["summary"]["n_anomalies_data"] == 2


def generate_report_from_dir(run_dir: Path):
    return generate_review_report(run_dir=run_dir, now=NOW)


def test_run_dir_scan_deterministic_and_nested(tmp_path: Path):
    d1 = tmp_path / "b_dir"
    d2 = tmp_path / "a_dir"
    d1.mkdir()
    d2.mkdir()
    (d1 / "verdict.json").write_text('{"verdict": "PASS"}', encoding="utf-8")
    (d2 / "verdict.json").write_text('{"verdict": "PASS"}', encoding="utf-8")
    r1 = generate_review_report(run_dir=tmp_path, now=NOW)
    r2 = generate_review_report(run_dir=tmp_path, now=NOW)
    assert r1 == r2  # 扫描序确定（路径排序），同输入逐位一致
    assert r1["inputs"]["n_files_read"] == 2
    # 同名 stem 文件的 source_path 各自在案
    paths = sorted(g["source_path"] for g in r1["gates_table"])
    assert len(paths) == 2 and paths[0] != paths[1]


# ─── EP-1 验收语义：waiver 过期自动翻 FAIL ──────────────────────────────────


def _waiver_item(expiry: str, severity: str = "block") -> dict:
    return {"id": "CK-001", "severity": severity, "auto_check": "constraints",
            "waiver": {"approved_by": "用户", "reason": "已知 UNSAT 待重构",
                       "expiry": expiry}}


def _single_fail_report(checklist):
    return generate_review_report(verdicts=[{"name": "constraints",
                                             "verdict": "FAIL"}],
                                  checklist=checklist, now=NOW)


def test_waiver_valid_does_not_block_but_not_clean():
    report = _single_fail_report([_waiver_item("2999-12-31")])
    assert report["summary"]["verdict"] == "PARTIAL"  # 豁免不拦，也不冒充干净
    assert report["summary"]["n_waived"] == 1
    assert report["summary"]["n_waiver_expired"] == 0
    gate = report["gates_table"][0]
    assert gate["waived"] is True and gate["grade"] == "FAIL"  # 门红留痕不洗白
    assert report["checklist"][0]["item_effective"] == "WAIVED"
    assert report["checklist"][0]["waiver_state"] == "valid"
    # 门红分区仍记录（带有效豁免标注）
    assert report["anomalies"]["gate_failures"][0]["waived"] is True


def test_waiver_expired_auto_fails_spec_acceptance():
    report = _single_fail_report([_waiver_item("2026-10-01")])  # NOW 前一天
    assert report["summary"]["verdict"] == "FAIL"  # 验收：过期自动翻 FAIL
    assert report["summary"]["n_waiver_expired"] == 1
    gate = report["gates_table"][0]
    assert gate["waiver_expired"] is True and gate["waived"] is False
    assert report["checklist"][0]["item_effective"] == "FAIL"
    assert report["checklist"][0]["waiver_state"] == "expired"
    md = render_markdown(report)
    assert "(waiver_expired)" in md and "waiver 过期翻 FAIL" in md


def test_waiver_date_only_expiry_is_inclusive_end_of_day():
    # 当日（NOW 日期同天）→ 含尾有效；昨日 → 过期
    assert _single_fail_report(
        [_waiver_item("2026-10-02")])["summary"]["verdict"] == "PARTIAL"
    assert _single_fail_report(
        [_waiver_item("2026-10-01")])["summary"]["verdict"] == "FAIL"


@pytest.mark.parametrize("waiver", [
    {"approved_by": "用户"},  # 缺 reason/expiry
    {"approved_by": "用户", "reason": "r", "expiry": "not-a-date"},
    "口头豁免",  # 非对象
])
def test_malformed_waiver_treated_as_absent(waiver):
    item = {"id": "CK-001", "severity": "block", "auto_check": "constraints",
            "waiver": waiver}
    report = _single_fail_report([item])
    assert report["summary"]["verdict"] == "FAIL"  # 畸形豁免=无豁免（多报不放过）
    assert report["checklist"][0]["waiver_state"] == "malformed"


def test_advisory_fail_degrades_to_partial_not_fail():
    item = {"id": "CK-002", "severity": "advisory", "auto_check": "constraints"}
    report = _single_fail_report([item])
    assert report["summary"]["verdict"] == "PARTIAL"
    assert report["summary"]["n_waived"] == 0  # advisory 是降级不是豁免


def test_info_severity_fail_recorded_not_judged():
    item = {"id": "CK-003", "severity": "info", "auto_check": "constraints"}
    report = _single_fail_report([item])
    assert report["summary"]["verdict"] == "PASS"  # 记录不判（规格 info 级语义）
    assert report["summary"]["fail"] == 1  # 门红计数如实保留
    assert report["anomalies"]["gate_failures"][0]["name"] == "constraints"


def test_unmanaged_gate_fail_defaults_to_block():
    # 门不在 checklist 内 → 缺省 block（未管理门红必拦，fail-safe）
    report = _single_fail_report([{"id": "CK-009", "severity": "info",
                                   "auto_check": "别的门"}])
    assert report["summary"]["verdict"] == "FAIL"
    assert report["summary"]["n_checklist_unmatched"] == 1


def test_datetime_and_naive_expiry_forms():
    item_aware = _waiver_item("2999-12-31T23:59:59+00:00")
    assert _single_fail_report([item_aware])["summary"]["verdict"] == "PARTIAL"
    item_naive = _waiver_item("2999-12-31T23:59:59")  # naive 按 UTC（口径显式）
    assert _single_fail_report([item_naive])["summary"]["verdict"] == "PARTIAL"


# ─── Markdown 渲染 ──────────────────────────────────────────────────────────


def test_markdown_contains_all_sections():
    report = generate_review_report(verdicts=[LINT_ISSUES, ANCHOR_PASS],
                                    checklist=[_waiver_item("2999-12-31")],
                                    now=NOW)
    md = render_markdown(report)
    for section in ALL_SECTIONS:
        assert section in md, f"缺 section: {section}"
    assert "constraints" in md and "mline_dual_anchor" in md
    assert REVIEW_REPORT_SCHEMA in md
    assert "| 门名 | 判级 | 阈值 | 实测 | 来源 | 判据引用 |" in md


def test_markdown_empty_gates_still_all_sections():
    md = render_markdown(generate_review_report(verdicts=[{}], now=NOW))
    for section in ALL_SECTIONS:
        assert section in md, f"缺 section: {section}"
    assert "（无门行）" in md and "（未提供检查清单）" in md


@pytest.mark.parametrize("bad", [{}, {"schema": "other-v1"}, "report", None])
def test_render_rejects_non_report(bad):
    with pytest.raises(ValueError):
        render_markdown(bad)


# ─── 负例（程序性错误如实 ValueError） ───────────────────────────────────────


@pytest.mark.parametrize("kwargs", [
    {}, {"verdicts": []}, {"verdicts": ()},
    {"verdicts": 3}, {"verdicts": [3.5]},
    {"run_dir": "Z:/definitely_not_a_dir_ep1"},
    {"verdicts": [{"verdict": "PASS"}], "now": "2026-10-02"},
])
def test_negative_value_errors(kwargs, tmp_path: Path):
    if kwargs.get("run_dir") == "Z:/definitely_not_a_dir_ep1":
        kwargs = dict(kwargs, run_dir=tmp_path / "nope")
    with pytest.raises(ValueError):
        generate_review_report(**kwargs)


def test_run_dir_empty_yields_value_error(tmp_path: Path):
    with pytest.raises(ValueError, match="空输入"):
        generate_review_report(run_dir=tmp_path, now=NOW)


@pytest.mark.parametrize("checklist", [
    "not-a-list", [{"severity": "block"}],  # 非 list / 缺 id
    [{"id": "CK", "severity": "mega"}],  # severity 非法
    [{"id": "CK", "auto_check": 3}], [42],
])
def test_checklist_programmatic_errors(checklist):
    with pytest.raises(ValueError):
        generate_review_report(verdicts=[{"verdict": "PASS"}],
                               checklist=checklist, now=NOW)


# ─── 确定性与写出 ────────────────────────────────────────────────────────────


def test_determinism_same_input_bitwise():
    kwargs = dict(verdicts=[LINT_ISSUES, ANCHOR_PASS],
                  checklist=[_waiver_item("2999-12-31")], now=NOW)
    r1 = generate_review_report(**kwargs)
    r2 = generate_review_report(**kwargs)
    assert r1 == r2
    assert json.dumps(r1, sort_keys=True, ensure_ascii=False) \
        == json.dumps(r2, sort_keys=True, ensure_ascii=False)


def test_write_review_report_dual_output(tmp_path: Path):
    report = generate_review_report(verdicts=[LINT_ISSUES], now=NOW)
    paths = write_review_report(report, tmp_path / "out", stem="ep1_review")
    assert set(paths) == {"json", "markdown"}
    loaded = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert loaded == report
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    for section in ALL_SECTIONS:
        assert section in md
    with pytest.raises(ValueError):
        write_review_report({"schema": "nope"}, tmp_path)
