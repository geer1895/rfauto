<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：six_port

> 六端口反射计（架构批 W3-S10 席域，R2_core_tier3 §③ D7 立项——

| 字段 | 值 |
|---|---|
| 内核 ID | `six_port` |
| 主模块 | `src/rfauto/core/calc_families/six_port.py`（`rfauto.core.calc_families.six_port`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/six_port.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

六端口反射计反演架构：功率读数→Γ 最小二乘闭式反演与已知负载→q 点校准常数提取——4 路功率检波干涉法的圆交点反演（桥式检波器件面之外的架构层）。

模块自述（docstring 首行，机读）：六端口反射计（架构批 W3-S10 席域，R2_core_tier3 §③ D7 立项——

## 公式与口径

### 六端口状态方程（Engen 反射计口径）

（docstring 原文转写）

```latex
P_i=K_i\,|a|^2\,|\Gamma-q_i|^2
```

出处：模块 docstring「六端口状态方程」节（Γ=b/a、q_i=第 i 路检波器等效波源复数位置；Engen IEEE TTT 25(12) 1977 二级转引，trl_standards 同源引注背书）。

docstring 逐字引文（防漂移钉）："P_i = K_i·|a|²·|Γ − q_i|²"

### Γ 最小二乘反演闭式（4×3 过定线性系统）

（docstring 原文转写）

```latex
|\Gamma-q_i|^2=X-2(u_i x+v_i y)+|q_i|^2\ \Rightarrow\ X-2u_i x-2v_i y=p_i-|q_i|^2
```

出处：模块 docstring「Γ 最小二乘反演闭式」节（记 Γ=x+jy、X=|Γ|²；正规方程 AᵀA·z=Aᵀb 纯 python 高斯消元；多余第 4 方程=过定冗余校验面）。

docstring 逐字引文（防漂移钉）："X − 2u_i·x − 2v_i·y = p_i − |q_i|²   （i=3..6，4×3 线性系统）"

### q 点校准提取闭式（恰定直解/OLS）

（docstring 原文转写）

```latex
|q_i|^2-2x_j u_i-2y_j v_i=p_{ij}-|\Gamma_j|^2
```

出处：模块 docstring「q 点校准提取闭式」节（N=3 恰定=直解残差机器精度、N>3 过定=最小二乘；extract→solve 合成回收=校准↔测量闭合成环 #118 锚树主判）。

docstring 逐字引文（防漂移钉）："|q_i|² − 2x_j·u_i − 2y_j·v_i = p_ij − |Γ_j|²"

### KD-1 出处注册（`src/rfauto/core/calc_families/six_port.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/six_port:<module>:01 | <module> | source | — | 出处（Engen 1977；Engen-Hoer 1979；Network Analyzer", IEEE Trans. MTT 25(12):1075-1080, 1977（二级；MTT 27(12):987-998, 1979（TRL 口径走 trl_standards 面，同源引注 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `six_port`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 理想平方律 K_i=1 归一化由调用方完成——实测检波律/温漂走 detector_device 与 power_cal_chain 补偿后归一（单源不重复）。
  - docstring 逐字引文："口径 p_i = P_i/(K_i·|a|²) 由调用方完成——实测 K_i≠1/检波律修正/"
- 退化面守卫：q 点全等/负载共线（设计矩阵奇异）显式拒绝——校准键要求 ≥3 线性独立负载点。
  - docstring 逐字引文："q 点全等/设计矩阵奇异 → 显式 ValueError（退化 q 面）。"
- 功率检波噪声加权 OLS/结非理想高阶项/双六端口 TRL 扩展不在本族；|Γ|>1 有源 DUT 不设界如实回显 flag。
  - docstring 逐字引文："Hoer 1979 TRL 口径走 trl_standards 面）不在本族；|Γ|>1（有源"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/six_port.py:six_port_gamma_solve`
- `src/rfauto/core/calc_families/six_port.py:six_port_cal_extract`

src/rfauto/core/calc_families/six_port.py 公开符号 **2** 个（AST 机读）：

`six_port_gamma_solve`、`six_port_cal_extract`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w3s10_agc_calkit_sixport.py`——引文："架构批 W3-S10 席域，R2_core_tier3 §③ D7 立项"

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
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

