"""E3 代理 Playground service（WP0.4）：滑条参数 → 代理实时预测。

诚实呈现纪律（方案 WP0.4）：预测值一律标注"代理非真值"；质量
（LOOCV ρ/判定/样本量）随结果返回；同时返回参数空间内最近样本的
真值供对照。

实现口径：每次请求用该 run 的校准产物（calibration/samples.json）
现场重拟合（25 点毫秒级）——与校准服务走同一 fit 路径，天然一致，
无需序列化拟合状态。predict 数值全部出自确定性代理内核（铁律 7）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

RUNS_DIR = Path("runs")


def _load_artifacts(run_id: str) -> dict[str, Any]:
    base = RUNS_DIR / run_id / "calibration"
    out: dict[str, Any] = {}
    for name in ("samples.json", "surrogate.json", "campaign.json"):
        p = base / name
        out[name] = (
            json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None)
    return out


def playground_runs() -> dict[str, Any]:
    """有校准产物的 run 清单（供 Playground 下拉选择）。"""
    runs: list[dict[str, Any]] = []
    if RUNS_DIR.is_dir():
        for d in sorted(RUNS_DIR.iterdir()):
            if not (d / "calibration" / "samples.json").is_file():
                continue
            info: dict[str, Any] = {"run_id": d.name}
            camp = d / "calibration" / "campaign.json"
            if camp.is_file():
                try:
                    c = json.loads(camp.read_text(encoding="utf-8"))
                    info["best_surrogate"] = c.get("best_surrogate")
                    info["rho"] = c.get("augment_rho")
                    info["verdict"] = c.get("augment_verdict")
                    info["n_samples"] = c.get("n_samples")
                    info["recipe"] = c.get("recipe")
                except (OSError, ValueError):
                    pass
            runs.append(info)
    return {"ok": True, "runs": runs}


def playground_predict(
    run_id: str, params: dict[str, float] | None = None,
) -> dict[str, Any]:
    """给定参数 → 代理预测指标 + 质量 + 最近样本真值对照。

    缺参取界中点；越界参数裁剪并在 clamped 里如实列出。
    """
    data = _load_artifacts(run_id)
    samples_doc = data["samples.json"]
    if not samples_doc:
        return {"ok": False, "error": f"该 run 无校准产物: {run_id}"}
    samples = samples_doc.get("samples") or []
    bounds = samples_doc.get("bounds") or {}
    if not samples or not bounds:
        return {"ok": False, "error": "校准产物缺 samples/bounds"}

    clean: dict[str, float] = {}
    clamped: list[str] = []
    for name, spec in bounds.items():
        lo, hi = float(spec[0]), float(spec[1])
        v = float((params or {}).get(name, (lo + hi) / 2.0))
        if v < lo:
            clamped.append(name)
            v = lo
        elif v > hi:
            clamped.append(name)
            v = hi
        clean[name] = v

    campaign = data["campaign.json"] or {}
    surrogate_doc = data["surrogate.json"] or {}
    kind = (campaign.get("best_surrogate")
            or surrogate_doc.get("kind") or "poly_ridge")

    from rfauto.optimization.surrogate import surrogate_registry

    try:
        # 与校准时刻同参：优先用校准产物里存的拟合 config（order/metrics），
        # 缺失时按 bounds 现场推导（与 calibration_service._make_model 同口径）
        config = dict(surrogate_doc.get("config") or {})
        config.setdefault("bounds", {k: (float(v[0]), float(v[1]))
                                     for k, v in bounds.items()})
        model = surrogate_registry.create(kind, config=config)
        fit_info = model.fit(samples)
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    if not model.fitted:
        return {"ok": False, "error": f"代理拟合失败（kind={kind}）"}
    predicted = model.predict(clean)

    def _norm(p: dict[str, float]) -> list[float]:
        out = []
        for name, spec in bounds.items():
            lo, hi = float(spec[0]), float(spec[1])
            base_v = float(p.get(name, (lo + hi) / 2.0))
            out.append((base_v - lo) / ((hi - lo) or 1.0))
        return out

    target = _norm(clean)
    nearest = min(
        samples,
        key=lambda s: sum((a - b) ** 2 for a, b in zip(
            target, _norm(s.get("params") or {}), strict=False)))
    dist = math.sqrt(sum(
        (a - b) ** 2 for a, b in zip(
            target, _norm(nearest.get("params") or {}), strict=False)))

    return {
        "ok": True,
        "run_id": run_id,
        "kind": kind,
        "bounds": {k: [float(v[0]), float(v[1])] for k, v in bounds.items()},
        "params": {k: round(v, 6) for k, v in clean.items()},
        "clamped": clamped,
        "predicted": {k: round(float(v), 4) for k, v in predicted.items()},
        "quality": {
            "rho": campaign.get("augment_rho"),
            "verdict": campaign.get("augment_verdict"),
            "n_samples": campaign.get("n_samples") or len(samples),
            "fit_info": fit_info if isinstance(fit_info, dict) else None,
        },
        "nearest_sample": {
            "params": nearest.get("params"),
            "metrics": nearest.get("metrics"),
            "normalized_distance": round(dist, 4),
        },
        "honest_note": "代理预测非真值：数值由校准样本拟合的代理模型给出，"
                       "仅供趋势/排序参考；精算以 openEMS/HFSS 求解为准。",
    }
