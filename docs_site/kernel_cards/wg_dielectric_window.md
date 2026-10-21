<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：wg_dielectric_window

> 矩形波导介质窗族（架构批 W2-S2 席域 C6，R2_core_tier4 §③ Top11

| 字段 | 值 |
|---|---|
| 内核 ID | `wg_dielectric_window` |
| 主模块 | `src/rfauto/core/calc_families/wg_dielectric_window.py`（`rfauto.core.calc_families.wg_dielectric_window`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/wg_dielectric_window.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

矩形波导介质窗（真空密封窗介质形态）：介质片半波长全传输谐振设计与给定厚度核验双档、逐频扫描带宽面——与薄膜片谐振窗成族补全阻抗变换/电纳对消两口径。

模块自述（docstring 首行，机读）：矩形波导介质窗族（架构批 W2-S2 席域 C6，R2_core_tier4 §③ Top11

## 公式与口径

### TE10 介质片传播面（空气段/介质段）

（docstring 原文转写）

```latex
\beta_a=\frac{2\pi f}{c}\sqrt{1-(f_c/f)^2},\quad\beta_d=\frac{2\pi f}{c}\sqrt{\varepsilon_r-(f_c/f)^2},\quad\frac{Z_d}{Z_a}=\frac{\beta_a}{\beta_d}=\frac{\lambda_{g,\mathrm{slab}}}{\lambda_{g,\mathrm{air}}}
```

出处：模块 docstring「物理口径」节（TE 模阻抗 Z_TE=ωμ/β → 阻抗比=λg 比同 μ 口径，与工作频率无关；介质填充只改 β 与 Z_TE、截止形状同）。

docstring 逐字引文（防漂移钉）："β_d = (2πf/c)·√(εr − (fc/f)²)" + "λg,air = 2π/β_a，λg,slab = 2π/β_d"

### 半波长全传输谐振（双界面反射对消）

（docstring 原文转写）

```latex
\Gamma_{\mathrm{in}}=\Gamma_{01}\frac{1-e^{-2j\beta_d t}}{1-\Gamma_{01}^2 e^{-2j\beta_d t}},\quad\beta_d t=m\pi\ (t=m\lambda_{g,\mathrm{slab}}/2)\ \Rightarrow\ \Gamma_{\mathrm{in}}=0
```

出处：模块 docstring（界面反射 Γ01=(Z_d−Z_a)/(Z_d+Z_a)；半波长段 ABCD=[−1,0;0,−1] 与恒等矩阵仅差符号——构造级恒等式；设计档取最薄阶 m_order=1 工程惯例）。

docstring 逐字引文（防漂移钉）："Γ_in = Γ01·(1 − e^{−2jβ_d t})/(1 − Γ01²·e^{−2jβ_d t})" + "β_d·t = mπ（t = m·λg,slab/2，m=1,2,...）时 e^{−2jβ_d t} = 1 → Γ_in = 0"

### 传输系数与能量守恒

（docstring 原文转写）

```latex
S_{21}=\frac{(1-\Gamma_{01}^2)e^{-j\beta_d t}}{1-\Gamma_{01}^2 e^{-2j\beta_d t}},\quad|S_{11}|^2+|S_{21}|^2=1
```

出处：模块 docstring（无损口径能量守恒随 residual 字段自检；λ/4 厚度档 |Γ_in|=(Z_d²−Z_a²)/(Z_d²+Z_a²) 变换器反射闭式独立路线对拍锚）。

docstring 逐字引文（防漂移钉）："构造级恒等式）；传输系数 S21 = (1−Γ01²)·e^{−jβ_d t}/(1−Γ01²·e^{−2jβ_d t})" + "（无损，|S11|²+|S21|²=1 恒等式随 residual 字段自检）。"

### KD-1 出处注册（`src/rfauto/core/calc_families/wg_dielectric_window.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/wg_dielectric_window:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `wg_dielectric_window`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 成族边界：wg_resonant_window=电纳对消口径膜片型窗——本键=阻抗变换口径介质段半波长谐振，两形态互指成族不并；waveguide_closed_form=模谱、rwg_mmt=数值模匹配仲裁路径（本键=工程闭式档）。
  - docstring 逐字引文："- waveguide_iris.wg_resonant_window=感/容薄膜片组合谐振窗（电纳对消"
- εr=1 无窗退化档全直通如实输出不拒绝、εr<1 非物理显式拒绝；verify 档残余反射如实不凑零；无损口径复 εr/材料损耗项不在键面。
  - docstring 逐字引文："退化自检：εr=1 → Z_d=Z_a → Γ01=0 → 任意 t 全直通（无窗退化档，如实"
- multipactor 倍增放电面不在本键（其 docstring「介质窗 multipactor 未建模」边界注记=本键的下游不覆盖声明）——本键只做窗传输设计；平板介质谐振器/天线罩语义不并入。
  - docstring 逐字引文："- multipactor=介质窗倍增放电面（其 docstring 边界注记即本键的下游不"
- 空气段截止以下无传播显式拒绝（窗谐振语义失效）；m_order≥1 整数、t_mm>0；数值锚 WR-90/10GHz/εr=2.2 逐位+t=λg/4 对拍 λ/4 变换器闭式（#118 锚树判据书）——越界一律显式 ValueError。
  - docstring 逐字引文："守卫：a_mm>0；f_ghz>TE10 截止（空气段传播守卫）；eps_r≥1（=1 无窗退"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/wg_dielectric_window.py:wg_dielectric_window`

src/rfauto/core/calc_families/wg_dielectric_window.py 公开符号 **1** 个（AST 机读）：

`wg_dielectric_window`

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
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

