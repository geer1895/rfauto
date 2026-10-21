"""scripts/rest_e2e_smoke.py + docs_site/rest_schema.json 定向钉子测试（架构批 E2E-REST 席）。

只钉离线确定性面（#139：单测禁网络）——脚本注册面（argparse 契约）、
verdict 组装 rc 语义、就绪探针超时/进程早死路径（getter 注入 mock）、
REST 传输面双形信封判据（正反两向）、路由反射对账/GET 探针分类纯函数、
起服/杀树命令形态；REST schema 常驻产物漂移钉（docs_site/rest_schema.json
再生产物逐字节一致 + live 枚举一致 + 溯源头在场）。真机起服巡检不在
单测面（内部证据目录 留档口径）。
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import time
import urllib.error
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[2]

_SCRIPT = _REPO / "scripts" / "rest_e2e_smoke.py"
_SPEC = importlib.util.spec_from_file_location("rest_e2e_smoke", _SCRIPT)
smoke = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(smoke)


def _load_builder():
    """按文件路径装载 scripts/build_docs_pages.py（test_docs_site 同款模式；
    py3.12 dataclass 注解解析需先注册 sys.modules）。"""
    path = _REPO / "scripts" / "build_docs_pages.py"
    spec = importlib.util.spec_from_file_location("_e2e_rest_bdp", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_e2e_rest_bdp"] = mod
    spec.loader.exec_module(mod)
    return mod


# ═══════════ verdict 组装与 rc 语义 ════════════

def test_check_shape():
    c = smoke.check("id1", "grp", "tgt", False, "细节")
    assert c == {"id": "id1", "group": "grp", "target": "tgt",
                 "pass": False, "detail": "细节"}


def test_assemble_verdict_rc0_when_all_pass():
    checks = [smoke.check("a", "g", "t", True, "ok"),
              smoke.check("b", "g", "t", True, "ok", dur_ms=1.0)]
    v = smoke.assemble_verdict({"n_routes": 25}, checks)
    assert v["schema"] == smoke.REPORT_SCHEMA == "架构批/rest_e2e_smoke/1"
    assert v["summary"] == {"total": 2, "pass": 2, "fail": 0, "rc": 0}
    assert v["checks"][1]["dur_ms"] == 1.0
    assert v["n_routes"] == 25


def test_assemble_verdict_rc1_on_any_fail():
    checks = [smoke.check("a", "g", "t", True, "ok"),
              smoke.check("b", "g", "t", False, "boom")]
    v = smoke.assemble_verdict({}, checks)
    assert v["summary"]["rc"] == 1
    assert v["summary"]["fail"] == 1 and v["summary"]["pass"] == 1


# ═══════════ 就绪探针（超时/早死/成功三路径，getter 注入）═══════════

def _never_ready(url: str, method: str = "GET", body: bytes | None = None,
                 timeout: float = 15.0) -> tuple[int, bytes, dict]:
    raise urllib.error.URLError("connection refused")


def _always_200(url: str, method: str = "GET", body: bytes | None = None,
                timeout: float = 15.0) -> tuple[int, bytes, dict]:
    return 200, b"ok", {"content-type": "application/json"}


def test_wait_ready_success_first_poll():
    ok, reason, wall = smoke.wait_ready(
        "http://x/api/v1/health", 5.0, poll_interval=0.01, getter=_always_200)
    assert ok and reason == "ready" and wall < 1.0


def test_wait_ready_timeout_path_fail_loud():
    t0 = time.monotonic()
    ok, reason, wall = smoke.wait_ready(
        "http://x/api/v1/health", 0.5, poll_interval=0.05, getter=_never_ready,
        is_alive=lambda: True)
    assert not ok
    assert "超时" in reason
    assert 0.4 <= time.monotonic() - t0 < 5.0
    assert wall >= 0.4


def test_wait_ready_dead_process_fails_fast():
    ok, reason, _ = smoke.wait_ready(
        "http://x/api/v1/health", 30.0, poll_interval=0.05,
        getter=_never_ready, is_alive=lambda: False)
    assert not ok
    assert "提前退出" in reason


# ═══════════ 起服命令与杀树命令形态（#245 坑钉）═══════════

def test_build_server_cmd_shape():
    cmd = smoke.build_server_cmd("py.exe", 8645)
    assert cmd[0] == "py.exe" and cmd[1] == "-c"
    assert "from rfauto.service.rest_api import serve" in cmd[2]
    assert "serve('127.0.0.1', 8645)" in cmd[2]


def test_build_taskkill_cmd_verbatim_list_form():
    # #245：list 传参不经 shell，/PID 不得被 MSYS 路径转换吃掉。
    assert smoke.build_taskkill_cmd(1234) == [
        "taskkill", "/PID", "1234", "/T", "/F"]


def test_pick_free_port_returns_bindable():
    port = smoke.pick_free_port(18645)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))  # 选出的端口必须真的可绑
    # 8645 起：避开 serve() 缺省 8644 与 UI 冒烟 8643 起（任务口径）。
    assert smoke.DEFAULT_PORT_BASE == 8645


# ═══════════ 信封形态判据（REST 传输面双形；正反两向）═══════════

def test_success_envelope_policy():
    ok, _ = smoke._success_envelope_shape({"ok": True, "data": {"x": 1}})
    assert ok
    # 键序=线形契约（test_rest_envelope_ratchet 同口径）：data 在前即红
    ok, detail = smoke._success_envelope_shape({"data": {}, "ok": True})
    assert not ok and "键序" in detail
    ok, detail = smoke._success_envelope_shape({"ok": False, "data": {}})
    assert not ok and "ok 非 True" in detail
    ok, detail = smoke._success_envelope_shape({"ok": True})  # 缺 data 键
    assert not ok
    ok, detail = smoke._success_envelope_shape({"ok": True, "data": {}, "x": 1})
    assert not ok  # 多余顶层键=信封违约
    ok, _ = smoke._success_envelope_shape(["not", "a", "dict"])
    assert not ok


def test_error_envelope_policy():
    ok, _ = smoke._error_envelope_shape(
        {"ok": False, "error": {"code": "not_found", "message": "run 不存在"}})
    assert ok
    ok, _ = smoke._error_envelope_shape(
        {"ok": False, "error": {"code": "not_found", "message": "x"}},
        want_code="not_found")
    assert ok
    ok, detail = smoke._error_envelope_shape(
        {"ok": False, "error": {"code": "invalid_request", "message": "x"}},
        want_code="not_found")
    assert not ok and "code=" in detail
    ok, detail = smoke._error_envelope_shape(
        {"ok": True, "error": {"code": "x", "message": "y"}})
    assert not ok and "预期 ok=False" in detail
    # service 层 errors 列表形不是 REST 传输面错误信封（不同形契约）
    ok, detail = smoke._error_envelope_shape({"ok": False, "errors": ["x"]})
    assert not ok and "键集" in detail
    ok, _ = smoke._error_envelope_shape(
        {"ok": False, "error": {"code": "x", "msg": "y"}})  # message 缺
    assert not ok
    ok, _ = smoke._error_envelope_shape("plain not found")
    assert not ok


# ═══════════ 程序化枚举/对账/探针分类（纯函数+live 反射）═══════════

def test_reflect_rest_routes_matches_live_inventory():
    """live 对 live：ASGI 路由表反射 vs endpoint_inventory 零漂移（#247
    零硬编码数字——计数互证，不写死 25）。"""
    routes = smoke.reflect_rest_routes()
    inventory = smoke.live_inventory()
    rec = smoke.reconcile_inventory(routes, inventory["endpoints"])
    assert not rec["missing"] and not rec["extra"] and not rec["method_diffs"]
    assert rec["n_routes"] == inventory["n_endpoints"] > 0
    assert inventory["n_operations"] == sum(len(m) for _, m in routes)


def test_reconcile_inventory_flags_drift():
    routes = [("/api/v1/a", ["GET"]), ("/api/v1/b", ["POST"])]
    endpoints = [
        {"path": "/api/v1/a", "methods": ["GET"]},
        {"path": "/api/v1/c", "methods": ["GET"]},
        {"path": "/api/v1/b", "methods": ["POST", "DELETE"]},
    ]
    rec = smoke.reconcile_inventory(routes, endpoints)
    assert rec["missing"] == []  # 路径双侧都在，只是方法集不一致
    assert rec["extra"] == ["/api/v1/c"]
    assert rec["method_diffs"] == ["/api/v1/b: 路由=['POST'] 清单=['DELETE', 'POST']"]


def test_spec_method_map_and_operation_ids():
    from rfauto.service import rest_api

    spec = rest_api.openapi_spec()
    spec_map = smoke.spec_method_map(spec)
    assert spec_map["/api/v1/health"] == ["GET"]
    assert spec_map["/api/v1/calculators/{name}/run"] == ["POST"]
    ids = smoke.spec_operation_ids(spec)
    assert "getHealth" in ids and len(ids) == len(set(ids))
    # 非方法键（summary 等）不得混入方法映射
    assert all(set(m) <= {x.upper() for x in smoke._HTTP_METHODS}
               for m in spec_map.values())


def test_spec_route_reconciliation_against_reflection():
    """live spec vs live 路由表逐位一致（互证面的离线同款口径）。"""
    from rfauto.service import rest_api

    spec_map = {p: sorted(m)
                for p, m in smoke.spec_method_map(rest_api.openapi_spec()).items()}
    route_map = {p: sorted(m) for p, m in smoke.reflect_rest_routes()}
    assert spec_map == route_map


def test_probe_url_of_substitutes_params():
    assert smoke.probe_url_of("/api/v1/runs/{run_id}") == (
        f"/api/v1/runs/{smoke.PROBE_PARAM}")
    assert smoke.probe_url_of("/api/v1/calculators/{name}/run") == (
        f"/api/v1/calculators/{smoke.PROBE_PARAM}/run")
    assert smoke.probe_url_of("/api/v1/health") == "/api/v1/health"


def test_classify_get_probe_get_face():
    ok, _ = smoke.classify_get_probe(["GET"], 200, {"ok": True, "data": {}})
    assert ok
    ok, _ = smoke.classify_get_probe(["GET"], 404, {
        "ok": False, "error": {"code": "not_found", "message": "x"}})
    assert ok  # handled 业务 404 信封=路由在场
    ok, _ = smoke.classify_get_probe(["GET"], 200, {"openapi": "3.0.3"})
    assert ok  # 裸 spec 形
    ok, detail = smoke.classify_get_probe(["GET"], 404, None)  # plain 404
    assert not ok and "非 JSON" in detail
    ok, _ = smoke.classify_get_probe(["GET"], 200, {"neither": 1})
    assert not ok


def test_classify_get_probe_post_only_face():
    ok, _ = smoke.classify_get_probe(["POST"], 405, "Method Not Allowed")
    assert ok
    ok, detail = smoke.classify_get_probe(["POST"], 404, None)
    assert not ok and "405" in detail
    ok, _ = smoke.classify_get_probe(["POST"], 200, {"ok": True})
    assert not ok  # GET 打进 POST-only 面=方法纪律漂移，即便 200 也不收


# ═══════════ 巡检面常量（防误编辑清空巡检面）═══════════

def test_sweep_constants_shapes():
    assert len(smoke.SUCCESS_ENVELOPE_API) >= 3
    assert all(p.startswith("/api/v1/") for p in smoke.SUCCESS_ENVELOPE_API)
    assert len(smoke.NOT_FOUND_404_API) >= 2
    assert any("{name}" in t for t, _ in smoke.NOT_FOUND_404_API)
    assert len(smoke.BAD_PARAM_400) >= 4
    assert any(m == "POST" for m, _, _, _ in smoke.BAD_PARAM_400)
    # 坏 JSON 形态在场（json.loads 必炸的 body 恰一条——bad_json 400 面）
    assert sum(1 for _, _, b, _ in smoke.BAD_PARAM_400
               if b is not None and not isinstance(_loads(b), dict)) == 1
    assert all(p.startswith("/api/v1/") for _, p, _, _ in smoke.BAD_PARAM_400)
    assert all(v > 0 for v in smoke._KERNEL_SYNTH.values())
    assert all(v > 0 for v in smoke._KERNEL_ANALYZE.values())


def test_argparse_contract():
    ns = smoke._parse_args([])
    assert ns.port is None and ns.base_url is None
    assert ns.json is False and ns.out is None
    assert ns.timeout == pytest.approx(smoke.DEFAULT_READY_TIMEOUT_S)
    ns2 = smoke._parse_args(["--json", "--out", "v.json", "--port", "8700",
                             "--base-url", "http://127.0.0.1:8644",
                             "--timeout", "30"])
    assert ns2.json and ns2.out == "v.json" and ns2.port == 8700
    assert ns2.base_url == "http://127.0.0.1:8644"
    assert ns2.timeout == pytest.approx(30.0)


# ═══════════ REST schema 常驻产物漂移钉（docs_site/rest_schema.json）═══════════

def _loads(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None


def _committed_artifact() -> dict[str, Any]:
    return json.loads(
        (_REPO / "docs_site" / "rest_schema.json").read_text(encoding="utf-8"))


def test_rest_schema_artifact_matches_regeneration():
    """再生产物逐字节一致（红=需在仓根重跑 python scripts/build_docs_pages.py）。"""
    text, n = _load_builder().build_rest_schema_page()
    committed = (_REPO / "docs_site" / "rest_schema.json").read_text(
        encoding="utf-8")
    assert committed == text
    assert n == _committed_artifact()["n_endpoints"] > 0


def test_rest_schema_artifact_has_provenance():
    doc = _committed_artifact()
    prov = doc.get("_provenance")
    assert isinstance(prov, dict)
    assert prov.get("generator") == "scripts/build_docs_pages.py"
    assert "endpoint_inventory" in str(prov.get("source"))
    assert doc["ok"] is True and doc["face"] == "rest"
    assert doc["openapi_version"] == "3.0.3"


def test_rest_schema_artifact_matches_live_enumeration():
    """已提交产物 vs live 枚举一致（路径+方法集逐位；漂移钉本体）。"""
    doc = _committed_artifact()
    inv_map = {e["path"]: sorted(e["methods"]) for e in doc["endpoints"]}
    route_map = {p: sorted(m) for p, m in smoke.reflect_rest_routes()}
    assert inv_map == route_map
    assert doc["n_endpoints"] == len(route_map)
    assert doc["n_operations"] == sum(len(m) for m in route_map.values())
