"""R8 runs/ 卫生盘点脚本单测：合成 tmp 树钉分类/覆盖/归档候选 + 只读保证。

判真口径单源复用 registry_backfill（meta.json + adapter/study 键，#144），
测试树覆盖一层/二层 run 点、`_` 前缀豁免、非 run 目录、顶层散文件。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import runs_inventory as ri


def _make_tree(tmp_path: Path) -> tuple[Path, Path]:
    """runs 树 + 最小 registry（run-a 在册；run-z 为 stale 行）。"""
    root = tmp_path / "runs"
    (root / "A").mkdir(parents=True)
    (root / "A" / "meta.json").write_text(
        '{"adapter": "fake", "run_id": "run-a", "status": "done"}',
        encoding="utf-8")
    (root / "A" / "data.bin").write_bytes(b"a" * 100)
    (root / "B" / "sub").mkdir(parents=True)
    (root / "B" / "meta.json").write_text(
        '{"adapter": "fake", "run_id": "run-b"}', encoding="utf-8")
    (root / "B" / "sub" / "x.bin").write_bytes(b"b" * 600)
    (root / "C").mkdir()
    (root / "C" / "note.txt").write_text("x", encoding="utf-8")
    (root / "_scratch").mkdir()
    (root / "_scratch" / "meta.json").write_text(
        '{"adapter": "fake", "run_id": "run-s"}', encoding="utf-8")
    (root / "f.log").write_bytes(b"l" * 50)

    db = tmp_path / "registry.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY)")
    con.executemany("INSERT INTO runs (run_id) VALUES (?)",
                    [("run-a",), ("run-z",)])
    con.commit()
    con.close()
    return root, db


def test_scan_tree_counts_and_top_file(tmp_path):
    root, _db = _make_tree(tmp_path)
    scan = ri.scan_tree(root)
    tops = {t["name"]: t for t in scan["tops"]}
    assert tops["A"]["kind"] == "dir"
    assert tops["A"]["files"] == 2  # meta.json + data.bin
    assert tops["B"]["files"] == 2
    assert tops["B"]["bytes"] >= 600
    assert tops["f.log"]["kind"] == "file"
    assert tops["f.log"]["bytes"] == 50
    assert scan["files_total"] >= 7  # 2+2+1+1 meta+1 bin+1 note+1 log
    assert scan["bytes_total"] >= 100 + 600 + 50


def test_collect_run_points_judgement_and_prefix_exempt(tmp_path):
    root, _db = _make_tree(tmp_path)
    info = ri.collect_run_points(root)
    # run-s 所在 `_scratch` 被 _run_points 前缀豁免（ge8b 口径）→ 不判真
    assert set(info["run_ids"]) == {"run-a", "run-b"}
    assert info["run_ids"]["run-b"] == "B"  # 二层点：映射到顶层目录名
    assert info["top_dirs"] == {"A", "B"}
    assert info["skipped_meta"] == 0


def test_registry_run_ids_readonly_uri(tmp_path):
    _root, db = _make_tree(tmp_path)
    assert ri.registry_run_ids(db) == {"run-a", "run-z"}
    assert ri.registry_run_ids(tmp_path / "nope.sqlite") is None


def test_archive_candidates_thresholds_and_limit():
    now = time.time()
    tops = [
        {"name": "old_big", "kind": "dir", "bytes": 1000,
         "mtime": now - 200 * 86400},
        {"name": "old_small", "kind": "dir", "bytes": 10,
         "mtime": now - 200 * 86400},
        {"name": "new_big", "kind": "dir", "bytes": 1000,
         "mtime": now - 1 * 86400},
        {"name": "boundary", "kind": "dir", "bytes": 400,
         "mtime": now - 90 * 86400},  # 恰在双阈值边界（<=/>= 收）
        {"name": "file.log", "kind": "file", "bytes": 9999,
         "mtime": now - 999 * 86400},  # 文件不入候选
    ]
    got = ri.archive_candidates(tops, now, min_age_days=90,
                                min_size_bytes=400, limit=10)
    assert [c["name"] for c in got] == ["old_big", "boundary"]
    one = ri.archive_candidates(tops, now, 90, 400, 1)
    assert [c["name"] for c in one] == ["old_big"]  # 体积降序截断
    assert one[0]["age_days"] >= 90


def test_main_end_to_end_and_readonly_db(tmp_path):
    root, db = _make_tree(tmp_path)
    # B 目录与文件调旧 → 归档候选（≥90d 且 ≥0.0005MB）
    old = time.time() - 200 * 86400
    import os
    os.utime(root / "B", (old, old))
    os.utime(root / "B" / "meta.json", (old, old))
    os.utime(root / "B" / "sub" / "x.bin", (old, old))

    db_bytes_before = db.read_bytes()
    out = tmp_path / "rep.json"
    rc = ri.main([
        "--runs-root", str(root), "--db", str(db),
        "--json", str(out),
        "--archive-min-age-days", "90",
        "--archive-min-size-mb", "0.0005",
    ])
    assert rc == 0
    assert db.read_bytes() == db_bytes_before  # 只读保证：registry 零改写

    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["schema"] == ri.REPORT_SCHEMA
    cov = rep["registry_coverage"]
    assert cov["available"] is True
    assert cov["registry_rows"] == 2
    assert cov["judged_run_points"] == 2
    assert cov["backfill_candidates"] == ["run-b"]  # 回填候选=缺口清单
    assert cov["stale_rows_total"] == 1  # run-z 无 meta 点对应
    assert rep["class_counts"]["run"] == 2
    assert rep["class_counts"]["non_run"] == 1
    assert rep["class_counts"]["scratch"] == 1
    names = [c["name"] for c in rep["archive_candidates"]]
    assert names == ["B"]


def test_main_db_unavailable_reports_and_stays_rc0(tmp_path):
    root, _db = _make_tree(tmp_path)
    out = tmp_path / "rep.json"
    rc = ri.main(["--runs-root", str(root), "--db",
                  str(tmp_path / "nope.sqlite"), "--json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["registry_coverage"]["available"] is False


def test_main_rc2_on_missing_root(tmp_path):
    rc = ri.main(["--runs-root", str(tmp_path / "no_runs_dir")])
    assert rc == 2
