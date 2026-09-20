"""NSGA-II 多目标入口测试（计划内缺口 2）。

验收口径："双目标出 Pareto 前沿"。库（multiobj_backend）与测试此前已备，
本文件验证生产入口 run_multi_optimization / start_tune_multi / CLI --multi。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _dual_obj_recipe(tmp_path: Path) -> Path:
    """双目标配方：带宽最大 + 回损最小（fake 解析模型对 arm_len 有真实响应）。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm", "bounds": [15.0, 30.0]}},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -20},
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "min_above", "value": -3.0},
        ],
    }
    path = tmp_path / "recipe_dual.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestRunMultiOptimization:
    def test_pareto_front_produced(self, tmp_path):
        from rfauto.optimization.optimizer import run_multi_optimization

        result = run_multi_optimization(
            _dual_obj_recipe(tmp_path), adapter_name="fake", n_gen=3, pop_size=6,
        )
        assert result["ok"], result.get("errors")
        assert result["algorithm"] == "nsga2"
        assert result["n_pareto"] >= 1
        assert len(result["pareto_points"]) == result["n_pareto"]
        # 目标名与参数回填
        assert result["objective_names"] == ["s11_db", "s21_db"]
        for pt in result["pareto_points"]:
            assert set(pt["params"]) == {"arm_len_mm"}
            assert 15.0 <= pt["params"]["arm_len_mm"] <= 30.0, "解必须落在参数边界内"
            assert set(pt["objectives"]) == {"s11_db", "s21_db"}

    def test_pareto_plot_written(self, tmp_path):
        from rfauto.optimization.optimizer import run_multi_optimization

        result = run_multi_optimization(
            _dual_obj_recipe(tmp_path), adapter_name="fake", n_gen=2, pop_size=4,
        )
        plot = Path(result["run_dir"]) / "results" / "figs" / "pareto_front.png"
        assert plot.exists(), "双目标必须产出 Pareto 前沿图"

    def test_meta_and_index_registered(self, tmp_path):
        from rfauto.optimization.optimizer import run_multi_optimization

        result = run_multi_optimization(
            _dual_obj_recipe(tmp_path), adapter_name="fake", n_gen=2, pop_size=4,
        )
        import json
        meta = json.loads(
            (Path(result["run_dir"]) / "meta.json").read_text(encoding="utf-8")
        )
        assert meta["status"] == "done"
        assert meta["algorithm"] == "nsga2"

    def test_single_objective_rejected(self, tmp_path):
        """单目标配方应显式报错（应走 TPE 通道）。"""
        recipe = {
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"value": 20.5, "unit": "mm", "bounds": [15.0, 30.0]}},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
        }
        path = tmp_path / "r.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        from rfauto.optimization.optimizer import run_multi_optimization

        result = run_multi_optimization(path, adapter_name="fake", n_gen=2, pop_size=4)
        assert result["ok"] is False
        assert any("至少 2 个" in e for e in result["errors"])

    def test_no_params_rejected(self, tmp_path):
        recipe = {
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": 20.5},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
                {"metric": "s21_db", "band": [2.3, 2.5], "op": "min_above", "value": -3.0},
            ],
        }
        path = tmp_path / "r.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        from rfauto.optimization.optimizer import run_multi_optimization

        result = run_multi_optimization(path, adapter_name="fake")
        assert result["ok"] is False


class TestServiceAndCli:
    def test_start_tune_multi(self, tmp_path):
        from rfauto.service.api import start_tune_multi

        result = start_tune_multi(
            _dual_obj_recipe(tmp_path), adapter_name="fake", n_gen=2, pop_size=4,
        )
        assert result["ok"], result.get("errors")
        assert result["n_pareto"] >= 1

    def test_cli_tune_multi(self, tmp_path, monkeypatch):
        """CLI tune --multi 端到端（typer CliRunner）。"""
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app,
            ["tune", str(_dual_obj_recipe(tmp_path)), "--multi", "--n-gen", "2",
             "--pop-size", "4"],
        )
        assert result.exit_code == 0, result.output
        assert "多目标" in result.output
        assert "Pareto" in result.output

    def test_cli_tune_multi_single_objective_fails(self, tmp_path, monkeypatch):
        recipe = {
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"value": 20.5, "unit": "mm", "bounds": [15.0, 30.0]}},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
        }
        path = tmp_path / "r1.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["tune", str(path), "--multi", "--n-gen", "2"])
        assert result.exit_code != 0
