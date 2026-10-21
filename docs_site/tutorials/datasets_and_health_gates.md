<!-- PR-10 文档站同步副本：源=docs/tutorials/datasets_and_health_gates.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 数据集与健康门：把 run 沉淀成可查数据

> `runs/` 里的每次仿真怎么变成能 SQL 查询的数据集？入册前那道"体检"
> （G11 健康门）判什么、三态怎么读？本文全程只读操作，命令与旗标经
> `--help` 逐项实测，manifest 与查询/体检输出均为当前工作区实跑记录。
> 读完你将知道：物化、查 manifest、行级查询、覆盖度/可见性，以及
> healthy/suspect/unhealthy 三态与 PASS/WARN/FAIL/UNKNOWN 四级因子的
> 如实判读。
> 英文版（English version）：docs/tutorials/datasets_and_health_gates_en.md
> （2026-10-19 全量复测同笔：注册表 20 数据集、三态计数
> healthy 5573/unhealthy 118/suspect 20 与本文一致）。

## 0. 前置

- 已按 docs/tutorials/getting-started.md 装好环境，工作目录在仓库根
  （`runs/`、`runs/datasets/` 都相对 cwd 解析）。
- 建议先跑过 first_optimization_loop 的 fake run——本文的查询/体检对
  fake 数据同样适用，零 license。

## 1. 两种粒度：run 级与数据集行

- **run 级**：`runs/<run_id>/` 一次仿真（meta.json、S 参数产物、trials、
  报告）。`rfauto runs health`、`rfauto runs compare` 消费这个粒度。
- **数据集行（点级）**：`runs/datasets/<名>/points.parquet` 的一行 =
  一个设计点。来源不只 run——trials/校准样本/代理环/autotune/单次 run/
  工作目录曲线/EDB 快车道产物各有收集道；行 schema 固定 12 列
  （`run_id/model/adapter/algorithm/study_name/seed/params_json/
  metrics_json/cost/point_index/source/provenance_json`，manifest
  `columns` 键照录）。
- 去重指纹：`(model, study_name, seed, params canonical json)`——同一
  设计点重跑不重复入册；注意 `study_name` 参与指纹，工作目录导入会填
  目录名防跨战役折叠。

本文的"健康门"作用在 run 级（体检单次 run），并在数据集物化时作为
入册闸门（只拦真实 FAIL）。

## 2. 物化：datasets materialize

```bash
.venv/Scripts/rfauto.exe datasets materialize --name my_first_dataset
```

把 runs/ 点级数据物化为 Parquet 数据集（指纹去重 + manifest 落盘）。
旗标（`--help` 实测）：`--runs`（逗号分隔 run_id，缺省=全部有 meta 的
run）、`--out-dir`（缺省 `runs\datasets`）、`--registry-sync/--no-registry-sync`
（登记进注册表 dataset 表，缺省读配置）、`--dry-run`（**计划面：枚举
run 清单零写入**——放量前先跑这个核对清单）、`--json`。

物化时默认带 `health_gate: true`：逐来源 run 过 G11 体检，
**verdict=unhealthy（有真实 FAIL 证据）的行禁入注册表**，suspect 放行
但 verdict 留档进 manifest（`health_verdicts` 逐 run 可查，
`n_unhealthy_skipped` 计数）。这就是"数据集默认是体检过的"的含义——
但见 §7，suspect 在册不等于全绿。

## 3. 读 manifest：一个真实样本

每个数据集目录 = `points.parquet` + `dataset_manifest.yaml`。以仓内
`runs/datasets/edb_lane_w1_smoke_20261009/dataset_manifest.yaml` 为例
（关键字段照录、排版压缩，节略以 … 标注；注解为本文所加）：

```yaml
schema_version: '2.0'
name: edb_lane_w1_smoke_20261009
points_file: points.parquet
importer: edb_lane              # 收集道（物化道无此键）
runs_root: ../..                # 相对本 manifest 目录的相对路径
runs_root_note: runs_root 为相对本 manifest 所在数据集目录的 posix 相对路径
  （…）；2026-10 起新生成 manifest 不落盘绝对路径与盘符（数据集条件发布
  脱敏），读取侧对旧绝对路径形态按存在性探测回退兼容。
source_runs:                    # 来源清单（run_id/来源目录/模型/点数）
- {run_id: branchline, source_dir: edblane85/w1_smoke/branchline,
   model: edb_branchline, n_points: 1}
n_points: 2                     # 收集点数（=n_rows 时一一对应）
n_rows: 2
n_dup: 0                        # 指纹重复被折叠数
n_skipped: 3                    # 坏目录如实跳过数（原因进 warnings）
bounds: {…}                     # 逐参数最小/最大（参数空间一眼看）
columns: [run_id, model, adapter, …]   # 12 列固定 schema
dedup_fingerprint: (model, study_name, seed, params canonical json)
health_gate: true
n_unhealthy_skipped: 0
health_verdicts: {edblane85/w1_smoke/branchline: healthy, …}
visibility: private             # 公开/私有双集（public 是 HF 导出前提）
ground_truth:
  policy: adapter 小写含真机引擎词根 hfss/openems/comsol/meas 且不含 fake
  n_gt_rows: 2
notes:
- 'W1 真机冒烟两行（…）正式入库；判读含 FAIL 门的行按 #122 如实保留
  （judgment 原文零改写）…'
```

敏感字段说明：早期 manifest 落过绝对路径/盘符（`runs_root` 为绝对形态），
2026-10 起新生成一律相对形态并带 `runs_root_note` 声明口径，读取侧对旧
绝对形态做存在性探测回退——对外发布数据集前检查这两个键（配合
`visibility` 双集与 §5 的导出面）。`notes` 是人读备注，如实记录判读
语境（含 FAIL 门的行不删数据只标注）。

## 4. 查询：datasets query（DuckDB 直查）

```bash
.venv/Scripts/rfauto.exe datasets query edb_lane_w1_smoke_20261009 \
  --columns run_id,model,adapter --limit 2
```

实测输出：

```
     数据集 edb_lane_w1_smoke_20261009（2
              行，过滤后共 2 行）
┌───────────────┬───────────────────┬─────────┐
│ run_id        │ model             │ adapter │
├───────────────┼───────────────────┼─────────┤
│ branchline    │ edb_branchline    │ hfss    │
│ power_divider │ edb_power_divider │ hfss    │
└───────────────┴───────────────────┴─────────┘
```

旗标逐条核对过（`--help`）：`--where/-w` 单条 SQL WHERE 片段（如
`"cost < 0.1 and model = 'mline'"`，**经白名单校验**，不是任意 SQL）、
`--columns` 逗号分隔列裁剪、`--limit`（缺省 100）、`--order-by/--order/
--offset`（排序分页）、`--format json|csv`（csv 为 RFC4180 文本直出）、
`--json` 信封输出。

**行数语义（最常用错的地方）**：信封里 `n_rows` 是本页返回行数，
`total_rows` 才是过滤后 LIMIT/OFFSET 前的全量——`--limit 1` 时
n_rows=1 而 total_rows=2（MCP 工具同款信封，实测核对过）。拿 n_rows 当
总数会犯 #369 的截断误判；标题行的"过滤后共 N 行"读的就是 total_rows。

同款能力：MCP `query_dataset` 工具（同 service 单源，见
docs/tutorials/mcp_in_practice.md §5）；UI「数据集」页是注册表只读清单
+ 行级预览（注意 UI 预览的 n_rows 同样是抽样返回行数）。

## 5. 覆盖度、标注、可见性与导出

- **覆盖度**：`rfauto datasets coverage <名>`——点数分布 + 参数空间逐维
  占用率/最弱维（`--bins` 缺省 10）。实测 edb_lane_w5_sweep_20261009：

  ```
  ✓ edb_lane_w5_sweep_20261009（5 行）
    mean occupancy: 0.3333333333333333  min: 0.1  最弱维: board_margin_mm
    常数维: 5（不虚报占用率）
  ```

  补数据前先看最弱维——加密加密在弱维上才有收益；常数维如实单列不算
  占用率。
- **GT 标注**：`rfauto datasets annotate <名>`——按 manifest 里那条
  policy（adapter 词根判定真机/fake）标注 ground truth 并回写 6.3 解锁
  进度（`--threshold` 族级解锁门槛，缺省 100 点），幂等。
- **可见性**：`rfauto datasets visibility <名> public|private`——
  **public 是 HF 导出（export-hf）的放行前提**，manifest 回写。
- **HF 导出**：`rfauto datasets export-hf`——parquet 分片 + README 数据
  卡的本地目录布局（确定性逐字节一致）。发布前回看 §3 的脱敏口径。
- 工作目录形态真机产物（无 meta.json 的 runs 子目录）走
  `discover-workdir`（只读发现）→ `import-workdir`（导入）两步。

## 6. G11 健康门：单 run 体检

```bash
.venv/Scripts/rfauto.exe runs health <run_id>
```

`--help` 原文口径：对单次 run 做求解健康度体检（G11：历史踩坑教训内核
化）；退出码 healthy=0，suspect/unhealthy 或 run 目录不存在=1。九个
确定性因子（factor 名照录注册面，`lesson_ref` 指回踩坑编号）：

| factor | 拦什么（教训出处） |
|---|---|
| excitation | 激励体积死：全带宽透射峰值 < 1e-6（#174 零宽盒/盒边未进网格） |
| cost_distribution | cost 退化常数：trial≥5 且 unique≤1 或方差<1e-12，优化无区分度（#195 带内常数统计量陷阱） |
| timestep | FDTD 时间步塌缩：min/max 比 < 1e-3（#152 近重合网格线，CFL 塌 6 个量级） |
| probe_scale | 各端口 εeff（CalcPort β 口径）互相矛盾=常数归一化偏移（1.0491 探针窗） |
| passivity | 无源性：max\|S\| ≤ 1.01（SpecEvaluator 口径） |
| reciprocity | 互易性：max\|Sij−Sji\| < 0.01，只对两向都独立已测的端口对（见 §7 掩码语义） |
| gain | 非物理增益：全带宽透射均值 > 0.5 dB 物理不可能（插损口径） |
| power_balance | 功率守恒闭合：∫q dV vs S 参数耗散功率，rel>3% 只 WARN（dump 覆盖不全/辐射是诊断不是病） |
| thermal_plausibility | 热合理性：热源非负、正热源下 ΔT==0 是 #233 Elmer 恒温陷阱、T_max 超材料额定 |

（测量 run——adapter=vna——另有校准态因子 measurement_calibration：未
校准上浮 WARN。）

**实测一：healthy 的 openEMS run**（`--json` 节选，真实输出）：

```json
{"ok": true, "verdict": "healthy",
 "factors": [
  {"factor": "excitation", "status": "PASS",
   "detail": "全部透射列全带宽峰值 0.9832 ≥ 1e-06，激励非零",
   "lesson_ref": "#174",
   "evidence": {"peak_transmission": 0.9832015476350525, "n_ports": 2}},
  {"factor": "cost_distribution", "status": "UNKNOWN",
   "detail": "cost 序列缺失，无法判定分布", "lesson_ref": "#195"},
  {"factor": "passivity", "status": "PASS",
   "detail": "max|S|=0.9832 ≤ 1.01（1% 容差，SpecEvaluator 口径）"},
  {"factor": "power_balance", "status": "UNKNOWN",
   "detail": "无损耗图积分功率（…），不评估功率守恒"}],
 "meta": {"model": "mline", "adapter": "openems", "status": "done"}}
```

**实测二：unhealthy 的 HFSS run**（真实输出节选，退出码实测 1）：

```json
{"ok": false, "verdict": "unhealthy",
 "factors": [
  {"factor": "cost_distribution", "status": "FAIL",
   "detail": "cost 序列退化常数（8 个 trial，unique=1，方差=0.000e+00 < 1e-12）：优化无区分度，疑带内常数统计量陷阱",
   "lesson_ref": "#195",
   "evidence": {"n_trials": 8, "n_unique": 1, "variance": 0.0}},
  {"factor": "excitation", "status": "UNKNOWN",
   "detail": "S 参数缺失，无法判定激励是否死"}]}
```

批量面：`rfauto runs health --all`（`--runs-root/--since/--template/
--campaign/--limit` 收窄扫描域，`--json` 出聚合账）——G11 从"手工逐点"
变周批门；退出码按 unhealthy 名单非空=1（suspect 放行留档）。

## 7. 如何判读：三态 verdict × 四级 factor（如实口径，不凑绿）

- **factor 级**：PASS / WARN / FAIL / UNKNOWN。
  **UNKNOWN 不是 PASS 的降级，也不是被悄悄放过**——产物缺失/解析失败/
  该项证据不足时如实 UNKNOWN，单项异常不传染（体检是 best-effort：run
  目录不存在 → ok=false + errors 说明，不抛异常）。
- **verdict 聚合规则**（内核原文口径）：任一 FAIL → unhealthy；无 FAIL
  有 WARN → suspect；否则 healthy。`ok` 字段 = verdict=="healthy"，即
  **suspect 也算"不可采信"**（注册表门禁消费这个口径；报告里 verdict
  保留细分）。
- **门禁消费口径**：数据集物化的 health_gate 只拦 verdict=="unhealthy"
  （真实 FAIL 证据）；suspect 不拦但 verdict 记进 manifest，供查询侧
  降权/过滤。换句话说：**在册 ≠ 全绿**——引用数据集行前可回查
  `health_verdicts`。
- **互易性掩码语义（最常见的假阳性来源）**：openEMS 单激励 sparams.csv
  是部分 S 矩阵（只测 S11/S21[/S31/S23]，S12/S13 置零），解析器带"已测
  掩码"——互易性只校两向都独立已测的端口对，一对都没有 → UNKNOWN 不拦
  （修正"置零元素 vs 已测元素"假阳性，#314 同族）；服务层载入优先级 =
  可解析的 sparams.csv（掩码载体）**优先于** Touchstone——单激励写入方
  落盘的 Touchstone 是零填充部分矩阵，按全矩阵逐对查互易必假阳性；
  csv 存在但全部解析失败 → 不回退 Touchstone（掩码载体损坏=证据损坏），
  S 参数因子走 UNKNOWN 低证据。
- **判读纪律**：FAIL 先分清"数据坏"与"判据不适用"（换口径而非重跑/
  凑绿）；观测字段缺失时如实重建元数据，不伪造 metrics/gates。深谐振
  谷族另注意 dB 门限本身可能误定——深谷随网格加密更深，dB 域误差可反
  向爆炸，消费口径用线性域 |Γ| 或以 εeff 作精度锚，而非继续加密凑门。

## 8. 与 edb_lane（EDB 快车道）数据集的关系

`rfauto edb`（build/solve/status 三命令）是 PyEDB 建库 + hfss_batch 批解
的平面族快车道，其产物目录既不是 meta.json run 也不是工作目录曲线形态，
由专门收集道 `service/dataset_edb_lane.py` 入册（数据工厂第⑥类产物通
道）：参数只从发射面 `*_spec.json` 搬（导入器不产生数字），判读取
`*_judgment.json`，Touchstone 只读元数据；行 schema/去重指纹与物化道
同构（同批次内同设计点折叠，跨批次不折叠）；cost 无统一语义置 NULL；
adapter 恒 "hfss"（构造性事实）自动入 GT 标注。

识别方式：manifest `importer: edb_lane`、模型名 `edb_*` 前缀。当前注册
表实测在册 4 个（2026-10-09）：`edb_lane_w1_smoke`（2 行冒烟）、
`edb_lane_gap_sweep`（3 行）、`edb_lane_w5_sweep`（5 行）、
`edb_lane_w10_families`（6 行，coupled_line/ratrace 两族）。MCP 侧有
`rfauto://edb/status` 与 `rfauto://edb/datasets` 两个只读资源同源透出。

## 9. 下一步

- MCP 客户端里做同一套查询（list_datasets/query_dataset 工具）：
  docs/tutorials/mcp_in_practice.md
- warm-start：把数据集历史样本注入优化先验：`rfauto warm-start --help`
- 门禁/判据面总读法：docs/how-to/read-verdict-gates.md
- 校准工作台（UI `#/calibration`）消费的校准产物与本文体检同一 G11 底座

## 附：本文核对清单

| 命令/数字 | 核对方式 | 结果 |
|---|---|---|
| `rfauto datasets --help` 及 materialize/query/coverage/visibility/annotate/export-hf/discover-workdir/import-workdir | 实跑 | 过（八子命令，旗标逐条对） |
| `rfauto datasets query … --limit 2` | 实跑 | 过（§4 输出已贴） |
| n_rows vs total_rows | CLI `--help` 信封说明 + MCP query_dataset limit=1 实调 | 过（n_rows=1，total_rows=2） |
| `rfauto datasets coverage edb_lane_w5_sweep_20261009` | 实跑 | 过（§5 输出已贴） |
| `rfauto runs health --help` | 实跑 | 过（退出码/批量面旗标逐条对） |
| healthy 样本（openEMS mline run） | `runs health <id> --json` 实跑 | 过（§6 节选照录） |
| unhealthy 样本（branchline run，#195 FAIL） | 实跑+退出码复测 | 过（verdict=unhealthy，exit=1） |
| 九因子名单 | `core/solve_health.py` 内核 + 两例实跑 factors 并集 | 过（9 因子+测量分支 1） |
| manifest 样本 | `runs/datasets/edb_lane_w1_smoke_20261009/dataset_manifest.yaml` 实读 | 过（§3 照录，节略以 … 标注） |
| 注册表数据集数（20）与三态计数（healthy 5573/unhealthy 118/suspect 20，各 manifest 汇总） | MCP list_datasets 实调 + manifest 扫描脚本实测（2026-10-11） | 过 |
| edb_lane 在册 4 个及行数 | 各 manifest 实读 | 过 |
| 三态/门禁消费口径 | `core/solve_health.py`、`service/health_service.py` docstring 实读 | 过（§7 引语均出自原文） |
