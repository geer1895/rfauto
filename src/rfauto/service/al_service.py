"""al_service —— active_learning 运行时入口（aurora_n O4 接线席，2026-10-31）。

zero_wiring REGISTRY O4 欠账清偿：service/active_learning 的
propose_next_points（T-N9 宿主）此前零运行时调用方（旧面存量——仅测试与
一次性探针脚本消费）。本模块给 AL 面落持久 JSON 门（规则 4：JSON 进出，
CLI 是薄壳）：

- 样本装载三形态（互斥，恰给一）：
    * ``samples_path`` —— samples.json（bounds/samples schema，与 certify
      公差盒同款）；
    * ``dataset`` —— 物化数据集名（走 dataset_service.query_dataset 既有
      消费链读 params_json/metrics_json——#144 湖读面不新开通道；
      bounds 由观测参数范围推导并如实标注）；
    * ``run`` —— run id（runs/<id>/trials/trial_*.json 的 params/metrics，
      bounds 同上推导）。
- 提议两模式：
    * legacy（缺省，``acquisition=None``）—— 整体转发宿主
      ``propose_next_points``（σ 求和 × 距离双重准则；宿主由此获得运行时
      调用方；信封按装载形态归一 sample_source 后原样透出，宿主函数本身
      零改动）；
    * acquisition（``acquisition`` ∈ ACQUISITION_KINDS）—— LHS 候选池 →
      ``estimate_uncertainty``（T-N9 registry σ 源 + conformal_fallback
      消费点）→ ``acquisition_scores``（T-N9 采集三族统一打分面，公式
      单源不复制）→ 距离过滤 → top-k。数值全部来自确定性内核（#7）。

确定性：同 seed 同输入逐位同输出（LHS/候选打分/共形包装全链固定种子）。
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["al_propose", "load_al_samples"]

#: 数据集装载的行数上限（超出如实 truncated 标注，不静默截断——#369 总数
#: 语义单列 total_rows）。
DEFAULT_MAX_ROWS = 5000

#: run 目录 trials 子目录名（Optuna tune 通道落点）。
_TRIALS_DIRNAME = "trials"


# ─── 样本装载三形态 ──────────────────────────────────────────────────────────


def _numeric_metric_keys(samples: list[dict[str, Any]]) -> list[str]:
    """样本集中出现过的有限数值指标键（与 active_learning 同口径）。"""
    keys: set[str] = set()
    for s in samples:
        for k, v in (s.get("metrics") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) \
                    and math.isfinite(float(v)):
                keys.add(k)
    return sorted(keys)


def _bounds_from_samples(samples: list[dict[str, Any]]) -> dict[str, list[float]]:
    """观测参数范围 → bounds（逐键 min/max；非数值/缺失键不进域）。"""
    vals: dict[str, list[float]] = {}
    for s in samples:
        for k, v in (s.get("params") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) \
                    and math.isfinite(float(v)):
                vals.setdefault(k, []).append(float(v))
    return {k: [min(vs), max(vs)] for k, vs in sorted(vals.items())}


def _validate_loaded(
    samples: list[dict[str, Any]],
    bounds: dict[str, list[float]],
    source_label: str,
) -> list[str]:
    """装载后公共负例闸（显式报错不静默）：空样本/空参数域/零数值指标。"""
    errors: list[str] = []
    if not samples:
        errors.append(f"{source_label} 样本为空，无法提议")
        return errors
    if not bounds:
        errors.append(f"{source_label} 样本无可用数值参数，参数域为空")
    if not _numeric_metric_keys(samples):
        errors.append(f"{source_label} 样本无可用数值指标（metrics 缺失或"
                      "全非有限数值）——代理无法训练")
    return errors


def _samples_from_dataset(
    dataset: str,
    *,
    out_dir: str | Path | None,
    max_rows: int,
) -> tuple[list[dict[str, Any]], dict[str, list[float]], dict[str, Any]]:
    """数据集 → (samples, bounds, meta)。走 query_dataset 既有消费链。"""
    from rfauto.service.dataset_service import query_dataset

    kwargs: dict[str, Any] = {"limit": max_rows}
    if out_dir is not None:
        kwargs["out_dir"] = out_dir
    q = query_dataset(dataset, **kwargs)
    if not q.get("ok"):
        return [], {}, {"errors": list(q.get("errors") or ["数据集查询失败"])}
    meta: dict[str, Any] = {
        "dataset": dataset,
        "dataset_total_rows": q.get("total_rows"),
        "dataset_n_rows": q.get("n_rows"),
    }
    n_total = int(q.get("total_rows") or 0)
    if n_total > int(q.get("n_rows") or 0):
        meta["truncated"] = True
        meta["note_extra"] = (
            f"数据集共 {n_total} 行，本次装载前 {q.get('n_rows')} 行"
            f"（--max-rows 上调可全量）")
    samples: list[dict[str, Any]] = []
    n_bad = 0
    for row in q.get("rows") or []:
        try:
            params = json.loads(row["params_json"]) if row.get(
                "params_json") else {}
            metrics = json.loads(row["metrics_json"]) if row.get(
                "metrics_json") else {}
        except (TypeError, ValueError):
            n_bad += 1
            continue
        if not isinstance(params, dict):
            params = {}
        if not isinstance(metrics, dict):
            metrics = {}
        samples.append({"params": params, "metrics": metrics})
    if n_bad:
        meta["n_bad_json_rows"] = n_bad
    return samples, _bounds_from_samples(samples), meta


def _samples_from_run(
    run: str,
    *,
    runs_root: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, list[float]], dict[str, Any]]:
    """run id → (samples, bounds, meta)。读 runs/<id>/trials/trial_*.json。"""
    trials_dir = Path(runs_root) / run / _TRIALS_DIRNAME
    if not trials_dir.is_dir():
        return [], {}, {"errors": [
            f"run 目录不存在或缺 trials/ 子目录: {trials_dir}"
            f"（tune 通道 run 才有 trials；run_once/校准 run 请用数据集或"
            " --samples 面）"]}
    files = list(trials_dir.glob("trial_*.json"))
    if not files:
        return [], {}, {"errors": [f"trials 目录无 trial_*.json: {trials_dir}"]}
    # 按 trial 序号数值排序（字典序会把 trial_10 排到 trial_2 前——样本
    # 顺序进代理拟合面，必须与 trial 语义序一致）
    def _trial_no(p: Path) -> tuple[int, str]:
        stem = p.stem.split("_")[-1]
        try:
            return (int(stem), "")
        except ValueError:
            return (1 << 30, p.name)

    files.sort(key=_trial_no)
    samples: list[dict[str, Any]] = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        params = d.get("params")
        metrics = d.get("metrics")
        if not isinstance(params, dict) or not isinstance(metrics, dict):
            continue
        samples.append({"params": params, "metrics": metrics})
    return samples, _bounds_from_samples(samples), {"run": run}


def load_al_samples(
    samples_path: str | Path | None = None,
    dataset: str | None = None,
    run: str | None = None,
    *,
    out_dir: str | Path | None = None,
    runs_root: str | Path = "runs",
    max_rows: int = DEFAULT_MAX_ROWS,
) -> dict[str, Any]:
    """三形态样本装载（互斥恰给一）→ ok 信封（samples/bounds/meta）。

    samples_path 形态原样透传文件内容（bounds 以文件为准）；dataset/run
    形态 bounds 由观测参数范围推导（推导口径见 _bounds_from_samples）。
    负例：未给/多给来源、来源不存在、空样本/空参数域/零数值指标——全部
    ok=False 显式报错。
    """
    given = [bool(samples_path), bool(dataset), bool(run)]
    if sum(given) == 0:
        return error_envelope(
            ["样本来源必给其一：--samples / --dataset / --run"])
    if sum(given) > 1:
        return error_envelope(
            ["样本来源互斥：--samples / --dataset / --run 只能给一个"])
    if samples_path is not None:
        path = Path(samples_path)
        if not path.exists():
            return error_envelope([f"样本集不存在: {path}"])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return error_envelope([f"样本集读取失败: {exc}"])
        samples = list(data.get("samples") or [])
        bounds: dict[str, list[float]] = {}
        for k, v in (data.get("bounds") or {}).items():
            try:
                if isinstance(v, (list, tuple)) and len(v) >= 2:
                    bounds[str(k)] = [float(v[0]), float(v[1])]
            except (TypeError, ValueError):
                continue
        errors = _validate_loaded(samples, bounds, f"样本集 {path}")
        if errors:
            return error_envelope(errors)
        return ok_envelope(
            sample_source="samples", samples_path=str(path),
            samples=samples, bounds=bounds)
    if dataset is not None:
        samples, bounds, meta = _samples_from_dataset(
            dataset, out_dir=out_dir, max_rows=max_rows)
        if meta.get("errors"):
            return error_envelope(meta["errors"])
        errors = _validate_loaded(samples, bounds, f"数据集 {dataset}")
        if errors:
            return error_envelope(errors)
        return ok_envelope(sample_source="dataset", dataset=dataset,
                           samples=samples, bounds=bounds, **{
                               k: v for k, v in meta.items()
                               if k not in ("errors", "dataset")})
    samples, bounds, meta = _samples_from_run(run or "", runs_root=runs_root)
    if meta.get("errors"):
        return error_envelope(meta["errors"])
    errors = _validate_loaded(samples, bounds, f"run {run}")
    if errors:
        return error_envelope(errors)
    return ok_envelope(sample_source="run", run=run, samples=samples,
                       bounds=bounds)


# ─── 提议门（legacy 转发宿主 / acquisition 采集族） ──────────────────────────


def _propose_legacy(
    samples_path: str | Path,
    *,
    k: int,
    kind: str,
    n_candidates: int,
    min_dist: float,
    seed: int,
    conformal_fallback: bool,
) -> dict[str, Any]:
    """整体转发宿主 propose_next_points（宿主函数零改动）。"""
    from rfauto.service.active_learning import propose_next_points

    return propose_next_points(
        samples_path, k=k, kind=kind, n_candidates=n_candidates,
        min_dist=min_dist, seed=seed,
        conformal_fallback=conformal_fallback)


def _propose_acquisition(
    samples: list[dict[str, Any]],
    bounds: dict[str, list[float]],
    *,
    k: int,
    kind: str,
    acquisition: str,
    source: str,
    beta: float,
    xi: float,
    n_candidates: int,
    min_dist: float,
    seed: int,
    conformal_fallback: bool,
) -> dict[str, Any]:
    """采集族提议：候选池 → 不确定度 → 采集打分 → 距离过滤 → top-k。

    数学全部单源复用：estimate_uncertainty（T-N9 registry σ 源 +
    conformal_fallback）与 acquisition_scores（T-N9 采集三族，EI 公式
    单源 gp_det.expected_improvement）；本函数只做装载/过滤/排序编排。
    多指标按逐指标采集分求和归并（与 legacy "score=Σσ" 同构的确定性
    归并口径；单指标时即逐位=统一打分面输出）。
    """
    import numpy as np

    from rfauto.optimization.sample_design import lhs_points, np_rel
    from rfauto.service.active_learning import (
        ACQUISITION_KINDS,
        UNCERTAINTY_SOURCES,
        acquisition_scores,
        estimate_uncertainty,
    )

    if acquisition not in ACQUISITION_KINDS:
        return error_envelope(
            [f"未知采集函数: {acquisition}（可用: {list(ACQUISITION_KINDS)}）"])
    if source not in UNCERTAINTY_SOURCES:
        return error_envelope(
            [f"未知不确定度来源: {source}（可用: {list(UNCERTAINTY_SOURCES)}）"])
    bounds_t = {k: (float(v[0]), float(v[1])) for k, v in bounds.items()}
    cand = lhs_points(bounds_t, n_candidates, seed=seed)["points"]
    if not cand:
        return error_envelope(["候选池为空（n_candidates 必须 ≥1）"])
    try:
        unc = estimate_uncertainty(
            samples, bounds_t, cand, source=source, kind=kind, seed=seed,
            conformal_fallback=conformal_fallback)
    except (ValueError, TypeError) as exc:
        return error_envelope([str(exc)])
    if not unc.get("ok"):
        return {k: v for k, v in unc.items() if k != "points"}
    keys = list(unc.get("metric_keys") or [])
    pts = list(unc.get("points") or [])
    if not keys or not pts:
        return error_envelope(["不确定度通道未产出可用指标/候选"])
    means = np.array([[float(p["mean"][k]) for k in keys] for p in pts])
    sigmas = np.array([[float(p["sigma"][k]) for k in keys] for p in pts])
    # 逐指标采集分求和（ei 的 y_best 取该指标当前最优=样本最小值）
    scores = np.zeros(len(pts), dtype=float)
    for j, key in enumerate(keys):
        finite_vals = [float(s["metrics"][key]) for s in samples
                       if isinstance(s.get("metrics", {}).get(key), (int, float))
                       and not isinstance(s["metrics"][key], bool)
                       and math.isfinite(float(s["metrics"][key]))]
        if not finite_vals:
            raise ValueError(
                f"指标 {key!r} 无有限观测值：acquisition={acquisition!r} 需要 "
                "y_best 基准——请补该指标的有效样本或改用 sigma 采集档")
        y_best = min(finite_vals)
        scores += acquisition_scores(
            means[:, j], sigmas[:, j], acquisition=acquisition, beta=beta,
            xi=xi, y_best=y_best)

    names = sorted(bounds_t)
    lower = [bounds_t[n][0] for n in names]
    span = [max(bounds_t[n][1] - bounds_t[n][0], 1e-12) for n in names]
    include = [np_rel(s["params"], names, lower, span) for s in samples]
    ranked: list[tuple[float, int]] = []
    for i, pt in enumerate(cand):
        if i >= len(pts):
            break
        pn = np_rel(pt, names, lower, span)
        d_existing = min(
            (sum((pn[n] - q.get(n, pn[n])) ** 2 for n in names) ** 0.5
             for q in include), default=float("inf"))
        if d_existing < min_dist:
            continue
        ranked.append((float(scores[i]), i))
    ranked.sort(key=lambda t: t[0], reverse=True)
    proposed = [{"params": dict(cand[i]),
                 "score": round(s, 6),
                 "mean": dict(pts[i]["mean"]),
                 "sigma": dict(pts[i]["sigma"])}
                for s, i in ranked[:max(int(k), 0)]]
    fields: dict[str, Any] = {"mode": "acquisition"}
    if unc.get("sigma_source"):
        fields["sigma_source"] = unc["sigma_source"]
    return ok_envelope(
        acquisition=acquisition,
        uncertainty_source=source,
        surrogate_kind=kind,
        beta=float(beta),
        xi=float(xi),
        n_existing=len(samples),
        n_candidates=n_candidates,
        min_dist=float(min_dist),
        seed=int(seed),
        metric_keys=keys,
        bounds={k: list(v) for k, v in bounds.items()},
        proposed=proposed,
        **fields,
        note="score=采集函数打分（越大越该采样，逐指标求和）；"
             "提议点需真机复验后方可并入样本集（σ 仅由确定性内核产出，#7）",
    )


def al_propose(
    samples_path: str | Path | None = None,
    dataset: str | None = None,
    run: str | None = None,
    *,
    k: int = 5,
    kind: str = "nn",
    acquisition: str | None = None,
    source: str = "gp",
    beta: float = 2.0,
    xi: float = 0.0,
    n_candidates: int = 500,
    min_dist: float = 0.12,
    seed: int = 42,
    conformal_fallback: bool | None = None,
    out_dir: str | Path | None = None,
    runs_root: str | Path = "runs",
    max_rows: int = DEFAULT_MAX_ROWS,
) -> dict[str, Any]:
    """主动学习提议门：装载样本 → 提议下一批实验点（JSON 信封）。

    缺省（acquisition=None）走 legacy：整体转发宿主
    ``propose_next_points``（σ 求和 × 距离双重准则；conformal_fallback
    缺省 False=宿主缺省逐字节等价）。``acquisition`` 给出（lcb|ucb|ei|
    sigma）走采集族模式：不确定度来源 ``source``（gp|bootstrap|nn|
    registry；registry 需 kind=注册键，原生 σ 缺席按 conformal_fallback
    走 T-N1 共形包装——缺省 True 同 estimate_uncertainty 缺省）。

    负例（全部 ok=False 显式）：来源未给/多给/不存在、空样本、空参数域、
    零数值指标、未知采集名/来源、registry 缺 kind 或 kind 未注册。
    """
    loaded = load_al_samples(
        samples_path, dataset, run, out_dir=out_dir, runs_root=runs_root,
        max_rows=max_rows)
    if not loaded.get("ok"):
        return loaded
    samples: list[dict[str, Any]] = loaded["samples"]
    bounds: dict[str, list[float]] = loaded["bounds"]
    sample_source: str = loaded["sample_source"]

    if acquisition is None:
        cf = bool(conformal_fallback) if conformal_fallback is not None else False
        if sample_source == "samples":
            # 直通形态：宿主信封原样透出（零改动转发，等价钉逐位成立）
            return _propose_legacy(
                loaded["samples_path"], k=k, kind=kind,
                n_candidates=n_candidates, min_dist=min_dist, seed=seed,
                conformal_fallback=cf)
        # dataset/run 形态：内存样本落临时 samples.json 再进宿主（宿主
        # 契约是路径面；临时目录随 with 退出清空），信封 samples_path
        # 归一回逻辑来源（防临时路径非确定性进输出）
        with tempfile.TemporaryDirectory(prefix="rfauto_al_") as td:
            tmp = Path(td) / "samples.json"
            tmp.write_text(json.dumps(
                {"bounds": bounds, "objectives": [], "samples": samples}),
                encoding="utf-8")
            result = _propose_legacy(
                tmp, k=k, kind=kind, n_candidates=n_candidates,
                min_dist=min_dist, seed=seed, conformal_fallback=cf)
        if result.get("ok"):
            result["samples_path"] = _source_label(loaded)
            result["sample_source"] = sample_source
            result["bounds"] = bounds
        return result

    result = _propose_acquisition(
        samples, bounds, k=k, kind=kind, acquisition=acquisition,
        source=source, beta=beta, xi=xi, n_candidates=n_candidates,
        min_dist=min_dist, seed=seed,
        conformal_fallback=(bool(conformal_fallback)
                            if conformal_fallback is not None else True))
    if result.get("ok"):
        result["sample_source"] = sample_source
        result["source_label"] = _source_label(loaded)
        if loaded.get("truncated"):
            result["truncated"] = True
            result.setdefault("notes", []).append(loaded.get("note_extra"))
        if loaded.get("n_bad_json_rows"):
            result["n_bad_json_rows"] = loaded["n_bad_json_rows"]
    return result


def _source_label(loaded: dict[str, Any]) -> str:
    """装载形态 → 稳定标签（信封 samples_path 归一口径）。"""
    src = loaded.get("sample_source")
    if src == "samples":
        return str(loaded.get("samples_path"))
    if src == "dataset":
        return f"dataset:{loaded.get('dataset')}"
    if src == "run":
        return f"run:{loaded.get('run')}"
    return str(src)
