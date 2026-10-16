# EDB 快车道用户指南：五族发射器 → 批处理求解 → Touchstone 判读

> 状态：正式文档（2026-10-08 首版；2026-10-09 判读章扩写——
> 健康门判读语义演化史/判读终表/已知语义边界；同日
> §2 族表落地态回填——发射器签名/缺省/名义实跑值与 lange 拒绝语义行）。
> 定位：EDB 快车道的工程师操作面——平面族器件如何经**声明式 spec 发射 →
> PyEDB/hfss_batch 建库 → `ansysedt` 批处理求解 → Touchstone 判读**批量
> 生成数据集。会话污染/进程治理/看门狗等通用无人值守纪律的权威口径在
> `docs/unattended_hfss_automation.md`（本文只引用不重复）；PyEDB API 技
> 术事实的权威口径在 `docs/pyedb_distilled.md`（对照 0.83 实装源码逐条核
> 验版），本文 API 名逐字以源码为准。
> 证据基线：pyedb 0.83.0 × pyaedt 1.4.0 × skrf 2.1.0 × AEDT 2025 R1
> （v251），W1 真机冒烟已归档（判读报告为判读
> 正本）。`#NNN` 为本仓坑号。未经本机实测的口径标"待验证"。

---

## 1. 快车道是什么、何时用

EDB（Ansys Electronics Database）是**文件夹型分层版图数据库**。PyEDB 是
独立内存态 API——**无需桌面会话**即可读写 `.aedb`（但需要本机有合法许可
的 AEDT 安装，官方 README 口径）。把它与 AEDT 命令行批处理拼起来，平面
族器件的全链收敛为：

```text
发射器（纯函数，产 spec + config JSON）
  → 建库（.aedb 落盘，无桌面会话）
  → ansysedt -ng -BatchSolve（每求解一个独立短命进程）
  → 批后导出 Touchstone（第二段 -batchextract 短命进程）
  → skrf 判读（离线发射层门）
```

全链没有长驻桌面会话——`docs/unattended_hfss_automation.md` §2 那一整类
"一次失败赋值毒化会话"的故障**无处附着**。这是它值得每点多付 AEDT 启动
成本的根本理由（同一哲学在 openEMS 侧的先例=每求解一子进程，#208/#261）。

**适用**：平面/版图族器件的数据集批量生成（耦合器/功分器/滤波器版图实
现/封装 RDL）、overnight 战役、单点挂死看门击杀即止的无人值守队列。

**不适用（现阶段）**：全空气盒三维辐射结构（天线等）——几何是参数驱动
在 HFSS 3D 原生建的，EDB 不替代该主路径（§1.1/§1.2 口径不变）。

**对齐基准纪律**：HFSS 3D 通路是仲裁基准（用户立规）。EDB 快车道产物进
数据集走与既有通道相同的质量门交叉验证；冒烟已暴露的门语义/收敛档问题
（§6）按 #122 如实记 FAIL 不凑绿，留对拍仲裁。

---

## 2. 五族发射器（模板元面）

发射器全部是**纯函数**（零 IO 零 pyedb 依赖，pyedb 属 adapter 消费层），
`params dict → (spec dict, config_json dict)`。全部尺寸由
`core.synthesis` 闭式综合产出（`inverse_width` HJ 反解 + `forward_media`
εeff + λg/4 闭式）——**禁止手抄毫米数**（闭式综合纪律，#252）。

| 族 | 状态 | 端口 | 拓扑 | 源码入口 |
|---|---|---|---|---|
| edb_branchline | 已落地 | 4 | 角馈 branchline 矩形环 | `rfauto.adapters.edb_templates.branchline.emit_branchline_spec` |
| edb_power_divider | 已落地 | 3 | T 结 Wilkinson（RISO=2·Z0 隔离电阻） | `rfauto.adapters.edb_templates.power_divider.emit_power_divider_spec` |
| edb_coupled_line | 已落地（W3） | 4 | 平行耦合线后向波定向耦合器 | `rfauto.adapters.edb_templates.coupled_line.emit_coupled_line_spec` |
| edb_ratrace | 已落地（W3） | 4 | 180° 混合环（1.5λg，√2·Z0） | `rfauto.adapters.edb_templates.ratrace.emit_ratrace_spec` |
| edb_lange | 预留键（声明不支持） | 4 | 展开型 Lange 电桥（含 air-bridge） | `rfauto.adapters.edb_templates.lange.emit_lange_spec`（恒 NotImplementedError；升格前置条件见 `docs/templates/edb_lange/meta.yaml`） |

- 族白名单单源=`edb_templates.schema.KNOWN_TEMPLATES`（现值
  `("edb_branchline", "edb_power_divider")`；W3 已落地 coupled_line/
  ratrace 两发射器，经 `edb_lane_service._emitters` 分派表接入、
  validate_spec 的 "template 非法" 行由发射器侧过滤——`KNOWN_TEMPLATES`
  白名单升格仍为 followUp，schema.py docstring 单源；lange 预留键的
  status 族清单行随 `LANGE_EDB_SUPPORTED` 翻转）。
- **lange 拒绝语义（两层，已定谳非待办）**：直调 `emit_lange_spec` 时
  输入校验先行（坏入参 ValueError，branchline 同款），校验通过恒抛
  NotImplementedError（`LANGE_EDB_SUPPORTED=False`）；走服务层
  （`edb_emit_spec`/`edb_build`/CLI/MCP）归一为结构化拒绝信封
  （`{template, supported: false, reason, upgrade_doc}`，`upgrade_doc`
  指 `docs/templates/edb_lange/meta.yaml`）。拒绝理由=pyedb 0.83
  configuration 无 crossover/air-bridge 原语（同层跨越=金属合并短路）
  + 单层 U 形跳线平面性障碍（网络 A(指1/3)/B(指2/4) 端部交错连线，
  Jordan 曲线论证）+ 第二层埋线+过孔跳线近似未经真机仲裁；综合数值
  需求走 `lange_synth()`（与注册模板
  `oe_templates/render_c4.py::lange_design` 同函数同参）。
  裁定记录=`lange.py` docstring。
- 已落地发射器的最小用法（以 branchline 为例，其余族同构）：

```python
from rfauto.adapters.edb_templates import emit_branchline_spec

spec, config_json = emit_branchline_spec({"f0_ghz": 2.4})
# spec        ——五契约字段声明式版图规格（§3）
# config_json ——pyedb edb.configuration.load() 兼容 dict
```

- 落地发射器同签名 `(params) -> (spec, config_json)`；缺省档族间公共
  （schema 假设 7/8）：`f0_ghz` 必填、`z0_ohm` 仅 50、stackup 缺省
  rogers4350b_h0.508 标量、`copper_thickness_mm` 缺省 0.035、
  `board_margin_mm` 缺省 2.0、sweep 缺省 [0.7,1.3]·f0 401 点
  interpolation、adapt 单频 f0 `max_passes`=20。族差面：branchline/
  coupled_line/ratrace 的 `feed_len_mm` 缺省 5.0；power_divider 无该键
  （`in_len_mm` 缺省 10.0 / `out_len_mm` 缺省 5.0 结构常量，另有
  `gap_mm` 缺省 6.0+波端口扩展守卫，§8-4）；coupled_line 的
  `coupling_db` 缺省 10.0（KJ 反解 w/s）、其 `adapt.max_delta` 缺省
  0.02=W10 定谳回退档（§6.5 附注）。
- 名义实跑值（@2.5GHz 缺省层叠，发射器实跑产出、文档面
  `docs/templates/edb_*/meta.yaml`）：coupled_line（10dB 设计点）
  w=0.9243 / s=0.0820 / coupled_len=18.1469 / w_feed=1.1134 mm；
  ratrace w_ring=0.6035 / 方形环边长 27.2435（中心线周长 108.9741=
  1.5λg）/ w_feed=1.1134 mm；branchline/power_divider 见各自 meta.yaml
  nominal_params（另 §6.1/§6.2 有真机判读读数）；lange 无发射产出——
  `lange_synth` 综合核对基准 w=0.1672 / gap=0.0386 / 指长 18.9712 /
  w_feed=1.1117 mm（3dB 设计点，升格后产出承诺基准、非发射器实测）。

- **模板元数据**：`docs/templates/edb_*/meta.yaml`（五族各一份）。注意
  元面形态：edb_* 族**不是** `openems_templates.TEMPLATE_NOMINAL` 注册模
  板——`tests/unit/test_template_meta_consistency.py` 与
  `tests/unit/test_template_geometry_audit.py` 的 EXPECTED_TEMPLATES（冻
  结 72 项）不扫描它们；`scripts/build_docs_pages.py` 模板聚合页将非注册
  目录按信息文档排除。meta.yaml 内容=设计参数键面/名义参数（已落地四族
  为发射器实跑产出；lange 为 lange_synth 综合核对基准，文件内显式标注
  非发射产出承诺）/acceptance 门值（**离线发射层门**，见 §6 口径声明）。

---

## 3. spec schema（v1）

契约正本=`src/rfauto/adapters/edb_templates/schema.py` 模块 docstring
（假设清单 1–8 逐条可追溯）。五契约字段 + 元段：

```text
template / schema_version(=1) / units(mm·GHz) / params   ——元段（记账面）
stackup   materials[] + layers[]（自底向上 GND/SUB/TOP 两层信号夹单介质）
traces    单段轴对齐两点中心线（拐角=端点重合）；cap=flat / corner=sharp
vias      契约字段；平面两层族恒空（保留；lange 跨线表达定谳=声明不支持，§2）
resistors 可选扩展：集总电阻声明（几何+r_ohm）——不进 config modeler，
          由 edb_adapter 用 pyedb lumped RLC 边界落地（防逐字套用 config
          时变金属短路）
ports     wave_port@走线端点（point_mm 与 trace path 端点 1e-9 重合）
board     地板矩形（lower_left_mm / upper_right_mm）
sim_setup f0_ghz + sweep{start_ghz,stop_ghz,points,type} + adapt{max_passes,max_delta}
```

三条硬约束（违反即 fail-fast，不静默错配）：

1. **仅 50Ω 系统**：pyedb `CfgEdgePort.set_parameters_to_edb` 把波端口阻
   抗硬编码 50Ω（0.83 实测，`pyedb_distilled.md` §7-A2）——spec 给非 50
   的 `z0_ohm` 直接报错。
2. **单位全域 mm/GHz**：进 pyedb 的换算在 adapter 内置（坐标=米浮点、宽
   度/厚度/频率=`%.10g` 带单位字符串）——spec 层永远写毫米/GHz。
3. **未知键 fail-fast**（adapter 侧）：防 #154 式同名参数跨通道语义漂移。

离线几何审计内建：`edb_templates.schema.validate_spec(spec)` 返回错误清
单（契约字段齐全、层叠形态、走线端点附着图**单连通**、端口落点、board
覆盖足迹、频窗含 f0、电阻端点附着）——发射器内部先自检再产出，"带病
spec"到不了 adapter（#212 离线审计制度化）。

**双路 config 一致性钉**：同一 spec 经发射器
`assemble_config` 与 adapter `spec_to_config_json` 产出的 config 逐键一
致（唯一豁免 setups[0].name 命名差异）——契约测试
`tests/unit/test_edb_adapter.py::TestEmitterSpecContract` 双向钉住。这是
2026-10-08 清偿"并行开发 schema 互不兼容"blocker 后的持久守卫
（W1 冒烟 §4.1 实录）。

---

## 4. 建库：EdbAdapter

```python
from pathlib import Path
from rfauto.adapters.edb_adapter import EdbAdapter

adapter = EdbAdapter(Path("runs/edb_demo"))
result = adapter.build(spec)          # → EdbBuildResult
solved = adapter.solve_batch(result.aedb_path, timeout_s=3600.0)
```

- `EdbBuildResult` 三字段：`aedb_path`（.aedb 工程路径，同名占用时数字后
  缀顺移不覆盖）、`config_json_path`（config JSON 落盘存证，可用
  `edb.configuration.load` 复现）、`warnings`。
- `build()` 内部：`spec_to_config_json` fail-fast 校验 → config JSON 存证
  → 惰性导入 pyedb → 新建 `.aedb` → `configuration.load(config,
  append=True, apply_file=True)` 一次注入 → `resistors` 逐条 lumped RLC
  落地（`_land_resistors`，纯电阻处方逐字对齐 pyedb 0.83 自家
  SourceType.Rlc 分支，无金属电阻体）→ `save_edb()`/`close_edb()`（
  finally 必关，#265 同族）。
- 版本钉：缺省 `version="2025.1"`（对齐基准），env
  `RFAUTO_EDB_AEDT_VERSION` 可覆盖。
- 依赖 extra：`pip install rfauto[edb]`（=pyedb>=0.83）；dotnet 后端还需
  `pyedb[dotnet]`（ansys-pythonnet）。
- adapter 不解析仿真输出（诚实边界，#122）——S 参数回收/判读在 §5/§6。

**环境实况（2026-10-08 真机，如实）**：本机 pyedb 0.83 dotnet 后端
`Edb()` 在 `Database.Create` 处**进程级失败**（stderr
`EVP_DecryptInit ... could not load the shared library`，exit 1，无
Python 异常可捕获；诊断链与最小复现存真机冒烟归档，issue
原料）。gRPC 后端要求 AEDT 2026.1+（本机 2025 R1 无绕行）。**因此 W1 冒
烟的建库段实际改道 pyaedt 非图形会话原生建模**（几何单一来源不变，仍由
`edb_templates` 发射器产出 spec）。该环境件闭环前，`EdbAdapter.build()`
在本机不可用——批处理求解/导出/判读段不受影响（它们只消费 `.aedb`/
`.aedt` 工程文件）。

---

## 5. 批处理求解：hfss_batch

### 5.1 一次性求解入口

```python
from rfauto.adapters.hfss_batch import solve_project_batch

raw = solve_project_batch(
    r"<drive>:\runs\edb_demo\edb_demo.aedb",   # .aedt 文件或 .aedb 目录
    timeout_s=3600.0,
    export_touchstone=True,              # 求解成功后二段导出（§5.2）
)
# 返回结构化 dict：{ok, rc, timed_out, command, ansysedt_exe, project,
#   project_kind, logfile, logfile_tail, artifacts, export, elapsed_s, errors}
# ok 仅在 rc==0 且未超时为真；rc=None=前置失败未拉起进程
```

- 每求解一个独立短命 `ansysedt` 进程（`-ng -BatchSolve`），进程退出即回
  收一切；watchdog 到点整树击杀并如实记 `timed_out=True`。
- exe 发现链：入参 `ansysedt_exe` → env `RFAUTO_AEDT_PATH` →
  `infra.version_probe.resolve_aedt_install` 自动探测（注册表 +
  `ANSYSEM_ROOTxxx`）。
- **命令行参数序纪律（真机实证）**：AEDT 2025 R1 拒收"-Logfile 置于工程
  之后"（`requires a filename ... last parameter`，rc=1）——
  `build_batch_command` 恒把工程路径放末位。
- **`-Logfile` 发射必带**：非图形会话 `GetMessages` 经常为空，console
  log 才是可靠的错误通道（unattended 指南 §3.4）。

### 5.2 Touchstone 导出（二段 -batchextract）

`-BatchSolve` 只求解**不产**网络参数（W1 冒烟实测 artifacts=0）。求解成
功后用官方旗标拉起第二个短命进程跑 IronPython 导出脚本：

```python
from rfauto.adapters.hfss_batch import export_touchstone_after_solve

out = export_touchstone_after_solve(project_path, renorm=False)
# 返回 {ok, rc, out_file, n_ports, ...}；ok=输出文件存在且未超时
```

`renorm=False`=原生参考基（hfss_adapter 主路径口径）；`True`=50Ω 重归一
（remote_service L2 口径）。也可在 `solve_project_batch` 里直接
`export_touchstone=True` 一步串起来（导出失败只追加 `errors` 告警项，
**不推翻求解 ok**——#105 best-effort）。

### 5.3 薄转调与战役路由缝

- `EdbAdapter.solve_batch(aedb_path, timeout_s)` 是
  `solve_project_batch` 的薄转调（结果归一为 `BatchSolveResult`
  dataclass：`success/message/log_path/artifacts/rc/timed_out/elapsed_s`）。
- campaign DAG 的 stage 节点声明 `stage_extra["hfss_batch"]`（字符串工程
  路径或全参 dict）即路由到同一条一次性批处理路径（缺省零行为变化）——
  路由实现 `rfauto/service/campaign_executor.py::stage_batch_decl` /
  `_route_batch_stage`。
- 孤儿 ansysedt 治理/杀前核对命令行/两档严格度：unattended 指南 §5.4，
  单源 `src/rfauto/infra/desktop_guard.py`。

---

## 6. Touchstone 判读（离线发射层门）

**口径声明**：本节门值分**两层**，读数前先分层——①**离线发射层门**
（offline gate，§6.1/§6.2 门表）：发射自检与数据集冒烟判读层，记录于
`docs/templates/edb_*/meta.yaml` 的 acceptance 键；②**health gate**
（真机批处理产物质量仲裁，「EDB 路径质量门适配」已落地）：
`src/rfauto/service/edb_health_gate.py::check_edb_batch_health`（schema
`edb-health-gate-v1`），其语义演化史/判读终表/已知语义边界见
§6.4–§6.6。两层门值不同（如 S11 离线门 -15dB vs 健康门通用缺省 -10dB）
是分层设计而非漂移（§6.5 单源核对结论）。

判读输入：批后 Touchstone（skrf `Network` 读 `.s4p`/`.s3p`）。**端口序
=AEDT 端口号序 P1..Pn**——sNp 头 `! Port[k] = Portk` 注释即存证（W1 实
测创建序=spec 端口序，并经物理交叉验证：branchline S41≈S23≈-33dB 对角
隔离对）。

### 6.1 edb_branchline 门表（@f0，W1 实测判读口径）

| 判据 | 门 | W1 读数 | 判定 |
|---|---|---|---|
| \|S11\| 谷深 | ≤ -15 dB | **-34.22 dB** | PASS |
| \|S21\| 直通窗 | ∈ [-3.5, -2.5] dB | **-3.584 dB** | FAIL（超窗 0.084dB） |
| \|S41\| 隔离 | ≤ -20 dB | **-33.23 dB** | PASS |
| passivity σmax | ≤ 1.05 | **0.9925** | PASS |
| f0 偏移（S11 谷） | \|Δ\| ≤ 5% | **0.0%**（f_res 恰 2.400GHz） | PASS |

S21 超窗如实记 FAIL（#122 不凑绿）；候选归因=单频自适应 ΔS=0.02 收敛档
较粗，留 HFSS 3D 路径对拍仲裁（后续对拍判读）。S11 -34dB + 隔离 -33dB 表明
器件本身是合格的定向耦合器。

### 6.2 edb_power_divider 门表（@f0）与门语义仲裁注记

| 判据 | 门 | W1 读数（无阻版） | 判定 |
|---|---|---|---|
| \|S11\| 谷深 | ≤ -15 dB | **-17.89 dB** | PASS |
| 幅度平衡差 | ≤ 0.5 dB | **0.068 dB** | PASS |
| \|S21\|/\|S31\| 分配损耗 | ∈ [-3.8, -2.5]（建议物理健康窗） | **-3.192 / -3.261 dB** | 见仲裁注记 |

**门语义仲裁（已裁定，W4 落定）**：W1 任务书字面门"各 ≤-3.8dB"会让
**任何**健康功分器 FAIL（理想等分分配就是 -3.01dB + 损耗；W1 健康实测
-3.19/-3.26）。冒烟判读按字面记 FAIL 不凑绿、双读数存档
`power_divider_judgment.json` 并发起仲裁（W1 判读报告 §3.2）；W4 门语义裁定物理窗 **[-3.8, -2.5] dB（双边闭）**
并以健康门第七判据 `s_split_window` 落地（单源=
`edb_health_gate.S_WINDOW_DB_BY_TEMPLATE`，演化史见 §6.4-2）。无阻版
特征性劣化（S22≈-6.7dB、S32 隔离仅 -5.62dB）只记读数不判门——隔离电
阻判读须待有阻版真跑（RLC 脚本落地通道 W8 十一轮探针定谳失败待上游，
W8 gap 扫描归档）。

### 6.3 判读纪律

- f0 是否落在 sweep 栅格点上先查（W1 401 点栅格 f0=2.4GHz 恰在格点，
  `f0_on_grid` 存证）；不在格点时取最近格点读数并记偏差。
- passivity σmax 与互易性自洽（branchline S23=S32 到 1e-14）是判读有效
  性的廉价旁证。
- 判读逻辑属确定性内核（数值只在内核）——离线门值进
  meta.yaml，健康门判读函数已落地 `src/rfauto/service/edb_health_gate.py`
  （64 测，`tests/unit/test_edb_health_gate.py`），LLM/脚本不现场发明门。

### 6.4 健康门判读语义演化史（W3→W11，为什么改）

真机批处理产物的质量仲裁门 `check_edb_batch_health`（schema
`edb-health-gate-v1`）自 W3 起经五轮语义演化。每轮改动都由真机冒烟/仲
裁的具体读数驱动，且全部遵循两条既定纪律：判据 FAIL 如实不凑绿（#122）、
门常量按模板作用域分派（#274）。本节记"为什么改+证据出处"；当前终态见
§6.5（单源=源码，本节文字与源码冲突时以源码为准）。冒烟批 2 =
coupled_line/ratrace 两新族首跑（判读报告自署
W6.2 批次）；W10 定谳重跑与 W10 两新族批量均有真机判读归档。

**（1）v1 六因子（W3）**。动机：仓内既有体检 G11 消费 `runs/<run_id>/`
目录形态，EDB 批处理产物=结构化回执 dict + Touchstone，既无 run 目录也
无 meta.json——直接复用 G11 会"无可识别体检产物"。首版六因子：
`solve_status`（rc/超时态；watchdog 整树击杀后残留产物不可信，#157 家
族）/ `touchstone`（发现链+可读性；`-BatchSolve` 只求解不产网络参数的
断链指纹，W1 真机实证）/ `port_count`（#248/#309 端口数契约）/
`passivity`（σmax 真奇异值判据，非 entry-wise max 近似）/ `s11_dip`
（#274 模板分派）/ `reciprocity`（#314 掩码纪律：按全矩阵判但
`measured_mask=None` 如实声明）。三态 verdict PASS/FAIL/UNKNOWN
（#122：UNKNOWN 不冒充 FAIL 也不冒充 PASS）。

**（2）W4：第七因子 `s_split_window`（功分器门语义仲裁落定）**。动机：
W1 冒烟任务书字面门"各 ≤-3.8dB"是单边下界语义错位——理想等分分配损耗
就是 -3.01dB，字面门会让任何健康功分器 FAIL；冒烟判读按字面记 FAIL 不凑
绿、双读数存证并发起仲裁（W1 判读报告 §3.2，健
康实测 -3.19/-3.26）。W4 裁定物理窗 **[-3.8, -2.5] dB 双边闭**（下界=
3dB 分配 + 0.8dB 实现容差；上界排除异常增益/提取伪象），双腿各自落窗
内才算过。作用域两条家法：**无通用缺省窗**（等分分配是功分器族专属物
理语义，与有通用缺省 -10dB 的 S11 门不同）——未登记且无显式窗的族
criteria 键缺席=不判，不硬套他族门也不冒充 UNKNOWN（#274）。

**（3）W5→W6→W11：闭边界 eps 三连（数值门边界家法）**。动机：健康
门闭区间语义（实测 ≤ 门为过 / 窗双边闭 / σmax ≤ 1+容差）在**恰等边界
读数**上会被浮点量化噪声系统性误 FAIL——噪声是门实现侧必须吸收的，不
是数据侧缺陷。三步：
- **W5 回取复核**抓第七判据自身缺陷：恰 10^(-2.5/20) 的腿经 double
  域 dB 往返实测读 -2.4999999999999996（越上界 4.4e-16dB）→
  `_SPLIT_WINDOW_DB_EPS=1e-9` + 恰等边界回归钉（家法源头，与
  `core/trl_solt._LINE_PASSIVE_MARGIN` 同源）；
- **W6 健康门边界盘点**全暴露面盘点：`s11_dip` 门值域扫描
  [-40,-1]×0.1dB 实测 **30/391** 个门值落违约侧（如 -7.2dB 读
  -7.199999999999999）；`passivity` 容差带缘 **114/201** 组合读
  1.0100000000000002（+2.2e-16，double 表示 + SVD 舍入；线性域无 dB
  换算、噪声源不同暴露面同型）→ 两门各加 1e-9 eps + 恰等回归钉；
  `reciprocity` 门义即边界=违约（FAIL 侧）、无暴露面；
- **W11 三 eps 收口**：三常量统一表（常量名/门/噪声源/量级论证
  9/8/14 个量级）落模块 docstring「数值门边界纪律」节；第四处逐判据核查全收口（reciprocity `worst >= 容差` 线性域直
  读、无门值↔量测表示变换，非 #376 类）。

**（4）W8：f0 多谷语义（`s11_dip` 锚最深谷 + `f0_offset` UNKNOWN）**。
动机：冒烟批 2 ratrace 实证双谷夹持（带内 1.9716/2.6664GHz 双谷、f0=
2.4GHz 居中本身 -18.42dB 健康）——argmin 谷/插值 f0 的"谷位标记"在多
谷形态语义失真（#298 家法：峰位/频偏判据只在单谷同口径可用）。落地
（确定性数值规则）：f0 对称窗内检出多谷（相邻极小间距 > 窗宽 5% 计独
立谷；≤5% 链式归并保留更深者，单谷肩部纹波不误触发）→ `s11_dip` 本因
子改锚**最深谷**（主谷@f0 典型形态与 at-f0 读数同值=既有行为保持）+
追加条件性因子 `f0_offset`：恒 UNKNOWN + detail 标 `multi_dip_near_f0`
（#122 不冒充）。单谷/无谷/既有 UNKNOWN 路径零变化（回归钉
`test_single_dip_behavior_unchanged` 等）。侧证：W8 功分器 gap 扫描
f_res 单调下移多谷加剧（W8 gap 扫描）——多谷形态在真
实参数族上并不罕见。

**（5）W8→W9→W10→W11：紧缝族生产判读档 0.02→0.005→回退 0.02（判
读校准锚确立）**。全链最重的一段演化，主角是 coupled_line 紧缝族
（s=0.082mm / 铜 0.035mm，s/h=0.161，s/t=2.34）：
- **W6/W7 冒烟**：S31@f0=-7.16dB 表观过耦 +2.84dB 超窗 [-11,-9]，如实
  FAIL 不调参（冒烟批 2 判读报告 §2.1）；
- **W8 三变体仲裁**（HFSS 3D 同参数对拍，W8 仲裁档）：表观过耦二分=真厚度效应 ≈+0.8~0.9dB@s/t=2.34
  （HFSS 匹配档阶梯随收紧趋稳 +0.80）+ **ΔS=0.02 收敛档读数伪象
  ≈+2.0dB**（HFSS 侧阶梯分解；两引擎 0.02 档一致读 -7.2~-7.6——0.02
  档的窗口判据在测"网格收敛度"而非"器件物理"）；零厚全波饱和 -9.772
  vs KJ 预测 -10.00（残差 0.23dB，综合无需修正）。据此建议生产档加严
  0.005（附带发现：EDB 重载改档不传播=回放缓存解，#333 族旋钮效力断言
  缺失）；
- **W9**：`DEFAULT_ADAPT_MAX_DELTA` 0.02→0.005 落地 + 收敛档写入核验
  工具 `verify_adapt_tightening` + s/t 厚度偏置声明（锚
  +0.8dB@s/t=2.34、s/t≥4 伪象主导区划线仅 warning）；同日 W9 审查
  （W10 落定）P0 抓出"建模期写入即生效"声明被真机反证（0.005 写入不
  传播，S31 与 0.02 档逐位同值 2.4e-13）；
- **W10 定谳**（真机单点全链判读报告）：① MaxDelta=0.005 在 EDB 3D Layout schema
  （SimSetupID=19）**无键、写入不可达**（四互证）；唯一可达收紧通道=
  扁平键 `MinConvergedPasses`（W9 mc2=2 / W10=4 两真机点被求解器实消
  费）；② **量级修正**：EDB 侧档位伪象实测仅 **~0.62dB**（W8 的 ~2dB
  系 HFSS 侧阶梯分解，不按面值转移 EDB），剩余 **~1.0dB=EDB-Layout 特
  有建模保真差**（引擎间隙随收紧变宽 0.406→0.623dB="不同收敛极限"而
  非"同一极限的滞后"）；③ 两新族批量 6 点旁证（W10 批量判读归档）：0.005 真档不可达下**回收天花板 ≈0.5dB**，S31
  三点 -7.49~-7.69 仍超窗，缺口 2.1~2.3dB=剩余伪象+厚度偏置构成；
- **W11 裁决**（后续真机复验定谳）：**回退 0.02**——
  写入口不可达定谳 + EDB 侧伪象 0.62dB 量级不支撑 4× 加严 + 保留
  0.005"请求档"=每建必告警噪声 + 存证值误导归因（#122 不虚报）。
  **复进条件**写死：pyedb/AEDT 暴露 MaxDelta 写入口后按 W8 依据显式重
  立，禁靠常量静默生效。**判读面校准锚**：复进前紧缝族 EDB S31 读数按
  "保真差 ~+1.0dB（窗心偏移）+ 厚度偏置 +0.8dB@s/t=2.34"对待
  （§6.6-4）。

**（6）两次判读口径错位修正（仲裁附带产出）**。① branchline S21 超窗
0.084dB（W1）：W5 HFSS 3D 仲裁 **AGREE_EDB**——两引擎同向超窗=模型级
特征（矩形环未 miter），非 EDB 伪象；收敛阶梯 d02→d01 S21 移动
+0.108dB ≥0.05 阈值 → 单点超窗含收敛档噪声成分
（W5 仲裁档）。② coupled_line W6 门表
S21∈[-11,-9] 属直通口物理口径错位——直通口理想读数
-10·log10(1-C²)≈-0.46dB（10dB 耦合器），同现象在 S31 重复计门；判读
面修正为功率残差口径（W8 仲裁档 §1.2
注）。

### 6.5 当前判读终表（2026-10-09，单源=src/rfauto/service/edb_health_gate.py）

七因子 + 条件性 `f0_offset`（全部确定性数值规则；LLM/agent 永
不产生物理数字，本门只消费求解器实测与批处理结构化回执）。门分派优先
级：调用方显式覆盖 > 模板登记表（值可 None=该族显式不设门）> 通用缺省
（仅 S11 有缺省；分配窗无缺省）。

| 因子 | PASS 条件 | FAIL 条件 | UNKNOWN 条件 | 闭边界余量 |
|---|---|---|---|---|
| solve_status | rc==0 且未超时 | timed_out（#157 残留产物不可信）/ rc=None（前置失败未拉起）/ rc≠0 / 回执契约矛盾 | 回执缺失/非 dict、rc 形态非法 | — |
| touchstone | 发现链命中且 skrf 可读（显式路径 > export.out_file > artifacts 扫 .sNp） | 候选缺失/文件不存在（-BatchSolve 断链指纹）/ 解析失败/形状非法（#316 多报方向） | skrf 环境缺失 | — |
| port_count | 实测=spec 声明（wave_port port_nr / 通用 number 同池取最大编号） | 不符（#248/#309 族） | spec 未声明 / S 不可读 | — |
| passivity | σmax ≤ 1.01（1% 容差，与 `core.solve_health.PASSIVITY_TOLERANCE` 同源） | σmax 超容差 / 含非有限值 | S 不可读 | `_PASSIVITY_LINEAR_EPS`=1e-9 |
| s11_dip | S11@f0（多谷锚最深谷）≤ 门（dB 谷深，实测 ≤ 门为过） | 未达门 | f0 未声明/出跨度/无有效样本；gate=None 族 | `_S11_DIP_DB_EPS`=1e-9 |
| f0_offset（条件性） | ——（仅在 f0 邻域检出多谷时出现） | ——（不硬 FAIL，#122） | 恒 UNKNOWN + detail 标 `multi_dip_near_f0` | — |
| s_split_window | 双腿 \|S21\|/\|S31\|@f0 各自 ∈ [下界,上界]（双边闭，逐腿判） | 任一腿出窗（detail 点名腿与越界方向） | <3 端口 / f0 缺失或出跨度 | `_SPLIT_WINDOW_DB_EPS`=1e-9 |
| reciprocity | max\|Sij−Sji\| < 0.01（`RECIPROCITY_TOLERANCE`；全矩阵口径 `measured_mask=None` 如实声明，#314；单端口=平凡真） | ≥ 0.01 / 含非有限值 | S 不可读 | 无 eps（门义即边界=违约，W11 第四处核查非 #376 类） |

verdict 聚合（#122）：任一 FAIL → FAIL；否则任一 UNKNOWN → UNKNOWN；
全 PASS → PASS。`ok` 仅作报告字段（=verdict==PASS），非门禁判据。

**门分派与登记表现状（单源核对结论，2026-10-09 grep 实测）**：

- `S11_DIP_DB_BY_TEMPLATE = {}`——**空表**：现无任何族登记族专属 S11
  谷深门；全族走通用缺省 `DEFAULT_S11_DIP_DB = -10.0`（回波损耗 ≥10dB
  通用惯例）或调用方显式覆盖；登记表值可为 None=该族显式不设门（如实
  UNKNOWN 不硬套）。
- `S_WINDOW_DB_BY_TEMPLATE = {"edb_power_divider": (-3.8, -2.5),
  "wilkinson": (-3.8, -2.5)}`——仅两键（后者=HFSS/openEMS 插件族同名
  物理窗，等分分配物理为族级语义、与适配器无关）；`edb_branchline`/
  `edb_coupled_line`/`edb_ratrace`/`edb_lange` 不在表 → 健康门
  criteria 不含该判据（缺席=不判）。
- 与 §6.1/§6.2 离线门的关系：离线门（meta.yaml acceptance，如 S11
  ≤-15dB）与健康门（-10dB 通用缺省）是**两层门**，值不同是分层设计
  （离线门=冒烟判读口径，健康门=真机产物通用质量门），非漂移；改动任
  一层门值一律先读对应单源（meta.yaml / 本模块），禁止臆造物理数字。
- 附：coupled_line 生产判读档单源=`adapters/edb_templates/
  coupled_line.py::DEFAULT_ADAPT_MAX_DELTA = 0.02`（W11 回退终态，
  全史见 §6.4-5）。

### 6.6 已知语义边界（判读读数的已知伪象与敏感面）

以下五类是实测确认的判读语义边界。判读 FAIL/异常读数先对照本节再下物
理结论——但不改判据本身（读数如实落档，#122）。

**（1）带缘钳位——非谷型响应的 f0 标记伪象**。带内 S11 无局部谷（单
调走低）的响应，"带内谷位"标记被钳到扫频带缘报出常数级大偏移：
coupled_line 三点批量 +30%×3（f_res=3.12GHz=上带缘，W10 批量定型）。
f0 处实测匹配本身健康（-16.3dB）——该标记 FAIL 只说明"非谷型响应"，
不说明匹配差。出处：冒烟批 2 判读报告 §2.1（首证）、W10 批量判读归档。

**（2）双谷夹持——多模闭合环族的 f0 标记伪象**。ratrace 带内双谷
（1.9716/2.6664GHz）夹持设计点，f0=2.4 居中本身 -18.42dB 健康，单标记
谷位报 -17.85%（冒烟批 2），三点 -17%×3 复现定型（W10 批量）。健康门
W8 起对该形态如实 UNKNOWN（`multi_dip_near_f0`）不再硬判；冒烟批 2 离
线判读表的 f0 偏移门按单谷语义记 FAIL——两层门口径差如实保留。出处：
冒烟批 2 判读报告 §2.2/§4-2。

**（3）多模族 f0 标记退化（语义总注）**。（1）（2）的共同根因：
`f0_offset` 的语义域=单谷响应，非谷型/多谷型上该标记退化。修语义（带
心口径/双谷几何均值/按族分派）为 W7 起登记的 followUp——落地前健康门
侧多谷如实 UNKNOWN；非谷型钳位形态判读时人工豁免并引本节，不冒充器件
缺陷也不回改证据。

**（4）紧缝族收敛档敏感（coupled_line，s/h≲0.2）**。名义 10dB 设计点
（s=0.082/t=0.035mm，s/h=0.161，s/t=2.34）的 S31 窗口判读受三重已知量
支配：ΔS=0.02 档收敛噪声（EDB 侧实测回收量 ~0.62dB；HFSS 侧阶梯
~2dB）+ EDB-Layout 建模保真差 **~+1.0dB**（判读校准锚，W10 定谳）+
有限铜厚厚度偏置 **+0.8dB@s/t=2.34**（发射器 `thickness_bias_note`
渲染期声明，s/t≥4 伪象主导区划线）。EDB 0.005 档写入不可达（schema
无键），唯一可达收紧通道=扁平键 `MinConvergedPasses`。**紧缝族 S31 窗
口判据 FAIL 时，先核对求解档位与上述三重量的构成，再下"器件过耦"结
论**——0.02 档的窗口判据测的是"网格收敛度+保真差+厚度"而非纯器件物理
（W8 仲裁判词）。出处：W8 仲裁档 §3、
W10 判读报告 §3、W10 批量判读归档。

**（5）通用收敛档噪声底（各族适用）**。W5 branchline 仲裁口径：ΔS 档
位阶梯上关键指标移动 ≥0.05dB 即视为"0.02 档读数含收敛档噪声"（d02→
d01 S21 移动 +0.108dB 实证）；单点超窗量级与该噪声底相当时，归因走对
拍仲裁（AGREE_EDB 判例），不调参凑绿也不误判器件缺陷（#335 收敛纪律：
仲裁前先验收敛——ΔS 目标达标≠关键标量已收敛）。

---

## 7. 数据集道（已落地，W3）

- **数据工厂 EDB 道**（dataset collector 消费 batch+Touchstone 形态）：
  已落地（W3）——`service/dataset_edb_lane.py`（#251 谱系第⑥类产物通
  道）：以 `<stem>_judgment.json` 为目录识别主标志，读 `<stem>_spec.json`
  （参数唯一来源）+ `state.json` + Touchstone 产物；行 schema 与
  `dataset_service` 逐键对齐（同布局 points.parquet/points.h5+manifest），
  `query_dataset`/`list_datasets` 直接可查；#320–#322 导入纪律在行
  schema 与 E1 指纹面同构适用（study_name=批次相对 runs 根 posix 路径，
  防跨战役同名批次折叠）。
- **CLI/MCP 出口**：已落地（W3）——CLI 三叶 `rfauto edb build/solve/
  status`（`cli/domains/edb.py`，均带 `--json`，与 MCP 同源同名 service
  函数）；MCP 三工具 `edb_emit_spec`/`edb_build_solve`/`edb_status`
  （`mcp_tools/edb.py`）+ resources 两件 `rfauto://edb/status`、
  `rfauto://edb/datasets`（不计入工具数）。
- **服务器/远程**：多机协同通道（`rfauto remote`，sim_host）当前锚
  HFSS gRPC 链路；EDB 批处理进程的远程化（含服务器侧工作盘临时目录/任务
  毕清理规则）尚未排期（真实未来项），远程服务器 AEDT 版本必须=本机
  （版本对齐纪律）。

---

## 8. 已知缺口与待验证清单（开工前必读）

1. **pyedb dotnet 后端本机进程级失败**（§4；issue 原料已备）——闭环前
   `EdbAdapter.build()` 本机不可用，建库段以 W1 冒烟的 pyaedt 改道形态
   为唯一实测通路。
2. **层序三口径**：spec 层叠注释"自底向上" × adapter"顺序透传" × pyedb
   `apply_stackup` 逐层 `add_layer_bottom`（首项落物理顶层）——真机首跑
   必以 `edb.stackup.layers` 落位复核（`pyedb_distilled.md` §3.1/§6-2）。
3. **cap_style 已钉**：rfauto config 面统一 `flat`/`sharp`（pyedb 缺省
   round 圆头会在端口落点短 r/2，`pyedb_distilled.md` §3.2）。
4. **power_divider 缺省 gap 与 wave_port 扩展因子 5 冲突**（rc=103
   真机实证）：**已闭环**——缺省 `DEFAULT_GAP_MM=6.0` 与插件口径 2.0
   有意分叉，渲染期守卫 fail-fast（`gap_mm ≤ 因子×shunt_w` 抛
   ValueError，报错自带建议放宽值；不足值的最低可行界=因子×shunt_w）。
   coupled_line/ratrace 无双臂 gap 参数，同款冲突未实证、无同款守卫。
5. **lange 发射器声明不支持**（W3 落地口径）：edb_coupled_line/
   edb_ratrace 已落地（W3）；edb_lange 为预留键——`emit_lange_spec` 恒
   NotImplementedError（`LANGE_EDB_SUPPORTED=False`），air-bridge spec
   表达待解即其主因之一，升格前置条件见 `docs/templates/edb_lange/
   meta.yaml`；三族 meta.yaml 名义值为注册模板参考口径（文件内已显式
   标注非产出承诺）。
6. **`-designs <design:setup>` 限定语法**：官方文档口径，本仓未实测该限
   定的具体分隔语法——待验证（unattended 指南 §1.2 同注）。

---

## 9. 证据与来源对照

| 文中主张 | 来源 |
|---|---|
| spec 契约/假设清单 1–8/KNOWN_TEMPLATES/validate_spec | `src/rfauto/adapters/edb_templates/schema.py` docstring |
| 四族发射器拓扑/端口语义/综合链 | `src/rfauto/adapters/edb_templates/branchline.py`、`power_divider.py`、`coupled_line.py`、`ratrace.py`（docstring）；单源一致性钉 `tests/unit/test_edb_templates.py` 与 `tests/unit/test_edb_templates_ext.py`；lange 拒绝语义与升格前置 `lange.py` docstring |
| EdbAdapter.build/solve_batch/EdbBuildResult/BatchSolveResult、resistors RLC 处方、版本钉 | `src/rfauto/adapters/edb_adapter.py`（含 docstring 逐条出处） |
| solve_project_batch/build_batch_command/export_touchstone_after_solve、参数序纪律、find_ansysedt_exe 链 | `src/rfauto/adapters/hfss_batch.py`；真机实证 W1 判读报告 §4.3 |
| W1 判读门表/读数/门语义仲裁/端口序存证 | W1 判读报告 §2–§3 + 两族 `*_judgment.json` |
| 健康门七因子/三 eps/门登记表（§6.5 判读终表单源） | `src/rfauto/service/edb_health_gate.py`（docstring「数值门边界纪律」=数值门边界家法）+ `tests/unit/test_edb_health_gate.py`（64 测，含恰等边界钉/多谷钉） |
| 判读语义演化证据链（§6.4：W1 冒烟/冒烟批 2/W5 仲裁/W8 仲裁/W10 定谳与批量） | W1 判读报告、冒烟批 2 判读报告、W5 仲裁档、W8 仲裁档、W10 判读报告与 W10 批量判读归档 |
| coupled_line 生产判读档 0.02 回退单源（W11 裁决） | `src/rfauto/adapters/edb_templates/coupled_line.py::DEFAULT_ADAPT_MAX_DELTA`（模块 docstring「生产判读档史」节带 W8→W9→W10 全史与复进条件） |
| campaign stage hfss_batch 路由缝 | `src/rfauto/service/campaign_executor.py::stage_batch_decl`/`_route_batch_stage` |
| pyedb API 名（Edb/configuration.load/run/export、CfgEdgePort 50Ω 硬编码、层序、sweep 词表） | `docs/pyedb_distilled.md`（0.83 实装源码逐条核验） |
| 无人值守纪律（-Logfile、看门、孤儿、进程隔离哲学） | `docs/unattended_hfss_automation.md` §1/§3/§5 |
| EDB meta.yaml 与注册模板消费者边界 | `tests/unit/test_template_meta_consistency.py`、`tests/unit/test_template_geometry_audit.py`（EXPECTED_TEMPLATES 冻结 72 项）、`scripts/build_docs_pages.py::build_templates_page`（信息文档排除，2026-10-08 同笔调整） |
| 后三族（coupled_line/ratrace/lange）综合单源名义参考（注册模板侧） | `docs/templates/cline_coupler/`、`ratrace/`、`lange/` 的 meta.yaml；`oe_templates/render_c4.py`（cline_coupler_design/lange_design）、`core/synthesis.py::synthesize_ratrace_model`；edb 侧一致性钉 `tests/unit/test_edb_templates_ext.py` |

> 维护约定：本文只写"已验证事实 + 操作纪律"。新增发射器族（含 lange
> 升格）、门值语义演化、出口面（CLI/MCP/数据集道）扩展时逐节回填；
> 未实测新口径先标"待验证"。文档与代码改动同 commit（#97）。
