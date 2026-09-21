"""人工核验 UI 测试：ui_service + starlette endpoints（E4c 尾巴批次）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rfauto.service.ui_service import (
    model3d_for_recipe,
    recipe_save,
    recipe_view,
    run_detail,
    sandbox_diff,
    sandbox_drafts,
    sandbox_promote,
    tune_trials,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    # 审批收件箱读路径接 RegistryDB 后，清掉注册表 DB 路径 env，
    # 防止本机 set 的 RFAUTO_REGISTRY_DB 把测试写入写到 tmp 之外（#144）
    monkeypatch.delenv("RFAUTO_REGISTRY_DB", raising=False)
    yield


def _recipe(tmp_path: Path) -> Path:
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
        "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


def _make_run(tmp_path: Path, run_id: str = "20260101_000000_test") -> Path:
    run_dir = tmp_path / "runs" / run_id
    (run_dir / "results" / "figs").mkdir(parents=True)
    (run_dir / "recipe.snapshot.yaml").write_text(
        yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"unit": "mm", "value": 20.5}},
        }), encoding="utf-8")
    (run_dir / "results" / "metrics.json").write_text(
        json.dumps({"s11_db": -15.2, "params": {"arm_len_mm": 20.5}}), encoding="utf-8")
    (run_dir / "results" / "figs" / "s11_curve.png").write_bytes(b"png")
    return run_dir


class TestRecipeViewSave:
    def test_view_form_shape(self, tmp_path):
        v = recipe_view(_recipe(tmp_path))
        assert v["ok"]
        assert v["template_hint"] == "wilkinson"
        p = v["params"][0]
        assert p["name"] == "arm_len_mm" and p["value"] == 20.5 and p["unit"] == "mm"
        assert v["optimization"]["params"]["arm_len_mm"] == {"low": 18.0, "high": 23.0}

    def test_save_params_roundtrip_and_validation(self, tmp_path):
        path = _recipe(tmp_path)
        r = recipe_save(path, {"params": {"arm_len_mm": 22.0}})
        assert r["ok"]
        v = recipe_view(path)
        assert v["params"][0]["value"] == 22.0

    def test_save_unknown_param_rejected(self, tmp_path):
        r = recipe_save(_recipe(tmp_path), {"params": {"bogus": 1.0}})
        assert not r["ok"]
        assert any("bogus" in e for e in r["errors"])

    def test_save_unknown_field_rejected(self, tmp_path):
        r = recipe_save(_recipe(tmp_path), {"model": "patch_antenna"})
        assert not r["ok"]


class TestRunDetail:
    def test_missing_run(self):
        assert not run_detail("no_such_run")["ok"]

    def test_detail_aggregates_artifacts(self, tmp_path):
        _make_run(tmp_path)
        d = run_detail("20260101_000000_test")
        assert d["ok"]
        assert d["metrics"]["s11_db"] == -15.2
        paths = [f["path"] for f in d["files"]]
        assert "results/metrics.json" in paths
        assert d["recipe_snapshot"]
        # 无 Touchstone 时回退 figs + 服务端 3D spec
        assert d["figs"] == ["runs/20260101_000000_test/results/figs/s11_curve.png"]
        spec = d["model3d"]
        assert spec and spec["ok"] and spec["template"] == "wilkinson"
        arm = next(b for b in spec["boxes"] if b["name"] == "arm_left")
        assert arm["stop_mm"][1] - arm["start_mm"][1] == 20.5  # 快照值 20.5，非默认


class TestModel3D:
    def test_spec_for_recipe(self, tmp_path):
        spec = model3d_for_recipe(_recipe(tmp_path))
        assert spec["ok"]
        assert spec["template"] == "wilkinson"
        names = {b["name"] for b in spec["boxes"]}
        assert {"substrate", "ground", "feed_in", "t_junction", "arm_left", "arm_right"} <= names
        # 端口标注在馈线端点、指向模型外侧（z=金属顶面，2026-09-04 新口径）
        h = spec["substrate"]["h_mm"]
        ports = {p["name"].split("（")[0]: p for p in spec["ports"]}
        assert ports["Port1"]["pos_mm"] == [0.0, -60.0, h]
        assert ports["Port1"]["dir"][1] < 0  # 输入端在 -y 外侧
        assert ports["Port2"]["pos_mm"][1] == 60.0
        assert ports["Port2"]["dir"][1] > 0

    def test_spec_param_change_moves_arm(self, tmp_path):
        path = _recipe(tmp_path)
        s1 = model3d_for_recipe(path)
        recipe_save(path, {"params": {"arm_len_mm": 23.0}})
        s2 = model3d_for_recipe(path)
        arm1 = next(b for b in s1["boxes"] if b["name"] == "arm_left")
        arm2 = next(b for b in s2["boxes"] if b["name"] == "arm_left")
        assert arm2["stop_mm"][1] - arm1["stop_mm"][1] == pytest.approx(2.5)

    def test_spec_size_consistent_with_template_script(self, tmp_path):
        """镜像约束：geometry_spec 与渲染脚本的关键尺寸一致。"""
        from rfauto.adapters.openems_templates import geometry_spec, render_script

        params = {"series_w_mm": 1.113, "shunt_w_mm": 0.604, "arm_len_mm": 20.5}
        spec = geometry_spec("wilkinson", params)
        script = render_script("wilkinson", params, (2.0, 3.0))
        arm = next(b for b in spec["boxes"] if b["name"] == "arm_left")
        assert f"{params['arm_len_mm']!r} * 1e-3" in script
        assert arm["stop_mm"][1] - arm["start_mm"][1] == params["arm_len_mm"]


def _make_trials(tmp_path: Path, run_id: str = "20260101_000000_test") -> Path:
    trials_dir = tmp_path / "runs" / run_id / "trials"
    trials_dir.mkdir(parents=True)
    for n, cost in enumerate([3.0, 2.5, 1.0]):
        (trials_dir / f"trial_{n}.json").write_text(json.dumps({
            "trial_number": n,
            "params": {"arm_len_mm": 20.0 + n},
            "metrics": {"s11_db_max_in_band": -10.0 - n},
            "cost": cost,
        }), encoding="utf-8")
    return trials_dir


class TestTuneTrials:
    def test_reads_trial_json_sorted(self, tmp_path):
        _make_trials(tmp_path)
        d = tune_trials("20260101_000000_test")
        assert d["ok"] and d["run_id"] == "20260101_000000_test"
        assert [t["trial_number"] for t in d["trials"]] == [0, 1, 2]
        assert d["trials"][2]["cost"] == 1.0

    def test_latest_run_fallback(self, tmp_path):
        _make_trials(tmp_path, "20260101_000000_aaa")
        _make_trials(tmp_path, "20260101_000000_bbb")
        d = tune_trials()  # 缺省取最近有 trials 的 run
        assert d["ok"] and d["run_id"] in ("20260101_000000_aaa", "20260101_000000_bbb")
        assert len(d["trials"]) == 3

    def test_empty_when_no_runs(self, tmp_path):
        d = tune_trials()
        assert d["ok"] and d["trials"] == []


class TestSandboxUi:
    def _stage_edited_draft(self, tmp_path):
        from rfauto.service.agent_sandbox import RecipeSandbox

        # 沙箱列表按 recipes/ 目录反查草稿来源，配方要落在该约定目录下
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir(exist_ok=True)
        recipe = {
            "model": "wilkinson_power_divider",
            "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
            "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
        }
        path = recipes_dir / "recipe.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        sandbox = RecipeSandbox()
        sandbox.apply_param_edits(path, {"arm_len_mm": 21.5})
        return path

    def test_drafts_lists_with_params_changed(self, tmp_path):
        self._stage_edited_draft(tmp_path)
        d = sandbox_drafts()
        assert d["ok"] and len(d["drafts"]) == 1
        item = d["drafts"][0]
        assert item["recipe"].replace("\\", "/").endswith("recipes/recipe.yaml")
        assert item["params_changed"]["arm_len_mm"] == {"old": 20.5, "new": 21.5}

    def test_drafts_empty_ok(self, tmp_path):
        assert sandbox_drafts() == {"ok": True, "drafts": []}

    def test_diff_returns_unified_and_params(self, tmp_path):
        path = self._stage_edited_draft(tmp_path)
        d = sandbox_diff(path)
        assert d["ok"] and "arm_len_mm" in d["params_changed"]
        assert "-    value: 20.5" in d["unified_diff"]

    def test_diff_without_draft_rejected(self, tmp_path):
        assert not sandbox_diff(_recipe(tmp_path))["ok"]

    def test_diff_rejects_escape(self, tmp_path):
        assert not sandbox_diff("../../etc/passwd.yaml")["ok"]

    def test_promote_creates_proposal(self, tmp_path):
        from rfauto.service.agent_safety import token_hash
        from rfauto.service.r3_services import list_pending_approvals

        path = self._stage_edited_draft(tmp_path)
        r = sandbox_promote(path)
        assert r["ok"], r
        assert r["sandbox_promote"] is True
        # 提案进收件箱（与人工提案同链）；审计只记 token 哈希
        pending = list_pending_approvals()["pending"]
        assert any(p["token_hash"] == token_hash(r["token"]) for p in pending)


class TestHttpEndpoints:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        monkeypatch.chdir(tmp_path)
        _recipe(tmp_path)
        _make_run(tmp_path)
        return TestClient(create_ui_app())

    def test_runs_endpoint(self, client):
        r = client.get("/api/runs").json()
        assert r["ok"]

    def test_runs_endpoint_carries_contract_check(self, client):
        """4.2 全量接线：服务点返回体带 best-effort 契约注记。"""
        r = client.get("/api/runs").json()
        cc = r["contract_check"]
        assert cc["contract"] == "list_runs"
        assert cc["ok"] is True, cc["errors"]
        assert cc["schema_version"] >= 2

    def test_run_detail_endpoint(self, client):
        r = client.get("/api/runs/20260101_000000_test").json()
        assert r["ok"] and r["metrics"]["s11_db"] == -15.2

    def test_recipe_get_save_post(self, client):
        v = client.get("/api/recipe", params={"path": "recipe.yaml"}).json()
        assert v["ok"] and v["params"][0]["value"] == 20.5
        r = client.post("/api/recipe", json={
            "path": "recipe.yaml", "updates": {"params": {"arm_len_mm": 19.0}},
        }).json()
        assert r["ok"]
        assert client.get("/api/recipe", params={"path": "recipe.yaml"}).json()[
            "params"][0]["value"] == 19.0

    def test_model3d_get_and_post(self, client):
        g = client.get("/api/model3d", params={"path": "recipe.yaml"}).json()
        assert g["ok"] and g["template"] == "wilkinson"
        p = client.post("/api/model3d", json={
            "template": "patch", "params": {"patch_len_mm": 41.0},
        }).json()
        assert p["ok"]
        assert any(b["name"] == "patch" for b in p["boxes"])

    def test_index_served(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "射频调优工作台" in r.text

    def test_tune_trials_endpoint(self, client):
        _make_trials(Path.cwd())
        r = client.get("/api/tune/trials").json()
        assert r["ok"] and len(r["trials"]) == 3
        assert r["trials"][0]["params"]["arm_len_mm"] == 20.0

    def test_sandbox_endpoints(self, client):
        from rfauto.service.agent_safety import token_hash

        recipes_dir = Path.cwd() / "recipes"
        recipes_dir.mkdir(exist_ok=True)
        path = recipes_dir / "recipe.yaml"
        path.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
            "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
        }), encoding="utf-8")
        from rfauto.service.agent_sandbox import RecipeSandbox

        RecipeSandbox().apply_param_edits(path, {"arm_len_mm": 22.0})
        drafts = client.get("/api/sandbox/drafts").json()
        assert drafts["ok"] and drafts["drafts"][0]["recipe"].endswith("recipe.yaml")
        diff = client.get("/api/sandbox/diff", params={"recipe": str(path)}).json()
        assert diff["ok"] and diff["params_changed"]["arm_len_mm"]["new"] == 22.0
        promo = client.post("/api/sandbox/promote", json={"recipe": str(path)}).json()
        assert promo["ok"], promo
        inbox = client.get("/api/inbox").json()
        assert any(p["token_hash"] == token_hash(promo["token"]) for p in inbox["pending"])


def _make_calibration_run(tmp_path: Path, run_id: str) -> Path:
    """造一份校准产物（gate/samples/report，3.2 工作台数据源）。"""
    run_dir = tmp_path / "runs" / run_id / "calibration"
    run_dir.mkdir(parents=True)
    (run_dir / "gate.json").write_text(json.dumps({
        "verdict": "PASS", "loocv": {"ok": True, "rho": 0.85, "n_folds": 9},
        "rho_threshold": 0.8, "validation_max_delta": 0.2,
        "n_samples": 9, "n_failures": 0, "mesh_resolution_mm": 0.45,
        "surrogate_kind": "poly_ridge",
    }), encoding="utf-8")
    (run_dir / "samples.json").write_text(json.dumps({
        "bounds": {"arm_len_mm": [18.0, 23.0]},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "samples": [{"params": {"arm_len_mm": 20.0},
                     "metrics": {"s11_db_max_in_band": -18.0}}],
        "validation": [],
        "mesh_resolution_mm": 0.45,
    }), encoding="utf-8")
    (run_dir / "report.md").write_text("# 校准报告\nPASS", encoding="utf-8")
    (tmp_path / "runs" / run_id / "meta.json").write_text(json.dumps({
        "model": "wilkinson_power_divider", "adapter": "calibration:openems",
    }), encoding="utf-8")
    return run_dir


class TestCalibrationEndpoints:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        monkeypatch.chdir(tmp_path)
        _make_calibration_run(tmp_path, "20260905_000000_cal000")
        return TestClient(create_ui_app())

    def test_calibration_list(self, client):
        r = client.get("/api/calibration").json()
        assert r["ok"] and len(r["runs"]) == 1
        entry = r["runs"][0]
        assert entry["verdict"] == "PASS"
        assert entry["rho"] == 0.85
        assert entry["mesh_resolution_mm"] == 0.45

    def test_calibration_detail(self, client):
        r = client.get("/api/calibration/20260905_000000_cal000").json()
        assert r["ok"]
        assert r["gate"]["verdict"] == "PASS"
        assert len(r["points"]) == 1
        assert r["points"][0]["cost"] == 0.0  # -18dB 优于 -15 → 无违约
        assert "校准报告" in r["report_md"]

    def test_calibration_detail_missing(self, client):
        r = client.get("/api/calibration/nope").json()
        assert not r["ok"]

    def test_cross_fidelity_view(self, client):
        r = client.get("/api/cross_fidelity").json()
        assert r["ok"]
        assert len(r["surrogate_evolution"]) == 1
        assert r["surrogate_evolution"][0]["rho"] == 0.85


class TestCalculatorEndpoints:
    """E4 微波工具箱 API（WP0.2）：清单自描述 + 执行。"""

    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs").mkdir()  # Mount("runs") 要求目录存在
        return TestClient(create_ui_app())

    def test_calculators_list(self, client):
        r = client.get("/api/calculators").json()
        assert r["ok"]
        assert len(r["calculators"]) >= 12
        by_name = {c["name"]: c for c in r["calculators"]}
        assert "microstrip_synthesis" in by_name
        assert any(p["required"] for p in by_name["microstrip_synthesis"]["params"])

    def test_calculators_run(self, client):
        r = client.post("/api/calculators/run", json={
            "name": "microstrip_synthesis",
            "params": {"z0_ohm": 50, "freq_ghz": 2.4,
                       "epsilon_r": 3.66, "h_mm": 0.508}}).json()
        assert r["ok"]
        assert abs(r["result"]["z0_actual_ohm"] - 50.0) < 0.5

    def test_calculators_run_unknown(self, client):
        r = client.post("/api/calculators/run",
                        json={"name": "nope", "params": {}}).json()
        assert not r["ok"] and "未注册" in r["error"]


# 示例 Touchstone（scripts/spike_b_ads/.../demo_BP.s2p）为二进制 .s2p，
# 不随 git 分发；缺文件时依赖它的用例 skip（合成输入的报错分支照常测）。
_DEMO_TOUCHSTONE = (Path(__file__).resolve().parents[2] / "scripts"
                    / "spike_b_ads" / "p3_d2_out" / "demo_BP.s2p")
_requires_demo_touchstone = pytest.mark.skipif(
    not _DEMO_TOUCHSTONE.exists(),
    reason="sample Touchstone fixture not distributed in this repo")


@_requires_demo_touchstone
class TestSparamsExternal:
    """Touchstone 导入对比：service + endpoint + PNG 渲染。"""

    DEMO = _DEMO_TOUCHSTONE

    def test_external_sparams_db_and_deg(self, tmp_path, monkeypatch):
        from rfauto.service.ui_service import external_sparams

        monkeypatch.chdir(tmp_path)
        r = external_sparams(str(self.DEMO), mode="db")
        assert r["ok"] and r["file"] == "demo_BP.s2p"
        assert r["curves"] and r["curves"][0]["name"] == "S11"
        assert r["n_points"] > 10
        r2 = external_sparams(str(self.DEMO), mode="deg")
        assert r2["ok"] and len(r2["curves"]) == len(r["curves"])

    def test_external_sparams_errors(self, tmp_path, monkeypatch):
        from rfauto.service.ui_service import external_sparams

        monkeypatch.chdir(tmp_path)
        assert not external_sparams("nope.s2p")["ok"]
        bad = tmp_path / "not_touchstone.txt"
        bad.write_text("hello", encoding="utf-8")
        r = external_sparams(str(bad))
        assert not r["ok"] and "非 Touchstone" in r["errors"][0]

    def test_compare_png_renders(self, tmp_path, monkeypatch):
        import shutil

        from rfauto.service.ui_service import sparams_compare_png

        monkeypatch.chdir(tmp_path)
        results = tmp_path / "runs" / "20260101_000000_test" / "results"
        results.mkdir(parents=True)
        shutil.copy(self.DEMO, results / "data.s2p")
        out = tmp_path / "cmp.png"
        r = sparams_compare_png("20260101_000000_test",
                                [str(self.DEMO)], out_path=str(out))
        assert r["ok"] and r["n_sources"] == 2 and r["n_curves"] >= 4
        assert out.is_file() and out.stat().st_size > 1000

    def test_compare_endpoint_route_order(self, tmp_path, monkeypatch):
        # 具体路由 /api/sparams/external 必须先于 /{run_id}，否则 POST 被
        # 参数路由部分匹配吃掉（405）
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs").mkdir()
        client = TestClient(create_ui_app())
        r = client.post("/api/sparams/external",
                        json={"path": str(self.DEMO), "mode": "db"}).json()
        assert r["ok"] and r["curves"]


class TestRunsMountGating:
    """开源默认安全：runs/ 静态挂载三态裁决。"""

    def test_default_app_keeps_runs_mount(self, tmp_path, monkeypatch):
        # 向后兼容钉：create_ui_app() 缺省（回环/测试路径）仍挂 /runs
        from rfauto.ui.server import create_ui_app

        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs").mkdir()
        app = create_ui_app()
        assert any(getattr(r, "path", None) == "/runs" for r in app.routes)

    def test_app_without_runs_mount(self):
        from rfauto.ui.server import create_ui_app

        app = create_ui_app(include_runs_mount=False)
        assert not any(getattr(r, "path", None) == "/runs" for r in app.routes)
        # 其余路由与 /static 不受影响
        assert any(getattr(r, "path", None) == "/static" for r in app.routes)
        assert any(getattr(r, "path", None) == "/api/runs" for r in app.routes)

    def test_resolve_three_state(self):
        from rfauto.ui.server import resolve_runs_mount

        # 缺省：回环开、非回环关
        assert resolve_runs_mount("127.0.0.1", None) is True
        assert resolve_runs_mount("localhost", None) is True
        assert resolve_runs_mount("::1", None) is True
        assert resolve_runs_mount("0.0.0.0", None) is False
        assert resolve_runs_mount("192.168.1.5", None) is False
        # 显式优先（#277 三态：显式 False 不得被"回环"覆盖）
        assert resolve_runs_mount("0.0.0.0", True) is True
        assert resolve_runs_mount("127.0.0.1", False) is False

    def test_cli_help_exposes_flag(self):
        # #305 族：新选项必须能过 --help（typer 注解/格式炸在构建期抓出）
        import pytest
        from typer.testing import CliRunner

        from rfauto.cli.main import app as cli_app

        runner = CliRunner()
        # 固定宽度：Linux CI 无 tty 时 rich 按 80 列换行会把选项名拆断
        result = runner.invoke(cli_app, ["ui", "--help"],
                               env={"COLUMNS": "200"})
        if result.exit_code != 0:
            pytest.fail(f"ui --help 失败: {result.output}")
        import re as _re
        plain = _re.sub(r"\[[0-9;]*m", "", result.output)
        flat = _re.sub(r"\s+", "", plain)
        assert "--expose-runs" in flat
        assert "--no-expose-runs" in flat
