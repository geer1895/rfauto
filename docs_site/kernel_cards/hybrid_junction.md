<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：hybrid_junction

> 混合结/魔 T/波导三口结族（架构批 A5-A 席域 2，R7 候补 G8 大件首拆席）。

| 字段 | 值 |
|---|---|
| 内核 ID | `hybrid_junction` |
| 主模块 | `src/rfauto/core/calc_families/hybrid_junction.py`（`rfauto.core.calc_families.hybrid_junction`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/hybrid_junction.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

混合结器件面：魔 T 理想四口 S 矩阵（和差臂隔离/均分/相位行为四约束钉死）、并联星形与串联环形三口结功率波闭式、和差合成能量守恒——结器件理想口径，不出波导尺寸综合。

模块自述（docstring 首行，机读）：混合结/魔 T/波导三口结族（架构批 A5-A 席域 2，R7 候补 G8 大件首拆席）。

## 公式与口径

### 魔 T 理想四口 S 矩阵（四约束钉死）

（docstring 原文转写）

```latex
\mathbf S=\frac{1}{\sqrt{2}}\begin{bmatrix}0&1&1&0\\1&0&0&1\\1&0&0&-1\\0&1&-1&0\end{bmatrix}
```

出处：模块 docstring「物理口径」节（Pozar §7.5 混合结口径；④和差相位行为——激励和口侧臂同相各 1/√2、差口反相各 1/√2；符号约定写死上式口径，测试侧幺正+隔离+3dB+相位四约束独立复核）。

docstring 逐字引文（防漂移钉）："S = (1/√2)·[[0, 1, 1, 0]," + "四约束钉死：①幺正（无耗）②S14=S41=0（E/H 臂隔离）③匹配 S_ii=0"

### H 面/E 面三口结功率波闭式（KCL/KVL 对偶）

（docstring 原文转写）

```latex
\text{H 面（并联星形）}:\ S_{ii}=-\frac{1}{3},\ S_{ij}=+\frac{2}{3};\quad\text{E 面（串联环形）}:\ S_{ii}=+\frac{1}{3},\ S_{ij}=-\frac{2}{3}
```

出处：模块 docstring（理想对称无耗互易功率波口径第一性推导；幺正+互易+镜像对称+E/H 对偶四约束钉死；侧臂均分 20lg(2/3)=−3.5218dB、支臂回损 9.5424dB 常数）。

docstring 逐字引文（防漂移钉）："并联星形结（H 面，共电压节点，KCL 推导）：S_ii=−1/3、S_ij=+2/3；" + "串联环形结（E 面，KVL 对偶）：S_ii=+1/3、S_ij=−2/3。"

### 和差合成与能量守恒（幺正推论）

（docstring 原文转写）

```latex
b_{\mathrm{sum}}=\frac{a_2+a_3}{\sqrt{2}},\quadb_{\mathrm{diff}}=\frac{a_2-a_3}{\sqrt{2}},\quad|b_{\mathrm{sum}}|^2+|b_{\mathrm{diff}}|^2=|a_2|^2+|a_3|^2
```

出处：模块 docstring（等幅同相→隔离 null、反相→和口零、正交→恰各半 −3.0103dB 恒等；和差键与四口矩阵乘 b=S·a 匹配负载口径跨键逐位互证）。

docstring 逐字引文（防漂移钉）："和差合成：b_sum=(a2+a3)/√2、b_diff=(a2−a3)/√2；能量守恒" + "|b_sum|²+|b_diff|²=|a2|²+|a3|² 恒等（幺正推论）；等幅同相→差口零"

### KD-1 出处注册（`src/rfauto/core/calc_families/hybrid_junction.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/hybrid_junction:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `hybrid_junction`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 拓扑必然性：无耗互易三口全匹配不可能（匹配三端口需非互易，环行器另域）——S11=±1/3 是拓扑必然非实现缺陷，如实按四约束口径落定。
  - docstring 逐字引文："④对偶 S_E=−S_H。无耗互易三口**全匹配不可能**（S11=±1/3 是拓扑必然"
- 符号约定纪律：印刷矩阵各文献符号约定不一（端口参考方向选择所致，部分 ±1/2 表违反幺正）——本实现按幺正四约束口径写死，测试侧 KCL/KVL 线性方程组独立重解异路线互证。
  - docstring 逐字引文："（端口参考方向选择所致，部分 ±1/2 表违反幺正），本实现按四约束口径"
- 边界防撞：unequal_split_wilkinson/bethe_hole_coupler=综合键（出几何尺寸）、ratrace=模板锚判读、butler_matrix 内嵌 90° 混合环块（本族为 180° 混合结）——本族只做结器件理想 S 矩阵口径，E/H 臂口径尺寸设计属波导模板域如实不做。
  - docstring 逐字引文："- unequal_split_wilkinson/bethe_hole_coupler=电阻功分/孔耦合**综合**键"
- excite_port/tee_type 白名单、功率幅值域界（幅值下溢防呆）；隔离 null 份额口径 frac<1e-24 → dBm 如实 None（浮点理想零不冒充伪精确值）——越界一律显式 ValueError。
  - docstring 逐字引文："守卫：excite_port∈{1,2,3,4}；tee_type∈{h_plane,e_plane}；p2_dbm/p3_dbm"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/hybrid_junction.py:magic_tee_s_matrix`
- `src/rfauto/core/calc_families/hybrid_junction.py:waveguide_tee_s_matrix`
- `src/rfauto/core/calc_families/hybrid_junction.py:hybrid_sum_difference`

src/rfauto/core/calc_families/hybrid_junction.py 公开符号 **3** 个（AST 机读）：

`magic_tee_s_matrix`、`waveguide_tee_s_matrix`、`hybrid_sum_difference`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_a5a_saw_hybrid.py`——引文："（KCL/KVL 独立重解见锚树）；'3dB 均分'直觉属失配理想化——无耗"

测试面（tests/unit 引用扫描，机读；合计 **69** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a5a_saw_hybrid.py` | 20 |
| `tests/unit/test_calculators.py` | 49 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

