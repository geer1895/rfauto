<!-- PR-10 文档站同步副本：源=docs/tutorials/verdict_semantics.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 判读语义：三态、掩码与门的作用域

> 一次真机 run 结束，门给你一行 `verdict: unhealthy`——然后呢？本文讲
> rfauto 判读面的**读法**：三态（PASS/FAIL/UNKNOWN）各意味着什么、掩码
> 怎么随矩阵流转、门常量为什么按模板分作用域、判据统计量为什么要匹配响
> 应形态。机制面（G11 体检怎么跑、verdict 产物在哪）分别在
> docs/tutorials/datasets_and_health_gates.md §6-7 与
> docs/how-to/read-verdict-gates.md，本文不重复——本文回答"拿到结论
> 之后，怎么读出**可信**的下一步"。全部例子都是仓内真实档案的实测输出，
> 出处随手可查。前置：docs/how-to/read-verdict-gates.md。
> 英文版（English version）：docs/tutorials/verdict_semantics_en.md。

## 1. 三态铁律：UNKNOWN 不是 PASS，也不是 FAIL

判读面只有三个结论值：**PASS**（证据达标）、**FAIL**（证据违反判据）、
**UNKNOWN**（证据不足、如实不判）。三条纪律（#122 家法）：

- **把 UNKNOWN 当 PASS 消费是错误用法**——fake run 没有场 dump 就不评
  功率守恒，不评 ≠ 通过；
- **无对（两向独立未测）不下结论**，不凑 PASS 也不冒充 FAIL；
- **FAIL 先分两族**："数据坏"与"判据面不覆盖本族"——后者换口径（判据
  按模板作用域分派），不是重跑（§5）。

run 级 rollup 规则：任一 factor FAIL → `unhealthy`；有 WARN →
`suspect`；否则 `healthy`。

## 2. 实测一遍：healthy ≠ 全 PASS

对一个真实 openEMS 采集点体检（数据工厂 M1 库存的第一点）：

```bash
rfauto runs health 20260920_002700_2bb07757
```

实测输出（节选）：

```
│ excitation           │ PASS    │ #174 │ 全部透射列全带宽峰…0.9832 ≥ 1e-06，激励非零
│ cost_distribution    │ UNKNOWN │ #195 │ cost 序列缺失，无法判定…
│ timestep             │ UNKNOWN │ #152 │ 无 timestep 记录…按 #152 惯例不误报
│ passivity            │ PASS    │ …│ max|S|=0.9832 ≤ 1.01（1% 容差…）
│ reciprocity          │ PASS    │ …│ max|Sij−Sji|=0.00e…< 0.01
│ gain                 │ PASS    │ …│ 全带宽透射均值 -0.160 dB ≤ 0.5 dB…
│ power_balance        │ UNKNOWN │ …│ 无损耗图积分功率（…dump_type=29 体 dump…）
│ thermal_plausibility │ UNKNOWN │ …│ 无热产物…
  verdict: healthy  ok=True
```

读法：**4 个 PASS + 4 个 UNKNOWN = healthy**。每个 factor 四列里"依据"
列是判据出处（#174 激励体积死、#152 CFL 塌缩、#195 cost 退化——历史踩
坑教训内核化），"说明"列是实测数字对照阈值。体检的诚实性正体现在
UNKNOWN 上：证据不在，就写明缺什么，不硬判。

## 3. unhealthy 怎么读：掩码语义与 FAIL 的两族分解

再看一个真实档案里的 unhealthy（aurora_c 战役 branchline 工作目录）：

```bash
rfauto runs health aurora_c_oe/branchline
```

实测输出（节选）：

```
│ reciprocity │ FAIL │ SpecEvaluator.check… │ max|Sij−Sji|=0.6957 ≥ 0.01：互易性违背
  verdict: unhealthy  ok=False
  - sparams.mask.json 形状与 csv 矩阵不符——掩码回退全矩阵已测（#316 多报方向）
```

第一反应不该是"数据坏了"，而是读**证据链**：

1. 尾行已经给出关键线索：掩码文件形状与 csv 矩阵不符，体检**回退成"全
   矩阵已测"**——这是 #316 立下的兜底方向：**多报不放过**（最多多一条
   FAIL 让人看见，不能把真问题静默放行）；
2. 0.6957 这个数是什么？它恰等于全带宽透射峰——**单激励 run 的 csv 是
   零填充部分矩阵**（激励行有真值，其余行填零），把填零行当独立测量去
   比对互易性，|S12−S21|≈|S21| 的"FAIL 指纹"就出现了（#314：派生元素
   与已测元素混入同一矩阵且不带掩码流转，下游任何全矩阵判据都会把补齐
   值当测量值）；
3. 所以此 FAIL 属于"判据面与掩码配位问题"，不是物理互易性被破坏——
   处置是修掩码流转（掩码载体优先于 Touchstone；单激励写入方必须随矩阵
   给掩码），而不是重跑仿真。同目录 `verdict.json` 里时序判据
   `nrts_converged` 是 ok=true（EndCriteria 提前停机，见 §4），无源无
   hot 的物理门也过——**一票 FAIL 不推翻全案，逐 factor 定位才是判读**。

掩码三条消费规则（#314/#316 族收口）：

- **掩码载体优先**：run 目录同时有掩码 csv 与 Touchstone 时认前者——
  单激励 Touchstone 是零填充部分矩阵，全对查互易必出上述假阳性指纹；
- **兜底方向多报**：掩码形状非法/不符 → 按"全矩阵已测"处理（宁可多一条
  FAIL），不静默按"全未测"放过；
- **互易性只对两向独立已测的端口对下结论**，一对都没有 → UNKNOWN。

## 4. 时序判据：NrTS 触顶、能量停滞与提前停机

时域引擎（openEMS FDTD）的 run 有专属时序判据族，`runs monitor` 一条
命令扫全战役目录（四类判据：进度/截断嫌疑/NrTS 触顶/能量停滞）：

```bash
rfauto runs monitor runs/aurora_c_oe --cycle
```

实测输出（节选）：

```
✓ 周期体检  监测 30 个 run  红 0  黄 1  unknown 29
  branchline: green
  ...
  pifa: yellow
```

黄名单那一个，单查它：

```bash
rfauto runs monitor runs/aurora_c_oe/pifa
```

```
  run: pifa  verdict: yellow
  - 激励结束后能量增长（衰减率 -0.5261 dB/ns < 0，发散/未歇嫌疑）
```

三条读法：

- **yellow=suspect 不是 FAIL**：能量在激励结束后还在涨，嫌疑是截断或
  未收敛——先查 NrTS 时窗是否覆盖脉冲全程（#262：窄 FC 窗长脉冲被截断
  会出 |S11|>1 假象；#266：NrTS 触顶即判未收敛），再怀疑物理；
- **无时域产物的 run 如实 unknown**（"无 port_ut/et 时域产物"）——
  unknown 同样不是通过；
- **提前停机是合法收敛**：branchline 档案 `verdict.json` 里
  `nrts_converged` 实测 `{iterations_done: 31439, nrts: 100000,
  end_criteria_db: -60.0, min_energy_db: -60.25, ok: true, reason:
  "按 EndCriteria 提前停机（未触 NrTS 上限）"}`——能量降到 -60.25dB
  越过 -60dB 判据即停，31439/100000 步。**触顶（跑满 NrTS）才是未收敛
  的信号**，提前停不是。

## 5. 门的作用域：门常量按模板分派（#274 家法）

通用缺省门（如 S11 谷深 -10dB 惯例）对非适用族会误判：全包盒偶极子的
η=0.99 会被 patch 族的 η 窗 [0.55,0.79] 打成 FAIL。服务层的解法是
**模板作用域门登记表**（`service/edb_health_gate.py`，#274 家法）：

```
门常量按模板作用域分派：调用方显式覆盖 > 模板登记表 > 通用缺省；
登记值 None = 该族显式不设门（如实 UNKNOWN，不硬套通用缺省）。
```

一个真实仲裁案例（`runs/edblane85/w1_smoke/REPORT.md` §3.2）：Wilkinson
功分器冒烟实测 |S21|@f0=-3.192dB、|S31|@f0=-3.261dB，字面门（≤-3.8dB）
判 FAIL——语义仲裁指出等分分配的理想值是 -3.01dB，"分配损耗显著小于
3dB"反而是提取/接线伪象。裁定后的模板作用域窗：

```
POWER_DIVIDER_SPLIT_WINDOW_DB = (-3.8, -2.5)   # 下界=3dB 分配+0.8dB 实现容差；上界排异常增益
```

-3.192/-3.261 双双落窗 → 健康。教训：**门数字必须有真机/仲裁出处，且
只对该模板族生效**；非适用族 gate=None 如实不判。

## 6. 判据统计量要匹配响应形态：深谷族 dB 陷阱

窄带深谐振谷（S11 谷深 -50dB 量级）族上，**dB 域门本身就是误定口径**
——谷深每深 1dB 需要的参数精度指数级上升，加密采样救不了（#370/#371
判据结论）。数据工厂的真实对账（`runs/datafactory_m2/verdict_merged150.json`，
谷区加密 150 点批）：

- 深谷点 dB 误差实测 max **30.38dB**（真值 -64.15 vs 预测 -33.77）——
  而同一点的**线性域 |ΔΓ| 误差只有 0.0199**；
- 深谷桶（n=179）dB 误差均值 6.79dB，浅谷桶（n=451）2.89dB——误差集中
  在谷深处；
- 换模型类对照（poly_ridge 控制腿）dB 门照样 FAIL（max 33.15dB）——
  **是表示问题（dB 域），不是模型问题**；
- 三方对照：120 点批与 150 点加密批的 s11_db 门**双双 FAIL**——加密把
  线性域门救 PASS 了（0.0159 < 0.04），dB 门反而随谷更深而更差。

正确姿势：**消费口径用线性域 |ΔΓ|，精度锚用 εeff**，两口径并列如实
落档（同目录 `verdict_linear.json` overall=PASS 与 `m2_verdict.json` 的
dB 门 FAIL 并存——不互相覆盖，各管各的语义）。§4 同款教训的判读版：
**判据统计量（max/mean/谷深/峰位）必须先匹配响应形态**（#195：窄带谐
振族带内 max 是常数陷阱），再谈阈值。

## 7. 预声明与重放：判据的时间轴纪律

- **先写后算**：批次判据落 `runs/<批次>/criteria.md`，写入时刻先于数据
  （数据工厂链的惯例，见 docs/tutorials/data_factory.md §1）；
- **门红不事后改门**：MFK FAIL、cost 劣化 +8.42% 这类结论都按预声明门
  如实落档，要改门就走新判据+新档案，不改历史；
- **归档零改写**：重标定/复算一律新文件（`--out` 到自己的工作目录），
  历史证据是 replay 的输入不是修改对象；
- **拿今天的判据重算昨天的判读**：`rfauto recast`（RECAST 判据重放，
  完整走查见 docs/tutorials/recast-walkthrough.md）——判据演化后，旧
  结论还成立吗？这是判读面自洽性的最后一道检查。

## 下一步

- G11 体检机制与数据集物化：docs/tutorials/datasets_and_health_gates.md
- 判据重放：docs/tutorials/recast-walkthrough.md
- 判读数据从哪来：docs/tutorials/data_factory.md
- 物理标定锚（判读的第三方参照）：docs/tutorials/anchor-guide.md
