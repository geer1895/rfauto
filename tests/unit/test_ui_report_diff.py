"""PR-4 报告页深化回归钉（规格 §D-8 ③，2026-10-02 批）。

四层：
1. **service 钉**：ui/runs_diff.py 的递归 diff（added/removed/changed、
   list 整体比较、datetime JSON 化）、metrics Δ、口径判定与 verdict_hints
   （跨模型"口径不同"显式提示；S11 方向只按仓内既有 UI 口径「越低越好」）。
2. **endpoint 钉**：GET /api/runs/diff?a&b——ok 形状、缺参/缺 run 错误信封、
   **路由序**（api/runs/diff 必须先于 /api/runs/{run_id}，否则 "diff" 被
   参数路由吃掉——test_compare_endpoint_route_order 同款坑）、路由计数
   （58→59，docs 侧「58 路由」钉由主代理回填，本测试为代码侧事实钉）。
3. **UI 源码钉**：报告页 TOC（h2/h3 稳定 id + >3 节左侧栏 + scrollspy）、
   双 run 对比面板（双 select + 两栏 diff 表 + 单 PlotCard 叠图 + 口径警示）。
4. **runs/ 证据面（软钉）**：runs/pr34/ 本批 harness 在档时校验 golden
   与内嵌快照一致（缺席跳过——干净环境不依赖 runs）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from rfauto.ui.runs_diff import recursive_diff, runs_diff


def _make_run(
    runs: Path, run_id: str, *, model: str = "wilkinson_power_divider",
    adapter: str = "fake", metrics: dict | None = None,
    params: dict | None = None, setup: dict | None = None,
) -> Path:
    rd = runs / run_id
    (rd / "results").mkdir(parents=True, exist_ok=True)
    (rd / "meta.json").write_text(json.dumps({
        "run_id": run_id, "model": model, "adapter": adapter,
        "status": "done", "timestamp": "2026-10-02T00:00:00+00:00",
        "metrics": metrics if metrics is not None
        else {"s11_db_max_in_band": -11.3},
    }), encoding="utf-8")
    snap = {
        "model": model,
        "params": params if params is not None
        else {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "setup": setup if setup is not None else {"points": 11},
    }
    (rd / "recipe.snapshot.yaml").write_text(
        yaml.safe_dump(snap), encoding="utf-8")
    return rd


@pytest.fixture(autouse=True)
def _isolated_runs(tmp_path, monkeypatch):
    """runs/ 指到 tmp（RUNS_DIR 是 cwd 相对单源，chdir 即 runs_diff 与
    sparams_series 两侧对齐，无需分别 patch）。"""
    runs = tmp_path / "runs"
    runs.mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path)
    yield runs


class TestRecursiveDiff:
    def test_nested_changed_added_removed(self):
        a = {"params": {"x": {"value": 1}, "y": 2}, "setup": {"points": 11}}
        b = {"params": {"x": {"value": 3}, "z": 9}, "setup": {"points": 11}}
        d = recursive_diff(a, b)
        kinds = {(e["path"], e["kind"]) for e in d}
        assert ("params.x.value", "changed") in kinds
        assert ("params.y", "removed") in kinds
        assert ("params.z", "added") in kinds
        assert all(e["path"] != "setup.points" for e in d)  # 相等不报

    def test_list_compared_as_whole(self):
        d = recursive_diff({"obj": [{"metric": "s11_db", "band": [2, 3]}]},
                           {"obj": [{"metric": "s11_db", "band": [2, 4]}]})
        assert len(d) == 1
        assert d[0]["path"] == "obj"
        assert d[0]["kind"] == "changed"

    def test_datetime_jsonable(self):
        d = recursive_diff({"t": datetime(2026, 10, 2, 12, 0, 0)},
                           {"t": "2026-10-03T00:00:00"})
        assert d[0]["a"] == "2026-10-02T12:00:00"  # isoformat 后可比

    def test_identical_empty(self):
        assert recursive_diff({"a": 1}, {"a": 1}) == []


class TestRunsDiffService:
    def test_same_model_diff_params_and_metrics(self, _isolated_runs):
        runs = _isolated_runs
        _make_run(runs, "20261002_000001_aaaa",
                  metrics={"s11_db_max_in_band": -11.3},
                  params={"arm_len_mm": {"value": 20.5}})
        _make_run(runs, "20261002_000002_bbbb",
                  metrics={"s11_db_max_in_band": -15.2},
                  params={"arm_len_mm": {"value": 22.0}})
        d = runs_diff("20261002_000001_aaaa", "20261002_000002_bbbb")
        assert d["ok"]
        assert d["same_model"] is True and d["same_adapter"] is True
        pd = d["params_recursive_diff"]
        assert any(e["path"] == "params.arm_len_mm.value"
                   and e["a"] == 20.5 and e["b"] == 22.0 for e in pd)
        delta = d["metrics_delta"]["s11_db_max_in_band"]
        assert delta["a"] == -11.3 and delta["b"] == -15.2
        assert delta["delta"] == pytest.approx(-3.9)
        assert d["sparams_a"]["curves"] == []  # fake run 无 Touchstone，如实空
        # S11 方向提示（越低越好=仓内既有 UI 口径）
        assert any("b 好" in h for h in d["verdict_hints"])

    def test_cross_model_warns_caliber(self, _isolated_runs):
        runs = _isolated_runs
        _make_run(runs, "20261002_000001_aaaa")
        _make_run(runs, "20261002_000002_bbbb", model="patch_antenna",
                  adapter="openems")
        d = runs_diff("20261002_000001_aaaa", "20261002_000002_bbbb")
        assert d["ok"]
        assert d["same_model"] is False and d["same_adapter"] is False
        assert any("口径不同" in h for h in d["verdict_hints"])

    def test_missing_and_bad_ids(self, _isolated_runs):
        _make_run(_isolated_runs, "20261002_000001_aaaa")
        assert not runs_diff("nope", "20261002_000001_aaaa")["ok"]
        assert not runs_diff("20261002_000001_aaaa", "nope")["ok"]
        assert not runs_diff("", "20261002_000001_aaaa")["ok"]
        assert not runs_diff("../etc", "20261002_000001_aaaa")["ok"]

    def test_snapshot_missing_is_empty_diff(self, _isolated_runs):
        runs = _isolated_runs
        _make_run(runs, "20261002_000001_aaaa")
        rd = runs / "20261002_000002_bbbb"
        (rd / "results").mkdir(parents=True)
        (rd / "meta.json").write_text(json.dumps({
            "run_id": "20261002_000002_bbbb",
            "model": "wilkinson_power_divider", "adapter": "fake",
            "metrics": {}}), encoding="utf-8")
        d = runs_diff("20261002_000001_aaaa", "20261002_000002_bbbb")
        assert d["ok"]
        assert d["b"]["has_snapshot"] is False
        # A 有快照 B 无 → 差异如实整列（removed），不臆测
        assert any(e["kind"] == "removed" for e in d["params_recursive_diff"])


class TestRunsDiffEndpoint:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        runs.mkdir(exist_ok=True)
        _make_run(runs, "20261002_000001_aaaa",
                  metrics={"s11_db_max_in_band": -11.3},
                  params={"arm_len_mm": {"value": 20.5}})
        _make_run(runs, "20261002_000002_bbbb",
                  metrics={"s11_db_max_in_band": -15.2},
                  params={"arm_len_mm": {"value": 22.0}})
        return TestClient(create_ui_app())

    def test_diff_endpoint_ok_shape(self, client):
        r = client.get("/api/runs/diff", params={
            "a": "20261002_000001_aaaa", "b": "20261002_000002_bbbb"}).json()
        assert r["ok"]
        for key in ("params_recursive_diff", "metrics_delta",
                    "sparams_a", "sparams_b", "verdict_hints",
                    "same_model", "same_adapter"):
            assert key in r, key
        assert r["a"]["run_id"] == "20261002_000001_aaaa"
        assert r["metrics_delta"]["s11_db_max_in_band"]["delta"] == \
            pytest.approx(-3.9)

    def test_diff_endpoint_errors(self, client):
        r = client.get("/api/runs/diff").json()  # 缺参
        assert not r["ok"]
        r = client.get("/api/runs/diff", params={
            "a": "ghost", "b": "20261002_000002_bbbb"}).json()
        assert not r["ok"] and any("不存在" in e for e in r["errors"])

    def test_route_registered_before_run_id_param_route(self):
        """路由序硬钉：/api/runs/diff 先于 /api/runs/{run_id}，否则被吃。"""
        from starlette.routing import Route

        from rfauto.ui.server import create_ui_app

        app = create_ui_app(include_runs_mount=False)
        paths = [getattr(r, "path", None) for r in app.routes]
        assert "/api/runs/diff" in paths
        assert paths.index("/api/runs/diff") < \
            paths.index("/api/runs/{run_id}")
        # 端点计数事实钉：58（PR-4 前）→ 59（+diff）→ 63（ge8b Wave B：画廊/仪表盘/profile/队列四页，席B2/B3）
        n_routes = sum(1 for r in app.routes if isinstance(r, Route))
        assert n_routes == 63, n_routes

    def test_server_route_order_source_pin(self):
        src = (Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui"
               / "server.py").read_text(encoding="utf-8")
        assert src.index('Route("/api/runs/diff"') < \
            src.index('Route("/api/runs/{run_id}"')


class TestReportPageUiPins:
    """TOC + 双 run 对比面板源码钉（免 node）。"""

    _PAGES = (Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui"
              / "static" / "pages.js").read_text(encoding="utf-8")

    def test_toc_stable_ids_and_scrollspy(self):
        src = self._PAGES
        assert "function buildReportToc(" in src
        assert 'body.querySelectorAll("h2, h3")' in src  # marked 渲染后取节
        assert "heads.length <= 3" in src  # >3 节才出目录（规格口径）
        assert 'className = "report-toc"' in src
        assert 'addEventListener("scroll", onScroll' in src  # scrollspy
        assert "scrollIntoView" in src  # 目录点击跳转
        assert "sec-" in src  # 稳定 id 前缀

    def test_run_diff_panel_wiring(self):
        src = self._PAGES
        for needle in (
            "async function renderRunDiff(",
            '"/api/runs/diff?a="',
            'id=\'rd-a\'', "id='rd-b'", "id='rd-go'",
            "口径不同",  # 跨模型显式警示
            "metrics_delta", "params_recursive_diff",
            "sparams_a", "verdict_hints",
        ):
            assert needle in src, needle
        # 叠图走 PlotCard（PR-3 组件复用），非裸 echarts
        assert "T.plotCard(chartEl" in src


def test_pr34_golden_evidence_consistent():
    """runs/pr34/ 证据面在档时：harness 快照与内嵌金钉同源（软钉，缺席跳过）。"""
    from tests.unit.test_ui_plotcard import _GOLDEN

    evidence = Path(__file__).resolve().parents[2] / "runs" / "pr34" / \
        "golden_option_snapshot.json"
    if not evidence.exists():
        pytest.skip("runs/pr34/golden_option_snapshot.json 不在档（开发机证据面）")
    assert json.loads(evidence.read_text(encoding="utf-8")) == _GOLDEN
