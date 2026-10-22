"""W3-S3 长跑防卡死对冲单测（aurora_i 服务器管控采纳 #1，全 fake 零网络零真机）.

覆盖（任务书判据逐条）：
- **缺省关闭=零行为变化（硬验收）**：env 未设/非法/≤0 → 对冲代码路径整体
  不进（探针零调用、动作零 hedge_*、状态档零新字段）；
- 配置解析：显式参数 > env > 缺省关（显式 ≤0 压过 env；重发开关词表
  1/true/yes/on 大小写不敏感）；
- 阈值触发链（合成时钟）：无进展 ≥ 阈值 → hedge_alert+hedge 账（变化才
  落账：同因不刷屏、since 稳定）；无进展 < 阈值不告警；探针无证据/异常
  =unknown 保守不告警；进展恢复摘账 hedge_recovered；终态随态清扫；
- 开关重发链：缺省只告警零重发；显式开 → hedge_relaunch 同 plan 一次
  （单飞位保持、pid 换新、hedge_attempts 落账）；重发失败项不终态化且
  尝试烧帽；帽=1 再停滞只告警不重发；
- 读侧：queue_hedge_index（仅 launched 带账）+ /api/campaign_queue
  ``queue_hedge`` 透出（关=无字段零变化）；
- 缺省进展探针：计划文件+发射日志 max mtime；全缺=None。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from rfauto.service.campaign_queue_daemon import (
    HEDGE_CODE_STALL,
    HEDGE_RELAUNCH_ENV,
    HEDGE_STALL_S_ENV,
    ITEM_DONE,
    ITEM_LAUNCHED,
    default_progress_ts,
    env_hedge_relaunch,
    env_hedge_stall_s,
    hedge_text_of,
    item_id_of,
    queue_hedge_index,
    queue_tick,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

_PLAN_A = r"E:\x\runs\camp_a\campaign.plan.json"


@pytest.fixture(autouse=True)
def _clean_hedge_env(monkeypatch):
    """清空对冲配置整个 env 集合（缺省口径=关；同名前缀全清纪律）。"""
    monkeypatch.delenv(HEDGE_STALL_S_ENV, raising=False)
    monkeypatch.delenv(HEDGE_RELAUNCH_ENV, raising=False)


# ─── 假件工厂（test_campaign_queue_daemon 同款口径）─────────────────────────

def _entry(plan_path: str, *, verdict: str = "",
           license_gated: bool = False, model: str = "wilkinson") -> dict:
    return {"item_id": item_id_of(plan_path), "plan_path": plan_path,
            "model": model, "verdict": verdict,
            "n_stages": 2, "license_gated": license_gated}


def _cal(state: str = "open") -> dict:
    return {"loaded": state != "open", "state": state, "launchable":
            state != "blocked", "windows_hit": [state] if state != "open" else [],
            "reason": f"fake calendar {state}"}


class _Launcher:
    """假发射器：记录调用，返回 pid 计数（或注入失败）。

    ``fail=True`` 全部调用失败；``fail_from=N`` 第 N 次（0 起）调用起失败
    （首发成功+重发失败场景用）。
    """

    def __init__(self, fail: bool = False, fail_from: int | None = None) -> None:
        self.calls: list[str] = []
        self.fail = fail
        self.fail_from = fail_from

    def __call__(self, plan_path: str) -> dict:
        idx = len(self.calls)
        self.calls.append(plan_path)
        if self.fail or (self.fail_from is not None and idx >= self.fail_from):
            return dict(ok=False, error="fake launch boom")
        return dict(ok=True, pid=100 + len(self.calls),
                    cmdline=["fake-python"], log_path=plan_path + ".log")


def _counting_probe(ts: float | None):
    """进展探针假件：返回定值（None=无证据）并计数（零调用断言用）。"""
    calls = {"n": 0}

    def probe(plan_path: str) -> float | None:
        calls["n"] += 1
        return ts

    probe.calls = calls  # type: ignore[attr-defined]
    return probe


def _drive_two_ticks(*, t1: float = 100.0, t2: float = 1000.0,
                     progress_ts: float | None = None,
                     probe_raises: bool = False,
                     launcher: _Launcher | None = None,
                     **hedge_kwargs) -> tuple[list[dict], dict, _Launcher]:
    """两 tick 驱动：T1 发射 → T2 在途（verdict=RUNNING）进门对冲判定。

    progress_ts/probe_raises 二选一作 T2 进展探针（缺省 None=无证据）。
    """
    launcher = launcher or _Launcher()
    entry1 = _entry(_PLAN_A)

    _, state = queue_tick(
        None, now_fn=lambda: t1, calendar_fn=lambda: _cal(),
        preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
        queue_fn=lambda root: [entry1], launcher_fn=launcher,
        failure_context_fn=None)
    assert any(a.get("action") == "launch"
               for a in state["last_actions"])

    entry2 = _entry(_PLAN_A, verdict="RUNNING")

    if probe_raises:
        def probe(plan_path: str) -> float | None:
            raise RuntimeError("probe boom")
    else:
        probe = _counting_probe(progress_ts)
    actions, state = queue_tick(
        state, now_fn=lambda: t2, calendar_fn=lambda: _cal(),
        preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
        queue_fn=lambda root: [entry2], launcher_fn=launcher,
        failure_context_fn=None, progress_fn=probe,
        **hedge_kwargs)
    return actions, state, launcher


def _hedge_actions(actions: list[dict]) -> list[dict]:
    return [a for a in actions if str(a.get("action", "")).startswith("hedge")]


# ─── 配置解析（env 词表 + 显式参数优先级）────────────────────────────────────

class TestHedgeCfg:
    def test_env_stall_unset_empty_invalid_nonpositive_all_disabled(self,
                                                                    monkeypatch):
        for raw in (None, "", "   ", "abc", "0", "-5", "1e-9x"):
            if raw is None:
                monkeypatch.delenv(HEDGE_STALL_S_ENV, raising=False)
            else:
                monkeypatch.setenv(HEDGE_STALL_S_ENV, raw)
            assert env_hedge_stall_s() is None, raw

    def test_env_stall_valid_values(self, monkeypatch):
        monkeypatch.setenv(HEDGE_STALL_S_ENV, "3600")
        assert env_hedge_stall_s() == 3600.0
        monkeypatch.setenv(HEDGE_STALL_S_ENV, " 12.5 ")
        assert env_hedge_stall_s() == 12.5

    def test_env_relaunch_wordlist_case_insensitive(self, monkeypatch):
        assert env_hedge_relaunch() is False  # 缺省=只告警
        for raw in ("1", "true", "TRUE", "Yes", "on", " on "):
            monkeypatch.setenv(HEDGE_RELAUNCH_ENV, raw)
            assert env_hedge_relaunch() is True, raw
        for raw in ("0", "false", "garbage", ""):
            monkeypatch.setenv(HEDGE_RELAUNCH_ENV, raw)
            assert env_hedge_relaunch() is False, raw

    def test_explicit_params_override_env(self, monkeypatch):
        monkeypatch.setenv(HEDGE_STALL_S_ENV, "9999")
        monkeypatch.setenv(HEDGE_RELAUNCH_ENV, "1")
        from rfauto.service.campaign_queue_daemon import _resolve_hedge_cfg
        # 显式 ≤0=显式关（压过 env）；显式 True/False 各自压过 env
        assert _resolve_hedge_cfg(0.0, None) == (None, True)
        assert _resolve_hedge_cfg(-1.0, None) == (None, True)
        assert _resolve_hedge_cfg(None, False) == (9999.0, False)
        monkeypatch.delenv(HEDGE_STALL_S_ENV, raising=False)
        monkeypatch.delenv(HEDGE_RELAUNCH_ENV, raising=False)
        assert _resolve_hedge_cfg(5.0, True) == (5.0, True)
        assert _resolve_hedge_cfg(None, None) == (None, False)  # 双缺省=关


# ─── 缺省关闭=零行为变化（硬验收）────────────────────────────────────────────

_BASE_RECORD_KEYS = {"item_id", "plan_path", "model", "status", "launched_at",
                     "pid", "log_path", "verdict_seen", "reason", "updated_at"}


class TestDefaultOff:
    def test_disabled_zero_probe_calls_zero_actions_zero_fields(self):
        # 进展证据极端陈旧（ts=0.0）也不触发——对冲代码路径整体不进
        launcher = _Launcher()
        e1 = _entry(_PLAN_A)
        _, state = queue_tick(
            None, now_fn=lambda: 100.0, calendar_fn=lambda: _cal(),
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [e1], launcher_fn=launcher,
            failure_context_fn=None)
        e2 = _entry(_PLAN_A, verdict="RUNNING")
        probe = _counting_probe(0.0)
        actions, state = queue_tick(
            state, now_fn=lambda: 1000.0, calendar_fn=lambda: _cal(),
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [e2], launcher_fn=launcher,
            failure_context_fn=None, progress_fn=probe)
        assert probe.calls["n"] == 0  # 探针零调用
        assert _hedge_actions(actions) == []  # 动作零 hedge_*
        rec = state["items"][item_id_of(_PLAN_A)]
        assert rec["status"] == ITEM_LAUNCHED  # 在途照旧
        assert "hedge" not in rec and "hedge_attempts" not in rec
        assert set(rec.keys()) == _BASE_RECORD_KEYS  # 状态档零新字段
        assert queue_hedge_index(state) == {}

    def test_env_garbage_stays_disabled(self, monkeypatch):
        monkeypatch.setenv(HEDGE_STALL_S_ENV, "not-a-number")
        probe = _counting_probe(0.0)
        e1 = _entry(_PLAN_A)
        _, state = queue_tick(
            None, now_fn=lambda: 100.0, calendar_fn=lambda: _cal(),
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [e1], launcher_fn=_Launcher(),
            failure_context_fn=None)
        e2 = _entry(_PLAN_A, verdict="RUNNING")
        actions, state = queue_tick(
            state, now_fn=lambda: 1000.0, calendar_fn=lambda: _cal(),
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [e2], launcher_fn=_Launcher(),
            failure_context_fn=None, progress_fn=probe)
        assert probe.calls["n"] == 0
        assert _hedge_actions(actions) == []


# ─── 阈值触发链（合成时钟；缺省动作=只告警）─────────────────────────────────

class TestStallAlert:
    def test_threshold_triggers_alert_and_hedge_ledger(self):
        # T2=1000，最后进展=850，阈值 100 → 停滞 150 ≥ 100 触发
        actions, state, launcher = _drive_two_ticks(
            progress_ts=850.0, hedge_stall_s=100.0)
        alerts = [a for a in actions if a.get("action") == "hedge_alert"]
        assert len(alerts) == 1
        assert alerts[0]["item_id"] == item_id_of(_PLAN_A)
        assert alerts[0]["stalled_s"] == 150.0
        assert alerts[0]["threshold_s"] == 100.0
        assert "疑似停滞" in alerts[0]["reason"]
        rec = state["items"][item_id_of(_PLAN_A)]
        assert rec["status"] == ITEM_LAUNCHED  # 只告警不换态
        hedge = rec["hedge"]
        assert hedge["code"] == HEDGE_CODE_STALL
        assert hedge["since"] == 1000.0  # 首次检出时刻
        assert hedge["last_progress"] == 850.0
        assert hedge["attempts"] == 0
        assert launcher.calls == [_PLAN_A]  # 缺省零重发
        # 读侧透出
        idx = queue_hedge_index(state)
        assert set(idx) == {item_id_of(_PLAN_A)}
        blk = idx[item_id_of(_PLAN_A)]
        assert blk["code"] == HEDGE_CODE_STALL
        assert "疑似停滞" in blk["text"] and "已停滞" in blk["text"]

    def test_below_threshold_no_alert(self):
        actions, state, _ = _drive_two_ticks(
            progress_ts=950.0, hedge_stall_s=100.0)  # 停滞 50 < 100
        assert _hedge_actions(actions) == []
        assert "hedge" not in state["items"][item_id_of(_PLAN_A)]

    def test_no_evidence_and_probe_error_conservative(self):
        # 无证据（None）与探针异常都=unknown，不判停滞不告警不炸 tick
        for kw in ({"progress_ts": None}, {"probe_raises": True}):
            actions, state, _ = _drive_two_ticks(
                hedge_stall_s=100.0, **kw)
            assert _hedge_actions(actions) == [], kw
            assert "hedge" not in state["items"][item_id_of(_PLAN_A)], kw

    def test_same_cause_no_respam_since_stable(self):
        actions1, state1, _ = _drive_two_ticks(
            progress_ts=850.0, hedge_stall_s=100.0)
        assert len([a for a in actions1
                    if a.get("action") == "hedge_alert"]) == 1
        # T3 仍停滞（同因）：不刷屏，since 保持首次检出
        e3 = _entry(_PLAN_A, verdict="RUNNING")
        actions3, state3 = queue_tick(
            state1, now_fn=lambda: 2000.0, calendar_fn=lambda: _cal(),
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [e3], launcher_fn=_Launcher(),
            failure_context_fn=None, hedge_stall_s=100.0,
            progress_fn=_counting_probe(850.0))
        assert [a for a in actions3
                if a.get("action") == "hedge_alert"] == []
        hedge = state3["items"][item_id_of(_PLAN_A)]["hedge"]
        assert hedge["since"] == 1000.0  # 稳定
        # 读侧停滞时长随真实读时推进（即时计算，状态档零冗余）
        blk = queue_hedge_index(state3, now=2600.0)[item_id_of(_PLAN_A)]
        assert blk["stalled_s"] == 1600.0

    def test_recovery_pops_ledger_and_records_action(self):
        _, state1, _ = _drive_two_ticks(
            progress_ts=850.0, hedge_stall_s=100.0)
        # T3 进展恢复（mtime 推进到 1950，停滞 50 < 100）
        e3 = _entry(_PLAN_A, verdict="RUNNING")
        actions3, state3 = queue_tick(
            state1, now_fn=lambda: 2000.0, calendar_fn=lambda: _cal(),
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [e3], launcher_fn=_Launcher(),
            failure_context_fn=None, hedge_stall_s=100.0,
            progress_fn=_counting_probe(1950.0))
        recovered = [a for a in actions3
                     if a.get("action") == "hedge_recovered"]
        assert len(recovered) == 1
        assert "hedge" not in state3["items"][item_id_of(_PLAN_A)]
        assert queue_hedge_index(state3) == {}

    def test_terminal_readback_sweeps_hedge(self):
        _, state1, _ = _drive_two_ticks(
            progress_ts=850.0, hedge_stall_s=100.0)
        iid = item_id_of(_PLAN_A)
        assert state1["items"][iid]["hedge"]["code"] == HEDGE_CODE_STALL
        # 终态回读：对冲账随态清扫
        e3 = _entry(_PLAN_A, verdict="COMPLETE")
        _actions3, state3 = queue_tick(
            state1, now_fn=lambda: 2000.0, calendar_fn=lambda: _cal(),
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [e3], launcher_fn=_Launcher(),
            failure_context_fn=None, hedge_stall_s=100.0)
        rec = state3["items"][iid]
        assert rec["status"] == ITEM_DONE
        assert "hedge" not in rec
        assert queue_hedge_index(state3) == {}

    def test_hedge_index_ignores_non_launched_records(self):
        # 读侧双保险：非在途态即使残留账面也不入索引
        iid = item_id_of(_PLAN_A)
        state = {"items": {iid: {
            "item_id": iid, "status": ITEM_DONE,
            "hedge": {"code": HEDGE_CODE_STALL, "since": 1.0,
                      "attempts": 0}}},
            "schema": "x"}
        assert queue_hedge_index(state, now=100.0) == {}

    def test_hedge_text_of_shapes(self):
        assert "疑似停滞" in hedge_text_of(HEDGE_CODE_STALL)
        assert "已停滞 30 秒" in hedge_text_of(
            HEDGE_CODE_STALL, stalled_s=30.0)
        assert "已停滞 2 分钟" in hedge_text_of(
            HEDGE_CODE_STALL, stalled_s=150.0)
        assert "已对冲重发 1 次" in hedge_text_of(
            HEDGE_CODE_STALL, attempts=1)
        assert hedge_text_of("unknown-code") == ""  # 未知码空串不猜


# ─── 开关重发链（显式开关；帽=1；缺省只告警）────────────────────────────────

class TestRelaunchSwitch:
    def test_default_alert_only_never_relaunches(self):
        env_relaunch_off = None  # 双缺省
        actions, state, launcher = _drive_two_ticks(
            progress_ts=0.0, hedge_stall_s=1.0,
            hedge_relaunch=env_relaunch_off)
        assert [a for a in actions if a.get("action") == "hedge_alert"]
        assert launcher.calls == [_PLAN_A]  # 只有首发一次
        rec = state["items"][item_id_of(_PLAN_A)]
        assert rec["status"] == ITEM_LAUNCHED
        assert rec["hedge"]["attempts"] == 0

    def test_relaunch_fires_once_updates_pid_keeps_single_flight(self):
        actions, state, launcher = _drive_two_ticks(
            progress_ts=0.0, hedge_stall_s=1.0, hedge_relaunch=True)
        rels = [a for a in actions if a.get("action") == "hedge_relaunch"]
        assert len(rels) == 1
        assert rels[0]["plan"] == _PLAN_A
        assert rels[0]["attempt"] == 1
        assert launcher.calls == [_PLAN_A, _PLAN_A]  # 首发+对冲重发一次
        rec = state["items"][item_id_of(_PLAN_A)]
        assert rec["status"] == ITEM_LAUNCHED  # 单飞位保持（不双开）
        assert rec["pid"] == 102  # 新发射 pid（launcher 计数第 2 次）
        assert rec["hedge_attempts"] == 1  # 尝试落账
        assert rec["hedge"]["attempts"] == 1
        assert rec["hedge"]["relaunched_at"] == 1000.0
        assert "对冲重发" in rec["reason"]

    def test_relaunch_failure_keeps_launched_and_burns_cap(self):
        # 首发成功+重发失败（fail_from=1）：项不终态化，尝试烧帽
        actions, state, _ = _drive_two_ticks(
            progress_ts=0.0, hedge_stall_s=1.0, hedge_relaunch=True,
            launcher=_Launcher(fail_from=1))
        fails = [a for a in actions
                 if a.get("action") == "hedge_relaunch_failed"]
        assert len(fails) == 1 and "fake launch boom" in fails[0]["error"]
        rec = state["items"][item_id_of(_PLAN_A)]
        assert rec["status"] == ITEM_LAUNCHED  # 不终态化（原进程可能仍活）
        assert rec["hedge_attempts"] == 1  # 失败也烧帽（防锁拒循环拉起）
        # T3 仍停滞：帽已烧+同因不刷屏——零重发零新告警
        e3 = _entry(_PLAN_A, verdict="RUNNING")
        launcher3 = _Launcher()
        actions3, _ = queue_tick(
            state, now_fn=lambda: 2000.0, calendar_fn=lambda: _cal(),
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [e3], launcher_fn=launcher3,
            failure_context_fn=None, hedge_stall_s=1.0,
            hedge_relaunch=True, progress_fn=_counting_probe(0.0))
        assert launcher3.calls == []  # 零新发射
        assert _hedge_actions(actions3) == []

    def test_cap_one_blocks_second_relaunch_after_recovery_restall(self):
        _, state1, _ = _drive_two_ticks(
            progress_ts=0.0, hedge_stall_s=1.0, hedge_relaunch=True)
        iid = item_id_of(_PLAN_A)
        assert state1["items"][iid]["hedge_attempts"] == 1
        # T3 进展恢复（新子进程写了日志，停滞 0.5 < 阈值 1）→ 摘账
        e3 = _entry(_PLAN_A, verdict="RUNNING")
        _, state3 = queue_tick(
            state1, now_fn=lambda: 2000.0, calendar_fn=lambda: _cal(),
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [e3], launcher_fn=_Launcher(),
            failure_context_fn=None, hedge_stall_s=1.0,
            hedge_relaunch=True, progress_fn=_counting_probe(1999.5))
        assert "hedge" not in state3["items"][iid]
        # T4 再停滞：只新告警，不再重发（帽=1 每项终身）
        e4 = _entry(_PLAN_A, verdict="RUNNING")
        launcher4 = _Launcher()
        actions4, state4 = queue_tick(
            state3, now_fn=lambda: 3000.0, calendar_fn=lambda: _cal(),
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [e4], launcher_fn=launcher4,
            failure_context_fn=None, hedge_stall_s=1.0,
            hedge_relaunch=True, progress_fn=_counting_probe(0.0))
        assert [a for a in actions4 if a.get("action") == "hedge_alert"]
        rels = [a for a in actions4 if a.get("action") == "hedge_relaunch"]
        assert rels == []
        assert launcher4.calls == []
        rec = state4["items"][iid]
        assert rec["hedge"]["attempts"] == 1  # 账面保持已重发事实
        assert "已对冲重发 1 次" in queue_hedge_index(
            state4, now=3000.0)[iid]["text"]

    def test_explicit_false_overrides_env_on(self, monkeypatch):
        monkeypatch.setenv(HEDGE_RELAUNCH_ENV, "1")
        actions, _state, launcher = _drive_two_ticks(
            progress_ts=0.0, hedge_stall_s=1.0, hedge_relaunch=False)
        # 显式 False 压过 env → 有告警、零重发
        assert [a for a in actions if a.get("action") == "hedge_alert"]
        assert [a for a in actions
                if a.get("action") == "hedge_relaunch"] == []
        assert launcher.calls == [_PLAN_A]


# ─── 缺省进展探针（mtime 口径）───────────────────────────────────────────────

class TestDefaultProgressProbe:
    def test_max_mtime_of_plan_and_launch_log(self, tmp_path):
        plan = tmp_path / "campaign.plan.json"
        log = tmp_path / "queue_daemon_launch.log"
        plan.write_text("{}", encoding="utf-8")
        os.utime(plan, (1000.0, 1000.0))
        assert default_progress_ts(plan) == 1000.0
        log.write_text("x", encoding="utf-8")
        os.utime(log, (2000.0, 2000.0))
        assert default_progress_ts(plan) == 2000.0  # 取最新
        os.utime(log, (500.0, 500.0))
        assert default_progress_ts(plan) == 1000.0  # 计划更新则取计划

    def test_missing_everything_returns_none(self, tmp_path):
        assert default_progress_ts(tmp_path / "ghost" / "campaign.plan.json") \
            is None

    def test_dir_form_plan_path_supported(self, tmp_path):
        d = tmp_path / "camp"
        d.mkdir()
        (d / "campaign.plan.json").write_text("{}", encoding="utf-8")
        # 目录形态：目录本体 mtime 不作证据（条目增删噪声面），只认目录内
        # 两探针名（计划文件+发射日志）
        os.utime(d, (2000.0, 2000.0))
        os.utime(d / "campaign.plan.json", (1234.0, 1234.0))
        assert default_progress_ts(d) == 1234.0
        log = d / "queue_daemon_launch.log"
        log.write_text("x", encoding="utf-8")
        os.utime(log, (3000.0, 3000.0))
        assert default_progress_ts(d) == 3000.0  # 目录内发射日志最新则取它


# ─── API 透出（/api/campaign_queue queue_hedge）─────────────────────────────

_PLAN_MIN = {
    "ok": True, "recipe": "recipes/demo.yaml", "model": "wilkinson",
    "stages": [{"stage": "calibrate", "kind": "calibrate",
                "adapter": "openems", "depends_on": [],
                "status": "pending", "license_gated": False}],
    "scheduling": {"ok": True, "n_jobs": 1, "predictor_used": False,
                   "budget_gate_used": False, "decision_log": []},
}


def _write_hedge_state(runs_root: Path, *, hedge: bool) -> None:
    """经 queue_tick 造真实形态状态档落默认路径（hedge=True 带停滞账）。"""
    from rfauto.service.campaign_queue_daemon import save_queue_state

    plan_path = str(runs_root / "runs" / "camp_a" / "campaign.plan.json")
    e1 = {"item_id": item_id_of(plan_path), "plan_path": plan_path,
          "model": "wilkinson", "verdict": "", "n_stages": 1,
          "license_gated": False}
    _, state = queue_tick(
        None, now_fn=lambda: 100.0, calendar_fn=lambda: _cal(),
        preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
        queue_fn=lambda root: [e1],
        launcher_fn=lambda p: {"ok": True, "pid": 7, "cmdline": ["x"],
                               "log_path": p + ".log"},
        failure_context_fn=None)
    e2 = dict(e1, verdict="RUNNING")
    kwargs: dict = {}
    if hedge:
        kwargs = {"hedge_stall_s": 10.0}
    probe = _counting_probe(0.0 if hedge else None)
    _, state = queue_tick(
        state, now_fn=lambda: 1000.0, calendar_fn=lambda: _cal(),
        preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
        queue_fn=lambda root: [e2],
        launcher_fn=lambda p: {"ok": True, "pid": 8, "cmdline": ["x"],
                               "log_path": p + ".log"},
        failure_context_fn=None, progress_fn=probe, **kwargs)
    save_queue_state(
        state, runs_root / "runs" / "campaign_queue" / "queue_state.json")


class TestQueueHedgeApi:
    @pytest.fixture()
    def runs_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        d = tmp_path / "runs" / "camp_a"
        d.mkdir(parents=True)
        (d / "campaign.plan.json").write_text(
            json.dumps(_PLAN_MIN, ensure_ascii=False), encoding="utf-8")
        return tmp_path

    @pytest.fixture()
    def client(self, runs_root):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        return TestClient(create_ui_app())

    def test_hedged_state_surfaces_queue_hedge(self, runs_root, client):
        _write_hedge_state(runs_root, hedge=True)
        r = client.get("/api/campaign_queue").json()
        assert r["ok"] is True
        hq = r["campaigns"][0].get("queue_hedge")
        assert hq is not None
        assert hq["code"] == HEDGE_CODE_STALL
        assert "疑似停滞" in hq["text"]
        assert isinstance(hq["stalled_s"], float) and hq["stalled_s"] >= 0.0
        assert hq["attempts"] == 0

    def test_hedge_off_state_carries_no_queue_hedge(self, runs_root, client):
        _write_hedge_state(runs_root, hedge=False)
        r = client.get("/api/campaign_queue").json()
        assert all("queue_hedge" not in c for c in r["campaigns"])

    def test_no_state_file_no_queue_hedge(self, runs_root, client):
        r = client.get("/api/campaign_queue").json()
        assert r["ok"] is True
        assert all("queue_hedge" not in c for c in r["campaigns"])


# ─── 常驻执行体透传（run_queue_daemon → queue_tick 对冲参数）────────────────

class TestDaemonForwarding:
    def test_once_mode_forwards_hedge_params_to_state(self, tmp_path):
        """生产执行体链路：预置在途账 → --once 单步 → 对冲账落状态档。"""
        from rfauto.service.campaign_queue_daemon import (
            load_queue_state,
            run_queue_daemon,
            save_queue_state,
        )

        sp = tmp_path / "runs" / "campaign_queue" / "queue_state.json"
        iid = item_id_of(_PLAN_A)
        seeded = {
            "schema": "rfauto-campaign-queue-daemon-v1", "root": "runs",
            "machine": None, "items": {iid: {
                "item_id": iid, "plan_path": _PLAN_A, "model": "wilkinson",
                "status": ITEM_LAUNCHED, "launched_at": 1.0, "pid": 9,
                "log_path": None, "verdict_seen": "RUNNING", "reason": "",
                "updated_at": 1.0}},
            "last_tick_at": 1.0, "last_actions": [], "updated_at": 1.0}
        save_queue_state(seeded, sp)
        res = run_queue_daemon(
            once=True, state_path=sp, root="runs",
            queue_fn=lambda root: [_entry(_PLAN_A, verdict="RUNNING")],
            calendar_fn=lambda: _cal(),
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            launcher_fn=_Launcher(), failure_context_fn=None,
            progress_fn=_counting_probe(0.0),
            hedge_stall_s=100.0, hedge_relaunch=False,
            now_fn=lambda: 1000.0, sleep_fn=lambda s: None)
        assert res.get("ok") is True
        state = load_queue_state(sp)
        rec = state["items"][iid]
        assert rec["hedge"]["code"] == HEDGE_CODE_STALL  # 对冲账穿透落盘
        assert any(a.get("action") == "hedge_alert"
                   for a in state["last_actions"])
