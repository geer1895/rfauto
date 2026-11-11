# 射频模板建模·官方例对照表（开发前必读）

> 2026-09-02 多模态审计批次沉淀。给 openEMS 模板/新结构建模时的**权威对照来源**
> 与已验证口径。修改模板前先对照本表，避免重复踩坑（详证见 DEVLOG 多模态审计节）。
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

### 0.1 HFSS 建模铁律两要点（2026-11-06 晶圆键合实测反馈转正，AGENTS 同笔；openEMS 对应端口铁律见 §3）

- **vacuum 体包裹约定**：`material="vacuum"`（SolveInside=true/
  Transparency=1）普通 Box **完全包住**实体叠层（整包、不布尔差直接重叠）
  合法可解——参考工程惯例：SICL 空气腔=真空 Box 整包三层叠层；但真空盒与
  实心体**部分相交**（实体穿出真空盒边界）validate 即报
  `Parts Vacuum and W2_Membrane intersect.`，求解失败。判定=**完全包含
  放行/部分相交 ERROR，两情形结论相反不可互推**——建模期几何门
  geometry_lint 检查④ partial_intersection 同口径（两两 AABB 相交且非
  包含才报，完全包含豁免；src/rfauto/service/geometry_lint_service.py）。
- **波端口三静默失败形态——solve 正常跑完结果是垃圾**（判据不能依赖引擎
  报错）：①端口面与实体端面**共面**（一侧无 solve-inside 体——真空是
  背景未被显式建体）→ `Port refinement error: Port P1 does not have a
  solved inside material on either side`；②端口面**跨多个不连通空气区**
  → 解正常但 |S11|≈0dB、|S21|≈−90dB 全反射（模式求解器把每个区当独立
  波导，mode 1 非传输线模）；③端口面**周长被薄膜金属/介质切分** → 解
  正常但 |S11|²+|S21|²>1（非无源）或假谐振（端口截面材料分布与线上不一致、
  模式失配）。三形态 solve 阶段均零报错——**须建模期几何断言**（端口落
  外边界/邻接 solve-inside 体/截面连通，即 geometry_lint 检查①②③）；
  HFSS 端口异常先查官方文档（#191），激励体积为零的 openEMS 同族坑见
  §2/#174。

## 1. Wilkinson 功分器（Ansys 官方 FDTD 例，Pozar 例 7.2）

来源：Ansys Optics「Wilkinson power divider」（FDTD/RF，含 .fsp/.lsf 工程文件）。

| 项目 | 官方口径 |
|---|---|
| 拓扑 | 输入 Z0 → 双 √2·Z0 λ/4 **环形臂** → 双 Z0 输出（Port1 左入，Port2/3 右侧上下出） |
| 阻抗/线宽 | h=1.59mm εr=2.2 上：50Ω=4.90mm、70.7Ω=2.804mm（由微带综合公式算，**不拍脑袋**。勘误 2026-10-04 review_ge8e R7-5/F1：原载"50Ω=3.195mm"系 Pozar 式号 3.195 误作线宽的转写残留——本仓双源复算 HJ `inverse_width(50Ω)`=4.907mm、skrf MLine 交叉一致，3.195mm 回代 z0=65.6Ω≠50Ω；70.7Ω=2.804mm 复算 70.7Ω 吻合保留。官方正文口径见 §5 "50Ω=4.9mm"） |
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
  谐振激励不起来）。证据：runs/audit_freq_scale/smoke_patch_auto/、
  patch_fix_threeview.png。
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
用户在 ZCode 配置的 MCP 工具后解决。逐个实测结果：

| MCP 工具 | 实测结果 | 本项目用途 |
|---|---|---|
| `web_reader` (webReader) | ✅ 完整读取 Ansys 官方例全文 | **受反爬/需代理的官方文档首选**；还纠正了截图看不清的口径（官方 50Ω=4.9mm） |
| `web-search-prime` (web_search_prime) | ✅ 返回结构化文献列表（标题/链接/摘要，Wilkinson 案例命中 COMSOL/SIMWORKS/CST 教程） | 建模借鉴搜索（官方例/商业软件案例/论文） |
| `zai-mcp-server` (analyze_image / ui_diff_check / analyze_data_visualization / extract_text_from_screenshot / understand_technical_diagram) | ✅ 多模态读图 | **多模态审计核心**：三视图 PNG 复核、UI 与参考截图 diff、S 曲线图分析、截图提取文字/报错诊断 |
| `zread` (get_repo_structure / read_file / search_doc) | ⚠️ 热门仓库可用（langchain ✅）；小众 RF 仓库未索引（microwave-structures、pyems 均报 repo not found） | 读大型开源库结构/文档；小众仓库 fallback 用 `git clone` 到 E 盘工作区 |
| `node_repl`（Browser Use） | 未实测 | 需登录/交互的官方资料页面（.fsp 工程下载等） |
| `computer-use` | 未实测 | 桌面级 GUI 审计（如打开 HFSS/CST 对照建模） |

**选型流程**：受反爬的官方文档 → `web_reader`；找借鉴案例 →
`web-search-prime` + 用户截图互证；图像复核 → `zai-mcp-server` 系列读图；
参考仓库 → 先 `zread`，未索引则 clone 到工作区再本地读。

## 6. 校准前验模型（AGENTS 硬限 1b）的审计工具链

1. 文本：逐行读 render_script 生成的 simulation.py；
2. 视觉：`scripts/gen_three_view_audit.py` 出三视图 PNG（归档 docs/audit/）；
3. 文献：本表 + 官方教程；
4. 数值：谐振点对照闭式解；端口健康检查（|S11|>1 即端口/网格错误）；
5. 标定：以上全过后才允许 `scripts/derive_fake_calibration.py` 生成校准锚。

## 7. CPW 端口口径（WP2.1 续，2026-09-08 侦察定稿）

- 本机 openEMS 绑定有一等 CPW 端口：`CPWPort/AddCPWPort(
  port_nr, metal_prop, start, stop, prop_dir, exc_dir, gap_width,
  excite=0, FeedShift/MeasPlaneShift/Feed_R)`（逐条对照源码）。
- 口径：start/stop 宽度范围=**中心带宽度**（端口只画中心导体段）；
  gap_width=每侧缝宽；两侧地金属**自画**（端口不补）；
  FeedShift/MeasPlaneShift 语义同 MSLPort。
- **exc_dir 语义（2026-10-02 上游破坏性重定义，EC-12 适配批核实）**：
  新绑定 `exc_dir`=**缝间 E 场方向=宽度方向**（`width_ny=CheckNyDir(
  exc_dir)`），高度法向自动推算 `height_ny=3−prop_ny−width_ny`，并新增
  校验 `start[height_ny]==stop[height_ny]`（ports.py CPWPort 构造器）。
  共面端口（y 传播/z 法向）须传 `exc_dir='x'`；旧口径 exc_dir='z'
  （面法向）会被当作宽度轴撞上中心带宽度差抛错。金属厚度盒不可再传入
  start/stop（高度向须平面化）。
- 合成/分析：skrf media.CPW(w, s, h, ep_r)（反解 w 用 bisection，同
  mline 手法）；fake 闭式同 mline（β=2πf√εeff/c）。

## 8. dipole 官方口径（WP1.3 修复依据，2026-09-08 侦察定稿）

来源：openEMS 官方 Helical Antenna 教程（Python，wire primitive +
LumpedPort 馈电全套）与 Dipole SAR 教程（wiki.openems.de
"Tutorial: Dipole SAR"）。

- 振子 = **wire primitive**（AddCurve/AddCylinder，radius 参数）或薄
  带 box；中央 gap 处 **FDTD.AddLumpedPort(port_nr, R, start, stop,
  'x', 1.0, priority=5)** 直馈（跨 gap，norm 方向沿振子轴）。
- **自由空间器件：无基板、无地**，域全 MUR（官方 Helical 用
  ['MUR'×5, 'PML_8']）+ nf2ff box（WP4.1 远场接口）。
- 馈电阻：半波偶极子谐振阻抗 ~73Ω（官方 Helical 示例 R_in=120Ω 是
  螺旋特定值）——模板口径 R=z0_ohm(50)，S11 判读窗放宽（-10~-15dB）。
- 我方 _dipole_lines 现状缺陷（⑭ 确认）：振子贴基板顶面 + MSL 微带
  馈线侧面接入 = "微带馈偶极子"混合怪 + MSLPort 悬空；render_script
  底边界恒 PEC（dipole 镜像破坏输入阻抗）。修复=重写 _dipole_lines
  （LumpedPort 中央直馈）+ render_script 底边界 per-template 特判
  （dipole→MUR 且域 z 向下延 λ0/4）+ fake 派发分支 + meta 同步。

## 9. rat-race 180° 混合环（WP2.3，#208 理论核验轮定版，2026-09-09）

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

### 9.1 k 定版结论（ratrace-k-finalize，2026-09-16；权威数据 runs/ratrace_arbitration/）

- **k=1.0975 归属 MESH_ARTIFACT（HFSS 仲裁背书）**：HFSS 物理 R=17.344mm
  （无 k）balance 中心 2.465GHz / S11 谷 2.41GHz（ratrace_arbitration.json
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
- **真机回验（Σ 单激励进程隔离 #208，runs/ratrace_arbitration/k_finalize/）**：
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
- **权威数据**：ratrace_arbitration.json（含追加 k_finalize 段）；
  hfss_arbitration.json 的 error/verdict 键为 run2 陈旧残留（已改名
  stale_error_run2 / stale_verdict_run2，与 ok=True/attempt=1 并存属数据卫生）。

## 10. Gysel 功分器（WP2.3，#211 理论核验轮定版，2026-09-09）

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

### 10.1 P2⑪ 拓扑重设计：L-jog 等长变体（2026-09-16 离线审计定版）

- **问题**：矩形六节环只有 2 个自由边长——顶边桥带继承臂 λ/4 跨度
  2·arm_len=36.324mm，对 50Ω λ/2 设计值 2·iso_len=35.500mm 有 **+2.32%**
  二阶偏差（桥带 184.176°@2.5GHz）。#211 pt2 矩形真跑 S32=-32.6dB/
  S11=-26.7dB PASS（二阶效应），但 P2 残余未量化归因。
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

## 11. CPS 共面带 / 悬置带线（C9 传输线族 II，2026-09-15 侦察定稿；2026-09-18 w2f-c9-refs 口径改写）

闭式内核：`core/calculators.py` `_cps_ri` / `_suspended_stripline_ri`
（注册键 cps_analysis / cps_synthesis / suspended_stripline_analysis /
suspended_stripline_synthesis）。铁律 1c：所有常数出处如下，无拍脑袋值。
**独立数值裁判（#118）统一为 `core/quasistatic_fd.py`**（张量网格变分 FD Laplace，
网格线精确落导体缘/介质面，能量法 C=2W/V²，一阶 Richardson 外推；CLI
`scripts/fd_laplace_tline_referee.py`）——裁判自身先过已知基准才有资格裁判闭式
（AGENTS 1b）：微带 vs Hammerstad–Jensen（skrf，4 几何含 εr=9.8）+0.1~+0.3%、
CPS 半空间极限 (1+εr)/2 −0.1%、零厚度带状线空气 Z0 vs Cohn −0.1%、悬置带线
h→b 全填充 εr 精确（tests/unit/test_quasistatic_fd.py 钉住）。**此前两份未入库
的临时 FD（侦察批 §11.1 旧表/§11.2 的 3.02；收尾批 postmortem 的 1.68/2.36）均
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
  **pt1 基线（runs/cps_smoke/pt1，2026-09-17，缺省网格 BASE 1.14/NEAR 0.285）**：
  |S11|max −23.9 dB 过；εeff 1.8909 vs FD 1.667 **+13.4% FAIL**（旧口径 vs 裸闭式
  +20.35%）。引擎侧候选由复跑（rm-oe-c9）分离：端口元落格线长（±5.7%）、z 域
  ±5mm MUR 非 PML、基板 4 格台阶化；建议差分线长（两 L）或落盘端口元 y 坐标把
  口径地板压到 ~1%。

### 11.2 悬置带线（suspended substrate stripline，基板对称居中）

- 几何口径（**本项定版，与任务书 "[B/2−h, B/2]" 单侧写法的差异**）：腔高 b
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
  1.284），且该临时求解器无任何已知基准对拍；收尾批 postmortem 的 2.36
  （2.412/2.376/2.356 序列）同样未过基准、与验证序列 2.084/2.088/2.092 不符，
  一并撤。
  **标称几何真值（w=0.731 b=1.016 h=0.508 εr=3.66）**：d0=b/40、b/80 →
  2.0836/2.0877，**εeff_FD=2.092**；Z0_air 81.19（Cohn 81.26，−0.08%）→
  **Z0=56.1Ω**（**2026-09-19 SSL 闭式已重定标 softmin 修正族、新 50Ω 点 w=0.9058——见文末「SSL 重定标追加」块，本段 2.092/56.1 保留为 w=0.731 历史锚**）——q 式 2.641/50.0Ω **高 +26%**：按 q 式综合的"50Ω 标称线"真值
  ≈56Ω。标称几何保持不动（真机配对 #158、docs meta 同源）；**SSL 闭式重定标=
  followUp**（裁判定点迭代：真 50Ω 需 w≈0.897mm，εeff≈2.028；重定标后
  TEMPLATE_NOMINAL/meta/fake 锚同步）。
- **StripLinePort β 口径审（followUps ⑦，离线定案）**：
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
  复跑（rm-oe-c9）：z 网格基板 ≥8 格、NEAR ≤w/6，预期 G2/G3 同向收敛到 FD；
  闭式 q 式对照只作信息项。
- **端口口径（openEMS）**：StripLinePort×2（v0.37 源码 L914+，`height`=带到
  每面地的对称距离=b/2，本 session inspect 实证），同 stripline 模板已真跑
  PASS 的口径；β 金标准可用（port_beta.csv）。top_bc/bottom_bc 均 PEC，
  z 域 [0,b]，基板两面/中面/壳边全部精确入网（#198）。
- 标称：b=1.016（=2·H_SUB，与 stripline 同 z 域、网格友好）、H_SUB=0.508
  对称居中、q 式 50Ω → **w=0.731mm，q 式 εeff=2.641（裁判真值 2.092/56.1Ω，
  见上）**。扰动域：审计 ×1.37 扰动 b→1.392 仍 >H_SUB ✔（对称填充守卫为
  H_SUB<b，非单侧的 h<b/2；任务书 "b≥2.8h" 系单侧口径，本项不适用）。
- **aurora_q 三席整合（2026-11-07）**：FD 收敛真值锚（w=0.52/b=0.5/h=0.05/
  εr=11.9 → εeff 1.58537/Z0 50.482Ω）、MeasPlaneShift 近场修复实证（G1
  FAIL→PASS）、G5 over_unity=306 归因修正（50Ω 参考失配提取偏置，非带缘
  盲区）、跨引擎四方对照——见文末「§11.2 追加 2」块。

## 12. C2 阵列族：1×4 corporate / 2×2 H-tree / 1×3 串馈贴片阵（2026-09-15 理论核验定稿）

方案行：continuation_plan_20260907.md §10.3 器件族表 "C2 阵列族"。本节为
openems_templates.py C2 段的权威口径出处（antenna2 §同款制度）。

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
    **实现总扣口径注记（R1-2 审查批 2026-10-04）**：仓内实现总扣=4ΔL
    （三副本一致，与本行字面 −2ΔL 的矛盾即 0.824 终裁本体；历史仲裁
    INCONCLUSIVE 在档 runs/xa1_arbitration/，语义终裁挂 L5 v2 批，见
    runs/xa1_arbitration/l5_sweep/criteria.md §一——出处标签如实，数值零改动）。
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
- **真机冒烟判据（followUp，scripts/smoke_array_anchor.py 已备离线判据函数）**：
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
  NrTS=100000 可能不足 30ns（coupled_bpf 冒烟 NrTS 截断同类，DEVLOG（一百一十）），
  冒烟前先估 Δt。

## 14. SMA 边缘弹射 sma_launcher（WP2.5 Tier 2，2026-09-16 真机 FAIL 根治定版）

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
  ≥17.7–20.8dB）；方案行（docs/continuation_plan_20260907.md §4 WP2.5）"验收靠
  文献曲线"：**带内回损常规 15–20dB，保守地板 −10dB**（objectives 口径）。
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

### 14.4 真机 FAIL 根因实证（精确接触图，禁 bbox；legacy 留档
runs/wp25_tier2_smoke/pt3_sma_launcher_diag/legacy_contacts.json）
pt2 签名：|S11|=+5.42dB（非物理）、|S21|≈−375dB（零传输）、port2 表观 εeff≈2866。
`scripts/diag_sma_launcher.py` 在根治前几何上：H2 引脚柱盒-壳底壁**实交叠**
（`legacy_H2_column_touches_shell=true`，y 重叠 0.635mm、壳底壁 z∈[0.508,0.855]
全落柱盒 z 域）→ 信号链对接地壳短路；H1 地侧针与壳/墙/底板**零接触**
（三项 false）→ 串馈口基准端悬空（其唯一"接地"路径经端口电阻穿过 H2 短路）；
H4 port1 y∈[−59.5,−59.4]mm ⊂ PML_8；H5 顶净距 0.251mm。旧测试漏洞：短路循环
不含 shell、净空判据只算 x 半对角忽略 z 延伸；另发现壳底切线与微带起点在
(0, Y_S, H_SUB) 恰触（第四条短路路径）。根治后接触图：信号链/地链各一分量、
互不接触、桥同时触针顶与壳内壁顶、port1 出 PML_8 1.75mm、顶净距 5.0mm
（fixed_contacts.json）。

### 14.5 验收门与真机结果（scripts/smoke_wp25_tier2.py `--only pt3_sma_launcher_v2 --no-cache --flo 1.5 --fhi 3.5`）
门：带内 2.25–2.75GHz max|S11| ≤ −10dB（文献保守地板）、|S11| ≤ 0dB 无源性、
带内 min|S21| ≥ −3dB 物理量级（理想级联 ≈−0.5dB；地板抓结构死亡，非精度门）、
port2 β→HJ εeff |Δ| ≤ 2%（msl_cpw ±1% 先例）。扫频 1.5–3.5GHz（高斯脉冲比
2.25–2.75 档短 4×，判据仍取带内 2.25–2.75），0.4mm 收敛档，绕开缓存。
- **v2（最终几何，PASS）** runs/wp25_tier2_smoke/pt3_sma_launcher_v2 +
  summary_pt3_sma_launcher_v2.json：solve 2215s；|S11|@2.5G **−11.75dB**、带内
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

## §11.2 追加：SSL 闭式重定标（2026-09-19，wf:fix-w2f-rescale-batch；上轮 F-R2-4 跟进）

- **softmin 修正族替换 q 式**：εeff=1+(Δ^−p+D^−p)^(−1/p)，Δ=(εr−1)·q̃，q̃=q·G(u,s)，D=D0(1+u)^d1·(4s(1−s))^d2，p=p0+p1·s（常数 SSL_Q_G1/SSL_Q_G2/SSL_D/SSL_P 共 13 个，core 内单源）。依据：FD 裁判 288 点（6u×6s×8εr）实证 q_fd 随 εr 单调降（softmin 串联饱和物理；2.2↔12.9 差 2.5×），q 式单 εr 定标在 εr=12.9 外推 +82% 不可行。精度：fit max 3.84%/rms 0.95%；独立验证族 75 点 max 1.94%/rms 0.74%；(u,s,εr) 单调 2001 点网格零违例；h→0/h→b 端点精确。复现：`scripts/fd_laplace_tline_referee.py --ssl-family/--refit-ssl-q`（逐位复现 runs/w2f_rescale_batch/refit_ssl_q_repro.json）。
- **新 50Ω 设计点 w=0.9058**（闭式 εeff 2.0011/Z0 50.0；FD 真值 2.0250/49.67Ω=+0.67%）；旧 w=0.731 口径（q 式 +26%、FD 2.092/56.1）撤为历史锚。TEMPLATE_NOMINAL/meta.yaml/fake 缺省/render 默认已全链级联；历史 pt 复放用 --w-mm 0.731。
- **CPS γ 定标域边界更新（R2-B-08③ 跟进，240 点角落扫描）**：单参数 γ(εr) 修正在角落不可修（增强比=(a/h,b/h) 二维曲面+εr 混叠；固定 a/h 随 b/h 非单调）——定标域写死 a/h≲1 且 b/h≲3；域外低估实测 (a/h=2,b/h=6,εr=10.2)→**−2.8%**、(a/h=3,b/h=6,εr=12.9)→**−5.7%**（比本文件旧注记 −2~−4% 更重，以本块为准）；复现 `--cps-corner`。

## §11.2 追加 2：SSL FD 收敛真值锚+近场修复实证+G5 归因修正+跨引擎四方对照（aurora_q，2026-11-07，Q-X20/Q-X19/Q-X25 三席整合）

### FD 收敛基准（悬置带线真值锚注册：w=0.52/b=0.5/h=0.05/εr=11.9）

- **锚点与真值**：u=w/b=1.04、s=h/b=0.1、εr=11.9 → **εeff=1.58537、
  Z0=50.482Ω**（`core/suspended_stripline_fd_judge` 六级阶梯
  d0=12.5µm→0.39µm+三点 Richardson 外推，status=CONVERGED；
  runs/aurora_q/qx20_fd_judge/judge_result.json）。该点 u=1.04 在 softmin
  修正族拟合域外，FD 锚覆盖外推区真值。
- **收敛资格三证**（裁判自身先过基准才有资格裁判，AGENTS 1b/#118）：
  1. **Richardson <0.1%**：末级残差 εeff 9.9e-5（0.01%）、C_air 3.8e-4；
     三点一致残差 1.2e-6/3.0e-6；观察阶 p_eps=1.10/p_cair=1.02 在窗、
     末三级单调——8 项 gates 全 true。
  2. **Cohn 资格锚**：空气线 Z0_air FD 63.565 vs Cohn 63.631（−0.105%，
     收敛后 within_tolerance）；精确极限全填充 εeff=11.9 误差 0、空气
     恒等 εeff=1.0 误差 0、薄板极限 1.1047 单调有序。
  3. **独立裁判族交叉**：第二实现 1.58517/50.4828，对自身 rel −0.0127%。
- **w2f 角落复核**（runs/w2f_rescale_batch/ssl_er_scan.json 只读 8 角）：
  闭式偏 FD +0.41%~+1.26% 全正——本点 +1.14% 与角落带一致（闭式系统性
  正偏方向，softmin 族精度口径吻合）。
- **FD 口径边界（如实）**：静流第三方裁判（零仿真），不覆盖 FDTD 动态/
  Yee 差异/探针链系统差——openEMS 对 FD 残余差中静态网格可仿真份额之外的
  未归因余项见四方对照。
- **锚注册声明（aurora_q Q-X45，2026-11-07）**：上述 G3 真值已注册
  anchors.yaml fdref-v1——`suspended_stripline.g3_eps_eff.fdref-v1`
  （value=1.58537）与 `suspended_stripline.g3_z0_ohm.fdref-v1`
  （value=50.482），锚值=judge_result.json 逐位舍入；id 三段式
  <族>.<量>.<源>-vN（量段携 G3 消歧，quantity.name=
  suspended_stripline_g3_*）；layer=closure/status=experimental/
  consumers=[]；uncertainty 紧档 0.1%（实测残差 9.9e-5 好于 fdref 先例族
  地板 0.5% 百倍，Q-X29 预备方案裁决采纳）；EXPECTED_ANCHORS 单源同笔
  87→89（core/anchors.py+计数链+gallery 再生）。
- **六级收敛阶梯详表（Q-X56 追加，2026-11-07；数值源 judge_result.json
  `fd` 块逐位转写）**：d0 自 12.5µm 逐级对半细化 6 级至 0.39µm：

  | 级 | d0 (µm) | εeff（网格原值） | C_air（×ε0） | 空气线 Z0 对 Cohn 锚逐级偏差 |
  |---|---|---|---|---|
  | 1 | 12.5 | 1.578489 | 6.000294 | −1.329% |
  | 2 | 6.25 | 1.582172 | 5.963716 | −0.724% |
  | 3 | 3.125 | 1.583825 | 5.945440 | −0.419% |
  | 4 | 1.5625 | 1.584650 | 5.936068 | −0.262% |
  | 5 | 0.78125 | 1.585034 | 5.931423 | —（锚逐级列仅记 4 级） |
  | 6 | 0.390625 | 1.585214 | 5.929124 | —（收敛后总判 −0.105%） |

  读法三件：①**Richardson 三点外推**——终值 εeff=1.58537（把六级末值
  1.585214 再推 1.6e-4）、观察收敛阶 p_eps=1.097/p_cair=1.015（一阶窗
  内）、末级残差 εeff 9.9e-5/C_air 3.8e-4、三点一致残差 1.2e-6/3.0e-6、
  末三级单调——8 项 gates 全 true（裁判自证收敛才有资格仲裁闭式/引擎，
  #118）。②**Cohn 资格锚随级收紧**——空气线 Z0_air 对 Cohn 偏差随 d0
  减半单调收敛（−1.33%→−0.11%），FD 资格与物理锚同向互证（精确极限三件
  恒真：全填充 εeff=11.9 误差 0、空气恒等 εeff=1.0 误差 0、薄板极限
  1.1047 单调有序）。③**独立裁判族交叉**——第二实现 1.58517/50.4828Ω
  （对自身 rel −0.0127%，观察阶 1.156 同窗）。
- **E1/E2/E3 静态网格仿真复现阶梯（Q-X56 追加；judge_result.json
  `emulation` 块）**——openEMS 干净口对 FD 残余 −2.49% 的网格因子分解：

  | 档 | x 轴网格 | z 轴网格 | 节点数 | FD εeff | 残差分解 |
  |---|---|---|---|---|---|
  | E1 | 跑档 | 跑档 | 486 | 1.55787 | 静态网格总仿真 −1.73%（占残余 70%） |
  | E2 | 精化 | 跑档 | 846 | 1.56219 | x 精化后余 −1.46% = z 轴份额 |
  | E3 | 跑档 | 精化 | 34614 | 1.57847 | z 精化后余 −0.44% = x 轴份额 |

  z 向精化（节点 ×71）回收 1.30pp、x 向精化（节点 ×1.7）只回收
  0.27pp——**z 轴离散（空气隙仅 2 格，run_mesh_profile 实测）是 openEMS
  εeff 偏低的主导轴**；z 空气隙假说 share=58.8%→**PARTIAL**（预声明阈值
  share≥0.60 CONFIRMED/≥0.25 PARTIAL/其余 REFUTED，冻结不改）；静态仿真
  外余项 −0.75% 如实悬置（FDTD 动态/Yee/探针链系统差不入 FD 静流裁判
  口径）。

### 近场污染修复实证（G1 FAIL→PASS：MeasPlaneShift 0.983→2.0mm）

- **根因链**（Q-X13 定位/Q-X19 实施）：模板惯例
  MeasPlaneShift=(BOARD−L/2)/3=0.983mm → 测量面距激励面仅
  0.809mm=2.83/kc1（kc1=3490.66 rad/m，衰减长 1/kc1=0.2865mm）→ 最低
  非传播模残余 e^−2.83≈5.9%（实测污染 a=+6.5%/c=+7.2%）→ S21 分母抬高
  → 全带平坦压缩 −0.5dB → G1 FAIL（observed −0.5765 dB vs HFSS −0.07，
  dev −0.5065 dB 超 0.3 门）。
- **修复**（runs/aurora_q/qx19_fix/fix_evidence.json）：shift 0.983→
  2.0mm（网格吸附后 1.98362mm，双变体同修；oe_templates 模板源零改动，
  patch_measplane_shift 锚各恰 1 fail-loud）→ 测量面-激励面间距
  0.809→1.8097mm=6.317 个衰减长 ≥5 守卫，**5/kc1=1.432mm 近场死区移出**；
  残差界请求 0.17%/吸附实测 0.18%——对照修复前污染 5.6~6.5%（理论
  e^−2.83≈5.9%），**压低 ~33×**。测量面间距 plane_dist 9.0164→7.0328mm
  （=2·BOARD−2·shift，与 runner 同式逐位吻合）。
- **实证门态**（C 档重跑，runs/aurora_q/qx9_anchor/verdict.json）：
  G1 observed −0.0021 dB（dev +0.0679 dB ≤0.3）**FAIL→PASS**，|S21|≈1.000；
  G2 PASS 不变（−19.55 dB，dev 3.95≤6）；G4 PASS 不变（open ZL 48.784Ω，
  rel 2.92%，HFSS 隐含带内）；G3 PARTIAL 独立面照旧（open εeff 1.554353
  vs 闭式 3.06%）。audit 守卫 5→7 项全绿（新增 nearfield_sep_ge_5kc1、
  measplane_in_feed）；两变体 EndCriteria −60dB 干净自停（shield 29070
  TS@−83.59dB / open 28560 TS@−82.74dB，NrTS 上限 150000 远未触）——
  #262 截断伪象排除。
- **判读纪律**：近场残余属频率平坦常数偏置（修复前 δ(f)≈−6.3%/−5.7%
  平坦，#255 驻波族同形态）——凡 S 参数提取判读前先核测量面-激励面
  间距 ≥5/kc1，该守卫已入 audit（nearfield_sep_ge_5kc1）。

### G5 归因修正（over_unity=306 = 50Ω 参考失配系统偏置，非带缘盲区）

- **现象**：修复后 over_unity 0→306（shield 98+open 208，**S21 列独占**，
  S11 全带零超一），passivity_max 0.8912→1.0142（≤1.05 门内），G5
  PASS→FAIL、verdict=DISAGREE——**驱动门已换（G1→G5），实为净改善一门、
  新暴露一门**。
- **谱形态**（Q-X25，g5_spectrum_evidence.json 逐点证据）：平滑确定性
  频率爬升漂移+峰钉 10.0GHz 高带缘——带内 400 逐点差分仅 5 次符号翻转
  （白噪声期望 ~200）；Spearman(+0.417/+0.447) p≈1e-18/5e-21；低带缘
  [1.0,2.5)GHz 两变体零超一；幅值 ≤1558 ppm（0.0135 dB），比 G1/G2 的
  dB 门低 1~3 个量级，不撼动任何物理标量门。
- **归因修正**：三重谱证据指向**固定 50Ω 参考下端口波分解的频率爬升型
  提取系统偏置**（#250/#280/#348 家族）；战役账"线端 nm 级入网盲区/
  网格分辨不足"归因不被支持（降级为次要嫌疑）：
  1. 反射通道零信号：shield |S11| 0.0989→0.1053 平滑爬升，量值恰=50Ω
     对 ZL=40.78Ω 的失配伪反射 |Γ|=|40.78−50|/(40.78+50)≈0.103，无窄带
     散射纹波/谐振尖峰；
  2. nm 级入网守卫全绿：strip_edges_exact_nm=True 残差逐位 0.0；线端
     残差 2.56µm≤NEAR 17.4µm——几何均匀线固定电长度偏移频率平坦，
     产生不了随 f 爬升的幅值偏置（audit 实测 min_gap 12.5~17.3µm，
     "40µm 网格"表述与实测不符）；
  3. 偏置幅值随失配缩放：shield（|Γ|≈0.10）δ 峰 +0.154% vs open
     （|Γ|≈0.012）+0.047%——网格分辨类伪象不随端口参考失配缩放。
- **"暴露"机制闭合**：修复前 |S21| 被近场污染压至中位 0.9358/0.9439
  （距 1.0 有 64000/56000 ppm 余量）→ ±1500 ppm 提取漂移不可能穿越 1.0
  → over_unity=0 是**掩蔽态**（G1 FAIL 的另一面）；修复后 |S21|≈1.000，
  ±0.15% 漂移带绕 1.0 往返必然产生超一点——**306 点是修复生效的直接
  副产物**。
- **门设计注记**（供模板族级根治参考，Q-X21 面）：over_unity==0 严格
  零容差与 ~±0.15% 提取偏置底结构不兼容（|S21|≈1.000 的健康无损线在此
  判据下必然超点）；passivity_max≤1.05（现值 1.0142，余量 25%）已覆盖
  同一偏置的能量面——零容差条款与提取精度底的匹配是门修订方向
  （不改门，如实登记）。

### 跨引擎四方对照表（同几何 w=0.52/b=0.5/h=0.05/εr=11.9）

| 口径 | εeff | Z0 (Ω) | vs FD（εeff） | vs FD（Z0） | 出处 |
|---|---|---|---|---|---|
| FD 收敛真值（锚） | 1.58537 | 50.482 | — | — | suspended_stripline_fd_judge 六级+Richardson |
| 闭式（softmin 重定标） | 1.6034 | 50.251 | +1.14% | −0.46% | `_suspended_stripline_ri` 现算 |
| openEMS（干净口谱） | 1.5459 | 50.466 | −2.49% | −0.03% | qx9_anchor ssl_open 真跑（Q-X20 three_way 口径） |
| HFSS implied（外部实测锚） | 1.59 | 50.2 | +0.29% | −0.56% | qx9 spec.md §1 引述 |

- **偏差带读法**：四方 εeff 带宽 [1.5459, 1.6034]（对 FD −2.49%~+1.14%）、
  Z0 带宽 [50.2, 50.482]（对 FD −0.56%~0%）——Z0 四方一致度（≤0.6%）
  显著优于 εeff，50Ω 设计面跨引擎可比；εeff 离散主项=openEMS 静态网格
  离散（仿真复现 −1.73%，其中 z 轴 −1.46%、占比 70%；z 空气隙假说
  PARTIAL，share=59%，预声明阈值 share≥0.60 CONFIRMED/≥0.25 PARTIAL；
  静态仿真外余项 −0.75% 如实悬置）。
- **域外推声明**：本点 u=1.04 在 softmin 拟合域外——闭式 +1.14% 落角落
  扫描带（+0.41%~+1.26%）内、方向全正，外推区偏差由 FD 锚覆盖仲裁；FD
  为准静态口径，不覆盖 FDTD 动态/Yee/探针链系统差。修复后 verdict 口径
  open εeff 1.554353 同带内（−3.06% vs 闭式）。
- **G3 门锚口径**：冻结 G3 门锚=闭式（3.06% PARTIAL 不改，#122 不因结果
  改门）；对 FD 真值 −1.96% 落 PASS 区——闭式正偏 +1.14% 与引擎负偏
  −2.5% 近似对消是"引擎 vs 闭式 3.06%"的构成解释，不构成改门理由。

### 15. c3 耦合/馈耦合标定锚（df6 A1 R4，2026-09-24）

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
  DP-2 轨独立互证一致）**：反射单载口径 S11 τmax=4·Qe/ω0 ⇒ Qe=ω0·τmax/**4**
  （C=4；实测钉 3.9972）；"/2"口径被否决。对称双馈 S21 口径
  τmax=2·Q_L/ω0（对称时 =Qe/ω0，C=1）。群时延四参数 Lorentzian+基线拟合
  τ(f)=A/(1+((f−f0)/w)²)+D——带缘斜率法测线时延被谐振器电抗斜率污染
  （实测 3.2×），禁用。
- **k–gap 全波标定曲线**：行业标准实践=用 fixture 的 k(g) 曲线整体替代
  KJ 闭式缝映射；曲线门=严格单调（hairpin 先例）。

- **CPS 端口元落盘新契约**：render cps beta 块增 port_y1_m/port_y2_m/plane_dist_m（E 场节点=cell 中心，终网格实测；前两列 freq_hz/beta_rad_per_m 契约不变），判读器 G2 优先实测线长（地板 ±5.7%→~±1% 待真机仲裁）。

## 16. 介质测量/材料参数提取（F-A P1，2026-09-28 增补）

- **确定性内核**：`src/rfauto/core/dielectric_extract.py`（四法纯算法零 IO；
  铁律 7 合规；不进 @register_calculator，免 #231 注册表消费者三表连动）；
  合成回收判据预声明见模块 docstring，测试=`tests/unit/test_dielectric_extract.py`。
- **mTRL（多线校准）**：γ 提取直接消费 skrf `NISTMultilineTRL` 校准的副产物
  （line 标准传播常数）——权威实现=NIST Multiline TRL（Agilent/Anritsu 应用
  注记口径，skrf 内建）；单线特征值法（`extract_gamma_single_line`）与 mTRL
  互证（免校准件对称性假设）。
- **NRW / Baker-Jarvis**：透射反射法（NRW）在 n·λg/2 厚度谐振点失稳是教科书
  已知缺陷；`baker_jarvis_iter` 迭代稳定法为修复路径（NIST TN 1341 Baker-Jarvis
  迭代口径；厚度选点避 n·λg/2）。合成回收判据：NRW ≤1e-3 相对。
- **环形谐振器**：`ring_resonator_f0_to_er`（f_n→εr 解析面）+ `ring_resonator`
  模板（全波段闭环）；**Design Dk 锚**（F-A.3 仿真域闭环：mline/ring 提取回收
  +HFSS 仲裁=Design Dk 锚→C10d 78GHz 复判）登记于月计划 §三 OE 队列，未发射。
- **γ→材料链口径**：`gamma_to_er_eff → er_eff_to_er`（HJ 正向模型 brentq 数值
  反演，正向与 `core/synthesis.py` 综合链同一模型口径：skrf MLine
  `model='hammerstadjensen'`/`disp='kirschningjansen'`）；tanδ 从 γ 实部提取：
  α_d = (β/2)·(εr/εeff)·(εeff−1)/(εr−1)·tanδ（skrf `mline.analyse_loss` 经典
  准静态介质损耗式）；带导体实测先减 Wheeler 增量电感 α_c 再走
  `tan_d_from_alpha_d`。
- **时谐约定**：γ = α + jβ，行波因子 e^{−γz}（e^{+jωt}）；无源线 α≥0、β≥0；
  εeff = (Im γ·c/ω)²——与 skrf 同口径，跨模块对拍前先对约定（#250 族教训）。
- **不确定度面**：GUM 一阶线性传播 vs 蒙特卡洛扰动对照（G4：u95 覆盖 ≥95%）；
  加性复高斯噪声→蒙特卡洛回收带放大（合成注入→回收钉，#118 纪律）。
- **真机段（UNVERIFIED）**：P2 SMA mTRL 校准件 KiCad 生成已登记；P3 真机测量
  硬件待定（D 裁决点），本节全部数值口径经合成回收钉，真机回收证据未产生。

## 17. EMC 参考口径（ME-1..3，2026-09-28 增补）

- **ME-1 传导发射**：`core/emi_filter.py`（两口 ABCD 级联口径）。ABCD 约定
  [V1;I1]=[[A,B],[C,D]][V2;I2']（Pozar *Microwave Engineering* 4th ed. §4.4，
  与 skrf `Network.a` 同约定，测试互证）；ABCD→S 伪波口径与 skrf `a2s` 逐位
  同式。LISN 双型内建子网：CISPR 16-1-2 50 µH/50 Ω 主电源 + CISPR 25 5 µH
  汽车；**CISPR-17 三端接（50/50、0.1/100、100/0.1）三口径 IL 并列**（失配
  口径差=频率无关常数 20·log10((ZS+ZL)/(2√(ZS·ZL)))，50/100 对=0.515 dB——
  消费方如需 CISPR-17 电压比口径自行加常数）。`emi_filter` 模板族挂同源内核。
- **限值线来源纪律（ME-1）**：FCC Part 15 传导限值（47 CFR §15.107/15.109）
  eCFR 现行文本**合法内嵌**（美国政府作品公有领域，双源核对）；CISPR 表收费
  ——走 provenance 次级源交叉核对模块（**不抄收费表**，#1c 同源纪律）。
- **ME-2 辐射发射**：`core/emc_radiated.py`（闭式层）。CM 电流 Ott 式
  E=1.257e-6·f·L·I_CM/d（H. W. Ott, *EMC Engineering*, Wiley 2009；单位推导
  表在模块 docstring——**带 10⁻⁶ 的常数输出 V/m，µV/m 口径常数是 1.25750**，
  两者差 10⁶ 勿混）；DM 环路 E=263e-16·f²·A·I/d（含地镜像）；镜像定理
  2·|cos(k·h·sinα)|；偶极上限对照面（偏移随结果并出，不做硬判定）。限值叠加
  `radiated_margin`（FCC Part 15B / CISPR 32 Class B 两表内建）复用 ME-1
  `margin_report`（最小裕量+首违频点）。精算层=openEMS nf2ff 既有链
  （#249 PEC 镜像 Prad 双计修正已内建）。
- **ME-3 ESD/浪涌免疫门**：`core/emc_tvs_gate.py`。IEC 61000-4-2:2008 /
  61000-4-5:2014 正文收费→**次级源双源交叉核对固化**（出处常量
  `IEC61000_4_2_PROVENANCE`/`IEC61000_4_5_PROVENANCE`，值面钉模块常量表）；
  TVS 选型闭式 VC=VBR+IPP·Rdyn、PPPM=VC·IPP。**警示（任务书 ME-3 明文）**：
  PyPI 包 `emc2` 是大气科学同名假朋友——EMC 面勿引用勿进依赖（
  `PYPI_EMC2_FAKE_FRIEND`）。
- **接线现状（如实）**：ME-1..3 均为 core 纯函数层（不进注册表，#231 约定）；
  `rfauto emc gate` CLI/service 接线属后续批，报告链挂接见
  `service/report_domains.py`（aging/PI/OTA/EMC 四节）。

## 18. 波导族参考口径（ME-4..7，2026-09-28 增补）

- **ME-4 WR 标准表**：`core/rw_tables.py`（EIA WR 系 a/b/推荐带/UG 法兰）。
  三源口径：计划点名 Copper Mountain/RF Essentials/A-Info；2026-09-26 实测
  检索 RF Essentials+同业多源（QuinStar/Keysight/Mi-Wave 等）命中，
  Copper Mountain/A-Info 未直接命中——来源等级**逐行标注**（`3src`=教科书
  EIA 表+检索多源一致+恒等式自洽 12 行；`2src`=教科书+恒等式自洽 5 行），
  单源行不收。主自洽判据：fc10 = c/(2a) 恒等式全表 rtol 1e-9；教科书推荐带
  本身重叠（9.5 GHz 同落 WR-112/WR-90）→ 多命中**显式并列**返回，不静默取一。
- **ME-5 MMT 不连续性**：`core/rwg_mmt.py`（TE_m0 模基 GSM）。权威源头
  N. Marcuvitz *Waveguide Handbook*（公开 PDF；销钉/谐振窗闭式逐式核对 #1c）；
  阶梯耦合积分闭式=Wexler 1967 / Masterman-Clarricoats 1971 矩形特例口径。
  **规格印式两处勘误（#1b 动工前裁决，以模块 docstring 为准）**：结面 GSM
  投影域=E 连续投影主侧全域/H 连续投影口径窗（规格印式恰为转置，校准实证
  不收敛）；cos-分子显式式系笔误（半角稳定形式数学等价替代）。
  HFSS 仲裁锚 1-2 点=月计划 W3 窗（**UNVERIFIED，未发射**）。
- **ME-6 波导-同轴过渡**：`coax_waveguide_transition` 模板（WR-90 起手）。
  官方口径=openEMS 官方 wiki *Coax-to-Waveguide Adapter* 教程（结构直抄：
  背短路板 λg/4）+ 官方 Python *Horn Antenna with Coaxial Pin Feed* 教程
  （探针参数直抄：wg_t=2.0、pin_len=0.55·b、pin_r=0.5、port_h=1.0）；
  名义几何全 `wr_lookup`+闭式导入期精算（#1c 零手抄毫米数）。**端口决定**：
  CoaxialPort 绑定存在但不用（仓内 sma_launcher pt2 真机判废先例 β=4166 vs
  TEM 闭式 68 + 官方讨论 #437 尺寸上限病态），采纳探针柱+LumpedPort 集总桥；
  跨口传输含 sqrt(ZL1/ZL2) 一阶阻抗校正（wiki 教程口径）。真机冒烟与 HFSS
  仲裁=Ph3 窗（**UNVERIFIED**；离线审计已过，`test_coax_wg_template`）。
- **ME-7 角锥喇叭**：`pyramid_horn` 模板 + `core/horn_synthesis.py`。
  主源 S.G. Orfanidis *Electromagnetic Waves & Antennas* Ch.21（增益式 21.4.2/
  口径效率 21.4.3/最优 σ 21.4.4-5/设计方程 21.5.1，式号逐条在 docstring）；
  对照源 Balanis *Antenna Theory* Ch.13（δ_H=3λ/8、δ_E=λ/4→(σa,σb)=(√1.5,1)，
  e≈0.51 缺省综合档）；**独立锚例**=Orfanidis Ex.21.5.1/21.5.2
  （`test_pyramid_horn_template` 逐位钉）。近似级别如实：一阶 Fresnel 口径场
  模型，不含壁损耗/口面反射/边缘绕射/高阶模；全波验证=openEMS（Ph3 窗，
  **UNVERIFIED**）。**波纹喇叭降级**（月计划原文）：综合公式+openEMS 验证，
  自研圆波导 MM 延期不排。
- **WR 表消费纪律**：波导族模板名义尺寸一律 `wr_lookup` 表口径导入期精算
  （coax_waveguide_transition/pyramid_horn 先例），禁止沿用其他文档毫米数
  （#1c/#252 同源）；跨模块 C0 同值由单测钉住。

## 19. GaAs IPD 集总无源件三模板：octagonal_spiral / mim_cap / interdigital_cap（K11/K12，2026-10-24 增补）

三模板同为 GaAs 薄膜 IPD 工艺集总器件，μm 参数口径（W/S/N/Din 等，经
core.stackup.to_mm(v,'um') 单源换算），基板 GaAs 半绝缘典型档
（er=12.9/tanδ=0.0006/h=100μm），全域 MUR（电小器件近场主导）。**网格禁
λ_sub/50 口径**（2GHz λ_sub/50≈6mm 装不下 0.2mm 器件），自动档=最细几何
特征/4；渲染期共同守卫：特征缘/切角/焊盘/端口盒边精确入网（#198）、
NEAR≤min(缝)/3（#266）、全轴近重合去重（#152）、端口盒激励向 ≥2 格
（#283）、离线几何审计（#212）。名义几何全部闭式精算
（docs/templates/<模板>/meta.yaml nominal_derivation 同源）；真机冒烟
均未发射（离线审计过，发射留真机批，HFSS=对齐基准）。

### 19.1 octagonal_spiral 八角螺旋电感

- 闭式：Mohan–Schneider–Chibante, "Simple Accurate Expressions for Planar
  Spiral Inductances", IEEE JSSC 34(10):1419-1424, Oct. 1999，三表达式
  系数逐形状原文锚——Table I 修正 Wheeler（八角 K1,K2=(2.25,3.55)）、
  **Table II 电流片式（八角 (c1,c2,c3,c4)=(1.07,2.29,0,0.19)）**：
  L=(c1·μ0·n²·d_avg/2)·(ln(c2/ρ)+c3·ρ+c4·ρ²)，ρ=(D_out−D_in)/(D_out+D_in)
  填充比、d_avg=(D_out+D_in)/2、n 允许分数（原文拟合库口径）；Table III
  单项式（八角 β=1.33e-3，μm/nH 单位口径）。原文 Table IV 两条八角实测例
  回放钉住（n=4/5、d_out=346μm、w=18、s=2μm → 原文实测 5.90/7.50nH）：
  本实现 5.993/7.447nH，误差列 |Δe|≤0.3 个百分点、对实测 |ΔL|/L≤10%
  （tests/unit/test_nfc_coil.py）。
- 仓内单源：core/nfc_coil（spiral_inductance 三式+turn_perimeter_m 匝梯
  几何+winding_parasitic_capacitance_f 匝间寄生 C 一阶，未标定如实声明）；
  CALC 键 octagonal_spiral_inductance（μm 参数薄注册包装，公式零复制）。
- 拓扑口径：八角折线螺旋（across-flats，45° 切角阶梯盒相邻重叠保导通），
  d_out 闭式=d_in+2nW+2(n−1)S；内端过孔上引跳线桥出外端同侧（§13.3
  lange air-bridge 同法）；外端-焊盘水平桥隙 LumpedPort 串联口径
  （Zin=50(1+S11)/(1−S11)，低频 L=Im(Zin)/(2πf)，SRF=绕组寄生并联谐振峰）。
- 验收：提取 L 对闭式 ±25% + SRF>2×f0（CALC 门随结果透传）。名义档
  n=5/din=80/w=10/s=5μm → d_out=220μm、ρ=0.4667、电流片式
  L=4.1147nH（三式互差 3.1%）；用户 HFSS 实测 2.4GHz L=4.226nH（默认
  网格）/4.312nH（金属局部 5μm 网格），偏差 +2.7%/+4.8%（门内）；C_par
  一阶 80.75fF → SRF=8.73GHz（对实测 6.32/7.18GHz 同量级，未标定如实）。
- **网格敏感性告警（用户 HFSS 实测教训）**：HFSS 默认网格 Q=10.86，金属
  局部 5μm 网格复核后 Q=13.44——默认网格 Q 低约 19% 而 L 只动 ~2%：
  **L 对网格钝感、Q 强烈依赖金属边缘网格**，Q 类判读必须金属局部细网格
  复核，单看默认网格 Q 会误判品质。Q 预算门阈值留真机批实测定。

### 19.2 mim_cap MIM 电容

- 闭式：平行板 C=ε0·εr·A/d（A=上极板叠合面积 w·l）教科书精确式，边缘场
  偏差 O(d/√A) 如实声明，**不引入未核修正系数**（铁律 1c：可选修正不做
  凭记忆式）；小电容档 O(d/√A) 占比上升，±25% 判据在精确几何档成立。
  串联寄生一阶：R_s=ρ·l/(t·w)（双板串联，趋肤/邻近不在内）、
  L_s=μ0·d·l/w（宽板 Ampère 精确 × 回路路径，可推导非转写）→
  SRF=1/(2π√(L_s·C))；MIM 本体自谐振远高于工作带，实测 SRF 由端口引线
  寄生主导（core/ipc_cap 模块头一阶口径声明）。
- 仓内单源：core/package_interconnect.mim_capacitance（复用零公式复制，
  #116）；报告面 core/ipc_cap.mim_capacitance_report；CALC 键
  mim_capacitance。
- 拓扑口径：下极板零厚金属面（足迹四周外伸 bot_overhang 抑制边缘场集中）
  + 介质真实体块 z∈[H,H+d]（SiNx）+ 上极板零厚金属面；竖直 LumpedPort
  跨介质（并联口径：Zin=R_s+jωL_s+1/(jωC)，低频 C=−1/(ω·Im(Zin))，
  Im(Zin) 过零=串联 SRF）。
- 验收：C±25% + SRF>2×f0。名义档 w=l=20μm/d=0.2μm SiNx（εr=7.5）→
  C=132.8128fF（面密度 0.332fF/μm²=0.2μm SiNx IPD 典型档）；串联寄生
  R_s=8.13mΩ（ρ=2.44e-8 金、t=3μm）/L_s=0.2513pH → SRF≈871GHz（CALC
  名义档输出 871.12GHz）。
- **薄介质网格成本告警**：介质 z 向三线（H、H+d/2、H+d）显式入网保证
  端口激励体积 ≥2 格（#283），最小 z-cell=d/2 → dt≈d/2c——d=0.2μm 档
  **dt≈0.33fs**，比 mm 级结构小三个量级，NrTS 预算按 dt 实测折算（#312
  纪律）；#152 近重合去重阈值 z 轴降为 d/4（全局 1μm 阈值会吞介质线）。

### 19.3 interdigital_cap 叉指电容（IDC）

- 闭式：侧壁 sum-of-capacitances 一阶——(N−1) 个相邻齿缝各贡献
  C_pair=ε0·εeff·t·l_c/s（面对面积 t·l_c、缝距 s 的几何恒等式推导，非
  文献转写），εeff=(1+εr)/2 衬底半空间均匀化，l_c=lf−e_tip（B 排尖部
  外伸段不产生相邻缝）。**精度类 ±50% 如实**：槽平面（共面缝）场与齿端
  边缘场为同阶省略项，薄金属（t/s 小）时系统性低估（零厚极限侧壁项→0
  而槽平面场有限）；Gevorgian 1996 级 even/odd 模精确式为上位替代——
  原文数表未逐位核对，不凭记忆转写（铁律 1c）。另：渲染零厚金属 vs
  闭式侧壁 t=3μm 跨口径（双处声明，真机对拍注记）。
- 仓内单源：core/ipc_cap.interdigital_capacitance_f（scope_note 携带
  ±50%+低估偏置声明）；CALC 键 interdigital_capacitance。
- 拓扑口径：n 根指 A/B 两排交错梳齿互锁（两排 DC 隔离=定义性质，几何
  审计恰 2 分量）；双水平桥隙 LumpedPort 串联口径（理想串联元
  Z=2·Z0·(1−S21)/S21 → 低频 C=−1/(ω·Im Z)，与 em deembed 的 Z12 提取
  链同式；Z12 对 T 型串联元精确、对 π 型端并联敏感——去嵌后口径）。
- 验收：对用户实测 C=173.5fF（Z12 去嵌后）±50% + SRF>2×f0。名义档
  n=24/lf=220/wf=sf=5/e_tip=15μm（l_c=205μm、t=3μm 金、εeff=6.95）→
  C=174.087fF（23 缝对 × 7.569fF），对实测偏差 0.34%（用户几何未给全，
  同量级参考对拍非逐位锚）；串联寄生一阶 R_s=824mΩ/L_s=209.9pH →
  SRF≈26.3GHz（CALC 名义档输出 26.33GHz）。

## 20. layered_stack 晶圆键合叠层族：真空约定+双档 INCOMPLETE 根因链+馈段四壁延续教训（aurora_q，2026-11-07；Q-X4/X6/X10/X11/X12/X14/X26/X28/X54 多席整合，Q-X56 落版）

族语义：晶圆键合/SIW/SICL/空气腔悬置线——「多层叠层+挖腔+腔壁金属化+
波端口落腔体截面」三维叠层结构（第 76 号模板，外部用户晶圆键合实测反馈
吸收立项）；名义锚 f0=95GHz、带 85–105GHz、闭式 εeff=1.60076
（qx10_verdict closed_form_anchor 现算）、用户 HFSS 实测 |S11|max=
−23.5dB@50Ω。单源=adapters/layered_stack_spec.py（schema+layout+lint
投影三件套），双引擎渲染器 oe_templates/render_layered_stack.py 与
hfss_builder_layered.py 纯消费。
（2026-11-08 勘误补记见 §20.6：Q-X54 判读对象勘误+RC1 结构归因闭合
升级+RC2 正交隔离跑在跑待补。）

### 20.1 真空约定与 v1 族约束（两引擎同口径建模铁律）

- **真空=普通 Box 完全包住全部固体**（不布尔差、直接重叠）——HFSS
  validate 对"完全包住"放行可解，对"部分相交"（实体穿出真空盒边界）报
  `Parts Vacuum and W2_Membrane intersect.` 求解失败——判定=完全包含
  放行/部分相交 ERROR，两情形结论相反不可互推（§0.1 同笔；geometry_lint
  检查④ partial_intersection 同口径：两两 AABB 相交且非包含才报）。
- **挖腔=分层围合**：非导体层按腔足迹分段、导体层完整横跨——零布尔运算
  （HFSS 侧纯分段坐标可离线审计；openEMS 侧 CSXCAD 按优先级原语天然免
  布尔）。
- **v1 族约束（渲染守卫显式拒绝，不静默兜底）**：腔沿传播轴贯通全长（波
  端口落腔两端截面=模型端面）；腔 z 区间完整包含导体层（膜悬置=定义性质，
  部分重叠拒绝）；腔 z 中心=带面（openEMS StripLinePort 对称探针 ±height
  口径，不对称腔无有效 height）；腔宽>strip 宽（带须悬置于腔内）；端口
  截面=腔体截面（size 缺省自动=腔 w×h，显式给出必须逐位一致）；膜横跨腔
  截面把端口空气区分为上下两腔=本族合法形态（连通域=2 口径）。

### 20.2 C 档/A 档双档 INCOMPLETE 四档对照总账（Q-X26/Q-X28 comparison_four_tier.json）

| 档 | 几何 | 网格 base/cells | NrTS/物理窗 | εeff_med（双口均值） | over_unity | passivity_max | verdict |
|---|---|---|---|---|---|---|---|
| C_qx10 前态 | pre-fix | 40µm / 4.60M | 51000 / 624.9ps | 0.6290（151/201 点 <1） | 66 | 2.791 | INCOMPLETE（原判 truncation-suspect） |
| A_qx11 前态 | pre-fix | 16.55µm / 26.99M | 135000 / 1255.1ps | 9.014（口1 13.32/口2 4.71，146/201 点 >εr） | 201（全带） | 5.000 | INCOMPLETE（S0 版重判 port-structure-suspect） |
| C_qx10 修复后 | post-fix | 40µm / 4.60M | 51000 / 624.9ps | 1.8317（对闭式 +14.4%） | 0 | 0.817 | INCOMPLETE（port-structure-suspect） |
| A_qx28 修复后 | post-fix | 16.55µm / 26.99M | 135000 / 1255.1ps | 326.6 | 201 | 2.617 | INCOMPLETE（port-structure-suspect） |

G0 反解自洽锚四档全 PASS（design_residual 7.1e-15Ω，#118 裁判）；A 档
修复后重发射=lab_server 27M cells 真跑 12315s（302 Mcell/s，NrTS 135000
走满未提前停）。INCOMPLETE/未判档原样透传不升格不凑绿（#122）。

### 20.3 RC1 主根因：馈段四壁未延续（Q-X12 五假设调查，H1 CONFIRMED/H2–H5 REFUTED）

- **机制链**：渲染器声称的"匹配馈延续"只兑现 1/3——馈段（|x|>±L_HALF 至
  ±DOM_X）只有 strip（StripLinePort 自画）+膜片（渲染器补），四壁（±height
  上下地+两侧壁）未延续。openEMS StripLinePort 契约（安装版 ports.py 实证）：
  端口只画 strip 金属（地不在端口职责内）、Feed_R=inf 缺省分支零绘制、
  电压探针=±height 对称对（语义 "toward the upper and lower ground
  planes"——**地是几何的责任，端口不建**）→ 探针面（馈段内）z=±height
  金属盒命中数=0（静态 11 盒逐点审计）→ 探针积分穿真空、i 环绕无回流单
  导体 → u/i 非任何模式的模式一致对 → telegrapher 提取（β=√(−dEt·dHt/
  (Ht·Et))、Z_ref=√(Et·dEt/(Ht·dHt))，成立前提=单一良定义模）前提崩塌 →
  CalcPort 强制 ref=50Ω 分解叠加垃圾 Z_ref → S 分解破无源性 → |S|>1。
- **三条物理不可能性铁证（任一条独立判死）**：①εeff<1（C 档 151/201 点，
  β<k0——准 TEM/介质填充线不可能，物理界 1≤εeff≤εr）；②εeff>εr=11.9
  （A 档口1 146/201 点——超全填充上限，任何介质波导模不可能）；③对称
  结构双口 β 差 29.5%（C 档）/50.9%（A 档）——同一传输线两端测同模 β
  必相等。加网格对照：base 2.42× 细化+窗 2.65× 加倍，εeff_med
  0.629→9.01 发散不收敛——**网格精度不是根因**。
- **RC2 截断假设证伪**：A 档按 #262 处方加倍窗（NrTS=135000=4.38× 激励
  步数 30816，物理窗 1255.1ps≥C 档加倍窗 1249.9ps）over_unity 反而
  66→201（全带）——加倍 NrTS 治不了端口失义。截断处方流程没错（如实
  INCOMPLETE 不凑绿正是它触发调查席），错在归因。
- **garbage 形态随网格变、违反物理界的本质不变**：C 档（x≈10µm 均匀档）
  排"近截止样"低 β/亚 k0 形态，A 档（探针间距 8.9µm、shift 随 BASE 缩放）
  排超 εr 界近常数相位形态——判读先过物理界铁证再谈收敛/截断。

### 20.4 Fix1/2/3 修复与修复后残留（Q-X14 commit 620d3024；Q-RM-3/Q-X28 重跑）

- **Fix1（主修，openEMS 渲染器）**：metal_sheets 六面腔壁盒 x 范围重定至
  馈段共 12 盒（(y,z) 几何单源不动，strip 体段盒除外——馈段 strip 仍由
  端口自画）；PEC 延伸入 PML=波导馈标准形态，网格零改动（壁面 y/z 已是
  特征线，±DOM_X 已入 x 网格，PEC 片不增 cell）。HFSS 侧无此概念（波端口
  落腔端截面无需馈段）——引擎不对称已在渲染器头注如实登记。
- **Fix2（渲染端 fail-loud 守卫×2）**：每面腔壁馈段延续存在性断言+探针面
  z=STRIP_Z±PORT_HEIGHT 平面金属覆盖断言（#212 离线审计同款零仿真；
  Q-X14 实证 probe_hits 0→1×4）。
- **Fix3（判读端 S0 结构哨兵三检，先判端口失义再谈截断）**：β 线性度
  （一次拟合 r2<0.95）／ZL 合理性（Re(ZL) 中位出 [10,200]Ω）／双口一致
  （|β1−β2|/均值 中位 >0.2）——命中⇒ verdict 记
  `INCOMPLETE(port-structure-suspect)` 指认 RC1 方向，**不进 #262 加倍
  NrTS 处方**（门限冻结版见 qx10_verdict.py，#122 冻结不改）。
- **修复后质变（C 档重跑实证，四壁延续生效的直接证据）**：εeff_med
  0.629→1.832（非物理 0.63→物理量级；对闭式 +14.4%）、over_unity 66→0、
  passivity_max 2.791→0.817、|S21| 均值 −11.37→−1.21dB、G2 谷
  99.2GHz/深 −27.5dB——但 S0 哨兵仍 TRIGGER（口1 β r2 0.806<0.95、口间
  一致 0.213>0.2）⇒ INCOMPLETE(port-structure-suspect) 如实登记。
- **修复后 A 档决定性实验（Q-X28）**：S0 仍 TRIGGER（β r2 0.0858、口间
  一致 0.619），εeff_med=326.6、over_unity 仍 201——RC 矩阵判定
  **RC1 仍 implicated（网格+窗联合精化不治）**、RC3 截断 C 档排除/A 档
  co-present not attributed、RC2 网格 not_observable（现存对照=网格+窗
  联合精化，正交归因需单因子隔离跑：同 mesh 换窗/同窗换 mesh）。
- **遗留（如实）**：L1 体区"介质窗"二阶面（膜横穿侧壁 y=±0.45 处无 PEC，
  场可经膜-金通道外泄——用户实测与 HFSS 模型同形态 −23.5dB 背书良好，
  判二阶扰动不修；修复后 εeff 对闭式差 >5% 先查此面再查闭式近似）；L2
  G2 谷位受两端过渡干涉相位支配（spec §5 预声明注记）；L3 单因子隔离跑
  未做；族级根治（Q-X55 在飞）未收官前 verdict 保持 INCOMPLETE。

### 20.5 四壁延续教训（落版五条）

1. **注释≠实现**：渲染脚本注释声称"腔管截面（膜片+四壁）同步延续=匹配
   端接"而四壁缺失——几何声明必须以静态命中审计验证（11 盒逐点探针面
   命中检查，#212 家族：字符串存在性+compile() 抓不住画法错误）。
2. **端口原语的地是几何的责任**：StripLinePort 族只画 strip 不画地
   （Feed_R=inf 缺省分支零绘制），±height 对称探针预设地面存在——凡用
   端口原语预设"±height 有 PEC"的模板，渲染端必须自证延续面存在
   （fail-loud 断言，Fix2 模式收编为惯例）。
3. **结构哨兵先于截断处方**：|S|>1 先查端口失义三检（β 线性度/ZL 合理性/
   双口一致），命中即 INCOMPLETE(port-structure-suspect) 指认结构方向，
   不盲目加倍 NrTS——RC2 实证加倍窗反而恶化（66→201）。
4. **物理界铁证优先于任何收敛叙事**：1≤εeff≤εr、对称双口 β 一致、
   passivity≤1——任一铁证破即测量失义，网格细化救不了测量前提崩塌
   （base 2.42×+窗 2.65× 联合精化 εeff 反而发散）。
5. **判据不凑**：修复后 εeff +14.4% 与 S0 仍 TRIGGER 均如实登记不升格，
   决定性实验（修复后几何×A 档）照跑不因前态惨烈跳过——四档对照矩阵
   （geometry×mesh 两因子）是 RC 归因的最小完备设计。

### 20.6 四壁延续定谳补记与判读对象勘误（2026-11-08，Q-X66/Q-X71）

> 本节为 20.2–20.5（Q-X56 落版，写于勘误前）之后的定谳补记——既有
> 20.1–20.5 段落原文一律不改写（历史账本只加不抹），勘误链全部已定谳
> （DEVLOG 二百八十二），本节按定谳口径落版。

**勘误时间线（判读对象错挂→证据链→定谳）**：Q-X54（DEVLOG 二百七十四）
收割判读所消费的 a_auto 目录实为 **Q-X11 代旧未修复跑**而非 Q-X28 的
a_auto_fix 修复后跑——其数字 εeff_med=9.014453/over_unity=201/发散于
94189 步=69.8% 帽窗与四档表 A_qx11 前态行逐位吻合，故其「修复后几何×A
档=决定性实验待跑」结论**不成立**（该象限已由 Q-X28 于 2026-11-07 跑毕：
12:22 发射满窗 135000 步 wall=12315.36s rc=0、15:52 收割判读）。证据链=
Q-X66 席三方逐字节绑定实证：渲染器 oe_templates/render_layered_stack.py
自 Fix1/2 commit 620d3024 至今零改动（git log 实测）+新鲜渲染文本 sha
a8588231… ≡ Q-X28 发射记录 render_sha256+镜像 a_auto_fix/simulation.py
文件 sha 349168d8… ≡ 上传记录（跨域 CRLF→LF 归一化恒等）——确定性引擎
下重发=零信息（Q-X66 就绪态未发射，qx66_relaunch/launch_notes.md 全档
备查）。

**RC1 结构归因闭合升级（同网格同窗对照两行定谳）**：

| 对照行 | 几何 | 网格/窗 | 终止形态 | 能量终态 |
|---|---|---|---|---|
| A_qx11 前态 | pre-fix | 16.55µm base/26,987,400 cells，NrTS=135000 | 发散终止于 94189 步=69.8% 帽窗 | energy→3.25e+27→inf |
| A_qx28 修复后 | post-fix（Fix1/2/3 @620d3024） | 同网格同窗，NrTS=135000 | 135000/135000 满窗走满未提前停，rc=0，wall=12315.36s（302.27 MC/s） | 能量全程有限，窗末 −0.05dB（~5.18e+14） |

修复几何（Fix1/2/3）×A 网格×A 窗满窗**无硬发散**，对比 pre-fix 同网格同
窗 energy→inf 于 69.8% 帽窗终止——**发散=结构因，RC1 闭合**（四壁未延续
是发散的充分成因，被修复消解）。20.3 机制链叙述不变，本对照升格为其
定谳背书。

**残余病理不变（如实）**：A_qx28_postfix 仍 over_unity=201/201（全带）+
S0 TRIGGER（beta_linearity_r2=0.0858<0.95、port_agreement=0.619>0.2）+
εeff_med=326.6（闭式 εeff=1.6007603731686557，≈1.6008）——**端口失义
未愈**，四档 INCOMPLETE 定性维持（20.2/20.4 判读不升格不凑绿）。自此
「发散」与「端口失义」分立为两个问题：前者 RC1 已闭合，后者的归因真缺位=
RC2 正交隔离跑（现存对照=网格+窗联合精化，单因子未隔离，20.4 遗留 L3）。

**RC2 正交隔离跑（在跑待补）**：post-fix×A 网格×C 窗（NrTS=51000，预算
~77min@302 MC/s）由 Q-X67 席在跑，结果待收割——本节落版时如实写「在跑
待补」，不预写任何结论，收割后另行补记。反向臂（post-fix×C 网格
0.04mm/4,599,980 cells×A 窗 NrTS=135000，预算 ~35min）在四档表
orthogonality_caveat 指认清单内待派。

**教训六（20.5 五条的扩充第六条）——判读对象指纹绑定**：判读席收割前
必须先核对任务目录指纹与预期镜像绑定——Q-X54 按目录名取材致旧跑冒充
新跑（**同名目录≠同一次跑**）；三方 sha 绑定（渲染器 commit/渲染产物/
上传镜像）是收割前置验证的家法（Q-X66 四域实证：文本域/文件域/归一化
域/上传记录域逐位恒等）。

### 20.7 RC2 正交隔离跑结果补录（2026-11-08，Q-X67）

**结论：窗长主导证据（window_dominated_evidence，预声明锚内判定）**。
post-fix 几何×A 网格×C 窗（NrTS=51000，单变量=窗长，与 Q-X28 发射件
逐行 diff 恰 1 行；三方 sha 绑定 c1335b96…）：over_unity **201→0**、
εeff_med **326.6→3.83**（85×，rel +139.3% vs 闭式 1.6008）、passivity
**2.62→0.57**、末窗能量 −0.17dB（51000/51000 满窗 wall=4699.6s rc=0）。
——A 档满窗（1255ps）的灾难性端口病理由**晚期未衰减场污染提取**驱动，
短窗（474ps）消除该伪象层。

**三态对照**（comparison_three_tier.json，冻结判读函数 verdict 全
INCOMPLETE 如实）：本席 A×C 窗（over_unity 0/εeff 3.83/S0 TRIGGER 三检
全败 β-R² 0.005/agreement 0.647/zl [8.52,47.21]Ω FAIL）vs C_qx10_postfix
（0/1.83/TRIGGER 两检/agreement 0.213/zl PASS）vs A_qx28_postfix
（201/326.6/TRIGGER 两检/agreement 0.619/zl PASS）。

**残余病理分立如实**：εeff +139% 未达 C 档 +14.4%；S0 三检全触发且 β
线性度 0.005 反劣于 A 窗 0.086——**端口结构失义（RC1 方向）在全部
post-fix 跑恒 TRIGGER，qx12 结构嫌疑进一步坐实**；"窗长伪象层"与"结构
失义层"分立为两层。

**已知限制**：物理秒口径未隔离——A 网格 dt 细使 51000 步仅 474ps<C 档
物理窗 625ps，"窗长主导"以步数口径对照成立；同物理窗定量分离需补对照
跑（post-fix×C 网格×A 物理窗，待派）。C 窗参数三源交叉核对冻结于
criteria_qx67.md §2（comparison_four_tier C_qx10_postfix 行 nrts=51000
/qx28_config C_NRTS/criteria_qx28 §3 加倍窗输入）。

**终证补录（2026-11-08，Q-X78 物理窗对照跑）**：post-fix×C 网格×A 物理窗
（NrTS=102426=round(135000×9.297037fs/12.253783fs)，物理窗 1255.106ps，
真跑 rc=0 满窗 wall=2260s 末窗 −48.73dB）判读=**window_dominance_terminal
（窗长主导终证）**：五键与 C×625ps 基线几乎逐位保持（εeff 1.8340 vs
1.8317、rel 差 0.16pp、over_unity 0/0、zl PASS/PASS）——窗长（625→1255ps）
在 C 网格上零敏感。双层结论精化：**病理=网格细节距在长物理窗下显现，
窗长是呈现开关（物理秒尺度）、网格是载体**；S0 四态全 TRIGGER（端口
结构失义网格/窗两轴均不治，独立残余维持，qx12 方向）。归因链三笔合成
终局：RC1 结构归因闭合（二百八十二勘误后）+RC2 步数口径窗长主导
（二百九十三）+本笔物理窗口径终证。

## 21. EDA 格式解析器集成指南——IBIS/Liberty/CITI/SDC/Verilog 五格式（aurora_q，2026-11-07；Q-X34/Q-X35/Q-X36/Q-X46/Q-X47 五席交付汇总+Q-X32/Q-X33 相邻面，Q-X56 落版）

**共性架构（五席同款，接新格式照抄）**：core 纯函数解析内核（零 IO/零
依赖/确定性——铁律 7：结构化数字只出自数据源文本与内核声明式公式，LLM/
agent 永不产生物理数字）→ service 包装（规则 4：JSON 信封进出，error 信
封构造器）→ CLI 薄壳叶（parse/list，--json 旗标）。错误=ParseError
（ValueError 子类，带行号文本）→服务层转 error 信封→CLI exit 1。未识别
构造**宁降级不炸**（warnings 如实回显零静默丢弃）、数值**宁 raw 不编数**、
判定**宁不报不误报**（#122 诚实语义三分支）。不设 `__all__` 的非门面文件
不进 tests/gold/public_api.json（零金快照漂移惯例）。

### 21.1 IBIS（Q-X46：core/ibis_parser.py，CLI ibis parse/list 两叶，96 测）

- **格式定位**：数字 IO buffer 行业标准（IBIS Open Forum v3.2/v4.x 经典
  节面）——SI 信号完整性读 buffer 模型的单源入口。
- **核心语法**：`[Keyword] args` 方括号 keyword（名大小写不敏感）+参数值；
  `|` 起行注释（行中任何位置）；数据行按当前节 mode 分派（typ/min/max
  三列惯例）；[End] 必须收尾（缺失/其后内容报错——ibischk 同口径）。
- **解析面**：头部 [IBIS Ver]/[File Name]/[File Rev]/[Date]/[Source]；
  器件 [Component]/[Package]（R_pkg/L_pkg/C_pkg 三列）/[Pin]（GND/VDD/NC
  =无模型两列形态）；[Model Selector]/[Model]（Model_type/Polarity 等
  子参数 `key = value` 与三列 typ-min-max 两形态）；四张 IV 表
  [Pullup]/[Pulldown]/[GND Clamp]/[POWER Clamp]（Voltage+I 三 corner）；
  [Ramp]（Ramp_load/Ramp_dR/Ramp_dF）；[Rising/Falling Waveform]
  （R_dut/C_dut/L_dut/V_fixture 必填元参数+time+V 三 corner）。
- **陷阱**：①单位词法=数字+可选后缀换算基准单位（V/A/Ohm/H/F/s/Hz 全谱
  +裸 SI 前缀——"10.0n" 是 IBIS 时间惯例写法）与 "X/Y" 比值形态
  （Ramp_dR "-2.228/V" 家族）并存；未知后缀报错宁红不猜；裸 "f"=femto
  前缀（法拉恒带词根 pF/nF/uF，裸 F 形态不存在——如实记录口径）。
  ②真实供应商文件含大量超范围 keyword（[Diff Pin]/[Die]/[Pin Mapping]
  等）→ 未识别 keyword 进 warnings+内容忽略，宁降级不炸。
  ③多器件文件：[Package]/[Pin] 归属当前 [Component]（IBIS 多器件惯例），
  而 [Model]/[Model Selector] 文件级不回填器件归属（如实声明）；pins
  扁平视图跨器件同号后者覆盖——多器件以 components[].pins 为准。
- **插值内核**：interp_iv（Voltage→Current）/interp_waveform（time→
  voltage）线性插值+边界夹取，x 轴要求严格递增（spec 表序），corner 列
  缺如如实 ValueError。

### 21.2 Liberty（Q-X34：core/liberty_parser.py，CLI liberty parse/list 两叶，69 测）

- **格式定位**：Synopsys Liberty .lib 时序库（IEEE 1601 系自由格式）——
  数模混合设计 timing/power 引用入口。
- **核心语法**：组 `cell (NAME) { … }`（类型名+圆括号名表+花括号体，名表
  可空 `timing () {…}` 惯例）；简单属性 `area : 4.5 ;`；复合属性
  `index_1 ("0.01, 0.2") ;`；值类型=带引号字符串/数字（整型字面量→int，
  ±inf→float）/词（true/false→bool，其余保留字符串）；`/* … */` C 风格
  块注释（**字符串字面量内不剥离**）；行尾反斜杠=行连续（values 表多行
  惯例）。
- **NLDM 主面**：library（name/file_version/单位属性）/cell(area)/pin(
  direction/function/capacitance)/timing(related_pin/timing_sense+四张表
  cell_rise/cell_fall/rise_transition/fall_transition)/lu_table_template/
  operating_conditions；功率面 pin 级 internal_power（rise_power/fall_power/
  power）+cell 级 leakage_power（values/value+when）/cell_leakage_power。
- **陷阱**：①NLDM 两维表 index_1（input transition）×index_2（output
  load）→values 矩阵；一维表（仅 index_1）与零维表（单值）按 dims 键
  归一。②表组可引用 lu_table_template（组名即模板名）——index_1/index_2
  缺省时从模板继承，values 恒为本地（继承只补 index 不补数据）。
  ③不做 Liberty 全语义（CCS/ECSM 深表、check_timing 约束建模按需扩展）
  ——未识别组/属性 attrs 透传+groups 子组表保留，消费端可继续下钻。

### 21.3 CITI（Q-X35：core/citi_parser.py，CLI citi info/segments/network 三叶，45 测）

- **格式定位**：HP/Agilent/Keysight 仪器 CITIfile（.cti）文本包——仪器
  传输中间格式（IC-CAP/ADS/PLTS 生态），RF 侧仪器 S 参数数据的入口。
- **核心语法**：首行版本行必判（`CITIFILE A.01.01`；缺=非 CITI 文件报错；
  `CVG VERSION` 为替代形态）；NAME/VAR/CONST(ANT)/VAR_LIST_BEGIN/END/
  SEG_LIST_BEGIN/SEG start stop count/SEG_LIST_END/DATA name fmt
  （RI/MAGANGLE/DBANGLE ASCII 对）+BEGIN/END 数据块；COMMENT 与 `!`
  注释；`#DEV` 设备关键字。SEG 线性段频率合成
  F(n)=start+(n−1)·(stop−start)/(count−1)（Ansys Circuit 文档口径）。
- **二进制扩展**：`SEG <格式串> <记录数>`——格式字母 A=%16E（16 hex 位
  double，**大端字节序**——HP 68000 系谱惯例）/B=%8E（binary32）/
  C=%10F/D=%6E/E=ASCII float；BEGIN_MODE/END_MODE 块内 MODE 逐记录形态
  （IC-CAP 模式块）。
- **陷阱（诚实语义 #122 族——本格式最大坑位）**：①C=%10F（40 bit）/
  D=%6E（24 bit）**没有 IEEE-754 标准位型映射、公开规范不可查**——
  decode_status="unsupported_width" 如实保留结构（格式字母/原始 hex 串/
  记录数），不解码出任何数值（宁 raw 不编数）；A/B/E 精确解码（struct
  位型往返逐位相等，测试钉住）。②布局歧义（SEG 每记录字段数与声明的
  dependent 数对不上）→ decode_status="layout_ambiguous"，values=None+
  raw 保留不猜。③BEGIN 无 END（文件截断）→ warning+已收记录如实保留
  （截断态），不假装完整；非记录杂行逐行 warning 零静默丢弃。
  ④**skrf 桥不在 core**（零依赖纪律）——service/citi_service 消费结构化
  输出组装 skrf.Network，数据段格式匹配才可桥，条件不满足走 skipped
  信封如实声明。

### 21.4 SDC（Q-X36：core/sdc_parser.py，CLI sdc parse/list 两叶，74 测）

- **格式定位**：Synopsys Design Constraints——Tcl 语法子集，clock/timing/
  IO 约束面。
- **Tcl 词法覆盖**：命令分隔=换行或 `;`；注释 `#`（命令位/`;#` 位正式
  规则；**词位起头也按 SDC 工具宽容惯例作注释**——严格 Tcl 会当普通词，
  生态两形态都常见，取宽容口径并如实声明；词中 `#` 是普通字符 `net#1`
  保真）；词形态=裸词/"引号词"（可含空白，转义+替换生效）/{花括号词}
  （**零替换**、嵌套配平、可跨行——SDC 多行列表惯例）/[方括号] 命令替换
  （子脚本原文保留按需递归——`[get_ports {a b}]` 对象访问器惯例）；
  一词可多段拼接（`clk$idx`/`pad[get_cells x]`）；变量 `$name`/`${name}`
  ——set 命令按解析序即时更新环境变量表，未定义如实保留原文 `$name`
  （静态解析无运行时语义，不猜不炸）；转义 `\x` 取下一字面字+行尾反斜杠
  行连续；`"`/`{`/`}` 只在词首特殊（Tcl 语义），词中一律普通字符。
- **SDC 语义面（八桶）**：clocks（create_clock -name/-period/-waveform/
  -add，无名时钟从源对象首 pattern 派生标 auto_named；create_generated_
  clock -source/-divide_by/-multiply_by/-edges）；delays（set_input_delay/
  set_output_delay——**既无 -max 又无 -min 时 Synopsys 语义=双边同时置
  值**，max=min=true 如实落键）；paths（set_false_path/set_max_delay/
  set_min_delay -from/-through/-to）；constraints（set_load/set_driving_
  cell/set_fanout_load/set_case_analysis/set_multicycle_path/set_clock_
  latency/set_clock_uncertainty）；对象访问器 get_ports/pins/cells/nets/
  clocks（内联子命令与顶层独立命令两路径统一收集 patterns；pattern 按
  空白+逗号切分——`{clk_p, clk_n}` 逗号形兼容收取）。
- **陷阱**：①未知命令不报错（SDC 文件合法含工具私有命令）→ warnings
  （line+name）披露后继续解析——宁全量带警告不半途而废。②负数值
  `-1.0` 不被当旗标（旗标=`-` 后字母起头）。③词位 `#` 宽容注释口径的
  双面性：消费端需知悉本解析按注释剥、严格 Tcl 工具可能当普通词——
  跨工具复用时留意此口径声明。

### 21.5 Verilog 网表（Q-X47：core/verilog_netlist_parser.py，CLI verilog parse/list 两叶，73 测）

- **格式定位**：IEEE 1364 结构网表子集——数字后端（综合/PnR）输出的
  gate-level netlist 标准交接面，结构分析（module/port/wire/assign/
  instance/parameter/defparam）单源入口。
- **词法覆盖**：`//` 与 `/* */` 注释（块注释未闭合报错带行号）；字符串
  字面量（未闭合报错）；普通标识符+**转义标识符** `\name` 到空白止
  （EDA 工具网表常见）+层次名 `a.b.c` 自然合成；数字=十进制明数（含
  `_` 位分隔）+**位宽字面量** `8'hFF`/`4'b0101`/`12'd135`/`1'bx`
  （parse_verilog_number 单源，parameter 数值提取同源消费）；系统任务
  `$display` 类词法识别；编译器指令 `` `timescale ``/`` `define ``/
  `` `include ``/`` `ifdef `` 族整行消费（含行尾续行），指令名收进
  directives 名录（网表功能语义不依赖指令体，静默跳过+如实登记）；
  多字符运算符最大吞噬（`<=`/`===`/`<<<` 等）。
- **语义面（模块级五桶+参数面）**：ports（**ANSI 2001 头内全声明与 1995
  头列名+体内方向声明双形态统一归一**；direction 无法判定如实 None；
  width={msb,lsb,span}）；wires（wire/reg/tri/wand/wor/supply0/supply1
  含 kind/init）；assigns（多目标逗号形逐条展开，delay 原文记录）；
  instances（**门级原语 LRM 14 章全集**（and/nand/…/pullup/pulldown）经
  GATE_PRIMITIVES 注册表（RegistryKit，规则 3）把位置连接归一命名映射
  out/in1..inN/ctrl+模块实例 named/positional 双形态——位置连接按子模块
  端口声明序对位，未知子模块（外部单元库）连接网如实入 external_boundary_
  nets）；parameters/localparams/defparams。
- **拓扑提取 extract_module_topology**：三层关系实例→网→实例
  （net_drivers/net_readers 双向图+instance_edges 边表）；孤立网双桶
  undriven/unloaded（**reg 类网不判 undriven**——行为块跳过属已知盲区，
  无证据不下结论；外部未知实例连接网豁免——宁不报不误报）；DAG 树深度
  +关键路径（同层取字典序=确定性）+组合环检测（cyclic=True 时 depth
  如实置 None 不猜；3000 级链迭代 DFS 防递归爆栈）。
- **陷阱**：行为块 always/initial/function/task/specify/generate 整体
  跳过记 warning（结构网表解析不进行为语义——被跳块内过程赋值驱动的
  reg 是孤立网检测盲区，双桶口径已内建豁免）；病态实例语句解析失败降级
  警告+跳语句，不炸全文档。

### 21.6 相邻面与跨格式消费链（Q-X32/Q-X33/Q-X48/Q-X49）

- **SPICE 网表解析器（Q-X33：core/spice_netlist_parser.py，CLI spice
  parse 单叶，59 测）**：ngspice/HSPICE/Spectre 三格式统一五维度结构化
  输出（elements/subckts/controls/models/topology）；flavor auto 内容
  启发式判定（simulator lang 显式>spectre 信号>ngspice .control>HSPICE
  .option post/.step/`;` 注释）；拓扑=MNA 维度（非地节点+V/E/H 分支
  增广）+节点双向图+孤立节点检测+接地归一（0/gnd/gnd!）+子电路调用层次
  树（环截断）；fail-soft（结构错误进 structural_errors 不中断；表达式
  值保留原文不代入）；.control/.endc 交互块整块收编防误吸元件；方言终止
  符 .endl/.endfl/.endt/ends 收编+warning。
- **SKILL 模板生成器（Q-X32：core/skill_template_engine.py，CLI skill
  三叶，57 测）**：非解析器——Jinja2 形态自制微实现（{{var}}/{%for%}/
  {%if%}/{#注释#}+|raw/|default 过滤器）+六检查语法守卫 fail-loud+5 电路
  设计模板（aedt_run_simulation/cell_layout/layer_setup/schematic_instance/
  waveform_export）byte-identical——EDAS 自动化脚本生成的确定性出口
  （Virtuoso-Bridge-lite 借鉴化用首块）。
- **跨格式消费链**：LVS 网表对照器（Q-X49，netgen 思想借鉴化用自研）
  双源消费 SPICE（Q-X33）+Verilog（Q-X47）——双源归一化+1-WL 颜色精化+
  元件回溯图同构+参数相对容差+RF 特化（端口/tline series/shunt/coupled
  分类），CLI lvs compare 叶（50 测）；DRC 规则解析器（Q-X48）三形态文法
  +12 类型注册表+RF 特化检查器四件（阻抗/焊盘间距/地过孔围栏/屏蔽罩间距），
  CLI drc parse/validate 两叶（89 测）。**接新格式的位次**：core 纯函数
  （零依赖、ParseError 带行号）→service 信封→CLI parse/list 叶→（如涉
  RF 数值）skrf 桥放 service 不进 core（CITI 先例）。

- **全集群扩展归属索引（Q-X75 追加行，2026-11-08；上行原文零改动——五格式
  之后的 13+ 新格式席位按族分节落 §21.7-21.11，每格式五件套：格式定位/
  核心语法要点/解析面/陷阱/集成点）**：
  - 数字后端：SPEF（Q-X60→§21.7.1）/SDF（Q-X61→§21.7.2）/LEF-DEF（Q-X57→
    §21.7.3）；SDC/Verilog 网表已在上文 §21.4/§21.5（交叉引用不重写）。
  - 版图与制造：GDSII（Q-X58→§21.8.1）/Gerber RS-274X+Excellon（Q-X59→
    §21.8.2，fab 组内两叶已接线）/IPC-D-356/356A（Q-X65→§21.8.3）/ODB++
    （Q-X68 在制→§21.8.4 如实标注零预写）。
  - 测试与波形：VCD（Q-X63→§21.9.1）/STIL（Q-X72→§21.9.2）；测试三面=
    STIL+IPC-356+VCD（DEVLOG 二百九十口径），仪器面=CITI（§21.3）。
  - 互连与封装：Touchstone（Q-X64→§21.10，#248/#287/#309 三坑经验单源化
    专节）。
  - 模拟生态：SKILL/OCEAN 语言解析（Q-X62→§21.11，与 Q-X32 skill 模板
    生成器读写对偶）。
  - MCP 暴露两批：Q-X69 mcp_tools/parser_formats.py 八工具（171→179，
    38 测）+Q-X73 mcp_tools/cad_formats.py 十工具（179→189，36 测）；
    CLI 叶接线除 fab 组内两叶外均挂账待合流（2026-11-08 时点，以
    rfauto --help 实测为准）。
  - 集群专审 Q-X74 在制（只读审查报告供合流与终门消费，零代码改动）。

### 21.7 数字后端三件套扩展（SPEF/SDF/LEF-DEF——SDC=§21.4、Verilog 网表=§21.5 已在前）

数字后端流程（综合→PnR→寄生提取→STA→时序反标）的交换格式族本节补齐三件：
SPEF 寄生（Q-X60）+SDF 时序标注（Q-X61）+LEF/DEF 库与版图交换（Q-X57）——
与 §21.4 SDC 约束、§21.5 Verilog 网表合成"约束/网表/寄生/时序标注/物理库"
五面（DEVLOG 二百八十一"数字后端三件套集齐"口径）。共性架构与 §21 卷首注
同款（core 纯函数→service 信封→CLI 薄壳）；全节 ParseError 家族+fail-soft
warning 如实回显+不设 __all__ 零金快照漂移。

#### 21.7.1 SPEF（Q-X60：core/spef_parser.py，CLI spef parse/report 两叶挂账，136 参数化测）

- **格式定位**：SPEF（Standard Parasitic Exchange Format，IEEE 1481-1998）
  寄生提取交换格式——OpenRCX/K-layout/商用提取器输出、STA 输入的标准交接
  面；RC 寄生网表（*D_NET+CAP/RES）与长名折叠（*NAME_MAP）的只读结构化
  解析单源入口。
- **核心语法要点**：①`*SPEF "IEEE 1481-1998"` 版本串头=文件身份判定面
  （缺失致命 SpefParseError）；②`*T_UNIT/*C_UNIT/*R_UNIT/*L_UNIT <乘数>
  <单位>` 单位三元组——换算系数=乘数×单位基准表（spef_unit_factor 单源；
  未知单位 fail-closed：warning+系数 1.0 原值保留，绝不猜量纲）；③
  `*NAME_MAP *id name` 长名折叠：id→name 主映射+name→id 反查双录，重复
  id 后者覆盖+warning，未映射 `*id` 引用保真展开 `<*id>` 字面（不猜不丢）；
  ④`*D_NET` 段状态机 `*D_NET *id 总电容`→`*CONN`→`*CAP`→`*RES`→`*IND`→
  `*END`；⑤`//` 与 `#` 行注释双形态（引号串内不剥）。
- **解析面**：parse_spef（header 含 dividers/bus_delimiters/scale+ports+
  nets[*CONN direction-first/type-first 双形态判定、*CAP 两列=对地/四列=
  耦合双端、*RES 四列、*IND 同 RES 形态换算亨利]）+拓扑三函数
  spef_topology_summary（逐 net 节点/元件/连通分量并查集+孤立节点宁多报
  不误报）/spef_coupling_stats（耦合总数/耦合对地比/top-k 排序键
  (-值,全局序) 确定性稳定）/spef_net_lookup（展开名查 net 全量视图，未
  命中 None）。schema v1.0（PARSER_SCHEMA_VERSION）；cap 总量一致性三数字
  （total_cap_far/cap_sum_far/cap_rel_diff）只报告不做硬门。
- **陷阱**（DEVLOG 二百七十八"已知限制"提炼）：①三值数值（min:typ:max）
  未支持——warning 整行跳过，真实提取器若用三值形态数据会**静默变少**
  （后续补）；②*R_NET/*D_PNET/*POWER_NETS/*DEFINE 未覆盖；③*I 行按第三
  词 I/O/B 分派——类型值恰为 I/O/B 会误读；④耦合电容是否计入总电容各
  提取器口径不一——rel_diff 只给数字，下结论归消费方复核。
- **集成点**：service/spef_service.py（parse_spef_file/spef_report(top_k)/
  spef_net_detail 全信封）；cli/domains/spef.py 域内自注册挂账（main.py
  re-export 待合流；二次 add_typer 双注册打红 zero-shadow 钉）；MCP
  spef_parse/spef_report 已暴露（Q-X73）。接线状态=2026-11-08 时点，以
  rfauto --help 实测为准。

#### 21.7.2 SDF（Q-X61：core/sdf_parser.py，CLI sdf parse/report 两叶挂账，167 测）

- **格式定位**：SDF（Standard Delay Format，IEEE 1497-2001/OVI 3.0）时序
  标注交换格式——OpenSTA/PrimeTime/Vivado 输出、门级仿真器反标
  （$sdf_annotate）输入；数字后端三件套（SDC 约束/SPEF 寄生/SDF 时序标注）
  收官面。
- **核心语法要点**：①S-expression 文法（括号/引号串/原子三类词元）+栈式
  解析零递归（MAX_NEST_DEPTH=512 深度守卫；括号失配/注释未闭合=
  SdfParseError 带行号）；②三元组 min:typ:max 按 `:` 切分三槽，空槽如实
  None 不猜，单值=三槽同值（IEEE 1497 语义）；③TIMESCALE 档位闭集：乘数
  1/10/100×单位 s/ms/us/ns/ps/fs 共 18 档显式表 TIMESCALE_FACTORS，表外
  fail-closed 抛错（绝不静默猜量纲）；缺省=标准规定 1ns（source=default
  +warning，OpenSTA SdfReader 同口径）；④`\x` 转义字保留反斜杠原文
  （SDF 标识符转义语义：`a\[3\]` 与总线下标 `a[3]` 不同——解析层不解
  转义，名字如实）；⑤`(INSTANCE)`=top-level/`(INSTANCE *)`=通配/层次名
  按 DIVIDER 切分（转义分隔符 `\.` 不切）。
- **解析面**：parse_sexpr（SdfList/SdfAtom 嵌套树）+parse_sdf（头部键闭集
  HEADER_KEYWORDS+CELL 段 DELAY ABSOLUTE/INCREMENT 下 IOPATH/COND/
  INTERCONNECT/PORT/NETDELAY/DEVICE 五类 del_def+TIMINGCHECK 十二类
  SETUP/HOLD/SETUPHOLD/RECOVERY/REMOVAL/RECREM/SKEW/TIMESKEW/FULLSKEW/
  WIDTH/PERIOD/NOCHANGE 按定位元数解析+TIMINGENV/LABEL unsupported 保留
  原文）+parse_sdf_triple+查询三函数 sdf_cell_lookup/sdf_delay_paths
  （from→to 平坦清单+秒值）/sdf_timing_check_summary（分类计数+每类最坏
  值 max of max 槽）。
- **陷阱**：①PATHPULSEPERCENT 值不做时间换算（unit=percent 如实标注）；
  ②COND/CONDELSE 条件表达式只携带不求值（词元级重建原文）；③DIVIDER
  缺省=标准 `.`（OpenSTA 内部缺省 `/` 属其网络约定——跨工具对拍留意
  口径差）；④缺 TIMESCALE 时按标准缺省 1ns+warning——消费端不要把
  "缺省"当"文件已声明"。
- **集成点**：service/sdf_service.py（parse_sdf_file/sdf_report/
  sdf_cell_detail——不存在 cell→ok=False 带可用 cell 清单）；
  cli/domains/sdf.py 独立根挂账（零导入钉随接线移除）；MCP sdf_parse/
  sdf_report 已暴露（Q-X73）。2026-11-08 时点/以 rfauto --help 实测为准。

#### 21.7.3 LEF/DEF（Q-X57：core/lef_def_parser.py，CLI lefdef parse/check 两叶挂账，148 测）

- **格式定位**：LEF（Library Exchange Format）/DEF（Design Exchange
  Format）5.8 语法子集——OpenLane/OpenROAD 数字后端流程的科技库（层/
  via/site/macro 抽象）与版图（组件摆放/引脚/网/走线）交换骨干格式；读取
  PnR 产物做结构分析（单元闭合/网连接度/引脚名对齐）的单源入口。
- **核心语法要点**：①词法：`#` 词首起注释（词中 `#` 属名字如 net#1）；
  `;`/`(`/`)` 恒独立标点（`0.14;`/`(0 0)` 贴身写法容忍），唯一例外=词内
  已开 `(` 由同词 `)` 配平（BUSBITCHARS 总线位名 `a(0)` 保持一词）；②
  语句无显式续行符——跨任意多行直到 `;`；关键字大小写容忍（LAYER/layer
  同义走大写归一）而**名字大小写敏感**（层名/单元名/网名走原文）；③LEF
  数值本身即 µm（*_um 直取无换算）；DEF 坐标是 DBU 整数——*_dbu 落原值、
  *_um=DBU÷UNITS DISTANCE MICRONS（预扫全文取换算因子语句序无关；缺
  UNITS 时 *_um 如实 None 不臆造缺省因子）；④节头声明计数（`COMPONENTS
  3 ;`）与实际条目数对账入 section_counts，不等记 count_mismatch 警告；
  ⑤fail-soft：未知关键字整句跳过记 unknown_statement（ANTENNA*/PROPERTY
  等合法但未建模语句收 other_statements 原文不记警告）+零进展死循环守卫。
- **解析面**：parse_lef（LAYERS/VIA/VIARULE/SITE/MACRO[PIN DIRECTION·USE
  +多 PORT 块 LAYER+RECT/POLYGON+OBS]）+parse_def（DIEAREA/ROW/TRACKS/
  COMPONENTS placed·fixed·unplaced/PINS/NETS 连接+ROUTED 走线段+VIA+
  SPECIALNETS/END DESIGN）+拓扑三函数 def_component_macro_closure
  （COMPONENTS.model ⊆ LEF macros 闭合校验，多份 LEF 合并口径）/
  def_net_connectivity（逐网连接度/悬空网/单连接网/未知组件与顶层 PIN
  引用）/def_pin_lef_alignment（DEF PINS↔LEF macro 引脚名双向缺席+方向
  不一致）——LEF/DEF 无方向语义网表，驱动/负载判定一律不做（宁不报不
  误报）。
- **陷阱**：①DEF PINS 的 LAYER 几何是**相对引脚落点的局部坐标**——原样
  保留不做变换（消费端自行叠加落点）；②走线段 layer=段首声明层，段内经
  via 换层不追踪（via 名与落点坐标如实登记 vias）；③`*` 沿用前点同轴值
  与 NEW 分段是 NETS 走线段两惯语（SPECIALNETS 容忍线宽/SHAPE/STYLE 续接）；
  ④设计文件常见未建模块（REGIONS/BLOCKAGES/FILLS/SCANCHAINS 等）整块跳过
  并登记——结构分析前先看 warnings 面。
- **集成点**：service/lef_def_service.py（parse_lef_file/parse_def_file/
  lef_def_check 信封——MACRO↔COMPONENTS 引用闭合+PIN↔PINS 对齐+NET 连接
  度摘要）；cli/domains/lefdef.py 独立根挂账（并发窗口延后接线——合流
  批量接线清单在册）；MCP lef_def_parse 单工具（LEF+可选 DEF 合并函数
  收单形态，多份 LEF/交叉校验留 CLI，Q-X73）。2026-11-08 时点/以
  rfauto --help 实测为准。

### 21.8 版图与制造面（GDSII/Gerber+Excellon/IPC-356/ODB++）

PCB/IC 制造数据族按流程排列：版图交换（GDSII，Q-X58）→光绘+钻孔
（Gerber RS-274X+Excellon，Q-X59）→裸板电气测试（IPC-D-356/356A，Q-X65）
→制造数据模型（ODB++，Q-X68 在制）——制造三件套=光绘+钻孔+电测
（DEVLOG 二百八十三口径），与 §21.6 DRC/LVS 相邻面构成制造消费链
（Q-X59→Q-X65 pair_check 只读消费是首个跨席消费实例）。

#### 21.8.1 GDSII（Q-X58：core/gdsii_parser.py，CLI gdsii parse/layers 两叶挂账，141 测）

- **格式定位**：版图交换事实标准 GDSII Stream Format（公开规范口径）的
  只读结构化解析——纯 Python 字节级、零第三方依赖（gdstk/gdspy 属大依赖
  不入仓；字节级确定性内核正是本席要点）。
- **核心语法要点**：①记录头=**4 字节**：2B 大端 length（**含头自身**）+
  1B record type+1B data type，负载长=length−4；data type 0x00 无负载/
  0x01 bitarray/0x02 int2/0x03 int4/0x04 real4/0x05 real8 全大端；②
  GDSII 实数（1 符号+7 指数 16 底偏移 64+尾数 real8 56 位/real4 24 位）
  精确解码=int/int 正确舍入除法+整数左移——56/24 位尾数超 double 53 位
  有效位，**禁 float(mant) 先行转换**（丢位）；全零字节特判 0.0；③
  ASCII 记录偶字节对齐尾部 NUL 填充，非 ASCII 字节→U+FFFD 如实显示不猜
  编码；④STRANS bit15=反射（先反射后旋转）、MAG 缺省 1.0/ANGLE 缺省
  0.0；XY 全程 DBU int 原值，DBU→µm 走 dbu_to_um 显式函数（UNITS 双
  real8 按规范语义原值双录 units_raw）。
- **解析面**：parse_gdsii（记录流状态机：HEADER/BGNLIB/LIBNAME/UNITS/
  BGNSTR/STRNAME+SREF/AREF[COLROW+3 锚点]/BOUNDARY/PATH[PATHTYPE/WIDTH]/
  TEXT/BOX；头截断/零 length/负载越界→warning+停流 truncated=True；
  未知记录 warning 跳过；重名结构 warning+桶合并）+拓扑三函数
  gdsii_hierarchy_stats（被引用计数+未定义引用+孤儿/零引用双桶宁多报）/
  gdsii_layer_summary（逐 (layer,datatype) 计数+包围盒）/gdsii_expand_
  bbox（递归展开——平移/反射/旋转仅 0/90/180/270 精确展开零近似，任意角
  或 mag≠1 如实 skip 带 reason；MAX_HIERARCHY_DEPTH=256+循环引用守卫）。
- **陷阱**（DEVLOG 二百七十七）：①"2+2+2"记录头系任务书笔误——公开规范
  与全部开源实现均为 4 字节头（接新实现前先核头长）；②任意角度/mag≠1
  引用不展开（宁 skip 不近似——skipped_refs 带 reason 是契约不是缺陷）；
  ③AREF bbox=锚点端点极值法（格位均匀落段的包围盒只依赖端点）；④首记录
  即不可读→GdsiiParseError 文件级错误，区别于流中截断（truncated=True
  已收面如实保留）。
- **集成点**：service/gdsii_service.py（parse_gdsii_file 信封/
  gdsii_layer_report/gdsii_hierarchy_report）；cli/domains/gdsii.py 独立
  根挂账（cli.main 零导入钉随接线移除）；MCP gdsii_parse 已暴露（Q-X73）。
  2026-11-08 时点/以 rfauto --help 实测为准。

#### 21.8.2 Gerber RS-274X + Excellon（Q-X59：core/gerber_parser.py+core/excellon_parser.py，CLI fab parse/summary 组内已接线，108 测）

- **格式定位**：PCB 制造事实标准双件——Gerber RS-274X 光绘（Ucamco 规范）
  指令级状态机解析（坐标模态/D-code 模态/插值模式/区域模式全跟踪）+
  Excellon 钻孔（CNC-7/Format 2 公开口径）刀具/钻点/槽孔解析。与既有统计
  级读入口 gerber_overview_service（T-Q6"禁写完整解析器"口径）分工不同
  且零 import 关系（单源各自成立，消费面不同层级）。
- **核心语法要点**：①`%FSLAX35Y35*%` FS 定长拆分：坐标词无小数点按
  (整数位,小数位) 拆——`0012345@3:5`=12345×10⁻⁵=0.12345 文件单位
  （Fraction 精确解码浮点累计误差免疫；L/T 零省略只影响补零方向，整数值
  恒为字面量整值）；②aperture：C 圆/R 矩/O 长圆/P 多边形+AM 宏
  （unexpanded 整块登记不做参数代换——宏原语求值属出图器职责）；③绘图：
  G01/02/03 线性/弧（I/J 圆心偏移原值记录不展开弧中间点）+D01 画/D02 移/
  D03 闪光+G36/G37 区域逐环路径（内环挖孔不做布尔运算如实逐环）+LP 极性
  登记不清算；④Excellon：M48 头/INCH·METRIC+LZ·TZ/T 刀具 C 直径/G85
  单行两对槽孔/T0 复位——头部不声明位数，缺省按 KiCad/行业惯例 6 位定标
  （`;FILE_FORMAT=2:5` 类 X2 注释出现时优先+decimals_source 如实回显）。
- **解析面**：parse_gerber（flashes/draws/regions+outline_bbox_mm+
  gerber_layer_summary/gerber_bbox 消费面）+parse_excellon（hits/slots+
  excellon_hit_grid_summary 最近邻孔距统计，n<2 如实 None 不做虚假统计）
  +service/fab_gerber_service.py 四函数全信封构造器（parse×2/summarize/
  pair_check——孔位落板 bbox 越界列表交叉校验，tol_mm 缺省 0.5 可调）。
- **陷阱**（DEVLOG 二百七十九）：①FS 拆分示例勘误（任务书"0012345→
  123.45mm"系笔误——按 Ucamco 规范 3 整数位+5 小数位=0.12345 文件单位；
  123.45mm 的 3:5 坐标词应为 12345000）——内核按规范钉、消费端换算前先
  对 MO 单位；②弧段 endpoint-only bbox 恒声明（I/J 圆心鼓出未展开——
  bbox_mode 键如实标注，宁近似不报错值）；③MO 缺失时 _mm 键如实 None
  （单位不明不猜，#316 多报不冒充同款方向）；④Excellon 6 位缺省定标是
  **声明限制**非规范保证（summary 交叉核对）；M97/M98 文字钻/R
  step-repeat warning 登记不展开；多行槽形态未覆盖（只解 KiCad 惯例单行
  两对 G85）。
- **集成点**：cli/fab_app.py 组内追加 fab parse/summary 两叶——**全集群
  唯一已接线 CLI 面**（fab 组既有 9 叶→11 叶零 main.py 编辑，2026-11-08
  时点）；service/fab_gerber_service.py；MCP gerber_excellon_pair_check
  已暴露（Q-X73）。以 rfauto --help 实测为准。

#### 21.8.3 IPC-D-356/356A（Q-X65：core/ipc356_parser.py，CLI ipc356 report 一叶挂账，104 测）

- **格式定位**：裸板电气测试网表事实标准（Per-Pin Electrical Test Data）
  ——KiCad/Altium 导出、飞针/测试架具消费；记录级结构化解析：头部参数+
  记录状态机+net→pads 测试点拓扑+单点 net 开路嫌疑清单。与 Q-X59 构成
  制造三件套（配对校验入口在服务层 ipc356_fab_pair_check）。
- **核心语法要点**：①头部 `P 2.10`/`P 3.00` 版本行（缺失=解析错误）+
  `C<数字>` 坐标缩放因子（≥4 位数字）+M10/M20 用户名/日期+CM 注释；②
  记录类目六种：317 元件/378 焊盘·V 节点/367 过孔/363 DIP 轴向/362 非测试
  面引脚/357 夹具探针（收 probes 独立清单不冒充板面焊盘）+XT 扩展变体族
  （tag 字段扫描天然列宽不敏感——356 旧式固定列与 356A 扩展列双形态同
  读取器容忍）；③坐标换算 mm=原始整数×100/C 因子（Fraction 精确十进制；
  表驱动已知量钉 C1000000+X0012345→1.2345mm）；C 缺失→warning+_mm 如实
  None；④net 名双形态：356A=记录尾裸词字段；356 旧式=独立 `%` 行
  （%NETNAME 模态段+空 `%` 行清模态）；⑤终止 `9999` 文件尾标记（00000
  兼容）；流尾无标记 truncated=True 不报错。
- **解析面**：parse_ipc356（schema 含 components/pads/vias/probes/nets
  映射/stats/truncated/warnings）+查询三函数 ipc356_net_pads（未知 net
  fail-closed ValueError 带可用名录）/ipc356_component_pins（元件引脚
  视图）/ipc356_single_point_nets（单点 net 清单——开路嫌疑信息桶非判错）。
- **陷阱**（DEVLOG 二百八十三）：①C 因子换算口径为 campaign 钉定未逐条
  对原版规范核验（docstring 声明限制）；②tag 扫描的代价：designator 内嵌
  `X<数字>` 形态（如 AX1B）会被提前截断、net 名内嵌 tag 字母+数字（如
  NET_X2）会被先行消费——真实 356A designator 走旗标/固定列两惯例时无害，
  自造命名前先对 docstring 限制声明；③过孔不入 nets 映射（测试点口径）
  自带 net 字段如实保留；④357 探针面只到坐标/点名级（探针网表关联不
  展开）。
- **集成点**：service/ipc356_service.py（parse_ipc356_file/ipc356_report/
  ipc356_fab_pair_check——只读消费 Q-X59 fab_gerber_service 产物零改动，
  lazy 标注）；cli/domains/ipc356.py 独立根挂账；MCP ipc356_report 已暴露
  （Q-X73）。2026-11-08 时点/以 rfauto --help 实测为准。

#### 21.8.4 ODB++（Q-X68 在制——零预写）

- **在制如实标注**：core/odbpp_parser.py+service/odbpp_service.py+
  cli/domains/odbpp.py 工作树在飞未提交（2026-11-08 时点 git untracked）
  ——测试数/集成状态/陷阱清单以席位交付与主代合流后实测为准，本节不预写
  任何数字。方向（工作树 docstring 调研结论）：ODB++Design 目录形态
  **结构与统计面**（matrix 层清单/step 目录树/netlists 网表/symbols/
  eda 顶层计数/net→pads 库存+悬空 pad/空 net 双清单+matrix↔step 层对齐
  校验）——与既有 adapters/layout_interchange.py import_odbpp（几何语义
  展开）、format_overview_service（存在性探测）三面零函数重叠；集群专审
  Q-X74 同为在制（只读审查报告供合流与终门消费）。

### 21.9 测试与波形面（VCD/STIL——与 IPC-356/CITI 构成测试三面+仪器面）

数字验证/测试面两件：VCD 波形（Q-X63）+STIL 测试向量（Q-X72）——测试
三面=STIL+IPC-356（§21.8.3）+VCD（DEVLOG 二百九十口径），仪器面=CITI
（§21.3）。x/z 值分型（VCD）与 WFC 事件字母表（STIL）同守"结构化保存
不解释物理含义"（铁律 7）。

#### 21.9.1 VCD（Q-X63：core/vcd_parser.py，CLI vcd parse/report 两叶挂账，141 测）

- **格式定位**：数字仿真波形交换事实标准 VCD（Value Change Dump，IEEE
  1364-2005 附录）——iverilog/Verilator/开源仿真器全走此链；声明段状态机
  +时间轴增量值事件流的只读结构化解析。
- **核心语法要点**：①声明段：$date/$version 跨行块；$timescale 表驱动
  （数值 1/10/100×单位 fs..s 档位闭集，非法 fail-closed VcdParseError）；
  $scope 嵌套栈→层次树（scope 路径点分单源）；$var type width id name
  （id=ASCII 33-126 多字符编码；同 id 冲突 warning+**后列覆盖**）；
  $enddefinitions 缺失=致命（文件身份判定面）；②数值段：#时间戳（单调
  不减违例 warning 不中断）；标量 `0!`/向量 `b1010 !`/实数 `r123.456 id`
  三类；③x/z 如实字符串分型（值恒 str 与数值不可比——不做数值化；单
  比特 x 值是标量非向量——向量 x 必 bx 形态，测试钉此区分）；④
  $dumpvars/$dumpall 快照是真数据不丢；$dumpoff..$dumpon 窗口登记（显式
  x 保留、**不合成**未显式写出的 x）；$dumpports 只计数登记不解析。
- **解析面**：parse_vcd（schema=vcd/1.0：header/scopes 树/vars by id/
  events by id[[time,value]]/dump_regions/stats）+查询三函数
  vcd_var_lookup/vcd_signal_profile/vcd_time_windows+vcd_activity_top。
- **陷阱**（DEVLOG 二百八十五）：①id 冲突后列覆盖→被覆盖 var 的层级名
  不可再查（事件按 id 合并如实保留）；②无流式/分块模式（全文读入——大
  波形注意内存）；③转义标识符 \name 形态不特判按原文收；④先于首个时间
  戳的值事件按时间 0 归置+warning；值事件引用未声明 id→warning+事件如实
  保留（events 与 vars 键集可异，消费方自查）。
- **集成点**：service/vcd_service.py（parse_vcd_file/vcd_report/
  vcd_var_detail，utf-8→Latin-1 兜底）；cli/domains/vcd.py 域内自注册
  挂账（main.py 只 re-export 三行待合流）；MCP vcd_parse 已暴露（Q-X73）。
  2026-11-08 时点/以 rfauto --help 实测为准。

#### 21.9.2 STIL（Q-X72：core/stil_parser.py，CLI stil parse/report 两叶挂账，134 测）

- **格式定位**：IEEE 1450 STIL（Standard Test Interface Language）数字
  测试向量交换标准——ATPG 输出、ATE 消费；块树状态机+两遍语义（先声明面
  后 Pattern 面）的只读结构化解析。
- **核心语法要点**：①块结构：块头关键字+`{...}` brace 平衡计数
  （MAX_BLOCK_DEPTH=100 深度守卫；失衡致命带开括号行号）；`/* */` 与
  `//` 注释双形态+`'...'`/`"..."` 字符串单 token；②Signals：`name =
  in|out|inout ;`+WFC 定义 `WFC_0 = '0' ;`（引号/裸字双形态，文件全局
  字符集定义序去重）；SignalGroups 四形态（引号/无引号/级联 `'a' + 'b'`/
  选择器只取末个 `:` 之后成员段）；③Timing：WaveformTable{Period+
  Waveforms 逐组逐 WFC 事件 token 序列化保存——**不解释事件字母物理含义**
  （铁律 7）}；④Pattern：`W <wft>`+`V { 组=值串; }` 向量行（长度≠组员数
  fail-soft 跳行）+`Loop n {` 倍数计数不物化（Loop 1000000 实测内存恒定）
  +Shift/SubStroke 计数+Ann 收编；⑤两遍语义：Pattern 先于 SignalGroups
  的文件同样可解析。
- **解析面**：parse_stil（schema=stil/1.0：signals/groups/timing{wft:
  {period,waveforms{组:{wfc:[事件 token]}}}}/patterns{burst:{patterns}}/
  stats）+查询三函数 stil_pattern_vectors/stil_vector_at（逐字符 WFC 事件
  联查缺映射如实 None）/stil_coverage_stats。
- **陷阱**（DEVLOG 二百九十）：①Procedures/Import/PatternExec（BSDL/
  过程引用）只登记名目不展开；②WFC 定义文件全局字符集回填不逐信号区分；
  ③n_loop=倍数累计和+嵌套加和**不乘积**（消费端自行换算）；④Pattern
  重名同 burst 后列覆盖、跨 burst 双录。
- **集成点**：service/stil_service.py（parse_stil_file/stil_report/
  stil_pattern_detail——未命中带可用 pattern 名录上限 30+总数注记+
  Latin-1 兜底）；cli/domains/stil.py 独立根挂账；MCP 面暂无 stil 工具
  （Q-X73 十域清单外，2026-11-08 时点）。

### 21.10 互连与封装面：Touchstone（Q-X64——#248/#287/#309 三坑单源化专节）

- **格式定位**：Touchstone .sNp 是 RF/互连 S 参数数据交换事实标准（IBIS
  Open Forum v1.0/v2.0 规范）。本席要点=把仓内三次 ad-hoc 修复**单源化**
  为确定性内核：rank 推断/频轴对齐/多模形状判定从此单一出处；既有消费者
  （adapters/hfss_adapter.infer_touchstone_port_count 等）迁移归后续席
  （本席零改既有消费方）。
- **核心语法要点**：①option line `# <freq_unit> <param(S/Y/Z/H/G)>
  <format(RI/MA/DB)> R <n>`；v2.0 关键字块（[Number of Ports]/[Two-Port
  Data Order]/[Matrix Format]/[Reference]/[Network Data]）；②rank 三规则
  按序嗅探：文件名 .sNp（N≤9 可信）→首行值数（v1 候选集消歧：9 值∈
  {2,4,5,…}；v2=2n²+1 直接解）→块结构（v1 块行数=n·ceil(n/4) 直接定 n；
  v2 token 流分组交叉验证）——②③内容共识 vs ①文件名冲突→**内容为准**
  +disagreement 登记（#248 口径：扩展名由实际端口数决定）；②③冲突→
  n_ports=None+disagreements 宁 UNKNOWN 不猜；③三格式解码 DB/MA/RI 表
  驱动（DB=20log10 换算已知量钉）；freqs_hz 单位表驱动；④2 端口 v1
  legacy 列序 S11 S21 S12 S22（与矩阵行列序相反的历史约定）；N≥3 端口每
  频率 n·ceil(n/4) 行仅首行带频率、行主序。
- **解析面**：sniff_touchstone（三规则+disagreement 清单）+parse_touchstone
  （s_matrix/freqs_hz/reference+detect_mode_data_shape）+align_freq_axis
  （同栅 rtol 1e-9 直接比对/异栅 argmin 真最近邻+端点 ulp 容差）+
  matrix_health（无源性 |max eig|≤1+ε 统计不做硬门）+to_skrf_network 桥
  （与 skrf.Network 直读 v1 1/2/3 端口+v2 rows_12_21 **全 parity 逐位
  对拍通过**）。
- **三坑回放（仓内真实痛点，接消费链必读）**：①#248——skrf 只按 .sNp
  扩展名推断 rank（1 端口数据写成 .s2p 即报 reshape 错）；首行值数
  (V−1)//2 对 2 端口 9 值文件误判 4 端口；HFSS 导出按插件契约 n_ports
  命名是错源（本内核规则③块结构消歧）；②#287——dB 形式写出/读回频率带
  ~1e-7 Hz 浮点噪声，与显式频扫端点差一个 ulp 即触发 scipy interp1d
  bounds ValueError（align_freq_axis：同栅 rtol 换频轴/异栅 bounds_error=
  False 端点微量外推——**禁 searchsorted 越位一格**，#294 同款）；③
  #309——HfssAdapter.export_touchstone 按端口边界数命名：2 个 2 模波端口
  的 4×4 模态数据被写成 .s2p，skrf 按扩展名推 rank 抛 IndexError（多模
  端口按 Σ模数改名 .s4p；detect_mode_data_shape=Σ模数 vs 端口数互证冲突
  建议输出）。
- **陷阱**（DEVLOG 二百八十四"已知限制"）：①noise 段 5 值行登记不解析
  语义（Γopt/Rn 不解释）；②v2.0 [Matrix Format] 仅 Full；③2 端口缺
  [Two-Port Data Order] 按规范默认 rows_12_21+警告（skrf 同场景按 legacy
  列序——口径差已入 warnings）；④[Reference] 不支持跨行延续；v1.0 规则
  ②单独不可采信宁 UNKNOWN。
- **集成点**：service/touchstone_service.py（touchstone_info 查询面冲突=
  答案 ok=True 带全量证据/parse_touchstone_file rank 冲突→ok=False 信封
  s_matrix [re,im] JSON 化 cap 4096 截断态如实/touchstone_report）；
  cli/domains/touchstone.py 独立根挂账（显式 callback 防 typer 单命令
  app flatten——typer 形态经验）；MCP touchstone_info 已暴露（Q-X73）。
  2026-11-08 时点/以 rfauto --help 实测为准。
- **席位与测数**：Q-X64 97 测（两轮不同 randomly 种子均绿——DEVLOG 二百八十四
  原文口径；主代独立复验 97 复现）。

### 21.11 模拟生态面：SKILL/OCEAN 语言解析（Q-X62——与 Q-X32 生成器对偶）

- **格式定位**：SKILL（Cadence Virtuoso 的 Lisp 方言）与 OCEAN（SKILL
  超集+仿真命令面：analysis/sweep/ocnXxx/asi/sim/netlist 前缀家族）的
  只读结构化解析——脚本静态分析/API 调用清单提取/defun 盘点/全局赋值面
  盘点；**永不执行**被解析代码（零求值副作用）。
- **与 Q-X32 的对偶关系**：core/skill_template_engine.py（Q-X32，§21.6）
  是**生成方向**——EDAS 自动化脚本的确定性出口（Jinja2 形态微实现+5 电路
  设计模板 byte-identical）；本席是**解析方向**——既有 SKILL 语料的
  确定性入口。两模块零 import 关系（读写两向互不依赖），合起来构成
  Virtuoso 生态双面；注意 CLI 顶层 `skill` 域已被 Q-X32 模板生成占用且
  已接线——解析域接线名必须另取（见集成点）。
- **核心语法要点**：①S-expression 词法+栈式解析零递归（MAX_NEST_DEPTH=
  512）；`;` 行注释+`/* */` 块注释；数字 int 优先（`1+`/`1-` 函数名符号
  同字符集自然覆盖）；②**f( 调用糖折叠**（SKILL 语言读取器口径）：符号
  后零字符间隔紧跟 `(` 时折叠为紧随表头部——`defun( f (x) …)` ≡
  `(defun f (x) …)`；冒烟实证：无此糖则真实 Cadence 语料 defun 盘点全空
  =解析器对真实语料失灵；符号与 `(` 间有空白则两独立形态；③前缀糖
  `'x`/`` `x ``/`,x`/`,@x`（quote/quasiquote/unquote/unquote-splicing）→
  Quote 包装不展开不求值（糖绑定下一个完整节点；悬挂糖=致命）；向量
  `[...]`→LispVector 与表类型区分；`|...|` 转义符号名单行逐字保留；④
  `&` 字符集扩展（&optional/&rest/&key defun 必需——任务书字母表最小
  超集，偏差项如实记录）；词法闭集外字符致命（异名走 `|...|` 形态）。
- **解析面**：parse_skill（Symbol/LispList/LispVector/Quote/原生值节点树）
  +结构提取四函数 skill_definitions（define 双形态+args 原文含 & 标记+
  arity）/skill_top_level_forms（闭集分类+逐头符号频次）/skill_api_calls
  （ocean/virtuoso/generic 前缀桶）/skill_globals（作用域深度）+
  skill_call_graph（静态调用边：符号名匹配同名 define，递归自环如实）+
  skill_literal_eval（数字算术/quote/list/字符串 concat 可求值，非字面量
  fail-closed 不猜）。引号数据整树视为数据（Quote 子树不计定义/赋值/
  调用）；绑定形态如实剪除（lambda 参数表/let 绑定变量位/setf 目标位等
  不计调用）。
- **陷阱**（DEVLOG 二百八十六"已知限制"）：①call graph 无作用域分析——
  调用归属最近包围定义；②中缀表达式首操作数计 generic 调用（前缀/中缀
  无句法界标）；③let 绑定表按扁平 var/val 剪除；④数组下标糖 x[1] 不
  折叠（向量字面量独立形态）；skill_literal_eval 除法恒真除。
- **集成点**：service/skill_service.py 加性节追加 +155/−0（parse_skill_
  file/skill_report/skill_call_graph 三信封——既有 935 行 Q-W6-1 card→
  skill 产线逐字节未动）；cli/domains/skill_parse.py 独立根挂账+**撞名
  自查**：接线名必须 `skill_parse`（顶层 skill 已占，双注册打红
  zero-shadow 钉）；MCP 面暂无 skill 解析工具（Q-X69 建议清单已备、
  Q-X73 十域未收——skill 落盘面不上 MCP 是既定取舍）。2026-11-08 时点/
  以 rfauto --help 实测为准。
- **席位与测数**：Q-X62 151 测（重派席——前任初写期静默死亡零足迹，本席从零
  重建；skill 家族既有测试+定向门 260 passed 零回归——DEVLOG 二百八十六原文
  口径）。

---

## 22. AI-driven RF 设计方法论吸收（aurora_r R-06 知识落点席，2026-11-10）

> 性质与口径：本章为纯知识落点（零代码改动）。四篇微信文章经 web_reader
> 全文实读（访问日期 2026-11-10，URL 见章尾出处清单）；virtuoso-bridge
> 与作者生态吸收以 runs/aurora_q/qx40_vbridge/{DIGEST.md,AUTHOR_SURVEY.md}
> （Q-X40 席+主代调研席，钉 SHA 实读口径）为接地底稿。**思想级转述、不搬
> 原文段落**；仓内统计数字（测试数/CLI 数/MCP 数等）一律不写具体值——
> 它们由数字链门管理，本章只写对位关系与仓内证据路径（#97 口径，
> 2026-11-10 本席 grep/ls 实测）。

### 22.1 L0–L5 六级成熟度与 rfauto 对位自评

**六级定义（一行级转述）**——出处：Keysight 官方博客《AI-Driven RF
Design: From Scripts to Autonomous Agents》（2026-09-09）的微信转述版
（URL 见章尾清单）：

| 级 | 名称 | 一行定义 |
|---|---|---|
| L0 | 手工 | 工程师在 EDA 图形界面点选/扫参/判读，全凭个人经验与直觉 |
| L1 | 自动化 | 重复劳动固化成脚本（批量仿真、批量优化），人不碰重复操作 |
| L2 | 副驾驶与代理模型 | AI 帮查文档/配分析/生成脚本；代理模型用监督学习逼近物理——AI 开始帮忙但仍需人带 |
| L3 | 领域智能体 | 自然语言下达目标与约束，智能体自主编排"跑求解器→看结果→调参数"——工程师从操作员变策略导演 |
| L4 | 智能体之智能体 | 中央编排智能体把任务派给领域智能体（电路/版图/EM/热），大部分流程自主执行，关键验证节点仍需人工介入 |
| L5 | 组织级智能 | 全自动自我改进的智能体组织覆盖规格→验证全生命周期，沉淀机构级知识，人只做高层治理（愿景） |

原文纪律（终句级结论）：**先在 L2 证明可靠性，再把自主权交给 L4 以上的
智能体**——连代理模型的误差边界都没摸清，就不该让它自主定版。

**rfauto 各面实测对号表**（每行给仓内证据路径，不写数字）：

| rfauto 面 | 对位 | 证据路径（2026-11-10 grep/ls 实测） |
|---|---|---|
| recipes 声明式配方 + CLI 命令域 | L1（自动化） | recipes/*.yaml；src/rfauto/cli/domains/ |
| capture 半边（把人的 GUI 会话/散乱实测数据结构化捕获） | **缺→自评 L1.5 登记** | 缺口处方已挂账：runs/aurora_r/PLAN.md Wave3 R-23"会话→配方录制" |
| GP 代理内核 + 数据工厂/lake + surrogate_loop | L2 | src/rfauto/core/gp_tensor_kernel.py；src/rfauto/service/dataset_service/、lake_service/、dataset_quality_service.py；src/rfauto/optimization/（model_registry/mo_bo/eipu 为 surrogate_loop 消费面） |
| autotune 闭环 + em_bench 判据 | L3 雏形 | src/rfauto/service/autotune_service.py（critique 为确定性 service 函数）；src/rfauto/service/em_bench_service.py（闭环编排面为内部档，不在公开树） |
| 战役/席位编排 + agent 工具循环家族 | L4 初级 | src/rfauto/service/campaign_executor.py、campaign_queue_daemon.py、multi_agent_service.py、agent_runtime.py（AgentRuntime 薄协议+RuntimeRegistry）、agent_sandbox.py（agent 写面沙箱隔离） |
| L5 | 不设目标，仅作愿景与风险参照 | 五坎（数据稀缺/强非线性/可解释性/代理漂移/集成难题）对本仓同样成立，处置见 22.2 |

对位结论：rfauto 分层架构（cli→service→…）天然落在"编排"半边的
L2→L4 连续带上；最薄的半边是 capture（L1.5）。对照 capture–accelerate–
orchestrate 框架（出处同文：把资深工程师"没被记录下来的鼠标点击"数字化
为脚本/可执行流程，是敢信任自主智能体的前提），本仓的知识捕获管道
（会话→配方、散乱实测→结构化数据）是下一个补强方向（R-23 挂账）。

### 22.2 代理模型方法论

**五步建法**（转述 Keysight 文；括号内为 rfauto 对位）：①定义与被测
器件相关的参数空间（recipes 的 design_params/physics_roles 面）；②DOE
在参数空间里挑稀疏网格点（数据工厂采集面，service/dataset_service/）；
③只对网格点跑全波真值（HFSS/openEMS/ADS 适配器，规则 0b 服务器优先）；
④拿真值训练代理模型（GP=core/gp_tensor_kernel.py；神经代理面挂账
R-05）；⑤在已仿真点之间做平滑插值（optimization/ 代理消费面）。

**验收四件套**（Keysight 文"但是"节+Alpha-RF 实证汇流；R-01/R-05
判据面对位）：

1. **训练包络声明**：代理模型被训练数据分布严格约束、不能安全外推——
   模型产物必须随包络（参数范围/样本来源）声明落盘；优化器出包络即
   降级为"仅探索参考"，不得采信为判读依据。
2. **OOD 探针**：在包络边缘与包络外构造探针点验证退化行为——Alpha-RF
   把耦合开口拉到训练范围外做成全通波导、四种长度预测仍贴合，是教科书
   级的 OOD 探针设计；注意其结论只对"几何相近"的外推有效，换工艺/
   频段/叠层不保。
3. **真值抽查**：交付级设计必须回全波/实测复核——Alpha-RF 六组人机
   对比中两组预测奖励漂亮而真值带宽偏出，代理误差一路传导到最终设计
   （原文自证），抽查门不可省。
4. **无源性/物理约束硬校验**：Keysight 文点名 EM 代理模型必须满足
   无源性（passivity），DRC/LVS 类工艺约束必须硬编码进流水线、不交给
   模型自觉——与铁律 7（数值只在确定性内核）、规则 1b（先验模型再
   校准）同构。

**Alpha-RF 奖励函数设计要点**（出处=Alpha-RF 拆解文 §2.2/附录 C 转述；
UC Davis×Keysight，arXiv:2603.00104）：

- **权重分档**：五项指标按工程重要性分档加权——中心频率与相对带宽各
  0.3（高档）、峰值插损 0.2（中档）、左右阻带抑制各 0.1（低档）；权重
  取舍全是射频判断，不是模型自己长出来的。
- **幂次重罚**：越界误差按 5 次/3 次幂重罚——把"差点达标"与"达标"
  的分差拉开，防止奖励地形在指标边缘过于平坦。
- **超标记满分**：指标一旦优于要求，该项直接记满——留口子鼓励超人
  设计，不卡"刚好及格"。
- rfauto 对位：autotune/em_bench 的 cost 设计与这三条同构（罚函数
  形态/达标饱和/权重分级）；改造 cost 或新增判据面时按此三角自查。
  另一条实现细节可参考：离散动作维度（阶数）用可微分类头+直通估计器
  保梯度通路，混合离散/连续动作空间不要用"输出实数再取整"。

**代理误差传导→全波兜底纪律**（与规则 1b/铁律 7 互链）：Keysight 文
的风险缓解同向——AI 只做快速预优化与初始化、把设计空间大幅收窄，最终
验证与签核一律回传统求解器；rfauto 现行纪律链（HFSS=对齐基准、闭式/
解析/实测三方裁判、代理只当加快器不当裁判）与其完全一致，本节将其
升级为明文：**代理模型参与判读的任何链路，必须存在全波/闭式/实测
兜底门，且兜底门的判定优先级高于代理预测**。

**数据账意识**：Alpha-RF 的门槛不是网络结构，是 100k 版图+全波真值的
数据集——按其单次全波 4 min 折算约 278 天单机（原文口径）。折算到
本仓：lab_server 8 路并行（AGENTS 规则 0b；runs/aurora_r/PLAN.md R-20
数据采集战役）把同类数据工厂战役的墙钟压缩约两个数量级——"凡可借
服务器加速的环节一律上服务器"正是数据账意识的执行形态；立项顺序=
先算数据的账，再算算法的账。

### 22.3 闭环基建论

**核心论点**（出处=张托肯《模拟设计缺的不是新 AI，缺的是新基建》，思想
转述）：模拟/RF 设计缺的不是新 AI，缺的是新基建——让 AI 调优化器/改
网表/跑仿真只证明局部流程可跑通，不等于进入真实工程；真实设计的判断
依赖一整套上下文（原理图/testbench/文件结构/标注/文档）作为反馈，AI
拿不到反馈就进不了闭环，进不了闭环就只能停留在外围。按任务三分类看：
标准明确+反馈充足（做题/编程）AI 已极强；标准模糊+反馈可得（写作）
同样好；**标准明确但拿不到反馈——模拟电路设计恰属此类：不是没有 spec，
是反馈断了**。

**闭环三件套**（原文尾节论点，思想转述）：**监督+反馈+验证**——监督=
人定边界与门；反馈=环境接口把验证结果与工程上下文持续回收给系统；
验证=确定性判据裁定。开环系统永远靠人盯着，闭环系统才开始自我进化
（原文句意的思想转述）。

**rfauto 对位**：三件套的仓内形态=autotune_service 的确定性 critique
（验证件，铁律 7）+agent_sandbox 三层 Gate+席位三禁（监督件；
不 commit/不写账本/不跑全量）——闭环编排层为内部档（不在公开树）。

**virtuoso-bridge 实证接地**（出处=runs/aurora_q/qx40_vbridge/DIGEST.md
§0–§1/§5，钉 SHA e2a69fca，MIT 判定三源一致）：Agent↔Virtuoso/Spectre
桥=经鉴权（HMAC-SHA256 帧签名+令牌永不过线）的 TCP→SSH 隧道→守护
进程→CIW evalstring 执行链+独立 Spectre 网表仿真通道；不确定结局
状态机（RequestNotStarted/ExecutionUncertain 毒化车道+探针重同步+
幂等回执）是"请求回执/不确定不重放"的参考实现。原文三块更新（maestro
读设回读等读写接口/多服务器多账号/弹窗与执行稳定性）与 DIGEST §0–§1
逐项对上。rfauto 侧接地对照（DIGEST §5 共 20 项，三态=已在/部分在/
缺）：**缺与半缺项**（MCP ToolAnnotations 全覆盖、resources+prompts、
逐工具限流、通道层请求回执/幂等、GUI 弹窗三态巡检、Spectre 交接件）
已挂账 aurora_r Wave2 VB 批（R-10..R-18，runs/aurora_r/PLAN.md）——
本席只登记对位，不做实现。下游实证：TACS-RF（arXiv:2610.31882）§II-A
载明 agent 经 virtuoso-bridge 控制 Virtuoso——"新基建论"已进真实
论文工作流，非 PPT。

**PINO 等效源框架一段摘要**（出处=PINN→PINO 文，适用域与局限如实
转录）：传统 PINN 解电磁"一个几何一个网络"不泛化；该框架把散射等效
原理搬进网络——输入=金属边界采样点坐标+入射波信息，输出=边界等效源
强度，用"金属表面切向电场为零"构造损失（无求解器标签，物理约束替代
数据监督）；等效源的全局耦合用多头注意力学（替代矩量法满阵求逆）；
几何用 RBF 参数化的水平集变成可微变量（可顺梯度做逆设计）。**泛化
证明走逆设计不走留出集误差**（随机生成的结构不唯一，留出集误差不可
靠）：单站 RCS 缩减/多角度单双站散射抑制/宽带平顶波束赋形三任务，
CST 全波复核吻合。局限（作者自认，如实转录）：只覆盖一维准平面 PEC、
理想导体、自由空间格林函数——受约束几何子空间内的泛化，离任意超
表面设计尚远；正向精度靠逆设计结果间接体现，无与矩量法/CST 的正面
对标精度与耗时曲线。对 rfauto 的启示：①泛化声明可用"目标功能可
达成"（逆设计+全波复核）与 OOD 探针双证，比单看留出集误差诚实；
②局限清单前置的写法=本仓诚实边界纪律的同款范式。

### 22.4 Token Zhang 生态与 ADC 蓝图

**作者生态**（出处=runs/aurora_q/qx40_vbridge/AUTHOR_SURVEY.md）：GitHub
Arcadia-1（署名 Token Zhang/微信笔名张托肯，三种署名形态并存如实
记录），AMS 侧"LLM×电路"完整栈（分析→仿真→评测→理解→知识→桥接
→技能）；与 rfauto 对位=AMS 器件级（Spectre/Virtuoso 生态）vs RF/EM
器件级（HFSS/openEMS/ADS 生态）——几乎零重叠、强互补；方法学签名
（fail-closed/显式认证边界/判据不凑绿/双层验证）与铁律 7/#122 同源。

**15 仓一行表（许可三档；stars/时点值以 AUTHOR_SURVEY §1 原表为准，
此处不复制防漂移）**：

| 许可档 | 仓 | 吸收级别 |
|---|---|---|
| MIT（代码级可参考） | virtuoso-bridge-lite / ADCToolbox / netlist-crawler / EVAS / circuits-and-systems-classroom | 代码级或思想级（Rust/TS 栈思想级） |
| Apache-2.0 软件面+内容面红线 | razavi-bench（基准材料禁再分发）/ analog-design-bench（内容 CC BY-NC 4.0）/ analog-design-bench-code-a-chip（本批唯一干净基准仓） | 思想级，内容面禁收编 |
| 无 LICENSE（默认版权保留，零文件搬运） | analog-agents / veriloga-skills / gmoverid-skill / awesome-ams-skills / behavioral-veriloga-eval / ADC-12b-100M / circuit-bench-toolchains | 一律思想级 |

**红线复述**（AUTHOR_SURVEY §3，硬约束）：①razavi-bench 题面/金标/
rubric/图/分数表**禁收编**进 em_bench/knowledge/数据工厂（其 LICENSE
§3 自定义双边界明文禁再分发）；②analog-design-bench 内容 CC BY-NC 4.0
禁并入 rfauto 基准/发布面；③无 LICENSE 7 仓零文件搬运；④MIT 徽章
陷阱：README 徽章字样≠许可成立，以 LICENSE 文件签名为准（速查 ㉖
口径实锤）；⑤PTM 模型文件（ASU 版权+学术引用义务）不进发布面。

**ADCToolbox 模块拓扑蓝图**（MIT 代码级；AUTHOR_SURVEY AX-9 远期
参照）：spectrum（频域测量）/aout（模拟输出）/dout（数字输出）/
calibration（校准）/timeinterleave（交织失配）五模块划分——特征化
与校准分离、按物理主题切模块；分发形态=包内捆绑 router 型 agent
skill+安装 CLI。对 rfauto 有源族（ADC/PLL/放大器，仓内现为空白面）
远期立项的参照：模块拓扑抄结构不抄代码，skill 分发形态与 card_to_skill
产线同构。

**吸收提案挂账**：立即可做 6 项（AX-1..6）+中期 3 项（AX-7 gm/ID
查表内核/AX-8 vaBench 四任务族/AX-9 ADC 蓝图）——其中 AX-1→R-01、
AX-2/AX-6→R-02、AX-3/AX-4→R-03、AX-5→R-04（aurora_r Wave1 排席）、
AX-7→R-19、AX-8→R-08（Wave1/Wave3，runs/aurora_r/PLAN.md）；台账
见 AUTHOR_SURVEY §2，本席不重复展开。

**出处落版清单**（访问日期均为 2026-11-10，本席 web_reader 全文实读；
思想级转述，技术数字以原文为准）：

1. Keysight 博客微信转述版——六级成熟度/capture-accelerate-orchestrate/
   代理模型五步/无源性硬校验（原文=Keysight 官方博客 2026-09-09
   《AI-Driven RF Design: From Scripts to Autonomous Agents》）：
   https://mp.weixin.qq.com/s/wOfPnB3UF2qONV0gPiOcPA
2. 张托肯《模拟设计缺的不是新 AI，缺的是新基建》：
   https://mp.weixin.qq.com/s/wgHy4K9-tWm6qjIpUhma7A
3. Alpha-RF 拆解文（UC Davis×Keysight，arXiv:2603.00104）：
   https://mp.weixin.qq.com/s/eECahVLaD_cxWcprwkpoVg
4. 从 PINN 到 PINO：电磁散射问题的几何泛化求解框架：
   https://mp.weixin.qq.com/s/f1413kyuxHe-jKHKPzMosQ
5. 仓内接地：runs/aurora_q/qx40_vbridge/DIGEST.md（Q-X40，2026-11-07）、
   runs/aurora_q/qx40_vbridge/AUTHOR_SURVEY.md（2026-11-09）、
   runs/aurora_r/PLAN.md（Wave1–4 挂账台账）。

**诚实边界**：①四篇均为微信转述/拆解版，论文级数字（Alpha-RF 的
MAE/耗时、PINO 框架细节）以 arXiv 原文为准，本席未核对原文（PINN→
PINO 文未给出处论文号）；②22.1 对位表是"证据路径存在+模块语义对号"
的自评，不是能力审计——各面成熟度以对应席位交付与测试面为准；③
AUTHOR_SURVEY 的 stars/时点值为 2026-11-09 API 值，本席未重测。

### 22.5 TACS-RF 报道吸收：LLM 操盘四件套九步设计 sub-THz 发射机（第五篇，R-23）

> 性质与口径：纯知识落点（零代码改动），本章第五篇——章首"四篇"为 R-06
> 落版时点口径，本节出处单列节尾续号，只追加、不改写既有清单。报道=射频
> 学堂微信文章（web_reader 全文实读，访问 2026-11-10）；同篇论文 TACS-RF
> （arXiv:2610.31882）abs 页与 HTML 全文本席同日实读核对——Q-X40 DIGEST
> 已实读 §II-A/§II-B，本席扩读 §I–§V 与表 I。思想级转述、不搬原文段落；
> 仓内统计数字一律不写（#97，数字链门管理），只写对位关系与证据路径。

**论文档案**：Tristan Liang、Aravind Nagulu（Northeastern University ECE，
HTML 首页署名）；2026-10-22 提交 arXiv（v1，cs.AI），Comments 载已录用
2027 IEEE RWW/SiRF。LLM 编码智能体=Claude Opus 4.8（§II 原文为 Enterprise
版），经脚本、命令行与机器可读仿真输出直驱四件套，**零人工 GUI 介入**。
验证载体=90 nm SiGe BiCMOS 工艺 240–251 GHz 亚太赫兹发射机：60 GHz
push-push Colpitts VCO 取二次谐波→多级差分 cascode 驱动→push-push 倍频
→片上差分领结天线，连同全部级间匹配由 agent 半自主设计。**半自主**的
分工：人供资料与参数化晶体管版图库、核验结果、拼顶层版图并终验；其余
由 agent 承担。

**①四件套分工表**（论文 §II-A/B/C 与 §III 原文转述；rfauto 对位列给
证据路径，2026-11-10 本席 ls/grep 实测）：

| 工具 | 流程角色 | 论文载明的具体活 | rfauto 对位 |
|---|---|---|---|
| Cadence Virtuoso/Spectre | 原理图·版图·电路仿真 | 经 virtuoso-bridge-lite 生成原理图/符号、查连通、建仿真视图、起 Spectre、画参数化版图；日志/工作点/波形量测以机器可读形式回传。双 Spectre 流：脚本网表流（并行快扫尺寸/偏置/无源值，供迭代优化）+ cellview/Maestro 流（原理图/testbench/配置视图，供人工核验） | 本机无 Cadence（Q-X40 VB-9 口径）；spectre 风格网表解析 service/spice_netlist_service.py；EM→IC 交接件 service/spectre_nport_service.py（VB-9/R-18，真 Spectre 运行 UNVERIFIED-LOCAL 常驻）；桥层吸收见 22.3 |
| Cadence EMX | 片上无源 EM 提取 | 顶两层金属参数化单圈八角变压器/电感；多端口 S 参数回 Virtuoso 做电路级评估；几何按整链发射机性能迭代更新 | EMX 不在本仓工具链；同几何族确定性模板位=§19.1 octagonal_spiral（openEMS 渲染模板，离线审计已过、真机冒烟未发射、HFSS=对齐基准——§19 节首口径；GaAs IPD 工艺，与论文 SiGe 后道叠层不同：几何族对位、工艺不对位）；sNp 互操作=adapters/touchstone_interop.py |
| Ansys HFSS/PyAEDT | 天线 3D EM | agent 现写 PyAEDT 脚本，按晶圆厂后道叠层与材料建领结天线，**自定**端口/辐射边界/网格/扫频，导出匹配/增益/方向性（§II-B、§III-D 步 9） | **同工具正对位**：adapters/hfss_session.py（PyAEDT 会话）+adapters/hfss_adapter.py；端口/边界/网格走确定性模板+健康门+HFSS 对齐基准纪律（§0 方法学基线）——见④ |
| Cadence Calibre | 物理验证+寄生提取 | 命令行+脚本化 runset 跑 DRC/LVS/PEX；提 RCC（R/C/耦合 C）寄生并导入 RCC 视图；对比原理图级与 RCC 提取级的增益/调谐范围/Pout 以改级间匹配 | Calibre 不在本仓工具链；只读相邻面=寄生交换格式 core/spef_parser.py、版图 core/gdsii_parser.py、网表级 LVS 拓扑对照 service/lvs_compare_service.py——解析/对照面，不执行签核 |

**②九步四阶段流程——登记为 em_bench 端到端任务族参照蓝本**（挂账
AX-8 扩展方向，**不实现只落版**）。步号区间与阶段名取论文 §III-A..D
小节标题；阶段内逐步拆分按段落顺序推定（Fig. 2 图内逐步标注未经多模态
实读，见诚实边界④）：

| 阶段 | 步 | 内容（转述） | 人/agent 分工 |
|---|---|---|---|
| 一 技术与参考设计准备 | 1 | 读 90 nm SiGe PDK 文档与选定前人 sub-THz 发射机文献，归纳可用器件/无源模型、偏置与安全工作区（SOA）界限、预期管子性能、代表拓扑 | 人供资料；agent 归纳 |
| 二 原理图级电路与匹配 | 2–4 | 扫偏置表征不同并联倍数的 SiGe NPN（看 Gmax 与 fT/fmax）→VCO/缓冲/PA/倍频器在独立 testbench 各自定尺寸与偏置→驱动级数+器件尺寸+偏置+匹配参数协同优化（级间网络先用参数化集总模型：两电感、品质因数、耦合系数 k）；结论=两级驱动够用，第三级只留增益裕量吸收版图后损耗与级间失谐 | agent 主导 |
| 三 版图与 EM 感知优化 | 5–7 | 人备参数化晶体管版图库；agent 选版图跑 Calibre LVS+RCC 提取、替换原理图理想管；并行把级间变压器用顶两层金属参数化、EMX 仿真、多端口 S 参数导入 Virtuoso 替换理想匹配；迭代到整链重居中 240 GHz 带并按 Pout 打磨。闭环=RCC 提取→无源几何生成→EM 仿真→电路评估→电路微调，无源件按**对整链的影响**优化而非孤立无源指标 | 人备版图库；agent 跑闭环 |
| 四 顶层集成与验证 | 8–9 | 步 8：提取态整链扫 VCO 调谐电压得 240–251 GHz，优化大信号匹配与功率传输，并在全调谐范围逐管把瞬态端电压对 PDK SOA 界限逐项比对；步 9：agent 在 HFSS 按晶圆厂后道叠层独立设计片上领结天线（匹配/增益/方向性/方向图）。顶层拼版与终验由人完成 | agent 验证+天线；人拼版终验 |

**蓝本化要点**（em_bench 端到端任务族候选形态，**未实现**；立项时须过
铁律 7、规则 1c 与 R-01 准入门）：

1. **阶段门控任务**：一个端到端任务=四阶段检查点串联，各阶段自带判据，
   首个失败检查点即停（与 PANDA"Stop at the first failing checkpoint"
   同思想，runs/aurora_r/p4_survey/RAW_P4_A.md 目标 1）。现役端到端族
   （service/em_bench_analog_service.py 的 va_end_to_end：spec→va→tb
   模拟侧全链）是同形态的模拟侧先例，RF 侧扩展挂账。
2. **两级保真路由**：阶段二"参数化集总模型先行"→阶段三"EM 提取件替换"
   =快引擎查→金标晋升两级验证（AX-8 原台账口径）；RF 侧天然对位闭式/
   fake→openEMS/HFSS 多保真链。
3. **系统级判据**：无源件 cost 以整链指标（Pout/调谐范围/相噪）计，不以
   孤立 S 参数指标计——autotune/em_bench cost 设计的系统级扩展位（与
   22.2 奖励函数三角同列自查）。
4. **硬约束全扫门**：SOA 逐管×全调谐范围扫描=确定性判据，不交模型自觉
   （22.2 验收四件套第 4 条同构）。
5. **交接一致性门**：EM 步→电路步之间的 sNp 交接须过端口数/节点一致性
   校验——VB-9 交接件已备（service/spectre_nport_service.py）。
6. **人工步显式声明**：人供版图库/人拼顶层/人终验三处须在任务 schema
   中显式标为人工持有步（agent 范围外、不计分），对应 22.1 的 L4"关键
   验证节点仍需人工介入"。
7. **本仓可承接范围（诚实划界）**：本机无 Cadence/EMX/Calibre——可落
   EM 侧步（步 6 类无源 EM→sNp、步 9 天线 HFSS）与交接件；IC 侧步
   （2–5、8）只能走 fake/代理桩，真机判读如实 UNVERIFIED-LOCAL（R-08
   L2_DEFERRAL 同款处置）。天线步须先立领结天线模板（src/rfauto/ 与
   docs/templates/ grep "bowtie" 0 命中，2026-11-10 实测），并按规则 1c
   先对照官方例。

台账锚：runs/aurora_r/PLAN.md「TACS-RF 报道吸收」条（AX-8 扩展挂账）；
AX-8 原台账=runs/aurora_q/qx40_vbridge/AUTHOR_SURVEY.md §2。

**③"机器可读输出回灌+AI 读数据改脚本"闭环=rfauto 已在形态**（自评
复证，非新能力）：

- TACS-RF 形态：工具回传日志/工作点/波形量测（机器可读）→agent 评估
  本轮→决定下一轮参数更新；全程终端驱动、零人工 GUI。
- rfauto 已在面（证据路径）：服务层 JSON 进出（规则 4）；run 元数据与
  引擎身份随 run 落盘 infra/run_store.py（R-03）；确定性 critique
  service/autotune_service.py；闭环编排面为内部档（不在公开树）；判据面
  service/em_bench_service.py；回灌前产物校验=退出码判读前置
  core/exit_code_verdict.py（R-21）+严格结果访问器
  core/strict_access.py（R-12）。
- 论文双 Spectre 流（脚本快路径供迭代、cellview 路径供人核）↔本仓
  fake/真机双轨与"快引擎查→金标晋升"两级路由——同属已在形态。
- **数值归属差异（有意差异化，非缺口）**：TACS-RF 的参数更新值由 LLM
  推理直接写进脚本；本仓铁律 7 要求几何/物理数值只由确定性内核/优化器/
  综合引擎产出——本仓在 prompt 契约层与 schema 层（extra="forbid"
  闭集）双闸禁止 LLM 产几何/物理数值，LLM 只产 spec 与 typed tool call。复证结论=**闭环形态同构、数值归属不同**；后者是
  本仓对"代理误差传导"（22.2）的结构性防线，不因 TACS-RF 的成功而放宽。

**④Q-X40 VB-9 定位复证**：

- 原定位（runs/aurora_q/qx40_vbridge/PROPOSALS.md VB-9 节）：TACS-RF
  电路侧建在开源 MIT 桥之上，EM 侧是 LLM 现写脚本（无内核/无门/无
  仲裁）——正是本仓确定性 EM 链可补的位置。
- 本席扩读复证三点：①§II-B 与 §III-D 步 9：HFSS 侧端口/辐射边界/网格/
  扫频均由 agent 逐次现写决定——恰是本仓坑账最密的面：端口（#191 波
  端口尺寸、#254 平衡线端口截面、#307 双导体模阻抗基准）、边界（#356
  零厚度薄片须 PerfectE）、网格收敛（#335 ΔS 达标≠关键标量收敛）；
  确定性模板+健康门+HFSS 对齐基准把"每次现写"收敛为"一次定版、门控
  复用"。②§III-C：EMX 多端口 S 参数"导入 Virtuoso 替换理想匹配网络"
  正是 VB-9 sNp→Spectre nport 交接件的落点（R-18 已交付）。③§V：作者
  自述设计耗时首要瓶颈=EM 仿真运行时，若有预表征无源库可再显著缩短——
  即本仓数据工厂/代理内核（22.2 数据账意识；service/active_learning_loop.py
  σ 选点回填、core/gp_tensor_kernel.py）与服务器并行（规则 0b）的直接
  用例。
- 结论：VB-9 定位成立且被论文全文加强；本仓 EM 侧确定性内核生态对
  TACS-RF 栈是正对位补位，不是重叠竞争。

**⑤关键数字如实转录**（论文 abs/§IV/表 I 原文值，报道版同值；**全部为
提取后仿真值，非流片实测**）：

| 量 | 值 | 出处口径 |
|---|---|---|
| 频段/工艺 | 240–251 GHz；90 nm SiGe BiCMOS（fT/fmax 300/350 GHz） | abs；表 I |
| 输出功率 | +5.1 ~ +6.3 dBm（峰值 +6.3 dBm @246 GHz） | abs；§IV-B |
| 直流功耗 | 361 mW（表 I 记 0.36 W） | abs；§IV-B |
| 效率 | ~1.2%（报道方现场换算：+6.3 dBm≈4.27 mW，÷361 mW≈1.18%；本席复算一致，下限 +5.1 dBm≈3.24 mW 对应≈0.90%） | **报道派生量，论文未给本工作效率** |
| 调谐范围 | 11 GHz，varactor-only（纯变容管，不切电容阵列、不换频段） | abs；§IV-B |
| 相位噪声 | −80 ~ −88 dBc/Hz @1 MHz（跨调谐范围）；表 I 单点 −88 @1 MHz、−108 @10 MHz（表注：工作于 248 GHz） | abs；表 I（§I 另写"≤−85 dBc/Hz @1 MHz、跨 6 GHz VCO 调谐范围"，与 abs 口径不一致，如实并列） |
| 子模块 | VCO −1.5 dBm @123.7 GHz（负载牵引最优 25+j30 Ω）；两级 PA 功率增益 14.1–16.6 dB、OP1dB +2.2 dBm、Psat +8.5 dBm；倍频器 +2.9 dBm @123 GHz 入→+6.3 dBm @246 GHz 出，变频增益 +3.4 dB | §IV-A |
| 用时 | pre-layout 整链从零不到一周；作者估计有知识库后同复杂度模块一天内 | §V |

调谐 11 GHz 的报道解读（"低频调、高频跟"：二次谐波节点约 6 GHz 调谐经
倍频放大约两倍）与论文 §I 的 6 GHz VCO 调谐范围口径一致；11 GHz 即
240–251 GHz 的频段宽度。

**诚实边界**：①数字全部为提取后仿真（§IV 标题即 Post-Extraction
Simulation Results），未报告流片/实测；顶层拼版与终验原文用"would
assemble"——硅验证未发生（对照 AMS-IO-Agent 报 28 nm 流片，验收等级
不同，见 RAW_P4_A.md 目标 3/4）；报道"真实实例""AI 自己当射频工程师"
属报道措辞，不作采信依据。②表 I 的两篇对比源恰是提供给 agent 的参考
设计（§IV-B 原文）——对比属"给定参考答案下的复现与再优化"，不是独立
基线。③效率~1.2% 为报道派生量（论文未给；参考文献 [6] 标题所载 1.3%
DC-to-RF 效率属对比源，非本工作）；相噪口径 abs 与 §I 不一致，本节并列
不择一。④Fig. 1/2/4/5 未多模态实读（微信图为 blob 占位不可取，arXiv
图未抓取）——九步内逐步拆分按 §III 段落顺序推定。⑤框架无公开代码：abs
页 Comments 无代码发布声明（本席实读），与 Q-X40 DIGEST §7 第 8 条
"TACS-RF 无公开代码"口径一致；本席未检索第三方代码索引。⑥利益相关
提示：报道开篇提及该号曾推荐本项目开源仓——本节对位结论只以论文原文与
仓内证据为据。⑦本机无 Cadence/EMX/Calibre：四件套中三件的对位为"交换
格式解析/交接件/思想"级，唯 HFSS/PyAEDT 为同工具真对位。

**出处落版清单（续 22.4 章尾清单）**（访问日期均为 2026-11-10；思想级
转述，技术数字以论文原文为准）：

6. 射频学堂《AI自己设计射频，这事可能真的快成了！？》（第五篇微信文章，
   web_reader 全文实读）：
   https://mp.weixin.qq.com/s/RRArWeeEPRxLfeMvmczzMA
7. T. Liang, A. Nagulu, "TACS-RF: Tool-driven Agentic Circuit Synthesis
   of RF and mmWave Modules", arXiv:2610.31882v1（2026-10-22）——abs 与
   HTML 全文本席实读：https://arxiv.org/abs/2610.31882 ，
   https://arxiv.org/html/2610.31882
8. 仓内接地：runs/aurora_q/qx40_vbridge/DIGEST.md（§0"下游使用实证"行、
   §7 第 8 条）、runs/aurora_q/qx40_vbridge/PROPOSALS.md（VB-9 节）、
   runs/aurora_r/PLAN.md（「TACS-RF 报道吸收」条）、
   runs/aurora_r/p4_survey/RAW_P4_A.md（PANDA/AMS-IO 对照）。

### 22.6 "不报错的错误"判据面与连通性诊断链（第六篇：PFC 热力耦合 AI 全自动验证，主代 2026-11-10）

- 出处：微信文章《AI 全自动做热力耦合：从一句话需求到解析解验证》
  https://mp.weixin.qq.com/s/cm8qUIt4JLgC00oGmmc9Gg （访问 2026-11-10；
  VibePFC 社区 PFC 6.0 实测演示——个人公众号文章非开源仓，思想级吸收零许可风险；
  PFC/Itasca 颗粒离散元生态与 rfauto RF/EM 域零重叠）。
- **核心案例与 rfauto 坑账同族实锤**："热求解器收敛指标全好但温度场冻结"
  （热量传到 x≈11 停止、升温球数恒定 68、零报错零警告——"程序正常结束≠物理
  正确"）与 rfauto 速查既有家族完全同构：#262（窄窗截断 |S11|>1 假象）、#266
  （耦合缝 <NEAR 缝内零内部线=外 Q 建模粗）、#268（et 文件 mtime 停止≠卡死，
  stdio 缓冲伪象）、#323（整树无声消失无 traceback）。本篇增量=**自主诊断链
  形态**：异常症状（冻结）→量化探查（升温球数恒定）→结构分析（接触网络导出
  边列表→flood fill 连通分量→11 孤岛，含热源孤岛恰=68 球覆盖 x≤11.5）→病因
  定谳（37% 近邻对有缝隙无接触=无热管道）→两种解法（半径放大/力学压密）各自
  全链验证。**整链零人工**。
- **吸收点①（em_bench 新任务族蓝本，挂账 R 系扩展池）**：silent-failure 检测
  任务族——给 agent 一个"数值上收敛但物理上退化/冻结/截断"的 run 产物，判据=
  agent 能否在无引擎报错辅助下检出退化（判据面：物理守恒量检查/边界值 sanity/
  传播深度与解析预期对照）。与本仓 #331"观察工具自身失真"家族互补：前者防
  观察面失真，本篇防"引擎侧静默退化被收敛指标掩盖"。
- **吸收点②（渲染链守卫参照）**：接触/网格连通性图论自检——flood fill 连通
  分量分析作为 run 前结构自检，与本仓 NetRegistry 连通性检查、#152/#311 网格
  缝隙守卫同构；增量=把"连通性"从建模期守卫扩展到**激励→边界的完整导热/导电
  路径贯通性检查**（单分量含源含汇），openEMS 渲染链可作后续席参照（挂账，
  不实现）。
- **吸收点③（多保真叙事互证）**：三版本对照方法论（A 规则排列=理想接触网络
  证算法本体正确，偏差 <0.2%；B 随机+放大=快捷但孔隙率失真 20-35%；C 随机+
  力学压密=保真且追平 0.6%）与 rfauto fake（理想闭式）→openEMS（离散真实）
  →HFSS（仲裁基准）三保真链同构——"基准版证模块对、工程版证地形对、双版互
  印证强于单算例碰巧对上"的叙事可直接引用为多保真判读文档语料。
- **吸收点④（报告形态参照，低优先）**：自包含单文件 HTML 报告（动图+偏差表+
  参数表+复现命令内嵌，可转发可归档）——rfauto design_report/health 报告已有
  HTML 面，"单文件自包含+复现命令附尾"两点可作报告产物形态参照。
- **采样策略小件**：瞬态扩散过程按 √t 等比取时刻切片（12 片+稳态）——对
  openEMS 时域场验证/收敛切片采样可借鉴（挂账）。
- 诚实边界：原文系数值模块功能验证（对标解析解），非真实材料标定——k/Cv 为
  算例设定值；"AI 全自动"含人工发起的一句话需求与迭代方向裁决，非无监督。
