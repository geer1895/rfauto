"""QM-8 锚漂移 SPC 时序支撑性如实评估（ge8b 席B8）。

对 knowledge/anchors.yaml 全锚盘点可用的残差时序长度（快照库 + 注册表
last_verified），逐锚跑 core/anchor_drift_spc 三证据报告（广义 ESD + EWMA
+ CUSUM），落档 runs/qm8_anchor_spc/assessment.json。

判读纪律（#122 如实，任务书预判口径）：锚注册表当前每锚只落**单点**
``last_verified.residual``（部分锚连该点也没有），漂移快照库
（runs/anchor_drift/snapshots.json，QW-16 机制）尚未积累——预期全锚
n<8 → verdict=insufficient（三线不硬算）。本评估的价值=把"哪条证据线
还差什么数据"逐锚量化落档，作为 revalidate 数据积累的启用条件清单，
**不虚构序列、不从单点内估 σ 凑判**（#118 家族）。

用法::

    .venv/Scripts/python.exe scripts/qm8_anchor_spc_assessment.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.core.anchor_drift_spc import (  # noqa: E402
    ESD_MIN_N,
    EWMA_MIN_N,
    SERIES_MIN_N,
    anchor_drift_spc_report,
)

ANCHORS_YAML = REPO / "knowledge" / "anchors.yaml"
#: 漂移指纹快照库（QW-16：service/anchors_service.record_anchor_drift_snapshot
#: 的缺省落点；缺失/损坏如实按空表——#105 best-effort）
SNAPSHOT_STORE = REPO / "runs" / "anchor_drift" / "snapshots.json"
OUT_PATH = REPO / "runs" / "qm8_anchor_spc" / "assessment.json"


def load_snapshot_series(path: Path) -> dict[str, list[float]]:
    """快照库 → {anchor_id: 时序}（各快照 values 批按落库序拼接；缺失/
    损坏如实空表，#105 best-effort）。"""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # 快照库损坏 best-effort 空表（#105）
    snaps = (data or {}).get("snapshots")
    if not isinstance(snaps, list):
        return {}
    out: dict[str, list[float]] = {}
    for s in snaps:
        if not isinstance(s, dict):
            continue
        vals = s.get("values")
        if isinstance(vals, list):
            out.setdefault(str(s.get("anchor_id")), []).extend(
                float(v) for v in vals)
    return out


def candidate_series(rec: dict[str, Any],
                     snap_series: list[float]) -> dict[str, Any]:
    """单锚可用时序盘点与组装（三来源逐一如实登记；数值=真实残差点）。"""
    lv = rec.get("last_verified")
    residual = lv.get("residual") if isinstance(lv, dict) else None
    series = [*snap_series]
    n_residual = 0
    if isinstance(residual, (int, float)) and not isinstance(residual, bool):
        series.append(float(residual))
        n_residual = 1
    return {
        "n_registry_last_verified": n_residual,
        "n_snapshot_points": len(snap_series),
        "n_total": len(series),
        "series": series,  # 仅供 n≥8 时 SPC 直读；n<8 报告不产生数值判定
        "has_declared_uncertainty": isinstance(rec.get("uncertainty"), dict),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="QM-8 锚时序 SPC 支撑性评估")
    ap.add_argument("--anchors", default=str(ANCHORS_YAML))
    ap.add_argument("--snapshots", default=str(SNAPSHOT_STORE))
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = yaml.safe_load(Path(args.anchors).read_text(encoding="utf-8"))
    anchors = raw.get("anchors") or []
    snap_series_by_id = load_snapshot_series(Path(args.snapshots))

    per_anchor: list[dict[str, Any]] = []
    n_insufficient = 0
    n_any_computed = 0
    for rec in anchors:
        aid = str(rec.get("anchor_id"))
        cand = candidate_series(rec, snap_series_by_id.get(aid, []))
        series = cand.pop("series")
        rep = anchor_drift_spc_report(series, sigma=None, target=None)
        verdict = rep["verdict"]
        if verdict == "insufficient":
            n_insufficient += 1
        else:
            n_any_computed += 1
        per_anchor.append({
            "anchor_id": aid,
            "kind": rec.get("kind"),
            "status": rec.get("status"),
            "available_series": cand,
            "spc_verdict": verdict,
            "fired_lines": rep.get("fired_lines") or [],
            "enables_when": {
                "esd": f"n≥{ESD_MIN_N}",
                "ewma_cusum": f"n≥{EWMA_MIN_N} 且显式声明 σ"
                              "（锚 uncertainty 为确定性外部源）",
                "overall": f"n≥{SERIES_MIN_N}",
            },
        })

    summary = {
        "schema": "rfauto-qm8-anchor-spc-assessment-v1",
        "n_anchors": len(anchors),
        "n_snapshot_anchors": len(snap_series_by_id),
        "snapshot_store_present": Path(args.snapshots).is_file(),
        "n_insufficient": n_insufficient,
        "n_with_spc_verdict": n_any_computed,
        "conclusion": (
            "全锚时序支撑性不足（n<8）：广义 ESD/EWMA/CUSUM 三证据线一律"
            "未启用（不硬算不凑数，#122）。漂移判读仍由 QW-16 既有面"
            "（core/anchor_drift 两线：Mann-Kendall+指纹差分）的 "
            "insufficient/单点语义承担；SPC 三线启用条件=快照库/复验残差"
            "积累至 n≥8（ESD 需 n≥10）且锚 uncertainty 显式声明为 σ 源。"),
        "per_anchor": per_anchor,
    }
    print(json.dumps({k: v for k, v in summary.items()
                      if k != "per_anchor"}, ensure_ascii=False, indent=1))
    if args.dry_run:
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"[qm8] 落档 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
