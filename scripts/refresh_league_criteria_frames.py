"""league/criteria 冻结帧夹具刷新器（aurora_m W1-2；显式动作，不进任何门）。

把以下三个真仓活扫型单测的输入帧再提取为 committed 夹具（W1-1 家法，
commit 828a94a0 范式）：
- tests/unit/test_league_service.py::TestRealRunsReplay::
  test_rebuild_real_tree_and_spot_check_verdicts（manifest 24.4s）
- tests/unit/test_league_service.py::TestRealRunsReplay::
  test_report_on_real_tree_runs（manifest 9.6s）
- tests/unit/test_criteria_index_build.py::test_real_runs_tree_no_silent_
  miss（manifest 12.9s）

【它扫什么】真仓数据湖 runs/（只读）：league 面=候选 run 目录枚举（与
collect_league_rows 同一枚举器，含 lake index 主源+护栏回退语义）+ 逐候
选 meta.json 与 verdict 工件；criteria 面=全树 criteria.md（与测试侧
rglob 同口径，含 _/. 前缀目录——264 文件实测，不跳过）。

【夹具内容】
- tests/fixtures/league_runs_frame.json：全部含内容候选目录（meta 存在
  或 verdict 工件在场的目录）的 meta.json 全文+工件全文。空候选目录不
  入帧（不产生行、不产生 skip 计数；n_candidate_dirs 因此允许与活湖有
  差异，其余 stats 逐键等门）。行集指纹（norm_rows_sha256）=活湖
  collect_league_rows 归一行集 sha256，是单元门的新鲜度钉。
- tests/fixtures/criteria_index_frame.json：全树 criteria.md 全文（相对
  路径+UTF-8 文本），entries 指纹（norm_entries_sha256，剔除 runs_root
  绝对路径键）为新鲜度钉。

写入前内建等价门：夹具材料化到临时树 → 同一引擎代码路径回放 → 行集/
entries 指纹与活湖逐键一致，且测试性质前置（league 行数>500、含 hfss
数值行、抽样板含 FAIL）不过即拒绝落盘——不许把红态洗进单元门。

【何时该刷新】
1. runs/ 湖合法演化后需要重锚快照（--check 红=夹具落后活湖，属预期）；
2. league/criteria 引擎抽取行为变化（norm 指纹红）——先确认行为变化
   合法，再刷新夹具（性质前置仍须过）；
3. 显式活扫对照发现漂移（先跑 RFAUTO_LEAGUE_CRITERIA_LIVE=1 pytest
   tests/integration/test_league_criteria_live.py 定分漂移归因）。

用法：
    .venv/Scripts/python.exe scripts/refresh_league_criteria_frames.py
        # --face all（缺省）：重扫活湖 → 等价门 → 落盘两夹具
    .venv/Scripts/python.exe scripts/refresh_league_criteria_frames.py --face league
    .venv/Scripts/python.exe scripts/refresh_league_criteria_frames.py --face criteria
    .venv/Scripts/python.exe scripts/refresh_league_criteria_frames.py --check
        # 只验证：重扫活湖与现夹具逐键比对，不写盘（漂移 exit 1）

幂等性：夹具内不含墙钟时间戳（快照时点由 source_head+source_stats 承
载）；湖无变化时重复执行输出逐字节一致（git diff 空）。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from criteria_index_build import build_index  # noqa: E402
from rfauto.service.league_service import (  # noqa: E402
    _is_verdict_artifact,
    _iter_candidate_run_dirs,
    lake_index_db_path_for,
)

DEFAULT_LEAGUE_FRAME = REPO / "tests" / "fixtures" / "league_runs_frame.json"
DEFAULT_CRITERIA_FRAME = REPO / "tests" / "fixtures" / "criteria_index_frame.json"
RUNS = REPO / "runs"

LEAGUE_FRAME_SCHEMA = "league_runs_frame/1.0"
CRITERIA_FRAME_SCHEMA = "criteria_index_frame/1.0"


# ---------------------------------------------------------------------------
# 共享工具（单元门测试与 opt-in live 件同源消费，避免两套口径漂移）
# ---------------------------------------------------------------------------

def _load_json_text(text: Any, enc: str = "utf8") -> str:
    """夹具文件值 → 文本（b64 形态解码；现行全帧均为 utf8 直存）。"""
    if isinstance(text, dict) and "b64" in text:
        return base64.b64decode(text["b64"]).decode("utf-8")
    if enc == "b64":
        return base64.b64decode(text).decode("utf-8")
    return text


def _read_text_bytes(path: Path) -> str | None:
    """读文件为文本；非 UTF-8 时回退 b64 形态（{"b64": ...} JSON 值）。"""
    raw = path.read_bytes()
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"b64": base64.b64encode(raw).decode("ascii")}
    return raw.decode("utf-8")


def normalize_league_rows(rows: list[dict[str, Any]], runs_root: Path) -> list[dict]:
    """行集归一：provenance 内绝对路径（meta_path/file）剥离 runs_root
    前缀 → 跨根可比（活湖 vs 材料化树）。"""
    prefix = str(runs_root)
    out: list[dict] = []
    for row in rows:
        r = dict(row)
        prov = json.loads(r["provenance_json"])
        for key in ("meta_path", "file"):
            v = prov.get(key)
            if isinstance(v, str) and v.startswith(prefix):
                prov[key] = "<RUNS>" + v[len(prefix):]
        r["provenance_json"] = json.dumps(prov, sort_keys=True,
                                          ensure_ascii=True)
        out.append(r)
    return out


def norm_rows_sha256(rows: list[dict[str, Any]], runs_root: Path) -> str:
    norm = normalize_league_rows(rows, runs_root)
    blob = json.dumps(norm, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def norm_entries_sha256(index: dict[str, Any]) -> str:
    """criteria index 指纹：剔除 runs_root 绝对路径键后 entries+计数。"""
    payload = {
        "n_files": index.get("n_files"),
        "n_gate_rows": index.get("n_gate_rows"),
        "entries": index.get("entries"),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# league 帧提取
# ---------------------------------------------------------------------------

def capture_league_live() -> dict[str, Any]:
    """活湖 league 帧：collect 全量 + 候选内容目录逐文件快照（只读）。"""
    from rfauto.service.league_service import collect_league_rows

    t0 = time.perf_counter()
    collected = collect_league_rows(RUNS)
    t_collect = time.perf_counter() - t0
    if not collected.get("ok"):
        raise SystemExit(f"2: 活湖 collect 失败: {collected.get('reason')}")

    t0 = time.perf_counter()
    candidates, _notes = _iter_candidate_run_dirs(
        RUNS, db_path=str(lake_index_db_path_for(RUNS)))
    dirs: list[dict[str, Any]] = []
    meta_files = meta_bytes = art_files = art_bytes = 0
    for run_dir, _campaign in candidates:
        meta_path = run_dir / "meta.json"
        art_names = [n for n in sorted(os.listdir(run_dir))
                     if _is_verdict_artifact(n)]
        has_meta = meta_path.is_file()
        if not has_meta and not art_names:
            continue  # 空候选：不产生行与 skip 计数（docstring 声明）
        rec: dict[str, Any] = {
            "p": run_dir.relative_to(RUNS).as_posix(),
            "m": None,
            "a": {},
        }
        if has_meta:
            rec["m"] = _read_text_bytes(meta_path)
            meta_files += 1
            meta_bytes += meta_path.stat().st_size
        for name in art_names:
            ap = run_dir / name
            rec["a"][name] = _read_text_bytes(ap)
            art_files += 1
            art_bytes += ap.stat().st_size
        dirs.append(rec)
    t_snap = time.perf_counter() - t0
    stats = collected.get("stats", {})
    print(f"[live/league] collect={t_collect:.2f}s snapshot={t_snap:.2f}s "
          f"candidates={len(candidates)} content_dirs={len(dirs)} "
          f"meta={meta_files} artifacts={art_files}")
    sha = norm_rows_sha256(collected["rows"], RUNS)
    return {
        "collected": collected,
        "sha": sha,
        "dirs": dirs,
        "counts": {"candidates": len(candidates),
                   "content_dirs": len(dirs),
                   "meta_files": meta_files, "meta_bytes": meta_bytes,
                   "artifact_files": art_files, "artifact_bytes": art_bytes},
        "stats": stats,
    }


def build_league_frame(live: dict[str, Any]) -> str:
    """组 league 帧文本（每目录一行，git diff 可按行读；无墙钟时间戳）。"""
    head = _git_head()
    stats = live["stats"]
    header_stats = {
        "candidates_live": live["counts"]["candidates"],
        "content_dirs": live["counts"]["content_dirs"],
        "meta_files": live["counts"]["meta_files"],
        "meta_bytes": live["counts"]["meta_bytes"],
        "artifact_files": live["counts"]["artifact_files"],
        "artifact_bytes": live["counts"]["artifact_bytes"],
        "n_rows": stats.get("n_rows"),
        "n_meta_dirs": stats.get("n_meta_dirs"),
        "n_paired_deltas": stats.get("n_paired_deltas"),
        "skipped": stats.get("skipped"),
    }
    parts: list[str] = []
    parts.append("{")
    parts.append(f' "schema_version": {json.dumps(LEAGUE_FRAME_SCHEMA)},')
    parts.append(f' "source_head": {json.dumps(head)},')
    parts.append(' "source_stats": '
                 + json.dumps(header_stats, ensure_ascii=False, sort_keys=True) + ",")
    parts.append(f' "norm_rows_sha256": {json.dumps(live["sha"])},')
    parts.append(' "dirs": [')
    recs = sorted(live["dirs"], key=lambda r: r["p"])
    for i, rec in enumerate(recs):
        comma = "," if i < len(recs) - 1 else ""
        parts.append("  " + json.dumps(rec, ensure_ascii=False,
                                       sort_keys=True) + comma)
    parts.append("]")
    parts.append("}")
    return "\n".join(parts) + "\n"


def materialize_league_tree(frame: dict[str, Any], root: Path) -> Path:
    """帧 → 材料化 runs 树（单元门/live 件/等价门三面同源）。"""
    root.mkdir(parents=True, exist_ok=True)
    for rec in frame["dirs"]:
        d = root / rec["p"]
        d.mkdir(parents=True, exist_ok=True)
        if rec["m"] is not None:
            (d / "meta.json").write_text(
                _load_json_text(rec["m"]), encoding="utf-8", newline="")
        for name, val in rec["a"].items():
            (d / name).write_text(_load_json_text(val), encoding="utf-8",
                                  newline="")
    return root


def verify_league_frame(live: dict[str, Any], frame_text: str) -> tuple[bool, list[str]]:
    """等价门：帧材料化 → 引擎回放 → 归一行集/统计与活湖逐键一致。"""
    from rfauto.service.league_service import collect_league_rows

    bad: list[str] = []
    frame = json.loads(frame_text)
    with tempfile.TemporaryDirectory(prefix="league_frame_gate_") as td:
        tree = materialize_league_tree(frame, Path(td) / "runs")
        replay = collect_league_rows(tree)
    if not replay.get("ok"):
        return False, [f"replay_collect_failed:{replay.get('reason')}"]
    sha_replay = norm_rows_sha256(replay["rows"], tree)
    if sha_replay != live["sha"]:
        bad.append(f"rows_sha replay={sha_replay[:12]} live={live['sha'][:12]}")
    ls, rs = live["stats"], replay.get("stats", {})
    for key in ("n_rows", "n_meta_dirs", "n_paired_deltas"):
        if ls.get(key) != rs.get(key):
            bad.append(f"stats.{key} live={ls.get(key)} replay={rs.get(key)}")
    if ls.get("skipped") != rs.get("skipped"):
        bad.append("stats.skipped 逐键不一致")
    return (not bad), bad


def league_frame_properties(collected: dict[str, Any]) -> tuple[bool, list[str]]:
    """测试性质前置（不许把红态洗进夹具）：行数>500、含 hfss 数值行、
    抽样板（工件行前 5+metric 行补足 10）含 ≥1 FAIL。"""
    from rfauto.service.league_service import GATE_VERDICT_QUANTITY

    rows = collected["rows"]
    bad: list[str] = []
    if not len(rows) > 500:
        bad.append(f"n_rows={len(rows)} 不满足 >500")
    hfss_metric = [x for x in rows
                   if x["engine"] == "hfss"
                   and x["quantity"] != GATE_VERDICT_QUANTITY]
    if not hfss_metric:
        bad.append("无 hfss 数值量行")
    artifact_rows = [x for x in rows
                     if json.loads(x["provenance_json"]).get("source")
                     == "verdict_artifact"]
    metric_rows = [x for x in rows
                   if json.loads(x["provenance_json"]).get("source") == "meta"]
    sample = (artifact_rows[:5] + metric_rows)[:10]
    if len(sample) != 10 or not artifact_rows:
        bad.append(f"抽样板不足（sample={len(sample)} artifact_rows="
                   f"{len(artifact_rows)}）")
    elif not any(x["verdict"] == "FAIL" for x in sample):
        bad.append("抽样板无 FAIL 行")
    return (not bad), bad


# ---------------------------------------------------------------------------
# criteria 帧提取
# ---------------------------------------------------------------------------

def capture_criteria_live() -> dict[str, Any]:
    """活湖 criteria 帧：build_index 全量 + 全树 criteria.md 全文。"""
    t0 = time.perf_counter()
    index = build_index(RUNS)
    t_build = time.perf_counter() - t0
    if not index.get("ok"):
        raise SystemExit(f"2: 活湖 build_index 失败: {index.get('errors')}")
    t0 = time.perf_counter()
    files = sorted((p for p in RUNS.rglob("criteria.md") if p.is_file()),
                   key=lambda p: p.relative_to(RUNS).as_posix())
    entries = []
    total = 0
    for p in files:
        text = _read_text_bytes(p)
        entries.append({"p": p.relative_to(RUNS).as_posix(), "t": text})
        total += p.stat().st_size
    t_snap = time.perf_counter() - t0
    print(f"[live/criteria] build_index={t_build:.2f}s snapshot={t_snap:.2f}s "
          f"files={len(files)} bytes={total}")
    return {"index": index, "entries": entries, "n_files": len(files),
            "total_bytes": total,
            "sha": norm_entries_sha256(index)}


def build_criteria_frame(live: dict[str, Any]) -> str:
    head = _git_head()
    header_stats = {
        "n_files": live["n_files"],
        "n_gate_rows": live["index"].get("n_gate_rows"),
        "file_bytes": live["total_bytes"],
    }
    parts: list[str] = []
    parts.append("{")
    parts.append(f' "schema_version": {json.dumps(CRITERIA_FRAME_SCHEMA)},')
    parts.append(f' "source_head": {json.dumps(head)},')
    parts.append(' "source_stats": '
                 + json.dumps(header_stats, ensure_ascii=False, sort_keys=True) + ",")
    parts.append(f' "norm_entries_sha256": {json.dumps(live["sha"])},')
    parts.append(' "files": [')
    for i, rec in enumerate(live["entries"]):
        comma = "," if i < len(live["entries"]) - 1 else ""
        parts.append("  " + json.dumps(rec, ensure_ascii=False) + comma)
    parts.append("]")
    parts.append("}")
    return "\n".join(parts) + "\n"


def materialize_criteria_tree(frame: dict[str, Any], root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rec in frame["files"]:
        p = root / rec["p"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_load_json_text(rec["t"]), encoding="utf-8", newline="")
    return root


def verify_criteria_frame(live: dict[str, Any],
                          frame_text: str) -> tuple[bool, list[str]]:
    bad: list[str] = []
    frame = json.loads(frame_text)
    with tempfile.TemporaryDirectory(prefix="criteria_frame_gate_") as td:
        tree = materialize_criteria_tree(frame, Path(td) / "runs")
        replay = build_index(tree)
    if not replay.get("ok"):
        return False, [f"replay_build_failed:{replay.get('errors')}"]
    sha_replay = norm_entries_sha256(replay)
    if sha_replay != live["sha"]:
        bad.append(f"entries_sha replay={sha_replay[:12]} live={live['sha'][:12]}")
    replay_paths = [e["path"] for e in replay["entries"]]
    live_paths = [e["path"] for e in live["index"]["entries"]]
    if replay_paths != live_paths:
        bad.append("entries.path 列表不一致")
    return (not bad), bad


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _git_head() -> str:
    r = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                       capture_output=True, text=True, check=False)
    return r.stdout.strip() or "unknown"


def _diff_summary(old: dict | None, new: dict) -> list[str]:
    lines: list[str] = []
    if old is None:
        return ["diff: 无现夹具（首次生成）"]
    if old.get("schema_version") != new.get("schema_version"):
        lines.append(f"diff: schema {old.get('schema_version')} -> "
                     f"{new.get('schema_version')}")
    if old.get("source_head") != new.get("source_head"):
        lines.append(f"diff: source_head {str(old.get('source_head'))[:10]} -> "
                     f"{str(new.get('source_head'))[:10]}")
    if old.get("source_stats") != new.get("source_stats"):
        lines.append("diff: source_stats 漂移（湖演化/引擎行为变化）")
    for key in ("norm_rows_sha256", "norm_entries_sha256"):
        if (key in old or key in new) and old.get(key) != new.get(key):
            lines.append(f"diff: {key} 漂移")
    ob = {d["p"] for d in old.get("dirs", [])}
    nb = {d["p"] for d in new.get("dirs", [])}
    of = {f["p"] for f in old.get("files", [])}
    nf = {f["p"] for f in new.get("files", [])}
    added, removed = (nb - ob) | (nf - of), (ob - nb) | (of - nf)
    if added or removed:
        lines.append(f"diff: 帧内路径 +{len(added)}/-{len(removed)}")
        for p in sorted(added)[:5]:
            lines.append(f"  + {p}")
        for p in sorted(removed)[:5]:
            lines.append(f"  - {p}")
    if not lines:
        lines.append("diff: 现夹具已是最新帧（无结构差异）")
    return lines


def _process_league(check: bool) -> int:
    live = capture_league_live()
    props_ok, props_bad = league_frame_properties(live["collected"])
    if not props_ok:
        print(f"[gate] 活湖性质前置不过: {props_bad}——拒绝把红态洗进夹具",
              file=sys.stderr)
        return 4
    print("[gate] 活湖性质前置 PASS（>500 行/hfss 数值行/抽样板含 FAIL）")
    text = build_league_frame(live)
    ok, bad = verify_league_frame(live, text)
    if not ok:
        print(f"[verify] league 等价门不过: {bad}", file=sys.stderr)
        return 3
    print("[verify] league 等价门 PASS（材料化回放行集/统计逐键一致）")
    return _finalize(DEFAULT_LEAGUE_FRAME, text, check, "league")


def _process_criteria(check: bool) -> int:
    live = capture_criteria_live()
    text = build_criteria_frame(live)
    ok, bad = verify_criteria_frame(live, text)
    if not ok:
        print(f"[verify] criteria 等价门不过: {bad}", file=sys.stderr)
        return 3
    print("[verify] criteria 等价门 PASS（材料化回放 entries 逐键一致）")
    return _finalize(DEFAULT_CRITERIA_FRAME, text, check, "criteria")


def _finalize(out: Path, text: str, check: bool, face: str) -> int:
    old: dict | None = None
    if out.is_file():
        try:
            old = json.loads(out.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[diff] 现夹具不可解析（将覆盖）: {exc}")
    if check:
        if old is None:
            print(f"[check] {face}: 无现夹具可验证", file=sys.stderr)
            return 2
        if old == json.loads(text):
            print(f"[check] {face} PASS 夹具与活湖一致")
            return 0
        for line in _diff_summary(old, json.loads(text)):
            print(line)
        print(f"[check] {face} DRIFT 夹具落后于活湖——重跑本脚本（不带 "
              "--check）刷新", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"[write] {out} ({out.stat().st_size} bytes, "
          f"time={time.strftime('%Y-%m-%dT%H:%M:%S')})")
    for line in _diff_summary(old, json.loads(text)):
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="refresh_league_criteria_frames.py",
        description="league/criteria 冻结帧夹具刷新器（aurora_m W1-2；"
                    "活湖快照 league ~6s + criteria ~20s）")
    parser.add_argument("--face", choices=("league", "criteria", "all"),
                        default="all", help="刷新面（缺省 all）")
    parser.add_argument("--check", action="store_true",
                        help="只验证不写盘：重扫活湖与现夹具逐键比对")
    args = parser.parse_args(argv)

    if not RUNS.is_dir():
        print(f"2: 真仓 runs/ 缺席: {RUNS}", file=sys.stderr)
        return 2
    rc = 0
    if args.face in ("league", "all"):
        rc = max(rc, _process_league(args.check))
    if args.face in ("criteria", "all"):
        rc = max(rc, _process_criteria(args.check))
    return rc


if __name__ == "__main__":
    sys.exit(main())
