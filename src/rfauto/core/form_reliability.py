"""FORM/SORM 一阶/二阶结构可靠度内核（XD-11，纯 numpy 零新依赖）。

背景：uq_service 良率面全走代理蒙特卡洛——稀有失效（Pf<1e-3）MC 样本
爆炸（PF=1e-4 精度需 ~1e8 样本）。FORM（First Order Reliability
Method）在已校准代理或闭式极限状态面上是几十次迭代的确定性数值：
HL-RF 迭代求设计点 → 可靠度指标 β → Pf=Φ(−β)；α 向量给出"哪个参数
把 Pf 拖下水"的失效方向灵敏度；SORM 在设计点补二阶曲率修正。

依据节（方法学出处）：
- Hasofer & Lind 1974（J. Eng. Mech. Div. ASCE 100(4):111-115）：
  β 的不变式几何定义 = 标准正态空间中原点到极限状态面 g=0 的最短距离
  （与失效面参数化无关的坐标不变量）。
- Rackwitz & Fiessler 1978（"Structural Safety and Reliability"，
  Pergamon：非正态变量的等价正态变换与 HL-RF 迭代格式）——本模块
  u_{k+1}=(∇Gᵀu_k−G_k)/||∇G_k||²·∇G_k 即 HL-RF 迭代（黑盒面梯度
  中心差分数值化）。
- Breitung 1984（Probabilistic Engineering Mechanics 1(3):SORM
  渐近式）：Pf_sorm ≈ Φ(−β)·∏_i(1+β·κ_i)^{−1/2}，κ_i=设计点处
  极限状态面主曲率（本模块切空间投影 Hessian/||∇G|| 数值求主曲率）。
- 方法学参照：OpenTURNS FORM 例题族（Hasofer-Lind-Rackwitz-
  Fiessler 迭代 / Breitung SORM 修正的标准实现口径）。

设计节（α 指数语义）：
- α = −∇_u G/||∇_u G|| = −(∂g/∂x)·σ / ||(∂g/∂x)·σ||——失效方向
  单位灵敏度向量。|α_i| 越大，第 i 个变量的不确定度把 Pf 拖得越狠
  （对线性面，σ_i 翻倍对 ln Pf 的敏感度恰 ∝ α_i²·β 尺度）；工程师
  读法=降哪个参数的公差/σ 最能压 Pf。
- 线性面解析关系：u*=β·α（设计点在 α 方向线上），本内核线性面
  HL-RF 一步到解、与闭式逐位一致（裁判锚 1）。
- κ 惯例：κ>0=面朝失效侧凸（FORM 切平面高估失效域偏保守，SORM 把
  Pf 往下修）；κ<0=朝失效侧凹（FORM 低估，SORM 往上修）。Breitung
  适用域=逐项 1+β·κ_i>0，域外显式 ValueError（不静默外推）。

诚实边界（预声明）：
- FORM 一阶对非线性面的偏差带：弱非线性面（设计点曲率半径≫β）
  相对偏差 ~10-30%（本测试 MC 对拍锚钉 30% 预声明带）；强非线性/
  双叶/沿轴细长失效域（如中心化乘积面 x1·x2<c）FORM 可差数倍到
  17×+（实测，见 test_form_reliability 选面注记）——此类面不走 FORM，
  回 uq_service 蒙特卡洛/重要性采样。
- SORM 曲率由二阶差分（h≈1e-4·max(1,|u|)）数值化：对 |g| 在差分
  步长上近退化的噪声面数值不稳——适用域守护 1+β·κ_i>0 之外，
  噪声面（如已校准 GP 代理的采样面）建议先平滑或在闭式面上用。
- 均值点已入失效域（g(μ)<0）时如实返回 β<0、Pf>0.5（不翻符号凑正）。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

__all__ = ["FormResult", "SormResult", "form_beta", "sorm_beta_correction"]

# 差分相对步长：一阶梯度 1e-6（黑盒面折衷），二阶 Hessian 1e-4
# （二阶差分 4 点同号相消比一阶狠一个量级，步长必须放大否则噪声淹没）
_GRAD_REL_STEP = 1e-6
_HESS_REL_STEP = 1e-4


# ─── 正态分布数值件（core 层不引 scipy：erfc 尾式 + Acklam 逆 CDF）───────

def _norm_sf(beta: float) -> float:
    """标准正态生存函数 Φ(−β)=½·erfc(β/√2)（尾域精度保到大 β）。"""
    return 0.5 * math.erfc(beta / math.sqrt(2.0))


# Acklam 逆正态 CDF 有理逼近常数（Peter Acklam 标准 4 区段实现，
# 相对精度 |ε|≈1.15e-9——常数逐位对 scipy.stats.norm.ppf 钉
# （test_form_reliability.test_norm_ppf_matches_scipy）。
_PPF_A = (-3.969683028665376e+01, 2.209460984245205e+02,
          -2.759285104469687e+02, 1.383577518672690e+02,
          -3.066479806614716e+01, 2.506628277459239e+00)
_PPF_B = (-5.447609879822406e+01, 1.615858368580409e+02,
          -1.556989798598866e+02, 6.680131188771972e+01,
          -1.328068155288572e+01)
_PPF_C = (-7.784894002430293e-03, -3.223964580411365e-01,
          -2.400758277161838e+00, -2.549732539343734e+00,
          4.374664141464968e+00, 2.938163982698783e+00)
_PPF_D = (7.784695709041462e-03, 3.224671290700398e-01,
          2.445134137142996e+00, 3.754408661907416e+00)
_PPF_P_LOW = 0.02425


def _norm_ppf(p: float) -> float:
    """标准正态逆 CDF（Acklam 有理逼近，|ε|≈1.15e-9 相对）。

    p≤0 → −inf、p≥1 → +inf（与 scipy.stats.norm.ppf 端点语义一致）。
    """
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"_norm_ppf 概率域外: {p!r}")
    if p == 0.0:
        return -math.inf
    if p == 1.0:
        return math.inf
    a, b, c, d = _PPF_A, _PPF_B, _PPF_C, _PPF_D
    if p < _PPF_P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q
                + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p <= 1.0 - _PPF_P_LOW:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r
                + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3])
                                * r + b[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q
             + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


# ─── 结果容器 ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FormResult:
    """FORM 一阶可靠度结果（β 口径：g(μ)>0 时 β>0，Pf=Φ(−β)）。

    converged=False 时 β/design_point 是如实占位（平坦面 β=±inf、
    迭代爆散 β=末点范数），消费方必须先查 converged 再采信数值（#122
    精神：不凑绿不冒充）。
    """

    beta: float
    design_point_x: np.ndarray  # 物理空间设计点 x*=μ+σ·u*
    design_point_u: np.ndarray  # 标准正态空间设计点 u*
    alpha: np.ndarray  # 失效方向单位灵敏度 α=−∇g·σ/||∇g·σ||
    pf_form: float  # Pf=Φ(−β)
    n_iter: int  # 实际 HL-RF 更新次数
    converged: bool  # ||Δu||<tol 收敛旗（平坦面/爆散/超限=False）


@dataclass(frozen=True)
class SormResult:
    """SORM 二阶修正结果（Breitung 1984 渐近式，适用域 1+β·κ_i>0）。"""

    beta: float  # FORM β（修正基准）
    beta_sorm: float  # −Φ⁻¹(Pf_sorm)
    pf_form: float
    pf_sorm: float  # Φ(−β)·∏(1+β·κ_i)^{−1/2}
    alpha: np.ndarray
    curvatures: tuple[float, ...]  # 主曲率 κ_i（切空间投影 Hessian/||∇G||）
    kappa_mean: float  # 平均主曲率（单修正简化口径 =∏ 替代 (1+β·κ̄)^{−(n−1)/2}）
    design_point_u: np.ndarray


# ─── 入参守卫与差分件 ───────────────────────────────────────────────────────

def _check_mean_stddev(mean: np.ndarray, stddev: np.ndarray) -> None:
    if mean.ndim != 1 or mean.size == 0:
        raise ValueError(f"mean 必须为一维非空向量, got shape={mean.shape}")
    if stddev.shape != mean.shape:
        raise ValueError(
            f"mean/stddev 形状不一致: {mean.shape} vs {stddev.shape}")
    if not np.all(np.isfinite(mean)):
        raise ValueError(f"mean 含非有限值: {mean.tolist()}")
    if not np.all(np.isfinite(stddev)):
        raise ValueError(f"stddev 含非有限值: {stddev.tolist()}")
    if np.any(stddev <= 0.0):
        raise ValueError(
            f"stddev 必须逐元素 >0, got {stddev.tolist()}")


def _wrap_limit_state(
    limit_state: Callable[[np.ndarray], float],
    mean: np.ndarray,
    stddev: np.ndarray,
) -> Callable[[np.ndarray], float]:
    """把物理空间黑盒 g(x) 变换到标准正态空间 G(u)=g(μ+σ·u)。

    callable 返回非有限值时如实抛错（不吞——数值在哪个点坏要可见）。
    """

    def g_u(u: np.ndarray) -> float:
        x = mean + stddev * u
        val = limit_state(x)
        val = float(val)
        if not math.isfinite(val):
            raise ValueError(
                f"极限状态面在 x={x.tolist()} 处返回非有限值 {val!r}"
                "（如实报错：黑盒面数值坏点不吞不替）")
        return val

    return g_u


def _grad_central(
    g_u: Callable[[np.ndarray], float], u: np.ndarray,
) -> np.ndarray:
    """标准正态空间中心差分梯度（h_i=1e-6·max(1,|u_i|)）。"""
    n = u.size
    grad = np.empty(n, dtype=float)
    for i in range(n):
        h = _GRAD_REL_STEP * max(1.0, abs(float(u[i])))
        u_p = u.copy()
        u_m = u.copy()
        u_p[i] += h
        u_m[i] -= h
        grad[i] = (g_u(u_p) - g_u(u_m)) / (2.0 * h)
    return grad


def _hessian_central(
    g_u: Callable[[np.ndarray], float], u: np.ndarray,
) -> np.ndarray:
    """二阶差分 Hessian（h_i=1e-4·max(1,|u_i|)；4 点交叉格式，对称回填）。"""
    n = u.size
    h = np.array([_HESS_REL_STEP * max(1.0, abs(float(u[i])))
                  for i in range(n)])
    hess = np.empty((n, n), dtype=float)
    for i in range(n):
        for j in range(i, n):
            u_pp = u.copy()
            u_pm = u.copy()
            u_mp = u.copy()
            u_mm = u.copy()
            u_pp[i] += h[i]
            u_pp[j] += h[j]
            u_pm[i] += h[i]
            u_pm[j] -= h[j]
            u_mp[i] -= h[i]
            u_mp[j] += h[j]
            u_mm[i] -= h[i]
            u_mm[j] -= h[j]
            val = (g_u(u_pp) - g_u(u_pm) - g_u(u_mp) + g_u(u_mm)) / (
                4.0 * h[i] * h[j])
            hess[i, j] = val
            hess[j, i] = val
    return hess


# ─── FORM 主入口 ───────────────────────────────────────────────────────────

def form_beta(
    limit_state: Callable[[np.ndarray], float],
    mean: np.typing.ArrayLike,
    stddev: np.typing.ArrayLike,
    *,
    max_iter: int = 100,
    tol: float = 1e-8,
    u0: np.typing.ArrayLike | None = None,
) -> FormResult:
    """FORM 一阶可靠度：HL-RF 迭代求设计点与 β（Pf=Φ(−β)）。

    入参：
    - limit_state：黑盒极限状态 callable g(x)（物理空间，x=np.ndarray
      长度 n；g>0 安全、g<0 失效——符号惯例与 Hasofer-Lind 教科书同）。
    - mean/stddev：物理空间均值 μ 与标准差 σ（逐元素有限、σ>0；
      变换 U=(x−μ)/σ 后在标准正态空间迭代）。
    - u0：可选迭代起点（缺省原点=均值点；中心化乘积面等在均值处
      梯度为零的面，可传非零起点）。

    迭代格式（Rackwitz-Fiessler 1978 HL-RF）：
        u_{k+1} = (∇Gᵀu_k − G_k)/||∇G_k||² · ∇G_k
    梯度中心差分（h=1e-6·max(1,|u_i)|），收敛判据 ||Δu||<tol。
    线性面一步到解且与闭式 β=(c−aᵀμ)/||a·σ|| 逐位一致（裁判锚 1）。

    病态面如实 converged=False 不抛（#122）：均值点梯度为零（平坦面/
    驻点）→ β=±inf（g(μ)≠0，恒安全/恒失效）；迭代爆散/超 max_iter →
    β=末点范数占位。callable 返回非有限值则显式 ValueError（不吞）。
    """
    mean_a = np.asarray(mean, dtype=float).ravel()
    stddev_a = np.asarray(stddev, dtype=float).ravel()
    _check_mean_stddev(mean_a, stddev_a)
    if max_iter < 1:
        raise ValueError(f"max_iter 必须 ≥1, got {max_iter!r}")
    if tol <= 0.0:
        raise ValueError(f"tol 必须 >0, got {tol!r}")
    g_u = _wrap_limit_state(limit_state, mean_a, stddev_a)
    n = mean_a.size

    if u0 is None:
        u = np.zeros(n, dtype=float)
    else:
        u = np.asarray(u0, dtype=float).ravel().copy()
        if u.shape != (n,):
            raise ValueError(f"u0 形状 {u.shape} 与变量数 {n} 不一致")

    # β 符号基准=均值点（原点）的 g 值，不是迭代起点（u0≠0 时两者不同）
    g_at_mean = g_u(np.zeros(n, dtype=float))
    n_iter = 0
    converged = False
    for _ in range(max_iter):
        grad = _grad_central(g_u, u)
        grad_norm = float(np.linalg.norm(grad))
        if grad_norm == 0.0:
            break  # 平坦面/驻点：HL-RF 无方向，如实不收敛
        g_val = g_u(u)
        u_next = (float(grad @ u) - g_val) / (grad_norm * grad_norm) * grad
        if not np.all(np.isfinite(u_next)):
            break  # 迭代爆散（范数溢出）：如实不收敛
        n_iter += 1
        step = float(np.linalg.norm(u_next - u))
        u = u_next
        if step < tol:
            converged = True
            break

    grad_f = _grad_central(g_u, u)
    grad_norm_f = float(np.linalg.norm(grad_f))
    if grad_norm_f == 0.0:
        # 平坦面（常数 g）：失效域为全空间或空集，β=±inf 如实
        if g_at_mean > 0.0:
            beta = math.inf
            pf = 0.0
        elif g_at_mean < 0.0:
            beta = -math.inf
            pf = 1.0
        else:
            beta = 0.0
            pf = 0.5
        return FormResult(
            beta=beta, design_point_x=mean_a + stddev_a * u,
            design_point_u=u, alpha=np.zeros(n), pf_form=pf,
            n_iter=n_iter, converged=False)
    alpha = -grad_f / grad_norm_f
    # β 符号惯例：g(μ)>0（均值安全）→ β>0；均值已失效 → β<0 如实
    u_norm = float(np.linalg.norm(u))
    sign = 1.0 if g_at_mean >= 0.0 else -1.0
    beta = sign * u_norm
    return FormResult(
        beta=beta, design_point_x=mean_a + stddev_a * u,
        design_point_u=u, alpha=alpha, pf_form=_norm_sf(beta),
        n_iter=n_iter, converged=converged)


# ─── SORM 修正 ─────────────────────────────────────────────────────────────

def sorm_beta_correction(
    limit_state: Callable[[np.ndarray], float],
    mean: np.typing.ArrayLike,
    stddev: np.typing.ArrayLike,
    design_point_u: np.typing.ArrayLike | None = None,
    *,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> SormResult:
    """SORM 二阶修正（Breitung 1984）：Pf_sorm=Φ(−β)·∏(1+β·κ_i)^{−1/2}。

    主曲率 κ_i：设计点处切空间正交基（SVD of α 的正交补）上投影
    Hessian 的本征值 / ||∇G||（惯例：κ>0=面朝失效侧凸 → SORM 把 Pf
    往下修、β_sorm≥β；κ<0=凹 → 往上修）。单变量 n=1 无切维 → 恒等
    β_sorm=β（空积=1）。

    design_point_u 缺省时内部跑 form_beta（未收敛显式拒绝——SORM 修正
    不在设计点外插）；显式传入时按给定点算曲率（球面等 βκ=−1 恰在
    Breitung 适用域边界，可直传设计点做域守卫负例）。

    适用域守护：任一 1+β·κ_i≤0 → ValueError（Breitung 渐近式失效，
    不静默外推）；κ̄ 单修正简化口径=kappa_mean 字段（(1+β·κ̄)^{−(n−1)/2}，
    主曲率接近时与全积一致，分散时如实看 curvatures）。
    二阶差分数值稳定性前提=面在 h≈1e-4 尺度上光滑（噪声代理面先平滑，
    见模块 docstring 诚实边界）。
    """
    mean_a = np.asarray(mean, dtype=float).ravel()
    stddev_a = np.asarray(stddev, dtype=float).ravel()
    _check_mean_stddev(mean_a, stddev_a)
    g_u = _wrap_limit_state(limit_state, mean_a, stddev_a)

    if design_point_u is None:
        fr = form_beta(limit_state, mean_a, stddev_a,
                       max_iter=max_iter, tol=tol)
        if not fr.converged:
            raise ValueError(
                "FORM 未收敛：SORM 修正拒绝在非设计点上外插"
                f"（converged=False, n_iter={fr.n_iter}）")
        u = fr.design_point_u
        beta = fr.beta
        pf_form = fr.pf_form
        alpha = fr.alpha
    else:
        u = np.asarray(design_point_u, dtype=float).ravel().copy()
        if u.shape != mean_a.shape:
            raise ValueError(
                f"design_point_u 形状 {u.shape} 与变量数 {mean_a.size} 不一致")
        beta = float(np.linalg.norm(u))
        # β 符号惯例与 FORM 同：均值点 g(μ)<0（已失效）→ β 取负
        if g_u(np.zeros_like(u)) < 0.0:
            beta = -beta
        pf_form = _norm_sf(beta)

    grad = _grad_central(g_u, u)
    grad_norm = float(np.linalg.norm(grad))
    if grad_norm == 0.0:
        raise ValueError("设计点梯度为零：无法定向失效方向（平坦面）")
    alpha = -grad / grad_norm

    # 切空间正交基：α 列向量 SVD 的 U 其余列张成 α 的正交补（n−1 维，
    # n=1 时空）。注意对 n×1 矩阵正交补在 U 不在 Vt（Vt 是 1×1）。
    u_svd, _, _ = np.linalg.svd(alpha.reshape(-1, 1))
    v_tan = u_svd[:, 1:]  # n×(n−1)
    n_tan = v_tan.shape[1]
    if n_tan == 0:
        curvatures: tuple[float, ...] = ()
        pf_sorm = pf_form
    else:
        hess = _hessian_central(g_u, u)
        proj = v_tan.T @ hess @ v_tan
        proj = 0.5 * (proj + proj.T)  # 数值对称化
        eig = np.linalg.eigvalsh(proj)
        curvatures = tuple(float(e) / grad_norm for e in eig)
        terms = [1.0 + beta * kap for kap in curvatures]
        bad = [t for t in terms if t <= 0.0]
        if bad:
            raise ValueError(
                f"Breitung 适用域外：1+β·κ_i 出现非正项 {bad!r}"
                f"（β={beta:.6g}, κ={list(curvatures)!r}）"
                "——球面等 βκ→−1 的强凹面渐近式失效，改走 MC")
        pf_sorm = pf_form * float(np.prod(terms)) ** (-0.5)
    kappa_mean = (float(sum(curvatures) / len(curvatures))
                  if curvatures else 0.0)
    return SormResult(
        beta=beta, beta_sorm=-_norm_ppf(pf_sorm), pf_form=pf_form,
        pf_sorm=pf_sorm, alpha=alpha, curvatures=curvatures,
        kappa_mean=kappa_mean, design_point_u=u)
