"""EC-17 SAAS 精神稀疏 ARD 高维先验（MAP 点估计 + opt-in 全后验档）。

后验采样器两档（aurora_p E2 升级位）：``sampler="mh"``（缺省，T-N11
自实现随机游走 MH，逐字节零变化）与 ``sampler="nuts"``（numpy 自实现
NUTS，``optimization.nuts_sampler`` 通用内核 + 本模块解析梯度）——
预声明选型=自实现（零新硬依赖红线），numpyro 接入=v2 裁决项。


池 P3 圈定件（aurora_e W5-S22；ecosystem §二 EC-17，条件件"≥15 维战役"
驱动——本档为离线内核+合成基准验证，真机放量等条件触发）。法源：
- SAASBO（Eriksson & Jankowiak, "High-Dimensional Bayesian Optimization
  with Sparse Axis-Aligned Subspaces", UAI 2021；botorch SAASBO）：
  log(ℓ_i) ~ N(0, τ²)（τ²=100）的超稀疏长度尺度先验——τ² 大 ⇒ 绝大多数
  维度被先验压向巨大 ℓ（轴向"关闭"），只有数据强支持的少数维度保留
  小 ℓ（"开启"），天然实现高维 ARD 稀疏化；
- 核：Matérn 5/2 ARD（SAASBO 缺省核）。

两档形态（T-N11，aurora_n W2）：
- **MAP 点估计档（缺省，逐字节不变）**：无 ``posterior_samples`` 配置时
  走原确定性 MAP 路径——没有后验分布，稀疏性来自先验罚项下的最优解，
  维度"活跃"判据是 ℓ 阈值（建模选择，非后验概率），消费方按点估计
  口径消费；
- **``posterior_samples`` 全后验档（opt-in）**：log 长度尺度向量
  θ=(log ℓ_1..log ℓ_d) 的后验采样（``sample_saas_posterior``，
  XD-12 KOHMCMCPosterior 同族固定 seed 先例；log 后验 = GP 边际似然
  + SAAS 先验核）。M 条长度尺度样本 → 每条一个 GP 后验 →
  ``predict``/``uncertainty`` 给后验混合（全方差公式），``acquire_lcb``/
  ``acquire_ei`` 给逐样本采集后平均（SAASBO 式平均采集/Thompson 语义）。
  **``sampler="mh"``（缺省，T-N11 原档逐字节零变化）**：对称高斯随机
  游走 MH——零梯度、实现小、链长/步长旋钮化，小样本 GP 超参后验
  （d≲20、n≲200）可承载；代价是高维下接受率偏低（accept_rate 如实
  透出作健康探针，同 KOH 口径）、同链长有效样本数低。**``sampler=
  "nuts"``（aurora_p E2 升级档）**：numpy 自实现 NUTS（SAASBO 原版
  同款采样器族）——对数超参后验解析梯度入内核（固定步长+最大树深
  v1 降档边界见 ``optimization.nuts_sampler`` docstring），同预算下
  ESS 显著高于 MH（bench 见 runs/aurora_p/e2/BENCH.md，胜负如实）；
  accept_rate 字段两档同形，nuts 档语义=链移动率（move_rate，健康
  探针——NUTS 无单步 MH 接受率，如实标注）。诚实边界：amp/nugget
  钉在该指标 MAP 拟合值（长度尺度**条件后验**，与提案"长度尺度全
  后验"口径一致，如实标注）；MAP 档其余边界（nugget 固定不参与优化
  等）对两档同样适用。

性能边界（T-N11 预声明 + E2 增补）：MH 每迭代 O(n³)（Cholesky）；
单测链长（burn=120/n_samples=96/thin=2，n=64、d=4）秒级；竞赛链长
（80/80/2，n≤36、d≤15）每次重拟合亚秒级；n 或 d 显著放大时应加链长
或换 ``sampler="nuts"``。NUTS 每梯度回调 O(n³+n²d)（Cholesky+逐维
核导数），每迭代回调数=实际树规模（≤2^max_depth−1）——同预算 ESS
远高于 MH（bench 表 runs/aurora_p/e2/BENCH.md），代价是每迭代墙钟
约为 MH 的梯度回调倍数关系，小样本 GP 后验两档都在秒级。

注册即生效（基类+注册表模式，规则 3）：``surrogate_registry.create(
"saas_gp", config={...})``；纯增量键，既有 kind 消费面零改动。

合成基准（已知真值回收）：15 维仅 2 维活跃的平滑函数，MAP 后活跃集
回收 + 非活跃维度 ℓ 全部 >> 活跃维度 ℓ；后验档真值集中带见
tests/unit/test_saas_gp_posterior.py 与 runs/aurora_n/w2_tn11/CRITERIA.md。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.optimization.nuts_sampler import nuts_sample
from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)
from rfauto.optimization.surrogate.gp_det import (
    _JITTER,
    DetGaussianProcess,
    expected_improvement,
    fit_map,
    gp_nll,
    matern52_ard_kernel,
    se_ard_kernel,
)

__all__ = [
    "DEFAULT_ACTIVE_THRESHOLD",
    "DEFAULT_POSTERIOR_SEED",
    "DEFAULT_TAU_SQ",
    "POSTERIOR_DEFAULTS",
    "SaasArdSurrogate",
    "sample_saas_posterior",
]
# （公开面纪律：E2 新增 sampler 档常量不入 __all__——public_api 金快照
# 按模块 __all__ 记账，不扩面则金快照零漂移，避免与他席在制快照交叉。）

#: SAAS 先验 log(ℓ) 方差（原论文 τ²=100 口径）
DEFAULT_TAU_SQ = 100.0

#: 活跃维度阈值（单元立方：ℓ < 阈值视为"开启"；建模选择，如实标注）
DEFAULT_ACTIVE_THRESHOLD = 2.0

#: 后验档 MH 链 seed 缺省（固定值确定性钉；同 seed 同数据逐位复现）
DEFAULT_POSTERIOR_SEED = 20261029

#: 后验档采样器种类（E2 增补："mh"=T-N11 随机游走（缺省，逐字节零
#: 变化）；"nuts"=numpy 自实现 NUTS 升级档）
POSTERIOR_SAMPLER_KINDS = ("mh", "nuts")

#: 后验档链长/步长缺省（旋钮；小样本 GP 超参后验的承载档，性能边界见
#: 模块 docstring——单测/竞赛按需 override，不静默放大）
POSTERIOR_DEFAULTS: dict[str, int | float] = {
    "n_samples": 64,
    "burn": 64,
    "thin": 2,
    "proposal_scale": 0.3,
    "sampler": "mh",
    "step_size": 0.10,
    "max_tree_depth": 10,
}

#: log ℓ 提议支撑盒（数值安全：exp 溢出/下溢路径不进核函数；先验
#: N(0,τ²=100) 在 ±30 外的双侧质量 <0.3%，截断影响可忽略且如实标注）
_LOG_ELL_SUPPORT = (-30.0, 30.0)


def _numeric_keys(samples: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for s in samples:
        keys |= {k for k, v in s.get("metrics", {}).items()
                 if isinstance(v, (int, float))}
    return keys


def _kernel_dlog_ell(
    x: np.ndarray, ell: np.ndarray, amp: float, kind: str, j: int,
) -> np.ndarray:
    """核矩阵对 log ℓ_j 的偏导 ∂K/∂(log ℓ_j)（n×n；E2 NUTS 梯度面）。

    法源推导（对数空间链式）：
    - SE：k=amp²exp(−½Σz_i)，z_i=(Δ_i/ℓ_i)²，∂z_j/∂log ℓ_j=−2z_j
      ⟹ ∂k/∂log ℓ_j = k·z_j；
    - Matérn 5/2：k=amp²f(s)，f'(s)=−e^{−s}s(1+s)/3，s=√5·r，
      ∂r/∂log ℓ_j=−z_j/r ⟹ ∂k/∂log ℓ_j =
      amp²·e^{−s}·s(1+s)·√5·z_j/(3r)（r=0 对角处取 0）。
    有限差分对拍钉见 tests/unit/test_nuts_sampler.py（#118 家法：梯度
    推导必须有独立来源验证）。
    """
    diff = (x[:, None, :] - x[None, :, :]) / np.maximum(ell, 1e-12)
    z_j = diff[:, :, j] ** 2
    if kind == "se":
        return se_ard_kernel(x, x, ell, amp) * z_j
    r = np.sqrt((diff ** 2).sum(axis=2))
    s = np.sqrt(5.0) * r
    # 注意（首轮 FD 对拍实证的修正）：∂k/∂log ℓ_j = amp²·e^{−s}·s(1+s)·
    # √5·z_j/(3r)——**不含**核值本身的 (1+s+s²/3) 因子（首版 base×slope
    # 把核值误乘进去，FD 对拍当场抓出；SE 分支的 k·z_j 是精确式无此坑）
    slope = np.where(
        r > 0.0,
        np.exp(-s) * s * (1.0 + s) * np.sqrt(5.0) * z_j
        / (3.0 * np.maximum(r, 1e-300)),
        0.0)
    return float(amp) * float(amp) * slope


def _saas_log_post_grad(
    lg: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    kind: str,
    nugget: float,
    prior: dict[str, float],
    log_amp: float,
) -> tuple[float, np.ndarray]:
    """SAAS 对数超参后验的（log p, ∇log p）联合回调（E2 NUTS 面）。

    log p = −gp_nll 同式展开（−边际 NLL − 先验罚项）；梯度推导
    （符号经 MAP 点 FD 对拍实证——首版 0.5 项符号反了，当场抓出）：
    ∂(½yᵀK⁻¹y)/∂θ_j = −½αᵀK_jα，∂(½log|K|)/∂θ_j = ½tr(K⁻¹K_j)
    ⟹ ∂logp/∂θ_j = ½·tr((ααᵀ−K⁻¹)K_j) − (lg_j−m)/s²（R&W 式 (5.9)
    变体取负号口径）。支撑外返回 (−inf, 0)（内核按发散处置）；
    Cholesky 数值失败同路（best-effort 观测性纪律，不崩采样链）。
    """
    d = x.shape[1]
    if (np.any(lg < _LOG_ELL_SUPPORT[0])
            or np.any(lg > _LOG_ELL_SUPPORT[1])):
        return -np.inf, np.zeros(d)
    m = float(prior.get("log_ell_mean", 0.0))
    s2 = max(float(prior.get("log_ell_var", 100.0)), 1e-12)
    try:
        ell = np.exp(lg)
        amp = float(np.exp(log_amp))
        n = x.shape[0]
        k = matern52_ard_kernel(x, x, ell, amp) if kind == "matern52" \
            else se_ard_kernel(x, x, ell, amp)
        k[np.diag_indices(n)] += max(float(nugget), 0.0) + _JITTER
        chol = np.linalg.cholesky(k)
        alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, y))
        log_lik = (-0.5 * float(y @ alpha)
                   - float(np.log(np.diag(chol)).sum())
                   - 0.5 * n * np.log(2.0 * np.pi))
        log_post = log_lik - 0.5 * float(((lg - m) ** 2).sum()) / s2
        ident = np.eye(n)
        k_inv = np.linalg.solve(chol.T, np.linalg.solve(chol, ident))
        w = np.outer(alpha, alpha) - k_inv
        grad = np.empty(d)
        for j in range(d):
            dk_j = _kernel_dlog_ell(x, ell, amp, kind, j)
            grad[j] = (0.5 * float((w * dk_j).sum())
                       - (float(lg[j]) - m) / s2)
        if not (np.isfinite(log_post) and np.all(np.isfinite(grad))):
            return -np.inf, np.zeros(d)
        return float(log_post), grad
    except (np.linalg.LinAlgError, FloatingPointError, ValueError):
        return -np.inf, np.zeros(d)


def sample_saas_posterior(
    x: np.ndarray,
    y: np.ndarray,
    *,
    kind: str = "matern52",
    tau_sq: float = DEFAULT_TAU_SQ,
    log_ell_mean: float = 0.0,
    seed: int = DEFAULT_POSTERIOR_SEED,
    n_samples: int = 64,
    burn: int = 64,
    thin: int = 2,
    proposal_scale: float = 0.3,
    maxiter: int = 200,
    sampler: str = "mh",
    nuts_step_size: float = 0.10,
    nuts_max_depth: int = 10,
) -> dict[str, Any]:
    """log 长度尺度向量的固定 seed MCMC 后验（T-N11/E2 全后验档内核）。

    模型：y ~ GP(0, K(ℓ, amp) + nugget·I)，先验 log ℓ_i ~ N(m, τ²)
    （SAAS 稀疏核）。采样只在 θ=(log ℓ_1..log ℓ_d) 上游走；amp 与
    nugget **钉在该数据 fit_map 的解上**（长度尺度条件后验，确定性、
    链初始化在 MAP 点——混合起点即高密度区，短链友好）。

    Args:
        x: (n, d) 归一化输入（[0,1]^d 由调用方负责）。
        y: (n,) 目标值（须有限）。
        kind: 核种类（KERNEL_KINDS；SAAS 档缺省 matern52）。
        tau_sq: log ℓ 先验方差（SAAS τ²，缺省 100）。
        log_ell_mean: log ℓ 先验均值（缺省 0）。
        seed: 链 seed（固定值 → 链逐位可复现，C4；两档同约定）。
        n_samples / burn / thin: 链长旋钮（保留样本数/预烧/细化）。
        proposal_scale: 对称高斯提议步长（标量，全维共享；仅 mh 档）。
        maxiter: 内部 fit_map 的 L-BFGS 最大迭代数。
        sampler: "mh"（缺省，T-N11 随机游走档，零梯度）| "nuts"
            （E2 升级档，numpy 自实现 NUTS+解析梯度，见
            ``optimization.nuts_sampler`` docstring 的 v1 降档边界）。
        nuts_step_size: NUTS 固定 leapfrog 步长 ε（仅 nuts 档）。
        nuts_max_depth: NUTS 倍增上限（仅 nuts 档；硬顶 12）。

    Returns:
        {"ell_samples": (n_samples, d) 自然空间 ℓ 样本,
         "log_ell_samples": (n_samples, d) log 空样本（链存档）,
         "accept_rate": mh=全程接受率 / nuts=链移动率 move_rate
            （两档同形的健康探针，语义差异如实标注）,
         "sampler": 采样器种类回执（"mh"/"nuts"）,
         "seed"/"n_samples"/"burn"/"thin": 链配置回执,
         "amp"/"nugget": 条件化钉值, "map_ell"/"map_nll": MAP 解回执,
         nuts 档另附诊断: "move_rate"/"tree_depth_mean"/"n_divergent"/
            "leapfrog_total"/"step_size"/"max_tree_depth"}

    Raises:
        ValueError: 数据退化（n < d 或 y/x 含非有限值）、链长/步长/
            τ²/采样器档非法——显式报错不静默（预声明负例契约）。

    确定性：seed 固定 + 同数据 → 样本集与健康探针逐位复现（两档）。
    诚实边界：mh 档无 ESS/R̂ 诊断面板（accept_rate 唯一探针，过低时
    调 proposal_scale 重跑）；nuts 档固定步长/恒等质量阵为 v1 降档
    （无 dual averaging），树深诊断透出，发散态 n_divergent>0 时
    消费方应调小 nuts_step_size 重跑。
    """
    x = np.atleast_2d(np.asarray(x, dtype=float))
    y = np.asarray(y, dtype=float).ravel()
    n, d = x.shape
    if n < d:
        raise ValueError(
            f"SAAS 后验采样数据退化：有效点数 n={n} < 维度 d={d}——长度尺度"
            "后验不可辨识，拒绝采样（预声明负例，不静默降档）")
    if y.size != n:
        raise ValueError(f"x/y 行数不一致：n={n}, y={y.size}")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise ValueError("x/y 含非有限值——后验采样拒绝开跑")
    if tau_sq <= 0.0:
        raise ValueError(f"tau_sq 须 >0，实得 {tau_sq}")
    if int(n_samples) < 1 or int(burn) < 0 or int(thin) < 1:
        raise ValueError(
            f"链长非法：n_samples={n_samples}（须 ≥1）、burn={burn}"
            f"（须 ≥0）、thin={thin}（须 ≥1）")
    if float(proposal_scale) <= 0.0:
        raise ValueError(f"proposal_scale 须 >0，实得 {proposal_scale}")
    if kind not in ("se", "matern52"):
        raise ValueError(f"未知核种类: {kind}")
    if sampler not in POSTERIOR_SAMPLER_KINDS:
        raise ValueError(
            f"未知采样器档: {sampler}，可用: {POSTERIOR_SAMPLER_KINDS}")
    if float(nuts_step_size) <= 0.0:
        raise ValueError(f"nuts_step_size 须 >0，实得 {nuts_step_size}")
    if not (1 <= int(nuts_max_depth) <= 12):
        raise ValueError(
            f"nuts_max_depth 须在 [1, 12]，实得 {nuts_max_depth}")

    prior = {"log_ell_mean": float(log_ell_mean),
             "log_ell_var": float(tau_sq)}
    map_res = fit_map(x, y, kind=kind, prior=prior, maxiter=int(maxiter))
    amp = float(map_res["amp"])
    nugget = float(map_res["nugget"])
    map_nll = float(map_res["nll"])
    log_amp = float(np.log(max(amp, 1e-300)))
    log_ell = np.log(np.maximum(
        np.asarray(map_res["ell"], dtype=float), 1e-300))

    def _log_post(lg: np.ndarray) -> float:
        if (np.any(lg < _LOG_ELL_SUPPORT[0])
                or np.any(lg > _LOG_ELL_SUPPORT[1])):
            return -np.inf
        theta = np.concatenate([lg, [log_amp]])
        # −(含先验 NLL) = GP 边际对数似然 + SAAS 先验对数密度
        return -gp_nll(theta, x, y, kind, nugget, prior)

    if sampler == "nuts":
        def _log_post_grad(lg_: np.ndarray) -> tuple[float, np.ndarray]:
            return _saas_log_post_grad(lg_, x, y, kind, nugget, prior,
                                       log_amp)

        # 与 MH 档同一链初始化点（MAP）；log_post 数值与 _log_post
        # 同式同序（两档逐位一致的交叉验证钉见单测）
        res_nuts = nuts_sample(
            _log_post_grad, log_ell, seed=int(seed),
            n_samples=int(n_samples), burn=int(burn), thin=int(thin),
            step_size=float(nuts_step_size),
            max_tree_depth=int(nuts_max_depth))
        log_samples = res_nuts["samples"]
        return {
            "ell_samples": np.exp(log_samples),
            "log_ell_samples": log_samples,
            "accept_rate": float(res_nuts["move_rate"]),
            "sampler": "nuts",
            "seed": int(seed),
            "n_samples": int(n_samples),
            "burn": int(burn),
            "thin": int(thin),
            "amp": amp,
            "nugget": nugget,
            "map_ell": np.asarray(map_res["ell"], dtype=float),
            "map_nll": map_nll,
            "move_rate": float(res_nuts["move_rate"]),
            "tree_depth_mean": float(res_nuts["tree_depth_mean"]),
            "n_divergent": int(res_nuts["n_divergent"]),
            "leapfrog_total": int(res_nuts["leapfrog_total"]),
            "step_size": float(res_nuts["step_size"]),
            "max_tree_depth": int(res_nuts["max_tree_depth"]),
        }

    rng = np.random.default_rng(int(seed))
    lp = _log_post(log_ell)
    total = int(burn) + int(n_samples) * int(thin)
    kept: list[np.ndarray] = []
    n_accept = 0
    for it in range(total):
        prop = log_ell + float(proposal_scale) * rng.standard_normal(d)
        lp_prop = _log_post(prop)
        if np.isfinite(lp_prop) and (
                lp_prop >= lp or np.log(rng.random()) < lp_prop - lp):
            log_ell, lp = prop, lp_prop
            n_accept += 1
        if it >= int(burn) and (it - int(burn)) % int(thin) == 0:
            kept.append(log_ell.copy())
    log_samples = np.array(kept)
    return {
        "ell_samples": np.exp(log_samples),
        "log_ell_samples": log_samples,
        "accept_rate": float(n_accept / max(total, 1)),
        "sampler": "mh",
        "seed": int(seed),
        "n_samples": int(n_samples),
        "burn": int(burn),
        "thin": int(thin),
        "amp": amp,
        "nugget": nugget,
        "map_ell": np.asarray(map_res["ell"], dtype=float),
        "map_nll": map_nll,
    }


@surrogate_registry.register("saas_gp")
class SaasArdSurrogate(SurrogateModel):
    """SAAS 稀疏 ARD GP（EC-17/T-N11；MAP 点估计档 + opt-in 全后验档）。

    config:
        bounds: {param: (low, high)}（必填，单元归一化基准）。
        tau_sq: log(ℓ) 先验方差（缺省 100 = SAASBO 口径；调小→更稀疏）。
        log_ell_mean: log(ℓ) 先验均值（缺省 0，SAASBO 口径）。
        active_threshold: 活跃维度 ℓ 阈值（缺省 2.0）。
        metrics: 指标键列表（缺省全部数值键；有效点 <3 跳过，同约定）。
        posterior_samples: 全后验档开关（None/缺省=MAP 旧路径逐位不变）。
            dict 时键（缺省见 POSTERIOR_DEFAULTS/DEFAULT_POSTERIOR_SEED）：
            seed / n_samples / burn / thin / proposal_scale；E2 增补：
            sampler（"mh" 缺省|"nuts"）/ step_size（nuts 步长 ε）/
            max_tree_depth（nuts 倍增上限）。真值（非
            dict）= 全缺省。posterior 档下某指标有效点
            < max(d, 3) → 显式 ValueError（数据退化不静默，预声明负例）。

    fit 后透出（合成基准/高维诊断消费面）：
        lengthscales_: {metric: {param: ℓ}}——MAP 档=点估计；posterior
            档=逐维后验中位数（中位 < 阈值 ⟺ 后验多数票"开启"，等价
            口径如实标注）；
        active_dims_: {metric: [param,...]}（ℓ < active_threshold）；
        posterior 档另透出：
        lengthscale_samples_: {metric: (M, d) 自然空间 ℓ 样本}；
        posterior_info_: {metric: {accept_rate, seed, n_samples, burn,
            thin, amp, nugget}}（accept_rate 为健康探针，同 KOH 口径；
            两档同形同 7 键——nuts 档 accept_rate 语义=链移动率，
            如实标注）；
        posterior_diag_: {metric: {...}}——nuts 档采样诊断（move_rate/
            tree_depth_mean/n_divergent/leapfrog_total/step_size/
            max_tree_depth/sampler）；mh/MAP 档= {}（零变化）。

    采集面（T-N11；minimization 口径，两档同名同语义）：
        acquire_lcb(candidates, beta=2.0) → 逐样本 LCB_β 后平均
            （MAP 档 = 单点 LCB）；
        acquire_ei(candidates, xi=0.0) → 逐样本 EI 后平均
            （y_best=该指标训练目标最小值）。
    """

    KIND = "saas_gp"

    def _unit_row(self, params: dict[str, float]) -> np.ndarray:
        return np.array([
            np.clip((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12),
                    0.0, 1.0)
            for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)])

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        self.bounds = {k: tuple(v) for k, v in self.config["bounds"].items()}
        self.names = sorted(self.bounds)
        d = len(self.names)
        keys = (self.config.get("metrics")
                or sorted(_numeric_keys(samples)))
        tau_sq = float(self.config.get("tau_sq", DEFAULT_TAU_SQ))
        prior = {"log_ell_mean": float(self.config.get("log_ell_mean", 0.0)),
                 "log_ell_var": tau_sq}
        thr = float(self.config.get("active_threshold",
                                    DEFAULT_ACTIVE_THRESHOLD))
        post_cfg = self.config.get("posterior_samples")
        self.posterior_mode = bool(post_cfg)
        post = dict(POSTERIOR_DEFAULTS)
        post["seed"] = DEFAULT_POSTERIOR_SEED
        if isinstance(post_cfg, dict):
            for k in ("seed", "n_samples", "burn", "thin",
                      "proposal_scale", "sampler", "step_size",
                      "max_tree_depth"):
                if k in post_cfg:
                    post[k] = post_cfg[k]
        x = np.array([self._unit_row(s["params"]) for s in samples])
        self.models: dict[str, DetGaussianProcess] = {}
        self.lengthscales_: dict[str, dict[str, float]] = {}
        self.active_dims_: dict[str, list[str]] = {}
        self.sample_models_: dict[str, list[DetGaussianProcess]] = {}
        self.lengthscale_samples_: dict[str, np.ndarray] = {}
        self.posterior_info_: dict[str, dict[str, Any]] = {}
        self.posterior_diag_: dict[str, dict[str, Any]] = {}
        for key in keys:
            y = np.array([float(s["metrics"].get(key, np.nan))
                          for s in samples])
            mask = np.isfinite(y)
            if self.posterior_mode and mask.sum() < max(d, 3):
                raise ValueError(
                    f"SAAS 后验档数据退化：指标 {key!r} 有效点数 "
                    f"{int(mask.sum())} < max(维度 {d}, 3)——长度尺度后验"
                    "不可辨识，拒绝静默降档/跳过（预声明负例）")
            if mask.sum() < 3:
                continue
            if self.posterior_mode:
                res = sample_saas_posterior(
                    x[mask], y[mask], kind="matern52", tau_sq=tau_sq,
                    log_ell_mean=float(prior["log_ell_mean"]),
                    seed=int(post["seed"]),
                    n_samples=int(post["n_samples"]),
                    burn=int(post["burn"]),
                    thin=int(post["thin"]),
                    proposal_scale=float(post["proposal_scale"]),
                    sampler=str(post["sampler"]),
                    nuts_step_size=float(post["step_size"]),
                    nuts_max_depth=int(post["max_tree_depth"]))
                base = {"ell": res["map_ell"], "amp": res["amp"],
                        "nugget": res["nugget"], "nll": res["map_nll"]}
                self.models[key] = DetGaussianProcess(
                    x[mask], y[mask], base, "matern52")
                self.sample_models_[key] = [
                    DetGaussianProcess(
                        x[mask], y[mask],
                        {"ell": row, "amp": res["amp"],
                         "nugget": res["nugget"], "nll": res["map_nll"]},
                        "matern52")
                    for row in res["ell_samples"]]
                self.lengthscale_samples_[key] = res["ell_samples"]
                self.posterior_info_[key] = {
                    "accept_rate": res["accept_rate"],
                    "seed": res["seed"],
                    "n_samples": res["n_samples"],
                    "burn": res["burn"],
                    "thin": res["thin"],
                    "amp": res["amp"],
                    "nugget": res["nugget"]}
                if res.get("sampler") == "nuts":
                    self.posterior_diag_[key] = {
                        "sampler": "nuts",
                        "move_rate": res["move_rate"],
                        "tree_depth_mean": res["tree_depth_mean"],
                        "n_divergent": res["n_divergent"],
                        "leapfrog_total": res["leapfrog_total"],
                        "step_size": res["step_size"],
                        "max_tree_depth": res["max_tree_depth"]}
                med = np.median(res["ell_samples"], axis=0)
                self.lengthscales_[key] = {
                    n: float(v) for n, v in zip(self.names, med, strict=True)}
            else:
                params = fit_map(x[mask], y[mask], kind="matern52",
                                 prior=prior)
                self.models[key] = DetGaussianProcess(x[mask], y[mask],
                                                      params, "matern52")
                self.lengthscales_[key] = {
                    n: float(v) for n, v in zip(self.names, params["ell"],
                                                strict=True)}
            self.active_dims_[key] = [
                n for n, v in self.lengthscales_[key].items() if v < thr]
        return self._mark_fitted(len(samples))

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def _resolve_metric(self, metric: str | None) -> str:
        if not self.models:
            raise ValueError(
                "无可用指标（全部键有效点不足被跳过）——采集面不可用")
        if metric is None:
            return sorted(self.models)[0]
        if metric not in self.models:
            raise ValueError(
                f"未知指标 {metric!r}；可用: {sorted(self.models)}")
        return metric

    def _gps_for(self, metric: str) -> list[DetGaussianProcess]:
        """该指标的预测 GP 列表（posterior 档=M 条样本 GP；MAP 档=单点）。"""
        if metric in self.sample_models_:
            return self.sample_models_[metric]
        return [self.models[metric]]

    def _pool_rows(self, candidates: list[dict[str, float]]) -> np.ndarray:
        if not candidates:
            return np.zeros((0, len(self.names)))
        return np.array([self._unit_row(c) for c in candidates])

    # ---------------------------------------------------------------- 预测
    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        self._check_fitted()
        x = self._unit_row(params)[None, :]
        if self.posterior_mode:
            return {key: float(np.mean(
                        [float(gp.predict(x)[0][0]) for gp in gps]))
                    for key, gps in self.sample_models_.items()}
        return {key: float(gp.predict(x)[0][0])
                for key, gp in self.models.items()}

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        self._check_fitted()
        x = self._unit_row(params)[None, :]
        if self.posterior_mode:
            out: dict[str, float] = {}
            for key, gps in self.sample_models_.items():
                means, variances = [], []
                for gp in gps:
                    mu, var = gp.predict(x)
                    means.append(float(mu[0]))
                    variances.append(float(var[0]))
                var = float(np.mean(variances)) + float(np.var(means))
                out[key] = float(np.sqrt(max(var, 0.0)))
            return out
        return {key: float(np.sqrt(max(gp.predict(x)[1][0], 0.0)))
                for key, gp in self.models.items()}

    # ------------------------------------------------- 采集面（T-N11）
    def acquire_lcb(
        self, candidates: list[dict[str, float]], *, beta: float = 2.0,
        metric: str | None = None,
    ) -> list[float]:
        """平均 LCB（逐样本 LCB_β=μ_m−β·σ_m 后平均；MAP 档=单点 LCB）。

        确定性：同（拟合态，candidates, beta）→ 逐位复现（无随机源）。
        """
        self._check_fitted()
        key = self._resolve_metric(metric)
        rows = self._pool_rows(candidates)
        if rows.shape[0] == 0:
            return []
        gps = self._gps_for(key)
        vals = np.zeros(rows.shape[0])
        for gp in gps:
            mu, var = gp.predict(rows)
            vals += mu - float(beta) * np.sqrt(np.maximum(var, 0.0))
        return [float(v) for v in vals / len(gps)]

    def acquire_ei(
        self, candidates: list[dict[str, float]], *, xi: float = 0.0,
        metric: str | None = None,
    ) -> list[float]:
        """平均 EI（逐样本极小化 EI 后平均；MAP 档=单点 EI）。

        y_best = 该指标训练目标最小值（观测无噪声口径，全样本共享）。
        确定性：同（拟合态，candidates, xi）→ 逐位复现（无随机源）。
        """
        self._check_fitted()
        key = self._resolve_metric(metric)
        rows = self._pool_rows(candidates)
        if rows.shape[0] == 0:
            return []
        gps = self._gps_for(key)
        y_best = float(np.min(gps[0].y_train))
        vals = np.zeros(rows.shape[0])
        for gp in gps:
            mu, var = gp.predict(rows)
            sigma = np.sqrt(np.maximum(var, 0.0))
            vals += expected_improvement(mu, sigma, y_best, xi=xi)
        return [float(v) for v in vals / len(gps)]
