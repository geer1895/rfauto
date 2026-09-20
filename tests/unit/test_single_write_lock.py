"""单写锁测试（计划内缺口 1）—— 并发 hfss job 的 license 互斥。

背景：job_registry 原先只跟踪状态不互斥，并发提交多个 hfss job 会开
多个 AEDT 会话抢 license。本文件验证 SingleWriteLock 的互斥 + FIFO 排队
语义，以及 run_once_async 的串行化编排。
"""

from __future__ import annotations

import threading
import time

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_cwd_and_registry(tmp_path, monkeypatch):
    """每个用例独立 CWD + 干净注册表/写锁，避免互相污染。"""
    monkeypatch.chdir(tmp_path)
    from rfauto.service.job_registry import reset_job_registry
    reset_job_registry()
    yield
    reset_job_registry()


class TestSingleWriteLock:
    def test_exclusive_access(self):
        """同一时间只有一个持有者。"""
        from rfauto.service.job_registry import SingleWriteLock

        lock = SingleWriteLock()
        active: list[str] = []
        max_active = 0
        violations: list[str] = []

        def worker(job_id: str):
            nonlocal max_active
            assert lock.acquire(job_id, timeout_s=10)
            active.append(job_id)
            max_active = max(max_active, len(active))
            if len(active) > 1:
                violations.append(job_id)
            time.sleep(0.05)
            active.remove(job_id)
            lock.release(job_id)

        threads = [threading.Thread(target=worker, args=(f"job_{i}",)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not violations, f"互斥被破坏: {violations}"
        assert lock.owner is None
        assert lock.queue_length == 0

    def test_fifo_order(self):
        """release 后按排队顺序（先到先得）唤醒。"""
        from rfauto.service.job_registry import SingleWriteLock

        lock = SingleWriteLock()
        assert lock.acquire("job_first")
        order: list[str] = []
        started = threading.Event()

        def worker(job_id: str):
            started.set()
            if lock.acquire(job_id, timeout_s=10):
                order.append(job_id)
                lock.release(job_id)

        threads = []
        for i in range(4):
            t = threading.Thread(target=worker, args=(f"job_{i}",))
            # 串行启动保证排队顺序确定性
            t.start()
            deadline = time.time() + 5
            while lock.queue_length <= i and time.time() < deadline:
                time.sleep(0.005)
            threads.append(t)
        lock.release("job_first")
        for t in threads:
            t.join(timeout=15)

        assert order == [f"job_{i}" for i in range(4)], f"FIFO 顺序被破坏: {order}"

    def test_timeout_returns_false(self):
        """带超时的 acquire 在锁被占时按期失败且不占队列。"""
        from rfauto.service.job_registry import SingleWriteLock

        lock = SingleWriteLock()
        assert lock.acquire("job_a")
        assert lock.acquire("job_b", timeout_s=0.1) is False
        assert lock.owner == "job_a"
        assert lock.queue_length == 0
        # job_b 超时退出后仍可重新排队并成功获得锁
        lock.release("job_a")
        assert lock.acquire("job_b", timeout_s=1.0)
        lock.release("job_b")

    def test_release_by_non_owner_is_noop(self):
        from rfauto.service.job_registry import SingleWriteLock

        lock = SingleWriteLock()
        assert lock.acquire("job_a")
        lock.release("job_b")  # 非持有者释放应被忽略
        assert lock.owner == "job_a"
        lock.release("job_a")
        assert lock.owner is None


class TestAsyncJobSerialization:
    def test_concurrent_jobs_serialized(self, tmp_path, monkeypatch):
        """并发提交的异步 job 实际执行互斥——任一时刻至多一个 run 在跑。"""
        from rfauto.service import api as api_mod

        recipe = {
            "model": "wilkinson_power_divider",
            "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
        }
        recipe_path = tmp_path / "recipe.yaml"
        recipe_path.write_text(yaml.safe_dump(recipe), encoding="utf-8")

        real_run_once = api_mod.run_once
        active = threading.Semaphore(1)  # 值为 1：同一时刻至多 1 个 run
        overflow: list[str] = []

        def tracked_run_once(recipe_path, *, adapter_name="fake"):
            name = threading.current_thread().name
            if not active.acquire(blocking=False):
                overflow.append(name)
                raise AssertionError(f"互斥被破坏: {name} 与其他 run 并发执行")
            try:
                time.sleep(0.05)  # 放大窗口
                return real_run_once(recipe_path, adapter_name=adapter_name)
            finally:
                active.release()

        monkeypatch.setattr(api_mod, "run_once", tracked_run_once)

        from rfauto.service.api import run_once_async
        from rfauto.service.job_registry import get_job_registry

        job_ids = [run_once_async(recipe_path)["job_id"] for _ in range(4)]
        for job_id in job_ids:
            final = get_job_registry().wait(job_id, timeout_s=120)
            assert final["state"] == "done", f"{job_id}: {final.get('error')}"

        assert not overflow
        assert get_job_registry().get(job_ids[0])["state"] == "done"
