"""F-ME.28 器件族批 1：TMA 时间调制阵列（Time-Modulated Array）Fourier 方向图内核。

纯确定性后处理（零全波、零求解器、零 IO），round3 方案
研究扩充 round3 §二 F-F 表件 3
（"合成开关序列→基波/谐波方向图 vs 逐项 Fourier 系数"）。

口径与公式来源（铁律 5：法源写 docstring；裁判=独立路径，#118）：

- 四维（空间-时间）辐射体原始口径：H. E. Shanks & R. W. Bickmore,
  "Four-Dimensional Electromagnetic Radiators", Canadian Journal of Physics,
  vol. 37, 1959（任务书所称 "Shanks & Chambers 四角 TMA 论文族"按论文族
  落到此处 + Tennant-Chambers 2004；Shanks-Chamess 无联名 TMA 论文，
  如实登记）。
- Fourier 开关系数框架（超低副瓣 TMA）：W. H. Kummer, A. T. Villeneuve,
  T. S. Fong, F. G. Terrio, "Ultra-Low Sidelobes from Time-Modulated
  Arrays", IEEE Trans. Antennas Propag., vol. 11, 1963。
- 谐波方向图 S_m 与边带抑制表述：S. Yang, Y. B. Gan, A. Qing, "Sideband
  Suppression in Time-Modulated Linear Arrays by the Differential Evolution
  Algorithm", IEEE Antennas Wireless Propag. Lett., vol. 1, 2002。
- 和/差开关波束捷变（半周期时移 = 第一边带 180°）：A. Tennant & B. Chambers,
  "A Two-Element Time-Modulated Array with Adaptive Beam Forming",
  IEEE Trans. Antennas Propag., vol. 52, no. 1, 2004。

Fourier 展开推导（钉死一行）：第 n 元开关函数 U_n(t) 为周期 T_p 内以
win_center_n（归一化周期坐标）为中心、占空比 τ_n 的矩形窗，
基波系数 c_n0 = τ_n（与计时无关），m≠0 谐波系数

    c_nm = (1/T_p)∫ U_n(t) e^{−j2πm f_p t} dt
         = τ_n · sinc(m·τ_n) · e^{−j2πm·win_center_n}，  sinc(x)=sin(πx)/(πx)；

等价窗起点形式（win_center = τ/2，即窗起点 0）：
c_nm = (1 − e^{−j2πm·τ_n}) / (j·2πm)（两种代数路径互证，单测钉）。
实现钉**中心形式**（对 win_center 泛化自然）；m=0 取精确 τ_n（非 sinc 极限），
τ_n == 1.0 时全部 m≠0 系数**逐位归零**（sinc(整数) 的浮点噪声不接见）。

约定
====
- 单元沿阵轴位置 positions_lambda（波长单位，非负；等间距 n·d 退化为
  array_synthesis.array_factor 的 ψ_n = 2π·d·(u−u0)·n 口径）；方向图变量为
  方向余弦 u 网格（θ→u 映射复用 array_synthesis.direction_cosine，本模块
  不重复实现）。
- 谐波方向图（窄带/宽带显式参数）：S_m(u) = Σ_n w_n·c_nm·
  exp(j·2π·p_n·(u−u0)·(1+m·f_p/f0))——边带 m 的空间相位按其真实频率
  f0+m·f_p 计（k_m = k0·(1+m·f_p/f0)）；f_p/f0=0（缺省）即文献窄带惯例
  （全部阶按 f0 波数求值，Kummer 1963 口径），比值作为显式入参进
  dataclass 留痕。
- **复权包装决定**：array_synthesis.array_factor 的 _validate_weights 将
  权重收敛为 float（复输入拒绝），TMA 有效权重 w_n·c_nm 天然为复——
  故空间相位核以最小包装自实现（同式、支持任意 positions），与
  array_factor(normalize=False) 的恒等式由单测逐位钉死（τ=1 基波=纯静态阵）。
- 时间调制周期比 f_p/f0 只进空间相位（上式），开关系数 c_nm 只依赖
  (τ_n, win_center_n)（归一化周期坐标），与 f_p 绝对值无关。

诚实边界（预声明）
==================
- 本模块只做 Fourier 谱域方向图（开关序列→各阶方向图），不含互耦、
  单元方向图（方向图积由调用方与 pattern_multiplication 组合）、开关
  瞬态与实机时序量化；
- 基波（m=0）对计时（τ/win_center）**免疫**：S_0 只见 w_n·τ_n 实幅相——
  波束捷变（和/差口径）物理上体现在 |m|≥1 边带（半周期时移=第一边带
  180°，Tennant-Chambers 2004），beam_agility_compare 按此口径同时返回
  基波峰与边带峰供对比；
- Parseval 截断：Σ_{|m|≤M'}|c_nm|² → τ_n 的尾部以 1/M' 收敛
  （|c_m|² ≤ 1/(πm)² ⇒ 尾部 ≤ 2/(π²(M'+1))），rel 1e-6 需 M'≈4e6
  （τ=0.1 最坏），parseval_residual 按 chunk 调公开系数函数。

接口：全部函数纯 numpy 进出、零 IO；数值 0.0 合法（判缺失一律
is not None）；入参 bool 显式拒收（df7+⑯）；不进 calculators 注册表
（器件族域内约定，同 aging，消费者是 service 层）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "BeamAgilityResult",
    "TmaPatternResult",
    "beam_agility_compare",
    "harmonic_patterns",
    "parseval_residual",
    "pattern_peak",
    "sll_metrics",
    "switch_fourier_coefficients",
]

_TINY = 1e-300
"""非零守卫下限（仅防 0 除；物理零值走显式分支，不用 or 惯语，#364④）。"""


# ─── 输入校验 ──────────────────────────────────────────────────────────────────


def _reject_bool(value: Any, name: str) -> None:
    """bool 显式拒收（float(True)=1.0 静默污染统计，df7+⑯）。"""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 不接受 bool")


def _finite_float(value: Any, name: str) -> float:
    _reject_bool(value, name)
    out = float(value)
    if not np.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


def _validate_tau(tau) -> np.ndarray:
    """τ 校验（标量或 1-D 收敛为 1-D）：有限、逐元 ∈ [0,1]、bool 拒收
    （float(True)=1.0 静默污染统计，df7+⑯——须在 float 强转前检查）。"""
    raw = np.asarray(tau)
    if raw.dtype == np.bool_:
        raise ValueError("tau 不接受 bool（float(True)=1.0 静默污染统计，df7+⑯）")
    arr = raw.astype(float)
    if arr.ndim == 0:
        arr = arr.reshape(1)
    if arr.ndim != 1 or arr.size < 1:
        raise ValueError(f"tau 必须是一维非空数组，收到 shape={np.shape(tau)}")
    if not np.all(np.isfinite(arr)):
        raise ValueError("tau 含非有限值（nan/inf）")
    if np.any(arr < 0.0) or np.any(arr > 1.0):
        raise ValueError(f"tau 每元须落在 [0, 1]，收到 {arr}")
    return arr


def _validate_win_center(win_center, tau: np.ndarray) -> np.ndarray:
    """win_center 校验：None → 缺省 τ/2（窗起点 0 口径）；给定则 ∈ [0,1)。"""
    if win_center is None:
        return tau / 2.0
    raw = np.asarray(win_center)
    if raw.dtype == np.bool_:
        raise ValueError("win_center 不接受 bool（df7+⑯）")
    arr = raw.astype(float)
    if arr.ndim == 0:
        arr = np.full(tau.shape, float(arr))
    if arr.shape != tau.shape:
        raise ValueError(f"win_center 形状须与 tau 一致 {tau.shape}，收到 {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError("win_center 含非有限值（nan/inf）")
    if np.any(arr < 0.0) or np.any(arr >= 1.0):
        raise ValueError(f"win_center 每元须落在 [0, 1)，收到 {arr}")
    return arr


def _validate_positions(positions_lambda) -> np.ndarray:
    """单元位置（波长单位）校验：1-D 有限且非负（负位置显式拒绝）。"""
    arr = np.asarray(positions_lambda, dtype=float)
    if arr.ndim != 1 or arr.size < 1:
        raise ValueError(
            f"positions_lambda 必须是一维非空数组，收到 shape={np.shape(positions_lambda)}"
        )
    if not np.all(np.isfinite(arr)):
        raise ValueError("positions_lambda 含非有限值（nan/inf）")
    if np.any(arr < 0.0):
        raise ValueError(f"positions_lambda 须非负（沿阵轴坐标），收到 {arr}")
    return arr


def _validate_complex_weights(weights, n: int) -> np.ndarray:
    """复静态权重校验（一维、长度 n、有限；复数合法——与 array_factor 实权
    通道不同，见模块 docstring 复权包装决定）。"""
    arr = np.asarray(weights, dtype=complex)
    if arr.ndim != 1 or arr.size != n:
        raise ValueError(f"weights 须为一维且长度={n}，收到 shape={arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError("weights 含非有限值（nan/inf）")
    return arr


def _validate_orders(orders) -> np.ndarray:
    """谐波阶序列校验：1-D 整数（可含 0 与负）。"""
    arr = np.asarray(orders, dtype=int)
    if arr.ndim != 1 or arr.size < 1:
        raise ValueError(f"orders 必须是一维非空整数数组，收到 shape={np.shape(orders)}")
    return arr


def _validate_max_order(max_order) -> int:
    """谐波阶上限 M 校验：非负整数（M<0 显式 ValueError）。"""
    _reject_bool(max_order, "max_order")
    m = int(max_order)
    if m != max_order:
        raise ValueError(f"max_order 必须是整数，收到 {max_order!r}")
    if m < 0:
        raise ValueError(f"max_order 须 ≥ 0，收到 {m}")
    return m


# ─── 开关函数 Fourier 系数 ─────────────────────────────────────────────────────


def switch_fourier_coefficients(tau, orders, win_center=None) -> np.ndarray:
    """矩形开关函数的 Fourier 系数（中心形式，模块 docstring 推导）。

    参数
    ----
    tau : 标量或 1-D (N,)，占空比 ∈ [0,1]
    orders : 1-D 整数数组（谐波阶 m，可含 0 与负）
    win_center : None 或与 tau 同形，窗中心 ∈ [0,1)（归一化周期坐标）；
        None → τ/2（窗起点 0 口径）

    返回
    ----
    complex ndarray，shape = broadcast(tau, win_center).shape + (len(orders),)；
    标量 tau → shape (len(orders),)。

    精确分支：m=0 列 = τ（逐位，非 sinc 极限）；τ==1.0 行的全部 m≠0 列
    逐位 0（sinc(非零整数) 的 ~1e-16 浮点噪声不接见）；τ==0.0 全行逐位 0
    （公式自然给出 0·sinc = 0.0，无需特判）。
    """
    tau_arr = _validate_tau(tau)
    scalar_in = np.ndim(tau) == 0
    if scalar_in and np.ndim(win_center) > 1:
        raise ValueError("标量 tau 配 win_center 须为标量/None")
    if scalar_in and win_center is not None and np.ndim(win_center) == 0:
        win_center = np.asarray(win_center, dtype=float).reshape(1)
    wc_arr = _validate_win_center(win_center, tau_arr)
    m_arr = _validate_orders(orders)
    out = np.empty((*tau_arr.shape, m_arr.size), dtype=complex)
    mask_m0 = m_arr == 0
    if np.any(mask_m0):
        out[..., mask_m0] = tau_arr[..., np.newaxis]
    mask_nz = ~mask_m0
    if np.any(mask_nz):
        m_nz = m_arr[mask_nz].astype(float)
        mt = tau_arr[..., np.newaxis] * m_nz[np.newaxis, :]
        # np.sinc(x) = sin(πx)/(πx) 且 sinc(0)=1，与本模块 sinc 定义同口径
        out[..., mask_nz] = (
            tau_arr[..., np.newaxis]
            * np.sinc(mt)
            * np.exp(-2j * np.pi * wc_arr[..., np.newaxis] * m_nz)
        )
        rows_tau1 = np.nonzero(tau_arr == 1.0)[0]
        if rows_tau1.size:
            out[rows_tau1[..., np.newaxis], np.nonzero(mask_nz)[0]] = 0.0
    if scalar_in:
        return out[0]
    return out


# ─── 谐波方向图 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TmaPatternResult:
    """TMA 各谐波阶方向图求值结果（纯数值装配，无物理判据）。"""

    orders: tuple[int, ...]
    """谐波阶列表（|m| ≤ max_order，升序含 0）。"""

    patterns: np.ndarray
    """(len(orders), len(u)) 复方向图矩阵 S_m(u)。"""

    direction_cosines: np.ndarray
    """求值方向余弦网格（原样回传）。"""

    freq_ratio_fp_f0: float
    """调制频率比 f_p/f0（边带空间相位按 1+m·ratio 折算；0=窄带惯例）。"""

    scan_direction_cosine: float
    """静态扫描方向余弦 u0。"""

    def to_dict(self, *, include_patterns: bool = True) -> dict[str, Any]:
        """JSON 信封载荷（复数 → [re, im] 对；include_patterns=False 时
        只回形状，供大网格遥测）。"""

        def _cplx(a: np.ndarray) -> list[list[list[float]]] | None:
            if not include_patterns:
                return None
            return [[[float(v.real), float(v.imag)] for v in row] for row in self.patterns]

        return {
            "orders": [int(m) for m in self.orders],
            "patterns_re_im": _cplx(self.patterns),
            "patterns_shape": [int(self.patterns.shape[0]), int(self.patterns.shape[1])],
            "direction_cosines": [float(u) for u in self.direction_cosines]
            if include_patterns
            else None,
            "freq_ratio_fp_f0": float(self.freq_ratio_fp_f0),
            "scan_direction_cosine": float(self.scan_direction_cosine),
        }


def harmonic_patterns(
    direction_cosines,
    positions_lambda,
    static_weights,
    tau,
    *,
    win_center=None,
    max_order: int = 1,
    scan_direction_cosine: float = 0.0,
    freq_ratio_fp_f0: float = 0.0,
) -> TmaPatternResult:
    """TMA 各谐波阶方向图 S_m(u) = Σ_n w_n·c_nm·e^{j·2π·p_n·(u−u0)·(1+m·f_p/f0)}。

    参数见模块 docstring 约定；orders = |m| ≤ max_order（含 0）。
    返回 :class:`TmaPatternResult`（patterns[行=阶, 列=u]）。

    空间相位核为复权最小包装（array_factor 的 _validate_weights 只收实权，
    见模块 docstring）：等间距 positions_lambda = n·d 时与
    ``array_synthesis.array_factor(u, w·τ, spacing_lambda=d, u0,
    normalize=False)`` 同式——基波恒等式由单测钉死。
    """
    u = np.asarray(direction_cosines, dtype=float)
    if u.ndim != 1 or u.size < 1:
        raise ValueError(f"direction_cosines 必须是一维非空数组，收到 shape={u.shape}")
    if not np.all(np.isfinite(u)):
        raise ValueError("direction_cosines 含非有限值（nan/inf）")
    pos = _validate_positions(positions_lambda)
    w = _validate_complex_weights(static_weights, pos.size)
    tau_arr = _validate_tau(tau)
    if tau_arr.size != pos.size:
        raise ValueError(f"tau 长度须等于单元数 {pos.size}，收到 {tau_arr.size}")
    wc_arr = _validate_win_center(win_center, tau_arr)
    m_max = _validate_max_order(max_order)
    u0 = _finite_float(scan_direction_cosine, "scan_direction_cosine")
    if abs(u0) > 1.0 + 1e-9:
        raise ValueError(f"scan_direction_cosine 须落在 [-1, 1]，收到 {u0!r}")
    ratio = _finite_float(freq_ratio_fp_f0, "freq_ratio_fp_f0")

    orders = tuple(range(-m_max, m_max + 1))
    coeffs = switch_fourier_coefficients(tau_arr, np.asarray(orders), wc_arr)  # (N, M)
    effective = w[:, np.newaxis] * coeffs  # 复有效权重 w_n·c_nm，(N, M)
    base_phase = 2.0 * np.pi * (u - u0)  # (U,)
    patterns = np.empty((len(orders), u.size), dtype=complex)
    for i, order in enumerate(orders):
        k_factor = 1.0 + order * ratio  # 边带波数比 k_m/k0（窄带 ratio=0 → 1）
        phase = np.exp(1j * pos[:, np.newaxis] * base_phase[np.newaxis, :] * k_factor)
        patterns[i] = effective[:, i] @ phase
    return TmaPatternResult(
        orders=orders,
        patterns=patterns,
        direction_cosines=u,
        freq_ratio_fp_f0=ratio,
        scan_direction_cosine=u0,
    )


# ─── 指标面 ────────────────────────────────────────────────────────────────────


def pattern_peak(u_grid, pattern) -> tuple[float, float]:
    """复方向图在 u 网格上的峰值：返回 (u_peak, |S|_peak)（网格分辨率限定的
    argmax，不做插值——报告口径须随网格步长声明）。"""
    u = np.asarray(u_grid, dtype=float)
    mag = np.abs(np.asarray(pattern))
    if u.ndim != 1 or u.shape != mag.shape:
        raise ValueError(f"u_grid 与 pattern 形状须一致，收到 {u.shape} vs {mag.shape}")
    if u.size < 1:
        raise ValueError("空网格无峰可寻")
    idx = int(np.argmax(mag))
    return float(u[idx]), float(mag[idx])


def sll_metrics(patterns, orders, u_grid) -> dict[str, Any]:
    """边带电平面指标（数值只从给定方向图矩阵统计，不回读内核）。

    返回 dict：
    - ``fundamental_peak_abs``：基波（orders 含恰一个 0，否则 ValueError）峰 |S_0|；
    - ``max_sideband_peak_abs``：全部 |m|≥1 阶的最大峰（无边带阶 → inf）；
    - ``fundamental_to_max_sideband_db``：20·log10(基波峰/最大边带峰)
      （无边带 → inf；基波峰为 0 → ValueError）；
    - ``order_power_abs`` / ``order_power_fraction``：各阶 u 域功率
      ∫|S_m|²du（u_grid 梯形积分）及占比（占比和=1，能量守恒面）。
    """
    p = np.asarray(patterns)
    if p.ndim != 2:
        raise ValueError(f"patterns 必须是二维 (阶, u)，收到 shape={p.shape}")
    order_list = [int(m) for m in np.asarray(orders).ravel()]
    if len(order_list) != p.shape[0]:
        raise ValueError("orders 长度须与 patterns 行数一致")
    if order_list.count(0) != 1:
        raise ValueError(f"orders 须含恰一个基波阶 0，收到 {order_list}")
    u = np.asarray(u_grid, dtype=float)
    if u.ndim != 1 or u.size != p.shape[1]:
        raise ValueError(f"u_grid 须为一维且长度={p.shape[1]}，收到 shape={u.shape}")
    fund_idx = order_list.index(0)
    fund_peak = float(np.abs(p[fund_idx]).max())
    if fund_peak <= 0.0:
        raise ValueError("基波峰值为 0，边带比无定义")
    side_idx = [i for i, m in enumerate(order_list) if m != 0]
    if side_idx:
        side_peak = float(max(np.abs(p[i]).max() for i in side_idx))
        ratio_db = 20.0 * float(np.log10(fund_peak / side_peak)) if side_peak > 0.0 else float("inf")
    else:
        side_peak = float("inf")
        ratio_db = float("inf")
    power = {
        m: float(np.trapezoid(np.abs(p[i]) ** 2, u)) for i, m in enumerate(order_list)
    }
    total = sum(power.values())
    if total <= _TINY:
        raise ValueError("全部阶功率之和为 0，功率占比无定义")
    return {
        "fundamental_peak_abs": fund_peak,
        "max_sideband_peak_abs": side_peak,
        "fundamental_to_max_sideband_db": ratio_db,
        "order_power_abs": power,
        "order_power_fraction": {m: v / total for m, v in power.items()},
    }


def parseval_residual(tau, win_center=None, *, max_order: int, chunk_size: int = 1 << 19):
    """Parseval 恒等式残差：|Σ_{|m|≤M'}|c_nm|² − τ_n| / τ_n（逐元）。

    τ_n == 0 元恒返 0.0（系数全零，残差按绝对差定义自然为 0）。
    截断尾部 ≤ 2/(π²(M'+1))（|c_m|² ≤ 1/(πm)² 积分界，模块 docstring）：
    rel 1e-6 最坏 τ=0.1 需 M' ≥ ~4e6（预声明口径）。按 chunk 调公开系数
    函数 :func:`switch_fourier_coefficients`（测试吃真实内核路径）。
    """
    tau_arr = _validate_tau(tau)
    wc_arr = _validate_win_center(win_center, tau_arr)
    m_max = _validate_max_order(max_order)
    chunk = int(chunk_size)
    if chunk < 1:
        raise ValueError(f"chunk_size 须 ≥ 1，收到 {chunk_size!r}")
    # chunk 按单元数收敛：(N, chunk) 复系数块内存 ≈ N·chunk·16B
    chunk = max(1, chunk // max(1, tau_arr.size))
    partial = np.zeros(tau_arr.size, dtype=float)
    lo = -m_max
    while lo <= m_max:
        hi = min(lo + chunk - 1, m_max)
        m_chunk = np.arange(lo, hi + 1)
        coeffs = switch_fourier_coefficients(tau_arr, m_chunk, wc_arr)
        partial += np.sum(np.abs(coeffs) ** 2, axis=-1)
        lo = hi + 1
    residual = np.abs(partial - tau_arr)
    nz = tau_arr > 0.0
    out = np.zeros(tau_arr.size, dtype=float)
    out[nz] = residual[nz] / tau_arr[nz]
    return out


# ─── 波束捷变演示面（和/差口径，数组进出，不做优化）───────────────────────────


@dataclass(frozen=True)
class BeamAgilityResult:
    """两套开关序列（和/差口径）的基波峰与指定边带峰对比。

    口径（模块 docstring 诚实边界）：基波对计时免疫——两套的基波峰均钉在
    静态扫描向（offset≈0 即恒等式的数值体现）；差方向图出现在 ``order``
    边带（半周期时移 = 该边带 180° 相位翻转，Tennant-Chambers 2004）。
    """

    order: int
    fundamental_pattern_sum: np.ndarray
    fundamental_pattern_diff: np.ndarray
    fundamental_peak_u_sum: float
    fundamental_peak_u_diff: float
    fundamental_peak_offset_u: float
    sideband_pattern_sum: np.ndarray
    sideband_pattern_diff: np.ndarray
    sideband_peak_u_sum: float
    sideband_peak_u_diff: float
    sideband_broadside_abs_sum: float
    sideband_broadside_abs_diff: float
    direction_cosines: np.ndarray

    def to_dict(self) -> dict[str, Any]:
        """JSON 信封载荷（方向图只回形状与峰，不整矩阵搬运）。"""
        return {
            "order": int(self.order),
            "fundamental_peak_u_sum": self.fundamental_peak_u_sum,
            "fundamental_peak_u_diff": self.fundamental_peak_u_diff,
            "fundamental_peak_offset_u": self.fundamental_peak_offset_u,
            "sideband_peak_u_sum": self.sideband_peak_u_sum,
            "sideband_peak_u_diff": self.sideband_peak_u_diff,
            "sideband_broadside_abs_sum": self.sideband_broadside_abs_sum,
            "sideband_broadside_abs_diff": self.sideband_broadside_abs_diff,
            "patterns_shape": [int(self.fundamental_pattern_sum.shape[0])],
            "n_u": int(self.direction_cosines.size),
        }


def beam_agility_compare(
    direction_cosines,
    positions_lambda,
    static_weights,
    tau_sum,
    win_center_sum,
    tau_diff,
    win_center_diff,
    *,
    order: int = 1,
    scan_direction_cosine: float = 0.0,
    freq_ratio_fp_f0: float = 0.0,
) -> BeamAgilityResult:
    """两套开关序列（和口径 / 差口径）→ 基波峰角偏移对比 + 边带峰对比。

    数组进出、确定性，不做任何寻优。和/差口径：同一静态阵列，两套
    (tau, win_center) 开关序列；典型差口径 = 右半阵列 win_center 平移 0.5
    （半周期），在 ``order`` 边带生成 180° 相位翻转（差方向图），基波不动。
    差口径若以基波差异表达须复权符号翻转（静态权重 (−1)^n）——计时
    （τ/win_center）在 m=0 无符号自由度，如实登记为模块边界。
    """
    _reject_bool(order, "order")
    if int(order) != order or order == 0:
        raise ValueError(f"order 须为非零整数边带阶，收到 {order!r}")
    result_sum = harmonic_patterns(
        direction_cosines,
        positions_lambda,
        static_weights,
        tau_sum,
        win_center=win_center_sum,
        max_order=abs(int(order)),
        scan_direction_cosine=scan_direction_cosine,
        freq_ratio_fp_f0=freq_ratio_fp_f0,
    )
    result_diff = harmonic_patterns(
        direction_cosines,
        positions_lambda,
        static_weights,
        tau_diff,
        win_center=win_center_diff,
        max_order=abs(int(order)),
        scan_direction_cosine=scan_direction_cosine,
        freq_ratio_fp_f0=freq_ratio_fp_f0,
    )
    orders = result_sum.orders
    idx_fund = orders.index(0)
    idx_side = orders.index(int(order))
    u = result_sum.direction_cosines
    u0 = result_sum.scan_direction_cosine
    broad_idx = int(np.argmin(np.abs(u - u0)))
    u_f0, _ = pattern_peak(u, result_sum.patterns[idx_fund])
    u_f1, _ = pattern_peak(u, result_diff.patterns[idx_fund])
    u_s0, _ = pattern_peak(u, result_sum.patterns[idx_side])
    u_s1, _ = pattern_peak(u, result_diff.patterns[idx_side])
    return BeamAgilityResult(
        order=int(order),
        fundamental_pattern_sum=result_sum.patterns[idx_fund],
        fundamental_pattern_diff=result_diff.patterns[idx_fund],
        fundamental_peak_u_sum=u_f0,
        fundamental_peak_u_diff=u_f1,
        fundamental_peak_offset_u=abs(u_f1 - u_f0),
        sideband_pattern_sum=result_sum.patterns[idx_side],
        sideband_pattern_diff=result_diff.patterns[idx_side],
        sideband_peak_u_sum=u_s0,
        sideband_peak_u_diff=u_s1,
        sideband_broadside_abs_sum=float(np.abs(result_sum.patterns[idx_side][broad_idx])),
        sideband_broadside_abs_diff=float(np.abs(result_diff.patterns[idx_side][broad_idx])),
        direction_cosines=u,
    )
