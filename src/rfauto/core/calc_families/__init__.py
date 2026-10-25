"""calc_families：core/calculators.py 巨石拆分包（AU-1 批 2，2026-09-30）。

导入本包即完成全部计算器注册（子模块按原文件定义顺序导入，
CALCULATOR_REGISTRY._specs 插入序与原单文件逐位一致）。
公开入口 = rfauto.core.calculators（facade，逐名 re-export）。

═══ 聚合面消费纪律（W11-S3/T7，2026-10-19；R1 架构审计 内部证据档
R1_arch_audit.md 面2/Top7）═══════════════════════════════════════════

本 ``__init__`` 是**注册副作用聚合面**（106 条出边全库第一；包面反向
消费实测为 0，消费者全部直插子模块或经 facade）——它只该被 import 触发
注册，不该被当作取键入口：

- **禁止**业务代码 ``from rfauto.core.calc_families import <键名>`` 或
  直插子模块（``...calc_families.<族>.import <键>``）取计算器键——
  统一走 ``rfauto.core.calculators`` facade（public_api 快照钉 + patch
  扇出单源，见 test_calculators.py::test_patch_through_fanout_complete）。
- 本注记为文档化收缩（聚合面本体不动——瘦身/PEP 562 惰性化会动注册序
  语义，R1 Top7 原案经 #222 审计否决）；硬约束由 .importlinter 的
  ``calc-families-no-direct-consumption`` forbidden 契约钉死（业务层
  全禁，core 层内部公式单源复用白名单见该契约 ignore_imports）。
"""
# isort: skip_file
# 导入顺序=注册顺序（@register_calculator 装饰器 import 期生效，
# 字母重排会致 _specs 插入序漂移——放文件头才生效，批 1 实证）

from . import registry  # noqa: F401  # 注册副作用
from . import rf_line  # noqa: F401  # 注册副作用
from . import rf_match  # noqa: F401  # 注册副作用
from . import cm_core  # noqa: F401  # 注册副作用
from . import cm_extract  # noqa: F401  # 注册副作用
from . import thermal  # noqa: F401  # 注册副作用
from . import cavity  # noqa: F401  # 注册副作用
from . import symbolic  # noqa: F401  # 注册副作用
from . import slotline_siw  # noqa: F401  # 注册副作用
from . import budget  # noqa: F401  # 注册副作用
from . import cm_diag  # noqa: F401  # 注册副作用
from . import taper  # noqa: F401  # 注册副作用
from . import kqe  # noqa: F401  # 注册副作用
from . import rfid  # noqa: F401  # 注册副作用
from . import shield  # noqa: F401  # 注册副作用
from . import mask_spec  # noqa: F401  # 注册副作用（ge6 pool1 mask 闭环，追加尾位）
from . import cma  # noqa: F401  # 注册副作用（ge6 Wave1 CMA 离线档）
from . import chipless_rfid  # noqa: F401  # 注册副作用（ge6 pool3 chipless 编码，追加尾位）
from . import t_match  # noqa: F401  # 注册副作用（ge6 pool3 T-match，追加尾位）
from . import exposure_limits  # noqa: F401  # 注册副作用（ge6 pool3 暴露限值，追加尾位）
from . import link  # noqa: F401  # 注册副作用（LT-1 G/T 组合键，round18，追加尾位）
from . import propagation  # noqa: F401  # 注册副作用（AP-5 传播基础闭式包，§A-7，追加尾位）
from . import satellite  # noqa: F401  # 注册副作用（AP-9 卫星链路预算器，§A-10，追加尾位）
from . import fading  # noqa: F401  # 注册副作用（AP-7 多径衰落统计包，§A-9，追加尾位）
from . import allan  # noqa: F401  # 注册副作用（MS-5 Allan 方差/时钟稳定度，round15 :212，追加尾位）
from . import corona  # noqa: F401  # 注册副作用（MP-2 电晕/局放判据，round15 :82，追加尾位）
from . import noise_correlation  # noqa: F401  # 注册副作用（MT-1 噪声相关矩阵级联，round17，追加尾位）
from . import rx_impairments  # noqa: F401  # 注册副作用（MT-4 接收机损伤三件套，round17，追加尾位）
from . import mimo  # noqa: F401  # 注册副作用（NX-1 MIMO 虚拟阵+NX-10 MIMO 容量，round14 :88/:108，追加尾位）
from . import ms_gstc  # noqa: F401  # 注册副作用（MM-3 GSTC 面抗综合三键，§C-2，追加尾位）
from . import multipactor  # noqa: F401  # 注册副作用（MP-3 multipactor 击穿阈值，round15 :84，追加尾位）
from . import microwave_heating  # noqa: F401  # 注册副作用（LT-5..7 微波加热整包，round18 :137-144，追加尾位）
from . import electromigration  # noqa: F401  # 注册副作用（MP-4 电迁移-场联动，round15 :86，追加尾位）
from . import pll_loop_filter  # noqa: F401  # 注册副作用（MT-5 PLL 三阶环路滤波器综合，round17 :34，追加尾位）
from . import ris_cascade  # noqa: F401  # 注册副作用（NX-4 RIS 级联闭式表征，round14 :96-97，追加尾位）
from . import crlh  # noqa: F401  # 注册副作用（MM-4 CRLH 单元计算器，round17 :146，追加尾位）
from . import homogenization  # noqa: F401  # 注册副作用（MM-7 均匀化通用内核四键，round17 :154，追加尾位）
from . import reliability  # noqa: F401  # 注册副作用（XD-11 FORM 可靠度 form_beta_linear，ge XD-11 2026-10-04，追加尾位）
from . import array_synth  # noqa: F401  # 注册副作用（RB-ALG-1 差波束三法+RB-ALG-2 MIP 量化阵列，Phase3 W3-E，追加尾位）
from . import itu_link  # noqa: F401  # 注册副作用（AP-6 ITU 大气/雨衰三键，SD 部分件键面收口，追加尾位）
from . import cdr_mask  # noqa: F401  # 注册副作用（DR-8 CDR 抖动容限 mask 键，SG 部分件键面收口，追加尾位）
from . import thz_vna  # noqa: F401  # 注册副作用（TH-2 TNVNA 扩频误差模型+跨带拼接两键，SB22-TH-2，追加尾位）
from . import power_cal  # noqa: F401  # 注册副作用（SB22-MS-1 功率校准补偿链键，MS12 储备池席，追加尾位）
from . import wilkinson_unequal  # noqa: F401  # 注册副作用（aurora36 W3-A 不等分 Wilkinson 综合键，追加尾位）
from . import bethe_hole  # noqa: F401  # 注册副作用（aurora36 W3-A Bethe 孔定向耦合器双向键，追加尾位）
from . import modulation_ber  # noqa: F401  # 注册副作用（aurora36 W4-A 数字调制 BER/Eb-N0 三键，追加尾位，新增键按字母序互排）
from . import radar_eq  # noqa: F401  # 注册副作用（aurora36 W4-A 雷达方程/检测统计三键，追加尾位，新增键按字母序互排）
from . import combline_resonator  # noqa: F401  # 注册副作用（aurora36 W5-A combline/同轴腔谐振器三键，追加尾位，新增键按字母序互排）
from . import doa  # noqa: F401  # 注册副作用（aurora36 W5-A DOA 子空间+MVDR 三键，追加尾位，新增键按字母序互排）
from . import emc_immunity  # noqa: F401  # 注册副作用（aurora36 W6-A EMC 抗扰度三键，追加尾位，新增键按字母序互排）
from . import trl_standards  # noqa: F401  # 注册副作用（aurora36 W6-A TRL 校准件设计两键，追加尾位，新增键按字母序互排）
from . import pa_arch  # noqa: F401  # 注册副作用（aurora36 W7-A PA 平衡对+Doherty 合路网络三键，追加尾位，新增键按字母序互排）
from . import qubit_readout  # noqa: F401  # 注册副作用（aurora36 W7-A 量子比特读出链三键，追加尾位，新增键按字母序互排）
from . import coax_line  # noqa: F401  # 注册副作用（aurora72 A2-C 标准圆同轴传输线通用件三键，追加尾位，新增键按字母序互排）
from . import waveguide_closed_form  # noqa: F401  # 注册副作用（aurora72 A2-C 圆柱腔任意模式闭式谱三键，追加尾位，新增键按字母序互排）
from . import linear_antenna_zin  # noqa: F401  # 注册副作用（aurora72 A3-B 偶极/折合/小环输入阻抗三键，追加尾位，新增键按字母序互排）
from . import stub_tuner  # noqa: F401  # 注册副作用（aurora72 A3-B 双/三支节并联调配器两键，追加尾位，新增键按字母序互排）
from . import coupled_line_bpf  # noqa: F401  # 注册副作用（aurora72 A3-C 耦合线带通综合两键，追加尾位，新增键按字母序互排）
from . import interdigital_bpf  # noqa: F401  # 注册副作用（aurora72 A3-C 交指杆实现族两键，追加尾位，新增键按字母序互排）
from . import detector_device  # noqa: F401  # 注册副作用（aurora72 A4-B 检波器件两键，追加尾位，新增键按字母序互排）
from . import pim_cascade  # noqa: F401  # 注册副作用（aurora72 A4-B PIM 多节点累计两键，追加尾位，新增键按字母序互排）
from . import radar_detection_ext  # noqa: F401  # 注册副作用（aurora72 A4-A Swerling 1-4 检测补全两键，追加尾位，新增键按字母序互排）
from . import rcs_targets  # noqa: F401  # 注册副作用（aurora72 A4-B 雷达目标 RCS 闭式件两键，追加尾位，新增键按字母序互排）
from . import vna_uncertainty  # noqa: F401  # 注册副作用（aurora72 A4-A VNA 不确定度+增益定标三键，追加尾位，新增键按字母序互排）
from . import hybrid_junction  # noqa: F401  # 注册副作用（aurora72 A5-A 混合结/魔 T 三键，追加尾位，新增键按字母序互排）
from . import saw_idt  # noqa: F401  # 注册副作用（aurora72 A5-A 声表面波 IDT 三键，追加尾位，新增键按字母序互排）
from . import multisection_coupler  # noqa: F401  # 注册副作用（aurora72 A6-B 多节对称定向耦合器两键，追加尾位，新增键按字母序互排）
from . import gysel_core  # noqa: F401  # 注册副作用（aurora72 A6-B Gysel 功分器 core 电气两键，追加尾位，新增键按字母序互排）
from . import guanella_tlt  # noqa: F401  # 注册副作用（aurora72 A7-B Guanella 传输线变压器两键，追加尾位，新增键按字母序互排）
from . import waveguide_iris  # noqa: F401  # 注册副作用（aurora72 A7-B 矩形波导膜片/谐振窗三键，追加尾位，新增键按字母序互排）
from . import isolator_circulator  # noqa: F401  # 注册副作用（aurora72 A8-B 隔离器/环行器理想 S 两键，追加尾位，新增键按字母序互排）
from . import taper_classic  # noqa: F401  # 注册副作用（aurora72 A8-B 经典渐变线（线性/指数/三角，core7 原位扩展三角）两键，追加尾位，新增键按字母序互排）
from . import dr_te01d  # noqa: F401  # 注册副作用（批 B Wave3 G9 圆柱 DR TE01δ 正解/反解两键，追加尾位）
from . import helix_axial_reg  # noqa: F401  # 注册副作用（批 B Wave3 G17 轴向模螺旋薄注册三键，公式单源 core/helix_axial，追加尾位）
from . import yagi_uda  # noqa: F401  # 注册副作用（批 B Wave3 G15 Yagi-Uda NBS TN688 增益/几何两键，追加尾位）
from . import slot_array  # noqa: F401  # 注册副作用（批 B Wave3 G16 波导缝隙阵 Stevenson 正反解/谐振阵综合两键，追加尾位）
from . import doa_crb  # noqa: F401  # 注册副作用（aurora_d W3-CORE6 DOA 单源 CRB 下界键，追加尾位，新增键按字母序互排）
from . import multiplexer  # noqa: F401  # 注册副作用（aurora_d W3-CORE6 多工器信道规划键，追加尾位，新增键按字母序互排）
from . import phase_shifter  # noqa: F401  # 注册副作用（aurora_d W3-CORE6 加载线/开关线移相器两键，追加尾位，新增键按字母序互排）
from . import manufacturing_yield  # noqa: F401  # 注册副作用（aurora_d W3-CORE7 制造良率换算两键，追加尾位，新增键按字母序互排）
from . import finline  # noqa: F401  # 注册副作用（aurora_e W2-S9 鳍线-波导渐变过渡两键，K2 渐变过渡面，追加尾位）
from . import mtrl_uncertainty  # noqa: F401  # 注册副作用（aurora_e W2-S9 EC-2 multiline TRL 不确定度传播键，追加尾位）
from . import polarization_reg  # noqa: F401  # 注册副作用（aurora_e W4-S18 EC-21 极化传输面度量三键，薄注册公式单源 core/polarization，追加尾位）
from . import lange  # noqa: F401  # 注册副作用（aurora_f W1-S3 Lange 电桥综合/频响两键，render_c4 链提升式重构单一事实源，追加尾位）
from . import stepped_impedance  # noqa: F401  # 注册副作用（aurora_f W1-S3 阶梯阻抗 LPF 综合/频响两键，R2 F2 设计案，追加尾位）
from . import mixer_conversion  # noqa: F401  # 注册副作用（aurora_f W2-S6 混频器变换面三键，R2 D2 立项，追加尾位）
from . import directional_bridge  # noqa: F401  # 注册副作用（aurora_f W2-S6 定向电桥反射计桥两键，R2 D4 立项，追加尾位）
from . import rf_switch  # noqa: F401  # 注册副作用（aurora_f W2-S6 射频开关件面三键，R2 D8 立项，追加尾位）
from . import ruthroff_balun  # noqa: F401  # 注册副作用（aurora_f W2-S7 Ruthroff 巴伦设计/频响两键，R2 D1 官方声明缺口席——guanella_tlt:148 拒绝注记改指路补全，追加尾位）
from . import gd_equalizer  # noqa: F401  # 注册副作用（aurora_f W2-S7 群时延均衡器综合/级联两键，R2 D9 立项，追加尾位）
from . import measurement_drift  # noqa: F401  # 注册副作用（aurora_f W2-S7 测量漂移估计/监控两键，R2 D6 立项——anchor_drift_spc 统计内核复用，追加尾位）
from . import agc_loop  # noqa: F401  # 注册副作用（aurora_f W3-S10 AGC 环路动力学两键，R2 D3 立项——rx_impairments 预声明排除面改指路补全，追加尾位）
from . import cal_kit_verify  # noqa: F401  # 注册副作用（aurora_f W3-S10 校准件完整性验证两键，R2 D5 立项——trl_solt/measurement 使用链与 trl_standards 设计端不撞，追加尾位）
from . import six_port  # noqa: F401  # 注册副作用（aurora_f W3-S10 六端口反射计两键，R2 D7 立项——trl_standards:25 文献引注背书+directional_bridge 互指边界，追加尾位）
from . import ring_resonator  # noqa: F401  # 注册副作用（aurora_f W3-S11 环形谐振器综合/响应两键，R2 §⑤ F3——render_ring 设计链提升式重构单一事实源，追加尾位）
from . import kuroda_identities  # noqa: F401  # 注册副作用（aurora_f W4-S14 Kuroda 四恒等式+三阶低通全并联实现两键，R2 边际池立项——Pozar Table 8.7/Example 8.5 全链，追加尾位）
from . import pll_lock_time  # noqa: F401  # 注册副作用（aurora_f W4-S14 PLL 锁定/捕获时间一键，R2 边际池立项——线性包络精确+pull-in 近似档如实，追加尾位）
from . import iss_on_wafer  # noqa: F401  # 注册副作用（aurora_f W5-S18 在片 ISS 校准两键，R2 边际池立项——cal_kit_verify 同轴件与 trl_solt 理想档边界互指，追加尾位）
from . import source_power_cal  # noqa: F401  # 注册副作用（aurora_f W5-S18 源功率校准一键，R2 边际池立项——power_cal_chain 测量端/本键源编程端闭环互指，追加尾位）
from . import link_limits  # noqa: F401  # 注册副作用（aurora_g W1-S2 链路极限面三键，R2_core_tier4 §③ Top1——shannon/FSPL 独立键零命中补口，追加尾位）
from . import fec_codes  # noqa: F401  # 注册副作用（aurora_g W1-S2 FEC 块码族三键，R2_core_tier4 §③ Top3——coded_ber_estimate 的 G 产生面官方缺口补口，Q 函数单源复用 modulation_ber，追加尾位）
from . import dgs  # noqa: F401  # 注册副作用（aurora_g W2-S2 DGS 缺陷接地结构两键，R2_core_tier4 §③ C3——src/tests/scripts 三面全零首批键，追加尾位）
from . import if_digitizer  # noqa: F401  # 注册副作用（aurora_g W2-S2 IF 数字化欠采样规划两键，R2_core_tier4 §③ C4——adc_budget/if_plan_sweep 两邻边界内空白补口，追加尾位）
from . import wg_dielectric_window  # noqa: F401  # 注册副作用（aurora_g W2-S2 波导介质窗一键，R2_core_tier4 §③ C6——介质形态半波长谐振与膜片型成族两形态，追加尾位）
from . import analog_modulation  # noqa: F401  # 注册副作用（aurora_g W4-S4 模拟调制域三键——carson|fm_processing_gain 全仓零命中的模拟姊妹空白补口，追加尾位）
from . import si_ctle  # noqa: F401  # 注册副作用（aurora_g W4-S4 CTLE 独立面三键——com_pam4=COM 规格包裹消费面之外的通用零极点代数补口，追加尾位）
from . import microstrip_disc  # noqa: F401  # 注册副作用（aurora_g W6-S3 微带不连续寄生三键——R3 视角1 A1 Top1 双归属：弯角/T接/阶跃 KJK+HB+Garg-Bahl 闭式，fake_adapter 弯角寄生门消费面背书，追加尾位）
from . import radar_clutter  # noqa: F401  # 注册副作用（aurora_g W6-S3 雷达杂波+MTI 三键——R3 视角4 E2 Top2 雷达第五件收官：|H|=2|sin(πfTr)| 恒等锚+改善因子双路径+σ0 双档（GIT 缺席如实），追加尾位）
from . import hf_skywave  # noqa: F401  # 注册副作用（aurora_g W7-S3 HF 电离层天波三键——R3 视角3 D1 Top5 全频段唯一整段空白：f_p/secant/n² 标度恒等锚，追加尾位）
from . import fmcw_radar  # noqa: F401  # 注册副作用（aurora_g W7-S3 FMCW 波形-观测量映射两键——R3 视角3 D5 Top3 车载/ISAC 主流波形零命中补口，isac no-go 显式尊重，追加尾位）
from . import sar_geometry  # noqa: F401  # 注册副作用（aurora_g W7-S3 SAR 几何指标两键——R3 视角4 E6 Top10 遥感收官：δ_az=D/2 恒等锚，sar.py 比吸收率误中形态不撞，追加尾位）
from . import gnss_geometry  # noqa: F401  # 注册副作用（aurora_g W9-S2 内核新域批 3 GNSS 定位几何三键——R3 视角4 E1 Top6 导航场景空白收官：gdop|uere|dilution 三面零命中补口，DOP 线性代数恒等锚+UERE 恒等式，追加尾位）
from . import open_wire_line  # noqa: F401  # 注册副作用（aurora_g W10-S4 平衡开线族两键——R3 视角1 A2 rf_line 第七线型：开架双线/单线对地精确式+镜像退化恒等，twin|open_wire|明线 三面零命中补口，追加尾位）
from . import wg_cavity_bpf  # noqa: F401  # 注册副作用（aurora_g W10-S4 波导膜片耦合腔 BPF 综合链两键——R3 视角2 B1 微带耦合线姊妹空白：Cohn 1957 原生 λg 域全链，消费 wg_iris+matching 单源，追加尾位）
from . import building_penetration  # noqa: F401  # 注册副作用（aurora_g W14-S3 穿墙/建筑媒质两键——R3 视角4 E4 Top9 穿媒质传播空白收官：P.2040-4 Table 3 材料电性质+单层板 Fresnel/Airy 穿透链，seawater|穿墙|through_wall 三面零命中补口，追加尾位）
from . import microstrip_extra  # noqa: F401  # 注册副作用（aurora_g W15-S2 微带全族扩展四键——R3_domain_expansion §④ A1 余量+损耗/接地过渡族收口：十字结=不连续族第七件（qucsator mscross.cpp+手册 11.226-11.231 双源）、衰减率=Hammerstad-Jensen（msline.cpp+手册 11.79-11.83 双源，coax/波导有微带独缺的不对称补口）、接地过孔=G-P 1991（手册 11.232-11.234+finetune.co.jp 双源，msvia.cpp 漏 2π 偏差注记）、开路端辐射电导=Balanis 两极限分段式，追加尾位）
from . import link_modulation  # noqa: F401  # 注册副作用（aurora_h W1-K2 调制/数字链路波形体制域五键——R2_core_tier5 §③ 4-6 号：PAPR/CFR 提升核单源消费 core/papr、OFDM 参数/CP 设计对、扩频 Pickholtz 1982 余量三项分解，追加尾位）
from . import pulse_compression  # noqa: F401  # 注册副作用（aurora_h W1-K2 LFM 脉冲压缩设计键——R2_core_tier5 §③ 7 号：TB/压缩增益恒等式+ΔR 单源消费 isac_ambiguity（同仓双源一致）+距离-多普勒耦合闭式，isac no-go 同源尊重，追加尾位）
from . import matching_network  # noqa: F401  # 注册副作用（aurora_h W1-K1 L 节匹配提升核一键——R2_core_tier5 §③ 1 Top1：Pozar §5.1 两元件集总 L 节 calc_families 面零补口，core/matching.synthesize_l_match 现代入口包壳、0bf 遗留标签入口不透传，追加尾位）
from . import wg_fundamental  # noqa: F401  # 注册副作用（aurora_h W1-K1 矩形波导 TE10 衰减+功率容量两键——R2_core_tier5 §③ 2 同族不对称补口：圆波导全参数/矩形 λg 面已有、矩形衰减/功率独缺，TE10 场构造解微扰推导，追加尾位）
from . import tdr_measurement  # noqa: F401  # 注册副作用（aurora_h W1-K1 TDR 测量规划族三键——R2_core_tier5 §③ 3：故障定位/空间分辨率/等效时间采样恒等式族，测量规划面与 serdes_referee DR-3 剖面裁判面同仓分端不接线，追加尾位）
from . import antenna_regions  # noqa: F401  # 注册副作用（aurora_h W1-K1 近/远场区界提升核一键——R2_core_tier5 §③ 8：core/near_field_regions 全套闭式现成零键的注册面（Balanis ch.2 锚+π/8 相位判据几何互证透传），追加尾位）
from . import quantum_cryo  # noqa: F401  # 注册副作用（aurora_h W3-K 池件批超导 Rs/能隙两键——R2_core_tier5 §⑤-1/§③-14 提升核，池件 MP-7 同笔清偿：core/quantum_cryo 登记级现成零键的注册面，两流体+局部极限 Rs+BCS 能隙，residual 档预声明不加，追加尾位）
from . import antenna_q  # noqa: F401  # 注册副作用（aurora_h W3-K 池件批电小天线 Q 一键——R2_core_tier5 §⑤-2/§③-11 提升核，池件 T1-A-04 分期承诺同笔清偿：core/antenna_q 全套现成零键的注册面（Yaghjian-Best 2005+FBW 换算+Chu 界 verdict 单源消费 bounds），追加尾位）
from . import probability_paper  # noqa: F401  # 注册副作用（aurora_h W3-K 池件批 Weibull 概率纸一键——R2_core_tier5 §⑤-3 提升核，池件 XD-15 同笔清偿：core/probability_paper 三函数现成零键的注册面（Benard 中位秩+线性化+闭式 OLS），删失口径走 alt_planning 边界互指，追加尾位）
from . import conductor_reg  # noqa: F401  # 注册副作用（aurora_j W4-S12 良导体表面阻抗薄注册一键——EC-3 收口：δ/Rs/Zs 基准面，公式单源 core/conductor_loss 零复制（polarization_reg 同款薄注册），追加尾位）
from . import wg_evanescent  # noqa: F401  # 注册副作用（aurora_j W4-S12 矩形波导 TE10 截止下倏逝传播解一键——截止侧全仓空白补口：α 精确式+倏逝波阻抗 ηc，coax 截止衰减器/行波衰减键边界互指，追加尾位）
from . import antenna_aperture  # noqa: F401  # 注册副作用（aurora_j W4-S13 天线口径效率分解域三键——PLF §4.4.3 薄注册+反射面效率分量/最优角锥喇叭双提升核，公式单源 core/polarization·reflector_antenna·horn_synthesis 零复制，追加尾位）
from . import deembed_metrics  # noqa: F401  # 注册副作用（aurora_k K8 THRU 去嵌+Z12 串联指标两键——反馈 F6/P14：2x-thru 对称半拆双边去嵌（参考面移回 pad 边缘）+Z12 传输阻抗主口径/−1/Y21 并联免疫副口径+简化式强失配拒绝，公式单源 core/deembed K8 扩展面零复制（conductor_reg 同款薄注册），追加尾位）
from . import spiral_inductor  # noqa: F401  # 注册副作用（aurora_k K11 八角螺旋电感一键——反馈 F1：GaAs IPD 工艺 μm 参数→Mohan 三式 L+GMD+SRF/Q 一阶+L±25%/SRF>2×f0 质量门，公式单源 core/nfc_coil 四形状内核零复制（deembed_metrics 同款薄注册），追加尾位）
from . import ipc_cap  # noqa: F401  # 注册副作用（aurora_k K12 两键——反馈 F1：MIM 平行板精确式+叉指 IDC 侧壁 sum-of-capacitances 一阶，C±25%/±50%+SRF>2×f0 质量门，公式单源 core/ipc_cap 零复制（deembed_metrics 同款薄注册），追加尾位）
from . import terminated_line  # noqa: F401  # 注册副作用（aurora_l G1 端接线输入阻抗精确解一键——Pozar §2.3-2.4 sin/cos 形：微波网络最基本单线变换闭式，vswr_convert 标量面/stub_tuner 调配面不撞，追加尾位）
from . import filter_prototype  # noqa: F401  # 注册副作用（aurora_l G1 最平坦低通原型一键——Pozar §8.2 g_k 生成式+RL/RS/ωs 阶数闭式+梯形 ABCD vs 多项式双路径自证，chebyshev_prototype 耦合矩阵级不撞，追加尾位）
from . import network_convert  # noqa: F401  # 注册副作用（aurora_l G1 二端口 S/Z/Y/ABCD 全对全换算一键——Pozar §4.4 网络互换恒等式+串联/并联单元表示缺席如实 null，kuroda/deembed 面不撞，追加尾位）
from . import oscillator_leeson  # noqa: F401  # 注册副作用（aurora_l G1 Leeson 振荡器相噪模型一键——Leeson 1966 谱形产生面，phase_noise_evm 消费面不撞，追加尾位）
from . import branchline_coupler  # noqa: F401  # 注册副作用（aurora_l G1 分支线耦合器理想设计一键——Pozar §7 臂阻抗闭式+奇偶模解析 4×4 S 矩阵（匹配+隔离⟺(1/Z1)²−(1/Z2)²=(1/Z0)² 推导在案），synthesize_branchline 模板级不撞，追加尾位）
