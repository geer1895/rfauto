<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：measurement_drift

> 测量系统漂移建模族（aurora_f W2-S7，R2_core_tier3 §③ D6）：参考对

| 字段 | 值 |
|---|---|
| 内核 ID | `measurement_drift` |
| 主模块 | `src/rfauto/core/calc_families/measurement_drift.py`（`rfauto.core.calc_families.measurement_drift`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/measurement_drift.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

测量系统漂移建模：参考对 OLS 线性漂移率估计+置信带+去趋势校正 GUM 预算，与测量链 EWMA+CUSUM 控制图监控（复用 anchor_drift_spc 统计内核的同仓双源组合）。

模块自述（docstring 首行，机读）：测量系统漂移建模族（aurora_f W2-S7，R2_core_tier3 §③ D6）：参考对

## 公式与口径

### OLS 线性漂移率估计（等间隔索引）

（docstring 原文转写）

```latex
\hat\beta=\frac{\sum(t-\bar t)(y-\bar y)}{\sum(t-\bar t)^2},\quad \mathrm{se}(\hat\beta)=\sigma/\sqrt{S_{xx}}
```

出处：模块 docstring「线性漂移率估计」行（σ=调用方显式声明走正态 z 带；缺省 s/√Sxx 残差档 t 带 df=n−2）。

docstring 逐字引文（防漂移钉）："β̂=Σ(t−t̄)(y−ȳ)/Σ(t−t̄)²、截距 ȳ−β̂·t̄；斜率标准误" + "se(β̂)=σ/√Sxx"

### 去趋势校正与 GUM 逐点不确定度

（docstring 原文转写）

```latex
y_{corr,i}=y_i-\hat\beta\,(i-\bar t),\quad u_i=\sqrt{\sigma^2+\mathrm{se}^2(i-\bar t)^2}
```

出处：模块 docstring「线性漂移率估计」行（校正序列去线性趋势、均值保持；测量散布+校正杠杆臂两项 GUM 合成）。

docstring 逐字引文（防漂移钉）："u_i=√(σ²+se²·(i−t̄)²)（GUM 独立贡献平方合成：测量散布+校正杠杆臂"

### EWMA/CUSUM 控制图（复用 anchor_drift_spc 内核）

（docstring 原文转写）

```latex
z_i=\lambda x_i+(1-\lambda)z_{i-1},\quad \mathrm{UCL}_i=\bar z\pm L\sigma\sqrt{\tfrac{\lambda}{2-\lambda}\bigl(1-(1-\lambda)^{2i}\bigr)}
```

出处：模块 docstring「SPC 控制图」行（复用 anchor_drift_spc 机器同仓双源；控制限恒等式自检 ≤1e-12 构造级锚）。

docstring 逐字引文（防漂移钉）："z_i=λx_i+(1−λ)z_{i−1}、控制限 z̄±L·σ·√(λ/(2−λ)·(1−(1−λ)^{2i}))"

### KD-1 出处注册（`src/rfauto/core/calc_families/measurement_drift.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/measurement_drift:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `measurement_drift`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 短序列不内估 σ——anchor_drift_spc #118 家族纪律同款；监控键 sigma 必填 >0。
  - docstring 逐字引文："σ 必须显式声明（短序列不内估，"
- drifted/warning/stable 三态组合判定（anchor_drift_spc 组合规则同构；线有效性下限随线自报不硬算）。
  - docstring 逐字引文："三证据组合判定：EWMA/CUSUM/线性趋势三线，≥2 →"
- 族界：anchor_drift/anchor_drift_spc=锚面漂移、filter_temp_drift=器件温漂——本族=测量链读数序列（漂移率估计/校正预算/控制图告警），SPC 统计内核组合复用不替代。
  - docstring 逐字引文："本族=**测量系统漂移**"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/measurement_drift.py:measurement_drift_estimate`
- `src/rfauto/core/calc_families/measurement_drift.py:measurement_drift_monitor`

src/rfauto/core/calc_families/measurement_drift.py 公开符号 **2** 个（AST 机读）：

`measurement_drift_estimate`、`measurement_drift_monitor`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w2s7_ruthroff_gd_drift.py`——引文："tests/unit/test_w2s7_ruthroff_gd_drift.py"

测试面（tests/unit 引用扫描，机读；合计 **77** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w2s7_ruthroff_gd_drift.py` | 28 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

