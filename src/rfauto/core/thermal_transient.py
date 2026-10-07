r"""MP-1 瞬态热 RC 内核（round15 路七"多物理场耦合深化" MP-1 / P1）。

Foster/Cauer RC 网络互转 + Z_th(t) 阶跃响应 + 脉动损耗 → 结温瞬态
（为 aging 热循环计数提供 ΔT 包络输入）。判据参考：

  * JEDEC JESD51-14：瞬态双界面法测热阻/瞬态热阻抗（Z_th 曲线语义：
    单位阶跃耗散功率下的结温瞬态响应，单位 °C/W）；
  * NXP AN11261 / Infineon "Transient Thermal Measurements and Thermal
    Equivalent Circuit Models"（AN2015-09）：
    - Foster 网络：Z_th(t) = Σ_i R_i·(1 − e^{−t/τ_i})，(R_i, τ_i) 直接来自
      曲线拟合，支路无逐层物理含义（非物理但拟合友好）；
    - Cauer 网络：逐层物理 RC 梯形（结→各层→环境，每层一个热容一个热阻），
      驱动点阻抗逐层反推。两者驱动点阻抗严格相等（同一 Z_th），互转 =
      阻抗多项式连分式展开（Foster→Cauer）/ 部分分式展开（Cauer→Foster）。

约定
----
* 本模块 Cauer 拓扑（0 基编号，n = 级数）：
    节点 0 = 结；C[i]：节点 i → 环境（热容，J/K）；
    R[i]（i < n−1）：节点 i → 节点 i+1；R[n−1]：节点 n−1 → 环境。
  驱动点阻抗 Z(s) = 1/(C0·s + 1/(R0 + 1/(C1·s + 1/(R1 + …))))，
  Z(0) = ΣR（稳态=热阻链，与 thermal_from_average_power 的 θ_tot 同口径），
  Z(∞) = 0（结热容高频短路 → 阶跃响应 t=0⁺ 连续）。
* Foster 网络：n 条 (R_i, τ_i) 并联 RC 支路的串联和（Z_th 拟合 canonical 形态）。
* 功率语义与 high_power.thermal_from_average_power 一致：平均/阶跃耗散功率
  P（W），温升 ΔT = P·Z_th（°C），Tj = Ta + ΔT。
* 稳态能量守恒锚：Z_th(t→∞) = ΣR；脉冲链稳态时间平均 = D·P·ΣR（线性系统
  均值定理）。

设计约束：core 叶子层纯标准库（math/cmath，零 numpy、零 IO）；非法输入
显式 ValueError，不静默兜底；dict 输出 JSON 可序列化（频率域函数返回
complex 供数学域使用，不入 JSON）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

__all__ = [
    "cauer_step_response_zth",
    "cauer_to_foster",
    "cauer_zth_frequency",
    "convolve_power_response",
    "foster_to_cauer",
    "pulse_response",
    "pulse_train_waveform",
    "step_response_zth",
    "zth_frequency",
]


# ---------------------------------------------------------------------------
# 输入校验（house style：显式 ValueError，不静默兜底）
# ---------------------------------------------------------------------------

def _finite(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为有限数值") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数值")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _nonneg(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 ≥0")
    return out


def _foster_branches(r_th: Sequence[float], tau_s: Sequence[float]) -> list[tuple[float, float]]:
    r_list = [_positive(v, f"r_th[{i}]") for i, v in enumerate(r_th)]
    t_list = [_positive(v, f"tau_s[{i}]") for i, v in enumerate(tau_s)]
    if len(r_list) != len(t_list):
        raise ValueError("r_th 与 tau_s 长度必须一致")
    return list(zip(r_list, t_list, strict=True))


def _cauer_elements(r_th: Sequence[float], c_th: Sequence[float]) -> tuple[list[float], list[float]]:
    r_list = [_positive(v, f"r_th[{i}]") for i, v in enumerate(r_th)]
    c_list = [_positive(v, f"c_th[{i}]") for i, v in enumerate(c_th)]
    if len(r_list) != len(c_list):
        raise ValueError("Cauer 网络 r_th 与 c_th 长度必须一致")
    return r_list, c_list


def _is_seq(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


# ---------------------------------------------------------------------------
# 升幂系数多项式工具（list[float]，index = s 的幂次）
# ---------------------------------------------------------------------------

def _poly_mul(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        if x == 0.0:
            continue
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


def _poly_add(a: list[float], b: list[float]) -> list[float]:
    size = max(len(a), len(b))
    out = [0.0] * size
    for i, v in enumerate(a):
        out[i] += v
    for i, v in enumerate(b):
        out[i] += v
    return out


def _poly_sub(a: list[float], b: list[float]) -> list[float]:
    return _poly_add(a, [-v for v in b])


def _poly_scale(a: list[float], k: float) -> list[float]:
    return [v * k for v in a]


def _poly_eval(p: list[float], s: complex) -> complex:
    acc = 0.0 + 0.0j
    for coef in reversed(p):
        acc = acc * s + coef
    return acc


def _poly_deriv(p: list[float]) -> list[float]:
    return [i * p[i] for i in range(1, len(p))]


def _trim_lead(a: list[float], floor: float) -> list[float]:
    """去掉次数最高处低于相对门限的噪声系数（至少保留 1 个系数）。"""
    end = len(a)
    while end > 1 and abs(a[end - 1]) <= floor:
        end -= 1
    return a[:end]


# ---------------------------------------------------------------------------
# 1) Z_th(t) 阶跃响应（Foster 闭式）
# ---------------------------------------------------------------------------

def step_response_zth(
    t_s: float | Sequence[float],
    r_th: Sequence[float],
    tau_s: Sequence[float],
    *,
    power_w: float = 1.0,
) -> float | list[float]:
    """Foster 网络阶跃温升 ΔT(t) = P·Σ_i R_i·(1 − e^{−t/τ_i})（JESD51-14 Z_th 曲线）。

    Args:
        t_s: 时刻（s），标量或升序序列。
        r_th: Foster 热阻列表（°C/W，逐项 >0）。
        tau_s: Foster 时间常数列表（s，逐项 >0，与 r_th 等长）。
        power_w: 阶跃耗散功率（W，≥0；缺省 1 W → 返回即 Z_th(t)，°C/W）。

    Returns:
        标量输入 → float（°C）；序列输入 → list[float]（°C）。
        锚：ΔT(0)=0、ΔT(∞)=P·ΣR（能量守恒）。
    """
    branches = _foster_branches(r_th, tau_s)
    p = _nonneg(power_w, "power_w")

    def one(t: float) -> float:
        tv = _nonneg(t, "t_s")
        return p * sum(r * (1.0 - math.exp(-tv / tau)) for r, tau in branches)

    if _is_seq(t_s):
        return [one(t) for t in t_s]
    return one(t_s)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2) Foster ↔ Cauer 互转
# ---------------------------------------------------------------------------

def foster_to_cauer(r_th: Sequence[float], tau_s: Sequence[float]) -> dict[str, list[float]]:
    """Foster (R_i, τ_i) → Cauer 梯形 (R_k, C_k)：驱动点阻抗多项式连分式展开。

    Z(s) = N(s)/D(s)，D = Π(1+τ_i·s)（n 次），N = Σ R_i·Π_{j≠i}(1+τ_j·s)
    （n−1 次）。Cauer（并容首梯）连分式逐级提取 (C_k, R_k)：
        C_k = lead(D_k)/lead(N_k)；D' = D_k − C_k·s·N_k；
        R_k = lead(N_k)/lead(D')；N' = N_k − R_k·D'。
    n 级后残差 ≈ 0 且 Σ R_k = Σ R_i（DC 恒等）；超差显式抛错（非被动网络或
    数值病态，不静默截断）。

    Returns:
        {"r_th_c_per_w": [...], "c_th_j_per_k": [...]}（与本模块 Cauer 拓扑对应）。
    """
    branches = _foster_branches(r_th, tau_s)
    factors = [[1.0, tau] for _, tau in branches]
    m = len(factors)
    prefix = [[1.0]]
    for f in factors:
        prefix.append(_poly_mul(prefix[-1], f))
    d_poly = prefix[m]
    suffix = [[1.0]] * (m + 1)
    for i in range(m - 1, -1, -1):
        suffix[i] = _poly_mul(suffix[i + 1], factors[i])
    n_poly = [0.0]
    for i, (r, _tau) in enumerate(branches):
        n_poly = _poly_add(n_poly, _poly_scale(_poly_mul(prefix[i], suffix[i + 1]), r))
    n_coef_scale = max(abs(v) for v in n_poly)
    num, den = list(n_poly), list(d_poly)
    r_out: list[float] = []
    c_out: list[float] = []
    for _stage in range(len(branches)):
        lead_num = num[-1]
        lead_den = den[-1]
        if lead_num <= 0.0 or lead_den <= 0.0:
            raise ValueError("Foster→Cauer 连分式失败：中间多项式首系数非正（网络非被动）")
        c_k = lead_den / lead_num
        c_out.append(c_k)
        den = _poly_sub(den, _poly_scale([0.0, *num], c_k))
        den = _trim_lead(den, 1e-12 * abs(lead_num * c_k))
        if den[-1] <= 0.0:
            raise ValueError("Foster→Cauer 连分式失败：余式首系数非正")
        r_k = lead_num / den[-1]
        r_out.append(r_k)
        num = _poly_sub(num, _poly_scale(den, r_k))
        num = _trim_lead(num, 1e-12 * abs(den[-1] * r_k))
    residual = max((abs(v) for v in num), default=0.0)
    if residual > 1e-8 * n_coef_scale:
        raise ValueError(
            f"Foster→Cauer 连分式残差超差（{residual:.3e}）：τ 分布病态，"
            "请合并近重合 τ 后重试")
    r_sum_in = sum(r for r, _ in branches)
    if abs(sum(r_out) - r_sum_in) > 1e-9 * r_sum_in:
        raise ValueError("Foster→Cauer DC 恒等校验失败：Σ R_cauer ≠ Σ R_foster")
    return {
        "r_th_c_per_w": [round(v, 12) for v in r_out],
        "c_th_j_per_k": [round(v, 12) for v in c_out],
    }


def cauer_to_foster(r_th: Sequence[float], c_th: Sequence[float]) -> dict[str, list[float]]:
    """Cauer 梯形 → Foster (R_i, τ_i)：驱动点阻抗部分分式展开（Durand-Kerner 求极点）。

    梯形逐层反推得 Z(s) = N(s)/D(s)（deg N = n−1，deg D = n）；被动 RC 网络
    极点全为负实数 s_k = −1/τ_k，留数 A_k = N(s_k)/D′(s_k)，Foster 支路
    R_k = A_k·τ_k。守恒校验：Σ R_k = Z(0)（超差显式抛错）。

    Returns:
        {"r_th_c_per_w": [...], "tau_s": [...]}（按 τ 升序排列）。
    """
    r_list, c_list = _cauer_elements(r_th, c_th)
    # 逐层反推：Z_{n-1} = R/(1+RCs)；Z_i = a/(C_i·s·a + den)，a = R_i·den + num
    num = [r_list[-1]]
    den = [1.0, r_list[-1] * c_list[-1]]
    for i in range(len(r_list) - 2, -1, -1):
        a_poly = _poly_add(_poly_scale(den, r_list[i]), num)
        den = _poly_add(_poly_scale([0.0, *a_poly], c_list[i]), den)
        num = a_poly
    roots = _real_negative_roots(den)
    d_deriv = _poly_deriv(den)
    foster: list[tuple[float, float]] = []
    for s_k in roots:
        tau_k = -1.0 / s_k.real
        resid = _poly_eval(num, s_k) / _poly_eval(d_deriv, s_k)
        r_k = resid * tau_k
        if abs(r_k.imag) > 1e-6 * max(abs(r_k.real), 1e-30) or r_k.real <= 0.0:
            raise ValueError("Cauer→Foster 部分分式失败：留数非正实（网络非被动/病态）")
        foster.append((r_k.real, tau_k))
    z0 = _poly_eval(num, 0.0j).real / _poly_eval(den, 0.0j).real
    if abs(sum(r for r, _ in foster) - z0) > 1e-6 * z0:
        raise ValueError("Cauer→Foster 守恒校验失败：ΣR ≠ Z(0)")
    foster.sort(key=lambda item: item[1])
    return {
        "r_th_c_per_w": [round(r, 12) for r, _ in foster],
        "tau_s": [round(t, 12) for _, t in foster],
    }


def _real_negative_roots(den: list[float]) -> list[complex]:
    """Durand-Kerner 求实系数多项式全部根，校验全为负实数（被动 RC 极点）。"""
    lead = den[-1]
    p = [v / lead for v in den]
    degree = len(p) - 1
    if degree < 1:
        raise ValueError("Cauer→Foster 失败：特征多项式退化")
    cauchy = 1.0 + max(abs(v) for v in p[:-1])
    coef_scale = sum(abs(v) for v in p)
    root_radius = cauchy ** (1.0 / degree)
    seed_base = complex(0.4, 0.9)
    roots = [seed_base ** (k + 1) * root_radius for k in range(degree)]
    for _ in range(500):
        delta_max = 0.0
        new_roots: list[complex] = []
        for k, rk in enumerate(roots):
            prod = 1.0 + 0.0j
            for j, rj in enumerate(roots):
                if j != k:
                    prod *= rk - rj
            delta = _poly_eval(p, rk) / prod
            new_roots.append(rk - delta)
            delta_max = max(delta_max, abs(delta))
        roots = new_roots
        if delta_max <= 1e-14 * max(1.0, max(abs(rk) for rk in roots)):
            break
    for rk in roots:
        bound = 1e-9 * coef_scale * max(1.0, abs(rk)) ** degree
        if abs(_poly_eval(p, rk)) > bound:
            raise ValueError(f"Cauer→Foster 失败：Durand-Kerner 根残差超差（{rk}）")
        if rk.imag > 1e-6 * max(abs(rk.real), 1e-30) or rk.real >= 0.0:
            raise ValueError(
                f"Cauer→Foster 失败：极点非负实数（{rk}）——网络非被动 RC 梯形")
    return [complex(rk.real, 0.0) for rk in roots]


# ---------------------------------------------------------------------------
# 3) Cauer 梯形阶跃响应（RK4 数值积分路径——与 Foster 闭式互证）
# ---------------------------------------------------------------------------

def cauer_step_response_zth(
    t_s: float | Sequence[float],
    r_th: Sequence[float],
    c_th: Sequence[float],
    *,
    power_w: float = 1.0,
    max_substep_s: float | None = None,
) -> float | list[float]:
    """Cauer 梯形阶跃温升：节点 ODE 组 RK4 数值积分（独立于 Foster 闭式路径）。

    状态方程（P 阶跃注入节点 0，环境 = 地）：
        C0·dT0/dt = P − (T0−T1)/R0
        Ci·dTi/dt = (T_{i−1}−Ti)/R_{i−1} − (Ti−T_{i+1})/R_i（1≤i≤n−2）
        C_{n−1}·dT_{n−1}/dt = (T_{n−2}−T_{n−1})/R_{n−2} − T_{n−1}/R_{n−1}
    子步长缺省 = 0.025/d_max，d_max = max_i((g_{i−1}+g_i)/C_i)（Gershgorin：
    λ_max ≤ 2·d_max → h·λ_max ≤ 0.05，RK4 每步相对误差 O((hλ)⁵) 量级）。
    t_s 必须升序非负。
    """
    r_list, c_list = _cauer_elements(r_th, c_th)
    p = _nonneg(power_w, "power_w")
    n = len(r_list)
    g = [1.0 / r for r in r_list]
    d_max = 0.0
    for i in range(n):
        g_left = g[i - 1] if i > 0 else 0.0
        g_right = g[i] if i < n - 1 else 0.0
        d_max = max(d_max, (g_left + g_right) / c_list[i])
    h_ref = 0.025 / d_max
    if max_substep_s is not None:
        h_ref = min(h_ref, _positive(max_substep_s, "max_substep_s"))

    def deriv(state: list[float], power: float) -> list[float]:
        out = [0.0] * n
        for i in range(n):
            flow_out = (state[i] - (state[i + 1] if i + 1 < n else 0.0)) * g[i]
            flow_in = 0.0 if i == 0 else (state[i - 1] - state[i]) * g[i - 1]
            out[i] = ((power if i == 0 else 0.0) + flow_in - flow_out) / c_list[i]
        return out

    def rk4_advance(state: list[float], power: float, h: float) -> list[float]:
        k1 = deriv(state, power)
        k2 = deriv([s + 0.5 * h * v for s, v in zip(state, k1, strict=True)], power)
        k3 = deriv([s + 0.5 * h * v for s, v in zip(state, k2, strict=True)], power)
        k4 = deriv([s + h * v for s, v in zip(state, k3, strict=True)], power)
        return [s + (h / 6.0) * (a + 2.0 * b + 2.0 * c + d)
                for s, a, b, c, d in zip(state, k1, k2, k3, k4, strict=True)]

    state = [0.0] * n
    t_now = 0.0
    scalar = not _is_seq(t_s)
    times = [_nonneg(t_s, "t_s")] if scalar else [_nonneg(t, "t_s") for t in t_s]
    results: list[float] = []
    for t_target in times:
        if t_target < t_now:
            raise ValueError("t_s 必须升序非负")
        span = t_target - t_now
        if span > 0.0:
            steps = max(1, math.ceil(span / h_ref))
            if steps > 4_000_000:
                raise ValueError(
                    f"RK4 步数超守卫（{steps}）：t 跨度相对最快时间常数过大，"
                    "请放大采样间隔或显式传 max_substep_s")
            h = span / steps
            for _ in range(steps):
                state = rk4_advance(state, p, h)
            t_now = t_target
        results.append(state[0])
    return results[0] if scalar else results


# ---------------------------------------------------------------------------
# 4) Z_th(jω) 频域逐点（验收口径：Foster ↔ Cauer 逐点对拍）
# ---------------------------------------------------------------------------

def zth_frequency(f_hz: float | Sequence[float], r_th: Sequence[float],
                  tau_s: Sequence[float]) -> complex | list[complex]:
    """Foster 网络 Z_th(jω) = Σ R_i/(1 + jωτ_i)（°C/W，单位功率频域热阻抗）。"""
    branches = _foster_branches(r_th, tau_s)

    def one(f: float) -> complex:
        fv = _positive(f, "f_hz")
        omega = 2.0 * math.pi * fv
        return complex(sum(r / (1.0 + 1j * omega * tau) for r, tau in branches))

    if _is_seq(f_hz):
        return [one(f) for f in f_hz]
    return one(f_hz)  # type: ignore[arg-type]


def cauer_zth_frequency(f_hz: float | Sequence[float], r_th: Sequence[float],
                        c_th: Sequence[float]) -> complex | list[complex]:
    """Cauer 梯形 Z_th(jω)：逐层复数反推（精确，无多项式展开误差）。"""
    r_list, c_list = _cauer_elements(r_th, c_th)

    def one(f: float) -> complex:
        fv = _positive(f, "f_hz")
        omega = 2.0j * math.pi * fv
        z_next = 1.0 / (c_list[-1] * omega + 1.0 / r_list[-1])
        for i in range(len(r_list) - 2, -1, -1):
            z_next = 1.0 / (c_list[i] * omega + 1.0 / (r_list[i] + z_next))
        return z_next

    if _is_seq(f_hz):
        return [one(f) for f in f_hz]
    return one(f_hz)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5) 脉动损耗 → 结温瞬态（稳态纹波 + 暂态波形 + 任意 ZOH 功率序列卷积）
# ---------------------------------------------------------------------------

def pulse_response(
    power_w: float,
    t_on_s: float,
    t_off_s: float,
    r_th: Sequence[float],
    tau_s: Sequence[float],
    *,
    ambient_c: float | None = None,
) -> dict[str, Any]:
    """周期脉冲功率链（导通 t_on / 关断 t_off）稳态结温包络（逐支路精确闭式）。

    单支路稳态：ΔT_peak,i = P·R_i·(1−a_i)/(1−a_i·b_i)、ΔT_min,i = ΔT_peak,i·b_i，
    其中 a_i = e^{−t_on/τ_i}、b_i = e^{−t_off/τ_i}；Foster 和网络逐支路线性
    叠加。守恒锚：时间平均 ΔT_mean = D·P·ΣR（D = t_on/(t_on+t_off)，线性系统
    均值定理）。t_off = 0 退化为连续功率稳态 ΔT = P·ΣR。

    Returns:
        dict（JSON 可序列化）：delta_t_peak_c / delta_t_min_c / delta_t_mean_c /
        ripple_c / duty / period_s / theta_total_c_per_w / mean_power_w；
        ambient_c 给定时附 junction_peak_c / junction_min_c / junction_mean_c。
    """
    branches = _foster_branches(r_th, tau_s)
    p = _nonneg(power_w, "power_w")
    t_on = _positive(t_on_s, "t_on_s")
    t_off = _nonneg(t_off_s, "t_off_s")
    period = t_on + t_off
    duty = t_on / period
    theta_total = sum(r for r, _ in branches)
    if t_off == 0.0:
        out = {
            "delta_t_peak_c": round(p * theta_total, 12),
            "delta_t_min_c": round(p * theta_total, 12),
            "delta_t_mean_c": round(p * theta_total, 12),
            "ripple_c": 0.0,
            "duty": round(duty, 12),
            "period_s": round(period, 12),
            "theta_total_c_per_w": round(theta_total, 12),
            "mean_power_w": round(p, 12),
        }
    else:
        peak = 0.0
        trough = 0.0
        mean = 0.0
        for r, tau in branches:
            a = math.exp(-t_on / tau)
            b = math.exp(-t_off / tau)
            dt_peak_i = p * r * (1.0 - a) / (1.0 - a * b)
            dt_min_i = dt_peak_i * b
            dt_ss_i = p * r
            # 一个稳态周期内两段指数的积分 → 时间平均
            integral_on = dt_ss_i * t_on + (dt_min_i - dt_ss_i) * tau * (1.0 - a)
            integral_off = dt_peak_i * tau * (1.0 - b)
            peak += dt_peak_i
            trough += dt_min_i
            mean += (integral_on + integral_off) / period
        mean_anchor = duty * p * theta_total
        scale = max(mean_anchor, peak, 1e-30)
        if abs(mean - mean_anchor) > 1e-9 * scale:
            raise ValueError("pulse_response 守恒锚失效：ΔT_mean ≠ D·P·ΣR（数值病态）")
        out = {
            "delta_t_peak_c": round(peak, 12),
            "delta_t_min_c": round(trough, 12),
            "delta_t_mean_c": round(mean, 12),
            "ripple_c": round(peak - trough, 12),
            "duty": round(duty, 12),
            "period_s": round(period, 12),
            "theta_total_c_per_w": round(theta_total, 12),
            "mean_power_w": round(duty * p, 12),
        }
    if ambient_c is not None:
        ta = _finite(ambient_c, "ambient_c")
        out["junction_peak_c"] = round(ta + out["delta_t_peak_c"], 12)
        out["junction_min_c"] = round(ta + out["delta_t_min_c"], 12)
        out["junction_mean_c"] = round(ta + out["delta_t_mean_c"], 12)
    return out


def pulse_train_waveform(
    power_w: float,
    t_on_s: float,
    t_off_s: float,
    n_periods: int,
    r_th: Sequence[float],
    tau_s: Sequence[float],
) -> dict[str, list[float]]:
    """脉冲链暂态波形（t=0 起步，逐段精确指数递推，无积分误差）。

    每段更新 x_i ← x_ss,i + (x_i − x_ss,i)·e^{−Δt/τ_i}（x_ss,i = P·R_i 导通 /
    0 关断）。采样点 = 每周期导通末 + 关断末（含 t=0 首点）。

    Returns:
        {"t_s": [...], "delta_t_c": [...]}（长度 1 + 2·n_periods；t_off=0 时
        长度 1 + n_periods）。
    """
    branches = _foster_branches(r_th, tau_s)
    p = _nonneg(power_w, "power_w")
    t_on = _positive(t_on_s, "t_on_s")
    t_off = _nonneg(t_off_s, "t_off_s")
    n_periods = int(n_periods)
    if n_periods < 1:
        raise ValueError("n_periods 必须 ≥1")
    state = [0.0] * len(branches)
    t_cursor = 0.0
    t_out = [0.0]
    dt_out = [0.0]
    for _ in range(n_periods):
        for dur, powered in ((t_on, True), (t_off, False)):
            if dur == 0.0:
                continue
            targets = [p * r if powered else 0.0 for r, _ in branches]
            decay = [math.exp(-dur / tau) for _, tau in branches]
            state = [t_ss + (x - t_ss) * d
                     for x, d, t_ss in zip(state, decay, targets, strict=True)]
            t_cursor += dur
            t_out.append(t_cursor)
            dt_out.append(sum(state))
    return {"t_s": t_out, "delta_t_c": dt_out}


def convolve_power_response(
    power_w_series: Sequence[float],
    dt_s: float,
    r_th: Sequence[float],
    tau_s: Sequence[float],
) -> list[float]:
    """零阶保持功率序列 → 结温瞬态序列（精确指数核递推，等价 Z_th 卷积）。

    ΔT[k] = Σ_i x_i[k]，x_i ← x_i·e^{−dt/τ_i} + P[k]·R_i·(1−e^{−dt/τ_i})；
    输出 ΔT[k] 对应第 k 个区间末时刻 (k+1)·dt。对 aging 热循环计数：直接
    消费本输出做 ΔT 峰谷提取（喂 core/aging.py 的循环寿命模型）。
    """
    branches = _foster_branches(r_th, tau_s)
    step = _positive(dt_s, "dt_s")
    series = [_nonneg(v, f"power_w_series[{i}]") for i, v in enumerate(power_w_series)]
    decay = [math.exp(-step / tau) for _, tau in branches]
    gain = [(1.0 - d) * r for d, (r, _) in zip(decay, branches, strict=True)]
    state = [0.0] * len(branches)
    out: list[float] = []
    for p_val in series:
        state = [x * d + p_val * g
                 for x, d, g in zip(state, decay, gain, strict=True)]
        out.append(sum(state))
    return out
