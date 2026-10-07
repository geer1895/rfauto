<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：pdn

> F-B.1 电源完整性（PI/PDN）AC 阻抗域确定性内核（research_expansion §F-B P1 离线段）。

| 字段 | 值 |
|---|---|
| 内核 ID | `pdn` |
| 主模块 | `src/rfauto/core/pdn.py`（`rfauto.core.pdn`） |
| 计算器注册表 | 未注册（AST 无 @register_calculator 装饰器——service 直调型内核，免 #231 注册表消费者三表同步） |
| KD-1 出处注册 | 3 条（kernel_file=src/rfauto/core/pdn.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

从 VRM、去耦电容、安装电感到平面腔模的电源分配网络阻抗闭式合成与去耦选型筛查——目标阻抗口径的工程快判内核，全场精算不在声明域。

模块自述（docstring 首行，机读）：F-B.1 电源完整性（PI/PDN）AC 阻抗域确定性内核（research_expansion §F-B P1 离线段）。

## 公式与口径

### 恒定目标阻抗（Smith 1999 口径）

（docstring 原文转写）

```latex
Z_{\mathrm{target}}=\frac{V_{\mathrm{ripple}}}{\Delta I}
```

出处：L. D. Smith et al., IEEE Trans. Adv. Packag. 22(3):284-291, 1999——KD-1 条目 pdn:<module>:01（source_doi 10.1109/6040.784476）。

docstring 逐字引文（防漂移钉）："恒定口径目标阻抗 Z_target = V_ripple / ΔI（Smith 1999 IEEE TAP 口径）"

### 频率依赖目标阻抗（Smith/Novak 分段包络）

（口径示意（非 docstring 原式，读代码为准））

```latex
Z_{\mathrm{target}}(f)=\begin{cases}Z_0, & f\le f_k\\Z_0\,f_k/f, & f>f_k\end{cases}\quad(\text{高频 }-20\,\mathrm{dB/dec})
```

出处：模块 docstring 模块面节（target_impedance_freq 行）；上式为分段形状的口径示意转写——实现以 src/rfauto/core/pdn.py:target_impedance_freq 为准。

docstring 逐字引文（防漂移钉）："（频率依赖分段包络，Smith/Novak 谱系：低频平坦+高频 −20dB/dec，拐点频率为参数）"

### 去耦电容单件阻抗（C+ESR+ESL）

（docstring 原文转写）

```latex
Z_{\mathrm{cap}}(\omega)=R_{\mathrm{ESR}}+j\Big(\omega L_{\mathrm{ESL}}-\frac{1}{\omega C}\Big)
```

出处：Kundert 去耦网络方法论（C+ESR+ESL 三件模型，反谐振峰机理）。

docstring 逐字引文（防漂移钉）："阻抗 Z=ESR+j(ωL−1/(ωC))；并联一律导纳求和"

### 整网合成（并联导纳求和）

（docstring 原文转写）

```latex
Y_{\mathrm{tot}}(\omega)=\sum_i\frac{1}{Z_i(\omega)},\qquad Z_{\mathrm{tot}}=\frac{1}{Y_{\mathrm{tot}}}
```

出处：模块 docstring 数值口径节（复数除法数值稳定；空网 Z=∞ 显式处理）。

docstring 逐字引文（防漂移钉）："整网合成：pdn_impedance_profile（VRM 与全部电容的并联导纳求和 Y=Σ1/Zᵢ）"

### 安装电感两贡献项（过孔对回路+径向扩张）

（docstring 原文转写）

```latex
L'_{\mathrm{via}}=\frac{\mu_0}{\pi}\,\mathrm{arcosh}\!\Big(\frac{s}{2r}\Big),\qquad L_{\mathrm{spread}}=\frac{\mu_0 h_d}{2\pi}\ln\frac{r_2}{r_1}
```

出处：Rosa/Grover 双线闭式 + Novak & Miller 平行板径向流扩张电感（Artech House 2007）——Archambeault 安装回路分解口径组装。

docstring 逐字引文（防漂移钉）："L'=μ0/π·arcosh(s/2r)" + "L_spread=μ0·h_d/(2π)·ln(r2/r1)"

### 矩形平面腔模频率（TM 闭式筛查）

（docstring 原文转写）

```latex
f_{mn}=\frac{c}{2\sqrt{\varepsilon_r}}\sqrt{\Big(\frac{m}{a}\Big)^2+\Big(\frac{n}{b}\Big)^2}
```

出处：矩形谐振腔 TM 闭式标准式（Pozar 腔体谐振器章同形口径；与 shield_cavity_mode 内核同源共享腔模闭式族）。

docstring 逐字引文（防漂移钉）："f_mn=c/(2√εr)·√((m/a)²+(n/b)²)"

### KD-1 出处注册（`src/rfauto/core/pdn.py`，knowledge/formula_provenance.yaml 过滤）

命中 **3** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| pdn:<module>:01 | <module> | source | 10.1109/6040.784476 | 10.1109/6040.784476；no. 3, pp. 284-291, Aug. 1999（doi 10.1109/6040.784476）；频率依赖目标；designers-guide.org/design/bypassing.pdf（2006）——C+ESR+ESL 三件模型、；"Inductance Calculations," 1946——L'=μ0/π·arcosh(s/2r)）按 Archambeault；Control, Kluwer，2011 印次：安装电感=过孔贡献+焊盘/扩张贡献）组装；Artech House 2007：L_spread=μ0·h_d/(2π)·ln(r2/r1)）。两者均为工程简化；- VRM 四元件模型：Sandler《Power Integrity》McGraw-Hill 2014 与 Smith 1999 |
| pdn:target_impedance_freq:01 | target_impedance_freq | pointer | — | — |
| pdn:vrm_model:01 | vrm_model | source | — | 出处：Sandler《Power Integrity》2014 / Smith 1999 的 VRM 宏模型谱系 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `pdn`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 安装电感两闭式均忽略有限长端部效应与过孔焊盘回流不对称——工程简化模型的量级筛查语义，非精算声明。
  - docstring 逐字引文："量级用于选型筛查非精算"
- 平面腔模 v1 只做频率闭式筛查，不做全场 TMM（docstring 模块面节同口径）。
  - docstring 逐字引文："v1 仅频率筛查"
- DC-bias 折减只有查表+线性插值；无曲线即如实标 no_derating，不虚构曲线（铁律 7）。
  - docstring 逐字引文："无曲线如实标 no_derating"
- decap 库 provenance 字段强制：首批条目一律 typical_engineering_value 标注；vendor 实测曲线入 dc_bias_curve 键并带出处（单条不合法即 ValueError 硬错）。
  - docstring 逐字引文："禁止虚构 vendor 实测数字"
- 空网显式返回 inf+0j，不静默吞除零（numpy 警告在函数内抑制）。
  - docstring 逐字引文："全频段无任何支路时 Y=0 → Z=∞ 显式处理"
- 贪心选型是确定性改善/成本比贪心；不凑解——超标即显式 infeasible。
  - docstring 逐字引文："全加完仍超标→显式 infeasible，不凑解"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/pdn.py:target_impedance`
- `src/rfauto/core/pdn.py:target_impedance_freq`
- `src/rfauto/core/pdn.py:decap_impedance`
- `src/rfauto/core/pdn.py:mount_inductance`
- `src/rfauto/core/pdn.py:vrm_model`
- `src/rfauto/core/pdn.py:plane_cavity_modes`
- `src/rfauto/core/pdn.py:mount_position_clearance`
- `src/rfauto/core/pdn.py:dc_bias_effective_c`
- `src/rfauto/core/pdn.py:pdn_impedance_profile`
- `src/rfauto/core/pdn.py:greedy_decap_select`
- `src/rfauto/core/pdn.py:load_decap_library`

src/rfauto/core/pdn.py 公开符号 **16** 个（AST 机读）：

`target_impedance`、`target_impedance_freq`、`decap_impedance`、`mount_inductance`、`VrmModel`、`vrm_model`、`CavityMode`、`plane_cavity_modes`、`ClearanceVerdict`、`mount_position_clearance`、`dc_bias_effective_c`、`DecapSpec`、`load_decap_library`、`pdn_impedance_profile`、`GreedyResult`、`greedy_decap_select`

消费面（service/adapters 引用扫描，机读）：

- service：`src/rfauto/service/pdn_service.py`
- adapters：`src/rfauto/adapters/kicad_power_pairs.py`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `研究扩充`（runs/ 证据面，gitignored，存在性不作测试断言）——引文："§F-B 第 4 节（先写后跑，#122）；本文件交付判据 1-5"

测试面（tests/unit 引用扫描，机读；合计 **249** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_kicad_power_pairs.py` | 41 |
| `tests/unit/test_microwave_heating.py` | 58 |
| `tests/unit/test_pdn.py` | 26 |
| `tests/unit/test_pdn_dc.py` | 19 |
| `tests/unit/test_pdn_service.py` | 36 |
| `tests/unit/test_pdn_tran.py` | 26 |
| `tests/unit/test_shield_cavity_mode.py` | 14 |
| `tests/unit/test_sso_ground_bounce.py` | 14 |
| `tests/unit/test_w4_d_pdn_vertical.py` | 15 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pce](pce.md)、[cascade](cascade.md)

