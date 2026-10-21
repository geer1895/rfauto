<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：sar_geometry

> SAR 合成孔径几何指标族（架构批 W7-S3 席，R3_domain_expansion 视角4

| 字段 | 值 |
|---|---|
| 内核 ID | `sar_geometry` |
| 主模块 | `src/rfauto/core/calc_families/sar_geometry.py`（`rfauto.core.calc_families.sar_geometry`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/sar_geometry.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

SAR 合成孔径几何指标两键：聚焦方位分辨率 δ_az=D/2「悖论」恒等式（真实孔径对照面）与条带几何/PRF 不模糊窗/天线照明面——遥感场景收官件（成像几何指标，不做成像处理链）。

模块自述（docstring 首行，机读）：SAR 合成孔径几何指标族（架构批 W7-S3 席，R3_domain_expansion 视角4

## 公式与口径

### 聚焦 SAR 方位分辨率（「悖论」恒等式）

（docstring 原文转写）

```latex
\delta_{az}=\frac{D}{2},\quad L_{sa}=\frac{R\lambda}{D},\quad T_{sa}=\frac{L_{sa}}{v}
```

出处：Curlander & McDonough (Wiley 1991) ch.1/Skolnik IRS ch.21 教科书「悖论」恒等式——与作用距离 R、波长 λ 无关（变更 R/λ 输出逐位不变=本族头号测试锚，数值锤实测）。

docstring 逐字引文（防漂移钉）："δ_az = D/2" + "L_sa=R·λ/D 随 R、λ 变而分辨率不变——变更 R/λ 输出 δ_az 逐位不变，"

### 真实孔径（非聚焦）对照面

（docstring 原文转写）

```latex
\theta_{az}=\frac{\lambda}{D},\quad \delta_{ra}=\frac{R\lambda}{D}
```

出处：同章通用口径（可选 range_m+wavelength_m 同给走对照面；数值锤 2m 天线/0.03m 波长@800km：θ_az=0.859°、δ_ra=L_sa=12km）。

docstring 逐字引文（防漂移钉）："真实孔径波束宽 θ_az = λ/D  [rad]" + "真实孔径（非聚焦）分辨率 δ_ra = R·λ/D"

### 条带几何（平地近似，正侧视，角自星下点）

（docstring 原文转写）

```latex
R_{slant}=\frac{h}{\cos\theta},\quad G=h\tan\theta,\quad W_{ground}=h(\tan\theta_{far}-\tan\theta_{near}),\quad W_{slant}=R_{far}-R_{near}
```

出处：Curlander & McDonough ch.1 几何口径；数值锤 800km/20°–40°：R_near=851.3km、W_ground=380.1km、W_slant=193.0km（独立算术逐位）。

docstring 逐字引文（防漂移钉）："R_slant(θ) = h/cos(θ)" + "W_ground = h·(tan θ_far − tan θ_near)"

### PRF 不模糊窗+天线照明面

（docstring 原文转写）

```latex
z_{amb}=\frac{c}{2\,\mathrm{PRF}},\quad \beta=\frac{\lambda}{D_w},\quad W_{beam}=\frac{R_{mid}\,\beta}{\cos\theta_{mid}}
```

出处：同章几何口径；W_slant ≤ z_amb=相邻脉冲回波混叠判据（数值锤 PRF 2kHz → z_amb=74.9km，193km 条带如实判 within=False）；β=λ/D_w 波束宽、W_beam 中角照明幅宽。

docstring 逐字引文（防漂移钉）："z_amb = c/(2·PRF)" + "W_beam = R_mid·β/cos(θ_mid)"

### KD-1 出处注册（`src/rfauto/core/calc_families/sar_geometry.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/sar_geometry:<module>:01 | <module> | source | — | 出处：δ_az=D/2/θ_az=λ/D/条带几何=Curlander & McDonough (1991) 教科书 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `sar_geometry`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 条带几何平地近似；球形地球修正/聚束/TOPS 模式/距离徙动校正不在本键口径如实声明（DBS 多普勒梯度同缺席）。
  - docstring 逐字引文："地球修正不在本键口径如实声明。"
- 零新引源（R3 报告预声明「教科书级零风险锚」）；出处以模块 docstring 单源（Curlander & McDonough 1991+Skolnik IRS ch.21 同口径）。
  - docstring 逐字引文："风险锚"）；DBS 多普勒梯度/聚束/TOPS 模式/距离徙动校正不在本键口径。"
- 雷达场景分工：rcs_targets/radar_eq/radar_detection_ext/radar_clutter 为场景其余件；isac_ambiguity 波形指标面 no-go 同源尊重——本族只做成像几何指标收官遥感场景。
  - docstring 逐字引文："面）no-go 同源尊重——本族只做**成像几何指标**，不做成像处理链；"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/sar_geometry.py:sar_azimuth_resolution`
- `src/rfauto/core/calc_families/sar_geometry.py:sar_swath_coverage`

src/rfauto/core/calc_families/sar_geometry.py 公开符号 **3** 个（AST 机读）：

`sar_azimuth_resolution`、`sar_swath_coverage`、`sar_doppler_geometry`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w7s3_core_domains.py`——引文："物理口径（#1c/#300 出处纪律；Curlander & McDonough 教科书几何恒等式，"

测试面（tests/unit 引用扫描，机读；合计 **97** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w14s3_core_domains.py` | 25 |
| `tests/unit/test_w7s3_core_domains.py` | 23 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

