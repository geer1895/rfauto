<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：siw

> 槽线 + SIW 闭式族（Janaswamy–Schaubert / Cassivi；内核在 core/slotline 等，本模块只做注册壳）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。

| 字段 | 值 |
|---|---|
| 内核 ID | `siw` |
| 主模块 | `src/rfauto/core/calc_families/slotline_siw.py`（`rfauto.core.calc_families.slotline_siw`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/slotline_siw.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

基片集成波导闭式：Cassivi 等效宽度+同宽介质矩形波导 TE10 等效（截止/色散/波阻抗），过孔藩篱设计规则复核（孔不重叠/泄漏上界/电小直径）显式把关——SIW 半族独立出卡，槽线半族见 slotline 卡。

模块自述（docstring 首行，机读）：槽线 + SIW 闭式族（Janaswamy–Schaubert / Cassivi；内核在 core/slotline 等，本模块只做注册壳）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。

## 公式与口径

### Cassivi 等效宽度

（docstring 原文转写）

```latex
w_{\mathrm{eff}}=w-\frac{d^2}{0.95\,s}
```

出处：模块头「SIW」注记（来源 A：Cassivi et al. 2002 MWCL 12(9):333-335 / Bozzi 2011 IET 综述；来源 B：Wu–Deslandes–Cassivi TELSIKS 2003——双源核实；值源优先 siw.w_eff.lit-v1 公式锚，回退闭式与锚逐位相等）。

docstring 逐字引文（防漂移钉）："Cassivi 2002 等效宽度（mm）：w_eff = w − d²/(0.95·s)。"

### TE10 等效截止与色散（介质矩形波导等效）

（docstring 原文转写）

```latex
f_{c10}=\frac{c}{2 w_{\mathrm{eff}}\sqrt{\varepsilon_r}},\quad \beta=\sqrt{(n k_0)^2-\Big(\frac{\pi}{w_{\mathrm{eff}}}\Big)^2},\quad n=\sqrt{\varepsilon_r}
```

出处：模块头「SIW」注记（按同宽 w_eff 同填充的介质矩形波导等效——来源 A 明文；截止下 β 虚数如实返 NaN 并附倏逝衰减系数供调用方处理）。

docstring 逐字引文（防漂移钉）："fc10 = c/(2·w_eff·√εr)，β(f) = √((n·k0)² − (π/w_eff)²)，n=√εr，kc=π/w_eff。"

### 波阻抗口径（u/i 与功率-电压两定义）

（docstring 原文转写）

```latex
Z_{TE}=\frac{\omega\mu_0}{\beta},\quad Z_{PV}=\frac{2 b\,Z_{TE}}{w_{\mathrm{eff}}}
```

出处：模块头「SIW」注记（功率-电压定义消元推导同节；截止/色散/波阻抗与基板厚无关，Z_PV 需基板厚时由渲染层按模板换算——本键只出与厚无关的量）。

docstring 逐字引文（防漂移钉）："波导阻抗口径（确定性内核非手数，#7）：TE10 波阻抗 Z_TE=ωμ0/β（u/i 定义），"

### KD-1 出处注册（`src/rfauto/core/calc_families/slotline_siw.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/slotline_siw:siw_check_design_rules:01 | siw_check_design_rules | pointer | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `siw`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 设计规则双源口径：孔不重叠（s>d）、泄漏控制上界（s≤2d）、电小直径（d<λ_sub/5，取较严 λ_sub 口径）——违规显式 ValueError 并返回实测比值表供判读留痕。
  - docstring 逐字引文："设计规则（过孔藩篱泄漏控制，来源 B[1]/C 双源）：s ≤ 2·d 且 d < λ_sub/5"
- 回收基准：过孔直径趋零退化为实体波导（等效宽度逐位）、空气填充复现 WR-90 教科书截止值——锚树钉死。
  - docstring 逐字引文："回收基准（#118/#300，test_siw_template 钉死）：d→0 极限 w_eff→w 逐位；"
- 综合为 Cassivi 式反解+回代自洽（残差超带显式硬错）；设计规则检查用截止频率带内最松端，工作频率端的电小直径条件由分析键按实查频率把关。
  - docstring 逐字引文："w = w_eff + d²/(0.95·s)（Cassivi 式反解）；设计规则检查用 fc10（带内最松"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/slotline_siw.py:siw_analysis`
- `src/rfauto/core/calc_families/slotline_siw.py:siw_synthesis`

src/rfauto/core/calc_families/slotline_siw.py 公开符号 **7** 个（AST 机读）：

`slotline_analysis`、`slotline_synthesis`、`siw_effective_width_mm`、`siw_check_design_rules`、`siw_beta_rad_m`、`siw_analysis`、`siw_synthesis`

## 锚与测试入口

analytic-anchor（knowledge/anchors.yaml 机读命中）：

| anchor_id | quantity |
|---|---|
| `siw.w_eff.lit-v1` | siw_w_eff_mm |

判据书/规格指针（docstring 逐字引文钉）：

- `runs/siw_family/criteria.md`（仓内档，公开分发视图不随附，存在性不作测试断言）——引文："双源核实与全部常数出处：runs/siw_family/criteria.md §1（铁律 1c）——"
- `tests/unit/test_siw_template.py`——引文："回收基准（#118/#300，test_siw_template 钉死）：d→0 极限 w_eff→w 逐位；"

测试面（tests/unit 引用扫描，机读；合计 **132** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_closed_form_oracle.py` | 18 |
| `tests/unit/test_rwg_mmt.py` | 26 |
| `tests/unit/test_siw_template.py` | 26 |
| `tests/unit/test_x5_analytic_anchors.py` | 13 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

