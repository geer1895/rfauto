# RECAST 走查：把归档判读重放一遍

> RECAST（判据重放）回答一个问题："当年那个判读，用今天登记的机器
> 判据再算一遍，结论还一样吗？"本文从判据格式讲到动手重放，全部代码
> 实测过。前置：docs/how-to/read-verdict-gates.md（判据与门的基本
> 读法）。RECAST 目前是 Python API 面（无 CLI/MCP 壳），本文即
> Python 用法。

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
    Path("runs/df5_c3fix/sentinel_verdict.json")
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

## 5. 练习

1. 对 `hfss_interdigital_check_m1.yaml`（nearest_reference_gate 形态）
   走一遍重放——它的归档判读就在证据 JSON 顶层 `verdict` 键，不用传
   `archived_verdict_path`。读返回里的 notes：两条注记分别解释
   "非机器直放"与"归档侧开向"。
2. 故意把 `archived_verdict_path` 传错路径，观察 direction 落在
   `not_judged` 而非报错——然后解释为什么这是正确行为。
3. `load_criteria_dir` 的条目直接喂 `replay_one`（不取 `criteria`
   键），读 notes 里的"非机器直放"注记与 direction。

## 6. 下一步

- 判据与门的判读基本面：docs/how-to/read-verdict-gates.md
- 锚——判据之外另一类"跨引擎可信证据"：docs/tutorials/anchor-guide.md
- 归档证据从哪来（真机求解点的产物面）：docs/tutorials/
  real-simulation.md
- V&V 状态映射与判读口径的权威出处：docs/reference.md
