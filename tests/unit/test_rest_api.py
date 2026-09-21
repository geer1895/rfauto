"""G1 REST API + Python SDK 测试（§10.7，确定性、无网络）。

覆盖：
- 路由响应契约（health / runs / calculators / datasets 信封与错误码）
- OpenAPI 3.0.3 spec 结构完整（info/paths/components）与自校验
- 路由表与 spec 单源同步
- SDK 端到端（进程内 ASGI + HTTP 传输打桩）
"""

from __future__ import annotations

import io
import json
import typing
import urllib.error
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from rfauto.service import rest_api, sdk

_REPO = Path(__file__).resolve().parents[2]
_RUN_ID = "20260101_000000_rest"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    (tmp_path / "runs").mkdir(exist_ok=True)
    yield


@pytest.fixture()
def client():
    return TestClient(rest_api.create_rest_app())


def _make_run(base: Path, run_id: str = _RUN_ID) -> Path:
    run_dir = base / "runs" / run_id
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    (run_dir / "results" / "metrics.json").write_text(
        json.dumps({"s11_db": -15.2, "params": {"arm_len_mm": 20.5}}),
        encoding="utf-8")
    return run_dir


def _make_dataset(base: Path, name: str = "demo") -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from rfauto.service.dataset_service import DATASET_SCHEMA

    type_map = {"string": pa.string(), "int64": pa.int64(), "float64": pa.float64()}
    schema = pa.schema([(c, type_map[t]) for c, t in DATASET_SCHEMA])
    rows = [{
        "run_id": "r1", "model": "mline", "adapter": "fake",
        "algorithm": "tune", "study_name": "s1", "seed": 1,
        "params_json": '{"w_mm": 1.0}', "metrics_json": '{"s11_db": -15.0}',
        "cost": 0.5, "point_index": 0, "source": "trials",
        "provenance_json": "{}",
    }]
    table = pa.Table.from_pylist(rows, schema=schema)
    dataset_dir = base / "runs" / "datasets" / name
    dataset_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, dataset_dir / "points.parquet")
    return dataset_dir


def _make_registered_dataset(base: Path, name: str = "demo",
                             visibility: str = "private") -> Path:
    """裸 Parquet + 最小 manifest（dataset_insights 八接口需要 manifest）。"""
    import yaml

    from rfauto.service.dataset_service import DATASET_SCHEMA

    dataset_dir = _make_dataset(base, name)
    manifest = {
        "schema_version": "2.0", "name": name,
        "created_at": "2026-09-15T00:00:00+00:00",
        "n_points": 1, "n_rows": 1, "n_dup": 0,
        "columns": [c for c, _t in DATASET_SCHEMA],
        "visibility": visibility,
    }
    (dataset_dir / "dataset_manifest.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return dataset_dir


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_envelope(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["status"] == "ok"
        assert data["version"]
        assert data["n_models"] >= 1
        assert "wilkinson_power_divider" in data["models"]

    def test_health_is_deterministic(self, client):
        first = client.get("/api/v1/health").json()
        second = client.get("/api/v1/health").json()
        assert first == second


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------

class TestOpenApi:
    def test_openapi_endpoint_structure(self, client):
        response = client.get("/api/v1/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        assert spec["openapi"].startswith("3.")
        assert spec["info"]["title"] and spec["info"]["version"]
        assert spec["paths"]
        assert spec["components"]["schemas"]

    def test_openapi_self_validation_passes(self):
        result = rest_api.validate_openapi_spec(rest_api.openapi_spec())
        assert result["ok"] is True, result["errors"]

    def test_openapi_validation_detects_missing_info(self):
        spec = rest_api.openapi_spec()
        del spec["info"]
        result = rest_api.validate_openapi_spec(spec)
        assert result["ok"] is False
        assert any("info" in error for error in result["errors"])

    def test_openapi_validation_detects_dangling_ref(self):
        spec = rest_api.openapi_spec()
        spec["components"]["schemas"]["Broken"] = {
            "$ref": "#/components/schemas/DoesNotExist"}
        result = rest_api.validate_openapi_spec(spec)
        assert result["ok"] is False
        assert any("$ref" in error for error in result["errors"])

    def test_openapi_validation_detects_duplicate_operation_id(self):
        spec = rest_api.openapi_spec()
        spec["paths"]["/api/v1/runs"]["get"]["operationId"] = "getHealth"
        result = rest_api.validate_openapi_spec(spec)
        assert result["ok"] is False
        assert any("operationId" in error for error in result["errors"])

    def test_route_table_and_spec_stay_in_sync(self):
        app = rest_api.create_rest_app()
        route_paths = {
            route.path for route in app.routes if hasattr(route, "path")}
        spec_paths = set(rest_api.openapi_spec()["paths"])
        assert route_paths == spec_paths

    def test_expected_operations_present(self):
        spec = rest_api.openapi_spec()
        operation_ids = {
            operation["operationId"]
            for item in spec["paths"].values()
            for method, operation in item.items()
            if method in rest_api._HTTP_METHODS
        }
        assert operation_ids == {
            "getHealth", "getOpenApi", "listRuns", "getRun",
            "listCalculators", "runCalculator", "queryDataset",
            # E1 收口：dataset_insights 八接口薄壳
            "listDatasets", "datasetCoverage", "annotateGroundTruth",
            "neuralOperatorReadiness", "setDatasetVisibility",
            "exportHfDataset", "registerPublicDataset", "loadDatasetSets",
            # F-R2-3：db/rag/工作目录发现/slotline·transitions 只读透传
            "dbStatus", "dbQuery", "ragQuery", "ragExplain", "discoverWorkdir",
            "slotlineAnalysis", "slotlineSynthesis", "mslSlotTransitionDesign",
            "marchandBalunDesign", "marchandTwoSectionSynthesis",
        }

    def test_every_operation_has_responses_and_ids(self):
        spec = rest_api.openapi_spec()
        for _path, item in spec["paths"].items():
            for method, operation in item.items():
                if method not in rest_api._HTTP_METHODS:
                    continue
                assert operation["operationId"]
                assert operation["responses"]
                for response in operation["responses"].values():
                    assert response["description"]

    def test_request_body_declared_for_post(self):
        spec = rest_api.openapi_spec()
        schema_name = spec["paths"]["/api/v1/calculators/{name}/run"]["post"][
            "requestBody"]["content"]["application/json"]["schema"]["$ref"]
        assert schema_name.endswith("/CalculatorRunRequest")
        dataset_ref = spec["paths"]["/api/v1/datasets/query"]["post"][
            "requestBody"]["content"]["application/json"]["schema"]["$ref"]
        assert dataset_ref.endswith("/DatasetQueryRequest")


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------

class TestRuns:
    def test_list_runs_empty(self, client):
        body = client.get("/api/v1/runs").json()
        assert body["ok"] is True
        assert body["data"]["ok"] is True
        assert body["data"]["runs"] == []

    def test_list_runs_rejects_non_integer_limit(self, client):
        response = client.get("/api/v1/runs", params={"limit": "abc"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"

    def test_list_runs_rejects_out_of_range_limit(self, client):
        response = client.get("/api/v1/runs", params={"limit": 0})
        assert response.status_code == 400

    def test_run_detail_ok(self, client, tmp_path):
        _make_run(tmp_path)
        body = client.get(f"/api/v1/runs/{_RUN_ID}").json()
        assert body["ok"] is True
        assert body["data"]["run_id"] == _RUN_ID

    def test_run_detail_unknown_is_404(self, client):
        response = client.get("/api/v1/runs/no_such_run")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# calculators
# ---------------------------------------------------------------------------

class TestCalculators:
    def test_list_calculators(self, client):
        body = client.get("/api/v1/calculators").json()
        assert body["ok"] is True
        names = [c["name"] for c in body["data"]["calculators"]]
        assert "attenuator_pi" in names

    def test_run_calculator_deterministic(self, client):
        payload = {"params": {"attenuation_db": 3.0, "z0_ohm": 50.0}}
        first = client.post(
            "/api/v1/calculators/attenuator_pi/run", json=payload).json()
        second = client.post(
            "/api/v1/calculators/attenuator_pi/run", json=payload).json()
        assert first == second
        assert first["ok"] is True
        result = first["data"]["result"]
        assert result["r_series_mid_ohm"] == 17.615
        assert result["r_shunt_end_ohm"] == 292.402

    def test_run_calculator_missing_param_is_400(self, client):
        response = client.post(
            "/api/v1/calculators/attenuator_pi/run",
            json={"params": {"attenuation_db": 3.0}})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"

    def test_run_calculator_unknown_is_404(self, client):
        response = client.post(
            "/api/v1/calculators/nope/run", json={"params": {}})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_run_calculator_bad_json_is_400(self, client):
        response = client.post(
            "/api/v1/calculators/attenuator_pi/run",
            content=b"not json", headers={"content-type": "application/json"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "bad_json"

    def test_run_calculator_params_not_object_is_400(self, client):
        response = client.post(
            "/api/v1/calculators/attenuator_pi/run",
            json={"params": [1, 2, 3]})
        assert response.status_code == 400


_EXPERIMENTAL_KEY = "patch_f0_symbolic_e13"
_EXP_PARAMS = {"l_mm": 40.0, "w_mm": 50.0}


class TestCalculatorsExperimentalPassthrough:
    """REST 壳层 experimental 标签 + allow_experimental 三态透传。"""

    @pytest.fixture(autouse=True)
    def _no_env_switch(self, monkeypatch):
        monkeypatch.delenv("RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL", raising=False)

    def test_list_default_labels_experimental(self, client):
        data = client.get("/api/v1/calculators").json()["data"]
        by_name = {c["name"]: c for c in data["calculators"]}
        assert by_name[_EXPERIMENTAL_KEY]["experimental"] is True
        assert data["experimental"] == [_EXPERIMENTAL_KEY]
        assert data["n_experimental"] == 1

    def test_list_include_experimental_false_query(self, client):
        data = client.get(
            "/api/v1/calculators", params={"include_experimental": "false"}).json()["data"]
        assert data["include_experimental"] is False
        assert _EXPERIMENTAL_KEY not in [c["name"] for c in data["calculators"]]
        assert data["experimental"] == [_EXPERIMENTAL_KEY]  # 名单仍如实报告

    def test_run_experimental_default_is_400_not_404(self, client):
        response = client.post(
            f"/api/v1/calculators/{_EXPERIMENTAL_KEY}/run", json={"params": _EXP_PARAMS})
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "invalid_request"
        assert "allow_experimental" in body["error"]["message"]

    def test_run_experimental_allow_true(self, client):
        response = client.post(
            f"/api/v1/calculators/{_EXPERIMENTAL_KEY}/run",
            json={"params": _EXP_PARAMS, "allow_experimental": True})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["experimental"] is True
        assert data["result"]["f0_ghz"] == pytest.approx(1.918754, abs=2e-6)

    def test_run_explicit_false_beats_env(self, client, monkeypatch):
        monkeypatch.setenv("RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL", "1")
        response = client.post(
            f"/api/v1/calculators/{_EXPERIMENTAL_KEY}/run",
            json={"params": _EXP_PARAMS, "allow_experimental": False})
        assert response.status_code == 400

    def test_run_env_switch_passes_when_body_field_absent(self, client, monkeypatch):
        """缺省（body 缺 allow_experimental 字段）读 env：env=1 放行——壳层
        不得把缺省当显式 False（#277 三态）。"""
        monkeypatch.setenv("RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL", "1")
        response = client.post(
            f"/api/v1/calculators/{_EXPERIMENTAL_KEY}/run",
            json={"params": _EXP_PARAMS})
        assert response.status_code == 200
        assert response.json()["data"]["experimental"] is True

    def test_allow_experimental_non_bool_is_400(self, client):
        response = client.post(
            f"/api/v1/calculators/{_EXPERIMENTAL_KEY}/run",
            json={"params": _EXP_PARAMS, "allow_experimental": "yes"})
        assert response.status_code == 400
        assert "allow_experimental" in response.json()["error"]["message"]

    def test_openapi_declares_switches(self):
        spec = rest_api.openapi_spec()
        run_schema = spec["components"]["schemas"]["CalculatorRunRequest"]
        assert run_schema["properties"]["allow_experimental"]["type"] == "boolean"
        list_params = spec["paths"]["/api/v1/calculators"]["get"]["parameters"]
        assert [p["name"] for p in list_params] == ["include_experimental"]
        assert rest_api.validate_openapi_spec(spec)["ok"] is True

    def test_sdk_passthrough(self):
        client = sdk.RfautoClient()
        names = [c["name"] for c in
                 client.list_calculators(include_experimental=False)["calculators"]]
        assert _EXPERIMENTAL_KEY not in names
        with pytest.raises(sdk.RfautoApiError) as excinfo:
            client.calculate(_EXPERIMENTAL_KEY, _EXP_PARAMS)
        assert excinfo.value.status_code == 400
        data = client.calculate(_EXPERIMENTAL_KEY, _EXP_PARAMS, allow_experimental=True)
        assert data["experimental"] is True
        assert data["result"]["f0_ghz"] == pytest.approx(1.918754, abs=2e-6)


# ---------------------------------------------------------------------------
# datasets
# ---------------------------------------------------------------------------

class TestDatasets:
    def test_query_dataset_ok(self, client, tmp_path):
        _make_dataset(tmp_path)
        body = client.post("/api/v1/datasets/query", json={"name": "demo"}).json()
        assert body["ok"] is True
        assert body["data"]["n_rows"] == 1
        assert body["data"]["rows"][0]["model"] == "mline"

    def test_query_dataset_unknown_is_404(self, client):
        response = client.post(
            "/api/v1/datasets/query", json={"name": "nope"})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_query_dataset_bad_name_is_400(self, client):
        response = client.post(
            "/api/v1/datasets/query", json={"name": "bad name"})
        assert response.status_code == 400

    def test_query_dataset_bad_where_is_400(self, client, tmp_path):
        _make_dataset(tmp_path)
        response = client.post(
            "/api/v1/datasets/query",
            json={"name": "demo", "where": "cost < 1; drop table x"})
        assert response.status_code == 400

    def test_query_dataset_missing_name_is_400(self, client):
        response = client.post("/api/v1/datasets/query", json={})
        assert response.status_code == 400

    def test_query_dataset_injection_converged_message(self, client, tmp_path):
        """注入 payload（FROM-first 变体）→ 400，错误文案统一收敛：
        不回传 payload 原文、不透传引擎原始消息（防存在性 oracle）。"""
        _make_dataset(tmp_path)
        response = client.post(
            "/api/v1/datasets/query",
            json={"name": "demo",
                  "where": "1=1) AND EXISTS (FROM glob('../../runs**'))"})
        assert response.status_code == 400
        body = response.json()
        assert body["ok"] is False
        message = body["error"]["message"]
        assert "被拒绝" in message
        # 不回传 payload 原文（glob/runs 等片段不得出现在回执中）
        assert "glob" not in message and "runs" not in message
        assert "EXISTS" not in message


class TestDatasetInsightsEndpoints:
    """E1 收口：dataset_insights 八接口薄壳（参数校验/状态码映射；语义在
    service 层，此处只验信封与错误码）。"""

    def test_list_datasets_ok_and_filter(self, client, tmp_path):
        _make_registered_dataset(tmp_path, "demo", visibility="private")
        body = client.get("/api/v1/datasets").json()
        assert body["ok"] is True
        assert body["data"]["n_datasets"] == 1
        item = body["data"]["datasets"][0]
        assert item["name"] == "demo" and item["visibility"] == "private"
        assert item["format"] == "parquet"  # 无 format 键的旧 manifest 回退
        filtered = client.get("/api/v1/datasets?visibility=public").json()
        assert filtered["data"]["n_datasets"] == 0

    def test_list_datasets_bad_visibility_is_400(self, client):
        response = client.get("/api/v1/datasets?visibility=secret")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"

    def test_coverage_ok_unknown_404_bad_bins_400(self, client, tmp_path):
        _make_registered_dataset(tmp_path)
        ok = client.post("/api/v1/datasets/coverage",
                         json={"name": "demo", "bins": 4}).json()
        assert ok["ok"] is True
        assert ok["data"]["bins"] == 4 and "w_mm" in ok["data"]["per_key"]
        assert client.post("/api/v1/datasets/coverage",
                           json={"name": "nope"}).status_code == 404
        bad = client.post("/api/v1/datasets/coverage",
                          json={"name": "demo", "bins": "four"})
        assert bad.status_code == 400
        assert client.post("/api/v1/datasets/coverage",
                           json={"name": "demo", "bins": True}).status_code == 400

    def test_ground_truth_annotate_and_readiness(self, client, tmp_path):
        _make_registered_dataset(tmp_path)
        ann = client.post("/api/v1/datasets/ground-truth/annotate",
                          json={"name": "demo", "threshold": 1}).json()
        assert ann["ok"] is True
        # 唯一行 adapter=fake → 不是 GT，门槛 1 也不解锁
        assert ann["data"]["n_gt_rows"] == 0 and ann["data"]["unlocked"] is False
        ready = client.post("/api/v1/datasets/neural-operator-readiness",
                            json={"name": "demo"}).json()
        assert ready["ok"] is True and ready["data"]["threshold"] == 100
        assert client.post("/api/v1/datasets/neural-operator-readiness",
                           json={"name": "demo", "threshold": 0}).status_code == 400
        assert client.post("/api/v1/datasets/ground-truth/annotate",
                           json={}).status_code == 400

    def test_visibility_and_export_hf_guard(self, client, tmp_path):
        _make_registered_dataset(tmp_path)
        # private 默认拒绝公开导出 → 400
        refused = client.post("/api/v1/datasets/export-hf", json={"name": "demo"})
        assert refused.status_code == 400
        bad_vis = client.post("/api/v1/datasets/visibility",
                              json={"name": "demo", "visibility": "secret"})
        assert bad_vis.status_code == 400
        flip = client.post("/api/v1/datasets/visibility",
                           json={"name": "demo", "visibility": "public"}).json()
        assert flip["ok"] is True and flip["data"]["visibility"] == "public"
        exported = client.post("/api/v1/datasets/export-hf",
                               json={"name": "demo", "license": "cc-by-4.0"}).json()
        assert exported["ok"] is True
        assert Path(exported["data"]["card"]).exists()
        assert Path(exported["data"]["parquet"]).exists()
        # allow_private 非 bool → 400（不做 "yes" 强转）
        assert client.post("/api/v1/datasets/export-hf",
                           json={"name": "demo", "allow_private": "yes"}
                           ).status_code == 400
        assert client.post("/api/v1/datasets/visibility",
                           json={"name": "ghost", "visibility": "public"}
                           ).status_code == 404

    def test_public_register_guard_and_sets_conflict(self, client, tmp_path):
        """公开集注册路径 + 双集防污染：私有 id 默认拒绝（400）；promote 转
        公开后注册成功；手改注册表制造交集 → sets 端点 409 conflict。"""
        import yaml

        _make_registered_dataset(tmp_path, "demo", visibility="private")
        refused = client.post("/api/v1/datasets/public/register",
                              json={"name": "demo"})
        assert refused.status_code == 400
        assert "双集污染防护" in refused.json()["error"]["message"]
        assert client.post("/api/v1/datasets/public/register",
                           json={"name": "demo", "promote": "yes"}
                           ).status_code == 400
        clean = client.get("/api/v1/datasets/sets").json()
        assert clean["ok"] is True
        assert clean["data"]["public"]["status"] == "not_configured"
        assert clean["data"]["private"]["ids"] == ["demo"]

        promoted = client.post("/api/v1/datasets/public/register",
                               json={"name": "demo", "promote": True,
                                     "source": "unit-test"}).json()
        assert promoted["ok"] is True
        assert promoted["data"]["promoted"] is True
        assert promoted["data"]["overlap_ids"] == []
        sets = client.get("/api/v1/datasets/sets").json()
        assert sets["data"]["public"]["ids"] == ["demo"]
        assert sets["data"]["private"]["ids"] == []

        # 手改注册表：把一个新私有数据集 id 塞进公开集 → 交集非空 → 409
        _make_registered_dataset(tmp_path, "secret_campaign", visibility="private")
        reg_path = tmp_path / "runs" / "datasets" / "public_set.yaml"
        payload = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
        payload["entries"].append({"name": "secret_campaign"})
        reg_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
        conflict = client.get("/api/v1/datasets/sets")
        assert conflict.status_code == 409
        err = conflict.json()["error"]
        assert err["code"] == "conflict" and "secret_campaign" in err["message"]

    def test_sets_invalid_registry_is_400(self, client, tmp_path):
        reg_dir = tmp_path / "runs" / "datasets"
        reg_dir.mkdir(parents=True, exist_ok=True)
        (reg_dir / "public_set.yaml").write_text(
            "entries: [not-an-object]\n", encoding="utf-8")
        response = client.get("/api/v1/datasets/sets")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"


# ---------------------------------------------------------------------------
# db / rag / 工作目录发现 / slotline·transitions（F-R2-3 只读透传）
# ---------------------------------------------------------------------------

def _make_registry(tmp_path: Path, name: str = "reg.sqlite") -> Path:
    from rfauto.service.db_service import db_init

    db_path = tmp_path / name
    db_init(db_path)
    return db_path


class TestDbEndpoints:
    """F-R2-3：db 只读透传（db_status / db_query_safe 薄壳）。

    全部显式 db_path（不读默认路径/env），确定性不依赖环境变量。
    """

    def test_db_status_missing_file_ok(self, client, tmp_path):
        body = client.get("/api/v1/db/status", params={
            "db_path": str(tmp_path / "nope.sqlite")}).json()
        assert body["ok"] is True
        assert body["data"]["exists"] is False
        assert body["data"]["schema_version"] == 0
        assert "runs" in body["data"]["tables"]

    def test_db_status_after_init(self, client, tmp_path):
        db_path = _make_registry(tmp_path)
        body = client.get(
            "/api/v1/db/status", params={"db_path": str(db_path)}).json()
        assert body["ok"] is True
        assert body["data"]["exists"] is True
        assert body["data"]["schema_version"] >= 1
        assert body["data"]["tables"]["runs"] == 0

    def test_db_query_select_ok(self, client, tmp_path):
        db_path = _make_registry(tmp_path)
        body = client.post("/api/v1/db/query", json={
            "sql": "SELECT COUNT(*) AS n FROM runs",
            "db_path": str(db_path),
        }).json()
        assert body["ok"] is True
        assert body["data"]["columns"] == ["n"]
        assert body["data"]["rows"] == [[0]]

    def test_db_query_placeholder_binding(self, client, tmp_path):
        db_path = _make_registry(tmp_path)
        body = client.post("/api/v1/db/query", json={
            "sql": "SELECT run_id FROM runs WHERE adapter = ?",
            "params": ["hfss"], "db_path": str(db_path),
        }).json()
        assert body["ok"] is True
        assert body["data"]["rows"] == []

    def test_db_query_rejects_non_select_is_400(self, client, tmp_path):
        db_path = _make_registry(tmp_path)
        response = client.post("/api/v1/db/query", json={
            "sql": "DELETE FROM runs", "db_path": str(db_path)})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"

    def test_db_query_missing_sql_is_400(self, client):
        assert client.post("/api/v1/db/query", json={}).status_code == 400

    def test_db_query_params_not_list_is_400(self, client, tmp_path):
        db_path = _make_registry(tmp_path)
        response = client.post("/api/v1/db/query", json={
            "sql": "SELECT 1", "params": "hfss", "db_path": str(db_path)})
        assert response.status_code == 400


_DOCS_TEXT = "# 槽线\n\n槽线 slotline 是准平面传输线，特性阻抗由槽宽决定。\n"


class TestRagEndpoints:
    """F-R2-3：rag 只读透传（query_corpus / explain_corpus 薄壳）。"""

    @pytest.fixture()
    def docs(self, tmp_path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "note.md").write_text(_DOCS_TEXT, encoding="utf-8")
        return docs_dir

    def test_rag_query_ok(self, client, docs):
        body = client.post("/api/v1/rag/query", json={
            "text": "槽线特性阻抗", "docs_dir": str(docs), "runs_dir": None,
        }).json()
        assert body["ok"] is True
        assert body["data"]["n_hits"] >= 1
        hit = body["data"]["hits"][0]
        assert hit["citation"]["path"]
        assert hit["snippet"]

    def test_rag_explain_has_score_breakdown(self, client, docs):
        body = client.post("/api/v1/rag/explain", json={
            "text": "slotline", "docs_dir": str(docs), "runs_dir": None,
        }).json()
        assert body["ok"] is True
        assert body["data"]["hits"][0]["score_breakdown"]

    def test_rag_query_both_sources_skipped_ok(self, client):
        """docs_dir/runs_dir 显式 null → 空索引 ok=True 零命中（确定性）。"""
        body = client.post("/api/v1/rag/query", json={
            "text": "任意词条", "docs_dir": None, "runs_dir": None}).json()
        assert body["ok"] is True
        assert body["data"]["n_hits"] == 0

    def test_rag_query_missing_text_is_400(self, client):
        assert client.post("/api/v1/rag/query", json={}).status_code == 400

    def test_rag_query_bad_top_k_is_400(self, client, docs):
        response = client.post("/api/v1/rag/query", json={
            "text": "槽线", "top_k": 0, "docs_dir": str(docs),
            "runs_dir": None})
        assert response.status_code == 400

    def test_rag_query_negative_runs_limit_is_400(self, client):
        response = client.post("/api/v1/rag/query", json={
            "text": "槽线", "docs_dir": None, "runs_dir": None,
            "runs_limit": -1})
        assert response.status_code == 400

    def test_rag_query_missing_docs_dir_is_404(self, client, tmp_path):
        response = client.post("/api/v1/rag/query", json={
            "text": "槽线", "docs_dir": str(tmp_path / "no_such_docs"),
            "runs_dir": None})
        assert response.status_code == 404


class TestDiscoverWorkdirEndpoint:
    """F-R2-3：工作目录形态发现（discover_workdir_candidates 只读薄壳）。"""

    def test_discover_empty_runs_ok(self, client):
        body = client.get("/api/v1/datasets/discover-workdir").json()
        assert body["ok"] is True
        assert body["data"]["n_candidates"] == 0
        assert "slotline" in body["data"]["families"]

    def test_discover_models_filter_ok(self, client):
        body = client.get("/api/v1/datasets/discover-workdir",
                          params={"models": "slotline,mline"}).json()
        assert body["ok"] is True
        assert body["data"]["families"] == ["slotline", "hairpin", "marchand",
                                            "mline", "helix"]

    def test_discover_unknown_family_is_400(self, client):
        response = client.get("/api/v1/datasets/discover-workdir",
                              params={"models": "nope"})
        assert response.status_code == 400

    def test_discover_missing_runs_root_is_404(self, client):
        response = client.get("/api/v1/datasets/discover-workdir",
                              params={"runs_root": "no_such_runs"})
        assert response.status_code == 404


class TestSlotlineTransitionsEndpoints:
    """F-R2-3：slotline/transitions 五入口只读计算薄壳（数值只出确定性内核；
    越有效域 ok=False → 400，不外推）。"""

    _MSL: typing.ClassVar[dict[str, float]] = {
        "f0_ghz": 2.5, "h_mm": 1.524, "er": 3.66, "w_slot_mm": 1.0}

    def test_slotline_analyze_ok(self, client):
        body = client.post("/api/v1/slotline/analyze", json={
            "w_mm": 1.0, "h_mm": 1.524, "epsilon_r": 3.66, "freq_ghz": 2.5,
        }).json()
        assert body["ok"] is True
        assert body["data"]["result"]["z0_ohm"] > 0

    def test_slotline_analyze_missing_param_is_400(self, client):
        response = client.post("/api/v1/slotline/analyze",
                               json={"w_mm": 1.0, "h_mm": 1.524})
        assert response.status_code == 400

    def test_slotline_analyze_out_of_domain_is_400(self, client):
        response = client.post("/api/v1/slotline/analyze", json={
            "w_mm": 1.0, "h_mm": 1.524, "epsilon_r": 30.0, "freq_ghz": 2.5})
        assert response.status_code == 400

    def test_slotline_analyze_non_numeric_is_400(self, client):
        response = client.post("/api/v1/slotline/analyze", json={
            "w_mm": "wide", "h_mm": 1.524, "epsilon_r": 3.66, "freq_ghz": 2.5})
        assert response.status_code == 400

    def test_slotline_synth_ok(self, client):
        body = client.post("/api/v1/slotline/synth", json={
            "z0_ohm": 110.0, "h_mm": 1.524, "epsilon_r": 3.66,
            "freq_ghz": 2.5,
        }).json()
        assert body["ok"] is True
        assert body["data"]["result"]["w_mm"] > 0

    def test_msl_slot_transition_ok(self, client):
        body = client.post(
            "/api/v1/transitions/msl-slot", json=self._MSL).json()
        assert body["ok"] is True
        assert body["data"]["design"]["l_stub_mm"] > 0
        assert body["data"]["gates"]

    def test_msl_slot_transition_optional_tan_d(self, client):
        body = client.post("/api/v1/transitions/msl-slot",
                           json={**self._MSL, "tan_d": 0.002}).json()
        assert body["ok"] is True

    def test_marchand_balun_ok(self, client):
        body = client.post("/api/v1/transitions/marchand-balun",
                           json=self._MSL).json()
        assert body["ok"] is True
        assert body["data"]["design"]["d_center_mm"] > 0

    def test_marchand_two_section_default_ok(self, client):
        body = client.post(
            "/api/v1/transitions/marchand-two-section", json={}).json()
        assert body["ok"] is True
        assert body["data"]["design"]["realizable"] is True
        assert body["data"]["gates"]

    def test_marchand_two_section_bad_band_is_400(self, client):
        response = client.post("/api/v1/transitions/marchand-two-section",
                               json={"band_ghz": [2.5]})
        assert response.status_code == 400


class TestSdkReadOnlyPassthrough:
    """F-R2-3：SDK 只读透传方法（db/rag/discover/slotline/transitions）。"""

    def test_sdk_db_end_to_end(self, tmp_path):
        db_path = _make_registry(tmp_path)
        client = sdk.RfautoClient()
        status = client.db_status(db_path=str(db_path))
        assert status["exists"] is True
        assert "runs" in status["tables"]
        data = client.db_query("SELECT run_id FROM runs WHERE adapter = ?",
                               ["hfss"], db_path=str(db_path))
        assert data["row_count"] == 0
        with pytest.raises(sdk.RfautoApiError) as excinfo:
            client.db_query("DROP TABLE runs")
        assert excinfo.value.status_code == 400

    def test_sdk_rag_end_to_end(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "note.md").write_text(
            "# 巴伦\n\nMarchand 巴伦是宽带平衡-不平衡变换器。\n",
            encoding="utf-8")
        client = sdk.RfautoClient()
        data = client.rag_query("巴伦", docs_dir=str(docs), runs_dir=None)
        assert data["n_hits"] >= 1
        explained = client.rag_explain("巴伦", docs_dir=str(docs),
                                       runs_dir=None)
        assert explained["hits"][0]["score_breakdown"]

    def test_sdk_rag_null_sources_skip(self):
        data = sdk.RfautoClient().rag_query(
            "任意词条", docs_dir=None, runs_dir=None)
        assert data["ok"] is True and data["n_hits"] == 0

    def test_sdk_discover_workdir(self):
        client = sdk.RfautoClient()
        assert client.discover_workdir()["n_candidates"] == 0
        filtered = client.discover_workdir(models=["slotline"])
        assert "slotline" in filtered["families"]

    def test_sdk_slotline_transitions_end_to_end(self):
        client = sdk.RfautoClient()
        ana = client.slotline_analyze(1.0, 1.524, 3.66, 2.5)
        assert ana["result"]["z0_ohm"] > 0
        syn = client.slotline_synth(110.0, 1.524, 3.66, 2.5)
        assert syn["result"]["w_mm"] > 0
        msl = client.msl_slot_transition(2.5, 1.524, 3.66, 1.0)
        assert msl["design"]["l_stub_mm"] > 0
        balun = client.marchand_balun(2.5, 1.524, 3.66, 1.0, tan_d=0.002)
        assert balun["design"]["d_center_mm"] > 0
        two = client.marchand_two_section()
        assert two["design"]["realizable"] is True




class TestRouting:
    def test_unknown_route_is_404(self, client):
        assert client.get("/api/v1/nope").status_code == 404

    def test_wrong_method_is_405(self, client):
        assert client.get("/api/v1/datasets/query").status_code == 405


# ---------------------------------------------------------------------------
# SDK
# ---------------------------------------------------------------------------

class TestSdk:
    def test_sdk_health_end_to_end(self):
        data = sdk.RfautoClient().health()
        assert data["status"] == "ok"

    def test_sdk_openapi_end_to_end(self):
        spec = sdk.RfautoClient().openapi()
        assert spec["openapi"].startswith("3.")

    def test_sdk_calculate_end_to_end(self):
        client = sdk.RfautoClient()
        result = client.calculate(
            "attenuator_pi", {"attenuation_db": 3.0, "z0_ohm": 50.0})
        assert result["result"]["r_series_mid_ohm"] == 17.615

    def test_sdk_calculate_deterministic(self):
        client = sdk.RfautoClient()
        assert client.calculate("vswr_convert", {"vswr": 2.0}) == \
            client.calculate("vswr_convert", {"vswr": 2.0})

    def test_sdk_run_detail_and_error(self, tmp_path):
        _make_run(tmp_path)
        client = sdk.RfautoClient()
        assert client.run_detail(_RUN_ID)["run_id"] == _RUN_ID
        with pytest.raises(sdk.RfautoApiError) as excinfo:
            client.run_detail("no_such_run")
        assert excinfo.value.status_code == 404
        assert excinfo.value.code == "not_found"

    def test_sdk_list_calculators(self):
        names = [c["name"] for c in
                 sdk.RfautoClient().list_calculators()["calculators"]]
        assert "attenuator_pi" in names

    def test_sdk_query_dataset_end_to_end(self, tmp_path):
        _make_dataset(tmp_path)
        client = sdk.RfautoClient()
        data = client.query_dataset("demo", where="cost < 1.0")
        assert data["n_rows"] == 1

    def test_sdk_dataset_insights_end_to_end(self, tmp_path):
        """SDK 八方法进程内端到端：list/coverage/annotate/readiness/
        visibility/export_hf/register_public/load_sets。"""
        _make_registered_dataset(tmp_path, "demo", visibility="private")
        client = sdk.RfautoClient()
        assert client.list_datasets()["n_datasets"] == 1
        assert client.list_datasets(visibility="public")["n_datasets"] == 0
        assert client.dataset_coverage("demo", bins=5)["bins"] == 5
        assert client.annotate_ground_truth("demo", threshold=1)["n_gt_rows"] == 0
        assert client.neural_operator_readiness("demo")["threshold"] == 100
        with pytest.raises(sdk.RfautoApiError) as refused:
            client.export_hf_dataset("demo")
        assert refused.value.status_code == 400
        assert client.set_dataset_visibility("demo", "public")["visibility"] == "public"
        assert Path(client.export_hf_dataset("demo", license="mit")["card"]).exists()
        reg = client.register_public_dataset("demo", source="unit-test")
        assert reg["promoted"] is False and reg["overlap_ids"] == []
        sets = client.load_dataset_sets()
        assert sets["public"]["ids"] == ["demo"] and sets["private"]["ids"] == []

    def test_sdk_dataset_sets_conflict_surfaces_409(self, tmp_path):
        import yaml

        _make_registered_dataset(tmp_path, "demo", visibility="private")
        reg_dir = tmp_path / "runs" / "datasets"
        (reg_dir / "public_set.yaml").write_text(
            yaml.safe_dump({"schema_version": "1.0",
                            "entries": [{"name": "demo"}]}),
            encoding="utf-8")
        client = sdk.RfautoClient()
        with pytest.raises(sdk.RfautoApiError) as exc:
            client.load_dataset_sets()
        assert exc.value.status_code == 409 and exc.value.code == "conflict"

    def test_sdk_custom_transport_receives_contract(self):
        calls = []

        class _RecordingTransport:
            def request(self, method, path, *, params=None, json_body=None):
                calls.append((method, path, params, json_body))
                return 200, {"ok": True, "data": {"echo": True}}

        client = sdk.RfautoClient(transport=_RecordingTransport())
        assert client.health() == {"echo": True}
        assert calls == [("GET", "/api/v1/health", None, None)]

    def test_sdk_http_transport_uses_base_url(self, monkeypatch):
        captured = {}

        class _FakeResponse:
            status = 200

            def __init__(self, payload):
                self._body = json.dumps(payload).encode("utf-8")

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, *args, **kwargs):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            return _FakeResponse({"ok": True, "data": {"status": "ok"}})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        data = sdk.RfautoClient(base_url="http://127.0.0.1:9999/").health()
        assert data["status"] == "ok"
        assert captured["url"] == "http://127.0.0.1:9999/api/v1/health"
        assert captured["method"] == "GET"

    def test_sdk_http_transport_surfaces_http_error(self, monkeypatch):
        def fake_urlopen(request, *args, **kwargs):
            body = json.dumps({"ok": False, "error": {
                "code": "not_found", "message": "no"}}).encode("utf-8")
            raise urllib.error.HTTPError(
                request.full_url, 404, "Not Found", {}, io.BytesIO(body))

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        with pytest.raises(sdk.RfautoApiError) as excinfo:
            sdk.RfautoClient(base_url="http://127.0.0.1:9999").health()
        assert excinfo.value.status_code == 404
        assert excinfo.value.code == "not_found"


# ---------------------------------------------------------------------------
# 分层守卫
# ---------------------------------------------------------------------------

class TestLayerGuard:
    def test_rest_modules_do_not_reference_higher_layers(self):
        for name in ("rest_api.py", "sdk.py"):
            source = (
                _REPO / "src" / "rfauto" / "service" / name
            ).read_text(encoding="utf-8")
            assert "rfauto.cli" not in source
            assert "rfauto.mcp_server" not in source
