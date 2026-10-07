"""UI 大块三页（datasets/anchors/uq）service 契约 + REST 薄端点 + 静态 smoke。

三页全部只读消费既有服务面（dataset_insights.list_datasets /
dataset_service.query_dataset / anchors_service.list_anchors+
anchors_stale_report / uq_service.surrogate_yield），本文件钉：

- 数据集页：datasets_overview 的清单 shape（含 models 模板族 best-effort
  提取三分支）+ dataset_preview 抽样契约（n_rows=抽样返回行数 #369）。
- 标定锚页：anchors_overview 合并 stale 报告（stale=None → UNKNOWN 如实
  透传）+ anchor_detail 透传；迷你注册表 fixture 零依赖真机。
- UQ 页：uq_samples_list 扫描判据（parsed/超上限如实不 mock）+
  uq_yield_run 透传确定性内核（σ 非数值显式拒绝，数值全部内核产出）。
- REST：新端点 JSON 契约 + index/pages.js 静态 smoke（三页导航/section
  存在，页面函数已注册）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPO_ROOT / "knowledge" / "anchors.yaml"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    (tmp_path / "runs").mkdir(exist_ok=True)
    yield


def _write_manifest(dataset_dir: Path, extra: dict | None = None,
                    *, name: str = "demo") -> None:
    manifest = {
        "schema_version": "2.0",
        "name": name,
        "format": "parquet",
        "created_at": "2026-09-27T00:00:00+00:00",
        "n_points": 6,
        "n_rows": 5,
        "n_dup": 1,
        "visibility": "private",
    }
    manifest.update(extra or {})
    dataset_dir.mkdir(parents=True, exist_ok=True)
    (dataset_dir / "dataset_manifest.yaml").write_text(
        yaml.safe_dump(manifest), encoding="utf-8")


class TestDatasetsOverview:
    """数据集页清单：models 模板族提取三分支（workdir/GT/旧 manifest）。"""

    def test_overview_shape_with_per_family_rows(self, tmp_path):
        from rfauto.service.ui_service import datasets_overview

        _write_manifest(tmp_path / "runs" / "datasets" / "ds_a",
                        {"per_family_rows": {"mline": 5, "wilkinson": 0}},
                        name="ds_a")
        r = datasets_overview()
        assert r["ok"] and r["n_datasets"] == 1
        item = r["datasets"][0]
        assert item["name"] == "ds_a"
        assert item["models"] == ["mline", "wilkinson"]  # 键集排序，零值也入
        assert item["n_rows"] == 5 and item["visibility"] == "private"
        assert {"dataset_dir", "created_at", "n_points"} <= set(item)

    def test_models_fallback_ground_truth_per_model(self, tmp_path):
        from rfauto.service.ui_service import datasets_overview

        _write_manifest(tmp_path / "runs" / "datasets" / "ds_b",
                        {"ground_truth": {"n_gt_rows": 3,
                                          "per_model": {"patch": 3}}},
                        name="ds_b")
        r = datasets_overview()
        assert r["ok"]
        assert r["datasets"][0]["models"] == ["patch"]

    def test_old_manifest_models_empty_honest(self, tmp_path):
        from rfauto.service.ui_service import datasets_overview

        _write_manifest(tmp_path / "runs" / "datasets" / "ds_old", name="ds_old")
        r = datasets_overview()
        assert r["ok"]
        assert r["datasets"][0]["models"] == []  # 旧 manifest 如实"未登记"

    def test_broken_manifest_listed_not_crash(self, tmp_path):
        from rfauto.service.ui_service import datasets_overview

        d = tmp_path / "runs" / "datasets" / "ds_bad"
        d.mkdir(parents=True)
        (d / "dataset_manifest.yaml").write_text("{ not: yaml:", encoding="utf-8")
        r = datasets_overview()
        assert r["ok"] and r["datasets"] == []


class TestDatasetsPreview:
    """行级预览：真实物化小数据集（duckdb/pyarrow，缺 extra 整类 skip）。"""

    @pytest.fixture()
    def materialized(self, tmp_path, monkeypatch):
        pytest.importorskip("duckdb", reason="需要 dataset extra（duckdb）")
        pytest.importorskip("pyarrow", reason="需要 dataset extra（pyarrow）")

        def _meta(run_id: str, model: str) -> dict:
            return {"run_id": run_id, "model": model, "adapter": "fake",
                    "algorithm": "tune", "study_name": "s1", "seed": 42,
                    "aedt_version": "fake", "ads_version": "",
                    "git_sha": "abc1234",
                    "timestamp": "2026-09-27T00:00:00+00:00",
                    "status": "done"}

        for i, model in enumerate(["mline", "mline"]):
            rid = f"run_{i}"
            base = tmp_path / "runs" / rid
            base.mkdir(parents=True)
            (base / "meta.json").write_text(
                json.dumps(_meta(rid, model)), encoding="utf-8")
            (base / "trials").mkdir()
            for n in range(2):
                (base / "trials" / f"trial_{n}.json").write_text(json.dumps({
                    "trial_number": n, "params": {"w_mm": 1.0 + n},
                    "metrics": {"s11_db_max_in_band": -10.0 - n},
                    "cost": 0.05 + n}), encoding="utf-8")
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(None, name="demo")
        assert r["ok"], r.get("errors")
        return r

    def test_preview_contract(self, materialized):
        from rfauto.service.ui_service import dataset_preview

        p = dataset_preview("demo", limit=10)
        assert p["ok"], p.get("errors")
        assert p["dataset"] == "demo"
        assert "model" in p["columns"]
        assert p["n_rows"] == len(p["rows"]) <= 10  # 抽样口径（#369）
        assert p["rows"][0]["model"] == "mline"

    def test_preview_model_filter(self, materialized):
        from rfauto.service.ui_service import dataset_preview

        p = dataset_preview("demo", limit=10, model="mline")
        assert p["ok"] and p["filters"]["model"] == "mline"
        assert all(row["model"] == "mline" for row in p["rows"])

    def test_preview_missing_dataset(self, materialized):
        from rfauto.service.ui_service import dataset_preview

        p = dataset_preview("nope")
        assert not p["ok"] and p["errors"]


def _mini_registry(tmp_path: Path, entries: list[dict]) -> str:
    path = tmp_path / "anchors_mini.yaml"
    path.write_text(yaml.safe_dump({
        "schema": "anchors/v1", "anchors": entries}), encoding="utf-8")
    return str(path)


class TestAnchorsPage:
    """标定锚页：清单合并 stale + 详情透传（迷你注册表，零真机）。"""

    def test_overview_real_registry_shape(self):
        from rfauto.service.ui_service import anchors_overview

        r = anchors_overview(path=str(_REGISTRY_PATH))
        assert r["ok"], r
        assert r["count"] == r["expected_count"] >= 6
        assert len(r["anchors"]) == r["count"]
        for a in r["anchors"]:
            assert {"anchor_id", "kind", "status", "template_family",
                    "stale_info"} <= set(a)
            si = a["stale_info"]
            assert si is not None and {"stale", "age_days"} <= set(si)
            assert si["stale"] in (True, False, None)  # None=UNKNOWN 如实

    def test_overview_merges_stale_none_as_unknown(self, tmp_path):
        from rfauto.service.ui_service import anchors_overview

        path = _mini_registry(tmp_path, [{
            "anchor_id": "test.demo.const-v1", "kind": "constant",
            "status": "active", "template_family": ["demo"], "value": 1.25,
        }])
        r = anchors_overview(path=path)
        assert r["ok"] and r["count"] == 1
        a = r["anchors"][0]
        assert a["stale_info"]["stale"] is None  # 无 last_verified → UNKNOWN
        assert a["stale_info"]["date_kind"] == "no_date"
        assert r["no_date_count"] == 1

    def test_detail_passthrough_and_unknown(self, tmp_path):
        from rfauto.service.ui_service import anchor_detail

        path = _mini_registry(tmp_path, [{
            "anchor_id": "test.demo.const-v1", "kind": "constant",
            "status": "active", "template_family": ["demo"], "value": 1.25,
        }])
        d = anchor_detail("test.demo.const-v1", path)
        assert d["ok"] and d["anchor"]["value"] == 1.25
        bad = anchor_detail("nope", path)
        assert not bad["ok"] and "未知锚" in bad["error"]


class TestUqSamplesList:
    """UQ 输入资产清单：判据 = 文件名含 samples + 顶层非空 samples 列表。"""

    def test_empty_runs(self):
        from rfauto.service.ui_service import uq_samples_list

        r = uq_samples_list()
        assert r["ok"] and r["items"] == [] and r["truncated"] is False

    def test_finds_parses_and_skips_honestly(self, tmp_path):
        from rfauto.service import ui_service

        good = tmp_path / "runs" / "r1" / "calibration" / "samples.json"
        good.parent.mkdir(parents=True)
        good.write_text(json.dumps({
            "bounds": {"w_mm": [0.5, 1.5], "a_mm": [1.0, 2.0]},
            "objectives": [{"metric": "s11_db"}],
            "samples": [{"params": {"w_mm": 1.0}, "metrics": {}}] * 2,
        }), encoding="utf-8")
        broken = tmp_path / "runs" / "r1" / "broken_samples.json"
        broken.write_text("{oops", encoding="utf-8")  # 损坏：入清单不解析
        ignored = tmp_path / "runs" / "r1" / "other.json"
        ignored.write_text(json.dumps({"samples": [1, 2]}), encoding="utf-8")
        empty = tmp_path / "runs" / "r1" / "empty_samples.json"
        empty.write_text(json.dumps({"samples": []}), encoding="utf-8")  # 空=非资产

        r = ui_service.uq_samples_list()
        assert r["ok"]
        by_name = {Path(it["path"]).name: it for it in r["items"]}
        assert set(by_name) == {"samples.json", "broken_samples.json"}
        g = by_name["samples.json"]
        assert g["parsed"] is True and g["n_samples"] == 2
        assert g["bounds_params"] == ["a_mm", "w_mm"]  # 排序确定性
        assert g["n_objectives"] == 1
        assert by_name["broken_samples.json"]["parsed"] is False
        assert by_name["broken_samples.json"]["n_samples"] is None

    def test_oversize_listed_unparsed(self, tmp_path, monkeypatch):
        from rfauto.service import ui_service

        monkeypatch.setattr(ui_service, "_UQ_SAMPLE_PARSE_CAP_BYTES", 10)
        p = tmp_path / "runs" / "r2" / "samples.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({
            "bounds": {}, "samples": [{"params": {}, "metrics": {}}]}),
            encoding="utf-8")
        r = ui_service.uq_samples_list()
        assert r["ok"] and r["n_items"] == 1
        it = r["items"][0]
        assert it["parsed"] is False and it["n_samples"] is None  # 超上限如实


class TestUqYieldRun:
    """UQ 运行面：透传 surrogate_yield（确定性内核），边界只做 σ 类型校验。"""

    @pytest.fixture()
    def samples_file(self, tmp_path):
        import numpy as np

        rng = np.random.default_rng(7)
        bounds = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}
        samples = []
        for _ in range(25):
            lv = float(rng.uniform(*bounds["arm_len_mm"]))
            wv = float(rng.uniform(*bounds["series_w_mm"]))
            samples.append({
                "params": {"arm_len_mm": lv, "series_w_mm": wv},
                "metrics": {"s11_db_max_in_band":
                            -20.0 + 5.0 * (lv - 20.0) ** 2
                            + 10.0 * (wv - 0.35) ** 2},
            })
        samples[0]["params"] = {"arm_len_mm": 20.0, "series_w_mm": 0.35}
        samples[0]["metrics"] = {"s11_db_max_in_band": -20.0}
        p = tmp_path / "runs" / "samples.json"
        p.write_text(json.dumps({
            "bounds": bounds,
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                            "op": "max_below", "value": -15}],
            "samples": samples}), encoding="utf-8")
        return str(p)

    def test_run_kernel_contract(self, samples_file):
        from rfauto.service.ui_service import uq_yield_run

        r = uq_yield_run(samples_file,
                         {"arm_len_mm": 0.1, "series_w_mm": 0.02},
                         n=500, seed=1)
        assert r["ok"], r.get("errors")
        assert 0.0 <= r["yield_rate"] <= 1.0
        assert set(r["sensitivity_violation_delta"]) == {
            "arm_len_mm", "series_w_mm"}
        assert r["sensitivity_ranking"] and r["metric_stats"]

    def test_non_numeric_sigma_rejected(self, samples_file):
        from rfauto.service.ui_service import uq_yield_run

        r = uq_yield_run(samples_file, {"arm_len_mm": "big"})
        assert not r["ok"] and "必须是数值" in r["errors"][0]

    def test_missing_samples_kernel_error_passthrough(self):
        from rfauto.service.ui_service import uq_yield_run

        r = uq_yield_run("runs/nope.json", {"x_mm": 0.1})
        assert not r["ok"] and "样本集不存在" in r["errors"][0]


class TestThreePagesHttpEndpoints:
    """REST 薄端点契约 + index/pages.js 静态 smoke。"""

    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        return TestClient(create_ui_app())

    def test_datasets_endpoints(self, client, tmp_path):
        _write_manifest(tmp_path / "runs" / "datasets" / "ds_http",
                        {"per_family_rows": {"mline": 5}}, name="ds_http")
        r = client.get("/api/datasets").json()
        assert r["ok"] and r["n_datasets"] == 1
        assert r["datasets"][0]["models"] == ["mline"]
        missing = client.get("/api/datasets/nope/preview").json()
        assert missing["ok"] is False

    def test_anchors_endpoints(self, client, tmp_path):
        path = _mini_registry(tmp_path, [{
            "anchor_id": "test.http.const-v1", "kind": "constant",
            "status": "active", "template_family": ["demo"], "value": 2.5,
        }])
        r = client.get("/api/anchors", params={"path": path}).json()
        assert r["ok"] and r["count"] == 1
        assert r["anchors"][0]["stale_info"]["stale"] is None
        d = client.get("/api/anchors/test.http.const-v1",
                       params={"path": path}).json()
        assert d["ok"] and d["anchor"]["value"] == 2.5

    def test_uq_endpoints(self, client, tmp_path):
        r = client.get("/api/uq/samples").json()
        assert r["ok"] and r["items"] == []
        p = client.post("/api/uq/yield",
                        json={"samples_path": "runs/nope.json",
                              "tolerances": {"x_mm": 0.1}}).json()
        assert p["ok"] is False and "样本集不存在" in p["errors"][0]

    def test_index_serves_three_pages(self, client):
        r = client.get("/")
        assert r.status_code == 200
        for needle in ('id="view-datasets"', 'id="view-anchors"',
                       'id="view-uq"', 'data-v="datasets"',
                       'data-v="anchors"', 'data-v="uq"',
                       "数据集", "标定锚", "UQ 不确定度"):
            assert needle in r.text, needle

    def test_pages_js_registers_three_pages(self):
        import rfauto.ui as ui_pkg

        src = (Path(ui_pkg.__file__).parent / "static" / "pages.js").read_text(
            encoding="utf-8")
        for needle in ("function pageDatasets", "function pageAnchors",
                       "function pageUq", "datasets: pageDatasets",
                       "anchors: pageAnchors", "uq: pageUq"):
            assert needle in src, needle
