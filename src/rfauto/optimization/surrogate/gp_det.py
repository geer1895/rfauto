"""确定性 ARD 高斯过程内核（EC-16/17/18 三件的共享数值底座）。

定位（池 P3 圈定件批，架构批 W5-S22）：numpy+scipy 零新依赖的紧凑
GP 实现——闭式后验 + 超参沿负对数边际似然（MLE）或 MAP（先验罚项）
的确定性优化（L-BFGS-B，固定初值/固定数据 → 同结果逐位可复现，C4）。
本模块不注册 surrogate_registry（内部底座），对外键面由消费模块给出：

- EC-16 warped_kriging（HEBO 式 Kumaraswamy 输入扭曲，SE 核 MLE）；
- EC-17 saas_gp（SAAS 精神稀疏 ARD 先验，Matérn 5/2 核 MAP）；
- EC-18 turbo（TuRBO-1 信任域局部 GP，SE 核 MLE）。

核函数法源：
- SE（RBF）：Rasmussen & Williams, "Gaussian Processes for Machine
  Learning", MIT Press 2006, §4.2（k(x,x')=σ_f²·exp(−½Σ_i ((x_i−x'_i)/ℓ_i)²)）；
- Matérn 5/2：同书 §4.2.1（ν=5/2 有理形式，SAASBO/BoTorch 缺省核）。

数值口径：
- 归一化输入 [0,1]^d 由调用方负责（消费模块各自单元化）；
- K 对角叠加 nugget（噪声方差）+ 1e-12 抖动再 Cholesky（PD 守卫）；
- NLL：R&W 式 (5.8)-(5.9) 的负号版，常数项保留（跨调用可比）；
- 诚实边界：这是精确小样本 GP（O(n³)），n≳2000 的规模化（SOBER/SGPR
  等近似档）不在本模块（本仓战役样本量远低于该门槛）。
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize

__all__ = [
    "KERNEL_KINDS",
    "DetGaussianProcess",
    "fit_map",
    "fit_mle",
    "gp_nll",
    "gp_posterior",
    "matern52_ard_kernel",
    "se_ard_kernel",
]

#: 支持的核种类（键面固定，新核须同时补 _kernel_matrix 分派与单测）
KERNEL_KINDS = ("se", "matern52")

#: Cholesky 前叠加的绝对抖动下限（数值 PD 守卫，非建模噪声）
_JITTER = 1e-12


def se_ard_kernel(
    a: np.ndarray, b: np.ndarray, ell: np.ndarray, amp: float,
) -> np.ndarray:
    """平方指数 ARD 核矩阵（a: n×d，b: m×d，ell: 每维长度尺度）。"""
    d = a[:, None, :] - b[None, :, :]
    z = (d / np.maximum(ell, 1e-12)[None, None, :]) ** 2
    return amp * amp * np.exp(-0.5 * z.sum(axis=2))


def matern52_ard_kernel(
    a: np.ndarray, b: np.ndarray, ell: np.ndarray, amp: float,
) -> np.ndarray:
    """Matérn 5/2 ARD 核矩阵（ν=5/2，R&W 式 (4.17)）。"""
    d = a[:, None, :] - b[None, :, :]
    r = np.sqrt(((d / np.maximum(ell, 1e-12)[None, None, :]) ** 2).sum(axis=2))
    s = np.sqrt(5.0) * r
    return amp * amp * ((1.0 + s + s * s / 3.0) * np.exp(-s))


def _kernel_matrix(
    a: np.ndarray, b: np.ndarray, ell: np.ndarray, amp: float,
    kind: str,
) -> np.ndarray:
    if kind == "se":
        return se_ard_kernel(a, b, ell, amp)
    if kind == "matern52":
        return matern52_ard_kernel(a, b, ell, amp)
    raise ValueError(f"未知核种类: {kind}，可用: {KERNEL_KINDS}")


def gp_posterior(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    *,
    ell: np.ndarray,
    amp: float,
    nugget: float,
    kind: str = "se",
) -> tuple[np.ndarray, np.ndarray]:
    """闭式条件后验（R&W 式 (2.22)-(2.24)）：返回 (mean, var) 于 x_test。"""
    n = x_train.shape[0]
    k_tt = _kernel_matrix(x_train, x_train, ell, amp, kind)
    k_tt[np.diag_indices(n)] += max(float(nugget), 0.0) + _JITTER
    k_st = _kernel_matrix(x_test, x_train, ell, amp, kind)
    k_ss = _kernel_matrix(x_test, x_test, ell, amp, kind)
    chol = np.linalg.cholesky(k_tt)
    alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, y_train))
    mean = k_st @ alpha
    v = np.linalg.solve(chol, k_st.T)
    var = np.maximum(np.diag(k_ss) - (v * v).sum(axis=0), 0.0)
    return mean, var


def gp_nll(
    log_params: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    kind: str = "se",
    nugget: float | None = None,
    prior: dict[str, float] | None = None,
) -> float:
    """负对数（边际似然 + 可选先验），MAP/MLE 统一目标。

    log_params = [log ℓ_1..log ℓ_d, log σ_f]（nugget 可优化时末位再附
    log σ_n）。prior 键（SAAS 档）：log_ell_mean/log_ell_var（log ℓ 的
    高斯先验，κ 全部维度共享），罚项 = ½·Σ (log ℓ_i−m)²/s² 逐维计入。
    """
    d = x.shape[1]
    ell = np.exp(log_params[:d])
    amp = float(np.exp(log_params[d]))
    if log_params.size > d + 1:  # 末位 log nugget（MLE 可优化档）
        nugget = float(np.exp(log_params[d + 1]))
    if nugget is None:
        # W6-P3-4（架构批 W1-S4）：assert 做控制流在 -O 下失效（届时 None
        # 潜行到 max(float(nugget),...) 才 TypeError）——显式守卫单点拦截。
        raise ValueError(
            "gp_nll 需要 nugget：传 nugget=None 时 log_params 必须附末位 "
            "log σ_n（可优化档），否则显式传固定值")
    k = _kernel_matrix(x, x, ell, amp, kind)
    k[np.diag_indices(x.shape[0])] += max(float(nugget), 0.0) + _JITTER
    chol = np.linalg.cholesky(k)
    alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, y))
    nll = (0.5 * float(y @ alpha)
           + float(np.log(np.diag(chol)).sum())
           + 0.5 * x.shape[0] * np.log(2.0 * np.pi))
    if prior is not None:
        m = float(prior.get("log_ell_mean", 0.0))
        s2 = max(float(prior.get("log_ell_var", 100.0)), 1e-12)
        nll += 0.5 * float(((log_params[:d] - m) ** 2).sum()) / s2
    return nll


def _fit(
    x: np.ndarray, y: np.ndarray, *, kind: str,
    optimize_nugget: bool, prior: dict[str, float] | None,
    init: dict[str, Any] | None, maxiter: int,
) -> dict[str, Any]:
    d = x.shape[1]
    var_y = float(np.var(y))
    ell0 = np.full(d, float((init or {}).get("ell", 0.5)))
    amp0 = float(np.sqrt(max(var_y, 1e-12)) if var_y > 0 else 1.0)
    nug_fixed = (init or {}).get("nugget")
    nugget = (max(float(nug_fixed), 0.0) if nug_fixed is not None
              else max(var_y, 1.0) * 1e-6 + 1e-10)
    x0 = [ell0, np.array([amp0])]
    bounds = [(-6.0, 8.0)] * d + [(-10.0, 10.0)]
    if optimize_nugget:
        x0.append(np.array([np.log(max(nugget, 1e-10))]))
        bounds.append((-16.0, 2.0))
    theta0 = np.concatenate(x0)
    res = minimize(gp_nll, theta0, args=(x, y, kind,
                                         None if optimize_nugget else nugget,
                                         prior),
                   method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": int(maxiter), "ftol": 1e-12})
    dd = x.shape[1]
    ell = np.exp(res.x[:dd])
    amp = float(np.exp(res.x[dd]))
    nug = (float(np.exp(res.x[dd + 1])) if optimize_nugget else nugget)
    return {"ell": ell, "amp": amp, "nugget": nug,
            "nll": float(res.fun), "converged": bool(res.success)}


def fit_mle(
    x: np.ndarray, y: np.ndarray, *, kind: str = "se",
    optimize_nugget: bool = False, init: dict[str, Any] | None = None,
    maxiter: int = 200,
) -> dict[str, Any]:
    """无先验 MLE 档（确定性：固定初值 + L-BFGS-B，同数据同结果）。

    缺省 nugget 固定为 max(var(y), 1)·1e-6+1e-10（var(y)<1 时取 1.0 地板，
    W6-P3-3 文档对齐：旧文"1e-6·var(y)+1e-10"漏写地板项）不参与优化
    （SMT KRG 的插值口径）：小样本上"联优 nugget"会退化到"把信号全解释成
    噪声"的常数
    预测器（实测 n=14 的 √x 面 NRMSE=1.0、nugget→0.5·var）——真要联优
    须显式 optimize_nugget=True 并自担该退化风险（消费方做交叉验证
    自证后才可采信）。
    """
    return _fit(x, y, kind=kind, optimize_nugget=optimize_nugget,
                prior=None, init=init, maxiter=maxiter)


def fit_map(
    x: np.ndarray, y: np.ndarray, *, kind: str = "matern52",
    prior: dict[str, float], init: dict[str, Any] | None = None,
    maxiter: int = 200,
) -> dict[str, Any]:
    """MAP 档（先验罚项入目标；EC-17 SAAS 档用 log_ell 高斯先验）。

    SAAS 档固定 nugget 不参与优化（先验语义集中在长度尺度上，且去掉
    nugget 自由度保证同数据 MAP 解唯一确定——建模选择，如实标注）。
    """
    return _fit(x, y, kind=kind, optimize_nugget=False,
                prior=prior, init=init, maxiter=maxiter)


class DetGaussianProcess:
    """拟合态 ARD-GP 便捷载体（predict 只读已训练状态，C4 纯函数语义）。"""

    def __init__(
        self, x_train: np.ndarray, y_train: np.ndarray,
        params: dict[str, Any], kind: str,
    ) -> None:
        self.x_train = np.asarray(x_train, dtype=float)
        self.y_train = np.asarray(y_train, dtype=float)
        self.ell = np.asarray(params["ell"], dtype=float)
        self.amp = float(params["amp"])
        self.nugget = float(params["nugget"])
        self.kind = kind
        self.nll = float(params["nll"])

    def predict(self, x_test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return gp_posterior(
            self.x_train, self.y_train, np.atleast_2d(x_test),
            ell=self.ell, amp=self.amp, nugget=self.nugget, kind=self.kind)
