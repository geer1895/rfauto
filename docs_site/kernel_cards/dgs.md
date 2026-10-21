<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：dgs

> DGS 缺陷接地结构族（架构批 W2-S2 席域 C3，R2_core_tier4 §③ Top5 设计案）。

| 字段 | 值 |
|---|---|
| 内核 ID | `dgs` |
| 主模块 | `src/rfauto/core/calc_families/dgs.py`（`rfauto.core.calc_families.dgs`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/dgs.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

哑铃形缺陷接地结构面：陷波/截止双条件反演一阶等效电感电容与陷波响应逐频再生（同文件双路径闭环）——全仓最后一个零命中 PCB 器件域的首批键位，几何经验拟合面如实留白待文献复读。

模块自述（docstring 首行，机读）：DGS 缺陷接地结构族（架构批 W2-S2 席域 C3，R2_core_tier4 §③ Top5 设计案）。

## 公式与口径

### 哑铃 DGS 一阶等效提取（陷波+3dB 两条件联立）

（docstring 原文转写）

```latex
C=\frac{2(\omega_0^2-\omega_c^2)}{Z_0\omega_0^2\omega_c}=\frac{2}{Z_0\omega_c}\left(1-\frac{\omega_c^2}{\omega_0^2}\right),\quadL=\frac{1}{\omega_0^2 C}=\frac{Z_0\omega_c}{2(\omega_0^2-\omega_c^2)}
```

出处：模块 docstring「物理口径」节（陷波条件 X(ω0)=0 与 3dB 条件 |X(ωc)|=Z0/2 由无损并联元件传输式令 =1/2 解出——第一性推导联立；文献族口径 Lim/Ahn IEEE MTT 2000-2002，UNVERIFIED 如实预声明）。

docstring 逐字引文（防漂移钉）："C = 2(ω0² − ωc²)/(Z0·ω0²·ωc) = (2/(Z0·ωc))·(1 − (ωc/ω0)²)" + "L = 1/(ω0²·C) = Z0·ωc/(2(ω0² − ωc²))"

### 陷波/低通响应再生（同文件双路径）

（docstring 原文转写）

```latex
|S_{21}(f)|=\frac{2|X|}{\sqrt{Z_0^2+4X^2}},\quad X(f)=2\pi fL-\frac{1}{2\pi fC}
```

出处：模块 docstring「响应再生」节（低频 X→−∞ 直通、f=f0 全陷波、f=fc 恰 −3.0102999dB 构造恒等式；extract→response roundtrip #118 同文件双路径）。

docstring 逐字引文（防漂移钉）："|S21(f)| = 2|X|/√(Z0²+4X²)" + "X(f)=2πfL − 1/(2πfC)"

### 两条提取条件（第一性推导源）

（docstring 原文转写）

```latex
X(\omega_0)=0\ \left(\omega_0=\frac{1}{\sqrt{LC}}\right),\quad|S_{21}|^2=\frac{4X^2}{Z_0^2+4X^2}=\frac{1}{2}\ \Rightarrow\ |X(\omega_c)|=\frac{Z_0}{2}
```

出处：模块 docstring「物理口径」节（并联支路 Z_g(jω)=jX(ω) 串联回路面；X(ωc)=−Z0/2 与 ω0²=1/(LC) 回代残差随输出自检）。

docstring 逐字引文（防漂移钉）："X(ω0) = 0 ⇔ ω0 = 1/√(LC)" + "|S21|² = 4X²/(Z0²+4X²) 令 =1/2 解出"

### KD-1 出处注册（`src/rfauto/core/calc_families/dgs.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/dgs:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `dgs`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 出处分级（#122）：两条件联立=第一性推导（构造恒等式锚），文献族口径 Lim/Ahn IEEE MTT 2000-2002 原文页码级复读未做 UNVERIFIED 如实登记（circulator_synthesis Wu-Rosenbaum 先例同口径）。
  - docstring 逐字引文："记忆写式；文献原文页码级复读未做，如实登记 UNVERIFIED——同"
- 几何面留白：哑铃边长/槽缝宽→L/C 的文献拟合经验常数不入键面（#1c 禁凭记忆写经验常数）——f0/fc 由调用方 EM 提取供给（真机仲裁链）。
  - docstring 逐字引文："几何→LC 的经验拟合式（哑铃边长/槽缝宽 → L/C 的文献拟合族）不做（#1c"
- 边界防撞：vendor_passives=分立器件、homogenization=体超材料、amc_mushroom=表面型 EBG、crlh=周期单元阵列——本族=离散地面缺陷单元；慢波等效面 R2 预声明登记不建模如实留白。
  - docstring 逐字引文："- vendor_passives=器件级 RLC（磁珠/电容 ESR 模型）——本族=地面缺陷结构"
- 模型自洽守卫：f0≤f3db 时支路呈感性无低通语义显式拒绝；dB 输出对理想全陷波取 −300dB 地板+below_floor 旗标（JSON 严格序列化禁 inf 信封契约）；全键越界显式 ValueError。
  - docstring 逐字引文："自洽性：ω0 > ωc（陷波在截止之上）时 C>0、L>0 恒成立；f0 ≤ f3db 时"
- 数值锚面（#118 独立算术）：(2.4GHz, 1.8GHz, 50Ω) → C=1.5473pF、L=2.8421nH 逐位；X(ωc)=−Z0/2 与 ω0²=1/(LC) 回代残差 ~1e-16；无耗 |S21|≤1 全扫描——锚树判据书。
  - docstring 逐字引文："守卫：f0_ghz/f3db_ghz/z0_ohm>0 且 f0>f3db；l_nh/c_pf>0；freq_ghz 列表"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/dgs.py:dgs_dumbbell_lc_extract`
- `src/rfauto/core/calc_families/dgs.py:dgs_notch_response`

src/rfauto/core/calc_families/dgs.py 公开符号 **2** 个（AST 机读）：

`dgs_dumbbell_lc_extract`、`dgs_notch_response`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w2s2_core_tier4.py`——引文："tests/unit/test_w2s2_core_tier4.py）"

测试面（tests/unit 引用扫描，机读；合计 **86** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w2s2_core_tier4.py` | 17 |
| `tests/unit/test_w4s1_review_guards.py` | 20 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

