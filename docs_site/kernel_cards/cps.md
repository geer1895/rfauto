<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：cps

> 射频传输线族闭式（微带/CPW/CPWG/带状线/CPS/悬置带线 + 共用底座与锚消费）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。

| 字段 | 值 |
|---|---|
| 内核 ID | `cps` |
| 主模块 | `src/rfauto/core/calc_families/rf_line.py`（`rfauto.core.calc_families.rf_line`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 2 条（kernel_file=src/rfauto/core/calc_families/rf_line.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

共面带（双带无地）准静态闭式：空气线椭圆积分精确解+有限厚基板 tanh 部分电容映射，叠加拉普拉斯 FD 定标的有效厚度因子与角落二维修正（显式 opt-in）——无地薄基板场泄漏导致的裸映射系统性低估已定标校正，定标域边界如实预声明。

模块自述（docstring 首行，机读）：射频传输线族闭式（微带/CPW/CPWG/带状线/CPS/悬置带线 + 共用底座与锚消费）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。

## 公式与口径

### 空气线 CPS 精确闭式（椭圆积分比）

（docstring 原文转写）

```latex
Z_{0}=\frac{120\pi}{\sqrt{\varepsilon_{\mathrm{eff}}}}\frac{K(k_1)}{K'(k_1)},\quad k_1=\frac{a}{b},\quad a=\tfrac{gap}{2},\ b=\tfrac{gap}{2}+w
```

出处：模块 docstring _cps_ri「出处」节（Wadell TLDH p.83 eqs 3.4.6.x；MathWorks RF PCB Toolbox 官方例 MoM 对拍；与 CPW 互补对偶 Z_CPS·Z_CPW=η0²/4 自洽）。

docstring 逐字引文（防漂移钉）："Z0 = 120π·K(k1)/K'(k1)/√εeff，k1=a/b"

### 有限厚基板部分电容合成（tanh 映射）

（docstring 原文转写）

```latex
C=\frac{\varepsilon_0}{r_1}+(\varepsilon_r-1)\frac{\varepsilon_0}{2\,r_3},\quad \varepsilon_{\mathrm{eff}}=\frac{C}{C_{\mathrm{air}}},\quad k_3=\frac{\tanh(\pi a/2h_{\mathrm{eff}})}{\tanh(\pi b/2h_{\mathrm{eff}})}
```

出处：模块 docstring _cps_ri「出处」节（Gupta/Ghione 部分电容技术，与 _cpwg_ri 同框架——介质超额项走接地板 tanh 映射）。

docstring 逐字引文（防漂移钉）："C = ε0/r1 + (εr−1)·ε0/(2·r3)，εeff = C/C_air = 1+(εr−1)·r1/(2·r3)。"

### FD 定标有效厚度（无地薄基板场泄漏校正）

（docstring 原文转写）

```latex
h_{\mathrm{eff}}=\gamma(\varepsilon_r)\,h,\quad \gamma(\varepsilon_r)=1+C\,\varepsilon_r^{-P}
```

出处：模块 docstring「FD 定标」节（quasistatic_fd.py 裁判逐 εr 最小二乘+幂律拟合；值源优先 cps.gamma_er.fdref-v1 公式锚、回退闭式与锚逐位相等）。

docstring 逐字引文（防漂移钉）："γ(εr) = 1 + 0.9014·εr^(−0.6361)（εr→∞ 场受限 γ→1，εr=3.66 γ=1.395）"

### KD-1 出处注册（`src/rfauto/core/calc_families/rf_line.py`，knowledge/formula_provenance.yaml 过滤）

命中 **2** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/rf_line:_cps_ri:01 | _cps_ri | source | — | (1991) p.83 eqs 3.4.6.x —— Z0 = 120π·K(k1)/K'(k1)/√εeff，k1=a/b |
| calc_families/rf_line:_suspended_stripline_ri:01 | _suspended_stripline_ri | source | — | 单调性：h↑ → εeff↑（严格，FD 域内 2001 点网格零违例），εeff∈[1, εr] |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `cps`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 定标域外单参数 γ 修正数据不支持（逐点最优 γ 是二维曲面，不硬凑）——域外闭式低估幅度如实注记在档。
  - docstring 逐字引文："定标域 a/h≲1 且 b/h≲3 之外（宽带缝角落）γ(εr) 单参数修正**数据不支持**"
- 角落二维修正为 corner2d=True 显式 opt-in——缺省路径与定标域内钉住的证据表逐位一致。
  - docstring 逐字引文："角落区按 160 点在档 FD 拟合 log E2 全二次面"
- 两端点极限与单调性有单测钉（定标不改变）：h→0 全空气、h→∞ Wen 半空间口径；gap 两端与 Z0 随宽单调同节。
  - docstring 逐字引文："极限自洽（有单测，定标不改变）：h→0 εeff→1；h→∞ εeff→(1+εr)/2（Wen"
- 定义域守卫显式 ValueError；k1 数值退化（gap/w 比例超出准静态共形映射适用域）显式拒绝。
  - docstring 逐字引文："CPS 闭式定义域：w>0、gap>0、h>0、εr≥1"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/rf_line.py:cps_analysis`
- `src/rfauto/core/calc_families/rf_line.py:cps_synthesis`

src/rfauto/core/calc_families/rf_line.py 公开符号 **15** 个（AST 机读）：

`microstrip_analysis`、`microstrip_synthesis`、`microstrip_lambda_g`、`cpw_analysis`、`cpw_synthesis`、`cpwg_analysis`、`cpwg_synthesis`、`stripline_analysis`、`stripline_synthesis`、`cps_effective_thickness_factor`、`cps_corner2d_gamma_factor`、`cps_analysis`、`cps_synthesis`、`suspended_stripline_analysis`、`suspended_stripline_synthesis`

## 锚与测试入口

analytic-anchor（knowledge/anchors.yaml 机读命中）：

| anchor_id | quantity |
|---|---|
| `cps.gamma_er.fdref-v1` | cps_gamma_er |
| `siw.w_eff.lit-v1` | siw_w_eff_mm |

判据书/规格指针（docstring 逐字引文钉）：

- `docs/rf_template_references.md`——引文："出处（docs/rf_template_references.md §11.1）："
- `scripts/fd_laplace_tline_referee.py`——引文："复现：scripts/fd_laplace_tline_referee.py --refit-cps-gamma）"

测试面（tests/unit 引用扫描，机读；合计 **159** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a3c_coupled_interdigital.py` | 20 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_cps_template.py` | 20 |
| `tests/unit/test_ep2_trace_matrix.py` | 17 |
| `tests/unit/test_ta_wave_c_templates.py` | 23 |
| `tests/unit/test_w4_w4e_anchors.py` | 10 |
| `tests/unit/test_w6_f_anchors_cpw.py` | 7 |
| `tests/unit/test_x5_analytic_anchors.py` | 13 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

