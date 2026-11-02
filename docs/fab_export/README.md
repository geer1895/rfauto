# fab_export 能力指数（HFSS → CAD/可加工交付）

> 本页是 docs/fab_export/ 的指数页：只做指针与能力地图，正文见各文档。
> 交付纪律：尺寸真源 = STEP/几何，禁止从 DXF 反量改数；发图前必须审计 PASS。

## 文档地图

| 文档 | 内容 |
|------|------|
| [HFSS到CAD加工图纸自动化方案.md](HFSS到CAD加工图纸自动化方案.md) | 主方案：链路 A/B/C、精度铁律、误差预算、架构 |
| [HFSS到CAD加工_可落地细则.md](HFSS到CAD加工_可落地细则.md) | 金样 WR-90、公差规则、RFQ/出图模板（内部资料，不入公开仓） |
| [HFSS到CAD加工图纸自动化方案_调研附录.md](HFSS到CAD加工图纸自动化方案_调研附录.md) | 调研附录 |
| [brep_projection_spec.md](brep_projection_spec.md) | B-rep 投影实现规范（WireExplorer+REVERSED／外框陷阱／实体类型全覆盖／中文路径 STEP 坑；OCC 依赖解锁前为文档态） |

## 代码能力地图（本仓实现）

| 能力 | 位置 |
|------|------|
| 机加单件包（dims/QIF/gcode/审计 A1–A12） | `core/fab_export/`、`adapters/fab_export/`、`service/fab_export_service.py`（T43 吸收批） |
| 2.5D 面轮廓 DXF + 参数化出图 | `adapters/fab_export/face_dxf.py`、`ezdxf_draw.py` |
| HFSS 真机几何导出（STEP/X_T） | `adapters/fab_export/hfss_export.py`（service: `fab_export_geometry`） |
| 复合层组板（介质+Z 向贴合金属 → M1/M2/sub/patch） | `core/fab_export/composite_layer.py`（ge5 F 组） |
| 复合层四图层 DXF 写/读 | `adapters/fab_export/composite_dxf.py`（ge5 F 组） |
| DXF 真值对照（三归一：INSERT 展开/去重/Y 归一） | `core/fab_export/dxf_compare.py` + `adapters/fab_export/dxf_truth.py`（ge5 F 组） |

## TRL 面板拼接（指针登记，暂不实现）

- **来源文档**：`E:\协助调研\cad导出\改动总结-复合层DXF导出.md`
  （§1.2 TRL 拼接规则、§1.1 复合层四图层约定；工作区 scripts/
  build_trl_panel.py 为参考实现，只读借鉴不搬代码）。
- **规则要点**：顺序矮→高（thr→kai→duan→delay2→delay1）；底对齐；
  件间 1 mm 缝；只删两件贴缝竖边的重叠高度段（内部边不删）；缝孔
  r=0.4、步距 1.2、重叠高度内居中、上下最小留白 0.7；高差台阶要闭合
  （矮件顶/底水平桥+高件突出段竖线）；**sub/M1/M2 都要桥**；多段铜皮
  全部保留；最大闭合外框 ≠ 拼接外形。
- **登记口径**（ge5 Goal Wave3 F 组，2026-09-30）：本批仅指针登记，
  拼接器不实现；真要做时按上表复合层组板/对照能力之上加编排层。
