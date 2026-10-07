"""W2-D XD-5：metrics.json 标准 + golden 基线 pin/compare/drift 三动作。

判据（sa_specs2 §八 §8.3 对应）：
- 金样例三动作：pin 落金样例（拒重复钉/update 留旧到新 digest 审计串）、
  compare 对金样例（match/drift 双态）、drift 超限显式 verdict（CLI 退出码
  语义在 test_w2_d_xd5_cli 节）；
- metrics 标准：schema 键集+对齐面（锚名集 hit/unanchored 如实分列，
  wilkinson 类对齐率 ≥0.8 进信封）；
- nightly golden 优先：golden 在→对照 golden（篡改滚动历史不翻判定）；
  无 golden→现状滚动行为逐位不变；显式 baseline 缺失→error 信封不静默。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from rfauto.service.sim_ci_service import (
    BASELINE_SCHEMA,
    latest_channel_baselines,
    pin_baseline,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # write_meta 的 pip freeze / git sha 子进程与本项无关——钉住保快且确定
    monkeypatch.setattr("rfauto.infra.run_store._pip_freeze_sha", lambda: "test")
    monkeypatch.setattr("rfauto.infra.run_store._git_sha", lambda: "test")
    yield


def _record(db_path, run_id, model, metrics, ts, status="done",
            adapter="fake"):
    from rfauto.infra.run_store import record_run

    assert record_run(db_path, {
        "run_id": run_id, "model": model, "adapter": adapter,
        "status": status, "timestamp": ts, "metrics": metrics,
    })


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "registry.sqlite"
    _record(p, "old_wilkinson", "wilkinson_power_divider",
            {"s11_db_max_in_band": -20.0, "s21_db_mean_in_band": -3.2},
            "2026-10-01T00:00:00+00:00")
    _record(p, "old_patch", "patch_antenna",
            {"s11_db_max_in_band": -15.0}, "2026-10-01T01:00:00+00:00")
    return p


class TestGoldenThreeActions:
    """pin / compare / drift 三动作 + 金样例文件面。"""

    def test_pin_writes_golden_sample(self, db, tmp_path):
        golden = tmp_path / "golden" / "simci_baseline.yaml"
        r = pin_baseline(adapter="fake", db_path=db, baseline_path=golden)
        assert r["ok"], r.get("errors")
        assert golden.is_file()
        data = yaml.safe_load(golden.read_text(encoding="utf-8"))
        assert data["schema"] == BASELINE_SCHEMA
        for key in ("pinned_at", "pinned_run_id", "adapter", "channel",
                    "metrics_digest", "baselines", "tool_versions", "git_sha"):
            assert key in data, f"golden 缺键 {key}"
        assert data["adapter"] == "fake"
        assert data["channel"] == "fake"
        assert set(data["baselines"]) == {"wilkinson_power_divider",
                                          "patch_antenna"}
        # digest 与 latest_channel_baselines 同源一致
        cur = latest_channel_baselines("fake", db_path=db)
        assert cur["ok"] and data["metrics_digest"] == cur["metrics_digest"]
        assert r["pinned_run_id"] == "old_patch"  # 最新时间戳的 run 为钉点

    def test_pin_digest_is_deterministic(self, db, tmp_path):
        a = tmp_path / "a.yaml"
        b = tmp_path / "b.yaml"
        r1 = pin_baseline(adapter="fake", db_path=db, baseline_path=a)
        r2 = pin_baseline(adapter="fake", db_path=db, baseline_path=b)
        assert r1["metrics_digest"] == r2["metrics_digest"]

    def test_pin_refuses_overwrite_without_update(self, db, tmp_path):
        golden = tmp_path / "g.yaml"
        r1 = pin_baseline(adapter="fake", db_path=db, baseline_path=golden)
        assert r1["ok"]
        r2 = pin_baseline(adapter="fake", db_path=db, baseline_path=golden)
        assert not r2["ok"]
        assert "update=True" in "".join(r2["errors"])
        assert r2["previous_metrics_digest"] == r1["metrics_digest"]

    def test_pin_update_records_old_to_new_digest(self, db, tmp_path):
        golden = tmp_path / "g.yaml"
        r1 = pin_baseline(adapter="fake", db_path=db, baseline_path=golden)
        _record(db, "new_wilkinson", "wilkinson_power_divider",
                {"s11_db_max_in_band": -22.0}, "2026-10-02T00:00:00+00:00")
        r2 = pin_baseline(adapter="fake", db_path=db, baseline_path=golden,
                          update=True)
        assert r2["ok"], r2.get("errors")
        assert r2["action"] == "update"
        assert r2["previous_metrics_digest"] == r1["metrics_digest"]
        assert r2["metrics_digest"] != r1["metrics_digest"]
        # #325 留痕：审计串携带旧→新 digest 前 12 位
        audit = r2["update_audit"]
        assert r1["metrics_digest"][:12] in audit
        assert r2["metrics_digest"][:12] in audit

    def test_compare_match_right_after_pin(self, db, tmp_path):
        from rfauto.service.sim_ci_service import compare_baseline

        golden = tmp_path / "g.yaml"
        pin_baseline(adapter="fake", db_path=db, baseline_path=golden)
        r = compare_baseline(adapter="fake", db_path=db,
                             baseline_path=golden)
        assert r["ok"] and r["outcome"] == "match"
        assert r["digest_match"] is True

    def test_compare_drift_after_rolling(self, db, tmp_path):
        from rfauto.service.sim_ci_service import compare_baseline

        golden = tmp_path / "g.yaml"
        pin_baseline(adapter="fake", db_path=db, baseline_path=golden)
        _record(db, "drift_wilkinson", "wilkinson_power_divider",
                {"s11_db_max_in_band": -12.0}, "2026-10-03T00:00:00+00:00")
        r = compare_baseline(adapter="fake", db_path=db,
                             baseline_path=golden)
        assert r["ok"] and r["outcome"] == "drift"
        assert r["digest_match"] is False
        assert r["max_abs_delta"] > 0
        drifted = {(d["model"], d["metric"]) for d in r["deltas"]}
        assert ("wilkinson_power_divider", "s11_db_max_in_band") in drifted

    def test_compare_missing_golden_is_legal_state(self, db, tmp_path):
        from rfauto.service.sim_ci_service import compare_baseline

        r = compare_baseline(adapter="fake", db_path=db,
                             baseline_path=tmp_path / "nope.yaml")
        assert r["ok"] and r["outcome"] == "missing_golden"

    def test_drift_exceeded_and_within(self, db, tmp_path):
        from rfauto.service.sim_ci_service import baseline_drift

        golden = tmp_path / "g.yaml"
        pin_baseline(adapter="fake", db_path=db, baseline_path=golden)
        _record(db, "drift_wilkinson", "wilkinson_power_divider",
                {"s11_db_max_in_band": -19.5}, "2026-10-03T00:00:00+00:00")
        # 容差 0.0：0.5dB 漂移即超限（显式 verdict，不放过）
        r0 = baseline_drift(adapter="fake", db_path=db,
                            baseline_path=golden, tolerance=0.0)
        assert r0["ok"] and r0["outcome"] == "exceeded"
        assert r0["n_exceeded"] >= 1
        # 容差 1.0：0.5dB 漂移在带内，但 digest 仍不一致→超限（模型集/非数值面
        # 变化不可被数值表覆盖，如实计入）
        r1 = baseline_drift(adapter="fake", db_path=db,
                            baseline_path=golden, tolerance=1.0)
        assert r1["ok"] and r1["outcome"] == "exceeded"
        assert r1["reason"]
        # update 重钉后 digest 回匹配→within
        pin_baseline(adapter="fake", db_path=db, baseline_path=golden,
                     update=True)
        r2 = baseline_drift(adapter="fake", db_path=db,
                            baseline_path=golden, tolerance=0.0)
        assert r2["ok"] and r2["outcome"] == "within"

    def test_pin_without_runs_index_is_error(self, tmp_path):
        r = pin_baseline(adapter="fake", db_path=tmp_path / "nope.sqlite",
                         baseline_path=tmp_path / "g.yaml")
        assert not r["ok"]

    def test_pin_without_qualifying_runs_is_error(self, tmp_path):
        from rfauto.infra.run_store import record_run

        db = tmp_path / "empty.sqlite"
        record_run(db, {"run_id": "r0", "model": "m", "adapter": "fake",
                        "status": "running", "timestamp": "2026-10-01",
                        "metrics": {}})
        r = pin_baseline(adapter="fake", db_path=db,
                         baseline_path=tmp_path / "g.yaml")
        assert not r["ok"]
        assert "无可钉基线" in "".join(r["errors"])


class TestStandardMetrics:
    """metrics.json 标准写读 + 对齐面。"""

    def test_schema_keys_and_readback(self, tmp_path):
        from rfauto.service.sim_ci_service import (
            read_standard_metrics,
            write_standard_metrics,
        )

        rdir = tmp_path / "run1"
        names = ["l_via_h", "k_of_g", "f_dip_L"]  # 锚注册表内真名
        r = write_standard_metrics(
            rdir, "final_verify",
            {names[0]: 0.125e-9, names[1]: 0.051, names[2]: 77.8,
             "custom_new_metric_db": -1.2},
            run_id="run1", adapter="openems", template="patch")
        assert r["ok"], r.get("errors")
        assert r["alignment_ratio"] == 0.75
        assert r["unanchored"] == ["custom_new_metric_db"]
        payload = json.loads(
            (rdir / "metrics.json").read_text(encoding="utf-8"))
        assert set(payload) == {
            "schema_version", "run_id", "stage", "adapter", "template",
            "metrics", "metric_alignment", "gate_digest", "created_at"}
        assert payload["schema_version"] == "1"
        assert payload["metric_alignment"]["anchored"] == sorted(
            [names[0], names[1], names[2]])
        assert payload["gate_digest"] is None
        back = read_standard_metrics(rdir)
        assert back["ok"]
        assert back["data"]["metrics"][names[2]] == 77.8

    def test_gate_digest_present_when_gate_given(self, tmp_path):
        from rfauto.service.sim_ci_service import (
            read_standard_metrics,
            write_standard_metrics,
        )

        r = write_standard_metrics(tmp_path / "r", "calibrate",
                                   {"k_of_g": 0.051},
                                   gate={"k_of_g": "PASS"})
        assert r["ok"] and r["gate_digest"]
        back = read_standard_metrics(tmp_path / "r")
        assert back["data"]["gate_digest"] == r["gate_digest"]

    def test_wilkinson_anchor_alignment_ratio(self, tmp_path):
        """判据 4：锚覆盖模板的指标名对齐率进报告（≥0.8 目标态演示）。"""
        from rfauto.service.sim_ci_service import (
            anchor_metric_names,
            write_standard_metrics,
        )

        anchored = anchor_metric_names()
        assert anchored, "锚注册表 quantity 名集不应为空"
        wilkinson_names = [n for n in anchored if "wilkinson" in n]
        metrics = {n: 0.5 for n in wilkinson_names}
        metrics["l_via_h"] = 0.125e-9  # 锚注册表内真名
        metrics["k_of_g"] = 0.051  # 锚注册表内真名
        metrics["f_dip_L"] = 77.8  # 锚注册表内真名
        metrics["s21_db_mean_in_band"] = -3.1  # 非（当前）锚名→unanchored
        r = write_standard_metrics(tmp_path / "rw", "final_verify", metrics,
                                   template="wilkinson_power_divider")
        assert r["ok"]
        assert r["anchored"] == sorted(set(wilkinson_names)
                                       | {"l_via_h", "k_of_g", "f_dip_L"})
        assert r["unanchored"] == ["s21_db_mean_in_band"]
        assert r["alignment_ratio"] >= 0.8

    def test_non_dict_metrics_rejected(self, tmp_path):
        from rfauto.service.sim_ci_service import write_standard_metrics

        r = write_standard_metrics(tmp_path / "r", "s", [1, 2])
        assert not r["ok"]

    def test_read_missing_and_bad_schema(self, tmp_path):
        from rfauto.service.sim_ci_service import read_standard_metrics

        assert not read_standard_metrics(tmp_path / "nope")["ok"]
        rdir = tmp_path / "r"
        rdir.mkdir()
        (rdir / "metrics.json").write_text(
            json.dumps({"schema_version": "9"}), encoding="utf-8")
        r = read_standard_metrics(rdir)
        assert not r["ok"] and "schema_version" in "".join(r["errors"])


class TestNightlyGoldenFirst:
    """nightly_regression golden 优先双态（判据 5）。"""

    @staticmethod
    def _recipe(path: Path, model: str) -> None:
        path.write_text(yaml.safe_dump({
            "model": model,
            "params": {"arm_len_mm": {"value": 20.0}},
            "setup": {"freq_range_ghz": [2.3, 2.5], "points": 5},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                            "op": "max_below", "value": -15}],
        }), encoding="utf-8")

    def test_golden_overrides_rolling(self, db, tmp_path):
        """golden 在：对照的是 golden 基值，判定不随滚动历史翻动。"""
        from rfauto.service.sim_ci_service import nightly_regression

        recipes = tmp_path / "recipes"
        recipes.mkdir()
        self._recipe(recipes / "r.yaml", "wilkinson_power_divider")
        # 先滚动跑一次拿 fake 确定性当前水位，把 golden 钉在同一水位
        r0 = nightly_regression(str(recipes), adapter="fake")
        assert r0["ok"]
        cur = r0["entries"][0]["metrics"]["s11_db_max_in_band"]
        _record(db, "anchor_row", "wilkinson_power_divider",
                {"s11_db_max_in_band": cur}, "2026-10-02T00:00:00+00:00")
        golden = tmp_path / "g.yaml"
        pin = pin_baseline(adapter="fake", db_path=db, baseline_path=golden)
        assert pin["ok"]
        assert pin["pinned_run_id"] == "anchor_row"
        # 篡改滚动历史：最新 wilkinson run 劣化到 -10（golden 不受影响）
        _record(db, "worse_roll", "wilkinson_power_divider",
                {"s11_db_max_in_band": -10.0}, "2026-10-04T00:00:00+00:00")

        r = nightly_regression(str(recipes), adapter="fake",
                               baseline_path=golden)
        assert r["ok"] and r["baseline_mode"] == "golden"
        entry = r["entries"][0]
        assert entry["baseline"]["source"] == "golden"
        assert entry["baseline"]["run_id"] == "anchor_row"
        # 当前水位 == golden 水位：对照 golden 零劣化
        assert r["n_regressions"] == 0

    def test_golden_flags_regression_rolling_misses(self, db, tmp_path,
                                                    monkeypatch):
        """判据 5 篡改态分叉：golden 判劣化命中，滚动基线（更差历史）不命中。"""
        from rfauto.service import sim_ci_service
        # 缺省 golden 路径钉到 tmp 缺失文件（W6 起 knowledge/simci_baseline.yaml
        # 已入册，缺省回退会误拾真仓 golden——测试隔离 #144）
        monkeypatch.setattr(sim_ci_service, "default_baseline_path",
                            lambda: tmp_path / "no_golden.yaml")
        from rfauto.service.sim_ci_service import nightly_regression

        recipes = tmp_path / "recipes"
        recipes.mkdir()
        self._recipe(recipes / "r.yaml", "wilkinson_power_divider")
        golden = tmp_path / "g.yaml"
        pin = pin_baseline(adapter="fake", db_path=db, baseline_path=golden)
        assert pin["ok"]  # golden 基值=old_wilkinson -20.0
        # 注入更差的滚动历史：滚动 prior 变成 -10（当前 fake 相对它是改善）
        _record(db, "worse_roll", "wilkinson_power_divider",
                {"s11_db_max_in_band": -10.0}, "2026-10-04T00:00:00+00:00")

        r = nightly_regression(str(recipes), adapter="fake",
                               baseline_path=golden)
        assert r["ok"] and r["baseline_mode"] == "golden"
        assert r["n_regressions"] == 1
        reg = r["regressions"][0]
        assert reg["baseline_source"] == "golden"
        assert reg["baseline_run_id"] == pin["pinned_run_id"]
        assert reg["delta_db"] > 1.0

        # 同湖同刻、无 golden（回退滚动）：prior=worse_roll(-10)，当前
        # fake run 相对它是改善——不记回归。两态分叉证明判定确实走
        # golden 而非滚动。
        golden.rename(tmp_path / "g_hidden.yaml")
        r2 = nightly_regression(str(recipes), adapter="fake")
        assert r2["ok"] and r2["baseline_mode"] == "rolling"
        assert r2["n_regressions"] == 0

    def test_explicit_missing_baseline_is_error(self, tmp_path):
        from rfauto.service.sim_ci_service import nightly_regression

        recipes = tmp_path / "recipes"
        recipes.mkdir()
        self._recipe(recipes / "r.yaml", "wilkinson_power_divider")
        r = nightly_regression(str(recipes), adapter="fake",
                               baseline_path=tmp_path / "nope.yaml")
        assert not r["ok"]
        assert "golden" in "".join(r["errors"])


class TestW2DXd5Cli:
    """CLI 叶：--help 真跑 + --json 双路径 + 退出码语义（0/1/2）。"""

    def _args(self, db, golden, *extra):
        return ["--adapter", "fake", "--db", str(db),
                "--baseline", str(golden), *extra]

    def test_help_runs(self):
        from rfauto.cli.domains.solvers import app

        result = runner.invoke(app, ["simci-pin-baseline", "--help"])
        assert result.exit_code == 0
        assert "pin" in result.output and "compare" in result.output

    def test_unknown_action_exit_2(self):
        from rfauto.cli.domains.solvers import app

        result = runner.invoke(app, ["simci-pin-baseline", "nope"],
                                 catch_exceptions=False)
        assert result.exit_code == 2

    def test_pin_compare_drift_json_paths(self, db, tmp_path):
        from rfauto.cli.domains.solvers import app

        golden = tmp_path / "g.yaml"

        base = self._args(db, golden)
        r1 = runner.invoke(app, ["simci-pin-baseline", "pin", *base, "--json"],
                           catch_exceptions=False)
        assert r1.exit_code == 0, r1.output
        payload = json.loads(r1.output)
        assert payload["ok"] and payload["action"] == "pin"

        r2 = runner.invoke(app, ["simci-pin-baseline", "compare", *base,
                                 "--json"], catch_exceptions=False)
        assert r2.exit_code == 0
        assert json.loads(r2.output)["outcome"] == "match"

        # 漂移注入 → drift 超限退出码 1（--json 仍是合法信封）
        _record(db, "drift_wilkinson", "wilkinson_power_divider",
                {"s11_db_max_in_band": -11.0}, "2026-10-05T00:00:00+00:00")
        r3 = runner.invoke(app, ["simci-pin-baseline", "drift", *base,
                                 "--json"], catch_exceptions=False)
        assert r3.exit_code == 1, r3.output
        assert json.loads(r3.output)["outcome"] == "exceeded"

        r4 = runner.invoke(app, ["simci-pin-baseline", "compare", *base,
                                 "--json"], catch_exceptions=False)
        assert r4.exit_code == 1
        assert json.loads(r4.output)["outcome"] == "drift"

    def test_missing_golden_exit_2(self, db, tmp_path):
        from rfauto.cli.domains.solvers import app

        result = runner.invoke(
            app, ["simci-pin-baseline", "compare",
                  *self._args(db, tmp_path / "nope.yaml"), "--json"],
            catch_exceptions=False)
        assert result.exit_code == 2
        assert json.loads(result.output)["outcome"] == "missing_golden"

    def test_pin_twice_without_update_exit_2(self, db, tmp_path):
        from rfauto.cli.domains.solvers import app

        golden = tmp_path / "g.yaml"
        base = self._args(db, golden)

        assert runner.invoke(app, ["simci-pin-baseline", "pin", *base],
                             catch_exceptions=False).exit_code == 0
        result = runner.invoke(app, ["simci-pin-baseline", "pin", *base,
                                     "--json"], catch_exceptions=False)
        assert result.exit_code == 2
        assert not json.loads(result.output)["ok"]

    def test_text_path_pin_mentions_audit_line(self, db, tmp_path, capsys):
        from rfauto.cli.domains.solvers import app

        result = runner.invoke(
            app, ["simci-pin-baseline", "pin", *self._args(db, tmp_path / "g")],
            catch_exceptions=False)
        assert result.exit_code == 0
        assert "simci golden pin" in result.output
