> 【归档注记】T48（2026-09-29）自用户桌面归档入仓。来源=用户桌面 fab-export 方案母本（吸收前调研稿）；归档日期=2026-09-29；对应实现 commit=7ed656d（T43 吸收批：src/rfauto/{core,adapters}/fab_export + service/fab_export_service + cli/fab_app）。**内部资料：本文档含厂家联系方式与商务口径，不入公开仓——release/发布前按 release/RELEASE_GUIDE.md §5 三层审查剔除或改写**。（本文档含厂家官网与客户/设备能力等商务语境） 正文自本行以下零改写。

# HFSS → 可 CNC 加工 CAD 图纸全链路方案（终极详细版）

**版本**：v3.4（细则含 ISO↔GB 对照、函数草稿、源码级格式清单）  
**日期**：2026-09-29  
**约束**：本轮仅调研与方案撰写；**不在 `D:/rf_workspace` 创建/修改任何文件**  
**配套细则**：`HFSS到CAD加工_可落地细则.md`（金样数字、图框/ezdxf、RFQ、规则库、**heal 安全预设**、**开源出图引擎选型**）
**首选厂家**：成都西夏科技发展有限公司（http://m.xixiakeji.com）  
**调研广度**：PyAEDT/OCCT 源码、开源 CAD 栈、微波机加标准、MBD/QIF/CAM、国产 CAD 自动化、特征识别/EDM、中文车间看图生态、学术自动出图、本机资产只读参考  

---

## 目录

1. 执行摘要  
2. 调研全景与采纳/拒绝表  
3. 精度铁律与误差预算  
4. 总体架构  
5. 真源与交付数据规范  
6. 链路 A：2.5D 腔体/波导/滤波器  
7. 链路 B：复杂曲面 3D  
8. 链路 C：PCB/介质板  
9. 工具栈（含 Parasolid/STEP 策略、国产 CAD）  
10. 导出清洗 SOP  
11. 线段闭合与几何修复  
12. 自动标注与工艺规则库  
13. 西夏科技适配包  
14. 标准与公差全表  
15. 加工工艺与图纸工艺标注（含 WEDM/铣）  
16. 精度审计门禁  
17. 金样验收方法  
18. 车间看图与 CAM 消费路径  
19. 分期实施计划  
20. 未来软件模块设计（描述性）  
21. 风险登记册  
22. DoD 与不做清单  
23. 附录：证据等级、API 速查、图注模板、参考源  

---

## 1. 执行摘要

### 1.1 问题

HFSS 定稿后进 CAD 出加工图：线段要手连、标注要手补；**几何/尺寸一旦偏离仿真，电性能报废**。

### 1.2 目标

| 目标 | 指标 |
|------|------|
| 几何保真 | 关键 RF 尺寸与 HFSS **偏差 = 0**（软件阈值 1e-6 mm） |
| 标注 | 腔体族人工标注量 **−70%** |
| 线段 | 自动闭合；位移 **>1e-4 mm 停线** |
| 交付 | **双格式 3D（x_t+STEP）** + DXF + 尺寸表 + PDF + 审计报告 |
| 回溯 | 任意关键数字 → HFSS 变量名或标准号 |

### 1.3 一句话

> **双真源（HFSS 变量 + 清洗 B-rep）→ 双格式导出（Parasolid .x_t + STEP AP214）→ OCCT 审计门禁 → ezdxf 参数化标注 → 2D PDF 为合同、STEP/x_t 给 CAM。**

### 1.4 核心结论（全部调研后）

1. **无**「HFSS 一键完美加工图」产品；必须工程集成。  
2. **从导入 STEP 量尺寸 = 报废主因**；标注只认 `dims.json`。  
3. **WR-90 = BJ100 = 22.86×10.16**（BJ84=WR-112）。  
4. 中国精密 CNC：**2D 图仍是合同**；自动标注只是草稿。  
5. 交付 **同时给 `.x_t` + `STEP AP214`**：NX/内核用 x_t，CAXA/Mastercam 类用 STEP。  
6. **禁 STL/IGES** 作加工真源。  
7. iris 薄片优先 **慢走丝 WEDM**，图纸必须标工艺/最小 R/基准。  

---

## 2. 调研全景与采纳/拒绝

### 2.1 西夏科技（首选厂）

| 项 | 结论 |
|----|------|
| 能力 | 波导/天线/微波腔体/太赫兹/金属 CNC；WR90 焊接法兰 |
| 客户 | 电科、华为、成电、东南、航天、中科院、泰格微波 |
| 公开规范 | **无详细公差表** |
| 策略 | 行业精密微波规则 v0 + 金样书面确认 |

### 2.2 采纳总表（含本轮新增）

| 来源 | 关键事实 | 采纳 |
|------|----------|------|
| PyAEDT export_3d_model | STEP/SAT/…、自动去 Region、assignment 白名单 | 主导出 |
| PyAEDT import_3d_cad / heal_objects | healing、tol、HealObject 全参数 | 确定性修复 |
| AEDT kernel_converter | **官方 x_t 往返** | **x_t 首选之一** |
| Mastercam/PowerMill 中国车间 | 习惯 **STEP AP214** | **必发 STEP** |
| UG/NX CAM | 原生 Parasolid | **必发 x_t** |
| CAXA/ZWCAD/浩辰 | 2D 强、自动标注弱；COM/LISP 填标题栏 | DXF→人审；COM 只填图框 |
| ezdxf | 公差 DIMSTYLE、闭环 LWPOLYLINE、GB 字体 | 2D 主工具 |
| FreeCAD Path + ocp-freecad-cam | 2.5D 刀路研究可用 | 可选 CAM 原型 |
| OCCT 布尔体积 | 验收级对比 | 审计 A 级 |
| WEDM vs 铣 | 薄 iris/尖角/高筋→线切割 | 工艺标注 |
| 浩辰看图王/Sview/3D阅阅/大腾 | 车间看 STEP | 交付兼容 |
| QIF 3.0 / ISO 23952 | 数字检验 | 远期 |
| 学术 OmniMech 等 | 自动出图≠免人审 | 不迷信全自动 |
| 中文 DXF 实践 | XOY→DXF→标注 | 与 STEP 双轨 |
| 本机 layout_interchange / fab_profiles | IPC/ODB 门禁、provenance | 只读借鉴模式 |

### 2.3 拒绝

| 拒绝 | 原因 |
|------|------|
| 买 CADfix/CADIQ 作硬依赖 | 过重 |
| SpaceClaim 强制 | 许可/GUI |
| STL/IGES 加工源 | 网格/样条退化 |
| 大容差自动连线 | 几何漂移 |
| STEP 测量回填标注 | 丢意图+浮点 |
| 仅 MBD 不出 2D | 中国车间不接受 |
| CAXA API 全自动 GD&T | 能力不足 |
| 期望 OSS 一键 STEP→ISO 全标注图 | 不存在成熟产品 |
| openEMS 当 CAD 源 | 非几何工厂 |

---

## 3. 精度铁律与误差预算

### 3.1 双真源

| 代号 | 内容 | 形式 |
|------|------|------|
| T1 | HFSS 设计变量 | `dims.json` |
| T2 | 清洗后 B-rep | `part.x_t` + `part.step` |

### 3.2 误差预算

| 环节 | 允许 | 相对 ±0.02 工艺 |
|------|------|-----------------|
| 变量→标注 | **0** | — |
| 导出 B-rep | ≤1e-6 mm | 1/20000 |
| 接缝吸附 | ≤1e-4 mm | 1/200 |
| 审计 | 1e-6 mm | 1/20000 |
| **软件合计** | **≪0.001 mm** | **≥20× 裕度** |

### 3.3 单位/坐标

- **mm** 钉死；禁止 Auto 作生产默认  
- 文件名带 `_mm`；manifest 记 WCS  
- 陷阱：ODB `$idx`=µm  

### 3.4 自动化白名单

删非零件 / 厚化薄片 / ≤1e-4 吸附并记日志 / 投影出图 / **变量写入标注**  

---

## 4. 总体架构

```text
HFSS 参数化（电性能真源）
        │
        ▼
S1 清洗（去 Region/端口/空气盒；sheet→实体；unite）
        │
        ▼
S2 双格式导出 + dims.json + manifest
   ① part.x_t   ② part.step(AP214)  ③ faces/*.dxf
        │
        ▼
S3 AuditGate（OCCT）FAIL=停线
   变量/bbox/布尔体积/BRepCheck/闭合/单位/标注一致
        │
        ▼
S4 DrawEngine（ezdxf）
   视图 + 参数标注 + 孔表 + 工艺标注(WEDM/铣) + 图框
        │
        ▼
S5 交付包（2D PDF=合同）
   x_t + step + dxf + pdf + dims + critical_chars + audit
        │
   ┌────┴────┬──────────┐
   ▼         ▼          ▼
 西夏 CNC  其他厂家   PCB(IPC旁路)
```

---

## 5. 真源与交付数据规范

### 5.1 目录

```text
fab_<part>_<rev>_<date>/
├── manifest.json
├── part.x_t              # NX/内核/SpaceClaim
├── part.step             # Mastercam/CAXA/通用（AP214）
├── faces/*.dxf           # 2.5D 刀路轮廓（闭合）
├── dims.json
├── critical_chars.csv
├── drawing.pdf           # 合同图纸
├── drawing.dxf
├── drawing_notes.txt
├── audit_report.{json,md}
└── optional/ (3dpdf, bom, cam_notes)
```

### 5.2 dims.json（契约要点）

- `units: "mm"`  
- `variables[]`: name, raw, value, role(rf_critical|assembly|free), tol_class, drawing_label, standard_ref  
- `derived[]`: 标准库派生（法兰孔系等）  
- `hfss` 指纹 + `wcs`  

### 5.3 critical_chars.csv

char_id, feature, nominal, tol±, datum, source_var, meas_method, inspect_pct  

### 5.4 DXF 图层

OUT / POCKET / HOLE / ENGRAVE / CENTER / DIM / TEXT  
轮廓 **LWPOLYLINE close=True**；弧用 bulge；标注 ezdxf+公差；GB 字体声明  

---

## 6. 链路 A：2.5D 腔体/波导/滤波器（主战场）

### 6.1 特征→公差→工艺→图纸标注

| 特征 | 公差 | Ra | 工艺标注 | 标注来源 |
|------|------|-----|----------|----------|
| 内腔 a,b | ±0.02~0.05 | ≤0.8 | 3轴精铣 | 变量/WR |
| iris/耦合窗 | **±0.01~0.02** | 0.4~0.8 | **WEDM** 或小刀+清角 | 变量 |
| 腔高/谐振长 | ±0.02~0.05 | 0.8 | 铣 | 变量 |
| 销孔 | H7 | 1.6 | 钻铰 | 标准 |
| 螺纹 | 6H | — | 攻丝 | 变量表 |
| 外形 | 1804-m | 3.2 | 铣 | 变量 |
| 法兰面 | 平面度 0.02~0.03 | 0.8 | 磨/精铣 | 标准 |

### 6.2 iris / 深腔 CAM 友好标注（新增）

1. 特征旁注 **「线切割 WEDM」** 或 **「3轴铣」**  
2. 最小内圆角：**允许 EDM 最小 R** 或「尖角」  
3. 筋/壁厚、平行度  
4. **相对型腔基准 A/B/C 的位置**（禁止只标外轮廓）  
5. 深窄槽：注明可穿丝/预钻孔  
6. 薄壁警示  

### 6.3 默认技术要求（图框文本）

1. 未注线性 **GB/T 1804-m**；未注形位 **GB/T 1184-K**  
2. 波导 a、b 关键；内壁 Ra≤0.8，无刀痕毛刺翻边  
3. iris 公差见表；倒钝 **≤0.1×45°**  
4. 法兰面平面度 0.03；销孔 H7  
5. 铝导电氧化 / 铜镀银 5μm（高 Q 5–8），**镀后不堵 iris**  
6. 去毛刺清洗无油  
7. **镀前全尺寸检验**，重要件镀后复测内腔  

---

## 7. 链路 B：复杂曲面

- 主交付 x_t + STEP AP214  
- 2D：包络、接口、壁厚、截面  
- 审计：布尔体积 + 采样点  
- PMI 仅在 CAD 侧补  

---

## 8. 链路 C：PCB

- PyEDB IPC-2581/ODB++/Gerber；µm 陷阱  
- 与机加包隔离  
- 可借鉴 fab_profiles 的 provenance 标注模式  

---

## 9. 工具栈

### 9.1 3D 交换策略（关键）

| 消费者 | 首选 | 说明 |
|--------|------|------|
| UG/NX、SpaceClaim | **.x_t** | 内核原生 |
| Mastercam / PowerMill / Fusion | **STEP AP214** | 中国车间通用 |
| CAXA 制造工程师 | STEP + DXF | 无原生 Parasolid |
| 高端带 PMI | STEP AP242 | 仅当对方读 PMI |

**结论：每个零件双发 x_t + STEP AP214，单位 mm。**

### 9.2 解析面保真

- 保持平面/圆柱/圆解析面；禁止 IGES（易变 NURBS）  
- 激进 stitch/merge 会破坏 CAM/探针  

### 9.3 2D / 国产 CAD

| 环节 | 做法 |
|------|------|
| 生成 | **ezdxf** 写全图（视图+尺寸+公差+GB 图框） |
| 打开 | CAXA / 中望 / 浩辰 / AutoCAD 人审 |
| 自动化 | COM/LISP **只填标题栏属性**（图号/材料/比例/日期） |
| 不做 | 指望 CAXA/ZWCAD 自动全 GD&T |

### 9.4 重建 vs 搬运

| 搬运 x_t/STEP | 参数重建 |
|---------------|----------|
| 保精确面 | 家族件/要改参 |
| 大曲面 | 特征级标注 |

重建后必须布尔体积门；禁止「为了干净」改供应商精确面。

### 9.5 CAM 研究栈（可选）

FreeCAD Path + ocp-freecad-cam + opencamlib；**无** CAMWorks 级 OSS AFR。  
实用路径：2.5D 特征提取（腔/孔/槽）+ 模板工序，不是全自动工艺。

---

## 10. 导出清洗 SOP

1. 锁变量快照 → dims.json  
2. 记 WCS/单位  
3. 列 object_names  
4. 剔除 Region/SubRegion/空气盒/PML  
5. 剔除端口/集总/理想边界面  
6. sheet **厚化**（设计厚度）  
7. 共面重叠 unite + 校验（禁只共边）  
8. 腔内倒角 ≤0.1×45°  
9. 导出前断言：无 sheet/Region、实体数=预期  
10. `export_3d_model` **x_t 与 step 各一**，assignment 白名单  
11. B-rep 投影 → 闭合 DXF  
12. 写 manifest/chars  
13. AuditGate  

导入若必须：`input_file_unit="mm"`；heal 用 `heal_objects` 钉 `max_stitch_tolerance=0.001` 并记 heal_log。

---

## 11. 线段闭合与修复

| 根因 | 正确 | 错误 |
|------|------|------|
| 零厚度 sheet | HFSS 厚化 | CAD 补面 |
| 共边 | 重叠 unite | 目测连 |
| 导出缝 | heal 0.001~0.01 | 0.1 乱吸附 |
| 投影碎段 | 一次投影 | 描图 |

接缝：`gap≤1e-4 mm` 才 snap 并 log；否则 FAIL。

---

## 12. 自动标注与规则库

```text
dims.json → tol_class → ezdxf DIMENSION + set_tolerance
         → critical_chars.csv
         → drawing_notes.txt
         → 工艺标签（WEDM/铣/镀）
```

| tol_class | 默认 |
|-----------|------|
| IRIS | ±0.02 |
| WG_AB | ±0.03 |
| CAV_H | ±0.03 |
| PIN_H7 | H7 |
| FLAT_FLANGE | 0.03 |
| THD | 6H |
| FREE | 1804-m |
| THz | 再紧 30–50% |

关键尺寸后缀 `(变量名)`；禁止手改不回写 HFSS。

---

## 13. 西夏适配包

### 13.1 产品映射

波导→A+法兰库；腔体/滤波器→A iris 加密；太赫兹→A/B 公差收紧；喇叭→B；机箱→A；PCB→C。

### 13.2 书面确认清单

1. 公差表认可？  
2. 格式：**x_t+step+pdf**？要 dwg？  
3. 法兰：UG-39 / FBP100 / CPR-90G？  
4. 图框模板  
5. 镀前/镀后检  
6. 变更只认 dims/HFSS  
7. **设备能力确认**（西夏公开：铣削中心 29、数车 17、走芯 7、**线切割 6**）— iris 走 WEDM 是否本厂  
8. 质量体系：ISO9001 + **GJB/国军标**（军工件另附检验规范）  

---

## 13A. 射频精密加工厂家调研（补充数据）

### 13A.1 国内厂家

| 厂家 | 地点 | 能力/产品 | 公开公差/Ra | 期望交付 | 备注 |
|------|------|-----------|------------|----------|------|
| **成都西夏科技**（首选） | 成华龙潭 | 波导/腔体/太赫兹/天线/定制 CNC；**29 铣+17 车+7 走芯+6 WEDM** | 官网未发表 | **来图/来样** 2D+3D | ISO9001+GJB；电科/华为/成电客户 |
| 成都泰格微波 | 成都 | 军民用微波器件组件（含内部机加） | 极少公开 | GB 2D+装配图 | 西夏合作方；非纯外协店 |
| 成都赛英 SINE | 龙潭（近西夏） | 雷达/微波混合集成/≤110GHz | 极少 | NDA 图纸包 | 系统级；非公开 job-shop |
| **嘉立创 CNC** | 深圳全国 | 3/4/5 轴、车铣；非专营 RF | **有公开表**（见下） | STEP+2D 在线报价 | 适合结构件/铝壳；RF 腔谨慎 |
| 华秋 HQ | 深圳 | **PCB 为主** | PCB 能力公开 | Gerber | 金属腔体非主线 |
| 中电科系/西安 | 各地 | 整机组件 | GJB 极少公开 | 军工图包+检验 | 多需保密资质 |

**成都龙潭** = 西夏+赛英等 RF 机加聚集地，适合同批 RFQ。

**嘉立创公开配合/表处（可写进规则库参考，非 RF 专属）：**

| 配合类型 | 公差带 (mm) |
|----------|-------------|
| 压入过盈 | −0.01～−0.02 |
| 定位 | 0～0.01 |
| 插接 | 0.02～0.05 |
| 普通装配 | 0.05～0.10 |
| 滑动/大件 | 0.05～0.20 |

表处单边：阳极 0.005–0.008；硬氧 0.02–0.04；喷漆 0.03–0.10 mm。  
螺纹：**有效牙深+底孔（牙深+3～5 螺距）+6H** 必须在图上写明。

### 13A.2 国际厂家（DFM 标杆）

| 厂家 | 定位 | 公开能力 | 图纸/交付实践 | 可借鉴 |
|------|------|----------|---------------|--------|
| **QuinStar**（美） | 波导 18–220GHz、腔体滤波 | **MIL-DTL-85/3**；CNC+EDM+镀 | **手绘可询价；2D CAD 缩短 LT；3D 最快**；build-to-print | **双文件交付**；视频检验弯扭 |
| **Eravant**（美，原 SAGE） | mmWave～330GHz + 定制 | AS9100D/ISO9001/ITAR/洁净室 | 定制+量产；PDF+3D | 质量/保密条款模板 |
| **Flann**（英） | 精密波导至 1.1THz | ISO9001；**3/4 轴 CNC**；成形弯曲；铜铝钎焊；电/化学镀；**电铸** | **Build-to-print** + 自研（HFSS/Mician/Inventor） | 工艺链完整度对标 |
| **Precision Micro**（英） | 光化学蚀刻薄片 | **公开全表**：t 0.01–0.1→±0.025；0.25–2.5→±10%t；最小孔/槽 | 技术指南 PDF | **能力表模板**；蚀刻 DFM |
| **Rosenberger CNC**（德） | 定制精密件 | 21 车/14 铣（含五轴） | 「图→成品」 | 产线能力清单制 |
| **SPINNER**（德） | 连接器/校准至 250GHz | 配合面计量 | 产品手册 PDF | 扭矩/量规纪律 |
| Fairview/Pasternack | 目录 COTS | 目录规格 | 现货+定制 RFQ | 区分 COTS vs 机加 |
| Millitech/Maury | 系统/校准 | — | 本会话站点受限 | 名录保留 |

### 13A.3 跨厂家共性（写入规则库）

1. **来图加工**是默认商业形态——**图纸必须自己带全公差/表处/螺纹**  
2. RF 机加几乎不公开 Ra/tol 数字表 → 我们的 `critical_chars` + 图注是唯一合同语言  
3. **3D+2D 双文件**可缩短交期（QuinStar 明文）  
4. 标准要写在图面：法兰（MIL-DTL-85/3 / UG-xx / GB）、材料（6061/Cu/银/可伐）、镀层  
5. RF GD&T：内腔 a/b、法兰共面、销孔位置度、内壁 Ra；注明检验方法（CMM/影像/气动）  
6. 质量块：ISO9001；军工 GJB；出口 AS9100/ITAR 另册  
7. 薄片蚀刻件单独附 **PCM DFM**（Precision Micro 模式）  

### 13A.4 对方案交付包的增补要求

| 增补 | 来源 |
|------|------|
| 螺纹：有效牙深+底孔+6H | JLC |
| 表处厚度单边补偿 | JLC |
| 图面写标准号（法兰/MIL） | QuinStar/Flann |
| 检验方法栏 | QuinStar |
| Build-to-print 封面（零件号/Rev/数量/材料/表处） | Flann/行业 |
| 能力表附件（可选） | Precision Micro |

---

## 14. 标准与公差全表

### 14.1 波导

| 型号 | a×b | 备注 |
|------|-----|------|
| **WR-90 / BJ100** | **22.86×10.16** | X |
| WR-112 / BJ84 | 28.499×12.624 | 勿混 |

误差 <0.05 mm（模式纯度）；夹具例 (−0.15~−0.05)；MIL-W-85 / GB/T 11450。

### 14.2 法兰

UG-39/U、UG-84/U、CMR-84/CPR-90G、FBP100、EIA-285-A、MIL-DTL-24211。  
**发图前用厂家既有法兰图核销距。**

### 14.3 制图

GB/T 4458；1804-m；1184-K；ASME Y14.5（出口）。

### 14.4 表面

铝导电氧化；镀银 3–5（高 Q 5–8）μm；内腔 ≤0.1×45° 倒钝；无毛刺。

---

## 15. 工艺标注深化（新增）

| 工序 | 图纸应注 |
|------|----------|
| 3轴 2.5D | 型腔、垂直度、精加工余量 0.1–0.2 |
| WEDM | 「线切割」、穿丝孔、最小 R、薄筋 |
| 电火花清角 | 根 R |
| 调谐螺钉 | 行程、密封面 |
| 检验 | CMM 基准与图纸一致；镀前/后 |

---

## 16. 精度审计门禁

| ID | 检查 | 阈值 |
|----|------|------|
| A1 | 变量闭合 | 0 |
| A2 | bbox | 1e-6 mm |
| A3 | 体积/重心 | 1e-9 rel / 1e-6 abs |
| A4 | 布尔 Cut 体积 | ≈0 |
| A5 | BRepCheck | 无错 |
| A6 | 关键 RF 尺寸 | 1e-6 mm |
| A7 | DXF 闭合 | 全闭合 |
| A8 | 接缝 log | ≤1e-4 |
| A9 | 单位指纹 | mm |
| A10 | 标注↔dims | 0 |
| A11 | 非零件残留 | 0 |
| A12 | 哈希 | 归档 |

**FAIL 禁止发图。** 网格 Hausdorff 仅初筛。

---

## 17. 金样验收

三份：HFSS 定稿 / 自动包 / 历史手修图。  
目标：关键尺寸 0 差；进 CAXA/SW 看补线/补标工作量；西夏试读图；通过再推广。

---

## 18. 车间看图与 CAM 消费

| 阶段 | 内容 |
|------|------|
| 合同 | **2D PDF**（+可选 DXF） |
| CAM | STEP AP214（或 x_t@NX） |
| 看图 | 浩辰看图王、Sview、UG 3D PDF、大腾 3D一览通 |
| 检验 | critical_chars；有 CMM 数字线可考虑 QIF |
| 文件名 | `零件_图号_Rev` 防混版 |

**不要**只丢 STEP 不给公差/基准/工艺。

---

## 19. 分期实施（未来，本轮不写码）

| 阶段 | 内容 | 验收 |
|------|------|------|
| P0 | 金样+西夏确认 | 纪要 |
| P1 | 清洗双格式导出+审计 | 几何 0 差 |
| P2 | ezdxf 自动图+工艺标注 | 标注 −70% |
| P3 | 厂家图框/CAD 适配 | 被接受 |
| P4 | 曲面/3D PDF | 接口正确 |
| P5 | PCB 规范化 | 隔离 |

---

## 20. 未来模块（描述）

`export_agent` / `dims_snapshot` / `face_dxf` / `audit_gate` / `draw_engine` / `rules_xixia` / `critical_chars` / `pack_deliverable`  

实现位置由用户届时指定；**本轮不写入任何项目仓**。

---

## 21. 风险登记

| ID | 风险 | 对策 |
|----|------|------|
| R1 | 连线改几何 | 1e-4+审计 |
| R2 | 单位错 | mm 合同 |
| R3 | STEP 量尺寸 | 只认 dims |
| R4 | WR/BJ 写错 | 锁 BJ100 |
| R5 | heal 过度 | 体积门 |
| R6 | 口头改关键尺寸 | 回写 HFSS |
| R7 | 标注碰撞 | 人审关键 |
| R8 | PCB 混图 | 隔离 |
| R9 | 字体缺 | 交付声明 |
| R10 | 全自动幻觉 | 人审 GD&T |
| R11 | 法兰孔距未核 | 对厂家图 |
| R12 | 仅 STEP 无工艺 | 交付清单强制 |

---

## 22. DoD 与不做

**DoD**：金样 0 差；A1–A12 PASS；双 3D+DXF+PDF+chars+notes；车间可读；可重复哈希；西夏书面接受；数字可回溯。  

**不做**：AI 猜尺寸；STL 真源；大容差连线；改关键尺寸不回写；仿真辅助对象进图；无审计出图；普通场景 MBD-only；CAXA 全自动 GD&T 幻想。

---

## 23. 附录

### 23.0 配套细则（必读）

见 **`HFSS到CAD加工_可落地细则.md`**：
- WR-90/BJ100 金样完整尺寸表（a/b/R1/A/B/T）与 dims.json 示例  
- GB/T 10609 标题栏字段、腔体四视图、ezdxf 代码模式  
- 导出清洗/审计伪代码、RFQ 勾选清单、公差规则 YAML 草稿  

### 23.1 证据等级

| 级 | 含义 |
|----|------|
| O | 官方/源码 |
| C | 社区/多篇一致 |
| K | 工程共识，合同前升 verified |

### 23.2 API 速查

PyAEDT：export_3d_model / import_3d_cad / heal_objects  
OCCT：BRepAlgoAPI_Cut、BRepGProp、BRepCheck_Analyzer  
ezdxf：add_lwpolyline(close=True)、add_*_dim、set_tolerance  

### 23.3 图注模板

见 §6.3。

### 23.4 参考源

m.xixiakeji.com；PyAEDT 文档与 pyaedt-main；OCCT/ezdxf/build123d/FreeCAD Path；GB/T 4458·1804·1184；MIL-W-85；UG-39/FBP100；QIF/ISO 23952；arXiv 自动出图系列；中文工程帖；Sview/浩辰/大腾等看图生态。  

### 23.5 本轮边界

- **只调研、只写桌面文档**  
- rf_workspace 未保留任何创建物（worktree/分支已删净）  
- 部分 CAM 偏好/CAXA API 细节为 **[K]**，实施前向厂家/厂商文档升 verified  

---

**完（v3.1）**  
相对 v3.0 新增：国内外射频精密机加厂家目录（西夏设备/嘉立创公差表/QuinStar 交期规则/Flann 工艺链/Precision Micro 能力表）、跨厂家共性、交付包增补（螺纹牙深底孔、标准号上图、检验方法栏、build-to-print 封面）。
