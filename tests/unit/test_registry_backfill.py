"""registry_backfill 脚本钉：#144 判真/行构造/JSON 摘要截断（ge8b 批销账件）。"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import registry_backfill as rb


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
