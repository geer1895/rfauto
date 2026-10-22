<!-- PR-10 文档站同步副本：源=docs/explanation/template-param-semantics.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 解释：模板参数语义——同名参数为什么必须逐通道对表

> 这是一篇 explanation（解释文）：回答"为什么 rfauto 坚持每个模板
> 声明 param_semantics、公式层只认 physics_roles 不认参数名、新通道
> 接入为什么要跑跨通道语义断言"。操作面互补：
> docs/tutorials/extending-rfauto_en.md（四条扩展路径）、
> docs/how-to/add-new-solver-engine.md（新引擎接入）、
> docs/how-to/add-new-calc-key.md（新计算器键）、
> docs/explanation/deterministic-kernel.md（确定性内核）。

## 一次惨案：两个"都对"的通道拼出两个器件

#154 教训（wilkinson 功分器）：同两个几何参数名 `series_w` /
`shunt_w`，在配方/HFSS 插件/fake/openEMS 各通道**各自"看着对"**——
单通道验收全绿，跨保真对比时却是**两个不同的器件家族**：一侧的
series 是 70.7Ω 阻抗臂宽，另一侧的 series 是 50Ω 馈线宽，语义恰好
相反。参数名是模型作者随口起的，**名字相同不等于物理相同**；反过来
名字不同也可能物理相同（`arm_len` 与 `arm_len_mm`）。

跨保真对不上号时，第一嫌疑不是"哪个引擎错了"，而是**同名参数在
某个通道里换了物理**。rfauto 为此建了三层防线，层层有实测。

## 第一层：物理角色（physics_roles）——公式只认角色不认名字

`core/physics_roles.py`（v0 起就是代理校准的地基）维护一张
**角色候选表** `ROLE_CANDIDATES`（实测 8 个角色，2026-10-19）：
`resonator_length_mm / impedance_line_width_mm / shunt_line_width_mm /
feed_offset_mm / patch_width_mm / line_width_mm / line_length_mm /
gap_width_mm`。每个角色映射到一组候选参数名（按优先级），公式与
代理层只消费角色：

```python
from rfauto.core.physics_roles import resolve_role

arm_len = resolve_role("resonator_length_mm", self._variables)
# wilkinson 命中 arm_len_mm；patch 模板命中 patch_len_mm——同一公式
# 不改一行就能跨模板工作
```

两个 fail-loud 都是实测过的（当场触发的原文报错，2026-10-19）：

- **未知角色名直接抛 ValueError**——拼写错静默回退 default 会把
  错值带进公式链且无痕；自定义模型显式传 `candidates=` 是白名单
  出口；
- **量纲后缀收紧到 mm**——旧实现剥 `m` 后缀把 `"20m"`（米）静默读
  成 20.0（千倍量纲错），现在 `"20m"` 抛 ValueError、`"2.5cm"` 同面
  收紧，无单位杂串仍返回 None 由调用方回退。

消费面实测：`resolve_role` 在 `adapters/fake_adapter.py` 中 95 处
调用（fake 的全部解析模型走角色取参）、`service/aging_service.py`
等；#154 之后 feed_offset 家族完成单源化（单贴片 feed_offset_mm=
自贴片中心偏移、openEMS 官方 x=−off 同基，综合/fake/HFSS 三面统一
——2026-10-03，表内注释即当时裁决的原文）。

## 第二层：param_semantics 声明——模板元数据的合同

光有角色表不够：角色表回答"公式要什么"，还要有人回答"这个模板的
每个参数**在本通道**充当什么"。两层声明、一个消费者：

- `TEMPLATE_META`（`adapters/oe_templates/registry.py`）每个模板的
  `param_semantics` 字段——**实测 72/72 模板全部声明**（2026-10-19），
  且 `docs/templates/<t>/meta.yaml` 逐键同步（单测
  test_template_meta_consistency 钉住）。wilkinson 的声明原文：
  `series_w_mm=70.7Ω 臂宽（窄），shunt_w_mm=50Ω 馈线宽（宽），
  arm_len_mm=λ/4 臂长——对齐 recipe/HFSS/fake 口径（2026-09-04
  统一）`——#154 的修复就是把这句语义写死成数据；
- 适配器侧同款：`param_semantics` 是 `EMSolverAdapter` 骨架自带的
  声明槽（scaffold_adapter 生成；comsol/ngsolve 适配器以
  ClassVar 落实），HFSS 插件另有 `hfss_var_map`（参数名→HFSS 设计
  变量名显式映射）——变量名不一致必须显式翻译，不许靠运气重名。

## 第三层：check_param_semantics——配方级的跨通道断言

三层防线的闸门在 `service/adapter_kit.check_param_semantics(recipe)`
（#154 工具化）：A. 模板 param_semantics 覆盖 optimization.params
全部参数；B. 插件 hfss_var_map 覆盖到位；C. 各通道声明的物理角色
互不冲突（角色词表权威 = ROLE_CANDIDATES）。实测（2026-10-19，
对 recipes/wilkinson_pd_v1.yaml）：

```json
{"ok": true, "recipe": "recipes\\wilkinson_pd_v1.yaml",
 "model": "wilkinson_power_divider", "template": "wilkinson",
 "n_opt_params": 3, "semantic_channels": ["openems_template"],
 "n_semantic_roles": 3, "issues": [],
 "note": "同名参数跨通道语义相反 = 两个器件家族（#154）；新增适配器/模板时先补 param_semantics 再跑采样"}
```

工具 docstring 里那句 note 就是本文的全部论点：**单通道各自"看着
对"，跨保真就是两个器件家族**——所以接入新适配器/新模板的流程是
先补语义声明、再跑断言、然后才轮到数值验证。

## 为什么这套东西长在文档与测试里，而不是"大家小心"

三个结构性理由：

1. **参数名空间不受控**。模板由多人/多批次贡献，参数名没有全局
   唯一性约束；靠约定记不住 72 个模板 × 每模板十几个参数的语义，
   数据化的声明才可被机器核对（声明进 TEMPLATE_META/meta.yaml，
   一致性有单测钉）。
2. **失败模式是静默的**。语义错配不报错——几何照画、仿真照跑、
   指标照出，只是"最优解"物理上是另一个器件。这种错配比崩溃贵
   得多（#154 两轮真跑白做的代价），必须用预声明+断言把它变成
   显式失败。
3. **公式复用的前提是语义稳定**。确定性内核（见
   docs/explanation/deterministic-kernel.md）的价值在"同一公式跨
   模板可复用且逐位可复现"——角色层把"名字不稳定"挡在公式之外，
   公式才只需要写一遍。

## 给贡献者的推论

- 给模板加参数：TEMPLATE_META 的 params 与 param_semantics 同笔补
  声明（一句话语义+口径+对齐基准），meta.yaml 同步，别让声明欠账；
- 接新通道：先逐参数对语义（走 ROLE_CANDIDATES 或显式 candidates），
  再跑 check_param_semantics——文档"看着对"不算数（#154 原文教训，
  how-to/add-new-solver-engine.md 第 20 行同款红线）；
- 写公式/代理消费几何：一律 `resolve_role`，禁止直接按参数名取值
  ——你的下一个消费者模板的参数名不会跟你商量；
- 单位一律 mm；`parse_length` 对 `m/cm` 后缀 fail-loud 是特性不是
  麻烦——千倍量纲错曾经无痕进入几何。
