# 计算器注册表参考

> `CALCULATOR_REGISTRY` 实注册 **100** 个（含实验键共 **101** 个；实验键默认不列、需显式开关）。与 `scripts/check_numbers.py` 的 `count_calculators()`/`count_calculators_all()` 构建时逐位互证。运行入口 `rfauto calc list` / `rfauto calc run <名> -p k=v`。本页由 `scripts/build_docs_pages.py` 机读生成，勿手改。

数值只在确定性内核（LLM/agent 永不产生物理数字）；每键的输入表由 `tests/unit/test_physics_invariants.py` 物理不变量门逐键消费。

## allan_deviation

MS-5 Allan 偏差（时钟稳定度，IEEE 1139/952 口径）：分数频率 y 序列（kind='freq'）或相位时间误差 x 序列秒（kind='phase'，y=Δx/τ0）→ 重叠（缺省）/非重叠 Allan 偏差序列 {tau_s, adev, adev_error, n_terms}（tau 缺省倍频程网格；越界 tau 裁剪）。label=全段 log-log 斜率按 IEEE 1139 Table 1 分类（pm/white_fm/flicker_fm/random_walk_fm/linear_drift/unknown；白相与闪相同斜率 −1 不可分辨，分辨走 core classify_joint 用 MDEV −3/2 vs −1，或频域 S_phi 斜率走 clock_noise 互检）。斜率分类是全段摘要启发式（≥2 个正 ADEV 点才给出，否则 'insufficient'）；误差棒=独立差分近似 EDF（Greenhall-Howe 修正未实现，UNVERIFIED，只作量级参考）。短序列/非有限值/非等间隔时间戳显式拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `samples` | list[float] 分数频率偏差 y_k 或相位时间误差 x_k（秒）序列（≥3 点等间隔） | 是 |
| `rate_hz` | float Hz 采样率（>0，τ0=1/rate_hz） | 是 |
| `kind` | str 'freq'\|'phase'（默认 'freq'） | 否 |
| `estimator` | str 'overlapping'\|'nonoverlap'（默认 'overlapping'） | 否 |
| `taus` | list[float] 可选取样时间数组秒（全正；缺省倍频程网格） | 否 |

## array.bayliss_weights

RB-ALG-1 Bayliss 差波束权向量（单脉冲低副瓣差方向图四参数闭式；Bayliss 1968 BSTJ 47(4):623-650 原文数表，Doerry SAND-2025-07335 转载双源锚定）。2N 元偶数阵奇对称实权，PSLL 回收=声明电平；文献值回收/恒等式门见 test_w3_e_array_synth

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_elements` | int 单元数（偶数，≥8；差波束奇对称 2N 元阵） | 是 |
| `sidelobe_level_db` | float 副瓣电平声明值 dB（负值，相对差主瓣峰） | 是 |
| `nbar` | int 等纹波零点对数（缺省 0=自动 min(7, N/2)；须 4 至 N/2） | 否 |

## array.quantized_milp

RB-ALG-2 量化约束阵列综合=MIP 精确解（scipy.milp/HiGHS，零新依赖）。移相器 b-bit/衰减器离散档/阵元开关 二进制选择+方向图约束线性化；目标=线性化峰值副瓣场，主瓣相干增益损失带内；回代 PSLL=真非线性口径；码字直连 firmware beam_codeword_table/beam_backsub_audit。不可行如实 ok=False（spec §7.4 风险③）

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

RB-ALG-1 Schelkunoff 单位圆零点置放权向量（Schelkunoff 1943 BSTJ 22:80-107）。给 n-1 个零方向（方向余弦）得阵列多项式系数=激励；全自然零点=均匀阵恒等式钉见 test_w3_e_array_synth

| 参数 | 说明 | 必填 |
|---|---|---|
| `n_elements` | int 单元数（≥2；零方向数须=n-1） | 是 |
| `null_positions` | array 零方向方向余弦序列（任意实数，按 2π wrap） | 是 |
| `spacing_lambda` | float 单元间距 d/lambda（缺省 0.5） | 否 |

## array.villeneuve_weights

RB-ALG-1 Villeneuve 和波束权向量（Taylor 零点的离散阵精确修正；Villeneuve 1984 IEEE TAP 32(10):1089-1093）。nbar=1 退化为均匀阵；PSLL 收敛带与单调钉见 test_w3_e_array_synth

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

AP-7 可用性↔衰落裕量双向换算+双模型同参差异带（平均最差月）：Vigants-Barnett 简式（Barnett 1972 BSTJ 51(2) §6.3 一手核，P=c·(f/4)·1e-5·D_mi³·10^(−F/10)，climate 四档 4/1/0.5(UNVERIFIED)/0.25）vs ITU-R P.530-18 正式式（§2.3.1 式(7) 文本层逐位核，K·d^3.51·(f²+13)^0.447·10^(几何/气象指数−A/10)）。availability_percent 与 fade_margin_db 二选一；diff_band 如实记录两式差异（不设对错门）；P.530 侧 log10_k 缺省 −2.0 为典型温带占位 UNVERIFIED（LogK.csv 网格零捆绑）

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

## blocking_budget

MT-4 件 3 阻塞/信道选择性预算（round17 MT-4，杂散面复用 core/cascade.spur_search，链路基线复用 cascade_budget——既有语义零改动）。三面：①倒易混频 N_rm=P_blk@mixer+L(f_offset)+10log10(B) → desense=10log10(1+10^((N_rm−N_floor)/10))（等效 NF 抬升=灵敏度恶化）；②线性度 p1db_margin=链路输入 P1dB−阻塞电平（无 p1db 级→None 不判）；③阻塞×本振 |m·f_blk±n·f_LO| 落带杂散（fundamental 不计；hazard='high' 落带判负）。pass=三面合取；L(f_offset) 为标量（裙边分段积分不在此层，可走 clock_noise 幂律谱合成取值）；filter_rejection_db=阻塞偏移处前端聚总选择性

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

Dishal 顺序调谐确定性 critique（与 autotune_service.critique_point 同型 issues+typed fixes，无 LLM，数值只在内核 #7）：τ(f) 峰数=指纹（1 峰=单腔接入步→Qe；2 峰=相邻耦合步→k 拆分精确式 k=(f₂²−f₁²)/(f₂²+f₁²)）；峰位偏=失谐方向。C 系数钉死（合成回收裁决，模块头注释）：S21 透射泄漏 C=2、S11 反射全通 C=4。k 计算注入点：df6 P1 k_split_pair 注册后由服务层经 k_split_fn 消费，计算器面保持内部精确式（显式拒绝外部回调串入）

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

矩形腔 TE101 腔体微扰频移（Pozar §6.7 / Slater 定理一阶）：腔尺寸+样品（轴对齐盒精确解析，或任意三角网格体素积分）→ f0、Δf/f0。小样品极限：E 极大点介质 −2(εr−1)Vs/Vc、金属 −2Vs/Vc（下调）；H 极大区金属符号翻正

| 参数 | 说明 | 必填 |
|---|---|---|
| `a_mm` | float mm 腔 x 边长（>0） | 是 |
| `b_mm` | float mm 腔 y 高（>0，进 Vc 与场权积分） | 是 |
| `d_mm` | float mm 腔 z 长（>0） | 是 |
| `sample_box_mm` | array [x0,y0,z0,x1,y1,z1] 轴对齐样品盒（mm，腔内） | 否 |
| `sample_triangles_mm` | array (n,3,3) 样品水密三角网格（mm，体素路线） | 否 |
| `sample_eps_r` | float - 样品相对介电常数（>1；缺省=金属微扰路线） | 否 |
| `voxel_mm` | float mm 体素步长上限（网格路线；缺省自动=样品最大边/24） | 否 |

## chebyshev_prototype

广义切比雪夫原型（chebyshev_g 等价形式）：阶数+回损+传输零点 → F/P/E 多项式系数与反射零点（Cameron 口径，S11=F/E, S21=P/(εE)）

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

chipless RFID 码字→谐振器组规划（等 Q 假设深谷）：code 槽位 0/1 →各谐振器频率（槽中心）/R=x/Q/预期谷深 20lg(2R/(2R+Z0))/无耗近似带宽 f·Z0/(2x)（Matthaei 电抗斜率口径，core/chipless_rfid.py）

| 参数 | 说明 | 必填 |
|---|---|---|
| `code` | list[int] 码字（每槽 0/1，长度=n_slots） | 是 |
| `f_start_hz` | float Hz 扫描带下缘 | 是 |
| `f_stop_hz` | float Hz 扫描带上缘（>f_start） | 是 |
| `q_unloaded` | float - 谐振器无载 Q（统一等 Q，>1） | 是 |
| `slope_ohm` | float Ω 电抗斜率参数 x=ω0·L（统一） | 是 |
| `z0_ohm` | float Ω 读出线特性阻抗（默认 50） | 否 |

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

MT-1 相关级联噪声系数（round17 MT-1，Hillbrand-Russer 链式噪声相关矩阵在匹配 z0 功率波域的显式式）：级表（gain_db/nf_db，信号流向）+ 级间加性噪声相关系数 → F_tot/NF + Friis 独立假设对照 + delta_nf_db（相关−独立差，核心产出）+ 等效噪声温度 + 逐级/逐对贡献分解。公式 F_tot = 1 + Σ(Fᵢ−1)/G_pre,ᵢ + 2Σ Re(ρᵢⱼ)√((Fᵢ−1)(Fⱼ−1)/(G_pre,ᵢ·G_pre,ⱼ))；ρ 全 0 逐位退化 Friis（与 core/cascade 对拍钉），ρ=±1 两极限有闭式锚，ρ 集合过 PSD 实测守卫（逐对 |ρ|≤1 不保证集合合法——三对不一致组合显式拒绝）⇒ F_tot≥1 解析保证。相噪相关性语义：共享 LO 双通道 ρ=+1、独立本振 ρ=0。失配/多端口广义 ABCD 噪声矩阵不在本域（诚实边界，见 core/noise_correlation.py 模块头）

| 参数 | 说明 | 必填 |
|---|---|---|
| `stages` | list[dict] 级表 [{gain_db: float dB, nf_db: float dB}, …]（信号流向；多余键忽略） | 是 |
| `rhos` | list[dict] 可选级间相关系数 [{i: int, j: int, rho: float\|[re, im]}, …]（0≤i<j<n；缺省全独立=Friis） | 否 |
| `t0_k` | float 参考温度 K（>0，默认 290） | 否 |

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

C13 显式 TZ 集合综合（Cameron N+2）：完整 TZ 列表（每个 Ω 单独列出；±Ω 成对=实系数原型，与 coupling_matrix_synthesize_n2 同口径；非成对=复系数原型，响应 Ω→−Ω 不对称）→ (N+2)×(N+2) 横向矩阵，频响与原型逐点一致（幅度；复系数路径实测 ≤1.3e−13）。复元矩阵为复对称 M=Mᵀ，非对称网络 |m_0k| 与 |m_kL| 允许不等

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

MM-4 CRLH（复合左/右手传输线）单元点分析（round17 §五 :146，Caloz & Itoh Wiley 2006 §3.1 口径）：T 型单元（串 L_R+C_L / 并 C_R+L_L）在单频点的谐振对 f_se=1/(2π√(L_R C_L))、f_sh=1/(2π√(L_L C_R))、ZOR（规格口径 1/√(L_L C_R)，短路边界 N=0 模；开路边径=ω_se 另提供）、平衡判定（δ=2(f_se−f_sh)/(f_se+f_sh)，平衡=0 阻带闭合）、频段归类（left_hand/right_hand/stopband；平衡单元 f_se=f_sh 为 transition 无缝过渡点）、复 Bloch 色散 β(ω)（左手频段 β<0 相位超前/右手 β>0/非平衡阻带 β 纯虚 Im≤0，深阻带 Bloch 相位 ±π/d）、CRLH 阻抗 Z_CRLH=√(Z/Y)（平衡时 ≡√(L_R/C_R) 与频率无关；ω→ω_sh 阻带高阻/开路极限）、衰减（Np/m 与 dB/单元）与漏波角 θ=arcsin(Re β/k0)（|Re β|≥k0 或阻带 → None 不辐射不外推）

| 参数 | 说明 | 必填 |
|---|---|---|
| `l_r_nh` | float 右手串联电感 L_R nH（>0） | 是 |
| `c_l_pf` | float 左手串联电容 C_L pF（>0） | 是 |
| `l_l_nh` | float 左手并联电感 L_L nH（>0） | 是 |
| `c_r_pf` | float 右手并联电容 C_R pF（>0） | 是 |
| `f_ghz` | float 分析频率 GHz（>0） | 是 |
| `cell_len_mm` | float 单元周期 d mm（>0；缺省 1.0） | 否 |
| `balance_rtol` | float 平衡判定相对容差（缺省 1e-6） | 否 |

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

AP-7 小尺度/阴影衰落中断概率 [%]（P(接收功率 < 中值−margin_db)，功率门限相对平均功率归一）：kind='rice' 走非中心 χ² CDF（≡1−Marcum-Q1，scipy.special.chndtr 等价路径，K 线性值，K→0 退化为 Rayleigh 实测 3e-17）；'rayleigh' 闭式 1−exp(−h)；'nakagami' 走正则化不完全 Gamma P(m,mh)（m≥0.5，m=1≡Rayleigh）；'lognormal' 对数正态阴影 0.5·erfc(M/(σ√2))（M=σ 时 15.87% 锚）

| 参数 | 说明 | 必填 |
|---|---|---|
| `margin_db` | float dB 衰落裕量（≥0，相对中值/平均功率） | 是 |
| `kind` | str 'rice'/'rayleigh'/'nakagami'/'lognormal'（默认 'rice'） | 否 |
| `k` | float Rice K 因子线性值（≥0，默认 10.0≈10dB；仅 rice 用） | 否 |
| `m` | float Nakagami-m（≥0.5，默认 1.0；仅 nakagami 用） | 否 |
| `sigma_db` | float 对数正态阴影标准差 dB（>0，默认 8.0；仅 lognormal 用） | 否 |

## form_beta_linear

XD-11 FORM 一阶可靠度·线性极限状态面便捷键：g(x)=offset−Σcoeff_i·x_i<0 失效（Hasofer-Lind 1974 β 几何定义 / Rackwitz-Fiessler 1978 HL-RF 迭代；OpenTURNS FORM 例题族方法学参照）。线性面 HL-RF 一步到解且与闭式 β=(offset−aᵀμ)/||a·σ|| 逐位一致（双路径互证字段 beta_closed_form）；Pf=Φ(−β)；α=a·σ/||a·σ||=失效方向单位灵敏度（|α_i| 大=第 i 个参数的公差/σ 把 Pf 拖得最狠）。stddev 逐元素>0；均值点已入失效域（β<0）如实返回 Pf>0.5 不翻符号。非线性面走 core.form_reliability.form_beta（黑盒 callable）直调

| 参数 | 说明 | 必填 |
|---|---|---|
| `coeffs` | list[float] 线性系数 a（g=offset−a·x；非全零） | 是 |
| `offset` | float 截距 offset=g(0)（安全裕度项，>0=均值点安全） | 是 |
| `mean` | list[float] 各变量均值 μ（与 coeffs 等长） | 是 |
| `stddev` | list[float] 各变量标准差 σ（逐元素>0） | 是 |

## gstc_forward

MM-3 GSTC 正向（规格 §C-2，arXiv 1408.0273v2=IEEE TAP 63(7) 2015 Eq.(17)/(18) 逐式）：法向入射单轴 Huygens 面 χ_ee/χ_mm（米；实数或 [re,im] 对）→ 共极化 T/R（[re,im]）+ 能量 |R|²+|T|²、dB/相位与 2×2 S 面（互易）。无源守卫 |R|²+|T|²≤1+1e-9 违即显式报错（本式口径无耗=χ 实数、Im χ>0=增益非物理）；χ_em/χ_me 交叉耦合闭式原文未给显式不做（参数位保留，传非 None 拒绝）；x/y 极化法向入射简并同结果。

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

MM-3 GSTC 逆解（规格 §C-2，arXiv 1408.0273v2 Eq.(19) 逐式）：目标共极化 (T,R)（[re,im]）→ 面极化率 χ_ee/χ_mm 反演 + Eq.(19)↔Eq.(17) 往返自检（逐位 ≤1e-12，违即 RuntimeError 显式失败——代数上应精确恒等）。|T±R+1|→0 的 χ→∞ 极点域（如 T=−1 全反 Huygens 极限）显式拒绝不外推；正向无源守卫不套用于本键（实测目标可轻微超物理，χ 可实现性归调用方判读）。

| 参数 | 说明 | 必填 |
|---|---|---|
| `t` | float\|[re,im] 目标透射系数 T（复数） | 是 |
| `r` | float\|[re,im] 目标反射系数 R（复数） | 是 |
| `freq_ghz` | float 频率 GHz（>0；k=2πf/c₀ 真空口径） | 是 |

## gt_ratio

LT-1 G/T 组合优值（ITU-R S.733-2 定义口径）：G/T = G_dB − 10·log10(T_sys) [dB/K]。T_sys 三路径显式择一：t_sys_k 直接给定 / nf_db（=cascade_budget.nf_total_db 直连，Te=T0·(F−1)）/ t_e_k（=nf_measurement y-factor 链等效输入噪声温度）；t_ant_k 并入系统温度，三者全缺省时退化为 antenna_only（T_sys=t_ant_k，如实标注）。t_sys_k/nf_db/t_e_k 同给按优先级取用并如实报告冗余

| 参数 | 说明 | 必填 |
|---|---|---|
| `gain_db` | float dB 接收链指向源方向总增益（cascade_budget.gain_total_db 同名直连） | 是 |
| `t_sys_k` | float K 系统噪声温度直接给定（可选，优先级最高） | 否 |
| `nf_db` | float dB 系统总噪声系数（可选；→ Te=T0·(F−1)） | 否 |
| `t_e_k` | float K 接收机等效输入噪声温度（可选，nf_measurement te_from_y 链输出） | 否 |
| `t_ant_k` | float K 天线噪声温度（默认 290） | 否 |
| `t0_k` | float K NF→Te 换算基准（默认 290，IEEE 口径） | 否 |

## hata_cost231

AP-5 Hata/COST-231 经验中值路损（Rappaport §4.10 承载，统一域盒 150–2000MHz）：150–1500MHz 走 Okumura-Hata 原式，1500–2000MHz 走 COST-231 Hata 扩展（urban=metropolitan C=3dB）；env=suburban/open 走 Hata 修正式（COST 段外推档如实标注）。域盒 f∈[150,2000]MHz/d∈[1,20]km/h_b∈[30,200]m/h_m∈[1,10]m，域外显式 ValueError

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_mhz` | float MHz 频率（域盒 [150,2000]） | 是 |
| `d_km` | float km 收发距离（域盒 [1,20]） | 是 |
| `h_b_m` | float m 基站天线有效高度（域盒 [30,200]） | 是 |
| `h_m_m` | float m 移动台天线高度（域盒 [1,10]） | 是 |
| `env` | str 'urban'/'suburban'/'open'（默认 'urban'） | 否 |

## homog_mix_eff

MM-7 三混合式统一面（规格 §五 :154，通用 core 内核）：rule ∈ maxwell_garnett（Garnett 1904 球夹杂稀疏极限，depol 因子 L 椭球广义）/bruggeman（Bruggeman 1935 对称有效介质，要求 L∈(0,1]）/looyenga（Looyenga 1965 立方根加权）——复数 ε 全程（e^{-jωt} 口径 Im≥0 无源）。depol 形状族：球=1/3、沿场细棒=0（仅 MG，退化为 Wiener 上界并联）、法向薄片=1（MG 退化为 Wiener 下界串联）。附 Wiener 双界（算术/调和）；实数输入报告界内判读、复数输入界不有序 如实 None。L=1/3 实数输入与 humidity_drift 球形闭式逐式一致

| 参数 | 说明 | 必填 |
|---|---|---|
| `rule` | str 'maxwell_garnett'\|'bruggeman'\|'looyenga' | 是 |
| `er_matrix` | float\|[re,im] 基质 ε_m（Re>0，Im≥0） | 是 |
| `er_inclusion` | float\|[re,im] 夹杂 ε_i（Re>0，Im≥0） | 是 |
| `v_inclusion` | float 夹杂体积分数 ∈[0,1]（端点恒等直返） | 是 |
| `depol` | float depolarization 因子 L ∈[0,1]（默认 1/3=球形） | 否 |

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

## ipc2152_trace_temp_rise

IPC-2152 走线载流温升：线宽/铜厚/电流 → ΔT（Brooks & Adam 拟合 ΔT=K·I^a·W^b·Th^c，W/Th 以 mil 计；系数取自 KiCad 独立实现）。IPC-2152 结论：内层不按 IPC-2221 的老规矩 ×2 降额

| 参数 | 说明 | 必填 |
|---|---|---|
| `width_mm` | float mm 走线宽度（>0） | 是 |
| `copper_oz` | float oz/ft² 铜厚（1 oz ≈ 1.378 mil） | 是 |
| `current_a` | float A 走线电流（DC/RMS，≥0） | 是 |
| `internal` | bool 是否内层（默认 False） | 否 |

## iq_imbalance_irr

MT-4 件 1 IQ 失衡 → 镜像抑制比 + EVM 贡献（round17 MT-4，Razavi 式 IRR=(1+ε²+2εcosφ)/(1+ε²−2εcosφ)，ε=Q/I 增益比线性、φ=正交相位误差；ε=1 退化 cot²(φ/2)）+ 3GPP TS 38.141-1 EVM 消费口径折算（evm_rms²=镜像/信号功率=1/IRR；IRR 本身不设 3GPP 限值门——限值面out-of-scope 如实注明）。完全平衡（0 dB+0°）→ irr_db=None（∞ 的 JSON 契约面）、evm=0；完全反相（0 dB+±180°）→ 信号支路零输出、EVM 无界走 None+full_image 旗标。|φ|>180° 显式拒绝

| 参数 | 说明 | 必填 |
|---|---|---|
| `amp_imbalance_db` | float I/Q 增益失衡 dB（ε=10^(a/20)；同值异号 IRR 相同） | 是 |
| `phase_imbalance_deg` | float 正交相位误差 deg（\|φ\|≤180；符号=旋转方向，IRR 同值） | 是 |

## k_split_pair

双峰模分裂耦合系数（Hong & Lancaster 精确式 k=(f2²−f1²)/(f2²+f1²)，df6 A1 R4）：|S21| dB 双主峰抛物线细化+KSPLIT_RULE 峰检（prominence 0.5dB HFSS 锚同款+通带邻域守卫）；偏置曲线 log-log 逆映射修正；双峰不可分如实 None（#122）

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

AP-5 刃形绕射损耗（ITU-R P.526-15 §4，Fresnel-Kirchhoff 参数 v）：method='exact' 走 Fresnel 积分精确值（J(0)=6.02dB 擦顶锚）；'approx' 走 P.526 闭式 6.9+20log10(√((v−0.1)²+1)+v−0.1)（v≤−0.78 记 0）；'lee' 走 Rappaport §4.11 分段式（v>2.4 档 20log(v/0.225)）。返回恒含三档数值供互检（exact vs approx 最大偏差 ~0.12dB@−0.7..6）

| 参数 | 说明 | 必填 |
|---|---|---|
| `v` | float Fresnel-Kirchhoff 绕射参数（无量纲；>0=障碍遮挡视线） | 是 |
| `method` | str 'exact'/'approx'/'lee'（默认 'exact'） | 否 |

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

发射遮罩→切比雪夫滤波器最小阶（经典 acosh 闭式，多段逐段取最大）：N=ceil(acosh(√((10^(A/10)−1)·K))/acosh(Ωs))，K=10^(RL/10)−1；Ωs 为段约束点（内缘裁剪到通带边缘+guard_offset_ghz 调制滚降信用区）经几何映射 Ω=(f/f0−f0/f)/fbw 的归一化频（fbw=u(2+u)/(1+u) 精确反解，使 Ω(±通道半宽)=±1）。返回阶数/回损分配/带内纹波/逐段 Ω 与需求明细；贴边段要求超过纹波电平如实报错（全极点在 Ω=1 只能提供纹波衰减）

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

LT-7 烘干/烧结工艺窗口+热失控（round18 :142）：Foster (R,τ) 阶跃热响应（复用 thermal_transient.step_response_zth，MP-1 零改动）→ 目标温度功率/时间窗（保持功率 ΔT/ΣR、工艺时刻所需功率 ΔT/Z_th(t)、给定功率到达时间二分反解、稳态越限旗标）；可选失控块（全给或全不给）：tanδ(T)=tanδ_ref·e^{α(T−T_ref)} 体吸收链 P(T)→定点迭代（方法论同 thermal_iteration）+稳定性斜率 R_th·dP/dT 临界+解析失控界 α_crit=1/(e·R_th·P0)（收敛/失控分界由锚树复现）。体吸收为 rms 场口径

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

NX-10 MIMO 信道容量/分集（round14 :108，C=log₂det(I+γHH†) 与分集增益）：Telatar 1999 容量 + Tse-Viswanath 2005 两档功率口径——等功率（总 snr 均分 Nt：Σlog₂(1+snr·λᵢ/Nt)）与注水（pᵢ=(μ−1/λᵢ)⁺、Σpᵢ=snr，活性模闭式搜索）；规格原式 log₂det(I+snr·HH†)（γ=单流 SNR 口径）由 slogdet 独立路径并行输出（与等功率档差 Nt 倍口径，恒等式由锚树钉）。分集面：rank(HH†) + 有效分集阶 N_eff=(Σλ)²/Σλ²（participation-ratio 有效秩；天线级 DG=10lg(1−ECC) 近似归 ecc_metrics 既有语义不重复）。S 参→H 提取面归 ecc_metrics（本键只接收已构成的 H）。

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

## multimode_cavity_heating

LT-5 多模腔模式统计+装填因子（round18 :137）：Weyl 渐近 N=8πV(f√εr/c0)³/3（双极化，Metaxas & Meredith Ch.5 口径）+ 矩形腔精确枚举交叉对拍（复用 shield_cavity_mode.rect_cavity_modes，TE 容许集+TM 子集分开计）+ 模式密度/平均模间距；可选负载块（全给或全不给）：均匀场装填因子 F=εr′V_l/(εr′V_l+V_c−V_l)、Q_d=1/(F·tanδ)、效率 η=Q_L/Q_d 与负载吸收功率（匹配源口径）；1kW 水负载经典量级锚见锚树

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

MP-3 multipactor 微放电击穿阈值（round15 :84，Vaughan 二次发射+20-gap 串接+N 载波等效功率语境）：施加峰值电压对平行板一阶渡越敏感带 × SEY crossover 窗口的合成裕量报告。每序 n=1..order_max 的封闭周期轨道带 V∈[K/√(4+(2n−1)²π²), K/2]（K=4π²(m_e/e)(f·d)² 相似标度）经碰撞能量 窗口 E_imp∈(E1,E2) 门控（δ>1 判据，Kishek & Lau PAC97 口径）后给可持续带；落带内判模型敏感。SEY 窗口 e1_ev/e2_ev 可显式给出（VERIFIED）或缺省由 Vaughan 普适曲线 δ=δmax·(v·e^{1−v})^{k_s} 派生（曲线形状 UNVERIFIED，判定只消费 crossover）。载波表 carrier_powers_w 支持 非相干 RSS（ECSS 口径 P_eq=ΣPi，缺省）与相干最坏相位（P_eq=(Σ√Pi)²）双口径。verdict 仅对一阶理想化模型自洽（零初速发射）；工程仲裁走 high_power 的 ECSS-E-ST-20-01C 实验包络 ecss_multipactor_fd（报告 notes 固定指向）。margin=阈值/施加（dB），≥required_margin_db 判过

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

## parallel_plate_breakdown_margin

平行板击穿场强裕量：E = V/d 对比材料击穿阈值表（空气 3 MV/m 等）；margin_ratio = E_bd/E，safety_factor 为要求的安全系数（E·sf ≤ E_bd 判过）

| 参数 | 说明 | 必填 |
|---|---|---|
| `voltage_v` | float V 施加直流/峰值电压（≥0） | 是 |
| `gap_mm` | float mm 极板间距（>0） | 是 |
| `material` | str 材料键（默认 air；可用见 _DIELECTRIC_STRENGTH_MV_PER_M） | 否 |
| `safety_factor` | float - 要求安全系数（默认 1.0） | 否 |

## patch_f0_symbolic_e13（实验）

符号回归归纳公式（实验态，默认关闭）：f0_ghz = 0.0261448 + 75.1834*1/L_mm + 0.0162789*L_mm/W_mm。E13（runs/symbolic_fit/patch_f0.json）：数据集 patch_antenna_openems_campaign，51 真实 openEMS 点（L∈[35,45]mm、W∈[40,60]mm、er=3.66、h=0.508），基模=[1.3,2.7]GHz 最低频 ≥3dB 局部谷；holdout 每 5 留 1，rmse_holdout=0.001773GHz、r2_train=0.999889；独立裁判 vs Hammerstad/HJ mean −0.699%、max|dev|=0.765%≤2% PASS

| 参数 | 说明 | 必填 |
|---|---|---|
| `l_mm` | float - 归纳变量 L_mm（适用域/出处见 description） | 是 |
| `w_mm` | float - 归纳变量 W_mm（适用域/出处见 description） | 是 |

## patch_length

矩形贴片谐振长度（Balanis 闭式含边缘修正）：f0+er+h → W/εeff/L

| 参数 | 说明 | 必填 |
|---|---|---|
| `f0_ghz` | float GHz 谐振频率 | 是 |
| `epsilon_r` | float - 基板相对介电常数 | 是 |
| `h_mm` | float mm 基板厚度 | 是 |

## phase_noise_evm

MT-4 件 2 相噪 → 积分 EVM（round17 MT-4；σ_φ²=2∫10^(L/10)df ADI MT-008 口径，积分复用 core/clock_noise.phase_jitter_from_l 不重复实现）→ EVM_rms=σ_φ（小角度平稳高斯口径，σ_φ>0.5 rad 打 small_angle_ok=False 不静默）+ evm_db/evm_percent + 可选 rms 抖动。f_edges=严格递增偏移频率边界 Hz；l_dbc 按 interp 取边界值（db_linear，长度=N）或段值（const，长度=N−1）；积分区间不外推。σ_φ=0 → evm_db=None（dB 域无定义，JSON 契约禁 −Inf）

| 参数 | 说明 | 必填 |
|---|---|---|
| `f_edges` | list[float] 偏移频率边界 Hz（严格递增，N≥2，全>0） | 是 |
| `l_dbc` | list[float] 单边带相噪 dBc/Hz（db_linear=边界值 N 个 / const=段值 N−1 个） | 是 |
| `interp` | str 'db_linear'\|'const'（默认 'db_linear'） | 否 |
| `f_carrier_hz` | float 可选载波 Hz（>0；给了才输出 jitter_s） | 否 |

## pll_loop_filter_synthesize

MT-5 三阶 PLL 环路滤波器综合（round17 MT-5，Banerjee SNAA106C T1/T2/T3→C1/C2/R2/C3 闭式+相位裕度迭代）：给定环路带宽 f_c（开环穿越）与相位裕度 PM → 峰值相位放置（dPM/dω|ωc=0，Gardner 二阶几何中值放置的三阶推广；极点比 r=T3/T1 为显式设计自由度，>1）反解 T1/T2/T3，总电容 A0 由 |G(jωc)|=1 闭式回代，元件值 C1=A0·T1/T2、C2=A0·(T2−T1)/T2、R2=T2/C2、C3·R3=T3。结果带回代复核（穿越/PM 残差入字段）+闭环 −3dB 带宽+|H(jωc)|=1/(2sin(PM/2)) 恒等值+C3 加载比（无源网络 T 形近似有效域自查：C3≪A0；有源拓扑 T 形精确）。可达 PM 窗随 r 收窄，窗外/PM∉(0°,90°)/r≤1 显式报错

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

单腔 Q 零点法（VF 极点+零点求和口径，免 q_e）：反射 S11 → VF 有理拟合 Γ=N/D（复极点对数从 1 起扫、取首个 fit_rms≤1e-2 的最小阶——更高阶会 出极点-零点双联伪对，和式翻倍）→ 带内衰减极点对 p 与频距最近的 Γ 零点对 z（Γ 自身零点，过耦时在右半平面，不判衰减性）→ Q_u=|Im p|/−(Re p+Re z)、f0=|Im p|/2π。正则单极点反射模型下 Re p=−ω0(1+β)/2Q_u、Re z=−ω0(1−β)/2Q_u ⟹ Re p+Re z=−ω0/Q_u 与 β 无关——无需 q_e 输入，与 q_factor_vf 极点法（需 q_e）互补；损耗判据仍在极点面：|Re p|/|Im p|>0.05 → loss_degraded（criteria §2）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | array GHz 频率轴（覆盖谐振 ±≥3 线宽；建议已去嵌参考面时延——残余时延进拟合误差） | 是 |
| `s11` | array 复 S11（[re,im] 对或复数） | 是 |
| `f0_hint_ghz` | float GHz 谐振频率提示（缺省=最弱阻尼极点对锚定） | 否 |
| `n_poles` | int VF 复极点对数扫描上限（默认 3；从 1 起取首个 rms≤1e-2 的最小阶，1..4） | 否 |

## qe_group_delay

单谐振器外部 Q 群时延法（Dishal/Hong 反射单端口径，df6 A1 R4）：τ(f)=A/(1+((f−f0)/w)²)+D 四参数 Lorentzian+基线拟合；无耗单端口 τmax=4Qe/ω0 ⇒ 缺省 c=4（合成回收 3.9972；/2 口径否决，DP-2 互证）

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

## resonator_thermal_drift

谐振温漂（§10.3 D14 一阶闭式）：Δf/f = −CTE·ΔT − ½·TCDk·ΔT。CTE=有效线膨胀系数、TCDk=(1/ε)dε/dT，单位 ppm/K

| 参数 | 说明 | 必填 |
|---|---|---|
| `f0_ghz` | float GHz 标称谐振频率（>0） | 是 |
| `delta_t_c` | float K 温度变化（可为负） | 是 |
| `cte_ppm_per_k` | float ppm/K 有效线膨胀系数（含封装） | 是 |
| `tcdk_ppm_per_k` | float ppm/K 介电常数温度系数 | 是 |

## retrieve_eff_params

MM-7 等效参数反演（Smith 2002 PRB 65:195104 同族口径）：单频 (S11,S21)（[re,im] 对）法向入射对称面板厚度 d → (ε,μ,n,Z)。时间 约定 e^{-jωt}（τ=e^{+jk0·nd}，无耗 Im(n)=0、有耗 Im(n)>0）。无源 守卫：能量 |S11|²+|S21|²≤1+1e-9、|τ|≤1+1e-9、Im(n)<0 显式拒绝；退化域（(1−S11)²−S21²=0、1−P·Γ=0、τ=0）显式拒绝。branch_m=相位 回绕支编号（相邻支差 2π/(k0·d) 恒等式可自检）；分支自动判据/Kramers-Kronig 因果核=MM-5 显式不做。slab_panel_rt=core 正向对偶面（合成回收对拍用，core 直调不注册）

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | float 频率 GHz（>0） | 是 |
| `s11` | float\|[re,im] 反射系数 S11 | 是 |
| `s21` | float\|[re,im] 透射系数 S21 | 是 |
| `thickness_mm` | float 面板厚度 d（mm，>0） | 是 |
| `branch_m` | int 折射率支编号（ℤ，默认 0=主枝；d<λ/2 时主枝） | 否 |

## rfid_backscatter_link

UHF RFID 反向背散射链路（标签→读写器，单站雷达方程 1/R⁴）：P_rx=EIRP·G_rx·λ²·σm/((4π)³d⁴)（Skolnik RCS 定义+Balanis 有效口径；Nikitin-Rao 2008 doi 10.1109/RFID.2008.4519368 链路预算框架），σm=(λ²G_tag²/4π)|Γ₁−Γ₂|²（Nikitin-Rao-Martinez 2007 Electron. Lett. 43(8):431，短路/开路态 |ΔΓ|=2 → σm=λ²G²/π）；给 tag_sensitivity_dbm 时合成读写距离=min(正向灵敏度门, 反向灵敏度门)

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

UHF RFID 正向链路（读写器→标签激活，Friis）：P_tag=EIRP·G_tag·(λ/4πd)²/L_pol（Friis 1946；Balanis §2 有效口径同式）；margin=P_tag−灵敏度；d_max=(λ/4π)·10^((EIRP+G_tag−L_pol−P_sens)/20)

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

AP-9 单跳卫星链路预算（JSON 进出，级表逐项风格）：C/N0 = EIRP − (FSPL+pointing+gas+rain) + G/T + 228.599（k=SI 精确值单源）。LEO 几何 elevation_deg∈(0,90]+alt_km>0 自算斜距 d=√((Re+h)²−(Re·cosE)²)−Re·sinE 与圆轨多普勒（rising/setting 反号；Re=6378km、GM=WGS-84 惯例），或 slant_km 直接给；G/T 单源复用 gt_link（t_sys_k/nf_db/t_e_k 三路径）。gas 项走 itu_atmosphere 降级面（P.676 表 UNVERIFIED→gas_db=0+注记，不产假数）；MODCOD 表 UNVERIFIED 档不做——margin 依据显式需求门 required_cn0_db_hz/required_cn_db/required_ebno_db，只出到 C/N0→C/N→margin。域守卫：仰角/高度/频率/损耗非负显式 ValueError

| 参数 | 说明 | 必填 |
|---|---|---|
| `link` | dict 链路描述（schema 见 core/sat_link.py sat_link_budget docstring：tx/path/rx 三段 + 可选 bw_hz/rb_bps/required_*） | 是 |

## shielding_effectiveness

屏蔽效能（Schelkunoff 平面波三段闭式）：SE=A+R+B——吸收 A=20lg|e^{γt}|=8.686·t/δ（γ=(1+j)/δ 良导体）；反射 R=20lg|(Z_w+Z_s)²/(4Z_w Z_s)|（Z_s=√(jωμ/σ) 表面阻抗、Z_w=η0=376.73Ω 平面波）；多次反射修正 B=20lg|1−Γ²e^{−2γt}|（Γ=(Z_s−Z_w)/(Z_s+Z_w)；厚屏蔽 e^{−2γt}→0 ⟹ B→0，薄屏蔽 t<δ 时 B<0 负贡献）。屏蔽体=有耗传输线段（Schelkunoff 1934 TL 类比；Ott 2009 §6），恒等式 SE_total≡−20lg|S21_ABCD| 由单测钉住；近场源（电/磁偶极）阻抗修正未实现，source 仅支持 plane_wave

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

LT-6 单模 applicator（round18 :140）：TE10p 矩形腔谐振频率+场量归一（∫|E|²=V/4、储能 W=ε0εrE0²V/8、壁损逐壁闭式→Q_c）+介质负载功率沉积链（微扰装填因子 F=4εr′V_l·s/εrV、1/Q_d=F·tanδ、耦合 β=Q_u/Q_e、谐振吸收 4β/(1+β)²、能量平衡→E0 与 P_load 双路恒等）；可选样品块（sample_box_mm+sample_eps_r）触发介质微扰失谐（复用 cavity_perturbation_shift，Pozar §6.7 口径）。峰值 phasor 口径（P=(ω/2)ε0εr″∫|E|²dV）

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

MM-7 Pendry 1999 SRR 阵列等效磁导率（IEEE TMTT 47(11):2075 Lorentz 形，arXiv 2006.13861 同式互证）：μ(ω)=1−F·ω²/(ω²−ω0²+iΓω)。F 填充因子与 f_mp（磁等离子频率）二选一入参（f_mp>f_res，F=1−(f_res/f_mp)²）。解析锚：μ(0)=1、μ(∞)=1−F、无损 μ(f_mp)=0、Re μ<0 带恰 =(f_res,f_mp)、Γ>0 全带 Im μ>0（无源性）。无损谐振点（分母零）与 非物理域显式拒绝。诚实边界：几何闭式 ω0(环尺寸) 原文常数需回 PDF 逐位核（#118），留 MM-11 极化率库——本键只收 Lorentz 参数化

| 参数 | 说明 | 必填 |
|---|---|---|
| `freq_ghz` | float 工作频率 GHz（>0） | 是 |
| `f_res_ghz` | float 环谐振频率 f_res=ω0/2π GHz（>0） | 是 |
| `fill_factor` | float 填充因子 F ∈(0,1)（与 f_mp_ghz 二选一） | 否 |
| `f_mp_ghz` | float 磁等离子频率 GHz（>f_res；与 fill_factor 二选一） | 否 |
| `gamma_ghz` | float 阻尼 Γ/2π GHz（≥0，默认 0=无损） | 否 |

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

T-match 输入阻抗（Balanis 3ed §9.7.3，(9-48)–(9-51)）：α=acosh((v²−u²+1)/2v)/acosh((v²+u²−1)/2uv)（u=a/a', v=s/a'）；Zt=jZ0·tan(kl'/2)、Z0=60·acosh((s²−a²−a'²)/(2aa'))；Zin=2Zt(1+α)²Za/(2Zt+(1+α)²Za)；l'≈λ/2 折合极限 Zin→(1+α)²Za（等半径 α=1→4Za）

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

## two_ray_loss

AP-5 双径干涉路损（平坦地面镜反射相干和，Rappaport 2nd ed §4.6）：LOS+镜反射 Fresnel 反射系数 Γ_v/Γ_h（σ=0 纯介电 eps_r）相干叠加，L=FSPL(d_los)−20log10|1+Γe^{jΔφ}|；附断点距离 d_break=4·h_tx·h_rx/λ、掠射角、Γ 元数据（d>>d_break 后包络 −40dB/dec 渐近）

| 参数 | 说明 | 必填 |
|---|---|---|
| `d_m` | float m 收发水平距离（>0） | 是 |
| `h_tx_m` | float m 发端天线高（>0） | 是 |
| `h_rx_m` | float m 收端天线高（>0） | 是 |
| `f_hz` | float Hz 载波频率（>0） | 是 |
| `eps_r` | float 地面相对介电常数（默认 15.0，中等湿地面；>1） | 否 |
| `pol` | str 极化 'v'/'h'（默认 'v'，选垂直/水平 Fresnel 系数） | 否 |

## vswr_convert

驻波换算：VSWR↔|Γ|↔回损↔失配损耗（三入任一，全出）

| 参数 | 说明 | 必填 |
|---|---|---|
| `vswr` | float - 电压驻波比（>1；与回损/Γ 二选一） | 否 |
| `return_loss_db` | float dB 回损（正数） | 否 |
| `gamma_mag` | float - 反射系数模（0-1） | 否 |

## wire_media_plasma

MM-7 Pendry 1996 线媒质等离子频率（PRL 76:4773）：ωp²=2π·c0²/(a²·ln(a/r))，a=晶格常数、r=线半径（a/r≥2 才入稀疏口径域）；附 Drude ε(ω)=1−ωp²/(ω(ω+jν))（e^{-jωt}：ν>0 → Im ε>0 无损正性、ν=0 ω<ωp → Re ε<0、ω=ωp 精确零点）。freq_ghz 给出时附 ε 报告。锚量级：a=1mm、r=1µm → f_p≈45.5 GHz（比金属光学等离子（~1e15 Hz）低 ~4 个量级——extremely low frequency 量化锚）

| 参数 | 说明 | 必填 |
|---|---|---|
| `lattice_mm` | float 晶格常数 a（mm，>0） | 是 |
| `wire_radius_mm` | float 线半径 r（mm，0<r<a 且 a/r≥2） | 是 |
| `freq_ghz` | float 可选工作频率 GHz（>0；给出时附 Drude ε 报告） | 否 |
| `nu_rad_s` | float 碰撞频率 ν（rad/s，≥0，默认 0=无损） | 否 |
