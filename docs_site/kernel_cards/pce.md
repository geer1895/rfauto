<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：pce

> D8 稀疏多项式混沌展开（PCE）：Sobol 系数直读 + worst-case + 设计中心化。

| 字段 | 值 |
|---|---|
| 内核 ID | `pce` |
| 主模块 | `src/rfauto/core/pce.py`（`rfauto.core.pce`） |
| 同族模块 | `src/rfauto/core/sparse_pce.py` |
| 计算器注册表 | 未注册（AST 无 @register_calculator 装饰器——service 直调型内核，免 #231 注册表消费者三表同步） |
| KD-1 出处注册 | 0 条（kernel_file=src/rfauto/core/pce.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

把响应面拟合成正交多项式混沌展开（纯 numpy 确定性），从展开系数直接读 Sobol 全局敏感度、worst-case 角与设计中心——代理模型的适用边界同样如实声明。

模块自述（docstring 首行，机读）：D8 稀疏多项式混沌展开（PCE）：Sobol 系数直读 + worst-case + 设计中心化。

## 公式与口径

### 一维正交归一基（Legendre/Hermite）

（docstring 原文转写）

```latex
\psi_n^{\mathrm{Leg}}(\xi)=\sqrt{2n+1}\,P_n(\xi),\qquad \psi_n^{\mathrm{Her}}(\xi)=\frac{He_n(\xi)}{\sqrt{n!}}
```

出处：E[psi_m psi_n]=delta_mn 归一口径（模块 docstring「机制」节）；多维基=各维基函数乘积，多指标 graded-lex 序。

docstring 逐字引文（防漂移钉）："Legendre（均匀输入）：psi_n(xi)=sqrt(2n+1)*P_n(xi)，xi∈[-1,1] 上"

### Sobol 指数系数直读（无需再采样）

（docstring 原文转写）

```latex
V=\sum_{\alpha\ne 0}c_\alpha^2,\qquad S_{1,i}=\frac{1}{V}\!\sum_{\alpha:\,\alpha_i>0,\,\alpha_{j\ne i}=0}c_\alpha^2,\qquad S_{\mathrm{T},i}=\frac{1}{V}\sum_{\alpha:\,\alpha_i>0}c_\alpha^2
```

出处：输入独立+基正交归一 ⇒ 系数平方和即该子空间方差贡献（较 Saltelli 采样省 1-2 量级——docstring「依据」节）。

docstring 逐字引文（防漂移钉）："V = sum_{alpha != 0} c_alpha^2；" + "ST_i = sum_{alpha: a_i>0} c_alpha^2 / V。"

### 稀疏回归（OMP 确定性路径）

（口径示意（非 docstring 原式，读代码为准））

```latex
\min_\theta \lVert y-\Psi\theta\rVert_2^2\ \ \text{s.t. } \mathrm{supp}(\theta)\text{ 由 OMP 路径给出}
```

出处：停止条件=残差 2 范数 ≤ tol 或非零项达 max_terms；上式为口径示意转写——实现以 src/rfauto/core/pce.py:omp_fit 为准。

docstring 逐字引文（防漂移钉）："OMP（正交匹配追踪，确定性并列取最小下标），常数项强制入选；"

### KD-1 出处注册（`src/rfauto/core/pce.py`，knowledge/formula_provenance.yaml 过滤）

命中 **0 条**——该模块 docstring 无「出处见/出处（」收集标记命中或未逐式登记。出处以模块 docstring 为单源（上方公式引文即逐字出自 docstring）；登记缺口如实呈现，属 XA-6 出处断链巡检门的巡检范围，不在本卡掩饰。

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `pce`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- Sobol 直读反映的是代理的方差分解——代理不准则指数不准（深谐振谷族先扫谷深再定口径，#370 族教训）。
  - docstring 逐字引文："PCE 是全局多项式代理；强不连续/多峰/窄带谐振（如 patch 谷深）收敛慢，"
- core 叶子只依赖 numpy；与 sensitivity/Saltelli 的互证在测试层做（#118 双路径裁判），不在内核内互调。
  - docstring 逐字引文："本模块不读 runs/、不联网、不依赖 scipy/optuna（core 零依赖叶子约束）"
- worst-case 两口径：角点穷举（确定性）与 PCE 上多起点 确定性 pattern search（可命中内部极值）。
  - docstring 逐字引文："corner_worst_case 穷举容差角点（均匀=low/high，正态=mean±kσ）；"
- 验收口径=patch 公差问题 PCE-Sobol vs 既有 Saltelli 互证 ±10%（续跑计划 §10.15 预声明）。
  - docstring 逐字引文："Saltelli 互证 ±10%（§10.15）"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/pce.py:fit_pce`
- `src/rfauto/core/pce.py:pce_sobol`
- `src/rfauto/core/pce.py:worst_case`
- `src/rfauto/core/pce.py:corner_worst_case`
- `src/rfauto/core/pce.py:design_centering`
- `src/rfauto/core/pce.py:tolerance_yield`
- `src/rfauto/core/sparse_pce.py:fit_sparse_pce`
- `src/rfauto/core/sparse_pce.py:sparse_pce_sobol`
- `src/rfauto/core/sparse_pce.py:ishigami_sobol_analytic`

src/rfauto/core/pce.py 公开符号 **13** 个（AST 机读）：

`legendre_orthonormal`、`hermite_orthonormal`、`orthonormal_1d`、`multi_indices`、`build_design_matrix`、`omp_fit`、`PCEModel`、`fit_pce`、`pce_sobol`、`corner_worst_case`、`worst_case`、`tolerance_yield`、`design_centering`

src/rfauto/core/sparse_pce.py 公开符号 **7** 个（AST 机读）：

`hyperbolic_indices`、`sample_canonical`、`SparsePCEModel`、`fit_sparse_pce`、`sparse_pce_sobol`、`ishigami`、`ishigami_sobol_analytic`

消费面（service/adapters 引用扫描，机读）：

- service：`src/rfauto/service/robustness_service.py`
- service：`src/rfauto/service/uq_service.py`
- service：`src/rfauto/service/sparse_pce_service.py`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `docs/续跑计划`（runs/ 证据面，gitignored，存在性不作测试断言）——引文："docs/续跑计划.md §10.4 D8：稀疏 PCE（ChaosPy/OpenTURNS）"

测试面（tests/unit 引用扫描，机读；合计 **115** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_pce.py` | 24 |
| `tests/unit/test_pcell_cli.py` | 15 |
| `tests/unit/test_pcell_dsl.py` | 26 |
| `tests/unit/test_rf_guard.py` | 29 |
| `tests/unit/test_sparse_pce.py` | 21 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[cascade](cascade.md)

