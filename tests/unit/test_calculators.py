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
    # core/slotline（路线 A 裁判面，），越域显式拒绝不外推
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
    # 快赢席 W2 键面收口（2026-10-08，#231 五钉同步）：
    # ① AP-6 ITU 大气/雨衰三键（内核 core/itu_atmosphere.py，系数表 AP-8 批
    # 已录入+Table 5 全量 116 频点对拍；薄壳 calc_families/itu_link.py）——
    # sd_freshness 净表"AP-6 CALC 三键未注册"的键面兑现；R0.01/h0 显式输入
    # （PV-011 数据文件不捆绑，占位 ValueError 语义不变）
    "gaseous_attenuation", "rain_specific_attenuation", "rain_attenuation_r001",
    # ② DR-8 CDR 抖动容限 mask 键（内核 core/cdr_jitter_mask.py，#118 双锚
    # 内证；薄壳 calc_families/cdr_mask.py；池/任务书双 ID round16 DR-8=席6
    # 任务书 DR-9）——"CALC+1 未兑现"的键面兑现
    "cdr_jitter_mask",
    # SB22-MS-1 功率校准补偿链键（MS12 储备池席，2026-10-08，#231 五钉同步）：
    # 内核 core/power_calibration.py（校准因子 Keysight AN 64-1A 定义/
    # 失配界 Keysight AN 1449-3 与 R&S 失配表双源/GUM JCGM 100:2008
    # §4.3.7 矩形 §4.3.9 U 形）；薄壳 calc_families/power_cal.py；锚树
    # tests/unit/test_power_calibration.py（回收钉+SWR1.5×1.25=0.19 dB 文献例）
    "power_cal_chain",
    # SB22-TH-2 TNVNA 扩频两键（TH2 储备池席，2026-10-08，#231 五钉同步）：
    # 内核 core/thz_vna.py（一端口三项误差模型闭式反演+一阶灵敏度 RSS 预算
    # NIST MUF 口径/两带重叠线性权重拼接器；Hesler ISSTT 2010 按带标定语义，
    # WR 带缘双源=core/rw_tables 2src-thz 行）；薄壳 calc_families/thz_vna.py；
    # 锚树 tests/unit/test_th2_tnvna_calculator_keys.py（恒等/回收/有限差分
    # 灵敏度互证+WR-10/WR-8 重叠文献例）
    "tnvna_extender_error_model", "tnvna_band_stitch",
    # aurora36 W3-A 确定性内核新域批 1 两键（2026-10-11，#231 五钉同步）：
    # ① 不等分 Wilkinson 综合（R2 空白域 G6）：Pozar 4ed §7.3 K²=P3/P2
    # 口径臂/隔离电阻/变换段闭式（原始设计 Parad–Moynihan 1965；文献锚
    # 2:1→51.5/103/106.07Ω @50Ω）；薄壳 calc_families/wilkinson_unequal.py；
    # ② Bethe 孔定向耦合器（R2 空白域 G5）：宽壁中心圆孔 Bethe 极化率
    # （单源消费 core/aperture_coupling）+E/M 支路 Z10 加减结构（f=c0/(√2a)
    # 隔离向相消=方向性极值）+Cohn 壁厚修正（圆波导截止常数 1.706d/1.305d
    # 口径）；双向单键（给孔径=分析/给目标耦合度=综合）；薄壳
    # calc_families/bethe_hole.py。共同锚树 tests/unit/test_w3a_unsplit_
    # bethe.py（K=1 等分退化+Parad–Moynihan 锚+节点导纳分析独立裁判/
    # X 波段 20~30dB 量级锚+d³ 律+设计频率方向性极大+守卫）
    "unequal_split_wilkinson", "bethe_hole_coupler",
    # aurora36 W4-A 确定性内核新域批 2 六键（2026-10-11，#231 五钉同步）：
    # ① 数字调制 BER/Eb-N0 族（R2 空白域 G3）：Q 函数单源 0.5·erfc(x/√2)
    # （_qfunc 全族唯一实现），BPSK/QPSK 闭式 Q(√(2γb))（同比特能量口径
    # QPSK≡BPSK 物理恒等）+square-QAM Gray 精确和式（Proakis 5ed/Cho&Kim
    # 2005）；曲线/反解（dB 域二分，双精度下限 1e-15）/编码一阶粗估三键；
    # ② 雷达方程与检测统计族（R2 空白域 G1）：基本雷达方程 SI 线性/dB 混
    # 合双口径互斥（Pr=Pt·G²λ²σ/((4π)³R⁴L)，Skolnik 3ed/Richards FRSP）
    # +Albersheim 三量互算（原式 √(N+0.44) 口径——√(N+1) 简化形与
    # Marcum 精确解差 0.8dB 不采用；Pfa=1e-6/Pd=0.9 锚 Δ=0.069dB≤0.1dB）
    # +CA-CFAR 门限因子闭式（Pfa=(1+β)^(−N)→α=N(Pfa^(−1/N)−1)+SW1-Pd 闭
    # 式，Richards FRSP ch.6）；薄壳 calc_families/modulation_ber.py 与
    # radar_eq.py（物理自含，同 W3-A 形态）。共同锚树 tests/unit/
    # test_w4a_mod_radar.py（Q 函数 scipy 互证+BPSK@10dB=3.872e-6 文献锚
    # +反解文献表锚+16QAM 蒙特卡洛独立裁判+Marcum-Q 精确反解互证+雷达
    # 方程 R 加倍 −12.0412dB 物理恒等+SI/dB 双口径一致+CFAR 蒙特卡洛裁
    # 判+守卫）
    "modulation_ber_curve", "required_ebn0", "coded_ber_estimate",
    "radar_range_equation", "albersheim_detection_snr", "ca_cfar_threshold",
    # aurora36 W5-A 确定性内核新域批 3 六键（2026-10-11，#231 五钉同步）：
    # ① DOA 子空间谱估计+自适应波束形成（R2 空白域 G2）：MUSIC 伪谱
    # （Schmidt 1986，噪声子空间 1/‖E_nᴴa‖²+黄金分割峰位精化）/TLS-ESPRIT
    # （Roy & Kailath 1989 §III-C 堆叠 SᴴS 分块 Φ=−V₁₂V₂₂⁻¹）/MVDR 权重
    # （Capon 1969，w=R⁻¹a/(aᴴR⁻¹a)，aᴴw=1 构造恒等）；ULA 侧射角约定，
    # 合成路径（angles+SNR+快拍+seed，PCG64 确定性；null=理想协方差）与
    # 显式协方差路径恰给其一，厄米化守卫+奇异协方差显式拒绝；
    # ② combline/同轴腔谐振器物理实现（R2 空白域 G20 尺寸级第一步）：
    # combline 双向（短路线 ω₀CZr·tanθ₀=1，C→0 极限=λ/4 短路线自谐振，
    # Matthaei-Young-Jones ch.8）/同轴腔 TEM 双向（λ/2·λ/4，Z0=60/√εr·
    # ln(b/a)+TE11 截止单模域，Pozar §6.6）/无载 Q 串联合成（趋肤电阻
    # 口径 Qc=ωμ·ln(b/a)/(Rs(1/a+1/b))+Qd=1/tanδ，1/Qu=1/Qc+1/Qd）；
    # 薄壳物理自含 calc_families/doa.py 与 combline_resonator.py（同
    # W3-A/W4-A 形态）。共同锚树 tests/unit/test_w5a_doa_combline.py
    # （理想协方差双源回收 <0.01°/单源 MUSIC=ESPRIT=真值/seed 逐位复现/
    # aᴴw=1 恒等/干扰零陷 <−60dB/R=I 常规波束退化恒等/双向 roundtrip
    # ≤1e-12/C→0 λ/4 极限/Qu 单调性+√σ·√f 定标/守卫）
    "doa_music_spectrum", "doa_esprit", "doa_mvdr_weights",
    "combline_resonance", "coaxial_cavity_resonance", "cavity_unloaded_q",
    # aurora36 W6-A 确定性内核新域批 4 五键（2026-10-11，#231 五钉同步）：
    # ① TRL 校准件设计面（R2 空白域 G7——trl_solt 只做提取/应用，设计端
    # 补口）：线标准 λg/4@带心（Engen-Hoer 1979/NIST TN 1341 规则面）+
    # 直通（0=flush/短直通）+反射标准（短/开 × ideal/λg/4 偏置，|Γ|≡1）
    # +经典窗双判据（带缘电长度 [20°,160°] 推荐窗+单线频带比
    # f2/f1∈[1.2,3]）；波导路 wr_name 走 rw_tables 单源/TEM 路显式
    # z0/εeff 恰其一；② EMC 抗扰度（R2 空白域 G4——抗扰半边，与发射
    # 面 emc_radiated 语义分离）：61000-4-3 场强/功率远场换算
    # （P=(E·R)²/(30G)，E=√(30EIRP)/R 同 exposure_limits 源；3m/10m+
    # 可选 AF 恒等面）/61000-4-6 CDN 耦合 emf↔功率（0dBm≡106.9897
    # dBµV 匹配端电压=惯称 107 口径、emf +6.0206dB；Level1-3=1/3/10 V
    # emf；80%AM +5.105dB 双列）/61000-4-2 接触放电双指数波形
    # （I=I0(e^{-t/τ1}−e^{-t/τ2})，峰值+I(30)/I(60)=2:1+rise 三条件定
    # 参，波形表单源消费 core/emc_tvs_gate，∫I dt=I0(τ1−τ2) 恒等回收）；
    # 薄壳物理自含 calc_families/trl_standards.py 与 emc_immunity.py
    # （同 W3-A..W5-A 形态）。共同锚树 tests/unit/test_w6a_trl_emc.py
    # （WR-90@10GHz λg/4=9.927mm 自洽回收/TEM 比值 8 恰触 20°-160° 窗
    # 界/X 波段单线窗内/扫描闭式逆互证/E↔P 双向残差/107 dBµV 恒等/
    # 面积恒等 <1e-6/8kV=2×4kV 逐点线性/守卫）
    "trl_standards_design", "trl_line_electric_scan",
    "radiated_immunity_power", "conducted_immunity_cdn",
    "esd_contact_waveform",
    # aurora36 W7-A 确定性内核新域批 5 六键（2026-10-11，#231 五钉同步）：
    # ① PA 平衡对+Doherty 合成网络（R2 空白域 G11——pa_architectures
    # 只有负载调制/Chireix 效率闭式，合成网络与平衡对=零）：平衡放大器
    # 对 S 参数合成（90° 杂交 Kurokawa 口径：S11,bal=(S11a−S11b)/2 同管
    # 逐位 0 反射对消+增益=单管+单管失效容忍 6.02dB+相位容差
    # Δφ_max=2asin(10^(−RL/20)/Γ)）/Doherty 合路 λ/4 网络（R_L=R_opt/2、
    # Z_T=R_opt、Z_BO=Z_T²/R_L=2R_opt，Cripps ARMMS 2008"Z0=2R、
    # R=Ropt/2"写死；合并点回退 10·log10(4)=6.0206dB、功分比 50/50、
    # peak 偏置线 90°@f0 惯例口径如实标注；quarter_wave_invert 单源
    # ABCD 回代自洽）/效率-回退曲线（单源消费 core/pa_architectures
    # 两区域闭式：η(σ=1)=η(σ=1/2)=π/4 双拐点逐位+中段凹陷 2π/9@σ=2/3
    # 严格 B 类口径如实报告——"全平平台"是理想化上界不采用；η≥单管
    # B 类逐点判读）；② 量子比特读出链（R2 空白域 G18——quantum_cryo
    # 登记级声明升格数值面）：色散位移 χ=g²Δ/((κ/2)²+Δ²)（Blais 2004
    # 一阶闭式+有限线宽；远失谐退化 g²/Δ；强色散判据 |2χ|≥κ+n_crit+
    # Purcell (g/Δ)²κ）/读出谐振器 S21 双态（notch 型单源：
    # S21=1−κe/(κ/2+j(δ∓χ))，临界耦合 κe=κ/2 态谐振点逐位 0 深谷
    # 归一；χ=0 双态曲线逐点相同连续性）/读出 SNR（IQ 平面分离
    # d_IQ·√(κe·n̄·τ/n_sys)，n_sys=k_B·T_n/(h·f_r) 量子极限缺省；
    # SNR∝√τ 恒等回收 τ×4→×2+Γ_m=8χ²n̄/κ 参考面，Goppl 2008/Blais
    # RMP 2021 口径写死）。薄壳物理自含 calc_families/pa_arch.py 与
    # qubit_readout.py（同 W3-A..W6-A 形态）。共同锚树
    # tests/unit/test_w7a_pa_qubit.py（同管 S11 逐位 0/失效 6.02dB/
    # 相位容差 60° 边界逐位/R_opt=100→50/100/200 阻抗集+测试侧独立
    # ABCD 级联三方互证/双拐点 π/4 逐位+凹陷 2π/9 独立求导锚/χ 远失谐
    # g²/Δ+奇对称+Δ→0 连续/临界耦合深谷逐位 0/χ=0 双态逐点相同/
    # τ×4→SNR×2/量子极限 n_sys=1/T_n×4→SNR÷2/守卫）
    "balanced_pair_sparams", "doherty_combining_network",
    "doherty_efficiency_curve", "qubit_dispersive_shift",
    "qubit_readout_s21", "qubit_readout_snr",
    # aurora72 A2-C 确定性内核第二梯队批 1 六键（2026-10-11，#231 五钉
    # 同步；R7_core_tier2 Top12 排名 1/2 两域，各一新股文件 2-3 键）：
    # ① 标准圆同轴传输线通用件族 coax_line.py（T1——R7 三重搜索证据：
    # coaxial 既有面仅 SICL/combline 腔/PCB 带状语境，行波线通用件=零；
    # 与 coaxial_cavity_resonance 的边界=谐振腔长 vs 行波线，与
    # cavity_unloaded_q 的边界=驻波腔 Q vs 每米行波衰减）：特性阻抗双向
    # 解（TEM 精确闭式 Z0=(60/√εr)·ln(b/a)；分析 a,b→Z0+单位长 L'/C'
    # （L'·C'=με 恒等测试钉）+TE11 高阶模截止 f_c=c₀/(π(a+b)√εr)；
    # 综合 z0+恰一尺寸→反解另一半径（b/a=exp(Z0√εr/60) roundtrip 恒
    # 等）；只给 z0=ratio_only 直径比路线）/行波衰减分解（导体
    # αc=Rs(1/a+1/b)/(4πZ0) 趋肤口径 ∝√f∝1/√σ+介质 αd=β·tanδ/2；
    # 线 Q=β/(2α) 与场积分路线互证 β/(2αc)↔ωμ·ln(b/a)/(Rs(1/a+1/b))
    # 解析同解 ≤1e-12，跨键对 cavity_unloaded_q 互证）/峰值功率容量
    # （E(ρ)=V/(ρ·ln(b/a)) 内导体表面最值 → V_max=E_br·a·ln(b/a)、
    # P_max=E_br²a²ln(b/a)√εr/120 恒等式测试侧独立重算；εr×4→P×2；
    # p_op=P_max/4→余量 6.0206dB；最优比 30Ω（b/a=√e 功率最大）/
    # 76.7Ω（lnx=1+1/x 根≈3.5911 损耗最小）双常数锚）。
    # ② 圆柱腔任意模式闭式谱族 waveguide_closed_form.py（T2=G8 最小
    # 拆席——rw_tables=EIA 表/rwg_mmt=模基 GSM/ridged=脊形/cavity.py=
    # 微扰测量/material_characterization=提取，任意模闭式谱=零）：谐振
    # 谱键（TE 用 J_m' 零点 p≥1——p=0 时 E_t≡0 非物理显式拒绝；TM 用
    # J_m 零点 p≥0/TM010 经典例；主模=全谱最低频计算判读（l<2a→TM010、
    # l>2a→TE111 经典口径复现）+TE11 波导截止参考；TE011/TM111 简并
    # 同频逐位；与 material_characterization._sc_empty_f0 同仓双源）/
    # 模式图键（归一化频率 f·2πa√εr/c₀=√(x²+(pπa/L)²) 随长径比曲线
    # 族+主模切换交叉点二分求根，TE111/TM010 交叉 r≈1.0154 测试侧独立
    # 常数式；p≥1 单调降/TM010 平坦单调性钉；与谱键跨键一致性互证）/
    # 任意模式无载 Q 键（导体微扰 Q=ωU/P_c 闭式（TE：J² 分子分母消去
    # 得 D=1−m²/x'² 恒等式形态；TM：I2x=x²J_{m+1}²/2）+同场表达式
    # scipy.quad 数值积分路线互证 <1e-9+Ue/Um≈1 谐振定理自检（测试侧
    # 独立体积分）；TM010 极限 (ηk0a/2Rs)·L/(L+a) 测试侧独立重算；
    # TE011>TE111 高 Q 性质；介质串联合成 1/Qu=1/Qc+1/Qd 同腔 Q 口径）。
    # 薄壳物理自含 calc_families/coax_line.py 与 waveguide_closed_form.py
    # （同 W3-A..W7-A 形态）。共同锚树
    # tests/unit/test_a2c_coax_waveguide.py（b/a=e^{5/6}↔50Ω 恒等/
    # L'C'=με/TE11 截止 23.8620GHz 独立重算/√f√σ 标度逐位/线 Q 跨键
    # ≤1e-12/P_max 恒等+6.0206dB 余量/30Ω-76.7Ω 常数/TM010=11.4743GHz
    # 独立常数/主模判据两腔复现/εr=4 全谱÷2 逐位/谱 vs 暴力枚举闭合/
    # 模式图交叉 r 逐位+跨键一致/Q 双路线 <1e-9+Ue/Um=1+TM010 清洁式/
    # Qc∝1/√σ/守卫）
    "coax_line_z0", "coax_line_attenuation", "coax_line_power_capacity",
    "circular_cavity_mode_spectrum", "circular_cavity_mode_chart",
    "circular_cavity_mode_q",
    # aurora72 A3-B 内核第二梯队批 2 五键（2026-10-11，#231 五钉同步；
    # R7_core_tier2 Top12 排名 3/4 两域，各一新股文件）：
    # ① 双/三支节并联调配器族 stub_tuner.py（T3——R7 三重搜索证据：
    # stub/tuner 键面零命中；t_match=集总三元件、quarter_wave/klopfenstein=
    # λ/4 变换/渐变线不并入）：双支节（归一电纳解析解——y_L=Z0/Z_L=g+jb，
    # 经间距 t=tanβd 变换 g2=g(1+t²)/[(1−tu)²+t²g²]，g2=1 ⟺
    # (1−tu)²=g[1+t²(1−g)]，有解 ⟺ g ≤ csc²(βd)（禁区 g>csc²(βd)，
    # λ/8 间距 g_max=2 Pozar 经典口径；禁区负载如实返 solvable=False
    # 不拒绝）；解 u=[1∓√D]/t 取 |u| 最小支，b_s1=u−b、b_s2=−Im(y2)；
    # 开路/短路支节长度回代 tan/cot 恒等；ABCD 级联 |Γ_in| 回代机器
    # 精度级；stub1_deg 可旋转负载出禁区）/三支节（首支节旁路/
    # 旋转双路线确定性规则消除禁区——旁路 Re[T(y_a,t)]≤g_max → b_s1=0；
    # 旋转 g_a≤g_max 时 u1 使 g2=1、g_a>g_max 时 u1=1/t 取可达电导
    # 上峰 (1+t²)/(t²g_a)<1<g_max——任意 r_L>0 负载有解，route 字段
    # 如实报告）。
    # ② 偶极/折合/小环输入阻抗族 linear_antenna_zin.py（T4——R7 三重
    # 搜索证据：dipole/folded/loop 单元阻抗键面零命中；emc_radiated=
    # 场强/patch/helix/lpda=其他单元不并入）：偶极（R=正弦电流辐射
    # 功率积分路线 η/(2πsin²kh)·∫[cos(kh·cosθ)−cos(kh)]²/sinθdθ——
    # 对假设分布精确，短偶极渐近 20π²(l/λ)²（三角电流极限）与半波
    # 73.1Ω 教科书常数双锚；X=感应电动势法 Si/Ci 经典闭式（Balanis
    # §8.4 印刷形含 Ci(2ka²/l) 线径项）半波 j42.5Ω 锚；谐振长度
    # [0.40,0.50]λ 二分（细线 ~0.47λ 锚带）；方向性共享同一积分——
    # 半波 2.15dBi/短偶极 1.76dBi 双锚）/折合偶极（传输线法两模分解：
    # 天线模 Z_d 与传输线模 2jZ_t·tan(kl/2) 馈点并联，谐振 l=λ/2 处
    # Z_in=4Z_d 等粗 4×（73.1Ω→292Ω≈300Ω 教科书口径，线径/间距谐振
    # 点约去=恒等锚）；l=mλ 处 Z_in=0 短路边；不等线径 Mushiake 比
    # 如实不做）/小环（Rr=320π⁴N²(A/λ²)² ≡ 20π²N²(C/λ)⁴ ≈ 31171·
    # N²(A/λ²)² 三式恒等（320π⁴=31170.9）；趋肤损耗 R_L=Rs·N·b/a；
    # 效率/Grover 电感 L=μ0b[ln(8b/a)−2]（X=2πf·N²L 密绕近似如实
    # 注记）/Q；电小判据 C/λ≤0.3 守卫）。
    # 薄壳物理自含 calc_families/stub_tuner.py 与 linear_antenna_zin.py。
    # 共同锚树 tests/unit/test_a3b_stub_antenna.py（g_max 45°→2/60°→4/3
    # 解析钉/可调区随机负载独立 ABCD 回收/禁区→三支节 matched/支节
    # 长度回代恒等/半波 73.1+j42.5 教科书常数/20π² 渐近 <1e-3/2.15dBi
    # /1.76dBi 双锚/谐振 0.47~0.49λ 锚带/折合 4× 恒等+并联恒等式/
    # 三式恒等机器精度/N×2→Rr×4、b×2→Rr×16 标度逐位/守卫）
    "stub_tuner_double", "stub_tuner_triple",
    "dipole_emf_zin", "folded_dipole_zin", "small_loop_zin",
    # aurora72 A3-C 内核批 2 四键（2026-10-11，#231 五钉同步；R7 第二梯队
    # T5/T6 两域，各一新股文件 2 键）：
    # ① 耦合线带通综合族 coupled_line_bpf.py（T5——R7 三重搜索证据：
    # calc_families 注册键面 coupled/interdigital 零命中；synthesis.py
    # synthesize_bpf_model=耦合矩阵级（广义切比雪夫→(N+2)×(N+2) 归一化
    # 矩阵，无物理尺寸）、render_coupled_bpf=模板渲染级（adapter 层绑定
    # TEMPLATE_META）、coupling_matrix_*/sir/mask=矩阵/SIR/规格级——本族
    # 只做全极点切比雪夫平行耦合线 BPF 实现尺寸链）：综合键（g 值走
    # core/matching 单源→J 倒置器 x 列表（Pozar §8.6：端
    # x01=√(πδ/2g0g1)、内 xj=(πδ/2)/√(gjgj+1)）→逐节
    # Z0e=Z0(1+x+x²)/Z0o=Z0(1−x+x²)→(w,s) 稳健二维反解（正向=core KJ
    # 1984 coupled_microstrip_even_odd_ohm；内层 s: Z0e 随 s 单调降
    # brentq、外层 w 网格括号——slotline_transitions 同义反解的外括号
    # 启发式在本综合域边缘实测 nan 假越域，故自带括号逻辑）→段长
    # λ/4@εeff 均值+谐振器 λg/2−2Δl（Hammerstad）+50Ω 馈线宽（skrf
    # HJ）。锚：Pozar Example 8.7（§8.6 p.435 4ed 文献例引文）阻抗表
    # (70.61,39.24)/(56.64,44.77) 逐位复现（εr/h 无关路径）+g 表
    # 1.5963/1.0967；x=(Z0e−Z0o)/(2Z0) 回代恒等；KJ 正向 ≤1e-6。
    # 频响键（同步 TEM 口径：偶/奇模 2 端口线 S 叠加成 4 端口、交叉口
    # Γ=+1 开路端接压缩 2 端口 ABCD 级联（S→ABCD 按 Pozar Table 4.2））：
    # 带心 |S21|=0dB/带内 S11 谷数=N/无耗恒等构造/vs 切比雪夫原型闭式
    # （测试侧独立 ε=√(10^(rip/10)−1)）带内 ≤0.5dB（带缘倒置器频率依赖
    # 二阶偏差实测 ~0.28dB）/vs adapters 裁判 coupled_bpf_circuit_sparams
    # （同物理异层实现）≤1e-6dB；θ=kπ 显式拒绝。
    # ② 交指杆实现族 interdigital_bpf.py（T6——R7 三重搜索证据：
    # combline_resonator=单谐振器频率/Q 级、render_c3 interdigital_
    # design_from_order=模板渲染级 KJ 微带链、hairpin_tap_frac_from_qe=
    # 抽头位已有——本族做 Getsinger 条带线（平行板均匀介质）电容闭式档，
    # 语义互补）：电容键（零厚度耦合杆条带线共形映射精确闭式：k_e=
    # tanh x·tanh y/k_o=tanh x/tanh y（x=πw/2b、y=π(w+s)/2b）、稳定形
    # k'（s→0 消相消）；Z0m=30π/(√εr·K/K')（AGM，与 rf_line 同 30π 口
    # 径）；C_m=√εr/(c0·Z0m)。双极限锚：s→∞=单杆条带线精确值（vs
    # stripline 跨键）；s→0 偶模每线阻抗=2×并合 2w 条（每线电容减半，
    # Landen 恒等 tanh²x=(1−sech2x)/(1+sech2x) 数值闭环）；k 电容式/
    # 阻抗式 TEM 恒等；J=v(C_o−C_e)/2）。综合键（Getsinger 1961 等效
    # 网络：λ/4 短路杆斜率 b=π/(4Z_r)→J01=√(bδ/(Z0g0g1))、
    # J_j=bδ/√(gjgj+1)→(C_e,C_o)=(√(ΔC²+4C0²)∓ΔC)/2 闭式（几何均值
    # 约束 Z0e·Z0o=Z_r²）→(w,s) 二维反解→杆长 λ/4@√εr）。锚：J 往返
    # （键出 6 位舍入→公共面 rel1e-3+in-output 全精度 ≤1e-9）；奇 N 缝
    # 回文；内节 k=δ/√(gjgj+1) 构造恒等（端节=Q_e 语义分列）；δ↑ 内缝
    # 单调收窄；越域显式拒绝。有限杆厚/端电容 Getsinger 修正与微带非
    # 均匀介质档不在 v1 口径（如实注记）。
    # 薄壳物理自含 calc_families/coupled_line_bpf.py 与
    # interdigital_bpf.py。共同锚树
    # tests/unit/test_a3c_coupled_interdigital.py（Pozar 表逐位/x 回代/
    # KJ 回代/段长重算/馈线 HJ 回代/带心 0dB/S11 谷数=N/无耗恒等/
    # 切比雪夫 ≤0.5dB/裁判 ≤1e-6dB/θ=kπ 拒绝/s→∞ 跨键/s→0 Landen/
    # k 两式恒等/C∝εr 缩律/k-s 单调/J 往返/缝回文/Qe 恒等/δ 单调/
    # 守卫族/描述形态门）
    "coupled_line_bpf_synthesize", "coupled_line_bpf_response",
    "interdigital_bars_capacitance", "interdigital_bpf_synthesize",
    # aurora72 A4-B 内核第二梯队批 5 六键（2026-10-11，#231 五钉同步；
    # R7_core_tier2 T9/T10/T11 三域，各一新股文件 2 键）：
    # ① 雷达目标 RCS 闭式件族 rcs_targets.py（T9=G10——R7 三重搜索证据：
    # corner.reflector|角反射器 零、mie|sphere.*rcs 仅 ridged_waveguide
    # "Jamieson" 误命中、rfid 的 RCS 是标签参数非目标库；radar_range_
    # equation 的 σ 是输入参数=本族是目标侧供给端）：金属球（精确 Mie
    # 级数 σ=(πa²/ρ²)|Σ(−1)^n(2n+1)(a_n−b_n)|²（ρ=ka，PEC 球 Mie 系数
    # a_n=−ψ'/ξ'、b_n=−ψ/ξ，Wiscombe 截断）+Rayleigh 9πa²(ka)⁴ 与光学
    # πa² 双解析极限自证字段 + 三区判据（rayleigh ka<0.5/mie 0.5–10/
    # optical ka>10 工程带）+ ka∈[1e-3,200] 级数稳定域守卫）/典型目标
    # 峰值库（平板法向 4πA²/λ²、二面角 8πa²b²/λ²（等效孔径 √2·ab）、
    # 方形三方角 4πa⁴/(3λ²)（等效孔径 a²/√3）、圆柱侧向 2πL²r/λ；板族
    # λ⁻² 与圆柱 λ⁻¹ 双标度钉；dBsm 换算恒等；三角三方角/圆锥尖顶常数
    # 源无法双源钉死如实不做）。
    # ② 检波/功率测量器件族 detector_device.py（T10=G13——R7 三重搜索
    # 证据：square.law|tangential|tss 仅 alt_planning 应力温度误命中；
    # power_cal_chain=校准链、cispr_detector=EMC 检波算法，器件级零）：
    # 平方律检波（i=kv² + 射频匹配 P=V_rms²/R_j → I_dc=(k·R_j)·P_in≡
    # β·P_in 灵敏度常数恒等，P×2→I×2 线性标度；平方律有效域
    # [−120,−20]dBm 工程惯例上沿、域外显式拒绝不外推压缩区）/TSS-NEP
    # （视频约翰逊噪声 v_n=√(4k_BT·R_v·B_v) → NEP=v_n/γ；TSS=检波后
    # SNR=8dB 切向判据口径写死，平方律下 TSS−NEP=snr/2=4.0dB 恒等；
    # √B/√R_v/√T 标度逐位；TSS 按脉冲定义 B_v 与脉宽配套如实注记）。
    # ③ PIM 多节点累计族 pim_cascade.py（T11——本次 triple-grep 证据：
    # pim_products/pim_empirical=单节点枚举/换算（未注册）、cascade_
    # budget/budget.B5=有源链增益加权截点级联（B5 docstring 明示二阶
    # 电压相干最坏"须自行换算"）——多节点电平累计键面零命中）：
    # 节点合成（同一产物频点 N 节点实测电平双口径：非相干功率和
    # 10log10ΣP 与相干同相最坏 20log10Σ√P，spread=相位统计带双极限；
    # N 等电平 +10log10N/+20log10N 恒等、N=1 退化恒等）/级联预算（参考
    # 条件 IEC 62037 +43dBm/载波实测电平→幂级数精确律平移（order n 斜
    # 率 n，实测覆盖 slope_db_per_db>0）→双口径累计（与合成键同核跨键
    # 互证）→可选限值裕量（相干负裕量如实报告不拒绝））。相干分支即
    # budget.py B5"二阶最坏情形自行换算"口径的电平注入式实现（互补
    # 不重复）。
    # 薄壳物理自含 calc_families/rcs_targets.py、detector_device.py 与
    # pim_cascade.py。共同锚树 tests/unit/test_a4b_rcs_detector_pim.py
    # （Rayleigh 闭式窗/深瑞利 ≤1e-4/f⁴ 标度/光学窗/对数导数降序递推
    # 独立 Mie 路线六点 ≤1e-9/三区边界双侧钉/四闭式独立重算/1m² 平板
    # 41.45dBsm/双标度/二面角 2× 平板/三方角等效孔回代/I_dc 常数链/
    # 线性标度/β 常数性/√B 标度/TSS−NEP=snr/2 恒等/等电平恒等/跨键
    # 互证/精确律 +3.0dB/IM2 斜率 2/斜率覆盖/限值裕量恒等/守卫族/
    # 描述形态门）
    "rcs_sphere_mie", "rcs_peak_canonical",
    "diode_square_law_detect", "detector_tss_nep",
    "pim_nodes_combine", "pim_cascade_budget",
    # aurora72 A4-A 内核第二梯队批 4 五键（2026-10-11，#231 五钉同步；
    # R7_core_tier2 T7/T8 两域，各一新股文件）：
    # ① VNA 测量不确定度族 vna_uncertainty.py（T7=G19——R7 三重搜索证据：
    # three.antenna|增益比较 零；nf_measurement=Y 因子 GUM（噪声面）、
    # material_uncertainty=Dk 容差（材料面）、tnvna=THz 扩频链、trl=校准
    # 件设计（校准上游）均非 S 参数残差传播）：反射不确定度（校准后残差
    # 三误差项经典纹波合成——δΓ≈Ed+ΔTr·Γ+Es·Γ² 一阶展开（Rytting 单端口
    # 误差模型），最坏界 |δΓ|≤|Ed|+|ΔTr||Γ|+|Es||Γ|² 逐项分解+主导项；
    # rss 档=均匀分布 Type-B 界/√3 方和根 u+扩展 U=k·u（EURAMET cg-12）；
    # 回损域换算 RL=−20lg|Γ|（Γ=0 理想负载→回损地板=−directivity_db 恒
    # 等=残差方向性限定可测最佳回损经典结论）/传输不确定度（传输侧四误
    # 差模型 δS21≈Xt+ΔEt·S21+El·S21² 同构；S21=0 隔离地板=−crosstalk_db
    # 恒等；直通@El=−20dB 纹波 20lg(1.1)=0.828dB 独立重算；源匹配二阶
    # 耦合项不在 v1 口径如实注记）/三天线法增益定标（Friis 口径 G_i+G_j
    # =FS−IL_ij 线性解三元组 G1=(FS−IL12−IL13+IL23)/2；构造恒等式随
    # pair_sum_max_err 机器精度自检；可选比较法 G_dut=G_ref+(IL_ref−
    # IL_dut)；失配/极化校正=输入侧责任如实 note）。
    # ② Swerling 检测补全族 radar_detection_ext.py（T8——radar_eq docst-
    # ring 自证"SW1-4 不冒充"的官方缺口；ca_cfar 的 SW1-Pd=CFAR β 门限
    # 口径不撞，本族=固定门限 T=Q⁻¹(N,Pfa) 检测因子）：检测因子三量互
    # 算（SW2 全 N 精确闭式 Pd=Q(N,T/(1+S̄))——信号复高斯与噪声严格合
    # 并；SW4 有限正权重 Γ 混合（每脉冲 CF=(1−jω)/(1−jωa)² 特征函数部
    # 分分式，本仓推导，权重和恒等式自检）；SW1/SW3 慢起伏 N>1 数值积
    # 分档（E_X[ncx2.sf(2T;2N,2NX)]，quad 固定容差确定性，如实声明）；
    # N=1 退化恒等 SW1≡SW2、SW3≡SW4（quad 核复现闭式=机器精度锚）；锚
    # Pfa=1e-6/Pd=0.9/N=1 → SW1=21.14dB vs SW0 精确 13.18dB（损失 7.96dB
    # 经典数 dB 窗））/非相干积累增益（improvement=SNR1−SNN>0 单调律；
    # SW1/SW3 loss≥0、SW2/SW4 可为负=起伏分集超相干界，符号如实不夹
    # 持；N=1 退化恒等三量全 0）。
    # 薄壳物理自含 calc_families/vna_uncertainty.py 与
    # radar_detection_ext.py。共同锚树 tests/unit/test_a4a_vna_swerling.py
    # （回损地板/单误差项退化/20dB 负载经典带/Type-B u 重算/隔离地板/
    # 直通纹波/Friis 正演反演逐位+92.45 常数式双源/对称恒等/比较法平移/
    # SW1-SW2 N=1 逐位/quad 核 vs 闭式机器精度/SW2 全 N scipy 独立重算/
    # SW4-SW3 双路线互证/原始基元蒙特卡洛 3σ/SW0 损失 7.96dB 窗/三向互
    # 算闭环/SW1 积累损失>0 与 SW2 分集负值对称钉/守卫族）
    "vna_reflection_uncertainty", "vna_transmission_uncertainty",
    "three_antenna_gain",
    "swerling_detection_factor", "swerling_integration_gain",
    # aurora72 A5-A 内核第二梯队批 6 六键（2026-10-11，#231 五钉同步；
    # R7_core_tier2 余量两域，各一新股文件 3 键）：
    # ① 声表面波 IDT 族 saw_idt.py（T12=G14——R7 三重搜索证据：\bsaw\b|IDT|
    # 声表面波 除 baw_ladder docstring 一句（梯形电路语境）外零命中；fading/
    # mimo 的 Rayleigh=通信信道语义误命中剔除）：同步设计双向（pitch≡λ0 指
    # 对周期口径写死，f0=v_R/λ0 双向；L=N_p·λ0、Δf_NN=2f0/N_p、N_p↔带宽
    # 倒数；ST 石英 1µm→3.158GHz 教科书常数锚）/δ 函数模型频响（Dirichlet
    # 核精确闭式 vs 几何级数逐项和双路线互证 ≤1e-12；零点栅格 Δf=k·f0/N 恒
    # 等；半零点 (2/π)² 经典常数；栅瓣归一功率=1 混叠如实报告；sinc 近似档
    # 仅主瓣区有效）/延迟线（τ=L/v 恒等；f² 传播损耗系数注入 α₁ 缺省 0=
    # 不冒充材料常数；双向 IDT 10lg2/只、双端 6.0206dB 恒等）。baw_ladder=
    # BAW/SAW 梯形电路综合（fs/fp 阻抗梯）不并入。
    # ② 混合结/魔 T 族 hybrid_junction.py（R7 G8 大件候补首拆席——magic.
    # tee|魔T|hybrid_ring|rat_race 注册键面零；ratrace 仅 anchor_benchmark
    # 模板锚判读、butler_matrix 内部 90° 混合环块（未注册）不并入）：魔 T
    # 理想 4 口 S 矩阵（幺正+E/H 臂隔离 S14=0+匹配+和差相位四约束；激励口
    # 逐端口输出）/H 面·E 面三口结（并联星形 S_ii=−1/3,S_ij=2/3 与串联对偶
    # S_ii=1/3,S_ij=−2/3 功率波第一性闭式，KCL/KVL 测试侧独立重解；S_E=−
    # S_H 对偶；无耗互易三口不可全匹配=拓扑必然，20lg(2/3)=−3.5218dB 侧臂
    # 均分）/和差合成（b±=(a2±a3)/√2；能量守恒残差；等幅同相/反相双 null；
    # 正交 −3.0103dB 恒等；与魔 T 键 4 口矩阵乘跨键互证）。理想口径出 S 矩
    # 阵不出尺寸综合（尺寸属波导模板域如实不做）。
    # 薄壳物理自含 calc_families/saw_idt.py 与 hybrid_junction.py。共同锚
    # 树 tests/unit/test_a5a_saw_hybrid.py（往返逐位/3.158GHz 常数窗/带宽
    # 倒数恒等/几何级数互证/零点栅格/半零点 (2/π)²/栅瓣混叠/τ=L/v/f² 标度/
    # 6.0206dB/SS† numpy 复算/四约束/相位 0°-180°/KCL-KVL 重解/对偶残差/
    # 能量守恒/正交拆分/跨键矩阵乘互证/守卫族/描述形态门）
    "saw_idt_sync_design", "saw_idt_frequency_response", "saw_delay_line",
    "magic_tee_s_matrix", "waveguide_tee_s_matrix", "hybrid_sum_difference",
    # aurora72 A6-B 内核机动批四键（2026-10-11，#231 五钉同步；R7_core_tier2
    # §② 余量两域，各一新股文件 2 键）：
    # ① 多节对称定向耦合器族 multisection_coupler.py（G5 余量——R7 三重搜
    # 索证据：multisection|levy 注册键面零命中，synthesize_multisection_
    # quarter_wave=λ/4 匹配变换器同名异域、bethe_hole_coupler=单节孔耦合、
    # coupled_line_bpf_*=带通谐振实现均不并入）：二项式（中心最大平坦）
    # 综合（结点权由 g(x)∝∫₀ˣ(1−t²)^M dt 与 sin 多项式三角分解唯一确定：
    # N=3 → 结点比 1:9:9:1、节耦合比 1:10:1；N=5 → 3:25:150；电平归一对
    # 精确偶/奇级联 θ=90° 求根，f0 精确命中目标耦合；一阶 vs 精确二阶差
    # 如实并列字段）/精确频响（偶/奇模各自 2 端口线级联叠加 4 端口：S31=
    # (Se11−So11)/2、S41=(Se21−So21)/2；构造恒无耗 |S11|²+|S21|²+|S31|²+
    # |S41|²=1 与互易；Z0e·Z0o=Z0² 配对下 f0 隔离口精确零 |S41|<1e-12 记
    # None）。(Z0e,Z0o) 同 core/slotline_transitions.even_odd_from_coupling
    # 闭式单源。单节退化锚=精确闭式 c·sinθ/√(1−c²cos²θ)（测试侧独立重解
    # #118）。
    # ② Gysel 功分器 core 电气族 gysel_core.py（G6 余量——R7 复核：现仅
    # synthesis.py synthesize_gysel_model 模板级（叠层几何配方）+fake 裁判
    # 级 _gysel_sparams（f0 常数理想 S），注册计算器 core 级零命中）：闭式
    # 综合（#206 定版拓扑 √2·Z0 臂+Z0 隔离线+Z0 λ/2 桥带（中点 M=对称面
    # 真实节点）+Δ1/Δ2 外置 Z0 负载；偶/奇半电路验证 Γe=Γo=0（有限代理
    # 端接两组缩比收敛到虚开路/虚地）+理想 f0 三口 S 矩阵（互易非幺正如
    # 实注记））/五线六节点导纳网络精确频响（Y_self=−j·cotθ/Zc、Y_mutual=
    # j·cscθ/Zc；耗散守恒 |a1|²=Σ|b_k|²+|V_Δ|²/Z0 残差字段；f0 锚 vs 理想
    # 矩阵逐位；no_bridge 判废对照字段=−6.53dB 与 #206 判废锚独立吻合；
    # 桥带拆中点 M 正则化规避连续 λ/2 的 Y 参量 θ=kπ 奇异）。
    # 薄壳物理自含 calc_families/multisection_coupler.py 与 gysel_core.py。
    # 共同锚树 tests/unit/test_a6b_multisection_gysel.py（N=1 闭式逐位/
    # 结点比 1:9:9:1 与最大平坦独立重解/节耦合回文/求根残差 1e-9/能量守恒
    # 1e-12/f0 隔离零/对称残差/γ 半电路收敛/−3.0103dB 恒等/耗散守恒/
    # no_bridge=−6.53 判废/跨键互证/守卫族/描述形态门）
    "multisection_coupler_binomial", "multisection_coupler_response",
    "gysel_core_synthesize", "gysel_frequency_response",
    # aurora72 A7-B 内核机动批2 五键（2026-10-11，#231 五钉同步；任务书候补
    # 两域——R7_core_tier2 候补池，各一新股文件）：
    # ① 矩形波导膜片/谐振窗匹配族 waveguide_iris.py（#222 triple-grep 证据：
    # iris|膜片 注册键面零命中，rwg_mmt=数值模匹配（H 阶梯构件级联 GSM，
    # 模块先例不注册）、rwg_tables=EIA 商品表、waveguide_closed_form=圆波
    # 导/腔谱、waveguide_tee=E/T 三口结均不并入）：对称薄膜片电纳正反解
    # 双向（感性 −(λg/a)cot²(πd/2a)/容性 (4b/λ0)ln csc(πd/2b) 薄膜片工程
    # 近似档，容式 λ0 与感式 λg 依赖差异如实照录）/谐振窗（B_ind+B_cap=0
    # 共振条件反解容性开口，指数下溢可达域守卫）/单膜片匹配（y_L 沿线变
    # 换 g_in=1 二次方程双分支闭式，判别式 g[b²+(1−g)²]≥0 恒两实根；开口
    # mm 反解+ABCD 回代构造级残差；感性分支工程优先；与 stub_tuner 边界
    # =波导 λg 口径+几何尺寸输出面）。
    # ② Guanella 传输线变压器族 guanella_tlt.py（#222 证据：guanella|balun
    # 注册键面零命中，marchand=slotline_transitions 模板级渲染、
    # quarter_wave/klopfenstein=单线拓扑、t_match/rf_match=集总 L 均不并
    # 入）：n²:1 设计（n=√比整数守卫、5:1 复合比显式拒绝、每线
    # Z0=√(Rin·Rlo) 全频匹配口径、λ/8 线长准则）/串入并出复合拓扑逐频精
    # 确解（4 端子线 Y 参量盖章+链节点消元+不等参考 D 标度 2 口 S；全频
    # 段理想匹配定理 |S11|≤1e-12、θ=90° 失配 (k²−1)/(k²+1) 经典倒抗式、
    # 无耗守恒+互易残差；低频磁化电感拐角 UNVERIFIED 如实不做）。
    # 薄壳物理自含 calc_families/waveguide_iris.py 与 guanella_tlt.py。
    # 共同锚树 tests/unit/test_a7b_iris_guanella.py（闭式测试侧独立重算
    # 1e-12/极限恒等与单调/正反解双向往返 1e-9/TE10 标度恒等/谐振窗回代
    # 零残差+验证档如实+下溢守卫/教科书解 y_L=0.5-|t|=√2 独立推导/ABCD
    # 回代 1e-9/g>1 与 Γ=0 退化/n² 恒等与 5:1 拒绝/λ/8 常数链/全频匹配定
    # 理 1e-12/标量串并式 vs 消元式双路线 1e-9/θ=90° 倒抗闭式/θ↔π−θ 对
    # 称单调段/n=1 直通恒等/θ=kπ 精确奇异拒绝/守卫族/描述形态门）
    "wg_iris_susceptance", "wg_resonant_window", "wg_iris_match",
    "guanella_tlt_design", "guanella_tlt_response",
    # aurora72 A8-B 内核末批四键（2026-10-11，#231 五钉同步；任务书候补
    # 两域，R7_core_tier2 附加候选余量成席，各一新股文件）：
    # ① 经典渐变线族 taper_classic.py（#222 triple-grep 证据：
    # exponential_taper|linear_taper|triangular_taper 注册键面零命中，
    # klopfenstein_taper=最优 Dolph-Chebyshev 剖面+微带宽度实现面、
    # quarter_wave=离散 λ/4 阶梯、t_match/stub_tuner=集总/支节调配均不
    # 并入）：线性/指数剖面逐频小反射理论双路线（指数 sinc 闭式/线性 Ei
    # 指数积分闭式 + 剖面核数值积分交叉互证；βL→0 阶跃极限包络 |δ|/2、
    # βL=π sinc 零点、剖面反转对称）/综合（|Γ(βL)|=ρ_max@f_min 首个变号
    # 括根+brentq，βL∈(0,4π] 不赌单调段；ρ≥|δ|/2 阶跃极限显式拒绝；第
    # 一瓣通带上界 f_max=π·f_min/x* 如实登记不冒充全带）。
    # ② 隔离器/环行器理想 S 口径族 isolator_circulator.py（#222 证据：
    # isolator|circulator 注册键面零命中，circulator_synthesis=铁氧体结
    # 尺寸综合内核（未注册）、magic_tee/waveguide_tee=互易结不并入）：
    # 两键均 reciprocal=False（registry QM-1 §D-7 非互易豁免位首批注册
    # 键，S≠Sᵀ 设计本体互易断言不适用）——隔离器 dB 规格参数化理想 2 口
    # S（IL/Iso/RL，None=理想档哨兵；无源性 γ²+c²≤1 双口守卫；理想极限
    # 档回 canonical [[0,0],[1,0]]）/环行器 sense=cw|ccw 理想 3 口 S（环
    # 行项/隔离项/对角 γ；每口无源性 γ²+c²+i²≤1 守卫；sense 翻转恒等式
    # S_ccw=S_cwᵀ；理想极限档回置换矩阵）。
    # 薄壳物理自含 calc_families/taper_classic.py 与 isolator_circulator.py。
    # 共同锚树 tests/unit/test_a8b_taper_isolator.py（指数 sinc 测试侧纯
    # math 重算 1e-12+独立 Simpson 互证 1e-9/线性 Ei vs 独立 Simpson
    # 1e-9/βL→0 阶跃极限/βL=π 零点/反转对称/第一瓣单调/综合回代 1e-9+
    # 二分法独立求根 1e-6/第一瓣上界恒等式/半长判废/阶跃极限拒绝/隔离器
    # canonical 逐位+dB 重算 1e-12+无耗违约拒绝+互易退化档对称/环行器置
    # 换矩阵逐位+S_ccw=S_cwᵀ 逐位+酉性核对+总能量恒等式/豁免位钉/守卫
    # 族/描述形态门）
    "classic_taper_response", "classic_taper_synthesize",
    "isolator_ideal_sparams", "circulator_ideal_sparams",
    # 批 B Wave3 G9 圆柱 DR TE01δ 正解/反解两键（2026-10-13，#231 五钉同步）：
    # Cohn 1968 磁壁超越方程 tan(βL/2)=α/β brentq 正解 + εr/f0/L-D 比反解
    # （不做 Kajfez 拟合表数字化）；实现 calc_families/dr_te01d.py；锚树
    # tests/unit/test_b_wave3_dr_te01d.py（D1-D5 规格包独立复算锚+测试侧
    # 纯二分第二路线 ≤1e-9/x01=J0 首零与圆柱腔 TM010 同根/贴面极点=式 D2
    # 结构恒等 f_D1<f_D2 严格/εr×4 标度破缺 0.501011 vs 式 D2 严格 ÷2/
    # L→0 趋频窗上缘（规格勘误：不收敛于贴面值）/courtney(J1 confined)
    # 口径边界方向锚/roundtrip ≤1e-10/边界恰值 εr=2.0 接受 1.999 拒绝、
    # h=2.0 恰值拒绝）；material_characterization courtney_*=提取面不并入
    "dr_te01d_cohn_f0", "dr_te01d_design_size",
    # 批 B Wave3 G17 轴向模螺旋薄注册三键（2026-10-13，#231 五钉同步）：
    # 薄包装（公式单源 core/helix_axial Kraus 闭式，Balanis §10.3.1 转引，
    # 本面零公式复制——#116 死副本教训）；锚树 tests/unit/test_b_wave3_
    # helix_reg.py（薄度守卫=wrapper 输出与 core 直调逐位 == 主判据/H1
    # 工作例透传/恰等出域 verdict 透传/透传拒绝面/N≤3 失效域 warnings）；
    # 物理锚树 tests/unit/test_helix_axial.py（B2 批在库，不重造）；
    # anchor_family_service=anchor 通道并存不撞
    "helix_axial_performance", "helix_axial_design", "helix_axial_bandwidth",
    # 批 B Wave3 G15 Yagi-Uda NBS TN688 两键（2026-10-13，#231 五钉同步）：
    # 实测经验数据面（Viezbicke NBS TN688 原文文本级验证，非闭式推导）：
    # 增益阶梯（六档 0.4-4.2λ → 7.1-14.2 dBd 逐字锚+线性插值档如实标注+
    # dBi=+2.15 恒等）+档位几何骨架（单元数 3/5/6/12/17/15 图注逐字/反射
    # 器间距 0.2λ/仅文本验证档的间距与长度——0.8λ 档 0.2λ+0.485/0.442+
    # 修正单点 0.490/0.447、4.2λ 档 0.308λ，其余 null 禁编造）；实现
    # calc_families/yagi_uda.py；锚树 tests/unit/test_b_wave3_yagi_slot.py
    # （B1-B8 规格包锚+例题恒等复核 ±0.003λ 截断容差/插值单调/跨键增益
    # 同源/封闭枚举拒绝/域外不外推）；dipole/folded=单元阻抗、array.*=
    # 幅度综合、helix=螺旋不并入；Table 1 全表数字化维持待有书如实不硬造
    "yagi_gain_nbs_tn688", "yagi_geometry_nbs_tn688",
    # 批 B Wave3 G16 波导缝隙阵 Stevenson 两键（2026-10-13，#231 五钉同步）：
    # RESOLVED 裁决式（规格包式 S1 证伪勘误——四路独立二手源逐字互证
    # +WR90 数值逐位，含 (a/b) 与 cos²(πλ0/2λg) 两因子；原文 closed 式号
    # 不可考禁编造）：slot_stevenson_conductance=宽壁纵缝谐振电导
    # g(x)=2.09(a/b)(λg/λ0)cos²(πλ0/2λg)sin²(πx/a) 正反解（route 二选一/
    # g>g_max 显式拒绝/g_max=1 边界 9.753118GHz WR90）+
    # slot_array_synthesis_resonant=驻波阵综合（gn=g_total·wn²/Σw²+交替
    # 换边+λg/2 间距+末缝后 λg/4 短路+单缝封顶守卫）；实现
    # calc_families/slot_array.py；锚树 tests/unit/test_b_wave3_yagi_slot.py
    # （RESOLVED 勘误表 A1-A7 替代锚/N1-N4 逐位+S1 源 Table II 跨源钉
    # 0.127649/sin² 半角恒等式第二路线/roundtrip/渐近/恰等行为）；
    # rw_tables/rwg_mmt/waveguide_iris/siw_*=波导其他面不并入
    "slot_stevenson_conductance", "slot_array_synthesis_resonant",
    # 批 B Wave3 W3-CORE3 G11 余量 PA/控制件四键（2026-10-13，pa_arch
    # 原位扩展，#231 五钉同步）：ET 包络跟踪效率（理想 B 类+Rayleigh
    # 包络+供电下限/削顶能量口径闭式——f=0→π/4 与 PAPR 无关/f=1→定供
    # 对照逐位结构恒等/scipy 数值积分第二路线 ≤1.3e-9）+PIN 二极管限幅
    # 器（并联导纳两态 S+功率三分和=1+R_on=Z0/2 吸收 50% 最大+门限
    # Vf²/2Z0 一阶估计档）+步进衰减器（二进制位组合 floor 量化余量
    # 如实+逐位 π/T 节单源消费 rf_match+worst/RSS 堆叠双口径）+倍频链
    # 预算（f=∏M·f_in+20log10(N) 相噪律逐级恒等+dBm 预算+剩余相噪功率
    # 和单列）；实现 calc_families/pa_arch.py 原位；锚树
    # tests/unit/test_b_wave3_pa_ctrl.py（独立复算锚+数值积分第二路线/
    # ABCD 退化恒等式/能量守恒/镜像阻抗回代/单调性/退化恒等）；固定
    # 衰减节 attenuator_pi/t、混频杂散 spur_search 不并入
    "envelope_tracking_efficiency", "pin_diode_limiter",
    "step_attenuator_design", "multiplier_chain_budget",
    # aurora_d W3-CORE6 四键（2026-10-14，R7 附加候选"loaded-line/
    # switched-line 移相器"+G20 行"doa 余量=CRB"+多工器顺手件）：
    # 加载线移相器（双并联可切换电纳格胞——匹配 b=2cotθ、Δφ=2arctan(b/2)
    # 闭式+ABCD 分析反解，Δφ≥180° 拒绝指回开关线）+开关线移相器（路径差
    # 电长度 TTD 口径 Δφ=360°Δl√εeff·f/c0，λg/4→90°、群时延 1/(4f)
    # 恒等）+DOA 单源 CRB（ULA 确定性下界 12/(2T·SNR·N(N²−1)k²cos²θ)，
    # 数值投影器第二路线 rel≤1e-12）+多工器信道规划（等分数/等绝对平铺
    # +交越 3.0103dB 互补定理）；实现 calc_families/phase_shifter.py+
    # doa_crb.py+multiplexer.py；锚树 tests/unit/test_aurora_d_core6.py
    # （numpy ABCD 级联/投影器 Fisher/几何中点恒等三族第二路线+roundtrip+
    # 标度律+域拒绝）；schiffman 模板级/butler 积木/varactor 谐振语境/
    # doa_* 估计器本体/diplexer_compose 内核不并入；SSIR 键语义 R7 原文
    # 无定义如实跳过不硬造
    "loaded_line_phaser", "switched_line_phaser",
    "doa_crb_ula", "multiplexer_channel_plan",
    # aurora_d W3-CORE7 三键（2026-10-14，R7 附加候选顺手件三域）：
    # ① Cpk↔良率正态尾双向换算+多工序串联良率（manufacturing_yield.py——
    # 单尾 Φ(3Cpk) Montgomery 表值档+双限边际精确两尾 Φ(3Cu)·Φ(3Cl)+仅知
    # Cpk 的界 [Φ(3Cpk)²,Φ(3Cpk)] 如实声明；串联=独立乘积+等相关高斯精确
    # 合并（ρ=0 退化乘积/ρ→1 退化 min 双极限）+Fréchet–Hoeffding 界并列；
    # manufacturing_stats(cpk_ci)=样本→CI/tolerance_allocation=公差分配面
    # 不并入）② taper_classic 原位扩展**三角剖面**（Γ=(δ/2)e^{−jx}sinc²
    # (x/2π) 首零 βL=2π——R7"渐变线指数/三角 profile"残项，指数/线性 A8-B
    # 已落）③ combline_coupling_gap（interdigital_bpf 第三键——R7 T6 两半
    # 边的 combline 残半：k_ij→J=b_s·k→(C_e,C_o)→(w,g_ij) 带域边界二分反
    # 解，斜率双档=空载 π/(4Z_r)/装载 [cotθ₀+θ₀csc²θ₀]/(2Z_r)；截面电容与
    # interdigital 两键同源 Getsinger；combline_resonator=谐振器级不并入）；
    # 锚树 tests/unit/test_aurora_d_core7.py（闭式 vs 剖面核 Simpson/
    # Montgomery 表值/quad vs GH/k↔J 代数互逆/跨键结构锚五族第二路线）；
    # R7 审计行"Wong"引文文献不可达如实跳过（combline 出处取 Getsinger
    # 1962+MYJ ch.8，Caspi 多项式近似档不并入）
    "cpk_yield_convert", "serial_yield_budget",
    "combline_coupling_gap",
    # aurora_d W3-CORE8 四键（2026-10-14，CORE6 遗留清单续作+R7-PREP G16
    # 可选件）：① doa_crb_ula_multisource（多源确定性 CRB——FIM=2T·
    # Re[(DᴴP⊥D)⊙P̄ᵀ] 通用式求逆对角元（Stoica-Nehorai 1989/Viberg-
    # Ottersten 1991 形态），P̄=√snr·R·√snr 等相关源协方差 ρ∈[0,1)；ρ=0
    # FIM 对角恒零化解耦但全 A 投影致罚因子>1、ρ→1 奇异显式拒绝；M=1
    # 与 doa_crb_ula 逐位一致回归钉；N>M 投影秩硬前提；随机 CRB 不在
    # 键面如实登记）② reflective_phaser（反射式移相器——环行器/正交混
    # 合环+可变电抗终端，Γ=(r+jx−1)/(r+jx+1) 二态、无耗 |Γ|=1/
    # φ=180°−2arctan(x)；设计 ±x=tan(Δφ/4) 容感对称态对（180° 位双有限
    # 态，与加载线 b→∞ 分工）+电抗/变容管分析反解+r_norm 损耗口径；
    # Pozar ch.10 反射式章节级转引，文献可达已核）③
    # multiplexer_channel_prototype（多工器逐通道阶数原型——带通→低通
    # 几何中心精确变换（Ω 边缘=±1 恒等）+最小阶闭式（N−1 阶并列证明）
    # +g 值链（Chebyshev 复用 core/matching 单源；Butterworth 闭式 N≤5
    # 与 diplexer_compose 互证））④ waveguide_lambda_g（TE10 λg/λc/β 抽
    # 键——R7-PREP G16 可选件"λg 闭式抽独立键"：内部复用 waveguide_
    # iris._frequency 单源零公式复制，slot_array 内嵌/microstrip 准 TEM
    # 分层不撞）；实现 phase_shifter/doa_crb/multiplexer/waveguide_iris
    # 四文件原位扩展；锚树 tests/unit/test_aurora_d_core8.py（全参数
    # FIM Schur 消元/阻抗式数值角/整数扫描+T_n 递推/λg 三形态互证四族
    # 第二路线+退化回归钉+域拒绝）
    "doa_crb_ula_multisource", "reflective_phaser",
    "multiplexer_channel_prototype", "waveguide_lambda_g",
    # aurora_d W3-CORE9 三键（2026-10-14，CORE8 遗留登记收口）：
    # ① doa_crb_stochastic（随机（高斯）信号 CRB——celebrated 闭式
    # CRB=(σ²/2T){Re[(DᴴP⊥D)⊙(QAᴴR⁻¹AQ)ᵀ]}⁻¹（Stoica-Nehorai 1989 两模
    # 型对照随机半边）+精确 Slepian-Bangs 全参数（σ²、Q Schur 消元）内建
    # 互证面（全域恰等 rel≤7.5e-15 实测）；M=1 退化=确定性键×(1+1/(pN))
    # 比值恒等式）② schiffman_phaser（Schiffman 耦合线移相器电长度设计
    # 面——arccos 闭式 φ_c=(ρ−tan²θ)/(ρ+tan²θ) 连续支延拓+Δφ=B·θ−φ_c；
    # 分析/定 ρ 设计/平坦点双条件综合三路线；θ₀=90°/B=3→90° 经典锚精确；
    # 文献=Schiffman 1958 IRE MTT 6(2):232-237 原文可达已核；物理长度/
    # 几何=synthesis.py QW-10、模板=render_phase_qwt.py 三层不重复）
    # ③ switched_network_phaser（开关网络式——PIN 选通 LC 低通 T 节镜像
    # 参数设计 L=2Z0tan(φ/2)/ω₀、C=sinφ/(ω₀Z0)、截止 f_c=f₀/sin(φ/2)；
    # 单网络/N 位级联双路线+量化 RMS=LSB/√12+开关插损与 pa_arch 同章衔
    # 接）；实现 doa_crb.py+phase_shifter.py 原位扩展；锚树
    # tests/unit/test_aurora_d_core9.py（naive N×N Slepian-Bangs/模态
    # S21/ABCD 数值级联三族第二路线+退化回归钉+域拒绝）
    "doa_crb_stochastic", "schiffman_phaser", "switched_network_phaser",
}

# W1⑨（2026-09-16 用户口径）：实验态计算器分表——自动归纳（符号回归）公式
# 一律 experimental=True 入库但默认关。EXPECTED 断言 names() **默认排除**；
# include_experimental=True 才含本表（默认列/默认跑都不过这道开关）。
EXPERIMENTAL_EXPECTED = {
    # E13 patch 基模谐振候选公式（，51 点归纳，vs HJ 0.765%）
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


# ─── 工具箱分组 + 中文名结构（aurora72 A2-A，2026-10-11）─────────────────────

def test_group_table_covers_all_keys_zero_leak_zero_dup():
    """分组单源表（CALC_GROUP_TABLE）对注册表键全集（含实验键）零漏零重。

    表外键运行时不报错（落 DEFAULT_CALC_GROUP="其他"），但本测试会把缺键
    点名——新键注册必须同步分组表（与 #231 注册表消费者同纪律）。
    """
    from rfauto.core.calculators import (
        CALC_GROUP_ORDER,
        CALC_GROUP_TABLE,
        DEFAULT_CALC_GROUP,
    )

    all_keys = set(CALCULATOR_REGISTRY.names(include_experimental=True))
    mapped = list(CALC_GROUP_TABLE)
    assert len(mapped) == len(set(mapped)), "表内键重复"
    assert set(mapped) == all_keys, "表与注册表键集不等（漏/多）"
    assert set(CALC_GROUP_TABLE.values()) == set(CALC_GROUP_ORDER), \
        "组名封闭于组序表"
    assert DEFAULT_CALC_GROUP not in CALC_GROUP_TABLE.values(), \
        "缺省组不占表（表外键才落缺省组）"


def test_describe_group_field_all_keys():
    """describe 每键带 group（键序在 experimental 之后）；样本组名断言。"""
    from rfauto.core.calculators import (
        CALC_GROUP_ORDER,
        DEFAULT_CALC_GROUP,
    )

    rows = CALCULATOR_REGISTRY.describe(include_experimental=True)
    assert all(r["group"] in {*CALC_GROUP_ORDER, DEFAULT_CALC_GROUP}
               for r in rows)
    by_name = {r["name"]: r for r in rows}
    assert by_name["microstrip_analysis"]["group"] == "传输线正反解"
    assert by_name["albersheim_detection_snr"]["group"] == "雷达"
    assert by_name["chebyshev_prototype"]["group"] == "滤波器与耦合矩阵"
    assert by_name["patch_f0_symbolic_e13"]["group"] == "实验"
    assert all({"name", "description", "experimental", "group", "params"}
               <= set(r) for r in rows)


def test_group_explicit_spec_overrides_table():
    """CalculatorSpec.group 显式声明优先于单源表；空串缺省走表/落"其他"。"""
    from rfauto.core.calculators import CalculatorSpec

    scratch = CalculatorRegistry()
    scratch.register(CalculatorSpec(
        name="a2a_group_override_stub", description="scratch 占位",
        func=lambda **kwargs: {"ok": True}, params=(), required=(),
        group="自定义组"))
    scratch.register(CalculatorSpec(
        name="a2a_group_default_stub", description="scratch 占位",
        func=lambda **kwargs: {"ok": True}, params=(), required=()))
    groups = {c["name"]: c["group"] for c in scratch.describe()}
    assert groups["a2a_group_override_stub"] == "自定义组"
    assert groups["a2a_group_default_stub"] == "其他"


def test_service_group_order_envelope():
    """list_calculators 信封 group_order=组序（缺省组"其他"殿后，UI
    optgroup 单源透传）。"""
    from rfauto.core.calculators import CALC_GROUP_ORDER, DEFAULT_CALC_GROUP

    env = list_calculators()
    assert env["group_order"] == [*CALC_GROUP_ORDER, DEFAULT_CALC_GROUP]
    assert env["group_order"][-1] == "其他"
    import json
    json.dumps(env, ensure_ascii=False)  # JSON 进出契约


def test_calc_zh_name_extraction_all_keys():
    """UI calcZhName 提取规则（description 冒号前首段含 CJK 且 ≤24 字符）
    对全键成立（#247 口径=单源 len(EXPECTED)+实验表，不再死数）——下拉中
    文名全部由 description 自带（R5 §① 根治），不再依赖 CALC_ZH 兜底表/
    裸 key 展示。"""
    import re

    rows = CALCULATOR_REGISTRY.describe(include_experimental=True)
    assert len(rows) == len(EXPECTED) + len(EXPERIMENTAL_EXPECTED)
    has_cjk = re.compile(r"[\u4e00-\u9fff]")
    bare = []
    for r in rows:
        head = re.split(r"[：:]", str(r["description"] or ""))[0].strip()
        if not (head and has_cjk.search(head) and len(head) <= 24):
            bare.append(r["name"])
    assert bare == []


def test_patch_through_fanout_complete():
    """A2-P2-3 钉：facade patch 扇出清单完整性（棘轮，只收不放）。

    凡 tests 面以 ``monkeypatch.setattr(calculators, "<name>", ...)`` patch
    的 facade 名，必须登记进 ``_PATCH_THROUGH`` 且扇出目标恰=该名在
    calc_families 包内的全部模块级绑定面（定义模块 + 全部 by-value 引用
    方）——否则"patch facade + 调 CALC 键"组合会静默走未 patch 的生产
    路径（#116 家法：名字绑定遮蔽）；扇出过时/少登同样红。"""
    import ast
    from collections import defaultdict

    from rfauto.core import calc_families as pkg
    from rfauto.core import calculators as calc_mod

    # 1) calc_families 各模块的模块级绑定面（def/class/assign/相对 import）
    bindings: dict[str, set[str]] = defaultdict(set)
    for py in sorted(Path(pkg.__file__).parent.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level >= 1:
                for a in node.names:
                    bindings[a.asname or a.name].add(py.stem)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)):
                bindings[node.name].add(py.stem)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        bindings[t.id].add(py.stem)

    # 2) tests 面 patch 的 facade 名（AST 扫 monkeypatch.setattr(calculators,...)）
    patched: dict[str, str] = {}
    for py in sorted(Path(__file__).parent.glob("test_*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "calculators"
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                continue
            if getattr(node.func, "attr", "") != "setattr":
                continue
            patched.setdefault(str(node.args[1].value), py.name)

    assert patched, "patch 扫描失效（tests 面应有 calculators patch 站）"
    through = dict(calc_mod._PATCH_THROUGH)
    # 本笔修复显式回归面：既有 5 个 patch 名全部登记（A2-P2-3：2/5→5/5）
    assert {"_cm_polish", "_cm_poly_max_err", "_cm_reduce_arrow",
            "_cm_reduce_folded", "_cm_transversal_exact"} <= set(through)
    # 棘轮：每个 patch 名必须登记且扇出=全部绑定面
    for name, src in sorted(patched.items()):
        assert name in through, (
            f"tests patch 的 facade 名 {name!r}（{src}）未登记 "
            f"_PATCH_THROUGH——'patch facade + 调 CALC 键'会静默走未 patch "
            f"生产路径（A2-P2-3）；新 patch 名入册或改经 facade 调用")
        expect = bindings.get(name, set())
        assert set(through[name]) == expect, (
            f"_PATCH_THROUGH[{name!r}]={sorted(through[name])} 与实际绑定面 "
            f"{sorted(expect)} 不一致（by-value 引用方增减未同步扇出）")
