"""W2-S3 队列阻塞原因人读透出单测（aurora_i 采纳 #2，全 fake 零网络零真机）.

覆盖（任务书判据逐条）：
- 原因分类：单飞互斥/日历 blocked/license 预检未过/前序未发射（依赖门 v2
  前的近义面）四码各归其位（tick 合成队列事件驱动）；
- 人读文案：blocked_text_of 组装（"等 license：…（已等 12 分钟）"形态，
  秒/分钟换算界）；
- 变化才落账：同 (code, detail) 不改写（since 保持首次阻塞时刻）；
  换因写新 detail 保 since；异码重置 since；解除摘账；
- 读侧透出：queue_blocks_index（仅 queued 带账项）+ queue_status_view
  blocked 计数；
- 失败诊断包触发：launch_failed/已发射→ABORTED/PARTIAL 经注入缝触发；
  COMPLETE 不触发；采集面异常留痕不拆 tick；纯函数缺省零副作用。
"""

from __future__ import annotations

import sys
from pathlib import Path

from rfauto.service.campaign_queue_daemon import (
    BLOCK_AHEAD,
    BLOCK_CALENDAR,
    BLOCK_LICENSE,
    BLOCK_NONE,
    BLOCK_SOLO,
    ITEM_ABORTED,
    ITEM_DONE,
    ITEM_LAUNCHED,
    ITEM_QUEUED,
    blocked_text_of,
    item_id_of,
    merge_blocked_reason,
    queue_blocks_index,
    queue_status_view,
    queue_tick,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


# ─── 假件工厂（test_campaign_queue_daemon 同款口径）─────────────────────────

def _entry(plan_path: str, *, verdict: str = "",
           license_gated: bool = False, model: str = "wilkinson") -> dict:
    return {"item_id": item_id_of(plan_path), "plan_path": plan_path,
            "model": model, "verdict": verdict,
            "n_stages": 2, "license_gated": license_gated}


def _cal(state: str = "open", reason: str = "") -> dict:
    return {"loaded": state != "open", "state": state,
            "launchable": state != "blocked",
            "windows_hit": [state] if state != "open" else [],
            "reason": reason or f"fake calendar {state}"}


def _pf(verdict: str, reason: str = "") -> dict:
    return {"ok": verdict != "FAIL", "verdict": verdict,
            "reason": reason or f"fake preflight {verdict}"}


class _Launcher:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def __call__(self, plan_path: str) -> dict:
        self.calls.append(plan_path)
        if self.fail:
            return dict(ok=False, error="fake launch boom")
        return dict(ok=True, pid=100 + len(self.calls),
                    cmdline=["fake-python"], log_path=plan_path + ".log")


class _FcRecorder:
    """失败诊断包注入缝记录器（可注入异常）。"""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def __call__(self, plan_path: str) -> dict:
        self.calls.append(plan_path)
        if self.fail:
            raise RuntimeError("fake fc boom")
        return dict(ok=True, path=plan_path + "/failure_context.json")


# ─── 人读文案（blocked_text_of 纯函数）───────────────────────────────────────

class TestBlockedTextOf:
    def test_license_with_waited_minutes(self):
        assert blocked_text_of(
            BLOCK_LICENSE, detail="HFSS 许可端口不可达",
            waited_s=720.0) == "等 license：HFSS 许可端口不可达（已等 12 分钟）"

    def test_solo_with_detail_and_seconds(self):
        assert blocked_text_of(
            BLOCK_SOLO, detail="camp_a", waited_s=45.0
        ) == "等单飞位：在途战役未收尾（camp_a）（已等 45 秒）"

    def test_calendar_and_ahead(self):
        assert blocked_text_of(
            BLOCK_CALENDAR, detail="备份窗 02:50-05:35"
        ) == "等日历窗：备份窗 02:50-05:35"
        assert blocked_text_of(BLOCK_AHEAD, n_ahead=2) == \
            "排队中：前面还有 2 个候选"

    def test_no_waited_and_unknown_code(self):
        assert blocked_text_of(BLOCK_LICENSE, detail="x") == "等 license：x"
        assert blocked_text_of("nonsense") == ""
        assert blocked_text_of(BLOCK_NONE) == ""


# ─── 变化才落账（merge_blocked_reason 纯函数）────────────────────────────────

class TestMergeBlockedReason:
    def test_first_merge_sets_since(self):
        rec, changed = merge_blocked_reason(
            {"status": ITEM_QUEUED}, BLOCK_LICENSE, detail="r1", now=100.0)
        assert changed is True
        assert rec["blocked"] == {"code": BLOCK_LICENSE, "detail": "r1",
                                  "n_ahead": 0, "since": 100.0,
                                  "updated_at": 100.0}

    def test_same_reason_no_rewrite(self):
        rec = {"status": ITEM_QUEUED, "blocked": {
            "code": BLOCK_LICENSE, "detail": "r1", "n_ahead": 0,
            "since": 100.0, "updated_at": 100.0}}
        new_rec, changed = merge_blocked_reason(
            rec, BLOCK_LICENSE, detail="r1", now=200.0)
        assert changed is False  # 同因不刷屏
        assert new_rec["blocked"]["since"] == 100.0
        assert new_rec["blocked"]["updated_at"] == 100.0  # 不推进

    def test_same_code_new_detail_keeps_since(self):
        rec = {"blocked": {"code": BLOCK_LICENSE, "detail": "r1",
                           "n_ahead": 0, "since": 100.0, "updated_at": 100.0}}
        new_rec, changed = merge_blocked_reason(
            rec, BLOCK_LICENSE, detail="r2", now=200.0)
        assert changed is True
        assert new_rec["blocked"]["detail"] == "r2"
        assert new_rec["blocked"]["since"] == 100.0  # 同码同一段等待期

    def test_code_switch_resets_since(self):
        rec = {"blocked": {"code": BLOCK_CALENDAR, "detail": "w",
                           "n_ahead": 0, "since": 100.0, "updated_at": 100.0}}
        new_rec, changed = merge_blocked_reason(
            rec, BLOCK_LICENSE, detail="r", now=200.0)
        assert changed is True
        assert new_rec["blocked"]["code"] == BLOCK_LICENSE
        assert new_rec["blocked"]["since"] == 200.0  # 新一段阻塞

    def test_clear_removes_and_idempotent(self):
        rec = {"blocked": {"code": BLOCK_LICENSE, "detail": "r",
                           "n_ahead": 0, "since": 100.0, "updated_at": 100.0}}
        new_rec, changed = merge_blocked_reason(rec, BLOCK_NONE, now=200.0)
        assert changed is True and "blocked" not in new_rec
        again, changed2 = merge_blocked_reason(new_rec, BLOCK_NONE, now=300.0)
        assert changed2 is False and "blocked" not in again

    def test_input_record_not_mutated(self):
        import copy

        rec = {"status": ITEM_QUEUED, "blocked": {
            "code": BLOCK_LICENSE, "detail": "r1", "n_ahead": 0,
            "since": 100.0, "updated_at": 100.0}}
        snapshot = copy.deepcopy(rec)
        merge_blocked_reason(rec, BLOCK_CALENDAR, detail="w", now=200.0)
        assert rec == snapshot  # copy-on-write：入参不改性


# ─── tick 合成事件分类（四码各归其位）────────────────────────────────────────

class TestTickBlockedClassification:
    def test_calendar_blocked_classified(self):
        q = [_entry("runs/camp_a")]
        actions, state = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("blocked"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=_Launcher(),
            now_fn=lambda: 10.0)
        iid = q[0]["item_id"]
        rec = state["items"][iid]
        assert rec["status"] == ITEM_QUEUED
        assert rec["blocked"]["code"] == BLOCK_CALENDAR
        assert rec["blocked"]["detail"] == "fake calendar blocked"
        assert rec["blocked"]["since"] == 10.0
        assert [a["action"] for a in actions] == [
            "scan", "enqueue", "calendar_blocked"]

    def test_license_fail_classified(self):
        q = [_entry("runs/camp_a", license_gated=True)]
        _, state = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("FAIL", "HFSS 许可端口不可达"),
            launcher_fn=_Launcher(), now_fn=lambda: 10.0)
        blk = state["items"][q[0]["item_id"]]["blocked"]
        assert blk["code"] == BLOCK_LICENSE
        assert blk["detail"] == "HFSS 许可端口不可达"

    def test_solo_blocks_all_candidates(self):
        qa, qb = _entry("runs/camp_a"), _entry("runs/camp_b")
        launch = _Launcher()
        _, s1 = queue_tick(None, queue_fn=lambda root: [qa, qb],
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=launch, now_fn=lambda: 1.0)
        assert launch.calls == ["runs/camp_a"]  # a 上位发射
        _, s2 = queue_tick(s1, queue_fn=lambda root: [qa, qb],
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=launch, now_fn=lambda: 2.0)
        # a 在途（launched 无阻塞账）；b 排队且阻塞因=单飞互斥
        assert s2["items"][qa["item_id"]]["status"] == ITEM_LAUNCHED
        assert "blocked" not in s2["items"][qa["item_id"]]
        blk = s2["items"][qb["item_id"]]["blocked"]
        assert blk["code"] == BLOCK_SOLO
        assert blk["detail"] == "wilkinson"  # 在途 model 兜底标签

    def test_ahead_candidate_classified(self):
        qa, qb = _entry("runs/camp_a"), _entry("runs/camp_b")
        _, state = queue_tick(None, queue_fn=lambda root: [qa, qb],
                              calendar_fn=lambda: _cal("blocked"),
                              preflight_fn=lambda m: _pf("PASS"),
                              launcher_fn=_Launcher(), now_fn=lambda: 1.0)
        assert state["items"][qa["item_id"]]["blocked"]["code"] \
            == BLOCK_CALENDAR
        blk_b = state["items"][qb["item_id"]]["blocked"]
        assert blk_b["code"] == BLOCK_AHEAD
        assert blk_b["n_ahead"] == 1  # 前面还有 1 个候选

    def test_change_only_across_ticks(self):
        q = [_entry("runs/camp_a")]
        _, s1 = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal(
                "blocked", "窗 A"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=_Launcher(),
            now_fn=lambda: 10.0)
        iid = q[0]["item_id"]
        blk1 = s1["items"][iid]["blocked"]
        # tick2 同因：账面原样（since/updated_at 均不推进——同因不刷屏）
        _, s2 = queue_tick(
            s1, queue_fn=lambda root: q, calendar_fn=lambda: _cal(
                "blocked", "窗 A"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=_Launcher(),
            now_fn=lambda: 70.0)
        assert s2["items"][iid]["blocked"] == blk1
        # tick3 换因（同码异 detail）：detail 更新，since 保持
        _, s3 = queue_tick(
            s2, queue_fn=lambda root: q, calendar_fn=lambda: _cal(
                "blocked", "窗 B"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=_Launcher(),
            now_fn=lambda: 130.0)
        blk3 = s3["items"][iid]["blocked"]
        assert blk3["detail"] == "窗 B"
        assert blk3["since"] == 10.0
        assert blk3["updated_at"] == 130.0

    def test_queued_to_terminal_clears_block(self):
        q = [_entry("runs/camp_a")]
        _, s1 = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("blocked"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=_Launcher(),
            now_fn=lambda: 10.0)
        iid = q[0]["item_id"]
        assert "blocked" in s1["items"][iid]
        q_done = [_entry("runs/camp_a", verdict="COMPLETE")]
        _, s2 = queue_tick(
            s1, queue_fn=lambda root: q_done, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=_Launcher(),
            now_fn=lambda: 20.0)
        assert s2["items"][iid]["status"] == ITEM_DONE
        assert "blocked" not in s2["items"][iid]  # 阻塞账随态清除


# ─── 读侧透出（index + status view）──────────────────────────────────────────

class TestReadSideViews:
    def _state_with_blocks(self) -> dict:
        q = [_entry("runs/camp_a"), _entry("runs/camp_b")]
        _, state = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("blocked"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=_Launcher(),
            now_fn=lambda: 100.0)
        return state

    def test_blocks_index_only_queued_with_ledger(self):
        state = self._state_with_blocks()
        idx = queue_blocks_index(state, now=160.0)
        assert len(idx) == 2
        a = idx[_entry("runs/camp_a")["item_id"]]
        assert a["code"] == BLOCK_CALENDAR
        assert a["waited_s"] == 60.0  # 读侧即时计算
        assert "已等 60 秒" in a["text"]
        # 跨过分钟界（>=90s 报分钟）
        b = queue_blocks_index(state, now=100.0 + 720.0)[
            _entry("runs/camp_b")["item_id"]]
        assert b["waited_s"] == 720.0
        assert "已等 12 分钟" in b["text"]

    def test_blocks_index_skips_terminal_and_unblocked(self):
        state = self._state_with_blocks()
        iid_a = _entry("runs/camp_a")["item_id"]
        state["items"][iid_a]["status"] = ITEM_ABORTED  # 终态陈账隐身
        idx = queue_blocks_index(state, now=110.0)
        assert set(idx) == {_entry("runs/camp_b")["item_id"]}
        assert queue_blocks_index({"items": {}}, now=0.0) == {}

    def test_status_view_blocked_counts_and_absent_key(self):
        state = self._state_with_blocks()
        view = queue_status_view(state)
        assert view["blocked"] == {BLOCK_CALENDAR: 1, BLOCK_AHEAD: 1}
        # 无阻塞账 → 键缺席（不加空壳键，消费方按缺键=无阻塞读）
        clean = {"items": {"x": {"status": ITEM_QUEUED}}}
        assert "blocked" not in queue_status_view(clean)


# ─── 失败诊断包触发（注入缝）─────────────────────────────────────────────────

class TestFailureContextTrigger:
    def test_launch_failed_triggers_snapshot(self):
        q = [_entry("runs/camp_a")]
        fc = _FcRecorder()
        actions, _ = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=_Launcher(fail=True),
            failure_context_fn=fc, now_fn=lambda: 1.0)
        assert fc.calls == ["runs/camp_a"]
        fc_actions = [a for a in actions if a["action"] == "failure_context"]
        assert len(fc_actions) == 1
        assert fc_actions[0]["path"].endswith("failure_context.json")

    def test_launched_aborted_triggers_complete_does_not(self):
        q = [_entry("runs/camp_a")]
        launch = _Launcher()
        _, s1 = queue_tick(None, queue_fn=lambda root: q,
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=launch, now_fn=lambda: 1.0)
        fc = _FcRecorder()
        # 终态回读 COMPLETE：不触发（成功不是案发现场）
        q_done = [_entry("runs/camp_a", verdict="COMPLETE")]
        queue_tick(s1, queue_fn=lambda root: q_done,
                   calendar_fn=lambda: _cal("open"),
                   preflight_fn=lambda m: _pf("PASS"),
                   launcher_fn=launch, failure_context_fn=fc, now_fn=lambda: 2.0)
        assert fc.calls == []
        # 终态回读 ABORTED：触发
        q_dead = [_entry("runs/camp_a", verdict="ABORTED")]
        actions, _ = queue_tick(s1, queue_fn=lambda root: q_dead,
                                calendar_fn=lambda: _cal("open"),
                                preflight_fn=lambda m: _pf("PASS"),
                                launcher_fn=launch, failure_context_fn=fc,
                                now_fn=lambda: 3.0)
        assert fc.calls == ["runs/camp_a"]
        assert "failure_context" in [a["action"] for a in actions]

    def test_launched_partial_triggers(self):
        q = [_entry("runs/camp_a")]
        _, s1 = queue_tick(None, queue_fn=lambda root: q,
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=_Launcher(), now_fn=lambda: 1.0)
        fc = _FcRecorder()
        q_partial = [_entry("runs/camp_a", verdict="PARTIAL")]
        queue_tick(s1, queue_fn=lambda root: q_partial,
                   calendar_fn=lambda: _cal("open"),
                   preflight_fn=lambda m: _pf("PASS"),
                   launcher_fn=_Launcher(), failure_context_fn=fc,
                   now_fn=lambda: 2.0)
        assert len(fc.calls) == 1

    def test_collector_error_leaves_trace_not_crash(self):
        q = [_entry("runs/camp_a")]
        fc = _FcRecorder(fail=True)
        actions, _ = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=_Launcher(fail=True),
            failure_context_fn=fc, now_fn=lambda: 1.0)
        errs = [a for a in actions if a["action"] == "failure_context_error"]
        assert len(errs) == 1 and "fake fc boom" in errs[0]["error"]

    def test_default_none_no_side_effect(self):
        # 纯函数缺省 fc_fn=None：失败路径零采集零额外动作（零副作用契约）
        q = [_entry("runs/camp_a")]
        actions, _ = queue_tick(
            None, queue_fn=lambda root: q, calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=_Launcher(fail=True))
        assert not [a for a in actions if a["action"].startswith("failure_")]
