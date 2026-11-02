"""league/criteria 冻结帧活湖对照（opt-in；tests/unit/全量门收集面外）。

单元门等价物=tests/unit/test_league_service.py::TestRealRunsReplay 两测
（读冻结帧夹具 tests/fixtures/league_runs_frame.json）与
tests/unit/test_criteria_index_build.py::test_real_runs_tree_no_silent_miss
（读 tests/fixtures/criteria_index_frame.json），均秒级。本件对活湖全扫
（league 候选枚举+逐候选 meta/工件 ~4s；criteria 全树 rglob ~11s，且随
湖增长膨胀），只在显式刷新验证/漂移归因时启用（df4⑥ 家法：真跑集成不
进缺省 unit 门；aurora_m W1-2）：

    RFAUTO_LEAGUE_CRITERIA_LIVE=1 .venv/Scripts/python.exe -m pytest \\
        tests/integration/test_league_criteria_live.py -q

断言与单元门夹具件同性质（活湖行集/entries 指纹=夹具头快照指纹）。用
途：① 夹具刷新后的显式活扫复核（刷新脚本另有内建等价门，本件是门外
的人工复核通道）；② 夹具被怀疑过期时对照活湖定分漂移归因（合法湖演
化 vs 引擎行为变化——指纹红且 stats 漂移=湖演化，指纹红且 stats 同=
引擎行为变化）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
src_dir = REPO / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))
scripts_dir = REPO / "scripts"
if scripts_dir.exists() and str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from criteria_index_build import build_index
from refresh_league_criteria_frames import (
    norm_entries_sha256,
    norm_rows_sha256,
)
from rfauto.service.league_service import collect_league_rows

RUNS = REPO / "runs"
LEAGUE_FRAME = REPO / "tests" / "fixtures" / "league_runs_frame.json"
CRITERIA_FRAME = REPO / "tests" / "fixtures" / "criteria_index_frame.json"


def _require_live_env() -> None:
    if os.environ.get("RFAUTO_LEAGUE_CRITERIA_LIVE") != "1":
        pytest.skip("opt-in 真仓活湖对照：设 RFAUTO_LEAGUE_CRITERIA_LIVE=1 "
                    "启用（league ~4s + criteria ~11s；单元门等价物读冻结"
                    "帧夹具）")
    if not RUNS.is_dir():
        pytest.skip("真仓 runs/ 缺席环境")


def _load_frame(path: Path) -> dict:
    import json
    if not path.is_file():
        pytest.fail(f"冻结帧夹具缺失: {path}——运行 "
                    f"scripts/refresh_league_criteria_frames.py 再生成")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.slow  # 终门 DURATIONS 慢件口径（活湖全扫；本层不在门收集面）
def test_league_frame_matches_live_lake():
    _require_live_env()
    frame = _load_frame(LEAGUE_FRAME)
    collected = collect_league_rows(RUNS)
    assert collected["ok"] is True
    # 活湖行集指纹=夹具快照指纹（湖演化→红=夹具过期，重跑刷新脚本）
    assert norm_rows_sha256(collected["rows"], RUNS) == \
        frame["norm_rows_sha256"]
    live_stats = collected["stats"]
    snap_stats = frame["source_stats"]
    assert live_stats["n_rows"] == snap_stats["n_rows"]
    assert live_stats["n_meta_dirs"] == snap_stats["n_meta_dirs"]
    assert live_stats["n_paired_deltas"] == snap_stats["n_paired_deltas"]
    assert live_stats["skipped"] == snap_stats["skipped"]


@pytest.mark.slow  # 终门 DURATIONS 慢件口径（活湖全树 rglob；本层不在门收集面）
def test_criteria_frame_matches_live_lake():
    _require_live_env()
    frame = _load_frame(CRITERIA_FRAME)
    index = build_index(RUNS)
    assert index["ok"] is True
    # 活湖 entries 指纹=夹具快照指纹（湖演化→红=夹具过期，重跑刷新脚本）
    assert norm_entries_sha256(index) == frame["norm_entries_sha256"]
    assert index["n_files"] == frame["source_stats"]["n_files"]
