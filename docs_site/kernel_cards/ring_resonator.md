<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：ring_resonator

> 微带环形谐振器综合内核（aurora_f W3-S11 席域，R2_core_tier3 §⑤ F3 设计案）。

| 字段 | 值 |
|---|---|
| 内核 ID | `ring_resonator` |
| 主模块 | `src/rfauto/core/calc_families/ring_resonator.py`（`rfauto.core.calc_families.ring_resonator`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/ring_resonator.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

微带环形谐振器专属综合内核：目标基模 f1→HJ εeff→环平均半径 r_mean=c/(2π·f1·√εeff)（闭环周长=λg 恒等式——render_ring 设计链的提升式重构单一事实源，字节级对拍钉），附间隙耦合 Qe 设计式（串联隙=J-反相器）与模阶谱/Q 分解/基模频响两键。

模块自述（docstring 首行，机读）：微带环形谐振器综合内核（aurora_f W3-S11 席域，R2_core_tier3 §⑤ F3 设计案）。

## 公式与口径

### 谐振恒等式（综合正向，render_ring 链逐字节提升）

（docstring 原文转写）

```latex
r_{\mathrm{mean}}=\frac{c}{2\pi f_1\sqrt{\varepsilon_{\mathrm{eff}}(f_1)}}
```

出处：模块 docstring「谐振恒等式」节（闭环周长=λg；基线 runs/aurora_f/w3s11_ring_parity_baseline.json 字节对拍钉；反方向=core/dielectric_extract.ring_resonator_f0_to_er 同仓双源，回收带 −0.52% 如实）。

docstring 逐字引文（防漂移钉）："r_mean = c/(2π·f1·√εeff(f1))，εeff 取微带 HJ 正向（core/synthesis."

### 间隙耦合 Qe 设计式（串联隙=J-反相器）

（docstring 原文转写）

```latex
J=\omega_0 C_g,\quad x=JZ_0,\quad Q_e=\tfrac{\pi}{2}\frac{Z_0/Z_r}{x^2}
```

出处：模块 docstring「间隙耦合 Qe 设计式」节（与 coupled_line_bpf 同式同仓双源；qe_target 反解隙宽 brentq 回代闭环）。

docstring 逐字引文（防漂移钉）："② 串联隙 = J-反相器：J = ω0·C_g（MYJ §8.5/Pozar §8.6 小隙口径）。" + "Q_e = (π/2)·(Z0/Z_r)/x²，x = J·Z0（与"

### 模阶谱（逐模不动点，HJ 弱色散）

（docstring 原文转写）

```latex
f_n=\frac{n\,c}{2\pi r_{\mathrm{mean}}\sqrt{\varepsilon_{\mathrm{eff}}(f_n)}}
```

出处：模块 docstring「模阶谱」节（基模 n=1 与综合恒等式同式构造位精确；HJ 弱色散偏差 n=2/3 实测 +0.073%/+0.115% 随档如实）。

docstring 逐字引文（防漂移钉）："f_n = n·c/(2π·r_mean·√εeff(f_n))（逐模不动点"

### 频响与谐振峰（Q 分解+ABCD 双路线）

（docstring 原文转写）

```latex
\frac{1}{Q_L}=\frac{1}{Q_d}+\frac{1}{Q_c}+\frac{1}{Q_r},\quad S_{21,\mathrm{pk}}=\frac{1}{1+Q_e/(2Q_0)}
```

出处：模块 docstring「Q 分解」「频响」节（Q_d 填充因子式/Q_c Wheeler 增量电感规则经 forward_z0 数值导数；闭式与网络数值逐位闭合 #118 双路线）。

docstring 逐字引文（防漂移钉）："S21pk = 1/(1+Qe/(2Q0))（对 ABCD 网络" + "Q_L = 1/(1/Q0 + 2/Qe)。频轴按基模（n=1）档评估（理想裁判口径，"

### KD-1 出处注册（`src/rfauto/core/calc_families/ring_resonator.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/ring_resonator:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `ring_resonator`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 隙电容 C_g=ε0·εh·w²/g 为 R2 F3 设计案预授权的简化电容模型档：单调性/极限行为正确、系数非场解精度——Garg-Bahl 拟合与共形场解无仓内验证出处不入面（禁凭记忆写常数），实测注入走 c_gap_ff/qe_per_port 覆盖档。
  - docstring 逐字引文："系数 1 量纲估计档，UNVERIFIED 如实"
- 近似级别与 render_ring 段头注同源：v1 闭式未含曲率/色散修正，精度由 G2 闭环+HFSS 仲裁另批兑现。
  - docstring 逐字引文："εeff 未含曲率/色散修正（v1）。"
- 频响=基模档理想裁判（coupled_line_bpf Qe 面同族窄带理想化）：线环网络实测隙加载失谐名义点 −1.6%（dielectric_extract P1「开路耦合隙相位移出」同族声明），模点走 modes 表。
  - docstring 逐字引文："多模复合响应与隙电容加载失谐"
- Q 分解 v1 面：Q_d 填充因子式、Q_c Wheeler 光滑壁档（粗糙度修正不做）、Q_r 记零——实测注入走 qe_per_port 覆盖档。
  - docstring 逐字引文："Q_r（辐射/表面波残差）v1 不建模记零贡献"
- 族界：ratrace=环行功分器拓扑、dielectric_extract=提取反方向面（同仓双源互证不重复）、combline_resonator/coaxial_cavity/cavity_unloaded_q=腔谐振面——本族=传输型环形谐振器综合两键。
  - docstring 逐字引文："coaxial_cavity=腔谐振、cavity_unloaded_q=腔 Q 面——本族只做"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/ring_resonator.py:ring_resonator_synthesize`
- `src/rfauto/core/calc_families/ring_resonator.py:ring_resonator_response`
- `src/rfauto/core/calc_families/ring_resonator.py:ring_resonator_design_params`

src/rfauto/core/calc_families/ring_resonator.py 公开符号 **3** 个（AST 机读）：

`ring_resonator_design_params`、`ring_resonator_synthesize`、`ring_resonator_response`

消费面（service/adapters 引用扫描，机读）：

- adapters：`src/rfauto/adapters/oe_templates/render_ring.py`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w3s11_ring.py`——引文："runs/aurora_f/w3s11_ring_parity_baseline.json"

测试面（tests/unit 引用扫描，机读；合计 **61** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w3s11_ring.py` | 12 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

