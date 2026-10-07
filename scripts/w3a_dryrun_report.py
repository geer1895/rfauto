"""W3-A 真湖 dry-run 只读报告驱动（RB-WN-1，sa_specs2 §五；W3-A criteria 预声明）。

**纯读承诺**：对 runs/ 全程零写零删零链接（真实压缩/删除/迁移等破坏性动作
绝不自动执行——生产数据，放量等用户窗与 XD-5 pin 互锁）；唯一写面=本席
报告目录 runs/w3_phase3/w3a/ 下的 dryrun.json。

产出（判据 6 dry-run 输出账）：h5 画像与三档保留/删除清单、et/ht 去重
统计、sparams 摘要资格面、golden 零改写断言、破坏性放量面清单+预估收益。

用法（自仓根）::

    .venv/Scripts/python.exe scripts/w3a_dryrun_report.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.service.lake_compact_service import (  # noqa: E402
    plan_et_ht_dedup,
    plan_h5_retention,
    plan_sparams_summaries,
)
from rfauto.service.sim_ci_service import (  # noqa: E402
    default_baseline_path,
    load_baseline,
)

OUT_DIR = REPO / "runs" / "w3_phase3" / "w3a"

GIB = 1024 ** 3


def _gib(n: int | float) -> float:
    return round(n / GIB, 2)


def main() -> int:
    t0 = time.perf_counter()
    runs = REPO / "runs"
    if not runs.is_dir():
        print(f"runs 不存在: {runs}")
        return 2

    # ── 画像速览（一遍 walk：h5/et/ht/csv 计数与体积；meta status 分布）──
    n_h5 = 0
    h5_bytes = 0
    n_et = n_ht = 0
    et_bytes = ht_bytes = 0
    n_csv = 0
    status_counter: Counter[str] = Counter()
    n_meta = 0
    for dirpath, _dirnames, filenames in os.walk(runs):
        here = Path(dirpath)
        for name in filenames:
            suffix = os.path.splitext(name)[1].lower()
            try:
                size = (here / name).stat().st_size
            except OSError:
                continue
            if suffix == ".h5":
                n_h5 += 1
                h5_bytes += size
            elif suffix == ".et":
                n_et += 1
                et_bytes += size
            elif suffix == ".ht":
                n_ht += 1
                ht_bytes += size
            elif name == "sparams.csv":
                n_csv += 1
        if name_meta := next((f for f in filenames
                              if f in ("meta.json", "run_meta.json")), None):
            n_meta += 1
            try:
                meta = json.loads((here / name_meta).read_text(
                    encoding="utf-8"))
                status_counter[str(meta.get("status"))] += 1
            except (OSError, ValueError):
                status_counter["<unreadable>"] += 1
    profile = {
        "n_h5": n_h5, "h5_gib": _gib(h5_bytes),
        "n_et": n_et, "et_gib": _gib(et_bytes),
        "n_ht": n_ht, "ht_gib": _gib(ht_bytes),
        "n_sparams_csv": n_csv, "n_meta": n_meta,
        "meta_status_counter": dict(status_counter.most_common(12)),
    }
    print("[1/4] 画像:", json.dumps(profile, ensure_ascii=False))

    # ── ① h5 白名单保留三档规划（纯读）──
    plan = plan_h5_retention(runs, tier="medium", keep_recent_n=0,
                             min_age_h=24.0)
    print("[2/4] h5 规划:", json.dumps(
        {k: plan.get(k) for k in ("ok", "n_h5", "total_bytes", "n_delete",
                                  "bytes_delete", "keep_reasons", "tiers",
                                  "n_protected_dirs")},
        ensure_ascii=False, default=str))
    by_campaign: Counter[str] = Counter()
    bytes_by_campaign: Counter[str] = Counter()
    for row in plan.get("delete") or []:
        camp = str(row["run_dir"]).split("/", 1)[0]
        by_campaign[camp] += 1
        bytes_by_campaign[camp] += int(row["size"])
    delete_top = [
        {"campaign": c, "n_h5": by_campaign[c],
         "gib": _gib(bytes_by_campaign[c])}
        for c, _ in by_campaign.most_common(20)]

    # ── ② et/ht 去重规划（纯读+hash）──
    dedup = plan_et_ht_dedup(runs, min_age_h=24.0)
    print("[3/4] et/ht 去重:", json.dumps(
        {k: dedup.get(k) for k in ("ok", "n_files", "total_bytes", "n_unique",
                                   "n_dup_files", "bytes_dup_total",
                                   "n_protected", "n_inflight_dirs",
                                   "n_too_fresh")},
        ensure_ascii=False, default=str))

    # ── ③ sparams 摘要资格面（纯读）──
    summaries = plan_sparams_summaries(runs)

    # ── XD-5 互锁状态（golden pin 面）──
    baseline_file = default_baseline_path()
    golden = load_baseline(baseline_file)
    xd5 = {
        "baseline_path": str(baseline_file),
        "pinned": golden is not None,
        "pinned_run_id": str((golden or {}).get("pinned_run_id") or ""),
        "note": "golden 未 pin → rfauto lake compact --apply 被互锁拒绝"
                if golden is None else "golden 已 pin（--apply 仍需用户显式窗）",
    }

    # ── golden 零改写断言（脚本断言，判据 1）──
    audit = plan.get("golden_rewrite_audit") or {}
    zero_rewrite = {
        "n_protected_dirs": audit.get("n_protected_dirs"),
        "violations": audit.get("violations"),
        "assert_pass": audit.get("violations") == [],
    }
    protected_names = plan.get("protected_names") or []

    elapsed = round(time.perf_counter() - t0, 1)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wall_s": elapsed,
        "mode": "dry-run 纯读（零写零删零链接；唯一写面=本 JSON）",
        "profile": profile,
        "h5_plan": {
            "tier_medium_delete_n": plan.get("n_delete"),
            "tier_medium_delete_gib": _gib(int(plan.get("bytes_delete") or 0)),
            "keep_reasons": plan.get("keep_reasons"),
            "tiers": plan.get("tiers"),
            "tiers_gib": {k: _gib(int(v.get("bytes_delete") or 0))
                          for k, v in (plan.get("tiers") or {}).items()},
            "delete_by_campaign_top20": delete_top,
            "n_delete_truncated": plan.get("delete_truncated"),
        },
        "etht_dedup_plan": {k: dedup.get(k) for k in (
            "ok", "n_files", "total_bytes", "n_unique", "n_dup_files",
            "bytes_dup_total", "n_protected", "n_inflight_dirs",
            "n_too_fresh")},
        "sparams_summary_plan": {k: summaries.get(k) for k in (
            "ok", "n_sparams_csv", "n_summary_existing", "n_eligible")},
        "golden_zero_rewrite": zero_rewrite,
        "protected_dir_names_sample": protected_names[:60],
        "xd5_interlock": xd5,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "dryrun.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[4/4] 报告落盘: {out_path}  wall={elapsed}s")
    print(json.dumps({"tiers_gib": report["h5_plan"]["tiers_gib"],
                      "dup_gib": _gib(int(dedup.get("bytes_dup_total") or 0)),
                      "xd5_pinned": xd5["pinned"],
                      "zero_rewrite_pass": zero_rewrite["assert_pass"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
