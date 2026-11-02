"""模型驱动多目标 BO 采集环（Noise-Aware EHVI 贪心，T-N13，aurora_n W2）。

定位：NSGA-II/III 进化族（multiobj_backend，pymoo）旁新增**模型驱动**
MO-BO 档——代理后验（含跨指标相关，消费 T-N12 ``mt_gp.predict_joint``）
驱动 EHVI（Expected Hypervolume Improvement）采集。本模块是 qNEHVI
（Daulton, Balandat & Bakshy, NeurIPS 2021）的**自实现最小简化形态**
（任务书预声明选型，预声明账本 runs/aurora_n/w2_tn13/CRITERIA.md）：

- 采集 = **Noise-Aware EHVI 贪心**：候选点 M 指标联合后验 (μ,Σ) → 含
  观测噪声的 EHVI 增量 → argmax；**不做** qNEHVI 全式（候选联合后验的
  EHVI 梯度积分与 fantasy 重条件化）。
- **2 维 EHVI = 解析分片闭式**（自实现推导，见下）；**M>2 = MC 采样
  预估**（:func:`ehvi_monte_carlo`，样本数旋钮 ``mc_samples``）。
- 超体积裁判**单源复用** pareto_tools.exact_hypervolume（零复制）。

数学（2 维最小化，推导预声明于 CRITERIA §1）
----------------------------------------------------------------
记参考点 r=(r₁,r₂)，前沿阶梯点 p_i=(a_i,b_i)（ref 盒内过滤后 f₁ 升序、
f₂ 严格降序；记 a_{k+1}:=r₁），候选 Z~N₂(μ,Σ)。

核心引理（Q 函数，Tallis 截断矩推导）：Q(u,m):=E[(m−Z₂)⁺(u−Z₁)⁺]，
标准化 u*=(u−μ₁)/σ₁、m*=(m−μ₂)/σ₂ 后 Q=σ₁σ₂·Ψ₂(u*,m*;ρ)：

    Ψ₂(u,m;ρ) = (u·m+ρ)·Φ₂(u,m;ρ) + u·φ(m)·Φ((u−ρm)/√(1−ρ²))
              + m·φ(u)·Φ((m−ρu)/√(1−ρ²)) + (1−ρ²)·φ₂(u,m;ρ)

（ρ=0 时退化为 [uΦ(u)+φ(u)]·[mΦ(m)+φ(m)]，测试内建恒等式钉。）

EHVI 分片装配（改进体 = [z,r] 盒减前沿盒覆盖，按 x₁ 切片
m(x₁)=min{b_i: a_i≤x₁} 展开逐片期望后 W 项相消）：

    EHVI(μ,Σ) = Q(a₁,r₂) + Σ_{i=1..k} [ Q(c_i,b_i) − Q(a_i,b_i) ]

其中 c_i = min(a_{i+1}, r₁)（c_k=r₁）；空阶梯（k=0）时 EHVI=Q(r₁,r₂)。
Φ₂ 用 Genz (2004) 单变量积分式（Gauss-Legendre 128 节点，确定性向量化）：
Φ₂(h,k;ρ)=Φ(h)Φ(k)+(ρ/2π)∫₀¹ exp(−(h²−2ρxhk+k²)/(2(1−ρ²x²)))/√(1−ρ²x²) dx。

裁判独立（#118）：解析路径的裁判 = MC 蒙特卡洛逐样本 HI 走
**pareto_tools.exact_hypervolume** 现成实现（与解析路径零共享代码）+
scipy dblquad 原式二重积分 + scipy mvn cdf 外部参照（三重对拍，测试钉）。

噪声感知语义：采集协方差 = 潜在后验 Σ + 观测噪声对角（未来比较发生在
带噪观测上，qNEHVI noise-aware 口径）。噪声方差解析顺序 = 显式
``noise_variances`` > 代理内生（duck-typed ``surrogate.model.nuggets``，
mt_gp 家族，键集须与 metrics 一致）> 零（纯潜在）。

MO 面 vs T-N5 竞赛架关系：``competition_scalar.register_scalar_engine``
是**标量**采集引擎竞赛面；本模块用超体积判据自有报表（hv_curve/front/
acquisitions），**不强塞竞赛架**——标量竞赛门与 MO HV 门判据不同族，
混挂会互相污染口径。

口径与诚实边界：
- 全程**最小化**（pareto_tools 同约定）；最大化指标调用方自行取负。
- batch q>1 = 贪心 + 目标空间 **plug-in fantasy**（选中点预测均值并入
  前沿作伪观测，批内不确定度不收缩——低估待评点间耦合，如实标注）。
- 观测缺测（指标部分缺失）样本参与代理拟合（mt_gp/smt_kriging 逐指标
  掩码同约定），但**不进前沿/超体积**（M 维不完整无法定位）。
- 退化协方差（σ→0 / 秩亏，最小特征值过阈）回退确定性 HI(μ)。
- 确定性：初始设计/候选池 lhs_points 固定 seed；解析路径零随机；MC
  路径逐候选派生子 seed——同 seed 采集序列逐位复现（G4 钉）。
- 新增独立模块，既有路径零改动（G5）；消费口 = 直接构造本类，代理经
  ``surrogate_registry`` 任选（mt_gp 联合 / smt_kriging 等逐指标独立）。

约束 c-EHVI 档（aurora_p E3，预声明账本 runs/aurora_p/e3/DESIGN.md）
----------------------------------------------------------------
``constraints`` 非 None 时启用；**None 时全部约束代码路径零触发，无约束
行为/返回体逐字节不变**。形态 = Gardner et al.（ICML **2014**，Bayesian
Optimization with Inequality Constraints）乘权档的 EHVI 推广、
**自实现简化形态**：

- 约束规格二选一：字符串 ``"c"``（指标 c 的原始带号值 g(x)，**g≤0 可行**，
  scipy/optuna constraints_func 同约定）或 ``{"metric","op","target"}``
  （op ∈ {"<=", ">="}）；objective_fn 与目标同 dict 返回约束指标**原始值**。
- 约束 GP = **与目标代理分离的独立代理实例**（同工厂另起实例 / 实例形态
  deepcopy 一份），只拟约束指标，采集只取逐约束边际 (μ_j, σ_j)；目标后验
  路径零改动；只作约束的键从目标代理拟合面剥离（目标后验不被约束任务
  改变；mt_gp 内生噪声键集检查亦不被约束键触发）。
- 可行概率 P_j(x)=Φ((target_j−μ_j)/σ_j)（"<="；">=" 翻号），σ_j² 含观测
  噪声（noise-aware 同目标口径）；σ_j=0 按均值可行性取 {0,1}。
- 采集 score(x) = EHVI(μ_f,Σ_f; **可行前沿**, ref) × Π_j P_j(x)——2 维
  解析 / M>2 MC 路径之后统一乘权；EHVI 参照前沿 = 已知可行完整样本的非
  支配集（不可行/UNKNOWN 不是改进基准）。
- 样本记账与 optimizer/surrogate_loop ``constraint_values`` 同语义：逐约束
  违约量（≥0，0=可行边界，MAX_BELOW/MIN_ABOVE 口径）+ ``feasible``；约束
  指标缺测/非有限 → 两者 None（UNKNOWN 如实，不进前沿/不进约束拟合）。
- **与精确 c-EHVI 的差距（如实）**：精确量 E[HVI(Z_f)·1{Z_c 可行}] 在目标与
  约束联合后验下取；本席 E[HVI]·ΠP_j 只在目标⊥约束且约束互独立时相等——
  本席模型即分离代理，**在本席模型下该式精确**（差距在"不建目标-约束相关
  的模型"而非公式；测试以独立联合 MC 对拍钉）；批内 fantasy 只按均值可行性
  并入工作前沿，不传播约束不确定度。
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from math import pi
from typing import Any

import numpy as np
from scipy.stats import norm

from rfauto.optimization.pareto_tools import (
    default_reference_point,
    exact_hypervolume,
    nondominated_indices,
)
from rfauto.optimization.sample_design import lhs_points

__all__ = [
    "MultiObjectiveBO",
    "bivariate_normal_cdf",
    "constrained_expected_hv_improvement_2d",
    "ehvi_monte_carlo",
    "expected_box_moment",
    "expected_hv_improvement_2d",
    "hypervolume_improvement_2d",
    "normalize_constraint_specs",
    "probability_of_feasibility",
    "staircase_2d",
]

#: 约束规格合法比较符（"<=" ↔ core.objectives MAX_BELOW，">=" ↔ MIN_ABOVE）
_CONSTRAINT_OPS = ("<=", ">=")

#: Genz (2004) Φ₂ 单变量积分的 Gauss-Legendre 节点（[0,1] 区间，模块级
#: 常量一次生成——确定性 + 向量化；128 节点对 |ρ|≤0.999 尾部裕量充足，
#: 实测对 scipy mvn cdf 相对偏差 ≤1e-8 量级）
_GL_X, _GL_W = np.polynomial.legendre.leggauss(128)
_XT = (_GL_X + 1.0) / 2.0
_WT = _GL_W / 2.0

#: Φ₂ 相关性_clip 下界（|ρ|<1 严格；ρ=±1 属退化协方差走 HI(μ) 回退）
_RHO_CLIP = 1.0 - 1e-12

#: 协方差退化判阈：最小特征值 ≤ tol·max(对角) 视为秩亏（走确定性回退）
_DEGEN_TOL = 1e-12

#: MC 采样协方差 Cholesky 失败的抖动阶梯（×10 递进）
_JITTER_LADDER = (0.0, 1e-12, 1e-10, 1e-8)


def bivariate_normal_cdf(
    u: np.ndarray | float, m: np.ndarray | float, rho: np.ndarray | float,
) -> np.ndarray:
    """二维正态 CDF Φ₂(u,m;ρ)——Genz (2004) 单变量积分式，确定性。

    Φ₂(h,k;ρ) = Φ(h)Φ(k) + (ρ/2π)∫₀¹ g(x) dx，
    g(x) = exp(−(h²−2ρxhk+k²)/(2(1−ρ²x²)))/√(1−ρ²x²)。

    指数恒 ≤0（h²−2txk+k²=(h−tx)²+(1−t²)k²≥0 对 |t|<1），无溢出面。
    u/m/rho 广播；rho 逐元素 clip 到 |ρ|<1（±1 属退化协方差，上游回退）。
    """
    u_a = np.asarray(u, dtype=float)
    m_a = np.asarray(m, dtype=float)
    rho_a = np.asarray(rho, dtype=float)
    shape = np.broadcast_shapes(u_a.shape, m_a.shape, rho_a.shape)
    rho_b = np.clip(np.broadcast_to(rho_a, shape), -_RHO_CLIP, _RHO_CLIP)
    u_b = np.broadcast_to(u_a, shape)
    m_b = np.broadcast_to(m_a, shape)
    t = rho_b[..., None] * _XT  # (..., 64)
    denom = 1.0 - t * t
    expo = -(u_b[..., None] ** 2 - 2.0 * t * u_b[..., None] * m_b[..., None]
             + m_b[..., None] ** 2) / (2.0 * denom)
    g = np.exp(expo) / np.sqrt(denom)
    integral = rho_b * (g @ _WT)  # ∫₀^ρ g dt = ρ·∫₀¹ g(ρx) dx（负 ρ 自动翻号）
    return norm.cdf(u_b) * norm.cdf(m_b) + integral / (2.0 * pi)


def _psi2_standard(
    u: np.ndarray, m: np.ndarray, rho: np.ndarray,
) -> np.ndarray:
    """标准化核 Ψ₂(u,m;ρ)=E[(m−T₂)⁺(u−T₁)⁺]（T 标准双变量正态，广播）。

    Tallis 截断矩推导（CRITERIA §1）；ρ=0 恒等式 [uΦ(u)+φ(u)]·[mΦ(m)+
    φ(m)] 由测试钉（G0 前置自检）。
    """
    u_a = np.asarray(u, dtype=float)
    m_a = np.asarray(m, dtype=float)
    rho_a = np.asarray(rho, dtype=float)
    shape = np.broadcast_shapes(u_a.shape, m_a.shape, rho_a.shape)
    rho_b = np.clip(np.broadcast_to(rho_a, shape), -_RHO_CLIP, _RHO_CLIP)
    u_b = np.broadcast_to(u_a, shape)
    m_b = np.broadcast_to(m_a, shape)
    r2 = 1.0 - rho_b * rho_b
    s = np.sqrt(r2)
    p2 = bivariate_normal_cdf(u_b, m_b, rho_b)
    cu = norm.cdf((u_b - rho_b * m_b) / s)
    cm = norm.cdf((m_b - rho_b * u_b) / s)
    phi_u = norm.pdf(u_b)
    phi_m = norm.pdf(m_b)
    expo = -(u_b ** 2 - 2.0 * rho_b * u_b * m_b + m_b ** 2) / (2.0 * r2)
    phi2 = np.exp(expo) / (2.0 * pi * s)
    return ((u_b * m_b + rho_b) * p2 + u_b * phi_m * cu + m_b * phi_u * cm
            + r2 * phi2)


def _cov_degenerate_mask(covs: np.ndarray) -> np.ndarray:
    """逐候选协方差退化掩码：非对称/非正定/最小特征值过阈。"""
    covs = np.asarray(covs, dtype=float)
    sym = 0.5 * (covs + np.swapaxes(covs, -1, -2))
    eig_min = np.linalg.eigvalsh(sym)[..., 0]
    diag_max = np.maximum(sym[..., 0, 0], sym[..., 1, 1])
    scale = np.maximum(diag_max, 1e-300)
    return ~(eig_min > _DEGEN_TOL * scale)


def _q_values(
    pairs_u: np.ndarray,
    pairs_m: np.ndarray,
    means: np.ndarray,
    covs: np.ndarray,
) -> np.ndarray:
    """Q(u,m)=E[(m−Z₂)⁺(u−Z₁)⁺] 批量矩阵（2 维，(n_cand, n_pairs)）。

    退化协方差行**先分流**再走标准化路径（σ=0 直除会溢出 inf）：点质量
    回退 (m−μ₂)⁺(u−μ₁)⁺（确定性 HI 语义的原子量）。
    """
    means = np.atleast_2d(np.asarray(means, dtype=float))
    covs = np.asarray(covs, dtype=float)
    if covs.ndim == 2:
        covs = covs[None, :, :]
    pu = np.asarray(pairs_u, dtype=float)[None, :]
    pm = np.asarray(pairs_m, dtype=float)[None, :]
    n_cand = means.shape[0]
    n_pairs = pu.shape[1]
    degen = _cov_degenerate_mask(covs)
    pm_mass = (np.maximum(pm - means[:, 1:2], 0.0)
               * np.maximum(pu - means[:, 0:1], 0.0))
    q = np.empty((n_cand, n_pairs))
    if bool(np.all(degen)):
        return pm_mass
    live = ~degen
    s1 = np.sqrt(np.maximum(covs[:, 0, 0], 0.0))[:, None]
    s2 = np.sqrt(np.maximum(covs[:, 1, 1], 0.0))[:, None]
    denom = s1 * s2
    cov12 = covs[:, 0, 1][:, None]  # (n,1)——与 denom 同形，禁 (n,)×(n,1) 广播
    rho = np.where(denom > 0.0, cov12 / np.maximum(denom, 1e-300), 0.0)
    u_star = (pu - means[:, 0:1]) / np.maximum(s1, 1e-300)
    m_star = (pm - means[:, 1:2]) / np.maximum(s2, 1e-300)
    psi = _psi2_standard(u_star[live], m_star[live], rho[live])
    q[live] = (denom[live]) * psi
    q[degen] = pm_mass[degen]
    return q


def staircase_2d(
    front: Sequence[Sequence[float]], ref: Sequence[float],
) -> list[tuple[float, float]]:
    """前沿 → ref 盒内阶梯点列（f₁ 升序、f₂ 严格降序；重复/支配点剔除）。

    ref 盒外点（a≥r₁ 或 b≥r₂）盒贡献恒空，先过滤——对 w.r.t. ref 的
    超体积与 EHVI 无影响（其覆盖区间为空）。
    """
    r1, r2 = float(ref[0]), float(ref[1])
    pts = sorted(
        (float(p[0]), float(p[1])) for p in front
        if float(p[0]) < r1 and float(p[1]) < r2)
    out: list[tuple[float, float]] = []
    for a, b in pts:
        if out and a <= out[-1][0]:
            continue  # 同 f₁（排序保证 b 更大）或更小 f₁：被阶梯末点支配
        if out and b >= out[-1][1]:
            continue  # f₂ 不更小：被支配
        out.append((a, b))
    return out


def hypervolume_improvement_2d(
    z: Sequence[float], front: Sequence[Sequence[float]],
    ref: Sequence[float],
) -> float:
    """确定性单点超体积改进 HI(z)=HV(front∪{z})−HV(front)（2 维最小化）。

    裁判 = pareto_tools.exact_hypervolume（单源复用；亦为解析 EHVI 的
    MC 对拍原子量，#118 裁判独立）。
    """
    ref_t = tuple(float(v) for v in ref)
    f_pts = [tuple(float(v) for v in p) for p in front]
    z_t = (float(z[0]), float(z[1]))
    base = exact_hypervolume(f_pts, ref_t) if f_pts else 0.0
    return float(exact_hypervolume([*f_pts, z_t], ref_t) - base)


def expected_box_moment(
    u: float, m: float, mean: Sequence[float], cov: Sequence[Sequence[float]],
) -> float:
    """Q(u,m)=E[(m−Z₂)⁺(u−Z₁)⁺]，Z~N₂(mean,cov)（2 维；G0b 对拍原子量）。"""
    q = _q_values(np.array([float(u)]), np.array([float(m)]),
                  np.asarray(mean, dtype=float)[None, :],
                  np.asarray(cov, dtype=float)[None, :, :])
    return float(q[0, 0])


def expected_hv_improvement_2d(
    mean: Sequence[float],
    cov: Sequence[Sequence[float]],
    front: Sequence[Sequence[float]],
    ref: Sequence[float],
) -> float:
    """解析 EHVI（2 维最小化，单候选；CRITERIA §1 分片装配式）。

    退化协方差（σ→0/秩亏）回退确定性 HI(μ)。数学正确的 EHVI≥0；浮点
    噪声级负值钳 0（真负值属公式缺陷，由 G0c MC 对拍门拦截）。
    """
    ehvi = _ehvi_batch_2d(
        np.asarray(mean, dtype=float)[None, :],
        np.asarray(cov, dtype=float)[None, :, :], front, ref)
    return float(ehvi[0])


def _ehvi_batch_2d(
    means: np.ndarray,
    covs: np.ndarray,
    front: Sequence[Sequence[float]],
    ref: Sequence[float],
) -> np.ndarray:
    """批候选解析 EHVI（(n,) 向量；环内 2 维采集评分单源实现）。"""
    stair = staircase_2d(front, ref)
    r1, r2 = float(ref[0]), float(ref[1])
    if stair:
        # 装配式：Q(a₁,r₂) + Σᵢ[Q(cᵢ,bᵢ) − Q(aᵢ,bᵢ)]，cᵢ=min(a_{i+1},r₁)
        a_seq = [p[0] for p in stair]
        b_seq = [p[1] for p in stair]
        c_seq = [*a_seq[1:], r1]
        pairs_u = np.array([a_seq[0], *c_seq, *a_seq])
        pairs_m = np.array([r2, *b_seq, *b_seq])
        coefs = np.array([1.0, *([1.0] * len(stair)),
                          *([-1.0] * len(stair))])
    else:
        pairs_u = np.array([r1])
        pairs_m = np.array([r2])
        coefs = np.array([1.0])
    q = _q_values(pairs_u, pairs_m, means, covs)
    return np.maximum(q @ coefs, 0.0)


def ehvi_monte_carlo(
    mean: Sequence[float],
    cov: Sequence[Sequence[float]],
    front: Sequence[Sequence[float]],
    ref: Sequence[float],
    n_samples: int = 20000,
    seed: int = 0,
) -> float:
    """MC 预估 EHVI（任意 M≥2；逐样本 HI 裁判 = pareto_tools 现成实现）。

    Z~N(mean,cov) 抽 n_samples 样本，均值化 HI；与解析路径（闭式积分）
    非同源（#118 裁判独立）。协方差 Cholesky 失败走抖动阶梯（×10 递进
    3 档，仍失败显式报错不静默）。
    """
    mean_a = np.asarray(mean, dtype=float).ravel()
    cov_a = np.asarray(cov, dtype=float)
    m_dim = int(mean_a.size)
    if cov_a.shape != (m_dim, m_dim):
        raise ValueError(
            f"cov shape {cov_a.shape} 与 mean 维数 {m_dim} 不一致")
    if int(n_samples) < 1:
        raise ValueError(f"n_samples 必须 ≥1，收到 {n_samples}")
    ref_t = tuple(float(v) for v in ref)
    f_pts = [tuple(float(v) for v in p) for p in front]
    base = exact_hypervolume(f_pts, ref_t) if f_pts else 0.0
    chol = None
    for jitter in _JITTER_LADDER:
        try:
            chol = np.linalg.cholesky(cov_a + jitter * np.eye(m_dim))
            break
        except np.linalg.LinAlgError:
            continue
    if chol is None:
        raise ValueError(
            "ehvi_monte_carlo：协方差 Cholesky 失败（抖动阶梯用尽），"
            "拒绝静默采样")
    rng = np.random.default_rng(int(seed))
    xi = rng.standard_normal((int(n_samples), m_dim))
    draws = mean_a + xi @ chol.T
    total = 0.0
    for z in draws:
        total += exact_hypervolume([*f_pts, tuple(float(v) for v in z)],
                                   ref_t) - base
    return float(total / int(n_samples))


# ─── 约束 c-EHVI 档（E3）：规格/违约量/可行概率/乘权采集 ──────────────────


def normalize_constraint_specs(
    constraints: Sequence[str | dict[str, Any]],
) -> list[dict[str, Any]]:
    """约束规格归一化 → ``[{"metric", "op", "target"}, ...]``（E3 形态）。

    每条二选一：字符串 ``"c"`` ≡ ``{"metric": "c", "op": "<=", "target": 0.0}``
    （原始带号约束函数 g≤0 可行）；字典须含 metric（非空 str）、op ∈
    {"<=", ">="}，target 缺省 0.0（须有限）。空序列显式拒绝（无约束请传
    None——空列表当"无约束"会把约束档静默降为无约束档）。
    """
    if constraints is None or isinstance(constraints, (str, bytes, dict)):
        raise ValueError(
            "constraints 须为约束规格序列（list/tuple），收到 "
            f"{type(constraints).__name__}")
    specs: list[dict[str, Any]] = []
    for i, raw in enumerate(constraints):
        if isinstance(raw, str):
            spec = {"metric": raw, "op": "<=", "target": 0.0}
        elif isinstance(raw, dict):
            spec = {"metric": raw.get("metric"),
                    "op": raw.get("op", "<="),
                    "target": raw.get("target", 0.0)}
        else:
            raise ValueError(
                f"constraints[{i}] 须为指标键字符串或 {{metric,op,target}} "
                f"字典，收到 {type(raw).__name__}")
        metric = spec["metric"]
        if not isinstance(metric, str) or not metric:
            raise ValueError(f"constraints[{i}].metric 须为非空字符串")
        op = str(spec["op"])
        if op not in _CONSTRAINT_OPS:
            raise ValueError(
                f"constraints[{i}].op 须为 {_CONSTRAINT_OPS} 之一，收到 {op!r}")
        try:
            target = float(spec["target"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"constraints[{i}].target 须为数值，收到 {spec['target']!r}"
            ) from exc
        if not np.isfinite(target):
            raise ValueError(f"constraints[{i}].target 须有限，收到 {target}")
        specs.append({"metric": metric, "op": op, "target": target})
    if not specs:
        raise ValueError("constraints 为空序列——无约束请传 None（不接受空列表"
                         "静默降为无约束档）")
    return specs


def _violations_from_metrics(
    metrics: dict[str, Any], specs: Sequence[dict[str, Any]],
) -> list[float] | None:
    """逐约束违约量（≥0，0=可行边界；MAX_BELOW/MIN_ABOVE 口径）。

    任一约束指标缺席/非有限 → 整体 None（UNKNOWN：不能凭部分约束断言
    可行，#122）。
    """
    out: list[float] = []
    for spec in specs:
        raw = metrics.get(spec["metric"])
        if raw is None or not isinstance(raw, (int, float)) \
                or not np.isfinite(float(raw)):
            return None
        val = float(raw)
        tgt = float(spec["target"])
        out.append(max(val - tgt, 0.0) if spec["op"] == "<="
                   else max(tgt - val, 0.0))
    return out


def probability_of_feasibility(
    means: np.ndarray | Sequence[Sequence[float]],
    stds: np.ndarray | Sequence[Sequence[float]],
    specs: Sequence[dict[str, Any]],
) -> np.ndarray:
    """可行概率 Π_j P(c_j 满足约束)（逐候选，(n,)）——确定性正态 CDF。

    means/stds 形 (n, S) 与 specs 逐列对齐（S=约束条数；1 维输入视作单候选）。
    P_j = Φ((target_j−μ_j)/σ_j)（"<="）或 Φ((μ_j−target_j)/σ_j)（">="）。
    端点：σ_j=0 → 按均值可行性取 {0,1}（含 μ=target 边界=可行）；|z| 大
    由 scipy 尾部给 0/1，无 NaN。σ<0 或非有限 μ/σ 显式拒绝（调用方缺陷，
    不静默钳位）。约束互独立假设（简化形态声明见模块 docstring）。
    """
    mu = np.atleast_2d(np.asarray(means, dtype=float))
    sd = np.atleast_2d(np.asarray(stds, dtype=float))
    n_spec = len(specs)
    if mu.shape != sd.shape or mu.ndim != 2 or mu.shape[1] != n_spec:
        raise ValueError(
            f"means/stds 形状须同为 (n, {n_spec})，收到 {mu.shape}/{sd.shape}")
    if not (np.all(np.isfinite(mu)) and np.all(np.isfinite(sd))):
        raise ValueError("约束后验 means/stds 含非有限值，拒绝计算可行概率")
    if np.any(sd < 0.0):
        raise ValueError("约束后验 stds 含负值，拒绝计算可行概率")
    if n_spec == 0:
        return np.ones(mu.shape[0])
    sign = np.array([1.0 if s["op"] == "<=" else -1.0 for s in specs])
    target = np.array([float(s["target"]) for s in specs])
    margin = sign[None, :] * (target[None, :] - mu)  # ≥0 ⇔ 均值可行
    with np.errstate(divide="ignore", invalid="ignore"):
        z = margin / sd
    z = np.where(sd > 0.0, z, np.where(margin >= 0.0, np.inf, -np.inf))
    return np.prod(norm.cdf(z), axis=1)


def constrained_expected_hv_improvement_2d(
    mean: Sequence[float],
    cov: Sequence[Sequence[float]],
    c_mean: Sequence[float],
    c_std: Sequence[float],
    constraints: Sequence[str | dict[str, Any]],
    front: Sequence[Sequence[float]],
    ref: Sequence[float],
) -> float:
    """单候选约束 c-EHVI（2 维最小化）= EHVI(mean,cov;front,ref) × Π_j P_j。

    c_mean/c_std 为逐约束边际后验（与 constraints 逐条对齐，S 条）；front
    须为**可行**前沿（调用方口径）。退化协方差/σ_c=0 两端均有定义：
    HI(μ)×{0,1}（G-E3 手算锚）。
    """
    specs = normalize_constraint_specs(constraints)
    pf = probability_of_feasibility(
        np.asarray(c_mean, dtype=float)[None, :],
        np.asarray(c_std, dtype=float)[None, :], specs)
    return float(expected_hv_improvement_2d(mean, cov, front, ref) * pf[0])


class MultiObjectiveBO:
    """模型驱动多目标 BO 采集环（Noise-Aware EHVI 贪心；最小化口径）。

    Args:
        bounds: {参数名: (low, high)}，非空，low<high。
        metrics: 指标键列表（**≥2**；=1 为退化标量问题显式拒绝并指引
            单目标 SBO 通道 ``rfauto.optimization.surrogate_loop``）。
        surrogate: 代理（二选一）：已构造未拟合代理实例（须含 ``fit``，
            且逐点后验走 ``predict_joint``→(dict, M×M cov) 联合口——
            mt_gp；或缺席时回退 ``predict``+``uncertainty`` 逐指标独立
            口构造对角协方差），或零参工厂 callable（每轮产新实例）。
        ref_point: 超体积参考点（长度=指标数）；None 时由初始设计前沿
            经 pareto_tools.default_reference_point 冻结（跨臂 HV 对比
            建议显式传入同值 ref）。
        n_init: 初始 LHS 设计点数（≥2）。
        n_iter: BO 迭代轮数（每轮采 batch_size 点真评估）。
        batch_size: 每轮采集批量 q（≥1；q>1 贪心+plug-in fantasy）。
        n_candidates: 每轮 LHS 候选池规模（≥1）。
        seed: 确定性种子（初始设计/候选池/MC 子流全由它派生）。
        noise_variances: {指标: 观测噪声方差}（noise-aware 对角；None=
            先试代理内生 ``model.nuggets``（键集须与 metrics 一致），
            再退零）。
        mc_samples: M>2 时逐候选 MC 样本数（2 维解析路径不消费）。
        fantasy: q>1 时是否启用目标空间 plug-in fantasy（缺省 True）。
        constraints: 约束规格序列（E3 c-EHVI 档；**None=无约束档，行为/
            返回体逐字节不变**）。每条为指标键字符串（原始带号 g≤0 可行）
            或 ``{"metric","op","target"}``（op ∈ {"<=", ">="}）；
            objective_fn 须与目标同 dict 返回约束指标原始值。约束代理 =
            同 surrogate 工厂另起的独立实例（实例形态 deepcopy 一份；
            deepcopy 失败显式报错指引改传工厂）。

    run(objective_fn) 返回 dict：samples（全评估）、hv_curve（逐批前沿
    HV，[0]=初始设计后）、front/front_params（终态非支配集）、
    acquisitions（逐批采集参数）、ref_point、n_evaluations、info。
    约束档另补：constraints（归一化规格回显）、n_feasible、
    n_unknown_feasibility、front_constraint_values（前沿逐点违约量）；
    samples 逐条补 constraint_values/feasible（UNKNOWN 为 None）；
    hv_curve/front 均按**可行前沿**；info.kind="mo_bo_cehvi_greedy"。
    """

    def __init__(
        self,
        bounds: dict[str, tuple[float, float]],
        metrics: Sequence[str],
        surrogate: Any,
        *,
        ref_point: Sequence[float] | None = None,
        n_init: int = 6,
        n_iter: int = 15,
        batch_size: int = 1,
        n_candidates: int = 256,
        seed: int = 0,
        noise_variances: dict[str, float] | None = None,
        mc_samples: int = 128,
        fantasy: bool = True,
        constraints: Sequence[str | dict[str, Any]] | None = None,
    ) -> None:
        if not bounds:
            raise ValueError("bounds 必须非空 dict（{参数名: (low, high)}）")
        self.bounds = {k: (float(v[0]), float(v[1]))
                       for k, v in dict(bounds).items()}
        for k, (lo, hi) in self.bounds.items():
            if not (np.isfinite(lo) and np.isfinite(hi)) or not lo < hi:
                raise ValueError(
                    f"bounds[{k}] 非法：须有限且 low<high，收到 {(lo, hi)}")
        self.metrics = [str(k) for k in metrics]
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError(f"metrics 含重复键: {self.metrics}")
        if len(self.metrics) == 1:
            raise ValueError(
                "指标数 1 为退化标量问题：MO 档（EHVI/超体积判据）要求"
                " ≥2 指标，请走单目标 SBO 通道"
                "（rfauto.optimization.surrogate_loop / run_surrogate_loop，"
                "gp 采集同族）；如需以多代理竞赛求解单指标请用 "
                "competition_scalar.register_scalar_engine")
        if len(self.metrics) < 2:
            raise ValueError(
                f"metrics 必须含 ≥2 个指标，收到 {len(self.metrics)} 个")
        if ref_point is not None:
            if len(ref_point) != len(self.metrics):
                raise ValueError(
                    f"ref_point 长度 {len(ref_point)} 与指标数 "
                    f"{len(self.metrics)} 不一致")
            self.ref_point: list[float] | None = [float(v) for v in ref_point]
        else:
            self.ref_point = None
        self.n_init = int(n_init)
        self.n_iter = int(n_iter)
        self.batch_size = int(batch_size)
        self.n_candidates = int(n_candidates)
        self.seed = int(seed)
        self.mc_samples = int(mc_samples)
        self.fantasy = bool(fantasy)
        for name, val, low in (("n_init", self.n_init, 2),
                               ("n_iter", self.n_iter, 0),
                               ("batch_size", self.batch_size, 1),
                               ("n_candidates", self.n_candidates, 1),
                               ("mc_samples", self.mc_samples, 1)):
            if val < low:
                raise ValueError(f"{name} 必须 ≥{low}，收到 {val}")
        if self.batch_size > self.n_candidates:
            raise ValueError(
                f"batch_size ({self.batch_size}) 不得超过 n_candidates "
                f"({self.n_candidates})——批内贪心从候选池不放回选取")
        self.noise_variances = (
            {str(k): float(v) for k, v in noise_variances.items()}
            if noise_variances is not None else None)
        if self.noise_variances is not None:
            bad = {k: v for k, v in self.noise_variances.items() if v < 0.0}
            if bad:
                raise ValueError(f"noise_variances 含负值: {bad}")
        if callable(surrogate) and not hasattr(surrogate, "fit"):
            self._surrogate_obj = None
            self._surrogate_factory: Callable[[], Any] = surrogate
        elif hasattr(surrogate, "fit"):
            self._surrogate_obj: Any = surrogate  # 同实例复拟合（fit 可重入）
            self._surrogate_factory = lambda: None  # 占位：_obj 优先消费
        else:
            raise ValueError(
                "surrogate 须为含 fit() 的代理实例或零参工厂 callable")
        # ── E3 约束档（None=无约束，下列全部零触发）────────────────────
        self.constraints: list[dict[str, Any]] | None = None
        self._constraint_keys: list[str] = []
        self._constraint_only_keys: set[str] = set()
        self._constraint_surrogate_obj: Any = None
        if constraints is not None:
            self.constraints = normalize_constraint_specs(constraints)
            seen: list[str] = []
            for spec in self.constraints:
                if spec["metric"] not in seen:
                    seen.append(spec["metric"])
            self._constraint_keys = seen
            # 只作约束、不作目标的键：从目标代理拟合面剥离（目标后验不被
            # 约束任务进 coregionalization 改变；mt_gp 内生噪声键集检查亦
            # 不被约束键触发）——既是目标又是约束的键保留在目标面
            self._constraint_only_keys = set(seen) - set(self.metrics)
            if self._surrogate_obj is not None:
                try:
                    self._constraint_surrogate_obj = copy.deepcopy(
                        self._surrogate_obj)
                except Exception as exc:  # 任意失败均指引改传工厂
                    raise ValueError(
                        "约束档需要独立的约束代理实例，传入代理实例无法 "
                        f"deepcopy（{type(exc).__name__}: {exc}）——请改传"
                        "零参工厂 callable") from exc

    # ── 内部：代理后验/噪声解析 ────────────────────────────────────────

    def _new_surrogate(self) -> Any:
        if self._surrogate_obj is not None:
            return self._surrogate_obj
        return self._surrogate_factory()

    def _new_constraint_surrogate(self) -> Any:
        """约束代理实例（E3）：实例形态复用 deepcopy 件，工厂形态另起新件。"""
        if self._constraint_surrogate_obj is not None:
            return self._constraint_surrogate_obj
        return self._surrogate_factory()

    def _resolve_noise(
        self, model: Any, keys: Sequence[str] | None = None,
    ) -> np.ndarray:
        """观测噪声对角（noise-aware）：显式参数 > 代理内生 > 零。

        keys 缺省=目标指标（无约束路径逐字节不变）；约束档传约束键列表对
        约束代理同口径解析（E3）。
        """
        keys_out = list(self.metrics) if keys is None else [str(k) for k in keys]
        if self.noise_variances is not None:
            return np.array([self.noise_variances.get(k, 0.0)
                             for k in keys_out])
        inner = getattr(model, "model", None)
        nuggets = getattr(inner, "nuggets", None)
        raw_keys = getattr(inner, "keys", None)
        # W6-1 P2：方法形 keys（dict.keys 绑定方法）调用会 TypeError——
        # 仅接受 list/tuple/set 序列形，其余按无内生噪声处理。
        keys = list(raw_keys) if isinstance(raw_keys, (list, tuple, set)) else []
        if nuggets is not None and keys:
            extra = set(keys) - set(keys_out)
            if extra:
                raise ValueError(
                    f"代理内生噪声含未知指标 {sorted(extra)}：请显式传 "
                    "noise_variances 消除歧义")
            nug = np.asarray(nuggets, dtype=float)
            # 按键名查找无位置歧义；指标缺测（键缺席）该维噪声取 0——
            # 该指标不可建模时后验检查会给出显式报错
            return np.array([float(nug[keys.index(k)]) if k in keys else 0.0
                             for k in keys_out])
        return np.zeros(len(keys_out))

    def _posterior_one(
        self, model: Any, params: dict[str, float], noise: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """单候选 (μ (M,), Σ (M,M)+噪声对角)；联合口优先，独立口回退。"""
        if hasattr(model, "predict_joint"):
            mu_d, cov = model.predict_joint(params)
            missing = [k for k in self.metrics if k not in mu_d]
            if missing:
                raise ValueError(
                    f"代理 predict_joint 缺指标 {missing}（指标键 <3 有效点"
                    "被跳过？）——MO 环要求全部指标可建模，请增补观测或"
                    "更换代理")
            mu = np.array([float(mu_d[k]) for k in self.metrics])
            cov_a = np.asarray(cov, dtype=float)
            if cov_a.shape != (len(self.metrics), len(self.metrics)):
                raise ValueError(
                    f"predict_joint 协方差 shape {cov_a.shape} 与指标数 "
                    f"{len(self.metrics)} 不一致")
        else:
            if hasattr(model, "predict_with_std"):
                # 单遍 mean±σ（DP-16 U3 口；KRG 等逐点双查减半）
                pw = model.predict_with_std(params)
                missing = [k for k in self.metrics if k not in pw]
                if missing:
                    raise ValueError(
                        f"代理 predict_with_std 缺指标 {missing}——MO 环要求"
                        "全部指标可建模")
                mu = np.array([float(pw[k][0]) for k in self.metrics])
                var = np.zeros(len(self.metrics))
                for j, k in enumerate(self.metrics):
                    sd = pw[k][1]
                    if sd is not None:
                        var[j] = max(float(sd), 0.0) ** 2
            else:
                pred = model.predict(params)
                missing = [k for k in self.metrics if k not in pred]
                if missing:
                    raise ValueError(
                        f"代理 predict 缺指标 {missing}——MO 环要求全部指标"
                        "可建模")
                mu = np.array([float(pred[k]) for k in self.metrics])
                unc = model.uncertainty(params) if hasattr(
                    model, "uncertainty") else None
                var = np.zeros(len(self.metrics))
                if unc is not None:
                    for j, k in enumerate(self.metrics):
                        sd = unc.get(k)
                        if sd is not None:
                            var[j] = max(float(sd), 0.0) ** 2
            cov_a = np.diag(var)
        cov_a = cov_a + np.diag(noise)
        return mu, 0.5 * (cov_a + cov_a.T)

    # ── 内部：前沿/超体积面 ────────────────────────────────────────────

    def _complete_points(self, samples: list[dict[str, Any]],
                         ) -> tuple[list[list[float]], list[dict[str, float]]]:
        """完整观测样本的目标向量与参数（缺测/非有限剔除，如实口径）。"""
        pts: list[list[float]] = []
        prs: list[dict[str, float]] = []
        for s in samples:
            met = s["metrics"]
            if all(k in met and np.isfinite(float(met[k]))
                   for k in self.metrics):
                pts.append([float(met[k]) for k in self.metrics])
                prs.append(dict(s["params"]))
        return pts, prs

    def _front(self, samples: list[dict[str, Any]],
               ) -> tuple[list[list[float]], list[dict[str, float]]]:
        pts, prs = self._complete_points(samples)
        if not pts:
            return [], []
        keep = nondominated_indices(pts)
        return [pts[i] for i in keep], [prs[i] for i in keep]

    def _hv(self, front: list[list[float]], ref: Sequence[float]) -> float:
        return float(exact_hypervolume(front, tuple(float(v) for v in ref))) \
            if front else 0.0

    # ── 内部：约束档（E3；constraints=None 时以下全部不被调用）──────────

    def _make_sample(self, x: dict[str, float], met: dict[str, float],
                     ) -> dict[str, Any]:
        """样本记账：无约束 = {params, metrics}（逐字节不变）；约束档补
        constraint_values（逐约束违约量 ≥0）/feasible（UNKNOWN=None）。"""
        sample: dict[str, Any] = {"params": dict(x), "metrics": met}
        if self.constraints is not None:
            viol = _violations_from_metrics(met, self.constraints)
            sample["constraint_values"] = viol
            sample["feasible"] = (all(v <= 0.0 for v in viol)
                                  if viol is not None else None)
        return sample

    def _objective_fit_metrics(self, met: dict[str, float]) -> dict[str, float]:
        """目标代理拟合面：无约束 = 原 dict 拷贝（逐字节不变）；约束档剥离
        只作约束的键（目标后验不被约束任务改变）。"""
        if self.constraints is None:
            return dict(met)
        return {k: v for k, v in met.items()
                if k not in self._constraint_only_keys}

    def _feasible_front(self, samples: list[dict[str, Any]],
                        ) -> tuple[list[list[float]], list[dict[str, float]],
                                   list[list[float]]]:
        """已知可行完整样本的非支配集（front, front_params, 逐点违约量）。"""
        pts: list[list[float]] = []
        prs: list[dict[str, float]] = []
        cvs: list[list[float]] = []
        for s in samples:
            if s.get("feasible") is not True:
                continue
            met = s["metrics"]
            if all(k in met and np.isfinite(float(met[k]))
                   for k in self.metrics):
                pts.append([float(met[k]) for k in self.metrics])
                prs.append(dict(s["params"]))
                cvs.append([float(v) for v in s["constraint_values"]])
        if not pts:
            return [], [], []
        keep = nondominated_indices(pts)
        return ([pts[i] for i in keep], [prs[i] for i in keep],
                [cvs[i] for i in keep])

    def _fit_constraint_surrogate(self, samples: list[dict[str, Any]]) -> Any:
        """约束代理拟合（只喂约束指标；缺测键按代理掩码约定跳过）。"""
        keys = self._constraint_keys
        rows = [{"params": dict(s["params"]),
                 "metrics": {k: float(s["metrics"][k]) for k in keys
                             if k in s["metrics"]
                             and np.isfinite(float(s["metrics"][k]))}}
                for s in samples]
        if not any(r["metrics"] for r in rows):
            raise ValueError(
                f"约束指标 {keys} 无任何有限观测——约束档无法建约束代理；"
                "请检查 objective_fn 是否返回约束指标原始值（#122 如实）")
        model = self._new_constraint_surrogate()
        try:
            model.fit(rows)
        except Exception as exc:
            raise ValueError(
                f"约束代理拟合失败（约束指标 {keys}）：{type(exc).__name__}: "
                f"{exc}") from exc
        return model

    def _constraint_marginals_one(
        self, model: Any, params: dict[str, float], noise: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """逐约束键边际 (μ (K,), σ (K,))，σ² 含观测噪声；键名口无位置歧义。

        解析顺序 predict_with_std > predict+uncertainty > predict（无不确定
        度口 σ=0，可行概率退化为均值硬判——与目标路径同约定）。
        """
        keys = self._constraint_keys
        if hasattr(model, "predict_with_std"):
            pw = model.predict_with_std(params)
            missing = [k for k in keys if k not in pw]
            if missing:
                raise ValueError(
                    f"约束代理 predict_with_std 缺约束指标 {missing}（有效"
                    "观测 <3 被跳过？）——约束档要求全部约束可建模")
            mu = np.array([float(pw[k][0]) for k in keys])
            var = np.array([max(float(pw[k][1]), 0.0) ** 2
                            if pw[k][1] is not None else 0.0 for k in keys])
        else:
            pred = model.predict(params)
            missing = [k for k in keys if k not in pred]
            if missing:
                raise ValueError(
                    f"约束代理 predict 缺约束指标 {missing}（有效观测 <3 被"
                    "跳过？）——约束档要求全部约束可建模")
            mu = np.array([float(pred[k]) for k in keys])
            unc = model.uncertainty(params) if hasattr(
                model, "uncertainty") else None
            var = np.zeros(len(keys))
            if unc is not None:
                for j, k in enumerate(keys):
                    sd = unc.get(k)
                    if sd is not None:
                        var[j] = max(float(sd), 0.0) ** 2
        var = var + np.asarray(noise, dtype=float)
        return mu, np.sqrt(np.maximum(var, 0.0))

    def _constraint_posterior_batch(
        self, model: Any, pool: list[dict[str, float]], noise: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """候选池逐约束**规格**边际 (means (n,S), stds (n,S))——同键多规格
        共享该键边际。"""
        assert self.constraints is not None
        keys = self._constraint_keys
        col = [keys.index(spec["metric"]) for spec in self.constraints]
        means = np.empty((len(pool), len(col)))
        stds = np.empty((len(pool), len(col)))
        for i, x in enumerate(pool):
            mu, sd = self._constraint_marginals_one(model, x, noise)
            means[i] = mu[col]
            stds[i] = sd[col]
        return means, stds

    def _mean_violation(self, means: np.ndarray) -> np.ndarray:
        """均值点逐候选总违约量 Σ_j max(sign·(μ_j−target_j),0)（回退序用）。"""
        assert self.constraints is not None
        sign = np.array([1.0 if s["op"] == "<=" else -1.0
                         for s in self.constraints])
        target = np.array([float(s["target"]) for s in self.constraints])
        return np.sum(np.maximum(sign[None, :] * (means - target[None, :]),
                                 0.0), axis=1)

    # ── 内部：采集评分 ─────────────────────────────────────────────────

    def _score_candidates(
        self,
        model: Any,
        pool: list[dict[str, float]],
        front: list[list[float]],
        ref: Sequence[float],
        noise: np.ndarray,
        it: int,
        q: int,
    ) -> np.ndarray:
        """候选池 EHVI 评分（2 维解析批量 / M>2 逐候选 MC）。"""
        m_dim = len(self.metrics)
        means = np.empty((len(pool), m_dim))
        covs = np.empty((len(pool), m_dim, m_dim))
        for i, x in enumerate(pool):
            mu, cov = self._posterior_one(model, x, noise)
            means[i], covs[i] = mu, cov
        if m_dim == 2:
            return _ehvi_batch_2d(means, covs, front, ref)
        ref_t = tuple(float(v) for v in ref)
        f_pts = [tuple(float(v) for v in p) for p in front]
        base = exact_hypervolume(f_pts, ref_t) if f_pts else 0.0
        scores = np.zeros(len(pool))
        for i in range(len(pool)):
            degen = bool(_cov_degenerate_mask(covs[i][None, :, :])[0])
            if degen:
                z = tuple(float(v) for v in means[i])
                # 空前沿时 base=0，HV({z}) 即改进量（与解析口径一致）
                scores[i] = exact_hypervolume([*f_pts, z], ref_t) - base
                continue
            chol = None
            for jitter in _JITTER_LADDER:
                try:
                    chol = np.linalg.cholesky(
                        covs[i] + jitter * np.eye(m_dim))
                    break
                except np.linalg.LinAlgError:
                    continue
            if chol is None:
                raise ValueError(
                    "M>2 MC 评分：候选协方差 Cholesky 失败（抖动阶梯用尽）")
            rng = np.random.default_rng([self.seed, int(it), int(q), i])
            xi = rng.standard_normal((self.mc_samples, m_dim))
            draws = means[i] + xi @ chol.T
            acc = 0.0
            for z in draws:
                acc += exact_hypervolume(
                    [*f_pts, tuple(float(v) for v in z)], ref_t) - base
            scores[i] = max(acc / self.mc_samples, 0.0)
        return scores

    # ── 主环 ───────────────────────────────────────────────────────────

    def run(
        self,
        objective_fn: Callable[[dict[str, float]], dict[str, float]],
        metric_observer: Callable[[dict[str, float], dict[str, float]],
                                  dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        """运行 MO-BO 环（初始 LHS → 逐轮 EHVI 采集批 → 真评估喂回）。

        objective_fn: {参数} → {指标数值}（最小化口径）；metric_observer:
        可选观测模型 (params, metrics) → 实际记录 metrics（异位/缺测模拟
        ——缺测指标仍参与代理拟合但不进前沿/HV）。
        """
        constrained = self.constraints is not None
        samples: list[dict[str, Any]] = []

        def _observe(x: dict[str, float], raw: dict[str, float]) -> dict:
            met = {k: float(v) for k, v in dict(raw).items()
                   if isinstance(v, (int, float))
                   and np.isfinite(float(v))}
            if metric_observer is not None:
                met = {k: float(v) for k, v in
                       dict(metric_observer(dict(x), met)).items()
                       if np.isfinite(float(v))}
            return met

        def _front_now() -> tuple[list[list[float]], list[dict[str, float]],
                                  list[list[float]]]:
            if constrained:
                return self._feasible_front(samples)
            f, p = self._front(samples)
            return f, p, []

        for x in lhs_points(self.bounds, self.n_init,
                            seed=self.seed)["points"]:
            met = _observe(x, objective_fn(x))
            samples.append(self._make_sample(x, met))

        if self.ref_point is None:
            pts, _ = self._complete_points(samples)
            if not pts:
                raise ValueError(
                    "初始设计无任何完整指标观测：无法冻结缺省参考点，"
                    "请显式传 ref_point 或检查 objective_fn")
            self.ref_point = default_reference_point(pts)
        ref = self.ref_point

        front, front_params, front_cvals = _front_now()
        hv_curve = [self._hv(front, ref)]
        acquisitions: list[dict[str, float]] = []
        noise_used: np.ndarray | None = None
        c_noise_used: np.ndarray | None = None
        n_feasibility_fallback = 0

        for it in range(self.n_iter):
            model = self._new_surrogate()
            model.fit([{"params": dict(s["params"]),
                        "metrics": self._objective_fit_metrics(s["metrics"])}
                       for s in samples])
            noise = self._resolve_noise(model)
            noise_used = noise
            front, front_params, front_cvals = _front_now()
            c_model: Any = None
            c_noise: np.ndarray | None = None
            if constrained:
                c_model = self._fit_constraint_surrogate(samples)
                c_noise = self._resolve_noise(c_model, self._constraint_keys)
                c_noise_used = c_noise
            pool = lhs_points(self.bounds, self.n_candidates,
                              seed=self.seed + 7919 * (it + 1))["points"]
            work_front = [list(p) for p in front]
            batch: list[dict[str, float]] = []
            for q in range(self.batch_size):
                if not pool:
                    break
                scores = self._score_candidates(model, pool, work_front,
                                                ref, noise, it, q)
                if constrained:
                    assert c_noise is not None and self.constraints is not None
                    c_means, c_stds = self._constraint_posterior_batch(
                        c_model, pool, c_noise)
                    pf = probability_of_feasibility(c_means, c_stds,
                                                    self.constraints)
                    scores = scores * pf  # c-EHVI 乘权（路径无关）
                    if not np.any(scores > 0.0):
                        # 全候选 EHVI×PF 恒 0（PF 下溢/无改进）：按可行概率
                        # 回退，仍全 0 则按均值总违约量最小——避免退化为
                        # "恒选池首点"；次数记入 info 如实
                        n_feasibility_fallback += 1
                        scores = (pf if np.any(pf > 0.0)
                                  else -self._mean_violation(c_means))
                best = int(np.argmax(scores))  # 平局取最小索引（确定性）
                x_star = pool.pop(best)
                batch.append(x_star)
                acquisitions.append(dict(x_star))
                if self.fantasy and q + 1 < self.batch_size:
                    mu, _ = self._posterior_one(model, x_star, noise)
                    fantasy_ok = True
                    if constrained:
                        assert c_noise is not None and self.constraints is not None
                        c_mu, _c_sd = self._constraint_marginals_one(
                            c_model, x_star, c_noise)
                        viol = _violations_from_metrics(
                            dict(zip(self._constraint_keys,
                                     (float(v) for v in c_mu), strict=True)),
                            self.constraints)
                        # plug-in fantasy 仅在均值可行时并入工作前沿
                        fantasy_ok = viol is not None and all(
                            v <= 0.0 for v in viol)
                    if fantasy_ok:
                        work_front.append([float(v) for v in mu])
            for x in batch:
                met = _observe(x, objective_fn(x))
                samples.append(self._make_sample(x, met))
            front, front_params, front_cvals = _front_now()
            hv_curve.append(self._hv(front, ref))

        result: dict[str, Any] = {
            "ok": True,
            "samples": samples,
            "hv_curve": hv_curve,
            "front": front,
            "front_params": front_params,
            "ref_point": list(ref),
            "acquisitions": acquisitions,
            "n_evaluations": len(samples),
            "info": {
                "kind": ("mo_bo_cehvi_greedy" if constrained
                         else "mo_bo_ehvi_greedy"),
                "n_init": self.n_init,
                "n_iter": self.n_iter,
                "batch_size": self.batch_size,
                "n_candidates": self.n_candidates,
                "mc_samples": self.mc_samples,
                "fantasy": self.fantasy,
                "seed": self.seed,
                "noise_resolved_last": (list(map(float, noise_used))
                                        if noise_used is not None else None),
            },
        }
        if constrained:
            assert self.constraints is not None
            result["constraints"] = [dict(s) for s in self.constraints]
            result["n_feasible"] = sum(
                1 for s in samples if s.get("feasible") is True)
            result["n_unknown_feasibility"] = sum(
                1 for s in samples if s.get("feasible") is None)
            result["front_constraint_values"] = front_cvals
            result["info"]["n_constraints"] = len(self.constraints)
            result["info"]["constraint_keys"] = list(self._constraint_keys)
            result["info"]["n_feasibility_fallback"] = n_feasibility_fallback
            result["info"]["constraint_noise_resolved_last"] = (
                list(map(float, c_noise_used))
                if c_noise_used is not None else None)
        return result
