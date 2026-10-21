<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：wilkinson_unequal

> Wilkinson 不等分功分器综合（架构批 W3-A 席，R2 空白域 G6）。

| 字段 | 值 |
|---|---|
| 内核 ID | `wilkinson_unequal` |
| 主模块 | `src/rfauto/core/calc_families/wilkinson_unequal.py`（`rfauto.core.calc_families.wilkinson_unequal`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/wilkinson_unequal.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

二路不等分 Wilkinson 综合（Pozar K 口径）：功分比 K → 两臂 λ/4 特性阻抗 + 隔离电阻（含臂端电阻分配）+ 几何均值输出变换段——闭式与节点导纳网络解算互为独立裁判（#118）。

模块自述（docstring 首行，机读）：Wilkinson 不等分功分器综合（架构批 W3-A 席，R2 空白域 G6）。

## 公式与口径

### 功分比与两臂 λ/4 特性阻抗

（docstring 原文转写）

```latex
K^2=\frac{P_3}{P_2},\qquad Z_{02}=Z_0\sqrt{K(1+K^2)},\qquad Z_{03}=Z_0\sqrt{\frac{1+K^2}{K^3}}=\frac{Z_{02}}{K^2}
```

出处：模块 docstring「公式口径」节（Pozar 4th ed. §7.3 不等分节；受惠端=低阻臂，由 λ/4 臂功率流与隔离等压条件直接导出）。

docstring 逐字引文（防漂移钉）："Z02 = Z0·√(K(1+K²))" + "Z03 = Z0·√((1+K²)/K³) = Z02/K²（端口 3 臂）"

### 隔离电阻与臂端分配（Parad–Moynihan）

（docstring 原文转写）

```latex
R=Z_0\frac{1+K^2}{K},\qquad R_2=\frac{Z_0}{K},\qquad R_3=K\,Z_0,\qquad R_2+R_3=R
```

出处：模块 docstring（两端电阻分配取 Parad–Moynihan 原文约定：受惠臂端=低阻端；中心频率 S 矩阵只依赖总串联 R）。

docstring 逐字引文（防漂移钉）："R  = Z0(1+K²)/K" + "R2 = Z0/K（端口 2 臂端）、R3 = K·Z0（端口 3 臂端），R2+R3=R"

### 输出变换段（几何均值选型）

（docstring 原文转写）

```latex
Z_{04}=Z_0\sqrt{K},\qquad Z_{05}=\frac{Z_0}{\sqrt{K}},\qquad Z_{04}\,Z_{05}=Z_0^2
```

出处：模块 docstring（Parad–Moynihan 几何均值选型，带宽最优化）。

docstring 逐字引文（防漂移钉）："Z04 = Z0·√K （端口 2 侧）、Z05 = Z0/√K （端口 3 侧）"

### KD-1 出处注册（`src/rfauto/core/calc_families/wilkinson_unequal.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/wilkinson_unequal:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `wilkinson_unequal`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- K 无上限——超大 K 的臂/电阻比超常规微带可实现域时 practical_split=False 如实标注，不拒绝不外推。
  - docstring 逐字引文："结果字段 practical_split=False 如实标注，不拒绝）。"
- 闭式之外以通用节点导纳分析（λ/4 线 j/Z 倒纳网络）独立重算全 S 矩阵作裁判。
  - docstring 逐字引文："独立重算全 S 矩阵作裁判（#118：网络解算器与设计闭式互为独立来源）。"
- K=1 精确退化到经典等分 Wilkinson——退化锚与文献锚（Microwaves101）都在档。
  - docstring 逐字引文："K=1 退化锚 = 经典等分 Wilkinson：两臂 √2·Z0、R=2·Z0、变换段=Z0（同书"
- 只出中心频率理论量（说明字段）——带内频率响应不在本键声明域。
  - docstring 逐字引文："带宽内隔离/回损按臂电长度 90° 设计点随频退化（本键只出 f0 闭式）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/wilkinson_unequal.py:unequal_split_wilkinson`

src/rfauto/core/calc_families/wilkinson_unequal.py 公开符号 **1** 个（AST 机读）：

`unequal_split_wilkinson`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w3a_unsplit_bethe.py`——引文："50Ω、P2/P3=2（K=1/√2）→ ZA=51.5Ω、ZB=103Ω、R=106.07Ω、变换段"

测试面（tests/unit 引用扫描，机读；合计 **67** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w3a_unsplit_bethe.py` | 18 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

