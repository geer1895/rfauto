"""scripts/ui_e2e_smoke.py 的定向钉子测试（aurora_d UI-R7 席）。

只钉离线确定性面（#139：单测禁网络）——脚本注册面（argparse 契约）、
verdict 组装 rc 语义、就绪探针超时/进程早死路径（getter 注入 mock）、
视图路由程序化枚举、路由模板正则、CDP 事件归桶、杀树命令形态。
真机起服+浏览器巡检不在单测面（runs/aurora_d/uir7/ 留档口径）。
"""

import importlib.util
import socket
import time
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ui_e2e_smoke.py"
_SPEC = importlib.util.spec_from_file_location("ui_e2e_smoke", _SCRIPT)
smoke = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(smoke)


# ═══════════ 视图路由程序化枚举（勿手抄钉）═══════════

def test_extract_view_routes_ordered_unique():
    html = (
        '<nav><button data-v="dashboard">总览</button>'
        '<button data-v="tune">调参</button>'
        '<button data-v="dashboard">重复忽略</button>'
        '<button data-v="detail" style="display:none">详情</button>'
        '<div data-page="not-a-data-v"></div></nav>')
    assert smoke.extract_view_routes(html) == ["dashboard", "tune", "detail"]


def test_extract_view_routes_real_index_has_26_views():
    html = (smoke.__dict__["REPO"]
            / "src/rfauto/ui/static/index.html").read_text(encoding="utf-8")
    views = smoke.extract_view_routes(html)
    assert len(views) >= 26  # uir2 口径 26 视图（只收不放）
    assert views[0] == "dashboard" and "detail" in views and "queue" in views


def test_enumerate_js_modules_covers_root_and_pages(tmp_path: Path):
    (tmp_path / "pages").mkdir()
    for name in ("theme.js", "app.js"):
        (tmp_path / name).write_text("// js", encoding="utf-8")
    (tmp_path / "pages" / "router.js").write_text("// js", encoding="utf-8")
    (tmp_path / "pages" / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "echarts.min.js").write_text("//", encoding="utf-8")
    rels = smoke.enumerate_js_modules(tmp_path)
    assert rels == ["app.js", "theme.js", "pages/router.js"]


# ═══════════ 路由模板正则（防漂移对账面）═══════════

def test_route_pattern_plain_and_param():
    rx = smoke.route_pattern_to_regex("/api/runs/{run_id}")
    assert rx.fullmatch("/api/runs/abc_123") and not rx.fullmatch("/api/runs/")


def test_route_pattern_path_type_param_spans_segments():
    rx = smoke.route_pattern_to_regex("/api/runs/{run_id}/figs/{name:path}")
    assert rx.fullmatch("/api/runs/r1/figs/a/b.png")
    assert not rx.fullmatch("/api/runs/r1/other/x")


def test_validate_targets_against_routes_flags_drift():
    table = ["/api/runs", "/api/runs/{run_id}", "/api/gallery"]
    assert smoke.validate_targets_against_routes(
        ["/api/runs", "/api/runs/x", "/api/gallery?limit=1"], table) == []
    missing = smoke.validate_targets_against_routes(
        ["/api/runs", "/api/removed_route"], table)
    assert missing == ["/api/removed_route"]


# ═══════════ verdict 组装与 rc 语义 ═══════════

def test_assemble_verdict_rc0_when_all_pass():
    checks = [smoke.check("a", "g", "t", True, "ok"),
              smoke.check("b", "g", "t", True, "ok", dur_ms=1.0)]
    v = smoke.assemble_verdict({"console_layer": "cdp"}, checks)
    assert v["schema"] == smoke.REPORT_SCHEMA
    assert v["summary"] == {"total": 2, "pass": 2, "fail": 0, "rc": 0}
    assert v["checks"][1]["dur_ms"] == 1.0
    assert v["console_layer"] == "cdp"


def test_assemble_verdict_rc1_on_any_fail():
    checks = [smoke.check("a", "g", "t", True, "ok"),
              smoke.check("b", "g", "t", False, "boom")]
    v = smoke.assemble_verdict({}, checks)
    assert v["summary"]["rc"] == 1
    assert v["summary"]["fail"] == 1 and v["summary"]["pass"] == 1


def test_check_shape():
    c = smoke.check("id1", "grp", "tgt", False, "细节")
    assert c == {"id": "id1", "group": "grp", "target": "tgt",
                 "pass": False, "detail": "细节"}


# ═══════════ 就绪探针（超时/早死/成功三路径，getter 注入）═══════════

def _never_ready(url: str, method: str = "GET", body: bytes | None = None,
                 timeout: float = 15.0) -> tuple[int, bytes, dict]:
    import urllib.error
    raise urllib.error.URLError("connection refused")


def _always_200(url: str, method: str = "GET", body: bytes | None = None,
                timeout: float = 15.0) -> tuple[int, bytes, dict]:
    return 200, b"ok", {"content-type": "text/html"}


def test_wait_ready_success_first_poll():
    ok, reason, wall = smoke.wait_ready(
        "http://x/", 5.0, poll_interval=0.01, getter=_always_200)
    assert ok and reason == "ready" and wall < 1.0


def test_wait_ready_timeout_path_fail_loud():
    t0 = time.monotonic()
    ok, reason, wall = smoke.wait_ready(
        "http://x/", 0.5, poll_interval=0.05, getter=_never_ready,
        is_alive=lambda: True)
    assert not ok
    assert "超时" in reason
    assert 0.4 <= time.monotonic() - t0 < 5.0
    assert wall >= 0.4


def test_wait_ready_dead_process_fails_fast():
    ok, reason, _ = smoke.wait_ready(
        "http://x/", 30.0, poll_interval=0.05, getter=_never_ready,
        is_alive=lambda: False)
    assert not ok
    assert "提前退出" in reason


# ═══════════ 起服命令与杀树命令形态（#245 坑钉）═══════════

def test_build_server_cmd_shape():
    cmd = smoke.build_server_cmd("py.exe", 8643)
    assert cmd[:4] == ["py.exe", "-m", "rfauto.cli.main", "ui"]
    assert "--no-open" in cmd and "--port" in cmd
    assert cmd[cmd.index("--port") + 1] == "8643"
    assert "8643" in " ".join(cmd) and "--host" in cmd


def test_build_taskkill_cmd_verbatim_list_form():
    # #245：list 传参不经 shell，/PID 不得被 MSYS 路径转换吃掉。
    assert smoke.build_taskkill_cmd(1234) == [
        "taskkill", "/PID", "1234", "/T", "/F"]


def test_pick_free_port_returns_bindable():
    port = smoke.pick_free_port(18463)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))  # 选出的端口必须真的可绑
    assert smoke.DEFAULT_PORT_BASE == 8643  # 任务口径：8643 起动态选


# ═══════════ 信封判据（正反两向）═══════════

def test_ok_envelope_policy():
    ok, _ = smoke._json_ok_envelope({"ok": True, "runs": []})
    assert ok
    ok, detail = smoke._json_ok_envelope({"ok": False, "errors": ["x"]})
    assert not ok and "ok=False" in detail
    ok, detail = smoke._json_ok_envelope({"runs": []})  # 无 ok 键不惩罚
    assert ok
    ok, _ = smoke._json_ok_envelope(["not", "a", "dict"])
    assert not ok


def test_fail_envelope_policy():
    ok, _ = smoke._fail_envelope({"ok": False, "errors": ["run 不存在: x"]})
    assert ok
    ok, _ = smoke._fail_envelope({"ok": True, "errors": []})
    assert not ok
    ok, _ = smoke._fail_envelope({"ok": False, "errors": "bare-string"})
    assert not ok  # AU-2 收敛语义：errors 须 list[str]


def test_generic_envelope_wellformed_allows_business_empty_state():
    # uir7 实证：降级空态下 cost_timeline 200+ok=False+errors 指引是合法信封
    ok, detail = smoke._json_envelope_wellformed(
        {"ok": False, "errors": ["runs 索引库不存在: runs\\registry.sqlite"]})
    assert ok and "业务空态" in detail
    ok, _ = smoke._json_envelope_wellformed({"ok": True, "runs": []})
    assert ok
    ok, _ = smoke._json_envelope_wellformed({"runs": []})  # 无 ok 键不惩罚
    assert ok
    ok, _ = smoke._json_envelope_wellformed(
        {"ok": False, "errors": "bare"})  # 形态违约仍红
    assert not ok
    ok, _ = smoke._json_envelope_wellformed({"ok": "yes"})
    assert not ok  # ok 非布尔
    ok, _ = smoke._json_envelope_wellformed([1, 2])
    assert not ok


def test_split_known_errors_exemption_is_narrow():
    bucket = {"console": [], "exceptions": [],
              "log": ["Failed to load resource: 404 "
                      "http://x/api/sparams/?mode=db"],
              "net": ["404 http://x/api/sparams/?mode=db",
                      "500 http://x/api/gallery"]}
    errs, known = smoke.split_known_errors(bucket)
    assert len(errs) == 1 and "500" in errs[0]
    assert len(known) == 2 and all("/api/sparams/?" in k for k in known)


def test_split_known_errors_with_real_run_id_not_exempt():
    bucket = {"console": [], "exceptions": [], "log": [],
              "net": ["404 http://x/api/sparams/realid?mode=db"]}
    errs, known = smoke.split_known_errors(bucket)
    assert errs and not known  # 带 id 的正常 fetch 不误豁免


def test_kernel_tolerances_match_calculator_rounding():
    # calculator_service.vswr_convert 返回 round(g,6)/round(rl,4)：
    # |1/3 - 0.333333| = 3.33e-7 必须落进容差（uir7 首跑 1e-9 过紧实证）。
    assert abs(0.333333 - smoke._KERNEL_GAMMA) <= smoke._KERNEL_GAMMA_TOL
    assert abs(9.5424 - smoke._KERNEL_RL_DB) <= smoke._KERNEL_RL_TOL


# ═══════════ CDP 事件归桶（favicon 豁免/abort 不计）═══════════

def test_record_cdp_event_console_error_and_exception():
    bucket: dict[str, list] = {"console": [], "exceptions": [], "log": [],
                               "net": []}
    smoke._record_cdp_event(bucket, {
        "method": "Runtime.consoleAPICalled",
        "params": {"type": "error", "args": [{"type": "string",
                                              "value": "boom"}]}})
    smoke._record_cdp_event(bucket, {
        "method": "Runtime.consoleAPICalled",
        "params": {"type": "warning", "args": [{"value": "w"}]}})
    smoke._record_cdp_event(bucket, {
        "method": "Runtime.exceptionThrown",
        "params": {"exceptionDetails": {"text": "Uncaught",
                                        "exception": {"description": "E"}}}})
    assert bucket["console"] == ["boom"]
    assert bucket["exceptions"] and "Uncaught" in bucket["exceptions"][0]


def test_record_cdp_event_log_favicon_exempt_and_net_4xx():
    bucket: dict[str, list] = {"console": [], "exceptions": [], "log": [],
                               "net": []}
    smoke._record_cdp_event(bucket, {
        "method": "Log.entryAdded",
        "params": {"entry": {"level": "error", "text": "Failed to load",
                             "url": "http://x/favicon.ico"}}})
    smoke._record_cdp_event(bucket, {
        "method": "Log.entryAdded",
        "params": {"entry": {"level": "error", "text": "real failure",
                             "url": "http://x/static/missing.js"}}})
    smoke._record_cdp_event(bucket, {
        "method": "Network.responseReceived",
        "params": {"response": {"status": 404,
                                "url": "http://x/api/runs/nope"}}})
    smoke._record_cdp_event(bucket, {
        "method": "Network.loadingFailed",
        "params": {"errorText": "net::ERR_ABORTED"}})  # SPA 导航 abort 不计
    assert bucket["log"] and "favicon" not in bucket["log"][0]
    assert "real failure" in bucket["log"][0]
    assert bucket["net"] == ["404 http://x/api/runs/nope"]


def test_chrome_launch_cmd_headless_flags():
    cmd = smoke._chrome_launch_cmd("chrome.exe", 9333, "prof")
    assert cmd[0] == "chrome.exe"
    assert "--headless=new" in cmd
    assert "--remote-debugging-port=9333" in cmd
    assert "--user-data-dir=prof" in cmd


# ═══════════ 注册面/argparse 契约 ════════════

def test_argparse_contract():
    ns = smoke._parse_args([])
    assert ns.port is None and ns.base_url is None
    assert ns.json is False and ns.no_browser is False
    assert ns.timeout == pytest.approx(smoke.DEFAULT_READY_TIMEOUT_S)
    assert ns.visit_timeout == pytest.approx(smoke.DEFAULT_VISIT_TIMEOUT_S)
    assert smoke.DEFAULT_PORT_BASE == 8643
    ns2 = smoke._parse_args(["--json", "--out", "v.json", "--port", "8700",
                             "--base-url", "http://127.0.0.1:8642",
                             "--no-browser", "--timeout", "30"])
    assert ns2.json and ns2.out == "v.json" and ns2.port == 8700
    assert ns2.base_url == "http://127.0.0.1:8642" and ns2.no_browser
    assert ns2.timeout == pytest.approx(30.0)


def test_targets_constants_consistent():
    """strict/generic/400 目标常量非空且形态合法（防误编辑清空巡检面）。"""
    assert len(smoke.STRICT_API) >= 5
    assert len(smoke.GENERIC_API) >= 20
    assert len(smoke.BAD_PARAM_400) >= 3
    assert any("limit=abc" in p for _, p, _ in smoke.BAD_PARAM_400)
    assert all(p.startswith("/api/") for p in smoke.GENERIC_API)
    assert any(m == "POST" for m, _, _ in smoke.BAD_PARAM_400)
    assert "/api/runs/__smoke_missing_run__" in smoke.FAIL_ENVELOPE_200


def test_kernel_constants_vswr2():
    assert smoke._KERNEL_VSWR == 2.0
    assert abs(smoke._KERNEL_GAMMA - 1.0 / 3.0) < 1e-12
    assert abs(smoke._KERNEL_RL_DB - 9.5424) < 1e-9
