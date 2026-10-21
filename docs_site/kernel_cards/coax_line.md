<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：coax_line

> 标准圆同轴传输线通用件族（架构批 A2-C 席域 1，R7 第二梯队 T1）。

| 字段 | 值 |
|---|---|
| 内核 ID | `coax_line` |
| 主模块 | `src/rfauto/core/calc_families/coax_line.py`（`rfauto.core.calc_families.coax_line`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 2 条（kernel_file=src/rfauto/core/calc_families/coax_line.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

标准圆同轴传输线通用件：TEM 特性阻抗双向解（分析/综合/ratio）、导体+介质行波衰减分解与线 Q 场积分路线互证、内导体表面场强功率容量与 30Ω/76.7Ω 经典最优比、截止波导衰减器倏逝模——与 combline 谐振腔面语义防撞。

模块自述（docstring 首行，机读）：标准圆同轴传输线通用件族（架构批 A2-C 席域 1，R7 第二梯队 T1）。

## 公式与口径

### TEM 特性阻抗精确闭式（分析/综合双向）

（docstring 原文转写）

```latex
Z_0=\frac{60}{\sqrt{\varepsilon_r}}\ln\frac{b}{a},\quad b/a=\exp\!\big(Z_0\sqrt{\varepsilon_r}/60\big)
```

出处：模块 docstring（Pozar §2.2 同轴线；60=工程惯例记号、精确常数 η0/2π=59.9585——损耗/Q 链按精确常数、阻抗面按惯例 60，记号差 ~0.07% 如实注记；L'·C'=με 恒等测试钉）。

docstring 逐字引文（防漂移钉）："Z0 = (60/√εr)·ln(b/a) Ω（非磁性；a=内导体半径、b=外导体内半径；" + "单位长度电容/电感：C' = 2πε/ln(b/a)（ε=ε0εr）、L' = (μ/2π)·ln(b/a)，"

### 行波衰减分解（导体趋肤+介质）

（docstring 原文转写）

```latex
\alpha_c=\frac{R_s(1/a+1/b)}{4\pi Z_0},\quad\alpha_d=\frac{\beta\tan\delta}{2},\quad\alpha_{dB/m}=8.686(\alpha_c+\alpha_d)
```

出处：模块 docstring（Pozar §2.7/Ramo-Whinnery-Van Duzer；线 Q=β/(2α) 与场积分路线解析同解，跨键测试互证 ≤1e-12；αc∝√f、αc∝1/√σ 标度恒等测试钉）。

docstring 逐字引文（防漂移钉）："αc = Rs·(1/a + 1/b)/(4π·Z0)   [Np/m]" + "αd = (β·tanδ)/2 = π·f·√(εr·μr)·tanδ/c₀   [Np/m]"

### 峰值功率容量（内导体表面场强上限）

（docstring 原文转写）

```latex
V_{\max}=E_{br}\,a\ln\frac{b}{a},\quadP_{\max}=\frac{V_{\max}^2}{2Z_0}=\frac{E_{br}^2 a^2 \ln(b/a)\sqrt{\varepsilon_r}}{120}
```

出处：模块 docstring（TEM 场分布 E(ρ)=V/(ρ·ln(b/a))；衰减最小 b/a≈3.59112 → Z0≈76.7/√εr——两最优比常数作输出字段与测试锚）。

docstring 逐字引文（防漂移钉）："P_max = V_max²/(2·Z0) = E_br²·a²·ln(b/a)·√εr/120  [W，峰值/匹配线]" + "经典最优比（外径 b 固定）：功率容量最大 b/a=√e → Z0=30/√εr；"

### 截止波导衰减器（TE11 以下倏逝模）

（docstring 原文转写）

```latex
\alpha=k_c\sqrt{1-(f/f_c)^2},\quadk_c\approx\frac{2}{a+b}
```

出处：模块 docstring 出处节（保角映射截止常数 kc≈2/(a+b) 与 TE11 截止同式；f≥f_c 单模 TEM 假设失效如实 note）。

docstring 逐字引文（防漂移钉）："- coax_line_cutoff_attenuator：Pozar §3 波导一般理论倏逝模"

### KD-1 出处注册（`src/rfauto/core/calc_families/coax_line.py`，knowledge/formula_provenance.yaml 过滤）

命中 **2** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/coax_line:<module>:01 | <module> | pointer | — | — |
| calc_families/coax_line:<module>:02 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `coax_line`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 语义防撞（R7 三重搜索证据）：combline=同轴谐振腔（λ/2·λ/4 腔长综合/腔 Q 驻波口径）、SICL/rf_trace_geometry=异形/印制截面——本族只做标准圆同轴行波通用件（阻抗/每米损耗/击穿功率/倏逝衰减）。
  - docstring 逐字引文："- combline_resonator.coaxial_cavity_resonance = **同轴谐振腔**（TEM 谐振"
- 单模边界：f ≥ TE11 截止时单模 TEM 假设失效（同 combline 腔键口径如实 note）；保角映射 kc 为一阶近似非精确根。
  - docstring 逐字引文："首个高阶模 TE11 截止（保角映射 kc≈2/(a+b)）：f_c = c₀/(π(a+b)√εr)，"
- E_br 缺省 3.0e6 V/m=均匀场空气击穿参考值（STP）——同轴内导体场非均匀，工程按海拔/湿度/安全系数降额，不冒充精确击穿预测（#122 如实）。
  - docstring 逐字引文："（STP；同轴内导体场非均匀，工程需按海拔/湿度/安全系数降额，如实"
- 路线互斥守卫：分析 a/b 恰给其一（同给或全缺显式拒绝）、a≥b 非物理拒绝；epsilon_r≥1、f>0、σ>0、μr>0、tanδ≥0、E_br>0、p_op≥0——越界一律 ValueError。
  - docstring 逐字引文："守卫：分析路线 a_mm>0、b_mm>a_mm（a≥b 非物理显式拒绝）；综合路线"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/coax_line.py:coax_line_z0`
- `src/rfauto/core/calc_families/coax_line.py:coax_line_attenuation`
- `src/rfauto/core/calc_families/coax_line.py:coax_line_power_capacity`
- `src/rfauto/core/calc_families/coax_line.py:coax_line_cutoff_attenuator`

src/rfauto/core/calc_families/coax_line.py 公开符号 **4** 个（AST 机读）：

`coax_line_z0`、`coax_line_attenuation`、`coax_line_power_capacity`、`coax_line_cutoff_attenuator`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_a2c_coax_waveguide.py`——引文："数值锚（#118 独立来源；锚树 tests/unit/test_a2c_coax_waveguide.py）"

测试面（tests/unit 引用扫描，机读；合计 **101** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a2c_coax_waveguide.py` | 38 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w5k_upgrade_tiers.py` | 14 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

