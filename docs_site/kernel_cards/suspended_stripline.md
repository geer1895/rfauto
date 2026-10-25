<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：suspended_stripline

> 射频传输线族闭式（微带/CPW/CPWG/带状线/CPS/悬置带线 + 共用底座与锚消费）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。

| 字段 | 值 |
|---|---|
| 内核 ID | `suspended_stripline` |
| 主模块 | `src/rfauto/core/calc_families/rf_line.py`（`rfauto.core.calc_families.rf_line`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 2 条（kernel_file=src/rfauto/core/calc_families/rf_line.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

悬置带线（基板居中对称填充）闭式：空气线共形电容比基准加 softmin 串联饱和修正族——平行份额式对中段 εeff 的系统性高估由拉普拉斯 FD 定标校正，两端点极限精确、全域单调性网格验证。

模块自述（docstring 首行，机读）：射频传输线族闭式（微带/CPW/CPWG/带状线/CPS/悬置带线 + 共用底座与锚消费）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。

## 公式与口径

### εeff 结构式（softmin 串联饱和修正族）

（口径示意（非 docstring 原式，读代码为准））

```latex
\varepsilon_{\mathrm{eff}}=1+\big(\Delta^{-p}+D^{-p}\big)^{-1/p},\quad \Delta=(\varepsilon_r-1)\,\tilde q,\quad Z_0=\frac{Z_{0,\mathrm{air}}(w,b)}{\sqrt{\varepsilon_{\mathrm{eff}}}}
```

出处：模块 docstring _suspended_stripline_ri（结构式与修正常数注记见同文件 SSL 常数块——介质份额实际沿场路径串联成分，εr 升高时有效份额饱和下降，softmin 分母表达该饱和）。

docstring 逐字引文（防漂移钉）："悬置带线（suspended substrate stripline，基板对称居中）闭式：(εeff, Z0)。" + "单调性：h↑ → εeff↑（严格，FD 域内 2001 点网格零违例），εeff∈[1, εr]。"

### 两支精确极限锚（定标不改变）

（docstring 原文转写）

```latex
h\to 0:\ \bigl(1,\ Z_{0,\mathrm{air}}\bigr),\qquad h\to b:\ \bigl(\varepsilon_r,\ Z_{0,\mathrm{full}}\bigr)
```

出处：模块 docstring（两支精确极限锚=零厚度对称带状线共形闭式 _stripline_z0——空气线与全填充两支，两端点极限精确）。

docstring 逐字引文（防漂移钉）："h→0 → 空气带状线 (1, _stripline_z0(w,b,1))；" + "h→b → 全填充 (εr, _stripline_z0(w,b,εr))。"

### FD 重定标（quasistatic_fd 裁判）

（口径示意（非 docstring 原式，读代码为准））

```latex
\tilde q=q\cdot G(u,s),\quad D=D_0(1+u)^{d_1}\bigl(4s(1-s)\bigr)^{d_2},\quad p=p_0+p_1 s
```

出处：模块 docstring「FD 重定标」注记（裸平行份额式中段高估，旧口径误表已撤；修正常数定标源、独立验证族精度与适用域见 SSL 常数块注记；Z0 空气侧 Cohn 共形对拍未动）。

docstring 逐字引文（防漂移钉）："裸 q 式把介质份额按平行份额计，中段系统性高估（标称几何 +26%；"

### KD-1 出处注册（`src/rfauto/core/calc_families/rf_line.py`，knowledge/formula_provenance.yaml 过滤）

命中 **2** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/rf_line:_cps_ri:01 | _cps_ri | source | — | (1991) p.83 eqs 3.4.6.x —— Z0 = 120π·K(k1)/K'(k1)/√εeff，k1=a/b |
| calc_families/rf_line:_suspended_stripline_ri:01 | _suspended_stripline_ri | source | — | 单调性：h↑ → εeff↑（严格，FD 域内 2001 点网格零违例），εeff∈[1, εr] |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `suspended_stripline`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 定标适用域外为外推（如实预声明）；两端点极限仍精确、全域单调性经稠密网格验证零违例。
  - docstring 逐字引文："u∈[0.1,1]、s∈[0.0625,0.9]、εr∈[1.5,12.9]；域外为外推（两端点极限仍精确、"
- 几何守卫：基板厚不得越出接地板腔（非负且不超腔高）——越界显式 ValueError。
  - docstring 逐字引文："（基板不得越出接地板腔）"
- 定义域与基板厚域两道显式守卫；极薄基板数值极限（份额趋零）精确退化空气线，不做静默外推。
  - docstring 逐字引文："悬置带线闭式定义域：w>0、b>0、εr≥1"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/rf_line.py:suspended_stripline_analysis`
- `src/rfauto/core/calc_families/rf_line.py:suspended_stripline_synthesis`

src/rfauto/core/calc_families/rf_line.py 公开符号 **15** 个（AST 机读）：

`microstrip_analysis`、`microstrip_synthesis`、`microstrip_lambda_g`、`cpw_analysis`、`cpw_synthesis`、`cpwg_analysis`、`cpwg_synthesis`、`stripline_analysis`、`stripline_synthesis`、`cps_effective_thickness_factor`、`cps_corner2d_gamma_factor`、`cps_analysis`、`cps_synthesis`、`suspended_stripline_analysis`、`suspended_stripline_synthesis`

## 锚与测试入口

analytic-anchor（knowledge/anchors.yaml 机读命中）：

| anchor_id | quantity |
|---|---|
| `cps.gamma_er.fdref-v1` | cps_gamma_er |
| `siw.w_eff.lit-v1` | siw_w_eff_mm |

判据书/规格指针（docstring 逐字引文钉）：

- `scripts/fd_laplace_tline_referee.py`——引文："复现：scripts/fd_laplace_tline_referee.py --refit-ssl-q）"
- `docs/rf_template_references.md`——引文："出处（docs/rf_template_references.md §11）："

测试面（tests/unit 引用扫描，机读；合计 **146** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a3c_coupled_interdigital.py` | 20 |
| `tests/unit/test_calc_cross_validation.py` | 5 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_suspended_stripline_template.py` | 19 |
| `tests/unit/test_ta_wave_c_templates.py` | 23 |
| `tests/unit/test_w4_w4e_anchors.py` | 10 |
| `tests/unit/test_w6_f_anchors_cpw.py` | 7 |
| `tests/unit/test_x5_analytic_anchors.py` | 13 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

