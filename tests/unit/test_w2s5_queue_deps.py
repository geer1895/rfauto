"""W2-S5 队列依赖门控 depends_on 单测（aurora_j，全 fake 零网络零真机）.

覆盖（任务书判据逐条）：
- 入队校验 validate_depends_on：引用不存在（未知 id）报 ValueError 带
  清晰文案；环检测（A→B→A/自身环/环下游）拒绝且环路径进文案；合法链
  通过；缺字段零校验问题；
- tick 依赖门：前置未终态阻塞（BLOCK_DEPS + detail=``<id>（<状态>）``）；
  前置在途覆写单飞码；前置终态（COMPLETE/launch_failed）解除阻塞放行
  （失败如实传播不自动取消——#122，v1 无 skip 态的选择，见交付报告）；
  pass-over：依赖未满足不阻塞队头（就绪候选照常发射）；依赖环成员全
  阻塞零发射；无账引用阻塞（不在当前队列）；陈账 survivor 终态放行
  （前置计划删除后依赖方仍可走）；
- 变化才落账：前置状态 queued→launched 换因 detail 更新、since 保持；
- 人话文案：blocked_text_of 新码（"等依赖：…（已等 N 分钟）"形态）；
- 读侧透出：queue_blocks_index/queue_status_view 自动带出新码；
- scan_queue：计划级 depends_on 键读入+规范化（strip/去空/去重保序/
  非列表=[]）；
- 缺字段零行为（回归钉）：无 depends_on 候选队列行为与既有门序逐位一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from rfauto.service.campaign_queue_daemon import (
    BLOCK_AHEAD,
    BLOCK_DEPS,
    ITEM_DONE,
    ITEM_LAUNCH_FAILED,
    ITEM_LAUNCHED,
    ITEM_TERMINAL,
    blocked_text_of,
    item_id_of,
    queue_blocks_index,
    queue_status_view,
    queue_tick,
    scan_queue,
    validate_depends_on,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


# ─── 假件工厂（test_campaign_queue_block_reason 同款口径）────────────────────

def _entry(plan_path: str, *, verdict: str = "",
           license_gated: bool = False, model: str = "wilkinson",
           depends_on: list[str] | None = None) -> dict:
    e = {"item_id": item_id_of(plan_path), "plan_path": plan_path,
         "model": model, "verdict": verdict,
         "n_stages": 2, "license_gated": license_gated}
    if depends_on is not None:
        e["depends_on"] = list(depends_on)
    return e


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


# ─── 入队校验（validate_depends_on 写侧契约）─────────────────────────────────

class TestValidateDepsOn:
    def test_unknown_ref_raises_with_clear_text(self):
        es = [{"item_id": "a", "depends_on": ["ghost"]}]
        with pytest.raises(ValueError) as ei:
            validate_depends_on(es)
        msg = str(ei.value)
        assert "depends_on 校验失败" in msg
        assert "a" in msg and "ghost" in msg
        assert "不在当前队列" in msg

    def test_cycle_raises_with_path(self):
        es = [{"item_id": "a", "depends_on": ["b"]},
              {"item_id": "b", "depends_on": ["a"]}]
        with pytest.raises(ValueError) as ei:
            validate_depends_on(es)
        assert "a → b → a" in str(ei.value)

    def test_self_cycle_raises(self):
        with pytest.raises(ValueError) as ei:
            validate_depends_on([{"item_id": "a", "depends_on": ["a"]}])
        assert "a → a" in str(ei.value)

    def test_downstream_of_cycle_flagged(self):
        es = [{"item_id": "a", "depends_on": ["b"]},
              {"item_id": "b", "depends_on": ["a"]},
              {"item_id": "c", "depends_on": ["a"]}]
        with pytest.raises(ValueError) as ei:
            validate_depends_on(es)
        msg = str(ei.value)
        assert "a → b → a" in msg
        assert "c" in msg  # 环下游同被点名（同样永不满足）

    def test_valid_chain_passes(self):
        es = [{"item_id": "a"},
              {"item_id": "b", "depends_on": ["a"]},
              {"item_id": "c", "depends_on": ["a", "b"]}]
        validate_depends_on(es)  # 不抛即过

    def test_missing_field_passes(self):
        validate_depends_on([{"item_id": "a"}, {"item_id": "b"}])


# ─── tick 依赖门（合成队列事件驱动）──────────────────────────────────────────

class TestTickDepsGate:
    def test_unmet_queued_prereq_blocks_and_passover(self):
        # 队序 [A(无依赖), B(deps A), C(无依赖)]：A 上位发射（队头不被
        # B 的未满足依赖挡住=pass-over），B 阻塞 BLOCK_DEPS，C 排队序
        # BLOCK_AHEAD（就绪候选内的位次）。
        qa = _entry("runs/camp_a")
        qb = _entry("runs/camp_b", depends_on=[qa["item_id"]])
        qc = _entry("runs/camp_c")
        launch = _Launcher()
        actions, state = queue_tick(
            None, queue_fn=lambda root: [qa, qb, qc],
            calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=launch,
            now_fn=lambda: 10.0)
        assert launch.calls == ["runs/camp_a"]  # 队头上位，不被 B 挡
        blk = state["items"][qb["item_id"]]["blocked"]
        assert blk["code"] == BLOCK_DEPS
        assert blk["detail"] == f"{qa['item_id']}（排队中）"
        assert state["items"][qc["item_id"]]["blocked"]["code"] == BLOCK_AHEAD
        assert "launch" in [a["action"] for a in actions]

    def test_prereq_inflight_overwrites_solo_code(self):
        qa = _entry("runs/camp_a")
        qb = _entry("runs/camp_b", depends_on=[qa["item_id"]])
        launch = _Launcher()
        _, s1 = queue_tick(None, queue_fn=lambda root: [qa, qb],
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=launch, now_fn=lambda: 1.0)
        assert launch.calls == ["runs/camp_a"]  # a 发射（b 依赖未满足不挡队头）
        # tick2：a 在途——b 同真报依赖（覆写 solo 码，更持久的原因）
        _, s2 = queue_tick(s1, queue_fn=lambda root: [qa, qb],
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=launch, now_fn=lambda: 2.0)
        assert s2["items"][qa["item_id"]]["status"] == ITEM_LAUNCHED
        blk = s2["items"][qb["item_id"]]["blocked"]
        assert blk["code"] == BLOCK_DEPS
        assert blk["detail"] == f"{qa['item_id']}（在途）"

    def test_prereq_complete_releases_same_tick(self):
        qa = _entry("runs/camp_a", verdict="COMPLETE")  # 先于守护的终态
        qb = _entry("runs/camp_b", depends_on=[qa["item_id"]])
        launch = _Launcher()
        _, state = queue_tick(
            None, queue_fn=lambda root: [qa, qb],
            calendar_fn=lambda: _cal("open"),
            preflight_fn=lambda m: _pf("PASS"), launcher_fn=launch,
            now_fn=lambda: 10.0)
        assert state["items"][qa["item_id"]]["status"] == ITEM_DONE
        assert launch.calls == ["runs/camp_b"]  # 前置终态=放行
        assert "blocked" not in state["items"][qb["item_id"]]

    def test_prereq_launch_failed_releases_too(self):
        # 失败传播如实（#122）：前置发射失败（launch_failed=终态）不自动
        # 取消依赖方——依赖方照常获得发射资格，成败由自身战役判定。
        qa = _entry("runs/camp_a")
        qb = _entry("runs/camp_b", depends_on=[qa["item_id"]])
        launch = _Launcher(fail=True)
        _, s1 = queue_tick(None, queue_fn=lambda root: [qa],
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=launch, now_fn=lambda: 1.0)
        assert s1["items"][qa["item_id"]]["status"] == ITEM_LAUNCH_FAILED
        _, s2 = queue_tick(s1, queue_fn=lambda root: [qa, qb],
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=_Launcher(), now_fn=lambda: 2.0)
        assert launch.calls == ["runs/camp_a"]  # 终态永不重发
        assert s2["items"][qb["item_id"]]["status"] == ITEM_LAUNCHED

    def test_cycle_members_block_never_launch(self):
        qa = _entry("runs/camp_a")
        qb = _entry("runs/camp_b")
        qa["depends_on"] = [qb["item_id"]]
        qb["depends_on"] = [qa["item_id"]]
        launch = _Launcher()
        _, state = queue_tick(None, queue_fn=lambda root: [qa, qb],
                              calendar_fn=lambda: _cal("open"),
                              preflight_fn=lambda m: _pf("PASS"),
                              launcher_fn=launch, now_fn=lambda: 1.0)
        assert launch.calls == []  # 环成员全不发射
        for q in (qa, qb):
            blk = state["items"][q["item_id"]]["blocked"]
            assert blk["code"] == BLOCK_DEPS
            assert "依赖环" in blk["detail"]

    def test_unknown_ref_blocks_not_crash(self):
        # 无账引用：守护 tick 降级为阻塞账（不拆 tick，#105），独立候选照发。
        qa = _entry("runs/camp_a")
        qb = _entry("runs/camp_b", depends_on=["ghost_id"])
        launch = _Launcher()
        _, state = queue_tick(None, queue_fn=lambda root: [qa, qb],
                              calendar_fn=lambda: _cal("open"),
                              preflight_fn=lambda m: _pf("PASS"),
                              launcher_fn=launch, now_fn=lambda: 1.0)
        assert launch.calls == ["runs/camp_a"]
        blk = state["items"][qb["item_id"]]["blocked"]
        assert blk["code"] == BLOCK_DEPS
        assert blk["detail"] == "ghost_id（不在当前队列）"

    def test_terminal_survivor_account_releases(self):
        # 前置计划已被删除（本 tick 扫描未命中）但状态档留有终态陈账
        # （survivor）——依赖方照样放行（以账状态字段为准）。
        qa_id = item_id_of("runs/camp_a")
        prev_state = {"items": {qa_id: {
            "item_id": qa_id, "plan_path": "runs/camp_a",
            "status": ITEM_DONE, "updated_at": 1.0}}}
        qb = _entry("runs/camp_b", depends_on=[qa_id])
        launch = _Launcher()
        _, state = queue_tick(prev_state, queue_fn=lambda root: [qb],
                              calendar_fn=lambda: _cal("open"),
                              preflight_fn=lambda m: _pf("PASS"),
                              launcher_fn=launch, now_fn=lambda: 10.0)
        assert launch.calls == ["runs/camp_b"]
        assert "blocked" not in state["items"][qb["item_id"]]

    def test_detail_change_keeps_since(self):
        # 前置 queued→launched：同码换因（detail 更新、since 保持首阻时刻）
        qa = _entry("runs/camp_a")
        qb = _entry("runs/camp_b", depends_on=[qa["item_id"]])
        q = [qa, qb]
        _, s1 = queue_tick(None, queue_fn=lambda root: q,
                           calendar_fn=lambda: _cal("blocked"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=_Launcher(), now_fn=lambda: 10.0)
        blk1 = s1["items"][qb["item_id"]]["blocked"]
        assert blk1["detail"] == f"{qa['item_id']}（排队中）"
        _, s2 = queue_tick(s1, queue_fn=lambda root: q,
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=_Launcher(), now_fn=lambda: 70.0)
        _, s3 = queue_tick(s2, queue_fn=lambda root: q,
                           calendar_fn=lambda: _cal("open"),
                           preflight_fn=lambda m: _pf("PASS"),
                           launcher_fn=_Launcher(), now_fn=lambda: 130.0)
        blk3 = s3["items"][qb["item_id"]]["blocked"]
        assert blk3["detail"] == f"{qa['item_id']}（在途）"
        assert blk3["since"] == 10.0  # 同码同一段等待期
        assert blk3["updated_at"] == 130.0

    def test_zero_behavior_without_field(self):
        # 回归钉：无 depends_on 键的候选队列与既有门序逐位一致
        # （队头发射、后位 BLOCK_AHEAD）。
        qa = _entry("runs/camp_a")
        qb = _entry("runs/camp_b")
        launch = _Launcher()
        _, state = queue_tick(None, queue_fn=lambda root: [qa, qb],
                              calendar_fn=lambda: _cal("open"),
                              preflight_fn=lambda m: _pf("PASS"),
                              launcher_fn=launch, now_fn=lambda: 1.0)
        assert launch.calls == ["runs/camp_a"]
        assert state["items"][qb["item_id"]]["blocked"]["code"] == BLOCK_AHEAD
        assert state["items"][qb["item_id"]]["blocked"]["n_ahead"] == 1
        assert "blocked" not in state["items"][qa["item_id"]]

    def test_empty_depends_on_is_zero_behavior(self):
        qa = _entry("runs/camp_a", depends_on=[])
        launch = _Launcher()
        _, state = queue_tick(None, queue_fn=lambda root: [qa],
                              calendar_fn=lambda: _cal("open"),
                              preflight_fn=lambda m: _pf("PASS"),
                              launcher_fn=launch, now_fn=lambda: 1.0)
        assert launch.calls == ["runs/camp_a"]
        assert state["items"][qa["item_id"]]["status"] == ITEM_LAUNCHED

    def test_terminal_set_membership_unchanged(self):
        # 终态集合口径：失败态也在内（放行语义的根据面）
        assert ITEM_TERMINAL == ("done", "partial", "aborted",
                                 "launch_failed")


# ─── 人读文案 + 读侧透出 ─────────────────────────────────────────────────────

class TestTextAndReadSide:
    def test_blocked_text_deps_template(self):
        assert blocked_text_of(
            BLOCK_DEPS, detail="abc123（在途）",
            waited_s=720.0) == "等依赖：abc123（在途）（已等 12 分钟）"
        assert blocked_text_of(
            BLOCK_DEPS, detail="abc123（排队中）",
            waited_s=45.0) == "等依赖：abc123（排队中）（已等 45 秒）"
        assert blocked_text_of(
            BLOCK_DEPS, detail="依赖环 a → b → a") == \
            "等依赖：依赖环 a → b → a"

    def test_blocks_index_and_status_view_surface_new_code(self):
        qa = _entry("runs/camp_a")
        qb = _entry("runs/camp_b", depends_on=[qa["item_id"]])
        _, state = queue_tick(None, queue_fn=lambda root: [qa, qb],
                              calendar_fn=lambda: _cal("blocked"),
                              preflight_fn=lambda m: _pf("PASS"),
                              launcher_fn=_Launcher(), now_fn=lambda: 100.0)
        idx = queue_blocks_index(state, now=160.0)
        b = idx[qb["item_id"]]
        assert b["code"] == BLOCK_DEPS
        assert b["waited_s"] == 60.0
        assert "等依赖" in b["text"] and "已等 60 秒" in b["text"]
        assert queue_status_view(state)["blocked"][BLOCK_DEPS] == 1


# ─── scan_queue 读计划级 depends_on（真实读盘，离线确定）─────────────────────

class TestScanQueueDeps:
    def test_scan_reads_and_normalizes_depends_on(self, tmp_path):
        from rfauto.service.campaign_manager import save_plan

        d1 = tmp_path / "runs" / "camp_a"
        d1.mkdir(parents=True)
        save_plan({"model": "m1", "depends_on": [
            " ab ", "ab", "", "cd", None], "stages": []}, d1)
        d2 = tmp_path / "runs" / "camp_b"
        d2.mkdir(parents=True)
        save_plan({"model": "m2", "stages": []}, d2)  # 缺键
        entries = scan_queue(tmp_path / "runs")
        by_model = {e["model"]: e for e in entries}
        # strip+去重保序+去空+非串项剔除
        assert by_model["m1"]["depends_on"] == ["ab", "cd"]
        assert by_model["m2"]["depends_on"] == []  # 缺键=空表（零行为）

    def test_scan_non_list_depends_on_ignored(self, tmp_path):
        from rfauto.service.campaign_manager import save_plan

        d = tmp_path / "runs" / "camp_a"
        d.mkdir(parents=True)
        save_plan({"model": "m1", "depends_on": "not-a-list",
                   "stages": []}, d)
        entries = scan_queue(tmp_path / "runs")
        assert entries[0]["depends_on"] == []  # 坏形态防御=无依赖
