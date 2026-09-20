"""real_edt 真机路径补全——branchline / patch / far_field（清理项）。

补齐三个真机路径测试（此前只有 wilkinson 全链 + ADS 联动）。
时间敏感：branchline ~20min、patch ~25min（含远场几分钟）。
运行：pytest tests/real_edt/test_multi_model_real.py -m real_edt
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_edt

_RECIPES_DIR = Path(__file__).parent.parent.parent / "recipes"


def _run_real(recipe_path: Path, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from rfauto.service.api import run_once

    result = run_once(str(recipe_path), adapter_name="hfss")
    assert result["ok"], f"run_once 失败: {result.get('errors')}"
    return result


@pytest.mark.skipif(not (_RECIPES_DIR / "branchline_coupler_v1.yaml").exists(),
                    reason="配方缺失")
def test_branchline_real_chain(aedt_env_ready, tmp_path, monkeypatch):
    """branchline 4 端口真机全链：params.s4p 产出 + 三校验（R5 已手验，固化为用例）。"""
    result = _run_real(_RECIPES_DIR / "branchline_coupler_v1.yaml", tmp_path, monkeypatch)

    sr = result["solve_report"]
    assert sr["success"] is True, f"solve 未成功: {sr}"
    assert (Path(result["run_dir"]) / "results" / "params.s4p").exists(), "4 端口 Touchstone 缺失"

    metrics_path = Path(result["run_dir"]) / "results" / "metrics.json"
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    checks = data["checks"]
    assert checks["passivity_ok"] and checks["reciprocity_ok"]
    print(f"[branchline 真机] passes={sr['passes']}, delta_s={sr['delta_s_final']}")


@pytest.mark.skipif(not (_RECIPES_DIR / "patch_antenna_v1.yaml").exists(),
                    reason="配方缺失")
def test_patch_real_chain(aedt_env_ready, tmp_path, monkeypatch):
    """patch 天线真机全链：params.s2p 产出（R4 已手验，固化为用例）。"""
    result = _run_real(_RECIPES_DIR / "patch_antenna_v1.yaml", tmp_path, monkeypatch)

    sr = result["solve_report"]
    assert sr["success"] is True, f"solve 未成功: {sr}"
    assert (Path(result["run_dir"]) / "results" / "params.s2p").exists(), "2 端口 Touchstone 缺失"
    print(f"[patch 真机] passes={sr['passes']}, delta_s={sr['delta_s_final']}")


@pytest.mark.skipif(not (_RECIPES_DIR / "patch_antenna_v1.yaml").exists(),
                    reason="配方缺失")
def test_far_field_real(aedt_env_ready, tmp_path, monkeypatch):
    """真机远场提取：run_once 带 gain_db 目标 → gain_db_max 指标（get_far_field 真机路径）。"""
    import yaml

    recipe = yaml.safe_load((_RECIPES_DIR / "patch_antenna_v1.yaml").read_text(encoding="utf-8"))
    recipe.setdefault("objectives", []).append(
        {"metric": "gain_db", "band": [], "op": "min_above", "value": 0}
    )
    recipe_path = tmp_path / "patch_farfield.yaml"
    recipe_path.write_text(yaml.safe_dump(recipe, allow_unicode=True), encoding="utf-8")

    result = _run_real(recipe_path, tmp_path, monkeypatch)
    assert "gain_db_max" in result["metrics"], "远场指标未进入 metrics"
    assert result["metrics"]["gain_db_max"] > 0, "broadside 增益应 > 0 dBi"
    print(f"[远场真机] gain_db_max={result['metrics']['gain_db_max']:.2f} dBi")
