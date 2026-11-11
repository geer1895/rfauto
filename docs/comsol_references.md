# COMSOL 引用与速查（WP4.4c，2026-09-10 定稿）

> 本文件是 COMSOL 开发的权威口径速查（对应 docs/rf_template_references.md
> 在 COMSOL 侧的对应物）。**纪律：COMSOL 相关开发先读本文件与官方文档，
> 禁止凭想象写 API**（同铁律 1c）。官方文档在本地安装内，离线可查且
> 与本机 6.3.0.290 版本精确对应。

## 0. 本机通道现状（2026-09-10 探测定版）

| 项 | 状态 |
|---|---|
| COMSOL 6.3.0.290 | ✅ **可用**（E:\COMSOL\COMSOL_63\COMSOL63\Multiphysics）；RF 模块运行时 license PASS（MPh 实测，证据链 runs/comsol_probe/） |
| COMSOL 6.4 | ❌ 禁用（license 单行 SERIAL 13-apr-2026 过期且无模块包） |
| **版本钉扎** | **必须显式 `mph.start(version="6.3")`**——MPh 自动探测选"最新"=6.4=过期（#215） |
| license 形态 | permanent uncounted，RF/RFBATCH/RFCSL/RFCOMPL 齐全；**每次求解占一个席位，串行使用** |
| Python 桥 | MPh 1.4.0（venv 已装，[dataset] 同款 extras 模式） |
| **首案例** | ✅ 2026-09-11：`ComsolAdapter` 接入 EMSolverRegistry + 平行板 TEM 真机冒烟闭式吻合（DEVLOG（廿七），坑 #217 API 口径实证已回写本文 §2/§3/§5） |

## 1. 权威文档来源（按查询优先序）

1. **本地官方 PDF（6.3 精确对应版）**：
   - `E:\COMSOL\COMSOL_63\COMSOL63\Multiphysics\doc\pdf\COMSOL_Multiphysics\ApplicationProgrammingGuide.pdf`（254 页，端到端 Java 惯用法）
   - 同目录 `COMSOL_ProgrammingReferenceManual.pdf`（model.* 全方法参考：geom/material/mesh/physics/study/sol/result/…）
   - RF 模块专属：`doc\pdf\RF_Module\`（端口/S 参数/频域求解器口径）
2. **MPh 文档**（Python 桥 API）：https://mph.readthedocs.io/en/latest/
   （tutorial.html=工作流惯用法；api/mph.Node.html=树节点 API；limitations.html）
3. doc.comsol.com 在线文档（部分路径 404/反爬，优先用本地 PDF）。

## 2. COMSOL API 官方惯用法（摘自本地 ApplicationProgrammingGuide）

模型树骨架（Java API；MPh 下经 `model.java` 或 Node 路径访问）：
```java
model.modelNode().create("comp1");            // 组件
model.geom().create("geom1", 2);              // 几何（2=空间维度）
model.mesh().create("mesh1", "geom1");        // 网格
model.material().create("mat1", "Common");
model.physics().create("emw", "ElectromagneticWaves", "geom1");  // RF 频域接口，tag 惯例 emw（#217①）
model.study().create("std1");
model.study("std1").create("freq", "Frequency");                 // 频域步类型串是 "Frequency"（#217②）
model.study("std1").feature("freq").set("plist", "2.4");  // 属性 set
model.study("std1").feature("freq").setIndex("geometricNonlinearity", "off", 0);
```
- **#217 实证更正（2026-09-11 首案例，DEVLOG（廿七））**：RF 集总端口
  建模必须用 `ElectromagneticWaves`（emw）——`ElectromagneticWavesFrequencyDomain`
  （ewfd，Wave Optics 风格）可创建但**无 LumpedPort 特征**；study 频域步
  类型串是 `Frequency` 非 `FrequencyDomain`。早期探针脚本
  runs/comsol_probe/_probe_*.py 用的 ewfd 仅证明 license 可用，不作建模
  口径。**参考实现：src/rfauto/adapters/comsol_adapter.py**（真机验证过的
  完整链：几何→材料→emw+LumpedPort→Frequency study→S 参数读取）。
- 属性访问三件套：`set()` / `setEntry()` / `setIndex()`；读取用
  `get*` 与 Selection Access Methods（见手册 General Commands 章）。
- `model.geom("geom1").axisymmetric(true)`——轴对称开关（仅 1/2 维）。
- 几何改后必须 `geom.run()`（或求解时隐式重建）；`model.build()`（MPh）。

## 3. MPh 工作流惯用法（readthedocs tutorial 实录）

```python
import mph
client = mph.start(cores=1)          # cores 限核；**version="6.3" 钉版本**
model = client.create("name")        # 或 client.load("x.mph")
model.parameter("d", "1[mm]")        # 参数读写（带单位字符串）
model.build(); model.mesh(); model.solve("static"); model.solve()  # 全部 study
value = model.evaluate("2*es.intWe/U^2", "pF")            # 全局量+单位
(x, y, E) = model.evaluate(["x", "y", "es.normE"])         # 场量→numpy
model.save("out.mph"); model.clear(); model.reset()       # 存/清解/剪历史
```
- **一个 Python 进程只能有一个 Client**（JPype 单 JVM）——并行=多进程；
  Client 常驻不可重启，多 COMSOL 求解并行必须进程隔离（同 openEMS #208
  路线，#217⑤），进程内串行锁已在 comsol_adapter.py。
- `model.solve(name)` 按 **label** 找 study；Java API 建的 study 用
  `model.java.study(tag).run()`（#217③）。JPype 整数/布尔属性
  （entitydim/PortName 等）一律传字符串，避免 set(String,int)/
  set(String,boolean) 二义（#217④）。
- 结果直接返回 numpy 数组；`model.inner()/outer()` 取时间步/扫参索引。

## 4. Node 树 API（MPh 1.4，路径语法）

```python
node = model/'physics'/'electrostatic'   # pathlib 风格下钻
node.exists(); node.name(); node.tag(); node.type()
node.properties()                        # 全属性 dict
node.property('HeatSource', 'Q0', '1[MW/m^3]')  # 属性 set
node.select('all'); node.select([1, 2, 3]); node.select(None)
node.toggle('disable'); node.create('Block', name='My Block')
node.rename(); node.retag(); node.remove()
node.java                                # 逃逸口→裸 COMSOL Java 对象
```
- **`.java` 是属性非缓存**——每次访问自顶向下全树搜索，热循环里要
  先取出持有。
- `create()` 只对 model "features" 有效（材料属性组等任意节点不行）；
  合法参数=官方文档的 feature 类型串（如 `'Block'`）。
- 含 `/` 的名字用双斜杠转义（`'sweep//solution'`）。
- `model/'...'.problems()` 列全树 warnings/errors（几何/网格/求解器）。
- 选择集：`NotImplementedError` on geometry 节点；无选择集节点 raise
  TypeError——几何操作直接走 `.java`。

## 5. RF 模块要点（S 参数仿真，详读 doc\pdf\RF_Module\）

- 物理场接口：**`ElectromagneticWaves`（tag emw）**——首案例真机求解
  通过（2026-09-11，DEVLOG（廿七））；`ElectromagneticWavesFrequencyDomain`
  仅在早期探针中用于 license checkout 验证，无 LumpedPort，不用于建模
  （#217①）。
- S 参数工作流：port 边界条件（LumpedPort，Uniform/Cable 型）+ study
  频域步 `Frequency`（plist 频点）+ 求解后 port 扫频 S 参量（官方 RF
  Module User's Guide 端口章）。首案例=平行板 TEM 2 端口（PEC 板+PMC
  侧壁）：匹配 Zref=50Ω 时 |S11| −98dB、|S21|=1.0000、反推 εeff=2.1000；
  失配 Zref=75Ω 变体与闭式复数逐点误差 ≤5.8e-8（证据 runs/comsol_smoke/，
  不入 git）。
- 频域求解器直接频点扫描（plist），与 openEMS 的时域→DFT 路线不同
  ——跨引擎对拍时频点网格要对齐。

### 5a. 数值 TEM 边界模端口完整链（mline 锚，2026-09-14 真机过锚实录）

集总端口 Uniform 的准静态场形与真实微带模失配（端口结电容）→ εeff 相位
斜率系统性偏高：**集总旧口径 run11 实测 εeff=2.98972、Δ_HJ=+4.805%，如实
FAIL**（runs/comsol_tail/mline_summary.json；run5→7 网格/空气盒细化各仅回
−0.4%，排除网格/域因素）。官方消除该口径差的路径是数值 TEM 边界模端口，
参考实现 `comsol_adapter.py::_build_mline`（`mline_port_chain="tem"`），
官方实录源全部在本机解包证据 `runs/comsol_tail/_doc_probe/`：

| 环节 | 官方口径（出处） | 实录/实现 |
|---|---|---|
| 端口特征 | `Port`，`PortType="Numeric"` + `numericTEM="1"`（cpw_numeric_tem_port 例 `_doc_probe/cpw_tem/model.xml`；`"TEM"` 值是同轴**解析**型，tem_via 例 `_doc_probe/tem_via/dmodel.xml`） | comsol_adapter.py `PORT_TYPE_NUMERIC` |
| 电压积分线 | 子特征 `IntegrationLineforVoltage`（GUI "Integration Line for Voltage" 去空格、for 小写；RF User's Guide p.128：数值 TEM 必须配，定标端口模阻抗） | WorkPlane(yz) LineSegment 地→走线，`specify1/2="coord"`（butler 例实录） |
| 边界模分析步 | 每端口一个 `BoundaryModeAnalysis` 步（cpw 例 Step1 bma PortName=1 → dup PortName=2 → freq）；属性 `modeFreq`/`shift`（真机 dump 实录），**无 plist**（频点概念在 Frequency 步） | `bma1`/`bma2`，shift=`sqrt(epsr)` |
| StudyStep 解引用 | 端口 `StudyStep="std1/bma{n}"`（tem_via 例 `std1/tbma` 同构）——run9/10 报 `Cmode_1 未定义` 即缺此接线 | bma 步**创建后**回填（步不存在时 set 报「参数值无效」） |
| tanδ 介质 | 官方 RF 材料库 `LossTangentDF` 属性组（`_doc_probe/rf_lib_dmodel.xml`）：`epsilonPrim` + `tanDelta`，def 组不再设 relpermittivity；6.3 客户端 `propertyGroup().create(tag, type)` 两参 | `_dielectric_material(tan_d=0.0037)` |

**五坑**（`comsol_adapter.py::_build_mline` docstring 原文）：① Port 特征只能放**外部边界**
（「狭缝条件只能应用于内部边界，或者，端口只能放置在外部边界上」）→ 域端
=端口面；② StudyStep 解引用须在 bma 步创建后回填；③ BoundaryModeAnalysis
步无 plist 属性；④ 数值 TEM 端口 PortType="Numeric"（"TEM"=同轴解析型）且必
须配 IntegrationLineforVoltage（缺失 solve 报 Cmode_1 未定义）；⑤ 每端口一个
bma 步（PortName 属性绑定）。

**真机三档网格收敛 PASS**（runs/comsol_tail/mline_tem_mesh_convergence.json，
tanδ=0.0037）：mesh_scale 1.0/0.7/0.55 → εeff 2.91724/2.91334/2.90516，最细
两档收敛 0.28%，最细档 Δ_gold(2.886) +0.66%、Δ_HJ(2.85264) +1.84%、
Δ_HFSS(2.920) −0.51%，|S11|max −41.0 dB。

## 6. 与 rfauto 的集成纪律（WP4.4c）

- 适配器 = EMSolverAdapter 基类 + EMSolverRegistry 注册（规则 3）；
  服务层 JSON 进出（规则 4）。
- **license 席位**：每次 solve 占一席，适配器内串行（同 HFSS 通道
  惯例）；进程隔离单 JVM（MPh 一进程一 Client）。
- 真跑前 `mph.start(version="6.3")` 钉版本；正式探针脚本
  `scripts/comsol_probe.py`（#217 口径：6.3 钉扎 + `ElectromagneticWaves`
  + LumpedPort 可创建即 license PASS；`--dump-api` 落 emw/study 步全属性
  供 API 核对，产物 runs/comsol_tail/probe_api_dump.json）。早期
  runs/comsol_probe/_probe_*.py 已清理，不再作为模板引用。
- 第三方仲裁定位：COMSOL FEM vs openEMS FDTD vs HFSS FEM 三源对拍
  （稀缺资源，不做日常主力）。

## 7. COMSOL 轨收口包实证（队列 #26，2026-09-15 真机）

### 7a. AFS 自适应频扫真机验收（§10.20⑩ 冻结判据）——PASS

`scripts/comsol_afs_realcase.py`：mline TEM 链（tanδ=0.0037，band
2.3-2.7 GHz，mesh_scale=1.0，6.3 钉版）建模一次 → 41 点密集全扫参考
（432.1 s，1 席）→ `core.afs.afs_sample` 以持久模型单频重解
（`ComsolAdapter.resolve_s21_at_frequency`：freq 步 plist 单点 →
`study("std1").run()` → EvalGlobal **唯一 tag** `gev_s21_r{seq}`+先
remove 兜底——EvalGlobal 重复 create 同名会撞名）为回调。真机
**13/41 次求解、缩减比 0.683（≥0.5 频点减半达成）、FSV GDM=Ex
（0.0138 ≥ VG）、converged**，证据 runs/comsol_tail/afs_realcase/。
离线审计先行抓出的两个判据边界（tests/unit/test_comsol_close_bundle.py
钉住）：① **FSV 按 |S| dB 归一，纯无耗匹配线参考 dB≈0（合成实测跨带
8e-8 dB）时 ADM/FDM 结构性退化 → VP（#195 同族常数陷阱，与 tol 无关）
——tanδ 必建**（真实量级损耗 |S21|≈−0.05 dB 下 VF 幅度误差仅 ~6e-4 dB）；
② tol 维持内核默认 1e-2：更紧（5e-3）时 (4,8) 阶梯拟合不了纯延迟线 →
max_points 未收敛。S11（−35 dB 底噪）不进 AFS，拟合对象=复数 S21。

### 7b. TEM 边界模端口 × Parametric 端口扫描（全 2×2 矩阵）——PASS

`scripts/comsol_mline_tem_benchmark.py --port-sweep`：官方
PortSweepSettings（useSweep=1、ExportTouchstone=1）+ study 外层
Parametric 步扫 PortName。真机步序实测 `["param","bma1","bma2","freq"]`
（param 外层先建、bma 在 freq 前；probe-only 零席位验证，步序回读用
`study("std1").feature().tags()`——study 本体无 tags()）。双档真跑
PASS（runs/comsol_tail/mline_tem_parametric/）：scale 1.0 → εeff 2.9172
（Δ_gold +1.08%、Δ_HJ +2.26%、|S11|max −35.1 dB）、scale 0.7 → 2.9133
（+0.95%/+2.13%/−37.3 dB）；收敛 0.13%<1%、无源 max|S|=0.9857、
Touchstone 原生导出；εeff 与单激励 tem run 逐位一致（组合零口径漂移）。
两个真机实证坑：① **bma 步零列污染装配**——bma 步（modeFreq=带中值
2.5 GHz）的解数据集也带 freq/PortName，S 表达式未定义回读精确 0，
`_extract_sparams_full` 的 dataset×outer 遍历中后到零列曾覆盖 2.5 GHz
行 S12/S22 真值（互易残差 0.98 假象；COMSOL 原生 Touchstone 同频点完
整）——已加守卫：全零列视为未定义跳过、首有效列不被覆盖；② 互易残差
实测 7.6e-3（scale 1.0）/2.3e-3（scale 0.7）：数值端口两端口各自 bma 模
归一在非同构端面网格上有亚百分位差异（**假设/待证**），1e-3 门对 FEM
数值端口过紧，互易只记录不作门。

### 7c. 官方 Microwave Oven 例 Figure 3 对照——PASS（形态级）

官方模型文档对温度场**无任何标量参考量**（PDF 全文 30 页核），唯一温度
参照=Figure 3 曲线图。本地官方图定位：
`doc\help\wtpwebapps\ROOT\doc\com.comsol.help.models.rf.microwave_oven
\images\microwave_oven.1.1.06.png`（PDF 第 5 页；官方 html 的 caption 与
img **错位一格**——1.1.07 前置文本挂着 Figure 3 caption 但内容是 5 s 末
态 3D 场图，逐图目检 1.1.06 才是双面板中心温度-时间曲线）。
`scripts/comsol_microwave_oven.py --thermal transient --fig3-curve`：
报告新字段 `center_probe.t_center_series_c`（官方 CutPoint3D 截点位
6 时刻序列）+ matplotlib 渲染对照 PNG。真机（2 min 级）：6 点序列
8.0/19.5/30.5/41.1/51.3/61.1 degC，P_absorbed=637.895 W vs 官方 631 W
（dev 1.09%，±5% 门内）、能量锚 rel_dev 0.000%。形态对照 4/4 一致
（单调上升、起始 ~8 degC、末值 ~61 degC 量级、近线性无饱和；官方图判
读=本会话多模态目检 + zai-mcp 判读我方曲线，官方图 zai-mcp 2 次超时
如实记录）→ verdict 落 runs/comsol_mw_oven/figure3_check/
figure3_check.json。

### 7d. 姊妹模型 rotating_microwave_oven 评估——**另立项，不并入当前收口**

官方文档本地在库（`com.comsol.help.models.rf.rotating_microwave_oven\`，
PDF+html+images 零网络）。与当前 oven 复现的能力差四族：① **Phase
Change Material**（ht 接口，相变温度 373.15 K、潜热 2.2564e6 J/kg，
water-rich→dehydrated 两相）；② **Moving Mesh/Rotating Domain**（9 deg/s
旋转、每 0.25 s 步进重贴网格）；③ **Events 接口**（Explicit Event 周期
dt + Discrete States 跟踪转角/步号）；④ **Wave Equation, Electric 2**
温度依赖介电常数/损耗。study=Frequency-Transient range(0,0.25,100)
（100 s、401 输出时刻）。**结论：另立项**。依据：当前 oven 复现的验收
判据已收口（吸收功率 631 W ±5% 真机 PASS、能量锚/中心峰化 PASS、
Figure 3 形态 PASS），相变+旋转是**物理效应增强项**而非验收缺口；四族
能力各需官方 dmodel 解包→离线门→真机三步（同 mline tem 链纪律），合计
复杂度远超单项收口包量级；且求解器复杂度（旋转重贴网格 ×401 时刻）与
license 席位时长预算需单独评估。官方结果叙述（平均温度渐近 380 K）属
相变封顶物理，对当前无相变模型不构成参考量（§10.24 已定论）。

## 8. 热弹性借用批 11 坑实录（2026-11-02 专利3 外借批）

> 来源：第三方只读借用（专利自动化工作台，晶圆键合热-力耦合参数研究，
> COMSOL 6.3.0.290 结构热弹性、2D 轴对称、160 组扫参+代理模型训练）用本仓
> venv 跑通后的实测反馈，原件
> `runs/aurora_q/feedback/rfauto使用反馈-20261102.md`（Win10 / MPh 1.4.0 /
> JPype 1.7.1；按排错代价从大到小排序，全部为该批真机实证）。转录纪律：
> 逐条照录 + 【建议/守卫】注记；坑1/坑2 的守卫已落地
> `comsol_adapter.py`（T-Q16 双守卫，缺省零行为变化——检测面拿不到一律
> unknown 放行，绝不误报）。

1. **【最大坑，2 小时级】ThermalExpansion userdef 模式下 `Tref` 不显式设置
   → 特征静默失效，解为精确零，全程无任何警告。** 表现：`std.run()` 正常
   返回、dataset 正常、位移场（w）恒等于 0.0。且属性可用性与设置顺序相关：
   先单独 `set("Tref",…)` 报「未知参数 Tref」，按
   `alpha_mat("userdef") → alpha → T → Tref` 顺序设置则成功。语义已用自由
   膨胀解析值精确验证：`ε = α·(T − Tref)`（T=终温、Tref=无应力温度）。
   【建议/守卫】adapter 已落「热弹性静默零解守卫」（`solution_all_zero` +
   `thermal_expansion_feature_tags`，solve 内解全精确零且模型含
   ThermalExpansion 特征 → message/field_data 显式警告，success 不变）；
   建模侧 Tref 官方属性名=minput_strainreferencetemperature
   （`add_thermal_expansion` 已按此配方）。
2. **空 mesh 序列（只有 Size 节点、无 FreeTri/Map 操作）不产生任何单元
   （getNumElem()=0），`std.run()` 仍静默「成功」**，评估全部返回空。
   【建议/守卫】adapter 已落「空网格守卫」（`mesh_element_count`，solve
   在 study.run 前检查，==0 拦截 success=False 并指向网格配置；拿不到单元
   数=unknown 放行不误报）。
3. **映射网格操作的类型标识是 `"Map"` 而非 `"Mapped"`**（后者报「在这个
   情景中不能创建本操作」，与编程指南文本不一致；伪类型名对照实验确认
   `"Map"` 可建）。Modeling Guide 文本与 6.3.0.290 实现存在出入。
   【建议/守卫】映射网格一律 `create(tag, "Map")`；类型串纪律同 #217
   （`"ElectromagneticWaves"` 非 `"...FrequencyDomain"`）——文档文本与引擎
   实现冲突时按引擎实测回写本表。
4. **薄层叠层（1μm×138mm 键合带）用 FreeTri 网格会爆炸/挂死**（跨尺度
   过渡单元数失控）；唯一稳解 = `Map` 映射网格 + 每长边显式 Distribution
   计数（对边计数一致）。该批配方：全场 ~1.4k 单元、单次求解 2~4 秒。
   【建议/守卫】薄层热-力模型网格配方=Map+Distribution 逐边显式计数、
   禁 FreeTri 跨尺度过渡；将来做结构/热通道可直接移植为 adapter 薄层
   档缺省网格。
5. **新建 LinearElasticModel feature 默认 `E_mat/nu_mat="from_mat"`**：
   无材料库的纯物理场模型必须显式 `set("E_mat","userdef")`，否则编译报
   「所需材料属性 E 未定义」，报错不指向真正根因（尤其报错编号指向的
   feature 未必是你以为的那个——label 序号与创建序号会错位，该批
   「线弹性材料 3」实际是第 4 个 feature）。
   【建议/守卫】无材料库模型一律显式 userdef 三件套（E/nu/alpha）；
   排错按 feature tag 定位、不信 label 序号（观察面自身失真，#331 族）。
6. **`mph.Model.evaluate` 不支持坐标与模型输入类表达式**（`x/y/X/Y/T` 均
   报「未定义变量」），仅场量可用；轴对称坐标用 `r`/`z`。多表达式同点集
   求值需走 `java.result().numerical().create(…,"Eval")` +
   `set("expr",[list])`（返回 点数×表达式数 矩阵）。
   【建议/守卫】坐标/模型输入类一律走 Eval 链不走 evaluate；adapter 既有
   评估面（EvalGlobal/Eval）同口径，新评估链沿用。
7. **Eval.getReal() 返回矩阵的行/列方向在两次会话中表现不一致**（一次
   [点][表达式]、一次疑似转置）。【建议/守卫】不假设行列方向——按物理
   范围（如 r∈[0,R]、z∈[0,H]）做列自动识别兜底；mph 侧若出统一转置策略
   须文档化（观察工具自身失真，#331 族）。
8. **2D 域最大值没有现成 numerical 算子**（MaxSurface 为 3D 专用）；
   Maximum 组件耦合的表达式引用（`maxring(...)`/`comp1.maxring(...)`/
   `mod1.maxring(...)`）三种前缀均报「未知函数或算子」。该批最终用 Eval
   全场矩阵 + numpy 过滤替代。【建议/守卫】2D 极值=Eval 全场取数+numpy
   聚合（数值只在确定性内核，铁律 7 同构）；耦合算子引用名勿臆测。
9. **JPype set 重载歧义**：`set(str,int)` 在 bool/int 间歧义 → 传
   `jpype.JInt`；数值属性一律传字符串最稳（`set("elemcount","154")`）。
   【建议/守卫】同 #217④ 既有纪律（整数/布尔属性一律传字符串），adapter
   全链已照此，新增 API 面沿用。
10. **本地 applications 目录的 .mph 是「案例库预览文件」，不能 load/solve**
    （该批加载 MEMS_Module/Sensors/thermal_expansion.mph 被拒）。
    【建议/守卫】实录里「官方例 XXX.mph」必须标注真实来源路径（本仓实录
    均来自可解副本/解包 dmodel，见 §5a/§7 出处注记）；按 applications
    路径找可解副本会落空。
11. **physics `create(tag,type,geom_tag)` 第三参是几何 tag 字符串而非维度
    整数**（报错信息含糊）；study feature `create(tag,type)` 只两参。
    【建议/守卫】签名差异以 §2/§5a 实录为准；adapter 顶部常量区已集中
    注记，新增物理场接口先核对本表再写。

### venv 作为只读运行时外借（官方口径，2026-11-02 实证）

- 绝对路径调用、不激活不复制：
  `E:\rfauto_workspace\.venv\Scripts\python.exe -I 脚本.py`（Python 3.12.14）；
- `-I` 隔离建议：忽略调用方 PYTHONPATH/用户 site-packages，嵌套虚拟环境
  不串味；调用方产物一律落**调用方自己的工作区**（零写入本仓）；
- 外借纪律：只读借用——不向仓内写文件、不动 venv（不装/卸包）、不动
  `runs/` 与 `configs/`；README 面同款口径见「venv 作为只读运行时外借」节；
- 该批借用栈实测全齐：torch 2.14 CPU / scipy 1.18 / sklearn 1.9 / numpy
  2.4 / matplotlib / pandas / MPh 1.4 + JPype 1.7——零安装直接开工，
  借用形态评价 ⭐⭐⭐⭐⭐。
