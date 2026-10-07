> 【归档注记】T48（2026-09-29）自用户桌面归档入仓。来源=用户桌面 fab-export 方案母本（吸收前调研稿）；归档日期=2026-09-29；对应实现 commit=7ed656d（T43 吸收批：src/rfauto/{core,adapters}/fab_export + service/fab_export_service + cli/fab_app）。**内部资料：本文档含厂家联系方式与商务口径，不入公开仓——release/发布前按 release/RELEASE_GUIDE.md §5 三层审查剔除或改写**。（本文档 §H 含厂家电话/QQ/邮箱/地址，公开发布前必须整节剔除） 正文自本行以下零改写。

# 调研原始附录（v3.0 支撑）

**配套**：`HFSS到CAD加工图纸自动化方案.md`  
**边界**：只读调研；未修改任何项目仓库。

---

## A. 派生结论速记（实现时优先）

1. **双格式必发**：`part.x_t`（NX/内核）+ `part.step AP214`（Mastercam/CAXA）。  
2. **2D PDF = 合同**；STEP 给 CAM 不够装公差。  
3. **WR-90 = BJ100 = 22.86×10.16**；BJ84=WR-112。  
4. 自动标注只认 `dims.json`，禁止 STEP 测量回填。  
5. iris：图纸标 **WEDM**、最小 R、相对型腔基准。  
6. 国产 CAD API 只适合 **填标题栏**，不指望自动 GD&T。  
7. 精度门用 **布尔体积**，不用网格距离当验收。  

---

## B. 双格式与内核

| 事实 | 来源级 |
|------|--------|
| AEDT kernel_converter = **x_t 往返** | O |
| NX/Siemens 内核 = Parasolid | O |
| 中国 CAM 多吃 STEP AP214 | K |
| CAXA 无原生 Parasolid | K |
| IGES 易 NURBS 化 / STL 网格 | O/K |
| OCCT STEP：AP203/214 强，AP242 部分 | O |

---

## C. 国产 CAD 自动化

| 产品 | 自动化 | 适合 |
|------|--------|------|
| CAXA 电子图板 | COM/OLE、模板 | GB 图框、填属性 |
| 中望 ZWCAD | ZRX/.NET/LISP | 同上 |
| 浩辰 GstarCAD | GRX/COM/LISP | 同上 |
| **ezdxf** | 纯 Python | **出图主力** |

Auto-dim：即使 SW DimXpert / NX PMI 也只是草稿（O）。

---

## D. CAM / 特征识别 / EDM

| 项 | 结论 |
|----|------|
| OSS AFR | 无 CAMWorks 级；BrepMFR 等仅研究 |
| FreeCAD Path | 最完整免费 2.5D |
| ocp-freecad-cam | CQ/build123d→Path，实验性 |
| opencamlib / CAMotics | 刀路算法/仿真 |
| 车间要的不只是几何 | 基准、公差、毛坯、装夹、工艺 |
| 薄 iris / 尖角 / 高筋 | **WEDM ±0.01 级** |
| 图纸助力 CAM | 工艺标签、最小 R、厚度、型腔基准、穿丝孔 |

---

## E. 车间看图

- 浩辰 CAD 看图王、Sview、UG 3D PDF、大腾 3D一览通、3D阅阅  
- 交付文件名含 **零件+图号+Rev**  
- 无公差 STEP → 已知报废源（原点/单位/版本/缺剖视）  

---

## F. 失败模式清单（STEP 重标注）

1. 原点/单位错  
2. 丢基准 → CMM 对不上  
3. 无公差/粗糙度/镀层/螺纹  
4. 缺深腔剖视  
5. Rev 混版  
6. 薄壁深槽 DFM 不可见  

---

## G. 既有研究汇总索引

| 轮次 | 主题 | 要点 |
|------|------|------|
| 1 | PyAEDT 源码 | export/heal/kernel x_t |
| 1 | OCCT/ezdxf/CQ/b123d | 出图与审计 |
| 1 | 波导/法兰/GB | 公差表 |
| 1 | MBD/QIF/CAM | 2D 合同现实 |
| 1 | 同类项目 | 采纳/拒绝 |
| 2 | Parasolid vs STEP | **双格式** |
| 2 | 国产 CAD | 填表不填 GD&T |
| 2 | AFR/EDM/看图 | 工艺标注与消费 |

---

## H. 西夏公开信息

成都西夏科技发展有限公司；028-84215383 / 13308037317；成华区龙潭成致路24号附2号；762861137@qq.com；波导/天线/腔体/太赫兹/CNC；官网无公开图纸规范。

---

## I. 工具与证据备注

- 主代理 playwright + 真 UA 访问官网/搜索  
- 部分子代理无 bash/Browser Use，结论标 [O]/[C]/[K]  
- 合同相关公差必须升级 verified  

---

## J. 射频加工厂家调研（v3.1 增）

### J.1 国内

| 厂家 | 要点 | 级 |
|------|------|-----|
| 西夏科技 | 龙潭；波导腔体 THz；29 铣/17 车/7 走芯/6 WEDM；ISO+GJB；来图来样 | O+C |
| 泰格微波 | 成都军民用微波；与西夏合作 | C |
| 赛英 SINE | 龙潭；雷达/≤110GHz；非公开 job-shop | C |
| 嘉立创 CNC | 公开配合公差与表处厚度；STEP+2D；非 RF 专营 | O |
| 华秋 | PCB 主线 | O |
| 中电科系 | GJB；保密；公开 tol 少 | K |

### J.2 国际

| 厂家 | 要点 | 级 |
|------|------|-----|
| QuinStar | 3D=最快 LT；2D 优于手绘；MIL-DTL-85/3；CNC+EDM | O |
| Eravant | 原 SAGE；AS9100D/ITAR/洁净室；至 330GHz | O |
| Flann | 1.1THz；3/4 轴；钎焊/镀/电铸；HFSS+build-to-print | O |
| Precision Micro | 蚀刻公差全表；DFM 指南 PDF | O |
| Rosenberger | 「图→成品」；五轴车铣清单 | O |
| SPINNER | 配合计量；至 250GHz | O |
| Fairview/Pasternack | COTS 目录 | O |
| Millitech/Maury | 本会话站点受限 | K |

### J.3 采纳到交付包

1. 双文件 3D+2D（交期）  
2. 图面标准号/材料/镀层/螺纹牙深底孔  
3. 检验方法栏  
4. Build-to-print 封面字段  
5. 薄片 PCM 附则（若需要）  
6. 质量体系块（ISO/GJB/AS9100）  

---

*附录完。*
