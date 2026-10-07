<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：cascade

> DP-5 系统级预算引擎 + 混频杂散搜索（纯函数，零 IO，微秒级确定性内核）。

| 字段 | 值 |
|---|---|
| 内核 ID | `cascade` |
| 主模块 | `src/rfauto/core/cascade.py`（`rfauto.core.cascade`） |
| 计算器注册表 | 未注册（AST 无 @register_calculator 装饰器——service 直调型内核，免 #231 注册表消费者三表同步） |
| KD-1 出处注册 | 0 条（kernel_file=src/rfauto/core/cascade.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

链路预算级联闭式（Friis 噪声/IIP3/P1dB/噪声底/SFDR/灵敏度）+ 混频杂散全阶枚举——纯 math 确定性内核，规格书笔误在动工前勘误并钉解析恒等式锚。

模块自述（docstring 首行，机读）：DP-5 系统级预算引擎 + 混频杂散搜索（纯函数，零 IO，微秒级确定性内核）。

## 公式与口径

### Friis 级联噪声（功率域线性）

（docstring 原文转写）

```latex
F_{\mathrm{tot}}=F_1+\frac{F_2-1}{G_1}+\frac{F_3-1}{G_1G_2}+\cdots
```

出处：模块 docstring「公式口径（§0，含规格书勘误 1 处）」节。

docstring 逐字引文（防漂移钉）："Friis 噪声级联（功率域线性）：F_tot = F₁ + (F₂−1)/G₁ + (F₃−1)/(G₁G₂) + …"

### IIP3 级联（功率域求和式；规格书字面式勘误）

（docstring 原文转写）

```latex
\frac{1}{\mathrm{IIP3}_{\mathrm{tot}}}=\sum_i\frac{G_{\mathrm{pre},i}}{\mathrm{IIP3}_i},\qquad \mathrm{OIP3}_{\mathrm{tot}}=\mathrm{IIP3}_{\mathrm{tot}}+G_{\mathrm{tot}}
```

出处：教科书口径（Pozar 级联非线性；core/budget.py LinkBudget 同口径且已有单测）——规格书 §2 字面式增益落分母系笔误；criteria.md §0 解析恒等式锚（IIP3_tot ≡ −7.0 dBm）。

docstring 逐字引文（防漂移钉）："1/IIP3_tot = Σᵢ G_pre,i / IIP3ᵢ" + "OIP3_tot = IIP3_tot + G_tot（恒等式）"

### 噪声底 / 灵敏度 / SFDR

（docstring 原文转写）

```latex
N_{\mathrm{floor}}=10\log_{10}(k_B T\,10^{3})+10\log_{10}B+\mathrm{NF}_{\mathrm{tot}}\ [\mathrm{dBm}],\quad \mathrm{SFDR}=\tfrac{2}{3}\big(\mathrm{IIP3}_{\mathrm{tot}}-N_{\mathrm{floor}}\big),\quad P_{\mathrm{sens}}=N_{\mathrm{floor}}+\mathrm{SNR}_{\min}
```

出处：k_B=1.380649e-23（SI 精确值）、T 缺省 290 K；带宽解析顺序 显式入参 > 末级 stage bw_hz > 显式报错（docstring §0）。

docstring 逐字引文（防漂移钉）："SFDR = (2/3)·(IIP3_tot − N_floor)；灵敏度 P_sens = N_floor + SNR_min；"

### P1dB 级联（工程惯例口径，非教科书闭式）

（docstring 原文转写）

```latex
\frac{1}{P1\mathrm{dB}_{\mathrm{out}}}=\sum_i\frac{1}{\mathrm{OP1dB}_i+G_{\mathrm{after},i}}
```

出处：与级联 IP3 同形的饱和功率叠加工程惯例；p1db_dbm 约定=该级输出 1dB 压缩点。

docstring 逐字引文（防漂移钉）："1/P1dB_out = Σᵢ 1/(OP1dBᵢ + G_after,i)"

### 混频杂散全阶枚举

（docstring 原文转写）

```latex
f_{\mathrm{spur}}=\big|m f_{\mathrm{RF}}\pm n f_{\mathrm{LO}}\big|
```

出处：带内判据=矩形近似卷积；危险等级=阶数反比（≤3 high、≤5 medium、其余 low）——docstring spur search 节。

docstring 逐字引文（防漂移钉）："f_spur = |m·f_RF ± n·f_LO| 全阶枚举（缺省 m+n ≤ max_order=7）；"

### KD-1 出处注册（`src/rfauto/core/cascade.py`，knowledge/formula_provenance.yaml 过滤）

命中 **0 条**——该模块 docstring 无「出处见/出处（」收集标记命中或未逐式登记。出处以模块 docstring 为单源（上方公式引文即逐字出自 docstring）；登记缺口如实呈现，属 XA-6 出处断链巡检门的巡检范围，不在本卡掩饰。

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `cascade`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- P1dB 级联是工程惯例叠加式，如实标注经验口径——不冒充闭式推导。
  - docstring 逐字引文："P1dB 级联为**经验口径**（无教科书闭式，如实标注）"
- 杂散搜索只报频率落带与危险等级；电平需器件特性，显式 out-of-scope。
  - docstring 逐字引文："只报频率落带不报电平（幅度需器件特性，out-of-scope）"
- 无源级缺省 NF=插损（T0 口径）；amp/mixer 的 nf_db 缺失显式报错——skrf 实取插损的解析在 service 层（core 零 IO）。
  - docstring 逐字引文："无源级（filter/atten/cable）缺省 NF = −gain_db（T0 口径无源损耗 NF=插损）；"
- 规格书字面式与教科书推导相反（后级 IIP3 折算到链路输入应除以前级增益）——本模块按教科书口径实现，勘误与解析锚在档。
  - docstring 逐字引文："规格书 §2 字面写作 ``1/(IIP3ᵢ·Π_{j<i}G_j)``（增益落分母）"
- 纯 math 微秒级确定性内核；不 import numpy/scipy/skrf、零 IO。
  - docstring 逐字引文："零 IO、不 import numpy/scipy/skrf（纯 math）——铁律 7 合规"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/cascade.py:cascade_budget`
- `src/rfauto/core/cascade.py:spur_search`
- `src/rfauto/core/cascade.py:if_plan_sweep`
- `src/rfauto/core/cascade.py:cascade_ipn_merge`
- `src/rfauto/core/cascade.py:cascade_compression_scan`
- `src/rfauto/core/cascade.py:cascade_am_pm`
- `src/rfauto/core/cascade.py:cascade_nonlinear_scan`
- `src/rfauto/core/cascade.py:p1db_from_oip3`

src/rfauto/core/cascade.py 公开符号 **12** 个（AST 机读）：

`cascade_budget`、`spur_search`、`if_plan_sweep`、`ipn_merge_linear`、`cascade_ipn_merge`、`im_products_extrapolate`、`p1db_from_oip3`、`cascade_compression_scan`、`am_am_pm_third_order`、`cascade_am_pm`、`NonlinearCascadeResult`、`cascade_nonlinear_scan`

消费面（service/adapters 引用扫描，机读）：

- service：`src/rfauto/service/cascade_service.py`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `规格深案`（runs/ 证据面，gitignored，存在性不作测试断言）——引文："规格：规格深案 §DP-5；判据书："
- `runs/df6_dp5cascade/criteria.md`（runs/ 证据面，gitignored，存在性不作测试断言）——引文："runs/df6_dp5cascade/criteria.md（回收钉锚值与来源）。"

测试面（tests/unit 引用扫描，机读；合计 **122** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_budget_iip2.py` | 10 |
| `tests/unit/test_cascade.py` | 47 |
| `tests/unit/test_cascade_nonlinear.py` | 38 |
| `tests/unit/test_docs_doctest.py` | 1 |
| `tests/unit/test_noise_correlation.py` | 26 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)

