"""UI 修复批（2026-09-15，用户看 UI 反馈）：报告中心图片白名单 + 优化洞察 run 分组。

项 2 裂图根因：report.md 里 ``![S11 Curve](results/figs/s11_curve.png)`` 是相对
报告文件的路径，前端在 ``/`` 页面渲染时按相对页面 URL 请求 ``/results/figs/...``
→ 404。修法：service 白名单解析（run_fig_file）+ 薄壳路由
``/api/runs/{run_id}/figs/{name:path}`` + 前端重写 img src；穿越/越界/缺失一律
None/404（前端占位"该 run 无此图"）。

项 3：run_once 类 run 无 trials/无 pareto_front.json 本就无 Pareto 数据（预期），
service 新增 pareto_runs() 三档分组（front > trials > single），前端据此分组下拉
并给人话空态。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.service import ui_service
from rfauto.service.ui_service import pareto_runs, report_content, run_fig_file

RUN_A = "20260101_000000_figrun"
RUN_B = "20260102_000000_paretofront"
RUN_C = "20260103_000000_trialsrun"
RUN_D = "20260104_000000_single"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


def _make_fig_run(tmp_path: Path, run_id: str = RUN_A) -> Path:
    run_dir = tmp_path / "runs" / run_id
    figs = run_dir / "results" / "figs"
    figs.mkdir(parents=True)
    (figs / "s11_curve.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16)
    (figs / "s21_curve.svg").write_text("<svg/>", encoding="utf-8")
    (figs / "notes.txt").write_text("not an image", encoding="utf-8")
    # 同 run 下 figs 之外的图：必须被白名单拒绝（只放 results/figs/）
    (run_dir / "results" / "secret.png").write_bytes(b"png")
    (run_dir / "report.md").write_text(
        "# report\n\n![S11 Curve](results/figs/s11_curve.png)\n\n"
        "![S21 Curve](results/figs/s21_curve.png)\n", encoding="utf-8")
    return run_dir


class TestRunFigWhitelist:
    def test_png_and_svg_resolved_inside_figs(self, tmp_path):
        run_dir = _make_fig_run(tmp_path)
        p = run_fig_file(RUN_A, "results/figs/s11_curve.png")
        assert p is not None and p.resolve() == (run_dir / "results" / "figs" / "s11_curve.png").resolve()
        assert run_fig_file(RUN_A, "results/figs/s21_curve.svg") is not None

    def test_bare_filename_gets_figs_subdir(self, tmp_path):
        _make_fig_run(tmp_path)
        p = run_fig_file(RUN_A, "s11_curve.png")
        assert p is not None and p.name == "s11_curve.png"

    def test_backslash_normalized(self, tmp_path):
        _make_fig_run(tmp_path)
        assert run_fig_file(RUN_A, "results\\figs\\s11_curve.png") is not None

    def test_missing_file_is_none(self, tmp_path):
        _make_fig_run(tmp_path)
        assert run_fig_file(RUN_A, "results/figs/nope.png") is None

    def test_non_image_suffix_rejected(self, tmp_path):
        _make_fig_run(tmp_path)
        assert run_fig_file(RUN_A, "results/figs/notes.txt") is None

    def test_outside_figs_subdir_rejected(self, tmp_path):
        _make_fig_run(tmp_path)
        # 同 run 内但不在 figs/ 下：白名单只放 results/figs/
        assert run_fig_file(RUN_A, "results/secret.png") is None

    @pytest.mark.parametrize("name", [
        "results/figs/../secret.png",           # 目录穿越出 figs
        "../../recipe.yaml",                    # 穿越出 run
        "results/figs/../../../etc/passwd",
        "/results/figs/s11_curve.png",          # 前导斜杠被剥离后仍需落 figs
    ])
    def test_traversal_rejected(self, tmp_path, name):
        _make_fig_run(tmp_path)
        p = run_fig_file(RUN_A, name)
        # 前导斜杠剥离后是合法 figs 路径 → 允许；其余穿越一律 None
        if name.startswith("/results/figs/s11"):
            assert p is not None
        else:
            assert p is None

    @pytest.mark.parametrize("rid", ["", ".", "..", "a/b", "a\\b", "..x", RUN_A + "/.."])
    def test_run_id_must_be_single_segment(self, tmp_path, rid):
        _make_fig_run(tmp_path)
        assert run_fig_file(rid, "results/figs/s11_curve.png") is None

    def test_nonexistent_run_is_none(self, tmp_path):
        assert run_fig_file("no_such_run", "results/figs/s11_curve.png") is None


class TestReportContentCarriesRunId:
    def test_run_id_attached(self, tmp_path):
        run_dir = _make_fig_run(tmp_path)
        c = report_content(str(run_dir / "report.md"))
        assert c["ok"] and c["run_id"] == RUN_A
        assert "results/figs/s11_curve.png" in c["content"]

    def test_still_rejects_outside_runs(self, tmp_path):
        other = tmp_path / "elsewhere.md"
        other.write_text("# x", encoding="utf-8")
        assert not report_content(str(other))["ok"]


class TestFigRoute:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        _make_fig_run(tmp_path)
        monkeypatch.setattr(
            "rfauto.service.runs_stats.query_runs",
            lambda **kw: {"ok": True, "n_runs": 0, "runs": []})
        return TestClient(create_ui_app())

    def test_route_registered_and_serves_png(self, client):
        r = client.get(f"/api/runs/{RUN_A}/figs/results/figs/s11_curve.png")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/png")
        assert r.content.startswith(b"\x89PNG")

    def test_route_serves_svg(self, client):
        r = client.get(f"/api/runs/{RUN_A}/figs/results/figs/s21_curve.svg")
        assert r.status_code == 200
        assert "svg" in r.headers["content-type"]

    def test_missing_fig_is_404_json_not_broken_image(self, client):
        r = client.get(f"/api/runs/{RUN_A}/figs/results/figs/s21_curve.png")
        assert r.status_code == 404
        body = r.json()
        assert body["ok"] is False and body["errors"]

    def test_traversal_is_404(self, client):
        r = client.get(f"/api/runs/{RUN_A}/figs/results/figs/../secret.png")
        assert r.status_code == 404
        r2 = client.get(f"/api/runs/{RUN_A}/figs/results/secret.png")
        assert r2.status_code == 404

    def test_non_image_is_404(self, client):
        r = client.get(f"/api/runs/{RUN_A}/figs/results/figs/notes.txt")
        assert r.status_code == 404

    def test_run_detail_route_not_shadowed(self, client):
        # 新增 /api/runs/{run_id}/figs/{name:path} 不得吞掉既有单段 /api/runs/{run_id}
        r = client.get(f"/api/runs/{RUN_A}")
        assert r.status_code == 200 and r.json()["ok"]

    def test_report_content_endpoint_has_run_id(self, client, tmp_path):
        p = str(tmp_path / "runs" / RUN_A / "report.md")
        r = client.get("/api/reports/content", params={"path": p}).json()
        assert r["ok"] and r["run_id"] == RUN_A


class TestParetoRuns:
    def _seed(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        # front：有 pareto_front.json
        (runs / RUN_B / "results").mkdir(parents=True)
        (runs / RUN_B / "results" / "pareto_front.json").write_text(
            json.dumps({"objective_names": ["a", "b"], "param_names": ["x", "y"],
                        "pareto_points": []}), encoding="utf-8")
        (runs / RUN_B / "meta.json").write_text(
            json.dumps({"model": "wilkinson", "adapter": "fake"}), encoding="utf-8")
        # trials：有 trials/*.json 但无前沿文件
        (runs / RUN_C / "trials").mkdir(parents=True)
        for i in range(3):
            (runs / RUN_C / "trials" / f"trial_{i:04d}.json").write_text(
                json.dumps({"trial_number": i}), encoding="utf-8")
        # single：单点仿真
        (runs / RUN_D / "results").mkdir(parents=True)
        (runs / RUN_D / "meta.json").write_text(
            json.dumps({"model": "patch", "adapter": "openems"}), encoding="utf-8")
        # 非目录文件不得混入
        (runs / "index.db").write_bytes(b"")

    def test_tiers_and_order(self, tmp_path):
        self._seed(tmp_path)
        d = pareto_runs()
        assert d["ok"]
        by = {r["run_id"]: r for r in d["runs"]}
        assert by[RUN_B]["tier"] == "front" and by[RUN_B]["has_pareto"] is True
        assert by[RUN_C]["tier"] == "trials" and by[RUN_C]["n_trials"] == 3
        assert by[RUN_D]["tier"] == "single" and by[RUN_D]["n_trials"] == 0
        # 优化 run 排前，单点排后
        order = [r["run_id"] for r in d["runs"]]
        assert order.index(RUN_B) < order.index(RUN_C) < order.index(RUN_D)
        assert by[RUN_B]["model"] == "wilkinson" and by[RUN_D]["adapter"] == "openems"

    def test_tier_stable_run_id_desc_within_tier(self, tmp_path):
        self._seed(tmp_path)
        runs = tmp_path / "runs"
        older = "20250101_000000_oldsingle"
        (runs / older).mkdir()
        order = [r["run_id"] for r in pareto_runs()["runs"] if r["tier"] == "single"]
        assert order == [RUN_D, older]

    def test_empty_when_no_runs_dir(self, tmp_path):
        assert pareto_runs() == {"ok": True, "runs": []}

    def test_limit_respected(self, tmp_path):
        self._seed(tmp_path)
        assert len(pareto_runs(limit=1)["runs"]) == 1

    def test_limit_applies_after_tier_sort_not_lexicographic(self, tmp_path):
        # 回归：字母命名目录字典序大于日期目录，若先切片会被它占满名额，
        # 把优化 run 截掉——limit 必须作用在 tier 排序之后
        self._seed(tmp_path)
        runs = tmp_path / "runs"
        for i in range(5):
            d = runs / f"wsteps_{i}"
            d.mkdir()
        d = pareto_runs(limit=4)
        got = [r["run_id"] for r in d["runs"]]
        assert RUN_B in got, "limit 截断不得丢掉 front 档优化 run"
        assert got[0] == RUN_B
        assert all(not g.startswith("wsteps") for g in got[:2])

    def test_route(self, tmp_path, monkeypatch):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        self._seed(tmp_path)
        monkeypatch.setattr(
            "rfauto.service.runs_stats.query_runs",
            lambda **kw: {"ok": True, "n_runs": 0, "runs": []})
        r = TestClient(create_ui_app()).get("/api/pareto_runs").json()
        assert r["ok"] and {x["tier"] for x in r["runs"]} == {"front", "trials", "single"}

    def test_single_point_run_pareto_view_is_explicit_error(self, tmp_path):
        # 单点 run 的 Pareto 视图本就不可算（预期）；前端据 tier=single 给人话空态
        self._seed(tmp_path)
        v = ui_service.pareto_view(RUN_D)
        assert not v["ok"] and v["errors"]


class TestServerThinShellGuardStillHolds:
    def test_new_routes_add_no_parsing(self):
        """新增两路由不得把解析/计算带进 UI 层（沿用 test_ui_pages 守卫口径）。"""
        import rfauto.ui.server as server_mod

        src = Path(server_mod.__file__).read_text(encoding="utf-8")
        for tok in ("json.loads", "import yaml", "geometry_spec", "import numpy"):
            assert tok not in src
        assert "run_fig_file" in src and "pareto_runs" in src
        assert '/api/runs/{run_id}/figs/{name:path}' in src
