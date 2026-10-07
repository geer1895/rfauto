"""W5-C DS-4：agentTeams 样板测试（roster 持久化+mailbox FIFO+合成 scheduler）。

规格判据（criteria.md W5-C 节预声明；experimental 域）：
①排满调度单测：7 子代理排满（第 8 个入队，executor 不调用）→
  1 完成→立即补位派队头（结束即派）——合成时钟定序，零线程零 sleep；
②mailbox FIFO 钉：同席位 send 序=recv 序；跨席位独立；可选 jsonl
  落盘审计（best-effort）；
③roster 存续单测：create_team 落盘→get_team 读回同席位/角色/状态；
④任务板可视：board 摘要信封 experimental 字段+计数面；
⑤零真模型调用（#139）：executor 全 mock（只记录调用），缺省 executor
  显式回执 executor=mock 不静默假装执行。
"""

from __future__ import annotations

import json

from rfauto.service.multi_agent_service import (
    TEAM_MAX_ACTIVE,
    TeamMailbox,
    TeamScheduler,
    create_team,
    get_team,
    set_seat_status,
    team_board,
)


class _FakeClock:
    """合成时钟：每次读数 +1，事件定序确定性（零真实时间依赖）。"""

    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


def _recording_executor(calls: list[str], fail_on: set[str] | None = None):
    """mock 执行器（#139 零真模型）：只记录 task_id 调用序。"""
    fail_on = fail_on or set()

    def _exec(task: dict) -> dict:
        tid = str(task.get("task_id"))
        calls.append(tid)
        if tid in fail_on:
            raise RuntimeError(f"mock 执行失败: {tid}")
        return {"ok": True, "task_id": tid}

    return _exec


# ─── ① 排满调度：7 槽排满→排队；1 完成→立即补位（合成时钟）────────────────────

def test_scheduler_seven_slots_full_then_immediate_refill():
    """7 席排满（第 8 任务 queued，executor 不调）→ complete 一个→队头
    立即派发（executor 调用数 7→8，结束即派）。"""
    calls: list[str] = []
    clock = _FakeClock()
    sched = TeamScheduler(max_active=TEAM_MAX_ACTIVE,
                          executor=_recording_executor(calls), clock=clock)
    assert TEAM_MAX_ACTIVE == 7
    stamps: list[float] = []
    for i in range(7):
        got = sched.submit(f"t{i + 1}", {"round": i})
        assert got["ok"] and got["status"] == "working"
        stamps.append(clock.t)
    snap = sched.snapshot()
    assert snap["n_active"] == 7 and snap["n_queued"] == 0

    got8 = sched.submit("t8", {"round": 8})
    assert got8["ok"] and got8["status"] == "queued"
    assert calls == [f"t{i + 1}" for i in range(7)]   # 排队任务 executor 不调
    snap = sched.snapshot()
    assert snap["n_active"] == 7 and snap["n_queued"] == 1
    assert snap["queued"] == ["t8"]

    done = sched.complete("t4")
    assert done["ok"] and done["refilled"] == 1
    assert calls[-1] == "t8"          # 结束即派：队头 t8 立即补位
    snap = sched.snapshot()
    assert snap["n_active"] == 7 and snap["n_queued"] == 0
    assert snap["done"] == ["t4"] and "t8" in snap["active"]

    # 剩余 7 个逐一收尾（t8 在内）：终态 done=8，队列恒空
    for tid in ("t1", "t2", "t3", "t8", "t5", "t6", "t7"):
        sched.complete(tid)
    snap = sched.snapshot()
    assert snap["n_done"] == 8 and snap["n_active"] == 0 and snap["n_queued"] == 0
    # 合成时钟定序：七次提交期派发时间戳严格递增
    assert stamps == sorted(stamps)


def test_scheduler_dispatch_stamp_after_completion_stamp():
    """补位任务的派发时间戳 > 触发它的完成时间戳（合成时钟定序）。"""
    calls: list[str] = []
    clock = _FakeClock()
    sched = TeamScheduler(max_active=1, executor=_recording_executor(calls),
                          clock=clock)
    sched.submit("a", {})
    dispatch_a = clock.t
    got = sched.submit("b", {})
    assert got["status"] == "queued"
    sched.complete("a")
    # complete 内部：先 settle（读时钟）再 refill 派发 b（再读时钟）
    assert clock.t >= dispatch_a + 2
    assert calls == ["a", "b"]
    assert sched.snapshot()["n_active"] == 1


def test_scheduler_executor_exception_marks_failed_queue_continues():
    """executor 异常=该任务 failed（席位 hook failed），队列继续补位。"""
    calls: list[str] = []
    hook: list[tuple[str, str]] = []
    sched = TeamScheduler(max_active=2,
                          executor=_recording_executor(calls, fail_on={"bad"}),
                          clock=_FakeClock(),
                          seat_hook=lambda seat, st: hook.append((seat, st)))
    sched.submit("bad", {}, seat_id="s1")
    sched.submit("good", {}, seat_id="s2")
    sched.submit("next", {}, seat_id="s1")     # 槽满入队
    sched.complete("bad", ok=True)             # 执行器已炸过，收尾仍如实落账
    snap = sched.snapshot()
    assert snap["n_active"] == 2 and snap["n_queued"] == 0
    assert ("s1", "working") in hook and ("s1", "done") in hook
    sched.complete("good")
    sched.complete("next")
    assert sched.snapshot()["n_done"] == 3


def test_scheduler_submit_rejects_duplicate_and_default_mock_executor():
    """任务 id 重复拒收；缺省 executor=显式 mock 回执（不静默假装执行）。"""
    sched = TeamScheduler(max_active=2, clock=_FakeClock())
    first = sched.submit("x", {})
    assert first["ok"] and first["status"] == "working"
    dup = sched.submit("x", {})
    assert dup["ok"] is False and "重复" in dup["errors"][0]
    # 缺省 mock 执行器回执 executor=mock（#139：显式暴露无真实执行器）
    assert "executor_error" not in sched._tasks["x"]


def test_scheduler_invalid_max_active_rejected():
    """max_active 非正整数构造即拒（帽值契约）。"""
    for bad in (0, -1, 1.5, True):
        try:
            TeamScheduler(max_active=bad)  # type: ignore[arg-type]
        except ValueError:
            continue
        raise AssertionError(f"max_active={bad!r} 应拒收")


# ─── ② mailbox FIFO 钉（纯内存+可选落盘）────────────────────────────────────

def test_mailbox_fifo_order_per_seat():
    """同席位 send 序=recv 序（FIFO 钉）；跨席位独立；空收 None。"""
    mb = TeamMailbox()
    for i in (3, 1, 2):
        sent = mb.send("s2", {"n": i}, from_seat="s1", kind="probe")
        assert sent["ok"] and sent["seq"] > 0
    mb.send("s1", {"n": 0})
    got = [mb.recv("s2")["payload"]["n"] for _ in range(3)]
    assert got == [3, 1, 2]                 # FIFO：发送序=接收序
    assert mb.recv("s2") is None            # 空队列如实 None
    assert mb.recv("s3") is None            # 未开户席位同样 None
    assert mb.pending("s1") == 1 and mb.pending("s3") == 0
    assert mb.pending_all() == {"s1": 1}


def test_mailbox_optional_spill_disk(tmp_path):
    """spill_dir 给定时逐条 jsonl 落盘（审计副本；序=发送序）。"""
    spill = tmp_path / "spill"
    mb = TeamMailbox(spill_dir=spill)
    for i in range(3):
        mb.send("reviewer", {"idx": i})
    path = spill / "mailbox_reviewer.jsonl"
    assert path.is_file()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    seqs = [json.loads(line)["seq"] for line in lines]
    assert seqs == [1, 2, 3]


def test_mailbox_rejects_empty_target():
    """缺 to_seat 拒收（消息必须有收席）。"""
    got = TeamMailbox().send("", {"n": 1})
    assert got["ok"] is False


# ─── ③ roster 持久化存续 + 席位状态流转 ──────────────────────────────────────

def test_roster_persistence_roundtrip(tmp_path):
    """create_team 落盘→get_team 读回同席位/角色/状态；文件带 experimental。"""
    root = tmp_path / "teams"
    made = create_team(
        "team_w5c", [
            {"seat_id": "tuner", "role": "调优"},
            {"seat_id": "verifier", "role": "验证"},
            {"seat_id": "reviewer", "role": "评审"},
        ],
        description="W5-C 样板队",
        root=root)
    assert made["ok"] and made["n_seats"] == 3 and made["experimental"] is True
    # 新查询口读回（跨调用存续；同 get_goal 存续语义）
    got = get_team("team_w5c", root=root)
    assert got["ok"]
    team = got["team"]
    assert team["schema"] == "rfauto-agent-team-v1"
    assert team["experimental"] is True
    assert [(s["seat_id"], s["role"], s["status"]) for s in team["seats"]] == [
        ("tuner", "调优", "idle"), ("verifier", "验证", "idle"),
        ("reviewer", "评审", "idle")]

    flow = set_seat_status("team_w5c", "tuner", "working", root=root)
    assert flow["ok"]
    reread = get_team("team_w5c", root=root)["team"]
    assert reread["seats"][0]["status"] == "working"   # 流转已落盘
    assert [s["status"] for s in reread["seats"][1:]] == ["idle", "idle"]


def test_roster_rejects_bad_input(tmp_path):
    """席位重复/空/状态词表外拒收（词表外零入口）。"""
    root = tmp_path / "teams"
    dup = create_team("t_dup", [{"seat_id": "a", "role": ""},
                                {"seat_id": "a", "role": ""}], root=root)
    assert dup["ok"] is False
    empty = create_team("t_empty", [], root=root)
    assert empty["ok"] is False
    create_team("t_ok", [{"seat_id": "a", "role": ""}], root=root)
    bad_status = set_seat_status("t_ok", "a", "dancing", root=root)
    assert bad_status["ok"] is False
    no_seat = set_seat_status("t_ok", "ghost", "working", root=root)
    assert no_seat["ok"] is False


# ─── ④ 任务板可视（状态摘要信封；experimental 字段）──────────────────────────

def test_team_board_summary_envelope(tmp_path):
    """board 合并 roster/邮箱/调度面：experimental 信封+计数面一屏读。"""
    root = tmp_path / "teams"
    create_team("team_board", [{"seat_id": "s1", "role": "调优"},
                               {"seat_id": "s2", "role": "评审"}],
                root=root)
    calls: list[str] = []
    sched = TeamScheduler(max_active=1, executor=_recording_executor(calls),
                          clock=_FakeClock())
    mb = TeamMailbox()
    mb.send("s2", {"hello": 1})
    sched.submit("task1", {}, seat_id="s1")
    sched.submit("task2", {}, seat_id="s2")     # 排队

    board = team_board("team_board", root=root, mailbox=mb, scheduler=sched)
    assert board["ok"] and board["experimental"] is True
    summary = board["summary"]
    assert summary["n_seats"] == 2
    assert summary["mailbox_pending"] == {"s2": 1}
    assert summary["scheduler"]["n_active"] == 1
    assert summary["scheduler"]["n_queued"] == 1
    assert summary["scheduler_active"] == ["task1"]
    assert summary["scheduler_queued"] == ["task2"]
    # roster 状态未流转时席位计数=缺省 idle 面（board 是只读视图，零回写）
    assert summary["n_idle"] == 2 and summary["n_working"] == 0


def test_team_board_with_roster_seat_hook_integration(tmp_path):
    """seat_hook 接 roster：派发/收尾流转落盘后 board 席位计数随之读出。"""
    root = tmp_path / "teams"
    create_team("team_hook", [{"seat_id": "s1", "role": "验证"}], root=root)
    calls: list[str] = []
    sched = TeamScheduler(
        max_active=1, executor=_recording_executor(calls), clock=_FakeClock(),
        seat_hook=lambda seat, st: set_seat_status("team_hook", seat, st,
                                                   root=root))
    sched.submit("t1", {}, seat_id="s1")
    board_working = team_board("team_hook", root=root, scheduler=sched)
    assert board_working["summary"]["n_working"] == 1
    sched.complete("t1")
    board_done = team_board("team_hook", root=root, scheduler=sched)
    assert board_done["summary"]["n_done"] == 1
    assert board_done["summary"]["n_working"] == 0


def test_team_board_missing_team_fails(tmp_path):
    """缺席 roster board 如实失败（不猜）。"""
    got = team_board("no_such_team", root=tmp_path / "teams")
    assert got["ok"] is False and "不存在" in got["errors"][0]
