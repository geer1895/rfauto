# B-rep 投影实现规范（复合层 DXF 导出前置件）

**版本**：v1.0（ge5 Goal Wave3 F 组，2026-09-30）
**来源**：`E:\协助调研\cad导出\改动总结-复合层DXF导出.md` §2.1/§2.2/§2.8/
§2.10/§6-8（只读借鉴，禁改该仓）；六百六十三 吸收账。
**状态**：实现规范（伪代码级步骤+验收判据）。本仓当前**无 OCC/pythonocc
依赖**，本文不引入重依赖；**解锁条件 = OCC 依赖裁决**（登记 followUp），
裁决通过前任何实现只允许落在 adapters 层并保持惰性 import（与
fab_export 包 ezdxf 同款纪律）。

---

## 0. 适用范围与分层

- 适用：AEDT/HFSS 几何 → STEP/X_T → OCC 读回 → 2D 投影轮廓/孔位 →
  复合层 DXF（`M1/M2/sub/patch`，图层语义见
  `rfauto.core.fab_export.composite_layer`）。
- 分层：OCC 读取/投影属 adapters（`adapters/fab_export/`，惰性
  import）；组板/过滤/对照判据属 core（已落地：composite_layer.py +
  dxf_compare.py）；DXF 写出已落地（adapters/fab_export/composite_dxf.py）。
- 本规范覆盖「几何对象 → 投影几何」一段；组板与真值对照见
  `README.md` 能力表。

---

## 1. 规则一：折线必须有序遍历（无序拼折线 = 自相交 X 线）

**症状**：2D DXF 出现大量对角线（X 号），自相交折线 3098 条
（源仓实测）。

**根因**：对 wire 的边用 `TopExp_Explorer` 无序枚举后直接拼接采样点；
且 `REVERSED` 方向的边未反转点列，相邻边首尾错位。

**实现步骤（伪代码）**：

```python
from OCP.BRepTools import BRepTools_WireExplorer
from OCP.TopAbs import TopAbs_REVERSED
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_QuasiUniformDeflection

def wire_to_polyline(wire, deflection=0.01):
    pts = []
    exp = BRepTools_WireExplorer(wire)          # ① 有序遍历器，不是 TopExp_Explorer
    while exp.More():
        edge = exp.Current()
        curve = BRepAdaptor_Curve(edge)
        disc = GCPnts_QuasiUniformDeflection(curve, deflection)
        seg = [curve.Value(disc.Parameter(i)) for i in range(1, disc.NbPoints() + 1)]
        if edge.Orientation() == TopAbs_REVERSED:   # ② 反向边先反转点列
            seg.reverse()
        # ③ 去相邻重复点后拼接
        if pts and seg and dist(pts[-1], seg[0]) < 1e-9:
            seg = seg[1:]
        pts.extend(seg)
        exp.Next()
    return pts
```

**验收判据**：
1. 读回 DXF 折线自相交计数 = 0（逐段求交或射线计数）；
2. 折线周长与 wire 三维长度差 < 1%（投影面内）；
3. 回归锚：矩形板外形读回必须恰为 4 段直线段（X 线症状下会多出
   对角段）。

---

## 2. 规则二：最大闭合外轮廓 ≠ 零件外形（外框陷阱）

**症状**：把图框/工艺外框（如 24×H 矩形）当成拼接外形，高度/缝孔
全错（源仓 B4/M8 反例）。

**实现步骤**：

```python
def pick_panel_outline(loops, marked_layer="LAYER_1"):
    # ① 优先显式标记层（源仓惯例 LAYER_1 = 拼接外形）
    if marked := [lp for lp in loops if lp.layer == marked_layer]:
        return marked
    # ② 否则取「非最大外框」的内轮廓：按 bbox 面积排序，
    #    剔除面积最大者（外框），在剩余中取最大闭合环
    ranked = sorted(loops, key=area, reverse=True)
    candidates = ranked[1:] if len(ranked) > 1 else ranked
    return [c for c in candidates if is_closed(c)]
```

**验收判据**：
1. 选中外形的 bbox 高度 = 设计件高（±1e-6），不是外框高；
2. 有 LAYER_1 标记时选中环 ∈ 标记层；
3. 单环退化情形（真只有一个环）必须显式留痕（报告 note），不得
   静默把唯一环当外框剔除。

---

## 3. 规则三：源实体类型全覆盖（圆孔常以独立 CIRCLE 实体存在）

**症状**：金属层上 r=0.16 的小圆孔漏画（源仓 duan M6 反例，§2.10）——
按「孔=wire 内环」假设提孔会漏掉独立 CIRCLE 实体。

**实现步骤**：投影提取必须按实体类型分派，禁止单一提取路径：

| 源实体 | 处理 |
|--------|------|
| 平面 wire | 规则一有序折线（外形/内环） |
| `CIRCLE` | 圆心+半径直取（通孔完整不简化，禁折线近似） |
| `ARC` | 圆心+半径+角度域（孔识别按圆心/半径，弧段另记） |
| `ELLIPSE`/`BSPLINE` | 采样折线 + 采样密度验收 |
| `POLYLINE`/`LWPOLYLINE`（2D 交换面） | 相邻点对折段（read 端已实现：composite_dxf._polyline_to_segments） |

**验收判据**：
1. 按类型计数：读回实体计数与源模型逐类型一致（LINE/N、CIRCLE/N…）；
2. 任何 CIRCLE 实体的圆心/半径逐位进入 DXF（读回 |Δr|<1e-9）；
3. 负例钉：构造含 r=0.16 CIRCLE 的最小模型，漏提即 FAIL。

---

## 4. 规则四：中文路径 STEP 坑（AEDT 写出静默失败）

**症状**：AEDT 对非 ASCII 路径写 STEP 可能失败且报错不显（源仓 §6-8）。

**实现步骤**：
1. 导出目标先落 **ASCII 临时目录**（如 `C:\Temp\rfauto_step\`）；
2. 写成功（文件存在 + 非零 + reader 可读回）后再拷回工作区目标路径；
3. 拷贝用 `shutil.copy2`（保留元数据），拷后哈希双记（进交付
   manifest，A12 同口径）。

**验收判据**：中文路径端到端导出成功且中间 ASCII 副本与最终文件
sha256 一致；失败时 errors 面显式报「AEDT 写 STEP 失败」而非静默。

---

## 5. 与 Z 向贴合组板的衔接

投影得到每个 solid 的 XY 投影 + bbox（z0/z1）+ 材质语义后，喂给
`core.fab_export.composite_layer.group_composite_layers`（物理贴合
组板）与 `filter_unsupported_holes`（悬空孔过滤）——圆柱孔识别用
「轴向 |dir·Z|>0.98 的圆柱面参数」或 XY bbox 双向近等的几何判据
（源仓 build_laminates cylinder_params 口径），名字语义
（via*/chao*）只作辅助。

## 6. followUp 登记（不引依赖的边界）

- OCC/pythonocc 依赖裁决 → 裁决前本规范仅文档态；
- 裁决通过后的落地顺序建议：规则四（导出路径卫生）→ 规则三（类型
  分派提取）→ 规则一（有序折线）→ 规则二（外形选取），每步带上述
  验收判据的离线单测（合成 STEP 或 mock 读回，零 AEDT）。
