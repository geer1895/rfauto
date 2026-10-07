"""XN-6 合成数据工厂（round19 P2，ge8c 席C6）——闭式内核工厂化产参数-响应数据集。

定位（round19 口径"MAPES 闭式内核工厂化——每模板自动产参数-响应数据集
（分布设计+漂移注入+泄漏防护），供 AI-2/3/4 与公开数据集锚三面消费"）：

- **分布设计**：numpy LHS（拉丁超立方，中心化分层 + 种子置换）——确定性
  可复现（同 seed 同数据，C4 可复现红线），零新依赖；
- **响应求值**：``response_fn(params) -> dict[str, float]`` **必须注入**——
  工厂本身零物理数字（铁律 7：数值只在确定性内核）。生产内核=注册表闭式
  计算器（``core.calculators.CALCULATOR_REGISTRY``）或 MAPES 解析代理
  （``optimization.surrogate.mapes_analytic``），由调用方按模板接线；
- **漂移注入**：响应级系统漂移（gain/offset）与参数级漂移（shift 占满量程
  比例），逐行显式落 ``drift`` 元数据（下游校准/回归消费面的鲁棒性考题）；
  无漂移行 drift=None——漂移是**合成标注**，不冒充实测；
- **泄漏防护**：train/eval 按**设计点**切分；eval 点与任一 train 点在归一化
  参数空间的 L2 距离 < ``min_dist`` 即判近邻泄漏 → 移出 eval 入
  ``excluded``（逐点带 reason，如实不静默）；切分确定性（种子置换）。

服务层 JSON 进出（规则 4）；负例（空参数域/非法响应/不可行配置）转
ok=False+errors，不抛穿。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "SYNTH_FACTORY_SCHEMA",
    "lhs_unit",
    "make_dataset",
]

#: 数据集 schema 标识（JSON 消费面稳定钉）。
SYNTH_FACTORY_SCHEMA = "rfauto-synthetic-factory-v1"

#: LHS 单位超立方响应函数契约：params dict → {metric: float}。
ResponseFn = Callable[[Mapping[str, float]], Mapping[str, float]]


def lhs_unit(n: int, d: int, rng: Any) -> Any:
    """n×d 中心化 LHS 单位样本（每维每层恰一点；确定性给定 rng）。"""
    import numpy as np

    if n < 1 or d < 1:
        raise ValueError("n/d 必须 ≥1")
    u = (np.arange(n) + 0.5) / n  # 层中心
    mat = np.empty((n, d))
    for j in range(d):
        col = rng.permutation(u)
        jitter = (rng.uniform(0, 1, n) - 0.5) / n  # 层内抖动保持分层不重叠
        mat[:, j] = col + jitter
    return np.clip(mat, 0.0, 1.0)


def _lhs_dataset(params_spec: Mapping[str, dict[str, float]], n: int,
                 seed: int) -> tuple[list[str], Any]:
    import numpy as np

    names = sorted(params_spec)
    lows = np.array([float(params_spec[p]["low"]) for p in names])
    highs = np.array([float(params_spec[p]["high"]) for p in names])
    rng = np.random.default_rng(seed)
    unit = lhs_unit(n, len(names), rng)
    mat = lows + unit * (highs - lows)
    return names, mat


def _drifted(value: float, gain: float, offset: float) -> float:
    return float(value) * float(gain) + float(offset)


def make_dataset(
    params_spec: Mapping[str, Mapping[str, float]],
    response_fn: ResponseFn,
    *,
    n_points: int = 32,
    seed: int = 0,
    drift: Mapping[str, Mapping[str, float]] | None = None,
    param_drift: Mapping[str, float] | None = None,
    split_frac: float = 0.7,
    min_dist: float = 1e-3,
) -> dict[str, Any]:
    """闭式内核 → 参数-响应合成数据集（train/eval 泄漏防护切分）。

    Args:
        params_spec: {param: {"low": l, "high": h}}（LHS 采样域）。
        response_fn: 确定性闭式内核（计算器/解析代理）；返回 {metric: float}。
        n_points: 设计点数（切分后 train≈n×split_frac）。
        seed: 全链种子（LHS+切分置换+漂移抖动均同源）。
        drift: {metric: {"gain": g, "offset": o}}——响应级系统漂移标注。
        param_drift: {param: fraction}——参数级漂移（满量程比例，同向平移）。
        split_frac: train 占比 (0,1)。
        min_dist: 归一化参数空间最小允许 train-eval 距离（近邻泄漏门）。

    Returns: {ok, schema, template?, n_points, n_train, n_eval, n_excluded,
        rows: [{point_id, params, response, response_raw?, drift, split}],
        excluded: [{point_id, reason}]}。
    """
    if not isinstance(params_spec, Mapping) or not params_spec:
        return error_envelope("params_spec 必须非空 mapping")
    for p, spec in params_spec.items():
        if not isinstance(spec, Mapping) or \
                "low" not in spec or "high" not in spec:
            return error_envelope(f"param {p!r} 缺 low/high")
        lo, hi = float(spec["low"]), float(spec["high"])
        if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
            return error_envelope(f"param {p!r} 界非法: [{lo}, {hi}]")
    if not callable(response_fn):
        return error_envelope("response_fn 必须可调用（确定性闭式内核）")
    n_points = int(n_points)
    if n_points < 4:
        return error_envelope("n_points 必须 ≥4（切分两侧非空）")
    if not 0.0 < float(split_frac) < 1.0:
        return error_envelope("split_frac 必须在 (0,1)")
    n_train = max(2, round(n_points * float(split_frac)))
    n_train = min(n_train, n_points - 2)  # eval 至少 2 点
    if float(min_dist) <= 0:
        return error_envelope("min_dist 必须 >0")

    try:
        names, mat = _lhs_dataset(params_spec, n_points, seed)
    except (KeyError, TypeError, ValueError) as exc:
        return error_envelope(f"采样失败: {exc}")

    import numpy as np

    # 切分置换（与 LHS 同源种子流——先 LHS 后切分，序列固定）
    rng = np.random.default_rng(seed + 1)
    order = rng.permutation(n_points)
    train_idx = set(order[:n_train].tolist())

    # 参数级漂移（满量程比例平移；作用于全部点，逐行标注）
    param_drift_eff: dict[str, float] = {}
    if param_drift:
        for p, frac in param_drift.items():
            if p not in params_spec:
                return error_envelope(f"param_drift 参数未登记: {p!r}")
            span = (float(params_spec[p]["high"]) -
                    float(params_spec[p]["low"]))
            param_drift_eff[str(p)] = float(frac) * span

    drift_eff: dict[str, dict[str, float]] = {}
    for metric, d in (drift or {}).items():
        gain = float(d.get("gain", 1.0))
        offset = float(d.get("offset", 0.0))
        if not (math.isfinite(gain) and math.isfinite(offset)):
            return error_envelope(f"drift[{metric!r}] 非有限")
        drift_eff[str(metric)] = {"gain": gain, "offset": offset}

    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    unit_train: list[Any] = []
    lows = np.array([float(params_spec[p]["low"]) for p in names])
    highs = np.array([float(params_spec[p]["high"]) for p in names])
    spans = highs - lows

    for i in range(n_points):
        raw_params = {p: float(mat[i, j]) for j, p in enumerate(names)}
        params = dict(raw_params)
        for p, shift in param_drift_eff.items():
            params[p] = params[p] + shift
        try:
            resp_raw = response_fn(params)
        except Exception as exc:  # 内核异常逐点如实入账（#105）
            excluded.append({"point_id": f"p{i:04d}",
                             "reason": f"response_fn raised: {exc}"})
            continue
        if not isinstance(resp_raw, Mapping) or not resp_raw:
            excluded.append({"point_id": f"p{i:04d}",
                             "reason": "response_fn 返回空/非 mapping"})
            continue
        resp: dict[str, float] = {}
        bad = False
        for k, v in resp_raw.items():
            fv = float(v) if not isinstance(v, bool) else math.nan
            if not math.isfinite(fv):
                excluded.append({"point_id": f"p{i:04d}",
                                 "reason": f"响应 {k!r} 非有限"})
                bad = True
                break
            resp[str(k)] = fv
        if bad:
            continue
        resp_drifted = {k: _drifted(v, d["gain"], d["offset"])
                        for k, v in resp.items()
                        if (d := drift_eff.get(k)) is not None}
        split = "train" if i in train_idx else "eval"
        unit_vec = (np.array([params[p] for p in names]) - lows) / spans
        if split == "train":
            unit_train.append(unit_vec)
            rows.append(_row(i, params, resp, resp_drifted, drift_eff,
                             param_drift_eff, split))
        else:
            # 泄漏门：与任一 train 点归一化 L2 < min_dist → 移出 eval
            dist = min(
                float(np.linalg.norm(unit_vec - t)) for t in unit_train
            ) if unit_train else math.inf
            if dist < float(min_dist):
                excluded.append({
                    "point_id": f"p{i:04d}",
                    "reason": f"near-duplicate of train (dist={dist:.3e} "
                              f"< min_dist={min_dist:g})"})
                continue
            rows.append(_row(i, params, resp, resp_drifted, drift_eff,
                             param_drift_eff, split))

    n_train_out = sum(1 for r in rows if r["split"] == "train")
    return ok_envelope(
        schema=SYNTH_FACTORY_SCHEMA,
        params=list(names),
        n_points=n_points,
        n_train=n_train_out,
        n_eval=sum(1 for r in rows if r["split"] == "eval"),
        n_excluded=len(excluded),
        rows=rows,
        excluded=excluded,
        drift={"response": dict(drift_eff), "param": dict(param_drift_eff)},
        note=("响应值全部来自注入的确定性闭式内核；drift 为合成标注"
              "（铁律 7）；同 seed 同 spec 逐位可复现"),
    )


def _row(i: int, params: dict[str, float], resp: dict[str, float],
         resp_drifted: dict[str, float], drift_eff: Mapping[str, Any],
         param_drift_eff: Mapping[str, float], split: str) -> dict[str, Any]:
    return {
        "point_id": f"p{i:04d}",
        "params": params,
        "response": resp_drifted if resp_drifted else resp,
        "response_raw": resp if resp_drifted else None,
        "drift": {
            "response": {k: dict(v) for k, v in drift_eff.items()
                         if k in resp_drifted} if resp_drifted else None,
            "param": dict(param_drift_eff) or None,
        } if (resp_drifted or param_drift_eff) else None,
        "split": split,
    }


def factory_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    """数据集 → 消费面摘要（每 metric 的 min/max/mean；确定性序）。"""
    if not result.get("ok"):
        return error_envelope("summary requires ok dataset")
    metrics: dict[str, list[float]] = {}
    for row in result.get("rows", []):
        for k, v in (row.get("response") or {}).items():
            metrics.setdefault(str(k), []).append(float(v))
    stats = {
        k: {"n": len(v), "min": min(v), "max": max(v),
            "mean": sum(v) / len(v)}
        for k, v in sorted(metrics.items())
    }
    return ok_envelope(n_metrics=len(stats), metrics=stats,
                       n_rows=sum(1 for _ in result.get("rows", [])))
