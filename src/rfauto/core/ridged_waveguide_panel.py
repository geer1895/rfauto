"""脊波导频扫输出面板（W4-B P14）：Z0(f)/单模带宽/α(f)。

规格出处（SM·core 深化报告 P14 顺件）：一阶横磁共振骨架上的频率扫描
输出面板——Z_PV(f)/Z_TE(f)、TE10 单模带宽（至下一高模截止）、导体损耗
α_c(f)（微扰式，rwg_mmt 先例同式）。本模块**只消费 core/ridged_waveguide
既有内核**（cutoff_kc/beta_z/z_pv_ohm/z_te_ohm 单源，零副本），自身零新
经验常数（#118）；与 W4-A/P2 的 Cohn 修正（cutoff_kc_cohn，opt-in）解耦：
本面板高模截止与主模截止均走一阶骨架（R=g/b），深脊定量不可信警告与
模块头精度域口径一致。

推导（模型内解析延拓，零借入系数）
------------------------------------
脊中线 x=a/2 是对称面：E_y 极大（开路）的模为奇指标 TE_m0（m=1,3,5…），
E_y=0（短路）的模为偶指标（m=2,4…）。记 A=k·s/2、B=k·(a−s)/2、R=g/b：

- 奇模：tan A·tan B = R。乘去 cosA·cosB 得**极零式**
      G(k) = sin A·sin B − R·cos A·cos B = 0，
  在正切极点处 G=sinA·sinB≠0（无伪根），扫描求根稳健。
  d==0（R=1）：G = −cos(A+B) = −cos(ka/2) → 根 (2m+1)π/a 逐位。
- 偶模：脊隙段向对称面看为短路线，谐振条件 cot A·tan B = −R，极零式
      F(k) = cos A·sin B + R·sin A·cos B = 0。
  d==0：F = sin(A+B) = sin(ka/2) → 根 2mπ/a 逐位（TE20 恒等式：
  fc20 = 2·fc10 对任意 s 成立——无脊即无脊负载，物理自洽）。
- α_c(f)：一阶微扰估计，α = Rs/(b·η0·√(1−(fc/f)²))·(1+2b/a·(fc/f)²)
  （与 core/rwg_mmt.alpha_c_te10 同式同口径），fc 取本骨架主模截止；
  **未含脊缘电流集中修正，深脊定量不可信（如实登记）**；d==0 时与
  rwg_mmt.alpha_c_te10 逐位一致（跨模块互证锚，单测钉）。

接口：纯函数零 IO；与 ridged_waveguide 同单位口径（SI 米/Hz，
JSON 可序列化输出）；bool 入参拒收（df7+⑯）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.ridged_waveguide import (
    C0,
    ETA0,
    MU0,
    RidgedWaveguide,
    beta_z,
    lambda_g_m,
    z_pv_ohm,
    z_te_ohm,
)

__all__ = [
    "alpha_c_te10_estimate",
    "even_mode_kcs",
    "next_mode_cutoff",
    "odd_mode_kcs",
    "ridged_waveguide_panel",
]

#: 高模扫描上限（k·a 计）：4π 覆盖 TE30（3π/a）与 TE40（4π/a）
_KA_SCAN_MAX = 4.0 * math.pi
#: 扫描网格点数（根间距 ~π/(2·max(s,l))，4000 点充分分辨）
_SCAN_N = 4000
#: 求根相对收敛容差（与内核 _ROOT_RTOL 同级）
_ROOT_RTOL = 1.0e-13


def _odd_g(k: float, wg: RidgedWaveguide) -> float:
    """奇模极零式 G(k)=sinA·sinB−R·cosA·cosB（A=ks/2，B=k(a−s)/2）。"""
    sa, ca = math.sin(k * wg.s / 2.0), math.cos(k * wg.s / 2.0)
    sb, cb = math.sin(k * (wg.a - wg.s) / 2.0), math.cos(k * (wg.a - wg.s) / 2.0)
    return sa * sb - wg.gap_ratio * ca * cb


def _even_f(k: float, wg: RidgedWaveguide) -> float:
    """偶模极零式 F(k)=cosA·sinB+R·sinA·cosB。"""
    sa, ca = math.sin(k * wg.s / 2.0), math.cos(k * wg.s / 2.0)
    sb, cb = math.sin(k * (wg.a - wg.s) / 2.0), math.cos(k * (wg.a - wg.s) / 2.0)
    return ca * sb + wg.gap_ratio * sa * cb


def _bisect(func, lo: float, hi: float, flo: float, a_scale: float) -> float:
    """区间二分求根（f(lo)·f(hi)<0 由调用方保证）。"""
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        fm = func(mid)
        if flo * fm < 0.0:
            hi = mid
        else:
            lo, flo = mid, fm
        if hi - lo <= _ROOT_RTOL * max(hi, a_scale * 1e-30):
            break
    return 0.5 * (lo + hi)


def _scan_roots(func: Any, wg: RidgedWaveguide, n_roots: int) -> list[float]:
    """(0, k_up] 网格符号变化扫描 + 二分精炼；d==0 走解析恒等式短路。"""
    if wg.d == 0.0:
        if func is _odd_g:
            return [(2 * m + 1) * math.pi / wg.a for m in range(n_roots)]
        return [2 * m * math.pi / wg.a for m in range(1, n_roots + 1)]
    k_up = _KA_SCAN_MAX / wg.a
    ks = [k_up * (i + 1) / _SCAN_N for i in range(_SCAN_N)]
    roots: list[float] = []
    f_prev = func(ks[0], wg)
    for i in range(1, _SCAN_N):
        f_cur = func(ks[i], wg)
        if f_prev == 0.0:
            roots.append(ks[i - 1])
        elif f_prev * f_cur < 0.0:
            roots.append(_bisect(lambda k: func(k, wg), ks[i - 1], ks[i],
                                 f_prev, wg.a))
        if len(roots) >= n_roots:
            break
        f_prev = f_cur
    return roots[:n_roots]


def odd_mode_kcs(wg: RidgedWaveguide, n_roots: int = 2) -> list[float]:
    """奇指标模（TE10/TE30/…）截止波数（rad/m，升序，m=1,3,5…）。

    n_roots=1 即主模（与内核 cutoff_kc 同解，不同求根路径——互证面）。
    """
    if not isinstance(n_roots, int) or isinstance(n_roots, bool) or n_roots < 1:
        raise ValueError(f"n_roots 须为 ≥1 整数，得到 {n_roots!r}")
    return _scan_roots(_odd_g, wg, n_roots)


def even_mode_kcs(wg: RidgedWaveguide, n_roots: int = 1) -> list[float]:
    """偶指标模（TE20/TE40/…）截止波数（rad/m，升序，m=2,4…）。"""
    if not isinstance(n_roots, int) or isinstance(n_roots, bool) or n_roots < 1:
        raise ValueError(f"n_roots 须为 ≥1 整数，得到 {n_roots!r}")
    return _scan_roots(_even_f, wg, n_roots)


def next_mode_cutoff(wg: RidgedWaveguide) -> dict[str, Any]:
    """TE10 之上第一个高模截止（单模带宽上端）。

    Returns:
        dict：mode（"TE20" 或 "TE30"）、kc_rad_m、fc_hz、
        single_mode_band_hz=(fc10, fc_next)。
    """
    fc10 = C0 * odd_mode_kcs(wg, 1)[0] / (2.0 * math.pi)
    k20 = even_mode_kcs(wg, 1)[0]
    k30 = odd_mode_kcs(wg, 2)[1]
    fc20 = C0 * k20 / (2.0 * math.pi)
    fc30 = C0 * k30 / (2.0 * math.pi)
    if fc20 <= fc30:
        return {"mode": "TE20", "kc_rad_m": k20, "fc_hz": fc20,
                "single_mode_band_hz": (fc10, fc20)}
    return {"mode": "TE30", "kc_rad_m": k30, "fc_hz": fc30,
            "single_mode_band_hz": (fc10, fc30)}


def alpha_c_te10_estimate(f_hz: float, wg: RidgedWaveguide,
                          sigma: float) -> float:
    """TE10 导体衰减一阶微扰估计（Np/m；脊缘电流集中未修正，如实登记）。

    α = Rs/(b·η0·√(1−(fc/f)²))·(1+2b/a·(fc/f)²)，Rs=√(πfμ0/σ)。
    f≤fc 显式 ValueError（微扰发散域，同 rwg_mmt 口径）；d==0 时与
    core/rwg_mmt.alpha_c_te10 逐位一致（跨模块互证锚）。
    """
    if isinstance(sigma, bool) or not isinstance(sigma, (int, float)):
        raise ValueError(f"sigma 必须为有限正数，得到 {sigma!r}")
    sigma = float(sigma)
    if not (math.isfinite(sigma) and sigma > 0.0):
        raise ValueError(f"sigma 必须为有限正数，得到 {sigma!r}")
    f = float(f_hz)
    if not (math.isfinite(f) and f > 0.0):
        raise ValueError(f"f_hz 必须为有限正数，得到 {f_hz!r}")
    fc = C0 * odd_mode_kcs(wg, 1)[0] / (2.0 * math.pi)
    if f <= fc:
        raise ValueError(
            f"alpha_c_te10_estimate: f={f:g} Hz ≤ fc10={fc:g} Hz，"
            "截止以下微扰发散不外推")
    rs = math.sqrt(math.pi * f * MU0 / sigma)
    x = (fc / f) ** 2
    return rs / (wg.b * ETA0 * math.sqrt(1.0 - x)) * (1.0 + 2.0 * wg.b / wg.a * x)


def ridged_waveguide_panel(f_grid_hz: list[float], wg: RidgedWaveguide,
                           sigma: float | None = None) -> dict[str, Any]:
    """频扫输出面板：逐频 Z_PV/Z_TE/β/λg/α_c + 单模带宽块（JSON 可序列化）。

    Args:
        f_grid_hz: 频率点（Hz，>fc10；每个点单独校验，越截止显式报错）。
        wg: 脊波导截面。
        sigma: 导体电导率（S/m；None=无损面板，α 字段为 None）。

    Returns:
        dict：rows（逐频行，multimode 标记 f 是否越下一模截止）+
        bandwidth（fc10_hz、next_mode 块）。
    """
    if not f_grid_hz:
        raise ValueError("f_grid_hz 不得为空")
    if sigma is not None:
        if isinstance(sigma, bool) or not isinstance(sigma, (int, float)):
            raise ValueError(f"sigma 必须为有限正数，得到 {sigma!r}")
        if not (math.isfinite(float(sigma)) and float(sigma) > 0.0):
            raise ValueError(f"sigma 必须为有限正数，得到 {sigma!r}")
    nxt = next_mode_cutoff(wg)
    rows: list[dict[str, Any]] = []
    for f in f_grid_hz:
        f = float(f)
        beta = beta_z(f, wg)  # f≤fc 在此显式报错（内核单源守卫）
        alpha = (alpha_c_te10_estimate(f, wg, float(sigma))
                 if sigma is not None else None)
        rows.append({
            "f_hz": f,
            "beta_rad_m": beta,
            "lambda_g_m": lambda_g_m(f, wg),
            "z_pv_ohm": z_pv_ohm(f, wg),
            "z_te_ohm": z_te_ohm(f, wg),
            "alpha_c_np_per_m": alpha,
            "multimode": bool(f > nxt["fc_hz"]),
        })
    return {"rows": rows,
            "bandwidth": {"fc10_hz": nxt["single_mode_band_hz"][0],
                          "next_mode": nxt}}
