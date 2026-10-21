"""REST e2e 冒烟门（架构批 E2E-REST 席，2026-10-14）：REST 面（/api/v1）安全网。

照 UI-R7 先例（scripts/ui_e2e_smoke.py）把 REST 面真机冒烟固化为可复跑门：
起服→四组巡检+内核往返→结构化 verdict→退出码。REST-B schema 叶
（rfauto rest schema）落地后，REST-B+ 再动 service/rest_api.py（路由表/
信封/OpenAPI 面）先跑它当安全网。

巡检面（端点清单程序化枚举 rest_api.endpoint_inventory() 单源，禁手抄）：
  ①清单 vs 路由表一致：endpoint_inventory() 与 create_rest_app() ASGI
    路由表反射对账（路径+方法集逐位；starlette 对 GET 自动补 HEAD，对账
    前剔除）+计数自洽；再逐端点 HTTP 探针证"路由在线上场"——GET 面
    断言 handled JSON（信封或裸 spec），POST-only 面断言 GET→405（方法
    纪律；全程只读，不向写端点发 POST）。
  ②信封形态纪律：成功信封键序 ["ok","data"]（test_rest_envelope_ratchet
    线形契约同口径）+ok is True；错误路径 404 信封键集 {ok,error}+
    error.{code,message}；openapi.json 裸 spec 非信封形（raw 面钉）。
  ③OpenAPI spec 与 live 路由表互证：线上 GET /api/v1/openapi.json →
    validate_openapi_spec 结构自校验 ok+paths 方法映射 vs 反射路由表+
    vs 端点清单（路径/方法/operationId 三向）+版本串一致。
  ④坏参数 400 信封：limit 非法/越界+坏 JSON（bad_json）+缺参+SQL 白名单
    拒绝，逐条断言 400+error 信封形态与 code。
  ⑤确定性内核往返（铁律 7 同款面）：slotline synth/analyze 闭式结果
    ok=True 且物理量为正数（数值只出内核，冒烟不锚具体值——锚值属
    test_rest_api/test_physics_invariants 职责）。

起服（默认 spawn 模式）：**临时 cwd**（REST 面无静态/runs 挂载依赖——
临时 cwd 同时验证空态：/api/v1/runs 空清单）+备用端口从 8645 起动态选
（避开 serve() 缺省 8644 与 UI 冒烟 8643 起）+分离进程（日志落文件）+
就绪探针轮询 GET /api/v1/health（超时 fail-loud：杀进程树+日志尾进
verdict）。--base-url 可附着既有服务（跳过起服与空态面）。

rc：0=全过；1=任一 fail（含起服/探针失败 fail-loud）。任务口径两值语义。

用法：
  .venv/Scripts/python.exe scripts/rest_e2e_smoke.py
  .venv/Scripts/python.exe scripts/rest_e2e_smoke.py --json --out <verdict.json>
  .venv/Scripts/python.exe scripts/rest_e2e_smoke.py --base-url http://127.0.0.1:8644

注册面：scripts/ 自检类脚本惯例（ui_e2e_smoke 同款）——不挂 CLI 叶；注册
面=本文件+定向钉测试 tests/unit/test_rest_e2e_smoke_script.py；真机留档
内部证据目录。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

REPORT_SCHEMA = "架构批/rest_e2e_smoke/1"

#: 备用端口动态选起点（serve() 缺省 8644、UI 冒烟 8643 起——本门走 8645 起）。
DEFAULT_PORT_BASE = 8645

#: spawn 模式就绪探针总预算（首跑含 rfauto.service.rest_api+uvicorn import）。
DEFAULT_READY_TIMEOUT_S = 90.0

#: 路径参数探针哨兵（{run_id}/{name} 段替换形态；__smoke_ 前缀不可撞真 id）。
PROBE_PARAM = "__smoke_probe__"

# 成功信封纪律抽查面（200 + 键序 ["ok","data"] + ok is True）。
SUCCESS_ENVELOPE_API: list[str] = [
    "/api/v1/health",
    "/api/v1/runs",
    "/api/v1/calculators",
]

# 错误路径 404 信封抽查面（path 含 {param} 段时探针哨兵替换）。
NOT_FOUND_404_API: list[tuple[str, str]] = [
    ("/api/v1/runs/{run_id}", "not_found"),
    ("/api/v1/calculators/{name}/run", "not_found"),
]

# 坏参数 400 信封抽查面（method, path, raw_body, 期望 code；body None=GET）。
BAD_PARAM_400: list[tuple[str, str, bytes | None, str]] = [
    ("GET", "/api/v1/runs?limit=abc", None, "invalid_request"),
    ("GET", "/api/v1/runs?limit=0", None, "invalid_request"),
    ("POST", "/api/v1/slotline/analyze", b"{bad json", "bad_json"),
    ("POST", "/api/v1/slotline/analyze",
     json.dumps({}).encode(), "invalid_request"),
    ("POST", "/api/v1/db/query",
     json.dumps({"sql": "DROP TABLE runs"}).encode(), "invalid_request"),
]

# 确定性内核往返（铁律 7）：闭式综合/分析各一条（参数取 test_rest_api 同款
# 已知可行域；断言 ok=True+物理量为正，不锚具体值）。
_KERNEL_SYNTH: dict[str, float] = {
    "z0_ohm": 110.0, "h_mm": 1.524, "epsilon_r": 3.66, "freq_ghz": 2.5}
_KERNEL_ANALYZE: dict[str, float] = {
    "w_mm": 1.0, "h_mm": 1.524, "epsilon_r": 3.66, "freq_ghz": 2.5}

#: OpenAPI path item 内允许的 HTTP 方法键（rest_api._HTTP_METHODS 同款小写）。
_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch",
                 "trace")


# ═══════════════════════════ 纯函数/可注入工具 ═══════════════════════════

def check(cid: str, group: str, target: str, ok: bool, detail: str,
          dur_ms: float | None = None) -> dict[str, Any]:
    """单检查项构造器（verdict 检查项 schema 单源；ui_e2e_smoke 同形）。"""
    item: dict[str, Any] = {
        "id": cid, "group": group, "target": target,
        "pass": bool(ok), "detail": detail,
    }
    if dur_ms is not None:
        item["dur_ms"] = round(dur_ms, 1)
    return item


def pick_free_port(start: int, host: str = "127.0.0.1", tries: int = 50) -> int:
    """从 start 起动态选第一个可绑定空闲端口。"""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
        return port
    raise RuntimeError(f"{start} 起 {tries} 个端口均被占用")


def build_server_cmd(python_exe: str, port: int) -> list[str]:
    """起服命令（rest_api.serve()——REST 面既定入口，无 CLI 叶）。"""
    return [
        python_exe, "-c",
        f"from rfauto.service.rest_api import serve; "
        f"serve('127.0.0.1', {port})",
    ]


def build_taskkill_cmd(pid: int) -> list[str]:
    """Windows 杀进程树命令（list 传参不经 shell——#245 MSYS 转换坑规避）。"""
    return ["taskkill", "/PID", str(pid), "/T", "/F"]


def kill_tree(pid: int) -> None:
    """杀进程树（Windows taskkill /T；失败回落 terminate——best-effort）。"""
    if pid <= 0:
        return
    if os.name == "nt":
        try:
            subprocess.run(build_taskkill_cmd(pid), capture_output=True,
                           timeout=15, check=False)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    with contextlib.suppress(OSError):
        os.kill(pid, 15)


def http_raw(url: str, method: str = "GET", body: bytes | None = None,
             timeout: float = 15.0,
             getter: Callable[..., Any] | None = None) -> tuple[int, bytes,
                                                                dict[str, str]]:
    """HTTP 裸往返 → (status, body, headers)；HTTPError 也归一返回不抛。"""
    if getter is not None:  # 单测注入点（就绪探针超时路径 mock）
        return getter(url, method, body, timeout)
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers or {})


def http_json(url: str, method: str = "GET", body: bytes | None = None,
              timeout: float = 15.0) -> tuple[int, Any]:
    status, raw, _ = http_raw(url, method=method, body=body, timeout=timeout)
    try:
        return status, json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return status, None


def wait_ready(url: str, timeout_s: float, poll_interval: float = 0.25,
               getter: Callable[..., Any] | None = None,
               is_alive: Callable[[], bool] | None = None
               ) -> tuple[bool, str, float]:
    """就绪探针：轮询 GET url 直到 200；超时/进程先死都 fail-loud。

    Returns:
        (ok, reason, wall_s)。reason：成功="ready"；失败给"探针超时（日志
        尾见 verdict.meta.server.log）"或"进程提前退出"——调用方负责把
        日志尾塞进 verdict（本函数不读日志，保持可注入可单测）。
    """
    t0 = time.monotonic()
    while True:
        if is_alive is not None and not is_alive():
            return False, "server 进程提前退出（日志尾见 meta.server.log)", (
                time.monotonic() - t0)
        try:
            status, _, _ = http_raw(url, timeout=3.0, getter=getter)
            if status == 200:
                return True, "ready", time.monotonic() - t0
        except (OSError, urllib.error.URLError, ValueError):
            pass  # 未就绪的连接拒绝/超时——继续轮询
        if time.monotonic() - t0 >= timeout_s:
            return False, (
                f"就绪探针超时（{timeout_s:.0f}s，日志尾见 meta.server.log）"), (
                time.monotonic() - t0)
        time.sleep(poll_interval)


def log_tail(path: Path, n_lines: int = 30, max_chars: int = 4000) -> str:
    """服务器日志尾（fail-loud 证据链；读不了如实降级占位）。"""
    try:
        lines = Path(path).read_text(
            encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-n_lines:])
        return tail[-max_chars:]
    except OSError:
        return "<log 不可读>"


# ─── 信封形态判据（REST 传输面双形；AU-2/棘轮契约口径）────────────────────

def _success_envelope_shape(body: Any) -> tuple[bool, str]:
    """成功信封判据：dict+键序 ["ok","data"]（线形契约，棘轮测试同口径）
    +ok is True。"""
    if not isinstance(body, dict):
        return False, f"非 JSON 对象（type={type(body).__name__}）"
    keys = list(body.keys())
    if keys != ["ok", "data"]:
        return False, f"键集/键序非 ['ok','data']（线形契约）：{keys}"
    if body["ok"] is not True:
        return False, f"ok 非 True：{body['ok']!r}"
    return True, "ok=True + data 在场"


def _error_envelope_shape(body: Any, want_code: str | None = None
                          ) -> tuple[bool, str]:
    """错误信封判据：dict+键集 {ok,error}+ok is False+error 键集
    {code,message}（对象形 error——REST 传输面与 service 层 errors 列表
    契约不同形，见 docs/envelope_contract.md）；want_code 给定时加比对。"""
    if not isinstance(body, dict):
        return False, f"非 JSON 对象（type={type(body).__name__}）"
    if set(body.keys()) != {"ok", "error"}:
        return False, f"键集非 {{ok,error}}：{sorted(body.keys())}"
    if body["ok"] is not False:
        return False, f"预期 ok=False，实际 ok={body['ok']!r}"
    err = body.get("error")
    if not (isinstance(err, dict) and set(err.keys()) == {"code", "message"}):
        return False, f"error 键集非 {{code,message}}：{err!r}"
    if want_code is not None and err.get("code") != want_code:
        return False, f"code={err.get('code')!r}（期望 {want_code!r}）"
    return True, f"code={err.get('code')} message={str(err.get('message'))[:80]}"


# ─── 程序化枚举与对账（rfauto 反射；禁手抄清单）──────────────────────────

def reflect_rest_routes() -> list[tuple[str, list[str]]]:
    """create_rest_app() ASGI 路由表反射 → [(模板路径, 声明方法)]。

    starlette 对含 GET 的路由自动补 HEAD——对账口径剔除（声明面单源是
    _ROUTE_TABLE，HEAD 是装配层衍生物）。
    """
    from starlette.routing import Route

    from rfauto.service.rest_api import create_rest_app

    out: list[tuple[str, list[str]]] = []
    for r in create_rest_app().routes:
        if isinstance(r, Route):
            methods = sorted(m for m in (r.methods or ()) if m != "HEAD")
            out.append((r.path, methods))
    return out


def live_inventory() -> dict[str, Any]:
    """endpoint_inventory() 端点清单（schema 导出叶同源；ok 信封）。"""
    from rfauto.service import rest_api

    return rest_api.endpoint_inventory()


def reconcile_inventory(routes: list[tuple[str, list[str]]],
                        endpoints: list[dict[str, Any]]) -> dict[str, Any]:
    """清单 vs 路由表对账（纯函数）：缺/多路径与方法差异清单。"""
    route_map = {p: sorted(m) for p, m in routes}
    inv_map = {e["path"]: sorted(e["methods"]) for e in endpoints}
    missing = sorted(set(route_map) - set(inv_map))
    extra = sorted(set(inv_map) - set(route_map))
    method_diffs = [
        f"{p}: 路由={route_map[p]} 清单={inv_map[p]}"
        for p in sorted(set(route_map) & set(inv_map))
        if route_map[p] != inv_map[p]]
    return {"missing": missing, "extra": extra, "method_diffs": method_diffs,
            "n_routes": len(route_map), "n_endpoints": len(inv_map)}


def spec_method_map(spec: Any) -> dict[str, list[str]]:
    """OpenAPI spec paths → {path: sorted 方法}（纯函数；非 HTTP 键剔除）。"""
    out: dict[str, list[str]] = {}
    for path, item in (spec or {}).get("paths", {}).items():
        methods = sorted(k for k in item if k.lower() in _HTTP_METHODS)
        out[path] = [m.upper() for m in methods]
    return out


def spec_operation_ids(spec: Any) -> list[str]:
    """spec paths → operationId 清单（纯函数；逐 path item 逐方法收集）。"""
    out: list[str] = []
    for item in (spec or {}).get("paths", {}).values():
        for key, op in item.items():
            if key.lower() in _HTTP_METHODS and isinstance(op, dict):
                oid = op.get("operationId")
                if oid:
                    out.append(str(oid))
    return out


def probe_url_of(route_path: str, sentinel: str = PROBE_PARAM) -> str:
    """路由模板路径 → 具体探针路径（{param} 段整体替换为哨兵）。"""
    return re.sub(r"\{[^}]+\}", sentinel, route_path)


def classify_get_probe(methods: list[str], status: int, parsed: Any
                       ) -> tuple[bool, str]:
    """GET 探针分类（纯函数；只读探针的双分支判据）。

    - GET 面：handled JSON 才算路由在场——信封形（有 ok 键）或裸 spec 形
      （openapi.json，有 openapi 键）；starlette 路由缺席回 plain text
      "Not Found"（非 JSON dict）→ 红。
    - POST-only 面：GET → 405（Method Not Allowed）=路径在场+方法纪律
      正确；其余状态=路由缺席或方法面漂移 → 红。
    """
    if "GET" in methods:
        if not isinstance(parsed, dict):
            return False, (f"HTTP {status} 非 JSON 对象——路由缺席的 plain "
                           f"404 形态?（body 头 {str(parsed)[:40]!r}）")
        if "ok" in parsed:
            return True, f"HTTP {status} handled 信封 JSON（ok 键在场）"
        if "openapi" in parsed:
            return True, f"HTTP {status} 裸 spec JSON（openapi 键在场）"
        return False, f"HTTP {status} JSON 对象但无 ok/openapi 键：{list(parsed)[:6]}"
    if status == 405:
        return True, "HTTP 405（POST-only 路由在场：方法纪律正确）"
    return False, f"HTTP {status}（期望 405：路由缺席或方法面漂移）"


# ═══════════════════════════ 巡检面 ═══════════════════════════

def sweep_inventory_schema(routes: list[tuple[str, list[str]]],
                           inventory: dict[str, Any]) -> list[dict[str, Any]]:
    """①schema 面：端点清单 vs ASGI 路由表对账 + 计数自洽（进程内反射）。"""
    checks: list[dict[str, Any]] = []
    endpoints = inventory.get("endpoints") or []
    rec = reconcile_inventory(routes, endpoints)
    drift = rec["missing"] + rec["extra"] + rec["method_diffs"]
    checks.append(check(
        "inventory.schema_vs_routes", "inventory",
        f"endpoint_inventory vs create_rest_app（{rec['n_routes']} 路由）",
        not drift,
        "路径+方法集逐位一致" if not drift else f"对账漂移：{drift}"))
    counts_ok = (inventory.get("ok") is True
                 and inventory.get("n_endpoints") == len(endpoints)
                 and inventory.get("n_operations")
                 == sum(len(e.get("methods") or []) for e in endpoints)
                 and len(endpoints) == rec["n_routes"])
    checks.append(check(
        "inventory.counts", "inventory", "n_endpoints/n_operations",
        counts_ok,
        f"n_endpoints={inventory.get('n_endpoints')} "
        f"n_operations={inventory.get('n_operations')} "
        f"endpoints={len(endpoints)} routes={rec['n_routes']}（自洽）"))
    return checks


def sweep_inventory_live(base_url: str,
                         inventory: dict[str, Any]) -> list[dict[str, Any]]:
    """①live 面：逐端点 GET 探针证路由在线上场（只读——POST-only 面断言
    405，不向写端点发 POST）。"""
    checks: list[dict[str, Any]] = []
    for ep in inventory.get("endpoints") or []:
        methods = [m.upper() for m in ep.get("methods") or []]
        path = probe_url_of(ep["path"])
        t0 = time.monotonic()
        status, parsed = http_json(base_url + path, timeout=10.0)
        ok, detail = classify_get_probe(methods, status, parsed)
        checks.append(check(
            f"inventory.live.{ep['path']}", "inventory_live",
            f"GET {path}（声明 {','.join(methods)}）", ok, detail,
            dur_ms=(time.monotonic() - t0) * 1000))
    return checks


def sweep_envelope(base_url: str) -> list[dict[str, Any]]:
    """②信封形态纪律：成功信封键序+错误路径 404 信封+裸 spec 非信封形。"""
    checks: list[dict[str, Any]] = []
    for path in SUCCESS_ENVELOPE_API:
        t0 = time.monotonic()
        status, body = http_json(base_url + path)
        ok_env, env_detail = _success_envelope_shape(body)
        ok = status == 200 and ok_env
        checks.append(check(f"envelope.ok.{path}", "envelope", path, ok,
                            f"HTTP {status}; {env_detail}",
                            dur_ms=(time.monotonic() - t0) * 1000))
    for template, want_code in NOT_FOUND_404_API:
        path = probe_url_of(template)
        t0 = time.monotonic()
        status, body = http_json(base_url + path,
                                 method="POST" if "{name}" in template else "GET",
                                 body=b"{}" if "{name}" in template else None)
        ok_env, env_detail = _error_envelope_shape(body, want_code)
        ok = status == 404 and ok_env
        checks.append(check(
            f"envelope.404.{template}", "envelope", path, ok,
            f"HTTP {status}; {env_detail}",
            dur_ms=(time.monotonic() - t0) * 1000))
    status, body = http_json(base_url + "/api/v1/openapi.json")
    raw_ok = (status == 200 and isinstance(body, dict)
              and "openapi" in body and "ok" not in body and "paths" in body)
    checks.append(check(
        "envelope.raw_spec", "envelope", "/api/v1/openapi.json", raw_ok,
        f"HTTP {status}; 裸 spec 形（openapi/paths 键在场、无 ok 信封包裹）"
        if raw_ok else f"HTTP {status}; 裸 spec 形违约：keys={list(body)[:6]}"))
    return checks


def sweep_openapi(base_url: str,
                  routes: list[tuple[str, list[str]]],
                  inventory: dict[str, Any]) -> list[dict[str, Any]]:
    """③OpenAPI spec 与 live 路由表互证：线上 spec 结构自校验+三向对账。"""
    checks: list[dict[str, Any]] = []
    from rfauto.service import rest_api

    t0 = time.monotonic()
    status, spec = http_json(base_url + "/api/v1/openapi.json")
    if not isinstance(spec, dict):
        checks.append(check("openapi.fetch", "openapi",
                            "GET /api/v1/openapi.json", False,
                            f"HTTP {status}；spec 非 JSON 对象"))
        return checks
    verdict = rest_api.validate_openapi_spec(spec)
    checks.append(check(
        "openapi.validate", "openapi", "validate_openapi_spec",
        verdict.get("ok") is True,
        f"HTTP {status}; 结构自校验 "
        + ("ok" if verdict.get("ok") else f"errors={verdict.get('errors')}"),
        dur_ms=(time.monotonic() - t0) * 1000))

    spec_map = spec_method_map(spec)
    route_map = {p: sorted(m) for p, m in routes}
    spec_norm = {p: sorted(m) for p, m in spec_map.items()}
    missing = sorted(set(route_map) - set(spec_norm))
    extra = sorted(set(spec_norm) - set(route_map))
    method_diffs = [
        f"{p}: 路由={route_map[p]} spec={spec_norm[p]}"
        for p in sorted(set(route_map) & set(spec_norm))
        if route_map[p] != spec_norm[p]]
    sync_ok = not (missing or extra or method_diffs)
    checks.append(check(
        "openapi.routes_sync", "openapi",
        f"spec.paths vs 反射路由表（{len(route_map)} 路由）", sync_ok,
        "paths+方法逐位一致" if sync_ok
        else f"漂移：仅路由表有={missing} 仅 spec 有={extra} 方法差={method_diffs}"))

    endpoints = inventory.get("endpoints") or []
    inv_map = {e["path"]: sorted(m.upper() for m in e.get("methods") or [])
               for e in endpoints}
    inv_missing = sorted(set(inv_map) - set(spec_norm))
    inv_extra = sorted(set(spec_norm) - set(inv_map))
    inv_ok = (not inv_missing and not inv_extra
              and inventory.get("openapi_version") == spec.get("openapi"))
    checks.append(check(
        "openapi.inventory_sync", "openapi",
        f"spec.paths vs 端点清单（{len(inv_map)} 端点）", inv_ok,
        f"路径集一致+版本 {spec.get('openapi')}"
        f"（清单声明 {inventory.get('openapi_version')}）" if inv_ok
        else f"漂移：仅清单有={inv_missing} 仅 spec 有={inv_extra}"))

    spec_ids = spec_operation_ids(spec)
    inv_ids = sorted(str(e.get("operation_id")) for e in endpoints)
    ids_ok = sorted(spec_ids) == inv_ids and len(spec_ids) == len(set(spec_ids))
    checks.append(check(
        "openapi.operation_ids", "openapi", "operationId 清单", ids_ok,
        f"spec {len(spec_ids)} 个=清单 {len(inv_ids)} 个且无重复" if ids_ok
        else f"漂移：spec={sorted(set(spec_ids) - set(inv_ids))} "
             f"清单={sorted(set(inv_ids) - set(spec_ids))}"))
    return checks


def sweep_badparam(base_url: str) -> list[dict[str, Any]]:
    """④坏参数 400 信封抽查（错误路径 JSON 形态+code 语义）。"""
    checks: list[dict[str, Any]] = []
    for method, path, body, want_code in BAD_PARAM_400:
        t0 = time.monotonic()
        status, parsed = http_json(base_url + path, method=method, body=body)
        ok_env, env_detail = _error_envelope_shape(parsed, want_code)
        ok = status == 400 and ok_env
        checks.append(check(
            f"badparam.{path.split('?')[0]}.{method.lower()}", "badparam",
            f"{method} {path}", ok, f"HTTP {status}; {env_detail}",
            dur_ms=(time.monotonic() - t0) * 1000))
    return checks


def sweep_kernel(base_url: str) -> list[dict[str, Any]]:
    """⑤确定性内核往返：slotline synth/analyze 闭式结果（数值只出内核）。"""
    checks: list[dict[str, Any]] = []
    body = json.dumps(_KERNEL_SYNTH).encode()
    status, parsed = http_json(base_url + "/api/v1/slotline/synth",
                               method="POST", body=body)
    result = ((parsed or {}).get("data") or {}).get("result") or {}
    w_mm = result.get("w_mm")
    ok = (status == 200 and (parsed or {}).get("ok") is True
          and isinstance(w_mm, (int, float)) and not isinstance(w_mm, bool)
          and float(w_mm) > 0)
    checks.append(check(
        "kernel.slotline_synth", "kernel",
        f"POST /api/v1/slotline/synth（z0={_KERNEL_SYNTH['z0_ohm']}Ω）", ok,
        f"HTTP {status}; ok={ (parsed or {}).get('ok') } w_mm={w_mm}（期望正数）"))
    body = json.dumps(_KERNEL_ANALYZE).encode()
    status, parsed = http_json(base_url + "/api/v1/slotline/analyze",
                               method="POST", body=body)
    result = ((parsed or {}).get("data") or {}).get("result") or {}
    z0 = result.get("z0_ohm")
    ok = (status == 200 and (parsed or {}).get("ok") is True
          and isinstance(z0, (int, float)) and not isinstance(z0, bool)
          and float(z0) > 0)
    checks.append(check(
        "kernel.slotline_analyze", "kernel",
        f"POST /api/v1/slotline/analyze（w={_KERNEL_ANALYZE['w_mm']}mm）", ok,
        f"HTTP {status}; ok={ (parsed or {}).get('ok') } z0_ohm={z0}（期望正数）"))
    return checks


def sweep_empty_state(base_url: str) -> list[dict[str, Any]]:
    """空态面（仅 spawn 模式）：临时 cwd 下 runs 空清单（REST 面无静态
    挂载依赖——空态即降级形态）。"""
    checks: list[dict[str, Any]] = []
    status, body = http_json(base_url + "/api/v1/runs")
    runs = ((body or {}).get("data") or {}).get("runs")
    ok = (status == 200 and _success_envelope_shape(body)[0] and runs == [])
    checks.append(check(
        "empty.runs_list", "empty_state", "/api/v1/runs", ok,
        f"GET /api/v1/runs → {status}，runs={runs!r}（期望 200+空清单："
        "临时 cwd 无 runs/）"))
    return checks


# ═══════════════════════════ verdict 组装与编排 ═══════════════════════════

def assemble_verdict(meta: dict[str, Any], checks: list[dict[str, Any]],
                     ) -> dict[str, Any]:
    """verdict 组装（纯函数）：逐检查项+墙钟+rc 语义（0 全过/1 有 fail）。"""
    n_fail = sum(1 for c in checks if not c.get("pass"))
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **meta,
        "checks": checks,
        "summary": {
            "total": len(checks),
            "pass": len(checks) - n_fail,
            "fail": n_fail,
            "rc": 1 if n_fail else 0,
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="REST e2e 冒烟门（架构批 E2E-REST）：起服+巡检+verdict")
    ap.add_argument("--port", type=int, default=None,
                    help=f"服务端口（缺省从 {DEFAULT_PORT_BASE} 起动态选空闲）")
    ap.add_argument("--base-url", default=None,
                    help="附着既有服务（跳过起服与空态面——空态断言仅 spawn 模式成立）")
    ap.add_argument("--timeout", type=float, default=DEFAULT_READY_TIMEOUT_S,
                    help=f"就绪探针预算秒（缺省 {DEFAULT_READY_TIMEOUT_S:.0f}）")
    ap.add_argument("--out", default=None, help="verdict JSON 落盘路径")
    ap.add_argument("--json", action="store_true",
                    help="stdout 输出 verdict JSON（人类摘要转 stderr）")
    ap.add_argument("--log", default=None,
                    help="服务器日志路径（缺省临时目录，随跑清理）")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    t_start = time.monotonic()
    ts_start = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def say(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    checks: list[dict[str, Any]] = []
    proc: subprocess.Popen[bytes] | None = None
    log_fh = None
    tmp_cwd: str | None = None
    base_url = args.base_url
    spawned = base_url is None
    log_path = Path(args.log) if args.log else Path(tempfile.gettempdir()) / (
        f"rfauto_rest_smoke_{int(time.time())}.log")

    # ① 程序化枚举（进程内反射失败=fail-loud——REST 装配面坏了）
    try:
        routes = reflect_rest_routes()
        inventory = live_inventory()
    except Exception as exc:
        checks.append(check("inventory.reflect", "inventory",
                            "create_rest_app()/endpoint_inventory()", False,
                            f"REST 面反射失败: {exc}"))
        routes, inventory = [], {}
    if routes:
        checks.extend(sweep_inventory_schema(routes, inventory))

    # ② 起服（spawn 模式：临时 cwd+备用端口动态选+分离进程+就绪探针）
    if spawned:
        port = args.port if args.port else pick_free_port(DEFAULT_PORT_BASE)
        tmp_cwd = tempfile.mkdtemp(prefix="rfauto_rest_smoke_cwd_")
        cmd = build_server_cmd(sys.executable, port)
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        say(f"[smoke] 起服：{' '.join(cmd)}（cwd={tmp_cwd}）")
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_fh = open(log_path, "wb")  # noqa: SIM115 - 生命周期=本函数
            proc = subprocess.Popen(
                cmd, cwd=tmp_cwd, stdout=log_fh, stderr=log_fh, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            checks.append(check("server.start", "server", " ".join(cmd), False,
                                f"起服失败: {exc}"))
        if proc is not None:
            base_url = f"http://127.0.0.1:{port}"
            ok, reason, wall = wait_ready(
                base_url + "/api/v1/health", args.timeout,
                is_alive=lambda: proc.poll() is None)
            checks.append(check(
                "server.ready", "server", base_url, ok,
                f"{reason}（就绪墙钟 {wall:.1f}s）", dur_ms=wall * 1000))
            if not ok:
                kill_tree(proc.pid)
                checks.append(check(
                    "server.log_tail", "server", str(log_path), False,
                    log_tail(log_path)))
                base_url = None
    else:
        say(f"[smoke] 附着既有服务：{base_url}")
        checks.append(check("server.attach", "server", base_url, True,
                            "attach 模式（空态面不适用，跳过）"))

    # ③ 巡检（服务活着才巡；schema 对账在反射成功时已做）
    if base_url and routes:
        checks.extend(sweep_inventory_live(base_url, inventory))
        checks.extend(sweep_envelope(base_url))
        checks.extend(sweep_openapi(base_url, routes, inventory))
        checks.extend(sweep_badparam(base_url))
        checks.extend(sweep_kernel(base_url))
        if spawned:
            checks.extend(sweep_empty_state(base_url))

    # ④ 收尾（杀服+清临时 cwd）
    if proc is not None:
        kill_tree(proc.pid)
        try:
            if proc.poll() is None:
                proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
    if log_fh is not None:
        log_fh.close()
    if tmp_cwd:
        import shutil

        shutil.rmtree(tmp_cwd, ignore_errors=True)

    meta: dict[str, Any] = {
        "wall_s": round(time.monotonic() - t_start, 2),
        "ts_start": ts_start,
        "server": {
            "mode": "spawned" if spawned else "attached",
            "base_url": base_url,
            "cwd": tmp_cwd,
            "pid": proc.pid if proc is not None else None,
            "log": str(log_path),
        },
        "n_routes": len(routes),
        "n_endpoints": len(inventory.get("endpoints") or []),
    }
    verdict = assemble_verdict(meta, checks)
    n_fail = verdict["summary"]["fail"]
    say(f"[smoke] 完成：{verdict['summary']['pass']}/{len(checks)} pass，"
        f"{n_fail} fail（wall={verdict['wall_s']}s）")

    payload = json.dumps(verdict, ensure_ascii=False, indent=1)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        say(f"[smoke] verdict 落盘：{out_path}")
    if args.json:
        print(payload)
    else:
        for c in checks:
            if not c["pass"]:
                say(f"  [FAIL] {c['id']}: {c['detail'][:300]}")
        print(f"rest_e2e_smoke: rc={verdict['summary']['rc']} "
              f"({verdict['summary']['pass']}/{len(checks)} pass)")
    return int(verdict["summary"]["rc"])


if __name__ == "__main__":
    sys.exit(main())
