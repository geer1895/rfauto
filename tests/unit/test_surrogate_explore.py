"""DP-16 U3 探索器单测：predict_with_std + explore + /api/explore 契约。

#139 钉：零网络零真机——合成 run fixture（线性语料闭式对照，#175 线性
语料+精确期望），monkeypatch.chdir 隔离 runs/（#144）。数值契约：
explore 曲线与直接 registry 调用逐位同。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.optimization.surrogate import surrogate_registry
from rfauto.service.surrogate_playground import explore

RUN_ID = "20260101_000000_pg"
BOUNDS = {"a_mm": [1.0, 2.1], "b_mm": [5.0, 6.5]}


def _make_calibrated_run(tmp_path: Path, kind: str = "poly_ridge") -> Path:
    """线性语料：target_metric = 2*a + b。"""
    base = tmp_path / "runs" / RUN_ID / "calibration"
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
        "bounds": BOUNDS,
        "objectives": [{"metric": "target_metric"}],
        "samples": samples,
    }), encoding="utf-8")
    config = {"bounds": {k: tuple(v) for k, v in BOUNDS.items()}}
    if kind == "poly_ridge":
        config["order"] = 1
        config["ridge_lambda"] = 0.0  # 线性语料精确恢复（#175：λ 收缩偏置）
    (base / "surrogate.json").write_text(json.dumps({
        "kind": kind, "config": config,
        "metric_keys": ["target_metric"],
    }), encoding="utf-8")
    (base / "campaign.json").write_text(json.dumps({
        "best_surrogate": kind, "augment_rho": 0.95,
        "augment_verdict": "PASS", "n_samples": 12,
    }), encoding="utf-8")
    return tmp_path / "runs" / RUN_ID


def _direct_model(kind: str):
    """与 explore 同参独立构建（契约对拍基准）。"""
    config = {"bounds": {k: tuple(v) for k, v in BOUNDS.items()}}
    if kind == "poly_ridge":
        config["order"] = 1
        config["ridge_lambda"] = 0.0
    model = surrogate_registry.create(kind, config=config)
    samples = []
    for i in range(12):
        a = 1.0 + i * 0.1
        b = 5.0 + (i % 4) * 0.5
        samples.append({
            "params": {"a_mm": a, "b_mm": b},
            "metrics": {"target_metric": 2.0 * a + b},
        })
    model.fit(samples)
    return model


# ── predict_with_std 透出面 ───────────────────────────────────────────────


def test_base_predict_with_std_none_for_plain_models():
    """poly_ridge 无 uncertainty → σ=None 如实（不伪造 0）。"""
    from rfauto.optimization.surrogate.poly_ridge import PolyRidgeSurrogate

    config = {"bounds": {k: tuple(v) for k, v in BOUNDS.items()},
              "order": 1, "ridge_lambda": 0.0}
    model = PolyRidgeSurrogate(config=config)
    samples = [{"params": {"a_mm": 1.0 + i * 0.1, "b_mm": 5.0 + (i % 4) * 0.5},
                "metrics": {"target_metric": 2.0 * (1.0 + i * 0.1)
                            + 5.0 + (i % 4) * 0.5}}
               for i in range(12)]
    model.fit(samples)
    pw = model.predict_with_std({"a_mm": 1.5, "b_mm": 5.5})
    mean, std = pw["target_metric"]
    assert std is None
    assert mean == pytest.approx(2 * 1.5 + 5.5, abs=1e-9)  # λ=0 线性精确恢复


def test_smt_kriging_predict_with_std_single_pass():
    """smt_kriging：predict_with_std 与 predict+uncertainty 两口径逐位同。"""
    pytest.importorskip("smt")
    from rfauto.optimization.surrogate.smt_kriging import SMTKrigingSurrogate

    samples = [{"params": {"a_mm": 1.0 + i * 0.1, "b_mm": 5.0 + (i % 4) * 0.5},
                "metrics": {"target_metric": 2.0 * (1.0 + i * 0.1)
                            + 5.0 + (i % 4) * 0.5}}
               for i in range(10)]
    model = SMTKrigingSurrogate(config={"bounds": BOUNDS})
    model.fit(samples)
    p = {"a_mm": 1.45, "b_mm": 5.6}
    pw = model.predict_with_std(p)
    assert pw["target_metric"][0] == model.predict(p)["target_metric"]
    assert pw["target_metric"][1] == model.uncertainty(p)["target_metric"]
    assert pw["target_metric"][1] > 0.0  # GP 外推点 σ>0（variance 已在，透出）


# ── explore 服务：1D/2D 参数扫描切片 ──────────────────────────────────────


def test_explore_1d_matches_direct_registry_bitwise(tmp_path, monkeypatch):
    """explore 曲线与直接 registry 调用逐位同（契约）。"""
    monkeypatch.chdir(tmp_path)
    _make_calibrated_run(tmp_path)
    fixed_b = 5.75
    r = explore(RUN_ID, {"b_mm": fixed_b}, {"axis": "a_mm", "n": 9})
    assert r["ok"] and r["kind"] == "poly_ridge"
    assert r["sweep"]["axes"] == ["a_mm"] and r["sweep"]["n"] == 9
    assert r["sweep"]["fixed"] == {"b_mm": pytest.approx(fixed_b)}
    model = _direct_model("poly_ridge")
    expect = [float(model.predict({"a_mm": v, "b_mm": fixed_b})["target_metric"])
              for v in r["sweep"]["axes_values"]["a_mm"]]
    assert r["curves"]["target_metric"]["mean"] == expect  # 逐位
    assert r["curves"]["target_metric"]["std"] is None
    assert r["has_variance"] is False
    assert "非 smt 族" in r["variance_note"]
    # 线性语料闭式对照（#175）：mean = 2a+b 逐点
    for v, m in zip(r["sweep"]["axes_values"]["a_mm"],
                    r["curves"]["target_metric"]["mean"], strict=True):
        assert m == pytest.approx(2.0 * v + fixed_b, abs=1e-6)


def test_explore_smt_has_variance(tmp_path, monkeypatch):
    """smt_kriging run：mean±std 全透出，engine 标签如实。"""
    pytest.importorskip("smt")
    monkeypatch.chdir(tmp_path)
    _make_calibrated_run(tmp_path, kind="smt_kriging")
    r = explore(RUN_ID, {"b_mm": 5.5}, {"axis": "a_mm", "n": 7})
    assert r["ok"] and r["engine"] == "smt_kriging"
    assert r["has_variance"] is True
    cur = r["curves"]["target_metric"]
    assert cur["std"] is not None and len(cur["std"]) == 7
    assert all(s > 0.0 for s in cur["std"])
    # 逐位：与直接 predict_with_std 同
    model = _direct_model("smt_kriging")
    for v, m, s in zip(r["sweep"]["axes_values"]["a_mm"], cur["mean"],
                       cur["std"], strict=True):
        dm, ds = model.predict_with_std({"a_mm": v, "b_mm": 5.5})["target_metric"]
        assert m == dm and s == ds
    assert "σ" in r["variance_note"]


def test_explore_2d_grid(tmp_path, monkeypatch):
    """2D 扫描 → n×n 嵌套网格，抽点与直接调用逐位同。"""
    monkeypatch.chdir(tmp_path)
    _make_calibrated_run(tmp_path)
    r = explore(RUN_ID, None, {"axes": ["a_mm", "b_mm"], "n": 5})
    assert r["ok"] and r["sweep"]["axes"] == ["a_mm", "b_mm"]
    grid = r["curves"]["target_metric"]["mean"]
    assert len(grid) == 5 and all(len(row) == 5 for row in grid)
    model = _direct_model("poly_ridge")
    vs_a = r["sweep"]["axes_values"]["a_mm"]
    vs_b = r["sweep"]["axes_values"]["b_mm"]
    for i in (0, 2, 4):
        for j in (0, 3):
            expect = float(model.predict(
                {"a_mm": vs_a[i], "b_mm": vs_b[j]})["target_metric"])
            assert grid[i][j] == expect  # 行=a 轴、列=b 轴


def test_explore_param_clamping(tmp_path, monkeypatch):
    """固定参数越界裁剪如实进 clamped 面语义（与 predict 同口径）。"""
    monkeypatch.chdir(tmp_path)
    _make_calibrated_run(tmp_path)
    r = explore(RUN_ID, {"b_mm": 99.0}, {"axis": "a_mm", "n": 5})
    assert r["ok"]
    assert r["sweep"]["fixed"]["b_mm"] == pytest.approx(6.5)  # 裁到上界


def test_explore_error_paths(tmp_path, monkeypatch):
    """无 sweep/未知轴/3 轴/缺 run → 显式报错不猜。"""
    monkeypatch.chdir(tmp_path)
    _make_calibrated_run(tmp_path)
    assert explore(RUN_ID, None, None)["ok"] is False
    assert "axis" in explore(RUN_ID, None, {} )["error"]
    r = explore(RUN_ID, None, {"axis": "not_a_param"})
    assert r["ok"] is False and "not_a_param" in r["error"]
    r = explore(RUN_ID, None, {"axes": ["a_mm", "b_mm", "c_mm"]})
    assert r["ok"] is False and "2D" in r["error"]
    assert explore("no_such_run", None, {"axis": "a_mm"})["ok"] is False


# ── /api/explore 端点契约（#139：进程内 TestClient，零网络零真机）─────────


def test_api_explore_endpoint_contract(tmp_path, monkeypatch):
    """POST /api/playground/explore：JSON schema + 数值与 service 逐位同。"""
    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app

    monkeypatch.chdir(tmp_path)
    _make_calibrated_run(tmp_path)
    (tmp_path / "runs").mkdir(exist_ok=True)
    client = TestClient(create_ui_app())
    resp = client.post("/api/playground/explore", json={
        "run_id": RUN_ID, "params": {"b_mm": 5.75},
        "sweep": {"axis": "a_mm", "n": 11}})
    assert resp.status_code == 200
    r = resp.json()
    # JSON schema 面契约
    assert {"ok", "run_id", "kind", "engine", "sweep", "curves",
            "has_variance", "variance_note", "quality",
            "honest_note"} <= set(r)
    assert {"axes", "n", "axes_values", "fixed"} <= set(r["sweep"])
    assert {"mean", "std"} <= set(r["curves"]["target_metric"])
    # 数值与 service 直接调用逐位同
    direct = explore(RUN_ID, {"b_mm": 5.75}, {"axis": "a_mm", "n": 11})
    assert r["curves"] == direct["curves"]
    assert r["sweep"]["axes_values"] == direct["sweep"]["axes_values"]
    # 旧端点不回归：predict/runs 仍通
    assert client.get("/api/playground/runs").json()["ok"] is True


def test_api_explore_error_contract(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app

    (tmp_path / "runs").mkdir(exist_ok=True)
    client = TestClient(create_ui_app())
    r = client.post("/api/playground/explore",
                    json={"run_id": "ghost", "sweep": {"axis": "a_mm"}}).json()
    assert r["ok"] is False and "无校准产物" in r["error"]
