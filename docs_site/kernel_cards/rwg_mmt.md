<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：rwg_mmt

> 自研 RWG/SIW 解析模基 MMT（GSM）求解器（DP-1 P1 内核）。

| 字段 | 值 |
|---|---|
| 内核 ID | `rwg_mmt` |
| 主模块 | `src/rfauto/core/rwg_mmt.py`（`rfauto.core.rwg_mmt`） |
| 计算器注册表 | 未注册（AST 无 @register_calculator 装饰器——service 直调型内核，免 #231 注册表消费者三表同步） |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/rwg_mmt.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

在矩形波导 TE_m0 解析模基上用模匹配（GSM）闭式链解 H 面阶梯/膜片/均匀段的过传响应——全波求解之前的解析快速通道，带自检锚、规格书勘误留痕与近截止诚实降级。

模块自述（docstring 首行，机读）：自研 RWG/SIW 解析模基 MMT（GSM）求解器（DP-1 P1 内核）。

## 公式与口径

### TE_m0 模基与色散（功率归一）

（docstring 原文转写）

```latex
k_c=\frac{m\pi}{a},\quad f_c=\frac{c\,m}{2a\sqrt{\varepsilon_r}},\quad \beta=\sqrt{k^2-k_c^2},\quad Z^{\mathrm{TE}}=\frac{\omega\mu}{\beta}
```

出处：Pozar §3 场分量式口径（模块 docstring「数学口径」节，#1b 先验模型，推导在档）。

docstring 逐字引文（防漂移钉）："k_c=mπ/a、fc=c·m/(2a√εr)、β=√(k²−k_c²)（k=k0√εr）；Z^TE=ωμ/β"

### 结面 GSM（功率波归一，规格勘误后口径）

（docstring 原文转写）

```latex
\hat C=D_1^{-1}H^{\mathsf T}D_2,\quad M=\hat C\hat C^{\mathsf T},\quad N=\hat C^{\mathsf T}\hat C;
```

出处：规格 规格深案 DP-1 §2.3（投影域勘误后变体）；两侧同时激励消元，纯转置无共轭。

docstring 逐字引文（防漂移钉）："**Ĉ=D1⁻¹·Hᵀ·D2**，H_nm=" + "S11=(M−I)(M+I)⁻¹、S21=2Ĉᵀ(I+M)⁻¹、S12=2(I+M)⁻¹Ĉ、S22=(I−N)(I+N)⁻¹"

### 阶梯耦合积分（半角稳定形式；规格书 §2.2 原式勘误）

（docstring 原文转写）

```latex
\int_{x_0}^{x_0+w}\!\cos(\pi\Delta x)\,dx=w\cos(\pi\Delta x_c)\,\mathrm{sinc}\!\big(\pi\Delta w/2/\pi\big),\quad x_c=x_0+\tfrac{w}{2}
```

出处：Wexler 1967 / Masterman-Clarricoats 1971 矩形闭式特例；cos-分子显式式系规格书笔误（#1b 动工前裁决），半角形式Δ→0 极限自动精确。

docstring 逐字引文（防漂移钉）："∫_{x0}^{x0+w} cos(πΔx)dx = w·cos(πΔ·x_c)·sinc(πΔw/2/π)"

### 损耗闭式（TE10 微扰口径）

（docstring 原文转写）

```latex
\alpha_c=\frac{R_s}{b\,\eta\,\sqrt{1-(f_c/f)^2}}\Big(1+\tfrac{2b}{a}\tfrac{f_c^2}{f^2}\Big),\qquad \alpha_d=\frac{k^2\tan\delta}{2\beta}
```

出处：规格 §2.6；作为均匀衰减因子作用于段传输指数（高阶倏逝模微扰损耗可忽略——已声明近似）。

docstring 逐字引文（防漂移钉）："损耗闭式（规格 §2.6，TE10 微扰口径）：α_c=Rs/(b·η·√(1−(fc/f)²))·" + "(1+2b/a·(fc/f)²)、α_d=k²·tanδ/(2β)"

### KD-1 出处注册（`src/rfauto/core/rwg_mmt.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| rwg_mmt:<module>:01 | <module> | source | — | 出处：Wexler 1967 / Masterman-Clarricoats 1971 / Eleftheriades 1994（×2 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `rwg_mmt`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 模基是 TE_m0 单族、H 面结构首例——E 面阶梯/多族模不在本内核声明域内。
  - docstring 逐字引文："TE_{m0} 单族，H 面首例域"
- 距截止 <5% 的频点处于近截止病态带，显式标 undetermined 不外推（_NEAR_CUTOFF_FRAC=0.05）。
  - docstring 逐字引文："# 近截止病态带半宽（规格 §2.5 风险⑤：<5% 频点显式标 undetermined 不外推）"
- 规格书 cos-分子显式式代入平凡自检得 0 而积分真值 a/2，属笔误——实现用数学等价的半角稳定形式，勘误留痕在档。
  - docstring 逐字引文："**规格书 §2.2 原式勘误（#1b，动工前裁决）**"
- 自检锚族：同波导恒等、单模台阶 Γ 闭式一致、宽口径膜片对 Marcuvitz 一阶旁证——解析可信度的来源先于真机仲裁。
  - docstring 逐字引文："自检锚：同波导 H=I→S11=S22=0、S21=I"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/rwg_mmt.py:mode_basis`
- `src/rfauto/core/rwg_mmt.py:junction_gsm`
- `src/rfauto/core/rwg_mmt.py:section_gsm`
- `src/rfauto/core/rwg_mmt.py:gsm_cascade`
- `src/rfauto/core/rwg_mmt.py:solve_chain`
- `src/rfauto/core/rwg_mmt.py:inductive_post_susceptance`
- `src/rfauto/core/rwg_mmt.py:resonant_window_susceptance`
- `src/rfauto/core/rwg_mmt.py:g1_systematic_bias_check`

src/rfauto/core/rwg_mmt.py 公开符号 **30** 个（AST 机读）：

`Waveguide`、`ModeBasis`、`mode_basis`、`alpha_c_te10`、`alpha_d_te10`、`overlap_1d`、`overlap_sin_sin_matrix`、`overlap_sin_cos_matrix`、`Gsm`、`aperture_h_matrix`、`junction_gsm`、`section_gsm`、`gsm_cascade`、`gsm_flip`、`gsm_to_2x2`、`shunt_admittance_from_s11`、`renormalize_2port`、`UniformSection`、`HStepJunction`、`InductiveIris`、`ModePolicy`、`SolveResult`、`mode_counts`、`solve_chain`、`G1TriggerVerdict`、`g1_systematic_bias_check`、`RefinementSlot`、`iris_refinement_comparison`、`inductive_post_susceptance`、`resonant_window_susceptance`

消费面（service/adapters 引用扫描，机读）：

- service：`src/rfauto/service/mmt_service.py`
- adapters：`src/rfauto/adapters/mmt_adapter.py`

## 锚与测试入口

analytic-anchor（knowledge/anchors.yaml 机读命中）：

| anchor_id | quantity |
|---|---|
| `mmt.inductive_post_b.hfss-v1` | inductive_post_b_dev_pct |
| `mmt.resonant_window_fres.hfss-v1` | resonant_window_f_res_dev_pct |

判据书/规格指针（docstring 逐字引文钉）：

- `规格深案`（runs/ 证据面，gitignored，存在性不作测试断言）——引文："规格 = 规格深案 DP-1 §2；"
- `runs/df6_dp1mmt/criteria.md`（runs/ 证据面，gitignored，存在性不作测试断言）——引文："判据预声明 = runs/df6_dp1mmt/criteria.md（先写后跑，#122）。"

测试面（tests/unit 引用扫描，机读；合计 **171** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_mmt_adapter.py` | 26 |
| `tests/unit/test_rw_tables.py` | 28 |
| `tests/unit/test_rwg_mmt.py` | 26 |
| `tests/unit/test_rwg_mmt_expansion.py` | 28 |
| `tests/unit/test_rwg_mmt_refinement.py` | 21 |
| `tests/unit/test_rwg_mmt_symmetry.py` | 14 |
| `tests/unit/test_w4_b_p14_rw_panel.py` | 15 |
| `tests/unit/test_w4_b_p5_horn.py` | 13 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)

