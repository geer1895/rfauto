> 【归档注记】T48（2026-09-29）自用户桌面归档入仓。来源=用户桌面 fab-export 方案母本（吸收前调研稿）；归档日期=2026-09-29；对应实现 commit=7ed656d（T43 吸收批：src/rfauto/{core,adapters}/fab_export + service/fab_export_service + cli/fab_app）。**内部资料：本文档含厂家联系方式与商务口径，不入公开仓——release/发布前按 release/RELEASE_GUIDE.md §5 三层审查剔除或改写**。（本文档含厂家选型与商务确认口径） 正文自本行以下零改写。

# 可落地细则：金样 / 规则草稿 / RFQ / 出图模板

**版本**：v1.0（配套主方案 v3.1）  
**边界**：只写桌面文档；不修改任何项目仓库  
**用途**：把主方案落到「能直接照着做」的字段、数字、代码模式、清单

---

## 1. 金样零件：WR-90 / BJ100 直波导段 + FBP100 法兰

### 1.1 标准几何（RFTOP 频优微波波导标准页，verified-web）

| 代号 | 名义 | 单位 | 角色 | tol_class |
|------|------|------|------|-----------|
| **a** | **22.86** | mm | 内截面宽（RF 关键） | WG_AB ±0.03 |
| **b** | **10.16** | mm | 内截面高（RF 关键） | WG_AB ±0.03 |
| R1 | 0.8 | mm | 内圆角 | FREE ±0.1 |
| A | 25.4 | mm | 外截面宽 | FREE ±0.1 |
| B | 12.7 | mm | 外截面高 | FREE ±0.1 |
| R2 | 0.65–1.15 | mm | 外圆角 | FREE |
| T | 1.27 | mm | 壁厚（管材） | FREE ±0.1 |

频段：8.2–12.5 GHz（X）；TE10 λc=45.72 mm，fc=6.557 GHz。  
重量：铝 0.244 kg/m；铜 0.804 kg/m。

**配套法兰（同页）：** FBP100 方形平法兰、FBM100 密封、FBE100 扼流、FDP100/FDM100 矩形。  
产品示例（扭波导）：**FBP100(UBR100)**；主体铝+灰色漆，内腔酸洗。

### 1.1b UG-39/U 与 Kerr 设计规则（金样补充）

| 项 | 数值 | 证据 |
|----|------|------|
| 法兰外廓（UG-39 类） | 约 **30×30** mm，厚 **6.0** | [K] 对照 MIL/TD-00077 冻结前核 |
| 螺栓孔 4× | **Ø3.2**，方阵 **25.4×25.4** | [K] |
| 销孔 2× | **Ø2.5 H7**，宽边两侧，间距 **25.4** | [K] |
| 法兰平面度 | **0.02** | [K] |
| 法兰对轴线垂直度 | 0.05/100 | [K] |
| 干涉密封 | 干接触；气密才用扼流/O 圈槽 | [K] |

**Kerr/NRAO 40 dB 回波经验规则（实现/设计对照）：**
- 线性尺寸公差 **0.5% 名义**（优先 ±0.02～0.05）  
- 内角 **R ≤ 10%·a**（WR-90 则 ≤2.3，常用 ≤0.5）  
- 法兰错位 **<3% 线性 / <6°**  

**权威冻结 PDF（待本地抽文本钉死孔系）：**  
`microwaves101.com/uploads/TD-00036X-Ulis-waveguide-list.pdf`、`TD-00077L-Simones-flange-list.pdf`

### 1.1c CMM 检验特性清单（腔体/波导）

1. 内腔 a、b（多截面）  
2. 内角 R  
3. 壁厚/外廓  
4. 各腔长 L1…Ln / iris 节距  
5. iris 厚、开口宽高  
6. 调谐孔位置/孔径/深度  
7. 法兰外廓+厚度  
8. 4 螺栓孔 Ø 与位置度  
9. 销孔 Ø/位置  
10. 法兰平面度、对轴垂直  
11. 法兰与波导同轴度  
12. 壁直线度/平行度  
13. 总长 L  
14. （可选）Ra 轮廓

### 1.2 金样 dims.json 示例（可直接改）

```json
{
  "$schema": "fab-dims-1.0",
  "part_id": "wg_straight_wr90_001",
  "rev": "A",
  "units": "mm",
  "source": "hfss",
  "hfss": {
    "project": "wg_straight.aedt",
    "design": "HFSSDesign1",
    "aedt_version": "2026.1"
  },
  "wcs": {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]},
  "variables": [
    {"name": "a", "raw": "22.86mm", "value": 22.86, "role": "rf_critical", "tol_class": "WG_AB", "drawing_label": "内腔宽边 a", "standard_ref": "WR-90/BJ100"},
    {"name": "b", "raw": "10.16mm", "value": 10.16, "role": "rf_critical", "tol_class": "WG_AB", "drawing_label": "内腔窄边 b", "standard_ref": "WR-90/BJ100"},
    {"name": "L", "raw": "60mm", "value": 60.0, "role": "assembly", "tol_class": "FREE", "drawing_label": "总长"},
    {"name": "wall", "raw": "1.27mm", "value": 1.27, "role": "free", "tol_class": "FREE", "drawing_label": "壁厚"}
  ],
  "derived": [
    {"name": "A_outer", "value": 25.4, "from": ["std:WR90"], "role": "free"},
    {"name": "B_outer", "value": 12.7, "from": ["std:WR90"], "role": "free"},
    {"name": "flange", "value": "FBP100", "from": ["std:FBP100"], "role": "assembly"}
  ]
}
```

### 1.3 critical_chars.csv 示例

```csv
char_id,feature,nominal,tol_plus,tol_minus,datum,source_var,meas_method,inspect_pct
CH-001,内腔宽a,22.86,0.03,0.03,A,a,三坐标/影像,100
CH-002,内腔高b,10.16,0.03,0.03,A,b,三坐标/影像,100
CH-003,内腔长度,60,0.05,0.05,A,L,卡尺,100
CH-004,法兰平面度,,0.03,0,A,,,50
```

**补充公差策略（Kerr）：** a/b 优先 **±0.02**（可严于默认 ±0.03）；总长 ±0.1；孔位 ±0.05；内角 R max 0.5。

### 1.4 金样图注（可粘贴）

1. 未注线性公差 GB/T 1804-m；未注形位 GB/T 1184-K。  
2. 内腔 a=22.86、b=10.16 为关键尺寸，公差 **±0.02～0.03**；内壁 Ra≤0.8，无刀痕、毛刺、翻边；内角 **R≤0.5**。  
3. 法兰 FBP100 或 UG-39 类；贴合面平面度 **0.02～0.03**；销孔 H7。  
4. 材料：铝合金；外表面灰色漆，内腔酸洗（或导电氧化）。  
5. 去毛刺、清洗、无油；镀/涂后不得堵内腔。  
6. 未注棱边倒钝 ≤0.1×45°。  

---

## 2. 图框与视图（GB）

### 2.1 标题栏最小字段（GB/T 10609.1）

| 区 | 字段 |
|----|------|
| 代号 | **图样代号**、**图样名称**、单位名称 |
| 签名 | **设计 / 工艺 / 审核 / 批准**（签名+年月日） |
| 属性 | **材料标记**、**阶段标记**、**重量**、**比例**、**共_张 第_张** |
| 更改（重要件） | 标记 / 处数 / 分区 / 更改文件号 / 签名 / 年月日 |

图幅：GB/T 14689；标题栏右下角；简化约 180×56 mm。

### 2.2 棱柱腔体最小视图集

1. **主视图**：开口面/腔体轮廓、总长宽、孔系、端口面  
2. **俯视图**：深度/高度、iris 排布、调谐螺钉轴  
3. **全剖 A-A**（阶梯剖过 iris）：腔高、iris 厚/高、壁厚  
4. **局部放大 I（iris）**：宽 w、厚 t、圆角 R、公差  
5. 可选侧视/剖 B-B；轴测图仅作辅助  

---

## 3. ezdxf 出图模式（实现时照抄）

### 3.1 样式与尺寸

```python
import ezdxf
doc = ezdxf.new("R2010", setup=True)  # 公差需 R2000+
msp = doc.modelspace()
doc.styles.add("GB", font="gbenor.shx", bigfont="gbcbig.shx")

dim = msp.add_linear_dim(base=(30, 25), p1=(0, 0), p2=(30, 0),
    override={"dimtxsty": "GB", "dimtxt": 3.5, "dimdec": 2})
dim.set_tolerance(upper=0.05, lower=0.02, hfactor=0.6, dec=2)
dim.render()   # 必须 render，否则 CAD 里空标注
```

- 配合代号：`text="22.86±0.03"` 或 `text="∅8H7"`  
- 字高：A3/A2 约 3.5 mm  

### 3.2 图层

| 层 | ACI | 用途 | 线宽 |
|----|-----|------|------|
| 粗实线-VISIBLE | 7 | 可见轮廓 | 0.5 |
| 细实线-DIM | 2/7 | 尺寸/剖面线 | 0.25 |
| 虚线-HIDDEN | 3 | 不可见 | 0.25 |
| 点画线-CENTER | 1 | 中心线 | 0.25 |
| 文字-TEXT | 4 | 技术要求 | 0.25 |
| 图框-FRAME | 7 | 图框标题栏 | 0.5 |

### 3.3 DXF→PDF

- `ezdxf draw in.dxf --out out.pdf`  
- 或 `pymupdf.PyMuPdfBackend` + `Page(297,210,mm)`  
- **ODA Converter 不能出 PDF**  

---

## 4. 导出清洗伪代码（pyAEDT，实现时展开）

```text
1. snap = read_all_design_variables()          # raw 字符串保留
2. manifest.wcs = get_wcs(); units="mm"
3. objs = object_names
4. drop = Region | SubRegion | air* | vacuum | port_sheets | lumped_sheets
5. for sheet in sheets: thicken(thickness=design_var)
6. unite(coplanar overlapping solids); assert object_names
7. export_3d_model(x_t, assignment_to_export=solids)
8. export_3d_model(step, assignment_to_export=solids)
9. for face in machined_faces: project_wires → faces/*.dxf (closed)
10. write dims.json, critical_chars.csv
11. audit_gate(); if FAIL: stop (禁止出图)
12. draw_engine → drawing.pdf
```

**export 要点：**
- `assignment_to_export` 显式白名单  
- `assignment_to_remove=["Region","airbox",...]`  
- 双文件：`.x_t` + `.step`  

---

## 5. 审计门禁伪代码

```text
A1  dims.raw == hfss.variables
A2  |bbox_export - bbox_hfss| <= 1e-6
A3  |V_export - V_hfss| / V <= 1e-9  (or abs 1e-6 mm³)
A4  volume(Cut(A,B)) ≈ 0
A5  BRepCheck_Analyzer.ok
A6  critical dims == 0 err
A7  all DXF loops closed
A8  max(snap_log) <= 1e-4
A9  unit fingerprint mm
A10 drawing text == dims
A11 no Region/port/sheet in export set
A12 sha256(files)
→ FAIL ⇒ 不交付
```

---

## 6. RFQ 交付包清单（发给西夏前勾选）

### 6.1 文件

- [ ] `drawing.pdf`（2D 合同图，含图框/技术要求/公差）  
- [ ] `part.step`（AP214，mm）  
- [ ] `part.x_t`（可选，NX/内核）  
- [ ] `faces/*.dxf`（若厂家要 2.5D）  
- [ ] `critical_chars.csv`（检验表）  
- [ ] 数量 / 交期 / 材料 / 表处说明  

### 6.2 图面必须有

- [ ] 图号 + Rev  
- [ ] 材料标记  
- [ ] 表处（导电氧化/镀银厚度/漆）  
- [ ] 关键尺寸公差（iris、a、b）  
- [ ] 基准 A/B/C  
- [ ] 螺纹：规格+有效牙深+底孔+6H  
- [ ] 法兰标准号（FBP100 / UG-39…）  
- [ ] 检验方法（CMM/影像）  
- [ ] 未注公差标准（1804-m / 1184-K）  

### 6.3 商务

- [ ] 是否保密/NDA  
- [ ] 是否 GJB 检验规范  
- [ ] 变更流程：关键尺寸只回写 HFSS  

---

## 7. 默认公差规则库草稿（YAML 语义）

```yaml
ruleset: xixia_rf_v0
units: mm
tol_classes:
  IRIS: {plus: 0.02, minus: 0.02, ra: 0.8}
  WG_AB: {plus: 0.03, minus: 0.03, ra: 0.8}
  CAV_H: {plus: 0.03, minus: 0.03, ra: 0.8}
  PIN_H7: {fit: H7}
  FLAT_FLANGE: {flatness: 0.03}
  THD: {class: "6H", note: "有效牙深+底孔(牙深+3~5P)"}
  FREE: {std: "GB/T 1804-m"}
  THz: {scale: 0.5, note: "再收紧 30~50%"}
finish:
  aluminum: "导电氧化 或 外漆+内酸洗"
  copper_silver: {um: 5, q_high: "5-8"}
chamfer_inside: "≤0.1x45"
audit:
  snap_max_mm: 0.0001
  volume_rel: 1.0e-9
  bbox_abs_mm: 1.0e-6
```

---

## 8. 典型失败 → 处置

| 症状 | 处置 |
|------|------|
| 导入后断线 | 先查 sheet 是否厚化，再 heal 0.001 |
| 标注和 HFSS 不一致 | 禁止量模型；查 dims.json |
| 厂家说孔距不对 | 对 FBP100/UG 图核销距，禁止拍脑袋 |
| 交期长 | 按 QuinStar：补 3D；勿只给手绘 |
| 镀后堵 iris | 图注「镀后不得堵」+镀前检 |

---

## 9. 与主方案章节对应

| 本细则 | 主方案 |
|--------|--------|
| §1 金样 | §17 金样验收 |
| §2–3 出图 | §6/§12/§15 |
| §4–5 审计 | §10/§16 |
| §6 RFQ | §13/§13A |
| §7 规则库 | §12/§14 |

---

---

## 10. 官方 API 安全预设（PyAEDT 1.7 核对）

### 10.1 export_3d_model（官方签名）

```python
export_3d_model(file_name="", file_path="", file_format=".step",
                assignment_to_export=None, assignment_to_remove=None,
                major_version=-1, minor_version=-1) -> bool
```

- 默认 `.step`；ACIS `.sm3/.sat/.sab` 自动 major=29  
- **必须**显式 `assignment_to_export`（Region 自动剔除不够，SubRegion/PML 要手列）  

### 10.2 import_3d_cad（生产钉法）

```python
import_3d_cad("part.step",
              healing=False,                    # 先不 heal
              point_coincidence_tolerance=1e-6,
              merge_planar_faces=True,
              merge_angle=0.02,
              input_file_unit="mm",             # 禁 Auto
              reduce_stl=False)
```

文档笔误：`reduce_stl` 正文写 True，**签名是 False**——以签名为准。

### 10.3 heal_objects：RF 制造「保守预设」（关键）

官方默认**对 RF 件过猛**，必须收紧：

| 参数 | 官方默认 | **RF 制造预设** | 原因 |
|------|----------|-----------------|------|
| max_stitch_tolerance | 0.001 | **0.001**（最多 0.01） | 禁几何漂移 |
| geometry_simplification_tolerance | **1 mm** | **≤0.001 或 simplify_geometry=False** | 1mm 会吃掉 iris！ |
| simplify_geometry | True | **False**（除非只圆角） | 保解析面 |
| tighten_gaps_width | 1e-5 | **1e-5** | 勿放大 |
| remove_holes / chamfers / blends | **True** | **全部 False** | 孔/倒角是零件 |
| allowable_volume_change | 5 | **≤0.01** 或记录后人工 | 5% 对 RF 不可接受 |
| heal_to_solid | False | 按需 | 仅缺面时 |
| explode_and_stitch | True | True | — |

```python
hfss.modeler.heal_objects(
    assignment="housing",
    auto_heal=False,
    tolerant_stitch=True,
    simplify_geometry=False,       # 关键
    tighten_gaps=True,
    max_stitch_tolerance=0.001,
    tighten_gaps_width=1e-5,
    remove_silver_faces=True,
    remove_small_edges=True,
    remove_holes=False,            # 关键
    remove_chamfers=False,
    remove_blends=False,
    allowable_surface_area_change=0.01,
    allowable_volume_change=0.01,
)
```

**每次 heal 必须写 heal_log（参数+前后体积）。**

### 10.4 PCB 侧（PyEDB）

- 公开 API **IPC-2581 可导出**；**ODB++ 文档面仅导入**  
- `export_to_ipc2581(ipc_path=...)`  
- ODB µm 陷阱仍在  

---

## 11. 出图引擎开源选型（采纳清单）

| 优先级 | 项目 | 用途 | 许可 |
|--------|------|------|------|
| 1 | **text-to-cad `engineering-drawing`** | 三视图+尺寸行+碰撞警告+图层+ISO 图框 API | MIT |
| 2 | **build123d TechnicalDrawing** | `project_to_viewport`、Draft/ExtensionLine、导出 SVG | Apache-2.0 |
| 3 | **step2pdf** 架构 | 几何分析→族分类→尺寸配方→批量 PDF+JSON 日志 | 可读小仓 |
| 4 | **ezdxf** | DXF 标注/公差/GB 字体 | MIT |
| 5 | **Autocad-MCP ISO 模式** | 借 **ISO 129/286/5457/7200/7573** 字段名与预设（不必用 COM） | MIT |
| 6 | pyAEDT modeler | 参数化腔体→STEP | MIT |

**推荐合成：**  
`dims.json → build123d/OCCT 投影 → text-to-cad 风格图纸 API 或 ezdxf → PDF/DXF`  
特征配方抄 step2pdf 的 family→dimension-recipe。

**缺口自建：** 成熟「WR-xx 尺寸表生成器」开源不存在 → 规则库 YAML（§7）+ RFTOP 数字自建。

---

## 12. 与主方案映射（官方/开源补强）

| 细则章节 | 补强点 |
|----------|--------|
| §10 | heal 保守预设；文档笔误以签名准 |
| §11 | 出图引擎可落地选型 |
| §4 | export 白名单强制 |
| §6 | RFQ 配 text-to-cad 风格三视图 |

---

---

## 13. ISO 7200 / 129 ↔ GB/T 10609 / 4458 对照（图框可映射）

### 13.1 标题栏字段

| ISO 字段 | GB/T 字段 | 示例 | 必填 |
|----------|-----------|------|------|
| Legal owner | **单位名称** | ××精密机械 | 是 |
| Title | **图样名称** | 波导腔体 | 是 |
| Document number | **图样代号/图号** | TJU-ME-24-001 | 是 |
| Revision / ECN | **更改区**（标记/处数/分区/文件号） | A | ISO 管理 |
| Date of issue | **年月日** | 2024-03-15 | 是 |
| Designed by | **设计** | 张三 | 是 |
| Checker | **校对** | 李四 | 是 |
| Approver | **审核/批准** | 王五 | 是 |
| — | **工艺/标准化** | 企业选填 | GB 常见 |
| Scale | **比例** | 1:2 | 是 |
| Sheet no./total | **共X张 第X张** | 共4张 第2张 | 是 |
| Material | **材料标记** | AL6061-T6 | 常见 |
| Mass | **重量** | 0.85 kg | 常见 |
| Projection | **投影符号** | 第一角/第三角 | ISO 字段 |
| Unit | mm（GB 可省） | mm | ISO 显式 |
| Stage | **阶段标记** | S1/生产 | 可选 |

**text-to-cad / Autocad-MCP 映射建议：** 以 GB 中文字段为一线名，ISO 名作别名。

### 13.2 尺寸注法 ISO 129-1 vs GB/T 4458.4

| 项 | ISO 129-1 | GB/T 4458.4 |
|----|-----------|-------------|
| 箭头 | 实心为主 | 箭头为主；**45°斜线/圆点**合法（窄空间） |
| 单位 | mm 可省 | mm 可省 |
| 公差 | 偏差叠排 / ISO 286 代号 | **Φ50H7** 等带代号优先；形位 GB/T 1182 |
| 文字 | 尺寸线上方 | 同；竖直尺寸数字头朝左 |
| 参考尺寸 | ( ) |  |
| 倒角圆角 | C× / R× | C2、R5 简化 |

**实现：** ezdxf `set_tick` 或闭合箭头；公差优先 **H7/±0.03** 形态；窄处用斜线。

---

## 14. 导出/修复函数草稿（实现时对照）

### 14.1 清洗+双格式导出

```python
def export_fab_geometry(hfss, out_dir: str, solids: list[str]) -> dict:
    """清洗后导出 x_t + step；返回 manifest 片段。"""
    # 1) 显式白名单：solids = 过滤后的 object_names
    export_list = [o for o in solids if not is_non_part(o)]
    # 2) 双格式
    for fmt in (".x_t", ".step"):
        ok = hfss.export_3d_model(
            file_name="part",
            file_path=out_dir,
            file_format=fmt,
            assignment_to_export=export_list,
            assignment_to_remove=["Region"],
        )
        if not ok:
            raise RuntimeError(f"export failed: {fmt}")
    return {
        "formats": [".x_t", ".step"],
        "objects": export_list,
        "units": "mm",
    }

def is_non_part(name: str) -> bool:
    low = name.lower()
    return any(k in low for k in ("region", "air", "vacuum", "pml", "port"))
```

### 14.2 保守 heal（必须记 log）

```python
def heal_for_fab(hfss, obj: str) -> dict:
    hfss.modeler.heal_objects(
        assignment=obj,
        auto_heal=False,
        tolerant_stitch=True,
        simplify_geometry=False,
        tighten_gaps=True,
        max_stitch_tolerance=0.001,
        tighten_gaps_width=1e-5,
        remove_silver_faces=True,
        remove_small_edges=True,
        remove_holes=False,
        remove_chamfers=False,
        remove_blends=False,
        allowable_surface_area_change=0.01,
        allowable_volume_change=0.01,
    )
    return {"obj": obj, "max_stitch": 0.001, "simplify": False}
```

### 14.3 审计门（纯函数）

```python
def audit_gate(dims, geom_a, geom_b, snaps) -> list[str]:
    errs = []
    if dims_raw_mismatch(dims):
        errs.append("A1 variable mismatch")
    if abs(bbox(geom_a) - bbox(geom_b)) > 1e-6:
        errs.append("A2 bbox")
    if rel_vol_err(geom_a, geom_b) > 1e-9:
        errs.append("A3 volume")
    if cut_volume(geom_a, geom_b) > 1e-6:
        errs.append("A4 boolean")
    if snaps and max(snaps) > 1e-4:
        errs.append("A8 snap")
    return errs  # empty ⇒ PASS
```

---

## 15. 导出格式清单（源码核对版）

`export_3d_model` 是 **后缀透传** 给 `oEditor.Export`，**无完整 allowlist**；仅 `.sm3/.sat/.sab` 自动 ACIS 版本 29.0。

| 格式 | 证据 | 生产建议 |
|------|------|----------|
| **.step** | 默认；primitives.py / analysis_3d.py | **必发**（AP214） |
| **.x_t / .x_b** | 测试 + kernel_converter.py | **必发**（NX/内核；3D Layout ≥2023R1） |
| .sat/.sab/.sm3 | 显式分支 | 仅调试/ACIS 链 |
| .stl | 有引用 | **禁加工真源** |
| IGES | 本树无 oEditor.Export 路径 | 勿依赖 |
| A3DCOMP / OBJ | 其他 API（Create3DComponent / ExportModelMesh） | 非加工 |

**3D Layout：** `ExportCAD`→`.x_t`（≥2023R1）否则 `ExportAcis`→`.sat`。  
**内核转换：** ACIS（≤2022R2）↔ Parasolid（≥2023R1）用 **`.x_t` 往返**；需 legacy AEDT 作读入端。  
**导入：** `import_3d_cad` 自动识别；另支持 DXF/GDSII/Nastran(→STL)/A3Dcomp/Layout 多格式。

---

*完（v1.2）：ISO↔GB 对照、导出/修复/审计函数草稿、格式清单。*
