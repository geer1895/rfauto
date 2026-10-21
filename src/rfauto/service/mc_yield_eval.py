"""代理蒙特卡洛良率评估叶（T1 解环；架构批 W6-S1）。

从 uq_service 叶化：_mc_yield 判据簇（逐点回退 loop + 向量化批预测
两条实现，抽样序逐位一致锚见 docstring）被 fab_service（制造公差
良率）与 robustness_service（robustness_report）共用。叶化后两者改
读本叶，静态图上不再出现 fab→uq 边（fab↔uq 2-环断）。
测试缝不变：无测试 setattr 替换这些符号（grep 实证）；uq_service
同名再导出（内部与既有消费面零变化）。
"""
from __future__ import annotations

from itertools import combinations
from typing import Any


def _violates(value: float, op: Any, spec: Any) -> bool:
    from rfauto.core.objectives import MetricOp

    if op in (MetricOp.MAX_BELOW, "max_below"):
        return value > float(spec)
    if op in (MetricOp.MIN_ABOVE, "min_above"):
        return value < float(spec)
    if op in (MetricOp.MEAN_WITHIN, "mean_within") and isinstance(
            spec, (list, tuple)) and len(spec) == 2:
        return value < float(spec[0]) or value > float(spec[1])
    return False


def _numeric_pred(model: Any, params: dict[str, float]) -> dict[str, float]:
    """代理预测 → 仅数值指标字典（缺失参数按代理界内缺省处理）。"""
    pred = model.predict(params)
    return {k: float(v) for k, v in pred.items()
            if isinstance(v, (int, float))}


def _violate_mask(values: Any, op: Any, spec: Any) -> Any:
    """`_violates` 的向量化镜像（同一判据式，逐元素）。"""
    import numpy as np

    from rfauto.core.objectives import MetricOp

    if op in (MetricOp.MAX_BELOW, "max_below"):
        return values > float(spec)
    if op in (MetricOp.MIN_ABOVE, "min_above"):
        return values < float(spec)
    if op in (MetricOp.MEAN_WITHIN, "mean_within") and isinstance(
            spec, (list, tuple)) and len(spec) == 2:
        return (values < float(spec[0])) | (values > float(spec[1]))
    return np.zeros(np.shape(values), dtype=bool)


def _mc_predict_columns(
    model: Any, X: Any, names: list[str],
) -> dict[str, Any] | None:
    """批预测能力探测分派：poly_ridge 精确批 / smt_kriging 分块批 / None 回退。

    返回 {metric_key: (n,) 预测列}；None = 该代理无批路径，调用方退逐点
    循环（monkeypatch 注入的裸 predict 模型照旧工作，test_uq_service
    _SigmaStub 兼容面）。
    """
    import numpy as np

    bounds = getattr(model, "bounds", None)
    m_names = getattr(model, "names", None)
    if not (isinstance(bounds, dict) and isinstance(m_names, list)
            and set(m_names) == set(names)):
        return None
    idx = [names.index(nm) for nm in m_names]
    Xa = X[:, idx] if idx != list(range(len(names))) else X
    lo = np.array([float(bounds[n][0]) for n in m_names])
    span = np.array([max(float(bounds[n][1]) - float(bounds[n][0]), 1e-12)
                     for n in m_names])
    unit = np.clip((Xa - lo) / span, 0.0, 1.0)

    if getattr(model, "KIND", "") == "poly_ridge":
        coefs = getattr(model, "models", None)
        if not (isinstance(coefs, dict) and coefs
                and all(isinstance(c, np.ndarray) and c.ndim == 1
                        for c in coefs.values())):
            return None
        order = int(getattr(model, "effective_order",
                            getattr(model, "order", 2)))
        d = len(m_names)
        ncols = 1 + d + (d + d * (d - 1) // 2 if order >= 2 else 0)
        feats = np.empty((Xa.shape[0], ncols), dtype=float)
        feats[:, 0] = 1.0
        feats[:, 1:1 + d] = unit
        if order >= 2:
            feats[:, 1 + d:1 + 2 * d] = unit * unit
            col = 1 + 2 * d
            for i, j in combinations(range(d), 2):
                feats[:, col] = unit[:, i] * unit[:, j]
                col += 1
        return _project_columns_exact(feats, coefs)

    if getattr(model, "KIND", "") == "smt_kriging":
        krgs = getattr(model, "models", None)
        if not (isinstance(krgs, dict) and krgs):
            return None
        # GP 批预测分块（#258：小矩阵批量在多线程 OpenBLAS 下可能反而慢
        # ~85×；如外层环境可设 OPENBLAS_NUM_THREADS=1 建议设 1——库导入后
        # 运行时设置无效，此处仅分块 + 提示）。
        chunk = 32768
        n = Xa.shape[0]
        out: dict[str, np.ndarray] = {}
        for key, krg in krgs.items():
            colv = np.empty(n, dtype=float)
            for s in range(0, n, chunk):
                colv[s:s + chunk] = np.asarray(
                    krg.predict_values(unit[s:s + chunk]),
                    dtype=float).reshape(-1)
            out[key] = colv
        return out
    return None


def _mc_yield_loop(
    ctx: dict[str, Any],
    nominal: dict[str, float],
    tolerances: dict[str, float],
    *,
    n: int,
    seed: int,
) -> dict[str, Any]:
    """旧逐点循环实现（原样保留）：无批路径代理的回退 + 判据 d 的逐位参照。"""
    import numpy as np

    specs = ctx["specs"]
    rng = np.random.default_rng(seed)
    base_metrics = _numeric_pred(ctx["model"], nominal)
    draws = {p: rng.normal(0.0, float(s), n)
             for p, s in tolerances.items()}
    pass_count = 0
    metric_draws: dict[str, list[float]] = {s["metric"]: [] for s in specs}
    for i in range(n):
        pt = dict(nominal)  # 从完整名义点出发（缺参会被代理按界内零点处理）
        for p in draws:
            pt[p] = float(nominal[p] + draws[p][i])
        m = _numeric_pred(ctx["model"], pt)
        ok_all = True
        for s in specs:
            v = m.get(s["metric"])
            if v is None:
                ok_all = False
                break
            metric_draws[s["metric"]].append(v)
            if _violates(v, s["op"], s["spec"]):
                ok_all = False
        if ok_all:
            pass_count += 1
    yield_rate = pass_count / n

    metric_stats = {}
    for mname, vals in metric_draws.items():
        if not vals:
            continue
        arr = np.asarray(vals)
        metric_stats[mname] = {
            "mean": float(arr.mean()), "std": float(arr.std()),
            "q05": float(np.quantile(arr, 0.05)),
            "q95": float(np.quantile(arr, 0.95)),
        }
    return {
        "nominal_metrics": base_metrics,
        "yield_rate": yield_rate,
        "metric_stats": metric_stats,
        "implementation": "loop",
    }


def _mc_yield(
    ctx: dict[str, Any],
    nominal: dict[str, float],
    tolerances: dict[str, float],
    *,
    n: int,
    seed: int,
) -> dict[str, Any]:
    """名义点代理蒙特卡洛良率 + 指标分布（确定性内核，共用）。

    tolerances：{param: σ}；抽样仅覆盖公差参数，名义点其余坐标保持不动
    （与阶段 6.4 首片语义一致）。

    DP-15 C3 向量化重写（numpy 批预测；DuckDB/Parquet 落盘见
    ``store_mc_draws``）：抽样序与旧逐点实现逐位一致（default_rng(seed)
    依 tolerances 插入序逐参数 ``normal(0, σ, n)``，同种子前缀性质实测）；
    poly_ridge 走系数闭式批投影（探针核对 gemv 与逐行 dot 逐位一致后才用
    gemv，否则退逐行——判据 d），smt_kriging 走 KRG 批预测分块（#258），
    其余代理回退 ``_mc_yield_loop`` 逐点路径（行为零变化）。判 Violation
    的 early-break 语义（首个缺指标 spec 之后的 spec 不收样本、该 draw 判
    fail）逐位复刻。新增键 ``implementation``（vectorized|loop）与
    ``wall_s``——既有键/语义零变化。
    """
    import time

    import numpy as np

    t0 = time.perf_counter()
    specs = ctx["specs"]
    model = ctx["model"]
    base_metrics = _numeric_pred(model, nominal)
    rng = np.random.default_rng(seed)
    draws = {p: rng.normal(0.0, float(s), n)
             for p, s in tolerances.items()}
    names = sorted(ctx["bounds"])
    X = np.empty((n, len(names)), dtype=float)
    for j, nm in enumerate(names):
        base = float(nominal.get(nm, ctx["bounds"][nm][0]))
        if nm in draws:
            X[:, j] = base + draws[nm]
        else:
            X[:, j] = base

    cols: dict[str, Any] | None = None
    try:
        cols = _mc_predict_columns(model, X, names)
    except Exception:
        cols = None  # 批路径故障退逐点（行为回到旧实现，不半途凑数）
    if cols is None:
        result = _mc_yield_loop(ctx, nominal, tolerances, n=n, seed=seed)
        result["wall_s"] = time.perf_counter() - t0
        return result

    # 缺指标 early-break 语义复刻：首个缺指标 spec 之后的不收样本；且该
    # spec 判 fail → 该 draw 整体不通过（与旧循环 ok_all=False 一致）
    first_missing = next((i for i, s in enumerate(specs)
                          if s["metric"] not in cols), None)
    collected = specs if first_missing is None else specs[:first_missing]
    if first_missing is None:
        pass_mask = np.ones(n, dtype=bool)
        for s in collected:
            pass_mask &= ~_violate_mask(cols[s["metric"]], s["op"],
                                        s["spec"])
    else:
        pass_mask = np.zeros(n, dtype=bool)
    yield_rate = float(pass_mask.sum()) / n

    metric_stats = {}
    for s in collected:
        arr = np.asarray(cols[s["metric"]], dtype=float)
        metric_stats[s["metric"]] = {
            "mean": float(arr.mean()), "std": float(arr.std()),
            "q05": float(np.quantile(arr, 0.05)),
            "q95": float(np.quantile(arr, 0.95)),
        }
    return {
        "nominal_metrics": base_metrics,
        "yield_rate": yield_rate,
        "metric_stats": metric_stats,
        "implementation": "vectorized",
        "wall_s": time.perf_counter() - t0,
        # 内部列（store_mc_draws/robustness_report 消费；非对外契约键）
        "_draw_columns": {"names": names, "X": X, "cols": cols,
                          "pass_mask": pass_mask},
    }

def _project_columns_exact(
    feats: Any, coefs: dict[str, Any],
) -> dict[str, Any]:
    """特征矩阵 × 系数 → 逐指标列，逐位等同旧实现的逐行 ``feats @ coef``。

    BLAS gemv（2D@1D）与逐行 dot（1D@1D）的累加顺序可能差 ulp（实测）；
    先 gemv 后用前 256 行逐行 dot 探针核对，逐位一致才保留 gemv 结果，
    否则整列退逐行 dot（实测 1e6×21 约 0.9s，48s 预算内）——逐位一致性
    优先于速度（判据 d）。
    """
    import numpy as np

    out: dict[str, np.ndarray] = {}
    probe = min(feats.shape[0], 256)
    for key, coef in coefs.items():
        gemv = feats @ coef
        if probe:
            per_row_probe = np.array(
                [feats[i] @ coef for i in range(probe)])
            if not np.array_equal(gemv[:probe], per_row_probe):
                gemv = np.array([feats[i] @ coef
                                 for i in range(feats.shape[0])])
        out[key] = gemv
    return out
