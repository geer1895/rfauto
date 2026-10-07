r"""NX-10 MIMO 信道容量/分集确定性内核（round14 §四 :108「C=log₂det(I+γHH†)
与分集增益，S 参法直接可得」；B 流，2026-10-02）。

确定性纯函数、零 IO、零求解器、零新依赖（纯 numpy）；数值全部落在本内核，
LLM/agent 只解释（铁律 7）。信道矩阵 H 可由实测 S 参数/端口阻抗直接构成
（S 参法），本内核只接收已构成的 H，S→H 的提取面归 ecc_metrics 既有语义
（本模块零改动不与其重叠——任务书文件面约束）。

口径与法源（铁律 5：法源写 docstring；裁判=独立路径，#118）
================================================================

- **容量公式**：E. Telatar, "Capacity of multi-antenna Gaussian channels",
  European Transactions on Telecommunications 10(6), 1999——
  C = log₂ det(I_Nr + γ·H H†)。本模块同时输出两档功率口径：
  * 等功率（equal）：总发射信噪比 snr 均分到 Nt 个发射阵元
    （D. Tse & P. Viswanath, "Fundamentals of Wireless Communication",
    Cambridge Univ. Press, 2005, §5.3——C_eq = Σᵢ log₂(1 + snr·λᵢ/Nt)，
    λᵢ 为 H H† 的特征值）。规格原式 C=log₂det(I+γHH†) 即本档在
    γ ≡ snr/Nt（单流信噪比口径）下的形式——两种写法的恒等由测试钉
    （slogdet 独立数值路径 vs 特征值求和路径）。
  * 注水（waterfilling）：逐特征模最优功率分配 pᵢ = (μ − 1/λᵢ)⁺、
    Σpᵢ = snr（Tse & Viswanath 2005, §5.4.3；Cover & Thomas, "Elements
    of Information Theory" 2nd ed., §10.5 平行高斯信道注水同构）。
    水位 μ 的活性模搜索：对降序 λ 取最大 k 使 μ_k=(snr+Σ_{i≤k}1/λᵢ)/k ≥
    1/λ_k（等价闭式搜索，标准算法）。
- **分集面**：rank(HH†)（空间复用自由度）+ 有效分集阶
  N_eff = (Σλᵢ)²/Σλᵢ²（participation-ratio 口径的有效秩/等效自由度，
  满秩 i.i.d. 时 N_eff=N、秩 1 时 N_eff=1；作为"分集增益"通道维的
  确定性度量输出。天线级 DG=10·log10(1−ECC) 近似归 ecc_metrics 既有
  语义，本模块不重复）。
- **i.i.d. Rayleigh 遍历容量闭式（SISO，测试锚）**：
  E[log₂(1+γ|H|²)]，|H|²~Exp(1)：
      E[ln(1+γX)] = ∫₀^∞ e^{−x}ln(1+γx)dx = e^{1/γ}·E₁(1/γ)
  （分部积分 + 代换 t=x+1/γ；E₁=指数积分。即 SISO Rayleigh 遍历容量
  经典结果，见 Tse & Viswanath 2005 §5.4.5 或 Goldsmith, "Wireless
  Communications", 2005 Ch.5；Monte Carlo 均值对拍由测试以
  scipy.special.exp1 独立求值裁判，本内核零 scipy 依赖）。

诚实边界（预声明，#122）
========================
- 本内核为无记忆窄带信道口径（一次快照 H → 该快照容量）；遍历/中断
  统计除测试锚的 SISO 闭式对照外不在本内核（多流遍历容量无简单闭式，
  不编造）。
- 注水在 λ=0（秩亏）模上功率为零，容量退化到非零模之和——秩亏退化
  行为由测试钉（等功率 vs 注水在秩亏下的差=注水增益）。
- H 的行列归一化（噪声口径）由调用方负责：snr 按"总发射信噪比、单
  RX 天线噪声归一"（Tse-Viswanath 惯例）解释，本内核不做口径换算。

设计约束：core 层（仅 numpy），非法输入显式 ValueError，不静默兜底；
输出 JSON 可序列化（全 float/int/list，零 NaN/Inf——json
allow_nan=False 兼容）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = [
    "capacity_from_eigenvalues",
    "effective_diversity_order",
    "eigenvalues_hh",
    "mimo_capacity",
    "mimo_capacity_report",
    "waterfilling_powers",
]

_TINY = 1e-12
_EIG_TOL = 1e-12  # 特征值零判阈（相对最大特征值）


# ─── 输入校验 ──────────────────────────────────────────────────────────────────


def _h_as_complex_matrix(seq: Any, name: str) -> np.ndarray:
    """嵌套列表 → 复矩阵；元素=实数（按实部）或 [re, im] 对。

    显式结构校验（矩形、非空、有限）——numpy 2.x 对锯齿列表 asarray 抛
    ValueError 的行为不作为接口依赖（显式逐行判，报错信息可读）。
    """
    if not isinstance(seq, (list, tuple)) or len(seq) == 0:
        raise ValueError(f"{name} 必须是非空嵌套列表（Nr×Nt 矩阵）")
    rows: list[np.ndarray] = []
    n_cols: int | None = None
    for r, row in enumerate(seq):
        if not isinstance(row, (list, tuple)) or len(row) == 0:
            raise ValueError(f"{name} 第 {r} 行必须是非空列表")
        if n_cols is None:
            n_cols = len(row)
        elif len(row) != n_cols:
            raise ValueError(
                f"{name} 不是矩形矩阵：第 {r} 行长度 {len(row)} != 第 0 行 {n_cols}")
        cells: list[complex] = []
        for c, cell in enumerate(row):
            if isinstance(cell, (list, tuple)):
                if len(cell) != 2:
                    raise ValueError(
                        f"{name}[{r}][{c}] 复数须为 [re, im] 对，收到长度 {len(cell)}")
                re, im = float(cell[0]), float(cell[1])
            elif isinstance(cell, (int, float)) and not isinstance(cell, bool):
                re, im = float(cell), 0.0
            else:
                raise ValueError(
                    f"{name}[{r}][{c}] 须为实数或 [re, im] 对，收到 {type(cell).__name__}")
            if not (math.isfinite(re) and math.isfinite(im)):
                raise ValueError(f"{name}[{r}][{c}] 含非有限值（NaN/Inf）")
            cells.append(complex(re, im))
        rows.append(np.asarray(cells, dtype=complex))
    return np.vstack(rows)


def _validate_snr(snr: Any) -> float:
    val = float(snr)
    if not math.isfinite(val) or val <= 0.0:
        raise ValueError(f"snr 必须为正有限数（线性口径），收到 {snr!r}")
    return val


# ─── 谱分解 ────────────────────────────────────────────────────────────────────


def eigenvalues_hh(h_matrix) -> np.ndarray:
    """H H† 的特征值（降序，数值零截断到 0——负的浮点尾数不上报）。"""
    h = np.asarray(h_matrix, dtype=complex)
    if h.ndim != 2 or min(h.shape) < 1:
        raise ValueError("H 必须是二维非空矩阵")
    lam = np.linalg.eigvalsh(h @ h.conj().T)
    lam = np.sort(lam)[::-1]
    tol = max(float(lam[0]), 0.0) * _EIG_TOL
    return np.where(lam > tol, lam, 0.0)


# ─── 注水 ──────────────────────────────────────────────────────────────────────


def waterfilling_powers(eigenvalues, snr_total: float) -> np.ndarray:
    """逐特征模注水功率 pᵢ = (μ − 1/λᵢ)⁺、Σpᵢ = snr_total（标准活性模
    搜索：最大 k 使 μ_k = (snr+Σ_{i≤k}1/λᵢ)/k ≥ 1/λ_k）。

    eigenvalues 降序非负（eigenvalues_hh 口径）；λ=0 模恒 0 功率。
    全零谱（H=0）返回全零。支持批量（(n, r) 逐行注水，逐行返回 (n, r)）。
    防御性降序重排（活性模搜索要求降序；无序输入静默错分的负例由测试钉）。
    """
    snr_total = _validate_snr(snr_total)
    lam_in = np.asarray(eigenvalues, dtype=float)
    was_1d = lam_in.ndim == 1
    lam = lam_in[None, :] if was_1d else lam_in
    if lam.ndim != 2:
        raise ValueError("eigenvalues 须为 (r,) 或 (n, r)")
    order = np.argsort(-lam, axis=1, kind="stable")  # 降序重排（活性模搜索要求）
    lam_sorted = np.take_along_axis(lam, order, axis=1)
    r = lam.shape[1]
    if r == 0:
        return np.zeros_like(lam)

    safe = np.where(lam_sorted > 0.0, lam_sorted, np.inf)  # λ=0 → 1/λ=0 贡献、恒不入活性集
    inv = 1.0 / safe
    cum_inv = np.cumsum(inv, axis=1)
    k = np.arange(1, r + 1)[None, :]
    mu_by_k = (snr_total + cum_inv) / k
    # 活性条件：μ_k ≥ 1/λ_k（λ_k=0 时 1/λ_k=∞ → 永不活性，被 max 过滤）
    cond = mu_by_k >= inv
    any_pos = lam_sorted > 0.0
    valid = cond & any_pos
    has_any = np.any(valid, axis=1)
    k_star = np.where(
        has_any, r - np.argmax(valid[:, ::-1], axis=1), 1)  # 最大活性 k；无→保底 1
    idx = np.clip(k_star - 1, 0, r - 1)
    mu = np.take_along_axis(mu_by_k, idx[:, None], axis=1)[:, 0]
    powers_sorted = np.clip(mu[:, None] - inv, 0.0, None)
    powers_sorted = np.where(any_pos, powers_sorted, 0.0)
    # 反重排回输入列序（输出与输入列对齐；降序输入时恒等）
    powers = np.empty_like(powers_sorted)
    np.put_along_axis(powers, order, powers_sorted, axis=1)
    return powers[0] if was_1d else powers


# ─── 容量 ──────────────────────────────────────────────────────────────────────


def capacity_from_eigenvalues(eigenvalues, snr_total: float, n_tx: int, *,
                              allocation: str = "equal") -> float | np.ndarray:
    """特征值 → 容量（bps/Hz）。等功率 / 注水两档。

    equal:  C = Σ log₂(1 + snr·λᵢ/n_tx)   （总 SNR 均分，Tse §5.3）
    waterfilling: C = Σ log₂(1 + pᵢ·λᵢ)   （注水，Tse §5.4.3）
    eigenvalues 支持 (r,) 单行或 (n, r) 批量（返回对应形状）。
    """
    snr_total = _validate_snr(snr_total)
    n_tx = int(n_tx)
    if n_tx < 1:
        raise ValueError(f"n_tx 至少为 1，收到 {n_tx!r}")
    if allocation == "equal":
        lam = np.asarray(eigenvalues, dtype=float)
        if lam.ndim == 1:
            return float(np.sum(np.log2(1.0 + snr_total * lam / n_tx)))
        if lam.ndim == 2:
            return np.sum(np.log2(1.0 + snr_total * lam / n_tx), axis=1)
        raise ValueError("eigenvalues 须为 (r,) 或 (n, r)")
    if allocation == "waterfilling":
        lam = np.asarray(eigenvalues, dtype=float)
        powers = waterfilling_powers(lam, snr_total)
        if lam.ndim == 1:
            return float(np.sum(np.log2(1.0 + powers * lam)))
        return np.sum(np.log2(1.0 + powers * lam), axis=1)
    raise ValueError(f"allocation 必须是 'equal'|'waterfilling'，收到 {allocation!r}")


def mimo_capacity(h_matrix, snr: float, *, allocation: str = "equal") -> float:
    """信道矩阵快照容量（bps/Hz）；mimo_capacity_report 的单值入口。"""
    h = _h_as_complex_matrix(h_matrix, "h_matrix")
    snr = _validate_snr(snr)
    lam = eigenvalues_hh(h)
    return float(capacity_from_eigenvalues(lam, snr, h.shape[1], allocation=allocation))


def effective_diversity_order(eigenvalues) -> float:
    """有效分集阶 N_eff = (Σλ)²/Σλ²（participation-ratio 有效秩）。

    满秩均匀谱 → N_eff=模数；秩 1 → 1；全零谱（H=0）→ 0（诚实零，
    不造下限）。
    """
    lam = np.asarray(eigenvalues, dtype=float)
    total = float(lam.sum())
    if total <= 0.0:
        return 0.0
    return float(total * total / float(np.square(lam).sum()))


def mimo_capacity_report(h_matrix, snr: float) -> dict[str, Any]:
    """MIMO 容量报告（JSON 可序列化）：谱 + 两档容量 + 规格原式 + 分集面。"""
    h = _h_as_complex_matrix(h_matrix, "h_matrix")
    snr = _validate_snr(snr)
    lam = eigenvalues_hh(h)
    n_rx, n_tx = int(h.shape[0]), int(h.shape[1])
    rank = int(np.count_nonzero(lam))

    c_equal = float(capacity_from_eigenvalues(lam, snr, n_tx, allocation="equal"))
    c_wf = float(capacity_from_eigenvalues(lam, snr, n_tx, allocation="waterfilling"))

    # 规格原式独立路径：C = log₂det(I + snr·HH†)（γ=单流 SNR 口径，无均分）
    hh = h @ h.conj().T
    sign, logabs = np.linalg.slogdet(np.eye(n_rx) + snr * hh)
    if sign <= 0.0:
        raise ValueError("det(I+snr·HH†) ≤ 0（数值谱异常），拒绝输出")
    c_logdet = float(logabs / math.log(2.0))

    powers = waterfilling_powers(lam, snr)
    water_level: float | None = None
    if rank > 0:
        active = powers[powers > 0.0]
        if active.size:
            water_level = float(np.max(active + _safe_inv(lam[powers > 0.0])))

    _, sv, _ = np.linalg.svd(h)  # 独立路径：σᵢ² ≡ λᵢ（测试钉）

    return {
        "n_rx": n_rx,
        "n_tx": n_tx,
        "n_modes": int(lam.size),
        "rank": rank,
        "singular_values": [float(v) for v in sv],
        "eigenvalues_hh": [float(v) for v in lam],
        "snr": snr,
        "capacity_equal_bps_hz": c_equal,
        "capacity_waterfilling_bps_hz": c_wf,
        "capacity_logdet_spec_form_bps_hz": c_logdet,
        "power_equal_per_tx": float(snr / n_tx),
        "power_waterfilling": [float(v) for v in powers],
        "water_level": water_level,
        "waterfilling_gain_bps_hz": float(c_wf - c_equal),
        "effective_diversity_order": effective_diversity_order(lam),
    }


def _safe_inv(lam_positive: np.ndarray) -> np.ndarray:
    """1/λ（仅对 >0 的 λ 调用；防御性 where 防 0 除）。"""
    vals = np.asarray(lam_positive, dtype=float)
    return np.where(vals > 0.0, 1.0 / np.where(vals > 0.0, vals, 1.0), 0.0)
