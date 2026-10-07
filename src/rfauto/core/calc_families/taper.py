"""Klopfenstein 渐变段综合（DP-15 C2）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from .registry import C_MM_GHZ, register_calculator
from .rf_line import _microstrip_media

# ─── Klopfenstein 渐变段（DP-15 C2，2026-09-24 df6_dp15c2，#231/#304 四表同步）
# 判据预声明与实测锚见 runs/df6_dp15c2/criteria.md §3；阻抗剖面来自
# skrf.taper.Klopfenstein 闭式（ DefinedGammaZ0(gamma=ω/c) 承载），宽度剖面
# 由 MLine 闭式同源求根——全程无抄毫米数（铁律 1c）。

@lru_cache(maxsize=8)
def _mline_z0_table(freq_ghz: float, epsilon_r: float, h_mm: float,
                    tand: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """微带 Z0(w) 对数锚表（48 点，w∈[1e-4·h, 30·h]），PCHIP 粗根底座。

    锚点全部来自 MLine 闭式（Hammerstad-Jensen），缓存纯函数于输入元组。
    """
    h_m = h_mm * 1e-3
    w_tab = np.exp(np.linspace(np.log(1e-4 * h_m), np.log(30.0 * h_m), 48))
    z_tab = [_mline_z0_of_width(float(w), freq_ghz, epsilon_r, h_mm, tand)
             for w in w_tab]
    return tuple(float(w) for w in w_tab), tuple(z_tab)


def _mline_z0_of_width(width_m: float, freq_ghz: float, epsilon_r: float,
                       h_mm: float, tand: float) -> float:
    media = _microstrip_media(width_m * 1e3, freq_ghz, epsilon_r, h_mm, tand)
    return float(np.real(media.z0[0]))


def _microstrip_width_for_z0(z0_target: float, freq_ghz: float,
                             epsilon_r: float, h_mm: float,
                             tand: float) -> tuple[float, float]:
    """MLine 闭式同源求根：w(mm) 使 |Z0_MLine(w)| = z0_target (Ω)。

    两步：对数域 PCHIP 粗根（锚表插值）→ MLine 牛顿精化（函数值精确、
    导数取 PCHIP，收敛到精确根）。返回 (width_mm, z0_achieved)。
    """
    from scipy.interpolate import PchipInterpolator

    w_tab, z_tab = _mline_z0_table(freq_ghz, epsilon_r, h_mm, tand)
    z_max, z_min = z_tab[0], z_tab[-1]  # w↑ → z0↓（单调，PCHIP 保号）
    zt = float(z0_target)
    if not z_min <= zt <= z_max:
        raise ValueError(
            f"目标阻抗 {zt:.2f}Ω 超出该叠层微带可达域 "
            f"[{z_min:.2f}, {z_max:.2f}]Ω（h={h_mm}mm/εr={epsilon_r}）")
    # 表按 w 升序 → z 降序；PCHIP 需要 x 升序，故反转（log-log 线性化）
    lnw_of_lnz = PchipInterpolator(np.log(np.array(z_tab[::-1])),
                                   np.log(np.array(w_tab[::-1])))
    lnw = float(lnw_of_lnz(math.log(zt)))
    lnzt = math.log(zt)
    z_exact = z_min
    for _ in range(6):
        w = math.exp(lnw)
        z_exact = _mline_z0_of_width(w, freq_ghz, epsilon_r, h_mm, tand)
        if abs(z_exact - zt) <= 1e-10 * zt:
            break
        d_lnw_d_lnz = float(lnw_of_lnz.derivative()(math.log(z_exact)))
        if not np.isfinite(d_lnw_d_lnz) or d_lnw_d_lnz == 0.0:
            break  # 导数退化：保守退出，末尾可达性检查会如实拦下
        # 注：lnw(lnz) 方向导数为负（z↑→w↓）是正常单调方向，勿拦
        lnw -= (math.log(z_exact) - lnzt) * d_lnw_d_lnz
    rel = abs(z_exact - zt) / zt
    if rel > 1e-6:
        raise ValueError(
            f"微带求根未收敛：目标 {zt:.4f}Ω， achieved {z_exact:.4f}Ω "
            f"（rel={rel:.2e}）")
    return math.exp(lnw) * 1e3, z_exact


def _klopfenstein_impedance_profile(z1: float, z2: float, rmax: float,
                                    length_m: float,
                                    n_sections: int) -> np.ndarray:
    """skrf.taper.Klopfenstein 阻抗剖面（Ω，length 方向 linspace(0, L)）。

    DefinedGammaZ0 需显式 gamma=ω/c——其缺省 gamma=1j 是常数 β=1 rad/m
    （零电长假网络陷阱，criteria §0.5）。rmax 经 f_kw 传入（构造器 kwarg
    会 TypeError，skrf.taper 实测）。
    """
    import skrf
    from skrf.taper import Klopfenstein

    freq = skrf.Frequency(1.0, 1.0, 1, unit="GHz")
    gamma = 1j * 2.0 * np.pi * freq.f / (C_MM_GHZ * 1e9)
    taper = Klopfenstein(
        med=skrf.media.DefinedGammaZ0,
        med_kw={"frequency": freq, "z0": float(z1), "gamma": gamma},
        f_kw={"rmax": float(rmax)},
        start=float(z1), stop=float(z2),
        length=float(length_m), n_sections=int(n_sections),
    )
    return np.array([float(m.z0[0].real) for m in taper.medias], dtype=float)


@register_calculator(
    "klopfenstein_taper",
    "Klopfenstein 阻抗渐变段综合：z1→z2 渐变（skrf.taper.Klopfenstein 剖面"
    " + 微带 MLine 同源宽度剖面）→ 阻抗/宽度剖面、通带回损估计、βL≥A 通带"
    "条件核验。rmax=通带反射因子 sech(A)，通带纹波 ρ0=Γ0·rmax（Γ0=½|ln(z2"
    "/z1)|，Pozar §5.9 参数化恒等）",
    (("z1_ohm", "float Ω 起端阻抗"),
     ("z2_ohm", "float Ω 末端阻抗（≠z1）"),
     ("length_mm", "float mm 渐变段物理长度"),
     ("epsilon_r", "float - 基板相对介电常数（>1）"),
     ("h_mm", "float mm 基板厚度"),
     ("freq_ghz", "float GHz 设计频率（βL 条件核验点）"),
     ("rmax", "float - 通带反射因子 ρ0/Γ0，(0,1) 开区间（缺省 0.1）"),
     ("n_sections", "int - 剖面离散段数 5..401（缺省 81）"),
     ("tand", "float - 损耗正切（默认 0）")),
    required=("z1_ohm", "z2_ohm", "length_mm", "epsilon_r", "h_mm",
              "freq_ghz"),
)
def klopfenstein_taper(z1_ohm: float, z2_ohm: float, length_mm: float,
                       epsilon_r: float, h_mm: float, freq_ghz: float,
                       rmax: float = 0.1, n_sections: int = 81,
                       tand: float = 0.0) -> dict:
    z1 = float(z1_ohm)
    z2 = float(z2_ohm)
    if not (np.isfinite(z1) and np.isfinite(z2)) or z1 <= 0 or z2 <= 0:
        raise ValueError("z1_ohm/z2_ohm 须为有限正数")
    if z1 == z2:
        raise ValueError(
            "z1==z2：步进反射 Γ0=0，渐变段无意义且通带回损无穷")
    if not (0.0 < float(rmax) < 1.0):
        raise ValueError(f"rmax 须在 (0,1) 开区间，实际 {rmax!r}")
    length = float(length_mm)
    if not np.isfinite(length) or length <= 0:
        raise ValueError(f"length_mm 须为正实数，实际 {length_mm!r}")
    er = float(epsilon_r)
    if not np.isfinite(er) or er <= 1.0:
        raise ValueError(f"epsilon_r 须 >1，实际 {epsilon_r!r}")
    h = float(h_mm)
    if not np.isfinite(h) or h <= 0:
        raise ValueError(f"h_mm 须为正实数，实际 {h_mm!r}")
    f_ghz = float(freq_ghz)
    if not np.isfinite(f_ghz) or f_ghz <= 0:
        raise ValueError(f"freq_ghz 须为正实数，实际 {freq_ghz!r}")
    n_sec = int(n_sections)
    if not 5 <= n_sec <= 401:
        raise ValueError(f"n_sections 须在 5..401，实际 {n_sections!r}")
    td = float(tand)
    if not np.isfinite(td) or td < 0:
        raise ValueError(f"tand 须为非负实数，实际 {tand!r}")

    gamma0 = abs(math.log(z2 / z1)) / 2.0
    A = math.acosh(1.0 / float(rmax))
    rho0 = gamma0 * float(rmax)
    rl_db = -20.0 * math.log10(rho0)

    profile = _klopfenstein_impedance_profile(z1, z2, rmax, length * 1e-3,
                                              n_sec)
    widths_mm = []
    z_rel_err = 0.0
    for zt in profile:
        w_mm, z_ok = _microstrip_width_for_z0(zt, f_ghz, er, h, td)
        widths_mm.append(w_mm)
        z_rel_err = max(z_rel_err, abs(z_ok - zt) / zt)

    diffs = np.diff(profile)
    monotonic = bool(np.all(diffs > 0) or np.all(diffs < 0))
    mid = _microstrip_media(widths_mm[n_sec // 2], f_ghz, er, h, td)
    beta_mid = float(np.real(mid.beta[0]))
    beta_l = beta_mid * (length * 1e-3)
    # 通带下限频率估算（低色散近似 β(f)≈β_mid·f/f_design；逐频色散不做，
    # 剖面是几何量，passband_ok 只在设计点核验）
    f_min_ghz = A * f_ghz / beta_l
    return {
        "z_profile_ohm": [round(v, 6) for v in profile],
        "width_profile_mm": [round(v, 6) for v in widths_mm],
        "x_norm": [round(v, 9) for v in np.linspace(0.0, 1.0, n_sec)],
        "n_sections": n_sec,
        "gamma0_step_reflection": round(gamma0, 9),
        "A": round(A, 9),
        "rmax": round(float(rmax), 9),
        "passband_ripple_rho0": round(rho0, 12),
        "rl_passband_db": round(rl_db, 4),
        "beta_l_design": round(beta_l, 6),
        "passband_ok": bool(beta_l >= A),
        "f_passband_min_ghz_estimate": round(f_min_ghz, 6),
        "monotonic": monotonic,
        "z0_width_check_max_rel": round(z_rel_err, 12),
        "note": "剖面=skrf.taper.Klopfenstein（linspace(0,L) 采样）；宽度="
                "MLine 闭式同源求根；通带纹波 ρ0=Γ0·rmax 仅在 βL≥A 频段"
                "成立（passband_ok/f_passband_min 为设计点核验与低色散估算）",
    }
