<!-- 站点副本：源=docs/reference/calculator-usage.md（手工同步；build_docs_pages.py 的 SYNC_DIRS 未收 docs/reference——aurora_l G3 落位批注，后续如收编请改生成器并撤此副本）。勿直接改本文件。 -->

# 计算器使用指南：按设计流程选键

> `rfauto calc` 的权威清单是 `rfauto calc list`（逐键参数自描述）与
> [计算器注册表参考](calculators.md)（机读生成，334 键全量：参数表/公式
> 出处/锚）。本页补另一面：微波设计流程走到某一步时该用哪个键、输入
> 怎么给、结果怎么判读、哪里容易用错。选键 48 个，覆盖 8 个环节；
> 没入选的键照常可用，入口在本页末尾「本页之外的域」。

## 本页读法

- 调用机制（CLI `-p k=v`、service 层 JSON、UI「微波工具箱」页 `#/tools`）
  见 [如何用 calc 计算器查闭式](../how-to/use-calculators.md)。
- **参数名不跨键统一**：相对介电常数在不同键里叫 `epsilon_r` 或 `er`，
  损耗正切叫 `tand` 或 `tan_delta`；T-match 两键用 SI 单位（Hz/m），其余
  主口径 mm/GHz/Ω/dB。跑之前先 `rfauto calc list` 核对该键参数名——
  参数自描述就是权威签名，报"未知参数"先查这里。
- 每键四行：什么时候用 / 典型输入 / 输出判读 / 常见误用。判读与误用
  大多来自键内守卫与锚（有效域、显式拒绝条件、文献锚值），照着核对
  能省一轮排查。

## 流程主线

一条微带链路的典型推进顺序，环节之间有先后依赖：

① 阻抗与传输线 → ② 匹配网络 → ③ 功分器/耦合器 → ④ 滤波器原型→综合
→ ⑤ 传输线不连续 → ⑥ 天线尺寸 → ⑦ 测量与校准 → ⑧ 链路预算

串起来的一个实例：`microstrip_synthesis` 定 50Ω 馈线宽 →
`unequal_split_wilkinson` 出两臂阻抗 → 对每条臂再跑
`microstrip_synthesis` 得线宽 → `microstrip_lambda_g` 得 λg 定臂长 →
`microstrip_bend_parasitics` 查直角弯寄生 → 投板前 `trl_standards_design`
设计 TRL 校准件 → 部件攒成链后 `cascade_budget` 过一遍预算。

## ① 阻抗与传输线正反解

先定叠层（εr、h 来自板材手册与 `configs/materials.yaml` 层叠库），再回答
两个方向的问题：给阻抗求几何（综合），给几何求阻抗（分析）。正反解
成对是这组的基本形态。

### `microstrip_synthesis` — 目标阻抗 → 线宽

- 什么时候用：拿到叠层后的第一步。50Ω 馈线、功分器臂、滤波器馈线
  都从这出宽度。
- 典型输入：`z0_ohm=50`、`freq_ghz=2.4`、`epsilon_r=3.66`、`h_mm=0.508`
  （rogers4350b 口径）。
- 输出判读：`width_mm`；brentq 求逆后自洽回代。拿结果喂
  `microstrip_analysis` 应还原 Z0。
- 常见误用：把 h 填成"介质+铜箔"总厚——h 是导带下介质厚度；板材 εr
  取工作频段值，宽频设计分段重算。

### `microstrip_analysis` — 线宽 → (Z0, εeff)

- 什么时候用：反解方向。已有版图量线宽，或给综合结果做独立复核
  （两条路径互差应 <1%，见 how-to 排错节）。
- 典型输入：`width_mm=1.112`、`freq_ghz=2.4`、`epsilon_r=3.66`、`h_mm=0.508`。
- 输出判读：Z0 与 εeff；εeff 进下游所有长度计算（λg、λ/4 段长）。
- 常见误用：只对 Z0 不看 εeff——长度错了比阻抗错了更常见。

### `microstrip_lambda_g` — λg 与色散

- 什么时候用：定 λ/4、λ/2 物理长度前必跑；Wilkinson 臂长、匹配段长
  全靠它。
- 典型输入：`width_mm`、`freq_ghz`、`epsilon_r`、`h_mm`；色散敏感加
  `dispersion=hammerstad-jensen`。
- 输出判读：εeff、λ0、λg。臂长取 λg/4；缺省档是准静态 εeff（不随频率变）。
- 常见误用：拿自由空间 λ0/4 当臂长——微带上要除 √εeff；mmWave 不开
  色散档长度会短几个百分点。

### `microstrip_attenuation` — 线损与线 Q

- 什么时候用：估插损预算（走线多长损多少）、看谐振器无载 Q 的构成。
- 典型输入：`width_mm`、`h_mm`、`epsilon_r`、`freq_ghz`、`tan_delta=0.0037`、
  `thickness_um=35`、`roughness_rms_um`。
- 输出判读：α（Np/m 与 dB/m）+ 线 Q=β/(2α)。分清导体项与介质项占比，
  谁主导决定换板材还是加宽线。
- 常见误用：`thickness_um` 缺省 0=零厚度无导体损耗——不给导体厚度，
  输出只有介质损耗；此键损耗正切叫 `tan_delta`，与综合键的 `tand` 不同名。

### `cpw_synthesis` — CPW 线宽

- 什么时候用：探针卡口径、要与地共面的布线；固定 gap 反解中心导带宽。
- 典型输入：`z0_ohm=50`、`gap_mm=0.1`、`freq_ghz`、`epsilon_r`、`h_mm`。
- 输出判读：中心导带宽。gap 先按工艺能力定，再解 w；两者一起动没有
  唯一解。
- 常见误用：背面有接地层（CPWG）却用本键——背面地拉近 Z0 变低，
  那种叠层走 `cpwg_synthesis`。

### `coax_line_z0` — 同轴正反解三路线

- 什么时候用：电缆/接头/腔体内导体；也给 TE11 高阶模截止（单模工作
  上限）。
- 典型输入：分析给 `a_mm`+`b_mm`；综合给 `z0_ohm` 加内或外半径恰一个；
  只给 `z0_ohm` 出直径比。
- 输出判读：Z0、单位长 L'/C'、TE11 截止频率。空气 50Ω 对应
  b/a=e^{5/6}（锚）。
- 常见误用：只按 Z0 选尺寸不看 TE11 截止——高阶模起跑后测量曲线上
  出现莫名谐振尖，先回这里查 fc。

### `waveguide_lambda_g` — 矩形波导 TE10 传播

- 什么时候用：波导段长、膜片间距、腔长换算的第一步；波导滤波器链
  （④）的入口之一。
- 典型输入：`a_mm=22.86`（WR-90）、`f_ghz=10`；`b_mm` 可选（只做 b≤a
  校验）。
- 输出判读：λc=2a、fc、λg=λ0/√(1−(fc/f)²)、β。f 离截止越近 λg 越发散。
- 常见误用：f≤fc 才显式拒绝，但贴截止的结果同样不可用——
  `bethe_hole_coupler` 就按距截止 <5% 拒绝，本键自留同量级裕量。

## ② 匹配网络

失配的两条路：窄带用集总/四分之一波长元件（L 节、λ/4 段、支节），
宽带用多节或锥形（`klopfenstein_taper` 等，见注册表「匹配·功分·衰减·
耦合」组）。所有匹配键都假设源/负载阻抗已知——阻抗从 ① 的正反解或
测量来。

### `l_section_match` — 两元件 L 节

- 什么时候用：最省元件的窄带匹配。先跑这个看 Q，Q 太高（带宽太窄）
  再升级 π/T 或多节。
- 典型输入：`z_source_ohm`、`z_load_ohm`、`f0_ghz`；`response` 选
  `low_pass`（串L并C）或 `high_pass`（串C并L）。
- 输出判读：Q=√(R大/R小−1) 决定带宽；输出带 Z_in(f0) 回代残差，应≈0。
- 常见误用：源/负载填反——串联元件在小电阻臂、并联元件跨大电阻侧，
  两半互换匹配就塌。

### `quarter_wave_transformer` — λ/4 阻抗变换

- 什么时候用：实阻抗对实阻抗的窄带匹配；也是功分器臂/耦合器馈线的
  理论原型。
- 典型输入：`z_source_ohm`、`z_load_ohm`；要物理长度给 `freq_ghz`+
  `eps_eff`。
- 输出判读：段阻抗 z0=√(Zs·Zl)；长度=λg/4，λg 用变换段自身的 εeff。
- 常见误用：`eps_eff` 填基板 εr——它是变换段那根线的有效介电常数，
  先用 `microstrip_analysis` 对 z0 那根线算出来。

### `stub_tuner_double` — 双支节调配

- 什么时候用：负载附近放不下 λ/4 段时的可调匹配；调腔体/天线耦合口
  常用。
- 典型输入：`rl_ohm`+`xl_ohm`（负载串联模型）、`z0_ohm=50`、
  `spacing_deg=45`（λ/8）。
- 输出判读：`solvable=False` 表示负载落在该间距禁区（g>csc²βd；λ/8 档
  g>2）——此时键面照常给边界数据，换间距再解。
- 常见误用：间距选 90°（βd=90° 是显式禁区）；负载在禁区先动
  `stub1_deg`（负载→首支节线长电长度）把工作点转出来，再解支节。

### `t_match_design` — T-match 折合馈电设计

- 什么时候用：粗振子/八木有源元的折合馈电——把天线阻抗升到目标
  实部附近，两只串联电容谐振掉剩余电抗。
- 典型输入：`freq_hz`、`main_radius_m`、`bar_radius_m`、`spacing_m`、
  `za_re_ohm`（无 T-match 的天线阻抗）、`target_rin_ohm=50`。
- 输出判读：T 棒长度+串联电容 C；步升上限=(1+α)²·Re(Za)，达不到目标
  显式报错。
- 常见误用：想往下降阻抗——T-match 只能升实部，300Ω 折合振子降到
  50Ω 走 ② 的其他键；本键族用 SI 单位（Hz/m）。

### `attenuator_t` — T 型电阻衰减器

- 什么时候用：定标衰减垫片。π 型（`attenuator_pi`）、桥 T
  （`attenuator_bridged_t`）同族三选一，看布线与阻值分布。
- 典型输入：`attenuation_db=3`、`z0_ohm=50`。
- 输出判读：端电阻值；三只电阻应能在常用阻值表附近选到。
- 常见误用：拿它当隔离器——电阻衰减器没有反向隔离，只耗功率；
  大衰减档并联臂阻值趋大、对电阻公差敏感，精度要求高就上精密度
  更高的档位并实测。

## ③ 功分器与耦合器

这组多数键只出电气参数（臂阻抗/隔离电阻/偶奇模阻抗），几何落地回到
①（微带综合）与 ⑤（寄生核查）。等分 Wilkinson 没有独立键——
`unequal_split_wilkinson` 取 K=1 即等分。

### `unequal_split_wilkinson` — 不等分功分器

- 什么时候用：两路输出功率不对称（馈电网络、监相支路）；K=1 退化
  为教科书等分（臂 √2·Z0、R=2·Z0）。
- 典型输入：`z0_ohm=50`、`power_ratio_k`（K²=P3/P2；K>1 表示端口 3 是
  大功率端）。
- 输出判读：两臂 λ/4 阻抗 Z02/Z03、隔离电阻 R（含臂端 R2/R3）、输出
  变换段 Z04/Z05。锚：K=2 → 51.5/103/106.07Ω @50Ω。
- 常见误用：拿可选输出 `freq_ghz` 的 λ0/4 直接当臂长——那是自由空间
  参考值，基板上要用 `microstrip_lambda_g` 的 λg/4；K>10:1 返回
  `practical_split=False`，可实现性先掂量。

### `lange_synthesize` — Lange 电桥

- 什么时候用：3dB 正交耦合、宽带平衡放大器正分；微带上的四指交指
  结构。
- 典型输入：`coupling_db=3.0103`（3dB 电桥口径）、`f0_ghz`、`er=3.66`、
  `h_mm=0.508`。
- 输出判读：耦合口 (Z0e,Z0o) → 四线等效 → KJ 反解的 (w,s) 与指长 λ/4。
  锚：3dB → (176.216,52.609)→(120.71,20.71)Ω。
- 常见误用：`coupling_db` 填负数——本键正数 dB 口径，3.0103 才是精确
  3dB；解出的缝 s 对照工艺极限，太窄降 h 或换板材重解。

### `gysel_core_synthesize` — Gysel 功分器（大功率）

- 什么时候用：隔离电阻要外挂大功率负载的场景（Wilkinson 内嵌电阻
  扛不住的功率量级）。
- 典型输入：只要 `z0_ohm=50`——纯电气口径。
- 输出判读：臂 √2·Z0、隔离线/桥带 Z0、外置负载 Δ1/Δ2；桥带 λ/2 中点
  是真实电压节点，外置负载可独立散热。
- 常见误用：拿输出直接画版图——本键只到阻抗级，几何在模板级
  （synthesize_gysel_model）；内嵌电阻版需求用 `unequal_split_wilkinson`。

### `bethe_hole_coupler` — 波导孔定向耦合器

- 什么时候用：波导系统取样/监测功率。公共宽壁中心圆孔，分析（给
  孔径）与综合（给耦合度）双向。
- 典型输入：`wr_name='WR-90'`、`freq_ghz=10`，分析给 `hole_diameter_mm`
  或综合给 `coupling_db=20`。
- 输出判读：耦合度/方向性/隔离；f=c0/(√2·a) 附近方向性取极值（隔离
  相消点）。
- 常见误用：工作点距 TE10 截止 <5% 显式拒绝；孔径守卫 d≤0.8b 且
  d≤λ0/3（小孔假设）——大耦合度硬塞会越界，改双孔阵（λg/4 间距
  口径随输出给出）。

### `multisection_coupler_equiripple` — 多节耦合器（等纹波）

- 什么时候用：定向耦合器要宽带平坦响应；对称奇数节，3..15。
- 典型输入：`n_sections=3`、`coupling_db=20`、`ripple_db=0.2`、`fbw=0.5`。
- 输出判读：逐节 (Z0e,Z0o)；耦合口带缘有 sinθ 锥度下垂，键面如实
  并列。
- 常见误用：与二项式版（`multisection_coupler_binomial`，带内单调最
  平坦）选型混淆——要平坦选等纹波、要单调选二项式；fbw 拉太宽逐节
  偶奇模阻抗差距拉大，工艺先掂量。

## ④ 滤波器：原型 → 综合 → 实现

主线三步：`chebyshev_prototype` 出原型（含传输零点）→ 按传输线形态选
综合键（微带耦合线/交指/波导腔/阶梯阻抗低通）→ 逐节几何落地。耦合
矩阵路线（调谐诊断、可调滤波）独立成支。带宽口径全部是相对带宽
fbw=(f2−f1)/f0。

### `chebyshev_prototype` — 广义切比雪夫原型

- 什么时候用：Chebyshev 族滤波器的起点；阶数+回损纹波（可加传输
  零点）拿 F/P/E 多项式与反射零点（Cameron 口径）。
- 典型输入：`order=5`、`rl_db=20`；椭圆特性给 `transmission_zeros`
  （±ω 成对）。
- 输出判读：反射零点应全在带内；带外零点位置就是阻带极点的理论
  落点，对照综合结果用。
- 常见误用：零点不成对（±ω）会进复系数原型口径——实结构先确认
  成对；本键是归一化低通域，带通换算在各综合键内部做。

### `stepped_impedance_lpf_synthesize` — 阶梯阻抗低通

- 什么时候用：微带低通（谐波抑制、偏置网络滤波）；高阻段当串联
  电感、低阻段当并联电容。
- 典型输入：`n_sections`、`fc_ghz`、`prototype=binomial`；chebyshev 档
  补 `ripple_db`。
- 输出判读：逐段线宽+长度（HJ 精算）；`z_high_ohm`（缺省 120）/
  `z_low_ohm`（缺省 20）须满足 Z_low<Z0<Z_high。
- 常见误用：chebyshev 档限奇数 N≤4（g 表域），偶数节直接被拒；
  高阻段阻抗定太高超出工艺最小线宽能实现的范围——先查厂内线宽
  下限。

### `coupled_line_bpf_synthesize` — 平行耦合线带通

- 什么时候用：中等带宽微带带通的主力形态；逐节 (w,s) 直接可画。
- 典型输入：`order=4`、`f0_ghz=2.4`、`fbw=0.1`、`ripple_db=0.5`、
  `epsilon_r`、`h_mm`。
- 输出判读：逐节 (Z0e,Z0o) → KJ 反解 (w,s)；谐振器长=λg/2−2Δl
  （Hammerstad 开路端修正已含）。锚：Pozar 例 8.7 阻抗表逐位复现。
- 常见误用：fbw 拉宽后端节耦合缝骤紧，先对照工艺缝极限；`fbw>1`
  被拒。

### `interdigital_bpf_synthesize` — 交指带通

- 什么时候用：紧凑布局的带通（谐振器 λ/4）；δ↑ 缝单调收窄，带宽
  与工艺缝极限相互牵制。
- 典型输入：`order`、`f0_ghz`、`fbw`、`ripple_db`、`b_mm`（两接地平板
  间距）、`epsilon_r`。
- 输出判读：杆宽/缝 mm（条带线介质档）；对称滤波器缝序列回文
  （s_1=s_{n+1}）可当自查锚。
- 常见误用：这是条带线（stripline）介质口径——微带实现换形式；
  `b_mm` 给错全体几何跟着错。

### `wg_cavity_bpf_synthesize` — 波导耦合腔带通（Cohn）

- 什么时候用：波导腔体滤波器（低损耗、高功率）；膜片耦合、λg/2 腔。
- 典型输入：`order=4`（谐振腔数，膜片=N+1）、`f1_ghz`/`f2_ghz`（通带
  两缘）、`ripple_db`、`a_mm`/`b_mm`。
- 输出判读：逐膜片开口 d（薄膜片闭式反解，与 `wg_iris_susceptance`
  同源同族）+腔长；Cohn 精度域 w≤0.2（相对带宽 ~20% 口径），越域
  如实守卫。
- 常见误用：相对带宽超 ~20% 还采信膜片尺寸——Cohn 一阶口径到头了；
  f1 贴 TE10 截止时 λg 映射发散。

### `combline_coupling_gap` — combline 耦合缝

- 什么时候用：combline 滤波器综合链的最后一步——k_ij 耦合系数换算
  成可加工的缝宽 g_ij。
- 典型输入：`k_coupling`（MYJ 口径 δ/√(g_j·g_{j+1})）、`z_r_ohm`、
  `b_mm`、`epsilon_r`；装载档给 `cap_ff`+`f0_ghz`（杆长随之给出）。
- 输出判读：w 与 g_ij（带域边界二分反解）；并列 k_norm_realized 与
  k_exact_phys 双口径自查。
- 常见误用：k 拿物理耦合定义值直接喂——综合链里的 k 是 MYJ 归一化
  口径，出自原型 g 值链；杆长/谐振频率配 `combline_resonance`。

### `coupling_matrix_synthesize_n2` — 耦合矩阵综合

- 什么时候用：已知目标传输零点集（椭圆/准椭圆特性）要 (N+2) 耦合
  矩阵指导腔间/端口耦合设计；与 `coupling_matrix_extract`（实测响应
  提矩阵）配对做调谐诊断。
- 典型输入：`order`、`rl_db`、`transmission_zeros`（±ω 成对，缺省全
  极点）。
- 输出判读：矩阵频响与原型逐点一致；耦合信息在 m0i/miL（首末节点
  =源/载）。
- 常见误用：零点口径没对齐——本键 ±ω 成对，逐个 TZ 的显式口径走
  `coupling_matrix_synthesize_explicit`；非成对=复系数原型（响应
  Ω→−Ω 不对称），实结构先想清楚。

## ⑤ 传输线不连续

布线拐弯、宽度跳变、层间过渡都会破坏 ① 里"均匀线"的假设。这组键给
等效 L/C 与 50Ω 参考 |S11|，用途：布局前定补偿（切角）、仿真前决定
要不要为这个不连续单独建模、实测异常时定位寄生来源。波导侧的膜片
匹配/电纳（`wg_iris_match`/`wg_iris_susceptance`）也是不连续家成员。

### `microstrip_bend_parasitics` — 直角弯寄生

- 什么时候用：布线必须拐 90° 时先看寄生多大、值不值得处理；给
  `freq_ghz` 直接出 50Ω 参考 |S11|。
- 典型输入：`width_mm`、`h_mm`、`epsilon_r`、可选 `freq_ghz`。
- 输出判读：未切角/50% 切角双档 L-C；有效域 W/h∈[0.2,6]、
  εr∈[2.36,10.4]、f·h≤12GHz·mm（精度 ~0.3%）。
- 常见误用：细线（W/h≲1.4）未切角档电感为负、显式拒绝——这是拟合
  域边界；切角比例别拍脑袋 50%，走 `microstrip_optimal_miter`。

### `microstrip_optimal_miter` — 弯角最优切角

- 什么时候用：切角值本身的设计；与上键的 50% 档成宽/窄线互补档。
- 典型输入：`width_mm`、`h_mm`——纯几何，与 εr、频率无关
  （Douville-James 1978 实测口径）。
- 输出判读：切角百分比 M=52+65·exp(−1.35·W/h)，切深 X=M·D/100
  （D=W√2 为未切角对角全长）。
- 常见误用：W/h 越出 [0.25,2.75] 实测域（守卫显式拦）；拿它处理
  非 90° 弯——拟合只对直角弯。

### `microstrip_step_parasitics` — 宽度阶跃寄生

- 什么时候用：阻抗段衔接处（滤波器高低阻段、匹配段换宽）评估反射。
- 典型输入：`w1_mm`（宽）、`w2_mm`（窄）、`h_mm`、`epsilon_r`、
  `freq_ghz`。
- 输出判读：并联 Cs+串联 Ls；只收收窄阶跃（W1>W2 且 Cs>0）。
- 常见误用：展宽方向（W1≤W2）显式拒绝——先分清哪侧是宽线；缓变
  锥形过渡靠多级小阶跃压寄生，单阶跃值替代不了整段。

### `microstrip_gap_parasitics` — 串联间隙寄生

- 什么时候用：直流隔断缝、间隙耦合谐振器的等效电路（π 网络
  Cs+两侧 Cp）。
- 典型输入：`w1_mm`、`w2_mm`、`gap_mm`、`h_mm`、`epsilon_r`、`freq_ghz`。
- 输出判读：50Ω 参考 |S11|/|S21|；g→∞ 时 Cs 指数归零（物理自检）。
- 常见误用：两侧线宽比超 W2/W1≤3 有效域（显式拒绝）；拿它算强耦合
  定向耦合器——那是耦合线理论的地盘（③ 的 `lange_synthesize`）。

### `microstrip_via_short` — 接地过孔

- 什么时候用：短路过孔/接地过渡的电感评估（傍路电容接地、短截线
  接地端）。
- 典型输入：`h_mm`（=基板厚）、`diameter_mm`、`freq_ghz`。
- 输出判读：R+L 与 50Ω 串联二口 S 参数；有效域 h<0.03λ0（守卫），
  拟合窗 h∈[100,631]µm 越窗有标记。
- 常见误用：低频厚基板下"过孔电感可忽略"的结论不能外推到 mmWave；
  多孔并联按 L/n 粗估前先确认电流真的均分。

## ⑥ 天线尺寸

这组给"第一性尺寸"——从频率/增益目标到几何初值。闭式起步，EM 仿真
复核是本仓的标准后手（模板库+多保真引擎阶梯）。阻抗类
（`dipole_emf_zin`/`small_loop_zin`）与口径效率类
（`horn_aperture_efficiency`/`aperture_efficiency_components`）见注册表
「天线与阵列」组。

### `patch_length` — 贴片尺寸速算

- 什么时候用：矩形贴片起点尺寸；f0+叠层三个数进出，出 W/εeff/L。
- 典型输入：`f0_ghz=2.4`、`epsilon_r=3.66`、`h_mm=0.508`。
- 输出判读：L 定谐振、W 影响带宽与馈电阻抗；εeff 是长度修正的核心。
- 常见误用：把闭式 L 当最终尺寸——边缘场与色散都在，谐振点以 EM/
  实测复核；馈点位置不在本键，贴片匹配走 ②。

### `folded_dipole_zin` — 折合偶极阻抗

- 什么时候用：折合振子馈电设计；谐振处 4× 步升（73.1→292Ω）是它的
  存在意义。
- 典型输入：`length_mm`、`f_ghz`、`wire_radius_mm`、`spacing_mm`（等
  线径口径）。
- 输出判读：Z_in 复数+step_up 比；l=λ/2 锚 292Ω≈300Ω。
- 常见误用：两臂线径不等——Mushiake 步升比修正在本键口径外（键面
  如实注明）；l 越出 (0,λ) 域拒绝。

### `helix_axial_design` — 轴向模螺旋反设计

- 什么时候用：圆极化中等增益天线的正向反设计；给 `n_turns` 得唯一
  解，不给则在整数圈内选带宽余量最大的解。
- 典型输入：`f0_ghz`、可选 `n_turns`；`alpha_deg` 缺省 13°（规程域
  [12°,14°] 带心）。
- 输出判读：直径/螺距/节距角/总轴长+随行 performance
  （design→performance 往返自洽 1e-9）。
- 常见误用：解出 C_λ 出规程域或 N≤3 时键面给 warnings 且不拒绝——
  采信由调用方定；目标度量缺省 directivity，要半功率瓣宽显式给
  `target_metric='hpbw_deg'`。

### `yagi_geometry_nbs_tn688` — Yagi 档位几何

- 什么时候用：要 NBS TN688 实测档案背书的八木起步图；六档封闭
  枚举。
- 典型输入：`class_lambda=0.8`、`f_ghz`（米制缩放）、`element_d_lambda`
  （缺省 0.0085=TN688 基准 0.25in@400MHz）。
- 输出判读：单元数/反射器间距 0.2λ/指向元间距；TN688 未覆盖的间距
  如实 null（禁编造），设计自行补。
- 常见误用：档位值乱给（只收 0.4/0.8/1.2/2.2/3.2/4.2λ 六档）；把
  已验证值与 null 两栏混着抄进图纸。

### `antenna_q_yaghjian_best` — 电小天线 Q 与 Chu 界

- 什么时候用：拿仿真/实测的 Z(f) 扫频评 Q、带宽上限；给 ka 判 Chu 界
  可达性。
- 典型输入：`f_hz`（升序 ≥3 点）+`z_re_ohm`/`z_im_ohm` 同长数组；`ka`
  可选；圆极化给 `polarization='circular'`。
- 输出判读：谐振点 Q、匹配半功率 FBW=2/Q、VSWR≤S 带宽；ka 给了附
  Chu/McLean 判定（低于无耗下界判 unreachable；圆极化界减半）。
- 常见误用：多谐振/宽带结构塞进来——单谐振口径（Δf/f₀≪1/(2Q)
  采样契约）；采样太粗让 dZ/dω 全是数值噪声；R≤0 或 X 无过零显式
  拒绝。

### `far_field_region` — 远场区界

- 什么时候用：定测试距离（⑦ 的前置）；判断近场测量要不要做近远场
  变换。
- 典型输入：`d_m`（天线最大口径，阵列给全阵口径）、`f_hz`；要分类给
  `r_m`。
- 输出判读：Fraunhofer 下界 2D²/λ+反应近场外界+Fresnel 区窗；测量
  距离惯例 2D²/λ 与 10D²/λ 两档并列。
- 常见误用：电小天线（D<λ/10.406）区界排序失效、显式拒绝——此时
  反应近场外界读 λ/2π 惯例档那一栏。

## ⑦ 测量与校准

投板之前把校准件设计好，投板之后把测量不确定度算清楚。这组覆盖
VNA 校准件设计（TRL）、校准件体检、夹具去嵌、不确定度预算、功率
定标、天线增益定标与谐振器 Q 的理论对照。全部是测量链上的确定性
闭式，与 VNA 误差修正算法本身无关。

### `trl_standards_design` — TRL 校准件设计

- 什么时候用：开测之前；给定波导或 TEM 线与频带，出直通/反射/线
  标准件尺寸。
- 典型输入：波导 `wr_name='WR-90'` 或 TEM `z0_ohm`+`epsilon_eff`
  （二选一互斥）、`f1_ghz`/`f2_ghz`。
- 输出判读：线标准=带中心 λg/4（Engen-Hoer 规则）；经典窗双判据：
  带缘电长度 [20°,160°]+f2/f1∈[1.2,3]——越窗给多线 TRL 建议。
- 常见误用：TEM 路线的 `epsilon_eff` 从 ① 的 `microstrip_analysis` 来，
  别拍 1；波导 f<1.05·fc 显式拒绝（λg 发散）；反射标准 ideal/λg/4
  偏置两档按夹具选。

### `cal_kit_standard_response` — 校准件体检

- 什么时候用：校准曲线不对劲时先判校准件本身——机械 SOLT 一阶
  模型 vs 理想响应+工程验收判据。
- 典型输入：`standard_type='open'`、`freq_ghz` 数组、`offset_length_mm`、
  `open_cap_ff`（open 件边缘电容）。
- 输出判读：工程档判据（非厂商 spec）：short/open |Γ|≥0.97、load
  RL≥35dB、through IL≤0.2dB；open 的 C_f>0 相位随 f 负旋。
- 常见误用：拿工程档判据替代厂商 spec 交收——口径不同；offset 损耗
  按 √f 标度，介质损耗主导件要调用方换算等效值（键面预声明）。

### `deembed_thru_metrics` — 2x-thru 夹具去嵌

- 什么时候用：测夹具里的 DUT 后把夹具效应拆掉，再提 C/R/Q。
- 典型输入：`freq_ghz`+DUT 的 S11/S21+2x-thru 的 S11/S21（[re,im] 对
  数组，同栅格）。
- 输出判读：去嵌后 Z12 主方法提取的 C/R/Q；内置锚=合成夹具+DUT→
  去嵌→网络与 C/R 逐位回收 ≤1e-9。
- 常见误用：DUT 与 thru 频率栅格不一致（同栅格是前提）；|S11|>0.9
  时简化式被拒（阈值可调），强反射 DUT 用全式口径。

### `vna_reflection_uncertainty` — 反射测量不确定度

- 什么时候用：回损验收前算"这次测量自己带多少不确定度"；校准后
  残差三误差项合成。
- 典型输入：`gamma_mag`、`directivity_db`、`source_match_db`、
  `tracking_db`（校准后典型 −45~−55/−40~−50）。
- 输出判读：|δΓ| 最坏界+主导项分解；Γ=0 时回损地板=−directivity
  （恒等锚）；rss 档给 u 与 U=k·u（k 缺省 2）。
- 常见误用：把校准前指标当残差填——残差是校准后剩余项；worst/rss
  两档口径别混着报。

### `power_cal_chain` — 功率校准链

- 什么时候用：功率计读数换算到远端平面可用功率，带 GUM 预算。
- 典型输入：`p_read_dbm`、`k_cal_lin`（传感器校准因子 K_b=η(1−|Γl|²)）、
  `cable_loss_db`、`gamma_source`/`gamma_load`。
- 输出判读：exact 模式逐点精确修正；相位未知用 band 模式拿 ±MU 带
  （U 形分布 u=MU/√2）。
- 常见误用：源/负载反射要用同一参考面的等效 Γ；频点逐点调用，别拿
  一个频点的修正值扫全带。

### `three_antenna_gain` — 三天线法定标

- 什么时候用：没有标准增益天线时，三支天线三对插损互相定标；或
  有参考天线走比较法（`method='comparison'`）。
- 典型输入：三天线法 `il12_db`/`il13_db`/`il23_db`+`f_ghz`+`range_m`；
  比较法给 `ref_gain_db`+`il_ref_db`+`il_dut_db`。
- 输出判读：三增益 G1/G2/G3（Friis 口径线性解）；IL 必须先扣电缆/
  接头并做失配与极化校正。
- 常见误用：远场条件不在本键内（自己拿 `far_field_region` 核）；原始
  插损不校正直接喂，三个增益全偏。

### `cavity_unloaded_q` — 同轴腔无载 Q

- 什么时候用：谐振器/腔体设计阶段评 Q 构成（导体 vs 介质）；给 ⑦
  的实测 Q 提取找理论对照。
- 典型输入：`f_ghz`、`conductivity_s_per_m=5.8e7`、`a_mm`/`b_mm`、
  `tan_delta`；粗糙度给 `roughness_model`（smooth/hammerstad/huray）。
- 输出判读：Qu=1/(1/Qc+1/Qd)；tanδ=0 时 Qd 如实返 null；
  Qu≤min(Qc,Qd)（单调性测试钉）。
- 常见误用：这是同轴腔理论口径——谐振器实测 Q 提取走 `q_factor_vf`
  （VF 极点法），一理论一实测，别互相替代。

## ⑧ 链路预算

部件设计完串成链，回答"到接收端还剩多少信噪比"。`cascade_budget` 是
总账本，路径损耗与其余键分头供数；收发混频规划先于预算——镜像落
进带内，后面全白算。

### `free_space_path_loss` — 自由空间路损

- 什么时候用：链路账的第一行；1km@1GHz=92.4477832dB（精确 SI 锚）。
- 典型输入：`distance_m`、`freq_hz`；环境/穿透损耗走 `excess_loss_db`
  显式加。
- 输出判读：d 或 f 加倍恒 +6.0205999dB；教科书常数式（32.44+…）与
  精确 SI 差 6.0mdB，对账时留意口径。
- 常见误用：拿它当城市/室内模型——统计环境模型（`hata_cost231` 等）
  是独立键，本键的环境损耗靠你显式给 `excess_loss_db`。

### `link_margin_calc` — 链路余量

- 什么时候用：一页纸链路账：发功率+双天线增益−路损−杂项，对比
  灵敏度出余量。
- 典型输入：`tx_power_dbm`、`tx_gain_dbi`/`rx_gain_dbi`、`distance_m`、
  `freq_hz`、`rx_sensitivity_dbm`、`misc_loss_db`。
- 输出判读：margin=P_r−灵敏度；d 加倍 margin 精确 −6.0206dB（恒等
  锚）可当自查。
- 常见误用：灵敏度自己另拍一个数——它是 `cascade_budget` 的产出，
  两条链对不上先查灵敏度口径。

### `cascade_budget` — 级联总账

- 什么时候用：接收/发射链逐级过账：总增益、Friis NF、IIP3/OIP3、
  P1dB、噪声底、SFDR、灵敏度。
- 典型输入：`stages` 级表（type∈{amp,mixer,filter,atten,cable}，顺序=
  信号流向）+`bw_hz`。
- 输出判读：无源级 NF 缺省=插损（T0 口径）；首级 NF 主导整机——
  第一放大器的增益与 NF 是预算的杠杆位。
- 常见误用：级表顺序填反（衰减器放第一级，插损直接进整机 NF）；
  `bw_hz` 缺省取末级，全链没给会显式报错。

### `correlated_cascade_nf` — 相关级联噪声

- 什么时候用：共享本振/共享源的双通道系统，级间噪声相关时 Friis
  不再准——本键算 delta_nf_db（相关−独立差）。
- 典型输入：`stages`（gain_db/nf_db 级表）+`rhos`（级间相关系数；
  共享 LO ρ=+1、独立 ρ=0）。
- 输出判读：F_tot、Friis 对照、delta_nf_db；ρ 全 0 逐位退化 Friis
  （对拍钉）。
- 常见误用：ρ 集合要过 PSD 实测守卫——逐对 |ρ|≤1 不够，三对不一致
  组合显式拒绝；失配/多端口广义噪声矩阵不在本域。

### `two_ray_loss` — 双径干涉路损

- 什么时候用：地面视距链路（塔站/无人站）的路径账；比 FSPL 多一面
  镜反射的相干干涉。
- 典型输入：`d_m`、`h_tx_m`/`h_rx_m`、`f_hz`、`pol='v'`。
- 输出判读：断点距离 d_break=4·h_tx·h_rx/λ；d≫d_break 后包络按
  −40dB/dec 渐近（比 FSPL 陡）。
- 常见误用：断点以内套 −40dB/dec 外推；地形起伏/绕射不在双径口径
  （刀刃绕射走 `knife_edge_loss`）。

### `mixer_image_plan` — 混频镜像规划

- 什么时候用：定中频之前——镜像距信号 2·f_IF，预选滤波器（④）的
  抑制指标从这里来。
- 典型输入：`f_rf_hz`、`f_lo_hz`；可选 IQ 失衡 `amp_imbalance_db`+
  `phase_imbalance_deg` 出镜像抑制比 IRR。
- 输出判读：低/高本振镜像位置、Δf_LO→f_IF 1:1 平移；IRR 与
  `iq_imbalance_irr` 同式双源互证。
- 常见误用：f_RF=f_LO（零中频，镜像=信号本身）显式拒绝；IF 选太低
  镜像贴带沿，预选滤波器做不出来。

## 本页之外的域

48 键只覆盖微波硬件设计主线。以下域的键面都在
[计算器注册表参考](calculators.md)，按组检索：

- 阵列综合与 DOA（`array.*`/`doa_*`）；雷达全链
  （`radar_range_equation`/`fmcw_*`/`sar_*`/`mti_*`/`*_cfar`）。
- 传播统计与卫星（`hata_cost231`/`walfisch_*`/`rain_*`/`sat_link_budget`）；
  EMC 与安规（`esd_*`/`multipactor_*`/`shielding_effectiveness`/
  `exposure_*`）。
- 高速数字（`ctle_*`/`cdr_*`/`tdr_*`）；量子读出（`qubit_*`）；
  超材料/超表面（`crlh_*`/`gstc_*`/`ris_*`）；调制与编码
  （`pll_*`/`ofdm_*`/`*_ber*`/`reed_solomon_*`）。

参数表与键数的权威出口永远是 `rfauto calc list`；本页与注册面冲突时，
以注册面实时输出为准。
