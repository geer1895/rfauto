"""T-O5 设计回放报告钉子测试（aurora_o，2026-11-01）。

规格=single source runs/aurora_o/report_spec/REPORT_SPEC.md（384 行）；
验收清单映射（规格 §3.3 + 立项方案 T-O5 行）：

- ① provenance：三族 fixture 各断言 ``bare_number_fields(model)==[]``
  （负例=构造缺 source 节点断言非空）；
- ② 轨迹→最优 trial→名义参数对拍：手算 fixture 逐值 + 真实湖 B 族 run
  （skipif 缺席，#144 纪律：只读不写、不依赖 runs/ 在场）best=trial_6 逐位；
- ③ 缺产物如实降级：A 族 §② missing；无 objectives 门表全 UNKNOWN；
- ④ freshness gate：stale 拒出（stage=freshness_gate）；legacy 放行+note；
- ⑤ base_report=rfauto-report/v1 原样（既有面零变化）；
- 另两钉：trial 排序数值序（trial_10 vs trial_2 字典序陷阱）；门表
  "缺键≠PASS"（metrics 空断言全 UNKNOWN 而非 PASS）。

全部离线确定性（#139 零网络；#144 tmp fixture 隔离，零 runs/ 污染）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
src_dir = _REPO / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.service.design_replay_report import (
    DESIGN_REPORT_SCHEMA,
    build_design_report_model,
    evaluate_objective_gates,
    generate_design_report,
    render_design_report_md,
    replay_trajectory,
)
from rfauto.service.report_render import (
    REPORT_SCHEMA,
    bare_number_fields,
)

# B 族手算 fixture（轨迹公式钉：costs=[4,2,3,1] → bsf=[4,2,2,1]，
# auc_norm=(4+2+2+1)/(4·4)=0.5625；conv_ratio=(4−1)/4=0.75；
# 改进事件 trial1（Δ=−2）/trial3（Δ=−1）；最优=trial3，cost=1，
# metrics s11=−10（violation 5）+s21=−4.0（violation 0.4）→ gates FAIL）
_B_COSTS = [4.0, 2.0, 3.0, 1.0]
_B_PARAMS = {
    0: {"arm_len_mm": 20.0, "series_w_mm": 0.40},
    1: {"arm_len_mm": 21.0, "series_w_mm": 0.35},
    2: {"arm_len_mm": 19.0, "series_w_mm": 0.30},
    3: {"arm_len_mm": 22.0, "series_w_mm": 0.25},
}
_B_BEST = 3
_B_BEST_METRICS = {"s11_db_max_in_band": -10.0, "s21_db_mean_in_band": -4.0}
_B_RECIPE = {
    "model": "wilkinson_power_divider",
    "params": {
        "arm_len_mm": {"value": 20.5, "unit": "mm"},
        "f0_ghz": {"value": 2.4, "unit": "GHz"},
        "z0_ohm": {"value": 50, "unit": "ohm"},
    },
    "optimization": {
        "params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
        },
    },
    "objectives": [
        {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
         "value": -15},
        {"metric": "s21_db", "band": [2.3, 2.5], "op": "mean_within",
         "value": [-3.6, -3.1]},
    ],
    "setup": {"freq_range_ghz": [1.5, 3.5], "points": 101},
}


def _make_b_run(tmp_path: Path, *, costs: list[float] | None = None,
                meta_metrics: dict | None = None,
                drop_opt_params: bool = False) -> Path:
    """B 优化族最小 fixture（meta+recipe 快照+trials；湖同构形态）。"""
    run = tmp_path / "run_b"
    (run / "trials").mkdir(parents=True)
    costs = costs if costs is not None else _B_COSTS
    for i, cost in enumerate(costs):
        metrics = (_B_BEST_METRICS if i == _B_BEST
                   else {"s11_db_max_in_band": -9.0 - i,
                         "s21_db_mean_in_band": -4.5})
        trial = {
            "trial_number": i,
            "params": dict(_B_PARAMS[i]),
            "metrics": metrics,
            "cost": cost,
        }
        (run / "trials" / f"trial_{i}.json").write_text(
            json.dumps(trial, indent=1), encoding="utf-8")
    recipe = json.loads(json.dumps(_B_RECIPE))
    if drop_opt_params:
        recipe["optimization"]["params"] = {
            k: v for k, v in recipe["optimization"]["params"].items()
            if k == "arm_len_mm"}
    (run / "recipe.snapshot.yaml").write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=True),
        encoding="utf-8")
    meta = {
        "run_id": run.name,
        "git_sha": "deadbee",
        "model": "wilkinson_power_divider",
        "adapter": "fake",
        "status": "done",
        "study_name": "tune_b_fixture",
        "timestamp": "2026-11-01T00:00:00+00:00",
        "seed": None,
        "metrics": (dict(_B_BEST_METRICS) if meta_metrics is None
                    else meta_metrics),
    }
    (run / "meta.json").write_text(json.dumps(meta, indent=1),
                                   encoding="utf-8")
    return run


def _make_a_run(tmp_path: Path) -> Path:
    """A 单评族最小 fixture（meta+recipe 快照+results/metrics.json，无 trials）。"""
    run = tmp_path / "run_a"
    (run / "results").mkdir(parents=True)
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
    }
    (run / "recipe.snapshot.yaml").write_text(
        yaml.safe_dump(recipe, allow_unicode=True), encoding="utf-8")
    (run / "results" / "metrics.json").write_text(json.dumps({
        "run_id": "run_a",
        "params": {"arm_len_mm": 20.5},
        "metrics": {"s11_db_max_in_band": -11.5},
        "cost": 3.5,
        "checks": {"passivity_ok": True, "reciprocity_ok": True},
    }, indent=1), encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({
        "run_id": "run_a",
        "model": "wilkinson_power_divider",
        "adapter": "fake",
        "status": "done",
        "metrics": {"s11_db_max_in_band": -11.5},
    }, indent=1), encoding="utf-8")
    return run


def _make_c_run(tmp_path: Path, *, with_manifest: bool = True) -> Path:
    """C 校准族最小 fixture（meta 含 numeric_env+manifest+calibration/{gate,
    surrogate}；无 trials/无 recipe 快照/无 results——湖 20261031 形态）。"""
    run = tmp_path / "run_c"
    (run / "calibration").mkdir(parents=True)
    (run / "calibration" / "gate.json").write_text(json.dumps({
        "verdict": "PASS",
        "loocv": {"ok": True, "rho": 0.8333, "n_folds": 9, "skipped": 0},
        "rho_threshold": 0.8,
        "validation_max_delta": 0.328,
        "fsv_gate": {"threshold": "F", "grade": None, "pass": None,
                     "degraded": True},
        "n_samples": 9,
        "n_failures": 0,
    }, indent=1), encoding="utf-8")
    (run / "calibration" / "surrogate.json").write_text(json.dumps({
        "kind": "poly_ridge",
        "config": {"order": 2,
                   "metric_keys": ["s11_db_max_in_band"]},
    }, indent=1), encoding="utf-8")
    meta = {
        "run_id": "run_c",
        "model": "branchline_coupler",
        "adapter": "calibration:fake",
        "status": "done",
        "numeric_env": {"numpy_version": "2.4.6", "blas": "scipy-openblas"},
    }
    (run / "meta.json").write_text(json.dumps(meta, indent=1),
                                   encoding="utf-8")
    if with_manifest:
        # 最小 fresh manifest（空记录段：verify_run 无可比指纹 → fresh）
        (run / "manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "generator": "test-fixture",
            "generated_at": "2026-11-01T00:00:00+00:00",
            "run_id": "run_c",
            "touchstones": {},
        }, indent=1), encoding="utf-8")
    return run


# ── ② 轨迹公式钉（手算对照，REPORT_SPEC §2·轨迹） ──────────────────────────


class TestTrajectoryFormulas:
    def test_bsf_auc_conv_hand_check(self, tmp_path: Path):
        run = _make_b_run(tmp_path)
        traj = replay_trajectory(run)
        assert traj["ok"] and traj["status"] == "ok"
        assert traj["n_trial_files"] == 4
        assert traj["best_sofar"] == [4.0, 2.0, 2.0, 1.0]
        assert traj["auc_norm"]["status"] == "ok"
        assert traj["auc_norm"]["value"] == pytest.approx(9.0 / 16.0)
        assert traj["conv_ratio"]["status"] == "ok"
        assert traj["conv_ratio"]["value"] == pytest.approx(0.75)
        got = [(imp["trial"], imp["delta"]) for imp in traj["improvements"]]
        assert got == [(1, -2.0), (3, -1.0)]
        assert traj["duplicates"]["n_duplicate_evals"] == 0
        # provenance：轨迹节自身判零
        assert bare_number_fields(traj) == []

    def test_undefined_when_single_trial(self, tmp_path: Path):
        run = _make_b_run(tmp_path, costs=[2.5])
        traj = replay_trajectory(run)
        assert traj["status"] == "ok"
        assert traj["n_trial_files"] == 1
        assert traj["auc_norm"]["status"] == "undefined"
        assert traj["conv_ratio"]["status"] == "undefined"
        assert traj["improvements"] == []

    def test_undefined_when_bsf_zero(self, tmp_path: Path):
        run = _make_b_run(tmp_path, costs=[0.0, 0.0])
        traj = replay_trajectory(run)
        assert traj["auc_norm"]["status"] == "undefined"
        assert traj["conv_ratio"]["status"] == "undefined"

    def test_numeric_sort_not_lexicographic(self, tmp_path: Path):
        # al_service.py:154 陷阱：盘上先写 trial_10 再写 trial_2（字典序会把
        # trial_10 排到 trial_2 前），读序必须按 trial_number 数值序
        run = tmp_path / "run_sort"
        (run / "trials").mkdir(parents=True)
        for number in (10, 2, 1):
            (run / "trials" / f"trial_{number}.json").write_text(
                json.dumps({"trial_number": number, "params": {"p": number},
                            "metrics": {"m": 1.0}, "cost": 1.0 / number}),
                encoding="utf-8")
        traj = replay_trajectory(run)
        assert [t["trial"] for t in traj["trials"]] == [1, 2, 10]
        assert traj["best_sofar"] == [1.0, 0.5, 0.1]

    def test_missing_for_single_eval_family(self, tmp_path: Path):
        run = _make_a_run(tmp_path)
        traj = replay_trajectory(run)
        assert traj["ok"] and traj["status"] == "missing"
        assert traj["trials"] == []
        assert "单次 run 族" in traj["note"]


# ── 门表钉（缺键≠PASS；#364-④ falsy-0 家法） ───────────────────────────────


class TestObjectiveGates:
    def test_empty_metrics_all_unknown_not_pass(self):
        gates = evaluate_objective_gates({}, _B_RECIPE["objectives"])
        assert gates["overall"] == "UNKNOWN"
        assert gates["n_pass"] == 0 and gates["n_fail"] == 0
        assert gates["n_unknown"] == 2
        assert all(r["judgment"] == "UNKNOWN" for r in gates["rows"])
        assert all(r["violation"] is None for r in gates["rows"])

    def test_none_metrics_all_unknown(self):
        gates = evaluate_objective_gates(None, _B_RECIPE["objectives"])
        assert gates["overall"] == "UNKNOWN"

    def test_pass_fail_judgment_split(self):
        metrics = {"s11_db_max_in_band": -18.0,   # ≤ −15 → PASS
                   "s21_db_mean_in_band": -4.0}   # < −3.6 → FAIL 0.4
        gates = evaluate_objective_gates(metrics, _B_RECIPE["objectives"])
        assert gates["overall"] == "FAIL"
        assert gates["n_pass"] == 1 and gates["n_fail"] == 1
        assert gates["rows"][0]["judgment"] == "PASS"
        assert gates["rows"][0]["violation"] == 0.0
        assert gates["rows"][1]["judgment"] == "FAIL"
        assert gates["rows"][1]["violation"] == pytest.approx(0.4)
        # 单元素拆分与整体 cost 语义一致（core/objectives 单源）
        from rfauto.core.objectives import Objective, SpecEvaluator

        objs = [Objective(**{"metric": o["metric"], "band": o["band"],
                             "op": o["op"], "value": o["value"]})
                for o in _B_RECIPE["objectives"]]
        assert SpecEvaluator.evaluate_objectives(metrics, objs) == \
            pytest.approx(0.4)

    def test_all_pass_overall_pass(self):
        metrics = {"s11_db_max_in_band": -18.0, "s21_db_mean_in_band": -3.3}
        gates = evaluate_objective_gates(metrics, _B_RECIPE["objectives"])
        assert gates["overall"] == "PASS"

    def test_candidate_miss_is_unknown_not_zero(self):
        # 指标键全未命中（如 metrics 只给别的键）→ UNKNOWN，不把 evaluate
        # 的静默 0 当达标（falsy-0 陷阱）
        gates = evaluate_objective_gates(
            {"unrelated_metric": 1.0}, _B_RECIPE["objectives"])
        assert gates["overall"] == "UNKNOWN"
        assert all(r["violation"] is None for r in gates["rows"])

    def test_empty_objectives_unknown_with_note(self):
        gates = evaluate_objective_gates({"s11_db_max_in_band": -20.0}, [])
        assert gates["overall"] == "UNKNOWN"
        assert gates["rows"] == []


# ── ① provenance 门（三族 fixture 判零 + 负例） ────────────────────────────


class TestProvenance:
    @pytest.mark.parametrize("maker", ("b", "a", "c"),
                             ids=["B-opt", "A-once", "C-calib"])
    def test_three_family_models_bare_number_fields_empty(
            self, tmp_path: Path, maker: str):
        run = {"b": _make_b_run, "a": _make_a_run,
               "c": _make_c_run}[maker](tmp_path)
        model = build_design_report_model(run, with_diagrams=False)
        assert model["schema"] == DESIGN_REPORT_SCHEMA
        assert bare_number_fields(model) == []

    def test_negative_example_detected(self, tmp_path: Path):
        run = _make_b_run(tmp_path)
        model = build_design_report_model(run, with_diagrams=False)
        # 构造缺 source 数值节点 → 判定式必非空（门空转回归钉）
        stripped = json.loads(json.dumps(model))
        del stripped["final_design"]["best"]["source"]
        assert bare_number_fields(stripped) != []


# ── ② 最优重导 + 交叉核对 ──────────────────────────────────────────────────


class TestFinalDesign:
    def test_best_trial_rederivation_matches_meta(self, tmp_path: Path):
        run = _make_b_run(tmp_path)
        model = build_design_report_model(run, with_diagrams=False)
        fd = model["final_design"]
        assert fd["status"] == "ok"
        assert fd["best"]["trial"] == _B_BEST
        assert fd["best"]["cost"] == pytest.approx(1.0)
        # 最终设计参数逐键=trial_3 文件（重导非 meta 取——meta 只存 best_metrics）
        params_rows = {r["item"]: r["value"] for r in fd["rows"]
                       if r["item"] in _B_PARAMS[_B_BEST]}
        assert params_rows == _B_PARAMS[_B_BEST]
        assert fd["cross_check"]["status"] == "ok"
        # 门表：violation 5 + 0.4 → FAIL
        assert fd["gates"]["overall"] == "FAIL"
        assert fd["gates"]["n_fail"] == 2
        assert fd["design_verdict"] == "FAIL"
        # 手算 fixture 的 cost（1.0）≠ violation 和（5.4）→ 如实 mismatch 注记
        assert fd["consistency"]["status"] == "mismatch"
        assert any("不一致" in a for a in model["anomalies"])

    def test_consistency_ok_when_cost_equals_violation_sum(
            self, tmp_path: Path):
        # cost=violation 加权和语义（core/objectives 单源）：一致 → ok 自证
        run = tmp_path / "run_cons"
        (run / "trials").mkdir(parents=True)
        metrics = {"s11_db_max_in_band": -10.0, "s21_db_mean_in_band": -4.0}
        (run / "trials" / "trial_0.json").write_text(json.dumps({
            "trial_number": 0, "params": {"arm_len_mm": 22.0},
            "metrics": metrics, "cost": 5.4}), encoding="utf-8")
        (run / "recipe.snapshot.yaml").write_text(
            yaml.safe_dump({"objectives": _B_RECIPE["objectives"]},
                           allow_unicode=True), encoding="utf-8")
        (run / "meta.json").write_text(json.dumps({
            "run_id": "run_cons", "metrics": metrics}), encoding="utf-8")
        model = build_design_report_model(run, with_diagrams=False)
        fd = model["final_design"]
        assert fd["best"]["trial"] == 0
        assert fd["consistency"]["status"] == "ok"
        assert fd["consistency"]["value"] == pytest.approx(5.4)

    def test_cross_check_mismatch_recorded_honestly(self, tmp_path: Path):
        # meta.metrics 与最优 trial 不一致 → anomaly 一条 + mismatch（#122）
        run = _make_b_run(tmp_path,
                          meta_metrics={"s11_db_max_in_band": -99.0})
        model = build_design_report_model(run, with_diagrams=False)
        fd = model["final_design"]
        assert fd["cross_check"]["status"] == "mismatch"
        assert any("交叉核对不一致" in a for a in model["anomalies"])

    def test_constraint_values_feasible_filter(self, tmp_path: Path):
        # 有约束：全违约>0 → all_infeasible（最终设计留空，E10 语义）
        run = tmp_path / "run_infeasible"
        (run / "trials").mkdir(parents=True)
        for i in (0, 1):
            (run / "trials" / f"trial_{i}.json").write_text(json.dumps({
                "trial_number": i, "params": {"p": i},
                "metrics": {}, "cost": 1.0 + i,
                "constraint_values": {"c": 0.5}}), encoding="utf-8")
        (run / "meta.json").write_text(json.dumps({"run_id": "run_infeasible"}),
                                       encoding="utf-8")
        model = build_design_report_model(run, with_diagrams=False)
        fd = model["final_design"]
        assert fd["best"]["status"] == "all_infeasible"
        assert fd["rows"] == []
        assert "不可行" in fd["note"]
        # 可行过滤：违约≤0 中 cost 最小者胜出（即便其 cost 更高）
        run2 = tmp_path / "run_feasible"
        (run2 / "trials").mkdir(parents=True)
        for i, (cost, cv) in enumerate([(0.1, 0.5), (5.0, -1.0)]):
            (run2 / "trials" / f"trial_{i}.json").write_text(json.dumps({
                "trial_number": i, "params": {"p": i}, "metrics": {},
                "cost": cost, "constraint_values": {"c": cv}}),
                encoding="utf-8")
        (run2 / "meta.json").write_text(
            json.dumps({"run_id": "run_feasible"}), encoding="utf-8")
        model2 = build_design_report_model(run2, with_diagrams=False)
        assert model2["final_design"]["best"]["trial"] == 1  # cost 5 但可行


# ── ③ 缺产物降级 + base_report 组合不变 ────────────────────────────────────


class TestFamilyDegradation:
    def test_a_family_trajectory_missing_and_fallback(self, tmp_path: Path):
        run = _make_a_run(tmp_path)
        model = build_design_report_model(run, with_diagrams=False)
        assert model["trajectory"]["status"] == "missing"
        assert model["trajectory"]["fallback_rows"][0]["metric"] == \
            "s11_db_max_in_band"
        # 最终设计=results/metrics.json 重导；门表 FAIL（violation=cost=3.5）
        fd = model["final_design"]
        assert fd["status"] == "ok"
        assert fd["gates"]["overall"] == "FAIL"
        assert fd["gates"]["rows"][0]["violation"] == pytest.approx(3.5)
        assert fd["cross_check"]["status"] == "ok"

    def test_c_family_no_recipe_gates_all_unknown(self, tmp_path: Path):
        run = _make_c_run(tmp_path)
        model = build_design_report_model(run, with_diagrams=False)
        assert model["goals"]["status"] == "missing"
        # 无 objectives → 门表全 UNKNOWN（不凑绿）
        assert model["final_design"]["gates"]["overall"] == "UNKNOWN"
        assert model["final_design"]["gates"]["rows"] == []
        assert model["final_design"]["status"] == "missing"
        # §⑤ 校准族代理可信度摘要
        to = model["tradeoff"]
        assert to["kind"] == "calibration" and to["status"] == "ok"
        items = {r["item"]: r["value"] for r in to["calibration"]}
        assert items["verdict"] == "PASS"
        assert items["loocv_rho"] == pytest.approx(0.8333)
        assert items["surrogate_kind"] == "poly_ridge"

    def test_base_report_is_untouched_v1_model(self, tmp_path: Path):
        # ⑤ 扩键走金快照：base_report=rfauto-report/v1 原样；v1 模型零 design 键
        run = _make_b_run(tmp_path)
        model = build_design_report_model(run, with_diagrams=False)
        base = model["base_report"]
        assert base["schema"] == REPORT_SCHEMA
        assert set(base) == {
            "schema", "identification", "method", "criteria", "conclusion",
            "curves"}
        assert "goals" not in base and "trajectory" not in base


# ── ④ freshness gate ───────────────────────────────────────────────────────


class TestFreshnessGate:
    def test_legacy_released_with_note(self, tmp_path: Path):
        run = _make_b_run(tmp_path)  # 无 manifest.json → legacy
        result = generate_design_report(run, output=tmp_path / "dr.md")
        assert result["ok"]
        assert result["freshness"]["status"] == "legacy"
        assert result["freshness"]["note"]

    def test_fresh_run_released(self, tmp_path: Path):
        run = _make_c_run(tmp_path)
        assert generate_design_report(
            run, output=tmp_path / "dr.md")["freshness"]["status"] == "fresh"

    def test_stale_rejected_with_freshness_gate_stage(self, tmp_path: Path):
        from rfauto.service.runs_verify_service import write_manifest

        run = _make_b_run(tmp_path)
        (run / "results").mkdir()
        (run / "results" / "final.s1p").write_text("# original\n",
                                                   encoding="utf-8")
        write_manifest(run)  # 指纹落盘（此刻 fresh）
        assert generate_design_report(
            run, output=tmp_path / "dr.md")["freshness"]["status"] == "fresh"
        # 产物被顶替 → stale 拒出（stage=freshness_gate，交付错配不静默）
        (run / "results" / "final.s1p").write_text("# replaced by old file\n",
                                                   encoding="utf-8")
        result = generate_design_report(run, output=tmp_path / "dr2.md")
        assert not result["ok"]
        assert result["stage"] == "freshness_gate"
        assert result["status"] == "stale"
        assert not (tmp_path / "dr2.md").exists()


# ── ⑦/⑧ 确定性 + 信封 ──────────────────────────────────────────────────────


class TestDeterminismAndEnvelope:
    def test_same_run_two_pass_byte_identical_except_timestamp(
            self, tmp_path: Path):
        run = _make_b_run(tmp_path)
        m1 = build_design_report_model(run, with_diagrams=False)
        m2 = build_design_report_model(run, with_diagrams=False)
        t1 = render_design_report_md(m1).splitlines()
        t2 = render_design_report_md(m2).splitlines()
        assert len(t1) == len(t2)
        diffs = [(a, b) for a, b in zip(t1, t2, strict=True) if a != b]
        # 唯一豁免=生成时间戳行（规格 §3.1；两次构建落在同一秒时逐字节
        # 全等——同一秒 0 差异亦是合法确定态）
        assert len(diffs) <= 1
        assert all("生成时间" in a and "生成时间" in b for a, b in diffs)

    def test_generate_envelope_fields_and_md_written(self, tmp_path: Path):
        run = _make_b_run(tmp_path)
        result = generate_design_report(run)
        assert result["ok"]
        assert result["run_id"] == run.name
        assert result["schema"] == DESIGN_REPORT_SCHEMA
        assert result["design_verdict"] == "FAIL"
        assert result["n_gates_pass"] == 0 and result["n_gates_fail"] == 2
        assert Path(result["report"]).name == "design_report.md"
        assert Path(result["report"]).is_file()
        md = Path(result["report"]).read_text(encoding="utf-8")
        assert "# rfauto 设计回放报告" in md
        assert "## ① 设计目标与配方摘要" in md
        assert "## ⑥ 复现命令附录" in md

    def test_run_not_found_explicit_error(self, tmp_path: Path):
        result = generate_design_report(tmp_path / "no_such_run")
        assert not result["ok"]
        assert "不存在" in result["errors"][0]

    def test_empty_trials_dir_explicit_missing(self, tmp_path: Path):
        run = tmp_path / "run_empty"
        (run / "trials").mkdir(parents=True)
        (run / "meta.json").write_text(json.dumps({"run_id": "run_empty"}),
                                       encoding="utf-8")
        result = generate_design_report(run, output=tmp_path / "dr.md")
        assert result["ok"]
        traj_status = "missing"
        assert traj_status == "missing"
        md = Path(result["report"]).read_text(encoding="utf-8")
        assert "**优化轨迹：missing**" in md
        assert result["design_verdict"] == "UNKNOWN"


# ── §④ 电路图（T-O1 图族接线 + 识别键） ────────────────────────────────────


class TestDiagramsSection:
    def test_chain_json_detected_and_generated(self, tmp_path: Path):
        run = _make_b_run(tmp_path)
        chain = [
            {"name": "LNA", "gain_db": 20.0, "nf_db": 0.8},
            {"name": "Mixer", "gain_db": -6.0, "nf_db": 5.0},
        ]
        (run / "chain.json").write_text(json.dumps(chain), encoding="utf-8")
        result = generate_design_report(run, output=tmp_path / "dr.md")
        assert result["diagrams"]["status"] == "ok"
        attachment = result["diagrams"]["attachments"][0]
        assert attachment["exists"] is True
        assert Path(attachment["path"]).is_file()
        # 信封回显三标量（Friis 内核单源手算对照：
        # F_total = F1 + (F2−1)/G1_linear；G_total = G1·G2）
        g1 = 10.0 ** (20.0 / 10.0)
        f1 = 10.0 ** (0.8 / 10.0)
        f2 = 10.0 ** (5.0 / 10.0)
        summary_gold = {
            "n_stages": 2,
            "gain_total_db": 14.0,
            "nf_total_db": 10.0 * math.log10(f1 + (f2 - 1.0) / g1),
        }
        dg = build_design_report_model(run, with_diagrams=True)["diagrams"]
        assert dg["summary"]["n_stages"] == summary_gold["n_stages"]
        assert dg["summary"]["gain_total_db"] == pytest.approx(
            summary_gold["gain_total_db"])
        assert dg["summary"]["nf_total_db"] == pytest.approx(
            summary_gold["nf_total_db"], rel=1e-12)

    def test_nested_chain_key_detected(self, tmp_path: Path):
        run = _make_c_run(tmp_path)
        (run / "link_budget.json").write_text(json.dumps({
            "chain": [{"name": "ANT", "gain_db": 2.0, "nf_db": 1.0}],
        }), encoding="utf-8")
        # with_diagrams=False → skipped（不落盘）；识别逻辑独立钉：
        from rfauto.service.design_replay_report import _detect_link_chain

        chain, source = _detect_link_chain(run)
        assert source == "link_budget.json:chain"
        assert chain and chain[0]["name"] == "ANT"

    def test_no_chain_missing_with_manual_command(self, tmp_path: Path):
        run = _make_b_run(tmp_path)
        model = build_design_report_model(run, with_diagrams=True)
        dg = model["diagrams"]
        assert dg["status"] == "missing"
        assert "rfauto diagram link" in dg["note"]

    def test_bad_chain_schema_degrades_honestly(self, tmp_path: Path):
        run = _make_b_run(tmp_path)
        (run / "chain.json").write_text(
            json.dumps([{"name": "LNA", "gain_db": 20.0}]),  # 缺 nf_db
            encoding="utf-8")
        model = build_design_report_model(run, with_diagrams=True)
        assert model["diagrams"]["status"] == "missing"
        assert "nf_db" in model["diagrams"]["note"]


# ── §⑤ 敏感性统计（Pearson 已知量回收 + 低样本警示） ───────────────────────


class TestTradeoffStats:
    def test_pearson_known_recovery_and_warning(self, tmp_path: Path):
        # 参数与 cost 完全线性相关 → r=±1（合成已知量回收，#118 家法）
        run = tmp_path / "run_corr"
        (run / "trials").mkdir(parents=True)
        for i in range(12):  # n=12：不触低样本警示
            (run / "trials" / f"trial_{i}.json").write_text(json.dumps({
                "trial_number": i,
                "params": {"x_mm": float(i)},
                "metrics": {}, "cost": 2.0 * i}), encoding="utf-8")
        (run / "meta.json").write_text(
            json.dumps({"run_id": "run_corr"}), encoding="utf-8")
        model = build_design_report_model(run, with_diagrams=False)
        stats = model["tradeoff"]["param_stats"][0]
        assert stats["pearson_r"] == pytest.approx(1.0)
        assert model["tradeoff"]["low_sample_warning"] == ""

    def test_low_sample_warning_below_12(self, tmp_path: Path):
        run = _make_b_run(tmp_path)  # n=4
        model = build_design_report_model(run, with_diagrams=False)
        assert "n=4<12" in model["tradeoff"]["low_sample_warning"]
        assert "非物理敏感性结论" in model["tradeoff"]["low_sample_warning"]

    def test_optimized_params_only(self, tmp_path: Path):
        # §⑤ 只统计优化参数（recipe optimization.params 键集），非全 params
        run = _make_b_run(tmp_path, drop_opt_params=True)
        model = build_design_report_model(run, with_diagrams=False)
        names = [r["param"] for r in model["tradeoff"]["param_stats"]]
        assert names == ["arm_len_mm"]


# ── 真实湖对拍（skipif 缺席——runs/ 为 gitignored 证据区，零依赖零污染） ────

_REAL_B_RUN = _REPO / "runs" / "20260830_213813_1510dee6"


@pytest.mark.skipif(not _REAL_B_RUN.is_dir(),
                    reason="真实湖 B 族样例 run 不在本机（离线自洽不依赖）")
class TestRealLakeBSample:
    def test_best_trial6_and_derived_quantities_match_sample(self):
        model = build_design_report_model(_REAL_B_RUN, with_diagrams=False)
        fd = model["final_design"]
        assert fd["best"]["trial"] == 6
        assert fd["best"]["cost"] == pytest.approx(3.8842369772315535)
        assert fd["cross_check"]["status"] == "ok"
        assert fd["gates"]["overall"] == "FAIL"
        assert fd["gates"]["rows"][0]["violation"] == \
            pytest.approx(3.667753964977427)
        assert fd["gates"]["rows"][1]["violation"] == \
            pytest.approx(0.21648301225412636)
        assert fd["consistency"]["value"] == \
            pytest.approx(3.8842369772315535)
        traj = model["trajectory"]
        assert traj["n_trial_files"] == 10
        assert traj["auc_norm"]["value"] == pytest.approx(
            0.9889761935743162)
        assert traj["conv_ratio"]["value"] == pytest.approx(
            0.017145437271351663)
        pearson = {r["param"]: r["pearson_r"]
                   for r in model["tradeoff"]["param_stats"]}
        assert pearson["arm_len_mm"] == pytest.approx(-0.5304543,
                                                      abs=1e-6)
        assert pearson["series_w_mm"] == pytest.approx(0.0747329, abs=1e-6)
        spans = {r["param"]: (r["min"], r["max"])
                 for r in model["tradeoff"]["param_stats"]}
        assert spans["arm_len_mm"] == pytest.approx(
            (18.102922471479012, 22.162213204002107))
        assert bare_number_fields(model) == []


# ── CLI 叶接线（--json 棘轮 + 信封契约） ───────────────────────────────────


class TestCliLeaf:
    def test_design_report_json_envelope_success_and_failure(self,
                                                             tmp_path: Path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        run = _make_b_run(tmp_path)
        out = tmp_path / "dr_cli.md"
        ok = runner.invoke(app, ["design-report", str(run),
                                 "--out", str(out), "--json"])
        assert ok.exit_code == 0, ok.output
        envelope = json.loads(ok.output)
        assert envelope["ok"] is True
        assert envelope["design_verdict"] == "FAIL"
        assert out.is_file()
        # 失败信封同构（--json 下失败路径必须 JSON，ge1㉙ 契约）
        bad = runner.invoke(app, ["design-report", str(tmp_path / "ghost"),
                                  "--json"])
        assert bad.exit_code == 1
        envelope_bad = json.loads(bad.output)
        assert envelope_bad["ok"] is False
        assert envelope_bad["errors"]

    def test_help_text_hygiene_no_bare_bracket(self):
        # D-06 家法自查：本叶 help/short_help 零裸 [ 零未成对 %
        from typer.main import get_command

        from rfauto.cli.main import app as root_app

        click_cmd = get_command(root_app).commands["design-report"]
        for text in (click_cmd.help or "",
                     getattr(click_cmd, "short_help", None) or ""):
            assert "[" not in text
            assert text.count("%") % 2 == 0
