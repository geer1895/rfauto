"""G8 引擎基准扩容 2026-09-15 证据 golden 钉子（离线零真机）。

背景：五锚产物落 runs/benchmark/（runs/ 不入库），可提交证据面为空。
按 tests/golden/ 惯例（参照 mline_benchmark_rescan_20260913.json）把
G8 扩容结果快照入库：tests/golden/engine_benchmark_expand_20260915.json
（四离线锚归档入账 + msl_cpw 真机补跑）。本文件离线回放：
① 快照结构自检（防证据文件本身被误改坏）；
② 每锚记录指标过判据内核 core/anchor_benchmark 复判 == 记录判定，
   且 verdict 与 gate_flags 自洽（PASS ⟺ 全门 True）；
③ criteria == 内核默认门常量（判据改动=显式重标定，须同步快照）；
④ 四离线锚 verdict==PASS 硬钉（归档数值离线复算实测现门全过）；
   msl_cpw 为真跑快照，只钉自洽不预设 PASS（#122 不凑绿）；
⑤ mline 证据面未动（新时点只新增不覆写）；
⑥ 20260915b 重标定：msl_cpw 传输门增补无源上界 |S21| 带内
   max ≤1.02，首轮真跑 mean 1.0296 / 带内 max 1.2902 由 PASS 如实改判
   FAIL（#122）；快照 metrics 补 s21_lin_band_max、gate_flags 补
   passive_ok、criteria 补 s21_lin_band_max_le，五锚 gate_version 同步；
   归档 runs/benchmark/msl_cpw_engine_benchmark.json 保持原样（归档不改），
   零仿真重归一证据见 runs/benchmark/msl_cpw_renorm/renorm_report.json；
⑦ 20260918a 重标定：via 传输门同构增补无源上界
   |S21| 带内 max ≤1.02，快照 metrics 补 s21_lin_band_max（0.9503，
   runs/via_smoke/pt3/sparams.csv 离线复算）、gate_flags 补 passive_ok、
   criteria 补 s21_lin_band_max_le，五锚 gate_version 同步；归档 401 点
   全部 ≤1.02 → 判定零翻转（收紧为预防性，与 msl_cpw 改判情形不同）；
   harness ingest_via 已同批补传带内 max（无悬空 followUp）。

证据源真跑命令（本测试不执行任何求解）：
  .venv/Scripts/python.exe scripts/engine_benchmark_expand.py --ingest all
  .venv/Scripts/python.exe scripts/engine_benchmark_expand.py --msl-cpw
  → runs/benchmark/<anchor>_engine_benchmark.json ×5
  日志尾：runs/benchmark/msl_cpw_m0.4/run_20260915.log
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.core import anchor_benchmark as ab

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "golden" / "engine_benchmark_expand_20260915.json"
MLINE_GOLDEN = REPO / "tests" / "golden" / "mline_benchmark_rescan_20260913.json"
OFFLINE_ANCHORS = ("ratrace", "atten_pi", "atten_t", "via")


def _load() -> dict:
    assert GOLDEN.exists(), (
        "G8 扩容证据 golden 缺失：tests/golden/engine_benchmark_expand_20260915.json")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _replay(anchor: str, metrics: dict) -> dict:
    """快照指标过内核复判（与 harness 同式）。"""
    if anchor == "ratrace":
        return ab.ratrace_benchmark_verdict(
            metrics["delta_eps_pct"], metrics["s21_db"], metrics["s41_db"],
            metrics["s31_db"], metrics["s24_db"], metrics["s11_db"],
            metrics["recip_max_lin"])
    if anchor in ("atten_pi", "atten_t"):
        return ab.atten_benchmark_verdict(
            metrics["delta_eps_pct"], metrics["s21_db_band_mean"],
            metrics["s11_db_band_max"])
    if anchor == "via":
        return ab.via_benchmark_verdict(
            metrics["delta_eps1_pct"], metrics["s11_db_band_max"],
            metrics["s21_lin_mean"], metrics["recip_db"],
            metrics["delta_eps2_pct"],
            s21_lin_band_max=metrics.get("s21_lin_band_max"))
    if anchor == "msl_cpw":
        return ab.msl_cpw_benchmark_verdict(
            metrics["delta_eps1_pct"], metrics["delta_eps2_pct"],
            metrics["s11_db_band_max"], metrics["s21_lin_mean"],
            s21_lin_band_max=metrics.get("s21_lin_band_max"))
    raise AssertionError(f"未知锚 {anchor}")


class TestSnapshotShape:
    """证据文件结构自检。"""

    def test_provenance_and_five_anchors(self):
        data = _load()
        assert data["kind"] == "engine_benchmark_expand_20260915"
        assert data["provenance"]["kernel"] == "src/rfauto/core/anchor_benchmark.py"
        assert data["provenance"]["gate_version"] == ab.GATE_VERSION
        assert data["provenance"]["harness"] == "scripts/engine_benchmark_expand.py"
        assert set(data["anchors"]) == {"ratrace", "atten_pi", "atten_t",
                                        "via", "msl_cpw"}

    def test_each_anchor_record_complete(self):
        for name, entry in _load()["anchors"].items():
            assert entry["anchor"] == name
            assert entry["gate_version"] == ab.GATE_VERSION
            assert entry["verdict"] in ("PASS", "FAIL", "PARTIAL")
            assert isinstance(entry["metrics"], dict)
            assert isinstance(entry["gate_flags"], dict)
            assert isinstance(entry["criteria"], dict)
            assert "kernel" in entry["provenance"]
            assert entry["source"].get("mesh_mm") == 0.4

    def test_source_kinds(self):
        anchors = _load()["anchors"]
        for name in OFFLINE_ANCHORS:
            assert anchors[name]["source"]["kind"] == \
                "smoke_archive_offline_ingest"
            assert anchors[name]["source"]["archive_dir"].startswith(
                "runs/")
        assert anchors["msl_cpw"]["source"]["kind"] == "openems_real_run"
        assert anchors["msl_cpw"]["source"]["working_dir"] == \
            "runs/benchmark/msl_cpw_m0.4"

    def test_offline_ingest_is_read_only_no_resolve(self):
        # 四离线锚 provenance 必须指向 smoke 归档（只读），不得含重跑痕迹
        for name in OFFLINE_ANCHORS:
            src = _load()["anchors"][name]["source"]
            assert src["kind"] == "smoke_archive_offline_ingest"
            assert "solve_s" not in src or name == "ratrace"


class TestReplayThroughKernel:
    """快照指标过内核复判 == 记录判定（判据一致性）。"""

    def test_recorded_metrics_replay_to_recorded_verdict(self):
        for name, entry in _load()["anchors"].items():
            r = _replay(name, entry["metrics"])
            assert r["verdict"] == entry["verdict"], (
                f"{name}: 内核复判 {r['verdict']} ≠ 快照判定 "
                f"{entry['verdict']}（判据漂移或快照被改）")
            flags = {k: r[k] for k in entry["gate_flags"]}
            assert flags == entry["gate_flags"]

    def test_verdict_consistent_with_gate_flags(self):
        for name, entry in _load()["anchors"].items():
            all_true = all(entry["gate_flags"].values())
            assert (entry["verdict"] == "PASS") is all_true, name

    def test_criteria_match_kernel_gates(self):
        anchors = _load()["anchors"]
        assert anchors["ratrace"]["criteria"] == {
            "delta_eps_pct_abs_le": ab.EPS_EFF_TOL_PCT,
            "split_target_db": ab.RATRACE_SPLIT_TARGET_DB,
            "split_tol_db": ab.RATRACE_SPLIT_TOL_DB,
            "balance_db_le": ab.RATRACE_BALANCE_MAX_DB,
            "s31_db_le": ab.RATRACE_ISO_DELTA_MAX_DB,
            "s24_db_le": ab.RATRACE_ISO_OUT_MAX_DB,
            "s11_db_le": -10.0,
            "recip_lin_le": ab.RATRACE_RECIP_MAX_LIN}
        for name in ("atten_pi", "atten_t"):
            assert anchors[name]["criteria"] == {
                "delta_eps_pct_abs_le": ab.EPS_EFF_TOL_PCT,
                "atten_target_db": ab.ATTEN_TARGET_DB,
                "atten_tol_db": ab.ATTEN_FLAT_TOL_DB,
                "s11_band_max_db_lt": ab.ATTEN_S11_FLOOR_DB}
        assert anchors["via"]["criteria"] == {
            "beta1_delta_eps_pct_abs_le": ab.EPS_EFF_TOL_PCT,
            "s11_band_max_db_lt": -10.0,
            "s21_lin_mean_ge": ab.VIA_S21_MIN_LIN,
            "s21_lin_band_max_le": ab.VIA_S21_MAX_LIN,
            "recip_db_le": ab.VIA_RECIP_MAX_DB}
        assert anchors["msl_cpw"]["criteria"] == {
            "eps1_delta_pct_abs_le": ab.EPS_EFF_TOL_PCT,
            "eps2_delta_pct_abs_le": ab.EPS_EFF_TOL_PCT,
            "s11_band_max_db_lt": -10.0,
            "s21_lin_mean_ge": ab.CPW_S21_MIN_LIN,
            "s21_lin_band_max_le": ab.CPW_S21_MAX_LIN}

    def test_gate_calibration_provenance_present(self):
        anchors = _load()["anchors"]
        # atten −12dB 地板与 via β1 单判的门校准依据必须入册
        assert "lumped" in anchors["atten_pi"]["provenance"][
            "gate_calibration"]
        assert "β1" in anchors["via"]["provenance"]["gate_calibration"]
        assert anchors["via"]["metrics"]["recip_source"] == "archive_log"
        assert "β2" in anchors["via"]["provenance"]["old_gate_verdict"][
            "note"]


class TestOfflineAnchorsHardPinned:
    """四离线锚现门全 PASS 硬钉（本会话离线复算实测）。"""

    def test_four_offline_verdicts_pass(self):
        anchors = _load()["anchors"]
        for name in OFFLINE_ANCHORS:
            assert anchors[name]["verdict"] == "PASS", (
                f"{name} 现门应为 PASS（归档离线复算）；若判据改动须显式"
                f"重标定并同步 golden")

    def test_archived_values_pinned(self):
        # 归档数值钉位（防快照被静默改动；出处=四 smoke 归档离线复算）
        a = _load()["anchors"]
        assert a["ratrace"]["metrics"]["s21_db"] == -3.11
        assert a["ratrace"]["metrics"]["s41_db"] == -3.27
        assert a["ratrace"]["metrics"]["s31_db"] == -24.32
        assert a["ratrace"]["metrics"]["s24_db"] == -23.81
        assert a["ratrace"]["metrics"]["s11_db"] == -26.57
        assert a["ratrace"]["metrics"]["delta_eps_pct"] == 0.894
        assert a["atten_pi"]["metrics"]["s11_db_band_max"] == -12.77
        assert a["atten_pi"]["metrics"]["s21_db_band_mean"] == -9.66
        assert a["atten_t"]["metrics"]["s11_db_band_max"] == -15.34
        assert a["atten_t"]["metrics"]["s21_db_band_mean"] == -9.64
        assert a["via"]["metrics"]["s11_db_band_max"] == -26.01
        assert a["via"]["metrics"]["s21_lin_mean"] == 0.944
        # 20260918a 补录统计量：runs/via_smoke/pt3/sparams.csv 离线复算
        assert a["via"]["metrics"]["s21_lin_band_max"] == 0.9503
        assert a["via"]["metrics"]["delta_eps1_pct"] == 0.793
        assert a["via"]["beta2_modal_difference_pct"] == 10.935

    def test_via_recip_only_from_archive_log(self):
        entry = _load()["anchors"]["via"]
        assert entry["metrics"]["recip_db"] == 0.0
        assert entry["metrics"]["recip_source"] == "archive_log"


class TestMslCpwRealRun:
    """msl_cpw 真跑快照：只钉自洽与口径，不预设 PASS（#122）。

    20260915b 起快照记录为 FAIL（无源上界超门）——这是重标定后的如实判定，
    不是"预设"：TestMslCpwRecalibration20260915b 钉住改判链条。
    """

    def test_real_run_record_self_consistent(self):
        entry = _load()["anchors"]["msl_cpw"]
        r = _replay("msl_cpw", entry["metrics"])
        assert r["verdict"] == entry["verdict"]
        assert entry["source"]["kind"] == "openems_real_run"
        assert entry["source"]["cache"] is False
        assert entry["source"]["solve_timeout_s"] == 36000
        assert entry["params"]["w_msl_mm"] == 1.1134
        assert entry["params"]["w_cpw_mm"] == 0.849
        assert entry["params"]["gap_cpw_mm"] == 0.2
        assert entry["metrics"]["wall_s"] >= 0

    def test_refs_computed_not_hardcoded(self):
        # 参考值运行时经闭式计算：与内核同式重算一致（允许 1e-4 舍入差）
        entry = _load()["anchors"]["msl_cpw"]
        from rfauto.core.calculators import _cpwg_ri
        from rfauto.core.synthesis import Stackup, forward_z0

        stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
        _, er_eff1 = forward_z0(entry["params"]["w_msl_mm"], 2.5, stackup)
        er_eff2, _ = _cpwg_ri(entry["params"]["w_cpw_mm"],
                              entry["params"]["gap_cpw_mm"],
                              stackup.thickness_mm, stackup.epsilon_r)
        assert entry["refs"]["er_eff1_hj_closed_form"] == pytest.approx(
            float(er_eff1), abs=1e-4)
        assert entry["refs"]["er_eff2_cpwg_closed_form"] == pytest.approx(
            float(er_eff2), abs=1e-4)
        # 复算 δ 与记录一致
        assert entry["metrics"]["delta_eps1_pct"] == pytest.approx(
            round((entry["metrics"]["eps_eff1"]
                   / float(er_eff1) - 1) * 100, 3), abs=0.01)


class TestMslCpwRecalibration20260915b:
    """无源上界重标定链条钉子：历史 PASS 如实改判 FAIL（#122 不凑绿）。"""

    def test_verdict_flipped_to_fail_by_passive_upper_bound(self):
        entry = _load()["anchors"]["msl_cpw"]
        assert entry["verdict"] == "FAIL"
        assert entry["gate_flags"]["passive_ok"] is False
        assert entry["gate_flags"]["thru_ok"] is False
        # 其余三门仍 True：改判只因无源上界，不牵连 β 双锚与匹配门
        assert all(entry["gate_flags"][k] for k in ("beta1_ok", "beta2_ok",
                                                    "match_ok"))
        assert "无源上界超门" in entry["reason"]

    def test_band_max_pinned_from_archive_recompute(self):
        # runs/benchmark/msl_cpw_m0.4/sparams.csv 离线复算：带内 max 1.2902
        # @2.25GHz；mean 1.0296 保留（旧门口径数值不改，只补统计量）
        m = _load()["anchors"]["msl_cpw"]["metrics"]
        assert m["s21_lin_band_max"] == 1.2902
        assert m["s21_lin_mean"] == 1.0296
        assert m["s21_lin_mean"] >= ab.CPW_S21_MIN_LIN      # 旧下侧门会放行
        assert m["s21_lin_band_max"] > ab.CPW_S21_MAX_LIN   # 现上侧门拦下

    def test_old_verdict_kept_in_provenance_not_erased(self):
        entry = _load()["anchors"]["msl_cpw"]
        old = entry["provenance"]["old_gate_verdict"]
        assert old["verdict"] == "PASS" and old["gate_version"] == "20260915"
        assert old["path"] == "runs/benchmark/msl_cpw_engine_benchmark.json"
        assert "无源上界" in entry["provenance"]["gate_calibration"]

    def test_top_level_recalibration_block(self):
        rc = _load()["provenance"]["recalibration_20260915b"]
        assert "msl_cpw" in rc["scope"]
        assert "PASS" in rc["msl_cpw_verdict_change"]
        assert "FAIL" in rc["msl_cpw_verdict_change"]
        assert any("msl_cpw_renorm" in e for e in rc["evidence"])
        # harness 尚未传带内 max 的 followUp 必须入册（不可静默）
        assert "s21_lin_band_max" in rc["harness_followup"]
        # followUp 已闭环（2026-09-18）：ingest_msl_cpw 同批补传
        # 带内 max + criteria/gate_flags 同步（与 via 20260918a 同款钉）
        assert "已闭环" in rc["harness_followup"]

    def test_offline_anchors_unaffected_by_recalibration(self):
        # 20260915b 只动 msl_cpw：四离线锚判定不变；passive_ok 门旗系后续
        # 20260918a（scope 仅 via）补入，msl_cpw 重标定时点四离线锚均无
        anchors = _load()["anchors"]
        for name in OFFLINE_ANCHORS:
            assert anchors[name]["gate_version"] == ab.GATE_VERSION
            assert anchors[name]["verdict"] == "PASS"
        for name in ("ratrace", "atten_pi", "atten_t"):
            assert "passive_ok" not in anchors[name]["gate_flags"]


class TestViaRecalibration20260918a:
    """无源上界重标定链条钉子（与 msl_cpw 20260915b 同类缺陷的预防性延伸）。

    与 msl_cpw 20260915b 的差异：via 归档 401 点带内 max 0.9503 全部
    ≤1.02，判定零翻转——收紧为预防性（堵住未来非物理放行），不翻任何
    历史案（#122 不凑绿：如实记录"零翻转"而非夸大成改判）。
    """

    def test_verdict_unchanged_but_passive_flag_added(self):
        entry = _load()["anchors"]["via"]
        assert entry["verdict"] == "PASS"
        assert entry["gate_flags"]["passive_ok"] is True
        assert entry["gate_flags"]["thru_ok"] is True
        assert all(entry["gate_flags"][k] for k in ("beta1_ok", "match_ok",
                                                    "recip_ok"))
        assert entry["reason"] == ""

    def test_band_max_pinned_from_archive_recompute(self):
        m = _load()["anchors"]["via"]["metrics"]
        assert m["s21_lin_band_max"] == 0.9503
        assert m["s21_lin_mean"] == 0.944
        assert m["s21_lin_mean"] >= ab.VIA_S21_MIN_LIN      # 旧下侧门本就过
        assert m["s21_lin_band_max"] <= ab.VIA_S21_MAX_LIN  # 新上侧门也过

    def test_kernel_replay_self_consistent(self):
        entry = _load()["anchors"]["via"]
        r = _replay("via", entry["metrics"])
        assert r["verdict"] == entry["verdict"]
        assert r["passive_ok"] is True and r["thru_ok"] is True

    def test_top_level_recalibration_block(self):
        rc = _load()["provenance"]["recalibration_20260918a"]
        assert "via" in rc["scope"]
        assert "PASS" in rc["via_verdict_change"]
        assert "零翻转" in rc["via_verdict_change"]
        assert any("via_smoke/pt3" in e for e in rc["evidence"])
        # harness 同批补传带内 max——不得再现 20260915b 式悬空 followUp
        assert "已同批补传" in rc["harness_followup"]

    def test_gate_calibration_provenance_records_new_bound(self):
        calib = _load()["anchors"]["via"]["provenance"]["gate_calibration"]
        assert "20260918a" in calib and "无源上界" in calib
        assert "0.9503" in calib


class TestMlineEvidenceUntouched:
    """新时点只新增不覆写 mline golden。"""

    def test_mline_golden_still_present(self):
        assert MLINE_GOLDEN.exists(), "mline 证据 golden 被误删/移动"

    def test_mline_golden_content_unchanged(self):
        data = json.loads(MLINE_GOLDEN.read_text(encoding="utf-8"))
        assert data["kind"] == "engine_benchmark_mline_rescan"
        assert data["result"]["verdict"] == "PASS"
        assert data["result"]["eps_hj_closed_form"] == 2.85264
        assert data["pre_rescan_189"]["finest_eps_eff"] == 2.8813
