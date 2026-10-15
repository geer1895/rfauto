"""UI e2e 冒烟门（aurora_d UI-R7 席，2026-10-14）：UI 大重构安全网制度化。

背景：UI-R1（server.py→routes/ 10 域拆分）+UI-R2（pages.js→pages/ 33 模块
ESM）两次大重构各靠一次一次性真机冒烟验收（先例 runs/aurora_d/uir2/ 26 视图
巡检+SMOKE_LOG）。本脚本把该冒烟固化为可复跑门：起服→五面巡检→结构化
verdict→退出码，UI-R8+ 再拆任何 UI 面先跑它当安全网。

巡检五面：
  ①视图路由：GET / 从**服务端 HTML 程序化枚举** nav data-v 注册表（app.js
    _VALID_PAGES 的派生同源；router.js VIEWS 是运行时注入空表，磁盘静态源
    只有 index.html 的 data-v——不手抄）——HTTP 层逐视图断言注册在壳内；
    CDP 层再逐视图真实导航（#/<view>）断言 nav 激活 + h2.page 渲染。
  ②核心 API：目标路径逐条对照 **server 路由表程序化校验**（create_ui_app()
    routes 反射，{param} 段转正则全匹配——UI-R8 改路由名即当场红，防
    "脚本绿但路由已漂移"）；strict 面（ok 信封+键型）+generic 面（200+
    JSON dict+ok 不得为 False）+确定性内核往返（vswr_convert 铁律 7）。
  ③静态资源：static/ 根+pages/ 全部 *.js 磁盘枚举逐个 GET——200 且
    Content-Type text/javascript（ESM 硬要求，uir2 口径）。
  ④坏参数 400 信封：limit=abc 形态×2+坏 JSON POST×1（A8-D ParamError→400
    error_envelope 面）；另附两条 200+ok=False 业务失败信封（run 不存在/
    runs diff 非法 id）。
  ⑤console error：能力自选并如实报告——CDP 层（websockets+本机
    Chrome/Edge headless：逐视图 consoleAPICalled/exceptionThrown/Log/
    Network≥400 全收，favicon 豁免+已知空态豁免（KNOWN_EMPTY_STATE_NET
    只收不放，逐条留痕））→ 缺浏览器或 websockets 时降级
    node --check 语法兜底 → 连 node 都缺则如实记 skipped（console_layer=
    none，不判绿冒充也不误红）。

起服（默认 spawn 模式）：**临时 cwd**（非仓根——刻意验证降级路径：runs
静态挂载缺席 404+stderr 提示+/api/runs 空清单）+备用端口从 8643 起动态
选空闲+分离进程（日志落文件）+就绪探针轮询（超时 fail-loud：杀进程树+
日志尾进 verdict）。--base-url 可附着既有服务（跳过起服与降级面——降级
断言只对 spawn 模式成立）。

rc：0=全过；1=任一 fail（含起服/探针失败 fail-loud）。任务口径两值语义。

用法：
  .venv/Scripts/python.exe scripts/ui_e2e_smoke.py
  .venv/Scripts/python.exe scripts/ui_e2e_smoke.py --json --out <verdict.json>
  .venv/Scripts/python.exe scripts/ui_e2e_smoke.py --base-url http://127.0.0.1:8643

注册面：scripts/ 自检类脚本惯例（check_numbers/audit_* 同款）——不挂 CLI
叶（新增叶触发注册序金快照+check_numbers 权威计数+docs 三处五钉，席位
禁碰 docs 冲突）；注册面=本文件+定向钉测试 tests/unit/
test_ui_e2e_smoke_script.py（最小代价裁定）。
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import shutil
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

REPORT_SCHEMA = "aurora_d/ui_e2e_smoke/1"

#: 备用端口动态选起点（8642 是 rfauto ui 缺省口，冒烟避开走 8643 起）。
DEFAULT_PORT_BASE = 8643

#: CDP 调试口动态选起点（避开 9222 常规调试口）。
CDP_PORT_BASE = 9333

#: spawn 模式就绪探针总预算（首跑含 rfauto 全量 import，实测 ~10s 级）。
DEFAULT_READY_TIMEOUT_S = 90.0

#: 单视图 CDP 导航+渲染就绪预算。
DEFAULT_VISIT_TIMEOUT_S = 20.0

#: 渲染就绪后的静置窗（loopback 异步 fetch 落地 console error 的余量）。
SETTLE_S = 1.0

#: 浏览器探测顺序（env RFAUTO_UI_SMOKE_BROWSER 显式指定优先）。
_BROWSER_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)

# strict 面：200 + ok True + 指定键型（cwd 无关，临时 cwd 下也成立）。
STRICT_API: list[tuple[str, str, type]] = [
    ("/api/runs", "runs", list),
    ("/api/recipes", "recipes", list),
    ("/api/tune/status", "running", bool),
    ("/api/gallery", "cards", list),
    ("/api/calculators", "calculators", list),
]

# generic 面：200 + JSON dict + （有 ok 键则不得为 False）。
GENERIC_API: list[str] = [
    "/api/tune/trials",
    "/api/solvers",
    "/api/solvers/viz",
    "/api/datasets",
    "/api/anchors",
    "/api/uq/samples",
    "/api/calibration",
    "/api/reports",
    "/api/cost_timeline",
    "/api/loop/boards",
    "/api/campaign_queue",
    "/api/edb_status",
    "/api/inbox",
    "/api/sandbox/drafts",
    "/api/playground/runs",
    "/api/farfield",
    "/api/field",
    "/api/pareto_runs",
    "/api/profile",
    "/api/chat/settings",
    "/api/chat/prompt",
    "/api/chat/stats",
]

# 坏参数 400 信封抽查（method, path, raw_body；body None=GET）。
BAD_PARAM_400: list[tuple[str, str, bytes | None]] = [
    ("GET", "/api/runs?limit=abc", None),
    ("GET", "/api/inbox?limit=abc", None),
    ("POST", "/api/calculators/run", b"{bad json"),
]

# 200 + ok=False 业务失败信封抽查（uir2 边界面制度化）。
FAIL_ENVELOPE_200: list[str] = [
    "/api/runs/__smoke_missing_run__",
    "/api/runs/diff?a=__smoke_a__&b=__smoke_b__",
]

#: 确定性内核往返（铁律 7：数值只出自确定性内核）：VSWR=2 → |Γ|=1/3 精确。
#: 内核返回按 6/4 位小数 round（calculator_service vswr_convert），容差取
#: 末位半 ulp 量级——非松门，是内核既定舍入口径。
_KERNEL_VSWR = 2.0
_KERNEL_GAMMA = 1.0 / 3.0
_KERNEL_RL_DB = 9.5424
_KERNEL_GAMMA_TOL = 5e-7   # round(x, 6) 半 ulp
_KERNEL_RL_TOL = 5e-5      # round(x, 4) 半 ulp

#: 已知空态豁免（uir7 真机实证，非回归；豁免清单只收不放）：sparams 视图
#: 空态下 run 下拉为空 → sel.value="" → fetch /api/sparams/?mode=db →
#: 404（view_sparams.js load() 无空 id 守卫，encodeURIComponent("") 形态
#: 与拆分前 pages.js 同构；页面 DOM 侧 ok=False 错误面板正常）。命中前缀
#: 的网络 error 归豁免桶并逐条留痕，其余 error 仍硬红。
KNOWN_EMPTY_STATE_NET: tuple[str, ...] = ("/api/sparams/?",)


# ═══════════════════════════ 纯函数/可注入工具 ═══════════════════════════

def check(cid: str, group: str, target: str, ok: bool, detail: str,
          dur_ms: float | None = None) -> dict[str, Any]:
    """单检查项构造器（verdict 检查项 schema 单源）。"""
    item: dict[str, Any] = {
        "id": cid, "group": group, "target": target,
        "pass": bool(ok), "detail": detail,
    }
    if dur_ms is not None:
        item["dur_ms"] = round(dur_ms, 1)
    return item


def extract_view_routes(html: str) -> list[str]:
    """服务端 index.html → nav data-v 视图路由清单（程序化枚举，不手抄）。

    app.js `_VALID_PAGES = [...querySelectorAll("[data-v]")]` 的静态同源；
    去重保序（隐藏 detail 按钮同在注册表，26 颗）。
    """
    seen: list[str] = []
    for m in re.finditer(r'data-v="([a-zA-Z0-9_]+)"', html or ""):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def enumerate_js_modules(static_root: Path) -> list[str]:
    """static 根+pages/ 全部 *.js 相对路径（磁盘枚举，静态根只读）。"""
    root = Path(static_root)
    out: list[str] = []
    for sub in ("", "pages"):
        d = root / sub if sub else root
        if d.is_dir():
            out.extend(sorted(
                (sub + "/" if sub else "") + p.name for p in d.glob("*.js")))
    return out


def route_pattern_to_regex(route_path: str) -> re.Pattern[str]:
    """starlette 路由模板（/api/runs/{run_id}）→ 具体路径全匹配正则。

    {name:path} 形态（跨段参数）转 .+，普通 {param} 转 [^/]+。
    """
    path_type = re.sub(r"\{[^}:]+:path\}", ".+", route_path)
    return re.compile(re.sub(r"\{[^}]+\}", "[^/]+", path_type) + r"$")


def pick_free_port(start: int, host: str = "127.0.0.1", tries: int = 50) -> int:
    """从 start 起动态选第一个可绑定空闲端口（备用端口 8643 动态选）。"""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
        return port
    raise RuntimeError(f"{start} 起 {tries} 个端口均被占用")


def build_server_cmd(python_exe: str, port: int) -> list[str]:
    """起服命令（rfauto ui 叶；--no-open 防冒烟弹浏览器）。"""
    return [
        python_exe, "-m", "rfauto.cli.main", "ui",
        "--host", "127.0.0.1", "--port", str(port), "--no-open",
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


def find_browser() -> str | None:
    """CDP 浏览器能力探测：env 显式指定 > 常见安装位 > PATH。"""
    env = os.environ.get("RFAUTO_UI_SMOKE_BROWSER", "").strip()
    if env:
        return env if Path(env).is_file() else None
    for cand in _BROWSER_CANDIDATES:
        if Path(cand).is_file():
            return cand
    for name in ("chrome.exe", "msedge.exe", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


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


def _json_ok_envelope(body: Any) -> tuple[bool, str]:
    """信封判据：dict 且（有 ok 键则必须 True）——400/失败信封专用反向。"""
    if not isinstance(body, dict):
        return False, f"非 JSON 对象（type={type(body).__name__}）"
    if "ok" in body and body.get("ok") is not True:
        return False, f"ok=False envelope: {body.get('errors')}"
    return True, "ok"


def _json_envelope_wellformed(body: Any) -> tuple[bool, str]:
    """generic 面判据：200+dict+ok（若有）须 bool+（ok=False 时 errors 须
    非空 list[str]）——降级空态的业务性 ok=False 是合法信封（uir7 实证：
    /api/cost_timeline 无 runs 索引库 → 200+ok=False+errors 指引），判的
    是"信封形态纪律"不是"业务必须成功"。"""
    if not isinstance(body, dict):
        return False, f"非 JSON 对象（type={type(body).__name__}）"
    if "ok" not in body:
        return True, "dict（无 ok 键）"
    if not isinstance(body.get("ok"), bool):
        return False, f"ok 非布尔：{body.get('ok')!r}"
    if body["ok"]:
        return True, "ok=True"
    errs = body.get("errors")
    if not (isinstance(errs, list) and errs
            and all(isinstance(e, str) for e in errs)):
        return False, f"ok=False 但 errors 非法（AU-2 须 list[str]）：{errs!r}"
    return True, f"ok=False 业务空态信封（errors={errs[:1]}）"


# ═══════════════════════════ 程序化枚举面（rfauto 反射）══════════════════════════

def enumerate_server_api_routes() -> list[str]:
    """create_ui_app() 路由表反射 → /api/* 模板路径清单（程序化、不手抄）。

    UI-R8 改路由名 → 本清单变 → 巡检目标当场对不上即红（防脚本与路由
    漂移双绿）。include_runs_mount=False：纯路由表反射，不碰磁盘。
    """
    from starlette.routing import Route

    from rfauto.ui.server import create_ui_app

    app = create_ui_app(include_runs_mount=False)
    out: list[str] = []
    for r in app.routes:
        if isinstance(r, Route) and r.path.startswith("/api/"):
            out.append(r.path)
    return out


def validate_targets_against_routes(targets: list[str],
                                    api_routes: list[str]) -> list[str]:
    """巡检目标逐条对照路由表 → 对不上的目标清单（空=全命中）。"""
    regexes = [route_pattern_to_regex(p) for p in api_routes]
    missing: list[str] = []
    for t in targets:
        path = t.split("?", 1)[0]
        if not any(rx.fullmatch(path) for rx in regexes):
            missing.append(t)
    return missing


def static_root() -> Path:
    """static/ 目录单源（rfauto.ui 包位派生，editable 安装即仓内）。"""
    import rfauto.ui

    return Path(rfauto.ui.__file__).parent / "static"


# ═══════════════════════════ CDP 浏览器层（console error 断言）══════════════════════════

def split_known_errors(bucket: dict[str, list[str]],
                       ) -> tuple[list[str], list[str]]:
    """error 归桶 → (硬错, 已知空态豁免)——豁免按 KNOWN_EMPTY_STATE_NET
    前缀精确命中（空 id fetch 形态 /api/sparams/?...；带 id 的正常 fetch
    不含该前缀不误豁免）。纯函数可单测。"""
    errs: list[str] = []
    known: list[str] = []
    for e in (bucket["console"] + bucket["exceptions"] + bucket["log"]
              + bucket["net"]):
        if any(p in e for p in KNOWN_EMPTY_STATE_NET):
            known.append(e)
        else:
            errs.append(e)
    return errs, known


class _CDPUnavailable(RuntimeError):
    """CDP 层不可用（缺浏览器/缺 websockets/调试口未起）——降级信号。"""


def _chrome_launch_cmd(exe: str, cdp_port: int, profile_dir: str) -> list[str]:
    return [
        exe, "--headless=new",
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-gpu", "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",  # 新版 headless 软件 WebGL 许可
        "--hide-scrollbars", "--window-size=1600,900",
        "--disable-features=Translate",
        "about:blank",
    ]


def _record_cdp_event(bucket: dict[str, list[str]], event: dict[str, Any]) -> None:
    """CDP 事件 → 归桶（favicon 豁免；SPA 导航 abort 不计——false 正例源）。"""
    method = event.get("method", "")
    params = event.get("params") or {}
    if method == "Runtime.consoleAPICalled":
        if params.get("type") == "error":
            texts = [str(a.get("value")) if "value" in a
                     else str(a.get("description") or "")
                     for a in params.get("args") or []]
            bucket["console"].append(" ".join(t for t in texts if t)[:500])
    elif method == "Runtime.exceptionThrown":
        det = params.get("exceptionDetails") or {}
        bucket["exceptions"].append(
            str(det.get("text", ""))[:300] + " " + str(
                (det.get("exception") or {}).get("description", ""))[:300])
    elif method == "Log.entryAdded":
        entry = params.get("entry") or {}
        if entry.get("level") == "error":
            url = str(entry.get("url") or "")
            text = str(entry.get("text") or "")
            if "favicon" not in url and "favicon" not in text:
                bucket["log"].append(f"{text[:200]} {url[:200]}".strip())
    elif method == "Network.responseReceived":
        resp = params.get("response") or {}
        status = resp.get("status") or 0
        url = str(resp.get("url") or "")
        if status >= 400 and "favicon" not in url:
            bucket["net"].append(f"{status} {url[:200]}")


class _CDPConn:
    """单页 target 的 CDP 连接（id-future 命令面+事件队列）。"""

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._mid = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        self._reader = asyncio.ensure_future(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
                else:
                    self.events.put_nowait(msg)
        except Exception:  # 连接关停（杀浏览器）——队列消费方超时兜底
            pass

    async def cmd(self, method: str, params: dict[str, Any] | None = None,
                  timeout: float = 15.0) -> dict[str, Any]:
        self._mid += 1
        mid = self._mid
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send(json.dumps(
            {"id": mid, "method": method, "params": params or {}}))
        resp = await asyncio.wait_for(fut, timeout)
        if resp.get("error"):
            raise RuntimeError(f"{method}: {resp['error']}")
        return resp.get("result") or {}

    async def drain(self, timeout_s: float | None = None,
                    predicate: Callable[[dict[str, Any]], bool] | None = None,
                    bucket: dict[str, list[str]] | None = None) -> bool:
        """消费事件队列：归桶 + 等谓词命中；超时返回 False。"""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (timeout_s if timeout_s else 0.0)
        while True:
            budget = 0.0 if not timeout_s else max(0.0, deadline - loop.time())
            if not timeout_s and self.events.empty():
                return False
            try:
                event = await asyncio.wait_for(self.events.get(),
                                               timeout=budget or 0.001)
            except asyncio.TimeoutError:
                return False
            if bucket is not None:
                _record_cdp_event(bucket, event)
            if predicate is not None and predicate(event):
                return True

    async def evaluate(self, expression: str) -> Any:
        res = await self.cmd("Runtime.evaluate", {
            "expression": expression, "returnByValue": True,
            "awaitPromise": False,
        })
        return (res.get("result") or {}).get("value")

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()


async def _cdp_wait_devtools(port: int, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            status, body, _ = http_raw(
                f"http://127.0.0.1:{port}/json/version", timeout=2.0)
            if status == 200 and body:
                return
        except (OSError, urllib.error.URLError, ValueError):
            pass
        await asyncio.sleep(0.25)
    raise _CDPUnavailable(f"DevTools 调试口 {port} 30s 未就绪")


async def _cdp_open_tab(port: int) -> dict[str, Any]:
    """新建 target（Chrome 111+ 要 PUT；旧版回退 GET）。"""
    for method in ("PUT", "GET"):
        try:
            status, body, _ = http_raw(
                f"http://127.0.0.1:{port}/json/new?about:blank",
                method=method, timeout=5.0)
            if status == 200:
                return json.loads(body.decode("utf-8", errors="replace"))
        except (OSError, urllib.error.URLError, ValueError) as exc:
            last = str(exc)
    raise _CDPUnavailable(f"/json/new 建目标失败: {last}")


async def _cdp_visit(conn: _CDPConn, base_url: str, name: str, suffix: str,
                     active_expected: str, idx: int,
                     view_timeout_s: float) -> list[dict[str, Any]]:
    """单视图真实导航：load→nav 激活→h2.page→console error 四断言。

    name=检查项键（裸视图与深链 visit 不撞 id）；suffix=hash 路由段；
    active_expected=期望激活的 nav data-v（深链=宿主页）。
    """
    url = f"{base_url}/?__smoke={idx:02d}#/{suffix}"
    bucket: dict[str, list[str]] = {
        "console": [], "exceptions": [], "log": [], "net": []}
    checks: list[dict[str, Any]] = []
    t0 = time.monotonic()

    await conn.drain(timeout_s=None, bucket=bucket)  # 清上个视图尾巴（非阻塞）
    await conn.cmd("Page.navigate", {"url": url}, timeout=view_timeout_s)
    loaded = await conn.drain(
        timeout_s=view_timeout_s, bucket=bucket,
        predicate=lambda ev: ev.get("method") == "Page.loadEventFired")
    checks.append(check(
        f"view.{name}.load", "view_cdp", url, loaded,
        "loadEventFired" if loaded else f"{view_timeout_s:.0f}s 内未触发 load",
        dur_ms=(time.monotonic() - t0) * 1000))

    active = ""
    deadline = time.monotonic() + view_timeout_s
    while time.monotonic() < deadline:
        try:
            active = str(await conn.evaluate(
                "document.querySelector('aside nav button.active')"
                "?.dataset.v || ''"))
        except (RuntimeError, asyncio.TimeoutError):
            active = ""
        if active == active_expected:
            break
        await asyncio.sleep(0.25)
        await conn.drain(timeout_s=0.0, bucket=bucket)
    checks.append(check(
        f"view.{name}.active", "view_cdp", f"#/{suffix}",
        active == active_expected, f"active nav data-v={active!r}",
        dur_ms=(time.monotonic() - t0) * 1000))

    h2 = False
    # UI-R12（2026-10-14）：视图改懒加载后渲染异步化（动态 import 在
    # load 事件后才拉模块）——h2.page 断言从单发查询改就绪轮询（与上方
    # active 轮询同 deadline；先到先停，静态视图首查即中行为不变）。
    deadline = time.monotonic() + view_timeout_s
    while time.monotonic() < deadline:
        try:
            h2 = bool(await conn.evaluate(
                f"!!document.querySelector('#view-{active_expected} h2.page')"))
        except (RuntimeError, asyncio.TimeoutError):
            h2 = False
        if h2:
            break
        await asyncio.sleep(0.25)
        await conn.drain(timeout_s=0.0, bucket=bucket)
    checks.append(check(
        f"view.{name}.content", "view_cdp", f"#view-{active_expected} h2.page",
        h2, "h2.page 已渲染" if h2 else "h2.page 缺失",
        dur_ms=(time.monotonic() - t0) * 1000))

    await asyncio.sleep(SETTLE_S)
    await conn.drain(timeout_s=0.0, bucket=bucket)  # 静置窗尾巴全收
    errs, known = split_known_errors(bucket)
    if errs:
        detail = "; ".join(errs)[:800]
    elif known:
        detail = (f"零 error（豁免已知空态项 {len(known)} 条——"
                  f"{' | '.join(known)[:400]}）")
    else:
        detail = "零 error"
    checks.append(check(
        f"view.{name}.console", "view_cdp", url, not errs, detail,
        dur_ms=(time.monotonic() - t0) * 1000))
    return checks


async def _cdp_sweep_async(base_url: str, visits: list[tuple[str, str, str]],
                           browser_exe: str, profile_dir: str,
                           cdp_port: int,
                           view_timeout_s: float) -> list[dict[str, Any]]:
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = await asyncio.create_subprocess_exec(
        *_chrome_launch_cmd(browser_exe, cdp_port, profile_dir),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        **popen_kwargs)
    try:
        await _cdp_wait_devtools(cdp_port)
        target = await _cdp_open_tab(cdp_port)
        ws_url = target.get("webSocketDebuggerUrl")
        if not ws_url:
            raise _CDPUnavailable("target 无 webSocketDebuggerUrl")
        try:
            from websockets.asyncio.client import connect as ws_connect
        except ImportError:  # 旧版 websockets 兼容
            from websockets import connect as ws_connect  # type: ignore[no-redef]
        async with ws_connect(ws_url, max_size=2 ** 23, open_timeout=10,
                              close_timeout=5) as ws:
            conn = _CDPConn(ws)
            await conn.start()
            for method in ("Page.enable", "Runtime.enable", "Log.enable",
                           "Network.enable"):
                await conn.cmd(method, timeout=10.0)
            results: list[dict[str, Any]] = []
            for idx, (name, suffix, active) in enumerate(visits):
                results.extend(await _cdp_visit(
                    conn, base_url, name, suffix, active, idx,
                    view_timeout_s))
            return results
    finally:
        kill_tree(proc.pid)


def cdp_sweep(base_url: str, visits: list[tuple[str, str, str]],
              browser_exe: str, view_timeout_s: float,
              cdp_port_base: int = CDP_PORT_BASE,
              ) -> tuple[list[dict[str, Any]] | None, str]:
    """CDP 视图巡检入口。visits=(检查键, hash 段, 期望激活 nav) 三元组。

    返回 (checks, "") 或 (None, 降级原因)——降级只属"层建不起来"（缺
    浏览器/缺 websockets/调试口未起）；单视图超时是真 fail 不降级。
    """
    try:
        import websockets  # noqa: F401
    except ImportError:
        return None, "websockets 未安装（venv 缺依赖）"
    profile = tempfile.mkdtemp(prefix="rfauto_ui_smoke_chrome_")
    cdp_port = pick_free_port(cdp_port_base)
    try:
        checks = asyncio.run(_cdp_sweep_async(
            base_url, visits, browser_exe, profile, cdp_port, view_timeout_s))
        return checks, ""
    except _CDPUnavailable as exc:
        return None, str(exc)
    except (OSError, RuntimeError, asyncio.TimeoutError) as exc:
        return None, f"CDP 会话失败: {exc}"
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def node_syntax_checks(static_root_dir: Path,
                       node_exe: str = "node") -> list[dict[str, Any]]:
    """降级层：node --check 全静态 JS 语法兜底（无浏览器时的 console 面）。"""
    checks: list[dict[str, Any]] = []
    for rel in enumerate_js_modules(static_root_dir):
        path = static_root_dir / rel
        try:
            proc = subprocess.run(
                [node_exe, "--check", str(path)], capture_output=True,
                timeout=20, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ok = proc.returncode == 0
            detail = "syntax ok" if ok else proc.stderr.decode(
                "utf-8", errors="replace")[:300]
        except (OSError, subprocess.TimeoutExpired) as exc:
            ok, detail = False, f"node --check 执行失败: {exc}"
        checks.append(check(f"js.syntax.{rel}", "js_syntax", rel, ok, detail))
    return checks


# ═══════════════════════════ 巡检面（HTTP 层）══════════════════════════

def sweep_http_views(base_url: str, views: list[str]) -> list[dict[str, Any]]:
    """HTTP 层逐视图 content 断言：data-v 注册在服务端壳内（26/26）。"""
    status, raw, _ = http_raw(base_url + "/")
    html = raw.decode("utf-8", errors="replace")
    ok = status == 200 and bool(html)
    checks = [check(
        "views.shell", "view_http", "/", ok,
        f"GET / → {status}，{len(html)}B")]
    served = extract_view_routes(html)
    checks.append(check(
        "views.enumerated", "view_http", "data-v 注册表",
        len(served) == len(views) and len(served) > 0,
        f"服务端枚举 {len(served)} 视图：{' '.join(served)}"))
    for name in views:
        present = f'data-v="{name}"' in html
        checks.append(check(
            f"view.http.{name}", "view_http", f'data-v="{name}"', present,
            "注册在服务端壳内" if present else "服务端壳缺该视图注册"))
    return checks


def sweep_api_strict(base_url: str) -> list[dict[str, Any]]:
    """strict 面：200+ok True+键型+gallery 卡片计数自洽（cwd 无关）。"""
    checks: list[dict[str, Any]] = []
    for path, key, typ in STRICT_API:
        t0 = time.monotonic()
        status, body = http_json(base_url + path)
        ok_env, env_detail = _json_ok_envelope(body)
        type_ok = isinstance(body, dict) and isinstance(body.get(key), typ)
        detail = f"HTTP {status}; {env_detail}; {key} type={type(body.get(key)).__name__}"
        ok = status == 200 and ok_env and type_ok
        checks.append(check(f"api.strict.{path}", "api_strict", path, ok,
                            detail, dur_ms=(time.monotonic() - t0) * 1000))
    _, gallery = http_json(base_url + "/api/gallery")
    if isinstance(gallery, dict):
        n_tpl = gallery.get("n_templates")
        cards = gallery.get("cards") or []
        consistent = isinstance(n_tpl, int) and n_tpl > 0 and len(cards) == n_tpl
        checks.append(check(
            "api.gallery.counts", "api_strict", "/api/gallery", consistent,
            f"n_templates={n_tpl} cards={len(cards)}（计数自洽）"))
    return checks


def sweep_api_generic(base_url: str) -> list[dict[str, Any]]:
    """generic 面：200+JSON dict+信封形态纪律——22 端点普查（ok=False 的
    业务空态信封合法，见 _json_envelope_wellformed）。"""
    checks: list[dict[str, Any]] = []
    for path in GENERIC_API:
        t0 = time.monotonic()
        status, body = http_json(base_url + path)
        ok_env, env_detail = _json_envelope_wellformed(body)
        ok = status == 200 and ok_env
        checks.append(check(f"api.generic.{path}", "api_generic", path, ok,
                            f"HTTP {status}; {env_detail}",
                            dur_ms=(time.monotonic() - t0) * 1000))
    return checks


def sweep_api_400(base_url: str) -> list[dict[str, Any]]:
    """坏参数 400 信封（A8-D ParamError 面）+200+ok=False 失败信封抽查。"""
    checks: list[dict[str, Any]] = []
    for method, path, body in BAD_PARAM_400:
        t0 = time.monotonic()
        status, parsed = http_json(base_url + path, method=method, body=body)
        ok_env, env_detail = _fail_envelope(parsed)
        ok = status == 400 and ok_env
        checks.append(check(
            f"api.400.{path.split('?')[0]}.{method.lower()}", "api_400",
            f"{method} {path}", ok, f"HTTP {status}; {env_detail}",
            dur_ms=(time.monotonic() - t0) * 1000))
    for path in FAIL_ENVELOPE_200:
        status, parsed = http_json(base_url + path)
        ok_env, env_detail = _fail_envelope(parsed)
        ok = status == 200 and ok_env
        checks.append(check(
            f"api.failenv.{path.split('?')[0]}", "api_400", path, ok,
            f"HTTP {status}; {env_detail}"))
    return checks


def _fail_envelope(body: Any) -> tuple[bool, str]:
    """失败信封判据：dict+ok is False+errors 非空 list[str]。"""
    if not isinstance(body, dict):
        return False, f"非 JSON 对象（type={type(body).__name__}）"
    if body.get("ok") is not False:
        return False, f"预期 ok=False，实际 ok={body.get('ok')!r}"
    errs = body.get("errors")
    if not (isinstance(errs, list) and errs
            and all(isinstance(e, str) for e in errs)):
        return False, f"errors 非法（AU-2 收敛语义须 list[str]）：{errs!r}"
    return True, f"errors={errs[:2]}"


def sweep_kernel_roundtrip(base_url: str) -> list[dict[str, Any]]:
    """确定性内核往返：vswr_convert（VSWR=2 → |Γ|=1/3 精确、回损 9.5424）。"""
    t0 = time.monotonic()
    body = json.dumps(
        {"name": "vswr_convert", "params": {"vswr": _KERNEL_VSWR}}).encode()
    status, parsed = http_json(base_url + "/api/calculators/run",
                               method="POST", body=body)
    result = (parsed or {}).get("result") or {}
    gamma = result.get("gamma_mag")
    rl = result.get("return_loss_db")
    ok = (status == 200 and (parsed or {}).get("ok") is True
          and isinstance(gamma, (int, float))
          and abs(float(gamma) - _KERNEL_GAMMA) <= _KERNEL_GAMMA_TOL
          and isinstance(rl, (int, float))
          and abs(float(rl) - _KERNEL_RL_DB) <= _KERNEL_RL_TOL)
    detail = (
        f"HTTP {status}; gamma_mag={gamma}（期望 1/3={_KERNEL_GAMMA:.6f}）；"
        f"return_loss_db={rl}（期望 {_KERNEL_RL_DB}）")
    return [check("kernel.vswr_convert", "kernel",
                  "POST /api/calculators/run", ok, detail,
                  dur_ms=(time.monotonic() - t0) * 1000)]


def sweep_static(base_url: str, root: Path) -> list[dict[str, Any]]:
    """静态资源：磁盘枚举全部 *.js → 200+text/javascript（ESM 硬要求）。"""
    checks: list[dict[str, Any]] = []
    for rel in enumerate_js_modules(root):
        t0 = time.monotonic()
        url = f"{base_url}/static/{rel}"
        status, _, headers = http_raw(url)
        ctype = (headers.get("content-type") or "").strip()
        ok = status == 200 and "text/javascript" in ctype
        checks.append(check(
            f"static.{rel}", "static", url, ok,
            f"HTTP {status}; Content-Type={ctype!r}（ESM 须 text/javascript）",
            dur_ms=(time.monotonic() - t0) * 1000))
    return checks


def sweep_degradation(base_url: str, log_path: Path) -> list[dict[str, Any]]:
    """降级路径面（仅 spawn 模式）：临时 cwd 下 runs 挂载缺席+空清单+提示。"""
    checks: list[dict[str, Any]] = []
    status, _, _ = http_raw(base_url + "/runs/")
    checks.append(check(
        "degraded.runs_mount_absent", "degraded", "/runs/",
        status == 404, f"GET /runs/ → {status}（期望 404：临时 cwd 无 runs/，"
        "静态挂载按 R2-B-05 降级缺席）"))
    status, body = http_json(base_url + "/api/runs")
    runs = (body or {}).get("runs")
    checks.append(check(
        "degraded.runs_empty", "degraded", "/api/runs",
        status == 200 and isinstance(body, dict) and body.get("ok") is True
        and runs == [],
        f"GET /api/runs → {status}，runs={runs!r}（期望 200+空清单："
        "API 面不受降级影响）"))
    hint = "runs 目录不存在" in log_tail(log_path, n_lines=200)
    checks.append(check(
        "degraded.stderr_hint", "degraded", str(log_path.name), hint,
        "服务器日志含降级提示" if hint else "日志未见「runs 目录不存在」提示"))
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
        description="UI e2e 冒烟门（aurora_d UI-R7）：起服+五面巡检+verdict")
    ap.add_argument("--port", type=int, default=None,
                    help=f"服务端口（缺省从 {DEFAULT_PORT_BASE} 起动态选空闲）")
    ap.add_argument("--base-url", default=None,
                    help="附着既有服务（跳过起服与降级面——降级断言仅 spawn 模式成立）")
    ap.add_argument("--timeout", type=float, default=DEFAULT_READY_TIMEOUT_S,
                    help=f"就绪探针预算秒（缺省 {DEFAULT_READY_TIMEOUT_S:.0f}）")
    ap.add_argument("--visit-timeout", type=float,
                    default=DEFAULT_VISIT_TIMEOUT_S,
                    help=f"单视图 CDP 预算秒（缺省 {DEFAULT_VISIT_TIMEOUT_S:.0f}）")
    ap.add_argument("--out", default=None, help="verdict JSON 落盘路径")
    ap.add_argument("--json", action="store_true",
                    help="stdout 输出 verdict JSON（人类摘要转 stderr）")
    ap.add_argument("--no-browser", action="store_true",
                    help="跳过 CDP 层（强制 node --check 语法兜底层）")
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
    console_layer = "none"
    browser_exe = None if args.no_browser else find_browser()
    base_url = args.base_url
    spawned = base_url is None
    log_path = Path(args.log) if args.log else Path(tempfile.gettempdir()) / (
        f"rfauto_ui_smoke_{int(time.time())}.log")

    # ① 路由表程序化枚举（防漂移：巡检目标逐条对照 server 路由表）
    try:
        api_routes = enumerate_server_api_routes()
        targets = ([p for p, _, _ in STRICT_API] + GENERIC_API
                   + [p for _, p, _ in BAD_PARAM_400] + FAIL_ENVELOPE_200)
        missing = validate_targets_against_routes(targets, api_routes)
        checks.append(check(
            "routes.table", "server", f"{len(api_routes)} 条 /api/* 路由",
            not missing, "巡检目标全部命中路由表" if not missing
            else f"路由表缺（脚本绿但路由已漂移的对面）：{missing}"))
    except Exception as exc:  # 反射失败=fail-loud（UI 装配面坏了）
        checks.append(check("routes.table", "server", "create_ui_app()", False,
                            f"路由表反射失败: {exc}"))
        api_routes = []

    # ② 起服（spawn 模式：临时 cwd+备用端口动态选+分离进程+就绪探针）
    if spawned:
        port = args.port if args.port else pick_free_port(DEFAULT_PORT_BASE)
        tmp_cwd = tempfile.mkdtemp(prefix="rfauto_ui_smoke_cwd_")
        cmd = build_server_cmd(sys.executable, port)
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        say(f"[smoke] 起服：{' '.join(cmd)}（cwd={tmp_cwd}）")
        log_fh = None
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
                base_url + "/", args.timeout,
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
                            "attach 模式（降级面不适用，跳过）"))

    # ③ 五面巡检（服务活着才巡）
    cdp_checks: list[dict[str, Any]] | None = None
    cdp_note = ""
    if base_url:
        try:
            html = http_raw(base_url + "/")[1].decode("utf-8", errors="replace")
            views = extract_view_routes(html)
        except (OSError, urllib.error.URLError, ValueError):
            views = []
        if not views:
            checks.append(check("views.enumerated", "view_http", "GET /", False,
                                "视图路由枚举为空（壳不可达或缺 data-v）"))
        else:
            checks.extend(sweep_http_views(base_url, views))
        checks.extend(sweep_api_strict(base_url))
        checks.extend(sweep_api_generic(base_url))
        checks.extend(sweep_api_400(base_url))
        checks.extend(sweep_kernel_roundtrip(base_url))
        checks.extend(sweep_static(base_url, static_root()))
        if spawned and log_path.exists():
            checks.extend(sweep_degradation(base_url, log_path))

        # ⑤ console error：能力自选（CDP → node --check → skipped）
        # visits=(检查键, hash 段, 期望激活 nav)：26 裸视图+1 深链
        # （#/tools/vswr_convert——uir2 深链面制度化）。
        visits = [(v, v, v) for v in views]
        if views:
            visits.append(("tools.deeplink", "tools/vswr_convert", "tools"))
        if browser_exe and views:
            cdp_checks, cdp_note = cdp_sweep(
                base_url, visits, browser_exe, args.visit_timeout)
            if cdp_checks is not None:
                console_layer = "cdp"
                checks.extend(cdp_checks)
            else:
                say(f"[smoke] CDP 层不可用（{cdp_note}）→ node --check 兜底")
        if cdp_checks is None:
            if shutil.which("node"):
                console_layer = "node-syntax"
                checks.extend(node_syntax_checks(static_root()))
            else:
                console_layer = "none"
                checks.append(check(
                    "console.layer", "js_syntax", "CDP/node 能力", True,
                    "skipped：无浏览器且无 node——console 断言层不可用"
                    "（如实降级，不判绿冒充）", ))

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
        shutil.rmtree(tmp_cwd, ignore_errors=True)

    meta: dict[str, Any] = {
        "wall_s": round(time.monotonic() - t_start, 2),
        "ts_start": ts_start,
        "console_layer": console_layer,
        "browser": {"exe": browser_exe} if browser_exe else None,
        "server": {
            "mode": "spawned" if spawned else "attached",
            "base_url": base_url,
            "cwd": tmp_cwd,
            "pid": proc.pid if proc is not None else None,
            "log": str(log_path),
        },
        "cdp_note": cdp_note,
    }
    verdict = assemble_verdict(meta, checks)
    n_fail = verdict["summary"]["fail"]
    say(f"[smoke] 完成：{verdict['summary']['pass']}/{len(checks)} pass，"
        f"{n_fail} fail（console_layer={console_layer}，"
        f"wall={verdict['wall_s']}s）")

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
        print(f"ui_e2e_smoke: rc={verdict['summary']['rc']} "
              f"({verdict['summary']['pass']}/{len(checks)} pass)")
    return int(verdict["summary"]["rc"])


if __name__ == "__main__":
    sys.exit(main())
