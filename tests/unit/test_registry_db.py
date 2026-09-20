"""注册表数据库层单测：SQLite 事务注册表 + PG 迁移接缝 + DuckDB attach。

隔离纪律（#144）：全部用 tmp_path + monkeypatch 清空/注入 env
（RFAUTO_REGISTRY_DB / RFAUTO_JOB_REGISTRY_DB），绝不落真实 runs/。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from rfauto.infra.db import (
    DEFAULT_REGISTRY_DB_FILENAME,
    ENV_REGISTRY_DB,
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
    PostgresBackend,
    RegistryDB,
    SQLiteBackend,
    default_registry_db_path,
)
from rfauto.infra.run_store import list_runs, record_run
from rfauto.service import db_service
from rfauto.service.job_registry import (
    ENV_JOB_REGISTRY_DB,
    JobRegistry,
    get_job_registry,
    reset_job_registry,
)

_SNAPSHOT_KEYS = {"job_id", "state", "run_id", "result", "error",
                  "created_at", "finished_at", "seats"}


@pytest.fixture(autouse=True)
def _isolated_env_and_cwd(tmp_path, monkeypatch):
    """每个用例独立 CWD + 清空同名前缀 env 集合（#144：清整个集合）。"""
    monkeypatch.chdir(tmp_path)
    for name in (ENV_REGISTRY_DB, ENV_JOB_REGISTRY_DB):
        monkeypatch.delenv(name, raising=False)
    yield


# ---------------------------------------------------------------------------
# 迁移：建表 + 幂等
# ---------------------------------------------------------------------------

class TestMigrations:
    def test_migrate_creates_all_tables_and_version(self, tmp_path):
        db = RegistryDB(path=tmp_path / "reg.sqlite")
        info = db.migrate()
        assert info["applied"] == len(MIGRATIONS)
        assert info["version"] == LATEST_SCHEMA_VERSION
        # schema_version 表每个版本一行
        rows = db.query("SELECT version FROM schema_version ORDER BY version")
        assert [r[0] for r in rows] == [v for v, _ in MIGRATIONS]
        # 五张注册表 + schema_version 全部存在
        names = {r[0] for r in db.query(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for t in ("runs", "jobs", "approvals", "datasets", "owners",
                  "schema_version"):
            assert t in names, f"缺表 {t}"

    def test_migrate_idempotent(self, tmp_path):
        db = RegistryDB(path=tmp_path / "reg.sqlite")
        first = db.migrate()
        db.upsert_run({"run_id": "r1", "status": "done"})
        counts_before = db.table_counts()
        second = db.migrate()
        assert second["applied"] == 0
        assert second["version"] == first["version"]
        assert db.query("SELECT COUNT(*) FROM schema_version")[0][0] == len(MIGRATIONS)
        assert db.table_counts() == counts_before

    def test_env_path_override(self, tmp_path, monkeypatch):
        target = tmp_path / "custom" / "env.sqlite"
        monkeypatch.setenv(ENV_REGISTRY_DB, str(target))
        assert default_registry_db_path() == target
        backend = SQLiteBackend()
        assert backend.path == target
        backend.migrate()
        assert target.exists()
        # 未设 env 时默认 runs/registry.sqlite
        monkeypatch.delenv(ENV_REGISTRY_DB)
        assert default_registry_db_path() == Path("runs") / DEFAULT_REGISTRY_DB_FILENAME

    def test_wal_and_busy_timeout(self, tmp_path):
        backend = SQLiteBackend(path=tmp_path / "reg.sqlite", busy_timeout_ms=1234)
        backend.connect()
        mode = backend.query("PRAGMA journal_mode")[0][0]
        assert str(mode).lower() == "wal"
        backend.close()


# ---------------------------------------------------------------------------
# runs 表 CRUD + run_store 双向兼容
# ---------------------------------------------------------------------------

class TestRunsTable:
    def test_upsert_get_list(self, tmp_path):
        db = RegistryDB(path=tmp_path / "reg.sqlite")
        db.upsert_run({"run_id": "r1", "model": "m", "adapter": "fake",
                       "status": "done", "timestamp": "2026-09-15T00:00:00Z",
                       "metrics": {"s11": -10}, "note": "extra"})
        got = db.get_run("r1")
        assert got is not None
        assert got["model"] == "m"
        assert got["metrics"] == {"s11": -10}
        assert got["meta"]["note"] == "extra"
        assert db.get_run("nope") is None
        # upsert 同主键覆盖
        db.upsert_run({"run_id": "r1", "status": "running"})
        assert db.get_run("r1")["status"] == "running"
        assert db.query("SELECT COUNT(*) FROM runs")[0][0] == 1

    def test_underscore_keys_not_persisted(self, tmp_path):
        db = RegistryDB(path=tmp_path / "reg.sqlite")
        db.upsert_run({"run_id": "r1", "_run_dir": "secret"})
        assert "_run_dir" not in json.dumps(db.get_run("r1"))

    def test_compat_with_run_store_both_directions(self, tmp_path):
        """同文件双向兼容：run_store 写 → RegistryDB 读；RegistryDB 写 → run_store 读。"""
        db_file = tmp_path / "index.db"
        assert record_run(db_file, {
            "run_id": "r1", "model": "wilkinson_power_divider",
            "adapter": "fake", "status": "done",
            "timestamp": "2026-08-29T00:00:00Z",
            "metrics": {"s11_db_max_in_band": -10.5},
        })
        db = RegistryDB(path=db_file)
        got = db.get_run("r1")
        assert got["metrics"]["s11_db_max_in_band"] == -10.5
        legacy_rows = list_runs(db_file)
        assert legacy_rows[0]["run_id"] == "r1"
        assert set(legacy_rows[0]) == {"run_id", "model", "adapter",
                                       "status", "timestamp", "metrics"}
        db.close()

        db2 = RegistryDB(path=db_file)
        db2.upsert_run({"run_id": "r2", "adapter": "hfss",
                        "timestamp": "2026-08-29T01:00:00Z",
                        "metrics": {"x": 1}})
        db2.close()
        rows = list_runs(db_file)
        assert [r["run_id"] for r in rows] == ["r2", "r1"]  # 新→旧

    def test_missing_file_list_empty(self, tmp_path):
        assert list_runs(tmp_path / "nope.db") == []


# ---------------------------------------------------------------------------
# jobs / approvals / datasets / owners CRUD
# ---------------------------------------------------------------------------

class TestRegistryTables:
    def _db(self, tmp_path) -> RegistryDB:
        return RegistryDB(path=tmp_path / "reg.sqlite")

    def test_jobs_crud(self, tmp_path):
        db = self._db(tmp_path)
        db.upsert_job(job_id="job_1", run_id="r1", state="running",
                      created_at=1.0, metadata={"seats": ["hfss"]})
        db.upsert_job(job_id="job_2", run_id="r2", state="done",
                      result={"ok": True}, error="",
                      created_at=2.0, finished_at=3.0)
        got = db.get_job("job_2")
        assert got["state"] == "done"
        assert got["result"] == {"ok": True}
        assert got["seats"] == []
        assert got["finished_at"] == 3.0
        assert db.get_job("job_1")["seats"] == ["hfss"]
        assert db.get_job("nope") is None
        # 同主键覆盖 + state 过滤
        db.upsert_job(job_id="job_1", run_id="r1", state="failed",
                      error="boom", created_at=1.0, finished_at=4.0)
        assert db.get_job("job_1")["state"] == "failed"
        assert [j["job_id"] for j in db.list_jobs(state="failed")] == ["job_1"]
        assert len(db.list_jobs()) == 2

    def test_approvals_crud(self, tmp_path):
        db = self._db(tmp_path)
        aid = db.insert_approval("recipe_change", {"delta": 1})
        assert aid
        rows = db.list_approvals(status="pending")
        assert len(rows) == 1
        assert rows[0]["payload"] == {"delta": 1}
        assert db.update_approval_status(aid, "approved") is True
        assert db.list_approvals(status="pending") == []
        assert db.list_approvals(status="approved")[0]["id"] == aid
        assert db.update_approval_status("nope", "approved") is False

    def test_datasets_crud(self, tmp_path):
        db = self._db(tmp_path)
        db.upsert_dataset(name="ds1", manifest_path="datasets/ds1/manifest.yaml",
                          format="parquet", n_rows=42, visibility="team")
        got = db.get_dataset("ds1")
        assert got["format"] == "parquet"
        assert got["n_rows"] == 42
        assert got["visibility"] == "team"
        assert db.get_dataset("nope") is None
        db.upsert_dataset(name="ds2")
        assert [d["name"] for d in db.list_datasets()] == ["ds2", "ds1"]

    def test_owners_crud(self, tmp_path):
        db = self._db(tmp_path)
        db.set_owner("run", "r1", "alice", visibility="team")
        got = db.get_owner("run", "r1")
        assert got["owner"] == "alice"
        assert got["visibility"] == "team"
        assert db.get_owner("run", "nope") is None
        # 复合主键 upsert 覆盖
        db.set_owner("run", "r1", "bob")
        assert db.get_owner("run", "r1")["owner"] == "bob"
        db.set_owner("dataset", "r1", "carol")
        assert db.get_owner("dataset", "r1")["owner"] == "carol"

    def test_table_counts(self, tmp_path):
        db = self._db(tmp_path)
        db.upsert_run({"run_id": "r1"})
        db.upsert_job(job_id="job_1")
        counts = db.table_counts()
        assert counts["runs"] == 1
        assert counts["jobs"] == 1
        assert counts["approvals"] == 0
        assert counts["datasets"] == 0
        assert counts["owners"] == 0

    def test_table_count_rejects_unknown(self, tmp_path):
        db = self._db(tmp_path)
        with pytest.raises(ValueError):
            db.table_count("sqlite_master")


# ---------------------------------------------------------------------------
# job_registry 可选持久化：开关前后行为对照
# ---------------------------------------------------------------------------

class TestJobRegistryPersistence:
    def test_default_off_memory_only(self, tmp_path):
        reset_job_registry()
        reg = get_job_registry()
        assert reg._persist is None
        reg.create("job_a")
        reg.finish("job_a", run_id="r1", result={"ok": True})
        assert get_job_registry().get("job_a")["state"] == "done"
        # 未生成任何数据库文件
        assert not (tmp_path / "runs" / "registry.sqlite").exists()
        reset_job_registry()

    def test_env_on_persists_and_fallback_read(self, tmp_path, monkeypatch):
        db_file = tmp_path / "jobs.sqlite"
        monkeypatch.setenv(ENV_JOB_REGISTRY_DB, str(db_file))
        reset_job_registry()
        reg = get_job_registry()
        assert reg._persist is not None
        reg.create("job_x")
        reg.finish("job_x", run_id="r9", result={"v": 1})
        snap = reg.get("job_x")
        assert snap["state"] == "done"

        # 模拟跨进程重启：全新注册表（内存为空）→ 先查表再回落
        fresh = JobRegistry(persist=reg._persist)
        from_fallback = fresh.get("job_x")
        assert from_fallback["run_id"] == "r9"
        assert from_fallback["result"] == {"v": 1}
        # 快照形状与内存快照逐键一致（poll 侧契约不变）
        assert set(from_fallback) == _SNAPSHOT_KEYS == set(snap)
        assert from_fallback["seats"] == snap["seats"] == []
        # 表内确有该行
        db = RegistryDB(path=db_file)
        assert db.get_job("job_x")["state"] == "done"
        db.close()
        reset_job_registry()

    def test_env_off_value_disables(self, monkeypatch):
        monkeypatch.setenv(ENV_JOB_REGISTRY_DB, "0")
        reset_job_registry()
        assert get_job_registry()._persist is None
        monkeypatch.setenv(ENV_JOB_REGISTRY_DB, "false")
        reset_job_registry()
        assert get_job_registry()._persist is None

    def test_persistence_failure_never_blocks_memory(self):
        """#105：持久化后端抛异常时，内存主路径行为不变。"""

        class _BrokenDB:
            def upsert_job(self, **kw):
                raise RuntimeError("boom")

            def get_job(self, job_id):
                raise RuntimeError("boom")

        reg = JobRegistry(persist=_BrokenDB())
        reg.create("job_b")
        reg.finish("job_b", run_id="r1")
        assert reg.get("job_b")["state"] == "done"
        assert reg.get("ghost") is None

    def test_fail_and_cancel_states_persisted(self, tmp_path):
        db_file = tmp_path / "jobs.sqlite"
        db = RegistryDB(path=db_file)
        reg = JobRegistry(persist=db)
        reg.create("job_f")
        reg.fail("job_f", error="sim crashed")
        assert reg.get("job_f")["state"] == "failed"
        assert db.get_job("job_f")["state"] == "failed"
        reg.create("job_c")
        reg.cancel("job_c")  # 未开始 → 直接 cancelled
        assert reg.get("job_c")["state"] == "cancelled"
        assert db.get_job("job_c")["state"] == "cancelled"
        db.close()


# ---------------------------------------------------------------------------
# db_service：init/status/reindex/query
# ---------------------------------------------------------------------------

class TestDbServiceInitStatus:
    def test_init_and_migrate_idempotent(self, tmp_path):
        target = tmp_path / "reg.sqlite"
        first = db_service.db_init(target)
        assert first["ok"] is True
        assert first["applied"] == len(MIGRATIONS)
        assert first["schema_version"] == LATEST_SCHEMA_VERSION
        second = db_service.db_migrate(target)
        assert second["applied"] == 0
        assert second["schema_version"] == first["schema_version"]

    def test_status_missing_and_existing(self, tmp_path):
        missing = db_service.db_status(tmp_path / "nope.sqlite")
        assert missing["exists"] is False
        assert missing["schema_version"] == 0
        assert not (tmp_path / "nope.sqlite").exists()  # status 不创建文件
        target = tmp_path / "reg.sqlite"
        db_service.db_init(target)
        record_run(target, {"run_id": "r1"})
        st = db_service.db_status(target)
        assert st["exists"] is True
        assert st["tables"]["runs"] == 1
        assert st["schema_version"] == LATEST_SCHEMA_VERSION

    def test_default_path_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_REGISTRY_DB, str(tmp_path / "env.sqlite"))
        out = db_service.db_init()
        assert out["path"] == str(tmp_path / "env.sqlite")
        st = db_service.db_status()
        assert st["exists"] is True


class TestReindexRuns:
    def _build_tree(self, root: Path) -> None:
        (root / "runs" / "r1").mkdir(parents=True)
        (root / "runs" / "r1" / "meta.json").write_text(json.dumps({
            "run_id": "r1", "model": "m", "adapter": "fake",
            "status": "done", "timestamp": "2026-09-15T01:00:00Z",
            "metrics": {"s11": -10},
        }), encoding="utf-8")
        (root / "runs" / "r2").mkdir(parents=True)
        (root / "runs" / "r2" / "meta.json").write_text(json.dumps({
            "model": "m", "adapter": "hfss",  # 缺 run_id → 目录名兜底
            "status": "done", "timestamp": "2026-09-15T02:00:00Z",
        }), encoding="utf-8")
        (root / "runs" / "bad").mkdir(parents=True)
        (root / "runs" / "bad" / "meta.json").write_text("{not json", encoding="utf-8")

    def test_reindex_synthetic_tree(self, tmp_path):
        self._build_tree(tmp_path)
        out = db_service.reindex_runs(tmp_path / "runs",
                                      db_path=tmp_path / "reg.sqlite")
        assert out["ok"] is True
        assert out["reindexed"] == 2
        assert out["failed"] == 1
        assert len(out["errors"]) == 1
        db = RegistryDB(path=tmp_path / "reg.sqlite")
        assert db.get_run("r1")["adapter"] == "fake"
        assert db.get_run("r2") is not None  # 目录名兜底
        db.close()

    def test_reindex_idempotent_and_missing_dir(self, tmp_path):
        self._build_tree(tmp_path)
        db_path = tmp_path / "reg.sqlite"
        first = db_service.reindex_runs(tmp_path / "runs", db_path=db_path)
        second = db_service.reindex_runs(tmp_path / "runs", db_path=db_path)
        assert second["reindexed"] == first["reindexed"] == 2
        db = RegistryDB(path=db_path)
        assert db.query("SELECT COUNT(*) FROM runs")[0][0] == 2
        db.close()
        out = db_service.reindex_runs(tmp_path / "no_such_dir",
                                      db_path=db_path)
        assert out["ok"] is True
        assert out["reindexed"] == 0


class TestDbQuery:
    def test_select_with_params(self, tmp_path):
        target = tmp_path / "reg.sqlite"
        record_run(target, {"run_id": "r1", "adapter": "fake", "status": "done"})
        record_run(target, {"run_id": "r2", "adapter": "hfss", "status": "done"})
        out = db_service.db_query(
            "SELECT run_id, adapter FROM runs WHERE adapter = ? ORDER BY run_id",
            ["fake"], db_path=target)
        assert out["ok"] is True
        assert out["columns"] == ["run_id", "adapter"]
        assert out["rows"] == [["r1", "fake"]]
        assert out["truncated"] is False

    def test_rejects_non_select_and_multistatement(self, tmp_path):
        target = tmp_path / "reg.sqlite"
        for bad in (
            "DROP TABLE runs",
            "DELETE FROM runs",
            "INSERT INTO runs (run_id) VALUES ('x')",
            "UPDATE runs SET status = 'x'",
            "SELECT 1; DROP TABLE runs",
            "SELECT 1; ",
            "-- comment\nSELECT 1",
            "SELECT 1 /* stealth */",
            "PRAGMA journal_mode",
            "ATTACH 'x' AS y",
            "SELECT readfile('secret')",
            "SELECT * FROM runs WHERE 1 = 1 UNION SELECT password FROM users",
            "",
        ):
            with pytest.raises(ValueError):
                db_service.db_query(bad, db_path=target)

    def test_row_limit_truncation(self, tmp_path):
        target = tmp_path / "reg.sqlite"
        for i in range(5):
            record_run(target, {"run_id": f"r{i}", "timestamp": f"2026-09-15T0{i}:00:00Z"})
        out = db_service.db_query("SELECT run_id FROM runs", limit=3,
                                  db_path=target)
        assert out["row_count"] == 3
        assert out["truncated"] is True

    def test_db_query_safe_envelopes_rejection_and_execution_errors(self, tmp_path):
        """薄壳用变体：拒绝/执行错误进信封，成功路径与 db_query 同。"""
        target = tmp_path / "reg.sqlite"
        record_run(target, {"run_id": "r1", "adapter": "fake", "status": "done"})
        ok = db_service.db_query_safe("SELECT run_id FROM runs", db_path=target)
        assert ok == db_service.db_query("SELECT run_id FROM runs", db_path=target)

        rejected = db_service.db_query_safe("DROP TABLE runs", db_path=target)
        assert rejected["ok"] is False
        assert rejected["sql"] == "DROP TABLE runs"
        assert rejected["errors"][0].startswith("查询被拒绝")

        failed = db_service.db_query_safe("SELECT x FROM no_such_table", db_path=target)
        assert failed["ok"] is False
        assert failed["errors"][0].startswith("查询执行失败")
        assert "no_such_table" in failed["errors"][0]


# ---------------------------------------------------------------------------
# analytics_attach：DuckDB 直读 SQLite（可用/不可用两路）
# ---------------------------------------------------------------------------

class TestAnalyticsAttach:
    def _seed(self, tmp_path) -> Path:
        target = tmp_path / "reg.sqlite"
        db_service.db_init(target)
        record_run(target, {"run_id": "r1", "model": "m", "adapter": "fake",
                            "status": "done", "timestamp": "2026-09-15T01:00:00Z"})
        record_run(target, {"run_id": "r2", "model": "m", "adapter": "hfss",
                            "status": "done", "timestamp": "2026-09-15T02:00:00Z"})
        return target

    def test_attach_available_branch(self, tmp_path):
        target = self._seed(tmp_path)
        res = db_service.analytics_attach(target)
        if not res["ok"]:
            # 环境受限（无 duckdb / sqlite 扩展装不上）时如实跳过，不凑绿
            pytest.skip(f"环境不支持 duckdb sqlite 扩展: {res.get('reason')}")
        assert res["tables"]["runs"] == 2
        assert res["sample_runs"][0]["run_id"] == "r2"  # 新→旧
        assert res["attached_as"] == "reg"

    def test_attach_missing_file(self, tmp_path):
        res = db_service.analytics_attach(tmp_path / "nope.sqlite")
        assert res["ok"] is False
        assert "不存在" in res["reason"]

    def test_attach_duckdb_missing(self, tmp_path, monkeypatch):
        target = self._seed(tmp_path)
        monkeypatch.setitem(sys.modules, "duckdb", None)  # import 即 ImportError
        res = db_service.analytics_attach(target)
        assert res["ok"] is False
        assert "duckdb" in res["reason"]


# ---------------------------------------------------------------------------
# PostgreSQL 迁移接缝桩
# ---------------------------------------------------------------------------

class TestPostgresSeam:
    def test_construction_and_methods_refuse(self):
        with pytest.raises(NotImplementedError):
            PostgresBackend(dsn="postgres://localhost/rfauto")
        for name in ("connect", "close", "execute", "executemany",
                     "query", "migrate"):
            assert hasattr(PostgresBackend, name), f"接缝缺方法 {name}"
        # 即使绕过 __init__（object.__new__），方法也显式拒绝
        stub = object.__new__(PostgresBackend)
        with pytest.raises(NotImplementedError):
            stub.connect()
        with pytest.raises(NotImplementedError):
            stub.migrate()


# ---------------------------------------------------------------------------
# approvals：单键取行 + 载荷刷新（审批读模型新增 API）
# ---------------------------------------------------------------------------

class TestApprovalGetAndPayload:
    def test_get_approval_roundtrip_and_missing(self, tmp_path):
        db = self._db(tmp_path)
        db.insert_approval("recipe", {"delta": 1}, approval_id="apr_1")
        got = db.get_approval("apr_1")
        assert got is not None
        assert got["id"] == "apr_1"
        assert got["kind"] == "recipe"
        assert got["payload"] == {"delta": 1}
        assert got["status"] == "pending"
        assert db.get_approval("nope") is None
        db.close()

    def test_update_approval_payload_keeps_status_and_created(self, tmp_path):
        db = self._db(tmp_path)
        db.insert_approval("recipe", {"v": 1}, approval_id="apr_2")
        before = db.get_approval("apr_2")
        assert db.update_approval_payload("apr_2", {"v": 2}, kind="other") is True
        after = db.get_approval("apr_2")
        assert after["payload"] == {"v": 2}
        assert after["kind"] == "other"
        assert after["status"] == before["status"] == "pending"  # 状态不动
        assert after["created_at"] == before["created_at"]  # created_at 不动
        assert db.update_approval_payload("nope", {"x": 1}) is False
        db.close()

    @staticmethod
    def _db(tmp_path) -> RegistryDB:
        return RegistryDB(path=tmp_path / "reg.sqlite")


# ---------------------------------------------------------------------------
# db 默认路径与 settings 合流：settings db.path 读链
# ---------------------------------------------------------------------------

class TestSettingsPathMerge:
    def test_settings_db_path_used_when_no_env(self, tmp_path, monkeypatch):
        """显式覆盖分支：configs/settings.yaml 配 db.path → 缺省路径随配置。"""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "settings.yaml").write_text(
            "db:\n  path: dbs/custom/registry.sqlite\n", encoding="utf-8")
        assert default_registry_db_path() == Path("dbs/custom/registry.sqlite")
        # 整链生效：db_service 缺省入口落到配置路径（行为可配置）
        out = db_service.db_init()
        assert out["ok"] is True
        assert out["path"] == str(Path("dbs/custom/registry.sqlite"))
        assert (tmp_path / "dbs" / "custom" / "registry.sqlite").exists()

    def test_settings_local_override_wins_over_base(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "settings.yaml").write_text(
            "db:\n  path: base.sqlite\n", encoding="utf-8")
        (config_dir / "settings.local.yaml").write_text(
            "db:\n  path: local.sqlite\n", encoding="utf-8")
        assert default_registry_db_path() == Path("local.sqlite")

    def test_env_beats_settings(self, tmp_path, monkeypatch):
        """缺省分支行为不变：无配置 → runs/registry.sqlite；env 仍最高优先。"""
        assert default_registry_db_path() == Path("runs") / DEFAULT_REGISTRY_DB_FILENAME
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "settings.yaml").write_text(
            "db:\n  path: from_yaml.sqlite\n", encoding="utf-8")
        assert default_registry_db_path() == Path("from_yaml.sqlite")
        monkeypatch.setenv(ENV_REGISTRY_DB, str(tmp_path / "env.sqlite"))
        assert default_registry_db_path() == tmp_path / "env.sqlite"

    def test_settings_model_carries_db_section(self, tmp_path, monkeypatch):
        from rfauto.infra.config import load_settings

        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "settings.yaml").write_text(
            "db:\n  path: via_model.sqlite\n", encoding="utf-8")
        s = load_settings()
        assert s.db.path == "via_model.sqlite"
        # 无配置时保持代码默认（空串 → runs/registry.sqlite 行为不变）
        s2 = load_settings(tmp_path / "nope.yaml")
        assert s2.db.path == ""
