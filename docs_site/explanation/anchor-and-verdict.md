<!-- PR-10 文档站同步副本：源=docs/explanation/anchor-and-verdict.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 解释：锚与判据——rfauto 的采信制度

> 这是一篇 explanation（解释文）：回答"为什么要有一套锚注册表 +
> 预声明判据的采信制度"。操作面互补：docs/tutorials/anchor-guide.md
> （锚注册表实操）、docs/tutorials/verdict_semantics.md（判读语义）、
> docs/how-to/read-verdict-gates.md（读门结果）、
> docs/tutorials/recast-walkthrough.md（判据重放）。

## 两个互补面：锚是"偏差的知识"，判据是"采信的规则"

仿真自动化走到真机，立刻遇到两个不同性质的问题：

1. **引擎会错，且错得有规律**——openEMS 与 HFSS 对同一设计给出方向
   甚至都相反的偏差（#350 实证过两引擎谐振偏移一低一高）。这些系统
   偏差本身是**可登记、可复用的知识**：这是**锚**要管的。
2. **数据能不能采信，不能临场裁决**——截断当物理、部分矩阵当满矩阵、
   常数谷当优化成功，每一种都比算得慢贵得多。采信必须是**预声明的
   确定性规则**：这是**判据（verdict 门）**要管的。

两面共享同一个哲学：**判断权不给临场的人（或 agent），给登记在册的
制度**。区别在对象——锚校的是数值偏差，判据管的是采信资格。

## 为什么需要锚：系统偏差是常态

理想的"引擎即真值"在多保真实践里不成立。三个本项目实证过的形态：

- **闭式经验公式高估**：c3 过孔寄生电感，Goldfarb-Pucel 闭式对粗短
  过孔高估 2.2-2.5 倍，HFSS 反解 0.12-0.13nH 区间（锚
  `c3.l_via_h.openems-hfss-v1`，replaces 字段留了被替换的旧值）；
- **引擎间常数级系统差**：openEMS 引擎自算线阻抗比 HJ 综合值低
  4.7%/3.7% 的系统偏差（#250 族）——不校准就化作每个端口的伪反射；
- **两引擎偏差方向相反**（#350）：HFSS 低 18% vs openEMS 高 ≥20%，
  任何"单引擎归因"都会得出相反的错误修正。

对这些偏差的态度有两种：每次遇到临时"修一下"，或者**登记成制度**。
rfauto 选后者——因为临时修一下的偏差知识留在会话记忆里，下个会话
再犯一遍；登记制度让偏差知识变成资产。

## 锚注册表的设计决定

注册表是 `knowledge/anchors.yaml`（schema `anchors/v1`），单源计数在
`core/anchors.py` 的 `EXPECTED_ANCHORS`（2026-10-23 实测 87）。锚的
定义式：**(模板族 × 引擎对 × 域) → (常量 | 曲线 | 公式)**。几个关键
枚举不是摆设，每一个都对应一次制度演进：

| 维度 | 枚举 | 为什么这样分 |
|---|---|---|
| status | active / stale / experimental / retired / awaiting_data | awaiting_data 让骨架锚可以先登记位置、数据回填后翻 active（预声明扩展，不占活跃计数）；retired 是历史保留位（见下节） |
| kind | constant / curve / formula / pointer | pointer 锚只登记引擎对双值、不产 constant 数字不就地求值——HFSS 窗 B→A 批的产物：证据在手但仲裁未完时，**不伪造定值** |
| layer | closure / component / system | V&V 层级制度化：闭式验证层 / 单器件仲裁层 / 阵列系统确认层——引用锚时先看它属于哪层验证，不越层消费 |

**Provenance 是锚的主体，不是附件**。每个锚必须带：仲裁 run 目录
（`arbitration_runs:`）、commit、开发注记 出处、被替换的旧值
（`replaces:`）。判一个锚可不可信，看的是这条证据链，不是数值本身
好不好看。

## 修订纪律：历史不改写

锚是知识，知识会更新——但 rfauto 的更新方式是**追加版本，不是覆盖**：
新证据登记 `-vN+1`，旧版 status 翻 `retired` + `superseded_by` 保留
原文（#325/#326：golden 与归档证据零改写）。这条纪律的动机和判据面
同源：如果可以就地改写，三个月前基于旧锚的判读就无法重放，RECAST
（判据重放，docs/tutorials/recast-walkthrough.md）就失去前提——
"当年那个判读，用今天登记的锚重算一遍"要求**当年的锚还在档**。

配套的保鲜机制：`scripts/audit_anchor_freshness.py`（合流预检第 14 项）
对注册表做只读时效审计——非 retired/awaiting_data 锚缺 `last_verified`
超棘轮（现值冻结、只收不放）即红；时效超龄（experimental>30 天/
active>90 天）进报告面**永不红**——时间推移本身不该打红无关席位，
但会让超龄锚在消费时被看见。

## 写入路径：运行时只读，写入只经人工

锚注册表运行时**只读**；写入只经人工 commit（内核立规 6，Agent
写面隔离）。这样规定不为限制 agent，是为了利益冲突隔离：agent 的
优化目标（让 cost 好看）与锚的公正性（如实登记偏差）结构性冲突——
让优化者自己改校准常数，等于让考生改评分标准。agent 可以**提议**新
锚或锚修订（带仲裁证据），落地必须人工审 commit。

## 判据面：三条纪律

判据（verdict 门）回答"这份数据能不能采信"。制度浓缩为三条，每条
都有项目史的失败案例背书：

1. **预声明**。判据（阈值/口径/适用族）在真跑前写进判据书或 meta，
   跑完不改门。判 FAIL 是有效产出——它拦住了坏数据入库；事后改门
   才是事故。适用族必须显式分派（#274）：patch 的效率合理窗
   [0.55, 0.79] 不加作用域会把带全包盒的 dipole 误判 FAIL——门常量
   旁边写死适用族，不适用族 `gate=None` 不判。
2. **诚实分级**。PASS / WARN / FAIL / UNKNOWN 四态，UNKNOWN=证据不足
   暂不下结论——把 UNKNOWN 当 PASS 消费是错误用法；数据只有单向已测
   时就标 UNKNOWN，既不凑成通过也不硬算作失败（#122/#314）。判定方向上，
   形状不符/非法掩码的兜底选"多报"不选"放过"（#316）。
3. **掩码先行**。对称/互易补齐的矩阵元素必须随掩码流转，互易性判据
   只对两向独立已测的对下结论——5 列 2 端口 csv 的"全 PASS"不构成
   互易证据（#314 族）。

门的实现位置也讲分层：判读逻辑全部内核化为确定性函数（健康体检
G11 等），壳层只渲染——这与"数值只在确定性内核"（见
docs/explanation/deterministic-kernel.md）是同一条架构纪律在判读面
的投影。

## 锚与判据怎么协作

一次典型的真机采信链，两面各出一次力：

```
真跑 → 判据门（预声明+掩码）裁决"数据合格"
     → 锚校准（active 锚按 provenance 消费）把引擎对偏差校到对齐基准
     → 产物落 run 目录（meta/verdict/锚引用齐备，可 RECAST 重放）
```

反过来，锚自身的健康也有判据管：时效审计棘轮（上节）、
`tests/unit/test_anchors_store_service.py` 钉注册表与单源计数一致、
双锚判定（`core/anchor_verdict.py` 的 dual_anchor_verdict，主/副锚
各自容差独立判定）。制度互相咬合，不留"谁来监督监督者"的空位——
监督者也被更外层的预声明规则监督。

## 给贡献者的推论

- 想登记新锚：先有仲裁证据链（run 目录+commit），再走人工 commit；
  增删锚必须同步 `EXPECTED_ANCHORS` 单源（教程第 5 节有消费者清单）；
- 想写新门：判据进判据书/预声明字段，实现进 service（JSON 进出），
  门常量带适用族作用域；
- 消费锚前看三个字段：status（可不可用）、layer（哪层验证）、
  provenance（谁仲裁的）——缺任一项都值得停下来问一句；
- 实操入口全在教程：docs/tutorials/anchor-guide.md。
