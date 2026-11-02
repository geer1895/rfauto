<!-- PR-10 文档站同步副本：源=docs/tutorials/design_report.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 设计回放报告：从一次 run 出一份带出处的设计总结

> 设计做完之后，"交出去"的东西不该是一堆 JSON，而是一份**能回答三个问题**
> 的报告：**要什么**（目标与配方）、**走了什么路**（优化轨迹）、**得到
> 什么**（最终设计与门判读）。`rfauto design-report` 把这三个问题收成一份
> 六节 md 单文件——每个数字都带来源标注，零 LLM 零网络（确定性模板，同
> 输入逐字节同输出）。本文命令与输出均在开发环境实测（示例 run 为仓内
> 真实湖 run：fake 通道 Wilkinson 功分器 10-trial 调参，run_id
> `20260830_213813_1510dee6`）；`生成时间` 是报告全文唯一不参与逐字节复
> 现的行，其余摘录可逐字节复跑。前置：`docs/tutorials/first_optimization_loop.md`
> （需要一个已完成的优化 run）。
> 英文版（English version）：`docs/tutorials/design_report_en.md`。

## 0. 你将完成

1. 弄清设计报告与既有两种报告的分工（先分清，免得用错入口）；
2. 对一次已完成的 run 生成单文件 md 设计报告（含可选 `.drawio` 电路图附件）；
3. 读懂报告六节：哪些数字来自 run 湖文件、哪些是派生统计、哪些是"如实
   缺失"；
4. 用报告尾部的复现附录把设计重跑/打包。

## 1. 三种报告，先分清分工

| 报告 | 命令 | 适用 run | 回答什么 |
| --- | --- | --- | --- |
| 单次 run 指标报告 | `rfauto report <run_id>` | 单评族（有 `results/metrics.json`） | 这次仿真的指标与曲线图 |
| 四段式仿真报告（PDF+HTML） | `rfauto reports render <run_dir>` | 任意 run 目录（缺产物如实降级） | 标识/方法/判据对照/结论 |
| **设计回放报告（本文）** | `rfauto design-report <run_id>` | **优化族为主**（有 `trials/`）；单评/校准族走降级形态 | 目标 → 轨迹 → 最终设计 → 门表 → 复现 |

为什么要新叶：优化族 run 的 `results/` 目录是空的（指标在 `trials/` 与
`meta.json` 里），`rfauto report` 对它直接报错（实测）：

```text
✗ 报告生成失败
  - 未找到 run 指标: runs\20260830_213813_1510dee6\results\metrics.json（→ run
    目录在但缺 results/metrics.json——…）
```

`design-report` 补的正是这块缺口——它是**增量面**，单评族用户继续用
`rfauto report`，PDF/HTML 双输出继续用 `rfauto reports render`。

## 2. 一次 run 目录里有什么（报告的数据源）

```text
runs/<run_id>/
├─ meta.json               # 谁/何时/哪个模型与通道；优化族还有 study_name 与最优指标
├─ recipe.snapshot.yaml    # 配方快照（名义参数/目标/优化范围/频扫设置）——复现以此为准
├─ trials/trial_N.json     # 每个成功 trial：params / metrics / cost（优化族）
├─ results/                # 单评族：metrics.json + params.sNp + figs/；优化族为空
├─ manifest.json           # run 收官指纹（老 run 没有 → 报告头标 legacy）
├─ calibration/            # 校准族：gate.json / samples.json / surrogate.json / report.md
└─ diagrams/               # （仅当报告生成出附件时新增）电路图附件落点
```

报告对 run 目录**只读**：唯一写面是 `design_report.md` 本身，以及（仅当
run 里有链路级数据时）`diagrams/` 附件。每个数字都能回指到上面某个文件的
某个键，或回指到一条在 REPORT_SPEC 里钉死的派生公式——这是 rfauto 报告面
的 provenance 纪律（全文数字 100% 有出处，模型面 `bare_number_fields`
恒空）。

## 3. 生成报告（旗标以 `--help` 实测为准）

```bash
rfauto design-report 20260830_213813_1510dee6
# 缺省落 runs/20260830_213813_1510dee6/design_report.md

rfauto design-report 20260830_213813_1510dee6 --json
# --json：信封输出（成功+失败同构），脚本与工作流消费

rfauto design-report 20260830_213813_1510dee6 --out out/design_report.md
# --out：报告落点另指（默认 run 目录内）；run_id 也可直接传 run 目录路径

rfauto design-report 20260830_213813_1510dee6 --no-diagrams
# --no-diagrams：禁用 §④ 图产物落盘
```

`--help` 实测旗标就这四个：`run_id`（位置参数，runs/ 下目录名或 run 目录
路径）、`--out`、`--no-diagrams`、`--json`。

人读输出（实测摘录）：

```text
设计回放报告  run=20260830_213813_1510dee6  design_verdict=FAIL  门 PASS 0/FAIL 2  freshness=legacy
✓ 已写出 runs\aurora_o\report_spec\tmp_cmd_design_report.md
```

`--json` 成功信封（实测，键清单完整）：

```json
{
  "ok": true,
  "run_id": "20260830_213813_1510dee6",
  "schema": "rfauto-design-report/v1",
  "report": "runs\\aurora_o\\report_spec\\tmp_cmd_design_report.md",
  "diagrams": {"status": "missing", "attachments": []},
  "design_verdict": "FAIL",
  "n_gates_pass": 0,
  "n_gates_fail": 2,
  "freshness": {
    "status": "legacy",
    "note": "run 无 manifest.json（老 run/未接线链路）：无指纹可比，新鲜度校验不适用，按 legacy 放行"
  }
}
```

### 3.1 新鲜度三态（生成前先过 freshness gate）

生成报告前会先做**新鲜度校验**（`rfauto runs verify` 同款语义），三态：

| 状态 | 判据 | 报告行为 |
| --- | --- | --- |
| `fresh` | 有 manifest.json 且盘上产物与收官指纹一致 | 正常出报告 |
| `legacy` | 老 run 无 manifest.json（无指纹可比） | **照出**，报告头多一行注记 |
| `stale` | 任一记录在案的产物 sha 不符/丢失/快照被顶替 | **拒绝出报告**，错误信封 `stage="freshness_gate"` |

stale 不是报告坏了，是**数据不可信**（交付错配风险）。实测把一次校准 run
副本的 `recipe.snapshot.yaml` 追加一行再出报告，信封如实红：

```json
{
  "ok": false,
  "errors": [
    "snapshot_replaced: recipe.snapshot.yaml（盘上 recipe 快照与 manifest 记录不符（旧快照顶替/内容被改））"
  ],
  "stage": "freshness_gate",
  "status": "stale"
}
```

处置：先 `rfauto runs verify <run_id>` 查哪里变了——确认文件来源后补拷正
确文件或重跑该 run，再复检。另一个显式负例：run 不存在 → 信封
`stage="resolve_run_dir"` 并附排查 `hints`（`ls runs/`、`rfauto runs watch`
等），不静默。

## 4. 读报告：六节各看什么

报告开头四行：run 目录（相对形态 `runs/<run_id>`，绝对路径只在模型面，
**外发报告不含本机绝对路径**）、生成时间（**唯一**不参与逐字节复现的
行）、freshness、汇总判定 `design_verdict`。然后是六节（以下摘录均实测，
示例 run 为 fake 通道 Wilkinson 功分器 10-trial）：

### ① 设计目标与配方摘要

三张表：基本信息（model/adapter/study/status/git）、名义参数与优化范围、
设计目标。**看点**：哪些参数在优化（有上下界），哪些是固定值；目标的 op
语义（`max_below`=带内最大值压上限，`mean_within`=带内均值落区间）：

```text
| 1 | s11_db | max_below   | ≤ -15             | 2.3–2.5 |
| 2 | s21_db | mean_within | 落在 [-3.6, -3.1] | 2.3–2.5 |
```

### ② 优化轨迹回放

trial 序表（params/cost=trials/trial_N.json）+ best-so-far 列 + 关键改进
事件表 + 两个汇总量。**看点**：

- **改进事件**=best-so-far 下降的 trial（示例：trial 1 与 trial 6 两次），
  这就是"关键决策点"；轨迹表里改进轮带 `↓` 标记；
- `auc_norm`（∈(0,1]，1=零改进，越小=收敛越快）、`conv_ratio`（全程相对
  改进）是**记账统计**——报告明写"不外推『已收敛/未收敛』结论（判定以
  §③ 门表为准）"；
- 诚实注记：trial 文件=成功 trial 全集，被剪枝/失败的 trial 不落文件，
  报告不虚报总数；重复参数向量单独计数。
- 校准/单评族 run 没有 `trials/` → 本节如实 `missing` 并降级为结果指标
  表（`results/metrics.json`），不硬凑轨迹。

### ③ 最终设计与 verdict 门表

最终设计=trial 文件中 cost 最小者（有约束时=可行最优），并与
`meta.json:metrics` 交叉核对（示例 run：trial 6，cost 3.88424）。门表逐
目标给观测/违约量/判定，并**自证一致性**（violation 之和 == cost）：

```text
| 1 | s11_db | ≤ -15 | -11.3322 | 3.66775 | **FAIL** |
| 2 | s21_db | [-3.6, -3.1] | -3.81648 | 0.216483 | **FAIL** |

汇总：**design_verdict = FAIL**（PASS 0 / FAIL 2 / UNKNOWN 0；有 FAIL 行即
FAIL，无 FAIL 有 UNKNOWN 即 UNKNOWN，不凑绿）。
```

**看点**：示例两目标均 FAIL（S11 只到 −11.3 dB，目标 −15 dB）——报告
如实 FAIL，不凑绿；这类结果正是该回去改配方/换通道的信号。缺指标键的
目标记 UNKNOWN，不凑 PASS。若 run 有 verdict.json（战役 run）会原样嵌入
其判读摘要；failed run 会附失败指纹候选族（explain_run）；三者都没有时
"其他判读面"逐条如实陈列，不虚构。

### ④ 电路图总结（.drawio 附件，T-O9 相对链接形态）

有链路级数据的 run 会自动出 `.drawio` 附件（原生可编辑，图内数字来自确
定性内核）：报告生成时在 run 湖内识别链路级级表——`chain.json`/
`link_chain.json`，或任一顶层 `*.json` 的 `chain` 键（级三键
`name`/`gain_db`/`nf_db`）——命中即调 `diagram_service.generate_link_diagram`
落 `runs/<run_id>/diagrams/link_summary.drawio`，正文以**相对链接**引用：

```text
- 附件：[diagrams/link_summary.drawio](diagrams/link_summary.drawio)（exists=true，generator=diagram_service.generate_link_diagram）
```

**round-trip 契约**：从报告文件所在目录解析链接即达附件。相对链接按报告
实际落点计算——缺省落 run 目录内即上式；`--out` 外置时自动带 `..` 段
（实测 `--out runs/aurora_o/report_spec/tmp_ext2/deep/report.md` 时链接为
`../../tmp_chain_run/diagrams/link_summary.drawio`）。同 run 再生成附件
逐字节一致（确定性）。另有 ADS 前仿反标注图扫描：run 目录顶层的
`<族>_circuit.drawio`（ads-circuit run 产物）在场时同样以相对链接列出。
四叶电路图与 ADS 前仿回路的完整教程见
`docs/tutorials/circuit_diagrams_and_reports.md`，本文不重复。

**missing 降级（诚实说明）**：普通优化族 run 多数没有链路级数据——本节
如实标 `missing（如实降级）`，**不猜链、不造数字**，并给出手工出图入口
（实测摘录）：

```text
**状态：missing（如实降级）**——run 湖内无链路级级表数据（…级三键
name/gain_db/nf_db）——不猜 chain、不造数字。手工出图入口：
rfauto diagram link --chain @chain.json --out runs/<run_id>/diagrams/link_summary.drawio --json
```

`--no-diagrams` 时本节标 `skipped`（连只读扫描一并禁用）。

### ⑤ 敏感性 / trade-off 摘要

优化族：各参数在 trial 内的跨度 min–max + 参数-cost Pearson r，**附 n 与
低样本警示**——n<12 时强制标"低样本探索性统计，非物理敏感性结论"，且
r 只陈列不解释（n 与混杂未控，不写"主控因素"类断言）。校准族：代理可信
度摘要（LOOCV ρ/阈值/验证点偏差，只读嵌入 `calibration/gate.json` 不重算）。

### ⑥ 复现命令附录

五条命令带用途与来源注记：`rfauto replay`（快照重跑+版本核对）、
`rfauto repro export`（复现包一键 `reproduce.py`）、`rfauto runs verify`
（收官指纹复核）、本报告再生成（自引）、`rfauto reports render`（单评族
可用）。**复现以 run 内 `recipe.snapshot.yaml` 为准，非 `recipes/` 原件**；
环境指纹表（git_sha/package_version/schema_version 等）老 run 缺的键如实
标"无"。

报告尾部还有一节"异常与注记汇总（anomalies）"——生成过程识别到的降级/
异常逐条列在这里，无异常写"（无异常注记）"。

## 5. 复现与打包（HEAD 既有命令）

```bash
rfauto replay 20260830_213813_1510dee6        # 快照重跑 + 版本核对
rfauto repro export 20260830_213813_1510dee6  # runs/repro/<id>_repro/（reproduce.py 一键）
rfauto runs verify 20260830_213813_1510dee6   # 新鲜度三态
rfauto reports render runs/20260830_213813_1510dee6   # 四段式 PDF+HTML（单评族）
```

## 6. 常见疑问

- **报告里的数字和 UI 看板不一样？** 先看来源列：报告只读 run 湖文件；
  UI 可能读 optuna storage（含剪枝 trial）。两边口径不同不是错。
- **为什么 §④ 没有电路图？** 该 run 没有链路级级表数据——missing 是诚实
  降级不是故障；按 §④ 给的 `rfauto diagram link --chain @chain.json …`
  手工出图，或跑一次会产 chain 数据的链路级 run。
- **能改报告里的判定吗？** 不能——判定来自配方目标与 cost 语义单源；要
  改结论就改配方重跑（不凑绿）。想改呈现细节也没有入口：报告是确定性
  模板渲染，同输入逐字节同输出。
- **stale 了又急着要报告？** 先查 `rfauto runs verify`：是漏拷文件就补拷
  正确文件复检；是产物真被顶替就重跑 run。报告宁可拒绝出，也不给不可信
  的数据背书。

## 7. 下一步

- `docs/tutorials/first_optimization_loop.md`：refine 热启动续调后再出一份
  报告，对比两次最终设计；
- `docs/tutorials/circuit_diagrams_and_reports.md`：电路图四叶与 ADS 前仿
  回路（§④ 附件的完整上游）；
- `docs/tutorials/verdict_semantics.md`：PASS/FAIL/UNKNOWN 口径全解。
