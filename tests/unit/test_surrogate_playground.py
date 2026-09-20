"""WP0.4 代理 Playground 单测：线性语料闭式对照（#175 教训：判定用
线性语料+精确期望，不赌拟合精度）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service.surrogate_playground import (
    playground_predict,
    playground_runs,
)


def _make_calibrated_run(
    tmp_path: Path, run_id: str = "20260101_000000_pg",
) -> Path:
    """线性语料：target_metric = 2*a + b（poly_ridge 一阶精确）。"""
    base = tmp_path / "runs" / run_id / "calibration"
    base.mkdir(parents=True)
    samples = []
    for i in range(12):
        a = 1.0 + i * 0.1
        b = 5.0 + (i % 4) * 0.5
        samples.append({
            "params": {"a_mm": a, "b_mm": b},
            "metrics": {"target_metric": 2.0 * a + b},
        })
    (base / "samples.json").write_text(json.dumps({
        "bounds": {"a_mm": [1.0, 2.1], "b_mm": [5.0, 6.5]},
        "objectives": [{"metric": "target_metric"}],
        "samples": samples,
    }), encoding="utf-8")
    # 校准产物存的拟合 config（一阶：线性语料无岭收缩高阶偏置）
    (base / "surrogate.json").write_text(json.dumps({
        "kind": "poly_ridge",
        "config": {"bounds": {"a_mm": [1.0, 2.1], "b_mm": [5.0, 6.5]},
                   "order": 1},
        "metric_keys": ["target_metric"],
    }), encoding="utf-8")
    (base / "campaign.json").write_text(json.dumps({
        "best_surrogate": "poly_ridge", "augment_rho": 0.95,
        "augment_verdict": "PASS", "n_samples": 12,
    }), encoding="utf-8")
    return tmp_path / "runs" / run_id


def test_predict_linear_exact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_calibrated_run(tmp_path)
    r = playground_predict("20260101_000000_pg", {"a_mm": 1.5, "b_mm": 5.5})
    assert r["ok"] and r["kind"] == "poly_ridge"
    assert r["predicted"]["target_metric"] == pytest.approx(
        2 * 1.5 + 5.5, abs=0.05)
    assert r["quality"]["verdict"] == "PASS" and r["quality"]["rho"] == 0.95
    assert "非真值" in r["honest_note"]
    # (1.5, 5.5) 是语料样本点 → 距离 0；非样本点距离必为正
    assert r["nearest_sample"]["normalized_distance"] == 0
    r2 = playground_predict("20260101_000000_pg",
                            {"a_mm": 1.55, "b_mm": 5.75})
    assert r2["ok"] and r2["nearest_sample"]["normalized_distance"] > 0


def test_predict_at_sample_point_distance_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_calibrated_run(tmp_path)
    # a=1.5, b=5.5 是语料第 6 个样本点（i=5）→ 距离恰为 0
    r = playground_predict("20260101_000000_pg", {"a_mm": 1.5, "b_mm": 5.5})
    assert r["ok"]
    assert r["nearest_sample"]["normalized_distance"] == 0
    assert r["nearest_sample"]["metrics"]["target_metric"] == pytest.approx(
        2 * 1.5 + 5.5, abs=1e-6)


def test_predict_clamps_and_midpoint_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_calibrated_run(tmp_path)
    r = playground_predict("20260101_000000_pg", {"a_mm": 99.0})
    assert r["ok"] and "a_mm" in r["clamped"]
    assert r["params"]["a_mm"] == 2.1  # 裁到上界
    assert 5.0 <= r["params"]["b_mm"] <= 6.5  # 缺参取中点
    assert r["bounds"]["b_mm"] == [5.0, 6.5]


def test_predict_missing_run_explicit_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = playground_predict("no_such_run", {})
    assert not r["ok"] and "无校准产物" in r["error"]


def test_playground_runs_lists_calibrated_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_calibrated_run(tmp_path)
    (tmp_path / "runs" / "empty_run").mkdir(parents=True)
    r = playground_runs()
    ids = [x["run_id"] for x in r["runs"]]
    assert "20260101_000000_pg" in ids and "empty_run" not in ids
    info = next(x for x in r["runs"] if x["run_id"] == "20260101_000000_pg")
    assert info["best_surrogate"] == "poly_ridge"
    assert info["verdict"] == "PASS" and info["n_samples"] == 12


def test_playground_endpoints(tmp_path, monkeypatch):
    """POST /api/playground/predict + GET /api/playground/runs 薄壳通。"""
    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app

    monkeypatch.chdir(tmp_path)
    _make_calibrated_run(tmp_path)
    (tmp_path / "runs").mkdir(exist_ok=True)
    client = TestClient(create_ui_app())
    r = client.get("/api/playground/runs").json()
    assert r["ok"] and len(r["runs"]) == 1
    r = client.post("/api/playground/predict", json={
        "run_id": "20260101_000000_pg",
        "params": {"a_mm": 1.5, "b_mm": 5.5}}).json()
    assert r["ok"]
    assert r["predicted"]["target_metric"] == pytest.approx(8.5, abs=0.05)
