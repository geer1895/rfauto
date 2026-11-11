"""em_bench Q-X55 扩容测试（aurora_q EM bench 任务扩容第二席）。

覆盖（任务书验收口径）：
- default 12→15 词表同步钉：两新 family（layered_verdict/ssl_rereverify）
  尾部追加+runner 注册面、判据枚举闭集零新增（复用 gate_pass/
  closedform_match）、三新任务预声明阈值锚（#122 本文件即锚）；
- prompt 型缺省变体（Q-X55 声明式枚举表 DEFAULT_PROMPT_VARIANTS）：
  表键闭集=prompt 型缺省任务全集、确定性（同任务两次调用逐字段同构）、
  同族路由不变量（变体与基线 route_family 同族——跨族措辞禁入枚举表）、
  未声明任务 fail-closed、失败探针继承；
- prompt 通道真跑（run_bench_with_proposals，#139 零网络）：wilkinson
  3 变体全 pass / branchline 3 变体 as-recorded 全 fail（措辞不敏感性：
  scores 跨变体逐字段同构）/ loop 变体真实 run_once 湖落 work_root
  （#144 纪律零真实污染）；
- branchline-campaign 全链：campaign 第二器件族 as-recorded FAIL（fake
  branchline 闭式模型粗档——3dB 等分偏差 75%/S11 杆不达，如实登记不凑
  绿）+ 门名随路由族（branchline_campaign_gate；wilkinson 门名逐字节
  不变——既有输出兼容钉）；
- layered-stack-verdict 全链：Q-X26 对照判读服务消费（as-recorded 三档
  冻结快照：三档 INCOMPLETE 透传不升格、eps_eff_rel 最坏 4.63、RC1 两档
  implicated → 双判据如实 FAIL）+ 合成两档正例（对照表/配对/RC 分解
  全绿 pass）+ 域检负例（tiers 缺/行缺键）+ RC 结构面门负例；
- suspended-stripline-rereverify 全链：Q-X27 判读单源动态加载消费
  （as-recorded 基准：期望核对 6 hit/2 miss → gate fail；G3 双基准最坏
  2.88% ≤5% 冻结带 → closedform pass；任务 verdict=fail 如实）+ 注入
  已清偿态正例（8 hit/0 miss → pass）+ 快照域检/三源一致守卫负例 +
  判读单源缺失 fail-loud + 确定性两跑逐字段同构。

零网络零真机（#139）：全部离线确定性（design_chain fake 采样器固定
seed/判读面纯函数/声明数据判读）；evidence/work_root 全落 tmp_path。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service import em_bench_service as em


def _task_by_id(task_id: str) -> em.BenchTask:
    return {t.task_id: t for t in em.default_bench_tasks()}[task_id]


# ---------------------------------------------------------------------------
# 词表同步钉（default 12→15 / family 尾序 / 判据枚举零新增）
# ---------------------------------------------------------------------------


def test_qx55_families_and_criteria_vocabulary_unchanged_enum():
    """两新 family 尾部追加（闭集纪律）+runner 注册面覆盖；判据枚举零新增
    （两新任务复用 gate_pass/closedform_match——词表闭集防漂移钉）。"""
    assert em.BENCH_FAMILIES[-2:] == ("layered_verdict", "ssl_rereverify")
    assert len(em.BENCH_FAMILIES) == 11  # v0.14.0 移除笔：loop 族摘除（闭环任务面内部档）
    assert em.registered_families() == em.BENCH_FAMILIES
    assert len(em.CRITERIA_NAMES) == 10  # Q-X55 零新判据（复用既有闭集）
    assert em.registered_criteria() == em.CRITERIA_NAMES
    assert em.CRITERIA_NAMES[-2:] == ("fd_convergence",
                                      "three_way_consistency")  # Q-X22 尾序不动
    for tid, fam in (("layered-stack-verdict", "layered_verdict"),
                     ("suspended-stripline-rereverify", "ssl_rereverify")):
        assert _task_by_id(tid).family == fam


def test_qx55_new_task_thresholds_predeclared_pins():
    """三新任务预声明锚（#122：本函数即预声明锚，改动=改门口径须同笔）：
    branchline=理想 3dB 等分带 0.10/−15dB 杆（wilkinson 同款物理带）；
    layered=closedform 0.02（qx10 G1_PASS 承袭）+gate 布尔；rereverify=
    gate 布尔+closedform 0.05（G3_PARTIAL 冻结带承袭）。模块常量钉。"""
    by_id = {t.task_id: t for t in em.default_bench_tasks()}
    bl = {c.name: c.threshold for c in by_id["branchline-campaign"].criteria}
    assert bl == {"closedform_match": 0.10, "gate_pass": -15.0}
    assert by_id["branchline-campaign"].input_spec == {
        "prompt": "设计一个 2.4GHz 50 欧姆分支线电桥，等分输出"}
    lv = {c.name: c.threshold for c in by_id["layered-stack-verdict"].criteria}
    assert lv == {"closedform_match": 0.02, "gate_pass": None}
    assert by_id["layered-stack-verdict"].input_spec["closed_eps_eff"] == \
        em._QX26_CLOSED_EPS_EFF == 1.6007603731686557
    assert set(by_id["layered-stack-verdict"].input_spec["tiers"]) == {
        "C_qx10_prefix", "C_qx10_postfix", "A_qx11_prefix"}
    rr = {c.name: c.threshold
          for c in by_id["suspended-stripline-rereverify"].criteria}
    assert rr == {"gate_pass": None, "closedform_match": 0.05}
    assert em._QX55_REREVERIFY_G3_REL_MAX == 0.05
    assert len(em._QX26_ROW_REQUIRED_KEYS) == 13
    # as-recorded FAIL 溯源锚在场（#122 不凑绿声明面）
    assert "as-recorded" in by_id["branchline-campaign"].data_source
    assert "as-recorded" in by_id["layered-stack-verdict"].data_source
    assert "as-recorded" in by_id["suspended-stripline-rereverify"].data_source


def test_qx55_new_symbols_deliberately_not_in_all():
    """Q-X55 新公开名（DEFAULT_PROMPT_VARIANTS/default_prompt_variants）
    **有意不进 __all__**（tests/gold/public_api.json 金快照本席禁改——
    公开面政策=模块 __all__，扩 __all__ 须同笔再生金快照=合流阶段主代理
    动作；本钉防无同笔金快照再生的意外扩面）。"""
    assert "DEFAULT_PROMPT_VARIANTS" not in em.__all__
    assert "default_prompt_variants" not in em.__all__


# ---------------------------------------------------------------------------
# prompt 型缺省变体（声明式枚举表）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qx55_branchline_single(tmp_path_factory):
    return em.run_bench_task(_task_by_id("branchline-campaign"),
                             work_root=tmp_path_factory.mktemp("q55_bl1"))


@pytest.fixture(scope="module")
def qx55_layered_result(tmp_path_factory):
    return em.run_bench_task(_task_by_id("layered-stack-verdict"),
                             work_root=tmp_path_factory.mktemp("q55_lv"))


@pytest.fixture(scope="module")
def qx55_rereverify_results(tmp_path_factory):
    """缺省任务两次真跑（确定性钉）+判读单源加载一次共享。"""
    task = _task_by_id("suspended-stripline-rereverify")
    r1 = em.run_bench_task(task, work_root=tmp_path_factory.mktemp("q55_rr1"))
    r2 = em.run_bench_task(task, work_root=tmp_path_factory.mktemp("q55_rr2"))
    return r1, r2


_BL_DEV = 0.0003205019711701304   # 3dB 等分偏差（Q-X83 内核接线后 as-built
#   2026-11-10 合流笔实测：HJ forward_z0 缺省宽 1.87/1.11mm 臂阻抗≈设计臂；
#   预告值 7.376e-16 系纯闭式设计臂口径——差值=HJ 准静态阻抗 vs 闭式设计
#   臂的几何差，如实登记不凑值；门 ≤0.10 实测 300× 余量）


_BL_S11_MIN = -61.74101765089705  # s11_db_min_in_band as-built 实测（预告
#   −316.68 系纯闭式设计臂口径；HJ 臂轻微失配仍深过 −15dB 门）


def test_qx55_branchline_campaign_task_wired_kernel_pass(qx55_branchline_single):
    """branchline-campaign 单任务全链：双判据 PASS（Q-X83 理想 TL 闭式内核
    接线 aurora_r 合流笔 2026-11-10 翻绿——原粗档 as-recorded FAIL（3dB 等
    分偏差 ~75%/S11 杆 −8.1dB）如实留档于 DEVLOG 三百零二）；族路由
    branchline、寻优 kickoff completed、综合参数在档。"""
    r = qx55_branchline_single
    assert r["ok"] is True and r["verdict"] == "pass" and r["errors"] == []
    assert r["stage"] == "execute"
    cf = r["scores"]["closedform_match"]
    assert cf["verdict"] == "pass" and cf["threshold"] == 0.10
    assert cf["value"] == pytest.approx(_BL_DEV, rel=2e-3)
    gate = r["scores"]["gate_pass"]
    assert gate["verdict"] == "pass" and gate["threshold"] == -15.0
    assert gate["value"] == pytest.approx(_BL_S11_MIN, abs=1e-3)
    assert r["detail"]["family"] == "branchline"
    assert r["detail"]["kickoff_status"] == "completed"
    assert r["detail"]["synthesis_params"]["f0_ghz"] == 2.4


def test_qx55_campaign_gate_name_follows_family():
    """门名随路由族（Q-X55）：branchline → branchline_campaign_gate；
    wilkinson 输出逐字节不变（既有输出兼容钉）。"""
    bl = em._RUNNER_REGISTRY["campaign"](
        _task_by_id("branchline-campaign"), em.BenchRunContext())
    assert bl["measures"]["gate_pass"]["gate"] == "branchline_campaign_gate"
    wil = em._RUNNER_REGISTRY["campaign"](
        _task_by_id("wilkinson-campaign"), em.BenchRunContext())
    assert wil["measures"]["gate_pass"]["gate"] == "wilkinson_campaign_gate"


# ---------------------------------------------------------------------------
# layered-stack-verdict 全链（Q-X26 对照判读服务消费）
# ---------------------------------------------------------------------------


def test_qx55_layered_verdict_as_recorded_fail(qx55_layered_result):
    """缺省任务（Q-X26 三档冻结快照）as-recorded FAIL：三档 INCOMPLETE
    透传不升格（#122）、closedform_match 最坏 4.63（A_qx11_prefix）超
    G1 带 fail、RC 结构面门 fail（RC1 两档 implicated+一档 unevaluated）、
    RC3 对照结论=联合精化不治（Q-X26 as-recorded 同款）、配对 pre-fix
    在档、数据溯源随行。"""
    r = qx55_layered_result
    assert r["ok"] is True and r["verdict"] == "fail" and r["errors"] == []
    assert r["stage"] == "execute"
    cf = r["scores"]["closedform_match"]
    assert cf["verdict"] == "fail" and cf["threshold"] == 0.02
    assert cf["value"] == pytest.approx(4.63135704204921, rel=1e-6)
    gate = r["scores"]["gate_pass"]
    assert gate["verdict"] == "fail" and gate["value"] == 0.0
    assert gate["threshold"] is None  # 布尔判据免阈值
    d = r["detail"]
    assert d["summary"]["n_tiers"] == 3 and d["summary"]["n_incomplete"] == 3
    assert "不升格" in d["summary"]["incomplete_passthrough_note"]
    rc = d["rc_matrix"]
    assert rc["conclusions"]["RC3_truncation"] == \
        "window_mesh_joint_refinement_not_cured"
    assert rc["factors"]["C_qx10_prefix"][
        "RC1_geometry_port_structure"] == "unevaluated"
    assert rc["factors"]["C_qx10_postfix"][
        "RC1_geometry_port_structure"] == "implicated"
    assert len(rc["pairs"]) == 1
    assert rc["pairs"][0]["geometry"] == "pre-fix"
    assert rc["pairs"][0]["rc3"]["pair_verdict"] == \
        "not_cured_by_joint_refinement"
    assert d["closed_eps_eff"] == 1.6007603731686557
    assert all(v for v in d["data_provenance"].values())  # 溯源随行
    assert d["gate_rule"] and "unevaluated" in d["gate_rule"]


def test_qx55_layered_verdict_synthetic_two_tier_pass(tmp_path):
    """合成两档正例（同 geometry 标签、粗/细两档、S0 清白+零超一点+观测
    贴锚）：RC1/RC3 双 excluded → gate pass；eps_eff_rel 0.31% ≤2% →
    closedform pass；对照表配对 absent_both；任务 verdict=pass。"""
    tiers = {
        "mesh_coarse": {
            "name": "mesh_coarse", "verdict": "AGREE", "not_judged": False,
            "g0_status": "PASS", "s0_status": "PASS", "s0_failed": [],
            "port_structure_suspect": False, "truncation_suspect": False,
            "over_unity_cnt": 0, "eps_eff_med": 1.605,
            "eps_eff_closed": 1.6007603731686557, "eps_eff_rel": None,
            "mesh_base_mm": 0.04, "mesh_cells": 100, "dt_fs": 12.25,
            "nrts": 51000, "window_ps": 625.0, "geometry": "synthetic",
            "source": "tests/unit/test_em_bench_qx55.py 合成档（判读机制钉）",
        },
        "mesh_fine": {
            "name": "mesh_fine", "verdict": "AGREE", "not_judged": False,
            "g0_status": "PASS", "s0_status": "PASS", "s0_failed": [],
            "port_structure_suspect": False, "truncation_suspect": False,
            "over_unity_cnt": 0, "eps_eff_med": 1.6025,
            "eps_eff_closed": 1.6007603731686557, "eps_eff_rel": None,
            "mesh_base_mm": 0.02, "mesh_cells": 800, "dt_fs": 12.25,
            "nrts": 51000, "window_ps": 625.0, "geometry": "synthetic",
            "source": "tests/unit/test_em_bench_qx55.py 合成档（判读机制钉）",
        },
    }
    r = em.run_bench_task(
        {"task_id": "lv-synth", "family": "layered_verdict",
         "input_spec": {"tiers": tiers, "closed_eps_eff": 1.6007603731686557},
         "criteria": [{"name": "closedform_match", "threshold": 0.02},
                      {"name": "gate_pass"}]},
        work_root=tmp_path)
    assert r["ok"] is True and r["verdict"] == "pass" and r["errors"] == []
    cf = r["scores"]["closedform_match"]
    assert cf["verdict"] == "pass" and cf["value"] == pytest.approx(
        abs(1.605 - 1.6007603731686557) / 1.6007603731686557, rel=1e-6)
    gate = r["scores"]["gate_pass"]
    assert gate["verdict"] == "pass"
    rc = r["detail"]["rc_matrix"]
    assert len(rc["pairs"]) == 1
    pair = rc["pairs"][0]
    assert (pair["coarse"], pair["fine"]) == ("mesh_coarse", "mesh_fine")
    assert pair["base_ratio"] == pytest.approx(2.0)
    assert pair["rc1"]["pair_verdict"] == "absent_both"
    assert pair["rc3"]["pair_verdict"] == "absent_both"
    assert rc["conclusions"]["RC2_mesh"] == "not_observable"
    # 行内 eps_eff_rel 由服务重算消费（声明 None 亦不缺——对照表补算）
    assert all(row["eps_eff_rel"] is not None
               for row in r["detail"]["tiers"].values())


def test_qx55_layered_verdict_runner_bad_input_fails_closed(tmp_path):
    """域检负例：tiers 缺/非映射/行非映射/行缺必需键 → execute fail
    （对照/分解消费面不猜）。"""
    good_row = dict(em._QX26_TIERS_SNAPSHOT["C_qx10_postfix"])
    for bad_spec in ({}, {"tiers": None}, {"tiers": []},
                     {"tiers": {"t1": "not-a-mapping"}},
                     {"tiers": {"t1": {"name": "t1"}}},  # 缺 12 键
                     {"tiers": {"t1": {k: v for k, v in good_row.items()
                                       if k != "s0_status"}}},
                     {"tiers": {"t1": good_row}, "closed_eps_eff": "x"}):
        r = em.run_bench_task(
            {"task_id": "bad-lv", "family": "layered_verdict",
             "input_spec": bad_spec,
             "criteria": [{"name": "closedform_match", "threshold": 0.02},
                          {"name": "gate_pass"}]},
            work_root=tmp_path)
        assert r["verdict"] == "fail" and r["stage"] == "execute", bad_spec
        assert "tiers" in r["errors"][0] or "closed_eps_eff" in r["errors"][0] \
            or "档位" in r["errors"][0]


def test_qx55_layered_verdict_gate_negative(tmp_path):
    """RC 结构面门负例：单档端口结构嫌疑（S0 TRIGGER）→ gate fail →
    任务 fail；closedform 独立达标不连坐（结构门与数值判据分离评定）。"""
    row = dict(em._QX26_TIERS_SNAPSHOT["C_qx10_postfix"])
    row.update({"name": "only", "eps_eff_med": 1.603,
                "eps_eff_rel": None})  # 观测贴锚（name 与映射键对齐）
    r = em.run_bench_task(
        {"task_id": "lv-gate-neg", "family": "layered_verdict",
         "input_spec": {"tiers": {"only": row},
                        "closed_eps_eff": 1.6007603731686557},
         "criteria": [{"name": "closedform_match", "threshold": 0.02},
                      {"name": "gate_pass"}]},
        work_root=tmp_path)
    assert r["ok"] is True and r["verdict"] == "fail"
    assert r["scores"]["closedform_match"]["verdict"] == "pass"
    assert r["scores"]["gate_pass"]["verdict"] == "fail"
    assert r["detail"]["rc_matrix"]["factors"]["only"][
        "RC1_geometry_port_structure"] == "implicated"


# ---------------------------------------------------------------------------
# suspended-stripline-rereverify 全链（Q-X27 判读单源消费）
# ---------------------------------------------------------------------------


def test_qx55_ssl_rereverify_as_recorded_fail(qx55_rereverify_results):
    """缺省任务（判读单源 as-recorded 冻结快照）真跑：期望核对 6 hit/
    2 miss（G5 计数分支 MIXED_PARTIAL_DROP 非大幅线+总判 DISAGREE 非预期
    PARTIAL）→ gate fail；G3 双基准最坏 2.88% ≤5% 冻结带 → closedform
    pass；任务 verdict=fail（as-recorded 如实登记不凑绿）；三态对照表/
    G5 归因/期望核对全量随行。"""
    r1, r2 = qx55_rereverify_results
    r = r1
    assert r["ok"] is True and r["verdict"] == "fail" and r["errors"] == []
    assert r["stage"] == "execute"
    gate = r["scores"]["gate_pass"]
    assert gate["verdict"] == "fail" and gate["value"] == 2.0
    assert gate["threshold"] is None
    cf = r["scores"]["closedform_match"]
    assert cf["verdict"] == "pass" and cf["threshold"] == 0.05
    assert cf["value"] == pytest.approx(0.028764247472669587, rel=1e-6)
    d = r["detail"]
    assert "as-recorded" in d["states_source"]  # 快照常量数据源声明
    chk = d["expectation_check"]
    assert (chk["n_hits"], chk["n_misses"]) == (6, 2)
    assert any("G5_count_branch" in m for m in chk["misses"])
    assert any(m.startswith("verdict:") for m in chk["misses"])
    g5 = d["g5_attribution"]
    assert g5["over_unity_before"] == 306 and g5["over_unity_after"] == 180
    assert g5["drop_ratio"] == pytest.approx((306 - 180) / 306)
    assert g5["classification"] == "MIXED_PARTIAL_DROP"
    assert g5["per_variant"]["variant_asymmetric"] is True  # shield 升 open 降
    assert g5["residual_face"] == "Q-X25_50ohm_mismatch_bias"
    tbl = d["three_state_table"]
    assert (tbl["verdict_before"], tbl["verdict_near_fix"],
            tbl["verdict_reverify"]) == ("DISAGREE", "DISAGREE", "DISAGREE")
    assert tbl["fail_gates_before"] == ["G1"]
    assert tbl["fail_gates_near_fix"] == ["G5"]
    assert tbl["fail_gates_reverify"] == ["G5"]
    g3 = d["g3_basis_switch"]["reverify"]
    assert g3["status_vs_closed"] == "PARTIAL" and g3["status_vs_fd"] == "PASS"
    assert g3["in_fd_band"] is True
    # 确定性（判读面纯函数+冻结快照）：两跑逐字段同构
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_qx55_ssl_rereverify_cleared_state_pass(tmp_path):
    """注入已清偿态正例：重验 G5 计数大幅下降（306→100 SUBSTANTIAL_DROP
    命中预声明分支）+总判 PARTIAL+G3 双基准（vs 闭式 PARTIAL/vs FD PASS）
    → 期望 8 hit/0 miss → gate pass；G3 最坏 2.71% ≤5% → closedform pass；
    任务 verdict=pass；分变体和=三态计数一致守卫过。"""
    mod = em._load_ssl_rereverify_module()
    reverify = {
        "verdict": "PARTIAL",
        "gates": {
            "G1": {"status": "PASS", "observed_s21_mean_db": -0.001},
            "G2": {"status": "PASS", "observed_s11_max_db": -20.0},
            "G3": {"status": "PARTIAL", "observed_eps_eff": 1.56,
                   "rel": 0.02708},
            "G4": {"status": "PASS", "observed_z0_ohm": 50.0, "rel": 0.018},
            "G5": {"status": "FAIL", "passivity_max": 1.0123,
                   "s_over_unity_cnt": 100},
        },
    }
    states = {
        "before": dict(mod.V_RM1),
        "near_fix": dict(mod.V_RM4),
        "reverify": reverify,
        "ou_before": {"ssl_shield": 98, "ssl_open": 208},
        "ou_after": {"ssl_shield": 60, "ssl_open": 40},
    }
    r = em.run_bench_task(
        {"task_id": "rr-cleared", "family": "ssl_rereverify",
         "input_spec": {"states": states},
         "criteria": [{"name": "gate_pass"},
                      {"name": "closedform_match", "threshold": 0.05}]},
        work_root=tmp_path)
    assert r["ok"] is True and r["verdict"] == "pass" and r["errors"] == []
    assert r["scores"]["gate_pass"]["verdict"] == "pass"
    assert r["scores"]["gate_pass"]["value"] == 0.0
    cf = r["scores"]["closedform_match"]
    assert cf["verdict"] == "pass"
    assert cf["value"] == pytest.approx(
        abs(1.56 - 1.6034175826523378) / 1.6034175826523378, rel=1e-6)
    d = r["detail"]
    assert d["expectation_check"]["n_misses"] == 0
    assert d["expectation_check"]["n_hits"] == 8
    assert d["g5_attribution"]["classification"] == "SUBSTANTIAL_DROP"
    assert d["states_source"] == "input_spec.states 声明数据（调用方供给）"


def test_qx55_ssl_rereverify_bad_states_fails_closed(tmp_path):
    """快照域检/三源一致守卫负例：states 缺必填键/门映射缺 status/G5 计数
    非法/G3 观测非法/分变体和与三态计数不一致 → execute fail（混态数据
    不进判读——Q-X27 三源一致守卫同款纪律）。"""
    mod = em._load_ssl_rereverify_module()
    good_reverify = dict(mod.V_REVERIFY)
    good = {"before": dict(mod.V_RM1), "near_fix": dict(mod.V_RM4),
            "reverify": good_reverify}
    bad_gates = dict(mod.V_REVERIFY)
    bad_gates = {**bad_gates, "gates": {**bad_gates["gates"],
                                        "G3": {"status": ""}}}
    bad_count = dict(mod.V_REVERIFY)
    bad_count = {**bad_count, "gates": {
        **bad_count["gates"],
        "G5": {**bad_count["gates"]["G5"], "s_over_unity_cnt": True}}}
    bad_eps = dict(mod.V_REVERIFY)
    bad_eps = {**bad_eps, "gates": {
        **bad_eps["gates"],
        "G3": {**bad_eps["gates"]["G3"], "observed_eps_eff": -1.0}}}
    cases = [
        ({}, "缺必填键"),                                        # states 空
        ({**good, "reverify": "not-a-mapping"}, "须为映射"),
        ({**good, "reverify": bad_gates}, "status"),
        ({**good, "reverify": bad_count}, "s_over_unity_cnt"),
        ({**good, "reverify": bad_eps}, "observed_eps_eff"),
        ({**good, "ou_after": {"ssl_shield": 1}}, "分变体和"),   # 1≠180
        ({**good, "ou_before": {"ssl_shield": -5}}, "非负整数"),
        ({**good, "ou_after": {"ssl_shield": True}}, "非负整数"),
    ]
    for states, needle in cases:
        r = em.run_bench_task(
            {"task_id": "bad-rr", "family": "ssl_rereverify",
             "input_spec": {"states": states},
             "criteria": [{"name": "gate_pass"},
                          {"name": "closedform_match", "threshold": 0.05}]},
            work_root=tmp_path)
        assert r["verdict"] == "fail" and r["stage"] == "execute", (needle,
                                                                    states)
        assert needle in r["errors"][0], (needle, r["errors"][0])


def test_qx55_ssl_rereverify_module_missing_fails_loud(tmp_path):
    """判读单源缺失 → FileNotFoundError（fail-loud 不静默降级——发布包无
    tests/ 时诚实失败，layered_stack_verdict_service 同款形态）。"""
    with pytest.raises(FileNotFoundError, match="判读单源缺失"):
        em._load_ssl_rereverify_module(tmp_path / "no_such_module.py")


def test_qx55_new_tasks_scorecard_gate_fail_not_interface(tmp_path):
    """得分卡分类钉：两新任务 as-recorded fail=数据判 fail（gate_fail 类，
    非接口类——interface_failure_rate 不受污染；execution 全 ok）。"""
    by_id = {t.task_id: t for t in em.default_bench_tasks()}
    results = [em.run_bench_task(by_id["layered-stack-verdict"],
                                 work_root=tmp_path / "w1"),
               em.run_bench_task(by_id["suspended-stripline-rereverify"],
                                 work_root=tmp_path / "w2"),
               em.run_bench_task(by_id["branchline-campaign"],
                                 work_root=tmp_path / "w3")]
    card = em.score_bench(results)
    # branchline 内核接线后翻绿（aurora_r 合流笔 2026-11-10）→ n_fail 3→2
    # （layered-stack-verdict/suspended-stripline-rereverify 仍 as-recorded
    # fail 如实保持——只有 branchline 翻绿）；failure_counts=通用三态计数
    # （接口失败分类面=内部档不在公开树，interface_failure_rate 恒 None）
    assert (card["n_tasks"], card["n_fail"]) == (3, 2)
    assert card["failure_counts"] == {"pass": 1, "fail": 2, "unknown": 0}
    assert card["three_metrics"]["interface_failure_rate"]["value"] is None
    assert {t["family"] for t in card["tasks"]} >= {"layered_verdict",
                                                    "ssl_rereverify"}
