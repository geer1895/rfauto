"""S-5a 稀疏多项式混沌展开（自适应 LARS，Blatman-Sudret）+ Sobol 系数直读。

法源与可达性（如实标注，round3 方案 研究扩充 round3
§3.1 S-5：core/pce 基构造 × sklearn LassoLars，Blatman-Sudret 最小自实现）
------------------------------------------------------------------------
- 目标方法：Blatman & Sudret (2011), "Adaptive sparse polynomial chaos
  expansion based on least angle regression", J. Comput. Phys. 230:2345-2367。
  **2011 JCP 原文付费墙不可达**（ScienceDirect 摘要页可读，2026-09-27 实测）；
  算法口径钉自两份开放获取文献（实现时全文已读）：
  * Blatman & Sudret (2009), "Sparse polynomial chaos expansions based on an
    adaptive least angle regression algorithm", 20e Congres Francais de
    Mecanique, Marseille（HAL hal-03391253，全文可达已读）——LAR 六步
    （预测子标准化→路径→LOO 精度选点→OLS 重拟合）+ 自适应升阶六步循环
    （p 递增、Q2 目标停机、过拟合守卫 Q2_p <= Q2_{p-1} <= Q2_{p-2}）+
    超截断集 A^M_{p,q}。
  * Luthen, Marelli & Sudret (2022), "A sparse polynomial chaos expansion
    review/ benchmark", CMAME 398:115261（HAL hal-02936436，全文可达已读）
    ——修正 LOO 误差 T = N/(N-P_act) * (1 + tr((Psi_act^T Psi_act)^-1))
    （其 Eq.(6)，源自 Chapelle et al. 2002）与超截断
    A_{p,q} = {alpha in N^d : ||alpha||_q <= p}（其 Eq.(9)）。
- 系数幅值截断（cut）：出自 2010/2011 期刊版对基富集的细化；**截断常数的
  原文逐字表述未核对**（付费墙），本实现按二手通引口径预声明：非常数系数
  |c_alpha| <= cut_factor * sqrt(LOO 误差估计) 判为零（cut_factor 缺省 1.0 =
  与残差标准差同量级）。这是本模块对原文的唯一"口径转述"点，如实登记。
- Ishigami 函数（判据函数，Sobol' & Levitin 1999 解析 Sobol 已知）：
  f(x1,x2,x3) = sin(x1) + a*sin(x2)^2 + b*x3^4*sin(x1)，xi~U(-pi,pi)；
    V1=(1+b*pi^4/5)^2/2，V2=a^2/8，V3=0，V13=b^2*pi^8*(1/18-1/50)=8*b^2*pi^8/225，
    V=V1+V2+V13；S1=V1/V，S2=V2/V，S3=0；ST1=(V1+V13)/V，ST2=V2/V，ST3=V13/V。
  解析值由 :func:`ishigami_sobol_analytic` 给出（判定用测试须独立重推导，
  见 tests/unit/test_sparse_pce.py 双路径裁判）。

与 core/pce.py 的关系（本任务 pce.py 只读）
------------------------------------------
正交基构造与设计矩阵**复用** core/pce.py（legendre_orthonormal /
hermite_orthonormal / build_design_matrix；参数规格解析复用其 _parse_specs，
uniform→Legendre、normal→Hermite 语义一致）。稀疏恢复面为**正交化增量**：
pce.py 是单轮 OMP（一次性定基），本模块是 LARS 全路径 + 修正 LOO 选点 +
OLS 重拟合 + 系数幅值截断 + 自适应升阶（Blatman-Sudret），Sobol 面另含
子集级 ANOVA 枚举闭式。故独立成文件而非原地扩展。

依赖纪律
--------
core 叶子层：模块顶层只 import numpy 与 core.pce；sklearn（lars_path）与
scipy（stats.qmc / stats.norm.ppf）在函数内 lazy import（同
core/metric_transform.py 的 GP lazy import 先例）。不读 runs/、不联网、
零文件 IO、数值只出确定性内核。

诚实边界
--------
- 修正 LOO 公式要求每个候选模型 P_active <= N-2（预声明稳定域）：越界候选
  不参与选点（如实跳过）；N < 候选基总数**合法**（LASSO 正则恢复正是此
  场景），但 N < dim+2 连线性模型的可判读自由度都没有，直接 ValueError。
- 原文自适应循环 step4 过拟合守卫触发后"加密试验设计重试"；本最小实现
  不自动加密（试验点数是调用方契约），触发即停并在 stopped_by='
  overfitting_guard' 报告，加密由调用方换 seed/n_samples 重跑。
- PCE 是全局多项式代理：强不连续/窄带深谷（patch 谷深族）收敛慢，Sobol
  直读反映**代理**的方差分解；代理不准则指数不准（与 pce.py 同边界）。
- 输入必须独立（PCE 张量积基的前提）；相关输入敏感性（Kucherenko 面，
  SALib）不在本模块，属新依赖裁决项（round3 S-5 原文，未裁决未实现）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from rfauto.core.pce import _parse_specs, build_design_matrix

__all__ = [
    "SparsePCEModel",
    "fit_sparse_pce",
    "hyperbolic_indices",
    "ishigami",
    "ishigami_sobol_analytic",
    "sample_canonical",
    "sparse_pce_sobol",
]

#: Kucherenko 面（相关输入敏感性）依赖 SALib——round3 S-5 明示"新依赖裁决"，
#: 用户未裁决前不装不实现（本常量仅作登记口径）。
KUCHERENKO_STATUS = "awaiting_dependency_decision"


# ---------------------------------------------------------------------------
# 多指标：超截断集 A_{p,q}（Blatman-Sudret）
# ---------------------------------------------------------------------------


def _compositions(total: int, dim: int) -> list[tuple[int, ...]]:
    """总阶恰为 total 的 dim 维非负整数分量枚举（graded-lex 消费用）。"""
    if dim == 1:
        return [(total,)]
    rows: list[tuple[int, ...]] = []
    for first in range(total + 1):
        for rest in _compositions(total - first, dim - 1):
            rows.append((first, *rest))
    return rows


def hyperbolic_indices(dim: int, degree: int, q: float = 1.0) -> np.ndarray:
    """超截断多指标集 A_{p,q} = {alpha : ||alpha||_q <= p}（含零指标=常数项）。

    ||alpha||_q = (sum_i alpha_i^q)^(1/q)（q<1 时为超范数，重罚高阶交互，
    sparsity-of-effects 原理）；q=1 退化为总阶截断，基数 = (d+p)!/(d!p!)。
    返回按 (总阶, 字典序) 排序的 (P, dim) int 数组，行 0 恒为全零。
    """
    if dim < 1:
        raise ValueError("dim must be >= 1")
    if degree < 0:
        raise ValueError("degree must be >= 0")
    if not (0.0 < q <= 1.0):
        raise ValueError("q must be in (0, 1]")
    rows: list[tuple[int, ...]] = []
    for total in range(degree + 1):
        for comp in _compositions(total, dim):
            norm = (
                float(total)
                if q == 1.0
                else float(np.sum(np.power(np.asarray(comp, dtype=float), q))) ** (1.0 / q)
            )
            if norm <= degree + 1e-12:
                rows.append(comp)
    rows.sort(key=lambda a: (sum(a), a))
    return np.asarray(rows, dtype=int)


# ---------------------------------------------------------------------------
# 试验点：固定 seed 拉丁超立方 / Sobol 序列（scipy.stats.qmc，零新依赖）
# ---------------------------------------------------------------------------


def sample_canonical(
    kinds: Sequence[str],
    n_samples: int,
    *,
    seed: int = 42,
    sampler: str = "lhs",
) -> np.ndarray:
    """规范空间试验点 (N, d)：Legendre 维 U(-1,1)、Hermite 维 N(0,1)。

    sampler="lhs"（缺省）为拉丁超立方（scipy.stats.qmc.LatinHypercube，逆 CDF
    变换）；"sobol" 为 Sobol 序列（要求 n_samples 为 2 的幂，否则 ValueError
    ——平衡性前提，且避免 scipy UserWarning 破坏 -W error 环境）。
    """
    if n_samples < 1:
        raise ValueError("n_samples must be >= 1")
    if sampler not in ("lhs", "sobol"):
        raise ValueError(f"unknown sampler: {sampler!r}")
    if sampler == "sobol" and n_samples & (n_samples - 1) != 0:
        raise ValueError("sampler='sobol' requires n_samples to be a power of 2")
    from scipy.stats import qmc  # lazy import（core 叶子纪律，见模块 docstring）

    dim = len(kinds)
    if sampler == "lhs":
        engine = qmc.LatinHypercube(d=dim, rng=np.random.default_rng(seed))
    else:
        engine = qmc.Sobol(d=dim, scramble=True, rng=np.random.default_rng(seed))
    unit = engine.random(n_samples)
    canonical = np.empty_like(unit)
    for j, kind in enumerate(kinds):
        if kind == "legendre":
            canonical[:, j] = 2.0 * unit[:, j] - 1.0
        elif kind == "hermite":
            from scipy.stats import norm  # lazy import

            canonical[:, j] = norm.ppf(unit[:, j])
        else:
            raise ValueError(f"unknown basis kind: {kind!r}")
    return canonical


# ---------------------------------------------------------------------------
# 修正 LOO（Blatman-Sudret 2011 / Luthen 2022 Eq.6）与 LARS 路径选点
# ---------------------------------------------------------------------------


def _ols_loo_stats(a: np.ndarray, y: np.ndarray) -> dict[str, float] | None:
    """OLS 重拟合 + 修正 LOO 精度（秩亏/不稳定返回 None）。

    返回 {"coef", "loo", "t_mod", "q2"}：loo=留一均方误差，q2 = 1 - T*loo/var(y)
    （Blatman-Sudret 的 Q2 修正口径：修正因子乘 LOO 误差后进 Q2）。
    """
    n, p = a.shape
    if p > n - 2:
        return None
    coef, *_ = np.linalg.lstsq(a, y, rcond=None)
    pred = a @ coef
    q_mat, _ = np.linalg.qr(a)
    h_diag = np.sum(q_mat * q_mat, axis=1)
    denom = 1.0 - h_diag
    if np.any(denom <= 1e-10):
        return None
    resid = y - pred
    loo = float(np.mean((resid / denom) ** 2))
    evals = np.linalg.eigvalsh(a.T @ a)
    if evals.size == 0 or evals[0] <= evals[-1] * 1e-10:
        return None
    t_mod = n / (n - p) * (1.0 + float(np.sum(1.0 / evals)))
    y_bar = float(np.mean(y))
    var_y = float(np.sum((y - y_bar) ** 2) / (n - 1))
    if var_y <= 0.0:
        return None
    q2 = 1.0 - t_mod * loo / var_y
    return {"coef": coef, "loo": loo, "t_mod": t_mod, "q2": float(q2)}


def _select_on_lars_path(
    psi: np.ndarray,
    y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, dict[str, float]] | None:
    """LARS-lasso 全路径 + 每步 OLS 重拟合按修正 LOO Q2 选最优。

    psi: (N, P) 预测子矩阵，**列 0 必须是常数项**（不进正则化）；其余列应已
    标准化（Blatman-Sudret 2009 LAR step1）。y 原始（未中心）响应。
    返回 (active_cols, coef, stats)：active_cols 为 psi 列号（均 >=1，升序），
    coef 长度 = len(active_cols)+1（行 0=常数项系数，其余与 active_cols 对齐）；
    无可行候选返回 None。
    """
    from sklearn.linear_model import lars_path  # lazy import（core 叶子纪律）

    y_centered = y - float(np.mean(y))
    candidates = psi[:, 1:]
    if candidates.size == 0:
        return None
    _alphas, _active, coefs = lars_path(candidates, y_centered, method="lasso")
    best_cols: np.ndarray | None = None
    best_coef: np.ndarray | None = None
    best_stats: dict[str, float] | None = None
    best_k = -1
    for k in range(coefs.shape[1]):
        mask = coefs[:, k] != 0.0
        if not bool(mask.any()):
            continue
        cols = np.nonzero(mask)[0] + 1  # 回到含常数列的编号（非常数激活列）
        refit_cols = np.concatenate(([0], cols)).astype(int)
        stats = _ols_loo_stats(psi[:, refit_cols], y)
        if stats is None:
            continue
        # 平局取项数更少者，再取路径更早者（确定性）
        key = (stats["q2"], -len(cols), -k)
        if best_stats is not None and best_cols is not None:
            take = key > (best_stats["q2"], -len(best_cols), -best_k)
        else:
            take = True
        if take:
            best_cols, best_coef, best_stats, best_k = cols, stats["coef"], stats, k
    if best_cols is None or best_coef is None or best_stats is None:
        return None
    return best_cols, best_coef, best_stats


def _standardize_columns(psi: np.ndarray) -> np.ndarray:
    """LAR step1：非常数列标准化为经验均值 0/方差 1（近零方差列原样保留）。"""
    out = psi.copy()
    for j in range(1, psi.shape[1]):
        col = psi[:, j]
        std = float(np.std(col))
        if std > 1e-12:
            out[:, j] = (col - float(np.mean(col))) / std
    return out


# ---------------------------------------------------------------------------
# 稀疏 PCE 模型
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class SparsePCEModel:
    """Blatman-Sudret 自适应稀疏 PCE 拟合结果（预测 + Sobol 系数直读）。"""

    names: list[str]
    kinds: list[str]
    locs: np.ndarray
    scales: np.ndarray
    q: float
    degree_start: int
    degree_max: int
    degree_selected: int
    indices: np.ndarray  # 激活多指标集（含零指标常数项），对齐 coeffs
    coeffs: np.ndarray
    n_samples: int
    n_basis_selected: int
    n_terms: int
    q2: float
    modified_loo_error: float
    r2: float
    stopped_by: str
    cut_factor: float
    sampler: str
    seed: int
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dim(self) -> int:
        return len(self.names)

    @property
    def mean(self) -> float:
        zero = np.all(self.indices == 0, axis=1)
        return float(np.sum(self.coeffs[zero]))

    @property
    def variance(self) -> float:
        mask = ~np.all(self.indices == 0, axis=1)
        return float(np.sum(self.coeffs[mask] ** 2))

    def sobol_components(self) -> dict[frozenset[str], float]:
        """子集级 ANOVA 方差贡献闭式：V_u = sum_{supp(alpha)=u} c_alpha^2。

        输入独立 + 基正交归一 => 系数平方即该子空间方差贡献
        （Blatman-Sudret Sobol 直读口径，多指标集枚举）。
        """
        out: dict[frozenset[str], float] = {}
        sq = self.coeffs**2
        for t in range(self.indices.shape[0]):
            alpha = self.indices[t]
            if not np.any(alpha):
                continue
            supp = frozenset(self.names[j] for j in range(self.dim) if int(alpha[j]) > 0)
            out[supp] = out.get(supp, 0.0) + float(sq[t])
        return out

    def sobol(self) -> dict[str, dict[str, float]]:
        """一阶/总阶 Sobol 闭式（S1: 支集恰为 {i}；ST: alpha_i>0 的全体）。"""
        var = self.variance
        out = {name: {"S1": 0.0, "ST": 0.0} for name in self.names}
        if var <= 0.0:
            return out
        comps = self.sobol_components()
        sq = self.coeffs**2
        for j, name in enumerate(self.names):
            s1 = comps.get(frozenset([name]), 0.0) / var
            involved = self.indices[:, j] > 0
            st = float(np.sum(sq[involved])) / var
            out[name] = {
                "S1": float(min(max(s1, 0.0), 1.0)),
                "ST": float(min(max(st, 0.0), 1.0)),
            }
        return out

    def predict_canonical(self, canonical: Any) -> np.ndarray:
        xa = np.asarray(canonical, dtype=float)
        if xa.ndim == 1:
            xa = xa.reshape(1, -1)
        _, design = build_design_matrix(self.kinds, xa, self.degree_selected, self.indices)
        return design @ self.coeffs

    def predict(self, params: Any) -> float:
        if isinstance(params, Mapping):
            missing = [n for n in self.names if n not in params]
            if missing:
                raise ValueError(f"missing parameter(s): {missing}")
            vec = np.array([float(params[n]) for n in self.names], dtype=float)
        else:
            vec = np.asarray(params, dtype=float)
            if vec.shape != (self.dim,):
                raise ValueError(f"expected {self.dim} values, got shape {vec.shape}")
        xi = (vec - self.locs) / self.scales
        return float(self.predict_canonical(xi.reshape(1, -1))[0])

    def to_dict(self) -> dict[str, Any]:
        """JSON 安全快照（numpy 标量/数组全部转原生类型）。"""
        return {
            "ok": True,
            "method": "sparse_pce_blatman_sudret",
            "names": list(self.names),
            "kinds": list(self.kinds),
            "q": float(self.q),
            "degree_start": int(self.degree_start),
            "degree_max": int(self.degree_max),
            "degree_selected": int(self.degree_selected),
            "n_samples": int(self.n_samples),
            "n_basis_selected": int(self.n_basis_selected),
            "n_terms": int(self.n_terms),
            "q2": float(self.q2),
            "modified_loo_error": float(self.modified_loo_error),
            "r2": float(self.r2),
            "variance": float(self.variance),
            "mean": float(self.mean),
            "sensitivity": self.sobol(),
            "indices": [[int(v) for v in row] for row in self.indices],
            "coeffs": [float(v) for v in self.coeffs],
            "stopped_by": str(self.stopped_by),
            "cut_factor": float(self.cut_factor),
            "sampler": str(self.sampler),
            "seed": int(self.seed),
            "history": [dict(rec) for rec in self.history],
        }


def fit_sparse_pce(
    param_specs: Mapping[str, Mapping[str, float]],
    objective_fn: Callable[[Mapping[str, float]], float],
    *,
    degree_max: int = 6,
    degree_start: int = 2,
    q: float = 1.0,
    n_samples: int | None = None,
    sampler: str = "lhs",
    cut_factor: float = 1.0,
    q2_target: float = 0.99,
    seed: int = 42,
) -> SparsePCEModel:
    """Blatman-Sudret 自适应稀疏 PCE 拟合（固定 seed 试验点，确定性）。

    Args:
        param_specs: {name: {"low","high"}}（均匀→Legendre）或
            {name: {"mean","std"}}（正态→Hermite），与 core/pce 同契约。
        objective_fn: callable(params_dict) -> float（确定性目标）。
        degree_max: 升阶循环上界 p_max（>=1）。
        degree_start: 起始阶 p0（>=1，<=degree_max）。
        q: 超截断范数指数（(0,1]，1=总阶截断）。
        n_samples: 试验点数（缺省 max(4*card(A_{p0,q}), 32)）。N 小于候选基
            总数合法（L1 正则恢复），但 < dim+2 直接 ValueError。
        sampler: "lhs"（缺省）或 "sobol"（需 2 的幂）。
        cut_factor: 系数幅值截断因子（|c| <= cut_factor*sqrt(LOO) 判零，
            预声明口径，见模块 docstring"可达性"节）。
        q2_target: 修正 LOO Q2 达标停机阈值（原文 Q2_tgt）。
        seed: 试验点种子（局部 Generator，不污染全局随机态）。
    """
    if degree_start < 1:
        raise ValueError("degree_start must be >= 1 (p<1 无意义)")
    if degree_max < 1:
        raise ValueError("degree_max must be >= 1 (p<1 无意义)")
    if degree_max < degree_start:
        raise ValueError("degree_max must be >= degree_start")
    if not (0.0 < q <= 1.0):
        raise ValueError("q must be in (0, 1]")
    if cut_factor < 0.0:
        raise ValueError("cut_factor must be >= 0")

    names, params = _parse_specs(param_specs)
    dim = len(names)
    kinds = [prm.kind for prm in params]
    locs = np.array([prm.loc for prm in params], dtype=float)
    scales = np.array([prm.scale for prm in params], dtype=float)

    n_start = hyperbolic_indices(dim, degree_start, q).shape[0]
    if n_samples is None:
        n_samples = max(4 * n_start, 32)
    n_samples = int(n_samples)
    if n_samples < dim + 2:
        raise ValueError(
            f"n_samples={n_samples} too small: need >= dim+2 = {dim + 2} "
            "(最低阶模型修正 LOO 的可判读自由度下限)"
        )

    canonical = sample_canonical(kinds, n_samples, seed=seed, sampler=sampler)
    actual = locs + scales * canonical
    y = np.array(
        [float(objective_fn(dict(zip(names, (float(v) for v in row), strict=True)))) for row in actual],
        dtype=float,
    )
    y_var = float(np.sum((y - float(np.mean(y))) ** 2) / (n_samples - 1))
    if y_var <= 0.0:
        raise ValueError("objective appears constant over the sample: cannot fit a PCE")

    history: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    stopped_by = "max_degree"
    p_prev2: float | None = None
    p_prev: float | None = None

    for p in range(degree_start, degree_max + 1):
        idx = hyperbolic_indices(dim, p, q)
        _, psi = build_design_matrix(kinds, canonical, p, idx)
        psi_std = _standardize_columns(psi)
        selected = _select_on_lars_path(psi_std, y)
        if selected is None:
            history.append(
                {
                    "degree": int(p),
                    "n_basis": int(idx.shape[0]),
                    "n_terms": 0,
                    "q2_pre_cut": None,
                    "q2_post_cut": None,
                    "note": "no feasible candidate on LARS path",
                }
            )
            break
        cols, _coef, stats = selected
        coef = stats["coef"]  # 长度 = len(cols)+1，行 0=常数项
        loo_pre = stats["loo"]
        # 系数幅值截断（预声明口径）：|c| <= cut_factor*sqrt(LOO) 判零；
        # 常数项不截断（coef[0] 对应列 0）
        threshold = cut_factor * math.sqrt(max(loo_pre, 0.0))
        keep_active = np.abs(coef[1:]) > threshold
        keep_cols = cols[keep_active]
        final_cols = np.concatenate(([0], keep_cols)).astype(int)
        post = _ols_loo_stats(psi[:, final_cols], y)
        if post is None:  # 截断后退化兜底：回退截断前选点（如实记历史）
            post = {"coef": coef, "loo": loo_pre, "t_mod": stats["t_mod"], "q2": stats["q2"]}
            final_cols = np.concatenate(([0], cols)).astype(int)
        q2_post = float(post["q2"])
        n_terms = int(np.sum(final_cols > 0))
        history.append(
            {
                "degree": int(p),
                "n_basis": int(idx.shape[0]),
                "n_terms": n_terms,
                "q2_pre_cut": float(stats["q2"]),
                "q2_post_cut": q2_post,
            }
        )
        if best is None or q2_post > float(best["q2"]) + 1e-12:
            best = {
                "degree": p,
                "indices": idx[final_cols],
                "coeffs": np.asarray(post["coef"], dtype=float),
                "q2": q2_post,
                "loo": float(post["loo"]),
                "n_basis": int(idx.shape[0]),
            }
        if float(best["q2"]) >= q2_target:
            stopped_by = "q2_target"
            break
        # 过拟合守卫（原文 step4 的最小化变体：触发即停，见模块 docstring）
        if p_prev2 is not None and p_prev is not None and q2_post <= p_prev <= p_prev2:
            stopped_by = "overfitting_guard"
            break
        p_prev2, p_prev = p_prev, q2_post

    if best is None:
        raise ValueError("no feasible sparse PCE candidate found for the given samples")

    final_idx = np.asarray(best["indices"], dtype=int)
    final_coef = np.asarray(best["coeffs"], dtype=float)
    pred = build_design_matrix(kinds, canonical, int(best["degree"]), final_idx)[1] @ final_coef
    sse = float(np.sum((y - pred) ** 2))
    r2 = 1.0 - sse / float(np.sum((y - float(np.mean(y))) ** 2))
    model = SparsePCEModel(
        names=names,
        kinds=kinds,
        locs=locs,
        scales=scales,
        q=float(q),
        degree_start=int(degree_start),
        degree_max=int(degree_max),
        degree_selected=int(best["degree"]),
        indices=final_idx,
        coeffs=final_coef,
        n_samples=n_samples,
        n_basis_selected=int(best["n_basis"]),
        n_terms=int(np.sum(final_idx.any(axis=1))),
        q2=float(best["q2"]),
        modified_loo_error=float(best["loo"]),
        r2=float(r2),
        stopped_by=stopped_by,
        cut_factor=float(cut_factor),
        sampler=str(sampler),
        seed=int(seed),
        history=history,
    )
    return model


# ---------------------------------------------------------------------------
# 便捷入口与 Ishigami 判据函数
# ---------------------------------------------------------------------------


def sparse_pce_sobol(
    param_specs: Mapping[str, Mapping[str, float]],
    objective_fn: Callable[[Mapping[str, float]], float],
    **kwargs: Any,
) -> dict[str, Any]:
    """拟合 + Sobol 直读，返回与 core/pce.pce_sobol 平行的口径。"""
    model = fit_sparse_pce(param_specs, objective_fn, **kwargs)
    return {
        "ok": True,
        "sensitivity": model.sobol(),
        "method": "sparse_pce_blatman_sudret",
        "degree_selected": model.degree_selected,
        "degree_max": model.degree_max,
        "n_samples": model.n_samples,
        "n_basis_selected": model.n_basis_selected,
        "n_terms": model.n_terms,
        "q2": model.q2,
        "r2": model.r2,
        "stopped_by": model.stopped_by,
        "model": model,
    }


def ishigami(x: Any, a: float = 7.0, b: float = 0.1) -> np.ndarray:
    """Ishigami 函数：sin(x1) + a*sin(x2)^2 + b*x3^4*sin(x1)。

    x: (..., 3) 数组，xi 取值域 U(-pi, pi)（判据函数，模块 docstring 引
    Sobol' & Levitin 1999 解析 Sobol）。
    """
    xa = np.asarray(x, dtype=float)
    if xa.shape[-1] != 3:
        raise ValueError("ishigami expects last axis of size 3")
    x1, x2, x3 = xa[..., 0], xa[..., 1], xa[..., 2]
    return np.sin(x1) + a * np.sin(x2) ** 2 + b * x3**4 * np.sin(x1)


def ishigami_sobol_analytic(a: float = 7.0, b: float = 0.1) -> dict[str, float]:
    """Ishigami 解析 Sobol 指数（Sobol' & Levitin 1999 闭式，见模块 docstring）。"""
    v1 = (1.0 + b * math.pi**4 / 5.0) ** 2 / 2.0
    v2 = a**2 / 8.0
    v13 = b**2 * math.pi**8 * (1.0 / 18.0 - 1.0 / 50.0)
    total = v1 + v2 + v13
    return {
        "V1": v1,
        "V2": v2,
        "V3": 0.0,
        "V13": v13,
        "V": total,
        "S1": v1 / total,
        "S2": v2 / total,
        "S3": 0.0,
        "ST1": (v1 + v13) / total,
        "ST2": v2 / total,
        "ST3": v13 / total,
    }
