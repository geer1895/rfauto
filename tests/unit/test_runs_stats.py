"""阶段 5.5：runs 数据库化查询/统计层测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture
def db_path(tmp_path):
    """预置 3 条 run 记录的索引库。"""
    from rfauto.infra.run_store import record_run

    db = tmp_path / "index.db"
    record_run(db, {"run_id": "r1", "model": "wilkinson_power_divider",
                    "adapter": "fake", "status": "done",
                    "timestamp": "2026-09-05 01:00:00",
                    "metrics": {"rho": 0.8}})
    record_run(db, {"run_id": "r2", "model": "wilkinson_power_divider",
                    "adapter": "calibration:openems", "status": "done",
                    "timestamp": "2026-09-05 02:00:00",
                    "metrics": {"rho": 0.85}})
    record_run(db, {"run_id": "r3", "model": "patch_antenna",
                    "adapter": "fake", "status": "done",
                    "timestamp": "2026-09-05 03:00:00",
                    "metrics": {"rho": 0.7}})
    return str(db)


class TestRunsStats:
    def test_summary_groups(self, db_path):
        from rfauto.service.runs_stats import runs_summary

        r = runs_summary(db_path)
        assert r["ok"]
        assert r["total"] == 3
        assert r["by_model"]["wilkinson_power_divider"] == 2
        assert r["by_adapter"]["fake"] == 2
        assert r["by_status"]["done"] == 3
        assert len(r["recent"]) == 3
        assert r["recent"][0]["run_id"] == "r3"  # 时间倒序

    def test_query_filters(self, db_path):
        from rfauto.service.runs_stats import query_runs

        r = query_runs(db_path, adapter="calibration:openems")
        assert r["ok"] and r["n_runs"] == 1
        assert r["runs"][0]["run_id"] == "r2"
        assert r["runs"][0]["metrics"]["rho"] == 0.85

    def test_missing_db_rejected(self, tmp_path):
        from rfauto.service.runs_stats import runs_summary

        assert not runs_summary(tmp_path / "nope.db")["ok"]
