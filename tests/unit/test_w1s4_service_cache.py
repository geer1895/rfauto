"""aurora_f W1-S4：service 目录扫回潮治理三件缓存 + P3 快活批行为单测。

缓存三件（R3_perf_quality.md §1.1 A 类）：
- a. surrogate_playground.playground_runs（UI GET 每请求全表扫）→ 接
  ui_service._SNAPSHOT_CACHE 指纹+TTL 快照（aurora72 A2-D 基建复用）；
- b. ui_service.run_detail（rglob 全树+Touchstone 每请求重解析）→
  _RUN_SCAN_CACHE per-run (path, 结构名集, 语义文件 mtime/size) 签名；
- c. rationale_memory._collect_docs（1803+ 次 meta/autotune/report 逐读）
  → _DOCS_CACHE 指纹快照。

钉面（逐键一致 + 失效语义）：
- 缓存前后输出逐键一致（== 全量比对，含 sparams_warning 等旁路键）；
- 结构性变化（新 run 目录/新产物文件）即刻可见（枚举名集，不依赖
  NTFS 目录 mtime 懒更新——确定性钉）；
- 语义输入就地改写（metrics.json）即刻失效（文件级 mtime/size）；
- deepcopy/浅拷贝防污染；RFAUTO_UI_CACHE=0 全直通（计数与缓存面不动）。

P3 快活批钉（同席清偿，R3 §2.1）：
- W6-P3-6 tune TOCTOU：任务槽置位先于 body await（交错第二请求必被拒）；
- Top6 load_settings 会话缓存：同参两次逐字段一致/副本隔离/env 与文件
  变化即刻失效；
- W5-P3-6/W6-P3-7 template_golden：digest 现值逐位不变 + 渲染源指纹
  失效 + 非 ValueError 渲染异常落 error 态不穿透。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from rfauto.service import ui_scan_cache, ui_service
from rfauto.service.rationale_memory import (
    _DOCS_CACHE,
    _collect_docs,
    build_index,
)
from rfauto.service.surrogate_playground import playground_runs
from rfauto.service.ui_service import _ui_cache_stats, _ui_scan_cache_clear


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, isolated):
    monkeypatch.delenv("RFAUTO_UI_CACHE", raising=False)
    _ui_scan_cache_clear()
    yield
    _ui_scan_cache_clear()
    _DOCS_CACHE._store.clear()


# ── 公共夹具 ────────────────────────────────────────────────────────────────


def _make_calibrated_run(run_id: str = "20260101_000000_pg") -> Path:
    base = Path("runs") / run_id / "calibration"
    base.mkdir(parents=True)
    (base / "samples.json").write_text(json.dumps({
        "bounds": {"a_mm": [1.0, 2.0]}, "samples": [
            {"params": {"a_mm": 1.0 + i * 0.1},
             "metrics": {"t": 2.0 * i}} for i in range(5)],
    }), encoding="utf-8")
    (base / "campaign.json").write_text(json.dumps({
        "best_surrogate": "poly_ridge", "augment_rho": 0.9,
        "augment_verdict": "PASS", "n_samples": 5,
    }), encoding="utf-8")
    return Path("runs") / run_id


def _make_detail_run(run_id: str = "20260101_000000_d") -> Path:
    run_dir = Path("runs") / run_id
    (run_dir / "results" / "figs").mkdir(parents=True)
    (run_dir / "results" / "metrics.json").write_text(
        json.dumps({"metrics": {"s11_db": -15.2}}), encoding="utf-8")
    (run_dir / "recipe.snapshot.yaml").write_text(yaml.safe_dump({
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"unit": "mm", "value": 20.5}},
    }), encoding="utf-8")
    (run_dir / "results" / "figs" / "s11_curve.png").write_bytes(b"png")
    return run_dir


def _make_corpus_run(run_id: str = "20260905_aaaaaaaa_r1",
                     verdict: str = "FAIL") -> Path:
    run = Path("runs") / run_id
    (run / "calibration").mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({
        "model": "m1", "adapter": "a1", "metrics": {"verdict": verdict},
    }), encoding="utf-8")
    return run


# ── a. playground_runs ──────────────────────────────────────────────────────


class TestPlaygroundRunsCache:
    def test_two_calls_key_identical(self):
        _make_calibrated_run()
        r1 = playground_runs()
        r2 = playground_runs()
        assert r1 == r2  # 逐键一致钉（含 ok/runs 全量）
        assert r1["runs"][0]["best_surrogate"] == "poly_ridge"

    def test_new_run_dir_immediately_visible(self, monkeypatch):
        # 顶层名集变化即刻失效（不依赖目录 mtime，NTFS 懒更新不影响）
        monkeypatch.setattr(ui_scan_cache, "_UI_SCAN_TTL_S", 99999.0)  # T1 解环：常量随定义体迁 ui_scan_cache
        assert playground_runs()["runs"] == []
        _make_calibrated_run()
        rows = playground_runs()["runs"]
        assert [x["run_id"] for x in rows] == ["20260101_000000_pg"]

    def test_deepcopy_isolation(self):
        _make_calibrated_run()
        r1 = playground_runs()
        r1["runs"].append({"junk": True})
        r2 = playground_runs()
        assert all("junk" not in x for x in r2["runs"])

    def test_env_off_passthrough(self, monkeypatch):
        monkeypatch.setenv("RFAUTO_UI_CACHE", "0")
        _make_calibrated_run("20260101_000000_p1")
        assert len(playground_runs()["runs"]) == 1
        _make_calibrated_run("20260102_000000_p2")
        st0 = _ui_cache_stats()
        rows = playground_runs()["runs"]
        assert _ui_cache_stats() == st0  # env 关闭：缓存面与计数全不动
        assert [x["run_id"] for x in rows] == [
            "20260101_000000_p1", "20260102_000000_p2"]  # 直通无 TTL 旧读（升序）


# ── b. ui_service.run_detail ────────────────────────────────────────────────


class TestRunDetailCache:
    RID = "20260101_000000_d"

    def test_two_calls_key_identical(self):
        _make_detail_run(self.RID)
        d1 = ui_service.run_detail(self.RID)
        d2 = ui_service.run_detail(self.RID)
        assert d1 == d2  # 逐键一致钉（files/metrics/figs/model3d 全量）

    def test_results_new_file_immediately_visible(self):
        # results/ 结构性变化（新文件）→ scandir 名集变化 → 即刻失效
        run_dir = _make_detail_run(self.RID)
        d1 = ui_service.run_detail(self.RID)
        n1 = len(d1["files"])
        (run_dir / "results" / "extra.bin").write_bytes(b"x")
        d2 = ui_service.run_detail(self.RID)
        assert len(d2["files"]) == n1 + 1

    def test_figs_new_file_immediately_visible(self):
        run_dir = _make_detail_run(self.RID)
        d1 = ui_service.run_detail(self.RID)
        assert len(d1["figs"]) == 1
        (run_dir / "results" / "figs" / "s21_curve.png").write_bytes(b"p")
        d2 = ui_service.run_detail(self.RID)
        assert len(d2["figs"]) == 2

    def test_metrics_in_place_rewrite_immediate(self):
        # 语义输入就地改写 → 文件级 (mtime_ns,size) 失效即刻；新值须变字节
        # 数（等长重写落同一 NTFS 时间戳刻度时签名不变——签名族已知盲窗，
        # 见 load_settings 缓存注记；house 先例 test_ui_service_cache 同款）
        mp = _make_detail_run(self.RID) / "results" / "metrics.json"
        ui_service.run_detail(self.RID)
        m = json.loads(mp.read_text(encoding="utf-8"))
        m["metrics"]["s11_db"] = -42.25
        mp.write_text(json.dumps(m), encoding="utf-8")
        d = ui_service.run_detail(self.RID)
        assert d["metrics"]["metrics"]["s11_db"] == -42.25

    def test_deepcopy_isolation(self):
        _make_detail_run(self.RID)
        d1 = ui_service.run_detail(self.RID)
        d1["files"].clear()
        d2 = ui_service.run_detail(self.RID)
        assert d2["files"]  # 调用方变换不污染缓存

    def test_env_off_passthrough(self, monkeypatch):
        monkeypatch.setenv("RFAUTO_UI_CACHE", "0")
        run_dir = _make_detail_run(self.RID)
        d1 = ui_service.run_detail(self.RID)
        (run_dir / "results" / "late.bin").write_bytes(b"x")
        st0 = _ui_cache_stats()
        d2 = ui_service.run_detail(self.RID)
        assert _ui_cache_stats() == st0
        assert len(d2["files"]) == len(d1["files"]) + 1  # 直通：立即可见

    def test_missing_run_error_unchanged(self):
        d = ui_service.run_detail("no_such_run")
        assert d["ok"] is False and d["errors"]


# ── c. rationale_memory._collect_docs ───────────────────────────────────────


class TestRationaleDocsCache:
    def test_two_calls_docs_identical(self):
        _make_corpus_run()
        d1 = _collect_docs(Path("runs"))
        d2 = _collect_docs(Path("runs"))
        assert d1 == d2  # 逐键一致钉（doc id+text 全量）
        assert d1 and d1[0]["id"].endswith("/meta")

    def test_build_index_warm_same_docs(self):
        _make_corpus_run()
        i1 = build_index("runs")
        i2 = build_index("runs")
        assert i1["docs"] == i2["docs"] and i1["n_docs"] == i2["n_docs"]
        assert i1["ok"] and i2["ok"]

    def test_new_run_immediately_visible(self, monkeypatch):
        monkeypatch.setattr(ui_scan_cache, "_UI_SCAN_TTL_S", 99999.0)  # T1 解环：常量随定义体迁 ui_scan_cache
        assert build_index("runs")["ok"] is False  # 无语料
        _make_corpus_run("20260905_aaaaaaaa_r1")
        idx = build_index("runs")
        assert idx["ok"] and idx["n_docs"] == 1
        _make_corpus_run("20260905_aaaaaaaa_r2", verdict="PASS")
        idx2 = build_index("runs")
        assert idx2["n_docs"] == 2  # 新 run 目录即刻入语料

    def test_new_proposal_file_immediately_visible(self):
        _make_corpus_run()
        assert build_index("runs")["n_docs"] == 1
        prop = Path("runs") / "agent_proposals"
        prop.mkdir(exist_ok=True)
        (prop / "p1.json").write_text('{"rationale": "调宽馈线"}',
                                      encoding="utf-8")
        assert build_index("runs")["n_docs"] == 2  # 提案文件即刻入语料

    def test_returned_list_isolation(self):
        _make_corpus_run()
        d1 = _collect_docs(Path("runs"))
        d1.append({"id": "junk", "text": "x"})  # 调用方变换不污染缓存
        d2 = _collect_docs(Path("runs"))
        assert all(x["id"] != "junk" for x in d2)

    def test_env_off_passthrough(self, monkeypatch):
        monkeypatch.setenv("RFAUTO_UI_CACHE", "0")
        _make_corpus_run("20260905_aaaaaaaa_r1")
        assert build_index("runs")["n_docs"] == 1
        _make_corpus_run("20260905_aaaaaaaa_r2")
        st_hits = _DOCS_CACHE.hits
        assert build_index("runs")["n_docs"] == 2  # 直通：立即可见
        assert _DOCS_CACHE.hits == st_hits  # env 关闭零命中计数

    def test_runs_dir_argument_isolation(self, tmp_path):
        # 不同 runs_dir 入参各走各的缓存键（build_index 任意路径契约）
        other = tmp_path / "other_runs"
        _make_corpus_run("20260905_aaaaaaaa_r1")
        r = other / "20260905_aaaaaaaa_r9"
        r.mkdir(parents=True)
        (r / "meta.json").write_text('{"model": "m9"}', encoding="utf-8")
        assert build_index("runs")["n_docs"] == 1
        assert build_index(other)["n_docs"] == 1  # 互不串味


# ── W6-P3-6 tune TOCTOU ─────────────────────────────────────────────────────


def _bare_request() -> Any:
    from starlette.requests import Request

    return Request({"type": "http", "method": "POST", "headers": [],
                    "query_string": b""})


def _wait_tune_idle(timeout_s: float = 5.0) -> None:
    from rfauto.ui.routes.tune import _TUNE_STATE

    deadline = time.monotonic() + timeout_s
    while _TUNE_STATE["running"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not _TUNE_STATE["running"], "tune 后台线程未在超时内释放任务槽"


class TestTuneStartToctou:
    def test_slot_held_before_body_await(self, monkeypatch):
        """W6-P3-6：槽置位先于 _json_body await——桩在读 body 时再入端点
        （模拟交错第二请求），第二请求必须被"已在运行"拒（旧序下双双通过
        检查=双启动窗口）。start_tune 桩化隔离真实调参。"""
        from rfauto.service import api as api_mod
        from rfauto.ui.routes import tune as tune_mod

        monkeypatch.setattr(api_mod, "start_tune",
                            lambda *a, **k: {"ok": True})
        monkeypatch.setattr(api_mod, "start_tune_multi",
                            lambda *a, **k: {"ok": True})
        inner: dict[str, Any] = {}

        async def spy_body(request):
            if not inner.get("entered"):
                inner["entered"] = True
                # 第一请求仍在读 body（旧实现此时尚未置位槽）——完整走
                # 第二请求端点
                resp2 = await tune_mod.api_tune_start(_bare_request())
                inner["resp2"] = json.loads(resp2.body)
            return {"path": "x"}

        monkeypatch.setattr(tune_mod, "_json_body", spy_body)
        try:
            resp1 = asyncio.run(tune_mod.api_tune_start(_bare_request()))
            j1 = json.loads(resp1.body)
            assert inner["resp2"]["ok"] is False
            assert "在运行" in inner["resp2"]["error"]  # 任务槽拒（旧序双通过）
            assert j1["ok"] is True  # 第一请求正常启动
        finally:
            _wait_tune_idle()

    def test_bad_param_releases_slot(self, monkeypatch):
        """A6 P0-2 行为保持：置位提前后，参数解析失败必须释放槽
        （"坏参数不占任务槽"——下一请求可正常启动）。"""
        from rfauto.service import api as api_mod
        from rfauto.ui.routes import tune as tune_mod

        monkeypatch.setattr(api_mod, "start_tune", lambda *a, **k: {"ok": 1})
        monkeypatch.setattr(api_mod, "start_tune_multi",
                            lambda *a, **k: {"ok": 1})

        async def bad_body(request):
            return {"n_gen": "abc"}  # _int_param 抛 ParamError

        monkeypatch.setattr(tune_mod, "_json_body", bad_body)
        from rfauto.ui.params import ParamError

        with pytest.raises(ParamError):
            asyncio.run(tune_mod.api_tune_start(_bare_request()))
        from rfauto.ui.routes.tune import _TUNE_STATE

        assert _TUNE_STATE["running"] is False  # 槽已释放


# ── Top6 load_settings 会话缓存 ─────────────────────────────────────────────


class TestLoadSettingsCache:
    def test_two_calls_field_identical_and_copied(self):
        from rfauto.infra.config import load_settings

        s1 = load_settings()
        s2 = load_settings()
        assert s1 == s2  # 逐字段一致钉
        assert s1 is not s2  # 副本返回（调用方改动不污染缓存）
        s1.grpc_port = 999
        assert load_settings().grpc_port == s2.grpc_port

    def test_env_change_invalidates_immediately(self, monkeypatch):
        from rfauto.infra.config import load_settings

        base = load_settings().timeout_default_s
        monkeypatch.setenv("RFAUTO_TIMEOUT_S", str(base + 7))
        assert load_settings().timeout_default_s == base + 7  # 即刻生效
        monkeypatch.delenv("RFAUTO_TIMEOUT_S")
        assert load_settings().timeout_default_s == base  # 还原即刻生效

    def test_yaml_rewrite_invalidates_immediately(self, tmp_path,
                                                  monkeypatch):
        from rfauto.infra.config import load_settings

        base = tmp_path / "settings.yaml"
        base.write_text("timeout_default_s: 111\n", encoding="utf-8")
        assert load_settings(base).timeout_default_s == 111
        # 重写改变字节数（同 (mtime,size) 是签名族的已知盲窗：两次写落同一
        # NTFS 时间戳刻度且等长时签名不变——test_ui_service_cache 的
        # json 重写钉同款处理，human 尺度配置编辑不受影响）
        base.write_text("timeout_default_s: 222  # rewritten\n",
                        encoding="utf-8")
        assert load_settings(base).timeout_default_s == 222  # 改写即刻生效
        local = tmp_path / "settings.local.yaml"
        local.write_text("timeout_default_s: 333\n", encoding="utf-8")
        assert load_settings(base).timeout_default_s == 333  # local 覆盖生效


# ── W5-P3-6 / W6-P3-7 template_golden 双修 ──────────────────────────────────


class TestTemplateGoldenDigest:
    def test_digest_value_unchanged_across_calls(self):
        # 值面逐位不变钉（缓存键换源指纹，payload 零变化）
        from rfauto.service import template_golden_service as tgs

        name = sorted(tgs.TEMPLATE_META)[0]
        d1 = tgs.compute_template_digest(name)
        d2 = tgs.compute_template_digest(name)
        assert d1 == d2 and d1["status"] in ("ok", "guard_blocked", "error")

    def test_monkeypatched_renderer_invalidates(self, monkeypatch):
        """W5-P3-6：monkeypatch render_script（换函数对象）后同键必须失效
        重算——旧键 (template, version, mesh) 无源成分时吃会话内旧值。"""
        from rfauto.service import template_golden_service as tgs

        name = sorted(tgs.TEMPLATE_META)[0]
        d1 = tgs.compute_template_digest(name)
        marker = "stale" if d1.get("status") != "guard_blocked" else "fresh"

        def fake_render(template, params, band, mesh_resolution_mm=0.0):
            raise ValueError(f"probe-guard-{marker}")

        orig = tgs.render_script
        monkeypatch.setattr(tgs, "render_script", fake_render)
        d2 = tgs.compute_template_digest(name)
        assert d2["status"] == "guard_blocked"
        assert d2["guard_error"] == f"probe-guard-{marker}"  # 新函数对象生效
        monkeypatch.setattr(tgs, "render_script", orig)  # 还原（不用 undo()）
        d3 = tgs.compute_template_digest(name)
        assert d3 == d1  # 还原后回到原渲染源（键含源指纹）

    def test_non_value_error_render_lands_error_not_crash(self, monkeypatch):
        """W6-P3-7：渲染期非守卫异常（KeyError）落 status=error 如实登记，
        不裸穿透中断调用方（build/diff 逐族循环）。"""
        from rfauto.service import template_golden_service as tgs

        name = sorted(tgs.TEMPLATE_META)[0]

        def bad_render(template, params, band, mesh_resolution_mm=0.0):
            raise KeyError("probe-render-defect")

        monkeypatch.setattr(tgs, "render_script", bad_render)
        d = tgs.compute_template_digest(name)
        assert d["status"] == "error"
        assert "KeyError" in d["error"] and "probe-render-defect" in d["error"]
        assert d["template"] == name and d["digest_version"] == tgs.DIGEST_VERSION
