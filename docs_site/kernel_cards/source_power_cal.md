<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：source_power_cal

> 源功率校准族（aurora_f W5-S18 席域，R2_core_tier3 边际池立项）。

| 字段 | 值 |
|---|---|
| 内核 ID | `source_power_cal` |
| 主模块 | `src/rfauto/core/calc_families/source_power_cal.py`（`rfauto.core.calc_families.source_power_cal`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/source_power_cal.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

源功率校准闭环：功率计参考面修正读数→offset 表→源编程设定闭式（参考面交付功率平坦档），附平坦设定对照档与不确定度 1:1 传播——源编程端与功率测量链的交付恒等式互补。

模块自述（docstring 首行，机读）：源功率校准族（aurora_f W5-S18 席域，R2_core_tier3 边际池立项）。

## 公式与口径

### 闭环方程（offset 表→源编程设定）

（docstring 原文转写）

```latex
\mathrm{offset}(f)=p_{meas}(f)-p_{set},\quad \mathrm{program}(f)=p_{target}-\mathrm{offset}(f)
```

出处：模块 docstring「闭环方程」节（交付恒等式 program(f)+offset(f)=p_target 逐位；Keysight "Source Power Calibration" 语义二级转引）。

docstring 逐字引文（防漂移钉）："offset(f) = p_meas(f) − p_set            （测量端传递/损耗表，dB）" + "program(f) = p_target − offset(f)        （源编程设定表，dBm）"

### flat-falling 双读法（方向旗标如实自报）

（docstring 原文转写）

```latex
p_{flat}(f)=p_{target}+\mathrm{offset}(f)\ \Rightarrow\ \mathrm{delivered}=p_{flat}+\mathrm{offset}\ (\text{随 }f\text{ 下坠})
```

出处：模块 docstring「flat-falling 双读法」节（平坦交付档与平坦设定对照档两档逐频列表与 span/单调方向全部落盘）。

docstring 逐字引文（防漂移钉）："② 平坦设定对照档 p_flat(f) = p_target + offset(f)"

### 不确定度传播（dB 域 1:1 线性）

（docstring 原文转写）

```latex
u_{program}(f)=u_{meas}(f),\quad U=k{=}2\cdot u
```

出处：模块 docstring「不确定度传播」节（功率计链 GUM 预算见 power_cal_chain 的 u_components 面，单源不重复）。

docstring 逐字引文（防漂移钉）："u_program(f) = u_meas(f)（参考面"

### KD-1 出处注册（`src/rfauto/core/calc_families/source_power_cal.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/source_power_cal:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `source_power_cal`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 输入语义=power_cal_chain 输出（参考面修正后读数）——原始读数先走该链（#118 语义单一事实源）。
  - docstring 逐字引文："读数端校准因子/失配补偿不在本键（输入必须已是参考"
- 逐频点独立闭式、无跨频拟合/插值面（源平滑约束不在本域）；接收机频响线性度（dB 域叠加）由调用方保证。
  - docstring 逐字引文："①逐频点独立闭式（无跨频拟合/插值面，源平滑"
- 可选源上限超限点记 infeasible+超限 dB——不裁剪不冒充可达。
  - docstring 逐字引文："源功率上限触顶时平坦交付不可达，如实不裁剪"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/source_power_cal.py:source_power_cal_table`

src/rfauto/core/calc_families/source_power_cal.py 公开符号 **1** 个（AST 机读）：

`source_power_cal_table`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w5s18_core_edge.py`——引文："aurora_f W5-S18 席域，R2_core_tier3 边际池立项"

测试面（tests/unit 引用扫描，机读；合计 **61** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w5s18_core_edge.py` | 12 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

