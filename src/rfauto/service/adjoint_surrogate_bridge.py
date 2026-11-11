"""代理梯度观测量桥（T-Q21 通道 2，aurora_q R6 吸收）：伴随梯度范数作为主动学习采样优先级。

定位（runs/aurora_q/PLAN_DRAFT.md 〇i T-Q21；ADJOINT.md §4.3 互补机制 ②）
====================================================================
R6 结论：伴随梯度不是替代黑箱优化，而是**新增一种高价值观测量**——
|∇f| 大处信息密度高，可作为主动学习加密点选择的优先级信号。本模块把
可微通道的梯度接进代理主动学习采样面：

- **侦察结论（2026-11-05 实读 service/active_learning.py）**：既有准则面
  **不是注册表形态**——采集函数=``acquisition_scores`` 分派函数 +
  ``ACQUISITION_KINDS=("lcb","ucb","ei","sigma")`` 模块常量（T-N9 三族）。
  按任务书分支"不存在则独立函数+调用方组合示例"执行：本模块零改
  active_learning.py（既有准则零改——lcb/ucb/ei/sigma 行为零变），
  梯度范数准则以独立纯函数落位，组合面消费 estimate_uncertainty 的
  契约形状（``{"params","mean","sigma","score"}`` 列表）。

- **注入缝**：``gradient_fn: params(dict) → 梯度``——params 为 bounds 键名
  字典，梯度可以是同键名字典或与 ``sorted(bounds)`` 对齐的序列。内核侧
  确定性（JAX 伴随/numpy 解析/fdtd_diff 包装——规则 7，梯度数字只出自
  确定性内核；本模块只做范数/归一化/排名的确定性数学）。LLM 零参与。

- **确定性纪律**：纯函数、同输入逐位同输出；排名并列按参数元组字典序
  定序（与 active_learning.score_exploration_candidates 同口径，跨进程
  可复现）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "ADJOINT_BRIDGE_SCHEMA_VERSION",
    "gradient_informed_sampling",
    "gradient_norm_priorities",
]

#: 代理梯度桥 schema 版本（recipe_version 与 schema_version 语义区分，#106）
ADJOINT_BRIDGE_SCHEMA_VERSION = "1.0"

#: 组合打分的缺省权重（σ 不确定度 vs 梯度范数各半；显式传参可旋）。
DEFAULT_WEIGHT_SIGMA = 0.5
DEFAULT_WEIGHT_GRAD = 0.5


def _resolve_gradient_vector(
    gradient_fn: Callable[[dict[str, float]], Any],
    point: dict[str, float],
    names: list[str],
) -> np.ndarray:
    """注入缝归一：kernel 梯度（同键名字典或按 sorted(bounds) 对齐的序列）
    → 与 names 对齐的向量。缺键/超键/长度错配显式 ValueError（契约破坏
    不静默补 0——#316 多报不放过）。"""
    raw = gradient_fn(dict(point))
    if isinstance(raw, Mapping):
        missing = [n for n in names if n not in raw]
        if missing:
            raise ValueError(f"kernel 梯度缺参数键: {missing}（bounds 键集: {names}）")
        extra = [k for k in raw if k not in set(names)]
        if extra:
            raise ValueError(f"kernel 梯度含 bounds 外键: {sorted(extra)}")
        try:
            vec = np.array([float(raw[n]) for n in names], dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"kernel 梯度含非数值项: {exc}") from exc
    else:
        arr = np.asarray(raw, dtype=float).reshape(-1)
        if arr.size != len(names):
            raise ValueError(
                f"kernel 梯度序列长度 {arr.size} != 参数维 {len(names)}"
                "（须与 sorted(bounds) 对齐）")
        vec = arr
    if not np.all(np.isfinite(vec)):
        raise ValueError("kernel 梯度含非有限值（内核产出垃圾，不进采样面）")
    return vec


def gradient_norm_priorities(
    bounds: Mapping[str, Sequence[float]],
    candidates: Sequence[dict[str, float]],
    gradient_fn: Callable[[dict[str, float]], Any],
    *,
    top_k: int | None = None,
) -> dict[str, Any]:
    """梯度范数采样准则（独立纯函数）：|∇f| 大者优先加密。

    bounds: 参数名 → (lo, hi)（只取键集与排序，不做域裁剪——候选点由
    调用方生成，如既有 LHS 池）。candidates: 参数字典列表。gradient_fn:
    注入缝（见模块 docstring）。score = ‖∇f(params)‖₂（越大越该采样）。

    返回信封 ok=True + ranked（score 降序，并列按参数元组字典序——跨进程
    可复现）+ top_k 截前；空候选=ok=True 空 ranked（无点可排不是错误）。
    内核契约破坏（缺键/非有限/形状错配）→ ok=False error 信封。
    """
    if not bounds:
        return error_envelope("搜索空间为空（bounds 缺失）")
    names = sorted(bounds)
    cands = [dict(c) for c in (candidates or [])]
    for c in cands:
        if not isinstance(c, dict):
            return error_envelope(f"候选点必须是参数字典: {c!r}")
    if top_k is not None and int(top_k) < 0:
        return error_envelope(f"top_k 必须 ≥0: {top_k!r}")

    ranked: list[dict[str, Any]] = []
    for c in cands:
        try:
            vec = _resolve_gradient_vector(gradient_fn, c, names)
        except ValueError as exc:
            return error_envelope(f"候选点 {c!r} 梯度解析失败: {exc}")
        norm = float(np.linalg.norm(vec))
        if not math.isfinite(norm):
            return error_envelope(f"候选点 {c!r} 梯度范数非有限")
        ranked.append({"params": c, "gradient_norm": norm})

    ranked.sort(key=lambda r: (-r["gradient_norm"],
                               tuple(sorted(r["params"].items()))))
    if top_k is not None:
        ranked = ranked[: int(top_k)]
    return ok_envelope(
        schema_version=ADJOINT_BRIDGE_SCHEMA_VERSION,
        criterion="gradient_norm",
        n_candidates=len(cands),
        param_names=names,
        ranked=ranked,
        note="score=‖∇f‖₂（确定性内核梯度，规则 7）；越大信息密度越高，"
             "优先加密；与既有 lcb/ucb/ei/sigma 准则零耦合（active_learning 未改动）",
    )


def _minmax(values: np.ndarray) -> np.ndarray:
    """min-max 归一化到 [0,1]；跨度为 0（常数向量）→ 全 0.5（中性，
    不给常数信号伪造区分度）。"""
    if values.size == 0:
        return values
    lo = float(values.min())
    hi = float(values.max())
    if hi - lo <= 0.0:
        return np.full(values.size, 0.5)
    return (values - lo) / (hi - lo)


def gradient_informed_sampling(
    bounds: Mapping[str, Sequence[float]],
    uncertainty_points: Sequence[Mapping[str, Any]],
    gradient_fn: Callable[[dict[str, float]], Any],
    *,
    weight_sigma: float = DEFAULT_WEIGHT_SIGMA,
    weight_grad: float = DEFAULT_WEIGHT_GRAD,
    top_k: int | None = None,
) -> dict[str, Any]:
    """组合示例：既有 σ 准则 × 梯度范数准则的加权合成排名。

    uncertainty_points: **active_learning.estimate_uncertainty 输出契约形状**
    （``points=[{"params": {...}, "mean": {...}, "sigma": {...}, "score": float}]``，
    本模块只读 params 与 sigma 之和，不改既有准则任何行为）。合成
    score = w_sigma·norm(Σσ) + w_grad·norm(‖∇f‖)（两项各自 min-max 归一化；
    常数向量记 0.5 中性）。权重非负且不限和为 1（显式旋钮，负权重=契约
    破坏）。返回信封含 ranked 与 weight 回显；零改 active_learning.py。
    """
    if not bounds:
        return error_envelope("搜索空间为空（bounds 缺失）")
    if not (weight_sigma >= 0.0 and weight_grad >= 0.0):
        return error_envelope(
            f"权重必须非负: weight_sigma={weight_sigma!r}, weight_grad={weight_grad!r}")
    if weight_sigma + weight_grad <= 0.0:
        return error_envelope("权重之和必须为正（全零权重无判读意义）")
    points = [dict(p) for p in (uncertainty_points or [])]
    if not points:
        return ok_envelope(
            schema_version=ADJOINT_BRIDGE_SCHEMA_VERSION,
            criterion="sigma_plus_gradient_norm",
            weight_sigma=float(weight_sigma),
            weight_grad=float(weight_grad),
            ranked=[],
            note="既有准则输出为空：无可组合点（不是错误）")

    names = sorted(bounds)
    sigmas = np.zeros(len(points), dtype=float)
    grad_norms = np.zeros(len(points), dtype=float)
    for i, pt in enumerate(points):
        params = pt.get("params")
        if not isinstance(params, dict):
            return error_envelope(f"第 {i} 点缺 params 字典: {pt!r}")
        sigma_map = pt.get("sigma") or {}
        if not isinstance(sigma_map, dict):
            return error_envelope(f"第 {i} 点 sigma 形态非法: {sigma_map!r}")
        vals = [float(v) for v in sigma_map.values()
                if isinstance(v, (int, float)) and math.isfinite(float(v))]
        sigmas[i] = sum(vals)
        try:
            vec = _resolve_gradient_vector(gradient_fn, params, names)
        except ValueError as exc:
            return error_envelope(f"第 {i} 点梯度解析失败: {exc}")
        grad_norms[i] = float(np.linalg.norm(vec))

    combined = (float(weight_sigma) * _minmax(sigmas)
                + float(weight_grad) * _minmax(grad_norms))
    ranked = []
    for i, pt in enumerate(points):
        ranked.append({
            "params": dict(pt.get("params") or {}),
            "sigma_sum": float(sigmas[i]),
            "gradient_norm": float(grad_norms[i]),
            "combined_score": float(combined[i]),
        })
    ranked.sort(key=lambda r: (-r["combined_score"],
                               tuple(sorted(r["params"].items()))))
    if top_k is not None:
        if int(top_k) < 0:
            return error_envelope(f"top_k 必须 ≥0: {top_k!r}")
        ranked = ranked[: int(top_k)]
    return ok_envelope(
        schema_version=ADJOINT_BRIDGE_SCHEMA_VERSION,
        criterion="sigma_plus_gradient_norm",
        weight_sigma=float(weight_sigma),
        weight_grad=float(weight_grad),
        n_points=len(points),
        ranked=ranked,
        note="组合示例：既有 estimate_uncertainty 契约形状的 σ 分数 × 梯度范数"
             "（R6 §4.3 机制②）；active_learning 既有准则零改",
    )
