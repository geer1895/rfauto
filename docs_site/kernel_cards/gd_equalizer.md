<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：gd_equalizer

> 群时延均衡器族（架构批 W2-S7，R2_core_tier3 §③ D9）：一阶/二阶

| 字段 | 值 |
|---|---|
| 内核 ID | `gd_equalizer` |
| 主模块 | `src/rfauto/core/calc_families/gd_equalizer.py`（`rfauto.core.calc_families.gd_equalizer`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/gd_equalizer.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

群时延均衡器综合面：一阶/二阶全通节零极点镜像构造与级联逐频响应——由目标时延构造传输零极点的纯综合内核（信道提取面的反向消费方）。

模块自述（docstring 首行，机读）：群时延均衡器族（架构批 W2-S7，R2_core_tier3 §③ D9）：一阶/二阶

## 公式与口径

### 一阶全通节（零极点镜像构造）

（docstring 原文转写）

```latex
H(s)=\frac{s-a}{s+a},\ \tau_g(\omega)=\frac{2a}{a^2+\omega^2},\ \tau_{dc}=\frac{2}{a},\ |H|\equiv 1
```

出处：模块 docstring「一阶全通节」行（τ_dc 参数化 a=2/τ_dc；|H|≡1 全通定义恒等式）。

docstring 逐字引文（防漂移钉）："H(s)=(s−a)/(s+a)（a>0：极点 −a、零点 +a=极点关于原" + "τ_g(ω)=2a/(a²+ω²)；直流时延 τ_dc=2/a"

### 二阶全通节（双参数化）

（docstring 原文转写）

```latex
\tau_{pk}=\tau_g(\omega_0)=\frac{4Q}{\omega_0},\quad \tau_{dc}=\frac{2}{Q\omega_0}
```

出处：模块 docstring「二阶全通节」行（f0×Q 或 f0×τ_peak 双档恰给其一，τ_peak 档 Q=τ_pk·ω0/4）。

docstring 逐字引文（防漂移钉）："τ_pk=τ_g(ω0)=4Q/ω0；直流时延 τ_dc=2/(Qω0)"

### 级联可加性与相位总旋转恒等式

（docstring 原文转写）

```latex
H=\prod_i H_i,\ \tau_g=\sum_i \tau_{g,i},\ |S_{21}|\equiv 1;\quad \int_0^{\infty}\tau_g\,d\omega=\varphi(0)-\varphi(\infty)=\mathrm{order}\,\pi
```

出处：模块 docstring「级联」「群时延曲线积分语义」行（任务书锚；测试侧数值积分钉+零极点镜像逐位 0 残差）。

docstring 逐字引文（防漂移钉）："∫₀^∞ τ_g dω = φ(0)−φ(∞) = order·π（一阶 π/二阶 2π——相位总旋转量恒" + "级联时延可加性"

### KD-1 出处注册（`src/rfauto/core/calc_families/gd_equalizer.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/gd_equalizer:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `gd_equalizer`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- Cauer 桥 T 集总实现元件值依赖终端阻抗与实现拓扑——无终端阻抗口径不虚构（UNVERIFIED 如实不做）。
  - docstring 逐字引文："本族只到**传输零极点/频响层**"
- 族界：si_channel/kqe=信道提取面、objectives/mask_filter=幅度规格面——方向相反不并入；既有 all_pass 命中均为布尔语义误中。
  - docstring 逐字引文："本族=**均衡器综合面**（由目标时延构造全通零极点）"
- 级联 sections 非空、节数上限 32 防滥用守卫；数值 0.0 合法（判缺失 is not None，#364④）。
  - docstring 逐字引文："上限 32（防滥用）"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/gd_equalizer.py:gd_allpass_section_synthesize`
- `src/rfauto/core/calc_families/gd_equalizer.py:gd_equalizer_cascade_response`

src/rfauto/core/calc_families/gd_equalizer.py 公开符号 **2** 个（AST 机读）：

`gd_allpass_section_synthesize`、`gd_equalizer_cascade_response`

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
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

