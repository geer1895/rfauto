"""经验公式符号归纳：确定性稀疏符号回归内核 + 谷位提取（core 叶子，仅 numpy）。

依据
----
- 符号回归（PySR 类）从仿真数据归纳闭式经验公式（f0(L,W,er,h)、k(BASE) 等），
  确定性可复现、可审计；产出经人工审核入 core/calculators，喂 fake 派发 /
  synthesis 初值 / 报告白名单数字；裁判 = 独立数值对照（#118：不得自证）。
- 候选须确定性可审计。

机制（不引入新依赖，纯 numpy 自实现；不装 PySR/gplearn/sympy）
--------------------------------------------------------------
1. **候选基函数库** `build_library`：常数、各变量幂、sqrt/log/倒数、
   两两比值与乘积。列名即表达式字符串，列序按变量名字典序完全确定；域
   不合法（sqrt 见负数 / log 见非正 / 分母近零）的列**确定性跳过**——
   调用方拿回列名清单即可审计库的实际内容。
2. **列选择** `select_subsets`：复杂度档 k = 1..K 各给出一个最优列子集。
   k 不超过穷举档时做**穷举最小二乘**（并列取字典序最小组合）——这是恢复
   稀疏生成式的关键：贪心/OMP 在共线基函数上会先选中"看起来更相关"的错列，
   再靠组合补偿（实测 y=3x1/x2+2sqrt(x3) 被 OMP 前两步选成 x2 与 1/x3）；
   更大 k 用贪心前向加列（从上一档最优子集出发）。全程无随机数。
   `omp_order` 仍作为可独立调用的正交匹配追踪工具保留（小库/诊断用）。
3. **复杂度-精度 Pareto**：`fit_design_matrix` 给出每档 k 的最优候选
   （复杂度 = 各列代价之和 + 加法节点数），`pareto_front` 去掉被支配点。
   选择准则三选一——"penalty"（mse·(1+penalty·complexity)）、"tolerance"
   （最小复杂度中误差已达最优容差）、"holdout"（留出误差最小，并列取低复杂度）。
4. **裁判面** `patch_resonance_hj_ghz`：Hammerstad（Balanis 教科书口径）
   矩形贴片谐振闭式，作为 patch 数据集的**独立闭式对照**。拟合路径
   **不经过它**（#118 不作自证），只有测试与 scripts/symbolic_fit_patch.py
   把它当裁判调用。
5. `resonance_dip`：从稠密 S 参数谱确定性提取指定频窗内最深**局部**
   谷（patch f0 数据面提取内核）。刻意不用全局 argmin：W>46mm 的宽贴片存在
   更深的高阶模簇（实测 3.1-3.5GHz 谷深可达 -26dB），全局 argmin 会把高阶模
   误当基模（见 patch_f0 标定归档的证据）。

诚实边界
--------
- 归纳式只是对**观测数据**的最小二乘近似，不含任何物理推导；任何准备入
  core/calculators 的常数必须经独立对照 + 人工审核。
- 本模块不读 runs/、不联网、不依赖 skrf/optuna（core 零依赖叶子约束）。
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "BasisConfig",
    "CandidateFormula",
    "ResonanceDip",
    "SymbolicFit",
    "build_library",
    "fit_design_matrix",
    "fit_symbolic",
    "format_formula",
    "omp_order",
    "pareto_front",
    "patch_resonance_hj_ghz",
    "resonance_dip",
    "select_subsets",
]

# 光速（mm·GHz，299792458 m/s）——与 core/synthesis.py 同口径。
_C_MM_GHZ = 299.792458


@dataclass(frozen=True)
class BasisConfig:
    """候选基函数库开关（默认覆盖公式归纳需要的多项式/1/x/sqrt/ln/比值族）。"""

    max_power: int = 2
    allow_inverse: bool = True
    allow_sqrt: bool = True
    allow_log: bool = True
    allow_ratios: bool = True
    allow_products: bool = True
    allow_constant: bool = True
    min_abs: float = 1e-9


@dataclass(frozen=True)
class CandidateFormula:
    """一个具体候选：项 + 系数 + 复杂度 + 训练/留出误差。"""

    terms: tuple[str, ...]
    coefficients: tuple[float, ...]
    complexity: int
    mse_train: float
    rmse_train: float
    r2_train: float
    mse_holdout: float | None = None
    rmse_holdout: float | None = None

    @property
    def n_terms(self) -> int:
        return len(self.terms)

    def formula(self, name: str = "y", precision: int = 6) -> str:
        return format_formula(self.terms, self.coefficients, name=name, precision=precision)

    def to_dict(self, name: str = "y", precision: int = 6) -> dict[str, Any]:
        return {
            "formula": self.formula(name=name, precision=precision),
            "terms": list(self.terms),
            "coefficients": [float(c) for c in self.coefficients],
            "complexity": int(self.complexity),
            "n_terms": int(self.n_terms),
            "mse_train": float(self.mse_train),
            "rmse_train": float(self.rmse_train),
            "r2_train": float(self.r2_train),
            "mse_holdout": None if self.mse_holdout is None else float(self.mse_holdout),
            "rmse_holdout": None if self.rmse_holdout is None else float(self.rmse_holdout),
        }


@dataclass(frozen=True)
class SymbolicFit:
    """一次归纳的全部产物：选中式 + 完整 Pareto 轨迹（可审计）。"""

    best: CandidateFormula
    candidates: tuple[CandidateFormula, ...]
    pareto: tuple[CandidateFormula, ...]
    feature_names: tuple[str, ...]
    subsets: tuple[tuple[int, ...], ...]
    selected_index: int
    select_by: str

    def to_dict(self, name: str = "y", precision: int = 6) -> dict[str, Any]:
        return {
            "select_by": self.select_by,
            "best": self.best.to_dict(name=name, precision=precision),
            "pareto": [c.to_dict(name=name, precision=precision) for c in self.pareto],
            "candidates": [c.to_dict(name=name, precision=precision) for c in self.candidates],
            "subsets": [[int(i) for i in subset] for subset in self.subsets],
            "subset_terms": [
                [self.feature_names[i] for i in subset] for subset in self.subsets
            ],
            "selected_index": int(self.selected_index),
        }


@dataclass(frozen=True)
class ResonanceDip:
    """指定频窗内最深的局部极小（幅值口径）。"""

    freq: float
    magnitude: float
    depth_db: float
    index: int


def _as_vector(values: Sequence[float] | np.ndarray, label: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{label} 必须是一维序列，收到 ndim={arr.ndim}")
    if arr.size == 0:
        raise ValueError(f"{label} 不能为空")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{label} 含 NaN/Inf，拒绝拟合（确定性前置条件）")
    return arr


def build_library(
    variables: Mapping[str, Sequence[float] | np.ndarray],
    config: BasisConfig | None = None,
) -> tuple[list[str], np.ndarray, list[int]]:
    """由具名变量构造确定性候选基函数库。

    返回 (names, phi, costs)：names[i] 是第 i 列的表达式字符串，phi 是
    (n_samples, n_features) 设计矩阵，costs[i] 是复杂度代价（常数/裸变量 1；
    x^p 为 p；sqrt/log/倒数 2；比值/乘积 3）。
    """
    cfg = config or BasisConfig()
    if not variables:
        raise ValueError("变量集合不能为空")
    if cfg.max_power < 1:
        raise ValueError(f"max_power 必须 >= 1，收到 {cfg.max_power}")
    if cfg.min_abs <= 0:
        raise ValueError(f"min_abs 必须 > 0，收到 {cfg.min_abs}")

    names = sorted(variables)
    cols = {name: _as_vector(variables[name], f"变量 {name}") for name in names}
    n_samples = cols[names[0]].size
    for name in names:
        if cols[name].size != n_samples:
            raise ValueError(f"变量 {name} 长度 {cols[name].size} 与 {names[0]} 的 {n_samples} 不一致")

    feat_names: list[str] = []
    feat_cols: list[np.ndarray] = []
    feat_costs: list[int] = []

    def _add(label: str, values: np.ndarray, cost: int) -> None:
        feat_names.append(label)
        feat_cols.append(values)
        feat_costs.append(cost)

    if cfg.allow_constant:
        _add("1", np.ones(n_samples, dtype=float), 1)
    for name in names:
        x = cols[name]
        _add(name, x.copy(), 1)
        for power in range(2, cfg.max_power + 1):
            _add(f"{name}^{power}", x**power, power)
        if cfg.allow_sqrt and bool(np.all(x >= 0.0)):
            _add(f"sqrt({name})", np.sqrt(x), 2)
        if cfg.allow_inverse and bool(np.all(np.abs(x) >= cfg.min_abs)):
            _add(f"1/{name}", 1.0 / x, 2)
        if cfg.allow_log and bool(np.all(x > 0.0)):
            _add(f"log({name})", np.log(x), 2)
    if cfg.allow_ratios:
        for i, num in enumerate(names):
            for den in names[i + 1 :]:
                for a, b in ((num, den), (den, num)):
                    if bool(np.all(np.abs(cols[b]) >= cfg.min_abs)):
                        _add(f"{a}/{b}", cols[a] / cols[b], 3)
    if cfg.allow_products:
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                _add(f"{a}*{b}", cols[a] * cols[b], 3)

    if not feat_cols:
        return [], np.empty((n_samples, 0), dtype=float), []
    return feat_names, np.column_stack(feat_cols), feat_costs


def omp_order(
    phi: np.ndarray,
    y: Sequence[float] | np.ndarray,
    *,
    max_terms: int | None = None,
    tol: float = 1e-12,
) -> list[int]:
    """正交匹配追踪列序（确定性：并列取最小列号；无随机数）。

    仅作诊断/小库工具：最终归纳走 `select_subsets` 的最优子集搜索。
    """
    matrix = np.asarray(phi, dtype=float)
    target = _as_vector(y, "y")
    if matrix.ndim != 2:
        raise ValueError(f"设计矩阵必须是二维，收到 ndim={matrix.ndim}")
    if matrix.shape[0] != target.size:
        raise ValueError(f"设计矩阵行数 {matrix.shape[0]} 与 y 长度 {target.size} 不一致")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("设计矩阵含 NaN/Inf，拒绝拟合")
    if tol < 0:
        raise ValueError(f"tol 必须 >= 0，收到 {tol}")

    n_samples, n_features = matrix.shape
    if max_terms is None:
        max_terms = n_features
    if max_terms < 0:
        raise ValueError(f"max_terms 必须 >= 0，收到 {max_terms}")
    max_terms = min(int(max_terms), n_features, n_samples)

    norms = np.linalg.norm(matrix, axis=0)
    norms = np.where(norms > 0.0, norms, np.inf)
    y_norm = float(np.linalg.norm(target))
    resid = target.copy()
    selected: list[int] = []
    for _ in range(max_terms):
        if y_norm > 0.0 and float(np.linalg.norm(resid)) <= tol * y_norm:
            break
        corr = np.abs(matrix.T @ resid) / norms
        if selected:
            corr[selected] = -np.inf
        best = int(np.argmax(corr))
        if not np.isfinite(corr[best]) or float(corr[best]) <= tol:
            break
        selected.append(best)
        coef, *_ = np.linalg.lstsq(matrix[:, selected], target, rcond=None)
        resid = target - matrix[:, selected] @ coef
    return selected


def select_subsets(
    phi: np.ndarray,
    y: Sequence[float] | np.ndarray,
    *,
    max_terms: int | None = None,
    exhaustive_max_terms: int = 2,
    max_combinations: int = 50000,
) -> list[tuple[int, ...]]:
    """确定性选出每个复杂度档 k 的最优列子集（k=1..K 各一个）。

    k <= exhaustive_max_terms 时穷举（组合总数超过 max_combinations 时从高到低
    收缩穷举档，保证耗时上限与确定性）；更大 k 从上一档最优子集贪心加列。
    等误差时取字典序最小组合（itertools.combinations 保序 + 严格小于比较）。
    """
    matrix = np.asarray(phi, dtype=float)
    target = _as_vector(y, "y")
    if matrix.ndim != 2:
        raise ValueError(f"设计矩阵必须是二维，收到 ndim={matrix.ndim}")
    if matrix.shape[0] != target.size:
        raise ValueError(f"设计矩阵行数 {matrix.shape[0]} 与 y 长度 {target.size} 不一致")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("设计矩阵含 NaN/Inf，拒绝拟合")
    if exhaustive_max_terms < 0:
        raise ValueError(f"exhaustive_max_terms 必须 >= 0，收到 {exhaustive_max_terms}")
    if max_combinations < 1:
        raise ValueError(f"max_combinations 必须 >= 1，收到 {max_combinations}")

    n_samples, n_features = matrix.shape
    if max_terms is None:
        max_terms = n_features
    if max_terms < 0:
        raise ValueError(f"max_terms 必须 >= 0，收到 {max_terms}")
    limit = min(int(max_terms), n_features, n_samples)
    if limit <= 0:
        return []

    exhaustive = min(int(exhaustive_max_terms), limit)
    while exhaustive > 0:
        total = sum(math.comb(n_features, k) for k in range(1, exhaustive + 1))
        if total <= max_combinations:
            break
        exhaustive -= 1
    # k=1 恒做穷举：只有 m 次试算，代价可忽略，且贪心需要上一档作起点。
    exhaustive = max(exhaustive, 1)

    def _mse(indices: Sequence[int]) -> float:
        cols = matrix[:, list(indices)]
        coef, *_ = np.linalg.lstsq(cols, target, rcond=None)
        resid = target - cols @ coef
        return float(np.mean(resid**2))

    subsets: list[tuple[int, ...]] = []
    for k in range(1, limit + 1):
        if k <= exhaustive:
            best_combo: tuple[int, ...] | None = None
            best_mse = np.inf
            for combo in itertools.combinations(range(n_features), k):
                mse = _mse(combo)
                if mse < best_mse:
                    best_mse = mse
                    best_combo = combo
            if best_combo is None:
                return subsets
            subsets.append(best_combo)
        else:
            base = subsets[-1]
            base_mse = _mse(base)
            best_combo = None
            best_mse = base_mse
            for cand in range(n_features):
                if cand in base:
                    continue
                combo = tuple(sorted((*base, cand)))
                mse = _mse(combo)
                if mse < best_mse:
                    best_mse = mse
                    best_combo = combo
            if best_combo is None:
                # 已无可改进列（残差为 0 或全列已选）：后续档不再有意义。
                break
            subsets.append(best_combo)
    return subsets


def _fit_terms(
    matrix: np.ndarray,
    target: np.ndarray,
    indices: Sequence[int],
    costs: Sequence[int],
    names: Sequence[str],
    train_mask: np.ndarray,
    holdout_mask: np.ndarray | None,
    complexity_offset: int,
) -> CandidateFormula:
    sub = matrix[:, list(indices)]
    coef, *_ = np.linalg.lstsq(sub[train_mask], target[train_mask], rcond=None)
    resid = target[train_mask] - sub[train_mask] @ coef
    mse_train = float(np.mean(resid**2))
    var = float(np.var(target[train_mask]))
    r2 = 1.0 - mse_train / var if var > 0.0 else (1.0 if mse_train == 0.0 else 0.0)
    mse_holdout: float | None = None
    if holdout_mask is not None:
        resid_h = target[holdout_mask] - sub[holdout_mask] @ coef
        mse_holdout = float(np.mean(resid_h**2))
    complexity = int(complexity_offset + sum(int(costs[i]) for i in indices))
    return CandidateFormula(
        terms=tuple(str(names[i]) for i in indices),
        coefficients=tuple(float(c) for c in coef),
        complexity=complexity,
        mse_train=mse_train,
        rmse_train=float(np.sqrt(mse_train)),
        r2_train=float(r2),
        mse_holdout=mse_holdout,
        rmse_holdout=None if mse_holdout is None else float(np.sqrt(mse_holdout)),
    )


def pareto_front(candidates: Sequence[CandidateFormula]) -> list[CandidateFormula]:
    """复杂度-精度 Pareto 前沿（误差口径 = 训练 mse，越低越好）。

    按复杂度升序扫描，仅保留误差严格下降的点（等误差时留低复杂度者）。
    """
    ordered = sorted(candidates, key=lambda c: (c.complexity, c.mse_train))
    front: list[CandidateFormula] = []
    best = np.inf
    for cand in ordered:
        if cand.mse_train < best:
            front.append(cand)
            best = cand.mse_train
    return front


def fit_design_matrix(
    names: Sequence[str],
    phi: np.ndarray,
    y: Sequence[float] | np.ndarray,
    costs: Sequence[int] | None = None,
    *,
    max_terms: int | None = None,
    penalty: float = 0.0,
    select_by: str = "tolerance",
    rtol: float = 1e-6,
    atol: float = 0.0,
    holdout_mask: Sequence[bool] | np.ndarray | None = None,
    exhaustive_max_terms: int = 2,
    max_combinations: int = 50000,
) -> SymbolicFit:
    """在已构造的设计矩阵上做确定性稀疏符号回归。

    select_by：
    - "penalty"：取 mse_train*(1+penalty*complexity) 最小者；
    - "tolerance"：取误差已达最优（<= min_mse + atol + rtol*var(y)）的最小复杂度者；
    - "holdout"：取留出 mse 最小者（并列取低复杂度），必须提供 holdout_mask。
    给定 holdout_mask 时列子集搜索与系数都只用留出集以外的样本拟合（无泄漏）。
    """
    matrix = np.asarray(phi, dtype=float)
    target = _as_vector(y, "y")
    if matrix.ndim != 2:
        raise ValueError(f"设计矩阵必须是二维，收到 ndim={matrix.ndim}")
    if matrix.shape[0] != target.size:
        raise ValueError(f"设计矩阵行数 {matrix.shape[0]} 与 y 长度 {target.size} 不一致")
    if matrix.shape[1] != len(names):
        raise ValueError(f"列名数 {len(names)} 与设计矩阵列数 {matrix.shape[1]} 不一致")
    if costs is None:
        costs = [1] * len(names)
    if len(costs) != len(names):
        raise ValueError(f"costs 长度 {len(costs)} 与列名数 {len(names)} 不一致")
    if penalty < 0:
        raise ValueError(f"penalty 必须 >= 0，收到 {penalty}")
    if rtol < 0 or atol < 0:
        raise ValueError(f"rtol/atol 必须 >= 0，收到 rtol={rtol}, atol={atol}")
    if select_by not in ("penalty", "tolerance", "holdout"):
        raise ValueError(f"未知 select_by={select_by!r}（可选 penalty/tolerance/holdout）")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("设计矩阵含 NaN/Inf，拒绝拟合")

    n_samples = target.size
    mask: np.ndarray | None = None
    train_mask = np.ones(n_samples, dtype=bool)
    if holdout_mask is not None:
        mask = np.asarray(holdout_mask, dtype=bool)
        if mask.ndim != 1 or mask.size != n_samples:
            raise ValueError(f"holdout_mask 形状 {mask.shape} 与样本数 {n_samples} 不匹配")
        train_mask = ~mask
        if not np.any(mask) or not np.any(train_mask):
            raise ValueError("holdout_mask 不能全 True 或全 False")
    if select_by == "holdout" and mask is None:
        raise ValueError("select_by='holdout' 必须提供 holdout_mask")

    subsets = select_subsets(
        matrix[train_mask],
        target[train_mask],
        max_terms=max_terms,
        exhaustive_max_terms=exhaustive_max_terms,
        max_combinations=max_combinations,
    )
    candidates: list[CandidateFormula] = []
    for k, subset in enumerate(subsets, start=1):
        candidates.append(
            _fit_terms(
                matrix,
                target,
                subset,
                costs,
                names,
                train_mask,
                mask,
                complexity_offset=max(0, k - 1),
            )
        )
    if not candidates:
        candidates.append(
            _fit_terms(matrix, target, [], costs, names, train_mask, mask, complexity_offset=0)
        )

    if select_by == "penalty":
        scores = [c.mse_train * (1.0 + penalty * c.complexity) for c in candidates]
        selected_index = int(np.argmin(np.asarray(scores)))
    elif select_by == "tolerance":
        best_mse = min(c.mse_train for c in candidates)
        # 容差相对**目标方差**而非 best_mse：精确恢复时 best_mse ~ 1e-15，
        # 相对它缩放会把数值噪声当显著改进（实测因此多选 1 项）。
        threshold = best_mse + atol + rtol * float(np.var(target[train_mask]))
        best_complexity = min(c.complexity for c in candidates if c.mse_train <= threshold)
        selected_index = next(i for i, c in enumerate(candidates) if c.complexity == best_complexity)
    else:
        holdout_scores = [c.mse_holdout if c.mse_holdout is not None else np.inf for c in candidates]
        best_score = min(holdout_scores)
        selected_index = min(
            (i for i, s in enumerate(holdout_scores) if s == best_score),
            key=lambda i: candidates[i].complexity,
        )

    return SymbolicFit(
        best=candidates[selected_index],
        candidates=tuple(candidates),
        pareto=tuple(pareto_front(candidates)),
        feature_names=tuple(str(n) for n in names),
        subsets=tuple(tuple(int(i) for i in s) for s in subsets),
        selected_index=int(selected_index),
        select_by=select_by,
    )


def fit_symbolic(
    variables: Mapping[str, Sequence[float] | np.ndarray],
    y: Sequence[float] | np.ndarray,
    *,
    config: BasisConfig | None = None,
    max_terms: int | None = None,
    penalty: float = 0.0,
    select_by: str = "tolerance",
    rtol: float = 1e-6,
    atol: float = 0.0,
    holdout_mask: Sequence[bool] | np.ndarray | None = None,
    exhaustive_max_terms: int = 2,
    max_combinations: int = 50000,
) -> SymbolicFit:
    """便捷入口：具名变量 → 基函数库 → 稀疏归纳（见 fit_design_matrix）。"""
    names, phi, costs = build_library(variables, config=config)
    if not names:
        raise ValueError("候选基函数库为空（配置过严或变量域全不合法）")
    return fit_design_matrix(
        names,
        phi,
        y,
        costs,
        max_terms=max_terms,
        penalty=penalty,
        select_by=select_by,
        rtol=rtol,
        atol=atol,
        holdout_mask=holdout_mask,
        exhaustive_max_terms=exhaustive_max_terms,
        max_combinations=max_combinations,
    )


def format_formula(
    terms: Sequence[str],
    coefficients: Sequence[float],
    *,
    name: str = "y",
    precision: int = 6,
) -> str:
    """把 (项, 系数) 渲染成可读公式串；系数 0 的项被省略（确定性输出）。"""
    if len(terms) != len(coefficients):
        raise ValueError(f"项数 {len(terms)} 与系数个数 {len(coefficients)} 不一致")
    if precision < 1:
        raise ValueError(f"precision 必须 >= 1，收到 {precision}")
    pieces: list[tuple[str, str]] = []
    for term, coef in zip(terms, coefficients, strict=True):
        value = float(coef)
        if not np.isfinite(value):
            raise ValueError(f"系数含 NaN/Inf（项 {term!r}），拒绝渲染公式")
        if value == 0.0:
            continue
        magnitude = f"{abs(value):.{precision}g}"
        if term == "1":
            body = magnitude
        else:
            factor = "" if magnitude == "1" else f"{magnitude}*"
            body = f"{factor}{term}"
        pieces.append(("-" if value < 0 else "+", body))
    if not pieces:
        return f"{name} = 0"
    head_sign, head_body = pieces[0]
    text = ("-" if head_sign == "-" else "") + head_body
    for sign, body in pieces[1:]:
        text += f" {sign} {body}"
    return f"{name} = {text}"


def resonance_dip(
    freqs: Sequence[float] | np.ndarray,
    magnitudes: Sequence[float] | np.ndarray,
    *,
    f_min: float | None = None,
    f_max: float | None = None,
    min_depth_db: float = 3.0,
    mode: str = "lowest",
) -> ResonanceDip | None:
    """提取频窗内局部极小；无合格谷位返回 None。

    mode="lowest" 取**最低频**合格谷（基模 TM10 语义：低阶模频率更低），
    mode="deepest" 取最深谷。depth_db 相对该窗内幅值上界（负值=谷深）。
    """
    freq_arr = _as_vector(freqs, "freqs")
    mag_arr = _as_vector(magnitudes, "magnitudes")
    if freq_arr.size != mag_arr.size:
        raise ValueError(f"freqs 长度 {freq_arr.size} 与 magnitudes 长度 {mag_arr.size} 不一致")
    if freq_arr.size < 3:
        raise ValueError(f"至少需要 3 个采样点，收到 {freq_arr.size}")
    if np.any(np.diff(freq_arr) <= 0.0):
        raise ValueError("freqs 必须严格递增（重复/乱序频点会让谷位提取不确定）")
    if np.any(mag_arr < 0.0):
        raise ValueError("magnitudes 为线性幅值，不能为负")
    if min_depth_db < 0.0:
        raise ValueError(f"min_depth_db 必须 >= 0，收到 {min_depth_db}")
    if mode not in ("lowest", "deepest"):
        raise ValueError(f"未知 mode={mode!r}（可选 lowest/deepest）")
    lo = -np.inf if f_min is None else float(f_min)
    hi = np.inf if f_max is None else float(f_max)
    if lo >= hi:
        raise ValueError(f"频窗非法：f_min={lo} >= f_max={hi}")

    window = (freq_arr >= lo) & (freq_arr <= hi)
    if int(np.count_nonzero(window)) < 3:
        return None
    idx = np.flatnonzero(window)
    local: list[int] = []
    for pos in range(1, idx.size - 1):
        i = int(idx[pos])
        if mag_arr[i] <= mag_arr[i - 1] and mag_arr[i] <= mag_arr[i + 1]:
            local.append(i)
    if not local:
        return None
    ref = float(np.max(mag_arr[idx]))
    if ref <= 0.0:
        return None
    # 谷深门是**候选过滤器**：谱上普遍存在 1e-3 量级的数值纹波局部极小，
    # 若先按 lowest/deepest 选点再判深度，最低频纹波会把真谷挤掉（实测）。
    qualifying = [
        i
        for i in local
        if 20.0 * math.log10(max(float(mag_arr[i]), 1e-300) / ref) <= -abs(min_depth_db)
    ]
    if not qualifying:
        return None
    if mode == "lowest":
        chosen = min(qualifying, key=lambda i: (float(freq_arr[i]), i))
    else:
        chosen = min(qualifying, key=lambda i: (float(mag_arr[i]), i))
    mag = float(mag_arr[chosen])
    depth_db = 20.0 * math.log10(max(mag, 1e-300) / ref)
    return ResonanceDip(
        freq=float(freq_arr[chosen]),
        magnitude=mag,
        depth_db=depth_db,
        index=chosen,
    )


def patch_resonance_hj_ghz(l_mm: float, w_mm: float, er: float, h_mm: float) -> float:
    """矩形贴片基模谐振闭式（Hammerstad/Balanis 教科书口径）——独立裁判。

    W 只用于有效介电常数：
    ee = (er+1)/2 + (er-1)/2 * (1+12*h/W)^(-1/2)；
    dL = 0.824*h*(ee+0.3)*(W/h+0.264) / ((ee-0.258)*(W/h+0.8))；
    f0 = c / (2*(L+2*dL)*sqrt(ee))。

    本函数只作经验公式归纳的独立对照（#118），拟合路径不调用它。
    """
    values = {"l_mm": l_mm, "w_mm": w_mm, "er": er, "h_mm": h_mm}
    for label, value in values.items():
        if not np.isfinite(value):
            raise ValueError(f"{label} 必须是有限数，收到 {value!r}")
    if l_mm <= 0.0 or w_mm <= 0.0 or h_mm <= 0.0:
        raise ValueError(f"几何必须为正：{values!r}")
    if er <= 1.0:
        raise ValueError(f"相对介电常数必须 > 1，收到 er={er}")
    ee = (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 + 12.0 * h_mm / w_mm) ** -0.5
    dl = (
        0.824
        * h_mm
        * (ee + 0.3)
        * (w_mm / h_mm + 0.264)
        / ((ee - 0.258) * (w_mm / h_mm + 0.8))
    )
    return _C_MM_GHZ / (2.0 * (l_mm + 2.0 * dl) * float(np.sqrt(ee)))
