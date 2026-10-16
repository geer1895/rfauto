<!-- PR-10 文档站同步副本：源=docs/tutorials/recast-walkthrough.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# RECAST 走查：把归档判读重放一遍

> RECAST（判据重放）回答一个问题："当年那个判读，用今天登记的机器
> 判据再算一遍，结论还一样吗？"本文从判据格式讲到动手重放，全部代码
> 实测过。前置：docs/how-to/read-verdict-gates.md（判据与门的基本
> 读法）。CLI 出口已闭合：aurora36 W2-D（2026-10-11）起有 `rfauto
> recast status/replay` 两只读薄壳（MCP 面仍无，见第 5 节）；本文
> 1-4 节讲 Python API 的语义细节，CLI 与 Python 共用同一确定性内核。

## 1. 概念：判据先行 + 归档零改写

rfauto 的判读纪律是**判据先行**：判据在战役跑之前预声明，判读按判据
执行，归档后的判读**永不改写**（与锚面"断锚不改历史"是同一条纪律的
两个面，见 docs/tutorials/anchor-guide.md 第 2 节）。RECAST 不推翻
这条纪律——它只在旁边**新增一份重放报告**：用当前登记的判据源对
归档证据再判一次，新旧结论对照标注。发现结论翻转时，处置是人走仲裁
重跑，不是改归档。

判据机器源是 `knowledge/criteria/v2/` 下的 YAML（criteria/v2 schema），
六个核心块：

| 块 | 作用 |
|---|---|
| `claim` | 判的是什么量（quantity/template/频率点） |
| `evidence_fields` | 从归档证据 JSON 取哪些字段（路径列表） |
| `u_val` | 数值不确定度三分量（u_num/u_input/u_D）——估不出就 unknown，不虚构 |
| `decision_rule` | 机器可执行的判定规则（下一节） |
| `verdict_map` | 判定结果 → V&V 状态映射（PASS→validated，FAIL→not_validated） |
| `provenance` | 判据出处（战役/判据文档/提交） |

同目录通常还有一份 md（人读渲染）与 YAML **双落盘、逐值一致**——md
给人看，YAML 给机器判。两者不一致时以 YAML 为准并修渲染。

## 2. 三种 decision_rule 形态

仓内现行三份 v2 判据恰好覆盖三种规则形态：

| 判据 | form | 语义 |
|---|---|---|
| `df5_c3fix_sentinel.yaml` | `multi_gate_all_pass` | 多门全过才 PASS，任一不过 FAIL |
| `df6_dp10_scan.yaml` | `threshold_gate` | 单阈值门 |
| `hfss_interdigital_check_m1.yaml` | `nearest_reference_gate` | 对最近参考点比对——**非机器直放**（见下） |

第三种要特别注意：`nearest_reference_gate` 依赖参考数据的选取语境，
机器重放器不直接执行它——实测重放返回 `direction: not_judged`，
notes 注明"form 'nearest_reference_gate' 非机器直放"。这不是缺陷
而是口径：**不能机器复算的判据，重放面就不冒充能算**。

## 3. 动手重放一条

对象：df5_c3fix 哨战役的四门判据 + 它的归档判读。

```python
import json
from pathlib import Path
import yaml

from rfauto.core.recast import replay_one

crit = yaml.safe_load(
    Path("knowledge/criteria/v2/df5_c3fix_sentinel.yaml")
    .read_text(encoding="utf-8"))
artifact = json.loads(
    Path("runs/demo/sentinel_verdict.json")
    .read_text(encoding="utf-8"))

result = replay_one(artifact, crit,
                    archived_verdict_path="four_gates.verdict")
# → {'replay_verdict': 'FAIL', 'replay_vv_status': 'not_validated',
#    'archived_verdict': 'FAIL（fail_kind=gates；如实记录）',
#    'direction': 'same'}
```

四门里 span 门（12.44dB < 20dB 阈值）不过——重放判 FAIL，归档当年
也判 FAIL，`direction: 'same'`：判读可复算、结论稳定。

### 关键参数：archived_verdict_path

`replay_one` 的第三个参数指定**归档判读在证据 JSON 里的位置**。缺省
取顶层 `"verdict"` 键，而这份哨档的判读嵌在 `four_gates.verdict`——
不传参会发生什么（实测）：

```python
replay_one(artifact, crit)
# → {'replay_verdict': 'FAIL', 'replay_vv_status': 'not_validated',
#    'archived_verdict': None, 'direction': 'not_judged'}
```

方向变成 `not_judged`（找不到归档侧结论，无法对照），而不是报错。
重放前先看一眼归档 JSON 的顶层键（`json.loads(...).keys()`），判读
不在顶层就显式传路径——这是本页最省时间的一课。

### 批量加载判据的坑

`load_criteria_dir` 返回的是**包装条目**不是判据本体：

```python
from rfauto.core.recast import load_criteria_dir

entries = load_criteria_dir("knowledge/criteria/v2")
# 每条：{path, name, ok, errors, criteria_id, decision_rule_form, criteria}
entries[0]["decision_rule_form"]   # → 'multi_gate_all_pass'
```

判据本体在每条的 `criteria` 键里——把整条包装直接传给 `replay_one`
会得到 form=None 的 `not_judged`（notes 注明"非机器直放"，实测），
初学者最常踩。

## 4. 三向标注与 fail-closed

`direction` 三向，语义要读准：

| direction | 含义 |
|---|---|
| `same` | 重放与归档结论一致（判读可复算） |
| `flip` | 结论翻转——触发人工仲裁复查，**不**改归档 |
| `not_judged` | 任一侧证据缺失 / 判据非机器直放——如实不判 |

`not_judged` 是 fail-closed 设计：证据缺失就多报"判不了"，**不冒充
same 也不虚构 flip**。这与体检门的 UNKNOWN 同一哲学——如实不判优于
凑结论。

批量面用 `replay_batch`（`core/recast.py`）：一次重放多份证据文件，
坏条目登记进报告、不静默跳过——批量结果里每个输入都有下落。

## 5. CLI 出口：rfauto recast status / replay

两只读薄壳（零逻辑转发 `service/recast_service` → `core.recast` 重放
内核；零写盘、不碰归档；全叶带 `--json`）。第 3-4 节的语义——三向
标注、fail-closed、`archived_verdict_path`——在 CLI 下逐条适用；
MCP 面暂无壳（2026-10-11 实测，需走 Python API）。

`rfauto recast --help` 实测，子命令恰两只：

```text
Commands:
  status  判据注册面清单（每条 id/规则形态/装载状态；坏条目如实登记）。
  replay  批量重放（全部已注册判据×全部证据，三向标注
          same/flip/not_judged）。
```

### status：判据注册面清单

`--criteria-dir` 缺省 `knowledge/criteria/v2`（等价于第 3 节的
`load_criteria_dir`）。`rfauto recast status` 实测输出：

```text
✓ 判据 3/3 条装载合格 ← knowledge\criteria\v2
┌───────────────────────────────┬────────────────────────┬────┬────────┐
│ criteria_id                   │ form                   │ ok │ errors │
├───────────────────────────────┼────────────────────────┼────┼────────┤
│ df5_c3fix_sentinel_four_gates │ multi_gate_all_pass    │ ✓  │        │
│ df6_dp10_scan_j1c_coverage    │ threshold_gate         │ ✓  │        │
│ hfss_interdigital_check_m1    │ nearest_reference_gate │ ✓  │        │
└───────────────────────────────┴────────────────────────┴────┴────────┘
```

坏条目不炸整表：`ok=✗` 且 errors 逐条登记（与 Python 面"坏条目如实
登记"同一口径）。

### replay：批量重放

关键旗标（`rfauto recast replay --help` 实测，节选）：

```text
--artifact               -a  归档证据 JSON 文件路径（可多次；
                             重放名=文件主干）
--evidence-path              threshold_gate 判据的证据绑定
                             criteria_id=点路径（可多次）
--archived-verdict-path      归档 verdict 在证据 JSON 内的点路径；
                             传 none 表示不比归档侧（方向恒
                             not_judged）  [default: verdict]
--json                   -j  JSON 输出
```

第 3 节哨档的 CLI 等价重放——`--archived-verdict-path
four_gates.verdict` 正对应 Python 例的第三个参数（缺省 `verdict`
落在顶层时不用传，第 3 节"最省时间的一课"在 CLI 下同样成立）：

```console
$ rfauto recast replay -a runs/demo/sentinel_verdict.json \
      --archived-verdict-path four_gates.verdict
✓ 重放完成 对数=3 判据=3（坏 0）
  same=1 flip=0 not_judged=2
  not_judged 2 对（证据缺失/非机器直放——如实不判，明细见 --json）
```

same=1 就是第 3 节 Python 例的那一对（归档 FAIL × 重放 FAIL）；另两
对如实 `not_judged`——threshold_gate 未给 `--evidence-path` 绑定、
nearest_reference_gate 非机器直放（第 2/4 节口径）。CLI 是纯批量面：
`-a` 可重复喂多份证据，全部判据 × 全部证据两两重放；`flip>0` 时终端
以醒目红字浮出（人工仲裁信号，如实透传不吞），明细与逐对结果走
`--json`。

## 6. 练习

1. 对 `hfss_interdigital_check_m1.yaml`（nearest_reference_gate 形态）
   走一遍重放——它的归档判读就在证据 JSON 顶层 `verdict` 键，不用传
   `archived_verdict_path`。读返回里的 notes：两条注记分别解释
   "非机器直放"与"归档侧开向"。
2. 故意把 `archived_verdict_path` 传错路径，观察 direction 落在
   `not_judged` 而非报错——然后解释为什么这是正确行为。
3. `load_criteria_dir` 的条目直接喂 `replay_one`（不取 `criteria`
   键），读 notes 里的"非机器直放"注记与 direction。
4. CLI 面重放哨档但不传 `--archived-verdict-path`——观察 not_judged
   计数（实测 3/3）与 Python 面"缺省取顶层 verdict"行为的一致性。

## 7. 下一步

- 判据与门的判读基本面：docs/how-to/read-verdict-gates.md
- 锚——判据之外另一类"跨引擎可信证据"：docs/tutorials/anchor-guide.md
- 归档证据从哪来（真机求解点的产物面）：docs/tutorials/
  real-simulation.md
- V&V 状态映射与判读口径的权威出处：docs/reference.md
