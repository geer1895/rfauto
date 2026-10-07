"""MM-1 吸波体族闭式内核 + Rozanov 厚度下界门（规格 规格深案 §A-4）。

纯函数零 IO 零环境依赖。
结构模型一律 ABCD 级联，原语 ``_abcd_tl``/``_abcd_shunt`` **逐字复用**
metasurface_lut（只 import 不改写）：入射面电阻片 shunt(Rs) @ 介质段
TL(η_s, β, d) @ PEC 终端（Z_L=0）→ Zin → Γ。

介质约定（两种入口分述，勿混用）：

- Salisbury / circuit-analog：**片与介质层同介质**（入射波阻抗
  η_in=η0/√εr）——规格设计式"最优 Rs=η0/√εr、d=λ0/(4√εr)"在该约定下
  于 f0 精确零反射；εr=1 退化为经典空气 Salisbury（Rs=η0=376.73Ω/sq、
  d=λ0/4）。若入射介质是空气而片贴介质垫层，最优片阻是 η0 而非
  η0/√εr（垫层只提供电长度 λ0/(4√εr)）——两种口径勿混装。
- Jaumann：多层（电阻片+背衬介质段）级联，入射介质=自由空间 η0
  （Knott《Radar Cross Section》多层 Salisbury/Jaumann 惯例）。

Rozanov 厚度下界（K.N. Rozanov, "Ultimate thickness to bandwidth ratio of
radar absorbers," IEEE TAP 48(8):1230-1234, 2000；介电型 μs=1）：

    d ≥ |∫₀^∞ ln|Γ(λ)| dλ| / (2π²)，  λ=自由空间波长。

本实现只对**输入有限带**数值积分（梯形），输出该带下界并显式附 band
注记——不冒充全带界（全谱界 ≥ 此值，分带越窄界越弱）。方向语义（定理
原文，实现即按此）：|Γ|=1（全反/零吸收）⇒ d_min=0；吸收越深/带越宽
⇒ |∫ln|Γ|dλ| 越大 ⇒ d_min 越大；理想 |Γ|=0 覆盖任意非零带宽 ⇒ d_min→∞
（Bode-Fano 型厚度-带宽守恒；Salisbury 的 Γ=0 只在孤立频点=测度零，
积分仍有限且已知饱和该界）。规格 §A-4 退化例"Γ=0 全吸收带→d_min→0"
方向与定理原文相反，本件按定理原文实现并如实记档（#122：学术诚信
优先于验收表全勾；勘误待规格 D 载体裁决回写）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from rfauto.core.metasurface_lut import C0_M_S, ETA0_OHM, _abcd_shunt, _abcd_tl

#: Rozanov 界分母 2π²（TAP 48(8):1230-1234 (2000)，介电型 μs=1）
_ROZANOV_DENOM = 2.0 * math.pi**2
_ROZANOV_NOTE = (
    "分频带下界：仅对输入有限带积分，全谱 Rozanov 界 >= 此值（带越窄界越弱，"
    "不冒充全带界）；介电型 mu_s=1 口径，Rozanov IEEE TAP 48(8):1230-1234 (2000)"
)


def _require_positive(value: float, name: str) -> float:
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，得到 {value!r}")
    return v


def _require_eps(eps_r: float) -> float:
    e = float(eps_r)
    if not math.isfinite(e) or e < 1.0:
        raise ValueError(f"eps_r 必须为无源介质（>=1），得到 {eps_r!r}")
    return e


def _freq_array(freq_hz) -> np.ndarray:
    f = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    if np.any(~np.isfinite(f)) or np.any(f <= 0.0):
        raise ValueError("freq_hz 必须为正有限频率（Hz）")
    return f


def _zin_pec(abcd: np.ndarray) -> complex:
    """ABCD 链终端接 PEC（Z_L=0）的输入阻抗 Zin=B/D；D=0（半波开路极限）→∞。"""
    den = abcd[1, 1]
    if den == 0.0:
        return complex(math.inf, 0.0)
    return complex(abcd[0, 1] / den)


def _gamma_from_zin(zin: complex, eta_in: float) -> complex:
    """入射介质波阻抗 η_in 下的反射系数；Zin=∞（开路）→ Γ=1。"""
    if math.isinf(zin.real) or math.isinf(zin.imag):
        return complex(1.0, 0.0)
    return (zin - eta_in) / (zin + eta_in)


def _reflection_payload(gammas: list[complex], zins: list[complex]) -> dict[str, np.ndarray]:
    gamma = np.asarray(gammas, dtype=complex)
    with np.errstate(divide="ignore"):
        gamma_db = 20.0 * np.log10(np.abs(gamma))
    return {"gamma": gamma, "gamma_db": gamma_db, "z_in": np.asarray(zins, dtype=complex)}


def salisbury_design(f0_hz: float, eps_r: float = 1.0) -> dict[str, float]:
    """Salisbury 屏设计式：最优 Rs=η0/√εr、d=λ0/(4√εr)（介质约定见模块 docstring）。

    返回 {"rs_ohm", "d_m"}；εr=1 退化为经典空气 Salisbury（377Ω/sq、λ0/4）。
    """
    f0 = _require_positive(f0_hz, "f0_hz")
    e = _require_eps(eps_r)
    return {"rs_ohm": ETA0_OHM / math.sqrt(e), "d_m": C0_M_S / (4.0 * f0 * math.sqrt(e))}


def salisbury_reflection(
    f_hz, d_m: float, rs_ohm: float, eps_r: float = 1.0
) -> dict[str, np.ndarray]:
    """Salisbury 屏反射系数：shunt(Rs) @ TL(η0/√εr, β, d) @ PEC → Zin → Γ。

    介质约定（片与介质层同介质，η_in=η0/√εr）见模块 docstring；d=λ0/(4√εr)、
    Rs=η0/√εr 时 f0 处 Zin=Rs（介质段半波开路极限）→ Γ=0 精确零反射。
    返回 {"gamma", "gamma_db", "z_in"}；γ=0 的 dB 载体为 −inf（errstate 抑制）。
    """
    f = _freq_array(f_hz)
    d = _require_positive(d_m, "d_m")
    rs = _require_positive(rs_ohm, "rs_ohm")
    e = _require_eps(eps_r)
    eta_s = ETA0_OHM / math.sqrt(e)
    beta = 2.0 * math.pi * f * math.sqrt(e) / C0_M_S
    gammas: list[complex] = []
    zins: list[complex] = []
    for i in range(f.size):
        abcd = _abcd_shunt(complex(rs)) @ _abcd_tl(eta_s, float(beta[i]), d)
        zin = _zin_pec(abcd)
        zins.append(zin)
        gammas.append(_gamma_from_zin(zin, eta_s))
    return _reflection_payload(gammas, zins)


def _sheet_params(sheet: Mapping, index: int) -> tuple[float, float, float]:
    rs = sheet.get("rs_ohm", sheet.get("rs"))
    d = sheet.get("d_m", sheet.get("d"))
    if rs is None or d is None:
        raise ValueError(
            f"sheets[{index}] 缺片阻/厚度键（接受 rs_ohm|rs 与 d_m|d），得到键 {sorted(sheet)}"
        )
    eps = _require_eps(sheet.get("eps_r", 1.0))
    return _require_positive(rs, f"sheets[{index}].rs"), _require_positive(
        d, f"sheets[{index}].d"
    ), eps


def jaumann_reflection(f_hz, sheets: Sequence[Mapping]) -> dict[str, np.ndarray]:
    """Jaumann 多层吸波体：sheets=[{rs_ohm, d_m, eps_r}, ...]（前→后），入射介质=自由空间。

    级联口径与 salisbury_reflection 同原语：逐层 shunt(rs_j) @ TL(η0/√εr_j,
    β_j, d_j)，PEC 终端，Γ 以 η0 计（Knott 惯例）。单层 eps_r=1、Rs=η0、
    d=λ0/4 精确退化为经典 Salisbury。守卫：sheets 空 / rs≤0 / d≤0 /
    eps_r<1 → ValueError。返回 {"gamma", "gamma_db", "z_in"}。
    """
    f = _freq_array(f_hz)
    if len(sheets) == 0:
        raise ValueError("sheets 至少一层")
    layers = [_sheet_params(s, i) for i, s in enumerate(sheets)]
    gammas: list[complex] = []
    zins: list[complex] = []
    for i in range(f.size):
        abcd = np.eye(2, dtype=complex)
        for rs, d, eps in layers:
            beta = 2.0 * math.pi * float(f[i]) * math.sqrt(eps) / C0_M_S
            abcd = abcd @ _abcd_shunt(complex(rs)) @ _abcd_tl(ETA0_OHM / math.sqrt(eps), beta, d)
        zin = _zin_pec(abcd)
        zins.append(zin)
        gammas.append(_gamma_from_zin(zin, ETA0_OHM))
    return _reflection_payload(gammas, zins)


def _ca_sheet_impedance(
    z_sheet_freq: Callable | Sequence, f: np.ndarray
) -> np.ndarray:
    """频变片阻抗取值：callable（f→复 Z 数组）或表 (freq_tab, z_tab) 线性插值。

    表口径：freq_tab 必须严格递增（逆序/乱序 ValueError，与 Rozanov 门同规）；
    带外取端点值钳位（np.interp 语义，docstring 显式声明不外推）。
    """
    if callable(z_sheet_freq):
        z_raw = np.asarray(z_sheet_freq(f), dtype=complex)
        if z_raw.ndim == 0:
            z = np.full(f.shape, complex(z_raw))  # 常数片阻抗（标量返回合法）
        else:
            z = np.atleast_1d(z_raw)
            if z.shape != f.shape:
                raise ValueError(f"z_sheet_freq(f) 形状 {z.shape} 与频率轴 {f.shape} 不一致")
    elif isinstance(z_sheet_freq, (int, float, complex)):
        z = np.full(f.shape, complex(z_sheet_freq))  # 常数片阻抗（标量入口）
    else:
        try:
            f_tab_raw, z_tab_raw = z_sheet_freq
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "z_sheet_freq 须为 callable 或 (freq_tab, z_tab) 表"
            ) from exc
        f_tab = np.atleast_1d(np.asarray(f_tab_raw, dtype=float))
        z_tab = np.atleast_1d(np.asarray(z_tab_raw, dtype=complex))
        if f_tab.shape != z_tab.shape or f_tab.ndim != 1 or f_tab.size < 2:
            raise ValueError("CA 表须为等长一维 (freq_tab, z_tab) 且 >=2 点")
        if np.any(~np.isfinite(f_tab)) or np.any(f_tab <= 0.0):
            raise ValueError("CA 表频率轴必须为正有限")
        if np.any(np.diff(f_tab) <= 0.0):
            raise ValueError("CA 表频率轴必须严格递增（逆序/乱序非法）")
        z = np.interp(f, f_tab, z_tab.real) + 1j * np.interp(f, f_tab, z_tab.imag)
    if np.any(z == 0):
        raise ValueError("片阻抗 Z=0（短路屏）超出 shunt 原语可表示域，非法")
    return z


def circuit_analog_reflection(
    f_hz, z_sheet_freq: Callable | Sequence, d_m: float, eps_r: float = 1.0
) -> dict[str, np.ndarray]:
    """电路模拟（CA）吸波体入口：频变片阻抗 shunt(Z(f)) @ TL(η0/√εr, β, d) @ PEC。

    介质约定与 salisbury_reflection 同（片与介质层同介质，η_in=η0/√εr），
    d_m/eps_r 为背衬介质段（CA 屏设计值常取 λ0/(4√εr) 量级）。
    z_sheet_freq：callable（f→复 Z）或表 (freq_tab, z_tab)（严格递增、带外
    端点钳位）。返回 {"gamma", "gamma_db", "z_in"}。
    """
    f = _freq_array(f_hz)
    d = _require_positive(d_m, "d_m")
    e = _require_eps(eps_r)
    z_arr = _ca_sheet_impedance(z_sheet_freq, f)
    eta_s = ETA0_OHM / math.sqrt(e)
    beta = 2.0 * math.pi * f * math.sqrt(e) / C0_M_S
    gammas: list[complex] = []
    zins: list[complex] = []
    for i in range(f.size):
        abcd = _abcd_shunt(z_arr[i]) @ _abcd_tl(eta_s, float(beta[i]), d)
        zin = _zin_pec(abcd)
        zins.append(zin)
        gammas.append(_gamma_from_zin(zin, eta_s))
    return _reflection_payload(gammas, zins)


def rozanov_min_thickness(freq_hz, gamma_mag) -> dict[str, Any]:
    """Rozanov 厚度下界（**分频带语义如实**）：d_min=|∫_带 ln|Γ(λ)|dλ|/(2π²)。

    只对输入有限带积分（梯形，λ=c0/f 轴），输出 {"d_min_m",
    "integral_ln_gamma_dlambda", "band_hz", "band_lambda_m", "note"}；note
    显式声明这是分带下界、全谱界 ≥ 此值（不冒充全带界）。方向语义：
    |Γ|=1 带 → d_min=0；深吸收/宽带 → d_min 增大；Γ=0 样本 → ValueError
    （ln0 发散；理想零反射是测度零点，用避开谷底的栅格）。守卫：频率轴
    严格递增（逆序/乱序 ValueError）、gamma_mag∈(0,1]（>1 非无源）。
    """
    f = _freq_array(freq_hz)
    g = np.atleast_1d(np.asarray(gamma_mag, dtype=float))
    if f.ndim != 1 or g.shape != f.shape:
        raise ValueError(f"freq_hz/gamma_mag 须为等长一维数组，得到 {f.shape} vs {g.shape}")
    if f.size < 2:
        raise ValueError("带积分至少需要 2 个频点")
    if np.any(np.diff(f) <= 0.0):
        raise ValueError("频率轴必须严格递增（逆序/乱序 ValueError）")
    if np.any(~np.isfinite(g)) or np.any(g <= 0.0) or np.any(g > 1.0):
        raise ValueError(
            "gamma_mag 必须在 (0,1]（无源反射率）；Γ=0 样本使带积分发散"
            "（理想零反射是测度零点，请用避开谷底的栅格或带实测下限的数据）"
        )
    lam = C0_M_S / f  # f 递增 → λ 递减，梯形积分符号随轴翻转，|·| 口径不受影响
    with np.errstate(all="ignore"):
        integral = float(np.trapezoid(np.log(g), lam))
    return {
        "d_min_m": abs(integral) / _ROZANOV_DENOM,
        "integral_ln_gamma_dlambda": integral,
        "band_hz": (float(f[0]), float(f[-1])),
        "band_lambda_m": (float(lam[-1]), float(lam[0])),
        "note": _ROZANOV_NOTE,
    }
