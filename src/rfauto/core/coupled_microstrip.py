"""耦合微带 / 抽头谐振器闭式内核（core 叶层；2026-09-16 自 adapters 下沉）。

本模块由 adapters/openems_templates.py 的 hairpin 段**原样下沉**（函数体
与 docstring 逐字保留，仅常量改为模块级公开名）；adapters 经再导出零改动消费
（#116：adapters 不留本地遮蔽副本）。数值只在确定性内核——闭式部分
不含任何经验常数，全部为公开闭式：

- 偶/奇模阻抗：Kirschning-Jansen 1984 准静态闭式（零厚/无盖口径），单线量
  取 skrf Hammerstad-Jensen 正向（core/synthesis.forward_z0），与 Qucs/transcalc
  的 c_microstrip.cpp 零厚无盖分支逐式对应；
- 平行耦合半波谐振器耦合系数 k=(Z0e−Z0o)/(Z0e+Z0o)（Hong §5.4）及 brentq 反解；
- 抽头外部 Q：Q_e=(π/2)(Z0/Z_r)sec²(πτ)（本仓派生，单测以精确分布参数 Y_res(ω)
  数值微分独立校核，#118）及反解 τ=arccos(√((π/2)(Z0/Z_r)/Q_e))/π；
- 展开半波长臂长 λg/2=c/(2·f0·√εeff)（Pozar；与 core/thermo_mech 同式）。

**hairpin 结构经验修正 c(gap)（2026-09-17）**：并排同向 U 形 hairpin 的级间耦合
不是均匀无限平行耦合线——相邻臂电流反向、两端开路、U 弯邻近，电/磁耦合部分相消，
EM 有效 k_EM 显著低于 KJ 平行线 k_KJ。闭式本身已由独立来源核实无误（NGSolve 2D 准静态
偶/奇模 k_NG/k_KJ=1.003/1.018/1.049 @gap 0.8/1.1328/1.6 离线复核），故修正只作用于
hairpin 通道、显式 opt-in
（structural_correction=True），常数 HAIRPIN_KGAP_TABLE_MM 全部出自 openEMS
N=2 弱抽头双谐振器真机（scripts/hairpin_q_extract.py --kgap-analyze 可复算），
适用域见 HAIRPIN_KGAP_CALIB，域外不外推（设计反解 raise；fake 前向可显式 clamp）。
"""
from __future__ import annotations

import math

C_MM_GHZ = 299.792458          # mm·GHz（真空光速，与 core 同口径）
ZF0_OHM = 376.730313668        # 自由空间波阻抗 Ω
HAIRPIN_50OHM_W_MM = 1.1134    # rogers4350b h=0.508 er=3.66 的 50Ω 线宽（HJ）

# ── hairpin 级间耦合结构经验修正表 c(gap)=k_EM/k_KJ（真机标定，2026-09-17）──
# 口径（HAIRPIN_KGAP_CALIB）：rogers4350b h=0.508/er=3.66、w=1.1117（50Ω@2.5GHz）、
# arm_gap=3.0、arm_len=36.7799、τ=0.43 双抽头 N=2、openEMS 0.4mm 网格、KJ 在 2.5GHz 求值；
# 提取=有耗 4×4 耦合矩阵模型峰电平反演（k<0.03）/全线形拟合（k≥0.03），Q_e/Q_u 取 B1
# 同 τ 单腔实测 34.691/236.347。表为 (gap_mm, c) 升序，内插=分段线性；域=[首,末] gap。
HAIRPIN_KGAP_TABLE_MM: tuple[tuple[float, float], ...] = (
    # (gap_mm, c)：标定曲线 kgap_curve.json（2026-09-17，N=2 τ0.43，openEMS 0.4mm）
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
    "source": "hairpin_kgap 标定曲线 kgap_curve.json（scripts/hairpin_q_extract.py --kgap-analyze）",
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


def hairpin_kgap_design_branch_mm(w_mm: float | None = None, freq_ghz: float = 2.5,
                                  er: float = 3.66, h_mm: float = 0.508,
                                  n_grid: int = 2001) -> tuple[float, float]:
    """单调设计支 [g_peak, g_max]：k_EM(g)=c(g)·k_KJ(g) 在标定域内**非单调**（真机
    0.5/0.8/1.1328 → 0.01466/0.01511/0.01327：更小 gap 相消加剧、净耦合反降），反解只在
    极大点右侧的递减支上唯一。g_peak 取域内细网格 argmax（确定性、可复算）。"""
    lo, hi = hairpin_kgap_domain_mm()
    w = HAIRPIN_50OHM_W_MM if w_mm is None else float(w_mm)
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
    w = HAIRPIN_50OHM_W_MM if w_mm is None else float(w_mm)
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
    的 1e-9 输出量化底以内逐位复现理想响应（验收门；1e-9 时陡带边末位翻转
    max|ΔS|=1.41e-9）。

    structural_correction=True：反解目标为 c(s)·k_KJ(s)=k，搜索域限**单调设计支**
    hairpin_kgap_design_branch_mm()=[g_peak, g_max]（k_EM(g) 非单调，极大点左侧为相消
    加剧支、非设计域）；k 超出支内可达范围时 ValueError 报可达上/下限（hairpin 结构
    k_EM 上限 ~0.015、FBW 大的设计点属拓扑能力问题，如实报错不越域外推）。
    """
    from scipy.optimize import brentq

    w = HAIRPIN_50OHM_W_MM if w_mm is None else float(w_mm)
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
