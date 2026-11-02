"""采样设计（v1 校准服务第 2 块，docs/surrogate_calibration_design.md §1）。

- taguchi_points：Taguchi 正交表（EMOptimizer TMTT 口径：正交表把全排列
  采样压缩 5-10 倍且保持两两因子水平均衡）。
- lhs_points：拉丁超立方（scipy qmc）——维数高/需要任意点数时的兜底。

约定：bounds 为 {param: (low, high)} 平铺 dict；返回值为
{"points": [{param: value}, ...], "design": 元数据}，3 水平表的水平取
[low, (low+high)/2, high]。

D1-2（审查批 2026-10-04，runs/review_ge8e/d1_opt_linkage/REPORT.md）：
L16(2^15)/L27(3^13) 硬编码表实测 35/105、32/78 列对非正交（两列组合
(a,b) 计数不等——"两两因子水平均衡"承诺失守，DOE 面交互效应混叠）。
全表改为**素数幂有限域线性型构造**程序化生成（rows=x∈GF(q)^m 均匀枚举、
columns=射影点 PG(m−1,q) 代表元、entry=v·x mod q）——列两两线性无关
⇒ 任意列对 (a,b) 组合格里逐格等频（OA(q^m,(q^m−1)/(q−1),q,2) 规范性质），
生成后由 ``_verify_linear_oa`` 自检，性质钉见 tests/unit/test_sample_design。
"""

from __future__ import annotations

from itertools import combinations, product
from typing import Any


def _linear_oa(q: int, m: int) -> list[list[int]]:
    """线性正交表 OA(q^m, (q^m−1)/(q−1), q, 2)（素数 q 有限域构造）。

    - 行：x ∈ GF(q)^m 的均匀枚举（q 进制计数序），共 q^m 行；
    - 列：射影点 PG(m−1,q)=非零向量按"首非零坐标归一为 1"取代表元，
      共 (q^m−1)/(q−1) 列；
    - 表项：entry = v·x mod q（标准内积）。

    正交性证明骨架：任两代表元射影不同 ⇒ 线性无关 ⇒ (u·x, v·x) 在均匀
    x 下于 GF(q)² 均匀 ⇒ 任意两列组合 (a,b) 各恰 q^(m−2) 次（2 水平
    q=2、3 水平 q=3 均为素数域，逆元 pow(c,-1,q) 有限）。
    """
    reps_dedup: dict[tuple[int, ...], None] = {}
    for v in product(range(q), repeat=m):
        if any(c != 0 for c in v):
            first = next(i for i, c in enumerate(v) if c != 0)
            inv = pow(v[first], -1, q)
            reps_dedup.setdefault(tuple((c * inv) % q for c in v))
    reps = list(reps_dedup)
    rows = []
    for x in product(range(q), repeat=m):
        rows.append([sum(v[i] * x[i] for i in range(m)) % q for v in reps])
    return rows


def _verify_linear_oa(array: list[list[int]], q: int) -> list[tuple[int, int]]:
    """规范性质自检（D1-2）：值域 GF(q)、任意两列组合逐格等频。

    供生成端与测试两侧调用（生成端不 assert 不炸 import；测试钉强制）。
    返回违规记录列表（(-1,-1)=值域违规；(c1,c2)=该列对组合计数不等；
    空列表=正交性质成立）。
    """
    import numpy as np

    a = np.asarray(array, dtype=int)
    n_rows, n_cols = a.shape
    problems: list[tuple[int, int]] = []
    if set(np.unique(a).tolist()) != set(range(q)):
        problems.append((-1, -1))
    for c1, c2 in combinations(range(n_cols), 2):
        counts: dict[tuple[int, int], int] = {}
        for r in range(n_rows):
            key = (int(a[r, c1]), int(a[r, c2]))
            counts[key] = counts.get(key, 0) + 1
        if len(counts) != q * q or len(set(counts.values())) != 1:
            problems.append((c1, c2))
    return problems


#: 标准 Taguchi 正交表（列为因子位，行为试验号；值为水平号 0/1 或 0/1/2）。
#: D1-2 起=``_linear_oa`` 程序化生成（键与容量不变，API 零改动）；
#: 坏表已撤（L16 35/105、L27 32/78 列对非正交，实测见本模块 docstring）。
_TAGUCHI_ARRAYS: dict[tuple[str, int], list[list[int]]] = {
    ("2", 3): _linear_oa(2, 2),    # L4(2^3)
    ("2", 7): _linear_oa(2, 3),    # L8(2^7)
    ("2", 15): _linear_oa(2, 4),   # L16(2^15)
    ("3", 4): _linear_oa(3, 2),    # L9(3^4)
    ("3", 13): _linear_oa(3, 3),   # L27(3^13)
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
