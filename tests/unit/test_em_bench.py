"""电磁 Agent 基准骨架测试（aurora_q Q-W8-5，R10 空白地图 P1 位）。

覆盖（任务书验收口径）：
- BenchTask 声明式 schema：合法任务/未知判据名拒收/必填阈值预声明检查；
- 判据注册表：枚举闭集全覆盖/重复注册拒收/自定义注册回查；
- 七判据函数语义：极性（上界/下界/布尔）/阈值恰等边界/测度缺失 unknown
  不凑分/零分母 unknown；
- 6 任务全链执行（每任务执行+判据两钉）：syn-mline/syn-cpw（core.synthesis
  闭式回代）/wilkinson-campaign（design_chain+run_surrogate_loop 离线确定性，
  kickoff completed）——closed_loop 闭环任务面为内部档，不在公开树
  湖零真实污染）/kicad-sch-roundtrip（Q-CAD-2 证书跨域复用 + ERC 通道缺席
  如实 unknown）/vendor-search（FTS5 索引+检索命中）；
- 负例：未知 family fail-closed/runner 异常 fail/判据测度缺失 unknown/
  runner 返回形态非法 fail；
- 得分卡：混合 verdict 聚合/零案例 success_rate None/interface_failure_rate
  派生（gate_fail vs 接口类）/token_cost 恒 None 不编数；
- 零 LLM 面：模块源 AST import 扫描（llm 通道/proposer 零触碰——T-Q24
  「不用 LLM 打分」红线静态钉）。

零网络零真机（#139）：全部 runner 离线形态（fake 适配器/本地子进程/
本地 SQLite）；kicad-cli ERC 通道 monkeypatch 钉住（test_kicad_sch_gen.py
同款纪律）；湖写入只发生在 tmp work_root（monkeypatch 无需 chdir——
run_bench_task 内建 cwd 隔离）。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service import em_bench_service as em
from rfauto.service.envelope import ok_envelope, skipped_envelope

# ---------------------------------------------------------------------------
# schema 与注册表
# ---------------------------------------------------------------------------


def test_default_bench_tasks_fourteen_unique_ids():
    """首批 14 任务（Q-X55 扩容 12→15 后，v0.14.0 移除笔摘 loop-endto-end=
    闭环任务面内部档不公开树）：id 唯一、family 全覆盖、判据≥1、数据源
    口径在场。"""
    tasks = em.default_bench_tasks()
    assert len(tasks) == 14
    ids = [t.task_id for t in tasks]
    assert len(set(ids)) == 14
    assert set(ids) == {"syn-mline", "syn-cpw", "wilkinson-campaign",
                        "kicad-sch-roundtrip", "vendor-search",
                        "layered-stack-synthesis", "afs-fsv-quality",
                        "suspended-stripline-anchor",
                        "suspended-stripline-param-race", "ssl-g5-attribution",
                        "suspended-stripline-synthesis-matrix",
                        "branchline-campaign", "layered-stack-verdict",
                        "suspended-stripline-rereverify"}
    assert {t.family for t in tasks} == set(em.BENCH_FAMILIES)
    for t in tasks:
        assert len(t.criteria) >= 1
        assert t.data_source.strip()  # 数据源口径必填（provenance 审计面）


def test_default_bench_tasks_thresholds_predeclared():
    """必填阈值判据全部预声明（#122：阈值预声明——本函数即预声明锚）。"""
    for t in em.default_bench_tasks():
        for c in t.criteria:
            if c.name in em.THRESHOLD_REQUIRED:
                assert c.threshold is not None, f"{t.task_id}.{c.name} 缺预声明阈值"
    # 预声明锚值抽钉（改动=改门口径，须同笔改断言）
    by_id = {t.task_id: t for t in em.default_bench_tasks()}
    syn = {c.name: c.threshold for c in by_id["syn-mline"].criteria}
    assert syn == {"closedform_match": 0.01}
    camp = {c.name: c.threshold for c in by_id["wilkinson-campaign"].criteria}
    assert camp == {"closedform_match": 0.10, "gate_pass": -15.0}
    kicad = {c.name: c.threshold for c in by_id["kicad-sch-roundtrip"].criteria}
    assert kicad == {"certificate_pass": None, "erc_clean": 0}
    vendor = {c.name: c.threshold for c in by_id["vendor-search"].criteria}
    assert vendor == {"success_rate": 1.0}
    layered = {c.name: c.threshold for c in by_id["layered-stack-synthesis"].criteria}
    assert layered == {"closedform_match": 0.01}
    afs = {c.name: c.threshold for c in by_id["afs-fsv-quality"].criteria}
    assert afs == {"fsv_grade": 2, "success_rate": 1.0}
    # Q-X22 ssl_anchor 预声明锚：fd_convergence 阈值=内核 LADDER_RESIDUAL_MAX
    # 单源直引（禁改内核只读消费）；闭式界 0.015/HFSS 外包络 0.02（模块
    # _SSL_* 常量同源）；gate_pass 布尔免阈值。
    from rfauto.core.suspended_stripline_fd_judge import LADDER_RESIDUAL_MAX

    ssl = {c.name: c.threshold for c in by_id["suspended-stripline-anchor"].criteria}
    assert ssl == {"fd_convergence": LADDER_RESIDUAL_MAX, "gate_pass": None,
                   "closedform_match": 0.015, "three_way_consistency": 0.02}
    assert LADDER_RESIDUAL_MAX == 1e-3  # 内核预声明门数字钉（Q-X20 冻结）
    assert by_id["suspended-stripline-anchor"].input_spec["geometry"] == {
        "w_mm": 0.52, "b_mm": 0.50, "h_mm": 0.05, "eps_r": 11.9}  # G3 锚点
    assert by_id["suspended-stripline-anchor"].input_spec["hfss_implied"] == {
        "eps_eff": 1.59, "z0_ohm": 50.2}  # 外部实测锚（Q-X20 冻结常量同源）


def test_bench_task_schema_rejects_unknown_criterion():
    """判据名不在枚举闭集 → schema 拒收（ValidationError）。"""
    with pytest.raises(ValidationError, match="枚举闭集"):
        em.BenchTask(task_id="x", family="synthesis",
                     criteria=[{"name": "llm_judge", "threshold": 0.5}])


def test_bench_task_schema_rejects_extra_fields_and_empty_criteria():
    """extra=forbid 抓拼写漂移；criteria 空列表拒收。"""
    with pytest.raises(ValidationError):
        em.BenchTask(task_id="x", family="synthesis", criterias=[],
                     criteria=[{"name": "gate_pass"}])
    with pytest.raises(ValidationError):
        em.BenchTask(task_id="x", family="synthesis", criteria=[])


def test_criterion_registry_covers_enum_exactly():
    """判据注册表与枚举闭集双向一致（注册序=枚举序）。"""
    assert em.registered_criteria() == em.CRITERIA_NAMES
    for name in em.CRITERIA_NAMES:
        assert callable(em.criterion_fn(name))


def test_register_criterion_duplicate_rejected_and_roundtrip(monkeypatch):
    """重复注册拒收（闭集防覆盖）；闭集外名拒收；合法注册可回查
    （monkeypatch 换隔离注册表——注册序是判据池稳定契约，不污染真表）。"""
    with pytest.raises(ValueError, match="已注册"):
        em.register_criterion("gate_pass")(em.criterion_fn("gate_pass"))
    # 新名须先扩枚举——闭集外名拒收
    with pytest.raises(ValueError, match="枚举闭集"):
        em.register_criterion("not_in_enum")(lambda m, t: {})
    # 合法路径：隔离注册表（去重 drc_count 后重注册，monkeypatch 还原）
    saved = dict(em._CRITERION_REGISTRY)
    monkeypatch.setattr(em, "_CRITERION_REGISTRY",
                        {k: v for k, v in saved.items() if k != "drc_count"})
    em.register_criterion("drc_count")(em._criterion_drc_count)
    assert em.criterion_fn("drc_count") is em._criterion_drc_count


def test_runner_registry_covers_families():
    """runner 注册面覆盖 family 闭集（首批 5 family 全在）。"""
    assert set(em.registered_families()) == set(em.BENCH_FAMILIES)
    with pytest.raises(ValueError, match="已注册"):
        em.register_runner("synthesis")(em._run_synthesis)


# ---------------------------------------------------------------------------
# 判据函数语义（极性/边界/unknown 不凑分）
# ---------------------------------------------------------------------------


def test_criterion_closedform_match_upper_bound_and_edge():
    """上界极性：deviation ≤ threshold 判 pass（恰等含）；超阈 fail；测度非法 unknown。"""
    fn = em.criterion_fn("closedform_match")
    assert fn({"deviation": 0.009}, 0.01)["verdict"] == "pass"
    assert fn({"deviation": 0.01}, 0.01)["verdict"] == "pass"  # 恰等（≤）
    assert fn({"deviation": 0.0101}, 0.01)["verdict"] == "fail"
    assert fn({"deviation": "x"}, 0.01)["verdict"] == "unknown"
    assert fn({}, 0.01)["verdict"] == "unknown"
    assert fn({"deviation": True}, 0.01)["verdict"] == "unknown"  # 拒 bool（#364）


def test_criterion_gate_pass_boolean_semantics():
    """布尔极性：只认 passed；metric 在场记 value，缺省记 1.0/0.0。"""
    fn = em.criterion_fn("gate_pass")
    r = fn({"passed": True, "gate": "g", "metric": -18.4}, None)
    assert (r["value"], r["verdict"]) == (-18.4, "pass")
    r = fn({"passed": False, "gate": "g"}, None)
    assert (r["value"], r["verdict"]) == (0.0, "fail")
    assert fn({"passed": "yes"}, None)["verdict"] == "unknown"


def test_criterion_certificate_pass_semantics():
    """round-trip 证书：passed → 1.0/pass；n_diff 进 note（Q-CAD-2 复用形态）。"""
    fn = em.criterion_fn("certificate_pass")
    r = fn({"passed": True, "n_diff": 0}, None)
    assert (r["value"], r["verdict"]) == (1.0, "pass")
    assert r["note"] == "n_diff=0"
    assert fn({"passed": False, "n_diff": 2}, None)["verdict"] == "fail"
    assert fn({}, None)["verdict"] == "unknown"


def test_criterion_erc_clean_unknown_when_unavailable():
    """ERC 通道缺席 → unknown（如实不凑分）；计数恰等阈值判 pass。"""
    fn = em.criterion_fn("erc_clean")
    r = fn({"available": False, "reason": "kicad-cli 未找到"}, 0)
    assert r["verdict"] == "unknown"
    assert "kicad-cli" in r["note"]
    assert fn({"available": True, "error_count": 0}, 0)["verdict"] == "pass"
    assert fn({"available": True, "error_count": 1}, 0)["verdict"] == "fail"
    assert fn({"available": True, "error_count": 0}, None)["verdict"] == "unknown"


def test_criterion_drc_count_semantics():
    """DRC 计数（预留判据）：同 ERC 形态——available/count/上界极性。"""
    fn = em.criterion_fn("drc_count")
    assert fn({"available": True, "count": 3}, 5)["verdict"] == "pass"
    assert fn({"available": True, "count": 6}, 5)["verdict"] == "fail"
    assert fn({"available": False}, 5)["verdict"] == "unknown"


def test_criterion_success_rate_lower_bound_and_zero_denominator():
    """下界极性：rate ≥ threshold 判 pass（恰等含）；分母 0 → unknown。"""
    fn = em.criterion_fn("success_rate")
    r = fn({"n_ok": 3, "n_total": 3}, 1.0)
    assert (r["value"], r["verdict"]) == (1.0, "pass")
    assert fn({"n_ok": 2, "n_total": 3}, 1.0)["verdict"] == "fail"
    assert fn({"n_ok": 1, "n_total": 2}, 0.5)["verdict"] == "pass"  # 恰等（≥）
    assert fn({"n_ok": 0, "n_total": 0}, 1.0)["verdict"] == "unknown"
    assert fn({"n_ok": -1, "n_total": 3}, 1.0)["verdict"] == "unknown"


def test_criterion_token_cost_unknown_without_ledger():
    """Token 成本：无计费账本 → unknown（不编数）；有账本走上界极性。"""
    fn = em.criterion_fn("token_cost")
    r = fn({"available": False, "cost": None, "reason": "无计费账本"}, 1.0)
    assert r["verdict"] == "unknown"
    assert fn({"available": True, "cost": 0.2}, 1.0)["verdict"] == "pass"
    assert fn({"available": True, "cost": 2.0}, 1.0)["verdict"] == "fail"


def test_criterion_fsv_grade_semantics():
    """FSV GDM 等级判据（Q-X15）：上界极性 grade_level ≤ threshold（恰等含）；
    grade 名进 note；测度缺失/非法/bool/threshold 缺 → unknown 不凑分。"""
    fn = em.criterion_fn("fsv_grade")
    r = fn({"grade_level": 1, "grade": "VG"}, 2)
    assert (r["value"], r["verdict"]) == (1.0, "pass") and r["note"] == "VG"
    assert fn({"grade_level": 2, "grade": "Ex"}, 2)["verdict"] == "pass"  # 恰等（≤）
    r3 = fn({"grade_level": 3, "grade": "GoOD"}, 2)
    assert r3["verdict"] == "fail" and r3["value"] == 3.0
    assert fn({"grade_level": 2}, 2)["note"] is None  # grade 缺省 note=None
    assert fn({}, 2)["verdict"] == "unknown"
    assert fn({"grade_level": "2"}, 2)["verdict"] == "unknown"
    assert fn({"grade_level": True}, 2)["verdict"] == "unknown"  # bool 拒收（#364）
    assert fn({"grade_level": 2}, None)["verdict"] == "unknown"  # 阈值未声明
    # 枚举闭集尾部追加钉：注册序=枚举序（Q-X15 期 fsv_grade 收尾；Q-X22 尾部
    # 追加 fd_convergence/three_way_consistency——词表同步迁移钉）
    assert em.registered_criteria()[-3] == "fsv_grade"
    assert "fsv_grade" in em.THRESHOLD_REQUIRED


def test_criterion_fd_convergence_semantics():
    """FD 收敛残差判据（Q-X22）：上界极性 residual_max ≤ threshold（恰等含）；
    超阈 fail；测度缺失/非法/bool/threshold 缺 → unknown 不凑分；status 进
    note 供审计（不进主判——全量门判读走 gate_pass）。"""
    fn = em.criterion_fn("fd_convergence")
    r = fn({"residual_max": 9.9e-4, "status": "CONVERGED"}, 1e-3)
    assert (r["value"], r["verdict"]) == (9.9e-4, "pass") and r["note"] == "CONVERGED"
    assert fn({"residual_max": 1e-3}, 1e-3)["verdict"] == "pass"  # 恰等（≤）
    r2 = fn({"residual_max": 1.1e-3, "status": "CONVERGED"}, 1e-3)
    assert r2["verdict"] == "fail" and r2["value"] == 1.1e-3
    assert fn({"residual_max": 5e-4}, 1e-3)["note"] is None  # status 缺省 note=None
    assert fn({}, 1e-3)["verdict"] == "unknown"
    assert fn({"residual_max": "x"}, 1e-3)["verdict"] == "unknown"
    assert fn({"residual_max": True}, 1e-3)["verdict"] == "unknown"  # bool 拒（#364）
    assert fn({"residual_max": 5e-4}, None)["verdict"] == "unknown"  # 阈值未声明


def test_criterion_three_way_consistency_semantics():
    """三方一致性判据（Q-X22）：双界（闭式 1.5%/HFSS 2%）+外包络 threshold
    三重校验；value=最坏偏差（带宽读数）；带符号对进 note；任一界破即 fail；
    测度缺失/阈值缺 → unknown 不凑分。"""
    fn = em.criterion_fn("three_way_consistency")
    ok = {"fd_vs_closed": 0.0114, "fd_vs_hfss": 0.0029,
          "bound_closed": 0.015, "bound_hfss": 0.02}
    r = fn(ok, 0.02)
    assert r["verdict"] == "pass" and r["value"] == 0.0114  # 最坏=闭式腿
    assert "fd_vs_closed=+0.011400" in r["note"] and "fd_vs_hfss=+0.002900" in r["note"]
    # 负偏差同判（带符号入、绝对值比）
    r_neg = fn({**ok, "fd_vs_closed": -0.0149, "fd_vs_hfss": -0.019}, 0.02)
    assert r_neg["verdict"] == "pass" and r_neg["value"] == 0.019  # 最坏=HFSS 腿
    # 闭式腿破界（1.5%）→ fail（HFSS 腿即便达标也救不回）
    assert fn({**ok, "fd_vs_closed": 0.0151}, 0.02)["verdict"] == "fail"
    # HFSS 腿破界（2%）→ fail
    assert fn({**ok, "fd_vs_hfss": 0.0201}, 0.02)["verdict"] == "fail"
    # 外包络 threshold 破（界内但超任务声明外包络）→ fail
    assert fn(ok, 0.011)["verdict"] == "fail"
    # 恰等边界（≤ 双界+外包络）→ pass
    edge = {"fd_vs_closed": 0.015, "fd_vs_hfss": 0.02,
            "bound_closed": 0.015, "bound_hfss": 0.02}
    assert fn(edge, 0.02)["verdict"] == "pass"
    # 测度缺失逐键 unknown；bool 拒（#364）；阈值未声明 unknown
    for drop in ("fd_vs_closed", "fd_vs_hfss", "bound_closed", "bound_hfss"):
        bad = {k: v for k, v in ok.items() if k != drop}
        r_missing = fn(bad, 0.02)
        assert r_missing["verdict"] == "unknown" and drop in r_missing["note"]
    assert fn({**ok, "fd_vs_closed": True}, 0.02)["verdict"] == "unknown"
    assert fn(ok, None)["verdict"] == "unknown"


def test_ssl_anchor_criteria_and_family_registry_pins():
    """Q-X22 词表钉：两新判据枚举尾部序/THRESHOLD_REQUIRED 成员/ssl_anchor
    family 闭集尾部/runner 注册面/新任务判据名集——闭集防漂移。"""
    assert em.registered_criteria()[-2:] == ("fd_convergence",
                                             "three_way_consistency")
    for name in ("fd_convergence", "three_way_consistency"):
        assert name in em.CRITERIA_NAMES and name in em.THRESHOLD_REQUIRED
        assert callable(em.criterion_fn(name))
    assert em.BENCH_FAMILIES[-6] == "ssl_anchor"
    # Q-X43/Q-X55 词表同步迁移钉：anchor 覆盖面三 family + Q-X55 两新 family
    # 尾部追加（闭集纪律）。
    assert em.BENCH_FAMILIES[-5:-2] == ("ssl_race", "ssl_g5", "ssl_matrix")
    assert em.BENCH_FAMILIES[-2:] == ("layered_verdict", "ssl_rereverify")
    assert "ssl_anchor" in em.registered_families()
    task = {t.task_id: t for t in em.default_bench_tasks()}[
        "suspended-stripline-anchor"]
    assert task.family == "ssl_anchor"
    assert [c.name for c in task.criteria] == [
        "fd_convergence", "gate_pass", "closedform_match",
        "three_way_consistency"]
    assert "suspended_stripline_fd_judge" in task.data_source  # 溯源锚在场


# ---------------------------------------------------------------------------
# 任务执行：6 任务全链（执行 + 判据两钉）
# ---------------------------------------------------------------------------


def _tasks_by_id() -> dict[str, em.BenchTask]:
    return {t.task_id: t for t in em.default_bench_tasks()}


def test_run_syn_mline_task_pass_with_evidence(tmp_path):
    """syn-mline：闭式回代判据 pass + 证据 JSON 落盘。"""
    task = _tasks_by_id()["syn-mline"]
    ev = tmp_path / "ev"
    r = em.run_bench_task(task, evidence_dir=ev, work_root=tmp_path / "work")
    assert r["ok"] is True and r["verdict"] == "pass"
    assert r["stage"] == "execute" and r["errors"] == []
    score = r["scores"]["closedform_match"]
    assert score["verdict"] == "pass" and score["value"] <= 0.01
    assert score["threshold"] == 0.01
    assert r["detail"]["model"] == "mline" and r["detail"]["params"]["w_mm"] > 0
    assert r["evidence_path"] is not None and Path(r["evidence_path"]).is_file()
    loaded = json.loads(Path(r["evidence_path"]).read_text(encoding="utf-8"))
    assert loaded["verdict"] == "pass" and loaded["task_id"] == "syn-mline"


def test_run_syn_cpw_task_pass(tmp_path):
    """syn-cpw：CPWG 口径回代判据 pass（#193 参照系）。"""
    r = em.run_bench_task(_tasks_by_id()["syn-cpw"], work_root=tmp_path / "w")
    assert r["verdict"] == "pass"
    assert r["scores"]["closedform_match"]["value"] <= 0.01
    assert r["detail"]["model"] == "cpw"


def test_run_wilkinson_campaign_task_pass(tmp_path):
    """wilkinson-campaign：design_chain+寻优发起（kickoff completed）+ 双判据。"""
    r = em.run_bench_task(_tasks_by_id()["wilkinson-campaign"], work_root=tmp_path / "w")
    assert r["ok"] is True and r["verdict"] == "pass"
    assert r["detail"]["kickoff_status"] == "completed"  # 战役真实完成出最优点
    assert r["scores"]["closedform_match"]["verdict"] == "pass"
    assert r["scores"]["closedform_match"]["value"] <= 0.10  # 3dB 等分闭式锚
    gate = r["scores"]["gate_pass"]
    assert gate["verdict"] == "pass" and gate["value"] <= -15.0  # s11 质量杆
    assert r["detail"]["family"] == "wilkinson"
    assert r["detail"]["synthesis_params"]["f0_ghz"] == 2.4


def test_run_kicad_roundtrip_certificate_pass(tmp_path, monkeypatch):
    """kicad-sch-roundtrip：证书判据 pass（Q-CAD-2 通用件跨域复用）；
    ERC ok 信封 → erc_clean pass（通道 monkeypatch 钉，零真机）。"""
    monkeypatch.setattr(
        "rfauto.service.kicad_sch_service.run_erc",
        lambda sch_path, **kw: ok_envelope(exit_code=0, error_count=0,
                                           warning_count=0, report_path=None),
    )
    r = em.run_bench_task(_tasks_by_id()["kicad-sch-roundtrip"],
                          work_root=tmp_path / "w")
    assert r["verdict"] == "pass"
    cert = r["scores"]["certificate_pass"]
    assert cert["verdict"] == "pass" and cert["value"] == 1.0
    assert r["detail"]["certificate_pass"] is True and r["detail"]["n_diff"] == 0
    assert r["detail"]["n_nets"] == 3 and r["detail"]["n_components"] == 2
    assert r["scores"]["erc_clean"]["verdict"] == "pass"
    assert Path(r["detail"]["out_path"]).is_file()  # .kicad_sch 产物在 work_root


def test_run_kicad_erc_unavailable_verdict_unknown(tmp_path, monkeypatch):
    """ERC 通道缺席（kicad-cli 未装 skipped 信封）→ erc_clean unknown →
    任务 verdict=unknown（显式不凑分——判据缺失不是通过也不是失败）。"""
    monkeypatch.setattr(
        "rfauto.service.kicad_sch_service.run_erc",
        lambda sch_path, **kw: skipped_envelope("kicad-cli 未找到（设 RFAUTO_KICAD_CLI 或安装 KiCad）"),
    )
    r = em.run_bench_task(_tasks_by_id()["kicad-sch-roundtrip"],
                          work_root=tmp_path / "w")
    assert r["ok"] is True
    assert r["scores"]["certificate_pass"]["verdict"] == "pass"  # 证书独立达标
    assert r["scores"]["erc_clean"]["verdict"] == "unknown"
    assert r["verdict"] == "unknown"  # 聚合语义：含 unknown 无 fail → unknown


def test_run_vendor_search_task_pass(tmp_path):
    """vendor-search：FTS5 索引+检索 3/3 命中（trigram+LIKE 双通道）→ success_rate pass。"""
    r = em.run_bench_task(_tasks_by_id()["vendor-search"], work_root=tmp_path / "w")
    assert r["verdict"] == "pass"
    sr = r["scores"]["success_rate"]
    assert sr["value"] == 1.0 and sr["verdict"] == "pass" and sr["threshold"] == 1.0
    modes = {q["mode"] for q in r["detail"]["queries"]}
    assert modes <= {"fts5", "fts5_phrase", "like"}  # 通道词表内
    assert r["detail"]["indexed_files"] == 2  # 内联语料两文件


def test_run_layered_stack_synthesis_task_pass(tmp_path):
    """layered-stack-synthesis（Q-X15 新任务）：layered_stack_spec.design_params
    Z0 目标→strip 宽反解全链 → closedform_match pass；反解自洽细节在档
    （独立裁判残差/εeff/HFSS 实测锚），锚出处（晶圆键合反馈 §2.1）进 data_source。"""
    task = _tasks_by_id()["layered-stack-synthesis"]
    r = em.run_bench_task(task, work_root=tmp_path / "w")
    assert r["ok"] is True and r["verdict"] == "pass" and r["errors"] == []
    assert r["detail"]["kind"] == "layered_stack"
    assert r["detail"]["model"] == "layered_stack"
    assert r["detail"]["z0_target"] == 50.0
    assert r["detail"]["params"]["strip_w_mm"] > 0
    score = r["scores"]["closedform_match"]
    assert score["verdict"] == "pass" and score["value"] <= 0.01
    assert score["threshold"] == 0.01
    # design_params 内建独立裁判（#118 家法）：反解残差 ≤ 1e-9Ω
    assert r["detail"]["z0_residual_ohm"] <= 1e-9
    assert r["detail"]["eps_eff"] > 1.0
    assert r["detail"]["anchor_hfss"]["hfss_measured_z0_ohm"] == 50.2  # §2.1 实测锚
    assert "design_params" in task.data_source  # 溯源锚在场
    # 反解的 strip 宽与反馈锚 0.52mm 同量级（50Ω 点经验对照，非严格裁判）
    assert 0.3 < r["detail"]["params"]["strip_w_mm"] < 0.8


def test_syn_runner_layered_stack_missing_z0_fails_closed(tmp_path):
    """layered_stack kind 缺 z0_ohm（或非正有限）→ RuntimeError → verdict=fail
    （不猜默认值——fail-closed）。"""
    for bad_params in ({}, {"z0_ohm": -5.0}, {"z0_ohm": "50"},
                       {"z0_ohm": True}):
        r = em.run_bench_task(
            {"task_id": "bad-ls", "family": "synthesis",
             "input_spec": {"kind": "layered_stack", "params": bad_params},
             "criteria": [{"name": "closedform_match", "threshold": 0.01}]},
            work_root=tmp_path)
        assert r["verdict"] == "fail" and r["stage"] == "execute"
        assert "z0_ohm" in r["errors"][0]


def test_run_afs_fsv_quality_task_pass(tmp_path):
    """afs-fsv-quality（Q-X15 新任务）：afs_service 真函数链
    synthetic_multiresonance_response×afs_sweep → fsv_grade + success_rate
    双判据 pass；阈值锚（fsv_grade=2 numpy 2.5.4 口径/缩减 ≥ REDUCTION_RATIO_MIN）
    在档，内核计费（n_solves/n_full）随行。"""
    task = _tasks_by_id()["afs-fsv-quality"]
    r = em.run_bench_task(task, work_root=tmp_path / "w")
    assert r["ok"] is True and r["verdict"] == "pass" and r["errors"] == []
    grade = r["scores"]["fsv_grade"]
    assert grade["verdict"] == "pass" and grade["value"] <= 2
    assert grade["threshold"] == 2 and grade["note"]  # GDM 等级名进 note
    sr = r["scores"]["success_rate"]
    assert sr["verdict"] == "pass" and sr["value"] == 1.0 and sr["threshold"] == 1.0
    # 内核真账：缩减比 ≥ REDUCTION_RATIO_MIN(0.5)，solve 数相对密集参考非平凡
    assert r["detail"]["reduction_ratio"] >= 0.5
    assert r["detail"]["reduction_ratio_min"] == 0.5
    assert r["detail"]["n_solves"] * 2 <= r["detail"]["n_full"]
    assert r["detail"]["spec"]["resonances"][0]["f0_ghz"] == 2.4  # 合成规格回显
    assert r["detail"]["acceptance"]["passed"] is True  # afs_service 验收门同判


def test_afs_runner_bad_spec_fails_closed(tmp_path):
    """afs runner 非法谐振规格 → ValueError → verdict=fail stage=execute（不猜）。"""
    r = em.run_bench_task(
        {"task_id": "bad-afs", "family": "afs_sweep",
         "input_spec": {"spec": "no_resonance_here", "band_ghz": [1.0, 4.0]},
         "criteria": [{"name": "fsv_grade", "threshold": 2},
                      {"name": "success_rate", "threshold": 1.0}]},
        work_root=tmp_path)
    assert r["verdict"] == "fail" and r["stage"] == "execute"
    assert "synthetic" in r["errors"][0] or "谐振" in r["errors"][0]


# ---------------------------------------------------------------------------
# suspended-stripline-anchor（Q-X22：Q-X20 FD 静流第三方裁判接入 bench；
# 跨引擎三方判据 FD+闭式+HFSS implied，资格锚全量）
# ---------------------------------------------------------------------------

#: G3 点本席实测数字带（runs/aurora_q/qx20_fd_judge/judge_result.json；
#: FD εeff/Z0 带宽 ±0.05% 级——静流纯数值内核跨环境漂移远低于此）。
_SSL_FD_EPS_ANCHOR = 1.5853718
_SSL_FD_Z0_ANCHOR = 50.4823194


@pytest.fixture(scope="module")
def ssl_result(tmp_path_factory):
    """G3 全链一次真跑（module 级共享——FD 阶梯 ~2s 确定性，多钉复用）。"""
    task = _tasks_by_id()["suspended-stripline-anchor"]
    return em.run_bench_task(task, work_root=tmp_path_factory.mktemp("ssl_w"))


def test_run_ssl_anchor_task_full_chain_pass(ssl_result):
    """suspended-stripline-anchor 全链：FD 阶梯 CONVERGED+资格锚全过+三方
    一致 → 四判据全 pass，任务 verdict=pass。"""
    r = ssl_result
    assert r["ok"] is True and r["verdict"] == "pass" and r["errors"] == []
    assert r["stage"] == "execute"
    fd = r["scores"]["fd_convergence"]
    assert fd["verdict"] == "pass" and fd["threshold"] == 1e-3
    assert fd["value"] < 1e-3 and fd["note"] == "CONVERGED"
    gate = r["scores"]["gate_pass"]
    assert gate["verdict"] == "pass" and gate["value"] == 1.0
    assert gate["threshold"] is None  # 布尔判据免阈值
    cf = r["scores"]["closedform_match"]
    assert cf["verdict"] == "pass" and cf["threshold"] == 0.015
    assert cf["value"] <= 0.015
    tw = r["scores"]["three_way_consistency"]
    assert tw["verdict"] == "pass" and tw["threshold"] == 0.02
    assert tw["value"] <= 0.02 and "fd_vs_closed=" in tw["note"]  # 带宽 note 在档
    assert r["detail"]["geometry"] == {"w_mm": 0.52, "b_mm": 0.50,
                                       "h_mm": 0.05, "eps_r": 11.9}
    assert r["detail"]["fd_converged"]["status"] == "CONVERGED"


def test_ssl_anchor_g3_numbers_match_qx20_judge_result(ssl_result):
    """G3 数字钉（对 runs/aurora_q/qx20_fd_judge/judge_result.json 本席实测，
    带宽容数值环境漂移）：FD 收敛真值 εeff/Z0+三方带符号偏差——跨引擎三方
    判据消费的是同一 FD 真值。"""
    d = ssl_result["detail"]
    assert d["fd_converged"]["eps_eff"] == pytest.approx(_SSL_FD_EPS_ANCHOR, abs=5e-4)
    assert d["fd_converged"]["z0_ohm"] == pytest.approx(_SSL_FD_Z0_ANCHOR, abs=0.05)
    # 闭式腿现场重算=Q-X20 three_way.closed_form（被裁判对象同源）
    assert d["closed_form"]["eps_eff"] == pytest.approx(1.6034176, abs=5e-4)
    assert d["closed_form"]["z0_ohm"] == pytest.approx(50.2512809, abs=0.05)
    # 带符号偏差=judge_result.bias_rel 同口径（FD 为基准）
    assert d["fd_vs_closed_signed"] == pytest.approx(0.011383, abs=1.5e-3)
    assert d["fd_vs_hfss_signed"] == pytest.approx(0.002919, abs=5e-4)
    assert d["hfss_implied"] == {"eps_eff": 1.59, "z0_ohm": 50.2}
    assert d["bounds"]["residual_gate_source"].endswith("LADDER_RESIDUAL_MAX")
    assert d["bounds"]["closed"] == 0.015 and d["bounds"]["hfss"] == 0.02


def test_ssl_anchor_detail_records_qualification_anchors(ssl_result):
    """资格锚全量随行（#300 裁判先过已知基准）：Cohn 空气带状线/构造恒等/
    独立网格族交叉对拍三锚+门旗位+预声明容差常数审计面。"""
    r = ssl_result
    anchors = r["detail"]["anchors"]
    assert anchors["cohn_air_z0"]["converged"] is True
    assert abs(anchors["cohn_air_z0"]["rel"]) <= 5e-3
    lim = anchors["exact_limits"]
    assert lim["full_fill_err"] == 0.0 and lim["air_identity_err"] == 0.0
    assert lim["thin_lt_thicker"] is True
    cross = anchors["referee_cross_check"]
    assert cross is not None and abs(cross["rel_vs_self"]) <= 2e-3
    assert r["detail"]["gate_flags"] == {"cohn_ok": True, "exact_ok": True,
                                         "cross_ok": True, "fd_converged": True}
    tol = r["detail"]["anchor_tolerance"]
    assert tol == {"cohn_rel_max": 5e-3, "cross_check_rel_max": 2e-3,
                   "exact_identity_tol": 1e-12}


def test_ssl_anchor_runner_missing_geometry_fails_closed(tmp_path):
    """geometry 缺键/非法（None/负值/bool）→ RuntimeError → verdict=fail
    stage=execute（不猜缺省几何——fail-closed）。"""
    for bad_geo in ({}, {"b_mm": 0.5, "h_mm": 0.05, "eps_r": 11.9},
                    {"w_mm": None, "b_mm": 0.5, "h_mm": 0.05, "eps_r": 11.9},
                    {"w_mm": -0.52, "b_mm": 0.5, "h_mm": 0.05, "eps_r": 11.9},
                    {"w_mm": True, "b_mm": 0.5, "h_mm": 0.05, "eps_r": 11.9}):
        r = em.run_bench_task(
            {"task_id": "bad-geo", "family": "ssl_anchor",
             "input_spec": {"geometry": bad_geo,
                            "hfss_implied": {"eps_eff": 1.59, "z0_ohm": 50.2}},
             "criteria": [{"name": "fd_convergence", "threshold": 1e-3},
                          {"name": "gate_pass"},
                          {"name": "closedform_match", "threshold": 0.015},
                          {"name": "three_way_consistency", "threshold": 0.02}]},
            work_root=tmp_path)
        assert r["verdict"] == "fail" and r["stage"] == "execute", bad_geo
        assert "geometry" in r["errors"][0]


def test_ssl_anchor_runner_eps_r_below_one_fails_closed(tmp_path):
    """εr<1 越闭式定义域 → fail-closed（εr≥1.0 显式拦截，错误口径可判读）。"""
    r = em.run_bench_task(
        {"task_id": "bad-epsr", "family": "ssl_anchor",
         "input_spec": {"geometry": {"w_mm": 0.52, "b_mm": 0.5, "h_mm": 0.05,
                                     "eps_r": 0.5},
                        "hfss_implied": {"eps_eff": 1.59, "z0_ohm": 50.2}},
         "criteria": [{"name": "fd_convergence", "threshold": 1e-3},
                      {"name": "gate_pass"},
                      {"name": "closedform_match", "threshold": 0.015},
                      {"name": "three_way_consistency", "threshold": 0.02}]},
        work_root=tmp_path)
    assert r["verdict"] == "fail" and r["stage"] == "execute"
    assert "eps_r" in r["errors"][0]


def test_ssl_anchor_runner_bad_hfss_implied_fails_closed(tmp_path):
    """hfss_implied 缺失/非法（None/非正/bool）→ fail-closed（外部实测锚=
    声明数据源，缺席不可判读不猜——铁律 7 同族）。"""
    good_geo = {"w_mm": 0.52, "b_mm": 0.5, "h_mm": 0.05, "eps_r": 11.9}
    for bad_hf in ({}, {"eps_eff": 1.59}, {"eps_eff": None, "z0_ohm": 50.2},
                   {"eps_eff": -1.59, "z0_ohm": 50.2},
                   {"eps_eff": 1.59, "z0_ohm": True}):
        r = em.run_bench_task(
            {"task_id": "bad-hf", "family": "ssl_anchor",
             "input_spec": {"geometry": good_geo, "hfss_implied": bad_hf},
             "criteria": [{"name": "fd_convergence", "threshold": 1e-3},
                          {"name": "gate_pass"},
                          {"name": "closedform_match", "threshold": 0.015},
                          {"name": "three_way_consistency", "threshold": 0.02}]},
            work_root=tmp_path)
        assert r["verdict"] == "fail" and r["stage"] == "execute", bad_hf
        assert "hfss_implied" in r["errors"][0]


def test_ssl_anchor_fd_incomplete_gate_fail(tmp_path, monkeypatch):
    """FD 阶梯 INCOMPLETE（注入非收敛 LadderResult：残差与三方读数均达标、
    唯 8 门状态不全）→ gate_pass fail → verdict=fail；其余三判据独立达标
    （状态门与残差门分离不连坐；聚合语义任一 fail 即任务 fail，#122 不凑）。"""
    from rfauto.core import suspended_stripline_fd_judge as fdj

    def _incomplete(**kw):
        del kw
        return fdj.LadderResult(
            status="INCOMPLETE", eps_eff=1.59, z0_ohm=50.2,
            c_air_f_per_m=5.2e-11, c_diel_f_per_m=8.2e-11,
            d0_levels_mm=[0.1, 0.05, 0.025, 0.0125],
            eps_levels=[1.6, 1.55, 1.6, 1.55],
            c_air_levels_eps0=[6.0, 5.9, 6.0, 5.9],
            p_eps=1.0, p_cair=1.0,
            residual_eps_fine=1e-4, residual_eps_agree=1e-4,
            residual_cair_fine=1e-4, residual_cair_agree=1e-4,
            gates={"monotone_eps_last3": False})

    monkeypatch.setattr("rfauto.core.suspended_stripline_fd_judge.judge_ladder",
                        _incomplete)
    r = em.run_bench_task(_tasks_by_id()["suspended-stripline-anchor"],
                          work_root=tmp_path)
    assert r["ok"] is True and r["verdict"] == "fail"
    assert r["scores"]["fd_convergence"]["verdict"] == "pass"  # 残差独立达标
    assert r["scores"]["fd_convergence"]["note"] == "INCOMPLETE"
    assert r["scores"]["closedform_match"]["verdict"] == "pass"  # 三方腿不连坐
    assert r["scores"]["three_way_consistency"]["verdict"] == "pass"
    gate = r["scores"]["gate_pass"]
    assert gate["verdict"] == "fail" and gate["value"] == 0.0
    assert r["detail"]["anchors"]["referee_cross_check"] is None  # INCOMPLETE 免交叉
    assert r["detail"]["gate_flags"]["fd_converged"] is False
    assert r["detail"]["gate_flags"]["cross_ok"] is False


def test_ssl_anchor_three_way_closed_bound_negative(tmp_path, monkeypatch):
    """闭式腿漂移注入（×1.05）→ closedform_match 与 three_way 闭式界双双
    fail（跨引擎三方判据的闭式腿负例——判据管线真实把关，非恒过摆设）。"""
    from rfauto.core.calculators import _suspended_stripline_ri

    eps_cf, z0_cf = _suspended_stripline_ri(0.52, 0.50, 0.05, 11.9)
    monkeypatch.setattr("rfauto.core.calculators._suspended_stripline_ri",
                        lambda w, b, h, e: (eps_cf * 1.05, z0_cf))
    r = em.run_bench_task(_tasks_by_id()["suspended-stripline-anchor"],
                          work_root=tmp_path)
    assert r["ok"] is True and r["verdict"] == "fail"
    assert r["scores"]["closedform_match"]["verdict"] == "fail"
    assert r["scores"]["closedform_match"]["value"] > 0.015
    tw = r["scores"]["three_way_consistency"]
    assert tw["verdict"] == "fail"
    assert "fd_vs_closed=" in tw["note"] and "fd_vs_hfss=" in tw["note"]
    gate = r["scores"]["gate_pass"]
    assert gate["verdict"] == "pass"  # FD 侧门不受闭式腿漂移连坐


def test_ssl_anchor_three_way_hfss_bound_negative(tmp_path):
    """HFSS implied 锚声明坏读数（1.8）→ three_way HFSS 界（2%）fail →
    verdict=fail；closedform_match 独立达标（三方判据逐腿独立评定）。"""
    task = _tasks_by_id()["suspended-stripline-anchor"].model_copy(deep=True)
    task.input_spec["hfss_implied"] = {"eps_eff": 1.8, "z0_ohm": 50.2}
    r = em.run_bench_task(task, work_root=tmp_path)
    assert r["ok"] is True and r["verdict"] == "fail"
    assert r["scores"]["three_way_consistency"]["verdict"] == "fail"
    assert r["scores"]["three_way_consistency"]["value"] > 0.02
    assert r["scores"]["closedform_match"]["verdict"] == "pass"
    assert r["detail"]["fd_vs_hfss_signed"] == pytest.approx(1.8 / _SSL_FD_EPS_ANCHOR - 1.0,
                                                             abs=1e-3)


def test_ssl_anchor_evidence_json_roundtrip(tmp_path):
    """证据落盘（evidence_dir 显式给定）：JSON 往返同构、verdict/task_id 在档。"""
    ev = tmp_path / "ev"
    r = em.run_bench_task(_tasks_by_id()["suspended-stripline-anchor"],
                          evidence_dir=ev, work_root=tmp_path / "work")
    assert r["evidence_path"] is not None and Path(r["evidence_path"]).is_file()
    loaded = json.loads(Path(r["evidence_path"]).read_text(encoding="utf-8"))
    assert loaded["verdict"] == "pass"
    assert loaded["task_id"] == "suspended-stripline-anchor"
    assert loaded["family"] == "ssl_anchor"
    assert loaded["detail"]["fd_converged"]["status"] == "CONVERGED"


# ---------------------------------------------------------------------------
# anchor 覆盖面扩容三任务（Q-X43：param_race 变体批量 / G5 归因数据基准 /
# 综合变体矩阵；fd_convergence 阈值同 Q-X22 单源直引，批量判据=最坏聚合）
# ---------------------------------------------------------------------------

#: Q-X43 本席实测数字带（runs/aurora_q/qx43_stats/probe_numbers.json 探针
#: 标定；FD 静流纯数值内核跨环境漂移远低于带宽——Q-X22 ssl_result 锚同款
#: 纪律，approx 容差只吸收浮点环境差，不吸收内核漂移）。
_QX43_RACE_RES_WORST = 5.4928e-4          # 最坏=w_mm-20pct
_QX43_RACE_DEV_WORST = 0.013750           # 最坏=w_mm+20pct
_QX43_MATRIX_RES_WORST = 4.0659e-4        # 最坏=b0p45_h0p055_e10p71
_QX43_MATRIX_DEV_CLOSED_WORST = 0.012879  # 最坏=b0p55_h0p045_e13p09
_QX43_MATRIX_DEV_TARGET_WORST = 0.005306  # 同点（带符号 −0.005306）


@pytest.fixture(scope="module")
def qx43_race_result(tmp_path_factory):
    """param_race 批量全链两次真跑（module 级共享——16 变体×judge_ladder
    ~16s/次；确定性钉=两次运行结果逐字段同构）。"""
    task = _tasks_by_id()["suspended-stripline-param-race"]
    r1 = em.run_bench_task(task, work_root=tmp_path_factory.mktemp("race_w1"))
    r2 = em.run_bench_task(task, work_root=tmp_path_factory.mktemp("race_w2"))
    return r1, r2


@pytest.fixture(scope="module")
def qx43_matrix_result(tmp_path_factory):
    """综合矩阵全链一次真跑（module 级共享——8 组×judge_ladder ~8s）。"""
    task = _tasks_by_id()["suspended-stripline-synthesis-matrix"]
    return em.run_bench_task(task,
                             work_root=tmp_path_factory.mktemp("matrix_w"))


def test_qx43_new_tasks_thresholds_and_spec_pins():
    """三新任务预声明锚（#122：本函数即预声明锚，改动=改门口径须同笔）：
    判据阈值/G5 as-recorded 数据/枚举表常量/门常量全部在档。"""
    by_id = _tasks_by_id()
    race = {c.name: c.threshold
            for c in by_id["suspended-stripline-param-race"].criteria}
    from rfauto.core.suspended_stripline_fd_judge import LADDER_RESIDUAL_MAX

    assert race == {"fd_convergence": LADDER_RESIDUAL_MAX,
                    "closedform_match": 0.015}
    assert by_id["suspended-stripline-param-race"].input_spec[
        "geometry_center"] == {"w_mm": 0.52, "b_mm": 0.50, "h_mm": 0.05,
                               "eps_r": 11.9}  # G3 中心（Q-X20 冻结锚）
    g5 = {c.name: c.threshold for c in by_id["ssl-g5-attribution"].criteria}
    assert g5 == {"gate_pass": None, "closedform_match": 0.05}
    stats = by_id["ssl-g5-attribution"].input_spec["g5_stats"]
    assert stats["over_unity_count"] == 306          # Q-RM-4 as-recorded
    assert stats["passivity_max"] == 1.0142          # Q-X19 修复后实测门内
    assert stats["variant_split"] == {"shield": 98, "open": 208}  # Q-X25 谱复算
    mat = {c.name: c.threshold
           for c in by_id["suspended-stripline-synthesis-matrix"].criteria}
    assert mat == {"fd_convergence": LADDER_RESIDUAL_MAX,
                   "closedform_match": 0.015, "three_way_consistency": 0.02}
    assert by_id["suspended-stripline-synthesis-matrix"].input_spec == {
        "z0_target_ohm": 50.0}
    # 预声明枚举表/门常量钉（模块常量单源）
    assert em._SSL_RACE_AXES == ("w_mm", "b_mm", "h_mm", "eps_r")
    assert em._SSL_RACE_FACTORS == (-0.2, -0.1, 0.1, 0.2)
    assert em._G5_OVER_UNITY_MAX == 0 and em._G5_PASSIVITY_MAX == 1.05
    assert em._G5_PASSIVITY_EXCESS_MAX == 0.05
    assert sorted(em._G5_STATS_KEYS) == ["attribution", "over_unity_count",
                                         "passivity_max", "peak_band_ghz",
                                         "source", "variant_split"]
    assert em._SSL_MATRIX_AXES == (("b_mm", 0.45, 0.55),
                                   ("h_mm", 0.045, 0.055),
                                   ("eps_r", 10.71, 13.09))


def test_qx43_criteria_enum_unchanged_and_families_registered():
    """判据枚举零新增（G5 双门复用 gate_pass/closedform_match——词表闭集
    防漂移钉）+三新 family runner 注册面/注册序=闭集序。"""
    assert len(em.CRITERIA_NAMES) == 10
    assert em.registered_criteria() == em.CRITERIA_NAMES
    assert em.CRITERIA_NAMES[-2:] == ("fd_convergence",
                                      "three_way_consistency")  # Q-X22 尾序
    assert not ({"over_unity_count", "passivity_max"}
                & set(em.CRITERIA_NAMES))
    assert em.registered_families() == em.BENCH_FAMILIES
    for fam in ("ssl_race", "ssl_g5", "ssl_matrix"):
        assert callable(em.criterion_fn("gate_pass"))  # 注册表面健全性
        assert fam in em.registered_families()


def test_run_ssl_param_race_full_chain_pass(qx43_race_result):
    """param_race 批量全链：16 变体全 CONVERGED、双判据批量最坏聚合 pass、
    枚举序=轴插入序×因子序（确定性枚举表）。"""
    r = qx43_race_result[0]
    assert r["ok"] is True and r["verdict"] == "pass" and r["errors"] == []
    fd = r["scores"]["fd_convergence"]
    assert fd["verdict"] == "pass" and fd["threshold"] == 1e-3
    assert fd["value"] < 1e-3 and fd["note"] == "CONVERGED"
    cf = r["scores"]["closedform_match"]
    assert cf["verdict"] == "pass" and cf["threshold"] == 0.015
    assert cf["value"] <= 0.015
    detail = r["detail"]
    assert detail["n_variants"] == 16
    assert detail["variant_table"]["axes"] == ["w_mm", "b_mm", "h_mm", "eps_r"]
    assert detail["variant_table"]["factors"] == [-0.2, -0.1, 0.1, 0.2]
    rows = detail["variants"]
    assert [v["variant_id"] for v in rows] == [
        f"{axis}{pct:+d}pct"
        for axis in ("w_mm", "b_mm", "h_mm", "eps_r")
        for pct in (-20, -10, 10, 20)]
    assert len({v["variant_id"] for v in rows}) == 16  # 变体锚唯一
    assert all(v["fd"]["status"] == "CONVERGED" for v in rows)
    assert all(v["fd"]["residual_max"] < 1e-3 for v in rows)
    assert all(v["verdicts"] == {"fd_convergence": "pass",
                                 "closedform_match": "pass"} for v in rows)


def test_run_ssl_param_race_deterministic_two_runs(qx43_race_result):
    """变体确定性（Q-X43 验收钉）：同任务两次全链真跑 → 结果 dict 逐字段
    同构（JSON 序列化逐字节同——纯确定性内核，零随机零时序）。"""
    r1, r2 = qx43_race_result
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_run_ssl_param_race_numbers_match_probe(qx43_race_result):
    """批量数字带对探针标定（runs/aurora_q/qx43_stats/probe_numbers.json）：
    最坏残差/最坏闭式偏差逐变体可溯（w_mm 轴两端）。"""
    r = qx43_race_result[0]
    rows = {v["variant_id"]: v for v in r["detail"]["variants"]}
    assert rows["w_mm-20pct"]["fd"]["residual_max"] == \
        pytest.approx(_QX43_RACE_RES_WORST, rel=2e-2)
    assert rows["w_mm+20pct"]["deviation"] == \
        pytest.approx(_QX43_RACE_DEV_WORST, rel=2e-2)
    # 批量聚合=逐变体最坏（上界极性 max——与 scores 值互证）
    assert r["scores"]["fd_convergence"]["value"] == max(
        v["fd"]["residual_max"] for v in rows.values())
    assert r["scores"]["closedform_match"]["value"] == max(
        v["deviation"] for v in rows.values())


def test_ssl_race_runner_bad_center_fails_closed(tmp_path):
    """中心几何缺键/非法（None/负值/bool/εr<1）与扰动越域（h+20%>b）→
    fail-closed（枚举期拦截，不半程炸在 FD 内部；错误带变体 id 可判读）。"""
    for bad_center in ({}, {"b_mm": 0.5, "h_mm": 0.05, "eps_r": 11.9},
                       {"w_mm": None, "b_mm": 0.5, "h_mm": 0.05,
                        "eps_r": 11.9},
                       {"w_mm": -0.52, "b_mm": 0.5, "h_mm": 0.05,
                        "eps_r": 11.9},
                       {"w_mm": True, "b_mm": 0.5, "h_mm": 0.05,
                        "eps_r": 11.9},
                       {"w_mm": 0.52, "b_mm": 0.5, "h_mm": 0.05, "eps_r": 0.5}):
        r = em.run_bench_task(
            {"task_id": "bad-center", "family": "ssl_race",
             "input_spec": {"geometry_center": bad_center},
             "criteria": [{"name": "fd_convergence", "threshold": 1e-3},
                          {"name": "closedform_match", "threshold": 0.015}]},
            work_root=tmp_path)
        assert r["verdict"] == "fail" and r["stage"] == "execute", bad_center
        assert "geometry_center" in r["errors"][0]
    # 扰动越域：中心 h=0.45/b=0.5 → 首个越域变体（枚举序 b 轴先于 h 轴）
    # =b_mm-20pct（b=0.4<h=0.45——h+20% 越域必蕴含 b-20% 越域，枚举期拦截）
    r = em.run_bench_task(
        {"task_id": "bad-variant", "family": "ssl_race",
         "input_spec": {"geometry_center": {"w_mm": 0.52, "b_mm": 0.5,
                                            "h_mm": 0.45, "eps_r": 11.9}},
         "criteria": [{"name": "fd_convergence", "threshold": 1e-3},
                      {"name": "closedform_match", "threshold": 0.015}]},
        work_root=tmp_path)
    assert r["verdict"] == "fail" and r["stage"] == "execute"
    assert "b_mm-20pct" in r["errors"][0] and "定义域" in r["errors"][0]
    # 扰动越域（εr 定义域）：中心 εr=1.1 → eps_r-20pct=0.88<1（枚举期拦截）
    r = em.run_bench_task(
        {"task_id": "bad-variant-eps", "family": "ssl_race",
         "input_spec": {"geometry_center": {"w_mm": 0.52, "b_mm": 0.5,
                                            "h_mm": 0.05, "eps_r": 1.1}},
         "criteria": [{"name": "fd_convergence", "threshold": 1e-3},
                      {"name": "closedform_match", "threshold": 0.015}]},
        work_root=tmp_path)
    assert r["verdict"] == "fail" and r["stage"] == "execute"
    assert "eps_r-20pct" in r["errors"][0] and "定义域" in r["errors"][0]


def test_run_ssl_g5_as_recorded_baseline_fail():
    """G5 as-recorded 基准（Q-RM-4 306 点）：over_unity 零容差门 fail +
    passivity 超单位门内（1.0142−1=0.0142≤0.05）→ 任务 verdict=fail（如实
    登记冻结门 FAIL 态不凑绿）；变体分解和=计数（Q-X25 谱复算自洽钉）。"""
    r = em.run_bench_task(_tasks_by_id()["ssl-g5-attribution"])
    assert r["ok"] is True and r["verdict"] == "fail" and r["errors"] == []
    gate = r["scores"]["gate_pass"]
    assert gate["verdict"] == "fail" and gate["value"] == 306.0
    assert gate["threshold"] is None  # 布尔判据免阈值（门条件=预声明常量）
    cf = r["scores"]["closedform_match"]
    assert cf["verdict"] == "pass"
    assert cf["value"] == pytest.approx(0.0142, abs=1e-6)
    assert cf["threshold"] == 0.05
    d = r["detail"]
    assert d["split_sum_matches_over_unity"] is True  # 98+208=306 逐位自洽
    assert d["variant_split"] == {"shield": 98, "open": 208}
    assert d["gates"]["over_unity_max"] == 0
    assert d["gates"]["passivity_in_gate"] is True
    assert "50ohm" in d["attribution"]  # Q-X25 归因（提取偏置非带缘盲区）
    assert "qx25_verify" in d["source"]


def test_run_ssl_g5_postfix_state_pass():
    """G5 修复后形态（over_unity=0 + passivity_max=0.8912 欠单位）：双门
    全过 → verdict=pass——带符号超单位余量语义钉（欠单位=合法损耗态非
    违例，deviation=−0.1088 不触发上界极性）。"""
    task = _tasks_by_id()["ssl-g5-attribution"].model_copy(deep=True)
    task.input_spec = {"g5_stats": {"over_unity_count": 0,
                                    "passivity_max": 0.8912}}
    r = em.run_bench_task(task)
    assert r["ok"] is True and r["verdict"] == "pass"
    assert r["scores"]["gate_pass"]["verdict"] == "pass"
    assert r["scores"]["gate_pass"]["value"] == 0.0
    cf = r["scores"]["closedform_match"]
    assert cf["verdict"] == "pass"
    assert cf["value"] == pytest.approx(-0.1088, abs=1e-6)
    assert r["detail"]["split_sum_matches_over_unity"] is None  # 未声明如实 None


def test_run_ssl_g5_passivity_gate_negative():
    """passivity 违例（1.06→超单位 0.06>0.05）：gate 过（over_unity=0）+
    passivity 门 fail → verdict=fail（双门独立评定，任一 fail 即任务 fail）。"""
    task = _tasks_by_id()["ssl-g5-attribution"].model_copy(deep=True)
    task.input_spec = {"g5_stats": {"over_unity_count": 0,
                                    "passivity_max": 1.06}}
    r = em.run_bench_task(task)
    assert r["verdict"] == "fail"
    assert r["scores"]["gate_pass"]["verdict"] == "pass"
    assert r["scores"]["closedform_match"]["verdict"] == "fail"
    assert r["scores"]["closedform_match"]["value"] == pytest.approx(0.06)


def test_ssl_g5_runner_invalid_stats_fails_closed(tmp_path):
    """g5_stats 域检（必填缺/类型非法/未知键/可选键非法）→ fail-closed
    （声明数据面缺席不可判读不猜——铁律 7 同族）。"""
    base_criteria = [{"name": "gate_pass"},
                     {"name": "closedform_match", "threshold": 0.05}]
    for bad_stats in ({}, {"passivity_max": 1.0142},
                      {"over_unity_count": 306},
                      {"over_unity_count": True, "passivity_max": 1.0142},
                      {"over_unity_count": 306.0, "passivity_max": 1.0142},
                      {"over_unity_count": -1, "passivity_max": 1.0142},
                      {"over_unity_count": 306, "passivity_max": -1.0},
                      {"over_unity_count": 306, "passivity_max": "1.01"},
                      {"over_unity_count": 306, "passivity_max": 1.0142,
                       "no_such_key": 1},
                      {"over_unity_count": 306, "passivity_max": 1.0142,
                       "variant_split": {}},
                      {"over_unity_count": 306, "passivity_max": 1.0142,
                       "variant_split": {"shield": True}},
                      {"over_unity_count": 306, "passivity_max": 1.0142,
                       "attribution": "  "},
                      {"over_unity_count": 306, "passivity_max": 1.0142,
                       "peak_band_ghz": -10.0}):
        r = em.run_bench_task(
            {"task_id": "bad-g5", "family": "ssl_g5",
             "input_spec": {"g5_stats": bad_stats},
             "criteria": base_criteria},
            work_root=tmp_path)
        assert r["verdict"] == "fail" and r["stage"] == "execute", bad_stats
        assert "g5_stats" in r["errors"][0] or "over_unity" in r["errors"][0] \
            or "passivity" in r["errors"][0]


def test_run_ssl_matrix_full_chain_pass(qx43_matrix_result):
    """综合矩阵全链：8 组全 CONVERGED、三判据批量最坏聚合 pass、综合面
    反解回代自洽（z0_actual≈目标）、three_way 双腿带符号在界、leg_semantics
    双声明在档（第三腿=声明设计目标非 HFSS 实测——如实声明不冒充）。"""
    r = qx43_matrix_result
    assert r["ok"] is True and r["verdict"] == "pass" and r["errors"] == []
    assert r["scores"]["fd_convergence"]["verdict"] == "pass"
    assert r["scores"]["fd_convergence"]["note"] == "CONVERGED"
    assert r["scores"]["closedform_match"]["verdict"] == "pass"
    tw = r["scores"]["three_way_consistency"]
    assert tw["verdict"] == "pass" and tw["threshold"] == 0.02
    assert "fd_vs_closed=" in tw["note"] and "fd_vs_hfss=" in tw["note"]
    detail = r["detail"]
    assert detail["z0_target_ohm"] == 50.0
    assert detail["n_combos"] == 8
    rows = detail["combos"]
    assert len({v["combo_id"] for v in rows}) == 8  # 组合锚唯一
    assert rows[0]["combo_id"] == "b0p45_h0p045_e10p71"  # 轴声明序×轴值序
    for v in rows:
        geo = v["geometry"]
        assert geo["w_mm"] > 0 and geo["b_mm"] > 0 and geo["h_mm"] > 0
        # 综合面反解回代自洽（brentq 闭式内核 z0_actual≈目标，#118 家法）
        assert geo["w_mm"] == pytest.approx(v["synthesis"]["w_mm"], abs=1e-9)
        assert v["synthesis"]["z0_actual_ohm"] == pytest.approx(50.0, abs=0.01)
        assert v["fd"]["status"] == "CONVERGED"
        assert abs(v["signed_dev_closed"]) <= 0.015
        assert abs(v["signed_dev_target"]) <= 0.02
        assert v["verdicts"] == {"fd_convergence": "pass",
                                 "closedform_match": "pass",
                                 "three_way_consistency": "pass"}
    assert detail["leg_semantics"]["fd_vs_hfss"]  # 第三腿语义声明在场
    assert "目标" in detail["leg_semantics"]["fd_vs_hfss"]
    assert detail["sample_table"]["axes"] == ["b_mm", "h_mm", "eps_r"]


def test_run_ssl_matrix_numbers_match_probe(qx43_matrix_result):
    """矩阵数字带对探针标定（双通道对照锚）：批量聚合=逐腿跨点最坏——
    fd/闭式/目标三腿与 qx43_stats 探针逐项互证。"""
    r = qx43_matrix_result
    rows = r["detail"]["combos"]
    assert r["scores"]["fd_convergence"]["value"] == \
        pytest.approx(_QX43_MATRIX_RES_WORST, rel=2e-2)
    assert r["scores"]["closedform_match"]["value"] == \
        pytest.approx(_QX43_MATRIX_DEV_CLOSED_WORST, rel=2e-2)
    tw = r["scores"]["three_way_consistency"]
    assert tw["value"] == pytest.approx(_QX43_MATRIX_DEV_CLOSED_WORST,
                                        rel=2e-2)  # 最坏腿=闭式腿
    worst_t = max(rows, key=lambda v: abs(v["signed_dev_target"]))
    assert abs(worst_t["signed_dev_target"]) == \
        pytest.approx(_QX43_MATRIX_DEV_TARGET_WORST, rel=2e-2)
    # 批量 three_way measure=逐腿跨点独立取最坏（与逐点行互证）
    worst_c = max(rows, key=lambda v: abs(v["signed_dev_closed"]))
    assert tw["value"] == abs(worst_c["signed_dev_closed"])


def test_ssl_matrix_runner_bad_target_fails_closed(tmp_path):
    """综合目标缺/非法（None/负值/bool）与不可达目标（1e-3Ω 越综合面可达
    域）→ fail-closed（runner 域检/内核 bracket 检双层，错误口径可判读）。"""
    criteria = [{"name": "fd_convergence", "threshold": 1e-3},
                {"name": "closedform_match", "threshold": 0.015},
                {"name": "three_way_consistency", "threshold": 0.02}]
    for bad_spec in ({}, {"z0_target_ohm": None}, {"z0_target_ohm": -50.0},
                     {"z0_target_ohm": True}, {"z0_target_ohm": "50"},
                     {"z0_target_ohm": 1e-3}):
        r = em.run_bench_task(
            {"task_id": "bad-matrix", "family": "ssl_matrix",
             "input_spec": bad_spec, "criteria": criteria},
            work_root=tmp_path)
        assert r["verdict"] == "fail" and r["stage"] == "execute", bad_spec


def test_ssl_g5_evidence_json_roundtrip(tmp_path):
    """G5 as-recorded 证据落盘（evidence_dir 显式给定）：verdict=fail 态如实
    进档、判据 scores/g5_stats 数据面 JSON 往返同构（归因账本审计前提）。"""
    ev = tmp_path / "ev"
    r = em.run_bench_task(_tasks_by_id()["ssl-g5-attribution"],
                          evidence_dir=ev, work_root=tmp_path / "work")
    assert r["evidence_path"] is not None and Path(r["evidence_path"]).is_file()
    loaded = json.loads(Path(r["evidence_path"]).read_text(encoding="utf-8"))
    assert loaded["verdict"] == "fail"  # as-recorded 如实态进档
    assert loaded["task_id"] == "ssl-g5-attribution"
    assert loaded["family"] == "ssl_g5"
    assert loaded["scores"]["gate_pass"]["verdict"] == "fail"
    assert loaded["detail"]["over_unity_count"] == 306
    assert loaded["detail"]["passivity_max"] == pytest.approx(1.0142)


# ---------------------------------------------------------------------------
# 负例（fail-closed / unknown 不凑分）
# ---------------------------------------------------------------------------


def test_run_task_unknown_family_fails_closed():
    """未知 family → verdict=fail stage=validate（不执行不猜）。"""
    r = em.run_bench_task({"task_id": "bad", "family": "no_such_family",
                           "criteria": [{"name": "gate_pass"}]})
    assert r["ok"] is False and r["verdict"] == "fail" and r["stage"] == "validate"
    assert "无注册 runner" in r["errors"][0]
    assert r["scores"] == {}  # 零伪造分数


def test_run_task_missing_required_threshold_fails_closed():
    """必填阈值判据缺阈值 → fail-closed（#122 阈值预声明纪律）。"""
    r = em.run_bench_task({"task_id": "bad", "family": "synthesis",
                           "input_spec": {"kind": "mline", "params": {}},
                           "criteria": [{"name": "closedform_match"}]})
    assert r["verdict"] == "fail" and r["stage"] == "validate"
    assert "缺预声明阈值" in r["errors"][0]


def test_run_task_schema_invalid_fails_closed():
    """schema 非法（判据名拼写漂移）→ fail stage=validate，id 尽力保留。"""
    r = em.run_bench_task({"task_id": "typo", "family": "synthesis",
                           "criteria": [{"name": "closedform_matchh", "threshold": 0.1}]})
    assert r["verdict"] == "fail" and r["stage"] == "validate"
    assert r["task_id"] == "typo"


def test_run_task_runner_exception_is_fail(tmp_path, monkeypatch):
    """runner 异常 → verdict=fail stage=execute（执行失败计失败，不 unknown）。"""

    def _boom(task, ctx):
        raise RuntimeError("注入执行崩溃")

    monkeypatch.setitem(em._RUNNER_REGISTRY, "synthesis", _boom)
    r = em.run_bench_task({"task_id": "boom", "family": "synthesis",
                           "input_spec": {"kind": "mline", "params": {}},
                           "criteria": [{"name": "closedform_match", "threshold": 0.01}]},
                          work_root=tmp_path)
    assert r["ok"] is False and r["verdict"] == "fail" and r["stage"] == "execute"
    assert "注入执行崩溃" in r["errors"][0]


def test_run_task_bad_runner_return_shape_is_fail(tmp_path, monkeypatch):
    """runner 返回形态非法（缺 measures）→ fail（不静默当全 unknown）。"""

    def _bad(task, ctx):
        return {"detail": {}}

    monkeypatch.setitem(em._RUNNER_REGISTRY, "synthesis", _bad)
    r = em.run_bench_task({"task_id": "badshape", "family": "synthesis",
                           "input_spec": {"kind": "mline", "params": {}},
                           "criteria": [{"name": "closedform_match", "threshold": 0.01}]},
                          work_root=tmp_path)
    assert r["verdict"] == "fail" and "形态非法" in r["errors"][0]


def test_run_task_missing_measure_is_unknown_not_pass(tmp_path):
    """判据测度缺失 → 该判据 unknown，任务 verdict=unknown（不凑分负例）。"""
    task = _tasks_by_id()["syn-mline"].model_copy(deep=True)
    task.criteria.append(em.BenchCriterion(name="drc_count", threshold=0))
    r = em.run_bench_task(task, work_root=tmp_path)
    assert r["ok"] is True
    assert r["scores"]["closedform_match"]["verdict"] == "pass"  # 已测判据独立成立
    assert r["scores"]["drc_count"]["verdict"] == "unknown"
    assert "测度缺失" in r["scores"]["drc_count"]["note"]
    assert r["verdict"] == "unknown"  # 聚合：无 fail 有 unknown → unknown


def test_syn_runner_unknown_kind_fails_closed(tmp_path):
    """synthesis runner 未知 kind → RuntimeError → verdict=fail（不猜）。"""
    r = em.run_bench_task({"task_id": "badkind", "family": "synthesis",
                           "input_spec": {"kind": "slotline", "params": {}},
                           "criteria": [{"name": "closedform_match", "threshold": 0.01}]},
                          work_root=tmp_path)
    assert r["verdict"] == "fail" and r["stage"] == "execute"
    assert "kind" in r["errors"][0]


def test_evidence_dir_none_rejects_write(tmp_path):
    """evidence_dir 缺省 None → 拒写证据（evidence_path=None；#144 同款）。"""
    r = em.run_bench_task(_tasks_by_id()["syn-mline"], work_root=tmp_path)
    assert r["evidence_path"] is None


# ---------------------------------------------------------------------------
# 得分卡
# ---------------------------------------------------------------------------


def _result(tid: str, verdict: str, *, ok: bool = True, stage: str = "execute",
            scores: dict | None = None, errors: list | None = None) -> dict:
    return {"schema_version": 1, "task_id": tid, "family": "synthesis",
            "stage": stage, "ok": ok, "verdict": verdict,
            "scores": scores or {}, "errors": errors or [], "evidence_path": None}


def test_score_bench_aggregates_mixed_verdicts():
    """混合 verdict 聚合：n_pass/n_fail/n_unknown + success_rate。"""
    card = em.score_bench([
        _result("a", "pass"), _result("b", "pass"), _result("c", "fail"),
        _result("d", "unknown"),
    ])
    assert card["n_tasks"] == 4
    assert (card["n_pass"], card["n_fail"], card["n_unknown"]) == (2, 1, 1)
    assert card["three_metrics"]["success_rate"]["value"] == pytest.approx(0.5)
    assert {t["task_id"] for t in card["tasks"]} == {"a", "b", "c", "d"}


def test_score_bench_empty_results_success_rate_none():
    """零案例：success_rate=None（不虚构 0——0 是合法实测值，缺席是缺席）。"""
    card = em.score_bench([])
    assert card["n_tasks"] == 0
    assert card["three_metrics"]["success_rate"]["value"] is None
    assert card["three_metrics"]["interface_failure_rate"]["value"] is None
    assert card["three_metrics"]["token_cost"]["value"] is None


def test_score_bench_token_cost_always_none():
    """token_cost 恒 None（无计费账本——有结果也不编数）。"""
    card = em.score_bench([_result("a", "pass"), _result("b", "fail")])
    assert card["three_metrics"]["token_cost"] == {
        "value": None,
        "basis": "无计费账本——成本轴缺数据如实 None 不编数（铁律 7 同族）"}


def test_score_bench_interface_failure_rate_honest_none():
    """interface_failure_rate 公开面语义：分类面为内部档（不在公开树），
    公开面恒如实 None（铁律 7 同族——缺就是不缺，不编数）；failure_counts
    =通用 pass/fail/unknown 三态计数。"""
    failing_scores = {"closedform_match": {"value": 0.5, "verdict": "fail",
                                           "threshold": 0.01, "note": None}}
    card = em.score_bench([
        _result("ok1", "pass"),
        _result("bad", "fail", ok=False, stage="validate",
                errors=["判据 ['closedform_match'] 缺预声明阈值"]),
        _result("gate", "fail", ok=True, scores=failing_scores),
        _result("crash", "fail", ok=False, stage="execute", errors=["RuntimeError: x"]),
    ])
    three = card["three_metrics"]["interface_failure_rate"]
    assert three["value"] is None
    assert card["failure_counts"] == {"pass": 1, "fail": 3, "unknown": 0}


def test_score_bench_invalid_entries_counted():
    """非 Mapping/缺 verdict 键条目 → n_invalid（多报不放过，#316 方向）。"""
    card = em.score_bench([_result("a", "pass"), "garbage", {"task_id": "no_verdict"}])
    assert card["n_tasks"] == 1 and card["n_invalid"] == 2


def test_scorecard_json_safe(tmp_path):
    """得分卡 JSON 安全（落档前提）：dump 往返同构。"""
    card = em.score_bench([_result("a", "pass")])
    text = json.dumps(card, ensure_ascii=False, sort_keys=True)
    assert json.loads(text)["n_pass"] == 1


# ---------------------------------------------------------------------------
# 零 LLM 面（T-Q24「不用 LLM 打分」红线静态钉）
# ---------------------------------------------------------------------------


def test_module_zero_llm_import_surface():
    """模块源 AST import 扫描：LLM 通道/proposer 零触碰（确定性判据红线）。"""
    banned = ("llm_transport", "proposer", "openai", "anthropic", "pydantic_ai",
              "agent_sandbox", "agent_runtime")
    source = Path(em.__file__).read_text(encoding="utf-8")
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


def test_module_docstring_declares_criteria_enum_absorption():
    """T-Q24 判据吸收对照表在档（模块 docstring 钉——学术判据可溯）。"""
    doc = em.__doc__ or ""
    for keyword in ("T-Q24", "certificate_pass", "erc_clean", "drc_count",
                    "token_cost", "success_rate", "closedform_match", "gate_pass"):
        assert keyword in doc, f"docstring 缺判据吸收锚: {keyword}"
