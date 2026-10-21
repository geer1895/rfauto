"""R8-ENG2（架构批）：UI runs 端点 registry 单源接线 + 长 POST 线程池行为钉。

覆盖面：
- registry 单源：covered 态与 legacy 态（RFAUTO_UI_REGISTRY=0）五端点
  输出字节等价（含豁免类目录：helper/判伪 meta/B 类 no_meta）；registry
  优先实证——covered 态下删 meta.json 端点仍出 model/adapter（行供给）；
  缺行态回退全扫且后台自愈回填落库（backfill 同口径行）；指纹（registry
  mtime+size、顶层目录名集）不变时索引命中零 sqlite 查询；env 关闭双开关
  （RFAUTO_UI_REGISTRY / RFAUTO_UI_CACHE）与库损坏降级。
- A6 P1-3 长 POST 线程池：api_run / api_chat / api_hfss_import 三类同步
  阻塞路由下放工作线程后，长请求进行中短请求（/api/tune/status）不被
  阻塞（并发探针：长请求 parked 在线程内、事件循环仍可服务短请求；
  未下放的反事实下 started 探针等待会超时直接失败）。

隔离：全部 tmp cwd（#144）+ RFAUTO_REGISTRY_DB 钉 tmp（env 优先级高于
settings，绝不触真实 runs/registry.sqlite）；缓存/自愈态/代际逐测试复位
（pytest-randomly 顺序无关）。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from rfauto.service import db_service, ui_service

h5py = pytest.importorskip("h5py")


@pytest.fixture()
def ui_env(tmp_path, monkeypatch):
    """tmp cwd + tmp registry（env 钉）+ 全部进程内状态复位。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RFAUTO_UI_CACHE", raising=False)
    dbp = tmp_path / "registry.sqlite"
    monkeypatch.setenv("RFAUTO_REGISTRY_DB", str(dbp))
    ui_service._ui_scan_cache_clear()
    ui_service._REG_GEN_LAST_SHAPE[0] = None
    ui_service._REG_GEN["n"] = 0
    ui_service._REG_HEAL_STATE.update({"last": 0.0, "running": False})
    yield {"tmp": tmp_path, "db": dbp}
    ui_service._ui_scan_cache_clear()


def _write_meta(run: Path, **kw) -> None:
    doc = {"model": "m", "adapter": "a"}
    doc.update(kw)
    run.mkdir(parents=True, exist_ok=True)
    (run / "meta.json").write_text(json.dumps(doc), encoding="utf-8")


def _write_gate(run: Path, verdict: str = "PASS", rho: float = 0.9) -> None:
    calib = run / "calibration"
    calib.mkdir(parents=True, exist_ok=True)
    (calib / "gate.json").write_text(json.dumps({
        "verdict": verdict, "rho": rho, "n_samples": 12, "n_failures": 0,
        "mesh_resolution_mm": 0.45, "surrogate_kind": "gp",
        "loocv": {"rho": rho},
    }), encoding="utf-8")


def _build_tree(root: Path) -> Path:
    """合成 runs/ 树：A 类判真×2 + 判伪 meta + B 类无 meta 真跑 + helper。"""
    runs = root / "runs"
    a = runs / "20260101_000000_a"
    (a / "results").mkdir(parents=True)
    _write_gate(a, verdict="PASS", rho=0.9)
    _write_meta(a, model="wilkinson", adapter="openems")
    (a / "report.md").write_text("# A", encoding="utf-8")
    (a / "results" / "pareto_front.json").write_text("{}", encoding="utf-8")
    b = runs / "20260102_000000_b"
    (b / "trials").mkdir(parents=True)
    for i in range(2):
        (b / "trials" / f"trial_{i}.json").write_text("{}", encoding="utf-8")
    _write_meta(b, model="patch", adapter="fake",
                algorithm="cross_fidelity_gate_from_asset",
                metrics={"rho": 0.7, "top5_recall": 0.8, "verdict": "PASS"})
    (b / "sim_ci_report.md").write_text("# B", encoding="utf-8")
    # 判伪 meta（无 adapter/study 键，#144）：registry 豁免、端点走文件读
    c = runs / "pseudo_meta_dir"
    c.mkdir()
    (c / "meta.json").write_text(json.dumps({"model": "from_pseudo"}),
                                 encoding="utf-8")
    # B 类：run 点命名（时间戳_hex8）+ trials 证据 + 无 meta
    d = runs / "20260103_000000_d1d0d1d0"
    (d / "trials").mkdir(parents=True)
    (d / "trials" / "trial_0.json").write_text("{}", encoding="utf-8")
    # helper：无 meta 非 run 点命名
    (runs / "helper_scratch").mkdir()
    (runs / "loose.txt").write_text("x", encoding="utf-8")
    return runs


def _seed_registry_sync(db: Path) -> int:
    """同步补齐 registry（walk 缺行 + 自愈回填同链；测试确定性用）。"""
    rows = ui_service._missing_registry_rows(set())
    return ui_service._self_heal_backfill(rows, db_path=db)


def _dumps(doc) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


_ENDPOINTS = (
    ("calibration_runs", lambda: ui_service.calibration_runs()),
    ("cross_fidelity_view", lambda: ui_service.cross_fidelity_view()),
    ("list_reports", lambda: ui_service.list_reports()),
    ("pareto_runs", lambda: ui_service.pareto_runs(limit=200)),
    ("field_runs", lambda: ui_service.field_runs(limit=50)),
)


class TestRegistrySingleSource:
    def test_covered_mode_byte_equivalent_to_legacy(self, ui_env, monkeypatch):
        """covered 态（registry 单源）与 legacy 态五端点输出逐字节相等。"""
        _build_tree(ui_env["tmp"])
        monkeypatch.setenv("RFAUTO_UI_REGISTRY", "0")  # legacy：恒全扫
        legacy = {name: fn() for name, fn in _ENDPOINTS}
        monkeypatch.delenv("RFAUTO_UI_REGISTRY")
        assert _seed_registry_sync(ui_env["db"]) >= 2  # A 类×2 + B 类×1
        ui_service._ui_scan_cache_clear()
        assert ui_service._registry_meta_lookup() is not None  # covered
        for name, fn in _ENDPOINTS:
            assert _dumps(fn()) == _dumps(legacy[name]), name

    def test_registry_first_serves_after_meta_removed(self, ui_env,
                                                      monkeypatch):
        """registry 优先实证：covered 态下删 meta.json，端点仍出文件面值
        （行供给）；legacy 态同树则 model=None（文件面语义）。"""
        runs = _build_tree(ui_env["tmp"])
        _seed_registry_sync(ui_env["db"])
        ui_service._ui_scan_cache_clear()
        assert ui_service._registry_meta_lookup() is not None
        meta = runs / "20260101_000000_a" / "meta.json"
        meta.unlink()  # 目录 mtime 变化 → 快照/索引重建，行仍在
        r = ui_service.pareto_runs(limit=200)
        row = next(e for e in r["runs"]
                   if e["run_id"] == "20260101_000000_a")
        assert (row["model"], row["adapter"]) == ("wilkinson", "openems")
        # 对照：关闭 registry 走文件面 → meta.json 已删 → None
        monkeypatch.setenv("RFAUTO_UI_REGISTRY", "0")
        ui_service._ui_scan_cache_clear()
        r2 = ui_service.pareto_runs(limit=200)
        row2 = next(e for e in r2["runs"]
                    if e["run_id"] == "20260101_000000_a")
        assert row2["model"] is None and row2["adapter"] is None

    def test_missing_row_falls_back_and_self_heals(self, ui_env, monkeypatch):
        """缺行态：端点回退全扫仍正确；后台自愈把缺行落库（backfill 同口径），
        落库后升级 covered。"""
        runs = _build_tree(ui_env["tmp"])
        # 空 registry（建表不灌行）：判真×2 即缺行
        from rfauto.infra.db import RegistryDB

        db = RegistryDB(path=ui_env["db"])
        db.migrate()
        db.close()
        monkeypatch.setattr(ui_service, "_REG_HEAL_MIN_INTERVAL_S", 0.0)
        r = ui_service.calibration_runs()  # 回退全扫：gate 条目照常出
        entry = next(e for e in r["runs"]
                     if e["run_id"] == "20260101_000000_a")
        assert (entry["model"], entry["verdict"]) == ("wilkinson", "PASS")
        # 自愈落库轮询（daemon 线程异步）
        deadline = time.monotonic() + 10.0
        n_rows = 0
        while time.monotonic() < deadline:
            con = sqlite3.connect(str(ui_env["db"]))
            try:
                n_rows = int(con.execute(
                    "SELECT COUNT(*) FROM runs").fetchone()[0])
            finally:
                con.close()
            if n_rows >= 3:  # A×2 + B×1（判伪/helper 不入）
                break
            time.sleep(0.05)
        assert n_rows >= 3, "自愈回填未在时限内落库"
        con = sqlite3.connect(str(ui_env["db"]))
        try:
            row = con.execute(
                "SELECT model, adapter, status, meta FROM runs "
                "WHERE run_id='20260101_000000_a'").fetchone()
        finally:
            con.close()
        assert row[:3] == ("wilkinson", "openems", "unknown")
        assert "r8_ui_selfheal" in row[3]
        # 落库 → registry mtime 变化 → 指纹失效 → covered 升级
        ui_service._ui_scan_cache_clear()
        assert ui_service._registry_meta_lookup() is not None
        assert Path(runs / "20260102_000000_b").is_dir()  # 树未被扰动

    def test_fingerprint_hit_skips_registry_query(self, ui_env, monkeypatch):
        """指纹（registry 签名+目录名集）不变 → 索引命中，二跑零 sqlite 查询。"""
        _build_tree(ui_env["tmp"])
        _seed_registry_sync(ui_env["db"])
        ui_service._ui_scan_cache_clear()
        real = db_service.registry_runs_query
        calls = {"n": 0}

        def counting(*a, **kw):
            calls["n"] += 1
            return real(*a, **kw)

        monkeypatch.setattr(db_service, "registry_runs_query", counting)
        for _, fn in _ENDPOINTS:
            fn()  # 冷：索引建立（≤1 次查询）
        warm = calls["n"]
        assert 1 <= warm <= 2
        for _, fn in _ENDPOINTS:
            fn()  # 暖：快照/索引双命中
        assert calls["n"] == warm, "指纹未变仍重查 registry"

    def test_registry_off_switch_never_queries(self, ui_env, monkeypatch):
        """RFAUTO_UI_REGISTRY=0：registry 零查询，端点恒走全扫（A/B 计时口）。"""
        _build_tree(ui_env["tmp"])
        _seed_registry_sync(ui_env["db"])
        monkeypatch.setenv("RFAUTO_UI_REGISTRY", "0")
        ui_service._ui_scan_cache_clear()
        real = db_service.registry_runs_query
        calls = {"n": 0}

        def counting(*a, **kw):
            calls["n"] += 1
            return real(*a, **kw)

        monkeypatch.setattr(db_service, "registry_runs_query", counting)
        for _, fn in _ENDPOINTS:
            fn()
        assert calls["n"] == 0
        assert ui_service._registry_meta_lookup() is None

    def test_corrupt_registry_degrades_to_full_scan(self, ui_env):
        """库文件损坏：registry_runs_query 错误信封 → covered=False，端点
        回退全扫照常出数（不炸不挂）。"""
        runs = _build_tree(ui_env["tmp"])
        ui_env["db"].write_bytes(b"not a sqlite database at all")
        r = ui_service.calibration_runs()
        entry = next(e for e in r["runs"]
                     if e["run_id"] == "20260101_000000_a")
        assert (entry["model"], entry["verdict"]) == ("wilkinson", "PASS")
        assert Path(runs).is_dir()

    def test_index_stats_include_reg_cache(self, ui_env):
        """观测面：reg_index 缓存入 stats/clear 单源清单。"""
        _build_tree(ui_env["tmp"])
        stats = ui_service._ui_cache_stats()
        assert set(stats) >= {"reg_index", "snapshot"}
        assert set(stats["reg_index"]) == {"enabled", "hits", "misses",
                                           "entries"}
        ui_service._ui_scan_cache_clear()
        assert ui_service._REG_INDEX_CACHE._store == {}


# ── A6 P1-3：长 POST 线程池化并发探针 ────────────────────────────────────────


class TestLongPostThreadpool:
    """长请求 parked 在工作线程期间，事件循环仍服务短请求。

    反事实（裸同步）下事件循环被长请求协程占死：started 探针的
    wait_for 先超时，测试以 TimeoutError 失败——探针即回归钉。
    """

    @staticmethod
    def _assert_probe_result(short, long_resp, dt: float,
                             long_body_key: str | None = None,
                             long_body_val: Any = None) -> None:
        assert short.status_code == 200
        assert short.json()["ok"] is True  # 短请求完整出信封
        assert long_resp.status_code == 200
        body = long_resp.json()
        assert body["ok"] is True
        if long_body_key is not None:
            assert body[long_body_key] == long_body_val
        assert dt < 5.0, f"短请求耗时 {dt:.2f}s——事件循环疑似被长请求冻结"

    def _probe(self, monkeypatch, route: str, post_json: dict,
               patch_target: str, ret: dict):
        """通用并发探针：长 POST parked + 短 GET 计时（httpx ASGITransport）。"""
        import httpx

        from rfauto.ui.server import create_ui_app

        started = threading.Event()
        release = threading.Event()

        def _parked(*a, **kw):
            started.set()
            release.wait(timeout=15.0)
            return dict(ret)

        monkeypatch.setattr(patch_target, _parked)

        async def _main():
            app = create_ui_app(include_runs_mount=False)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                    transport=transport, base_url="http://t") as ac:
                long_task = asyncio.create_task(ac.post(route, json=post_json))
                # 长请求已进入（线程池内 parked；反事实下事件循环占死、
                # 本等待超时失败=探针抓到回归）
                await asyncio.wait_for(asyncio.to_thread(started.wait), 15.0)
                t0 = time.perf_counter()
                short = await asyncio.wait_for(ac.get("/api/tune/status"), 10.0)
                dt = time.perf_counter() - t0
                long_resp = await long_task
                return short, long_resp, dt

        try:
            return asyncio.run(_main())
        finally:
            release.set()  # 泄漏探针兜底释放

    def test_run_once_offloop_short_request_unblocked(self, ui_env,
                                                      monkeypatch):
        short, long_resp, dt = self._probe(
            monkeypatch, "/api/run", {"path": "r", "adapter": "fake"},
            "rfauto.service.api.run_once", {"ok": True, "run_id": "x"})
        self._assert_probe_result(short, long_resp, dt, "run_id", "x")

    def test_hfss_import_offloop_short_request_unblocked(self, ui_env,
                                                         monkeypatch):
        short, long_resp, dt = self._probe(
            monkeypatch, "/api/hfss/import", {"project": "p.aedt"},
            "rfauto.service.v3_services.hfss_import_recipe",
            {"ok": True, "spec": {"variables": {}}})
        self._assert_probe_result(short, long_resp, dt)

    def test_chat_offloop_short_request_unblocked(self, ui_env, monkeypatch):
        """chat 探针：AgentChat 单例打桩为 parked chat，短请求不被阻塞。"""
        import httpx

        # 架构批 UI-R1 拆分：会话单例随 api_chat 机械迁 routes/agent.py
        # （server_mod 薄 re-export 不含 _CHAT_INSTANCE，patch 目标随单源走）。
        from rfauto.ui.routes import agent as agent_routes
        from rfauto.ui.server import create_ui_app

        started = threading.Event()
        release = threading.Event()

        class _FakeChat:
            def chat(self, message: str) -> dict:
                started.set()
                release.wait(timeout=15.0)
                return {"ok": True, "reply": f"echo:{message}"}

        monkeypatch.setattr(agent_routes, "_CHAT_INSTANCE", None)
        monkeypatch.setattr("rfauto.service.r3_services.AgentChat",
                            _FakeChat)

        async def _main():
            app = create_ui_app(include_runs_mount=False)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                    transport=transport, base_url="http://t") as ac:
                long_task = asyncio.create_task(
                    ac.post("/api/chat", json={"message": "hi"}))
                await asyncio.wait_for(asyncio.to_thread(started.wait), 15.0)
                t0 = time.perf_counter()
                short = await asyncio.wait_for(ac.get("/api/tune/status"), 10.0)
                dt = time.perf_counter() - t0
                long_resp = await long_task
                return short, long_resp, dt

        try:
            short, long_resp, dt = asyncio.run(_main())
        finally:
            release.set()
            monkeypatch.setattr(agent_routes, "_CHAT_INSTANCE", None)
        self._assert_probe_result(short, long_resp, dt, "reply", "echo:hi")

    def test_hfss_import_empty_path_still_fast_400(self, ui_env):
        """空路径快速 400 守卫保持同步（不下线程池，不真启 AEDT）。"""
        from rfauto.ui.server import create_ui_app

        client = TestClient(create_ui_app(include_runs_mount=False))
        r = client.post("/api/hfss/import", json={"project": "  "})
        assert r.status_code == 400
        assert r.json()["ok"] is False
