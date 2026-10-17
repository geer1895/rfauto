"""runs 湖 registry 回填（ge8b 首建 1→1779；R8 #7 扩展三层口径+落后度检查）。

扫描 runs/ 树，判真 run 点幂等回填 runs 表（INSERT OR IGNORE——已存在
run_id 零改写）。三层口径（R8-ENG1 2026-10-13 扩展，前两层=ge8b 原口径）：

- A meta run 点：runs/*/meta.json 与 runs/*/*/meta.json（两层，一层优先），
  #144 判真=adapter/study 任一键在。status：meta.done 或 meta.status 直读，
  缺省 "unknown"（不猜）；timestamp：meta.time > meta.timestamp > 目录
  mtime（ISO 化，来源注记）；metrics/meta 列存 JSON 摘要（2000 字符截断）。
- B 无 meta 真跑目录：顶层目录名合 run 点命名（YYYYMMDD_HHMMSS_hex8）
  且无 meta.json（死亡/中断 run——meta 落盘前即终止），但有真跑证据
  （引擎子目录 ads/hfss/openems/comsol/elmer 任一，或 recipe.snapshot.yaml，
  或 results/checkpoints/trials 非空）。status 恒 "unknown"、adapter 恒空
  （不猜）；model 仅从 recipe.snapshot.yaml 顶层 model: 行直读（读不到
  恒空）；timestamp=目录 mtime（来源注记 dir_mtime_no_meta）；meta 列注
  no_meta_run + 证据清单。dry-run/合成件/helper 命名目录不匹配此口径，
  如实计入豁免不猜入。
- 豁免（不入库，如实计数）：meta 在但 #144 判伪/读损坏、无 meta 且非
  run 点命名（helper/scratch）、run 点命名但零真跑证据（创建即弃）、
  点/下划线开头条目、顶层散文件。

--check 落后度模式（只读）：registry 行数 vs 盘面 run 点数差报告，
would_insert=0 才 rc0（落后 rc1）；runs/ 树不可读 rc2（SKIP 诚实降级，
merge_preflight 挂面口径）。--dry-run 只统计不写库；真跑幂等可重复。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.infra.db import RegistryDB, default_registry_db_path  # noqa: E402

#: 回填批次注记（写进 meta 列 backfill_batch；改批次时只动这里）
_BACKFILL_BATCH = "r8_registry_backfill"

#: run 点目录命名（api/pipeline 发射惯例：时间戳_hex8）
RUN_DIR_NAME_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}$")

#: B 类真跑证据：引擎子目录 / 发射快照 / 有内容的产物目录
_RUN_EVIDENCE_ENGINE_DIRS = ("ads", "hfss", "openems", "comsol", "elmer")
_RUN_EVIDENCE_FILES = ("recipe.snapshot.yaml",)
_RUN_EVIDENCE_CONTENT_DIRS = ("results", "checkpoints", "trials")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _run_points(runs_root: Path) -> list[Path]:
    """run 点候选：runs/*/meta.json 与 runs/*/*/meta.json（两层）。

    兼容符号：scripts/runs_inventory.py 卫生盘点消费（bfbd04eb 重写时曾
    误删致消费方收集即炸，2026-10-15 恢复）。本主脚本改用 _scan_lake
    三层口径后不再调用它——两侧枚举语义差异见 _scan_lake docstring。
    """
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
             "backfill_batch": _BACKFILL_BATCH},
            ensure_ascii=False)[:2000],
    }


def _no_meta_evidence(d: Path) -> list[str]:
    """无 meta 目录的真跑证据清单（空=非 run 点）。"""
    try:
        list(d.iterdir())  # 可读性探针（不可读目录如实按无证据处理）
    except OSError:
        return []
    ev: list[str] = []
    for name in _RUN_EVIDENCE_ENGINE_DIRS:
        if (d / name).is_dir():
            ev.append(f"dir:{name}")
    for name in _RUN_EVIDENCE_FILES:
        if (d / name).is_file():
            ev.append(f"file:{name}")
    for name in _RUN_EVIDENCE_CONTENT_DIRS:
        p = d / name
        if p.is_dir():
            try:
                if any(p.iterdir()):
                    ev.append(f"content:{name}")
            except OSError:
                pass
    return ev


def _model_from_recipe_snapshot(d: Path) -> str:
    """recipe.snapshot.yaml 顶层 model: 行直读（无 yaml 依赖；读不到恒空）。"""
    try:
        for line in (d / "recipe.snapshot.yaml").read_text(encoding="utf-8").splitlines():
            m = re.match(r"^model:\s*(.+?)\s*$", line)
            if m:
                return m.group(1).split(" #", 1)[0].strip().strip("'\"")
    except OSError:
        pass
    return ""


def _no_meta_run_row(d: Path, evidence: list[str]) -> dict:
    """B 类行：无 meta 真跑目录 → status/adapter 不猜，证据与来源全注记。"""
    return {
        "run_id": d.name,
        "model": _model_from_recipe_snapshot(d),
        "adapter": "",  # 无 meta 不猜
        "status": "unknown",  # 死亡/中断形态不猜（失败目录如实计数）
        "git_sha": "",
        "timestamp": _iso(d.stat().st_mtime),
        "metrics": "{}",
        "meta": json.dumps(
            {"no_meta_run": True, "backfill_evidence": evidence,
             "backfill_ts_source": "dir_mtime_no_meta",
             "backfill_batch": _BACKFILL_BATCH},
            ensure_ascii=False)[:2000],
    }


def _scan_lake(runs_root: Path) -> tuple[dict[str, dict], dict[str, int], int]:
    """runs/ 树 → (run 点行 by run_id, 豁免分类计数, meta 候选数)。

    一层 meta 优先（setdefault 首见即胜），二层 meta 仍入 A 类候选
    （ge8b 两层口径不变）；B 类只看顶层（二层无 meta 子目录非发射形态）。
    """
    rows: dict[str, dict] = {}
    exempt = {
        "meta_non_run": 0,        # meta 在但 #144 判伪/读损坏
        "no_meta_helper": 0,      # 无 meta 且非 run 点命名（helper/scratch）
        "no_meta_unbacked": 0,    # run 点命名但零真跑证据（创建即弃）
        "dot_or_underscore": 0,   # 点/下划线开头条目（.optuna 等）
        "top_level_files": 0,     # 顶层散文件（门日志等）
    }
    scanned_meta = 0
    if not runs_root.exists():
        return rows, exempt, scanned_meta
    for p in sorted(runs_root.iterdir()):
        if not p.is_dir():
            exempt["top_level_files"] += 1
            continue
        if p.name.startswith((".", "_")):
            exempt["dot_or_underscore"] += 1
            continue
        if (p / "meta.json").exists():
            scanned_meta += 1
            got = _row_for(p / "meta.json")
            if got is not None:
                rows.setdefault(got[0], got[1])
            else:
                exempt["meta_non_run"] += 1
        elif RUN_DIR_NAME_RE.match(p.name):
            ev = _no_meta_evidence(p)
            if ev:
                row = _no_meta_run_row(p, ev)
                rows.setdefault(row["run_id"], row)
            else:
                exempt["no_meta_unbacked"] += 1
        else:
            exempt["no_meta_helper"] += 1
        # 二层 meta 候选（ge8b 口径保留；当前湖面实测 0 个，防空战役目录漂移）
        for q in sorted(p.iterdir()):
            if q.is_dir() and (q / "meta.json").exists():
                scanned_meta += 1
                got = _row_for(q / "meta.json")
                if got is not None:
                    rows.setdefault(got[0], got[1])
                else:
                    exempt["meta_non_run"] += 1
    return rows, exempt, scanned_meta


def _db_existing_ids(con) -> set[str]:
    # 空库/未迁移容错：connect 对不存在文件自动建空库（无 schema），直接
    # SELECT 会 OperationalError 崩成 rc1 而非 rc2 诚实 SKIP（公开仓 fresh
    # checkout + runs/ 仅门日志时实测）——查 sqlite_master 无 runs 表=空集。
    has = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
    ).fetchall()
    if not has:
        return set()
    return {r[0] for r in con.execute("SELECT run_id FROM runs").fetchall()}


def main() -> int:
    ap = argparse.ArgumentParser(description="runs 湖 → registry 幂等回填")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    ap.add_argument("--check", action="store_true",
                    help="落后度检查（只读）：would_insert=0 才 rc0，落后 rc1，"
                         "runs/ 不可读 rc2（SKIP）")
    ap.add_argument("--db", default="", help="覆盖 registry 路径（缺省三层口径）")
    args = ap.parse_args()

    runs_root = REPO / "runs"
    rows, exempt, scanned_meta = _scan_lake(runs_root)
    db_path = Path(args.db) if args.db else default_registry_db_path()

    if not runs_root.exists():
        # runs/ 树不可读/缺失：回填无事可做；--check 按 SKIP 口径 rc2
        stats = {"mode": "check" if args.check else "dry-run",
                 "runs_root": str(runs_root), "exists": False,
                 "scanned_meta": 0, "run_points": 0}
        print(json.dumps(stats, ensure_ascii=False, indent=1))
        return 2 if args.check else 0

    stats: dict = {"scanned_meta": scanned_meta, "run_points": len(rows),
                   "exempt": exempt}

    if args.dry_run and not args.check:
        stats.update({"mode": "dry-run", "would_insert": len(rows),
                      "db_path": str(db_path)})
        print(json.dumps(stats, ensure_ascii=False, indent=1))
        return 0

    db = RegistryDB(path=str(db_path))
    con = db.connect()
    try:
        existing = _db_existing_ids(con)
        fresh = [r for rid, r in sorted(rows.items()) if rid not in existing]
        if not args.check:
            con.executemany(
                "INSERT OR IGNORE INTO runs (run_id, model, adapter, status,"
                " git_sha, timestamp, metrics, meta) VALUES (:run_id,:model,"
                ":adapter,:status,:git_sha,:timestamp,:metrics,:meta)",
                fresh)
            con.commit()
        stats.update({
            "mode": "check" if args.check else "backfill",
            "db_path": str(db_path),
            "registry_rows": len(existing),
            "already_present": len(rows) - len(fresh),
            "db_rows_not_on_disk": len(existing - set(rows)),
            "inserted": 0 if args.check else len(fresh),
            "would_insert": len(fresh),
        })
        print(json.dumps(stats, ensure_ascii=False, indent=1))
    finally:
        con.close()
        db.close()
    if args.check:
        return 0 if not stats["would_insert"] else 1
    return 0


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    print(f"elapsed {time.time() - t0:.1f}s")
    sys.exit(rc)
