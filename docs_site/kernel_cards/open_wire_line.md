<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：open_wire_line

> 平衡开线族（架构批 W10-S4 席，R3_domain_expansion 视角1 A2——rf_line

| 字段 | 值 |
|---|---|
| 内核 ID | `open_wire_line` |
| 主模块 | `src/rfauto/core/calc_families/open_wire_line.py`（`rfauto.core.calc_families.open_wire_line`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/open_wire_line.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

平衡开线两键：开架双线（双极坐标精确式）与单线对地（镜像定理精确式）的 Z0/C′/L′/延迟/趋肤衰减——rf_line 六型基板线之外唯一无基板开架平行线（模型域全域精确，非细线近似档）。

模块自述（docstring 首行，机读）：平衡开线族（架构批 W10-S4 席，R3_domain_expansion 视角1 A2——rf_line

## 公式与口径

### 开架双线（双极坐标精确式）

（docstring 原文转写）

```latex
Z_0=\frac{\eta_0}{\pi\sqrt{\varepsilon_r}}\,\mathrm{acosh}\!\frac{D}{2a},\quad C'=\frac{\pi\varepsilon_0\varepsilon_r}{\mathrm{acosh}(D/2a)}
```

出处：Ramo-Whinnery-Van Duzer §2.6 / Pozar 4th ed eq.(2.74)（与 core/corona.py two_wire 几何因子 arcosh(D/2r) 同核双源）；D≫a 渐近对数式与 acosh 式逐位同值（同式双形态锚）。

docstring 逐字引文（防漂移钉）："Z0 = (η0/(π·√εr))·acosh(D/(2a))" + "C' = π·ε0·εr/acosh(D/(2a))"

### 单线对地（镜像定理精确式）

（docstring 原文转写）

```latex
Z_0=\frac{\eta_0}{2\pi\sqrt{\varepsilon_r}}\,\mathrm{acosh}\!\frac{h}{a}\approx\frac{60}{\sqrt{\varepsilon_r}}\ln\frac{2h}{a}
```

出处：镜像定理（wire+镜像电荷 −q 恰为 D=2h 双线奇激励半问题，midplane 精确等位面；Jackson §2.2 级教科书恒等式）。

docstring 逐字引文（防漂移钉）："Z0 = (η0/(2π·√εr))·acosh(h/a)     ≈ (60/√εr)·ln(2h/a)（h≫a）" + "C' = 2π·ε0·εr/acosh(h/a)"

### 镜像退化恒等式（跨键）

（docstring 原文转写）

```latex
Z_{0,\mathrm{wg}}(h)=\tfrac{1}{2}Z_{0,\mathrm{2w}}(D=2h)
```

出处：#118 跨键恒等（对地电压=差分电压之半）逐位可验；h→a⁺ 时 acosh→0 → Z0→0（导线触地=短路，物理极限行为正确）。

docstring 逐字引文（防漂移钉）："Z0_wg(h) = Z0_two_wire(D=2h)/2——激励"

### 趋肤衰减面（freq+conductivity 同给时）

（docstring 原文转写）

```latex
R'=\frac{R_s}{2\pi a},\quad \alpha_c=\frac{R'}{2Z_0}\ \mathrm{Np/m}
```

出处：Rs=√(πfμ0/σ)（与 core/coax_line/conductor_loss 同核三源）；低损线通用式（Pozar eq.(2.87) 口径）→dB=8.686·Np。

docstring 逐字引文（防漂移钉）："R'=Rs/(2πa)，双线回路两导体串联" + "αc=R'/(2Z0) Np/m"

### KD-1 出处注册（`src/rfauto/core/calc_families/open_wire_line.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/open_wire_line:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `open_wire_line`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- rf_line=基板线六型（有基板口径）；coax_line=同轴嵌套；corona=电晕起始场强判据（arcosh 仅几何因子同核、量纲 Ω·m）；wirebond=键合线部分电感（无传输线参数面）。
  - docstring 逐字引文："本族只做开架平行线单位长参数（Z0/C'/L'/延迟/趋肤衰减）。"
- 近距双线的邻近效应修正不建模；σ=None 或 freq=None 不出衰减面（如实缺档）。
  - docstring 逐字引文："邻近效应修正不建模（如实边界；σ=None 或 freq=None 不出衰减面）。"
- arccosh(2h/a) 形态在 h→a 给非零 Z0=非物理，显式拒绝；h/a 半径口径与 2h/d 直径口径等价。
  - docstring 逐字引文："故本键拒绝该误形态——h/a 为半径口径，直径口径 2h/d 与"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/open_wire_line.py:open_two_wire_line`
- `src/rfauto/core/calc_families/open_wire_line.py:open_wire_over_ground`

src/rfauto/core/calc_families/open_wire_line.py 公开符号 **2** 个（AST 机读）：

`open_two_wire_line`、`open_wire_over_ground`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w10s4_core_domains.py`——引文："平衡开线族（架构批 W10-S4 席，R3_domain_expansion 视角1 A2——rf_line"

测试面（tests/unit 引用扫描，机读；合计 **73** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w10s4_core_domains.py` | 24 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

