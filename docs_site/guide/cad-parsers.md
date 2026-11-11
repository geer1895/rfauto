# CAD/EDA 格式解析器指南

> 本文讲"拿一份 EDA 格式文件，rfauto 能读出什么"：17 个解析面各自
> 的仓内入口、最小用例与已知限制。逐命令完整参数表见
> [CLI 命令参考](../reference/cli.md)（机读生成，与代码实注册同源），
> 每条命令的权威口径始终是 `rfauto <命令> --help`。
> 页内接线状态为 **2026-11-08 代码实测**（`rfauto --help` + 注册面巡检）；
> "待接线"域随合流批接线后即可用，以届时 `rfauto --help` 实测为准。

## 0. 集群定位与三层架构

aurora_q 战役交付的 EDA 格式解析器集群覆盖数字/模拟混合设计常见交换
格式：仿真网表（SPICE/Verilog）、时序与约束（Liberty/SDC/SDF）、寄生
（SPEF）、仪器数据（CITI/Touchstone）、IO 模型（IBIS）、波形（VCD）、
制造与版图（Gerber/Excellon/GDSII/LEF/DEF/IPC-D-356）、规则与对照
（DRC/LVS）以及脚本语言（SKILL/OCEAN 静态解析）。

共性架构（全集群一致，接新格式照此位次）：

```
core 纯函数解析内核          service 信封包装            CLI 薄壳 / MCP 工具
（零 IO/零依赖/确定性）  →  （文件 IO 收敛+ok/error  →  rfauto <域> <叶> --json
  ParseError 带行号            信封构造，JSON 进出）      （MCP 八工具，2026-11-08 起）
```

三条诚实语义纪律贯穿全部解析器（与"数值只在确定性内核"铁律同源）：

- **fail-soft**：未识别构造不炸全文——降级为 `warnings` 逐条如实回显，
  零静默丢弃；
- **宁 raw 不编数**：解码不了的值保留原文并标注状态（绝不合成数值）；
- **宁不报不误报**：证据不足的判定如实置空/置 UNKNOWN（解析不仿真，
  零求解零器件方程）。

## 1. 状态总表（2026-11-08 实测）

| 格式 | CLI 叶（顶层组） | CLI 状态 | MCP 工具 | service 单源 |
|---|---|---|---|---|
| SPICE | `spice parse` | 已接线 | `spice_netlist_parse` | `service/spice_netlist_service.py` |
| Liberty | `liberty parse` / `liberty list` | 已接线 | `liberty_parse` | `service/liberty_service.py` |
| CITI | `citi info/segments/network` | **待接线**（孤儿域挂账） | `citi_info` | `service/citi_service.py` |
| SDC | `sdc parse` / `sdc list` | 已接线 | `sdc_parse` | `service/sdc_service.py` |
| IBIS | `ibis parse` / `ibis list` | 已接线 | `ibis_parse` | `service/ibis_service.py` |
| Verilog | `verilog parse` / `verilog list` | 已接线 | `verilog_netlist_parse` | `service/verilog_netlist_service.py` |
| DRC 规则 | `drc parse` / `drc validate` | 已接线 | `drc_rules_parse` | `service/drc_service.py` |
| LVS 对照 | `lvs compare` | 已接线 | `lvs_compare_files` | `service/lvs_compare_service.py` |
| GDSII | `gdsii parse/layers` | **待接线**（孤儿域挂账） | — | `service/gdsii_service.py` |
| LEF/DEF | `lefdef parse/check` | **待接线**（孤儿域挂账） | — | `service/lef_def_service.py` |
| Gerber/Excellon | `fab parse` / `fab summary`（fab 组内） | 已接线 | — | `service/fab_gerber_service.py` |
| SPEF | `spef parse/report` | **待接线**（孤儿域挂账） | — | `service/spef_service.py` |
| SDF | `sdf parse/report` | **待接线**（孤儿域挂账） | — | `service/sdf_service.py` |
| IPC-D-356 | `ipc356 report` | **待接线**（孤儿域挂账） | — | `service/ipc356_service.py` |
| Touchstone | `touchstone info` | **待接线**（孤儿域挂账） | — | `service/touchstone_service.py` |
| SKILL/OCEAN 解析 | `skill-parse parse/report` | **待接线**（孤儿域挂账；顶层 `skill` 组是模板生成器，另一回事） | — | `service/skill_service.py`（解析节） |
| VCD | `vcd parse/report` | **待接线**（孤儿域挂账） | — | `service/vcd_service.py` |

说明：

- **已接线**=本文写作时 `rfauto --help` 实测可见，叶可直接跑；
- **待接线（孤儿域挂账）**=core+service+CLI 域模块三面齐备且测试全绿，
  但 CLI 域模块尚未挂进主注册树（合流纪律：先接线后重锚计数锚，属主
  代理显式评审动作）。这些域的 **service 函数现在就能用**（Python 直调
  面与 CLI 同源）；MCP 侧八工具组（SPICE/Liberty/CITI/SDC/IBIS/Verilog/
  DRC/LVS）已覆盖的域见 [MCP 工具参考](../reference/mcp.md)；
- fab 组内 `fab parse --drill` 与 `ipc356 report --check-drill` 是
  Gerber×Excellon×IPC-356 三件制造面的交叉校验入口（见 §13/§16）。

## 2. 三种消费路径

同一份解析能力有三条等价消费路径，按场景取用：

```bash
# ① CLI（人/脚本）：wired 叶直接跑
rfauto spice parse deck.cir --json
```

```python
# ② Python service（程序化调用面；与 CLI 同源同参）
from rfauto.service.spice_netlist_service import parse_netlist_file
env = parse_netlist_file("deck.cir")     # ok/error 信封（见下）
if env["ok"]:
    print(env["summary"]["n_elements"])
```

```text
# ③ MCP（Agent 只读面）：八域工具名见 §1 表与 reference/mcp.md
```

信封契约（全部 service 函数一致）：成功 `{"ok": True, ...业务键}`；失败
`{"ok": False, "errors": ["..."], ...诊断键}`——失败不抛异常（core 层的
`*ParseError` 在 service 层转 error 信封；CLI 层 usage 错 exit 2、service
失败 exit 1）。所有 CLI 叶带 `--json`，JSON 输出成功+失败同构。

---

以下每格式一节：**是什么** / **仓内入口**（core→service→CLI→MCP）/
**最小用例** / **已知限制**。用例片段与 2026-11-08 HEAD 的真实 API 签名
逐条核验一致。

## 3. SPICE 网表（ngspice/HSPICE/Spectre）

**是什么**：三方言统一的网表深度解析——把一份 SPICE 网表解析为五维度
结构化输出：元件实例（R/L/C/D/M/Q/J/E/F/G/H/K/X/V/I…+端口对+单位）、
子电路层次树、控制语句（.tran/.ac/.dc 等）、模型卡、拓扑（MNA 维度+
节点双向图+孤立节点检测+接地归一 0/gnd/gnd!）。flavor 可 `auto` 内容
判定或显式指定。

**仓内入口**：core `parse_spice_netlist_text(text, flavor="auto")`
（`rfauto/core/spice_netlist_parser.py`）→ service
`parse_netlist_file(path, flavor="auto", include_topology=True)` /
`parse_netlist_text(text, ...)` → CLI `rfauto spice parse <file>
[--flavor auto|ngspice|hspice|spectre] [--topology/--no-topology] [--json]`
→ MCP `spice_netlist_parse(path, flavor, include_topology)`。

**最小用例**：

```bash
rfauto spice parse deck.cir --flavor auto --json
```

```python
from rfauto.service.spice_netlist_service import parse_netlist_file
env = parse_netlist_file("deck.cir")
n_elem = env["summary"]["n_elements"]       # 元件计数
mna = env["topology"]["mna_size"]           # MNA 维度（非地节点+分支增广）
```

**已知限制**：解析不仿真（零求解）；表达式参数 `{...}`/`'...'` 保留原文
不代入；拓扑只在顶层网表计算（子电路体是模板不展平）；fail-soft——结构
错误进 `structural_errors` 不中断；方言终止符变体（.endl 等）收编并记
warning。

## 4. Liberty 时序库（.lib）

**是什么**：Synopsys Liberty（IEEE 1601 系）时序库只读结构化解析——
library/cell/pin/timing 四级结构+四张 NLDM 查找表（cell_rise/cell_fall/
rise_transition/fall_transition）+功率面（internal_power/leakage_power）
+lu_table_template 模板继承+operating_conditions。

**仓内入口**：core `parse_liberty(text)` / `extract_library(library,
include_timing=True, include_power=True)` / `lookup_table(table, x1,
x2=None)`（双线性插值+边界夹取）（`rfauto/core/liberty_parser.py`）→
service `parse_liberty_file(path, cell=None, pin=None, include_timing=
True, include_power=True)` / `list_liberty_cells(path)` → CLI
`rfauto liberty parse <file> [--cell --pin --timing --power --json]`、
`rfauto liberty list <file> [--json]` → MCP `liberty_parse`。

**最小用例**：

```bash
rfauto liberty parse mylib.lib --cell INVX1 --pin ZN --timing
```

```python
from rfauto.core.liberty_parser import extract_library, lookup_table, parse_liberty
lib = extract_library(parse_liberty(open("mylib.lib", encoding="utf-8").read()))
t = lib["cells"]["INVX1"]["pins"]["ZN"]["timing"]["A"]["cell_rise"]
delay = lookup_table(t, x1=0.01, x2=0.5)    # 双线性插值（越界夹取）
```

**已知限制**：只钉 NLDM 主面——CCS/ECSM 深表、check_timing 约束建模不
做；模板继承只补 index 不补数据（values 恒为本地）；未识别组/属性原样
保留（attrs+groups 透传），消费端可继续下钻。

## 5. CITI 仪器数据（CITIfile/CVG）

**是什么**：HP/Agilent/Keysight 仪器传输中间格式（IC-CAP/ADS/PLTS 生态）
的包级解析：包头关键字+变量/常量声明+数据段（ASCII 与二进制扩展），
SEG 线性段按 Ansys 公式合成频率轴；可桥 skrf 读取 S 参数段。

**仓内入口**：core `parse_citi_file(path)` / `parse_citi_text(text)` /
`decode_citi_field(letter, text)`（`rfauto/core/citi_parser.py`）→
service `citi_info(path, max_values=None)` / `citi_read_segments(path,
names=None, include_raw=False)` / `citi_network_probe(path)`（skrf 桥
条件探针）→ CLI `rfauto citi info|segments|network`（**待接线**）→ MCP
`citi_info(path, max_values)`。

**最小用例**（service 现在就能用）：

```python
from rfauto.service.citi_service import citi_info, citi_read_segments
info = citi_info("trace.cti")
seg = citi_read_segments("trace.cti", names=["S[1,1]"])
s11 = seg["segments"][0]["dependent_vars"][0]["values"]   # [re, im] 对列表
```

**已知限制**：二进制格式字母 C（40 bit）/D（24 bit）无 IEEE-754 位型
映射——`decode_status="unsupported_width"` 只留结构不解码数值（宁 raw
不编数）；布局歧义段 `values=None`+raw 保留；截断文件如实带 warning；
skrf 桥是**条件**的（S 段齐套方阵+无多值扫描才桥，不满足走 skipped
信封）；CLI 三叶为孤儿域挂账（接线前用 service/MCP 面）。

## 6. SDC 约束（Synopsys Design Constraints）

**是什么**：Tcl 语法子集的时序约束结构化解析，输出八桶：clocks
（create_clock/-generated）、delays（set_input/output_delay）、paths
（false_path/max/min_delay）、constraints（load/driving_cell/fanout/
case/multicycle/latency/uncertainty）、objects（get_ports/pins/cells/
nets/clocks 的 pattern 收集）、variables、warnings、stats。

**仓内入口**：core `parse_sdc(text, variables=None)` / `parse_tcl(text)`
（`rfauto/core/sdc_parser.py`，词法层+语义层同代分层）→ service
`parse_sdc_file(path)` / `list_sdc_commands(path)` → CLI
`rfauto sdc parse <file> [--clocks --timing --paths --constraints --json]`、
`rfauto sdc list <file> [--json]` → MCP `sdc_parse(path)`。

**最小用例**：

```bash
rfauto sdc parse top.sdc --clocks --json
```

```python
from rfauto.service.sdc_service import parse_sdc_file
env = parse_sdc_file("top.sdc")
clk = env["clocks"][0]          # {"name", "period", "waveform", ...}
```

**已知限制**：SDC 命令面是结构化子集（20 个命令名+对象访问器）；未知
命令不报错进 warnings（SDC 文件合法含工具私有命令）；词位 `#` 按 SDC
生态宽容口径作注释（严格 Tcl 会当普通词——跨工具复用时留意）；静态
解析无运行时语义（未定义变量保留原文不猜）。

## 7. IBIS 模型（.ibs）

**是什么**：数字 IO buffer 行业标准（IBIS Open Forum v3.2/v4.x 经典
节面）只读解析：头部/器件 [Component]/[Package]/[Pin]、模型 [Model]
与 [Model Selector]、四张 IV 表（Pullup/Pulldown/GND Clamp/POWER
Clamp）、[Ramp] 与暂态波形表；带单位词法（V/mA/nH/pF/裸 SI 前缀/"X/Y"
比值）与线性插值内核。

**仓内入口**：core `parse_ibis(text)` / `extract_ibis(file,
include_tables=True)` / `interp_iv(table, voltage, corner="typ")` /
`interp_waveform(table, time, corner="typ")` / `parse_quantity(token)`
（`rfauto/core/ibis_parser.py`）→ service `parse_ibis_file(path,
component=None, model=None, include_tables=True)` /
`list_ibis_inventory(path)` → CLI `rfauto ibis parse <file> [--component
--model --tables --json]`、`rfauto ibis list <file> [--json]` → MCP
`ibis_parse`。

**最小用例**：

```bash
rfauto ibis parse device.ibs --model IO_FAST
```

```python
from rfauto.core.ibis_parser import extract_ibis, interp_iv, parse_ibis
ibs = extract_ibis(parse_ibis(open("device.ibs", encoding="utf-8").read()))
tbl = ibs["models"]["PD_MODEL"]["tables"]["gnd_clamp"]   # voltage/typ/min/max
i = interp_iv(tbl, 0.35)                                # 线性插值+边界夹取
```

**已知限制**：真实供应商文件的超范围 keyword（[Diff Pin]/[Die] 等）进
warnings+内容忽略（宁降级不炸）；多器件文件 [Model] 面文件级不回填器件
归属（以 components[].pins 为准）；[End] 必须收尾（ibischk 同口径）；
未知单位后缀报错宁红不猜。

## 8. Verilog 网表（IEEE 1364 结构子集）

**是什么**：数字后端 gate-level netlist 只读解析：module ANSI 2001/
1995 双形态统一、ports/wires/assigns/instances/parameters 五桶、门级
原语注册表（LRM 14 章全集，位置连接归一命名映射）+拓扑提取（实例→网→
实例三层关系、孤立网双桶 undriven/unloaded、DAG 树深度+关键路径+组合
环检测）。

**仓内入口**：core `parse_verilog(text)` / `extract_module_topology(doc,
module_name)` / `parse_verilog_number(text)`（`rfauto/core/
verilog_netlist_parser.py`）→ service `parse_verilog_file(path,
with_topology=True)` / `parse_verilog_module(path, module,
with_topology=True)` / `list_verilog_modules(path)` → CLI
`rfauto verilog parse <file> [--module/-m NAME] [--topology/--no-topology]
[--json]`、`rfauto verilog list <file> [--json]` → MCP
`verilog_netlist_parse(path, with_topology)`。

**最小用例**：

```bash
rfauto verilog parse netlist.v --module top --json
```

```python
from rfauto.service.verilog_netlist_service import parse_verilog_file
env = parse_verilog_file("netlist.v")
top = env["modules"]["top"]
view = env["topology"]["top"]
print(top["ports"], view["instance_count"], view["tree_depth"]["depth"])   # 端口表+实例数+DAG 树深度
```

**已知限制**：行为块（always/initial/function/task/specify/generate）
整体跳过——过程赋值驱动的 reg 不判 undriven（已知盲区，双桶口径内建
豁免）；外部单元库实例的连接网进 external_boundary_nets（驱动方向不可
判，宁不报不误报）；组合环时 depth 如实置 None 不猜。

## 9. DRC 规则（JSON/CSV/自由文本）

**是什么**：PCB 设计规则文件三形态统一解析到同一 schema（name/type/
layer_scope/value/unit/priority/...），12 类型注册表+单位族归一
（mm/um/mil→mm、ohm/token/count）+优先级压制语义；`drc validate` 把
design JSON（objects 列表）×规则集跑出 verdict=issues/attention/clean，
`--rf` 启用四个 RF 特化检查器（阻抗精度/焊盘间距/地过孔围栏/屏蔽罩
间距）。

**仓内入口**：core `parse_drc_rules(text, fmt="auto")` /
`evaluate_drc_rules(rules, objects, coord_unit="mm", rf_checks=False)` /
`default_rf_rules()` / `to_dfm_rule(rule)`（`rfauto/core/drc_parser.py`）
→ service `parse_drc_file(path, fmt="auto")` / `validate_design_file(
design_path, rules_path=None, rf=False)` → CLI `rfauto drc parse <file>
[--rules --rf --json]`、`rfauto drc validate <design.json> [--rules FILE
--rf --json]` → MCP `drc_rules_parse(path, fmt)`。

**最小用例**：

```bash
rfauto drc validate board.json --rf        # rf=True 无规则文件时走内置缺省 RF 规则集
```

```python
from rfauto.service.drc_service import validate_design_file
env = validate_design_file("board.json", "rules.csv", rf=True)
print(env["verdict"], env["violations"])   # issues/attention/clean + 违规清单
```

**已知限制**：规则类型注册表外的未知 type 如实保留+warning 不判；度量
缺测=unknown 不算 fail（不伪造违规）；design 必须是含 objects 列表的
JSON（coordinate_unit 长度族）；内置缺省 RF 规则集是保守通用档（数值=
确定性内核静态常量，`--rules` 覆盖）；违规≠调用失败（ok=True 照常，
verdict 在信封内）。

## 10. LVS 网表对照（Layout vs Schematic）

**是什么**：两份网表（SPICE 三格式或 Verilog 门级）的拓扑一致性比对：
双源归一化+1-WL 颜色精化剪枝+元件回溯图同构+同构映射下逐对参数相对
容差比对；`--rf` 加 S 参数端口数量/序号/阻抗与传输线拓扑分类比对。
verdict 三分：MATCH / MISMATCH（结构性不一致）/ PARTIAL（值级出窗或
同构预算耗尽不可判定）。

**仓内入口**：service 单源 `compare_netlist_files(layout_path,
schematic_path, tolerance=0.01, rf=False, fmt="auto",
iso_step_budget=None)` / `compare_netlist_texts(...)` /
`detect_netlist_format(text)`（`rfauto/service/lvs_compare_service.py`，
只读消费 SPICE/Verilog 两个解析内核）→ CLI `rfauto lvs compare <layout>
<schematic> [--tolerance 0.01] [--rf/--no-rf] [--format auto|spice|
verilog] [--json]`（MATCH=0 其余 exit 1）→ MCP `lvs_compare_files`。

**最小用例**：

```bash
rfauto lvs compare layout.sp schematic.sp --rf --json
```

```python
from rfauto.service.lvs_compare_service import compare_netlist_files
env = compare_netlist_files("layout.sp", "schematic.sp", tolerance=0.01)
print(env["verdict"], env["score"], env["differences"])
```

**已知限制**：SPICE 侧只对照顶层 scope（子电路体不展开——与解析器口径
一致）；Verilog schema 不识时兜底内置最小门级归一器（切换在信封
`layout.verilog_parser_source`=core|builtin 如实披露）；对称族
（R/L/C）两引脚可翻转、其余族引脚序固定（二极管翻转=MISMATCH 是结构
判定）；同构预算耗尽如实 PARTIAL 不猜。

## 11. GDSII 版图（Stream 格式）

**是什么**：版图交换事实标准 GDSII 的纯 Python 字节级确定性解析（零
第三方依赖）：记录流状态机+GDS 实数逐位手解（56/24 位尾数整数舍入禁
float 先转）+库/结构/SREF/AREF/BOUNDARY/PATH/TEXT/BOX 全结构+UNITS
DBU 双值+层级拓扑三函数（引用计数/层汇总/包围盒展开）。

**仓内入口**：core `parse_gdsii_file(path)` / `parse_gdsii_bytes(data)` /
`gdsii_hierarchy_stats(doc)` / `gdsii_layer_summary(doc)` /
`gdsii_expand_bbox(doc, name)` / `dbu_to_um(value_dbu, units)`
（`rfauto/core/gdsii_parser.py`）→ service `parse_gdsii_file(path)` /
`gdsii_layer_report(path)` / `gdsii_hierarchy_report(path)` → CLI
`rfauto gdsii parse --file <x.gds> [--json]`、`rfauto gdsii layers
--file <x.gds> [--json]`（**待接线**）。

**最小用例**（service 现在就能用）：

```python
from rfauto.service.gdsii_service import gdsii_hierarchy_report, parse_gdsii_file
env = parse_gdsii_file("top.gds")
print(env["lib_name"], env["stats"]["n_structures"])
hier = gdsii_hierarchy_report("top.gds")     # 引用计数/未定义引用/孤儿双桶
```

**已知限制**：任意角度/mag≠1 的引用不展开（expand_bbox 如实 skip 带
reason——宁 skip 不近似）；仅 0/90/180/270 精确展开；NODE/TEXTNODE
契约外跳过；截断文件 fail-soft `truncated=True`；非 ASCII 字节按
U+FFFD 如实显示不猜编码。另有统计级速览面：MCP `format_overview`
（kind=gdsii，见 §20）。

## 12. LEF/DEF 物理设计（5.8 子集）

**是什么**：OpenLane/OpenROAD 流程骨干交换格式：LEF（层/via/site/
单元 macro 抽象）与 DEF（diearea/components/pins/nets 走线段拓扑）的
只读解析；DEF 坐标 DBU→µm 按 UNITS 换算；交叉校验三函数（单元闭合/
网连接度/引脚名对齐），`lefdef check` 汇总 verdict=clean/attention/
issues。

**仓内入口**：core `parse_lef(text)` / `parse_def(text)` /
`def_component_macro_closure(def_doc, lef)` / `def_net_connectivity(
def_doc)` / `def_pin_lef_alignment(def_doc, lef, macro=None)`
（`rfauto/core/lef_def_parser.py`）→ service `parse_lef_file(path)` /
`parse_def_file(path)` / `parse_lef_def(lef_paths=None, def_path=None)` /
`lef_def_check(lef_paths, def_path, macro=None)` → CLI `rfauto lefdef
parse [--lef x.lef ...] [--def d.def] [--json]`、`rfauto lefdef check
--lef ... --def ... [--macro NAME] [--json]`（**待接线**）。

**最小用例**（service 现在就能用）：

```python
from rfauto.service.lef_def_service import lef_def_check, parse_def_file, parse_lef_file
lef = parse_lef_file("cells.lef")
def_env = parse_def_file("design.def")
chk = lef_def_check(["cells.lef"], "design.def")
print(chk["verdict"], chk["closure"], chk["connectivity"])
```

**已知限制**：5.8 语法子集——未建模块（ANTENNA*/PROPERTY/
SPACINGTABLE/REGIONS/BLOCKAGES/FILLS 等）整块跳过并登记；DEF 缺 UNITS
时 `*_um` 如实 None+warning（不臆造换算因子）；LEF/DEF 无方向语义
（驱动/负载判定不做，宁不报不误报）；走线段 layer=段首声明层（段内经
via 换层不追踪）。

## 13. Gerber 光绘与 Excellon 钻孔（RS-274X / CNC-7）

**是什么**：PCB 制造面双解析：Gerber RS-274X 指令级状态机（FS 定长
Fraction 精确解码+aperture/AM 宏+弧段+区域逐环+包络盒）与 Excellon
钻孔（刀具登记/钻点/G85 槽孔/最近邻孔距统计）；两件合跑做孔位落板
bbox 越界交叉校验。与既有统计级 `gerber_overview_service` 分工不同
（那是声明聚合，本集群是指令级解析）。

**仓内入口**：core `parse_gerber(text)` / `gerber_bbox(doc)` /
`gerber_layer_summary(doc)`（`rfauto/core/gerber_parser.py`）；
`parse_excellon(text)` / `excellon_hit_grid_summary(doc)`
（`rfauto/core/excellon_parser.py`）→ service `parse_gerber_file(path)` /
`parse_excellon_file(path)` / `summarize_gerber(path)` /
`gerber_excellon_pair_check(gerber_path, drill_path)`
（`rfauto/service/fab_gerber_service.py`）→ CLI（fab 组内，已接线）
`rfauto fab parse --gerber <x.gbr> [--drill x.drl] [--json]`、
`rfauto fab summary --gerber <x.gbr> [--json]`。

**最小用例**：

```bash
rfauto fab parse --gerber top.gbr --drill top.drl --json   # 解析+配对校验
rfauto fab summary --gerber top.gbr                         # D 码分组摘要+包络盒
```

```python
from rfauto.service.fab_gerber_service import gerber_excellon_pair_check, parse_gerber_file
env = parse_gerber_file("top.gbr")
pair = gerber_excellon_pair_check("top.gbr", "top.drl")
print(pair["n_hits"], pair["n_out_of_bounds"])
```

**已知限制**：弧段 endpoint-only bbox（I/J 圆心鼓出未展开，恒声明）；
AM 宏不展开不做参数代换（expanded=False 如实）；槽孔只解单行两对 G85
形态；LP 极性只登记不清算叠加；Excellon 头部不声明位数——缺省按
6 位定标（`decimals_source` 键如实回显，X2 注释出现时按注释位数）；
M97/M98/R step-repeat 登记不展开。

## 14. SPEF 寄生网表（IEEE 1481）

**是什么**：数字后端寄生提取交换格式只读解析：头部单位三元组
（T/C/R/L_UNIT 表驱动换算）+`*NAME_MAP` 长名折叠双向映射+`*D_NET`
四段状态机（CONN/CAP/RES/IND）+拓扑三函数（连通分量/耦合 top-k/孤立
节点）+cap 总量一致性三数字报告。

**仓内入口**：core `parse_spef(text)` / `spef_topology_summary(doc)` /
`spef_coupling_stats(doc, top_k=5)` / `spef_net_lookup(doc, name)` /
`spef_unit_factor(kind, unit)`（`rfauto/core/spef_parser.py`）→ service
`parse_spef_file(path)` / `spef_report(path, top_k=5)` /
`spef_net_detail(path, name)` → CLI `rfauto spef parse --file <x.spef>
[--json]`、`rfauto spef report --file <x.spef> [--top-k N] [--json]`
（**待接线**）。

**最小用例**（service 现在就能用）：

```python
from rfauto.service.spef_service import parse_spef_file, spef_net_detail, spef_report
env = parse_spef_file("top.spef")
print([n["name"] for n in env["nets"]])
print(spef_net_detail("top.spef", "clk")["topology"])
rep = spef_report("top.spef", top_k=5)      # 耦合电容 top-k+连通分量
```

**已知限制**：三值数值（min:typ:max）未支持——warning 整行跳过（真实
提取器若用三值形态数据会静默变少）；`*R_NET`/`*D_PNET`/`*POWER_NETS`/
`*DEFINE` 未覆盖；未知单位 fail-closed（warning+系数 1.0 原值保留）；
反斜杠转义原样保留。

## 15. SDF 时序标注（IEEE 1497）

**是什么**：STA 输出/门级仿真反标的标准延迟格式只读解析，两层结构：
S 表达式词法（栈式零递归+深度守卫）+语义层（头部 TIMESCALE 18 档表
驱动换算到秒、CELL 段 IOPATH/COND/INTERCONNECT/十二类 TIMINGCHECK、
三元组 min:typ:max 空槽 None）；查询三函数（cell 查找/延迟路径平坦
清单/时序检查摘要）。

**仓内入口**：core `parse_sexpr(text, max_depth=512)` / `parse_sdf(text)`
/ `sdf_cell_lookup(doc, celltype, instance=None)` / `sdf_delay_paths(
doc, celltype)` / `sdf_timing_check_summary(doc)` /
`parse_sdf_triple(text, timescale_factor=None)`（`rfauto/core/
sdf_parser.py`）→ service `parse_sdf_file(path)` / `sdf_report(path)` /
`sdf_cell_detail(path, celltype, instance=None)` → CLI `rfauto sdf parse
--file <x.sdf> [--json]`、`rfauto sdf report --file <x.sdf> [--json]`
（**待接线**）。

**最小用例**（service 现在就能用）：

```python
from rfauto.service.sdf_service import parse_sdf_file, sdf_cell_detail
env = parse_sdf_file("top.sdf")
print(env["header"]["timescale"]["factor_s"], [c["celltype"] for c in env["cells"]])
det = sdf_cell_detail("top.sdf", "DFF_X1", instance="u_core/u_ff1")   # 精确实例命中（同 CELLTYPE 通配条目一并返回）
paths = det["delay_paths"]
```

**已知限制**：TIMESCALE 表外值（乘数 5、单位 xs）fail-closed 抛错
（绝不静默猜量纲）；TIMINGENV/LABEL 面外构造 warning+原文保留；DIVIDER
缺省按 IEEE 1497 是 `.`（部分工具内部惯用 `/`——跨工具对拍留意）；
条件块 COND 只携带表达式原文不求值。

## 16. IPC-D-356 裸板测试网表（356/356A）

**是什么**：PCB 制造三件套的电气测试面事实标准（KiCad/Altium 导出、
飞针/测试架具消费）只读记录级解析：头部 C 因子坐标换算+记录状态机
（元件/焊盘·V 节点/过孔/DIP 轴向/非测试面引脚/夹具探针）+net→pads
测试点拓扑+单点 net（开路嫌疑）统计；与 Gerber/Excellon 做配对交叉
校验。

**仓内入口**：core `parse_ipc356(text)` / `ipc356_net_pads(doc, net)` /
`ipc356_component_pins(doc, refdes)` / `ipc356_single_point_nets(doc)` /
`scale_to_mm(raw, scale_factor)`（`rfauto/core/ipc356_parser.py`）→
service `parse_ipc356_file(path)` / `ipc356_report(path)` /
`ipc356_fab_pair_check(ipc_path, gerber_path=None, drill_path=None,
tol_mm=0.5)` → CLI `rfauto ipc356 report --file <x.d356>
[--check-gerber x.gbr] [--check-drill x.drl] [--json]`（**待接线**）。

**最小用例**（service 现在就能用）：

```python
from rfauto.service.ipc356_service import ipc356_fab_pair_check, ipc356_report
rep = ipc356_report("board.d356")
print(rep["single_point_nets"])                # 开路嫌疑 net 清单
pair = ipc356_fab_pair_check("board.d356", gerber_path="top.gbr",
                             drill_path="top.drl", tol_mm=0.5)
print(pair["n_out_of_bounds"], pair["n_uncovered"])
```

**已知限制**：C 因子换算口径为战役钉定（未逐条对原版规范核验）；EOF
标记按 KiCad 惯例钉 9999（00000 兼容），缺标记 `truncated=True` 不报
错；356 旧式为 tag 扫描非逐列位语义（designator 内嵌 X<数字> 形态会
误读）；过孔不入 nets 映射（测试点口径，自带 net 字段如实保留）。

## 17. Touchstone S 参数（.sNp）

**是什么**：S 参数文件统一解析内核——#248/#287/#309 三坑经验单源化：
rank 三规则嗅探（文件名/首行值数/块结构，冲突宁 UNKNOWN 不猜）+
RI/MA/DB 三格式解码+频轴 ulp 对齐工具+Σ模数形状判定+无源性健康统计
+skrf 桥（与 skrf 直读全 parity 对拍）。

**仓内入口**：core `sniff_touchstone(path)` / `parse_touchstone(path)` /
`align_freq_axis(a, b, rtol=1e-9)` / `detect_mode_data_shape(path,
n_ports_declared)` / `matrix_health(s_matrix, eps=0.001)` /
`to_skrf_network(parsed)`（`rfauto/core/touchstone_parser.py`）→
service `touchstone_info(path)` / `parse_touchstone_file(path)` /
`touchstone_report(path)` → CLI `rfauto touchstone info --file <x.s2p>
[--json]`（**待接线**）。

**最小用例**（service 现在就能用）：

```python
from rfauto.service.touchstone_service import parse_touchstone_file, touchstone_info
info = touchstone_info("device.s2p")
print(info["n_ports"], info["rank"], info["disagreements"])  # 冲突宁 UNKNOWN
env = parse_touchstone_file("device.s2p")     # s_matrix 为 [re, im] 对嵌套
print(env["health"])
```

**已知限制**：noise 参数段（Γopt/Rn）登记不解释；v2.0 [Matrix Format]
仅 Full；2 端口缺 [Two-Port Data Order] 按规范默认 rows_12_21+warning
（skrf 同场景按 legacy 列序——口径差已入 warnings）；v1.0 规则②单独
不可采信（宁 UNKNOWN）；[Reference] 不支持跨行延续；矩阵 JSON 化超
cap 只留首频点 preview+截断旗标。写出侧见 `rfauto interop ts21-write`
（TS 2.1 写出）；统计级速览见 MCP `format_overview`（kind=touchstone）。

## 18. SKILL/OCEAN 源码（解析面）

**是什么**：Cadence SKILL（Lisp 方言）与 OCEAN 的只读静态解析：S 表达式
词法（含 SKILL 惯用 `f(` 调用糖折叠，栈式零递归+深度守卫）+结构提取
（define/defun 盘点、API 调用清单按 ocean/virtuoso/generic 前缀分桶、
全局赋值面）+静态调用边+literal_eval（字面量可求值，非字面量
fail-closed）。**只读静态分析，永不执行被解析代码**。

**仓内入口**：core `parse_skill(text, max_depth=512)` /
`skill_definitions(tree)` / `skill_api_calls(tree)` / `skill_globals(
tree)` / `skill_call_edges(tree)` / `skill_literal_eval(node)`
（`rfauto/core/skill_parser.py`）→ service `parse_skill_file(path)` /
`skill_report(path)` / `skill_call_graph(path)`
（`rfauto/service/skill_service.py` Q-X62 加性节；同文件的 recipe/card
族函数是另一件事——SKILL 模板**生成**面）→ CLI `rfauto skill-parse
parse --file <x.il> [--json]`、`rfauto skill-parse report --file <x.il>
[--json]`（**待接线**；接线顶层名必须≠`skill`——`skill` 组已被模板
生成器占用）。

**最小用例**（service 现在就能用）：

```python
from rfauto.service.skill_service import parse_skill_file, skill_call_graph, skill_report
rep = skill_report("main.il")
print(rep["definitions"], rep["api"]["by_bucket"]["ocean"])   # define 盘点+OCEAN 调用桶
graph = skill_call_graph("main.il")
print(graph["n_edges"], graph["n_external"])
```

**已知限制**：调用图无作用域分析（调用归属最近包围定义，按符号名匹配
同名 define）；中缀表达式首操作数计 generic 调用；let 绑定表按扁平
var/val 剪除；数组下标糖 `x[1]` 不折叠；literal_eval 除法恒真除。
注意区分：`rfauto skill list/render/lint`（已接线）是 Q-X32 模板生成
器，与本文的解析面无依赖关系。

## 19. VCD 波形（IEEE 1364 Value Change Dump）

**是什么**：数字仿真波形交换事实标准（iverilog/Verilator 全走此链）
只读解析：声明段状态机（$timescale 表驱动 fail-closed/$scope 嵌套栈/
$var 表）+数值段三类值事件流（标量/向量/实数，x/z 如实字符串分型）
+$dumpoff 窗口登记+查询三函数（变量查找/信号事件画像/时间窗）+活跃度
top。

**仓内入口**：core `parse_vcd(text)` / `parse_timescale(raw)` /
`vcd_var_lookup(doc, name, scope=None)` / `vcd_signal_profile(doc,
var_id)` / `vcd_time_windows(doc)` / `vcd_activity_top(doc, top_n=10)`
（`rfauto/core/vcd_parser.py`）→ service `parse_vcd_file(path)` /
`vcd_report(path, top_n=10)` / `vcd_var_detail(path, name, scope=None)`
→ CLI `rfauto vcd parse --file <x.vcd> [--json]`、`rfauto vcd report
--file <x.vcd> [--top N] [--json]`（**待接线**）。

**最小用例**（service 现在就能用）：

```python
from rfauto.service.vcd_service import parse_vcd_file, vcd_var_detail, vcd_report
env = parse_vcd_file("dump.vcd")
det = vcd_var_detail("dump.vcd", "clk")      # 命中变量的事件流
print(det["n_matches"], len(det["matches"][0]["events"]))
rep = vcd_report("dump.vcd", top_n=5)        # 活跃度 top+时间窗
```

**已知限制**：$dumpports 只计数登记不解析；无流式/分块模式（全文读入）；
$var id 冲突后列覆盖——被覆盖 var 的层级名不可再查（事件按 id 合并如实
保留）；转义标识符 `\name` 不特判按原文收。

## 20. 相邻面与延伸阅读

与解析器集群相邻的既有面（互链，非本文范围）：

- **格式速览（一屏看懂）**：MCP 工具 `format_overview(path, kind)`——
  8 kind（touchstone/kicad_pcb/drawio/gdsii/dxf/ipc2581/odbpp/ads_ds）
  的统计级速览信封，与本文的指令级/记录级深解析互补（专有格式 ADS .ds
  只有速览面）；
- **Gerber 统计级读面**：`service/gerber_overview_service.py`（T-Q6 席，
  声明聚合口径）——与 §13 指令级解析分工不同，两模块零 import 关系；
- **写出/互操作侧**：`rfauto interop ts21-write`（Touchstone 2.1 写出）
  与 `rfauto interop hfss-comments`（HFSS 注释块直读）；`rfauto layout
  build --fmt gdsii|dxf|ipc2581|odbpp`（版图互操作四格式生成/读入）；
- **KiCad 制造链**：`rfauto kicad gerber`（板→Gerber X2+Excellon 导出）
  ——其产物正是 §13/§16 三件套解析器的典型输入；
- **fab 交付链**：`rfauto fab go/pipeline/audit/...`（HFSS→可机加交付
  包）——§13 两叶挂在 fab 组内；
- **格式陷阱与席位级细节**：仓内 `docs/rf_template_references.md` §21
  "EDA 格式解析器集成指南"（五格式逐个陷阱表+接新格式位次），仓内文档
  不上站，读仓库源文件；
- **CLI 全参数表**：[CLI 命令参考](../reference/cli.md)（机读再生，与
  实注册同源）；**MCP 工具清单**：[MCP 工具参考](../reference/mcp.md)。

接新格式的位次（照抄既有先例）：core 纯函数（零依赖、ParseError 带行
号）→ service 信封（文件 IO 收敛）→ CLI parse/list 叶（带 --json）→
（如涉 RF 数值）skrf 桥放 service 不进 core（CITI 先例）。
