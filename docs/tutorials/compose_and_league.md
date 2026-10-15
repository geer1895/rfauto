# compose 组合链与引擎联赛

> 单个模板调完，怎么把 msl↔SIW 过渡段和 SIW 段拼成一条链一次仿真？多
> 个引擎（HFSS/openEMS/fake…）各跑了一堆 run，怎么回答"哪个引擎在该器
> 件族上又快又准"？本文讲两件正交的工具：**compose**（netlist YAML →
> 单一 simulation.py 的几何组合器，含组合前的端口兼容快审面）与
> **league**（runs/ 证据面抽取的引擎联赛表）。文中输出全部为当前工作区
> 只读实测；落盘/重建类命令给读法不代跑，守卫失败样例照录原文。

## 0. 前置与三个名字

- 已按 docs/tutorials/getting-started.md 装好环境；compose 产物是
  openEMS 渲染脚本，真跑组合产物需要 openEMS 通道（见
  docs/tutorials/real-simulation.md），本文的组合/审计/榜单本身零
  license。
- 命令一律走 `.venv/Scripts/rfauto.exe`（`python -m rfauto` 不是有效
  CLI 入口）。
- 三个名字别混（服务层各一个模块，#222 实测）：

| 名字 | 模块 | 一句话 |
|---|---|---|
| 组合器 | `service/compose_service.py`（DP-8） | netlist 三段式 → 摆位求解 + 守卫 → 单一 simulation.py |
| 链审计 | `service/compose_chain_audit_service.py` | **不摆位不渲染**，只回答"这条链的端口面兼容吗" |
| 联赛 | `service/league_service.py`（DP-17 W1） | runs/ 证据面 → engine_league 表 → 各引擎 Pareto 榜 |

## 1. 台账：哪些模板能组合

```bash
.venv/Scripts/rfauto.exe compose-templates
```

实测输出（组合契约是 opt-in 注册表，当前 2 个模板）：

```
             组合契约模板（2 个，DP-8 opt-in）
┌───────────────┬─────┬───────────┬───────────┬───────────┐
│ template      │ pin │ port_type │ z_ref_ohm │ direction │
├───────────────┼─────┼───────────┼───────────┼───────────┤
│ msl_siw_taper │ msl │ msl       │ 50.0      │ [0, -1]   │
│               │ siw │ lumped    │ None      │ [0, 1]    │
│ siw           │ p1  │ lumped    │ None      │ [0, -1]   │
│               │ p2  │ lumped    │ None      │ [0, 1]    │
└───────────────┴─────┴───────────┴───────────┴───────────┘
```

读法：每个模板声明若干 **pin**（连接面）——port_type 是端口形态
（msl=微带波端口 / lumped=集总），direction 是朝向（±轴），z_ref_ohm
是阻抗基准（None=由契约 layout 按带内实算）。组合就是把 A 的 outlet
pin 吸附到 B 的 inlet pin。想扩自己的模板进组合，实现契约
`layout(params, band, base_m, h_m, frame) → {pins, primitives, …}` 并
注册进 `COMPOSE_CONTRACTS`（契约字段全表见
`core/compose/layout_netlist.py` 模块头）。

## 2. 场景一：SIW 过渡链一次成型

### 2.1 netlist 三段式

netlist 是 rfauto-netlist-v1 三段式（instances / connections /
exposed_ports，与 gdsfactory 同构）。仓内 golden 首例
（`compose_service.GOLDEN_NETLISTS["siw_chain"]`，测试与示例共用单一
事实源，原文照录）：

```yaml
schema: rfauto-netlist-v1
band_ghz: [9.75, 10.25]
mesh_resolution_mm: 0.4
substrate: {h_mm: 0.508, er: 3.66, tan_d: 0.0037}
instances:
  - {id: taper_in,  template: msl_siw_taper, params: {siw_len_mm: 2.8}}
  - {id: run,       template: siw,           params: {}}
  - {id: taper_out, template: msl_siw_taper, params: {siw_len_mm: 2.8}}
connections:
  - {a: [taper_in, siw],  b: [run, p1]}
  - {a: [run, p2],        b: [taper_out, siw]}
exposed_ports:
  - {instance: taper_in,  pin: msl}
  - {instance: taper_out, pin: msl}
global_params: {excite_port: 1, nrts: 100000}
```

读法：`connections` 声明"谁的哪个 pin 吸附谁的哪个 pin"（摆位由此求
解：首实例 identity，其余 rot180+平移——不可对向/斜摆显式报错不静
默）；`exposed_ports` 的**书写顺序 = FDTD 端口编号 1..M**；
`mesh_resolution_mm: 0` 表示自动 λ_sub/50。

### 2.2 rfauto compose：三件套落盘

```bash
.venv/Scripts/rfauto.exe compose netlist.yaml --out-dir runs/compose_out
```

（落盘类，本文不代跑；旗标 `--out-dir/-o` 必给，`--json/-j` 信封。）
产物三件套：`simulation.py`（可直接跑的组合渲染脚本）+
`compose_meta.json`（确定性 provenance）+ `netlist.yaml`（回写副本）。
组合引擎**不做渲染文本拼接**——逐实例契约 layout→帧仿射→合并→单一发
射器逐条渲染，杜绝 CSX/FDTD/mesh 头尾重复。

组合结果长什么样（golden 链经服务层内存态入口实测，零落盘）：

- 11 项守卫全 ok：`guards: {P1…P5: ok, D1…D6: ok}`（守卫表见 §5）；
- 端口重编号：`exposed_ports: [{port_nr: 1, instance: taper_in, pin:
  msl, port_type: msl, z_ref_ohm: 50.0}, {port_nr: 2, …}]`；
- 预算估算：`estimates: {dt_s: 4.64e-14, nrts: 100000, time_window_s:
  4.64e-09}`（dt 为上限口径——真预算按终网格 CFL 实算，#328）；
- 指纹：`render_sha256: f4b6eb25d090ab5d…`（组合是确定性的：同
  netlist 重跑逐字节同，meta 无时间戳）；
- `simulation.py` 实测 550 行、自包含（DLL 目录处理内嵌），
  `compose_meta.json` 的 `render_sha256/netlist_sha256` 可用服务层
  `verify_compose_provenance(out_dir)` 复验（重渲染对账，C5 预演）。

失败语义实测（把 connection 指到不存在的 pin，内存态复现）：

```
ok: False
error: connection 引用未声明 pin: taper_in.siw/run.nope
       （契约 pin 集=['msl', 'siw']/['p1', 'p2']）
```

守卫失败（P1-P5/D1-D6 任一）同风格：显式 ValueError 报**双 pin id +
坐标 + 差值**，不静默吞。MCP 侧同款能力：`compose_netlist` 工具
（`out_dir=None` 时纯内存态，见 docs/tutorials/mcp_in_practice.md）。

## 3. 场景二：组合前快审——compose_chain_audit

写 netlist 之前想先问"这两块积木的端口面根本接不上吗"？链审计面专
干这个：**不摆位不渲染**，逐实例调契约 layout（identity frame）自动
配对相邻实例的 outlet→inlet，出 P2/P3/P5 同容差的兼容报告 + 暴露端口
方案 + D5 边界类/D6 基板一致性预检。verdict 三态：`clean`（全兼容）/
`attention`（有 unknown，如契约缺）/`issues`（有实打实 mismatch）。

#222 如实注记：**该面当前是纯 service 面**（`compose_chain_audit`
函数，JSON 进出），CLI/MCP 零接线，消费方式：

```bash
.venv/Scripts/python.exe -c "
from rfauto.service.compose_chain_audit_service import compose_chain_audit
r = compose_chain_audit({
  'chain': [{'template': 'msl_siw_taper', 'params': {'siw_len_mm': 2.8}},
            {'template': 'siw'}],
  'band_ghz': [9.75, 10.25], 'mesh_resolution_mm': 0.4})
print(r['verdict'], r['summary'])
"
```

两态实测（当前工作区照录）：

- **两实例线性链**（taper→siw）：`verdict=clean`，结 siw→p1
  compatible（z 22.84Ω→22.84Ω），暴露方案 = 首 inlet（msl）+ 末
  outlet（p2），`d4_emittable: true`；
- **未知模板**：`verdict=attention`，`unknown_instances` 给原因原文
  `"模板 'nope' 无组合契约（可用: ['msl_siw_taper', 'siw']）"`。

**一个必须知道的局限**（实测撞到过）：把 golden 三实例链
[taper, siw, taper] 喂给链审计会得 `verdict=issues`——审计按链序自动
配对，把 siw 的 outlet p2 配到了末实例 identity 朝向的 **msl** pin
（z 22.84Ω vs 50Ω → mismatch），而 golden netlist 里末实例是 rot180
摆位、经 **siw** pin 连接。这不是组合器有错：审计的理由栏自己写着
**"显式 connections 走组合器"**——线性同向链用快审，含翻转/异构连接
的链直接上组合器（守卫会兜底）。审计报 issues ≠ 链不可组合，先看配对
标签再下结论。

## 4. 场景三：引擎联赛——db league-rebuild / league-report

多引擎对拍（同一配方在 hfss/openems/fake 各跑过一批 run）后，联赛面
把 runs/ 证据面抽成一张表回答"该器件族上哪个引擎又准又快"。

### 4.1 两步走：rebuild（重建表）→ report（读榜）

```bash
.venv/Scripts/rfauto.exe db league-rebuild          # runs/ 证据 → runs/league.duckdb
.venv/Scripts/rfauto.exe db league-report --family mline --json
```

- `league-rebuild`（旗标 `--runs-dir/--db/--json`）：**落盘类本文不代
  跑**。语义读法：runs/ 证据面只读抽取（唯一写面=league.duckdb 自身，
  运行时产物不进 git）；来源 A=meta.json（adapter/model/metrics/
  wall_s…），来源 B=verdict 类工件（verdict*/judg*/gate*/arbitration*
  .json 经四形态读取器归一到白名单；markdown verdict 非机器可读一律
  skip 计数不猜，#321 未知形态如实 skip）。事务内全删全插——**确定性
  输入下二次 rebuild 内容逐字节不变**（幂等，有 content hash 度量）。
- `league-report`（旗标 `--family/--quantity/--db/--json`）：只读，
  按（模板族，量）分组出各引擎 **|delta_vs_ref| 中位 × wall_s 中位**
  的 Pareto 前沿，JSON+md 双出。参考引擎缺省 **hfss**（对齐基准立
  规）：同组内按设计点配对，引擎==ref 的行 delta=0 恒成立且不进 delta
  轴；组内无数值 ref 的行 delta=NULL 不硬凑。

### 4.2 读榜：一张真实报告

当前工作区 `rfauto db league-report --json` 实测（league.duckdb 在册
2189 行）：12 个（族，量）分组，引擎行数分布 fake=2052 / hfss=86 /
openems=48 / mf:fake+hfss=2 / p0_gate:asset_reuse=1，覆盖 5 个模板
族。分组行结构实测：

```json
{"template_family": "branchline_coupler",
 "quantity": "s11_db_max_in_band",
 "engines": [
  {"engine": "fake", "n_rows": 1, "median_abs_delta": null,
   "median_wall_s": null, "on_front": null, "p_raw": null,
   "p_adj": null, "sig_reject": false},
  {"engine": "hfss", "n_rows": 4, …}]}
```

读法三条（都是"如实"语义，不是缺数据 bug）：

- **`on_front=null` = 该引擎缺某一轴**（delta 或 wall_s 无非空值），
  不硬凑前沿。当前库的 delta 轴恰为空（跨引擎同设计点配对尚未形成），
  所以全表无前沿——要让榜单"亮起来"，得对同一族同一量跑**成对的跨引
  擎 run**（同配方 `--adapter hfss` 与 `--adapter openems` 各一轮）。
- **`p_raw/p_adj/sig_reject`（S-1 显著性列）**：组内 Dunnett（各引擎
  vs 参考引擎）+ BH 多重校正，`sig_reject = p_adj < 0.05`；样本不足/
  零方差时 None/None/False **如实不判**。前沿只回答"谁更快更准"，
  sig_reject 才回答"差异是不是噪声"。
- `quantity=gate_verdict` 的裁决登记行与 `engine=unknown` 不进前沿
  （无物理量纲）；量名带单位 token（#121），过滤 `--quantity` 时照
  台账原文名传。

想绕过报告直接查表：league.duckdb 是普通 DuckDB 库，只读连接
`SELECT … FROM engine_league`（12 列 schema 见
`league_service.ENGINE_LEAGUE_COLUMNS`，主键 (run_id, engine,
quantity)）。注册表另一面 `rfauto db status/query` 查的是
registry.sqlite，与联赛库是两个文件——别混。

## 5. 守卫速查（P=连接，D=合并）

组合失败报错里的守卫代号（`core/compose/layout_netlist.py` 模块头口
径，全文以代码为准）：

| 族 | 代号 | 拦什么 |
|---|---|---|
| P1-P5 | 连接守卫 | P1 位置共点 / P2 方向对向 / P3 阻抗 / P4 参考面（pin 面到远端跨度）/ P5 截面 |
| D1-D6 | 合并守卫 | D1 域合并+暴露端口贴界与净距 / D2 结缝导体覆盖（顶板/底板）/ D3 网格衔接 / D4 端口重编 / D5 边界类一致性 / D6 基板一致性 |

链审计面复用同容差判据（单源自 layout_netlist，禁双头），并额外报
D4 可发射性（暴露端口形态须 ∈ {lumped, msl}）与 D5/D6 预检。

## 6. 下一步

- 组合产物真跑与判读（openEMS 通道）：docs/tutorials/real-simulation.md
- 多引擎对拍的 verdict/仲裁语义：docs/tutorials/anchor-guide.md 与
  docs/how-to/read-verdict-gates.md
- run 级对比（runs compare N-way）与数据集沉淀：
  docs/tutorials/datasets_and_health_gates.md
- netlist schema 与契约字段权威出处：`src/rfauto/core/compose/
  layout_netlist.py` 模块头（本文引语均出自该处原文）

## 附：本文核对清单

| 项 | 核对方式 | 结果 |
|---|---|---|
| `rfauto compose-templates` 台账（2 模板/4 pin） | 只读实跑 | 过（§1 表格照录） |
| netlist 三段式与 golden 首例 | `compose_service.GOLDEN_NETLISTS` 实读照录 | 过 |
| `rfauto compose --help`（--out-dir 必给/--json） | 实跑 | 过 |
| 组合确定性输出（11 守卫 ok/端口重编/estimates/render_sha256/550 行脚本） | 服务层内存态入口实调（零落盘） | 过（§2.2 数据照录） |
| 失败语义（未声明 pin 报错原文） | 内存态复现实调 | 过（错误原文照录） |
| provenance 复验面 | `verify_compose_provenance` docstring 实读 | 过 |
| 链审计 verdict 三态与两态实测（clean/attention） | 服务函数只读实调 | 过（§3 输出照录） |
| 三实例链 issues = 自动配对局限（显式 connections 走组合器） | 只读实调 + junction 详情核对 | 过（z 22.84 vs 50 mismatch 定位） |
| 链审计为纯 service 面（CLI/MCP 零接线） | cli/mcp_tools 全域 grep `compose_chain_audit` | 过（仅 tests 消费） |
| `db league-rebuild/--report --help` | 实跑 | 过（旗标逐条对） |
| league 语义（来源 A/B、delta 配对、ref=hfss、幂等全删全插） | `league_service.py` 模块头+rebuild/league_report docstring 实读 | 过 |
| 真实榜单（2189 行/12 组/引擎分布/on_front=NULL 诚实口径） | `league-report --json` 只读实跑 + duckdb 只读直查 | 过（§4.2 照录） |
| S-1 Dunnett+BH 显著性列与"如实不判" | league_report docstring + `_group_significance` 实读 | 过 |
| league.duckdb ≠ registry.sqlite（db query 查的是后者） | `db status` 只读实跑 + 路径实读 | 过（runs=1779 行/联赛库另存） |
| 守卫 P1-P5/D1-D6 代号表 | `layout_netlist.py` 模块头实读 | 过 |
