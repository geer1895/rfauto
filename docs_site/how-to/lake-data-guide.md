<!-- PR-10 文档站同步副本：源=docs/how-to/lake-data-guide.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 如何消费数据湖与数据集（datasets / lake / compact 三面指南）

**场景**：你跑完一批战役/run，想"这批数据有多少点、按模板/study 筛、
物化成数据集做 SQL 查询"；或者 runs/ 目录膨胀要归档/压实；或者想从
一个数据集反查它上游是哪些 run、哪个渲染 commit 产出的。三个服务面
分工：`dataset_service` 管**点级数据 → Parquet 数据集**，
`lake_service` 管 **runs/ 全量 DuckDB 索引与归档**，
`lake_compact_service` 管**语义压缩（gc 规划与执行）**。数据湖总览
见 docs/tutorials/data_lake.md——本文是操作手册。

## 1. 数据集面：物化 + 查询（`rfauto datasets`）

```bash
# runs/ 点级数据（trials/samples/best 点）物化为 Parquet 数据集
# （指纹去重：同 (study, seed, params) 跨 run 只留一份；manifest 落盘；
#   缺省=全部有 meta 的 run；--dry-run 先看将物化清单）
rfauto datasets materialize --name my_batch --json

# DuckDB 直查（谓词下推/列裁剪；where 经白名单校验后才拼接）
rfauto datasets query my_batch \
    --where "cost < 0.1" --columns params,cost --limit 50 --json

# 一键画像（点数分布/参数空间占用/离群点）
rfauto datasets profile my_batch --json

# 覆盖度、GT 标注（白名单通道，threshold=族级解锁门槛）、
# 公开/私有切换（public 是 HF 导出放行前提）、HF 导出
rfauto datasets coverage my_batch --json
rfauto datasets annotate my_batch --json
rfauto datasets visibility my_batch public --json
rfauto datasets export-hf my_batch --json
```

import 等价面（service 层单源）：

```python
from rfauto.service.dataset_service import (
    materialize_dataset, query_dataset, dataset_profile)

materialize_dataset(name="my_batch")                    # 缺省 runs/datasets
query_dataset("my_batch", where="cost < 0.1", limit=50)
dataset_profile("my_batch")
```

真机工作目录形态的漏数口（无 meta.json 的产物目录）：
`rfauto datasets discover-workdir` 只读发现 → `import-workdir` 导入
（键路径优先级 `params > calib_params > design_params`，导入行
`study_name` 回填工作目录名防跨战役折叠）。

## 2. 湖索引面：全量入索引 + 归档链（`rfauto lake`）

```bash
# runs/ 两层目录（一级战役+二级 run 点）全量入 DuckDB 索引
# （缺省库 runs/.lake_index.duckdb；缺失字段如实 NULL 不臆造）
rfauto lake index --json

# 只读查询：等值过滤+日期段；值只进 ? 绑定，永不拼进 SQL
rfauto lake query --template mline --date-from 2026-10-01 --limit 100 --json

# 半产物清点（complete/incomplete/empty/unannotated 四类，零改写）
rfauto lake sweep --json

# 将失效 run 清单（代码/参数/引擎/环境/预算五类原因；0 无失效/1 有/2 错）
rfauto lake audit-stale --json

# 血缘三跳：数据集 → 上游 run → 渲染 commit（--down 反查影响面）
rfauto lake lineage --run <run_id> --hops 3

# 归档链：打包（tar.zst+偏移清单）→ 逐文件校验 → 恢复到新目录
rfauto lake pack runs/<战役> --json          # 原目录零改动，只读打包
rfauto lake verify <pack.tar.zst> <pack.tar.zst>.manifest.json
rfauto lake restore <pack.tar.zst> <pack.tar.zst>.manifest.json <新目录>

# 外部引擎直读的 parquet 冷层（hive 分区）
rfauto lake export-parquet --json
```

import 等价面：`from rfauto.service.lake_service import build_runs_index,
query_runs_index`（签名与 CLI 旗标一一对应）。

## 3. 压实面：dry-run 规划 → 显式放量（`rfauto lake compact`）

```bash
# 缺省 dry-run 纯读：h5 白名单保留三档统计 + et/ht 去重收益预估
rfauto lake compact --runs-root runs --dedup-et-ht --json
```

放量纪律（破坏性动作绝不自动执行）：

1. `--apply` 有**前置互锁**——XD-5 golden 基线未 pin 一律拒绝（先
   `rfauto simci-pin-baseline`）；
2. 缺省 `--reversible`：apply 把删除清单 blob 化进内容寻址存储 +
   manifest 审计（观察窗内可恢复回填，禁裸删），窗满 purge 才物理
   释放；`--exempt-subtree` 用户豁免子树只走可逆路径；
3. 在跑/半途 run（无 meta）任何档位都不可删；meta 落盘不足
   `--min-age-h`（缺省 24h）的 run 一律不动；
4. golden 零改写红线：指针源命中目录（锚证据/simci 基线/golden 判读）
   进保留清单，"删除清单 ∩ 保护面 = ∅" 有审计断言钉死。

## 4. 依赖与落点

- duckdb/zstandard 是可选 extra（`pip install rfauto[dataset]`），
  缺装在索引/压缩路径显式报缺，不阻塞其余路径；
- 数据集缺省落 `runs/datasets/<name>/points.parquet +
  dataset_manifest.yaml`；湖索引缺省 `runs/.lake_index.duckdb`；
- 三面全部遵守"runs/ 既有内容只读"：唯一写点是显式传入的
  db/out/manifest/target 路径，restore 目标已存在即拒——绝不覆盖。

## 5. 高频坑位

- **`n_rows` 是返回行数不是总数**：`query_dataset` 的 `limit` 截断后
  `n_rows` = 截断后行数，拿它当"数据集总行数"会判出全红假 FAIL
  （#369）——总数语义用大 limit 实测一次返回语义，或读 manifest 的
  `n_points/n_rows/n_dup` 统计；
- **在跑 run 没有 meta**：meta 在 run 结束才落盘（#144）——索引/体检
  里"有 trials 无 meta"是在跑或中断的常态，`lake sweep` 把它归
  incomplete 如实清点；判定 run 真伪看 meta 的 adapter/study 字段，
  别拿索引 NULL 行当坏行清；
- **workdir 导入别按文件序猜归属**：多曲线目录共用根级 JSON 时，按
  显式引用（曲线相对该 JSON 目录的路径）或同名 stem 归属，猜错的
  参数会静默张冠李戴（#320/#321）；
- **compact 的 dry-run 报告是规划面不是收益承诺**：三档统计全给但
  实际可删=当前档 ∩ 保护面之外；先看 `golden_rewrite_audit` 有无
  violations，再谈 --apply。
