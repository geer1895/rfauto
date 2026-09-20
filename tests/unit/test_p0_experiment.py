"""方向 1 P0 实验 + 6a/4d study inject 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


def _write_recipe(tmp_path: Path) -> Path:
    recipe = {
        "model": "wilkinson_power_divider",
        "recipe_version": 1,
        "schema_version": 1,
        "params": {
            "arm_len_mm": {"value": 20.5, "unit": "mm"},
            "series_w_mm": {"value": 0.33},
            "shunt_w_mm": {"value": 1.10},
        },
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
        "optimization": {
            "params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
                "shunt_w_mm": {"low": 0.90, "high": 1.30},
            }
        },
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe, allow_unicode=True), encoding="utf-8")
    return path


class TestP0Experiment:
    """P0 实验服务函数测试。"""

    def test_p0_runs_and_returns_verdict(self, tmp_path):
        from rfauto.service.api import run_p0_experiment
        recipe = _write_recipe(tmp_path)
        result = run_p0_experiment(
            recipe,
            seed=42,
            coarse_trials=5,
            fine_trials=3,
            baseline_trials=5,
            edge_samples=3,
        )
        assert result["ok"]
        # fake vs fake 自比较：gate 关闭，verdict 必须是 INCONCLUSIVE
        # （曾对自比较输出 PASS，硬门槛被架空）
        assert result["verdict"] == "INCONCLUSIVE"
        assert result["gate"] == "self_comparison_disabled"
        assert "correlation" in result
        assert "edge_sampling" in result
        assert "cross_fidelity" in result

    def test_p0_verdict_thresholds(self, tmp_path):
        from rfauto.service.api import run_p0_experiment
        recipe = _write_recipe(tmp_path)
        result = run_p0_experiment(recipe, seed=42, coarse_trials=8, fine_trials=5,
                                   baseline_trials=8, edge_samples=3)
        assert result["ok"]
        corr = result["correlation"]
        if corr.get("spearman_rho") is not None:
            rho = corr["spearman_rho"]
            assert -1.0 <= rho <= 1.0

    def test_p0_missing_recipe_fails(self, tmp_path):
        from rfauto.service.api import run_p0_experiment
        result = run_p0_experiment(tmp_path / "nope.yaml")
        assert not result["ok"]


class TestP0CLI:
    """rfauto p0 CLI 测试。"""

    def test_p0_success(self, tmp_path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        runner = CliRunner()
        recipe = _write_recipe(tmp_path)
        result = runner.invoke(app, ["p0", str(recipe),
                                     "--coarse", "5", "--fine", "3",
                                     "--baseline", "5", "--edge-samples", "2"])
        assert result.exit_code in (0, 1), result.output  # 1 if FAIL verdict
        assert "Verdict" in result.output


class TestStudyInject:
    """study_inject 服务函数测试（enqueue_trial 语义）。"""

    def _make_study(self, study_name: str):
        import optuna

        from rfauto.optimization.optimizer import get_storage_path
        study = optuna.create_study(
            study_name=study_name, storage=get_storage_path(), direction="minimize",
        )
        study.optimize(lambda t: (t.suggest_float("arm_len_mm", 18.0, 23.0) - 20.5) ** 2,
                       n_trials=5, show_progress_bar=False)
        return study

    def test_inject_into_nonexistent_study_fails(self, tmp_path):
        from rfauto.service.api import study_inject
        result = study_inject("no_such_study", {"arm_len_mm": 20.5}, source="human")
        assert not result["ok"]

    def test_inject_creates_waiting_trial_with_source_tag(self, tmp_path):
        import optuna

        from rfauto.optimization.optimizer import get_storage_path
        from rfauto.service.api import study_inject
        name = "inj_waiting"
        self._make_study(name)
        result = study_inject(name, {"arm_len_mm": 20.0}, source="human")
        assert result["ok"]
        study = optuna.load_study(study_name=name, storage=get_storage_path())
        trial = next(t for t in study.get_trials(deepcopy=False)
                 if t.number == result["trial_number"])
        assert trial.state == optuna.trial.TrialState.WAITING
        assert trial.user_attrs.get("trial_source") == "human"
        # WAITING trial 的注入参数存于 system_attrs.fixed_params（消费后进入 params）
        assert trial.system_attrs["fixed_params"]["arm_len_mm"] == 20.0

    def test_inject_clips_out_of_bounds_and_marks(self, tmp_path):
        # 计划 4d 边界映射：越界裁切入库并标记，不静默丢弃
        import optuna

        from rfauto.optimization.optimizer import get_storage_path
        from rfauto.service.api import study_inject
        name = "inj_clip"
        self._make_study(name)
        result = study_inject(name, {"arm_len_mm": 30.0}, source="human")
        assert result["ok"]
        assert result["clipped_from"]["arm_len_mm"]["requested"] == 30.0
        study = optuna.load_study(study_name=name, storage=get_storage_path())
        trial = next(t for t in study.get_trials(deepcopy=False)
                 if t.number == result["trial_number"])
        assert trial.system_attrs["fixed_params"]["arm_len_mm"] == 23.0
        assert trial.user_attrs["clipped_from"]["arm_len_mm"]["clipped_to"] == 23.0

    def test_injected_trial_consumed_and_evaluated(self, tmp_path):
        # 注入点被下一次 optimize 消费后 COMPLETE 且参数精确等于注入值
        import optuna

        from rfauto.optimization.optimizer import get_storage_path
        from rfauto.service.api import study_inject
        name = "inj_consumed"
        study = self._make_study(name)
        result = study_inject(name, {"arm_len_mm": 19.5}, source="human")
        assert result["ok"]
        obj = lambda t: (t.suggest_float("arm_len_mm", 18.0, 23.0) - 20.5) ** 2  # noqa: E731
        study.optimize(obj, n_trials=1, show_progress_bar=False)
        study = optuna.load_study(study_name=name, storage=get_storage_path())
        trial = next(t for t in study.get_trials(deepcopy=False)
                 if t.number == result["trial_number"])
        assert trial.state == optuna.trial.TrialState.COMPLETE
        assert trial.params["arm_len_mm"] == 19.5

    def test_inject_unknown_param_rejected(self, tmp_path):
        from rfauto.service.api import study_inject
        name = "inj_unknown"
        self._make_study(name)
        result = study_inject(name, {"bogus_param": 1.0}, source="human")
        assert not result["ok"]
        assert "bogus_param" in result["errors"][0]
