"""架构批 UI-R3 席位回归钉：统一实时事件流（event_bus + events + 接入钩子）。

对象（本席新增/改动面）：
1. src/rfauto/ui/routes/event_bus.py——统一事件信封
   {seq, ts, kind, domain, payload} 与单源广播/订阅 helper（seq 单调轴/
   去重窗/环形缓冲背压/订阅注册表）；
2. src/rfauto/ui/routes/events.py——统一 SSE 端点 ×3（/api/events/stream
   全域 + tune/campaign 单域）+ campaign tick 检测器 + runs 镜像；
3. src/rfauto/ui/routes/tune.py——状态转移发布钩子 + 逐 trial 探针
   （service start_tune 既有 on_trial 挂点，服务层零改动）；
4. src/rfauto/ui/routes/runs.py——P-1 桥逐事件懒镜像（帧零改动）；
5. src/rfauto/ui/server.py——3 条新路由装配。

钉面（任务书三钉 + 兼容钉）：
- 统一信封形态钉：键集恰为 EVENT_ENVELOPE_KEYS、seq 单调、SSE 帧
  event=<kind>/id=<seq>/data=<信封>；
- tune/campaign 事件推送钉：POST /api/tune/start → tune_started/
  tune_completed 帧；campaign 计划文件改写 → 队列 tick 推 stage_changed/
  launch_completed 帧。流式断言走 ``_drive_sse``（ASGI 直驱）——
  starlette 1.6 TestClient transport 全量缓冲响应（portal.call 等 app
  收束才返回），长驻 SSE 经它读必然挂死；ASGI 直驱是 TestClient
  streaming 的等价驱动，且覆盖真实 http.disconnect 断开路径；
- 断开清理无泄漏钉：生成器 aclose（局部路径）与 http.disconnect（服务端
  全链路）→ 订阅注册表归零；订阅数上限 → 503 信封；
- 向后兼容钉：runs 镜像信封 payload 携带旧事件字段原样（event_type/
  event_id/run_id 不消失）、既有桥帧字面不变、/api/tune/status、
  /api/campaign_queue、/api/tune/start 响应键集与既有单数 error 形态
  全部保持；
- UI-R9 修复钉（uir8 审查 P1-A/P1-B）：控制帧（hello/resync）省略 id 行
  ——EventSource 不清客户端 Last-Event-ID 游标；tune 状态转移去重键
  run_seq 化——同秒"启动→即时失败→重试"两次 tune_failed 均出帧；
- UI-R10 修复钉（uir8 审查 P2）：campaign 扫描共享 ticker——N 连接同
  TTL 窗口复用同一快照代际（扫描计数 ≤1），TTL 过期必重扫保新鲜度，
  跨测试经 autouse 清缓存隔离。

不读网络、不启动真实服务器（TestClient 走 ASGI 传输）；总线经
monkeypatch 换隔离实例，跨测试零串味。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

# ────────────────────────── 共享小工具 ──────────────────────────


@pytest.fixture()
def fresh_bus(monkeypatch):
    """隔离总线单例（端点/发布钩子经 bus() 现读模块属性——换血零缓存面）。"""
    import rfauto.ui.routes.event_bus as event_bus

    eb = event_bus.EventBus()
    monkeypatch.setattr(event_bus, "_BUS", eb)
    return eb


@pytest.fixture()
def ui_app():
    """Starlette 应用实例（TestClient 与 ASGI 直驱共用同一装配面）。"""
    from rfauto.ui.server import create_ui_app

    return create_ui_app(include_runs_mount=False)


@pytest.fixture()
def client(tmp_path, monkeypatch, fresh_bus, ui_app):
    """TestClient（runs 挂载缺席本面）+ cwd 隔离 + _TUNE_STATE 还原。

    注：starlette 1.6 的 TestClient transport 全量缓冲响应（portal.call 等
    app 收束才返回）——长驻 SSE 流不可经它增量读；流式断言走本文件
    ``_drive_sse``（ASGI 直驱等价驱动，并覆盖真实 http.disconnect 断开路径）。
    """
    from rfauto.ui.routes import tune as tune_routes

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    saved = dict(tune_routes._TUNE_STATE)
    try:
        from starlette.testclient import TestClient

        yield TestClient(ui_app)
    finally:
        tune_routes._TUNE_STATE.clear()
        tune_routes._TUNE_STATE.update(saved)


@pytest.fixture(autouse=True)
def _fresh_campaign_scan_cache():
    """campaign 共享扫描缓存逐测试清空（UI-R10 共享 ticker——防跨测试串味）。"""
    from rfauto.ui.routes import events as events_routes

    events_routes._reset_campaign_scan_cache()
    yield
    events_routes._reset_campaign_scan_cache()


def _parse_sse_block(block: str) -> dict | None:
    frame: dict = {}
    data_lines = []
    for line in block.splitlines():
        if line.startswith("event:"):
            frame["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("id:"):
            frame["id"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
    if not frame and not data_lines:
        return None  # ping 注释等非帧块
    frame["data_json"] = json.loads("\n".join(data_lines)) if data_lines else {}
    return frame


async def _drive_sse_async(app, path, *, query: str = "",
                           headers: dict | None = None, stop,
                           hook=None, hook_when=None, timeout_s: float = 10.0):
    """ASGI 直驱 SSE 流（TestClient streaming 在 starlette 1.6 不可用的
    等价驱动，且更真）：app 任务化 + send 增量收帧；收束走真实
    ``http.disconnect`` 路径——sse-starlette 取消流任务 → 生成器 finally
    （断开清理的服务端全链路，不止 aclose 局部）。"""
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "root_path": "",
        "query_string": query.encode(),
        "headers": [(k.lower().encode(), v.encode())
                    for k, v in (headers or {}).items()],
        "client": ("testclient", 50000), "server": ("testserver", 80),
    }
    info: dict = {"status": None, "content_type": None, "chunks": []}
    disc = asyncio.Event()

    async def receive():
        await disc.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            info["status"] = message["status"]
            for k, v in message.get("headers", []):
                if k.decode().lower() == "content-type":
                    info["content_type"] = v.decode()
        else:
            info["chunks"].append(
                message.get("body", b"").decode("utf-8", "replace"))

    task = asyncio.create_task(app(scope, receive, send))
    frames: list[dict] = []
    consumed = 0
    hooked = False
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        await asyncio.sleep(0.02)
        if task.done():
            break
        text = "".join(info["chunks"]).replace("\r\n", "\n")
        while True:
            end = text.find("\n\n", consumed)
            if end < 0:
                break
            frame = _parse_sse_block(text[consumed:end])
            consumed = end + 2
            if frame:
                frames.append(frame)
        if hook_when is not None and not hooked and hook_when(frames):
            hook()
            hooked = True
        if stop(frames):
            break
    disc.set()  # 客户端断开 → 服务端取消路径
    try:
        await asyncio.wait_for(asyncio.shield(task), 5.0)
    except asyncio.TimeoutError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise AssertionError(
            "SSE 流未响应 http.disconnect（断开清理失守）") from None
    return frames, info


def _drive_sse(app, path, **kw):
    return asyncio.run(_drive_sse_async(app, path, **kw))


def _parse_sse_text(text: str) -> list[dict]:
    """整段 SSE 文本 → 帧清单（自终止流的 client.get 路径用）。"""
    frames: list[dict] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        frame = _parse_sse_block(block)
        if frame is not None:
            frames.append(frame)
    return frames


def _write_events_jsonl(run_dir: Path, events: list[dict]) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8")


def _write_plan(camp_dir: Path, stages: list[tuple[str, str]],
                model: str = "wilkinson_pd") -> None:
    """原子写战役计划（读面 tick 在他线程——os.replace 免半行竞态）。"""
    import os

    camp_dir.mkdir(parents=True, exist_ok=True)
    plan = {"model": model, "stages": [
        {"stage": s, "status": st, "adapter": "fake"} for s, st in stages]}
    tmp = camp_dir / "campaign.plan.json.tmp"
    tmp.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, camp_dir / "campaign.plan.json")


# ────────────────────────── 1. 统一信封形态钉 ──────────────────────────


class TestEnvelopeShape:
    def test_envelope_keys_constant(self):
        from rfauto.ui.routes.event_bus import EVENT_ENVELOPE_KEYS

        assert EVENT_ENVELOPE_KEYS == ("seq", "ts", "kind", "domain", "payload")

    def test_envelope_exact_shape_and_types(self, fresh_bus):
        env = fresh_bus.publish("trial_new", "tune", {"number": 1})
        assert env is not None
        assert set(env) == set(("seq", "ts", "kind", "domain", "payload"))
        assert isinstance(env["seq"], int)
        assert isinstance(env["ts"], float)
        assert env["kind"] == "trial_new"
        assert env["domain"] == "tune"
        assert env["payload"] == {"number": 1}

    def test_seq_monotonic_and_since_order(self, fresh_bus):
        for i in range(3):
            fresh_bus.publish(f"k{i}", "campaign", {"i": i})
        events, truncated = fresh_bus.since(0)
        assert [e["seq"] for e in events] == [1, 2, 3]
        assert truncated is False
        assert [e["payload"]["i"] for e in events] == [0, 1, 2]
        # 游标增量语义：since(seq1) 只回 2、3
        events2, _ = fresh_bus.since(events[0]["seq"])
        assert [e["seq"] for e in events2] == [2, 3]
        assert fresh_bus.head_seq() == 3

    def test_publish_argument_validation(self, fresh_bus):
        import rfauto.ui.routes.event_bus as event_bus

        with pytest.raises(ValueError):
            event_bus.EventBus().publish("", "tune", {})
        with pytest.raises(ValueError):
            event_bus.EventBus().publish("k", "", {})
        with pytest.raises(ValueError):
            event_bus.EventBus().publish("k", "tune", ["not", "dict"])

    def test_dedupe_window_exactly_once(self, fresh_bus):
        first = fresh_bus.publish("stage_changed", "campaign", {"to": "done"},
                                  dedupe_key="stage:p:s1:done")
        again = fresh_bus.publish("stage_changed", "campaign", {"to": "done"},
                                  dedupe_key="stage:p:s1:done")
        assert first is not None and again is None  # 去重窗内恰好一次
        other = fresh_bus.publish("stage_changed", "campaign", {"to": "done"},
                                  dedupe_key="stage:p:s2:done")
        assert other is not None  # 不同键不受影响

    def test_try_publish_best_effort_never_raises(self, fresh_bus, monkeypatch):
        import rfauto.ui.routes.event_bus as event_bus

        def _boom(*a, **kw):
            raise RuntimeError("推送面故障")

        monkeypatch.setattr(event_bus.EventBus, "publish", _boom)
        assert event_bus.try_publish("k", "tune", {}) is None  # #105：吞异常

    def test_sse_frame_shape_single_source(self, fresh_bus):
        import rfauto.ui.routes.event_bus as event_bus

        env = fresh_bus.publish("tune_started", "tune", {})
        frame = event_bus.sse_frame(env)
        assert frame["event"] == "tune_started"
        assert frame["id"] == str(env["seq"])
        assert json.loads(frame["data"])["seq"] == env["seq"]
        ctrl = event_bus.control_frame("hello", {"cursor": 0})
        assert ctrl["event"] == "hello"
        assert json.loads(ctrl["data"])["domain"] == "system"
        # UI-R9 P1-A：控制帧省略 id 键（EventSource 不更新 lastEventId，
        # 客户端游标不被清回 0）；data 内信封形态仍完整。
        assert "id" not in ctrl
        assert set(json.loads(ctrl["data"])) == set(
            event_bus.EVENT_ENVELOPE_KEYS)


# ────────────────────────── 2. 背压（环形缓冲截断）钉 ──────────────────────────


class TestBackpressure:
    def test_ring_truncation_flag_and_resync_semantics(self):
        import rfauto.ui.routes.event_bus as event_bus

        eb = event_bus.EventBus(ring_size=4)
        for i in range(6):
            eb.publish(f"k{i}", "tune", {"i": i})
        # 游标 0 落后窗口（1、2 已淘汰）→ truncated，交 resync 整刷兜底
        events, truncated = eb.since(0)
        assert truncated is True
        assert [e["seq"] for e in events] == [3, 4, 5, 6]
        # 游标追平窗口左界 → 不截断
        events2, truncated2 = eb.since(2)
        assert truncated2 is False
        assert [e["seq"] for e in events2] == [3, 4, 5, 6]

    def test_subscription_cap_returns_none(self):
        import rfauto.ui.routes.event_bus as event_bus

        eb = event_bus.EventBus(max_subscribers=2)
        s1 = eb.subscribe(source="a")
        s2 = eb.subscribe(source="b")
        assert s1 is not None and s2 is not None
        assert eb.subscribe(source="c") is None  # 满员（端点转 503 信封）
        assert eb.unsubscribe(s1) is True
        assert eb.unsubscribe(s1) is False  # 幂等
        assert eb.subscribe(source="d") is not None  # 清理后空位回归


# ────────────────────────── 3. 断开清理无泄漏钉 ──────────────────────────


class TestDisconnectCleanup:
    def test_generator_aclose_unsubscribes_no_leak(self, fresh_bus):
        from rfauto.ui.routes.events import make_stream_generator

        sub = fresh_bus.subscribe(source="t")
        gen = make_stream_generator(fresh_bus, sub, domains=("tune",))

        async def _scenario():
            hello = await gen.__anext__()
            assert hello["event"] == "hello"
            await gen.aclose()  # = ASGI 客户端断开时对生成器的取消路径

        asyncio.run(_scenario())
        assert fresh_bus.subscriber_count() == 0  # finally 单点清理（防泄漏）

    def test_generator_replays_from_last_event_id(self, fresh_bus):
        from rfauto.ui.routes.events import make_stream_generator

        e1 = fresh_bus.publish("tune_started", "tune", {})
        e2 = fresh_bus.publish("tune_completed", "tune", {})
        sub = fresh_bus.subscribe(last_seq=e1["seq"])  # = Last-Event-ID 续传
        gen = make_stream_generator(fresh_bus, sub, domains=("tune",))

        async def _scenario():
            out = []
            for _ in range(2):
                out.append(await gen.__anext__())
            await gen.aclose()
            return out

        frames = asyncio.run(_scenario())
        assert [f["event"] for f in frames] == ["hello", "tune_completed"]
        assert frames[1]["id"] == str(e2["seq"])
        assert json.loads(frames[1]["data"])["seq"] == e2["seq"]
        assert fresh_bus.subscriber_count() == 0

    def test_generator_resync_frame_on_truncation(self):
        import rfauto.ui.routes.event_bus as event_bus
        from rfauto.ui.routes.events import make_stream_generator

        eb = event_bus.EventBus(ring_size=2)
        for i in range(5):
            eb.publish(f"k{i}", "tune", {})
        sub = eb.subscribe(last_seq=0)
        gen = make_stream_generator(eb, sub, domains=("tune",))

        async def _scenario():
            out = []
            for _ in range(2):
                out.append(await gen.__anext__())
            await gen.aclose()
            return out

        frames = asyncio.run(_scenario())
        assert frames[0]["event"] == "hello"
        assert frames[1]["event"] == "resync"  # 背压截断 → 整刷控制帧
        # UI-R9 P1-A：两枚控制帧都省略 id 键（生成器直出形态）
        assert "id" not in frames[0] and "id" not in frames[1]

    def test_generator_runs_only_terminal_end_and_cleanup(self, fresh_bus,
                                                          tmp_path,
                                                          monkeypatch):
        from rfauto.ui.routes.events import make_stream_generator

        monkeypatch.chdir(tmp_path)  # RUNS_DIR 是相对路径（cwd 口径）
        _write_events_jsonl(tmp_path / "runs" / "R", [
            {"event_type": "run_started", "event_id": "e1", "run_id": "R"},
            {"event_type": "trial_completed", "event_id": "e2", "run_id": "R"},
            {"event_type": "run_completed", "event_id": "e3", "run_id": "R"},
        ])
        sub = fresh_bus.subscribe(source="mirror")
        gen = make_stream_generator(fresh_bus, sub, domains=("runs",),
                                    run_id="R", tick_s=0.01)

        async def _scenario():
            out = []
            async for frame in gen:
                out.append(frame)
            return out

        frames = asyncio.run(_scenario())  # 自终止：terminal end 帧收束
        assert [f["event"] for f in frames] == [
            "hello", "run_started", "trial_completed", "run_completed", "end"]
        assert json.loads(frames[-1]["data"])["terminal"] is True
        assert fresh_bus.subscriber_count() == 0  # 收束路径同样清理

    def test_generator_runs_only_missing_stream_end_exists_false(self,
                                                                 fresh_bus,
                                                                 tmp_path,
                                                                 monkeypatch):
        from rfauto.ui.routes.events import make_stream_generator

        monkeypatch.chdir(tmp_path)
        sub = fresh_bus.subscribe(source="mirror")
        gen = make_stream_generator(fresh_bus, sub, domains=("runs",),
                                    run_id="NOPE", tick_s=0.01)

        async def _scenario():
            out = []
            async for frame in gen:
                out.append(frame)
            return out

        frames = asyncio.run(_scenario())
        assert [f["event"] for f in frames] == ["hello", "end"]
        assert json.loads(frames[-1]["data"])["exists"] is False


# ────────────────────────── 4. campaign tick 检测器钉 ──────────────────────────


class TestCampaignDetector:
    def test_baseline_announces_inventory_as_campaign_new(self):
        from rfauto.ui.routes.events import detect_campaign_changes

        cur = {"p1": {"model": "m", "verdict": "",
                      "stages": {"doe": "pending"}}}
        out = detect_campaign_changes(None, cur)  # prev=None=首测基线公告
        assert [kind for kind, _, _ in out] == ["campaign_new"]
        assert out[0][1]["campaign"] == "p1"
        assert out[0][2] == "cnew:p1"

    def test_stage_transition_and_launch_completed(self):
        from rfauto.ui.routes.events import detect_campaign_changes

        prev = {"p": {"model": "m", "verdict": "",
                      "stages": {"doe": "pending", "opt": "pending"}}}
        cur = {"p": {"model": "m", "verdict": "",
                     "stages": {"doe": "done", "opt": "failed"}}}
        out = detect_campaign_changes(prev, cur)
        kinds = [kind for kind, _, _ in out]
        assert kinds == ["stage_changed", "launch_completed", "stage_changed"]
        by_kind = {(kind, payload["stage"]): payload for kind, payload, _ in out}
        assert by_kind[("stage_changed", "doe")]["from"] == "pending"
        assert by_kind[("stage_changed", "doe")]["to"] == "done"
        assert by_kind[("launch_completed", "doe")]["to"] == "done"
        assert by_kind[("stage_changed", "opt")]["to"] == "failed"
        # 去重键逐事件可区分（多连接恰好一次语义的载体）
        keys = [key for _, _, key in out]
        assert len(set(keys)) == len(keys)

    def test_no_change_no_events(self):
        from rfauto.ui.routes.events import detect_campaign_changes

        snap = {"p": {"model": "m", "verdict": "",
                      "stages": {"doe": "pending"}}}
        assert detect_campaign_changes(snap, snap) == []

    def test_snapshot_reads_plans_and_survives_bad_root(self, tmp_path,
                                                        monkeypatch):
        from rfauto.ui.routes.events import campaign_snapshot

        monkeypatch.chdir(tmp_path)
        _write_plan(tmp_path / "runs" / "campA", [("doe", "pending")])
        snap = campaign_snapshot("runs")
        assert len(snap) == 1
        (path, info), = snap.items()
        assert path.endswith("campaign.plan.json")
        assert info["stages"] == {"doe": "pending"}
        assert info["model"] == "wilkinson_pd"
        # 坏根/缺目录 → 空快照（观测面 #105：宁缺勿炸流）
        assert campaign_snapshot("no_such_root") == {}


class TestCampaignSharedTicker:
    """UI-R10 修复钉（uir8 审查 P2）：campaign 扫描共享 ticker。

    修复前 ``_campaign_tick`` 在每个流生成器循环内各扫一遍盘——N 连接 =
    N 次/秒全目录扫描（订阅上限 64 → 最坏 64 次/秒）。修复后同 root 同
    TTL 窗口至多扫一次（惰性单飞），连接数与扫描频次解耦。
    """

    def test_n_connections_share_one_snapshot_generation(
            self, fresh_bus, tmp_path, monkeypatch):
        # 钉（任务书口径）：monkeypatch 计数扫描次数——N 连接 × 1 tick 断言 ≤1
        from rfauto.ui.routes import events as events_routes

        _write_plan(tmp_path / "runs" / "campA", [("doe", "pending")])
        root = str(tmp_path / "runs")
        scans = {"n": 0}
        real_scan = events_routes.campaign_snapshot

        def _counting(r):
            scans["n"] += 1
            return real_scan(r)

        monkeypatch.setattr(events_routes, "campaign_snapshot", _counting)
        s1 = fresh_bus.subscribe(source="c1")
        s2 = fresh_bus.subscribe(source="c2")
        gen1 = events_routes.make_stream_generator(
            fresh_bus, s1, domains=("campaign",), root=root)
        gen2 = events_routes.make_stream_generator(
            fresh_bus, s2, domains=("campaign",), root=root)

        async def _scenario():
            hello1 = await gen1.__anext__()
            hello2 = await gen2.__anext__()
            tick1 = await gen1.__anext__()  # 首个 tick 扫盘（窗口内第 1 次）
            tick2 = await gen2.__anext__()  # 同窗第 2 连接复用同一快照代际
            await gen1.aclose()
            await gen2.aclose()
            return hello1, hello2, tick1, tick2

        frames = asyncio.run(_scenario())
        assert [f["event"] for f in frames[:2]] == ["hello", "hello"]
        assert scans["n"] == 1, scans  # 修复前=2；共享后窗口内恒 ≤1
        assert frames[2]["event"] == "campaign_new"
        # 同一代际：第 2 连接公告同一信封（其差分发布被去重窗吞掉、帧来自
        # 总线回放——共享快照不破坏恰好一次语义，也不丢帧；生成器直驱=
        # 原始帧，data 是 JSON 字符串）
        assert frames[3]["event"] == "campaign_new"
        assert json.loads(frames[3]["data"]) == json.loads(frames[2]["data"])
        assert fresh_bus.subscriber_count() == 0  # aclose 清理不回归

    def test_window_reuse_returns_same_generation_object(self, tmp_path):
        from rfauto.ui.routes import events as events_routes

        _write_plan(tmp_path / "runs" / "campA", [("doe", "pending")])
        root = str(tmp_path / "runs")
        a = events_routes.shared_campaign_snapshot(root)
        b = events_routes.shared_campaign_snapshot(root)
        assert a is b  # 同窗同代际=同一快照对象（非重扫副本）

    def test_ttl_window_expiry_forces_fresh_scan(self, tmp_path, monkeypatch):
        # 新鲜度边界：TTL 过期必重扫（同生成器相邻 tick 间隔 ≥ tick_s =
        # TTL，故单连接变化检测时延与修复前等价——此钉防"缓存成陈旧面"）
        from rfauto.ui.routes import events as events_routes

        _write_plan(tmp_path / "runs" / "campA", [("doe", "pending")])
        root = str(tmp_path / "runs")
        scans = {"n": 0}
        real_scan = events_routes.campaign_snapshot

        def _counting(r):
            scans["n"] += 1
            return real_scan(r)

        monkeypatch.setattr(events_routes, "campaign_snapshot", _counting)
        monkeypatch.setattr(events_routes, "_CAMPAIGN_SCAN_TTL_S", 0.0)
        first = events_routes.shared_campaign_snapshot(root)
        second = events_routes.shared_campaign_snapshot(root)
        assert scans["n"] == 2  # TTL=0 → 窗口恒过期，逐调用重扫
        assert first == second and first is not second  # 内容同、代际异

    def test_cache_bounded_and_root_keyed(self, tmp_path, monkeypatch):
        # ``?root=`` 接受任意路径（uir8 P2-3 登记面）——缓存有界防任意根撑爆；
        # 键=abspath 归一（等价写法归并到同一代际）
        import os

        from rfauto.ui.routes import events as events_routes

        monkeypatch.setattr(events_routes, "_CAMPAIGN_SCAN_CACHE_MAX_ROOTS", 2)
        for i in range(3):
            (tmp_path / f"r{i}").mkdir()
            events_routes.shared_campaign_snapshot(str(tmp_path / f"r{i}"))
        assert len(events_routes._scan_cache) == 2  # LRU 淘汰最旧
        assert os.path.abspath(str(tmp_path / "r2")) in (
            events_routes._scan_cache)
        a = events_routes.shared_campaign_snapshot("./nope/../nope")
        b = events_routes.shared_campaign_snapshot("nope")
        assert a is b  # abspath 归一并键（坏根空快照同样入窗）


class TestRunsMirrorTick:
    def test_mirror_envelope_keeps_legacy_fields_intact(self, fresh_bus,
                                                        tmp_path,
                                                        monkeypatch):
        from rfauto.ui.routes.events import _runs_mirror_tick

        monkeypatch.chdir(tmp_path)
        legacy = [
            {"event_type": "run_started", "event_id": "e1", "run_id": "R",
             "message": "hello"},
            {"event_type": "run_completed", "event_id": "e2", "run_id": "R"},
        ]
        _write_events_jsonl(tmp_path / "runs" / "R", legacy)
        offset, exists, terminal, mirrored = _runs_mirror_tick("R", 0)
        assert exists is True and terminal is True
        assert [m["kind"] for m in mirrored] == ["run_started", "run_completed"]
        # 向后兼容钉：payload=旧事件 dict 原样，旧字段一个不消失
        assert mirrored[0]["payload"]["event_type"] == "run_started"
        assert mirrored[0]["payload"]["event_id"] == "e1"
        assert mirrored[0]["payload"]["run_id"] == "R"
        assert mirrored[0]["payload"]["message"] == "hello"
        assert mirrored[0]["domain"] == "runs"
        assert offset > 0
        # 偏移增量：续读零新事件（不重放）
        _, _, terminal2, mirrored2 = _runs_mirror_tick("R", offset)
        assert terminal2 is False and mirrored2 == []

    def test_mirror_missing_stream_and_read_failure_degrade(self, tmp_path,
                                                            monkeypatch):
        from rfauto.ui.routes import events as events_routes

        monkeypatch.chdir(tmp_path)
        offset, exists, terminal, mirrored = (
            events_routes._runs_mirror_tick("NOPE", 0))
        assert (offset, exists, terminal, mirrored) == (0, False, False, [])


# ────────────────────────── 5. tune 发布钩子钉 ──────────────────────────


class TestTunePublishHooks:
    def test_trial_probe_publishes_trial_new(self, fresh_bus):
        from rfauto.ui.routes import tune as tune_routes

        class _Study:
            study_name = "stu"

        class _Trial:
            number = 3
            value = 0.5
            state = "COMPLETE"

        tune_routes._tune_trial_probe(_Study(), _Trial())
        events, _ = fresh_bus.since(0)
        assert [e["kind"] for e in events] == ["trial_new"]
        payload = events[0]["payload"]
        assert payload["study"] == "stu"
        assert payload["number"] == 3
        assert payload["value"] == 0.5
        assert "COMPLETE" in payload["state"]

    def test_publish_hook_swallows_bus_failure(self, monkeypatch):
        # #105：观测面故障不影响调参主路径（钩子不外抛）
        import rfauto.ui.routes.event_bus as event_bus
        from rfauto.ui.routes import tune as tune_routes

        def _boom(*a, **kw):
            raise RuntimeError("bus down")

        monkeypatch.setattr(event_bus, "try_publish", _boom)
        tune_routes._publish_tune_event("tune_started", {})  # 不抛即过


# ────────────────────────── 6. 端点钉（TestClient streaming）──────────────────────────


class TestTuneStreamEndpoint:
    def test_start_endpoint_pushes_transitions_end_to_end(self, client,
                                                          ui_app, fresh_bus,
                                                          monkeypatch):
        from rfauto.ui.routes import tune as tune_routes

        calls: dict = {}

        def _stub(path, *, adapter_name="fake", max_trials=30,
                  sampler="tpe", on_trial=None, **kw):
            calls["on_trial"] = on_trial
            return {"ok": True, "best_value": 1.0}
        monkeypatch.setattr("rfauto.service.api.start_tune", _stub)

        r = client.post("/api/tune/start", json={"path": "p.yaml"})
        assert r.status_code == 200 and r.json()["ok"] is True
        deadline = time.time() + 5.0
        while tune_routes._TUNE_STATE["running"] and time.time() < deadline:
            time.sleep(0.02)
        assert tune_routes._TUNE_STATE["running"] is False  # 后台线程已收尾
        assert calls["on_trial"] is tune_routes._tune_trial_probe  # 探针已挂

        frames, info = _drive_sse(
            ui_app, "/api/tune/events/stream", stop=lambda fs: len(fs) >= 3)
        assert info["status"] == 200
        assert info["content_type"].startswith("text/event-stream")
        kinds = [f["event"] for f in frames]
        assert kinds == ["hello", "tune_started", "tune_completed"]
        started = frames[1]["data_json"]
        assert set(started) == {"seq", "ts", "kind", "domain", "payload"}
        assert started["domain"] == "tune"
        assert frames[1]["id"] == str(started["seq"])
        completed = frames[2]["data_json"]
        assert completed["payload"]["ok"] is True
        assert completed["payload"]["started_at"] == (
            started["payload"]["started_at"])
        # 真实 http.disconnect 断开 → 订阅注册表归零（无泄漏，服务端全链路）
        assert fresh_bus.subscriber_count() == 0

    def test_last_event_id_header_resumes(self, client, ui_app, fresh_bus):
        e1 = fresh_bus.publish("tune_started", "tune", {})
        fresh_bus.publish("tune_completed", "tune", {})
        frames, _ = _drive_sse(
            ui_app, "/api/events/stream", query="domain=tune",
            headers={"Last-Event-ID": str(e1["seq"])},
            stop=lambda fs: len(fs) >= 2)
        assert [f["event"] for f in frames] == ["hello", "tune_completed"]
        assert fresh_bus.subscriber_count() == 0

    def test_hello_first_frame_has_no_id_line(self, client, ui_app):
        # UI-R9 P1-A（HTTP 面）：经 sse-starlette 编码后 hello 帧无 ``id:``
        # 行——浏览器 lastEventId 不被清 0，Last-Event-ID 续传语义保持；
        # 重连起点引导走 hello payload.cursor（=head seq）。
        frames, info = _drive_sse(
            ui_app, "/api/tune/events/stream", stop=lambda fs: len(fs) >= 1)
        assert info["status"] == 200
        assert frames[0]["event"] == "hello"
        assert "id" not in frames[0]
        assert isinstance(frames[0]["data_json"]["payload"]["cursor"], int)

    def test_same_second_double_failure_both_emit_frames(self, client,
                                                         ui_app, fresh_bus,
                                                         monkeypatch):
        # UI-R9 P1-B：去重键混入进程内单调启动计数 run_seq——同秒"启动→
        # 即时失败→重试"是两次独立状态转移，均出帧。时钟钉死同一秒：
        # 旧键形态 tune_failed:{started_at} 必撞去重窗吞第二次（此钉必红）。
        import datetime as _dt_mod

        from rfauto.ui.routes import tune as tune_routes

        class _FixedDT(_dt_mod.datetime):
            @classmethod
            def now(cls, *a, **kw):
                return cls(2026, 10, 14, 12, 0, 0)

        monkeypatch.setattr(_dt_mod, "datetime", _FixedDT)

        def _boom(*a, **kw):
            raise RuntimeError("bad path")

        monkeypatch.setattr("rfauto.service.api.start_tune", _boom)
        for _ in range(2):
            r = client.post("/api/tune/start", json={"path": "p.yaml"})
            assert r.status_code == 200 and r.json()["ok"] is True
            deadline = time.time() + 5.0
            while tune_routes._TUNE_STATE["running"] and time.time() < deadline:
                time.sleep(0.01)
        frames, _ = _drive_sse(
            ui_app, "/api/tune/events/stream",
            stop=lambda fs: sum(1 for f in fs
                                if f["event"] == "tune_failed") >= 2)
        failed = [f for f in frames if f["event"] == "tune_failed"]
        assert len(failed) == 2  # 同秒两次失败都出帧（run_seq 键不撞窗）
        # 前提自证：两次 started_at 确为同一秒（时钟钉死，旧键必撞窗）
        assert (failed[0]["data_json"]["payload"]["started_at"]
                == failed[1]["data_json"]["payload"]["started_at"]
                == "2026-10-14T12:00:00")
        seqs = [f["data_json"]["seq"] for f in failed]
        assert seqs[0] < seqs[1]  # 两个独立信封，非去重吞没

    def test_busy_start_legacy_singular_error_unchanged(self, client,
                                                        monkeypatch):
        from rfauto.ui.routes import tune as tune_routes

        monkeypatch.setitem(tune_routes._TUNE_STATE, "running", True)
        r = client.post("/api/tune/start", json={"path": "p.yaml"})
        # 旧形态钉（envelope 契约 §3 遗留族）：单数 error，前端读 .error
        assert r.json() == {"ok": False, "error": "已有调参任务在运行"}

    def test_tune_status_polling_keys_unchanged(self, client):
        # 兼容层钉：既有轮询端点旧字段不消失
        body = client.get("/api/tune/status").json()
        assert body["ok"] is True
        assert {"running", "result", "error", "started_at"} <= set(body)


class TestCampaignStreamEndpoint:
    def test_queue_tick_pushes_transitions_live(self, client, ui_app,
                                                fresh_bus, tmp_path):
        camp = tmp_path / "runs" / "campA"
        _write_plan(camp, [("doe", "pending"), ("opt", "pending")])
        frames, info = _drive_sse(
            ui_app, "/api/campaign_queue/events/stream",
            stop=lambda fs: any(f["event"] == "launch_completed"
                                for f in fs),
            hook=lambda: _write_plan(camp, [("doe", "done"),
                                            ("opt", "failed")]),
            hook_when=lambda fs: any(f["event"] == "campaign_new"
                                     for f in fs))
        assert info["status"] == 200
        kinds = [f["event"] for f in frames]
        assert kinds[0] == "hello"
        assert "campaign_new" in kinds
        assert "stage_changed" in kinds and "launch_completed" in kinds
        cnew = next(f["data_json"] for f in frames
                    if f["event"] == "campaign_new")
        assert cnew["domain"] == "campaign"
        assert cnew["payload"]["campaign"].endswith("campaign.plan.json")
        assert cnew["payload"]["model"] == "wilkinson_pd"
        by_stage = {f["data_json"]["payload"]["stage"]: f["data_json"]["payload"]
                    for f in frames if f["event"] == "stage_changed"}
        assert by_stage["doe"]["from"] == "pending"
        assert by_stage["doe"]["to"] == "done"
        assert by_stage["opt"]["to"] == "failed"
        launch = next(f["data_json"]["payload"] for f in frames
                      if f["event"] == "launch_completed")
        assert launch["stage"] == "doe" and launch["to"] == "done"
        # 队列 tick 真实断开 → 注册表归零
        assert fresh_bus.subscriber_count() == 0

    def test_campaign_queue_polling_keys_unchanged(self, client):
        # 兼容层钉：既有队列轮询端点旧字段不消失
        body = client.get("/api/campaign_queue").json()
        assert body["ok"] is True
        assert {"root", "machine", "campaigns", "n_campaigns"} <= set(body)
        assert body["n_campaigns"] == 0

    def test_bad_root_param_still_serves_stream(self, client, ui_app):
        # 计划根不存在 → tick 降级空快照，流照常（hello 可达）
        frames, info = _drive_sse(
            ui_app, "/api/campaign_queue/events/stream", query="root=nope",
            stop=lambda fs: len(fs) >= 1)
        assert info["status"] == 200
        assert frames[0]["event"] == "hello"


class TestUnifiedStreamEndpoint:
    def test_runs_mirror_mode_backcompat_frames(self, client, tmp_path):
        legacy = [
            {"event_type": "run_started", "event_id": "e1", "run_id": "R9"},
            {"event_type": "trial_completed", "event_id": "e2", "run_id": "R9"},
            {"event_type": "run_completed", "event_id": "e3", "run_id": "R9"},
        ]
        _write_events_jsonl(tmp_path / "runs" / "R9", legacy)
        r = client.get("/api/events/stream?run_id=R9&domain=runs")
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        frames = _parse_sse_text(r.text)
        assert [f["event"] for f in frames] == [
            "hello", "run_started", "trial_completed", "run_completed", "end"]
        # 信封向后兼容：event=旧 event_type、payload=旧事件 dict 原样
        for frame, want in zip(frames[1:4], legacy, strict=True):
            data = frame["data_json"]
            assert set(data) == {"seq", "ts", "kind", "domain", "payload"}
            assert data["kind"] == want["event_type"] == frame["event"]
            assert data["domain"] == "runs"
            assert data["payload"]["event_type"] == want["event_type"]
            assert data["payload"]["event_id"] == want["event_id"]
            assert data["payload"]["run_id"] == want["run_id"]
            assert frame["id"] == str(data["seq"])
        assert frames[-1]["data_json"]["terminal"] is True

    def test_invalid_domain_400_envelope(self, client):
        r = client.get("/api/events/stream?domain=bogus")
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False and body["errors"]

    def test_invalid_last_event_id_400_envelope(self, client):
        r = client.get("/api/events/stream", headers={"Last-Event-ID": "abc"})
        assert r.status_code == 400
        assert r.json()["ok"] is False

    def test_subscriber_cap_503_envelope(self, client, fresh_bus, monkeypatch):
        import rfauto.ui.routes.event_bus as event_bus

        monkeypatch.setattr(event_bus, "_BUS",
                            event_bus.EventBus(max_subscribers=0))
        r = client.get("/api/tune/events/stream")
        assert r.status_code == 503
        body = r.json()
        assert body["ok"] is False and body["errors"]

    def test_sse_starlette_missing_503_envelope(self, client, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _no_sse(name, *a, **kw):
            if name.startswith("sse_starlette"):
                raise ImportError("no sse")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", _no_sse)
        r = client.get("/api/events/stream")
        assert r.status_code == 503
        assert r.json()["ok"] is False


class TestLegacyBridgeFramesUnchanged:
    def test_bridge_frames_literal_unchanged_with_mirror_active(
            self, client, tmp_path):
        # 懒镜像钩子插入桥生成器后，帧字面零漂移（test_ui_sse 桥契约的同席复述）
        _write_events_jsonl(tmp_path / "runs" / "R7", [
            {"event_type": "run_started", "event_id": "e1", "run_id": "R7"},
            {"event_type": "trial_completed", "event_id": "e2", "run_id": "R7"},
            {"event_type": "run_completed", "event_id": "e3", "run_id": "R7"},
        ])
        r = client.get("/api/runs/R7/events/stream")
        assert r.status_code == 200
        assert "event: run_started" in r.text
        assert "event: trial_completed" in r.text
        assert "event: run_completed" in r.text
        assert "id: e2" in r.text  # 旧 id 帧=旧 event_id（非统一 seq）
        blocks = [b for b in r.text.replace("\r\n", "\n").split("\n\n")
                  if b.strip()]
        assert "event: end" in blocks[-1]
        end_data = next(ln.split(":", 1)[1] for ln in blocks[-1].splitlines()
                        if ln.startswith("data:"))
        assert json.loads(end_data)["terminal"] is True
