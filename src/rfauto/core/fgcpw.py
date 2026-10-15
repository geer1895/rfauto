"""真 CPW / 有限地 FGCPW 确定性内核（TA-9 批 Wave A 席 1）。

结构口径：基板上表面共面条带+两接地（**无底地**——与 cpw 模板的 CPWG
强制底地口径相区别，registry.py CPW 段注释自证），基板下方空气（域底
MUR），地**有限宽**（FGCPW；gnd→∞ 退化为经典 CPW）。

两层数字来源（#118/#300 纪律，逐条可溯）：

1. **文献闭式交叉参考** `fgcpw_gn_closed_form`：Ghione & Naldi,
   "Analytical Formulas for Coplanar Lines in Hybrid and Monolithic MICs,"
   Electron. Lett., vol. 20, no. 4, pp. 179-181, Feb. 1984——式 (1)-(3b)
   无底地口径（skrf.media.cpw.analyse_quasi_static 逐式对照源，backside-
   air 分支；本实现用 scipy ellipk 精确模数比，skrf 用 Hilberg 近似
   ellipa——小 k 端 ellipa 偏差可达 %级，大 k 端 ~0.1-0.5%，故两侧对拍
   只在设计点 k≈0.85-0.95 带 ≤1% 门）。

2. **设计链数字真值** `fgcpw_design_params`：2D 准静态 FD Laplace 裁判
   （core/quasistatic_fd.cpw_quasistatic，本批新增几何族）brentq 反解。
   裁判资格：求解器四文献锚已过（模块头）+ 新族两精确极限
   （k=1/√2 空气线 Z0=30π 逐位、h→∞ 半空间 εeff=(1+εr)/2）+ 对拍见下。

**文献闭式系统偏差如实登记（双因归因，ge9 审查 P1 勘误 2026-10-08）**：
有限厚开线共面槽场 G-N 闭式对 FD 裁判的偏差是**两个独立因子的叠加**——
① **椭圆积分约定错（已修）**：本模块旧 q 把模数 k 直传 scipy ellipk
（参数 m=k²），实算 K(√k)/K(√k′)，名义点贡献 εeff ~2.6pp/Z0 ~2.6pp
（skrf 第三方裁判实证：修正前 −2.69%/−2.60%、修正后 +0.00%/+0.05%
逐位回收）；② **#302 共形映射族真实近似残差（仍在账）**：修正后名义点
（w=4.3466/gap=0.2/gnd=4.0/h=0.508/εr=3.66）对 FD（有限地 4mm 同参）
仍余 εeff −3.99%、Z0 −1.01%（G-N 无穷地假设+部分电容映射族，与 CPS 批
Gupta/Ghione 结论同族）。历史账 −6.6%/−3.6%（修正前）中 εeff 四成/
Z0 七成系因子①，原"#302 同族"100% 归因不成立（#350-② 单侧误归因家族）。
**设计链仍以 FD 裁判为真值**，G-N 只作文献交叉参考不作设计式
（非 #118"自己的推导自证"：FD 与 G-N 是两条独立来源）。

近似级别：准静态（无色散）、零厚金属、地有限宽（gnd≥~2×(w/2+gap) 时
地效应 ≤2% FD 实测带，名义 gnd=4.0 处 +0.6%）、介质无损。
**W4-A/P4（2026-10-05）**：有限金属厚度修正档 `fgcpw_gn_closed_form_thickness`
（Wadell/Qucs 三源核对；#118 裁判=本批新增 core/quasistatic_fd.
cpw_finite_thickness_quasistatic，构成形态取 qucs——wcalc 基值改宽形态
与 FD 方向矛盾已登记；实测精度带见函数 docstring），零厚缺省路径零变化。
"""

from __future__ import annotations

import math

__all__ = ["fgcpw_design_params", "fgcpw_fd", "fgcpw_gn_closed_form",
           "fgcpw_gn_closed_form_thickness"]


def _q_ratio(k: float) -> float:
    """K(k)/K(k')（第一类完全椭圆积分数比，scipy 参数 m=k² 约定单源）。

    ge9 审查 P1（2026-10-08）单源化：旧实现两处拷贝把模数 k 直传
    scipy.special.ellipk（其参数是 m=k² 非模数 k），实算 K(√k)/K(√k')，
    与 Ghione-Naldi 的 K(k)/K(k') 是两个不同函数（k=0.92 处 mpmath 高精度
    仲裁 1.4527389 vs 错约定 1.5144572）。正确约定=仓内四处先例
    （calc_families/rf_line._kk_ratio/_cpwg_ri、sicl_line、aperture_coupling）：
    K(k)=ellipk(k²)、K'(k)=ellipk(1−k²)。本模块仅此一份实现，两处消费。
    """
    from scipy.special import ellipk

    return float(ellipk(k * k)) / float(ellipk(1.0 - k * k))


def fgcpw_fd(w_mm: float, gap_mm: float, h_mm: float, eps_r: float,
             gnd_mm: float | None = None) -> object:
    """CPW/FGCPW FD 裁判单点（core/quasistatic_fd 薄再导出，#116 零副本）。

    gnd_mm=None 为无穷地（G-N 闭式同口径）；>0 为有限地（FGCPW）。
    返回 QuasiStaticResult。
    """
    from rfauto.core.quasistatic_fd import cpw_quasistatic

    return cpw_quasistatic(float(w_mm), float(gap_mm), float(h_mm),
                           float(eps_r), gnd_mm=gnd_mm)


def fgcpw_gn_closed_form(w_mm: float, gap_mm: float, h_mm: float,
                         eps_r: float) -> dict[str, float]:
    """Ghione-Naldi 1984 式 (1)-(3b)（无底地、有限厚基板、无穷地）。

    a=w（条带宽）、b=w+2g（全几何口径）；k1=a/b；k2=sinh(πa/4h)/
    sinh(πb/4h)；q=K(k)/K(k')（**模数制比值**，本模块单源 `_q_ratio`：
    scipy ellipk 参数 m=k²，ge9 P1 勘误——旧实现直传模数 k 实算
    K(√k)/K(√k') 约定错；#118 独立仲裁=mpmath 高精度 K/K′ 与 skrf
    ellipa 双源，名义点修正后与 skrf 差 εeff +0.00%/Z0 +0.05%）；
    εeff = 1+(εr−1)/2·q2/q1（式 2/3b）；Z0 = η0/(4·q1·√εeff)（式 1）。
    h→∞ 时 k2→k1 → εeff=(1+εr)/2（回收锚）。q(k) 单调、Z0 随 w 单调
    递减（单测钉）。
    """
    w = float(w_mm)
    g = float(gap_mm)
    h = float(h_mm)
    er = float(eps_r)
    for name, v in (("w_mm", w), ("gap_mm", g), ("h_mm", h)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"fgcpw_gn: {name} 必须为正有限数，得到 {v!r}")
    if not (math.isfinite(er) and er >= 1.0):
        raise ValueError(f"fgcpw_gn: er 须 ≥1，得到 {er!r}")
    a = w
    b = w + 2.0 * g
    k1 = a / b
    if not 0.0 < k1 < 1.0:
        raise ValueError(f"fgcpw_gn: 模数 k1={k1!r} 越域 (0,1)")
    k2 = math.sinh(math.pi * a / (4.0 * h)) / math.sinh(math.pi * b / (4.0 * h))
    k2 = min(max(k2, 0.0), 1.0 - 1e-12)

    q1, q2 = _q_ratio(k1), _q_ratio(k2)
    eps_eff = 1.0 + (er - 1.0) / 2.0 * (q2 / q1)
    z0 = 376.730313668 / (4.0 * q1 * math.sqrt(eps_eff))
    return {"eps_eff": eps_eff, "z0_ohm": z0, "k1": k1, "k2": k2,
            "q1": q1, "q2": q2}


def fgcpw_design_params(z0_ohm: float = 50.0,
                        gap_mm: float = 0.2,
                        gnd_mm: float = 4.0,
                        h_mm: float = 0.508,
                        er: float = 3.66,
                        line_len_mm: float = 40.0,
                        f0_ghz: float = 2.5) -> dict[str, float]:
    """设计链：目标 Z0 → 条带宽 w（FD 裁判 brentq 反解，含有限地 gnd 同参
    ——名义点自洽）。Z0 随 w 单调递减（单测网格钉）。单次反解 ~15-25s
    （richardson 双档；一次性综合入口，非渲染路径）。"""
    from scipy.optimize import brentq

    from rfauto.core.quasistatic_fd import cpw_quasistatic

    z_t = float(z0_ohm)
    if not (math.isfinite(z_t) and z_t > 0.0):
        raise ValueError(f"fgcpw: z0_ohm 须为正有限数，得到 {z0_ohm!r}")
    for name, v in (("gap_mm", gap_mm), ("gnd_mm", gnd_mm), ("h_mm", h_mm)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"fgcpw: {name} 须为正有限数，得到 {v!r}")
    if not (math.isfinite(er) and er >= 1.0):
        raise ValueError(f"fgcpw: er 须 ≥1，得到 {er!r}")
    gn = fgcpw_gn_closed_form(1.0, gap_mm, h_mm, er)   # k1=1/(1+2g) 域自检
    del gn

    def objective(w_mm: float) -> float:
        r = cpw_quasistatic(w_mm, float(gap_mm), float(h_mm), float(er),
                            gnd_mm=float(gnd_mm))
        return r.z0_ohm - z_t

    lo = 0.5 * (gap_mm + gnd_mm)
    # 括号自适应倍增（w 域上限=大网格节点数，固定大 hi 会让端点求解 O(GB)
    # ——实测 hi=210mm 端点即 ~500s；倍增至首次 f(hi)<0 封顶 4 次）
    hi = 4.0 * (gap_mm + gnd_mm)
    z_lo = objective(lo)
    z_hi = objective(hi)
    _n_double = 0
    while z_hi > 0.0 and _n_double < 4:
        hi *= 2.0
        z_hi = objective(hi)
        _n_double += 1
    if z_lo < 0.0 or z_hi > 0.0:
        raise ValueError(
            f"目标 {z_t}Ω 超出 FGCPW 可达范围 [{z_hi + z_t:.1f}, "
            f"{z_lo + z_t:.1f}]Ω（w∈[{lo:.4f}, {hi:.4f}]mm 括号扫描；"
            "加大 gap/gnd 可下调 Z0 下界）")
    w_mm = float(brentq(objective, lo, hi, xtol=1e-9))
    r = cpw_quasistatic(round(w_mm, 4), float(gap_mm), float(h_mm), float(er),
                        gnd_mm=float(gnd_mm))
    eps_eff = float(r.eps_eff)
    lam_g_mm = 299.792458 / (float(f0_ghz) * math.sqrt(eps_eff))
    gn_nom = fgcpw_gn_closed_form(round(w_mm, 4), gap_mm, h_mm, er)
    return {
        "w_mm": round(w_mm, 4),
        "z0_actual_ohm": round(float(r.z0_ohm), 3),
        "eps_eff": round(eps_eff, 5),
        "lambda_g_mm": round(lam_g_mm, 4),
        "line_len_mm": float(line_len_mm),
        "gap_mm": float(gap_mm),
        "gnd_mm": float(gnd_mm),
        "er": float(er),
        # 文献交叉参考偏差如实带出（#122：不静默）
        "gn_eps_eff_dev_pct": round(100.0 * (gn_nom["eps_eff"] / eps_eff - 1.0), 2),
        "gn_z0_dev_pct": round(
            100.0 * (gn_nom["z0_ohm"] / float(r.z0_ohm) - 1.0), 2),
    }


def fgcpw_gn_closed_form_thickness(w_mm: float, gap_mm: float, h_mm: float,
                                    eps_r: float, t_mm: float
                                    ) -> dict[str, float]:
    """G-N 闭式 + 有限金属厚度修正档（W4-A/P4，opt-in；零厚缺省路径零变化）。

    式面（#1c 三源核对，2026-10-05）：

    - Δ = (1.25·t/π)·(1+ln(4π·w/t))——Wadell《Transmission Line Design
      Handbook》§3.4.1（wcalc coplanar.c 式 (3.4.1.8)/(3.4.1.9) 逐式注记）
      与 Qucs 技术文档 §"Coplanar waveguides—Effects of metalization
      thickness"（Δ/We/s_e 式）及 qucs-transcalc coplanar.cpp 三源同值；
    - 修正模数 k_e = W_e/(W_e+2·s_e)（W_e=w+Δ、s_e=gap−Δ；Qucs 文档同式
      给出 ≈k₁+(1−k₁²)Δ/(2·gap) 一阶恒等形态），Z0 = η0/(4·q(k_e)·√εeff_t)；
    - εeff_t = εeff₀ − 0.7·(εeff₀−1)·(t/gap)/(q(k₁)+0.7·t/gap)（Qucs 文档
      /qucs-transcalc/wcalc 同式，0.7 为该文献族经验项）。

    **构成形态裁判（#118 双源互斥，数字真值仲裁）**：wcalc/Wadell 转录
    把修正宽代进有限厚比 k₂（sinh 比分子分母同改），预测 εeff 随 t 增
    （与物理"厚金属抬侧壁、缝场入空气"方向相反）；qucs-transcalc 构成
    （基值零厚几何 + k_e 修 Z0 + 0.7 项修 εeff）预测 εeff 随 t 降。本仓
    新落地的有限厚 FD 数字裁判（core/quasistatic_fd.
    cpw_finite_thickness_quasistatic，t→0⁺ 与零厚族连续已钉）实测方向=
    随 t 降——**本函数取 qucs 构成**，wcalc 基值改宽形态如实登记不采信。

    有效域：t>0、w>2t（Δ 式定义域）、gap>Δ（修正后缝宽须正），
    越域显式 ValueError 不外推。t→0⁺ 连续性：d→0、k_e→k₁、εeff_t→εeff₀
    （与 fgcpw_gn_closed_form 逐位衔接，连续性钉在测试）。

    **实测精度带（vs 本仓有限厚 FD 裁判，ge9 P1 修后重标 2026-10-08，
    名义基板 er=3.66/h=0.508/gnd=4.0）**：修正方向与 FD 全域一致（εeff/Z0
    随 t 同降）；厚度响应（偏置对消口径）在 t/gap≈1.75% 时闭式/FD≈1.30×/
    2.23×（εeff/Z0），t/gap≈8.75% 时≈1.65×/2.89×（旧带 1.25×/2.5×、2×/4×
    在错约定基线上标定，修后实测重登记）——一阶扰动式幅值随 t/gap 恶化，
    定量可靠带 t/gap ≲2%（如实登记）；重标钉在 test_w4_a_sm_core。
    零厚 G-N 对 FD 的系统偏差为**双因**——椭圆积分约定错（已修，本模块
    `_q_ratio` 勘误注记）+ #302 共形映射族真实残差（修正后名义点仍余
    εeff −3.99%/Z0 −1.01%，模块头双因归因节），设计链仍以 FD 裁判为真值
    （模块头既有立场）。
    """
    w = float(w_mm)
    g = float(gap_mm)
    h = float(h_mm)
    er = float(eps_r)
    t = float(t_mm)
    for name, v in (("w_mm", w), ("gap_mm", g), ("h_mm", h)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"fgcpw_thickness: {name} 必须为正有限数，得到 {v!r}")
    if not (math.isfinite(er) and er >= 1.0):
        raise ValueError(f"fgcpw_thickness: er 须 ≥1，得到 {er!r}")
    if not (math.isfinite(t) and t > 0.0):
        raise ValueError(f"fgcpw_thickness: t_mm 必须为正有限数，得到 {t_mm!r}")
    if not w > 2.0 * t:
        raise ValueError(
            f"w={w}mm ≤ 2t={2.0 * t}mm：Δ 增宽式无定义域（细线厚金属），不外推")

    a = w
    b = w + 2.0 * g
    k1 = a / b
    if not 0.0 < k1 < 1.0:
        raise ValueError(f"fgcpw_thickness: 模数 k1={k1!r} 越域 (0,1)")
    d = (1.25 * t / math.pi) * (1.0 + math.log(4.0 * math.pi * w / t))
    w_e = w + d
    s_e = g - d
    if s_e <= 0.0:
        raise ValueError(
            f"gap={g}mm 被厚度修正 Δ={d * 1e3:.4f}mm 吃光（修正后缝宽非正）"
            "——厚金属窄缝口径越出准静态修正式有效域，不外推")
    k_e = w_e / (w_e + 2.0 * s_e)
    if not 0.0 < k_e < 1.0:
        raise ValueError(f"fgcpw_thickness: 修正模数 k_e={k_e!r} 越域 (0,1)")
    k2 = math.sinh(math.pi * a / (4.0 * h)) / math.sinh(math.pi * b / (4.0 * h))
    k2 = min(max(k2, 0.0), 1.0 - 1e-12)
    q1, q2, qe = _q_ratio(k1), _q_ratio(k2), _q_ratio(k_e)
    eps_eff0 = 1.0 + (er - 1.0) / 2.0 * (q2 / q1)
    eps_eff_t = eps_eff0 - 0.7 * (eps_eff0 - 1.0) * (t / g) / (q1 + 0.7 * t / g)
    z0 = 376.730313668 / (4.0 * qe * math.sqrt(eps_eff_t))
    return {"eps_eff": eps_eff_t, "z0_ohm": z0, "k1": k1, "k_e": k_e,
            "delta_w_mm": d, "eps_eff_zero_t": eps_eff0}
