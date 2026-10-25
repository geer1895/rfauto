<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：gnss_geometry

> GNSS 定位几何族（aurora_g W9-S2 席，R3_domain_expansion 视角4 E1 Top6

| 字段 | 值 |
|---|---|
| 内核 ID | `gnss_geometry` |
| 主模块 | `src/rfauto/core/calc_families/gnss_geometry.py`（`rfauto.core.calc_families.gnss_geometry`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/gnss_geometry.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

GNSS 定位几何三键：卫星视线几何→DOP 因子全族（GDOP/PDOP/HDOP/VDOP/TDOP）、方位角/仰角档同一 H 构建单源与 UERE→定位/授时误差恒等式+RSS 分解——导航接收机误差预算的几何底座（不做星历/轨道递推）。

模块自述（docstring 首行，机读）：GNSS 定位几何族（aurora_g W9-S2 席，R3_domain_expansion 视角4 E1 Top6

## 公式与口径

### 几何矩阵与 DOP 因子全族

（docstring 原文转写）

```latex
\mathbf Q=(\mathbf H^{\mathsf T}\mathbf H)^{-1},\quad \mathrm{GDOP}=\sqrt{\mathrm{tr}\,\mathbf Q},\quad \mathrm{PDOP}=\sqrt{Q_{xx}+Q_{yy}+Q_{zz}}
```

出处：Misra & Enge, Global Positioning System ch.6 / Parkinson & Spilker v.1 ch.11 教科书口径；H 每行 [u_x, u_y, u_z, 1]（u=用户→卫星单位视线矢量）。

docstring 逐字引文（防漂移钉）："Q = (HᵀH)⁻¹，  DOP 因子 = Q 对角元开方：" + "GDOP=√tr(Q)、PDOP=√(Q_xx+Q_yy+Q_zz)、HDOP=√(Q_xx+Q_yy)、"

### 方位角/仰角→视线矢量（ENU 惯例，同一 H 单源）

（docstring 原文转写）

```latex
\mathbf u=[\cos el\,\sin az,\ \cos el\,\cos az,\ \sin el]
```

出处：同章 ENU 惯例；两档对同一几何给同一 DOP 面（锚树 rel 1e-12 对照，#118 双路径）。

docstring 逐字引文（防漂移钉）："u = [cos(el)·sin(az), cos(el)·cos(az), sin(el)]" + "与位置矢量档共享同一 H 构建与求逆单源（_dop_report）"

### UERE→定位/授时误差与 RSS 分解恒等式

（docstring 原文转写）

```latex
\sigma_{3d}=\mathrm{GDOP}\cdot\mathrm{UERE},\quad \sigma_{3d}^2=\sigma_{horiz}^2+\sigma_{vert}^2+\sigma_{time}^2c^2
```

出处：Misra & Enge ch.6 等UERE 独立伪距误差口径；RSS 分解=tr(Q) 逐项恒等式。

docstring 逐字引文（防漂移钉）："σ_3d=GDOP·UERE、σ_horiz=HDOP·UERE、σ_vert=VDOP·UERE、" + "GDOP²=PDOP²+TDOP²、PDOP²=HDOP²+VDOP²"

### 理想几何最小值（4 星正四面体）

（docstring 原文转写）

```latex
\mathrm{GDOP}_{\min}=\sqrt{5/2}\approx 1.5811
```

出处：Kihara & Okada 1984 IEEE Trans.AES 4 星最优几何经典结果；任意单星追加 GDOP 单调不增（Sherman-Morrison，锚树数值钉）。

docstring 逐字引文（防漂移钉）："GDOP_min=√(5/2)≈1.5811、PDOP=3/2、HDOP=√(3/2)、VDOP=√3/2、TDOP=1/2"

### KD-1 出处注册（`src/rfauto/core/calc_families/gnss_geometry.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/gnss_geometry:<module>:01 | <module> | source | — | Kihara & Okada 1984 IEEE Trans.AES（4 星最优几何 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `gnss_geometry`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 星历/轨道递推与 Klobuchar 电离层延迟系数表不在本族（R3 审计列可弃，#122 如实缺席不凑）。
  - docstring 逐字引文："本族只做**定位几何/DOP/误差预算**，不做"
- HDOP/VDOP 的水平/垂直语义只在 ENU（x=East、y=North、z=Up）系下有物理意义；系旋转不变性=Q 对角元不变（GDOP/PDOP 迹量任意直角系逐位一致）。
  - docstring 逐字引文："本族位置矢量档建议 ENU"
- 任意单星追加使 HᵀH 加 PSD 秩一项 ⇒ Q Loewner 非增（锚树数值钉）——加星不劣化是几何恒等不是经验。
  - docstring 逐字引文："⇒ GDOP 单调不增"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/gnss_geometry.py:gdop_dop`
- `src/rfauto/core/calc_families/gnss_geometry.py:dop_from_satellite_geometry`
- `src/rfauto/core/calc_families/gnss_geometry.py:uere_to_position_error`

src/rfauto/core/calc_families/gnss_geometry.py 公开符号 **3** 个（AST 机读）：

`gdop_dop`、`dop_from_satellite_geometry`、`uere_to_position_error`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w9s2_core_domains.py`——引文："#222 triple-grep 证据（2026-10-19 本席开工实测）"

测试面（tests/unit 引用扫描，机读；合计 **67** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w9s2_core_domains.py` | 18 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

