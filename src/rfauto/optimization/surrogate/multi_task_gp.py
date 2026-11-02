"""多任务/多输出确定性 GP（ICM 共区域化核，T-N12，aurora_n W2）。

定位：既有代理面逐指标独立 GP（gp_det 底座的 EC-16/17/18 各自单指标
拟合）升格为**跨指标联合建模**——多指标共享输入核 × 指标间共区域化
矩阵 B，曲线形状先验跨指标共享 + 跨指标相关免费产出后验协方差
（``predict_joint``，多目标采集 T-N13/qNEHVI 消费预留面）。

法源（实施前三源实读，2026-10-29；预声明账本
runs/aurora_n/w2_tn12/CRITERIA.md §0）：

- **Bonilla, Chai & Williams, "Multi-task Gaussian Process Prediction",
  NIPS 2007（全文实读）**：https://papers.nips.cc/paper_files/paper/2007/
  hash/66368270ffd51418ec58bd793f2d9b1b-Paper.pdf
  - 模型式 (1)：⟨f_l(x)f_k(x')⟩ = K_f^{lk}·k_x(x,x')——ICM（intrinsic
    coregionalization model，单数据核 × 自由形态任务协方差矩阵）；
    **k_x 约束为相关函数（单位振幅）**："the variance can be explained
    fully by K_f"——本实现照此把 gp_det 核 amp 钉 1.0，方差全部由 B
    承载（避免 amp×B 冗余参数化）；
  - 联合协方差式 (2)：Σ = K_f ⊗ K_x + D ⊗ I，D=diag(σ_1²..σ_M²)——
    **观测噪声 = LCM 第二过程，共区域化矩阵取对角**（原文 §4："Our
    model for the observations corresponds to an LCM model with two
    processes: the process for f· and the noise process"）——本实现
    逐指标固定 nugget 对角入 Σ（``optimize_noise=True`` 时联优）；
  - **正定化：K_f = L Lᵀ Cholesky**（原文 §2.2："In order to guarantee
    positive-semidefiniteness of K_f, one possible parametrization is to
    use the Cholesky decomposition"）——本实现取 L 为 M×rank 无约束
    因子（rank=M 时与下三角 Cholesky 张成同一 PSD 锥；因子式同
    GPyTorch covar_factor 形态，规避三角约束的打包复杂度）；
  - **传递抵消警告（原文 §2.3，本档实验设计依据）**：无噪声 + 块设计
    （同位置全任务观测）⇒ 跨任务预测不获益（autokrigeability）——
    "if the observations are noisy, or if there is not a block design,
    this result ... will not hold"。跨指标收益要求噪声>0 或异位设计；
    本档缺省固定 nugget>0 且支持异位（逐指标独立观测掩码），两条件
    天然满足。
- **GPyTorch MultiTaskKernel/IndexKernel 官方文档（实读）**：
  https://docs.gpytorch.ai/en/stable/kernels.html ——IndexKernel
  k(i,j)=(BBᵀ+diag(v))_{i,j}（低秩因子缺省 rank=1 + 非负对角 v），与
  数据核按 Kronecker 积组合（K=K_TT⊗K_XX）；LCMKernel=多基核
  Kronecker 积之线性和。B 语义（对称 PSD 任务协方差）与 Bonilla 一致；
  正定化路线两源并存（Bonilla 纯 Cholesky 因子 vs GPyTorch 因子+学习
  对角），本档取 Bonilla 纯因子形 + 固定对角 nugget（噪声归 D 不归
  B），差异如实标注。
- **Álvarez, Rosasco & Lawrence, "Kernels for Vector-Valued Functions:
  a Review", FnTML 2012（§4 实读）**：https://arxiv.org/abs/1106.6251
  ——可分离核式 (9) K(x,x')=k(x,x')·B（B 对称 PSD）；一般 LMC/SoS
  K(x,x')=Σ_q k_q(x,x')·B_q，矩阵形式式 (10) K(X,X)=Σ_q B_q⊗k_q(X,X)；
  本档为 Q=1 的 ICM 特例。

单源纪律：SE/Matérn ARD 核、数值口径（nugget 公式/_JITTER PD 守卫/
L-BFGS-B 固定选项）复用 optimization/surrogate/gp_det 既有件，不复制。

确定性（C4）：拟合路径除因子初值（由 ``seed`` 经
np.random.default_rng 确定性生成，同 seed 同数据逐位复现）外无随机
源——固定初值 + L-BFGS-B（同 gp_det fit_mle 口径），同 config 同数据
两次拟合结果逐位一致。

诚实边界：
- 精确小样本 GP——堆叠 Gram 逐块装配 + Cholesky，复杂度 O((Σn_l)³)；
  小样本（n≲200、M≲8）毫秒-秒级；n_obs≳2000 的规模化（SOBER/SGPR/
  Kronecker 网格档）不在本模块（本仓战役样本量远低于该门槛）；
- M=1 时自然退化为单指标（B 为 1×1、等价普通 GP），不报错；
- 跨指标协方差 B 是潜过程量：指标噪声越大，B̂ 相对真 latent 相关的
  偏置越大（噪声归 D 不归 B 的口径后果，如实标注）。

消费预留：surrogate_loop/factory 接 ``mt_gp`` 属后续席（T-N13/qNEHVI
经 ``predict_joint`` 消费跨指标后验协方差），本席只交付注册面+判据面
（tests/unit/test_multi_task_gp.py，预声明门见
runs/aurora_n/w2_tn12/CRITERIA.md）。

注册即生效（基类+注册表模式，规则 3）：``surrogate_registry.create(
"mt_gp", config={...})``；纯增量键，既有 kind 消费面零改动。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import minimize

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)
from rfauto.optimization.surrogate.gp_det import (
    _JITTER,
    KERNEL_KINDS,
    matern52_ard_kernel,
    se_ard_kernel,
)

__all__ = [
    "DEFAULT_MT_SEED",
    "MultiTaskGPSurrogate",
    "MultiTaskGaussianProcess",
    "validate_coregionalization_matrix",
]

#: 因子初值 seed 缺省（固定值确定性钉；同 seed 同数据逐位复现）
DEFAULT_MT_SEED = 20261029

#: 共区域化矩阵 PSD 校验的相对容差（相对谱尺度；数值半正定带）
_PSD_TOL = 1e-10

#: NLL 数值异常回退值（Cholesky 失效时让优化器撤离该区域，非建模量）
_BIG_NLL = 1e25

#: 因子/噪声参数的优化盒（gp_det 同款量级，防 exp 溢出走核函数）
_FACTOR_BOUND = 15.0


def _kx_matrix(
    a: np.ndarray, b: np.ndarray, ell: np.ndarray, kind: str,
) -> np.ndarray:
    """输入核矩阵（amp=1 相关函数口径，Bonilla 式 (1) 约定）。"""
    if kind == "se":
        return se_ard_kernel(a, b, ell, 1.0)
    if kind == "matern52":
        return matern52_ard_kernel(a, b, ell, 1.0)
    raise ValueError(f"未知核种类: {kind}，可用: {KERNEL_KINDS}")


def validate_coregionalization_matrix(
    B: np.ndarray, name: str = "B",
) -> np.ndarray:
    """共区域化矩阵校验：对称 + 半正定，明确违例显式 ValueError。

    语义（CRITERIA G4b"非正定显式报错"）：数学要求是 **半正定**
    （Bonilla K_f、Álvarez 式 (9) B 均为 PSD 即可；秩亏 B 配噪声对角
    仍使 Σ 正定），故按"明确违反半正定"报错——非对称，或最小特征值
    < −tol·谱尺度。不修复、不静默、不降档。
    """
    B = np.asarray(B, dtype=float)
    if B.ndim != 2 or B.shape[0] != B.shape[1] or B.shape[0] == 0:
        raise ValueError(f"{name} 必须是非空方阵，收到 shape={B.shape}")
    if not np.allclose(B, B.T, atol=1e-10, rtol=0.0):
        raise ValueError(f"{name} 非对称：共区域化矩阵必须对称（PSD 前提）")
    sym = 0.5 * (B + B.T)
    scale = max(float(np.abs(sym).max()), 1.0)
    eig_min = float(np.linalg.eigvalsh(sym).min())
    if eig_min < -_PSD_TOL * scale:
        raise ValueError(
            f"{name} 非半正定（最小特征值 {eig_min:.3e} < 0）：共区域化"
            "矩阵必须 PSD（Bonilla 2007 §2.2 / Álvarez 2012 式 (9)），"
            "拒绝修复与静默")
    return sym


def _numeric_metric_keys(samples: list[dict[str, Any]]) -> list[str]:
    """样本 metrics 数值键并集（排序；smt_kriging/warped_kriging 同约定）。"""
    keys: set[str] = set()
    for s in samples:
        keys |= {k for k, v in s.get("metrics", {}).items()
                 if isinstance(v, (int, float))}
    return sorted(keys)


def _stacked_sigma(
    task_x: list[np.ndarray],
    B: np.ndarray,
    ell: np.ndarray,
    kind: str,
    nuggets: np.ndarray,
) -> tuple[np.ndarray, list[int], list[int]]:
    """堆叠观测 Gram：Σ[(i,l),(j,k)] = B_{lk}·k_x(x_i^{(l)},x_j^{(k)})
    + δ_{lk}δ_{ij}·σ_l²（Bonilla 式 (2) 的异位观测子集形态；按观测
    位置块装配，不物化全 Kronecker）。

    返回 (Σ, 行偏移表, 各任务观测数表)——偏移表同时服务交叉协方差装配。
    """
    n_task = len(task_x)
    sizes = [int(x.shape[0]) for x in task_x]
    n_obs = sum(sizes)
    offsets = [0]
    for s in sizes:
        offsets.append(offsets[-1] + s)
    sigma = np.zeros((n_obs, n_obs))
    for ti in range(n_task):
        for tj in range(n_task):
            if abs(float(B[ti, tj])) < 1e-300:
                continue
            block = float(B[ti, tj]) * _kx_matrix(
                task_x[ti], task_x[tj], ell, kind)
            sigma[offsets[ti]:offsets[ti + 1],
                  offsets[tj]:offsets[tj + 1]] += block
    for ti in range(n_task):
        rows = range(offsets[ti], offsets[ti + 1])
        for r in rows:
            sigma[r, r] += max(float(nuggets[ti]), 0.0)
    sigma[np.diag_indices(n_obs)] += _JITTER
    return sigma, offsets, sizes


def _cross_cov(
    x_test: np.ndarray,
    task_x: list[np.ndarray],
    B: np.ndarray,
    ell: np.ndarray,
    kind: str,
    offsets: list[int],
) -> np.ndarray:
    """测试行 × 观测堆叠的交叉协方差 C[(r,l),(i,k)]=B_{lk}·k_x(x*_r,x_i^{(k)})。"""
    n_test = int(x_test.shape[0])
    n_task = len(task_x)
    n_obs = offsets[-1]
    C = np.zeros((n_test * n_task, n_obs))
    for ti in range(n_task):
        for tj in range(n_task):
            if abs(float(B[ti, tj])) < 1e-300:
                continue
            C[ti * n_test:(ti + 1) * n_test,
              offsets[tj]:offsets[tj + 1]] = float(B[ti, tj]) * _kx_matrix(
                x_test, task_x[tj], ell, kind)
    return C


def _stacked_nll(
    theta: np.ndarray,
    task_x: list[np.ndarray],
    task_y: list[np.ndarray],
    d: int,
    rank: int,
    kind: str,
    fixed_nuggets: np.ndarray | None,
    fixed_B: np.ndarray | None,
) -> float:
    """负对数边际似然（堆叠输出版 R&W 式 (5.8)-(5.9)，常数项保留）。

    theta = [log ℓ_1..log ℓ_d] + [L 因子 flat M×rank]
            + [log σ_l² × M（fixed_nuggets=None 时）]；
    fixed_B 给定时因子项缺席（B 钉先验，只优 ℓ/噪声）。
    """
    n_task = len(task_x)
    ell = np.exp(theta[:d])
    pos = d
    if fixed_B is None:
        L = theta[pos:pos + n_task * rank].reshape(n_task, rank)
        B = L @ L.T
        pos += n_task * rank
    else:
        B = fixed_B
    nuggets = (np.exp(theta[pos:]) if fixed_nuggets is None
               else fixed_nuggets)
    y = np.concatenate(task_y)
    try:
        sigma, _offs, _sz = _stacked_sigma(task_x, B, ell, kind, nuggets)
        chol = np.linalg.cholesky(sigma)
    except np.linalg.LinAlgError:
        return _BIG_NLL
    alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, y))
    n_obs = y.size
    nll = (0.5 * float(y @ alpha)
           + float(np.log(np.diag(chol)).sum())
           + 0.5 * n_obs * math.log(2.0 * math.pi))
    return nll


class MultiTaskGaussianProcess:
    """拟合态 ICM 多任务 GP 载体（predict 只读已训练状态，C4 纯函数语义）。

    状态 = 逐任务 (X_l, y_l)（单元空间）、共享 ℓ、共区域化矩阵 B、
    逐任务 nugget；后验面 = 堆叠观测 Gram 的 Cholesky 解（构造期一次）。
    """

    def __init__(
        self,
        task_x: list[np.ndarray],
        task_y: list[np.ndarray],
        keys: list[str],
        *,
        ell: np.ndarray,
        B: np.ndarray,
        nuggets: np.ndarray,
        kind: str,
        nll: float,
    ) -> None:
        self.task_x = [np.asarray(x, dtype=float) for x in task_x]
        self.task_y = [np.asarray(y, dtype=float) for y in task_y]
        self.keys = list(keys)
        self.ell = np.asarray(ell, dtype=float)
        self.B = validate_coregionalization_matrix(np.asarray(B, dtype=float))
        self.nuggets = np.asarray(nuggets, dtype=float)
        self.kind = kind
        self.nll = float(nll)
        self._sigma, self._offsets, self._sizes = _stacked_sigma(
            self.task_x, self.B, self.ell, self.kind, self.nuggets)
        self._chol = np.linalg.cholesky(self._sigma)
        y = np.concatenate(self.task_y)
        self._alpha = np.linalg.solve(
            self._chol.T, np.linalg.solve(self._chol, y))

    def _prepare(self, x_test: np.ndarray) -> np.ndarray:
        return np.atleast_2d(np.asarray(x_test, dtype=float))

    def predict_batch(
        self, x_test: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """批后验均值/标准差：返回 (means (n,M), stds (n,M))，任务序=keys。

        后验方差 = B_{ll}·k_x(x*,x*) − cᵀΣ⁻¹c（R&W 式 (2.26) 堆叠版）；
        k_x(x*,x*) 对 SE/Matérn 零距恒为 1.0（amp=1 相关函数口径，精确
        恒等式非近似）。
        """
        xs = self._prepare(x_test)
        n_test = int(xs.shape[0])
        M = len(self.keys)
        C = _cross_cov(xs, self.task_x, self.B, self.ell, self.kind,
                       self._offsets)
        mean = (C @ self._alpha).reshape(M, n_test).T  # (n, M)
        v = np.linalg.solve(self._chol, C.T)  # (n_obs, n*M)
        prior_var = np.repeat(
            np.maximum(np.diag(self.B), 0.0)[None, :], n_test, axis=0)
        post_var = np.maximum(
            prior_var - (v * v).sum(axis=0).reshape(n_test, M), 0.0)
        return mean, np.sqrt(post_var)

    def predict_joint(
        self, x_test: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """单点全后验 (means (M,), cov (M,M))——跨指标后验协方差（T-N13
        qNEHVI 消费预留面；对角=各指标 σ²，非对角=跨指标相关）。

        K*(x*,x*) = B ⊗ k_x(x*,x*) − C Σ⁻¹ Cᵀ（Bonilla 式 (2) 后验；
        k_x(x*,x*)=1.0 amp=1 口径）。
        """
        xs = self._prepare(x_test)
        if int(xs.shape[0]) != 1:
            raise ValueError(
                "predict_joint 只收单点（x_test 一行）；批量请走 "
                "predict_batch 对角面")
        M = len(self.keys)
        C = _cross_cov(xs, self.task_x, self.B, self.ell, self.kind,
                       self._offsets)
        mean = (C @ self._alpha).reshape(M)
        v = np.linalg.solve(self._chol, C.T)  # (n_obs, M)
        cov = self.B - v.T @ v
        cov = 0.5 * (cov + cov.T)
        return mean, cov


@surrogate_registry.register("mt_gp")
class MultiTaskGPSurrogate(SurrogateModel):
    """ICM 多任务 GP 代理（T-N12，opt-in 新键 ``mt_gp``）。

    config:
        bounds: {param: (low, high)}（必填，单元归一化基准，同
            warped_kriging/smt_kriging 约定）。
        metrics: 指标键列表（缺省 = fit 样本全部数值键并集，排序）。
        kernel: "se"（缺省）| "matern52"（复用 gp_det 核面）。
        rank: B=L Lᵀ 因子秩（缺省 = M 自由形态；1..M）。
        fixed_B: 先验共区域化矩阵（嵌套 list，按指标键排序序）——
            给定时 B 不学习（ℓ/噪声仍优）；非对称/非半正定显式
            ValueError（validate_coregionalization_matrix）。
        optimize_noise: log σ_l² 是否入 MLE（缺省 False，固定
            nugget=gp_det fit_mle 同式 max(var(y_l),1)·1e-6+1e-10；
            联优有"信号全解释成噪声"退化风险，同 gp_det 契约）。
        seed: 因子初值 seed（缺省 DEFAULT_MT_SEED；同 seed 逐位复现）。
        maxiter: L-BFGS-B 最大迭代（缺省 200，gp_det 同款）。
    """

    KIND = "mt_gp"

    def _unit_rows(self, samples: list[dict[str, Any]]) -> np.ndarray:
        return np.array([
            [np.clip((float(s["params"].get(n, lo)) - lo)
                     / max(hi - lo, 1e-12), 0.0, 1.0)
             for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)]
            for s in samples])

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        self.bounds = {k: tuple(v)
                       for k, v in (self.config.get("bounds") or {}).items()}
        self.names = sorted(self.bounds)
        if not self.names:
            raise ValueError("mt_gp 需要 config['bounds']（非空，单元归一化"
                             "基准，同 warped_kriging 约定）")
        kind = str(self.config.get("kernel", "se"))
        if kind not in KERNEL_KINDS:
            raise ValueError(f"未知核种类: {kind}，可用: {KERNEL_KINDS}")
        keys = list(self.config.get("metrics")
                    or _numeric_metric_keys(samples))
        if not keys:
            raise ValueError(
                "mt_gp 拟合失败：样本 metrics 无任何数值指标（指标数 0），"
                "拒绝空拟（CRITERIA G4a）")
        x_all = self._unit_rows(samples)
        d = x_all.shape[1]
        task_x: list[np.ndarray] = []
        task_y: list[np.ndarray] = []
        task_keys: list[str] = []
        skipped: list[str] = []
        for key in keys:
            y = np.array([float(s["metrics"].get(key, np.nan))
                          for s in samples])
            mask = np.isfinite(y)
            if int(mask.sum()) < 3:
                skipped.append(key)  # 键缺测/全 NaN——跳过不硬拟（同约定）
                continue
            task_x.append(x_all[mask])
            task_y.append(y[mask])
            task_keys.append(key)
        if not task_keys:
            raise ValueError(
                "mt_gp 拟合失败：全部指标有效点 <3（有效指标数 0），"
                "拒绝空拟（CRITERIA G4a）")
        M = len(task_keys)
        rank = int(self.config.get("rank", M))
        if not 1 <= rank <= M:
            raise ValueError(
                f"rank 必须在 1..M（M={M}）内，收到 {rank}（CRITERIA G4c）")
        fixed_B: np.ndarray | None = None
        if self.config.get("fixed_B") is not None:
            fixed_B = validate_coregionalization_matrix(
                np.asarray(self.config["fixed_B"], dtype=float))
            if fixed_B.shape != (M, M):
                raise ValueError(
                    f"fixed_B shape {fixed_B.shape} 与指标数 {M} 不一致"
                    "（按指标键排序序对齐）")
        optimize_noise = bool(self.config.get("optimize_noise", False))
        nuggets = np.array([
            max(float(np.var(y)), 1.0) * 1e-6 + 1e-10 for y in task_y])

        # 参数向量与初值/盒（ℓ 共享；因子由 seed 确定性初始化）
        theta0: list[np.ndarray] = [np.full(d, math.log(0.5))]
        bounds: list[tuple[float, float]] = [(-6.0, 8.0)] * d
        if fixed_B is None:
            rng = np.random.default_rng(int(
                self.config.get("seed", DEFAULT_MT_SEED)))
            F0 = 0.7 * np.eye(M, rank) + 0.05 * rng.standard_normal((M, rank))
            theta0.append(F0.reshape(-1))
            bounds.extend([(-_FACTOR_BOUND, _FACTOR_BOUND)] * (M * rank))
        if optimize_noise:
            theta0.append(np.log(np.maximum(nuggets, 1e-12)))
            bounds.extend([(-16.0, 2.0)] * M)
        theta_init = np.concatenate(theta0)
        res = minimize(
            _stacked_nll, theta_init,
            args=(task_x, task_y, d, rank, kind,
                  None if optimize_noise else nuggets, fixed_B),
            method="L-BFGS-B", bounds=bounds or None,
            options={"maxiter": int(self.config.get("maxiter", 200)),
                     "ftol": 1e-12})
        ell = np.exp(res.x[:d])
        pos = d
        if fixed_B is None:
            B = (res.x[pos:pos + M * rank].reshape(M, rank)
                 @ res.x[pos:pos + M * rank].reshape(M, rank).T)
            pos += M * rank
        else:
            B = fixed_B
        fit_nuggets = (np.exp(res.x[pos:]) if optimize_noise else nuggets)
        # 事后诚实校验：理论 PSD（L Lᵀ / 先验校验）落浮点后仍守门
        validate_coregionalization_matrix(B, name="拟合 B")
        self.model = MultiTaskGaussianProcess(
            task_x, task_y, task_keys, ell=ell, B=B, nuggets=fit_nuggets,
            kind=kind, nll=float(res.fun))
        denom = np.sqrt(np.outer(
            np.maximum(np.diag(B), 0.0), np.maximum(np.diag(B), 0.0)))
        corr = np.divide(B, denom, out=np.full_like(B, np.nan),
                         where=denom > 0.0)
        info = {
            **self._mark_fitted(len(samples)),
            "metrics": list(task_keys),
            "skipped_metrics": skipped,
            "n_obs_per_metric": [int(x.shape[0]) for x in task_x],
            "ell": ell,
            "B": B,
            "corr": corr,
            "nugget": fit_nuggets,
            "nll": float(res.fun),
            "converged": bool(res.success),
        }
        self.info_ = info
        self.corr_ = corr
        return info

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def _row(self, params: dict[str, float]) -> np.ndarray:
        return np.array([
            np.clip((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12),
                    0.0, 1.0)
            for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)])

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        self._check_fitted()
        mean, _std = self.model.predict_batch(self._row(params)[None, :])
        return {key: float(mean[0, j])
                for j, key in enumerate(self.model.keys)}

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        self._check_fitted()
        _mean, std = self.model.predict_batch(self._row(params)[None, :])
        return {key: float(std[0, j])
                for j, key in enumerate(self.model.keys)}

    def predict_joint(
        self, params: dict[str, float],
    ) -> tuple[dict[str, float], np.ndarray]:
        """单点全后验（means dict, cov M×M）——跨指标后验协方差消费面
        （T-N13 qNEHVI 预留；本席只交付面，不做环内接线）。"""
        self._check_fitted()
        mean, cov = self.model.predict_joint(self._row(params)[None, :])
        return ({key: float(mean[j])
                 for j, key in enumerate(self.model.keys)}, cov)
