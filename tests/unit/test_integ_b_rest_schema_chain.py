"""INTEG-B 席跨模块集成测试：REST schema 链全链一致（aurora_d INTEG-B，2026-10-14）.

链条（单源 _ROUTE_TABLE 程序化枚举 → 四个消费面身份不变形，零网络）：

    service/rest_api._ROUTE_TABLE
      ├─ endpoint_inventory() ── CLI `rfauto rest schema --out`（cli/domains/rest.py）
      ├─ openapi_spec() ──────── CLI `rfauto rest schema --openapi --out`
      ├─ create_rest_app() ASGI 路由表（传输线形）
      └─ build_docs_pages.build_rest_schema_page() → docs_site/rest_schema.json
          （构建期 inventory ↔ ASGI 反射互证，漂移 RuntimeError 拒绝出页）

钉面：四消费面同一信封（service inventory == CLI 落盘 == 已提交 docs_site
产物 == openapi spec paths 逐位一致）；漂移检测错误路径（装配失同步 →
RuntimeError 拒绝出页；inventory 失败信封 → 拒绝出页；坏 $ref → 校验器
ok=False）；边界（确定性、operation_id 唯一、信封形态摘要单源派生）。

既有单测分工：test_rest_e2e_smoke_script 钉产物再生逐字节与 live 枚举、
test_a8d 钉 REST 传输信封——本文件补「CLI 导出面与 docs_site 常驻产物、
与 openapi spec 三方同源」的跨模块链与漂移门的拒绝行为。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import pytest
from starlette.applications import Starlette
from starlette.routing import Route as StarletteRoute
from typer.testing import CliRunner

from rfauto.cli.main import app  # 先于域模块导入：锁定子应用注册位次
from rfauto.service import rest_api

runner = CliRunner()


def _load_builder():
    """按文件路径装载 scripts/build_docs_pages.py（test_docs_site 同款；
    py3.12 dataclass 注解解析需先注册 sys.modules）。"""
    path = REPO / "scripts" / "build_docs_pages.py"
    spec = importlib.util.spec_from_file_location("_integ_b_bdp", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_integ_b_bdp"] = mod
    spec.loader.exec_module(mod)
    return mod


def _route_map_of(asgi_app) -> dict[str, list[str]]:
    """ASGI 路由表反射（build_rest_schema_page 同口径：剔除 HEAD）。"""
    return {
        r.path: sorted(m for m in (r.methods or ()) if m != "HEAD")
        for r in asgi_app.routes if isinstance(r, StarletteRoute)
    }


def _inv_map_of(inventory: dict[str, Any]) -> dict[str, list[str]]:
    return {e["path"]: sorted(e["methods"]) for e in inventory["endpoints"]}


@pytest.fixture(scope="module")
def inventory() -> dict[str, Any]:
    inv = rest_api.endpoint_inventory()
    assert inv["ok"] is True, inv.get("errors")
    return inv


# ────────────────────────── 正向：四消费面同源 ──────────────────────────


class TestFourFacesConsistency:
    def test_inventory_matches_asgi_route_table(self, inventory):
        assert _inv_map_of(inventory) == _route_map_of(rest_api.create_rest_app())
        assert inventory["n_endpoints"] == len(inventory["endpoints"]) > 0
        assert inventory["n_operations"] == sum(
            len(e["methods"]) for e in inventory["endpoints"])

    def test_openapi_spec_paths_match_inventory(self, inventory):
        spec = rest_api.openapi_spec()
        assert spec["openapi"] == inventory["openapi_version"] == "3.0.3"
        spec_map = {
            path: sorted(m.upper() for m in ops)
            for path, ops in spec["paths"].items()
        }
        assert spec_map == _inv_map_of(inventory)
        verdict = rest_api.validate_openapi_spec(spec)
        assert verdict["ok"] is True and verdict["errors"] == []

    def test_cli_schema_export_equals_service_inventory(
            self, inventory, tmp_path):
        out = tmp_path / "rest_schema_export.json"
        r = runner.invoke(app, ["rest", "schema", "--out", str(out), "--json"])
        assert r.exit_code == 0, r.output
        assert out.is_file()
        # 落盘文件=纯 inventory 信封（written/out_path 记账只进 stdout 信封）
        exported = json.loads(out.read_text(encoding="utf-8"))
        assert exported == inventory
        envelope = json.loads(r.stdout)
        assert envelope["written"] is True
        assert envelope["out_path"] == str(out)

    def test_cli_openapi_export_equals_service_spec(self, tmp_path):
        out = tmp_path / "openapi.json"
        r = runner.invoke(app, ["rest", "schema", "--openapi",
                                "--out", str(out), "--json"])
        assert r.exit_code == 0, r.output
        assert json.loads(out.read_text(encoding="utf-8")) == (
            rest_api.openapi_spec())
        payload = json.loads(r.stdout)
        assert payload["ok"] is True and payload["written"] is True
        assert payload["format"] == "openapi"
        assert payload["n_endpoints"] == len(rest_api.openapi_spec()["paths"])

    def test_committed_docs_site_artifact_equals_live_faces(
            self, inventory, tmp_path):
        """已提交 docs_site/rest_schema.json == 再生页 == service inventory
        == CLI 导出（去 _provenance/written/out_path 记账键后逐键一致）。"""
        builder = _load_builder()
        text, n = builder.build_rest_schema_page()
        committed_path = REPO / "docs_site" / "rest_schema.json"
        committed = json.loads(committed_path.read_text(encoding="utf-8"))
        assert json.loads(text) == committed
        assert n == committed["n_endpoints"] > 0

        prov = committed.pop("_provenance")
        assert prov["generator"] == "scripts/build_docs_pages.py"
        assert committed == inventory

        out = tmp_path / "cli_export.json"
        r = runner.invoke(app, ["rest", "schema", "--out", str(out),
                                "--json"])
        assert r.exit_code == 0, r.output
        exported = json.loads(out.read_text(encoding="utf-8"))
        assert exported == committed  # 第三面：CLI 导出同源

    def test_inventory_deterministic(self):
        a = rest_api.endpoint_inventory()
        b = rest_api.endpoint_inventory()
        assert json.dumps(a, sort_keys=True, ensure_ascii=False) == (
            json.dumps(b, sort_keys=True, ensure_ascii=False))

    def test_envelope_shape_summary_single_source(self, inventory):
        # 信封形态摘要=OpenAPI components 单源派生（schema dict 非 $ref 串）
        shape = inventory["envelope_shape"]
        assert shape["success_schema"] == rest_api._schemas()[
            "SuccessEnvelope"]
        assert shape["error_schema"] == rest_api._schemas()["ErrorEnvelope"]
        assert all(isinstance(e["envelope"], bool)
                   for e in inventory["endpoints"])


# ────────────────────────── 错误路径：漂移门拒绝 ──────────────────────────


class TestDriftGateRejects:
    def test_assembly_desync_rejects_page(self, monkeypatch):
        """路由装配与 _ROUTE_TABLE 失同步（少装一条）→ RuntimeError 拒绝出页。

        生产形态失同步源=create_rest_app 被改成手写路由（正是该门存在的
        故障模式）；测试经装配函数缝注入陈旧装配模拟。"""
        builder = _load_builder()
        stale = Starlette(routes=rest_api.create_rest_app().routes[1:])
        monkeypatch.setattr(rest_api, "create_rest_app", lambda: stale)
        with pytest.raises(RuntimeError, match="漂移"):
            builder.build_rest_schema_page()

    def test_extra_assembly_route_rejects_page(self, monkeypatch):
        builder = _load_builder()
        extra = Starlette(routes=[
            *rest_api.create_rest_app().routes,
            StarletteRoute("/api/v1/ghost", rest_api.endpoint_inventory,
                           methods=["GET"]),
        ])
        monkeypatch.setattr(rest_api, "create_rest_app", lambda: extra)
        with pytest.raises(RuntimeError, match="漂移"):
            builder.build_rest_schema_page()

    def test_inventory_failure_envelope_rejects_page(self, monkeypatch):
        builder = _load_builder()
        monkeypatch.setattr(
            rest_api, "endpoint_inventory",
            lambda: {"ok": False, "errors": ["注入失败"]})
        with pytest.raises(RuntimeError, match="拒绝出页"):
            builder.build_rest_schema_page()

    def test_spec_validator_rejects_broken_ref(self):
        spec = rest_api.openapi_spec()
        broken = json.loads(json.dumps(spec))
        # 把一个响应 schema $ref 指向不存在的组件（装配漂移的 schema 面）
        first_path = next(iter(broken["paths"]))
        first_op = next(iter(broken["paths"][first_path].values()))
        first_op["responses"][next(iter(first_op["responses"]))][
            "content"]["application/json"]["schema"]["$ref"] = (
            "#/components/schemas/Ghost")
        verdict = rest_api.validate_openapi_spec(broken)
        assert verdict["ok"] is False
        assert any("Ghost" in e or "$ref" in e for e in verdict["errors"])

    def test_cli_openapi_without_out_is_usage_error(self):
        r = runner.invoke(app, ["rest", "schema", "--openapi", "--json"])
        assert r.exit_code == 2
        assert json.loads(r.stdout)["ok"] is False
