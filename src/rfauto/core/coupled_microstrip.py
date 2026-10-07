"""耦合微带 / 抽头谐振器闭式内核（core 叶层；WP2.3 hairpin 收口 ⑦ 升格，2026-09-16）。

本模块由 adapters/openems_templates.py 的 WP2.3 hairpin 段**原样下沉**（函数体
与 docstring 逐字保留，仅常量改为模块级公开名）；adapters 经再导出零改动消费
（#116：adapters 不留本地遮蔽副本）。数值只在确定性内核（铁律 7）——闭式部分
不含任何经验常数，全部为公开闭式：

- 偶/奇模阻抗：Kirschning-Jansen 1984 准静态闭式（零厚/无盖口径），单线量
  取 skrf Hammerstad-Jensen 正向（core/synthesis.forward_z0），与 Qucs/transcalc
  的 c_microstrip.cpp 零厚无盖分支逐式对应；
- **频变偶/奇 εeff 色散层（W4-A/P1，2026-10-05）**：
  `coupled_microstrip_eps_disp`——KJ 1984 论文式 (2)-(7)（fn=f·h 归一频率、
  Getsinger 型 εeff,e/o(f)=εr−(εr−εeff,e/o(0))/(1+F_e/o)、P1-P15 色散系数），
  式面与三独立源逐式核对（Wcalc libwcalc/coupled_microstrip.c 逐式注释实现、
  Qucs 技术文档 §11.8 式 (11.89)-(11.155)、qucs-core mscoupled.cpp；P1 加式
  形态以论文原文全文（Scribd 影印）定谳——qucs-core 的 p1 乘式形态系转录
  误，报告有账）；Jansen 有限厚修正 opt-in（thickness_mm，Qucs tech doc
  式 (11.180)-(11.183)：ΔW 按 Hammerstad-Bekkadal 双支、W_t,e/W_t,o 与
  Δt=2th/(s·εr)，适用 s>20t）；阻抗色散（论文式 (10)/(11)）**不实现**——
  wcalc 与 qucs-core 在 Q18 常数上互斥（2.13 vs 2.31）且原文不可达，
  #1c/#122 如实登记不解锁。
- 平行耦合半波谐振器耦合系数 k=(Z0e−Z0o)/(Z0e+Z0o)（Hong §5.4）及 brentq 反解；
- 抽头外部 Q：Q_e=(π/2)(Z0/Z_r)sec²(πτ)（本仓派生，单测以精确分布参数 Y_res(ω)
  数值微分独立校核，#118）及反解 τ=arccos(√((π/2)(Z0/Z_r)/Q_e))/π；
- 展开半波长臂长 λg/2=c/(2·f0·√εeff)（Pozar；与 core/thermo_mech 同式）。

**hairpin 结构经验修正 c(gap)（W4④，2026-09-17）**：并排同向 U 形 hairpin 的级间耦合
不是均匀无限平行耦合线——相邻臂电流反向、两端开路、U 弯邻近，电/磁耦合部分相消，
EM 有效 k_EM 显著低于 KJ 平行线 k_KJ。闭式本身已由独立来源核实无误（NGSolve 2D 准静态
偶/奇模 k_NG/k_KJ=1.003/1.018/1.049 @gap 0.8/1.1328/1.6，runs/hairpin_kgap/
offline_kj_vs_ngsolve.json），故修正只作用于 hairpin 通道、显式 opt-in
（structural_correction=True），常数 HAIRPIN_KGAP_TABLE_MM 全部出自本战役 openEMS
N=2 弱抽头双谐振器真机（scripts/hairpin_q_extract.py --kgap-analyze 可复算，铁律 7），
适用域见 HAIRPIN_KGAP_CALIB，域外不外推（设计反解 raise；fake 前向可显式 clamp）。
精度档案：knowledge/precision_profiles.yaml#coupled_microstrip（行为=REFUSE，last_verified=2026-09-17）。
"""
from __future__ import annotations

import math

C_MM_GHZ = 299.792458          # mm·GHz（真空光速，与 core 同口径）
ZF0_OHM = 376.730313668        # 自由空间波阻抗 Ω
HAIRPIN_50OHM_W_MM = 1.1134    # rogers4350b h=0.508 er=3.66 的 50Ω 线宽（HJ）
_HAIRPIN_W_REF_ER = 3.66       # 上行常数唯一有效标定档（XC-W 跨档守卫参考面）
_HAIRPIN_W_REF_H_MM = 0.508


def _hairpin_default_w_mm(w_mm: float | None, er: float,
                          h_mm: float) -> float:
    """XC-W 跨档缺省守卫：HAIRPIN_50OHM_W_MM 只对标定档 (3.66, 0.508) 有效。

    该常数按 rogers4350b h=0.508/er=3.66 HJ 精算——跨档（异基板/异厚）时
    它不是 50Ω 线宽（偏差可达 2-3×），静默缺省=静默错几何。w 显式传参放行；
    缺省仅同档生效，跨档 ValueError 指路 synthesis 50Ω 综合。
    """
    if w_mm is not None:
        return float(w_mm)
    if (math.isclose(er, _HAIRPIN_W_REF_ER, rel_tol=1e-9)
            and math.isclose(h_mm, _HAIRPIN_W_REF_H_MM, rel_tol=1e-9)):
        return HAIRPIN_50OHM_W_MM
    raise ValueError(
        f"w_mm 缺省仅在标定档 er=3.66/h=0.508mm 有效（实得 er={er}/h={h_mm}mm）"
        "——跨档请显式传 w_mm 或按该档现场综合 50Ω 线宽（XC-W 单源化口径）")

# ── hairpin 级间耦合结构经验修正表 c(gap)=k_EM/k_KJ（W4④ 本战役真机，2026-09-17）──
# 口径（HAIRPIN_KGAP_CALIB）：rogers4350b h=0.508/er=3.66、w=1.1117（50Ω@2.5GHz）、
# arm_gap=3.0、arm_len=36.7799、τ=0.43 双抽头 N=2、openEMS 0.4mm 网格、KJ 在 2.5GHz 求值；
# 提取=有耗 4×4 耦合矩阵模型峰电平反演（k<0.03）/全线形拟合（k≥0.03），Q_e/Q_u 取 B1
# 同 τ 单腔实测 34.691/236.347。表为 (gap_mm, c) 升序，内插=分段线性；域=[首,末] gap。
HAIRPIN_KGAP_TABLE_MM: tuple[tuple[float, float], ...] = (
    # (gap_mm, c)：runs/hairpin_kgap/kgap_curve.json（2026-09-17，N=2 τ0.43，openEMS 0.4mm）
    (0.5, 0.12108771661717306),      # kgap2_g0500：峰 −3.79dB，宽 66.0/65.5MHz，k_EM 0.014659
    (0.65, 0.16083017395381485),     # kgap2_g0650：峰 −3.49dB，宽 69.0/66.5MHz，k_EM 0.015457
    (0.8, 0.19408963003474614),      # kgap2_g0800：峰 −3.62dB，宽 66.0/66.0MHz，k_EM 0.015112
    (1.1328, 0.25765314206246065),   # kgap2_g11328：峰 −4.39dB，宽 63.0/62.5MHz，k_EM 0.013273
    # gap 1.6 排除：端口健康 FAIL（max|S11| 1.067、144 点越界）、宽 93 vs 55.5MHz 门不过
)
HAIRPIN_KGAP_CALIB: dict[str, object] = {
    "w_mm": 1.1117, "h_mm": 0.508, "er": 3.66, "f0_ghz": 2.5, "arm_gap_mm": 3.0,
    "arm_len_mm": 36.7799, "tap_frac": 0.43, "order": 2, "mesh_mm": 0.4,
    "qe_em": 34.69064166747507, "q_u": 236.34736862539347,
    "source": "runs/hairpin_kgap/kgap_curve.json（scripts/hairpin_q_extract.py --kgap-analyze）",
    "note": "hairpin 结构经验修正（非闭式），仅同口径几何可用；域外不外推",
}


def hairpin_kgap_domain_mm() -> tuple[float, float]:
    """c(gap) 标定域 [gap_min, gap_max]（表空则抛 ValueError=未标定）。"""
    if not HAIRPIN_KGAP_TABLE_MM:
        raise ValueError("hairpin c(gap) 结构修正未标定（HAIRPIN_KGAP_TABLE_MM 为空）")
    return float(HAIRPIN_KGAP_TABLE_MM[0][0]), float(HAIRPIN_KGAP_TABLE_MM[-1][0])


def hairpin_kgap_correction(gap_mm: float, *, extrapolate: str = "raise") -> float:
    """hairpin 级间耦合结构修正 c(gap)=k_EM/k_KJ（分段线性内插标定表）。

    extrapolate="raise"（默认，设计反解口径）：域外 ValueError；"clamp"：域外取端点值
    （fake 前向裁判显式假设，非外推口径，调用方须自知）。
    """
    if extrapolate not in ("raise", "clamp"):
        raise ValueError("extrapolate 须为 raise|clamp")
    lo, hi = hairpin_kgap_domain_mm()
    g = float(gap_mm)
    if not lo <= g <= hi:
        if extrapolate == "clamp":
            g = min(max(g, lo), hi)
        else:
            raise ValueError(
                f"gap={gap_mm}mm 超出 hairpin c(gap) 标定域 [{lo}, {hi}]mm（域外不外推）")
    xs = [float(p[0]) for p in HAIRPIN_KGAP_TABLE_MM]
    ys = [float(p[1]) for p in HAIRPIN_KGAP_TABLE_MM]
    for i in range(len(xs) - 1):
        if xs[i] <= g <= xs[i + 1]:
            span = xs[i + 1] - xs[i]
            return ys[i] if span == 0.0 else ys[i] + (ys[i + 1] - ys[i]) * (g - xs[i]) / span
    return ys[-1]


def hairpin_arm_len_mm(f0_ghz: float, w_mm: float,
                       er: float = 3.66, h_mm: float = 0.508) -> float:
    """展开半波长臂长 λg/2（mm）= c/(2·f0·√εeff)，εeff 走 skrf HJ（内核口径）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="hairpin", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    _, eps_eff = forward_z0(float(w_mm), float(f0_ghz), stackup)
    return C_MM_GHZ / (2.0 * float(f0_ghz) * math.sqrt(eps_eff))


def coupled_microstrip_even_odd_ohm(
    w_mm: float, s_mm: float, freq_ghz: float,
    er: float = 3.66, h_mm: float = 0.508,
    *, single: tuple[float, float] | None = None,
) -> tuple[float, float, float, float]:
    """耦合微带准静态偶/奇模阻抗（Kirschning-Jansen 1984 闭式；零厚/无盖）。

    single：预计算的 (Z0_single, εeff_single)（skrf HJ 正向量，仅依赖 w/f）。
    反解器在同一 w 下高频调用时传入可跳过重复 skrf 构造（纯加速，不改口径）。

    Returns:
        (Z0e, Z0o, εeff_even, εeff_odd)，单位 Ω。

    口径：单线量（Z0_single/εeff_single）取 skrf Hammerstad-Jensen 正向
    （core/synthesis.forward_z0），耦合修正取 KJ 偶/奇模填充因子 + Q 因子族；
    与 Qucs/transcalc 的 c_microstrip.cpp 零金属厚、无盖分支逐式对应
    （Jansen 1978 厚/盖修正项在本口径下恒为 0）。
    """
    from rfauto.core.synthesis import Stackup, forward_z0

    w = float(w_mm)
    s = float(s_mm)
    h = float(h_mm)
    e_r = float(er)
    if w <= 0.0 or s <= 0.0 or h <= 0.0:
        raise ValueError("耦合微带几何参数须 >0")
    if single is None:
        stackup = Stackup(name="hairpin", epsilon_r=e_r, thickness_mm=h)
        z0_s, ere_s = forward_z0(w, float(freq_ghz), stackup)
    else:
        z0_s, ere_s = float(single[0]), float(single[1])
    u = w / h                       # 归一化线宽（零厚：u_t = u）
    g = s / h                       # 归一化缝宽

    # ── 偶模：填充因子 + Q 因子族 ──
    v = u * (20.0 + g * g) / (10.0 + g * g) + g * math.exp(-g)
    v3 = v ** 3
    v4 = v3 * v
    a_e = (1.0 + math.log((v4 + v * v / 2704.0) / (v4 + 0.432)) / 49.0
           + math.log(1.0 + v3 / 5929.741) / 18.7)
    b_e = 0.564 * ((e_r - 0.9) / (e_r + 3.0)) ** 0.053
    q_inf_e = (1.0 + 10.0 / v) ** (-a_e * b_e)
    ere_e = 0.5 * (e_r + 1.0) + 0.5 * (e_r - 1.0) * q_inf_e
    q1 = 0.8695 * u ** 0.194
    q2 = 1.0 + 0.7519 * g + 0.189 * g ** 2.31
    q3 = (0.1975 + (16.6 + (8.4 / g) ** 6.0) ** -0.387
          + math.log(g ** 10.0 / (1.0 + (g / 3.4) ** 10.0)) / 241.0)
    q4 = 2.0 * q1 / (q2 * (math.exp(-g) * u ** q3
                           + (2.0 - math.exp(-g)) * u ** (-q3)))
    z0e = (z0_s * math.sqrt(ere_s / ere_e)
           / (1.0 - math.sqrt(ere_s) * q4 * z0_s / ZF0_OHM))

    # ── 奇模：填充因子 + Q 因子族 ──
    b_o = 0.747 * e_r / (0.15 + e_r)
    c_o = b_o - (b_o - 0.207) * math.exp(-0.414 * u)
    d_o = 0.593 + 0.694 * math.exp(-0.562 * u)
    q_inf_o = math.exp(-c_o * g ** d_o)
    a_o = 0.7287 * (ere_s - 0.5 * (e_r + 1.0)) * (1.0 - math.exp(-0.179 * u))
    ere_o = (0.5 * (e_r + 1.0) + a_o - ere_s) * q_inf_o + ere_s
    q5 = 1.794 + 1.14 * math.log(1.0 + 0.638 / (g + 0.517 * g ** 2.43))
    q6 = (0.2305 + math.log(g ** 10.0 / (1.0 + (g / 5.8) ** 10.0)) / 281.3
          + math.log(1.0 + 0.598 * g ** 1.154) / 5.1)
    q7 = (10.0 + 190.0 * g * g) / (1.0 + 82.3 * g * g * g)
    q8 = math.exp(-6.5 - 0.95 * math.log(g) - (g / 0.15) ** 5.0)
    q9 = math.log(q7) * (q8 + 1.0 / 16.5)
    q10 = (q2 * q4 - q5 * math.exp(math.log(u) * q6 * u ** (-q9))) / q2
    z0o = (z0_s * math.sqrt(ere_s / ere_o)
           / (1.0 - math.sqrt(ere_s) * q10 * z0_s / ZF0_OHM))
    return z0e, z0o, ere_e, ere_o


# ── KJ 1984 频变偶/奇 εeff 色散层（W4-A/P1）────────────────────────────────────
#: KJ 1984 式 (2)：归一频率 fn = f[GHz]·h[mm]（论文口径，Wcalc 1e-6·f[Hz]·h[m] 同值）
_KJ_FN_SCALE = 1.0
#: 色散式精度域（论文 p.85 经 Wcalc/qucs 转述）：fn≤25 → 1.4% 精度声明
_KJ_FN_MAX = 25.0
_KJ_U_RANGE = (0.1, 10.0)     # 论文式 (1) 有效域 W/H
_KJ_G_RANGE = (0.1, 10.0)     # 论文式 (1) 有效域 S/H
_KJ_ER_RANGE = (1.0, 18.0)    # 论文式 (1) 有效域 εr


def _kj_dispersion_fe_fo(u: float, g: float, fn: float, er: float) -> tuple[float, float]:
    """KJ 1984 式 (6)/(7)：偶/奇模色散函数 F_e、F_o（式 (5) Getsinger 型）。

    常数面逐式来源（#1c 三源核对，2026-10-05）：
    - Wcalc-1.1 libwcalc/coupled_microstrip.c（逐式注释引用 MTT-32(1):83-90
      式号，含论文勘误注记）；
    - Qucs 技术文档 §"Parallel coupled microstrip lines"（式 11.100-11.117
      同一系数面）；
    - 论文原文 P1 加式形态（Scribd 影印全文核对；qucs-core mscoupled.cpp 的
      p1 乘式形态与原文不符，系该实现的转录误——三源中两源+原文定谳）。
    """
    # 偶模式 (6)：P1..P7
    p1 = (0.27488 + (0.6315 + 0.525 / (1.0 + 0.0157 * fn) ** 20.0) * u
          - 0.065683 * math.exp(-8.7513 * u))
    p2 = 0.33622 * (1.0 - math.exp(-0.03442 * er))
    p3 = 0.0363 * math.exp(-4.6 * u) * (1.0 - math.exp(-(fn / 38.7) ** 4.97))
    p4 = 1.0 + 2.751 * (1.0 - math.exp(-(er / 15.916) ** 8.0))
    p5 = 0.334 * math.exp(-3.3 * (er / 15.0) ** 3.0) + 0.746
    p6 = p5 * math.exp(-(fn / 18.0) ** 0.368)
    p7 = (1.0 + 4.069 * p6 * g ** 0.479
          * math.exp(-1.347 * g ** 0.595 - 0.17 * g ** 2.5))
    f_e = p1 * p2 * ((p3 * p4 + 0.1844 * p7) * fn) ** 1.5763
    # 奇模式 (7)：P8..P15（P12/P15 含 |·|，论文口径）
    p8 = 0.7168 * (1.0 + 1.076 / (1.0 + 0.0576 * (er - 1.0)))
    p9 = (p8 - 0.7913 * (1.0 - math.exp(-(fn / 20.0) ** 1.424))
          * math.atan(2.481 * (er / 8.0) ** 0.946))
    p10 = 0.242 * (er - 1.0) ** 0.55
    p11 = 0.6366 * (math.exp(-0.3401 * fn) - 1.0) * math.atan(1.263 * (u / 3.0) ** 1.629)
    p12 = p9 + (1.0 - p9) / (1.0 + 1.183 * u ** 1.376)
    p13 = 1.695 * p10 / (0.414 + 1.605 * p10)
    p14 = 0.8928 + 0.1072 * (1.0 - math.exp(-0.42 * (fn / 20.0) ** 3.215))
    p15 = abs(1.0 - 0.8928 * (1.0 + p11) * p12
              * math.exp(-p13 * g ** 1.092) / p14)
    f_o = p1 * p2 * ((p3 * p4 + 0.1844) * fn * p15) ** 1.5763
    return f_e, f_o


def _jansen_thickness_widths(w_mm: float, s_mm: float, h_mm: float,
                             er: float, t_mm: float) -> tuple[float, float]:
    """Jansen 有限厚修正宽（Qucs tech doc 式 (11.180)-(11.183)，qucs-core
    mscoupled.cpp 同式实现）：返回 (W_t,e, W_t,o)。

    ΔW 按 Hammerstad-Bekkadal 双支（2t<W≤h/2π: ln(4πW/t)；W>h/2π 且
    h/2π>2t: ln(2h/t)）；Δt=2·t·h/(s·εr)；适用域 s>20t（原文 s≫2t，
    qucs 实现为 s>10·(2t)，本仓同取）。域外显式 ValueError 不外推。
    """
    if t_mm <= 0.0:
        raise ValueError("thickness_mm 须 >0（零厚直接走准静态口径）")
    if s_mm <= 20.0 * t_mm:
        raise ValueError(
            f"s/h={s_mm / h_mm:.4g} 越出 Jansen 厚度修正适用域（须 s>20t，"
            f"实得 s={s_mm}mm ≤ 20t={20.0 * t_mm}mm）——厚耦合缝口径需回原文"
            "重推，不外推")
    u = w_mm / h_mm
    two_t_over_h = 2.0 * t_mm / h_mm
    if u >= 1.0 / (2.0 * math.pi) and 1.0 / (2.0 * math.pi) > two_t_over_h:
        d_w = t_mm * (1.0 + math.log(2.0 * h_mm / t_mm)) / math.pi
    elif w_mm > 2.0 * t_mm:
        d_w = t_mm * (1.0 + math.log(4.0 * math.pi * w_mm / t_mm)) / math.pi
    else:
        raise ValueError(
            f"W={w_mm}mm ≤ 2t={2.0 * t_mm}mm：Hammerstad-Bekkadal 增宽式"
            "无定义域（细线厚金属），不外推")
    d_t = 2.0 * t_mm * h_mm / (s_mm * er)
    w_te = w_mm + d_w * (1.0 - 0.5 * math.exp(-0.69 * d_w / d_t))
    w_to = w_te + d_t
    return w_te, w_to


def coupled_microstrip_eps_disp(
    w_mm: float, s_mm: float, freq_ghz: float,
    er: float = 3.66, h_mm: float = 0.508,
    *, thickness_mm: float | None = None,
) -> tuple[float, float, float, float]:
    """耦合微带频变偶/奇 εeff（Kirschning-Jansen 1984 式 (2)-(7)；W4-A/P1）。

    静态锚：式 (3)/(4) 准静态偶/奇 εeff（与 coupled_microstrip_even_odd_ohm
    同式面，零厚口径取 skrf HJ 单线量；thickness_mm 有限厚时按 Jansen 修正
    宽 W_t,e/W_t,o 分道取 u_e/u_o，单线量同步取修正宽下的 skrf HJ）；频变：
    式 (5) Getsinger 型 εeff(f)=εr−(εr−εeff(0))/(1+F)，F_e/F_o 由式 (6)/(7)
    P1-P15 系数面给出。

    Returns:
        (εeff_even(f), εeff_odd(f), εeff_even(0), εeff_odd(0))。

    有效域（论文式 (1)+p.85，域外显式 ValueError 不外推）：0.1≤u≤10、
    0.1≤g≤10、1≤εr≤18、fn=f[GHz]·h[mm]≤25（1.4% 精度声明）；
    thickness_mm 须 s>20t（Jansen 修正域）。

    精度档案（#118 双源）：论文精度声明（色散 ≤1.4%、静态 ≤0.7%/0.5%）+
    既有 openEMS hairpin 锚基础设施（P-KJ-EVEN 静态锚再标定可直接复用本
    函数的静态锚通道）；f→0 连续性极限逐位回到准静态值（连续性钉）。
    阻抗色散（论文式 (10)/(11)）不实现（Q18 常数双源互斥，见模块头）。
    """
    from rfauto.core.synthesis import Stackup, forward_z0

    w = float(w_mm)
    s = float(s_mm)
    h = float(h_mm)
    e_r = float(er)
    f_ghz = float(freq_ghz)
    if w <= 0.0 or s <= 0.0 or h <= 0.0:
        raise ValueError("耦合微带几何参数须 >0")
    if f_ghz < 0.0:
        raise ValueError("freq_ghz 须 ≥0")
    if not (_KJ_ER_RANGE[0] <= e_r <= _KJ_ER_RANGE[1]):
        raise ValueError(
            f"εr={e_r} 越出 KJ 1984 式 (1) 有效域 {_KJ_ER_RANGE}（域外不外推）")
    if thickness_mm is not None:
        w_e, w_o = _jansen_thickness_widths(w, s, h, e_r, float(thickness_mm))
    else:
        w_e, w_o = w, w
    u_e = w_e / h
    u_o = w_o / h
    g = s / h
    for tag, uu in (("偶", u_e), ("奇", u_o)):
        if not (_KJ_U_RANGE[0] <= uu <= _KJ_U_RANGE[1]):
            raise ValueError(
                f"{tag}模修正宽比 u={uu:.4g} 越出 KJ 1984 有效域 "
                f"{_KJ_U_RANGE}（域外不外推）")
    if not (_KJ_G_RANGE[0] <= g <= _KJ_G_RANGE[1]):
        raise ValueError(
            f"g={g:.4g} 越出 KJ 1984 式 (1) 有效域 {_KJ_G_RANGE}（域外不外推）")
    fn = f_ghz * h * _KJ_FN_SCALE
    if fn > _KJ_FN_MAX:
        raise ValueError(
            f"fn=f·h={fn:.4g} 超出 KJ 1984 色散式精度域（fn≤{_KJ_FN_MAX:g}，"
            "论文 p.85 的 1.4% 精度声明仅覆盖该域）——域外不外推")

    stackup = Stackup(name="hairpin", epsilon_r=e_r, thickness_mm=h)
    # 静态偶模：式 (3)（HJ 型填充因子，V 代 u）
    v = u_e * (20.0 + g * g) / (10.0 + g * g) + g * math.exp(-g)
    v4 = v ** 4
    a_e = (1.0 + math.log((v4 + v * v / 2704.0) / (v4 + 0.432)) / 49.0
           + math.log(1.0 + v ** 3 / 5929.741) / 18.7)
    b_e = 0.564 * ((e_r - 0.9) / (e_r + 3.0)) ** 0.053
    q_inf_e = (1.0 + 10.0 / v) ** (-a_e * b_e)
    ere_e0 = 0.5 * (e_r + 1.0) + 0.5 * (e_r - 1.0) * q_inf_e
    # 静态奇模：式 (4)（单线量取修正宽下 skrf HJ 静态 εeff）
    _, ere_s_o = forward_z0(w_o, max(f_ghz, 1e-6), stackup)
    b_o = 0.747 * e_r / (0.15 + e_r)
    c_o = b_o - (b_o - 0.207) * math.exp(-0.414 * u_o)
    d_o = 0.593 + 0.694 * math.exp(-0.562 * u_o)
    q_inf_o = math.exp(-c_o * g ** d_o)
    a_o = 0.7287 * (ere_s_o - 0.5 * (e_r + 1.0)) * (1.0 - math.exp(-0.179 * u_o))
    ere_o0 = (0.5 * (e_r + 1.0) + a_o - ere_s_o) * q_inf_o + ere_s_o
    # 频变：式 (5)-(7)
    f_e, f_o = _kj_dispersion_fe_fo(u_e, g, fn, e_r)
    ere_e_f = e_r - (e_r - ere_e0) / (1.0 + f_e)
    ere_o_f = e_r - (e_r - ere_o0) / (1.0 + f_o)
    return ere_e_f, ere_o_f, ere_e0, ere_o0


def hairpin_kgap_design_branch_mm(w_mm: float | None = None, freq_ghz: float = 2.5,
                                  er: float = 3.66, h_mm: float = 0.508,
                                  n_grid: int = 2001) -> tuple[float, float]:
    """单调设计支 [g_peak, g_max]：k_EM(g)=c(g)·k_KJ(g) 在标定域内**非单调**（真机
    0.5/0.8/1.1328 → 0.01466/0.01511/0.01327：更小 gap 相消加剧、净耦合反降），反解只在
    极大点右侧的递减支上唯一。g_peak 取域内细网格 argmax（确定性、可复算）。"""
    lo, hi = hairpin_kgap_domain_mm()
    w = _hairpin_default_w_mm(w_mm, er, h_mm)
    best_g, best_k = lo, -1.0
    for i in range(int(n_grid)):
        g = lo + (hi - lo) * i / (n_grid - 1)
        k = hairpin_k_from_gap_mm(g, w, freq_ghz, er, h_mm, structural_correction=True)
        if k > best_k:
            best_g, best_k = g, k
    return float(best_g), float(hi)


def hairpin_k_from_gap_mm(gap_mm: float, w_mm: float | None = None,
                          freq_ghz: float = 2.5, er: float = 3.66,
                          h_mm: float = 0.508, *,
                          structural_correction: bool = False,
                          extrapolate: str = "raise") -> float:
    """耦合缝 → 平行耦合系数 k = (Z0e − Z0o)/(Z0e + Z0o)（KJ 闭式）。

    structural_correction=True：hairpin 并排同向 U 结构经验修正——返回 k_EM =
    c(gap)·k_KJ（c 见 HAIRPIN_KGAP_TABLE_MM；标定口径 HAIRPIN_KGAP_CALIB，仅
    w=1.1117/h=0.508/er=3.66 @2.5GHz 同口径几何可用，域外按 extrapolate 处理）。
    默认 False=纯 KJ（U 内臂自耦 k_self 等同口径消费方不受影响）。
    """
    w = _hairpin_default_w_mm(w_mm, er, h_mm)
    z0e, z0o, _, _ = coupled_microstrip_even_odd_ohm(
        w, gap_mm, freq_ghz, er, h_mm)
    k = (z0e - z0o) / (z0e + z0o)
    if structural_correction:
        k *= hairpin_kgap_correction(gap_mm, extrapolate=extrapolate)
    return k


def hairpin_gap_mm_from_k(k: float, w_mm: float | None = None,
                          freq_ghz: float = 2.5, er: float = 3.66,
                          h_mm: float = 0.508,
                          s_lo_mm: float = 0.02, s_hi_mm: float = 30.0, *,
                          structural_correction: bool = False) -> float:
    """耦合系数 → 耦合缝（brentq 反解；k(s) 单调递减，单测钉住）。

    xtol=1e-12mm：设计几何→电气往返（gap→k→耦合矩阵）须在 coupling_matrix_response
    的 1e-9 输出量化底以内逐位复现 C13 理想响应（A4 验收；1e-9 时陡带边末位翻转
    max|ΔS|=1.41e-9）。

    structural_correction=True：反解目标为 c(s)·k_KJ(s)=k，搜索域限**单调设计支**
    hairpin_kgap_design_branch_mm()=[g_peak, g_max]（k_EM(g) 非单调，极大点左侧为相消
    加剧支、非设计域）；k 超出支内可达范围时 ValueError 报可达上/下限（hairpin 结构
    k_EM 上限 ~0.015、FBW 大的设计点属拓扑能力问题，如实报错不越域外推）。
    """
    from scipy.optimize import brentq

    w = _hairpin_default_w_mm(w_mm, er, h_mm)
    k = float(k)
    if not 0.0 < k < 1.0:
        raise ValueError("耦合系数须在 (0,1)")
    if structural_correction:
        s_lo_mm, s_hi_mm = hairpin_kgap_design_branch_mm(w, freq_ghz, er, h_mm)

    def _residual(s_mm: float) -> float:
        return hairpin_k_from_gap_mm(s_mm, w, freq_ghz, er, h_mm,
                                     structural_correction=structural_correction) - k

    f_lo = _residual(s_lo_mm)
    f_hi = _residual(s_hi_mm)
    if f_lo <= 0.0 or f_hi >= 0.0:
        raise ValueError(
            f"k={k} 超出可达范围 [{f_hi + k:.4f}, {f_lo + k:.4f}]"
            f"（缝 {s_lo_mm}~{s_hi_mm}mm）")
    return float(brentq(_residual, s_lo_mm, s_hi_mm, xtol=1e-12))


def hairpin_qe_from_tap_frac(tap_frac: float, z0_ohm: float = 50.0,
                             z_line_ohm: float = 50.0) -> float:
    """抽头比例 → 外部 Q：Q_e = (π/2)·(Z0/Z_r)·sec²(π·τ)（τ∈(0,0.5)）。"""
    tau = float(tap_frac)
    if not 0.0 < tau < 0.5:
        raise ValueError("抽头比例须在 (0,0.5)（0.5=电压节点，无耦合）")
    return ((math.pi / 2.0) * (float(z0_ohm) / float(z_line_ohm))
            / math.cos(math.pi * tau) ** 2)


def hairpin_tap_frac_from_qe(qe: float, z0_ohm: float = 50.0,
                             z_line_ohm: float = 50.0) -> float:
    """外部 Q → 抽头比例 τ=arccos(√((π/2)(Z0/Z_r)/Q_e))/π。"""
    q_e = float(qe)
    if q_e <= 0.0:
        raise ValueError("Q_e 须 >0")
    ratio = (math.pi / 2.0) * (float(z0_ohm) / float(z_line_ohm))
    c2 = ratio / q_e
    if not 0.0 < c2 <= 1.0:
        raise ValueError(
            f"Q_e={q_e} 低于抽头可达下限 {ratio:.4f}（τ→0 极限）")
    return math.acos(math.sqrt(c2)) / math.pi
