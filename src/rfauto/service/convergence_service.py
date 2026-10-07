"""OP-10：优化收敛诊断面（round16:211，P3/S）。

三件能力，全部确定性内核（铁律 7：不涉及任何 LLM/网络）：
- ``duplicate_evals`` —— n_duplicate_evals：参数向量完全重复的评估计数
  （批采样/TPE 扎堆/缓存旁路故障的直观指纹）；
- ``improvement_rate`` —— best-so-far 序列的改进事件率与相对改进量；
- ``parallel_coordinate_figure`` —— optuna 5.0 并行坐标图封装。

**optuna 5.0.0 API（2026-10-03 venv 实测，非臆写）**：
- ``optuna.visualization.plot_parallel_coordinate(study, params=None, *,
  target=None, target_name='Objective Value') -> plotly go.Figure``
  （本机 plotly 7.1.0 已安装，调用返回真实 Figure 对象，零网络）。

输入口径：既接受 ``optuna.study.Study``，也接受裸 trial 记录序列
（``{"params": {...}, "value": float}`` 映射）——数据集/回放面无 optuna
实例时可复用同一诊断。重复判定 = 参数键集相同且逐键浮点完全相等
（"同一点被重复评估"的标准语义；近似点不计入，宁可少报不虚报）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from rfauto.service.envelope import ok_envelope

__all__ = [
    "convergence_report",
    "duplicate_evals",
    "improvement_rate",
    "parallel_coordinate_figure",
]


def _completed_trials(source: Any) -> list[dict[str, Any]]:
    """Study/记录序列 → 统一 [{number, params, value}]（按评估序排列）。

    Study 输入只取 TrialState.COMPLETE（failed/pruned/running 不进收敛
    统计——它们没有可信目标值）；记录序列输入要求 value 为有限数值。
    """
    rows: list[tuple[int, dict[str, float], float]] = []
    if hasattr(source, "get_trials"):
        import optuna

        for t in source.get_trials(
                states=(optuna.trial.TrialState.COMPLETE,), deepcopy=False):
            if t.value is None:
                continue
            rows.append((int(t.number),
                         {k: float(v) for k, v in dict(t.params).items()},
                         float(t.value)))
    elif isinstance(source, Sequence):
        for i, item in enumerate(source):
            if not isinstance(item, Mapping):
                raise TypeError(f"trial 记录 #{i} 不是映射: {type(item).__name__}")
            value = item.get("value")
            if value is None or value != value or value in (float("inf"), float("-inf")):
                continue
            rows.append((int(item.get("number", i)),
                         {k: float(v) for k, v in dict(item.get("params") or {}).items()},
                         float(value)))
    else:
        raise TypeError(
            f"不支持的数据源: {type(source).__name__}（optuna Study 或记录序列）")
    rows.sort(key=lambda r: r[0])
    return [{"number": n, "params": p, "value": v} for n, p, v in rows]


def duplicate_evals(source: Any) -> dict[str, Any]:
    """n_duplicate_evals：与更早 trial 参数向量完全重复的评估计数。

    返回 ``{ok, n_evals, n_duplicate_evals, duplicate_rate, groups}``；
    groups 为重复组（每组 ≥2 个 trial number，按首现序）。空输入 ok=False
    （拒绝空跑，防空转绿）。
    """
    rows = _completed_trials(source)
    if not rows:
        return {"ok": False, "n_evals": 0, "n_duplicate_evals": 0,
                "duplicate_rate": 0.0, "groups": [],
                "errors": ["无已完成 trial，收敛诊断拒绝空跑"]}
    seen: dict[tuple, int] = {}
    dup_groups: dict[tuple, list[int]] = {}
    n_dup = 0
    for row in rows:
        key = tuple(sorted(row["params"].items()))
        if key in seen:
            n_dup += 1
            dup_groups.setdefault(key, [seen[key]]).append(row["number"])
        else:
            seen[key] = row["number"]
    return ok_envelope(
        n_evals=len(rows),
        n_duplicate_evals=n_dup,
        duplicate_rate=n_dup / len(rows),
        groups=sorted(dup_groups.values()),
        errors=[],
    )


def improvement_rate(source: Any) -> dict[str, Any]:
    """best-so-far 改进率：改进事件率 + 首/末 best + 相对改进量。

    改进事件 = 第 2 个起 completed trial 的目标值严格小于此前最小值
    （首个 trial 是基线确立，不计事件——基线≠改进）。
    ``relative_improvement = (best_first - best_last) / |best_first|``；
    best_first=0 时如实 None（不除零不伪造，#122）。
    """
    rows = _completed_trials(source)
    if not rows:
        return {"ok": False, "n_evals": 0, "improvement_events": 0,
                "improvement_rate": 0.0, "best_first": None, "best_last": None,
                "relative_improvement": None, "best_so_far": [],
                "errors": ["无已完成 trial，收敛诊断拒绝空跑"]}
    best = float("inf")
    best_series: list[float] = []
    events = 0
    for i, row in enumerate(rows):
        v = row["value"]
        if v < best:
            # 首个 completed trial 是基线确立，不计改进事件（基线≠改进）
            if i > 0:
                events += 1
            best = v
        best_series.append(best)
    best_first, best_last = best_series[0], best_series[-1]
    rel = (best_first - best_last) / abs(best_first) if best_first != 0 else None
    return ok_envelope(
        n_evals=len(rows),
        improvement_events=events,
        improvement_rate=events / len(rows),
        best_first=best_first,
        best_last=best_last,
        relative_improvement=rel,
        best_so_far=best_series,
        errors=[],
    )


def convergence_report(source: Any) -> dict[str, Any]:
    """聚合诊断：duplicate_evals + improvement_rate 单次调用双产出。"""
    dup = duplicate_evals(source)
    imp = improvement_rate(source)
    return {
        "ok": bool(dup.get("ok") and imp.get("ok")),
        "duplicates": dup,
        "improvement": imp,
        "errors": list(dup.get("errors") or []) + list(imp.get("errors") or []),
    }


def parallel_coordinate_figure(
    study: Any,
    params: list[str] | None = None,
    *,
    target: Any = None,
    target_name: str = "Objective Value",
) -> Any:
    """optuna 5.0 并行坐标图封装（venv 实测签名，见模块 docstring）。

    返回 plotly ``go.Figure``（零网络渲染数据对象）；无已完成 trial 时
    optuna 自身会告警并返回空 figure——调用方按需自判。plotly 缺失时抛
    ImportError 由调用方转诚实降级（本仓 plotly 7.1.0 在装）。
    """
    from optuna.visualization import plot_parallel_coordinate

    return plot_parallel_coordinate(study, params=params, target=target,
                                    target_name=target_name)
