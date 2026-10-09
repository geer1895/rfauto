# EDB 快车道端到端教程（walkthrough）：从设计参数到数据集

> 状态：正式文档（2026-10 首版）。
> 定位：**按序执行**的 walkthrough——每步给真实命令与真实产物摘录，从
> 一行设计参数（`f0_ghz=2.4`）走通到一行可查询的数据集记录。概念、
> spec schema 五契约字段、门语义仲裁等**参考型**内容不在本文重复，正本
> 在 `docs/edb_lane_guide.md`（下称"指南"）；无人值守通用纪律在
> `docs/unattended_hfss_automation.md`（下称"无人值守指南"）。
> 证据基线：pyedb 0.83.0 × pyaedt 1.4.0 × skrf 2.1.0 × AEDT 2025 R1
> （v251）。文中数字凡标"实测于本机 2026-10"者全部来自真机产物：W1 冒
> 烟战役（判读正本 `REPORT.md`）与 W5 五点战役。`#NNN` 为开发过程沉淀
> 的坑号。runs/ 产物不入 git，本机在档可复核。
> 命令行 help 文本逐字核自本机 2026-10 已装 CLI
> （`src/rfauto/cli/domains/edb.py`，服务层
> `src/rfauto/service/edb_lane_service.py`）。

---

## 0. 全链一览

```text
设计参数（f0_ghz 等，recipe/CLI/MCP 同一参数面）
  ① 前置：AEDT 安装 + rfauto[edb] extra + 自检
  ② 发射：rfauto edb build --dry-run 看计划 → 真跑建库（.aedb + config 存证）
  ③ 求解：rfauto edb solve --export（ansysedt -BatchSolve → -batchextract 二段导出）
  ④ 判读：<stem>_judgment.json 五门 + <stem>_health_gate.json 七因子健康门
  ⑤ 批量：五点 f0 扫描循环（W5 战役实测 438.7s 总耗时）
  ⑥ 入库：collect_edb_lane_dataset → datasets query 直查
  ⑦ 排障：W1–W5 四则实证（dotnet 阻断 / -Logfile 序 / 3D Layout 导出分派 / rc=103）
```

每求解一个独立短命 `ansysedt` 进程，全链没有长驻桌面会话（哲学与动机
见指南 §1 与无人值守指南 §1.2/§4）。本文按 branchline 主线走查，
power_divider 在排障 §8.4 出场。

---

## 1. 前置：许可、安装与自检

### 1.1 AEDT 安装与 exe 发现

快车道的求解/导出段只消费工程文件，靠 `find_ansysedt_exe()`
（`src/rfauto/adapters/hfss_batch.py`）发现本机 `ansysedt.exe`，
优先级：入参 `ansysedt_exe` → 环境变量 `RFAUTO_AEDT_PATH` → 自动探测
（Windows 注册表 + `ANSYSEM_ROOTxxx`）。本机实测（2026-10，W1
REPORT §1，本机在档）：自动探测链命中 AEDT 2025 R1（v251）安装目录
下的 `ansysedt.exe`。

许可面：批处理求解占一次 AEDT 许可；`-batchextract` 官方旗标口径是
"非图形跑脚本后自动退出，不做求解 license 检查"
（`build_batch_extract_command` docstring）——发射前确认许可可达；
license 类失败按无人值守指南 §3.1 指数退避后再判死。

版本钉：建库段缺省 `version="2025.1"`（对齐基准），env
`RFAUTO_EDB_AEDT_VERSION` 可覆盖（`src/rfauto/adapters/edb_adapter.py`
`_AEDT_VERSION_ENV`）。**服务器/远程扩展时版本必须=本机**（版本配对
断言，无人值守指南 §6 第 7 条）。

### 1.2 Python 依赖

```bash
pip install rfauto[edb]        # = pyedb>=0.83（pyproject.toml extras）
pip install "pyedb[dotnet]"    # pyedb dotnet 后端硬依赖（ansys-pythonnet）
pip install scikit-rf          # 判读/收集复读 Touchstone（或 rfauto[openems]）
```

**本机现状（如实，实测于本机 2026-10）**：pyedb 0.83 dotnet 后端
`Edb()` 在 `Database.Create` 处进程级失败（stderr
`EVP_DecryptInit ... could not load the shared library`，exit 1，无
Python 异常可捕获；gRPC 后端要求 AEDT 2026.1+，2025 R1 无绕行）。
诊断链存 W1 冒烟档案（REPORT §4.2，本机在档）。**该环境件闭环前，
`EdbAdapter.build()`（即 `rfauto edb build` 真跑）在本机不可用**——但
dry-run 计划态（零 pyedb）、批解/导出/判读/入库各段只消费工程文件，
不受影响。本机实测通路是建库段改道 pyaedt 非图形会话（§3.2），几何
单一来源不变（仍由发射器产 spec）。

### 1.3 零成本自检

不碰许可、不写盘、零 pyedb 的最小自检就是 §2 的 `--dry-run`：它能过 =
发射器综合内核与适配器契约双检通过。注意它**不证明** pyedb 可用
（dry-run 有意绕开 pyedb）——建库段的真机可用性只能真跑验证（本机
现状见上）。

---

## 2. 第一步 发射 spec：先 `--dry-run` 看计划

`rfauto edb` 子应用三叶（help 原文，实测于本机 2026-10）：

```text
rfauto edb --help:
  EDB 快车道（PyEDB 建库+hfss_batch 批解，平面族发射器）
  Commands:
    build   发射 spec + EDB 建库（pyedb configuration → .aedb 工程+存证）。
    solve   批处理求解（ansysedt -BatchSolve）+ 可选 Touchstone 批后导出。
    status  扫描产物根目录的快车道资产清单（工程/存证/日志/Touchstone）。
```

设计参数从 recipe/命令行进来都是同一面：`-p k=v`（可多次，值走 JSON
解析，嵌套 stackup/sweep dict 可直接传；`f0_ghz` 必填）。所有尺寸由
`core.synthesis` 闭式综合产出，**禁止手抄毫米数**（指南 §2）。

先看计划（真实命令与真实输出，实测于本机 2026-10）：

```console
$ rfauto edb build --template edb_branchline -p f0_ghz=2.4 --dry-run
✓ dry-run 计划态（零写盘零 pyedb） template=edb_branchline
workdir=runs/edb_lane
  spec: traces=8 ports=4 resistors=0
  config 段: boundaries, modeler, ports, setups, stackup
```

dry-run = 发射器综合自检 + 适配器契约双检（`spec_to_config_json` 纯函数
再过一遍），零写盘零 pyedb——无 license 环境的计划态冒烟。

当前发射分派面（`edb_lane_service._emitters`，实测于本机 2026-10 逐一
dry-run 验证）：

| template | dry-run 摘要 | 状态 |
|---|---|---|
| edb_branchline | traces=8 ports=4 resistors=0 | 支持 |
| edb_power_divider | traces=6 ports=3 resistors=1（RISO） | 支持 |
| edb_coupled_line | traces=6 ports=4 resistors=0 | 支持 |
| edb_ratrace | traces=12 ports=4 resistors=0 | 支持 |
| edb_lange | — | 声明不支持：结构化拒绝信封（pyedb 0.83 configuration 无 crossover/air-bridge 原语；升格前置条件指 lange 发射器 docstring） |

> 注：`edb build --template` 的 help 文本现写"edb_branchline 或
> edb_power_divider"（两落地族），分派表已扩到四族——以
> `edb_lane_service._emitters` 为准。schema 白名单
> `KNOWN_TEMPLATES` 冻结二元组属 validate_spec 豁免口径（schema.py
> 模块注释），与发射分派表是两个面。

真跑建库（通用形态，在 pyedb dotnet/gRPC 可用的机器上）：

```console
$ rfauto edb build --template edb_branchline -p f0_ghz=2.4 --workdir runs/edb_lane
✓ EDB 工程已建 → runs/edb_lane/edb_branchline.aedb
  config 存证: runs/edb_lane/edb_branchline_config.json
```

产物两件：`.aedb` 工程（同名占用时数字后缀顺移不覆盖）与
`<stem>_config.json` 存证（可用 `edb.configuration.load` 复现）。同名
再次 `--dry-run` 后换 `--name bl_f0_2p4` 即得 W5 战役的产物名形态。

**spec 长什么样**（真实摘录，W5 战役 f0_2p4 点 spec JSON，本机在档；
实测于本机 2026-10，`params` 全部是综合内核产出）：

```json
{
  "template": "edb_branchline",
  "schema_version": 1,
  "units": {"length": "mm", "frequency": "GHz"},
  "params": {
    "f0_ghz": 2.4,
    "z0_ohm": 50.0,
    "series_w_mm": 1.8702732602391428,
    "shunt_w_mm": 1.1133408215162708,
    "series_len_mm": 18.0890969702821,
    "shunt_len_mm": 18.488507896952576,
    "eps_eff_series": 2.9803355693433917,
    "eps_eff_shunt": 2.8529569182441734,
    "feed_len_mm": 5.0,
    "port_roles": "P1 输入/P2 直通/P3 耦合/P4 隔离（串联臂 1-2、4-3，并联臂 1-4、2-3）"
  },
  "stackup": {"materials": [{"name": "copper", ...},
             {"name": "rogers4350b_h0.508", "permittivity": 3.66, ...}],
              "layers": [{"name": "GND", "type": "signal", ...},
                         {"name": "SUB", "type": "dielectric", ...},
                         {"name": "TOP", "type": "signal", ...}]},
  "traces": [ ... 8 段 ... ], "ports": [ ... 4 个 wave_port ... ]
}
```

字段契约与三条硬约束（仅 50Ω / 全域 mm·GHz / 未知键 fail-fast）见指南
§3，不重复。硬约束被违反时发射器 fail-fast，"带病 spec"到不了 adapter。

---

## 3. 第二步 建库：设计入口与本机改道

### 3.1 设计入口

`rfauto edb build`（无 `--dry-run`）→
`edb_lane_service.edb_build` → `EdbAdapter.build(spec)`：
config JSON 存证 → 惰性导入 pyedb → 新建 `.aedb` →
`configuration.load(config, append=True, apply_file=True)` 一次注入 →
`resistors` 逐条 lumped RLC 落地（功分器 RISO 用）→ `save_edb()`/
`close_edb()`。`resistors` 只在 spec 声明、不发进 config modeler
（防逐字套用 config 时变金属短路，指南 §3/§4）。

MCP 面同一语义：`edb_emit_spec` / `edb_build_solve` /
`edb_status` 三工具（`src/rfauto/mcp_tools/edb.py`），其中
`edb_build_solve` 是"建库+可选批解"一站式（`solve=True` 真机 opt-in）。

### 3.2 本机实测通路：pyaedt 改道（W1/W5）

如 §1.2，本机 pyedb dotnet 后端进程级失败，真跑 `edb build` 报
`EDB 建库失败: ...`。W1 冒烟的改道（此后 W5 全程复用）：

- 冒烟战役的建库脚本（本机在档）：**消费同一发射器产出的 spec**，用
  pyaedt `Hfss3dLayout` 非图形会话原生建模（层叠/平面/走线/端口/
  setup+sweep/保存），`finally` 必释放；
- W5 战役的 point worker 逐行复用它（每点独立子进程）。

真实建库证据（W5 战役 f0_2p4 点 `state.json` 的 `build` 节，本机在档；
实测于本机 2026-10）：

```json
{"route": "pyaedt Hfss3dLayout native (W1 改道复用)",
 "design": "bl_f0_2p4_d1", "layers": ["GND", "SUB", "TOP"],
 "materials": ["copper", "rogers4350b_h0.508"],
 "elapsed_s": 21.1, "ok": true, "n_ports": 4}
```

W1 分步时长正本（REPORT §1 表，本机在档；实测于本机 2026-10）：
branchline 建库 21.0s / 求解 82.9s（rc=0）/ Touchstone 导出 16.3s /
判读 0.4s；emit 两族均 <0.01s（纯函数）。

改道只动"谁把 spec 画进工程"，不动"spec 从哪来"——③④⑤⑥ 各段
消费的工程文件/判读 JSON/入库记录与设计入口完全同构。

---

## 4. 第三步 批处理求解 + Touchstone 导出

```console
$ rfauto edb solve runs/edb_lane/edb_branchline.aedb
```

`--export` 缺省开（`--export/--no-export`，help 原文："求解成功后批后
导 Touchstone（-batchextract 第二段进程；失败只告警不推翻求解 ok）"）。
`--timeout-s` 缺省 3600s（每段进程的 watchdog，`<=0` 不设超时）；
`--design/--setup` 限定 `-designs <design:setup>`（缺省自动枚举；该限定
语法的具体分隔形态官方文档口径、本仓未实测——待验证，指南 §8.6）。

实际发生两段短命进程（真实命令摘录，W5 战役 f0_2p4 点 `state.json`
solve 节，本机在档；实测于本机 2026-10；工程路径在末位是硬纪律，
见 §8.2）：

```text
段1 求解: ansysedt.exe -ng -BatchSolve -Logfile <dir>\ansysedt_batch_<stem>.log  <stem>.aedt
段2 导出: ansysedt.exe -ng -batchextract <dir>\batch_extract_touchstone_<stem>.py  <stem>.aedt
```

**为什么必须二段**：`-BatchSolve` 只求解不产网络参数——W1 实测
artifacts=0（REPORT §4.4），判读断链；求解成功后由 `-batchextract`
（官方旗标：非图形跑脚本后自动退出）跑内嵌 IronPython 脚本
`ExportNetworkData` 导出。脚本由 `hfss_batch.build_batch_extract_script`
按字面量烘焙（14 参与 hfss_adapter 主路径逐参一致），落盘留档
（`batch_extract_touchstone_<stem>.py`）。

W5 真实 solve 段回执（`state.json` → `solve`，rc=0、elapsed_s=63.485、
`errors` 里那条导出告警正是 §8.3 的历史 bug，修复后自动分派）：

```json
{"ok": true, "rc": 0, "timed_out": false, "project_kind": "aedt",
 "elapsed_s": 63.485,
 "logfile": "...\\f0_2p4\\ansysedt_batch_bl_f0_2p4.log",
 "artifacts": []}
```

信封字段（`edb_lane_service.edb_solve`）：
`solve:{ok, rc, timed_out, logfile, artifacts, elapsed_s}` +
`export:{ok, out_file, n_ports, rc, timed_out, errors}` + `warnings`。
**导出失败只并告警、不推翻求解 ok**（#105 best-effort）。

导出产物名：先按占位名 `<stem>_export.s2p` 落盘，再按文件内容反推实际
端口数改名 `.sNp`（skrf 只按扩展名推 rank，#248/#309）。W5 实测：
`f0_2p4/bl_f0_2p4_export.s4p`（n_ports=4）。`renorm` 缺省 False=原生
参考基（`export_touchstone_after_solve` 的 `renorm=True` 才是 50Ω 重归
一，远程 L2 通道口径）。

进程治理：watchdog 到点整树击杀（psutil 两段 + taskkill 兜底）并如实记
`timed_out=True`；本模块只杀自己 Popen 拉起的树，他人孤儿归
`infra.desktop_guard` 单源（#245 不盲杀）。

---

## 5. 第四步 判读：judgment 五门 + 健康门七因子

判读输入 = 批后 Touchstone（skrf 读 `.s4p`/`.s3p`）。端口序=AEDT 端口
号序 P1..Pn，头注释即存证（W5 真实头：

```text
! Touchstone file from project bl_f0_2p4
! Exported from HFSS 3D Layout Design 2025.1.0
! Port[1] = Port1  ...  ! Port[4] = Port4
```

）。branchline 端口语义：P1 输入 / P2 直通 / P3 耦合 / P4 隔离。

### 5.1 `<stem>_judgment.json` 逐字段

真实摘录（W5 战役 f0_2p4 点 judgment JSON，本机在档；实测于本机
2026-10，下同）：

```json
{"ok": true, "all_pass": true,
 "f0_ghz": 2.4,
 "touchstone": "...\\f0_2p4\\bl_f0_2p4_export.s4p",
 "n_ports": 4, "n_freqs": 401,
 "f_range_ghz": [1.68, 3.12],
 "f0_on_grid": true, "grid_step_ghz": 0.0036,
 "readings": {
   "s11_db@f0": -34.21927595015303,
   "s21_db@f0": -3.5838086440794066,
   "sigma_max@f0": 0.9925094124016509,
   "sigma_max_fullband": 0.9946259623056684,
   "f_res_ghz_s11min": 2.4,
   "f0_offset_pct": 0.0,
   "s31_db@f0": -2.869093951295858,
   "s41_db@f0": -33.22626123612451 },
 "gates": [ ...五门，见下... ],
 "health_gate": {"schema": "edb-health-gate-v1", "verdict": "PASS",
                 "summary": {"n_pass": 7, "n_fail": 0, "n_unknown": 0}},
 "port_order_assumption": "Touchstone 端口序=AEDT 端口号序 P1..Pn（头注释存证）"}
```

逐字段怎么读：

- `f0_on_grid`：f0 是否落在 sweep 栅格点上（判读纪律：不在格点取最近
  格点并记偏差）。本例 401 点栅格、步距 0.0036GHz，2.4GHz 恰在格点。
- `readings`：物理读数主体。`f_res_ghz_s11min`=带内 |S11| 谷位（本例
  **f_res=2.400GHz**，f0 偏移 0.0%）；信息读数（不判门）S22=-26.5/
  S33=-33.4/S44=-25.8/S23=-32.98 dB，互易自洽到 1e-14。
- `gates`：任务书五门逐条 `{item, label, reading, op, bound, pass}`。

branchline 五门表（W5 @2.4GHz 实测，5/5 PASS；与 W1 门口径的差异见
5.2）：

| 判据 | 门 | W5 读数 | 判定 |
|---|---|---|---|
| s11_db@f0 | ≤ -15 dB | **-34.22 dB** | PASS |
| s21_db@f0（直通） | ∈ [-3.8, -2.5] dB | **-3.584 dB** | PASS |
| s41_db@f0（隔离） | ≤ -20 dB | **-33.23 dB** | PASS |
| sigma_max_fullband | ≤ 1.01（1% 容差） | **0.9946** | PASS |
| f0_offset_pct | abs ≤ 5% | **0.0%**（f_res 恰 2.400GHz） | PASS |

### 5.2 W1 与 W5 的门口径差异（如实）

W1 冒烟（实测于本机 2026-10）直通窗还是 [-3.5, -2.5]，-3.584 超窗
0.084dB **如实记 FAIL**（#122 不凑绿）；门语义仲裁（REPORT §3.2）后
裁定物理窗 [-3.8, -2.5]（理想等分 -3.01dB + 0.8dB 实现容差），W5 五点
全按此窗判 PASS。两代 judgment JSON 都在档（W1/W5，本机在档），这正是
"门改动必须带真机/仲裁出处"（#274）的活例子。

### 5.3 `edb-health-gate-v1` 健康门（框架级七因子）

第二份产物 `<stem>_health_gate.json`
（`src/rfauto/service/edb_health_gate.check_edb_batch_health`，消费
hfss_batch 结构化回执 + Touchstone，与任务书五门相互独立）。真实摘录
（W5 战役 health gate JSON，本机在档）：

```json
{"schema": "edb-health-gate-v1", "verdict": "PASS",
 "template": "edb_branchline",
 "criteria": [
   {"factor": "solve_status", "status": "PASS",
    "detail": "求解成功（rc=0 未超时，elapsed_s=63.485）"},
   {"factor": "touchstone",   "status": "PASS", "detail": "Touchstone 在档且可读: ..."},
   {"factor": "port_count",   "status": "PASS", "detail": "端口数一致（4）"},
   {"factor": "passivity",    "status": "PASS",
    "detail": "σmax=0.9946 ≤ 1.01（1% 容差内）"},
   {"factor": "s11_dip",      "status": "PASS",
    "detail": "S11@f0=-34.22 dB ≤ 门 -15.00 dB（门作用域=explicit）"},
   {"factor": "s_split_window", "status": "PASS",
    "detail": "|S21|@f0=-3.58 dB、|S31|@f0=-2.87 dB 双落窗 [-3.8, -2.5] dB"},
   {"factor": "reciprocity",  "status": "PASS",
    "detail": "互易（max|Sij−Sji|=1.25e-14 < 0.01，全矩阵口径）"}],
 "summary": {"n_pass": 7, "n_fail": 0, "n_unknown": 0}}
```

字段解读：

- 每条 criterion 带 `lesson_ref` 指回踩坑原文（#157/#316/#248/#274/
  #314），evidence 里是数值与门作用域。`s11_dip` 门分派链（#274 家法）：
  调用方显式门 > 模板登记表 `S11_DIP_DB_BY_TEMPLATE` > 通用缺省
  -10dB；`s_split_window` 是功分器族专属（登记表
  `S_WINDOW_DB_BY_TEMPLATE`，无通用缺省窗，未登记族该判据整体缺席）。
- `verdict` 三态：任一 FAIL → FAIL；否则任一 UNKNOWN → UNKNOWN；全
  PASS → PASS（#122 不冒充）。`ok` 只是报告字段（=verdict==PASS）。
- `reciprocity` 的 `measured_mask=None` 是 #314 掩码纪律的如实声明
  （Touchstone 全矩阵无掩码载体）。

数据集道（§7）的健康门走另一入口（G11 目录级 `health_check_run`，
verdict 词汇 healthy/unhealthy/suspect）——两门词汇不同，别混用。

---

## 6. 第五步 批量：五点 f0 扫描（W5 战役实测）

### 6.1 循环骨架

批量=每点一个子进程 + 每点看门 + 前后 ansysedt 清点。W5 战役驱动脚本
（本机在档；实测于本机 2026-10）的骨架可直接抄：

```python
# 五点 f0 扫描（W5 实测骨架，节选；完整驱动脚本本机在档）
POINT_TIMEOUT_S = 900.0                    # 预算 ~5min/点，给 2× 余量
for f0 in (2.2, 2.3, 2.4, 2.5, 2.6):
    tag = f"f0_{str(f0).replace('.', 'p')}"
    stem = f"bl_{tag}"
    cmd = [sys.executable, "-u", "point_worker.py",
           "--f0", str(f0), "--root", ROOT]   # -u：日志实时落盘
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), timeout=POINT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        kill_matching_ansysedt(stem)           # 按工程 stem 匹配，不盲杀（#245）
```

point worker 每点做完整单点链：emit → 建库 →
`solve_project_batch(..., export_touchstone=True)` → 判读（退出码
0=全绿 / 1=建库失败 / 2=求解失败 / 3=判读有 FAIL，judgment 照写）。
发射前 `list_ansysedt()` 清点、收工后复核残留=0。

通用 CLI 循环形态（在 EdbAdapter.build 可用的机器上；本机真跑建库
见 §3.2 改道）：

```bash
for f0 in 2.2 2.3 2.4 2.5 2.6; do
  tag=$(echo $f0 | tr . p)
  rfauto edb build --template edb_branchline -p f0_ghz=$f0 \
      --workdir runs/edb_sweep --name bl_f0_$tag
  rfauto edb solve runs/edb_sweep/bl_f0_$tag.aedb --timeout-s 1800 --json
done
```

### 6.2 W5 实测时长与读数

五点全绿（导出段经恢复路由，见 §8.3；数据实测于本机 2026-10，
campaign summary 在档）：

| 点 | 单点 wall | solve rc | S11@f0 dB | S21@f0 dB | S41@f0 dB | σmax 带内 | f0 偏移 | 判读 |
|---|---|---|---|---|---|---|---|---|
| 2.2 GHz | 90.5s | 0 | -34.249 | -3.491 | -32.864 | 0.9948 | +0.45% | 5/5 PASS |
| 2.3 GHz | 90.6s | 0 | -37.559 | -3.570 | -31.546 | 0.9948 | +0.15% | 5/5 PASS |
| 2.4 GHz | 85.9s | 0 | -34.219 | -3.584 | -33.226 | 0.9946 | 0.00% | 5/5 PASS |
| 2.5 GHz | 86.0s | 0 | -31.853 | -3.519 | -31.895 | 0.9945 | +0.75% | 5/5 PASS |
| 2.6 GHz | 85.7s | 0 | -34.270 | -3.528 | -31.040 | 0.9945 | +0.60% | 5/5 PASS |

总账：`total_point_s=438.7`（五点 wall 之和；含恢复导出与判读）；导出
恢复每点 wall 5.2–5.3s；前后 ansysedt 残留均 0。单点成本拆解
（f0_2p4）：建库 21.1s + 求解 63.5s + 导出 ~5s + 判读 <0.5s。

批量纪律（全部 W1–W5 实证，细则见无人值守指南 §6 十条自查）：
驱动与 worker 一律绝对路径 + `-u`；单点超时=先杀 worker 树、再按工程
stem 匹配清理遗孤 ansysedt（不盲杀）；任务毕清点残留必须为 0。

---

## 7. 第六步 数据集入库与查询

### 7.1 收集器调用

EDB 道收集器是服务层函数
`rfauto.service.dataset_edb_lane.collect_edb_lane_dataset`
（**暂无 CLI 叶**——如实；候选发现可用只读的
`discover_edb_lane_candidates`）：

```python
from rfauto.service.dataset_edb_lane import collect_edb_lane_dataset

result = collect_edb_lane_dataset(
    name="edb_lane_w5_sweep",
    run_ids=["edb_w5_sweep/f0_2p2",
             "edb_w5_sweep/f0_2p3",
             "edb_w5_sweep/f0_2p4",
             "edb_w5_sweep/f0_2p5",
             "edb_w5_sweep/f0_2p6"],
    health_gate=True,      # G11 目录级体检，仅 unhealthy 禁入
    fmt="parquet",
)
print(result["n_rows"], result["ground_truth"]["n_gt_rows"])
```

W5 实跑产物 manifest 关键行（本机在档；实测于本机 2026-10）：

```yaml
importer: edb_lane
n_rows: 5
per_model_rows: {edb_branchline: 5}
health_gate: true
health_verdicts:
  f0_2p2: healthy   # 五点全 healthy
n_dup: 0
ground_truth: {n_gt_rows: 5, per_model: {edb_branchline: 5}}
bounds: {f0_ghz: [2.2, 2.6], z0_ohm: [50.0, 50.0], ...}
dedup_fingerprint: (model, study_name, seed, params canonical json)
```

收集语义（源码 `dataset_edb_lane.py` docstring，#251 谱系第⑥类产物
通道）：目录识别标志=`<stem>_judgment.json`；参数唯一来源=`<stem>_spec.json`
的 `params` 段（导入器零数值）；metrics=judgment `readings`
标量 + 判定元数据（ok/all_pass/n_ports/n_freqs/f0_on_grid/grid_step_ghz）
+ `n_gates_pass/n_gates_total`；`adapter` 恒 "hfss"（AEDT 批量求解的
构造性事实）→ 自动命中 GT 白名单标注；`study_name`=批次目录相对 runs
根的 posix 路径（E1 指纹 #322：同批次内同设计点折叠一份，跨战役不折叠）；
重复收集幂等（同指纹不重入，行数只随在盘产物增长）。

### 7.2 查询

数据集落数据集根目录 `<name>/`（`points.parquet` + manifest）后，
`rfauto datasets query` 直接可查（DuckDB 谓词下推）。真实输出
（实测于本机 2026-10）：

```console
$ rfauto datasets query edb_lane_w5_sweep \
      --columns "run_id,params_json,metrics_json" --limit 2
           数据集 edb_lane_w5_sweep（2 行，过滤后共 5 行）
┌────────┬───────────────────────────────┬──────────────────────────────┐
│ run_id │ params_json                   │ metrics_json                 │
├────────┼───────────────────────────────┼──────────────────────────────┤
│ f0_2p2 │ {"board_margin_mm":2.0,...    │ {"all_pass":true,            │
│        │ "f0_ghz":2.2,...}             │  "f_res_ghz_s11min":2.2099,  │
│        │                               │  "s11_db@f0":-34.248875...,  │
│        │                               │  "n_gates_pass":5, ...}      │
│ f0_2p3 │ {..., "f0_ghz":2.3, ...}      │ {..., "f_res_ghz_s11min":    │
│        │                               │  2.30345, ...}               │
└────────┴───────────────────────────────┴───────────────────────  ────┘
```

等值过滤走 `--where`（SQL 片段白名单校验）或便捷参；总数语义看信封
`total_rows`（过滤后 LIMIT 前总行数，#369 治理：`n_rows` 是截断后
行数，别当总数）。

---

## 8. 排障速查（W1–W5 实证）

### 8.1 pyedb dotnet 后端进程级失败 → 改道 pyaedt

**症状**：装齐 `pyedb[dotnet]` 后 `Edb()` 无 Python 异常、进程直接死：
stderr `legacy Provider loading failed` + `EVP_DecryptInit. could not
load the shared library`，exit 1（faulthandler 定位死点在
`Database.Create`，pyedb/dotnet/edb.py:742）。只装 pyedb 本体则只有
`RuntimeWarning: Failed to initialize Dlls.`（无行动价值提示）。
gRPC 后端要求 AEDT 2026.1+，2025 R1 无绕行。
（诊断链与最小复现：W1 冒烟档案 REPORT §4.2，本机在档。）

**处置**：建库段改道 pyaedt 非图形会话原生建模（§3.2），spec
单一来源不变；批解/导出/判读段不受影响。**别在死点上反复重装试**
——W1 已逐项排除 venv shim OpenSSL shim、OPENSSL_MODULES 环境变量、
ossl-modules/legacy.dll 安放、净 PATH、System32 LibreSSL 直接冲突等
假设（REPORT §4.2 逐条在档）。

### 8.2 `-Logfile` 位置纪律（工程恒末位）

**症状**：`ansysedt -ng -BatchSolve <project.aedt> -Logfile <path>`
真机 rc=1，批处理日志：
`The -batchsolve/batchsave/batchextract option requires a filename
which must be specified as the last parameter.`
（AEDT 2025 R1 实测，W1 REPORT §4.3。）

**处置**：`build_batch_command` 恒把工程路径放末位（自己拼命令时照
抄）。另：`-Logfile` 发射必带——非图形会话 `GetMessages` 经常为空，
console log 才是可靠的错误通道（无人值守指南 §3.4）。

### 8.3 HFSS 3D Layout 设计导出分派（无 Analysis 模块）

**症状**：求解 rc=0 全过、`-batchextract` 5s 即退、`*_export.s2p` 未
生成（`errors`："导出文件未生成: ...（脚本/选择器错误通常见 logfile
尾部 [rfauto-batch-extract] 行或 IronPython traceback）"）。W5 首遍
5/5 复现。
**根因**（探针定谳）：HFSS 3D Layout 设计（EDB 快车道
全部产物形态）**无 AnalysisSetup/Setup/Output/Solutions 模块**——
`design.GetModule` 四名全 FAIL，`ExportNetworkData` 直接挂在 design
对象上。
**处置**：现行 `hfss_batch` 导出脚本先探针 Solutions 模块、失败自动
回退 design 级直呼（14 参逐字一致），setup 枚举不可达时按名义名
`setup1:sweep1` 兜底——无旗标自动适配两形态（W5 实证后修入 src）。
历史战役用战役侧恢复脚本补导出+判读（本机在档；恢复 5/5、单点 wall
5.2s），judgment 的 `export_route` 字段如实区分原链路失败与恢复路由
——排查同类问题时先读这个字段。
另两件配套：`QuitApplication` 置于 finally（FATAL 早退也必须退出批处理
会话，否则留孤儿桌面 #265）；被击杀树可能残留 `<project>.lock`，复跑前
按 #157 核对进程后清理。

### 8.4 功分器 gap 守卫 rc=103

**症状**：edb_power_divider 用旧口径 `gap_mm=2.0` 真跑，AEDT 网格生成
失败 **rc=103**：`[error] Port#Port2 intersects mesh body:
Port#Port3`（W1 真机实证，实测于本机 2026-10）。**根因**：EDB/3D
Layout 的波端口物理片宽=水平扩展因子 5×线宽（50Ω 馈线约
5.57mm@缺省层叠），两输出口中心距 2.0mm 时 P2/P3 端口片互相交叠。
**处置**：现行发射器已带渲染期守卫（#347 家法）——缺省
`gap_mm=6.0`（与 HFSS 插件旧口径 2.0 有意分叉），`gap_mm ≤
因子×shunt_w` 时 fail-fast 抛 ValueError 并给建议放宽值（最小可行
间隙 ×1.05 上取 0.5mm 网格，缺省层叠下建议值恰为 6.0）。看到该
ValueError 不是坏消息：它替你省了一轮 rc=103 真跑。

### 8.5 附：两条高频小坑

- **`-BatchSolve` artifacts=0**：批解成功 ≠ 有 Touchstone。产物清单为
  空且 `export=None` 时检查是否忘了 `--export`（缺省开）或求解段没过
  （导出仅 rc==0 且未超时才尝试）。
- **孤儿 ansysedt**：pyaedt 失败路径 release 后可留 `-grpcsrv` 孤儿
  （W1 实测各 ~770MB）。治理四条（枚举拿 pid/ppid/CommandLine、只杀
  孤儿、杀后复核、两档严格度）单源在 `infra/desktop_guard.py`；
  git-bash 下 `taskkill /PID` 的 `/PID` 会被 MSYS 路径转换吃掉，用
  `//PID` 或 PowerShell `Stop-Process -Id`。
- **`edb status` 是平铺扫描**：只扫 `--root` 直下条目（按 stem 归组：
  `.aedb` 目录、`*_config.json`、`ansysedt_batch_*.log`、
  `*_export.s<N>p`），与 `edb build` 的 workdir 平铺布局配套；W5 式
  "每点一个子目录"的战役布局不在其扫描形态内（实测
  `edb status --root <W5 战役目录>` 报"无 EDB 快车道产物"——是扫描形
  态使然，产物本身在档）。`.aedb` 工程的日志/导出名带 `.aedb` 尾缀变
  体，status 已折叠回裸 stem。

---

## 9. 证据与来源对照

| 文中内容 | 来源 |
|---|---|
| CLI 三叶 help/选项面/dry-run 输出 | `src/rfauto/cli/domains/edb.py`；本机 2026-10 实跑实录 |
| edb_build/edb_solve/edb_status 信封字段、lange 结构化拒绝 | `src/rfauto/service/edb_lane_service.py` |
| solve_project_batch/export_touchstone_after_solve 回执、二段进程、参数序纪律、导出分派 | `src/rfauto/adapters/hfss_batch.py`（模块 docstring 含 W5 实证注记） |
| EdbAdapter.build/solve_batch/版本钉/config 存证 | `src/rfauto/adapters/edb_adapter.py` |
| 健康门七因子/门分派/三态 verdict | `src/rfauto/service/edb_health_gate.py` |
| 收集器语义/manifest 键面 | `src/rfauto/service/dataset_edb_lane.py` |
| W1 分步时长/判读表/门语义仲裁/坑清单 | W1 冒烟战役 REPORT.md（§1–§4，本机在档） |
| W5 五点时长/读数/恢复路由/数据集 | W5 五点战役产物（campaign summary、恢复摘要、f0_2p4 点 state/judgment/health gate JSON）+ 数据集 manifest（本机在档） |
| spec schema 五契约/KNOWN_TEMPLATES/发射分派面 | 指南 §2/§3 + `src/rfauto/adapters/edb_templates/schema.py` |
| 无人值守纪律（-Logfile、看门、孤儿、发射十条自查） | `docs/unattended_hfss_automation.md` |
| MCP 出口 | `src/rfauto/mcp_tools/edb.py`（edb_emit_spec/edb_build_solve/edb_status + resource） |

> 维护约定：本文与指南分工——指南讲"是什么/为什么"，本文讲"一步步
> 怎么跑"。CLI 面或回执字段变更时同步改本文对应摘录；新实测数字进
> §5/§6 表格须标实测日期；未实测口径标"待验证"。
