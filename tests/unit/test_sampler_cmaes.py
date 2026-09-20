"""CMA-ES sampler 测试（计划内缺口 5）。

计划写"TPE/CMA-ES"，此前只实现了 TPE。本文件验证 sampler 参数通路。
"""

from __future__ import annotations

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _recipe(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm", "bounds": [15.0, 30.0]}},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


def test_cmaes_sampler_runs(tmp_path):
    from rfauto.optimization.optimizer import run_optimization

    result = run_optimization(
        _recipe(tmp_path), adapter_name="fake", max_trials=4, sampler="cmaes",
    )
    assert result["ok"], result.get("errors")
    assert result["sampler"] == "cmaes"
    assert result["trials_completed"] >= 1
    assert result["best_cost"] is not None


def test_tpe_default_unchanged(tmp_path):
    from rfauto.optimization.optimizer import run_optimization

    result = run_optimization(_recipe(tmp_path), adapter_name="fake", max_trials=3)
    assert result["ok"]
    assert result["sampler"] == "tpe"


def test_invalid_sampler_rejected(tmp_path):
    from rfauto.optimization.optimizer import run_optimization

    result = run_optimization(
        _recipe(tmp_path), adapter_name="fake", max_trials=2, sampler="grid",
    )
    assert result["ok"] is False
    assert any("未知 sampler" in e for e in result["errors"])


def test_service_start_tune_sampler_passthrough(tmp_path):
    from rfauto.service.api import start_tune

    result = start_tune(_recipe(tmp_path), adapter_name="fake", max_trials=3, sampler="cmaes")
    assert result["ok"]
