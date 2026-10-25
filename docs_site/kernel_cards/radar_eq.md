<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：radar_eq

> 雷达方程与检测统计族（aurora36 W4-A 席，R2 空白域 G1）。

| 字段 | 值 |
|---|---|
| 内核 ID | `radar_eq` |
| 主模块 | `src/rfauto/core/calc_families/radar_eq.py`（`rfauto.core.calc_families.radar_eq`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/radar_eq.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

雷达方程与检测统计面：基本雷达方程 SI/dB 双口径互斥闭式、Albersheim 检测因子三量互算经验式（Swerling 0 如实不冒充）、CA-CFAR 门限因子与 Swerling 1 检测概率闭式——雷达链路预算三件套。

模块自述（docstring 首行，机读）：雷达方程与检测统计族（aurora36 W4-A 席，R2 空白域 G1）。

## 公式与口径

### 基本雷达方程（单基地同天线、匹配接收）

（docstring 原文转写）

```latex
P_r=\frac{P_t G^2 \lambda^2 \sigma}{(4\pi)^3 R^4 L}
```

出处：模块 docstring（Skolnik *Introduction to Radar Systems* 3rd ed. ch.2 / Richards FRSP ch.1 通用口径；dB 路径 λ 经 registry.C_MM_GHZ 单源、内部归一 SI 同式计算，同参一致性测试钉）。

docstring 逐字引文（防漂移钉）："Pr = Pt·G²·λ²·σ / ((4π)³·R⁴·L)" + "两口径互斥（显式二选一，跨口径参数混给显式拒绝）；dB 路径内部"

### Albersheim 检测因子经验式（三量互算）

（docstring 原文转写）

```latex
A=\ln(0.62/P_{fa}),\ B=\ln\!\tfrac{P_d}{1-P_d},\quad\mathrm{SNR}_{dB}=-5\lg N+\left(6.2+\tfrac{4.54}{\sqrt{N+0.44}}\right)\lg(A+0.12AB+1.7B)
```

出处：模块 docstring（原式 W. J. Albersheim IEEE Trans. AES 1981；转引 Skolnik 3ed ch.2；Pfa+Pd→SNR 前向、Pfa+SNR→Pd/Pd+SNR→Pfa 宗量线性闭式反解）。

docstring 逐字引文（防漂移钉）："A = ln(0.62/Pfa)、B = ln(Pd/(1−Pd))" + "SNR_dB = −5·lg(N) + (6.2 + 4.54/√(N+0.44))·lg(A + 0.12·A·B + 1.7·B)"

### CA-CFAR 门限因子（指数噪声单元）

（docstring 原文转写）

```latex
P_{fa}=(1+\beta)^{-N}\Rightarrow\ \alpha=N\big(P_{fa}^{-1/N}-1\big)
```

出处：模块 docstring（Richards FRSP ch.6 CA-CFAR 节标准结果；门限 T=β·Σx_i=α·(Σx_i/N)；保护单元只改窗几何不进 α；可选 SW1 检测概率 Pd=(1+β/(1+S))^(−N) 闭式）。

docstring 逐字引文（防漂移钉）："Pfa = (1+β)^(−N)   →   β = Pfa^(−1/N) − 1   （对参考窗求和）" + "α = N·β = N·(Pfa^(−1/N) − 1)                （对参考窗平均）"

### KD-1 出处注册（`src/rfauto/core/calc_families/radar_eq.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/radar_eq:<module>:01 | <module> | source | — | "A graphical approach to linear detector SNR", IEEE Trans. AES, 1981 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `radar_eq`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- #122 如实口径：Albersheim 只覆盖 Swerling 0 非起伏目标（线性检波、N 脉冲非相干积累），SW1-4 起伏目标检测因子不冒充；分母 √(N+0.44) 取原式形态（二手 √(N+1) 简化与本键差 0.5~0.8 dB 不采用）。
  - docstring 逐字引文："Swerling 1-4 起伏目标检测因子不在 Albersheim 覆盖内，"
- 拟合窗 Pd∈[0.1,0.9]、Pfa∈[1e-7,1e-3]（文献 ±0.2 dB 精度声明窗）——窗外照算但 extrapolated=True 如实标注；硬域 0<Pfa/Pd<1 越界显式拒绝。
  - docstring 逐字引文："窗外计算照常、extrapolated=True 如实标注（硬域仍为 0<Pfa<1、"
- 全键域盒显式守卫（Pt/G/λ/f/σ/R/L、n_pulses 正整数、0<Pfa/Pd<1）；SI/dB 跨口径参数混给显式拒绝——越界一律 ValueError。
  - docstring 逐字引文："守卫：Pt（pt_w>0 / pt_dbm 有限）、G>0（线性）/有限（dB）、λ>0、"
- 数值锚面（#118 独立路线）：Albersheim 对 Marcum-Q 精确反解 |Δ|≤0.07 dB、雷达方程 R 加倍 Pr 精确 ÷16 恒等、SI/dB 同参一致 <1e-9、CFAR 闭式回代逐位+蒙特卡洛独立裁判——锚树判据书。
  - docstring 逐字引文："- Albersheim：Pfa=1e-6/Pd=0.9/N=1 → 13.1145 dB，与线性检波 Marcum-Q"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/radar_eq.py:radar_range_equation`
- `src/rfauto/core/calc_families/radar_eq.py:albersheim_detection_snr`
- `src/rfauto/core/calc_families/radar_eq.py:ca_cfar_threshold`

src/rfauto/core/calc_families/radar_eq.py 公开符号 **3** 个（AST 机读）：

`radar_range_equation`、`albersheim_detection_snr`、`ca_cfar_threshold`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w4a_mod_radar.py`——引文："数值锚（#118 独立来源；锚树 tests/unit/test_w4a_mod_radar.py）"

测试面（tests/unit 引用扫描，机读；合计 **219** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a8d_envelope_rest.py` | 12 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_ui_modules_behavior.py` | 50 |
| `tests/unit/test_ui_routing.py` | 25 |
| `tests/unit/test_ui_tools_page.py` | 41 |
| `tests/unit/test_w4a_mod_radar.py` | 24 |
| `tests/unit/test_w9s2_core_domains.py` | 18 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

