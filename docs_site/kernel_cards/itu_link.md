<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：itu_link

> itu_link 族（AP-6 ITU 大气/雨衰键面，SD 部分件残差收口，追加尾位；

| 字段 | 值 |
|---|---|
| 内核 ID | `itu_link` |
| 主模块 | `src/rfauto/core/calc_families/itu_link.py`（`rfauto.core.calc_families.itu_link`） |
| 同族模块 | `src/rfauto/core/itu_atmosphere.py` |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/itu_link.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

ITU-R 大气/雨衰键面：P.676-13 逐线大气气体 specific attenuation、P.838-3 Gauss 和式雨衰减与 P.618-13 长期雨衰全链（逐中间量留痕）——系数表逐值录入并经官方 Table 5 全量频点对拍。

模块自述（docstring 首行，机读）：itu_link 族（AP-6 ITU 大气/雨衰键面，SD 部分件残差收口，追加尾位；

## 公式与口径

### 大气气体 specific attenuation（P.676-13 Annex 1 逐线求和）

（docstring 原文转写）

```latex
\gamma=0.1820\,f\,N''(f)\ [\mathrm{dB/km}],\quadN''=N''_{\mathrm{Oxygen}}+N''_{\mathrm{WaterVapour}}
```

出处：模块 docstring（itu_atmosphere 式面已逐式对照官方 PDF 视觉核verify——Table 1 全 44 行+Table 2 全 35 行经 pypdf 机械抽取+前席 dump 553 值对拍 all-equal；有效域 f∈(0,1000]GHz）。

docstring 逐字引文（防漂移钉）："γ=0.1820·f·N″(f)；p_hpa 为干空气分压（总压 ptot=p+e）、θ=300/T、" + "逐线求和：O2 44 行+H2O 35 行谱线+干空气连续谱，式(1)-(9) 原文式号"

### 雨衰特征衰减（P.838-3 Gauss 和式）

（docstring 原文转写）

```latex
\gamma_R=k\,R^{\alpha}\ [\mathrm{dB/km}],\quad\log_{10}k=\textstyle\sum_j a_je^{-\left(\frac{\log_{10}f-b_j}{c_j}\right)^2}+m_k\log_{10}f+c_k
```

出处：模块 docstring rain_specific_attenuation 键面（系数经官方 Table 5 全量频点对拍=≤4 位有效数字印刷舍入界；pol 只收 h/v 线极化直取档，插值式不注册）。

docstring 逐字引文（防漂移钉）："γ_R=k·R^α；式(2)/(3) Gauss 和式给 kH/kV/αH/αV，Tables 1-4 系数经官方" + "Table 5 全量 116 频点对拍 max rel dev 0.112%，证据 runs/ap8/）。"

### 长期雨衰全链（P.618-13 §2.2.1.1 Step1-9）

（docstring 原文转写）

```latex
h_R=h_0+0.36,\ L_s=\tfrac{h_R-h_s}{\sin\theta},\ r_{0.01}=\tfrac{1}{1+0.78\sqrt{L_G\gamma_R/f}-0.38(1-e^{-2L_G})},\ A_{0.01}=\gamma_R L_E
```

出处：模块 docstring（Step1-9 逐中间量留痕——l_s/l_g/γR/r0.01/ζ/χ/ν0.01/L_E 全链对拍面；A0.01=γR·LE 式(7)；Step10 Ap 换算纯辅助走 core.rain_attenuation_ap 组合消费）。

docstring 逐字引文（防漂移钉）："hR=h0+0.36→Ls（θ≥5° 式(1)/θ<5° 式(2)）→LG=Ls·cosθ→γR（P.838-3" + "r0.01 = 1/(1+0.78√(LG·γR/f)−0.38(1−e^{−2LG}))（式(5)）"

### KD-1 出处注册（`src/rfauto/core/calc_families/itu_link.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/itu_link:<module>:01 | <module> | source | — | ITU-R P.676-13；ITU-R P.838-3；ITU-R P.618-13 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `itu_link`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 数据面边界：P.837 雨率图与 P.839 冻结层高度均为 ITU 数字地图数据文件（PV-011 不捆绑）——R0.01/h0 调用方显式输入，本地实测/气象数据直接进链，公式面零数据依赖可用。
  - docstring 逐字引文："R0.01/h0 维持调用方显式输入（P.837/P.839 数字地图数据文件 PV-011 不捆"
- rain_rate_r001_mmh 占位显式 ValueError 语义不变（P.837 系数 UNVERIFIED 如实不建模——#122 如实口径）；hR<=hs 或 R0.01=0 走原文零分支 a001_db=0+zero_reason。
  - docstring 逐字引文："P.837 R0.01 系数仍 UNVERIFIED（ITU 数据"
- 极化域：任意仰角/倾角插值式（圆/线极化转换）不注册——P.618 链路面只消费 h/v 直取档（链路面与插值面边界如实）。
  - docstring 逐字引文："pol 只收 'h'/'v'（线极化直取；任意仰角/倾角插值式(4)/(5) 不注册——"
- 输出 a001_db 后由 core.rain_attenuation_ap 组合消费（sat_link 链路面）——本族只做键面收口，内核式面在 core/itu_atmosphere（纯函数零 IO）。
  - docstring 逐字引文："由 core.rain_attenuation_ap 组合消费（sat_link 链路面）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/itu_link.py:gaseous_attenuation`
- `src/rfauto/core/calc_families/itu_link.py:rain_specific_attenuation`
- `src/rfauto/core/calc_families/itu_link.py:rain_attenuation_r001`

src/rfauto/core/calc_families/itu_link.py 公开符号 **5** 个（AST 机读）：

`gaseous_attenuation`、`rain_specific_attenuation`、`rain_attenuation_r001`、`cloud_specific_attenuation`、`cloud_attenuation_slant`

src/rfauto/core/itu_atmosphere.py 公开符号 **26** 个（AST 机读）：

`OxygenLine`、`WaterLine`、`RainCoeffs`、`has_676_tables`、`has_838_coeffs`、`data_status`、`gamma_gasses_db_per_km`、`gamma_rain_db_per_km`、`rain_attenuation_db`、`rain_rate_r001_mmh`、`effective_rain_height_km`、`slant_path_rain_km`、`rain_attenuation_r001`、`rain_attenuation_ap`、`saturation_vapour_pressure_hpa`、`vapour_pressure_hpa`、`refractivity_wet`、`scintillation_nwet`、`scintillation_sigma_ref_db`、`scintillation_std_db`、`scintillation_fade_db`、`xpd_rain_db`、`water_permittivity_p840`、`gamma_cloud_db_per_km`、`kl_mass_cloud_db_per_mm`、`cloud_attenuation_slant`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_ap6_dr8_calculator_keys.py`——引文："Tables 1-4 系数已由 AP-8 批逐值录入，验证链见该模块 docstring 与"
- `tests/unit/test_w4_c_p10_itu_p618.py`——引文："P.618-13 式面（W4-C P10 批 2026-10-05，已逐式对照官方 PDF 视觉核verify）"

测试面（tests/unit 引用扫描，机读；合计 **184** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_ap6_dr8_calculator_keys.py` | 12 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w14s3_core_domains.py` | 25 |
| `tests/unit/test_w4_c_p10_itu_p618.py` | 26 |
| `tests/unit/test_formula_provenance.py` | 17 |
| `tests/unit/test_itu_atmosphere.py` | 28 |
| `tests/unit/test_sat_link.py` | 27 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

