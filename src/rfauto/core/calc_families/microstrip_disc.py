"""微带不连续寄生闭式族（aurora_g W6-S3 席，R3_domain_expansion 视角1 A1
Top1，跨视角 1/2 双归属——物理不连续层+PCB layout 节点唯一直系核空白；
W11-S4 席全族扩展 +2 键：串联间隙+开路端效应）。

五键：microstrip_bend_parasitics（直角弯寄生 L/C——未切角与 50% 切角双档）
/ microstrip_t_junction_parasitics（T 接头 Hammerstad-Bekkadal 等效电路）
/ microstrip_step_parasitics（宽度阶跃 Garg-Bahl 等效 L/C）/
microstrip_gap_parasitics（W11-S4：串联间隙 Garg-Bahl π 网络电容）/
microstrip_open_end_parasitics（W11-S4：开路端效应 Δl 双档+等效电容）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``mitre|chamfer|bekkadal|microstrip_disc|ms_discontinuity`` src/tests/scripts
三面仅几何级误中：kicad_edb_bridge "chamfered_rect" 枚举、fab_export 制造
注记、pcell_dsl 切角几何基元、rf_trace_geometry 切角面积、coupled_microstrip
Hammerstad-Bekkadal ΔW **线宽修正**（均匀线修正非不连续）——核心无任何
不连续寄生参数闭式。消费面背书：adapters/fake_adapter.py ``_bend_sparams``
docstring 逐字"理想的唯一偏差即弯角寄生贡献，|S11| 绝对门 -15dB（未切角
直角弯折文献口径）"——fake 裁判面把弯角寄生记为零（理想级联），本族补的
正是该寄生参数的物理参考实体（同仓双源对拍锚）。

物理口径（#1c/#300 出处纪律；公式逐式双源核对 2026-10-19，引文在案）
--------------------------------------------------------
1. 直角弯（等效电路：串联 L—并联 C—串联 L 的对称 T 网络，见 Poole-
   Darwazeh《Microwave Active Circuit Analysis and Design》Lecture 3
   fig 10(b)/11(b) 与其式(25) Z 矩阵 z11=jωL+1/(jωC)、z12=1/(jωC)）：

   未切角直角弯（Kirschning 1983，式(20)(21) 逐字；TU/e van Meeteren
   thesis 同式双源）：

       C = W·[(10.35·εr+2.5)·(W/h) + (2.6·εr+5.64)]    pF（W 取 m）
       L = 220·h·(1 − 1.35·exp(−0.18·(W/h)^1.39))      nH（h 取 m）

   50% 切角弯（同源式(22)(23) 逐字；= qucsator msmbend.cpp 可执行同式，
   Qucs 技术手册 §Microstrip corner 引 Kirschning）：

       C = W·[(3.93·εr+0.62)·(W/h) + (7.6·εr+3.80)]    pF（W 取 m）
       L = 440·h·(1 − 1.062·exp(−0.177·(W/h)^0.947))   nH（h 取 m）

   validity（文献原文：两档同）：W/h∈[0.2,6]、εr∈[2.36,10.4]、
   f·h≤12 GHz·mm、精度 ~0.3%。未切角 L 式在 W/h≲1.4 给负值（拟合域外，
   TU/e thesis 明示 "validity limited to w/h ≳ 1"）——负值显式
   ValueError 如实拒绝。Douville-James 1978 实测结论（Visser 2007
   EuCAP 转述逐字）："α=45°, b=0.5√2W（50% 切角）对所考虑的全部宽度/
   高度/介电常数/频率均改善反射"；最优切角百分式已由 W10-S4 席双网源
   逐字核对补齐（Microwaves101 Mitered Bends 与 rftools.io 同式双源，
   原文 Douville-James MTT-26(3) 1978 pp.175-181）→ 见本文件
   microstrip_optimal_miter 键（W/h∈[0.25,2.75] 实测域）。

   fake_adapter 消费面对拍锚：T 网络（串联 L×2+并联 C）在 50Ω 参考下的
   |S11|（本键 bend_s11_db 输出）与 fake 裁判面"未切角直角弯 |S11| 绝对
   门 −15dB"同量级（本键 W/h=2 氧化铝 10GHz 档 ≈−15dB，锚树钉带）。

2. T 接头（Hammerstad-Bekkadal 等效电路；qucsator mstee.cpp 可执行逐字
   转录，Qucs 技术手册 §Microstrip tee junction 同源；原始出处 HB 1975
   ELAB report STF44 A74169 / Hammerstad 1981 MTT-S）：

       D_i   = η0·h/(Z_i·√εeff_i)          （等效平行板线宽；平行板阻抗
                                             恒等式 Z0_pp=η0·h/(D√εeff) 反
                                             解——结构独立可核对）
       f_p,i = 0.4e6·Z_i/h                 （一阶高阶模截止，Hz/m 口径）
       da,db = 0.055·D_3·(Z_{a,b}/Z_3)·(1 − 2·(Z_{a,b}/Z_3)·(f/f_p)^2)
       L_a   = W_3/2 − da、L_b = W_3/2 − db（主臂长度修正）
       r     = √(Z_a·Z_b)/Z_3、q = f²/(f_p,a·f_p,b)
       d2    = √(D_a·D_b)·(0.5 − r·(0.05+0.7·e^(−1.6r)+0.25·r·q−0.17·ln r))
       L_2   = max(W_1,W_2)/2 − d2          （支臂长度修正）
       T_a   = 1 − π(f/f_p,a)²·((Z_a/Z_3)²/12+(0.5−d2/D_a)²)（主臂变比，
                                             qucsator ≥NR_TINY 截断同构）
       Bt    = 5.5·√(D_a·D_b/(λ_a·λ_b))·(εr+2)/εr/Z_3/√(T_a·T_b)
             ·√(da·db)/D_3·(1+0.9·ln r+4.5·r·q−4.4·e^(−1.3r)−20·(Z_3/η0)²)
                                             （并联电纳，S）

   其中 W/Z/D/λ 取 m/Ω/m/m、λ_i=C0/√εeff_i/f；η0=376.73031346958504364963
   （qucs::Z0 同值）。Z_i/εeff_i 走仓内单源（skrf HJ，与
   microstrip_analysis 同口径；rf_line lazy import 先例）。f→0 极限：
   Bt→0（λ→∞）、T_a→1、da→0.055·D_3·Z_a/Z_3——准静态结构恒等锚。
   负长度修正（规范几何下即出现，如对称 50Ω 氧化铝 0.6mm@5GHz 的
   L_2≈−0.26mm）=参考面伸入结区的簿记值——qucsator 无守卫照常装配，
   本键放行并输出 reference_planes_crossed 标记位如实呈现；da·db<0
   （f 过近高阶模截止、√(da·db) 结构破裂）显式 ValueError。

4. 串联间隙（W11-S4；Garg-Bahl——qucsator msgap.cpp 可执行逐字转录，
   Qucs 技术手册 §Microstrip gap："两开路端+串联耦合电容"π 网络；等宽
   对称特化与第三方文献转写（Bahl《Microstrip Lines and Slotlines》
   [39] 口径，2018 论文在案 内部证据档）互证：
   Q1/Q2/Q3 常数与 (Q2+Q3)/(Q2+1) 修正结构逐项一致，2026-10-19 双源
   核对）：

       约定：W1'=min(W1,W2)/h、W2'=max(W1,W2)/min(W1,W2)（≥1，flip 后
       窄边进拟合）、s'=s/h
       Q5 = 1.23/(1+0.12·(W2'−1)^0.9)
       Q1 = 0.04598·(0.03+W1'^Q5)·(0.272+0.07·εr)
       Q2 = 0.107·(W1'+9)·s'^3.23 + 2.09·s'^1.05·(1.5+0.3·W1')/(1+0.6·W1')
       Q3 = e^(−0.5978·W2'^1.35)−0.55（窄边并联修正）
       Q4 = e^(−0.5978·W2'^−1.35)−0.55（宽边并联修正）
       Cs = 5e-10·h·e^(−1.86·s')·Q1·[1+4.19·(1−e^(−0.785·√(1/W1')·W2'))]
            （串联间隙电容；h 取 m → F）
       C_i = C_end,i·(Q2+Q_{3,4})/(Q2+1)   （两侧并联电容=Kirschning 开路
                                            端电容×Garg-Bahl 间隙修正）
       Y=[jω(C1+Cs) −jωCs; −jωCs jω(C2+Cs)] → 50Ω |S11|/|S21|（qucsator
       ytos 同构）

   validity（qucsator msgap.cpp 注释原文 "equations are valid for
   1 <= W2/W1 <= 3"）→ 宽比 >3 显式拒绝；g→∞ 时 Cs 指数归零；等宽
   W1=W2 时 C1==C2 逐位（flip 恒等锚）。qucsator 开路端基础电容走
   Kirschning 色散档——本键按仓内单源口径走 skrf HJ（与 T 接/阶跃同
   口径），色散模型差如实注记。ring_resonator._gap_capacitance_model
   （系数 1 量纲估计档，模块内 UNVERIFIED 如实标）为间隙电容占位实
   现，本键拟合式为其升级对拍面（后续仲裁批衔接）。

5. 开路端效应（W11-S4；Hammerstad-Bekkadal 0.412 档=仓内单源
   slotline_transitions.microstrip_open_end_delta_l_mm 复用（lazy
   import，coupled_line_bpf 同仓消费先例）+ Kirschning-Jansen-Koster
   1981 档=qucsator msopen.cpp calcCend "Kirschning" 段逐字；等效电
   容恒等式 C=Δl·√εeff/(Z0·c0)（msopen C 段与 Qucs 手册 eq.(11.192)
   "等效延长线变换为开路端电容"同式，第三方文献 CL=Cll·√εe/(Z0·c)
   互证））：

       Δl_K = Q1·Q3·Q5/Q4·h（Q1=0.434907·(Q6+0.26)/(Q6−0.189)·
             (Q7+0.236)/(Q7+0.87)、Q6=εeff^0.81、Q7=(W/h)^0.8544；
             Q2=(W/h)^0.371/(2.358εr+1)+1；Q3=atan(0.084(W/h)^
             (1.9413/Q2))·0.5274/εeff^0.9236+1；Q4=0.0377·(6−5e^
             (0.036(1−εr)))·atan(0.067(W/h)^1.456)+1；Q5=1−0.218·
             e^(−7.5·W/h)）
       C_end = Δl·√εeff/(Z0·c0)

   双档横向一致面（2026-10-20 全网格重测 117 点@2.5GHz）：
   ≤5% 一致带包络随 εr 渐宽——εr≤5 W/h≤2.0、εr 6–7 W/h≤2.5、
   εr 8 W/h≤3.0、εr 9 W/h≤3.5、εr 9.9 全 [0.3,5]；窄端 0.3@εr=2.2
   微越（5.1%），带外最宽点 16.5%@5.0/2.2——原声明
   "W/h∈[0.3,5]×εr∈[2.2,9.9]≤4.9%" 系子网格过声明（W12 审计
   P3 F-6 修正，越界点如实记不凑带）。边界：patch_fringing_delta_l（synthesis，
   patch 天线每边缘 fringing 修正）与本键=传输线开路端效应同族不同
   物件；qucsator 色散档同键 4 注记走 skrf HJ 单源。

3. 宽度阶跃（Garg-Bahl；qucsator msstep.cpp 可执行逐字转录，Qucs 技术
   手册 §Microstrip impedance step 引 Gupta [38] 转引面）：

       Cs = √(W1·W2)·[(10.1·lg εr+2.33)·(W1/W2) − 12.6·lg εr − 3.17]  pF
       Ls = h·[(r−1)·(40.5+0.2·(r−1)) − 75·lg r]（r=W1/W2）           nH

   （W/h 取 m/nH 口径同弯角。）串联 Ls 按两线单位长 L'_i=Z_i·√εeff_i/c0
   权重分摊（qucsator 同构：L_i=Ls·L'_i/(L'_1+L'_2)）。validity 如实：
   本拟合形态只收收窄阶跃——W1≤W2 时 Cs 括号为负（εr=9.9 零交叉在
   W1/W2≈1.27，介电常数越低越高）=拟合域外显式拒绝；W1=W2 时 Ls≡0
   （r−1=0 与 lg1=0 逐位）但 Cs<0，直通退化恒等经同文件 _step_ls 双
   路径锚（#118 roundtrip 同文件双路径）。

边界防撞（#222 triple-grep，2026-10-19 实测；W11-S4 扩面复检）
--------------------------------------------------------
- rf_line/microstrip_analysis=均匀线正反解（skrf HJ 单源，本键 T 接/阶跃
  内部复用同源 Z_i/εeff_i，不另立口径）；
- pcell_dsl/rf_trace_geometry=切角几何基元/面积（非寄生参数）；
- impedance_drc=DRC 警示面；coupled_microstrip=HB ΔW 线宽修正（均匀线）；
- patch_fringing_delta_l=patch 天线每边缘 fringing 修正（R3 判"已有不重
  做"——W11-S4 起传输线开路端效应由本族 microstrip_open_end_parasitics
  承接，patch 长度修正仍归 synthesis 单源）；
- amc_mushroom.amc_gap_capacitance_f=AMC 蘑菇单元间隙电容（周期结构面）/
  ring_resonator._gap_capacitance_model=环谐振器耦合间隙占位估计——与本
  族 microstrip_gap_parasitics（不连续寄生拟合式）物件不同层；
- fake_adapter._bend_sparams=模板级理想裁判面（寄生零）。
本族只做微带不连续寄生参数闭式（L/C/参考面修正/频响面）。

W11-S4 扩面 #222 triple-grep 复检（2026-10-19 实测）
--------------------------------------------------------
``microstrip_gap_parasitics|microstrip_open_end|open_end_parasitics|
gap_capacitance|msgap`` src/tests/scripts 三面：注册键零命中；语义邻面
仅 slotline_transitions.microstrip_open_end_delta_l_mm（Hammerstad 0.412
Δl core 函数、**非注册键**——本键复用为 HB 档单源+补 Kirschning 档与等
效电容面）、amc/ring_resonator 间隙电容（上列边界物件）、
layout_ports.ports_from_open_ends（版图端口提取，非寄生）——全为边界件
非覆盖；FMCW 侧 ``fmcw_chirp_design|chirp_slope|fmcw_if_signal_chain|
if_signal_chain`` 三面零命中（W7-S3 已收 range_doppler/
bandwidth_resolution 两键，本席做域内设计/链面扩展，isac no-go 同源尊
重）。待办清单 无四键处置注记；R3_domain_expansion A1/D5 为立项出处。

出处：Kirschning-Jansen-Koster 1983 MTT-S（弯角两档，经 Poole-Darwazeh
2015 Lecture 3 式(20)-(23) 与 TU/e van Meeteren thesis 双源逐字；50% 切
角档另有 qucsator msmbend.cpp 可执行同式）；Douville-James 1978 MTT-26(3)
pp.175-181（最优切角百分式，经 Microwaves101 Mitered Bends 与 rftools.io
Microstrip Mitered Bend Calculator 双网源逐字，W10-S4 补齐）；Hammerstad-
Bekkadal 1975 ELAB STF44 A74169（T 接头，经 qucsator mstee.cpp 可执行逐
字）；Garg-Bahl 1978（阶跃，经 qucsator msstep.cpp 可执行逐字，Qucs 手册
引 Gupta [38]）；Garg-Bahl（串联间隙，经 qucsator msgap.cpp 可执行逐字
转录——Qucs 手册 §Microstrip gap 归 [37]/[30]；等宽特化与 Bahl
《Microstrip Lines and Slotlines》[39] 口径第三方文献转写互证，
内部证据档 在案）；Kirschning-Jansen-Koster 1981
Electron. Lett.（开路端等效延长，经 qucsator msopen.cpp calcCend
"Kirschning" 段可执行逐字；Hammerstad-Bekkadal 0.412 档=仓内单源
slotline_transitions.microstrip_open_end_delta_l_mm 复用；等效电容恒等式
经 msopen C 段+第三方文献 CL=Cll·√εe/(Z0·c) 互证）——W11-S4 两件网源
逐字在 内部证据档。
"""

from __future__ import annotations

import math

from .registry import register_calculator

#: 真空波阻抗 η0（qucs::Z0 同值，qucsator src/constants.h L54 逐字）
_ETA0_OHM = 376.73031346958504364963
#: 光速 m/s（与 _ETA0 配套的 T 接波长/单位长 L' 权重口径）
_C0_M_S = 299792458.0


def _finite_pos(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if v != v or v in (float("inf"), float("-inf")) or v <= 0.0:
        raise ValueError(f"{key}: {name} 必须 >0 且有限，得 {value!r}")
    return v


def _finite(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"{key}: {name} 必须有限，得 {value!r}")
    return v


def _bend_network_s11_db(l_nh: float, c_pf: float, freq_ghz: float,
                         z_ref: float = 50.0) -> float:
    """对称 T 网络（串联 L×2+并联 C）在 z_ref 参考下的 |S11|（dB）。

    ABCD = Series(Z_L)·Shunt(Y_C)·Series(Z_L)；S11=(a+b/Z−cZ−d)/全和
    （fake_adapter._atten_pi_sparams 同构路径）。"""
    omega = 2.0 * math.pi * freq_ghz * 1e9
    z_l = 1j * omega * l_nh * 1e-9
    y_c = 1j * omega * c_pf * 1e-12
    a = 1.0 + z_l * y_c
    b = 2.0 * z_l + z_l * z_l * y_c
    c = y_c
    d = a
    num = a + b / z_ref - c * z_ref - d
    den = a + b / z_ref + c * z_ref + d
    return 20.0 * math.log10(abs(num / den))


@register_calculator(
    "microstrip_bend_parasitics",
    "微带直角弯寄生：未切角/50% 切角双档等效 L/C 与频响面"
    "（Kirschning 1983 两档；50% 切角档=qucsator msmbend.cpp 可执行同式）。"
    "T 网络串联 L—并联 C—串联 L；validity W/h∈[0.2,6]、εr∈[2.36,10.4]、"
    "f·h≤12GHz·mm、精度~0.3%。未切角 L 在 W/h≲1.4 为负=拟合域外显式拒绝。"
    "给 freq_ghz 时出 50Ω 参考 |S11|（fake_adapter 弯角寄生门 −15dB 同量级"
    "对拍面）",
    (("width_mm", "float mm 弯角线宽 W"),
     ("h_mm", "float mm 基板厚度 h"),
     ("epsilon_r", "float 基板相对介电常数 εr（[2.36,10.4]）"),
     ("freq_ghz", "float GHz 求频响面频率（可选；缺省只出 L/C 参数面）")),
    required=("width_mm", "h_mm", "epsilon_r"),
)
def microstrip_bend_parasitics(width_mm: float, h_mm: float,
                               epsilon_r: float,
                               freq_ghz: float | None = None) -> dict:
    key = "microstrip_bend_parasitics"
    w_mm = _finite_pos(key, "width_mm", width_mm)
    h_mm = _finite_pos(key, "h_mm", h_mm)
    er = _finite(key, "epsilon_r", epsilon_r)
    if not 2.36 <= er <= 10.4:
        raise ValueError(
            f"{key}: εr 域 [2.36,10.4]（KJK 拟合原文），得 {epsilon_r!r}")
    u = w_mm / h_mm
    if not 0.2 <= u <= 6.0:
        raise ValueError(
            f"{key}: W/h 域 [0.2,6]（KJK 拟合原文），得 {u!r}")

    # 未切角（式 20/21 逐字；C 的 W、L 的 h 取 SI m → pF/nH）
    c_plain_pf = 1e-3 * w_mm * ((10.35 * er + 2.5) * u + (2.6 * er + 5.64))
    l_plain_nh = 220.0 * h_mm * 1e-3 * (
        1.0 - 1.35 * math.exp(-0.18 * u ** 1.39))
    # 50% 切角（式 22/23 逐字 = qucsator msmbend.cpp）
    c_mit_pf = 1e-3 * w_mm * ((3.93 * er + 0.62) * u + (7.6 * er + 3.80))
    l_mit_nh = 440.0 * h_mm * 1e-3 * (
        1.0 - 1.062 * math.exp(-0.177 * u ** 0.947))
    if l_plain_nh <= 0.0 or l_mit_nh <= 0.0:
        raise ValueError(
            f"{key}: L≤0（未切角式拟合域外 W/h≲1.4，TU/e thesis 明示 "
            f"'validity limited to w/h≳1'），W/h={u!r}——如实拒绝")

    out: dict = {
        "width_mm": w_mm,
        "h_mm": h_mm,
        "epsilon_r": er,
        "w_over_h": u,
        # 未切角档
        "c_unmitered_pf": c_plain_pf,
        "l_unmitered_nh": l_plain_nh,
        # 50% 切角档
        "c_mitered50_pf": c_mit_pf,
        "l_mitered50_nh": l_mit_nh,
        "note": ("50% 切角=45°、切角量 x=W/2（Douville-James 1978 实测结论："
                 "对全部宽度/基板/频率均改善反射）；最优切角百分式见同文件 "
                 "microstrip_optimal_miter 键（W10-S4 双网源补齐）"),
    }
    if freq_ghz is not None:
        f_ghz = _finite_pos(key, "freq_ghz", freq_ghz)
        if f_ghz * h_mm > 12.0:
            raise ValueError(
                f"{key}: f·h≤12 GHz·mm（模型频散上限原文），得 "
                f"{f_ghz!r}GHz×{h_mm!r}mm")
        out["freq_ghz"] = f_ghz
        out["s11_unmitered_db"] = _bend_network_s11_db(
            l_plain_nh, c_plain_pf, f_ghz)
        out["s11_mitered50_db"] = _bend_network_s11_db(
            l_mit_nh, c_mit_pf, f_ghz)
    return out


def _line_z0_eps_eff(width_mm: float, freq_ghz: float, epsilon_r: float,
                     h_mm: float) -> tuple[float, float]:
    """skrf HJ 单源 (Z0, εeff)——与 rf_line._microstrip_media 同口径。"""
    import skrf

    media = skrf.media.MLine(
        frequency=skrf.Frequency(freq_ghz, freq_ghz, 1, unit="GHz"),
        w=width_mm * 1e-3, h=h_mm * 1e-3, ep_r=epsilon_r, tand=0.0,
        model="hammerstadjensen",
    )
    z0 = float(abs(complex(media.z0[0])))
    eps_eff = float(complex(media.ep_reff[0]).real)
    return z0, eps_eff


@register_calculator(
    "microstrip_t_junction_parasitics",
    "微带 T 接头寄生：Hammerstad-Bekkadal 等效电路（qucsator mstee.cpp "
    "可执行逐字）——主臂/支臂参考面位移 da/db/d2、臂长修正 La/Lb/L2、主臂 "
    "变比 Ta/Tb、并联电纳 Bt。Z/εeff 走 skrf HJ 仓内单源。f→0 极限 Bt→0、"
    "Ta→1（准静态恒等锚）；参考面交叉（L≤0）显式拒绝",
    (("w1_mm", "float mm 主臂 A 线宽（port1→port2 直通主臂一侧）"),
     ("w2_mm", "float mm 主臂 B 线宽（port1→port2 直通主臂另一侧）"),
     ("w3_mm", "float mm 支臂线宽（port3）"),
     ("h_mm", "float mm 基板厚度"),
     ("epsilon_r", "float 基板相对介电常数（≥1）"),
     ("freq_ghz", "float GHz 工作频率（>0；须低于高阶模截止）")),
    required=("w1_mm", "w2_mm", "w3_mm", "h_mm", "epsilon_r", "freq_ghz"),
)
def microstrip_t_junction_parasitics(w1_mm: float, w2_mm: float,
                                     w3_mm: float, h_mm: float,
                                     epsilon_r: float,
                                     freq_ghz: float) -> dict:
    key = "microstrip_t_junction_parasitics"
    wa = _finite_pos(key, "w1_mm", w1_mm)
    wb = _finite_pos(key, "w2_mm", w2_mm)
    w3 = _finite_pos(key, "w3_mm", w3_mm)
    h_m = _finite_pos(key, "h_mm", h_mm) * 1e-3
    er = _finite(key, "epsilon_r", epsilon_r)
    if er < 1.0:
        raise ValueError(
            f"{key}: εr≥1（空气微带不在 skrf HJ 模型域，microstrip_analysis "
            f"同口径守卫），得 {epsilon_r!r}")
    f_hz = _finite_pos(key, "freq_ghz", freq_ghz) * 1e9

    za, eps_a = _line_z0_eps_eff(wa, freq_ghz, er, h_m * 1e3)
    zb, eps_b = _line_z0_eps_eff(wb, freq_ghz, er, h_m * 1e3)
    z3, eps_3 = _line_z0_eps_eff(w3, freq_ghz, er, h_m * 1e3)

    # 等效平行板线宽与高阶模截止（HB/qucsator 逐字）
    da_w = _ETA0_OHM / za * h_m / math.sqrt(eps_a)
    db_w = _ETA0_OHM / zb * h_m / math.sqrt(eps_b)
    d3_w = _ETA0_OHM / z3 * h_m / math.sqrt(eps_3)
    fp_a = 0.4e6 * za / h_m
    fp_b = 0.4e6 * zb / h_m
    lda = _C0_M_S / math.sqrt(eps_a) / f_hz
    ldb = _C0_M_S / math.sqrt(eps_b) / f_hz

    # 主臂参考面位移与长度修正（qucsator 逐字）
    da = 0.055 * d3_w * za / z3 * (1.0 - 2.0 * za / z3 * (f_hz / fp_a) ** 2)
    db = 0.055 * d3_w * zb / z3 * (1.0 - 2.0 * zb / z3 * (f_hz / fp_b) ** 2)
    la = 0.5 * w3 * 1e-3 - da
    lb = 0.5 * w3 * 1e-3 - db

    # 支臂位移与长度修正（qucsator 逐字）
    r = math.sqrt(za * zb) / z3
    q = (f_hz * f_hz) / (fp_a * fp_b)
    d2 = math.sqrt(da_w * db_w) * (
        0.5 - r * (0.05 + 0.7 * math.exp(-1.6 * r)
                   + 0.25 * r * q - 0.17 * math.log(r)))
    l2 = 0.5 * max(wa, wb) * 1e-3 - d2

    if da * db < 0.0:
        raise ValueError(
            f"{key}: da·db<0（f 过近高阶模截止 f_p，参考面位移异号——HB "
            "模型域外结构性破裂）——如实拒绝")

    # 主臂变比（qucsator NR_TINY 截断同构）
    ta = 1.0 - math.pi * (f_hz / fp_a) ** 2 * (
        (za / z3) ** 2 / 12.0 + (0.5 - d2 / da_w) ** 2)
    tb = 1.0 - math.pi * (f_hz / fp_b) ** 2 * (
        (zb / z3) ** 2 / 12.0 + (0.5 - d2 / db_w) ** 2)
    ta = max(ta, 1e-300)
    tb = max(tb, 1e-300)

    # 并联电纳（qucsator 逐字）
    bt = (5.5 * math.sqrt(da_w * db_w / lda / ldb) * (er + 2.0) / er / z3
          / math.sqrt(ta * tb) * math.sqrt(da * db) / d3_w
          * (1.0 + 0.9 * math.log(r) + 4.5 * r * q
             - 4.4 * math.exp(-1.3 * r) - 20.0 * (z3 / _ETA0_OHM) ** 2))

    return {
        "w1_mm": wa, "w2_mm": wb, "w3_mm": w3, "h_mm": h_m * 1e3,
        "epsilon_r": er, "freq_ghz": f_hz / 1e9,
        "z0_main_a_ohm": za, "z0_main_b_ohm": zb, "z0_side_ohm": z3,
        "eps_eff_main_a": eps_a, "eps_eff_main_b": eps_b,
        "eps_eff_side": eps_3,
        "fp_main_a_ghz": fp_a / 1e9, "fp_main_b_ghz": fp_b / 1e9,
        "d_ref_a_mm": da * 1e3, "d_ref_b_mm": db * 1e3,
        "d_ref_side_mm": d2 * 1e3,
        "l_main_a_mm": la * 1e3, "l_main_b_mm": lb * 1e3,
        "l_side_mm": l2 * 1e3,
        "turn_ratio_a": ta, "turn_ratio_b": tb,
        "shunt_susceptance_s": bt,
        "r_ratio": r, "q_sq": q,
        # 负长度=参考面伸入结区的簿记修正（qucsator 无守卫照常装配，语义
        # 如实标记给消费者；da·db<0 的结构性破裂已在上游显式拒绝）
        "reference_planes_crossed": bool(la < 0.0 or lb < 0.0 or l2 < 0.0),
    }


def _step_cs_pf(w1_mm: float, w2_mm: float, er: float) -> float:
    """阶跃并联电容（Garg-Bahl/qucsator 逐字；W 取 mm → pF）。"""
    ratio = w1_mm / w2_mm
    bracket = ((10.1 * math.log10(er) + 2.33) * ratio
               - 12.6 * math.log10(er) - 3.17)
    return 1e-3 * math.sqrt(w1_mm * w2_mm) * bracket


def _step_ls_nh(w1_mm: float, w2_mm: float, h_mm: float) -> float:
    """阶跃串联总电感（Garg-Bahl/qucsator 逐字；h 取 mm → nH）。

    W1=W2 退化恒等：r−1=0 与 lg(1)=0 双项逐位归零 → Ls≡0（#118 同文件
    双路径锚的内部路径）。"""
    ratio = w1_mm / w2_mm
    dr = ratio - 1.0
    return h_mm * 1e-3 * (dr * (40.5 + 0.2 * dr) - 75.0 * math.log10(ratio))


@register_calculator(
    "microstrip_step_parasitics",
    "微带宽度阶跃寄生：Garg-Bahl 等效 L/C（qucsator msstep.cpp 可执行逐字）"
    "——并联 Cs+串联 Ls 按两线单位长 L'=Z√εeff/c0 权重分摊。Z/εeff 走 skrf "
    "HJ 仓内单源。拟合形态只收收窄阶跃（W1>W2 且 Cs>0；εr=9.9 零交叉 "
    "W1/W2≈1.27）——W1≤W2 拒绝不凑",
    (("w1_mm", "float mm 宽线宽 W1（收窄侧，>W2）"),
     ("w2_mm", "float mm 窄线宽 W2（<W1）"),
     ("h_mm", "float mm 基板厚度"),
     ("epsilon_r", "float 基板相对介电常数（≥1）"),
     ("freq_ghz", "float GHz 线参数求值频率（>0）")),
    required=("w1_mm", "w2_mm", "h_mm", "epsilon_r", "freq_ghz"),
)
def microstrip_step_parasitics(w1_mm: float, w2_mm: float, h_mm: float,
                               epsilon_r: float, freq_ghz: float) -> dict:
    key = "microstrip_step_parasitics"
    wa = _finite_pos(key, "w1_mm", w1_mm)
    wb = _finite_pos(key, "w2_mm", w2_mm)
    h = _finite_pos(key, "h_mm", h_mm)
    er = _finite(key, "epsilon_r", epsilon_r)
    if er < 1.0:
        raise ValueError(
            f"{key}: εr≥1（skrf HJ 模型域守卫），得 {epsilon_r!r}")
    _ = _finite_pos(key, "freq_ghz", freq_ghz)
    if wa <= wb:
        raise ValueError(
            f"{key}: 本拟合形态只收收窄阶跃 W1>W2（W1=W2 直通无阶跃且 Cs "
            f"括号为负；展宽 W1<W2 同为域外），得 {w1_mm!r}→{w2_mm!r}")
    cs_pf = _step_cs_pf(wa, wb, er)
    if cs_pf <= 0.0:
        raise ValueError(
            f"{key}: Cs≤0（Garg-Bahl 拟合零交叉 W1/W2≈1.27@εr=9.9 以下，"
            f"域外不凑），W1/W2={wa / wb!r}、εr={er!r}")
    ls_nh = _step_ls_nh(wa, wb, h)

    za, eps_a = _line_z0_eps_eff(wa, freq_ghz, er, h)
    zb, eps_b = _line_z0_eps_eff(wb, freq_ghz, er, h)
    lp1 = za * math.sqrt(eps_a) / _C0_M_S   # 单位长 L'（H/m）权重
    lp2 = zb * math.sqrt(eps_b) / _C0_M_S
    wgt1 = lp1 / (lp1 + lp2)
    return {
        "w1_mm": wa, "w2_mm": wb, "h_mm": h, "epsilon_r": er,
        "freq_ghz": freq_ghz,
        "c_shunt_pf": cs_pf,
        "l_series_total_nh": ls_nh,
        "l_series_port1_nh": ls_nh * wgt1,
        "l_series_port2_nh": ls_nh * (1.0 - wgt1),
        "weight_port1": wgt1,
        "z0_wide_ohm": za, "z0_narrow_ohm": zb,
        "eps_eff_wide": eps_a, "eps_eff_narrow": eps_b,
    }


@register_calculator(
    "microstrip_optimal_miter",
    "微带弯最优切角：Douville-James 1978 实测拟合（Microwaves101/"
    "rftools.io 双网源逐字核对）切角百分比 M=52+65·exp(−1.35·W/h)——"
    "对角线切深 X=M·D/100（D=W√2 未切角对角全长）、外缘切边长 "
    "a=X·√2（纯几何换算）。与 εr、频率无关（实测域 εr∈[2.5,25]）；"
    "W/h∈[0.25,2.75] 实测域显式守卫（W/h<0.225 外推 M>100% 域外）。"
    "与 KJK 50% 切角档（同文件 microstrip_bend_parasitics）成宽/窄线"
    "互补档",
    (("width_mm", "float mm 弯角线宽 W（>0）"),
     ("h_mm", "float mm 基板厚度 h（>0）")),
    required=("width_mm", "h_mm"),
)
def microstrip_optimal_miter(width_mm: float, h_mm: float) -> dict:
    key = "microstrip_optimal_miter"
    w_mm = _finite_pos(key, "width_mm", width_mm)
    h_mm = _finite_pos(key, "h_mm", h_mm)
    u = w_mm / h_mm
    # Douville-James 实测域（两网源一致：0.25≤W/H≤2.75、εr 2.5-25、
    # 与 εr/频率无关；W/h<0.225 拟合外推 M>100%（切过内角）显式拒绝）
    if not 0.25 <= u <= 2.75:
        raise ValueError(
            f"{key}: W/h={u!r} 在 Douville-James 实测域 [0.25,2.75] 外"
            f"（W/h≲0.225 外推 M>100% 切过内角=非物理），得 "
            f"w_mm={w_mm!r}, h_mm={h_mm!r}")

    miter_percent = 52.0 + 65.0 * math.exp(-1.35 * u)
    if not 0.0 < miter_percent < 100.0:
        raise ValueError(
            f"{key}: M={miter_percent!r}% 出 (0,100)（拟合域结构性守卫）")
    diag_mm = w_mm * math.sqrt(2.0)          # 未切角对角全长 D
    cut_depth_mm = miter_percent * diag_mm / 100.0   # 对角线切深 X
    # 切边长 a=X·√2（切线垂直于对角线、与两外缘交点距角 a 的纯几何换算；
    # = M·W/50——M=50% 档切边长恰=W 的几何自检锚）
    chamfer_leg_mm = cut_depth_mm * math.sqrt(2.0)
    return {
        "width_mm": w_mm, "h_mm": h_mm, "w_over_h": u,
        "miter_percent": miter_percent,
        "diagonal_mm": diag_mm,
        "cut_depth_mm": cut_depth_mm,
        "chamfer_leg_mm": chamfer_leg_mm,
        # 切边长/线宽比（纯几何恒等 M/50，同文件双路径锚内部路径）
        "chamfer_over_width": chamfer_leg_mm / w_mm,
        "note": ("M=52+65·exp(−1.35·W/h)%（Douville-James 1978 实测拟合，"
                 "对 εr/频率无关；X 沿对角线自外角量起，a=X√2 为外缘切"
                 "边长=M·W/50 纯几何恒等）。M=100% ⇔ 切线过内角（X=D "
                 "全长）；宽线渐近 52%（50% 切角 rule-of-thumb 只对宽线"
                 "成立）；同文件 KJK 50% 切角档（切边 W/2）在本口径为 "
                 "M=25%——两约定经 a=M·W/50 互译"),
    }


def _open_end_dl_kirschning_m(w_mm: float, h_mm: float, epsilon_r: float,
                              eps_eff: float) -> float:
    """Kirschning-Jansen-Koster 1981 开路端等效延长 Δl（m）。

    qucsator msopen.cpp calcCend "Kirschning" 段逐字（dl 归一 h 段；
    色散 εeff/Z0 由调用方按仓内单源 skrf HJ 给出）。"""
    u = w_mm / h_mm
    q6 = eps_eff ** 0.81
    q7 = u ** 0.8544
    q1 = (0.434907 * (q6 + 0.26) / (q6 - 0.189)
          * (q7 + 0.236) / (q7 + 0.87))
    q2 = u ** 0.371 / (2.358 * epsilon_r + 1.0) + 1.0
    q3 = (math.atan(0.084 * u ** (1.9413 / q2)) * 0.5274
          / eps_eff ** 0.9236 + 1.0)
    q4 = (0.0377 * (6.0 - 5.0 * math.exp(0.036 * (1.0 - epsilon_r)))
          * math.atan(0.067 * u ** 1.456) + 1.0)
    q5 = 1.0 - 0.218 * math.exp(-7.5 * u)
    return q1 * q3 * q5 / q4 * h_mm * 1e-3


def _open_end_capacitance_f(dl_m: float, eps_eff: float,
                            z0_ohm: float) -> float:
    """开路端等效电容 C=Δl·√εeff/(Z0·c0)（F）。

    等效延长线段电容恒等式（qucsator msopen.cpp C 段与 Qucs 手册
    eq.(11.192) 同式：等效延长线变换为开路端电容）。"""
    return dl_m * math.sqrt(eps_eff) / z0_ohm / _C0_M_S


@register_calculator(
    "microstrip_open_end_parasitics",
    "微带开路端效应（W11-S4）：等效长度延长 Δl 双档——Hammerstad-Bekkadal "
    "0.412 档（仓内单源 slotline_transitions 复用）+Kirschning-Jansen-"
    "Koster 1981 档（qucsator msopen.cpp 可执行逐字）——加等效电容恒等式 "
    "C=Δl·√εeff/(Z0·c0) 双档输出。Z/εeff 走 skrf HJ 仓内单源（qucsator "
    "Kirschning 色散档不在口径，注记如实）。双档横向一致带 ≤5%（数值锤 "
    "W/h∈[0.3,5]），非逐位如实",
    (("width_mm", "float mm 开路线宽 W"),
     ("h_mm", "float mm 基板厚度 h"),
     ("epsilon_r", "float 基板相对介电常数（≥1）"),
     ("freq_ghz", "float GHz 线参数求值频率（>0）")),
    required=("width_mm", "h_mm", "epsilon_r", "freq_ghz"),
)
def microstrip_open_end_parasitics(width_mm: float, h_mm: float,
                                   epsilon_r: float,
                                   freq_ghz: float) -> dict:
    key = "microstrip_open_end_parasitics"
    w_mm = _finite_pos(key, "width_mm", width_mm)
    h = _finite_pos(key, "h_mm", h_mm)
    er = _finite(key, "epsilon_r", epsilon_r)
    if er < 1.0:
        raise ValueError(
            f"{key}: εr≥1（skrf HJ 模型域守卫，T 接/阶跃同口径），得 "
            f"{epsilon_r!r}")
    _ = _finite_pos(key, "freq_ghz", freq_ghz)

    # HB 0.412 档：仓内单源复用（lazy import，coupled_line_bpf 先例）
    from rfauto.core.slotline_transitions import (
        microstrip_open_end_delta_l_mm,
    )

    z0, eps_eff = _line_z0_eps_eff(w_mm, freq_ghz, er, h)
    dl_hb_mm = microstrip_open_end_delta_l_mm(w_mm, h, eps_eff)
    dl_k_m = _open_end_dl_kirschning_m(w_mm, h, er, eps_eff)
    if dl_k_m <= 0.0:
        raise ValueError(
            f"{key}: Kirschning Δl≤0（拟合域结构性破裂），得 {dl_k_m!r}")
    return {
        "width_mm": w_mm, "h_mm": h, "epsilon_r": er, "freq_ghz": freq_ghz,
        "z0_ohm": z0, "eps_eff": eps_eff,
        "dl_hammerstad_mm": dl_hb_mm,
        "dl_kirschning_mm": dl_k_m * 1e3,
        # 等效电容恒等式双档（C=Δl·√εeff/(Z0·c0)）
        "c_end_f": _open_end_capacitance_f(dl_k_m, eps_eff, z0),
        "c_end_hammerstad_f": _open_end_capacitance_f(
            dl_hb_mm * 1e-3, eps_eff, z0),
        "dual_model_rel_diff": dl_k_m * 1e3 / dl_hb_mm - 1.0,
        "note": ("HB 0.412 档=仓内单源（slotline_transitions）复用；"
                 "Kirschning 档=qucsator msopen.cpp 逐字；qucsator 的 "
                 "Kirschning 色散 εeff/Z0 档不在本键口径（skrf HJ 单源）"),
    }


@register_calculator(
    "microstrip_gap_parasitics",
    "微带串联间隙寄生（W11-S4）：Garg-Bahl π 网络电容（qucsator msgap.cpp "
    "可执行逐字）——串联 Cs+两侧并联 C_i（Kirschning 开路端电容×Garg-Bahl "
    "(Q2+Q_{3,4})/(Q2+1) 间隙修正），出 50Ω 参考 |S11|/|S21|。Z/εeff 走 "
    "skrf HJ 仓内单源。宽比 W2/W1≤3（msgap.cpp 注释原文 validity），越界"
    "显式拒绝；g→∞ 时 Cs 指数归零、等宽 C1==C2 逐位",
    (("w1_mm", "float mm 端口 1 侧线宽 W1"),
     ("w2_mm", "float mm 端口 2 侧线宽 W2"),
     ("gap_mm", "float mm 间隙宽度 s（>0）"),
     ("h_mm", "float mm 基板厚度"),
     ("epsilon_r", "float 基板相对介电常数（≥1）"),
     ("freq_ghz", "float GHz 工作频率（>0）")),
    required=("w1_mm", "w2_mm", "gap_mm", "h_mm", "epsilon_r", "freq_ghz"),
)
def microstrip_gap_parasitics(w1_mm: float, w2_mm: float, gap_mm: float,
                              h_mm: float, epsilon_r: float,
                              freq_ghz: float) -> dict:
    key = "microstrip_gap_parasitics"
    wa = _finite_pos(key, "w1_mm", w1_mm)
    wb = _finite_pos(key, "w2_mm", w2_mm)
    s_mm = _finite_pos(key, "gap_mm", gap_mm)
    h = _finite_pos(key, "h_mm", h_mm)
    er = _finite(key, "epsilon_r", epsilon_r)
    if er < 1.0:
        raise ValueError(
            f"{key}: εr≥1（skrf HJ 模型域守卫，T 接/阶跃同口径），得 "
            f"{epsilon_r!r}")
    f_hz = _finite_pos(key, "freq_ghz", freq_ghz) * 1e9

    # qucsator msgap flip：窄边进拟合（W2/W1=max/min ≥1）
    flip = wb < wa
    w_lo, w_hi = (wb, wa) if flip else (wa, wb)
    ratio = w_hi / w_lo
    if ratio > 3.0:
        raise ValueError(
            f"{key}: 宽比 W2/W1={ratio!r} 超 validity（qucsator msgap.cpp "
            "注释原文 'equations are valid for 1 <= W2/W1 <= 3'）——如实拒绝")

    z_lo, ee_lo = _line_z0_eps_eff(w_lo, freq_ghz, er, h)
    z_hi, ee_hi = _line_z0_eps_eff(w_hi, freq_ghz, er, h)
    # 开路端基础电容（Kirschning Δl→C 恒等式；msgap calcCend 同位）
    c1_base = _open_end_capacitance_f(
        _open_end_dl_kirschning_m(w_lo, h, er, ee_lo), ee_lo, z_lo)
    c2_base = _open_end_capacitance_f(
        _open_end_dl_kirschning_m(w_hi, h, er, ee_hi), ee_hi, z_hi)

    # Garg-Bahl 间隙块（qucsator 逐字：W2'=宽比、W1'=窄边/h、s'=s/h）
    w2r = ratio
    u1 = w_lo / h
    s_n = s_mm / h
    q5 = 1.23 / (1.0 + 0.12 * (w2r - 1.0) ** 0.9)
    q1 = 0.04598 * (0.03 + u1 ** q5) * (0.272 + 0.07 * er)
    q2 = (0.107 * (u1 + 9.0) * s_n ** 3.23
          + 2.09 * s_n ** 1.05 * (1.5 + 0.3 * u1) / (1.0 + 0.6 * u1))
    q3 = math.exp(-0.5978 * w2r ** 1.35) - 0.55
    q4 = math.exp(-0.5978 * w2r ** -1.35) - 0.55
    cs = (5e-10 * h * 1e-3 * math.exp(-1.86 * s_n) * q1
          * (1.0 + 4.19 * (1.0 - math.exp(-0.785 * math.sqrt(1.0 / u1)
                                          * w2r))))
    if cs <= 0.0:
        raise ValueError(
            f"{key}: Cs≤0（拟合结构破裂非物理），得 {cs!r}")
    c1 = c1_base * (q2 + q3) / (q2 + 1.0)   # 窄边侧
    c2 = c2_base * (q2 + q4) / (q2 + 1.0)   # 宽边侧
    if flip:
        c1, c2 = c2, c1                      # 端口翻回原序（qucsator 同构）

    # π 网络 Y 矩阵→50Ω S（qucsator ytos 同构，手推闭式）
    omega = 2.0 * math.pi * f_hz
    y11 = 1j * omega * (c1 + cs)
    y22 = 1j * omega * (c2 + cs)
    y12 = -1j * omega * cs
    yn11, yn22, yn12 = y11 * 50.0, y22 * 50.0, y12 * 50.0
    den = (1.0 + yn11) * (1.0 + yn22) - yn12 * yn12
    s11 = ((1.0 + yn22) * (1.0 - yn11) + yn12 * yn12) / den
    s21 = -2.0 * yn12 / den
    return {
        "w1_mm": wa, "w2_mm": wb, "gap_mm": s_mm, "h_mm": h,
        "epsilon_r": er, "freq_ghz": freq_ghz,
        "c_series_gap_f": cs,
        "c_shunt_port1_f": c1, "c_shunt_port2_f": c2,
        "c_open_end_base_port1_f": (c2_base if flip else c1_base),
        "c_open_end_base_port2_f": (c1_base if flip else c2_base),
        "s11_db": 20.0 * math.log10(abs(s11)),
        "s21_db": 20.0 * math.log10(abs(s21)),
        "q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5,
        "width_ratio": ratio,
        "equal_width": bool(wa == wb),
        "note": ("π 网络=两修正开路端并联电容+串联间隙电容（Garg-Bahl，"
                 "qucsator msgap.cpp 逐字）；开路端基础电容走 Kirschning "
                 "Δl→C 恒等式（skrf HJ 单源，qucsator 色散档不在口径）"),
    }
