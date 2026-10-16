"""注册表单源（CalculatorSpec/CalculatorRegistry/CALCULATOR_REGISTRY/register_calculator + C_MM_GHZ）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

C_MM_GHZ = 299.792458  # mm·GHz（光速，f[GHz]×λ[mm]=此值）


# ─── 工具箱分组单源表（aurora72 A2-A，2026-10-11；分组方案档（内部）=
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
    # ── 传输线正反解（20）──
    "microstrip_analysis": "传输线正反解",
    "microstrip_synthesis": "传输线正反解",
    "microstrip_lambda_g": "传输线正反解",
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
    # ── 匹配·功分·衰减·耦合（26）──
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
    # aurora72 A3-B 双/三支节并联调配器两键（R7 T3——t_match=集总三元件/
    # quarter_wave=λ/4 变换不并入，边界见 R7 §③ T3）
    "stub_tuner_double": "匹配·功分·衰减·耦合",
    "stub_tuner_triple": "匹配·功分·衰减·耦合",
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
    # ── 滤波器与耦合矩阵（28）──
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
    # ── 谐振器与腔体（8）──
    "coaxial_cavity_resonance": "谐振器与腔体",
    "combline_resonance": "谐振器与腔体",
    "cavity_perturbation_shift": "谐振器与腔体",
    "cavity_unloaded_q": "谐振器与腔体",
    "patch_length": "谐振器与腔体",
    # aurora72 A2-C 圆柱腔任意模式闭式谱三键（谱/模式图/模式 Q）
    "circular_cavity_mode_spectrum": "谐振器与腔体",
    "circular_cavity_mode_chart": "谐振器与腔体",
    "circular_cavity_mode_q": "谐振器与腔体",
    # 批 B Wave3 G9 圆柱 DR TE01δ 正解/反解两键（Cohn 1968 磁壁超越方程；
    # material_characterization courtney_*=提取面（J1 零点 confined 口径）
    # 不并入，口径边界见 dr_te01d.py 模块 docstring）
    "dr_te01d_cohn_f0": "谐振器与腔体",
    "dr_te01d_design_size": "谐振器与腔体",
    # ── 天线与阵列（15）──
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
    # ── DOA 与波束形成（4）──
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
    # ── MIMO 与 RIS（3）──
    "mimo_channel_capacity": "MIMO 与 RIS",
    "mimo_virtual_array": "MIMO 与 RIS",
    "ris_cascade_budget": "MIMO 与 RIS",
    # ── 雷达（3）──
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
    # ── 链路与传播（15）──
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
    "availability_margin": "链路与传播",
    "fade_outage_percent": "链路与传播",
    # ── 收发链路·频综（9）──
    "cascade_budget": "收发链路·频综",
    "correlated_cascade_nf": "收发链路·频综",
    "blocking_budget": "收发链路·频综",
    "spur_search": "收发链路·频综",
    "if_plan_sweep": "收发链路·频综",
    "iq_imbalance_irr": "收发链路·频综",
    "phase_noise_evm": "收发链路·频综",
    "pll_loop_filter_synthesize": "收发链路·频综",
    "doherty_efficiency_curve": "收发链路·频综",
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
    # ── 调制与数字链路（4）──
    "modulation_ber_curve": "调制与数字链路",
    "required_ebn0": "调制与数字链路",
    "coded_ber_estimate": "调制与数字链路",
    "cdr_jitter_mask": "调制与数字链路",
    # ── EMC·安规·放电（9）──
    "conducted_immunity_cdn": "EMC·安规·放电",
    "radiated_immunity_power": "EMC·安规·放电",
    "esd_contact_waveform": "EMC·安规·放电",
    "exposure_mpe_limit": "EMC·安规·放电",
    "exposure_compliance_distance": "EMC·安规·放电",
    "shielding_effectiveness": "EMC·安规·放电",
    "corona_pd_check": "EMC·安规·放电",
    "multipactor_susceptibility_check": "EMC·安规·放电",
    "ecss_multipactor_fd": "EMC·安规·放电",
    # ── 热·功率·可靠性（12）──
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
    # ── 测量与校准（6）──
    "power_cal_chain": "测量与校准",
    "trl_standards_design": "测量与校准",
    "trl_line_electric_scan": "测量与校准",
    "tnvna_extender_error_model": "测量与校准",
    "tnvna_band_stitch": "测量与校准",
    "allan_deviation": "测量与校准",
    # aurora72 A4-B 检波器件两键（R7 T10=G13——power_cal_chain=校准链/
    # cispr_detector=EMC 检波算法不并入，边界见 detector_device.py 模块
    # docstring）
    "diode_square_law_detect": "测量与校准",
    "detector_tss_nep": "测量与校准",
    # aurora72 A4-A VNA 不确定度+增益定标三键（R7 T7=G19——tnvna=THz 扩
    # 频链/trl=校准件设计/power_cal=功率链/nf_measurement=Y 因子均不并
    # 入，边界见 vna_uncertainty.py 模块 docstring）
    "vna_reflection_uncertainty": "测量与校准",
    "vna_transmission_uncertainty": "测量与校准",
    "three_antenna_gain": "测量与校准",
    # ── 超材料·超表面（8）──
    "homog_mix_eff": "超材料·超表面",
    "retrieve_eff_params": "超材料·超表面",
    "srr_permeability": "超材料·超表面",
    "wire_media_plasma": "超材料·超表面",
    "crlh_unit_cell_report": "超材料·超表面",
    "gstc_forward": "超材料·超表面",
    "gstc_synthesize": "超材料·超表面",
    "gstc_lut_crosscheck": "超材料·超表面",
    # ── 量子读出（3）──
    "qubit_dispersive_shift": "量子读出",
    "qubit_readout_s21": "量子读出",
    "qubit_readout_snr": "量子读出",
    # ── 实验（1）──
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


class CalculatorRegistry:
    """基类+注册表模式（参照 EMSolverRegistry）：重名注册报错，
    未注册调用 KeyError 并列出可用名。"""

    def __init__(self) -> None:
        self._specs: dict[str, CalculatorSpec] = {}

    def register(self, spec: CalculatorSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"计算器重名注册: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> CalculatorSpec:
        if name not in self._specs:
            raise KeyError(
                f"未注册的计算器: {name}"
                f"（可用: {self.names(include_experimental=True)}）")
        return self._specs[name]

    def names(self, include_experimental: bool = False) -> list[str]:
        """已注册键（字典序）；实验键默认排除，include_experimental=True 才列。"""
        return sorted(
            key for key, spec in self._specs.items()
            if include_experimental or not spec.experimental)

    def is_experimental(self, name: str) -> bool:
        """键是否实验态；未注册名显式 KeyError（与 get 同语义）。"""
        return self.get(name).experimental

    def describe(self, include_experimental: bool = False) -> list[dict[str, Any]]:
        """自描述清单（含 experimental/group 标签）；实验键默认排除。"""
        return [
            {
                "name": self._specs[key].name,
                "description": self._specs[key].description,
                "experimental": bool(self._specs[key].experimental),
                "group": (self._specs[key].group
                          or CALC_GROUP_TABLE.get(key, DEFAULT_CALC_GROUP)),
                "params": [
                    {"name": pname, "desc": pdesc,
                     "required": pname in self._specs[key].required}
                    for pname, pdesc in self._specs[key].params
                ],
            }
            for key in self.names(include_experimental=include_experimental)
        ]


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
