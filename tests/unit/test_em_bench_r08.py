"""em_bench 模拟侧任务族定向测试（aurora_r R-08 席，AX-8 四族+B5 逆设计）。

覆盖（任务书验收口径）：
- AX-8 vaBench 四任务族（spec-to-va/tb-generation/end-to-end/bugfix）：全链
  run verdict+判据面（解析接受门+must_include 要素命中）/负例 judged fail/
  unknown kind 与空 tokens fail-closed；
- B5 逆设计任务族：预声明双轴显式口径（频偏≤tol1+幅度偏差≤tol2）命中度/
  invalid 候选判 miss 不崩溃/未知 target_id fail-closed/合成响应面逐位可复现/
  hidden 一致性门防伪造（visible pass ∧ hidden fail → verdict fail——AX-1③
  分层语义）/B3 包络 ood_flag 不改 verdict 本体；
- R-01 准入门接线：七任务全部 admitted（noop/oracle×5 稳定/反例自检三探针）
  +oracle 目录=runner 实测测度+批量分区；
- 注册纪律：import 期不注册（进程级闭集钉保护）/installer 幂等+冲突拒收/
  判据枚举零新增（词表闭集防漂移）/不入 default_bench_tasks（15 锚钉不动）；
- L2 挂账申报：L2_DEFERRAL 五族覆盖+模块源码零 pssfss import（不伪造 L2）。

零网络零真机零 LLM（#139）：veriloga_parser 只读消费+纯文本判据；注册表
经 monkeypatch 注入（R-01 探针族同款，自动还原）；湖写只落 tmp。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service import em_bench_analog_service as vab
from rfauto.service import em_bench_service as em


@pytest.fixture
def va_families(monkeypatch):
    """注入五族 runner 到 em_bench 运行注册表（monkeypatch 自动还原——
    进程级闭集钉保护：import 期不注册，测试期显式注入）。"""
    for fam, fn in vab.VA_BENCH_RUNNERS.items():
        monkeypatch.setitem(em._RUNNER_REGISTRY, fam, fn)
    return dict(vab.VA_BENCH_RUNNERS)


def _tasks_by_id() -> dict[str, em.BenchTask]:
    return {t.task_id: t for t in vab.default_va_bench_tasks()}


# ---------------------------------------------------------------------------
# 任务集结构与判据纪律
# ---------------------------------------------------------------------------


def test_r08_default_va_tasks_structure():
    """七任务结构钉：id 唯一/family 全覆盖/判据≥1/数据源/grader_notes/
    反例 ≥1/命中率阈值预声明（#122）。"""
    tasks = vab.default_va_bench_tasks()
    assert len(tasks) == 7
    ids = [t.task_id for t in tasks]
    assert len(set(ids)) == 7
    assert {t.family for t in tasks} == set(vab.ANALOG_BENCH_FAMILIES)
    for t in tasks:
        assert len(t.criteria) >= 1
        assert t.data_source.strip()
        assert t.grader_notes is not None
        assert t.grader_notes.correct_core and t.grader_notes.common_errors
        assert t.grader_notes.partial_credit.strip()
        assert len(t.negative_variants) >= 1
        for c in [*t.criteria, *t.hidden_criteria]:
            if c.name in em.THRESHOLD_REQUIRED:
                assert c.threshold is not None, f"{t.task_id}.{c.name} 缺阈值"
    # 每族至少一个任务且判据面齐全（AX-8 四族+B5 一族）
    fam_ids = {t.family: t.task_id for t in tasks}
    assert set(fam_ids) == {vab.VA_FAMILY_SPEC_TO_VA, vab.VA_FAMILY_TB_GENERATION,
                            vab.VA_FAMILY_END_TO_END, vab.VA_FAMILY_BUGFIX,
                            vab.B5_FAMILY_INVERSE_DESIGN}


def test_r08_criteria_enum_zero_new_names():
    """判据枚举零新增（词表闭集防漂移——Q-X43 钉纪律）：本模块五族只复用
    gate_pass/success_rate；family 词表不入 BENCH_FAMILIES 闭集且 import 期
    不注册（进程级注册表保护）。"""
    assert len(em.CRITERIA_NAMES) == 10
    used = set()
    for t in vab.default_va_bench_tasks():
        used |= {c.name for c in t.criteria}
        used |= {c.name for c in t.hidden_criteria}
    assert used == {"gate_pass", "success_rate"}
    assert used <= set(em.CRITERIA_NAMES)
    assert not (set(vab.ANALOG_BENCH_FAMILIES) & set(em.BENCH_FAMILIES))
    for fam in vab.ANALOG_BENCH_FAMILIES:
        assert fam not in em.registered_families()


def test_r08_l2_deferral_declared_and_no_pssfss_import():
    """L2 金标挂账申报面：L2_DEFERRAL 五族覆盖+每条声明挂账态+模块源码零
    pssfss/pypssfss import（本席不伪造 L2 结果——两级验证路由第二级缺席
    如实 absent）。"""
    assert set(vab.L2_DEFERRAL) == set(vab.ANALOG_BENCH_FAMILIES)
    for fam, note in vab.L2_DEFERRAL.items():
        assert "挂账" in note, f"{fam} L2 声明缺挂账态"
    src = inspect.getsource(vab)
    assert "pypssfss" not in src
    # import 行扫描（docstring 提及 PSSFSS 适配器路径属挂账声明面，允许；
    # 代码 import 一律无——本席零 PSSFSS 调用）
    import_lines = [ln for ln in src.splitlines()
                    if ln.strip().startswith(("import ", "from "))
                    and "pssfss" in ln.lower()]
    assert not import_lines


def test_r08_module_zero_llm_import_surface():
    """零 LLM 面（T-Q24 红线静态钉，R-01 同款）：本模块 AST import 扫描
    ——LLM 通道/proposer 零触碰（确定性判据红线）。"""
    import ast

    banned = ("llm_transport", "proposer", "openai", "anthropic",
              "pydantic_ai", "agent_sandbox", "agent_runtime")
    source = Path(vab.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    for mod in imported:
        low = mod.lower()
        assert not any(b in low for b in banned), f"禁入 LLM 面 import: {mod}"


# ---------------------------------------------------------------------------
# AX-8 ① spec-to-va
# ---------------------------------------------------------------------------


def test_r08_run_spec_to_va_pass(va_families, tmp_path):
    """spec-to-va 全链：解析接受门+8 要素全命中 → verdict pass（含
    spec_score=1.0 与 detail 双旗分解）。"""
    t = _tasks_by_id()["va-spec-to-va"]
    r = em.run_bench_task(t, work_root=tmp_path / "s2v")
    assert r["ok"] and r["stage"] == "execute" and r["verdict"] == "pass"
    assert r["scores"]["gate_pass"]["verdict"] == "pass"
    assert r["scores"]["gate_pass"]["value"] == 1.0
    assert r["scores"]["success_rate"]["verdict"] == "pass"
    assert r["scores"]["success_rate"]["value"] == 1.0
    assert r["scores"]["success_rate"]["threshold"] == vab._VA_HIT_RATE_MIN
    assert r["spec_score"] == 1.0
    assert r["detail"]["parse_ok"] is True
    assert r["detail"]["module_present"] is True
    assert len(r["detail"]["elements"]) == 8  # 2 端口+2 参数+1 贡献+3 文本
    assert all(e["hit"] for e in r["detail"]["elements"])


def test_r08_spec_to_va_parse_fail_and_neg_variant(va_families, tmp_path):
    """spec-to-va 反例面：解析失败候选→门 fail+结构性要素全 miss（
    fail-closed）/缺省任务负例（参数缺席+禁用算子）judged fail。"""
    t = _tasks_by_id()["va-spec-to-va"]
    broken = t.model_copy(update={"input_spec": {
        "spec": dict(t.input_spec["spec"]),
        "candidate_va": t.input_spec["candidate_va"].replace(
            "analog begin", "analog begin /* 未闭合"),
    }})
    r = em.run_bench_task(broken, work_root=tmp_path / "s2v_broken")
    assert r["ok"] and r["verdict"] == "fail"
    assert r["scores"]["gate_pass"]["verdict"] == "fail"
    assert r["detail"]["parse_ok"] is False and r["detail"]["parse_error"]
    structural = [e for e in r["detail"]["elements"]
                  if e["kind"] in ("port", "param", "contribution_lhs")]
    assert structural and all(not e["hit"] for e in structural)
    # 缺省任务负例（AX-1④）：解析通过但要素双 miss → 判据判 fail
    neg = em.check_negative_variants(t, work_root=tmp_path / "s2v_neg")
    assert neg["status"] == "pass" and neg["results"][0]["judged_fail"]


def test_r08_spec_element_unknown_kind_fail_closed(va_families):
    """未知要素 kind → ValueError（fail-closed 不猜——判读函数拒绝路径；
    doc=None 时非文本 kind 先落入解析失败 miss 分支，故须给合法 doc+body
    才达防御性 kind 闭集拒绝）。"""
    assert va_families is not None  # fixture 注入（本测只打判读函数，注入保持一致性）
    doc = {"modules": {"m": {"ports": [], "params": [],
                             "analog": {"contributions": []}}}}
    with pytest.raises(ValueError, match="未知规格要素 kind"):
        vab._spec_element_hit({"kind": "hacker", "element_id": "x"},
                              doc, "m", "text")


# ---------------------------------------------------------------------------
# AX-8 ② tb-generation
# ---------------------------------------------------------------------------


def test_r08_run_tb_generation_pass_and_negative(va_families, tmp_path):
    """tb-generation 全链：三要素组齐备+DUT 锚 → pass；负例（监测/控制缺位
    +未引用 DUT）judged fail；空 tokens 组 fail-closed。"""
    t = _tasks_by_id()["va-tb-generation"]
    r = em.run_bench_task(t, work_root=tmp_path / "tb")
    assert r["ok"] and r["verdict"] == "pass"
    assert r["scores"]["gate_pass"]["verdict"] == "pass"
    assert r["detail"]["dut_parse_ok"] is True
    assert r["detail"]["dut_module_referenced"] is True
    assert len(r["detail"]["tb_groups"]) == 3
    assert all(g["hit"] for g in r["detail"]["tb_groups"])
    assert r["scores"]["success_rate"]["value"] == 1.0
    # 负例 judged fail（AX-1④）
    neg = em.check_negative_variants(t, work_root=tmp_path / "tb_neg")
    assert neg["status"] == "pass" and neg["results"][0]["judged_fail"]
    neg_run = em.run_bench_task(
        t.model_copy(update={"input_spec": dict(t.negative_variants[0].input_spec)}),
        work_root=tmp_path / "tb_neg_run")
    assert neg_run["verdict"] == "fail"
    assert neg_run["scores"]["gate_pass"]["verdict"] == "fail"
    assert [g["hit"] for g in neg_run["detail"]["tb_groups"]] == [True, False, False]
    # 空 tokens 组 → ValueError fail-closed
    bad = t.model_copy(update={"input_spec": {
        **dict(t.input_spec), "tb_elements": [{"element_id": "x", "tokens": []}]}})
    r_bad = em.run_bench_task(bad, work_root=tmp_path / "tb_bad")
    assert r_bad["ok"] is False and r_bad["stage"] == "execute"


# ---------------------------------------------------------------------------
# AX-8 ③ end-to-end
# ---------------------------------------------------------------------------


def test_r08_run_end_to_end_pass_and_negative(va_families, tmp_path):
    """end-to-end 全链：组合①②判据（11 要素+组单一名分母）→ pass；词法
    损坏候选 → 门 fail+结构性要素全 miss judged fail。"""
    t = _tasks_by_id()["va-end-to-end"]
    r = em.run_bench_task(t, work_root=tmp_path / "e2e")
    assert r["ok"] and r["verdict"] == "pass"
    assert r["scores"]["success_rate"]["value"] == 1.0
    assert r["detail"]["parse_ok"] and r["detail"]["module_present"]
    assert r["detail"]["tb_module_referenced"]
    assert len(r["detail"]["elements"]) == 8 and len(r["detail"]["tb_groups"]) == 3
    neg = em.check_negative_variants(t, work_root=tmp_path / "e2e_neg")
    assert neg["status"] == "pass" and neg["results"][0]["judged_fail"]


# ---------------------------------------------------------------------------
# AX-8 ④ bugfix
# ---------------------------------------------------------------------------


def test_r08_run_bugfix_pass_and_negative(va_families, tmp_path):
    """bugfix 全链：双缺陷消除+功能保全 → pass（分母 4）；no-op 修复负例
    judged fail；半修复（只改一处）→ 3/4 判 fail 不凑绿。"""
    t = _tasks_by_id()["va-bugfix"]
    r = em.run_bench_task(t, work_root=tmp_path / "bf")
    assert r["ok"] and r["verdict"] == "pass"
    assert r["scores"]["success_rate"]["value"] == 1.0
    assert r["scores"]["gate_pass"]["verdict"] == "pass"
    assert all(d["eliminated"] for d in r["detail"]["defects"])
    assert all(k["present"] for k in r["detail"]["must_keep"])
    neg = em.check_negative_variants(t, work_root=tmp_path / "bf_neg")
    assert neg["status"] == "pass" and neg["results"][0]["judged_fail"]
    # 半修复：从缺陷源出发只修反向取样、留幽灵因子 → success_rate=3/4 → 判 fail
    half = t.input_spec["broken_va"].replace("I(n, p)", "I(p, n)")
    assert "gain_k" in half and "I(n, p)" not in half
    t_half = t.model_copy(update={"input_spec": {
        **dict(t.input_spec), "candidate_va": half}})
    r_half = em.run_bench_task(t_half, work_root=tmp_path / "bf_half")
    assert r_half["verdict"] == "fail"
    assert r_half["scores"]["success_rate"]["value"] == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# B5 逆设计
# ---------------------------------------------------------------------------


def test_r08_inverse_design_hit_rate_explicit_formula(va_families, tmp_path):
    """B5 命中判据显式口径：freq_dev=|Δf0|/f0_t ≤tol_freq_rel ∧
    dip_dev=|Δdip|≤tol_dip_db；混合候选面 2/3≥0.5 pass；逐候选 dev 逐位
    断言（同 surface_response 单源重算——逐位可复现）。"""
    t = _tasks_by_id()["inverse-design-surface-halfwave"]
    r = em.run_bench_task(t, work_root=tmp_path / "b5a")
    assert r["ok"] and r["verdict"] == "pass"
    assert r["scores"]["success_rate"]["value"] == pytest.approx(2.0 / 3.0)
    assert r["scores"]["success_rate"]["threshold"] == 0.5
    rows = {row["candidate_id"]: row for row in r["detail"]["candidates"]}
    for cid in ("c_hit_l30", "c_hit_l31", "c_freq_miss"):
        params = t.input_spec["candidates"][cid]["params"]
        exp_f0 = vab.surface_response(params)["f0_ghz"]
        exp_dev = abs(exp_f0 - 2.4) / 2.4
        assert rows[cid]["freq_dev_rel"] == exp_dev  # 逐位（同函数同输入）
    assert [rows[c]["hit"] for c in ("c_hit_l30", "c_hit_l31", "c_freq_miss")] \
        == [True, True, False]
    assert rows["c_freq_miss"]["freq_dev_rel"] > 0.02  # 频偏越界
    assert rows["c_freq_miss"]["dip_dev_db"] <= 2.5    # 幅度轴在带（双轴独立）


def test_r08_surface_bitwise_reproducible():
    """合成响应面逐位可复现：同输入重复调用逐位一致；三演示任务缺省候选
    response==surface_response(params) 逐位（by construction 单源）。"""
    params = {"l_mm": 30.0, "eps_r": 4.34, "g_mm": 0.24}
    a = vab.surface_response(params)
    b = vab.surface_response(params)
    assert a == b and list(a) == ["f0_ghz", "dip_db"]
    for t in vab.default_va_bench_tasks():
        if t.family != vab.B5_FAMILY_INVERSE_DESIGN:
            continue
        for cand in t.input_spec["candidates"].values():
            assert cand["response"] == vab.surface_response(cand["params"])
    # 非法参数 fail-closed（零/负/缺键）
    for bad in ({"l_mm": 0.0, "eps_r": 4.0, "g_mm": 0.2},
                {"l_mm": 30.0, "eps_r": -4.0, "g_mm": 0.2},
                {"l_mm": 30.0, "eps_r": 4.0}):
        with pytest.raises(ValueError):
            vab.surface_response(bad)


def test_r08_inverse_design_invalid_response_miss_not_crash(va_families, tmp_path):
    """候选 response 垃圾（非数值/缺键）→ 判 miss 不崩溃（候选质量=被评判
    对象；任务定义错误才 fail-closed）——judged fail 完成态。"""
    t = _tasks_by_id()["inverse-design-surface-halfwave"]
    bad_input = {
        "targets": dict(t.input_spec["targets"]),
        "candidates": {"c_garbage": {
            "target_id": "t_main", "params": {"l_mm": 30.0, "eps_r": 4.34,
                                              "g_mm": 0.24},
            "response": {"f0_ghz": "x", "dip_db": None}}},
        "surface_check": True,
    }
    r = em.run_bench_task(t.model_copy(update={"input_spec": bad_input}),
                          work_root=tmp_path / "b5_garbage")
    assert r["ok"] and r["stage"] == "execute" and r["verdict"] == "fail"
    assert r["scores"]["success_rate"]["value"] == 0.0
    row = r["detail"]["candidates"][0]
    assert row["hit"] is False and "invalid_response" in row["note"]
    # 未知 target_id=任务定义错误 → fail-closed（执行失败如实 fail）
    bad_anchor = {"targets": dict(t.input_spec["targets"]),
                  "candidates": {"c_bad": {"target_id": "nope",
                                           "params": {"l_mm": 30.0, "eps_r": 4.34,
                                                      "g_mm": 0.24},
                                           "response": {"f0_ghz": 2.4,
                                                        "dip_db": -20.0}}}}
    r_anchor = em.run_bench_task(t.model_copy(update={"input_spec": bad_anchor}),
                                 work_root=tmp_path / "b5_anchor")
    assert r_anchor["ok"] is False and r_anchor["stage"] == "execute"


def test_r08_inverse_design_fabricated_hidden_gate(va_families, tmp_path):
    """防伪造门（AX-1③ hidden 分层）：编造 response 恰好达标值——visible
    success_rate pass ∧ hidden 一致性门 fail → 任务 verdict fail（报告面
    scores 只含 visible 明细，hidden 只出汇总）。"""
    t = _tasks_by_id()["inverse-design-surface-strict"]
    r = em.run_bench_task(t, work_root=tmp_path / "b5b")
    assert r["verdict"] == "pass"
    assert r["hidden_summary"] == {"n_total": 1, "n_pass": 1, "n_fail": 0,
                                   "n_unknown": 0}
    neg = t.negative_variants[0]
    r_neg = em.run_bench_task(
        t.model_copy(update={"input_spec": dict(neg.input_spec)}),
        work_root=tmp_path / "b5b_neg")
    assert r_neg["ok"] and r_neg["verdict"] == "fail"
    assert r_neg["scores"]["success_rate"]["verdict"] == "pass"  # visible 过
    assert "gate_pass" not in r_neg["scores"]  # hidden 细节不出报告面
    assert r_neg["hidden_summary"]["n_fail"] == 1  # 汇总如实翻 fail
    assert all(not c["consistent"] for c in r_neg["detail"]["surface_check"]["rows"])


def test_r08_inverse_design_multi_target_wrong_anchor_negative(va_families, tmp_path):
    """多目标批：三候选按 target_id 全命中 → pass；错锚负例 judged fail。"""
    t = _tasks_by_id()["inverse-design-surface-multi-target"]
    r = em.run_bench_task(t, work_root=tmp_path / "b5c")
    assert r["verdict"] == "pass" and r["scores"]["success_rate"]["value"] == 1.0
    anchors = {row["candidate_id"]: row["target_id"]
               for row in r["detail"]["candidates"]}
    assert anchors["a_2g_l36"] == "t_2g" and anchors["b_4g_l18"] == "t_4g"
    neg = em.check_negative_variants(t, work_root=tmp_path / "b5c_neg")
    assert neg["status"] == "pass" and neg["results"][0]["judged_fail"]


def test_r08_inverse_design_envelope_ood_flag_not_flipping_verdict(
        va_families, tmp_path):
    """B3 包络：缺省域内 ood_flag=False；越界候选（eps_r=1.93<min 2.0）→
    ood_flag=True+violations 在场且 verdict 本体照常由判据聚合（该候选
    双轴命中 → verdict=pass——ood 只标记不翻判）。"""
    t = _tasks_by_id()["inverse-design-surface-halfwave"]
    r = em.run_bench_task(t, work_root=tmp_path / "b5_env")
    assert r["ood_flag"] is False
    assert r["envelope"]["status"] == "declared"
    assert sorted(r["envelope"]["checked_keys"]) == ["eps_r", "g_mm", "l_mm"]
    ood_input = {
        "targets": dict(t.input_spec["targets"]),
        "candidates": {"c_ood_hit": {
            "target_id": "t_main",
            "params": {"l_mm": 45.0, "eps_r": 1.93, "g_mm": 0.24},
            "response": {"f0_ghz": vab.surface_response(
                {"l_mm": 45.0, "eps_r": 1.93, "g_mm": 0.24})["f0_ghz"],
                "dip_db": vab.surface_response(
                {"l_mm": 45.0, "eps_r": 1.93, "g_mm": 0.24})["dip_db"]},
        }},
        "surface_check": True,
    }
    r_ood = em.run_bench_task(t.model_copy(update={"input_spec": ood_input}),
                              work_root=tmp_path / "b5_ood")
    assert r_ood["ood_flag"] is True
    assert r_ood["envelope"]["violations"][0]["key"] == "eps_r"
    assert r_ood["verdict"] == "pass"  # ood_flag 不改 verdict 本体（B3 语义）


def test_r08_inverse_design_targets_missing_tolerance_fail_closed(
        va_families, tmp_path):
    """容差缺声明=任务定义错误（#122：缺即 fail-closed 不猜）→ 执行失败。"""
    t = _tasks_by_id()["inverse-design-surface-halfwave"]
    no_tol = {"targets": {"t_main": {"f0_ghz": 2.4, "dip_db": -20.0}},
              "candidates": dict(t.input_spec["candidates"])}
    r = em.run_bench_task(t.model_copy(update={"input_spec": no_tol}),
                          work_root=tmp_path / "b5_notol")
    assert r["ok"] is False and r["stage"] == "execute"
    assert any("tol_freq_rel" in e for e in r["errors"])


# ---------------------------------------------------------------------------
# R-01 准入门接线（admit_bench_task/admit_bench_tasks）
# ---------------------------------------------------------------------------


def test_r08_admission_catalog_is_runner_measures():
    """oracle 目录=本模块 runner 对缺省输入的实测测度（非手工编造）：
    目录值与直跑 runner measures 逐键一致；覆盖全部七任务。"""
    tasks = _tasks_by_id()
    cat = vab.va_bench_admission_catalog()
    assert set(cat) == set(tasks)
    for tid, t in tasks.items():
        fn = vab.VA_BENCH_RUNNERS[t.family]
        direct = fn(t, em.BenchRunContext())
        assert cat[tid]["oracle_measures"] == direct["measures"]


def test_r08_all_seven_tasks_admitted(va_families, tmp_path):
    """七任务全过 R-01 准入门：三探针全 ok → admitted=7/quarantined=0/
    rejected=0（noop 必败门/oracle×5 稳定/反例自检）。"""
    tasks = vab.default_va_bench_tasks()
    cat = vab.va_bench_admission_catalog()
    batch = em.admit_bench_tasks(
        tasks,
        oracle_measures_by_task={tid: c["oracle_measures"]
                                 for tid, c in cat.items()},
        work_root=tmp_path / "batch",
    )
    assert batch["n_tasks"] == 7
    assert batch["n_admitted"] == 7 and batch["n_quarantined"] == 0
    assert batch["n_rejected"] == 0
    assert sorted(batch["admitted"]) == sorted(t.task_id for t in tasks)
    for rep in batch["reports"]:
        assert rep["status"] == "admitted"
        assert all(p["ok"] for p in rep["probes"].values())
        assert rep["probes"]["oracle_stability"]["n_runs"] == 5
        assert rep["probes"]["oracle_stability"]["stable"] is True


def test_r08_negative_variants_selfcheck_all_pass(va_families, tmp_path):
    """AX-1④ 反例自检（判据必须判 fail——ok∧execute∧verdict=fail 口径）：
    七任务全部 status=pass。"""
    for t in vab.default_va_bench_tasks():
        neg = em.check_negative_variants(t, work_root=tmp_path / f"neg_{t.task_id}")
        assert neg["status"] == "pass", f"{t.task_id}: {neg}"
        assert neg["n_variants"] >= 1
        assert all(r["judged_fail"] for r in neg["results"])


def test_r08_score_bench_over_seven_tasks(va_families, tmp_path):
    """得分卡消费面：七任务全 pass → n_pass=7/spec_score 均值=1.0/
    success_rate=1.0（AX-1② 报告列口径）。"""
    tasks = vab.default_va_bench_tasks()
    results = [em.run_bench_task(t, work_root=tmp_path / f"sc_{t.task_id}")
               for t in tasks]
    card = em.score_bench(results)
    assert card["n_tasks"] == 7 and card["n_pass"] == 7
    assert card["n_fail"] == 0 and card["n_unknown"] == 0
    assert card["spec_score"]["n_scored"] == 7
    assert card["spec_score"]["mean"] == pytest.approx(1.0)
    assert card["three_metrics"]["success_rate"]["value"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 注册纪律（installer 幂等/冲突拒收；不入 default_bench_tasks）
# ---------------------------------------------------------------------------


def test_r08_install_va_bench_runners_idempotent_and_conflict(monkeypatch):
    """installer：隔离注册表上首次装 5/重装 0（幂等）/同名异函数冲突拒收
    （闭集禁静默覆盖）。"""
    saved = dict(em._RUNNER_REGISTRY)
    # 冲突路径：family 已被异函数占用 → installer 拒收（闭集禁静默覆盖）
    monkeypatch.setattr(em, "_RUNNER_REGISTRY",
                        {**saved, vab.VA_FAMILY_SPEC_TO_VA: lambda t, c: {}})
    with pytest.raises(ValueError, match="静默覆盖"):
        vab.install_va_bench_runners()
    # 幂等路径：干净隔离表首次装 5/重装 0
    monkeypatch.setattr(em, "_RUNNER_REGISTRY", dict(saved))
    installed = vab.install_va_bench_runners()
    assert installed == vab.ANALOG_BENCH_FAMILIES
    assert set(vab.ANALOG_BENCH_FAMILIES) <= set(em.registered_families())
    assert vab.install_va_bench_runners() == ()  # 幂等
    # 其余既有 family 不受影响（隔离表含全部原 runner）
    assert set(em.BENCH_FAMILIES) <= set(em.registered_families())


def test_r08_va_tasks_not_in_default_bench_tasks():
    """锚钉（v0.14.0 移除笔 15→14 摘 loop-endto-end）：default_bench_tasks()
    不含本席任务（合流面决策项）且长度仍 14——本席零改 em_bench_service
    任务面。"""
    base_ids = {t.task_id for t in em.default_bench_tasks()}
    assert len(base_ids) == 14
    mine = {t.task_id for t in vab.default_va_bench_tasks()}
    assert not (base_ids & mine)
