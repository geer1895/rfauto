<!-- PR-10 文档站同步副本：源=docs/explanation/engine-ladder-and-arbitration.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 解释：多保真引擎阶梯与 HFSS 仲裁——为什么可信

> 这是一篇 explanation（解释文）：回答"为什么 rfauto 要 fake → openEMS →
> HFSS/ADS 三层引擎、为什么 HFSS 是对齐基准、经验常数凭什么被采信"。
> 操作面互补：docs/tutorials/real-simulation_en.md（真机实操）、
> docs/tutorials/anchor-guide_en.md（锚注册表实操）、
> docs/explanation/anchor-and-verdict.md（锚与判据制度）、
> docs/fake_channel_investigation.md（fake 通道调查档案）、
> docs/how-to/add-new-solver-engine.md（接入新引擎）。

## 三个问题，一张阶梯

仿真自动化绕不开三个"为什么"：

1. **为什么不全用真求解器？**——HFSS 一次求解分钟到小时级、占
   license 席位；优化动辄几十到几百次评估，全用贵通道等于把搜索
   预算烧在明显错误的参数点上。
2. **为什么不全用便宜通道？**——解析近似（fake）看不见它没建模的
   物理；用它排序，错得很有规律（下节有实测证据）。
3. **便宜通道给出的数字，凭什么信？**——凭**仲裁**：把跨引擎偏差
   登记成制度，让贵通道只在关键处出场。

rfauto 的答案是阶梯（分层架构里 adapters 层的注册表，实测
`channel_names()` → `('fake', 'hfss', 'openems')`，2026-10-19；
`check_known_adapters()` 另见 comsol/mmt/palace/vna 四个 EMSolver
契约适配器与 ads 原生 API 通道）：

```
fake（秒级，解析近似）→ 校准代理（预筛）→ openEMS（分钟级，全波 FDTD）
                        → HFSS / ADS（贵通道：仲裁与终验）
```

每一层的职责不是拍脑袋分的，是三个实证战役换来的——fake 只做冒烟/
CI/UI（把"配方写得对不对"这类结构性错误拦在秒级）；openEMS 做参数
扫描与校准的主力；HFSS 做仲裁与终验。

## 为什么 fake 不能预筛：一份实测档案

直觉说"fake 便宜，先用它粗筛再上真引擎"。2026-09-04~05 的调查
（结论档案 docs/fake_channel_investigation.md，五级实验全部可复跑）
把这个直觉证伪了：

- fake 原生 vs openEMS 排序一致性 **ρ=0.377**；锚重推谷位后
  ρ=0.608——仍低于可用线；
- 换教科书电路通道（Pozar 偶/奇模）**ρ=0.18**，比 fake 更差；
- 电路形状+物理修正的混合 fake-v2 **ρ=−0.278**，越修越差。

失败是结构性的：排序分歧由**公式看不见的物理**主导——T 型结储场、
双臂耦合、色散、馈线真实阻抗（闭式谷位 2.5GHz vs 全波 2.2GHz，
−12%，且错位恰落在排序最敏感的带内平坦区）。预筛职责最终由校准
代理承担（LOOCV ρ=0.845）。**这就是"数值只在确定性内核"与"每层
引擎只干它证得过的事"两条纪律的交汇点**：不是 fake 数字不准，是
fake 数字回答不了排序问题。

## 为什么 HFSS 是对齐基准

项目立规（2026-09-08）：**HFSS 结果为对齐基准，其他引擎/设计值向
HFSS 对齐**。理由是一个工程判断（并非"HFSS 永远对"）：

- HFSS 是射频领域认可度最高的 EDA——对齐到它，结论才可对外主张；
- 同模型仿真异常时，**几乎必然是我方建模错误**（波端口尺寸、边界、
  网格），不是引擎错——修正路径先查官方文档再动手（#191 实证）；
- 对齐是有方向的：经验常数只有**经 HFSS 仲裁背书**后才能成为配方
  设计依据（如 patch 族引擎经验常数 f_dip·L≈76.8，锚
  `patch.f_dip_l.openems-v1` / `patch.f_dip_l.hfss-v1` 双引擎分立
  ——同一常数跨引擎直接沿用正是首轮目标落空的根因）。

HFSS/ADS 的环境探测是 `doctor` 的职责（实测输出：AEDT 2025.1 v251
best_effort、ADS 2027 verified——没有 license 时 doctor 如实标注，
阶梯自动退化为 fake → openEMS 两层可用）。

## 仲裁语义：引擎对、锚、指针

两个引擎对同一设计的偏差，本身是**可登记的知识**。登记式样
（knowledge/anchors.yaml，schema `anchors/v1`，2026-10-19 实测
79 条）：**(模板族 × 引擎对 × 域) → (常量 | 曲线 | 公式 | 指针)**，
其中 `engine_pair: {calibrated: openems, referee: hfss}` 显式写明
谁被校准、谁当裁判。

三条实测过的仲裁语义，每条都对应一次制度演进：

1. **常量锚必须带证据链**。例：c3 过孔寄生电感，闭式
   Goldfarb-Pucel 对粗短过孔高估 2.2-2.5 倍；HFSS 反解 0.12-0.13nH
   区间中点定值 0.125nH（锚 `c3.l_via_h.openems-hfss-v1`，status
   active，provenance 带仲裁 run 目录/commit/DEVLOG 出处/replaces
   旧值）。openEMS 反解 0.20nH 如实登记为跨引擎发现、**不作定值**
   ——裁判只有一个。
2. **证据在手但仲裁未完时，登记指针不产定值**（kind=pointer，实测
   8 条）。例：stepped_impedance 谷位双引擎分歧超预声明门，锚按
   双值登记、`consumers=[]`、不产 constant——**禁止取平均凑数**
   （#122 家族：如实登记优先于好看）。
3. **两引擎偏差可以方向相反**（#350 实证：HFSS 低 18% vs openEMS
   高 ≥20%）——所以单引擎归因"哪个引擎差多少"天然不可靠，必须
   引擎对成对登记；预声明 AGREE/DISAGREE 门在 DISAGREE 时阻止
   单侧误采信。

注册表当日分布（实测）：kind = constant 68 / pointer 8 / formula 2 /
curve 1；layer = closure 61 / component 14 / system 4；status =
active 19 / experimental 59 / retired 1。experimental 占多数是
制度健康的信号——新锚先挂 experimental 观察窗，验证后才翻 active。

## 阶梯与锚怎么协作

一次典型的跨保真工作流，三层各出一次力：

```
fake 冒烟（配方/几何/链路对不对，秒级）
  → openEMS 批量评估 + active 锚校准（把 openEMS 对 HFSS 的已知系统
    偏差先校掉，再看设计趋势）
  → 关键设计点 HFSS 仲裁（预声明判据：幅度差与方向一致性双门）
      → AGREE   → 结论采信，必要时登记/更新锚
      → DISAGREE → 双值指针锚如实登记，回查建模（先验模型再校准）
```

注意锚在其中的位置：**锚校的是"已知、稳定、登记在册"的引擎对系统
偏差**，它让便宜通道的结论可以外推到对齐基准口径；锚不管的（新
模板族、新结构、超锚域的设计点）必须由真仲裁补——这就是
docs/explanation/anchor-and-verdict.md 讲的"锚是偏差的知识，判据
是采信的规则"分工在跨保真场景的展开。

## 给贡献者的推论

- 接入新引擎（how-to/add-new-solver-engine.md）时，先问它在这张
  阶梯的哪一层、跟谁构成引擎对、第一批仲裁实验是什么——没有仲裁
  路线的新引擎只能挂 experimental；
- 想让某个经验常数进配方：先跑仲裁、再登记锚、然后人工 commit
  （写入路径见 anchor-and-verdict 同名节——agent 可提议，落笔在
  人）；
- 引用带锚校准的结论时，看三个字段：engine_pair（对齐到谁）、
  status（active 才可直接消费）、layer（闭式/器件/系统哪层验证）；
- fake 输出只用于结构性判断（几何/链路/门禁），永远不要用 fake
  的 cost 排序外推物理结论——那份 ρ=0.377 的档案就是为此立的。
