<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：agc_loop

> AGC 环路动力学（架构批 W3-S10 席域，R2_core_tier3 §③ D3 立项——

| 字段 | 值 |
|---|---|
| 内核 ID | `agc_loop` |
| 主模块 | `src/rfauto/core/calc_families/agc_loop.py`（`rfauto.core.calc_families.agc_loop`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/agc_loop.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

AGC 环路动力学：对数域一阶环线性化闭环常数（环路带宽/attack-release 时间常数/稳态误差）与阶跃扰动时域轨迹——rx_impairments 预声明排除面的动态半边补全。

模块自述（docstring 首行，机读）：AGC 环路动力学（架构批 W3-S10 席域，R2_core_tier3 §③ D3 立项——

## 公式与口径

### 开环对数增益与扰动方程

（docstring 原文转写）

```latex
T=A\,K_d\,K_v,\quad \tau_L\frac{d\delta}{dt}+(1+T)\,\delta=\delta_{in}
```

出处：模块 docstring「链路模型」「开环对数增益」行（控制论一阶环线性化口径；负反馈极性=输出过高→V_c↑→增益↓）。

docstring 逐字引文（防漂移钉）："τ_L·dδ/dt + (1+T)·δ = δ_in" + "T = A·K_d·K_v（量纲 dB/V·V/dB 相消，无量纲）"

### 闭环常数闭式（一阶环恒等式，测试锚主判）

（docstring 原文转写）

```latex
\omega_p=\frac{1+T}{\tau_L},\ f_{loop}=\frac{1+T}{2\pi\tau_L},\ \tau_a=\frac{\tau_L}{1+T},\ \varepsilon=\frac{1}{1+T}
```

出处：模块 docstring「闭环常数闭式」节（release 档 τ_r=ρ·τ_L/(1+T) 带宽再除 ρ；建立时间一阶标准口径）。

docstring 逐字引文（防漂移钉）："闭环极点 ω_p=(1+T)/τ_L [rad/s]；环路带宽 f_loop=(1+T)/(2π·τ_L)" + "ε=1/(1+T)；阶跃暂态衰减到份额 α 的建立时间 t_s=−τ·ln(α)"

### 阶跃响应闭式（attack/release 双档）

（docstring 原文转写）

```latex
\delta(t)=\frac{\delta_{in}}{1+T}\bigl(1+T\,e^{-t/\tau_{eff}}\bigr)
```

出处：模块 docstring「阶跃响应闭式」节（正阶跃=attack 快档、负阶跃=release 慢档语义如实回显）。

docstring 逐字引文（防漂移钉）："δ(t) = δ_in/(1+T)·(1 + T·e^{−t/τ_eff})"

### KD-1 出处注册（`src/rfauto/core/calc_families/agc_loop.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/agc_loop:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `agc_loop`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 诚实边界：检波理想对数律/VGA dB 线性/单极点滤波——高阶滤波与时延稳定性裕度面（时延相位侵蚀可致振荡）不在本域。
  - docstring 逐字引文："线性化对数域一阶环——检波器理想对数律"
- A→0⁺ 数值极限档=开环直通恒等（τ→τ_L、ε→1）——loop_gain_a>0 守卫下的退化锚。
  - docstring 逐字引文："无 AGC 退化=T→0（A→0 极限）："
- 静态线性度归 rx_impairments（预声明注记已改指路本模块）；PLL 环路滤波器综合走 pll_loop_filter——同族不同对象边界互指。
  - docstring 逐字引文："P1dB 裕量/压缩后 NF 等静态线性度面仍归 rx_impairments"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/agc_loop.py:agc_loop_dynamics`
- `src/rfauto/core/calc_families/agc_loop.py:agc_loop_response`

src/rfauto/core/calc_families/agc_loop.py 公开符号 **2** 个（AST 机读）：

`agc_loop_dynamics`、`agc_loop_response`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w3s10_agc_calkit_sixport.py`——引文："架构批 W3-S10 席域，R2_core_tier3 §③ D3 立项"

测试面（tests/unit 引用扫描，机读；合计 **73** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w3s10_agc_calkit_sixport.py` | 24 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

