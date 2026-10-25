"""微带全族扩展四键（aurora_g W15-S2 席，R3_domain_expansion §④ A1 余量
+ 微带损耗/接地过渡族收尾——W6-S3/W10-S4/W11-S4 六不连续键之后的余量）。

四键：microstrip_cross_parasitics（十字结四口寄生网络+复 S 矩阵）
/ microstrip_attenuation（Hammerstad-Jensen 导体+介质衰减率）
/ microstrip_via_short（Goldfarb-Pucel 接地过孔 L/R+S 面）
/ microstrip_open_end_radiation（开路端辐射电导分段式+开路损耗正切+|Γ|）。

#222 triple-grep 证据（2026-10-20 本席开工实测）
--------------------------------------------------------
``microstrip_cross|mscross|cross_junction`` src/tests/scripts 三面仅历史
runs/ 目录名与判读注释误中（内部证据档、judge_mscross
注释）——注册键面零命中（W6-S3 弯/T/阶跃、W10-S4 最优切角、W11-S4 间隙/
开路端之后十字结=不连续族唯一未落件）。
``radiation_conductance|open_end_radiation|g_rad`` 三面零注册键（唯一误中
=render_mmwave beta_g_rad_mm 变量名）；patch 侧辐射电导为腔模积分式
（synthesis.patch_rin_edge_balanis，槽对互电导面）——开路端/馈线口径的
分段式辐射电导空白。
``microstrip_attenuation|alpha_c`` 三面：core/thermal_iteration.
microstrip_resonator_em 有未注册 helper αc=Rs/(Z0·W)（HJ 双因子=1 渐近
档，谐振器热反馈语境）+calc_families/thermal.microstrip_loss_heat 消费
α（热源面）——**衰减率闭式本身无注册键**（coax 有 coax_line_attenuation、
波导有 HJ αc、微带独缺=同族不对称）。
``microstrip_via|via_short|via_inductance`` 三面零（via_process_params=
PCB 工艺参数面、rf_guard_structures 过孔=DRC 几何面，非电路模型）。

物理口径（#1c/#300 出处纪律；2026-10-20 逐式双源核对，网源在
内部证据档*.{cpp,h,pdf}）
--------------------------------------------------------
1. 十字结（Hammerstad-Bekkadal 系拟合；qucsator mscross.cpp 可执行逐字
   + Qucs 技术手册 §Microstrip cross 式(11.226)-(11.231) 双源逐字一致；
   原始拟合基准 εr=9.9、精度 5%：C 域 W1/h∈[0.3,3]、W2/h∈[0.1,3]，
   L 域 W/h∈[0.5,2]）：

       X = lg(W1h)·(86.6·W2h − 30.9·√W2h + 367) + W2h³ + 74·W2h + 130
       C_i = 1e-12·W_i·(0.25·X·W1h^(−1/3) − 60 + 0.5/W2h
                        − 0.375·W1h·(1−W2h))        （F，W_i 取 m）
       Y = 165.6·W2h + 31.2·√W2h − 11.8·W2h²
       L_i = 1e-9·h·(Y·W1h − 32·W2h + 3)·W1h^(−1.5) （H，h 取 m）
       L5 = 1e-9·h·(5·W2h·cos(π/2·(1.5−W1h)) − (1+7/W1h)/W2h − 337.5)
       L5 ← L5·0.8（手册明示经验改进："value of L3 is too large,
       multiplying it by 0.8 leads to much better results"）

   其中 W1h=本臂 W_i/h、W2h=对臂对平均 (W_j+W_k)/2/h（qucsator 非对称
   推广=对臂平均代入，手册同文背书"as long as the lines that lie
   opposite are not too different in width"；标准模型前提 W1=W3、
   W2=W4）。手册明示 L5<0（负中心电感）为模型固有——脱离外部微带线
   不物理，qucsator 无守卫照常装配，本键放行并输出
   center_inductance_negative 标记位如实呈现。
   εr≠9.9 修正（式 11.231）：C_i ← C_i·Z0(W_i,9.9)/Z0(W_i,εr)
   ·√(εeff(W_i,εr)/εeff(W_i,9.9))——qucsator 用 Hammerstad 准静态
   +Kirschning 色散链，本键按族内口径走 skrf HJ 单源（同 microstrip_disc
   T 接头/间隙键注记）；**εr=9.9（氧化铝）时修正恒等于 1.0 逐位**
   （两路调用全同，锚树钉）。网络=每臂串联 L_i+端口并联 C_i+两内部结点
   5/6 间 L5（qucsator 6 节点 Y 矩阵逐字），内节点经 Schur 消元（与
   qucsator SP 求解器全局节点消去同构）→4×4 Y→50Ω S。
   频率极限锚：f→0 电感全短接、四口并接=理想 4 口结——50Ω 等臂
   S_ii→2/N−1=−0.5、S_ij→+0.5（闭式）。互易 S=Sᵀ 构造保证（Y 对称）。

2. 微带衰减率（Hammerstad-Jensen；qucsator msline.cpp analyseLoss
   "Hammerstad" 支路可执行逐字 + Qucs 手册 §Single microstrip line/
   Transmission losses 式(11.79)-(11.83) 双源逐字一致）：

       Rs = √(π·f·μ0·ρ)                     （表面电阻，11.81）
       δ  = ρ/Rs = √(ρ/(π·f·μ0))            （趋肤深度=conductor_loss.
                                             skin_depth 同仓同式，单源
                                             复用）
       Ki = exp(−1.2·(Z0/η0)^0.7)           （电流分布因子，11.82）
       Kr = 1 + (2/π)·arctan(1.4·(Δ/δ)²)    （表面粗糙度修正，11.83，
                                             Δ=RMS 粗糙度）
       αc = Rs/(Z0·W)·Ki·Kr                 （导体衰减 Np/m，11.80）
       αd = (π/λ0)·(εr/√εeff)·((εeff−1)/(εr−1))·tanδ
                                            （介质衰减 Np/m，11.79）

   validity（手册明文）：Ki 档要求铜厚 t>3δ（qucsator 仅 WARNING 放行，
   本键同构放行+输出 thickness_below_3_skin_depths 标记位）；t=0 →
   αc=0（qucsator 同构；零厚度=无导体损耗口径）。αd 同式同仓双源：
   core/thermal_iteration.microstrip_resonator_em 用同一式（其 εeff 走
   简化 HJ 档，本键 skrf HJ 单源——公式逐字同、εeff 源不同，如实注记）。
   αc 渐近面：Ki=Kr=1 时 αc=Rs/(Z0·W)——即 thermal_iteration 未注册
   helper 的形态（同仓双源对拍锚）。输出 Np/m 与 dB/m 双单位+线 Q
   Q=β/(2α)（β=2πf√εeff/c0）。Z0/εeff 走 skrf HJ 仓内单源。

3. 接地过孔（Goldfarb-Pucel 1991；Qucs 手册 §Microstrip via hole
   式(11.232)-(11.234) 与 finetune.co.jp 独立转录（引 Wadell 1991+GP
   原文）双源逐字一致）：

       R_dc = ρ·h/(π·(r²−(r−t)²))           （空心圆柱 DC 电阻）
       f_δ  = ρ/(π·μ0·t²)                   （趋肤转折频率）
       R(f) = R_dc·√(1+f/f_δ)               （11.233，"valid independent
                                             of t/δ ratio" 手册原文）
       L    = (μ0/2π)·[h·ln((h+√(r²+h²))/r) + 1.5·(r−√(r²+h²))]（11.232）
       Z    = R(f)+j·2πf·L → 50Ω 串联到地二口：s11=z/(z+2)、s21=2/(z+2)
                                             （qucsator msvia.cpp calcSP
                                             逐字）

   **qucsator 可执行偏差如实注记**：msvia.cpp `ind = MU0·(...)` 漏除
   2π（手册 11.232=μ0/2π，finetune 转录同式，MU0=4πe-7 为真磁导率——
   _w15s2_constants.h 实测），数值上 qucsator 形态给 2mil GaAs
   D/H=0.5 → ~66pH，与 Microwaves101 工程口径 ~10pH 矛盾；本键按
   手册/G-P 形态落地并注记偏差。validity：h<0.03λ0（手册+qucsator
   warning 同口径，越界显式拒绝）；拟合窗 h∈[100,631]μm（Microwaves101
   转录 GP 实测域）越窗输出 via_fit_window_flag 标记位不硬拒。
   渐近锚：h≫r 时 L→(μ0·h/2π)·(ln(2h/r)−1.5)+小项。

4. 开路端辐射电导（分段式；Balanis 4th ed Ch.14 槽辐射电导两极限
   ——SDSMT 课程讲义逐字转录在案 _w15s2_sdsmt_patch.pdf："G1=(1/90)·
   (W/λ0)² for W/λ0≪1；(1/120)·(W/λ0) for W/λ0≫1"，AWR/Cadence
   教程 _w15s2_msant.pdf 宽槽档同式（1−(k0h)²/24 修正形态引 Bahl &
   Bhartia 1980 p.51）为第二源）：

       G_r = (1/90)·(W/λ0)²                 （W/λ0 ≤ 1）
       G_r = (1/120)·(W/λ0)                 （W/λ0 ≥ 2）
       1<x<2 线性内插（工程惯例；Balanis 只给两极限不设内插条款，
       内插约定=Bahl 系文献通行形态，如实记约定档）

   开路端等效损耗正切 = G_r/(ω·C_end)（C_end=HB Δl 仓内单源
   slotline_transitions.microstrip_open_end_delta_l_mm→C=Δl√εeff/
   (Z0·c0)，同 microstrip_open_end_parasitics 口径）；开路端反射
   Γ=(Y0−Y_L)/(Y0+Y_L)、Y_L=G_r+jωC_end（50Ω 线终端），|Γ|<1 即
   辐射损耗可见面。同仓双源锚：宽槽档 (1/120)·(W/λ0) 与
   synthesis.patch_rin_edge_balanis 积分式 G1=(W/120λ0)·(1−(k0h)²/24)
   在 k0h→0 渐近逐位相合（本键无 k0h 修正——残差 ≤(k0h)²/24 锚树钉）。
   输出口径：W=物理线宽（Balanis 槽宽口径；有效宽度变体不在本键）。

边界防撞（#222 triple-grep，2026-10-20 实测）
--------------------------------------------------------
- microstrip_disc.py 六键=弯/T/阶跃/最优切角/间隙/开路端（本文件十字结
  为其族内第七件、损耗面为族外邻接件）；
- synthesis.patch_rin_edge_balanis=patch 腔模槽对积分式（本键开路端
  分段式=宽槽渐近的同仓对拍面）；thermal_iteration.microstrip_
  resonator_em=谐振器热反馈 helper（未注册，αc 渐近形态同仓对拍面）；
- conductor_loss.py=表面电阻/趋肤/粗糙度单源（本键 δ 复用）；
  via_process_params/rf_guard_structures=工艺与 DRC 几何面（非电路
  模型）；slotline_transitions=槽线过渡（Δl 单源复用）。
- 裁判面 fake_adapter._bend_sparams=理想寄生零（同族注记）。
本文件只做微带族余量：十字结寄生网络/线衰减率/接地过孔/开路端辐射电导。

出处：Hammerstad-Bekkadal 系十字结拟合（经 qucsator mscross.cpp 可执行
逐字+Qucs 技术手册 §Microstrip cross 式(11.226)-(11.231) 双源）；E.
Hammerstad & Ø. Jensen 衰减式（经 qucsator msline.cpp analyseLoss 可执行
逐字+Qucs 手册 式(11.79)-(11.83) 双源）；M. Goldfarb & R. A. Pucel
"Modeling Via Grounds in Microstrip" IEEE MGW Lett. 1(6) 1991 pp.135-137
（经 Qucs 手册 式(11.232)-(11.234)+finetune.co.jp 独立转录双源；qucsator
msvia.cpp 可执行偏差注记在案）；Balanis《Antenna Theory》4th ed Ch.14
槽辐射电导两极限（SDSMT 讲义逐字+_w15s2_msant.pdf Bahl-Bhartia p.51
同式，内插约定=Bahl 系通行形态如实记档）。
"""

from __future__ import annotations

import math

from .microstrip_disc import _line_z0_eps_eff
from .registry import register_calculator

#: 真空波阻抗 η0（qucs::Z0 同值，qucsator constants.h L54 实测）
_ETA0_OHM = 376.73031346958504364963
#: 光速 m/s
_C0_M_S = 299792458.0
#: 真空磁导率（qucsator MU0=12.566370614e-7 同值）
_MU0_H_PER_M = 4.0e-7 * math.pi


def _finite(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if not math.isfinite(v):
        raise ValueError(f"{key}: {name} 必须有限，得 {value!r}")
    return v


def _finite_pos(key: str, name: str, value: object) -> float:
    v = _finite(key, name, value)
    if v <= 0.0:
        raise ValueError(f"{key}: {name} 必须 >0，得 {value!r}")
    return v


# ─── 1. 十字结 ──────────────────────────────────────────────────────────────

def _cross_cap_f(w_own_m: float, w_own_h: float, w_perp_h: float) -> float:
    """十字结臂并联电容（mscross.cpp calcCap/手册式(11.226)-(11.227) 逐字）。"""
    x = (math.log10(w_own_h) * (86.6 * w_perp_h - 30.9 * math.sqrt(w_perp_h)
                                + 367.0)
         + w_perp_h ** 3 + 74.0 * w_perp_h + 130.0)
    return 1e-12 * w_own_m * (0.25 * x * w_own_h ** (-1.0 / 3.0) - 60.0
                              + 0.5 / w_perp_h
                              - 0.375 * w_own_h * (1.0 - w_perp_h))


def _cross_ind_h(w_own_h: float, w_perp_h: float, h_m: float) -> float:
    """十字结臂串联电感（mscross.cpp calcInd/手册式(11.228)-(11.229) 逐字）。"""
    y = (165.6 * w_perp_h + 31.2 * math.sqrt(w_perp_h)
         - 11.8 * w_perp_h * w_perp_h)
    return (1e-9 * h_m * (y * w_own_h - 32.0 * w_perp_h + 3.0)
            * w_own_h ** (-1.5))


def _cross_center_ind_h(w1h: float, w2h: float, h_m: float) -> float:
    """十字结中心电感 L5（mscross.cpp 逐字+0.8 经验因子；手册式(11.230)
    明示 L5<0 为模型固有，脱离外部微带线不物理）。"""
    l5 = 1e-9 * h_m * (5.0 * w2h * math.cos(math.pi / 2.0 * (1.5 - w1h))
                       - (1.0 + 7.0 / w1h) / w2h - 337.5)
    return l5 * 0.8


@register_calculator(
    "microstrip_cross_parasitics",
    "微带十字结四口寄生网络（W15-S2）：每臂串联 "
    "L_i+端口并联 C_i（Hammerstad-Bekkadal 系拟合，qucsator mscross.cpp "
    "可执行逐字+Qucs 手册 式(11.226)-(11.231) 双源）+两内结点间中心电感 "
    "L5（手册明示为负=模型固有，标记位如实）。εr≠9.9 走式(11.231) 阻抗"
    "比修正（skrf HJ 单源，εr=9.9 恒 1.0 逐位）。输出 4×4 复 S 矩阵"
    "（[行][列]=[re,im]，互易 S=Sᵀ 构造保证）+|S| dB 面。f→0 极限=理想 "
    "4 口并接结（50Ω 等臂 S_ii→−0.5/S_ij→+0.5）。C 域 W/h∈[0.3,3]×[0.1,3] "
    "显式守卫；L 域 [0.5,2] 越窗标记",
    (("w1_mm", "float mm 臂 1 线宽（臂 1-3 为一对、臂 2-4 为一对）"),
     ("w2_mm", "float mm 臂 2 线宽"),
     ("w3_mm", "float mm 臂 3 线宽"),
     ("w4_mm", "float mm 臂 4 线宽"),
     ("h_mm", "float mm 基板厚度"),
     ("epsilon_r", "float 基板相对介电常数（拟合基准 εr=9.9）"),
     ("freq_ghz", "float GHz 工作频率（>0）")),
    required=("w1_mm", "w2_mm", "w3_mm", "w4_mm", "h_mm", "epsilon_r",
              "freq_ghz"),
)
def microstrip_cross_parasitics(w1_mm: float, w2_mm: float, w3_mm: float,
                                w4_mm: float, h_mm: float,
                                epsilon_r: float,
                                freq_ghz: float) -> dict:
    key = "microstrip_cross_parasitics"
    w_mm = tuple(_finite_pos(key, f"w{i}_mm", w)
                 for i, w in enumerate((w1_mm, w2_mm, w3_mm, w4_mm), 1))
    h = _finite_pos(key, "h_mm", h_mm)
    er = _finite(key, "epsilon_r", epsilon_r)
    if er < 1.0:
        raise ValueError(
            f"{key}: εr≥1（skrf HJ 模型域守卫，族内 T 接/阶跃同口径），得 "
            f"{epsilon_r!r}")
    _ = _finite_pos(key, "freq_ghz", freq_ghz)

    w_own_h = [w / h for w in w_mm]
    # 对臂平均：臂 i 的垂直对 = 另一对的两臂平均（qucsator 逐字）
    perp_idx = ((1, 3), (0, 2), (1, 3), (0, 2))
    w_perp_h = [0.5 * (w_own_h[a] + w_own_h[b]) for a, b in perp_idx]
    for i in range(4):
        # C 拟合域（手册明文 5% 精度域）逐臂守卫：本臂 [0.3,3]、对臂平均
        # [0.1,3]——越域显式拒绝（不外推，#122）
        if not 0.3 <= w_own_h[i] <= 3.0:
            raise ValueError(
                f"{key}: 本臂 W{i + 1}/h={w_own_h[i]!r} 在 C 拟合域 "
                f"[0.3,3] 外（手册原文 accuracy domain），得 "
                f"w{i + 1}_mm={w_mm[i]!r}")
        if not 0.1 <= w_perp_h[i] <= 3.0:
            raise ValueError(
                f"{key}: 对臂平均 W/h={w_perp_h[i]!r} 在 C 拟合域 [0.1,3] "
                f"外（手册原文），臂 {i + 1} 垂直对")

    # εr 修正（式 11.231）：skrf HJ 双调用，εr=9.9 → 逐位 1.0（同构恒等锚）
    corrections = []
    for i in range(4):
        if er == 9.9:
            corrections.append(1.0)
            continue
        z_ref, e_ref = _line_z0_eps_eff(w_mm[i], freq_ghz, 9.9, h)
        z_sub, e_sub = _line_z0_eps_eff(w_mm[i], freq_ghz, er, h)
        corrections.append(z_ref / z_sub * math.sqrt(e_sub / e_ref))

    caps_f = [_cross_cap_f(w_mm[i] * 1e-3, w_own_h[i], w_perp_h[i])
              * corrections[i] for i in range(4)]
    inds_h = [_cross_ind_h(w_own_h[i], w_perp_h[i], h * 1e-3)
              for i in range(4)]
    l5_h = _cross_center_ind_h(
        0.5 * (w_own_h[0] + w_own_h[2]), 0.5 * (w_own_h[1] + w_own_h[3]),
        h * 1e-3)

    # 6 节点 Y 矩阵（qucsator calcMatrixY 逐字装配）→ Schur 消去内节点
    # 5/6（与 qucsator SP 求解器全局节点消去同构）→ 4×4 Y → 50Ω S
    import numpy as np

    omega = 2.0 * math.pi * freq_ghz * 1e9
    yl = [1.0 / (1j * omega * li) for li in (*inds_h, l5_h)]
    yc = [1j * omega * c for c in caps_f]
    y_big = np.zeros((6, 6), dtype=complex)
    y_big[0, 0] = yl[0] + yc[0]
    y_big[1, 1] = yl[1] + yc[1]
    y_big[2, 2] = yl[2] + yc[2]
    y_big[3, 3] = yl[3] + yc[3]
    y_big[4, 4] = yl[0] + yl[2] + yl[4]
    y_big[5, 5] = yl[1] + yl[3] + yl[4]
    y_big[0, 4] = y_big[4, 0] = -yl[0]
    y_big[2, 4] = y_big[4, 2] = -yl[2]
    y_big[1, 5] = y_big[5, 1] = -yl[1]
    y_big[3, 5] = y_big[5, 3] = -yl[3]
    y_big[4, 5] = y_big[5, 4] = -yl[4]
    y_ext = y_big[:4, :4] - y_big[:4, 4:] @ np.linalg.inv(
        y_big[4:, 4:]) @ y_big[4:, :4]
    eye = np.eye(4)
    s_mat = (eye - 50.0 * y_ext) @ np.linalg.inv(eye + 50.0 * y_ext)
    s_db = 20.0 * np.log10(np.abs(s_mat) + 1e-300)

    return {
        "w1_mm": w_mm[0], "w2_mm": w_mm[1], "w3_mm": w_mm[2],
        "w4_mm": w_mm[3], "h_mm": h, "epsilon_r": er,
        "freq_ghz": freq_ghz,
        "c_arm1_f": caps_f[0], "c_arm2_f": caps_f[1],
        "c_arm3_f": caps_f[2], "c_arm4_f": caps_f[3],
        "l_arm1_h": inds_h[0], "l_arm2_h": inds_h[1],
        "l_arm3_h": inds_h[2], "l_arm4_h": inds_h[3],
        "l5_center_h": l5_h,
        "cap_correction_1": corrections[0], "cap_correction_2": corrections[1],
        "cap_correction_3": corrections[2], "cap_correction_4": corrections[3],
        "s_matrix": [[[float(z.real), float(z.imag)] for z in row]
                     for row in s_mat],
        "s11_db": float(s_db[0, 0]), "s21_db": float(s_db[1, 0]),
        "s31_db": float(s_db[2, 0]), "s41_db": float(s_db[3, 0]),
        "center_inductance_negative": bool(l5_h < 0.0),
        "inductance_out_of_fitted_domain": any(
            not 0.5 <= u <= 2.0 for u in (*w_own_h, *w_perp_h)),
        "note": ("Hammerstad-Bekkadal 系拟合（基准 εr=9.9、精度 5%），"
                 "qucsator mscross.cpp 可执行逐字+Qucs 手册 式(11.226)-"
                 "(11.231) 双源；εr 修正=式(11.231)（qucsator 用 "
                 "Kirschning 色散链，本键 skrf HJ 单源，εr=9.9 恒 1.0）；"
                 "L5<0=手册明示模型固有（脱离外部微带线不物理，qucsator "
                 "同构放行）；L 域 [0.5,2] 越窗标记不硬拒（qucsator 无 "
                 "守卫）；f→0 极限=理想 4 口并接结（50Ω 等臂 S_ii→−0.5/"
                 "S_ij→+0.5）"),
    }


# ─── 2. 微带衰减率（Hammerstad-Jensen）─────────────────────────────────────

@register_calculator(
    "microstrip_attenuation",
    "微带线衰减率（W15-S2）："
    "Hammerstad-Jensen 导体衰减 αc=Rs/(Z0·W)·Ki·Kr（电流分布因子 Ki+"
    "粗糙度修正 Kr，qucsator msline.cpp analyseLoss 可执行逐字+Qucs 手册 "
    "式(11.79)-(11.83) 双源）+介质衰减 αd（同式同仓双源：core/"
    "thermal_iteration 同形态）。趋肤深度复用 conductor_loss.skin_depth "
    "仓内单源。Ki 档 validity t>3δ（越窗标记不硬拒）；t=0 → αc=0"
    "（qucsator 同构）。输出 Np/m+dB/m+线 Q=β/(2α)",
    (("width_mm", "float mm 导带宽度 W"),
     ("h_mm", "float mm 基板厚度 h"),
     ("epsilon_r", "float 基板相对介电常数（>1）"),
     ("freq_ghz", "float GHz 工作频率（>0）"),
     ("tan_delta", "float 介质损耗正切 tanδ（>=0，缺省 0=无耗）"),
     ("thickness_um", "float µm 导体厚度 t（>=0，缺省 0=零厚度无导体损耗"
      "——qucsator 同构口径）"),
     ("roughness_rms_um", "float µm 导体表面 RMS 粗糙度 Δ（>=0，缺省 0"
      "→Kr=1 逐位）"),
     ("sigma_s_per_m", "float S/m 导体电导率（缺省 5.8e7 铜）")),
    required=("width_mm", "h_mm", "epsilon_r", "freq_ghz"),
)
def microstrip_attenuation(width_mm: float, h_mm: float, epsilon_r: float,
                           freq_ghz: float, tan_delta: float = 0.0,
                           thickness_um: float = 0.0,
                           roughness_rms_um: float = 0.0,
                           sigma_s_per_m: float = 5.8e7) -> dict:
    from rfauto.core.conductor_loss import skin_depth

    key = "microstrip_attenuation"
    w = _finite_pos(key, "width_mm", width_mm)
    h = _finite_pos(key, "h_mm", h_mm)
    er = _finite(key, "epsilon_r", epsilon_r)
    if er <= 1.0:
        raise ValueError(
            f"{key}: εr>1（αd 的 εr−1 分母；空气线 αd 无定义，"
            f"thermal_iteration 同口径守卫），得 {epsilon_r!r}")
    f_hz = _finite_pos(key, "freq_ghz", freq_ghz) * 1e9
    td = _finite(key, "tan_delta", tan_delta)
    if td < 0.0:
        raise ValueError(f"{key}: tanδ>=0，得 {tan_delta!r}")
    t_m = _finite(key, "thickness_um", thickness_um) * 1e-6
    if t_m < 0.0:
        raise ValueError(f"{key}: 厚度 t>=0，得 {thickness_um!r}")
    d_m = _finite(key, "roughness_rms_um", roughness_rms_um) * 1e-6
    if d_m < 0.0:
        raise ValueError(f"{key}: 粗糙度 Δ>=0，得 {roughness_rms_um!r}")
    sigma = _finite_pos(key, "sigma_s_per_m", sigma_s_per_m)
    rho = 1.0 / sigma

    z0, eps_eff = _line_z0_eps_eff(w, freq_ghz, er, h)
    # 介质衰减（式 11.79 逐字；tand=0 → 0 逐位，εr>1 守卫在上方）
    ad_np = (math.pi * f_hz / _C0_M_S) * (er / math.sqrt(eps_eff)) \
        * ((eps_eff - 1.0) / (er - 1.0)) * td
    # 导体衰减（式 11.80-11.83 逐字；t=0 → αc=0 同 qucsator）
    ac_np = 0.0
    delta_m = None
    kr = 1.0
    ki = None
    below_3delta = None
    if t_m > 0.0:
        rs = math.sqrt(math.pi * f_hz * _MU0_H_PER_M * rho)   # 11.81
        delta_m = skin_depth(f_hz, sigma)                     # 同仓单源
        ki = math.exp(-1.2 * (z0 / _ETA0_OHM) ** 0.7)         # 11.82
        kr = 1.0 + (2.0 / math.pi) * math.atan(1.4 * (d_m / delta_m) ** 2)
        ac_np = rs / (z0 * w * 1e-3) * ki * kr                # 11.80
        below_3delta = bool(t_m < 3.0 * delta_m)
    alpha_np = ac_np + ad_np
    beta = 2.0 * math.pi * f_hz * math.sqrt(eps_eff) / _C0_M_S
    q_line = math.inf if alpha_np <= 0.0 else beta / (2.0 * alpha_np)
    return {
        "width_mm": w, "h_mm": h, "epsilon_r": er, "freq_ghz": freq_ghz,
        "tan_delta": td, "thickness_um": thickness_um,
        "roughness_rms_um": roughness_rms_um, "sigma_s_per_m": sigma,
        "z0_ohm": z0, "eps_eff": eps_eff,
        "alpha_conductor_np_per_m": ac_np,
        "alpha_dielectric_np_per_m": ad_np,
        "alpha_total_np_per_m": alpha_np,
        "alpha_total_db_per_m": alpha_np * 8.686,
        "q_line": q_line,
        "skin_depth_m": delta_m,
        "ki_current_factor": ki,
        "kr_roughness_factor": kr,
        "thickness_below_3_skin_depths": below_3delta,
        "note": ("Hammerstad-Jensen（qucsator msline.cpp analyseLoss 逐字"
                 "+Qucs 手册 式(11.79)-(11.83) 双源）；αd 同式同仓双源="
                 "thermal_iteration.microstrip_resonator_em（εeff 源不同"
                 "：彼=简化 HJ 档、本键=skrf HJ 单源）；Ki=1/Kr=1 渐近档"
                 "αc=Rs/(Z0·W)=同 helper 形态；Q=β/(2α) 行波线 Q"),
    }


# ─── 3. 接地过孔（Goldfarb-Pucel）───────────────────────────────────────────

@register_calculator(
    "microstrip_via_short",
    "微带接地过孔 L/R+S 面（W15-S2）：Goldfarb-Pucel 圆柱过孔模型——"
    "R_dc=ρh/(π(r²−(r−t)²))+R(f)=R_dc·√(1+f/f_δ)+L=(μ0/2π)[h·ln((h+"
    "√(r²+h²))/r)+1.5(r−√(r²+h²))]（Qucs 手册 式(11.232)-(11.234)+"
    "finetune.co.jp 独立转录双源）→ 50Ω 串联到地二口 s11=z/(z+2)、"
    "s21=2/(z+2)（qucsator calcSP 逐字）。validity h<0.03λ0 显式守卫；"
    "拟合窗 h∈[100,631]µm 越窗标记。qucsator msvia.cpp 电感漏除 2π 偏差"
    "注记在案（本键按手册/G-P 形态）",
    (("h_mm", "float mm 过孔长度（=基板厚度）"),
     ("diameter_mm", "float mm 过孔直径 D（钻孔）"),
     ("freq_ghz", "float GHz 工作频率（>0；h<0.03λ0 守卫）"),
     ("thickness_um", "float µm 孔壁金属化厚度 t（0<t<r）"),
     ("sigma_s_per_m", "float S/m 孔壁电导率（缺省 5.8e7 铜）")),
    required=("h_mm", "diameter_mm", "freq_ghz"),
)
def microstrip_via_short(h_mm: float, diameter_mm: float, freq_ghz: float,
                         thickness_um: float = 35.0,
                         sigma_s_per_m: float = 5.8e7) -> dict:
    key = "microstrip_via_short"
    h = _finite_pos(key, "h_mm", h_mm)
    dia = _finite_pos(key, "diameter_mm", diameter_mm)
    f_hz = _finite_pos(key, "freq_ghz", freq_ghz) * 1e9
    t_m = _finite_pos(key, "thickness_um", thickness_um) * 1e-6
    sigma = _finite_pos(key, "sigma_s_per_m", sigma_s_per_m)
    rho = 1.0 / sigma
    r_m = dia * 1e-3 / 2.0
    h_m = h * 1e-3
    if t_m >= r_m:
        raise ValueError(
            f"{key}: 孔壁厚 t<r（R_dc 分母 r²−(r−t)² 结构性须正），得 "
            f"t={thickness_um!r}µm >= r={r_m * 1e6:.3f}µm")
    # validity（手册+qucsator warning 同口径）：h < 0.03·λ0
    if f_hz * h_m >= 0.03 * _C0_M_S:
        raise ValueError(
            f"{key}: f·h={f_hz * h_m:.4e} >= 0.03·c0（G-P 模型 validity "
            f"h<0.03λ0，手册/qucsator 同口径），得 h={h!r}mm @ "
            f"{freq_ghz!r}GHz")
    fit_window_flag = not (100e-6 <= h_m <= 631e-6)

    # R_dc（msvia.cpp calcResistance 逐字=手册 11.232 链路电阻部分）
    r_dc = rho * h_m / (math.pi * (r_m * r_m - (r_m - t_m) ** 2))
    f_delta = rho / (math.pi * _MU0_H_PER_M * t_m * t_m)          # 11.234
    r_ac = r_dc * math.sqrt(1.0 + f_hz / f_delta)                 # 11.233
    a_m = math.hypot(r_m, h_m)
    # L（手册 11.232/G-P/finetune 转录逐字；qucsator msvia.cpp 漏 2π
    # 偏差如实注记——模块 docstring 节 3）
    ind_h = (_MU0_H_PER_M / (2.0 * math.pi)) * (
        h_m * math.log((h_m + a_m) / r_m) + 1.5 * (r_m - a_m))
    z_norm = complex(r_ac, 2.0 * math.pi * f_hz * ind_h) / 50.0
    s11 = z_norm / (z_norm + 2.0)
    s21 = 2.0 / (z_norm + 2.0)
    return {
        "h_mm": h, "diameter_mm": dia, "freq_ghz": freq_ghz,
        "thickness_um": thickness_um, "sigma_s_per_m": sigma,
        "r_dc_ohm": r_dc, "f_delta_hz": f_delta, "r_ac_ohm": r_ac,
        "l_inductance_h": ind_h,
        "z_real_ohm": r_ac, "z_imag_ohm": 2.0 * math.pi * f_hz * ind_h,
        "s11_re": s11.real, "s11_im": s11.imag,
        "s21_re": s21.real, "s21_im": s21.imag,
        "s11_mag": abs(s11), "s21_mag": abs(s21),
        "via_fit_window_flag": fit_window_flag,
        "note": ("Goldfarb-Pucel 1991（Qucs 手册 式(11.232)-(11.234)+"
                 "finetune.co.jp 独立转录双源）；qucsator msvia.cpp 电感"
                 "漏除 2π（MU0 而非 MU0/2π，_w15s2_constants.h 实测 MU0="
                 "4πe-7）——本键按手册形态；拟合窗 h∈[100,631]µm 越窗"
                 "flag 不硬拒；f→0 极限 R→R_dc、ρ→∞ 理想短路时"
                 "|S11|²+|S21|²=1"),
    }


# ─── 4. 开路端辐射电导 ──────────────────────────────────────────────────────

def _open_end_radiation_s(x_wl: float) -> float:
    """开路端辐射电导 G_r（S）——Balanis 4th Ch.14 槽辐射电导两极限
    （SDSMT 讲义逐字）：(1/90)(W/λ0)² 窄槽 / (1/120)(W/λ0) 宽槽；
    1<x<2 线性内插（Bahl 系工程惯例，两极限在 x=1/2 处逐位衔接）。"""
    if x_wl <= 1.0:
        return x_wl * x_wl / 90.0
    if x_wl >= 2.0:
        return x_wl / 120.0
    return 1.0 / 90.0 + (x_wl - 1.0) * (1.0 / 60.0 - 1.0 / 90.0)


@register_calculator(
    "microstrip_open_end_radiation",
    "微带开路端辐射电导（W15-S2）：G_r 分段式——(1/90)·"
    "(W/λ0)² 窄槽档 / (1/120)·(W/λ0) 宽槽档（Balanis 4th Ch.14 槽辐射"
    "电导两极限，SDSMT 讲义逐字；1<x<2 线性内插=Bahl 系工程惯例如实记"
    "档）+等效开路损耗正切 G_r/(ω·C_end)（C_end=HB Δl 仓内单源）+50Ω "
    "终端反射 |Γ|=(Y0−Y_L)/(Y0+Y_L)。宽槽档与 synthesis."
    "patch_rin_edge_balanis 积分式 k0h→0 渐近同仓对拍",
    (("width_mm", "float mm 开路端线宽 W"),
     ("h_mm", "float mm 基板厚度 h"),
     ("epsilon_r", "float 基板相对介电常数（>=1）"),
     ("freq_ghz", "float GHz 工作频率（>0）")),
    required=("width_mm", "h_mm", "epsilon_r", "freq_ghz"),
)
def microstrip_open_end_radiation(width_mm: float, h_mm: float,
                                  epsilon_r: float,
                                  freq_ghz: float) -> dict:
    key = "microstrip_open_end_radiation"
    w = _finite_pos(key, "width_mm", width_mm)
    h = _finite_pos(key, "h_mm", h_mm)
    er = _finite(key, "epsilon_r", epsilon_r)
    if er < 1.0:
        raise ValueError(
            f"{key}: εr>=1（族内开路端/间隙键同口径守卫），得 {epsilon_r!r}")
    f_hz = _finite_pos(key, "freq_ghz", freq_ghz) * 1e9

    from rfauto.core.slotline_transitions import (
        microstrip_open_end_delta_l_mm,
    )

    z0, eps_eff = _line_z0_eps_eff(w, freq_ghz, er, h)
    x_wl = w * 1e-3 / (_C0_M_S / f_hz)
    g_rad = _open_end_radiation_s(x_wl)
    dl_m = microstrip_open_end_delta_l_mm(w, h, eps_eff) * 1e-3
    c_end = dl_m * math.sqrt(eps_eff) / (z0 * _C0_M_S)   # 式(11.192) 恒等式
    omega = 2.0 * math.pi * f_hz
    y_l = complex(g_rad, omega * c_end)
    y0 = 1.0 / z0
    gamma = (y0 - y_l) / (y0 + y_l)
    k0h = 2.0 * math.pi * f_hz * h * 1e-3 / _C0_M_S
    return {
        "width_mm": w, "h_mm": h, "epsilon_r": er, "freq_ghz": freq_ghz,
        "w_over_lambda0": x_wl, "z0_ohm": z0, "eps_eff": eps_eff,
        "k0h": k0h,
        "g_radiation_s": g_rad,
        "c_end_f": c_end,
        "dl_hammerstad_mm": dl_m * 1e3,
        "open_end_loss_tangent": g_rad / (omega * c_end),
        "gamma_re": gamma.real, "gamma_im": gamma.imag,
        "gamma_mag": abs(gamma), "gamma_db": 20.0 * math.log10(abs(gamma)),
        "radiation_regime": ("narrow" if x_wl <= 1.0
                             else ("wide" if x_wl >= 2.0 else "interp")),
        "note": ("两极限=Balanis 4th Ch.14 槽辐射电导（SDSMT 讲义逐字；"
                 "宽槽档 AWR 教程引 Bahl-Bhartia 1980 p.51 同式）；"
                 "1<x<2 线性内插=Bahl 系工程惯例（Balanis 只给极限，"
                 "内插约定如实记档）；C_end=HB Δl 仓内单源+式(11.192) "
                 "恒等式；宽槽档与 patch_rin_edge_balanis 积分式 k0h→0 "
                 "渐近同仓对拍（本键无 (k0h)²/24 修正——残差 ≤(k0h)²/24）"),
    }
