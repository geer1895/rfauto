"""meta_metrics：仓库指标时间序列采集与漂移周报（MT2-1，round19 P2 前半）。

**接口原型级**（ge8c 席C5 口径）：①门级指标快照采集器（测试数/通过率/
时长逐门快照）+②漂移周报（复用 anchor_drift 内核）+③测试选择实验的
确定性 sampler 接口。零真机、零 LLM 通道（#139）、纯确定性。

存储形态（runs 湖同构：JSONL 追加索引 + 逐记录自包含，lake_service
JSONL/manifest 惯例的轻量同型）：

- ``<out_dir>/index.jsonl``：全门追加索引（一行一快照，自包含字段）；
- ``<out_dir>/gates/<gate>.jsonl``：逐门序列（周报直读面）。

③判据客观规避自我指涉（round19 原文）：sampler 只做确定性选择
（sha256(seed:id) 稳定序），**全量门金标对照不在本面**（需真实全量门
运行，ge8c 席C5 三禁不跑全量）——gold 字段如实 None+UNVERIFIED 登记，
见 :func:`select_smoke_subset` docstring。

漂移检测消费 ``core.anchor_drift.anchor_drift_report``（QW-16，MK 趋势
+ 分布指纹双线）——不复写内核（#222 接地：复用 anchor_drift）。
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.core.anchor_drift import anchor_drift_report
from rfauto.service.envelope import ok_envelope

_SOURCE = "rfauto.service.meta_metrics_service"
_SCHEMA = "meta_metrics_snapshot/v1"

#: 可派生指标键 → 计算式（test_count = passed+failed+skipped；
#: pass_rate = passed/(passed+failed)，分母 0 如实缺测）
_DERIVED_KEYS = ("passed", "failed", "skipped", "duration_s", "test_count",
                 "pass_rate")


def _num(value: Any, name: str, *, nonneg: bool = False) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为数值，得到 {value!r}") from exc
    if not math.isfinite(v):
        raise ValueError(f"{name} 必须有限，得到 {v!r}")
    if nonneg and v < 0:
        raise ValueError(f"{name} 必须 ≥0，得到 {v!r}")
    return v


def _record(payload: dict[str, Any]) -> dict[str, Any]:
    gate = str(payload.get("gate") or "").strip()
    if not gate:
        raise ValueError("gate 必填（非空字符串）")
    passed = int(_num(payload.get("passed"), "passed", nonneg=True))
    failed = int(_num(payload.get("failed", 0), "failed", nonneg=True))
    skipped = int(_num(payload.get("skipped", 0), "skipped", nonneg=True))
    duration_s = _num(payload.get("duration_s", 0.0), "duration_s",
                      nonneg=True)
    at = str(payload.get("at") or
             datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return {
        "schema": _SCHEMA,
        "at": at,
        "gate": gate,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "test_count": passed + failed + skipped,
        "pass_rate": (passed / (passed + failed)
                      if (passed + failed) > 0 else None),
        "duration_s": duration_s,
        "source": str(payload.get("source") or "unspecified"),
    }


def snapshot_gate_metrics(payload: dict[str, Any],
                          out_dir: str | Path) -> dict[str, Any]:
    """门级指标快照（JSONL 追加：index.jsonl + gates/<gate>.jsonl）。

    out_dir 必填（原型显式口径；单测用 tmp_path 隔离防污染真实 runs/，
    #144 同源纪律）。追加语义：已有文件尾部续写，不重写历史（证据面
    零改写，#325/#326 同源）。
    """
    p = payload if isinstance(payload, dict) else {}
    if out_dir is None or str(out_dir).strip() == "":
        return {"ok": False, "source": _SOURCE,
                "reason": "out_dir 必填（快照存储根；tmp_path 隔离纪律）"}
    try:
        rec = _record(p)
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "source": _SOURCE, "reason": f"入参非法: {exc}"}
    root = Path(out_dir)
    gate_dir = root / "gates"
    try:
        gate_dir.mkdir(parents=True, exist_ok=True)
        idx_path = root / "index.jsonl"
        gate_path = gate_dir / f"{rec['gate']}.jsonl"
        line = json.dumps(rec, ensure_ascii=False)
        for path in (idx_path, gate_path):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError as exc:
        return {"ok": False, "source": _SOURCE,
                "reason": f"快照写入失败: {exc}"}
    return ok_envelope(source=_SOURCE, snapshot=rec, index_path=str(root / "index.jsonl"), gate_series_path=str(gate_path))


def _read_index(out_dir: str | Path) -> dict[str, Any]:
    path = Path(out_dir) / "index.jsonl"
    if not path.is_file():
        return {"ok": False, "reason": f"索引不存在: {path}"}
    rows: list[dict[str, Any]] = []
    bad = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    bad += 1
    except OSError as exc:
        return {"ok": False, "reason": f"索引读取失败: {exc}"}
    return ok_envelope(rows=rows, bad_lines=bad, path=str(path))


def _value_of(rec: dict[str, Any], key: str) -> float | None:
    if key in rec:
        v = rec[key]
        return None if v is None else float(v)
    return None


def metrics_series(out_dir: str | Path, key: str,
                   gate: str | None = None) -> dict[str, Any]:
    """指标序列读取（key ∈ {passed, failed, skipped, duration_s,
    test_count, pass_rate}；pass_rate 缺测点如实跳过并计数）。"""
    if key not in _DERIVED_KEYS:
        return {"ok": False, "source": _SOURCE,
                "reason": f"未知指标键 {key!r}（合法: {list(_DERIVED_KEYS)}）"}
    idx = _read_index(out_dir)
    if not idx["ok"]:
        return {"ok": False, "source": _SOURCE, "reason": idx["reason"]}
    points: list[tuple[str, float]] = []
    missing = 0
    for rec in idx["rows"]:
        if gate is not None and rec.get("gate") != gate:
            continue
        v = _value_of(rec, key)
        if v is None:
            missing += 1
        else:
            points.append((str(rec.get("at")), v))
    return ok_envelope(
        source=_SOURCE,
        key=key,
        gate=gate,
        ats=[a for a, _ in points],
        values=[v for _, v in points],
        missing_points=missing,
        bad_lines=idx.get("bad_lines", 0),
    )


def metrics_drift_report(out_dir: str | Path, key: str,
                         gate: str | None = None, **drift_kwargs) -> dict[str, Any]:
    """指标漂移报告（anchor_drift 内核复用，阈值 kwarg 透传）。"""
    ser = metrics_series(out_dir, key, gate)
    if not ser["ok"]:
        return ser
    rep = anchor_drift_report(ser["values"], **drift_kwargs)
    return ok_envelope(
        source=_SOURCE,
        key=key,
        gate=gate,
        n_points=len(ser["values"]),
        missing_points=ser["missing_points"],
        drift=rep,
    )


def metrics_weekly_report(out_dir: str | Path, *,
                          window: int = 7) -> dict[str, Any]:
    """周报：逐门取最近 window 个快照 → 通过率/时长双指标漂移 verdict。"""
    idx = _read_index(out_dir)
    if not idx["ok"]:
        return {"ok": False, "source": _SOURCE, "reason": idx["reason"]}
    gates: dict[str, list[dict[str, Any]]] = {}
    for rec in idx["rows"]:
        gates.setdefault(str(rec.get("gate")), []).append(rec)
    per_gate: list[dict[str, Any]] = []
    lines: list[str] = [f"# meta metrics 周报（近 {int(window)} 快照/门）"]
    for gate_name in sorted(gates):
        rows = gates[gate_name][-int(window):]
        row: dict[str, Any] = {"gate": gate_name, "n_snapshots": len(rows),
                               "latest_at": rows[-1].get("at"),
                               "latest": {k: rows[-1].get(k) for k in
                                          ("passed", "failed", "skipped",
                                           "duration_s", "pass_rate")}}
        for key in ("pass_rate", "duration_s"):
            vals = [v for v in (_value_of(r, key) for r in rows)
                    if v is not None]
            row[f"drift_{key}"] = (anchor_drift_report(vals)
                                   if vals else {"verdict": "no_data"})
        per_gate.append(row)
        pr = row["drift_pass_rate"].get("verdict")
        du = row["drift_duration_s"].get("verdict")
        lines.append(f"- {gate_name}: n={len(rows)} 最新通过率="
                     f"{row['latest'].get('pass_rate')} "
                     f"(drift={pr}, duration drift={du})")
    return ok_envelope(source=_SOURCE, window=int(window), per_gate=per_gate, lines=lines)


def select_smoke_subset(test_ids: list[str], k: int, seed: int = 0
                        ) -> dict[str, Any]:
    """确定性冒烟子集选择（sha256(seed:id) 稳定序前 k）。

    **UNVERIFIED 登记（round19 条件件③）**：全量门金标对照（sampler 子集
    vs 全量门失败捕获率）需真实全量门运行，本席三禁不跑全量——``gold``
    字段恒 None，选择器覆盖率/失败捕获率不预支、不自我指涉。
    """
    if k < 0:
        return {"ok": False, "source": _SOURCE, "reason": "k 必须 ≥0"}
    uniq = list(dict.fromkeys(str(t) for t in test_ids))
    if len(uniq) != len(test_ids):
        return {"ok": False, "source": _SOURCE,
                "reason": "test_ids 含重复项（确定性选择要求唯一）"}
    ranked = sorted(uniq, key=lambda t: hashlib.sha256(
        f"{int(seed)}:{t}".encode()).hexdigest())
    k_eff = min(int(k), len(ranked))
    return ok_envelope(
        source=_SOURCE,
        subset=ranked[:k_eff],
        excluded=ranked[k_eff:],
        meta={"selector": "sha256_stable_order", "seed": int(seed),
                     "k": k_eff, "n_total": len(ranked)},
        gold=None,
        gold_note="UNVERIFIED：全量门金标对照未跑（需真实全量门，"
                         "本席不跑全量）——此字段由调用方在全量门后回填",
    )
