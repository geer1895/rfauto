"""aurora_e W2-S7 席位钉：U4 SSE 生产写入方（events.jsonl 生产侧接线 + e2e）。

背景（W0_recon §1.3 U4 定谳）：aurora_d UI-R3 落了统一 EventBus+3 SSE 端点
+读侧镜像（35 新钉），但生产编排器对 ``runs/<run_id>/events.jsonl`` 零写入
——core.events.EventBus 的 set_jsonl_sink 无任何生产调用方（grep 全仓定谳），
orchestration_wiring/agent_graph 的 emit 全部落空（无 sink 不落盘），
「写入→SSE 端点可读」端到端从未真实发生。

本席实施（写侧最小面）：
1. ``service/ui_service.append_run_event``——生产写入单条事件（core.events
   Event schema rfauto-event/1 与读侧同源；路径段守卫与 read_run_events
   同款；不走全局单例总线——进程级单 sink 会把多 run 事件互写错目录）；
2. ``routes/tune._write_tune_terminal_event``——调参完成态写 run_completed/
   run_failed 终态事件（有 run_id 才写；观测面 best-effort #105）。

钉面：
1. **append_run_event 单元钉**：合法写→读侧增量可见 + terminal 判定 +
   schema 统一信封；偏移增量两段写；坏 run_id（分隔符/穿越/空）拒；
   未识别 event_type 拒且零落盘；EventType 枚举入参收；OSError→error
   信封不抛（#105 观测面不阻业务主路径）；目录缺席零 mkdir 不虚构
   （run 目录由 run 链路负责，recipe_write_guard UI 面 AST 盘点口径）；
2. **e2e 钉（进程内全链路，#139 零网络）**：append_run_event →
   ui_service.read_run_events（偏移增量）→ routes.events._runs_mirror_tick
   （SSE 总线镜像）→ make_stream_generator 帧序列
   ``[hello, run_started, run_completed, end]``——生产写入方存在的意义即
   此链路真实可读；
3. **tune 路由接线钉**：monkeypatch start_tune（#139 钉通道禁真跑）返回带
   run_id 信封 → POST /api/tune/start → 终态事件落盘 run_completed；无
   run_id 信封零写入；start_tune 抛异常路径零写入不炸（tune_failed 既有
   总线语义不破坏）。

不读网络、不启动真实服务器（TestClient 走 ASGI 传输）；RUNS_DIR 相对
路径 cwd 口径与 test_ui_event_stream 既有钉同款（monkeypatch.chdir）。
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

# ────────────────────────── 共享 fixture ──────────────────────────


@pytest.fixture()
def fresh_bus(monkeypatch):
    """隔离总线单例（与 test_ui_event_stream 同款——端点/发布钩子经 bus()
    现读模块属性，换血零缓存面）。"""
    import rfauto.ui.routes.event_bus as event_bus

    eb = event_bus.EventBus()
    monkeypatch.setattr(event_bus, "_BUS", eb)
    return eb


@pytest.fixture()
def runs_root(tmp_path, monkeypatch):
    """cwd 隔离到 tmp（RUNS_DIR=Path("runs") 相对路径口径）→ 返回 runs 根。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path / "runs"


def _mk_run(runs_root, rid):
    """建 run 目录（生产不变量：run 链路已建目录后才写事件——append 面
    零 mkdir 与读侧零副作用对称，目录缺席=error 信封不虚构）。"""
    d = runs_root / rid
    d.mkdir(parents=True, exist_ok=True)
    return d


# ────────────────────────── 1. append_run_event 单元钉 ──────────────────────────


class TestAppendRunEvent:
    def test_write_then_read_increment_and_terminal(self, runs_root):
        from rfauto.service import ui_service

        _mk_run(runs_root, "R1")
        out = ui_service.append_run_event("R1", "run_completed",
                                          message="调参完成", data={"ok": True})
        assert out["ok"] is True
        assert out["run_id"] == "R1"
        assert out["event_id"]
        assert str(out["path"]).replace("\\", "/").endswith("R1/events.jsonl")
        snap = ui_service.read_run_events("R1")
        assert snap["ok"] is True and snap["exists"] is True
        assert [e["event_type"] for e in snap["events"]] == ["run_completed"]
        assert snap["terminal"] is True  # 终态判读（RUN_TERMINAL_EVENT_TYPES）
        ev = snap["events"][0]
        # 统一事件 schema（W3 飞行记录仪口径：写出侧带 schema 落盘）
        assert ev["schema"] == "rfauto-event/1"
        assert ev["run_id"] == "R1" and ev["data"] == {"ok": True}

    def test_two_writes_offset_increment(self, runs_root):
        from rfauto.service import ui_service

        _mk_run(runs_root, "R1")
        assert ui_service.append_run_event("R1", "run_started")["ok"]
        first = ui_service.read_run_events("R1")
        assert [e["event_type"] for e in first["events"]] == ["run_started"]
        assert first["terminal"] is False
        assert ui_service.append_run_event("R1", "run_completed")["ok"]
        # 偏移增量续读：offset 回传语义（读侧契约）
        inc = ui_service.read_run_events("R1", int(first["offset"]))
        assert [e["event_type"] for e in inc["events"]] == ["run_completed"]
        assert inc["terminal"] is True
        # 从头全量仍两件
        full = ui_service.read_run_events("R1")
        assert len(full["events"]) == 2

    @pytest.mark.parametrize(
        "bad", ["../x", "a/b", "a\\b", ".", "..", "", "bad\x00id"])
    def test_bad_run_id_rejected(self, runs_root, bad):
        # "bad\x00id"：null 字节此前漏过守卫、open() 抛 ValueError 逃出
        # error 信封契约（W6-S26 P2-2）——守卫显式拒，回归钉在案
        from rfauto.service import ui_service

        out = ui_service.append_run_event(bad, "run_completed")
        assert out["ok"] is False and out["errors"]
        assert not (runs_root / "x").exists() and not (runs_root / "a").exists()

    def test_unknown_event_type_rejected_zero_side_effect(self, runs_root):
        from rfauto.service import ui_service

        out = ui_service.append_run_event("R1", "not_a_real_type")
        assert out["ok"] is False and "未识别 event_type" in out["errors"][0]
        assert not (runs_root / "R1" / "events.jsonl").exists()  # 零落盘

    def test_event_type_enum_accepted(self, runs_root):
        from rfauto.core.events import EventType
        from rfauto.service import ui_service

        _mk_run(runs_root, "R1")
        out = ui_service.append_run_event("R1", EventType.RUN_FAILED)
        assert out["ok"] is True and out["event_type"] == "run_failed"

    def test_missing_run_dir_no_fabrication(self, runs_root):
        # 目录缺席=run_id 失真——零 mkdir 不虚构 run 目录（与读侧零副作用
        # 对称；recipe_write_guard UI 面 AST 盘点口径：写点不新增目录原语）
        from rfauto.service import ui_service

        out = ui_service.append_run_event("GHOST", "run_completed")
        assert out["ok"] is False and "events 写入失败" in out["errors"][0]
        assert not (runs_root / "GHOST").exists()

    def test_write_oserror_error_envelope_no_raise(self, runs_root,
                                                   monkeypatch):
        import rfauto.service.ui_service as us

        def _boom(*_a, **_k):
            raise OSError("disk full")

        # open 是内建（模块 globals 无该名）——raising=False 注入模块级桩
        monkeypatch.setattr(us, "open", _boom, raising=False)
        out = us.append_run_event("R1", "run_completed")
        assert out["ok"] is False and "events 写入失败" in out["errors"][0]

    def test_validate_event_payload_passes_on_written_line(self, runs_root):
        # 写出侧经 W3 统一校验面必须合法（fail-closed 多报方向，#316）
        from rfauto.core.events import validate_event_payload
        from rfauto.service import ui_service

        _mk_run(runs_root, "R1")
        assert ui_service.append_run_event(
            "R1", "trial_completed", data={"cost": 0.1})["ok"]
        line = (runs_root / "R1" / "events.jsonl").read_text(
            encoding="utf-8").strip()
        assert validate_event_payload(json.loads(line)) == []


# ────────────────────────── 2. e2e：写入→SSE 端点可读 ──────────────────────────


class TestWriterToSseEndToEnd:
    def test_append_to_stream_frames(self, runs_root, fresh_bus):
        """生产写入 → runs 镜像 → 生成器帧序列全链路（进程内，#139 零网络）。"""
        from rfauto.service import ui_service
        from rfauto.ui.routes import events as events_routes

        _mk_run(runs_root, "R1")
        assert ui_service.append_run_event("R1", "run_started",
                                           message="开始")["ok"]
        assert ui_service.append_run_event("R1", "run_completed",
                                           message="完成")["ok"]

        sub = fresh_bus.subscribe(source="mirror")
        gen = events_routes.make_stream_generator(
            fresh_bus, sub, domains=("runs",), run_id="R1", tick_s=0.01)

        async def _scenario():
            frames = []
            async for f in gen:  # 终态 end 帧自然收束（自终止生成器）
                frames.append(f)
            return frames

        frames = asyncio.run(_scenario())
        assert [f["event"] for f in frames] == [
            "hello", "run_started", "run_completed", "end"]
        done_env = json.loads(frames[-2]["data"])
        assert done_env["kind"] == "run_completed"
        assert done_env["payload"]["event_type"] == "run_completed"  # 旧事件 dict 原样（向后兼容钉口径）
        assert json.loads(frames[-1]["data"])["terminal"] is True
        assert fresh_bus.subscriber_count() == 0  # 收束路径订阅清理

    def test_missing_stream_still_exists_false(self, runs_root, fresh_bus):
        """未写事件的 run：镜像流 exists=False end 帧（既有语义不因写入方面世而变）。"""
        from rfauto.ui.routes import events as events_routes

        sub = fresh_bus.subscribe(source="mirror")
        gen = events_routes.make_stream_generator(
            fresh_bus, sub, domains=("runs",), run_id="NOPE", tick_s=0.01)

        async def _scenario():
            frames = []
            async for f in gen:
                frames.append(f)
            return frames

        frames = asyncio.run(_scenario())
        assert [f["event"] for f in frames] == ["hello", "end"]
        assert json.loads(frames[-1]["data"])["exists"] is False


# ────────────────────────── 3. tune 路由接线钉 ──────────────────────────


class TestTuneRouteTerminalWrite:
    def _client(self):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        return TestClient(create_ui_app(include_runs_mount=False))

    def _wait_terminal(self, tune_routes, ev_path, timeout_s=5.0):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if ev_path.is_file() and not tune_routes._TUNE_STATE["running"]:
                return True
            time.sleep(0.02)
        return False

    def test_tune_completed_writes_terminal_event(self, runs_root, fresh_bus,
                                                  monkeypatch):
        from rfauto.ui.routes import tune as tune_routes

        def _stub(path, **_kw):
            # 生产不变量：run_optimization 已落盘 run 目录——终端事件才可写
            (runs_root / "R1").mkdir(parents=True, exist_ok=True)
            return {"ok": True, "run_id": "R1", "best_cost": 0.5,
                    "trials_completed": 3}

        monkeypatch.setattr("rfauto.service.api.start_tune", _stub)
        saved = dict(tune_routes._TUNE_STATE)
        try:
            r = self._client().post(
                "/api/tune/start",
                json={"path": "recipes/x.yaml", "adapter": "fake",
                      "max_trials": 1})
            assert r.status_code == 200 and r.json()["ok"] is True
            ev_path = runs_root / "R1" / "events.jsonl"
            assert self._wait_terminal(tune_routes, ev_path), \
                "tune 终态事件未在时限内落盘"
            lines = [json.loads(ln) for ln in
                     ev_path.read_text(encoding="utf-8").splitlines()
                     if ln.strip()]
            assert [e["event_type"] for e in lines] == ["run_completed"]
            assert lines[0]["run_id"] == "R1"
            assert lines[0]["schema"] == "rfauto-event/1"
            assert lines[0]["data"]["trials_completed"] == 3
        finally:
            tune_routes._TUNE_STATE.clear()
            tune_routes._TUNE_STATE.update(saved)

    def test_tune_result_without_run_id_writes_nothing(self, runs_root,
                                                       fresh_bus,
                                                       monkeypatch):
        from rfauto.ui.routes import tune as tune_routes

        monkeypatch.setattr(
            "rfauto.service.api.start_tune",
            lambda path, **_kw: {"ok": True})  # 无 run_id（multi/旧形态）
        saved = dict(tune_routes._TUNE_STATE)
        try:
            r = self._client().post(
                "/api/tune/start",
                json={"path": "recipes/x.yaml", "adapter": "fake",
                      "max_trials": 1})
            assert r.status_code == 200
            deadline = time.time() + 3.0
            while time.time() < deadline and tune_routes._TUNE_STATE["running"]:
                time.sleep(0.02)
            assert tune_routes._TUNE_STATE["running"] is False
            # 零写入（无 run_id 不猜目录）——runs 根未创建
            assert not runs_root.exists() or not any(runs_root.iterdir())
        finally:
            tune_routes._TUNE_STATE.clear()
            tune_routes._TUNE_STATE.update(saved)

    def test_tune_exception_path_writes_nothing(self, runs_root, fresh_bus,
                                                monkeypatch):
        from rfauto.ui.routes import tune as tune_routes

        def _boom(path, **_kw):
            raise RuntimeError("adapter exploded")

        monkeypatch.setattr("rfauto.service.api.start_tune", _boom)
        saved = dict(tune_routes._TUNE_STATE)
        try:
            r = self._client().post(
                "/api/tune/start",
                json={"path": "recipes/x.yaml", "adapter": "fake",
                      "max_trials": 1})
            assert r.status_code == 200
            deadline = time.time() + 3.0
            while time.time() < deadline and tune_routes._TUNE_STATE["running"]:
                time.sleep(0.02)
            assert tune_routes._TUNE_STATE["running"] is False
            assert tune_routes._TUNE_STATE["error"] == "adapter exploded"
            # 异常路径零写入（写入点在成功分支；既有 tune_failed 总线语义不动）
            assert not (runs_root / "R1").exists()
        finally:
            tune_routes._TUNE_STATE.clear()
            tune_routes._TUNE_STATE.update(saved)
