<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：waveguide_closed_form

> 波导/腔体任意模式闭式谱族（架构批 A2-C 席域 2，R7 第二梯队 T2；

| 字段 | 值 |
|---|---|
| 内核 ID | `waveguide_closed_form` |
| 主模块 | `src/rfauto/core/calc_families/waveguide_closed_form.py`（`rfauto.core.calc_families.waveguide_closed_form`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/waveguide_closed_form.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

波导/腔体任意模式闭式谱：圆柱腔与矩形腔谐振谱、模式图主模切换交叉点二分求根、任意模式无载 Q 闭式与数值积分双路线互证——腔体微扰测量与材料提取面的上游模式谱供给。

模块自述（docstring 首行，机读）：波导/腔体任意模式闭式谱族（架构批 A2-C 席域 2，R7 第二梯队 T2；

## 公式与口径

### 圆柱腔 TE/TM_mnp 谐振谱（Bessel 零点闭式）

（docstring 原文转写）

```latex
f_{\mathrm{TE}_{mnp}}=\frac{c_0}{2\pi\sqrt{\varepsilon_r}}\sqrt{\left(\frac{x'_{mn}}{a}\right)^2+\left(\frac{p\pi}{L}\right)^2},\quadf_{\mathrm{TM}_{mnp}}=\frac{c_0}{2\pi\sqrt{\varepsilon_r}}\sqrt{\left(\frac{x_{mn}}{a}\right)^2+\left(\frac{p\pi}{L}\right)^2}
```

出处：模块 docstring「物理口径」节（Pozar Microwave Engineering §6.4 圆柱腔/Collin；TE 的 p≥1——p=0 时 E_t≡0 非物理显式拒绝、TM 的 p≥0 允许 TM010 经典例）。

docstring 逐字引文（防漂移钉）："TE_mnp: f = c₀/(2π√εr)·√((x'_mn/a)² + (pπ/L)²)   x'_mn = J_m'(x)" + "TM_mnp: f = c₀/(2π√εr)·√((x_mn/a)² + (pπ/L)²)    x_mn = J_m(x)"

### 主模判据与模式图交叉点

（docstring 原文转写）

```latex
\frac{l}{2a}=\frac{\pi}{2\sqrt{x_{01}^2-x'^2_{11}}}\approx 1.0154\ (\text{TM010}/\text{TE111 主模切换交叉})
```

出处：模块 docstring（模式图=归一化频率-长径比曲线族，主模切换点在相邻网格间二分求根——交叉点为模式图键输出、测试侧独立常数式钉）。

docstring 逐字引文（防漂移钉）："主模判据（计算判读非假定）：全谱最低频模式。经典口径 l<2a → TM010、" + "l>2a → TE111，交叉长径比 l/2a = π/(2·√(x_01²−x'_11²)) ≈ 1.0154"

### 无载 Q：闭式与数值积分双路线互证

（docstring 原文转写）

```latex
Q_c=\frac{\omega U}{P_c},\quadQ_{c,\mathrm{TM010}}=\frac{\eta k_0 a}{2R_s}\cdot\frac{L}{L+a},\quad\frac{1}{Q_u}=\frac{1}{Q_c}+\frac{1}{Q_d}
```

出处：模块 docstring（导体微扰 Q=ωU/P_c，Pozar §6.4/Collin 微扰法本席从场表达式独立推导；数值路线 scipy.integrate.quad 不消费 Bessel 恒等式——双路线失配即推导有误的显式证据；介质 Q=1/tanδ 串联合成同 cavity_unloaded_q 口径）。

docstring 逐字引文（防漂移钉）："TM010 极限（测试钉，测试侧独立重算）：Qc = (η·k0·a/2Rs)·L/(L+a)" + "等式）——q_xcheck_rel_dev 应为 quad 精度级（<1e-9），双路线失配即"

### KD-1 出处注册（`src/rfauto/core/calc_families/waveguide_closed_form.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/waveguide_closed_form:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `waveguide_closed_form`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 上游语义：cavity/cavity_perturbation_shift=腔体微扰测量面、material_characterization=分裂腔/Courtney 材料提取面——本族是它们的模式谱供给（TE011 空腔频率与其 _sc_empty_f0 同仓双源测试互证）；rwg_mmt=模基 GSM 数值、rw_tables=EIA 尺寸表、combline=同轴腔 TEM 单模不并入。
  - docstring 逐字引文："它们的**上游模式谱供给**（先定模式再提取）；TE011 空腔频率与"
- 模阶域守卫：TE 的 p≥1（p=0 非物理）、TM 的 p≥0 允许（TM010 经典例）；模式名白名单解析（形如 'TE011'/'TM010'，类型+mnp 三位数字），非法/越界显式拒绝。
  - docstring 逐字引文："第 n 个正零点（m≥0, n≥1, p≥1——p=0 时 E_t≡0 非物理，显式拒绝）"
- 数值锚面（#118 独立来源）：TM010 a=10mm→11.4743GHz（x_01 测试侧独立常数）；TE011/TM111 简并同频逐位；Qc 闭式 vs 数值 <1e-9、Qc∝1/Rs；主模判据经典口径复现——锚树判据书。
  - docstring 逐字引文："- εr 标度：全谱频率 ÷√εr（εr=4 → ÷2 逐位）。"
- 枚举规模守卫（max_modes 整型上限、防组合爆炸超限拒绝要求收窄频段）；radius/length>0、0<f_min<f_max、epsilon_r≥1、conductivity>0、tan_delta≥0——越界一律显式 ValueError。
  - docstring 逐字引文："整型 1..500（超限显式拒绝要求收窄频段）；模式名形如 'TE011'/'TM010'"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/waveguide_closed_form.py:circular_cavity_mode_spectrum`
- `src/rfauto/core/calc_families/waveguide_closed_form.py:circular_cavity_mode_chart`
- `src/rfauto/core/calc_families/waveguide_closed_form.py:circular_cavity_mode_q`
- `src/rfauto/core/calc_families/waveguide_closed_form.py:circular_waveguide_mode_prop`
- `src/rfauto/core/calc_families/waveguide_closed_form.py:rectangular_cavity_mode_spectrum`
- `src/rfauto/core/calc_families/waveguide_closed_form.py:rectangular_cavity_mode_q`

src/rfauto/core/calc_families/waveguide_closed_form.py 公开符号 **6** 个（AST 机读）：

`circular_cavity_mode_spectrum`、`circular_cavity_mode_chart`、`circular_cavity_mode_q`、`circular_waveguide_mode_prop`、`rectangular_cavity_mode_spectrum`、`rectangular_cavity_mode_q`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_a2c_coax_waveguide.py`——引文："数值锚（#118 独立来源；锚树 tests/unit/test_a2c_coax_waveguide.py）"

测试面（tests/unit 引用扫描，机读；合计 **187** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a2c_coax_waveguide.py` | 38 |
| `tests/unit/test_b_wave3_dr_te01d.py` | 16 |
| `tests/unit/test_calc_sympy_oracle.py` | 12 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_ui_tools_page.py` | 41 |
| `tests/unit/test_w1s2_tier2_residual.py` | 17 |
| `tests/unit/test_w5k_upgrade_tiers.py` | 14 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

