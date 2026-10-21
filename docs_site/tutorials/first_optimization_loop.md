<!-- PR-10 文档站同步副本：源=docs/tutorials/first_optimization_loop.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 第一次优化闭环：syn → run → tune → refine → replay

> docs/tutorials/getting-started.md 的直接续篇——入门教程止步于「跑一次
> fake 仿真、看一次体检」，本文把剩下的一半补上：**调参（tune）→ 热启动
> 续调（refine）→ 复现（replay）** 的最小闭环。全程 fake 适配器（秒级解析
> 近似，零 license），约 10 个 trial 的量级。
> 英文版（English version）：docs/tutorials/first_optimization_loop_en.md。
>
> 诚信口径：本文每条命令的旗标都经 `--help` 逐项核对；两条瞬时命令
> （`syn wilkinson` 综合、`validate` 校验）为实跑记录；**run/tune/refine/
> replay 的执行输出留给读者自己跑**——数字因机器与代码版本而异，本文只
> 教读法，不贴虚构输出。
> **勘误注记（2026-10-19 复测）**：§4 tune 的执行路径在当前 HEAD 实测
> 失败（CLI 以 `recipe=` 关键字调 `service/api.py::start_tune`，而形参
> 名为 `recipe_path`，TypeError 退出码 1）；`--dry-run` 与本文其余命令
> 全部通过，MCP 侧 `start_tune`（走 `start_tune_async` 位置传参）不受
> 影响。修复为 workflow.py 一行形参名改动，落地前 tune 执行面请走
> --dry-run/MCP 通道。

## 0. 你将完成

1. 用闭式综合器拿到 Wilkinson 功分器初值（认识「数值从哪来」）；
2. 认识配方三要素（参数/目标/优化范围）并校验；
3. 冒烟：单次 run（fake）；
4. 第一次小战役：tune 10 个 trial；
5. 看结果：CLI 汇总 + UI 看板两个视角；
6. refine 热启动续调，理解 study/seed 的「同轨迹 vs 新轨迹」语义；
7. replay 一键复现任一次 run。

前置：已装好环境（getting-started §1），工作目录在仓库根（recipes/、
runs/ 都在这里）。

## 1. 综合初值：rfauto syn wilkinson

优化的起点是一个说得过去的初值。`syn` 子命令是闭式综合器
（Hammerstad-Jensen 模型 + 数值反解，毫秒级、零仿真）：

```bash
rfauto syn wilkinson --f0 2.4 --z0 50
```

实测输出：

```
Wilkinson 综合结果 (f0=2.4GHz, Z0=50.0ohm)
  arm_len:   18.92 mm
  series_w:  0.603 mm
  shunt_w:   1.113 mm
  lambda/4 = 18.92mm @ 2.4GHz (εeff@w_series=2.7248，w=0.603mm，εeff 来源
ep_reff)
  70.7ohm series arm = 0.603mm
  50ohm shunt feeder = 1.113mm
```

读法：臂长=λ/4（介质内），series 臂走 70.7Ω、shunt 馈线走 50Ω。加
`--json` 可出机器可读版。可用的综合器看 `rfauto syn --help`（mline /
wilkinson / branchline / patch / bpf 五个）。

## 2. 配方：优化的完整定义

仓里自带一份 Wilkinson 配方 `recipes/wilkinson_pd_v1.yaml`（`ls recipes/`
可见，还有 branchline/patch 各两份）。关键三段：

```yaml
objectives:            # 什么算"好"——优化器按它打分
  - {metric: s11_db, band: [2.3, 2.5], op: max_below, value: -15}
  - {metric: s21_db, band: [2.3, 2.5], op: mean_within, value: [-3.6, -3.1]}
  - {metric: iso_s23_db, band: [2.3, 2.5], op: min_above, value: 20}
optimization:          # 调参时允许搜索的区间（bounds）
  params:
    arm_len_mm:  {low: 18.0, high: 23.0}
    series_w_mm: {low: 0.25, high: 0.45}
    shunt_w_mm:  {low: 0.90, high: 1.30}
limits: {max_trials: 60, max_wall_hours: 12}
```

（节选自真实文件，完整内容直接打开看。）注意：§1 综合给的是闭式初值；
配方里的名义参数与搜索范围是独立维护的，**以配方文件为准**。

先校验（不执行仿真）：

```bash
rfauto validate recipes/wilkinson_pd_v1.yaml
```

实测输出（退出码 0）：

```
✓ 配方校验通过
```

## 3. 冒烟：单次 run

优化前先确认配方端到端能跑通：

```bash
rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake
```

fake 适配器是秒级解析近似，零 license。完成时会打印：`✓ 仿真完成` +
run_id、run 目录、cost 与逐项指标（具体数字每次跑都不同，以你的终端为
准）。run 目录落在 `runs/<run_id>/`（含 meta.json、指标与产物）。

`rfauto run --help` 实测旗标：`--adapter/-a`（缺省 fake）、`--detach/-d`
（后台化，返回 job_id 用 `rfauto jobs status <job_id>` 轮询）、`--dry-run`
（只验证不执行，打印执行计划）、`--json`（成功+失败同构的信封输出）。

顺便做一次健康体检（G11 门，healthy 退出码 0）：

```bash
rfauto runs health <run_id>
```

判据细节见 `rfauto runs health --help` 与 docs/how-to/read-verdict-gates.md。

## 4. 第一次小战役：tune

```bash
rfauto tune recipes/wilkinson_pd_v1.yaml \
  --adapter fake --max-trials 10 --seed 42 --study-name first-loop-demo
```

fake 通道 10 个 trial 通常秒级到数十秒。旗标逐条核对过（`rfauto tune
--help`）：

| 旗标 | 缺省 | 说明 |
|---|---|---|
| `--adapter/-a` | fake | 仿真通道 |
| `--max-trials` | 60 | 最大试验数 |
| `--seed` | 42（optimizer.SAMPLER_SEED） | 采样器随机种子 |
| `--study-name` | 由配方路径+内容哈希自动生成 | Optuna study 名 |
| `--sampler` | tpe | 单目标采样器：tpe / cmaes / sbo |
| `--watch/-w` | 关 | 逐 trial 播报（trial#/cost/Δ，单目标路径） |
| `--detach/-d` | 关 | 后台执行返回 job_id（单目标路径） |
| `--multi` / `--fidelity auto` / `--pruner` | 关/single/none | 多目标 NSGA-II / 多保真 / 裁剪器，本文用不到 |

**输出读法**（字段名按 CLI 实现归纳，数字以你的实际输出为准）：
`✓ 优化完成` 后依次是 `study_name` / `run_id` / `总试验` / `完成` /
`剪枝`（多保真才有）/ `耗时` / `best cost` / `best params` / `best metrics`。
**best_params 就是当前推荐工作点**——三个几何参数在搜索区间里的一组取值。

cost 是什么：优化器按配方 objectives 确定性算出的标量罚分，越低越好；
违约越多 cost 越高。它是优化器唯一看得见的裁判，物理判读仍看 best metrics
各分项。

想看逐 trial 播报，加 `--watch` 重跑（新 study 名，见 §6 的轨迹语义），
终端会出一张 Live 表：每行一个 trial 的 cost 与 Δ（=cost−上轮 best，负值
=改进），底部常驻当前 best。

## 5. 看结果：CLI 与 UI 两个视角

**CLI 侧**：

```bash
rfauto runs stats          # runs 总览：总数、按 model/adapter/status 分组、最近 10 条
rfauto runs health <run_id>        # 单 run 体检
rfauto runs compare <run_id_1> <run_id_2>   # A/B 对比：指标 Δ 与 cost
```

（三条均过 `--help` 核对：compare 恰好 2 个 run_id 走经典 A/B，N>2 走
N-way 矩阵，`--provenance` 附实验复现块。）

**UI 侧**（启动见 ui_workbench_tour 教程）：

- **优化调参**页（`#/tune`）：表单里填同一配方，选 fake、trials=10 点
  「启动」；下方 Trial 实时监控每 3 秒刷新，收敛曲线=cost 随 trial 下降的
  best-so-far 阶梯线。
- **战役仪表盘**页（`#/campaign`）：带 trials 审计的调参 run 会出现在
  Run 下拉里——座位状态表（PASS/SKIP/FAIL 三分）+ 两参数成本热图（格色=
  平均 cost，格内数字=样本数）+ trial 虚拟列表。
- **优化洞察**页（`#/optstack`）：Pareto 前沿散点与参数平面热图；多目标
  run 直读逐代超体积收敛。
- **总览**页（`#/dashboard`）的 S11 趋势组件：每个点=一次 run 的带内
  S11 最大值按时间排布（趋势向低=在变好；注意它是点趋势，不是频域曲线）。

## 6. refine：热启动续调

上一轮 best 通常还没榨干——让 TPE 站在已有成果上继续采样：

```bash
rfauto refine <tune输出的run_id> recipes/wilkinson_pd_v1.yaml --max-trials 30
```

语义（`rfauto refine --help` 原文口径）：**沿用上一轮的 study_name +
SQLite storage（runs/.optuna/optuna.db），Optuna 自动加载已有 trial，从
已有结果继续采样**。输出里会多一行 `恢复已有: N 个 trial`——这就是热启动
生效的证据；`--max-trials` 是**本次新增**的试验数（缺省 30）。

**study/seed 的轨迹语义**（这个坑值得先讲清楚）：

- 不传 `--study-name` 时，study 名由「配方路径+内容哈希」确定性生成——
  同一份配方反复 tune，**天然续在同一 study 里**（增量，不是重跑）。
- 想要一条**全新轨迹**（对照实验、换采样器起跑）：显式换 `--study-name`
  或换 `--seed`。study 复用+缓存让同种子重跑秒回——配对实验合法；但拿
  「同 study 续跑」当「独立重复实验」是错的。

## 7. replay：一键复现任一次 run

```bash
rfauto replay <run_id>
```

它用该 run 目录里的配方快照（`runs/<run_id>/recipe.snapshot.yaml`）重跑
一次，并自动核对版本一致性（`rfauto replay --help` 原文：核对 plugin/
schema 版本）。输出包含：

- `source_run_id` / `replay_run_id`——源 run 与复现产生的新 run（新 run
  目录、新快照，不覆盖历史）；
- `version_warnings`——schema 版本、git HEAD 与记录时不一致时的**警告**
  （如实提示「复现结果可能有差异」，不静默、不阻断）；
- 快照里的模型当前未注册时会显式报错。

复现对不上时的第一排查项就是这三类：配方内容变了没、代码/插件版本变了
没、分支对不对。

## 8. 闭环之后

- 把 best_params 应用回配方（UI 配方编辑页改值保存，或手改 YAML），换
  openEMS/HFSS 真跑验证：docs/tutorials/real-simulation.md
- 想推进多阶段战役（校准→粗筛→调参→公差→报告）：fake 先行口径同样适用，
  见 docs/tutorials/campaign-walkthrough.md
- 指标/门禁判据怎么读：docs/how-to/read-verdict-gates.md
- 回 UI 总览（`#/dashboard`）看 S11 趋势线是否整体下移——那就是你这几轮
  闭环的成果。

## 附：本文命令核对清单

| 命令 | 核对方式 | 结果 |
|---|---|---|
| `rfauto --help` | 实跑 | 过（命令树含 run/tune/refine/replay/validate/syn/runs 等） |
| `rfauto syn --help` / `rfauto syn wilkinson --help` | 实跑 | 过 |
| `rfauto syn wilkinson --f0 2.4 --z0 50` | 实跑 | 过（输出已贴，闭式瞬时） |
| `rfauto validate recipes/wilkinson_pd_v1.yaml` | 实跑 | 过（✓ 配方校验通过，退出码 0） |
| `rfauto run --help` | 实跑 | 过（--adapter/--detach/--dry-run/--json） |
| `rfauto tune --help` | 实跑 | 过（§4 旗标表逐项对） |
| `rfauto refine --help` | 实跑 | 过（--max-trials/--adapter/--json） |
| `rfauto replay --help` | 实跑 | 过 |
| `rfauto runs stats/health/compare --help` | 实跑 | 过 |
| `rfauto jobs status`（--detach 轮询用） | `rfauto jobs --help` 实跑 | 过 |
