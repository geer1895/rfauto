"""设计点重要性采样（Importance Sampling）稀有失效概率内核（XD-11）。

背景：Pf∈[1e-4,1e-6] 区间普通 MC 需 1e6+ 样本（RC 选型矩阵 §3.1 判读）；
FORM 给出设计点 u* 与 β 后，以 h=N(u*,I) 为重要性密度补采样件——单设计点
问题上方差削减可达数量级（Rubinstein 1981 指数扭转的均值移位特例；
OpenTURNS 对应 PostAnalyticalImportanceSampling 的自实现最简档）。

依据节（方法学出处）：
- Rubinstein 1981（"Simulation and the Monte Carlo Method"，Wiley）：
  指数扭转/均值移位重要性密度与似然比权重；
- Rackwitz-Fiessler/HL-RF 链路上的设计点由 core.form_reliability.form_beta
  产出（design_point_u 免费喂料，本内核不重复求设计点）。

权重与估计量（u 空间，f=N(0,I)）：
    u_i ~ h=N(u*, I)，x_i = μ + σ⊙u_i，g_i = limit_state(x_i)
    w_i = φ(u_i)/φ(u_i−u*) = exp(u*·u_i − ‖u*‖²/2)
    Pf̂ = mean(1(g≤0)·w)，Var̂ = (mean((w·1)²) − Pf̂²)/n
    cov_is = √Var̂/Pf̂；ESS = (Σw)²/Σw²

诚实边界（预声明，#122 不凑绿）：
- 单设计点 IS 对多峰失效域系统性低估（漏峰）——A3 判据钉该失败模式；
  applicability 面应触发 suspect（service 层 rare_yield_is 预检③）。
- ESS 诊断在大 β 下整体偏低是 N(u*,I) 均值移位的已知数学性质：
  E_h[w²]=exp(‖u*‖²)，故 ESS/n≈exp(−‖u*‖²)——估计量 cov_is 小（0.0x 量级）
  与 ESS 偏低并存并不矛盾（权重平方被安全区大权重支配，而那些样本对
  Pf 无贡献）。ESS<N/10 触发 applicability 提示，数值采信以 cov_is 为准。
- ‖u*‖²≳700 时 exp 溢出（β≳26）——目标域 Pf∈[1e-4,1e-6]（β≤5）远离
  该界，越界显式 OverflowError 不静默。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

__all__ = ["IsResult", "WeightsStats", "importance_sampling_pf"]


@dataclass(frozen=True)
class WeightsStats:
    """似然比权重统计（ESS 诊断面）。"""

    max: float
    mean: float


@dataclass(frozen=True)
class IsResult:
    """设计点 IS 结果（RC §3.5C schema 字段全集，消费方按 as_dict 落盘）。"""

    pf_is: float  # Pf̂ = mean(1(g≤0)·w)
    cov_is: float  # 变异系数 √Var̂/Pf̂（估计量相对标准差）
    ess: float  # 有效样本量 (Σw)²/Σw²
    n_evals: int  # limit_state 求值次数（=n_samples）
    seed: int
    weights_stats: WeightsStats  # {max, mean}

    def as_dict(self) -> dict[str, object]:
        """schema 强制键形态（pf_is/cov_is/ess/n_evals/seed/weights_stats）。"""
        return {
            "pf_is": self.pf_is,
            "cov_is": self.cov_is,
            "ess": self.ess,
            "n_evals": self.n_evals,
            "seed": self.seed,
            "weights_stats": {"max": self.weights_stats.max,
                              "mean": self.weights_stats.mean},
        }


def importance_sampling_pf(
    limit_state: Callable[[np.ndarray], float],
    mean: np.typing.ArrayLike,
    stddev: np.typing.ArrayLike,
    design_point_u: np.typing.ArrayLike,
    *,
    n_samples: int = 5000,
    seed: int = 0,
    vectorized: bool = False,
) -> IsResult:
    """设计点 IS 稀有失效概率（h=N(u*,I) 均值移位，纯 numpy）。

    入参：
    - limit_state：黑盒极限状态 g(x)（物理空间）。vectorized=False 时
      收 1-D ndarray 长 n 返回标量；vectorized=True 时收 (n,n_var) 矩阵
      返回 (n,) 列（代理批预测通道走此形态，service 层
      _mc_predict_columns 列批直喂）。
    - mean/stddev：物理空间 μ/σ（σ 逐元素 >0，与 form_reliability 同约）。
    - design_point_u：标准正态空间设计点 u*（core.form_beta 的
      FormResult.design_point_u 直喂；调用方须先验 converged——不收敛
      设计点禁喂 IS，拒绝在 service 挂点执行）。
    - n_samples/seed：抽样数与种子（复现性契约，E 件）。

    返回 IsResult（pf_is/cov_is/ess/n_evals/seed/weights_stats）。
    失效判据 g≤0（form_reliability 同符号惯例）；Pf̂=0（无失效样本）时
    cov_is=inf 如实（稀有事件零命中不是零概率证据，#122 不凑数）。
    """
    mean_a = np.asarray(mean, dtype=float).ravel()
    stddev_a = np.asarray(stddev, dtype=float).ravel()
    u_star = np.asarray(design_point_u, dtype=float).ravel()
    n = mean_a.size
    if n == 0 or stddev_a.size != n or u_star.size != n:
        raise ValueError(
            f"mean/stddev/design_point_u 维度不一致: {n}/{stddev_a.size}/"
            f"{u_star.size}")
    if int(n_samples) < 1:
        raise ValueError(f"n_samples 必须 ≥1, got {n_samples!r}")
    if not np.all(np.isfinite(mean_a)) or not np.all(np.isfinite(u_star)):
        raise ValueError("mean/design_point_u 必须有限")
    if not np.all(np.isfinite(stddev_a)) or np.any(stddev_a <= 0.0):
        raise ValueError("stddev 必须逐元素有限且 >0")
    half_norm_sq = 0.5 * float(u_star @ u_star)
    if half_norm_sq > 690.0:
        # exp 溢出预守卫：‖u*‖²/2>690 即 β≳37——远超 IS 适用域（β≤5），
        # 显式拒绝而非静默 inf（权重上溢会使 Pf̂ 恒 0 的假象）
        raise OverflowError(
            f"‖u*‖²/2={half_norm_sq:.1f} 超出 IS 权重可表示域（β≳37）；"
            "深尾部请走 SuS（登记 followUp）")

    rng = np.random.default_rng(int(seed))
    U = rng.standard_normal((int(n_samples), n)) + u_star
    # w = φ(u)/φ(u−u*) = exp(‖u*‖²/2 − u*·u)（log 域合成避免中间量溢出；
    # 符号自证：E_h[w]=exp(‖u*‖²/2)·E[exp(−u*·u)]，u~N(u*,I) 的 MGF 给
    # E[exp(−u*·u)]=exp(−‖u*‖²+‖u*‖²/2)，总积=1 ✓）
    log_w = half_norm_sq - U @ u_star
    w = np.exp(log_w)

    X = mean_a + stddev_a * U
    if vectorized:
        g = np.asarray(limit_state(X), dtype=float).reshape(-1)
        if g.size != int(n_samples):
            raise ValueError(
                f"limit_state 返回长度 {g.size} 与 n_samples {n_samples} 不一致")
    else:
        g = np.array([float(limit_state(row)) for row in X])
    if not np.all(np.isfinite(g)):
        raise ValueError("limit_state 返回非有限值（不吞，form_reliability 同约）")

    fail = (g <= 0.0).astype(float)
    h = w * fail
    pf_is = float(h.mean())
    n_evals = int(n_samples)
    if pf_is == 0.0:
        cov_is = math.inf
    else:
        var_hat = max(float((h * h).mean()) - pf_is * pf_is, 0.0) / n_evals
        cov_is = math.sqrt(var_hat) / pf_is
    w_sum = float(w.sum())
    w_sq_sum = float((w * w).sum())
    ess = (w_sum * w_sum / w_sq_sum) if w_sq_sum > 0.0 else 0.0
    return IsResult(
        pf_is=pf_is,
        cov_is=float(cov_is),
        ess=float(ess),
        n_evals=n_evals,
        seed=int(seed),
        weights_stats=WeightsStats(max=float(w.max()), mean=float(w.mean())),
    )
