"""registry_runs_query 服务单入口钉（R8-ENG1 单源地基件，2026-10-13）。

只读信封进出：过滤/排序/截断/库缺失 ok+exists=False/坏库 error 信封，
过滤值 ? 绑定零拼串。UI runs 端点接线归后续席，本钉只锁地基行为。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from rfauto.infra.db import RegistryDB
from rfauto.service.db_service import registry_runs_query


def _make_db(tmp_path: Path, rows: list[dict]) -> Path:
    db_file = tmp_path / "reg.sqlite"
    db = RegistryDB(path=db_file)
    db.migrate()
    for r in rows:
        db.upsert_run(r)
    db.close()
    return db_file


def test_query_returns_envelope_with_contract_row_shape(tmp_path):
    """信封形状：ok/runs/n_rows/truncated/limit/exists；行字段与消费契约对齐。"""
    db_file = _make_db(tmp_path, [
        {"run_id": "r1", "model": "wpd", "adapter": "openems",
         "status": "done", "timestamp": "2026-10-01T00:00:00+00:00",
         "metrics": {"s11": -15.0}, "meta": {"seed": 1}},
        {"run_id": "r2", "model": "patch", "adapter": "hfss",
         "status": "failed", "timestamp": "2026-10-02T00:00:00+00:00"},
    ])
    env = registry_runs_query(db_path=db_file)
    assert env["ok"] is True
    assert env["exists"] is True
    assert env["truncated"] is False
    assert env["n_rows"] == 2
    assert [r["run_id"] for r in env["runs"]] == ["r2", "r1"]  # timestamp 降序
    row = env["runs"][1]
    assert set(row) == {"run_id", "model", "adapter", "status", "git_sha",
                        "timestamp", "metrics"}
    assert row["metrics"] == {"s11": -15.0}  # metrics 已解析成 dict


def test_query_filters_exact_match_bound_params(tmp_path):
    """过滤键精确匹配（值绑定不拼串）；无命中=空集非报错。"""
    db_file = _make_db(tmp_path, [
        {"run_id": "r1", "adapter": "openems", "status": "done",
         "model": "wpd", "timestamp": "2026-10-01T00:00:00+00:00"},
        {"run_id": "r2", "adapter": "hfss", "status": "failed",
         "model": "wpd", "timestamp": "2026-10-02T00:00:00+00:00"},
    ])
    env = registry_runs_query(adapter="hfss", db_path=db_file)
    assert [r["run_id"] for r in env["runs"]] == ["r2"]
    env = registry_runs_query(adapter="hfss", status="failed",
                              db_path=db_file)
    assert [r["run_id"] for r in env["runs"]] == ["r2"]
    env = registry_runs_query(status="done", model="wpd", db_path=db_file)
    assert [r["run_id"] for r in env["runs"]] == ["r1"]
    env = registry_runs_query(run_id="nope", db_path=db_file)
    assert env["ok"] is True and env["n_rows"] == 0 and env["runs"] == []


def test_query_truncates_at_limit(tmp_path):
    """limit 截断如实标记（多取 1 行判截断，db_query 同款）。"""
    db_file = _make_db(tmp_path, [
        {"run_id": f"r{i}", "timestamp": f"2026-10-{i:02d}T00:00:00+00:00"}
        for i in range(1, 6)
    ])
    env = registry_runs_query(limit=3, db_path=db_file)
    assert env["n_rows"] == 3 and env["truncated"] is True
    assert [r["run_id"] for r in env["runs"]] == ["r5", "r4", "r3"]


def test_query_missing_db_ok_empty_exists_false(tmp_path):
    """库文件不存在：ok=True + exists=False + 空集（UI 空态友好，不 raise）。"""
    env = registry_runs_query(db_path=tmp_path / "nope.sqlite")
    assert env["ok"] is True
    assert env["exists"] is False
    assert env["runs"] == [] and env["n_rows"] == 0


def test_query_unreadable_db_error_envelope(tmp_path):
    """坏库文件（非 SQLite）：ok=False 信封，绝不 raise（薄壳零逻辑直渲染）。"""
    bad = tmp_path / "bad.sqlite"
    bad.write_text("this is not a database", encoding="utf-8")
    env = registry_runs_query(db_path=bad)
    assert env["ok"] is False
    assert env["errors"]


def test_query_is_read_only(tmp_path):
    """查询后行数与内容零变化（只读面）。"""
    db_file = _make_db(tmp_path, [
        {"run_id": "r1", "status": "unknown",
         "timestamp": "2026-10-01T00:00:00+00:00"}])
    before = sqlite3.connect(str(db_file)).execute(
        "SELECT run_id, status FROM runs").fetchall()
    registry_runs_query(db_path=db_file)
    after = sqlite3.connect(str(db_file)).execute(
        "SELECT run_id, status FROM runs").fetchall()
    assert before == after
    assert json.loads(json.dumps(before)) == [["r1", "unknown"]]
