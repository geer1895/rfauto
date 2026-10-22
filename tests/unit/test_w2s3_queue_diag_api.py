"""W2-S3 API 合流单测（aurora_i 采纳 #2/#3，全 fake 零网络零真机）.

覆盖：
- /api/campaign_queue 阻塞账合流：queue-daemon 状态档有账 → 逐战役附
  ``queue_block``（人读阻塞原因透出）；无状态档 → 守护未在跑如实降级
  （清单照常零阻塞账）；顶层 ``queue_daemon`` 摘要块；
- /api/runs/<run_id>/failure_context 读面：有包/缺包/run 不存在三态。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from rfauto.service.campaign_queue_daemon import (
    QUEUE_STATE_FILE,
    item_id_of,
    queue_tick,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

_PLAN_MIN = {
    "ok": True,
    "recipe": "recipes/demo.yaml",
    "model": "wilkinson",
    "stages": [
        {"stage": "calibrate", "kind": "calibrate", "adapter": "openems",
         "depends_on": [], "status": "pending", "license_gated": False},
    ],
    "scheduling": {"ok": True, "n_jobs": 1, "predictor_used": False,
                   "budget_gate_used": False, "decision_log": []},
}


@pytest.fixture()
def runs_root(tmp_path, monkeypatch):
    """tmp runs/<id>/campaign.plan.json + runs/campaign_queue/ 状态档根。"""
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "runs" / "camp_a"
    d.mkdir(parents=True)
    (d / "campaign.plan.json").write_text(
        json.dumps(_PLAN_MIN, ensure_ascii=False), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(runs_root):
    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app

    return TestClient(create_ui_app())


def _write_daemon_state(runs_root: Path, *, blocked: bool) -> None:
    """经 queue_tick 造一份真实形态的状态档落默认路径（日历窗驱动阻塞）。"""
    from rfauto.service.campaign_queue_daemon import save_queue_state

    plan_path = str(runs_root / "runs" / "camp_a" / "campaign.plan.json")
    entry = {"item_id": item_id_of(plan_path), "plan_path": plan_path,
             "model": "wilkinson", "verdict": "", "n_stages": 1,
             "license_gated": False}
    cal = {"loaded": True, "state": "blocked" if blocked else "open",
           "launchable": not blocked, "windows_hit": ["wm"] if blocked else [],
           "reason": "备份窗 02:50-05:35 未开"}
    _, state = queue_tick(
        None, queue_fn=lambda root: [entry], calendar_fn=lambda: cal,
        preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
        launcher_fn=lambda p: {"ok": True, "pid": 7, "cmdline": ["x"],
                               "log_path": p + ".log"},
        now_fn=lambda: 100.0)
    save_queue_state(
        state, runs_root / "runs" / "campaign_queue" / QUEUE_STATE_FILE)


class TestQueueBlockMerge:
    def test_blocked_campaign_carries_queue_block(self, runs_root, client):
        _write_daemon_state(runs_root, blocked=True)
        r = client.get("/api/campaign_queue").json()
        assert r["ok"] is True
        assert r["queue_daemon"]["loaded"] is True
        c = r["campaigns"][0]
        blk = c["queue_block"]
        assert blk["code"] == "calendar_blocked"
        assert blk["detail"] == "备份窗 02:50-05:35 未开"
        # 等待时长读侧即时计算（状态档 since=假造 100.0，真实时钟差为正巨值
        # ——断言非负数即口径成立，不锚真实时钟）
        assert isinstance(blk["waited_s"], float) and blk["waited_s"] >= 0.0
        assert "等日历窗" in blk["text"] and "已等" in blk["text"]

    def test_no_state_file_degrades_honestly(self, runs_root, client):
        r = client.get("/api/campaign_queue").json()
        assert r["ok"] is True  # 清单不阻塞（#105）
        assert r["queue_daemon"]["loaded"] is False
        assert all("queue_block" not in c for c in r["campaigns"])

    def test_unblocked_state_carries_no_queue_block(self, runs_root, client):
        _write_daemon_state(runs_root, blocked=False)
        r = client.get("/api/campaign_queue").json()
        assert all("queue_block" not in c for c in r["campaigns"])
        assert r["queue_daemon"]["loaded"] is True


class TestFailureContextEndpoint:
    def test_read_with_context(self, runs_root, client):
        from rfauto.service.failure_context_service import write_failure_context

        d = runs_root / "runs" / "camp_a"
        write_failure_context(
            d, probe_fn=lambda m: {"ok": True, "machines": []},
            preflight_fn=lambda m: {"ok": True, "verdict": "SKIP",
                                    "skipped": True},
            now_fn=lambda: 1.0)
        r = client.get("/api/runs/camp_a/failure_context").json()
        assert r["ok"] is True and r["exists"] is True
        assert r["context"]["schema"] == "rfauto-failure-context-v1"

    def test_read_without_context_exists_false(self, runs_root, client):
        r = client.get("/api/runs/camp_a/failure_context").json()
        assert r["ok"] is True and r["exists"] is False

    def test_read_missing_run_error(self, runs_root, client):
        r = client.get("/api/runs/ghost/failure_context").json()
        assert r["ok"] is False and r["errors"]

    def test_read_traversal_rejected(self, runs_root, client):
        r = client.get("/api/runs/..%5C..%5Cetc/failure_context").json()
        assert r["ok"] is False
