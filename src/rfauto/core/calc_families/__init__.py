"""calc_families：core/calculators.py 巨石拆分包（AU-1 批 2，2026-09-30）。

导入本包即完成全部计算器注册（子模块按原文件定义顺序导入，
CALCULATOR_REGISTRY._specs 插入序与原单文件逐位一致）。
公开入口 = rfauto.core.calculators（facade，逐名 re-export）。
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
