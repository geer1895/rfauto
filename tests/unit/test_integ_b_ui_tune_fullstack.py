"""INTEG-B 席跨模块集成测试：UI 调参全栈链（架构批 INTEG-B，2026-10-14）.

与既有单测的分工（test_ui_event_stream 钉帧形态/钩子语义、test_sampler_cmaes
钉服务层采样通路，均对 start_tune 打桩或缺 UI 面）：本文件把**全链真跑**——

    POST /api/tune/start（routes/tune.py 任务槽 _TUNE_STATE）
      → service/api.start_tune（真 Optuna+fake adapter，进程内零外部依赖）
        → runs/ 作业登记面（runs/<run_id>/meta.json + trials/trial_N.json
          + runs/registry.sqlite record_run 注册表）
        → on_trial 探针 → event_bus（trial_new/tune_started/tune_completed）
      → SSE 帧到达（/api/tune/events/stream，ASGI 直驱）
      → 终态三方一致（SSE 帧 ↔ /api/tune/status ↔ 落盘 run 产物）

正向路径（成功 run 全链一致）+ 错误路径（服务层失败信封 ≠ 线程异常两形态：
前者出 tune_completed(ok=False)、后者出 tune_failed——如实钉住现行契约）+
边界（坏参数 400 不占任务槽、run_seq 单调、_TUNE_STATE 跨测试还原）。

#139 纪律：零网络零真机零真进程——fake adapter 进程内求解，Optuna storage
与 runs/ 注册表全在 monkeypatch.chdir 的 tmp_path 下；SSE 走 ASGI 直驱
（starlette 1.6 TestClient 全量缓冲，长驻流不可经它读——test_ui_event_stream
同款驱动）。不触 static/、不触 service 层源码。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
import yaml

# ────────────────────────── 环境与工具 ──────────────────────────


@pytest.fixture()
def fresh_bus(monkeypatch):
    """隔离事件总线单例（端点经 bus() 现读模块属性——换血零缓存面）。"""
    import rfauto.ui.routes.event_bus as event_bus

    eb = event_bus.EventBus()
    monkeypatch.setattr(event_bus, "_BUS", eb)
    return eb


@pytest.fixture()
def ui_app():
    from rfauto.ui.server import create_ui_app

    return create_ui_app(include_runs_mount=False)


@pytest.fixture()
def client(tmp_path, monkeypatch, fresh_bus, ui_app):
    """TestClient + cwd 隔离（runs//optuna/registry 全落 tmp）+ 任务槽还原。"""
    from rfauto.ui.routes import tune as tune_routes

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    monkeypatch.delenv("RFAUTO_REGISTRY_DB", raising=False)
    saved = dict(tune_routes._TUNE_STATE)
    try:
        from starlette.testclient import TestClient

        yield TestClient(ui_app)
    finally:
        tune_routes._TUNE_STATE.clear()
        tune_routes._TUNE_STATE.update(saved)


def _write_recipe(tmp_path: Path) -> Path:
    """最小 fake 配方（与 test_sampler_cmaes 同款形态——fake 通道进程内求解）。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {
            "arm_len_mm": {"value": 20.5, "unit": "mm",
                           "bounds": [15.0, 30.0]},
        },
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


def _wait_tune_done(timeout_s: float = 60.0) -> None:
    from rfauto.ui.routes import tune as tune_routes

    deadline = time.monotonic() + timeout_s
    while tune_routes._TUNE_STATE["running"] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert tune_routes._TUNE_STATE["running"] is False, "调参线程未在时限内收尾"


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


async def _drive_sse_async(app, path, *, stop, timeout_s: float = 15.0):
    """ASGI 直驱 SSE（真实 http.disconnect 收束；test_ui_event_stream 同款）。"""
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "root_path": "",
        "query_string": b"", "headers": [],
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
        if stop(frames):
            break
    disc.set()
    try:
        await asyncio.wait_for(asyncio.shield(task), 5.0)
    except asyncio.TimeoutError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise AssertionError("SSE 流未响应 http.disconnect") from None
    return frames, info


def _drive_sse(app, path, **kw):
    return asyncio.run(_drive_sse_async(app, path, **kw))


# ────────────────────────── 正向路径：全链一致 ──────────────────────────


class TestFullStackHappyPath:
    def test_tune_start_to_sse_and_run_artifacts_consistent(
            self, client, ui_app, fresh_bus, tmp_path):
        from rfauto.infra.run_store import list_runs
        from rfauto.service import ui_service

        recipe = _write_recipe(tmp_path)
        r = client.post("/api/tune/start", json={
            "path": str(recipe), "adapter": "fake", "max_trials": 3})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["started"] is True
        _wait_tune_done()

        # ── 终态①：任务槽（_TUNE_STATE）───────────────────────────────
        from rfauto.ui.routes import tune as tune_routes

        result = tune_routes._TUNE_STATE["result"]
        assert isinstance(result, dict) and result["ok"] is True
        assert result["trials_completed"] == 3
        assert result["best_cost"] is not None
        assert tune_routes._TUNE_STATE["error"] is None

        run_id = result["run_id"]
        run_dir = tmp_path / "runs" / run_id

        # ── 终态②：落盘作业登记面（meta/trials/SQLite 注册表）──────────
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["run_id"] == run_id
        assert meta["status"] == "done"
        assert meta["adapter"] == "fake"
        assert meta["study_name"] == result["study_name"]
        trial_files = sorted((run_dir / "trials").glob("trial_*.json"))
        assert len(trial_files) == 3
        registry_rows = [row for row in list_runs(limit=50)
                         if row.get("run_id") == run_id]
        assert len(registry_rows) == 1, "runs/registry.sqlite 缺本次 run 登记"
        assert registry_rows[0]["status"] == "done"

        # ── 终态③：轮询面（status/trials）与落盘一致 ───────────────────
        status = client.get("/api/tune/status").json()
        assert status["ok"] is True
        assert status["running"] is False
        assert status["error"] is None
        assert status["result"]["run_id"] == run_id
        trials_view = ui_service.tune_trials(run_id)
        assert trials_view["ok"] is True
        assert trials_view["run_id"] == run_id
        assert len(trials_view["trials"]) == 3

        # ── SSE 帧到达与全链一致（回放自 0：hello + 全部业务帧）────────
        frames, info = _drive_sse(
            ui_app, "/api/tune/events/stream",
            stop=lambda fs: any(f["event"] == "tune_completed" for f in fs))
        assert info["status"] == 200
        assert info["content_type"].startswith("text/event-stream")
        assert frames[0]["event"] == "hello"
        kinds = [f["event"] for f in frames[1:]]
        assert kinds[0] == "tune_started"
        assert kinds[-1] == "tune_completed"
        assert kinds.count("trial_new") == 3

        started = frames[1]["data_json"]
        assert set(started) == {"seq", "ts", "kind", "domain", "payload"}
        assert started["domain"] == "tune"
        assert started["payload"]["path"] == str(recipe)
        assert started["payload"]["adapter"] == "fake"
        seqs = [int(f["data_json"]["seq"]) for f in frames[1:]]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

        trial_frames = [f["data_json"] for f in frames
                        if f["event"] == "trial_new"]
        assert {f["payload"]["number"] for f in trial_frames} == {0, 1, 2}
        assert all(f["payload"]["study"] == result["study_name"]
                   for f in trial_frames)
        # 探针 value 与落盘 trial 文件同源（trial_0.json cost）
        by_number = {}
        for p in trial_files:
            data = json.loads(p.read_text(encoding="utf-8"))
            by_number[int(data["trial_number"])] = data
        for tf in trial_frames:
            n = tf["payload"]["number"]
            assert by_number[n]["cost"] == pytest.approx(tf["payload"]["value"])

        completed = next(f for f in frames
                         if f["event"] == "tune_completed")
        comp = completed["data_json"]
        assert comp["payload"]["ok"] is True  # 与 result 信封一致
        assert comp["payload"]["started_at"] == started["payload"]["started_at"]
        assert frames[1]["id"] == str(started["seq"])
        assert completed["id"] == str(comp["seq"])
        # 断开清理：订阅注册表归零（真实 http.disconnect 全链路）
        assert fresh_bus.subscriber_count() == 0

    def test_status_during_run_reports_running(self, client, ui_app,
                                               fresh_bus, monkeypatch):
        """运行中查询面：running=True 可见，started_at 已置位（慢求解桩）。"""
        def _slow(*a, **kw):
            time.sleep(1.5)
            return {"ok": True, "run_id": "r_slow"}

        monkeypatch.setattr("rfauto.service.api.start_tune", _slow)
        r = client.post("/api/tune/start", json={"path": "p.yaml"})
        assert r.status_code == 200 and r.json()["ok"] is True
        status = client.get("/api/tune/status").json()
        assert status["running"] is True
        assert status["started_at"]
        assert status["result"] is None and status["error"] is None
        _wait_tune_done()
        # 收尾后自动翻转
        assert client.get("/api/tune/status").json()["running"] is False


# ────────────────────────── 错误路径：两形态 ──────────────────────────


class TestFailureShapes:
    def test_service_failure_envelope_emits_completed_ok_false(
            self, client, ui_app, fresh_bus, tmp_path):
        """服务层失败信封（配方不存在）→ tune_completed(ok=False) 非
        tune_failed——线程没炸，失败在信封里如实透出（现行契约钉）。"""
        r = client.post("/api/tune/start", json={
            "path": str(tmp_path / "no_such_recipe.yaml"),
            "adapter": "fake", "max_trials": 2})
        assert r.status_code == 200 and r.json()["ok"] is True
        _wait_tune_done()
        from rfauto.ui.routes import tune as tune_routes

        assert tune_routes._TUNE_STATE["error"] is None  # 线程异常面干净
        result = tune_routes._TUNE_STATE["result"]
        assert result["ok"] is False
        assert any("不存在" in e for e in result["errors"])
        frames, _ = _drive_sse(
            ui_app, "/api/tune/events/stream",
            stop=lambda fs: any(f["event"] == "tune_completed" for f in fs))
        comp = [f for f in frames if f["event"] == "tune_completed"]
        assert len(comp) == 1
        assert comp[0]["data_json"]["payload"]["ok"] is False
        assert not [f for f in frames if f["event"] == "tune_failed"]
        # 失败 run 也完成线程收尾（running 翻 False）
        assert client.get("/api/tune/status").json()["running"] is False

    def test_thread_exception_emits_tune_failed_and_error_state(
            self, client, ui_app, fresh_bus, monkeypatch):
        def _boom(*a, **kw):
            raise RuntimeError("service exploded")

        monkeypatch.setattr("rfauto.service.api.start_tune", _boom)
        r = client.post("/api/tune/start", json={"path": "p.yaml"})
        assert r.status_code == 200 and r.json()["ok"] is True
        _wait_tune_done()
        from rfauto.ui.routes import tune as tune_routes

        assert tune_routes._TUNE_STATE["error"] == "service exploded"
        assert tune_routes._TUNE_STATE["result"] is None
        status = client.get("/api/tune/status").json()
        assert status["running"] is False and status["error"] == (
            "service exploded")
        frames, _ = _drive_sse(
            ui_app, "/api/tune/events/stream",
            stop=lambda fs: any(f["event"] == "tune_failed" for f in fs))
        failed = [f for f in frames if f["event"] == "tune_failed"]
        assert len(failed) == 1
        assert failed[0]["data_json"]["payload"]["error"] == "service exploded"

    def test_two_failures_same_second_both_emit(self, client, ui_app,
                                                fresh_bus, monkeypatch):
        """连续两次失败（run_seq 去重键）：两个独立帧不撞去重窗。"""
        from rfauto.ui.routes import tune as tune_routes

        seq0 = int(tune_routes._TUNE_STATE.get("run_seq") or 0)
        monkeypatch.setattr(
            "rfauto.service.api.start_tune",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("x")))
        for _ in range(2):
            r = client.post("/api/tune/start", json={"path": "p.yaml"})
            assert r.status_code == 200
            _wait_tune_done()
        frames, _ = _drive_sse(
            ui_app, "/api/tune/events/stream",
            stop=lambda fs: sum(1 for f in fs
                                if f["event"] == "tune_failed") >= 2)
        failed = [f for f in frames if f["event"] == "tune_failed"]
        assert len(failed) == 2
        seqs = [f["data_json"]["seq"] for f in failed]
        assert seqs[0] < seqs[1]
        assert tune_routes._TUNE_STATE["run_seq"] == seq0 + 2  # 单调启动计数


# ────────────────────────── 边界：参数守卫与隔离 ──────────────────────────


class TestBoundaries:
    def test_bad_params_rejected_400_slot_not_occupied(
            self, client, fresh_bus):
        # A6 P0-2：坏参数路由层守卫 400 信封，不占任务槽、不出事件帧
        from rfauto.ui.routes import tune as tune_routes

        seq0 = int(tune_routes._TUNE_STATE.get("run_seq") or 0)
        r = client.post("/api/tune/start",
                        json={"path": "p.yaml", "n_gen": "abc"})
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False and body["errors"]
        assert tune_routes._TUNE_STATE["running"] is False
        assert tune_routes._TUNE_STATE["run_seq"] == seq0  # 未启动
        assert fresh_bus.head_seq() == 0  # 零事件帧（隔离总线 seq 轴未推进）

    def test_bad_json_body_400(self, client):
        r = client.post("/api/tune/start", content=b"not-json",
                        headers={"content-type": "application/json"})
        assert r.status_code == 400
        assert r.json()["ok"] is False

    def test_tune_trials_unknown_run_returns_empty_envelope(
            self, client, tmp_path):
        body = client.get(
            "/api/tune/trials", params={"run_id": "no_such_run"}).json()
        assert body["ok"] is True
        assert body["trials"] == []
