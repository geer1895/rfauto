"""GP 张量输入核：广义距离度量嵌入（PB-3，round5 插⑤）。

出处（arXiv:2407.15877 "Gaussian Process Model with Tensorial Inputs and
Its Application to the Design of 3D Printed Antennas"；配套数据 GitHub
xichennn/GP_dataset——仓库只含 CSV 数据集、无核代码：方法层双源
（arXiv abstract + repo README），**核心式单源**（arXiv HTML 全文
Eq.7-9，如实标注）：

- 论文把 IMED（Image Euclidean Distance，图像欧氏距离）嵌入标准 RBF：
  k(𝒳,𝒳') = σ²·exp(−d_IMED(𝒳,𝒳')/(2l))（Eq.8），其中
  d_IMED(𝒳,𝒳') = Σ_p (vec(𝒳^p)−vec(𝒳'^p))ᵀ G^p (vec(𝒳^p)−vec(𝒳'^p))
  （Eq.9，对 P 个材料通道求和），G^p 为正定度量阵，其元素由体素位置
  的高斯核给出（Eq.7：g^p_{αβ} ∝ exp(−|J_α−J_β|²/(2(γ^p)²))，含
  **非对角**项=体素空间邻近性）。G=I 时退化为普通欧氏距离；等价形式
  G=(A)ᵀA 时 IMED=变换坐标 Z=A·vec(𝒳) 上的普通欧氏距离。
- 本模块核形式 k=σ_f²·exp(−q/(2ℓ²))（q=广义**平方**距离）与论文 Eq.8
  经 ℓ²=l 重参数等价（d_IMED 本身即二次型/"平方距离"口径），如实注明。

v1 最小自实现口径（任务书钉，rwg_mmt 先例：独立内核不进任何注册表，
消费接线留后续）：
- **对角度量**：逐元素权重 w_e（ARD 类广义距离），q=Σ_e w_e(a_e−b_e)²；
  不实现论文 Eq.7 的非对角体素耦合 G（留后续），单位权重退化普通 RBF；
- **张量输入**：同形张量堆叠 (n, d1, d2, ...) 展平为 (n, F) 后与向量
  输入走同一路径（等价性钉测试保证两路径逐位一致）；
- 权重实现序=**√w 缩放坐标后标准欧氏**（先缩放后作差，与"缩放坐标后
  标准 RBF"恒等式逐位同序；不做 |a|²+|b|²−2ab 展开——后者有灾难性
  消去且求和序与直接作差不一致；直接作差的 (n,m,F) 中间量在小规模
  定位下内存可接受）；
- LOO/后验必加**相对 nugget**（×var(y)，core/metric_transform.py
  df6⑨ 先例同值同口径：插值型 GP 的 σ 塌缩防波堤）；
- 小规模定位：LOOCV 网格 n≤DEFAULT_MAX_POINTS=200（超限显式
  ValueError，不静默走慢路径）。

纯 numpy 零 sklearn 零 IO 零外部进程（铁律 7）。
"""

from __future__ import annotations

import math

import numpy as np

#: 相对 nugget（×var(y)）——与 core/metric_transform.py RELATIVE_NUGGET
#: 同值（df6⑨：插值型 GP 的 LOO 后验 σ 塌到机器零、logpdf 爆 ±1e12）
RELATIVE_NUGGET = 1e-8
#: nugget 绝对地板（防 var(y)=0 退化；metric_transform 同口径）
_NUGGET_ABS_FLOOR = 1e-10
#: 折内 σ 绝对地板（防 var 负零与下溢）
_SIGMA_FLOOR = 1e-12
#: LOOCV 小规模样本上限（超限显式拒绝）
DEFAULT_MAX_POINTS = 200
#: Cholesky 失败时 λ 阶梯（×10）最大重试数
_MAX_JITTER_TRIES = 5

__all__ = [
    "DEFAULT_MAX_POINTS",
    "RELATIVE_NUGGET",
    "fit_weights_loocv",
    "generalized_distance",
    "regression_predict",
    "tensor_rbf_kernel",
]


# ------------------------------------------------------------- 内部工具


def _finite_float_array(x: object, name: str) -> np.ndarray:
    """入参收敛为有限 float 数组；bool/复数/非数值/NaN/Inf 显式拒绝。"""
    a = np.asarray(x)
    if a.dtype.kind == "b":
        raise ValueError(f"{name} 必须是实数数组，收到 bool 数组")
    if np.iscomplexobj(a):
        raise ValueError(f"{name} 必须是实数数组，收到复数数组")
    try:
        a = a.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 无法转换为 float 数组: {exc}") from exc
    if a.size and not bool(np.isfinite(a).all()):
        raise ValueError(f"{name} 含 NaN/Inf")
    return a


def _positive_scalar(x: object, name: str) -> float:
    """正标量参数（lengthscale/sigma_f）校验。"""
    v = _finite_float_array(x, name)
    if v.ndim != 0:
        raise ValueError(f"{name} 必须是标量，收到形状 {v.shape}")
    f = float(v)
    if f <= 0.0:
        raise ValueError(f"{name} 必须为正数，收到 {f}")
    return f


def _sample_stack(x: object, name: str) -> np.ndarray:
    """样本堆叠入参：(n,) 视作 (n,1)，(n, ...) 保留；首轴恒为样本轴。"""
    a = _finite_float_array(x, name)
    if a.ndim == 0:
        raise ValueError(f"{name} 至少需要一维（首轴=样本轴）")
    return a


def _resolve_weights(
    weights: np.ndarray | None, trailing_shape: tuple[int, ...], name: str = "weights"
) -> np.ndarray | None:
    """权重收敛：None→单位权重；标量→广播填满；形状不符显式拒绝。"""
    if weights is None:
        return None
    w = _finite_float_array(weights, name)
    if w.ndim == 0:
        w = np.full(trailing_shape, float(w))
    if w.shape != tuple(trailing_shape):
        raise ValueError(
            f"{name} 形状 {w.shape} 与单样本形 {tuple(trailing_shape)} 不一致"
        )
    return w


def _flatten_pairs(
    A: np.ndarray, B: np.ndarray, weights: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """A/B/weights 统一校验并展平到 (n,F)/(m,F)/(F,)；共享同一单样本形。"""
    a3 = _sample_stack(A, "A")
    b3 = _sample_stack(B, "B")
    if a3.ndim == 1:
        a3 = a3[:, None]
    if b3.ndim == 1:
        b3 = b3[:, None]
    if a3.shape[1:] != b3.shape[1:]:
        raise ValueError(
            f"A/B 单样本形不一致: {a3.shape[1:]} vs {b3.shape[1:]}（张量输入须同形堆叠）"
        )
    w = _resolve_weights(weights, a3.shape[1:])
    return a3.reshape(a3.shape[0], -1), b3.reshape(b3.shape[0], -1), (
        None if w is None else w.reshape(-1)
    )


def _scaled_sqdist(
    af: np.ndarray, bf: np.ndarray, wf: np.ndarray | None
) -> np.ndarray:
    """√w 缩放坐标后的平方欧氏距离矩阵 (n,m)（实现序：先缩放后作差）。"""
    if wf is not None:
        s = np.sqrt(wf)
        af = af * s
        bf = bf * s
    d = af[:, None, :] - bf[None, :, :]
    out: np.ndarray = (d * d).sum(axis=-1)
    return out


def _gaussian_logpdf(yv: float, mu: float, sigma: float) -> float:
    """单点高斯 logpdf（σ 已地板化；metric_transform 同式）。"""
    return (
        -0.5 * ((yv - mu) / sigma) ** 2
        - math.log(sigma)
        - 0.5 * math.log(2.0 * math.pi)
    )


def _chol_factor(k: np.ndarray, nugget: float) -> np.ndarray:
    """K+λI 的 Cholesky 因子；数值非正定时 λ 阶梯 ×10 重试（确定性）。"""
    lam = float(nugget)
    last: Exception | None = None
    for _ in range(_MAX_JITTER_TRIES):
        try:
            return np.linalg.cholesky(k + lam * np.eye(k.shape[0]))
        except np.linalg.LinAlgError as exc:
            last = exc
            lam *= 10.0
    raise np.linalg.LinAlgError(
        f"K+λI 不可 Cholesky 分解（λ 阶梯 ×10 共 {_MAX_JITTER_TRIES} 次仍失败）: {last}"
    ) from last


def _loo_errors(k: np.ndarray, y: np.ndarray, nugget: float) -> tuple[float, float]:
    """单候选 (ℓ,w) 的 LOO：返回 (均方误差, 平均 logpdf)。

    逐折：K_train+λI Cholesky → held-out (μ,σ) → 残差平方与高斯
    logpdf（σ 地板化，df6⑨ 口径）。K 由调用方按候选预算好（对角恒
    σ_f²，exp(−0)=1 逐位精确）。
    """
    n = y.size
    idx = np.arange(n)
    sq = np.empty(n)
    lp = np.empty(n)
    for i in range(n):
        tr = idx[idx != i]
        chol = _chol_factor(k[np.ix_(tr, tr)], nugget)
        v = np.linalg.solve(chol, k[i, tr])  # L⁻¹k*（方差路径用）
        alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, y[tr]))  # (K+λI)⁻¹y
        mu = float(k[i, tr] @ alpha)
        var = max(float(k[i, i]) - float(v @ v), 0.0)
        sigma = max(math.sqrt(var), _SIGMA_FLOOR)
        resid = float(y[i]) - mu
        sq[i] = resid * resid
        lp[i] = _gaussian_logpdf(float(y[i]), mu, sigma)
    return float(sq.mean()), float(lp.mean())


# --------------------------------------------------------------- 公开 API


def generalized_distance(
    A: np.ndarray, B: np.ndarray, weights: np.ndarray | None = None
) -> np.ndarray:
    """同形张量堆叠输入的广义距离矩阵（逐元素加权欧氏，IMED 对角度量）。

    d²[i,j] = Σ_e w_e·(A[i,e]−B[j,e])²（对角度量版论文 Eq.9；w=None
    退化为普通欧氏距离）。实现序=√w 缩放坐标后标准欧氏（模块 docstring
    "权重实现序"节），与"缩放坐标后标准距离"逐位同序。

    Args:
        A: (n,) 或 (n, d1, d2, ...) 样本堆叠（首轴=样本；(n,) 视作单特征）。
        B: (m,) 或 (m, ...)，单样本形须与 A 一致。
        weights: 单样本形 (d1, d2, ...) 的逐元素权重（或标量广播）；
            None=单位权重。

    Returns:
        (n, m) 距离矩阵（非负）。

    Raises:
        ValueError: A/B 单样本形不一致、weights 形状不符、bool/复数/
            NaN/Inf 入参。
    """
    af, bf, wf = _flatten_pairs(A, B, weights)
    dist: np.ndarray = np.sqrt(_scaled_sqdist(af, bf, wf))
    return dist


def tensor_rbf_kernel(
    A: np.ndarray,
    B: np.ndarray,
    lengthscale: float,
    weights: np.ndarray | None = None,
    sigma_f: float = 1.0,
) -> np.ndarray:
    """广义距离上的 RBF 核：k=σ_f²·exp(−q/(2ℓ²))（论文 Eq.8 等价重参数）。

    q=广义平方距离（generalized_distance 的平方，直接由内部平方路径
    产出、不经 sqrt 往返）。w=None 且 1 维输入时与手写经典 RBF 逐位
    一致（标量极限判据锚）。

    Args:
        A/B: 同 generalized_distance。
        lengthscale: 正标量 ℓ。
        weights: 同 generalized_distance。
        sigma_f: 正标量信号标准差（核幅 σ_f²）。

    Returns:
        (n, m) 核矩阵；对角元（A is B 时）恒 =σ_f²（q 对角逐位为 0）。

    Raises:
        ValueError: 形状/值域守卫（同 generalized_distance）+
            lengthscale/sigma_f 非正。
    """
    ell = _positive_scalar(lengthscale, "lengthscale")
    sf = _positive_scalar(sigma_f, "sigma_f")
    af, bf, wf = _flatten_pairs(A, B, weights)
    q = _scaled_sqdist(af, bf, wf)
    return (sf * sf) * np.exp(-q / (2.0 * ell * ell))


def fit_weights_loocv(
    A: np.ndarray,
    y: np.ndarray,
    lengthscale_grid: list[float] | tuple[float, ...] | np.ndarray,
    weights_grid: list[np.ndarray | None] | None = None,
    *,
    sigma_f: float = 1.0,
    relative_nugget: float = RELATIVE_NUGGET,
    max_points: int = DEFAULT_MAX_POINTS,
) -> dict[str, object]:
    """长度尺度（与可选权重候选）小网格 LOOCV 选择（纯 numpy，n≤200）。

    目标=逐折留一（LOO）均方误差（argmin；平局取先）；每折 GP 用相对
    nugget（×var(y)，df6⑨ 口径）防插值 σ 塌缩，同时记录平均高斯
    logpdf 供 informational 对照。σ_f 与均值函数（零均值）固定，不参与
    网格——v1 最小口径。K 按权重候选预算、长度尺度内层复用平方距离。

    Args:
        A: (n, ...) 样本堆叠（张量/向量均可）。
        y: (n,) 目标（有限实数）。
        lengthscale_grid: 正标量候选序列（非空）。
        weights_grid: 可选权重候选序列（每项=单样本形数组或 None=单位
            权重）；None=[None]（只选 ℓ）。
        sigma_f: 固定信号标准差（正标量）。
        relative_nugget: 相对 nugget 系数（≥0）。
        max_points: 样本数上限（超限显式 ValueError）。

    Returns:
        dict：lengthscale（最优 ℓ）、weights（最优权重数组或 None）、
        loocv_mse、loocv_mean_logpdf、nugget（实际 λ=相对 nugget×var(y)
        带 _NUGGET_ABS_FLOOR 地板）、n_candidates、table（逐候选
        weights_index/lengthscale/loocv_mse/loocv_mean_logpdf）。

    Raises:
        ValueError: 样本数 <3 或 >max_points、网格空/非正、形状/值域
            守卫（同 generalized_distance）。
    """
    yv = _finite_float_array(y, "y").ravel()
    n = yv.size
    a3 = _sample_stack(A, "A")
    if a3.ndim == 1:
        a3 = a3[:, None]
    if a3.shape[0] != n:
        raise ValueError(f"A/y 行数不一致: {a3.shape[0]} vs {n}")
    if n < 3:
        raise ValueError(f"LOOCV 至少需要 3 个样本，收到 {n}")
    if n > int(max_points):
        raise ValueError(
            f"样本数 {n} 超出小规模 LOOCV 上限 max_points={int(max_points)}"
        )
    ls_vals = np.atleast_1d(_finite_float_array(lengthscale_grid, "lengthscale_grid"))
    if ls_vals.size == 0:
        raise ValueError("lengthscale_grid 不能为空")
    ls_grid = [_positive_scalar(v, "lengthscale_grid[i]") for v in ls_vals]
    if weights_grid is None:
        cand_weights: list[np.ndarray | None] = [None]
    else:
        cand_weights = [
            None if w is None else _resolve_weights(w, a3.shape[1:])
            for w in weights_grid
        ]
    nugget_coef = float(
        _finite_float_array(relative_nugget, "relative_nugget")
    )
    if nugget_coef < 0.0:
        raise ValueError(f"relative_nugget 必须 >=0，收到 {nugget_coef}")
    sf = _positive_scalar(sigma_f, "sigma_f")
    lam = max(nugget_coef * float(np.var(yv)), _NUGGET_ABS_FLOOR)
    af = a3.reshape(n, -1)
    table: list[dict[str, object]] = []
    best: tuple[float, float, int, float] | None = None
    for wi, cand in enumerate(cand_weights):
        wf = None if cand is None else cand.reshape(-1)
        q = _scaled_sqdist(af, af, wf)
        for ell in ls_grid:
            k = (sf * sf) * np.exp(-q / (2.0 * ell * ell))
            mse, mlp = _loo_errors(k, yv, lam)
            table.append(
                {
                    "weights_index": wi,
                    "lengthscale": ell,
                    "loocv_mse": mse,
                    "loocv_mean_logpdf": mlp,
                }
            )
            if best is None or mse < best[0]:
                best = (mse, ell, wi, mlp)
    assert best is not None  # 网格非空已守卫
    w_best = cand_weights[best[2]]
    return {
        "lengthscale": best[1],
        "weights": None if w_best is None else w_best.copy(),
        "loocv_mse": best[0],
        "loocv_mean_logpdf": best[3],
        "nugget": lam,
        "n_candidates": len(table),
        "table": tuple(table),
    }


def regression_predict(
    A: np.ndarray,
    y: np.ndarray,
    A_test: np.ndarray,
    *,
    lengthscale: float,
    weights: np.ndarray | None = None,
    sigma_f: float = 1.0,
    relative_nugget: float = RELATIVE_NUGGET,
) -> dict[str, object]:
    """广义距离核 GP 后验预测：{mean, std}（K+λI 解，λ=相对 nugget）。

    零均值 GP 后验：α=(K+λI)⁻¹y、mean=K*·α、var=k**−‖L⁻¹k*‖²
    （L=chol(K+λI)），var 负值钳 0、std 带 _SIGMA_FLOOR 地板（df6⑨）。
    核对角恒 σ_f²（q(x,x)=0 逐位精确），k**=σ_f² 常数。

    Args:
        A: (n, ...) 训练样本堆叠；y: (n,) 训练目标。
        A_test: (m, ...) 测试样本堆叠（单样本形同 A）。
        lengthscale: 正标量 ℓ（fit_weights_loocv 产出）。
        weights: 单样本形权重（None=单位权重）。
        sigma_f: 正标量信号标准差。
        relative_nugget: 相对 nugget 系数（≥0）。

    Returns:
        dict：mean (m,)、std (m,)、nugget（实际 λ）。

    Raises:
        ValueError: A/y 行数不一致、形状/值域守卫（同
            generalized_distance）、lengthscale/sigma_f 非正。
    """
    yv = _finite_float_array(y, "y").ravel()
    n = yv.size
    af, bf, wf = _flatten_pairs(A, A_test, weights)
    if af.shape[0] != n:
        raise ValueError(f"A/y 行数不一致: {af.shape[0]} vs {n}")
    ell = _positive_scalar(lengthscale, "lengthscale")
    sf = _positive_scalar(sigma_f, "sigma_f")
    nugget_coef = float(_finite_float_array(relative_nugget, "relative_nugget"))
    if nugget_coef < 0.0:
        raise ValueError(f"relative_nugget 必须 >=0，收到 {nugget_coef}")
    lam = max(nugget_coef * float(np.var(yv)), _NUGGET_ABS_FLOOR)
    k_tr = (sf * sf) * np.exp(-_scaled_sqdist(af, af, wf) / (2.0 * ell * ell))
    k_te = (sf * sf) * np.exp(-_scaled_sqdist(bf, af, wf) / (2.0 * ell * ell))
    chol = _chol_factor(k_tr, lam)
    v = np.linalg.solve(chol, k_te.T)  # L⁻¹K*ᵀ, (n, m)
    alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, yv))  # (K+λI)⁻¹y
    mean = k_te @ alpha  # (m,)
    var = np.maximum((sf * sf) - (v * v).sum(axis=0), 0.0)  # (m,)
    std = np.maximum(np.sqrt(var), _SIGMA_FLOOR)
    return {"mean": mean, "std": std, "nugget": lam}
