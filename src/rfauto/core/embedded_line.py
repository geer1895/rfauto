"""嵌入式微带 / 非对称三层带线 / 双层悬置变体确定性内核（TA-11，ge8d Wave D 席 D2）。

条目（研究扩充 round15 §二·2 TA-11）：
「嵌入式微带/双层悬置变体/非对称三层带线 | Wadell/Edwards&Steer | S-M/P2-P3」。

**内核形态如实登记（#122，inverted_ms/fgcpw 同制度）**：Wadell《Transmission
Line Design Handbook》/Edwards&Steer 的嵌入式微带（介质覆盖层）与非对称
（偏置）带线闭式系数在可达来源中均无原文数字（反爬/纸本受限；凭记忆复写
系数的引用腐坏风险被 #df6-⑬ 先例否决），本内核以 **2D 准静态 FD Laplace
裁判**（core/quasistatic_fd 通用变分求解器 energy_quasistatic + 网格原语
直连，本模块零改 quasistatic_fd 既有行）+ brentq 反解为数字真值：

- FD 裁判求解器资格（core/quasistatic_fd 模块头）：微带 vs HJ 静态
  +0.18~0.32%、CPS 半空间极限 −0.1%、Cohn 空气带线 −0.5%、h→b εr 精确
  四锚已过；
- 新几何族族内验证锚（test_ta_wave_c_templates）：
  * 嵌入式微带：① h2→0 退化为普通微带（跨族同物理互检，quasistatic_fd
    microstrip 族）；② h2→∞（厚覆盖同 εr）→ 均匀介质化 εeff→εr；③
    εr=1 与微带族 εr=1 精确同解（无介质边界）；④ 1 ≤ εeff ≤ εr 括号+
    εeff(h2)/Z0(w) 单调性；
  * 非对称带线：① 均匀介质 εeff=εr **精确**（场全在均质介质内——解析
    恒等式锚）；② 对称极限 d1=d2 对 Cohn 精确闭式（core/calc_families/
    rf_line._stripline_z0，椭圆积分共形映射）；③ 偏置单调性（带贴近一地
    → C 增 → Z0 降）；
  * 双层悬置变体：① er2=er1 与既有单层悬置带线族（quasistatic_fd
    suspended_stripline）同物理互检；② 对称双层 εeff ∈ (min, max)(εr1,εr2)
    括号；
- 近似级别如实声明：准静态（无色散）、零厚度带、PEC 地/腔壁、介质无损；
  数值地板=FD 离散+Richardson 外推（族内实测 ~0.2-0.5%）。

设计链（#1c 无手抄毫米数）：50Ω 名义 w 由 brentq 反解+回代自洽；λg 准静
态口径（色散未计如实声明）。

真机冒烟与 HFSS 仲裁属后续批次（本批零发射；模板 meta smoke_note 登记）。
"""

from __future__ import annotations

import math

__all__ = [
    "asym_stripline_capacitance_eps0",
    "asym_stripline_design_params",
    "asym_stripline_quasistatic",
    "embedded_microstrip_capacitance_eps0",
    "embedded_ms_design_params",
    "embedded_ms_quasistatic",
    "suspended_stripline_2layer_quasistatic",
]


# ─── FD 族一：嵌入式微带（地上基板 h1 + 零厚带 z=h1 + 覆盖层 h2，无上地）─────

def embedded_microstrip_capacitance_eps0(
        w_mm: float, h1_mm: float, h2_mm: float, er1: float, er2: float,
        d0_mm: float, xmax_mm: float | None = None,
        zmax_mm: float | None = None) -> tuple[float, int]:
    """嵌入式微带半域电容（ε0 单位）：地 z=0 φ=0；基板 z∈[0,h1] εr1、覆盖层
    z∈[h1,h1+h2] εr2；零厚度带 z=h1（层界面）、x∈[0,w/2] φ=1；上/右外边界
    Neumann（开线无上地）。C = 4·W_half。

    对称轴 x=0 Neumann（微带族同口径）；外域缺省 = inverted_microstrip 族
    20·b 口径（#303：开线族空气场衰减慢，域截断进 C_air 而 εeff 比值不敏感
    ≤0.1%）。er1=er2 时退化为均匀嵌埋（焊帽/预浸覆盖经典定义）；h2→0 退化
    普通微带。
    """
    import numpy as np

    from rfauto.core.quasistatic_fd import (
        concat_lines,
        energy_quasistatic,
        graded_lines,
        uniform_lines,
    )

    if w_mm <= 0 or h1_mm <= 0 or h2_mm <= 0 or er1 < 1.0 or er2 < 1.0:
        raise ValueError(
            "嵌入式微带裁判定义域：w>0、h1>0、h2>0、εr1/εr2≥1")
    z1 = h1_mm
    z2 = h1_mm + h2_mm
    scale = max(w_mm / 2.0, z1)
    xm = xmax_mm if xmax_mm is not None else max(8.0, 20.0 * scale)
    zm = (zmax_mm if zmax_mm is not None
          else max(8.0, 20.0 * scale, z2 + 4.0 * (h1_mm + h2_mm)))
    xs = concat_lines(uniform_lines(0.0, w_mm / 2.0, d0_mm),
                      graded_lines(w_mm / 2.0, xm, d0_mm))
    zs = concat_lines(uniform_lines(0.0, z1, d0_mm),
                      uniform_lines(z1, z2, d0_mm),
                      graded_lines(z2, zm, d0_mm))
    nx, nz = xs.size, zs.size
    eps = np.ones((nx - 1, nz - 1))
    zc = 0.5 * (zs[:-1] + zs[1:])
    eps[:, zc < z1] = er1
    eps[:, (zc >= z1) & (zc < z2)] = er2
    j1 = int(np.argmin(np.abs(zs - z1)))
    iw = int(np.argmin(np.abs(xs - w_mm / 2.0)))
    if abs(zs[j1] - z1) > 1e-12 or abs(xs[iw] - w_mm / 2.0) > 1e-12:
        raise RuntimeError("嵌入式微带网格线未精确落在带缘/层界面（构造错误）")
    diri = {i * nz: 0.0 for i in range(nx)}          # 地 z=0
    for i in range(iw + 1):                           # 带 z=h1 φ=1
        diri[i * nz + j1] = 1.0
    return 4.0 * energy_quasistatic(xs, zs, eps, diri), nx * nz


def embedded_ms_quasistatic(w_mm: float, h1_mm: float, h2_mm: float,
                            er: float, d0_mm: float | None = None,
                            richardson: bool = True,
                            **grid_kw: float) -> object:
    """嵌入式微带 εeff/Z0 裁判（同 εr 嵌入口径 er1=er2=er）。缺省
    d0 = min(h1, h2)/20。"""
    from rfauto.core.quasistatic_fd import _finish, richardson_first_order

    d0 = d0_mm if d0_mm is not None else min(h1_mm, h2_mm) / 20.0
    steps = (d0, d0 / 2.0) if richardson else (d0,)
    eps_v, cair_v, n_nodes = [], [], 0
    for d in steps:
        c_d, n_nodes = embedded_microstrip_capacitance_eps0(
            w_mm, h1_mm, h2_mm, er, er, d, **grid_kw)
        c_a, _ = embedded_microstrip_capacitance_eps0(
            w_mm, h1_mm, h2_mm, 1.0, 1.0, d, **grid_kw)
        eps_v.append(c_d / c_a)
        cair_v.append(c_a)
    c_air = (richardson_first_order(cair_v[0], cair_v[1]) if richardson
             else cair_v[-1])
    return _finish(eps_v[-1] * c_air, c_air, d0, richardson,
                   eps_v[0], eps_v[-1], n_nodes)


def embedded_ms_design_params(z0_ohm: float = 50.0,
                              h1_mm: float = 0.508,
                              h2_mm: float = 0.254,
                              er: float = 3.66,
                              line_len_mm: float = 40.0,
                              f0_ghz: float = 2.5) -> dict[str, float]:
    """设计链：目标 Z0 → 带宽 w（FD 裁判 brentq 反解，回代自洽）。

    返回 w_mm（4 位舍入）/ z0_actual_ohm / eps_eff / line_len_mm 及派生
    λg@f0（准静态口径，色散未计如实声明）。Z0 随 w 单调递减（宽带→低阻；
    单测网格钉）。
    """
    from scipy.optimize import brentq

    z_t = float(z0_ohm)
    if not (math.isfinite(z_t) and z_t > 0.0):
        raise ValueError(f"embedded_ms: z0_ohm 须为正有限数，得到 {z0_ohm!r}")
    for name, v in (("h1_mm", h1_mm), ("h2_mm", h2_mm)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"embedded_ms: {name} 须为正有限数，得到 {v!r}")
    if not (math.isfinite(er) and er >= 1.0):
        raise ValueError(f"embedded_ms: er 须 ≥1，得到 {er!r}")

    def objective(w_mm: float) -> float:
        r = embedded_ms_quasistatic(w_mm, float(h1_mm), float(h2_mm),
                                    float(er))
        return r.z0_ohm - z_t

    ht = float(h1_mm) + float(h2_mm)
    lo, hi = 0.05 * ht, 60.0 * ht
    z_lo, z_hi = objective(lo), objective(hi)
    if z_lo < 0.0 or z_hi > 0.0:
        raise ValueError(
            f"目标 {z_t}Ω 超出嵌入式微带可达范围 [{z_hi + z_t:.1f}, "
            f"{z_lo + z_t:.1f}]Ω（w∈[{lo:.4f}, {hi:.4f}]mm 括号扫描）")
    w_mm = float(brentq(objective, lo, hi, xtol=1e-9))
    r = embedded_ms_quasistatic(round(w_mm, 4), float(h1_mm), float(h2_mm),
                                float(er))
    eps_eff = float(r.eps_eff)
    lam_g_mm = 299.792458 / (float(f0_ghz) * math.sqrt(eps_eff))
    return {
        "w_mm": round(w_mm, 4),
        "z0_actual_ohm": round(float(r.z0_ohm), 3),
        "eps_eff": round(eps_eff, 5),
        "lambda_g_mm": round(lam_g_mm, 4),
        "line_len_mm": float(line_len_mm),
        "h1_mm": float(h1_mm),
        "h2_mm": float(h2_mm),
        "er": float(er),
    }


# ─── FD 族二：非对称（偏置）三层带线（双地板腔 + 均质介质）───────────────────

def asym_stripline_capacitance_eps0(
        w_mm: float, d1_mm: float, d2_mm: float, eps_r: float,
        d0_mm: float) -> tuple[float, int]:
    """偏置带线半域电容（ε0 单位）：地 z=0 与 z=b=d1+d2 双 Dirichlet φ=0；
    零厚度带 z=d1、x∈[0,w/2] φ=1；均质介质 εr（εeff=εr 精确——解析恒等式，
    单测钉）。
    C = 4·W_half。对称轴 x=0 Neumann（微带族同口径）。"""
    import numpy as np

    from rfauto.core.quasistatic_fd import (
        concat_lines,
        energy_quasistatic,
        graded_lines,
        uniform_lines,
    )

    if w_mm <= 0 or d1_mm <= 0 or d2_mm <= 0 or eps_r < 1.0:
        raise ValueError("偏置带线裁判定义域：w>0、d1>0、d2>0、εr≥1")
    b = d1_mm + d2_mm
    # 远区外界必须严格越过带缘（w 可达 20·b ⇒ 8/4b 缺省可小于 w/2——括号
    # 扫描宽支 graded_lines 逆向非单调 concat 即炸，2026-10-03 实测修复）
    xm = max(8.0, 4.0 * b, 3.0 * w_mm / 2.0)
    xs = concat_lines(uniform_lines(0.0, w_mm / 2.0, d0_mm),
                      graded_lines(w_mm / 2.0, xm, d0_mm))
    zs = concat_lines(uniform_lines(0.0, d1_mm, d0_mm),
                      uniform_lines(d1_mm, b, d0_mm))
    nx, nz = xs.size, zs.size
    eps = np.full((nx - 1, nz - 1), float(eps_r))
    j1 = int(np.argmin(np.abs(zs - d1_mm)))
    iw = int(np.argmin(np.abs(xs - w_mm / 2.0)))
    if abs(zs[j1] - d1_mm) > 1e-12 or abs(xs[iw] - w_mm / 2.0) > 1e-12:
        raise RuntimeError("偏置带线网格线未精确落在带缘（构造错误）")
    diri: dict[int, float] = {}
    for i in range(nx):                               # 地 z=0 与 z=b
        diri[i * nz] = 0.0
        diri[i * nz + nz - 1] = 0.0
    for i in range(iw + 1):                           # 带 z=d1 φ=1
        diri[i * nz + j1] = 1.0
    return 4.0 * energy_quasistatic(xs, zs, eps, diri), nx * nz


def asym_stripline_quasistatic(w_mm: float, d1_mm: float, d2_mm: float,
                               eps_r: float, d0_mm: float | None = None,
                               richardson: bool = True) -> object:
    """偏置带线 εeff/Z0 裁判。缺省 d0 = min(d1, d2)/20。"""
    from rfauto.core.quasistatic_fd import _finish, richardson_first_order

    d0 = d0_mm if d0_mm is not None else min(d1_mm, d2_mm) / 20.0
    steps = (d0, d0 / 2.0) if richardson else (d0,)
    eps_v, cair_v, n_nodes = [], [], 0
    for d in steps:
        c_d, n_nodes = asym_stripline_capacitance_eps0(
            w_mm, d1_mm, d2_mm, eps_r, d)
        c_a, _ = asym_stripline_capacitance_eps0(w_mm, d1_mm, d2_mm, 1.0, d)
        eps_v.append(c_d / c_a)
        cair_v.append(c_a)
    c_air = (richardson_first_order(cair_v[0], cair_v[1]) if richardson
             else cair_v[-1])
    return _finish(eps_v[-1] * c_air, c_air, d0, richardson,
                   eps_v[0], eps_v[-1], n_nodes)


def asym_stripline_design_params(z0_ohm: float = 50.0,
                                 d1_mm: float = 0.381,
                                 d2_mm: float = 0.635,
                                 er: float = 3.66,
                                 line_len_mm: float = 40.0,
                                 f0_ghz: float = 2.5) -> dict[str, float]:
    """设计链：目标 Z0 → 带宽 w（FD 裁判 brentq 反解，回代自洽；登记级
    闭式面——无模板注册，消费方=本模块单测与后续批次）。"""
    from scipy.optimize import brentq

    z_t = float(z0_ohm)
    if not (math.isfinite(z_t) and z_t > 0.0):
        raise ValueError(f"asym_stripline: z0_ohm 须为正有限数，得到 {z0_ohm!r}")
    for name, v in (("d1_mm", d1_mm), ("d2_mm", d2_mm)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"asym_stripline: {name} 须为正有限数，得到 {v!r}")
    if not (math.isfinite(er) and er >= 1.0):
        raise ValueError(f"asym_stripline: er 须 ≥1，得到 {er!r}")

    def objective(w_mm: float) -> float:
        r = asym_stripline_quasistatic(w_mm, float(d1_mm), float(d2_mm),
                                       float(er))
        return r.z0_ohm - z_t

    b = float(d1_mm) + float(d2_mm)
    lo, hi = 0.02 * b, 20.0 * b
    z_lo, z_hi = objective(lo), objective(hi)
    if z_lo < 0.0 or z_hi > 0.0:
        raise ValueError(
            f"目标 {z_t}Ω 超出偏置带线可达范围 [{z_hi + z_t:.1f}, "
            f"{z_lo + z_t:.1f}]Ω（w∈[{lo:.4f}, {hi:.4f}]mm 括号扫描）")
    w_mm = float(brentq(objective, lo, hi, xtol=1e-9))
    r = asym_stripline_quasistatic(round(w_mm, 4), float(d1_mm),
                                   float(d2_mm), float(er))
    lam_g_mm = 299.792458 / (float(f0_ghz) * math.sqrt(float(r.eps_eff)))
    return {
        "w_mm": round(w_mm, 4),
        "z0_actual_ohm": round(float(r.z0_ohm), 3),
        "eps_eff": round(float(r.eps_eff), 6),
        "lambda_g_mm": round(lam_g_mm, 4),
        "line_len_mm": float(line_len_mm),
        "d1_mm": float(d1_mm),
        "d2_mm": float(d2_mm),
        "er": float(er),
    }


# ─── FD 族三：双层悬置带线变体（腔内两层基板，带在层界面；登记级）────────────

def suspended_stripline_2layer_quasistatic(
        w_mm: float, b_mm: float, h1_mm: float, h2_mm: float,
        er1: float, er2: float, d0_mm: float | None = None,
        richardson: bool = True) -> object:
    """双层悬置带线 εeff/Z0 裁判（TA-11「双层悬置变体」登记级）。

    腔 0..b（上下地=腔壁 PEC），双层基板以腔中面对称悬浮：总厚 h=h1+h2、
    z∈[b/2−h/2, b/2+h/2]，层界面 z=b/2−h/2+h1；零厚度带贴层界面 z 界。
    er2=er1 时与既有单层悬置带线族（quasistatic_fd.suspended_stripline_
    quasistatic）同物理——跨族互检锚（单测钉）。登记级：无模板注册、无
    设计链（分析面先行，综合链随真机批次另立）。"""
    import numpy as np

    from rfauto.core.quasistatic_fd import (
        _finish,
        concat_lines,
        energy_quasistatic,
        graded_lines,
        richardson_first_order,
        uniform_lines,
    )

    if w_mm <= 0 or b_mm <= 0 or h1_mm <= 0 or h2_mm <= 0:
        raise ValueError("双层悬置带线定义域：w>0、b>0、h1>0、h2>0")
    if er1 < 1.0 or er2 < 1.0:
        raise ValueError("双层悬置带线 εr1/εr2 须 ≥1")
    h = h1_mm + h2_mm
    if not h < b_mm:
        raise ValueError(
            f"双层悬置带线：层总厚 h={h:.4g}mm 须 < 腔高 b={b_mm:.4g}mm")
    d0 = d0_mm if d0_mm is not None else min(h1_mm, h2_mm) / 20.0
    z_lo = b_mm / 2.0 - h / 2.0
    z_mid = z_lo + h1_mm
    z_hi = z_lo + h

    def cap(eps_r_a: float, eps_r_b: float, d: float) -> tuple[float, int]:
        xm = max(8.0, 4.0 * b_mm, 3.0 * w_mm / 2.0)   # 远区外界越带缘（同上）
        xs = concat_lines(uniform_lines(0.0, w_mm / 2.0, d),
                          graded_lines(w_mm / 2.0, xm, d))
        zs = concat_lines(uniform_lines(0.0, z_lo, d),
                          uniform_lines(z_lo, z_mid, d),
                          uniform_lines(z_mid, z_hi, d),
                          uniform_lines(z_hi, b_mm, d))
        nx, nz = xs.size, zs.size
        eps = np.ones((nx - 1, nz - 1))
        zc = 0.5 * (zs[:-1] + zs[1:])
        eps[:, (zc > z_lo) & (zc < z_mid)] = eps_r_a
        eps[:, (zc >= z_mid) & (zc < z_hi)] = eps_r_b
        j_m = int(np.argmin(np.abs(zs - z_mid)))
        iw = int(np.argmin(np.abs(xs - w_mm / 2.0)))
        if abs(zs[j_m] - z_mid) > 1e-12 or abs(xs[iw] - w_mm / 2.0) > 1e-12:
            raise RuntimeError("双层悬置带线网格线未精确落在带缘/层界面")
        diri: dict[int, float] = {}
        for i in range(nx):                           # 腔壁双地
            diri[i * nz] = 0.0
            diri[i * nz + nz - 1] = 0.0
        for i in range(iw + 1):                       # 带 z=z_mid φ=1
            diri[i * nz + j_m] = 1.0
        return 4.0 * energy_quasistatic(xs, zs, eps, diri), nx * nz

    steps = (d0, d0 / 2.0) if richardson else (d0,)
    eps_v, cair_v, n_nodes = [], [], 0
    for d in steps:
        c_d, n_nodes = cap(er1, er2, d)
        c_a, _ = cap(1.0, 1.0, d)
        eps_v.append(c_d / c_a)
        cair_v.append(c_a)
    c_air = (richardson_first_order(cair_v[0], cair_v[1]) if richardson
             else cair_v[-1])
    return _finish(eps_v[-1] * c_air, c_air, d0, richardson,
                   eps_v[0], eps_v[-1], n_nodes)
