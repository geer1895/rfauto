<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：rf_switch

> 射频开关件面（aurora_f W2-S6 席域，R2_core_tier3 §③ D8 立项）。

| 字段 | 值 |
|---|---|
| 内核 ID | `rf_switch` |
| 主模块 | `src/rfauto/core/calc_families/rf_switch.py`（`rfauto.core.calc_families.rf_switch`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/rf_switch.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

射频开关器件面：PIN 串/并联元件导通/截止两态 S 参数与 cutoff 品质因数、λ/4 并联二极管 SPDT 频响（开关带宽语义）、开关链二态插损/隔离 dB 可加预算与失配纹波界。

模块自述（docstring 首行，机读）：射频开关件面（aurora_f W2-S6 席域，R2_core_tier3 §③ D8 立项）。

## 公式与口径

### PIN 元件两态模型与 cutoff 品质因数

（docstring 原文转写）

```latex
S_{21}^{\mathrm{on}}=\frac{2Z_0}{2Z_0+R_{\mathrm{on}}},\quad S_{21}^{\mathrm{off}}=\frac{2Z_0}{2Z_0+1/j\omega C_{\mathrm{off}}},\quad f_c=\frac{1}{2\pi R_{\mathrm{on}}C_{\mathrm{off}}}
```

出处：模块 docstring「PIN 元件两态模型」节（串联拓扑口径；并联拓扑与 f_c=1/(2π·R_on·C_off) FOM 同节——R_on·C_off 乘积单值标度，测试按乘积标度恒等钉）。

docstring 逐字引文（防漂移钉）："导通（R_on）=直通态 S21=2Z0/(2Z0+R_on)、S11=R_on/(2Z0+" + "截止（C_off）=隔离态 S21=2Z0/(2Z0+1/jωC_off)——低频渐近"

### λ/4 并联二极管 SPDT（switched line）

（docstring 原文转写）

```latex
Z_{\mathrm{in}}=Z_0\frac{Z_L+jZ_0\tan\theta}{Z_0+jZ_L\tan\theta},\quad\theta=2\pi f\sqrt{\varepsilon_{\mathrm{eff}}}L/c
```

出处：模块 docstring「λ/4 并联二极管 SPDT」节（选中臂截止=匹配、非选中臂导通近短路经 λ/4 变换高阻挂结点；Pozar Ch.12 / 微波控制器件文献二级转引）。

docstring 逐字引文（防漂移钉）："Z_in(线)=Z0(Z_L+jZ0·tanθ)/(Z0+jZ_L·tanθ)，θ=2πf·√εeff·L/c" + "偏离 f0 时 tanθ 失谐→隔离/匹配退化（**开关带宽语义**：λ/4 线窄带"

### 开关链二态预算（dB 可加与失配纹波界）

（docstring 原文转写）

```latex
IL_{\mathrm{tot}}=\sum_i IL_i,\quadISO_{\mathrm{tot}}=\sum_j ISO_j,\quad\Delta\le\sum_i 20\log_{10}(1+\gamma_i\gamma_{i+1})
```

出处：模块 docstring「开关链二态预算」节（20log10(1+γ_iγ_{i+1}) 逐对叠加；吸收式=严格界、反射式=一阶近似 flag 如实透传）。

docstring 逐字引文（防漂移钉）："（ΣIL_dB——dB 域级联定义恒等式）；路径隔离=各离选支路隔离 dB 可加。" + "失配纹波界（教科书级联口径）：相邻端口对 γ_i、γ_{i+1} 交互最坏"

### KD-1 出处注册（`src/rfauto/core/calc_families/rf_switch.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/rf_switch:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `rf_switch`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 边界防撞：switch_pa_efficiency=开关模 PA 效率、phase_shifter switched_line=移相网络（态间相位差面）、pa_arch pin_diode_limiter=限幅器、step_attenuator_design=步进衰减——本族只做 SPnT 开关器件级（插损/隔离/带宽口径）。
  - docstring 逐字引文："switch_pa_efficiency=开关**模 PA 效率**（D/E 类调制域）、phase_shifter"
- 吸收式 vs 反射式语义：反射式离选臂把功率反射回源（二阶再反射项本键不计如实注记）——纹波界对吸收式为严格界、对反射式为一阶近似（flag 如实透传）。
  - docstring 逐字引文："（离选臂内置 Z0 端接）无再反射——纹波界对吸收式为严格界，对反射式"
- 拓扑语义：矩阵列换面不在本层——路径预算按元件列表面消费（可加性口径与拓扑无关）。
  - docstring 逐字引文："rf 矩阵列换面（N×M 交叉点拓扑）不在本层——本键按路径元件列表面"
- elements 表逐项 il_db/iso_db ≥0 且有限、γ∈[0,1)——越界一律显式 ValueError。
  - docstring 逐字引文："守卫：r_on_ohm>0、c_off_f>0、z0_ohm>0、频率>0；topology∈{series,shunt}；"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/rf_switch.py:pin_switch_s2p`
- `src/rfauto/core/calc_families/rf_switch.py:rf_switch_spdt_quarter_wave`
- `src/rfauto/core/calc_families/rf_switch.py:rf_switch_matrix_path`

src/rfauto/core/calc_families/rf_switch.py 公开符号 **3** 个（AST 机读）：

`pin_switch_s2p`、`rf_switch_spdt_quarter_wave`、`rf_switch_matrix_path`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w2s6_mixer_bridge_switch.py`——引文："射频开关件面（aurora_f W2-S6 席域，R2_core_tier3 §③ D8 立项）。"

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
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

