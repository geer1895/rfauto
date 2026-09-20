"""WP3.9 MVP 基准换代战役 2026-09-16 证据 golden 钉子（离线零真机）。

背景：wp39-factory-verdict-next 真跑产物只落 runs/ 下同名战役目录
（runs/ 不入库），按 tests/golden/ 惯例（参照 mline_benchmark_rescan_20260913）
把汇总 summary.json 逐字节回录为 tests/golden/wp39_factory_verdict_next.json。
本文件离线回放四件事：
① 快照结构/schema/判据常量自检（防证据文件被误改坏）；
② 三组 judge 从快照内数据经唯一裁判 judge_problem_pair 重判——与快照记录的
   verdict/ratio/劣化逐位一致（mline_eps_factory、ratrace_null、决策输入
   native_vs_scripted）；
③ probe_eps 三网格 εeff 地貌过 mline_landscape_health_gate 重判——1.2mm PASS、
   2.0/3.0mm FAIL 与快照一致；
④ 关键数字钉死（带容差）：ratrace 换判据劣化 +1.85%（旧单频判据 +11.01%）、
   wall 比 1.347、HFSS/openEMS εeff 标定点跨引擎一致 ≤0.2%、工厂缓存全关。

证据源真跑命令见快照 provenance.commands（本测试不执行任何求解）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.service.wp39_benchmark import (
    BUDGET_DEFAULT,
    COST_MAX_DEGRADATION_PCT,
    WALLCLOCK_MAX_RATIO,
    judge_problem_pair,
    mline_landscape_health_gate,
)

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "golden" / "wp39_factory_verdict_next.json"


def _load() -> dict:
    assert GOLDEN.exists(), "证据 golden 缺失：tests/golden/wp39_factory_verdict_next.json"
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _result() -> dict:
    return _load()["result"]


class TestSnapshotShape:
    def test_kind_provenance_schema(self):
        data = _load()
        assert data["kind"] == "wp39_factory_verdict_next"
        assert data["captured_at"] == "2026-09-16"
        for key in ("live_result", "attribution", "commands", "kernel"):
            assert data["provenance"][key], f"provenance.{key} 缺失"
        assert len(data["provenance"]["commands"]) == 7
        result = data["result"]
        assert result["schema"] == "wp39_followup_verdict_next_summary_v1"
        assert set(result["problems"]) == {"mline_eps_factory", "ratrace_null"}
        assert result["summary"]["n_problems"] == 2

    def test_criteria_match_kernel_constants(self):
        crit = _result()["criteria"]
        assert crit["budget"] == BUDGET_DEFAULT == 25
        assert crit["wallclock_max_ratio"] == WALLCLOCK_MAX_RATIO == 0.5
        assert crit["cost_max_degradation_pct"] == COST_MAX_DEGRADATION_PCT == 5.0

    def test_verdict_strings_pinned(self):
        result = _result()
        assert result["summary"]["overall"] == "FAIL"
        assert result["summary"]["per_problem"] == {
            "mline_eps_factory": "FAIL", "ratrace_null": "FAIL"}
        # ratrace 换判据：cost 门过、只剩 wall 门（#224 算术锁死）
        rn = result["problems"]["ratrace_null"]
        assert rn["cost_ok"] is True and rn["wallclock_ok"] is False
        assert rn["budget_ok"] is True
        # mline 工厂：wall 与 cost 双超门（如实）
        mf = result["problems"]["mline_eps_factory"]
        assert mf["cost_ok"] is False and mf["wallclock_ok"] is False
        assert mf["budget_ok"] is True


class TestJudgeReplay:
    """快照内数据经唯一裁判重判 = 记录的 verdict（判据内核改动即显形）。"""

    @staticmethod
    def _same(recorded: dict, fresh: dict) -> None:
        for key in ("verdict", "budget_ok", "wallclock_ok", "cost_ok",
                    "wallclock_ratio", "degradation_pct", "metric_candidate",
                    "metric_baseline", "n_evals_candidate", "n_evals_baseline"):
            assert fresh[key] == recorded[key], (key, fresh[key], recorded[key])

    def test_ratrace_null_replay(self):
        result = _result()
        det = result["details"]["ratrace_null"]
        base = {"problem": "ratrace_null", **det["baseline"]}
        cand = {"problem": "ratrace_null", **det["candidate"]}
        self._same(result["problems"]["ratrace_null"],
                   judge_problem_pair(base, cand))

    def test_mline_eps_factory_replay(self):
        result = _result()
        base = {"problem": "mline_eps", **result["mline_eps_baseline"]}
        cand = result["details"]["mline_eps_factory"]["merged_candidate"]
        self._same(result["problems"]["mline_eps_factory"],
                   judge_problem_pair(base, cand))

    def test_native_vs_scripted_decision_input_replay(self):
        di = _result()["decision_inputs"]["native_vs_scripted_mline"]
        fresh = judge_problem_pair(
            {"problem": "mline", **di["scripted_baseline"]}, di["native_view"])
        self._same(di["verdict"], fresh)
        # 归档口径：原生 Optimetrics 9 评估 283.45s/−49.44dB vs scripted 9 评估
        # 296.88s/−38.05dB → wall 0.955>0.5 FAIL、cost 更优（劣化为负）
        assert fresh["verdict"] == "FAIL" and fresh["cost_ok"]
        assert fresh["wallclock_ratio"] == pytest.approx(0.9548, abs=1e-4)
        assert fresh["degradation_pct"] < 0.0


class TestProbeEpsGateReplay:
    def test_three_meshes_gate_replay(self):
        probe = _result()["probe_eps"]
        assert probe["verdict"] == "PASS"
        assert probe["chosen"]["mesh_mm"] == 1.2
        eps_hj = probe["eps_hj_nominal"]
        assert eps_hj == pytest.approx(2.85264, abs=2e-5)  # HJ 闭式副锚
        expected = {1.2: "PASS", 2.0: "FAIL", 3.0: "FAIL"}
        for cfg in probe["configs"]:
            gate = mline_landscape_health_gate(
                [0.85, 1.113, 1.4], cfg["eps_eff"],
                nominal_w=1.113, eps_hj=eps_hj)
            assert gate["verdict"] == cfg["gate"] == expected[cfg["mesh_mm"]]
            # 快照 eps_hj_nominal 六位小数回录（live 用全精度）→ Δ% 差 ~2e-6
            assert gate["nominal_delta_hj_pct"] == pytest.approx(
                cfg["nominal_delta_hj_pct"], abs=1e-4)
        # 1.2mm：εeff 随 w 单调增、名义点对 HJ +2.30%（≤3% 副锚）
        m12 = next(c for c in probe["configs"] if c["mesh_mm"] == 1.2)
        assert m12["eps_eff"] == pytest.approx([2.847363, 2.918116, 2.95923],
                                               abs=1e-6)
        # 粗网格 2.0/3.0mm：εeff<1 非物理（线未被解析），门如实判废且不省墙钟
        for cfg in probe["configs"]:
            if cfg["mesh_mm"] > 1.2:
                assert min(cfg["eps_eff"]) < 1.0


class TestKeyNumbers:
    def test_ratrace_null_degradation_narrowed(self):
        rn = _result()["problems"]["ratrace_null"]
        # 旧单频谷深判据 sbo 劣化 +11.01%（旧战役归档）→
        # 邻域能量判据 +1.85%（≤5% 门）；wall 比 1.347≈旧 1.30（#224）
        assert rn["degradation_pct"] == pytest.approx(1.8455, abs=1e-3)
        assert rn["degradation_pct"] < COST_MAX_DEGRADATION_PCT < 11.01
        assert rn["wallclock_ratio"] == pytest.approx(1.3471, abs=1e-3)
        assert rn["metric_baseline"] == pytest.approx(-48.469, abs=1e-2)
        assert rn["metric_candidate"] == pytest.approx(-47.575, abs=1e-2)
        assert (rn["n_evals_baseline"], rn["n_evals_candidate"]) == (17, 13)

    def test_mline_eps_factory_numbers(self):
        result = _result()
        mf = result["problems"]["mline_eps_factory"]
        assert mf["wallclock_ratio"] == pytest.approx(0.8434, abs=1e-3)
        assert mf["degradation_pct"] == pytest.approx(12.9067, abs=1e-3)
        assert mf["metric_baseline"] == pytest.approx(0.009236, abs=1e-5)
        assert mf["metric_candidate"] == pytest.approx(0.010428, abs=1e-5)
        fac = result["factory_eps"]
        assert fac["n_evals"] == 11 and fac["stop_reason"] == "stagnation"
        assert fac["cache_disabled"] is True and fac["cached_any"] is False
        assert fac["invalidated"] is None
        assert fac["best"]["params"]["w_mm"] == pytest.approx(1.1483, abs=1e-3)
        assert fac["wall_s"]["optimization_s"] == pytest.approx(1229.49, abs=0.1)

    def test_cross_engine_eps_target_consistency(self):
        result = _result()
        eps_openems = result["probe_eps"]["chosen"]["eps_eff_target"]
        eps_hfss = result["mline_eps_baseline"]["calibration"]["eps_eff_target"]
        # 同名义点 w=1.113：openEMS β 抽取 2.918116 vs HFSS S21 相位斜率 2.919815
        assert eps_openems == pytest.approx(2.918116, abs=1e-6)
        assert eps_hfss == pytest.approx(2.919815, abs=1e-5)
        assert abs(eps_hfss / eps_openems - 1.0) * 100 < 0.2
        # 两引擎对 HJ 2.85264 同向 +2.3%（副锚 3% 内）
        for eps in (eps_openems, eps_hfss):
            assert 2.0 < (eps / 2.85264 - 1.0) * 100 < 3.0

    def test_decision_inputs_not_in_overall(self):
        result = _result()
        di = result["decision_inputs"]
        assert di["optislang_mop"]["status"] == "NOT_RUN"
        assert di["optislang_mop"]["available"] is False
        assert "native_vs_scripted_mline" not in result["problems"]
        assert result["attribution"]["path"].endswith(
            "attribution_mline_s11_pseudofloor.md")
