"""WP0.2 微波计算器（E4）单测：闭式解对照 + 注册表语义 + service JSON。

数值断言口径（#118 教训）：锚值先独立实测（scipy 椭圆积分/ABCD 级联/
skrf 回代），不赌推导；带状线 w/b=1、er=1 → 65.4Ω 为零厚度共形映射
闭式的自洽锚（独立脚本实测后写死）。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import (
    CALCULATOR_REGISTRY,
    CalculatorRegistry,
)
from rfauto.service.calculator_service import (
    list_calculators,
    run_calculator,
)

EXPECTED = {
    "microstrip_analysis", "microstrip_synthesis", "microstrip_lambda_g",
    "cpw_analysis", "cpw_synthesis",
    "cpwg_analysis", "cpwg_synthesis",
    "stripline_analysis", "stripline_synthesis",
    # C9 传输线族 II（2026-09-15）：共面带 CPS（Wadell/Gupta 共形闭式）+ 悬置带线
    # （两支精确极限锚回到 _stripline_z0，共形电容比填充因子），refs §11
    "cps_analysis", "cps_synthesis",
    "suspended_stripline_analysis", "suspended_stripline_synthesis",
    # 槽线（2026-09-18 w1b 注册，#231 三表同步）：Janaswamy–Schaubert 闭式
    # core/slotline（路线 A 裁判面），越域显式拒绝不外推
    "slotline_analysis", "slotline_synthesis",
    # SIW（2026-09-22 siw-family 立项，#231 三表同步）：Cassivi 2002 等效宽度
    # + RWG TE10 等效（双源出处 runs/siw_family/criteria.md §1；WR-90/RWG
    # 极限回收钉在 test_siw_template）
    "siw_analysis", "siw_synthesis",
    "quarter_wave_transformer", "attenuator_pi", "attenuator_t",
    # F8 首族变体锚（#19 提议→沙箱→三层 Gate 链，2026-09-16）：桥 T 型闭式
    "attenuator_bridged_t",
    "vswr_convert", "patch_length",
    "chebyshev_prototype", "chebyshev_prototype_asym", "chebyshev_refl_fn",
    "coupling_matrix_synthesize_n2", "coupling_matrix_synthesize_explicit",
    "coupling_matrix_arrow",
    "coupling_matrix_folded", "coupling_matrix_response",
    "coupling_matrix_extract",
    # E4 热/功率闭式族（§10.21 第九轮 E4 补强）
    "resonator_thermal_drift", "ipc2152_trace_temp_rise",
    "thermal_resistance_stack", "microstrip_loss_heat",
    "parallel_plate_breakdown_margin", "ecss_multipactor_fd",
    # B3 腔体微扰频移（Pozar §6.7 / Slater 一阶式）
    "cavity_perturbation_shift",
    # DP-5 系统级预算引擎 + spur search（2026-09-24 df6_dp5cascade，#231 三表同步）
    # payload=core/cascade.py；回收钉 runs/df6_dp5cascade/criteria.md
    "cascade_budget", "spur_search", "if_plan_sweep",
    # DP-2 耦合矩阵诊断三件套（2026-09-24 df6_dp2diag，#231 三表同步）：
    # VF+LM 固定拓扑反演 + Q 双通道 + Dishal critique；判据预声明
    # runs/df6_dp2diag/criteria.md；既有 Cauchy 反提键保留为独立裁判（#315）
    "cm_extract_vf", "cm_refine_lm", "q_factor_vf", "q_factor_circle",
    # T36（2026-09-29）：Q 半零点法第四键——Γ 极点+零点求和口径免 q_e
    # （launch_ready §6① 落地；存档验证
    # runs/df6_dp2diag/q_half/vf_zero_archive_check.json vs circle 0.01%/0.19%）
    "q_factor_vf_zero",
    "cat_critique",
    # DP-15 C2 Klopfenstein 渐变段（2026-09-24 df6_dp15c2，#231/#304 四表
    # 同步）：skrf.taper.Klopfenstein 剖面 + 微带 MLine 同源宽度剖面；
    # 判据预声明 runs/df6_dp15c2/criteria.md §3
    "klopfenstein_taper",
    "k_split_pair",
    "qe_group_delay",
    # r6 插② UHF RFID 链路预算闭式（2026-09-26，#231 五钉同步）：Nikitin-Rao
    # 正向 Friis + 反向单站雷达方程 + 差分 RCS（与 NFC 近场面近/远场双覆盖）
    "rfid_forward_link", "rfid_backscatter_link",
    # QW-11 屏蔽效能（2026-09-26，#231 五钉同步）：Schelkunoff 平面波三段
    # 闭式（吸收/反射/多次反射），SE=A+R+B≡−20lg|S21_ABCD| 恒等式钉于
    # test_qw10_qw11；材料表复用 D15 provenance 格式（Ott 2009 §6 典型值）
    "shielding_effectiveness",
    # ge6 pool1 mask→滤波器规格综合闭环（2026-09-30，#231 五钉同步）：
    # 遮罩→切比雪夫最小阶 acosh 闭式 + cm_core N+2 耦合矩阵裕量回验 + 自动
    # +1 闭环（实现 core/mask_filter_synthesis.py，注册薄壳
    # calc_families/mask_spec.py；内置 FCC §15.247/IEEE 802.11 DSSS/
    # 3GPP NR ACLR 三模板）
    "mask_min_order", "mask_margin_report", "mask_filter_synthesize",
    # ge6 Wave1 CMA 特征模离线档（2026-09-30，#231 五钉同步）：广义阻抗
    # 矩阵 Z=R+jX 的 R-加权特征模分解（Harrington–Mautz 1971/Cabedo-
    # Fabrés 2007 口径；实现 core/characteristic_modes.py，注册薄壳
    # calc_families/cma.py；散射 dyadic CMA 重建层另行立项）
    "cma_modes",
    # ge6 pool3 三小件（2026-09-30，#231 五钉同步）：① chipless RFID
    # 频域零点编码（滤波器组谐振器组等 Q 深谷，Matthaei 斜率参数口径；
    # 实现 core/chipless_rfid.py，注册薄壳 calc_families/chipless_rfid.py）；
    # ② T-match 匹配闭式（Balanis 3ed §9.7.3 (9-48)–(9-55) 原文逐位；
    # 实现 core/t_match.py，薄壳 calc_families/t_match.py）；
    # ③ RF 暴露限值表（FCC 47 CFR §1.1310(e)(1) Table 1 + ICNIRP 2020
    # Table 5 公众，原文逐位抄录；实现 core/exposure_limits.py，薄壳
    # calc_families/exposure_limits.py）
    "chipless_tag_plan", "chipless_tag_encode", "chipless_tag_decode",
    "t_match_impedance", "t_match_design",
    "exposure_mpe_limit", "exposure_compliance_distance",
    # LT-1 G/T 组合键（round18 :129，2026-10-02，#231 五钉同步）：G/T =
    # G_dB−10·log10(T_sys)（ITU-R S.733-2 定义口径）；实现 core/gt_link.py，
    # 注册薄壳 calc_families/link.py；T_sys 三路径（t_sys_k/nf_db/t_e_k），
    # 恒等式回收+级联链消费钉 tests/unit/test_gt_link_calculators.py
    "gt_ratio",
    # LT-5..7 微波加热整包三键（round18 :137-144，2026-10-02，#231 五钉同步）：
    # ① 多模腔模式统计+装填因子（Weyl N=8πV(f√εr/c0)³/3 与 rect_cavity_modes
    # 精确枚举交叉对拍+均匀场装填匹配，Metaxas & Meredith Ch.5 口径；实现
    # core/microwave_heating.py，薄壳 calc_families/microwave_heating.py）；
    # ② 单模 applicator（TE10p 场量归一+壁损能量法 Q+介质负载沉积链，微扰
    # 失谐组合复用 cavity_perturbation_shift 零重实现；Pozar §6.4/§6.7 口径）；
    # ③ 工艺窗口+热失控（消费 thermal_transient.step_response_zth 功率-时间窗
    # +tanδ(T) 指数链定点迭代+α_crit=1/(e·R_th·P0) 折叠界，thermal_iteration
    # 方法论）；锚树 tests/unit/test_microwave_heating.py（Weyl 渐近对拍/
    # 均分恒等式/壁损数值面积分裁判/双路功率恒等/失控分界复现/单 RC 解析窗/
    # 1kW 水负载 0.24°C/s 量级锚）；weyl/精确计数/装填匹配/TE10p 场量/体吸收/
    # 定点迭代/失控界/工艺窗为 core 纯函数不注册
    "multimode_cavity_heating", "single_mode_applicator",
    "microwave_process_window",
    # AP-5 传播基础闭式包（§A-7，2026-10-02，#231 五钉同步）：two_ray_loss
    # 双径干涉（Fresnel Γ_v/Γ_h+断点 4·h_tx·h_rx/λ）/ knife_edge_loss 刃形
    # 绕射（P.526-15 exact/approx/lee 三档，J(0)=6.02dB 实测锚）/
    # hata_cost231 经验路损（150–2000MHz 统一域盒，Rappaport §4.10）；
    # 实现 core/propagation.py，薄壳 calc_families/propagation.py；
    # 锚树 tests/unit/test_propagation.py（断点连续/−40dB·dec/Brewster/
    # 域盒四角/接缝跳变），fresnel_zone_radius/clearance_ok 纯辅助不注册
    "two_ray_loss", "knife_edge_loss", "hata_cost231",
    # AP-9 卫星链路预算器（§A-10，2026-10-02，#231 五钉同步）：单跳链路
    # 预算逐项（EIRP→FSPL+pointing+gas+rain→G/T（gt_link 单源）→C/N0→
    # C/N→margin），LEO 圆轨几何（斜距 d=√((Re+h)²−(Re·cosE)²)−Re·sinE
    # +多普勒 rising/setting）；gas 项走 itu_atmosphere 降级面（表
    # UNVERIFIED→0+注记不产假数）；MODCOD 表 UNVERIFIED 档不做（需求门
    # 显式输入）；实现 core/sat_link.py，薄壳 calc_families/satellite.py；
    # 锚树 tests/unit/test_sat_link.py（FSPL 恒等/G-T↔NF 往返逐位/天顶
    # d=h/GEO 公开算例量级窗/降级面）
    "sat_link_budget",
    # AP-7 多径衰落统计包（§A-9，2026-10-02，#231 五钉同步）：
    # fade_outage_percent 小尺度/阴影衰落 CDF 族（Rice 走非中心 χ²
    # chndtr 等价路径（scipy 1.18.1 无 marcumq 实测）/Rayleigh 闭式/
    # Nakagami-m 不完全 Gamma/对数正态 erfc；K→0≡Rayleigh 3e-17、
    # m=1≡Rayleigh 恒等，任务书 "K→∞→Rayleigh" 系笔误实测勘误）/
    # availability_margin 可用性↔裕量双向换算+V-B（Barnett 1972 BSTJ
    # 51(2) §6.3 一手核）vs P.530-18（§2.3.1 式(7) 文本层核）同参
    # 差异带（不设对错门）；实现 core/fading.py，薄壳
    # calc_families/fading.py；锚树 tests/unit/test_fading.py（退化/
    # 恒等/scipy 互证/单调/V-B Table II 回核/差异带），V-B 单参直算
    # vigants_barnett_outage 纯辅助不注册
    "fade_outage_percent", "availability_margin",
    # MS-5 Allan 方差/时钟稳定度（2026-10-02，#231 五钉同步）：重叠/非重叠
    # Allan 偏差 + IEEE 1139 Table 1 斜率分类摘要（round15 :212 规格
    # 「重叠 Allan 三 coef 公式与 clock_noise 幂律谱互检」；round16 §二
    # :49 与 clock_noise Leeson 接回合并，与 DR-8 CDR 互补）；实现
    # core/allan_variance.py，薄壳 calc_families/allan.py；锚树
    # tests/unit/test_allan_variance.py（白频/白相离散精确解析例/线性
    # 漂移零随机恒等/MDEV 白相 −3/2 NIST 表双证/闪烁频 PSD↔ADEV 互检/
    # 三 coef 闭式回核/L(f) 桥手算 2e-22）；mdev/classify_joint/
    # avar_from_h/h_from_l_points 为 core 纯函数不注册
    "allan_deviation",
    # MP-2 电晕/局放判据（2026-10-02，#231 五钉同步）：Paschen+海拔降额
    # 三面裕量报告（round15 §三 :82 规格「电晕/局放判据（Paschen+海拔
    # 降额）入 high_power，ECSS-E-ST-10-04C 语境」；high_power 既有语义
    # 零改动，判据面独立落档）；实现 core/corona.py，薄壳
    # calc_families/corona.py；锚树 tests/unit/test_corona.py（Schumann
    # 1mm→4.345kV/1cm→30.3kV 经典锚/Townsend 手算 5035V+Paschen 最小值
    # 305V@0.836cm·Torr 自洽/Peek 39.03 峰值·27.60 rms kV/cm 量级锚/
    # 镜像定理恒等式/ISA 22632.1Pa@11km 表值/10km 降额比手算链/左支
    # 无解域显式拒绝）；isa/δ/townsend/peek/几何因子为 core 纯函数不注册
    "corona_pd_check",
    # MP-3 multipactor 微放电击穿阈值（2026-10-02，#231 五钉同步）：平行板
    # 一阶渡越敏感带 × SEY crossover 窗口合成裕量报告（round15 §三 :84 规格
    # 「Vaughan 二次发射+20-gap 串接+N 载波等效功率」；high_power 的 ECSS
    # f·d 实验包络既有语义零改动，机制面独立落档）；实现 core/multipactor.py，
    # 薄壳 calc_families/multipactor.py；锚树 tests/unit/test_multipactor.py
    # （V_1=K/π=71.4477V@fd=1 手算/带边 60.2707 与 112.2298V/序间 ÷(2n−1)
    # 精确标度/碰撞能量恒等式/Vaughan 曲线构造恒等式+crossover 回收/M1–M6
    # 参数表逐值/M2 窗带 1=[68.7960,71.4477]V 手算链/非相干 RSS vs 相干
    # (Σ√Pi)²/20-gap 链级缩放/负例守卫）；谐振线/带边/SEY 曲面/级联换算
    # 为 core 纯函数不注册
    "multipactor_susceptibility_check",
    # MP-4 电迁移-场联动（2026-10-02，#231 五钉同步）：loss_density 场→局部
    # J→Black MTTF + IPC-2152 ΔT 联合（round15 :86；Black/Arrhenius 消费
    # core/aging 既有实现零重复，温度链消费 MP-1 core/thermal_transient
    # Foster Z_th，既有语义零改动）；实现 core/electromigration.py，薄壳
    # calc_families/electromigration.py；锚树 tests/unit/
    # test_electromigration.py（J=sqrt(q/ρ) 手算 2.4084e8 A/m²+TCR 链/
    # q↔J 往返恒等式/Black 708.2h 手算回收/AF 55→125°C 77.64 手算+
    # MTTF 比值恒等式/单调性/Blech Cu Δσ=50MPa→2.14e3 A/cm 文献带+
    # 摩尔体积独立推 Ω/immortal-mortal 双向判/margin 恒等式/Foster 稳态
    # 85°C+瞬态 38.04°C 手算/IPC-2152 ΔT 组合链演示/负例守卫）；
    # local_current_density/resistivity_at/blech_* 为 core 纯函数不注册
    "electromigration_mttf_check",
    # NX-1 MIMO 虚拟阵（2026-10-02，#231 五钉同步，B 流）：TX×RX Kronecker
    # 展开虚拟阵/等效孔径/角分辨率（round14 §四 :88；Li & Stoica IEEE SPM
    # 24(5) 2007 sum co-array 口径；EuRAD 2023 12×6→17 元验收锚）；实现
    # core/mimo_virtual_array.py，薄壳 calc_families/mimo.py；锚树
    # tests/unit/test_mimo_virtual_array.py（等距 ULA M+N−1 闭式+三角多重数/
    # 孔径可加恒等式/乘积≡等效物理阵 1e-15/sparse_array_cs.forward_matrix
    # Kronecker 同构/首零 1/(max(M,N)d) 精确/monostatic 孔径加倍/等距
    # 不等距负例），sum/difference 双口径；虚拟阵几何辅助（元素表/两路
    # 方向图）为 core 纯函数不注册
    "mimo_virtual_array",
    # NX-10 MIMO 信道容量/分集（2026-10-02，#231 五钉同步，B 流）：
    # Telatar 1999 C=log₂det(I+γHH†) + Tse-Viswanath 等功率/注水两档+
    # 秩/有效分集阶（round14 §四 :108；S 参→H 提取归 ecc_metrics 既有
    # 语义零改动）；实现 core/mimo_capacity.py，薄壳 calc_families/
    # mimo.py；锚树 tests/unit/test_mimo_capacity.py（对角 2×2 正交容量
    # 求和恒等 log2(52)/slogdet 独立路径+口径恒等/秩亏退化/注水闭式
    # [1.375,0.625]+截模 log2(11)/H=0 零容量/i.i.d. Rayleigh MC 均值 vs
    # e^{1/γ}E₁(1/γ)·log₂e 解析），waterfilling_powers/
    # capacity_from_eigenvalues/eigenvalues_hh 为 core 纯函数不注册
    "mimo_channel_capacity",
    # MT-1 噪声相关矩阵级联（2026-10-02，#231 五钉同步）：Hillbrand-Russer
    # 链式噪声相关矩阵在匹配 z0 功率波域的显式式（round17 §二 MT-1；
    # Wedge-Rutledge IEEE T-MTT 40(4) 1992 二手承载）；实现
    # core/noise_correlation.py，薄壳 calc_families/noise_correlation.py；
    # 锚树 tests/unit/test_noise_correlation.py（ρ=0 逐位退化 Friis 对拍
    # cascade_budget/ρ=±1 两极限闭式/Cholesky 合成蒙特卡洛独立裁判回收
    # 解析 F/fet_noise 双管级联对拍/PSD 守卫负例/F≥1 解析保证）；
    # correlation_matrix/cholesky_factor/synthesize_correlated/
    # combine_noise_power 为 core 纯函数不注册
    "correlated_cascade_nf",
    # MT-4 接收机损伤三件套（2026-10-02，#231 五钉同步）：IQ 失衡 IRR
    # （Razavi 式+3GPP TS 38.141-1 EVM 消费口径）/相噪→积分 EVM（消费
    # clock_noise.phase_jitter_from_l 不重实现）/blocking 预算（倒易混频
    # desense+P1dB 裕量+杂散落带，复用 cascade_budget/spur_search 既有
    # 语义零改动）（round17 §二 MT-4）；实现 core/rx_impairments.py，薄壳
    # calc_families/rx_impairments.py；锚树 tests/unit/test_rx_impairments
    # .py（IRR cot²(φ/2) 与完全平方两极限+复模形式独立路径/平谱 σ_φ 手算
    # 逐位/desense 线性域 mW 算术独立路径/(2,2) medium 与 (2,1) high 落带
    # 翻面/P1dB 裕量手算±翻转）
    "iq_imbalance_irr", "phase_noise_evm", "blocking_budget",
    # MT-5 PLL 三阶环路滤波器综合（2026-10-02，#231 五钉同步）：Banerjee
    # SNAA106C T1/T2/T3→C1/C2/R2/C3 闭式+相位裕度迭代（round17 §二 :34；
    # 峰值相位放置 dPM/dω|ωc=0、r=T3/T1 显式设计自由度，A0 由 |G(jωc)|=1
    # 闭式回代）；实现 core/pll_loop_filter.py，薄壳
    # calc_families/pll_loop_filter.py；锚树 tests/unit/test_pll_loop_filter
    # .py（规格验收回代复现 f_c/PM 双路径/Gardner 二阶几何中值极限 uv→1
    # 逐位/真峰邻域裁判/闭环 |H(jωc)|=1/(2sin(PM/2)) 恒等/bw_3db 独立路径/
    # CP 噪声整形带内 N/Kφ+低通/元件闭式重构恒等/可达 PM 窗外显式拒绝）；
    # 开环/闭环/误差/CP 噪声整形传函为 core 纯函数不注册（pll_budget 既有
    # 语义零改动——规格补强项「pll_budget 接 MT-5 综合入口」留消费侧接线）
    "pll_loop_filter_synthesize",
    # MM-3 GSTC 面抗综合三键（2026-10-02，#231 五钉同步，B 流超材料）：
    # 法向入射单轴 Huygens 面闭式（规格 §C-2，arXiv 1408.0273v2=IEEE TAP
    # 63(7) 2015 Eq.(17)/(18)/(19) 逐式核到）；实现 core/gstc.py，薄壳
    # calc_families/ms_gstc.py；无源守卫 |R|²+|T|²≤1+1e-9、Eq.19↔Eq.17
    # 往返逐位 ≤1e-12 自检、χ_em/χ_me 显式不做；锚树 tests/unit/test_gstc.py
    # （对称 χ R=0/实 χ 能量恒等/电阻膜 T=2/3/CPA/PEC 帘渐近/奇点负例/
    # LUT v2 通道桥）；gstc_lut_crosscheck=J4 Floquet 锚通道接口面
    # （带内 Δ|T|≤0.5dB 起步，真机正演腿留位）
    "gstc_forward", "gstc_synthesize", "gstc_lut_crosscheck",
    # NX-4 RIS 级联闭式表征（2026-10-02，#231 五钉同步）：BS-RIS-UE 几何
    # 级联+路径损耗∝N²（round14 §四 :96-97，Björnson TWC 2020；ETSI GR
    # RIS 001 用例/KPI 语义引用，PV-020 免费交付物）；实现
    # core/ris_cascade.py，薄壳 calc_families/ris_cascade.py；锚树
    # tests/unit/test_ris_cascade.py（单元退化=镜面反射相位不敏感/
    # 共轭 vs 随机比值精确 N+MC 固定种子/四次律 2+2 vs 平方律精确斜率/
    # 交叉距离 4π·d1·d2/(N·λ) 手算+两侧翻转/谱峰对准 UE 几何方向/
    # 量化损失对拍 metasurface_lut sinc² 解析带/近场共轭>远场配相/
    # 负例守卫）；fspl_db/conjugate_phases_rad/直连 Friis 为 core 纯
    # 函数不注册（分析面走 core 直调）
    "ris_cascade_budget",
    # MM-4 CRLH 单元计算器（2026-10-02，#231 五钉同步，B 流超材料翻案件）：
    # 色散 β(ω)/平衡条件/ZOR ω0=1/√(L_L·C_R)/漏波角闭式+skrf 级联
    # （round17 §五 :146；翻案声明：前轮 no-go 仅限 openEMS 模板形态，
    # 计算器+skrf 形态成立）；实现 core/crlh.py，薄壳
    # calc_families/crlh.py；锚树 tests/unit/test_crlh.py（平衡点 β 过零
    # =ω_se=ω_sh=ZOR 恒等+scipy 求根对拍/左手 β<0 相位超前符号钉
    # −344.2312/右手 +334.3078/非平衡阻带 Re β=0+Im β<0/深阻带 Bloch
    # 相位 −π/d 精确恒等/Z_CRLH 平衡恒值 √(L_R/C_R)=63.2456+阻带高阻
    # 极限 1093.89Ω@0.999f_sh/漏波角 ±9° 锚+|β|≥k0 None/skrf 级联对拍
    # ≤0.1dB/1° 实测 1e-14dB/1e-13°/负 L·C 与 ω≤0 显式拒绝）；β/Z_T/
    # 不平衡参数/漏波角/闭式 S21/skrf 级联为 core 纯函数不注册（级联
    # 对拍面走 core 直调+锚树）
    "crlh_unit_cell_report",
    # MM-7 均匀化通用内核四键（2026-10-02，#231 五钉同步，B 流超材料）：
    # 规格 §五 :154「三混合式提升通用 core 内核+Wiener 界+Pendry 1999
    # SRR μ 公式+线媒质 ωp（Pendry 1996 PRL）」；实现
    # core/homogenization.py（复数通用核+depolarization L 形状族），
    # 薄壳 calc_families/homogenization.py；锚树
    # tests/unit/test_homogenization.py（L=1/3 与 humidity_drift 跨模块
    # 一致 rel≤1e-12/MG L=0 与 L=1 极限=Wiener 界本身/Bruggeman 换相对
    # 称恒等式/SRR μ(0)=1·μ(∞)=1−F·μ(f_mp)=0 逐位+负 μ 带=(f_res,f_mp)
    # +Γ>0 Im μ>0 无源性/线媒质 a=1mm·r=1µm f_p≈45.5GHz 手算链+Drude
    # ω=ωp 精确零点/反演合成回收双路径 ≤1e-10+支差 2π/(k0d) 恒等+厚面板
    # 回绕支恢复+能量/退化域显式拒绝）；depolarization_factors/
    # wiener_bounds/slab_panel_rt/mix_eff 边界守卫为 core 纯函数不注册
    "homog_mix_eff", "srr_permeability", "wire_media_plasma",
    "retrieve_eff_params",
    # XD-11 FORM 一阶可靠度（2026-10-04，#231 五钉同步）：线性极限状态
    # 面便捷键 form_beta_linear（内核 core/form_reliability.py HL-RF，
    # 薄壳 calc_families/reliability.py）；锚树 tests/unit/test_form_
    # reliability.py（Hasofer-Lind 线性面 β=3/√5 设计点/α 逐位 1e-9、
    # R−S 应力-强度 50/√1300 Pf 对拍 norm.sf、非线性面 MC 1e6 固定种子
    # 30% 预声明带+Gauss 求积双裁判、SORM 凸面 β_sorm≥β 弱钉+Breitung
    # 适用域守卫、Acklam 逆 CDF 对拍 scipy 防常数笔误）；form_beta/
    # sorm_beta_correction 为 core 纯函数不注册（非线性面走 core 直调）
    "form_beta_linear",
    # W3-E RB-ALG-1/2 四键（2026-10-05，sa_specs2 §七；内核 core/array_
    # synthesis.py 增段+core/quantized_array_milp.py，薄壳 calc_families/
    # array_synth.py 全部 reciprocal=False）；锚树 tests/unit/test_w3_e_
    # array_synth.py（Doerry SAND-2025-07335 Table 1 双源逐位）+test_w3_e_
    # quantized_milp.py（8^8 全枚举对拍 5.2e-17）
    "array.bayliss_weights",
    "array.villeneuve_weights",
    "array.schelkunoff_nulls",
    "array.quantized_milp",
}

# W1⑨（2026-09-16 用户口径）：实验态计算器分表——自动归纳（符号回归）公式
# 一律 experimental=True 入库但默认关。EXPECTED 断言 names() **默认排除**；
# include_experimental=True 才含本表（默认列/默认跑都不过这道开关）。
EXPERIMENTAL_EXPECTED = {
    # E13 patch 基模谐振候选公式（51 点归纳，vs HJ 0.765%）
    "patch_f0_symbolic_e13",
}


# ─── 注册表语义（接口先行）────────────────────────────────────────────────────

def test_registry_has_expected_calculators():
    assert set(CALCULATOR_REGISTRY.names()) == EXPECTED


def test_registry_include_experimental():
    """默认名单不含实验键；显式 include_experimental 才含（并集恰满）。"""
    full = set(CALCULATOR_REGISTRY.names(include_experimental=True))
    assert full == EXPECTED | EXPERIMENTAL_EXPECTED
    assert full >= EXPERIMENTAL_EXPECTED
    assert not (EXPERIMENTAL_EXPECTED & set(CALCULATOR_REGISTRY.names()))


def test_registry_is_experimental():
    assert not CALCULATOR_REGISTRY.is_experimental("microstrip_analysis")
    for key in EXPERIMENTAL_EXPECTED:
        assert CALCULATOR_REGISTRY.is_experimental(key)
    with pytest.raises(KeyError):
        CALCULATOR_REGISTRY.is_experimental("no_such_calc")


def test_describe_experimental_filtering_and_flag():
    """describe 默认排除实验键；条目恒带 experimental 元数据标签。"""
    default = CALCULATOR_REGISTRY.describe()
    by_name = {c["name"]: c for c in default}
    assert not (set(by_name) & EXPERIMENTAL_EXPECTED)
    assert all(c["experimental"] is False for c in by_name.values())
    full = {c["name"]: c
            for c in CALCULATOR_REGISTRY.describe(include_experimental=True)}
    assert set(full) == EXPECTED | EXPERIMENTAL_EXPECTED
    for key in EXPERIMENTAL_EXPECTED:
        assert full[key]["experimental"] is True


def test_registry_unknown_name_keyerror_lists_available():
    with pytest.raises(KeyError) as ei:
        CALCULATOR_REGISTRY.get("no_such_calc")
    assert "microstrip_analysis" in str(ei.value)


def test_registry_duplicate_registration_rejected():
    reg = CalculatorRegistry()
    spec = CALCULATOR_REGISTRY.get("vswr_convert")
    reg.register(spec)
    with pytest.raises(ValueError, match="重名"):
        reg.register(spec)


def test_describe_is_json_ready_with_param_metadata():
    items = list_calculators()["calculators"]
    by_name = {c["name"]: c for c in items}
    ms = by_name["microstrip_analysis"]
    assert ms["description"]
    required_names = {p["name"] for p in ms["params"] if p["required"]}
    assert {"width_mm", "freq_ghz", "epsilon_r", "h_mm"} <= required_names
    # 全部条目可 JSON 序列化（JSON 进出契约）
    import json
    json.dumps(list_calculators(), ensure_ascii=False)


# ─── 微带 ────────────────────────────────────────────────────────────────────

def test_microstrip_synthesis_roundtrip_50ohm():
    out = run_calculator("microstrip_synthesis",
                         {"z0_ohm": 50, "freq_ghz": 2.4,
                          "epsilon_r": 3.66, "h_mm": 0.508})
    assert out["ok"]
    r = out["result"]
    assert r["status"] == "ok"
    assert abs(r["z0_actual_ohm"] - 50.0) < 0.5
    back = run_calculator("microstrip_analysis",
                          {"width_mm": r["width_mm"], "freq_ghz": 2.4,
                           "epsilon_r": 3.66, "h_mm": 0.508})
    assert abs(back["result"]["z0_ohm"] - 50.0) < 0.5


def test_microstrip_analysis_monotonic_in_width():
    thin = run_calculator("microstrip_analysis",
                          {"width_mm": 0.05, "freq_ghz": 2.4,
                           "epsilon_r": 3.66, "h_mm": 0.508})["result"]
    wide = run_calculator("microstrip_analysis",
                          {"width_mm": 3.0, "freq_ghz": 2.4,
                           "epsilon_r": 3.66, "h_mm": 0.508})["result"]
    assert thin["z0_ohm"] > wide["z0_ohm"]  # 线宽↑ → Z0↓
    for r in (thin, wide):
        assert 0.4 * 3.66 < r["eps_eff"] < 3.66  # 准静态 εeff 界


def test_microstrip_lambda_g_consistency():
    r = run_calculator("microstrip_lambda_g",
                       {"width_mm": 1.1, "freq_ghz": 2.4,
                        "epsilon_r": 3.66, "h_mm": 0.508})["result"]
    lam0 = 299.792458 / 2.4
    assert abs(r["lambda_0_mm"] - lam0) < 0.01
    assert abs(r["lambda_g_mm"] - lam0 / math.sqrt(r["eps_eff"])) < 0.05
    assert r["lambda_0_mm"] > r["lambda_g_mm"] > lam0 / math.sqrt(3.66)


# ─── CPW ─────────────────────────────────────────────────────────────────────

def test_cpw_synthesis_roundtrip_and_monotonic():
    out = run_calculator("cpw_synthesis",
                         {"z0_ohm": 50, "gap_mm": 0.2, "freq_ghz": 2.4,
                          "epsilon_r": 3.66, "h_mm": 0.508})
    assert out["ok"]
    r = out["result"]
    assert abs(r["z0_actual_ohm"] - 50.0) < 0.5
    back = run_calculator("cpw_analysis",
                          {"w_mm": r["w_mm"], "gap_mm": 0.2, "freq_ghz": 2.4,
                           "epsilon_r": 3.66, "h_mm": 0.508})
    assert abs(back["result"]["z0_ohm"] - 50.0) < 0.5
    narrow = run_calculator("cpw_analysis",
                            {"w_mm": r["w_mm"] / 3, "gap_mm": 0.2,
                             "freq_ghz": 2.4, "epsilon_r": 3.66,
                             "h_mm": 0.508})["result"]
    assert narrow["z0_ohm"] > 50.0  # 窄中心带 → 高阻


def test_cpw_synthesis_out_of_range_is_explicit_error():
    out = run_calculator("cpw_synthesis",
                         {"z0_ohm": 1.0, "gap_mm": 0.2, "freq_ghz": 2.4,
                          "epsilon_r": 3.66, "h_mm": 0.508})
    assert not out["ok"] and "超出可达范围" in out["error"]


# ─── CPWG（底接地共面波导）────────────────────────────────────────────────────

def test_cpwg_thick_substrate_limit_matches_half_sum():
    """h→∞ 退化为无地 CPW 无限厚基板：εeff → (1+εr)/2（闭式自洽极限）。"""
    out = run_calculator("cpwg_analysis",
                         {"w_mm": 1.0, "gap_mm": 0.2, "epsilon_r": 3.66,
                          "h_mm": 100.0})["result"]
    assert out["eps_eff"] == pytest.approx((1 + 3.66) / 2, rel=0.005)


def test_cpwg_measured_anchors_from_cpw_smoke():
    """#193 冒烟实测双锚：εeff=3.084（β 实测）与 |S11|=−6.5dB
    （=18.2Ω 失配线理论值）——参照系错位定案的数值证据。"""
    out = run_calculator("cpwg_analysis",
                         {"w_mm": 4.035, "gap_mm": 0.2, "epsilon_r": 3.66,
                          "h_mm": 0.508})["result"]
    assert out["eps_eff"] == pytest.approx(3.084, rel=0.025)
    assert 15.0 < out["z0_ohm"] < 22.0


def test_cpwg_synthesis_roundtrip_and_monotonic():
    out = run_calculator("cpwg_synthesis",
                         {"z0_ohm": 50, "gap_mm": 0.2, "freq_ghz": 2.5,
                          "epsilon_r": 3.66, "h_mm": 0.508})
    assert out["ok"]
    r = out["result"]
    assert abs(r["z0_actual_ohm"] - 50.0) < 0.5
    assert r["w_mm"] == pytest.approx(0.849, abs=0.05)
    back = run_calculator("cpwg_analysis",
                          {"w_mm": r["w_mm"], "gap_mm": 0.2,
                           "epsilon_r": 3.66, "h_mm": 0.508})["result"]
    assert abs(back["z0_ohm"] - 50.0) < 0.5
    wide = run_calculator("cpwg_analysis",
                          {"w_mm": r["w_mm"] * 3, "gap_mm": 0.2,
                           "epsilon_r": 3.66, "h_mm": 0.508})["result"]
    assert wide["z0_ohm"] < 50.0  # 宽中心带 → 低阻


def test_cpwg_eps_eff_between_limits():
    """薄基板场压进介质：εeff 单调趋向 εr（h 小 → 大）。"""
    thin = run_calculator("cpwg_analysis",
                          {"w_mm": 1.0, "gap_mm": 0.2, "epsilon_r": 3.66,
                           "h_mm": 0.1})["result"]["eps_eff"]
    thick = run_calculator("cpwg_analysis",
                           {"w_mm": 1.0, "gap_mm": 0.2, "epsilon_r": 3.66,
                            "h_mm": 2.0})["result"]["eps_eff"]
    assert thin > thick > 1.0 and thin < 3.66


# ─── 带状线 ──────────────────────────────────────────────────────────────────

def test_stripline_analysis_anchor_w_over_b_eq_1():
    r = run_calculator("stripline_analysis",
                       {"w_mm": 1.0, "b_mm": 1.0, "epsilon_r": 1.0})["result"]
    assert r["z0_ohm"] == pytest.approx(65.4, abs=1.0)


def test_stripline_monotonic_and_eps_eff_is_er():
    z_narrow = run_calculator("stripline_analysis",
                              {"w_mm": 0.2, "b_mm": 1.0,
                               "epsilon_r": 2.2})["result"]["z0_ohm"]
    z_mid = run_calculator("stripline_analysis",
                           {"w_mm": 1.0, "b_mm": 1.0,
                            "epsilon_r": 2.2})["result"]["z0_ohm"]
    z_wide = run_calculator("stripline_analysis",
                            {"w_mm": 2.0, "b_mm": 1.0,
                             "epsilon_r": 2.2})["result"]["z0_ohm"]
    assert z_narrow > z_mid > z_wide
    r = run_calculator("stripline_analysis",
                       {"w_mm": 1.0, "b_mm": 1.0, "epsilon_r": 2.2,
                        "freq_ghz": 2.4})["result"]
    assert r["eps_eff"] == 2.2  # 全嵌介质对称结构
    assert r["lambda_g_mm"] == pytest.approx(
        299.792458 / (2.4 * math.sqrt(2.2)), abs=0.01)


def test_stripline_synthesis_roundtrip():
    out = run_calculator("stripline_synthesis",
                         {"z0_ohm": 50, "b_mm": 1.578, "epsilon_r": 2.2})
    assert out["ok"]
    assert abs(out["result"]["z0_actual_ohm"] - 50.0) < 0.05
    assert 0 < out["result"]["w_mm"] < 3.156


# ─── 审查 R1-1/R1-3 回归钉（runs/review_ge8e/r1_calculators/REPORT.md）───────

def test_stripline_z0_wide_band_no_tanh_cliff():
    """R1-1：w/b≳12.1 后旧 ellipk 形态 tanh 双精度饱和 → 1−k² 下溢、
    ellipk(1)=inf → Z0 静默返 0；AGM 形态（#333 _kk_ratio_tanh 先例）
    须全程有限且与 K(k)≈ln(4/k') 独立渐近一致（悬崖域 k'≲1.5e-8，
    渐近修正在机器精度级）。"""
    from rfauto.core.calc_families.rf_line import _stripline_z0

    for w_over_b in (12.0, 12.135, 13.0, 15.0, 20.0):
        z0 = _stripline_z0(w_over_b, 1.0, 1.0)
        assert math.isfinite(z0) and z0 > 0.0
        x = math.pi * w_over_b / 2.0
        kp = 1.0 / math.cosh(x)
        z0_asym = 30.0 * math.pi * (math.pi / 2.0) / math.log(4.0 / kp)
        assert abs(z0 - z0_asym) / z0_asym < 1e-9


def test_stripline_synthesis_5ohm_wide_band_roundtrip():
    """R1-1 回代自洽：5Ω（b=1mm、εr=1）解 w/b≈18.4 落在旧悬崖域内，
    综合回代 |Z0(w)−5|/5 < 1e-6（旧实现此处返 0 静默失配）。"""
    out = run_calculator("stripline_synthesis",
                         {"z0_ohm": 5.0, "b_mm": 1.0, "epsilon_r": 1.0})
    assert out["ok"]
    from rfauto.core.calc_families.rf_line import _stripline_z0

    z_back = _stripline_z0(out["result"]["w_mm"], 1.0, 1.0)
    assert abs(z_back - 5.0) / 5.0 < 1e-6


def test_cpw_analysis_rejects_epsilon_r_le_1():
    """R1-3：cpw_analysis(εr≤1) 旧径静默返 nan（skrf 色散修正 √(εr−1)
    除零），现入口显式拒绝（service 面 ok=False+error 带参数名与原因）。"""
    out = run_calculator("cpw_analysis",
                         {"w_mm": 0.5, "gap_mm": 0.2, "freq_ghz": 10.0,
                          "epsilon_r": 1.0, "h_mm": 0.254})
    assert not out["ok"] and "epsilon_r" in out["error"]


def test_microstrip_analysis_rejects_nonpositive_h():
    """R1-3：microstrip_analysis(h≤0) 旧径抛 ZeroDivisionError/math domain
    error（无名异常），现入口显式拒绝带参数名。"""
    for bad_h in (0.0, -0.2):
        out = run_calculator("microstrip_analysis",
                             {"width_mm": 0.5, "freq_ghz": 10.0,
                              "epsilon_r": 4.4, "h_mm": bad_h})
        assert not out["ok"] and "h_mm" in out["error"]


def test_stripline_analysis_rejects_zero_w():
    """R1-3：stripline_analysis(w=0) 旧径静默返 z0=inf，现入口显式拒绝。"""
    out = run_calculator("stripline_analysis",
                         {"w_mm": 0.0, "b_mm": 1.0, "epsilon_r": 2.2})
    assert not out["ok"] and "w_mm" in out["error"]


def test_line_analysis_guards_raise_valueerror_core_face():
    """R1-3 内核面：三处入口守卫在函数直调层抛 ValueError（带参数名）。"""
    from rfauto.core.calc_families import rf_line

    with pytest.raises(ValueError, match="epsilon_r"):
        rf_line.cpw_analysis(w_mm=0.5, gap_mm=0.2, freq_ghz=10.0,
                             epsilon_r=1.0, h_mm=0.254)
    with pytest.raises(ValueError, match="h_mm"):
        rf_line.microstrip_analysis(width_mm=0.5, freq_ghz=10.0,
                                    epsilon_r=4.4, h_mm=-0.2)
    with pytest.raises(ValueError, match="w_mm"):
        rf_line.stripline_analysis(w_mm=0.0, b_mm=1.0, epsilon_r=2.2)


def test_line_synthesis_guards_raise_valueerror_core_face():
    """ge8e P3 小件批 A-13/A-14/A-15：综合入口域盒守卫直调层 ValueError
    带参数回显（旧径非法入参直入 skrf+brentq 裸报 'The function value
    is NaN'——scipy 文本无参数名不可诊断；microstrip_analysis εr<1
    旧径实测 er=0.5 静默返非物理 eps_eff=0.6483）。"""
    from rfauto.core.calc_families import rf_line

    with pytest.raises(ValueError, match=r"h_mm=-1.0"):
        rf_line.microstrip_synthesis(z0_ohm=50.0, freq_ghz=2.5,
                                     epsilon_r=3.66, h_mm=-1.0)
    with pytest.raises(ValueError, match=r"epsilon_r=0.5"):
        rf_line.microstrip_synthesis(z0_ohm=50.0, freq_ghz=2.5,
                                     epsilon_r=0.5, h_mm=0.508)
    with pytest.raises(ValueError, match=r"z0_ohm=-50.0"):
        rf_line.microstrip_synthesis(z0_ohm=-50.0, freq_ghz=2.5,
                                     epsilon_r=3.66, h_mm=0.508)
    with pytest.raises(ValueError, match=r"h_mm=-1.0"):
        rf_line.cpw_synthesis(z0_ohm=50.0, gap_mm=0.2, freq_ghz=2.5,
                              epsilon_r=3.66, h_mm=-1.0)
    with pytest.raises(ValueError, match=r"epsilon_r=0.5"):
        rf_line.cpw_synthesis(z0_ohm=50.0, gap_mm=0.2, freq_ghz=2.5,
                              epsilon_r=0.5, h_mm=0.508)
    with pytest.raises(ValueError, match=r"epsilon_r=0.5"):
        rf_line.microstrip_analysis(width_mm=1.113, freq_ghz=2.5,
                                    epsilon_r=0.5, h_mm=0.508)


def test_stripline_synthesis_roundtrip_insurance_raise(monkeypatch):
    """A-18（siw_synthesis 同款形态）：回代自洽保险带——brentq 返偏根时
    回代不复得目标 Z0 → 显式 ValueError 不静默透传不自洂数值（monkeypatch
    注入坏 brentq，正问题 _stripline_z0 不动）。"""
    import scipy.optimize as sopt

    from rfauto.core.calc_families import rf_line

    real_brentq = sopt.brentq

    def wrong_root(f, a, b, **kw):
        return real_brentq(f, a, b, **kw) * 0.5  # 偏根：回代 Z0(w/2)≠目标

    monkeypatch.setattr(sopt, "brentq", wrong_root)
    with pytest.raises(ValueError, match="回代自洽失败"):
        rf_line.stripline_synthesis(z0_ohm=50.0, b_mm=1.016, epsilon_r=3.66)


def test_stripline_synthesis_roundtrip_covers_high_impedance():
    """A-18 容差带：工作域高端 z0=120Ω（er=3.66 下可达上限 ~159Ω——更高端
    被既有括号扫描 objective-vs-z0 误拒面挡住，登记 followUp 不属本批）
    保险带不误伤；直接 brentq 面实测最差档（z0=300）回代 rel 残差
    ~1.3e-6 ≪ 1e-4 保险带。"""
    out = run_calculator("stripline_synthesis",
                         {"z0_ohm": 120.0, "b_mm": 1.016, "epsilon_r": 3.66})
    assert out["ok"], out
    assert abs(out["result"]["z0_actual_ohm"] - 120.0) / 120.0 <= 1e-4


# ─── λ/4 变换 ────────────────────────────────────────────────────────────────

def test_quarter_wave_transformer():
    r = run_calculator("quarter_wave_transformer",
                       {"z_source_ohm": 25, "z_load_ohm": 50})["result"]
    assert r["z0_section_ohm"] == pytest.approx(math.sqrt(25 * 50), abs=1e-3)
    r2 = run_calculator("quarter_wave_transformer",
                        {"z_source_ohm": 25, "z_load_ohm": 50,
                         "freq_ghz": 2.4, "eps_eff": 2.2})["result"]
    assert r2["length_mm"] == pytest.approx(
        299.792458 / (4 * 2.4 * math.sqrt(2.2)), abs=0.01)


# ─── 衰减器（ABCD 级联独立校验，非同源公式回代）──────────────────────────────

def _abcd_pi(zs: float, z1: float):
    """π 型拓扑 = 并(Z1)-串(Zs)-并(Z1)，级联序 M_shunt·M_series·M_shunt。"""
    y = 1.0 / z1
    return ((1 + zs * y, zs), (y * (2 + zs * y), 1 + zs * y))


def _abcd_t(zs: float, zb: float):
    """T 型拓扑 = 串(Zs)-并(Zb)-串(Zs)，级联序 M_series·M_shunt·M_series。"""
    y = 1.0 / zb
    return ((1 + zs * y, zs * (2 + zs * y)), (y, 1 + zs * y))


def test_attenuator_classic_3db_values():
    """经典 3dB/50Ω 查表值（推导后与 RF 手册核对）。"""
    r = run_calculator("attenuator_pi",
                       {"attenuation_db": 3, "z0_ohm": 50})["result"]
    assert r["r_series_mid_ohm"] == pytest.approx(17.612, abs=0.01)
    assert r["r_shunt_end_ohm"] == pytest.approx(292.48, abs=0.1)
    r = run_calculator("attenuator_t",
                       {"attenuation_db": 3, "z0_ohm": 50})["result"]
    assert r["r_series_arm_ohm"] == pytest.approx(8.550, abs=0.01)
    assert r["r_shunt_mid_ohm"] == pytest.approx(141.93, abs=0.1)


@pytest.mark.parametrize("kind,abcd_fn", [("pi", _abcd_pi), ("t", _abcd_t)])
def test_attenuator_network_check(kind: str, abcd_fn) -> None:
    atten_db, z0 = 3.0, 50.0
    r = run_calculator(f"attenuator_{kind}",
                       {"attenuation_db": atten_db, "z0_ohm": z0})["result"]
    if kind == "pi":
        zs, zsh = r["r_series_mid_ohm"], r["r_shunt_end_ohm"]
    else:
        zs, zsh = r["r_series_arm_ohm"], r["r_shunt_mid_ohm"]
    (a, b), (c, d) = abcd_fn(zs, zsh)
    zin = (a * z0 + b) / (c * z0 + d)
    # 电阻值展示舍入到 3 位小数 → Zin 容差放宽到 0.05Ω（#175 舍入兼容）
    assert zin == pytest.approx(z0, abs=0.05)
    s21 = 2 / (a + b / z0 + c * z0 + d)
    assert abs(s21) ** 2 == pytest.approx(10 ** (-atten_db / 10), rel=1e-3)


def test_attenuator_nonpositive_attenuation_rejected():
    for kind in ("pi", "t", "bridged_t"):
        out = run_calculator(f"attenuator_{kind}",
                             {"attenuation_db": 0, "z0_ohm": 50})
        assert not out["ok"]


# ─── 桥 T 型（F8 首族变体锚；#118：闭式先经独立数值裁判再采信）────────────────

def _bridged_t_sparams(r_arm: float, r_shunt: float, r_bridge: float,
                       z0: float) -> tuple[complex, complex]:
    """三节点导纳 Kron 消元 → 2 端口 S（独立于闭式推导的裁判）。

    in(1)—r_arm—mid(3)—r_arm—out(2)，mid—r_shunt—gnd，in—r_bridge—out。
    """
    import numpy as np

    y = np.zeros((3, 3))
    y[0, 0] = y[1, 1] = 1 / r_arm + 1 / r_bridge
    y[2, 2] = 2 / r_arm + 1 / r_shunt
    y[0, 1] = y[1, 0] = -1 / r_bridge
    y[0, 2] = y[2, 0] = y[1, 2] = y[2, 1] = -1 / r_arm
    y2 = y[:2, :2] - y[:2, 2:] @ np.linalg.inv(y[2:, 2:]) @ y[2:, :2]
    eye = np.eye(2)
    s = (eye - z0 * y2) @ np.linalg.inv(eye + z0 * y2)
    return complex(s[0, 0]), complex(s[1, 0])


def test_attenuator_bridged_t_classic_3db_values():
    """经典 3dB/50Ω：桥 Z0(N−1)=20.627Ω、并 Z0/(N−1)=121.201Ω、串臂固定 50Ω。"""
    r = run_calculator("attenuator_bridged_t",
                       {"attenuation_db": 3, "z0_ohm": 50})["result"]
    assert r["r_series_arm_ohm"] == pytest.approx(50.0, abs=1e-9)
    assert r["r_bridge_ohm"] == pytest.approx(20.627, abs=0.001)
    assert r["r_shunt_mid_ohm"] == pytest.approx(121.201, abs=0.001)


@pytest.mark.parametrize("atten_db", [1.0, 3.0, 6.0, 10.0, 20.0, 40.0])
def test_attenuator_bridged_t_network_check(atten_db: float) -> None:
    """节点导纳级联自检：S11=0（匹配）且 |S21|=1/N（衰减量），全档位。"""
    z0 = 50.0
    r = run_calculator("attenuator_bridged_t",
                       {"attenuation_db": atten_db, "z0_ohm": z0})["result"]
    s11, s21 = _bridged_t_sparams(r["r_series_arm_ohm"], r["r_shunt_mid_ohm"],
                                  r["r_bridge_ohm"], z0)
    # 电阻值展示舍入 3 位小数 → S11 容差 1e-4（#175 舍入兼容）
    assert abs(s11) < 1e-4
    assert abs(s21) == pytest.approx(10 ** (-atten_db / 20), rel=1e-4)


def test_attenuator_bridged_t_limits_consistent():
    """极限自洽：A→0 桥→0/并→∞（直通）；A 增大桥单调升、并单调降。"""
    tiny = run_calculator("attenuator_bridged_t",
                          {"attenuation_db": 1e-3, "z0_ohm": 50})["result"]
    assert tiny["r_bridge_ohm"] < 0.01
    assert tiny["r_shunt_mid_ohm"] > 1e5
    prev_b, prev_s = 0.0, float("inf")
    for a in (1.0, 3.0, 10.0, 30.0):
        r = run_calculator("attenuator_bridged_t",
                           {"attenuation_db": a, "z0_ohm": 50})["result"]
        assert r["r_bridge_ohm"] > prev_b and r["r_shunt_mid_ohm"] < prev_s
        prev_b, prev_s = r["r_bridge_ohm"], r["r_shunt_mid_ohm"]


# ─── 驻波换算 ────────────────────────────────────────────────────────────────

def test_vswr_convert_from_vswr():
    r = run_calculator("vswr_convert", {"vswr": 2.0})["result"]
    assert r["gamma_mag"] == pytest.approx(1 / 3, abs=1e-6)  # 展示舍入 6 位
    assert r["return_loss_db"] == pytest.approx(9.5424, abs=1e-3)
    assert r["mismatch_loss_db"] == pytest.approx(0.5115, abs=1e-3)


def test_vswr_convert_roundtrip_and_errors():
    r = run_calculator("vswr_convert", {"return_loss_db": 20.0})["result"]
    back = run_calculator("vswr_convert", {"gamma_mag": r["gamma_mag"]})["result"]
    assert back["return_loss_db"] == pytest.approx(20.0, abs=1e-4)
    assert run_calculator("vswr_convert", {"vswr": 1.0})["ok"] is False
    assert run_calculator("vswr_convert", {"return_loss_db": -3})["ok"] is False
    assert run_calculator("vswr_convert", {"gamma_mag": 1.5})["ok"] is False
    assert run_calculator("vswr_convert", {})["ok"] is False


# ─── 贴片谐振（与 synthesize_patch 跨模块一致性）─────────────────────────────

def test_patch_length_matches_synthesize_patch():
    from rfauto.core.synthesis import synthesize_patch

    r = run_calculator("patch_length",
                       {"f0_ghz": 2.4, "epsilon_r": 3.66,
                        "h_mm": 0.508})["result"]
    ref = synthesize_patch(f0_ghz=2.4, er=3.66, h_mm=0.508)
    assert round(r["patch_w_mm"], 2) == ref.params["patch_w_mm"]
    assert round(r["patch_l_mm"], 2) == ref.params["patch_len_mm"]
    assert 1.0 < r["eps_eff"] < 3.66


# ─── service 层 JSON 契约 ────────────────────────────────────────────────────

def test_service_unknown_and_missing_param_explicit_error():
    out = run_calculator("no_such", {})
    assert not out["ok"] and "未注册" in out["error"]
    assert "microstrip_analysis" in out["error"]  # 报错列出可用名
    out = run_calculator("microstrip_analysis", {"width_mm": 1.0})
    assert not out["ok"] and "缺少必需参数" in out["error"]


def test_service_extra_param_typeerror_and_json_serializable():
    out = run_calculator("vswr_convert", {"vswr": 2.0, "bogus_k": 1})
    assert not out["ok"] and "参数不匹配" in out["error"]
    import json
    json.dumps(run_calculator("vswr_convert", {"vswr": 2.0}),
               ensure_ascii=False)  # Infinity 不允许出现在 JSON 里


# ─── B3 腔体微扰频移（Pozar §6.7 口径锚）─────────────────────────────────────

_CAV = {"a_mm": 30.0, "b_mm": 10.0, "d_mm": 40.0}  # TE101 f0≈6.246 GHz


def _emax_box(half_mm: float) -> list:
    c = [_CAV["a_mm"] / 2, _CAV["b_mm"] / 2, _CAV["d_mm"] / 2]
    return [c[0] - half_mm, c[1] - half_mm, c[2] - half_mm,
            c[0] + half_mm, c[1] + half_mm, c[2] + half_mm]


def test_cavity_perturbation_te101_f0_closed_form():
    r = run_calculator("cavity_perturbation_shift",
                       {**_CAV, "sample_box_mm": _emax_box(0.5),
                        "sample_eps_r": 2.1})["result"]
    # f0 = (c/2)·sqrt(1/a²+1/d²)，a=30/d=40mm → 6.2457 GHz（独立闭式）
    assert r["f0_ghz"] == pytest.approx(149.896229 * math.sqrt(
        1 / 30.0 ** 2 + 1 / 40.0 ** 2), rel=1e-9)
    assert r["cavity_volume_mm3"] == pytest.approx(30 * 10 * 40, rel=1e-12)


def test_cavity_perturbation_small_sample_limits_pozar():
    """小样品极限（Pozar §6.7 标准式，几何 Vc 表述）：
    介质 E 极大点 → −2(εr−1)·Vs/Vc；金属 E 极大点 → −2Vs/Vc。"""
    eps_r, vs = 2.1, 0.1 ** 3  # 0.2mm 盒
    r = run_calculator("cavity_perturbation_shift",
                       {**_CAV, "sample_box_mm": _emax_box(0.05),
                        "sample_eps_r": eps_r})["result"]
    limit = -2.0 * (eps_r - 1.0) * vs / (30 * 10 * 40)
    assert r["df_over_f"] == pytest.approx(limit, rel=5e-5)
    m = run_calculator("cavity_perturbation_shift",
                       {**_CAV, "sample_box_mm": _emax_box(0.05)})["result"]
    assert m["df_over_f"] == pytest.approx(-2.0 * vs / (30 * 10 * 40), rel=5e-4)
    assert m["perturbation"] == "metal"


def test_cavity_perturbation_h_max_sign_flips_positive():
    """Slater 形状微扰：金属样品置 H 极大区（E≈0）→ 频移符号翻正。"""
    lo = [_CAV["a_mm"] / 2 - 0.5, _CAV["b_mm"] / 2 - 0.5, 0.0]
    hi = [_CAV["a_mm"] / 2 + 0.5, _CAV["b_mm"] / 2 + 0.5, 1.0]
    r = run_calculator("cavity_perturbation_shift",
                       {**_CAV, "sample_box_mm": lo + hi})["result"]
    assert r["df_over_f"] > 0  # H 区上抬（调谐螺钉口径）


def test_cavity_perturbation_box_analytic_exact_vs_independent_integral():
    """有限盒解析积分的独立裁判：数值积分（scipy dblquad 独立路径）对照。"""
    from scipy.integrate import dblquad

    lo, hi = [13.0, 4.0, 18.0], [17.0, 6.0, 22.0]
    r = run_calculator("cavity_perturbation_shift",
                       {**_CAV, "sample_box_mm": lo + hi,
                        "sample_eps_r": 2.1})["result"]
    a, b, d = _CAV["a_mm"], _CAV["b_mm"], _CAV["d_mm"]
    # 独立数值积分 ∫∫ sin²(πx/a)sin²(πz/d) dz dx × y 长度（scipy 自适应）
    val, _ = dblquad(
        lambda z, x: math.sin(math.pi * x / a) ** 2
        * math.sin(math.pi * z / d) ** 2,
        lo[0], hi[0], lambda x: lo[2], lambda x: hi[2])
    i_e = val * (hi[1] - lo[1])
    expect = -(2.1 - 1) / 2 * i_e / (a * b * d / 4.0)
    assert r["df_over_f"] == pytest.approx(expect, rel=1e-10)
    assert r["route"] == "analytic_box"
