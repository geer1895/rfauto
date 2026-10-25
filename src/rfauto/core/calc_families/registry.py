"""注册表单源（CalculatorSpec/CalculatorRegistry/CALCULATOR_REGISTRY/register_calculator + C_MM_GHZ）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rfauto.core.registry_kit import RegistryKit

C_MM_GHZ = 299.792458  # mm·GHz（光速，f[GHz]×λ[mm]=此值）


# ─── 工具箱分组单源表（aurora72 A2-A，2026-10-11；分组方案=内部证据档
# R5_tools_audit.md §② 程序验证零漏零重版）────────────────────────────────
# 键 → 组名。describe() 每键输出 group（CalculatorSpec.group 显式声明优先，
# 未声明键查本表，表外键落 DEFAULT_CALC_GROUP="其他"——新键注册未同步本表
# 不报错但落"其他"，test_calculators 的组完备性钉会点名，注册须同步）。
# CALC_GROUP_ORDER 为 UI optgroup 建议序（按"日常使用频率×自包含度"排，
# 实验组殿后；"其他"恒在最后）；calculator_service.list_calculators 信封
# 以 group_order 字段透传同表（单源）。
DEFAULT_CALC_GROUP = "其他"

CALC_GROUP_ORDER: tuple[str, ...] = (
    "传输线正反解",
    "匹配·功分·衰减·耦合",
    "滤波器与耦合矩阵",
    "谐振器与腔体",
    "天线与阵列",
    "DOA 与波束形成",
    "MIMO 与 RIS",
    "雷达",
    "链路与传播",
    "收发链路·频综",
    "调制与数字链路",
    "EMC·安规·放电",
    "热·功率·可靠性",
    "测量与校准",
    "超材料·超表面",
    "量子读出",
    "实验",
)

CALC_GROUP_TABLE: dict[str, str] = {
    # ── 传输线正反解（40）────
    "microstrip_analysis": "传输线正反解",
    "microstrip_synthesis": "传输线正反解",
    "microstrip_lambda_g": "传输线正反解",
    # aurora_g W6-S3 微带不连续寄生三键（R3 视角1 A1 Top1 跨视角双归属
    # ——均匀线正反解之外的不连续寄生闭式；fake_adapter 弯角寄生门消费
    # 面背书，边界见 microstrip_disc.py 模块 docstring）
    "microstrip_bend_parasitics": "传输线正反解",
    "microstrip_t_junction_parasitics": "传输线正反解",
    "microstrip_step_parasitics": "传输线正反解",
    # aurora_g W10-S4 微带最优切角键（Douville-James 1978 实测拟合，W6-S3
    # 因系数表不可达不 ship、本席双网源逐字补齐；同文件 KJK 50% 切角档
    # 跨约定互译见键面 note）
    "microstrip_optimal_miter": "传输线正反解",
    # aurora_g W11-S4 微带不连续全族扩展两键（串联间隙 Garg-Bahl π 网络
    # +开路端效应 Δl 双档——W6-S3 三键的全族收尾；边界见 microstrip_disc.py
    # 模块 docstring）
    "microstrip_gap_parasitics": "传输线正反解",
    "microstrip_open_end_parasitics": "传输线正反解",
    # aurora_g W15-S2 微带全族扩展四键（R3_domain_expansion §④ A1 余量
    # +损耗/接地过渡族收口——十字结=不连续族第七件；衰减率=coax/波导有、
    # 微带独缺的同族不对称补口；接地过孔=G-P 1991（qucsator msvia.cpp
    # 漏 2π 偏差注记在案）；开路端辐射电导=Balanis 两极限分段式。边界见
    # microstrip_extra.py 模块 docstring）
    "microstrip_cross_parasitics": "传输线正反解",
    "microstrip_attenuation": "传输线正反解",
    "microstrip_via_short": "传输线正反解",
    "microstrip_open_end_radiation": "传输线正反解",
    # aurora_g W10-S4 平衡开线族两键（R3 视角1 A2——rf_line 第七线型：
    # 开架双线/单线对地精确式，twin|open_wire|明线 三面零命中补口；
    # 边界见 open_wire_line.py 模块 docstring）
    "open_two_wire_line": "传输线正反解",
    "open_wire_over_ground": "传输线正反解",
    "cpw_analysis": "传输线正反解",
    "cpw_synthesis": "传输线正反解",
    "cpwg_analysis": "传输线正反解",
    "cpwg_synthesis": "传输线正反解",
    "cps_analysis": "传输线正反解",
    "cps_synthesis": "传输线正反解",
    "stripline_analysis": "传输线正反解",
    "stripline_synthesis": "传输线正反解",
    "suspended_stripline_analysis": "传输线正反解",
    "suspended_stripline_synthesis": "传输线正反解",
    "slotline_analysis": "传输线正反解",
    "slotline_synthesis": "传输线正反解",
    "siw_analysis": "传输线正反解",
    "siw_synthesis": "传输线正反解",
    # aurora_d W3-CORE8 一键（2026-10-14，R7-PREP G16 可选件"λg 闭式抽
    # 独立键"：TE10 λg/λc/β 传播参数面，内部复用 waveguide_iris._
    # frequency 单源零公式复制；slot_array 内嵌 λg/microstrip_lambda_g
    # 准 TEM 分层不撞，边界见 waveguide_iris.py 模块 docstring）
    "waveguide_lambda_g": "传输线正反解",
    # aurora72 A2-C 标准圆同轴行波线通用件三键（同轴腔/combline=谐振腔
    # 语境不并入，边界见 R7 §③ T1）
    "coax_line_z0": "传输线正反解",
    "coax_line_attenuation": "传输线正反解",
    "coax_line_power_capacity": "传输线正反解",
    # W8-S37 池件批 3 顺手件：截止式衰减器（同轴行波线族第四键）
    "coax_line_cutoff_attenuator": "传输线正反解",
    # aurora_e W1-S2 圆波导 TE/TM_mn 传播解一键（R7 T2"圆波导截止/衰减/
    # 波导波长/功率容量"子项——bethe_hole 内部截止常数=孔耦合口径、
    # waveguide_lambda_g=矩形 TE10 面不撞，边界见 waveguide_closed_form.py
    # 模块 docstring）
    "circular_waveguide_mode_prop": "传输线正反解",
    # aurora_h W1-K1 矩形波导 TE10 衰减+功率容量两键（R2_core_tier5 §③ 2
    # 同族不对称补口：圆波导全参数/矩形 λg 面已有、矩形衰减/功率独缺——
    # waveguide_closed_form 内 alpha 命中全属圆波导函数体（R2 逐行核实）；
    # TE10 场构造解 P_l/(2P) 微扰推导，粗糙度档留升级核不做，边界见
    # wg_fundamental.py 模块 docstring）
    "wg_te10_attenuation": "传输线正反解",
    "wg_te10_power_capacity": "传输线正反解",
    # aurora_j W4-S12 两键（2026-10-23；候选定稿 内部证据档
    # w4_candidates.md §1.3 A1/A2）：良导体表面阻抗基准面（EC-3 收口——
    # calc_families 注册键面零命中，薄注册单源 core/conductor_loss，
    # wg_fundamental "Rs 留调用方自算"注记的正式面补口）+矩形波导 TE10
    # 截止下倏逝传播解（截止侧全仓空白——coax_line_cutoff_attenuator=
    # 同轴 TE11 截止衰减器器件面、wg_te10_attenuation=行波区 f≤fc 拒绝
    # 均不撞，边界见 wg_evanescent.py 模块 docstring）
    "conductor_surface_impedance": "传输线正反解",
    "wg_evanescent_attenuation": "传输线正反解",
    # aurora_l G1 一键（2026-10-23）：端接线输入阻抗精确解（Pozar §2.3-2.4
    # sin/cos 形——微波网络最基本单线变换；``tan.*βl|电长度输入``
    # calc_families 注册面零命中补口。vswr_convert=纯标量 Γ/VSWR 换算无
    # 电长度自由度、stub_tuner=调配拓扑解、microstrip_*=几何正反解不撞，
    # 边界见 terminated_line.py 模块 docstring）
    "line_input_impedance": "传输线正反解",
    # ── 匹配·功分·衰减·耦合（54）────
    "attenuator_pi": "匹配·功分·衰减·耦合",
    "attenuator_t": "匹配·功分·衰减·耦合",
    "attenuator_bridged_t": "匹配·功分·衰减·耦合",
    "quarter_wave_transformer": "匹配·功分·衰减·耦合",
    "t_match_design": "匹配·功分·衰减·耦合",
    "t_match_impedance": "匹配·功分·衰减·耦合",
    "klopfenstein_taper": "匹配·功分·衰减·耦合",
    "vswr_convert": "匹配·功分·衰减·耦合",
    "unequal_split_wilkinson": "匹配·功分·衰减·耦合",
    "bethe_hole_coupler": "匹配·功分·衰减·耦合",
    "balanced_pair_sparams": "匹配·功分·衰减·耦合",
    "doherty_combining_network": "匹配·功分·衰减·耦合",
    # aurora_h W1-K1 L 节匹配提升核一键（R2_core_tier5 §③ 1 Top1：Pozar
    # §5.1 两元件集总 L 节 calc_families 面零（l_section|l_match|two_element
    # 三面零命中）——core/matching.synthesize_l_match 现代入口（C14 锚）
    # 包壳，0bf 遗留标签入口不透传键面；t_match=三元件有 q 自由度/
    # quarter_wave=λ/4 分布/stub_tuner=支节不并入，边界见
    # matching_network.py 模块 docstring）
    "l_section_match": "匹配·功分·衰减·耦合",
    # aurora72 A3-B 双/三支节并联调配器两键（R7 T3——t_match=集总三元件/
    # quarter_wave=λ/4 变换不并入，边界见 R7 §③ T3）
    "stub_tuner_double": "匹配·功分·衰减·耦合",
    "stub_tuner_triple": "匹配·功分·衰减·耦合",
    # aurora_l G1 一键（2026-10-23）：单支节并联调配（Pozar §5.2 电导圆
    # 条件二次闭式，判别式=g[b²+(g−1)²]≥0 任意无源负载有解——R7 T3 立项
    # 时"单支节如实不做"的遗留空白补口；``single.?stub|单支节`` 三面零
    # 命中复测在案。double/triple=禁区判据族不撞，边界见 stub_tuner.py
    # 模块 docstring 单支节节）
    "stub_tuner_single": "匹配·功分·衰减·耦合",
    # aurora72 A5-A 混合结/魔 T 三键（R7 G8 大件候补首拆席——ratrace 仅
    # anchor_benchmark 模板锚判读、butler_matrix 内部固定理想 90° 混合环块
    # （未注册）不并入，边界见 hybrid_junction.py 模块 docstring）
    "magic_tee_s_matrix": "匹配·功分·衰减·耦合",
    "waveguide_tee_s_matrix": "匹配·功分·衰减·耦合",
    "hybrid_sum_difference": "匹配·功分·衰减·耦合",
    # aurora72 A6-B 多节耦合器+Gysel core 四键（R7 §② G5/G6 余量两域——
    # synthesize_multisection_quarter_wave=λ/4 匹配变换器、bethe_hole=单节
    # 孔耦合、coupled_line_bpf_*=带通谐振实现不并入；Gysel 模板级走
    # synthesize_gysel_model、fake 裁判级 _gysel_sparams 不重复，边界见各
    # 模块 docstring）
    "multisection_coupler_binomial": "匹配·功分·衰减·耦合",
    "multisection_coupler_response": "匹配·功分·衰减·耦合",
    "gysel_core_synthesize": "匹配·功分·衰减·耦合",
    "gysel_frequency_response": "匹配·功分·衰减·耦合",
    # aurora72 A7-B 膜片/窗匹配+Guanella 传输线变压器五键（任务书候补两域
    # ——rwg_mmt=数值模匹配（不注册）、rwg_tables=EIA 表、waveguide_tee=
    # 三口结、stub_tuner=通用线支节电长度面不并入；marchand=slotline_
    # transitions 模板级、quarter_wave/klopfenstein=单线拓扑不并入；5:1
    # 等非 n² 复合比显式拒绝，边界见各模块 docstring）
    "wg_iris_susceptance": "匹配·功分·衰减·耦合",
    "wg_resonant_window": "匹配·功分·衰减·耦合",
    "wg_iris_match": "匹配·功分·衰减·耦合",
    "guanella_tlt_design": "匹配·功分·衰减·耦合",
    "guanella_tlt_response": "匹配·功分·衰减·耦合",
    # aurora_f W2-S7 Ruthroff 巴伦两键（R2_core_tier3 §③ D1=官方声明缺口
    # 席：guanella_tlt:148 拒绝注记改指路补全——等延迟族（直通+延迟求和）
    # vs 本品等比族边界互斥，marchand=模板级不并入，边界见
    # ruthroff_balun.py 模块 docstring）
    "ruthroff_balun_design": "匹配·功分·衰减·耦合",
    "ruthroff_balun_response": "匹配·功分·衰减·耦合",
    # aurora72 A8-B 内核末批四键（任务书候补两域——R7_core_tier2 附加候选
    # 余量成席：隔离器/环行器=非互易铁氧体理想 S 口径（reciprocal=False
    # 豁免位首批注册键，Q-M1 §D-7 设计用途落地；circulator_synthesis=
    # 尺寸综合内核未注册、magic_tee=互易结不并入）；经典渐变线=linear/
    # exponential 剖面（klopfenstein=最优剖面+微带宽度面、quarter_wave=
    # 离散阶梯不并入），边界见各模块 docstring）
    "isolator_ideal_sparams": "匹配·功分·衰减·耦合",
    "circulator_ideal_sparams": "匹配·功分·衰减·耦合",
    "classic_taper_response": "匹配·功分·衰减·耦合",
    "classic_taper_synthesize": "匹配·功分·衰减·耦合",
    # aurora_e W2-S9 鳍线渐变过渡两键（K2 渐变过渡面，波导 TE10 导波 β 档；
    # 基模等效 Meier/Sharma-Hoefer 经验档未落地如实放弃——finline.py 范围声明）
    "finline_taper_response": "匹配·功分·衰减·耦合",
    "finline_taper_length": "匹配·功分·衰减·耦合",
    # 批 B Wave3 W3-CORE3 两键（2026-10-13，pa_arch 原位扩展 G11 余量：
    # PIN 限幅器=并联 PIN 二极管两态线性口径、步进衰减器=二进制位组合+
    # 逐位 π/T 节综合（单源消费 attenuator_pi/t）；attenuator_pi/t=
    # 固定衰减节不并入，边界见 pa_arch.py 模块 docstring）
    "pin_diode_limiter": "匹配·功分·衰减·耦合",
    "step_attenuator_design": "匹配·功分·衰减·耦合",
    # aurora_d W3-CORE6 两键（2026-10-14，R7 附加候选"loaded-line/
    # switched-line 移相器"补口：PIN 控制电路相移面（Pozar ch.10 同章与
    # 限幅器/步进衰减器同族分工）；schiffman=耦合线宽带定差模板级、
    # butler_matrix=馈网理想移相器积木（未注册）、varactor=加载线谐振
    # 语境不并入，边界见 phase_shifter.py 模块 docstring）
    "loaded_line_phaser": "匹配·功分·衰减·耦合",
    "switched_line_phaser": "匹配·功分·衰减·耦合",
    # aurora_d W3-CORE8 一键（2026-10-14，CORE6 遗留清单"反射式"续作：
    # 反射式移相器=环行器/正交混合环+可变电抗终端 Γ 相位二态口径
    # （Pozar ch.10 同章）；schiffman=耦合线宽带定差模板级、开关网络式
    # 不在键面，边界见 phase_shifter.py 模块 docstring）
    "reflective_phaser": "匹配·功分·衰减·耦合",
    # aurora_d W3-CORE9 两键（2026-10-14，CORE8 遗留登记收口）：①
    # schiffman_phaser=Schiffman 耦合线移相器**电长度设计面**（arccos 闭
    # 式+平坦点双条件综合——物理长度/几何反演=synthesis.py QW-10、模板
    # 渲染=render_phase_qwt.py 三层不重复）② switched_network_phaser=
    # 开关网络式（PIN 选通 LC 低通 T 节镜像参数设计+开关插损+N 位级联，
    # 与 pin_diode_limiter 同章开关口径）；边界见 phase_shifter.py 模块
    # docstring
    "schiffman_phaser": "匹配·功分·衰减·耦合",
    "switched_network_phaser": "匹配·功分·衰减·耦合",
    # aurora_f W1-S3 Lange 电桥 core 提升两键（R2_core_tier3 §⑤ F1——全链
    # 此前在 adapters/render_c4.py:202 零 core 键零卡；提升式重构单一事实
    # 源，cline_coupler=单节耦合线模板、coupled_line_bpf=谐振器 BPF、
    # multisection_coupler=直通多节级联不并入，边界见 lange.py docstring）
    "lange_synthesize": "匹配·功分·衰减·耦合",
    "lange_response": "匹配·功分·衰减·耦合",
    # aurora_f W2-S6 射频开关件面三键（R2_core_tier3 §③ D8——switch_pa_
    # efficiency=开关模 PA、phase_shifter=移相网络、pin_diode_limiter=
    # 限幅器不并入，边界见 rf_switch.py 模块 docstring）
    "pin_switch_s2p": "匹配·功分·衰减·耦合",
    "rf_switch_spdt_quarter_wave": "匹配·功分·衰减·耦合",
    "rf_switch_matrix_path": "匹配·功分·衰减·耦合",
    # aurora_f W4-S14 等纹波多节耦合器一键（R7 G5 唯一遗留=Levy 等纹波
    # 成员收官——binomial 中心最大平坦成员同族续作，flatness 语义分派
    # 字段显式，边界见 multisection_coupler.py 模块 docstring）
    "multisection_coupler_equiripple": "匹配·功分·衰减·耦合",
    # aurora_g W2-S2 波导介质窗一键（R2_core_tier4 §③ C6：``dielectric.
    # window|介质窗`` 仅 multipactor 边界注记的介质形态补口——半波长全传
    # 输谐振（阻抗变换口径）与 wg_resonant_window 膜片型（电纳对消口径）
    # 成族两形态，边界见 wg_dielectric_window.py 模块 docstring）
    "wg_dielectric_window": "匹配·功分·衰减·耦合",
    # ── 滤波器与耦合矩阵（41）────
    "chebyshev_prototype": "滤波器与耦合矩阵",
    "chebyshev_prototype_asym": "滤波器与耦合矩阵",
    "chebyshev_refl_fn": "滤波器与耦合矩阵",
    "coupling_matrix_synthesize_n2": "滤波器与耦合矩阵",
    "coupling_matrix_synthesize_explicit": "滤波器与耦合矩阵",
    "coupling_matrix_arrow": "滤波器与耦合矩阵",
    "coupling_matrix_folded": "滤波器与耦合矩阵",
    "coupling_matrix_response": "滤波器与耦合矩阵",
    "coupling_matrix_extract": "滤波器与耦合矩阵",
    "cm_extract_vf": "滤波器与耦合矩阵",
    "cm_refine_lm": "滤波器与耦合矩阵",
    "q_factor_circle": "滤波器与耦合矩阵",
    "q_factor_vf": "滤波器与耦合矩阵",
    "q_factor_vf_zero": "滤波器与耦合矩阵",
    "cat_critique": "滤波器与耦合矩阵",
    "k_split_pair": "滤波器与耦合矩阵",
    "qe_group_delay": "滤波器与耦合矩阵",
    "mask_filter_synthesize": "滤波器与耦合矩阵",
    "mask_margin_report": "滤波器与耦合矩阵",
    "mask_min_order": "滤波器与耦合矩阵",
    # aurora72 A3-C 耦合线 BPF 综合两键（实现尺寸级链；耦合矩阵级走
    # coupling_matrix_*/synthesize_bpf_model、模板渲染级走 render_coupled_bpf
    # 均不重复）+ 交指杆实现两键（combline_resonator=谐振器级续作）
    "coupled_line_bpf_synthesize": "滤波器与耦合矩阵",
    "coupled_line_bpf_response": "滤波器与耦合矩阵",
    # aurora_g W10-S4 波导膜片耦合腔 BPF 综合链两键（R3 视角2 B1——
    # 微带耦合线姊妹空白：Cohn 1957 Proc.IRE 原生 λg 域全链，消费
    # wg_iris_susceptance+core/matching g_k 单源；边界见
    # wg_cavity_bpf.py 模块 docstring）
    "wg_cavity_bpf_synthesize": "滤波器与耦合矩阵",
    "wg_cavity_bpf_response": "滤波器与耦合矩阵",
    "interdigital_bars_capacitance": "滤波器与耦合矩阵",
    "interdigital_bpf_synthesize": "滤波器与耦合矩阵",
    # aurora72 A5-A 声表面波 IDT 三键（R7 T12=G14——baw_ladder=BAW/SAW 梯形
    # 电路综合（fs/fp 阻抗梯）不并入，边界见 saw_idt.py 模块 docstring）
    "saw_idt_sync_design": "滤波器与耦合矩阵",
    "saw_idt_frequency_response": "滤波器与耦合矩阵",
    "saw_delay_line": "滤波器与耦合矩阵",
    # aurora_d W3-CORE6 一键（2026-10-14，R7 附加候选"多工器"顺手件：
    # N 信道平铺规划+交越定理标量面；diplexer_compose=两信道精确 S 参数
    # 组合内核（未注册）不并入，边界见 multiplexer.py 模块 docstring）
    "multiplexer_channel_plan": "滤波器与耦合矩阵",
    # aurora_d W3-CORE8 一键（2026-10-14，CORE6 遗留清单"滤波器阶数/
    # 原型"续作：逐通道带通→低通变换+最小阶闭式+原型 g 值链（Chebyshev
    # 复用 core/matching 单源）；chebyshev_prototype=耦合矩阵级/
    # coupled_line_bpf=实现尺寸级为其下游不并入，边界见 multiplexer.py
    # 模块 docstring）
    "multiplexer_channel_prototype": "滤波器与耦合矩阵",
    # aurora_d W3-CORE7 一键（2026-10-14，R7 T6="combline 耦合缝+交指综合"
    # 两半边的 combline 残半：耦合缝 k_ij→邻杆间隙 g_ij 换算，截面电容与
    # interdigital 两键同源 Getsinger 共形映射；combline_resonator=谐振器
    # 频率/Q 级、render_c3 combline_design_from_order=模板级全滤波器设计
    # 不并入，边界见 interdigital_bpf.py 模块 docstring）
    "combline_coupling_gap": "滤波器与耦合矩阵",
    # aurora_f W1-S3 阶梯阻抗 LPF 综合两键（R2_core_tier3 §⑤ F2——模板
    # 名义值手设无综合链的留缺补口；lc_filter=集总、synthesize_commensurate_
    # line=Richards 全 λ/4、stub_filter_design=stub BPF、stepped_impedance
    # 模板=实现级通道不并入，边界见 stepped_impedance.py docstring）
    "stepped_impedance_lpf_synthesize": "滤波器与耦合矩阵",
    "stepped_impedance_response": "滤波器与耦合矩阵",
    # aurora_f W2-S7 群时延均衡器两键（R2_core_tier3 §③ D9——si_channel/
    # kqe=提取面、mask_filter=幅度规格面不并入，边界见 gd_equalizer.py
    # 模块 docstring）
    "gd_allpass_section_synthesize": "滤波器与耦合矩阵",
    "gd_equalizer_cascade_response": "滤波器与耦合矩阵",
    # aurora_f W4-S14 Kuroda 恒等式两键（R2_core_tier3 边际池立项——
    # stub_k_inverter 有 Richards 无 Kuroda 的补口：Pozar Table 8.7 四恒
    # 等式 ABCD 校验+Example 8.5 三阶低通全并联实现全链，边界见
    # kuroda_identities.py 模块 docstring）
    "kuroda_identity_abcd": "滤波器与耦合矩阵",
    "kuroda_shunt_realize": "滤波器与耦合矩阵",
    # aurora_g W2-S2 DGS 缺陷接地结构两键（R2_core_tier4 §③ C3：``DGS``
    # src/tests/scripts 三面全零的首批键——哑铃形一阶 LC 等效提取+陷波/
    # 低通响应再生；vendor_passives=分立器件、amc_mushroom=表面 EBG、
    # crlh=周期单元不并入，边界见 dgs.py 模块 docstring）
    "dgs_dumbbell_lc_extract": "滤波器与耦合矩阵",
    "dgs_notch_response": "滤波器与耦合矩阵",
    # aurora_l G1 一键（2026-10-23）：最平坦（Butterworth）低通原型（Pozar
    # §8.2 g_k=2sin[(2k−1)π/2n] 生成式+RL/RS/ωs 阶数闭式+梯形 ABCD vs
    # 多项式双路径自证；``butterworth|最平坦`` 键面零命中补口——
    # chebyshev_prototype=广义切比雪夫耦合矩阵级、multisection_coupler_
    # binomial=耦合器域不撞，边界见 filter_prototype.py 模块 docstring）
    "butterworth_prototype": "滤波器与耦合矩阵",
    # ── 谐振器与腔体（15）────
    "coaxial_cavity_resonance": "谐振器与腔体",
    "combline_resonance": "谐振器与腔体",
    "cavity_perturbation_shift": "谐振器与腔体",
    "cavity_unloaded_q": "谐振器与腔体",
    "patch_length": "谐振器与腔体",
    # aurora72 A2-C 圆柱腔任意模式闭式谱三键（谱/模式图/模式 Q）
    "circular_cavity_mode_spectrum": "谐振器与腔体",
    "circular_cavity_mode_chart": "谐振器与腔体",
    "circular_cavity_mode_q": "谐振器与腔体",
    # aurora_e W1-S2 矩形腔 TE/TM_mnp 谱+Q 两键（R7 T2"矩形腔留续作"子项
    # 收口——cavity_perturbation_shift=微扰测量面、TE101 f0 同仓双源互证，
    # 边界见 waveguide_closed_form.py 模块 docstring）
    "rectangular_cavity_mode_spectrum": "谐振器与腔体",
    "rectangular_cavity_mode_q": "谐振器与腔体",
    # 批 B Wave3 G9 圆柱 DR TE01δ 正解/反解两键（Cohn 1968 磁壁超越方程；
    # material_characterization courtney_*=提取面（J1 零点 confined 口径）
    # 不并入，口径边界见 dr_te01d.py 模块 docstring）
    "dr_te01d_cohn_f0": "谐振器与腔体",
    "dr_te01d_design_size": "谐振器与腔体",
    # aurora_f W3-S11 环形谐振器两键（R2_core_tier3 §⑤ F3 kernel_cards
    # 前置第三族——ratrace=环行功分器拓扑、dielectric_extract=提取反方向
    # 面、combline_resonator/coaxial_cavity=腔谐振不并入，边界见
    # ring_resonator.py 模块 docstring）
    "ring_resonator_synthesize": "谐振器与腔体",
    "ring_resonator_response": "谐振器与腔体",
    # aurora_j W4-S12 一键（2026-10-23；候选定稿 §1.3 A3）：TM010 圆柱腔
    # 轴上细杆微扰介质测量正反解（cavity.py 原位扩展——与既有
    # cavity_perturbation_shift=TE101 矩形腔场积分面同定理异几何，边界
    # 互指；0.539/0.269 Bessel 几何常数二级源逐字核对注记见该
    # 模块 docstring TM010 节）
    "cavity_tm010_perturbation_shift": "谐振器与腔体",
    # ── 天线与阵列（23）────
    "array.bayliss_weights": "天线与阵列",
    "array.villeneuve_weights": "天线与阵列",
    "array.schelkunoff_nulls": "天线与阵列",
    "array.quantized_milp": "天线与阵列",
    "cma_modes": "天线与阵列",
    # aurora72 A3-B 偶极/折合/小环输入阻抗三键（R7 T4——emc_radiated=场强/
    # patch/helix/lpda=其他单元不并入，边界见 R7 §③ T4）
    "dipole_emf_zin": "天线与阵列",
    "folded_dipole_zin": "天线与阵列",
    "small_loop_zin": "天线与阵列",
    # 批 B Wave3 G17 轴向模螺旋薄注册三键（薄包装：公式单源 core/helix_
    # axial Kraus 闭式，本面零公式复制；anchor_family_service=anchor 通道
    # 并存不撞，边界见 helix_axial_reg.py 模块 docstring）
    "helix_axial_performance": "天线与阵列",
    "helix_axial_design": "天线与阵列",
    "helix_axial_bandwidth": "天线与阵列",
    # 批 B Wave3 G15 Yagi-Uda NBS TN688 两键（实测经验数据面：增益阶梯+
    # 档位几何骨架；dipole/folded=单元阻抗、array.*=幅度综合、helix=螺旋
    # 不并入，边界见 yagi_uda.py 模块 docstring）
    "yagi_gain_nbs_tn688": "天线与阵列",
    "yagi_geometry_nbs_tn688": "天线与阵列",
    # 批 B Wave3 G16 波导缝隙阵 Stevenson 两键（宽壁纵缝电导正反解+谐振阵
    # 综合；rw_tables/rwg_mmt/waveguide_iris/siw_*=波导其他面、array.*=
    # 幅度综合不并入，行波阵 Elliott/有限壁厚修正留续作，边界见
    # slot_array.py 模块 docstring）
    "slot_stevenson_conductance": "天线与阵列",
    "slot_array_synthesis_resonant": "天线与阵列",
    # aurora_e W4-S18 EC-21 极化传输面度量三键（§4.4 极化态数学面接 CALC：
    # 任意两分量极化态口径；helix_axial_performance 的 axial_ratio=Kraus
    # 螺旋经验式轴上值不并入，farfield 服务消费面不受影响，边界见
    # polarization_reg.py 模块 docstring）
    "pol_axial_ratio": "天线与阵列",
    "pol_delta_ipd_il": "天线与阵列",
    "pol_group_delay_diff": "天线与阵列",
    # aurora_h W1-K1 近/远场区界提升核一键（R2_core_tier5 §③ 8：core/
    # near_field_regions.py 全套闭式现成（Balanis ch.2 引文+π/8 相位判据
    # 几何互证+区界排序域守卫已钉）零 CALC 键、docstring 自证"service 挂
    # 接是后续项"——本键即注册面；exposure_limits=合规面、ris_cascade=
    # 远场注记消费点不并入，边界见 antenna_regions.py 模块 docstring）
    "far_field_region": "天线与阵列",
    # aurora_h W3-K 池件批一键（2026-10-19，R2_core_tier5 §⑤-2/§③-11
    # 提升核——池件 T1-A-04 分期承诺同笔清偿：core/antenna_q 全套现成
    # 零键的注册面（Yaghjian-Best 2005 导数式 Q+FBW 换算+Chu/McLean
    # 界 verdict 单源消费 core/bounds）；linear_antenna_zin=偶极/小环
    # 解析阻抗面、helix_axial=螺旋经验面、far_field_region=场区几何面
    # 不并入，边界见 antenna_q.py 模块 docstring）
    "antenna_q_yaghjian_best": "天线与阵列",
    # aurora_j W4-S13 天线口径效率分解域三键（B 批：①PLF 薄注册——§4.4.3
    # 同库直取 core/polarization.polarization_loss_factor，pol_* 三键同库
    # 不并入；②反射面效率分量分解提升核——core/reflector_antenna 在库零
    # 键的注册面（η_s/η_i/Ruze/方向性单源），gt_ratio=G/T 不同面、
    # sat_link_budget=链路面不并入；③最优角锥喇叭增益/口径效率/HPBW 提
    # 升核——core/horn_synthesis ME-7 在库零键的注册面（(21.4.2)/(21.4.3)
    # + δ_H=3λ/8、δ_E=λ/4 单源），pyramid_horn=模板通道、
    # horn_gain_exact_aperture=精确口径积分面不并入，边界见
    # antenna_aperture.py 模块 docstring）
    "polarization_loss_factor": "天线与阵列",
    "aperture_efficiency_components": "天线与阵列",
    "horn_aperture_efficiency": "天线与阵列",
    # ── DOA 与波束形成（6）────
    "doa_esprit": "DOA 与波束形成",
    "doa_music_spectrum": "DOA 与波束形成",
    "doa_mvdr_weights": "DOA 与波束形成",
    # aurora_d W3-CORE6 一键（2026-10-14，R7 §② G20 行"doa 余量=CRB
    # （零命中）"补口：估计器精度下界裁判面；doa_*=估计器本体不并入，
    # 边界见 doa_crb.py 模块 docstring）
    "doa_crb_ula": "DOA 与波束形成",
    # aurora_d W3-CORE8 一键（2026-10-14，CORE6 遗留清单"多源 CRB"续作：
    # FIM 矩阵求逆通用式（Stoica-Nehorai 1989 确定性多源形态）；doa_*=
    # 估计器本体不并入，边界见 doa_crb.py 模块 docstring）
    "doa_crb_ula_multisource": "DOA 与波束形成",
    # aurora_d W3-CORE9 一键（2026-10-14，CORE8 遗留登记"随机 CRB"收口：
    # 高斯信号模型 celebrated 闭式+精确 Slepian-Bangs 内建互证面——
    # Stoica-Nehorai 两模型对照的随机半边；doa_*=估计器本体不并入，
    # 边界见 doa_crb.py 模块 docstring）
    "doa_crb_stochastic": "DOA 与波束形成",
    # ── MIMO 与 RIS（3）────
    "mimo_channel_capacity": "MIMO 与 RIS",
    "mimo_virtual_array": "MIMO 与 RIS",
    "ris_cascade_budget": "MIMO 与 RIS",
    # ── 雷达（20）────
    "radar_range_equation": "雷达",
    "albersheim_detection_snr": "雷达",
    "ca_cfar_threshold": "雷达",
    # aurora72 A4-B 雷达目标 RCS 闭式件两键（R7 T9=G10——radar_range_
    # equation 的 σ 供给端；isac=分辨率面、rfid=标签参数不并入）
    "rcs_sphere_mie": "雷达",
    "rcs_peak_canonical": "雷达",
    # aurora72 A4-A Swerling 1-4 检测补全两键（R7 T8——radar_eq docstring
    # 自证"SW1-4 不冒充"的官方缺口补全；ca_cfar 的 SW1-Pd=CFAR β 门限
    # 口径不撞，本族=固定门限检测因子；SW0 显式拒绝指回 albersheim）
    "swerling_detection_factor": "雷达",
    "swerling_integration_gain": "雷达",
    # aurora_g W6-S3 雷达杂波+MTI 三键（R3_domain_expansion 视角4 E2 Top2
    # ——雷达第五件收官：方程/起伏/RCS/波形之后唯一零命中面；与 radar_
    # detection_ext 积累增益正交衔接，本族=杂波环境+MTI 滤波面）
    "mti_frequency_response": "雷达",
    "mti_improvement_factor": "雷达",
    "clutter_sigma0_model": "雷达",
    # aurora_g W7-S3 FMCW 波形-观测量映射两键（R3_domain_expansion 视角3
    # D5 Top3——车载/ISAC 最主流波形全仓零命中补口；isac_ambiguity 指标面
    # no-go 显式尊重，本族=波形→观测量映射闭式非处理链）
    "fmcw_range_doppler": "雷达",
    "fmcw_bandwidth_range_resolution": "雷达",
    # aurora_g W11-S4 FMCW 域内扩展两键（chirp 参数设计+IF 信号链规划——
    # W7-S3 波形映射两键的设计/链面延长，isac no-go 同源尊重）
    "fmcw_chirp_design": "雷达",
    "fmcw_if_signal_chain": "雷达",
    # aurora_g W7-S3 SAR 合成孔径几何两键（R3_domain_expansion 视角4 E6
    # Top10 遥感收官——δ_az=D/2 与 R、λ 无关恒等=教科书级零风险锚；
    # core/sar.py=比吸收率误中形态不撞）
    "sar_azimuth_resolution": "雷达",
    "sar_swath_coverage": "雷达",
    # aurora_g W9-S2 雷达杂波扩展两键（R3_domain_expansion 视角4 E2 续作
    # 批 3——Weibull 杂波幅度分布参数化（core/aging+probability_paper=
    # 可靠性寿命/作图回归域同名异域不撞）+CA-CFAR 滑窗检测链（radar_eq.
    # ca_cfar_threshold=标量因子面、本键=实测窗+保护带几何+判决链，同式
    # 双源互证，边界见 radar_clutter.py 模块 docstring）
    "weibull_clutter_model": "雷达",
    "cell_averaging_cfar": "雷达",
    # aurora_g W14-S3 SAR 斜视多普勒几何键（R3_domain_expansion 视角4 E6
    # 余量扩展——W7-S3 正侧视两键的 squint 面：多普勒质心/带宽/PRF 约束/
    # 驻留时间几何恒等式；聚焦分辨率/成像处理链 no-go 同源尊重）
    "sar_doppler_geometry": "雷达",
    # aurora_h W1-K2 LFM 脉冲压缩设计键（R2_core_tier5 §③ 7 号——
    # compression.?gain|tb_product|time.?bandwidth|脉冲压缩 calc_families
    # 面零的波形设计面补口；isac_ambiguity=模糊函数裁判/指标面 no-go
    # 同源尊重（ΔR 单源消费彼面非第二实现）、fmcw=连续波拍频面、
    # radar_eq=主方程面不并入，边界见 pulse_compression.py 模块 docstring）
    "pulse_compression_design": "雷达",
    # ── 链路与传播（30）────
    "sat_link_budget": "链路与传播",
    "gt_ratio": "链路与传播",
    "rfid_forward_link": "链路与传播",
    "rfid_backscatter_link": "链路与传播",
    "chipless_tag_plan": "链路与传播",
    "chipless_tag_encode": "链路与传播",
    "chipless_tag_decode": "链路与传播",
    "hata_cost231": "链路与传播",
    "two_ray_loss": "链路与传播",
    "knife_edge_loss": "链路与传播",
    "rain_attenuation_r001": "链路与传播",
    "rain_specific_attenuation": "链路与传播",
    "gaseous_attenuation": "链路与传播",
    # aurora_g W14-S3 云/雾衰减两键（R3_domain_expansion 视角3 D3 Top11
    # ——itu_link 第三成员（雨 P.838/气体 P.676 之后云雾 P.840 零命中
    # 补口）；官方 PDF 逐式转写，K_L 式(12) 分母 σ 无平方 5× 渲染核 verify）
    "cloud_specific_attenuation": "链路与传播",
    "cloud_attenuation_slant": "链路与传播",
    # aurora_g W14-S3 穿墙/建筑媒质两键（R3_domain_expansion 视角4 E4
    # Top9——穿媒质传播空白收官：P.2040-4 Table 3 材料电性质+单层板
    # Fresnel/Airy 穿透链；conductor_loss=金属不撞）
    "building_material_properties": "链路与传播",
    "wall_slab_transmission": "链路与传播",
    "availability_margin": "链路与传播",
    "fade_outage_percent": "链路与传播",
    # aurora_g W1-S2 链路极限面三键（2026-10-19，R2_core_tier4 §③ Top1：
    # shannon/FSPL 独立键全仓零命中的补口——FSPL 此前仅 rfid/vna_
    # uncertainty 内嵌式；sat_link_budget=卫星细项、mimo=矩阵容量、
    # required_ebn0=实现调制需求面不并入，边界见 link_limits.py 模块
    # docstring）
    "shannon_capacity": "链路与传播",
    "free_space_path_loss": "链路与传播",
    "link_margin_calc": "链路与传播",
    # aurora_g W4-S4 COST-231 Walfisch-Ikegami 两键（R2 边际池"传播模型
    # 相邻"件：``walfisch|ikegami`` 全仓零命中补口——hata_cost231=COST-231
    # Hata 经验拟合、本两键=WI 几何分析模型（街道峡谷 LoS+三分量 NLoS），
    # 边界见 core/propagation.py 模块 docstring）
    "walfisch_ikegami_los": "链路与传播",
    "walfisch_ikegami_nlos": "链路与传播",
    # aurora_g W7-S3 HF 电离层天波三键（R3_domain_expansion 视角3 D1 Top5
    # ——全频段维度唯一整段空白（HF 以下零覆盖）：f_p/secant/n² 标度恒等
    # 锚干净；itu_atmosphere=对流层非电离层不并入，边界见 hf_skywave.py
    # 模块 docstring）
    "critical_frequency": "链路与传播",
    "secant_law_muf": "链路与传播",
    "ionospheric_plasma_frequency": "链路与传播",
    # aurora_g W9-S2 GNSS 定位几何三键（R3_domain_expansion 视角4 E1 Top6
    # ——导航场景空白收官：gdop|uere|dilution 三面零命中补口；sat_link_
    # budget/satellite=链路预算/多普勒面、doa_crb=阵列估计界不并入，边界
    # 见 gnss_geometry.py 模块 docstring）
    "gdop_dop": "链路与传播",
    "uere_to_position_error": "链路与传播",
    "dop_from_satellite_geometry": "链路与传播",
    # ── 收发链路·频综（22）────
    "cascade_budget": "收发链路·频综",
    "correlated_cascade_nf": "收发链路·频综",
    "blocking_budget": "收发链路·频综",
    "spur_search": "收发链路·频综",
    "if_plan_sweep": "收发链路·频综",
    "iq_imbalance_irr": "收发链路·频综",
    "phase_noise_evm": "收发链路·频综",
    # aurora_f W3-S10 AGC 环路动力学两键（R2_core_tier3 §③ D3——
    # rx_impairments 预声明排除注记改指路补全：本族=AGC 闭环动态面
    # （闭环时间常数/稳态误差/阶跃轨迹），rx_impairments 保留 P1dB/
    # 压缩静态线性度面；pll_loop_filter=PLL 环路滤波器综合不同对象，
    # 边界见 agc_loop.py 模块 docstring）
    "agc_loop_dynamics": "收发链路·频综",
    "agc_loop_response": "收发链路·频综",
    "pll_loop_filter_synthesize": "收发链路·频综",
    # aurora_f W4-S14 PLL 锁定/捕获时间一键（R2_core_tier3 边际池立项——
    # pll_loop_filter=滤波器综合（ω_n/ζ 供给端）、pll_budget=相噪/抖动
    # 预算面，本键=频率阶跃捕获动力学（线性包络精确+pull-in 近似档如实），
    # 边界见 pll_lock_time.py 模块 docstring）
    "pll_lock_time": "收发链路·频综",
    "doherty_efficiency_curve": "收发链路·频综",
    # aurora_g W4-S4 N-way Doherty 两键（R2 边际池"N-way Doherty 顺延"件
    # 的有界落地：``n.?way.?doherty`` 此前全仓零——N=2 逐位回归既有
    # doherty_efficiency Cripps 闭式为独立裁判的 N 区域推广（断点回峰/
    # 凹陷闭式锚）；doherty_combining_network=2-way 合路网络面不并入，
    # 边界见 core/pa_architectures.py N-way 节 docstring）
    "doherty_nway_efficiency": "收发链路·频综",
    "doherty_nway_breakpoints": "收发链路·频综",
    # aurora72 A4-B PIM 多节点累计两键（R7 T11——cascade_budget=有源链
    # 截点级联、pim_products/pim_empirical=单节点枚举/换算（未注册）不
    # 并入，边界见 pim_cascade.py 模块 docstring）
    "pim_nodes_combine": "收发链路·频综",
    "pim_cascade_budget": "收发链路·频综",
    # 批 B Wave3 W3-CORE3 两键（2026-10-13，pa_arch 原位扩展 G11 余量：
    # ET 包络跟踪效率=理想 B 类 Rayleigh 包络闭式（doherty_efficiency_
    # curve=Doherty 回退曲线不同架构不并入）、倍频链预算=频率/功率/
    # 20log10(N) 相噪律（spur_search=混频杂散乘积域不并入），边界见
    # pa_arch.py 模块 docstring）
    "envelope_tracking_efficiency": "收发链路·频综",
    "multiplier_chain_budget": "收发链路·频综",
    # aurora_f W2-S6 混频器变换面三键（R2 D2——cascade/spur=杂散面、
    # iq_imbalance_irr=损伤面不并入，边界见 mixer_conversion.py 模块
    # docstring）
    "mixer_ssb_nf": "收发链路·频综",
    "mixer_conversion_loss": "收发链路·频综",
    "mixer_image_plan": "收发链路·频综",
    # aurora_l G1 一键（2026-10-23）：Leeson 振荡器相噪模型（Leeson 1966
    # Proc. IEEE 54(2):329-330——L(f_m)=[FkT/2Ps](1+fc/fm)(1+(f0/2QLfm)²)；
    # ``leeson`` src/tests 三面零命中，phase_noise_evm=相噪→EVM 消费面
    # 不撞（本键=谱形产生面），边界见 oscillator_leeson.py 模块 docstring）
    "leeson_phase_noise": "收发链路·频综",
    # ── 调制与数字链路（18）────
    "modulation_ber_curve": "调制与数字链路",
    "required_ebn0": "调制与数字链路",
    "coded_ber_estimate": "调制与数字链路",
    # aurora_g W1-S2 FEC 块码族三键（2026-10-19，R2_core_tier4 §③ Top3：
    # coded_ber_estimate 的 coding_gain_db 输入参数官方缺口的产生面——
    # Hamming/RS 闭式+硬判 union bound G 反解；coded_ber_estimate=消费面、
    # hamming 窗函数/汉明距离同名异义剔除，边界见 fec_codes.py 模块
    # docstring）
    "hamming_code_design": "调制与数字链路",
    "reed_solomon_capacity": "调制与数字链路",
    "coded_ebn0_requirement": "调制与数字链路",
    "cdr_jitter_mask": "调制与数字链路",
    # aurora_g W4-S4 模拟调制域三键（本席 grep 新发现：``carson|carsons_
    # rule`` 全仓零、``\\bfm\\b`` 命中均误中——modulation_ber=数字 BER 面
    # 的模拟姊妹空白补口，边界见 analog_modulation.py 模块 docstring）
    "carson_bandwidth": "调制与数字链路",
    "fm_processing_gain": "调制与数字链路",
    "am_power_split": "调制与数字链路",
    # aurora_g W4-S4 CTLE 独立面三键（R2 边际池点名件：独立零极点闭式
    # 评估/综合键面零——com_pam4=pychopmarg COM 规格包裹消费面、
    # si_channel=眼图/FFE 时域面、gd_equalizer=微波全通面不并入；本族
    # 只做通用零极点代数无规格依赖，边界见 si_ctle.py 模块 docstring）
    "ctle_nyquist_gain": "调制与数字链路",
    "ctle_pole_from_boost": "调制与数字链路",
    "ctle_gain_at": "调制与数字链路",
    # aurora_h W1-K2 调制/数字链路波形体制域五键（R2_core_tier5 §③ 4-6
    # 号：PAPR/CFR=提升核（core/papr 全套+service/papr_service 现成零键，
    # lange F1 同构——单源消费零公式复制）；OFDM 参数/CP 设计=成对键
    # （cyclic.?prefix|cp_length|guard.?interval 三面零）；扩频=
    # dsss|fhss|jamming.?margin 三面零的体制面补口；modulation_ber/
    # analog_modulation=BER/模拟面、rx_impairments.phase_noise_evm=相噪
    # 损伤面、link_limits=容量极限面、pa_arch=PA 效率消费面不并入，边界
    # 见 link_modulation.py 模块 docstring）
    "papr_ofdm_ccdf": "调制与数字链路",
    "cfr_evm_cost": "调制与数字链路",
    "ofdm_waveform_params": "调制与数字链路",
    "ofdm_cp_design": "调制与数字链路",
    "spread_spectrum_gain": "调制与数字链路",
    # ── EMC·安规·放电（9）────
    "conducted_immunity_cdn": "EMC·安规·放电",
    "radiated_immunity_power": "EMC·安规·放电",
    "esd_contact_waveform": "EMC·安规·放电",
    "exposure_mpe_limit": "EMC·安规·放电",
    "exposure_compliance_distance": "EMC·安规·放电",
    "shielding_effectiveness": "EMC·安规·放电",
    "corona_pd_check": "EMC·安规·放电",
    "multipactor_susceptibility_check": "EMC·安规·放电",
    "ecss_multipactor_fd": "EMC·安规·放电",
    # ── 热·功率·可靠性（13）────
    "thermal_resistance_stack": "热·功率·可靠性",
    "ipc2152_trace_temp_rise": "热·功率·可靠性",
    "microstrip_loss_heat": "热·功率·可靠性",
    "resonator_thermal_drift": "热·功率·可靠性",
    "electromigration_mttf_check": "热·功率·可靠性",
    "parallel_plate_breakdown_margin": "热·功率·可靠性",
    "microwave_process_window": "热·功率·可靠性",
    "multimode_cavity_heating": "热·功率·可靠性",
    "single_mode_applicator": "热·功率·可靠性",
    "form_beta_linear": "热·功率·可靠性",
    # aurora_d W3-CORE7 两键（2026-10-14，R7 附加候选"Cpk→良率% / 多工序
    # 串联良率"顺手件：能力指数↔良率正态尾双向换算+多工序串联合并——
    # manufacturing_stats(cpk_ci)/tolerance_allocation=样本→CI 与公差分配
    # 面（CLI stats 薄壳直连内核、CALC 键面零命中）不并入，边界见
    # manufacturing_yield.py 模块 docstring）
    "cpk_yield_convert": "热·功率·可靠性",
    "serial_yield_budget": "热·功率·可靠性",
    # aurora_h W3-K 池件批一键（2026-10-19，R2_core_tier5 §⑤-3 提升核
    # ——池件 XD-15 同笔清偿：core/probability_paper 三函数现成零键的
    # 注册面（Benard 中位秩+ln(−ln(1−p)) 线性化+闭式 OLS β̂/η̂/R²）；
    # weibull_clutter_model=雷达杂波同名异域、alt_planning=右删失 MLE
    # 面、aging/cpk=统计域不并入，边界见 probability_paper.py 模块
    # docstring）
    "weibull_paper_fit": "热·功率·可靠性",
    # ── 测量与校准（32）────
    "power_cal_chain": "测量与校准",
    "trl_standards_design": "测量与校准",
    "trl_line_electric_scan": "测量与校准",
    "tnvna_extender_error_model": "测量与校准",
    "tnvna_band_stitch": "测量与校准",
    "allan_deviation": "测量与校准",
    # aurora_e W2-S9 EC-2 multiline TRL εr/tan_d 不确定度传播键（GUM 双通道
    # +MC 对照；锚 gate 消费面）
    "mtrl_er_tand_uncertainty": "测量与校准",
    # aurora72 A4-B 检波器件两键（R7 T10=G13——power_cal_chain=校准链/
    # cispr_detector=EMC 检波算法不并入，边界见 detector_device.py 模块
    # docstring）
    "diode_square_law_detect": "测量与校准",
    "detector_tss_nep": "测量与校准",
    # aurora_e W1-S2 热偶/测辐射热计功率换算一键（R7 T10"热偶/测辐射热计
    # 功率计换算"子项——power_calibration=校准链、detector_tss_nep=灵敏度
    # 极限面不撞，边界见 detector_device.py 模块 docstring）
    "thermal_power_sensor_detect": "测量与校准",
    # aurora72 A4-A VNA 不确定度+增益定标三键（R7 T7=G19——tnvna=THz 扩
    # 频链/trl=校准件设计/power_cal=功率链/nf_measurement=Y 因子均不并
    # 入，边界见 vna_uncertainty.py 模块 docstring）
    "vna_reflection_uncertainty": "测量与校准",
    "vna_transmission_uncertainty": "测量与校准",
    "three_antenna_gain": "测量与校准",
    # aurora_f W2-S7 测量系统漂移两键（R2_core_tier3 §③ D6——anchor_drift/
    # anchor_drift_spc=锚面（统计内核组合复用不替代）、filter_temp_drift=
    # 器件温漂不并入，边界见 measurement_drift.py 模块 docstring）
    "measurement_drift_estimate": "测量与校准",
    "measurement_drift_monitor": "测量与校准",
    # aurora_f W2-S6 定向电桥反射计桥两键（R2_core_tier3 §③ D4——
    # vna_uncertainty=误差箱传播消费面（本族为其上游器件面）、multisection_
    # coupler/bethe_hole=耦合器族不并入，边界见 directional_bridge.py
    # 模块 docstring）
    "directional_bridge_s_matrix": "测量与校准",
    "directional_bridge_response": "测量与校准",
    # aurora_f W3-S10 校准件完整性验证两键（R2_core_tier3 §③ D5——
    # trl_solt/measurement=校准件使用链、trl_standards=TRL 设计端、
    # vna_uncertainty=误差箱传播、power_cal=功率链均不并入，本族=标准
    # 件响应核验+纹波法 verification"验"半边，边界见 cal_kit_verify.py
    # 模块 docstring）+ 六端口反射计两键（R2 §③ D7——trl_standards:25
    # 文献引注背书落地；directional_bridge=两端口差分检波桥器件面、
    # detector_device=检波器件面不并入，本族=多端口功率检波干涉反演
    # 架构，边界互指见 six_port.py 模块 docstring）
    "cal_kit_standard_response": "测量与校准",
    "cal_kit_verify_ripple": "测量与校准",
    "six_port_gamma_solve": "测量与校准",
    "six_port_cal_extract": "测量与校准",
    # aurora_f W5-S18 在片 ISS 校准两键（R2_core_tier3 边际池——ISS/在片
    # 全仓零实现的首批键：cal_kit_verify=同轴机械件（频率多项式恰在其预
    # 声明诚实边界外）、trl_solt=理想标准定义使用链、deembed=泛用 2 端口
    # 夹具去嵌均不并入，边界见 iss_on_wafer.py 模块 docstring）+ 源功率校
    # 准一键（power_cal_chain=测量端读数修正链、本键=源编程端闭环方程，
    # 边界见 source_power_cal.py 模块 docstring）
    "iss_standard_response": "测量与校准",
    "iss_oneport_cal_extract": "测量与校准",
    "source_power_cal_table": "测量与校准",
    # aurora_g W2-S2 IF 数字化欠采样规划两键（R2_core_tier4 §③ C4：
    # adc_budget=噪声合成面/if_plan_sweep=混频杂散面两邻 docstring 边界
    # 内空白的补口——带通采样 VSW 1991 可行区间规划+折叠三态核验，抖动
    # SNR 经 adc_budget.snr_jitter_db 单源消费，边界见 if_digitizer.py
    # 模块 docstring）
    "bandpass_sampling_plan": "测量与校准",
    "alias_fold_check": "测量与校准",
    # aurora_h W1-K1 TDR 测量规划族三键（R2_core_tier5 §③ 3：tdr|
    # reflectomet|fault.?locat|equivalent.?time 全面零命中——故障定位/
    # 空间分辨率/等效时间采样恒等式族，测量**规划面**；剖面**裁判面**=
    # core/serdes_referee DR-3（已存在零键，本批不接线仅 docstring 注记
    # 同仓消费链）；bandpass_sampling_plan=A/D 采样规划不同对象不并入，
    # 边界见 tdr_measurement.py 模块 docstring）
    "tdr_fault_location": "测量与校准",
    "tdr_resolution": "测量与校准",
    "tdr_ets_equivalent_time": "测量与校准",
    # aurora_k K8 THRU 去嵌+Z12 串联指标两键（反馈 F6/P14：波端口参考面
    # 从引线外端移回 pad 边缘+强失配简化式拒绝——Z12 传输阻抗主口径与
    # −1/Y21 π 并联免疫副口径、2x-thru 对称半拆双边去嵌一站式；公式
    # 单源 core/deembed K8 扩展面（deembed_thru half/z12_series_metrics）
    # 零复制，iss_on_wafer 预声明"泛用件不并入"指向的正是该单源的注册
    # 出口补齐；afr_2xthru=IEEEP370 时域面与频域精确代数互补不并入，
    # 边界见 deembed_metrics.py 模块 docstring）
    "z12_series_extract": "测量与校准",
    "deembed_thru_metrics": "测量与校准",
    # aurora_l G1 一键（2026-10-23）：二端口 S/Z/Y/ABCD 全对全换算（Pozar
    # §4.4 网络互换恒等式——S=Z0(I+S)(I−S)⁻¹ 1 端口短路/开路口径自证；
    # kuroda_identity_abcd=Kuroda 恒等式实现域、deembed_thru_metrics=去
    # 嵌指标面不撞，边界见 network_convert.py 模块 docstring）
    "twoport_matrix_convert": "测量与校准",
    # aurora_k K11 八角螺旋电感一键（反馈 F1：GaAs 薄膜 IPD 工艺集总无源
    # 模板族闭式锚——W/S/N/Din μm 参数→Mohan 三式 L+SRF/Q 一阶+L±25%/
    # SRF>2×f0 质量门；公式单源 core/nfc_coil（四形状内核）八角形状的
    # 注册出口，边界见 spiral_inductor.py 模块 docstring）
    "octagonal_spiral_inductance": "匹配·功分·衰减·耦合",
    # aurora_k K12 两键（反馈 F1：MIM/IDC 电容闭式锚——C±25%/±50%+
    # SRF>2×f0 质量门；公式单源 core/ipc_cap（MIM 复用
    # package_interconnect 平行板精确式零复制；IDC 侧壁推导式±50%
    # 精度类如实声明），边界见 calc_families/ipc_cap.py 模块 docstring）
    "mim_capacitance": "匹配·功分·衰减·耦合",
    "interdigital_capacitance": "匹配·功分·衰减·耦合",
    # aurora_l G1 一键（2026-10-23）：分支线耦合器理想设计（Pozar §7——
    # 耦合系数 c→臂阻抗闭式 Z1=c·Z0/Z2=Z0·c/√(1−c²)+奇偶模解析 4×4 S；
    # ``branchline|分支线`` calc_families 键面零命中，模板级几何综合=
    # core/synthesis.synthesize_branchline 不撞，边界见
    # branchline_coupler.py 模块 docstring）
    "branchline_coupler_design": "匹配·功分·衰减·耦合",
    # ── 超材料·超表面（9）────
    "homog_mix_eff": "超材料·超表面",
    "retrieve_eff_params": "超材料·超表面",
    "srr_permeability": "超材料·超表面",
    "wire_media_plasma": "超材料·超表面",
    "crlh_unit_cell_report": "超材料·超表面",
    # aurora_g W2-S2 CRLH 平衡综合一键（R2_core_tier4 §③ C5：分析面既有
    # 单键的 complement——`crlh.*synth` 全仓零的补口，(f0,Z0,种子)→四元
    # LC 平衡闭式；内核 core/crlh.crlh_balanced_synthesis，回判面=同族
    # 分析键，边界见 calc_families/crlh.py 模块 docstring）
    "crlh_balanced_synthesize": "超材料·超表面",
    "gstc_forward": "超材料·超表面",
    "gstc_synthesize": "超材料·超表面",
    "gstc_lut_crosscheck": "超材料·超表面",
    # ── 量子读出（5）────
    "qubit_dispersive_shift": "量子读出",
    "qubit_readout_s21": "量子读出",
    "qubit_readout_snr": "量子读出",
    # aurora_h W3-K 池件批两键（2026-10-19，R2_core_tier5 §⑤-1/§③-14
    # 提升核——池件 MP-7 同笔清偿：core/quantum_cryo 登记级现成零键的
    # 注册面，两流体 σ₁=t⁴+λ_L(T)=λ_L0/√(1−t⁴)+局部极限 Rs 一阶恒等
    # 互证+BCS/Mühlschlegel 能隙；材料档 Nb/NbTiN/Al 文献带（#122）；
    # residual Rs 档预声明不加；qubit_readout=读出链数值面不并入，
    # 边界见 quantum_cryo.py 模块 docstring）
    "superconductor_rs": "量子读出",
    "superconductor_gap": "量子读出",
    # ── 实验（1）────
    "patch_f0_symbolic_e13": "实验",
}


# ─── 注册表（接口先行：注册可见、未注册调用显式报错）─────────────────────────
# 实验态开关（W1⑨，2026-09-16 用户口径）：自动归纳（符号回归等）的经验
# 公式一律 experimental=True 入库——names()/describe() **默认不列**（任何
# 只拿 names() 的消费方天然不会拾取），显式 include_experimental=True 才
# 可见；运行放行由 service 层开关决定（core 零配置依赖，只带元数据）。

@dataclass(frozen=True)
class CalculatorSpec:
    """一个计算器的自描述条目（供 CLI/UI 动态生成表单）。"""

    name: str
    description: str
    func: Callable[..., dict[str, Any]]
    params: tuple[tuple[str, str], ...]  # (参数名, "类型 单位 说明")
    required: tuple[str, ...]
    experimental: bool = False  # 实验态：默认不列/默认拒跑，显式开关才用
    # 互易豁免位（QM-1 §D-7，2026-10-02）：产出 S/ABCD 的键默认 True，受
    # test_physics_invariants 互易全键扫描裁判；非互易器件（铁氧体隔离器/
    # 环形器类）注册时显式 reciprocal=False 进豁免清单——豁免清单由该测试
    # 封闭断言钉死，新增豁免键必须同步清单。纯元数据位，不参与计算语义。
    reciprocal: bool = True
    # 工具箱分组（aurora72 A2-A，2026-10-11）：缺省空串 = 不逐键声明，
    # 由下方 CALC_GROUP_TABLE 单源表解析（键→组名）；显式传值优先于表
    # （未来按注册点就地分组时无需改表）。纯元数据位，不参与计算语义。
    group: str = ""


class CalculatorRegistry(RegistryKit[CalculatorSpec]):
    """基类+注册表模式（参照 EMSolverRegistry）：重名注册报错，
    未注册调用 KeyError 并列出可用名。

    T6 扩面四批（aurora_h W2-S3，R1_arch_audit_v3 §5）：dict 样板由
    core.registry_kit.RegistryKit 承载（Kit 本体已下沉 core，分层合法）——
    历史语义逐项保真：重名/缺名 ValueError/KeyError 文案经
    dup_fmt/missing_fmt 逐字节同旧（"计算器重名注册: {key}" /
    "未注册的计算器: {key}（可用: {全键字典序列表 repr，含实验键}）"——
    后者经 {keys_list} 占位符保列表 repr 形态）、names() 实验键过滤口径
    与字典序不变、describe() 输出逐键逐字段不变（group 表解析同单源）、
    register(spec) 返回 None、is_experimental 缺名与 get 同语义 KeyError；
    ``_specs`` 属性名以只读 property 直通 Kit 存储（facade 注释与潜在
    插入序审计缝的命名保真）。
    """

    def __init__(self) -> None:
        super().__init__(
            label="计算器",
            missing_fmt="未注册的计算器: {key}（可用: {keys_list}）",
            dup_fmt="计算器重名注册: {key}",
        )

    @property
    def _specs(self) -> dict[str, CalculatorSpec]:
        """历史存储属性名（Kit ``_items`` 只读直通）：facade 注册序注释
        （core/calculators.py、calc_families/__init__.py）的命名保真缝。
        """
        return self._items

    def register(self, spec: CalculatorSpec) -> None:
        """登记 spec（键=spec.name；重名 ValueError 文案经 dup_fmt 逐字节
        同旧，键校验/验重/落表统一走 Kit insert 口径）。"""
        self.insert(spec.name, spec)

    def get(self, name: str) -> CalculatorSpec:
        """按键取 spec（单参历史签名钉：get 不带 default 形参——多余
        实参维持历史 TypeError，不升级为 Kit 的缺省回退形态）。"""
        return super().get(name)

    def names(self, include_experimental: bool = False) -> list[str]:
        """已注册键（字典序）；实验键默认排除，include_experimental=True 才列。"""
        if include_experimental:
            return self.keys()
        return [
            key for key in self.keys()
            if not self._items[key].experimental]

    def is_experimental(self, name: str) -> bool:
        """键是否实验态；未注册名显式 KeyError（与 get 同语义）。"""
        return self.get(name).experimental

    def describe(self, include_experimental: bool = False) -> list[dict[str, Any]]:
        """自描述清单（含 experimental/group 标签）；实验键默认排除。"""
        rows: list[dict[str, Any]] = []
        for key in self.names(include_experimental=include_experimental):
            spec = self._items[key]
            rows.append({
                "name": spec.name,
                "description": spec.description,
                "experimental": bool(spec.experimental),
                "group": (spec.group
                          or CALC_GROUP_TABLE.get(key, DEFAULT_CALC_GROUP)),
                "params": [
                    {"name": pname, "desc": pdesc,
                     "required": pname in spec.required}
                    for pname, pdesc in spec.params
                ],
            })
        return rows


CALCULATOR_REGISTRY = CalculatorRegistry()


def register_calculator(
    name: str,
    description: str,
    params: tuple[tuple[str, str], ...],
    required: tuple[str, ...] = (),
    experimental: bool = False,
    reciprocal: bool = True,
    group: str = "",
) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    """把纯函数登记进 CALCULATOR_REGISTRY 的装饰器。

    experimental=True 的键：names()/describe() 默认不列、service 运行默认
    拒绝（见 calculator_service.run_calculator 的 allow_experimental 与
    configs/settings.yaml 的 calculators.allow_experimental）。

    reciprocal=False：非互易器件豁免位（QM-1 §D-7，铁氧体键显式 False）——
    纯元数据标注，只被 test_physics_invariants 的互易全键扫描/豁免清单
    封闭断言消费；不改变任何计算语义。

    group：工具箱分组（aurora72 A2-A）——缺省空串=走 CALC_GROUP_TABLE
    单源表解析（表外键落 DEFAULT_CALC_GROUP="其他"）；显式传值优先于表。
    """

    def deco(
        func: Callable[..., dict[str, Any]],
    ) -> Callable[..., dict[str, Any]]:
        CALCULATOR_REGISTRY.register(CalculatorSpec(
            name=name, description=description, func=func,
            params=params, required=required, experimental=experimental,
            reciprocal=reciprocal, group=group))
        return func

    return deco
