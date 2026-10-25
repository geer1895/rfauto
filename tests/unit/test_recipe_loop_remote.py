"""recipe-loop 远跑执行面单测（交接书尾程项 11 末件；全 fake 零真机零网络）。

覆盖口径（任务书四场景+契约面）：
- 正常批次：launcher 调用序列=发射序列，逐点落账（trial_id/params_hash/
  status/metrics/artifact_path），评估一次=一次求解发射；
- 中断重启续跑：同 run_dir 同 seed 重开环 → 采样点逐一命中已 done 记录
  → 整环零发射完整回放，best/轨迹逐位一致；批级重启只重试失败点；
- launcher 异常：如实落 status=failed 账本并向环上抛（failure sample，
  不炸环）；全失败环如实记 n_failures、best=None 不凑绿（#122）；
- 空 loop：bounds 为空 → 环既有错误信封，零发射零记账；
- 契约面：LocalLoopLauncher 返回值契约 / RemoteLoopLauncher 诚实占位
  （NotImplementedError，不伪造远端结果）/ 账本撕裂行计数（#316 多报）。

假 launcher 的 metrics=确定性 bowl 闭式（可复算），目标阈值 -100 保证
cost=f+100 无零平台（#207 种子彩票防线）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.core.objectives import MetricOp, Objective
from rfauto.service.recipe_loop_remote import (
    LEDGER_FILENAME,
    RESULT_FILENAME,
    EvalResult,
    LocalLoopLauncher,
    LoopLauncher,
    LoopLedger,
    RecipeLoopRemoteSession,
    RemoteLoopLauncher,
    params_fingerprint,
    run_recipe_loop_remote,
)

BOUNDS = {"x": (0.0, 1.0), "y": (0.0, 1.0)}
OBJS = [Objective(metric="f", band=[0.0, 1.0], op=MetricOp.MAX_BELOW,
                  value=-100.0, weight=1.0)]
LOOP_KW = dict(n_init=4, top_k=2, virtual_trials=30, max_real=8, seed=7)

# 撕裂行示例（半行 JSON，模拟中断时的未刷完写入）
TORN_LINE = '{"trial_id": "tl-abc", "params_hash": "abc", "sta'


def bowl_metrics(params: dict[str, float]) -> dict[str, float]:
    """确定性 bowl 闭式（谷心 (0.30, 0.62)，可复算）。"""
    x = float(params.get("x", 0.0))
    y = float(params.get("y", 0.0))
    return {"f": (x - 0.30) ** 2 + (y - 0.62) ** 2 + 0.10}


class FakeLauncher:
    """假 launcher：记录调用序列（发射序），metrics=bowl 闭式。"""

    def __init__(self, *, name: str = "fake") -> None:
        self.name = name
        self.calls: list[dict[str, float]] = []

    def evaluate(self, params: dict[str, float]) -> EvalResult:
        self.calls.append(dict(params))
        return EvalResult.from_metrics(bowl_metrics(params))


class FailingLauncher(FakeLauncher):
    """恒失败假 launcher（如实失败记账场景）。"""

    def evaluate(self, params: dict[str, float]) -> EvalResult:
        self.calls.append(dict(params))
        raise ValueError("求解失败: fake boom")


class FlakyLauncher(FakeLauncher):
    """按参数指纹定点失败的假 launcher（失败点重试场景）。"""

    def __init__(self, fail_on: dict[str, float], **kw) -> None:
        super().__init__(**kw)
        self.fail_hash = params_fingerprint(fail_on)

    def evaluate(self, params: dict[str, float]) -> EvalResult:
        if params_fingerprint(params) == self.fail_hash:
            self.calls.append(dict(params))
            raise RuntimeError("定点失败: 目标点求解器崩溃")
        return super().evaluate(params)


@pytest.fixture(autouse=True)
def _isolated_cwd(isolated_cache_off):
    yield


# ─── 契约面 ──────────────────────────────────────────────────────────────────

def test_protocol_runtime_checkable_and_fingerprint_stable():
    assert isinstance(FakeLauncher(), LoopLauncher)
    assert isinstance(LocalLoopLauncher(bowl_metrics), LoopLauncher)
    p = {"x": 0.5, "y": 0.25}
    assert params_fingerprint(p) == params_fingerprint({"y": 0.25, "x": 0.5})
    assert params_fingerprint(p) != params_fingerprint({"x": 0.5, "y": 0.26})


def test_local_launcher_contract():
    ok = LocalLoopLauncher(bowl_metrics).evaluate({"x": 0.3, "y": 0.62})
    assert ok.ok and ok.metrics == {"f": pytest.approx(0.10)}

    # 非 dict 返回 = 契约违约的 ok=False（不抛异常，由会话统一记账）
    bad = LocalLoopLauncher(lambda p: 42).evaluate({"x": 0.1, "y": 0.1})
    assert not bad.ok and "dict" in (bad.error or "")

    # EvalResult 直通（自带产物路径的进阶入口）
    ref = EvalResult.from_metrics({"f": 1.0}, artifact="run/t.s2p")
    passthrough = LocalLoopLauncher(lambda p: ref).evaluate({"x": 0.1})
    assert passthrough is ref and passthrough.artifact == "run/t.s2p"


def test_remote_launcher_honest_placeholder():
    rl = RemoteLoopLauncher("sim_server")
    assert rl.name == "remote:sim_server"
    assert isinstance(rl, LoopLauncher)
    with pytest.raises(NotImplementedError, match="未接线"):
        rl.evaluate({"x": 0.5})
    # 占位语义自描述（路标在 docstring，不伪造结果、不硬编机器细节）
    assert "docstring" in RemoteLoopLauncher.REMOTE_PLACEHOLDER_MSG


def test_ledger_corrupt_line_counted(tmp_path):
    path = tmp_path / LEDGER_FILENAME
    good_done = {"trial_id": "tl-a", "params_hash": "ha", "status": "done",
                 "metrics": {"f": 1.0}}
    good_failed = {"trial_id": "tl-b", "params_hash": "hb",
                   "status": "failed", "error": "boom"}
    path.write_text(
        json.dumps(good_done) + "\n" + TORN_LINE + "\n"
        + json.dumps(good_failed) + "\n",
        encoding="utf-8")
    ledger = LoopLedger(path)
    assert len(ledger.records) == 2
    assert ledger.n_corrupt == 1
    assert set(ledger.completed_map()) == {"ha"}


# ─── 正常批次：发射序=调用序，逐点落账 ─────────────────────────────────────

def test_normal_batch_launch_and_ledger(tmp_path):
    launch = FakeLauncher()
    session = RecipeLoopRemoteSession(tmp_path, launch)
    points = [{"x": 0.1, "y": 0.2}, {"x": 0.5, "y": 0.5}, {"x": 0.9, "y": 0.8}]
    outcomes = session.evaluate_batch(points)

    assert [o["action"] for o in outcomes] == ["launched"] * 3
    assert launch.calls == points  # 发射序=调用序，逐点透传
    for o, pt in zip(outcomes, points, strict=True):
        assert o["metrics"]["f"] == pytest.approx(bowl_metrics(pt)["f"])

    stats = session.stats
    assert stats["n_launched"] == 3 and stats["n_replayed"] == 0
    assert stats["n_ledger_done"] == 3 and stats["n_ledger_failed"] == 0

    # 账本行 schema（任务书口径：trial_id/params 哈希/状态/产物路径）
    lines = (tmp_path / LEDGER_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line, pt in zip(lines, points, strict=True):
        rec = json.loads(line)
        assert rec["params_hash"] == params_fingerprint(pt)
        assert rec["trial_id"] == f"tl-{rec['params_hash'][:12]}"
        assert rec["status"] == "done"
        assert rec["launcher"] == "fake"
        assert rec["metrics"]["f"] == pytest.approx(bowl_metrics(pt)["f"])
        assert rec["artifact_path"] is None  # 拿不到产物如实 None
        assert rec["ts"]


def test_batch_replay_skips_completed(tmp_path):
    launch = FakeLauncher()
    session = RecipeLoopRemoteSession(tmp_path, launch)
    points = [{"x": 0.1, "y": 0.2}, {"x": 0.5, "y": 0.5}]
    session.evaluate_batch(points)

    launch2 = FakeLauncher()
    session2 = RecipeLoopRemoteSession(tmp_path, launch2)
    outcomes = session2.evaluate_batch(points)

    assert launch2.calls == []  # 全部命中 done 记录，零发射
    assert [o["action"] for o in outcomes] == ["replayed", "replayed"]
    for o, pt in zip(outcomes, points, strict=True):
        assert o["metrics"]["f"] == pytest.approx(bowl_metrics(pt)["f"])
    assert session2.stats["n_replayed"] == 2


def test_same_session_duplicate_point_replays_zero_relaunch(tmp_path):
    """同会话幂等口径与跨重启一致：done 记账即时并入缓存——同一参数点
    在会话内第二次评估=回放（不再发射真求解）；failed 点不入表（会话内
    失败点重试语义保持）。"""
    launch = FakeLauncher()
    session = RecipeLoopRemoteSession(tmp_path, launch)
    p = {"x": 0.3, "y": 0.62}
    out1 = session.evaluate_batch([p, dict(p)])
    assert [o["action"] for o in out1] == ["launched", "replayed"]
    assert launch.calls == [p]  # 只发射一次
    assert session.stats["n_launched"] == 1
    assert session.stats["n_replayed"] == 1
    assert out1[1]["metrics"]["f"] == pytest.approx(out1[0]["metrics"]["f"])

    # 失败点会话内不缓存：同点重评仍发射（失败重试，非跳过）
    flaky = FlakyLauncher(fail_on=p)
    session2 = RecipeLoopRemoteSession(tmp_path / "s2", flaky)
    with pytest.raises(RuntimeError, match="定点失败"):
        session2.evaluate(dict(p))
    with pytest.raises(RuntimeError, match="定点失败"):
        session2.evaluate(dict(p))
    assert len(flaky.calls) == 2  # 两次都真发射（失败不进 done 缓存）


# ─── 环级远跑：回填 + 结果落盘 + 断点续跑 ──────────────────────────────────

def test_run_loop_remote_backfill_and_result_file(tmp_path):
    launch = FakeLauncher()
    result = run_recipe_loop_remote(
        BOUNDS, OBJS, launch, tmp_path, **LOOP_KW)

    assert result["ok"] is True
    assert result["best"] is not None
    assert launch.calls  # 环确实发射过
    # 评估一次=一次求解发射：发射数=环真跑尝试数=账本 done 数
    assert len(launch.calls) == result["n_attempts"]
    rex = result["remote_exec"]
    assert rex["launcher"] == "fake"
    assert rex["n_launched"] == len(launch.calls)
    assert rex["n_ledger_done"] == result["n_real_used"]
    assert Path(rex["ledger_path"]).exists()

    out_file = tmp_path / RESULT_FILENAME
    assert out_file.exists()
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["remote_exec"]["n_launched"] == rex["n_launched"]


def test_restart_full_replay_zero_launch_identical_trace(tmp_path):
    """中断重启续跑：同 run_dir 同 seed 重开环 → 整环零发射完整回放。"""
    launch1 = FakeLauncher()
    result1 = run_recipe_loop_remote(BOUNDS, OBJS, launch1, tmp_path, **LOOP_KW)
    n_attempts1 = result1["n_attempts"]

    launch2 = FakeLauncher()
    result2 = run_recipe_loop_remote(BOUNDS, OBJS, launch2, tmp_path, **LOOP_KW)

    assert launch2.calls == []  # 重启零新发射（全部命中已 done 记录）
    assert result2["remote_exec"]["n_launched"] == 0
    assert result2["remote_exec"]["n_replayed"] == n_attempts1
    # 回放的 metrics 逐位一致 → best 与真跑轨迹逐位复现
    assert result2["best"]["cost"] == result1["best"]["cost"]
    assert result2["real_cost_trace"] == result1["real_cost_trace"]


# ─── launcher 异常：如实失败记账 + 失败点重试 ───────────────────────────────

def test_launcher_exception_recorded_then_retried_on_restart(tmp_path):
    flaky = FlakyLauncher(fail_on={"x": 0.5, "y": 0.5})
    session = RecipeLoopRemoteSession(tmp_path, flaky)
    points = [{"x": 0.1, "y": 0.2}, {"x": 0.5, "y": 0.5}, {"x": 0.9, "y": 0.8}]

    with pytest.raises(RuntimeError, match="定点失败"):
        session.evaluate({"x": 0.5, "y": 0.5})
    outcomes = session.evaluate_batch(points)
    by_action = {o["action"] for o in outcomes}
    assert by_action == {"launched", "failed"}
    failed_row = next(o for o in outcomes if o["action"] == "failed")
    assert "定点失败" in failed_row["error"]

    # 失败如实落账（status=failed + error 明细），不冒充 done（#122）
    ledger = LoopLedger(tmp_path / LEDGER_FILENAME)
    assert ledger.count_status("failed") == 2  # evaluate + batch 各一次
    failed_recs = [r for r in ledger.records if r["status"] == "failed"]
    assert all("定点失败" in (r["error"] or "") for r in failed_recs)

    # 重启：失败点重试（不跳过），已完成点跳过
    healthy = FakeLauncher()
    session2 = RecipeLoopRemoteSession(tmp_path, healthy)
    outcomes2 = session2.evaluate_batch(points)
    assert [o["action"] for o in outcomes2] == [
        "replayed", "launched", "replayed"]
    assert healthy.calls == [{"x": 0.5, "y": 0.5}]  # 只有失败点被重发


def test_loop_all_failures_honest_accounting(tmp_path):
    """launcher 恒失败：环如实记 failure sample，best=None 不凑绿（#122）。"""
    launch = FailingLauncher()
    result = run_recipe_loop_remote(BOUNDS, OBJS, launch, tmp_path, **LOOP_KW)

    assert result["ok"] is True  # 环跑完（failure sample 语义），非崩溃
    assert result["best"] is None
    assert result["stop_reason"] == "surrogate_fit_failed"
    assert result["n_real_used"] == 0
    assert result["n_failures"] == LOOP_KW["n_init"]
    assert len(launch.calls) == LOOP_KW["n_init"]
    rex = result["remote_exec"]
    assert rex["n_failed"] == LOOP_KW["n_init"]
    assert rex["n_ledger_failed"] == LOOP_KW["n_init"]
    assert rex["n_ledger_done"] == 0


# ─── 空 loop：零发射零记账 ───────────────────────────────────────────────────

def test_empty_loop_zero_launch(tmp_path):
    launch = FakeLauncher()
    result = run_recipe_loop_remote({}, OBJS, launch, tmp_path, **LOOP_KW)

    assert result["ok"] is False
    assert result["errors"]
    assert launch.calls == []  # 环拒绝后零发射
    rex = result["remote_exec"]
    assert rex["n_launched"] == 0 and rex["n_ledger_done"] == 0
    # 空 loop 无评估 → 账本文件不存在也合法（零记录语义）
    session = RecipeLoopRemoteSession(tmp_path, FakeLauncher())
    assert session.evaluate_batch([]) == []
    assert session.ledger.records == []
