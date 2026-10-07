# 锚导览：查、读、消费一条物理标定锚

> 本文面向"知道 rfauto 有锚、但还没用过"的读者：锚是什么 → 为什么可信
> → 怎么查 → 怎么消费 → 怎么维护，五问一页走完。全部命令与代码都在
> 开发环境实测过（退出码 0），示例输出为实测摘录。前置：已读
> docs/tutorials/getting-started.md（安装与 CLI 基本面）。

## 1. 锚是什么

一句话（knowledge/anchors.yaml 头注原文口径）：

> 锚 =（模板族 × 引擎对 × 域）→（常量 | 曲线 | 公式 | 指针），
> 描述**引擎对系统偏差**。运行时只读；写入只经人工提交。

它回答的问题是："同一个设计，openEMS 算出来和闭式/HFSS 差多少？"
这个差值不是 bug，而是每个引擎的系统性偏差——把它测出来、登记成
锚，后续综合与判读就有了跨引擎的"换算基准"。

当前注册表共 49 条锚（`rfauto anchors validate` 实测），分型分布：

| 维度 | 分布 |
|---|---|
| kind | constant 38 / pointer 8 / formula 2 / curve 1 |
| status | experimental 36 / active 13 |
| engine_pair | closedform→∅ 26 / openems→hfss 14 / mmt→hfss 2 / quasistatic_fd→∅ 2 / hfss→hfss 1 / hfss→openems 1 / 无 3 |
| 模板族 | 38 族（c3 / patch / wilkinson / branchline / cps / coil_nfc / siw …） |

**pointer（双值指针锚）值得单说**：openEMS 与 HFSS 各登记一个值，
**不合并成单一常数、也不就地求值**。设计意图是"双值并存、比对消费"，
所以你在 list 里看到 pointer 的 value 列是 `None`——这不是缺数据，
而是"不该有单值"。

## 2. 为什么可信：一条锚的证据结构

看一条真实锚（active、经 HFSS 仲裁的常量锚）：

```bash
rfauto anchors inspect c3.l_via_h.openems-hfss-v1
```

实测输出：

```
c3.l_via_h.openems-hfss-v1（v1，constant，active）
  量: l_via_h [H]——过孔寄生电感校准值（补偿电感），替代 Goldfarb-Pucel 闭式缺省
  value: 1.25e-10
  uncertainty: {'value': 2e-11, 'kind': 'arbitration_interval'}
  domain: None
  engine_pair: {'calibrated': 'openems', 'referee': 'hfss'}  fallback: closed_form
  provenance: runs=['runs/df5_c3fix'] commit=caa79b5
  consumers: ['src/rfauto/adapters/openems_templates.py',
              'src/rfauto/adapters/fake_adapter.py']
```

判读一条锚，看四个面：

**（1）uncertainty.kind 分型即信任等级**。当前注册表出现六类：

| kind | 含义 |
|---|---|
| `arbitration_interval` | 预声明仲裁门宽作包络（本例：HFSS 反解 0.12–0.13nH 区间中点） |
| `relative` | 保守相对包络（如 patch.f_dip_l 的 ±5%） |
| `rounding_band` | 名义几何 4 位舍入回代带 |
| `identity` | 内核恒等（定义即真） |
| `engine_pair_spread` | 双引擎平方法差 |
| `fd_referee_band` | 有限元裁判带 |

**（2）仲裁语义**。凡经引擎对仲裁的锚，provenance 里带
`verdict_state`（AGREE_OPENEMS / AGREE_HFSS / DISAGREE 三向，当前
15 条带）；HFSS 是对齐基准——两引擎分歧时以 HFSS 侧为准采信
（各引擎的定位与门槛见 docs/tutorials/real-simulation.md 第 6 节
多保真全景）。
带 ΔS 收敛阶梯的锚还有 `ladder_last_rung`：判读前先看它是否触顶——
触顶说明"最后一档没收敛"，数值要打折读。

**（3）新鲜度**。`last_verified.at/residual` 记录上次复验时间与残差；
status 生命周期为 active | stale | experimental | retired |
awaiting_data。**断锚不改历史**：新证据登记 -vN+1 版本，旧版标
retired + superseded_by 保留原文——归档证据永远零改写。

**（4）消费禁令也是锚内容**。以 `patch.f_dip_l.hfss-v1` 为例：它是
HFSS 归档探针离线复核的谷位标定常数，后续仲裁实证该值反解出的物理
几何不可能（隐含 εeff 低于物理下限）——semantics 里明写"引擎内部
定标口径非物理谐振量，禁止当物理 TM10 锚消费"。注意它 status=
active：**active 表验证态，不是消费许可**。读锚先读 semantics，
是消费任何锚的第一步。

## 3. 怎么查：三层入口

**CLI 面**（`src/rfauto/cli/domains/anchors.py`，五命令）：

```bash
rfauto anchors list          # 总览表：anchor_id/kind/status/value
rfauto anchors inspect c3.l_via_h.openems-hfss-v1   # 单锚全量记录
rfauto anchors validate      # schema + provenance + 单源计数校验
rfauto anchors stale --threshold 30   # 新鲜度盘点
```

实测 `validate` 输出：

```
锚注册表校验（DP-3）：49 条（单源期望 49，匹配=True），registry=None
✓ schema + provenance 全过
```

实测 `stale` 输出头（`no_date` 是"从未复验、如实不算 stale"）：

```
锚新鲜度（QW-3，阈值 30.0 天，stale 0/no_date 30/49 条）
```

另有 `rfauto anchors drift <anchor_id>`：Mann-Kendall 趋势 + 分布
指纹差分（需要历史快照数据，积累期如实报 empty_series）。

**service 面**（JSON 进出，CLI/MCP 都是其薄壳）：

```python
from rfauto.service.anchors_service import find_anchors_request

find_anchors_request("patch", "f_dip_L", engine="openems")
# → {'ok': True, 'count': 1, 'anchors': [...patch.f_dip_l.openems-v1...]}
```

`engine=` 参数用于双席去歧义：同一族×量若同时登记 openems/hfss 两版
（如 patch.f_dip_l），不传 engine 会命中多席。

**知识检索面**（跨规则/锚/手册/工艺四个源统一搜）：

```python
from rfauto.service.knowledge_service import search_knowledge

search_knowledge("l_via_h", scope="anchors")
# → {'ok': True, 'n_hits': 1, 'scanned': {'rules': 9, 'anchors': 49,
#    'playbook': 17, 'fab': 2}}
```

MCP 面（`anchors_list` / `anchors_inspect`）与 service 同源，供
Agent 工具循环消费，见 docs/reference.md 的 MCP 清单。

## 4. 怎么消费：锚→设计自动修正链（XC-A）

先钉分层，防混层（core/anchors.py 模块注释口径）：

- **warm_start = 参数面**：历史优化样本作新战役起点；
- **XC-A = 偏差面**：锚修正综合闭式的输出（注入综合初值或收缩
  bounds）。XC-A 产物**可以**作 warm_start 的候选输入，但锚修正
  **永不**直接改优化器状态——两层边界由模块签名钉死：只产出修正
  包络，零优化器 IO。

链路四步（命令全实测）：

**第 1 步：族×量查锚**

```python
find_anchors_request("patch", "f_dip_L", engine="openems")["count"]
# → 1
```

**第 2 步：算修正包络**

```python
from rfauto.service.anchors_service import apply_anchor_correction_request

apply_anchor_correction_request(
    "patch", "f_dip_L",
    params={"f0_ghz": 2.45, "patch_len_mm": 40.0},
    design_value=98.0, engine="openems")["result"]
# → {'applied': True, 'value': 76.8, 'delta': -21.2,
#    'delta_kind': 'absolute', 'band_rel': 0.05}
```

设计值 98.0（GHz·mm 闭式输出）被锚值 76.8 修正 −21.2。

**第 3 步：三拒绝门（永不抛异常，结构化 reason）**

```python
apply_anchor_correction_request(
    "wilkinson", "wilkinson_f_match_dev_pct",
    params={"arm_len_mm": 20.0}, design_value=None,
    engine="openems")["result"]
# → {'applied': False, 'reason': 'uncertainty_exceeds_threshold'}
```

拒绝门三张 + 前置分支两张：

| reason | 触发条件 |
|---|---|
| `no_matching_anchor` | 族×量×引擎无锚（前置分支） |
| `ambiguous_active_anchors` | 命中多席且未用 engine= 去歧义（前置分支） |
| `uncertainty_exceeds_threshold` | 锚不确定度相对值超阈（缺省 10%） |
| `status_not_active` | 锚非 active（experimental/stale/retired） |
| `out_of_domain` | 设计点在锚 domain 声明域外 |

上面 wilkinson 的例子是刻意的：它的仲裁包络换算成相对值 265%，
远超 10% 阈值——**弱约束锚不做修正，不凑**。拒绝是正确行为。

**第 4 步：注入综合输出**

```python
from rfauto.service.level2_design import apply_synthesis_anchor_correction

apply_synthesis_anchor_correction(
    "patch", {"params": {"f0_ghz": 2.45, "patch_len_mm": 40.0}})
# → {'applied': True, 'injection': {'key': 'patch_len_mm',
#    'mode': 'constant_over_f0', 'old_value': 40.0, 'new_value': 31.35}}
```

76.8 / 2.45 GHz = 31.35 mm——闭式给的 40.0 被锚修正注入。注意注入
表白名单（service/level2_design.py 的 `_ANCHOR_CORRECTION_TABLE`）
当前只挂 patch：wilkinson/branchline 的锚只做查询+判读+留痕，不做
修正注入——是否挂表按锚的约束强度逐族决定。

## 5. 怎么维护（贡献者向）

- **单源计数**：增删锚必须同步 `src/rfauto/core/anchors.py` 的
  `EXPECTED_ANCHORS`（tests/unit/test_anchors_store_service.py 钉住
  数量一致），否则 `rfauto anchors validate` 报"单源期望不匹配"。
  这与计算器/模板注册的"消费者五钉清单"是同一纪律（钉法对照见
  docs/tutorials/extending-rfauto.md 第 2 节）。
- **残差登记走内存面**：`note_anchor_residual_request(anchor_id,
  point)` 只翻 stale 标记、不写 YAML——注册表落盘只经人工提交。
- **漂移门**：|残差| > max(3σ, 5%·|锚值|) 即判 stale（core/
  anchors.py 常量口径）。
- 版本演进：新证据登记 -vN+1，旧版 retired + superseded_by——
  永不原地改值。

## 6. 练习

1. `rfauto anchors inspect branchline.f_match.openems-hfss-v1`（或任一
   pointer 锚），解释它为什么没有单值。
2. 用 wilkinson 偏差锚触发 `uncertainty_exceeds_threshold` 拒绝门，
   读出完整 reason 结构。
3. 对比 `find_anchors_request("patch", "f_dip_L")` 不带 engine= 与带
   `engine="openems"` 的 count 差异，理解双席去歧义。

## 7. 下一步

- 锚在多保真方法论中的位置：docs/explanation/layered-architecture.md
- 引擎对从哪来（真机求解与多保真全景）：docs/tutorials/
  real-simulation.md
- 判据先行的重放验证（与锚的证据面互补）：docs/tutorials/
  recast-walkthrough.md
- 各模板的能力卡（含锚引用）：docs/capability_cards/
- 全部命令权威出处：docs/reference.md
