"""S15（架构批 W4）lake index 批处理消费接线——一致性钉。

R3_perf_quality.md §性能面 Top5：B 类批处理面（health_check_batch /
monitor_cycle / league 候选枚举）改走 lake_runs_index SQL 主源 + 计数
护栏 + 目录扫回退。本文件钉三件事：

1. **枚举对拍**：索引主源 vs 强制回退（db 缺失指认）——三面信封数据键
   逐键一致（同一合成树、同参双跑）；
2. **护栏**：索引滞后（新增目录不改索引）/库缺 → 回退目录扫 + 告警
   注记如实；阈值语义（差值>阈值才回退）；
3. **查询原语**：query_runs_index 新参（depth/has_meta/meta_source）、
   count_runs_index、index_candidate_paths、index_scope_dir_count。

依赖 duckdb（dataset extra），缺失诚实 skip（test_lake_service 同款）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="湖索引需要 dataset extra（duckdb）")

from rfauto.service.health_service import health_check_batch
from rfauto.service.lake_service import (
    LAKE_INDEX_SOURCE_DIRSCAN,
    LAKE_INDEX_SOURCE_INDEX,
    build_runs_index,
    count_runs_index,
    index_candidate_paths,
    index_scope_dir_count,
    lake_index_db_path_for,
    query_runs_index,
)
from rfauto.service.league_service import (
    _iter_candidate_run_dirs,
    collect_league_rows,
)
from rfauto.service.runtime_monitor_service import monitor_cycle

# ---------------------------------------------------------------------------
# 合成 runs/ 树（一树覆盖三面枚举形态）
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _meta(**kw: str) -> dict:
    base = {"model": "mline", "adapter": "fake", "study_name": "s1",
            "status": "done"}
    base.update(kw)
    return base


def _make_tree(root: Path) -> None:
    """合成树：顶层 run / 仅 run_meta.json / 空目录 / 前缀跳过 / 战役两级
    / 排序敏感兄弟（'beta'+'beta-x'，'-'<'/' 边界）/ monitor 产物形态 /
    campaign/runs/<ts> 深层战役点（league 第三层，索引不覆盖）。"""
    _write_json(root / "run_a" / "meta.json",
                _meta(timestamp="2026-10-01T10:00:00"))
    _write_json(root / "run_b" / "meta.json",
                _meta(model="patch", timestamp="2026-10-02T10:00:00"))
    # 仅 run_meta.json：目录扫（meta.json 严格判）不入选；索引 has_meta
    # =True 但 meta_source="run_meta.json"——meta_source 过滤对齐钉
    _write_json(root / "run_alt" / "run_meta.json",
                _meta(timestamp="2026-10-02T11:00:00"))
    (root / "bare").mkdir(parents=True)
    # 前缀跳过（league 语义；health/monitor 不跳）
    _write_json(root / "_skip" / "meta.json",
                _meta(timestamp="2026-10-02T12:00:00"))
    # 战役两级
    _write_json(root / "camp1" / "pt1" / "meta.json",
                _meta(timestamp="2026-10-03T10:00:00", study_name="camp1"))
    (root / "camp1" / "pt2").mkdir(parents=True)
    _write_json(root / "camp1" / "_ptskip" / "meta.json",
                _meta(timestamp="2026-10-03T11:00:00"))
    # 排序钉：目录扫序 = beta, beta/z, beta-x（顶层序→各自子序），
    # 而全路径字符串序会把 beta-x 插在 beta/z 前——重建排序的回归钉
    _write_json(root / "beta" / "z" / "meta.json",
                _meta(timestamp="2026-10-04T10:00:00"))
    _write_json(root / "beta-x" / "meta.json",
                _meta(timestamp="2026-10-04T11:00:00"))
    # monitor 产物形态（无 meta：fdtd 目录 / port_ut_* / et）
    (root / "mon_fdtd" / "fdtd").mkdir(parents=True)
    (root / "mon_port").mkdir(parents=True)
    (root / "mon_port" / "port_ut_1.dat").write_text("1 2\n", encoding="utf-8")
    (root / "mon_et").mkdir(parents=True)
    (root / "mon_et" / "et").write_text("0 0\n", encoding="utf-8")
    # 深层战役点（league 第三层 glob；索引只建两层）
    _write_json(root / "camp2" / "campaign" / "runs" / "20260101_000000"
                / "meta.json",
                _meta(timestamp="2026-10-05T10:00:00", study_name="deep"))


@pytest.fixture()
def wired(tmp_path: Path) -> tuple[Path, str]:
    """合成树 + 已建索引；返回 (树路径, 索引库路径串)。"""
    tree = tmp_path / "runs"
    _make_tree(tree)
    idx = lake_index_db_path_for(tree)
    out = build_runs_index(runs_dir=str(tree), db_path=str(idx))
    assert out["ok"], out.get("errors")
    return tree, str(idx)


def _missing_db(tmp_path: Path) -> str:
    return str(tmp_path / "definitely_missing.duckdb")


# ---------------------------------------------------------------------------
# 查询原语（query 新参 / count / probe / 目录计数）
# ---------------------------------------------------------------------------

class TestQueryScopeParams:
    def test_depth_has_meta_meta_source_filters(self, wired):
        _tree, idx = wired
        q1 = query_runs_index(idx, depth=1, has_meta=True,
                              meta_source="meta.json")
        assert q1["ok"]
        assert {r["run_id"] for r in q1["rows"]} == {
            "run_a", "run_b", "_skip", "beta-x"}
        q2 = query_runs_index(idx, depth=2, campaign="camp1")
        assert q2["ok"]
        assert {r["run_id"] for r in q2["rows"]} == {"pt1", "pt2", "_ptskip"}
        q3 = query_runs_index(idx, has_meta=True, meta_source="run_meta.json")
        assert q3["ok"]
        assert {r["run_id"] for r in q3["rows"]} == {"run_alt"}
        q4 = query_runs_index(idx, depth=1)
        assert {r["run_id"] for r in q4["rows"]} == {
            "run_a", "run_b", "run_alt", "_skip", "beta-x", "bare", "camp1",
            "camp2", "beta", "mon_fdtd", "mon_port", "mon_et"}

    def test_param_validation_errors(self, wired):
        _tree, idx = wired
        assert query_runs_index(idx, depth=True)["ok"] is False  # bool 冒充
        assert query_runs_index(idx, depth="1")["ok"] is False
        assert query_runs_index(idx, has_meta=1)["ok"] is False
        assert query_runs_index(idx, meta_source="")["ok"] is False
        assert query_runs_index(idx, meta_source=3)["ok"] is False


class TestCountAndProbe:
    def test_count_runs_index_scopes(self, wired, tmp_path):
        tree, idx = wired
        n_all = index_scope_dir_count(tree, two_level=True)
        assert count_runs_index(idx) == n_all
        assert count_runs_index(idx, depth=1) == index_scope_dir_count(tree)
        assert count_runs_index(idx, campaign="camp1") == 3
        assert count_runs_index(_missing_db(tmp_path)) is None

    def test_index_scope_dir_count(self, wired):
        tree, _idx = wired
        tops = [p for p in tree.iterdir() if p.is_dir()]
        n1 = index_scope_dir_count(tree)
        assert n1 == len(tops)
        n2 = index_scope_dir_count(tree, two_level=True)
        manual = n1 + sum(1 for t in tops for c in t.iterdir() if c.is_dir())
        assert n2 == manual

    def test_index_scope_dir_count_symlink_not_followed(self, wired):
        """symlink 目录不入计数（架构批 审查波 2 P3-5 收账）。

        is_dir(follow_symlinks=False) 与 _runs_fingerprint 同口径——symlink
        目录计入会让目录侧/索引侧分叉 → 护栏误判滞后 → 无谓回退目录扫。
        Windows 无符号链接特权时诚实 skip（环境类，非口径缺陷）。
        """
        import os

        tree, _idx = wired
        link = tree / "linkdir"
        try:
            os.symlink(tree / "beta", link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("符号链接创建受限（Windows 无开发者模式/特权）")
        n1 = index_scope_dir_count(tree)
        # Path.is_dir(follow_symlinks=) 系 py3.13+ 形参（CI 3.12 实证
        # TypeError）——等价语义=目录且非 symlink（与 DirEntry 口径一致）
        manual = sum(1 for p in tree.iterdir()
                     if p.is_dir() and not p.is_symlink())
        assert n1 == manual
        assert link.is_dir()  # 前提自证：symlink 确实指向目录（但未计数）
        n2 = index_scope_dir_count(tree, two_level=True)
        manual2 = manual + sum(
            1 for t in tree.iterdir()
            if t.is_dir(follow_symlinks=False)
            for c in t.iterdir() if c.is_dir(follow_symlinks=False))
        assert n2 == manual2

    def test_probe_usable_matches_dirscan(self, wired):
        tree, idx = wired
        probe = index_candidate_paths(
            scope_dir=tree, depth=1, has_meta=True, meta_source="meta.json",
            db_path=idx)
        assert probe["usable"] and probe["warnings"] == []
        scan = sorted(p.name for p in tree.iterdir()
                      if p.is_dir() and (p / "meta.json").is_file())
        assert sorted(probe["paths"]) == scan
        assert probe["dir_count"] == index_scope_dir_count(tree)
        assert probe["index_count"] == probe["dir_count"]

    def test_probe_fallback_missing_db(self, wired, tmp_path):
        tree, _idx = wired
        probe = index_candidate_paths(scope_dir=tree, depth=1,
                                      db_path=_missing_db(tmp_path))
        assert probe["usable"] is False
        assert probe["paths"] == []
        assert any("不可用" in w for w in probe["warnings"])

    def test_probe_stale_fallback_and_threshold(self, wired, tmp_path):
        tree, idx = wired
        # 索引建后新增目录（常见漂移态）→ 差值>0 → 回退 + 滞后告警
        _write_json(tree / "run_new" / "meta.json",
                    _meta(timestamp="2026-10-06T10:00:00"))
        probe = index_candidate_paths(scope_dir=tree, depth=1, db_path=idx)
        assert probe["usable"] is False
        assert any("滞后" in w for w in probe["warnings"])
        # 阈值语义：差值≤threshold 仍走索引（如实缺新行——由阈值方担责）
        probe_t = index_candidate_paths(scope_dir=tree, depth=1, db_path=idx,
                                        threshold=1)
        assert probe_t["usable"] is True
        assert "run_new" not in probe_t["paths"]


# ---------------------------------------------------------------------------
# health_check_batch 对拍钉
# ---------------------------------------------------------------------------

_HEALTH_DATA_KEYS = ("n_checked", "verdicts", "healthy", "suspect",
                     "unhealthy", "failed", "truncated", "runs_root",
                     "campaign")


def _assert_health_parity(r_index: dict, r_fallback: dict) -> None:
    assert r_index["ok"] and r_fallback["ok"]
    assert r_index["enumeration_source"] == LAKE_INDEX_SOURCE_INDEX
    assert r_fallback["enumeration_source"] == LAKE_INDEX_SOURCE_DIRSCAN
    assert r_fallback["enumeration_warnings"]
    for key in _HEALTH_DATA_KEYS:
        assert r_index[key] == r_fallback[key], key


class TestHealthBatchWiring:
    def test_parity_default_scan(self, wired, tmp_path):
        tree, idx = wired
        _assert_health_parity(health_check_batch(runs_dir=str(tree),
                                                 db_path=idx),
                              health_check_batch(runs_dir=str(tree),
                                                 db_path=_missing_db(
                                                     tmp_path)))

    def test_parity_filters_and_truncation(self, wired, tmp_path):
        tree, idx = wired
        miss = _missing_db(tmp_path)
        _assert_health_parity(
            health_check_batch(runs_dir=str(tree), template="mline",
                               db_path=idx),
            health_check_batch(runs_dir=str(tree), template="mline",
                               db_path=miss))
        _assert_health_parity(
            health_check_batch(runs_dir=str(tree), since="2026-10-02",
                               db_path=idx),
            health_check_batch(runs_dir=str(tree), since="2026-10-02",
                               db_path=miss))
        # campaign 域：枚举收窄到二级（depth=2 + campaign 过滤）
        _assert_health_parity(
            health_check_batch(runs_dir=str(tree), campaign="camp1",
                               db_path=idx),
            health_check_batch(runs_dir=str(tree), campaign="camp1",
                               db_path=miss))
        # limit 截断语义：截断发生在过滤后（两路径一致）
        _assert_health_parity(
            health_check_batch(runs_dir=str(tree), limit=1, db_path=idx),
            health_check_batch(runs_dir=str(tree), limit=1, db_path=miss))

    def test_run_meta_json_only_not_candidate(self, wired, tmp_path):
        """meta_source 对齐钉：仅 run_meta.json 的目录两路径都不入选。"""
        tree, idx = wired
        for db in (idx, _missing_db(tmp_path)):
            r = health_check_batch(runs_dir=str(tree), db_path=db)
            assert "run_alt" not in r["verdicts"]

    def test_explicit_run_ids_annotated(self, wired, tmp_path):
        tree, idx = wired
        r = health_check_batch(runs_dir=str(tree), run_ids=["run_a", "ghost"],
                               db_path=idx)
        assert r["enumeration_source"] == "explicit"
        assert set(r["verdicts"]) == {"run_a", "ghost"}

    def test_new_dir_after_build_falls_back(self, wired, tmp_path):
        """索引滞后（新 run 落地）→ 回退目录扫如实（新 run 入账不丢）。"""
        tree, idx = wired
        _write_json(tree / "run_new" / "meta.json",
                    _meta(timestamp="2026-10-06T10:00:00"))
        r_index = health_check_batch(runs_dir=str(tree), db_path=idx)
        r_fb = health_check_batch(runs_dir=str(tree),
                                  db_path=_missing_db(tmp_path))
        assert r_index["enumeration_source"] == LAKE_INDEX_SOURCE_DIRSCAN
        assert any("滞后" in w for w in r_index["enumeration_warnings"])
        assert "run_new" in r_index["verdicts"]
        # 两路径都是回退态：数据键仍逐键一致
        for key in _HEALTH_DATA_KEYS:
            assert r_index[key] == r_fb[key], key


# ---------------------------------------------------------------------------
# league 对拍钉
# ---------------------------------------------------------------------------

class TestLeagueWiring:
    def test_candidate_enumeration_parity_and_order(self, wired, tmp_path):
        tree, idx = wired
        cands_i, notes_i = _iter_candidate_run_dirs(tree, db_path=idx)
        cands_f, notes_f = _iter_candidate_run_dirs(
            tree, db_path=_missing_db(tmp_path))
        assert notes_i["enumeration_source"] == LAKE_INDEX_SOURCE_INDEX
        assert notes_f["enumeration_source"] == LAKE_INDEX_SOURCE_DIRSCAN
        assert notes_f["enumeration_warnings"]
        li = [(str(d), c) for d, c in cands_i]
        lf = [(str(d), c) for d, c in cands_f]
        assert li == lf  # 序+成员逐键一致
        # 排序钉：beta 的子 z 紧随 beta，先于兄弟 beta-x（非字符串序）
        keys = [k for k, _c in li]
        assert keys.index(str(tree / "beta")) \
            < keys.index(str(tree / "beta" / "z")) \
            < keys.index(str(tree / "beta-x"))
        # 前缀跳过与深层战役点（索引不覆盖第三层，glob 兜住）
        assert not any("/_skip" in k or k.endswith("\\_skip") or
                       str(tree / "_skip") == k for k in keys)
        assert not any("/_ptskip" in k.replace("\\\\", "/") for k in keys)
        deep = (str(tree / "camp2" / "campaign" / "runs" / "20260101_000000"),
                "camp2")
        assert deep in [(str(d), c) for d, c in cands_i]

    def test_collect_rows_stats_parity(self, wired, tmp_path):
        tree, idx = wired
        r_i = collect_league_rows(tree, db_path=idx)
        r_f = collect_league_rows(tree, db_path=_missing_db(tmp_path))
        assert r_i["ok"] and r_f["ok"]
        assert r_i["enumeration_source"] == LAKE_INDEX_SOURCE_INDEX
        assert r_f["enumeration_source"] == LAKE_INDEX_SOURCE_DIRSCAN
        assert r_i["rows"] == r_f["rows"]
        assert r_i["stats"] == r_f["stats"]
        assert r_i["stats"]["n_candidate_dirs"] == \
            r_f["stats"]["n_candidate_dirs"]


# ---------------------------------------------------------------------------
# monitor_cycle 对拍钉
# ---------------------------------------------------------------------------

class TestMonitorCycleWiring:
    def test_parity_and_artifact_predicate(self, wired, tmp_path):
        tree, idx = wired
        m_i = monitor_cycle(tree, db_path=idx)
        m_f = monitor_cycle(tree, db_path=_missing_db(tmp_path))
        assert m_i["ok"] and m_f["ok"]
        assert m_i["enumeration_source"] == LAKE_INDEX_SOURCE_INDEX
        assert m_f["enumeration_source"] == LAKE_INDEX_SOURCE_DIRSCAN
        assert m_f["enumeration_warnings"]
        for key in ("n_monitored", "verdicts", "red", "yellow", "unknown",
                    "failed", "snapshots"):
            assert m_i[key] == m_f[key], key
        # 产物判定（meta/fdtd/port_ut/et）语义零变化：bare 不入选
        assert "bare" not in m_i["verdicts"]
        assert {"mon_fdtd", "mon_port", "mon_et"} <= set(m_i["verdicts"])
