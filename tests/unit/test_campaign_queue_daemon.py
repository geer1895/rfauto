"""campaign queue-daemon 常驻执行体单测（2026-10-08，全 fake 零真机零网络）.

覆盖（任务书判据逐条）：
- tick 纯函数判定链：日历窗三态（blocked 不发射不记永久 skip/risk 照发
  落账/open 照发）→ license 预检（PASS 照发/SKIP fail-open/FAIL fail-skip；
  仅 license 消耗面计划默认咨询）→ 发射（单飞逐项，fire-and-forget）；
- 幂等记账：已发射项不重发（按 item_id）；终态（done/partial/aborted/
  launch_failed）永不重发；他人 RUNNING 只观察不接管；
- 状态落盘崩溃续跑：save/load 往返 + schema 不符/损坏=空白档；
- 常驻执行体：--once 单步信封、单例锁防双发射、优雅退出（stop_check）、
  锁释放；
- 发射薄包装：命令构造纯函数 + 真实子进程冒烟（错误计划速败写日志）；
- CLI 接线：campaign queue-daemon --once 双路径（--json 信封/rich 摘要）
  + 注册面。

时钟/日历/预检/队列/发射器全部注入假件（#139：零网络零配置依赖）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from rfauto.service.campaign_queue_daemon import (
    ITEM_ABORTED,
    ITEM_DONE,
    ITEM_EXTERNAL,
    ITEM_LAUNCH_FAILED,
    ITEM_LAUNCHED,
    QUEUE_DAEMON_SCHEMA,
    QUEUE_STATE_FILE,
    _launch_cmd,
    default_queue_state_path,
    item_id_of,
    load_queue_state,
    queue_tick,
    run_queue_daemon,
    save_queue_state,
    scan_queue,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

RUNNER = CliRunner()


# ─── 假件工厂 ────────────────────────────────────────────────────────────────

def _entry(plan_path: str, *, verdict: str = "",
           license_gated: bool = False, model: str = "wilkinson") -> dict:
    return {"item_id": item_id_of(plan_path), "plan_path": plan_path,
            "model": model, "verdict": verdict,
            "n_stages": 2, "license_gated": license_gated}


def _cal(state: str = "open") -> dict:
    return {"loaded": state != "open", "state": state, "launchable":
            state != "blocked", "windows_hit": [state] if state != "open" else [],
            "reason": f"fake calendar {state}"}


def _pf(verdict: str) -> dict:
    return {"ok": verdict != "FAIL", "verdict": verdict,
            "reason": f"fake preflight {verdict}"}


class _Launcher:
    """假发射器：记录调用，返回 pid 计数（或注入失败）。"""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def __call__(self, plan_path: str) -> dict:
        self.calls.append(plan_path)
        if self.fail:
            return dict(ok=False, error="fake launch boom")
        return dict(ok=True, pid=100 + len(self.calls),
                    cmdline=["fake-python"], log_path=plan_path + ".log")


class _Recorder:
    """预检/日历调用计数器（门咨询面断言用）。"""

    def __init__(self, result: dict) -> None:
        self.result = result
        self.n_calls = 0

    def __call__(self, *args) -> dict:
        self.n_calls += 1
        return self.result


# ─── item 身份与状态档 ───────────────────────────────────────────────────────

class TestItemIdAndState:
    def test_item_id_stable_and_distinct(self):
        a = item_id_of(r"E:\x\runs\camp_a")
        assert a == item_id_of(r"E:\x\runs\camp_a")  # 跨重启稳定（幂等键）
        assert a != item_id_of(r"E:\x\runs\camp_b")
        assert len(a) == 12

    def test_default_queue_state_path_double_root(self, tmp_path,
                                                  monkeypatch):
        monkeypatch.chdir(tmp_path)  # 无 runs/ → cwd 根（新工作区语义）
        p = default_queue_state_path()
        assert p == tmp_path / "runs" / "campaign_queue" / QUEUE_STATE_FILE

    def test_state_roundtrip(self, tmp_path):
        sp = tmp_path / "q.json"
        state = {"schema": QUEUE_DAEMON_SCHEMA, "items": {"a": {"s": 1}},
                 "root": "runs"}
        assert save_queue_state(state, sp) == str(sp)
        loaded = load_queue_state(sp)
        assert loaded["items"]["a"] == {"s": 1}
        assert loaded["schema"] == QUEUE_DAEMON_SCHEMA

    def test_state_save_atomic_no_tmp_leftover(self, tmp_path):
        """原子落盘：重复覆盖写不留 .tmp 半写残面（崩溃态不落正式档）。"""
        sp = tmp_path / "q.json"
        for n in range(3):
            state = {"schema": QUEUE_DAEMON_SCHEMA, "items": {"n": n},
                     "root": "runs"}
            save_queue_state(state, sp)
        assert load_queue_state(sp)["items"]["n"] == 2
        assert list(tmp_path.glob("*.tmp")) == []

    def test_state_missing_or_corrupt_or_schema_mismatch_fresh(self, tmp_path):
        assert load_queue_state(tmp_path / "nope.json")["items"] == {}
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert load_queue_state(bad)["schema"] == QUEUE_DAEMON_SCHEMA
        wrong = tmp_path / "wrong.json"
        wrong.write_text(json.dumps({"schema": "v0-old", "items": {}}),
                         encoding="utf-8")
        assert load_queue_state(wrong)["items"] == {}  # 整档弃用重新起步


# ─── scan_queue（真实读盘，离线确定）──────────────────────────────────────────

class TestScanQueue:
    def test_scan_reads_plans_and_license_flag(self, tmp_path):

        from rfauto.service.campaign_manager import save_plan
        monkey_root = tmp_path / "runs"
        d1 = monkey_root / "camp_a"
        d1.mkdir(parents=True)
        save_plan({"model": "m1", "stages": [
            {"stage": "tune", "kind": "tune", "adapter": "openems"}]}, d1)
        d2 = monkey_root / "camp_b"
        d2.mkdir(parents=True)
        save_plan({"model": "m2", "verdict": "COMPLETE", "stages": [
            {"stage": "fv", "kind": "tune", "adapter": "hfss",
             "license_gated": True}]}, d2)
        entries = scan_queue(monkey_root)
        by_model = {e["model"]: e for e in entries}
        assert by_model["m1"]["verdict"] == ""  # 新立计划无 verdict=排队
        assert by_model["m1"]["license_gated"] is False
        assert by_model["m2"]["verdict"] == "COMPLETE"
        assert by_model["m2"]["license_gated"] is True  # adapter=hfss 命中

    def test_scan_skips_broken_plan(self, tmp_path):
        d = tmp_path / "runs" / "camp_bad"
        d.mkdir(parents=True)
        (d / "campaign.plan.json").write_text("{broken", encoding="utf-8")
        assert scan_queue(tmp_path / "runs") == []


# ─── tick 判定链 ─────────────────────────────────────────────────────────────

class TestTickGates:
    def test_launch_first_candidate_open_open(self):
        q = [_entry("runs/camp_a")]
        launch = _Launcher()
        actions, state = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=_Recorder(_pf("PASS")), launcher_fn=launch,
            now_fn=lambda: 1.0)
        kinds = [a["action"] for a in actions]
        assert kinds[0] == "scan" and kinds.count("launch") == 1
        iid = q[0]["item_id"]
        assert state["items"][iid]["status"] == ITEM_LAUNCHED
        assert state["items"][iid]["pid"] == 101
        assert launch.calls == ["runs/camp_a"]

    def test_idempotent_no_relaunch_while_in_flight(self):
        q = [_entry("runs/camp_a")]
        launch = _Launcher()
        _, state1 = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=launch)
        assert len(launch.calls) == 1
        # 第二 tick：同队列同状态 → 在途不重发
        actions, state2 = queue_tick(
            state1, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=launch,
            now_fn=lambda: 2.0)
        assert len(launch.calls) == 1  # 永不重发（幂等记账）
        kinds = [a["action"] for a in actions]
        assert "in_flight_wait" in kinds and "launch" not in kinds
        assert state2["items"][q[0]["item_id"]]["status"] == ITEM_LAUNCHED

    def test_calendar_blocked_no_launch_no_permanent_skip(self):
        q = [_entry("runs/camp_a")]
        launch = _Launcher()
        actions, state = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("blocked"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=launch)
        assert [a["action"] for a in actions] == ["scan", "calendar_blocked"]
        assert launch.calls == []
        assert state["items"] == {}  # 项不记永久 skip（下 tick 重探）
        # 窗开后照发（SKIP=inconclusive 续跑重探同源）
        actions2, _ = queue_tick(
            state, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=launch,
            now_fn=lambda: 2.0)
        assert "launch" in [a["action"] for a in actions2]
        assert len(launch.calls) == 1

    def test_calendar_risk_launches_with_risk_recorded(self):
        q = [_entry("runs/camp_a")]
        actions, state = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("risk"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=_Launcher(),
            now_fn=lambda: 1.0)
        kinds = [a["action"] for a in actions]
        assert "calendar_risk" in kinds and "launch" in kinds
        assert state["items"][q[0]["item_id"]]["status"] == ITEM_LAUNCHED

    def test_license_fail_fail_skip_reprobe(self):
        q = [_entry("runs/camp_a", license_gated=True)]
        launch = _Launcher()
        actions, state = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("FAIL"), launcher_fn=launch)
        kinds = [a["action"] for a in actions]
        assert "license_skip" in kinds and "launch" not in kinds
        assert launch.calls == [] and state["items"] == {}  # 重探不记账
        # 预检转 PASS 后下 tick 照发
        actions2, _ = queue_tick(
            state, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=launch,
            now_fn=lambda: 2.0)
        assert "launch" in [a["action"] for a in actions2]

    def test_license_skip_verdict_fails_open(self):
        # 无登记机器 → verdict=SKIP（守卫自身契约"本地路径不受影响"）→ 照发
        q = [_entry("runs/camp_a", license_gated=True)]
        actions, state = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("SKIP"), launcher_fn=_Launcher())
        assert "license_skip_open" in [a["action"] for a in actions]
        assert state["items"][q[0]["item_id"]]["status"] == ITEM_LAUNCHED

    def test_preflight_not_consulted_without_license_stages(self):
        pre = _Recorder(_pf("FAIL"))  # 若被咨询会 FAIL 拦下——断言不被咨询
        q = [_entry("runs/camp_a", license_gated=False)]
        actions, state = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=pre, launcher_fn=_Launcher())
        assert pre.n_calls == 0  # 非 license 消耗面默认不预检
        assert "launch" in [a["action"] for a in actions]
        assert state["items"]

    def test_explicit_license_gate_forces_preflight(self):
        pre = _Recorder(_pf("PASS"))
        q = [_entry("runs/camp_a", license_gated=False)]
        _, _ = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=pre, launcher_fn=_Launcher(), license_gate=True)
        assert pre.n_calls == 1  # --license-gate 强制全量预检

    def test_no_license_gate_disables_preflight(self):
        pre = _Recorder(_pf("FAIL"))
        q = [_entry("runs/camp_a", license_gated=True)]
        actions, _ = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=pre, launcher_fn=_Launcher(), license_gate=False)
        assert pre.n_calls == 0  # --no-license-gate 一律不预检
        assert "launch" in [a["action"] for a in actions]


class TestTickBookkeeping:
    def test_serial_queue_one_per_tick_until_terminal(self):
        """逐项发射语义：第一项在途时第二项等待；第一项终态后第二项发射。"""
        q1 = [_entry("runs/camp_a"), _entry("runs/camp_b")]
        launch = _Launcher()
        _, s1 = queue_tick(None, queue_fn=lambda root: q1,
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=launch, now_fn=lambda: 1.0)
        assert launch.calls == ["runs/camp_a"]  # 单飞：只发第一项
        _, s2 = queue_tick(s1, queue_fn=lambda root: q1,
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=launch, now_fn=lambda: 2.0)
        assert launch.calls == ["runs/camp_a"]  # 在途等待
        # 第一项 verdict COMPLETE → 刷新终态，第二项上位发射
        q2 = [_entry("runs/camp_a", verdict="COMPLETE"), _entry("runs/camp_b")]
        actions, s3 = queue_tick(s2, queue_fn=lambda root: q2,
                                 calendar_fn=lambda: _cal("open"),
                                 preflight_fn=lambda m: _pf("PASS"),
                                 launcher_fn=launch, now_fn=lambda: 3.0)
        assert launch.calls == ["runs/camp_a", "runs/camp_b"]
        kinds = [a["action"] for a in actions]
        assert kinds.count("refresh_terminal") == 1
        assert kinds.count("launch") == 1
        assert s3["items"][q1[0]["item_id"]]["status"] == ITEM_DONE
        assert s3["items"][q1[1]["item_id"]]["status"] == ITEM_LAUNCHED

    def test_preexisting_terminal_and_external_recorded_not_launched(self):
        q = [_entry("runs/camp_a", verdict="COMPLETE"),
             _entry("runs/camp_b", verdict="ABORTED"),
             _entry("runs/camp_c", verdict="RUNNING"),
             _entry("runs/camp_d")]
        launch = _Launcher()
        actions, state = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=launch,
            now_fn=lambda: 1.0)
        by_kind: dict[str, list] = {}
        for a in actions:
            by_kind.setdefault(a["action"], []).append(a)
        assert len(by_kind.get("record_terminal", [])) == 2  # a+b
        assert len(by_kind.get("observe_external", [])) == 1  # c
        assert len(by_kind.get("launch", [])) == 1  # 只有 d 可发射
        assert launch.calls == ["runs/camp_d"]
        assert state["items"][q[0]["item_id"]]["status"] == ITEM_DONE
        assert state["items"][q[1]["item_id"]]["status"] == ITEM_ABORTED
        assert state["items"][q[2]["item_id"]]["status"] == ITEM_EXTERNAL
        # external 永不接管：第二 tick 零发射
        actions2, _ = queue_tick(state, queue_fn=lambda root: q,
                                 calendar_fn=lambda: _cal("open"),
                                 preflight_fn=lambda m: _pf("PASS"),
                                 launcher_fn=launch, now_fn=lambda: 2.0)
        assert launch.calls == ["runs/camp_d"]
        assert "in_flight_wait" in [a["action"] for a in actions2]

    def test_launch_failure_terminal_no_loop(self):
        q = [_entry("runs/camp_a")]
        launch = _Launcher(fail=True)
        _, state = queue_tick(None, queue_fn=lambda root: q,
                              calendar_fn=lambda: _cal("open"),
                              preflight_fn=lambda m: _pf("PASS"),
                              launcher_fn=launch)
        iid = q[0]["item_id"]
        assert state["items"][iid]["status"] == ITEM_LAUNCH_FAILED
        _, state2 = queue_tick(state, queue_fn=lambda root: q,
                               calendar_fn=lambda: _cal("open"),
                               preflight_fn=lambda m: _pf("PASS"),
                               launcher_fn=_Launcher(), now_fn=lambda: 2.0)
        assert state2["items"][iid]["status"] == ITEM_LAUNCH_FAILED  # 终态不重发

    def test_launched_refreshed_to_done(self):
        q = [_entry("runs/camp_a")]
        _, s1 = queue_tick(None, queue_fn=lambda root: q,
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=_Launcher(), now_fn=lambda: 1.0)
        q_done = [_entry("runs/camp_a", verdict="COMPLETE")]
        actions, s2 = queue_tick(s1, queue_fn=lambda root: q_done,
                                 calendar_fn=lambda: _cal("open"),
                                 preflight_fn=lambda m: _pf("PASS"),
                                 launcher_fn=_Launcher(), now_fn=lambda: 2.0)
        assert "refresh_terminal" in [a["action"] for a in actions]
        assert s2["items"][q[0]["item_id"]]["status"] == ITEM_DONE

    def test_survivor_records_preserved_when_plan_vanishes(self):
        q = [_entry("runs/camp_a")]
        _, s1 = queue_tick(None, queue_fn=lambda root: q,
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=_Launcher())
        # 计划目录整个消失（扫描未命中）——陈账保留不删除不重发
        _, s2 = queue_tick(s1, queue_fn=lambda root: [],
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=_Launcher(), now_fn=lambda: 2.0)
        assert q[0]["item_id"] in s2["items"]

    def test_survivor_in_flight_blocks_launch_no_escape(self):
        """单飞不逃逸：在途账目的计划瞬时不可读（扫描未命中）时，第二项
        不得上位发射（否则在途项隐身一瞬=双战役并发，#261 单飞破约）。"""
        qa, qb = _entry("runs/camp_a"), _entry("runs/camp_b")
        launch = _Launcher()
        _, s1 = queue_tick(None, queue_fn=lambda root: [qa, qb],
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=launch, now_fn=lambda: 1.0)
        assert launch.calls == ["runs/camp_a"]
        # tick2：A 的计划读不到（队列只见 B）——在途陈账照常阻塞
        actions2, s2 = queue_tick(
            s1, queue_fn=lambda root: [qb],
            calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=launch,
            now_fn=lambda: 2.0)
        assert launch.calls == ["runs/camp_a"]  # B 未上位（不逃逸）
        waits = [a for a in actions2 if a["action"] == "in_flight_wait"]
        assert waits and waits[0]["item_id"] == qa["item_id"]
        assert "未命中" in waits[0]["reason"]
        assert s2["items"][qa["item_id"]]["status"] == ITEM_LAUNCHED
        # tick3：A 恢复可见仍在途 → 继续等待
        _, s3 = queue_tick(s2, queue_fn=lambda root: [qa, qb],
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=launch, now_fn=lambda: 3.0)
        assert launch.calls == ["runs/camp_a"]
        # tick4：A 终态 → 刷新 + B 上位（阻塞解除路径不受伤）
        qa_done = _entry("runs/camp_a", verdict="COMPLETE")
        actions4, s4 = queue_tick(
            s3, queue_fn=lambda root: [qa_done, qb],
            calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=launch,
            now_fn=lambda: 4.0)
        assert launch.calls == ["runs/camp_a", "runs/camp_b"]
        kinds = [a["action"] for a in actions4]
        assert kinds.count("refresh_terminal") == 1
        assert kinds.count("launch") == 1
        assert s4["items"][qa["item_id"]]["status"] == ITEM_DONE

    def test_state_input_not_mutated(self):
        q = [_entry("runs/camp_a")]
        prev = {"schema": QUEUE_DAEMON_SCHEMA, "items": {}, "root": "runs"}
        import copy
        snapshot = copy.deepcopy(prev)
        queue_tick(prev, queue_fn=lambda root: q,
                   calendar_fn=lambda: _cal("open"),
                   preflight_fn=lambda m: _pf("PASS"),
                   launcher_fn=_Launcher())
        assert prev == snapshot  # 纯函数：入参不改性


# ─── 常驻执行体 ───────────────────────────────────────────────────────────────

class TestRunDaemon:
    def _fakes(self, queue):
        return dict(queue_fn=lambda root: queue,
                    calendar_fn=lambda: _cal("open"),
                    preflight_fn=lambda m: _pf("PASS"),
                    launcher_fn=_Launcher(), now_fn=lambda: 42.0,
                    sleep_fn=lambda s: None)

    def test_once_mode_single_tick_state_written_lock_released(self, tmp_path):
        sp = tmp_path / "q" / QUEUE_STATE_FILE
        q = [_entry("runs/camp_a")]
        result = run_queue_daemon(once=True, state_path=sp, **self._fakes(q))
        assert result["ok"] is True and result["ticks"] == 1
        assert Path(result["state_path"]).is_file()
        on_disk = load_queue_state(sp)
        assert on_disk["items"][q[0]["item_id"]]["status"] == ITEM_LAUNCHED
        assert not Path(str(sp) + ".lock").exists()  # 锁已释放（干净退出）

    def test_empty_queue_once_ok(self, tmp_path):
        result = run_queue_daemon(once=True, state_path=tmp_path / "q.json",
                                  **self._fakes([]))
        assert result["ok"] is True
        assert result["items"]["n_items"] == 0

    def test_singleton_lock_rejects_second_instance(self, tmp_path):
        from rfauto.pipeline.dag_runner import acquire_lock

        sp = tmp_path / "q.json"
        lock = sp.parent / (sp.name + ".lock")
        assert acquire_lock("other-daemon", lock, max_wait_s=0) is not None
        result = run_queue_daemon(once=True, state_path=sp, **self._fakes([]))
        assert result["ok"] is False
        assert "另一" in " ".join(result.get("errors") or [])
        assert lock.exists()  # 他人锁不动

    def test_stop_check_graceful_exit(self, tmp_path):
        sp = tmp_path / "q.json"
        fakes = self._fakes([])
        fakes["stop_check"] = lambda: True
        result = run_queue_daemon(interval_s=0.1, state_path=sp, **fakes)
        assert result["ok"] is True and result["ticks"] == 1
        assert result["final"].get("stopped_gracefully") is True


# ─── 发射薄包装 ───────────────────────────────────────────────────────────────

class TestLaunchWrapper:
    def test_launch_cmd_shape(self):
        cmd = _launch_cmd(r"E:\x\runs\camp_a\campaign.plan.json")
        assert cmd[1:4] == ["-m", "rfauto.cli.main", "campaign"]
        assert cmd[4:6] == ["run", r"E:\x\runs\camp_a\campaign.plan.json"]
        assert "--resume" in cmd and "--json" in cmd

    def test_launch_subprocess_real_smoke(self, tmp_path):
        """真实子进程冒烟：错误计划速败，stdout 重定向进发射日志（发射后不等）。"""
        from rfauto.service.campaign_queue_daemon import _launch_campaign_subprocess

        plan = tmp_path / "camp_x" / "campaign.plan.json"
        plan.parent.mkdir(parents=True)
        plan.write_text('{"model": "bogus"}', encoding="utf-8")
        res = _launch_campaign_subprocess(str(plan))
        assert res["ok"] is True and isinstance(res["pid"], int)
        log = Path(res["log_path"])
        assert log.is_file()  # 发射即建日志（追加面）
        deadline = 60.0
        waited = 0.0
        import time
        while log.stat().st_size == 0 and waited < deadline:
            time.sleep(0.5)
            waited += 0.5
        assert log.stat().st_size > 0, "子进程 60s 内未写日志（发射链断）"
        body = log.read_text(encoding="utf-8", errors="replace")
        assert "ok" in body  # campaign run --json 错误信封已落日志


# ─── CLI 接线 ────────────────────────────────────────────────────────────────

class TestCli:
    def test_registered_in_campaign_app(self):
        # 公开仓结构：campaign 命令面内联在 bands_uq（无独立 campaign 模块）
        from rfauto.cli.domains import bands_uq

        names = [c.name for c in bands_uq.campaign_app.registered_commands]
        assert "queue-daemon" in names

    def test_bands_uq_reexport_intact(self):
        from rfauto.cli.domains import bands_uq

        assert hasattr(bands_uq, "campaign_app")
        assert hasattr(bands_uq, "campaign_queue_daemon_cmd")

    def test_once_json_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # 空 runs 根：零候选零真机
        sp = tmp_path / "q.json"
        result = RUNNER.invoke(
            __import__("rfauto.cli.main", fromlist=["app"]).app,
            ["campaign", "queue-daemon", "--once", "--json",
             "--state-path", str(sp)])
        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["ok"] is True
        assert envelope["ticks"] == 1
        assert envelope["items"]["n_items"] == 0
        assert sp.is_file()

    def test_once_json_failure_envelope_singleton(self, tmp_path):
        from rfauto.pipeline.dag_runner import acquire_lock

        sp = tmp_path / "q.json"
        acquire_lock("other", sp.parent / (sp.name + ".lock"), max_wait_s=0)
        result = RUNNER.invoke(
            __import__("rfauto.cli.main", fromlist=["app"]).app,
            ["campaign", "queue-daemon", "--once", "--json",
             "--state-path", str(sp)])
        assert result.exit_code == 1
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["errors"]

    def test_once_text_summary(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = RUNNER.invoke(
            __import__("rfauto.cli.main", fromlist=["app"]).app,
            ["campaign", "queue-daemon", "--once",
             "--state-path", str(tmp_path / "q.json")])
        assert result.exit_code == 0, result.output
        assert "queue-daemon 退出" in result.output
        assert "scan" in result.output  # 末 tick 动作词表可见

    def test_json_flag_present_for_ratchet(self):
        # JSON 覆盖棘轮同款探针口径：参数名含 json 即计
        import inspect

        from rfauto.cli.domains import bands_uq

        sig = inspect.signature(bands_uq.campaign_queue_daemon_cmd)
        assert any("json" in p for p in sig.parameters)


# ─── tick 观测行 markup 安全（ge8e 审查批回归钉）─────────────────────────────

class TestTickLineMarkupSafety:
    """常驻逐 tick 输出面禁 rich markup 吞字。

    payload 动态字符串含 "[...]" 形态（plan 路径 runs/[debug]x、reason
    窗口[wm]）时，console.print 缺省 markup 解析会把方括号段当样式标签
    整段静默吞掉——JSON 行流被截改（机器消费方拿到失真数据）、人读行
    "[queue-daemon]" 前缀自身也被当未知标签吞掉。钉住：--json 逐 tick
    单行 JSON 逐字节保真（markup=False）；人读行前缀与动作段字面可见。
    """

    @staticmethod
    def _run_with_tick(monkeypatch, tmp_path, json_output: bool):
        import rfauto.cli.main as main_mod
        import rfauto.service.campaign_queue_daemon as qd_mod

        payload = {"tick": 1,
                   "actions": [{"action": "skip", "plan": "runs/[debug]x",
                                "reason": "窗口[wm]未开"}]}
        seen: list = []

        def _fake_run(*, log=None, **kwargs):
            seen.append(kwargs.get("once"))
            if log is not None:
                log(payload)
            return {"ok": True, "ticks": 1,
                    "items": {"n_items": 1, "in_flight": 0},
                    "state_path": str(kwargs.get("state_path")),
                    "final": {"actions": []}}

        monkeypatch.setattr(qd_mod, "run_queue_daemon", _fake_run)
        argv = ["campaign", "queue-daemon",
                "--state-path", str(tmp_path / "q.json")]
        if json_output:
            argv.append("--json")
        result = RUNNER.invoke(main_mod.app, argv)
        assert result.exit_code == 0, result.output
        assert seen == [False]  # 常驻模式才挂 log（--once 走 log=None）
        return result.output

    def test_json_tick_stream_brackets_survive(self, tmp_path, monkeypatch):
        out = self._run_with_tick(monkeypatch, tmp_path, json_output=True)
        tick_lines = [ln for ln in out.splitlines() if '"tick": 1' in ln]
        assert len(tick_lines) == 1
        payload = json.loads(tick_lines[0])  # 行流仍合法 JSON（未截改）
        assert payload["actions"][0]["plan"] == "runs/[debug]x"
        assert payload["actions"][0]["reason"] == "窗口[wm]未开"

    def test_human_tick_line_prefix_and_brackets_visible(
            self, tmp_path, monkeypatch):
        # 人读分支=动作词表（plan/reason 只在 --json 行流承载）；前缀
        # "[queue-daemon]" 须字面可见（不被当未知样式标签整段吞掉）
        out = self._run_with_tick(monkeypatch, tmp_path, json_output=False)
        assert "[queue-daemon]" in out
        assert "tick=1" in out
        assert "['skip']" in out
