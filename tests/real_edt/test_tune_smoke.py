"""real_edt: tune(hfss) 独立 2-trial smoke。

setup 通道（configure_setup→solve）已随 R3/R5 真机验证，本文件补上
"tune 独立通道真机冒烟"：2 个 TPE trial 走完整优化外环（参数建议→
写变量→求解→指标→cost）。

运行：pytest tests/real_edt/test_tune_smoke.py -m real_edt （约 5-15 分钟）
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.real_edt

_RECIPES_DIR = Path(__file__).parent.parent.parent / "recipes"


def test_tune_hfss_two_trial_smoke(aedt_env_ready, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from rfauto.optimization.optimizer import run_optimization

    recipe = yaml.safe_load(
        (_RECIPES_DIR / "wilkinson_pd_v1.yaml").read_text(encoding="utf-8")
    )
    # 轻量窄带 setup + 优化参数段（真机时间敏感）
    recipe["setup"] = {
        "solver": "DrivenModal",
        "freq_range_ghz": [2.3, 2.5],
        "points": 11,
        "convergence_delta": 0.1,
        "radiation_box": "open",
    }
    recipe["optimization"] = {
        "params": {"arm_len_mm": {"low": 19.5, "high": 21.5}},
    }
    recipe["objectives"] = [
        {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        {"metric": "s21_db", "band": [2.3, 2.5], "op": "min_above", "value": -4.0},
    ]
    path = tmp_path / "tune_smoke.yaml"
    path.write_text(yaml.safe_dump(recipe, allow_unicode=True), encoding="utf-8")

    result = run_optimization(path, adapter_name="hfss", max_trials=2)
    assert result["ok"], result.get("errors")
    assert result["trials_completed"] >= 1, "2-trial smoke 至少 1 个 COMPLETE"
    assert result["best_cost"] is not None
    print(
        f"[tune smoke] trials={result['trials_total']} "
        f"completed={result['trials_completed']} best_cost={result['best_cost']:.4f} "
        f"best_params={result['best_params']}"
    )
