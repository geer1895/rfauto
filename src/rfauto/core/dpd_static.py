"""F-E.8 数字预失真（DPD）静态提取内核：记忆多项式 LS + Saleh 静态模型 + 间接学习综合。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立路径，不自证，#118）：

- 记忆多项式（memory polynomial, MP）：y(n) = Σ_{k=0}^{K-1} Σ_{m=0}^{M}
  a_{km}·x(n−m)·|x(n−m)|^k（复基带口径）。出处：J. Kim, K. Konstantinou,
  "Digital predistortion of wideband signals based on power amplifier model
  with memory", Electronics Letters 37(23):1417-1418, 2001（IEE）。
  **出处勘误登记（#122）**：任务书标注 "Kim & Konstantinou 2001 (IEEE TSP)"
  与原文不符——该文发表于 IEE Electronics Letters；IEEE TSP 的是其后继
  广义记忆多项式（GMP）论文（Morgan et al. 2006，本内核不实现 GMP）。
- 无记忆退化（M=0）：y = Σ_k a_k·x·|x|^k 幂级数（Saleh 保守幂级数口径）；
  GMP 交叉项（x(n−m)·|x(n−m')|^k, m≠m'）不做（预声明边界，Kim-Konstantinou
  原文 MP 同此口径）。
- Saleh 静态模型：A(r) = α_a·r/(1+β_a·r²)、Φ(r) = α_φ·r²/(1+β_φ·r²)。
  出处：A. A. M. Saleh, "Frequency-independent and frequency-dependent
  nonlinear models of TWT amplifiers", IEEE Trans. Communications
  COM-29(11):1715-1720, 1981。本模块不内嵌论文 TWT 具体参数值（#118：未
  逐位核对原文表格不虚构），四参数全部显式传参；AM/PM 量纲（线性幅度/
  弧度或 dB/度）由调用方约定，联合拟合对两通道**等权**（量纲悬殊时调用方
  应先归一化）。
- 预失真器综合（间接学习架构, ILA）：post-inverse 最小二乘——以 PA 输出
  y(n−m) 为回归输入、PA 输入 x(n) 为期望输出提取逆模型系数，该 post-inverse
  直接用作预失真器。出处：C. Eun, E. J. Powers, "A new Volterra predistorter
  based on the indirect learning architecture", IEEE Trans. Signal Processing
  45(1):223-227, 1997。
- ACPR/ACLR：**本内核不产数字**（F-E 表件 8 预声明"只做线性近似面标注"）。
  ACPR 精确预测需对激励做频谱再生成型（谐波平衡/包络仿真，本仓接
  circuit_hb Pin 扫描），线性一阶互调展开对 ACLR 量级误差可达数 dB，
  不属可信输出面（规则 7：数值只在确定性内核的可信面产出）——见
  :func:`acpr_linear_estimate` 占位与 disclaimer。

约定（钉死口径）：

- 系数矩阵 coeffs 形状 (K, M+1)，coeffs[k, m] 即 a_{km}；回归列序 = 行优先
  展平 col = k*(M+1) + m（文档化确定性排序）。
- 回归窗口：滞后 m>0 的样本 x(n−m)、n<M 不可得——丢弃前 M 个样本，仅用
  n ∈ [M, N) 的行（窗口约定，单测钉住"改 y[0:M] 不改系数"）。
- :func:`apply_memory_polynomial` 全长输出：负滞后（n−m<0）按 0 填充
  （zero-pad 约定）；与回归窗口一致（n>=M 行的滞后项全部落在真实数据上）。
- 条件数守卫：cond(Φ) 上限预声明 1e8（:data:`DEFAULT_COND_MAX`），超限
  显式 ValueError（病态回归系数不可信，不静默降级）。
- to_dict：复系数序列化为 {"re": float, "im": float} 对（钉死这一种口径，
  JSON 往返自洽）；ndarray 不进 to_dict 之外的字段。
- 纯函数零 IO（numpy/scipy.optimize）；数值 0.0 合法（判缺失一律
  ``is not None``、禁 ``or 缺省``，#364④）；bool 显式拒收（df7+⑯）。
  不进 calculators 注册表（F-E P1 域内约定，消费者是 service 层薄壳；
  HB 数据源接线在 service 层参数入口——本内核只吃数组，不跑 HB）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import curve_fit

#: cond(Φ) 预声明上限（任务书口径；超限 ValueError 不静默降级）
DEFAULT_COND_MAX = 1e8

#: ACPR 占位 disclaimer（F-E 表件 8 预声明边界，措辞钉死）
_ACPR_DISCLAIMER = (
    "ACPR/ACLR 精确预测需激励频谱再生的非线性仿真（谐波平衡/包络，本仓"
    "circuit_hb Pin 扫描链）；线性一阶互调展开对 ACLR 量级误差可达数 dB，"
    "本内核按预声明边界（F-E 表件 8：只做线性近似面标注）不产数字，"
    "占位返回 None。"
)


# ─── 入参收敛助手 ─────────────────────────────────────────────────────────────


def _int_order(value: Any, name: str, minimum: int) -> int:
    """阶数/深度收敛为 int：bool 显式拒收、非整数值显式拒收（df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    try:
        iv = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须为整数，实际 {value!r}") from None
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} 必须为整数，实际 {value!r}")
    if iv < minimum:
        raise ValueError(f"{name} 必须 >={minimum}，实际 {iv}")
    return iv


def _complex_vector(value: Any, name: str) -> np.ndarray:
    """复基带向量收敛：1-D、有限（NaN/Inf 拒收）、bool 拒收。"""
    raw = np.asarray(value)
    if raw.dtype == bool:
        raise ValueError(f"{name} 不接受布尔数组（df7+⑯）")
    try:
        arr = raw.astype(complex)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须可转换为复数数组: {exc}") from None
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须为 1-D 数组，实际 ndim={arr.ndim}")
    if arr.size and not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含 NaN/Inf（非有限样本）")
    return arr


def _real_vector(value: Any, name: str) -> np.ndarray:
    """实向量收敛：1-D、有限、bool/复数拒收（Saleh 特性为实函数——复入参
    应先由调用方取 |·|/相位）。"""
    raw = np.asarray(value)
    if raw.dtype == bool:
        raise ValueError(f"{name} 不接受布尔数组（df7+⑯）")
    if np.issubdtype(raw.dtype, np.complexfloating):
        raise ValueError(f"{name} 必须为实数组（复数入参请先取模/相位）")
    try:
        arr = raw.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须可转换为实数数组: {exc}") from None
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须为 1-D 数组，实际 ndim={arr.ndim}")
    if arr.size and not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含 NaN/Inf（非有限样本）")
    return arr


def _finite_param(value: Any, name: str) -> float:
    """标量参数收敛：bool 拒收 + 有限性。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须为数字，实际 {value!r}") from None
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


# ─── 1. 记忆多项式（Kim-Konstantinou 2001） ──────────────────────────────────


@dataclass
class MemoryPolyModel:
    """记忆多项式模型：coeffs[k, m] = a_{km}（复系数，形状 (K, M+1)）。

    n_samples：回归有效行数（N−M）；cond：回归矩阵 Φ 的条件数；
    rms_residual：拟合残差 RMS（复模方意义）；warnings：预声明降级/备注
    面（当前实现为空列表，留作 API 稳定面）。
    """

    k: int
    m: int
    coeffs: np.ndarray
    n_samples: int
    cond: float
    rms_residual: float
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON 信封：复系数 → {"re","im"} 对（钉死口径，往返自洽）。"""
        return {
            "k": int(self.k),
            "m": int(self.m),
            "n_samples": int(self.n_samples),
            "cond": float(self.cond),
            "rms_residual": float(self.rms_residual),
            "warnings": list(self.warnings),
            "coeffs": [
                [{"re": float(c.real), "im": float(c.imag)} for c in row]
                for row in self.coeffs
            ],
        }


def extract_memory_polynomial(
    x: Any,
    y: Any,
    k_order: int,
    m_depth: int,
    cond_max: float = DEFAULT_COND_MAX,
) -> MemoryPolyModel:
    """记忆多项式 LS 提取（Kim-Konstantinou 2001）：给定 (x, y) 回收 a_{km}。

    x/y：复基带样本（等长，numpy 可转换）；k_order=K（非线性阶数，>=1，
    幂次 |x|^k 取 k=0..K-1）；m_depth=M（记忆深度，>=0）；cond_max：条件数
    上限（缺省 1e8，超限 ValueError——病态回归系数不可信，不静默降级）。

    回归矩阵 Φ 行 n（n ∈ [M, N)，前 M 样本因滞后越界丢弃）：
    [x(n−m)·|x(n−m)|^k]_{k=0..K-1, m=0..M}，列序 col = k*(M+1)+m；
    正规方程 np.linalg.lstsq（复数，rcond=None）收口。

    样本数不足（N−M < K*(M+1)）、长度不等、非有限样本、K<1、M<0 均显式
    ValueError。
    """
    k = _int_order(k_order, "k_order", 1)
    m = _int_order(m_depth, "m_depth", 0)
    xv = _complex_vector(x, "x")
    yv = _complex_vector(y, "y")
    if xv.size != yv.size:
        raise ValueError(f"x/y 长度不等: {xv.size} vs {yv.size}")
    n_cols = k * (m + 1)
    n_rows = xv.size - m
    if n_rows < n_cols:
        raise ValueError(
            f"有效样本数 {n_rows}（N={xv.size}−M={m}）< 回归列数 {n_cols}"
            "（K×(M+1)），样本不足"
        )
    phi = np.empty((n_rows, n_cols), dtype=complex)
    for ki in range(k):
        for mi in range(m + 1):
            col = xv[m - mi : m - mi + n_rows]  # x(n−mi), n ∈ [M, N)
            phi[:, ki * (m + 1) + mi] = col * np.abs(col) ** ki
    cond = float(np.linalg.cond(phi))
    if not math.isfinite(cond) or cond > float(cond_max):
        raise ValueError(
            f"cond(Φ)={cond:.6e} 超过预声明上限 {float(cond_max):.6e}"
            "（病态回归：激励未充分覆盖模型流形，系数不可信）"
        )
    coef_flat, _, _, _ = np.linalg.lstsq(phi, yv[m:], rcond=None)
    coeffs = coef_flat.reshape(k, m + 1)
    resid = phi @ coef_flat - yv[m:]
    rms = float(np.sqrt(np.mean(np.abs(resid) ** 2)))
    return MemoryPolyModel(
        k=k, m=m, coeffs=coeffs, n_samples=int(n_rows), cond=cond,
        rms_residual=rms,
    )


def apply_memory_polynomial(x: Any, coeffs: Any) -> np.ndarray:
    """记忆多项式正演 y(n) = Σ_{k,m} a_{km}·x(n−m)·|x(n−m)|^k（全长输出）。

    coeffs：(K, M+1) 复系数（1-D 视为 (K,1)）；负滞后（n−m<0）按 0 填充
    （zero-pad 约定，与 extract_memory_polynomial 的回归窗口一致）。
    """
    xv = _complex_vector(x, "x")
    c = np.asarray(coeffs, dtype=complex)
    if c.ndim == 1:
        c = c.reshape(-1, 1)
    if c.ndim != 2:
        raise ValueError(f"coeffs 必须为 1-D/2-D 数组，实际 ndim={c.ndim}")
    k_order, m_depth = c.shape[0], c.shape[1] - 1
    n = xv.size
    out = np.zeros(n, dtype=complex)
    for ki in range(k_order):
        for mi in range(m_depth + 1):
            lag = np.zeros(n, dtype=complex)
            if mi < n:
                lag[mi:] = xv[: n - mi]
            out += c[ki, mi] * (lag * np.abs(lag) ** ki)
    return out


def synthesize_dpd_postinverse(
    x_pa_in: Any,
    y_pa_out: Any,
    k_order: int,
    m_depth: int,
    cond_max: float = DEFAULT_COND_MAX,
) -> MemoryPolyModel:
    """间接学习架构（ILA）预失真器综合：post-inverse LS（判据主路径）。

    以 PA 输出 y 为回归输入、PA 输入 x 为期望输出提取逆模型系数，直接用
    作预失真器（Eun-Powers 1997 间接学习口径：post-inverse ≈ pre-inverse）。
    与 :func:`extract_memory_polynomial` 交换 (x, y) 完全同 computation
    （恒等式，单测钉住）；调用它只为语义命名。
    """
    return extract_memory_polynomial(
        y_pa_out, x_pa_in, k_order, m_depth, cond_max=cond_max
    )


# ─── 2. AM-AM 一阶线性度（级联判据度量） ─────────────────────────────────────


def amam_linear_fit(x: Any, z: Any) -> dict[str, Any]:
    """复增益一阶拟合 z ≈ g·x 与相对残差（级联线性化判据的度量面）。

    g = Σ conj(x_i)·z_i / Σ|x_i|²（最小二乘复增益）；residual_rms =
    ||z−g·x||₂ / ||z||₂（相对量，无量纲）。x 全零（增益无定义）或长度不等
    显式 ValueError；z 全零 → residual_rms=0.0（恒等退化，合法值 #364④）。
    """
    xv = _complex_vector(x, "x")
    zv = _complex_vector(z, "z")
    if xv.size != zv.size:
        raise ValueError(f"x/z 长度不等: {xv.size} vs {zv.size}")
    denom = float(np.sum(np.abs(xv) ** 2))
    if denom == 0.0:
        raise ValueError("x 全零：一阶拟合复增益无定义")
    gain = complex(np.vdot(xv, zv) / denom)
    power_z = float(np.mean(np.abs(zv) ** 2))
    if power_z == 0.0:
        return {"gain": gain, "residual_rms": 0.0}
    resid = float(np.sqrt(np.mean(np.abs(zv - gain * xv) ** 2) / power_z))
    return {"gain": gain, "residual_rms": resid}


def evaluate_dpd_cascade(
    x: Any, pa_coeffs: Any, dpd: MemoryPolyModel | np.ndarray
) -> dict[str, Any]:
    """DPD·PA 级联线性化评估：无 DPD vs 有 DPD 的 AM-AM 一阶残差对照。

    x：级联输入（复基带）；pa_coeffs：PA 幂级数/记忆多项式系数
    （MemoryPolyModel 或 (K, M+1) 数组）；dpd：预失真器（同两种形态）。
    返回 {"gain_pre","gain_post"（复增益）, "residual_pre","residual_post"
    （相对残差）, "improvement_factor"（residual_pre/residual_post，
    post 残差恰为 0 时为 math.inf）}。预声明判据面：有效 DPD 应给出
    improvement >= 10（量级判据，精确值依 PA/激励实测报告）。
    """
    xv = _complex_vector(x, "x")
    pa = pa_coeffs.coeffs if isinstance(pa_coeffs, MemoryPolyModel) else pa_coeffs
    dpd_c = dpd.coeffs if isinstance(dpd, MemoryPolyModel) else dpd
    u = apply_memory_polynomial(xv, dpd_c)
    z_pre = apply_memory_polynomial(xv, pa)
    z_post = apply_memory_polynomial(u, pa)
    pre = amam_linear_fit(xv, z_pre)
    post = amam_linear_fit(xv, z_post)
    improvement = (
        math.inf
        if post["residual_rms"] == 0.0
        else pre["residual_rms"] / post["residual_rms"]
    )
    return {
        "gain_pre": pre["gain"],
        "gain_post": post["gain"],
        "residual_pre": pre["residual_rms"],
        "residual_post": post["residual_rms"],
        "improvement_factor": float(improvement),
    }


# ─── 3. Saleh 静态模型（Saleh 1981） ─────────────────────────────────────────


def saleh_am_am(r: Any, alpha_a: float, beta_a: float) -> np.ndarray:
    """Saleh AM/AM 特性 A(r) = α_a·r/(1+β_a·r²)（r>=0 实向量）。"""
    rv = _real_vector(r, "r")
    aa = _finite_param(alpha_a, "alpha_a")
    ba = _finite_param(beta_a, "beta_a")
    return aa * rv / (1.0 + ba * rv**2)


def saleh_am_pm(r: Any, alpha_phi: float, beta_phi: float) -> np.ndarray:
    """Saleh AM/PM 特性 Φ(r) = α_φ·r²/(1+β_φ·r²)（r>=0 实向量）。"""
    rv = _real_vector(r, "r")
    ap = _finite_param(alpha_phi, "alpha_phi")
    bp = _finite_param(beta_phi, "beta_phi")
    return ap * rv**2 / (1.0 + bp * rv**2)


@dataclass
class SalehStaticModel:
    """Saleh 1981 四参数静态模型 + 拟合诊断（rms 残差按各自通道口径）。"""

    alpha_a: float
    beta_a: float
    alpha_phi: float
    beta_phi: float
    n_points: int
    rms_am: float
    rms_pm: float
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alpha_a": float(self.alpha_a),
            "beta_a": float(self.beta_a),
            "alpha_phi": float(self.alpha_phi),
            "beta_phi": float(self.beta_phi),
            "n_points": int(self.n_points),
            "rms_am": float(self.rms_am),
            "rms_pm": float(self.rms_pm),
            "warnings": list(self.warnings),
        }


def _saleh_joint(
    r_flat: np.ndarray, aa: float, ba: float, ap: float, bp: float
) -> np.ndarray:
    n = r_flat.size // 2
    r = r_flat[:n]
    return np.concatenate([saleh_am_am(r, aa, ba), saleh_am_pm(r, ap, bp)])


def fit_saleh_static(
    r: Any,
    a_meas: Any,
    p_meas: Any,
    p0: tuple[float, float, float, float] | None = None,
) -> SalehStaticModel:
    """Saleh 四参数非线性最小二乘拟合（scipy.optimize.curve_fit / LM）。

    r：幅度栅格（实、>=0）；a_meas：AM/AM 实测（与 r 同长）；p_meas：
    AM/PM 实测。p0=(α_a, β_a, α_φ, β_φ) 可选初值——缺省确定性启发式
    （β=1 假设 r 已归一到 O(1)，α 取 2×参考值：Saleh 式在 r=1/√β 处取
    极值 α/(2√β)；r 量级悬殊时调用方应显式给 p0）。样本 <4 或 r 无变化
    量（四参数不可辨识）显式 ValueError；curve_fit 不收敛（RuntimeError）
    转译为 ValueError 带初值提示。

    迭代法回收阈值预声明：无噪声合成数据 rel<=1e-6（判据 #122 先行）；
    小噪声 1e-3 时偏差带由测试实测钉（量级 ~1e-3 相对偏差）。
    """
    rv = _real_vector(r, "r")
    av = _real_vector(a_meas, "a_meas")
    pv = _real_vector(p_meas, "p_meas")
    if rv.size != av.size or rv.size != pv.size:
        raise ValueError(
            f"r/a_meas/p_meas 长度不等: {rv.size} / {av.size} / {pv.size}"
        )
    if rv.size < 4:
        raise ValueError(f"样本数 {rv.size} < 4（Saleh 四参数不可辨识）")
    if rv.size and float(np.min(rv)) < 0.0:
        raise ValueError("r 必须为非负幅度")
    if float(np.max(rv)) - float(np.min(rv)) <= 0.0:
        raise ValueError("r 无变化量（常数栅格）：四参数不可辨识")
    if p0 is None:
        a_ref = float(av[int(np.argmax(np.abs(av)))])
        p_ref = float(pv[int(np.argmax(np.abs(pv)))])
        p0 = (
            2.0 * a_ref if a_ref != 0.0 else 1.0,
            1.0,
            2.0 * p_ref if p_ref != 0.0 else 1.0,
            1.0,
        )
    else:
        if len(p0) != 4:
            raise ValueError(f"p0 必须为 4 元组 (α_a,β_a,α_φ,β_φ)，实际 {p0!r}")
        p0 = tuple(_finite_param(v, f"p0[{i}]") for i, v in enumerate(p0))  # type: ignore[assignment]
    y_joint = np.concatenate([av, pv])
    try:
        popt, _ = curve_fit(_saleh_joint, np.concatenate([rv, rv]), y_joint, p0=p0)
    except RuntimeError as exc:
        raise ValueError(f"Saleh 拟合不收敛（可尝试显式 p0）: {exc}") from None
    aa, ba, ap, bp = (float(v) for v in popt)
    rms_am = float(np.sqrt(np.mean((saleh_am_am(rv, aa, ba) - av) ** 2)))
    rms_pm = float(np.sqrt(np.mean((saleh_am_pm(rv, ap, bp) - pv) ** 2)))
    return SalehStaticModel(
        alpha_a=aa, beta_a=ba, alpha_phi=ap, beta_phi=bp,
        n_points=int(rv.size), rms_am=rms_am, rms_pm=rms_pm,
    )


# ─── 4. ACPR 线性近似面（占位，不产数字——预声明边界） ────────────────────────


def acpr_linear_estimate(model: Any = None) -> dict[str, Any]:
    """ACPR 占位口径：如实返回 None + disclaimer（F-E 表件 8 预声明）。

    model：可选任意模型对象（仅回显类型名，供上游信封组装）。ACPR 精确
    预测需 HB/包络仿真的频谱再生数据（service 层接 circuit_hb Pin 扫描）；
    本函数是"线性近似面标注"的诚实占位，永不产数字（规则 7）。
    """
    return {
        "acpr_db": None,
        "available": False,
        "model_type": type(model).__name__ if model is not None else None,
        "disclaimer": _ACPR_DISCLAIMER,
    }
