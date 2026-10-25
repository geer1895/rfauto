"""W2-S3 失败诊断包服务单测（aurora_i 采纳 #3，全 fake 零网络零真机）.

覆盖（任务书判据逐条）：
- 聚合面：结局面（plan verdict/失败 stage/events 终态事件）+ 机器实况面
  （注入 fake probe）+ license 面（注入 fake preflight）+ 日志尾面；
- 聚合判定：全绿 OK / 单面败 PARTIAL / 全败 FAILED（diagnosis_service
  run_diagnosis 同款聚合口径）；采集面异常降级不抛；
- 日志尾 N 行 + 超长行截断；exit_code/error 参数在档即录；
- 落包/读包：原子写（无 .tmp 残留）、幂等覆盖、schema 版本门、
  safe_run_id 路径段守卫、缺包 exists=False 如实。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rfauto.service.failure_context_service import (
    FAILURE_CONTEXT_FILE,
    FAILURE_CONTEXT_SCHEMA,
    LOG_TAIL_LINES_DEFAULT,
    build_failure_context,
    failure_context_path,
    read_failure_context,
    write_failure_context,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


def _fake_probe(reachable: bool = True, n_machines: int = 1):
    def _probe(machine=None):
        machines = [{"name": "sim_server", "host": "10.0.0.8",
                     "reachable": reachable,
                     "ports": {"ansys_license": {"port": 1055,
                                                 "open": reachable,
                                                 "latency_ms": 1.5}},
                     "probe_s": 0.01} for _ in range(n_machines)]
        return {"ok": True, "machines": machines}

    return _probe


def _fake_preflight(verdict: str = "PASS", reason: str | None = None):
    def _pf(machine=None):
        out = {"ok": verdict == "PASS", "verdict": verdict,
               "reason": reason, "machine": "sim_server" if verdict != "SKIP"
               else None,
               "gate": {"kind": "tcp_license_ports",
                        "all_open": verdict == "PASS", "closed": []}}
        if verdict == "SKIP":
            out["skipped"] = True  # 无登记机器=SKIP（license_preflight 契约）
        return out

    return _pf


def _make_run_dir(tmp_path: Path, *, verdict: str = "ABORTED",
                  with_events: bool = True) -> Path:
    d = tmp_path / "runs" / "camp_dead"
    d.mkdir(parents=True)
    plan = {"model": "wilkinson", "verdict": verdict,
            "stages": [
                {"stage": "calibrate", "status": "done"},
                {"stage": "final_verify", "status": "failed"},
                {"stage": "report", "status": "aborted"}]}
    (d / "campaign.plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    if with_events:
        lines = [
            json.dumps({"event_type": "progress", "message": "stage 1/3"}),
            json.dumps({"event_type": "run_failed",
                        "message": "stage final_verify failed",
                        "data": {"error": "HFSS solve exit=-1073741819"}}),
        ]
        (d / "events.jsonl").write_text("\n".join(lines) + "\n",
                                        encoding="utf-8")
    return d


class TestBuildFailureContext:
    def test_full_snapshot_sections(self, tmp_path):
        d = _make_run_dir(tmp_path)
        ctx = build_failure_context(
            d, probe_fn=_fake_probe(), preflight_fn=_fake_preflight("FAIL",
                                                                    "端口不可达"),
            exit_code=-1073741819, error="fake boom", now_fn=lambda: 1000.0)
        assert ctx["schema"] == FAILURE_CONTEXT_SCHEMA
        assert ctx["verdict"] == "OK" and ctx["ok"] is True
        assert ctx["captured_epoch"] == 1000.0
        ex = ctx["exit"]
        assert ex["exit_code"] == -1073741819 and ex["error"] == "fake boom"
        oc = ex["outcome"]
        assert oc["ok"] is True and oc["verdict"] == "ABORTED"
        assert oc["failed_stages"] == ["final_verify", "report"]
        assert oc["n_done"] == 1
        assert oc["terminal_event"]["error"] == "HFSS solve exit=-1073741819"
        mac = ctx["machine"]
        assert mac["ok"] is True and mac["reachable"] is True
        assert mac["ports"]["ansys_license"]["port"] == 1055
        lic = ctx["license"]
        assert lic["verdict"] == "FAIL" and lic["reason"] == "端口不可达"
        assert [f["file"] for f in ctx["logs"]["files"]] == [
            "queue_daemon_launch.log", "events.jsonl"]

    def test_no_registered_machine_skips_not_fails(self, tmp_path):
        d = _make_run_dir(tmp_path)
        ctx = build_failure_context(
            d, probe_fn=_fake_probe(n_machines=0),
            preflight_fn=_fake_preflight("SKIP"), now_fn=lambda: 1.0)
        assert ctx["machine"]["skipped"] is True
        assert ctx["machine"]["ok"] is True
        assert ctx["license"]["skipped"] is True
        assert ctx["verdict"] == "OK"

    def test_probe_exception_degrades_to_partial(self, tmp_path):
        d = _make_run_dir(tmp_path)

        def _boom(machine=None):
            raise RuntimeError("net down")

        ctx = build_failure_context(
            d, probe_fn=_boom, preflight_fn=_fake_preflight(),
            now_fn=lambda: 1.0)
        assert ctx["machine"]["ok"] is False
        assert "RuntimeError" in ctx["machine"]["error"]
        assert ctx["verdict"] == "PARTIAL" and ctx["ok"] is True

    def test_all_sections_failed_verdict_failed(self, tmp_path):
        d = tmp_path / "runs" / "empty_dir"  # 无 plan 无 events
        d.mkdir(parents=True)

        def _boom(machine=None):
            raise OSError("down")

        ctx = build_failure_context(
            d, probe_fn=_boom, preflight_fn=_boom, now_fn=lambda: 1.0)
        assert ctx["verdict"] == "FAILED" and ctx["ok"] is False

    def test_log_tail_lines_and_truncation(self, tmp_path):
        d = _make_run_dir(tmp_path)
        (d / "queue_daemon_launch.log").write_text(
            "\n".join(f"line {i}" for i in range(50)) + "\n"
            + "x" * 2000 + "\n", encoding="utf-8")
        ctx = build_failure_context(d, tail_lines=10,
                                    probe_fn=_fake_probe(n_machines=0),
                                    preflight_fn=_fake_preflight("SKIP"),
                                    now_fn=lambda: 1.0)
        launch = next(f for f in ctx["logs"]["files"]
                      if f["file"] == "queue_daemon_launch.log")
        assert launch["exists"] is True
        assert len(launch["tail"]) == 10
        assert launch["tail"][0] == "line 41"  # 51 行（含超长行）尾窗 10 行
        assert launch["tail"][-1] == "x" * 500  # 超长行截断
        assert ctx["logs"]["tail_lines"] == 10

    def test_missing_logs_recorded_exists_false(self, tmp_path):
        d = _make_run_dir(tmp_path, with_events=False)
        ctx = build_failure_context(d, probe_fn=_fake_probe(n_machines=0),
                                    preflight_fn=_fake_preflight("SKIP"),
                                    now_fn=lambda: 1.0)
        assert all(not f["exists"] for f in ctx["logs"]["files"])
        assert ctx["verdict"] == "OK"  # 日志缺席合法（不进聚合判定）

    def test_default_tail_lines_constant(self):
        assert LOG_TAIL_LINES_DEFAULT == 40


class TestWriteAndRead:
    def test_write_then_read_roundtrip(self, tmp_path):
        d = _make_run_dir(tmp_path)
        res = write_failure_context(
            d, probe_fn=_fake_probe(), preflight_fn=_fake_preflight(),
            now_fn=lambda: 1.0)
        assert res["ok"] is True and res["verdict"] == "OK"
        assert Path(res["path"]).is_file()
        assert not list(d.glob("*.tmp"))  # 原子写无半写残面
        back = read_failure_context(run_dir=d)
        assert back["ok"] is True and back["exists"] is True
        assert back["context"]["schema"] == FAILURE_CONTEXT_SCHEMA
        assert back["run_id"] == "camp_dead"

    def test_write_idempotent_overwrite(self, tmp_path):
        d = _make_run_dir(tmp_path)
        kw = dict(probe_fn=_fake_probe(n_machines=0),
                  preflight_fn=_fake_preflight("SKIP"), now_fn=lambda: 1.0)
        write_failure_context(d, **kw)
        write_failure_context(d, **kw)
        back = read_failure_context(run_dir=d)
        assert back["exists"] is True

    def test_write_missing_dir_error_envelope(self, tmp_path):
        res = write_failure_context(tmp_path / "nope")
        assert res["ok"] is False and res["errors"]
        assert res.get("path") is None

    def test_read_missing_context_exists_false(self, tmp_path):
        d = _make_run_dir(tmp_path)
        back = read_failure_context(run_dir=d)
        assert back["ok"] is True and back["exists"] is False

    def test_read_nonexistent_run_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs").mkdir()
        back = read_failure_context("ghost_run")
        assert back["ok"] is False and back["exists"] is False

    def test_read_traversal_run_id_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs").mkdir()
        back = read_failure_context("..")
        assert back["ok"] is False
        back2 = read_failure_context("a..b")
        assert back2["ok"] is False

    def test_read_by_run_id_resolves_runs_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # runs 根=tmp/runs（双根收敛 cwd 优先）
        d = _make_run_dir(tmp_path)
        write_failure_context(d, probe_fn=_fake_probe(n_machines=0),
                              preflight_fn=_fake_preflight("SKIP"),
                              now_fn=lambda: 1.0)
        back = read_failure_context("camp_dead")
        assert back["ok"] is True and back["exists"] is True
        assert back["context"]["exit"]["outcome"]["verdict"] == "ABORTED"

    def test_read_corrupt_context_error(self, tmp_path):
        d = _make_run_dir(tmp_path)
        failure_context_path(d).write_text("{broken", encoding="utf-8")
        back = read_failure_context(run_dir=d)
        assert back["ok"] is False and back["exists"] is True

    def test_read_schema_mismatch_error(self, tmp_path):
        d = _make_run_dir(tmp_path)
        failure_context_path(d).write_text(
            json.dumps({"schema": "v0-old"}), encoding="utf-8")
        back = read_failure_context(run_dir=d)
        assert back["ok"] is False and FAILURE_CONTEXT_SCHEMA in back["errors"][0]

    def test_failure_context_path_shape(self, tmp_path):
        p = failure_context_path(tmp_path)
        assert p == tmp_path / FAILURE_CONTEXT_FILE
        assert FAILURE_CONTEXT_FILE == "failure_context.json"


class TestDaemonIntegration:
    def test_daemon_failure_context_fn_real_writer_smoke(self, tmp_path,
                                                         monkeypatch):
        """生产缝冒烟：run_queue_daemon 缺省接真包——发射失败路径落
        failure_context.json（零网络：monkeypatch 采集生产缝为 fake）。"""
        from rfauto.service import failure_context_service as fcs
        from rfauto.service.campaign_queue_daemon import (
            QUEUE_STATE_FILE,
            run_queue_daemon,
        )

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(fcs, "_default_probe", _fake_probe(n_machines=0))
        monkeypatch.setattr(fcs, "_default_preflight",
                            _fake_preflight("SKIP"))
        plan_dir = tmp_path / "runs" / "camp_x"
        plan_dir.mkdir(parents=True)
        (plan_dir / "campaign.plan.json").write_text(
            json.dumps({"model": "bogus", "verdict": "ABORTED",
                        "stages": [{"stage": "tune", "status": "failed"}]}),
            encoding="utf-8")
        entry = {"item_id": "deadbeef01", "plan_path":
                 str(plan_dir / "campaign.plan.json"),
                 "model": "bogus", "verdict": "", "n_stages": 0,
                 "license_gated": False}

        def _fail_launch(plan_path):
            return dict(ok=False, error="fake launch boom")

        result = run_queue_daemon(
            once=True, state_path=tmp_path / "q" / QUEUE_STATE_FILE,
            queue_fn=lambda root: [entry],
            calendar_fn=lambda: {"loaded": False, "state": "open",
                                 "launchable": True, "windows_hit": [],
                                 "reason": ""},
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            launcher_fn=_fail_launch,
            sleep_fn=lambda s: None, now_fn=lambda: 42.0)
        assert result["ok"] is True
        ctx = read_failure_context(run_dir=plan_dir)
        assert ctx["ok"] is True and ctx["exists"] is True
        assert ctx["context"]["exit"]["outcome"]["ok"] is True
