"""numpy 自实现 NUTS（No-U-Turn Sampler）内核（aurora_p E2；通用面）。

定位：T-N11 saas_gp 的 MH 自实现档的升级位采样内核——**通用面，不绑死
SAAS 语义**：任何"对数后验+解析梯度"回调都可接入（logp_grad 返回
(log p(θ), ∇log p(θ))）。

法源：Hoffman & Gelman, "The No-U-Turn Sampler: Adaptively Setting Path
Lengths in Hamiltonian Monte Carlo", JMLR 14 (2014)，**Algorithm 6**
（高效 NUTS，逐点片 slice 变量版）。

v1 降档边界（预声明选型=自实现，如实声明，不硬凑）：
- **固定步长**：无 dual averaging 步长调适（Algorithm 6 的 α′ 统计不
  回写 ε）——步长由调用方旋钮显式给出；
- **恒等质量矩阵**：动量 r ~ N(0, I)，无对角/稠密质量矩阵调适；
- **逐点片采样**（Algorithm 6 原版 slice 变量）而非 multinomial 轨迹
  采样（Betancourt 式）——两者均为合法 NUTS 形态；
- **固定最大树深**：倍增次数上限旋钮（缺省 10，硬顶 12），U-Turn
  折返或触顶先到者停。

multinomial 采样 / dual averaging / 质量矩阵调适 = v2 升级位（登记
TODO 由主代理裁决是否接 numpyro 概率库——零新硬依赖红线下的自实现
边界，工作量失控时以本 v1 形态如实收口）。

数值口径：
- 片变量在**对数空间**（log u = joint₀ − Exp(1)，等价 log U 抽样，
  防溢出）；
- 发散守卫 Δmax=1000（Stan 口径）：joint′ 与 log u 差超 Δmax 判发散，
  该叶 s′=0 → 整棵倍增提前停；
- 支撑外/数值异常（Cholesky 失败等）：回调返回 −inf 由内核按发散
  处置——叶 n′=0、s′=0，不静默也不崩；
- U-Turn 判据：Δθ·r₋ < 0 或 Δθ·r₊ < 0（H&G 式 (10)，子树内+全树
  双重循环双端判）。

确定性：seed → 单一 np.random.default_rng 随机流（动量/方向/片变量/
子树接管概率全部出自它），同 seed 同输入 → 样本集与诊断逐位复现
（C4 纪律）。

依赖：numpy 单一硬依赖（零新依赖红线；无 scipy——本内核不需要）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

#: 发散判据 Δmax（Stan 缺省口径：joint′ 距 log u 超此值判发散）
DELTA_MAX = 1000.0

#: 最大树深硬顶（2^12=4096 步 leapfrog/迭代上界；超过属预算 bug，
#: 显式报错不静默——数值预算守卫，非算法限制）
MAX_TREE_DEPTH_CAP = 12

LogPosteriorGrad = Callable[[np.ndarray], tuple[float, np.ndarray]]

# 无 __all__（消费面显式按名 import；公开面金快照 public_api 只收 __all__
# 模块——本模块不进快照，避免与他席在制金快照漂移面交叉，aurora_p E2）。


def effective_sample_size(chain: np.ndarray) -> float:
    """一维链的有效样本尺寸 ESS（Geyer 初始正序列截断，FFT 自相关）。

    法源：Geyer (1992) 初始正序列——τ = −1 + 2·Σ_{k=0}^{m} Γ_k，
    Γ_k = ρ_{2k} + ρ_{2k+1}，m 为最后一个使全部 Γ_j (j≤m) > 0 的截断；
    ESS = n/τ（截断到 [1, n]）。bench/测试裁判面用（#300 家法：裁判
    自身实现简单可复核，不用近似黑箱）。

    零方差链（常数）返回 NaN 如实（不可定义，不伪造）。
    """
    x = np.asarray(chain, dtype=float).ravel()
    n = x.size
    if n < 4:
        raise ValueError(f"ESS 需要链长 ≥4，实得 {n}")
    x = x - x.mean()
    nfft = 1 << int(2 * n - 1).bit_length()
    f = np.fft.rfft(x, nfft)
    acov = np.fft.irfft(f * np.conj(f), nfft)[:n]
    if acov[0] <= 0.0:
        return float("nan")
    rho = acov / acov[0]
    tau = -1.0
    k = 0
    while 2 * k + 1 < n:
        gamma = rho[2 * k] + rho[2 * k + 1]
        if gamma <= 0.0:
            break
        tau += 2.0 * gamma
        k += 1
    tau = max(tau, 1.0 / (10.0 * n))  # τ 下界守卫（数值噪声防 ESS≫n）
    ess = n / tau
    return float(min(max(ess, 1.0), float(n)))


def _leapfrog(
    logp_grad: LogPosteriorGrad,
    theta: np.ndarray,
    r: np.ndarray,
    grad: np.ndarray,
    eps: float,
) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """单步 leapfrog（蛙跳积分）；支撑外/异常态以 log p=−inf 标记。"""
    r_half = r + 0.5 * eps * grad
    theta_new = theta + eps * r_half
    if not np.all(np.isfinite(theta_new)):
        return theta_new, r_half, -np.inf, np.zeros_like(theta)
    lp, grad_new = logp_grad(theta_new)
    if not (np.isfinite(lp) and np.all(np.isfinite(grad_new))):
        # 支撑外/数值异常：joint=−inf 走发散处置，梯度零向量防 NaN 扩散
        return theta_new, r_half, -np.inf, np.zeros_like(theta)
    r_new = r_half + 0.5 * eps * grad_new
    if not np.all(np.isfinite(r_new)):
        return theta_new, r_new, -np.inf, grad_new
    return theta_new, r_new, lp, grad_new


def _joint(lp: float, r: np.ndarray) -> float:
    """联合对数密度 log p(θ) − ½·rᵀr（H&G joint，恒等质量阵动能）。"""
    return lp - 0.5 * float(r @ r)


def _build_tree(
    logp_grad: LogPosteriorGrad,
    rng: np.random.Generator,
    theta: np.ndarray,
    r: np.ndarray,
    grad: np.ndarray,
    lp: float,
    log_u: float,
    v: int,
    depth: int,
    eps: float,
) -> dict[str, Any]:
    """Algorithm 6 的 BuildTree 递归（v=−1 向后 / v=+1 向前倍增）。

    返回 dict：双端态（theta/r/grad/lp 各 minus/plus）、提案态
    （theta_prop/lp_prop/grad_prop）、片内有效态数 n、继续倍增旗 s、
    叶级发散计数 n_divergent、leapfrog 步数 n_leapfrog。

    深度 >0 时：先建半棵子树，s=1 才沿同方向建另一半；提案以
    n″/(n′+n″) 概率接管（Algorithm 6 式 (12)）；子树端点做 U-Turn
    判据（式 (10)）与 s″ 相乘得本层 s′。
    """
    if depth == 0:
        theta1, r1, lp1, grad1 = _leapfrog(logp_grad, theta, r, grad,
                                           v * eps)
        joint1 = _joint(lp1, r1)
        n_prime = 1 if log_u <= joint1 else 0
        divergent = not (log_u < DELTA_MAX + joint1)
        s_prime = 0 if divergent else 1
        return {
            "theta_minus": theta1, "r_minus": r1, "grad_minus": grad1,
            "lp_minus": lp1,
            "theta_plus": theta1, "r_plus": r1, "grad_plus": grad1,
            "lp_plus": lp1,
            "theta_prop": theta1, "lp_prop": lp1, "grad_prop": grad1,
            "n": n_prime, "s": s_prime,
            "n_divergent": int(divergent), "n_leapfrog": 1,
        }
    first = _build_tree(logp_grad, rng, theta, r, grad, lp, log_u, v,
                        depth - 1, eps)
    if first["s"] == 1:
        if v == -1:
            second = _build_tree(
                logp_grad, rng, first["theta_minus"], first["r_minus"],
                first["grad_minus"], first["lp_minus"], log_u, v,
                depth - 1, eps)
            first["theta_minus"] = second["theta_minus"]
            first["r_minus"] = second["r_minus"]
            first["grad_minus"] = second["grad_minus"]
            first["lp_minus"] = second["lp_minus"]
        else:
            second = _build_tree(
                logp_grad, rng, first["theta_plus"], first["r_plus"],
                first["grad_plus"], first["lp_plus"], log_u, v,
                depth - 1, eps)
            first["theta_plus"] = second["theta_plus"]
            first["r_plus"] = second["r_plus"]
            first["grad_plus"] = second["grad_plus"]
            first["lp_plus"] = second["lp_plus"]
        # 提案接管：以 n″/(n′+n″) 概率（n″=0 跳过，不耗随机流）
        n_total = first["n"] + second["n"]
        if second["n"] > 0 and rng.random() < second["n"] / max(n_total, 1):
            first["theta_prop"] = second["theta_prop"]
            first["lp_prop"] = second["lp_prop"]
            first["grad_prop"] = second["grad_prop"]
        first["n"] = n_total
        first["s"] = min(first["s"], second["s"])
        # 子树端点 U-Turn 判据（Algorithm 6 BuildTree 内层式 (10)）
        d_theta = first["theta_plus"] - first["theta_minus"]
        if first["s"] == 1 and (float(d_theta @ first["r_minus"]) < 0.0
                                or float(d_theta @ first["r_plus"]) < 0.0):
            first["s"] = 0
        first["n_divergent"] += second["n_divergent"]
        first["n_leapfrog"] += second["n_leapfrog"]
    return first


def nuts_sample(
    logp_grad: LogPosteriorGrad,
    theta0: np.ndarray,
    *,
    seed: int,
    n_samples: int,
    burn: int = 0,
    thin: int = 1,
    step_size: float = 0.2,
    max_tree_depth: int = 10,
) -> dict[str, Any]:
    """固定步长+固定最大树深的 NUTS 采样（Algorithm 6 slice 档，v1）。

    Args:
        logp_grad: 回调 θ → (log p(θ), ∇log p(θ))；支撑外/数值异常时
            返回 (−inf, 任意有限向量)——内核按发散处置不静默不崩。
        theta0: 初始点（1 维有限数组；链初始化在支撑内是调用方责任——
            初始 log p 非有限时显式报错）。
        seed: 随机流 seed（同 seed 同输入逐位复现，C4）。
        n_samples / burn / thin: 链长旋钮（保留样本数/预烧迭代数/细化）。
        step_size: 固定 leapfrog 步长 ε（v1 降档：无 dual averaging）。
        max_tree_depth: 倍增上限（缺省 10；硬顶 12——超过显式报错）。

    Returns:
        {"samples": (n_samples, d) 链存档,
         "logp_samples": (n_samples,) 保留点的 log p,
         "seed"/"n_samples"/"burn"/"thin"/"step_size"/"max_tree_depth":
             配置回执,
         "move_rate": 链移动率（该次迭代被选态 ≠ 前一态的占比——NUTS
             无单步 MH 接受率，此为健康探针：稳态良好混合应接近 1）,
         "tree_depth_mean": 平均最终树深（U-Turn 越早折返越小）,
         "n_divergent": 叶级发散态计数（Δmax 判据）,
         "leapfrog_total": 全程 leapfrog 步数（≈梯度回调次数面）}

    Raises:
        ValueError: 链长/步长/树深非法、theta0 非有限或初始 log p 非有限
            （预声明负例，显式报错不静默）。
    """
    theta = np.asarray(theta0, dtype=float).ravel()
    d = theta.size
    if not np.all(np.isfinite(theta)):
        raise ValueError("theta0 含非有限值——拒绝采样")
    n_samples_i, burn_i, thin_i = int(n_samples), int(burn), int(thin)
    eps = float(step_size)
    depth_cap = int(max_tree_depth)
    if n_samples_i < 1 or burn_i < 0 or thin_i < 1:
        raise ValueError(
            f"链长非法：n_samples={n_samples}（须 ≥1）、burn={burn}"
            f"（须 ≥0）、thin={thin}（须 ≥1）")
    if eps <= 0.0:
        raise ValueError(f"step_size 须 >0，实得 {step_size}")
    if depth_cap < 1 or depth_cap > MAX_TREE_DEPTH_CAP:
        raise ValueError(
            f"max_tree_depth 须在 [1, {MAX_TREE_DEPTH_CAP}]，"
            f"实得 {max_tree_depth}")

    lp, grad = logp_grad(theta)
    if not (np.isfinite(lp) and np.all(np.isfinite(grad))):
        raise ValueError(
            "theta0 处 log p/grad 非有限——链初始化必须在支撑内"
            "（预声明负例，不静默开跑）")

    rng = np.random.default_rng(int(seed))
    samples = np.empty((n_samples_i, d))
    logp_samples = np.empty(n_samples_i)
    n_div_total = 0
    n_leap_total = 0
    depth_total = 0
    n_moved = 0

    for it in range(burn_i + n_samples_i * thin_i):
        # ① 动量重抽 + 对数空间片变量（log u = joint₀ − Exp(1)）
        r0 = rng.standard_normal(d)
        joint0 = _joint(lp, r0)
        log_u = joint0 - rng.exponential(1.0)
        # ② 倍增主循环：方向随机 → 建子树 → 提案接管 → 全树端点
        #    U-Turn 双端判据 → 触顶/折返停
        th_m, r_m, g_m, lp_m = theta, r0, grad, lp
        th_p, r_p, g_p, lp_p = theta, r0, grad, lp
        th_cur, lp_cur, g_cur = theta, lp, grad
        n = 1
        s = 1
        j = 0
        while s == 1 and j < depth_cap:
            v = -1 if rng.random() < 0.5 else 1
            if v == -1:
                sub = _build_tree(logp_grad, rng, th_m, r_m, g_m, lp_m,
                                  log_u, v, j, eps)
                th_m, r_m, g_m, lp_m = (sub["theta_minus"],
                                        sub["r_minus"], sub["grad_minus"],
                                        sub["lp_minus"])
            else:
                sub = _build_tree(logp_grad, rng, th_p, r_p, g_p, lp_p,
                                  log_u, v, j, eps)
                th_p, r_p, g_p, lp_p = (sub["theta_plus"], sub["r_plus"],
                                        sub["grad_plus"], sub["lp_plus"])
            n_div_total += sub["n_divergent"]
            n_leap_total += sub["n_leapfrog"]
            if sub["s"] == 1 and sub["n"] > 0 and (
                    sub["n"] >= n or rng.random() < sub["n"] / n):
                th_cur, lp_cur, g_cur = (sub["theta_prop"],
                                         sub["lp_prop"], sub["grad_prop"])
            n += sub["n"]
            # 全树端点 U-Turn 双端判据（H&G 式 (10)：任一端折返即停）
            d_theta = th_p - th_m
            s = sub["s"]
            if s == 1 and (float(d_theta @ r_m) < 0.0
                           or float(d_theta @ r_p) < 0.0):
                s = 0
            j += 1
        depth_total += j
        if not np.array_equal(th_cur, theta):
            n_moved += 1
        theta, lp, grad = th_cur, lp_cur, g_cur
        if it >= burn_i and (it - burn_i) % thin_i == 0:
            samples[(it - burn_i) // thin_i] = theta
            logp_samples[(it - burn_i) // thin_i] = lp

    total = burn_i + n_samples_i * thin_i
    return {
        "samples": samples,
        "logp_samples": logp_samples,
        "seed": int(seed),
        "n_samples": n_samples_i,
        "burn": burn_i,
        "thin": thin_i,
        "step_size": eps,
        "max_tree_depth": depth_cap,
        "move_rate": float(n_moved / max(total, 1)),
        "tree_depth_mean": float(depth_total / max(total, 1)),
        "n_divergent": int(n_div_total),
        "leapfrog_total": int(n_leap_total),
    }
