"""变换域注册表与逐域 LOO-LML 选择器（DP-15 C1，plan_deepdive_specs §15.1）。

深谷判据背景（#370/#371 结论，数据工厂一期收官结论）：深谐振
谷族 S11 的 dB 表示在谷底把微小线性误差放大成几十 dB，GP 在 dB 目标上
"看着病"、线性 |Γ| 才是消费口径——本模块把"选哪种表示"从人工裁定变成
确定性统计量：逐域 leave-one-out 对数边缘似然（LOO-LML），argmax 者胜。

设计约束：
- 纯函数域内核：零 IO、零墙钟，core 层只依赖 numpy（GP 经 lazy import
  sklearn，core 是 .importlinter 分层的稳定叶子）；
- dB 域下限钳 −120 dB 防 −inf（钳在 forward 内，非后处理补丁）；
- 表示不可能的域如实从候选剔除（diff 缺频率轴 / re_im 缺复数相位），
  不报错、不静默选中（#316 方向：多报不放过）；
- 各域同一 GP 配置（kernel / n_restarts_optimizer / random_state 钉死
  同参）保证公平——只有目标表示不同；
- ΔLML < ε 平局按优先序 dB > gamma_linear > re_im > diff 取先，保向后
  兼容（现缺省 dB）；
- 显式统计量指标名（s11_db_min 等）不受自动选择覆盖——自动选择只作用
  于 cost/回归目标表示（见 is_explicit_statistic_name）。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

#: dB 表示下限（钳制防 −inf；|z| 低于 10^(−120/20) 一律记 −120 dB）
DB_FLOOR_DB = -120.0
#: 与 DB_FLOOR_DB 对应的线性幅值下限（diff 域零导数同用此地板防 log(0)）
DB_FLOOR_LINEAR = 10.0 ** (DB_FLOOR_DB / 20.0)
#: 平局优先序（保向后兼容：现缺省 dB）
DOMAIN_PRIORITY: tuple[str, ...] = ("dB", "gamma_linear", "re_im", "diff")
#: ΔLML 平局判定阈（nats）；m2 判据另用 ≥5 nats 的显著性门，与此无关
DEFAULT_TIE_EPSILON = 1.0
#: LOO 折内 GP 随机重启数（各域同参；与 CV_GP_RESTARTS 同量级控成本）
LOO_GP_RESTARTS = 1
#: 相对 nugget（×var(y)）：插值型 GP 的 LOO 后验 σ 会塌到机器零，交叉域
#: LML 在近精确插值点上爆 ±1e12——加数据尺度相对噪声地板（各域同参数
#: 过程，公平性不变）保证 σ 有界、LML 有限（数值稳定项，不改判别力）
RELATIVE_NUGGET = 1e-8
#: 折内 σ 绝对地板（相对 nugget 的最后兜底，防 var(y)=0 退化）
_SIGMA_FLOOR = 1e-12

__all__ = [
    "DB_FLOOR_DB",
    "DB_FLOOR_LINEAR",
    "DEFAULT_TIE_EPSILON",
    "DOMAIN_PRIORITY",
    "LOO_GP_RESTARTS",
    "MetricDomain",
    "available_domains",
    "forward_domain",
    "get_domain",
    "inverse_domain",
    "is_explicit_statistic_name",
    "loo_loglik",
    "loo_loglik_table",
    "register_domain",
    "select_metric_domain",
]


# --------------------------------------------------------------- registry


@dataclass(frozen=True)
class MetricDomain:
    """单个变换域：forward/inverse + 注册名 + 表示前提。

    forward/inverse 语义（值域诚实边界）：
    - dB / gamma_linear：作用在幅值 |z| 上，inverse 恢复幅值（相位不属
      于该域，不硬造）；
    - re_im：作用在复数上，inverse 精确恢复复数；
    - diff：forward = log|dΓ/df|（沿频率轴 np.gradient），inverse = exp
      回幅值导数模 + 累积梯形积分，恢复幅值形状且至多差一个加性常数
      （起点幅值不可知，近似逆，诚实标注）。
    """

    name: str
    forward: Callable[..., np.ndarray]
    inverse: Callable[..., np.ndarray]
    #: 需要频率轴（曲线 + freqs 齐备才能构造该域目标）
    requires_freq: bool = False
    #: 需要复数相位（仅幅值来源时该域表示不可能）
    requires_complex: bool = False
    description: str = ""


_REGISTRY: dict[str, MetricDomain] = {}


def register_domain(domain: MetricDomain) -> MetricDomain:
    """注册变换域（基类+注册表模式；重名覆盖按调用序后者胜）。"""
    _REGISTRY[domain.name] = domain
    return domain


def get_domain(name: str) -> MetricDomain:
    if name not in _REGISTRY:
        raise KeyError(f"未注册的变换域: {name}，可用: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


# ----------------------------------------------------- domain kernels（纯函数）


def _fwd_db(values: np.ndarray, freqs: np.ndarray | None = None) -> np.ndarray:
    """dB 域：y = max(20·log10|z|, −120)——下限钳制防 −inf。"""
    mag = np.abs(np.asarray(values))
    return np.maximum(20.0 * np.log10(np.maximum(mag, DB_FLOOR_LINEAR)),
                      DB_FLOOR_DB)


def _inv_db(y: np.ndarray, freqs: np.ndarray | None = None) -> np.ndarray:
    """dB → 线性幅值（钳制域内精确可逆）。"""
    return 10.0 ** (np.asarray(y, dtype=float) / 20.0)


def _fwd_linear(values: np.ndarray,
                freqs: np.ndarray | None = None) -> np.ndarray:
    """线性幅值域：y = |z|（#370/#371 消费口径）。"""
    return np.abs(np.asarray(values))


def _inv_linear(y: np.ndarray, freqs: np.ndarray | None = None) -> np.ndarray:
    """线性幅值 → 幅值（域内恒等）。"""
    return np.asarray(y, dtype=float)


def _fwd_re_im(values: np.ndarray,
               freqs: np.ndarray | None = None) -> np.ndarray:
    """re/im 域：y = (Re z, Im z)，末维展开双列。"""
    z = np.asarray(values)
    if not np.iscomplexobj(z):
        raise ValueError("re_im 域 forward 需要复数输入（幅值无相位）")
    return np.stack([z.real.astype(float), z.imag.astype(float)], axis=-1)


def _inv_re_im(y: np.ndarray,
               freqs: np.ndarray | None = None) -> np.ndarray:
    """(Re, Im) → 复数（精确逆）。"""
    a = np.asarray(y, dtype=float)
    return a[..., 0] + 1j * a[..., -1]


def _fwd_diff(values: np.ndarray, freqs: np.ndarray | None = None) -> np.ndarray:
    """diff 域：y = log|dΓ/df|（复数取复导数模，幅值取幅值导数模）。

    零导数/微小导数钳到 DB_FLOOR_LINEAR 地板防 log(0)（与 dB 域同一
    幅值地板，钳在 forward 内）。
    """
    if freqs is None:
        raise ValueError("diff 域 forward 需要频率轴 freqs")
    z = np.asarray(values)
    freqs = np.asarray(freqs, dtype=float)
    if z.ndim < 2 or z.shape[-1] != freqs.size:
        raise ValueError(
            f"diff 域需要曲线 (n, m) 且 m==len(freqs)：got {z.shape} vs {freqs.size}")
    if freqs.size < 2:
        raise ValueError("diff 域需要 ≥2 个频率点")
    deriv = np.gradient(z, freqs, axis=-1)
    return np.log(np.maximum(np.abs(deriv), DB_FLOOR_LINEAR))


def _inv_diff(y: np.ndarray, freqs: np.ndarray | None = None) -> np.ndarray:
    """log|dΓ/df| → |Γ|（近似逆，诚实边界：至多差一个加性常数）。

    exp 回幅值导数模 → 频率轴累积梯形积分；起点幅值不可知（forward 丢
    了 |Γ(f0)|），恢复的是"幅值形状"。对纯实指数族 Γ=A·e^{bf} 精确
    （至差分/梯形误差）：∫|dΓ/df| = A·e^{bf} − A，减 |Γ| 恰为常数 −A。
    """
    if freqs is None:
        raise ValueError("diff 域 inverse 需要频率轴 freqs")
    y = np.asarray(y, dtype=float)
    freqs = np.asarray(freqs, dtype=float)
    deriv_mag = np.exp(y)
    seg = 0.5 * (deriv_mag[..., 1:] + deriv_mag[..., :-1]) * np.diff(freqs)
    return np.concatenate(
        [np.zeros((*y.shape[:-1], 1)), np.cumsum(seg, axis=-1)], axis=-1)


register_domain(MetricDomain(
    "dB", _fwd_db, _inv_db, description="20·log10|z|，下限钳 −120dB"))
register_domain(MetricDomain(
    "gamma_linear", _fwd_linear, _inv_linear,
    description="线性幅值 |z|（深谷族消费口径，#370/#371）"))
register_domain(MetricDomain(
    "re_im", _fwd_re_im, _inv_re_im, requires_complex=True,
    description="(Re z, Im z) 双列，LOO-LML 两列求和"))
register_domain(MetricDomain(
    "diff", _fwd_diff, _inv_diff, requires_freq=True,
    description="log|dΓ/df| 沿频率轴导数（inverse=exp+累积积分恢复幅值形状至常数）"))


def forward_domain(name: str, values: np.ndarray,
                   freqs: np.ndarray | None = None) -> np.ndarray:
    """注册名分派的 forward（纯函数薄壳）。"""
    return get_domain(name).forward(values, freqs)


def inverse_domain(name: str, values: np.ndarray,
                   freqs: np.ndarray | None = None) -> np.ndarray:
    """注册名分派的 inverse（纯函数薄壳）。"""
    return get_domain(name).inverse(values, freqs)


# ------------------------------------------------------- candidate domains


def available_domains(
    values_shape: tuple[int, ...],
    freqs: np.ndarray | None,
    has_complex: bool,
) -> tuple[list[str], dict[str, str]]:
    """按优先序返回可用域候选 + 被剔除域及原因（如实剔除，不报错）。

    - diff：需要 (n, m) 曲线 + freqs（m==len(freqs)≥2）；一维标量目标
      或频率轴缺失 → 剔除；
    - re_im：需要复数相位；仅幅值来源 → 剔除（幅值 reconstruct 不出
      相位，不硬造）。
    """
    excluded: dict[str, str] = {}
    curve = len(values_shape) == 2
    freqs_ok = (curve and freqs is not None
                and np.asarray(freqs).size == values_shape[-1]
                and values_shape[-1] >= 2)
    if not freqs_ok:
        excluded["diff"] = (
            "频率轴缺失（需要 (n, m) 曲线与 m≥2 的 freqs），如实排除")
    if has_complex:
        excluded.pop("re_im", None)
    else:
        excluded["re_im"] = "仅幅值来源（无复数相位），如实排除"
    available = [d for d in DOMAIN_PRIORITY if d not in excluded]
    return available, excluded


def _to_magnitude(values: np.ndarray, values_domain: str) -> np.ndarray:
    """声明来源域 → 内部统一幅值表示（各候选域 forward 的公共输入）。"""
    v = np.asarray(values)
    if values_domain == "dB":
        if np.iscomplexobj(v):
            raise ValueError("values_domain='dB' 的 values 应为实 dB 值")
        return _inv_db(v)
    if values_domain in ("gamma_linear", "magnitude"):
        return np.abs(v)
    raise ValueError(
        f"未知来源域 {values_domain!r}（支持 'dB'/'gamma_linear'/'magnitude'）")


def _domain_targets(
    name: str,
    magnitude: np.ndarray,
    complex_values: np.ndarray | None,
    freqs: np.ndarray | None,
) -> np.ndarray:
    """域 → 回归目标表（末维为目标列；re_im 末维 2 列）。"""
    source = complex_values if (name == "re_im" and complex_values is not None) \
        else magnitude
    return forward_domain(name, source, freqs)


def _targets_to_columns(y: np.ndarray) -> np.ndarray:
    """目标表 → (n, k) 列矩阵（re_im 的末维 2 并进列维）。"""
    a = np.asarray(y, dtype=float)
    if a.ndim < 2:
        a = a[:, None]
    return a.reshape(a.shape[0], -1)


# ------------------------------------------------------------- LOO-LML


def _make_selection_gp(n_restarts: int, random_state: int,
                       alpha: float) -> Any:
    """构造选择器 GP（各域同参公平性锚点：只此一处构造，全部域共用配置）。

    alpha=相对 nugget（×var(y)，调用方算好传入）——插值型 GP 的 LOO
    后验 σ 在近精确插值点塌到机器零，高斯 logpdf 爆 ±1e12（实测）；
    nugget 给 σ 一个数据尺度相对地板（数值稳定项，各域同参数过程）。
    """
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel

    kernel = ConstantKernel(1.0) * RBF(length_scale=1.0)
    return GaussianProcessRegressor(
        kernel=kernel, n_restarts_optimizer=int(n_restarts),
        random_state=int(random_state), alpha=float(alpha))


def _gaussian_logpdf(y: float, mu: float, sigma: float) -> float:
    """单点高斯 logpdf（σ 已地板化）。"""
    return (-0.5 * ((y - mu) / sigma) ** 2
            - math.log(sigma) - 0.5 * math.log(2.0 * math.pi))


def loo_loglik(
    X: np.ndarray,
    y: np.ndarray,
    *,
    random_state: int = 0,
    n_restarts: int = LOO_GP_RESTARTS,
) -> float:
    """单列目标的逐折 LOO 高斯 logpdf 求和（DP-15 C1 选择器内核）。

    每折：GP fit n−1 点 → held-out (μ,σ) → 高斯 logpdf；确定性
    （random_state 钉死）。任一折拟合/预测失败抛出（选择器侧按域
    剔除并记录原因，不静默吞）。
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float).ravel()
    if X.shape[0] != y.size:
        raise ValueError(f"X/y 行数不一致: {X.shape[0]} vs {y.size}")
    alpha = max(RELATIVE_NUGGET * float(np.var(y)), 1e-10)
    total = 0.0
    for i in range(y.size):
        test = np.array([i])
        train = np.array([j for j in range(y.size) if j != i])
        gp = _make_selection_gp(n_restarts, random_state, alpha)
        gp.fit(X[train], y[train])
        mu, sigma = gp.predict(X[test], return_std=True)
        s = max(float(np.asarray(sigma).ravel()[0]), _SIGMA_FLOOR)
        total += _gaussian_logpdf(float(y[i]),
                                  float(np.asarray(mu).ravel()[0]), s)
    return total


def loo_loglik_table(
    X: np.ndarray,
    Y: np.ndarray,
    *,
    random_state: int = 0,
    n_restarts: int = LOO_GP_RESTARTS,
) -> float:
    """多列目标的逐折 LOO-LML（列间独立 GP，logpdf 全折全列求和）。

    曲线头（m 个频率列）与 re_im（2 列）同构处理——与 m2 链的逐频率
    独立头口径一致。
    """
    A = np.asarray(Y, dtype=float)
    if A.ndim == 1:
        return loo_loglik(X, A, random_state=random_state,
                          n_restarts=n_restarts)
    return float(sum(
        loo_loglik(X, A[:, j], random_state=random_state,
                   n_restarts=n_restarts)
        for j in range(A.shape[1])))


# ------------------------------------------------------------- selection


def is_explicit_statistic_name(metric_name: str | None) -> bool:
    """显式统计量指标名判定（交付 4 的豁免判据）。

    与 SpecEvaluator.metric_key_candidates 同口径：以 _min/_max 结尾的
    指标名（s11_db_min/s11_db_max 等，谷深/峰值显式语义）不受自动选择
    覆盖——自动选择只作用于 cost/回归目标的表示。
    """
    if not metric_name:
        return False
    return str(metric_name).endswith(("_min", "_max"))


def select_metric_domain(
    X: np.ndarray,
    values: np.ndarray,
    *,
    freqs: np.ndarray | None = None,
    complex_values: np.ndarray | None = None,
    values_domain: str = "dB",
    epsilon: float = DEFAULT_TIE_EPSILON,
    n_restarts: int = LOO_GP_RESTARTS,
    random_state: int = 0,
) -> dict[str, Any]:
    """逐域 LOO-LML 变换域自动选择（DP-15 C1 主入口）。

    Args:
        X: (n, p) 回归自变量（各域共用同参 GP）。
        values: 目标值——(n,) 标量或 (n, m) 曲线，量纲由 values_domain
            声明（'dB' / 'gamma_linear' / 'magnitude'）。
        freqs: (m,) 频率轴；缺失时 diff 域如实从候选剔除。
        complex_values: 与 values 同形的复数数组；缺失时 re_im 域剔除。
        values_domain: 声明来源表示域（缺省 dB=项目现口径）。
        epsilon: ΔLML 平局阈（nats）；<ε 按优先序 dB>gamma_linear>
            re_im>diff 取先（保向后兼容）。

    Returns:
        fit meta 契约 dict：selected / selected_lml / loo_loglik（逐域
        表，仅可用域）/ excluded（剔除域+原因）/ delta_lml_vs_db /
        tie_broken_by_priority / epsilon / n_samples / values_domain /
        gp（同参证明）。
    """
    X = np.asarray(X, dtype=float)
    values = np.asarray(values)
    n = int(X.shape[0])
    if values.shape[0] != n:
        raise ValueError(
            f"X 与 values 行数不一致: {n} vs {values.shape[0]}")
    if complex_values is not None:
        complex_values = np.asarray(complex_values)
        if complex_values.shape != values.shape:
            raise ValueError(
                f"complex_values 形状 {complex_values.shape} 与 values "
                f"{values.shape} 不一致")
    magnitude = _to_magnitude(values, values_domain)
    available, excluded = available_domains(values.shape, freqs,
                                            complex_values is not None)

    lmls: dict[str, float] = {}
    for name in available:
        try:
            targets = _domain_targets(name, magnitude, complex_values, freqs)
            cols = _targets_to_columns(targets)
            if not np.all(np.isfinite(cols)):
                excluded[name] = "目标含非有限值，如实排除"
                continue
            lmls[name] = loo_loglik_table(
                X, cols, random_state=random_state, n_restarts=n_restarts)
        except Exception as exc:  # 折拟合失败：该域剔除并记录原因，不静默
            excluded[name] = f"LOO 拟合失败: {exc}"

    if not lmls:
        raise ValueError(
            f"全部候选域被剔除或失败: {excluded}（无表示可评，不硬选）")

    best_lml = max(lmls.values())
    argmax_domain = max(
        (d for d in lmls), key=lambda d: (lmls[d], -DOMAIN_PRIORITY.index(d)))
    selected = next(
        (d for d in DOMAIN_PRIORITY
         if d in lmls and lmls[d] >= best_lml - float(epsilon)),
        argmax_domain)
    db_lml = lmls.get("dB")
    return {
        "selected": selected,
        "selected_lml": float(lmls[selected]),
        "loo_loglik": {d: float(v) for d, v in lmls.items()},
        "excluded": excluded,
        "delta_lml_vs_db": (float(lmls[selected] - db_lml)
                            if db_lml is not None else None),
        "tie_broken_by_priority": bool(selected != argmax_domain),
        "epsilon": float(epsilon),
        "n_samples": n,
        "values_domain": values_domain,
        "priority": list(DOMAIN_PRIORITY),
        "gp": {"n_restarts": int(n_restarts), "random_state": int(random_state)},
    }
