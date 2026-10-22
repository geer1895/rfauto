# 解释：recipe/study/run/seed 生命周期——为什么重跑秒回、什么时候必须换轨迹

> 这是一篇 explanation（解释文）：回答新用户第一周必撞的两个"为什么"——
> 「为什么同一条命令再跑一遍几秒就回来了？」「为什么想看新轨迹必须换
> seed（或 study）？」这背后是四类对象的生命周期与两层缓存的分工。
> 操作面互补：docs/tutorials/first_optimization_loop.md（第一次优化
> 闭环）、docs/tutorials/data_factory.md（数据工厂的 study/seed 纪律）、
> docs/explanation/deterministic-kernel.md（确定性内核）。

## 四个名词各是什么

| 对象 | 本质 | 落盘位置 | 生命周期 |
|---|---|---|---|
| **recipe** | 一份 YAML 声明：模型、参数边界、目标、采样器（`recipes/*.yaml`） | 文件本身 | 静态——你改它才变 |
| **study** | Optuna 的优化容器：一个配方的一段（或几段）优化轨迹 | `runs/.optuna/optuna.db`（SQLite 单库多 study） | 跨 run 持久——断点续跑与缓存 provenance 的身份锚 |
| **run** | 一次执行的目录：产物、快照、meta 身份卡 | `runs/<rid>/`（rid=`yyyymmdd_HHMMSS_<8位hash>`） | 一次执行一份，永不覆写 |
| **seed** | 采样器的随机种子（tune `--seed`，缺省 42） | 不单独落盘——活在 study/trial 记录与采样器里 | 随调用给 |

三个数字给规模感（2026-10-19 本机实测）：仓根 `runs/` 下 1819 个
run 目录；`runs/.optuna/optuna.db` 里 10 个 study；内容寻址缓存
`.rfauto_cache/` 129 个条目。

## study 的名字是内容哈希，不是随便起的

`make_study_name`（`optimization/optimizer.py`）：

```
tune_{sha256(配方内容)[:8]}_{配方文件名}
```

实测本篇的活体引证：`recipes/branchline_tune_light.yaml` 产出的
study 叫 `tune_f61555ce_branchline_tune_light`——`f61555ce` 就是那份
YAML 字节的哈希前缀。**配方内容不变 ⇒ study 名不变**，`create_study(
load_if_exists=True)` 就会续上同一容器（optimizer 里那行日志
「恢复已有 study: N 个已完成 trial」就是它）。反过来你改了配方的一个
字节，study 名就换代——旧轨迹不被污染，新轨迹从零开始。名字里前置
内容哈希，是修过一个"长文件名哈希被截断"的坑之后的做法：旧式
「文件名_哈希尾缀」在长文件名下哈希被截掉，两个不同配方静默共
study，轨迹互串。

**refine（热启动续调）就靠这个锚**：`refine <run_id>` 从那执 run 的
`meta.json` 读出 `study_name` 原键续容器——所以"续调"续的是**同一份
配方内容的同一段轨迹**，而不是"同名配方碰运气"。

## run 的身份卡在最后一刻才写

`runs/<rid>/meta.json` 是 run 的身份卡（run_id/study_name/adapter/
status/git_sha/python_version…，`infra/run_store.py write_meta` 自动
追加 provenance）。它有一个时序特征（#144 教训）：**meta 在执行结束
时才落盘**——跑动中的 run 目录是「有 trials/无 meta」。所以：

- 按 `meta.json` 存在性枚举 run 的工具（UI Run 历史、batch_ops）
  天然看不见在跑的 run——这是设计不是丢失；
- 反过来，想判断「这目录是不是活 run」，"有产物没 meta" 就是答案。

run 目录本身永不覆写：每次执行都生成新 rid（时间戳+随机 hash），
重跑同一配方产生**新的 run 目录 + 复用的 study**——run 是"执行事
件"，study 是"优化轨迹"，两层记账各管各的。

## 两层缓存：秒回从哪来

同配方同 seed 重跑"秒回"，是两层缓存叠加的效果，键语义完全不同：

**第一层：ResultCache（内容寻址，`.rfauto_cache/`）**——回答"这个
仿真点算过没有"。键是 13 个成分的 SHA-256（`infra/result_cache.py`
`CONTENT_KEY_FIELDS`）：模型名、渲染脚本哈希、几何规格、材料、网格
参数、设计参数、setup、导出契约、适配器版本、AEDT 版本、插件版本、
recipe_version、schema_version。任一成分变化必然 miss，且 `why_miss`
会告诉你**哪个成分**变的——「为什么缓存没命中」是可定位的工程问题，
不是玄学。

**第二层：study 复用（Optuna `load_if_exists`）**——回答"这段优化
轨迹从哪续"。与第一层正交：trial 级的 propose→evaluate 循环在
study 里记账，逐点求值结果在 ResultCache 里记账。

### #158：study/seed 明确不进缓存键

这是全文最重要的一条语义：缓存键的 13 个成分里**没有 study、没有
seed**（`KEY_EXCLUDED_SCOPES`，源码头注原文「同几何不同 study 合法
复用同一数值结果（配对实验）」）。为什么——

- 缓存键回答的是"**这个物理点在当前代码态下的数值是多少**"。同一
  几何+同一网格+同一代码版本，无论你从哪条轨迹、用哪个 seed 到达
  它，物理答案只有一个。A/B 配对实验（换 seed、换采样器）到达同一
  点时，复用不是作弊，是**同一事实只算一次**。
- 反方向才危险：如果你的"新轨迹"其实是**新物理模型/新网格**，那
  `rendered_script_hash`/`mesh_params` 等成分已经变了，自然 miss——
  不会误命中旧数值。想造"假新轨迹"（物理没变却想绕过缓存）反而绕
  不过去，除非你升 recipe_version/schema_version（#106 的两版本分列
  就是给这种"我知道语义变了"的显式申报口）。

### 活体引证：同配方同 seed 连跑两次

隔离目录、fake 通道、5 trials、seed=42（2026-10-19 实测）：

| 次 | 行为 | 耗时 | best cost |
|---|---|---|---|
| 第 1 次 | 新建 study `tune_f61555ce_…`，5 trial 全新执行 | 10.1s | 6.8499 |
| 第 2 次 | 「恢复已有： 5 个 trial」续容器，再提 5 个新 trial | 6.7s | **6.8499（逐位一致）** |

第二次的最优参数与第一次逐位相同——同 seed 的采样器提出**相同的
候选序列**（确定性内核下逐点求值也确定），这是特性不是故障：它让
"配对实验"成立——你改一个变量（采样器、约束、起始点），其余全部
钉死，差值才有归因。**想要一条真正不同的轨迹？换 seed**（或换
study-name 隔离面）。数据工厂的批采集同理：同 seed 重跑秒回是合法
缓存，新轨迹换 study/seed（docs/tutorials/data_factory.md 同口径）。

## 什么时候必须换 study/seed（速查）

| 你想做的事 | 动作 |
|---|---|
| 断点续跑/接着上次的轨迹继续优化 | 什么都不用做——同配方再跑 `tune` 自动续 study |
| 热启动续调（以上轮 best 为起点） | `rfauto refine <run_id>`（走 meta 里的 study_name） |
| 配对实验：只改一个变量看效果 | 保持配方不变，换 `--seed`；同物理点缓存合法复用 |
| 全新轨迹（同配方） | 换 `--seed`，或 `tune --study-name <新名>` 显式隔离 |
| 物理模型/网格真变了 | 直接改——内容哈希自动换代 study，缓存键自动 miss；若语义有意变更，升配方 `recipe_version`/插件 `schema_version` 显式申报（#106） |

## 一句话总结

recipe 是声明（改一个字节=换代 study），study 是轨迹（内容哈希锚定、
跨 run 持久、load_if_exists 续跑），run 是执行事件（目录永不覆写、
meta 最后一刻落盘），seed 是轨迹的指纹（同 seed 同轨迹是确定性特性，
配对实验的地基）。缓存键只认"物理点+代码态"，不认轨迹——所以重跑
秒回是**同一事实只算一次**，而新轨迹靠换 seed 获得，不靠祈祷缓存
失效。
