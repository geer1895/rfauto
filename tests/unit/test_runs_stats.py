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


class TestRegistryCoexistence:
    """B④ 默认路径合流收口：runs_stats（裸 sqlite3 只读聚合）与
    RegistryDB（registry.sqlite，schema_version 迁移表）同文件共存——
    CREATE TABLE IF NOT EXISTS 对已有表 no-op、SELECT version 走已迁移行。

    注意方向：RegistryDB 先建库（带 applied_at 列）→ runs_stats 只读，
    这是安全的单向；反向（runs_stats 先建单列 schema_version）不在本波
    合流面内。"""

    _ENV_NAMES = ("RFAUTO_REGISTRY_DB", "RFAUTO_JOB_REGISTRY_DB")

    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for name in self._ENV_NAMES:
            monkeypatch.delenv(name, raising=False)

    def test_runs_summary_over_registry_db_default_path(self, tmp_path, monkeypatch):
        from rfauto.infra.db import RegistryDB, default_registry_db_path
        from rfauto.infra.run_store import record_run
        from rfauto.service.runs_stats import query_runs, runs_summary

        self._isolate(tmp_path, monkeypatch)
        target = default_registry_db_path()  # runs/registry.sqlite
        assert record_run(record={"run_id": "r1", "model": "m", "adapter": "fake",
                                  "status": "done",
                                  "timestamp": "2026-09-05 01:00:00",
                                  "metrics": {"rho": 0.8}})
        # RegistryDB 侧同文件可读（runs 行 + schema_version 迁移行）
        db = RegistryDB(path=target)
        assert db.get_run("r1") is not None
        assert db.current_schema_version() >= 1
        db.close()
        # runs_stats 缺省路径读同一文件：schema_version 有行 → SELECT 分支
        r = runs_summary()
        assert r["ok"] is True
        assert r["total"] == 1
        assert r["recent"][0]["run_id"] == "r1"
        q = query_runs(adapter="fake")
        assert q["ok"] is True and q["n_runs"] == 1

    def test_missing_default_db_reports_reindex_hint(self, tmp_path, monkeypatch):
        from rfauto.service.runs_stats import runs_summary

        self._isolate(tmp_path, monkeypatch)
        r = runs_summary()
        assert r["ok"] is False
        assert "reindex-runs" in r["errors"][0]
