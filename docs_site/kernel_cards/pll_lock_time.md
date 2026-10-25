<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：pll_lock_time

> PLL 锁定/捕获时间族（aurora_f W4-S14 席域 3，R2_core_tier3 边际池立项

| 字段 | 值 |
|---|---|
| 内核 ID | `pll_lock_time` |
| 主模块 | `src/rfauto/core/calc_families/pll_lock_time.py`（`rfauto.core.calc_families.pll_lock_time`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/pll_lock_time.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

PLL 锁定/捕获时间：二阶 II 型环频率阶跃的线性锁定精确包络闭式与非线性 pull-in 近似档、lock-in/pull-out 范围档位判别——环路滤波器综合（ω_n/ζ 供给端）与相噪预算面之间的捕获动力学键。

模块自述（docstring 首行，机读）：PLL 锁定/捕获时间族（aurora_f W4-S14 席域 3，R2_core_tier3 边际池立项

## 公式与口径

### 误差传函与频率阶跃精确暂态（Gardner Ch.3）

（docstring 原文转写）

```latex
E(s)=\frac{s^2}{s^2+2\zeta\omega_n s+\omega_n^2},\quad \phi_e(t)=\frac{\Delta\omega}{\omega_d}e^{-\zeta\omega_n t}\sin(\omega_d t),\ \omega_d=\omega_n\sqrt{1-\zeta^2}
```

出处：模块 docstring「线性模型」节（Gardner Phaselock Techniques Ch.3 标准形式；ζ=1 临界阻尼/ζ>1 双指数精确式同节；II 型环频率阶跃稳态误差恒 0——终值定理，测试锚）。

docstring 逐字引文（防漂移钉）："H(s)=(2ζω_n·s+ω_n²)/(s²+2ζω_n·s+ω_n²)，误差传函" + "ζ<1：φ_e(t)=(Δω/ω_d)·e^{−ζω_n t}·sin(ω_d t)，ω_d=ω_n√(1−ζ²)"

### 线性锁定时间（包络精确闭式）

（docstring 原文转写）

```latex
t_{\mathrm{lock}}=\frac{\ln\big(\Delta\omega/(\varphi_{\mathrm{tol}}\,\omega_d)\big)}{\zeta\omega_n}\ (\zeta<1),\quad \zeta\ge 1\ \text{精确暂态二分求根}
```

出处：模块 docstring「线性锁定时间」节（包络口径精确闭式；ζ≥1 对精确暂态二分求根=确定性，包络不适用如实声明）。

docstring 逐字引文（防漂移钉）："t_lock=ln(Δω/(φ_tol·ω_d))/(ζω_n)（ζ<1）；ζ≥1 对精确暂态二分求根"

### 捕获档（lock-in/pull-in/pull-out，近似与仿真档如实标）

（docstring 原文转写）

```latex
\Delta\omega_L\approx 2\zeta\omega_n,\ T_L\approx\frac{2\pi}{\omega_n},\quadT_P=\frac{\pi^2\Delta\omega_0^2}{16\,\zeta\omega_n^3},\quad \Delta\omega_{PO}\approx 1.8\omega_n(\zeta+1)
```

出处：模块 docstring「pull-in 时间」节（Best 4th ed. App.A/GT L060 同式；文献例 f_n=3Hz、ζ=0.7、Δf=30Hz → T_P=4.675s 本键逐位复现窗 0.5%；pull-out=仿真经验档如实标）。

docstring 逐字引文（防漂移钉）："高环路增益三滤波器统一 Δω_L≈2ζω_n；lock-in 时间 T_L≈1/f_n=2π/ω_n" + "T_P=(π²/16)·Δω₀²/(ζ·ω_n³)——近似档；文献锚（#122）：GT L060 例"

### KD-1 出处注册（`src/rfauto/core/calc_families/pll_lock_time.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/pll_lock_time:<module>:01 | <module> | source | — | 出处（Gardner 2005 Ch.3；Best 1999 App.A；3rd ed., Wiley 2005, Ch.3（pll_loop_filter 同源引注）；pull-in 时间/；范围式=R.E. Best, Phase-Locked Loops, 4th ed., McGraw-Hill 1999 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `pll_lock_time`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 边界防撞：pll_loop_filter=滤波器综合（ω_n/ζ 上游供给端）、pll_budget=相噪/抖动预算面、clock_noise=相噪谱积分——均不做捕获动力学，边界互指见各模块 docstring。
  - docstring 逐字引文："- pll_loop_filter=三阶环路滤波器**综合**（T1/T2/T3→元件值，ω_n/ζ 上游"
- 档位判别三档：线性档（t_lock 有效）/非线性捕获档（t_lock 不适用如实标记报 T_P 近似）/超出 pull-out 档位提示（可能失锁，II 型环仍可慢速拉入的定性注记）。
  - docstring 逐字引文："档位判别**：|Δf|≤Δf_L=ζω_n/π → 线性档（t_lock 有效，无周期滑移）；"
- 无环路增益输入时 pull-in 范围不判（II 型有源 PI 环理论上 Δω_P→∞，如实注记不虚构有限范围）。
  - docstring 逐字引文："无环路增益输入时 pull-in 范围不判（II 型有源 PI 环"
- 越界一律显式 ValueError（tol_deg 半相位窗开区间）。
  - docstring 逐字引文："守卫：fn_hz>0；zeta>0；df_hz≥0；tol_deg∈(0,180)；loop_gain 可选>0。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/pll_lock_time.py:pll_lock_time`

src/rfauto/core/calc_families/pll_lock_time.py 公开符号 **1** 个（AST 机读）：

`pll_lock_time`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w4s14_core_edge.py`——引文："一键：pll_lock_time（二阶 II 型 PLL 频率阶跃的线性锁定时间精确包络闭式+"

测试面（tests/unit 引用扫描，机读；合计 **66** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w4s14_core_edge.py` | 17 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

