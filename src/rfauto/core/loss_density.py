r"""损耗图提取确定性内核。

口径与公式来源（裁判 = 独立来源，不是本模块自己的推导，#118）
----------------------------------------------------------------
1) 时谐 **峰值相量** 口径的时均损耗密度 [W/m^3]::

       q = 0.5 * sigma * |E|^2 + 0.5 * omega * eps'' * |E|^2

   - 欧姆项 0.5*sigma*|E|^2：Jackson, Classical Electrodynamics, 3rd ed.,
     §6.9（时谐场时均焦耳损耗密度）；亦见 Pozar, Microwave Engineering,
     4th ed., §1.7（导体损耗）。
   - 介电项 0.5*omega*eps''*|E|^2：Pozar, Microwave Engineering, 4th ed.,
     §1.6（复介电常数 eps = eps' * (1 - j*tan_delta)，eps'' = eps' * tan_delta
     对应的时均损耗）。
   - E 为 **峰值相量**（复振幅，|E|_peak = sqrt(2) * E_rms）。若调用方持有
     RMS 相量，传 rms=True，时均因子 0.5 消失：
     q = sigma*|E|^2 + omega*eps''*|E|^2。
   - 本模块的 LossMaterial 用 **相对损耗因子** eps_r'' = eps_r * tan_delta
     （无量纲），内部乘真空介电常数 eps0；等价绝对口径
     eps''_abs = eps0 * eps_r * tan_delta [F/m]，即 q 第二项
     = 0.5 * omega * eps''_abs * |E|^2。
   - eps0 = 8.8541878128e-12 F/m、mu0 = 1.25663706212e-6 H/m
     （CODATA 2018，NIST）。

2) 趋肤深度 delta = sqrt(2 / (omega * mu * sigma))：Pozar 4th ed. §1.7.1。
   导体半空间内 |E(z)| = |E0| * exp(-z / delta)，于是
       integral_0^t 0.5 * sigma * |E|^2 * A dz
           = 0.25 * sigma * A * delta * |E0|^2 * (1 - exp(-2t / delta))
   —— 单测与 scripts/loss_conservation_check.py 用它作网格积分的解析裁判。

3) 功率守恒闭合（能量守恒）::

       integral(q dV)  ==  P_in * (1 - sum_j |S_ij|^2)

   右端 = 激励端口 i 入射、其余端口全匹配时的网络耗散功率。非无源 S 行
   （sum_j |S_ij|^2 > 1）时右端为负，判不闭合并置 non_passive（不吞掉）。

设计约束
--------
- core 叶子层：只 import numpy（不引 scipy/skrf）。规则网格重采样自实现
  线性/最近邻插值，避免给 core 增加任何新依赖。
- 全部纯函数 / 冻结数据类；非法输入显式 ValueError，不静默兜底。
- 判据阈值与口径集中在模块常量，供 service 层复用。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# 物理常量（CODATA 2018，NIST）与判据阈值
# ---------------------------------------------------------------------------

EPS0 = 8.8541878128e-12  # 真空介电常数 [F/m]
MU0 = 1.25663706212e-6  # 真空磁导率 [H/m]

# 验收口径：|integral(q dV) - P_sparams| / scale <= 3%
DEFAULT_CLOSURE_TOLERANCE = 0.03

RESAMPLE_LINEAR = "linear"
RESAMPLE_NEAREST = "nearest"
_RESAMPLE_METHODS = (RESAMPLE_LINEAR, RESAMPLE_NEAREST)

__all__ = [
    "DEFAULT_CLOSURE_TOLERANCE",
    "EPS0",
    "MU0",
    "RESAMPLE_LINEAR",
    "RESAMPLE_NEAREST",
    "LossMaterial",
    "PowerBalance",
    "integrate_loss_density",
    "loss_density",
    "power_conservation_check",
    "resample_regular",
    "resolve_omega",
    "uniform_cell_measure",
]


# ---------------------------------------------------------------------------
# 材料与频率
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LossMaterial:
    """各向同性损耗介质参数（标量口径）。

    Args:
        sigma: 电导率 sigma [S/m]，>= 0。
        eps_r: 相对介电常数实部 eps_r，> 0。
        tan_delta: 介质损耗角正切 tan_delta，>= 0。

    Raises:
        ValueError: 任一参数非有限或越界。
    """

    sigma: float = 0.0
    eps_r: float = 1.0
    tan_delta: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.sigma) or self.sigma < 0.0:
            raise ValueError(f"sigma 必须是 >=0 的有限实数，收到 {self.sigma!r}")
        if not math.isfinite(self.eps_r) or self.eps_r <= 0.0:
            raise ValueError(f"eps_r 必须是 >0 的有限实数，收到 {self.eps_r!r}")
        if not math.isfinite(self.tan_delta) or self.tan_delta < 0.0:
            raise ValueError(f"tan_delta 必须是 >=0 的有限实数，收到 {self.tan_delta!r}")

    @property
    def eps_double_prime_rel(self) -> float:
        """相对损耗因子 eps_r'' = eps_r * tan_delta（无量纲）。"""
        return self.eps_r * self.tan_delta

    @property
    def eps_double_prime_abs(self) -> float:
        """绝对介电常数虚部 eps'' = eps0 * eps_r * tan_delta [F/m]。"""
        return EPS0 * self.eps_double_prime_rel


def resolve_omega(
    omega: float | None = None,
    freq_hz: float | None = None,
) -> float | None:
    """解析角频率 omega [rad/s]；omega 与 freq_hz 二选一，都可为 None。

    Raises:
        ValueError: 同时给了两个；或给了负数/非有限值。
    """
    if omega is not None and freq_hz is not None:
        raise ValueError("omega 与 freq_hz 只能给一个")
    if freq_hz is not None:
        f = float(freq_hz)
        if not math.isfinite(f) or f < 0.0:
            raise ValueError(f"freq_hz 必须是 >=0 的有限实数，收到 {freq_hz!r}")
        return 2.0 * math.pi * f
    if omega is not None:
        w = float(omega)
        if not math.isfinite(w) or w < 0.0:
            raise ValueError(f"omega 必须是 >=0 的有限实数，收到 {omega!r}")
        return w
    return None


# ---------------------------------------------------------------------------
# 损耗密度与网格积分
# ---------------------------------------------------------------------------

def loss_density(
    e_field: np.ndarray | Sequence[complex],
    *,
    omega: float | None = None,
    freq_hz: float | None = None,
    material: LossMaterial | None = None,
    rms: bool = False,
) -> np.ndarray:
    """时均损耗密度 q [W/m^3]（口径与来源见模块 docstring）。

    公式（峰值相量，rms=False）::

        q = 0.5 * sigma * |E|^2 + 0.5 * omega * eps0 * eps_r * tan_delta * |E|^2

    Args:
        e_field: 复电场相量（任意形状，逐点）。
        omega: 角频率 [rad/s]；与 freq_hz 二选一。
        freq_hz: 频率 [Hz]；与 omega 二选一。
        material: 损耗介质参数；None 等价于无损材料（q 恒 0）。
        rms: E 是否为 RMS 相量（True 时不再乘 1/2）。

    Returns:
        与 e_field 同形状的 float64 ndarray。

    Raises:
        ValueError: 场为空或含 NaN/Inf；频率非法；tan_delta>0 却未给频率。
    """
    mat = LossMaterial() if material is None else material
    e = np.asarray(e_field)
    if e.size == 0:
        raise ValueError("e_field 不能为空")
    if np.iscomplexobj(e):
        ok = bool(np.all(np.isfinite(e.real)) and np.all(np.isfinite(e.imag)))
    else:
        ok = bool(np.all(np.isfinite(e)))
    if not ok:
        raise ValueError("e_field 含 NaN/Inf")

    w = resolve_omega(omega, freq_hz)
    if mat.eps_double_prime_rel > 0.0 and w is None:
        raise ValueError("tan_delta>0 时必须给 omega 或 freq_hz（介电损耗项无法确定）")

    factor = 1.0 if rms else 0.5
    mag2 = np.abs(e) ** 2
    q = factor * mat.sigma * mag2
    if w is not None:
        q = q + factor * w * mat.eps_double_prime_abs * mag2
    return np.asarray(q, dtype=float)


def uniform_cell_measure(spacing_m: float | Sequence[float]) -> float:
    """均匀规则网格的单元测度。

    传三个轴步长 -> 体测度 dV = dx*dy*dz；传两个面内步长 -> 面测度 dA。
    积分测度由调用方显式给出——内核不猜维度、不猜法向（避免把面网格
    当体网格积掉一个量级，见踩坑 #154 类"同名参数语义相反"）。

    Args:
        spacing_m: 标量或逐轴步长序列 [m]。

    Returns:
        单元测度 [m^3] 或 [m^2]。

    Raises:
        ValueError: 序列为空或含非正/非有限步长。
    """
    values = ([float(spacing_m)]  # type: ignore[arg-type]
              if np.isscalar(spacing_m) else [float(v) for v in spacing_m])
    if not values:
        raise ValueError("spacing_m 不能为空")
    for v in values:
        if not math.isfinite(v) or v <= 0.0:
            raise ValueError(f"网格步长必须是 >0 的有限实数，收到 {v!r}")
    return float(math.prod(values))


def integrate_loss_density(
    q: np.ndarray | Sequence[float],
    *,
    cell_measure: float | np.ndarray,
) -> float:
    """数值积分 integral(q dV) ~= sum_i q_i * dV_i（体/面网格通用）。

    Args:
        q: 损耗密度数组 [W/m^3]，实数、有限、非空。
        cell_measure: 标量（均匀网格单元测度）或与 q 同形状的逐点测度。

    Returns:
        积分值 [W]。

    Raises:
        ValueError: q 非实数/为空/含 NaN/Inf；测度非正/非有限；形状不匹配。
    """
    arr = np.asarray(q)
    if np.iscomplexobj(arr):
        raise ValueError("q 必须是实数数组（损耗密度是实数量）")
    arr = arr.astype(float)
    if arr.size == 0:
        raise ValueError("q 不能为空")
    if not np.all(np.isfinite(arr)):
        raise ValueError("q 含 NaN/Inf")

    cm = np.asarray(cell_measure, dtype=float)
    if cm.ndim == 0:
        value = float(cm)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"cell_measure 必须是 >0 的有限实数，收到 {cell_measure!r}")
        return value * float(np.sum(arr))
    if cm.shape != arr.shape:
        raise ValueError(f"cell_measure 形状 {cm.shape} 与 q 形状 {arr.shape} 不匹配")
    if not np.all(np.isfinite(cm)) or bool(np.any(cm <= 0.0)):
        raise ValueError("cell_measure 逐点测度必须是 >0 的有限实数")
    return float(np.sum(arr * cm))


# ---------------------------------------------------------------------------
# 功率守恒闭合
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PowerBalance:
    """integral(q dV) 与 P_in*(1 - sum|S_ij|^2) 的闭合结果。"""

    field_power_w: float
    sparams_power_w: float
    rel_error: float
    tolerance: float
    closed: bool
    non_passive: bool
    reflected_fraction: float

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好字典。"""
        return {
            "field_power_w": self.field_power_w,
            "sparams_power_w": self.sparams_power_w,
            "rel_error": self.rel_error,
            "tolerance": self.tolerance,
            "closed": self.closed,
            "non_passive": self.non_passive,
            "reflected_fraction": self.reflected_fraction,
        }


def power_conservation_check(
    q: np.ndarray | Sequence[float],
    *,
    cell_measure: float | np.ndarray,
    incident_power_w: float,
    s_row: Sequence[complex],
    tolerance: float = DEFAULT_CLOSURE_TOLERANCE,
) -> PowerBalance:
    """功率守恒闭合检查：integral(q dV) vs P_in * (1 - sum_j |S_ij|^2)。

    相对误差定义（对称、对零稳健）::

        scale = max(|field_power|, |sparams_power|)
        rel_error = |field_power - sparams_power| / scale   (scale > 0)

    非无源 S 行（sum|S|^2 > 1）使 sparams_power < 0，此时恒判不闭合并置
    non_passive=True（不静默返回 closed）。

    Args:
        q: 损耗密度数组 [W/m^3]。
        cell_measure: 标量或逐点积分测度。
        incident_power_w: 激励端口入射功率 P_in [W]，必须 > 0。
        s_row: 激励端口对应的一行 S 参数 S_ij（j 遍历全部端口），复数列。
        tolerance: 闭合容差（默认 0.03 = 3%），取值须在 (0, 1) 内。

    Returns:
        PowerBalance。

    Raises:
        ValueError: P_in <= 0；tolerance 越界；s_row 为空或含 NaN/Inf；
            或 q/测度非法（透传 integrate_loss_density 的校验）。
    """
    p_in = float(incident_power_w)
    if not math.isfinite(p_in) or p_in <= 0.0:
        raise ValueError(f"incident_power_w 必须是 >0 的有限实数，收到 {incident_power_w!r}")
    tol = float(tolerance)
    if not math.isfinite(tol) or not (0.0 < tol < 1.0):
        raise ValueError(f"tolerance 必须在 (0, 1) 内，收到 {tolerance!r}")

    s = np.asarray(s_row, dtype=complex)
    if s.size == 0:
        raise ValueError("s_row 不能为空")
    if not bool(np.all(np.isfinite(s.real)) and np.all(np.isfinite(s.imag))):
        raise ValueError("s_row 含 NaN/Inf")

    field_power = integrate_loss_density(q, cell_measure=cell_measure)
    reflected_fraction = float(np.sum(np.abs(s) ** 2))
    sparams_power = p_in * (1.0 - reflected_fraction)
    non_passive = reflected_fraction > 1.0 + 1e-9

    scale = max(abs(field_power), abs(sparams_power))
    rel_error = abs(field_power - sparams_power) / scale if scale > 0.0 else 0.0
    closed = bool(rel_error <= tol) and not non_passive

    return PowerBalance(
        field_power_w=field_power,
        sparams_power_w=sparams_power,
        rel_error=rel_error,
        tolerance=tol,
        closed=closed,
        non_passive=non_passive,
        reflected_fraction=reflected_fraction,
    )


# ---------------------------------------------------------------------------
# 规则网格重采样（node-centered，保持样本点覆盖的物理区间）
# ---------------------------------------------------------------------------

def _validate_and_resample(
    arr: np.ndarray,
    dst_shape: Sequence[int],
    method: str,
) -> np.ndarray:
    if method not in _RESAMPLE_METHODS:
        raise ValueError(f"method 必须是 {_RESAMPLE_METHODS} 之一，收到 {method!r}")
    if arr.size == 0:
        raise ValueError("field 不能为空")
    shape = tuple(int(v) for v in dst_shape)
    if len(shape) != arr.ndim:
        raise ValueError(f"dst_shape 维数 {len(shape)} 与 field 维数 {arr.ndim} 不匹配")
    if any(v < 1 for v in shape):
        raise ValueError(f"dst_shape 各轴必须 >=1，收到 {dst_shape!r}")

    out = arr
    for axis, m in enumerate(shape):
        out = _resample_axis(out, axis, m, method)
    return out


def _resample_axis(arr: np.ndarray, axis: int, m: int, method: str) -> np.ndarray:
    """沿单轴把 n 个样本点重采样为 m 个（linspace(0, n-1, m) 索引坐标）。"""
    n = int(arr.shape[axis])
    if m == n:
        return arr
    if n == 1:
        # 源轴退化为单点：该轴上物理区间为零，按常数延拓（线性/最近邻同解）
        return np.take(arr, np.zeros(m, dtype=int), axis=axis)

    u = np.linspace(0.0, float(n - 1), m)
    if method == RESAMPLE_NEAREST:
        idx = np.clip(np.rint(u).astype(int), 0, n - 1)
        return np.take(arr, idx, axis=axis)

    i0 = np.clip(np.floor(u).astype(int), 0, n - 2)
    w = u - i0
    lo = np.take(arr, i0, axis=axis)
    hi = np.take(arr, i0 + 1, axis=axis)
    wshape = [1] * arr.ndim
    wshape[axis] = m
    w = w.reshape(wshape)
    return lo * (1.0 - w) + hi * w


def resample_regular(
    field: np.ndarray | Sequence[complex],
    dst_shape: Sequence[int],
    *,
    method: str = RESAMPLE_LINEAR,
) -> np.ndarray:
    """规则网格重采样（线性/最近邻；node-centered，端点物理坐标重合）。

    源轴长 n、目标轴长 m 时，目标点索引坐标取 linspace(0, n-1, m)，
    即保持"样本点覆盖的物理区间"不变（不是保持单元数或单元中心）。
    线性插值对复场逐点作用于实/虚部（等价于复线性插值）。

    Args:
        field: 源场数组（实数或复数，任意维）。
        dst_shape: 目标各轴长度（维数须与 field 相同）。
        method: "linear"（默认）或 "nearest"。

    Returns:
        形状为 dst_shape 的 ndarray；实数输入返回 float64，复数输入返回
        complex128。

    Raises:
        ValueError: field 为空或含 NaN/Inf；method 未知；dst_shape 维数/
            长度非法。
    """
    arr = np.asarray(field)
    if np.iscomplexobj(arr):
        ok = bool(np.all(np.isfinite(arr.real)) and np.all(np.isfinite(arr.imag)))
    else:
        ok = bool(np.all(np.isfinite(arr)))
    if arr.size > 0 and not ok:
        raise ValueError("field 含 NaN/Inf")
    out = _validate_and_resample(arr, dst_shape, method)
    return np.asarray(out, dtype=complex) if np.iscomplexobj(arr) else np.asarray(out, dtype=float)
