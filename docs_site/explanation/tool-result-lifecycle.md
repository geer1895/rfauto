<!-- PR-10 文档站同步副本：源=docs/explanation/tool-result-lifecycle.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 解释：tool-result 生命周期——run 产物怎么变成对账摘要，为什么中途不需要 LLM

> 这是一篇 explanation（解释文）：回答收官/审计场景的两个"为什么"——
> 「战役跑完，为什么对账不靠人逐份开 JSON？」「为什么摘要面宁可少报
> 也不猜？」这背后是 run 结束**之后**的产物链：判定档案（verdict）→
> 确定性提取层 → 确定性渲染层。启动侧（recipe→study→run→缓存）见
> docs/explanation/recipe-study-run-lifecycle.md；采信制度（锚+判据）
> 见 docs/explanation/anchor-and-verdict.md。操作面互补：
> docs/how-to/read-verdict-gates.md（读单 run 门结果）。

## 1. 问题：判定档案是"各战役自研 schema"的

一次 run（或一整个战役）结束后，`runs/` 树里沉淀下来的不只是曲线和
指标，还有**判定档案** `verdict.json`——它记录着"这批数据过没过门"。
但它不是统一 schema：2026-10-19 实测仓内 **220 份** verdict.json，
形态至少分三族——

| 族 | 形态 | 典型出处 |
|---|---|---|
| 架构批 / 架构批 族 | 平铺 dict：`status` + `g1_render`/`g5_health` 等门键 + 数值标量 | 引擎仲裁/多保真战役 |
| k2 / 五点族 | `points` / `attempts` 嵌套数组 | 逐点校准战役 |
| designs_verify 族 | `arms.checks` 嵌套（逐臂门清单） | 设计验证批 |

三族并存是**演化的自然结果**——每个战役的判据面不同，门键名也不同
（`g3_finite` vs `checks_pass` vs `exec_rc`）。统一它们意味着重写历史
档案（证据零改写纪律，见 #325），所以**档案保持原样，摘要面做适配**
——这就是 W8-S4 三件摘要出口的由来。

## 2. 设计：提取层与渲染层分离，两层都是确定性函数

对账链是两段式，每段一个单源模块（规则 4「服务层 JSON 进出」+
铁律 7「数值只在确定性内核」的直接落地）：

```
verdict.json ──提取层──> 结构化 dict ──渲染层──> 人读表格
              (零臆测)                 (零新数值)
```

- **提取层**：`service/verdict_summary_service.verdict_summary()` /
  `service/batch_ops_service.compare_runs_batch()`——从档案原文提取
  总判定、门清单、关键指标，所有数字**原文透传**（浮点仅 `.6g`
  显示格式化，不改值）；
- **渲染层**：同模块的 `*_md()` 函数——**同一提取层的确定性渲染**，
  不重新读文件、不重复解析。你在 `--format md` 表格里看到的每个数，
  都能对回 JSON 信封里的同一个键。

为什么不让 LLM 来读档案做对账？因为对账结论会被写进收官报告——
**写入报告的数字必须有出处链**。LLM 读 220 份异构 JSON 会产生"看着
合理"的摘要，但没人能审计它有没有把 `suspect` 读成 `healthy`。确定性
提取层相反：宁可输出空字段，也不猜（下节）。

## 3. 门识别口径：宁漏不猜

判定档案没有统一的"门列表"字段，提取层用**键名形态规则**识别门
（`verdict_summary_service` 模块 docstring 为权威全文）：

| 形态 | 判定 | 例子 |
|---|---|---|
| bool 值 + 键名命中门形态（`g<数字>*` 前缀 / `gate`·`check` 词根 / `_ok`·`_success`·`_pass` 后缀） | 布尔门，pass=值本身 | `g5_health`、`nrts_converged_ok` |
| dict 值含布尔 `ok` 键 | 复合门，pass=该 ok | `g5_health`/`cleanup` 惯例 |
| dict 值键名自身命中门形态且无 `ok` 键 | 直属布尔叶全收为门 | `checks` 容器（c1_flag_accepted 族） |
| int 值恰 `rc` / `*_rc` | 退出码门，pass=rc==0 | `exec_rc` |

这条口径的设计取向是**宁漏不猜**：形态不像门的键不硬解释成门，于是
摘要可能**少列**一两个非典型命名的门——但列出来的每个门都是档案
原文的忠实转写。对账场景里，"少报需人工补看"的成本远低于"错报假绿"
的成本（与 G11 体检 UNKNOWN 的语义同源，见
docs/how-to/read-verdict-gates.md 第 1 节）。

## 4. 三条消费链（命令全部实测）

### 4.1 单 run 判定档案 → 人读摘要

```bash
rfauto verdict-summary <run_id> --format md
```

实测（2026-10-19，`coax_ph3_hfss`）：输出总判定、`门通过 5/7（fail 2）`
与逐门表格（`judge.hfss_template_gates.band_min_le_-10` FAIL …）、
关键指标表（`judge.delta.s11_f0_db` 0.518143 …）。`--format json` 出
同源结构化信封，供脚本消费。

### 4.2 多 run 收官对账表

```bash
rfauto runs compare-batch <run_id>… --format md
```

逐 run 并排：判定（verdict.json `status` 优先，回落 `meta.status`）+
耗时 + cost + 数值指标 top-K 极差排行。**缺产物的 run 降级 missing 行
不传染**——实测两个纯 verdict 档案 run 得到「仅 0 个 run 有数值指标」
的如实注记，而不是报错或编造空表。

### 4.3 数据集画像（物化产物的描述统计）

```bash
rfauto datasets profile <数据集名>
```

实测（`datafactory_g2_cpw_20260922`）：120 行 × 12 列 / 逐参数范围 /
逐指标分布与 >3σ 异常值 / 健康门 `healthy 120/120（100.0%）`。门通过
率的**唯一事实源是物化时落盘的 manifest**（`dataset_manifest.yaml` 的
`health_verdicts` 映射）——画像面只读不重跑健康门，不触发求解。

三条链共同的边界：**只读零写入**。对账是消费行为，不能再往证据区
写东西——这也是它们与"重放判据"（recast）的分工边界。

## 5. 和相邻面的分工

| 面 | 回答的问题 | 文档 |
|---|---|---|
| 健康体检（G11） | 这**一次 run** 的数据可信吗（逐因子 PASS/WARN/FAIL/UNKNOWN） | how-to/read-verdict-gates.md |
| 锚 + 判据 | 偏差知识与采信规则为什么要制度化 | explanation/anchor-and-verdict.md |
| **本文（摘要面）** | 战役收官时怎么把**一批**判定档案变成对账结论 | 本文 |
| recast 判据重放 | 用今天的判据重判历史数据 | tutorials/recast-walkthrough.md |

记一句话：**门判定在求解/物化时发生一次，摘要面永远只是读取与转写**
——你在 verdict-summary 里看到的 FAIL 不是它新算出来的，是档案里
本来就有的；它做的只是让 220 份异构档案在人读层面重新变得可对账。
