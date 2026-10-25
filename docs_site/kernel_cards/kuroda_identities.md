<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：kuroda_identities

> Kuroda 恒等式族（aurora_f W4-S14 席域 2，R2_core_tier3 边际池立项）。

| 字段 | 值 |
|---|---|
| 内核 ID | `kuroda_identities` |
| 主模块 | `src/rfauto/core/calc_families/kuroda_identities.py`（`rfauto.core.calc_families.kuroda_identities`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/kuroda_identities.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

Kuroda 恒等式：单位元与短截线四恒等式的两侧 ABCD 逐位精确等效变换（Pozar Table 8.7）与三阶低通原型 Richards 变换+恒等式两端化并联全链实现（Example 8.5 文献数值锚）。

模块自述（docstring 首行，机读）：Kuroda 恒等式族（aurora_f W4-S14 席域 2，R2_core_tier3 边际池立项）。

## 公式与口径

### 网络基元 ABCD（commensurate 公共电长）

（docstring 原文转写）

```latex
[\mathrm{UE}]=\begin{bmatrix}\cos\theta&jZ\sin\theta\\j\sin\theta/Z&\cos\theta\end{bmatrix},\quadZ_{\mathrm{in}}^{short}=jZ\tan\theta,\ Z_{\mathrm{in}}^{open}=-jZ\cot\theta
```

出处：模块 docstring「物理口径」节（Pozar Table 4.1 基元同式；§8.5 式 (8.79)-(8.80) 以 Ω=tanβℓ 因式分解的证明口径，本族数值实现逐位复核）。

docstring 逐字引文（防漂移钉）："λ/8@ωc 传输线 Z）[cosθ, jZ·sinθ; j·sinθ/Z, cosθ]；串联短路线段" + "四恒等式在**任意公共电长 θ**（commensurate）下两侧 ABCD 逐位相等"

### 四恒等式（Pozar Table 8.7，精确等效变换）

（docstring 原文转写）

```latex
(a)\,\frac{[\parallel stub][ue]}{\text{左}}\equiv\frac{[ue/n^2][\text{串联短路}\,ue/n^2]}{\text{右}},\quad n^2=1+\frac{Z_2}{Z_1}
```

出处：模块 docstring「四恒等式」节（行语义按 stub/ue 显式命名消除错位、输出回显元素清单；(a)(b) 无变压器=串联↔并联、开路↔短路双转换；(c)(d) 同型换位+变压器阻抗重整）。

docstring 逐字引文（防漂移钉）："(a) [并联开路 stub] · [UE ue] ≡ [UE stub/n²] · [串联短路 ue/n²]，n²=1+stub/ue" + "(b) [串联短路 stub] · [UE ue] ≡ [UE n²·stub] · [并联开路 n²·ue]，n²=1+ue/stub"

### 三阶低通全并联实现（Example 8.5 全链）

（docstring 原文转写）

```latex
g\to\mathrm{Richards}(\lambda/8@\omega_c)\to+UE\to(b)\times 2\to Z_0\ \mathrm{定标}
```

出处：模块 docstring「三阶低通全并联实现」节（本族精确值 64.931/70.254/64.931/217.435，圆整窗 0.5% 内一致；全链 ABCD 等价残差字段）。

docstring 逐字引文（防漂移钉）："文献数值锚（#122）：g=(3.3487, 0.7117, 3.3487)、Z₀=50Ω" + "→ 并联短截线 64.9/70.3/64.9Ω、连接线 217.5Ω（Pozar 图 8.36(e) 三位"

### KD-1 出处注册（`src/rfauto/core/calc_families/kuroda_identities.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/kuroda_identities:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `kuroda_identities`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 域首键：全仓 grep（kuroda）注册键面此前零命中——本族为该域首批注册键（R2 §③ D9 附注同证）。
  - docstring 逐字引文："- 全仓 grep（kuroda）src/tests 零命中（R2 §③ D9 附注同证）；本族为该域"
- Richards 变换本体单源 core/stub_k_inverter（P.I. Richards 1948 同源）——本族不重复实现，仅输出 Ω=tan(θ) 映射值供互查；stub_filter_design=短截线 BPF 综合不同对象。
  - docstring 逐字引文："Richards 变换本体已在 core/stub_k_inverter.py（richards_omega/"
- 一般 N 阶的级联恒等式迭代化实现留续作——N=3 两端化=Pozar 原例口径如实声明（不冒充一般阶完备面）。
  - docstring 逐字引文："一般 N 阶的级联恒等式迭代化实现不在本键（留续作，"
- θ=0/π 线段零长奇异显式拒绝；realize 键 g 须 3 元全正、z0>0——越界一律显式 ValueError。
  - docstring 逐字引文："守卫：identity ∈{1,2,3,4}；z1/z2>0；θ∈(0,π) 且 sinθ≠0（θ=0/π 线段零"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/kuroda_identities.py:kuroda_identity_abcd`
- `src/rfauto/core/calc_families/kuroda_identities.py:kuroda_shunt_realize`

src/rfauto/core/calc_families/kuroda_identities.py 公开符号 **2** 个（AST 机读）：

`kuroda_identity_abcd`、`kuroda_shunt_realize`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w4s14_core_edge.py`——引文："Kuroda 恒等式族（aurora_f W4-S14 席域 2，R2_core_tier3 边际池立项）。"

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
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

