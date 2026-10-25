<!-- PR-10 文档站同步副本：源=docs/tutorials/getting-started.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 入门：30 分钟跑通第一条链路

> 本文每条命令都在开发环境实测过（退出码 0，2026-10-24 复测）。骨架与
> README「快速开始」六步一致：安装 → 体检 → 零 license 冒烟 → 读产物
> → 起 UI → 接真机。每步比 README 多讲两件事：实测输出长什么样、第一
> 次最容易在哪里走岔（岔路处都标了 README 排查表的对应行）。第 3 节
> 综合与交叉核对是 rfauto 特有的即时报表。第 7 节之前全程不需要
> HFSS/ADS license（fake 适配器是离线解析近似）。
> 英文版（English version）：docs/tutorials/getting-started_en.md。

赶时间的话：第 1-2 节装好环境，第 4 节一条命令看到第一份结果。

## 0. 前置

- Python ≥3.10，<3.13（项目按 3.12 开发），`python --version` 核对。
- git（拉源码用）。

## 1. 安装（约 5 分钟）

```bash
git clone https://github.com/geer1895/rfauto && cd rfauto
python -m venv .venv
.venv\Scripts\activate               # Linux/macOS: source .venv/bin/activate
pip install -e ".[ui]"               # 核心 + 浏览器工作台
```

`-e`（editable）装完即用，源码改了立即生效——这个项目本来就值得边读
边跑。`[ui]` 是第 6 节浏览器工作台要用的 starlette/uvicorn；`[dev]`
是测试与 lint 工具链；`[hfss]` 到第 7 节再装。

**你会看到**：`rfauto --help` 打出命令表，按用途分组——`doctor`
（环境探测）、`run/sweep/tune/refine`（仿真与优化）、`syn`（闭式综
合）、`calc`（闭式计算器）、`runs`（产物检视），另有 `models`、
`campaign`、`datasets`、`remote` 等。帮助页头部自带一条新手五步路：
`doctor` → `syn mline` → `calc` → `run … --adapter fake` →
`runs health`——本文就按这个顺序走。

**岔路**：只装核心（`pip install -e .`）时，`rfauto ui` 会报
`ImportError`（缺 starlette/uvicorn）。重装 `pip install -e ".[ui]"`
即可。任何子命令都吃 `--help`：`rfauto syn mline --help` 看综合参数。

## 2. 环境体检（1 分钟）

```bash
rfauto doctor
```

**你会看到**（路径因机器而异）：

```text
┌──────────┬──────┬────────────────────────────────────────────────────────┐
│ 检查项   │ 状态 │ 详情                                                   │
├──────────┼──────┼────────────────────────────────────────────────────────┤
│ Python   │ ok   │ 3.12.14                                                │
├──────────┼──────┼────────────────────────────────────────────────────────┤
│ AEDT     │ ok   │ <AEDT 安装目录>（版本 2025.1，best_effort）            │
├──────────┼──────┼────────────────────────────────────────────────────────┤
│ ADS      │ ok   │ <ADS 安装目录>（版本 2027，verified）                  │
├──────────┼──────┼────────────────────────────────────────────────────────┤
│ 缓存模式 │ ok   │ readwrite                                              │
└──────────┴──────┴────────────────────────────────────────────────────────┘
```

状态列有两档可信度：AEDT 靠安装目录推断版本，标 `best_effort`，不冒
充 verified；ADS 经实测握手才标 `verified`。没装商业工具的机器上，
AEDT/ADS 两行不会是 `ok`，退出码转非 0（这是写给 CI 脚本的契约）——
第 3-6 节不受影响，fake 通道不依赖任何商业软件。

`rfauto doctor --extras` 另出一张表：各可选依赖组装了几个、缺哪个。

**岔路**（README 排查表）：doctor 查不到 license 服务器——探测目标
未配置。设 `RFAUTO_LICENSE_SERVER` 后重跑。

## 3. 秒级出数：综合 + 独立交叉核对（3 分钟）

综合器把目标阻抗变成几何尺寸；计算器目录用另一条独立代码路径复算同
一设计。

```bash
rfauto syn mline 35.35 --freq 2.4
```

**你会看到**：

```text
微带线综合结果 (rogers4350b_h0.508 @ 2.4 GHz)
  目标阻抗: 35.35 Ω
  线宽:     1.8707 mm
  实际阻抗: 35.35 Ω
  εeff:     2.9804（来源 ep_reff，skrf 2.1.0）
  ΔZ0:      0.0000 Ω
  状态:     ok
```

读法：35.35Ω 是 Wilkinson 功分器 70.7/50Ω 家族的分支阻抗。综合器用
Hammerstad-Jensen 闭式 + brentq 反解出线宽，再把线宽**回代**正向模型
得到「实际阻抗」；ΔZ0 是自洽性残差（>0.5Ω 会标 `needs_calibration`
提醒，不静默通过）。层叠缺省 `rogers4350b_h0.508`，εeff 行标注了数字
来源。层叠清单在 `configs/materials.yaml`（带 source/verified_by
出处字段）。

脚本消费走 JSON 面（`rfauto syn mline 50.0 --freq 2.4 --json`）；退
出码仍是唯一成败判据。

再用第二条独立路径交叉核对：

```bash
rfauto calc run microstrip_synthesis -p z0_ohm=50 -p freq_ghz=2.4 -p epsilon_r=3.66 -p h_mm=0.508
```

```text
microstrip_synthesis
  width_mm: 1.1117
  z0_actual_ohm: 50.0
  eps_eff: 2.8579
  status: ok
  lambda_g_mm: 73.891
```

线宽 1.1117 vs 综合 1.1133 mm——两条独立代码路径互差 <0.2%。设计值
有两条路径背书，比任何一条单独说了算都硬。计算器全部清单自描述
（`rfauto calc list`：衰减器/功分器/级联预算等）；标 `[实验]` 的键
默认拒跑，需 `--allow-experimental` 显式放行。

## 4. 第一次仿真：零 license 冒烟（5 分钟）

先校验配方，再看执行计划，然后才真跑：

```bash
rfauto validate recipes/wilkinson_pd_v1.yaml
# → ✓ 配方校验通过

rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake --dry-run
```

dry-run 打印执行计划（JSON）：模型、适配器、每个参数值、目标函数及
其频段——不执行任何仿真。去掉 `--dry-run` 才正式提交：

```bash
rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake
```

**你会看到**（run_id 每次不同；指标确定性复现）：

```text
✓ 仿真完成  run_id: 20261024_133154_a8b244f6
  run 目录: <workspace>\runs\20261024_133154_a8b244f6
  cost: 7.424965102246688
  指标:
    s11_db_max_in_band: -8.0835
    s11_db_min_in_band: -10.2581
    s21_db_mean_in_band: -4.1084
    iso_s23_db_min_in_band: 25.4717
```

指标名带频段后缀（`*_in_band`）：回损、插损、隔离度，都在配方声明的
频段内取值。cost 是优化器要压下去的那一个数——怎么组装由配方的
objectives 定义。

**fake 与真机的差别，这里说清一次**：fake 是闭式解析近似，不是电磁
仿真——数字出自公式，不出自场求解。它的职责是在几秒内把「配方 →
run → 产物 → 指标 → cost」整条链路走通，不占 license。第 7 节把适
配器换成 openEMS/HFSS 后，配方与判据一字不改，数字会动——那个差别
是真物理进场，不是要上报的缺陷。

**岔路**（README 排查表里两行属于这一步）：

- fake 结果与真机差很多——预期行为：fake 只验链路，真物理在
  openEMS/HFSS；
- run 目录里没有 Touchstone——fake 通道只出解析指标，看
  `results/metrics.json`；Touchstone 出自真机通道。

更多入门配方在同目录：`recipes/branchline_coupler_v1.yaml`、
`recipes/patch_antenna_v1.yaml`，另有 `*_tune_light.yaml` 精简版供
快速调参环使用。

## 5. 读 run 产物（5 分钟）

每次 run 落一个 `runs/<run_id>/` 目录：

- `meta.json` ——环境指纹（git sha、numpy/BLAS、pip freeze 哈希），
  复现凭据；
- `recipe.snapshot.yaml` ——本次 run 的配方快照，
  `rfauto replay <run_id>` 按它原样复跑；
- `report.md` 与 `results/` ——指标与图（`figs/`、`metrics.json`）；
  真机 run 另有 Touchstone 文件；
- `manifest.json` ——收官指纹，新鲜度校验拿它对盘上文件。

用自带的健康门读这个 run：

```bash
rfauto runs health 20261024_133154_a8b244f6
```

**你会看到**（节选）：

```text
│ excitation        │ UNKNOWN │ #174 │ S 参数缺失，无法判定…
│ cost_distribution │ UNKNOWN │ #195 │ 有效 trial 数 1 < 5，样本不足以判定…
│ …
  verdict: healthy  ok=True
```

读法：现行 fake 通道只落指标、不落 S 参数产物，所以凡靠证据下结论的
检查项都如实报 UNKNOWN——「证据不足，暂不下结论」。UNKNOWN 既非
PASS 也非 FAIL，run 级汇总仍是 `healthy`。依据列引用的是判据背后的
坑号（#174 激励体积为零、#195 cost 退化为常数）。`verdict` 取
healthy / suspect / unhealthy，退出码与之一致（healthy=0），可直接
进 CI 门禁；`--json` 出原始 JSON。检查项逐条含义、判据范围与两类
FAIL：docs/tutorials/verdict_semantics.md 与
docs/how-to/read-verdict-gates.md。

新鲜度校验——manifest 收官指纹对盘上文件：

```bash
rfauto runs verify 20261024_133154_a8b244f6
# → run 产物新鲜度校验  20261024_133154_a8b244f6  status: fresh
```

**岔路**（README 排查表）：盘上 Touchstone 和 run 记录对不上——旧文
件顶替了新 run。`rfauto runs verify <run_id>` 报 `stale`、退出码 1，
不静默放行。指纹面不止 Touchstone 曲线：`recipe.snapshot.yaml` 配方
快照与 `results/metrics.json`、`report.md` 报告主数据源也在内，任一被
旧文件顶替或丢失都报 `stale`。`rfauto replay <run_id>` 复现前走同一
道校验——源 run 被 `stale` 判定则拒绝重跑（复现的必须是源 run 真实
的配方）；老 run（无 manifest）不受影响，照常复现。

## 6. 起浏览器工作台（2 分钟）

```bash
rfauto ui --port 8643          # 缺省 8642；被旧实例占用时换端口
```

浏览器打开 http://127.0.0.1:8643（仅本机）。

**你会看到**：「Runs」——每次仿真的指标、S 参数曲线与判读结论；
「Gallery」——器件模板库，每张卡点开是白话参数表（这是什么、数字什
么含义、数字从哪来）；「Tune」——第 4 节同款调参环搬进浏览器：适配
器保持 **fake**，点启动，结果卡直接给推荐尺寸；「Tools」——第 3 节
那批闭式计算器，随点随算交叉核对。右上角 **zh/EN** 整站切换。

**岔路**（README 排查表）：页面打不开或 404——8642 被旧实例占着
（旧进程带旧代码）。换 `rfauto ui --port 8643` 起一个；或核对命令行
后清掉旧实例。

## 7. 真物理：openEMS 与 HFSS

```bash
pip install -e ".[hfss]"      # pyaedt；需 AEDT 2025 R1
```

把 `--adapter` 换成 **openEMS**（免费——离线审计 → 真跑 → 读 S 参
数：docs/tutorials/real-simulation.md）或 **HFSS**（需 license；第
2 节那张体检表就是机器就绪与否的答案）。配方与判据不变，换的只是适
配器。

无人值守跑 HFSS 之前，先读
docs/unattended_hfss_automation.md——本仓一年真机踩坑沉淀的操作纪律。
最先咬人的三条：

- `Desktop` 构造参数名是 `version=`/`non_graphical=`/`new_desktop=`，
  不是旧版 `specified_version`；
- 同一 Desktop 只建一个 `Hfss` 实例（第二个实例的设计变量管理器返
  `None`）；
- 一次失败赋值会毒化整个会话（元数据查询返 `None`，gRPC 通道连带损
  坏，`release_desktop` 静默失败）——判毒化即整轮重建，不带毒续跑。

发射前先过体检与闸门：

```bash
rfauto doctor --janitor --min-free-gb 8
```

**你会看到**（节选；锁路径因机器而异）：

```text
进程清点（通道: psutil）：ansysedt 族共 0 个，疑似孤儿 0 个，合计内存 0.00 GB
AEDT 工程锁（扫描根: <workspace>\runs）：共 8 处
  - …\design.aedt.lock（文件，工程伴生=False）
清理姿势：复核上表后加 --janitor-clean 执行（只动疑似孤儿与上列锁）。
内存闸：可用内存 19.14 GB ≥ 阈值 8.00 GB，闸放行
```

进程清点列出残留的 `ansysedt`（带父进程链证据）；工程锁面板扫 AEDT
锁文件；内存闸拿可用内存对阈值。不带 `--janitor-clean` 绝不动手清。
README 排查表对应行：HFSS 连不上/报 license 错——孤儿 `ansysedt` 占
着许可席位——复核清单后 `--janitor-clean`。

同一张排查表里还有三条真机现场纪律：

- **路径要绝对、要 ASCII**。工程/outdir/日志一律绝对路径——相对
  `-outdir` 会让构造期 `Project.Rename` 挂起数分钟再失败；路径里出
  现非 ASCII 字符（如中文）会让 AEDT 写文件失败（STEP/导出）。避不
  开时先落 ASCII 临时目录再拷回。
- **发射前过内存闸**。`rfauto doctor --min-free-gb 8 --enforce` 在
  可用内存低于阈值时非 0 退出——「求解中途被杀、机器卡死」这类故障
  拦在发射前。
- **容器里没有商业工具**。Docker 镜像只含开源核心（fake 通道 + 确定
  性计算面），真机求解要靠宿主机上的工具：

```bash
docker build -t rfauto:local . && docker run --rm rfauto:local
```

构建与镜像边界详见 docs/how-to/container-build-and-ci.md。

## 8. 下一步

核心进阶链四篇（都假设你已走完本文）：

- 想查、读懂并消费物理标定锚（跨引擎系统偏差的「换算基准」）：
  docs/tutorials/anchor-guide.md
- 想跑真电磁求解（openEMS 直连面：离线审计 → 真跑 → 读 S 参数）：
  docs/tutorials/real-simulation.md
- 想把归档判读用今天的判据重放一遍（RECAST 判据重放）：
  docs/tutorials/recast-walkthrough.md
- 想给 rfauto 加适配器/计算器/通道/模板（基类+注册表四条标准路径）：
  docs/tutorials/extending-rfauto.md

全教程地图（中文原文在 docs/tutorials/；带 `*_en.md` 姊妹篇的有英文
版）：

- 优化闭环与战役：first_optimization_loop（第一次优化闭环）、
  campaign-walkthrough（战役推进）、recast-walkthrough（判据重放）、
  uncertainty_and_surrogates（不确定度与代理）
- 真机与对齐：real-simulation（openEMS 真跑）、
  measurement-alignment（实测对齐）、remote_server（远程协同）、
  anchor-guide（锚）、verdict_semantics（判读语义）
- 数据与湖：datasets_and_health_gates（数据集与健康门）、
  data_factory（数据工厂）、data_lake（数据湖）
- 平台与扩展：extending-rfauto（扩展开发）、mcp_in_practice（MCP
  实战）、compose_and_league（组合与评测）、dag_orchestration（DAG
  编排）、ui_workbench_tour（UI 工作台导览）

专题手册（docs/how-to/）：

- 想跑真实 openEMS 冒烟：docs/how-to/run-openems-smoke.md
- 想做链路预算/混频杂散规划：docs/how-to/cascade-budget-and-spur.md
- 想读懂体检门判据：docs/how-to/read-verdict-gates.md
- 架构分层为什么这样设计：docs/explanation/layered-architecture.md
- 全部命令与模块的权威出处（单一事实源）：docs/reference.md
