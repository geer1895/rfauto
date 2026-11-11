"""主动学习环（aurora_r R-07，B4：GP 后验 σ 阈值→触发真值点→回填）。

语境（runs/aurora_q/qx40_vbridge/AUTHOR_SURVEY.md 调研吸收；§22.2
rf_template_references 五步建法②③对位）：数据工厂采集面在参数域撒
LHS 候选池 → GP 后验 (μ,σ) 逐点评估 → **σ 高于阈值/最不确定的 top-k**
才烧真值预算（run_once/eval 通道同款 params→metrics 注入口径）→ 回填
数据集 →（可选）GP 重训 → 每轮落盘 round 报告。纯确定性内核（铁律 7，
无 LLM）：同 seed 同输入逐位复现同一轨迹。

- **σ 输出（任务①）**：零 core 改动——σ 已在消费链两端就位：
  ``core.gp_tensor_kernel.regression_predict`` 返回 ``{mean, std, nugget}``
  （相对 nugget=RELATIVE_NUGGET×var(y)，df6⑨ 同源），``optimization.
  surrogate.gp_det.gp_posterior`` 返回 (mean, var)。本模块只消费 std 键
  并按目标量纲反缩放，不新增不改名任何 core 输出键（缺省路径零变化，
  钉在 tests/unit/test_active_learning_loop.py）。
- **采集策略（任务②）**：``select_by_sigma`` 纯函数——候选点集+GP
  (μ,σ)+阈值/批量参数 → 方差贪心 top-k（σ 降序 + 归一化最小距离多样性
  筛选，同 active_learning.propose_next_points 双重准则口径）；NaN/Inf
  的 μ/σ 显式排除计数，不静默（#122）。候选点生成复用既有
  ``optimization.sample_design.lhs_points``（scipy qmc，种子确定性）。
- **环编排（任务③）**：``run_active_learning_loop``——上限/预算显式
  （max_rounds/max_evals 谁先触发谁停，防无限环）；evaluate_fn 注入即
  真值求解通道（fake 适配器/闭式响应端到端可测，与 run_surrogate_loop
  同构口径，solve 失败记 failure 不炸环）；回填幂等闸（同点不重复采，
  口径见 ``canonical_param_key``）；重训指标（LOOCV MSE/logpdf/
  lengthscale/nugget）入轮报告；报告落盘 runs/ 产物惯例（report_dir
  显式传入，best-effort #105——写失败只记不炸环；本模块绝不自建
  create_run_dir（#144 家族：runs/ 写面由调用方显式给路径））。
- **重复点识别口径（回填幂等，docstring 单源）**：两点互为"同点" ⟺
  参数键集合相同（排序后逐键）且逐键 ``round(float(v), 12)`` 相等
  （``canonical_param_key``）；选点阶段另有归一化 L2 距离 ≥ min_dist
  的近邻闸（防近似重复点烧预算）——两道闸独立生效：canonical 闸保
  **回填幂等**（精确同点零重复行、零重复评估），min_dist 闸保**批量
  多样性**。初始样本集内已存在的 canonical 键全部预登记，环内任何
  轮次再选中同点一律跳过评估（n_dup_skipped 计数，不烧预算）。

信封契约（规则 4）：环入口 ok/error envelope（service/envelope 构造器，
AU-2 单源）；纯函数返回普通 dict（内核契约，非信封面）。无 CLI/MCP
叶（挂账处方：后续可挂 ``al_service`` 同款运行时 JSON 门或
``rfauto al loop`` 薄壳——采集/环逻辑已在本模块，CLI 只透传参数，
勿再复制实现）。模块**不带 __all__**：public_api 金快照（tests/gold）
本席禁改，公开面按申报制登记于本 docstring + 席位报告；合流席如需
钉入快照，加 __all__ 后跑 scripts/check_public_api.py --generate 重钉
（评审动作）。
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.gp_tensor_kernel import (
    DEFAULT_MAX_POINTS,
    RELATIVE_NUGGET,
    fit_weights_loocv,
    regression_predict,
)
from rfauto.service.envelope import error_envelope, ok_envelope

#: 报告文件名前缀（report_dir 显式给定时逐轮写
#: ``<前缀>_round_<序号三位>.json``）。
REPORT_STEM = "active_learning_round"

#: 环内 stop_reason 取值面（契约钉；消费方按值分派）。
STOP_REASONS = (
    "rounds_exhausted",         # 跑满 max_rounds（自然收官）
    "eval_budget_exhausted",    # 真值评估预算 max_evals 用尽
    "sigma_saturated",          # 全体合格候选 σ < 阈值（代理已够信）
    "no_eligible_candidates",   # 无合格候选（全被 NaN/距离/空池拦下）
    "no_new_samples",           # 整轮零回填（全 dup/全失败，续转即空转）
    "gp_fit_failed",            # GP 拟合异常（如实停环，不静默降级）
    "insufficient_gp_samples",  # GP 有效样本 <3（中途防御性停环）
)


# ─── 采集策略纯函数（任务②，可离线全测） ──────────────────────────────────


def canonical_param_key(
    params: Mapping[str, Any], *, ndigits: int = 12,
) -> tuple[tuple[str, float], ...]:
    """重复点识别口径单源（语义见模块头"重复点识别口径"节）。

    参数键排序后逐键 ``round(float(v), ndigits)``——键集不同或任一键
    舍入值不同即非同点。非数值参数值显式抛 ValueError（不静默当 0）。
    ndigits=12 的理由：LHS/qmc 输出的双精度参数经 JSON 往返后逐位不变，
    12 位只吸收浮点尾数级抖动；近邻重复（距离 >0 但极小）由选点阶段
    min_dist 闸负责，canonical 闸不越权。
    """
    items: list[tuple[str, float]] = []
    for name in sorted(params):
        v = params[name]
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(float(v)):
            raise ValueError(f"参数 {name!r} 非有限数值: {v!r}")
        items.append((str(name), round(float(v), int(ndigits))))
    return tuple(items)


def select_by_sigma(
    candidates: Sequence[Mapping[str, float]],
    mu: Sequence[float],
    sigma: Sequence[float],
    *,
    bounds: Mapping[str, Sequence[float]],
    k: int = 3,
    sigma_threshold: float | None = None,
    min_dist: float = 0.05,
    existing_points: Sequence[Mapping[str, float]] | None = None,
) -> dict[str, Any]:
    """方差贪心 top-k 采集（纯函数，零随机源，零入参突变）。

    Args:
        candidates: 候选点参数字典列表（与 mu/sigma 按下标对齐）。
        mu / sigma: GP 后验均值/标准差（目标量纲）；σ<0 视为非法。
        bounds: ``{param: (low, high)}``——归一化 [0,1]^d 距离空间。
        k: 批量上限（≥1）。
        sigma_threshold: σ 准入阈值（None=不设阈，纯 top-k）；边界语义
            **σ == threshold 合格**（≥ 判据，恰好等于不排除）。
        min_dist: 归一化 L2 最小距离（对已选点与 existing_points 双向
            生效；0=关闭近邻闸）。
        existing_points: 既有样本参数集（近邻闸参照；不改变候选池）。

    Returns:
        普通 dict 契约（内核面，非信封）::

            {"selected": [{"index", "params", "mu", "sigma"}, ...],
             "n_eligible", "n_below_threshold", "n_invalid",
             "n_rejected_by_min_dist", "k_requested",
             "sigma_pool": {"max", "mean", "median"}}   # 合格池统计

        selected 按 σ 降序（σ 相等按下标升序——确定性 tie-break）；
        空候选/全非法/全低于阈值/全被距离拦下时 selected=[]（各计数
        字段如实区分原因，不静默）。

    Raises:
        ValueError: k<1、min_dist<0、阈值非有限或 <0、mu/sigma 与候选
            数不对齐、bounds 非法或候选点参数非有限数值。
    """
    if int(k) < 1:
        raise ValueError(f"k 必须 >=1，收到 {k!r}")
    md = float(min_dist)
    if not math.isfinite(md) or md < 0.0:
        raise ValueError(f"min_dist 必须为 >=0 的有限数，收到 {min_dist!r}")
    thr: float | None = None
    if sigma_threshold is not None:
        thr = float(sigma_threshold)
        if not math.isfinite(thr) or thr < 0.0:
            raise ValueError(
                f"sigma_threshold 必须为 >=0 的有限数或 None，收到 "
                f"{sigma_threshold!r}")
    names, lower, span = _bounds_arrays(bounds)
    n = len(candidates)
    if len(mu) != n or len(sigma) != n:
        raise ValueError(
            f"candidates/mu/sigma 数量不对齐: {n}/{len(mu)}/{len(sigma)}")
    cand_norm = [
        _normalize_point(dict(pt), names, lower, span) for pt in candidates]
    exist_norm = [
        _normalize_point(dict(pt), names, lower, span)
        for pt in (existing_points or [])]

    eligible: list[tuple[float, float, int]] = []  # (sigma, mu, index)
    n_invalid = 0
    n_below = 0
    for i in range(n):
        m_i, s_i = float(mu[i]), float(sigma[i])
        if not (math.isfinite(m_i) and math.isfinite(s_i)) or s_i < 0.0:
            n_invalid += 1  # NaN/Inf μ/σ、负 σ：显式排除计数，不静默
            continue
        if thr is not None and s_i < thr:
            n_below += 1  # 阈值边界：σ == threshold 合格（< 才排除）
            continue
        eligible.append((s_i, m_i, i))
    # σ 降序、同 σ 按下标升序（确定性 tie-break，无随机源）
    eligible.sort(key=lambda t: (-t[0], t[2]))

    picked_norm: list[list[float]] = []
    selected: list[dict[str, Any]] = []
    n_rejected_dist = 0
    for s_i, m_i, i in eligible:
        if len(selected) >= int(k):
            break
        pn = cand_norm[i]
        if md > 0.0 and (_too_close(pn, picked_norm, md) is not None
                         or _too_close(pn, exist_norm, md) is not None):
            n_rejected_dist += 1
            continue
        picked_norm.append(pn)
        selected.append({
            "index": i,
            "params": dict(candidates[i]),
            "mu": m_i,
            "sigma": s_i,
        })
    return {
        "selected": selected,
        "n_eligible": len(eligible),
        "n_below_threshold": n_below,
        "n_invalid": n_invalid,
        "n_rejected_by_min_dist": n_rejected_dist,
        "k_requested": int(k),
        "sigma_pool": _pool_stats([t[0] for t in eligible]),
    }


# ─── 归一化/距离小工具（bounds 空间收敛，非法输入显式报错） ─────────────────


def _bounds_arrays(
    bounds: Mapping[str, Sequence[float]],
) -> tuple[list[str], list[float], list[float]]:
    """(names, lower, span) 收敛；空/非有限/low>=high 显式拒绝。"""
    if not isinstance(bounds, Mapping) or not bounds:
        raise ValueError("bounds 必须为非空 {param: (low, high)} 字典")
    names = sorted(bounds)
    lower: list[float] = []
    span: list[float] = []
    for nm in names:
        pair = bounds[nm]
        try:
            lo, hi = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(f"bounds[{nm!r}] 非法: {pair!r}") from exc
        if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
            raise ValueError(
                f"bounds[{nm!r}] 须为有限 (low, high) 且 low < high: "
                f"{(lo, hi)!r}")
        lower.append(lo)
        span.append(max(hi - lo, 1e-12))
    return names, lower, span


def _normalize_point(
    pt: Mapping[str, float], names: list[str], lower: list[float],
    span: list[float],
) -> list[float]:
    """单点 → 归一化行（缺失键回落下界；非数值显式拒绝）。"""
    row = []
    for i, nm in enumerate(names):
        v = pt.get(nm, lower[i])
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(float(v)):
            raise ValueError(f"参数 {nm!r} 非有限数值: {v!r}")
        row.append((float(v) - lower[i]) / span[i])
    return row


def _too_close(
    pn: list[float], pool: list[list[float]], min_dist: float,
) -> list[float] | None:
    """pn 与池内任一点归一化 L2 距离 < min_dist → 返回首个过近点。"""
    for q in pool:
        d2 = sum((a - b) ** 2 for a, b in zip(pn, q, strict=True))
        if math.sqrt(d2) < min_dist:
            return q
    return None


def _pool_stats(pool: list[float]) -> dict[str, float]:
    """合格池 σ 统计（max/mean/median；空池三元 0.0——如实零面）。"""
    if not pool:
        return {"max": 0.0, "mean": 0.0, "median": 0.0}
    sp = sorted(pool)
    n = len(sp)
    median = sp[n // 2] if n % 2 else 0.5 * (sp[n // 2 - 1] + sp[n // 2])
    return {"max": sp[-1], "mean": sum(sp) / n, "median": median}


# ─── GP 拟合/预测链（消费 core.gp_tensor_kernel，σ 零 core 改动） ──────────


def _fit_gp(
    x: np.ndarray, z: np.ndarray, *, lengthscale_grid: Sequence[float],
    sigma_f: float, relative_nugget: float,
) -> dict[str, Any]:
    """LOOCV 网格定 ℓ（确定性：固定网格 + 闭式折误差，无随机源）。"""
    fit = fit_weights_loocv(
        x, z, [float(v) for v in lengthscale_grid],
        sigma_f=float(sigma_f), relative_nugget=float(relative_nugget))
    return {
        "lengthscale": float(fit["lengthscale"]),
        "loocv_mse": float(fit["loocv_mse"]),
        "loocv_mean_logpdf": float(fit["loocv_mean_logpdf"]),
        "nugget": float(fit["nugget"]),
        "n_candidates": int(fit["n_candidates"]),
    }


def _predict_mu_sigma(
    fit: dict[str, Any], x_tr: np.ndarray, z_tr: np.ndarray,
    x_cand: np.ndarray, *, sigma_f: float, relative_nugget: float,
    y_mean: float, y_std: float,
) -> tuple[list[float], list[float]]:
    """候选池后验 (μ,σ)，z 尺度反缩放回目标量纲（σ≥0 恒成立）。

    σ 源=regression_predict 的 ``std`` 键（core 既有输出，本模块零
    core 改动；相对 nugget 防插值 σ 塌缩，df6⑨ 同源）。
    """
    out = regression_predict(
        x_tr, z_tr, x_cand, lengthscale=fit["lengthscale"],
        sigma_f=float(sigma_f), relative_nugget=float(relative_nugget))
    mu = [float(v) * y_std + y_mean for v in out["mean"]]
    sigma = [max(float(v) * y_std, 0.0) for v in out["std"]]
    return mu, sigma


def _fit_gp_state(
    work: list[dict[str, Any]], names: list[str], lower: list[float],
    span: list[float], *, metric_key: str,
    lengthscale_grid: Sequence[float], sigma_f: float,
    relative_nugget: float,
) -> tuple[dict[str, Any] | None, str | None]:
    """样本集 → GP 拟合态（z 尺度；有限 y 行过滤，不足/异常如实上报）。

    返回 (state, None) 或 (None, error)；state 携带拟合超参 + 训练
    矩阵 + 反缩放统计 + 有效/排除行数（观测性全量入报告）。
    """
    rows: list[list[float]] = []
    ys: list[float] = []
    n_excluded = 0
    for s in work:
        v = (s.get("metrics") or {}).get(metric_key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(float(v)):
            n_excluded += 1
            continue
        try:
            rows.append(_normalize_point(s.get("params") or {}, names,
                                         lower, span))
        except ValueError:
            n_excluded += 1
            continue
        ys.append(float(v))
    if len(ys) < 3:
        return None, (f"GP 有效样本不足：metrics[{metric_key!r}] 有限数值"
                      f"行 {len(ys)} < 3（排除 {n_excluded} 行）")
    y_mean = sum(ys) / len(ys)
    y_var = sum((v - y_mean) ** 2 for v in ys) / len(ys)
    y_std = max(y_var ** 0.5, 1e-12)
    z = [(v - y_mean) / y_std for v in ys]
    try:
        fit = _fit_gp(
            np.asarray(rows, dtype=float), np.asarray(z, dtype=float),
            lengthscale_grid=lengthscale_grid, sigma_f=sigma_f,
            relative_nugget=relative_nugget)
    except Exception as exc:
        return None, f"GP 拟合失败: {type(exc).__name__}: {exc}"
    return ({"fit": fit, "rows": rows, "z": z, "y_mean": y_mean,
             "y_std": y_std, "n_used": len(ys),
             "n_excluded": n_excluded}), None


# ─── 环编排 service 函数（任务③，信封进出，规则 4） ────────────────────────


def run_active_learning_loop(
    bounds: dict[str, tuple[float, float]],
    samples: list[dict[str, Any]],
    evaluate_fn: Callable[[dict[str, float]], dict[str, float]],
    *,
    metric_key: str,
    sigma_threshold: float | None = None,
    batch_k: int = 3,
    max_rounds: int = 4,
    max_evals: int | None = None,
    candidate_n: int = 128,
    min_dist: float = 0.05,
    lengthscale_grid: Sequence[float] = (0.05, 0.1, 0.2, 0.35, 0.5,
                                         0.8, 1.2),
    sigma_f: float = 1.0,
    relative_nugget: float = RELATIVE_NUGGET,
    refit: bool = True,
    seed: int = 42,
    report_dir: str | Path | None = None,
) -> dict[str, Any]:
    """主动学习环入口：LHS 候选 → GP (μ,σ) → σ 选点 → 真值评估 → 回填。

    Args:
        bounds: 参数域 ``{param: (low, high)}``（low < high 有限）。
        samples: 既有数据集行 ``{"params": {...}, "metrics": {...}}``
            （与 samples.json/数据工厂行同构）；本函数**不改写入参**
            （回填到内部副本，原列表零突变——缺省路径零变化钉）。
        evaluate_fn: 真值求解通道 ``params → metrics``（与
            run_surrogate_loop.evaluate_fn / run_once 指标链同构口径；
            抛异常=该点失败，记 failure 不炸环）。fake 适配器/闭式响应
            即可端到端。
        metric_key: GP 建模的目标指标键（samples 的 metrics 内有限
            数值者入拟合，不足 3 个入口即拒）。
        sigma_threshold: σ 准入阈值（None=纯 top-k 模式）。
        batch_k / max_rounds / max_evals: 每轮批量、轮数上限、真值评估
            总预算（max_evals None=默认 max_rounds×batch_k；成功+失败
            都烧预算，dup 跳过不烧）。**三者显式给上限，防无限环**。
        candidate_n: 每轮 LHS 候选池大小（复用
            optimization.sample_design.lhs_points，seed=seed+1000·轮序）。
        min_dist: 归一化最小距离（选点近邻闸，见模块头两道闸口径）。
        lengthscale_grid / sigma_f / relative_nugget: GP 链旋钮
            （relative_nugget 缺省=core RELATIVE_NUGGET，df6⑨ 同源）。
        refit: True=每轮回填后重训（重训指标入轮报告）；False=只训
            一次复用（σ 图随样本陈旧，预算敏感档如实标注 "refit"=False）。
        seed: LHS 候选池种子（确定性唯一随机源）。
        report_dir: 每轮报告落盘目录（runs/ 产物惯例；None=不落盘，
            报告仍在返回体 rounds 内；写失败 best-effort 不炸环 #105）。

    Returns:
        ok 信封::

            {"ok": True, "metric_key", "sigma_threshold", "batch_k",
             "max_rounds", "max_evals", "stop_reason",  # STOP_REASONS 面
             "n_rounds", "n_evals_used", "n_backfilled", "n_failed",
             "n_dup_skipped", "backfilled": [...], "failures": [...],
             "rounds": [...], "sigma_trace": [...], "elapsed_s",
             "report_dir"?, "report_files"?}

        负例（非法入参）error 信封零副作用。确定性：同 seed 同输入
        逐位复现（含选点序与 σ 统计；唯一随机源=LHS 种子）。
    """
    t0 = time.monotonic()
    err = _validate_inputs(
        bounds, samples, metric_key, sigma_threshold=sigma_threshold,
        batch_k=batch_k, max_rounds=max_rounds, max_evals=max_evals,
        candidate_n=candidate_n, min_dist=min_dist,
        lengthscale_grid=lengthscale_grid, sigma_f=sigma_f,
        relative_nugget=relative_nugget)
    if err is not None:
        return err

    names, lower, span = _bounds_arrays(bounds)
    max_evals_eff = int(max_evals) if max_evals is not None \
        else int(max_rounds) * int(batch_k)

    # 工作副本（入参零突变）+ 回填幂等登记表（canonical 口径见模块头）
    work = [dict(s) for s in samples]
    known_keys: set[tuple[tuple[str, float], ...]] = set()
    for s in work:
        try:
            known_keys.add(canonical_param_key(s.get("params") or {}))
        except ValueError:
            continue  # 既有行参数非法不入登记表（GP 拟合侧同样排除）

    from rfauto.optimization.sample_design import lhs_points

    rounds: list[dict[str, Any]] = []
    sigma_trace: list[dict[str, Any]] = []
    backfilled: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    report_files: list[str] = []
    n_evals = 0
    n_dup = 0
    stop_reason: str | None = None
    gp_state: dict[str, Any] | None = None

    for rnd in range(int(max_rounds)):
        round_report: dict[str, Any] = {
            "round": rnd,
            "n_samples_before": len(work),
        }
        # ① GP 拟合（refit=False 只训一次；失败如实停环 #122）
        if gp_state is None or refit:
            gp_state, fit_err = _fit_gp_state(
                work, names, lower, span, metric_key=metric_key,
                lengthscale_grid=lengthscale_grid, sigma_f=sigma_f,
                relative_nugget=relative_nugget)
            if fit_err is not None:
                round_report["gp_refit"] = {"ok": False, "error": fit_err}
                rounds.append(round_report)
                _flush_report(round_report, report_dir, report_files)
                stop_reason = (
                    "insufficient_gp_samples"
                    if fit_err.startswith("GP 有效样本不足")
                    else "gp_fit_failed")
                break
        fit = gp_state["fit"]
        round_report["gp_refit"] = {
            "ok": True,
            "refit": bool(refit or rnd == 0),
            "n_gp_samples": gp_state["n_used"],
            "n_gp_excluded": gp_state["n_excluded"],
            **fit,
        }

        # ② 候选池（lhs_points 复用；seed=seed+1000·轮序 确定性轮换）
        cand = lhs_points(
            {nm: (lower[i], lower[i] + span[i])
             for i, nm in enumerate(names)},
            int(candidate_n), seed=int(seed) + 1000 * rnd)["points"]
        round_report["n_candidates"] = len(cand)
        if not cand:
            stop_reason = "no_eligible_candidates"
            rounds.append(round_report)
            _flush_report(round_report, report_dir, report_files)
            break

        # ③ 候选池 GP 后验 (μ,σ)（std 键消费，反缩放回目标量纲）
        x_cand = np.asarray(
            [_normalize_point(p, names, lower, span) for p in cand],
            dtype=float)
        mu, sigma = _predict_mu_sigma(
            fit, np.asarray(gp_state["rows"], dtype=float),
            np.asarray(gp_state["z"], dtype=float), x_cand,
            sigma_f=sigma_f, relative_nugget=relative_nugget,
            y_mean=gp_state["y_mean"], y_std=gp_state["y_std"])

        # ④ σ 选点（纯函数；近邻闸双向：已选点 + 既有样本）
        sel = select_by_sigma(
            cand, mu, sigma, bounds=bounds, k=int(batch_k),
            sigma_threshold=sigma_threshold, min_dist=float(min_dist),
            existing_points=[s.get("params") or {} for s in work])
        round_report["selection"] = {
            kk: sel[kk] for kk in
            ("n_eligible", "n_below_threshold", "n_invalid",
             "n_rejected_by_min_dist")}
        round_report["sigma_pool"] = sel["sigma_pool"]
        round_report["selected"] = [
            {"params": s["params"], "mu": s["mu"], "sigma": s["sigma"]}
            for s in sel["selected"]]
        sigma_trace.append({
            "round": rnd, **sel["sigma_pool"],
            "n_eligible": sel["n_eligible"],
            "n_invalid": sel["n_invalid"],
            "n_below_threshold": sel["n_below_threshold"],
        })

        if not sel["selected"]:
            stop_reason = (
                "sigma_saturated"
                if (sigma_threshold is not None and sel["n_eligible"] == 0
                    and sel["n_invalid"] == 0)
                else "no_eligible_candidates")
            rounds.append(round_report)
            _flush_report(round_report, report_dir, report_files)
            break

        # ⑤ 逐点真值评估 + 回填（canonical 幂等闸先于评估，dup 不烧预算）
        n_backfilled_round = 0
        round_report["evals"] = []
        for item in sel["selected"]:
            if n_evals >= max_evals_eff:
                stop_reason = "eval_budget_exhausted"
                break
            params = dict(item["params"])
            key = canonical_param_key(params)
            if key in known_keys:
                n_dup += 1  # 回填幂等：同点不重复采（口径见模块头）
                round_report["evals"].append(
                    {"params": params, "skipped": "duplicate"})
                continue
            n_evals += 1
            try:
                metrics = evaluate_fn(params)
                if not isinstance(metrics, Mapping):
                    raise TypeError(
                        f"evaluate_fn 须返回 metrics 字典，实得 "
                        f"{type(metrics).__name__}")
            except Exception as exc:  # 真跑失败记 failure，不炸环
                failures.append({"round": rnd, "params": params,
                                 "error": str(exc)})
                round_report["evals"].append(
                    {"params": params, "ok": False, "error": str(exc)})
                continue
            work.append({"params": params, "metrics": dict(metrics)})
            known_keys.add(key)
            backfilled.append({"round": rnd, "params": params,
                               "metrics": dict(metrics)})
            n_backfilled_round += 1
            round_report["evals"].append(
                {"params": params, "ok": True, "metrics": dict(metrics)})
        round_report["n_backfilled"] = n_backfilled_round
        round_report["n_failures"] = sum(
            1 for e in round_report["evals"] if e.get("ok") is False)
        rounds.append(round_report)
        _flush_report(round_report, report_dir, report_files)

        if stop_reason == "eval_budget_exhausted":
            break
        if n_backfilled_round == 0:
            # 整轮零回填（全 dup/全失败）：refit 后 GP 面不变、下轮候选
            # 亦难改观——继续轮转空转烧轮次，如实停（防无效环）
            stop_reason = "no_new_samples"
            break
    else:
        stop_reason = "rounds_exhausted"

    return ok_envelope(
        metric_key=str(metric_key),
        sigma_threshold=(None if sigma_threshold is None
                         else float(sigma_threshold)),
        batch_k=int(batch_k),
        max_rounds=int(max_rounds),
        max_evals=max_evals_eff,
        stop_reason=stop_reason,
        n_rounds=len(rounds),
        n_evals_used=n_evals,
        n_backfilled=len(backfilled),
        n_failed=len(failures),
        n_dup_skipped=n_dup,
        backfilled=backfilled,
        failures=failures,
        rounds=rounds,
        sigma_trace=sigma_trace,
        elapsed_s=round(time.monotonic() - t0, 4),
        **_report_fields(report_dir, report_files),
    )


# ─── 环内部件（入口校验 / 报告落盘 best-effort） ────────────────────────────


def _validate_inputs(
    bounds: Any, samples: Any, metric_key: Any, *,
    sigma_threshold: float | None, batch_k: int, max_rounds: int,
    max_evals: int | None, candidate_n: int, min_dist: float,
    lengthscale_grid: Sequence[float], sigma_f: float,
    relative_nugget: float,
) -> dict[str, Any] | None:
    """入口负例校验（error 信封零副作用；None=通过）。"""
    try:
        _bounds_arrays(bounds)
    except ValueError as exc:
        return error_envelope([str(exc)])
    if not isinstance(metric_key, str) or not metric_key:
        return error_envelope(["metric_key 必须为非空字符串"])
    if not isinstance(samples, list) or not all(
            isinstance(s, dict) for s in samples):
        return error_envelope(["samples 必须为 {params, metrics} 行列表"])
    n_finite = _count_finite_metric(samples, metric_key)
    if n_finite < 3:
        return error_envelope([
            f"GP 拟合有效样本不足：metrics[{metric_key!r}] 有限数值行 "
            f"{n_finite} < 3（gp_tensor_kernel LOOCV 下限）"])
    if n_finite > DEFAULT_MAX_POINTS:
        return error_envelope([
            f"GP 有效样本 {n_finite} 超出 gp_tensor_kernel 小规模上限 "
            f"{DEFAULT_MAX_POINTS}（超限显式拒绝，不静默走慢路径）"])
    if int(batch_k) < 1:
        return error_envelope([f"batch_k 必须 >=1，收到 {batch_k!r}"])
    if int(max_rounds) < 1:
        return error_envelope([f"max_rounds 必须 >=1，收到 {max_rounds!r}"])
    if max_evals is not None and int(max_evals) < 1:
        return error_envelope(
            [f"max_evals 必须 >=1（或 None=默认 max_rounds×batch_k），"
             f"收到 {max_evals!r}"])
    if int(candidate_n) < 1:
        return error_envelope([f"candidate_n 必须 >=1，收到 {candidate_n!r}"])
    if not math.isfinite(float(min_dist)) or float(min_dist) < 0.0:
        return error_envelope(
            [f"min_dist 必须为 >=0 的有限数，收到 {min_dist!r}"])
    if sigma_threshold is not None:
        thr = float(sigma_threshold)
        if not math.isfinite(thr) or thr < 0.0:
            return error_envelope(
                [f"sigma_threshold 必须为 >=0 的有限数或 None，收到 "
                 f"{sigma_threshold!r}"])
    if not math.isfinite(float(sigma_f)) or float(sigma_f) <= 0.0:
        return error_envelope([f"sigma_f 必须为正有限数，收到 {sigma_f!r}"])
    if not math.isfinite(float(relative_nugget)) \
            or float(relative_nugget) < 0.0:
        return error_envelope(
            [f"relative_nugget 必须 >=0 有限，收到 {relative_nugget!r}"])
    grid = [float(v) for v in lengthscale_grid]
    if not grid or any(not math.isfinite(v) or v <= 0.0 for v in grid):
        return error_envelope([
            f"lengthscale_grid 必须为非空正数序列，收到 "
            f"{lengthscale_grid!r}"])
    return None


def _count_finite_metric(
    samples: list[dict[str, Any]], metric_key: str,
) -> int:
    """metrics[metric_key] 为有限数值（bool 除外）的行数。"""
    n = 0
    for s in samples:
        v = (s.get("metrics") or {}).get(metric_key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(float(v)):
            continue
        n += 1
    return n


def _flush_report(
    round_report: dict[str, Any], report_dir: str | Path | None,
    report_files: list[str],
) -> None:
    """轮报告落盘（best-effort #105：写失败只记不炸环）。

    report_dir=None → 记 skipped（报告仍在返回体 rounds 内）；
    report_dir 给定时缺父目录自动建（调用方显式给路径，本模块绝不
    自建 create_run_dir——#144 家族 runs/ 写面纪律）。
    """
    if report_dir is None:
        round_report["report_write"] = {"ok": True, "skipped": True,
                                        "reason": "report_dir 未给"}
        return
    path = Path(report_dir) / (
        f"{REPORT_STEM}_{int(round_report['round']):03d}.json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(round_report, ensure_ascii=False, indent=1,
                       default=str),
            encoding="utf-8")
        report_files.append(str(path))
        round_report["report_write"] = {"ok": True, "path": str(path)}
    except Exception as exc:
        round_report["report_write"] = {"ok": False, "error": str(exc)}


def _report_fields(
    report_dir: str | Path | None, report_files: list[str],
) -> dict[str, Any]:
    """信封报告面字段（report_dir 未给时不加键——缺省键面最小）。"""
    if report_dir is None:
        return {}
    return {"report_dir": str(report_dir), "report_files": report_files}
