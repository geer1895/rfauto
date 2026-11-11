"""em_bench 判据增强包定向测试（aurora_r R-01 席，AX-1+B3 六件）。

覆盖（任务书验收口径，六件各含正例+负例+unknown/absent 例）：
- ① grader_notes/rubric 字段：schema 缺省缺席/vendor-search 缺省任务携带/
  TaskResult+score_bench 报告面透出（纯数据零 LLM 打分）；
- ② spec_score 部分分列：口径单测（pass 占比/unknown 不进分子分母/全
  unknown=None）/run 结果列/verdict 语义零变钉/scorecard 均值口径；
- ③ hidden/visible 双层判据：两层都算（隐藏层 fail 翻任务 verdict）/
  报告只出 visible 明细+hidden 汇总/隐藏层阈值预声明同规/跨层同名拒收/
  无隐藏层 hidden_summary=None；
- ④ negative_variants 反例集：vendor-search 缺省任务真反例判 fail/反例
  判不出 fail → unknown（判据退化如实）/执行崩溃的 fail 不算判据判 fail
  （不凑绿）/无反例 absent；
- ⑤ no-op 必败门+任务准入门：真任务 admitted 三探针全过/数值判据任务
  no-op=unknown → quarantined（如实）/空过判据（阈值 0）→ quarantined/
  oracle 不稳定 quarantined/oracle 判不过 quarantined/结构拒绝 rejected/
  批量分区/NOOP_PROBE_MEASURES 覆盖判据枚举闭集；
- ⑥ B3 OOD 探针+训练包络守卫：absent 如实/declared 域内 ood_flag=False/
  越界 ood_flag=True 且 verdict 本体零变/包络键缺席 unverified 如实不判/
  评估点提取确定性/schema 失败 envelope=unknown 如实。

零网络零真机（#139）：vendor-search/证照链全离线；探针族 runner 经
monkeypatch.setitem 注入（注册表闭集不落真注册）；湖写只落 tmp。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service import em_bench_service as em

# ---------------------------------------------------------------------------
# 探针族 runner（确定性受控测度回放——测度全由 input_spec 声明，零内核依赖）
# ---------------------------------------------------------------------------

_PROBE_FAMILY = "r01_probe"


@pytest.fixture
def probe_family(monkeypatch):
    """注入 r01_probe 探针族 runner：input_spec.measures 原样回放为测度
    （boom 键在场=执行崩溃负例通道）。monkeypatch 自动还原注册表。"""

    def _run(task, ctx):
        spec = task.input_spec or {}
        if spec.get("boom"):
            raise RuntimeError("探针执行崩溃（负例通道）")
        return {"measures": dict(spec.get("measures") or {}),
                "detail": {"probe": True}}

    monkeypatch.setitem(em._RUNNER_REGISTRY, _PROBE_FAMILY, _run)
    return _run


def _probe_task(task_id: str = "r01-probe", **overrides) -> dict:
    base = {
        "task_id": task_id, "family": _PROBE_FAMILY,
        "input_spec": {"measures": {}},
        "criteria": [{"name": "gate_pass"}],
    }
    base.update(overrides)
    return base


def _tasks_by_id() -> dict[str, em.BenchTask]:
    return {t.task_id: t for t in em.default_bench_tasks()}


# ---------------------------------------------------------------------------
# schema：可选字段缺省缺席 + 跨层互斥 + 包络域检
# ---------------------------------------------------------------------------


def test_r01_default_tasks_optional_fields_state():
    """缺省任务可选字段三态抽钉：syn-cpw 全缺席（None/[]/None）；vendor-
    search 携带 grader_notes+真反例；syn-mline 携带 envelope（B3 声明面）。
    hidden_criteria 全缺省任务不携带（隐藏层 opt-in——缺省 verdict 行为零变）。"""
    by_id = _tasks_by_id()
    cpw = by_id["syn-cpw"]
    assert cpw.grader_notes is None
    assert cpw.negative_variants == []
    assert cpw.hidden_criteria == []
    assert cpw.envelope is None
    vendor = by_id["vendor-search"]
    assert vendor.grader_notes is not None
    assert vendor.grader_notes.correct_core and vendor.grader_notes.common_errors
    assert vendor.grader_notes.partial_credit.strip()
    assert len(vendor.negative_variants) == 1
    assert vendor.negative_variants[0].variant_id == "noop-queries-absent-terms"
    mline = by_id["syn-mline"]
    assert mline.envelope is not None
    assert set(mline.envelope) == {"z0_ohm", "freq_ghz"}
    for t in by_id.values():
        assert t.hidden_criteria == []


def test_r01_hidden_visible_name_overlap_rejected():
    """visible/hidden 判据名跨层重复 → schema 拒收（分层语义破坏不猜）。"""
    with pytest.raises(ValidationError, match="跨层重复"):
        em.BenchTask(
            task_id="dup", family=_PROBE_FAMILY,
            criteria=[{"name": "gate_pass"}],
            hidden_criteria=[{"name": "gate_pass"}],
        )


def test_r01_envelope_bounds_validation():
    """包络域检：min>max 反向界/双界全缺/inf 非有限/空白键——全部 schema 拒收。"""
    with pytest.raises(ValidationError, match="反向界"):
        em.BenchTask(task_id="e1", family=_PROBE_FAMILY,
                     criteria=[{"name": "gate_pass"}],
                     envelope={"p": {"min": 10.0, "max": 1.0}})
    with pytest.raises(ValidationError, match="至少声明一界"):
        em.BenchTask(task_id="e2", family=_PROBE_FAMILY,
                     criteria=[{"name": "gate_pass"}],
                     envelope={"p": {"min": None, "max": None}})
    with pytest.raises(ValidationError, match="有限"):
        em.BenchTask(task_id="e3", family=_PROBE_FAMILY,
                     criteria=[{"name": "gate_pass"}],
                     envelope={"p": {"min": float("inf")}})
    with pytest.raises(ValidationError, match="空白"):
        em.BenchTask(task_id="e4", family=_PROBE_FAMILY,
                     criteria=[{"name": "gate_pass"}],
                     envelope={"  ": {"min": 0.0}})


def test_r01_envelope_bound_rejects_bool():
    """包络界 bool 拒收（#364 判据布尔化纪律——True 不是有限界）。"""
    with pytest.raises(ValidationError):
        em.BenchTask(task_id="e5", family=_PROBE_FAMILY,
                     criteria=[{"name": "gate_pass"}],
                     envelope={"p": {"min": True}})


# ---------------------------------------------------------------------------
# ① grader_notes/rubric 字段（纯数据+报告面透出，零 LLM 打分）
# ---------------------------------------------------------------------------


def test_r01_grader_notes_passthrough_in_result(tmp_path):
    """缺省任务 vendor-search 真跑：TaskResult.grader_notes 三段结构原样
    透出（rubric 是声明数据不是判定输入——verdict 仍由判据注册表产出）。"""
    r = em.run_bench_task(_tasks_by_id()["vendor-search"], work_root=tmp_path)
    assert r["ok"] is True and r["verdict"] == "pass"
    notes = r["grader_notes"]
    assert isinstance(notes, dict)
    assert notes["correct_core"] and notes["common_errors"]
    assert "命中" in notes["partial_credit"]


def test_r01_grader_notes_none_when_absent(tmp_path):
    """未声明 grader_notes 的任务 → 报告面 None（缺席如实，不伪造空表）。"""
    r = em.run_bench_task(_tasks_by_id()["syn-cpw"], work_root=tmp_path)
    assert r["grader_notes"] is None


def test_r01_grader_notes_in_scorecard_rows():
    """score_bench 逐任务行透传 grader_notes（无键结果行=None 兼容旧形态）。"""
    with_notes = {"task_id": "a", "family": "synthesis", "verdict": "pass",
                  "ok": True, "scores": {}, "errors": [],
                  "grader_notes": {"correct_core": ["x"], "common_errors": [],
                                   "partial_credit": ""}}
    card = em.score_bench([with_notes, {"task_id": "b", "family": "synthesis",
                                        "verdict": "fail", "ok": True,
                                        "scores": {}, "errors": []}])
    rows = {t["task_id"]: t for t in card["tasks"]}
    assert rows["a"]["grader_notes"] == {"correct_core": ["x"],
                                         "common_errors": [],
                                         "partial_credit": ""}
    assert rows["b"]["grader_notes"] is None


def test_r01_grader_notes_is_pure_data_no_judgment(tmp_path, probe_family):
    """rubric 附注不参与判定：声明正确核的同时喂 fail 测度——verdict 仍
    fail（grader_notes 零打分语义钉）。"""
    task = em.BenchTask.model_validate(_probe_task(
        input_spec={"measures": {"gate_pass": {"passed": False, "gate": "g"}}},
        grader_notes={"correct_core": ["门必须过"], "common_errors": ["门 fail"],
                      "partial_credit": "无"}))
    r = em.run_bench_task(task, work_root=tmp_path)
    assert r["verdict"] == "fail"
    assert r["grader_notes"]["correct_core"] == ["门必须过"]


# ---------------------------------------------------------------------------
# ② spec_score 部分分列（verdict 语义零变）
# ---------------------------------------------------------------------------


def test_r01_spec_score_semantics_unit():
    """口径单测：全 pass=1.0 / 混合=pass 占比（unknown 不进分子分母）/
    全 unknown=None / 空=None / 全 fail=0.0。"""
    s = lambda d: em.spec_score_from_scores(d)  # noqa: E731
    assert s({"a": {"verdict": "pass"}, "b": {"verdict": "pass"}}) == 1.0
    assert s({"a": {"verdict": "pass"}, "b": {"verdict": "fail"},
              "c": {"verdict": "unknown"}}) == pytest.approx(0.5)
    assert s({"a": {"verdict": "unknown"}, "b": {}}) is None
    assert s({}) is None
    assert s({"a": {"verdict": "fail"}}) == 0.0
    assert s({"a": "garbage"}) is None  # 非映射条目按 unknown（不进分母）


def test_r01_spec_score_column_and_verdict_unchanged(tmp_path, probe_family):
    """run 结果列：fail 设计 spec_score=通过检查占比，verdict 语义零变
    （fail 仍 fail、pass 仍 pass——#122 红线钉）。"""
    r_fail = em.run_bench_task(_probe_task(criteria=[
        {"name": "gate_pass"}, {"name": "certificate_pass"}],
        input_spec={"measures": {
            "gate_pass": {"passed": False, "gate": "g"},
            "certificate_pass": {"passed": True, "n_diff": 0}}}),
        work_root=tmp_path)
    assert r_fail["verdict"] == "fail"
    assert r_fail["spec_score"] == pytest.approx(0.5)
    r_pass = em.run_bench_task(_probe_task(input_spec={"measures": {
        "gate_pass": {"passed": True, "gate": "g"}}}), work_root=tmp_path)
    assert r_pass["verdict"] == "pass" and r_pass["spec_score"] == 1.0
    r_unknown = em.run_bench_task(_probe_task(
        input_spec={"measures": {"gate_pass": {"metric": None}}}),
        work_root=tmp_path)
    assert r_unknown["verdict"] == "unknown"
    assert r_unknown["spec_score"] is None  # 全 unknown：缺席不编数


def test_r01_spec_score_scorecard_mean():
    """scorecard 聚合：mean 只对已得分任务；无得分任务 → mean=None+n_scored=0。"""
    card = em.score_bench([
        {"task_id": "a", "family": "f", "verdict": "pass", "ok": True,
         "scores": {}, "errors": [], "spec_score": 1.0},
        {"task_id": "b", "family": "f", "verdict": "fail", "ok": True,
         "scores": {}, "errors": [], "spec_score": 0.5},
        {"task_id": "c", "family": "f", "verdict": "unknown", "ok": True,
         "scores": {}, "errors": [], "spec_score": None},
    ])
    block = card["spec_score"]
    assert block["mean"] == pytest.approx(0.75)
    assert block["n_scored"] == 2
    assert "verdict 语义零变" in block["basis"]
    empty = em.score_bench([])
    assert empty["spec_score"]["mean"] is None
    assert empty["spec_score"]["n_scored"] == 0


# ---------------------------------------------------------------------------
# ③ hidden/visible 双层判据
# ---------------------------------------------------------------------------


def test_r01_hidden_layer_judged_and_summarized(tmp_path, probe_family):
    """两层都算：隐藏层 fail 翻任务 verdict；报告面 scores 只含 visible
    明细，hidden 只出汇总（隐藏判据名不出现在 scores——防对着裁判调参）。"""
    task = em.BenchTask.model_validate(_probe_task(
        input_spec={"measures": {
            "gate_pass": {"passed": True, "gate": "g"},
            "certificate_pass": {"passed": False, "n_diff": 3}}},
        hidden_criteria=[{"name": "certificate_pass"}]))
    r = em.run_bench_task(task, work_root=tmp_path)
    assert r["verdict"] == "fail"  # visible 全过 + hidden fail → 任务 fail
    assert set(r["scores"]) == {"gate_pass"}  # 明细只出 visible
    assert r["scores"]["gate_pass"]["verdict"] == "pass"
    assert r["hidden_summary"] == {"n_total": 1, "n_pass": 0, "n_fail": 1,
                                   "n_unknown": 0}
    assert "certificate_pass" not in json.dumps(r["scores"])


def test_r01_hidden_layer_unknown_counts(tmp_path, probe_family):
    """隐藏层缺测 → n_unknown 计数如实；无 fail 时任务 verdict=unknown。"""
    task = em.BenchTask.model_validate(_probe_task(
        input_spec={"measures": {"gate_pass": {"passed": True, "gate": "g"}}},
        hidden_criteria=[{"name": "certificate_pass"}]))  # 测度缺失
    r = em.run_bench_task(task, work_root=tmp_path)
    assert r["verdict"] == "unknown"
    assert r["hidden_summary"] == {"n_total": 1, "n_pass": 0, "n_fail": 0,
                                   "n_unknown": 1}


def test_r01_hidden_threshold_predeclared_same_rule(tmp_path, probe_family):
    """隐藏层阈值预声明同规（#122）：hidden 层 closedform_match 缺阈值 →
    validate 态 fail（不跑 runner），报错点名 hidden 层同规。"""
    task = em.BenchTask.model_validate(_probe_task(
        hidden_criteria=[{"name": "closedform_match"}]))
    r = em.run_bench_task(task, work_root=tmp_path)
    assert r["ok"] is False and r["verdict"] == "fail" and r["stage"] == "validate"
    assert "hidden 层同规" in r["errors"][0]


def test_r01_hidden_summary_none_without_hidden(tmp_path):
    """无隐藏层 → hidden_summary=None（absent 如实）。"""
    r = em.run_bench_task(_tasks_by_id()["syn-cpw"], work_root=tmp_path)
    assert r["hidden_summary"] is None


def test_r01_spec_score_covers_hidden_layer(tmp_path, probe_family):
    """spec_score 分母=visible+hidden 全体已判定检查（隐藏层计入占比，
    与 hidden_summary 汇总粒度一致——不新增泄漏面）。"""
    task = em.BenchTask.model_validate(_probe_task(
        input_spec={"measures": {
            "gate_pass": {"passed": False, "gate": "g"},
            "certificate_pass": {"passed": True, "n_diff": 0}}},
        hidden_criteria=[{"name": "certificate_pass"}]))
    r = em.run_bench_task(task, work_root=tmp_path)
    assert r["verdict"] == "fail"
    assert r["spec_score"] == pytest.approx(0.5)  # 1 pass / 2 judged（含 hidden）


# ---------------------------------------------------------------------------
# ④ negative_variants 反例集
# ---------------------------------------------------------------------------


def test_r01_negative_variants_vendor_search_real(tmp_path):
    """缺省任务真反例：语料外期望词查询走真 FTS5 管线 → 判据判 fail
    （ok∧execute∧verdict=fail 三件齐）。"""
    rep = em.check_negative_variants(_tasks_by_id()["vendor-search"],
                                     work_root=tmp_path)
    assert rep["status"] == "pass" and rep["ok"] is True
    row = rep["results"][0]
    assert row["variant_id"] == "noop-queries-absent-terms"
    assert row["pipeline_ok"] is True and row["stage"] == "execute"
    assert row["verdict"] == "fail" and row["judged_fail"] is True


def test_r01_negative_variant_not_failing_is_unknown(tmp_path, probe_family):
    """反例判不出 fail → 检查态 unknown（判据退化如实——阈值 0 的
    success_rate 让空产出 pass=空过判据，反例门当场拦下）。"""
    task = em.BenchTask.model_validate(_probe_task(
        criteria=[{"name": "success_rate", "threshold": 0.0}],
        negative_variants=[{"variant_id": "v1",
                            "input_spec": {"measures": {"success_rate": {
                                "n_ok": 0, "n_total": 1}}}}]))
    rep = em.check_negative_variants(task, work_root=tmp_path)
    assert rep["status"] == "unknown" and rep["ok"] is False
    assert rep["results"][0]["judged_fail"] is False
    assert rep["results"][0]["verdict"] == "pass"


def test_r01_negative_variant_crash_not_counted_as_judged_fail(
        tmp_path, probe_family):
    """执行崩溃的 fail 不算"判据判 fail"（pipeline ok=False → judged_fail
    False → unknown——不凑绿：没跑成≠判错答案）。"""
    task = em.BenchTask.model_validate(_probe_task(
        negative_variants=[{"variant_id": "boom", "input_spec": {"boom": True}}]))
    rep = em.check_negative_variants(task, work_root=tmp_path)
    assert rep["status"] == "unknown" and rep["ok"] is False
    row = rep["results"][0]
    assert row["pipeline_ok"] is False and row["verdict"] == "fail"
    assert row["judged_fail"] is False
    assert "RuntimeError" in row["errors"][0]


def test_r01_negative_variants_absent(tmp_path, probe_family):
    """无反例 → absent（缺席不是通过也不是失败——ok=True 仅表示无可拦项）。"""
    rep = em.check_negative_variants(em.BenchTask.model_validate(_probe_task()),
                                     work_root=tmp_path)
    assert rep["status"] == "absent" and rep["n_variants"] == 0
    assert rep["ok"] is True and "absent" in rep["note"]


def test_r01_negative_variant_bad_task_unknown(tmp_path):
    """任务 schema 非法 → 检查态 unknown（未运行如实，不冒充 pass）。"""
    rep = em.check_negative_variants({"task_id": "bad", "family": _PROBE_FAMILY,
                                      "criteria": []})
    assert rep["status"] == "unknown" and rep["ok"] is False


# ---------------------------------------------------------------------------
# ⑤ no-op 必败门 + 任务准入门
# ---------------------------------------------------------------------------


def test_r01_noop_probe_registry_covers_criteria_enum():
    """no-op 输出单源覆盖判据枚举闭集（新判据注册须同笔登记 no-op 形态）。"""
    assert set(em.NOOP_PROBE_MEASURES) == set(em.CRITERIA_NAMES)


def test_r01_admit_vendor_search_admitted(tmp_path):
    """真任务准入门正例：vendor-search 三探针全过 → admitted（no-op 必败
    fail/oracle 5 次稳定 pass/真反例判 fail）。"""
    rep = em.admit_bench_task(
        _tasks_by_id()["vendor-search"],
        oracle_measures={"success_rate": {"n_ok": 3, "n_total": 3}},
        work_root=tmp_path)
    assert rep["status"] == "admitted" and rep["admitted"] is True
    assert rep["probes"]["noop"]["ok"] is True
    assert rep["probes"]["noop"]["verdict"] == "fail"
    assert rep["probes"]["noop"]["source"] == "NOOP_PROBE_MEASURES"
    o = rep["probes"]["oracle_stability"]
    assert o["ok"] is True and o["n_runs"] == 5 and o["stable"] is True
    assert o["verdicts"] == ["pass"] * 5
    assert rep["probes"]["negative_variants"]["status"] == "pass"
    assert rep["errors"] == []


def test_r01_admit_numeric_only_noop_unknown_quarantined(tmp_path):
    """纯数值判据任务：no-op 缺测语义=unknown（既有语义不改）→ no-op 必败
    未证明 → quarantined 如实（不是通过也不是拒绝）。"""
    rep = em.admit_bench_task(
        _tasks_by_id()["syn-cpw"],
        oracle_measures={"closedform_match": {"deviation": 1e-6}},
        work_root=tmp_path)
    assert rep["status"] == "quarantined" and rep["admitted"] is False
    assert rep["probes"]["noop"]["verdict"] == "unknown"
    assert any("no-op 探针未判 fail" in e for e in rep["errors"])
    # oracle 探针本身干净（稳定 pass）——quarantine 只因 no-op 未证明
    assert rep["probes"]["oracle_stability"]["ok"] is True


def test_r01_admit_vacuous_threshold_noop_pass_quarantined(tmp_path, probe_family):
    """最严重档：空产出被判据判 pass（阈值 0 的 success_rate=空过判据）
    → quarantined 且报错点名判据退化。"""
    rep = em.admit_bench_task(
        em.BenchTask.model_validate(_probe_task(
            criteria=[{"name": "success_rate", "threshold": 0.0}])),
        oracle_measures={"success_rate": {"n_ok": 1, "n_total": 1}},
        work_root=tmp_path)
    assert rep["status"] == "quarantined"
    assert rep["probes"]["noop"]["verdict"] == "pass"
    assert any("空过判据" in e for e in rep["errors"])


def test_r01_admit_oracle_unstable_quarantined(tmp_path, probe_family, monkeypatch):
    """oracle 稳定探针：判据随跑漂移（奇偶交替 verdict）→ 5 次判定不一致
    → quarantined（确定性判据的稳定性门）。"""
    calls = {"n": 0}

    def _flaky(measure, threshold):
        calls["n"] += 1
        passed = calls["n"] % 2 == 1
        return em._outcome(1.0 if passed else 0.0,
                           "pass" if passed else "fail", threshold)

    monkeypatch.setitem(em._CRITERION_REGISTRY, "gate_pass", _flaky)
    rep = em.admit_bench_task(
        em.BenchTask.model_validate(_probe_task()),
        oracle_measures={"gate_pass": {"passed": True, "gate": "g"}},
        work_root=tmp_path)
    assert rep["status"] == "quarantined"
    o = rep["probes"]["oracle_stability"]
    assert o["stable"] is False and len(o["verdicts"]) == 5
    assert len(set(o["verdicts"])) > 1
    assert any("不一致" in e for e in rep["errors"])


def test_r01_admit_oracle_not_pass_quarantined(tmp_path, probe_family):
    """oracle 输出判不过（已知好输出判 fail）→ quarantined——oracle 解必须过。"""
    rep = em.admit_bench_task(
        em.BenchTask.model_validate(_probe_task()),
        oracle_measures={"gate_pass": {"passed": False, "gate": "g"}},
        work_root=tmp_path)
    assert rep["status"] == "quarantined"
    o = rep["probes"]["oracle_stability"]
    assert o["stable"] is True and o["verdict"] == "fail" and o["ok"] is False
    assert any("oracle 输出未判 pass" in e for e in rep["errors"])


def test_r01_admit_rejected_paths(probe_family):
    """结构拒绝三态：schema 非法/family 无 runner/预声明阈值缺失 → rejected
    且 probes 不运行。"""
    rep1 = em.admit_bench_task({"task_id": "x", "family": _PROBE_FAMILY,
                                "criteria": []},
                               oracle_measures={})
    assert rep1["status"] == "rejected" and "schema" in rep1["errors"][0]
    rep2 = em.admit_bench_task({"task_id": "x", "family": "no_such_family",
                                "criteria": [{"name": "gate_pass"}]},
                               oracle_measures={"gate_pass": {"passed": True}})
    assert rep2["status"] == "rejected" and "无注册 runner" in rep2["errors"][0]
    rep3 = em.admit_bench_task(
        {"task_id": "x", "family": _PROBE_FAMILY,
         "criteria": [{"name": "closedform_match"}]},
        oracle_measures={"closedform_match": {"deviation": 0.0}})
    assert rep3["status"] == "rejected" and "缺预声明阈值" in rep3["errors"][0]
    for rep in (rep1, rep2, rep3):
        assert rep["probes"] == {} and rep["admitted"] is False


def test_r01_admit_negative_variant_failure_quarantined(tmp_path, probe_family):
    """反例判不出 fail → 准入 quarantined（探针③接线钉）。"""
    rep = em.admit_bench_task(
        em.BenchTask.model_validate(_probe_task(
            criteria=[{"name": "success_rate", "threshold": 0.0}],
            negative_variants=[{"variant_id": "v1",
                                "input_spec": {"measures": {"success_rate": {
                                    "n_ok": 0, "n_total": 1}}}}])),
        oracle_measures={"success_rate": {"n_ok": 1, "n_total": 1}},
        work_root=tmp_path)
    assert rep["status"] == "quarantined"
    assert rep["probes"]["negative_variants"]["status"] == "unknown"
    assert any("反例自检未过" in e for e in rep["errors"])


def test_r01_admit_noop_measures_override(tmp_path, probe_family):
    """no-op 输出显式覆盖：声明 fail 形态 → 门过（source=caller_declared）；
    覆盖降不了门——喂出 pass 照样 quarantined。"""
    good = em.admit_bench_task(
        em.BenchTask.model_validate(_probe_task()),
        oracle_measures={"gate_pass": {"passed": True, "gate": "g"}},
        noop_measures={"gate_pass": {"passed": False, "gate": "custom"}},
        work_root=tmp_path)
    assert good["status"] == "admitted"
    assert good["probes"]["noop"]["source"] == "caller_declared"
    bad = em.admit_bench_task(
        em.BenchTask.model_validate(_probe_task()),
        oracle_measures={"gate_pass": {"passed": True, "gate": "g"}},
        noop_measures={"gate_pass": {"passed": True, "gate": "custom"}},
        work_root=tmp_path)
    assert bad["status"] == "quarantined"
    assert any("空过判据" in e for e in bad["errors"])


def test_r01_admit_oracle_runs_validation(probe_family):
    """oracle_runs 非法（0/bool）→ ValueError fail-closed（探针族已注册，
    结构检查全过——校验真达参数面）。"""
    with pytest.raises(ValueError, match="oracle_runs"):
        em.admit_bench_task(_probe_task(), oracle_measures={}, oracle_runs=0)
    with pytest.raises(ValueError, match="oracle_runs"):
        em.admit_bench_task(_probe_task(), oracle_measures={}, oracle_runs=True)


def test_r01_admit_tasks_batch_partition(tmp_path):
    """批量准入分区：admitted/quarantined/rejected 三清单记账（vendor-search
    准入/syn-cpw no-op 未证明隔离/未知 family 拒绝/syn-mline 无 oracle 条目
    隔离——oracle 是准入必需品，缺席如实 quarantined 不猜）。"""
    batch = em.admit_bench_tasks(
        [_tasks_by_id()["vendor-search"], _tasks_by_id()["syn-cpw"],
         {"task_id": "nope", "family": "ghost",
          "criteria": [{"name": "gate_pass"}]},
         _tasks_by_id()["syn-mline"]],
        oracle_measures_by_task={
            "vendor-search": {"success_rate": {"n_ok": 3, "n_total": 3}},
            "syn-cpw": {"closedform_match": {"deviation": 1e-6}},
            "nope": {"gate_pass": {"passed": True}},
        },
        work_root=tmp_path)
    assert batch["n_tasks"] == 4
    assert (batch["n_admitted"], batch["n_quarantined"], batch["n_rejected"]) \
        == (1, 2, 1)
    assert batch["admitted"] == ["vendor-search"]
    assert batch["rejected"] == ["nope"]
    assert batch["quarantined"] == ["syn-cpw", "syn-mline"]
    no_oracle = [r for r in batch["reports"]
                 if r["task_id"] == "syn-mline" and r["status"] == "quarantined"]
    assert no_oracle and "oracle" in no_oracle[0]["errors"][0]
    assert no_oracle[0]["probes"] == {}  # oracle 缺席 → 探针未运行


# ---------------------------------------------------------------------------
# ⑥ B3 OOD 探针 + 训练包络守卫
# ---------------------------------------------------------------------------


def test_r01_envelope_absent_block(tmp_path):
    """包络未声明 → envelope=absent 如实输出（ood_flag=False 不伪造）。"""
    r = em.run_bench_task(_tasks_by_id()["syn-cpw"], work_root=tmp_path)
    assert r["envelope"]["status"] == "absent"
    assert r["ood_flag"] is False
    assert r["envelope"]["violations"] == []
    assert "absent" in r["envelope"]["note"]


def test_r01_envelope_declared_in_bounds(tmp_path):
    """syn-mline 声明包络+域内点 → status=declared/ood_flag=False/两键 checked。"""
    r = em.run_bench_task(_tasks_by_id()["syn-mline"], work_root=tmp_path)
    env = r["envelope"]
    assert env["status"] == "declared"
    assert env["ood_flag"] is False and env["violations"] == []
    assert sorted(env["checked_keys"]) == ["freq_ghz", "z0_ohm"]
    assert env["unverified_keys"] == []


def test_r01_envelope_ood_flag_true_verdict_unchanged(tmp_path):
    """越界点 → ood_flag=True 且 verdict 本体零变（综合回代仍自洽 pass
    ——B3 红线：OOD 标记不裁 verdict）；违例行带键值与界。"""
    ood_task = _tasks_by_id()["syn-mline"].model_copy(update={
        "input_spec": {"kind": "mline",
                       "params": {"z0_ohm": 150.0, "freq_ghz": 2.5}}})
    r = em.run_bench_task(ood_task, work_root=tmp_path)
    assert r["verdict"] == "pass" and r["ok"] is True
    assert r["ood_flag"] is True
    assert r["envelope"]["violations"] == [
        {"key": "z0_ohm", "value": 150.0, "bound_min": 40.0, "bound_max": 120.0}]


def test_r01_envelope_unverified_keys_not_fabricated(tmp_path, probe_family):
    """包络键在评估点缺席 → ood_flag=False + unverified_keys 如实（未验证
    不判 OOD——不伪造），note 声明未验证语义。"""
    task = em.BenchTask.model_validate(_probe_task(
        input_spec={"measures": {"gate_pass": {"passed": True, "gate": "g"}}},
        envelope={"w_mm": {"min": 0.1, "max": 5.0}}))
    r = em.run_bench_task(task, work_root=tmp_path)
    assert r["verdict"] == "pass"
    assert r["ood_flag"] is False
    assert r["envelope"]["unverified_keys"] == ["w_mm"]
    assert "未验证" in r["envelope"]["note"]


def test_r01_bench_envelope_point_extraction():
    """评估点提取：嵌套 Mapping 数值叶收集/bool 与字符串与列表排除/键冲突
    首现胜（确定性）。"""
    point = em.bench_envelope_point({
        "geometry": {"w_mm": 0.52, "b_mm": 0.50, "eps_r": 11.9},
        "hfss_implied": {"eps_eff": 1.59, "z0_ohm": 50.2},
        "params": {"z0_ohm": 75.0},  # z0_ohm 键冲突——hfss_implied 首现胜
        "flag": True, "name": "abc", "band": [1.0, 2.0],
        "nested": {"deep": {"k": 3}},
    })
    assert point == {"w_mm": 0.52, "b_mm": 0.50, "eps_r": 11.9,
                     "eps_eff": 1.59, "z0_ohm": 50.2, "k": 3}
    assert point["z0_ohm"] == 50.2  # 首现胜（非后到覆盖）
    assert "flag" not in point and "name" not in point and "band" not in point
    dup = em.bench_envelope_point({"a": {"k": 1.0}, "b": {"k": 2.0}})
    assert dup == {"k": 1.0}  # 首现胜
    assert em.bench_envelope_point(None) == {}
    assert em.bench_envelope_point({}) == {}


def test_r01_evaluate_bench_envelope_unit():
    """包络判定纯函数：min-only/max-only/双界/越界方向/非数值 unverified。"""
    rep = em.evaluate_bench_envelope(
        {"p_low": {"min": 0.0}, "p_high": {"max": 10.0},
         "p_both": {"min": 1.0, "max": 2.0}},
        {"p_low": -0.5, "p_high": 11.0, "p_both": 1.5})
    assert rep["status"] == "declared" and rep["ood_flag"] is True
    assert rep["violations"] == [
        {"key": "p_low", "value": -0.5, "bound_min": 0.0, "bound_max": None},
        {"key": "p_high", "value": 11.0, "bound_min": None, "bound_max": 10.0}]
    assert rep["checked_keys"] == ["p_low", "p_high", "p_both"]
    rep2 = em.evaluate_bench_envelope({"x": {"min": 0.0}}, {"x": "abc"})
    assert rep2["ood_flag"] is False and rep2["unverified_keys"] == ["x"]
    rep3 = em.evaluate_bench_envelope({"x": {"min": 1.0}}, {"y": 5.0})
    assert rep3["ood_flag"] is False and rep3["checked_keys"] == []
    # 边界恰等（min ≤ val ≤ max）不算越界
    rep4 = em.evaluate_bench_envelope({"x": {"min": 1.0, "max": 2.0}},
                                      {"x": 1.0})
    assert rep4["ood_flag"] is False and rep4["violations"] == []


def test_r01_envelope_on_failure_path_declared_unverified(tmp_path, probe_family):
    """已声明包络的任务 runner 缺席 → validate fail 结果中 envelope 仍
    status=declared（声明在场不谎报 absent），全键 unverified+note。"""
    r = em.run_bench_task({"task_id": "envfail", "family": "ghost_family",
                           "criteria": [{"name": "gate_pass"}],
                           "envelope": {"p": {"min": 0.0}}},
                          work_root=tmp_path)
    assert r["ok"] is False and r["verdict"] == "fail"
    assert r["envelope"]["status"] == "declared"
    assert r["ood_flag"] is False
    assert r["envelope"]["unverified_keys"] == ["p"]
    assert "未达评估点" in r["envelope"]["note"]


def test_r01_envelope_schema_fail_unknown_block(tmp_path):
    """schema 校验失败 → envelope status=unknown（任务形态不可读——声明
    不可知如实，不冒充 absent）。"""
    r = em.run_bench_task({"task_id": "broken", "family": _PROBE_FAMILY,
                           "criteria": []}, work_root=tmp_path)
    assert r["verdict"] == "fail" and r["stage"] == "validate"
    assert r["envelope"]["status"] == "unknown"
    assert "不可知" in r["envelope"]["note"]


# ---------------------------------------------------------------------------
# 公开面申报（public_api 金快照由主代合流再生——本席不动 gold）+ JSON 安全
# ---------------------------------------------------------------------------


def test_r01_public_api_new_names_declared():
    """R-01 新公开名 +10 全部进 __all__（金快照再生=主代合流动作，申报口径）。"""
    new_names = (
        "NOOP_PROBE_MEASURES", "BenchGraderNotes", "BenchNegativeVariant",
        "EnvelopeBound", "admit_bench_task", "admit_bench_tasks",
        "bench_envelope_point", "check_negative_variants",
        "evaluate_bench_envelope", "spec_score_from_scores",
    )
    for name in new_names:
        assert name in em.__all__, f"缺申报公开名: {name}"
    assert len(em.__all__) == 29  # 既有 24 + 10−5（v0.14.0 移除笔摘 proposals 面公开名）


def test_r01_result_json_safe_with_new_fields(tmp_path):
    """新报告列全 JSON 安全（落档前提）：grader_notes/envelope/
    hidden_summary/spec_score dump 往返同构。"""
    r = em.run_bench_task(_tasks_by_id()["vendor-search"], work_root=tmp_path)
    text = json.dumps(r, ensure_ascii=False, sort_keys=True)
    back = json.loads(text)
    assert back["grader_notes"]["correct_core"] == r["grader_notes"]["correct_core"]
    assert back["envelope"]["status"] == "absent"
    assert back["spec_score"] == 1.0
