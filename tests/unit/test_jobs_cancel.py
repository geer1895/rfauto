"""jobs cancel 实装测试——排队取消 / 执行中取消请求 / 终态语义。"""

from __future__ import annotations

import time

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from rfauto.service.job_registry import reset_job_registry

    reset_job_registry()
    yield
    reset_job_registry()


def _recipe(tmp_path, name="recipe.yaml"):
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
    }
    path = tmp_path / name
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestRegistryCancel:
    def test_cancel_unstarted_job_is_terminal(self):
        from rfauto.service.job_registry import JobRegistry

        reg = JobRegistry()
        reg.create("job_a")
        snap = reg.cancel("job_a")
        assert snap["state"] == "cancelled"
        assert snap["finished_at"] is not None
        # 终态再取消为空操作
        assert reg.cancel("job_a")["state"] == "cancelled"

    def test_cancel_running_job_requests(self):
        from rfauto.service.job_registry import JobRegistry

        reg = JobRegistry()
        reg.create("job_b")
        assert reg.mark_started("job_b") is True
        snap = reg.cancel("job_b")
        assert snap["state"] == "cancel_requested"
        assert reg.is_cancelled("job_b")
        # 执行器确认终态
        reg.mark_cancelled("job_b", run_id="run_x")
        assert reg.get("job_b")["state"] == "cancelled"
        assert reg.get("job_b")["run_id"] == "run_x"

    def test_mark_started_false_when_cancelled_earlier(self):
        from rfauto.service.job_registry import JobRegistry

        reg = JobRegistry()
        reg.create("job_c")
        reg.cancel("job_c")
        assert reg.mark_started("job_c") is False, "已取消的 job 在执行前检查点必须被拦下"

    def test_cancel_done_job_is_noop(self):
        from rfauto.service.job_registry import JobRegistry

        reg = JobRegistry()
        reg.create("job_d")
        reg.finish("job_d", run_id="r1")
        snap = reg.cancel("job_d")
        assert snap["state"] == "done"
        assert not reg.is_cancelled("job_d")

    def test_cancel_unknown_returns_none(self):
        from rfauto.service.job_registry import JobRegistry

        assert JobRegistry().cancel("job_ghost") is None


class TestAsyncCancel:
    def test_cancel_during_execution_discards_result(self, tmp_path):
        """执行中取消：run 跑完（不可安全中断）但结果按取消丢弃 → cancelled。"""
        from rfauto.service import api as api_mod

        recipe_path = _recipe(tmp_path)
        real_run_once = api_mod.run_once
        executed: list[bool] = []

        def slow_run_once(*a, **kw):
            executed.append(True)
            time.sleep(1.0)  # 放大窗口，保证取消发生在执行期间
            return real_run_once(*a, **kw)

        monkey = pytest.MonkeyPatch()
        monkey.setattr(api_mod, "run_once", slow_run_once)
        try:
            from rfauto.service.api import poll_job, run_once_async
            from rfauto.service.job_registry import get_job_registry

            job_id = run_once_async(recipe_path)["job_id"]
            reg = get_job_registry()
            deadline = time.time() + 5
            while not executed and time.time() < deadline:
                time.sleep(0.02)
            assert executed, "测试前置失败：job 未开始执行"
            snap = reg.cancel(job_id)
            assert snap["state"] in ("cancel_requested", "cancelled")
            final = reg.wait(job_id, timeout_s=30)
            assert final["state"] == "cancelled", f"执行中取消应收敛为 cancelled: {final['state']}"
            assert poll_job(job_id)["message"] == "任务已取消"
        finally:
            monkey.undo()

    def test_poll_cancelled_state(self, tmp_path):
        from rfauto.service.api import poll_job
        from rfauto.service.job_registry import get_job_registry

        job_id = "job_manual_cancel"
        reg = get_job_registry()
        reg.create(job_id)
        reg.cancel(job_id)
        polled = poll_job(job_id)
        assert polled["state"] == "cancelled"
        assert polled["progress_pct"] == 100.0
