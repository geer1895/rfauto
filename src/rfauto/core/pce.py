"""D8 稀疏多项式混沌展开（PCE）：Sobol 系数直读 + worst-case + 设计中心化。

依据
----
- 稀疏 PCE（ChaosPy/OpenTURNS 思路）
  →Sobol 指数直读（较 Saltelli 采样省 1-2 量级）+ worst-case 角分析 +
  设计中心化（良率最大化）；验收口径 = patch 公差问题 PCE-Sobol vs 既有
  Saltelli 互证 ±10%。
- core 零依赖叶子约束（.importlinter）：只依赖 numpy，不装 chaospy/openturns，
  不 import optimization/sensitivity（互证在测试里做，#118）。

机制（纯 numpy，确定性）
------------------------
1. 一维正交归一基：
   - Legendre（均匀输入）：psi_n(xi)=sqrt(2n+1)*P_n(xi)，xi∈[-1,1] 上
     E[psi_m psi_n]=delta_mn；
   - Hermite（正态输入）：psi_n(xi)=He_n(xi)/sqrt(n!)，xi~N(0,1) 上
     E[psi_m psi_n]=delta_mn（概率论家 Hermite）。
   多维基 = 各维基函数乘积；多指标按 graded-lex（总阶升序、组内字典序）确定。
2. 稀疏回归：OMP（正交匹配追踪，确定性并列取最小下标），常数项强制入选；
   method="ls" 为全基最小二乘。停止条件 = 残差 2 范数 <= tol 或非零项达
   max_terms。
3. Sobol 直读（系数闭式，无需再采样）：
   V = sum_{alpha != 0} c_alpha^2；
   S1_i = sum_{alpha: a_i>0, a_j=0 (j!=i)} c_alpha^2 / V；
   ST_i = sum_{alpha: a_i>0} c_alpha^2 / V。
   输入独立 + 基正交归一 ⇒ 系数平方和即该子空间的方差贡献。
4. worst-case：corner_worst_case 穷举容差角点（均匀=low/high，正态=mean±kσ）；
   worst_case 在 PCE 上做多起点确定性 pattern search（可命中内部极值）。
5. 设计中心化：容差箱确定性网格良率 + 坐标 pattern search 偏移设计中心。

诚实边界
--------
- PCE 是全局多项式代理；强不连续/多峰/窄带谐振（如 patch 谷深）收敛慢，
  Sobol 直读反映的是**代理**的方差分解，代理不准则指数不准。
- 本模块不读 runs/、不联网、不依赖 scipy/optuna（core 零依赖叶子约束）。
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "PCEModel",
    "build_design_matrix",
    "corner_worst_case",
    "design_centering",
    "fit_pce",
    "hermite_orthonormal",
    "legendre_orthonormal",
    "multi_indices",
    "omp_fit",
    "orthonormal_1d",
    "pce_sobol",
    "tolerance_yield",
    "worst_case",
]

# ---------------------------------------------------------------------------
# 参数规格解析：{name: {"low","high"}} -> 均匀；{name: {"mean","std"}} -> 正态
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Param:
    name: str
    kind: str  # "legendre" | "hermite"
    loc: float  # 均匀=(low+high)/2；正态=mean
    scale: float  # 均匀=(high-low)/2；正态=std
    low: float  # 设计容许下界（正态为 loc-3*scale）
    high: float  # 设计容许上界（正态为 loc+3*scale）


def _parse_specs(param_specs: Mapping[str, Mapping[str, float]]) -> tuple[list[str], list[_Param]]:
    if not isinstance(param_specs, Mapping) or len(param_specs) == 0:
        raise ValueError("param_specs must be a non-empty mapping")
    names = sorted(param_specs.keys())
    params: list[_Param] = []
    for name in names:
        spec = param_specs[name]
        if not isinstance(spec, Mapping):
            raise ValueError(f"param spec for {name!r} must be a mapping")
        has_interval = "low" in spec or "high" in spec
        has_moment = "mean" in spec or "std" in spec
        if has_interval and has_moment:
            raise ValueError(f"param spec for {name!r} mixes interval and moment keys")
        if has_interval:
            if "low" not in spec or "high" not in spec:
                raise ValueError(f"param spec for {name!r} needs both 'low' and 'high'")
            low = float(spec["low"])
            high = float(spec["high"])
            if not np.isfinite(low) or not np.isfinite(high) or high <= low:
                raise ValueError(f"param spec for {name!r} needs finite low < high")
            params.append(
                _Param(name, "legendre", 0.5 * (low + high), 0.5 * (high - low), low, high)
            )
        elif has_moment:
            if "mean" not in spec or "std" not in spec:
                raise ValueError(f"param spec for {name!r} needs both 'mean' and 'std'")
            mean = float(spec["mean"])
            std = float(spec["std"])
            if not np.isfinite(mean) or not np.isfinite(std) or std <= 0.0:
                raise ValueError(f"param spec for {name!r} needs finite mean and std > 0")
            params.append(
                _Param(name, "hermite", mean, std, mean - 3.0 * std, mean + 3.0 * std)
            )
        else:
            raise ValueError(
                f"param spec for {name!r} must contain low/high (uniform) or mean/std (normal)"
            )
    return names, params


# ---------------------------------------------------------------------------
# 一维正交归一基
# ---------------------------------------------------------------------------


def legendre_orthonormal(n_max: int, x: Any) -> np.ndarray:
    """正交归一 Legendre 基（在 xi~U(-1,1) 下），返回 shape (n_max+1,) + x.shape。"""
    if n_max < 0:
        raise ValueError("n_max must be >= 0")
    xa = np.asarray(x, dtype=float)
    flat = xa.ravel()
    polys = np.empty((n_max + 1, flat.size), dtype=float)
    polys[0] = 1.0
    if n_max >= 1:
        polys[1] = flat
    for n in range(1, n_max):
        polys[n + 1] = ((2 * n + 1) * flat * polys[n] - n * polys[n - 1]) / (n + 1)
    polys *= np.sqrt(2.0 * np.arange(n_max + 1) + 1.0)[:, None]
    return polys.reshape((n_max + 1, *xa.shape))


def hermite_orthonormal(n_max: int, x: Any) -> np.ndarray:
    """正交归一概率论家 Hermite 基（在 xi~N(0,1) 下）。"""
    if n_max < 0:
        raise ValueError("n_max must be >= 0")
    xa = np.asarray(x, dtype=float)
    flat = xa.ravel()
    polys = np.empty((n_max + 1, flat.size), dtype=float)
    polys[0] = 1.0
    if n_max >= 1:
        polys[1] = flat
    for n in range(1, n_max):
        polys[n + 1] = flat * polys[n] - n * polys[n - 1]
    norm = np.array([1.0 / math.sqrt(math.factorial(n)) for n in range(n_max + 1)], dtype=float)
    polys *= norm[:, None]
    return polys.reshape((n_max + 1, *xa.shape))


def orthonormal_1d(kind: str, n_max: int, x: Any) -> np.ndarray:
    """按 kind 分派一维正交归一基。"""
    if kind == "legendre":
        return legendre_orthonormal(n_max, x)
    if kind == "hermite":
        return hermite_orthonormal(n_max, x)
    raise ValueError(f"unknown basis kind: {kind!r}")


# ---------------------------------------------------------------------------
# 多指标与设计矩阵
# ---------------------------------------------------------------------------


def _compositions(total: int, dim: int) -> list[tuple[int, ...]]:
    if dim == 1:
        return [(total,)]
    rows: list[tuple[int, ...]] = []
    for first in range(total + 1):
        for rest in _compositions(total - first, dim - 1):
            rows.append((first, *rest))
    return rows


def multi_indices(dim: int, degree: int) -> np.ndarray:
    """总阶截断的多指标集：graded-lex 排序，行 0 为全零（常数项）。"""
    if dim < 1:
        raise ValueError("dim must be >= 1")
    if degree < 0:
        raise ValueError("degree must be >= 0")
    rows: list[tuple[int, ...]] = []
    for total in range(degree + 1):
        rows.extend(_compositions(total, dim))
    return np.asarray(rows, dtype=int)


def build_design_matrix(
    kinds: Sequence[str],
    canonical: Any,
    degree: int,
    indices: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """构造 PCE 设计矩阵。

    Args:
        kinds: 每维基类型（"legendre"/"hermite"）。
        canonical: (N, d) 规范空间样本。
        degree: 总阶截断。
        indices: 可选多指标集（默认 multi_indices(d, degree)）。

    Returns: (indices, A)，A 第 0 列恒为 1（常数项）。
    """
    xa = np.asarray(canonical, dtype=float)
    if xa.ndim == 1:
        xa = xa.reshape(1, -1)
    if xa.ndim != 2:
        raise ValueError("canonical must be a 1-D or 2-D array")
    dim = xa.shape[1]
    if len(kinds) != dim:
        raise ValueError("kinds length must match canonical columns")
    if degree < 0:
        raise ValueError("degree must be >= 0")
    if indices is None:
        idx = multi_indices(dim, degree)
    else:
        idx = np.asarray(indices, dtype=int)
        if idx.ndim != 2 or idx.shape[1] != dim:
            raise ValueError("indices shape incompatible with canonical columns")
    bases = np.empty((dim, degree + 1, xa.shape[0]), dtype=float)
    for j, kind in enumerate(kinds):
        bases[j] = orthonormal_1d(kind, degree, xa[:, j])
    design = np.ones((xa.shape[0], idx.shape[0]), dtype=float)
    for t in range(idx.shape[0]):
        for j in range(dim):
            a = int(idx[t, j])
            if a:
                design[:, t] *= bases[j, a]
    return idx, design


# ---------------------------------------------------------------------------
# 稀疏回归：OMP
# ---------------------------------------------------------------------------


def omp_fit(
    design: Any,
    target: Any,
    *,
    max_terms: int | None = None,
    tol: float = 0.0,
) -> dict[str, Any]:
    """正交匹配追踪（确定性）。

    Args:
        design: (N, P) 设计矩阵，**第 0 列必须是常数项**。
        target: (N,) 观测值。
        max_terms: 最多入选的非常数项数（默认 P-1）。
        tol: 残差 2 范数停止阈值（默认 0 精确拟合）。

    Returns: {"selected", "coeffs", "residual_norm", "n_terms"}；coeffs 含常数项。
    """
    a = np.asarray(design, dtype=float)
    y = np.asarray(target, dtype=float).ravel()
    if a.ndim != 2:
        raise ValueError("design must be 2-D")
    if a.shape[0] != y.size:
        raise ValueError("design rows must match target length")
    if a.shape[1] < 1:
        raise ValueError("design must contain at least the constant column")
    n_candidates = a.shape[1] - 1
    if max_terms is None:
        max_terms = n_candidates
    max_terms = int(max_terms)
    if max_terms < 0:
        raise ValueError("max_terms must be >= 0")
    max_terms = min(max_terms, n_candidates)

    y_mean = float(np.mean(y))
    y_centered = y - y_mean
    residual = y_centered.copy()
    candidates = list(range(1, a.shape[1]))
    selected: list[int] = []
    while len(selected) < max_terms and float(np.linalg.norm(residual)) > tol:
        if not candidates:
            break
        corr = a[:, candidates].T @ residual
        k = int(np.argmax(np.abs(corr)))
        if abs(float(corr[k])) <= 0.0:
            break
        selected.append(candidates.pop(k))
        cols = [0, *selected]
        coeffs, *_ = np.linalg.lstsq(a[:, cols], y, rcond=None)
        residual = y - a[:, cols] @ coeffs

    cols = [0, *selected]
    coeffs, *_ = np.linalg.lstsq(a[:, cols], y, rcond=None)
    full = np.zeros(a.shape[1], dtype=float)
    full[cols] = coeffs
    residual = y - a[:, cols] @ coeffs
    return {
        "selected": selected,
        "coeffs": full,
        "residual_norm": float(np.linalg.norm(residual)),
        "n_terms": len(selected),
    }


# ---------------------------------------------------------------------------
# PCE 模型
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class PCEModel:
    """拟合好的稀疏 PCE 代理，支持预测与 Sobol 系数直读。"""

    names: list[str]
    kinds: list[str]
    locs: np.ndarray
    scales: np.ndarray
    lows: np.ndarray
    highs: np.ndarray
    degree: int
    indices: np.ndarray
    coeffs: np.ndarray
    active: np.ndarray
    n_samples: int
    r2: float
    method: str
    tol: float

    @property
    def dim(self) -> int:
        return len(self.names)

    @property
    def variance(self) -> float:
        mask = ~np.all(self.indices == 0, axis=1)
        return float(np.sum(self.coeffs[mask] ** 2))

    @property
    def mean(self) -> float:
        zero = np.all(self.indices == 0, axis=1)
        return float(np.sum(self.coeffs[zero]))

    def _as_vector(self, params: Any) -> np.ndarray:
        if isinstance(params, Mapping):
            missing = [n for n in self.names if n not in params]
            if missing:
                raise ValueError(f"missing parameter(s): {missing}")
            return np.array([float(params[n]) for n in self.names], dtype=float)
        arr = np.asarray(params, dtype=float)
        if arr.shape != (self.dim,):
            raise ValueError(f"expected {self.dim} values, got shape {arr.shape}")
        return arr

    def to_canonical(self, params: Any) -> np.ndarray:
        return (self._as_vector(params) - self.locs) / self.scales

    def from_canonical(self, canonical: Any) -> np.ndarray:
        return self.locs + self.scales * np.asarray(canonical, dtype=float)

    def predict_canonical(self, canonical: Any) -> np.ndarray:
        xa = np.asarray(canonical, dtype=float)
        if xa.ndim == 1:
            xa = xa.reshape(1, -1)
        _, design = build_design_matrix(self.kinds, xa, self.degree, self.indices)
        return design @ self.coeffs

    def predict(self, params: Any) -> float:
        xi = self.to_canonical(params).reshape(1, -1)
        return float(self.predict_canonical(xi)[0])

    def predict_many(self, params_list: Sequence[Any]) -> np.ndarray:
        rows = np.array([self._as_vector(p) for p in params_list], dtype=float)
        return self.predict_canonical((rows - self.locs) / self.scales)

    def active_terms(self) -> list[tuple[int, ...]]:
        return [tuple(int(v) for v in self.indices[t]) for t in np.nonzero(self.active)[0]]

    def sobol(self) -> dict[str, dict[str, float]]:
        """从系数直读一阶/总效应 Sobol 指数（独立输入）。"""
        out = {name: {"S1": 0.0, "ST": 0.0} for name in self.names}
        var = self.variance
        if var <= 0.0:
            return out
        sq = self.coeffs**2
        for j, name in enumerate(self.names):
            involved = self.indices[:, j] > 0
            if self.dim == 1:
                others_zero = np.ones(self.indices.shape[0], dtype=bool)
            else:
                others_zero = np.all(self.indices[:, np.arange(self.dim) != j] == 0, axis=1)
            s1 = float(np.sum(sq[involved & others_zero])) / var
            st = float(np.sum(sq[involved])) / var
            out[name] = {
                "S1": float(min(max(s1, 0.0), 1.0)),
                "ST": float(min(max(st, 0.0), 1.0)),
            }
        return out


def fit_pce(
    param_specs: Mapping[str, Mapping[str, float]],
    objective_fn: Callable[[Mapping[str, float]], float],
    *,
    degree: int = 3,
    n_samples: int | None = None,
    max_terms: int | None = None,
    method: str = "omp",
    tol: float | None = None,
    seed: int = 42,
) -> PCEModel:
    """确定性稀疏 PCE 拟合。

    Args:
        param_specs: {name: {"low","high"}}（均匀）或 {name: {"mean","std"}}（正态）。
        objective_fn: callable(params_dict) -> float。
        degree: 总阶截断。
        n_samples: 训练样本数（默认 max(2*P, 32)，P=多指标项数）。
        max_terms: OMP 非零项上限（默认不设限）。
        method: "omp"（默认，稀疏）或 "ls"（全基最小二乘）。
        tol: OMP 残差 2 范数停止阈值（默认 1e-10*max(1, ||y||)）。
        seed: 采样种子（局部 Generator，不污染全局随机态）。
    """
    if degree < 0:
        raise ValueError("degree must be >= 0")
    if method not in ("omp", "ls"):
        raise ValueError(f"unknown method: {method!r}")
    names, params = _parse_specs(param_specs)
    dim = len(names)
    indices = multi_indices(dim, degree)
    n_basis = indices.shape[0]
    if n_samples is None:
        n_samples = max(2 * n_basis, 32)
    n_samples = int(n_samples)
    if n_samples < 1:
        raise ValueError("n_samples must be >= 1")

    rng = np.random.default_rng(seed)
    canonical = np.empty((n_samples, dim), dtype=float)
    for j, prm in enumerate(params):
        if prm.kind == "legendre":
            canonical[:, j] = rng.uniform(-1.0, 1.0, n_samples)
        else:
            canonical[:, j] = rng.standard_normal(n_samples)
    actual = np.empty((n_samples, dim), dtype=float)
    for j, prm in enumerate(params):
        actual[:, j] = prm.loc + prm.scale * canonical[:, j]
    y = np.array(
        [float(objective_fn(dict(zip(names, (float(v) for v in row), strict=True)))) for row in actual],
        dtype=float,
    )

    kinds = [prm.kind for prm in params]
    _, design = build_design_matrix(kinds, canonical, degree, indices)

    if method == "ls":
        coeffs, *_ = np.linalg.lstsq(design, y, rcond=None)
        active = np.ones(n_basis, dtype=bool)
    else:
        if max_terms is not None and int(max_terms) < 0:
            raise ValueError("max_terms must be >= 0")
        if tol is None:
            tol = 1e-10 * max(1.0, float(np.linalg.norm(y)))
        fit = omp_fit(design, y, max_terms=max_terms, tol=float(tol))
        coeffs = fit["coeffs"]
        active = coeffs != 0.0

    if tol is None:
        tol = 0.0
    pred = design @ coeffs
    sse = float(np.sum((y - pred) ** 2))
    sst = float(np.sum((y - float(np.mean(y))) ** 2))
    r2 = 1.0 - sse / sst if sst > 0.0 else 1.0

    model = PCEModel(
        names=names,
        kinds=kinds,
        locs=np.array([prm.loc for prm in params], dtype=float),
        scales=np.array([prm.scale for prm in params], dtype=float),
        lows=np.array([prm.low for prm in params], dtype=float),
        highs=np.array([prm.high for prm in params], dtype=float),
        degree=degree,
        indices=indices,
        coeffs=coeffs,
        active=active,
        n_samples=n_samples,
        r2=float(r2),
        method=method,
        tol=float(tol),
    )
    return model


def pce_sobol(
    param_specs: Mapping[str, Mapping[str, float]],
    objective_fn: Callable[[Mapping[str, float]], float],
    **kwargs: Any,
) -> dict[str, Any]:
    """PCE-Sobol 便捷入口：拟合 + 系数直读，返回与 Saltelli 平行的口径。"""
    model = fit_pce(param_specs, objective_fn, **kwargs)
    non_constant = np.sum(model.active & ~np.all(model.indices == 0, axis=1))
    return {
        "ok": True,
        "sensitivity": model.sobol(),
        "method": "pce",
        "degree": model.degree,
        "n_samples": model.n_samples,
        "n_terms": int(non_constant),
        "variance": model.variance,
        "r2": model.r2,
        "model": model,
    }


# ---------------------------------------------------------------------------
# worst-case：角点穷举 + PCE 极值搜索
# ---------------------------------------------------------------------------


def corner_worst_case(
    param_specs: Mapping[str, Mapping[str, float]],
    cost_fn: Callable[[Mapping[str, float]], float],
    *,
    maximize: bool = False,
    sigma_scale: float = 2.0,
) -> dict[str, Any]:
    """穷举容差角点，返回最优/最差角点。

    均匀参数取 low/high；正态参数取 mean ± sigma_scale*std。
    """
    if sigma_scale <= 0.0:
        raise ValueError("sigma_scale must be > 0")
    names, params = _parse_specs(param_specs)
    levels: list[list[float]] = []
    for prm in params:
        if prm.kind == "legendre":
            levels.append([prm.low, prm.high])
        else:
            levels.append([prm.loc - sigma_scale * prm.scale, prm.loc + sigma_scale * prm.scale])
    best_params: dict[str, float] | None = None
    best_value: float | None = None
    count = 0
    for combo in itertools.product(*levels):
        point = dict(zip(names, (float(v) for v in combo), strict=True))
        value = float(cost_fn(point))
        count += 1
        if best_value is None or (value > best_value if maximize else value < best_value):
            best_value = value
            best_params = point
    return {
        "ok": True,
        "params": best_params,
        "value": float(best_value) if best_value is not None else float("nan"),
        "maximize": maximize,
        "n_evaluations": count,
    }


def _pattern_search(
    func: Callable[[np.ndarray], float],
    start: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    maximize: bool,
    max_iter: int,
    step_tol: float,
) -> tuple[np.ndarray, float, int]:
    x = np.clip(np.asarray(start, dtype=float), lo, hi)
    best_x = x.copy()
    best_v = func(best_x)
    n_eval = 1
    step = 0.5 * (hi - lo)
    sign = 1.0 if maximize else -1.0
    for _ in range(max_iter):
        moved = False
        for j in range(x.size):
            if step[j] <= 0.0:
                continue
            for delta in (step[j], -step[j]):
                cand = x.copy()
                cand[j] = min(hi[j], max(lo[j], cand[j] + delta))
                if cand[j] == x[j]:
                    continue
                value = func(cand)
                n_eval += 1
                if sign * (value - best_v) > 1e-15:
                    best_x = cand.copy()
                    best_v = value
                    x = cand
                    moved = True
        if not moved:
            step = step * 0.5
            if np.all(step <= step_tol * np.maximum(1.0, hi - lo)):
                break
    return best_x, best_v, n_eval


def worst_case(
    model: PCEModel,
    *,
    maximize: bool = False,
    max_iter: int = 200,
    step_tol: float = 1e-8,
    sigma_scale: float = 3.0,
) -> dict[str, Any]:
    """在 PCE 代理上做多起点确定性极值搜索（角点 + 中心起步）。"""
    if not isinstance(model, PCEModel):
        raise TypeError("model must be a PCEModel")
    if sigma_scale <= 0.0:
        raise ValueError("sigma_scale must be > 0")
    if max_iter < 1:
        raise ValueError("max_iter must be >= 1")
    lo = np.array([-1.0 if k == "legendre" else -sigma_scale for k in model.kinds], dtype=float)
    hi = -lo
    center = 0.5 * (lo + hi)
    corners = [np.array(c, dtype=float) for c in itertools.product(*zip(lo, hi, strict=True))]
    starts = [center, *corners]
    if len(starts) > 128:  # 高维退化：中心 + 各轴端点
        axis = [center]
        for j in range(model.dim):
            for bound in (lo[j], hi[j]):
                point = center.copy()
                point[j] = bound
                axis.append(point)
        starts = axis

    def func(x: np.ndarray) -> float:
        return float(model.predict_canonical(x.reshape(1, -1))[0])

    best_x: np.ndarray | None = None
    best_v: float | None = None
    n_eval = 0
    for start in starts:
        x, value, used = _pattern_search(func, start, lo, hi, maximize, max_iter, step_tol)
        n_eval += used
        if best_v is None or (value > best_v if maximize else value < best_v):
            best_v = value
            best_x = x
    assert best_x is not None
    actual = model.from_canonical(best_x)
    return {
        "ok": True,
        "params": dict(zip(model.names, (float(v) for v in actual), strict=True)),
        "canonical": [float(v) for v in best_x],
        "value": float(best_v) if best_v is not None else float("nan"),
        "maximize": maximize,
        "n_evaluations": n_eval,
    }


# ---------------------------------------------------------------------------
# 设计中心化（良率最大化）
# ---------------------------------------------------------------------------


def tolerance_yield(
    center: Mapping[str, float],
    cost_fn: Callable[[Mapping[str, float]], float],
    *,
    tolerances: Mapping[str, float],
    spec_max: float,
    n_levels: int = 3,
) -> dict[str, Any]:
    """容差箱确定性网格良率（cost <= spec_max 为通过）。"""
    if not center:
        raise ValueError("center must be non-empty")
    if n_levels < 2:
        raise ValueError("n_levels must be >= 2")
    if not np.isfinite(spec_max):
        raise ValueError("spec_max must be finite")
    names = sorted(center.keys())
    levels = np.linspace(-1.0, 1.0, n_levels)
    total = 0
    passed = 0
    worst_cost = float("-inf")
    worst_params: dict[str, float] | None = None
    for combo in itertools.product(levels, repeat=len(names)):
        point = {
            name: float(center[name]) + float(tolerances.get(name, 0.0)) * float(level)
            for name, level in zip(names, combo, strict=True)
        }
        value = float(cost_fn(point))
        total += 1
        if value > worst_cost:
            worst_cost = value
            worst_params = point
        if value <= spec_max:
            passed += 1
    return {
        "ok": True,
        "yield": passed / total if total else 0.0,
        "n_pass": passed,
        "n_samples": total,
        "worst_cost": worst_cost,
        "worst_params": worst_params,
    }


def design_centering(
    param_specs: Mapping[str, Mapping[str, float]],
    cost_fn: Callable[[Mapping[str, float]], float],
    *,
    spec_max: float,
    tolerances: Mapping[str, float],
    n_levels: int = 3,
    max_iter: int = 50,
    step_frac: float = 0.25,
    shrink: float = 0.5,
    step_tol: float = 1e-9,
) -> dict[str, Any]:
    """设计中心化：坐标 pattern search 偏移中心以最大化容差箱良率。

    Args:
        param_specs: 设计容许箱（均匀 low/high；正态 mean±3σ）。
        cost_fn: callable(params) -> float（越小越好）。
        spec_max: 通过阈值（cost <= spec_max）。
        tolerances: {name: 半宽}（确定性容差箱）。
        n_levels: 每维容差网格层数。
        max_iter: 坐标搜索轮数。
        step_frac: 初始步长 = step_frac * 容许箱宽。
        shrink: 无改进时步长收缩因子。
        step_tol: 相对步长收敛阈值。
    """
    if shrink <= 0.0 or shrink >= 1.0:
        raise ValueError("shrink must be in (0, 1)")
    if step_frac <= 0.0:
        raise ValueError("step_frac must be > 0")
    names, params = _parse_specs(param_specs)
    lows = np.array([prm.low for prm in params], dtype=float)
    highs = np.array([prm.high for prm in params], dtype=float)
    span = np.maximum(highs - lows, 1e-12)

    def evaluate(position: np.ndarray) -> dict[str, Any]:
        point = dict(zip(names, (float(v) for v in position), strict=True))
        return tolerance_yield(
            point, cost_fn, tolerances=tolerances, spec_max=spec_max, n_levels=n_levels
        )

    initial = 0.5 * (lows + highs)
    init = evaluate(initial)
    best_position = initial.copy()
    best_yield = float(init["yield"])
    best_worst = float(init["worst_cost"])
    n_eval = int(init["n_samples"])
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
                result = evaluate(cand)
                n_eval += int(result["n_samples"])
                better = result["yield"] > best_yield + 1e-12 or (
                    abs(result["yield"] - best_yield) <= 1e-12
                    and result["worst_cost"] < best_worst - 1e-15
                )
                if better:
                    best_position = cand
                    best_yield = float(result["yield"])
                    best_worst = float(result["worst_cost"])
                    improved = True
        if not improved:
            step = step * shrink
            if np.all(step <= step_tol * span):
                break
    final = evaluate(best_position)
    n_eval += int(final["n_samples"])
    return {
        "ok": True,
        "center": dict(zip(names, (float(v) for v in best_position), strict=True)),
        "yield": float(final["yield"]),
        "worst_cost": float(final["worst_cost"]),
        "initial_center": dict(zip(names, (float(v) for v in initial), strict=True)),
        "initial_yield": float(init["yield"]),
        "initial_worst_cost": float(init["worst_cost"]),
        "n_evaluations": n_eval,
        "n_levels": n_levels,
    }
