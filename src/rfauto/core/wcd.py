"""DP-18 C8：WCD 最坏情况距离 + 逐规范 Cpk（纯函数零 IO）。

WCD（Worst-Case Distance）口径 = Antreich–Graeb–Wieser（TCAD 1994）：
σ 归一化空间 u = (x − c)/σ（原点 = 名义点）中，原点到可接受域
A = {u: ∀j g_j(u) ≥ 0} 边界的最短距离。高斯容差下良率随 WCD 单调，
因此设计中心化目标可取 max-WCD（确定性代理面，无 MC 噪声）。

g_j = SpecEvaluator 铰链的 margin 镜像（与 uq_service._violates /
_vector_spec_cost 同一判据式，pass ⇔ g ≥ 0、violate ⇔ g < 0）：

- max_below:  g = value − v
- min_above:  g = v − value
- mean_within: g = min(v − low, high − v)
- bandwidth:  g = v − value（带宽 ≥ 阈值）

逐规范边界距离算法（规格书 §18.1）：
1. 角向粗扫：确定性方向集（±e_i 坐标轴 + fixed-seed 单位向量，2D 为
   均匀角度栅格）；
2. 每方向径向均匀扫描找**首个** g_j 符号穿越，区间内二分逼近 g_j = 0；
3. 对最优方向的角度邻域复用 ``core.pce._pattern_search`` 精化（目标 =
   穿越半径最小化，无穿越方向罚 r_max 上限）。

符号约定：名义在可接受域内（g_j(0) ≥ 0）→ WCD_j = +r；名义已违约
（g_j(0) < 0）→ WCD_j = −r（|r| = 到可接受域距离，负号 = 已违约）；
r_max 内无穿越 → 距离封顶 ±r_max 且 censored=true（如实标记截断，
不冒充精确值）。overall = min_j WCD_j（最短腿）；binding_spec = argmin。

Cpk 零新机制：直接由 _mc_yield 已产 metric_stats（mean/std）算
min((USL − μ)/3σ, (μ − LSL)/3σ)。robustness_service._cpk_for_objectives
已存在（键 ``metric#i``）；本模块 ``cpk_from_metric_stats`` 以 specs
schema（metric/op/spec）进、metric 名出，供 uq_service/wcd 共用——
不反向 import robustness_service（其函数体内 import uq_service，反向
成环）；bandwidth op 按 LSL 口径计（_cpk_for_objectives 对 bandwidth
返回 None，本实现为其超集，docstring 如实分叉声明）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from rfauto.core.objectives import MetricOp, SpecEvaluator

__all__ = [
    "boundary_distance",
    "cpk_from_metric_stats",
    "spec_margin",
    "wcd_specs",
]


# ---------------------------------------------------------------------------
# margin（SpecEvaluator 铰链镜像）
# ---------------------------------------------------------------------------


def spec_margin(op: Any, value: Any, v: float) -> float:
    """单规范 margin：pass ⇔ g ≥ 0，violate ⇔ g < 0。

    镜像对象 = ``uq_service._vector_spec_cost``（四种 op 全处理的权威
    判定式，MC cost 列与 FORM 失效面同源）：hinge = max(0, −g)。
    注意既有逐点 ``_violates``/``_violate_mask`` **不含 bandwidth 分支**
    （恒 False）——本函数对 bandwidth 按 ``v ≥ value`` 判（与
    _vector_spec_cost 的 ``max(0, thr−v)`` 铰链一致），系其超集。

    op 接受 MetricOp 或其字符串值；mean_within 的 value 为 [low, high]。
    未知 op 返回 NaN（调用方按违约面保守处理并如实标注）。

    Examples
    --------
    用法示例（pass ⇔ margin ≥ 0，violate ⇔ margin < 0）：

    >>> from rfauto.core.wcd import spec_margin
    >>> spec_margin("max_below", -15.0, -18.0)   # S11 ≤ −15dB，实测 −18 → pass
    3.0
    >>> spec_margin("max_below", -15.0, -12.5)   # 实测 −12.5 → violate
    -2.5
    >>> spec_margin("min_above", 0.5, 0.75)      # 增益 ≥ 0.5dB
    0.25
    >>> spec_margin("mean_within", [0.0, 2.0], 2.5)  # 越上界 0.5
    -0.5
    >>> round(spec_margin("bandwidth", 1.0, 0.8), 12)  # 带宽 ≥ 1GHz，实测 0.8
    -0.2
    """
    if op in (MetricOp.MAX_BELOW, "max_below"):
        return float(value) - float(v)
    if op in (MetricOp.MIN_ABOVE, "min_above"):
        return float(v) - float(value)
    if op in (MetricOp.MEAN_WITHIN, "mean_within") and isinstance(
        value, (list, tuple)
    ) and len(value) == 2:
        return min(float(v) - float(value[0]), float(value[1]) - float(v))
    if op in (MetricOp.BANDWIDTH, "bandwidth"):
        return float(v) - float(value)
    return float("nan")


def _is_violated(g_val: float) -> bool:
    """violate 判定（NaN/非有限 = 退化面，保守记违约侧）。"""
    return (not math.isfinite(g_val)) or g_val < 0.0


# ---------------------------------------------------------------------------
# 径向穿越 + 角向精化
# ---------------------------------------------------------------------------


def _first_crossing_radius(
    g: Callable[[Any], float],
    direction: np.ndarray,
    *,
    inside: bool,
    r_max: float,
    n_scan: int,
    bisect_iter: int,
    bisect_tol: float,
) -> tuple[float | None, int]:
    """沿射线方向找首个 g 符号穿越半径（扫描定段 + 二分逼近 g=0）。

    inside=True（名义在域内）找首次进入违约侧（g<0）；inside=False 找
    首次进入可接受域（g≥0）。返回 (radius | None, n_eval)；None = 到
    r_max 无穿越。
    """
    n_eval = 0
    prev_r = 0.0
    for k in range(1, n_scan + 1):
        r = r_max * k / n_scan
        val = float(g(r * direction))
        n_eval += 1
        here = _is_violated(val)
        crossed = here if inside else not here
        if crossed:
            lo, hi = prev_r, r
            for _ in range(bisect_iter):
                if hi - lo <= bisect_tol:
                    break
                mid = 0.5 * (lo + hi)
                v_mid = float(g(mid * direction))
                n_eval += 1
                q = _is_violated(v_mid) if inside else not _is_violated(v_mid)
                if q:
                    hi = mid
                else:
                    lo = mid
            return 0.5 * (lo + hi), n_eval
        prev_r = r
    return None, n_eval


def _angles_to_dir(angles: np.ndarray) -> np.ndarray:
    """(d−1) 个球角 → 单位方向（末角为方位角 ∈ [−π,π]，其余极角截到 [0,π]）。"""
    d = angles.size + 1
    u = np.empty(d, dtype=float)
    running = 1.0
    for m in range(d - 1):
        th = float(angles[m])
        if m < d - 2:
            th = min(max(th, 0.0), math.pi)
        u[m] = running * math.cos(th)
        running *= math.sin(th)
    u[d - 1] = running
    norm = float(np.linalg.norm(u))
    if norm <= 0.0:
        out = np.zeros(d, dtype=float)
        out[0] = 1.0
        return out
    return u / norm


def _dir_to_angles(u: np.ndarray) -> np.ndarray:
    """单位方向 → (d−1) 个球角（_angles_to_dir 的逆）。"""
    u = np.asarray(u, dtype=float)
    d = u.size
    angles = np.empty(d - 1, dtype=float)
    if d == 2:
        angles[0] = math.atan2(float(u[1]), float(u[0]))
        return angles
    angles[0] = math.acos(min(1.0, max(-1.0, float(u[0]))))
    for m in range(1, d - 2):
        tail = float(np.linalg.norm(u[m + 1:]))
        angles[m] = math.atan2(tail, float(u[m]))
    angles[d - 2] = math.atan2(float(u[d - 1]), float(u[d - 2]))
    return angles


def _coarse_directions(dim: int, n_directions: int, rng_seed: int) -> list[np.ndarray]:
    """确定性粗扫方向集：2D 均匀角度栅格；≥3D 坐标轴 ±e_i + fixed-seed 单位向量。"""
    if dim == 1:
        return [np.array([1.0]), np.array([-1.0])]
    if dim == 2:
        step = 2.0 * math.pi / n_directions
        return [np.array([math.cos(step * k), math.sin(step * k)]) for k in range(n_directions)]
    dirs: list[np.ndarray] = []
    for j in range(dim):
        for bound in (1.0, -1.0):
            e = np.zeros(dim, dtype=float)
            e[j] = bound
            dirs.append(e)
    rng = np.random.default_rng(rng_seed)
    extra = max(4, n_directions - 2 * dim)
    raw = rng.standard_normal((extra, dim))
    norms = np.linalg.norm(raw, axis=1)
    for row, n in zip(raw, norms, strict=True):
        if n > 0.0:
            dirs.append(row / n)
    return dirs


def boundary_distance(
    g: Callable[[Any], float],
    *,
    dim: int,
    r_max: float = 6.0,
    n_directions: int | None = None,
    n_scan: int = 12,
    bisect_iter: int = 60,
    refine: bool = True,
    refine_max_iter: int = 60,
    refine_step_tol: float = 1e-10,
    rng_seed: int = 0,
) -> dict[str, Any]:
    """σ 归一化空间原点到 {g = 0} 边界的最短距离（WCD 内核，纯函数）。

    Args:
        g: callable(u: (dim,) ndarray) -> float，margin（pass ⇔ ≥0）；
            原点 = 名义点。非有限返回值按违约侧保守处理。
        dim: σ 空间维数。
        r_max: 径向搜索半径上限（σ 单位；无穿越时距离按 ±r_max 截断）。
        n_directions: 粗扫方向数（缺省 max(16, 6·dim)；1D 固定 ±1）。
        n_scan: 每方向径向扫描段数（定位首个穿越段）。
        bisect_iter: 二分迭代上限（配合 bisect_tol 收敛到机器精度量级）。
        refine: 是否对最优方向做 ``pce._pattern_search`` 角向精化。
        refine_max_iter / refine_step_tol: 精化 pattern search 参数。
        rng_seed: ≥3D 粗扫随机方向固定种子（确定性）。

    Returns:
        {ok, distance, point_u, direction, radius, inside, g0, censored,
         refined, n_eval, dim, r_max}；distance = +radius（域内）或
         −radius（名义违约）；censored=True 时 point_u 为 None。

    Examples
    --------
    一维线性 margin（违约面在 u0=2，σ 归一化空间距离解析值 = 2.0）：

    >>> from rfauto.core.wcd import boundary_distance
    >>> g = lambda u: 2.0 - float(u[0])   # 违约面在 u0 = 2
    >>> r = boundary_distance(g, dim=1, r_max=6.0)
    >>> round(r["distance"], 9), r["inside"], r["censored"]
    (2.0, True, False)
    """
    from rfauto.core.pce import _pattern_search

    if dim < 1:
        return {"ok": False, "errors": [f"dim 必须 ≥1，收到: {dim}"]}
    if r_max <= 0.0:
        return {"ok": False, "errors": [f"r_max 必须 >0，收到: {r_max}"]}
    if n_scan < 2:
        return {"ok": False, "errors": [f"n_scan 必须 ≥2，收到: {n_scan}"]}
    n_dirs = int(n_directions) if n_directions is not None else max(16, 6 * dim)
    if n_dirs < 4:
        return {"ok": False, "errors": [f"n_directions 必须 ≥4，收到: {n_dirs}"]}

    origin = np.zeros(dim, dtype=float)
    g0 = float(g(origin))
    if not math.isfinite(g0):
        return {"ok": False, "errors": ["g(原点) 非有限，边界距离无定义"]}
    inside = g0 >= 0.0
    bisect_tol = 1e-12 * max(1.0, r_max)

    n_eval = 0
    best_r: float | None = None
    best_dir: np.ndarray | None = None
    for direction in _coarse_directions(dim, n_dirs, rng_seed):
        r, used = _first_crossing_radius(
            g, direction, inside=inside, r_max=r_max,
            n_scan=n_scan, bisect_iter=bisect_iter, bisect_tol=bisect_tol)
        n_eval += used
        if r is not None and (best_r is None or r < best_r):
            best_r = r
            best_dir = direction

    refined = False
    if best_r is None:
        # 全方向无穿越：距离按 r_max 截断（censored，如实标记）
        distance = r_max if inside else -r_max
        return {
            "ok": True, "distance": float(distance), "point_u": None,
            "direction": None, "radius": None, "inside": inside,
            "g0": g0, "censored": True, "refined": False,
            "n_eval": n_eval, "dim": dim, "r_max": r_max,
        }

    if refine and dim >= 2:
        assert best_dir is not None
        angles0 = _dir_to_angles(best_dir)
        # 精化邻域角宽 = 粗扫角距量级（2D 均匀栅格角距；≥3D 方向集不均匀，
        # 按方向数开方尺度取 π/(4√N)）
        delta = (2.0 * math.pi / n_dirs if dim == 2
                 else math.pi / (4.0 * math.sqrt(n_dirs)))
        lo = angles0 - delta
        hi = angles0 + delta
        # 球角定义域裁剪（末角方位角 ∈ [−π,π] 不裁；极角 ∈ [0,π]）
        for m in range(dim - 2):
            lo[m] = max(0.0, lo[m])
            hi[m] = min(math.pi, hi[m])

        def refine_func(angles: np.ndarray) -> float:
            r, used = _first_crossing_radius(
                g, _angles_to_dir(angles), inside=inside, r_max=r_max,
                n_scan=n_scan, bisect_iter=bisect_iter, bisect_tol=bisect_tol)
            nonlocal n_eval
            n_eval += used
            return r if r is not None else r_max  # 无穿越方向罚上限

        x_ref, v_ref, used = _pattern_search(
            refine_func, angles0, lo, hi, False, refine_max_iter,
            refine_step_tol)
        n_eval += used
        if v_ref < best_r:
            best_r = float(v_ref)
            best_dir = _angles_to_dir(x_ref)
            refined = True

    assert best_dir is not None and best_r is not None
    point_u = best_dir * best_r
    return {
        "ok": True,
        "distance": float(best_r if inside else -best_r),
        "point_u": [float(v) for v in point_u],
        "direction": [float(v) for v in best_dir],
        "radius": float(best_r),
        "inside": inside,
        "g0": g0,
        "censored": False,
        "refined": refined,
        "n_eval": n_eval,
        "dim": dim,
        "r_max": r_max,
    }


# ---------------------------------------------------------------------------
# WCD 编排（逐规范 + overall + binding_spec）
# ---------------------------------------------------------------------------


def _objective_triple(obj: Any) -> tuple[str, Any, Any, float] | None:
    """Objective 对象 / mapping → (metric, op, value, weight)；不可解析返回 None。"""
    if hasattr(obj, "metric"):
        metric = str(obj.metric)
        op = getattr(obj, "op", None)
        value = getattr(obj, "value", None)
        weight = float(getattr(obj, "weight", 1.0))
        return metric, op, value, weight
    if isinstance(obj, Mapping):
        metric = obj.get("metric")
        if metric is None:
            return None
        op = obj.get("op", "max_below")
        value = obj.get("value", obj.get("spec"))
        weight = float(obj.get("weight", 1.0))
        return str(metric), op, value, weight
    return None


def wcd_specs(
    center: Mapping[str, float],
    sigmas: Mapping[str, float],
    predict: Callable[[dict[str, float]], dict[str, float]],
    objectives: Sequence[Any],
    *,
    r_max: float = 6.0,
    n_directions: int | None = None,
    n_scan: int = 12,
    bisect_iter: int = 60,
    refine: bool = True,
    refine_max_iter: int = 60,
    refine_step_tol: float = 1e-10,
    rng_seed: int = 0,
) -> dict[str, Any]:
    """逐规范 WCD 编排（WCD 口径 = 最短腿 + binding_spec）。

    Args:
        center: 名义点（全参数 dict；非公差参数钉在 center）。
        sigmas: {param: σ}（σ 归一化空间的坐标缩放，须为正）。
        predict: callable(params_dict) -> {metric_key: value}（代理面）。
        objectives: Objective 对象或 {metric, op, value} mapping 列表。
        其余参数透传 ``boundary_distance``。

    Returns:
        {ok, per_spec: {metric_key: entry}, overall, binding_spec,
         n_evaluations}；entry 含 {distance, metric, resolved_key, op,
         value, weight, inside, censored, refined, point_x, point_u,
         g0, n_eval}。per_spec 键 = DEFAULT_METRIC_KEY 映射后的规范键
         （与 uq_service ctx["specs"]/metric_stats 同口径）。
    """
    from rfauto.core.objectives import DEFAULT_METRIC_KEY

    names = sorted(sigmas)
    if not names:
        return {"ok": False, "errors": ["sigmas 为空（σ 归一化空间至少 1 维）"]}
    sig_vals = [float(sigmas[n]) for n in names]
    bad = [n for n, s in zip(names, sig_vals, strict=True) if not (s > 0.0)
           or not math.isfinite(s)]
    if bad:
        return {"ok": False, "errors": [f"σ 必须为正有限: {bad}"]}
    missing = [n for n in names if n not in center]
    if missing:
        return {"ok": False, "errors": [f"center 缺少公差参数: {missing}"]}
    base_vals = [float(center[n]) for n in names]
    dim = len(names)

    def make_g(op: Any, value: Any, resolved: str) -> Callable[[Any], float]:
        def g(u: Any) -> float:
            x = {k: float(v) for k, v in center.items()}
            for j, nm in enumerate(names):
                x[nm] = base_vals[j] + float(u[j]) * sig_vals[j]
            pred = predict(x)
            if resolved not in pred:
                return float("nan")
            return spec_margin(op, value, float(pred[resolved]))
        return g

    try:
        pred_keys = set(dict(predict({k: float(v) for k, v in center.items()})).keys())
    except Exception:
        pred_keys = set()

    per_spec: dict[str, Any] = {}
    n_eval_total = 0
    for idx, obj in enumerate(objectives):
        triple = _objective_triple(obj)
        if triple is None:
            per_spec[f"unresolved#{idx}"] = {
                "ok": False, "note": "objective 不可解析（缺 metric）"}
            continue
        metric, op, value, weight = triple
        # per_spec 键与 uq_service ctx["specs"]/metric_stats 同口径
        mapped = DEFAULT_METRIC_KEY.get(metric, metric)
        key = mapped if mapped not in per_spec else f"{mapped}#{idx}"
        resolved = next(
            (k for k in SpecEvaluator.metric_key_candidates(metric, op)
             if k in pred_keys), None)
        entry: dict[str, Any] = {
            "metric": metric, "op": str(getattr(op, "value", op)),
            "value": value, "weight": weight,
        }
        if resolved is None:
            entry["ok"] = False
            entry["note"] = "代理预测面缺该指标键，WCD 不可评估（如实不硬算）"
            per_spec[key] = entry
            continue
        entry["resolved_key"] = resolved
        res = boundary_distance(
            make_g(op, value, resolved), dim=dim, r_max=r_max,
            n_directions=n_directions, n_scan=n_scan,
            bisect_iter=bisect_iter, refine=refine,
            refine_max_iter=refine_max_iter,
            refine_step_tol=refine_step_tol, rng_seed=rng_seed)
        if not res.get("ok"):
            entry["ok"] = False
            entry["note"] = "; ".join(str(e) for e in res.get("errors", []))
            per_spec[key] = entry
            continue
        point_u = res["point_u"]
        point_x = None
        if point_u is not None:
            point_x = {k: float(v) for k, v in center.items()}
            for j, nm in enumerate(names):
                point_x[nm] = base_vals[j] + float(point_u[j]) * sig_vals[j]
        entry.update({
            "ok": True,
            "distance": res["distance"],
            "inside": res["inside"],
            "censored": res["censored"],
            "refined": res["refined"],
            "g0": res["g0"],
            "point_u": point_u,
            "point_x": point_x,
            "n_eval": res["n_eval"],
        })
        n_eval_total += int(res["n_eval"])
        per_spec[key] = entry

    all_ok = bool(per_spec) and all(bool(v.get("ok")) for v in per_spec.values())
    errors = [str(v.get("note")) for v in per_spec.values() if not v.get("ok")]
    finite = {k: float(v["distance"]) for k, v in per_spec.items()
              if v.get("ok") and math.isfinite(float(v["distance"]))}
    binding = min(finite, key=lambda k: finite[k]) if finite else None
    return {
        "ok": all_ok,
        "errors": errors or None,
        "per_spec": per_spec,
        "overall": finite[binding] if binding is not None else None,
        "binding_spec": binding,
        "n_evaluations": n_eval_total,
        "dim": dim,
        "r_max": r_max,
    }


# ---------------------------------------------------------------------------
# Cpk（metric_stats → 逐规范 Cpk + min，零新机制）
# ---------------------------------------------------------------------------


def cpk_from_metric_stats(
    metric_stats: Mapping[str, Mapping[str, float]],
    specs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """逐规范 Cpk = min((USL−μ)/3σ, (μ−LSL)/3σ) + 全规范 min（纯函数）。

    Args:
        metric_stats: {metric_key: {mean, std, ...}}（_mc_yield 已产）。
        specs: [{metric, op, spec|value}]（uq_service ctx["specs"] 同构；
            op 接受 MetricOp 或字符串）。

    Returns:
        {per_spec: {metric_key: {cpk, mean?, std?, lsl?, usl?, op, note?}},
         min: float | None}。零离散度/缺指标 → cpk=None + note（不硬算）。
        bandwidth op 按 LSL 口径计（robustness_service._cpk_for_objectives
        对 bandwidth 返回 None——本实现为其超集，分叉如实声明）。
        键名规则：首个同名规范用裸 metric 键，重复出现加 ``#序号`` 后缀。

    Examples
    --------
    S11 ≤ −10dB 规范、MC 统计 μ=−15dB/σ=1dB → Cpk=(USL−μ)/3σ=5/3（手算
    闭式，与 tests/unit/test_wcd.py 独立手算钉同口径）：

    >>> from rfauto.core.wcd import cpk_from_metric_stats
    >>> stats = {"s11_db": {"mean": -15.0, "std": 1.0}}
    >>> specs = [{"metric": "s11_db", "op": "max_below", "spec": -10.0}]
    >>> out = cpk_from_metric_stats(stats, specs)
    >>> round(out["per_spec"]["s11_db"]["cpk"], 12)
    1.666666666667
    >>> out["min"] == out["per_spec"]["s11_db"]["cpk"]
    True
    """
    per_spec: dict[str, Any] = {}
    values: list[float] = []
    used_names: set[str] = set()
    for i, spec in enumerate(specs):
        metric = str(spec.get("metric", ""))
        op = spec.get("op", "max_below")
        op_v = str(getattr(op, "value", op))
        raw = spec.get("spec", spec.get("value"))
        key = metric if metric not in used_names else f"{metric}#{i}"
        used_names.add(metric)
        entry: dict[str, Any] = {"op": op_v}
        stats = metric_stats.get(metric)
        if stats is None:
            entry["cpk"] = None
            entry["note"] = "metric_stats 缺该指标（判 FAIL 面）"
        else:
            mean = float(stats["mean"])
            std = float(stats["std"])
            entry["mean"] = mean
            entry["std"] = std
            if not (std > 0.0):
                entry["cpk"] = None
                entry["note"] = "MC 分布零离散度（常数面），Cpk 不可辨识"
            elif op_v == "max_below":
                usl = float(raw)
                entry["usl"] = usl
                entry["cpk"] = (usl - mean) / (3.0 * std)
            elif op_v in ("min_above", "bandwidth"):
                lsl = float(raw)
                entry["lsl"] = lsl
                entry["cpk"] = (mean - lsl) / (3.0 * std)
            elif op_v == "mean_within" and isinstance(raw, (list, tuple)) and len(raw) == 2:
                low = float(raw[0])
                high = float(raw[1])
                entry["lsl"] = low
                entry["usl"] = high
                entry["cpk"] = min((high - mean) / (3.0 * std),
                                   (mean - low) / (3.0 * std))
            else:
                entry["cpk"] = None
                entry["note"] = "该 op 无 Cpk 口径（如实不硬算）"
        cpk = entry.get("cpk")
        if isinstance(cpk, float) and math.isfinite(cpk):
            values.append(cpk)
        per_spec[key] = entry
    return {"per_spec": per_spec, "min": min(values) if values else None}
