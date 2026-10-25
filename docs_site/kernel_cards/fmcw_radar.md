<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：fmcw_radar

> FMCW 三角波调制波形-观测量映射族（aurora_g W7-S3 席，

| 字段 | 值 |
|---|---|
| 内核 ID | `fmcw_radar` |
| 主模块 | `src/rfauto/core/calc_families/fmcw_radar.py`（`rfauto.core.calc_families.fmcw_radar`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/fmcw_radar.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

三角调制 FMCW 波形→观测量映射四键：拍频正反解（距离/多普勒解耦恒等式）、带宽→距离分辨率/IF 带宽量程面、chirp 参数设计（正问题链逆解面，W11-S4 扩展）与 IF 信号链规划（混频→LPF→ADC→距离 FFT，W11-S4 扩展）——ISAC/车载最主流波形的指标面延长线（不做 FFT 处理链/动目标检测链）。

模块自述（docstring 首行，机读）：FMCW 三角波调制波形-观测量映射族（aurora_g W7-S3 席，

## 公式与口径

### 三角调制拍频分解（距离拍频+多普勒）

（docstring 原文转写）

```latex
f_{b,R}=S\tau=\frac{2SR}{c},\quad f_D=\frac{2vf_c}{c},\quad f_{up}=f_{b,R}-f_D,\ f_{down}=f_{b,R}+f_D
```

出处：Skolnik IRS ch.14/Richards FRSP ch.3 车载雷达教科书通用口径（S=B/T 扫频斜率、τ=2R/c 往返时延、v>0 逼近约定）。

docstring 逐字引文（防漂移钉）："f_b,R = S·τ = 2·S·R/c" + "上扫：f_up = f_b,R − f_D"

### 解耦恒等式与正反解

（docstring 原文转写）

```latex
\frac{f_{up}+f_{down}}{2}=\frac{2SR}{c}\Rightarrow R=\frac{c(f_{up}+f_{down})}{4S};\quad \frac{f_{down}-f_{up}}{2}=f_D\Rightarrow v=\frac{c\,f_D}{2f_c}=\frac{\lambda f_D}{2}
```

出处：同章通用口径；mode=forward（距离/速度→拍频）/inverse（拍频→距离/速度）roundtrip 逐位闭环（#118 锚树钉，数值锤 150m/10m/s@77GHz 回收逐位）。

docstring 逐字引文（防漂移钉）："(f_up+f_down)/2 = 2·S·R/c → R = c·(f_up+f_down)/(4·S)" + "(f_down−f_up)/2 = f_D   → v = c·f_D/(2·f_c) = λ·f_D/2"

### 带宽-距离分辨率恒等式

（docstring 原文转写）

```latex
\Delta R=\frac{c}{2B}
```

出处：Skolnik/Richards 教科书恒等式（1GHz→14.99cm/4GHz→3.75cm 车载口径；数值锤实测逐位）。

docstring 逐字引文（防漂移钉）："ΔR = c/(2B)"

### IF 带宽量程面（饱和恒等）

（docstring 原文转写）

```latex
R_{max}=\frac{c\,\mathrm{BW_{IF}}}{2S},\quad f_b(R_{max})=\mathrm{BW_{IF}},\quad T_{chirp}=B/S
```

出处：同章通用口径；饱和恒等=量程处拍频恰满 IF 带（数值锤 50MHz IF/5e13 Hz/s → R_max=149.90m、f_b(R_max)=50MHz 逐位）；T_chirp=B/S 半程 chirp 时长随带。

docstring 逐字引文（防漂移钉）："R_max = c·BW_IF/(2·S)" + "f_b(R_max) = BW_IF"

### chirp 参数设计（正问题链逆解面，W11-S4）

（docstring 原文转写）

```latex
B=\frac{c}{2\Delta R},\quad S=\frac{c\,\mathrm{BW_{IF}}}{2R_{max}}\ \text{或}\ S=\frac{c\,f_s}{4R_{max}},\quad T_{chirp}=B/S,\quad f_{s,\min}=2f_b(R_{max})
```

出处：同章通用口径的逆解面；三斜率定档互斥（部分给/多给/全缺显式拒绝），IF 带限与实采样 Nyquist 档在 BW_IF=fs/2 时斜率逐位一致（跨档一致性锚）。

docstring 逐字引文（防漂移钉）："B = c/(2·ΔR)" + "IF 带限档：S = c·BW_IF/(2·R_max)"

### IF 信号链规划（混频→LPF→ADC→距离 FFT，W11-S4）

（docstring 原文转写）

```latex
R_{adc}=\frac{c\,f_s}{4S},\quad R_{lpf}=\frac{c\,f_{lpf}}{2S},\quad \Delta R_{obs}=\frac{c}{2B_{eff}}=\frac{c\,f_s}{2SN},\quad G_{proc}=10\lg N\ \mathrm{dB}
```

出处：同章通用口径+Richards FRSP ch.1 相参积累增益 N 口径（bins=⌊N/2⌋、处理增益 10·lg(N) dB；观测分辨率=矩形窗距离 bin 宽恒等式逐位）。

docstring 逐字引文（防漂移钉）："R_adc = c·fs/(4·S)" + "ΔR_obs = c/(2·B_eff) = c·fs/(2·S·N)"

### KD-1 出处注册（`src/rfauto/core/calc_families/fmcw_radar.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/fmcw_radar:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `fmcw_radar`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 拍频非负守卫：一阶解耦模型域=拍频内多普勒-距离耦合 O(τ·f_D) 忽略（v≪c 恒成立）；|f_D|>f_b,R 时模型折叠，显式拒绝不出伪数。
  - docstring 逐字引文："（|f_D|>f_b,R 时解耦模型折叠，显式拒绝）。"
- 静止目标 f_up=f_down 逐位对称；远离目标（v<0）f_up>f_down 方向恒等；inverse 出速度需 carrier_hz 同给。
  - docstring 逐字引文："静止目标（v=0）f_up=f_down 逐位对称恒等；正反解双向（mode=forward/"
- 本族只做波形→观测量映射闭式；发射泄漏/相位噪声对分辨率的退化不在键口径；isac_ambiguity「只做指标不做处理链」no-go 同源尊重。
  - docstring 逐字引文："波形（快慢时间 MIMO）/FFT 处理链不在本键口径（isac no-go 同源尊重）。"
- chirp 设计三档互斥：部分给/多给/全缺显式拒绝；IF 带限与实采样 Nyquist 档在 BW_IF=fs/2 时斜率逐位一致（跨档一致性锚）。
  - docstring 逐字引文："三斜率定档互斥（if_bandwidth_hz/adc_sample_rate_hz/slope_hz_per_s"
- IF 链折叠守卫：设计量程拍频超 Nyquist 与观测窗超 chirp 时长（B_eff>B 非物理）显式拒绝；多普勒维处理链不在本键口径（no-go 同源尊重）。
  - docstring 逐字引文："折叠守卫：设计量程拍频超 Nyquist（|f_D|=0 一阶域）与观测窗超 chirp"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/fmcw_radar.py:fmcw_range_doppler`
- `src/rfauto/core/calc_families/fmcw_radar.py:fmcw_bandwidth_range_resolution`
- `src/rfauto/core/calc_families/fmcw_radar.py:fmcw_chirp_design`
- `src/rfauto/core/calc_families/fmcw_radar.py:fmcw_if_signal_chain`

src/rfauto/core/calc_families/fmcw_radar.py 公开符号 **4** 个（AST 机读）：

`fmcw_range_doppler`、`fmcw_bandwidth_range_resolution`、`fmcw_chirp_design`、`fmcw_if_signal_chain`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w7s3_core_domains.py`——引文："物理口径（#1c/#300 出处纪律；三角波几何恒等式，2026-10-19 数值锤独立"

测试面（tests/unit 引用扫描，机读；合计 **92** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calc_cross_validation.py` | 5 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w11s4_core_domains.py` | 15 |
| `tests/unit/test_w7s3_core_domains.py` | 23 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

