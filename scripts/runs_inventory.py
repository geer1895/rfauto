"""runs/ 湖卫生盘点（aurora72 R8 附录 250GB 面 + 可立项 #8 审计半边；
2026-10-11 A7-D 席）。

**零删除零移动零改写**：runs/ 永不在清理范围（内核立规注记 硬规则 3），本脚本
只盘点——归档候选清单仅供用户决策，处置权在用户；registry 覆盖缺口只
报告不代跑回填（处置=既有的 scripts/registry_backfill.py 一条命令幂等
回填，ge8b 先例）。registry 打开走 sqlite 只读 URI（mode=ro），全脚本
除 --json 显式报告路径外无任何写面。

四面产出：
1. 规模面：顶层条目/嵌套目录/文件数/总字节（os.walk 单遍 stat 累计，
   不读文件内容；全树实测 ~35s/2.6 万目录/22.4 万文件/267GB，
   2026-10-11 A7-D）。
2. 分类面：顶层目录按 registry_backfill 判真口径单源复用（meta.json
   存在且含 adapter/study 任一键=#144，两层深度）→ run 点所在顶层目录
   vs 非 run 目录（报告/战役/scratch 区，`_`/`.` 前缀按 ge8b 口径豁免）。
3. registry 覆盖面（只读）：meta 判真 run 点的 run_id 与
   runs/registry.sqlite ``runs`` 表差集 → **回填候选**（缺行清单）；
   反向 = registry 行无 meta 点对应（已删目录/非标准 run_id）计数+样本。
4. 归档候选面：顶层目录 mtime 年龄 ≥ --archive-min-age-days 且体积
   ≥ --archive-min-size-mb → 按体积降序清单（只列不动作）。

rc：0=正常盘点；2=runs 根不可用（盘点跑不起来，环境类如实报）。

用法：
  .venv/Scripts/python.exe scripts/runs_inventory.py [--json <out>]
      [--runs-root <path>] [--db <path>] [--top 20]
      [--archive-min-age-days 90] [--archive-min-size-mb 500]
      [--archive-limit 200] [--skip-registry]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from registry_backfill import _row_for, _run_points  # noqa: E402

REPORT_SCHEMA = "r8/runs_inventory/1"


def scan_tree(runs_root: Path) -> dict:
    """单遍盘点：顶层逐条目 os.walk 累计文件数/字节/最新 mtime（stat 级，
    零内容读取）。返回 totals 与 top 条目明细。"""
    tops: list[dict] = []
    total_files = 0
    total_bytes = 0
    total_dirs = 0  # 含顶层
    for entry in sorted(runs_root.iterdir(), key=lambda p: p.name):
        try:
            st = entry.stat()
        except OSError:
            continue
        if entry.is_dir():
            files = 0
            nbytes = 0
            latest = st.st_mtime
            for dp, _dns, fns in os.walk(entry):
                total_dirs += 1
                for fn in fns:
                    files += 1
                    try:
                        fst = os.stat(os.path.join(dp, fn))
                    except OSError:
                        continue
                    nbytes += fst.st_size
                    latest = max(latest, fst.st_mtime)
            total_files += files
            total_bytes += nbytes
            total_dirs += 1
            tops.append({
                "name": entry.name, "kind": "dir", "files": files,
                "bytes": nbytes, "mtime": latest,
            })
        else:
            total_files += 1
            total_bytes += st.st_size
            tops.append({
                "name": entry.name, "kind": "file", "files": 1,
                "bytes": st.st_size, "mtime": st.st_mtime,
            })
    return {
        "top_entries": len(tops), "dirs_total": total_dirs,
        "files_total": total_files, "bytes_total": total_bytes,
        "tops": tops,
    }


def collect_run_points(runs_root: Path) -> dict:
    """registry_backfill 判真口径单源复用：meta 判真 run 点 →
    run_id→顶层目录名映射 + 判真点顶层祖先集合（同 id 一/二层取首见，
    与回填同序；单遍历，分类与覆盖共用）。"""
    rows: dict[str, str] = {}
    top_dirs: set[str] = set()
    skipped = 0
    for mp in _run_points(runs_root):
        got = _row_for(mp)
        if got is None:
            skipped += 1
            continue
        rid, _row = got
        rows.setdefault(rid, mp.parent.name)
        rel = mp.parent.relative_to(runs_root)
        top_dirs.add(rel.parts[0])
    return {"run_ids": rows, "skipped_meta": skipped, "top_dirs": top_dirs}


def registry_run_ids(db_path: Path) -> set[str] | None:
    """runs 表 run_id 全集（只读 URI）；库不可用返回 None。"""
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        return {str(r[0]) for r in con.execute("SELECT run_id FROM runs")}
    except sqlite3.Error:
        return None
    finally:
        con.close()


def archive_candidates(
    tops: list[dict],
    now: float,
    min_age_days: int,
    min_size_bytes: int,
    limit: int,
) -> list[dict]:
    """归档候选（纯函数）：顶层目录年龄与体积双阈值，按体积降序截断。"""
    min_ts = now - min_age_days * 86400
    cands = [
        {"name": t["name"], "bytes": t["bytes"],
         "age_days": int((now - t["mtime"]) // 86400)}
        for t in tops
        if t["kind"] == "dir" and t["mtime"] <= min_ts
        and t["bytes"] >= min_size_bytes
    ]
    cands.sort(key=lambda d: -d["bytes"])
    return cands[: max(limit, 0)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="runs/ 湖卫生盘点（只读）")
    ap.add_argument("--runs-root", default=str(REPO / "runs"))
    ap.add_argument("--db", default=str(REPO / "runs" / "registry.sqlite"))
    ap.add_argument("--json", dest="json_out", default="",
                    help="报告 JSON 落盘路径（唯一写面）")
    ap.add_argument("--top", type=int, default=20,
                    help="体积 Top-N 清单长度")
    ap.add_argument("--archive-min-age-days", type=int, default=90)
    ap.add_argument("--archive-min-size-mb", type=float, default=500.0)
    ap.add_argument("--archive-limit", type=int, default=200)
    ap.add_argument("--skip-registry", action="store_true",
                    help="跳过 registry 覆盖面（省 meta 逐个判真开销）")
    args = ap.parse_args(argv)

    runs_root = Path(args.runs_root)
    if not runs_root.is_dir():
        print(f"[SKIP] runs 根不可用：{runs_root}")
        return 2
    t0 = time.monotonic()
    scan = scan_tree(runs_root)

    run_point_info: dict = {"run_ids": {}, "skipped_meta": 0, "top_dirs": set()}
    if not args.skip_registry:
        run_point_info = collect_run_points(runs_root)
        for t in scan["tops"]:
            if t["kind"] != "dir":
                continue
            if t["name"].startswith(("_", ".")):
                t["class"] = "scratch"
            elif t["name"] in run_point_info["top_dirs"]:
                t["class"] = "run"
            elif t["files"] == 0:
                t["class"] = "empty"
            else:
                t["class"] = "non_run"

    db_path = Path(args.db)
    reg_ids = None if args.skip_registry else registry_run_ids(db_path)
    coverage: dict = {"available": reg_ids is not None}
    if reg_ids is not None:
        cand_ids = set(run_point_info["run_ids"])
        missing = sorted(cand_ids - reg_ids)
        stale = sorted(reg_ids - cand_ids)
        coverage.update({
            "registry_rows": len(reg_ids),
            "judged_run_points": len(cand_ids),
            "backfill_candidates": missing,
            "stale_rows_sample": stale[:50],
            "stale_rows_total": len(stale),
        })

    now = time.time()
    archive = archive_candidates(
        scan["tops"], now, args.archive_min_age_days,
        int(args.archive_min_size_mb * 1024 * 1024), args.archive_limit)

    top_by_bytes = sorted(
        (t for t in scan["tops"] if t["kind"] == "dir"),
        key=lambda t: -t["bytes"])[: max(args.top, 0)]
    for t in top_by_bytes:
        t["age_days"] = int((now - t["mtime"]) // 86400)

    class_counts: dict[str, int] = {}
    for t in scan["tops"]:
        if t["kind"] == "dir":
            c = t.get("class", "unclassified")
            class_counts[c] = class_counts.get(c, 0) + 1

    wall = time.monotonic() - t0
    report = {
        "schema": REPORT_SCHEMA,
        "runs_root": str(runs_root),
        "walk_seconds": round(wall, 1),
        "totals": {k: scan[k] for k in
                   ("top_entries", "dirs_total", "files_total",
                    "bytes_total")},
        "gb_total": round(scan["bytes_total"] / 1e9, 1),
        "class_counts": class_counts,
        "top_by_bytes": top_by_bytes,
        "archive_candidates": archive,
        "archive_thresholds": {
            "min_age_days": args.archive_min_age_days,
            "min_size_mb": args.archive_min_size_mb,
        },
        "registry_coverage": coverage,
        "run_point_skipped_meta": run_point_info["skipped_meta"],
        "note": "只读盘点零删除；归档候选仅供用户决策（AGENTS 硬规则 3："
                "runs/ 永不在清理范围）；回填缺口处置=scripts/registry_"
                "backfill.py 幂等回填（本脚本不代跑）",
    }
    print(f"runs/ 盘点：顶层 {scan['top_entries']} 条目 / 目录 "
          f"{scan['dirs_total']} / 文件 {scan['files_total']} / "
          f"{report['gb_total']}GB（walk {wall:.0f}s）")
    print(f"顶层目录分类：{class_counts}")
    if coverage.get("available"):
        print(f"registry 覆盖：判真 run 点 {coverage['judged_run_points']}"
              f" vs 表行 {coverage['registry_rows']} → 回填候选 "
              f"{len(coverage['backfill_candidates'])}（处置="
              "registry_backfill.py 幂等回填，本脚本不代跑）；无 meta 对应"
              f"行 {coverage['stale_rows_total']}")
    print(f"归档候选（≥{args.archive_min_age_days}d 且 "
          f"≥{args.archive_min_size_mb:g}MB）：{len(archive)} 个目录"
          "（只列不动作，处置权在用户）")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"报告 JSON → {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
