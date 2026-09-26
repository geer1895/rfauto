"""uq_service：代理免费蒙特卡洛 UQ（阶段 6.4 首片；WP4.2 公差/良率收口）。

代理就位后，10k 点蒙特卡洛零仿真成本——产出：
- 良率（yield）：名义点公差盒内 objectives 满足概率；
- 指标分布统计（mean/std/分位数）；
- 参数扰动敏感性排序（单参数 σ 扫描对违约概率的边际影响）。

WP4.2 收口（2026-09-14，方案 §4）：
- surrogate_yield_at：显式名义点的良率求值（良率目标函数点值形式，
  供外部优化器/中心化逐点驱动）；
- yield_design_center：良率目标函数（容差盒确定性网格上代理违约
  cost ≤ 0 比例，复用 core/pce.tolerance_yield/design_centering 内核）
  + 坐标 pattern search 设计中心化；蒙特卡洛只在中心化前后做认证
  报告——搜索不吃随机噪声；
- temperature_zone_yield：D9 环境包络（core/bands.env_to_uq_axis 温度轴）
  → σ_c 并入 t_c 维度做代理蒙特卡洛 + 温区两端确定性角点评估
  （温区良率待接收口，D9 已 ✅）。

与 tolerance 模块的差别：tolerance 每点真机求解（贵，n≤数百）；
本模块全部在代理上（免费，n≥10k），代理可信度由校准 gate 背书。
数值全部确定性内核。

DP-13 R1 spread-skill 总闸：全部四个输出面带 ``uncertainty_status``——
代理 σ 与真实误差的 Spearman ρ ≥ 0.5（spread_skill 门）→
``quantitative``（"±"标注可采信）；不过门/代理无 σ（uncertainty→None）
→ ``qualitative``（"±"降级定性标注，数据不删）。

DP-15 C3 良率流水线第二片：``_mc_yield`` 向量化重写（numpy 批预测，
poly_ridge 系数闭式批投影逐位兼容 / smt_kriging KRG 批预测分块（#258）/
其余代理回退逐点循环），抽样序与旧实现逐位一致；新增 ``store_mc_draws``
把 MC 抽样/预测列落 Parquet+manifest（``runs/datasets`` 形态，复用
``query_dataset`` 读面；全量计数以 manifest ``n_rows`` 为准——#369）。
robustness_report 编排面见 service/robustness_service.py。
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any


def _metric_key(metric: str) -> str:
    """objectives 指标名 → compute_metrics 产物键（与 tolerance 模块同约定）。"""
    from rfauto.core.objectives import DEFAULT_METRIC_KEY

    return DEFAULT_METRIC_KEY.get(metric, metric)


# ─── R1 spread-skill 总闸（DP-13）────────────────────────────────────────────

#: spread-skill 门（预声明 runs/df6_dp13/criteria.md §R1）：Spearman ρ ≥
#: SPREAD_SKILL_GATE 才判 quantitative（"±"标注可采信），不过则降级定性
#: （标注降级、数据不删）。
SPREAD_SKILL_GATE = 0.5
#: 判 ρ 的最少样本对（少于该数无法有意义地算 Spearman，如实 qualitative）。
SPREAD_SKILL_MIN_PAIRS = 3


def spread_skill(
    pairs: list[tuple[float, float]], *, gate: float = SPREAD_SKILL_GATE,
) -> dict[str, Any]:
    """(预测σ, |误差|) 对 → Spearman ρ spread-skill 门（DP-13 R1，纯函数）。

    预测不确定性与真实误差的秩相关：ρ ≥ gate → ``quantitative``（σ 与误差
    同向散开，"±"标注可采信）；否则 ``qualitative``（"±"降级为定性标注，
    **数据一律不删**）。退化情形（n<3 / σ 或 |误差| 无离散度 → ρ NaN）如实
    qualitative + reason，不凑数。裁判先过已知基准：合成回收钉见
    tests/unit/test_uq_service.py（σ∝|噪声| 过门 / 随机 σ 不过门）。
    """
    clean = [(float(s), float(e)) for s, e in pairs
             if s is not None and e is not None
             and math.isfinite(float(s)) and math.isfinite(float(e))]
    n = len(clean)
    if n < SPREAD_SKILL_MIN_PAIRS:
        return {
            "ok": False, "status": "qualitative", "spearman_rho": None,
            "gate": float(gate), "n_pairs": n,
            "reason": f"有效样本对 {n} <{SPREAD_SKILL_MIN_PAIRS}，无法计算 Spearman ρ",
        }
    sigmas = [p[0] for p in clean]
    errors = [p[1] for p in clean]
    if len(set(sigmas)) < 2 or len(set(errors)) < 2:
        return {
            "ok": False, "status": "qualitative", "spearman_rho": None,
            "gate": float(gate), "n_pairs": n,
            "reason": "σ 或 |误差| 无离散度，ρ 退化",
        }
    from scipy.stats import spearmanr

    res = spearmanr(sigmas, errors)
    rho = getattr(res, "statistic", None)
    if rho is None:  # 旧 scipy 属性名兼容
        rho = getattr(res, "correlation", None)
    rho_f = float(rho) if rho is not None and math.isfinite(float(rho)) else None
    if rho_f is None:
        return {
            "ok": False, "status": "qualitative", "spearman_rho": None,
            "gate": float(gate), "n_pairs": n,
            "reason": "Spearman ρ 非有限值（退化）",
        }
    ok = rho_f >= float(gate)
    return {
        "ok": bool(ok), "status":
            "quantitative" if ok else "qualitative",
        "spearman_rho": rho_f, "gate": float(gate), "n_pairs": n,
    }


def _spread_skill_for_model(
    model: Any, samples: list[dict[str, Any]], objs: list[Any], *,
    gate: float = SPREAD_SKILL_GATE,
) -> dict[str, Any]:
    """拟合代理的 uncertainty-vs-误差 spread-skill 评估（uq 输出面共用）。

    逐样本取 uncertainty(params)[指标键] 为预测 σ、|pred−actual| 为真实误差；
    模型无 σ（uncertainty→None，如 poly_ridge 缺省）→ qualitative + reason。
    """
    if not objs:
        return {"ok": False, "status": "qualitative", "spearman_rho": None,
                "gate": float(gate), "n_pairs": 0,
                "reason": "无 objectives，无从取误差指标"}
    key = _metric_key(objs[0].metric)
    pairs: list[tuple[float, float]] = []
    for s in samples:
        try:
            unc = model.uncertainty(dict(s.get("params") or {}))
        except Exception:
            unc = None
        if not isinstance(unc, dict) or key not in unc:
            return {"ok": False, "status": "qualitative",
                    "spearman_rho": None, "gate": float(gate),
                    "n_pairs": 0,
                    "reason": "代理无不确定性估计（uncertainty→None）"
                              f"或缺指标键 {key}"}
        try:
            sigma = abs(float(unc[key]))
            actual = float(s["metrics"][key])
            pred = float(_numeric_pred(model, dict(s["params"]))[key])
        except (KeyError, TypeError, ValueError):
            continue
        pairs.append((sigma, abs(pred - actual)))
    return spread_skill(pairs, gate=gate)


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


def build_yield_context(
    samples: list[dict[str, Any]],
    bounds: dict[str, tuple[float, float]],
    objectives: list[dict[str, Any]],
    tolerances: dict[str, float],
    *,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
) -> tuple[dict[str, Any] | None, list[str] | None]:
    """样本列表/界/objectives → 代理拟合 yield 上下文（surrogate_yield 族共用）。

    DP-15 C3 从 ``_load_yield_context`` 拆出的内存版装载面：dataset/
    robustness_report 等非 samples.json 来源构造同构 ctx（键集/语义与
    ``_load_yield_context`` 逐键一致）。返回 (ctx, None) 或 (None, errors)。
    """
    if len(samples) < 5:
        return None, ["样本点不足（需 ≥5）以拟合代理"]
    if not objectives:
        return None, ["样本集无 objectives，无从定义良率"]
    bounds = {k: (float(v[0]), float(v[1])) for k, v in bounds.items()}
    bad_tol = [k for k in tolerances if k not in bounds]
    if bad_tol:
        return None, [f"公差参数不在搜索空间: {bad_tol}"]

    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.service.calibration_service import _make_model

    objs = [Objective(**o) for o in objectives]
    model = _make_model(kind, bounds, order=order, ridge_lambda=ridge_lambda)
    model.fit(samples)

    def cost_of(s: dict[str, Any]) -> float:
        return SpecEvaluator.evaluate_objectives(s["metrics"], objs)

    nominal_sample = min(samples, key=cost_of)
    ctx = {
        "path": None,
        "samples": samples,
        "bounds": bounds,
        "objs": objs,
        "specs": [{"metric": _metric_key(o.metric), "op": o.op,
                   "spec": o.value} for o in objs],
        "model": model,
        "nominal_sample": nominal_sample,
        # R1 spread-skill 总闸：代理 σ 与真实误差的 Spearman ρ 门
        # （ρ≥0.5 → quantitative；不过/无 σ → qualitative，数据不删）。
        # 惰性求值改直求（模型已拟合，逐样本 uncertainty 纯内存）。
        "uncertainty_status": _spread_skill_for_model(model, samples, objs),
    }
    return ctx, None


def _load_yield_context(
    samples_path: str | Path,
    tolerances: dict[str, float],
    *,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
) -> tuple[dict[str, Any] | None, list[str] | None]:
    """样本集装载/校验/代理拟合（surrogate_yield 族共用）。

    返回 (ctx, None) 或 (None, errors)。ctx 含 path/bounds/objs/specs/
    model/nominal_sample；名义样本 = 校准样本集中 cost 最小者（确定性）。
    tolerances 允许为空（temperature_zone_yield 的温度 σ 由包络提供）。
    """
    path = Path(samples_path)
    if not path.exists():
        return None, [f"样本集不存在: {path}"]
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = list(data.get("samples") or [])
    objectives = list(data.get("objectives") or [])
    bounds_raw = data.get("bounds") or {}

    ctx, errors = build_yield_context(
        samples, bounds_raw, objectives, tolerances,
        kind=kind, order=order, ridge_lambda=ridge_lambda)
    if ctx is not None:
        ctx["path"] = path
    return ctx, errors


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


def _vector_spec_cost(
    cols: dict[str, Any], objs: list[Any],
) -> Any:
    """SpecEvaluator.evaluate_objectives 的向量化镜像（逐 draw 加权违约和）。

    与逐点版同一公式（MAX_BELOW/MIN_ABOVE/BANDWIDTH 铰链 + MEAN_WITHIN 双侧
    铰链，weight 加权，缺失指标键跳过）；供 MC 落盘 cost 列与 FORM 失效面
    g(x) = threshold − cost(x) 使用。
    """
    import numpy as np

    from rfauto.core.objectives import MetricOp, SpecEvaluator

    n = next(iter(cols.values())).shape[0] if cols else 0
    cost = np.zeros(n, dtype=float)
    for o in objs:
        val = None
        for k in SpecEvaluator.metric_key_candidates(o.metric, o.op):
            if k in cols:
                val = cols[k]
                break
        if val is None:
            continue
        v = np.asarray(val, dtype=float)
        w = float(getattr(o, "weight", 1.0))
        raw = o.value
        if o.op == MetricOp.MAX_BELOW:
            thr = float(raw if isinstance(raw, (int, float)) else raw[0])
            cost += w * np.maximum(0.0, v - thr)
        elif o.op == MetricOp.MIN_ABOVE:
            thr = float(raw if isinstance(raw, (int, float)) else raw[0])
            cost += w * np.maximum(0.0, thr - v)
        elif o.op == MetricOp.MEAN_WITHIN:
            if isinstance(raw, list) and len(raw) == 2:
                low, high = float(raw[0]), float(raw[1])
                cost += w * np.where(v < low, low - v,
                                     np.where(v > high, v - high, 0.0))
        elif o.op == MetricOp.BANDWIDTH:
            thr = float(raw if isinstance(raw, (int, float)) else raw[0])
            cost += w * np.maximum(0.0, thr - v)
    return cost


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


def store_mc_draws(
    name: str,
    mc: dict[str, Any],
    *,
    objs: list[Any] | None = None,
    out_dir: str | Path = "runs/datasets",
    seed: int | None = None,
    source_dataset: str | None = None,
) -> dict[str, Any]:
    """MC 抽样/预测列 → Parquet 数据集 + manifest（复用 query_dataset 读面）。

    平面向量 schema：``draw_index / param__<name>… / metric__<key>… /
    is_pass / cost``（pyarrow 向量化写，1e6 行秒级；不用逐行 JSON——
    1e6 次 json.dumps 会吃掉 48s 预算）。manifest 记 ``n_rows``=全量行数
    ——消费侧全量计数以 manifest 为准，``query_dataset`` 的 ``n_rows`` 是
    limit 截断后返回行数（#369 口径）。is_pass 用 ``_violates`` 语义
    （specs 判据），cost 用 ``SpecEvaluator`` 加权违约和（含 BANDWIDTH；
    两者在带宽类目标上语义不同，如实分列）。objs = objectives 列表
    （robustness_report 传 ctx["objs"]），None 则不写 cost 列。
    """
    internal = mc.get("_draw_columns")
    if not internal:
        return {"ok": False,
                "errors": ["store_mc_draws 需要向量化 _mc_yield 产物"
                           "（缺 _draw_columns；loop 路径不可落盘）"]}
    try:
        from rfauto.service.dataset_service import (
            MANIFEST_NAME,
            PARQUET_NAME,
            SCHEMA_VERSION,
            _import_pyarrow,
            _validate_dataset_name,
        )

        name = _validate_dataset_name(name)
        pa, pq = _import_pyarrow()
    except (ImportError, RuntimeError, ValueError) as exc:
        return {"ok": False, "errors": [str(exc)]}
    import numpy as np
    import yaml

    names: list[str] = internal["names"]
    X = internal["X"]
    cols: dict[str, Any] = internal["cols"]
    pass_mask = internal["pass_mask"]
    n = int(pass_mask.shape[0])
    arrays: list[Any] = [pa.array(np.arange(n, dtype=np.int64))]
    fields: list[tuple[str, str]] = [("draw_index", "int64")]
    for j, nm in enumerate(names):
        arrays.append(pa.array(np.ascontiguousarray(X[:, j])))
        fields.append((f"param__{nm}", "float64"))
    for key, col in cols.items():
        arrays.append(pa.array(np.ascontiguousarray(
            np.asarray(col, dtype=float))))
        fields.append((f"metric__{key}", "float64"))
    arrays.append(pa.array(pass_mask.astype(np.int8)))
    fields.append(("is_pass", "int8"))
    if objs:
        cost = _vector_spec_cost(cols, objs)
        arrays.append(pa.array(np.ascontiguousarray(cost)))
        fields.append(("cost", "float64"))

    table = pa.Table.from_arrays(arrays, names=[f for f, _t in fields])
    schema_map = dict(fields)
    dataset_dir = Path(out_dir) / name
    dataset_dir.mkdir(parents=True, exist_ok=True)
    points_path = dataset_dir / PARQUET_NAME
    pq.write_table(table, points_path)

    bounds = {nm: (float(X[:, j].min()), float(X[:, j].max()))
              for j, nm in enumerate(names)}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "format": "parquet",
        "points_file": points_path.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_runs": [{"run_id": f"mc:{name}", "n_points": n}],
        "n_points": n,
        "n_rows": n,  # 全量行数（#369：query_dataset n_rows 是 limit 截断语义）
        "n_dup": 0,
        "bounds": {k: list(v) for k, v in bounds.items()},
        "columns": [c for c, _t in fields],
        "visibility": "private",
        "generator": {
            "kind": "uq_service.store_mc_draws",
            "seed": seed,
            "n_draws": n,
            "implementation": mc.get("implementation"),
            "yield_rate": mc.get("yield_rate"),
            "wall_s": mc.get("wall_s"),
            "source_dataset": source_dataset,
            "column_types": schema_map,
        },
    }
    (dataset_dir / MANIFEST_NAME).write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return {
        "ok": True, "name": name, "dataset_dir": str(dataset_dir),
        "points_file": str(points_path), "n_rows": n,
        "columns": manifest["columns"],
    }


def surrogate_yield(
    samples_path: str | Path,
    tolerances: dict[str, float] | None = None,
    *,
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
    tolerance_source: Any = None,
) -> dict[str, Any]:
    """代理蒙特卡洛良率/分布/敏感性（JSON 契约）。

    tolerances：{param: σ}（与该参数同单位）。名义点 = 校准样本集中
    cost 最小的点（确定性）。

    DP-7 P2 输入规范化（只追加，缺省行为零变化）：``tolerance_source``
    （dict/str/Path，形态见 fab_service.resolve_tolerance_source）引用
    fab 剖面 → σ 由公差单源自动展开（trace=名义×trace_tol_pct/100/k_sigma、
    板厚=剖面字段、εr=materials.yaml 声明），此时 ``tolerances`` 必须为
    空（二选一）；输出追加 ``tolerance_provenance``（逐参数 source），
    ``tolerances`` 键为派生 σ。不传 tolerance_source 的调用路径与输出
    键集逐字节不变。
    """
    use_source = tolerance_source is not None
    if use_source and tolerances:
        return {"ok": False, "errors": [
            "tolerances 与 tolerance_source 二选一（DP-7 P2 单源：引用"
            "剖面时 σ 由 fab 剖面派生，不手工直传）"]}
    if not use_source and not tolerances:
        return {"ok": False, "errors": ["缺少 tolerances（{param: σ}）"]}
    if n < 1:
        return {"ok": False, "errors": [f"n 必须 ≥1，收到: {n}"]}
    ctx, errors = _load_yield_context(
        samples_path, tolerances or {}, kind=kind, order=order,
        ridge_lambda=ridge_lambda)
    if ctx is None:
        return {"ok": False, "errors": errors}

    nominal = {k: float(v) for k, v in ctx["nominal_sample"]["params"].items()}
    provenance: dict[str, Any] | None = None
    if use_source:
        from rfauto.service.fab_service import resolve_tolerance_source

        res = resolve_tolerance_source(tolerance_source, nominal)
        if not res.get("ok"):
            return {"ok": False,
                    "errors": list(res.get("errors")
                                   or ["tolerance_source 解析失败"])}
        derived = {k: float(v) for k, v in (res.get("sigmas") or {}).items()}
        bad = [k for k in derived if k not in ctx["bounds"]]
        if bad:
            return {"ok": False,
                    "errors": [f"派生公差参数不在搜索空间: {bad}"]}
        if not derived:
            return {"ok": False, "errors": [
                "tolerance_source 未派生出任何参数公差"
                "（检查样本参数分类/材料声明）"]}
        tolerances = derived
        provenance = res.get("provenance")
    mc = _mc_yield(ctx, nominal, tolerances, n=n, seed=seed)
    base_metrics = mc["nominal_metrics"]

    # 敏感性排序：单参数 ±1σ 扰动的指标响应幅值 |Δmetric| 求和（确定性）。
    #    不用违约计数——稳健区违约恒 0 无区分度。
    specs = ctx["specs"]
    model = ctx["model"]
    base_by_metric = {s["metric"]: base_metrics.get(s["metric"])
                      for s in specs}
    sensitivity = {}
    for p, sigma in tolerances.items():
        total = 0.0
        for sign in (1.0, -1.0):
            pt = dict(nominal)
            pt[p] = float(nominal[p]) + sign * float(sigma)
            m = _numeric_pred(model, pt)
            for s in specs:
                v = m.get(s["metric"])
                b = base_by_metric.get(s["metric"])
                if v is not None and b is not None:
                    total += abs(v - b)
        sensitivity[p] = float(total)

    ranked = sorted(sensitivity, key=lambda k: sensitivity[k], reverse=True)
    out: dict[str, Any] = {
        "ok": True,
        "samples_path": str(ctx["path"]),
        "uncertainty_status": ctx["uncertainty_status"],
        "surrogate_kind": kind,
        "n_draws": n,
        "seed": seed,
        "nominal_params": nominal,
        "nominal_metrics": base_metrics,
        "tolerances": tolerances,
        "yield_rate": mc["yield_rate"],
        "metric_stats": mc["metric_stats"],
        "implementation": mc["implementation"],
        "sensitivity_ranking": ranked,
        "sensitivity_violation_delta": sensitivity,
    }
    if provenance is not None:  # DP-7 P2：仅 tolerance_source 分支追加
        out["tolerance_provenance"] = provenance
    return out


def surrogate_yield_at(
    samples_path: str | Path,
    tolerances: dict[str, float] | None = None,
    nominal: dict[str, float] | None = None,
    *,
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
    tolerance_source: Any = None,
) -> dict[str, Any]:
    """显式名义点的代理蒙特卡洛良率（良率目标函数点值形式，JSON 契约）。

    与 surrogate_yield 的差别：名义点由调用方给定（优化器/中心化外部
    驱动逐点求值），不取样本集 cost 最小点。nominal 须覆盖全部公差参数。

    DP-7 P2 输入规范化（只追加，缺省行为零变化）：``tolerance_source``
    引用形态同 :func:`surrogate_yield`（此时 ``tolerances`` 必须为空），
    σ 由公差单源在给定名义点上派生；输出追加
    ``tolerance_provenance``。
    """
    if n < 1:
        return {"ok": False, "errors": [f"n 必须 ≥1，收到: {n}"]}
    if not nominal:
        return {"ok": False, "errors": ["名义点为空"]}
    use_source = tolerance_source is not None
    if use_source and tolerances:
        return {"ok": False, "errors": [
            "tolerances 与 tolerance_source 二选一（DP-7 P2 单源：引用"
            "剖面时 σ 由 fab 剖面派生，不手工直传）"]}
    ctx, errors = _load_yield_context(
        samples_path, tolerances or {}, kind=kind, order=order,
        ridge_lambda=ridge_lambda)
    if ctx is None:
        return {"ok": False, "errors": errors}
    bad = [k for k in nominal if k not in ctx["bounds"]]
    if bad:
        return {"ok": False, "errors": [f"名义点参数不在搜索空间: {bad}"]}
    missing = [p for p in (tolerances or {}) if p not in nominal]
    if missing:
        return {"ok": False, "errors": [f"名义点缺少公差参数: {missing}"]}

    nom = {k: float(v) for k, v in nominal.items()}
    provenance: dict[str, Any] | None = None
    if use_source:
        from rfauto.service.fab_service import resolve_tolerance_source

        res = resolve_tolerance_source(tolerance_source, nom)
        if not res.get("ok"):
            return {"ok": False,
                    "errors": list(res.get("errors")
                                   or ["tolerance_source 解析失败"])}
        derived = {k: float(v) for k, v in (res.get("sigmas") or {}).items()}
        bad_derived = [k for k in derived if k not in ctx["bounds"]]
        if bad_derived:
            return {"ok": False,
                    "errors": [f"派生公差参数不在搜索空间: {bad_derived}"]}
        missing = [p for p in derived if p not in nom]
        if missing:
            return {"ok": False,
                    "errors": [f"名义点缺少派生公差参数: {missing}"]}
        if not derived:
            return {"ok": False, "errors": [
                "tolerance_source 未派生出任何参数公差"
                "（检查名义参数分类/材料声明）"]}
        tolerances = derived
        provenance = res.get("provenance")
    mc = _mc_yield(ctx, nom, tolerances, n=n, seed=seed)
    out: dict[str, Any] = {
        "ok": True,
        "samples_path": str(ctx["path"]),
        "uncertainty_status": ctx["uncertainty_status"],
        "surrogate_kind": kind,
        "n_draws": n,
        "seed": seed,
        "nominal_params": nom,
        "nominal_metrics": mc["nominal_metrics"],
        "tolerances": tolerances,
        "yield_rate": mc["yield_rate"],
        "metric_stats": mc["metric_stats"],
        "implementation": mc["implementation"],
    }
    if provenance is not None:  # DP-7 P2：仅 tolerance_source 分支追加
        out["tolerance_provenance"] = provenance
    return out


def yield_design_center(
    samples_path: str | Path,
    tolerances: dict[str, float],
    *,
    k_sigma: float = 3.0,
    n_levels: int = 3,
    max_iter: int = 40,
    step_frac: float = 0.25,
    shrink: float = 0.5,
    n_mc: int = 2000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
) -> dict[str, Any]:
    """良率目标函数 + 设计中心化（WP4.2 收口，JSON 契约）。

    良率目标函数：容差盒确定性网格上代理违约 cost（SpecEvaluator 加权
    violation 和）≤ 0 的比例——cost ≤ 0 ⇔ 全规格通过；网格求值与坐标
    pattern search 复用 core/pce.tolerance_yield/design_centering 内核，
    搜索不吃随机噪声。tolerances：{param: σ}；容差盒半宽 = k_sigma·σ
    （项目公差惯例，与 optimization/tolerance.py 3σ 口径一致）。
    蒙特卡洛（surrogate_yield 内核，σ 抽样）只在中心化前后做认证报告
    （initial_yield_mc / final_yield_mc）。
    """
    if k_sigma <= 0:
        return {"ok": False, "errors": [f"k_sigma 必须 >0，收到: {k_sigma}"]}
    if n_levels < 2:
        return {"ok": False, "errors": [f"n_levels 必须 ≥2，收到: {n_levels}"]}
    if n_mc < 1:
        return {"ok": False, "errors": [f"n_mc 必须 ≥1，收到: {n_mc}"]}
    ctx, errors = _load_yield_context(
        samples_path, tolerances, kind=kind, order=order,
        ridge_lambda=ridge_lambda)
    if ctx is None:
        return {"ok": False, "errors": errors}

    from rfauto.core.objectives import SpecEvaluator
    from rfauto.core.pce import design_centering

    model = ctx["model"]
    objs = ctx["objs"]
    bounds = ctx["bounds"]

    # 指标键守卫：目标指标必须落在代理预测面。evaluate_objectives 对缺失
    # 键静默跳过 → 缺指标时良率会被虚高成 1.0，必须前置显式报错。
    box_mid = {name: 0.5 * (lo + hi) for name, (lo, hi) in bounds.items()}
    pred_keys = set(_numeric_pred(model, box_mid))
    missing_metrics = [o.metric for o in objs if not any(
        k in pred_keys
        for k in SpecEvaluator.metric_key_candidates(o.metric, o.op))]
    if missing_metrics:
        return {"ok": False,
                "errors": [f"目标指标不在代理预测面: {missing_metrics}"]}

    def cost_fn(point: dict[str, float]) -> float:
        return SpecEvaluator.evaluate_objectives(model.predict(point), objs)

    half_widths = {p: float(k_sigma) * float(s) for p, s in tolerances.items()}
    param_specs = {name: {"low": lo, "high": hi}
                   for name, (lo, hi) in bounds.items()}
    grid = design_centering(
        param_specs, cost_fn, spec_max=0.0, tolerances=half_widths,
        n_levels=n_levels, max_iter=max_iter, step_frac=step_frac,
        shrink=shrink)

    mc_initial = _mc_yield(ctx, dict(grid["initial_center"]), tolerances,
                           n=n_mc, seed=seed)
    mc_final = _mc_yield(ctx, dict(grid["center"]), tolerances,
                         n=n_mc, seed=seed)
    return {
        "ok": True,
        "samples_path": str(ctx["path"]),
        "uncertainty_status": ctx["uncertainty_status"],
        "surrogate_kind": kind,
        "objective": "tolerance_box_grid_cost_violation(spec_max=0)",
        "k_sigma": float(k_sigma),
        "tolerances": tolerances,
        "box_half_widths": half_widths,
        "n_levels": n_levels,
        "initial_center": grid["initial_center"],
        "initial_yield": grid["initial_yield"],
        "initial_yield_rate": grid["initial_yield"],
        "center": grid["center"],
        "yield": grid["yield"],
        "yield_rate": grid["yield"],
        "worst_cost": grid["worst_cost"],
        "n_evaluations": grid["n_evaluations"],
        "initial_yield_mc": mc_initial["yield_rate"],
        "final_yield_mc": mc_final["yield_rate"],
        "n_mc": n_mc,
        "seed": seed,
        "implementation": mc_final["implementation"],
    }


def temperature_zone_yield(
    samples_path: str | Path,
    tolerances: dict[str, float],
    env_key: str,
    *,
    t_ref_c: float | None = None,
    k_sigma: float = 3.0,
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
) -> dict[str, Any]:
    """温区良率（WP4.2 ← D9 环境包络待接收口，JSON 契约）。

    D9 环境包络（core/bands.ENVIRONMENTS）→ env_to_uq_axis 温度轴
    （名义 = t_ref_c，σ_c = 包络半宽/k_sigma），σ_c 并入 t_c 维度做代理
    蒙特卡洛；温区两端（t_min_c/t_max_c）做确定性角点评估。要求校准
    样本集含 t_c 维度（D8 温度轴校准集）；温度 σ 以包络为准（调用方若
    传 t_c 公差会被包络覆盖）。tolerances 可为空（只做温度维扰动）。
    """
    from rfauto.core.bands import env_to_delta_t, env_to_uq_axis, get_env

    if k_sigma <= 0:
        return {"ok": False, "errors": [f"k_sigma 必须 >0，收到: {k_sigma}"]}
    if n < 1:
        return {"ok": False, "errors": [f"n 必须 ≥1，收到: {n}"]}
    try:
        env = get_env(env_key)
        axis = env_to_uq_axis(env_key, t_ref_c=t_ref_c, k_sigma=k_sigma)
        delta_t = env_to_delta_t(env_key, t_ref_c=t_ref_c)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "errors": [str(exc)]}

    ctx, errors = _load_yield_context(
        samples_path, tolerances, kind=kind, order=order,
        ridge_lambda=ridge_lambda)
    if ctx is None:
        return {"ok": False, "errors": errors}
    if "t_c" not in ctx["bounds"]:
        return {"ok": False, "errors": [
            "样本集无 t_c 维度（温区良率要求 D8 温度轴校准集含 t_c 参数）"]}

    # 温度 σ 以包络为准（覆盖调用方同名入参），其余参数公差照常
    merged = {**tolerances, "t_c": float(axis["sigma_c"])}
    nominal = {k: float(v) for k, v in ctx["nominal_sample"]["params"].items()}
    nominal["t_c"] = float(axis["nominal_c"])

    mc = _mc_yield(ctx, nominal, merged, n=n, seed=seed)

    # 温区角点（确定性）：包络端点处代理指标与规格判据
    specs = ctx["specs"]
    corners: dict[str, Any] = {}
    for label, t_val in (("t_min_c", env.t_min_c), ("t_max_c", env.t_max_c)):
        pt = dict(nominal)
        pt["t_c"] = float(t_val)
        m = _numeric_pred(ctx["model"], pt)
        ok_all = True
        for s in specs:
            v = m.get(s["metric"])
            if v is None or _violates(v, s["op"], s["spec"]):
                ok_all = False
        corners[label] = {"t_c": float(t_val), "metrics": m,
                          "pass": ok_all}

    return {
        "ok": True,
        "samples_path": str(ctx["path"]),
        "uncertainty_status": ctx["uncertainty_status"],
        "surrogate_kind": kind,
        "n_draws": n,
        "seed": seed,
        "env_key": env.key,
        "env": env.to_dict(),
        "axis": axis,
        "delta_t": delta_t,
        "sigma_c": float(axis["sigma_c"]),
        "half_range_c": float(axis["half_range_c"]),
        "nominal_params": nominal,
        "nominal_metrics": mc["nominal_metrics"],
        "tolerances": merged,
        "yield_rate": mc["yield_rate"],
        "metric_stats": mc["metric_stats"],
        "implementation": mc["implementation"],
        "corners": corners,
        "corner_pass": {"t_min_c": corners["t_min_c"]["pass"],
                        "t_max_c": corners["t_max_c"]["pass"]},
    }


def wcd_design_center(
    samples_path: str | Path,
    tolerances: dict[str, float],
    *,
    k_sigma: float = 3.0,
    max_iter: int = 40,
    step_frac: float = 0.25,
    shrink: float = 0.5,
    n_mc: int = 2000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
    r_max_sigma: float = 6.0,
    n_directions: int | None = None,
) -> dict[str, Any]:
    """WCD 设计中心化（DP-18 C8，JSON 契约；只追加，既有函数零改动）。

    目标 = max-WCD（Antreich-Graeb-Wieser σ 归一化空间到可接受域边界
    最短距离；高斯容差下良率随 WCD 单调）——代理点值全程确定性，搜索
    不吃 MC 噪声（区别于 ``yield_design_center`` 的容差盒网格良率目标）。
    外层复用 ``core/pce.design_centering`` 骨架（坐标 pattern search：
    step_frac·span 初始步长、无改进收缩 shrink、步长收敛 1e-9·span），
    搜索域 = 全部 bounds 维度（非公差参数也参与寻优，公差参数张成
    σ 空间）；循环内用粗扫 WCD（refine=False 控成本），收敛后对最终
    中心做 ``pce._pattern_search`` 角向精化全量重估。MC（C3 向量化
    ``_mc_yield``）只做前后认证；Cpk 由 metric_stats 直算
    （``core/wcd.cpk_from_metric_stats``，零新机制）。缺省行为零变化
    （新函数 + 新键）。

    Returns:
        {ok, center, initial_center, wcd, wcd_initial, cpk, cpk_initial,
         yield_mc_before, yield_mc_after, n_mc, seed, ...}；
        wcd = {per_spec, binding_spec, overall, n_evaluations}（另含
        refined 等审计键）；yield_mc_* 为 ``_mc_yield`` 认证 dict
        （剔除内部 ``_draw_columns`` 列后嵌入，JSON 安全）。
    """
    if k_sigma <= 0:
        return {"ok": False, "errors": [f"k_sigma 必须 >0，收到: {k_sigma}"]}
    if n_mc < 1:
        return {"ok": False, "errors": [f"n_mc 必须 ≥1，收到: {n_mc}"]}
    if r_max_sigma <= 0:
        return {"ok": False, "errors": [f"r_max_sigma 必须 >0，收到: {r_max_sigma}"]}
    if not (0.0 < shrink < 1.0):
        return {"ok": False, "errors": [f"shrink 必须在 (0,1)，收到: {shrink}"]}
    if step_frac <= 0:
        return {"ok": False, "errors": [f"step_frac 必须 >0，收到: {step_frac}"]}
    ctx, errors = _load_yield_context(
        samples_path, tolerances, kind=kind, order=order,
        ridge_lambda=ridge_lambda)
    if ctx is None:
        return {"ok": False, "errors": errors}

    import numpy as np

    from rfauto.core.objectives import SpecEvaluator
    from rfauto.core.wcd import cpk_from_metric_stats, wcd_specs

    model = ctx["model"]
    objs = ctx["objs"]
    bounds = ctx["bounds"]

    # 指标键守卫：与 yield_design_center 同款——缺指标时 margin 面不可
    # 评估，必须前置显式报错（缺失键静默跳过会把 WCD 虚高）。
    box_mid = {name: 0.5 * (lo + hi) for name, (lo, hi) in bounds.items()}
    pred_keys = set(_numeric_pred(model, box_mid))
    missing_metrics = [o.metric for o in objs if not any(
        k in pred_keys
        for k in SpecEvaluator.metric_key_candidates(o.metric, o.op))]
    if missing_metrics:
        return {"ok": False,
                "errors": [f"目标指标不在代理预测面: {missing_metrics}"]}

    def pred(point: dict[str, float]) -> dict[str, float]:
        return _numeric_pred(model, point)

    def wcd_at(point: dict[str, float], *, refine: bool) -> dict[str, Any]:
        return wcd_specs(
            point, tolerances, pred, objs, r_max=r_max_sigma,
            n_directions=n_directions, refine=refine)

    names = sorted(bounds)
    lows = np.array([bounds[n][0] for n in names], dtype=float)
    highs = np.array([bounds[n][1] for n in names], dtype=float)
    span = np.maximum(highs - lows, 1e-12)
    position = 0.5 * (lows + highs)

    def score(res: dict[str, Any]) -> tuple[float, float]:
        """(overall 最短腿, 逐规范距离和) 双键：主目标 max-WCD，
        平手时偏好各腿总和更大（确定性 tie-break）。"""
        dists = [float(v["distance"]) for v in res["per_spec"].values()
                 if v.get("ok")]
        return (float(res["overall"] or 0.0), float(sum(dists)))

    initial_res = wcd_at({n: float(v) for n, v in zip(names, position, strict=True)},
                         refine=False)
    best_score = score(initial_res)
    best_position = position.copy()
    initial_center = {n: float(v) for n, v in zip(names, position, strict=True)}
    n_wcd_evals = int(initial_res.get("n_evaluations") or 0)

    step = step_frac * span
    for _ in range(max_iter):
        improved = False
        for j in range(len(names)):
            if step[j] <= 0.0:
                continue
            for delta in (step[j], -step[j]):
                cand = best_position.copy()
                cand[j] = min(highs[j], max(lows[j], cand[j] + delta))
                if cand[j] == best_position[j]:
                    continue
                cand_point = {n: float(v)
                              for n, v in zip(names, cand, strict=True)}
                res = wcd_at(cand_point, refine=False)
                n_wcd_evals += int(res.get("n_evaluations") or 0)
                cand_score = score(res)
                if cand_score[0] > best_score[0] + 1e-12 or (
                    abs(cand_score[0] - best_score[0]) <= 1e-12
                    and cand_score[1] > best_score[1] + 1e-12
                ):
                    best_position = cand
                    best_score = cand_score
                    improved = True
        if not improved:
            step = step * shrink
            if np.all(step <= 1e-9 * span):
                break

    final_center = {n: float(v) for n, v in zip(names, best_position, strict=True)}
    wcd_final = wcd_at(final_center, refine=True)
    wcd_initial = wcd_at(initial_center, refine=True)
    n_wcd_evals += int(wcd_final.get("n_evaluations") or 0)
    n_wcd_evals += int(wcd_initial.get("n_evaluations") or 0)

    mc_initial = _mc_yield(ctx, dict(initial_center), tolerances, n=n_mc, seed=seed)
    mc_final = _mc_yield(ctx, dict(final_center), tolerances, n=n_mc, seed=seed)

    def mc_public(mc: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in mc.items() if k != "_draw_columns"}

    return {
        "ok": True,
        "samples_path": str(ctx["path"]),
        "uncertainty_status": ctx["uncertainty_status"],
        "surrogate_kind": kind,
        "objective": "min_wcd(sigma_normalized_boundary_distance,AGW-TCAD1994)",
        "tolerances": tolerances,
        "k_sigma": float(k_sigma),
        "r_max_sigma": float(r_max_sigma),
        "initial_center": initial_center,
        "center": final_center,
        "wcd": {
            "per_spec": wcd_final["per_spec"],
            "binding_spec": wcd_final["binding_spec"],
            "overall": wcd_final["overall"],
        },
        "wcd_initial": {
            "per_spec": wcd_initial["per_spec"],
            "binding_spec": wcd_initial["binding_spec"],
            "overall": wcd_initial["overall"],
        },
        "cpk": cpk_from_metric_stats(mc_final["metric_stats"], ctx["specs"]),
        "cpk_initial": cpk_from_metric_stats(mc_initial["metric_stats"],
                                             ctx["specs"]),
        "yield_mc_before": mc_public(mc_initial),
        "yield_mc_after": mc_public(mc_final),
        "n_mc": n_mc,
        "seed": seed,
        "n_wcd_evaluations": n_wcd_evals,
        "refined": bool(wcd_final.get("per_spec")
                        and all(v.get("refined") for v in
                                wcd_final["per_spec"].values()
                                if v.get("ok"))),
    }
