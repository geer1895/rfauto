# 射频模板建模·官方例对照表（开发前必读）

> 2026-09-02 多模态审计批次沉淀。给 openEMS 模板/新结构建模时的**权威对照来源**
> 与已验证口径。修改模板前先对照本表，避免重复踩坑。
> **2026-09-04 增补（阶段 0.1 根因闭环）**：网格/边界方法学升级为官方
> MSL_NotchFilter 基线（见 §0），旧 λ/20@空气粗网格口径作废。

## 0. 网格/边界/端口面方法学基线（2026-09-04 定稿，render_script 已内置）

| 项 | 权威口径 | 旧口径（作废）|
|---|---|---|
| 网格 base | 基板内波长 λ_sub/50 @F_MAX（3.5GHz 档 ≈0.9mm）；近走线区 base/4 | λ/20@空气 ≈4.3mm |
| 地面 | z-min PEC 边界 | 内部金属盒 |
| 基板 | 延伸到侧边界（无板边衍射）| 有限小板 + 70mm 空气隙 |
| z 轴 | 基板 [0,H]，金属在 z=H 顶面 | 基板 [-H,0]，金属 z=0 |
| 端口 | FeedShift=10×NEAR，MeasPlaneShift=端口段/3 | FeedShift=10×旧MESH，默认中点测量面 |
| 停机 | NrTS=100000 不设 EndCriteria（默认能量判据）| EndCriteria=1e-4 |
| 辐射器件（patch/dipole）| 空气隙 λ0/4（上/侧）| 5mm/70mm 混合 |

- **mesh_resolution_mm 语义已变**：旧=边缘加密分辨率 → 新=网格 base 覆盖
  （0=自动 λ_sub/50）。0.5≈λ_sub/100 已收敛档（E4-fine 实证），0.3 在
  16GB 内存档不可承受（cell 数 ×9）。
- **判健康度用 β 金标准（#162）**：跑一次官方 notch（30s），
  `median(CalcPort.beta)` 对照 skrf HJ 闭式 εeff，±1% 内即引擎正确。
- **uf_ref/uf_inc 相位不可用于物理判读（#161）**——含端口分解伪象；
  幅值与 β 可信。
- 收敛证据（E4/E4-fine）：谷位 2.15→2.205GHz（base 减半漂 -2.5%，收敛），
  谷深 -26/-29dB，S21/S31@谷 -3.4/-2.9dB 教科书功分；旧口径同点 1.53GHz
  且每档漂 -8% 发散。

## 1. Wilkinson 功分器（Ansys 官方 FDTD 例，Pozar 例 7.2）

来源：Ansys Optics「Wilkinson power divider」（FDTD/RF，含 .fsp/.lsf 工程文件）。

| 项目 | 官方口径 |
|---|---|
| 拓扑 | 输入 Z0 → 双 √2·Z0 λ/4 **环形臂** → 双 Z0 输出（Port1 左入，Port2/3 右侧上下出） |
| 阻抗/线宽 | h=1.59mm εr=2.2 上：50Ω=3.195mm、70.7Ω=2.804mm（由微带综合公式算，**不拍脑袋**） |
| 臂长 | 环周长 = λ/4 = 55.5mm @1GHz |
| 隔离电阻 | 2Z0=100Ω，2D 片状材料，跨接在**输出侧双臂末端之间** |
| 网格 | 走线区 mesh override；弯曲/斜走线区 dx=dy；直走线对齐坐标轴即可 |
| 验收基准 | S11=-40dB、S32 隔离=-43dB、S31=-3dB @f0（中心频率偏差 <1%） |
| 多端口口径 | N 端口需 N 次激励；利用对称/互易可减少次数 |

对照结论（我们的 openEMS 直臂简化版）：
- 环形臂 → **直臂是合法简化**（轴对齐网格约束），但阻抗角色必须精确：本栈
  （rogers4350b h=0.508 er=3.66）50Ω=**1.113mm**、70.7Ω=**0.604mm**、35.35Ω=
  1.871mm——**曾经把 branchline 的 35Ω/50Ω 线宽错搬给 wilkinson 当 50Ω/70.7Ω，
  臂阻抗差 17%，是失配主因**（教训：线宽必须用 skrf HJ 综合精算，见
  core/synthesis.py inverse_width）。
- 臂长 λ/4 = c/(4·f0·√εeff)，εeff 用 Hammerstad 闭式（w=0.604 → 2.73 → 18.1mm
  @2.5GHz）。

**直臂 vs 环形臂的资料依据（2026-09-02 补查）**：
- Wilkinson 1960 原始论文与 Pozar 教科书（Wikipedia 词条沿用的经典微带图）
  画的就是**直臂**：电学定义只要求"Z=√2·Z0、电长度 λ/4 的传输线"，对几何
  形状无要求——直臂/环形/折弯（45° chamfer）都是版图选择。
- 环形版（Ansys 官方例、Circular Wilkinson 论文等）的动机是**版图紧凑和
  多路扩展**（环形便于 N 路圆周分布），不是电学优越性。
- FDTD 视角直臂**更优**：笛卡尔网格下曲线走线产生阶梯化（staircasing）
  误差，Ansys 官方例自己也要求"弯曲/斜走线区 dx=dy 特殊加密"，直臂轴对齐
  零阶梯误差、网格更省。结论：**保持直臂**，环形留作版图紧凑需求时的选项。

## 2. Patch 天线（openEMS 官方 Simple Patch Antenna 教程，CC BY-SA）

- 馈电 = **LumpedPort 底馈**（50Ω，跨基板厚度 z，2mm 宽，馈点在谐振轴上
  x=-feed_offset）——不要自创边缘微带馈（悬空、网格敏感）。
- patch_len = 谐振 λ/2 轴；官方例 30mm(谐振)×40mm @εr3.38 h1.524。
- 官方例口径：地=全尺寸 PEC；基板 z 向 ≥4 层网格；λ/20 加密 + SmoothMeshLines。
- **实现状态（2026-09-05 冒烟审计后对齐）**：`_patch_lines` 已按官方口径重构
  （LumpedPort 0.2×2mm 盒、x=-feed_offset、盒边进 `_near_points`、侧界全
  MUR）。历史两轮失败均已有根因：①"零宽探针 |S11|≡1"=激励体积坍缩
  （盒未进网格，非引擎缺陷，官方同款盒式可行）；②"微带边缘馈"冒烟病态
  （辐射器件 λ0/4 空气隙把域扩到 ±(BOARD+λ0/4) 后端口面仍贴 ±BOARD——
  馈线止于域中违反端口贴 PML 铁律；且馈点 x=0 是 patch_len 谐振模场节点，
  谐振激励不起来）。证据：patch 冒烟审计存档（含三视图 PNG 复核）。
- 闭式 sanity：patch_len=40mm @εr3.66 h0.508 patch_w=50 → f_res≈2.16GHz
  （Balanis: ε_eff=(εr+1)/2+(εr-1)/2·(1+12h/W)^-1/2≈2.96，含 ΔL 边缘延伸）。
  **判读窗口 2.2-2.6GHz 的下沿按此修正为 ~2.05GHz**——谷位落 2.05-2.25GHz
  且深度 ≤-10dB 即与健康模型一致；若落 2.3-2.5 反而说明 ε_eff 口径错误。

## 3. MSLPort/LumpedPort 使用铁律（openEMS 官方教程 + 本地 ports.py 源码）

1. MSLPort 的 start/stop = **馈线段本身**（端口自画金属；stop 的 z 定
   upside_down）。激.plan面在 stop 端，`FeedShift=10×分辨率` 把激励面从金属
   端头内移（官方 NotchFilter 做法）。
2. **端口平面必须落在均匀线段 + 基板边缘**——压在 T 分叉/不连续点上会让
   CalcPort 入射/反射分离失效（实测 |S11|>1 非物理）。
3. **激励/LumpedPort 盒必须与网格线对齐**（盒边加进 mesh.AddLine）：0.2mm
   盒不与 0.5mm 网格对齐时激励体积坍缩为零 → |S11|≡1 无能量馈入。
4. LumpedPort 签名 = (CSX, port_nr, R, start, stop, exc_dir, excite)——无
   p_dir；MSLPort 才是 (…, prop_dir, exc_dir)。

## 4. openEMS 运行口径

- `disable_dumps=True` 只能关**场转储**；openEMS 还会强制写 `et` 端口时间
  信号文件（每时间步刷盘，实测 1.3MB/s、GB 级、CPU 被压到 <10% I/O bound），
  无法关闭——长跑瓶颈在此而非计算本身。修正后的真实谐振结构 FDTD 要跑满
  能量衰减（激励坍缩的坏模型反而"秒收敛"，280s 是假快）。子进程 kill 要
  连带 kill 孙进程 openEMS.exe。
- 单位约定：FakeAdapter/skrf Network 频率 = **Hz**；OpenEMSSolver 结果 = **GHz**。
  跨适配器比较必须显式归一（空交集会静默通过）。
- 带内偏差比较：双方曲线在公共网格 np.interp 插值后再算 |Δ|。

## 5. 参考实现库

- [rookiepeng/microwave-structures](https://github.com/rookiepeng/microwave-structures)：
  CST 设计文件库（含 24GHz Wilkinson 45° 转角），布局参考。
- [matthuszagh/pyems](https://github.com/matthuszagh/pyems)：openEMS Python 高层封装。
- [Ansys Wilkinson 官方例](https://optics.ansys.com/hc/en-us/articles/360042528713-Wilkinson-power-divider)：
  本表第 1 节来源（Pozar Example 7.2）。正文口径：h=1.59mm εr=2.2，50Ω=4.9mm、
  70.7Ω=2.804mm（Pozar Eqs 3.195/3.197），环形臂周长 λg/4=55.5mm，100Ω 片状电阻，
  双激励利用对称/互易省仿真次数，z-min 用 Metal 边界当地面。
- [openEMS 官方教程索引](https://docs.openems.de/python/openEMS/Tutorials/index.html)；
  [MSL NotchFilter](https://docs.openems.de/python/openEMS/Tutorials/MSL_NotchFilter.html)；
  [Simple Patch Antenna (wiki)](https://wiki.openems.de/index.php/Tutorial:_Simple_Patch_Antenna.html)。
- [Microwaves101 Wilkinson 条目](https://www.microwaves101.com/encyclopedias/wilkinson-power-splitters)：设计公式速查。

## 5b. 官方文档读取方式与 MCP 工具箱（2026-09-02 实测）

**背景**：内置 WebFetch 抓 Ansys Optics（Zendesk）会 403/连接超时；改用
配置好的外置 MCP 工具箱后解决。逐个实测结果：

| MCP 工具 | 实测结果 | 本项目用途 |
|---|---|---|
| `web_reader` (webReader) | ✅ 完整读取 Ansys 官方例全文 | **受反爬/需代理的官方文档首选**；还纠正了截图看不清的口径（官方 50Ω=4.9mm） |
| `web-search-prime` (web_search_prime) | ✅ 返回结构化文献列表（标题/链接/摘要，Wilkinson 案例命中 COMSOL/SIMWORKS/CST 教程） | 建模借鉴搜索（官方例/商业软件案例/论文） |
| `zai-mcp-server` (analyze_image / ui_diff_check / analyze_data_visualization / extract_text_from_screenshot / understand_technical_diagram) | ✅ 多模态读图 | **多模态审计核心**：三视图 PNG 复核、UI 与参考截图 diff、S 曲线图分析、截图提取文字/报错诊断 |
| `zread` (get_repo_structure / read_file / search_doc) | ⚠️ 热门仓库可用（langchain ✅）；小众 RF 仓库未索引（microwave-structures、pyems 均报 repo not found） | 读大型开源库结构/文档；小众仓库 fallback 用 `git clone` 到本地工作区 |
| `node_repl`（Browser Use） | 未实测 | 需登录/交互的官方资料页面（.fsp 工程下载等） |
| `computer-use` | 未实测 | 桌面级 GUI 审计（如打开 HFSS/CST 对照建模） |

**选型流程**：受反爬的官方文档 → `web_reader`；找借鉴案例 →
`web-search-prime` + 截图互证；图像复核 → `zai-mcp-server` 系列读图；
参考仓库 → 先 `zread`，未索引则 clone 到工作区再本地读。

## 6. 校准前验模型的审计工具链

1. 文本：逐行读 render_script 生成的 simulation.py；
2. 视觉：`scripts/gen_three_view_audit.py` 出三视图 PNG（人工/多模态复核）；
3. 文献：本表 + 官方教程；
4. 数值：谐振点对照闭式解；端口健康检查（|S11|>1 即端口/网格错误）；
5. 标定：以上全过后才允许 `scripts/derive_fake_calibration.py` 生成校准锚。

## 7. CPW 端口口径（2026-09-08 侦察定稿）

- 本机 openEMS v0.37.0-rc1 绑定有一等 CPW 端口：`CPWPort/AddCPWPort(
  port_nr, metal_prop, start, stop, prop_dir, exc_dir, gap_width,
  excite=0, FeedShift/MeasPlaneShift/Feed_R)`（ports.py L1117+，逐条
  对照源码）。
- 口径：start/stop 宽度范围=**中心带宽度**（端口只画中心导体段）；
  gap_width=每侧缝宽；两侧地金属**自画**（端口不补）；exc_dir='z'
  （height 方向=探针 z 向，同 MSL 惯例；width 方向由 cross(prop,exc)
  推导为 x）；FeedShift/MeasPlaneShift 语义同 MSLPort。
- 合成/分析：skrf media.CPW(w, s, h, ep_r)（反解 w 用 bisection，同
  mline 手法）；fake 闭式同 mline（β=2πf√εeff/c）。

## 8. dipole 官方口径（2026-09-08 侦察定稿）

来源：openEMS 官方 Helical Antenna 教程（Python，wire primitive +
LumpedPort 馈电全套）与 Dipole SAR 教程（wiki.openems.de
"Tutorial: Dipole SAR"）。

- 振子 = **wire primitive**（AddCurve/AddCylinder，radius 参数）或薄
  带 box；中央 gap 处 **FDTD.AddLumpedPort(port_nr, R, start, stop,
  'x', 1.0, priority=5)** 直馈（跨 gap，norm 方向沿振子轴）。
- **自由空间器件：无基板、无地**，域全 MUR（官方 Helical 用
  ['MUR'×5, 'PML_8']）+ nf2ff box（远场接口）。
- 馈电阻：半波偶极子谐振阻抗 ~73Ω（官方 Helical 示例 R_in=120Ω 是
  螺旋特定值）——模板口径 R=z0_ohm(50)，S11 判读窗放宽（-10~-15dB）。
- 我方 _dipole_lines 现状缺陷（确认）：振子贴基板顶面 + MSL 微带
  馈线侧面接入 = "微带馈偶极子"混合怪 + MSLPort 悬空；render_script
  底边界恒 PEC（dipole 镜像破坏输入阻抗）。修复=重写 _dipole_lines
  （LumpedPort 中央直馈）+ render_script 底边界 per-template 特判
  （dipole→MUR 且域 z 向下延 λ0/4）+ fake 派发分支 + meta 同步。

## 9. rat-race 180° 混合环（#208 理论核验轮定版，2026-09-09）

- 权威口径：Pozar《Microwave Engineering》§7.5（180° hybrid ring）；
  环特性阻抗 Z√2=70.7Ω，周长 3λg/2，arcs λ/4×3 + 3λ/4。
- **规范角位（#208 定版，pt5 实测背书）**：Σ=0°（geo）、out1=60°、
  Δ=120°、out2=300°——out1/out2 分居 Σ 两侧 λ/4（环相位 90/450），
  Δ 在 λ/2（180），大弧 3λ/4 扫 Δ→out2 之间。**out2 不得放 geo 180**
  （Σ 的直径对点=环相位 270=两侧各 3λ/4 的"匹配直通"位置：实测
  -0.54dB 直通 + 3λ/4 倒阻抗匹配 S11=-11dB，#208）。
- 理想 S 矩阵（端口 1=Σ/2=out1/3=Δ/4=out2，f0 闭式，Y 矩阵推导）：
  S=(-j/√2)·[[0,1,0,1],[1,0,1,0],[0,1,0,-1],[1,0,-1,0]]——Σ 激励输出
  同相、Δ 激励输出反相（180° 混合环定义性质）、Σ↔Δ 与 out1↔out2 隔离。
- 工程注意：70.7Ω 环与 50Ω 馈线 εeff 差 ~4.5%（2.72 vs 2.85），
  λg 分开精算；径向馈必须真带宽栅格化（每列盒 y=线心±W/(2cosθ)，
  中心线弦画法在 FDTD 网格不导通，#212）。

### 9.1 k 定版结论（2026-09-16）

- **k=1.0975 归属 MESH_ARTIFACT（HFSS 仲裁背书）**：HFSS 物理 R=17.344mm
  （无 k）balance 中心 2.465GHz / S11 谷 2.41GHz（仲裁存档
  verdict.k_attribution=MESH_ARTIFACT）；openEMS 直角坐标同一 k=1.0975 下
  hybrid 中心随网格细化上移（0.4mm 2.354 → 0.2mm 2.5225GHz，f_center_avg，
  openems_convergence.json），伪象随细化收敛而非几何问题。
- **k(BASE) 标度与有效域**（`openems_templates.ratrace_ring_mesh_k`，仅 adapter
  渲染层，#219③）：k(BASE)=1+(k02−1)·((k04−1)/(k02−1))^t，t=(BASE−0.2)/0.2，
  即 (k−1)∝BASE^α、α=log2(0.1654/0.0877)=0.915；锚 k(0.2mm)=1.0877 /
  k(0.4mm)=1.1654（一阶标度 k_needed=k_cur×F0/f_center_avg）；有效域
  [0.2,0.4]mm，域外夹到最近锚并在渲染脚本写"未定标档 clamp"（默认自动档
  BASE=λ_sub/50=1.1405mm → k(0.4)），禁止外推；近场线（_near_points）与几何段
  （_ratrace_lines）同 BASE 同 k。pt8 归档常数 `_RATRACE_RING_MESH_K=1.0975`
  仅存证不再消费。
- **真机回验（Σ 单激励进程隔离 #208）**：
  0.4mm k=1.1654 → balance 中心 **2.5013GHz**（对 2.5 +0.05%、对 HFSS 2.465
  +1.47%）、S11 谷 2.5088、bal 0.001dB、S11 −39.3dB、S31 −35.1dB、S21/S41
  −3.17dB 全门过，k_eff=1.1631（锚差 −0.2% ≤1% → 锚保留，756.8s）——一阶
  "中心∝k"标度精确兑现（1.0975→2.354 / 1.1654→2.505GHz）。
  0.2mm k=1.0877 → balance 中心 **2.525GHz**（对 2.5 +1.0%、对 HFSS +2.43%）、
  S11 谷 2.4575（−60.8dB）、avg 2.4912、bal 0.021dB、S11 −35.9dB、S31 −41.2dB、
  S21/S41 −3.15/−3.17dB 全门过，k_eff=1.0915（锚差 +0.35% ≤1% → 锚保留，
  13936.7s，受并发 HFSS 拖慢）。两锚均回验闭合，α=0.915 不变；0.2mm 档
  balance/S11 谷分裂 67.5MHz（0.4mm 仅 7.5MHz）是细网格固有特征，与 2026-09-12
  收敛核验（60MHz）一致——判中心一律用 f_center_avg，与锚导出约定同源。
  Δ 口（excite_port=3）未加跑（真机合计 4.08h，加跑将超 5h 预算；全 4×4 留 G8）。
- **柱坐标 k=1 为根治首选**（#219/#232，`render_ratrace_cylindrical`）：无阶梯化，
  0.4mm 2.470GHz / 0.2mm 2.4875GHz 直接回 HFSS 2.465GHz；直角坐标 k(BASE) 是
  阶梯化伪象的工程补偿——换网格档按标度取值、新档（<0.2 或 >0.4mm）必须重定标。
- **cap sliver 处置 = 保留原判据**（|行中心|>R_OUT 跳行，仲裁决议）：成本=带阈值
  变体+重定标+重跑 pt 系列 ≥8h 真机；收益=默认档 ±75°/±105° 弦量化楔形 0.27mm×4
  + 带顶 0.0651mm（=0.057·BASE）sliver，非电气主害（pt9 三门与本轮回验门全过）。
  k(0.4) 下 0.4mm 档候选判据已是**无操作**（顶行上缘 15.2921 > R_OUT 15.1842，
  中心圈覆盖 100%）；原"非无操作"断言曾因 round6→round4 双重舍入产生 8 行假差集
  而假绿，已改原始浮点比较并按实测钉值（test_ratrace_template.py，#122）。
- **权威数据**：k_finalize 仲裁与收敛核验存档（HFSS 仲裁存档的
  error/verdict 键为早期陈旧残留，已改名
  stale_error_run2 / stale_verdict_run2，与 ok=True/attempt=1 并存属数据卫生）。

## 10. Gysel 功分器（#211 理论核验轮定版，2026-09-09）

- 权威口径：Microwaves101 "Gysel power divider / even-odd mode
  analysis"（Gysel 1970 拓扑）。**六节 λ/4 环**：P1—[70.7Ω λ/4 臂]—
  P2—[50Ω λ/4 隔离线]—Δ1—[50Ω λ/2 桥带，中点开路悬空]—Δ2—[50Ω
  λ/4 隔离线]—P3—[70.7Ω λ/4 臂]—P1；Δ1/Δ2 各接 50Ω 外置负载
  （大功率意义：负载不贴片）。
- 隔离机制（偶/奇模）：偶模 λ/2 桥带中点开路→短路压 Δ→经隔离线变
  开路（负载支路输出端不可见）；奇模 P1 结点/桥带中点=虚拟地，输出
  只见隔离线端接的 50Ω 负载——Γe=Γo=0 → S22=S32=0。
- 判废锚（skrf 六段线+双负载装配）：无桥带朴素拓扑 S21=-6.53dB/
  S32=-15.6dB FAIL——λ/2 桥带是隔离的必要环节。
- 工程注意：70.7Ω 臂（w=0.6035，εeff=2.72）与 50Ω 线（w=1.1134，
  εeff=2.85）εeff 差 4.5%，λ/4 长度分开精算不可混用。

### 10.1 拓扑重设计：L-jog 等长变体（2026-09-16 离线审计定版）

- **问题**：矩形六节环只有 2 个自由边长——顶边桥带继承臂 λ/4 跨度
  2·arm_len=36.324mm，对 50Ω λ/2 设计值 2·iso_len=35.500mm 有 **+2.32%**
  二阶偏差（桥带 184.176°@2.5GHz）。#211 pt2 矩形真跑 S32=-32.6dB/
  S11=-26.7dB PASS（二阶效应），但该项残余未量化归因。
- **电路级归因**（无损线 Y 装配，`test_gysel_template._candidate_ring_s`
  固化，与 #206 角度装配互检 atol=1e-7）：矩形桥带相位误差把 @f0 S32/S11
  **封顶 -34.8dB**（-34.77/-34.78），为主因；junction 宽度台阶
  （0.6035→1.1134mm）与双臂对称性为二阶。
- **四候选对照**（@2.3/2.5/2.7GHz，S32/S11 dB）：

  | 候选 | 几何 | @2.5 S32/S11 | @2.3 S32 | @2.7 S32 | 取舍 |
  |---|---|---|---|---|---|
  | rect 矩形现状 | 桥带 2·arm_len | -34.8/-34.8 | -29.5 | -23.0 | 基线；2.7GHz 隔离 23dB<25dB |
  | trap 真斜梯形 | 隔离线斜置、桥带 2·iso_len | -90/-88 | -25.9 | -25.9 | 电路级同 ljog；**0.412mm 横移在 0.4mm 网格=1 胞**，斜边逐行栅格化要么 ~9µm/行亚网格步距触发 #152 CFL 塌缩、要么退化为折线——不采 |
  | **ljog L-jog 折线** | 竖直 YJ=17.338+横移 jog=0.412、Δ 在 x=±iso_len | -90/-88 | -25.9 | -25.9 | **定版**：六节电长度精确、轴对齐盒 #198 精确入网、#152 最小间距=jog、保 50Ω 桥带官方口径 |
  | z70 桥带 70.7Ω | 零几何改动（2·arm_len=70.7Ω λ/2 精确） | -116/-110 | -25.3 | -25.3 | @f0 理想但低带边隔离差于 rect 4.2dB（深度换带宽）、带边均分 -3.20dB 最差、偏离 50Ω 桥带口径——不采 |

  选型判据：@f0 电路级 S32 与 S11 均 ≤-40dB 优先、带边隔离 ≥25dB、对
  Microwaves101 官方口径偏离最小。ljog 的 @f0 残余 -90dB 来自 mm 三位
  舍入（精确 λ/4 喂入即与角度装配逐元素相等）。
- **L-jog 几何**（`_gysel_layout` 单一事实源，参数表仍 4 键，派生量不入
  schema）：jog=|arm_len−iso_len|、YJ=iso_len−jog、Δ 节点 x=±iso_len；
  方向无关（arm_len>iso_len 时 Δ 内移，反之外移），守卫 YJ>0 ⟺
  arm_len<2·iso_len 否则渲染 ValueError。#212 五判据全绿；0.4mm 档 jog
  间隙被 NEAR 平滑细分为 82.4µm 单元（≫1µm）。
- **EM 预期与定案口径**：电路级 -90dB 的理论增益会被两处未切角 90° 弯折
  （§bend 口径 |S11|<-15dB）与网格地板吃掉，候选天花板估 -35~-41dB 档；
  真机 pt3（mesh 0.4mm 双激励）定案判据=对比 pt2 基线（S32 -32.6/
  S11 -26.7dB）的改善量如实落账，硬门不变（β±2%、均分差≤0.5dB、
  S32≤-15dB、S11≤-10dB）；增益有限时如实 PARTIAL 不凑绿（#122）。

## 11. CPS 共面带 / 悬置带线（2026-09-15 侦察定稿；2026-09-18 口径改写）

闭式内核：`core/calculators.py` `_cps_ri` / `_suspended_stripline_ri`
（注册键 cps_analysis / cps_synthesis / suspended_stripline_analysis /
suspended_stripline_synthesis）。铁律 1c：所有常数出处如下，无拍脑袋值。
**独立数值裁判（#118）统一为 `core/quasistatic_fd.py`**（张量网格变分 FD Laplace，
网格线精确落导体缘/介质面，能量法 C=2W/V²，一阶 Richardson 外推；CLI
`scripts/fd_laplace_tline_referee.py`）——裁判自身先过已知基准才有资格裁判闭式
（校准前先验模型铁律）：微带 vs Hammerstad–Jensen（skrf，4 几何含 εr=9.8）+0.1~+0.3%、
CPS 半空间极限 (1+εr)/2 −0.1%、零厚度带状线空气 Z0 vs Cohn −0.1%、悬置带线
h→b 全填充 εr 精确（tests/unit/test_quasistatic_fd.py 钉住）。**此前两份未入库
的临时 FD（§11.1 旧表/§11.2 的 3.02；事后复核的 1.68/2.36）均
未经上述基准，其中 §11.2 两份互相矛盾（3.02 vs 2.36），全部撤下**——只有 CPS
标称 1.68 与本裁判 1.667 巧合一致（≤1%）。

### 11.1 CPS（coplanar strips，双等宽带夹中央缝，无地）

- 几何记号：带宽 w、缝 gap；a=gap/2（内缘半距）、b=gap/2+w（外缘半距）、
  基板厚 h、基板下方空气；k1=a/b，r(k)=K(k)/K'(k)（scipy ellipk(m)，m=k²）。
- **均匀介质（空气）闭式**：Wadell《Transmission Line Design Handbook》
  (Artech House 1991) p.83 eqs (3.4.6.1)/(3.4.6.3)-(3.4.6.5)：
  **Z0 = 120π·K(k1)/K'(k1)/√εeff**，等价 C_air = ε0·K'(k1)/K(k1) = ε0/r1。
  引用途径：MathWorks RF PCB Toolbox 官方例 "Analysis of a Coplanar Strip
  Transmission Line with no Conductor Backing"（a=内缘距 0.5mm、b=外缘距
  2.0mm，`z0_expected = 120π·ellipke(k)/ellipke(kp)`，MoM 求解器对拍到
  几 Ω 级网格差）。裁判空气线（20·b 域）Z0_air 150.46 vs 闭式 150.42（+0.03%）。
- **互补对偶核实（"对偶常数先核实再写死"）**：CPS(w,gap) 的 Babinet 互补
  结构=中心带 gap、缝 w 的 CPW，二者共用同一模量 k=gap/(gap+2w)；repo
  CPW 闭式（Qucs tech doc §12 Gupta 口径，与 `_cpwg_ri` 逐式吻合）
  Z_CPW=30π·K'/K/√εeff → **Z_CPS·Z_CPW = 120π·30π = 3600π² = η0²/4**（Booker
  扩展 Babinet 原理的经典常数）✔——120π 系数由对偶恒等式独立背书；曾推导
  出的 60π 变体与 η0²/4 矛盾，被 2D FD 数值裁判否决。
- **有限厚基板（FD 定标，2026-09-18）**：Gupta/Ghione 部分电容技术，介质超额
  项取接地板 tanh 映射 **k3=tanh(πa/2h_eff)/tanh(πb/2h_eff)**（同 `_cpwg_ri`
  的 k4 映射家族）：**C = ε0/r1 + (εr−1)·ε0/(2·r3)**，**εeff = 1+(εr−1)·r1/(2·r3)**，
  **Z0 = 1/(c·√(C_air·C))**。裸映射（h_eff=h）对无地薄基板**系统性偏低**——
  无地时介质场向基板外泄漏，等效于更厚的接地映射板：
  **h_eff = γ(εr)·h，γ(εr) = 1 + 0.9014·εr^(−0.6361)**（`CPS_H_EFF_GAMMA_C/P`，
  εr→∞ 场受限 γ→1；εr=3.66 γ=1.395）。定标源（`--refit-cps-gamma` 可复现）：
  裁判在 εr∈{1.5,2.2,3.0,3.66,4.4,6.15,10.2,12.9}×6 几何（w/gap∈{2.95/0.5,
  0.5/0.5, 1.27/0.508, 1.0/0.2, 4.0/1.0, 0.4/0.1}，h=0.508）逐 εr 相对误差最小
  二乘 γ（1.706/1.547/1.446/1.392/1.348/1.281/1.206/1.180，每档 max|err|
  ≤0.6%），再幂律拟合。独立验证族（εr=3.66，`--cps-family`）：a/h∈[0.05,1]×
  b/h∈[1.5,12] 35 点 **max|err| 1.4%、rms 0.7%**（裸映射 −2.9~−12.4%）；域外
  角落 a/h≥1.5 且 b/h≤3（窄带宽缝）残差 −2~−4% 如实。两支极限不受 γ 影响：
  h→0 εeff→1；h→∞ k3→k1 → εeff→(1+εr)/2（Wen 半空间口径）；gap→0 Z0→0、
  gap→∞ Z0→∞；Z0 随 w 单调递减；εeff∈(1,εr)。
- **裁判点表（w=s=0.5 εr=3.66，Richardson；test_cps_template 钉住）**：
  h=0.15/0.3/0.508/1.0/2.5/8.0mm → FD 1.5504/1.8359/2.0450/2.2222/2.3082/2.3280
  （h=8 vs 精确 2.33 −0.1%）；定标闭式 1.5199/1.8147/2.0379/2.2259/2.3111/2.3281
  （−2.0/−1.2/−0.4/+0.2/+0.1/0.0%；h=0.15 为 a/h=1.67 定标域边缘）。
  **旧表（1.4696/1.9665/2.2260/2.3592/2.3916）撤**：其 h=8 极限自偏 +2.8%
  即侧墙过近证据，曾使裸闭式"看似 ≤2%"。
- **标称（定标后口径）**：印制 CPS 天然高阻——rogers4350b h=0.508 上 gap=0.5
  可达域下限 ≈94Ω，50Ω 需亚 0.1mm 缝不可制造。**标称几何 w=2.95/gap=0.5 保持**
  （真机配对 #158：pt1 与复跑同几何；docs/templates/cps/meta.yaml 同源），该几何
  内核精算 **Z0=116.17Ω/εeff=1.6765**（FD 裁判 1.667 +0.6%；旧裸映射口径
  120Ω/1.571 撤）；120Ω 设计档在定标口径下 `cps_synthesis` 解 **w=2.4863mm**
  （εeff 1.7046，`synthesize_cps_model` 缺省目标）。
- **端口口径（openEMS）**：`openEMS.ports` 枚举实证只有 MSLPort/CPWPort/
  StripLinePort/CoaxialPort/RectWGPort/CircWGPort/CurvePort/LumpedPort/
  WaveguidePort——**无 CPS/slotline 端口原语**。模板用 **LumpedPort 差分
  直馈×2**（§8 官方 AddLumpedPort 范式，_dipole_lines 同法）：跨缝 [−gap/2,
  gap/2] norm='x'，R=闭式 Z0（render 期同源 `_cps_ri`，定标后 116.17Ω），
  port1 激励/port2 R 端接；CalcPort 参考阻抗同步取 R。带内 |S11| 深谷=Z0 锚；
  **εeff 锚如实降级为 S21 解缠相位斜率**（LumpedPort 无 beta 属性，
  sma_launcher 同坑），含端口元落格 ±1 BASE 的线长口径不确定度（±1.14mm/40mm
  → εeff ±5.7%）。无地 → 底界 MUR + 域向下延 AIR_TOP，端口在域内 → 侧界全 MUR。
- **预声明复跑门（scripts/smoke_cps_anchor.py `GATES`，#122 不因结果改门）**：
  G1 带内 |S11|max < −15 dB；G2 |εeff(S21 斜率)/εeff_FD − 1| ≤3% PASS / ≤7%
  PARTIAL（线长口径地板）/ 其余 FAIL；INFO 定标闭式 vs FD ≤1.2%（不设门）。
  FD 锚由判读器按实际几何**现算**（cps_quasistatic，20·b 域，≈0.8s）。
  **pt1 基线（cps 冒烟 pt1，2026-09-17，缺省网格 BASE 1.14/NEAR 0.285）**：
  |S11|max −23.9 dB 过；εeff 1.8909 vs FD 1.667 **+13.4% FAIL**（旧口径 vs 裸闭式
  +20.35%）。引擎侧候选由合规网格复跑分离：端口元落格线长（±5.7%）、z 域
  ±5mm MUR 非 PML、基板 4 格台阶化；建议差分线长（两 L）或落盘端口元 y 坐标把
  口径地板压到 ~1%。

### 11.2 悬置带线（suspended substrate stripline，基板对称居中）

- 几何口径（**本项定版，与早期设计稿 "[B/2−h, B/2]" 单侧写法的差异**）：腔高 b
  （上下地=域 z 边界 PEC），零厚度带在中面 z=b/2，厚 H_SUB 基板以带为中面
  **对称**悬浮 z∈[b/2−H/2, b/2+H/2]，两侧空气隙各 (b−H)/2。选对称填充的
  理由=验收锚 "h→b → (εr, _stripline_z0(w,b,εr))" 只对对称填充是物理真值
  （单侧填充 εeff 饱和于 ≈(1+εr)/2，永远到不了 εr）。
- **闭式**（`_suspended_stripline_ri`，未改）：两支精确极限锚=repo 零厚度对称带状
  线共形闭式 `_stripline_z0`（Cohn/Wadell 30π·K'(k)/K(k)/√εr，k=tanh(πw/2b)）：
  h→0 → (1, _stripline_z0(w,b,1))；h→b → (εr, _stripline_z0(w,b,εr))。中间 h
  填充因子取带状线共形电容比 **q(h)=r(k_b)/r(k_h)**，k_b=tanh(πw/2b)、
  k_h=tanh(πw/2h)；**εeff=1+(εr−1)·q**，**Z0=_stripline_z0(w,b,1)/√εeff**。
- **裁判定案（2026-09-18，`--ssl-series`；test_quasistatic_fd 钉住）**：q 式
  **中段系统性高估**（w=0.6 b=1.6 εr=3.66，Richardson）：h/b=0.0625/0.1875/
  0.3175/0.5/0.75/0.994 → FD 1.2842/1.6331/1.9286/2.3059/2.8511/3.6319，
  q 式 +3.9/+15.2/+20.6/+21.7/+15.5/+0.6%——方向与旧表结论（"q 式中段偏低
  −10~−27%"）**相反**。旧表（FD 1.769/2.394/2.777/3.106/3.388/3.656）与其
  标称 3.02 撤：h/b=0.0625（0.1mm 板悬在 1.6mm 腔）得 1.769 物理不合理（裁判
  1.284），且该临时求解器无任何已知基准对拍；事后复核的 2.36
  （2.412/2.376/2.356 序列）同样未过基准、与验证序列 2.084/2.088/2.092 不符，
  一并撤。
  **标称几何真值（w=0.731 b=1.016 h=0.508 εr=3.66）**：d0=b/40、b/80 →
  2.0836/2.0877，**εeff_FD=2.092**；Z0_air 81.19（Cohn 81.26，−0.08%）→
  **Z0=56.1Ω**（**2026-09-19 SSL 闭式已重定标 softmin 修正族、新 50Ω 点 w=0.9058——见文末「SSL 重定标追加」块，本段 2.092/56.1 保留为 w=0.731 历史锚**）——q 式 2.641/50.0Ω **高 +26%**：按 q 式综合的"50Ω 标称线"真值
  ≈56Ω。标称几何保持不动（真机配对 #158、docs meta 同源）；**SSL 闭式重定标=
  followUp**（裁判定点迭代：真 50Ω 需 w≈0.897mm，εeff≈2.028；重定标后
  TEMPLATE_NOMINAL/meta/fake 锚同步）。
- **StripLinePort β 口径审（离线定案）**：
  1. 源码口径（openEMS ports.py L914+）：U 探针=带中心线到上/下地各一条
     （weight 0.5 求和=平均带-地电压）×测量面附近 A/B/C 三条网格线；I 探针=
     包住全带宽 ±1.5 格的两环；**β=√(−dU·dI/(U·I))、Z=√(U·dU/(I·dI))**——电报员
     方程恒等式，对单一准 TEM 模的前/后向任意叠加**精确**成立（驻波因子抵消），
     离散误差二阶 (βΔ)²/6≈0.16%@BASE 1.14mm；探针距激励 13.3mm
     （MeasPlaneShift=(Y0+BOARD)/3）为洁净区。
  2. **pt1 归档零仿真回放**（tests/unit/test_c9_smoke_judges 钉住）：端口 β
     74.42 rad/m（εeff 2.0172）vs S21 解缠相位斜率（测量面间距 93.33mm）74.46
     （2.0193）**差 0.05%**；f0 处 S21 绝对相位 mod 2π −0.664 只与端口 β
     （−0.663）吻合，q 式/2.36 候选给 −1.664/−1.230——**端口三点差分 β 是引擎在
     该网格下的真实传播常数，"三点差分在非对称介质下有偏"假设否证**；差分探针
     直读 β 口径合法，判读器保留为主口径并加自洽门 G0。
  3. **"引擎 S11 隐含 εeff≈2.64、否定 3.02"推理撤**：它假设引擎空气阻抗=Cohn
     81.2Ω；实测引擎 L'=Z·β/ω=2.378e-7 H/m 比 Cohn 2.708e-7 **低 12%**（粗网格
     有效带宽化：带 0.731mm≈2.6 NEAR 格、b/2=4 z 格），引擎自洽口径 √εeff=
     Z0_air,eng/Z=71.5/50.2 → 2.03≈β 口径。|S11| −52.9dB 只说明"该网格下引擎线
     ≈50.2Ω"，既不背书 2.64 也不否定别的值；按裁判真值 Z=56.1Ω，网格收敛后预期
     |S11|≈−24.8 dB（可证伪预测）。
  4. 三源对账：裁判 2.092 / 引擎（粗网格）2.017（−3.6%）/ q 式 2.641（+26%）——
     **引擎与真值最近**，偏差归网格（基板 4 格、带 2.6 格），非端口口径。
- **预声明复跑门（scripts/smoke_suspended_stripline_anchor.py `GATES`）**：
  G0 |εeff(β)/εeff(S21 斜率)−1| ≤2.5%（超限=端口 β 不可判读 → UNDECIDABLE）；
  G1 带内 |S11|max < −10 dB；G2 |εeff(β)/εeff_FD−1| ≤3% PASS / ≤5% PARTIAL /
  其余 FAIL；G3 |ZL/Z_FD−1| ≤5%（ZL 优先 port_beta.csv 新列 re_zl1_ohm，缺列由
  S11 反演 ZL=50(1+S11)/(1−S11)，H1 定案）。FD 锚按实际几何现算。模板 beta 块
  （2026-09-18）前两列契约不变，追加 beta2/re·im_zl1·zl2/plane_dist_m（两测量面
  精确间距，G0 不再含网格吸附 ±BASE/2 不确定度）。**pt1 基线**：G0 0.1% ✓、
  G1 −56.4 dB（带内）✓、G2 −3.6% PARTIAL、G3 ZL≈50 vs 56.1 −11% ✗ → **PARTIAL**。
  复跑：z 网格基板 ≥8 格、NEAR ≤w/6，预期 G2/G3 同向收敛到 FD；
  闭式 q 式对照只作信息项。
- **端口口径（openEMS）**：StripLinePort×2（v0.37 源码 L914+，`height`=带到
  每面地的对称距离=b/2，本 session inspect 实证），同 stripline 模板已真跑
  PASS 的口径；β 金标准可用（port_beta.csv）。top_bc/bottom_bc 均 PEC，
  z 域 [0,b]，基板两面/中面/壳边全部精确入网（#198）。
- 标称：b=1.016（=2·H_SUB，与 stripline 同 z 域、网格友好）、H_SUB=0.508
  对称居中、q 式 50Ω → **w=0.731mm，q 式 εeff=2.641（裁判真值 2.092/56.1Ω，
  见上）**。扰动域：审计 ×1.37 扰动 b→1.392 仍 >H_SUB ✔（对称填充守卫为
  H_SUB<b，非单侧的 h<b/2；早期设计稿 "b≥2.8h" 系单侧口径，本项不适用）。

## 12. 贴片阵列族：1×4 corporate / 2×2 H-tree / 1×3 串馈贴片阵（2026-09-15 理论核验定稿）

本节为 openems_templates.py 阵列族段的权威口径出处（antenna2 §同款制度）。

- **权威口径（铁律 1c/1b，先理论后几何）**：
  - C. A. Balanis, *Antenna Theory: Analysis and Design*, 3rd ed., Wiley,
    Ch. 6 "Arrays: Linear, Planar, and Circular"：ULA AF 闭式
    |sin(Nψ/2)/(N sin(ψ/2))|（§6.3）、方向图积定理、侧射 HPBW 渐近式
    0.886λ/(Nd)（**N=4 精确 26.32° vs 渐近 25.38°，偏 3.7%**——单测钉死，
    渐近式不冒充精确值）、栅瓣判据 d/λ ≤ 1/(1+|u0|)、§6.10 矩形栅格平面阵
    可分离积 AF(θ,φ)=AF_x(sinθcosφ)·AF_y(sinθsinφ)。
  - C. L. Dolph, "A Current Distribution for Broadside Arrays Which Optimizes
    the Relationship Between Beam Width and Side-Lobe Level", Proc. IRE, 1946
    （Chebyshev 等副瓣加权；副瓣判据 `peak_sidelobe_level_db`）。
  - Balanis Ch. 14 "Microstrip Antennas"（传输线/腔模型）：W = c/(2f0)·√(2/(εr+1))、
    εeff（Hammerstad）、ΔL 边缘修正、L = c/(2f0√εeff)−2ΔL——与
    `core/calculators.patch_length`、`core/synthesis.synthesize_patch` 同公式，
    `core/symbolic_fit.patch_resonance_hj_ghz` 为独立裁判（f0 = c/(2(L+2ΔL)√εeff)）。
    双缝方向图闭式：`core/array_synthesis.patch_element_field`（等效磁面流同相、
    地面镜像、上半空间；E 面 ∝ cos((k0L/2)sinθ)、H 面 ∝ cosθ·sinc((k0W/2)sinθ)，
    函数文档含矢量推导）。馈电阻抗一阶口径（fake 常数出处，未标定不进锚）：
    单缝电导小缝近似 G1 ≈ (W/λ0)²/90 → 边馈 Rin(0)=1/(2G1)，插入馈
    Rin(y0)=Rin(0)cos²(πy0/L)；5.8GHz 标称 Rin(0)=419.4Ω、Rin(0.3L)=144.9Ω。
  - **openEMS 无官方阵列教程**——官方基线仅 Simple Patch Antenna（§2），本族
    单元几何沿用其口径（底馈 LumpedPort、基板延伸到侧界、z-min PEC 地、nf2ff
    盒域缩 4×网格）；阵列层离线裁判 = 积定理闭式（D5 内核），**不杜撰官方
    阵列例**。
- **设计点 f0=5.8GHz**：BOARD=60e-3 为全模板共享字面量（禁改）——2.4GHz 下
  1×4 λ0/2 间距需 ~222mm 装不进 120mm 板。单元间距 0.484λ0=25.0172mm（略缩
  λ0/2）：#212 审计 ×1.37+0.013 扰动域下 3d+W=119.79mm ≤ 120mm 恰装下；
  串馈取 3 元是同扰动域上限（4 元 4L+3λg/2 超板）。线宽/λ 段 skrf HJ 精算：
  50Ω w=1.112mm（εeff 2.8579 → λg/2=15.2876mm）、70.7Ω w=0.6025mm
  （εeff 2.7294 → λ/4=7.8217mm）；单元 W=16.9311 / L=12.9058 / 插入 0.3L。
- **拓扑**：1×4 corporate（插入馈单元 + 全 λ/4 70.7Ω 变换树 + 底探针集总馈，
  全 MUR）；2×2 H-tree（顶排缺口向 +y，馈线走元列外侧走廊自上入缺口——同层
  零交叉）；1×3 串馈（λg/2 互联接辐射边中心，MSLPort 自 y=−BOARD 入，单轴 y
  PML；相位账：λg/2 段 180° + λ/2 贴片两边场反相 180° ⇒ 同相侧射）。
- **真机冒烟判据（scripts/smoke_array_anchor.py 已备离线判据函数）**：
  S11 谷位 f0±12% 窗 + 谷深 ≤−6dB（s11_db_min 语义 #195）；far_field nf2ff
  主瓣天顶 |θ|≤5°、阵列面 HPBW 与闭式（patch_element_field×AF，同算法
  core/farfield.hpbw_deg）相对偏差 ≤30%、Dmax 与闭式（无限地面上半空间积分，
  标称 10.53/11.15/11.32 dBi）线性比偏差 ≤30%、η=Prad/P_acc∈(0.3,1.05]。
  预算 NrTS=100000 分钟~小时级，逐模板串行单飞。

## 13. C4 耦合器族 II：耦合线定向耦合器 / 两节分支线 / Lange（#206 理论核验轮，2026-09-16）

三模板均为 **4 端口 MSLPort 全建 + excite_port 轮转**（#208 进程隔离，9 列
单激励 CSV，`openems_rotation.solve_smatrix_openems` 通用装配），端口面贴
PML 边界（§3 铁律），f0=2.5GHz、rogers4350b h=0.508 er=3.66；线宽一律 skrf HJ
精算（`inverse_width`），(Z0e,Z0o)→(w,s) 走 KJ 二维反解
`coupled_bpf_width_gap_from_zee_zoo`（coupled_bpf 段既有内核）。口径全账与
假设清单在 `openems_templates.py` 文末 §C4 段首；单测 `test_coupler2_templates.py`。

### 13.1 耦合线定向耦合器 cline_coupler（Pozar《Microwave Engineering》4th ed. §7.6）
- 闭式：电压耦合 C=10^(−C_dB/20)；匹配条件 Z0²=Z0e·Z0o 下
  **Z0e=Z0√((1+C)/(1−C))、Z0o=Z0√((1−C)/(1+C))**，C=(Z0e−Z0o)/(Z0e+Z0o)。
  频响（同步 TEM）**S31=jC·sinθ/(√(1−C²)cosθ+j·sinθ)、S21=√(1−C²)/(…)**，
  S11=S41=0；θ=90° 处 |S31|=C（同相）、S21=−j√(1−C²)。
- 端口约定（后向波）：1 输入（线 A 近端）、2 直通（线 A 远端）、3 耦合
  （线 B 近端，**与输入同侧**）、4 隔离（线 B 远端）。
- 独立互检：偶/奇模 2 端口叠加装配 `_coupled_section_s4` 在 θ=60/75/90/110°
  与 Pozar 闭式逐位一致（|Δ|<1e-9，单测钉住）。
- 10dB 标称：C=0.31623 → (Z0e,Z0o)=(69.371,36.038)Ω → KJ 反解
  **(w,s)=(0.9243,0.0820)mm**，εeff_e/o=2.9922/2.4663 → λ/4 @平均 εeff
  **18.1469mm**；50Ω 馈线 1.1117mm。
- **非同步残差（微带定向性固有极限，Pozar 明述）**：真 KJ 相速下 @f0
  |S31|=−10.045dB、**S41=−23.3dB、S11=−32.9dB**（定向性 ≈13dB，未做相速补偿/
  锯齿缝）。fake 默认走真相速（coupled_bpf 同口径），`synchronous_tem=True`
  为理想极限（|S31|=−10.000dB、S11=S41 数值零）；冒烟按 −23dB 口径判读，
  不是缺陷。
- 几何：50Ω 馈线（1.11mm）比线心距（1.006mm）宽，同心直连必短路 → 馈线外推
  （内缘净距 5mm ≈10h，并行段串扰 <−45dB 一阶）+ 横向搭接段（bend 族同类
  不连续性，进冒烟偏差项）。#212 审计分组 ({1,2},{3,4}) 双 DC 隔离。

### 13.2 两节分支线 branchline_2sect（Pozar §7.5 偶/奇模推广；Levy & Lind 1968）
- 出处：Pozar 4th ed. §7.5 分支线偶/奇模分析推广至两节；R. Levy & L. F. Lind,
  "Synthesis of Symmetrical Branch-Guide Directional Couplers," IEEE Trans.
  MTT-16(2), pp. 80–89, 1968（对称分支导综合）；Microwaves101 "Two-section
  branchline coupler" 页（二级参照，独立印证族关系与 35% 带宽）。
- 二分口径：沿水平中面二分，支臂切成 λ/8 半桩（偶模 PMC=开路桩
  +j·Y_b·tan(θ_b/2)、奇模 PEC=短路桩 −j·Y_b·cot(θ_b/2)），半电路
  ABCD=桩(Y_b1)·线(Z_a)·桩(Y_b2)·线(Z_a)·桩(Y_b1)；**S11=(Γe+Γo)/2、
  S21=(Te+To)/2（直通=同线远端）、S31=(Te−To)/2（耦合=对角）、
  S41=(Γe−Γo)/2（隔离=同侧）**。映射校验：单节 (Z0/√2, Z0) 代入复现 Pozar
  S21=−j/√2、S31=−1/√2、S11=S41≈1e-17。
- **f0 解为单参数族**（本轮多起点数值解 + 归纳）：**Z_b1=(1+√2)Z0=120.71Ω
  （外支臂）、Z_b2=√2·Z_a²/Z0（中支臂）、Z_a 自由**——Microwaves101 独立
  表述逐字一致（"end impedances must remain at [1+√2]×Z0 … Z3=√2×Z1²/Z0"）。
  标称取 Pozar 经典点 **Z_a=Z0 → (50, 120.71, 70.71)Ω**；最平坦匹配解
  Z_a≈0.72·Z0 保留为 `main_z_ratio` 选项。
- 带宽（TEM 同步裁判，单测钉住）：±1dB 均分 **35.0%（两节）vs 25.8%（单节）**
  （Microwaves101 同页 35%）；−20dB 匹配/隔离 **24.2% vs 10.5%**。f0 处
  S21=−1/√2（−180°，两 λ/4）、S31=+j/√2（+90°），正交。
- 标称几何：w_main/w_out/w_mid=1.1117/0.1620/0.6024mm（HJ）；主线节
  λ/4=17.7338mm（εeff 2.8579）；**支臂跨度=外/中支臂 λ/4（18.7144/18.1465）
  均值 18.4304mm**——矩形拓扑单跨度 vs 两支臂 εeff 不同的固有二阶偏差
  （≈±1.5%，gysel 桥带同类），闭式残差 @f0 S11≈−38dB，如实记录。
- 四角 50Ω 馈线沿 x 引出（P1 左上入 / P2 右上直通 / P3 右下耦合 / P4 左下
  隔离），x 单轴 PML；单导体网络（审计默认分组）。

### 13.3 Lange 电桥 lange（Pozar §7.6 Lange 节；J. Lange, IEEE-MTT-S 1969）
- 四线换算（Pozar）：相邻对 (Z0e,Z0o) → 等效两线
  **Ze4=Z0e(Z0o+Z0e)/(3Z0o+Z0e)、Zo4=Z0o(Z0o+Z0e)/(3Z0e+Z0o)**，
  C=(Ze4−Zo4)/(Ze4+Zo4)、Z0=√(Ze4·Zo4)。设计式（反解）：
  **Z0e=Z0(4C−3+√(9−8C²))/(2C√((1−C)/(1+C)))、
  Z0o=Z0(4C+3−√(9−8C²))/(2C√((1+C)/(1−C)))**。
- 自洽校验（单测钉住）：3dB（C=1/√2）→ 相邻对 **(176.216, 52.609)Ω**（文献
  常引 ≈176/52.6）→ 换算回 (Ze4,Zo4)=(120.711,20.711) → **C=0.707107、
  Z0=50.000 逐位闭合**。等效两线代入 13.1 偶/奇模内核 → f0 处
  |S21|=|S31|=−3.01dB、S31=+1/√2（耦合同相）、S21=−j/√2、S11=S41=0。
- 拓扑：**展开型**（Pozar fig 7.33(b)：交替指两端各以 air-bridge 并联，等效
  两线模型精确成立；折叠型中央交叉跳线为几何变体不在本项）。网络 A=指 1/3、
  B=指 2/4，DC 隔离；外指承馈 P1/P2=指 1 近/远端（输入/直通，**DC 相连**——
  Microwaves101/Steer "through 与 input 有 DC 连接"口径一致）、P3/P4=指 4
  近/远端（耦合/隔离）。air-bridge=抬高薄金属 z∈[H+0.1, H+0.15]mm + 竖直
  立柱 z∈[H, H+0.1]（**不落 z=0 地面**），同端 A/B 桥错位 0.55mm、两端分置
  → #212 bbox 连通审计恰判两组 DC 隔离（g=0 同层直通即两组短路红，单测
  "审计牙齿"钉住）。桥尺寸为 FDTD 网格尺度选择（真工艺 µm 级），如实标注。
- 标称几何：KJ 反解 **(w,s)=(0.1672,0.0386)mm**；指长 λ/4 @平均 εeff 2.4972
  =**18.9712mm**。**KJ 有效域提示**：g=s/h=0.076 略低于闭式标称有效域下限 0.1
  （u=w/h=0.33 在域内），如实记录不判废。相速口径：相邻对 KJ εeff_e/o 不是
  四线等效模相速（多导体模式，Ou 1975）→ fake 只给同步理想裁判（ratrace/
  gysel 窄带理想化同口径）；非相邻指耦合忽略（一阶 Lange 设计）。

### 13.4 验收与后置
- 离线验收（本轮已跑）：Pozar 闭式 vs 装配逐位、Lange 四线回代闭合、单节
  映射复现、两节族 f0 理想（ratio 0.8/1.0/1.25）、带宽两节 ≥ 单节、
  标称=设计函数 4 位舍入再生、内核幺正/互易、#212 五门 × 3 模板、fake 派发。
- 真机 openEMS 冒烟后置（followUp）：镜像 scripts/smoke_ratrace_anchor.py 走
  `openems_rotation.solve_smatrix_openems`（3 模板 × 4 激励轮转）；判读口径
  已写入各 meta.yaml `smoke_note`（cline 非同步 −23dB、2sect T 结/拐角偏差、
  lange 桥缝寄生 + g=0.076 提示）。lange 指缝 38.6µm 使 CFL 时间步很小，
  NrTS=100000 可能不足 30ns（coupled_bpf 冒烟 NrTS 截断同类），
  冒烟前先估 Δt。

## 14. SMA 边缘弹射 sma_launcher（2026-09-16 真机 FAIL 根治定版）

铁律 1c 权威口径（本节此前缺位——grep 0 命中）。模板 `sma_launcher`
（openems_templates `_sma_launcher_lines` / 几何单源 `sma_launcher_layout`）、
综合 `synthesize_sma_launcher_model`、fake `_sma_launcher_sparams`、离线接触图
`scripts/diag_sma_launcher.py`。

### 14.1 SMA 接口尺寸与同轴闭式（确定性内核，非手数）
- SMA 接口（IEC 61169-15 / MIL-STD-348）：中心针 Ø1.27mm → `r_i_mm=0.635`；
  PTFE 填充 εr=2.1（TEM 口径 εeff=εr 精确）。
- 50Ω 同轴闭式 Z0=(60/√εr)·ln(r_o/r_i) 反解 `r_o = r_i·exp(Z0·√εr/60)`
  = 2.124389mm（`sma_launcher_r_o_mm`，nominal 4 位舍入 2.1244）；外导体外径
  `r_os = r_o + shell_t`（壁厚 0.25mm）为**派生量**，不进 meta params
  （test_template_geometry_audit 单键 ×1.37 扰动会破坏 r_os>r_o）。
- 微带侧 50Ω 线宽 skrf HJ inverse_width（w_msl=1.1134mm @Rogers 4350B h=0.508）。

### 14.2 end-launch 文献几何口径（连接器厂商应用笔记，本模板建模依据）
- Copper Mountain Technologies《Optimal Fixture Design with End-Launch SMA
  Connectors》（coppermountaintech.com/optimal-fixture-design-with-end-launch-sma-
  connectors/，2026-09-16 web_fetch 读取）：① 中心针为小而平的接触片**水平压在
  微带上**（大针增加同轴→平面界面边缘电容，劣化回损）；② **连接器平面必须与
  PCB 板边齐平**（"flush with the side of the PCB"），接地翼间留竖直台阶/空气隙会
  在 6GHz 以上明显劣化回损；③ 顶层地与首层 RF 地以过孔缝合、铜皮直达板边不回缩；
  ④ 基板厚度须给中心针留合理离地净空（防短路/过量电容）；⑤ 其优化结果：
  30mil Rogers 4350B、41mil 线宽、12mil 缝下**仿真回损优于 22dB 至 20GHz**。
- 厂商口径（Cinch/Amphenol RF 132413/L-com/SV Microwave end-launch 系列，
  web_search 2026-09-16）：PTFE 介质、VSWR ≤1.2–1.3 至 18–27GHz（对应回损
  ≥17.7–20.8dB）；验收口径"验收靠文献曲线"：**带内回损常规 15–20dB，保守地板 −10dB**（objectives 口径）。
- 几何要点转译到 openEMS（全部由 `sma_launcher_layout` 单源给出，米）：
  针轴高 `Z_AX = r_os`（壳底切 z=0 PEC 夹具底板）；PCB 抬高 `Z_G = r_os − r_i − H_SUB`
  使**针底切线 = 基板顶 = 微带面 Z_TOP**（针水平搭焊，焊锡盒填实针下半侧）；
  同轴段 y∈[Y_B, Y_E]，`Y_E` = 板边切口面 = 壳端 = 微带起点（连接器面与板边齐平），
  针外伸 `pin_lay_mm=2.0` 搭在微带上；y<Y_E 无基板（空气盒 `sma_notch` 优先级 1
  盖过基板 0，PTFE 5、金属 10）；PCB 下方 z∈[0,Z_G]、y∈[Y_E,BOARD] 为实心夹具
  金属块（PCB 地 = 块顶；前脸与壳端实触；壳底切底板）——地链 壳—夹具—PEC 底板。
- **连接器体前脸（v2，真机实证必要件）**：与板边齐平的金属面墙 `sma_face`
  （x∈±(r_os+2 cells)、y∈[Y_E−2 cells, Y_E]、z∈[0, 壳顶+2 cells]，priority 4 <
  PTFE 环 5 / 针 10 → 同轴孔径按材料优先级挖空，针穿孔而过）。v1（无前脸，仅
  0.25mm 壳端环露在 PCB 之上）真跑 |S11|@2.5G=−4.0dB、结点阻抗 Z≈31−j61Ω
  （串联容性）；v2 加前脸后 −11.75dB、Z≈48.6+j26Ω（实部回到 50Ω，残余≈1.7nH
  串联弹射电感）——厂商口径"connector face flush with PCB edge"的电磁含义：
  针出孔处的上半场线需要前脸地墙作回流参考，缺失即结点高阻容性失配。

### 14.3 端口与域口径（H4/H5 根治）
- port1 = 同轴截面集总桥 LumpedPort R=50Ω：盒 x∈±r_i/2、y∈[Y_P0, Y_P0+port_len]、
  z∈[针顶 Z_AX+r_i, 壳内壁顶 Z_AX+r_o]，`exc_dir="z"`（径向）、priority 6（高于
  PTFE 5、低于金属 10）；针顶接触垫盒保证阶梯网格下桥下电极金属边连续。
  CoaxialPort 真机判废（pt2：β=4166 vs TEM 闭式 68、|S21|=−240dB）。
- **port1 面距 y-min 边界 12 cells**（`_SMA_PORT_CELLS_FROM_BOUNDARY`：越过 PML_8
  8 cells + 4 cells 净空）；开口同轴端再后退 2 cells。根治前 port1 距边界 0.5mm
  整体落在 PML_8 内（PML 边 −59.13mm，0.4mm 档实测）。
- 域顶 = 壳顶 + AIR_TOP（5mm）；根治前域顶距壳顶仅 0.251mm=1 cell（H5）。
- β 金标准只锚 port2（MSL HJ εeff）；LumpedPort 无 beta 属性。

### 14.4 真机 FAIL 根因实证（精确接触图，禁 bbox；legacy 接触图留档）
pt2 签名：|S11|=+5.42dB（非物理）、|S21|≈−375dB（零传输）、port2 表观 εeff≈2866。
`scripts/diag_sma_launcher.py` 在根治前几何上：H2 引脚柱盒-壳底壁**实交叠**
（`legacy_H2_column_touches_shell=true`，y 重叠 0.635mm、壳底壁 z∈[0.508,0.855]
全落柱盒 z 域）→ 信号链对接地壳短路；H1 地侧针与壳/墙/底板**零接触**
（三项 false）→ 串馈口基准端悬空（其唯一"接地"路径经端口电阻穿过 H2 短路）；
H4 port1 y∈[−59.5,−59.4]mm ⊂ PML_8；H5 顶净距 0.251mm。旧测试漏洞：短路循环
不含 shell、净空判据只算 x 半对角忽略 z 延伸；另发现壳底切线与微带起点在
(0, Y_S, H_SUB) 恰触（第四条短路路径）。根治后接触图：信号链/地链各一分量、
互不接触、桥同时触针顶与壳内壁顶、port1 出 PML_8 1.75mm、顶净距 5.0mm
。

### 14.5 验收门与真机结果（scripts/smoke_wp25_tier2.py `--only pt3_sma_launcher_v2 --no-cache --flo 1.5 --fhi 3.5`）
门：带内 2.25–2.75GHz max|S11| ≤ −10dB（文献保守地板）、|S11| ≤ 0dB 无源性、
带内 min|S21| ≥ −3dB 物理量级（理想级联 ≈−0.5dB；地板抓结构死亡，非精度门）、
port2 β→HJ εeff |Δ| ≤ 2%（msl_cpw ±1% 先例）。扫频 1.5–3.5GHz（高斯脉冲比
2.25–2.75 档短 4×，判据仍取带内 2.25–2.75），0.4mm 收敛档，绕开缓存。
- **v2（最终几何，PASS）** pt3_sma_launcher_v2 存档 summary：solve 2215s；|S11|@2.5G **−11.75dB**、带内
  max|S11| **−10.71dB**（门 −10）、|S21|@2.5G −0.42dB、带内 min|S21| −0.50dB、
  port2 εeff 引擎 2.8806 vs HJ 2.8527（**+0.98%**）、|S11|²+|S21|²=0.974（无耗
  一致，余为基板 tanδ）。Z_in@2.5G ≈ 48.6+j26Ω。
- **v1（无前脸，FAIL 留档）** pt3_sma_launcher_v1（原 pt3_sma_launcher 目录同源）：
  solve 2270s；|S11|@2.5G −4.00dB、带内 max −3.31dB、|S21| −2.30dB、β +0.97%、
  无源性 OK——结构已物理（对比 pt2 +5.42dB/−375dB 且 pt2 探针电压 1.5e14 数值
  发散），失配来自结点（S11 相位斜率往返 74ps ≈ 5–7mm = 同轴段长）。
- 回损 −11.75dB 过保守地板但未达文献常规 15–20dB：残余 ≈1.7nH 串联弹射电感
  （针搭焊段/焊锡台阶），厂商笔记的"launch 处线宽渐变补偿寄生"为 followUp
  （pin_lay/焊锡宽度或渐变段参数扫描，走 recipe 优化）；HFSS 仲裁可选。

## §11.2 追加：SSL 闭式重定标（2026-09-19）

- **softmin 修正族替换 q 式**：εeff=1+(Δ^−p+D^−p)^(−1/p)，Δ=(εr−1)·q̃，q̃=q·G(u,s)，D=D0(1+u)^d1·(4s(1−s))^d2，p=p0+p1·s（常数 SSL_Q_G1/SSL_Q_G2/SSL_D/SSL_P 共 13 个，core 内单源）。依据：FD 裁判 288 点（6u×6s×8εr）实证 q_fd 随 εr 单调降（softmin 串联饱和物理；2.2↔12.9 差 2.5×），q 式单 εr 定标在 εr=12.9 外推 +82% 不可行。精度：fit max 3.84%/rms 0.95%；独立验证族 75 点 max 1.94%/rms 0.74%；(u,s,εr) 单调 2001 点网格零违例；h→0/h→b 端点精确。复现：`scripts/fd_laplace_tline_referee.py --ssl-family/--refit-ssl-q`（逐位复现）。
- **新 50Ω 设计点 w=0.9058**（闭式 εeff 2.0011/Z0 50.0；FD 真值 2.0250/49.67Ω=+0.67%）；旧 w=0.731 口径（q 式 +26%、FD 2.092/56.1）撤为历史锚。TEMPLATE_NOMINAL/meta.yaml/fake 缺省/render 默认已全链级联；历史 pt 复放用 --w-mm 0.731。
- **CPS γ 定标域边界更新（R2-B-08③ 跟进，240 点角落扫描）**：单参数 γ(εr) 修正在角落不可修（增强比=(a/h,b/h) 二维曲面+εr 混叠；固定 a/h 随 b/h 非单调）——定标域写死 a/h≲1 且 b/h≲3；域外低估实测 (a/h=2,b/h=6,εr=10.2)→**−2.8%**、(a/h=3,b/h=6,εr=12.9)→**−5.7%**（比本文件旧注记 −2~−4% 更重，以本块为准）；复现 `--cps-corner`。
- **CPS 端口元落盘新契约**：render cps beta 块增 port_y1_m/port_y2_m/plane_dist_m（E 场节点=cell 中心，终网格实测；前两列 freq_hz/beta_rad_per_m 契约不变），判读器 G2 优先实测线长（地板 ±5.7%→~±1% 待真机仲裁）。

### 15. c3 耦合/馈耦合标定锚

- **k 模分裂精确式**：k=(f₂²−f₁²)/(f₂²+f₁²)（M. Makimoto, S. Yamashita,
  Microwave Resonators and Filters for Wireless Communication（MYJ）耦合谐振
  章口径；同 J.-S. Hong & M. J. Lancaster, Microstrip Filters for RF/Microwave
  Applications, Wiley 2001, §5 耦合谐振器测量节）——对 f₁,₂=f₀/√(1∓k) 恒等，
  窄带近似 k≈2|f₂−f₁|/(f₂+f₁) 只作旁证列。
- **权威源头**：M. Dishal, "Design of dissipative band-pass filters
  producing desired exact amplitude-frequency characteristics", Proc. IRE,
  vol.37, no.9, pp.968-983, Sept. 1949（谐振器耦合网络测量口径）；
  群时延法外部 Q：Hong & Lancaster 同书外部 Q 测量节（τmax 法）。
- **C 常数裁决（本仓合成回收钉死，runs/df6_a1_r4/selftest_result.json；
  独立互证一致）**：反射单载口径 S11 τmax=4·Qe/ω0 ⇒ Qe=ω0·τmax/**4**
  （C=4；实测钉 3.9972）；"/2"口径被否决。对称双馈 S21 口径
  τmax=2·Q_L/ω0（对称时 =Qe/ω0，C=1）。群时延四参数 Lorentzian+基线拟合
  τ(f)=A/(1+((f−f0)/w)²)+D——带缘斜率法测线时延被谐振器电抗斜率污染
  （实测 3.2×），禁用。
- **k–gap 全波标定曲线**：行业标准实践=用 fixture 的 k(g) 曲线整体替代
  KJ 闭式缝映射；曲线门=严格单调（hairpin 先例）。
