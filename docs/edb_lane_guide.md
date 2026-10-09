# EDB 快车道用户指南：五族发射器 → 批处理求解 → Touchstone 判读

> 状态：正式文档（2026-10 首版）。
> 定位：EDB 快车道的工程师操作面——平面族器件如何经**声明式 spec 发射 →
> PyEDB/hfss_batch 建库 → `ansysedt` 批处理求解 → Touchstone 判读**批量
> 生成数据集。会话污染/进程治理/看门狗等通用无人值守纪律的权威口径在
> `docs/unattended_hfss_automation.md`（本文只引用不重复）；PyEDB API
> 技术事实以 pyedb 0.83 实装源码逐字核验口径为准，本文 API 名逐字以源
> 码为准。
> 证据基线：pyedb 0.83.0 × pyaedt 1.4.0 × skrf 2.1.0 × AEDT 2025 R1
> （v251），W1 真机冒烟（判读正本 `REPORT.md`，本机在档，runs/ 产物不
> 入 git）。`#NNN` 为开发过程沉淀的坑号。未经本机实测的口径标"待验证"。

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
在 HFSS 3D 原生建的，EDB 不替代该主路径（无人值守指南 §1.1/§1.2 口径
不变）。

**对齐基准纪律**：HFSS 3D 通路是仲裁基准。EDB 快车道产物进数据集走与
既有通道相同的质量门交叉验证；冒烟已暴露的门语义问题（§6.1/§6.2）按
#122 如实记 FAIL 不凑绿，留对拍仲裁。

---

## 2. 五族发射器（模板元面）

发射器全部是**纯函数**（零 IO 零 pyedb 依赖，pyedb 属 adapter 消费层），
`params dict → (spec dict, config_json dict)`。全部尺寸由
`core.synthesis` 闭式综合产出（`inverse_width` HJ 反解 + `forward_media`
εeff + λg/4 闭式）——**禁止手抄毫米数**（综合单源纪律，#252）。

| 族 | 状态 | 端口 | 拓扑 | 源码入口 |
|---|---|---|---|---|
| edb_branchline | 已落地 | 4 | 角馈 branchline 矩形环 | `rfauto.adapters.edb_templates.branchline.emit_branchline_spec` |
| edb_power_divider | 已落地 | 3 | T 结 Wilkinson（RISO=2·Z0 隔离电阻） | `rfauto.adapters.edb_templates.power_divider.emit_power_divider_spec` |
| edb_coupled_line | 已落地 | 4 | 平行耦合线后向波定向耦合器 | `rfauto.adapters.edb_templates.coupled_line.emit_coupled_line_spec` |
| edb_ratrace | 已落地 | 4 | 180° 混合环（1.5λg，√2·Z0） | `rfauto.adapters.edb_templates.ratrace.emit_ratrace_spec` |
| edb_lange | 声明不支持 | 4 | 展开型 Lange 电桥（含 air-bridge） | 结构化拒绝信封（`emit_lange_spec`，见下） |

- 族白名单单源=`edb_templates.schema.KNOWN_TEMPLATES`（现值
  `("edb_branchline", "edb_power_divider")`）。注意这是 validate_spec 的
  豁免口径（白名单外族的契约校验由各族发射器侧过滤承担），与
  `edb_lane_service._emitters` 的**发射分派表**（四支持族+lange 拒绝信
  封）是两个面。
- 已落地发射器的最小用法：

```python
from rfauto.adapters.edb_templates import emit_branchline_spec

spec, config_json = emit_branchline_spec({"f0_ghz": 2.4})
# spec        ——五契约字段声明式版图规格（§3）
# config_json ——pyedb edb.configuration.load() 兼容 dict
```

- **模板元面**：edb_* 族**不是** `openems_templates.TEMPLATE_NOMINAL` 注
  册模板——`tests/unit/test_template_meta_consistency.py` 与
  `tests/unit/test_template_geometry_audit.py` 的 EXPECTED_TEMPLATES 冻
  结注册集不扫描它们。acceptance 门值走两处登记：离线发射层门（§6 口径
  声明）与框架级健康门登记表（`src/rfauto/service/edb_health_gate.py`
  的 `S11_DIP_DB_BY_TEMPLATE`/`S_WINDOW_DB_BY_TEMPLATE`，端到端形态见
  `docs/edb_lane_walkthrough.md` §5.3）。

---

## 3. spec schema（v1）

契约正本=`src/rfauto/adapters/edb_templates/schema.py` 模块 docstring
（假设清单 1–8 逐条可追溯）。五契约字段 + 元段：

```text
template / schema_version(=1) / units(mm·GHz) / params   ——元段（记账面）
stackup   materials[] + layers[]（自底向上 GND/SUB/TOP 两层信号夹单介质）
traces    单段轴对齐两点中心线（拐角=端点重合）；cap=flat / corner=sharp
vias      契约字段；平面两层族恒空（保留；lange 的 air-bridge 表达待解）
resistors 可选扩展：集总电阻声明（几何+r_ohm）——不进 config modeler，
          由 edb_adapter 用 pyedb lumped RLC 边界落地（防逐字套用 config
          时变金属短路）
ports     wave_port@走线端点（point_mm 与 trace path 端点 1e-9 重合）
board     地板矩形（lower_left_mm / upper_right_mm）
sim_setup f0_ghz + sweep{start_ghz,stop_ghz,points,type} + adapt{max_passes,max_delta}
```

三条硬约束（违反即 fail-fast，不静默错配）：

1. **仅 50Ω 系统**：pyedb `CfgEdgePort.set_parameters_to_edb` 把波端口阻
   抗硬编码 50Ω（0.83 实测）——spec 给非 50 的 `z0_ohm` 直接报错。
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
`tests/unit/test_edb_adapter.py::TestEmitterSpecContract` 双向钉住。

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

**环境实况（2026-10 真机，如实）**：实测机器上 pyedb 0.83 dotnet 后端
`Edb()` 在 `Database.Create` 处**进程级失败**（stderr
`EVP_DecryptInit ... could not load the shared library`，exit 1，无
Python 异常可捕获；诊断链与最小复现本机在档，issue 原料已备）。gRPC
后端要求 AEDT 2026.1+（2025 R1 无绕行）。**因此 W1 冒烟的建库段实际改
道 pyaedt 非图形会话原生建模**（几何单一来源不变，仍由 `edb_templates`
发射器产出 spec；改道形态与逐条排除记录见
`docs/edb_lane_walkthrough.md` §3.2/§8.1）。该环境件闭环前，
`EdbAdapter.build()` 在该类机器不可用——批处理求解/导出/判读段不受影
响（它们只消费 `.aedb`/`.aedt` 工程文件）。

---

## 5. 批处理求解：hfss_batch

### 5.1 一次性求解入口

```python
from rfauto.adapters.hfss_batch import solve_project_batch

raw = solve_project_batch(
    "runs/edb_demo/edb_demo.aedb",      # .aedt 文件或 .aedb 目录
    timeout_s=3600.0,
    export_touchstone=True,             # 求解成功后二段导出（§5.2）
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
  log 才是可靠的错误通道（无人值守指南 §3.4）。

### 5.2 Touchstone 导出（二段 -batchextract）

`-BatchSolve` 只求解**不产**网络参数（W1 冒烟实测 artifacts=0）。求解成
功后用官方旗标拉起第二个短命进程跑 IronPython 导出脚本：

```python
from rfauto.adapters.hfss_batch import export_touchstone_after_solve

out = export_touchstone_after_solve(project_path, renorm=False)
# 返回 {ok, rc, out_file, n_ports, ...}；ok=输出文件存在且未超时
```

`renorm=False`=原生参考基（hfss_adapter 主路径口径）；`True`=50Ω 重归一
（远程 L2 通道口径）。也可在 `solve_project_batch` 里直接
`export_touchstone=True` 一步串起来（导出失败只追加 `errors` 告警项，
**不推翻求解 ok**——#105 best-effort）。

### 5.3 薄转调

- `EdbAdapter.solve_batch(aedb_path, timeout_s)` 是
  `solve_project_batch` 的薄转调（结果归一为 `BatchSolveResult`
  dataclass：`success/message/log_path/artifacts/rc/timed_out/elapsed_s`）。
- 孤儿 ansysedt 治理/杀前核对命令行/两档严格度：无人值守指南 §5.4，
  单源 `src/rfauto/infra/desktop_guard.py`。

---

## 6. Touchstone 判读（离线发射层门）

**口径声明**：本节门值全部是**离线发射层门**——发射自检与数据集冒烟判
读层的 offline gate；真机求解产物的质量仲裁另有框架级 **health gate**
（`src/rfauto/service/edb_health_gate.py`，七因子 `edb-health-gate-v1`，
端到端形态见 `docs/edb_lane_walkthrough.md` §5.3）。

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

S21 超窗如实记 FAIL（#122 不凑绿）。门语义仲裁（真机 REPORT §3.2）后
直通窗已裁定放宽为 [-3.8, -2.5]（理想等分 -3.01dB + 实现容差），上表
按 W1 当时代码口径原样保留（门改动必须带真机/仲裁出处的活例子，见
walkthrough §5.2）。S11 -34dB + 隔离 -33dB 表明器件本身是合格的定向
耦合器。

### 6.2 edb_power_divider 门表（@f0）与门语义仲裁注记

| 判据 | 门 | W1 读数（无阻版） | 判定 |
|---|---|---|---|
| \|S11\| 谷深 | ≤ -15 dB | **-17.89 dB** | PASS |
| 幅度平衡差 | ≤ 0.5 dB | **0.068 dB** | PASS |
| \|S21\|/\|S31\| 分配损耗 | ∈ [-3.8, -2.5]（建议物理健康窗） | **-3.192 / -3.261 dB** | 见仲裁注记 |

**门语义仲裁请求（未裁定）**：W1 任务书字面门"各 ≤-3.8dB"会让**任何**
健康功分器 FAIL（理想分配就是 -3.01dB + 损耗）。冒烟按字面记 FAIL 不
凑绿、双读数存档（`power_divider_judgment.json`）；本文记录建议窗、不
视作已裁定。无阻版特征性劣化（S22≈-6.7dB、S32 隔离仅 -5.62dB）只记读
数不判门——隔离电阻判读须待有阻版真跑（`edb_adapter._land_resistors`
已落地）。

### 6.3 判读纪律

- f0 是否落在 sweep 栅格点上先查（W1 401 点栅格 f0=2.4GHz 恰在格点，
  `f0_on_grid` 存证）；不在格点时取最近格点读数并记偏差。
- passivity σmax 与互易性自洽（branchline S23=S32 到 1e-14）是判读有效
  性的廉价旁证。
- 判读逻辑属确定性内核（数值只在内核）——门值随登记面在档，判读函数在
  src/tests（框架级健康门 `src/rfauto/service/edb_health_gate.py`），
  LLM/脚本不现场发明门。

---

## 7. 数据集道与出口（已落地，操作面见 walkthrough）

- **数据集收集器**：`rfauto.service.dataset_edb_lane.collect_edb_lane_
  dataset`（消费 batch+Touchstone 产物目录，健康门体检、指纹去重、
  parquet/manifest 落盘）；候选发现用只读的
  `discover_edb_lane_candidates`。端到端（含 manifest 键面与查询示例）
  见 `docs/edb_lane_walkthrough.md` §7。
- **CLI 出口**：`rfauto edb build / solve / status` 三叶（`src/rfauto/
  cli/domains/edb.py`）。
- **MCP 出口**：`edb_emit_spec` / `edb_build_solve` / `edb_status` 三工
  具 + 状态/数据集 resource（`src/rfauto/mcp_tools/edb.py`）。
- **服务器/远程**：EDB 批处理进程的远程化待规划。远程扩展时 AEDT 版本
  必须与本机一致（版本配对断言，不一致拒连，无人值守指南 §6 第 7 条）。

---

## 8. 已知缺口与待验证清单（开工前必读）

1. **pyedb dotnet 后端实测机器进程级失败**（§4；issue 原料已备，诊断链
   本机在档）——闭环前 `EdbAdapter.build()` 在该类机器不可用，建库段以
   冒烟的 pyaedt 改道形态为唯一实测通路（walkthrough §3.2）。
2. **层序三口径**：spec 层叠注释"自底向上" × adapter"顺序透传" × pyedb
   `apply_stackup` 逐层 `add_layer_bottom`（首项落物理顶层）——真机首跑
   必以 `edb.stackup.layers` 落位复核（pyedb 0.83 源码核验口径）。
3. **cap_style 已钉**：rfauto config 面统一 `flat`/`sharp`（pyedb 缺省
   round 圆头会在端口落点短 r/2，0.83 源码核验口径）。
4. **power_divider 波端口物理片宽守卫已落地**：wave_port 水平扩展因子
   5×线宽，输出口间距过小时端口片互相交叠（历史 rc=103 真机实证，
   walkthrough §8.4）——现行发射器缺省 `gap_mm=6.0`，`gap_mm ≤ 因子×
   shunt_w` 时 fail-fast 抛 ValueError 并给建议放宽值。
5. **lange 声明不支持**：`emit_lange_spec` 返回结构化拒绝信封（pyedb
   0.83 configuration 无 crossover/air-bridge 原语；升格前置条件随拒绝
   信封给出）——lange 的 air-bridge spec 表达待解。
6. **`-designs <design:setup>` 限定语法**：官方文档口径，本仓未实测该限
   定的具体分隔语法——待验证（无人值守指南 §1.2 同注）。

---

## 9. 证据与来源对照

| 文中主张 | 来源 |
|---|---|
| spec 契约/假设清单 1–8/KNOWN_TEMPLATES/validate_spec | `src/rfauto/adapters/edb_templates/schema.py` docstring |
| 四族发射器拓扑/端口语义/综合链 | `src/rfauto/adapters/edb_templates/{branchline,power_divider,coupled_line,ratrace}.py`（docstring）；单源一致性钉 `tests/unit/test_edb_templates.py` |
| EdbAdapter.build/solve_batch/EdbBuildResult/BatchSolveResult、resistors RLC 处方、版本钉 | `src/rfauto/adapters/edb_adapter.py`（含 docstring 逐条出处） |
| solve_project_batch/build_batch_command/export_touchstone_after_solve、参数序纪律、find_ansysedt_exe 链 | `src/rfauto/adapters/hfss_batch.py`；真机实证=W1 冒烟 REPORT §4.3（本机在档） |
| W1 判读门表/读数/门语义仲裁/端口序存证 | W1 冒烟 REPORT §2–§3 + 两族 `*_judgment.json`（本机在档） |
| pyedb API 名（Edb/configuration.load/run/export、CfgEdgePort 50Ω 硬编码、层序、sweep 词表） | pyedb 0.83 实装源码逐条核验档（本机在档） |
| 无人值守纪律（-Logfile、看门、孤儿、进程隔离哲学） | `docs/unattended_hfss_automation.md` §1/§3/§5 |
| 框架级健康门/门分派/三态 verdict/端到端操作面 | `src/rfauto/service/edb_health_gate.py`；`docs/edb_lane_walkthrough.md` |
| 综合单源参考（发射器综合链同源） | `docs/templates/cline_coupler/`、`ratrace/`、`lange/` 元数据；`src/rfauto/adapters/oe_templates/render_c4.py`、`src/rfauto/core/synthesis.py` |

> 维护约定：本文只写"已验证事实 + 操作纪律"。lange 升格、建库环境件闭
> 环时逐节回填；未实测新口径先标"待验证"。文档与代码改动同 commit。
