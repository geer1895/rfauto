"""runs 湖 registry 回填（round16 勘误销账：runs 表 1 行 vs ~2900 目录脱节）。

扫描 runs/ 树（一层+二层），meta.json 判真 run（#144：adapter/study 字段），
runs 表幂等 upsert（已存在 run_id 跳过——既有 1 行与已回填行零改写）。
判据：
- meta.json 存在且含 adapter 或 study 任一键 → run 点；
- status：meta.done 或 meta.status 直读，缺省 "unknown"（不猜）；
- timestamp：meta.time > meta.timestamp > 目录 mtime（ISO 化，来源注记）；
- metrics/meta 列存 JSON 摘要（metrics 取 meta.metrics 键全量，meta 存
  provenance 子集——列宽可控）。
--dry-run 只统计不写库；真跑幂等可重复（INSERT OR IGNORE）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.infra.db import RegistryDB, default_registry_db_path  # noqa: E402


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _run_points(runs_root: Path) -> list[Path]:
    """run 点候选：runs/*/meta.json 与 runs/*/*/meta.json（两层）。"""
    out: list[Path] = []
    if not runs_root.exists():
        return out
    for p in sorted(runs_root.iterdir()):
        if not p.is_dir() or p.name.startswith((".", "_")):
            continue
        if (p / "meta.json").exists():
            out.append(p / "meta.json")
        for q in sorted(p.iterdir()):
            if q.is_dir() and (q / "meta.json").exists():
                out.append(q / "meta.json")
    return out


def _row_for(meta_path: Path) -> tuple[str, dict] | None:
    """meta.json → runs 表行 dict（非 run 点返回 None）。"""
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    if "adapter" not in meta and "study" not in meta:
        return None  # #144：判真=adapter/study 字段在
    run_id = meta.get("run_id") or meta_path.parent.name
    status = meta.get("status") or ("done" if meta.get("done") else "unknown")
    if isinstance(status, bool):
        status = "done" if status else "failed"
    ts_src = "dir_mtime"
    ts = meta_path.parent.stat().st_mtime
    for key in ("time", "timestamp", "started"):
        if meta.get(key):
            try:
                ts = datetime.fromisoformat(str(meta[key]).replace("Z", "+00:00")).timestamp()
                ts_src = f"meta.{key}"
                break
            except ValueError:
                continue
    metrics = meta.get("metrics") if isinstance(meta.get("metrics"), dict) else {}
    prov = {k: meta[k] for k in ("model", "adapter", "study", "seed", "recipe_version")
            if k in meta}
    return run_id, {
        "run_id": str(run_id),
        "model": str(meta.get("model") or meta.get("template") or ""),
        "adapter": str(meta.get("adapter") or ""),
        "status": str(status),
        "git_sha": str(meta.get("git_sha") or meta.get("git_sha_short") or ""),
        "timestamp": _iso(ts),
        "metrics": json.dumps(metrics, ensure_ascii=False)[:2000],
        "meta": json.dumps(
            {**prov, "backfill_ts_source": ts_src,
             "backfill_batch": "ge8b_registry_backfill"},
            ensure_ascii=False)[:2000],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="runs 湖 → registry 幂等回填")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    ap.add_argument("--db", default="", help="覆盖 registry 路径（缺省三层口径）")
    args = ap.parse_args()

    runs_root = REPO / "runs"
    candidates = _run_points(runs_root)
    rows: dict[str, dict] = {}
    skipped = 0
    for mp in candidates:
        got = _row_for(mp)
        if got is None:
            skipped += 1
            continue
        rid, row = got
        rows.setdefault(rid, row)  # 同 id 二层覆盖取首见（一层优先）

    db_path = Path(args.db) if args.db else default_registry_db_path()
    stats = {"scanned_meta": len(candidates), "run_points": len(rows),
             "skipped_non_run": skipped}
    if args.dry_run:
        stats["would_insert"] = len(rows)
        stats["db_path"] = str(db_path)
        print(json.dumps(stats, ensure_ascii=False, indent=1))
        return 0

    db = RegistryDB(path=str(db_path))
    con = db.connect()
    try:
        existing = {r[0] for r in con.execute("SELECT run_id FROM runs").fetchall()}
        fresh = [r for rid, r in sorted(rows.items()) if rid not in existing]
        con.executemany(
            "INSERT OR IGNORE INTO runs (run_id, model, adapter, status, git_sha,"
            " timestamp, metrics, meta) VALUES (:run_id,:model,:adapter,:status,"
            ":git_sha,:timestamp,:metrics,:meta)",
            fresh)
        con.commit()
        stats.update({"already_present": len(existing),
                      "inserted": len(fresh)})
        print(json.dumps(stats, ensure_ascii=False, indent=1))
    finally:
        con.close()
        db.close()
    return 0


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    print(f"elapsed {time.time() - t0:.1f}s")
    sys.exit(rc)
