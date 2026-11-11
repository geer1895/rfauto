"""DP-13 Z1 单测——criteria_index_build 批量抽取与无静默漏抽门。

判据（runs/df6_dp13/criteria.md §Z1）：
- 门阈值行 regex 抽取（正例抽中+阈值、负例零抽中）；
- status 双态 migrate_to_v2|legacy_only；
- 无静默漏抽：index 行数==rglob 扫描文件数（tmp 合成树 + 真实 runs/ 树
  快照双向钉）；
- 输出确定性：同树重跑逐字节一致；
- runs/ 历史文件零改写（builder 只读扫描，写点仅 --out）。

真实 runs/ 树钉（test_real_runs_tree_no_silent_miss）自 aurora_m W1-2 起
改读**冻结帧夹具**（tests/fixtures/criteria_index_frame.json，由
scripts/refresh_league_criteria_frames.py --face criteria 显式刷新）：全树
rglob（含 _/. 前缀目录，264 文件实测）单测内两趟实测 ~13-19s 且随湖增
长膨胀，夹具化后秒级、成本与湖增长脱钩。相等性门语义逐字保留（门是相
等性不是份数常数——在快照材料化树上 index 行数==rglob 文件数恒成立）；
帧内建等价门（材料化回放 entries 与活湖逐键一致才落盘）+测试侧新鲜度钉
（norm_entries_sha256：现引擎在冻结帧上的 entries 指纹=快照时点活帧指
纹）。opt-in 真仓活湖对照件在 tests/integration/test_league_criteria_
live.py（RFAUTO_LEAGUE_CRITERIA_LIVE=1 门控）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from criteria_index_build import build_index, extract_gate_lines, write_index
from refresh_league_criteria_frames import (
    CRITERIA_FRAME_SCHEMA,
    materialize_criteria_tree,
    norm_entries_sha256,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
CRITERIA_FRAME = (_REPO_ROOT / "tests" / "fixtures"
                  / "criteria_index_frame.json")


def test_extract_gate_lines_positive_and_negative():
    text = "\n".join([
        "# 某战役判据",
        "- 谷深 ≤-10dB 才算起振",           # 比较符+单位 → 抽中
        "- 预算帽 ≤12000s，超 1.5×=PARTIAL",  # 比较符+数字+s → 抽中
        "- 偏差 ±0.02mm 以内",               # ±数值 → 抽中
        "- 普通散文行没有判据",              # 无比较符无单位 → 不抽
        "- see docs/rf_template_references.md",  # 无单位词 → 不抽
        "- 上限 10 分钟",                    # 中文单位 → 不抽（regex 外如实漏）
    ])
    gates = extract_gate_lines(text)
    raws = [g["raw"] for g in gates]
    assert len(gates) == 3
    assert any("≤-10dB" in r for r in raws)
    assert any("12000s" in r for r in raws)
    assert any("±0.02mm" in r for r in raws)
    # 阈值抽取：≤ 后首个数值（含负号前缀时取绝对数值部分，如 -10 → 10）
    by_raw = {g["raw"]: g["threshold"] for g in gates}
    assert by_raw["- 谷深 ≤-10dB 才算起振"] == 10.0
    assert by_raw["- 预算帽 ≤12000s，超 1.5×=PARTIAL"] == 12000.0
    assert by_raw["- 偏差 ±0.02mm 以内"] == 0.02


def test_build_index_status_and_no_silent_miss(tmp_path):
    runs = tmp_path / "runs"
    (runs / "camp_a").mkdir(parents=True)
    (runs / "camp_b").mkdir(parents=True)
    (runs / "camp_a" / "nested").mkdir(parents=True)
    (runs / "camp_a" / "criteria.md").write_text(
        "# 战役 A\n- 谷深 ≤-10dB\n", encoding="utf-8")
    (runs / "camp_b" / "criteria.md").write_text(
        "纯散文判读，无结构化门。\n", encoding="utf-8")
    (runs / "camp_a" / "nested" / "criteria.md").write_text(
        "# 嵌套档\n- 谷深 ≤-10dB\n", encoding="utf-8")

    index = build_index(runs)
    scanned = [p.relative_to(runs).as_posix()
               for p in runs.rglob("criteria.md")]
    # 无静默漏抽：index 行数==扫描文件数，且路径集合一一对应
    assert index["n_files"] == len(scanned) == len(index["entries"])
    assert {e["path"] for e in index["entries"]} == set(scanned)
    by_path = {e["path"]: e for e in index["entries"]}
    assert by_path["camp_a/criteria.md"]["status"] == "migrate_to_v2"
    assert by_path["camp_a/criteria.md"]["n_gates"] == 1
    assert by_path["camp_b/criteria.md"]["status"] == "legacy_only"
    assert by_path["camp_b/criteria.md"]["n_gates"] == 0
    assert by_path["camp_a/nested/criteria.md"]["status"] == "migrate_to_v2"
    assert index["schema"] == "rfauto-criteria-index-v1"


def test_write_index_deterministic(tmp_path):
    runs = tmp_path / "runs"
    (runs / "a").mkdir(parents=True)
    (runs / "a" / "criteria.md").write_text(
        "# A\n- ≤0.5dB\n- 门 ≤2%\n", encoding="utf-8")
    index1 = build_index(runs)
    index2 = build_index(runs)
    out1 = write_index(index1, tmp_path / "idx1.yaml")
    out2 = write_index(index2, tmp_path / "idx2.yaml")
    # 同树重跑逐字节一致（确定性输出，无时间戳键）
    assert out1.read_bytes() == out2.read_bytes()
    doc = yaml.safe_load(out1.read_text(encoding="utf-8"))
    assert doc["n_files"] == 1
    assert doc["entries"][0]["n_gates"] == 2
    assert doc["entries"][0]["status"] == "migrate_to_v2"


def test_build_index_missing_root():
    index = build_index(Path("Z:/definitely/not/here"))
    assert index["ok"] is False
    assert index["errors"]


def test_real_runs_tree_no_silent_miss(tmp_path):
    """真实 runs/ 树冻结快照：index 行数==rglob 扫描文件数（相等性门在
    快照材料化树上恒成立——门是相等性不是份数常数；份数以快照 captured
    值注记，活湖漂移由刷新脚本 --check 与 opt-in live 件对照）。"""
    if not CRITERIA_FRAME.is_file():
        pytest.fail(
            f"冻结帧夹具缺失: {CRITERIA_FRAME}——运行 "
            f"scripts/refresh_league_criteria_frames.py --face criteria "
            f"再生成（显式刷新动作，活湖快照 ~11s）；不许 skip 凑绿")
    frame = json.loads(CRITERIA_FRAME.read_text(encoding="utf-8"))
    if frame.get("schema_version") != CRITERIA_FRAME_SCHEMA:
        pytest.fail(
            f"夹具 schema 漂移: {frame.get('schema_version')} != "
            f"{CRITERIA_FRAME_SCHEMA}——重跑刷新脚本再锚定")
    runs = tmp_path / "runs"
    materialize_criteria_tree(frame, runs)
    index = build_index(runs)
    scanned = sorted(
        p.relative_to(runs).as_posix()
        for p in runs.rglob("criteria.md") if p.is_file())
    assert index["ok"] is True
    assert index["n_files"] == len(scanned)
    assert [e["path"] for e in index["entries"]] == scanned
    n_migrate = sum(1 for e in index["entries"]
                    if e["status"] == "migrate_to_v2")
    assert n_migrate + sum(1 for e in index["entries"]
                           if e["status"] == "legacy_only") == len(scanned)
    # 新鲜度钉（W1-2）：现引擎在冻结帧上的 entries 指纹=快照时点活帧指纹；
    # 漂移=引擎抽取行为变化或夹具过期（重跑刷新脚本再锚定）。
    assert norm_entries_sha256(index) == frame["norm_entries_sha256"]
    # 实测份数随行打印（快照 captured 值+回放值，见 criteria.md 附记）
    print(f"frozen runs/ criteria.md count = {len(scanned)} "
          f"(snapshot head {frame['source_head'][:10]}, "
          f"captured live = {frame['source_stats']['n_files']})")
