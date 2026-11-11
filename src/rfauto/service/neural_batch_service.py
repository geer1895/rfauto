"""神经代理批量优化编排（aurora_r R-28 / C2 前半 service 面）。

语境
----
Alpha-RF（arXiv:2603.00104；runs/aurora_q/qx40_vbridge/AUTHOR_SURVEY.md
B1/C2 行）第一层批量消费的编排壳：**LHS 候选生成 → 神经代理批量前向 →
逐候选按目标规格命中度打分 → top-k 报告（含最优候选全响应 + 逐目标
命中明细）**。只做"批量评估取最优"这一半，不训 RL 策略、不做搜索器
（C2 后半挂账）。模型 = core.neural_surrogate fit 信封（R-05）——dict
直传或 JSON 模型文件路径皆可（state 为纯 list 权重，可跨进程 JSON 携带）。

判据口径（em_bench inverse_design 只读复用，#122 预声明）
--------------------------------------------------------
目标规格 schema 与命中判据同 service/em_bench_analog_service 的
inverse_design runner 口径（本席只读复用、不 import 其私有件、零改动）：
``targets = {target_id: {f0_ghz>0, dip_db, tol_freq_rel>=0, tol_dip_db>=0}}``；
命中 = ``freq_dev_rel ≤ tol_freq_rel ∧ dip_dev_db ≤ tol_dip_db``（恰等
合格，≥/≤ 边界语义同源）。响应标量测度由预测曲线确定性提取
（:func:`curve_measures`）：dB 曲线幅度地板 1e-12（|S|→0 深谷发散防线，
#195 族）、谷深=曲线最小 dB（显式 min 口径）、f0=argmin 频点——
纹波多谷器件的 argmin 峰位歧义是已知边界（#298 族），本打分器为通用
确定性口径，逐目标明细如实携带测度。排序分数 = 命中数 − 封顶超差罚项
和/(T+1)（罚项=min(两轴 dev/tol 比值超 1 部分, 1)，除以 (T+1) 使**命中
数严格占优**；tol=0 合法预声明，分母钳 1e-12 数值地板后由封顶接管——
恰等命中不受影响，miss 罚项有界确定性）。

候选域（bounds 缺省派生口径）
----------------------------
显式 ``bounds`` 缺省时从 fit 信封 ``norm_x``（minmax 窗）派生：
非退化维（|scale| ≥ 1e-12，与 neural_surrogate._SCALE_EPS 同阈值）=
``(center, center+scale)`` 训练数据观测窗；退化维（常数列）不出 LHS、
以 center 定值注入每候选。LHS 复用 optimization.sample_design.lhs_points
（scipy qmc，seed 确定性；懒 import——active_learning_loop 同先例）。

上限棘轮
--------
``n_candidates`` 显式上限 :data:`NEURAL_BATCH_MAX_CANDIDATES`（缺省
100000，**只收不放**：超限 error 信封点名上限，不静默截断）。预算/耗时
best-effort 落报告（elapsed_s + 各计数，#105：观测失败不阻塞主路径——
耗时测量本身单调钟零失败面）。

信封契约（规则 4，AU-2 单源）：入口 ok/error envelope（service.envelope
构造器）；core.batch_evaluate 的 not-ok 信封（unavailable/前置校验）原样
透传。无 CLI/MCP 叶（挂账处方：后续可挂 ``rfauto neural-opt`` 薄壳——
编排逻辑已在本模块，CLI 只透传参数，勿再复制实现）。模块**不带
__all__**：public_api 金快照（tests/gold）本席禁改，公开面按申报制登记
于本 docstring + 席位报告——parse_inverse_targets / curve_measures /
score_against_targets / make_target_score_fn / optimize_with_neural_surrogate /
NEURAL_BATCH_MAX_CANDIDATES。
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.neural_batch import batch_evaluate
from rfauto.core.neural_surrogate import NormalizationSpec
from rfauto.service.envelope import error_envelope, ok_envelope

#: n_candidates 显式上限（棘轮：超限显式拒绝，上限值只收不放）。
NEURAL_BATCH_MAX_CANDIDATES = 100000

#: 退化维判据（与 core.neural_surrogate._SCALE_EPS 同阈值口径）。
_DEGENERATE_SCALE_EPS = 1e-12

#: |S|→0 深谷 dB 地板（20·log10(1e-12) = -240 dB；#195 族发散防线）。
_AMPLITUDE_FLOOR = 1e-12

#: tol=0 合法预声明时的分母数值地板（比值有限化，封顶罚项接管排序语义）。
_TOL_FLOOR = 1e-12


# ─── 目标规格解析（fail-closed，em_bench _inverse_targets 判据同口径） ─────


def _finite_number(v: Any) -> float | None:
    """有限数值提取（bool 除外；None=非法——em_bench 同口径）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def parse_inverse_targets(spec: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """目标规格读取（预声明 schema，任务定义错误 ValueError fail-closed）。

    ``spec.targets = {target_id: {f0_ghz>0, dip_db, tol_freq_rel>=0,
    tol_dip_db>=0}}``——任一键缺失/非法抛 ValueError（不猜，em_bench
    inverse_design 判据同口径；容差缺即拒绝是 #122 预声明纪律）。
    """
    if not isinstance(spec, Mapping):
        raise ValueError(f"spec 须为映射（得 {type(spec).__name__}）")
    targets_raw = spec.get("targets")
    if not isinstance(targets_raw, Mapping) or not targets_raw:
        raise ValueError("spec.targets 必填（≥1 目标规格——逆设计判据声明面）")
    targets: dict[str, dict[str, Any]] = {}
    for tid, t in targets_raw.items():
        if not isinstance(t, Mapping):
            raise ValueError(f"targets[{tid!r}] 形态非法: {t!r}")
        f0_t = _finite_number(t.get("f0_ghz"))
        dip_t = _finite_number(t.get("dip_db"))
        tol_f = _finite_number(t.get("tol_freq_rel"))
        tol_d = _finite_number(t.get("tol_dip_db"))
        if f0_t is None or f0_t <= 0.0:
            raise ValueError(f"targets[{tid!r}].f0_ghz 必须为正有限数值"
                             "（相对频偏分母——0/负不可判读）")
        if dip_t is None:
            raise ValueError(f"targets[{tid!r}].dip_db 缺失/非法（幅度轴）")
        if tol_f is None or tol_f < 0.0:
            raise ValueError(f"targets[{tid!r}].tol_freq_rel 必须为 ≥0 有限数值"
                             "（#122：命中容差预声明，缺即 fail-closed）")
        if tol_d is None or tol_d < 0.0:
            raise ValueError(f"targets[{tid!r}].tol_dip_db 必须为 ≥0 有限数值"
                             "（#122：命中容差预声明，缺即 fail-closed）")
        targets[str(tid)] = {"f0_ghz": f0_t, "dip_db": dip_t,
                             "tol_freq_rel": tol_f, "tol_dip_db": tol_d}
    return targets


# ─── 响应测度提取与命中度打分（确定性纯函数） ─────────────────────────────


def curve_measures(
    pred_response: Mapping[str, Any], channel: str,
) -> dict[str, Any]:
    """预测曲线 → 标量测度（确定性；dB 地板 1e-12，谷深=显式 min 口径）。

    返回 ``{"f0_ghz"（argmin 频点，GHz）, "dip_db"（曲线最小 dB）,
    "f0_index"（argmin 下标，追溯面）}``。#195：谷深语义 = 显式
    min-of-dB（不取带内 max 等歧义统计量）；#298：多谷纹波器件 argmin
    峰位歧义为已知边界（通用口径的诚实声明）。
    """
    curves = pred_response.get("curves") if isinstance(
        pred_response, Mapping) else None
    if not isinstance(curves, Mapping) or channel not in curves:
        raise ValueError(
            f"pred_response.curves 缺通道 {channel!r}"
            f"（可得 {sorted(curves) if isinstance(curves, Mapping) else '无'}）")
    ch = curves[channel]
    try:
        re = np.asarray(ch["re"], dtype=np.float64)
        im = np.asarray(ch["im"], dtype=np.float64)
        freqs = np.asarray(pred_response["freqs_hz"], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"pred_response 曲线形态违例: {exc}") from exc
    if not (re.shape == im.shape == freqs.shape and re.ndim == 1
            and re.size >= 1):
        raise ValueError(
            f"曲线/频栅形状违例：re={re.shape} im={im.shape} "
            f"freqs={freqs.shape}（须同形一维非空）")
    db = 20.0 * np.log10(np.maximum(np.hypot(re, im), _AMPLITUDE_FLOOR))
    j = int(np.argmin(db))
    return {"f0_ghz": float(freqs[j]) / 1e9, "dip_db": float(db[j]),
            "f0_index": j}


def _tol_ratio(dev: float, tol: float) -> float:
    """dev/tol 比值（tol=0 合法：恰零比 0，非零比按 1e-12 地板——有限巨罚）。"""
    if tol <= 0.0:
        return 0.0 if dev <= 0.0 else dev / _TOL_FLOOR
    return dev / tol


def score_against_targets(
    measures: Mapping[str, Any], targets: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """逐目标命中明细 + 排序分数（em_bench 命中判据同口径的确定性纯函数）。

    命中 = ``freq_dev_rel ≤ tol_freq_rel ∧ dip_dev_db ≤ tol_dip_db``（恰等
    合格）；排序分数 = ``n_hits − Σ_missed min(max(两轴 dev/tol 比)−1, 1)
    /(T+1)``——罚项封顶 1 且除以 (T+1)，**命中数严格占优**（数学性质：
    score(h) > h−1 ≥ 任何更少命中数的分数），同命中数内超容差越小越前。
    返回 ``{"rows": [...], "n_hits", "n_targets", "score"}``，rows 字段与
    em_bench inverse_design detail 行同构（freq_dev_rel/dip_dev_db/tol_*/
    hit），另携 target_id 与目标锚值（报告自足）。
    """
    rows: list[dict[str, Any]] = []
    n_hits = 0
    total_excess = 0.0
    for tid in sorted(targets):
        t = targets[tid]
        f0_c = float(measures["f0_ghz"])
        dip_c = float(measures["dip_db"])
        freq_dev = abs(f0_c - t["f0_ghz"]) / t["f0_ghz"]
        dip_dev = abs(dip_c - t["dip_db"])
        hit = freq_dev <= t["tol_freq_rel"] and dip_dev <= t["tol_dip_db"]
        n_hits += 1 if hit else 0
        excess = max(_tol_ratio(freq_dev, t["tol_freq_rel"]),
                     _tol_ratio(dip_dev, t["tol_dip_db"])) - 1.0
        if excess > 0.0:
            total_excess += min(excess, 1.0)  # 封顶：大额超差不淹没命中数
        rows.append({
            "target_id": tid,
            "f0_target_ghz": t["f0_ghz"], "dip_target_db": t["dip_db"],
            "f0_ghz": f0_c, "dip_db": dip_c,
            "freq_dev_rel": freq_dev, "dip_dev_db": dip_dev,
            "tol_freq_rel": t["tol_freq_rel"], "tol_dip_db": t["tol_dip_db"],
            "hit": bool(hit),
        })
    # score = n_hits − 封顶罚项和/(T+1)：命中数**严格主导**（数学性质：
    # score(h) = h − S/(T+1)，S ≤ T−h < T+1 → score(h) > h−1 ≥ 任一更少
    # 命中数的分数上界）；同命中数内按封顶超差和升序。
    return {"rows": rows, "n_hits": n_hits, "n_targets": len(targets),
            "score": float(n_hits) - total_excess / (len(targets) + 1)}


def make_target_score_fn(
    targets: Mapping[str, Mapping[str, Any]], channel: str,
) -> Callable[[Mapping[str, Any]], float]:
    """目标规格 → batch_evaluate 打分纯函数（curve_measures + 命中度）。"""

    def _score(pred_response: Mapping[str, Any]) -> float:
        measures = curve_measures(pred_response, channel)
        return float(score_against_targets(measures, targets)["score"])

    return _score


# ─── 候选域派生与模型装载 ──────────────────────────────────────────────────


def _derive_bounds(
    fit_env: Mapping[str, Any],
) -> tuple[dict[str, tuple[float, float]], dict[str, float]]:
    """norm_x minmax 窗 → (LHS bounds, 定值维)（退化维=常数列定值注入）。"""
    nx = NormalizationSpec.from_dict(fit_env["norm_x"])
    names = [str(p) for p in fit_env["param_names"]]
    bounds: dict[str, tuple[float, float]] = {}
    fixed: dict[str, float] = {}
    for i, p in enumerate(names):
        c = float(nx.center[i])
        s = float(nx.scale[i])
        if abs(s) < _DEGENERATE_SCALE_EPS:
            fixed[p] = c
        else:
            bounds[p] = (c, c + s)
    return bounds, fixed


def _validate_explicit_bounds(
    bounds: Mapping[str, Any], param_names: list[str],
) -> dict[str, tuple[float, float]]:
    """显式 bounds 校验（键集须=param_names；low<high 有限——fail-closed）。"""
    if not isinstance(bounds, Mapping) or set(bounds) != set(param_names):
        raise ValueError(
            f"bounds 键集须与模型 param_names 一致 {sorted(param_names)}"
            f"（得到 {sorted(bounds) if isinstance(bounds, Mapping) else type(bounds).__name__}）")
    out: dict[str, tuple[float, float]] = {}
    for p in param_names:
        pair = bounds[p]
        try:
            lo, hi = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(f"bounds[{p!r}] 非法: {pair!r}") from exc
        if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
            raise ValueError(
                f"bounds[{p!r}] 须为有限 (low, high) 且 low < high: "
                f"{(lo, hi)!r}")
        out[p] = (lo, hi)
    return out


def _load_model(model: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """模型装载：fit 信封 dict 直传或 JSON 文件路径（读失败 error 信封）。"""
    if isinstance(model, Mapping):
        return dict(model), None
    if isinstance(model, (str, Path)):
        path = Path(model)
        try:
            env = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None, error_envelope([f"模型文件不存在: {path}"])
        except (OSError, json.JSONDecodeError) as exc:
            return None, error_envelope([f"模型文件读取/解析失败: {exc}"])
        if not isinstance(env, dict):
            return None, error_envelope(
                [f"模型文件顶层须为 JSON 对象（得 {type(env).__name__}）"])
        return env, None
    return None, error_envelope([
        f"model 须为 fit 信封 dict 或 JSON 文件路径（得 {type(model).__name__}）"])


# ─── 编排入口（LHS 候选 → 批量评估 → top-k 命中度报告） ────────────────────


def optimize_with_neural_surrogate(
    model: Mapping[str, Any] | str | Path,
    spec: Mapping[str, Any],
    n_candidates: int = 10000,
    top_k: int = 5,
    *,
    seed: int = 42,
    bounds: Mapping[str, Sequence[float]] | None = None,
) -> dict[str, Any]:
    """神经代理批量取最优：LHS 候选 → 批量前向 → 目标命中度打分 → top-k。

    Args:
        model: fit_neural_surrogate ok 信封（dict）或其 JSON 文件路径；
            unavailable 信封传入→unavailable 信封如实透传（装 torch 后
            重训即可，权重面不存在时无降级可走）。
        spec: ``{"targets": {...}}``（schema 见 parse_inverse_targets）+
            可选 ``"channel"``（打分通道；缺省=channels[0]）。
        n_candidates: LHS 候选数（≥1；棘轮上限
            NEURAL_BATCH_MAX_CANDIDATES=100000，超限显式拒绝）。
        top_k: 报告排名条数（≥1，> 有效候选数时取全部）。
        seed: LHS 种子（确定性唯一随机源；同 seed 同输入逐位复现）。
        bounds: 显式候选域 ``{param: (low, high)}``（键集须=param_names，
            low<high）；None=从 fit 信封 norm_x 观测窗派生（退化维定值
            注入，见模块头候选域口径）。

    Returns:
        ok 信封::

            {"ok": True, "kind": "neural_batch_optimize",
             "n_candidates", "seed", "top_k", "channel", "targets",
             "bounds_source", "bounds", "fixed_dims",
             "engine", "engine_note",
             "n_evaluated", "n_dropped", "n_score_invalid", "n_score_failed",
             "ranked": [...（每条附 measures + hit_detail 逐目标命中明细）],
             "best": ranked[0] | None, "elapsed_s"}

        负例（模型/规格/域/上限非法）error 信封零副作用；unavailable
        如实透传。确定性：同 seed 同输入全信封逐位复现（elapsed_s 除外）。
    """
    t0 = time.monotonic()
    try:
        n_cand = int(n_candidates)
        k = int(top_k)
        seed_i = int(seed)
    except (TypeError, ValueError):
        return error_envelope([
            f"n_candidates/top_k/seed 须可数值化（得 {n_candidates!r}/"
            f"{top_k!r}/{seed!r}）"])
    if n_cand < 1:
        return error_envelope([f"n_candidates 必须 >=1，收到 {n_candidates!r}"])
    if n_cand > NEURAL_BATCH_MAX_CANDIDATES:
        return error_envelope([
            f"n_candidates={n_cand} 超出上限 {NEURAL_BATCH_MAX_CANDIDATES}"
            "（棘轮上限只收不放——更大批量须先升上限常量并过评审）"])
    if k < 1:
        return error_envelope([f"top_k 必须 >=1，收到 {top_k!r}"])

    # ① 模型装载与规格解析（fail-closed；unavailable 在本层如实透传——
    # 权重面不存在时无降级可走，早于通道/候选域检查避免误报缺键）
    env, load_err = _load_model(model)
    if load_err is not None:
        return load_err
    assert env is not None
    if env.get("ok") is not True:
        if env.get("unavailable") is True:
            return env
        return error_envelope([
            "model 须为 fit_neural_surrogate 的 ok 信封（或其 JSON 文件）",
            *(f"model errors: {e}" for e in (env.get("errors") or []))])
    try:
        targets = parse_inverse_targets(spec)
    except ValueError as exc:
        return error_envelope([str(exc)])
    channels = [str(c) for c in (env.get("channels") or [])]
    if not channels:
        return error_envelope(["模型信封 channels 为空（非 fit ok 信封？）"])
    channel = str(spec.get("channel") or channels[0])
    if channel not in channels:
        return error_envelope([
            f"spec.channel={channel!r} 不在模型通道面 {channels}"])
    param_names = [str(p) for p in (env.get("param_names") or [])]
    if not param_names:
        return error_envelope(["模型信封 param_names 为空（非 fit ok 信封？）"])

    # ② 候选域（显式 bounds 校验；缺省 norm 窗派生 + 退化维定值）
    fixed: dict[str, float] = {}
    if bounds is not None:
        try:
            bounds_eff = _validate_explicit_bounds(bounds, param_names)
        except ValueError as exc:
            return error_envelope([str(exc)])
        bounds_source = "explicit"
    else:
        bounds_eff, fixed = _derive_bounds(env)
        bounds_source = "norm_window"
    if not bounds_eff:
        return error_envelope([
            "候选域全退化（norm 窗全为常数列）——LHS 无域可撒；"
            "请显式传 bounds 或扩大训练数据参数覆盖"])

    # ③ LHS 候选（懒 import——active_learning_loop 同先例）+ 定值维注入
    from rfauto.optimization.sample_design import lhs_points

    lhs = lhs_points(dict(bounds_eff), n_cand, seed=seed_i)
    candidates = [{**pt, **fixed} for pt in lhs["points"]]

    # ④ 批量评估（打分纯函数注入；not-ok 信封原样透传）
    score_fn = make_target_score_fn(targets, channel)
    result = batch_evaluate(env, candidates, score_fn, top_k=k)
    if not result.get("ok"):
        return result

    # ⑤ top-k 逐目标命中明细回填（与 score_fn 同纯函数重算，确定性一致）
    ranked: list[dict[str, Any]] = []
    for entry in result["ranked"]:
        measures = curve_measures(entry["pred_response"], channel)
        detail = score_against_targets(measures, targets)
        ranked.append({**entry, "measures": measures, "hit_detail": detail})
    best = ranked[0] if ranked else None

    return ok_envelope(
        kind="neural_batch_optimize",
        n_candidates=len(candidates),
        seed=seed_i,
        top_k=k,
        channel=channel,
        targets={tid: dict(t) for tid, t in sorted(targets.items())},
        bounds_source=bounds_source,
        bounds={p: list(v) for p, v in sorted(bounds_eff.items())},
        fixed_dims=dict(sorted(fixed.items())),
        engine=result["engine"],
        engine_note=result["engine_note"],
        n_evaluated=result["n_evaluated"],
        n_dropped=result["n_dropped"],
        n_score_invalid=result["n_score_invalid"],
        n_score_failed=result["n_score_failed"],
        ranked=ranked,
        best=best,
        elapsed_s=round(time.monotonic() - t0, 4),
    )
