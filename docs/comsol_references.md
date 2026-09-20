# COMSOL 引用与速查（2026-09-10 定稿）

> 本文件是 COMSOL 开发的权威口径速查（对应 docs/rf_template_references.md
> 在 COMSOL 侧的对应物）。**纪律：COMSOL 相关开发先读本文件与官方文档，
> 禁止凭想象写 API**（同铁律 1c）。官方文档在本地安装内，离线可查且
> 与本机 6.3.0.290 版本精确对应。

## 0. 本机通道现状（2026-09-10 探测定版）

| 项 | 状态 |
|---|---|
| COMSOL 6.3.0.290 | ✅ **可用**；RF 模块运行时 license PASS（MPh 实测） |
| COMSOL 6.4 | ❌ 禁用（license 单行 SERIAL 13-apr-2026 过期且无模块包） |
| **版本钉扎** | **必须显式 `mph.start(version="6.3")`**——MPh 自动探测选"最新"=6.4=过期（#215） |
| license 形态 | permanent uncounted，RF/RFBATCH/RFCSL/RFCOMPL 齐全；**每次求解占一个席位，串行使用** |
| Python 桥 | MPh 1.4.0（venv 已装，[dataset] 同款 extras 模式） |
| **首案例** | ✅ 2026-09-11：`ComsolAdapter` 接入 EMSolverRegistry + 平行板 TEM 真机冒烟闭式吻合（坑 #217 API 口径实证已回写本文 §2/§3/§5） |

## 1. 权威文档来源（按查询优先序）

1. **本地官方 PDF（6.3 精确对应版，随安装自带）**：
   - `<COMSOL 安装根>\Multiphysics\doc\pdf\COMSOL_Multiphysics\ApplicationProgrammingGuide.pdf`（254 页，端到端 Java 惯用法）
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
- **#217 实证更正（2026-09-11 首案例）**：RF 集总端口
  建模必须用 `ElectromagneticWaves`（emw）——`ElectromagneticWavesFrequencyDomain`
  （ewfd，Wave Optics 风格）可创建但**无 LumpedPort 特征**；study 频域步
  类型串是 `Frequency` 非 `FrequencyDomain`。早期探针脚本用的 ewfd 仅证明 license 可用，不作建模
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
  通过（2026-09-11 真机验证）；`ElectromagneticWavesFrequencyDomain`
  仅在早期探针中用于 license checkout 验证，无 LumpedPort，不用于建模
  （#217①）。
- S 参数工作流：port 边界条件（LumpedPort，Uniform/Cable 型）+ study
  频域步 `Frequency`（plist 频点）+ 求解后 port 扫频 S 参量（官方 RF
  Module User's Guide 端口章）。首案例=平行板 TEM 2 端口（PEC 板+PMC
  侧壁）：匹配 Zref=50Ω 时 |S11| −98dB、|S21|=1.0000、反推 εeff=2.1000；
  失配 Zref=75Ω 变体与闭式复数逐点误差 ≤5.8e-8（冒烟证据存档，
  不入 git）。
- 频域求解器直接频点扫描（plist），与 openEMS 的时域→DFT 路线不同
  ——跨引擎对拍时频点网格要对齐。

### 5a. 数值 TEM 边界模端口完整链（mline 锚，2026-09-14 真机过锚实录）

集总端口 Uniform 的准静态场形与真实微带模失配（端口结电容）→ εeff 相位
斜率系统性偏高：**集总旧口径 run11 实测 εeff=2.98972、Δ_HJ=+4.805%，如实
FAIL**（mline 汇总存档；run5→7 网格/空气盒细化各仅回
−0.4%，排除网格/域因素）。官方消除该口径差的路径是数值 TEM 边界模端口，
参考实现 `comsol_adapter.py::_build_mline`（`mline_port_chain="tem"`），
官方实录源全部在本地解包证据（官方例 model.xml/dmodel.xml 解包）：

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

**真机三档网格收敛 PASS**（mline_tem 网格收敛存档，
tanδ=0.0037）：mesh_scale 1.0/0.7/0.55 → εeff 2.91724/2.91334/2.90516，最细
两档收敛 0.28%，最细档 Δ_gold(2.886) +0.66%、Δ_HJ(2.85264) +1.84%、
Δ_HFSS(2.920) −0.51%，|S11|max −41.0 dB。

## 6. 与 rfauto 的集成纪律

- 适配器 = EMSolverAdapter 基类 + EMSolverRegistry 注册（规则 3）；
  服务层 JSON 进出（规则 4）。
- **license 席位**：每次 solve 占一席，适配器内串行（同 HFSS 通道
  惯例）；进程隔离单 JVM（MPh 一进程一 Client）。
- 真跑前 `mph.start(version="6.3")` 钉版本；正式探针脚本
  `scripts/comsol_probe.py`（#217 口径：6.3 钉扎 + `ElectromagneticWaves`
  + LumpedPort 可创建即 license PASS；`--dump-api` 落 emw/study 步全属性
  供 API 核对，产物落存档）。早期探针脚本已清理，不再作为模板引用。
- 第三方仲裁定位：COMSOL FEM vs openEMS FDTD vs HFSS FEM 三源对拍
  （稀缺资源，不做日常主力）。

## 7. COMSOL 收口包实证（2026-09-15 真机）

### 7a. AFS 自适应频扫真机验收（冻结判据）——PASS

`scripts/comsol_afs_realcase.py`：mline TEM 链（tanδ=0.0037，band
2.3-2.7 GHz，mesh_scale=1.0，6.3 钉版）建模一次 → 41 点密集全扫参考
（432.1 s，1 席）→ `core.afs.afs_sample` 以持久模型单频重解
（`ComsolAdapter.resolve_s21_at_frequency`：freq 步 plist 单点 →
`study("std1").run()` → EvalGlobal **唯一 tag** `gev_s21_r{seq}`+先
remove 兜底——EvalGlobal 重复 create 同名会撞名）为回调。真机
**13/41 次求解、缩减比 0.683（≥0.5 频点减半达成）、FSV GDM=Ex
（0.0138 ≥ VG）、converged**（证据存档）。
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
PASS（mline_tem 参数化扫描存档）：scale 1.0 → εeff 2.9172
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
读=多模态目检互证，zai-mcp 判读官方图 2 次超时如实记录）→ verdict 落
figure3_check 存档（figure3_check.json）。

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
相变封顶物理，对当前无相变模型不构成参考量（已定论）。
