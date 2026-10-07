# 模板库

> 器件模板共 **71** 个（`docs/templates/*/meta.yaml` 聚合；与代码单源 `openems_templates.TEMPLATE_META` 键集/计数构建时互证，一致性另由 `tests/unit/test_template_meta_consistency.py` 钉死）。本页由 `scripts/build_docs_pages.py` 机读生成，勿手改；单模板物理细节（几何画法/标定史/真机锚）以仓内 `docs/templates/<名>/` 为准。

## 总表

| 模板 | f0 (GHz) | 端口 | 参数数 | 拓扑摘要 |
|---|---|---|---|---|
| [atten_pi](#atten_pi) | 2.5 | 2 | 3 | — |
| [atten_t](#atten_t) | 2.5 | 2 | 3 | — |
| [bend](#bend) | 2.5 | 2 | 2 | — |
| [branchline](#branchline) | 2.4 | 4 | 3 | — |
| [branchline_2sect](#branchline_2sect) | 2.5 | 4 | 6 | 两节分支线 3dB 正交耦合器（C4 族，Pozar 经典点）：主线 Z_a=Z0 两节 + 外支臂 (1+√2)Z0 + 中支臂 √2·Z_a²/Z0（单参数族，main_z_ratio 可调）；四角 50Ω 馈线沿 x 引出，P1 左上输入/P2 右上直通/P3 右下耦合/P4 左下隔离 |
| [cline_coupler](#cline_coupler) | 2.5 | 4 | 4 | 耦合线定向耦合器（后向波，C4 族）：两条 λ/4 平行耦合线（KJ (w,s) 反解）+ 四条 50Ω 馈线外推+横向搭接段（同心直连短路）；1=输入/2=直通（线 A 远端）/3=耦合（线 B 近端，与输入同侧）/4=隔离 |
| [coax_waveguide_transition](#coax_waveguide_transition) | 10.0 | 2 | 8 | 波导-同轴探针过渡：WR-90 矩形厚壁腔（a×b×l_wg，四壁+背短路板厚 wg_t，封闭 PEC 腔）+ 探针柱经底壁伸入腔内（针轴平行 TE10 E 场沿 y，针中心距背短路内侧面 backshort=λg/4）；port1=探针基 LumpedPort 集总桥（R=50Ω），port2=腔端面 RectWGPort 解析 TE10；z 轴双端 PML_8、x/y MUR |
| [coil_nfc](#coil_nfc) | 0.01356 | 1 | 6 | NFC/WPC 平面线圈：FR4 类基板（无地平面）+ 阶梯方螺旋（外圈馈隙=端口位）+ 中跳线桥（抬高 z 越过螺旋，lange air-bridge 同法）把内端引出到外端端口 对侧——单导体通路，端口跨馈隙；全域 MUR（无地，辐射口径；13.56MHz 电小， 近场主导） |
| [combline](#combline) | 2.5 | 2 | 6 | 梳状带通（§C3 滤波器族 II，MYJ Ch.10 口径）：N 根缩短棒平行排列，接地端同端（底端全部过孔 r=0.15mm），顶端各接 LumpedElement 装载电容（CSXCAD caps=True，ny=2 即方向索引 z——shunt 对地惯用法，电压沿 z 跨基板全隙、端帽板落在 z=0/z=H_SUB 既有 PEC 面；C=c_load_pf；谐振条件 cot θr=ω0·C·Z_r 定缩短长度）；双 50Ω 馈线缝耦合自 y=−BOARD 板边引入（单轴 PML） |
| [coupled_bpf](#coupled_bpf) | 2.5 | 2 | 6 | 平行耦合（边缘耦合）带通（WP2.3 Tier1 BPF 族锚，Pozar §8.6.2）：N 个 λg/2 半波谐振器沿 y 阶梯排列（相邻平行、y 向错位 λg/4），N+1 个耦合段（馈-腔、腔-腔×(N−1)、腔-馈，段长逐端 Δl 修正）；输入/输出 50Ω 馈线在 y=∓BOARD 板边（单轴 PML） |
| [coupled_line](#coupled_line) | 2.4 | 3 | 3 | — |
| [cps](#cps) | 2.5 | 2 | 3 | — |
| [cpw](#cpw) | 2.5 | 2 | 3 | — |
| [diplexer](#diplexer) | 2.5 | 3 | 3 | Diplexer LP+HP T 结（TA-5，一阶常阻互补对偶 CR 型）：输入 50Ω 馈线（port1=antenna， −BOARD 板边）→ 微带 T 结 → LPF 臂（+x：50Ω 短段+LumpedElement 串联 L 断口桥接+50Ω stub 至 +BOARD=port2）与 HPF 臂（−x 镜像，串联 C=port3）；集总元件 atten_pi 串臂同法（ny=0 断口桥接）； 全金属同层零交叉 |
| [dipole](#dipole) | 2.4 | 1 | 3 | — |
| [embedded_ms](#embedded_ms) | 2.5 | 2 | 3 | 嵌入式微带均匀段（TA-11）：地面=z=0 域 PEC 底界，基板 [0,H_SUB]， 零厚条带 z=H_SUB，同 εr 覆盖层 [H_SUB, H_SUB+H2]（嵌埋介质单材料盒，均匀 嵌埋电气精确），其上开放（top MUR）；双 MSLPort 板边入（端口面贴 PML） |
| [fgcpw](#fgcpw) | 2.5 | 2 | 4 | 有限地共面波导 FGCPW 均匀段（TA-9，真 CPW 口径）：基板上表面中心条带+两有限宽接地（全长度含端口段）， 无底地（基板下方空气、域底 MUR——cps 口径；与 cpw 模板 CPWG 强制底地相区别，registry CPW 段注释自证）；双 CPWPort 板边入（端口面贴 PML） |
| [gysel](#gysel) | 2.5 | 3 | 4 | Gysel 高隔离功分器（1975 六节 λ/4 环，P2⑪ L-jog 等长拓扑重设计 2026-09-16）：P1—70.7Ω λ/4 臂—P2/P3；P2/P3—50Ω λ/4 隔离线（竖直段 YJ=iso_len−jog + 顶端横移 jog=\|arm_len−iso_len\| 保电长度）—Δ1/Δ2（x=±iso_len，各接 50Ω LumpedElement 端接，隔离负载外置）；Δ1—50Ω λ/2 桥带（跨度 2·iso_len=λ/2 精确，中点开路）—Δ2。矩形旧版（Δ 在角部、桥带继承 2·arm_len，+2.32% 二阶偏差）为历史口径（#211） |
| [hairpin](#hairpin) | 2.5 | 2 | 6 | 发夹线带通（WP2.3 Tier1 滤波器族）：N 个 λg/2 半波谐振器折成 U 形沿 x 并排，相邻外臂平行耦合（缝 gap_mm）；输入/输出为 50Ω 抽头馈线（T 形，板边 x=∓BOARD 至首/末谐振器外臂，抽头位置 tap_frac 自开路端计） |
| [hairpin_alt](#hairpin_alt) | 2.5 | 2 | 6 | 交替取向发夹线带通（TODO 0dk 根修变体）：N 个 λg/2 半波谐振器折成 U 形沿 x 并排，奇数序谐振器上下翻转（弯带/开路端 y 逐腔轮替），相邻臂开路端交替 → 电/磁耦合同号叠加；相邻外臂平行耦合（缝 gap_mm）；输入/输出为 50Ω 抽头馈线（板边 x=∓BOARD 至首/末谐振器外臂，抽头位置 tap_frac 各自开路端计，末腔翻转时输出抽头自 y1 向下）。可选布局选项 orientation=alternating\|same（缺省 alternating；same=同网格同向对照，不进 params） |
| [helix](#helix) | 2.4 | 1 | 5 | 螺旋（§10.3 C1）：单导线 staircase 方螺旋（每圈 4 直段各 1/4 螺距上升 + 角部竖板，无双并联回路），首圈 A 段即馈口顶，总线长 4·d·N + N·p = k_helix·λ0/4（k_helix=1.3615 HFSS 仲裁）；馈口=地面 z=0 → 角 A 柱底 LumpedPort；无介质板（PEC 地面悬空导体） |
| [hmsiw](#hmsiw) | 10.0 | 2 | 4 | HM-SIW 半模基片集成波导均匀段（TA-8）：基板矩形域，底板=显式零厚板贴 z=0 PEC 底界+单列过孔藩篱 x=+w/2（藩篱止于端口面），开路边 x=−w/2=磁壁（域 MUR 余量 w_eff/2）、顶开放（MUR，无上板——HMSIW 定义性质）；端口=两端面 LumpedPort z 桥（跨介质孔径、R=Z_PV， 端口即终端负载 siw v2 口径）——准 TE0.5 模 fc 由式 (11) 链给出（Lai-Fumeaux 2009 T-MTT 式 (8)-(14)） |
| [ifa](#ifa) | 2.4 | 1 | 3 | IFA（§10.3 C1，PIFA 窄臂退化）：短路板 x∈[−1,0]（z 0→h）+ 臂 z=h 自短路板 −x 向伸出 λ/4 + 馈针=LumpedPort x=−feed_off（顶触臂、底触地，不另画金属针盒）；基板 + z-min PEC 地 |
| [interdigital](#interdigital) | 2.5 | 2 | 5 | 交指带通（§C3 滤波器族 II，Cohn 交指口径）：N 根 λ/4 均匀谐振棒平行排列，接地端交替（奇棒底端过孔/偶棒顶端过孔，r=0.15mm），相邻棒全长缝耦合；双 50Ω 馈线缝耦合自 y=−BOARD 板边引入（gysel 同边先例，单轴 PML） |
| [inverted_ms](#inverted_ms) | 2.5 | 2 | 3 | 倒置微带均匀段（TA-7）：金属/介质 z 序相对微带对调——地面=z=0 域 PEC 底界，零厚条带悬于 z=h_air 空气隙顶（基板下表面），基板 [h_air, h_air+h_sub] 上覆、其上开放（top MUR）；双 MSLPort 板边入（端口面贴 PML） |
| [isl_shielded](#isl_shielded) | 2.5 | 2 | 6 | ISL 屏蔽悬置线均匀段（TA-10，准静态口径如实）：地面=z=0 域 PEC 底界→空气隙 g→基板 [g, g+h_sub]（悬浮）→零厚条带（基板上表面）→空气 h_top→屏蔽顶板（显式零厚板 z=z_wall）；两列过孔藩篱 x=±wall_x 贯通底地与顶板（藩篱止于端口面，hmsiw v2 端面口径）；双 MSLPort 板边入（端口面贴 PML） |
| [lange](#lange) | 2.5 | 4 | 4 | 展开型 Lange 电桥（3dB 正交，C4 族）：四指交替并联（网络 A=指1/3、B=指2/4，DC 隔离），air-bridge=抬高薄金属+竖直立柱（同端 A/B 桥错位、两端分置）；外指承馈 P1/P2/P3/P4，等效两线 (Ze4,Zo4)=(120.71,20.71)Ω 精确成立 |
| [loop](#loop) | 2.4 | 1 | 3 | 环形（§10.3 C1，2026-09-16 自由空间改造）：z=0 方环（中心线边 a、带宽 w，顶/左/右全跨含角）+ 底边中央断口 g（馈口位）LumpedPort 跨断口（E 沿 x，dipole 中央馈口同型）；无基板无地：底 MUR + 域 z 向下延 λ0/4（dipole 同款） |
| [marchand_balun](#marchand_balun) | 2.5 | 3 | 3 | Marchand 双槽臂最小族（底层五盒：外地 M1/M2、中条 M3、封口桥 M4/M5 与中条精确共边；顶层微带穿两槽+共享开路支节）：设计级结论=单支节串接已被两引擎互证证伪（四门 FAIL、两跨越点激励不对称、拓扑无隔离机制）——真 Marchand=两节对称耦合段（电路级综合 core/slotline_transitions.synthesize_marchand_two_section，名义点 50Ω→280Ω 差分、C=−7.02dB、(w,s,ℓ)=(1.7616,0.1016,18.4670)mm@h=1.524）；本模板保留作对照口径与判据载体，不作生产巴伦 |
| [mline](#mline) | 2.5 | 2 | 2 | — |
| [mmwave_series_array](#mmwave_series_array) | 78.0 | 1 | 7 | 1×N 串馈毫米波阵（§18.3d C10d）：N 元共线沿 y（x=0 居中，L 沿 y/W 沿 x）， 相邻元以互联线接辐射边中心（互联长 s=自由设计参数，行波渐进相位 βg·s）； MSLPort 自 y=−DOM 入、自画馈段至链首元（feed_margin）；链末 stub+匹配集总 负载到地（R=线 Z0 一阶）——行波阵口径，与 C2 patch_array_series（λg/2 谐振式、链末开路）分族；基板 + z-min PEC 地，y 轴 PML_8 |
| [monopole](#monopole) | 2.4 | 1 | 3 | 单极子（§10.3 C1 天线族 II）：竖直零厚细带（x 向宽 mon_w，y=0 面）自馈口顶 z=feed_gap 起立 λ0/4；馈口=地面 z=0 → 细带底缘 LumpedPort（patch 底馈探针同型）；无介质板（像理论口径） |
| [ms_array_NxN](#ms_array_nxn) | 10.0 | 0 | 5 | 有限 N×N 反射阵（ms_patch 单元平铺）：接地基板（z 底 PEC 边界，地连续 由边界构造性保证）+ cell_map 逐单元贴片表；上方 λ0/4 空气隙软激励平面 照明（exc_type=0 全口径，官方 PPW 教程口径，法向入射 E∥x 极化前提）； 侧向 MUR（有限口径，无 PEC/PMC 对壁——那是单胞无限阵技巧） |
| [ms_cross](#ms_cross) | 10.0 | 2 | 4 | FSS 带阻十字偶极子单元：基板顶零厚正交双十字臂（x 臂=受激臂，y 臂= 正交极化对偶臂；金属偶极子 E∥臂耦合，无需槽缝族的方向旋转）；单胞 PEC/PMC 对壁域（x 对壁 PEC / y 对壁 PMC，TEM 平面波）；屏两侧 λ0/4 空气区各置双 E 探针对（自由悬浮无源）+ z 底 MUR 上方 soft plane 激励面 |
| [ms_jcross](#ms_jcross) | 10.0 | 2 | 5 | FSS 带通 Jerusalem cross 缝单元：零厚金属屏（胞面减「主缝+4 端枝」互联 孔径的补集盒分解，ms_jcross_metal_boxes 单源）+ 主缝端 4 枝端加载； 单胞 PEC/PMC 对壁域（x 对壁 PEC / y 对壁 PMC，TEM 平面波）；屏两侧 λ0/4 空气区各置全口径电阻片（下片激励、上片接收）；z 底 MUR |
| [ms_patch](#ms_patch) | 10.0 | 1 | 4 | 反射阵方贴片单元：接地基板（z 底 PEC 边界）+ 零厚方贴片；单胞方形域 x 对壁 PEC / y 对壁 PMC（TEM 平面波，官方 Parallel Plate Waveguide 教程 口径）；贴片上方 λ0/4 空气区置双 E 探针对（自由悬浮无源）+ 探针对上方 soft plane 激励面，域内零电阻片 |
| [ms_ring_patch](#ms_ring_patch) | 10.0 | 1 | 3 | 双谐振反射阵单元：接地基板（z 底 PEC 边界）+ 零厚方环（外边 ring_outer=void+2·ring_w，内空腔 void=0.4λ0，环宽 λg/40）+ 环心方贴片 （边长=LUT 扫描变量）；单胞方形域 x 对壁 PEC / y 对壁 PMC（TEM 平面波）； 贴片上方 λ0/4 空气区置双 E 探针对（自由悬浮无源）+ 探针对上方 soft plane 激励面，域内零电阻片 |
| [msl_cpw](#msl_cpw) | 2.5 | 2 | 8 | 微带↔接地共面波导过渡（WP2.5 Tier 2）：微带直段 → 4 段等分阶梯渐变（线宽线性内插）→ CPW 中心带 + 两侧地（延至板边）+ 双列接地过孔栅栏（地缝合底板 PEC，抑制平行板模）；过渡区居中 |
| [msl_siw_taper](#msl_siw_taper) | 10.0 | 2 | 5 | MSL 锥形过渡+SIW 直段（Deslandes-Wu 两段论）：50Ω MSL 馈线 → 线性锥（w50→ w_end=Z_PV 微带当宽的阻抗变换器+锥末-SIW 台阶不连续）→ SIW 直段（顶壁显式板 +两列过孔藩篱止于板缘=siw v2 口径+底壁板）；基板填满矩形域，z=0 PEC 底界， 顶界 MUR（MSL 区微带环境）；端口=双 MSLPort（面贴域界 PML_8、端口段=均匀 50Ω 线） |
| [msl_slot_transition](#msl_slot_transition) | 2.5 | 2 | 3 | Roberts/Knorr 过渡（双层板）：底层地板开槽（槽开口向 −x 直入 PML，+x 封口=λg'/4 短路臂），顶层微带沿 y 跨槽后延伸 λg_m/4−Δl 开路支节（C6 2026-09-22 符号修正：端效应惯例=物理长缩短，Pozar eq.4.23）（跨越点虚短路/虚开路机理，Knorr 1974/Schuppert 1988）；MSLPort 段内移 14·BASE（H4：段⊂PML_8 致非物理已根治） |
| [nway_wilkinson](#nway_wilkinson) | 2.5 | 5 | 4 | N-way Wilkinson 功分器（TA-4，树形 N=4）：输入馈线（port1，−BOARD 板边）→ 一级 T 叉（双 λ/4 臂 √2·Z0，x 向并列间距 G1=9mm，wilkinson GAP 口径）→ 50Ω 支线 → 二级双 T 叉（各叉臂间距 G2=5.5mm）→ 四路 50Ω 输出馈线（port2..5，+BOARD 板边）；隔离电阻 R=2·Z0 各臂端面跨接（LumpedElement ny=0，共 3 支）；全金属同层零交叉。拓扑选择：内核 star 分支（Pon 1961 浮点节点）单层 N≥3 不可布（浮点节点/Δ 环闭合路径必与边界馈线交叉）——渲染取 内核 tree 分支（阻抗级同源），N=2 与 wilkinson 模板同解、N≥8 超轮转管线规模（渲染守卫拒 n_way≠4） |
| [patch](#patch) | 2.4 | 1 | 3 | 矩形贴片（patch_len = 谐振 λ/2 轴，沿馈电方向 y）+ 边缘微带馈电 |
| [patch_array_1x4](#patch_array_1x4) | 5.8 | 1 | 7 | 1×4 直线贴片阵（§10.3 C2）：4 元沿 x 等距 spacing、行中心 y=20mm，单元 L 沿 y/W 沿 x、插入馈缺口开在 −y 边（3 盒贴片）；corporate 树=主干 50Ω（底探针→J0）+ J0→J1± λ/4 70.7Ω + J1± 50Ω 透明连线（y0 横走/各元 x 竖走）+ 每元最后一段 λ/4 70.7Ω 入缺口；基板 + z-min PEC 地 |
| [patch_array_2x2](#patch_array_2x2) | 5.8 | 1 | 8 | 2×2 平面贴片阵（§10.3 C2）：栅格中心 (0,20mm)，元列 x=±dx/2、元排 y=20∓dy/2；底排缺口向 −y 自下入，顶排缺口向 +y——馈线经 J1± 沿 y0 外走到元列外侧走廊 x=±(dx/2+W/2+2mm) 上行、顶排上方内折、变换段自上向下入缺口（同层零交叉）；H-tree 阻抗账同 1×4；基板 + z-min PEC 地 |
| [patch_array_series](#patch_array_series) | 5.8 | 1 | 5 | 1×3 串馈贴片阵（§10.3 C2）：3 元共线沿 y（x=0 居中，L 沿 y/W 沿 x），相邻元以 λg/2 50Ω 互联接辐射边中心；MSLPort 自 y=−BOARD 入、自画馈段至链首元 −y 边（feed_margin）；链末开路。相位账：λg/2 段 180°+λ/2 贴片两边场反相 180° ⇒ 同相侧射；单轴 PML（y）；基板 + z-min PEC 地 |
| [patch_eep_1x4](#patch_eep_1x4) | 5.8 | 4 | 5 | 1×4 EEP 贴片阵（§DP-4 P3）：4 元沿 x 等距 spacing（行中心 y=20mm），缺口全开 −y；每元独立 LumpedPort 底探针（端口 1..4 =x 升序），无 corporate 馈树，元间 DC 隔离=EEP 定义性质；基板 + z-min PEC 地 |
| [patch_eep_2x2](#patch_eep_2x2) | 5.8 | 4 | 6 | 2×2 EEP 贴片阵（§DP-4 P3）：栅格中心 (0,20mm)，元列 x=±dx/2、元排 y=20∓dy/2，四元同向（缺口全开 −y）；每元独立 LumpedPort 底探针（端口 1..4=行主序 x 外层 y 内层），无 corporate 馈树，元间 DC 隔离=EEP 定义性质；基板 + z-min PEC 地 |
| [pifa](#pifa) | 2.4 | 1 | 5 | PIFA（§10.3 C1）：贴片 z=h（L×W）+ +x 边短路板（宽 Ws，z 0→h 触地）+ 馈针（距短路板 pin_back，y 偏 pin_y，针顶触贴片、针底触地）；LumpedPort 沿针 z 向；基板 + z-min PEC 无限大地 |
| [pyramid_horn](#pyramid_horn) | 10.0 | 1 | 6 | 标准增益角锥喇叭：WR-90 波导馈电直管（端口面贴 y=−DOM_Y PML_8 域边）+ 四壁 梯形口径段（喉部 y=0、口径 y=l_flare；H 面宽沿 x a→a1、E 面高沿 z b→b1）； 斜壁以 8 段矩形截面阶梯链逼近（段间框面闭合=全 PEC 封闭腔）；空气填充无介质 板，y 轴双端 PML_8、x/z MUR |
| [qwt_multisection](#qwt_multisection) | 2.5 | 1 | 4 | 多节 λ/4 阻抗变换器（TA-2）：50Ω 馈线（port1，−BOARD 板边入）+ N 节 λ/4 均匀微带线级联（节阻抗 Z1..ZN 闭式表驱动，沿 y）+ 末端 LumpedElement R=ZL 端接盒（z=0..H_SUB 对地，mmwave_series_array 链末负载同法）；z-min PEC 地 + 缺省 rogers4350b 叠层（guided 口径） |
| [ratrace](#ratrace) | 2.5 | 4 | 2 | — |
| [ridged_wg](#ridged_wg) | 5.2 | 2 | 6 | 空气单脊矩形波导均匀段（TA-6）：脊段外廓 a×b+顶壁居中脊 s×d（y∈±l_ridge/2）+ 两端加宽馈波导 a_feed×b（H 面对称阶跃，a_feed=c/(2·0.75·fc_ridge) 结构性 >4a/3）+ 阶跃端面框板闭合（零泄漏）； 双 RectWGPort 打在馈段（激励/探针面均内移 16·BASE 出 PML_8）；空气填充全金属（无介质板） |
| [ring_resonator](#ring_resonator) | 2.5 | 2 | 4 | 微带环形谐振器（F-A M3 材料提取 fixture）：闭环环带（r_mean±w/2，逐网格行 栅格化，ratrace 同法 #198 零台阶）+ 径向对置双 50Ω 间隙耦合馈线（x=0 沿 y， 端口面贴 y=±BOARD PML_8 域边）；对置 180° 馈点对各次模均为场腹（全 n 模可 激励）；z-min PEC 地 + 缺省 rogers4350b 叠层（guided 口径） |
| [schiffman](#schiffman) | 2.5 | 4 | 5 | Schiffman 90° 定差移相器（TA-1）：耦合段=远端桥接平行耦合 U 形全通段（C-section：双带条 x=±(gap/2+w/2) 沿 y、远端桥带闭合，port1/2 在 −BOARD 板边近端）+ 参考直通段（50Ω，长 l_ref，port3/4 在 ±BOARD 板边）；双路径同板 DC 隔离（净空 ≥3·h_sub）；全通匹配 Z0e·Z0o=Z0²=2500 由设计链构造保证 |
| [sicl](#sicl) | 2.5 | 2 | 5 | SICL 基片集成同轴线均匀段（TA-3）：矩形同轴腔（上下地板=域 z 边界 PEC+显式零厚板 siw 同款；两列接地过孔墙 x=±a/2、心距 s、藩篱贯通全域直入 PML=匹配端接 siw v1 口径）+ 零厚度内导体条带（w，中面 z=b/2=H_SUB/2）；端口=双 StripLinePort（面贴 ±DOM_Y 域边界 PML_8）；矩形域 DOM_X/DOM_Y 字面注入 |
| [sir_bpf](#sir_bpf) | 2.5 | 2 | 8 | λ/4 型接地 SIR 带通（§C3 滤波器族 II，MYJ SIR 章口径）：N 根阶梯阻抗棒平行排列（开路端低阻段 w_low + 接地端高阻段 w_high，步进比 Z_lo/Z_hi=35/70 给出紧凑化，谐振条件 tanθ1·tanθ2=Z_lo/Z_hi），同端接地顶端过孔 r=0.15mm，耦合区=低阻段（相邻棒低阻段对齐）；双 50Ω 馈线（板边段 w_feed + 耦合段 w_low 台阶）缝耦合自 y=−BOARD 板边引入（单轴 PML） |
| [siw](#siw) | 10.0 | 2 | 4 | 直 SIW 传输线段：基板 z∈[0,h] 上下显式零厚金属板（贴 z 边界 PEC）+ 两列 金属化过孔 PEC 圆柱（x=±w/2、心距 s、全域精确栅格、藩篱直入 PML=匹配 端接）；端口=两端 LumpedPort z 桥（中线、跨全高、盒边入网、16·BASE 出 PML_8）；域 x 半宽=w/2+w_eff/2（侧界 MUR 吸收泄漏）、y 半宽=line_len/2+ 16·BASE（PML_8）——矩形域，BOARD=60e-3 不适用（机制层 DOM_X/DOM_Y 字面注入） |
| [slot](#slot) | 2.4 | 2 | 4 | 缝隙（§10.3 C1）：z=0 有限金属地（4 盒拼合、槽 L×Ws 留空）+ z=h 50Ω 微带馈线 y 向垂直跨槽居中 + 双 MSLPort 板边端接（y=∓BOARD，单轴 PML）；底 MUR + z 向下延 λ0/4（槽向下半空间也辐射，PEC 底会短路槽） |
| [slotline](#slotline) | 2.5 | 2 | 3 | 均匀槽线段（路线 A，单面金属开缝、无地开放结构）：槽 \|y\|≤w/2 贯通至两端边界，两端 WaveguidePort（E/H 模式文件），激励面内移 16·BASE 出 PML_8；基板 z∈[0,h]，上下/侧向 MUR、端口轴 PML_8；槽跨压探针 9 站 |
| [slotline_lumped](#slotline_lumped) | 2.5 | 2 | 3 | 均匀槽线段（路线 B，官方 AddLumpedPort 范式）：金属/基板/槽贯通全域直入 PML（匹配端接），两端 LumpedPort 跨槽桥接（盒三向边全部入网，#198/#174）；槽跨压探针 9 站 [−L/4,+L/4] |
| [sma_launcher](#sma_launcher) | 2.5 | 2 | 10 | SMA 边缘弹射（WP2.5 Tier 2，end-launch 夹具口径）：PTFE 填充 50Ω 同轴段（针/壳圆柱自画）在板边切口之外，针水平穿出搭焊在微带上（针底切线=基板顶），壳底切 z=0 PEC 夹具底板、壳端与 PCB 下方夹具金属块前脸实触（地链）；port1=同轴截面集总桥（针顶→壳内壁顶），port2=板边 MSLPort |
| [stepped_impedance](#stepped_impedance) | 2.4 | 2 | 5 | — |
| [stripline](#stripline) | 2.5 | 2 | 2 | — |
| [suspended_stripline](#suspended_stripline) | 2.5 | 2 | 3 | — |
| [tjunc](#tjunc) | 2.5 | 3 | 3 | — |
| [varactor_bpf](#varactor_bpf) | 2.5 | 2 | 9 | 变容管调谐发夹线带通（M-5 首个半有源模板，hairpin 族增量）：N 个 λg/2 级 U 形谐振器沿 x 并排、相邻外臂平行耦合（缝 gap_mm），每 U 左臂开路端对地并联一只 lumped C(V)（CSXCAD LumpedElement，ny=2 全隙盒）；输入/输出 50Ω 抽头馈线（T 形，板边 x=∓BOARD；单轴 x PML） |
| [via](#via) | 2.5 | 2 | 3 | — |
| [vivaldi_tsa](#vivaldi_tsa) | 10.0 | 2 | 4 | Vivaldi 端射张口槽线天线（AP-11）：有限地面 z=0 带指数张口槽（喉部 y=−L/2 向口面 y=+L/2 指数张开，阶梯化栅格化），基板上覆、顶面 50Ω 微带跨槽馈（slot 模板已证机理；巴伦=独立馈电件留登记注记）；双 MSLPort 板边入（prop_dir=x） |
| [wilkinson](#wilkinson) | 2.5 | 3 | 3 | T型分叉 + 双 λ/4 臂（x 向并列）+ 100Ω 隔离电阻（LumpedElement） |
| [wstep](#wstep) | 2.5 | 2 | 3 | — |
| [xcheb_bpf4](#xcheb_bpf4) | 2.5 | 2 | 9 | 交叉耦合开路环四重奏（TA-14）：四个 λg/2 方形开路环 2×2 排布（环1 左上/2 右上/3 右下/4 左下）；耦合=1-2 顶行水平缝 + 2-3 右侧竖缝 + 3-4 底行 水平缝 + **4-1 左侧竖缝（非相邻交叉耦合，cm_core folded m14 映射）**；馈电 =环 1/4 左边抽头（50Ω 馈线自 x=−BOARD 板边，hairpin A1 去嵌口径） |

## atten_pi

- **抽取判据**：S11/S21 @ MSLPort 1-2（π 型电阻衰减器：\|S21\|≈-A dB 平坦，锚=ABCD 电阻网络闭式裁判+E4 attenuator_pi 同源）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`atten_db`、`w_mm`、`shunt_off_mm`
- **名义参数**：`atten_db`=10.0，`w_mm`=1.1134，`shunt_off_mm`=6.0

## atten_t

- **抽取判据**：S11/S21 @ MSLPort 1-2（T 型电阻衰减器：\|S21\|≈-A dB 平坦，锚=ABCD 电阻网络闭式裁判+E4 attenuator_t 同源）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`atten_db`、`w_mm`、`shunt_off_mm`
- **名义参数**：`atten_db`=10.0，`w_mm`=1.1134，`shunt_off_mm`=6.0

## bend

- **抽取判据**：S11/S21 @ MSLPort 1-2（直角弯折：锚=\|S11\|<-15dB 绝对门+β 金标准；裁判=理想级联）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`arm_len_mm`
- **名义参数**：`w_mm`=1.1134，`arm_len_mm`=20.0

## branchline

- **抽取判据**：S11/S21/S31/S41 @ MSLPort 1-4（单激励 9 列 CSV；整 4×4 由 excite_port=1..4 进程隔离轮转装配 → .s4p，#208；2026-09-16 前 port4 为 PML 端接不提取）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`arm_len_mm`、`series_w_mm`、`shunt_w_mm`
- **名义参数**：`arm_len_mm`=20.5，`series_w_mm`=1.87，`shunt_w_mm`=1.11

## branchline_2sect

- **抽取判据**：全 S 矩阵 4×4 @ .s4p（excite_port 轮转 4 run，#208）。裁判=偶/奇模二分频响 branchline_2sect_sparams（Pozar §7.5 推广 + Levy & Lind 1968）：f0 处 \|S21\|=\|S31\|=−3.01dB、S11=S41=0；两节 ≥ 单节带宽（±1dB 均分 35.0% vs 25.8%）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_main_mm`、`w_out_mm`、`w_mid_mm`、`sect_len_mm`、`branch_len_mm`、`w_feed_mm`
- **名义参数**：`w_main_mm`=1.1117，`w_out_mm`=0.162，`w_mid_mm`=0.6024，`w_feed_mm`=1.1117，`sect_len_mm`=17.7338，`branch_len_mm`=18.4304
- **拓扑**：两节分支线 3dB 正交耦合器（C4 族，Pozar 经典点）：主线 Z_a=Z0 两节 + 外支臂 (1+√2)Z0 + 中支臂 √2·Z_a²/Z0（单参数族，main_z_ratio 可调）；四角 50Ω 馈线沿 x 引出，P1 左上输入/P2 右上直通/P3 右下耦合/P4 左下隔离
- **冒烟注记**：真机未跑（followUp）：预期引擎偏差项=T 结不连续性+拐角（理想闭式不含），冒烟对照 branchline 单节同门

## cline_coupler

- **抽取判据**：全 S 矩阵 4×4 @ .s4p（excite_port 轮转 4 run，#208 进程隔离；同 ratrace footer 9 列单激励 CSV）。裁判=偶/奇模频响 coupled_line_coupler_sparams（Pozar §7.6 闭式）：f0 处 \|S31\|=C、S21=−j√(1−C²)、S11=S41=0（同步极限）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`gap_mm`、`coupled_len_mm`、`w_feed_mm`
- **名义参数**：`w_mm`=0.9243，`gap_mm`=0.082，`coupled_len_mm`=18.1469，`w_feed_mm`=1.1117
- **拓扑**：耦合线定向耦合器（后向波，C4 族）：两条 λ/4 平行耦合线（KJ (w,s) 反解）+ 四条 50Ω 馈线外推+横向搭接段（同心直连短路）；1=输入/2=直通（线 A 远端）/3=耦合（线 B 近端，与输入同侧）/4=隔离
- **冒烟注记**：真机未跑（followUp）：非同步残差预期 S41≈−23dB/S11≈−33dB（定向性 ≈13dB，微带耦合线固有，openems_templates §C4 段首口径 1），冒烟按此判读；理想同步极限 \|S31\|=−10.000dB

## coax_waveguide_transition

- **抽取判据**：S 参数 @ LumpedPort 1（探针基同轴截面集总桥，Z_ref=R=50Ω 实常数）+ RectWGPort 2 （解析 TE10，Z_ref=ZL=k·Z0/β 色散）；跨口传输含 sqrt(ZL1/ZL2) 阻抗校正（官方 wiki Coax-to-Waveguide 教程口径）；HFSS 仲裁=Ph3 窗
- **基板**：er=1.0，h_mm=0.0
- **参数**：`a_mm`、`b_mm`、`l_wg_mm`、`wg_t_mm`、`pin_len_mm`、`pin_r_mm`、`port_h_mm`、`backshort_mm`
- **名义参数**：`a_mm`=22.86，`b_mm`=10.16，`l_wg_mm`=30.0，`wg_t_mm`=2.0，`pin_len_mm`=5.588000000000001，`pin_r_mm`=0.5，`port_h_mm`=1.0，`backshort_mm`=9.926779802778025，`er`=1.0，`h_mm`=0.0
- **拓扑**：波导-同轴探针过渡：WR-90 矩形厚壁腔（a×b×l_wg，四壁+背短路板厚 wg_t，封闭 PEC 腔）+ 探针柱经底壁伸入腔内（针轴平行 TE10 E 场沿 y，针中心距背短路内侧面 backshort=λg/4）；port1=探针基 LumpedPort 集总桥（R=50Ω），port2=腔端面 RectWGPort 解析 TE10；z 轴双端 PML_8、x/y MUR
- **冒烟注记**：未冒烟（离线审计过，#212，test_coax_wg_template）；近似级别如实登记：①探针柱 为矩形盒阶梯化（官方教程亦为矩形截面 pin，非圆柱）；②同轴连接器理想化为探针基 集总桥（官方 Python 教程口径，不含连接器体/介质填充）；③S21 跨口阻抗校正按 wiki 教程 sqrt(ZL1/ZL2) 一阶口径；④真机冒烟与 HFSS 仲裁=Ph3 窗（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ0/50（空气口径，官方 base 级）；NEAR=base/4；全部壁面/探针特征站线（±a/2、±(a/2+wg_t)、±b/2、 ±(b/2+wg_t)、±pin_r、−b/2+port_h、−b/2+pin_len、背短路面、探针 z 缘、端口 校准面）显式入网（#198）+ 全轴 1µm 近重合去重（#152）；背面空气余量 6mm≈λ0/5（封闭腔无外漏场）

## coil_nfc

- **抽取判据**：S11 @ LumpedPort 1（外圈馈隙桥接，R=50Ω CalcPort 同参考；f0 谷=串联谐振 1/(2π√(L_self·C_tune))，C_tune=外匹配电容不进几何，fake 同源 47pF 口径）
- **基板**：er=4.4，h_mm=1.6
- **参数**：`n_turns`、`d_out_mm`、`w_mm`、`s_mm`、`gap_mm`、`h_mm`
- **名义参数**：`n_turns`=7，`d_out_mm`=38.2988，`w_mm`=0.5，`s_mm`=0.5，`gap_mm`=0.4，`h_mm`=1.6，`er`=4.4，`tan_d`=0.02
- **拓扑**：NFC/WPC 平面线圈：FR4 类基板（无地平面）+ 阶梯方螺旋（外圈馈隙=端口位）+ 中跳线桥（抬高 z 越过螺旋，lange air-bridge 同法）把内端引出到外端端口 对侧——单导体通路，端口跨馈隙；全域 MUR（无地，辐射口径；13.56MHz 电小， 近场主导）
- **冒烟注记**：未冒烟（离线审计过，#212，test_coil_nfc_template）；真机发射面=13.56MHz FDTD 预算审计（runs/df7_nfc/criteria.md §e：小时-天/点量级，建议几何等比 缩放阶梯研究后由主代理决定），本批零发射
- **网格注记**：mesh_resolution_mm=网格 base 覆盖；0=自动 max(w,s,gap)/4（MQS 频段几何驱动 网格，禁 λ_sub/50 口径——13.56MHz 下 λ_sub/50≈250mm 装不下线圈）；螺旋缘/ 馈隙缘/桥面/过孔棱精确入网（#198）；NEAR≤min(s,gap)/3 渲染期守卫（#266）； 全轴 1µm 近重合去重（#152）；端口盒三向 ≥NEAR 厚、边全入网（#174/#283）

## combline

- **抽取判据**：S11/S21 @ MSLPort 1-2（梳状带通：带内回波纹波 + 带外抑制；裁判=并联谐振 J 倒置器链 c3_circuit_sparams，同步 TEM 极限对照 C13 coupling_matrix_response 互证，实测 max\|ΔS21\|=0.00045dB）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`order`、`w_mm`、`res_len_mm`、`gaps_mm`、`feed_len_mm`、`c_load_pf`
- **名义参数**：`order`=3，`w_mm`=1.1117，`res_len_mm`=8.4238，`gaps_mm`=[0.1393, 0.9291, 0.9291, 0.1393]，`feed_len_mm`=55.7881，`c_load_pf`=1.2732
- **拓扑**：梳状带通（§C3 滤波器族 II，MYJ Ch.10 口径）：N 根缩短棒平行排列，接地端同端（底端全部过孔 r=0.15mm），顶端各接 LumpedElement 装载电容（CSXCAD caps=True，ny=2 即方向索引 z——shunt 对地惯用法，电压沿 z 跨基板全隙、端帽板落在 z=0/z=H_SUB 既有 PEC 面；C=c_load_pf；谐振条件 cot θr=ω0·C·Z_r 定缩短长度）；双 50Ω 馈线缝耦合自 y=−BOARD 板边引入（单轴 PML）
- **冒烟注记**：真机 openEMS 冒烟后置（followUp，LumpedElement 电容真机行为待冒烟实证；循 coupled_bpf NrTS PARTIAL 先例），本项全程离线验收

## coupled_bpf

- **抽取判据**：S11/S21 @ MSLPort 1-2（平行耦合 BPF：带内回波纹波 + 带外抑制；裁判=电路级联 coupled_bpf_circuit_sparams，同步 TEM 极限对照 C13 coupling_matrix_response 互证）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`order`、`w_feed_mm`、`widths_mm`、`gaps_mm`、`res_len_mm`、`feed_len_mm`
- **名义参数**：`order`=3，`w_feed_mm`=1.1117，`widths_mm`=[0.8952, 1.0956, 1.0956, 0.8952]，`gaps_mm`=[0.1286, 0.7794, 0.7794, 0.1286]，`res_len_mm`=35.5107，`feed_len_mm`=24.4893
- **拓扑**：平行耦合（边缘耦合）带通（WP2.3 Tier1 BPF 族锚，Pozar §8.6.2）：N 个 λg/2 半波谐振器沿 y 阶梯排列（相邻平行、y 向错位 λg/4），N+1 个耦合段（馈-腔、腔-腔×(N−1)、腔-馈，段长逐端 Δl 修正）；输入/输出 50Ω 馈线在 y=∓BOARD 板边（单轴 PML）
- **冒烟注记**：真机 runs/coupled_bpf_smoke/（2026-09-12）：β 金标准 PASS，响应受 NrTS 截断不可判读，如实 PARTIAL

## coupled_line

- **抽取判据**：S11/S21/S31 @ MSLPort 1-3（耦合度）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`coupled_len_mm`、`line_w_mm`、`gap_mm`
- **名义参数**：`coupled_len_mm`=20.0，`line_w_mm`=1.0，`gap_mm`=0.5

## cps

- **抽取判据**：S11/S21 @ LumpedPort 1-2（共面带差分直馈，R=闭式 Z0：带内 \|S11\| 深谷=Z0 锚；εeff 锚=S21 解缠相位斜率——LumpedPort 无 β 属性，β 金标准如实降级）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`gap_mm`、`line_len_mm`
- **名义参数**：`w_mm`=2.95，`gap_mm`=0.5，`line_len_mm`=40.0

## cpw

- **抽取判据**：S11/S21 @ CPWPort 1-2（均匀共面线：S21 相位斜率→εeff）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`gap_mm`、`line_len_mm`
- **名义参数**：`w_mm`=0.849，`gap_mm`=0.2，`line_len_mm`=40.0

## diplexer

- **抽取判据**：S11/S21/S31 @ MSLPort 1-3 单激励 7 列 CSV（port1=antenna 公共口激励，port2=LP/port3=HP 探针；3 端口轮转 footer，#208 口径）。裁判=core.diplexer_compose 同参精确复算 + diplexer_verdict 四门：能量守恒（幺正性恒等式 ≤1e-8）、交越=fc（\|S21\|=\|S31\| 交点 ±tol）、通带 \|S11\|、互补亏缺； CR 一阶对闭式锚 S11≡0/\|S21\|²+\|S31\|²≡1/交越精确 fc
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_feed_mm`、`l_lpf_nh`、`c_hpf_pf`
- **名义参数**：`w_feed_mm`=1.1134，`l_lpf_nh`=3.1831，`c_hpf_pf`=1.2732
- **拓扑**：Diplexer LP+HP T 结（TA-5，一阶常阻互补对偶 CR 型）：输入 50Ω 馈线（port1=antenna， −BOARD 板边）→ 微带 T 结 → LPF 臂（+x：50Ω 短段+LumpedElement 串联 L 断口桥接+50Ω stub 至 +BOARD=port2）与 HPF 臂（−x 镜像，串联 C=port3）；集总元件 atten_pi 串臂同法（ny=0 断口桥接）； 全金属同层零交叉
- **冒烟注记**：未冒烟（离线审计过，#212，test_diplexer_ridged_templates）；近似级别如实登记：①理想集总 LumpedElement（无寄生 L/C/自谐振——2.5GHz 下 nH/pF 级元件自谐振 ≫fc，PCB 集总现实口径如实登记）； ②元件间 50Ω 连接线/馈线 stub 电长度寄生不进闭式裁判（qwt 节间阶梯同口径，元件紧凑排布使寄生段电小）； ③≥2 阶对固有回损地板使其判读门不可判读——v1 取一阶 CR 对（20dB/dec 选择性为一阶固有）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50（官方口径）；全盒缘（馈线/T 条/臂带缘/元件断口缘）+ 端口 junction 精确入网（#198）；全轴 1µm 近重合去重（#152）；端口面贴 PML_8 域边（#154 前节）；#347 输入段测量面-激励分离守卫

## dipole

- **抽取判据**：S11 @ LumpedPort 1（#194 官方口径重写：底探针馈电，无 MSL 端口）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`dipole_len_mm`、`dipole_w_mm`、`gap_mm`
- **名义参数**：`dipole_len_mm`=58.0，`dipole_w_mm`=2.0，`gap_mm`=2.0

## embedded_ms

- **抽取判据**：S11/S21 @ MSLPort 1-2（嵌入式微带均匀线：S21 相位斜率→εeff，β 金标准 mline 同口径；\|S11\| 显著非零=端口/网格判废信号）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`h2_mm`、`line_len_mm`
- **名义参数**：`w_mm`=1.0014，`h2_mm`=0.254，`line_len_mm`=40.0，`h_mm`=0.508，`er`=3.66，`tan_d`=0.0037
- **拓扑**：嵌入式微带均匀段（TA-11）：地面=z=0 域 PEC 底界，基板 [0,H_SUB]， 零厚条带 z=H_SUB，同 εr 覆盖层 [H_SUB, H_SUB+H2]（嵌埋介质单材料盒，均匀 嵌埋电气精确），其上开放（top MUR）；双 MSLPort 板边入（端口面贴 PML）
- **冒烟注记**：离线审计先行（#212，test_ta_wave_c_templates）；内核数字裁判=FD 四锚 （h2→0 退化微带跨族互检/thick overlay εeff→εr/εr=1 精确同解/括号单调， test_ta_wave_c_templates 钉）；近似级别如实登记：准静态/零厚带/PEC 地/无色散， 设计链=FD 裁判反演（Wadell 闭式系数不可达——core/embedded_line docstring 如实 账）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；条带缘 x 向 + 线两端 y 向精确入网（#198）；z 网格=基板 _sub_cells 层+覆盖层 _sub_cells 层 +AIR_TOP（条带 z 面恰在网格线，#212 审计①）

## fgcpw

- **抽取判据**：S11/S21 @ CPWPort 1-2（有限地共面波导均匀线：S21 相位斜率→εeff，β 金标准
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`gap_mm`、`gnd_mm`、`line_len_mm`
- **名义参数**：`w_mm`=4.3466，`gap_mm`=0.2，`gnd_mm`=4.0，`line_len_mm`=40.0，`h_mm`=0.508，`er`=3.66，`tan_d`=0.0037
- **拓扑**：有限地共面波导 FGCPW 均匀段（TA-9，真 CPW 口径）：基板上表面中心条带+两有限宽接地（全长度含端口段）， 无底地（基板下方空气、域底 MUR——cps 口径；与 cpw 模板 CPWG 强制底地相区别，registry CPW 段注释自证）；双 CPWPort 板边入（端口面贴 PML）
- **冒烟注记**：离线审计先行（#212，test_ta_wave_a_templates）；内核数字裁判=FD 裁判两精确极限（k=1/√2 空气线 Z0=30π、h→∞ 半空间 εeff=(1+εr)/2）+G-N/skrf 第三方对拍（设计点 ≤1% 带）；G-N 文献闭式系统偏差如实入账（名义点 εeff −6.6%/Z0 −3.6%，#302 同族，设计链以 FD 为准）； 近似级别：准静态/零厚金属/无损；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；六条带/地缘（±w/2、±(w/2+gap)、±(w/2+gap+gnd)）+缝中线 x 向精确入网（#198/cpw pt4 同源）+线两端 y 向；基板 z 8 层（CPW/槽下场族 G3 分档）

## gysel

- **抽取判据**：S11/S21/S31 @ MSLPort 1-3 + S23 第二激励（输出互隔离，标准双激励 footer 同 wilkinson）。裁判=理想 Gysel 环 S 闭式（#206 理论核验轮，skrf 六段线+双负载装配 @f0）：均分 -3.01dB 同相、全端口匹配、P2↔P3 互隔离
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_arm_mm`、`w_feed_mm`、`arm_len_mm`、`iso_len_mm`
- **名义参数**：`w_arm_mm`=0.6035，`w_feed_mm`=1.1134，`arm_len_mm`=18.162，`iso_len_mm`=17.75
- **拓扑**：Gysel 高隔离功分器（1975 六节 λ/4 环，P2⑪ L-jog 等长拓扑重设计 2026-09-16）：P1—70.7Ω λ/4 臂—P2/P3；P2/P3—50Ω λ/4 隔离线（竖直段 YJ=iso_len−jog + 顶端横移 jog=\|arm_len−iso_len\| 保电长度）—Δ1/Δ2（x=±iso_len，各接 50Ω LumpedElement 端接，隔离负载外置）；Δ1—50Ω λ/2 桥带（跨度 2·iso_len=λ/2 精确，中点开路）—Δ2。矩形旧版（Δ 在角部、桥带继承 2·arm_len，+2.32% 二阶偏差）为历史口径（#211）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；三带缘+jog 顶边带缘+Δ 节点负载盒边精确入网（#198）；jog 横移 0.412mm ≈1 网格胞（0.4mm 档），Δ 缘与竖边带缘最小间距=jog≫1µm（#152 守卫）

## hairpin

- **抽取判据**：S11/S21 @ MSLPort 1-2（发夹线 BPF：带内回波纹波 + 带外抑制；裁判=C13 耦合矩阵闭式 coupling_matrix_response）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`order`、`w_mm`、`arm_len_mm`、`arm_gap_mm`、`gap_mm`、`tap_frac`
- **名义参数**：`order`=3，`w_mm`=1.1117，`arm_len_mm`=36.7799，`arm_gap_mm`=3.0，`gap_mm`=1.1328，`tap_frac`=0.398159
- **拓扑**：发夹线带通（WP2.3 Tier1 滤波器族）：N 个 λg/2 半波谐振器折成 U 形沿 x 并排，相邻外臂平行耦合（缝 gap_mm）；输入/输出为 50Ω 抽头馈线（T 形，板边 x=∓BOARD 至首/末谐振器外臂，抽头位置 tap_frac 自开路端计）
- **战役精算能力**：受限；同向拓扑结构性受限：相邻臂开路端对齐→电/磁耦合反号相消，k_EM 非单调（真机 5 点图谱极大 0.0155@gap0.65）≪ k_KJ=0.0515（真机比值上限 ≈0.30）；FBW5% 名义（k=0.0515）落在可达域 [0.0133, 0.0155] 之外，且 Q_e·k=0.879 恒等式需 Q_e≥57＞抽头上限 ~47-50——参数空间内无自洽 Chebyshev 设计点，名义 gap 不可给出

## hairpin_alt

- **抽取判据**：S11/S21 @ MSLPort 1-2（交替取向发夹线 BPF：带内回波纹波 + 带外抑制；裁判=C13 耦合矩阵闭式 coupling_matrix_response，gap→k 纯 KJ）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`order`、`w_mm`、`arm_len_mm`、`arm_gap_mm`、`gap_mm`、`tap_frac`
- **名义参数**：`order`=3，`w_mm`=1.1117，`arm_len_mm`=36.7799，`arm_gap_mm`=3.0，`gap_mm`=1.1328，`tap_frac`=0.398159
- **拓扑**：交替取向发夹线带通（TODO 0dk 根修变体）：N 个 λg/2 半波谐振器折成 U 形沿 x 并排，奇数序谐振器上下翻转（弯带/开路端 y 逐腔轮替），相邻臂开路端交替 → 电/磁耦合同号叠加；相邻外臂平行耦合（缝 gap_mm）；输入/输出为 50Ω 抽头馈线（板边 x=∓BOARD 至首/末谐振器外臂，抽头位置 tap_frac 各自开路端计，末腔翻转时输出抽头自 y1 向下）。可选布局选项 orientation=alternating\|same（缺省 alternating；same=同网格同向对照，不进 params）
- **战役精算能力**：受限；真机 k(gap) 图谱未复跑：交替取向 k_EM(gap) 单调性与比值门（c=k_EM/k_KJ∈[0.6,1.2]）均未实测（预声明门见 scripts/hairpin_q_extract.HAIRPIN_ALT_KGAP_GATE）；c_f0=1.0370 / c(τ) 沿用同向标定先验，hairpin_alt 未独立复标

## helix

- **抽取判据**：S11 @ LumpedPort 1（法向模方螺旋：判据=Zin 电抗容→感上穿 f_x，R 电小失配谷深不适用；旧 λ0/4 口径真机 f_x 3.31GHz，HFSS 同几何仲裁 3.2675GHz 偏差 1.44% AGREE → k_helix=1.3615 定版，见 smoke_note）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`helix_d_mm`、`helix_turns`、`helix_pitch_mm`、`helix_w_mm`、`feed_gap_mm`
- **名义参数**：`helix_d_mm`=3.0，`helix_turns`=2，`helix_pitch_mm`=9.2587，`helix_w_mm`=0.6，`feed_gap_mm`=2.0
- **拓扑**：螺旋（§10.3 C1）：单导线 staircase 方螺旋（每圈 4 直段各 1/4 螺距上升 + 角部竖板，无双并联回路），首圈 A 段即馈口顶，总线长 4·d·N + N·p = k_helix·λ0/4（k_helix=1.3615 HFSS 仲裁）；馈口=地面 z=0 → 角 A 柱底 LumpedPort；无介质板（PEC 地面悬空导体）
- **冒烟注记**：真机 runs/antenna2_smoke/helix（2026-09-14）FAIL：S11 ≤−1.22dB；Zin 全带容性 X∈[−156,−44]Ω 且随 f 单调升 → 谐振在 2.9GHz 之上（与段首"慢波使谐振更低"预期相反，λ0/4 总线长口径高估电长度）；R=1.8~6.2Ω 与电小天线 395(h/λ)²≈2Ω 一致——即便谐振也对 50Ω 失配，S11 谷深判据不适用，应改判电抗过零。扩带（2026-09-16，runs/antenna2_smoke/helix_wide，1.5-4.5GHz，solve 173s）FOUND：f_x=3.3146GHz R=9.47Ω（首个容性→感性上穿）。**HFSS 同几何仲裁（2026-09-17 收尾批，scripts/hfss_helix_arbitration.py，runs/helix_arbitration）AGREE**：真实三维盒几何（t*_d 段为 0.6×3.0×0.9 金属块，前六轮 sheet 映射把它压成薄板断了 C→D→A 电流路径 → 全带容性 UNDECIDABLE，几何修复后）f_x_hfss=3.2675GHz R=8.74Ω vs openEMS 3.3146（自动/0.35mm 网格、16.7/50mm 域三重稳健 3.29–3.32）偏差 1.44% ≤5% ⇒ k_helix=f_x(HFSS)/2.4=1.3615 进设计式（K_HELIX 单源），helix_pitch_mm 3.6142→9.2587（element_top 9.23→20.52mm）；新名义真机验证 runs/antenna2_smoke/helix_knew（openEMS 1.9–2.9GHz）FOUND f_x=2.2039GHz R=17.51Ω、S11 min −6.74dB@2.275——落 f0±12% 窗内但偏低 −8.2%：单点 k 修正隐含 f∝1/wire，螺距 3.6→9.3mm 改变慢波因子致一阶外推过冲；割线二次迭代（两点 (31.23mm,3.3146)/(42.52mm,2.2039) → wire≈40.5mm、k≈1.30、pitch≈8.26）须再经 HFSS 仲裁方可进设计式（#190，followUp）。

## hmsiw

- **抽取判据**：LumpedPort z 桥×2 端面口径（R=闭式 Z_PV=2h·Z_TE/w_eff，CalcPort 同参考）： β/εeff 主判=S21 解缠相位斜率÷port_beta.csv 实测 plane_dist（cps/siw 同契约，LumpedPort 无 β 属性）；fc 由带内 φ(f)=−β(f；fc)·L+φ0 单参数拟合对照式 (11) 链（预声明门归真机窗）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`d_mm`、`s_mm`、`line_len_mm`
- **名义参数**：`w_mm`=5.5829，`d_mm`=0.6，`s_mm`=1.0，`line_len_mm`=63.0721，`h_mm`=0.508，`er`=3.66，`tan_d`=0.0037
- **拓扑**：HM-SIW 半模基片集成波导均匀段（TA-8）：基板矩形域，底板=显式零厚板贴 z=0 PEC 底界+单列过孔藩篱 x=+w/2（藩篱止于端口面），开路边 x=−w/2=磁壁（域 MUR 余量 w_eff/2）、顶开放（MUR，无上板——HMSIW 定义性质）；端口=两端面 LumpedPort z 桥（跨介质孔径、R=Z_PV， 端口即终端负载 siw v2 口径）——准 TE0.5 模 fc 由式 (11) 链给出（Lai-Fumeaux 2009 T-MTT 式 (8)-(14)）
- **冒烟注记**：离线审计先行（#212，test_ta_wave_a_templates）；内核数字裁判=论文图面数值锚三方互证（Fig.6/7：fc 4.789/20.746GHz、β(12GHz) 342 rad/m，test_ta_wave_a_templates 钉）；近似级别如实登记：式 (13) 拟合 <2%（论文声明域内）、过孔藩篱离散化未经真机仲裁（siw 经验迁移）、端面 LumpedPort R=Z_PV 对 1/4 余弦场分布的功率-电压近似（siw v1/v2 同族近似级）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；过孔直径 ≥4·NEAR 守卫、孔间缝 ≥1 内部线（siw 同款）、显式近场线 10µm 地板（#349）、端口盒边/开路边/藩篱心线落格（#283， 生成期断言）、基板 z 4 层

## ifa

- **抽取判据**：S11 @ LumpedPort 1（IFA λ/4 窄臂：谷位/谷深；真机 −8.48dB@2.44GHz（+1.7%）PASS，并联型谐振 R_peak≈103Ω 限谷深）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`ifa_arm_mm`、`ifa_w_mm`、`feed_off_mm`
- **名义参数**：`ifa_arm_mm`=18.5515，`ifa_w_mm`=1.0，`feed_off_mm`=2.0
- **拓扑**：IFA（§10.3 C1，PIFA 窄臂退化）：短路板 x∈[−1,0]（z 0→h）+ 臂 z=h 自短路板 −x 向伸出 λ/4 + 馈针=LumpedPort x=−feed_off（顶触臂、底触地，不另画金属针盒）；基板 + z-min PEC 地
- **冒烟注记**：真机 runs/antenna2_smoke/ifa（2026-09-14，去针盒 v2）PASS：S11 −8.48dB @2.44GHz（+1.7%），Zin@谷=103−24jΩ（并联型谐振，馈针 2mm 过耦合限谷深）；与 ifa_v1_pin_short（有针盒）−8.52dB@2.44 逐点一致 ⇒ 针盒无影响、谐振为真。带外 R≈0（1.9GHz −0.11+4.3j、2.9GHz 0.19+3.3j）是无耗短路桩馈结构的正常反应，首判"端口短路→PARTIAL"已证伪

## interdigital

- **抽取判据**：S11/S21 @ MSLPort 1-2（交指带通：带内回波纹波 + 带外抑制；裁判=并联谐振 J 倒置器链 c3_circuit_sparams，同步 TEM 极限对照 C13 coupling_matrix_response 互证，实测 max\|ΔS21\|=0.0104dB）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`order`、`w_mm`、`res_len_mm`、`gaps_mm`、`feed_len_mm`
- **名义参数**：`order`=3，`w_mm`=1.1117，`res_len_mm`=17.082，`gaps_mm`=[0.2263, 1.3567, 1.3567, 0.2263]，`feed_len_mm`=51.459
- **拓扑**：交指带通（§C3 滤波器族 II，Cohn 交指口径）：N 根 λ/4 均匀谐振棒平行排列，接地端交替（奇棒底端过孔/偶棒顶端过孔，r=0.15mm），相邻棒全长缝耦合；双 50Ω 馈线缝耦合自 y=−BOARD 板边引入（gysel 同边先例，单轴 PML）
- **冒烟注记**：真机 openEMS 冒烟后置（followUp，循 coupled_bpf NrTS PARTIAL 先例；真机轨道留队列 openems-real-smoke-bundle 类包），本项全程离线验收

## inverted_ms

- **抽取判据**：S11/S21 @ MSLPort 1-2（倒置微带均匀线：S21 相位斜率→εeff，β 金标准 mline 同口径；\|S11\| 显著非零=端口/网格判废信号）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`h_air_mm`、`line_len_mm`
- **名义参数**：`w_mm`=2.1359，`h_air_mm`=0.508，`line_len_mm`=40.0，`h_mm`=0.508，`h_sub_mm`=0.508，`er`=3.66，`tan_d`=0.0037
- **拓扑**：倒置微带均匀段（TA-7）：金属/介质 z 序相对微带对调——地面=z=0 域 PEC 底界，零厚条带悬于 z=h_air 空气隙顶（基板下表面），基板 [h_air, h_air+h_sub] 上覆、其上开放（top MUR）；双 MSLPort 板边入（端口面贴 PML）
- **冒烟注记**：离线审计先行（#212，test_ta_wave_a_templates）；近似级别如实登记：准静态/零厚带/PEC 地/无色散，设计链=FD 裁判反演（文献闭式不可达——core/inverted_ms docstring 如实账）； 真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；条带缘 x 向 + 线两端 y 向精确入网（#198）；z 网格=空气隙 2 层+基板 _sub_cells 层+AIR_TOP（条带 z 面恰在网格线，#212 审计①）

## isl_shielded

- **抽取判据**：S11/S21 @ MSLPort 1-2（ISL 屏蔽悬置线均匀线：S21 相位斜率→εeff，β 金标准 mline 同口径；\|S11\| 显著非零=端口/网格判废信号）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`g_air_mm`、`h_top_mm`、`d_mm`、`s_mm`、`line_len_mm`
- **名义参数**：`w_mm`=2.4818，`g_air_mm`=0.508，`h_top_mm`=1.016，`d_mm`=0.6，`s_mm`=1.0，`line_len_mm`=40.0，`er`=3.66，`tan_d`=0.0037
- **拓扑**：ISL 屏蔽悬置线均匀段（TA-10，准静态口径如实）：地面=z=0 域 PEC 底界→空气隙 g→基板 [g, g+h_sub]（悬浮）→零厚条带（基板上表面）→空气 h_top→屏蔽顶板（显式零厚板 z=z_wall）；两列过孔藩篱 x=±wall_x 贯通底地与顶板（藩篱止于端口面，hmsiw v2 端面口径）；双 MSLPort 板边入（端口面贴 PML）
- **冒烟注记**：离线审计先行（#212，test_ta_wave_b_templates）；内核数字裁判=三精确极限（对称退化≡_stripline_z0 逐位/εr=1→εeff=1/w→∞ 串联层精确），文献频变闭式不可达如实账（round15 IET 口径，core/isl_line docstring）；近似级别如实登记：准静态/零厚带/PEC 墙/无色散，双半腔非对称一阶误差 O(\|h1−h2\|/D)（模型 wide-limit 与逐径混合差异，h1=h2 点恒等已钉）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；条带缘/藩篱三线对 x 向 + 线两端/每孔三线 y 向精确入网（#198）；过孔直径 ≥4·NEAR、孔间缝 ≥1 内部线（hmsiw 同守卫）、显式近场线 10µm 地板（#349）；基板 z 4 层+空气隙 2 层（z 网格字面与基板盒/条带同源）

## lange

- **抽取判据**：全 S 矩阵 4×4 @ .s4p（excite_port 轮转 4 run，#208）。裁判=四线等效两线偶/奇模频响（Pozar §7.6 Lange 节设计式自洽回代 C/Z0 逐位闭合）：f0 处 \|S21\|=\|S31\|=−3.01dB、S31=+1/√2（耦合同相）、S21=−j/√2、S11=S41=0
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`gap_mm`、`finger_len_mm`、`w_feed_mm`
- **名义参数**：`w_mm`=0.1672，`gap_mm`=0.0386，`finger_len_mm`=18.9712，`w_feed_mm`=1.1117
- **拓扑**：展开型 Lange 电桥（3dB 正交，C4 族）：四指交替并联（网络 A=指1/3、B=指2/4，DC 隔离），air-bridge=抬高薄金属+竖直立柱（同端 A/B 桥错位、两端分置）；外指承馈 P1/P2/P3/P4，等效两线 (Ze4,Zo4)=(120.71,20.71)Ω 精确成立
- **冒烟注记**：真机未跑（followUp）：指缝 38.6µm 小于 0.4mm 审计网格（near 加密入网）；桥缝耦合寄生于理想裁判之外，冒烟按 g=0.076 提示与一阶口径判读

## loop

- **抽取判据**：S11 @ LumpedPort 1（一周长方环，自由空间口径：判据=Zin 电抗过零 f0±12% + 过零处 R≥20Ω，S11 −5dB 次级；旧贴地口径真机 R=0.56Ω 镜像抵消 FAIL，v2 见 smoke_note）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`loop_side_mm`、`loop_w_mm`、`loop_gap_mm`
- **名义参数**：`loop_side_mm`=31.2284，`loop_w_mm`=1.0，`loop_gap_mm`=1.0
- **拓扑**：环形（§10.3 C1，2026-09-16 自由空间改造）：z=0 方环（中心线边 a、带宽 w，顶/左/右全跨含角）+ 底边中央断口 g（馈口位）LumpedPort 跨断口（E 沿 x，dipole 中央馈口同型）；无基板无地：底 MUR + 域 z 向下延 λ0/4（dipole 同款）
- **冒烟注记**：真机 v1 runs/antenna2_smoke/loop（2026-09-14，旧贴地口径 λg/4=18.5515、z=h 贴 PEC 地）FAIL：S11 −0.19dB；Zin 电抗过零 2.3825GHz（−0.7%，谐振长度口径正确）但 R=0.56Ω。归因（像理论，v2 实证）：水平环贴 PEC 地 0.508mm（0.004λ0），镜像反向电流抵消辐射 → R_rad→0。改造（2026-09-16）：自由空间口径（无板无地、底 MUR、域下延 λ0/4、环面 z=0、a=λ0/4=31.2284），判据改电抗过零 f0±12% + 过零处 R≥20Ω（S11 −5dB 次级；一周长环馈阻抗文献 ≈100-200Ω 对 50Ω 固有失配，谷深非谐振判据）。v2 真机 runs/antenna2_smoke/loop_v2（2026-09-16，solve 352s）PASS：Zin 电抗过零 2.6774GHz（+11.6%，端效应窗内）R=112.02Ω（v1 0.56Ω → 112Ω，镜像抵消归因实证；落在文献 100-200Ω 带内），S11 −8.67dB@2.64GHz（次级 −5dB 门过）；判读窗 2.0-2.8GHz 321/321 点全保留（Σ\|S\|² 全带 ≤0.94，无带边伪象）；谐振位 +11.6% 为细带/断口馈电端效应，设计式不预补偿（#190）

## marchand_balun

- **抽取判据**：excite_port∈{1,2,3} 轮转（#208 进程隔离单激励）：P1 MSLPort 线基、P2/P3 LumpedPort 跨槽（抽头基线 RX/SRC 因子修正口径）；S23（隔离）需第二激励；巴伦判据门=BALUN_GATES（不平衡 ≤1dB、RL ≤−10、隔离 ≤−15、\|S21\| ≥−3.5）+ 相位极性约定如实报告
- **基板**：er=3.66，h_mm=1.524
- **参数**：`w_slot_mm`、`x_port_mm`、`h_mm`
- **名义参数**：`w_slot_mm`=1.0，`x_port_mm`=40.0，`h_mm`=1.524，`er`=3.66，`tan_d`=0.0037，`f0_ghz`=2.5
- **拓扑**：Marchand 双槽臂最小族（底层五盒：外地 M1/M2、中条 M3、封口桥 M4/M5 与中条精确共边；顶层微带穿两槽+共享开路支节）：设计级结论=单支节串接已被两引擎互证证伪（四门 FAIL、两跨越点激励不对称、拓扑无隔离机制）——真 Marchand=两节对称耦合段（电路级综合 core/slotline_transitions.synthesize_marchand_two_section，名义点 50Ω→280Ω 差分、C=−7.02dB、(w,s,ℓ)=(1.7616,0.1016,18.4670)mm@h=1.524）；本模板保留作对照口径与判据载体，不作生产巴伦
- **冒烟注记**：真机（a8abe8d）四门 FAIL 两引擎一致：不平衡 2.76/2.64dB、RL −7.4/−5.6、\|S21\| −4.05/−3.93、隔离 −0.55/−5.42、相位 −97°/−31°；幅度三量两引擎差 ≤0.2dB 互证=设计级结论成立。复跑冒烟只作回归对照，验收看两节新设计（followUp 立项）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50、NEAR=base/4；槽内缘/中条/封口桥共边网格线已钉（PEC 共棱连通）

## mline

- **抽取判据**：S11/S21 @ MSLPort 1-2（均匀线：S21 相位斜率→εeff，β 金标准（#162）；\|S11\| 显著非零=端口/网格判废信号）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`line_len_mm`
- **名义参数**：`w_mm`=1.113，`line_len_mm`=40.0

## mmwave_series_array

- **抽取判据**：S11 @ MSLPort 1（1×4 行波串馈贴片阵，链末 50Ω 集总匹配到地：谷位=单元谐振 设计式精确逆 patch_resonance_hj_ghz；方向图走 far_field=True nf2ff，离线 裁判=相位递推闭式主瓣指向 core/array_synthesis.series_feed_beam_direction_ cosine；未真机冒烟）
- **基板**：er=3.0，h_mm=0.127
- **参数**：`n_elem`、`elem_len_mm`、`elem_w_mm`、`link_len_mm`、`feed_w_mm`、`feed_margin_mm`、`h_mm`
- **名义参数**：`n_elem`=4，`elem_len_mm`=0.9271，`elem_w_mm`=1.3589，`link_len_mm`=1.7482，`feed_w_mm`=0.3259，`feed_margin_mm`=3.0，`load_r_ohm`=50.0，`h_mm`=0.127，`er`=3.0，`tan_d`=0.001
- **拓扑**：1×N 串馈毫米波阵（§18.3d C10d）：N 元共线沿 y（x=0 居中，L 沿 y/W 沿 x）， 相邻元以互联线接辐射边中心（互联长 s=自由设计参数，行波渐进相位 βg·s）； MSLPort 自 y=−DOM 入、自画馈段至链首元（feed_margin）；链末 stub+匹配集总 负载到地（R=线 Z0 一阶）——行波阵口径，与 C2 patch_array_series（λg/2 谐振式、链末开路）分族；基板 + z-min PEC 地，y 轴 PML_8
- **冒烟注记**：未冒烟（离线审计过，#212，test_mmwave_series_array_template）；真机发射面= 预算预声明 runs/df7_c10d/criteria.md §d（0.1mm 格 ~3.6e7 cells、 dt~4.8e-14s、NrTS~2.5e4、墙钟数小时～半天/点，发射前以 exec 实测为准）， 本批零发射
- **网格注记**：辐射器件：上方空气隙 λ0/4+、侧向至域界（MUR）；贴片/互联/stub/负载盒缘 精确入网（#198）；渲染守卫：NEAR≤feed_w/3（#266 族，线宽分辨）、 \|MeasPlaneShift−FeedShift\|≥3.9·NEAR（#347）；全轴 1µm 近重合去重（#152）； 端口面贴 PML_8 域边（#154 前节）

## monopole

- **抽取判据**：S11 @ LumpedPort 1（PEC 地面 λ0/4 竖直细带单极子：谷位/谷深；真机 −17.39dB@2.135GHz，端效应 −11%）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`mon_len_mm`、`mon_w_mm`、`feed_gap_mm`
- **名义参数**：`mon_len_mm`=31.2284，`mon_w_mm`=1.0，`feed_gap_mm`=2.0
- **拓扑**：单极子（§10.3 C1 天线族 II）：竖直零厚细带（x 向宽 mon_w，y=0 面）自馈口顶 z=feed_gap 起立 λ0/4；馈口=地面 z=0 → 细带底缘 LumpedPort（patch 底馈探针同型）；无介质板（像理论口径）
- **冒烟注记**：真机 runs/antenna2_smoke/monopole（2026-09-14）PASS：S11 −17.39dB @2.135GHz（设计 2.4，−11.0% 端效应）；Zin 电抗过零 2.110GHz R=37.3Ω（Balanis 36.5Ω 口径吻合）

## ms_array_NxN

- **抽取判据**：无端口（软平面照明散射体）：产物=farfield_cut.csv/farfield3d.csv/ farfield_meta.json/array_meta.json；J2 峰值方向 vs 闭式 φ_mn 指向 ≤3° （真机轨，runs/df6_dp10ms/criteria.md §3）；farfield=总出射场 （镜面反射+赋形波束，判读面在 J2 分解）
- **基板**：er=3.66，h_mm=1.524
- **参数**：`n_x`、`n_y`、`period_mm`、`cell_map`、`h_mm`
- **名义参数**：`n_x`=3，`n_y`=3，`period_mm`=14.9896，`cell_map`=[[{'cell_id': 'ms_patch', 'px_mm': 6.0, 'py_mm': 6.0}, {'cell_id': 'ms_patch', 'px_mm': 7.5, 'py_mm': 7.5}, {'cell_id': 'ms_patch', 'px_mm': 9.0, 'py_mm': 9.0}], [{'cell_id': 'ms_patch', 'px_mm': 7.5, 'py_mm': 7.5}, {'cell_id': 'ms_patch', 'px_mm': 9.0, 'py_mm': 9.0}, {'cell_id': 'ms_patch', 'px_mm': 6.0, 'py_mm': 6.0}], [{'cell_id': 'ms_patch', 'px_mm': 9.0, 'py_mm': 9.0}, {'cell_id': 'ms_patch', 'px_mm': 6.0, 'py_mm': 6.0}, {'cell_id': 'ms_patch', 'px_mm': 7.5, 'py_mm': 7.5}]]，`h_mm`=1.524，`er`=3.66，`tan_d`=0.0037
- **拓扑**：有限 N×N 反射阵（ms_patch 单元平铺）：接地基板（z 底 PEC 边界，地连续 由边界构造性保证）+ cell_map 逐单元贴片表；上方 λ0/4 空气隙软激励平面 照明（exc_type=0 全口径，官方 PPW 教程口径，法向入射 E∥x 极化前提）； 侧向 MUR（有限口径，无 PEC/PMC 对壁——那是单胞无限阵技巧）
- **冒烟注记**：离线审计先行（#212，test_metasurface_templates）；真机 solo 单飞 （#246/#261）；J2 真机轨另派
- **网格注记**：mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；全部贴片缘 精确入网；胞缘/邻胞缝 ≥2·NEAR 渲染期守卫；1µm 近重合去重（#152）； 全轴最小网格间距 ≥10µm；演示名义 3×3（审计快档），真机 15×15 预算 （~4×10⁷ cells 小时级/轮，#328 CSXCAD exec 实测口径）见 战役任务书

## ms_cross

- **抽取判据**：S11/S21 @ 双 E 探针对方向求解（soft plane 激励 exc_type=0；探针对=屏两侧 空气区各 2 只全口径 E 线探针，对内距 λ0/16，精确 β=2πf/c 分解 F/B； 波导模拟器≡无限阵@θ=0，E∥x 极化前提；S21 谷=带阻谐振；J3 vs PSSFSS.jl Δf≤0.3GHz 或 ≤5% 属真机轨）。能量门=\|S11\|²+\|S21\|²∈[0.90,1.02]（单模子带 f≤0.95·c/(2b)）。2026-10-01 ge5 同族修复：原全口径 LumpedPort 电阻片= 测量面并联 Z0 负载，能量预算破损（runs/ge5_msjcross/audit.md §E）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`arm_len_mm`、`arm_w_mm`、`period_mm`、`h_mm`
- **名义参数**：`arm_len_mm`=4.91，`arm_w_mm`=0.982，`period_mm`=11.9917，`h_mm`=0.508，`er`=3.66，`tan_d`=0.0037
- **拓扑**：FSS 带阻十字偶极子单元：基板顶零厚正交双十字臂（x 臂=受激臂，y 臂= 正交极化对偶臂；金属偶极子 E∥臂耦合，无需槽缝族的方向旋转）；单胞 PEC/PMC 对壁域（x 对壁 PEC / y 对壁 PMC，TEM 平面波）；屏两侧 λ0/4 空气区各置双 E 探针对（自由悬浮无源）+ z 底 MUR 上方 soft plane 激励面
- **冒烟注记**：离线审计先行（#212，test_metasurface_templates）；带阻谐振闭式互证 （λ0/2√εeff 口径，test_metasurface_lut）；真机波导模拟器 smoke（空波导 EN 标定+真屏带阻谷+裁判对拍）判据 runs/ge5_msfam/criteria.md §2
- **网格注记**：mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；臂缘精确入网 +邻臂尖缝 3+ 中点入网（#311）；NEAR≤邻臂尖缝/3 渲染期守卫（#266）； 全轴最小网格间距 ≥10µm

## ms_jcross

- **抽取判据**：S11/S21 @ 全口径集总片端口 1-2（R=η0，CalcPort 同参考；波导模拟器 ≡无限阵@θ=0，E∥x 极化前提；S21 峰=带通——JC 缝互联孔径谐振； J3 vs PSSFSS.jl Δf≤0.3GHz 或 ≤5% 属真机轨）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`slot_len_mm`、`slot_w_mm`、`stub_len_mm`、`period_mm`、`h_mm`
- **名义参数**：`slot_len_mm`=4.91，`slot_w_mm`=0.491，`stub_len_mm`=2.455，`period_mm`=11.9917，`h_mm`=0.508，`er`=3.66，`tan_d`=0.0037
- **拓扑**：FSS 带通 Jerusalem cross 缝单元：零厚金属屏（胞面减「主缝+4 端枝」互联 孔径的补集盒分解，ms_jcross_metal_boxes 单源）+ 主缝端 4 枝端加载； 单胞 PEC/PMC 对壁域（x 对壁 PEC / y 对壁 PMC，TEM 平面波）；屏两侧 λ0/4 空气区各置全口径电阻片（下片激励、上片接收）；z 底 MUR
- **冒烟注记**：离线审计先行（#212，test_metasurface_templates）；EC 自洽钉（shunt 并联 LC 峰=f0，shunt 串联 LC=f0 谷即拓扑反接）在 test_metasurface_lut； 真机带心修正（openEMS LUT 一轮）归 P3
- **网格注记**：mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；缝缘精确入网 +屏缘缝 3+ 中点入网（#311）；NEAR≤最小屏缝/3 渲染期守卫（#266）； 孔洞补集盒逐面入网（#174 激励体积铁律）；全轴最小网格间距 ≥10µm

## ms_patch

- **抽取判据**：S11 @ 双 E 探针对反射分解（soft plane 激励 exc_type=0；探针对=贴片上方空气区 2 只全口径 E 线探针，对内距 λ0/16，精确 β=2πf/c 分解 F/B 后 _WgProbePairRefl 对调 uf——入射=−z 照明波、反射=+z 回波，footer 契约/S 列 schema 不变， _port2=_port1 别名 S21 列≡S11）。波导模拟器≡无限阵@θ=0，E∥x 极化前提； \|S11\|≈1 的 argΓ 逐 px 入反射相位 LUT（探针面去嵌相位常数项不进扫 px 差分）； 健康判据=\|Γ\| 线性域 ≈1（空波导标定 EN=\|Γ\|²≈1.0 平坦）。无耗接地结构幅度 读出 «1 = 读出判废信号。（2026-10-01 ge5 ms_patch 读出修复：原全口径 LumpedPort 电阻片=测量面并联 Z0 负载，反射相位为片负载 Möbius 像， runs/ge5_msjcross/audit.md §D/E）
- **基板**：er=3.66，h_mm=1.524
- **参数**：`px_mm`、`py_mm`、`period_mm`、`h_mm`
- **名义参数**：`px_mm`=8.5406，`py_mm`=8.5406，`period_mm`=14.9896，`h_mm`=1.524，`er`=3.66，`tan_d`=0.0037
- **拓扑**：反射阵方贴片单元：接地基板（z 底 PEC 边界）+ 零厚方贴片；单胞方形域 x 对壁 PEC / y 对壁 PMC（TEM 平面波，官方 Parallel Plate Waveguide 教程 口径）；贴片上方 λ0/4 空气区置双 E 探针对（自由悬浮无源）+ 探针对上方 soft plane 激励面，域内零电阻片
- **冒烟注记**：离线审计先行（#212，test_metasurface_templates）；波导模拟器扫描战役 （粗 21+细 41 点）发射面见 战役任务书；读出修复后重扫 见 runs/ge5_j2fb/（J2 fallback 战役段②）；J1c 相位覆盖 ≥300° 与 J4 HFSS Floquet 锚属真机轨
- **网格注记**：mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；贴片缘精确入网 +胞缘缝 3+ 中点入网（#311）；NEAR≤最小胞缘缝/3 渲染期守卫（#266）； 全轴最小网格间距 ≥10µm

## ms_ring_patch

- **抽取判据**：S11 @ 双 E 探针对反射分解（soft plane 激励 exc_type=0；探针对=贴片上方空气区 2 只全口径 E 线探针，对内距 λ0/16，精确 β=2πf/c 分解 F/B 后 _WgProbePairRefl 对调 uf——入射=−z 照明波、反射=+z 回波，footer 契约/S 列 schema 不变， _port2=_port1 别名 S21 列≡S11；与 ms_patch 段①修复同族读出，空波导标定 EN≈1.0+闭式相位 0.19° 实证 runs/ge5_j2fb/stage2/smoke_report.json）。 波导模拟器≡无限阵@θ=0，E∥x 极化前提；\|S11\|≈1 的 argΓ 逐 patch_px 入反射 相位 LUT；健康判据=\|Γ\| 线性域 ≈1
- **基板**：er=3.66，h_mm=1.524
- **参数**：`patch_px_mm`、`period_mm`、`h_mm`
- **名义参数**：`patch_px_mm`=8.5406，`period_mm`=14.9896，`h_mm`=1.524，`er`=3.66，`tan_d`=0.0037
- **拓扑**：双谐振反射阵单元：接地基板（z 底 PEC 边界）+ 零厚方环（外边 ring_outer=void+2·ring_w，内空腔 void=0.4λ0，环宽 λg/40）+ 环心方贴片 （边长=LUT 扫描变量）；单胞方形域 x 对壁 PEC / y 对壁 PMC（TEM 平面波）； 贴片上方 λ0/4 空气区置双 E 探针对（自由悬浮无源）+ 探针对上方 soft plane 激励面，域内零电阻片
- **冒烟注记**：离线审计先行（#212，test_metasurface_templates）；段④ J1c 扫描（粗 21 点档 +圆周覆盖门 ≥300°）发射面=runs/ge5_j2fb/stage2/campaign_j2fb.py --template ms_ring_patch
- **网格注记**：mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；贴片缘/环内外缘 精确入网+环-贴片缝与环-胞缝 3+ 中点入网（#311）；NEAR≤最小缝/3 渲染期 守卫（#266）；全轴最小网格间距 ≥10µm

## msl_cpw

- **抽取判据**：S11/S21 @ MSLPort 1 / CPWPort 2（MSL↔CPWG 过渡：双端口 β 金标准（port1→HJ、port2→CPWG 共形映射）+ skrf 两段理想 TL 级联裁判）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_msl_mm`、`w_cpw_mm`、`gap_cpw_mm`、`line_len_mm`、`trans_len_mm`、`r_via_mm`、`via_spacing_mm`、`via_offset_mm`
- **名义参数**：`w_msl_mm`=1.1134，`w_cpw_mm`=0.849，`gap_cpw_mm`=0.2，`line_len_mm`=40.0，`trans_len_mm`=10.0，`r_via_mm`=0.15，`via_spacing_mm`=2.0，`via_offset_mm`=0.5
- **拓扑**：微带↔接地共面波导过渡（WP2.5 Tier 2）：微带直段 → 4 段等分阶梯渐变（线宽线性内插）→ CPW 中心带 + 两侧地（延至板边）+ 双列接地过孔栅栏（地缝合底板 PEC，抑制平行板模）；过渡区居中

## msl_siw_taper

- **抽取判据**：S11/S21 @ MSLPort 1-2（线基：CalcPort ref=50 主口径；port_beta.csv 落双端口 β+引擎自算 ZL（ReadUIData 重读，wstep/mline W3② 法）+测量面间距 plane_dist_m ——line_z0='engine' 线基反演+renormalize 判读旋钮消费，#250/#280）；fc10 主判 =G1' 带内相位拟合 φ=−β_siw(f;fc)·L_siw+(a+b·f)（线性项吸收馈线/锥群延迟， 预声明 runs/df6_a2siwmsl/criteria.md §4）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`d_mm`、`s_mm`、`taper_len_mm`、`siw_len_mm`
- **名义参数**：`w_mm`=12.1317，`d_mm`=0.6，`s_mm`=1.0，`taper_len_mm`=10.5121，`siw_len_mm`=63.0724，`h_mm`=0.508，`er`=3.66，`tan_d`=0.0037
- **拓扑**：MSL 锥形过渡+SIW 直段（Deslandes-Wu 两段论）：50Ω MSL 馈线 → 线性锥（w50→ w_end=Z_PV 微带当宽的阻抗变换器+锥末-SIW 台阶不连续）→ SIW 直段（顶壁显式板 +两列过孔藩篱止于板缘=siw v2 口径+底壁板）；基板填满矩形域，z=0 PEC 底界， 顶界 MUR（MSL 区微带环境）；端口=双 MSLPort（面贴域界 PML_8、端口段=均匀 50Ω 线）
- **冒烟注记**：离线审计先行（#212，test_msl_siw_taper_template）；OE 锚发射面备妥（驱动 scripts/siw_anchor_smoke.py --template msl_siw_taper，发射前置=A1 队列清空 +.oe_collect.lock 空，见 战役任务书）；预声明门与预算见 runs/df6_a2siwmsl/criteria.md §4/§6；R*=14.5402Ω 旋钮（siw v2_criteria.md §2 条件触发项）在 MSL 线基端口下语义废弃——匹配由锥形几何承担，Z_PV 只进 锥末宽度设计式（如实收档，v2 历史档不删）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；全域 NEAR=base/4； 过孔直径 ≥4·NEAR 守卫、孔间缝 ≥1 内部线（#311）、显式近场线 10µm 地板（#349）、 锥缘/板缘/端口边落格断言（#283）、FeedShift/MeasPlaneShift 间距 ≥3.9·NEAR （#347）；基板 z 4 层（TE10 的 E_z 沿 z 均匀，z 分辨非限制项）

## msl_slot_transition

- **抽取判据**：P1 MSLPort（微带线基：CalcPort 自算 Z_ref(f)/β(f)）激励，S11=uf_ref/uf_inc；P2 LumpedPort 跨槽 R=槽线 Z0（并联抽头拓扑（#250），S21 判据按 tap_receive_factor_db 修正、原始值并列如实；β_slot 双行波拟合对照闭式（信息门 ≤5%）
- **基板**：er=3.66，h_mm=1.524
- **参数**：`w_slot_mm`、`x_port_mm`、`h_mm`
- **名义参数**：`w_slot_mm`=1.0，`x_port_mm`=40.0，`h_mm`=1.524，`er`=3.66，`tan_d`=0.0037，`f0_ghz`=2.5
- **拓扑**：Roberts/Knorr 过渡（双层板）：底层地板开槽（槽开口向 −x 直入 PML，+x 封口=λg'/4 短路臂），顶层微带沿 y 跨槽后延伸 λg_m/4−Δl 开路支节（C6 2026-09-22 符号修正：端效应惯例=物理长缩短，Pozar eq.4.23）（跨越点虚短路/虚开路机理，Knorr 1974/Schuppert 1988）；MSLPort 段内移 14·BASE（H4：段⊂PML_8 致非物理已根治）
- **冒烟注记**：真机（a8abe8d）：openEMS \|S11\|@f0 −19.9/带内 max −10.43dB（匹配门 PASS）、超额损耗 1.05dB 贴门；HFSS β=66.55 对闭式 −1.0%、带内 −9.55dB 贴门、IL 1.37dB FAIL——判 PASS 需结区优化（渐变槽/径向短路盘），复跑按 TRANSITION_GATES 预声明门判读
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50、NEAR=base/4；封口 SEAM 搭接（×NEAR 不关槽方向）、全部盒缘入网

## nway_wilkinson

- **抽取判据**：全 S 矩阵 5×5 @ .s5p（进程隔离激励轮转 5 run，#208 口径推广；openems_rotation n_ports 参数化；port1=输入、port2..5=输出 x=∓(XA1±XA2)）。裁判=内核 synthesize_nway_wilkinson(tree) 阻抗级：@f0 均分 −6.02dB（1/4 功率）、全端口匹配 \|S11\| 深谷、输出对隔离（每级 R=2·Z0 经典 2-way 单元级联保证）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_arm_mm`、`w_feed_mm`、`arm_len_mm`、`iso_r_ohm`
- **名义参数**：`w_arm_mm`=0.6035，`w_feed_mm`=1.1134，`arm_len_mm`=18.1624，`iso_r_ohm`=100.0
- **拓扑**：N-way Wilkinson 功分器（TA-4，树形 N=4）：输入馈线（port1，−BOARD 板边）→ 一级 T 叉（双 λ/4 臂 √2·Z0，x 向并列间距 G1=9mm，wilkinson GAP 口径）→ 50Ω 支线 → 二级双 T 叉（各叉臂间距 G2=5.5mm）→ 四路 50Ω 输出馈线（port2..5，+BOARD 板边）；隔离电阻 R=2·Z0 各臂端面跨接（LumpedElement ny=0，共 3 支）；全金属同层零交叉。拓扑选择：内核 star 分支（Pon 1961 浮点节点）单层 N≥3 不可布（浮点节点/Δ 环闭合路径必与边界馈线交叉）——渲染取 内核 tree 分支（阻抗级同源），N=2 与 wilkinson 模板同解、N≥8 超轮转管线规模（渲染守卫拒 n_way≠4）
- **冒烟注记**：未冒烟（离线审计过，#212，test_sicl_nway_templates）；近似级别如实登记：①λ/4 臂窄带理想口径——T 叉/臂端电阻位结点寄生不进闭式裁判（gysel/branchline 同口径，离线裁判=skrf 理想 2-way 单元级联装配）；②隔离电阻 LumpedElement 零厚度集总（qwt 端接同法，寄生 L/C 未建模）；③star 分支单层不可布为渲染面拓扑约束（非内核语义变更）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50（官方口径）；全部盒缘（叉臂带缘/T 条缘/电阻盒边/支线与输出馈线缘）+ 端口 junction 精确入网（#198）；显式近场线 10µm 地板（#349）；全轴 1µm 近重合去重（#152）；端口面贴 PML_8 域边（#154 前节）

## patch

- **抽取判据**：S11 @ MSLPort 1（单端口回退）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`patch_len_mm`、`patch_w_mm`、`feed_offset_mm`
- **名义参数**：`patch_len_mm`=34.9，`patch_w_mm`=50.0，`feed_offset_mm`=10.0
- **拓扑**：矩形贴片（patch_len = 谐振 λ/2 轴，沿馈电方向 y）+ 边缘微带馈电

## patch_array_1x4

- **抽取判据**：S11 @ LumpedPort 1（底探针馈 corporate 1×4 贴片阵：谷位/谷深；方向图走 far_field=True nf2ff，离线裁判=积定理闭式：主瓣 0°、HPBW 对照 broadside_hpbw_deg(4,d/λ0)、无栅瓣；未真机冒烟）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`elem_len_mm`、`elem_w_mm`、`elem_feed_mm`、`spacing_mm`、`feed_w_mm`、`q_w_mm`、`q_len_mm`
- **名义参数**：`elem_len_mm`=12.9058，`elem_w_mm`=16.9311，`elem_feed_mm`=3.8717，`spacing_mm`=25.0172，`feed_w_mm`=1.112，`q_w_mm`=0.6025，`q_len_mm`=7.8217
- **拓扑**：1×4 直线贴片阵（§10.3 C2）：4 元沿 x 等距 spacing、行中心 y=20mm，单元 L 沿 y/W 沿 x、插入馈缺口开在 −y 边（3 盒贴片）；corporate 树=主干 50Ω（底探针→J0）+ J0→J1± λ/4 70.7Ω + J1± 50Ω 透明连线（y0 横走/各元 x 竖走）+ 每元最后一段 λ/4 70.7Ω 入缺口；基板 + z-min PEC 地
- **冒烟注记**：未真机冒烟（2026-09-15 注册，离线审计/闭式裁判已过）。openEMS 轨 followUp：scripts/smoke_array_anchor.py <template>，判据=S11 谷位 f0±12% 窗（谷深 ≤−6dB）+ far_field nf2ff 主瓣天顶/HPBW·Dmax 对照 core/array_synthesis 闭式 ≤20-30% + η=Prad/P_acc 合理；预算 NrTS=100000 分钟~小时级，逐模板串行单飞
- **网格注记**：辐射器件：上方/侧向空气隙 λ0/4；全部盒缘（贴片/缺口/树/探针）精确入网（#198）

## patch_array_2x2

- **抽取判据**：S11 @ LumpedPort 1（底探针馈 H-tree 2×2 贴片阵：谷位/谷深；方向图走 far_field=True nf2ff，离线裁判=平面阵可分离积 AF_x·AF_y 逐点；未真机冒烟）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`elem_len_mm`、`elem_w_mm`、`elem_feed_mm`、`spacing_x_mm`、`spacing_y_mm`、`feed_w_mm`、`q_w_mm`、`q_len_mm`
- **名义参数**：`elem_len_mm`=12.9058，`elem_w_mm`=16.9311，`elem_feed_mm`=3.8717，`spacing_x_mm`=25.0172，`spacing_y_mm`=25.0172，`feed_w_mm`=1.112，`q_w_mm`=0.6025，`q_len_mm`=7.8217
- **拓扑**：2×2 平面贴片阵（§10.3 C2）：栅格中心 (0,20mm)，元列 x=±dx/2、元排 y=20∓dy/2；底排缺口向 −y 自下入，顶排缺口向 +y——馈线经 J1± 沿 y0 外走到元列外侧走廊 x=±(dx/2+W/2+2mm) 上行、顶排上方内折、变换段自上向下入缺口（同层零交叉）；H-tree 阻抗账同 1×4；基板 + z-min PEC 地
- **冒烟注记**：未真机冒烟（2026-09-15 注册，离线审计/闭式裁判已过）。openEMS 轨 followUp：scripts/smoke_array_anchor.py <template>，判据=S11 谷位 f0±12% 窗（谷深 ≤−6dB）+ far_field nf2ff 主瓣天顶/HPBW·Dmax 对照 core/array_synthesis 闭式 ≤20-30% + η=Prad/P_acc 合理；预算 NrTS=100000 分钟~小时级，逐模板串行单飞
- **网格注记**：辐射器件：上方/侧向空气隙 λ0/4；全部盒缘精确入网（#198）

## patch_array_series

- **抽取判据**：S11 @ MSLPort 1（1×3 共线串馈贴片阵，端接=链末开路辐射边：谷位/谷深；方向图走 far_field=True nf2ff，离线裁判=积定理闭式（同相侧射）；未真机冒烟）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`elem_len_mm`、`elem_w_mm`、`feed_w_mm`、`link_len_mm`、`feed_margin_mm`
- **名义参数**：`elem_len_mm`=12.9058，`elem_w_mm`=16.9311，`feed_w_mm`=1.112，`link_len_mm`=15.2876，`feed_margin_mm`=8.0
- **拓扑**：1×3 串馈贴片阵（§10.3 C2）：3 元共线沿 y（x=0 居中，L 沿 y/W 沿 x），相邻元以 λg/2 50Ω 互联接辐射边中心；MSLPort 自 y=−BOARD 入、自画馈段至链首元 −y 边（feed_margin）；链末开路。相位账：λg/2 段 180°+λ/2 贴片两边场反相 180° ⇒ 同相侧射；单轴 PML（y）；基板 + z-min PEC 地
- **冒烟注记**：未真机冒烟（2026-09-15 注册，离线审计/闭式裁判已过）。openEMS 轨 followUp：scripts/smoke_array_anchor.py <template>，判据=S11 谷位 f0±12% 窗（谷深 ≤−6dB）+ far_field nf2ff 主瓣天顶/HPBW·Dmax 对照 core/array_synthesis 闭式 ≤20-30% + η=Prad/P_acc 合理；预算 NrTS=100000 分钟~小时级，逐模板串行单飞
- **网格注记**：辐射器件：上方/侧向空气隙 λ0/4；贴片/互联/馈段盒缘精确入网（#198）

## patch_eep_1x4

- **抽取判据**：整 4×4 S @ LumpedPort 1-4（单激励 9 列 CSV，excite_port=1..4 进程隔离轮转装配 → .s4p，#208）+ EEPₙ @ farfield3d_cplx.csv（far_field=True，f_res=F0 固定口径，轮间同频可叠加）；互耦档判据 J4 见 runs/df6_dp4p3/criteria.md
- **基板**：er=3.66，h_mm=0.508
- **参数**：`elem_len_mm`、`elem_w_mm`、`elem_feed_mm`、`spacing_x_mm`、`feed_w_mm`
- **名义参数**：`elem_len_mm`=12.9058，`elem_w_mm`=16.9311，`elem_feed_mm`=3.8717，`spacing_x_mm`=25.0172，`feed_w_mm`=1.112
- **拓扑**：1×4 EEP 贴片阵（§DP-4 P3）：4 元沿 x 等距 spacing（行中心 y=20mm），缺口全开 −y；每元独立 LumpedPort 底探针（端口 1..4 =x 升序），无 corporate 馈树，元间 DC 隔离=EEP 定义性质；基板 + z-min PEC 地
- **冒烟注记**：未真机冒烟（2026-09-24 注册，离线审计已过）。真机 J4 门预声明于 runs/df6_dp4p3/criteria.md（4 轮装配 σmax≤1.005 硬门 + 全阵 vs 快档带内报告 + Γ_act(0°) vs HFSS Floquet）；发射命令/预算/判读见 战役任务书；openEMS 串行 solo（#246/#261），发射前 CSXCAD 离线 exec 实测 dt/NrTS 预算（#328/#349）
- **网格注记**：辐射器件：上方/侧向空气隙 λ0/4；全部盒缘（贴片/缺口/探针）精确入网（#198）

## patch_eep_2x2

- **抽取判据**：整 4×4 S @ LumpedPort 1-4（单激励 9 列 CSV，excite_port=1..4 进程隔离轮转装配 → .s4p，#208）+ EEPₙ @ farfield3d_cplx.csv（far_field=True，f_res=F0 固定口径，轮间同频可叠加）；互耦档判据 J4 见 runs/df6_dp4p3/criteria.md
- **基板**：er=3.66，h_mm=0.508
- **参数**：`elem_len_mm`、`elem_w_mm`、`elem_feed_mm`、`spacing_x_mm`、`spacing_y_mm`、`feed_w_mm`
- **名义参数**：`elem_len_mm`=12.9058，`elem_w_mm`=16.9311，`elem_feed_mm`=3.8717，`spacing_x_mm`=25.0172，`spacing_y_mm`=25.0172，`feed_w_mm`=1.112
- **拓扑**：2×2 EEP 贴片阵（§DP-4 P3）：栅格中心 (0,20mm)，元列 x=±dx/2、元排 y=20∓dy/2，四元同向（缺口全开 −y）；每元独立 LumpedPort 底探针（端口 1..4=行主序 x 外层 y 内层），无 corporate 馈树，元间 DC 隔离=EEP 定义性质；基板 + z-min PEC 地
- **冒烟注记**：未真机冒烟（2026-09-24 注册，离线审计已过）。真机 J4 门预声明于 runs/df6_dp4p3/criteria.md（4 轮装配 σmax≤1.005 硬门 + 全阵 vs 快档带内报告 + Γ_act(0°) vs HFSS Floquet）；发射命令/预算/判读见 战役任务书；openEMS 串行 solo（#246/#261），发射前 CSXCAD 离线 exec 实测 dt/NrTS 预算（#328/#349）
- **网格注记**：辐射器件：上方/侧向空气隙 λ0/4；全部盒缘（贴片/缺口/探针）精确入网（#198）

## pifa

- **抽取判据**：S11 @ LumpedPort 1（PIFA 居中短路板 λ/4：谷位/谷深；L 路径式定版标称 17.0785 ≈ 真机 override 17.08 → −8.79dB@2.26GHz（−5.8%）PASS，Zin@谷=105−14jΩ，见 smoke_note）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`pifa_l_mm`、`pifa_w_mm`、`pifa_ws_mm`、`pin_back_mm`、`pin_y_mm`
- **名义参数**：`pifa_l_mm`=17.0785，`pifa_w_mm`=8.0，`pifa_ws_mm`=2.0，`pin_back_mm`=2.0，`pin_y_mm`=2.0
- **拓扑**：PIFA（§10.3 C1）：贴片 z=h（L×W）+ +x 边短路板（宽 Ws，z 0→h 触地）+ 馈针（距短路板 pin_back，y 偏 pin_y，针顶触贴片、针底触地）；LumpedPort 沿针 z 向；基板 + z-min PEC 无限大地
- **冒烟注记**：真机 runs/antenna2_smoke/pifa（2026-09-14，旧通式标称 L=11.0785）FAIL：\|S11\|≥−0.02dB 全带，Zin=0.0+j(3.9→8.6)Ω 随 f 线性=纯短路桩电感 ⇒ 谐振在 2.9GHz 之上。两轮实证：① 去掉同体积金属针盒（pifa_v1_pin_short→pifa）S11 逐点不变，"PEC 针盒短路端口"假设证伪；② override pifa_l_mm=17.08（=λ0/(4√εeff(W))，仅 L 路径口径，runs/antenna2_smoke/pifa_override）→ −8.79dB @2.26GHz（−5.8%）PASS，Zin@谷=105−14jΩ（并联型谐振，馈针距短路板 2mm ⇒ R_peak≈100Ω 过耦合限谷深）。根因：L+W−Ws=λ/4 通式假定角部短路板（电流绕行贴片宽），本布局短路板居中不绕行，有效路径≈L。定版（2026-09-16）：设计式改 L 路径式 pifa_l_mm=λ0/(4√εeff(W))，标称 17.0785（与 PASS 的 override 17.08 差 0.0015mm=0.009%，真机证据直接沿用，不另跑），fake 逆/ANTENNA2_NOMINAL/单测/本文件同步；谷位 −5.8% 为细带端效应/短路板电感口径偏差，设计式不预补偿（#190）

## pyramid_horn

- **抽取判据**：S11 @ RectWGPort 1（解析 TE10 模式端口，Z_ref=解析波导阻抗 ZL=k·Z0/β 口径）； 增益判读=口径场闭式（core/horn_synthesis）对照，方向图/nf2ff=Ph3 真机窗
- **基板**：er=1.0，h_mm=0.0
- **参数**：`a_mm`、`b_mm`、`a1_mm`、`b1_mm`、`l_feed_mm`、`l_flare_mm`
- **名义参数**：`a_mm`=22.86，`b_mm`=10.16，`a1_mm`=76.40094536120978，`b1_mm`=57.54769444861163，`l_feed_mm`=60.0，`l_flare_mm`=45.48234099926676，`er`=1.0，`h_mm`=0.0
- **拓扑**：标准增益角锥喇叭：WR-90 波导馈电直管（端口面贴 y=−DOM_Y PML_8 域边）+ 四壁 梯形口径段（喉部 y=0、口径 y=l_flare；H 面宽沿 x a→a1、E 面高沿 z b→b1）； 斜壁以 8 段矩形截面阶梯链逼近（段间框面闭合=全 PEC 封闭腔）；空气填充无介质 板，y 轴双端 PML_8、x/z MUR
- **冒烟注记**：未冒烟（离线审计过，#212，test_pyramid_horn_template）；近似级别如实登记： ①斜壁 8 段阶梯化（矩形截面链，段中截面采样）；②闭式口径面模型不含壁损耗/ 口面反射/边缘绕射；③方向图/nf2ff 与真机冒烟=Ph3 窗（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ0/50（空气口径，官方 base 级）；NEAR=base/4；全部壁面站线（波导口缘/逐段截面缘/阶梯框/口径面/端口面） 显式入网（#198）+ 全轴 1µm 近重合去重（#152）；渲染守卫：阶梯步距 ≥4·NEAR （#266 族）、a1>a 且 b1>b；口径侧空气域 ≥λ0/4+4mm 由管长自动外推保证 （#174 族）

## qwt_multisection

- **抽取判据**：S11 @ MSLPort 1（λ/4 节级联 + 末端 LumpedElement R=ZL 端接到地，单端口回退 footer 同 patch）。裁判=skrf N 节理想 TL 级联 50Ω 端接闭式 \|S11(f)\|：@f0 深零（binomial/chebyshev 奇 N 中心精确匹配，内核谱系恒等式）、带内纹波电平=Γm、FBW 对照 kernel bandwidth_estimate；引擎-理想偏差=节间阶梯跳宽寄生（stepped_impedance 同口径）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`widths_mm`、`lengths_mm`、`feed_w_mm`、`z_load_ohm`
- **名义参数**：`widths_mm`=[0.966, 0.603, 0.344]，`lengths_mm`=[17.851, 18.162, 18.462]，`feed_w_mm`=1.1134，`z_load_ohm`=100.0
- **拓扑**：多节 λ/4 阻抗变换器（TA-2）：50Ω 馈线（port1，−BOARD 板边入）+ N 节 λ/4 均匀微带线级联（节阻抗 Z1..ZN 闭式表驱动，沿 y）+ 末端 LumpedElement R=ZL 端接盒（z=0..H_SUB 对地，mmwave_series_array 链末负载同法）；z-min PEC 地 + 缺省 rogers4350b 叠层（guided 口径）
- **冒烟注记**：未冒烟（离线审计过，#212，test_schiffman_qwt_templates）；近似级别如实登记：①节间阶梯跳宽不连续性不进闭式裁判（离线裁判=理想 TL 级联，偏差即寄生）；②LumpedElement 集总端接的寄生电感/电容未建模（零厚度集总口径）；③一阶小反射表驱动闭式（N>4 chebyshev 需 Riblet 数值迭代，内核显式拒绝）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50（官方口径）；馈线/各节带缘+节间 junction/端接盒缘精确入网（#198）；全轴 1µm 近重合去重（#152）；端口面贴 PML_8 域边

## ratrace

- **抽取判据**：全 S 矩阵 4×4 @ ratrace.s4p（官方激励轮转 4 run：SetEnabled 逐端口激励+匹配终端探针；skrf Touchstone 主路，CSV 降兼容）。裁判=理想 180° 混合环 S 矩阵闭式（#208 Y 矩阵推导）：Σ 均分 -3dB 同相、Δ 隔离、out1↔out2 互隔离；规范角位 Σ=0°/out1=60°/Δ=120°/out2=180°
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_ring_mm`、`w_feed_mm`
- **名义参数**：`w_ring_mm`=0.604，`w_feed_mm`=1.1134，`r_ring_mm`=17.344

## ridged_wg

- **抽取判据**：S11/S21 @ RectWGPort 1-2（解析 TE10 打在加宽馈段，Z_ref=解析波导阻抗；S21=port2.uf_inc 口径——自然升序定义端口透射在 uf_inc，coax_wg 同款）。判读锚（预声明，真机窗）：①交越膝点 \|S21\| −3dB 落内核 fc·(1±8%)（脊段消逝衰减 @0.8fc≈22dB/40mm 使过渡陡峭）；②带底消逝衰减斜率对照 evanescent_attenuation_db； ③带内 \|S21\| 平台≈1（馈段/脊段单模行波）。内核裁判=ridged_waveguide.cutoff_fc_hz 同参复算（XC-P 精度域 g/b≥0.4，名义 0.454）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`a_mm`、`b_mm`、`s_mm`、`d_mm`、`l_ridge_mm`、`l_feed_mm`
- **名义参数**：`a_mm`=22.86，`b_mm`=10.16，`s_mm`=9.144，`d_mm`=5.5434，`l_ridge_mm`=40.0，`l_feed_mm`=25.0，`er`=1.0，`h_mm`=0.0
- **拓扑**：空气单脊矩形波导均匀段（TA-6）：脊段外廓 a×b+顶壁居中脊 s×d（y∈±l_ridge/2）+ 两端加宽馈波导 a_feed×b（H 面对称阶跃，a_feed=c/(2·0.75·fc_ridge) 结构性 >4a/3）+ 阶跃端面框板闭合（零泄漏）； 双 RectWGPort 打在馈段（激励/探针面均内移 16·BASE 出 PML_8）；空气填充全金属（无介质板）
- **冒烟注记**：未冒烟（离线审计过，#212，test_diplexer_ridged_templates）；近似级别如实登记：①一阶横磁共振闭式遗漏脊缘杂散电容（kc 高估 +1.5~+8% @g/b≥0.4 分档域，内核精度档案 WARN）；②H 面阶跃结反射不进闭式裁判（v1 直阶跃无渐变——工程实践为 λ/4 锥削过渡，后续变体）；③RectWGPort 打在馈段，脊模经阶跃结的耦合损耗计入 S21；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ0/50（空气口径，horn 同款）；全部壁面站线（外廓缘/脊缘/馈段缘/阶跃框/端口面）显式入网（#198）+ 全轴 1µm 近重合去重（#152）；渲染守卫：NEAR ≤ min(s,g)/3（#266 族特征分辨）、g/b≥0.4（XC-P 精度域）、判读带 ⊂（fc_feed, min(1.5·fc_ridge, 外廓 TE10)）单模域

## ring_resonator

- **抽取判据**：S11/S21 @ MSLPort 1-2（环形谐振器：S21 谐振指纹 f_n≈n·c/(2πr_mean·√εeff) 反演 εr；1/Q_L=1/Q_d+1/Q_c+1/Q_r 分离提取 tanδ——F-A M3 口径，提取内核 core/dielectric_extract 属后续批次）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`r_mean_mm`、`w_mm`、`gap_mm`、`feed_w_mm`
- **名义参数**：`r_mean_mm`=11.299802692199101，`w_mm`=1.1134，`gap_mm`=0.4，`feed_w_mm`=1.1134
- **拓扑**：微带环形谐振器（F-A M3 材料提取 fixture）：闭环环带（r_mean±w/2，逐网格行 栅格化，ratrace 同法 #198 零台阶）+ 径向对置双 50Ω 间隙耦合馈线（x=0 沿 y， 端口面贴 y=±BOARD PML_8 域边）；对置 180° 馈点对各次模均为场腹（全 n 模可 激励）；z-min PEC 地 + 缺省 rogers4350b 叠层（guided 口径）
- **冒烟注记**：未冒烟（离线审计过，#212，test_ring_resonator_template）；近似级别如实 登记：v1 闭式未含色散/曲率修正与栅格化慢波补偿（ratrace_ring_mesh_k 两锚 定标于 70.7Ω 线宽未对本模板定标，禁止外推复用），εr 提取精度由 G2 闭环+ HFSS 仲裁另批兑现
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50（官方口径）——本 模板缺省自动档触发缝分辨守卫（NEAR=0.285mm>gap/3），须显式 mesh≤4·gap/3 （C3 族同口径）；环带基点缘/馈线带缘/馈端与缝缘精确入网 + 缝中线入网 （#198/#311）；渲染守卫：NEAR≤gap/3（#266 族缝分辨）、feed_len≥42·NEAR （#347 族 MeasPlaneShift-FeedShift 分离）、r_in>0；全轴 1µm 近重合去重 （#152）；端口面贴 PML_8 域边（#154 前节）

## schiffman

- **抽取判据**：全 S 矩阵 4×4 @ .s4p（官方激励轮转 4 run，#208 口径同 ratrace/lange；port1/2=耦合段两端、port3/4=参考段两端）。裁判=core.synthesis.schiffman_delta_phase 闭式：Δφ(f)=deg(unwrap∠S43)−deg(unwrap∠S21)（两路径测量面经 MeasPlaneShift 解嵌到段端面），@f0=+90°、带内平坦度对照 kernel phase_flatness；openEMS DFT e^{−jωt} 口径（#253②），skrf 装配侧符号取反如实换算
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`gap_mm`、`l_coupled_mm`、`l_ref_mm`、`w_ref_mm`
- **名义参数**：`w_mm`=0.9051，`gap_mm`=0.0692，`l_coupled_mm`=18.192633，`l_ref_mm`=54.577898，`w_ref_mm`=1.1134
- **拓扑**：Schiffman 90° 定差移相器（TA-1）：耦合段=远端桥接平行耦合 U 形全通段（C-section：双带条 x=±(gap/2+w/2) 沿 y、远端桥带闭合，port1/2 在 −BOARD 板边近端）+ 参考直通段（50Ω，长 l_ref，port3/4 在 ±BOARD 板边）；双路径同板 DC 隔离（净空 ≥3·h_sub）；全通匹配 Z0e·Z0o=Z0²=2500 由设计链构造保证
- **冒烟注记**：未冒烟（离线审计过，#212，test_schiffman_qwt_templates）；近似级别如实登记：①准静态 εeff 逐模常数化无色散（内核 v1 声明）；②参考段 εeff 取偶/奇模相速平均口径（内核 v1）；③测量面解嵌到段端面，端面孤立线↔耦合对阶跃寄生不建模（Schiffman 原文口径）；④ρ=2.0 平坦度 ±25% 窗 max 偏差 ≈7.2°（低 εr 可达域内，不凑 ρ=3）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50（官方口径）；耦合缝 0.0692mm<NEAR 按 #311 缝中点精确入网（x=0 中线+±gap/2 带缘精确 AddLine，缝内内部线 ≥1 恒成立，不设 NEAR≤gap/3 硬守卫——C4 决议口径）；耦合对四带缘/桥带缘/段两端/参考段两端/参考带缘精确入网（#198）；真机建议显式 mesh_resolution_mm≤0.3（缝邻域分辨）；全轴 1µm 近重合去重（#152）；端口面贴 PML_8 域边（#154 前节）

## sicl

- **抽取判据**：S11/S21 @ StripLinePort 1-2（height=b/2 带-地半高对称探针，suspended_stripline 同法）：β 金标准→εeff 对照内核闭式 εeff=εr=3.66（均匀填充 TEM，\|Δ\|≤2% 口径同 stripline 族）；\|S11\| 带谷=Z0 锚（名义反解 Z0=50 故 ref=50；cps 口径）。内核裁判=sicl_line.sicl_closed_form（FD 裁判 ±5% 声明域，名义点 in_referee_band=True）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`a_mm`、`d_mm`、`s_mm`、`line_len_mm`
- **名义参数**：`w_mm`=0.554，`a_mm`=2.54，`d_mm`=0.6，`s_mm`=1.0，`line_len_mm`=40.0，`h_mm`=1.016，`er`=3.66，`tan_d`=0.0037
- **拓扑**：SICL 基片集成同轴线均匀段（TA-3）：矩形同轴腔（上下地板=域 z 边界 PEC+显式零厚板 siw 同款；两列接地过孔墙 x=±a/2、心距 s、藩篱贯通全域直入 PML=匹配端接 siw v1 口径）+ 零厚度内导体条带（w，中面 z=b/2=H_SUB/2）；端口=双 StripLinePort（面贴 ±DOM_Y 域边界 PML_8）；矩形域 DOM_X/DOM_Y 字面注入
- **冒烟注记**：未冒烟（离线审计过，#212，test_sicl_nway_templates）；近似级别如实登记：①准静态闭式无色散/零厚带/均匀填充（内核 FD 裁判 ±5% 声明域，UNVERIFIED-1 公式族归属如实登记）；②过孔墙离散化（s=1.0mm 圆柱列）对理想连续壁的等效性未经真机仲裁（SIW 经验迁移，内核 docstring 登记面）；③StripLinePort 端口段=屏蔽腔内均匀延伸无过渡（同 stripline 口径）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50（官方口径）；条带缘/过孔墙三线对（列心±d/2、列心）/条带两端/端口面精确入网（#198）；条带中面 z=b/2 落格依赖基板 z 偶数格（_sub_cells 缺省 4，生成期断言 #283 口径）；过孔直径 ≥4·NEAR + 孔间缝>NEAR（#311 先例口径）守卫；显式近场线 10µm 地板（#349）；全轴 1µm 近重合去重（#152）

## sir_bpf

- **抽取判据**：S11/S21 @ MSLPort 1-2（SIR 带通：带内回波纹波 + 带外抑制；裁判=并联谐振 J 倒置器链 c3_circuit_sparams，同步 TEM 极限对照 C13 coupling_matrix_response 互证，实测 max\|ΔS21\|=0.0061dB）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`order`、`w_feed_mm`、`w_low_mm`、`w_high_mm`、`l_low_mm`、`l_high_mm`、`gaps_mm`、`feed_len_mm`
- **名义参数**：`order`=3，`w_feed_mm`=1.1117，`w_low_mm`=1.8944，`w_high_mm`=0.6144，`l_low_mm`=6.5719，`l_high_mm`=6.7818，`gaps_mm`=[0.2417, 1.5189, 1.5189, 0.2417]，`feed_len_mm`=53.3232
- **拓扑**：λ/4 型接地 SIR 带通（§C3 滤波器族 II，MYJ SIR 章口径）：N 根阶梯阻抗棒平行排列（开路端低阻段 w_low + 接地端高阻段 w_high，步进比 Z_lo/Z_hi=35/70 给出紧凑化，谐振条件 tanθ1·tanθ2=Z_lo/Z_hi），同端接地顶端过孔 r=0.15mm，耦合区=低阻段（相邻棒低阻段对齐）；双 50Ω 馈线（板边段 w_feed + 耦合段 w_low 台阶）缝耦合自 y=−BOARD 板边引入（单轴 PML）
- **冒烟注记**：真机 openEMS 冒烟后置（followUp，循 coupled_bpf NrTS PARTIAL 先例），本项全程离线验收

## siw

- **抽取判据**：LumpedPort z 桥×2（R=闭式 Z_PV=2b·Z_TE/w_eff，CalcPort 同参考）： 原始 S=带载比值（#250 口径，slotline_lumped 同）；β/εeff 主判=S21 解缠 相位斜率÷port_beta.csv 实测 plane_dist（cps 同契约，LumpedPort 无 β 属性）；fc10 由带内 φ(f)=−β(f；fc)·L+φ0 单参数拟合（OE 锚 G1，预声明 runs/siw_family/criteria.md §6）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`d_mm`、`s_mm`、`line_len_mm`
- **名义参数**：`w_mm`=12.1317，`d_mm`=0.6，`s_mm`=1.0，`line_len_mm`=63.0724，`h_mm`=0.508，`er`=3.66，`tan_d`=0.0037
- **拓扑**：直 SIW 传输线段：基板 z∈[0,h] 上下显式零厚金属板（贴 z 边界 PEC）+ 两列 金属化过孔 PEC 圆柱（x=±w/2、心距 s、全域精确栅格、藩篱直入 PML=匹配 端接）；端口=两端 LumpedPort z 桥（中线、跨全高、盒边入网、16·BASE 出 PML_8）；域 x 半宽=w/2+w_eff/2（侧界 MUR 吸收泄漏）、y 半宽=line_len/2+ 16·BASE（PML_8）——矩形域，BOARD=60e-3 不适用（机制层 DOM_X/DOM_Y 字面注入）
- **冒烟注记**：离线审计先行（#212，test_siw_template）；真机锚已落判（df4f：G1 勘误 PASS/G2 PASS/G3 口径裁定/G4 PASS，runs/siw_family/，驱动 scripts/siw_anchor_smoke.py）；预声明门与预算见 runs/siw_family/criteria.md §6
- **网格注记**：mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；全域 NEAR=base/4 （SmoothMesh 全轴均匀化实测）；过孔直径 ≥4·NEAR 守卫、孔间缝 ≥1 内部线 （#311 类比）、显式近场线 10µm 地板（#349）、端口盒 ≥2 格且中线落格 （#283，生成期断言）、基板 z 4 层（TE10 的 E_z 沿 z 均匀，z 分辨非限制项）

## slot

- **抽取判据**：S11/S21 @ MSLPort 1-2（地面谐振缝：S21 辐射凹位置+深度=谐振判据，过缝辐射负载使 S11 全带平坦不适用；真机 −16.41dB@2.665GHz PASS；判读窗收内带 f0±0.4GHz + Σ\|S\|²>1.02 点剔除——带边 Σ\|S\|²>1 为高斯激励 −20dB 带边归一化伪象，见 smoke_note）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`slot_l_mm`、`slot_w_mm`、`feed_w_mm`、`feed_margin_mm`
- **名义参数**：`slot_l_mm`=40.9168，`slot_w_mm`=2.0，`feed_w_mm`=1.1134，`feed_margin_mm`=12.0
- **拓扑**：缝隙（§10.3 C1）：z=0 有限金属地（4 盒拼合、槽 L×Ws 留空）+ z=h 50Ω 微带馈线 y 向垂直跨槽居中 + 双 MSLPort 板边端接（y=∓BOARD，单轴 PML）；底 MUR + z 向下延 λ0/4（槽向下半空间也辐射，PEC 底会短路槽）
- **冒烟注记**：真机 runs/antenna2_smoke/slot 与 slot_override（2026-09-14）PASS×2：S21 辐射凹 −16.41dB @2.665GHz（L=40.9168，+11.0%，隐含 εeff 1.84）/ −21.76dB @2.6275GHz（L=46.036，隐含 εeff 1.54）；k_slot∈[0.66,0.79]·(1+εr)/2 待 HFSS 仲裁后才进设计式（#190）。Σ\|S\|² 带边 >1 已排查（2026-09-16，slot/sparams.csv 实测）：1.9GHz=1.212、2.9GHz=1.128，>1.02 的点全部落在 1.9-2.08 与 2.82-2.9 两侧，f0±12% 判读窗（2.112-2.688GHz）内 ≤1.008——越限恰在 SetGaussExcite(F0,FC) 高斯激励 −20dB 带边（评估带=激励带，uf_inc 归一化分母趋零放大数值噪声），归一化伪象而非 MSLPort/有限地物理错；判读口径=窗收内带 f0±0.4GHz（激励带内 80%）+ Σ\|S\|²>1.02 点剔除（scripts/smoke_antenna2_anchor.py 全模板通用；掩模后 307/321 点，凹位/深度不变），全局 FC 不动（f_max 进网格预算，改激励带会漂全部模板网格锚）

## slotline

- **抽取判据**：WaveguidePort 文件模式（NGSolve 2D 本征模 E/H 喂入，exc_dir=x）：模式文件必需 SetPropagationDir；CalcPort 参考阻抗=交叉取对面端口视入阻抗（文件模式 U/I 度量常数 γ≈2.71，坑 B）；S21=port2.uf_inc/SREF（实证口径）；β 独立提取=槽跨压探针 N 站自实现工程 DFT 相位斜率
- **基板**：er=3.66，h_mm=1.524
- **参数**：`w_mm`、`line_len_mm`、`h_mm`
- **名义参数**：`w_mm`=1.0，`line_len_mm`=93.4624，`h_mm`=1.524，`er`=3.66，`tan_d`=0.0037
- **拓扑**：均匀槽线段（路线 A，单面金属开缝、无地开放结构）：槽 \|y\|≤w/2 贯通至两端边界，两端 WaveguidePort（E/H 模式文件），激励面内移 16·BASE 出 PML_8；基板 z∈[0,h]，上下/侧向 MUR、端口轴 PML_8；槽跨压探针 9 站
- **冒烟注记**：真机 PASS（08d63b0）：β 闭式 67.227/NGSolve 67.149/openEMS 67.937 rad/m 互差 ≤1.2%、\|S11\|@f0 −39.1dB、\|S21\| −0.32dB 三门。运行前置：模式文件必须先经 adapters/ngsolve_modes.solve_slotline_mode + openems_slotline_port.write_slotline_mode_files 生成，params 传 e_mode_file/h_mode_file 绝对路径（缺省名仅占位，真跑会缺文件报错）；kc/z_mode 缺省由闭式反解，正式口径取 NGSolve 解
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；近槽/近端口 NEAR=base/4、基板 z 6 层、#152 最小间距守卫；槽缘细化步长 min(NEAR, w/8)、地板 10µm（#349，TODO 0df④——自动档恰为 w/8 且引擎 dt 相应减半，真跑前按 et 实测 dt 重排 NrTS，#283）

## slotline_lumped

- **抽取判据**：LumpedPort 跨槽 R=线阻抗档（CalcPort 参考同值）：带载比值 S11/S21（#250）口径，assemble_route_b_sparams 归一到 50Ω 对拍；β 主口径=双行波拟合 two_wave_beta_fit（线性斜率法驻波下偏 +10.7% 只作诊断列）
- **基板**：er=3.66，h_mm=1.524
- **参数**：`w_mm`、`line_len_mm`、`h_mm`
- **名义参数**：`w_mm`=1.0，`line_len_mm`=93.4624，`h_mm`=1.524，`er`=3.66，`tan_d`=0.0037
- **拓扑**：均匀槽线段（路线 B，官方 AddLumpedPort 范式）：金属/基板/槽贯通全域直入 PML（匹配端接），两端 LumpedPort 跨槽桥接（盒三向边全部入网，#198/#174）；槽跨压探针 9 站 [−L/4,+L/4]
- **冒烟注记**：真机 β_B 68.40 vs HFSS-wide +2.44%（门 3% PASS，e35a517）。原始 \|S11\|/\|S21\| 为"PML 匹配线上并联抽头"拓扑解析必然（βL=2π 时 S11=−1/2/S21=+1/2）：β 生产口径可用，S 参数 D 级需 tap_network_sparams 换算（#250）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；端口盒/槽缘/基板界面精确入网、#152 守卫

## sma_launcher

- **抽取判据**：S11/S21 @ LumpedPort 1（同轴截面集总桥）/ MSLPort 2（SMA edge-launch：port2 β→HJ 金标准 + \|S11\| 文献曲线门 -10dB 保守地板）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_msl_mm`、`r_i_mm`、`r_o_mm`、`shell_t_mm`、`er_fill`、`shell_len_mm`、`pin_lay_mm`、`line_len_mm`、`port_len_mm`、`tan_d_fill`
- **名义参数**：`w_msl_mm`=1.1134，`r_i_mm`=0.635，`r_o_mm`=2.1244，`shell_t_mm`=0.25，`er_fill`=2.1，`shell_len_mm`=5.0，`pin_lay_mm`=2.0，`line_len_mm`=40.0，`port_len_mm`=0.2，`tan_d_fill`=0.0
- **拓扑**：SMA 边缘弹射（WP2.5 Tier 2，end-launch 夹具口径）：PTFE 填充 50Ω 同轴段（针/壳圆柱自画）在板边切口之外，针水平穿出搭焊在微带上（针底切线=基板顶），壳底切 z=0 PEC 夹具底板、壳端与 PCB 下方夹具金属块前脸实触（地链）；port1=同轴截面集总桥（针顶→壳内壁顶），port2=板边 MSLPort

## stepped_impedance

- **抽取判据**：S11/S21 @ MSLPort 1-2（带通形状）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`z1_width_mm`、`z2_width_mm`、`seg_len_mm`、`n_segments`、`feed_w_mm`
- **名义参数**：`z1_width_mm`=0.3，`z2_width_mm`=3.0，`seg_len_mm`=5.0，`n_segments`=5，`feed_w_mm`=1.1133

## stripline

- **抽取判据**：S11/S21 @ StripLinePort 1-2（对称带状线：TEM，εeff=εr）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`line_len_mm`
- **名义参数**：`w_mm`=0.5554，`line_len_mm`=40.0

## suspended_stripline

- **抽取判据**：S11/S21 @ StripLinePort 1-2（悬置带线：β 金标准→εeff 对照共形电容比闭式 _suspended_stripline_ri；基板 H_SUB 以带为中面对称悬浮于腔高 b 中）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`b_mm`、`line_len_mm`
- **名义参数**：`w_mm`=0.9058，`b_mm`=1.016，`line_len_mm`=40.0

## tjunc

- **抽取判据**：S11/S21/S31/S23 @ MSLPort 1-3（对称 T 结：均分+隔离，锚=skrf 理想三端口结点+HJ 线裁判）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_feed_mm`、`through_len_mm`、`branch_len_mm`
- **名义参数**：`w_feed_mm`=1.1134，`through_len_mm`=25.0，`branch_len_mm`=20.0

## varactor_bpf

- **抽取判据**：S11/S21 @ MSLPort 1-2（变容管调谐 BPF：三档偏压=三次静态 run 各自谷位；裁判=hairpin 耦合矩阵理想频响平移到 f0(C(V))，主谐振方程 tan(βL)=−ωCZ0 同源闭式 core/varactor.py）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`order`、`w_mm`、`arm_len_mm`、`arm_gap_mm`、`gap_mm`、`tap_frac`、`cj0_pf`、`phi_v`、`bias_v`
- **名义参数**：`order`=3，`w_mm`=1.1117，`arm_len_mm`=31.6675，`arm_gap_mm`=3.0，`gap_mm`=1.1328，`tap_frac`=0.330119，`cj0_pf`=1.0，`phi_v`=0.9，`bias_v`=3.6342
- **拓扑**：变容管调谐发夹线带通（M-5 首个半有源模板，hairpin 族增量）：N 个 λg/2 级 U 形谐振器沿 x 并排、相邻外臂平行耦合（缝 gap_mm），每 U 左臂开路端对地并联一只 lumped C(V)（CSXCAD LumpedElement，ny=2 全隙盒）；输入/输出 50Ω 抽头馈线（T 形，板边 x=∓BOARD；单轴 x PML）
- **冒烟注记**：真机三档偏压冒烟（V=0.5/3.6342/10.0，各档 C 为常数）未发射——本件只备妥发射面与离线审计（M-5 判据「openEMS 名义点 3 档偏压冒烟」归真机批）；离线几何审计（#212 制度化）见 tests/unit/test_varactor_bpf_template.py。2026-09-29 更新：三档冒烟已跑全 FAIL（触帽+慢振铃），规则 1b 模型审计定案 P0=抽头 τ 沿用无载廓线闭式（loaded 节点恰扫过旧设计值 0.401892）外耦失配 3-1139×——本批 P0（loaded 廓线 τ 自 C 端计，名义 0.330119）+P2（C_literal=C(V)−C_geo）修复后真机复验待 oe-queue 排期，详见 runs/varactor_smoke/model_audit_verdict.md
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；全部臂缘/弯带缘/抽头缘+变容管盒外 y 缘精确入网（#198）

## via

- **抽取判据**：S11/S21 @ MSLPort 1-2（双层板过孔过渡：β 金标准+\|S11\|<-10dB 绝对门）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`antipad_mm`、`r_via_mm`
- **名义参数**：`w_mm`=1.1134，`antipad_mm`=0.8，`r_via_mm`=0.15

## vivaldi_tsa

- **抽取判据**：S11/S21 @ MSLPort 1-2（跨槽耦合馈；\|S11\| 谷=槽线模建立判读，f_low 由口面半波准则预声明）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_throat_mm`、`w_mouth_mm`、`l_mm`、`feed_w_mm`
- **名义参数**：`w_throat_mm`=0.3，`w_mouth_mm`=24.982705，`l_mm`=80.0，`feed_w_mm`=1.1134，`er`=3.66，`tan_d`=0.0037
- **拓扑**：Vivaldi 端射张口槽线天线（AP-11）：有限地面 z=0 带指数张口槽（喉部 y=−L/2 向口面 y=+L/2 指数张开，阶梯化栅格化），基板上覆、顶面 50Ω 微带跨槽馈（slot 模板已证机理；巴伦=独立馈电件留登记注记）；双 MSLPort 板边入（prop_dir=x）
- **冒烟注记**：离线审计先行（#212，test_ta_wave_b_templates）；内核数字裁判=指数律往返恒等+口面↔截止双向回收+单调性（core/vivaldi_tsa tests 钉）；近似级别如实登记：低截止=二手工程准则（Yngvesson 1985 介质加载修正未回原文不入码，citation-rot），巴伦面未做（登记注记），增益/方向图全波面不在本批；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；阶梯化站缘 x 向 + 馈线缘精确入网（#198）；底 MUR+域 z 下延（slot 同款：槽向下半空间辐射）；显式近场线 10µm 地板（#349）

## wilkinson

- **抽取判据**：S11/S21/S31/S23 @ MSLPort 1-3（S23 双激励第二 run，#211 footer 修复后第二激励前禁用全部非 e3_ 前缀 Excitation）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`series_w_mm`、`shunt_w_mm`、`arm_len_mm`
- **名义参数**：`series_w_mm`=0.604，`shunt_w_mm`=1.113，`arm_len_mm`=18.1
- **拓扑**：T型分叉 + 双 λ/4 臂（x 向并列）+ 100Ω 隔离电阻（LumpedElement）

## wstep

- **抽取判据**：S11/S21 @ MSLPort 1-2（单阶跃两段线：锚=skrf 级联 HJ 闭式裁判）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w1_mm`、`w2_mm`、`line_len_mm`
- **名义参数**：`w1_mm`=1.1134，`w2_mm`=1.897，`line_len_mm`=40.0

## xcheb_bpf4

- **抽取判据**：S11/S21 @ MSLPort 1-2（交叉耦合开路环 BPF：带内回波纹波+带外抑制+ **有限传输零点**（TZ，交叉耦合指纹）；裁判=C13 耦合矩阵闭式 coupling_matrix_response（cm_core 折叠矩阵消费），缝→k 纯 KJ+χ 一阶部分长标度）
- **基板**：er=3.66，h_mm=0.508
- **参数**：`w_mm`、`a_mm`、`g12_mm`、`g23_mm`、`g34_mm`、`g14_mm`、`g_open_mm`、`g_pos_mm`、`tap_t_mm`
- **名义参数**：`w_mm`=1.1117，`a_mm`=8.7626，`g12_mm`=0.3581，`g23_mm`=0.4253，`g34_mm`=0.2885，`g14_mm`=1.6526，`g_open_mm`=0.3，`g_pos_mm`=6.1338，`tap_t_mm`=8.1454，`h_mm`=0.508，`er`=3.66，`tan_d`=0.0037
- **拓扑**：交叉耦合开路环四重奏（TA-14）：四个 λg/2 方形开路环 2×2 排布（环1 左上/2 右上/3 右下/4 左下）；耦合=1-2 顶行水平缝 + 2-3 右侧竖缝 + 3-4 底行 水平缝 + **4-1 左侧竖缝（非相邻交叉耦合，cm_core folded m14 映射）**；馈电 =环 1/4 左边抽头（50Ω 馈线自 x=−BOARD 板边，hairpin A1 去嵌口径）
- **冒烟注记**：离线审计先行（#212，test_ta_wave_c_templates）；内核数字裁判三锚 （test_cross_coupled_map）：①全极点退化对 classical g 值闭式（独立综合路径， max rel dev 1.2e-5）②KJ 往返+矩阵频响一致性（max\|ΔS\|≤1e-6 实测 7.5e-7）③ TZ=[±2.0] 传输零点保持（−88dB 谷映射前后一致）；χ 一阶部分长耦合与环角/开缝 结构效应未经 EM 校准（hairpin c(gap) 同族待标定项，#122 如实登记）；真机冒烟 与 HFSS 仲裁属后续批次（本批零发射）
- **网格注记**：mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；#266 耦合缝 守卫 NEAR≤缝_min/3（layout 抛错拒渲染）；全部环边/开缝缘/馈线缘精确入网（#198） +四耦合缝中线入网（#311）；审计档 TEMPLATE_MESH_MM=0.35（NEAR=0.0875 ≤ 0.2885/3 过守卫）
