"""阶段 7.5：仿真 CI 夜间回归测试（§10.20 补强⑫ 三源编排 + G14 成本表）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rfauto.pipeline.quota_guard import CostLedger


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # write_meta 的 pip freeze / git sha 子进程只影响 meta 内容与耗时，
    # 与本项报告无关——钉住以保持单测快且确定。
    monkeypatch.setattr("rfauto.infra.run_store._pip_freeze_sha", lambda: "test")
    monkeypatch.setattr("rfauto.infra.run_store._git_sha", lambda: "test")
    yield


def _recipe(model: str, arm: float) -> dict:
    return {
        "model": model,
        "params": {"arm_len_mm": {"value": arm},
                   "patch_len_mm": {"value": arm}},
        "setup": {"freq_range_ghz": [2.3, 2.5], "points": 41},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
    }


def _write_recipe(path: Path, model: str, arm: float) -> None:
    path.write_text(yaml.safe_dump(_recipe(model, arm)), encoding="utf-8")


@pytest.fixture
def recipes_dir(tmp_path):
    rd = tmp_path / "recipes"
    rd.mkdir()
    for i, (model, arm) in enumerate(
            (("wilkinson_power_divider", 20.5),
             ("patch_antenna", 40.0))):
        _write_recipe(rd / f"r{i}.yaml", model, arm)
    return str(rd)


@pytest.fixture
def recipes_3(tmp_path):
    rd = tmp_path / "recipes3"
    rd.mkdir()
    for i, (model, arm) in enumerate(
            (("wilkinson_power_divider", 20.5),
             ("patch_antenna", 40.0),
             ("wilkinson_power_divider", 25.0))):
        _write_recipe(rd / f"r{i}.yaml", model, arm)
    return str(rd)


@pytest.fixture
def fast_fake(monkeypatch):
    """把 fake 全量扫描替换为确定性桩：聚焦三源编排，避免重复 ~8s 真扫。

    真扫路径由 TestThreeSourceAggregation::test_real_fake_full_scan_* 与
    既有 TestNightlyRegression 覆盖。
    """
    def _stub(recipe_files, *, adapter, tolerance_db):
        entries = [{"recipe": p.name, "status": "done", "run_id": "inner-x",
                    "metrics": {"s11_db_max_in_band": -20.0},
                    "baseline": "missing"} for p in recipe_files]
        return entries, []

    monkeypatch.setattr("rfauto.service.sim_ci_service._scan_recipe_files", _stub)
    return _stub


class TestNightlyRegression:
    """既有 API（nightly_regression）回归——行为不变。"""

    def test_all_recipes_regress(self, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_regression

        r = nightly_regression(recipes_dir)
        assert r["ok"], r.get("errors")
        assert r["n_recipes"] == 2
        assert r["n_done"] == 2
        assert r["n_regressions"] == 0  # 首轮无历史基线
        assert all(e.get("baseline") == "missing" for e in r["entries"])
        report = Path(r["run_dir"]) / "sim_ci_report.json"
        assert report.exists()

    def test_deterministic_second_pass_clean(self, recipes_dir):
        """确定性内核：同批配方连跑两轮指标应完全一致 → 无回归。"""
        from rfauto.service.sim_ci_service import nightly_regression

        r1 = nightly_regression(recipes_dir)
        r2 = nightly_regression(recipes_dir)
        assert r1["ok"] and r2["ok"]
        assert r2["n_regressions"] == 0
        # 两轮同配方指标逐位一致（fake 通道确定性）
        m1 = {e["recipe"]: e["metrics"] for e in r1["entries"]
              if e.get("status") == "done"}
        m2 = {e["recipe"]: e["metrics"] for e in r2["entries"]
              if e.get("status") == "done"}
        assert m1 == m2

    def test_missing_dir_rejected(self, tmp_path):
        from rfauto.service.sim_ci_service import nightly_regression

        assert not nightly_regression(tmp_path / "nope")["ok"]


class TestThreeSourceAggregation:
    """三源聚合：fake 全量 / openEMS 冒烟抽检 / HFSS 周抽检。"""

    def test_real_fake_full_scan_runs_all_recipes(self, recipes_dir):
        """真扫（不注入桩）：fake 全量确实跑遍全部配方。"""
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(recipes_dir, run_id="real-fake")
        assert r["ok"], r.get("errors")
        assert r["n_recipes"] == 2
        assert r["sources"]["fake"]["status"] == "pass"
        assert r["sources"]["fake"]["n_done"] == 2
        assert r["sources"]["fake"]["n_failed"] == 0
        # 未注入 runner → 外部源 skipped 且未被调用
        assert r["sources"]["openems"]["status"] == "skipped"
        assert r["sources"]["openems"]["skipped_reason"] == "no_runner"
        assert r["sources"]["hfss"]["status"] == "skipped"
        assert r["sources"]["hfss"]["skipped_reason"] == "not_due"
        assert r["issues"] == []
        assert (Path(r["run_dir"]) / "sim_ci_report.md").exists()

    def test_all_three_sources_pass(self, fast_fake, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        def runner(_path):
            return {"ok": True}

        r = nightly_multisource_regression(
            recipes_dir, openems_sample=2, hfss_sample=2,
            openems_runner=runner, hfss_runner=runner, hfss_due=True,
            run_id="all-pass")
        assert r["ok"], r.get("errors")
        assert [r["sources"][s]["status"] for s in ("fake", "openems", "hfss")] == [
            "pass", "pass", "pass"]
        assert r["status"] == "pass"
        assert r["n_sources"] == 3
        assert r["n_sources_pass"] == 3
        assert r["n_sources_fail"] == 0
        assert r["n_sources_skipped"] == 0
        assert r["issues"] == []

    def test_openems_runner_invoked_for_each_sampled_recipe(self, fast_fake,
                                                            recipes_3):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        calls: list[str] = []

        def runner(path):
            calls.append(Path(path).name)
            return {"ok": True}

        r = nightly_multisource_regression(recipes_3, openems_sample=2,
                                           openems_runner=runner,
                                           run_id="oem-calls")
        src = r["sources"]["openems"]
        assert src["status"] == "pass"
        assert src["n_sampled"] == 2
        assert calls == src["sample"]
        assert calls == ["r0.yaml", "r2.yaml"]  # 等距抽检（两端点）
        assert src["n_pass"] == 2

    def test_sample_larger_than_recipes_is_clamped(self, fast_fake, recipes_3):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(
            recipes_3, openems_sample=99,
            openems_runner=lambda p: {"ok": True}, run_id="clamp")
        src = r["sources"]["openems"]
        assert src["requested_sample"] == 99
        assert src["n_sampled"] == 3
        assert src["sample"] == ["r0.yaml", "r1.yaml", "r2.yaml"]

    def test_hfss_weekly_due_invokes_runner(self, fast_fake, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        calls: list[str] = []

        def runner(path):
            calls.append(Path(path).name)
            return {"ok": True}

        r = nightly_multisource_regression(
            recipes_dir, hfss_sample=1, hfss_runner=runner, hfss_due=True,
            run_id="hfss-due")
        src = r["sources"]["hfss"]
        assert src["status"] == "pass"
        assert src["due"] is True
        assert src["n_sampled"] == 1
        assert calls == ["r0.yaml"]

    def test_hfss_not_due_skips_without_calling_runner(self, fast_fake,
                                                       recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        calls: list[str] = []
        r = nightly_multisource_regression(
            recipes_dir, hfss_sample=2,
            hfss_runner=lambda p: calls.append(p) or {"ok": True},
            hfss_due=False, run_id="hfss-not-due")
        src = r["sources"]["hfss"]
        assert src["status"] == "skipped"
        assert src["skipped_reason"] == "not_due"
        assert calls == []

    def test_hfss_due_with_zero_sample_skipped(self, fast_fake, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(
            recipes_dir, hfss_sample=0,
            hfss_runner=lambda p: {"ok": True}, hfss_due=True,
            run_id="hfss-zero")
        src = r["sources"]["hfss"]
        assert src["status"] == "skipped"
        assert src["skipped_reason"] == "sample_zero"

    def test_openems_without_runner_skipped(self, fast_fake, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(recipes_dir, openems_sample=3,
                                           run_id="oem-no-runner")
        src = r["sources"]["openems"]
        assert src["status"] == "skipped"
        assert src["skipped_reason"] == "no_runner"

    def test_even_sample_picks_deterministic_subset(self):
        from rfauto.service.sim_ci_service import _even_sample

        items = [f"r{i}.yaml" for i in range(5)]
        assert _even_sample(items, 2) == ["r0.yaml", "r4.yaml"]
        assert _even_sample(items, 3) == ["r0.yaml", "r2.yaml", "r4.yaml"]
        assert _even_sample(items, 1) == ["r0.yaml"]
        assert _even_sample(items, 5) == items
        assert _even_sample(items, 9) == items
        assert _even_sample(items, 0) == []
        assert _even_sample([], 3) == []


class TestIssueMinting:
    """红即 issue 化：红 → issue 非空；绿 → 空（防空转）。"""

    def test_external_failure_mints_issue_and_red_status(self, fast_fake,
                                                         recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(
            recipes_dir, openems_sample=2,
            openems_runner=lambda p: {"ok": False, "error": "solver exploded"},
            run_id="red-openems")
        assert r["status"] == "fail"
        src = r["sources"]["openems"]
        assert src["status"] == "fail"
        assert src["n_fail"] == 2
        assert [i["id"] for i in r["issues"]] == ["sim-ci-openems"]
        issue = r["issues"][0]
        assert issue["source"] == "openems"
        assert issue["severity"] == "error"
        assert issue["detail"]["failures"][0]["error"] == "solver exploded"
        on_disk = json.loads(Path(r["issue_file"]).read_text(encoding="utf-8"))
        assert on_disk == r["issues"]

    def test_runner_exception_recorded_as_failure(self, fast_fake, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        def boom(_path):
            raise RuntimeError("boom")

        r = nightly_multisource_regression(recipes_dir, openems_sample=1,
                                           openems_runner=boom, run_id="boom")
        src = r["sources"]["openems"]
        assert src["status"] == "fail"
        assert "RuntimeError: boom" in src["results"][0]["error"]

    def test_runner_non_dict_return_recorded_as_failure(self, fast_fake,
                                                        recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(recipes_dir, openems_sample=1,
                                           openems_runner=lambda p: 42,
                                           run_id="non-dict")
        src = r["sources"]["openems"]
        assert src["status"] == "fail"
        assert "非 dict" in src["results"][0]["error"]

    def test_fake_regression_mints_fake_issue(self, monkeypatch, recipes_dir):
        from rfauto.service import sim_ci_service as svc

        def _stub(recipe_files, *, adapter, tolerance_db):
            entries = [{"recipe": p.name, "status": "done", "metrics": {}}
                       for p in recipe_files]
            regs = [{"recipe": "r0.yaml", "metric": "s11_db_max_in_band",
                     "current": -10.0, "baseline": -20.0, "delta_db": 10.0,
                     "baseline_run_id": "base"}]
            return entries, regs

        monkeypatch.setattr(svc, "_scan_recipe_files", _stub)
        r = svc.nightly_multisource_regression(recipes_dir, run_id="red-fake")
        assert r["sources"]["fake"]["status"] == "fail"
        assert r["n_regressions"] == 1
        assert [i["id"] for i in r["issues"]] == ["sim-ci-fake"]
        assert r["issues"][0]["detail"]["regressions"][0]["delta_db"] == 10.0

    def test_invalid_recipe_marks_fake_source_fail(self, tmp_path):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        rd = tmp_path / "bad_recipes"
        rd.mkdir()
        (rd / "bad.yaml").write_text(yaml.safe_dump({"model": "patch_antenna"}),
                                     encoding="utf-8")
        r = nightly_multisource_regression(str(rd), run_id="invalid")
        assert r["sources"]["fake"]["status"] == "fail"
        assert r["sources"]["fake"]["n_done"] == 0
        assert [i["id"] for i in r["issues"]] == ["sim-ci-fake"]

    def test_green_run_mints_no_issue(self, fast_fake, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        def ok(_path):
            return {"ok": True}

        r = nightly_multisource_regression(
            recipes_dir, openems_sample=1, hfss_sample=1,
            openems_runner=ok, hfss_runner=ok, hfss_due=True,
            run_id="green-empty")
        assert r["status"] == "pass"
        assert r["issues"] == []
        assert json.loads(Path(r["issue_file"]).read_text(encoding="utf-8")) == []


class TestCostTable:
    """G14 成本表字段全部来自 CostLedger.rollup。"""

    def test_cost_table_matches_ledger_rollup(self, fast_fake, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        ledger = CostLedger()
        ledger.add("preseed", "agent", tokens=10)

        def oem(_path):
            return {"ok": True, "cost": {"solve_s": 2.0, "seat_hours": 0.25}}

        r = nightly_multisource_regression(
            recipes_dir, openems_sample=1, openems_runner=oem, ledger=ledger,
            run_id="cost")
        assert r["cost_table"] == ledger.rollup()
        row = r["cost_table"]["openems"]
        assert row["solve_s"] == 2.0
        assert row["solve_hours"] == 2.0 / 3600.0
        assert row["seat_hours"] == 0.25
        assert row["total_tokens"] == 0.0
        assert set(row["actors"]) == {r["sources"]["openems"]["sample"][0]}
        assert r["cost_table"]["preseed"]["total_tokens"] == 10.0

    def test_runner_cost_fields_feed_ledger(self, fast_fake, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        def runner(_path):
            return {"ok": True,
                    "cost": {"solve_s": 5.0, "gpu_hours": 1.5, "cost": 3.0}}

        r = nightly_multisource_regression(recipes_dir, openems_sample=2,
                                           openems_runner=runner,
                                           run_id="cost-2")
        row = r["cost_table"]["openems"]
        assert row["solve_s"] == 10.0
        assert row["gpu_hours"] == 3.0
        assert row["cost"] == 6.0

    def test_invalid_cost_marks_failure(self, fast_fake, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(
            recipes_dir, openems_sample=1,
            openems_runner=lambda p: {"ok": True, "cost": {"solve_s": -1.0}},
            run_id="bad-cost")
        src = r["sources"]["openems"]
        assert src["status"] == "fail"
        assert "cost 非法" in src["results"][0]["error"]


class TestValidation:
    """空/非法输入显式行为：ok=False + errors，不落盘。"""

    def test_missing_recipes_dir(self, tmp_path):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(tmp_path / "nope")
        assert r["ok"] is False
        assert any("配方目录不存在" in e for e in r["errors"])
        assert "run_dir" not in r

    def test_empty_recipes_dir(self, tmp_path):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        rd = tmp_path / "empty"
        rd.mkdir()
        r = nightly_multisource_regression(str(rd))
        assert r["ok"] is False
        assert any("下无配方" in e for e in r["errors"])

    def test_negative_sample_rejected(self, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(recipes_dir, openems_sample=-1)
        assert r["ok"] is False
        assert any("openems_sample" in e for e in r["errors"])

    def test_non_int_sample_rejected(self, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(recipes_dir, hfss_sample=1.5)
        assert r["ok"] is False
        assert any("hfss_sample" in e for e in r["errors"])

    def test_non_callable_runner_rejected(self, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(recipes_dir, openems_runner="nope")
        assert r["ok"] is False
        assert any("openems_runner" in e for e in r["errors"])

    def test_non_ledger_rejected(self, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(recipes_dir, ledger={"a": 1})
        assert r["ok"] is False
        assert any("ledger" in e for e in r["errors"])

    def test_invalid_run_id_rejected(self, recipes_dir):
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        r = nightly_multisource_regression(recipes_dir, run_id="")
        assert r["ok"] is False
        assert any("run_id" in e for e in r["errors"])


class TestDeterminism:
    def test_same_input_byte_identical_reports(self, recipes_dir):
        """同输入两次：报告/issue 文件逐字节一致（钉 run_id + 清历史）。"""
        from rfauto.service.sim_ci_service import nightly_multisource_regression

        def red(_path):
            return {"ok": False, "error": "deterministic red"}

        def run_once():
            return nightly_multisource_regression(
                recipes_dir, openems_sample=2,
                openems_runner=red, ledger=CostLedger(), run_id="det")

        first = run_once()
        report_path = Path(first["run_dir"]) / "sim_ci_report.json"
        first_report = report_path.read_bytes()
        first_issues = Path(first["issue_file"]).read_bytes()
        assert first["issues"], "红场景必须产出 issue（否则本测试空转）"

        # 清 runs 索引历史：否则第二轮会命中第一轮基线，报告含历史 run_id。
        index = Path("runs") / "index.db"
        index.unlink(missing_ok=True)

        second = run_once()
        assert report_path.read_bytes() == first_report
        assert Path(second["issue_file"]).read_bytes() == first_issues
