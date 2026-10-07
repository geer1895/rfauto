"""PR-6 战役仪表盘单测（service/campaign_dashboard_service.py + 端点）。"""

from __future__ import annotations

import json

import pytest


def _write_trial(run_dir, number: int, params: dict, cost: float) -> None:
    tdir = run_dir / "trials"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"trial_{number:04d}.json").write_text(
        json.dumps({"trial_number": number, "params": params,
                    "metrics": {}, "cost": cost}),
        encoding="utf-8")


@pytest.fixture()
def campaign_run(tmp_path, monkeypatch):
    """tmp runs/<id>：5 trial 双参数成本面（cost=x+y），chdir 隔离（#144）。"""
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "runs" / "camp1"
    for i, (x, y) in enumerate([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0),
                                (1.0, 1.0), (0.5, 0.5)]):
        _write_trial(run_dir, i, {"w_mm": x, "er": y}, cost=x + y)
    return run_dir


class TestServiceFace:
    def test_shape_and_best(self, campaign_run):
        from rfauto.service.campaign_dashboard_service import campaign_dashboard

        r = campaign_dashboard("camp1")
        assert r["ok"]
        assert r["n_trials_used"] == 5
        assert r["params_source"] == "auto"
        assert (r["x_param"], r["y_param"]) == ("er", "w_mm")  # 字典序自动取前两
        assert r["best"]["trial_number"] == 0 and r["best"]["cost"] == 0.0
        assert r["table_truncated"] is False and r["table_rows"] == 5
        assert [t["trial_number"] for t in r["trials"]] == [0, 1, 2, 3, 4]

    def test_explicit_params_flagged(self, campaign_run):
        from rfauto.service.campaign_dashboard_service import campaign_dashboard

        r = campaign_dashboard("camp1", x_param="w_mm", y_param="er")
        assert r["params_source"] == "explicit"
        assert r["x_param"] == "w_mm" and r["y_param"] == "er"

    def test_cells_bin_cost_means(self, campaign_run):
        from rfauto.service.campaign_dashboard_service import campaign_dashboard

        r = campaign_dashboard("camp1", x_param="w_mm", y_param="er", grid_n=2)
        by_cell = {(c["i"], c["j"]): c for c in r["cells"]}
        assert by_cell[(0, 0)]["cost_mean"] == 0.0
        # (0.5,0.5) 按等宽分箱落 (1,1)，与 (1,1) 同格；格内 cost=[2.0(trial3), 1.0(trial4)]
        assert by_cell[(1, 1)]["n"] == 2
        assert by_cell[(1, 1)]["cost_mean"] == 1.5
        assert by_cell[(1, 1)]["cost_min"] == 1.0
        assert by_cell[(1, 1)]["best_trial"] == 4
        assert by_cell[(1, 0)]["n"] == 1 and by_cell[(0, 1)]["n"] == 1

    def test_missing_run_is_error(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.campaign_dashboard_service import campaign_dashboard

        r = campaign_dashboard("nope")
        assert r["ok"] is False and "不存在" in r["errors"][0]

    def test_no_trials_is_error(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs" / "empty").mkdir(parents=True)
        from rfauto.service.campaign_dashboard_service import campaign_dashboard

        r = campaign_dashboard("empty")
        assert r["ok"] is False and "无 trials" in r["errors"][0]

    def test_non_numeric_cost_excluded(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        run_dir = tmp_path / "runs" / "mixed"
        _write_trial(run_dir, 0, {"w_mm": 0.0, "er": 3.0}, cost=1.0)
        _write_trial(run_dir, 2, {"w_mm": 1.0, "er": 4.0}, cost=3.0)
        (run_dir / "trials" / "trial_0001.json").write_text(
            json.dumps({"trial_number": 1, "params": {"w_mm": 2.0, "er": 3.66},
                        "cost": None}),
            encoding="utf-8")
        from rfauto.service.campaign_dashboard_service import campaign_dashboard

        r = campaign_dashboard("mixed")
        assert r["ok"] and r["n_trials_used"] == 2 and r["n_trials_total"] == 3
        assert [t["trial_number"] for t in r["trials"]] == [0, 2]

    def test_single_numeric_param_is_error(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        run_dir = tmp_path / "runs" / "onep"
        _write_trial(run_dir, 0, {"w_mm": 1.0}, cost=1.0)
        _write_trial(run_dir, 1, {"w_mm": 2.0}, cost=2.0)
        from rfauto.service.campaign_dashboard_service import campaign_dashboard

        r = campaign_dashboard("onep")
        assert r["ok"] is False and "不足 2 个" in r["errors"][0]

    def test_non_spread_param_is_error(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        run_dir = tmp_path / "runs" / "flat"
        _write_trial(run_dir, 0, {"w_mm": 1.0, "er": 2.0}, cost=1.0)
        _write_trial(run_dir, 1, {"w_mm": 1.0, "er": 3.0}, cost=2.0)
        from rfauto.service.campaign_dashboard_service import campaign_dashboard

        r = campaign_dashboard("flat")
        assert r["ok"] is False and "无展宽" in r["errors"][0]

    def test_equal_cost_missing_trial_number_no_typeerror(self, monkeypatch, tmp_path):
        """S2-1/W4c 回归钉：等 cost + 缺 trial_number（#320 导入面使外来
        trial json 真实可达）——best=min 的裸元组比较原炸
        `TypeError: '<' not supported between 'NoneType' and 'int'`（服务无
        try 兜底、UI route 直连 → 确定性 500）。修后：200 信封且 best 确定
        （缺号按 +inf 排末位，有号者胜出）。"""
        monkeypatch.chdir(tmp_path)
        run_dir = tmp_path / "runs" / "w4c"
        tdir = run_dir / "trials"
        tdir.mkdir(parents=True)
        # 外来 trial 文件：无 trial_number 键（#320 形态）
        (tdir / "trial_0000.json").write_text(
            json.dumps({"params": {"w_mm": 0.0, "er": 3.0}, "cost": 1.0}),
            encoding="utf-8")
        _write_trial(run_dir, 1, {"w_mm": 1.0, "er": 4.0}, cost=1.0)  # 同 cost
        from rfauto.service.campaign_dashboard_service import campaign_dashboard

        r = campaign_dashboard("w4c")
        assert r["ok"] is True and r["n_trials_used"] == 2
        # 缺号者排序末位：best 确定性落在有 trial_number 的一侧
        assert r["best"]["trial_number"] == 1 and r["best"]["cost"] == 1.0
        # 表排序保持 `or 0` 历史口径：缺号行按 0 排最前
        assert [t["trial_number"] for t in r["trials"]] == [None, 1]


class TestHttpEndpoint:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_trial(tmp_path / "runs" / "http1", 0, {"a": 0.0, "b": 1.0}, 2.0)
        _write_trial(tmp_path / "runs" / "http1", 1, {"a": 1.0, "b": 0.0}, 3.0)
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        return TestClient(create_ui_app())

    def test_dashboard_endpoint(self, client):
        r = client.get("/api/runs/http1/dashboard").json()
        assert r["ok"] and r["n_trials_used"] == 2
        assert r["trials"][0]["cost"] == 2.0

    def test_missing_run_error_passthrough(self, client):
        r = client.get("/api/runs/nope/dashboard").json()
        assert r["ok"] is False

    def test_index_serves_campaign_view(self, client):
        html = client.get("/").text
        assert 'id="view-campaign"' in html and 'data-v="campaign"' in html
