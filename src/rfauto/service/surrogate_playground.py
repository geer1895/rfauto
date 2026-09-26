"""E3 代理 Playground service（WP0.4）：滑条参数 → 代理实时预测。

诚实呈现纪律（方案 WP0.4）：预测值一律标注"代理非真值"；质量
（LOOCV ρ/判定/样本量）随结果返回；同时返回参数空间内最近样本的
真值供对照。

实现口径：每次请求用该 run 的校准产物（calibration/samples.json）
现场重拟合（25 点毫秒级）——与校准服务走同一 fit 路径，天然一致，
无需序列化拟合状态。predict 数值全部出自确定性代理内核（铁律 7）。

DP-16 U3 探索器：explore(run_id, params, sweep) → 参数扫描切片后验
曲线 JSON（mean±std）。variance 只在模型有原生逐点 σ（smt 族，
predict_with_std/uncertainty）时透出，否则 std=null 如实标注——
非 smt 族不伪造 0（#122）。samples.json schema={params, metrics 标量}：
曲线是**参数扫描切片**而非频率曲线（规格书 §16.2 加粗口径）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

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


def _prepare_run_model(
    run_id: str, params: dict[str, float] | None = None,
) -> dict[str, Any]:
    """载入校准产物 + 现场重拟合（与校准服务同 fit 路径）。

    返回 {"error": str} 或含 samples/bounds/clean/clamped/kind/model 的
    准备好的上下文（playground_predict 与 explore 共用）。
    """
    data = _load_artifacts(run_id)
    samples_doc = data["samples.json"]
    if not samples_doc:
        return {"error": f"该 run 无校准产物: {run_id}"}
    samples = samples_doc.get("samples") or []
    bounds = samples_doc.get("bounds") or {}
    if not samples or not bounds:
        return {"error": "校准产物缺 samples/bounds"}

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
        return {"error": str(exc)}
    if not model.fitted:
        return {"error": f"代理拟合失败（kind={kind}）"}

    return {
        "run_id": run_id,
        "samples": samples,
        "bounds": bounds,
        "clean": clean,
        "clamped": clamped,
        "campaign": campaign,
        "kind": kind,
        "model": model,
        "fit_info": fit_info,
        "quality": {
            "rho": campaign.get("augment_rho"),
            "verdict": campaign.get("augment_verdict"),
            "n_samples": campaign.get("n_samples") or len(samples),
            "fit_info": fit_info if isinstance(fit_info, dict) else None,
        },
    }


def playground_predict(
    run_id: str, params: dict[str, float] | None = None,
) -> dict[str, Any]:
    """给定参数 → 代理预测指标 + 质量 + 最近样本真值对照。

    缺参取界中点；越界参数裁剪并在 clamped 里如实列出。
    """
    prep = _prepare_run_model(run_id, params)
    if "error" in prep:
        return {"ok": False, "error": prep["error"]}
    samples: list[dict[str, Any]] = prep["samples"]
    bounds: dict[str, Any] = prep["bounds"]
    clean: dict[str, float] = prep["clean"]
    model = prep["model"]
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
        "run_id": prep["run_id"],
        "kind": prep["kind"],
        "bounds": {k: [float(v[0]), float(v[1])] for k, v in bounds.items()},
        "params": {k: round(v, 6) for k, v in clean.items()},
        "clamped": prep["clamped"],
        "predicted": {k: round(float(v), 4) for k, v in predicted.items()},
        "quality": prep["quality"],
        "nearest_sample": {
            "params": nearest.get("params"),
            "metrics": nearest.get("metrics"),
            "normalized_distance": round(dist, 4),
        },
        "honest_note": "代理预测非真值：数值由校准样本拟合的代理模型给出，"
                       "仅供趋势/排序参考；精算以 openEMS/HFSS 求解为准。",
    }


def explore(
    run_id: str,
    params: dict[str, float] | None = None,
    sweep: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """DP-16 U3 探索器：参数扫描切片 → 后验曲线 JSON（mean±std）。

    sweep 规格：
        1D: {"axis": "a_mm", "n": 41}——该参数在 bounds 内 linspace n 点；
        2D: {"axes": ["a_mm", "b_mm"], "n": 21}——n×n 网格（v1 最多 2D）。
    其余参数固定为 params（缺省界中点、越界裁剪同 playground_predict）。

    返回 curves={metric: {mean, std|null}}；std 只在模型有原生逐点
    σ（predict_with_std，smt 族）时透出，否则 null+如实标注。数值全部
    出自确定性代理内核（铁律 7），engine 标签=kind 如实随行。
    """
    prep = _prepare_run_model(run_id, params)
    if "error" in prep:
        return {"ok": False, "error": prep["error"]}
    bounds: dict[str, Any] = prep["bounds"]
    clean: dict[str, float] = prep["clean"]
    model = prep["model"]

    sweep = dict(sweep or {})
    axes: list[str] = list(sweep.get("axes")
                           or ([sweep["axis"]] if sweep.get("axis") else []))
    if not axes:
        return {"ok": False,
                "error": "sweep 需 axis（1D）或 axes（2D，最多两轴）"}
    if len(axes) > 2:
        return {"ok": False, "error": f"v1 最多 2D 扫描，得到 {len(axes)} 轴"}
    unknown = [a for a in axes if a not in bounds]
    if unknown:
        return {"ok": False,
                "error": f"扫参轴不在 bounds 内: {unknown}（可用: {sorted(bounds)}）"}
    n = int(sweep.get("n", 41 if len(axes) == 1 else 21))
    n = max(n, 2)
    axes_values = {
        a: [float(v) for v in np.linspace(float(bounds[a][0]),
                                          float(bounds[a][1]), n)]
        for a in axes
    }

    # 参数扫描切片网格点（其余参数取 fixed 值）
    if len(axes) == 1:
        a = axes[0]
        points = [{**clean, a: v} for v in axes_values[a]]
    else:
        a1, a2 = axes
        points = [{**clean, a1: v1, a2: v2}
                  for v1 in axes_values[a1] for v2 in axes_values[a2]]

    means: dict[str, list[float]] = {}
    stds: dict[str, list[float]] = {}
    all_have_std = True
    for p in points:
        pw = model.predict_with_std(p)
        for key, (m, s) in pw.items():
            means.setdefault(key, []).append(float(m))
            stds.setdefault(key, []).append(
                None if s is None else float(s))
            if s is None:
                all_have_std = False

    def _reshape(flat: list[float]) -> list[Any]:
        return flat if len(axes) == 1 else [
            flat[i * n:(i + 1) * n] for i in range(n)]

    curves: dict[str, Any] = {}
    for key in means:
        has = all_have_std and not any(v is None for v in stds[key])
        curves[key] = {
            "mean": _reshape(means[key]),
            "std": _reshape(stds[key]) if has else None,
        }

    return {
        "ok": True,
        "run_id": prep["run_id"],
        "kind": prep["kind"],
        "engine": prep["kind"],  # engine 标签如实（确定性代理内核）
        "sweep": {
            "axes": axes,
            "n": n,
            "axes_values": axes_values,
            "fixed": {k: round(v, 6) for k, v in clean.items()
                      if k not in axes},
        },
        "curves": curves,
        "has_variance": bool(all_have_std and curves),
        "variance_note": (
            "模型原生逐点 σ 已透出（predict_with_std）" if all_have_std
            else "该代理无原生逐点不确定度（非 smt 族），std=null 如实标注"),
        "quality": prep["quality"],
        "honest_note": "代理预测非真值：数值由校准样本拟合的代理模型给出，"
                       "仅供趋势/排序参考；精算以 openEMS/HFSS 求解为准。",
    }
