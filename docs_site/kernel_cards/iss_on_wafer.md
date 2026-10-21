<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：iss_on_wafer

> 在片 ISS 校准件族（架构批 W5-S18 席域，R2_core_tier3 边际池立项）。

| 字段 | 值 |
|---|---|
| 内核 ID | `iss_on_wafer` |
| 主模块 | `src/rfauto/core/calc_families/iss_on_wafer.py`（`rfauto.core.calc_families.iss_on_wafer`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/iss_on_wafer.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

在片 ISS 校准件族：共面开路/短路/负载/直通的频率多项式寄生模型闭式响应与一端口三项误差模型提取——任意非理想标准定义下 Ed/Es/Er 闭式线性反解。

模块自述（docstring 首行，机读）：在片 ISS 校准件族（架构批 W5-S18 席域，R2_core_tier3 边际池立项）。

## 公式与口径

### 开路/短路频率多项式（套件定义惯例格式）

（docstring 原文转写）

```latex
C(f)=c_0+c_1f+c_2f^2+c_3f^3\ (\mathrm{fF}),\quad L(f)=l_0+l_1f+l_2f^2+l_3f^3\ (\mathrm{pH})
```

出处：模块 docstring「开路」「短路」节（Keysight 机械/在片套件定义 C0..C3/L0..L3 多项式惯例格式二级转引——格式出处而非厂商数值）。

docstring 逐字引文（防漂移钉）："C(f) = c₀ + c₁·f + c₂·f² +" + "L(f) = l₀ + l₁·f + l₂·f² +"

### 一端口三项误差模型（Cramer 闭式）

（docstring 原文转写）

```latex
\Gamma_{meas}=E_d+\frac{E_r\Gamma}{1-E_s\Gamma}\ \Rightarrow\ \Gamma=\frac{m-E_d}{E_r+E_s(m-E_d)}
```

出处：模块 docstring「一端口三项误差模型」节（恒等变形 m_i=Ed+Er′·Γ_i+Es·(m_i·Γ_i)、Er′=Er−Ed·Es 的 3×3 线性方程组 Cramer 闭式；Pozar VNA 校准章同款）。

docstring 逐字引文（防漂移钉）："Γ_meas = Ed + Er·Γ/(1 − Es·Γ)。给定三个已知标准定义 Γ_i 与原" + "DUT 回收：Γ = (m − Ed)/(Er + Es·(m − Ed))。"

### 直通匹配线（损耗时延恒等式）

（docstring 原文转写）

```latex
S_{21}=e^{-(\alpha_{np}+j\beta)l},\quad \tau=\frac{l\sqrt{\varepsilon_{eff}}}{c},\quad |S_{21}|=10^{-IL/20}
```

出处：模块 docstring「直通」节（α_np=IL/(20·log10 e) 精确 dB→Np 换算，平损耗档）。

docstring 逐字引文（防漂移钉）："τ = l·√εeff/c（ns）；|S21| = 10^(−IL/20) 恒等式；理想 l=0 → S21=1。"

### KD-1 出处注册（`src/rfauto/core/calc_families/iss_on_wafer.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/iss_on_wafer:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `iss_on_wafer`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 套件定义来源自负——不冒充任何厂商 spec 数值（#122/#300）；逐频点代入值必须 ≥0（无源性检验，负值显式拒绝）。
  - docstring 逐字引文："②多项式系数值须调用"
- 分工面：cal_kit_verify=同轴机械 SOLT 件验证端（连接器/offset 空气线）、trl_solt=使用链理想档——本族=共面在片件多项式寄生面；理想标准档退化回 trl_solt 同式逐位互证。
  - docstring 逐字引文："本族=**共面在片件**"
- 三项误差模型不含串扰/漂移项；deembed=OpenShort 去嵌泛用件不重复实现（探针垫去嵌半边如实不并）。
  - docstring 逐字引文："差模型不含串扰/漂移项（八项以上归 trl_solt/thz_vna 级联域）；"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/iss_on_wafer.py:iss_standard_response`
- `src/rfauto/core/calc_families/iss_on_wafer.py:iss_oneport_cal_extract`

src/rfauto/core/calc_families/iss_on_wafer.py 公开符号 **2** 个（AST 机读）：

`iss_standard_response`、`iss_oneport_cal_extract`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w5s18_core_edge.py`——引文："架构批 W5-S18 席域，R2_core_tier3 边际池立项"

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
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

