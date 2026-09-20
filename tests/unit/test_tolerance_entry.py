"""tolerance 孤岛接线测试——rfauto tolerance <recipe>。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _recipe(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -8},
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "min_above", "value": -6.0},
        ],
        "tolerance": {
            "n_samples": 20,
            "tolerances": {"arm_len_mm": 0.2},
        },
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestRunTolerance:
    def test_yield_analysis_produced(self, tmp_path):
        from rfauto.service.api import run_tolerance

        result = run_tolerance(_recipe(tmp_path), adapter_name="fake", n_samples=20)
        assert result["ok"], result.get("errors")
        assert result["n_samples"] == 20
        assert 0.0 <= result["yield_rate"] <= 1.0
        assert result["n_pass"] + result["n_fail"] == 20
        assert set(result["specs"]) == {"s11_db_max_in_band", "s21_db_mean_in_band"}
        assert "s11_db_max_in_band" in result["stats"]

    def test_tolerance_json_written(self, tmp_path):
        from rfauto.service.api import run_tolerance

        result = run_tolerance(_recipe(tmp_path), adapter_name="fake", n_samples=10)
        out = Path(result["run_dir"]) / "results" / "tolerance.json"
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["yield_rate"] == result["yield_rate"]

    def test_missing_tolerances_rejected(self, tmp_path):
        recipe = {
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
        }
        path = tmp_path / "r.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        from rfauto.service.api import run_tolerance

        result = run_tolerance(path, adapter_name="fake")
        assert result["ok"] is False
        assert any("公差" in e for e in result["errors"])

    def test_unknown_tolerance_param_rejected(self, tmp_path):
        recipe = yaml.safe_load(_recipe(tmp_path).read_text(encoding="utf-8"))
        recipe["tolerance"]["tolerances"] = {"no_such_param": 0.1}
        path = tmp_path / "r2.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        from rfauto.service.api import run_tolerance

        result = run_tolerance(path, adapter_name="fake")
        assert result["ok"] is False


class TestToleranceCli:
    def test_cli_tolerance(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app, ["tolerance", str(_recipe(tmp_path)), "-n", "10"]
        )
        assert result.exit_code == 0, result.output
        assert "良率" in result.output
