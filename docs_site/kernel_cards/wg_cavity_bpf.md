<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：wg_cavity_bpf

> 波导膜片耦合腔带通滤波器综合链（架构批 W10-S4 席，R3_domain_expansion

| 字段 | 值 |
|---|---|
| 内核 ID | `wg_cavity_bpf` |
| 主模块 | `src/rfauto/core/calc_families/wg_cavity_bpf.py`（`rfauto.core.calc_families.wg_cavity_bpf`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/wg_cavity_bpf.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

波导膜片耦合腔带通滤波器综合链两键：g_k→J 倒置器→感性膜片电纳/开口/腔长全链综合与膜片电纳 λg 标度+腔电角逐频 ABCD 级联频响——滤波器实现族的波导腔体侧（Cohn 1957 原文链全文逐字核验）。

模块自述（docstring 首行，机读）：波导膜片耦合腔带通滤波器综合链（架构批 W10-S4 席，R3_domain_expansion

## 公式与口径

### 设计变量=导内波长带限（Cohn 原文口径）

（docstring 原文转写）

```latex
\lambda_{g0}=\frac{\lambda_{g1}+\lambda_{g2}}{2},\quad w=\frac{\lambda_{g1}-\lambda_{g2}}{\lambda_{g0}}
```

出处：S.B. Cohn, Direct-Coupled-Resonator Filters, Proc. IRE 45(2) 1957 pp.187-196（Fig.5 设计公式族全文逐字核验；「the desired guide-wavelength passband limits」原文口径）。

docstring 逐字引文（防漂移钉）："λg0 = (λg1 + λg2)/2                    （Cohn eq.(19) 算术均值）" + "w = (λg1 − λg2)/λg0                    （导内波长域相对带宽）"

### J 倒置器（πw/2 公式族）

（docstring 原文转写）

```latex
\frac{J_{01}}{Z_0}=\sqrt{\frac{\pi w}{2g_0g_1}},\quad \frac{J_{j,j+1}}{Z_0}=\frac{\pi w/2}{\sqrt{g_jg_{j+1}}}
```

出处：与 coupled_line_bpf/Pozar §8.6.2 同形（已双源在案）；g_k 走 core/matching.chebyshev_g_values 单源。

docstring 逐字引文（防漂移钉）："J01/Z0 = √(πw/(2·g0·g1))" + "Jj,j+1/Z0 = (πw/2)/√(gj·gj+1)（内部 j=1..N−1）"

### 膜片归一化电抗与开口反解

（docstring 原文转写）

```latex
x_j=\frac{J_j/Z_0}{1-(J_j/Z_0)^2},\quad d=\frac{2a}{\pi}\arctan\sqrt{\frac{\lambda_{g0}x}{a}}
```

出处：Cohn Fig.13(e) 设计反演式；膜片开口=消费 wg_iris_susceptance 同一薄膜片闭式反解（roundtrip 逐位）。

docstring 逐字引文（防漂移钉）："x_j = (J_j/Z0)/(1−(J_j/Z0)²)      （感性膜片，x>0）" + "d=(2a/π)·arctan(√(λg0·x/a))，正反解"

### 腔长（Cohn Fig.5 φi 式）

（docstring 原文转写）

```latex
\theta_i=\pi-\tfrac{1}{2}\left[\arctan(2x_{i-1,i})+\arctan(2x_{i,i+1})\right],\quad l_i=\frac{\theta_i\lambda_{g0}}{2\pi}
```

出处：负线长簿记 θi+½(φ_{i−1}+φ_i)=180°（Cohn 原文口径）。

docstring 逐字引文（防漂移钉）："θ_i = π − ½[arctan(2x_{i−1,i}) + arctan(2x_{i,i+1})]" + "l_i = θ_i·λg0/(2π)"

### 频响面：膜片电抗 λg 反比标度+腔电角逐频级联

（docstring 原文转写）

```latex
x\propto\frac{\lambda_{g0}}{\lambda_g(f)},\quad \psi_i(f)=\frac{2\pi l_i}{\lambda_g(f)}
```

出处：Cohn 原文逐字（λg 标度）——与薄膜片闭式自身 λg 依赖同标度（两路径逐位同值=#118 同文件双路径）；ABCD→S 级联在 λg 轴对称（Cohn 原文性质）。

docstring 逐字引文（防漂移钉）："The iris reactance is assumed to vary in inverse proportion to guide" + "b ∝ λg ⟹ x ∝ λg0/λg(f)，"

### KD-1 出处注册（`src/rfauto/core/calc_families/wg_cavity_bpf.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/wg_cavity_bpf:<module>:01 | <module> | source | — | 出处：Cohn 1957 Proc. IRE 45(2) pp.187-196（Fig.5/Fig.13(e)/λg 标度全链 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `wg_cavity_bpf`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 精度域 w≤0.2 显式守卫（Cohn 原文 good results with bandwidths of at least 20 percent）；域内高档纹波畸变渐显（原文 Fig.8/9 同行为），消费者须以响应键全带复核。
  - docstring 逐字引文："least 20 percent in guide wavelength"——域内高档通带纹波畸变渐显（原文"
- 厚膜片/销钉/谐振窗结构不在此口径；无耗假设（Q→∞），有限 Q 插损面不入键面。
  - docstring 逐字引文："薄膜片近似（零厚度感性窗，wg_iris_susceptance 同口径）；厚膜片/销钉/"
- f≤TE10 截止显式拒绝（与 wg_iris/waveguide_closed_form 同源守卫）。
  - docstring 逐字引文："f≤TE10 截止显式拒绝（_frequency 守卫同源）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/wg_cavity_bpf.py:wg_cavity_bpf_synthesize`
- `src/rfauto/core/calc_families/wg_cavity_bpf.py:wg_cavity_bpf_response`

src/rfauto/core/calc_families/wg_cavity_bpf.py 公开符号 **2** 个（AST 机读）：

`wg_cavity_bpf_synthesize`、`wg_cavity_bpf_response`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w10s4_core_domains.py`——引文："波导膜片耦合腔带通滤波器综合链（架构批 W10-S4 席，R3_domain_expansion"

测试面（tests/unit 引用扫描，机读；合计 **73** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w10s4_core_domains.py` | 24 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)

