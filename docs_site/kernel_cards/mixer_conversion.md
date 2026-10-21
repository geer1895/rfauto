<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：mixer_conversion

> 混频器变换面（架构批 W2-S6 席域，R2_core_tier3 §③ D2 立项）。

| 字段 | 值 |
|---|---|
| 内核 ID | `mixer_conversion` |
| 主模块 | `src/rfauto/core/calc_families/mixer_conversion.py`（`rfauto.core.calc_families.mixer_conversion`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/mixer_conversion.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

混频器变换面：镜像噪声折入 SSB-NF 精确恒等式、变频损耗 SSB/DSB 口径换算与无源混频噪声地板、镜像频率规划与 IQ 失衡 IRR 同式复算——级联噪声预算上游的变换记账内核。

模块自述（docstring 首行，机读）：混频器变换面（架构批 W2-S6 席域，R2_core_tier3 §③ D2 立项）。

## 公式与口径

### 镜像噪声折入精确恒等式（消元闭式）

（docstring 原文转写）

```latex
F_{\mathrm{SSB}}=(1+g\,t)\,F_{\mathrm{DSB}},\quad g=10^{-IR/10},\ t=T_{\mathrm{im}}/T_0
```

出处：模块 docstring「镜像噪声折入（image noise fold）」节（两式消 N_int 与 F_m；t=1 档对混频器噪声分配无假设依赖；Pozar Ch.12 口径，出处节在档）。

docstring 逐字引文（防漂移钉）："**F_SSB = (1 + g·t)·F_DSB**" + "**NF_SSB = NF_DSB + 3.0103 dB** 教科书 3dB 折入极限"

### 变频损耗 SSB/DSB 等分恒等式

（docstring 原文转写）

```latex
CL_{\mathrm{DSB}}=CL_{\mathrm{SSB}}-3.0103\,\mathrm{dB}
```

出处：模块 docstring「变频损耗 SSB/DSB 口径」行（DSB 两带都载信号 → 增益 +3.0103 dB）。

docstring 逐字引文（防漂移钉）："（CL_DSB = CL_SSB − 3.0103 dB，等分恒等式）"

### 无源混频噪声地板（衰减器同构）

（docstring 原文转写）

```latex
F_{\mathrm{DSB}}=\tfrac{CL_{\mathrm{lin}}}{2},\quad F_{\mathrm{SSB}}=CL_{\mathrm{lin}},\quad NF_{\mathrm{SSB}}^{\mathrm{ideal\,passive}}=CL_{\mathrm{SSB}}
```

出处：模块 docstring「无源混频噪声地板」节（与 mixer_ssb_nf 键跨键双源互证：F_SSB=2·(CL_lin/2)=CL_lin）。

docstring 逐字引文（防漂移钉）："F_DSB=CL_lin/2、" + "即 **NF_SSB(理想无源) = CL_SSB**（与 mixer_ssb_nf 键"

### 镜像规划与 IQ 失衡 IRR

（docstring 原文转写）

```latex
f_{im}^{\mathrm{low}}=f_{LO}-f_{IF},\ f_{im}^{\mathrm{high}}=f_{LO}+f_{IF},\ |f_{im}-f_{RF}|=2f_{IF};\quad \mathrm{IRR}=\frac{1+\varepsilon^2+2\varepsilon\cos\varphi}{1+\varepsilon^2-2\varepsilon\cos\varphi}
```

出处：模块 docstring「镜像规划」「IQ 失衡→IRR」行（IRR 与 rx_impairments 同式独立复算，#118 同仓双源）。

docstring 逐字引文（防漂移钉）："镜像距信号 **2·f_IF**（预选滤波器设计依据）" + "Razavi 式 IRR=(1+ε²+2εcosφ)/(1+ε²−2εcosφ)"

### KD-1 出处注册（`src/rfauto/core/calc_families/mixer_conversion.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/mixer_conversion:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `mixer_conversion`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- t≠1 档的等噪声贡献假设如实注记（t=1 档消元精确不受影响）——实际器件以手册 SSB 实测为准。
  - docstring 逐字引文："t≠1 时本键按镜像支路与信号支路"
- 无源地板是下界参考——超出量=器件质量指标（手册如实），不冒充典型值。
  - docstring 逐字引文："真实有源/二极管混频器的 NF 高于该地板"
- 族界：cascade 杂散面（m·f_RF±n·f_LO 乘积域）与 BlockSpec.conversion_loss_db=模型层参数槽；IRR 消费面归 rx_impairments（同式独立复算互证不重写）。
  - docstring 逐字引文："本族只做**变换损耗+镜像噪声记账+镜像几何规划**"
- 守卫面：nf/损耗有限非负、IR≥0（None=完美镜像抑制）、t∈[0,1]、f_RF≠f_LO（零中频镜像=信号本身显式拒绝）。
  - docstring 逐字引文："越界一律显式 ValueError"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/mixer_conversion.py:mixer_ssb_nf`
- `src/rfauto/core/calc_families/mixer_conversion.py:mixer_conversion_loss`
- `src/rfauto/core/calc_families/mixer_conversion.py:mixer_image_plan`

src/rfauto/core/calc_families/mixer_conversion.py 公开符号 **3** 个（AST 机读）：

`mixer_ssb_nf`、`mixer_conversion_loss`、`mixer_image_plan`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w2s6_mixer_bridge_switch.py`——引文："架构批 W2-S6 席域，R2_core_tier3 §③ D2 立项"

测试面（tests/unit 引用扫描，机读；合计 **74** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w2s6_mixer_bridge_switch.py` | 25 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

