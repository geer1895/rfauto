<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：bethe_hole_coupler

> Bethe 孔定向耦合器（矩形波导公共宽壁中心圆孔，架构批 W3-A 席，R2 空白域 G5）。

| 字段 | 值 |
|---|---|
| 内核 ID | `bethe_hole_coupler` |
| 主模块 | `src/rfauto/core/calc_families/bethe_hole.py`（`rfauto.core.calc_families.bethe_hole`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/bethe_hole.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

Bethe 孔定向耦合器（矩形波导共宽壁中心圆孔）：小孔极化率偶/奇支路 E+M/E−M 结构给出耦合/隔离/方向性闭式，综合方向 c∝d³ 反解三次式——Cohn 有限壁厚修正 opt-in、近似层级与守卫逐条声明。

模块自述（docstring 首行，机读）：Bethe 孔定向耦合器（矩形波导公共宽壁中心圆孔，架构批 W3-A 席，R2 空白域 G5）。

## 公式与口径

### Bethe 小孔极化率（零厚无限屏）

（docstring 原文转写）

```latex
\alpha_e=\tfrac{2r^3}{3},\qquad \alpha_m=\tfrac{4r^3}{3}
```

出处：模块 docstring「物理口径」节（与 core/aperture_coupling.bethe_polarizability_circle 同源单源消费）。

docstring 逐字引文（防漂移钉）："αe=2r³/3、αm=4r³/3（H. A. Bethe," + ""Theory of Diffraction by Small Holes", Phys. Rev. 66:66, 1944；"

### 耦合/隔离幅值（E、M 支路同相相加/反相相消）

（docstring 原文转写）

```latex
|c_{\mathrm{coup}}|=\tfrac{2\omega}{ab}\bigl(\varepsilon_0\alpha_e Z_{10}+\mu_0\alpha_m/Z_{10}\bigr),\quad |c_{\mathrm{iso}}|=\tfrac{2\omega}{ab}\bigl|\varepsilon_0\alpha_e Z_{10}-\mu_0\alpha_m/Z_{10}\bigr|
```

出处：模块 docstring（功率归一化模反应式；两项同量纲、乘积无量纲幅值比已核实）。

docstring 逐字引文（防漂移钉）："|c_耦合| = (2ω/(ab))·(ε0αe·Z10 + μ0αm/Z10)    （E、M 同相相加）" + "|c_隔离| = (2ω/(ab))·|ε0αe·Z10 − μ0αm/Z10|    （反相相消）"

### 方向性极值（设计频率 E/M 平衡）

（docstring 原文转写）

```latex
\frac{M}{E}=2\Bigl(\frac{\beta}{k_0}\Bigr)^{\!2},\quad f=\frac{c_0}{\sqrt{2}\,a}\Rightarrow D\to\infty
```

出处：模块 docstring（隔离向严格相消→单孔方向性无究大；偏离设计频率 D=20lg[(E+M)/|E−M|] 退化，窄带单孔特性）。

docstring 逐字引文（防漂移钉）："M/E 比 = (αm/αe)·(η0/Z10)² = 2(β/k0)²：f = c0/(√2·a)（λg=2a）时隔离"

### Cohn 有限壁厚修正（opt-in）

（docstring 原文转写）

```latex
R=\frac{1}{1-(f/f_{\mathrm{res}})^2},\quad e^{-\alpha_{\mathrm{cut}}t}
```

出处：模块 docstring（f_res,m=c0/(1.706d) TE11 型、f_res,e=c0/(1.305d) TM01 型；孔颈截止衰减 Collin 截止波导节；近似层级如实声明）。

docstring 逐字引文（防漂移钉）："①孔口共振增强因子 R=1/(1−(f/f_res)²)，f_res 取对应圆波导截止常数"

### KD-1 出处注册（`src/rfauto/core/calc_families/bethe_hole.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/bethe_hole:<module>:01 | <module> | source | — | Nassiri 2003、Microwaves101 directional couplers 条目）；Cohn 有限 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `bethe_hole_coupler`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 近截止病态带显式拒绝（finline/rwg_mmt 同哲学）。
  - docstring 逐字引文："- f ≤ fc10 或 f/fc < 1.05（截止附近 λg 发散，Bethe 场系数失真）；"
- 一阶小孔假设域守卫（d>0.8·b 窄边比例上限同守卫族）。
  - docstring 逐字引文："d>λ0/3（小孔假设 d≪λ0）；"
- 修正因子发散域显式拒绝——不外推共振奇点。
  - docstring 逐字引文："Cohn 域 f≥0.9·f_res,m 显式拒绝（共振因子发散）；"
- 弱耦合单孔口径：不迭代加载修正、多孔阵只给间距口径。
  - docstring 逐字引文："（|c|≪1，不迭代加载修正）、无孔间互耦（多孔阵口径只给 λg/4 间距）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/bethe_hole.py:bethe_hole_coupler`

src/rfauto/core/calc_families/bethe_hole.py 公开符号 **1** 个（AST 机读）：

`bethe_hole_coupler`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

测试面（tests/unit 引用扫描，机读；合计 **79** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calc_sympy_oracle.py` | 12 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w3a_unsplit_bethe.py` | 18 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

