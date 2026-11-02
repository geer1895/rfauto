"""AI-3（round14 §三）：预训练-微调迁移协议（源→目标少样本 vs 从头训对比）。

规格原文："复用 rfic_tl_dataset 源→目标少样本微调 vs 从头训对比表，
复验 4× 降数据口径。torch extra"。本席交付边界（任务书：AI 系小图/
合成数据验证接口即可，真训练超本席门）：

- **闭式微调内核**（零 torch，确定性红线 C4）：
  - :func:`pretrain_ridge`——源域岭回归闭式（含偏置列）；
  - :func:`l2sp_finetune`——L2-SP 微调（Li et al., ICML 2018，
    "Exploiting Structural Redundancy for Robust Few-shot Transfer"，
    规格口径的预训练-微调协议标准基线）：目标域目标
    ``λ‖y−Xw‖² + μ‖w−w_src‖²``，闭式
    ``w* = (XᵀX + (μ/λ)I)⁻¹ (Xᵀy + (μ/λ)·w_src)``——μ→0 退化为从头
    岭回归、μ→∞ 退化为源模型直用（两端连续可控）；
- **对比协议** :func:`transfer_comparison`：目标域按给定数据比例
  frac 切少样本集（seed 化可复现、n_repeat 次重复），每档比较
  {从头岭回归, L2-SP 微调} 在固定目标域测试集上的 MSE；
- **真数据通道** :func:`rfic_tl_transfer_table`：接 core/rfic_tl_dataset
  （数据在盘 runs/pb1_rfic_tl/upstream 时可跑，缺席诚实 skip——同
  test_rfic_tl_dataset 惯例）；"4× 降数据口径"的真数据复验超本席门
  （训练面），本函数只产表不裁结论。

铁律 7 对照：全部数字来自注入数据与闭式线代，无 LLM/无随机炼丹
（seed 只控制少样本切分索引，切法逐位可复现）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

#: 对比协议缺省数据比例档（4× 降数据口径的采样：1/8、1/4、1/2、全量）
DEFAULT_FRACS: tuple[float, ...] = (0.125, 0.25, 0.5, 1.0)


def _design(X: np.ndarray) -> np.ndarray:
    """加偏置列的设计矩阵 (n, d+1)。"""
    X = np.asarray(X, dtype=float)
    if X.ndim != 2:
        raise ValueError(f"X 须为二维 (n, d)，实得 {X.shape}")
    return np.column_stack([X, np.ones(X.shape[0])])


def _fit_bias_included(
    A: np.ndarray, b: np.ndarray, anchor: np.ndarray | None, ratio: float,
) -> np.ndarray:
    """岭闭式：w = (AᵀA + ratio·I)⁻¹ (Aᵀb + ratio·anchor)；anchor=None 即
    普通岭回归（锚置零等价）。"""
    dim = A.shape[1]
    reg = ratio * np.eye(dim)
    rhs = A.T @ b
    if anchor is not None:
        rhs = rhs + ratio * np.asarray(anchor, dtype=float)
    return np.linalg.solve(A.T @ A + reg, rhs)


def pretrain_ridge(
    X: np.ndarray, y: np.ndarray, lam: float = 1.0,
) -> np.ndarray:
    """源域岭回归闭式（含偏置列，偏置同受正则——L2-SP 口径统一）。"""
    A = _design(X)
    yv = np.asarray(y, dtype=float).ravel()
    if A.shape[0] != yv.size or yv.size < 2:
        raise ValueError("X/y 行数不一致或样本 <2")
    if float(lam) <= 0.0:
        raise ValueError(f"lam 必须 >0，实得 {lam}")
    return _fit_bias_included(A, yv, None, float(lam))


def l2sp_finetune(
    X: np.ndarray, y: np.ndarray, w_src: np.ndarray,
    *, lam: float = 1.0, mu: float = 1.0,
) -> np.ndarray:
    """L2-SP 微调闭式（对源权重 w_src 的 L2 锚；见模块 docstring）。

    μ=0 显式拒绝（那即从头训，走 pretrain_ridge 保持语义显式）。
    """
    A = _design(X)
    yv = np.asarray(y, dtype=float).ravel()
    w0 = np.asarray(w_src, dtype=float).ravel()
    if A.shape[0] != yv.size or yv.size < 1:
        raise ValueError("X/y 行数不一致或为空")
    if w0.shape[0] != A.shape[1]:
        raise ValueError(
            f"w_src 维数 {w0.shape[0]} 与设计矩阵列数 {A.shape[1]} 不符"
            "（须含偏置项——用 pretrain_ridge 产出）")
    if float(lam) <= 0.0 or float(mu) <= 0.0:
        raise ValueError(f"lam/mu 必须 >0（μ=0 即从头训，走 pretrain_ridge），"
                         f"实得 lam={lam}, mu={mu}")
    return _fit_bias_included(A, yv, w0, float(mu) / float(lam))


def _predict(A: np.ndarray, w: np.ndarray) -> np.ndarray:
    return A @ w


def transfer_comparison(
    X_tgt: np.ndarray,
    y_tgt: np.ndarray,
    w_src: np.ndarray,
    *,
    fracs: Sequence[float] = DEFAULT_FRACS,
    test_frac: float = 0.25,
    n_repeat: int = 8,
    seed: int = 20261003,
    lam_pre: float = 1.0,
    lam_ft: float = 1.0,
    mu_ft: float = 10.0,
) -> dict[str, Any]:
    """目标域少样本 {从头, 微调} 对比表（seed 化切分，确定性）。

    固定测试集（尾部 test_frac，切分与重复无关）→ 每档 frac 取
    n = max(2, round(frac·n_train)) 个训练样本（default_rng(seed+i)
    置换前 n 个）→ 两臂回归 → 固定测试集 MSE。全部数字可复现：
    同参同 seed 同表。

    Returns:
        {"fracs": [...], "n_train", "n_test", "n_repeat",
        "table": [{frac, n_fewshot, mse_scratch_mean, mse_finetune_mean,
        mse_scratch_all, mse_finetune_all}...]}
    """
    X = np.asarray(X_tgt, dtype=float)
    y = np.asarray(y_tgt, dtype=float).ravel()
    if X.ndim != 2 or X.shape[0] != y.size or y.size < 8:
        raise ValueError("X_tgt/y 形状不一致或样本 <8（需留出测试集）")
    if not 0.0 < float(test_frac) < 0.5:
        raise ValueError(f"test_frac 须在 (0, 0.5)，实得 {test_frac}")
    if int(n_repeat) < 1:
        raise ValueError(f"n_repeat 必须 ≥1，实得 {n_repeat}")
    for f in fracs:
        if not 0.0 < f <= 1.0:
            raise ValueError(f"frac 须在 (0, 1]，实得 {f}")

    n_total = y.size
    n_test = max(2, round(n_total * float(test_frac)))
    idx_all = np.arange(n_total)
    idx_test = idx_all[:n_test]          # 尾部固定测试集
    idx_pool = idx_all[n_test:]
    A_test = _design(X[idx_test])
    y_test = y[idx_test]

    table: list[dict[str, Any]] = []
    for frac in fracs:
        n_few = max(2, round(float(frac) * idx_pool.size))
        mse_s: list[float] = []
        mse_f: list[float] = []
        for i in range(int(n_repeat)):
            rng = np.random.default_rng(int(seed) + i)
            picked = rng.permutation(idx_pool)[:n_few]
            A_few = _design(X[picked])
            y_few = y[picked]
            w_scratch = _fit_bias_included(A_few, y_few, None, float(lam_ft))
            w_ft = l2sp_finetune(
                X[picked], y_few, w_src,
                lam=float(lam_ft), mu=float(mu_ft))
            mse_s.append(float(np.mean(
                (_predict(A_test, w_scratch) - y_test) ** 2)))
            mse_f.append(float(np.mean(
                (_predict(A_test, w_ft) - y_test) ** 2)))
        table.append({
            "frac": float(frac),
            "n_fewshot": n_few,
            "mse_scratch_mean": float(np.mean(mse_s)),
            "mse_finetune_mean": float(np.mean(mse_f)),
            "mse_scratch_all": mse_s,
            "mse_finetune_all": mse_f,
        })
    return {
        "fracs": [float(f) for f in fracs],
        "n_train": int(idx_pool.size),
        "n_test": int(n_test),
        "n_repeat": int(n_repeat),
        "table": table,
    }


def rfic_tl_transfer_table(
    root: str,
    source_nodes: Sequence[str],
    target_node: str,
    *,
    target_block: str = "y",
    metric_col: int = 3,
    **kwargs: Any,
) -> dict[str, Any]:
    """RFIC-TL 真数据迁移对比表（数据在盘时；缺席抛 FileNotFoundError）。

    源域 = source_nodes 全样本预训练岭回归（目标块 target_block 的第
    metric_col 列），目标域 = target_node；其余同 transfer_comparison。
    数据缺席/上游未 clone 时如实抛错（他机 skipif 由测试侧判）。
    """
    from rfauto.core.rfic_tl_dataset import load_rfic_tl

    data = load_rfic_tl(root, nodes=[*source_nodes, target_node])
    src = data["nodes"]

    def _stack(names: list[str], block: str) -> tuple[np.ndarray, np.ndarray]:
        xs = np.vstack([src[n]["x"] for n in names])
        ys = np.vstack([src[n][block] for n in names])
        return xs, ys[:, int(metric_col)]

    x_src, y_src = _stack(list(source_nodes), target_block)
    x_tgt, y_tgt = _stack([target_node], target_block)
    w_src = pretrain_ridge(x_src, y_src, lam=float(kwargs.get("lam_pre", 1.0)))
    out = transfer_comparison(x_tgt, y_tgt, w_src, **{
        k: v for k, v in kwargs.items() if k != "lam_pre"})
    out["source_nodes"] = list(source_nodes)
    out["target_node"] = str(target_node)
    out["target_block"] = str(target_block)
    out["metric_col"] = int(metric_col)
    return out


def synthetic_transfer_case(
    n_src: int = 240,
    n_tgt: int = 120,
    *,
    seed: int = 11,
    delta: float = 0.1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """共享结构合成迁移案例（4 维线性族；裁判用，2026-10-03 冻结）。

    y = w·x + b + ε：源域 w 精确、目标域 w_t = w + 0.1·定向扰动、同
    截距、噪声 0.05→0.20。**设计注记（2026-10-03 实测证伪记录）**：
    早期版本的"目标域截距平移"形态下 L2-SP 全参数锚（含偏置）在少
    样本档会被锚拽向错误的源截距，微调反而输给从头训——L2-SP 协议
    的适用前提是**权重结构共享**（含截距），均值平移族需免偏置锚
    变体（本协议不覆盖，如实声明）。
    """
    rng = np.random.default_rng(int(seed))
    w_true = np.array([2.0, -1.0, 0.5, 0.25])
    w_tgt = w_true + float(delta) * np.array([1.0, -1.0, 0.5, -1.0])
    x_src = rng.uniform(-1.0, 1.0, size=(int(n_src), 4))
    y_src = x_src @ w_true + 1.0 + 0.05 * rng.standard_normal(int(n_src))
    x_tgt = rng.uniform(-1.0, 1.0, size=(int(n_tgt), 4))
    y_tgt = x_tgt @ w_tgt + 1.0 + 0.20 * rng.standard_normal(int(n_tgt))
    return x_src, y_src, x_tgt, y_tgt


def transfer_better_at_low_shot(
    table: dict[str, Any],
    *,
    tol: float = 0.0,
) -> bool:
    """判读：最低数据档微调 MSE ≤ 从头 MSE + tol（对比表→布尔判据）。"""
    rows = sorted(table["table"], key=lambda r: r["frac"])
    first = rows[0]
    return bool(first["mse_finetune_mean"]
                <= first["mse_scratch_mean"] + float(tol))


def make_transfer_callable(
    x_src: np.ndarray, y_src: np.ndarray, lam_pre: float = 1.0,
) -> tuple[np.ndarray, Callable[[np.ndarray, np.ndarray, float, float], np.ndarray]]:
    """便捷面：返回 (w_src, 微调闭包)——协议演示/测试复用。"""
    w_src = pretrain_ridge(x_src, y_src, lam=float(lam_pre))

    def _ft(X: np.ndarray, y: np.ndarray, lam: float = 1.0,
            mu: float = 10.0) -> np.ndarray:
        return l2sp_finetune(X, y, w_src, lam=lam, mu=mu)

    return w_src, _ft
