<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：directional_bridge

> 定向电桥/反射计桥（aurora_f W2-S6 席域，R2_core_tier3 §③ D4 立项）。

| 字段 | 值 |
|---|---|
| 内核 ID | `directional_bridge` |
| 主模块 | `src/rfauto/core/calc_families/directional_bridge.py`（`rfauto.core.calc_families.directional_bridge`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/directional_bridge.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

Wheatstone 电阻反射计桥器件面：三参考臂节点分析精确 S 矩阵（理想对称档直通/反射耦合、三口全匹配、方向性无穷）与反射计响应闭式（方向性-源匹配残差→被测 Γ 误差双界与回损测量链地板恒等式）。

模块自述（docstring 首行，机读）：定向电桥/反射计桥（aurora_f W2-S6 席域，R2_core_tier3 §③ D4 立项）。

## 公式与口径

### 理想对称桥 S 矩阵（节点分析精确解）

（docstring 原文转写）

```latex
\mathbf S=\begin{bmatrix}0&0.5&0\\0.5&0&-0.5\\0&-0.5&0\end{bmatrix}
```

出处：模块 docstring「理想 S 矩阵闭式」节（对称四臂、端口 3 Z0 端接；第 2 行功率和 0.25+0+0.25=0.5<1=臂电阻耗散 50%；反射路径总预算=乘积 0.25；方向性 ∞=S31=0 机器精度）。

docstring 逐字引文（防漂移钉）："直通 6.02 dB（|S21|=0.5）、反射耦合 6.02 dB（|S32|=0.5，乘积" + "三口全匹配（S11=S22=S33=0——"

### 反射计响应与归一去嵌

（docstring 原文转写）

```latex
b_3/a_1=S_{31}+\frac{S_{32}S_{21}\Gamma}{1-S_{22}\Gamma},\quad \Gamma_{\mathrm{meas}}=\frac{\Gamma}{1-\Gamma s}+d
```

出处：模块 docstring「反射计响应闭式」节（s=S22 源匹配误差项二阶小量 |Γ²s|、d=S31/k 剩余方向性矢量 |d|=10^(−D/20)；误差矢量相位未知→同相/反相双界如实报告）。

docstring 逐字引文（防漂移钉）："b3/a1 = S31 + S32·S21·Γ/(1−S22·Γ)；按耦合积 k=|S32·S21| 归一去嵌：" + "Γ_meas = Γ/(1−Γ·s) + d"

### 完美负载回损地板（方向性恒等式）

（docstring 原文转写）

```latex
|\Gamma|=0\Rightarrow RL_{\mathrm{meas}}=D,\quadD\to\infty\Rightarrow\Gamma_{\mathrm{meas}}\to\frac{\Gamma}{1-\Gamma s}
```

出处：模块 docstring（与 vna_reflection_uncertainty 的回损地板=−directivity_db 同仓双源；Γ_meas≈Γ+d+s·Γ² 一阶展开=Rytting 单端口误差模型的器件级特例）。

docstring 逐字引文（防漂移钉）："完美负载（Γ=0）读回损=D（方向性地板" + "同仓双源）；D→∞ 残差→0，只剩源匹配项 Γ/(1−Γs)；|Γ|≪1 单误差项"

### KD-1 出处注册（`src/rfauto/core/calc_families/directional_bridge.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/directional_bridge:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `directional_bridge`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 边界防撞：multisection_coupler/bethe_hole/coupled_line=定向耦合器族（线耦合孔耦机构）、isolator_circulator=非互易件——本族只做电阻桥反射计件（Wheatstone 平衡方向性机构）。
  - docstring 逐字引文："multisection_coupler/bethe_hole/coupled_line=定向**耦合器**族（线"
- six_port=六端口反演架构（多端口功率检波干涉法）——本族可为其供前级 S 矩阵，反演只在 six_port 层；vna_uncertainty=误差箱传播/不确定度面（本族的下游预算面）。
  - docstring 逐字引文："本族=两端口差分检波电阻桥器件面，语义不同域共存互指不互代；"
- 出处分级：对称四臂闭式=本席节点分析推导落地（键内对称档自检+测试侧独立重算 #118）；Pozar Ch.12 反射计测量口径二级转引如实标注。
  - docstring 逐字引文："对称四臂 S 矩阵闭式为本席节点分析推导落地（键内对称档逐位自检，"
- 容差档 arm_tolerance_pct 工程上限、gamma_mag∈[0,1]、directivity_db>0 或 None=完美——越界一律显式 ValueError。
  - docstring 逐字引文："守卫：z0_ohm>0；arm_tolerance_pct∈[0,0.2]（工程容差档，0=理想平衡）；"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/directional_bridge.py:directional_bridge_s_matrix`
- `src/rfauto/core/calc_families/directional_bridge.py:directional_bridge_response`

src/rfauto/core/calc_families/directional_bridge.py 公开符号 **2** 个（AST 机读）：

`directional_bridge_s_matrix`、`directional_bridge_response`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w2s6_mixer_bridge_switch.py`——引文："定向电桥/反射计桥（aurora_f W2-S6 席域，R2_core_tier3 §③ D4 立项）。"

测试面（tests/unit 引用扫描，机读；合计 **98** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w2s6_mixer_bridge_switch.py` | 25 |
| `tests/unit/test_w3s10_agc_calkit_sixport.py` | 24 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

