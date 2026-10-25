<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：cal_kit_verify

> 校准件完整性验证（aurora_f W3-S10 席域，R2_core_tier3 §③ D5 立项）。

| 字段 | 值 |
|---|---|
| 内核 ID | `cal_kit_verify` |
| 主模块 | `src/rfauto/core/calc_families/cal_kit_verify.py`（`rfauto.core.calc_families.cal_kit_verify`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/cal_kit_verify.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

校准件完整性验证：机械 SOLT 标准件一阶模型响应闭式与工程验收判据、校准后 verification 纹波法正反双解——校准件「使用链」之外的模型核验与质量验收端。

模块自述（docstring 首行，机读）：校准件完整性验证（aurora_f W3-S10 席域，R2_core_tier3 §③ D5 立项）。

## 公式与口径

### offset 传输线因子（机械件统一模型）

（docstring 原文转写）

```latex
\beta=\frac{2\pi f\sqrt{\varepsilon_r}}{c},\ \alpha_{\mathrm{dB/m}}=L_1\sqrt{f_{\mathrm{GHz}}},\quad e^{-2(\alpha_{np}+j\beta)l}\ (\alpha_{np}=A_{\mathrm{dB}}/8.6859)
```

出处：模块 docstring「offset 传输线因子」节（参考面在连接器；反射路径往返因子作用于各标准件闭式）。

docstring 逐字引文（防漂移钉）："β=2πf√εr/c（TEM 色散-free 档）、衰减系数按趋肤 √f 标度" + "（α_np=A_dB/8.6859）"

### 各标准件一阶闭式

（docstring 原文转写）

```latex
\Gamma_{short}=-e^{-2(\alpha+j\beta)l},\quad \Gamma_{open}=\frac{1-j\omega C_f Z_0}{1+j\omega C_f Z_0}e^{-2(\alpha+j\beta)l},\quad \Gamma_{load}=\frac{\mathrm{ratio}-1}{\mathrm{ratio}+1}
```

出处：模块 docstring「各标准件一阶闭式」节（open 边缘电容/through 损耗时延同节；load 失配地板 RL=−20lg|Γ₀| 理想档 None JSON 契约）。

docstring 逐字引文（防漂移钉）："short：Γ=−e^{−2(α+jβ)l}（理想 l=0/无耗 → |Γ|=1、相位 180°；" + "load：Z_L=ratio·Z0 → Γ₀=(ratio−1)/(ratio+1)（实数），偏置时"

### verification 纹波法（正反双解）

（docstring 原文转写）

```latex
pp_{\mathrm{dB}}=20\lg\frac{g+d}{g-d},\quad d=g\,\frac{10^{pp/20}-1}{10^{pp/20}+1},\quad |\Gamma_{meas}|\in[|g-d|,\,g+d]
```

出处：模块 docstring「纹波法」节（残余方向性 d=10^(D_db/20)；与 directional_bridge/vna_reflection_uncertainty 回损地板恒等式同仓双源三方互证）。

docstring 逐字引文（防漂移钉）："纹波峰峰 pp_dB = 20lg((g+d)/(g−d))，反向 d = g·(10^(pp/20)−1)" + "/(10^(pp/20)+1)。"

### KD-1 出处注册（`src/rfauto/core/calc_families/cal_kit_verify.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/cal_kit_verify:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `cal_kit_verify`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 验收判据=计量级惯例档（调用方可覆写）——非特定厂商 spec 不冒充（#300 归属纪律）；pass=适用判据合取，不适用判据如实 not_applicable。
  - docstring 逐字引文："（工程档缺省=计量级惯例带，调用方可覆写；非特定"
- 辐射开路频率相关电容高阶项（多参数拟合面）不在本域——iss_on_wafer 族=该频率多项式面（边界互补互指）；纹波法只含方向性单误差项（高阶纹波面归 vna_uncertainty）。
  - docstring 逐字引文："一阶模型——offset 线 Z0 失配/连接器重复性/"
- 包围旗标+回损判据按不通过如实记，不外推假窗；d=g 恰过零 dB 域峰峰无定义走 None JSON 契约。
  - docstring 逐字引文："（g>0）=|Γ_meas| 圆环包围原点、相位回绕域——纹波窗仍给但回损"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/cal_kit_verify.py:cal_kit_standard_response`
- `src/rfauto/core/calc_families/cal_kit_verify.py:cal_kit_verify_ripple`

src/rfauto/core/calc_families/cal_kit_verify.py 公开符号 **2** 个（AST 机读）：

`cal_kit_standard_response`、`cal_kit_verify_ripple`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w3s10_agc_calkit_sixport.py`——引文："aurora_f W3-S10 席域，R2_core_tier3 §③ D5 立项"

测试面（tests/unit 引用扫描，机读；合计 **85** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w3s10_agc_calkit_sixport.py` | 24 |
| `tests/unit/test_w5s18_core_edge.py` | 12 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

