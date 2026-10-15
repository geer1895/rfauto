# 数据湖与查询面：run 产物 → 数据集 → DuckDB 湖 → 查询

> `runs/` 越长越大之后，"我上次那批 openEMS 的 mline run 都在哪、哪些
> 判读过、哪个战役还有半途产物"这类问题就不能再靠翻目录了。本文讲
> rfauto 的三个数据沉淀面怎么串成一条链：**datasets**（点级数据物化成
> Parquet）、**lake**（runs/ 树的 DuckDB 湖索引 + tar.zst 冷层归档与
> 语义压缩）、**db**（SQLite 事务注册表 + DuckDB 分析直读 + 引擎联赛）。
> 文中全部命令与输出为当前工作区只读实测（2026-10-11），个别沙盒演示
> 在系统临时目录做完即删，正文照录时已把临时绝对路径略去。

## 0. 前置与三个名字

- 已按 docs/tutorials/getting-started.md 装好环境，工作目录在仓库根
  （`runs/`、`runs/.lake_index.duckdb`、`runs/registry.sqlite` 都相对
  cwd 解析）。本文全程零 license、零网络。
- 命令一律走 `.venv/Scripts/rfauto.exe`。
- 三个名字别混（服务层各一个模块，#222 实测口径）：

| 名字 | 命令域 | 服务模块 | 一句话 |
|---|---|---|---|
| 数据集 | `rfauto datasets` | `service/dataset_service.py` 等 | run 点级数据 → Parquet + manifest，行级 SQL 查询 |
| 数据湖 | `rfauto lake` | `service/lake_service.py`、`service/lake_compact_service.py` | runs/ 两层目录全量入 DuckDB 索引；冷层 pack/verify/restore；语义压缩 |
| 注册表 | `rfauto db` | `service/db_service.py` | SQLite 事务型注册表（runs 表等）+ DuckDB 直读 + 引擎联赛表 |

## 1. 全景：一份数据的三种沉淀形态

一次 `rfauto run` 结束后，产物落在 `runs/<run_id>/`（meta.json、S 参数、
trials、verdict……）。往上沉淀有三条正交的道：

```text
runs/<run_id>/ （run 级目录，唯一事实源）
   │
   ├─① datasets 物化道：点级参数/指标 → runs/datasets/<名>/points.parquet
   │     消费：datasets query / coverage / warm-start / HF 导出
   │
   ├─② lake 索引道：runs/ 两层目录树 → runs/.lake_index.duckdb（runs_lake_index 表）
   │     消费：lake query / audit-stale / lineage / export-parquet
   │
   └─③ db 注册表道：runs/*/meta.json → runs/registry.sqlite（事务面）
         消费：db query / analytics-attach / league-rebuild+report
```

分工直觉：**要按"设计点"查数值**走①；**要按"目录"盘点 runs 树**
（哪些没判读、哪些该归档）走②；**要事务登记与跨引擎联赛**走③。
①的物化/查询/健康门判读已有专文（docs/tutorials/datasets_and_health_gates.md），
本文不重复，只在 §7 讲它与湖的关系。

## 2. 湖索引：`lake index`（幂等重建）

```bash
.venv/Scripts/rfauto.exe lake index --help
```

选项就三个：`--runs-dir`（扫一级战役目录+二级 run 点**两层**，
缺省 `runs`）、`--db`（缺省 `runs/.lake_index.duckdb`）、`--json`。

对全仓 runs/ 重建一次索引是纯读扫描（数千目录量级，逐目录读
meta/verdict 求精），落一个 DuckDB 文件。用临时沙盒演示全链（沙盒两个
假 run，跑完即删）：

```bash
.venv/Scripts/rfauto.exe lake index --runs-dir <沙盒>/runs --db <沙盒>/lake.duckdb --json
```

```json
{
  "ok": true,
  "n_rows": 3,
  "n_meta_rows": 2,
  "n_verdict_rows": 0,
  "errors": [],
  "n_lineage_edges": 0,
  "db_path": "…（临时目录，略）",
  "table": "runs_lake_index"
}
```

读法：

- 两层目录**全部入索引**（本例 3 行 = 1 个战役目录 + 2 个 run 点）；
  目录级元数据缺字段如实 NULL，不臆造。
- 索引是**重建式快照**：不随新 run 自动追新——下面 §3 末尾有实测证据。
- DuckDB 连接有防御性缺省：内存上限 2GB、线程上限 4（湖索引是低频
  批处理面，防止挤占在跑真机求解，`lake_service` 常量）。

## 3. 湖查询：`lake query`（只读）

```bash
.venv/Scripts/rfauto.exe lake query --help
```

| 过滤器 | 语义 |
|---|---|
| `--template` / `--adapter` / `--study` / `--campaign` | 等值过滤（meta 字段/战役目录名） |
| `--date-from` / `--date-to` | created_date 闭区间（YYYY-MM-DD） |
| `--limit` / `--order-by` / `--order` | 行数上限（缺省 200）/ 白名单排序列 / asc·desc |

沙盒查询（同上索引）：

```bash
.venv/Scripts/rfauto.exe lake query --db <沙盒>/lake.duckdb --template mline --order-by created_ts --order asc
```

```text
path  template  adapter  study  created_date  n_files
demo_campaign/20261001_000000_demo01  mline  fake  lake_tut  2026-10-01  2
demo_campaign/20261001_000100_demo02  mline  openems  lake_tut  2026-10-01  1
2 行
```

本仓真实索引（历史批次建的）同样可查：

```bash
.venv/Scripts/rfauto.exe lake query --template mline --limit 3 --order-by created_ts --order desc
```

```text
path  template  adapter  study  created_date  n_files
20260922_014743_ccbb2894  mline  openems  datafactory_a2d  2026-09-21  4
20260922_014704_e82608e4  mline  openems  datafactory_a2d  2026-09-21  4
20260922_014626_82e51cb6  mline  openems  datafactory_a2d  2026-09-21  4
3 行
```

快照语义的实测证据：查 `--date-from 2026-10-01 --date-to 2026-10-11`
返回 **0 行**（索引建于更早批次，之后的新 run 不在其中）——**先
`lake index` 重建再查**，别把旧快照当全量。查询面是只读参数化 SQL
（值只进 `?` 绑定，永不拼进 SQL）。

## 4. 湖巡检三件：`sweep` / `audit-stale` / `lineage`

### 4.1 `lake sweep`：半产物只读清点

```bash
.venv/Scripts/rfauto.exe lake sweep --max-list 5
```

```text
✓ dirs=11223  complete=10  incomplete=383  empty=6279  unannotated=2506
  20260903_235147_cb982df7/calibration  files=227  markers=['samples.json']
  …（明细按 --max-list 截断）
```

四态口径：`complete`=有 meta；`empty`=零文件空壳；`incomplete`=无 meta
但有产物证据（在跑或中断——meta 是 run 结束才落盘的，#144，别把
incomplete 当垃圾清）；`unannotated`=无 meta 无已知产物。整条命令零改写。

### 4.2 `lake audit-stale`：失效 run 清单

扫全湖找"代码/参数/引擎/环境/预算变了之后判读可能失效"的 run，按原因
分类。退出码：0 无失效、1 有失效行、2 程序性错误——可以直接接 CI 门。

```bash
.venv/Scripts/rfauto.exe lake audit-stale --json
```

```json
{
  "ok": true,
  "n_dirs": 5310,
  "n_checked": 3051,
  "n_stale": 2983,
  "n_fresh": 68,
  "n_unknown_meta": 2259,
  "class_counts": { … }
}
```

n_stale 大是常态（代码在长、判读锚点在重标定），它的用途是**给重跑
排序**，不是给历史定罪；失效原因分类在 `class_counts` 里逐桶计数。

### 4.3 `lake lineage`：跨 run 血缘

数据集 → 上游 run → 渲染 commit 端点（`--up`，缺省），或反向影响面
（`--down`）。依赖索引库里的 `run_lineage` 边表（`lake index` 重建时
一并生成）：

```bash
.venv/Scripts/rfauto.exe lake lineage --run 20260920_002700_2bb07757 --hops 3
```

```text
20260920_002700_2bb07757  model=mline  git_sha=a6dcc7d  (起点)
n_nodes_total=1  children_count=0  hops=3  direction=up
```

该点无上游边（run_once 形态），n_nodes_total=1 如实；数据工厂批次产物
才会展开出边家族。`--expand` 展开全部节点明细（缺省 cap 摘要防爆炸）。

## 5. 冷层归档：`pack` / `verify` / `restore`

战役结束后目录动辄几千文件，湖提供内容寻址的冷层三件套（沙盒实测，
原目录零改动）：

```bash
# ① 打包：确定性文件排序 + 归一化 tar 头 → 同内容重打包 sha256 逐位一致
.venv/Scripts/rfauto.exe lake pack <沙盒>/runs/demo_campaign --out <沙盒>/demo.tar.zst
```

```text
✓ files=3  total=243B
pack=<沙盒>/demo.tar.zst
  sha256=cd9967c654e08a7df5bcdef47531dfa70804ed461a2325288593438d6f07f410
manifest=<沙盒>/demo.tar.zst.manifest.json
```

```bash
# ② 校验：整包 sha256 快校验 + 逐文件 sha256 重算（如实逐文件报告）
.venv/Scripts/rfauto.exe lake verify <沙盒>/demo.tar.zst <沙盒>/demo.tar.zst.manifest.json
```

```text
pack_sha256_ok=True  ok=3  fail=0
  ok  20261001_000000_demo01/meta.json
  ok  20261001_000000_demo01/sparams.csv
  ok  20261001_000100_demo02/meta.json
```

```bash
# ③ 恢复：目标目录必须不存在（绝不覆盖），恢复后逐文件哈希复核
.venv/Scripts/rfauto.exe lake restore <沙盒>/demo.tar.zst <沙盒>/demo.tar.zst.manifest.json <沙盒>/restored
```

```text
✓ restored=3/3  bytes=243
target=<沙盒>/restored
```

manifest 记录每文件的相对路径 + 偏移 + size + sha256，`verify` 不解包
全档也能按偏移定位重算——千文件战役的完整性核对是秒级动作。归档后
原目录零改动；删原目录是**人**的决定，湖只负责让这个决定可验证、可回滚。

## 6. 语义压缩：`lake compact`（缺省 dry-run，--apply 有互锁）

`lake compact` 是湖的"gc 规划面"（`lake_compact_service`）：h5 白名单
保留策略推导（锚注册表/sim_ci golden 基线/目录名启发三路指针源）+
et/ht 内容寻址去重 + 三档（conservative/medium/aggressive）删除统计。
**缺省纯读规划**：

```bash
.venv/Scripts/rfauto.exe lake compact --runs-root runs --json   # 纯读，三档统计
```

真删要 `--apply`，且有前置互锁：XD-5 golden 基线未 pin 时拒绝（先
`rfauto simci-pin-baseline` pin）；缺省走可逆路径——删除清单 h5 先 blob
化进 `runs/.blob_store`（内容寻址 + manifest 审计），观察窗（缺省 30 天）
内可恢复回填，窗满 purge 才物理释放；`--no-reversible` 才是历史直删路径。
另有 `--min-age-h`（缺省 24h，meta 太新的一律不动）与 `--exempt-subtree`
（用户豁免子树）两道保守阀。一句话：**破坏性动作绝不自动执行**。

配套的检索加速面：sparams 的有界 VF 摘要（`sparams.vf.json`，带
L∞ 误差界，不带误差界的摘要不落盘）在索引里有 `vf_summary` 列
（lossless_equivalent / bounded_lossy / NULL），零解压即可按保真等级筛。

## 7. `datasets` 命令域与湖的关系

`datasets` 八子命令（materialize / query / discover-workdir /
import-workdir / coverage / annotate / visibility / export-hf）负责
①号道：把 run 点级数据收成**行**。它和湖的分工与衔接：

| 问题 | 走哪 | 为什么 |
|---|---|---|
| "cost < 0.1 的设计点参数是什么" | `datasets query` | 行级 SQL + json_extract 展开 params |
| "参数空间哪一维没扫到" | `datasets coverage` | 逐维占用率/最弱维 |
| "这批 run 目录哪些没判读/是空壳" | `lake sweep` | 目录粒度盘点，不读数值 |
| "这批目录打包归档" | `lake pack` | 内容寻址冷层 |
| "把湖索引交给外部引擎" | `lake export-parquet` | DuckDB COPY 出 hive 分区冷层（缺省按 created_date 分区，`--overwrite` 才允许覆盖） |

衔接点：数据集物化的指纹去重以 run_id+参数指纹为键（跨战役不折叠），
湖索引的 `lineage` 面再把数据集名连回上游 run。物化全程走健康门
（G11），`--dry-run` 出零写入计划面：

```bash
.venv/Scripts/rfauto.exe datasets materialize -n tut_demo \
  --runs 20260829_191826_da184d1d,20260829_191828_25c6b5d5 --dry-run
```

```text
物化计划（dry-run，零写入） name=tut_demo  格式: parquet
  将物化 2 个 run（健康门 not evaluated）
    20260829_191826_da184d1d
    20260829_191828_25c6b5d5
```

对本仓既有数据集做两个只读查询（列裁剪 + 覆盖度）：

```bash
.venv/Scripts/rfauto.exe datasets query datafactory_m1_mline_20260919 \
  --limit 2 --columns run_id,model,cost
.venv/Scripts/rfauto.exe datasets coverage datafactory_m1_mline_20260919
```

```text
  数据集 datafactory_m1_mline_20260919（2 行，过滤后共 120 行）
┌──────────────────────────┬───────┬──────┐
│ run_id                   │ model │ cost │
├──────────────────────────┼───────┼──────┤
│ 20260920_002700_2bb07757 │ mline │      │
│ 20260920_002731_b1e97e8c │ mline │      │
└──────────────────────────┴───────┴──────┘

✓ datafactory_m1_mline_20260919（120 行）
  mean occupancy: 1.0  min: 1.0  最弱维: w_mm
```

（cost 列空白=该批样本 cost 为 NULL——cost 无统一语义即置 NULL（可空
列契约），由标注/判读面另行回填；覆盖度逐维占用率 1.0 说明参数空间是
满格网格。判读细节见
docs/tutorials/datasets_and_health_gates.md。）

## 8. `db` 命令域：事务注册表与分析直读

`db` 域是 SQLite 事务型注册表（零服务器）+ DuckDB 分析直读：

```bash
.venv/Scripts/rfauto.exe db status
```

```text
runs\registry.sqlite  [存在]  schema_version=1
  runs: 1779
  jobs: 0
  approvals: 0
  datasets: 0
  owners: 0
```

八子命令速查（`--help` 逐条实测过）：

| 命令 | 写/读 | 什么时候用 |
|---|---|---|
| `db init` | 写 | 全新环境建库 + 幂等迁移（重放 applied=0） |
| `db migrate` | 写 | schema 迁移（`--dry-run` 出零写入计划面） |
| `db status` | 读 | 路径/存在性/schema 版本/各表行数（文件不存在不创建） |
| `db reindex-runs` | 写 | 扫 `runs/*/meta.json` 重建 runs 表（upsert 幂等；单文件失败不阻塞） |
| `db query` | 读 | 单条 SELECT 白名单 + `?` 参数绑定（`-p` 传参，拒绝原因进信封） |
| `db analytics-attach` | 读 | DuckDB sqlite 扩展直读注册表（零拷贝分析面，不可用如实 ok=False） |
| `db league-rebuild` | 写 | 扫 runs/ verdict 形态白名单抽取 → `runs/league.duckdb`（幂等重建） |
| `db league-report` | 读 | 按（模板族，量）出 \|delta\| 中位 × wall_s 中位 Pareto 前沿（JSON+md 双出） |

只读查询与分析直读实测：

```bash
.venv/Scripts/rfauto.exe db query "SELECT run_id, model, adapter FROM runs LIMIT 3"
```

```text
run_id  model  adapter
20260925_062950_1a6365e9  wilkinson_power_divider  fake
20260829_191826_da184d1d  wilkinson_power_divider  fake
20260829_191828_25c6b5d5  wilkinson_power_divider  fake
3 行
```

```bash
.venv/Scripts/rfauto.exe db analytics-attach
```

```text
✓ duckdb 1.5.5 attached runs\registry.sqlite as reg
  runs: 1779
  …（各表行数 + 最近 runs 示例查询）
```

联赛面（读榜单、F6 验收语义）已有专文 docs/tutorials/compose_and_league.md；
这里只给最小闭环：`db league-rebuild`（重建，幂等）→ `db league-report
--json`（读前沿，实测返回 ok=true 且 groups 按 template_family×quantity
分组，如 branchline_coupler × s11_db_max_in_band）。

## 9. 下一步

- 点级数据的健康门判读（G11 三态 × 四级因子）：
  docs/tutorials/datasets_and_health_gates.md
- 联赛表怎么读（Pareto 前沿与 F6 验收）：
  docs/tutorials/compose_and_league.md
- 把数据集历史样本注入优化先验：`rfauto warm-start --help`
- MCP 客户端同源工具：list_datasets / query_dataset（152 工具面，
  docs/tutorials/mcp_in_practice.md）

## 附：本文核对清单

| 命令/数字 | 核对方式 | 结果 |
|---|---|---|
| `rfauto lake --help` 十子命令（index/query/pack/verify/restore/sweep/export-parquet/audit-stale/lineage/compact） | 实跑 | 过（旗标逐条对） |
| `rfauto db --help` 八子命令（init/migrate/status/reindex-runs/query/analytics-attach/league-rebuild/league-report） | 实跑 | 过 |
| `rfauto datasets --help` 八子命令 | 实跑 | 过 |
| `lake index` 沙盒（2 假 run + 1 战役目录 → n_rows=3/n_meta_rows=2） | 临时目录实跑后即删 | 过（§2 输出照录，db_path 略） |
| `lake query` 沙盒 2 行 + 本仓 `--template mline` 3 行 + 日期段 0 行 | 实跑 | 过（§3 输出照录） |
| `lake sweep` 四态计数（11223/10/383/6279/2506） | 实跑 | 过（§4.1） |
| `lake audit-stale` 计数（5310/3051/2983/68/2259） | 实跑 --json | 过（§4.2） |
| `lake lineage` 起点 run n_nodes_total=1 | 实跑 | 过（§4.3） |
| `lake pack/verify/restore` 沙盒链（sha256 → ok=3 fail=0 → restored=3/3） | 临时目录实跑后即删 | 过（§5 输出照录，路径略） |
| `datasets materialize --dry-run` 2 run 计划面 | 实跑 | 过（§7） |
| `datasets query/coverage`（120 行，最弱维 w_mm） | 实跑 | 过（§7 输出照录） |
| `db status`（runs: 1779）/`db query` 3 行/`analytics-attach`（duckdb 1.5.5）/`league-report --json` | 实跑 | 过（§8 输出照录） |
| DuckDB 资源缺省（内存 2GB/4 线程）、`vf_summary` 列、compact 互锁与观察窗 | `service/lake_service.py`、`service/lake_compact_service.py` 源码实读 | 过 |
| 敏感面 | 全文 grep：真实 IP/主机名/盘符路径/凭据零命中 | 过 |
