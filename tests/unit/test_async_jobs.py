"""异步 job 链路测试。

钉住的原始问题：run_once_async 返回的 job_id 与 run_once 内部的真实
run_id 无关联，poll_job 永远查不到；结果写入 result_holder 后无人读取。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_cwd_and_registry(tmp_path, monkeypatch):
    """每个用例独立 CWD + 干净注册表，避免互相污染。"""
    monkeypatch.chdir(tmp_path)
    from rfauto.service.job_registry import reset_job_registry
    reset_job_registry()
    yield
    reset_job_registry()


def _recipe(tmp_path: Path) -> Path:
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestRunOnceAsync:
    def test_async_job_lifecycle(self, tmp_path):
        """job_id 必须能轮询到后台 run 的真实 run_id 与最终状态。"""
        from rfauto.service.api import poll_job, run_once_async
        from rfauto.service.job_registry import get_job_registry

        result = run_once_async(_recipe(tmp_path))
        assert result["ok"] is True
        assert result["state"] == "running"
        job_id = result["job_id"]
        assert job_id.startswith("job_"), "job_id 应为 job_ 前缀（与 run_id 可区分）"

        final = get_job_registry().wait(job_id, timeout_s=60)
        assert final is not None
        assert final["state"] == "done"
        assert final["run_id"], "必须回填真实 run_id"

        # run_id 真实存在于磁盘
        assert (Path("runs") / final["run_id"] / "meta.json").exists()

        # poll_job 拿到同一份状态
        polled = poll_job(job_id)
        assert polled["state"] == "done"
        assert polled["run_id"] == final["run_id"]
        assert polled["metrics"], "done 状态应带出 metrics"

    def test_async_job_failure_path(self, tmp_path):
        """后台 run 失败时 job 状态应为 failed 并携带错误信息。"""
        from rfauto.service.api import poll_job, run_once_async
        from rfauto.service.job_registry import get_job_registry

        result = run_once_async(tmp_path / "no_such_recipe.yaml")
        job_id = result["job_id"]

        final = get_job_registry().wait(job_id, timeout_s=60)
        assert final["state"] == "failed"
        assert final["error"]

        polled = poll_job(job_id)
        assert polled["state"] == "failed"
        assert polled["message"]

    def test_poll_unknown_still_unknown(self):
        """registry 未命中 + 磁盘未命中 → unknown（历史行为兼容）。"""
        from rfauto.service.api import poll_job
        polled = poll_job("job_nonexistent_000000")
        assert polled["ok"] is True
        assert polled["state"] == "unknown"

    def test_concurrent_async_jobs(self, tmp_path):
        """并发提交 5 个异步 job，全部可独立追踪到各自 run_id。"""
        from rfauto.service.api import run_once_async
        from rfauto.service.job_registry import get_job_registry

        recipe_path = _recipe(tmp_path)  # 只写一次，避免与后台读线程竞争
        job_ids = [run_once_async(recipe_path)["job_id"] for _ in range(5)]
        run_ids = set()
        for job_id in job_ids:
            final = get_job_registry().wait(job_id, timeout_s=120)
            assert final["state"] == "done", f"{job_id} 失败: {final.get('error') or final.get('result')}"
            run_ids.add(final["run_id"])
        assert len(run_ids) == 5, "5 个 job 应对应 5 个独立 run"


class TestJobRegistryCapacity:
    def test_prune_finished_jobs(self):
        from rfauto.service.job_registry import JobRegistry

        reg = JobRegistry(max_entries=3)
        for i in range(6):
            reg.create(f"job_{i}")
            reg.finish(f"job_{i}")
        reg.create("job_running")

        snap = reg.get("job_5")
        assert snap is not None
        # 超容量时最早的已完成条目被淘汰，运行中的保留
        assert reg.get("job_0") is None
        assert reg.get("job_running") is not None
