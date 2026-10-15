# 计算器注册表参考

> `CALCULATOR_REGISTRY` 实注册 **204** 个（含实验键共 **205** 个；实验键默认不列、需显式开关）。与 `scripts/check_numbers.py` 的 `count_calculators()`/`count_calculators_all()` 构建时逐位互证。运行入口 `rfauto calc list` / `rfauto calc run <名> -p k=v`。本页由 `scripts/build_docs_pages.py` 机读生成，勿手改。

数值只在确定性内核（LLM/agent 永不产生物理数字）；每键的输入表由 `tests/unit/test_physics_invariants.py` 物理不变量门逐键消费。

## albersheim_detection_snr

检测因子三量互算：Albersheim 检测因子经验式三量互算（Swerling 0 非起伏、线性检波、N 脉冲非相干积累）：A=ln(0.62/Pfa)、B=ln(Pd/(1−Pd))，SNR_dB=−5lg(N)+(6.2+4.54/√(N+0.44))·lg(A+0.12AB+1.7B)（原式 N+0.44 口径——√(N+1) 简化形与 Marcum 精确解差 0.8 dB，不采用）。Pfa/Pd/SNR 三给二解一（缺 SNR 前向；缺 Pd/Pfa 宗量线性闭式反解），三量全给显式拒绝（超定）；附相干检测参考 SNR（Q 反解界）。锚：Pfa=1e-6/Pd=0.9/N=1→13.1145dB vs Marcum 精确 13.1835dB（Δ=0.069dB≤0.1dB）。拟合窗 Pd∈[0.1,0.9]/Pfa∈[1e-7,1e-3]，窗外 extrapolated=True 如实标注；SW1-4 起伏目标不在本式覆盖（如实不做）。出处 Albersheim 1981 IEEE Trans.AES；Skolnik 3ed/Richards FRSP 转引

| 参数 | 说明 | 必填 |
|---|---|---|
| `pfa` | float - 虚警概率（0<Pfa<1；与 pd/snr_db 三给二解一） | 否 |
| `pd` | float - 检测概率（0<Pd<1；与 pfa/snr_db 三给二解一） | 否 |
| `snr_db` | float dB 单脉冲检测 SNR（与 pfa/pd 三给二解一） | 否 |
| `n_pulses` | float - 非相干积累脉冲数 N（≥1 整数，默认 1） | 否 |

## allan_deviation

Allan偏差分析：MS-5 Allan 偏差（时钟稳定度，IEEE 1139/952 口径）：分数频率 y 序列（kind='freq'）或相位时间误差 x 序列秒（kind='phase'，y=Δx/τ0）→ 重叠（缺省）/非重叠 Allan 偏差序列 {tau_s, adev, adev_error, n_terms}（tau 缺省倍频程网格；越界 tau 裁剪）。label=全段 log-log 斜率按 IEEE 1139 Table 1 分类（pm/white_fm/flicker_fm/random_walk_fm/linear_drift/unknown；白相与闪相同斜率 −1 不可分辨，分辨走 core classify_joint 用 MDEV −3/2 vs −1，或频域 S_phi 斜率走 clock_noise 互检）。斜率分类是全段摘要启发式（≥2 个正 ADEV 点才给出，否则 'insufficient'）；误差棒=独立差分近似 EDF（Greenhall-Howe 修正未实现，UNVERIFIED，只作量级参考）。短序列/非有限值/非等间隔时间戳显式拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `samples` | list[float] 分数频率偏差 y_k 或相位时间误差 x_k（秒）序列（≥3 点等间隔） | 是 |
| `rate_hz` | float Hz 采样率（>0，τ0=1/rate_hz） | 是 |
| `kind` | str 'freq'\|'phase'（默认 'freq'） | 否 |
| `estimator` | str 'overlapping'\|'nonoverlap'（默认 'overlapping'） | 否 |
| `taus` | list[float] 可选取样时间数组秒（全正；缺省倍频程网格） | 否 |

## array.bayliss_weights

Bayliss差波束权：RB-ALG-1 Bayliss 差波束权向量（单脉冲低副瓣差方向图四参数闭式；Bayliss 1968 BSTJ 47(4):623-650 原文数表，Doerry SAND-2025-07335 转载双源锚定）。2N 元偶数阵奇对称实权，PSLL 回收=声明电平；文献值回收/恒等式门见 test_w3_e_array_synth

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_elements` | int 单元数（偶数，≥8；差波束奇对称 2N 元阵） | 是 |
| `sidelobe_level_db` | float 副瓣电平声明值 dB（负值，相对差主瓣峰） | 是 |
| `nbar` | int 等纹波零点对数（缺省 0=自动 min(7, N/2)；须 4 至 N/2） | 否 |

## array.quantized_milp

量化阵列MIP综合：RB-ALG-2 量化约束阵列综合=MIP 精确解（scipy.milp/HiGHS，零新依赖）。移相器 b-bit/衰减器离散档/阵元开关 二进制选择+方向图约束线性化；目标=线性化峰值副瓣场，主瓣相干增益损失带内；回代 PSLL=真非线性口径；码字直连 firmware beam_codeword_table/beam_backsub_audit。不可行如实 ok=False（spec §7.4 风险③）

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_elements` | int 单元数（2-128；16-64 秒-分级） | 是 |
| `sidelobe_level_db` | float 副瓣电平声明值 dB（负值；亦定参考锥削） | 是 |
| `n_bits` | int 移相器位宽 1-8（码本 2^b；64 元建议 ≤4） | 是 |
| `atten_steps` | int 衰减器档数 G（≥1；1=无衰减自由度） | 是 |
| `atten_step_db` | float 每档衰减 dB（缺省 0.5） | 否 |
| `element_switch` | bool 是否启用阵元开关（缺省 False） | 否 |
| `spacing_lambda` | float 单元间距 d/lambda（缺省 0.5） | 否 |
| `scan_u0` | float 扫描方向余弦（缺省 0 侧射） | 否 |
| `max_mainlobe_loss_db` | float 主瓣相干增益损失上限 dB（缺省 1.0） | 否 |
| `mainlobe_half_u` | float 主瓣半宽（方向余弦；缺省=参考锥削第一零点自动探测，探测失败回退 1.6×均匀阵第一零点） | 否 |
| `n_sidelobe_points` | int 副瓣约束网格点数（缺省 min(720, max(60, 6N))） | 否 |
| `n_tangent` | int 切平面旋转角数 K（缺省 16，保守带约 0.166dB） | 否 |
| `mip_rel_gap` | float MIP 相对间隙（缺省 1e-4，与内核 options 同源） | 否 |
| `time_limit_s` | float 求解墙钟上限 s（缺省 0=不设；G15 确定性钉要求 fixture 规模瞬完） | 否 |

## array.schelkunoff_nulls

Schelkunoff零点权：RB-ALG-1 Schelkunoff 单位圆零点置放权向量（Schelkunoff 1943 BSTJ 22:80-107）。给 n-1 个零方向（方向余弦）得阵列多项式系数=激励；全自然零点=均匀阵恒等式钉见 test_w3_e_array_synth

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_elements` | int 单元数（≥2；零方向数须=n-1） | 是 |
| `null_positions` | array 零方向方向余弦序列（任意实数，按 2π wrap） | 是 |
| `spacing_lambda` | float 单元间距 d/lambda（缺省 0.5） | 否 |

## array.villeneuve_weights

Villeneuve权向量：RB-ALG-1 Villeneuve 和波束权向量（Taylor 零点的离散阵精确修正；Villeneuve 1984 IEEE TAP 32(10):1089-1093）。nbar=1 退化为均匀阵；PSLL 收敛带与单调钉见 test_w3_e_array_synth

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_elements` | int 单元数（≥2 且 ≥2·nbar） | 是 |
| `sidelobe_level_db` | float 副瓣电平目标 dB（负值） | 是 |
| `nbar` | int 内侧修正零点边界（缺省 4；nbar=1 均匀阵） | 否 |

## attenuator_bridged_t

桥 T 型电阻衰减器：衰减量+Z0 → 桥/并电阻（串臂固定 Z0；节点导纳级联校验有单测）

| 参数 | 说明 | 必填 |
|---|---|---|
| `attenuation_db` | float dB 衰减量（>0） | 是 |
| `z0_ohm` | float Ω 系统阻抗 | 是 |

## attenuator_pi

π 型电阻衰减器：衰减量+Z0 → 端电阻（ABCD 校验有单测）

| 参数 | 说明 | 必填 |
|---|---|---|
| `attenuation_db` | float dB 衰减量（>0） | 是 |
| `z0_ohm` | float Ω 系统阻抗 | 是 |

## attenuator_t

T 型电阻衰减器：衰减量+Z0 → 端电阻（ABCD 校验有单测）

| 参数 | 说明 | 必填 |
|---|---|---|
| `attenuation_db` | float dB 衰减量（>0） | 是 |
| `z0_ohm` | float Ω 系统阻抗 | 是 |

## availability_margin

可用度裕量换算：AP-7 可用性↔衰落裕量双向换算+双模型同参差异带（平均最差月）：Vigants-Barnett 简式（Barnett 1972 BSTJ 51(2) §6.3 一手核，P=c·(f/4)·1e-5·D_mi³·10^(−F/10)，climate 四档 4/1/0.5(UNVERIFIED)/0.25）vs ITU-R P.530-18 正式式（§2.3.1 式(7) 文本层逐位核，K·d^3.51·(f²+13)^0.447·10^(几何/气象指数−A/10)）。availability_percent 与 fade_margin_db 二选一；diff_band 如实记录两式差异（不设对错门）；P.530 侧 log10_k 缺省 −2.0 为典型温带占位 UNVERIFIED（LogK.csv 网格零捆绑）

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 载波频率（>0） | 是 |
| `d_km` | float km 路径长度（>0；P.530 侧 d≤5km 记 0 中断） | 是 |
| `climate` | str 'over_water'/'average'/'rough'/'dry_mountain'（默认 'average'，V-B 侧 c 档） | 否 |
| `availability_percent` | float (0,100) 开区间目标时间可用度（与 fade_margin_db 二选一） | 否 |
| `fade_margin_db` | float dB 衰落裕量（≥0；与 availability_percent 二选一） | 否 |
| `log10_k` | float P.530-18 地理气候因子 K[%] 的常用对数（默认 -2.0 典型温带占位 UNVERIFIED） | 否 |
| `eps_p_mrad` | float mrad 路径倾角 \|εp\|（≥0，默认 10.0） | 否 |
| `hc_m` | float m 平均路径地形净空 hc（默认 500.0） | 否 |
| `h_l_m` | float m 较低天线海拔 hL（默认 100.0） | 否 |
| `vsr` | float 亚折射参数 v_sr（≥0，默认 0.0=无亚折射修正） | 否 |

## balanced_pair_sparams

平衡对S参数合成：平衡放大器对 S 参数合成（90° 杂交 Kurokawa 口径，G11）：两管单管S 参数 → 平衡对合成 S 参数。恒等式：S11,bal=(S11a−S11b)/2（同管→ 严格 0 反射对消）、S21,bal=(S21a+S21b)/2（同管 → 增益=单管）、S22,bal 输出侧同恒等式。B 管参数缺省=A 管值（同管口径）。失配容忍度字段：单管失效 → 输入回损 6.0206 dB 上界+增益 −6.0206 dB（失效不灾难性失配）；同幅反射管对相位容差 Δφ_max=2·arcsin(10^(−RL/20)/Γ)。hybrid_il_db 为每只混合器插损（缺省 0=理想混合器；增益按 −2×IL 修正）。守卫：反射幅值∈[0,1]

| 参数 | 说明 | 必填 |
|---|---|---|
| `s11a_mag` | float A 管输入反射线性幅值（[0,1]） | 是 |
| `s21a_db` | float dB A 管增益 \|S21\|（dB，正=放大） | 是 |
| `s11a_deg` | float deg A 管 S11 相位（缺省 0） | 否 |
| `s21a_deg` | float deg A 管 S21 相位（缺省 0） | 否 |
| `s11b_mag` | float B 管输入反射幅值（缺省=A 管：同管口径） | 否 |
| `s11b_deg` | float deg B 管 S11 相位（缺省=A 管） | 否 |
| `s21b_db` | float dB B 管增益（缺省=A 管） | 否 |
| `s21b_deg` | float deg B 管 S21 相位（缺省=A 管） | 否 |
| `s22a_mag` | float A 管输出反射幅值（缺省=s11a_mag：只回损一手数据时的镜像口径，note 如实标注） | 否 |
| `s22a_deg` | float deg A 管 S22 相位（缺省=s11a_deg） | 否 |
| `s22b_mag` | float B 管输出反射幅值（缺省=B 管 S11 同口径） | 否 |
| `s22b_deg` | float deg B 管 S22 相位（缺省=B 管 S11 同口径） | 否 |
| `hybrid_il_db` | float dB 每只 90° 混合器插损（≥0，缺省 0=理想；增益按 −2×IL 修正） | 否 |
| `target_rl_db` | float dB 相位容差字段的目标回损（>0，缺省 20） | 否 |

## bethe_hole_coupler

Bethe孔耦合器：Bethe 孔定向耦合器（矩形波导公共宽壁中心圆孔，双向单键）：①分析——给孔径 hole_diameter_mm → 耦合度/方向性/隔离/设计频率（Bethe 极化率 αe=2r³/3、αm=4r³/3 + E/M 支路 Z10 加减结构，f=c0/(√2·a) 处隔离向严格相消=方向性极值；反向 reverse 耦合器）；②综合——给目标 coupling_db → 反解孔径（c∝d³）并回代自洽。wall_thickness_mm>0 启用 Cohn 修正（孔口共振因子 1/(1−(f/f_res)²)+截止衰减 e^(−αt)，f_res 取圆波导 TE11/TM01 截止常数 1.706d/1.305d口径）。守卫：f 距 TE10 截止 <5% 拒绝（λg 发散）；d≤0.8b 且 d≤λ0/3（小孔假设）；耦合度越可达窗显式报错。孔位输出=宽壁中线 s=a/2 + 多孔阵 λg/4 间距口径。近似层级：一阶小孔/单模/弱耦合。

| 参数 | 说明 | 必填 |
|---|---|---|
| `wr_name` | str - WR 波导型号（如 'WR-90'，rw_tables 单源；与 a_mm/b_mm 二选一） | 否 |
| `a_mm` | float mm 宽边内尺寸（显式口径，须与 b_mm 同给） | 否 |
| `b_mm` | float mm 窄边内尺寸 | 否 |
| `freq_ghz` | float GHz 中心频率 | 是 |
| `hole_diameter_mm` | float mm 圆孔直径（分析方向入参） | 否 |
| `coupling_db` | float dB 目标耦合度（综合方向入参，正 dB） | 否 |
| `wall_thickness_mm` | float mm 公共壁厚（>0 启用 Cohn 修正，缺省 0） | 否 |

## blocking_budget

阻塞预算：MT-4 件 3 阻塞/信道选择性预算（round17 MT-4，杂散面复用 core/cascade.spur_search，链路基线复用 cascade_budget——既有语义零改动）。三面：①倒易混频 N_rm=P_blk@mixer+L(f_offset)+10log10(B) → desense=10log10(1+10^((N_rm−N_floor)/10))（等效 NF 抬升=灵敏度恶化）；②线性度 p1db_margin=链路输入 P1dB−阻塞电平（无 p1db 级→None 不判）；③阻塞×本振 |m·f_blk±n·f_LO| 落带杂散（fundamental 不计；hazard='high' 落带判负）。pass=三面合取；L(f_offset) 为标量（裙边分段积分不在此层，可走 clock_noise 幂律谱合成取值）；filter_rejection_db=阻塞偏移处前端聚总选择性

| 参数 | 说明 | 必填 |
|---|---|---|
| `stages` | list[dict] 接收链级表（schema 同 cascade_budget：type/gain_db/nf_db/iip3_dbm/p1db_dbm/bw_hz…；NF/P1dB/噪声底走其聚总） | 是 |
| `bw_hz` | float 信道噪声带宽 Hz（>0） | 是 |
| `blocker_dbm` | float 链路输入处阻塞电平 dBm | 是 |
| `f_blocker_hz` | float 阻塞频率 Hz（>0） | 是 |
| `f_lo_hz` | float 本振频率 Hz（>0） | 是 |
| `lo_phase_noise_dbc_hz` | float 阻塞偏移处 LO 单边带相噪 dBc/Hz（标量） | 是 |
| `f_rx_hz` | float 期望信道频率 Hz（if_center_hz 缺省时 IF=\|f_rx−f_lo\|；两者必给其一） | 否 |
| `if_center_hz` | float 显式信道 IF Hz（≥0，缺省由 f_rx 解析） | 否 |
| `filter_rejection_db` | float 前端聚总选择性 dB（≥0，默认 0） | 否 |
| `desense_limit_db` | float desense 判过限值 dB（≥0，默认 3.0） | 否 |
| `max_order` | int 杂散最大阶 m+n（≥1，默认 7） | 否 |
| `t_kelvin` | float 热噪声温度 K（>0，默认 290） | 否 |

## ca_cfar_threshold

CFAR门限因子：CA-CFAR（单元平均，单脉冲）虚警与门限因子闭式：Pfa=(1+β)^(−N) → β=Pfa^(−1/N)−1（对参考窗求和）、α=N·(Pfa^(−1/N)−1)（对参考窗平均，门限 T=α·均值）。可选 snr_db 附 Swerling 1 目标检测概率闭式 Pd=(1+β/(1+S))^(−N)。保护单元只改窗几何不进 α。锚：N=16/Pfa=1e-4→α=12.4525；闭式回代逐位自洽 + 蒙特卡洛独立裁判（测试钉）。出处 Richards FRSP 2ed ch.6（指数噪声单元标准结果）

| 参数 | 说明 | 必填 |
|---|---|---|
| `pfa` | float - 目标虚警概率（0<Pfa<1） | 是 |
| `n_ref` | float - 参考窗单元数 N（≥1 整数；典型 8~50，保护单元不计入） | 是 |
| `snr_db` | float dB 单脉冲 SNR（可选；给出则附 Swerling 1 检测概率闭式） | 否 |

## cascade_budget

DP-5 级联预算：stage 列表 → 总增益/Friis NF/IIP3·OIP3 级联/P1dB(经验幂和)/噪声底/SFDR/灵敏度/链路裕量。stage schema type∈{amp,mixer,filter,atten,cable}；无源级 NF 缺省=插损（T0）；skrf 真实插损解析在 service 层

| 参数 | 说明 | 必填 |
|---|---|---|
| `stages` | list[dict] 级表（顺序=信号流向；type/gain_db/nf_db?/iip3_dbm?/p1db_dbm?/bw_hz?） | 是 |
| `snr_min_db` | float dB 解调最小 SNR（默认 10） | 否 |
| `rx_power_dbm` | float dBm 接收功率（可选，给定时输出链路裕量） | 否 |
| `bw_hz` | float Hz 系统噪声带宽（缺省取末级 bw_hz，皆无则显式报错） | 否 |
| `t_kelvin` | float K 等效热噪声温度（默认 290） | 否 |

## cat_critique

顺序调谐判读：Dishal 顺序调谐确定性 critique（与 autotune_service.critique_point 同型 issues+typed fixes，无 LLM，数值只在内核 #7）：τ(f) 峰数=指纹（1 峰=单腔接入步→Qe；2 峰=相邻耦合步→k 拆分精确式 k=(f₂²−f₁²)/(f₂²+f₁²)）；峰位偏=失谐方向。C 系数钉死（合成回收裁决，模块头注释）：S21 透射泄漏 C=2、S11 反射全通 C=4。k 计算注入点：df6 P1 k_split_pair 注册后由服务层经 k_split_fn 消费，计算器面保持内部精确式（显式拒绝外部回调串入）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | array GHz 频率轴 | 是 |
| `s21` | array 复 S21（透射口径，与 s11 恰给其一） | 否 |
| `s11` | array 复 S11（反射口径，C=4） | 否 |
| `f0_ghz` | float GHz 目标中心频率 | 是 |
| `fbw` | float 相对带宽（0<fbw≤1） | 是 |
| `target_matrix` | array (N+2)×(N+2) 目标耦合矩阵 | 是 |
| `current_params` | object 当前可调参数名→值（缺省=只报物理偏差） | 否 |
| `bounds` | object 参数名→[下,上]（缺省=不限） | 否 |
| `max_step_pct` | float 单步限幅（默认 0.2） | 否 |
| `tol` | float 相对容差（默认 0.1） | 否 |

## cavity_perturbation_shift

腔体微扰法：矩形腔 TE101 腔体微扰频移（Pozar §6.7 / Slater 定理一阶）：腔尺寸+样品（轴对齐盒精确解析，或任意三角网格体素积分）→ f0、Δf/f0。小样品极限：E 极大点介质 −2(εr−1)Vs/Vc、金属 −2Vs/Vc（下调）；H 极大区金属符号翻正

| 参数 | 说明 | 必填 |
|---|---|---|
| `a_mm` | float mm 腔 x 边长（>0） | 是 |
| `b_mm` | float mm 腔 y 高（>0，进 Vc 与场权积分） | 是 |
| `d_mm` | float mm 腔 z 长（>0） | 是 |
| `sample_box_mm` | array [x0,y0,z0,x1,y1,z1] 轴对齐样品盒（mm，腔内） | 否 |
| `sample_triangles_mm` | array (n,3,3) 样品水密三角网格（mm，体素路线） | 否 |
| `sample_eps_r` | float - 样品相对介电常数（>1；缺省=金属微扰路线） | 否 |
| `voxel_mm` | float mm 体素步长上限（网格路线；缺省自动=样品最大边/24） | 否 |

## cavity_unloaded_q

谐振器无载Q：同轴腔无载 Q 三方合成（趋肤电阻口径，Pozar §6.6）：Rs=√(πfμ/σ) → 导体 Qc=ωμ·ln(b/a)/(Rs·(1/a+1/b))（场积分法与 β/(2α) 衰减关系双路自洽闭式，测试互证 ≤1e-12）；满充均匀介质 Qd=1/tanδ（tanδ=0 如实返 null）；1/Qu=1/Qc+1/Qd 串联合成。单调性（测试钉）：Qu ≤ min(Qc,Qd)、tanδ→0 时 Qu→Qc、Qc∝√σ。锚：Cu σ=5.8e7、1GHz、a=1mm/b=2.301mm 空气 50Ω 口径 Qc≈5.56e2 量级

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 工作频率（>0） | 是 |
| `conductivity_s_per_m` | float S/m 导体电导率（>0；Cu=5.8e7） | 是 |
| `a_mm` | float mm 内导体半径（>0） | 是 |
| `b_mm` | float mm 外导体内半径（>a_mm） | 是 |
| `epsilon_r` | float 腔内介质相对介电常数（≥1，缺省 1；满充均匀假定） | 否 |
| `mu_r` | float 导体/介质相对磁导率（>0，缺省 1 非磁性） | 否 |
| `tan_delta` | float 介质损耗角正切（≥0，缺省 0=无耗，Qd 返 null） | 否 |

## cdr_jitter_mask

抖动容限曲线：DR-8 CDR 抖动容限 JT 曲线+mask 余量（线性相位模型，JT0=1 UI 归一）：order='first' 走 H(s)=ωc/(s+ωc)，JT=√(ω²+ωc²)/ω（锚 JT(fc)=√2、高频平台→1、低频 −20dB/dec）；order='second' 走二阶 H(s)=ωn²/(s²+2ζωn·s+ωn²)（peaking |H|max=1/(2ζ√(1−ζ²))，ζ≥1/√2 无峰如实=1）。可选 mask=[[f,UI],...]（调用方按所引标准给入点列，对数-线性插值）：逐点 margin_db=20(log10 mask−log10 JT)，worst 点+verdict（pass/fail）。域守卫：freq 全正（JT 在 f→0 发散不外推直流）、ζ∈(0,2)、mask 点全正

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_hz` | list[float] Hz 频率点列（>=2 点，全正；升序推荐） | 是 |
| `order` | str 'first'/'second'（缺省 'first'） | 否 |
| `fc_hz` | float Hz 一阶环路角频（order='first' 必填） | 否 |
| `fn_hz` | float Hz 二阶自然频率（order='second' 必填） | 否 |
| `zeta` | float 阻尼比（order='second' 必填，(0,2)） | 否 |
| `mask` | list[[f_hz, ui]] 可选标准 mask 点对（>=2 点，全正） | 否 |

## chebyshev_prototype

切比雪夫原型：广义切比雪夫原型（chebyshev_g 等价形式）：阶数+回损+传输零点 → F/P/E 多项式系数与反射零点（Cameron 口径，S11=F/E, S21=P/(εE)）

| 参数 | 说明 | 必填 |
|---|---|---|
| `order` | int - 滤波器阶数（≥1） | 是 |
| `rl_db` | float dB 带内回波损耗纹波（>0） | 是 |
| `transmission_zeros` | array 归一化低通传输零点 \|Ω\|>1 列表（±ω 成对口径，缺省=全极点） | 否 |

## chebyshev_prototype_asym

广义切比雪夫原型（显式 TZ 集合口径）：阶数+回损+完整 TZ 列表（每个 Ω 单独列出）→ F/P/E 多项式与反射零点。±Ω 共轭闭合输入走实系数 s 域谱分解（与 chebyshev_prototype 数值一致 ≤1e−9）；非闭合（真·非对称）输入走复系数谱分解（推广 Feldtkeller 的 Hurwitz 半边），轴上幺正性保持、响应 Ω→−Ω 不再对称；可继续综合为复对称 N+2 耦合矩阵（见 coupling_matrix_synthesize_explicit）

| 参数 | 说明 | 必填 |
|---|---|---|
| `order` | int - 滤波器阶数（≥1） | 是 |
| `rl_db` | float dB 带内回波损耗纹波（>0） | 是 |
| `transmission_zeros` | array 显式 TZ 列表（每项一个 Ω；成对输入=实系数路径，非成对输入=复系数路径） | 是 |

## chebyshev_refl_fn

全极点切比雪夫反射函数：n+rz_db+Ω → |S11|/|S21|（闭式 |S11|=ε|T_n(Ω)|/√(1+ε²T_n²)，带边 Ω=1 处纹波峰值=−RL）

| 参数 | 说明 | 必填 |
|---|---|---|
| `n` | int - 阶数 | 是 |
| `rz_db` | float dB 带内回损纹波（>0） | 是 |
| `omega` | array 归一化低通频率轴 | 是 |

## chipless_tag_decode

chipless RFID 扫频谱→码字反解：逐槽窗内谷深（max−min |S21|dB）>阈值→1；给 codebook 时附最近合法码字与汉明距离；窗内采样<2 的槽如实记 unresolved（#314 掩码纪律同源：不猜）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_hz` | list[float] 扫频轴（Hz，单调递增） | 是 |
| `s21_db` | list[float] \|S21\|（dB，与 freq_hz 等长） | 是 |
| `f_start_hz` | float Hz 扫描带下缘 | 是 |
| `f_stop_hz` | float Hz 扫描带上缘 | 是 |
| `n_slots` | int - 编码槽位数（≥2） | 是 |
| `codebook` | list[list[int]] 合法码字表（可选，给则报汉明距离） | 否 |
| `depth_threshold_db` | float dB 谷深门限（默认 3） | 否 |
| `window_frac` | float - 谷检窗宽（×槽距，≤1，默认 0.8） | 否 |

## chipless_tag_encode

chipless RFID 实测谐振频点→码字：每频点映最近槽位（容差=tol_frac×槽距）；越容差/带外/两频点同槽显式报错（不静默丢位）

| 参数 | 说明 | 必填 |
|---|---|---|
| `resonance_freqs_hz` | list[float] 检测到的谐振频率（Hz） | 是 |
| `f_start_hz` | float Hz 扫描带下缘 | 是 |
| `f_stop_hz` | float Hz 扫描带上缘 | 是 |
| `n_slots` | int - 编码槽位数（≥2） | 是 |
| `tol_frac` | float - 映射容差（×槽距，默认 0.4） | 否 |

## chipless_tag_plan

无芯片RFID规划：chipless RFID 码字→谐振器组规划（等 Q 假设深谷）：code 槽位 0/1 →各谐振器频率（槽中心）/R=x/Q/预期谷深 20lg(2R/(2R+Z0))/无耗近似带宽 f·Z0/(2x)（Matthaei 电抗斜率口径，core/chipless_rfid.py）

| 参数 | 说明 | 必填 |
|---|---|---|
| `code` | list[int] 码字（每槽 0/1，长度=n_slots） | 是 |
| `f_start_hz` | float Hz 扫描带下缘 | 是 |
| `f_stop_hz` | float Hz 扫描带上缘（>f_start） | 是 |
| `q_unloaded` | float - 谐振器无载 Q（统一等 Q，>1） | 是 |
| `slope_ohm` | float Ω 电抗斜率参数 x=ω0·L（统一） | 是 |
| `z0_ohm` | float Ω 读出线特性阻抗（默认 50） | 否 |

## circular_cavity_mode_chart

圆柱腔模式图数据：归一化频率 f·2πa√εr/c₀=√(x²+(pπa/L)²) 随长径比 r=l/(2a) 的曲线族（TM010 平坦、p≥1 模式单调降——单调性测试钉），逐格点主模排序+主模切换交叉点（相邻网格变号对二分求根；TE111/TM010 交叉 r≈1.0154 测试侧独立常数式）。与 spectrum 键单源同式（同根值helper），测试做跨键一致性互证

| 参数 | 说明 | 必填 |
|---|---|---|
| `modes` | list[str] 模式名列表（形如 'TM010'；缺省 TM010/TE111/TM011/TE021/TE012/TM111/TE011/TM021） | 否 |
| `l_over_2a_min` | float 长径比下缘（>0，<max，缺省 0.2） | 否 |
| `l_over_2a_max` | float 长径比上缘（≤20，缺省 3.0） | 否 |
| `n_points` | int 网格点数（2..401，缺省 61） | 否 |
| `epsilon_r` | float 相对介电常数（≥1，缺省 1；归一化频率已约去） | 否 |

## circular_cavity_mode_q

圆柱腔任意 TE/TM_mnp 模式无载 Q：导体微扰口径 Q=ωU/P_c（板坐标系场表达式闭式化简：TE 用 D=1−m²/x'² 恒等式、TM 用 I2x=x²J_{m+1}²/2；TM010 极限 (ηk0a/2Rs)·L/(L+a) 测试钉）+ 数值积分路线互证（q_xcheck_rel_dev<1e-9，推导失配即红）+ Ue/Um≈1 谐振定理自检；介质 Q=1/tanδ（tanδ=0 返 null），1/Qu=1/Qc+1/Qd 串联合成。锚：TE011>TE111（无端壁环流高 Q 性质）；Qc∝1/√σ

| 参数 | 说明 | 必填 |
|---|---|---|
| `mode_type` | str 'TE' 或 'TM' | 是 |
| `m` | int 方位序号（≥0；TM010 即 m=0） | 是 |
| `n` | int 径向序号（≥1） | 是 |
| `p` | int 轴向序号（TE ≥1——p=0 非物理显式拒绝；TM ≥0） | 是 |
| `radius_mm` | float mm 腔半径（>0） | 是 |
| `length_mm` | float mm 腔长（>0） | 是 |
| `conductivity_s_per_m` | float S/m 导体电导率（>0；Cu=5.8e7） | 是 |
| `epsilon_r` | float 腔内均匀填充相对介电常数（≥1，缺省 1） | 否 |
| `mu_r` | float 相对磁导率（>0，缺省 1 非磁性） | 否 |
| `tan_delta` | float 介质损耗角正切（≥0，缺省 0=无耗） | 否 |

## circular_cavity_mode_spectrum

圆柱腔多模谐振谱：TE/TM_mnp Bessel 零点闭式 f=c₀/(2π√εr)·√((x/a)²+(pπ/L)²)（TE 用 J_m' 零点 p≥1，TM 用 J_m 零点 p≥0/TM010 经典例），给半径/长度/频段 → 带内模式频率列表（排序）+全谱主模标识（计算判读非假定：l<2a→TM010、l>2a→TE111 经典口径复现）+TE11 波导截止参考 x'_11·c₀/(2πa)。锚：TM010=11.4743GHz@a=10mm；TE011 与 material_characterization 空腔闭式同仓双源；TE011/TM111 简并同频

| 参数 | 说明 | 必填 |
|---|---|---|
| `radius_mm` | float mm 腔半径（>0） | 是 |
| `length_mm` | float mm 腔长（>0） | 是 |
| `f_min_ghz` | float GHz 频段下缘（>0，<f_max_ghz） | 是 |
| `f_max_ghz` | float GHz 频段上缘（>f_min_ghz） | 是 |
| `epsilon_r` | float 腔内均匀填充相对介电常数（≥1，缺省 1） | 否 |
| `max_modes` | int 带内模式数上限（1..500，缺省 200；超限显式拒绝要求收窄频段） | 否 |

## circulator_ideal_sparams

环行器理想 3 口 S 口径：非互易铁氧体件（reciprocal=False 豁免位）sense=cw|ccw 环行方向参数化——环行项 10^(−IL/20)、隔离项 10^(−Iso/20)（None=理想）、对角 10^(−RL/20)（None=理想匹配）；每口无源性一致性守卫（γ²+c²+i²≤1）违约显式拒绝；sense 翻转恒等式 S_ccw=S_cwᵀ；理想极限档回置换矩阵（与 circulator_synthesis SENSE_FORWARD 同布局）

| 参数 | 说明 | 必填 |
|---|---|---|
| `sense` | str 环行方向 cw（1→2→3→1）\|ccw（1→3→2→1），缺省 cw | 否 |
| `il_db` | float dB 环行方向插损 IL（≥0，缺省 0=理想无耗） | 否 |
| `isolation_db` | float dB 反向隔离度 Iso（≥0 或 None=∞ 理想隔离） | 否 |
| `rl_db` | float dB 各口回损 RL（≥0 或 None=理想匹配） | 否 |

## classic_taper_response

经典渐变线频响：线性/指数/三角阻抗剖面逐频小反射理论双路线——闭式（指数 |Γ|=(|δ|/2)|sinc(βL)| / 线性 Ei 指数积分闭式 / 三角 |Γ|=(|δ|/2)sinc²(βL/2π) 首零 βL=2π）+剖面核数值积分交叉互证残差；βL→0 阶跃极限包络 |δ|/2、剖面样本 Z(x)（三角剖面含 Z(½)=√(z1z2) 几何中点）；TEM 均匀口径（v_f 相速因子），色散/高阶模不在口径

| 参数 | 说明 | 必填 |
|---|---|---|
| `z1_ohm` | float Ω 起端阻抗（>0） | 是 |
| `z2_ohm` | float Ω 末端阻抗（>0 且 ≠z1） | 是 |
| `length_mm` | float mm 渐变段物理长度（>0） | 是 |
| `freq_ghz` | array GHz 频率轴（>0） | 是 |
| `profile` | str 剖面白名单 exponential\|linear\|triangular（缺省 exponential） | 否 |
| `v_f` | float 相速因子（0<v_f≤1，缺省 1.0=TEM 空气口径） | 否 |
| `n_quad` | int 交叉互证数值积分点数 101..200001（缺省 20001，奇数时三角剖面 u=½ 尖点恰为采样节点） | 否 |
| `n_profile` | int 剖面样本点数 5..401（缺省 65） | 否 |

## classic_taper_synthesize

经典渐变线综合：给定 ρ_max@f_min 反解最短长度——|Γ(βL)|=ρ_max 在 βL∈(0,4π] 首个变号括根+brentq 精化（三剖面统一，不赌单调段）；βL→0 阶跃极限 |δ|/2 守卫（ρ≥阶跃极限=零长渐变即可满足，显式拒绝）；三角剖面首零 βL=2π（|Γ| 在 (0,2π) 单调降，ρ>0 首根恒 <2π）

| 参数 | 说明 | 必填 |
|---|---|---|
| `z1_ohm` | float Ω 起端阻抗（>0） | 是 |
| `z2_ohm` | float Ω 末端阻抗（>0 且 ≠z1） | 是 |
| `f_min_ghz` | float GHz 通带下限频率（>0；综合点） | 是 |
| `rho_max` | float 通带内允许 \|Γ\| 上限（>0 且 <\|ln(z2/z1)\|/2） | 是 |
| `profile` | str 剖面白名单 exponential\|linear\|triangular（缺省 exponential） | 否 |
| `v_f` | float 相速因子（0<v_f≤1，缺省 1.0） | 否 |

## cm_extract_vf

CM 反向提取段一（VF 结构面）：复 S11/S21 → skrf VectorFitting 定阶扫描（rms 表）→ 带内复极点对↔谐振器数 N + 逐对 Q_pole/损耗比 + S21 分子根→TZ 数 → (N,n_fz) 结构 → Ω 域固定结构重拟合 → Cameron Y 留数（既有 _cm_transversal_exact 复用，与 Cauchy 路线互证）→ folded/arrow 拓扑初值。既有 coupling_matrix_extract 键保留为独立裁判不删改（#315）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | array GHz 频率轴 | 是 |
| `s11` | array 复 S11（[re,im] 对或复数） | 是 |
| `s21` | array 复 S21（[re,im] 对或复数） | 是 |
| `order` | int 阶数（缺省=由 VF 带内极点对数判） | 否 |
| `n_fz` | int 有限 TZ 数（缺省=由 S21 分子根判） | 否 |
| `f0_ghz` | float GHz 中心频率提示（缺省=纹波带边估计） | 否 |
| `fbw` | float 相对带宽提示（缺省=带边估计） | 否 |
| `topology` | str folded（缺省）\| arrow 拓扑初值 | 否 |
| `k_max` | int VF 定阶扫描上限（默认 6） | 否 |
| `phase_ref` | str unknown（缺省，\|S\| 裁判）\| known（复值逐点裁判） | 否 |
| `deembed_delay_s` | float 每侧馈线单程时延 τ(s)：复 S11/S21 先经 deembed_reference_delay 粗去嵌再进带缘检测与 VF（规格 §2a①，缺省关=不去嵌） | 否 |

## cm_refine_lm

CM 反向提取段二（LM 固定拓扑反演）：给定初值矩阵+拓扑掩码，θ=支撑集非零元+对角失谐/损耗 d_k≥0（+可选 qe），残差 r=Ŵ[S_model−S_meas] 实虚堆叠（S_model=向量化 _cm_response_raw 口径，逐位一致有钉），scipy trf 箱约束最小二乘（|m_ij|≤2max|初值|、d_k≥0）；同伦 S_λ=(1−λ)S_ideal+λS_meas 共 8 步热启动（残差劣化 >50% 半步回退）+ ±20%×4 确定性多起点；收敛双门=末段 rms≤1e-2 且 max|ΔS|≤0.05，不过 ok=False 如实

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | array GHz 频率轴 | 是 |
| `s11` | array 复 S11（[re,im] 对或复数） | 是 |
| `s21` | array 复 S21（[re,im] 对或复数） | 是 |
| `matrix` | array (N+2)×(N+2) 初值矩阵（cm_extract_vf 产出） | 是 |
| `f0_ghz` | float GHz 中心频率 | 是 |
| `fbw` | float 相对带宽（0<fbw≤1） | 是 |
| `topology` | str folded（缺省）\| arrow 掩码 | 否 |
| `loss` | bool true=对角损耗 d_k 进 θ（缺省 true） | 否 |
| `refine_qe` | bool true=归一化外部导纳进 θ（缺省 false） | 否 |
| `external_q` | array [q_in,q_out] 归一化外部导纳初值（缺省 [1,1]） | 否 |
| `transmission_zeros_norm` | array Ω 域 TZ 位置（缺省=只做带内 ×3 加权） | 否 |
| `homotopy_steps` | int 同伦步数（默认 8） | 否 |
| `n_starts` | int 多起点数（默认 4，1..8） | 否 |

## cma_modes

CMA 特征模分解（ge6 Wave1 离线档）：广义阻抗矩阵 Z=R+jX 的 R-加权广义特征值问题 X·I_n=λ_n·R·I_n（Harrington–Mautz 1971；综述 Cabedo-Fabrés 2007）。返回 λ 谱（升序实数）/模 significance MS_n=1/(1+λ²)（功率口径，幅值口径 1/√(1+λ²) 同步给出）/R-正交归一特征电流（I_mᵀ·R·I_n=δ_mn）/特征阻抗 Z_cn=1+jλ_n（R 归一口径，对 Z→αZ 缩放不变）/逐模相对残差。矩阵由调用方提供（MoM 导出、HFSS CMA 导出或散射法重建算子；npz 读出后以嵌套列表传入，计算器零 IO）；R 非正定/奇异显式报错不产 NaN。散射 dyadic CMA（Capek 2023）重建层另行立项，见 core/characteristic_modes docstring 扩展面登记

| 参数 | 说明 | 必填 |
|---|---|---|
| `z` | list N×N Z 矩阵：嵌套 [re,im] 对（JSON 语义）或全实数方阵；npz/MoM 导出由调用方读入后转嵌套列表（零 IO） | 是 |

## coax_line_attenuation

同轴线行波衰减分解：导体 αc=Rs·(1/a+1/b)/(4π·Z0)（Rs=√(πfμ/σ) 趋肤口径，αc∝√f∝1/√σ 测试钉）+ 介质 αd=β·tanδ/2（满充均匀假定，tanδ=0 如实返 null）；α_total dB/m=8.686(αc+αd)。附线 Q=β/(2α) 与场积分路线互证（β/(2αc) ↔ ωμ·ln(b/a)/(Rs(1/a+1/b)) 解析同解，q_xcheck_rel_dev 机器精度级）。锚：Cu/1GHz/a=1mm/b=2.301mm 空气 αc≈0.16373 dB/m（实测 0.163730589366）

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 工作频率（>0） | 是 |
| `a_mm` | float mm 内导体半径（>0） | 是 |
| `b_mm` | float mm 外导体内半径（>a_mm） | 是 |
| `conductivity_s_per_m` | float S/m 导体电导率（>0；Cu=5.8e7） | 是 |
| `epsilon_r` | float 填充介质相对介电常数（≥1，缺省 1） | 否 |
| `mu_r` | float 相对磁导率（>0，缺省 1 非磁性） | 否 |
| `tan_delta` | float 介质损耗角正切（≥0，缺省 0=无耗） | 否 |

## coax_line_power_capacity

同轴线峰值功率容量：TEM 场 E(ρ)=V/(ρ·ln(b/a))，内导体表面（ρ=a）场强最大 → V_max=E_br·a·ln(b/a)、P_max=V_max²/(2Z0)=E_br²·a²·ln(b/a)·√εr/120 W（峰值/匹配线，频率无关）。可选 p_op_w → 工作场强余量 dB（20log10(E_br/E_op)，可负=超容量如实报告）。最优比参考：外径固定功率容量最大 b/a=√e（Z0=30/√εr）。E_br 缺省 3.0e6 V/m=均匀场空气击穿参考值（非均匀场需降额，如实 note）。锚：恒等式测试侧独立重算；εr×4→P×2；p_op=P_max/4→余量 6.0206 dB

| 参数 | 说明 | 必填 |
|---|---|---|
| `a_mm` | float mm 内导体半径（>0） | 是 |
| `b_mm` | float mm 外导体内半径（>a_mm） | 是 |
| `epsilon_r` | float 填充介质相对介电常数（≥1，缺省 1） | 否 |
| `e_br_v_per_m` | float V/m 击穿场强参考值（>0，缺省 3.0e6 空气 STP 均匀场） | 否 |
| `p_op_w` | float W 工作峰值功率（≥0，可选——给则输出工作场强余量） | 否 |

## coax_line_z0

同轴线特性阻抗双向解：标准圆同轴 TEM 精确闭式 Z0=(60/√εr)·ln(b/a)，分析（给内/外导体半径 a,b）→ Z0+单位长 L'/C'+TE11 高阶模截止 f_c=c₀/(π(a+b)√εr)；综合（给 z0_ohm+外径 b 或内径 a 恰一）→ 反解另一半径（b/a=exp(Z0√εr/60)，roundtrip 恒等）；只给 z0_ohm → 直径比 ratio_only 路线。锚：空气 50Ω ↔ b/a=e^{5/6}；a=1/b=3mm → 65.916737Ω；L'·C'=με 恒等

| 参数 | 说明 | 必填 |
|---|---|---|
| `a_mm` | float mm 内导体半径（>0；分析与 b 同给，或综合只给 a） | 否 |
| `b_mm` | float mm 外导体内半径（>a_mm；分析与 a 同给，或综合只给 b） | 否 |
| `z0_ohm` | float Ω 目标特性阻抗（>0；综合/ratio_only 路线输入） | 否 |
| `epsilon_r` | float 填充介质相对介电常数（≥1，缺省 1=空气） | 否 |

## coaxial_cavity_resonance

同轴腔谐振：同轴腔 TEM 谐振双向解（Pozar §6.6）：λ/2 短路-短路腔 f₀=c₀/(2·l·√εr) 或 λ/4 短路-开路腔 f₀=c₀/(4·l·√εr)，给 f0_ghz 反解腔长/给 length_mm 解 f₀（双向 roundtrip 恒等）。可选内/外导体半径 a_mm/b_mm（同给，0<a<b）→ 特性阻抗 Z0=(60/√εr)·ln(b/a) 闭式 + 首高阶模 TE11 截止 f_c=c₀/(π(a+b)√εr)（保角映射 kc≈2/(a+b) 口径）；f₀≥f_c 时单模 TEM 假设失效如实 note 不拒绝。锚：空气 L=100mm λ/2 → 1.49896229 GHz；a=1/b=3mm → Z0=65.916737Ω

| 参数 | 说明 | 必填 |
|---|---|---|
| `mode` | str 'half'（λ/2 短路-短路）或 'quarter'（λ/4 短路-开路） | 是 |
| `f0_ghz` | float GHz 谐振频率（>0；与 length_mm 恰给其一=综合腔长） | 否 |
| `length_mm` | float mm 腔长（>0；与 f0_ghz 恰给其一=分析谐振频率） | 否 |
| `epsilon_r` | float 腔内介质相对介电常数（≥1，缺省 1=空气） | 否 |
| `a_mm` | float mm 内导体半径（>0，与 b_mm 同给，a<b；可选） | 否 |
| `b_mm` | float mm 外导体内半径（>a_mm；可选） | 否 |

## coded_ber_estimate

级联编码 BER 一阶粗估：γb_eff = ebn0_db + 10·lg(code_rate) + coding_gain_db → 理论 BER（闭式同 modulation_ber_curve）。仅计入码率能量扩张 + 固定净编码增益偏移（G 必须取目标 BER 点净增益），不建模打孔/交织/迭代译码瀑布区——粗估口径 docstring+note 双写死。锚：rate=1/2 且 gain=5dB ⇔ 未编码 +1.9897 dB 恒等（测试钉）。code_rate ∈ (0,1]，coding_gain_db 有限（可为负=弱码）

| 参数 | 说明 | 必填 |
|---|---|---|
| `scheme` | str 'bpsk'/'qpsk'/'16qam'/'64qam'（大小写不敏感） | 是 |
| `ebn0_db` | float dB 信息比特能量口径 Eb/N0（未编码等效） | 是 |
| `code_rate` | float - 码率 R_c=k/n（(0,1]，默认 1.0=无编码） | 否 |
| `coding_gain_db` | float dB 目标 BER 点净编码增益（有限，默认 0.0；弱码可为负） | 否 |

## combline_coupling_gap

combline 耦合缝→间隙换算：k_ij（MYJ 综合归一化耦合=δ/√(g_j·g_{j+1})口径）→ J=b_s·k_ij → (C_e,C_o) 几何均值约束闭式 → (w,g_ij) 带域边界二分反解（combline 半边，截面电容与 interdigital 两键同源 Getsinger 共形映射）；斜率双档=空载 λ/4 杆 π/(4Z_r)（缺省，与交指综合键同源）或 combline 装载斜率 [cotθ₀+θ₀csc²θ₀]/(2Z_r)（给 cap_ff+f0_ghz，θ₀ 与 combline_resonance 同解）；输出并列 k_norm_realized（MYJ 档 roundtrip）与 k_exact_phys（精确阻抗/电容定义档）

| 参数 | 说明 | 必填 |
|---|---|---|
| `k_coupling` | float 归一化耦合系数 k_ij（0<k<1 开区间；MYJ 综合口径） | 是 |
| `z_r_ohm` | float Ω 杆特性阻抗目标 Z0e·Z0o=Z_r²（>0） | 是 |
| `b_mm` | float mm 两接地平板间距（>0；条带线介质档口径） | 是 |
| `epsilon_r` | float 填充介质相对介电常数（≥1） | 是 |
| `cap_ff` | float fF 开路端装载电容（>0；与 f0_ghz 成对给=装载斜率档） | 否 |
| `f0_ghz` | float GHz 装载档谐振频率（>0；与 cap_ff 成对；给了才出杆长） | 否 |

## combline_resonance

梳状线谐振：combline 梳状线谐振器双向解（短路线 X=Zr·tanθ + 集总加载电容 C，谐振条件 ω₀·C·Zr·tanθ₀=1，Matthaei-Young-Jones ch.8 等效电路口径；θ<90° 感性区）：给 f0_ghz → 闭式 θ₀=arctan(1/(ω₀C·Zr)) 反解杆长 l=θ₀·c₀/(2π·f₀·√εeff)；给 length_mm → 单调域二分 200 轮解 f₀。C→0 极限退化为 λ/4 短路线自谐振（l→λg/4，测试钉）。输出含等效 L(ω₀)=Zr·tanθ₀/ω₀ 与 f₀=1/(2π√(L·C)) 口径自洽量。锚：Zr=80Ω/C=1pF/εeff=1/f₀=2GHz → l≈18.7mm；roundtrip ≤1e-12 相对

| 参数 | 说明 | 必填 |
|---|---|---|
| `zr_ohm` | float Ω 杆线特性阻抗（>0；典型 60~120Ω 高阻口径） | 是 |
| `cap_ff` | float fF 端部集总加载电容（>0；C→0 趋 λ/4 短路线极限） | 是 |
| `epsilon_r` | float 杆线有效介电常数 εeff（≥1，准 TEM 口径） | 是 |
| `f0_ghz` | float GHz 目标谐振频率（>0；与 length_mm 恰给其一——给 f0=综合杆长） | 否 |
| `length_mm` | float mm 杆长（>0；与 f0_ghz 恰给其一——给长度=分析谐振频率） | 否 |

## conducted_immunity_cdn

传导抗扰换算：IEC 61000-4-6 射频传导抗扰 CDN 耦合口径电压/功率换算：严酷度 test_level（1/2/3→1/3/10 V **emf**，Table 1 开路电动势口径）或显式 emf_v 恰给其一 → 匹配负载端电压（emf/2）、所需功率 P=(emf/2)²/Z、注入电流、80% AM 1kHz 包络峰（×1.8/+5.105dB）双列。dB 恒等式口径写死：0 dBm=1mW → 50Ω 匹配端电压 106.9897 dBµV（惯称 107 dBµV）；emf 开路口径 +6.0206 dB（0 dBm≡113.01 dBµV emf）。锚：Level 3→0.5 W/26.99 dBm；emf×2→+6.0206 dB 同步

| 参数 | 说明 | 必填 |
|---|---|---|
| `test_level` | int 严酷度等级 1\|2\|3（Table 1 emf 口径；与 emf_v 恰给其一） | 否 |
| `emf_v` | float V 显式电动势 emf（开路口径，>0；与 test_level 恰给其一） | 否 |
| `system_z_ohm` | float Ω 系统阻抗（>0，缺省 50） | 否 |

## corona_pd_check

MP-2 电晕/局放判据（round15 :82，Paschen+海拔降额，ECSS-E-ST-10-04C 语境）：施加电压（峰值口径）对空气隙的击穿/局放/电晕三面裕量报告。击穿面=Schumann 空气均匀场工程式（V_b=24.22x+6.08√x kV，x=δ·d cm；1mm 海平面 4.345 kV 经典锚）主判，Townsend-Paschen 物理形式（L&L Table 14.1 空气常数）作参照列；局放面=均匀隙起始（空洞尺寸 pd_gap_mm 缺省=gap，更小时先于击穿面 binding）；电晕面=Peek 起始场（δ 空气密度修正）×几何因子（coax/two_wire/wire_plane，镜像定理 wire_plane(h)≡two_wire(2h)）。气压由 ISA/US 1976 按海拔换算（0–20 km，可 pressure_pa 覆盖）；气温缺省 25 °C 参考标准日（忽略高空低温对降额偏保守，可显式注入 isa_temperature_c(alt)）。margin=限值/施加，≥safety_factor 判过；pass=已计算面合取

| 参数 | 说明 | 必填 |
|---|---|---|
| `voltage_v` | float 施加电压峰值 V（>0） | 是 |
| `gap_mm` | float 空气隙距离 mm（>0；击穿判据对象） | 是 |
| `geometry` | str 'uniform_gap'\|'coax'\|'two_wire'\|'wire_plane'（默认 'uniform_gap'；非 uniform 需 r_mm+d_mm 触发电晕面） | 否 |
| `r_mm` | float 导体半径 mm（coax 内半径/two_wire 线半径/wire_plane 线半径；>0） | 否 |
| `d_mm` | float coax 外半径 R/two_wire 中心距 D/wire_plane 对地高度 h（mm；需满足 R>r、D>2r、h>r） | 否 |
| `pd_gap_mm` | float 局放对象空洞特征尺寸 mm（缺省=gap_mm；空洞<间隙即经典'空洞局放'形态） | 否 |
| `altitude_m` | float 海拔 m（0–20000；默认 0；ISA 标准大气，20 km 以上近真空走 high_power multipactor 面） | 否 |
| `pressure_pa` | float 显式气压 Pa（>0；给定时覆盖 ISA 换算） | 否 |
| `temperature_c` | float 气温 °C（缺省 25 °C 参考标准日；ISA 剖面可经 core.corona.isa_temperature_c(alt) 显式注入） | 否 |
| `roughness` | float 导线表面粗糙度系数 m0（>0，缺省 1=光滑；<1 为工程粗糙面降额） | 否 |
| `safety_factor` | float 要求安全系数（缺省 1.0；margin≥sf 判过） | 否 |
| `e0_kv_per_cm` | float Peek E_0（缺省 30 kV/cm 峰值口径；rms 口径给 21.1） | 否 |
| `k` | float Peek k（缺省 0.301；rms 口径给 0.3081） | 否 |

## correlated_cascade_nf

相关级联噪声：MT-1 相关级联噪声系数（round17 MT-1，Hillbrand-Russer 链式噪声相关矩阵在匹配 z0 功率波域的显式式）：级表（gain_db/nf_db，信号流向）+ 级间加性噪声相关系数 → F_tot/NF + Friis 独立假设对照 + delta_nf_db（相关−独立差，核心产出）+ 等效噪声温度 + 逐级/逐对贡献分解。公式 F_tot = 1 + Σ(Fᵢ−1)/G_pre,ᵢ + 2Σ Re(ρᵢⱼ)√((Fᵢ−1)(Fⱼ−1)/(G_pre,ᵢ·G_pre,ⱼ))；ρ 全 0 逐位退化 Friis（与 core/cascade 对拍钉），ρ=±1 两极限有闭式锚，ρ 集合过 PSD 实测守卫（逐对 |ρ|≤1 不保证集合合法——三对不一致组合显式拒绝）⇒ F_tot≥1 解析保证。相噪相关性语义：共享 LO 双通道 ρ=+1、独立本振 ρ=0。失配/多端口广义 ABCD 噪声矩阵不在本域（诚实边界，见 core/noise_correlation.py 模块头）

| 参数 | 说明 | 必填 |
|---|---|---|
| `stages` | list[dict] 级表 [{gain_db: float dB, nf_db: float dB}, …]（信号流向；多余键忽略） | 是 |
| `rhos` | list[dict] 可选级间相关系数 [{i: int, j: int, rho: float\|[re, im]}, …]（0≤i<j<n；缺省全独立=Friis） | 否 |
| `t0_k` | float 参考温度 K（>0，默认 290） | 否 |

## coupled_line_bpf_response

耦合线带通频响校验：逐节 (Z0e,Z0o) 同步 TEM 电路频响——偶/奇模各自 2 端口线 S 叠加成 4 端口（构造无耗/互易），交叉口 Γ=+1 开路端接压缩 2 端口级联（S→ABCD 按 Pozar Table 4.2）。锚：Pozar Example 8.7 阻抗表带心 |S21|=0 dB、S11 谷数=N、无耗 |S11|²+|S21|²=1；vs 切比雪夫原型闭式带内 ≤0.5 dB（带缘倒置器频率依赖二阶偏差）

| 参数 | 说明 | 必填 |
|---|---|---|
| `z0e_ohm` | array 逐节偶模阻抗 Ω（≥2 节） | 是 |
| `z0o_ohm` | array 逐节奇模阻抗 Ω（同长；须 Z0e>Z0o>0） | 是 |
| `f0_ghz` | float GHz 中心频率（段长=λ/4@f0） | 是 |
| `freq_ghz` | array GHz 频率轴（>0；避开各节 θ=kπ） | 是 |
| `eps_eff` | float\|array 逐节平均有效介电常数（≥1；标量=同步均匀） | 否 |

## coupled_line_bpf_synthesize

耦合线带通综合：全极点切比雪夫平行耦合线带通（Pozar §8.6.2/MYJ ch.8）：阶数+中心频率+相对带宽+纹波 → J 倒置器 x 列表 → 逐节 (Z0e,Z0o) → KJ 二维反解微带实现 (w,s) mm → 段长 λ/4@εeff 均值、谐振器 λg/2−2Δl（Hammerstad 开路端修正）、50Ω 馈线宽（skrf HJ）。锚：Pozar Example 8.7 阻抗表 (70.61,39.24)/(56.64,44.77) 逐位复现（εr/h 无关）；x=(Z0e−Z0o)/(2Z0) 回代恒等；g 值 vs 教科书表 1.5963/1.0967

| 参数 | 说明 | 必填 |
|---|---|---|
| `order` | int 阶数 N（≥2；谐振器数，耦合段=N+1） | 是 |
| `f0_ghz` | float GHz 中心频率（>0） | 是 |
| `fbw` | float 相对带宽 δ=（f2−f1)/f0（0<δ≤1） | 是 |
| `ripple_db` | float dB 通带等纹波（>0；0.5dB 教科书例口径） | 是 |
| `z0_ohm` | float Ω 端口/馈线阻抗（>0，缺省 50） | 否 |
| `epsilon_r` | float 基板相对介电常数（≥1） | 是 |
| `h_mm` | float mm 基板厚（>0） | 是 |

## coupling_matrix_arrow

耦合矩阵拓扑约简（arrow）：N+2 全矩阵 → 三对角线+载端星形（复正交合同旋转 RMRᵀ，频响与原矩阵逐点一致）

| 参数 | 说明 | 必填 |
|---|---|---|
| `matrix` | array (N+2)×(N+2) 嵌套列表 [re, im] 对或实数 | 是 |

## coupling_matrix_extract

C13 EM/电路响应反提：频轴+复 S11/S21(+阶数) → f0、FBW、外部 Q、N+2 耦合矩阵与拟合残差。Cauchy 线性化有理拟合（S11=F/E, S21=P/E）→ Cameron Y 留数重建；f0 由拟合精化，fbw 无输入时按纹波带边估计（形状不可辨识，见 note）；domain=magnitude 走 |S|² 幅值域（相位污染数据兜底，精度损失见 note）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | array GHz 频率轴 | 是 |
| `s11` | array 复 S11（[re,im] 对或复数；magnitude 域取模） | 是 |
| `s21` | array 复 S21（[re,im] 对或复数；magnitude 域取模） | 是 |
| `order` | int 阶数（缺省=自动判阶） | 否 |
| `f0_ghz` | float GHz 中心频率（缺省=由拟合估计） | 否 |
| `fbw` | float 相对带宽（缺省=由纹波带边估计） | 否 |
| `phase_ref` | str complex 域符号枚举裁判：unknown（缺省，\|S\| 相位无关）\|known（已知参考面，复值逐点） | 否 |
| `domain` | str complex（缺省，复 S 全信息）\| magnitude（\|S\|² 幅值域） | 否 |
| `ref_delay_s` | float 对称参考面时延 τ(s)，complex 域反推后再拟合 | 否 |
| `ref_delay_scan` | bool true=按拟合残差最小一维扫描 τ̂（仿 f0 精化） | 否 |

## coupling_matrix_folded

耦合矩阵拓扑约简（folded）：N+2 横向矩阵 → 主线+交叉耦合（经典 palindromic 合同旋转序列，频响与原矩阵逐点一致；交叉耦合族自适应：anti=i+j=N+1（偶 N）/ shifted=i+j=N+2（奇 N 偶数 TZ）；非横向输入的残留如实见 pattern_residual）。边界注记：复系数（真·非对称 TZ）输入不保证单族 folded 清洁——实测仅单侧 TZ 的偶 N（N3[2.0]）与奇 N全规范（N2[1.5]）落单族（anti/shifted，残差 0），其余非对称输入（N3[1.5,-2.0]/N4[1.2,2.5]/N5[1.5,2.5]）pattern_residual 0.2~0.8、family=mixed 如实返回（频响不变性不受影响）；复系数 folded 拓扑增量不在本内核（方案 §10.18-§10.23 冻结，TODO 另立增量）

| 参数 | 说明 | 必填 |
|---|---|---|
| `matrix` | array (N+2)×(N+2) 嵌套列表 [re, im] 对或实数 | 是 |
| `sign_mode` | str - 符号归一口径：mainline_positive（默认，主线全正，S21 相位可能对输入翻 180°）\| preserve_s21_phase（只翻谐振器节点，S21 相位与输入同相，末端 m_{N,L} 允许为负） | 否 |

## coupling_matrix_response

耦合矩阵理想频响（fake 裁判闭式）：给定 (N+2) 矩阵+频率轴，低通→带通映射 Ω=(f/f0−f0/f)/fbw，返回 S11/S21（复数+dB）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | array GHz 频率轴 | 是 |
| `f0_ghz` | float GHz 中心频率 | 是 |
| `fbw` | float - 相对带宽（0<fbw≤1） | 是 |
| `matrix` | array (N+2)×(N+2) 嵌套列表 [re, im] 对或实数 | 是 |
| `external_q` | array [q_in, q_out] 归一化外部导纳（本项目=1,1） | 否 |
| `z_ref` | float Ω 参考阻抗（默认 50，仅标注用） | 否 |

## coupling_matrix_synthesize_explicit

显式TZ综合：C13 显式 TZ 集合综合（Cameron N+2）：完整 TZ 列表（每个 Ω 单独列出；±Ω 成对=实系数原型，与 coupling_matrix_synthesize_n2 同口径；非成对=复系数原型，响应 Ω→−Ω 不对称）→ (N+2)×(N+2) 横向矩阵，频响与原型逐点一致（幅度；复系数路径实测 ≤1.3e−13）。复元矩阵为复对称 M=Mᵀ，非对称网络 |m_0k| 与 |m_kL| 允许不等

| 参数 | 说明 | 必填 |
|---|---|---|
| `order` | int - 阶数（≥1） | 是 |
| `rl_db` | float dB 带内回损纹波（>0） | 是 |
| `transmission_zeros` | array 显式 TZ 列表（每项一个 Ω，\|Ω\|>1，个数 ≤ 阶数） | 是 |

## coupling_matrix_synthesize_n2

Cameron N+2 耦合矩阵综合：广义切比雪夫原型 → (N+2)×(N+2) 矩阵（口径：首/末节点为源/载，外部导纳 q=(1,1) 归一化，耦合信息在 m0i/miL；复 Entries 允许，频响与原型逐点一致）

| 参数 | 说明 | 必填 |
|---|---|---|
| `order` | int - 阶数（≥1） | 是 |
| `rl_db` | float dB 带内回损纹波（>0） | 是 |
| `transmission_zeros` | array 归一化低通传输零点 \|Ω\|>1 列表（±ω 成对口径，缺省=全极点） | 否 |

## cpk_yield_convert

Cpk↔良率正态尾双向换算：Cpk→良率（单尾工业标准档 Φ(3Cpk)=Montgomery 表值口径 + 可选双限边际 (Cu,Cl) 精确两尾 Φ(3Cu)·Φ(3Cl) + 仅知 Cpk 的界 [Φ(3Cpk)²,Φ(3Cpk)] 如实声明）；良率→Cpk 反解 Φ⁻¹/3（单尾/居中两尾双档声明）；随行 ppm/DPMO 面出界率

| 参数 | 说明 | 必填 |
|---|---|---|
| `cpk` | float 过程能力指数 Cpk（≥0；Cpk→良率路线，与 yield_frac 二选一） | 否 |
| `yield_frac` | float 良率小数（0<Y<1 开区间；反解路线） | 否 |
| `cpk_upper` | float 上侧边际指数 Cu=(USL−μ)/(3σ)（成对与 cpk_lower；给了才出精确两尾档） | 否 |
| `cpk_lower` | float 下侧边际指数 Cl=(μ−LSL)/(3σ)（成对与 cpk_upper） | 否 |
| `spec_side` | str 反解档位 one_sided\|two_sided_centered（缺省 one_sided，档位假设如实进 note） | 否 |

## cps_analysis

共面带（CPS，双带无地）分析：共形映射部分电容闭式 (w, gap, h) → (Z0, εeff)。

| 参数 | 说明 | 必填 |
|---|---|---|
| `w_mm` | float mm 单带宽度（两带等宽） | 是 |
| `gap_mm` | float mm 两带间缝宽 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `h_mm` | float mm 基板厚度（无地，基板下为空气） | 是 |
| `freq_ghz` | float GHz 频率（可选，给了才返回 λg） | 否 |

## cps_synthesis

共面带（CPS）综合：目标 Z0 → 单带宽度（固定 gap，brentq 回代自洽）

| 参数 | 说明 | 必填 |
|---|---|---|
| `z0_ohm` | float Ω 目标特性阻抗 | 是 |
| `gap_mm` | float mm 两带间缝宽 | 是 |
| `freq_ghz` | float GHz 频率 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `h_mm` | float mm 基板厚度（无地） | 是 |

## cpw_analysis

共面波导分析：(w, gap) → (Z0, εeff)。skrf CPW 准静态模型

| 参数 | 说明 | 必填 |
|---|---|---|
| `w_mm` | float mm 中心导带宽度 | 是 |
| `gap_mm` | float mm 导带-地缝隙 | 是 |
| `freq_ghz` | float GHz 频率 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `h_mm` | float mm 基板厚度 | 是 |
| `tand` | float - 损耗正切（默认 0） | 否 |

## cpw_synthesis

共面波导综合：目标 Z0 → 中心导带宽度（固定 gap，brentq 求逆）

| 参数 | 说明 | 必填 |
|---|---|---|
| `z0_ohm` | float Ω 目标特性阻抗 | 是 |
| `gap_mm` | float mm 导带-地缝隙 | 是 |
| `freq_ghz` | float GHz 频率 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `h_mm` | float mm 基板厚度 | 是 |

## cpwg_analysis

底接地共面波导（CPWG）分析：共形映射闭式 (w, gap) → (Z0, εeff)。

| 参数 | 说明 | 必填 |
|---|---|---|
| `w_mm` | float mm 中心导带宽度 | 是 |
| `gap_mm` | float mm 导带-地缝隙 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `h_mm` | float mm 基板厚度（底接地距离） | 是 |
| `freq_ghz` | float GHz 频率（可选，给了才返回 λg） | 否 |

## cpwg_synthesis

底接地共面波导（CPWG）综合：目标 Z0 → 中心带宽度（固定 gap，brentq）

| 参数 | 说明 | 必填 |
|---|---|---|
| `z0_ohm` | float Ω 目标特性阻抗 | 是 |
| `gap_mm` | float mm 导带-地缝隙 | 是 |
| `freq_ghz` | float GHz 频率 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `h_mm` | float mm 基板厚度（底接地距离） | 是 |

## crlh_unit_cell_report

CRLH单元分析：MM-4 CRLH（复合左/右手传输线）单元点分析（round17 §五 :146，Caloz & Itoh Wiley 2006 §3.1 口径）：T 型单元（串 L_R+C_L / 并 C_R+L_L）在单频点的谐振对 f_se=1/(2π√(L_R C_L))、f_sh=1/(2π√(L_L C_R))、ZOR（规格口径 1/√(L_L C_R)，短路边界 N=0 模；开路边径=ω_se 另提供）、平衡判定（δ=2(f_se−f_sh)/(f_se+f_sh)，平衡=0 阻带闭合）、频段归类（left_hand/right_hand/stopband；平衡单元 f_se=f_sh 为 transition 无缝过渡点）、复 Bloch 色散 β(ω)（左手频段 β<0 相位超前/右手 β>0/非平衡阻带 β 纯虚 Im≤0，深阻带 Bloch 相位 ±π/d）、CRLH 阻抗 Z_CRLH=√(Z/Y)（平衡时 ≡√(L_R/C_R) 与频率无关；ω→ω_sh 阻带高阻/开路极限）、衰减（Np/m 与 dB/单元）与漏波角 θ=arcsin(Re β/k0)（|Re β|≥k0 或阻带 → None 不辐射不外推）

| 参数 | 说明 | 必填 |
|---|---|---|
| `l_r_nh` | float 右手串联电感 L_R nH（>0） | 是 |
| `c_l_pf` | float 左手串联电容 C_L pF（>0） | 是 |
| `l_l_nh` | float 左手并联电感 L_L nH（>0） | 是 |
| `c_r_pf` | float 右手并联电容 C_R pF（>0） | 是 |
| `f_ghz` | float 分析频率 GHz（>0） | 是 |
| `cell_len_mm` | float 单元周期 d mm（>0；缺省 1.0） | 否 |
| `balance_rtol` | float 平衡判定相对容差（缺省 1e-6） | 否 |

## detector_tss_nep

检波器切向灵敏度 TSS/噪声等效功率 NEP：视频约翰逊噪声 v_n=√(4k_BT·R_v·B_v) → NEP=v_n/γ（输出 SNR=1 输入功率，γ=电压灵敏度 V/W）；TSS=检波后 SNR=8dB 的输入功率（切向显示判据口径写死，平方律下 TSS−NEP=snr/2 dB——8dB 判据恰 +4.0dB 恒等锚）；NEP∝√(R_v·B_v/T) 标度可钉。TSS 按脉冲定义（B_v 与脉宽配套，如实注记）。锚：v_n 测试侧独立常数重算；√B/√R_v 标度逐位；TSS−NEP=snr/2 恒等

| 参数 | 说明 | 必填 |
|---|---|---|
| `gamma_v_per_w` | float V/W 电压灵敏度 γ（>0；典型零偏 Schottky 10³–10⁴ 量级） | 是 |
| `r_v_ohm` | float Ω 视频负载（>0，缺省 1e6） | 否 |
| `b_video_hz` | float Hz 视频带宽（>0，缺省 1e6；与检波脉冲宽度配套） | 否 |
| `t_kelvin` | float K 噪声温度（>0，缺省 290） | 否 |
| `snr_tss_db` | float dB 切向判据检波后 SNR（∈(0,40)，缺省 8.0 工程惯例口径） | 否 |

## diode_square_law_detect

二极管平方律检波：小信号 i=kv²（k=转移曲率）+射频匹配 P=V_rms²/R_j → I_dc=(k·R_j)·P_in≡β·P_in（电流灵敏度 β 与功率无关=平方律恒等锚），视频电压 V_video=I_dc·R_v；dBm→mW→V_rms 换算链直出。平方律有效域[−120,−20]dBm（上沿=零偏 Schottky 工程惯例，域外显式拒绝不外推到压缩区）。锚：I_dc=k·R_j·P_in 测试侧独立重算；P×2→I×2 线性标度；β 两功率点同值；V_video=I·R_v 回代

| 参数 | 说明 | 必填 |
|---|---|---|
| `p_in_dbm` | float dBm 射频输入功率（∈[−120,p_sq_max_dbm]，缺省上沿−20） | 是 |
| `k_uav2` | float µA/V² 平方律转移曲率 k（>0；i=kv²，I_dc=k·V_rms²） | 是 |
| `r_j_ohm` | float Ω 检波管射频阻抗（>0；匹配口径 P=V_rms²/R_j） | 是 |
| `r_v_ohm` | float Ω 视频负载（>0，缺省 1e6 高阻视频） | 否 |
| `p_sq_max_dbm` | float dBm 平方律有效域上沿（>p_in_dbm 下限，缺省 −20；实际器件以厂家曲线为准） | 否 |

## dipole_emf_zin

偶极输入阻抗（正弦电流假设）：R=辐射功率积分路线 η/(2πsin²kh)·∫₀^π[cos(kh·cosθ)−cos(kh)]²/sinθdθ（对假设分布精确，quad 定精度）——短偶极渐近 20π²(l/λ)²（三角电流极限）与半波 73.1Ω 教科书常数双锚；X=感应电动势法 Si/Ci 经典闭式（Balanis §8.4 印刷形，含 Ci(2ka²/l) 线径项）——半波 j42.5Ω 锚、细线容性渐近定性钉；谐振长度 [0.40,0.50]λ 二分（细线 ~0.47λ 锚带）；方向性 D 共享同一积分——半波 2.15dBi/短偶极 1.76dBi 双锚。域 l∈(0,λ)（单瓣正弦假设；l=λ 全波馈点电流节点奇点显式拒绝）

| 参数 | 说明 | 必填 |
|---|---|---|
| `length_mm` | float mm 偶极总长 l（∈(0,λ)，单瓣正弦电流假设域） | 是 |
| `f_ghz` | float GHz 工作频率（>0） | 是 |
| `wire_radius_mm` | float mm 导线半径 a（>0；X 闭式线径项 Ci(2ka²/l) 输入） | 是 |

## doa_crb_stochastic

DOA 随机（高斯）信号 CRB：s_t~CN(0,Q) 边缘化 x_t~CN(0,R) 模型——celebrated 闭式 CRB=(σ²/2T){Re[(DᴴP⊥D)⊙(QAᴴR⁻¹AQ)ᵀ]}⁻¹（Stoica-Nehorai 1989 两模型对照随机半边）主口径 + 精确 Slepian-Bangs 全参数（σ²、Q Schur 消元）内建互证面（全域恰等 rel≤7.5e-15 实测）；M=1 退化=确定性键×(1+1/(pN))（随机≥确定性、高 SNR 渐近相等）；与 doa_crb_ula_multisource（确定性）并列口径

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_elements` | int 阵元数 N（整数 ≥2 且 >源数 M——P⊥ 秩 N−M≥1） | 是 |
| `snapshots` | int 快拍数 T（整数 ≥1） | 是 |
| `angles_deg` | list[float]° 各源来波角（1..16 个；开区间 (−90,90)、两两异角） | 是 |
| `snr_db` | float\|list dB 各源阵元级 SNR=p/σ²（标量广播或长度=M 列表） | 是 |
| `spacing_lambda` | float 阵元间隔 d/λ（∈(0,1]） | 是 |
| `corr_coef` | float 源间等相关系数 ρ（∈[0,1) 缺省 0=不相关；ρ=0 闭式恰等精确面） | 否 |

## doa_crb_ula

DOA 单源 CRB 下界：ULA 确定性 Cramér-Rao 下界 CRB(θ)=12/(2·T·SNR·N(N²−1)·(2π·d/λ)²·cos²θ)——阵元数/快拍数/SNR/间隔/来波角 → 方差 rad²、标准差 rad/deg、Fisher 信息；闭式∝1/T·1/SNR·1/cos²θ·1/N³(渐近)；端fire θ=±90° 与 N=1 显式拒绝（发散）；MUSIC/ESPRIT 估计精度裁判面（估计器本体走 doa_* 键不并入）

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_elements` | int 阵元数 N（整数 ≥2） | 是 |
| `snapshots` | int 快拍数 T（整数 ≥1） | 是 |
| `snr_db` | float dB 单源阵元级 SNR（有限实数） | 是 |
| `spacing_lambda` | float 阵元间隔 d/λ（∈(0,1]；>1/2 栅瓣风险如实 note） | 是 |
| `angle_deg` | float° 来波角（侧射=0°；开区间 (−90,90)） | 是 |

## doa_crb_ula_multisource

DOA 多源 CRB 下界：FIM 矩阵求逆通用式 FIM=2T·Re[(DᴴP⊥D)⊙P̄ᵀ]（P̄=√snr·R·√snr 等相关源协方差）→ 求逆对角元=各源 CRB 方差/标准差 rad/deg；ρ=0 源解耦（FIM 对角恒零化）、ρ→1 相干奇异显式拒绝；N>M 投影秩硬前提；M=1 与 doa_crb_ula 逐位一致；MUSIC/ESPRIT 多目标精度裁判面（随机 CRB 不在键面如实登记）

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_elements` | int 阵元数 N（整数 ≥2 且 >源数 M——P⊥ 秩 N−M≥1） | 是 |
| `snapshots` | int 快拍数 T（整数 ≥1） | 是 |
| `angles_deg` | list[float]° 各源来波角（1..16 个；开区间 (−90,90)、两两异角） | 是 |
| `snr_db` | float\|list dB 各源阵元级 SNR（标量广播或长度=M 列表） | 是 |
| `spacing_lambda` | float 阵元间隔 d/λ（∈(0,1]） | 是 |
| `corr_coef` | float 源间等相关系数 ρ（∈[0,1) 缺省 0=不相关；→1 相干 FIM 奇异显式拒绝） | 否 |

## doa_esprit

ESPRIT测向：TLS-ESPRIT 旋转不变子空间 DOA（闭式步骤，Roy & Kailath 1989 §III-C）：信号子空间移位对 Z₀=E_s[:-1]/Z₁=E_s[1:]，堆叠 SᴴS 最小 m 个特征向量分块 Φ=−V₁₂V₂₂⁻¹（V₂₂ᴴ 线性求解稳定形，条件数劣化显式拒绝），ψ=eig(Φ) 相角 → sinθ=ω/(2π·d/λ)。无网格误差（与 MUSIC 网格口径互补）。输入路径/守卫同 doa_music_spectrum。锚：单源 ESPRIT=MUSIC=真值（<1e-8°）；理想协方差双源 <1e-6°

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_elements` | int 阵元数 N（≥2，m<N） | 是 |
| `angles_deg` | array 合成路径：来波角列表（度，\|θ\|<90°，两两相异） | 否 |
| `covariance` | array 显式路径：n×n 协方差（[re,im] 对嵌套，正定） | 否 |
| `n_sources` | int 信源数 m（显式协方差路径必给；合成路径=源角数且不可另给） | 否 |
| `spacing_lambda` | float d/λ（(0,1]，缺省 0.5） | 否 |
| `snr_db` | float 每源带内 SNR dB（有限，缺省 10） | 否 |
| `n_snapshots` | int\|null 快拍数 T（≥N；null=理想协方差） | 否 |
| `seed` | int 随机种子（≥0，缺省 0） | 否 |

## doa_music_spectrum

MUSIC角度谱：MUSIC 多重信号分类角度谱（ULA 窄带远场，侧射角约定 θ=0=broadside，a(θ)_m=exp(j2π(d/λ)sinθ·m)）：协方差合成路径（angles_deg+snr_db+n_snapshots+seed；n_snapshots=null=理想协方差，整数=白噪声快拍 PCG64 确定性）或显式协方差路径（n×n [re,im] 嵌套，须配 n_sources）恰给其一。噪声子空间伪谱 P=1/‖E_nᴴa‖²，网格局部极大取前 m 个+log10 域抛物线亚网格内插。锚：理想协方差双源峰位回收误差 <0.01°（Schmidt 1986）。厄米化守卫+奇异协方差显式拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_elements` | int 阵元数 N（≥2，m<N） | 是 |
| `angles_deg` | array 合成路径：来波角列表（度，\|θ\|<90°，两两相异） | 否 |
| `covariance` | array 显式路径：n×n 协方差（[re,im] 对嵌套，正定） | 否 |
| `n_sources` | int 信源数 m（显式协方差路径必给；合成路径=源角数且不可另给） | 否 |
| `spacing_lambda` | float d/λ（(0,1]，缺省 0.5） | 否 |
| `snr_db` | float 每源带内 SNR dB（有限，缺省 10；噪声功率归一 1） | 否 |
| `n_snapshots` | int\|null 快拍数 T（≥N；null=理想协方差） | 否 |
| `seed` | int 随机种子（≥0，缺省 0；PCG64 流稳定） | 否 |
| `grid_step_deg` | float 角度谱网格步长（[0.05,5.0] 度，缺省 0.05） | 否 |

## doa_mvdr_weights

MVDR波束权重：MVDR/Capon 最小方差无失真响应波束形成权重与阵列响应（Capon 1969/Van Trees OAP ch.6）：w=R⁻¹a(θ_look)/(aᴴR⁻¹a)——期望方向增益恒 1（aᴴw=1 构造恒等式，残差逐位回显）；R=I 退化常规波束形成 w=a/‖a‖²。协方差（n×n [re,im] 嵌套，正定非奇异显式拒绝）必给；期望方向给 look_angle_deg（配 spacing_lambda 构造导向矢量）或显式 steering [re,im] 矢量恰其一。输出权重、期望方向增益、探针角响应 dB、栅格响应与零陷深度（主瓣 ±λ/(Nd) u 域掩蔽后最小响应）

| 参数 | 说明 | 必填 |
|---|---|---|
| `covariance` | array n×n 协方差（[re,im] 对嵌套，正定非奇异） | 是 |
| `look_angle_deg` | float 期望方向（度，\|θ\|<90°；与 steering 恰给其一） | 否 |
| `steering` | array 显式导向矢量（[re,im] 对列表，长 n） | 否 |
| `spacing_lambda` | float d/λ（(0,1]，缺省 0.5；栅格/探针导向矢量构造口径） | 否 |
| `probe_angles_deg` | array 探针角列表（度，\|θ\|<90°；逐角回响应 dB） | 否 |

## doherty_combining_network

Doherty合路网络：经典 2-Way 等功率 Doherty 合路 λ/4 网络综合（G11，口径写死）：给单管最优负载 R_opt → 合路节点负载 R_L=R_opt/2、载波臂 λ/4 逆变器特征阻抗 Z_T=R_opt=2R_L、回退点载波视入 Z_BO=Z_T²/R_L=2R_opt（Cripps ARMMS 2008：Z0=2R、R=Ropt/2）；合并点回退固定 10·log10(4)=6.0206 dB、功分比 50/50。λ/4 反演 Z_in=Z_T²/Z_L 走 core 单源（ABCD βl=π/2 精确退化）并回代自洽；peak 臂偏置线（90°@f0、Z=Z_T 惯例口径，实现相关非唯一）如实标注。backoff_db 偏离经典值超 0.05dB 显式拒绝（非等功率口径不外推）

| 参数 | 说明 | 必填 |
|---|---|---|
| `r_opt_ohm` | float Ω 单管最优基波负载 R_opt=V_dd/I_1（>0） | 是 |
| `z0_ohm` | float Ω 系统阻抗（归一化展示面，缺省 50） | 否 |
| `backoff_db` | float dB 合并点回退（缺省=经典 6.0206；偏离超 0.05dB 显式拒绝） | 否 |

## doherty_efficiency_curve

Doherty效率曲线：理想 B 类 Doherty 效率-回退曲线（G11，单源消费 core/pa_architectures 两区域闭式，Cripps ARMMS 2008 口径）：区域 I（σ≤1/2 辅管截止）η=(π/2)σ、区域 II η=πσ²/[2(3σ−1)]，σ=√(P/P_pk)。双拐点锚：η(σ=1)=η(σ=1/2)=π/4≈78.54% 逐位（峰值与 6.0206dB 合并点）；中段凹陷严格极小 2π/9≈69.81% 在 σ=2/3（PBO≈3.5218dB，独立求导锚）——凹陷深度依辅管实现（Cripps Notes 7 原文），本键采用严格 B 类口径如实报告凹陷、不冒充全平平台。对照列：单管 B 类 (π/4)√p 三角衰减律+逐点 doherty_ge_class_b 判读

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_points` | int 回退轴点数（[2,1001]，缺省 41；PBO 0→pbo_max_db 均匀栅格） | 否 |
| `pbo_max_db` | float dB 回退轴上限（(0,30]，缺省 10） | 否 |

## dr_te01d_cohn_f0

圆柱介质谐振器 TE01δ 正解（磁壁模型）：Cohn 1968 超越方程 tan(βL/2)=α/β，brentq 求根——直径 D/高 L/εr → f0，随行式 D2 端板贴面对照频率（两模型之比=空气份额物理量）、k_r=x01/a（x01=J0 首正零点 2.4048，与圆柱腔 TM010 同根）、β/α、介质内储能份额 δ_e、q_dielectric=1/tanδ（tanδ=0 返 null）。L≥D 带高阶模竞争警告不拒绝。锚（规格包独立复算，测试面独立二分双路线互证）：εr=38/D=15mm/L=7.5mm → f0=3.114682 GHz、贴面=4.083040 GHz（比 0.7628）；εr=81/D=10.6/L=4.6 → 3.132377 GHz；εr=36.3/D=18/L=8 → 2.733303 GHz

| 参数 | 说明 | 必填 |
|---|---|---|
| `diameter_mm` | float mm 谐振器直径 D=2a（>0，DR 商品口径单输入） | 是 |
| `height_mm` | float mm 谐振器高度 L（>0） | 是 |
| `epsilon_r` | float 相对介电常数（≥2，DR 实用域；<2 模式概念退化拒绝） | 是 |
| `tan_delta` | float 损耗角正切（≥0，缺省 0=无耗，q_dielectric=null） | 否 |

## dr_te01d_design_size

圆柱介质谐振器 TE01δ 反解尺寸：式 D1 一维求根——εr/目标频率/L-D 比h → 直径 D、高 L=h·D。f0(D) 在有效域严格单调降（√εr 标度因空气份额破缺——εr×4 只降 0.501 非 0.5，规格包 D5 锚），可行域 D ∈ (K_lo, min(K_hi, K_pole))/f_target 由频窗上下缘+贴面极点三界给出，log 栅格扫描+cell 内 brentq；roundtrip 残差（尺寸回代式 D1）随行，>1e-8 内部断言失败显式报错。锚：εr=38/f0=3.1146824935345903 GHz/h=0.5 → D=15mm/L=7.5mm（D1 锚回代）

| 参数 | 说明 | 必填 |
|---|---|---|
| `epsilon_r` | float 相对介电常数（≥2，DR 实用域） | 是 |
| `f0_ghz` | float GHz 目标 TE01δ 谐振频率（>0） | 是 |
| `height_to_diameter` | float L/D 设计比（0<h<2 开区间，2.0 恰值拒绝；缺省 0.4=商品 DR 典型域；h≥1 带高阶模竞争警告） | 否 |

## ecss_multipactor_fd

ECSS 多载流子 f·d 判据：f×d(GHz·mm) 查 ECSS-E-ST-20-01C Table 5-1 的最低击穿电压阈值边界（Al/Cu/Ag/Au，对数插值），与施加峰值电压比给出裕量 dB 与过/不过判定

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | float GHz 工作频率（>0） | 是 |
| `gap_mm` | float mm 临界间隙（>0） | 是 |
| `material` | str 金属键 aluminium/copper/silver/gold（默认 silver） | 否 |
| `voltage_v` | float V 施加峰值电压（优先；与功率二选一） | 否 |
| `power_w` | float W 单载波功率（配 z0_ohm：V=√(2PZ0)） | 否 |
| `z0_ohm` | float Ω 系统阻抗（默认 50） | 否 |
| `carrier_powers_w` | array W 各载波平均功率（ECSS 口径 Pavg=ΣPi） | 否 |
| `required_margin_db` | float dB 要求裕量（默认 6） | 否 |

## electromigration_mttf_check

MP-4 电迁移-场联动（round15 :86）：局部损耗密度场→局部 J→Black MTTF（+IPC-2152 ΔT 联合温度链 + 可选 Blech immortal 判据）联合报告。J 路由二选一：loss_density_w_per_m3（EM 场后处理局部焦耳体损耗，J=sqrt(q/ρ)，逐网格局部口径不做全局等效——高频趋肤下局部 J 高于截面均值）或 j_density_a_per_m2 直接给；ρ(T)=ρ_ref·(1+α·ΔT) 线性 TCR 修正（tcr_per_k 可选，铜 α=3.93e-3/K@20 °C 为模块常量非隐藏缺省）。T 路由二选一：temperature_c 直接给（IPC-2152 ΔT 联合=ipc2152 键输出 delta_t_c 加环境温度后注入）或 Foster 热链 zth_r_c_per_w+zth_tau_s+power_w（三参同给，消费 MP-1 thermal_transient；time_s 缺省稳态 ΔT=P·ΣR 能量守恒锚）。Black：MTTF=A·J⁻ⁿ·exp(Ea/kT)，n 缺省 2.0（Black 1969 IEEE T-ED 原始口径），a_black/ea_ev 必填（Ea 随金属/工艺标定：Al 系 ~0.5–0.7 eV、Cu 系 ~0.8–1.0 eV 为文献量级语境非缺省值，MTTF 时间单位与 a_black 标定一致）；t_ref_af_c 给定时输出 Arrhenius AF=exp[(Ea/k)(1/T_use−1/T_stress)] 与参考温度 MTTF（恒等式 mttf_at_ref=mttf·AF）。Blech（segment_length_m 给则启用）：临界积 (jL)_c=Δσ·Ω/(|Z*|eρ)（Blech 1976 JAP 47:1203），j·L≤(jL)_c 判 immortal，Ω 缺省铜 1.1807e-29 m³（量级锚：Cu Δσ=50 MPa → (jL)_c≈2.1e3 A/cm=文献『Blech product ~2000 A/cm』带，判据对 Δσ 线性敏感应按工艺标定）

| 参数 | 说明 | 必填 |
|---|---|---|
| `loss_density_w_per_m3` | float W/m³ 局部焦耳体损耗密度（>0；与 j_density_a_per_m2 二选一，需 resistivity_ohm_m） | 否 |
| `j_density_a_per_m2` | float A/m² 直接给局部电流密度（>0；与 loss_density 二选一） | 否 |
| `resistivity_ohm_m` | float Ω·m 参考温度电阻率（>0；loss_density 路/Blech 判据必需，铜 1.724e-8@20 °C） | 否 |
| `tcr_per_k` | float 1/K 电阻温度系数（缺省不修正；铜 3.93e-3） | 否 |
| `t_ref_c` | float °C TCR 参考温度（缺省 20） | 否 |
| `temperature_c` | float °C 局部金属温度（与 Foster 热链二选一；IPC-2152 ΔT 联合=ambient+delta_t_c 经此注入） | 否 |
| `ambient_c` | float °C Foster 热链环境温度（缺省 25） | 否 |
| `zth_r_c_per_w` | array °C/W Foster 热阻链（与 zth_tau_s+power_w 三参同给） | 否 |
| `zth_tau_s` | array s Foster 时间常数链（与热阻链等长） | 否 |
| `power_w` | float W 阶跃耗散功率（≥0；稳态 ΔT=P·ΣR） | 否 |
| `time_s` | float s 瞬态评估时刻（缺省稳态） | 否 |
| `a_black` | float Black 前置常数（>0；单位吸收时间标定，h·(J 单位)^n 标定则 MTTF 返回小时） | 是 |
| `n_black` | float 电流密度指数（缺省 2.0=Black 1969 原始口径；≥0） | 否 |
| `ea_ev` | float eV 激活能（≥0；随金属/工艺标定，必填不内置缺省） | 是 |
| `t_ref_af_c` | float °C AF 参考温度（给则输出 AF 与参考 MTTF） | 否 |
| `segment_length_m` | float m 导体段长度（>0；给则启用 Blech 判据） | 否 |
| `delta_sigma_mpa` | float MPa 应力松弛窗（≥0；Blech 启用时必填） | 否 |
| `atomic_volume_m3` | float m³ 原子体积（缺省铜 1.1807e-29） | 否 |
| `zstar` | float 有效电荷数（非零，取 \|Z*\|；缺省 1.0） | 否 |

## envelope_tracking_efficiency

ET包络跟踪效率：理想 B 类包络跟踪平均漏极效率闭式（Rayleigh 包络+供电下限 f+轨上硬削顶）：η=(π/4)(1−e^−ξ)/[e^−ξf²−e^−ξ+(√(πξ)/2)f·erf(f√ξ)]，ξ=PAPR 线性。双结构锚：f=0 → η=π/4 与 PAPR 无关（ET 全部要义）；f=1 → 逐位退化为定供 B 类对照 η_fixed（随行输出）。能量口径 E[Pout]/E[Pdc]；η_ET ≥ η_fixed 全域（供电恒不高于定供）。门限/削顶概率随行

| 参数 | 说明 | 必填 |
|---|---|---|
| `papr_db` | float dB 信号峰均比（[0,15]；<0 非物理、>15 超 Rayleigh 包络模型有效域） | 是 |
| `supply_floor_frac` | float - 供电下限占满摆幅份额 f（[0,1]；0=理想全程跟踪，1=无跟踪退化档；缺省 0.1=典型 ET 面口径） | 否 |

## esd_contact_waveform

接触放电波形：IEC 61000-4-2 接触放电（ESD）双指数电流波形特征键：波形表仅对接触放电定义（空气放电无独立表），归一化每 kV——Ip=3.75 A/kV（±10%）、I(30ns)=2 A/kV、I(60ns)=1 A/kV（±30%）、t_r=0.6–1 ns（150pF/330Ω 发生器校准口径，单源消费 core/emc_tvs_gate）。保守双指数参数化 I(t)=I0(e^(−t/τ1)−e^(−t/τ2))（规范只给包络点，非规范定义）：三条件定参=峰值 + I(30)/I(60)=2:1 比值恒等 + rise_time_ns（缺省 0.7，域 [0.6,1.0]）；τ1/τ2 定点迭代（单调二分），I0 由解析峰时反解。恒等锚：∫I dt=I0(τ1−τ2) 解析面积 vs 梯形积分回收；4 kV→15 A/0.7 ns；8 kV 波形=2×4 kV 波形（归一化表线性性）

| 参数 | 说明 | 必填 |
|---|---|---|
| `charge_kv` | float kV 充电电压（接触放电档 {2,4,6,8}） | 是 |
| `rise_time_ns` | float ns 上升时间 t_r 10%→90%（[0.6,1.0] 规范窗，缺省 0.7） | 否 |
| `n_points` | int 波形采样点数（[50,5000]，缺省 401） | 否 |
| `t_max_ns` | float ns 波形时窗（[30,200]，缺省 100） | 否 |

## exposure_compliance_distance

EIRP 合规距离（远场球面反解）：R=√(EIRP_W/(4π·S_lim))；同几何远场 E=√(30·EIRP)/R 与 S=E²/η0 恒等（η0=4π·30）；plane_wave_equiv 段（FCC <300 MHz）如实标注；无 S 列段（ICNIRP 0.1–30 MHz恒近场域）显式拒绝；近场不判（note 声明）

| 参数 | 说明 | 必填 |
|---|---|---|
| `eirp_w` | float W 等效全向辐射功率（线性瓦，>0） | 是 |
| `freq_hz` | float Hz 工作频率 | 是 |
| `standard` | str - fcc_occupational\|fcc_general\|icnirp_public | 否 |

## exposure_mpe_limit

RF 暴露 MPE/参考水平查表：FCC 47 CFR §1.1310(e)(1) Table 1（fcc_occupational/fcc_general）+ ICNIRP 2020 Table 5 全身平均公众（icnirp_public）→ E(V/m)/H(A/m)/S(W/m²) 限值与平均时间；域外显式拒绝（FCC 0.3–100000 MHz、ICNIRP 0.1–300000 MHz）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_hz` | float Hz 工作频率 | 是 |
| `standard` | str - fcc_occupational\|fcc_general\|icnirp_public | 否 |

## fade_outage_percent

衰落中断概率：AP-7 小尺度/阴影衰落中断概率 [%]（P(接收功率 < 中值−margin_db)，功率门限相对平均功率归一）：kind='rice' 走非中心 χ² CDF（≡1−Marcum-Q1，scipy.special.chndtr 等价路径，K 线性值，K→0 退化为 Rayleigh 实测 3e-17）；'rayleigh' 闭式 1−exp(−h)；'nakagami' 走正则化不完全 Gamma P(m,mh)（m≥0.5，m=1≡Rayleigh）；'lognormal' 对数正态阴影 0.5·erfc(M/(σ√2))（M=σ 时 15.87% 锚）

| 参数 | 说明 | 必填 |
|---|---|---|
| `margin_db` | float dB 衰落裕量（≥0，相对中值/平均功率） | 是 |
| `kind` | str 'rice'/'rayleigh'/'nakagami'/'lognormal'（默认 'rice'） | 否 |
| `k` | float Rice K 因子线性值（≥0，默认 10.0≈10dB；仅 rice 用） | 否 |
| `m` | float Nakagami-m（≥0.5，默认 1.0；仅 nakagami 用） | 否 |
| `sigma_db` | float 对数正态阴影标准差 dB（>0，默认 8.0；仅 lognormal 用） | 否 |

## folded_dipole_zin

折合偶极输入阻抗（等线径，传输线法两模分解）：天线模=等效偶极阻抗 Z_d（dipole_emf_zin 路线复用）与传输线模=短路线 l/2 输入阻抗 2jZ_t·tan(kl/2)（Z_t=(η/π)·acosh(s/2a) 空气双线）在馈点并联——Z_in=4Z_d·Z_tl/(4Z_d+Z_tl)；谐振 l=λ/2 处 tan→∞ → Z_in=4Z_d（等粗 4×：73.1Ω→292Ω≈300Ω 教科书口径，线径/间距谐振点约去=恒等锚）；l=mλ 处 Z_in=0 短路边定性钉；step_up=Z_in/Z_d 复数输出。不等线径 Mushiake 步升比与包络等效半径修正不在本键口径（如实不做）

| 参数 | 说明 | 必填 |
|---|---|---|
| `length_mm` | float mm 折合偶极总长 l（∈(0,λ)，与 Z_d 同域） | 是 |
| `f_ghz` | float GHz 工作频率（>0） | 是 |
| `wire_radius_mm` | float mm 导线半径 a（>0） | 是 |
| `spacing_mm` | float mm 两线中心距 s（>2·wire_radius_mm，线不重叠） | 是 |

## form_beta_linear

FORM可靠度：XD-11 FORM 一阶可靠度·线性极限状态面便捷键：g(x)=offset−Σcoeff_i·x_i<0 失效（Hasofer-Lind 1974 β 几何定义 / Rackwitz-Fiessler 1978 HL-RF 迭代；OpenTURNS FORM 例题族方法学参照）。线性面 HL-RF 一步到解且与闭式 β=(offset−aᵀμ)/||a·σ|| 逐位一致（双路径互证字段 beta_closed_form）；Pf=Φ(−β)；α=a·σ/||a·σ||=失效方向单位灵敏度（|α_i| 大=第 i 个参数的公差/σ 把 Pf 拖得最狠）。stddev 逐元素>0；均值点已入失效域（β<0）如实返回 Pf>0.5 不翻符号。非线性面走 core.form_reliability.form_beta（黑盒 callable）直调

| 参数 | 说明 | 必填 |
|---|---|---|
| `coeffs` | list[float] 线性系数 a（g=offset−a·x；非全零） | 是 |
| `offset` | float 截距 offset=g(0)（安全裕度项，>0=均值点安全） | 是 |
| `mean` | list[float] 各变量均值 μ（与 coeffs 等长） | 是 |
| `stddev` | list[float] 各变量标准差 σ（逐元素>0） | 是 |

## gaseous_attenuation

大气气体衰减：AP-6 大气气体 specific attenuation γ [dB/km]（ITU-R P.676-13 Annex 1 逐线求和：O2 44 行+H2O 35 行谱线+干空气连续谱，式(1)-(9) 原文式号）：γ=0.1820·f·N″(f)；p_hpa 为干空气分压（总压 ptot=p+e）、θ=300/T、e=ρT/216.7。有效域 f∈(0,1000]GHz。系数表经 AP-8 批逐值录入+前席 dump 553 值对拍（模块 docstring 状态节）；数据文件 PV-011 不捆绑

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_hz` | float Hz 频率（(0,1000GHz]） | 是 |
| `p_hpa` | float hPa 干空气分压（>0；P.676 约定 ptot=p+e） | 是 |
| `t_k` | float K 热力学温度（>0） | 是 |
| `rho_wv_g_m3` | float g/m³ 水汽密度（>=0，0=干空气；缺省 7.5 ≈ITU-R P.835 标准大气地面值量级） | 否 |

## gstc_forward

GSTC正演：MM-3 GSTC 正向（规格 §C-2，arXiv 1408.0273v2=IEEE TAP 63(7) 2015 Eq.(17)/(18) 逐式）：法向入射单轴 Huygens 面 χ_ee/χ_mm（米；实数或 [re,im] 对）→ 共极化 T/R（[re,im]）+ 能量 |R|²+|T|²、dB/相位与 2×2 S 面（互易）。无源守卫 |R|²+|T|²≤1+1e-9 违即显式报错（本式口径无耗=χ 实数、Im χ>0=增益非物理）；χ_em/χ_me 交叉耦合闭式原文未给显式不做（参数位保留，传非 None 拒绝）；x/y 极化法向入射简并同结果。

| 参数 | 说明 | 必填 |
|---|---|---|
| `chi_ee` | float\|[re,im] 面电极化率 χ_ee（米；无耗=实数，Im>0 即增益必拒） | 是 |
| `chi_mm` | float\|[re,im] 面磁极化率 χ_mm（米，同上） | 是 |
| `freq_ghz` | float 频率 GHz（>0；k=2πf/c₀ 真空口径） | 是 |
| `polarization` | str 'x'\|'y'（法向入射共极化简并；默认 'x'） | 否 |
| `chi_em` | float\|[re,im] 显式不做：传非 None 即 ValueError（闭式原文未给） | 否 |
| `chi_me` | float\|[re,im] 显式不做：传非 None 即 ValueError（闭式原文未给） | 否 |

## gstc_lut_crosscheck

MM-3 GSTC 带内对拍通道（规格 §C-2：ms 真机单胞 Γ/T→χ 反演→正演回对拍，J4 Floquet 锚通道接口面；真机正演腿后接）：频带 (Γ,T) 复数组（实数或 [re,im] 对，freq_ghz 严格升序）→ 逐点 Eq.(19) χ 反演 → 正演回带内 Δ|T|_dB 门（gate_dt_db 缺省 0.5dB 起步）。返回 verdict/max_dt_db/逐点 χ 与 Δ|T|。诚实边界：离线通道正反两腿同源闭式 → Δ|T|≈1e-13dB（门判接口/管线破坏），判别力在 J4 Floquet 锚真机侧到位；|T|=0 点无有限 dB 诚实剔除（n_dt_excluded 计数，全剔除判 UNKNOWN 不凑 PASS）。

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | array 频率 GHz（一维严格升序正数） | 是 |
| `s11` | array 逐频点反射系数 Γ（实数或 [re,im] 对） | 是 |
| `s21` | array 逐频点透射系数 T（实数或 [re,im] 对） | 是 |
| `band_ghz` | array [f_lo, f_hi] 带内窗（GHz；缺省全带） | 否 |
| `gate_dt_db` | float 带内 Δ\|T\| 门（dB，>0；缺省 0.5） | 否 |

## gstc_synthesize

GSTC综合：MM-3 GSTC 逆解（规格 §C-2，arXiv 1408.0273v2 Eq.(19) 逐式）：目标共极化 (T,R)（[re,im]）→ 面极化率 χ_ee/χ_mm 反演 + Eq.(19)↔Eq.(17) 往返自检（逐位 ≤1e-12，违即 RuntimeError 显式失败——代数上应精确恒等）。|T±R+1|→0 的 χ→∞ 极点域（如 T=−1 全反 Huygens 极限）显式拒绝不外推；正向无源守卫不套用于本键（实测目标可轻微超物理，χ 可实现性归调用方判读）。

| 参数 | 说明 | 必填 |
|---|---|---|
| `t` | float\|[re,im] 目标透射系数 T（复数） | 是 |
| `r` | float\|[re,im] 目标反射系数 R（复数） | 是 |
| `freq_ghz` | float 频率 GHz（>0；k=2πf/c₀ 真空口径） | 是 |

## gt_ratio

G/T优值：LT-1 G/T 组合优值（ITU-R S.733-2 定义口径）：G/T = G_dB − 10·log10(T_sys) [dB/K]。T_sys 三路径显式择一：t_sys_k 直接给定 / nf_db（=cascade_budget.nf_total_db 直连，Te=T0·(F−1)）/ t_e_k（=nf_measurement y-factor 链等效输入噪声温度）；t_ant_k 并入系统温度，三者全缺省时退化为 antenna_only（T_sys=t_ant_k，如实标注）。t_sys_k/nf_db/t_e_k 同给按优先级取用并如实报告冗余

| 参数 | 说明 | 必填 |
|---|---|---|
| `gain_db` | float dB 接收链指向源方向总增益（cascade_budget.gain_total_db 同名直连） | 是 |
| `t_sys_k` | float K 系统噪声温度直接给定（可选，优先级最高） | 否 |
| `nf_db` | float dB 系统总噪声系数（可选；→ Te=T0·(F−1)） | 否 |
| `t_e_k` | float K 接收机等效输入噪声温度（可选，nf_measurement te_from_y 链输出） | 否 |
| `t_ant_k` | float K 天线噪声温度（默认 290） | 否 |
| `t0_k` | float K NF→Te 换算基准（默认 290，IEEE 口径） | 否 |

## guanella_tlt_design

Guanella 传输线变压器设计：n²:1 阻抗比口径——线数 n=√(r_in/r_out)（非完全平方整数比如 5:1 显式拒绝）、每线最优特性阻抗 Z0=√(r_in·r_out)（全频段理想匹配定理口径）、低阻侧每线视入负载 n·r_out；可选 f_max 给 θ≤45°（λ/8 准则）线长上限；低频磁化电感拐角依赖磁芯数据如实不做（UNVERIFIED）

| 参数 | 说明 | 必填 |
|---|---|---|
| `r_in_ohm` | float Ω 高阻侧端口阻抗（=n²·r_out） | 是 |
| `r_out_ohm` | float Ω 低阻侧端口阻抗（>0） | 是 |
| `f_max_ghz` | float GHz 上限频率（可选；给则出 λ/8 线长上限） | 否 |
| `v_f` | float 线相速因子（0<v_f≤1，缺省 1.0） | 否 |

## guanella_tlt_response

Guanella 传输线变压器频响：n 条相同无耗线串入并出复合拓扑逐频精确解——4 端子线 Y 参量（Y_self=−j cotθ/Z0、Y_mut=j cscθ/Z0）盖章+链节点消元+不等参考阻抗 D 标度 2 口 S；s11/s21 dB+无耗功率守恒+互易残差；最优 Z0=√(r_in·r_out) 缺省（全频匹配定理锚）；θ=kπ 显式拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `r_in_ohm` | float Ω 高阻侧端口阻抗（=n²·r_out） | 是 |
| `r_out_ohm` | float Ω 低阻侧端口阻抗（>0） | 是 |
| `length_mm` | float mm 每线物理长度（>0） | 是 |
| `freq_ghz` | array GHz 频率轴（>0；避开 θ=kπ 点） | 是 |
| `v_f` | float 线相速因子（0<v_f≤1，缺省 1.0） | 否 |
| `z_line_ohm` | float Ω 每线特性阻抗（缺省 √(r_in·r_out) 最优口径；失配对照显式给值） | 否 |

## gysel_core_synthesize

Gysel 功分器 core 闭式综合：等分大功率口径——臂 √2·Z0、隔离线/桥带 Z0（桥带 λ/2 中点=对称面真实节点）、Δ1/Δ2 外置 Z0 负载（可独立散热=与内嵌电阻 Wilkinson 的族界）；偶/奇模半电路闭式验证 Γe=Γo=0（有限代理端接+缩比收敛）+理想 f0 三口 S 矩阵（S21=S31=−j/√2、S32=0、互易非幺正如实注记）。锚：半电路测试侧独立重解 ≤1e-9；−3.0103dB 恒等；无桥带判废对照（#206）。纯电气口径不出几何尺寸（模板级走 synthesize_gysel_model）

| 参数 | 说明 | 必填 |
|---|---|---|
| `z0_ohm` | float Ω 系统/端口/负载阻抗（>0，缺省 50） | 否 |

## gysel_frequency_response

Gysel 功分器精确频响：五线六节点导纳网络（臂×2=√2·Z0 λ/4@f0、隔离线×2=Z0 λ/4@f0、桥带按中点 M 拆两半段、Δ1/Δ2 外置 Z0 负载）逐频精确解——S11/S21/S31 dB+P2↔P3 隔离+幅度失衡+耗散守恒残差；f0 锚 vs 理想矩阵（−3.0103dB/全匹配/全隔离）逐位 ≤1e-9；无桥带判废对照字段（桥带必要性 #206 同口径）。θ=kπ（f=2k·f0）显式拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `f0_ghz` | float GHz 中心频率（线节长=λ/4@f0；>0） | 是 |
| `freq_ghz` | array GHz 频率轴（>0；避开 f=2k·f0 奇异点） | 是 |
| `z0_ohm` | float Ω 系统/端口/负载阻抗（>0，缺省 50） | 否 |

## hata_cost231

Hata经验路损：AP-5 Hata/COST-231 经验中值路损（Rappaport §4.10 承载，统一域盒 150–2000MHz）：150–1500MHz 走 Okumura-Hata 原式，1500–2000MHz 走 COST-231 Hata 扩展（urban=metropolitan C=3dB）；env=suburban/open 走 Hata 修正式（COST 段外推档如实标注）。域盒 f∈[150,2000]MHz/d∈[1,20]km/h_b∈[30,200]m/h_m∈[1,10]m，域外显式 ValueError

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_mhz` | float MHz 频率（域盒 [150,2000]） | 是 |
| `d_km` | float km 收发距离（域盒 [1,20]） | 是 |
| `h_b_m` | float m 基站天线有效高度（域盒 [30,200]） | 是 |
| `h_m_m` | float m 移动台天线高度（域盒 [1,10]） | 是 |
| `env` | str 'urban'/'suburban'/'open'（默认 'urban'） | 否 |

## helix_axial_bandwidth

轴向模工作带宽（周长域判据频率域换算）：周长固定时 C_λ(f)=C_λ0·(f/f0) 落设计规程域 [0.75, 4/3] 的频率区间——f_low=f0·0.75/C_λ0、f_high=f0·(4/3)/C_λ0，输出带边/带宽/比值与 f0 是否在带内。诚实边界：这是**周长域判据的频率域换算**，非增益/阻抗带宽估计（core 诚实边界 4，文献口径 ~1.78:1 波束带宽不在本键）

| 参数 | 说明 | 必填 |
|---|---|---|
| `f0_ghz` | float GHz 设计中心频率（>0） | 是 |
| `c_lambda` | float 设计点周长波长数 C_λ0（>0） | 是 |

## helix_axial_design

轴向模螺旋反设计双 route：给 n_turns → for_n_turns（N 整数化后尺寸唯一，C_λ=(D0/(15·N·tanα))^(1/3) 或 HPBW 形）；不给 n_turns → optimal（在 [n_min,n_max] 整数圈内选 C_λ 最靠带心=带宽余量最大的解，同距取更小 N）。输出直径/螺距/节距角/总轴长几何+随行 performance（design→performance 往返自洽 1e-9）。解出 C_λ 出规程域或 N≤3 → warnings 如实登记不拒绝（域外解是合法数学解，采信由调用方决定）

| 参数 | 说明 | 必填 |
|---|---|---|
| `f0_ghz` | float GHz 中心频率（>0） | 是 |
| `n_turns` | float 圈数（可选；给则 route=for_n_turns，≥1） | 否 |
| `alpha_deg` | float ° 螺距角（缺省 13.0=规程域 [12°,14°] 带心） | 否 |
| `target_metric` | str 反设计目标度量：'directivity'（线性）\| 'hpbw_deg'（度），缺省 directivity | 否 |
| `target_value` | float 目标值（>0，同度量纲），缺省 30.0 | 否 |
| `n_min` | int optimal 路线圈数下限（≥1），缺省 4 | 否 |
| `n_max` | int optimal 路线圈数上限（≥n_min），缺省 64 | 否 |

## helix_axial_performance

轴向模螺旋天线 Kraus 闭式性能：HPBW=52/(C_λ√(N·S_λ))、FNBW=115/(C_λ√(N·S_λ))、D0=15·N·C_λ²·S_λ（线性+dB）、Zin≈140·C_λ、轴上轴比 AR=1+1/(2N)；随行轴向模域 verdict（0.75<C_λ<4/3、12°<α<14°、N>3 严格，恰等出域）与失效域 warnings（N≤3 不静默）。锚（Balanis §10.3.1 工作例 N=10/f0=10GHz/C_λ=0.95/α=14°）：HPBW=35.5658°/FNBW=78.6551°/D0=32.0651（15.0603dB）/Zin=133Ω

| 参数 | 说明 | 必填 |
|---|---|---|
| `f0_ghz` | float GHz 中心频率（>0） | 是 |
| `n_turns` | float 圈数（≥1；≤3 为 Kraus 失效域，warnings 如实登记不拒绝） | 是 |
| `alpha_deg` | float ° 螺距角（0<α<90 物理可建域；设计规程域 12°<α<14°） | 是 |
| `c_lambda` | float 周长波长数 C/λ（>0；与 diameter_mm 二选一，同给须一致相对偏差 ≤1e-9） | 否 |
| `diameter_mm` | float mm 螺旋直径（>0；与 c_lambda 二选一，C=πD） | 否 |
| `include_axial_ratio` | bool 缺省 True；False 时 axial_ratio=None | 否 |

## homog_mix_eff

MM-7 三混合式统一面（规格 §五 :154，通用 core 内核）：rule ∈ maxwell_garnett（Garnett 1904 球夹杂稀疏极限，depol 因子 L 椭球广义）/bruggeman（Bruggeman 1935 对称有效介质，要求 L∈(0,1]）/looyenga（Looyenga 1965 立方根加权）——复数 ε 全程（e^{-jωt} 口径 Im≥0 无源）。depol 形状族：球=1/3、沿场细棒=0（仅 MG，退化为 Wiener 上界并联）、法向薄片=1（MG 退化为 Wiener 下界串联）。附 Wiener 双界（算术/调和）；实数输入报告界内判读、复数输入界不有序 如实 None。L=1/3 实数输入与 humidity_drift 球形闭式逐式一致

| 参数 | 说明 | 必填 |
|---|---|---|
| `rule` | str 'maxwell_garnett'\|'bruggeman'\|'looyenga' | 是 |
| `er_matrix` | float\|[re,im] 基质 ε_m（Re>0，Im≥0） | 是 |
| `er_inclusion` | float\|[re,im] 夹杂 ε_i（Re>0，Im≥0） | 是 |
| `v_inclusion` | float 夹杂体积分数 ∈[0,1]（端点恒等直返） | 是 |
| `depol` | float depolarization 因子 L ∈[0,1]（默认 1/3=球形） | 否 |

## hybrid_sum_difference

魔 T/180° 混合结和差合成：双侧臂复数输入（dBm+相对相位）→ 和口 b_sum=(a2+a3)/√2 与差口 b_diff=(a2−a3)/√2 功率（dBm，null 如实 None）+占总功率份额；能量守恒 |b_sum|²+|b_diff|²=|a2|²+|a3|² 恒等（残差字段）；等幅同相→差口 null（隔离）、反相→和口 null、正交→恰各半 −3.0103dB。锚：与 magic_tee_s_matrix 全矩阵乘 b=S·a 匹配负载口径跨键逐位互证；正交 3.0103dB 恒等

| 参数 | 说明 | 必填 |
|---|---|---|
| `p2_dbm` | float dBm 侧臂 2 输入功率（∈[−300,300]） | 是 |
| `p3_dbm` | float dBm 侧臂 3 输入功率（∈[−300,300]） | 是 |
| `phase_deg` | float deg 侧臂 3 相对侧臂 2 的相位（缺省 0=同相） | 否 |

## if_plan_sweep

DP-5 IF 频率规划扫掠：IF 候选网格逐点重取本振（low/high 侧注入）→ 逐点杂散落带判定 + spurious-free 窗口表（窗口边界=网格分辨率内）

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_rf_hz` | float Hz RF 中心频率（>0） | 是 |
| `if_lo_hz` | float Hz IF 扫掠下限（>0） | 是 |
| `if_hi_hz` | float Hz IF 扫掠上限（low 侧须 <f_RF） | 是 |
| `side` | str 注入侧 'low'\|'high'（默认 low：f_LO=f_RF−IF） | 否 |
| `n_points` | int 网格点数（默认 201） | 否 |
| `if_bw_hz` | float Hz 目标带宽（默认 0） | 否 |
| `rf_bw_hz` | float Hz RF 信号带宽（默认 0） | 否 |
| `lo_bw_hz` | float Hz LO 带宽（默认 0） | 否 |
| `max_order` | int 最大阶数 m+n（默认 7） | 否 |

## interdigital_bars_capacitance

交指杆偶奇电容闭式：零厚度耦合杆条带线（平行板间距 b，Getsinger 1962 薄条极限）共形映射精确解——(w,s,b,εr) → 偶/奇模阻抗 Z0e/Z0o、每米电容 C_e/C_o、耦合系数 k=(C_o−C_e)/(C_o+C_e)、倒置器 J=v·(C_o−C_e)/2。锚：s→∞ 退化单杆条带线精确值（rf_line 跨键逐位）；s→0 偶模=并合 2w 条电容之半（Landen 恒等）；k 的电容/阻抗两式恒等

| 参数 | 说明 | 必填 |
|---|---|---|
| `w_mm` | float mm 杆宽（>0） | 是 |
| `s_mm` | float mm 缝宽（>0） | 是 |
| `b_mm` | float mm 两接地平板间距（>w_mm） | 是 |
| `epsilon_r` | float 填充介质相对介电常数（≥1） | 是 |

## interdigital_bpf_synthesize

交指带通综合（Getsinger 等效网络）：全极点切比雪夫 g 值 → λ/4 短路杆斜率 b=π/(4Z_r) → J 倒置器目标 → 逐节 (C_e,C_o) 闭式 → 零厚度耦合杆条带线二维反解杆宽/缝 mm → 杆长 λ/4@√εr。锚：J 往返逐位；对称滤波器缝回文（s_1=s_{n+1}）；J·4Z_r/π=δ/√(g_jg_{j+1}) 构造恒等；δ↑ 缝单调收窄

| 参数 | 说明 | 必填 |
|---|---|---|
| `order` | int 阶数 N（≥2；谐振器数，耦合缝=N+1） | 是 |
| `f0_ghz` | float GHz 中心频率（>0） | 是 |
| `fbw` | float 相对带宽 δ（0<δ≤1） | 是 |
| `ripple_db` | float dB 通带等纹波（>0） | 是 |
| `b_mm` | float mm 接地平板间距（>0；条带线介质档口径） | 是 |
| `epsilon_r` | float 填充介质相对介电常数（≥1） | 是 |
| `z0_ohm` | float Ω 端口阻抗（>0，缺省 50） | 否 |
| `z_r_ohm` | float Ω 杆特性阻抗目标 Z0e·Z0o=Z_r²（>0，缺省=z0_ohm） | 否 |

## ipc2152_trace_temp_rise

IPC-2152 走线载流温升：线宽/铜厚/电流 → ΔT（Brooks & Adam 拟合 ΔT=K·I^a·W^b·Th^c，W/Th 以 mil 计；系数取自 KiCad 独立实现）。IPC-2152 结论：内层不按 IPC-2221 的老规矩 ×2 降额

| 参数 | 说明 | 必填 |
|---|---|---|
| `width_mm` | float mm 走线宽度（>0） | 是 |
| `copper_oz` | float oz/ft² 铜厚（1 oz ≈ 1.378 mil） | 是 |
| `current_a` | float A 走线电流（DC/RMS，≥0） | 是 |
| `internal` | bool 是否内层（默认 False） | 否 |

## iq_imbalance_irr

IQ失衡分析：MT-4 件 1 IQ 失衡 → 镜像抑制比 + EVM 贡献（round17 MT-4，Razavi 式 IRR=(1+ε²+2εcosφ)/(1+ε²−2εcosφ)，ε=Q/I 增益比线性、φ=正交相位误差；ε=1 退化 cot²(φ/2)）+ 3GPP TS 38.141-1 EVM 消费口径折算（evm_rms²=镜像/信号功率=1/IRR；IRR 本身不设 3GPP 限值门——限值面out-of-scope 如实注明）。完全平衡（0 dB+0°）→ irr_db=None（∞ 的 JSON 契约面）、evm=0；完全反相（0 dB+±180°）→ 信号支路零输出、EVM 无界走 None+full_image 旗标。|φ|>180° 显式拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `amp_imbalance_db` | float I/Q 增益失衡 dB（ε=10^(a/20)；同值异号 IRR 相同） | 是 |
| `phase_imbalance_deg` | float 正交相位误差 deg（\|φ\|≤180；符号=旋转方向，IRR 同值） | 是 |

## isolator_ideal_sparams

隔离器理想 2 口 S 口径：非互易铁氧体件（reciprocal=False 豁免位）dB 规格参数化——前向 s21=10^(−IL/20)、反向 s12=10^(−Iso/20)（None=理想全隔离）、s11=s22=10^(−RL/20)（None=理想匹配）；无源性一致性守卫（γ²+c²≤1 双口）违约显式拒绝；理想极限档回 canonical [[0,0],[1,0]]

| 参数 | 说明 | 必填 |
|---|---|---|
| `il_db` | float dB 前向插损 IL（≥0，缺省 0=理想无耗） | 否 |
| `isolation_db` | float dB 反向隔离度 Iso（≥0 或 None=∞ 理想隔离） | 否 |
| `rl_db` | float dB 双口回损 RL（≥0 或 None=理想匹配） | 否 |

## k_split_pair

模分裂耦合：双峰模分裂耦合系数（Hong & Lancaster 精确式 k=(f2²−f1²)/(f2²+f1²)，df6 A1 R4）：|S21| dB 双主峰抛物线细化+KSPLIT_RULE 峰检（prominence 0.5dB HFSS 锚同款+通带邻域守卫）；偏置曲线 log-log 逆映射修正；双峰不可分如实 None（#122）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_hz` | ndarray Hz 升序扫频栅格 | 是 |
| `s21` | ndarray complex 复 S21（等长） | 是 |
| `bias_raw_grid` | list\|None 偏置曲线 raw k 节点（缺省 None 不修正） | 否 |
| `bias_true_grid` | list\|None 对应 true k 节点 | 否 |

## klopfenstein_taper

Klopfenstein 阻抗渐变段综合：z1→z2 渐变（skrf.taper.Klopfenstein 剖面 + 微带 MLine 同源宽度剖面）→ 阻抗/宽度剖面、通带回损估计、βL≥A 通带条件核验。rmax=通带反射因子 sech(A)，通带纹波 ρ0=Γ0·rmax（Γ0=½|ln(z2/z1)|，Pozar §5.9 参数化恒等）

| 参数 | 说明 | 必填 |
|---|---|---|
| `z1_ohm` | float Ω 起端阻抗 | 是 |
| `z2_ohm` | float Ω 末端阻抗（≠z1） | 是 |
| `length_mm` | float mm 渐变段物理长度 | 是 |
| `epsilon_r` | float - 基板相对介电常数（>1） | 是 |
| `h_mm` | float mm 基板厚度 | 是 |
| `freq_ghz` | float GHz 设计频率（βL 条件核验点） | 是 |
| `rmax` | float - 通带反射因子 ρ0/Γ0，(0,1) 开区间（缺省 0.1） | 否 |
| `n_sections` | int - 剖面离散段数 5..401（缺省 81） | 否 |
| `tand` | float - 损耗正切（默认 0） | 否 |

## knife_edge_loss

刃形绕射损耗：AP-5 刃形绕射损耗（ITU-R P.526-15 §4，Fresnel-Kirchhoff 参数 v）：method='exact' 走 Fresnel 积分精确值（J(0)=6.02dB 擦顶锚）；'approx' 走 P.526 闭式 6.9+20log10(√((v−0.1)²+1)+v−0.1)（v≤−0.78 记 0）；'lee' 走 Rappaport §4.11 分段式（v>2.4 档 20log(v/0.225)）。返回恒含三档数值供互检（exact vs approx 最大偏差 ~0.12dB@−0.7..6）

| 参数 | 说明 | 必填 |
|---|---|---|
| `v` | float Fresnel-Kirchhoff 绕射参数（无量纲；>0=障碍遮挡视线） | 是 |
| `method` | str 'exact'/'approx'/'lee'（默认 'exact'） | 否 |

## loaded_line_phaser

加载线移相器：双并联可切换电纳格胞（jb|θ线|jb）二态相移——设计正解 Δφ→b=2tan(Δφ/2)/间距 θ=90°−Δφ/2（匹配 b=2cotθ，S11=0 精确）或 ABCD 格胞分析反解 b/θ→S11/S21/差分相移（route 二选一）；差分相移闭式 Δφ=2arctan(b/2)、等效匹配线 θ'=180°−θ；随行集总 C/L 实现值；Δφ≥180° 显式拒绝（b→∞ 指回开关线口径）

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 工作频率（>0） | 是 |
| `ereff` | float 线有效相对介电常数（≥1，准 TEM 色散均值） | 是 |
| `z0_ohm` | float Ω 线特性阻抗（>0，缺省 50） | 否 |
| `delta_phi_deg` | float° 目标差分相移（0<Δφ<180 开区间；设计路线，与 susceptance_norm/spacing_deg 二选一） | 否 |
| `susceptance_norm` | float Z0 归一化并联电纳 b（≠0 有限；分析路线） | 否 |
| `spacing_deg` | float° 两电纳间线电长度 θ（0<θ<90 开区间；分析路线） | 否 |

## magic_tee_s_matrix

魔 T 理想 S 矩阵口径：匹配 E/H 混合结 4 口——端口 1=H 臂和口/4=E 臂差口/2·3=侧臂互隔离；S 矩阵 + 幺正残差 + E/H 臂隔离 S14=0 + 3dB 均分 |S21|²=0.5 + 激励口逐端口输出功率与相位行为（激励 1→侧臂同相 0°、激励 4→侧臂反相 180°、激励 2→和/差口各半）。锚：SS†=I 测试侧 numpy 独立复算；3.0103dB/隔离/相位三常数恒等；与 hybrid_sum_difference 跨键矩阵乘互证。注意：理想口径出 S 矩阵与功率分配，不出波导尺寸综合

| 参数 | 说明 | 必填 |
|---|---|---|
| `excite_port` | int 激励端口 ∈{1,2,3,4}（缺省 1=H 臂和口） | 否 |

## mask_filter_synthesize

mask→滤波器规格综合闭环：遮罩→闭式最小阶→cm_core (N+2) 耦合矩阵→矩阵频响逐段回验裕量→不足自动 +1 重试（max_order_extra 上限），报告各阶裕量轨迹与最紧段。min_order_override 可钉起步阶（轨迹演示/调用方钉阶）；全程零仿真纯确定性（铁律 7）

| 参数 | 说明 | 必填 |
|---|---|---|
| `mask` | dict - 遮罩规格（MaskSpec.to_dict() 形态；内置模板见 fcc_15_247_dts_2g4 / ieee_80211_dsss_2g4 / nr_aclr_20mhz_envelope） | 是 |
| `required_margin_db` | float dB 各段所需设计裕量（默认 0，进闭式） | 否 |
| `max_order_extra` | int - 起步阶之上最多重试阶数（默认 3） | 否 |
| `min_order_override` | int - 显式起步阶（缺省=闭式最小阶） | 否 |
| `topology` | str - 拓扑（当前仅 chebyshev 全极点） | 否 |

## mask_margin_report

给定阶数滤波器 vs 发射遮罩的裕量报告：阶数→cm_core Cameron N+2 耦合矩阵→矩阵频响（−20lg|S21|，几何映射采样）→逐遮罩段裕量 dB+最紧段+PASS/FAIL；含耦合矩阵与响应采样。贴滤波器责任起点（通带边缘+guard）的段如实标注并按负裕量判 FAIL（Ω=1 处衰减=纹波电平）

| 参数 | 说明 | 必填 |
|---|---|---|
| `mask` | dict - 遮罩规格（MaskSpec.to_dict() 形态；内置模板见 fcc_15_247_dts_2g4 / ieee_80211_dsss_2g4 / nr_aclr_20mhz_envelope） | 是 |
| `order` | int - 滤波器阶数（≥1） | 是 |
| `required_margin_db` | float dB 各段所需设计裕量（默认 0） | 否 |

## mask_min_order

遮罩最小阶数：发射遮罩→切比雪夫滤波器最小阶（经典 acosh 闭式，多段逐段取最大）：N=ceil(acosh(√((10^(A/10)−1)·K))/acosh(Ωs))，K=10^(RL/10)−1；Ωs 为段约束点（内缘裁剪到通带边缘+guard_offset_ghz 调制滚降信用区）经几何映射 Ω=(f/f0−f0/f)/fbw 的归一化频（fbw=u(2+u)/(1+u) 精确反解，使 Ω(±通道半宽)=±1）。返回阶数/回损分配/带内纹波/逐段 Ω 与需求明细；贴边段要求超过纹波电平如实报错（全极点在 Ω=1 只能提供纹波衰减）

| 参数 | 说明 | 必填 |
|---|---|---|
| `mask` | dict - 遮罩规格（MaskSpec.to_dict() 形态；内置模板见 fcc_15_247_dts_2g4 / ieee_80211_dsss_2g4 / nr_aclr_20mhz_envelope） | 是 |
| `required_margin_db` | float dB 各段所需设计裕量（默认 0，进闭式） | 否 |
| `topology` | str - 拓扑（当前仅 chebyshev 全极点，显式拒绝其他） | 否 |

## microstrip_analysis

微带线分析：线宽 → (Z0, εeff)。skrf HJ 模型

| 参数 | 说明 | 必填 |
|---|---|---|
| `width_mm` | float mm 导带宽度 | 是 |
| `freq_ghz` | float GHz 频率 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `h_mm` | float mm 基板厚度 | 是 |
| `tand` | float - 损耗正切（默认 0） | 否 |

## microstrip_lambda_g

微带 λg：给定几何/频率 → εeff、λ0、λg

| 参数 | 说明 | 必填 |
|---|---|---|
| `width_mm` | float mm 导带宽度 | 是 |
| `freq_ghz` | float GHz 频率 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `h_mm` | float mm 基板厚度 | 是 |

## microstrip_loss_heat

微带导体/介质损耗 → 等效线热源：匹配行波 P_loss/m = 2(α_c+α_d)·P（Pozar §2.7）。α_c=R'/(2Z0)（R'=Rs/w，趋肤 Rs=√(ωμ0/2σ)）、α_d=π·f·tanδ·√εeff/c

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | float GHz 频率（>0） | 是 |
| `power_w` | float W 传输功率（匹配负载，>0） | 是 |
| `z0_ohm` | float Ω 特性阻抗（>0） | 是 |
| `eps_eff` | float - 有效介电常数（>0） | 是 |
| `tand` | float - 损耗正切（≥0） | 是 |
| `width_mm` | float mm 导带宽度（面密度用，>0） | 是 |
| `sigma_s_per_m` | float S/m 导体电导率（默认铜 5.8e7） | 否 |

## microstrip_synthesis

微带线综合：目标 Z0 → 线宽（brentq 求逆 + 自洽回代）

| 参数 | 说明 | 必填 |
|---|---|---|
| `z0_ohm` | float Ω 目标特性阻抗 | 是 |
| `freq_ghz` | float GHz 频率 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `h_mm` | float mm 基板厚度 | 是 |
| `tand` | float - 损耗正切（默认 0） | 否 |

## microwave_process_window

工艺窗口热失控：LT-7 烘干/烧结工艺窗口+热失控（round18 :142）：Foster (R,τ) 阶跃热响应（复用 thermal_transient.step_response_zth，MP-1 零改动）→ 目标温度功率/时间窗（保持功率 ΔT/ΣR、工艺时刻所需功率 ΔT/Z_th(t)、给定功率到达时间二分反解、稳态越限旗标）；可选失控块（全给或全不给）：tanδ(T)=tanδ_ref·e^{α(T−T_ref)} 体吸收链 P(T)→定点迭代（方法论同 thermal_iteration）+稳定性斜率 R_th·dP/dT 临界+解析失控界 α_crit=1/(e·R_th·P0)（收敛/失控分界由锚树复现）。体吸收为 rms 场口径

| 参数 | 说明 | 必填 |
|---|---|---|
| `r_th_c_per_w` | array Foster 热阻表 °C/W（非空逐项 >0） | 是 |
| `tau_s` | array Foster 时间常数表 s（等长逐项 >0） | 是 |
| `ambient_c` | float °C 环境温度 | 是 |
| `target_c` | float °C 目标温度（>ambient_c） | 是 |
| `t_max_c` | float °C 温度上限（≥target_c；给功率窗上沿/越限旗标） | 否 |
| `t_process_s` | float s 工艺时刻（>0；给所需功率/功率窗） | 否 |
| `power_w` | float W 给定功率（>0；给到达时间） | 否 |
| `f_ghz` | float GHz 加热频率（失控块触发键） | 否 |
| `e_rms_v_per_m` | float V/m rms 场强（失控块） | 否 |
| `load_v_l` | float L 负载体积（失控块） | 否 |
| `eps_r` | float - 负载 εr（>0，缺省 1） | 否 |
| `tan_d_ref` | float - 参考温度 tanδ（失控块，>0） | 否 |
| `alpha_per_k` | float 1/K tanδ 指数温升系数（失控块） | 否 |
| `t_ref_c` | float °C 材料参考温度（缺省 25） | 否 |
| `deps_d_t_per_k` | float 1/K εr 线性温度系数（缺省 0；失控界为一阶口径以 tanδ 指数主导为前提） | 否 |

## mimo_channel_capacity

MIMO容量：NX-10 MIMO 信道容量/分集（round14 :108，C=log₂det(I+γHH†) 与分集增益）：Telatar 1999 容量 + Tse-Viswanath 2005 两档功率口径——等功率（总 snr 均分 Nt：Σlog₂(1+snr·λᵢ/Nt)）与注水（pᵢ=(μ−1/λᵢ)⁺、Σpᵢ=snr，活性模闭式搜索）；规格原式 log₂det(I+snr·HH†)（γ=单流 SNR 口径）由 slogdet 独立路径并行输出（与等功率档差 Nt 倍口径，恒等式由锚树钉）。分集面：rank(HH†) + 有效分集阶 N_eff=(Σλ)²/Σλ²（participation-ratio 有效秩；天线级 DG=10lg(1−ECC) 近似归 ecc_metrics 既有语义不重复）。S 参→H 提取面归 ecc_metrics（本键只接收已构成的 H）。

| 参数 | 说明 | 必填 |
|---|---|---|
| `h_matrix` | array Nr×Nt 信道矩阵（元素=实数或 [re,im] 复数对；矩形非空） | 是 |
| `snr` | float 总发射信噪比（线性口径，>0；单 RX 天线噪声归一） | 是 |

## mimo_virtual_array

NX-1 MIMO 虚拟阵（round14 :88，TX×RX Kronecker 展开虚拟阵/等效孔径/角分辨率闭式）：收发分置两路相位相加 → 虚拟阵元位置 s=p_tx+p_rx（sum 口径主判；difference=带符号差 Lag 协方差口径伴生）。等距收发ULA（M,N，同距 d）→ 虚拟 M+N−1 元等距 ULA、三角多重数（EuRAD 2023 12×6 → 17 元验收锚）。报告：distinct 位置+多重数+成对权重分组、孔径可加恒等式（L_v=L_tx+L_rx 残差）、乘积路径 vs 等效物理阵路径逐点恒等残差、数值/闭式 HPBW 与首零分辨率（闭式只对分组权重均匀ULA 与两因子同距均匀 ULA 给出——三角锥削自然虚拟阵上均匀阵闭式偏宽 ~29%，不越界外推）、孔径增益 L_v/L_tx、PSLL。前向算子与sparse_array_cs.forward_matrix 同构（kron 恒等由锚树钉死）。

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float 频率 GHz（>0；位置归一波长单位 λ=C_MM_GHZ/f_ghz） | 是 |
| `tx_positions_mm` | array Tx 阵元位置 mm（一维，非空；波长单位口径自适应，无需等距） | 是 |
| `rx_positions_mm` | array Rx 阵元位置 mm（一维，非空） | 是 |
| `tx_weights` | array Tx 权重（实数，缺省全 1；复权重综合走 core） | 否 |
| `rx_weights` | array Rx 权重（实数，缺省全 1） | 否 |
| `convention` | str 'sum'\|'difference'（默认 'sum'；MIMO 虚拟阵主判口径） | 否 |
| `scan_deg` | float 扫描角 θ0（度，z 轴 ULA 惯例 u0=cos θ0；默认 90°=侧射） | 否 |
| `u_points` | int u∈[−1,1] 方向余弦网格点数（默认 801，≥3；数值 HPBW/PSLL 采样密度） | 否 |

## modulation_ber_curve

调制BER曲线：数字调制理论 BER 曲线（相干解调 AWGN、Gray 映射、比特能量口径 γb=Eb/N0）：bpsk/qpsk 闭式 Q(√(2γb))（QPSK≡BPSK 物理恒等）；16qam/64qam square-QAM Gray 精确和式 4(1−1/√M)/k·ΣQ((2i−1)·√(3kγb/(M−1)))。Q 函数单源 0.5·erfc(x/√2)。ebn0_db 标量或列表（列表返回曲线数组）；锚：BPSK@10dB=3.872e-6、Q(3.026)=1.239e-3、16QAM@10dB=1.754e-3。出处 Proakis 5ed ch.4 / Cho&Kim 2005

| 参数 | 说明 | 必填 |
|---|---|---|
| `ebn0_db` | float\|list dB Eb/N0（比特能量口径，标量或非空列表，逐点有限校验） | 是 |
| `scheme` | str 'bpsk'/'qpsk'/'16qam'/'64qam'（大小写不敏感） | 是 |

## multimode_cavity_heating

多模腔模式装填：LT-5 多模腔模式统计+装填因子（round18 :137）：Weyl 渐近 N=8πV(f√εr/c0)³/3（双极化，Metaxas & Meredith Ch.5 口径）+ 矩形腔精确枚举交叉对拍（复用 shield_cavity_mode.rect_cavity_modes，TE 容许集+TM 子集分开计）+ 模式密度/平均模间距；可选负载块（全给或全不给）：均匀场装填因子 F=εr′V_l/(εr′V_l+V_c−V_l)、Q_d=1/(F·tanδ)、效率 η=Q_L/Q_d 与负载吸收功率（匹配源口径）；1kW 水负载经典量级锚见锚树

| 参数 | 说明 | 必填 |
|---|---|---|
| `a_mm` | float mm 腔 x 边长（>0） | 是 |
| `b_mm` | float mm 腔 y 边长（>0） | 是 |
| `d_mm` | float mm 腔 z 边长（>0） | 是 |
| `f_ghz` | float GHz 统计频率（>0） | 是 |
| `er` | float - 腔内介质相对介电常数（>0，缺省 1=空气腔） | 否 |
| `v_load_l` | float L 负载体积（负载块；>0，≤腔体积） | 否 |
| `load_eps_r` | float - 负载 εr′（负载块；>0） | 否 |
| `load_tan_d` | float - 负载 tanδ（负载块；>0） | 否 |
| `q_wall` | float - 空腔壁损 unloaded Q（负载块；>0） | 否 |
| `power_w` | float W 输入功率（>0，缺省 1） | 否 |

## multipactor_susceptibility_check

微放电阈值：MP-3 multipactor 微放电击穿阈值（round15 :84，Vaughan 二次发射+20-gap 串接+N 载波等效功率语境）：施加峰值电压对平行板一阶渡越敏感带 × SEY crossover 窗口的合成裕量报告。每序 n=1..order_max 的封闭周期轨道带 V∈[K/√(4+(2n−1)²π²), K/2]（K=4π²(m_e/e)(f·d)² 相似标度）经碰撞能量 窗口 E_imp∈(E1,E2) 门控（δ>1 判据，Kishek & Lau PAC97 口径）后给可持续带；落带内判模型敏感。SEY 窗口 e1_ev/e2_ev 可显式给出（VERIFIED）或缺省由 Vaughan 普适曲线 δ=δmax·(v·e^{1−v})^{k_s} 派生（曲线形状 UNVERIFIED，判定只消费 crossover）。载波表 carrier_powers_w 支持 非相干 RSS（ECSS 口径 P_eq=ΣPi，缺省）与相干最坏相位（P_eq=(Σ√Pi)²）双口径。verdict 仅对一阶理想化模型自洽（零初速发射）；工程仲裁走 high_power 的 ECSS-E-ST-20-01C 实验包络 ecss_multipactor_fd（报告 notes 固定指向）。margin=阈值/施加（dB），≥required_margin_db 判过

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | float GHz 工作频率（>0） | 是 |
| `gap_mm` | float mm 平行板临界间隙（>0） | 是 |
| `voltage_v` | float V 施加峰值电压（优先；与功率/载波三选一） | 否 |
| `power_w` | float W 单载波功率（配 z0_ohm：V=√(2PZ0)） | 否 |
| `z0_ohm` | float Ω 系统阻抗（默认 50） | 否 |
| `carrier_powers_w` | array W 各载波平均功率（触发多载波等效口径） | 否 |
| `carrier_coherent` | bool 载波相干最坏相位口径（缺省 False=RSS） | 否 |
| `delta_max` | float SEY 峰值 δmax（>1；缺省 2.0=UNVERIFIED 形状面） | 否 |
| `emax_ev` | float SEY 峰值能量 Emax eV（缺省 300=UNVERIFIED 形状面） | 否 |
| `e1_ev` | float 第一 crossover 能量 eV（与 e2_ev 成对；VERIFIED 判据面） | 否 |
| `e2_ev` | float 第二 crossover 能量 eV（与 e1_ev 成对；需 >e1） | 否 |
| `k_s` | float Vaughan 表面粗糙度因子（>0，缺省 1=光滑） | 否 |
| `order_max` | int 扫描最高序数（>=1，缺省 10） | 否 |
| `required_margin_db` | float dB 要求裕量（默认 6） | 否 |

## multiplexer_channel_plan

多工器信道规划（滤波器组复用平铺）：总带 [f1,f2] 等分数/等绝对双口径 N 道划分——逐道中心/边带/绝对与分数带宽+N−1 交越点+互补 diplexer 交越损耗 3.0103 dB 定理+全带利用率恒 1；等分数口径交越=几何中点、fc 对称恒等 fc_k·fc_{N−1−k}=f1·f2；diplexer_compose=两道精确 S 面不并入，滤波器阶数/原型走 multiplexer_channel_prototype（同族姊妹键）

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_start_ghz` | float GHz 总带下缘（>0，<f_stop） | 是 |
| `f_stop_ghz` | float GHz 总带上缘（>f_start） | 是 |
| `n_channels` | int 信道数 N（2..128） | 是 |
| `spacing` | str 平铺口径 equal_fractional（缺省）\|equal_absolute | 否 |

## multiplexer_channel_prototype

多工器逐通道滤波器阶数原型：通道带宽+阻带抑制需求 → 带通→低通变换（几何中心精确口径，通带边缘 Ω=±1）+ Butterworth/Chebyshev 最小阶闭式（N−1 阶并列证明最小性）+ 原型 g 值链（Chebyshev 复用 core/matching 表递推单源；Butterworth 闭式 N≤5 与 diplexer_compose 互证）；交越区邻道隔离的阻带面供给

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_center_ghz` | float GHz 通道中心频率（>0） | 是 |
| `channel_bw_ghz` | float GHz 通道带宽 B（>0 且 f_center−B/2>0） | 是 |
| `rejection_db` | float dB 阻带抑制需求（>0） | 是 |
| `stopband_freq_ghz` | float GHz 阻带频点（严格在通道通带外） | 是 |
| `prototype` | str 原型 butterworth\|chebyshev（缺省 chebyshev） | 否 |
| `ripple_db` | float dB 带内纹波（chebyshev 必给；butterworth 可选，缺省 3.0103 dB≡ε=1） | 否 |

## multiplier_chain_budget

倍频链预算：级联 ×M_i 倍频器——f_out=f_in·∏M_i、逐级频率/累计倍次/累计损耗表、理想倍频相噪劣化 20log10(N)（逐级累计恒等式 Σ20log10(M_i)=20log10(∏M_i)）+dBm 功率预算；可选逐级剩余相噪地板功率和（同偏移同频功率相加，单列不与理想律合并）。谐波杂散枚举归 spur_search，本键不做

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_in_ghz` | float GHz 输入频率（>0） | 是 |
| `factors` | list[int] 逐级倍次 M_i（整数 [2,64]，1..8 级，N=∏M_i ≤ 65536） | 是 |
| `stage_loss_db` | list[float] 逐级转换损耗 dB（≥0 有限，长度=级数；缺省全 0=理想倍频档） | 否 |
| `pin_dbm` | float dBm 输入功率（可选；给定时输出 pout_dbm） | 否 |
| `stage_residual_pn_dbc_hz` | list[float] 逐级剩余相噪地板 dBc/Hz（有限，长度=级数，同偏移口径；可选——给定时输出功率和） | 否 |

## multisection_coupler_binomial

多节定向耦合器二项式综合：对称 N 节（奇）中心最大平坦口径——结点反射权按 g(x)∝∫₀ˣ(1−t²)^M dt 三角分解唯一确定（N=3 → 结点比 1:9:9:1、节耦合比 1:10:1；N=5 → 3:25:150），节耦合累计→逐节 (Z0e,Z0o)（恒 Z0e·Z0o=Z0²，f0 隔离口精确零）。电平归一对精确偶/奇级联 θ=90° 求根，f0 精确命中目标耦合；一阶 vs 精确二阶差如实并列。锚：N=1 退化 vs 单节精确闭式逐位；最大平坦条件测试侧独立重解；能量守恒 ≤1e-12

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_sections` | int 耦合节数（正奇整数，1..15；3 节最常用） | 是 |
| `coupling_db` | float dB 目标耦合度（正数口径：10=10dB 耦合器） | 是 |
| `z0_ohm` | float Ω 端口/馈线阻抗（>0，缺省 50） | 否 |

## multisection_coupler_response

多节定向耦合器精确频响：逐节 (Z0e,Z0o)（≥1 节，段长=λ/4@f0）偶/奇模各自 2 端口线级联、叠加构造 4 端口（P1=入/P2=直通/P3=耦合/P4=隔离）——S11/S21/S31/S41 幅度+dB、方向性、能量守恒残差（构造恒无耗）；Z0e·Z0o=Z0² 配对下 f0 隔离口精确零（|S41|<1e-12 如实记 None）。锚：N=1 vs 单节精确闭式 c·sinθ/√(1−c²cos²θ) 逐位 ≤1e-12

| 参数 | 说明 | 必填 |
|---|---|---|
| `z0e_ohm` | array 逐节偶模阻抗 Ω（≥1 节） | 是 |
| `z0o_ohm` | array 逐节奇模阻抗 Ω（同长；须 Z0e>Z0o>0） | 是 |
| `f0_ghz` | float GHz 中心频率（段长=λ/4@f0；>0） | 是 |
| `freq_ghz` | array GHz 频率轴（>0；避开 θ=kπ 奇异点） | 是 |
| `z0_ohm` | float Ω 端口参考阻抗（>0，缺省 50） | 否 |
| `eps_eff` | float\|array 逐节有效介电常数（≥1；标量=同步均匀，缺省 1） | 否 |

## parallel_plate_breakdown_margin

平行板击穿场强裕量：E = V/d 对比材料击穿阈值表（空气 3 MV/m 等）；margin_ratio = E_bd/E，safety_factor 为要求的安全系数（E·sf ≤ E_bd 判过）

| 参数 | 说明 | 必填 |
|---|---|---|
| `voltage_v` | float V 施加直流/峰值电压（≥0） | 是 |
| `gap_mm` | float mm 极板间距（>0） | 是 |
| `material` | str 材料键（默认 air；可用见 _DIELECTRIC_STRENGTH_MV_PER_M） | 否 |
| `safety_factor` | float - 要求安全系数（默认 1.0） | 否 |

## patch_f0_symbolic_e13（实验）

符号回归归纳公式（实验态，默认关闭）：f0_ghz = 0.0261448 + 75.1834*1/L_mm + 0.0162789*L_mm/W_mm。E13（/runs/symbolic_fit/patch_f0.json）：数据集 patch_antenna_openems_campaign，51 真实 openEMS 点（L∈[35,45]mm、W∈[40,60]mm、er=3.66、h=0.508），基模=[1.3,2.7]GHz 最低频 ≥3dB 局部谷；holdout 每 5 留 1，rmse_holdout=0.001773GHz、r2_train=0.999889；独立裁判 vs Hammerstad/HJ mean −0.699%、max|dev|=0.765%≤2% PASS

| 参数 | 说明 | 必填 |
|---|---|---|
| `l_mm` | float - 归纳变量 L_mm（适用域/出处见 description） | 是 |
| `w_mm` | float - 归纳变量 W_mm（适用域/出处见 description） | 是 |

## patch_length

贴片长度速算：矩形贴片谐振长度（Balanis 闭式含边缘修正）：f0+er+h → W/εeff/L

| 参数 | 说明 | 必填 |
|---|---|---|
| `f0_ghz` | float GHz 谐振频率 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `h_mm` | float mm 基板厚度 | 是 |

## phase_noise_evm

相噪积分EVM：MT-4 件 2 相噪 → 积分 EVM（round17 MT-4；σ_φ²=2∫10^(L/10)df ADI MT-008 口径，积分复用 core/clock_noise.phase_jitter_from_l 不重复实现）→ EVM_rms=σ_φ（小角度平稳高斯口径，σ_φ>0.5 rad 打 small_angle_ok=False 不静默）+ evm_db/evm_percent + 可选 rms 抖动。f_edges=严格递增偏移频率边界 Hz；l_dbc 按 interp 取边界值（db_linear，长度=N）或段值（const，长度=N−1）；积分区间不外推。σ_φ=0 → evm_db=None（dB 域无定义，JSON 契约禁 −Inf）

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_edges` | list[float] 偏移频率边界 Hz（严格递增，N≥2，全>0） | 是 |
| `l_dbc` | list[float] 单边带相噪 dBc/Hz（db_linear=边界值 N 个 / const=段值 N−1 个） | 是 |
| `interp` | str 'db_linear'\|'const'（默认 'db_linear'） | 否 |
| `f_carrier_hz` | float 可选载波 Hz（>0；给了才输出 jitter_s） | 否 |

## pim_cascade_budget

PIM 级联预算：N 节点实测电平（IEC 62037 双音 +43dBm/载波参考条件，缺省口径）按幂级数精确律平移到实际载波功率（order n 产物平移 n·ΔP，IM3 缺省斜率 3；实测斜率偏离走 slope_db_per_db 覆盖）→ 双口径累计（pim_nodes_combine 同核）→ 可选 pim_limit_dbm 裕量（双口径各给，相干裕量负=最坏情形超限如实报告）。锚：p_carrier=p_ref 与合成键逐位互证；ΔP=1dB/IM3 → 每节点恰 +3.0dB；单节点退化=本级电平平移

| 参数 | 说明 | 必填 |
|---|---|---|
| `nodes` | list[dict] 节点清单（每条 {'level_dbm': 参考条件实测电平, 'name': 可选}；≥1 条） | 是 |
| `p_carrier_dbm` | float dBm 实际每载波载波功率（双音口径，有限） | 是 |
| `order` | int 互调产物阶数（IM2/IM3…，∈[2,64] 与 pim_products 同上限口径，缺省 3） | 否 |
| `p_ref_dbm` | float dBm 参考条件每载波功率（缺省 43=IEC 62037 口径） | 否 |
| `slope_db_per_db` | float 实测斜率覆盖（>0 可选；缺省=order 精确律；实测常见 2–5，pim_empirical 硬守卫 [1,6] 口径注记） | 否 |
| `pim_limit_dbm` | float dBm 系统限值（可选；给则输出双口径裕量） | 否 |

## pim_nodes_combine

多节点 PIM 电平累计：同一 IM 产物频点上 N 个无源节点实测电平双口径合成——非相干功率和 10log10Σ10^(Pi/10)（随机相位统计，验收惯例）与相干同相最坏 20log10Σ10^(Pi/20)（电压线性相加上界），spread=两者差（相位统计带如实以双极限呈现）；节点占比+主导节点直出。锚：N 等电平→+10log10N/+20log10N 恒等；两等电平 +3.0103/+6.0206dB；N=1 退化恒等

| 参数 | 说明 | 必填 |
|---|---|---|
| `levels_dbm` | list[float] dBm 各节点同一产物的实测电平（≥1 个，逐元素有限；电平实测注入——PIM 绝对值不可预测铁律沿用） | 是 |

## pin_diode_limiter

PIN二极管限幅器：并联 PIN 二极管限幅器两态线性口径——关断态（y=jωC_off·Z0）插损/回损、导通态（y=Z0/R_on）隔离与功率三分（反射/泄漏/二极管吸收，和=1 精确；R_on=Z0/2 吸收恒 50% 最大）+限幅门限一阶估计 P_th=V_f²/(2Z0)。互易 S11=S22、S12=S21；集总并联近似（二极管 ≪λ）、封装 L/C 不在键面

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 工作频率（>0；集总并联近似有效域） | 是 |
| `r_on_ohm` | float Ω 导通态串联电阻 R_on（>0，缺省 1=典型 PIN 导通档） | 否 |
| `c_off_pf` | float pF 关断态结电容 C_off（>0，缺省 0.1=典型零偏结电容档） | 否 |
| `z0_ohm` | float Ω 系统阻抗（>0，缺省 50） | 否 |
| `v_forward_v` | float V 二极管导通电压 V_f（>0，缺省 0.7=硅 PIN 典型；门限为一阶估计） | 否 |

## pll_loop_filter_synthesize

PLL环路滤波：MT-5 三阶 PLL 环路滤波器综合（round17 MT-5，Banerjee SNAA106C T1/T2/T3→C1/C2/R2/C3 闭式+相位裕度迭代）：给定环路带宽 f_c（开环穿越）与相位裕度 PM → 峰值相位放置（dPM/dω|ωc=0，Gardner 二阶几何中值放置的三阶推广；极点比 r=T3/T1 为显式设计自由度，>1）反解 T1/T2/T3，总电容 A0 由 |G(jωc)|=1 闭式回代，元件值 C1=A0·T1/T2、C2=A0·(T2−T1)/T2、R2=T2/C2、C3·R3=T3。结果带回代复核（穿越/PM 残差入字段）+闭环 −3dB 带宽+|H(jωc)|=1/(2sin(PM/2)) 恒等值+C3 加载比（无源网络 T 形近似有效域自查：C3≪A0；有源拓扑 T 形精确）。可达 PM 窗随 r 收窄，窗外/PM∉(0°,90°)/r≤1 显式报错

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_c_hz` | float 目标开环穿越频率（环路带宽）Hz（>0） | 是 |
| `phase_margin_deg` | float 目标相位裕度 deg（开区间 0<PM<90） | 是 |
| `kp_a_per_rad` | float 电荷泵/鉴相增益 Kφ A/rad（>0） | 是 |
| `kvco_hz_per_v` | float VCO 压控灵敏度 Hz/V（>0；内核折 rad/s/V） | 是 |
| `n_div` | float 分频比 N（≥1；分数 N 合法） | 是 |
| `t3_t1_ratio` | float 极点比 r=T3/T1（>1，缺省 3.0；设计自由度） | 否 |
| `c3_frac` | float C3=A0×此份额（0<c≤0.5，缺省 0.1；r3_ohm 未给时生效） | 否 |
| `r3_ohm` | float 显式第三极点电阻 Ω（>0；给定时 C3=T3/R3 覆盖 c3_frac） | 否 |

## power_cal_chain

功率校准链：SB22-MS-1 功率校准补偿链（读数 → 远端平面可用功率 + GUM 预算，确定性闭式）：①传感器校准因子补偿 P_inc=P_read−10lg K_b（K_b=η(1−|Γl|²)，Keysight AN 64-1A 定义）；②平缆损耗补偿 +L；③源匹配校正 +10lg(1/(1−|Γs|²))；④失配相位项 +20lg|1−ΓsΓl|——exact 模式逐点精确修正，band 模式相位未知只给 ±MU=20lg(1+|Γs||Γl|) 带（U 形 u=MU/√2，JCGM 100:2008 §4.3.9；文献数值例 SWR1.5×1.25→±0.19 dB，Keysight AN 1449-3 与 R&S 失配表双源）。u_components B 类组件（rectangular a/√3=§4.3.7 / ushaped a/√2=§4.3.9）或已标准 u_db 直收，合成 u_c=√Σu²、展开 U=k=2。诚实边界：缆 S 参数级联失配与 |Γ| 自身不确定度不在本域（调用方以同一参考面等效 Γ 给入）；逐频点由调用方逐点调用。

| 参数 | 说明 | 必填 |
|---|---|---|
| `p_read_dbm` | float dBm 功率计原始读数 | 是 |
| `k_cal_lin` | float 线性 传感器校准因子 K_b=η(1−\|Γl\|²)（(0,1]） | 是 |
| `cable_loss_db` | float dB 传感器平面→远端平面平缆损耗（>=0，缺省 0） | 否 |
| `gamma_source` | list[float] 源反射 [re, im]（\|Γ\|<1，缺省 [0,0]） | 否 |
| `gamma_load` | list[float] 传感器侧反射 [re, im]（\|Γ\|<1，缺省 [0,0]） | 否 |
| `mismatch_mode` | str 'none'/'band'/'exact'（缺省 'none'） | 否 |
| `u_components` | list[dict] 可选不确定度组件 [{name, u_db} 或 {name, half_width_db, distribution: 'rectangular'\|'ushaped'}] | 否 |

## q_factor_circle

单腔 Q 双通道之 B（Kajfez 圆拟合）：S11 → Taubin 代数圆拟合（Kasa 小弧有偏不用）→ β=1/(2s−1)（直径投影式，参考面旋转不变）→ 3dB 弦 Q_L=f0/(f₂−f₁) → Q_u=Q_L(1+β)。与 q_factor_vf 互证 ≤10%，超阈 UNDECIDABLE（#122）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | array GHz 频率轴（覆盖谐振 ±≥1 线宽） | 是 |
| `s11` | array 复 S11（[re,im] 对或复数） | 是 |

## q_factor_vf

单腔 Q 双通道之 A（VF 极点法）：反射 S11 → skrf VectorFitting 复极点对 → Q_L=|Im p|/(2|Re p|)、f0=|Im p|/2π；给 q_e 时 1/Q_u=1/Q_L−Σ1/Q_e,k。|Re p|/|Im p|>0.05 → loss_degraded 如实标记（判据 criteria.md §2）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | array GHz 频率轴（覆盖谐振 ±≥5 线宽） | 是 |
| `s11` | array 复 S11（[re,im] 对或复数） | 是 |
| `f0_hint_ghz` | float GHz 谐振频率提示（缺省=取带内最强极点对） | 否 |
| `q_e` | array 外部 Q（列表或标量；缺省=None 只报 Q_L） | 否 |
| `n_poles` | int VF 复极点对数（默认 1） | 否 |

## q_factor_vf_zero

Q零点法：单腔 Q 零点法（VF 极点+零点求和口径，免 q_e）：反射 S11 → VF 有理拟合 Γ=N/D（复极点对数从 1 起扫、取首个 fit_rms≤1e-2 的最小阶——更高阶会 出极点-零点双联伪对，和式翻倍）→ 带内衰减极点对 p 与频距最近的 Γ 零点对 z（Γ 自身零点，过耦时在右半平面，不判衰减性）→ Q_u=|Im p|/−(Re p+Re z)、f0=|Im p|/2π。正则单极点反射模型下 Re p=−ω0(1+β)/2Q_u、Re z=−ω0(1−β)/2Q_u ⟹ Re p+Re z=−ω0/Q_u 与 β 无关——无需 q_e 输入，与 q_factor_vf 极点法（需 q_e）互补；损耗判据仍在极点面：|Re p|/|Im p|>0.05 → loss_degraded（criteria §2）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | array GHz 频率轴（覆盖谐振 ±≥3 线宽；建议已去嵌参考面时延——残余时延进拟合误差） | 是 |
| `s11` | array 复 S11（[re,im] 对或复数） | 是 |
| `f0_hint_ghz` | float GHz 谐振频率提示（缺省=最弱阻尼极点对锚定） | 否 |
| `n_poles` | int VF 复极点对数扫描上限（默认 3；从 1 起取首个 rms≤1e-2 的最小阶，1..4） | 否 |

## qe_group_delay

群时延测Q：单谐振器外部 Q 群时延法（Dishal/Hong 反射单端口径，df6 A1 R4）：τ(f)=A/(1+((f−f0)/w)²)+D 四参数 Lorentzian+基线拟合；无耗单端口 τmax=4Qe/ω0 ⇒ 缺省 c=4（合成回收 3.9972；/2 口径否决，DP-2 互证）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_hz` | ndarray Hz 升序扫频栅格 | 是 |
| `s11` | ndarray complex 复 S11（单载反射） | 是 |
| `c` | float - τ→Qe 常数（缺省 4.0；对称双馈 S21 口径配 1.0） | 否 |

## quarter_wave_transformer

λ/4 阻抗变换器：段特性阻抗 z0=sqrt(Zs·Zl)；给 εeff/频率时附物理长度

| 参数 | 说明 | 必填 |
|---|---|---|
| `z_source_ohm` | float Ω 源侧阻抗 | 是 |
| `z_load_ohm` | float Ω 负载阻抗 | 是 |
| `freq_ghz` | float GHz 频率（可选，配合 eps_eff 算长度） | 否 |
| `eps_eff` | float - 有效介电常数（可选） | 否 |

## qubit_dispersive_shift

色散位移：量子比特读出色散位移 χ 一阶闭式（G18，Blais 2004 色散近似+有限线宽修正）：χ = g²Δ/((κ/2)²+Δ²)（复色散系数 Re(g²/(Δ+jκ/2))；远失谐 |Δ|≫κ 退化教科书 g²/Δ）。附强色散域判据字段：可分辨 |2χ|≥κ、色散近似有效 |g/Δ|≤0.1、临界光子数 n_crit=Δ²/(4g²)、Purcell 衰减 Γ_P=(g/Δ)²κ、有效比特线宽 Γ1+Γ_P。全部频率量普通频率口径（MHz 入参；g 为单比特真空耦合——实测谐振分裂 2g 请先除 2）。Δ=0 简并点色散近似失效，显式拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `g_mhz` | float MHz 腔-比特真空耦合强度 g（>0；非 2g 分裂） | 是 |
| `delta_mhz` | float MHz 比特-腔失谐 Δ=ω_q−ω_r（≠0，符号进 χ） | 是 |
| `kappa_mhz` | float MHz 腔总线宽 κ（>0） | 是 |
| `gamma1_mhz` | float MHz 比特弛豫率 Γ1（≥0，缺省 0；给定时出有效线宽 Γ1+Γ_P 面） | 否 |

## qubit_readout_s21

读出S21曲线：读出谐振器 S21 双态频响曲线（G18，notch/through 型单源实现）：S21(δ)=1−κe/(κ/2+j(δ∓χ))，两态经同一内部函数产出（单源：双态差异只经 ±χ 位移进入；state0=|g⟩ 取 +χ、state1=|e⟩ 取 −χ，符号约定写死）。锚：临界耦合 κe=κ/2 → 态谐振点 S21 逐位 0（深谷归一 −1 口径）；欠/过耦合谐振点幅值 1−2κe/κ 与相位翻转。χ=0 → 双态曲线逐点相同（与色散键连续）。分离度 |2χ|/κ 字段

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_r_ghz` | float GHz 裸腔频率 ω_r/2π（>0） | 是 |
| `kappa_mhz` | float MHz 腔总线宽 κ（>0） | 是 |
| `kappa_e_mhz` | float MHz 外部（耦合口）线宽 κe（0<κe≤κ） | 是 |
| `chi_mhz` | float MHz 色散频移（缺省 0；qubit_dispersive_shift.chi_mhz 直连；state0 取 +χ、state1 取 −χ） | 否 |
| `span_mhz` | float MHz 扫频跨度（>0，缺省 10×κ，以 f_r 为中心） | 否 |
| `n_points` | int 频点数（[2,2001]，缺省 201） | 否 |

## qubit_readout_snr

读出SNR：量子比特读出 SNR/积分时间（G18，IQ 平面分离口径，工程近似写死）：SNR = d_IQ·√(κe·n̄·τ/n_sys)。d_IQ=|S21(f_probe,+χ)−S21(f_probe,−χ)|（单源消费键 2 同一内部函数）；n̄=腔内平均光子数（光子流 κe·n̄ 过耦合口径）；n_sys=k_B·T_n/(h·f_r) 折算输入噪声光子数（T_n 缺省=量子极限 h·f_r/k_B → n_sys=1；相敏放大口径）。恒等锚：SNR∝√τ（τ×4→×2）、SNR∝√n̄；参考字段 Γ_m=8χ²n̄/κ（坏腔可分辨极限，仅参考）与 SNR=1 积分时间 τ₁=n_sys/(κe·n̄·d_IQ²)。|χ|=0 零信号显式拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `chi_mhz` | float MHz 色散频移（\|χ\|>0；qubit_dispersive_shift.chi_mhz 直连） | 是 |
| `kappa_mhz` | float MHz 腔总线宽 κ（>0） | 是 |
| `kappa_e_mhz` | float MHz 外部线宽 κe（0<κe≤κ） | 是 |
| `n_bar` | float 腔内平均读出光子数（>0；须≪ncrit，调用方自查） | 是 |
| `f_r_ghz` | float GHz 裸腔频率（>0；n_sys 的 T_q=h·f/k_B 口径） | 是 |
| `tau_us` | float μs 积分时间（>0） | 是 |
| `t_n_k` | float K 放大器噪声温度（>0，缺省=量子极限 h·f_r/k_B） | 否 |
| `detune_mhz` | float MHz 探针频率偏移 δ（缺省 0=on-resonance） | 否 |

## radar_range_equation

基本雷达方程（单基地同天线）：Pr=Pt·G²·λ²·σ/((4π)³R⁴L)，SI 线性口径（pt_w/antenna_gain 线性/wavelength_m/rcs_m2/range_m/loss_factor≥1）与 dB 混合口径（pt_dbm/antenna_gain_db/freq_ghz→λ/rcs_dbsm/range_km/loss_db≥0）二选一，跨口径混给显式拒绝；给 bandwidth_hz 时附 N=k·T0·B·F 与 SNR（T0 缺省 290K，F 按路径 noise_fig≥1/noise_fig_db≥0）。锚：R 加倍→Pr ÷16（−12.0412dB）；kT0B@290K/1MHz=−113.98dBm。出处 Skolnik 3ed ch.2/Richards FRSP 2ed ch.1

| 参数 | 说明 | 必填 |
|---|---|---|
| `pt_w` | float W 发射峰值功率（SI 口径，与 pt_dbm 二选一） | 否 |
| `antenna_gain` | float - 天线增益线性值（SI 口径，同天线收发） | 否 |
| `wavelength_m` | float m 波长（SI 口径） | 否 |
| `rcs_m2` | float m² 目标雷达截面（SI 口径） | 否 |
| `range_m` | float m 目标距离（SI 口径） | 否 |
| `loss_factor` | float - 系统损耗线性值 L≥1（SI 口径，默认 1.0） | 否 |
| `pt_dbm` | float dBm 发射峰值功率（dB 口径，与 pt_w 二选一） | 否 |
| `antenna_gain_db` | float dBi 天线增益（dB 口径） | 否 |
| `freq_ghz` | float GHz 载频（dB 口径，λ=C_MM_GHZ/f 单源） | 否 |
| `rcs_dbsm` | float dBsm 目标雷达截面（dB 口径） | 否 |
| `range_km` | float km 目标距离（dB 口径） | 否 |
| `loss_db` | float dB 系统损耗（dB 口径，≥0，默认 0.0） | 否 |
| `bandwidth_hz` | float Hz 接收带宽（可选；给出则附噪声与 SNR） | 否 |
| `noise_fig` | float - 噪声系数线性值 F≥1（SI 口径，默认 1.0） | 否 |
| `noise_fig_db` | float dB 噪声系数（dB 口径，默认 0.0） | 否 |
| `t0_k` | float K 噪声温度基准（默认 290，IEEE 口径） | 否 |

## radiated_immunity_power

辐射抗扰换算：IEC 61000-4-3 射频辐射抗扰场强/功率换算（远场口径）：严酷度 test_level（1/2/3/4→1/3/10/30 V/m，Table 1）或显式 field_v_per_m 恰给其一 → 天线口所需前向功率 P=(E·R)²/(30G)（E=√(30·EIRP)/R 恒等闭式，Ott ch.5；与 exposure_limits 合规距离同源）+ EIRP + 源输出补偿（cable_loss_db）。试验距离 3m/10m（标准首选 3m）。恒等锚：E↔P 双向残差 <1e-12；E×2=+6.0206dB；3m→10m 功率 ×(10/3)²。可选 freq_mhz 给天线系数换算面 AF(dB/m)=20log10(f_MHz)−G_dBi−29.79（50Ω 接收口径经典恒等）。80% AM 1kHz 包络峰 +5.105dB 只进 note

| 参数 | 说明 | 必填 |
|---|---|---|
| `test_level` | int 严酷度等级 1\|2\|3\|4（Table 1；与 field_v_per_m 恰给其一） | 否 |
| `field_v_per_m` | float V/m 显式场强（>0；与 test_level 恰给其一） | 否 |
| `distance_m` | float m 试验距离（3\|10，标准试验距离） | 是 |
| `antenna_gain_db` | float dBi 发射天线线增益（≥0，缺省 6） | 否 |
| `cable_loss_db` | float dB 天线口前馈缆损耗（≥0，缺省 0；源输出按此补偿） | 否 |
| `freq_mhz` | float MHz 天线系数换算频率（可选；给了才出 AF 面） | 否 |

## rain_attenuation_r001

长期雨衰：AP-6 长期雨衰全链 A0.01 [dB]（ITU-R P.618-13 §2.2.1.1 Step1-9，式(1)-(7)：hR=h0+0.36→Ls（θ≥5° 式(1)/θ<5° 式(2)）→LG=Ls·cosθ→γR（P.838-3 已录入面）→r0.01 水平缩减→ζ/χ/ν0.01 垂直调整→LE→A0.01=γR·LE）。R0.01 与 h0 为调用方显式输入（P.837/P.839 数字地图 PV-011 不捆绑，本地实测/气象数据直接进链）；全部中间量留痕供对拍。原文零分支如实：hR<=hs 或 R0.01=0 → a001_db=0 + zero_reason 注记。Ap 换算（Step10）见 core.rain_attenuation_ap

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 频率（γR 域 [1,1000]） | 是 |
| `r001_mmh` | float mm/h 年均 0.01% 时间超越雨率 R0.01（>=0，0=无雨） | 是 |
| `elevation_deg` | float deg 仰角（(0,90]） | 是 |
| `h0_km` | float km 年均 0°C 层高度（>0；P.839 数据面显式输入） | 是 |
| `h_s_km` | float km 站址海拔（>=0） | 是 |
| `lat_deg` | float deg 纬度（式内取 \|φ\|） | 是 |
| `pol` | str 'h'/'v' 极化（缺省 'h'） | 否 |

## rain_specific_attenuation

雨衰特征衰减：AP-6 雨衰 specific attenuation γ_R [dB/km]（ITU-R P.838-3 式(1) γ_R=k·R^α；式(2)/(3) Gauss 和式给 kH/kV/αH/αV，Tables 1-4 系数经官方 Table 5 全量 116 频点对拍 max rel dev 0.112%，证据 runs/ap8/）。pol 只收 'h'/'v'（线极化直取；任意仰角/倾角插值式(4)/(5) 不注册——P.618 链路面只消费 h/v 直取档）。R=0 合法→0（无雨零分支）；f∈[1,1000]GHz 域外显式 ValueError

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 频率（[1,1000]） | 是 |
| `rain_rate_mmh` | float mm/h 雨率 R（>=0，0=无雨→0） | 是 |
| `pol` | str 'h'/'v' 极化（缺省 'h'） | 否 |

## rcs_peak_canonical

典型目标峰值 RCS 库：平板法向 σ=4πA²/λ²（A=a·b）/二面角 90° σ=8πa²b²/λ²（双跳变等效孔径 √2·ab）/方形三方角 σ=4πa⁴/(3λ²)（等效孔径 a²/√3）/圆柱侧向 σ=2πL²r/λ（λ⁻¹ 标度）——姿态=峰值口径（各形状最大方向），不建姿态方向图。锚：全闭式测试侧独立重算；板族 λ⁻² 与圆柱 λ⁻¹ 双标度钉；二面角(a=b)=2×同单面平板、三方角按 a²/√3 回代平板式两结构恒等；1m² 平板@10GHz=41.45dBsm 常数

| 参数 | 说明 | 必填 |
|---|---|---|
| `shape` | str 形状 'flat_plate'\|'dihedral'\|'square_trihedral'\|'cylinder_broadside'（封闭集合） | 是 |
| `f_ghz` | float GHz 雷达频率（>0） | 是 |
| `a_mm` | float mm 主尺寸：平板/二面角=边 a；三方角=边长；圆柱=半径 r（>0） | 是 |
| `b_mm` | float mm 次尺寸：平板/二面角=边 b；圆柱=长度 L（>0；三方角不给） | 否 |

## rcs_sphere_mie

金属球 RCS 三区精确解：PEC 球后向散射 Mie 级数 σ=(πa²/ρ²)·|Σ(−1)^n·(2n+1)(a_n−b_n)|²（ρ=ka，Wiscombe 截断），输出 σ/dBsm+ka+三区判据（rayleigh ka<0.5 / mie 0.5–10 振荡过渡 / optical ka>10）+ 双解析极限自证字段（Rayleigh 9πa²(ka)⁴ 与光学 πa² 的 rel_dev，级数双极限锚）；Rayleigh 窗 f⁴ 标度逐点可钉。锚：ka=0.02 极限偏差 ≤1e-4；ka=30 偏差≤0.1dB；测试侧对数导数路线独立实现互证 ≤1e-9

| 参数 | 说明 | 必填 |
|---|---|---|
| `radius_mm` | float mm 金属球半径 a（>0） | 是 |
| `f_ghz` | float GHz 雷达频率（>0；ka=2πa/λ 决定三区归属） | 是 |

## reflective_phaser

反射式移相器：可变电抗终端反射经环行器/正交混合环回输——Γ=(r+jx−1)/(r+jx+1) 二态，无耗 |Γ|=1、φ=180°−2arctan(x)；设计正解 Δφ→±x=tan(Δφ/4) 容感对称态对（180° 位双有限态精确可达，Δφ∈(0,360)）或 x1/x2（变容管 C1/C2 pF@f0 同价）分析反解 Δφ=2(arctan x1−arctan x2)+逐态反射损耗；r_norm 串联损耗口径 Q=|x|/r 随行

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 工作频率（>0；变容管路线必需，电抗路线路由 x 无量纲化不消费） | 是 |
| `z0_ohm` | float Ω 参考阻抗（>0，缺省 50） | 否 |
| `delta_phi_deg` | float° 目标差分相移（0<Δφ<360 开区间；设计路线，与 reactance_norm/varactor 路线二选一） | 否 |
| `x1_norm` | float 态 1 归一化电抗 X/Z0（有限；与 x2_norm 成对，分析路线） | 否 |
| `x2_norm` | float 态 2 归一化电抗 X/Z0（有限且 ≠x1；分析路线） | 否 |
| `c1_pf` | float pF 态 1 变容管电容（>0；变容管路线，与 c2_pf 成对，需 f_ghz/z0_ohm） | 否 |
| `c2_pf` | float pF 态 2 变容管电容（>0 且 ≠c1_pf；变容管路线） | 否 |
| `r_norm` | float 归一化串联损耗电阻 R_s/Z0（≥0 有限，缺省 0=无耗） | 否 |

## required_ebn0

所需Eb/N0：目标 BER→所需 Eb/N0 反解（dB 域二分，BER 单调降闭式同 modulation_ber_curve）：BPSK 锚 1e-5→9.5879 dB（文献 9.588）、1e-3→6.7895 dB（文献 6.79）；16QAM 1e-6→14.40 dB；64QAM 1e-6→18.78 dB（文献表）。target_ber ∈ [1e-15, 0.5)（>0.1 如实标 low_confidence——square-QAM 和式高 BER 端渐失精确，不拒绝）；低于双精度下限/高于可反解上界显式拒绝。反解后前向回代自检

| 参数 | 说明 | 必填 |
|---|---|---|
| `target_ber` | float - 目标误码率（[1e-15,0.5)，越大越接近闭式高 BER 失精确带） | 是 |
| `scheme` | str 'bpsk'/'qpsk'/'16qam'/'64qam'（大小写不敏感） | 是 |

## resonator_thermal_drift

谐振温漂（§10.3 D14 一阶闭式）：Δf/f = −CTE·ΔT − ½·TCDk·ΔT。CTE=有效线膨胀系数、TCDk=(1/ε)dε/dT，单位 ppm/K

| 参数 | 说明 | 必填 |
|---|---|---|
| `f0_ghz` | float GHz 标称谐振频率（>0） | 是 |
| `delta_t_c` | float K 温度变化（可为负） | 是 |
| `cte_ppm_per_k` | float ppm/K 有效线膨胀系数（含封装） | 是 |
| `tcdk_ppm_per_k` | float ppm/K 介电常数温度系数 | 是 |

## retrieve_eff_params

等效参数反演：MM-7 等效参数反演（Smith 2002 PRB 65:195104 同族口径）：单频 (S11,S21)（[re,im] 对）法向入射对称面板厚度 d → (ε,μ,n,Z)。时间 约定 e^{-jωt}（τ=e^{+jk0·nd}，无耗 Im(n)=0、有耗 Im(n)>0）。无源 守卫：能量 |S11|²+|S21|²≤1+1e-9、|τ|≤1+1e-9、Im(n)<0 显式拒绝；退化域（(1−S11)²−S21²=0、1−P·Γ=0、τ=0）显式拒绝。branch_m=相位 回绕支编号（相邻支差 2π/(k0·d) 恒等式可自检）；分支自动判据/Kramers-Kronig 因果核=MM-5 显式不做。slab_panel_rt=core 正向对偶面（合成回收对拍用，core 直调不注册）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | float 频率 GHz（>0） | 是 |
| `s11` | float\|[re,im] 反射系数 S11 | 是 |
| `s21` | float\|[re,im] 透射系数 S21 | 是 |
| `thickness_mm` | float 面板厚度 d（mm，>0） | 是 |
| `branch_m` | int 折射率支编号（ℤ，默认 0=主枝；d<λ/2 时主枝） | 否 |

## rfid_backscatter_link

RFID反向链路：UHF RFID 反向背散射链路（标签→读写器，单站雷达方程 1/R⁴）：P_rx=EIRP·G_rx·λ²·σm/((4π)³d⁴)（Skolnik RCS 定义+Balanis 有效口径；Nikitin-Rao 2008 doi 10.1109/RFID.2008.4519368 链路预算框架），σm=(λ²G_tag²/4π)|Γ₁−Γ₂|²（Nikitin-Rao-Martinez 2007 Electron. Lett. 43(8):431，短路/开路态 |ΔΓ|=2 → σm=λ²G²/π）；给 tag_sensitivity_dbm 时合成读写距离=min(正向灵敏度门, 反向灵敏度门)

| 参数 | 说明 | 必填 |
|---|---|---|
| `frequency_hz` | float Hz 载波频率（UHF 860–960 MHz，域外显式拒绝） | 是 |
| `eirp_dbm` | float dBm 读写器发射 EIRP（含发射天线增益） | 是 |
| `g_reader_rx_dbi` | float dBi 读写器接收天线增益（单站=发射增益） | 是 |
| `distance_m` | float m 读写距离（>0） | 是 |
| `rx_sensitivity_dbm` | float dBm 读写器接收灵敏度（背散射检测门） | 是 |
| `g_tag_dbi` | float dBi 标签天线增益（γ 态算 σm 或正向门合成时必填） | 否 |
| `gamma_1` | float - 标签调制态 1 反射系数（Nikitin 功率波口径，有限即可） | 否 |
| `gamma_2` | float - 标签调制态 2 反射系数（与 gamma_1 成对） | 否 |
| `rcs_diff_m2` | float m² 差分 RCS 直给（与 γ 态二选一，同给显式报错） | 否 |
| `tag_sensitivity_dbm` | float dBm 标签激活灵敏度（给则合成读写距离） | 否 |

## rfid_forward_link

RFID正向链路：UHF RFID 正向链路（读写器→标签激活，Friis）：P_tag=EIRP·G_tag·(λ/4πd)²/L_pol（Friis 1946；Balanis §2 有效口径同式）；margin=P_tag−灵敏度；d_max=(λ/4π)·10^((EIRP+G_tag−L_pol−P_sens)/20)

| 参数 | 说明 | 必填 |
|---|---|---|
| `frequency_hz` | float Hz 载波频率（UHF 860–960 MHz，域外显式拒绝） | 是 |
| `eirp_dbm` | float dBm 读写器 EIRP（含发射天线增益） | 是 |
| `g_tag_dbi` | float dBi 标签天线增益（≥0，无源） | 是 |
| `distance_m` | float m 读写距离（>0；远场条件 d≥2D²/λ 由调用方自审） | 是 |
| `sensitivity_dbm` | float dBm 标签芯片激活灵敏度 | 是 |
| `polarization_loss_db` | float dB 极化/失配等附加损耗（≥0，默认 0） | 否 |

## ris_cascade_budget

NX-4 RIS 级联闭式表征（round14 :96-97，Björnson TWC 2020 N² 律；ETSI GR RIS 001 用例/KPI 语义引用，不抄数值）：BS-RIS-UE 三段几何级联（product-distance 逐元精确和+远场 N² 闭式）一键报告。缺省几何=RIS 在原点 xy 面、BS/UE 对称 30° 仰角（bs_pos_m/ue_pos_m [x,y,z] m 可覆盖）；共轭匹配相位 φ_n=k(d1n+d2n)（闭式对角化）vs 随机相位（固定种子 MC）vs 全零基线；无源波束指向角谱验证（谱峰 vs UE 几何方向偏角+均匀阵 −3dB 束宽锚）；b-bit 相位量化经验损失对拍 metasurface_lut.quantization_loss_db 解析 sinc² 带；直连 FSPL 对比与交叉距离 d_cross=4π·d1·d2/(N·λ)（短距直链占优的经典定量形态）。远场适用性按 Fraunhofer 2D²/λ 逐段诚实标注（近场精确和仍在场）

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float 频率 GHz（>0） | 是 |
| `n_x` | int RIS 单元列数（≥1；n_x=1 退化为点镜面） | 是 |
| `n_y` | int RIS 单元行数（≥1） | 是 |
| `d1_m` | float BS→RIS 中心距离 m（>0；缺省几何用） | 是 |
| `d2_m` | float RIS→UE 中心距离 m（>0；缺省几何用） | 是 |
| `period_mm` | float 单元间距 mm（>0；缺省 λ/2） | 否 |
| `bs_pos_m` | array BS 位置 [x,y,z] m（缺省几何可省） | 否 |
| `ue_pos_m` | array UE 位置 [x,y,z] m（缺省几何可省；与任一单元重合显式拒绝） | 否 |
| `tx_power_dbm` | float 发射功率 dBm（缺省 0，报告 received_power_dbm 用） | 否 |
| `gt_db` | float BS 天线增益 dBi（缺省 0 各向同性） | 否 |
| `gr_db` | float UE 天线增益 dBi（缺省 0） | 否 |
| `phase_mode` | str 'conjugate'\|'random'\|'none'（缺省 'conjugate'） | 否 |
| `bits` | int 相位量化位数（缺省 0=不量化；≥1 时挂 metasurface_lut 量化损失） | 否 |
| `random_seed` | int 随机相位种子（缺省 0；固定可复现） | 否 |
| `n_random_trials` | int 随机相位 MC trial 数（缺省 4096） | 否 |
| `include_direct` | bool 是否含直连对比与交叉距离（缺省 True） | 否 |

## sat_link_budget

卫星链路预算：AP-9 单跳卫星链路预算（JSON 进出，级表逐项风格）：C/N0 = EIRP − (FSPL+pointing+gas+rain) + G/T + 228.599（k=SI 精确值单源）。LEO 几何 elevation_deg∈(0,90]+alt_km>0 自算斜距 d=√((Re+h)²−(Re·cosE)²)−Re·sinE 与圆轨多普勒（rising/setting 反号；Re=6378km、GM=WGS-84 惯例），或 slant_km 直接给；G/T 单源复用 gt_link（t_sys_k/nf_db/t_e_k 三路径）。gas 项走 itu_atmosphere 降级面（P.676 表 UNVERIFIED→gas_db=0+注记，不产假数）；MODCOD 表 UNVERIFIED 档不做——margin 依据显式需求门 required_cn0_db_hz/required_cn_db/required_ebno_db，只出到 C/N0→C/N→margin。域守卫：仰角/高度/频率/损耗非负显式 ValueError

| 参数 | 说明 | 必填 |
|---|---|---|
| `link` | dict 链路描述（schema 见 core/sat_link.py sat_link_budget docstring：tx/path/rx 三段 + 可选 bw_hz/rb_bps/required_*） | 是 |

## saw_delay_line

声表面波延迟线：τ=L/v_R 恒等（L=收发 IDT 中心距）+ 传播损耗预算 α=α₁·(f/1GHz)²·τ（f² 黏滞衰减律写死；α₁=1GHz 每微秒损耗系数注入，缺省 0=纯延迟——材料系数文献发散不做缺省物理值）+ 双向换能器辐射损耗 10lg2=3.0103dB/只（匹配单电极口径，双端合计 6.0206dB 恒等锚）+ 波长数标尺。锚：τ=L/v 测试侧独立换算；f×2→损耗×4 标度；双端 2×10lg2 常数

| 参数 | 说明 | 必填 |
|---|---|---|
| `f0_ghz` | float GHz 工作频率（>0） | 是 |
| `v_sound_m_s` | float m/s 基板声速（>0） | 是 |
| `idt_gap_mm` | float mm 收发 IDT 中心距（>0） | 是 |
| `loss_db_per_us_1ghz` | float dB/µs@1GHz 传播损耗系数 α₁（≥0，缺省 0；f² 标度口径，实测系数按材料文献/实验覆盖注入） | 否 |

## saw_idt_frequency_response

声表面波 IDT δ 函数模型频响：指对=δ 源阵列 → H(f)=Σ e^{-j2πn·f/f0} 几何级数，归一功率 |H|²=[sin(πN·u)/(N·sin(πu))]²（u=Δf/f0，Dirichlet 核精确闭式）；零点栅格 Δf=k·f0/N（k=±1…）恒等、栅瓣 f=(m+1)f0 处归一功率=1（阵列因子混叠如实报告）；同点给 sinc 近似档 [sinc(N·u)]² 与相对偏差（仅主瓣区有效）。锚：测试侧几何级数逐项和互证 ≤1e-12；首零点 f0(1±1/N) |H|²→0；半零点 (2/π)² 经典常数；峰点 0dB

| 参数 | 说明 | 必填 |
|---|---|---|
| `f0_ghz` | float GHz 同步频率（>0） | 是 |
| `n_finger_pairs` | int 指对数 N_p（∈[1,10⁶]） | 是 |
| `freq_ghz` | float\|list[float] GHz 工作频点（逐点 >0；给绝对频率，失谐u=(f−f0)/f0 内部换算） | 是 |

## saw_idt_sync_design

声表面波 IDT 同步设计（双向）：指对周期 pitch≡同步声波长 λ0（指宽=缝宽=pitch/2 占空 0.5 惯例）↔ 同步频率 f0=v_R/λ0 双向解；N_p 指对数 → 换能器长度 L=N_p·λ0、自延迟 τ=L/v_R、零点-零点带宽 Δf_NN=2f0/N_p 与分数带宽 2/N_p（N_p↔带宽倒数关系）。锚：pitch→f0→pitch 往返逐位；Δf_NN·N_p=2f0 恒等；ST 石英 1µm→3.158GHz 教科书常数窗。基板声速文献典型值带见模块 docstring（LiNbO3 Y-Z 3488 / ST 石英 3158 / 36°YX-LiTaO3 ≈4212 m/s）

| 参数 | 说明 | 必填 |
|---|---|---|
| `v_sound_m_s` | float m/s 基板表面声速 v_R（>0；缺省无物理值，覆盖注入） | 是 |
| `n_finger_pairs` | int 指对数 N_p（∈[1,10⁶]） | 是 |
| `pitch_um` | float µm 指对周期（≡λ0；与 f0_ghz 恰给其一） | 否 |
| `f0_ghz` | float GHz 同步频率（与 pitch_um 恰给其一） | 否 |

## schiffman_phaser

Schiffman 耦合线移相器（电长度设计面）：短路耦合 C-section φ_c=arccos[(ρ−tan²θ)/(ρ+tan²θ)] vs 参考段 B·θ——三路线：分析（ρ/B/θ₀→Δφ(f₀)+频带响应+平坦度）、设计（Δφ 目标+ρ+B→θ₀ brentq 上升支反解）、平坦综合（Δφ 目标+B→ρ* 与 θ* 双条件——dΔφ/dθ=0 平坦峰）；λ/4 耦合段 vs 3λ/4 参考段经典 90° 锚精确；Z0e·Z0o=Z0² 全通匹配随行几何；(0,360) 连续支延拓全域

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 工作频率（>0；电长度→物理长度换算） | 是 |
| `ereff` | float 线有效相对介电常数（≥1，准 TEM 色散均值） | 是 |
| `z0_ohm` | float Ω 系统阻抗（>0，缺省 50；全通匹配 Z0e·Z0o=Z0²） | 否 |
| `rho` | float 阻抗比 ρ=Z0e/Z0o（>1 物理序；设计路线与 delta_phi_deg 同给） | 否 |
| `b_ratio` | float 参考段/耦合段电长度比 B=L_ref/L（>0，缺省 3=Schiffman 3λ/4 惯例） | 否 |
| `theta0_deg` | float° 耦合段电长度 θ₀（0<θ₀≤180；分析路线，与 delta_phi_deg 二选一） | 否 |
| `delta_phi_deg` | float° 目标差分相移（>0；设计路线——与 rho 同给走定 ρ 反解 θ₀，缺省 rho 走平坦综合双条件） | 否 |

## serial_yield_budget

多工序串联良率预算：独立口径乘积 ∏y_i + 总 DPMO；可选等相关高斯潜变量精确合并（rho>0，条件分解 1D 积分，ρ=0 退化乘积/ρ→1 退化 min 双极限锚）；任意相关结构恒真 Fréchet–Hoeffding 界 [max(0,Σy−N+1), min(y)] 如实并列（相关性口径声明，不冒充精确）

| 参数 | 说明 | 必填 |
|---|---|---|
| `yields` | array 各工序良率小数序列（每元素 ∈(0,1]，1..64 条） | 是 |
| `rho` | float 等相关系数 ρ（[0,1)；缺省 0=独立乘积精确；>0 走等相关高斯合并口径） | 否 |

## shielding_effectiveness

屏蔽效能速算：屏蔽效能（Schelkunoff 平面波三段闭式）：SE=A+R+B——吸收 A=20lg|e^{γt}|=8.686·t/δ（γ=(1+j)/δ 良导体）；反射 R=20lg|(Z_w+Z_s)²/(4Z_w Z_s)|（Z_s=√(jωμ/σ) 表面阻抗、Z_w=η0=376.73Ω 平面波）；多次反射修正 B=20lg|1−Γ²e^{−2γt}|（Γ=(Z_s−Z_w)/(Z_s+Z_w)；厚屏蔽 e^{−2γt}→0 ⟹ B→0，薄屏蔽 t<δ 时 B<0 负贡献）。屏蔽体=有耗传输线段（Schelkunoff 1934 TL 类比；Ott 2009 §6），恒等式 SE_total≡−20lg|S21_ABCD| 由单测钉住；近场源（电/磁偶极）阻抗修正未实现，source 仅支持 plane_wave

| 参数 | 说明 | 必填 |
|---|---|---|
| `frequency_hz` | float Hz 单点频率（与 f_axis_hz 二选一，同给显式拒绝） | 否 |
| `f_axis_hz` | list Hz 频率轴（逐点 >0；与 frequency_hz 二选一） | 否 |
| `thickness_m` | float m 屏蔽体厚度（>0） | 是 |
| `conductivity_s_per_m` | float S/m 电导率（>0；与 material 二选一，直给优先） | 否 |
| `mu_r` | float - 相对磁导率（>0，默认 1.0；material 命中表时取表值） | 否 |
| `material` | str 材料键（copper/aluminum/brass/steel_low_carbon，见 _SHIELD_MATERIALS） | 否 |
| `source` | str 源口径（仅 plane_wave；近场修正未实现，显式拒绝） | 否 |

## single_mode_applicator

单模加热腔：LT-6 单模 applicator（round18 :140）：TE10p 矩形腔谐振频率+场量归一（∫|E|²=V/4、储能 W=ε0εrE0²V/8、壁损逐壁闭式→Q_c）+介质负载功率沉积链（微扰装填因子 F=4εr′V_l·s/εrV、1/Q_d=F·tanδ、耦合 β=Q_u/Q_e、谐振吸收 4β/(1+β)²、能量平衡→E0 与 P_load 双路恒等）；可选样品块（sample_box_mm+sample_eps_r）触发介质微扰失谐（复用 cavity_perturbation_shift，Pozar §6.7 口径）。峰值 phasor 口径（P=(ω/2)ε0εr″∫|E|²dV）

| 参数 | 说明 | 必填 |
|---|---|---|
| `a_mm` | float mm 腔 x 边长（>0） | 是 |
| `b_mm` | float mm 腔 y 边长（>0） | 是 |
| `d_mm` | float mm 腔 z 边长（>0） | 是 |
| `wall_sigma_s_per_m` | float S/m 腔壁电导率（>0，铜 5.8e7） | 是 |
| `er` | float - 腔内介质相对介电常数（>0，缺省 1） | 否 |
| `p_index` | int - z 向半波数 p（≥1，缺省 1=TE101） | 否 |
| `input_power_w` | float W 输入功率（>0，缺省 1） | 否 |
| `load_v_l` | float L 介质负载体积（缺省 None=空腔） | 否 |
| `load_eps_r` | float - 负载 εr′（给 load_v_l 时必给，>0） | 否 |
| `load_tan_d` | float - 负载 tanδ（给 load_v_l 时必给，>0） | 否 |
| `q_ext` | float - 外部耦合 Q（>0；缺省 None=匹配口径） | 否 |
| `load_x_mm` | float mm 负载重心 x（缺省 a/2 波腹） | 否 |
| `load_z_mm` | float mm 负载重心 z（缺省 d/2 波腹；偶 p 中心为波节会显式报错） | 否 |
| `sample_box_mm` | array [x0,y0,z0,x1,y1,z1] 微扰失谐样品盒（mm，腔内；给则触发 cavity_perturbation_shift） | 否 |
| `sample_eps_r` | float - 样品 εr（>1 介质微扰；缺省 None=金属微扰路线，透传复用键口径） | 否 |

## siw_analysis

SIW 分析：Cassivi 2002 等效宽度 + RWG TE10 等效 (w, d, s, εr, f) → (fc10, weff, β, λg, Z_TE, Z_PV)；过孔设计规则违规显式报错不外推。

| 参数 | 说明 | 必填 |
|---|---|---|
| `w_mm` | float mm 两过孔列心距（物理宽度） | 是 |
| `d_mm` | float mm 金属化过孔直径 | 是 |
| `s_mm` | float mm 过孔心距（同列相邻孔中心间距） | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `freq_ghz` | float GHz 工作频率（β/λg/设计规则 d<λ_sub/5 检查） | 是 |

## siw_synthesis

SIW 综合：目标 TE10 截止 fc10 → 两列心距 w（w_eff=c/(2·fc10·√εr) 反解 Cassivi 式；设计规则违规显式报错；回代自洽）。

| 参数 | 说明 | 必填 |
|---|---|---|
| `fc10_ghz` | float GHz 目标 TE10 截止频率 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `d_mm` | float mm 金属化过孔直径 | 是 |
| `s_mm` | float mm 过孔心距 | 是 |

## slot_array_synthesis_resonant

谐振缝隙阵综合（Stevenson 驻波阵口径）：权重向量 wn（外部幅度综合产物，如 Taylor）→ 逐缝相对电导 gn=g_total·wn²/Σw²（Σgn=g_total，缺省 1=单馈匹配）+ 反解偏置+相邻缝交替换边符号序列+λg/2 等间距轴向位置+末缝后 λg/4 短路位；单缝 gn≤g_max(f) 守卫（f 高于 9.753GHz WR90 时 g_max<1，g_total=1 单馈匹配须按 N≥ceil(1/g_max) 分摊）

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 工作频率（TE10 单模域 fc<f<2fc） | 是 |
| `a_mm` | float mm 波导宽壁内尺寸（>0；WR-90=22.86） | 是 |
| `b_mm` | float mm 波导窄壁内尺寸（>0 且 <a；WR-90=10.16） | 是 |
| `n_slots` | int 缝数（2..128） | 是 |
| `weights` | list[float] 逐缝幅度权重（≥0 有限，长度=n_slots，全零拒绝；可为 array.villeneuve_weights 等外部综合产物） | 是 |
| `g_total` | float Σgn 目标（>0，缺省 1.0=单馈匹配口径） | 否 |

## slot_stevenson_conductance

波导缝隙 Stevenson 电导（正反解）：宽壁纵向偏置缝谐振相对电导 g(x)=2.09(a/b)(λg/λ0)cos²(πλ0/2λg)sin²(πx/a)——offset→g 正解或 g→offset 反解（route 自动分派，二选一）；随行 g_max(f) 元数据与 g_max=1 边界频率（WR90=9.753118GHz，低于此值单缝匹配 g=1 可达）；g>g_max 显式拒绝（公式封顶非缺陷）；谐振缝长=λ0/2 理想口径

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 工作频率（TE10 单模域 fc<f<2fc） | 是 |
| `a_mm` | float mm 波导宽壁内尺寸（>0；WR-90=22.86） | 是 |
| `b_mm` | float mm 波导窄壁内尺寸（>0 且 <a；WR-90=10.16） | 是 |
| `offset_x_mm` | float mm 缝中心偏置（0≤x≤a/2；与 g 二选一） | 否 |
| `g` | float 目标相对电导 G/G0（0≤g≤g_max；与 offset_x_mm 二选一） | 否 |

## slotline_analysis

槽线（slotline）分析：Janaswamy–Schaubert 闭式 (w, h, εr, f) → (λ'/λ0, εeff, β, Z0)；越有效域显式报错不外推。

| 参数 | 说明 | 必填 |
|---|---|---|
| `w_mm` | float mm 槽宽（金属面上的缝） | 是 |
| `h_mm` | float mm 基板厚（单面金属，基板下为空气） | 是 |
| `epsilon_r` | float - 基板相对介电常数（2.22–9.8 两段拟合） | 是 |
| `freq_ghz` | float GHz 频率（W/λ0、d/λ0 进入拟合式，必需） | 是 |

## slotline_synthesis

槽线（slotline）综合：目标 Z0 → 槽宽 w（同频窄槽段 0.0015≤W/λ0≤0.075 括号内 brentq，回代自洽；不可达/越域显式报错）

| 参数 | 说明 | 必填 |
|---|---|---|
| `z0_ohm` | float Ω 目标特性阻抗（功率-电压定义） | 是 |
| `h_mm` | float mm 基板厚 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `freq_ghz` | float GHz 频率 | 是 |

## small_loop_zin

小环输入阻抗分解（电小圆环，N 匝）：辐射电阻 Rr=320π⁴·N²·(A/λ²)² ≡ 20π²·N²·(C/λ)⁴ ≈ 31171·N²·(A/λ²)² 三式恒等（320π⁴=31170.9 测试钉）；趋肤损耗 R_L=Rs·N·b/a（Rs=√(πfμ/σ)，表面电流口径）；效率 Rr/(Rr+R_L)；电感 L=μ0·b·[ln(8b/a)−2]（Grover 单匝闭式，X=2πf·N²·L 密绕 N² 近似如实注记）；Q=X/(Rr+R_L)。电小判据 C/λ≤0.3 守卫（超出电小假设显式拒绝）

| 参数 | 说明 | 必填 |
|---|---|---|
| `radius_mm` | float mm 环半径 b（>wire_radius_mm） | 是 |
| `f_ghz` | float GHz 工作频率（>0） | 是 |
| `wire_radius_mm` | float mm 导线半径 a（0<a<radius_mm） | 是 |
| `turns_n` | float 匝数 N（≥1；N² 标度口径，非整数仅作标度插值） | 是 |
| `conductivity_s_per_m` | float S/m 导体电导率（>0；Cu=5.8e7） | 是 |

## spur_search

DP-5 混频杂散落带搜索：f_spur=|m·f_RF±n·f_LO| 全阶枚举（缺省 m+n≤7），矩形近似卷积落带判据，危险等级=阶数反比；只报频率落带不报电平

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_rf_hz` | float Hz RF 中心频率（>0） | 是 |
| `f_lo_hz` | float Hz 本振频率（>0） | 是 |
| `if_center_hz` | float Hz 目标 IF 中心（缺省 \|f_RF−f_LO\|） | 否 |
| `if_bw_hz` | float Hz 目标带宽（默认 0） | 否 |
| `rf_bw_hz` | float Hz RF 信号带宽（默认 0，谐波带宽线性缩放） | 否 |
| `lo_bw_hz` | float Hz LO 带宽（默认 0=理想 LO） | 否 |
| `max_order` | int 最大阶数 m+n（默认 7） | 否 |

## srr_permeability

SRR磁导率：MM-7 Pendry 1999 SRR 阵列等效磁导率（IEEE TMTT 47(11):2075 Lorentz 形，arXiv 2006.13861 同式互证）：μ(ω)=1−F·ω²/(ω²−ω0²+iΓω)。F 填充因子与 f_mp（磁等离子频率）二选一入参（f_mp>f_res，F=1−(f_res/f_mp)²）。解析锚：μ(0)=1、μ(∞)=1−F、无损 μ(f_mp)=0、Re μ<0 带恰 =(f_res,f_mp)、Γ>0 全带 Im μ>0（无源性）。无损谐振点（分母零）与 非物理域显式拒绝。诚实边界：几何闭式 ω0(环尺寸) 原文常数需回 PDF 逐位核（#118），留 MM-11 极化率库——本键只收 Lorentz 参数化

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | float 工作频率 GHz（>0） | 是 |
| `f_res_ghz` | float 环谐振频率 f_res=ω0/2π GHz（>0） | 是 |
| `fill_factor` | float 填充因子 F ∈(0,1)（与 f_mp_ghz 二选一） | 否 |
| `f_mp_ghz` | float 磁等离子频率 GHz（>f_res；与 fill_factor 二选一） | 否 |
| `gamma_ghz` | float 阻尼 Γ/2π GHz（≥0，默认 0=无损） | 否 |

## step_attenuator_design

步进衰减器综合：二进制加权位组合（N 位、LSB=step_db → 量程 step_db·(2^N−1)、分辨率=step_db）——目标衰减 realized=floor(target/step) 的位组合（量化余量 residual 如实输出），逐 engaged 位π/T 衰减节电阻闭式（单源消费 rf_match attenuator 键）+堆叠误差 worst-case/RSS 两口径（给逐位精度规格时）

| 参数 | 说明 | 必填 |
|---|---|---|
| `attenuation_db` | float dB 目标衰减（≥0 且 ≤量程；超量程显式拒绝不回卷） | 是 |
| `step_db` | float dB 最低位步进 LSB（>0，缺省 1） | 否 |
| `n_bits` | int 位数（[1,8]，缺省 5 → 31dB 量程） | 否 |
| `z0_ohm` | float Ω 系统阻抗（>0，缺省 50） | 否 |
| `pad_topology` | str 衰减节拓扑 pi\|t（缺省 pi） | 否 |
| `per_step_accuracy_db` | list[float] 逐位精度规格（≥0 有限，长度=n_bits；可选——给定时输出 worst-case/RSS 堆叠误差） | 否 |

## stripline_analysis

对称带状线分析（零厚度闭式，椭圆积分）：(w, b) → Z0

| 参数 | 说明 | 必填 |
|---|---|---|
| `w_mm` | float mm 中心导带宽度 | 是 |
| `b_mm` | float mm 两接地平面间距 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `freq_ghz` | float GHz 频率（可选，给了才返回 λg） | 否 |

## stripline_synthesis

对称带状线综合（零厚度闭式求逆）：目标 Z0 → w

| 参数 | 说明 | 必填 |
|---|---|---|
| `z0_ohm` | float Ω 目标特性阻抗 | 是 |
| `b_mm` | float mm 两接地平面间距 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |

## stub_tuner_double

双支节并联调配器：归一电纳解析解（Pozar §5.3）——负载导纳 y_L=Z0/Z_L=g+jb，支节总电纳 u 自由 → 经间距 t=tanβd 变换 g2=g(1+t²)/[(1−tu)²+t²g²]，g2=1 ⟺ (1−tu)²=g[1+t²(1−g)]，有解 ⟺ g ≤ csc²(βd)=g_max（λ/8 间距禁区 g>2 经典口径；禁区负载如实返 solvable=False+边界数据不拒绝）；解 u=[1∓√D]/t 取 |u| 最小支，b_s1=u−b、b_s2=−Im(y2)，开路/短路支节长度 l/λ（回代 tan/cot 恒等）；ABCD 级联 |Γ_in| 回代机器精度级（matched 旗标）。stub1_deg 可旋转负载出禁区。锚：g_max(45°)=2.0、g_max(60°)=4/3 解析钉；可调区随机负载独立 ABCD 回收

| 参数 | 说明 | 必填 |
|---|---|---|
| `rl_ohm` | float Ω 负载电阻实部（>0；纯电抗负载退化显式拒绝） | 是 |
| `xl_ohm` | float Ω 负载电抗（有限任意，可负） | 是 |
| `z0_ohm` | float Ω 传输线特性阻抗（>0，缺省 50） | 否 |
| `spacing_deg` | float deg 支节间距电长度 βd（∈[5,175] 且 ≠90°，缺省 45=λ/8；3λ/8=135 同禁区） | 否 |
| `stub1_deg` | float deg 负载→第一支节线长电长度（∈[0,180)，缺省 0=负载在首支节；可旋转负载出禁区） | 否 |
| `stub_type` | str 支节终端类型 'open'\|'short'（缺省 open） | 否 |

## stub_tuner_triple

三支节并联调配器（等间距级联）：首支节旁路/旋转双路线消除双支节禁区——①Re[T(y_a,t)] ≤ g_max → b_s1=0 按双支节解后两支节；②否则首支节取总电纳 u1 使 g2=1（g_a≤g_max，u1=[1∓√D]/t 取 |u1| 最小支）或 u1=1/t 取可达电导上峰 (1+t²)/(t²g_a)<1<g_max（g_a>g_max），再解后两支节——任意 r_L>0 负载有解。route 字段如实报告路线（bypass_first/rotate_first）；ABCD 四节级联 |Γ_in| 回代机器精度级。锚：双支节禁区负载（如 z_L=10+j10 Ω@50Ω，g=2.5>2）三支节 matched=True；200 随机负载全匹配

| 参数 | 说明 | 必填 |
|---|---|---|
| `rl_ohm` | float Ω 负载电阻实部（>0） | 是 |
| `xl_ohm` | float Ω 负载电抗（有限任意，可负） | 是 |
| `z0_ohm` | float Ω 传输线特性阻抗（>0，缺省 50） | 否 |
| `spacing_deg` | float deg 相邻支节间距电长度 βd（∈[5,175] 且 ≠90°，缺省 45=λ/8） | 否 |
| `stub1_deg` | float deg 负载→第一支节线长电长度（∈[0,180)，缺省 0） | 否 |
| `stub_type` | str 支节终端类型 'open'\|'short'（缺省 open） | 否 |

## suspended_stripline_analysis

悬置带线分析（基板厚 h 居中夹带、腔高 b）：共形电容比闭式 (w, b, h) → (Z0, εeff)

| 参数 | 说明 | 必填 |
|---|---|---|
| `w_mm` | float mm 中心导带宽度 | 是 |
| `b_mm` | float mm 两接地平面间距（腔高） | 是 |
| `h_mm` | float mm 基板厚度（0≤h≤b，以带为中面对称填充） | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `freq_ghz` | float GHz 频率（可选，给了才返回 λg） | 否 |

## suspended_stripline_synthesis

悬置带线综合：目标 Z0 → w（固定 b/h，brentq 回代自洽，越界显式报错）

| 参数 | 说明 | 必填 |
|---|---|---|
| `z0_ohm` | float Ω 目标特性阻抗 | 是 |
| `b_mm` | float mm 两接地平面间距（腔高） | 是 |
| `h_mm` | float mm 基板厚度（0≤h≤b） | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |

## swerling_detection_factor

Swerling检测因子：SW1-4 起伏目标检测因子三量互算（Pfa/Pd/SNR 三给二解一，N 脉冲非相干积累，平方律检波固定门限 T=Q⁻¹(N,Pfa) 与 k 无关）。快起伏精确闭式档：SW2 Pd=Q(N,T/(1+S̄))（信号复高斯与噪声严格合并）；SW4 有限正权重 Γ 混合 Pd=Σ C(N,m)β'^(N−m)a^(−m)Q(2N−m,T/a)（特征函数部分分式，本仓推导）；慢起伏数值积分档（如实声明）：SW1/SW3 Pd=E_X[ncx2.sf(2T;2N,2NX)]、X~Gamma(k,S̄/k)，quad 固定容差确定性。N=1 退化恒等：SW1≡SW2 Pd=Pfa^(1/(1+S̄))、SW3≡SW4（数值积分复现闭式=机器精度锚）。锚：Pfa=1e-6/Pd=0.9/N=1 → SW1=21.14dB vs SW0 精确 13.18dB（损失 7.96dB=经典 Swerling 损耗曲线数 dB 窗）。swerling 只收 1/2/3/4，SW0 显式拒绝指回 albersheim_detection_snr。出处 Swerling 1954/Marcum 1950 IRE；Richards FRSP 2ed ch.6/Skolnik 3ed ch.2 转引

| 参数 | 说明 | 必填 |
|---|---|---|
| `pfa` | float - 虚警概率（0<Pfa<1；与 pd/snr_db 三给二解一） | 否 |
| `pd` | float - 检测概率（0<Pd<1 且 >pfa；与 pfa/snr_db 三给二解一） | 否 |
| `snr_db` | float dB 单脉冲平均 SNR（与 pfa/pd 三给二解一） | 否 |
| `swerling` | int - Swerling 例号 1/2/3/4（SW0 非起伏显式拒绝，走 albersheim_detection_snr） | 否 |
| `n_pulses` | float - 非相干积累脉冲数 N（[1,4096] 整数，默认 1） | 否 |

## swerling_integration_gain

Swerling积累增益：非相干积累改善因子与积累损失（SW1-4，N 脉冲 vs 单脉冲同 Pd/Pfa 检测因子差）。improvement_db=SNR1−SNN（积累节省的每脉冲 SNR，>0 单调律）；coherent_reference_db=10lgN（相干积累参考界）；integration_loss_db=10lgN−improvement：SW1/SW3 慢起伏 ≥0（相关序列积累增益低于相干界，经典结论）；SW2/SW4 快起伏可为负——独立起伏采样的起伏分集增益超出相干界（经典 Swerling 改善因子曲线结论，符号如实不夹持）。N=1 退化恒等（三量全 0）。精度层级随例号同 swerling_detection_factor（快闭式/慢数值积分）。出处 Swerling 1954；Richards FRSP 2ed ch.6/Skolnik 3ed ch.2 转引

| 参数 | 说明 | 必填 |
|---|---|---|
| `pfa` | float - 虚警概率（0<Pfa<1） | 是 |
| `pd` | float - 检测概率（0<Pd<1 且 >pfa） | 是 |
| `swerling` | int - Swerling 例号 1/2/3/4（SW0 显式拒绝） | 是 |
| `n_pulses` | float - 非相干积累脉冲数 N（[1,4096] 整数） | 是 |

## switched_line_phaser

开关线移相器：SPDT 间参考臂/延迟臂路径差电长度二态——Δφ=360°·Δl·√εeff·f/c0 正解（Δφ→Δl=Δφ/360°·λg）或 Δl→Δφ 反解（route 二选一）；真时延（TTD）口径：Δφ 随 f 线性外推零相差误差、群时延 Δt=Δl√εeff/c0=Δφ/(360°f)；参考臂缺省 λg/4 布局惯例（不影响 Δφ）；180° 位 Δl=λg/2 精确可达

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 工作频率（>0） | 是 |
| `ereff` | float 线有效相对介电常数（≥1） | 是 |
| `z0_ohm` | float Ω 线特性阻抗（>0，缺省 50） | 否 |
| `delta_phi_deg` | float° 目标差分相移（0<Δφ<360 开区间主值；设计路线，与 delay_line_mm 二选一） | 否 |
| `delay_line_mm` | float mm 路径差物理长度 Δl（>0；反解路线） | 否 |
| `ref_len_mm` | float mm 参考臂长度（>0，缺省 λg/4 布局惯例） | 否 |

## switched_network_phaser

开关网络式移相器：PIN 开关选通 LC 低通 T 节移相网络（滞后相位态 vs 直通参考）——镜像参数设计闭式 L=2Z0·tan(φ/2)/ω₀、C=sinφ/(ω₀Z0)、截止 f_c=f₀/sin(φ/2)、f₀ 处 Z_T=Z0 精确匹配；单网络路线（φ→L/C/截止/开关插损）或 N 位级联路线（权重 180/2^i 逐位设计+全开 Δφ=360−LSB+量化 RMS=LSB/√12+总开关插损）；与 pin_diode_limiter 同章开关口径衔接

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_ghz` | float GHz 工作频率（>0） | 是 |
| `z0_ohm` | float Ω 系统阻抗（>0，缺省 50） | 否 |
| `phi_deg` | float° 单网络目标相位滞后（0<φ<180 开区间；单网络路线，与 n_bits 二选一） | 否 |
| `n_bits` | int 位数（1..8；N 位级联路线，与 phi_deg 二选一） | 否 |
| `r_on_ohm` | float Ω PIN 串联开关导通电阻（≥0，缺省 0=理想开关；每位 2 只串联开关） | 否 |

## t_match_design

T-match 设计闭式：几何+Za+目标 Rin → T 棒长度（正根二次式）与两只对称串联谐振化电容 C=1/(πf·Xin)（Balanis (9-55)）；含正向回代复核 rin_re_check；步升 (1+α)²·Re(Za) ≤ 目标显式报错（并联短截线只能降实部）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_hz` | float Hz 设计频率 | 是 |
| `main_radius_m` | float m 主偶极子半径 a | 是 |
| `bar_radius_m` | float m T 棒半径 a' | 是 |
| `spacing_m` | float m 两棒中心距 s | 是 |
| `za_re_ohm` | float Ω 天线阻抗实部（默认 73=半波锚） | 否 |
| `za_im_ohm` | float Ω 天线阻抗虚部（默认 0=谐振点设计） | 否 |
| `target_rin_ohm` | float Ω 目标输入实部（默认 50） | 否 |

## t_match_impedance

T-match阻抗：T-match 输入阻抗（Balanis 3ed §9.7.3，(9-48)–(9-51)）：α=acosh((v²−u²+1)/2v)/acosh((v²+u²−1)/2uv)（u=a/a', v=s/a'）；Zt=jZ0·tan(kl'/2)、Z0=60·acosh((s²−a²−a'²)/(2aa'))；Zin=2Zt(1+α)²Za/(2Zt+(1+α)²Za)；l'≈λ/2 折合极限 Zin→(1+α)²Za（等半径 α=1→4Za）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_hz` | float Hz 设计频率 | 是 |
| `main_radius_m` | float m 主偶极子半径 a | 是 |
| `bar_radius_m` | float m T 棒半径 a' | 是 |
| `spacing_m` | float m 两棒中心距 s（≥a+a'，相交显式拒绝） | 是 |
| `tbar_length_m` | float m T 棒总长 l'（<λ，tan 主支） | 是 |
| `dipole_length_m` | float m 主偶极子长度（≥l'，T-match 定义） | 是 |
| `za_re_ohm` | float Ω 无 T-match 天线中心阻抗实部（默认 73=半波锚） | 否 |
| `za_im_ohm` | float Ω 同上虚部（默认 42.5=半波锚） | 否 |

## thermal_resistance_stack

1-D 热阻栈（结→壳→散热器→环境）：串联 Σθ 与可选并联完整支路 1/(Σ1/θi) 构成热阻网络，Tj = Ta + P·θtot（教科书电阻类比）

| 参数 | 说明 | 必填 |
|---|---|---|
| `power_w` | float W 耗散功率（≥0） | 是 |
| `ambient_c` | float °C 环境温度 | 是 |
| `theta_jc_c_per_w` | float °C/W 结→壳（串联链必需项） | 是 |
| `theta_cs_c_per_w` | float °C/W 壳→散热器（默认 0） | 否 |
| `theta_sa_c_per_w` | float °C/W 散热器→环境（默认 0） | 否 |
| `parallel_paths_c_per_w` | array °C/W 并联完整支路热阻（默认空） | 否 |

## three_antenna_gain

三天线法增益定标：同 R/λ 三对插入损耗 ILij（须先扣电缆/接头并做失配与极化校正）经 Friis 口径 G_i+G_j=FS−IL_ij 线性解三元组 G1=(FS−IL12−IL13+IL23)/2（G2/G3 轮换），FS=20lg(4πR/λ)、λ=C_MM_GHZ/f 单源；构造恒等式 G_i+G_j=FS−IL_ij 随 pair_sum_max_err 自检（机器精度级）。可选 method='comparison' 增益比较法：同场地参考替代 G_dut=G_ref+(IL_ref−IL_dut)。锚：对称 IL→三增益相等恒等；Friis 正演→反演逐位回收（独立 92.45+20lgf_GHz+20lgd_km 常数式双源）。出处 IEEE Std 149 天线测量惯例/Friis 传输公式

| 参数 | 说明 | 必填 |
|---|---|---|
| `method` | str 定标方法 'three_antenna'（缺省）\|'comparison' | 否 |
| `il12_db` | float dB 天线 1-2 对插入损耗（失配/极化校正后） | 否 |
| `il13_db` | float dB 天线 1-3 对插入损耗 | 否 |
| `il23_db` | float dB 天线 2-3 对插入损耗 | 否 |
| `f_ghz` | float GHz 定标频率（三天线法必需） | 否 |
| `range_m` | float m 收发距离（三天线法必需，远场条件须另行满足） | 否 |
| `ref_gain_db` | float dBi 参考天线增益（比较法必需） | 否 |
| `il_ref_db` | float dB 参考天线对插入损耗（比较法必需） | 否 |
| `il_dut_db` | float dB 被测天线对插入损耗（比较法必需） | 否 |

## tnvna_band_stitch

TH-2 TNVNA 跨带拼接器：相邻两带（低/高由 f_start 判定）在重叠区按到带缘归一距离线性权重合并（带缘 C0 连续），输出全带拼接曲线；重叠一致性=max|S_low−S_high| vs 调用方 tol_abs_linear（#122 阈值不 ship）→ consistent/inconsistent；带界预算=权重合成 σ=sqrt((w·σlo)²+((1−w)·σhi)²) 逐点（max+两带缘）。域守卫：两带频栅严格递增全正；重叠区必须同频点（异栅格如实拒绝不静默插值）；恰共点=退化单点重叠等权合并；无重叠=butt 直连如实报告（verdict='no_overlap'）。N>2 带链式拼接为登记 followUp

| 参数 | 说明 | 必填 |
|---|---|---|
| `band_a` | dict {freq_hz, s(list[[re,im]]), sigma, name?} | 是 |
| `band_b` | dict 同 band_a | 是 |
| `tol_abs_linear` | float 重叠区一致性阈值（线性域 \|ΔS\|，>=0，必填） | 是 |

## tnvna_extender_error_model

扩频VNA误差：TH-2 THz VNA 扩频器一端口三项误差模型修正+1σ 预算：Γ=(M−Ed)/(Er+Es·(M−Ed))（经典一端口误差模型闭式反演，Hesler ISSTT 2010 按带标定语义）；预算=一阶灵敏度 RSS（NIST MUF 口径）σ_Γ=sqrt(|Er|²(σM²+σEd²)+|N|⁴σEs²+|N|²σEr²)/|D|²，N=M−Ed、D=Er+Es·N。Ed/Es/Er 为带级标定复数（标量 [re,im] 广播）或逐点；σ 四项=修正后残余幅值（线性域，≥0，缺省 0）。域守卫：|Er| 逐点非零、修正分母非零（奇异显式拒绝不外推）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_hz` | list[float] Hz 频率点列（>=1 点，全正） | 是 |
| `measured` | list[[re,im]] 原始（未修正）反射复数列 | 是 |
| `ed` | [re,im] 或 list[[re,im]] directivity 误差项 | 是 |
| `es` | [re,im] 或 list[[re,im]] source match 误差项 | 是 |
| `er` | [re,im] 或 list[[re,im]] reflection tracking 误差项 | 是 |
| `sigma_m` | float 原始测量残余 1σ（线性域，缺省 0） | 否 |
| `sigma_ed` | float Ed 残余 1σ（缺省 0） | 否 |
| `sigma_es` | float Es 残余 1σ（缺省 0） | 否 |
| `sigma_er` | float Er 残余 1σ（缺省 0） | 否 |

## trl_line_electric_scan

TRL电长度扫描：TRL 线标准适用性键（频带电长度扫描 + 覆盖率）：给定线长 line_length_mm（波导 wr_name 或 TEM z0/εeff 双路同 trl_standards_design）与频带 f1–f2 → 逐频点电长度 θ(f)=360°·L/λg(f) 数组、[20°,160°] 经典窗覆盖率（窗内点占比）、窗界连续解 [f_lo,f_hi]（闭式逆：波导 f=√(fc²+(θ·C/(360L))²)/TEM 线性逆）与全带覆盖判定。θ 随 f 单调升（λg 降）。守卫同族：线长>0、n_points∈[2,2001]、波导 f<1.05·fc 拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `wr_name` | str - WR 波导型号（rw_tables 单源；与 z0/εeff 二选一） | 否 |
| `z0_ohm` | float Ω TEM 线特性阻抗（显式口径） | 否 |
| `epsilon_eff` | float - TEM 线有效介电常数（≥1） | 否 |
| `line_length_mm` | float mm 线标准物理长度（>0） | 是 |
| `f1_ghz` | float GHz 频带下缘（>0） | 是 |
| `f2_ghz` | float GHz 频带上缘（>f1） | 是 |
| `n_points` | int 扫描点数（[2,2001]，缺省 41） | 否 |

## trl_standards_design

TRL 校准件设计面（直通/反射/线标准件综合）：给定波导（wr_name 走 rw_tables 单源）或 TEM 线（z0_ohm/epsilon_eff 显式）与频带 f1–f2 → 线标准长度=带中心 λg/4（Engen-Hoer 1979/NIST TN 1341 规则）、直通长度（0=flush 或短直通）、反射标准（短路/开路 × ideal/λg/4 偏置，归一化电抗回显，|Γ|≡1 口径）+ 经典窗双判据（带缘电长度 [20°,160°] 推荐窗 + 单线频带比 f2/f1∈[1.2,3]；越窗给多线 TRL 建议 note）。锚：WR-90@10GHz λg/4=9.927mm；TEM 比值 8 恰触 20°/160° 窗界。守卫：波导 f<1.05·fc 拒绝（λg 发散）；wr_name 与 z0/εeff 互斥

| 参数 | 说明 | 必填 |
|---|---|---|
| `wr_name` | str - WR 波导型号（如 'WR-90'，rw_tables 单源；与 z0_ohm/epsilon_eff 二选一） | 否 |
| `z0_ohm` | float Ω TEM 线特性阻抗（显式口径，须与 epsilon_eff 同给） | 否 |
| `epsilon_eff` | float - TEM 线有效介电常数（≥1） | 否 |
| `f1_ghz` | float GHz 频带下缘（>0） | 是 |
| `f2_ghz` | float GHz 频带上缘（>f1） | 是 |
| `through_length_mm` | float mm 直通长度（≥0，缺省 0=flush 口径） | 否 |
| `reflect_type` | str - short\|open（缺省 short） | 否 |
| `reflect_offset` | str - ideal\|quarter_wave（缺省 ideal；quarter_wave=λg/4 偏置短路段，无损线变换） | 否 |

## two_ray_loss

双径干涉路损：AP-5 双径干涉路损（平坦地面镜反射相干和，Rappaport 2nd ed §4.6）：LOS+镜反射 Fresnel 反射系数 Γ_v/Γ_h（σ=0 纯介电 eps_r）相干叠加，L=FSPL(d_los)−20log10|1+Γe^{jΔφ}|；附断点距离 d_break=4·h_tx·h_rx/λ、掠射角、Γ 元数据（d>>d_break 后包络 −40dB/dec 渐近）

| 参数 | 说明 | 必填 |
|---|---|---|
| `d_m` | float m 收发水平距离（>0） | 是 |
| `h_tx_m` | float m 发端天线高（>0） | 是 |
| `h_rx_m` | float m 收端天线高（>0） | 是 |
| `f_hz` | float Hz 载波频率（>0） | 是 |
| `eps_r` | float 地面相对介电常数（默认 15.0，中等湿地面；>1） | 否 |
| `pol` | str 极化 'v'/'h'（默认 'v'，选垂直/水平 Fresnel 系数） | 否 |

## unequal_split_wilkinson

不等分功分器：Wilkinson 二路不等分功分器综合（Pozar K 口径 K²=P3/P2）：给定端接 Z0 与功分比 → 两臂 λ/4 特性阻抗 Z02/Z03 + 隔离电阻 R（含臂端分配 R2/R3）+ 两输出 λ/4 变换段阻抗 Z04/Z05（Parad–Moynihan 几何均值选型）+ 中心频率理论分配/极值说明。K=1 退化为等分（臂 √2·Z0、R=2·Z0）；K≤0 显式拒绝；K 极值下阻抗单调不产生负值（>10:1 如实标 practical_split=False 不拒绝）。公式出处 Pozar 4th ed §7.3 / Parad–Moynihan 1965，文献锚 2:1→51.5/103/106.07Ω @50Ω。

| 参数 | 说明 | 必填 |
|---|---|---|
| `z0_ohm` | float Ω 端接/输入特性阻抗 | 是 |
| `power_ratio_k` | float - 功分比 K（K²=P3/P2，K>0；K>1 端口 3 为大功率端，K=1 等分） | 是 |
| `freq_ghz` | float GHz 可选设计频率（给出则附自由空间 λ0/4 参考长度；不含基板有效介电） | 否 |

## vna_reflection_uncertainty

反射测量不确定度：VNA 校准后残差三误差项经典纹波合成（单端口模型）——δΓ≈Ed+ΔTr·Γ+Es·Γ² 一阶展开，最坏界 |δΓ|≤|Ed|+|ΔTr||Γ|+|Es||Γ|²，方向性/跟踪/源匹配逐项分解+主导项判读；rss 档按均匀分布 Type-B（界/√3）方和根给 u 与扩展 U=k·u（EURAMET cg-12 惯例）。回损域换算 RL=−20lg|Γ|（最坏窗口/u_RL=8.686u/|Γ|）。残差 dB 口径：方向性/源匹配=20lg|残差系数|（<0），跟踪=±dB 纹波（线性化 10^(dB/20)−1）。锚：Γ=0 回损地板=−directivity_db 恒等；20dB 负载@40dB 残差纹波 ~±0.9dB 经典带。出处 Rytting 误差模型/EURAMET cg-12/Keysight AN 1287

| 参数 | 说明 | 必填 |
|---|---|---|
| `gamma_mag` | float - 反射系数幅值 \|Γ\|（[0,1]；0=理想负载合法） | 是 |
| `directivity_db` | float dB 残差方向性 \|Ed\|（20lg 口径，<0；校准后典型 −45~−55） | 是 |
| `source_match_db` | float dB 残差源匹配 \|Es\|（20lg 口径，<0；校准后典型 −40~−50） | 是 |
| `tracking_db` | float dB 反射跟踪残差 ±dB 纹波（[0,10]，缺省 0） | 否 |
| `combine` | str 合成方式 'worst'（最坏纹波界，缺省）\|'rss'（Type-B 方和根） | 否 |
| `k` | float 扩展不确定度包含因子（rss 档，≥1，缺省 2） | 否 |

## vna_transmission_uncertainty

传输测量不确定度：VNA 校准后残差三误差项经典纹波合成（传输侧四误差模型）——δS21≈Xt+ΔEt·S21+El·S21² 一阶展开，最坏界 |δS21|≤|Xt|+|ΔEt||S21|+|El||S21|²，串扰/跟踪/负载匹配逐项分解+主导项判读；rss 档均匀分布 Type-B（界/√3）方和根 u 与扩展 U=k·u。增益域换算 G=20lg|S21|（最坏窗口/u_G=8.686u/|S21|）。锚：S21=0 隔离地板=−crosstalk_db 恒等；直通@El=−20dB 纹波 20lg(1.1)=0.828dB 独立重算。出处 Rytting 误差模型/EURAMET cg-12/Keysight AN 1287

| 参数 | 说明 | 必填 |
|---|---|---|
| `s21_mag` | float - 传输系数幅值 \|S21\|（≥0 有限；>1 有源器件线性化口径照算） | 是 |
| `crosstalk_db` | float dB 残差串扰/泄漏 \|Xt\|（20lg 口径，<0；典型 −80~−100） | 是 |
| `load_match_db` | float dB 残差负载匹配 \|El\|（20lg 口径，<0；典型 −35~−45） | 是 |
| `tracking_db` | float dB 传输跟踪残差 ±dB 纹波（[0,10]，缺省 0） | 否 |
| `combine` | str 合成方式 'worst'（最坏纹波界，缺省）\|'rss'（Type-B 方和根） | 否 |
| `k` | float 扩展不确定度包含因子（rss 档，≥1，缺省 2） | 否 |

## vswr_convert

驻波换算：VSWR↔|Γ|↔回损↔失配损耗（三入任一，全出）

| 参数 | 说明 | 必填 |
|---|---|---|
| `vswr` | float - 电压驻波比（>1；与回损/Γ 二选一） | 否 |
| `return_loss_db` | float dB 回损（正数） | 否 |
| `gamma_mag` | float - 反射系数模（0-1） | 否 |

## waveguide_lambda_g

矩形波导 TE10 传播参数抽键：λ0=c/f、λc=2a、fc=c/2a、λg=λ0/√(1−(fc/f)²)、β=2π/λg（rad/m 与 rad/mm）+ 相/群速因子 λg/λ0 与 λ0/λg；f≤fc 截止显式拒绝；内部复用本族 _frequency 单源（wg_iris_*/wg_resonant_window 同源，零公式复制）；slot_array 内嵌 λg（λ0/2a 同构形态）与 microstrip_lambda_g（准 TEM）分层不撞

| 参数 | 说明 | 必填 |
|---|---|---|
| `a_mm` | float mm 波导宽边（TE10 截止=c/2a；>0） | 是 |
| `f_ghz` | float GHz 工作频率（>TE10 截止，截止下显式拒绝） | 是 |
| `b_mm` | float mm 波导窄边（>0 且 ≤a_mm，可选——TE10 λg 与 b 无关，给出即校验标准口径 b≤a） | 否 |

## waveguide_tee_s_matrix

H 面/E 面波导三口结理想 S 矩阵：对称无耗互易星形结功率波闭式——H 面（并联）S_ii=−1/3、S_ij=+2/3；E 面（串联对偶）S_ii=+1/3、S_ij=−2/3；幺正+互易+镜像对称+E/H 对偶（S_E=−S_H）四约束钉死。侧臂均分 20lg(2/3)=−3.5218dB、支臂反射 1/3（回损 9.5424dB）=无耗互易三口不可全匹配的拓扑必然（匹配需非互易=环行器另域）。锚：KCL/KVL 方程组测试侧独立重解；对偶残差 ≤1e-15；−3.5218dB/9.5424dB 常数。理想口径不出尺寸综合

| 参数 | 说明 | 必填 |
|---|---|---|
| `tee_type` | str 三口结类型 ∈{h_plane,e_plane}（缺省 h_plane 并联星形结） | 否 |

## wg_iris_match

波导单膜片匹配：负载反射 Γ → 归一导纳 y_L 沿线变换（TE10 λg 口径）g_in=1 二次方程双分支闭式解——每支给位置 ℓ、所需膜片电纳 b_i 与开口尺寸反解（感性/容性分支并列，感性标工程优先）；ABCD 回代 |Γin| 构造级残差；|Γ|≥1 非物理显式拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `a_mm` | float mm 波导宽边（>0） | 是 |
| `b_mm` | float mm 波导窄边（0<b≤a） | 是 |
| `f_ghz` | float GHz 工作频率（>TE10 截止） | 是 |
| `gamma_mag` | float 负载反射幅度（0≤\|Γ\|<1；=0 已匹配如实报告） | 是 |
| `gamma_phase_deg` | float 度 负载反射相位（−180..180） | 是 |

## wg_iris_susceptance

波导感性/容性膜片电纳：TE10 矩形波导对称薄膜片（感性宽边开口/容性窄边开口）归一化电纳闭式 B/Y0——感性 −(λg/a)cot²(πd/2a)、容性 (4b/λ0)ln csc(πd/2b)（薄膜片工程近似档，λg/λ0 依赖差异如实照录）；正反解双向（d_mm→电纳 / 电纳→d_mm 恰给其一）；f≤TE10 截止显式拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `a_mm` | float mm 波导宽边（TE10 截止= c/2a；>0） | 是 |
| `b_mm` | float mm 波导窄边（0<b≤a） | 是 |
| `f_ghz` | float GHz 工作频率（>TE10 截止） | 是 |
| `iris_type` | str 膜片类型 inductive\|capacitive（缺省 inductive） | 否 |
| `d_mm` | float mm 膜片开口（正解方向，与 b_norm 恰给其一） | 否 |
| `b_norm` | float B/Y0 归一化电纳（反解方向，与 d_mm 恰给其一；感性<0/容性>0） | 否 |

## wg_resonant_window

波导谐振窗设计：感性+容性薄膜片组合谐振窗（总电纳=0，f0 全传输——真空密封窗/波导滤波器谐振元），给定感性开口 d_ind 反解容性开口 d_cap，或双开口给齐验证残余电纳；指数下溢（感性开口过小容性解不可达）显式拒绝；f0 回代 |B总|≈0 构造级残差

| 参数 | 说明 | 必填 |
|---|---|---|
| `a_mm` | float mm 波导宽边（>0） | 是 |
| `b_mm` | float mm 波导窄边（0<b≤a） | 是 |
| `f_ghz` | float GHz 谐振频率（>TE10 截止） | 是 |
| `d_ind_mm` | float mm 感性膜片开口（0<d<a） | 是 |
| `d_cap_mm` | float mm 容性膜片开口（给齐=验证档；缺省=反解档） | 否 |

## wire_media_plasma

线媒质等离子：MM-7 Pendry 1996 线媒质等离子频率（PRL 76:4773）：ωp²=2π·c0²/(a²·ln(a/r))，a=晶格常数、r=线半径（a/r≥2 才入稀疏口径域）；附 Drude ε(ω)=1−ωp²/(ω(ω+jν))（e^{-jωt}：ν>0 → Im ε>0 无损正性、ν=0 ω<ωp → Re ε<0、ω=ωp 精确零点）。freq_ghz 给出时附 ε 报告。锚量级：a=1mm、r=1µm → f_p≈45.5 GHz（比金属光学等离子（~1e15 Hz）低 ~4 个量级——extremely low frequency 量化锚）

| 参数 | 说明 | 必填 |
|---|---|---|
| `lattice_mm` | float 晶格常数 a（mm，>0） | 是 |
| `wire_radius_mm` | float 线半径 r（mm，0<r<a 且 a/r≥2） | 是 |
| `freq_ghz` | float 可选工作频率 GHz（>0；给出时附 Drude ε 报告） | 否 |
| `nu_rad_s` | float 碰撞频率 ν（rad/s，≥0，默认 0=无损） | 否 |

## yagi_gain_nbs_tn688

Yagi 增益阶梯（NBS TN688）：boom 总长 λ∈[0.4,4.2] → 增益 dBd/dBi（六档实测锚 7.1/9.2/10.2/12.3/13.4/14.2 dBd 线性插值，插值档如实标注非实测点；dBd 相对半波偶极，dBi=+2.15 恒等）；附最近标准档类与NBS 400MHz 建模测量口径注记——经验面非闭式

| 参数 | 说明 | 必填 |
|---|---|---|
| `boom_length_lambda` | float λ boom 总长（0.4≤L≤4.2，端点恰值=实测档；域外拒绝不外推） | 是 |
| `output` | str 输出选择（"dbd"/"dbi"/"both"，缺省 "both"双输出；单选时另一口径返 null） | 否 |

## yagi_geometry_nbs_tn688

Yagi 档位几何（NBS TN688）：六档（0.4/0.8/1.2/2.2/3.2/4.2λ）封闭枚举 → 单元数（3/5/6/12/17/15）/反射器间距 0.2λ/已文本验证的指向元间距（0.8λ 档 0.2λ、4.2λ 档 0.308λ，其余 null 如实注记禁编造）+0.8λ 档例题长度（未补偿 0.485/0.442+修正单点 0.490/0.447）+f_ghz 米制缩放位置（有源元原点/反射器 −0.2λ/指向元等距）

| 参数 | 说明 | 必填 |
|---|---|---|
| `class_lambda` | float λ 标准档（0.4/0.8/1.2/2.2/3.2/4.2 六档封闭枚举，其他值显式拒绝） | 是 |
| `f_ghz` | float GHz 工作频率（>0，几何米制缩放用） | 是 |
| `element_d_lambda` | float d/λ 阵元直径比（>0，缺省 0.0085=TN688 基准 0.25in@400MHz；合理域 0.001..0.05 越域注记不拒绝） | 否 |
