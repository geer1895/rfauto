"""golden 容差回归测试（计划内缺口 3）。

tests/golden/ 此前为空目录。本文件用 wilkinson fake 解析指标建立基线，
以容差断言防指标漂移（解析模型改动 / 依赖升级导致的静默数值变化）。

重新生成基线：设环境变量 RFAUTO_REGEN_GOLDEN=1 后运行本文件，
测试会以当前指标覆写基线并自行通过。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

GOLDEN_PATH = Path(__file__).parent.parent / "golden" / "wilkinson_fake_baseline.json"


def _recipe(tmp_path: Path) -> Path:
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 201},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "min_above", "value": -4.0},
            {"metric": "iso_s23_db", "band": [2.3, 2.5], "op": "min_above", "value": 20},
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


@pytest.fixture()
def current_metrics(tmp_path, monkeypatch):
    """在隔离 CWD 中跑一次 wilkinson fake 全链，返回 metrics。"""
    monkeypatch.chdir(tmp_path)
    from rfauto.service.api import run_once

    result = run_once(_recipe(tmp_path), adapter_name="fake")
    assert result["ok"], result.get("errors")
    return result["metrics"]


@pytest.mark.skipif(
    not GOLDEN_PATH.exists(), reason="golden 基线缺失（tests/golden/ 为空）"
)
def test_golden_metrics_within_tolerance(current_metrics, monkeypatch):
    """当前指标与基线逐项对比，|delta| 超容差即失败。"""
    if os.environ.get("RFAUTO_REGEN_GOLDEN") == "1":
        _regen(current_metrics)
        pytest.skip("RFAUTO_REGEN_GOLDEN=1：基线已按当前指标重写")

    baseline = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    tol_cfg = baseline.get("tolerances", {})
    default_tol = float(tol_cfg.get("default", 0.25))

    golden_metrics = baseline["metrics"]
    # 共有指标必须逐项对齐
    for name, expected in golden_metrics.items():
        assert name in current_metrics, f"指标 {name} 已从结果中消失（漂移）"
        tol = float(tol_cfg.get(name, default_tol))
        actual = current_metrics[name]
        delta = abs(actual - expected)
        assert delta <= tol, (
            f"golden 漂移: {name} 期望 {expected:.4f} (±{tol}), 实际 {actual:.4f}, "
            f"|delta|={delta:.4f}。若为有意变更，设 RFAUTO_REGEN_GOLDEN=1 重写基线"
        )

    # 新增指标不阻断但要有容差意识：提示重写基线
    extra = set(current_metrics) - set(golden_metrics)
    if extra:
        pytest.fail(
            f"出现基线外的新指标 {sorted(extra)}：确认后设 RFAUTO_REGEN_GOLDEN=1 重写基线"
        )


def _regen(metrics: dict) -> None:
    baseline = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    baseline["metrics"] = metrics
    GOLDEN_PATH.write_text(
        json.dumps(baseline, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def test_golden_baseline_file_shape():
    """基线文件结构自检：防止基线本身被误改坏。"""
    assert GOLDEN_PATH.exists(), "tests/golden/wilkinson_fake_baseline.json 不应缺失"
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert data["model"] == "wilkinson_power_divider"
    assert data["adapter"] == "fake"
    assert isinstance(data["metrics"], dict) and data["metrics"]
    assert "default" in data.get("tolerances", {})
