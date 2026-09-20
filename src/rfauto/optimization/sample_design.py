"""采样设计（v1 校准服务第 2 块）。

- taguchi_points：Taguchi 正交表（EMOptimizer TMTT 口径：正交表把全排列
  采样压缩 5-10 倍且保持两两因子水平均衡）。
- lhs_points：拉丁超立方（scipy qmc）——维数高/需要任意点数时的兜底。

约定：bounds 为 {param: (low, high)} 平铺 dict；返回值为
{"points": [{param: value}, ...], "design": 元数据}，3 水平表的水平取
[low, (low+high)/2, high]。
"""

from __future__ import annotations

from typing import Any

# 标准 Taguchi 正交表（列为因子位，行为试验号；值为水平号 0/1/2 或 0/1）
_TAGUCHI_ARRAYS: dict[tuple[str, int], list[list[int]]] = {
    ("3", 4): [  # L9(3^4)
        [0, 0, 0, 0], [0, 1, 1, 1], [0, 2, 2, 2],
        [1, 0, 1, 2], [1, 1, 2, 0], [1, 2, 0, 1],
        [2, 0, 2, 1], [2, 1, 0, 2], [2, 2, 1, 0],
    ],
    ("3", 13): [  # L27(3^13) 前 13 列（标准表）
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2],
        [1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 2, 2, 2],
        [1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 0, 0, 0],
        [1, 1, 1, 2, 2, 2, 2, 0, 0, 0, 1, 1, 1],
        [2, 2, 2, 0, 0, 0, 0, 2, 2, 2, 1, 1, 1],
        [2, 2, 2, 1, 1, 1, 1, 0, 0, 0, 2, 2, 2],
        [2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 0, 0, 0],
        [0, 1, 2, 0, 1, 2, 0, 1, 2, 0, 1, 2, 0],
        [0, 1, 2, 1, 2, 0, 1, 2, 0, 1, 2, 0, 1],
        [0, 1, 2, 2, 0, 1, 2, 0, 1, 2, 0, 1, 2],
        [1, 2, 0, 0, 1, 2, 1, 2, 0, 2, 0, 1, 1],
        [1, 2, 0, 1, 2, 0, 2, 0, 1, 0, 1, 2, 2],
        [1, 2, 0, 2, 0, 1, 0, 1, 2, 1, 2, 0, 0],
        [2, 0, 1, 0, 1, 2, 2, 0, 1, 1, 2, 0, 2],
        [2, 0, 1, 1, 2, 0, 0, 1, 2, 2, 0, 1, 0],
        [2, 0, 1, 2, 0, 1, 1, 2, 0, 0, 1, 2, 1],
        [0, 2, 1, 0, 2, 1, 0, 2, 1, 1, 0, 2, 1],
        [0, 2, 1, 1, 0, 2, 1, 0, 2, 2, 1, 0, 2],
        [0, 2, 1, 2, 1, 0, 2, 1, 0, 0, 2, 1, 0],
        [1, 0, 2, 0, 2, 1, 1, 1, 0, 2, 2, 0, 2],
        [1, 0, 2, 1, 0, 2, 2, 2, 1, 0, 0, 1, 0],
        [1, 0, 2, 2, 1, 0, 0, 0, 2, 1, 1, 2, 1],
        [2, 1, 0, 0, 2, 1, 2, 1, 0, 0, 1, 2, 2],
        [2, 1, 0, 1, 0, 2, 0, 2, 1, 1, 2, 0, 0],
        [2, 1, 0, 2, 1, 0, 1, 0, 2, 2, 0, 1, 1],
    ],
    ("2", 3): [  # L4(2^3)
        [0, 0, 0], [0, 1, 1], [1, 0, 1], [1, 1, 0],
    ],
    ("2", 7): [  # L8(2^7)
        [0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 1, 1, 1, 1],
        [0, 1, 1, 0, 0, 1, 1], [0, 1, 1, 1, 1, 0, 0],
        [1, 0, 1, 0, 1, 0, 1], [1, 0, 1, 1, 0, 1, 0],
        [1, 1, 0, 0, 1, 1, 0], [1, 1, 0, 1, 0, 0, 1],
    ],
    ("2", 15): [  # L16(2^15) 前 15 列（标准表）
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1],
        [0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1],
        [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0],
        [0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1],
        [0, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0],
        [0, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0],
        [0, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1],
        [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        [1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0],
        [1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0],
        [1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1],
        [1, 1, 0, 0, 1, 0, 1, 0, 1, 1, 0, 0, 1, 0, 1],
        [1, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0],
        [1, 1, 0, 1, 0, 1, 0, 0, 1, 1, 0, 1, 0, 1, 0],
        [1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1],
    ],
}


def _level_values(low: float, high: float, n_levels: int) -> list[float]:
    if n_levels == 2:
        return [low, high]
    mid = (low + high) / 2
    return [low, mid, high]


def taguchi_points(bounds: dict[str, tuple[float, float]],
                   n_levels: int = 3) -> dict[str, Any]:
    """Taguchi 正交采样点集。

    因子数超过当前表容量时按表容量截断（多余因子固定在中位水平）并记录
    在 design.truncated——高维场景的正经处理在 §4 三层对策（预筛后进表）。
    """
    if n_levels not in (2, 3):
        raise ValueError(f"n_levels 仅支持 2/3，收到 {n_levels}")
    names = sorted(bounds)
    array = None
    for (lvl, cap), rows in _TAGUCHI_ARRAYS.items():
        if lvl == str(n_levels) and len(names) <= cap and (
                array is None or cap < len(array[0])):
            array = rows
    truncated: list[str] = []
    if array is None:
        # 没有足够列数的表：可用表中最大者，溢出因子固定中位
        best_key = max(
            (k for k in _TAGUCHI_ARRAYS if k[0] == str(n_levels)),
            key=lambda k: k[1])
        array = _TAGUCHI_ARRAYS[best_key]
        truncated = names[best_key[1]:]
        names = names[:best_key[1]]
    levels = {n: _level_values(bounds[n][0], bounds[n][1], n_levels)
              for n in names}
    points = []
    for row in array:
        pt = {n: levels[n][row[i]] for i, n in enumerate(names)}
        for n in truncated:  # 截断因子固定中位
            pt[n] = (bounds[n][0] + bounds[n][1]) / 2
        points.append(pt)
    return {"points": points,
            "design": {"kind": "taguchi", "n_levels": n_levels,
                       "array_rows": len(array),
                       "truncated": truncated}}


def lhs_points(bounds: dict[str, tuple[float, float]], n_points: int,
               seed: int = 42, include: list[dict[str, float]] | None = None,
               min_dist: float = 0.0) -> dict[str, Any]:
    """拉丁超立方采样（归一化空间），可选排除与既有点过近的候选。"""
    from scipy.stats import qmc

    names = sorted(bounds)
    lower = [bounds[n][0] for n in names]
    upper = [bounds[n][1] for n in names]
    span = [max(u - lo, 1e-12) for lo, u in zip(lower, upper, strict=True)]
    sampler = qmc.LatinHypercube(d=len(names), seed=seed)
    unit = sampler.random(n=n_points)
    unit = qmc.scale(unit, lower, upper)
    points = []
    include_norm = [
        np_rel(p, names, lower, span) for p in (include or [])]
    for row in unit:
        pt = {n: float(row[i]) for i, n in enumerate(names)}
        if include and _too_close(pt, include_norm, names, span, min_dist):
            continue
        points.append(pt)
    return {"points": points,
            "design": {"kind": "lhs", "n_points": n_points, "seed": seed,
                       "skipped_close": n_points - len(points)}}


def np_rel(pt: dict[str, float], names: list[str],
           lower: list[float], span: list[float]) -> dict[str, float]:
    return {n: (pt[n] - lower[i]) / span[i] for i, n in enumerate(names)}


def _too_close(pt: dict[str, float], include_norm: list[dict[str, float]],
               names: list[str], span: list[float],
               min_dist: float) -> bool:
    if min_dist <= 0:
        return False
    for other in include_norm:
        d = math_sqrt(sum(
            (pt[n] - other.get(n, pt[n])) ** 2 for n in names))
        if d < min_dist:
            return True
    return False


def math_sqrt(x: float) -> float:
    return x ** 0.5
