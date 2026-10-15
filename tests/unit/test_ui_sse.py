"""aurora72 A6-A 席位回归钉：UI SSE 实时面（R6 审计 F-1）。

对象：src/rfauto/ui/static/pages.js（SSE 消费块：订阅/回退链/生命周期 +
sseStreamUrl/sseSubscribedTypes/sseFrameAction/sseEndMark/sseShouldGiveUp/
ssePollSuppressed 纯函数）与 src/rfauto/ui/server.py（既有 P-1 桥端点
/api/runs/{run_id}/events/stream——本席零改动，帧契约测试钉住前端消费面
依赖的形态）。app.js/index.html/palette.js/plotcard.js 归他席——只读。

解决的 R6 证据（F-1：宣称与行为不符——诚实性问题）：
1. SSE 端点已存在而前端 EventSource 零消费、campaign 页文案宣称"实时
   进度监听 SSE 流自动刷新"为不实陈述——本批接通渐进增强消费（tune/campaign
   两面）并把文案改为真实行为描述（含空流/不可用回退口径）；
2. 生命周期：离页（showPage 单源）与标签页隐藏（visibilitychange）close，
   恢复重开；终态 end 帧收束不复活（W2-B 终态停同款纪律）；
3. 回退链：SSE onopen 让位轮询（守卫跳过 fetch，定时器保留——setInterval
   计数不变）、原生连接错误即翻 live 轮询接管、连续 _SSE_MAX_ERRORS 次
   未恢复 close 放弃——渐进增强零硬依赖。

三层（与 test_ui_tools_page / test_ui_lifecycle / test_ui_routing 同惯例）：
1. **源码钉（免 node）**：订阅面/守卫/生命周期/回退链/文案真实性。
2. **跨席计数钉复述**（任务书清单；先红=本批扰动生命周期/图表不变量）。
3. **行为钉（node 在才跑，否则诚实 skip）**：帧分派/URL 构造/end 分型/
   回退判定纯函数实测 + pages.js 真 ESM import（结构改动语法门）。
4. **端点帧契约（TestClient，端点零改动的消费面契约钉）**：空流 end 帧
   exists=false / 事件帧 event+id+data / 终态 end 帧 terminal=true。

不依赖 runs/ 存量、不读网络、不启动服务器（TestClient 走 ASGI 传输）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")
# aurora_d UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_SRC = _pages_union_text()



def _body(func_sig: str) -> str:
    """取顶层函数体（起于 function 声明行，止于首个列 0 收括号）。"""
    m = re.search(func_sig + r" \{(.*?)\n\}", _SRC, re.S)
    assert m, f"函数体缺失: {func_sig}"
    return m.group(1)


# ────────────────────────── 1. 源码钉 ──────────────────────────

class TestSseConsumerPins:
    """F-1：EventSource 消费装配面（订阅面唯一、渐进增强、幂等换订）。"""

    def test_eventsource_single_entry_with_support_guard(self):
        # 唯一连接构造点在 _sseOpen（生命周期单源）；缺席环境全链静默跳过
        assert _SRC.count("new window.EventSource(") == 1
        body = _body(r"function _sseSupported\(\)")
        assert 'typeof window !== "undefined"' in body
        assert 'typeof window.EventSource === "function"' in body

    def test_subscription_faces_tune_and_campaign(self):
        # 只接最有价值两面（任务书口径）：tune=trial 推送、campaign=选 run 进度
        assert '_sseSubscribe("tune", d.run_id, tuneRefresh, "tune");' in _SRC
        assert '_sseSubscribe("campaign", runId, loadDash, "campaign");' in _SRC

    def test_subscribe_idempotent_and_done_empty_guards(self):
        body = _body(r"function _sseSubscribe\(name, runId, refresh, view\)")
        assert "!_sseSupported() || !runId" in body  # 渐进增强：无 EventSource/无 run 跳过
        # 幂等门抽纯函数 sseSubscribeBlocked（A6 P1-4 起含放弃态；node 行为钉
        # 实测）——存活/终态/空流/放弃态同会话跳过；换订先收束旧流
        assert "sseSubscribeBlocked(_SSE[name], runId, refresh)" in body
        assert "_sseClose(name);" in body
        gbody = _body(r"export function sseSubscribeBlocked\(cur, runId, refresh\)")
        assert "cur.runId === runId && cur.refresh === refresh" in gbody
        assert "cur.es || cur.done || cur.empty || cur.gaveUp" in gbody

    def test_url_single_source_encoded(self):
        body = _body(r"function _sseOpen\(name, st\)")
        assert "sseStreamUrl(st.runId)" in body  # URL 单源（encodeURIComponent 内置）

    def test_poll_suppression_guard_in_polltune(self):
        # 轮询让位守卫：定时器保留、回调跳过 fetch（setInterval 计数不变口径）
        body = _body(r"async function pollTune\(\)")
        assert 'if (!_pollVisible("tune")) return;' in body  # P2-13 既有守卫保持
        assert "if (ssePollSuppressed(_SSE.tune)) return;" in body  # A6-A 让位守卫
        assert "await tuneRefresh();" in body  # 拉取体抽出（轮询/SSE 共用）

    def test_refresh_body_shared_by_poll_and_sse(self):
        # SSE kick 与轮询共用幂等整页刷新（tuneRefresh）——含终态停既有逻辑
        body = _body(r"async function tuneRefresh\(\)")
        assert 'await T.api("/api/tune/status");' in body
        assert '_pollStop("tune", true)' in body  # 终态停保持（W2-B 口径）


class TestSseFallbackChain:
    """回退链：让位→兜底→放弃，全程零硬依赖。"""

    def test_max_errors_and_give_up_call(self):
        assert "const _SSE_MAX_ERRORS = 3;" in _SRC
        body = _body(r"function _sseOpen\(name, st\)")
        assert "sseShouldGiveUp(st.errors + 1, _SSE_MAX_ERRORS)" in body
        assert "st.live = false;" in body  # 原生错误即翻 live：轮询立即接管兜底

    def test_error_frame_vs_native_error_discriminated(self):
        # 服务端 error 帧（MessageEvent 有 data）→ close+末次刷新回退；
        # 原生连接错误（plain Event 无 data）→ 计数/兜底链
        body = _body(r"function _sseOpen\(name, st\)")
        assert 'if (e && typeof e.data === "string") {' in body
        assert body.count('addEventListener("error"') == 1  # 单监听双形态分派
        assert body.count('addEventListener("end"') == 1  # end 控制帧专用监听

    def test_onopen_resets_errors_and_flips_live(self):
        body = _body(r"function _sseOpen\(name, st\)")
        assert "es.onopen = () => { st.live = true; st.errors = 0; };" in body
        assert "st.done = false;" in body  # 重开清终态标记
        assert "st.empty = false;" in body  # 重开清空流标记

    def test_kick_coalesced_and_cleared_on_close(self):
        # 150ms 去抖合并刷新（重连重放/批量 trial 事件只刷一次）；close 清挂起
        body = _body(r"function _sseKick\(name, st\)")
        assert "setTimeout" in body
        cbody = _body(r"function _sseClose\(name\)")
        assert "clearTimeout(st.timer)" in cbody
        assert "st.es.close()" in cbody
        assert "st.live = false;" in cbody

    def test_end_frame_marks_and_final_refresh(self):
        body = _body(r"function _sseOpen\(name, st\)")
        assert "const mark = sseEndMark(e && e.data);" in body
        assert "st.done = mark.done;" in body
        assert "st.empty = mark.empty;" in body
        assert "if (refresh) refresh();" in body  # 末次刷新收尾


class TestSseGiveUpMarker:
    """A6 P1-4（review_aurora_next 审查）：放弃态标记——give-up 后轮询常驻
    但订阅不得复活（旧实现无标记：close 后 es/done/empty 全空 → 下个轮询
    tick 重启注定失败的 EventSource 且 onopen 归零 errors → 重连永动机）。"""

    def test_give_up_sets_marker_before_close(self):
        body = _body(r"function _sseOpen\(name, st\)")
        # 放弃路径（连续达限/浏览器已判死 CLOSED）先置 gaveUp 再 close
        assert "st.gaveUp = true;" in body
        assert "sseShouldGiveUp(st.errors + 1, _SSE_MAX_ERRORS)" in body
        assert "st.live = false;" in body

    def test_explicit_reopen_resets_marker(self):
        # 显式重连入口（_sseOpen）重置全部会话标记（含放弃态）
        body = _body(r"function _sseOpen\(name, st\)")
        assert "st.gaveUp = false;" in body
        assert "st.done = false;" in body
        assert "st.empty = false;" in body

    def test_resume_does_not_revive_given_up(self):
        # 恢复可见对放弃态不放行（放弃后轮询常驻；回页新闭包/换 runId 才是
        # 显式重连入口，经 _sseSubscribe 新建状态对象天然重置）
        rbody = _body(r"function _sseResume\(\)")
        assert "!st.gaveUp" in rbody
        sbody = _body(r"function _sseSubscribe\(name, runId, refresh, view\)")
        assert "sseSubscribeBlocked(_SSE[name], runId, refresh)" in sbody

    def test_state_table_documented_shape(self):
        assert ("const _SSE = {}; // name → { es, runId, view, live, errors, "
                "refresh, timer, done, empty, gaveUp }") in _SRC


class TestSseLifecycle:
    """生命周期：离页/隐藏 close，恢复重开，终态不复活（W2-B 语义复用）。"""

    def test_leave_page_hook_in_showpage_single_source(self):
        # showPage 单源写入 _activeView 处同点挂离页收束（不另开 hashchange 监听）
        assert "_activeView = v; // aurora36 W2-B：页面可见语义单源（轮询当前页守卫消费）" in _SRC
        assert "_sseLeavePage(v); // aurora72 A6-A：离页收束 SSE 连接（留档 runId，回页重订阅幂等）" in _SRC
        body = _body(r"function _sseLeavePage\(v\)")
        assert "if (_SSE[name].view !== v) _sseClose(name);" in body  # 切走才收束

    def test_visibility_binding_and_resume(self):
        assert "_bindVisibilitySSE(); // aurora72 A6-A" in _SRC  # initPages 装配一次
        body = _body(r"function _bindVisibilitySSE\(\)")
        assert "_sseVisBound" in body  # 幂等装配
        assert 'document.addEventListener("visibilitychange"' in body
        assert 'document.visibilityState === "hidden"' in body
        assert "for (const name of Object.keys(_SSE)) _sseClose(name);" in body  # 隐藏全收束
        assert "} else _sseResume();" in body  # 恢复可见重开
        rbody = _body(r"function _sseResume\(\)")
        assert "!st.es && !st.done" in rbody  # 终态不复活（W2-B 同款纪律）
        assert "st.empty = false;" in rbody  # 空流恢复=显式重试点
        assert "getActiveView() === st.view" in rbody  # 仅当前页复活（UI-R2：_activeView 经 context.js 访问器读）
        assert 'document.visibilityState !== "hidden"' in rbody

    def test_state_table_and_subscribed_types_shape(self):
        assert "const _SSE = {};" in _SRC  # name → 订阅态（es/runId/view/live/…）
        body = _body(r"function _sseSupported\(\)")
        assert body  # 支持判定独立成函数（node 缺席路径单点）
        # 订阅事件面与桥帧契约对齐（16 EventType 值；end/error 控制帧不在内）
        m = re.search(r"const _SSE_EVENT_TYPES = \[(.*?)\];", _SRC, re.S)
        assert m, "_SSE_EVENT_TYPES 缺失"
        types = re.findall(r'"([a-z_]+)"', m.group(1))
        assert len(types) == 16
        assert "end" not in types and "error" not in types
        assert {"run_completed", "run_failed", "trial_completed", "progress"} <= set(types)


class TestSseCopyHonesty:
    """F-1 文案修正：宣称=行为（含空流/不可用回退口径）。"""

    def test_false_claim_removed(self):
        # 旧不实陈述必须清零（R6 证据原文）
        assert "实时进度监听 SSE 流自动刷新" not in _SRC

    def test_campaign_help_truthful(self):
        assert "选中 run 后订阅 SSE 进度流" in _SRC
        assert "流不可用或该 run 无事件流（events.jsonl 缺席）时不会自动刷新" in _SRC
        assert "「刷新」按钮手动刷新" in _SRC  # 回退面如实

    def test_tune_panel_title_truthful(self):
        # tune 标题从"每 3 秒刷新"改为真实双形态（SSE 推送可达时推送，否则轮询）
        assert "SSE 进度流可达时推送刷新，否则每 3 秒轮询" in _SRC
        assert "每 3 秒刷新；收敛曲线" not in _SRC  # 旧口径清零


# ────────────────────────── 2. 跨席计数钉复述 ──────────────────────────

class TestCrossSeatPinsHold:
    """任务书跨席计数钉自查（与 test_ui_lifecycle/test_ui_routing 同源复述；
    先红=本批扰动生命周期/图表不变量）。"""

    def test_pages_js_counts_untouched(self):
        assert _SRC.count("T.plotCard(") == 12
        assert _SRC.count("window.echarts.init(") == 1  # 唯一入口=echartsInitCached
        assert _SRC.count('window.addEventListener("resize"') == 1
        assert _SRC.count("chartExportTools(el.parentElement, el, {") == 4
        assert _SRC.count("bindChartResize(el); // P0-5") == 4
        assert _SRC.count("bindChartResize(el); // aurora72 A3-A") == 1
        assert _SRC.count("disposeChartsIn(") == 4
        assert _SRC.count("setInterval(") == 2  # 仅轮询托管器两处（SSE 让位走回调守卫，不加定时器）
        assert _SRC.count("echartsInitCached(el)") == 6
        assert _SRC.count("plotCardCached(") == 3
        assert _SRC.count('window.addEventListener("hashchange"') == 1  # pages.js 单源（A4-C 口径）

    def test_campaign_cost_format_untouched(self):
        # 他席钉（test_w7c_ui_p2_sweep）：campaign cost 列 4dp 口径
        assert "fmtNum(row.cost, 4)" in _SRC


# ────────────────────────── 3. 行为钉（node 在才跑） ──────────────────────────

_NODE_GLUE = r"""
const p = await import('./pages.js');
const A = (cond, msg) => { if (!cond) throw new Error("assert: " + msg); };

// -- sseStreamUrl: same-origin relative + encodeURIComponent guard --
A(p.sseStreamUrl("20260101_000000_ab") === "/api/runs/20260101_000000_ab/events/stream", "plain id");
A(p.sseStreamUrl("a/b") === "/api/runs/a%2Fb/events/stream", "slash encoded");
A(p.sseStreamUrl("a b") === "/api/runs/a%20b/events/stream", "space encoded");
A(p.sseStreamUrl("跑") === "/api/runs/%E8%B7%91/events/stream", "unicode encoded");
A(p.sseStreamUrl(123) === "/api/runs/123/events/stream", "number coerced");

// -- sseSubscribedTypes: bridge value domain, control frames excluded --
const types = p.sseSubscribedTypes();
A(types.length === 16, "16 event types");
A(types.includes("trial_completed") && types.includes("run_completed"), "trial/terminal faces");
A(!types.includes("end") && !types.includes("error"), "control frames excluded");
types.push("__poison__");
A(p.sseSubscribedTypes().length === 16, "defensive copy");

// -- sseFrameAction: frame name -> action --
A(p.sseFrameAction("end") === "end", "end -> end");
A(p.sseFrameAction("error") === "fallback", "error -> fallback");
A(p.sseFrameAction("trial_completed") === "refresh", "named event -> refresh");
A(p.sseFrameAction("progress") === "refresh", "progress -> refresh");
A(p.sseFrameAction("__future_type__") === "refresh", "unknown -> refresh (forward compat)");
A(p.sseFrameAction("") === "refresh", "empty -> refresh");
A(p.sseFrameAction(null) === "refresh", "null -> refresh");

// -- sseEndMark: control frame -> close marking --
A(p.sseEndMark('{"terminal": true, "run_id": "r"}').done === true, "terminal -> done");
A(p.sseEndMark('{"terminal": true}').empty === false, "terminal not empty");
A(p.sseEndMark('{"exists": false, "run_id": "r"}').empty === true, "missing stream -> empty");
A(p.sseEndMark('{"exists": false}').done === false, "missing stream not done");
A(p.sseEndMark("{}").empty === true, "bare end -> empty (retryable)");
A(p.sseEndMark("not-json").empty === true, "broken json -> empty (retryable)");
A(p.sseEndMark(undefined).empty === true, "no data -> empty");

// -- sseShouldGiveUp: consecutive-failure policy --
A(p.sseShouldGiveUp(3, 3) === true, "at limit -> give up");
A(p.sseShouldGiveUp(2, 3) === false, "below limit -> keep");
A(p.sseShouldGiveUp(0, 3) === false, "fresh -> keep");
A(p.sseShouldGiveUp(5, 3) === true, "beyond limit -> give up");

// -- sseSubscribeBlocked: idempotent gate incl. gave-up marker (A6 P1-4) --
const sess = { runId: "r1", refresh: 1 };
A(p.sseSubscribeBlocked(null, "r1", 1) === false, "no state -> subscribe");
A(p.sseSubscribeBlocked({ ...sess, es: {} }, "r1", 1) === true, "alive -> blocked");
A(p.sseSubscribeBlocked({ ...sess, done: true }, "r1", 1) === true, "terminal -> blocked");
A(p.sseSubscribeBlocked({ ...sess, empty: true }, "r1", 1) === true, "empty -> blocked");
A(p.sseSubscribeBlocked({ ...sess, gaveUp: true }, "r1", 1) === true,
  "gave-up -> blocked (poll loop must not revive)");
A(p.sseSubscribeBlocked({ ...sess, gaveUp: true }, "r2", 1) === false,
  "gave-up + new runId -> explicit reconnect allowed");
A(p.sseSubscribeBlocked({ ...sess, gaveUp: true }, "r1", 2) === false,
  "gave-up + new closure (page rebuild) -> explicit reconnect allowed");
A(p.sseSubscribeBlocked({ runId: "r1", refresh: 1 }, "r1", 1) === false,
  "bare state (no marks) -> resubscribe");

// -- ssePollSuppressed: live-only yielding (timer kept) --
A(p.ssePollSuppressed({ live: true }) === true, "live -> suppressed");
A(p.ssePollSuppressed({ live: false }) === false, "not live -> poll");
A(p.ssePollSuppressed(null) === false, "no state -> poll");
A(p.ssePollSuppressed({}) === false, "blank state -> poll");

console.log("ok:sse");
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestNodeBehavioral:
    def test_sse_pure_functions_synthetic(self):
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e", _NODE_GLUE],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, cwd=str(_STATIC))
        assert r.returncode == 0, r.stderr[-2000:]
        assert "ok:sse" in r.stdout

    def test_pages_js_real_esm_import(self):
        # 结构改动（新增块+export 面）后的真 import 门（node --check 对 ESM 假绿）
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e",
             "await import('file:///" + str(_STATIC / "pages.js").replace("\\", "/") + "');"
             "console.log('esm-ok')"],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
        )
        assert r.returncode == 0, f"pages.js ESM 解析失败:\n{r.stderr[-1500:]}"
        assert "esm-ok" in r.stdout


# ────────────────────────── 4. 端点帧契约（端点零改动的消费面钉） ──────────────────────────

@pytest.fixture()
def sse_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app

    # runs/ 静态挂载缺席本面（StaticFiles 要求目录存在）；流端点不依赖它
    return TestClient(create_ui_app(include_runs_mount=False))


def _sse_blocks(text: str) -> list[str]:
    """SSE 帧切块（sse-starlette 用 \\r\\n 行尾——先归一化再按空行切帧）。"""
    return [b for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]


def _sse_assert_frames(text: str, frames: list[tuple[str, dict]]) -> None:
    """帧序断言：event 名与 data JSON 键值按序匹配（仅含命名事件块）。"""
    blocks = _sse_blocks(text)
    named = []
    for b in blocks:
        ev = None
        data_lines = []
        for line in b.splitlines():
            if line.startswith("event:"):
                ev = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        named.append((ev, "\n".join(data_lines)))
    got = [(e, d) for e, d in named if e is not None]
    assert len(got) == len(frames), f"帧数不符: {got}"
    for (want_ev, want_keys), (got_ev, got_data) in zip(frames, got, strict=True):
        assert got_ev == want_ev, f"事件名不符: {got_ev} != {want_ev}"
        d = json.loads(got_data) if got_data else {}
        for k, v in want_keys.items():
            assert d.get(k) == v, f"{want_ev} data[{k}]={d.get(k)!r} != {v!r}"


class TestStreamEndpointFrameContract:
    """P-1 桥帧契约（前端消费面依赖的形态；端点本席零改动——钉防漂移）。"""

    def test_missing_stream_yields_end_exists_false(self, sse_client, tmp_path):
        # runs/<id>/events.jsonl 缺席 → ok 空流语义：end 帧 exists=false（前端 empty 口径）
        r = sse_client.get("/api/runs/20990101_000000_nostream/events/stream")
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        _sse_assert_frames(r.text, [("end", {"exists": False,
                                             "run_id": "20990101_000000_nostream"})])

    def test_events_frames_then_terminal_end(self, sse_client, tmp_path):
        # 事件帧（event=<event_type> + id=<event_id> + data=事件 JSON）按序透传，
        # 终态（run_completed）后 end 帧 terminal=true 收束连接（流自然终止）。
        run_dir = tmp_path / "runs" / "20990101_010000_stream"
        run_dir.mkdir(parents=True)
        events = [
            {"event_type": "run_started", "event_id": "e1", "run_id": "20990101_010000_stream"},
            {"event_type": "trial_completed", "event_id": "e2", "run_id": "20990101_010000_stream"},
            {"event_type": "run_completed", "event_id": "e3", "run_id": "20990101_010000_stream"},
        ]
        (run_dir / "events.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
            encoding="utf-8")
        r = sse_client.get("/api/runs/20990101_010000_stream/events/stream")
        assert r.status_code == 200
        assert "event: run_started" in r.text
        assert "event: trial_completed" in r.text
        assert "event: run_completed" in r.text
        assert "id: e2" in r.text  # EventSource 续传语义的 id 帧
        _sse_assert_frames_tail(r.text)

    def test_route_registered_before_param_route(self, sse_client):
        # "stream" 不被 /api/runs/{run_id} 参数路由吃掉（starlette 注册序契约）
        r = sse_client.get("/api/runs/whatever/events/stream")
        assert r.status_code == 200  # 404 = 注册序漂移（diff 端点同款坑）


def _sse_assert_frames_tail(text: str) -> None:
    """末帧必须是 end 且 terminal=true（收束语义）。"""
    blocks = _sse_blocks(text)
    assert blocks, "空流"
    last = blocks[-1]
    assert "event: end" in last
    data = "\n".join(line.split(":", 1)[1].strip() for line in last.splitlines()
                     if line.startswith("data:"))
    assert json.loads(data)["terminal"] is True
