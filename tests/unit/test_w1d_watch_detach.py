"""W1-D SN-9（2026-10-05）：tune --watch 死旗修真 + --detach 补实回归钉。

死旗与假 docstring 本相（sn_platform_deepen/REPORT.md SN-9 行）：
- cli/domains/workflow.py tune 声明 ``--watch`` 但函数体从未消费（死旗）；
- cli/main.py 模块 docstring 宣传 ``rfauto tune <recipe.yaml> [--watch|--detach]``
  而 tune 无 --detach（假宣传）。

修真形态：
- --watch = Optuna study.optimize(callbacks=...) 逐 trial 播报（rich Live：
  trial#/cost/Δ），挂点链 run_optimization(callbacks=) ← start_tune(on_trial=)
  ← CLI _TrialWatchReporter；
- --detach = run_once_async 范式复用（进程内 JobRegistry + 单写锁 + 非daemon
  线程）实装 start_tune_async，jobs status 可轮询。

多保真/多目标/代理寻优路径：detach 显式拒绝（exit 1），watch 一行降级提示
（#122 不静默）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


@pytest.fixture(autouse=True)
def _isolated_runs(tmp_path, monkeypatch):
    """chdir + 临时 optuna storage（#144：优化循环类测试必须 chdir 隔离）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    db_dir = tmp_path / "runs" / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "rfauto.optimization.optimizer.get_storage_path",
        lambda: f"sqlite:///{(db_dir / 'optuna.db').as_posix()}",
    )


@pytest.fixture
def recipe_path(tmp_path):
    """最小 Wilkinson 配方（含 optimization.params 段，fake 适配器秒级）。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {
            "f0_ghz": {"value": 2.4},
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.33},
        },
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 101},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
        "optimization": {
            "params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
            },
        },
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


# ─── 死旗修真：旗标真实存在且被消费 ─────────────────────────────────────────


class TestWatchDetachFlagsExist:
    def test_tune_has_watch_and_detach_options(self):
        """死旗回归钉：tune 必须声明 --watch 与 --detach 两个旗标（click 树鸭子遍历）。"""
        from typer.main import get_command

        from rfauto.cli.main import app

        cmd = get_command(app).commands["tune"]
        opt_names = {p.name for p in getattr(cmd, "params", [])}
        assert {"watch", "detach"} <= opt_names

    def test_run_optimization_accepts_callbacks(self):
        """挂点存在性：run_optimization 签名含 callbacks（study.optimize 透传）。"""
        import inspect

        from rfauto.optimization.optimizer import run_optimization

        assert "callbacks" in inspect.signature(run_optimization).parameters

    def test_start_tune_accepts_on_trial(self):
        import inspect

        from rfauto.service.api import start_tune, start_tune_async

        assert "on_trial" in inspect.signature(start_tune).parameters
        async_params = set(inspect.signature(start_tune_async).parameters)
        assert {"recipe_path", "max_trials", "sampler"} <= async_params


# ─── 挂点链：on_trial → callbacks → study.optimize ──────────────────────────


class TestCallbackWiring:
    def test_start_tune_on_trial_passthrough(self, monkeypatch):
        """on_trial 条件透传（#df6③）：给→callbacks=[f]；不给→键不加。"""
        import rfauto.optimization.optimizer as opt_mod
        from rfauto.service.api import start_tune

        captured: dict = {}

        def fake_run(recipe_path, **kwargs):
            captured.update(kwargs)
            return {"ok": False, "errors": ["stub"]}

        monkeypatch.setattr(opt_mod, "run_optimization", fake_run)

        marker = lambda study, trial: None  # noqa: E731
        start_tune("r.yaml", on_trial=marker)
        assert captured.get("callbacks") == [marker]

        captured.clear()
        start_tune("r.yaml")
        assert "callbacks" not in captured

    def test_run_optimization_invokes_callbacks_per_trial(self, recipe_path):
        """真环集成钉：fake 2 trial → 回调恰被调 2 次（study.optimize 接线）。"""
        import optuna

        from rfauto.optimization.optimizer import run_optimization

        calls: list = []
        states: list = []

        def recorder(study, trial):
            calls.append(trial.number)
            states.append(trial.state)

        result = run_optimization(
            recipe_path, adapter_name="fake", max_trials=2,
            adapter_kwargs={"n_ports": 3}, callbacks=[recorder])
        assert result["ok"], result.get("errors")
        assert result["trials_completed"] == 2
        assert sorted(calls) == [0, 1]
        assert isinstance(calls[0], int)
        assert states and all(s in (optuna.trial.TrialState.COMPLETE,
                                    optuna.trial.TrialState.PRUNED)
                              for s in states)


# ─── _TrialWatchReporter：播报状态与渲染 ────────────────────────────────────


class TestTrialWatchReporter:
    def _reporter(self, console=None):
        from io import StringIO

        from rich.console import Console

        from rfauto.cli.domains.workflow import _TrialWatchReporter

        if console is None:
            # 非终端 Console（StringIO 出口）→ 回调走一行直出支路，零文件句柄
            console = Console(file=StringIO(), width=200)
        return _TrialWatchReporter(console)

    def test_record_tracks_best_and_delta(self):
        """纯状态记账：best 单调、Δ=cost−prev_best（负=改进）、PRUNED 无值行。"""
        r = self._reporter()
        r.record(0, 1.0, "COMPLETE")
        r.record(1, 0.8, "COMPLETE")   # 改进：Δ=-0.2
        r.record(2, 0.9, "COMPLETE")   # 劣于 best：Δ=+0.1
        r.record(3, None, "PRUNED")    # 无值
        assert [row[0] for row in r._rows] == [0, 1, 2, 3]
        assert r._rows[1][2] == pytest.approx(-0.2)
        assert r._rows[2][2] == pytest.approx(0.1)
        assert r._rows[3][1] is None and r._rows[3][2] is None
        assert r.best == pytest.approx(0.8)
        assert r.best_trial == 1

    def test_render_contains_rows_and_best(self):
        r = self._reporter()
        r.record(0, 2.5, "COMPLETE")
        r.record(1, 2.1, "COMPLETE")   # 改进：Δ=-0.4000
        r.record(2, 2.3, "COMPLETE")   # 劣于 best：Δ=+0.2000
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        Console(file=buf, width=200).print(r._render())
        out = buf.getvalue()
        assert "trial" in out and "best cost: 2.1000" in out
        assert "2.5000" in out and "-0.4000" in out and "+0.2000" in out

    def test_callback_consumes_real_optuna_trials(self, recipe_path):
        """端到端：真 optuna study + reporter 回调 → rows 逐 trial 记账。"""
        from rfauto.optimization.optimizer import run_optimization

        reporter = self._reporter()
        result = run_optimization(
            recipe_path, adapter_name="fake", max_trials=3,
            adapter_kwargs={"n_ports": 3}, callbacks=[reporter])
        assert result["ok"], result.get("errors")
        assert len(reporter._rows) == 3
        assert reporter.best is not None
        assert reporter.best == pytest.approx(result["best_cost"])
        # 渲染面含播报表头与 best 行
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        Console(file=buf, width=120).print(reporter._render())
        assert "tune --watch" in buf.getvalue()


# ─── CLI 层：--watch 输出可捕获；--detach job 生命周期 ──────────────────────


class TestTuneCliWatchDetach:
    def _invoke(self, argv, monkeypatch, fake_start_tune=None):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        if fake_start_tune is not None:
            monkeypatch.setattr("rfauto.service.api.start_tune", fake_start_tune)
        return CliRunner().invoke(app, argv)

    @staticmethod
    def _fake_trials_payload(on_trial):
        """合成两个 trial（duck typing，模拟 optuna frozen trial 回调）。"""

        class _T:
            def __init__(self, number, value):
                self.number = number
                self.value = value
                self.state = "COMPLETE"

        if on_trial is not None:
            on_trial(None, _T(0, 1.5))
            on_trial(None, _T(1, 1.2))

    def test_watch_prints_per_trial_lines(self, recipe_path, monkeypatch):
        """--watch：非终端出口逐 trial 播报行（trial#/cost/Δ/best）可捕获。"""
        seen: dict = {}

        def fake_start_tune(recipe, *, on_trial=None, **kw):
            seen["on_trial"] = on_trial
            self._fake_trials_payload(on_trial)
            return {"ok": True, "study_name": "s", "run_id": "run-x",
                    "trials_total": 2, "trials_completed": 2, "trials_pruned": 0,
                    "existing_trials": 0, "elapsed_s": 0.1,
                    "best_cost": 1.2, "best_params": {"arm_len_mm": 20.0},
                    "best_metrics": {}}

        r = self._invoke(["tune", recipe_path, "--watch", "--max-trials", "2"],
                         monkeypatch, fake_start_tune)
        assert r.exit_code == 0, r.output
        assert "trial 0: cost=1.5000" in r.output
        assert "trial 1: cost=1.2000" in r.output
        assert "best=1.2000" in r.output
        # 回调真被挂进 start_tune（死旗修真的本质断言：旗标已消费）
        assert seen["on_trial"] is not None

    def test_no_watch_no_on_trial(self, recipe_path, monkeypatch):
        """无 --watch：不传 on_trial（缺省路径行为不变）。"""
        seen: dict = {}

        def fake_start_tune(recipe, *, on_trial=None, **kw):
            seen["on_trial"] = on_trial
            return {"ok": True}

        r = self._invoke(["tune", recipe_path], monkeypatch, fake_start_tune)
        assert r.exit_code == 0, r.output
        assert seen["on_trial"] is None

    def test_detach_returns_job_and_polls_done(self, recipe_path, monkeypatch):
        """--detach：立即回 job_id；后台线程完成后 poll_job state=done 且收全量信封。"""
        import time

        from rfauto.service.api import poll_job
        from rfauto.service.job_registry import get_job_registry

        def fake_start_tune(recipe, **kw):
            time.sleep(0.05)
            return {"ok": True, "run_id": "run-detach-1", "study_name": "s",
                    "best_cost": 0.5, "best_params": {"arm_len_mm": 21.0},
                    "trials_completed": 2, "trials_total": 2}

        r = self._invoke(["tune", recipe_path, "--detach"], monkeypatch, fake_start_tune)
        assert r.exit_code == 0, r.output
        assert "job_id: job_" in r.output
        job_id = r.output.split("job_id: ")[1].split()[0].strip()

        job = get_job_registry().wait(job_id, timeout_s=10.0)
        assert job is not None and job["state"] == "done"
        polled = poll_job(job_id)
        assert polled["ok"] and polled["state"] == "done"
        assert polled["run_id"] == "run-detach-1"

    def test_detach_refused_for_multi_and_sbo(self, recipe_path, monkeypatch):
        """多目标/代理寻优路径 --detach 显式拒绝（不静默丢弃后台语义）。"""
        for extra in (["--multi"], ["--sampler", "sbo"]):
            r = self._invoke(["tune", recipe_path, "--detach", *extra], monkeypatch,
                             lambda recipe, **kw: {"ok": True})
            assert r.exit_code == 1, (extra, r.output)
            assert "仅支持单目标" in r.output

    def test_watch_degraded_note_for_multi(self, recipe_path, monkeypatch):
        """多目标路径 --watch：一行降级提示后照常执行（#122 不静默）。"""

        def fake_multi(recipe, **kw):
            return {"ok": True, "run_id": "run-m", "objective_names": ["cost"],
                    "n_pareto": 1, "n_evaluations": 5, "elapsed_s": 0.1,
                    "pareto_points": [{"params": {"a": 1.0}, "objectives": {"cost": 1.0}}]}

        monkeypatch.setattr("rfauto.service.api.start_tune_multi", fake_multi)
        r = self._invoke(["tune", recipe_path, "--watch", "--multi"], monkeypatch)
        assert r.exit_code == 0, r.output
        assert "仅单目标路径支持" in r.output
