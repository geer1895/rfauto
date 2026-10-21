<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：if_digitizer

> IF 数字化欠采样规划族（架构批 W2-S2 席域 C4，R2_core_tier4 §③ Top6

| 字段 | 值 |
|---|---|
| 内核 ID | `if_digitizer` |
| 主模块 | `src/rfauto/core/calc_families/if_digitizer.py`（`rfauto.core.calc_families.if_digitizer`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/if_digitizer.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

测量接收机中频数字化面：带通采样可行区间规划（区号/最小采样率/推荐点折叠像与两端保护带）与候选采样率混叠折叠核验三态判定——噪声合成面与杂散落带面两邻之间的采样规划半边。

模块自述（docstring 首行，机读）：IF 数字化欠采样规划族（架构批 W2-S2 席域 C4，R2_core_tier4 §③ Top6

## 公式与口径

### 带通采样可行区间（VSW 1991 不等式）

（docstring 原文转写）

```latex
m=1:\ f_s\ge 2f_H,\quadm\ge 2:\ \frac{2f_H}{m}\le f_s\le\frac{2f_L}{m-1},\quadm=1..M,\ M=\lfloor f_H/BW\rfloor
```

出处：模块 docstring「物理口径」节（Vaughan-Scott-White 1991 IEEE Trans. SP 39(9) 带通采样定理；区间非空 ⇔ m ≤ f_H/BW 与 M 上界自洽；m=1 基带退化档 fs≥2f_H 无上界同节）。

docstring 逐字引文（防漂移钉）："2·f_H/m ≤ fs ≤ 2·f_L/(m−1)" + "最小可行采样率 = 2·f_H/M（最高区号档）。"

### 混叠折叠恒等式与防混叠判据

（docstring 原文转写）

```latex
f'\equiv\left|f-\mathrm{round}\!\left(\frac{f}{f_s}\right)f_s\right|\in\left[0,\frac{f_s}{2}\right],\quad\text{无混叠}\Leftrightarrow[f_L,f_H]\text{ 不跨 }kf_s/2\text{ 边界}
```

出处：模块 docstring（折叠恒等式第一性逐频严格成立；三态 alias_free_strict/boundary_touching/alias_overlap 如实三分，#122 不凑绿口径）。

docstring 逐字引文（防漂移钉）："f' ≡ |f − round(f/fs)·fs| ∈ [0, fs/2]" + "混叠不发生 ⇔ [f_L, f_H] 不跨越任何 k·fs/2 边界。三态判定（如实三分，"

### 孔径抖动 SNR 消费面（单源复用）

（docstring 原文转写）

```latex
\mathrm{SNR}_{\mathrm{jitter}}=-20\lg\left(2\pi f_{\mathrm{in}}\sigma_j\right),\quad f_{\mathrm{in}}=f_H\ (\text{模拟最高频率})
```

出处：模块 docstring（导入复用零公式复制——欠采样 ADC 的 dv/dt 由模拟频率决定非折叠后 IF；σ_j=0 → inf 以旗标透出，JSON 禁 inf）。

docstring 逐字引文（防漂移钉）："孔径抖动 SNR 直接消费 adc_budget.snr_jitter_db 同式（MT-007 口径" + "−20lg(2π·f_in·σ_j)；f_in 取模拟输入最高频率 f_H——欠采样 ADC 的 dv/dt"

### KD-1 出处注册（`src/rfauto/core/calc_families/if_digitizer.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/if_digitizer:<module>:01 | <module> | source | — | 1991, IEEE Trans. SP 39(9) 带通采样不等式 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `if_digitizer`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 三态如实：alias_free_strict=严格单区内（保护带 >0）、boundary_touching=零保护带理论点不判绿（fs 微扰即混叠）、alias_overlap=真实混叠拒绝；m=M 档两端相等即边界触碰档如实标注。
  - docstring 逐字引文："boundary_touching ：带缘恰落 k·fs/2（零保护带理论点，fs 微扰即混叠，"
- 边界防撞：adc_budget=噪声合成面（规划键出 f_H、噪声键给 SNR 消费衔接）、budget.if_plan_sweep=混频杂散落带面、cispr_detector=EMC 检波、cdr_jitter_mask=SI 抖动——本族只做采样/折叠区规划（抗混叠滤波器设计不在口径）。
  - docstring 逐字引文："- adc_budget=ADC 噪声合成面（孔径抖动/量化/kTC+ENOB）——本族=采样规划"
- 数值锚面（#118 独立算术）：fc=70MHz/BW=20MHz → M=4 区；fs=54MHz 折叠像 [6,26]MHz 保护带 6/1MHz；fs=40MHz 边界触碰、fs=50MHz 跨界混叠三态齐验；VSW 区号回查逐档对拍——锚树判据书。
  - docstring 逐字引文："- fs=54MHz（m=3 档内点）→ 原带居第 3 Nyquist 区（54–81MHz），折叠像"
- 全键越界显式 ValueError（f_L≤0 非物理拒绝）；bool 入参显式拒收（_finite_nb，fec_codes._as_int 同族先例——W3-S1 审查 P3-2）。
  - docstring 逐字引文："守卫：f_center_hz>BW/2（f_L>0）、bw_hz>0、fs_hz>0、sigma_jitter_s≥0；"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/if_digitizer.py:bandpass_sampling_plan`
- `src/rfauto/core/calc_families/if_digitizer.py:alias_fold_check`

src/rfauto/core/calc_families/if_digitizer.py 公开符号 **2** 个（AST 机读）：

`bandpass_sampling_plan`、`alias_fold_check`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w2s2_core_tier4.py`——引文："tests/unit/test_w2s2_core_tier4.py）"

测试面（tests/unit 引用扫描，机读；合计 **86** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w2s2_core_tier4.py` | 17 |
| `tests/unit/test_w4s1_review_guards.py` | 20 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

