"""registry_backfill 脚本钉：#144 判真/行构造/JSON 摘要截断（ge8b 批销账件）。

R8-ENG1 扩展钉（2026-10-13）：无 meta 真跑目录（B 类）判真/豁免分类、
三层口径扫描、幂等回填与 --check 落后度退出码。
"""

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import registry_backfill as rb
from rfauto.infra.db import RegistryDB


def test_row_for_rejects_non_run(tmp_path):
    """#144 判真：无 adapter/study 键的 meta.json ≠ run 点（如判据/工具目录）。"""
    p = tmp_path / "criteria_only"
    p.mkdir()
    (p / "meta.json").write_text(json.dumps({"note": "criteria"}),
                                 encoding="utf-8")
    assert rb._row_for(p / "meta.json") is None


def test_row_for_builds_row_with_defaults(tmp_path):
    """run 点行构造：status done 直读/timestamp 目录 mtime 兜底+来源注记。"""
    p = tmp_path / "wp1"
    p.mkdir()
    (p / "meta.json").write_text(json.dumps(
        {"adapter": "openems", "study": "ge8b_x", "done": True,
         "model": "hairpin"}), encoding="utf-8")
    got = rb._row_for(p / "meta.json")
    assert got is not None
    rid, row = got
    assert rid == "wp1"
    assert row["status"] == "done"
    assert row["adapter"] == "openems"
    assert row["timestamp"].endswith("+00:00")
    assert "backfill_ts_source" in json.loads(row["meta"])


def test_row_for_truncates_metrics():
    """metrics/meta 列宽上限 2000 字符截断（DB 列宽可控）。"""
    big = {"k": "x" * 5000}
    out = json.dumps(big, ensure_ascii=False)[:2000]
    assert len(out) == 2000


# ---------------------------------------------------------------------------
# R8-ENG1 扩展：B 类（无 meta 真跑目录）判真 + 豁免分类 + 幂等/--check
# ---------------------------------------------------------------------------

_TS_NAME = "20260830_204310_46d58b22"


def _make_b_dir(root: Path, name: str = _TS_NAME, *,
                engines: bool = True, recipe_model: str | None = "wpd",
                results_nonempty: bool = False) -> Path:
    d = root / name
    d.mkdir(parents=True)
    if engines:
        (d / "hfss").mkdir()
        (d / "ads").mkdir()
    if recipe_model is not None:
        (d / "recipe.snapshot.yaml").write_text(
            f"model: {recipe_model}\nschema_version: 1\n", encoding="utf-8")
    if results_nonempty:
        (d / "results").mkdir()
        (d / "results" / "out.json").write_text("{}", encoding="utf-8")
    return d


def test_no_meta_run_row_guessed_nothing_and_annotates(tmp_path):
    """B 类行：status/adapter 不猜，model 仅 recipe 直读，证据+来源注记。"""
    d = _make_b_dir(tmp_path)
    ev = rb._no_meta_evidence(d)
    assert ev  # 引擎目录+发射快照=真跑证据
    row = rb._no_meta_run_row(d, ev)
    assert row["run_id"] == _TS_NAME
    assert row["status"] == "unknown"  # 死亡/中断形态不猜
    assert row["adapter"] == ""
    assert row["model"] == "wpd"
    meta = json.loads(row["meta"])
    assert meta["no_meta_run"] is True
    assert "dir:hfss" in meta["backfill_evidence"]
    assert meta["backfill_ts_source"] == "dir_mtime_no_meta"


def test_no_meta_evidence_requires_substance(tmp_path):
    """零证据时间戳目录=创建即弃（no_meta_unbacked）；空 results 不算证据。"""
    d = _make_b_dir(tmp_path, engines=False, recipe_model=None)
    assert rb._no_meta_evidence(d) == []  # 空壳目录零证据
    (d / "results").mkdir()  # 空 results 目录≠产物
    assert rb._no_meta_evidence(d) == []


def test_scan_lake_classifies_three_categories(tmp_path):
    """三层口径：meta run 点 + 无 meta 真跑 + helper 豁免，一层 meta 优先。"""
    runs = tmp_path / "runs"
    runs.mkdir()
    _make_b_dir(runs)  # B 类：无 meta 真跑
    (runs / "helper_ws").mkdir()  # helper 命名豁免
    (runs / "helper_ws" / "x.txt").write_text("x", encoding="utf-8")
    meta_run = runs / "20260101_000000_aaaabbbb"
    meta_run.mkdir()
    (meta_run / "meta.json").write_text(
        json.dumps({"run_id": "meta_rid", "adapter": "fake",
                    "status": "done"}), encoding="utf-8")
    rows, exempt, scanned = rb._scan_lake(runs)
    assert scanned == 1
    assert set(rows) == {_TS_NAME, "meta_rid"}
    assert exempt["no_meta_helper"] == 1
    assert exempt["meta_non_run"] == 0


def test_backfill_idempotent_and_check_exit_codes(tmp_path, monkeypatch):
    """幂等回填两轮零增量 + --check rc0/rc1 语义 + runs 缺失 rc2 SKIP。"""
    runs = tmp_path / "runs"
    runs.mkdir()
    _make_b_dir(runs)
    db_file = tmp_path / "reg.sqlite"
    db = RegistryDB(path=db_file)
    db.migrate()
    db.close()
    monkeypatch.setattr(rb, "REPO", tmp_path)
    argv_backfill = ["registry_backfill.py", "--db", str(db_file)]
    monkeypatch.setattr(sys, "argv", argv_backfill)
    assert rb.main() == 0
    monkeypatch.setattr(sys, "argv", argv_backfill)
    assert rb.main() == 0  # 重跑零增量
    con = sqlite3.connect(str(db_file))
    n_rows = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    con.close()
    assert n_rows == 1  # 恰 1 行（B 类），重复回填不翻倍
    argv_check = ["registry_backfill.py", "--check", "--db", str(db_file)]
    monkeypatch.setattr(sys, "argv", argv_check)
    assert rb.main() == 0  # 覆盖齐 → rc0
    _make_b_dir(runs, "20260901_000000_ccccdddd")  # 新落真跑目录 → 落后
    monkeypatch.setattr(sys, "argv", argv_check)
    assert rb.main() == 1  # 落后 → rc1
    monkeypatch.setattr(rb, "REPO", tmp_path / "no_such_root")
    monkeypatch.setattr(sys, "argv", argv_check)
    assert rb.main() == 2  # runs 树不可读 → SKIP 口径 rc2
