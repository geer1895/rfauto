<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：combline

> combline/同轴腔谐振器物理实现族（aurora36 W5-A 席，R2 空白域 G20 尺寸级闭环第一步）。

| 字段 | 值 |
|---|---|
| 内核 ID | `combline` |
| 主模块 | `src/rfauto/core/calc_families/combline_resonator.py`（`rfauto.core.calc_families.combline_resonator`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/combline_resonator.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

combline 杆与同轴腔谐振器频率/Q 闭式：短路线加载电容串联谐振双向互解（给定频率解杆长/给定杆长解频率）、同轴腔 TEM 半波与四分之一波双向互解带高阶模截止筛查、无载 Q 导体/介质串联合成——滤波器实现族的谐振器级底座。

模块自述（docstring 首行，机读）：combline/同轴腔谐振器物理实现族（aurora36 W5-A 席，R2 空白域 G20 尺寸级闭环第一步）。

## 公式与口径

### combline 谐振条件与双向互解（感性杆+集总电容）

（docstring 原文转写）

```latex
X_L(\omega_0)=Z_r\tan\theta_0=\frac{1}{\omega_0 C}\ \Leftrightarrow\ \omega_0 C Z_r\tan\theta_0=1,\quad \theta_0=\arctan\frac{1}{\omega_0 C Z_r}
```

出处：模块 docstring「公式口径」节（Matthaei–Young–Jones ch.8 combline 等效电路口径；杆长 l=θ₀·c₀/(2π·f₀·√εeff) 反解与分析给杆长的单调二分同节在档）。

docstring 逐字引文（防漂移钉）："ω₀·C·Zr·tan(θ₀) = 1" + "综合（给 f₀）：θ₀ = arctan(1/(ω₀·C·Zr))（闭式，0<θ₀<90°）"

### 同轴腔 TEM 谐振（Z0 闭式与半波/四分之一波双向）

（docstring 原文转写）

```latex
Z_0=\frac{60}{\sqrt{\varepsilon_r}}\ln\frac{b}{a},\quad f_0=\frac{c_0}{2l\sqrt{\varepsilon_r}}\ (\lambda/2),\quad f_0=\frac{c_0}{4l\sqrt{\varepsilon_r}}\ (\lambda/4)
```

出处：模块 docstring（Pozar Microwave Engineering §6.6 同轴线谐振器；短路-短路/短路-开路两腔型双向互解）。

docstring 逐字引文（防漂移钉）："特性阻抗 Z0 = (60/√εr)·ln(b/a) Ω（TEM 精确闭式）" + "f₀ = c₀/(2·l·√εr)，λ/4 短路-开路腔 f₀ = c₀/(4·l·√εr)（双向互解）"

### 首个高阶模 TE11 截止（保角映射近似）

（docstring 原文转写）

```latex
f_{c,TE11}=\frac{c_0}{\pi\,(a+b)\,\sqrt{\varepsilon_r}}
```

出处：模块 docstring（保角映射近似 kc≈2/(a+b)，λc=π(a+b)——单模 TEM 假设的截止筛查面）。

docstring 逐字引文（防漂移钉）："f_c,TE11 = c₀ / (π·(a+b)·√εr)"

### 无载 Q 合成（趋肤电阻口径）

（docstring 原文转写）

```latex
R_s=\sqrt{\pi f\mu/\sigma},\quad Q_c=\frac{\omega\mu\ln(b/a)}{R_s\,(1/a+1/b)},\quad Q_d=\frac{1}{\tan\delta},\quad \frac{1}{Q_u}=\frac{1}{Q_c}+\frac{1}{Q_d}
```

出处：模块 docstring（Pozar §6.6 谐振器 Q；由场积分法与 β/(2α) 衰减关系两条路线同解自洽，测试互证）。

docstring 逐字引文（防漂移钉）："Qc = ω·μ·ln(b/a) / ( Rs·(1/a + 1/b) )" + "1/Qu = 1/Qc + 1/Qd  →  Qu = Qc·Qd/(Qc+Qd)"

### KD-1 出处注册（`src/rfauto/core/calc_families/combline_resonator.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/combline_resonator:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `combline`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 高阶模越界=单模口径失效，如实注记不拒绝——TEM 谐振式本身仍成立，判定交消费面。
  - docstring 逐字引文："f₀ ≥ f_c,TE11 时单模 TEM 假设失效——如实 note 不拒绝（TEM 谐振式"
- 无耗介质档 Qd 无穷如实返 null，不虚构有限 Q。
  - docstring 逐字引文："tanδ=0 → Qd=∞ 如实返 null"
- 加载电容极限档：C→0 退化为 λ/4 短路线自谐振（测试钉）；分析给杆长的根唯一性由 g(f) 导数式保证。
  - docstring 逐字引文："C→0 时 θ₀→90°，l→λg/4——退化为 λ/4 短路线自谐振。"
- 双向互解 f0/length 恰给其一、同轴 a<b 同给且 mode 两档——越界一律显式拒绝不外推。
  - docstring 逐字引文："守卫：zr_ohm>0；cap_ff>0；epsilon_r ≥ 1；f0_ghz>0 / length_mm>0 恰给"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/combline_resonator.py:combline_resonance`
- `src/rfauto/core/calc_families/combline_resonator.py:coaxial_cavity_resonance`
- `src/rfauto/core/calc_families/combline_resonator.py:cavity_unloaded_q`

src/rfauto/core/calc_families/combline_resonator.py 公开符号 **3** 个（AST 机读）：

`combline_resonance`、`coaxial_cavity_resonance`、`cavity_unloaded_q`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w5a_doa_combline.py`——引文："数值锚（#118 独立来源；锚树 tests/unit/test_w5a_doa_combline.py）"

测试面（tests/unit 引用扫描，机读；合计 **152** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a2c_coax_waveguide.py` | 38 |
| `tests/unit/test_aurora_d_core7.py` | 22 |
| `tests/unit/test_calc_cross_validation.py` | 5 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w5a_doa_combline.py` | 24 |
| `tests/unit/test_w5k_upgrade_tiers.py` | 14 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

