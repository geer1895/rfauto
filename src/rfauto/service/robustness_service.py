"""robustness_service：DP-15 C3 稳健性报告（良率/FORM/worst-case/Cpk）。

规格书 docs/plan_deepdive_specs_20260924.md §15.3 第二片，service 层
JSON 进出（分层铁律 #4；数值只在确定性内核 #7——FORM/搜索全部吃代理
确定性求值，本模块无随机决策）：

- ``load_tolerance_profile``：公差配方 profile schema+加载（±tol →
  σ = tol/k_sigma，k_sigma 缺省 3.0，与 optimization/tolerance.py 的
  ``sigma = tol / 3`` 口径一致；``fab`` 挂载点本批只定义 schema+加载
  透传，DP-7 解析接口后续接入）。
- ``form_pf``：FORM 服务面（XD-11 换基：HL-RF 迭代收敛 core.form_beta
  单源内核 ``core/form_reliability.py``，本模块只保留多起点播种/选点与
  JSON 信封；失效面 g(x) = threshold − cost(x)（threshold 缺省 0 = 代理
  加权违约 cost ≥ 0 判失效））；openturns/uqpy 可选库存在则对照、缺失
  回退内核自实现（惰性 import，``form_engine`` 显式标注引擎来源）。
- ``surrogate_worst_case``：代理面上优化违约角点（复用 core/pce 的
  ``_pattern_search`` 内核——多起点=中心+2^d 角点，不重写搜索）。
- ``robustness_report``：输入=数据集/run/samples.json + 规范限 + 公差
  profile；输出 = {yield_mc（向量化 MC，见 uq_service）, form_pf,
  worst_case 角点, 逐规范 Cpk, uncertainty_status（消费 DP-13 R1 已挂
  面）, pf_vs_mc}。CLI/MCP 薄壳后续批次接线。

与 optimization/tolerance.py 的差别：tolerance 每点真机求解（贵）；
本模块全部在代理上（免费），代理可信度由校准 gate/uncertainty_status
背书。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.form_eval import (  # T1 解环：FORM 面叶化（定义体在 form_eval）
    FORM_DEFAULT_FD_EPS as FORM_DEFAULT_FD_EPS,
)
from rfauto.service.form_eval import (
    FORM_DEFAULT_MAX_ITER as FORM_DEFAULT_MAX_ITER,
)
from rfauto.service.form_eval import (
    FORM_DEFAULT_TOL as FORM_DEFAULT_TOL,
)
from rfauto.service.form_eval import (
    _mk_cost_fn,
    form_pf,
)
from rfauto.service.form_eval import (
    _normal_cdf as _normal_cdf,
)

#: 公差半宽 → σ 的换算口径：tol = k_sigma·σ（缺省 3σ = tol，即 #195/
#: tolerance.py 同款"3σ=公差"惯例）。
PROFILE_DEFAULT_K_SIGMA = 3.0
#: profile.params[p].dist 允许值（v1 只有正态；均匀/三角等后续按需加）。
PROFILE_ALLOWED_DISTS = ("normal",)
#: robustness_report 数据集读面的行数上限（本服务面向校准级样本集，
#: 不是 1e6 行 MC 库的检索面——检索走 query_dataset）。
_REPORT_MAX_DATASET_ROWS = 200_000


# ---------------------------------------------------------------------------
# 公差配方 profile schema + 加载
# ---------------------------------------------------------------------------

def load_tolerance_profile(
    profile: dict[str, Any] | str | Path,
) -> dict[str, Any]:
    """公差配方 profile → {param: σ} 换算（纯函数，JSON/YAML 进出）。

    schema（dict 或 YAML/JSON 文件路径）::

        profile: cpw_fab_std          # 名字（可选）
        description: ...              # 可选
        k_sigma: 3.0                  # tol = k_sigma·σ；缺省 3.0（3σ 口径）
        params:                       # 必填非空
          w_mm: {tol: 0.02, unit: mm} # tol=±半宽必填>0；dist 缺省 normal
          gap_mm: {tol: 0.01, dist: normal, nominal: 0.25}  # nominal 可选覆盖
        fab: {...}                    # 可选 fab 剖面挂载点（DP-7 解析接口，
                                      # 本批只加载透传不解释）

    σ = tol / k_sigma（±20µm → σ=20/3 µm）。返回
    {ok, profile, description, k_sigma, sigmas, tolerances, units,
    nominal_overrides, params, fab} 或 {ok: False, errors}。
    """
    if isinstance(profile, (str, Path)):
        path = Path(profile)
        if not path.is_file():
            return error_envelope([f"profile 文件不存在: {path}"])
        text = path.read_text(encoding="utf-8")
        try:
            import yaml

            data = yaml.safe_load(text)
        except Exception as exc:
            return error_envelope([f"profile YAML 解析失败: {exc}"])
        if not isinstance(data, dict):
            return error_envelope(["profile 文件顶层必须是映射"])
        source = str(path)
    elif isinstance(profile, dict):
        data = profile
        source = "dict"
    else:
        return error_envelope(
            [
            f"profile 必须是 dict 或文件路径，收到 {type(profile).__name__}"],
        )

    errors: list[str] = []
    raw_params = data.get("params")
    if not isinstance(raw_params, dict) or not raw_params:
        errors.append("profile.params 必须是非空映射 {param: {tol: ...}}")
        raw_params = {}
    k_sigma = data.get("k_sigma", PROFILE_DEFAULT_K_SIGMA)
    try:
        k_sigma = float(k_sigma)
        if k_sigma <= 0:
            errors.append(f"k_sigma 必须 >0，收到 {k_sigma}")
            k_sigma = PROFILE_DEFAULT_K_SIGMA
    except (TypeError, ValueError):
        errors.append(f"k_sigma 必须是数值，收到 {k_sigma!r}")
        k_sigma = PROFILE_DEFAULT_K_SIGMA

    sigmas: dict[str, float] = {}
    tolerances: dict[str, float] = {}
    units: dict[str, str] = {}
    overrides: dict[str, float] = {}
    detail: dict[str, dict[str, Any]] = {}
    for name, spec in raw_params.items():
        name = str(name)
        if not isinstance(spec, dict):
            errors.append(f"params.{name} 必须是映射（含 tol）")
            continue
        tol = spec.get("tol")
        try:
            tol_f = float(tol)
        except (TypeError, ValueError):
            errors.append(f"params.{name}.tol 必须是数值（±半宽），收到 {tol!r}")
            continue
        if tol_f <= 0:
            errors.append(f"params.{name}.tol 必须 >0，收到 {tol_f}")
            continue
        dist = str(spec.get("dist", "normal"))
        if dist not in PROFILE_ALLOWED_DISTS:
            errors.append(f"params.{name}.dist 只允许 "
                          f"{'/'.join(PROFILE_ALLOWED_DISTS)}，收到 {dist!r}")
            continue
        sigmas[name] = tol_f / k_sigma
        tolerances[name] = tol_f
        if spec.get("unit") is not None:
            units[name] = str(spec["unit"])
        if spec.get("nominal") is not None:
            try:
                overrides[name] = float(spec["nominal"])
            except (TypeError, ValueError):
                errors.append(f"params.{name}.nominal 必须是数值，"
                              f"收到 {spec['nominal']!r}")
                continue
        detail[name] = {"tol": tol_f, "sigma": sigmas[name],
                        "dist": dist, **({"unit": units[name]}
                                         if name in units else {}),
                        **({"nominal": overrides[name]}
                           if name in overrides else {})}
    if errors:
        return error_envelope(errors, source=source)
    fab = data.get("fab")
    return {
        "ok": True,
        "source": source,
        "profile": str(data["profile"]) if data.get("profile") else None,
        "description": str(data.get("description") or ""),
        "k_sigma": k_sigma,
        "sigmas": sigmas,
        "tolerances": tolerances,
        "units": units,
        "nominal_overrides": overrides,
        "params": detail,
        # fab 剖面挂载点：DP-7 解析接口（本批 schema+加载透传，不解释）
        "fab": fab if isinstance(fab, dict) else None,
    }


# ---------------------------------------------------------------------------
# FORM v1 自实现（HL-RF + 数值梯度）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# worst-case 违约角点（复用 core/pce._pattern_search 内核）
# ---------------------------------------------------------------------------

def surrogate_worst_case(
    cost_fn: Any,
    nominal: dict[str, float],
    sigmas: dict[str, float],
    bounds: dict[str, tuple[float, float]],
    *,
    k_sigma: float = 3.0,
    threshold: float = 0.0,
    max_iter: int = 200,
    step_tol: float = 1e-8,
) -> dict[str, Any]:
    """公差盒内代理违约 cost 最大角点（多起点坐标 pattern search）。

    搜索域 = 名义 ±k_sigma·σ ∩ bounds（只动公差参数，其余坐标钉名义）；
    起点集 = 盒中心 + 2^d 角点（d>10 退化为中心+各轴端点，同
    core/pce.worst_case 结构），搜索内核直接复用 ``pce._pattern_search``
    （勿重写——规格书 §15.3 ③）。返回 {ok, params, cost, violated,
    threshold, k_sigma, box, n_evaluations, n_starts}。
    """
    from rfauto.core.pce import _pattern_search

    if k_sigma <= 0:
        return error_envelope([f"k_sigma 必须 >0，收到: {k_sigma}"])
    if max_iter < 1:
        return error_envelope([f"max_iter 必须 ≥1，收到: {max_iter}"])
    names = sorted(sigmas)
    if not names:
        return error_envelope(["sigmas 为空（无公差参数）"])
    missing = [n for n in names if n not in nominal]
    if missing:
        return error_envelope([f"名义点缺少公差参数: {missing}"])
    lo = []
    hi = []
    box: dict[str, list[float]] = {}
    for n in names:
        if n not in bounds:
            return error_envelope([f"公差参数不在搜索空间: {n}"])
        blo, bhi = (float(bounds[n][0]), float(bounds[n][1]))
        base = float(nominal[n])
        b_lo = max(blo, base - float(k_sigma) * float(sigmas[n]))
        b_hi = min(bhi, base + float(k_sigma) * float(sigmas[n]))
        lo.append(b_lo)
        hi.append(b_hi)
        box[n] = [b_lo, b_hi]

    def func(x: Any) -> float:
        pt = {n: float(v) for n, v in zip(names, x, strict=True)}
        return float(cost_fn(pt))

    import numpy as np

    lo_arr = np.asarray(lo, dtype=float)
    hi_arr = np.asarray(hi, dtype=float)
    d = len(names)
    center = [0.5 * (a + b) for a, b in zip(lo, hi, strict=True)]
    if d <= 10:
        starts = [center]
        for i in range(2 ** d):
            corner = [lo[j] if (i >> j) & 1 == 0 else hi[j]
                      for j in range(d)]
            starts.append(corner)
    else:  # 高维退化：中心 + 各轴端点（pce.worst_case 同款）
        starts = [center]
        for j in range(d):
            for bound in (lo[j], hi[j]):
                pt = list(center)
                pt[j] = bound
                starts.append(pt)

    best_x: list[float] | None = None
    best_v = -math.inf
    n_eval = 0
    for start in starts:
        x, value, used = _pattern_search(
            func, start, lo_arr, hi_arr, True, max_iter, step_tol)
        n_eval += used
        if value > best_v:
            best_v = value
            best_x = list(x)
    assert best_x is not None
    params = dict(nominal)
    params.update({n: float(v) for n, v in zip(names, best_x, strict=True)})
    return ok_envelope(
        params=params,
        cost=float(best_v),
        violated=bool(best_v > float(threshold)),
        threshold=float(threshold),
        k_sigma=float(k_sigma),
        box=box,
        n_evaluations=int(n_eval),
        n_starts=len(starts),
        search="pce._pattern_search(multi-start corner+center)",
    )


# ---------------------------------------------------------------------------
# robustness_report（JSON 进出编排面）
# ---------------------------------------------------------------------------


def _dataset_samples(
    name: str, out_dir: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, tuple[float, float]]] | tuple[None, list[str]]:
    """runs/datasets/<name>（query_dataset 读面）→ samples + bounds。"""
    from rfauto.service.dataset_service import query_dataset

    qr = query_dataset(name, limit=_REPORT_MAX_DATASET_ROWS + 1,
                       out_dir=out_dir)
    if not qr.get("ok"):
        return None, list(qr.get("errors") or ["数据集读取失败"])
    rows = list(qr.get("rows") or [])
    # #369 口径：query_dataset 的 n_rows 是 limit 截断后返回行数——超限
    # 判别用 len(rows) > 上限（再查 manifest 全量计数代价高且无必要，
    # 本服务面向校准级样本集）
    if len(rows) > _REPORT_MAX_DATASET_ROWS:
        return None, [f"数据集行数超过本服务上限 {_REPORT_MAX_DATASET_ROWS}"
                      "（MC 库检索请走 query_dataset）"]
    samples: list[dict[str, Any]] = []
    pmin: dict[str, float] = {}
    pmax: dict[str, float] = {}
    flat_mode = bool(rows) and "params_json" not in rows[0]
    for row in rows:
        if flat_mode:
            # 平面向量库（store_mc_draws 形态）：param__*/metric__* 列
            params = {c[len("param__"):]: float(v) for c, v in row.items()
                      if c.startswith("param__") and v is not None}
            metrics = {c[len("metric__"):]: float(v) for c, v in row.items()
                       if c.startswith("metric__") and v is not None}
        else:
            try:
                params = json.loads(row.get("params_json") or "{}")
                metrics = json.loads(row.get("metrics_json") or "{}")
            except (TypeError, ValueError):
                continue
            params = {k: float(v) for k, v in params.items()
                      if isinstance(v, (int, float))}
            metrics = {k: float(v) for k, v in metrics.items()
                       if isinstance(v, (int, float))}
        if not params or not metrics:
            continue
        samples.append({"params": params, "metrics": metrics})
        for k, v in params.items():
            pmin[k] = min(pmin.get(k, math.inf), v)
            pmax[k] = max(pmax.get(k, -math.inf), v)
    bounds: dict[str, tuple[float, float]] = {}
    for k in sorted(pmin):
        lo, hi = pmin[k], pmax[k]
        if hi <= lo:  # 常数参数：±0.5% 或 1e-6 垫开（poly_ridge clip 前提）
            pad = max(abs(lo) * 5e-3, 1e-6)
            lo, hi = lo - pad, hi + pad
        bounds[k] = (lo, hi)
    if not samples:
        return None, ["数据集无可解析的 params/metrics 点"]
    return samples, bounds


def _cpk_for_objectives(
    objs: list[Any], metric_stats: dict[str, Any],
) -> dict[str, Any]:
    """逐规范 Cpk（MC 分布 mean/std；单侧/双侧按 op 分派）。"""
    out: dict[str, Any] = {}
    for i, o in enumerate(objs):
        key = f"{o.metric}#{i}"
        stats = metric_stats.get(key)
        entry: dict[str, Any] = {"op": str(getattr(o.op, "value", o.op))}
        if stats is None:
            out[key] = {**entry, "cpk": None,
                        "note": "MC 统计缺该指标（判 FAIL 面）"}
            continue
        mean = float(stats["mean"])
        std = float(stats["std"])
        entry.update({"mean": mean, "std": std})
        if std <= 0.0:
            out[key] = {**entry, "cpk": None,
                        "note": "MC 分布零离散度（常数面），Cpk 不可辨识"}
            continue
        op = getattr(o.op, "value", o.op)
        if op == "max_below":
            usl = float(o.value)
            out[key] = {**entry, "usl": usl,
                        "cpk": (usl - mean) / (3.0 * std)}
        elif op == "min_above":
            lsl = float(o.value)
            out[key] = {**entry, "lsl": lsl,
                        "cpk": (mean - lsl) / (3.0 * std)}
        elif op == "mean_within" and isinstance(o.value, list) \
                and len(o.value) == 2:
            low, high = float(o.value[0]), float(o.value[1])
            out[key] = {**entry, "lsl": low, "usl": high,
                        "cpk": min((high - mean) / (3.0 * std),
                                   (mean - low) / (3.0 * std))}
        else:
            out[key] = {**entry, "cpk": None,
                        "note": "该 op 无 Cpk 口径（如实不硬算）"}
    return out


def robustness_report(
    source: str | Path,
    specs: list[dict[str, Any]],
    *,
    profile: dict[str, Any] | str | Path | None = None,
    tolerances: dict[str, float] | None = None,
    n_mc: int = 100_000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
    k_sigma: float = 3.0,
    threshold: float = 0.0,
    form_engine: str = "auto",
    persist: bool = False,
    store_name: str | None = None,
    store_out_dir: str | Path = "runs/datasets",
) -> dict[str, Any]:
    """稳健性报告：数据集/run/samples.json + 规范限 + 公差 profile → JSON。

    输入：``source`` = samples.json 路径 | 数据集名（runs/datasets/<name>，
    经 query_dataset 读面）| run id（runs/<rid>/meta.json 存在 → 先
    materialize_dataset(health_gate=False, registry_sync=False) 物化为
    数据集再读）；``specs`` = objectives schema 列表（metric/op/value/
    weight）；公差 = ``profile``（load_tolerance_profile schema，优先）
    或 ``tolerances``（{param: σ} 遗传直传）。

    输出（单 dict）：ok / source / surrogate_kind / uncertainty_status
    （R1 已挂面）/ profile / nominal_params / nominal_metrics /
    yield_mc{yield_rate, n_draws, wall_s, implementation, metric_stats,
    store?} / form{pf, beta, form_engine, converged, ..., method_note} /
    worst_case{params, cost, violated, box} / cpk / pf_vs_mc /
    tolerance_source。CLI/MCP 薄壳后续批次接线（本批不接）。
    """
    from rfauto.service.mc_yield_eval import _mc_yield  # T1 解环：MC 判据叶
    from rfauto.service.uq_service import (
        _load_yield_context,
        build_yield_context,
        store_mc_draws,
    )

    if not isinstance(specs, list) or not specs:
        return error_envelope(["specs 必须是非空列表（objectives schema）"])
    if n_mc < 1:
        return error_envelope([f"n_mc 必须 ≥1，收到: {n_mc}"])

    # 公差解析：profile 优先，tolerances 兜底
    prof_out: dict[str, Any] | None = None
    if profile is not None:
        prof_out = load_tolerance_profile(profile)
        if not prof_out.get("ok"):
            return error_envelope(list(prof_out.get("errors") or []))
        sigmas = dict(prof_out["sigmas"])
        if prof_out.get("k_sigma"):
            k_sigma = float(prof_out["k_sigma"])
        tolerance_source = ("profile:" + (prof_out.get("profile")
                                          or prof_out.get("source", "dict")))
    elif isinstance(tolerances, dict) and tolerances:
        sigmas = {k: float(v) for k, v in tolerances.items()}
        tolerance_source = "tolerances_arg"
    else:
        return error_envelope(["缺少公差：给 profile（推荐）或 tolerances"])

    # 来源解析：samples.json | 数据集名 | 数据集目录 | run id
    src_path = Path(source)
    dataset_used: str | None = None
    if src_path.is_file():
        ctx, errs = _load_yield_context(
            src_path, sigmas, kind=kind, order=order,
            ridge_lambda=ridge_lambda)
        if ctx is None:
            return error_envelope(list(errs or []))
        resolved = str(src_path)
    else:
        from rfauto.service.dataset_service import materialize_dataset

        ds_out = Path(store_out_dir)
        ds_name: str | None = None
        if (ds_out / str(source)).is_dir():
            ds_name, ds_out = str(source), ds_out
        elif src_path.is_dir():
            ds_name, ds_out = src_path.name, src_path.parent
        else:
            run_meta = Path("runs") / str(source) / "meta.json"
            if run_meta.is_file():
                mat_name = f"robustness_src_{src_path.name}"
                mat = materialize_dataset(
                    [str(source)], name=mat_name, out_dir=ds_out,
                    health_gate=False, registry_sync=False)
                if not mat.get("ok"):
                    return error_envelope(
                        [
                        f"run 物化失败: {mat.get('errors')}"],
                    )
                ds_name, ds_out = mat_name, ds_out
            else:
                return error_envelope(
                    [
                    "来源不可解析（非 samples.json 文件/数据集/run id）: "
                    f"{source}"],
                )
        samples, bounds_or_errs = _dataset_samples(ds_name, ds_out)
        if samples is None:
            return error_envelope(list(bounds_or_errs))
        ctx, errs = build_yield_context(
            samples, bounds_or_errs, specs, sigmas, kind=kind, order=order,
            ridge_lambda=ridge_lambda)
        if ctx is None:
            return error_envelope(list(errs or []))
        dataset_used = ds_name
        resolved = str(ds_out / ds_name)

    if not sigmas:
        return error_envelope(["公差解析结果为空"])

    # 名义点：样本集 cost 最小点（确定性）+ profile nominal 覆盖（界内校验）
    nominal = {k: float(v)
               for k, v in ctx["nominal_sample"]["params"].items()}
    if prof_out and prof_out.get("nominal_overrides"):
        bad = [k for k, v in prof_out["nominal_overrides"].items()
               if k not in ctx["bounds"]
               or not (ctx["bounds"][k][0] <= v <= ctx["bounds"][k][1])]
        if bad:
            return error_envelope(
                [
                f"profile nominal 覆盖越界/未知参数: {bad}"],
            )
        nominal.update(prof_out["nominal_overrides"])

    # ① 向量化 MC 良率
    mc = _mc_yield(ctx, nominal, sigmas, n=int(n_mc), seed=int(seed))
    report: dict[str, Any] = ok_envelope(
        source=resolved,
        dataset=dataset_used,
        surrogate_kind=kind,
        uncertainty_status=ctx["uncertainty_status"],
        profile={k: v for k, v in (prof_out or {}).items()
                    if k in ("profile", "description", "k_sigma", "params",
                             "fab", "source")},
        tolerance_source=tolerance_source,
        sigmas=sigmas,
        n_mc=int(n_mc),
        seed=int(seed),
        nominal_params=nominal,
        nominal_metrics=mc["nominal_metrics"],
        yield_mc={
            "yield_rate": mc["yield_rate"],
            "n_draws": int(n_mc),
            "implementation": mc["implementation"],
            "wall_s": mc["wall_s"],
            "metric_stats": mc["metric_stats"],
        },
    )
    if persist:
        sname = store_name or f"mc_{Path(resolved).stem}_{int(n_mc)}"
        store = store_mc_draws(
            sname, mc, objs=ctx["objs"], out_dir=store_out_dir,
            seed=int(seed), source_dataset=dataset_used)
        if store.get("ok"):
            # #369 口径提示：全量计数以 manifest n_rows 为准
            report["yield_mc"]["store"] = {
                "dataset": store["name"],
                "n_rows": store["n_rows"],
                "note": "全量计数以 manifest n_rows 为准"
                        "（query_dataset 返回 n_rows 是 limit 截断语义）",
            }
        else:
            report["yield_mc"]["store_error"] = list(
                store.get("errors") or ["MC 落盘失败"])

    # ② FORM（失效面 = 代理违约 cost ≥ threshold）
    cost_fn = _mk_cost_fn(ctx["model"], ctx["objs"])
    form = form_pf(cost_fn, nominal, sigmas, threshold=threshold,
                   form_engine=form_engine)
    report["form"] = form

    # ③ worst-case 违约角点
    worst = surrogate_worst_case(cost_fn, nominal, sigmas, ctx["bounds"],
                                 k_sigma=k_sigma, threshold=threshold)
    report["worst_case"] = worst

    # ④ 逐规范 Cpk（MC 分布口径）
    stats_by_key = {f"{o.metric}#{i}": mc["metric_stats"].get(s["metric"])
                    for i, (o, s) in enumerate(zip(ctx["objs"],
                                                   ctx["specs"],
                                                   strict=True))}
    report["cpk"] = _cpk_for_objectives(
        ctx["objs"], {k: v for k, v in stats_by_key.items() if v})

    # ⑤ FORM vs MC 交叉口径（threshold=0 且无 bandwidth 类目标时同事件）
    supported = all(
        str(getattr(o.op, "value", o.op)) in
        ("max_below", "min_above", "mean_within") for o in ctx["objs"])
    if supported and threshold == 0.0:
        mc_pf = 1.0 - float(mc["yield_rate"])
        pf = float(form["pf"])
        report["pf_vs_mc"] = {
            "mc_pf": mc_pf,
            "mc_n": int(n_mc),
            "rel_diff": abs(pf - mc_pf) / max(abs(mc_pf), 1e-12),
            "note": "同事件口径（cost>0 ⇔ 违约）；MC 采样标准差 ~√(p(1-p)/n)"
                    "（1e4→~0.5%@p=0.5）——差值含 FORM 线性化误差",
        }
    else:
        report["pf_vs_mc"] = {
            "mc_pf": None, "rel_diff": None,
            "note": "事件口径不同（bandwidth 类目标/非零 threshold），"
                    "不做同事件对照（如实不硬比）",
        }
    return report
