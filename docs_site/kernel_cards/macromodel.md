<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：macromodel

> D13 S 参数宏模型内核（向量拟合 + 无源性 + SPICE 导出 + FSV 保真裁判）。

| 字段 | 值 |
|---|---|
| 内核 ID | `macromodel` |
| 主模块 | `src/rfauto/core/macromodel.py`（`rfauto.core.macromodel`） |
| 计算器注册表 | 未注册（AST 无 @register_calculator 装饰器——service 直调型内核，免 #231 注册表消费者三表同步） |
| KD-1 出处注册 | 0 条（kernel_file=src/rfauto/core/macromodel.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

把频域 S 参数档案变成电路仿真器可直接挂载的有理极点-留数宏模型，并用相互独立的裁判（FSV 保真、带内 SVD 无源性、SPICE 回放自检）回答“这个模型还能不能信”。

模块自述（docstring 首行，机读）：D13 S 参数宏模型内核（向量拟合 + 无源性 + SPICE 导出 + FSV 保真裁判）。

## 公式与口径

### 向量拟合有理模型（skrf VectorFitting，Gustavsen 谱系）

（docstring 原文转写）

```latex
S_{ij}(s)=\sum_{n=1}^{N}\frac{c_{ij,n}}{s-p_n}+d_{ij}+s\,e_{ij}
```

出处：skrf 2.1.0 ``inspect.signature`` 实测口径；确定性（固定阶数、无随机初值）——模块 docstring「外部算法（不自造）」节。

docstring 逐字引文（防漂移钉）："有理拟合全链使用 skrf 2.1.0 自带 ``skrf.vectorFitting.VectorFitting``"

### 拟合 RMS（本仓主口径，逐响应+逐频点归一）

（docstring 原文转写）

```latex
\mathrm{rms}=\sqrt{\mathrm{mean}_{i,j,k}\,\left|S_{ij}(f_k)-\hat S_{ij}(f_k)\right|^2},\quad\mathrm{rms}_{\mathrm{dB}}=20\log_{10}(\mathrm{rms})
```

出处：模块 docstring「数值口径」节；阈值缺省 -40 dB；skrf get_rms_error 只作诊断旁证另存溯源。

docstring 逐字引文（防漂移钉）："``rms``：``sqrt(mean_{i,j,k} |S_ij(f_k) - Sfit_ij(f_k)|^2)``（逐响应 + 逐频点"

### 无源性带内直判（独立于 skrf 半尺寸测试）

（docstring 原文转写）

```latex
\sigma_{\max}\!\big(\mathbf S(f)\big)\le 1,\quad \forall f\in[f_{\min},f_{\max}]
```

出处：模块 docstring「无源性口径」节——无源化只要求模型有效频带内成立；passivity_enforce 仅带内违规时触发。

docstring 逐字引文（防漂移钉）："直接对模型 S 矩阵做 SVD 取最大奇异值（``sigma_max_in_band``）"

### FSV 保真裁判（D12 内核，IEEE 1597.1）

（docstring 原文转写）

```latex
\mathrm{GDM}\le\mathrm{Good}\ (\text{等级下标}\le 2)
```

出处：core/fsv.py（IEEE 1597.1 独立实现）——模块 docstring「裁判设计（不自证）」节。

docstring 逐字引文（防漂移钉）："目标 GDM ≤ Good（等级下标 ≤ 2）"

### KD-1 出处注册（`src/rfauto/core/macromodel.py`，knowledge/formula_provenance.yaml 过滤）

命中 **0 条**——该模块 docstring 无「出处见/出处（」收集标记命中或未逐式登记。出处以模块 docstring 为单源（上方公式引文即逐字出自 docstring）；登记缺口如实呈现，属 XA-6 出处断链巡检门的巡检范围，不在本卡掩饰。

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `macromodel`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 内置纯 Python 复数 MNA 求解器只证明导出网表在标准 SPICE 元素语义下重现模型；不得把 spice_replay.status=='ok' 读成第三方 SPICE 仿真通过——ngspice .AC 对拍在 adapters 层（core 禁 import adapters）。
  - docstring 逐字引文："SPICE 回放是"回放自检"，不是第三方 SPICE 等价验证"
- 第三方交叉验证是缺工具时 best-effort 跳过（#139 精神），不炸主链、不假装验证过。
  - docstring 逐字引文："``fit_macromodel`` 主链**不缺省依赖 ngspice**"
- 全频轴（含外推）判违规会把数值模型外推段的伪违规当真；本模块同时报告全轴与带内结果，以带内直判为无源性结论。
  - docstring 逐字引文："物理上无源化只要求在**模型有效频带**"
- 可能改不动带内违规、也可能大幅劣化带内精度——enforce 前/后 RMS 与 SVD 同时返回，不隐藏劣化。
  - docstring 逐字引文："``passivity_enforce`` 是 skrf 的启发式迭代"
- 极窄违规带可能被漏检；skrf 半尺寸测试的解析频段边界同时给出。
  - docstring 逐字引文："带内直判只在 ``passivity_samples`` 个密集采样点上做 SVD"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/macromodel.py:fit_macromodel`
- `src/rfauto/core/macromodel.py:model_response`
- `src/rfauto/core/macromodel.py:replay_spice_subcircuit_s`
- `src/rfauto/core/macromodel.py:compare_s_matrices`
- `src/rfauto/core/macromodel.py:request_from_touchstone`
- `src/rfauto/core/macromodel.py:validate_spice_subcircuit`

src/rfauto/core/macromodel.py 公开符号 **11** 个（AST 机读）：

`MacromodelError`、`MacromodelInputError`、`MacromodelFitError`、`model_response`、`validate_spice_subcircuit`、`replay_spice_subcircuit_s`、`replay_spice_ac_response`、`spice_subcircuit_port_info`、`compare_s_matrices`、`request_from_touchstone`、`fit_macromodel`

消费面（service/adapters 引用扫描，机读）：

- service：`src/rfauto/service/lake_compact_service.py`
- adapters：`src/rfauto/adapters/spice_netlist.py`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `docs/续跑计划`（runs/ 证据面，gitignored，存在性不作测试断言）——引文："任务来源：续跑计划 §10.3 D13 / §10.19 第 2 条。"

测试面（tests/unit 引用扫描，机读；合计 **86** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_macromodel.py` | 15 |
| `tests/unit/test_macromodel_replay.py` | 43 |
| `tests/unit/test_macromodel_xval.py` | 10 |
| `tests/unit/test_w3_a_lake_compact.py` | 18 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)

