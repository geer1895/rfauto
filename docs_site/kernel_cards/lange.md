<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：lange

> Lange 电桥专属综合内核（架构批 W1-S3 席域，R2_core_tier3 §⑤ F1 设计案）。

| 字段 | 值 |
|---|---|
| 内核 ID | `lange` |
| 主模块 | `src/rfauto/core/calc_families/lange.py`（`rfauto.core.calc_families.lange`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/lange.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

Lange 电桥专属综合内核：C(dB)→相邻对 (Z0e,Z0o) 四指设计式→四线等效 (Ze4,Zo4)→KJ 二维反解 (w,s)→指长 λ/4——render_c4 全链的提升式重构单一事实源（字节级对拍钉），附四线等效偶/奇模频响裁判。

模块自述（docstring 首行，机读）：Lange 电桥专属综合内核（架构批 W1-S3 席域，R2_core_tier3 §⑤ F1 设计案）。

## 公式与口径

### 四指设计式（Pozar §7.6 Lange 节）

（docstring 原文转写）

```latex
Z_{0e}=\frac{Z_0(4C-3+\sqrt{9-8C^2})}{2C\sqrt{\frac{1-C}{1+C}}},\quad Z_{0o}=\frac{Z_0(4C+3-\sqrt{9-8C^2})}{2C\sqrt{\frac{1+C}{1-C}}}
```

出处：模块 docstring「物理口径」节（原始 J. Lange IEEE-MTT 1969 二级转引；C=10^(−C_dB/20)）。

docstring 逐字引文（防漂移钉）："Z0e=Z0(4C−3+√(9−8C²))/(2C√((1−C)/(1+C)))、" + "Z0o=Z0(4C+3−√(9−8C²))/(2C√((1+C)/(1−C)))，须 8C²<9"

### 四线等效两线（Pozar §7.6）

（docstring 原文转写）

```latex
Z_{e4}=\frac{Z_{0e}(Z_{0o}+Z_{0e})}{3Z_{0o}+Z_{0e}},\quad Z_{o4}=\frac{Z_{0o}(Z_{0o}+Z_{0e})}{3Z_{0e}+Z_{0o}},\quad C=\frac{Z_{e4}-Z_{o4}}{Z_{e4}+Z_{o4}},\quad Z_0=\sqrt{Z_{e4}Z_{o4}}
```

出处：模块 docstring（回代自证逐位闭合；3dB 闭合链 (176.216,52.609)→(120.71,20.71)Ω 教科书锚在测试侧）。

docstring 逐字引文（防漂移钉）："Ze4=Z0e(Z0o+Z0e)/(3Z0o+Z0e)、Zo4=Z0o(Z0o+Z0e)/(3Z0e+Z0o)；" + "耦合 C=(Ze4−Zo4)/(Ze4+Zo4)、Z0=√(Ze4·Zo4)"

### 几何链（KJ 二维反解+HJ 精算）

（docstring 原文转写）

```latex
(w,s)=f^{-1}_{\mathrm{KJ}}(Z_{0e},Z_{0o}),\quad L_{\mathrm{finger}}=\frac{c}{4f_0\sqrt{\tfrac{\varepsilon_{e}+\varepsilon_{o}}{2}}}
```

出处：模块 docstring「几何链」行（(w,s) 走 core/coupled_microstrip.coupled_bpf_width_gap_from_zee_zoo——本席同批提升；铁律 1c 唯一线宽口径）。

docstring 逐字引文（防漂移钉）："→ 指长 λ/4 @ (εeff_e+εeff_o)/2；馈线宽 inverse_width（skrf HJ，"

### 频响（四线等效偶/奇模叠加裁判）

（docstring 原文转写）

```latex
S^{(4\square)}=\tfrac{1}{2}(S^{e}+S^{o}),\quad \theta_{e/o}=k_0L\sqrt{\varepsilon_{e/o}}
```

出处：模块 docstring「频响键」行（与 adapters._coupled_section_s4 同构造异路线，测试互证 ≤1e-12 #118）。

docstring 逐字引文（防漂移钉）："偶/奇模各自 2 端口线 S 叠加构造 4 端口（(Se+So)/2 口径——与"

### KD-1 出处注册（`src/rfauto/core/calc_families/lange.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/lange:<module>:01 | <module> | source | — | IEEE Trans. MTT 17(12), 1969；二级转引 Pozar, Microwave Engineering；4th ed. §7.6；多导体模式相速口径 W. P. Ou, IEEE Trans. MTT, 1975 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `lange`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 一阶设计口径：非相邻指耦合与桥缝耦合寄生于理想裁判之外（render_c4 §C4 口径 3 同源）。
  - docstring 逐字引文："非相邻指耦合忽略（一阶 Lange 设计口径）**如实登记。"
- 同步 TEM 档（缺省）取平均 εeff 给理想裁判；真非同步相速属多导体模式问题，不做修正即如实声明（ Ou 1975 口径）。
  - docstring 逐字引文："相邻对 KJ εeff_e/εeff_o 不是四线等效模相速（多导体模式，Ou 1975）——拿来"
- KJ 有效域提示（g=s/h 下限 0.1）：3dB 设计于本叠层略出域，如实记录不拦截。
  - docstring 逐字引文："h=0.508 反解 s=0.0386mm → g=s/h=0.076 略低于 KJ 标称有效域下限 0.1"
- 提升式重构单一事实源：adapters/render_c4 与 openems_templates 的同名入口=core 同一函数对象（字节级对拍钉，基线 内部证据目录）。
  - docstring 逐字引文："函数体自 render_c4 原样下沉（逐字节未动），render_c4 改为"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/lange.py:lange_synthesize`
- `src/rfauto/core/calc_families/lange.py:lange_response`
- `src/rfauto/core/calc_families/lange.py:lange_design`
- `src/rfauto/core/calc_families/lange.py:lange_pair_zee_zoo`
- `src/rfauto/core/calc_families/lange.py:lange_equivalent_zee_zoo`

src/rfauto/core/calc_families/lange.py 公开符号 **5** 个（AST 机读）：

`lange_pair_zee_zoo`、`lange_equivalent_zee_zoo`、`lange_design`、`lange_synthesize`、`lange_response`

消费面（service/adapters 引用扫描，机读）：

- adapters：`src/rfauto/adapters/oe_templates/render_c4.py`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w1s3_lange_stepped.py`——引文："内部证据目录"

测试面（tests/unit 引用扫描，机读；合计 **60** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w1s3_lange_stepped.py` | 11 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

