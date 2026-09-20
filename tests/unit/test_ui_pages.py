"""UI 页面 service 契约单测（§10.22 补强第二批 #25；#90/#92 铁律回查）。

三页契约（全部走确定性 fixture，不读真实 runs/、不联网、不跑求解）：

- S 参数分析：sparams_series(db|deg) / external_sparams 的曲线 JSON 结构与
  边界（未知 mode、缺 results 显式报错）；手写 3 点 .s2p，S11=0.5 → -6.0206 dB。
- 成本时间线：cost_timeline 的 points/n_without_cost/latest_tune_* 契约；
  monkeypatch runs_stats.query_runs 提供确定性索引行，快照 objectives
  确定性重算 cost（-12 vs -15 → 3.0）。
- 报告中心：list_reports / report_content 的字段与 runs/*.md 路径白名单。

另加静态守卫：ui/server.py 源码不得出现 YAML/CSV/JSON 解析或指标/几何计算
（解析与计算一律下沉 service），以及被下沉的 recipe_create /
model3d_for_params 两函数的行为契约。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rfauto.service import ui_service

RUN_ID_SP = "20260101_000000_sp"
RUN_ID_TL = "20260101_000000_tl"
RUN_ID_RP = "20260101_000000_rp"

# 3 点 2 端口 Touchstone v1：S11=S22=0.5（→ -6.0206 dB），S21=S12=0.7。
_S2P = """# GHz S RI R 50
1.0  0.5 0.0  0.7 0.0  0.7 0.0  0.5 0.0
2.0  0.5 0.0  0.7 0.0  0.7 0.0  0.5 0.0
3.0  0.5 0.0  0.7 0.0  0.7 0.0  0.5 0.0
"""

_OBJECTIVES = [
    {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    (tmp_path / "runs").mkdir(exist_ok=True)
    yield


def _make_sparams_run(tmp_path: Path, run_id: str = RUN_ID_SP) -> Path:
    results = tmp_path / "runs" / run_id / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "data.s2p").write_text(_S2P, encoding="utf-8")
    return results


def _make_snapshot_run(tmp_path: Path, run_id: str) -> Path:
    run = tmp_path / "runs" / run_id
    run.mkdir(parents=True, exist_ok=True)
    (run / "recipe.snapshot.yaml").write_text(
        yaml.safe_dump({"objectives": _OBJECTIVES}), encoding="utf-8")
    return run


class TestSparamsPageContract:
    """S 参数分析页（3.1）：曲线序列 JSON 契约。"""

    def test_db_series_shape(self, tmp_path):
        _make_sparams_run(tmp_path)
        r = ui_service.sparams_series(RUN_ID_SP, "db")
        assert r["ok"] and r["run_id"] == RUN_ID_SP and r["mode"] == "db"
        assert r["warning"] is None
        assert sorted(c["name"] for c in r["curves"]) == [
            "S11", "S12", "S21", "S22"]  # 2 端口 S 行列全对
        for c in r["curves"]:
            assert set(c) == {"file", "name", "freq_ghz", "y"}
            assert c["file"] == "data.s2p"
            assert len(c["freq_ghz"]) == 3 and len(c["y"]) == 3
            assert c["freq_ghz"] == [1.0, 2.0, 3.0]
        s11 = next(c for c in r["curves"] if c["name"] == "S11")
        assert all(abs(v - (-6.0206)) < 1e-3 for v in s11["y"])

    def test_deg_mode_phase_contract(self, tmp_path):
        _make_sparams_run(tmp_path)
        r = ui_service.sparams_series(RUN_ID_SP, "deg")
        assert r["ok"] and r["mode"] == "deg"
        assert len(r["curves"]) == 4
        s11 = next(c for c in r["curves"] if c["name"] == "S11")
        # S11 为正实数 → 相位 0°，解缠绕后仍为 0
        assert all(abs(v) < 1e-6 for v in s11["y"])

    def test_unknown_mode_is_explicit_error(self, tmp_path):
        r = ui_service.sparams_series(RUN_ID_SP, "nope")
        assert r["ok"] is False and "未知 mode" in r["errors"][0]

    def test_missing_results_is_explicit_error(self, tmp_path):
        r = ui_service.sparams_series("no_such_run", "db")
        assert r["ok"] is False and "无 results 产物" in r["errors"][0]

    def test_external_sparams_contract(self, tmp_path):
        ext = tmp_path / "ext.s2p"
        ext.write_text(_S2P, encoding="utf-8")
        r = ui_service.external_sparams(str(ext), "db")
        assert r["ok"] and r["file"] == "ext.s2p" and r["mode"] == "db"
        assert r["n_points"] == 3 and len(r["curves"]) == 4
        assert set(r["curves"][0]) == {"file", "name", "freq_ghz", "y"}
        # mode 非法复用同一显式错误口径
        assert ui_service.external_sparams(str(ext), "bad")["ok"] is False


class TestCostTimelinePageContract:
    """成本时间线页（3.4）：points 升序 + 无快照计数 + 最新 trials。"""

    def _patch_query(self, monkeypatch, rows):
        monkeypatch.setattr(
            "rfauto.service.runs_stats.query_runs",
            lambda **kw: {"ok": True, "n_runs": len(rows), "runs": rows})

    def test_points_ascending_with_deterministic_cost(self, tmp_path, monkeypatch):
        _make_snapshot_run(tmp_path, "20260101_000001_a")
        _make_snapshot_run(tmp_path, "20260101_000002_b")
        # query_runs 返回时间倒序（新→旧）；cost_timeline 反转为时间升序
        self._patch_query(monkeypatch, [
            {"run_id": "20260101_000002_b", "model": "wilkinson_power_divider",
             "adapter": "fake", "status": "ok",
             "timestamp": "2026-01-01T00:00:02",
             "metrics": {"s11_db_max_in_band": -12.0}},  # -12 > -15 → cost 3.0
            {"run_id": "20260101_000001_a", "model": "wilkinson_power_divider",
             "adapter": "fake", "status": "ok",
             "timestamp": "2026-01-01T00:00:01",
             "metrics": {"s11_db_max_in_band": -18.0}},  # 达标 → cost 0.0
        ])
        r = ui_service.cost_timeline()
        assert r["ok"] and r["n_without_cost"] == 0
        assert [p["run_id"] for p in r["points"]] == [
            "20260101_000001_a", "20260101_000002_b"]
        a, b = r["points"]
        assert set(a) == {"run_id", "timestamp", "adapter", "model", "cost"}
        assert a["cost"] == 0.0
        assert b["cost"] == pytest.approx(3.0)
        assert a["adapter"] == "fake" and a["model"] == "wilkinson_power_divider"
        assert a["timestamp"] == "2026-01-01T00:00:01"
        assert r["latest_tune_run_id"] is None and r["latest_tune_trials"] == []

    def test_run_without_snapshot_counted_not_plotted(self, tmp_path, monkeypatch):
        # metrics 有但配方快照缺失 → cost 无法确定性重算，只计数不画点
        self._patch_query(monkeypatch, [
            {"run_id": "no_snap", "model": "wilkinson_power_divider",
             "adapter": "fake", "status": "ok", "timestamp": "t",
             "metrics": {"s11_db_max_in_band": -12.0}}])
        r = ui_service.cost_timeline()
        assert r["ok"] and r["points"] == [] and r["n_without_cost"] == 1

    def test_query_error_passthrough(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "rfauto.service.runs_stats.query_runs",
            lambda **kw: {"ok": False, "errors": ["runs 索引不存在"]})
        r = ui_service.cost_timeline()
        assert r == {"ok": False, "errors": ["runs 索引不存在"]}

    def test_latest_tune_trials_attached(self, tmp_path, monkeypatch):
        trials = tmp_path / "runs" / RUN_ID_TL / "trials"
        trials.mkdir(parents=True)
        for n in (1, 2):
            (trials / f"trial_{n}.json").write_text(
                json.dumps({"trial_number": n, "cost": float(n)}),
                encoding="utf-8")
        self._patch_query(monkeypatch, [])
        r = ui_service.cost_timeline()
        assert r["latest_tune_run_id"] == RUN_ID_TL
        assert [t["trial_number"] for t in r["latest_tune_trials"]] == [1, 2]


class TestReportsPageContract:
    """报告中心页（3.5）：清单字段 + runs/*.md 路径白名单。"""

    def _make_reports(self, tmp_path: Path) -> Path:
        run = tmp_path / "runs" / RUN_ID_RP
        (run / "calibration").mkdir(parents=True, exist_ok=True)
        (run / "report.md").write_text("# 主报告", encoding="utf-8")
        (run / "sim_ci_report.md").write_text("# 一致性报告", encoding="utf-8")
        (run / "calibration" / "report.md").write_text("# 校准报告", encoding="utf-8")
        (run / "meta.json").write_text(json.dumps(
            {"model": "wilkinson_power_divider"}), encoding="utf-8")
        return run

    def test_list_reports_contract(self, tmp_path):
        self._make_reports(tmp_path)
        r = ui_service.list_reports()
        assert r["ok"]
        by_kind = {e["kind"]: e for e in r["reports"]}
        assert set(by_kind) == {"run", "sim_ci", "calibration"}
        for e in r["reports"]:
            assert set(e) == {"run_id", "kind", "model", "path",
                              "size_bytes", "mtime"}
            assert e["run_id"] == RUN_ID_RP
            assert e["model"] == "wilkinson_power_divider"
            assert e["path"].startswith("runs/") and e["size_bytes"] > 0
            assert e["mtime"] > 0

    def test_list_reports_empty_when_no_reports(self, tmp_path):
        assert ui_service.list_reports() == {"ok": True, "reports": []}

    def test_report_content_contract(self, tmp_path):
        run = self._make_reports(tmp_path)
        rel = (run / "report.md").relative_to(tmp_path)
        r = ui_service.report_content(str(rel))
        assert r["ok"] and "主报告" in r["content"]
        assert r["path"] == (run / "report.md").as_posix()

    def test_report_content_rejects_outside_runs(self, tmp_path):
        outside = tmp_path / "outside.md"
        outside.write_text("# 越界", encoding="utf-8")
        r = ui_service.report_content(str(outside))
        assert r["ok"] is False and "路径越界" in r["errors"][0]

    def test_report_content_rejects_non_md(self, tmp_path):
        run = self._make_reports(tmp_path)
        (run / "metrics.json").write_text("{}", encoding="utf-8")
        r = ui_service.report_content(
            str((run / "metrics.json").relative_to(tmp_path)))
        assert r["ok"] is False and "不是 runs/ 下的 .md" in r["errors"][0]

    def test_report_content_missing_file(self, tmp_path):
        r = ui_service.report_content("runs/nope/report.md")
        assert r["ok"] is False
class TestSunkServiceFunctions:
    """被下沉的写面/计算函数：UI 端点现在只传参，契约在 service。"""

    def test_recipe_create_writes_yaml_and_roundtrips(self, tmp_path):
        path = tmp_path / "new_recipe.yaml"
        data = {
            "model": "wilkinson_power_divider", "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
            "objectives": list(_OBJECTIVES), "optimization": {},
        }
        r = ui_service.recipe_create(path, data)
        assert r == {"ok": True, "path": str(path)}
        assert path.is_file()
        v = ui_service.recipe_view(path)
        assert v["ok"] and v["template_hint"] == "wilkinson"
        assert v["params"][0] == {
            "name": "arm_len_mm", "value": 20.5, "unit": "mm", "bounds": None}

    def test_recipe_create_empty_path_rejected(self):
        r = ui_service.recipe_create("", {"model": "wilkinson_power_divider"})
        assert r["ok"] is False and r["errors"]

    def test_model3d_for_params_without_recipe_file(self):
        spec = ui_service.model3d_for_params("wilkinson", {"arm_len_mm": 20.5})
        assert spec["ok"] and spec["template"] == "wilkinson"
        arm = next(b for b in spec["boxes"] if b["name"] == "arm_left")
        assert arm["stop_mm"][1] - arm["start_mm"][1] == pytest.approx(20.5)
        assert any(p["name"].startswith("Port1") for p in spec["ports"])


# 静态守卫口径：UI 层不得出现解析库调用或指标/几何计算（HTTP body 解码的
# await request.json() 不算——那是传输层解码，不是数据解释）。
_FORBIDDEN_UI_TOKENS = (
    "import yaml", "safe_load", "safe_dump",          # YAML 解析/序列化
    "import csv", "csv.reader", "csv.DictReader",      # CSV 解析
    "json.loads", "json.load(",                        # JSON 解析
    "import_touchstone",                               # Touchstone 解析
    "geometry_spec",                                   # 几何计算内核
    "np.log10", "import numpy",                        # 指标计算
)


class TestUiLayerStaticGuard:
    def test_server_source_has_no_parsing_or_computation(self):
        import rfauto.ui.server as server_mod

        src = Path(server_mod.__file__).read_text(encoding="utf-8")
        hits = [t for t in _FORBIDDEN_UI_TOKENS if t in src]
        assert hits == [], (
            f"UI 层出现解析/计算，应下沉 service（#90/#92）: {hits}")
        # 守卫非空转：坏样本必须命中（防 token 表笔误退化成永真）
        bad = ("import yaml\n"
               "from rfauto.adapters.openems_templates import geometry_spec\n")
        assert [t for t in _FORBIDDEN_UI_TOKENS if t in bad]
class TestPageEndpointsContract:
    """三页 HTTP 薄壳：契约注记 contract_check 打通（service 契约已验证）。"""

    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        _make_sparams_run(tmp_path)
        report_run = tmp_path / "runs" / RUN_ID_RP
        report_run.mkdir(parents=True, exist_ok=True)
        (report_run / "report.md").write_text("# r", encoding="utf-8")
        monkeypatch.setattr(
            "rfauto.service.runs_stats.query_runs",
            lambda **kw: {"ok": True, "n_runs": 0, "runs": []})
        return TestClient(create_ui_app())

    def test_sparams_page_contract_annotation(self, client):
        r = client.get(f"/api/sparams/{RUN_ID_SP}", params={"mode": "db"}).json()
        assert r["ok"] and r["curves"]
        cc = r["contract_check"]
        assert cc["contract"] == "sparams_series"
        assert cc["ok"] is True, cc["errors"]

    def test_cost_timeline_page_contract_annotation(self, client):
        r = client.get("/api/cost_timeline").json()
        assert r["ok"] and r["points"] == []
        cc = r["contract_check"]
        assert cc["contract"] == "cost_timeline"
        assert cc["ok"] is True, cc["errors"]

    def test_reports_page_contract_annotation(self, client):
        r = client.get("/api/reports").json()
        assert r["ok"] and any(e["kind"] == "run" for e in r["reports"])
        cc = r["contract_check"]
        assert cc["contract"] == "reports_list"
        assert cc["ok"] is True, cc["errors"]

    def test_recipe_create_endpoint_thin_shell(self, client):
        r = client.post("/api/recipe", json={
            "path": "imported.yaml",
            "create": {
                "model": "wilkinson_power_divider", "schema_version": 1,
                "params": {"arm_len_mm": {"value": 21.0, "unit": "mm"}},
                "setup": {}, "objectives": [], "optimization": {}},
        }).json()
        assert r["ok"] and Path("imported.yaml").is_file()
        assert client.get(
            "/api/recipe", params={"path": "imported.yaml"}).json()[
                "params"][0]["value"] == 21.0

    def test_model3d_post_endpoint_thin_shell(self, client):
        r = client.post("/api/model3d", json={
            "template": "patch", "params": {"patch_len_mm": 41.0}}).json()
        assert r["ok"] and any(b["name"] == "patch" for b in r["boxes"])
