<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：multisection_coupler

> 多节对称定向耦合器族（架构批 A6-B 席域 1，R7_core_tier2 §② G5 余量；

| 字段 | 值 |
|---|---|
| 内核 ID | `multisection_coupler` |
| 主模块 | `src/rfauto/core/calc_families/multisection_coupler.py`（`rfauto.core.calc_families.multisection_coupler`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/multisection_coupler.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

多节对称定向耦合器：二项式（中心最大平坦）与等纹波 Chebyshev 两成员综合（结点权→节耦合→逐节偶/奇阻抗）与偶/奇模精确级联四端口频响——构造恒无耗互易、f0 隔离口精确零。

模块自述（docstring 首行，机读）：多节对称定向耦合器族（架构批 A6-B 席域 1，R7_core_tier2 §② G5 余量；

## 公式与口径

### 偶/奇模精确级联四端口构造（Pozar §7.6 同源）

（docstring 原文转写）

```latex
S_{11}=\tfrac{S_{e11}+S_{o11}}{2},\ S_{21}=\tfrac{S_{e21}+S_{o21}}{2},\ S_{31}=\tfrac{S_{e11}-S_{o11}}{2},\ S_{41}=\tfrac{S_{e21}-S_{o21}}{2}
```

出处：模块 docstring「偶/奇模精确级联」节（偶/奇模各为 2 端口级联链端接 Z0；该构造恒满足无耗 |S11|²+|S21|²+|S31|²+|S41|²=1 与互易——测试钉）。

docstring 逐字引文（防漂移钉）："S11=(Se11+So11)/2   S21=(Se21+So21)/2（直通）" + "S31=(Se11−So11)/2（耦合）   S41=(Se21−So21)/2（隔离）"

### 单节精确闭式（N=1 退化裁判）

（docstring 原文转写）

```latex
|S_{31}|=\frac{c\sin\theta}{\sqrt{1-c^2\cos^2\theta}},\quad c=\frac{2g}{1+g^2},\ g=\frac{Z_{0e}-Z_0}{Z_{0e}+Z_0},\quad|S_{31}(90^\circ)|=c
```

出处：模块 docstring「单节精确闭式」节（Z0e·Z0o=Z0² 配对下 Γ0o=−Γ0e 故 S31=Γe；θ=90° 处恰=c 精确非近似——f0 隔离口精确零）。

docstring 逐字引文（防漂移钉）："S31=Γe，|S31|=c·sinθ/√(1−c²cos²θ)，c=2g/(1+g²)、g=(Z0e−Z0)/(Z0e+Z0)"

### 二项式结点权（中心最大平坦一阶小反射）

（docstring 原文转写）

```latex
g(x)\propto\int_0^x(1-t^2)^M\,\mathrm{d}t=\sum_k\frac{(-1)^k\binom{M}{k}}{2k+1}x^{2k+1}
```

出处：模块 docstring「二项式」节（N=2M+1 奇数节镜像对称；与 sin 多项式按 x 奇次展开三角分解解线性方程组；电平归一对精确偶/奇级联在 θ=90° 二分求根——f0 精确命中目标耦合）。

docstring 逐字引文（防漂移钉）："g(x) ∝ ∫₀ˣ(1−t²)^M dt = Σ_k (−1)^k·C(M,k)/(2k+1)·x^(2k+1)" + "三角分解解线性方程组即 Γ_i（N=3 → 结点比 1:9:9:1、节耦合比 1:10:1；"

### 等纹波成员与 (Z0e,Z0o) 配对闭式

（docstring 原文转写）

```latex
Q_M(y)=1+\varepsilon(-1)^M T_M(1-2y/Y),\quadZ_{0e}=Z_0\sqrt{\tfrac{1+c}{1-c}},\ Z_{0o}=Z_0\sqrt{\tfrac{1-c}{1+c}}
```

出处：模块 docstring（等纹波 Chebyshev 成员=Q_M 母多项式三角分解，与二项式成员 flatness 语义分派字段；(Z0e,Z0o) 同 core/slotline_transitions.even_odd_from_coupling 闭式，配对性质给出 f0 隔离口精确零）。

docstring 逐字引文（防漂移钉）："multisection_coupler_equiripple（等纹波 Chebyshev 成员：Q_M=1+ε·T_M(1−" + "（Z0e=Z0√((1+c)/(1−c))、Z0o=Z0√((1−c)/(1+c))，恒 Z0e·Z0o=Z0²——该"

### KD-1 出处注册（`src/rfauto/core/calc_families/multisection_coupler.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/multisection_coupler:<module>:01 | <module> | source | — | 出处（Pozar《Microwave Engineering》§7.6/§7.83-7.84；Levy 1966；MY69；Coupled-Line Directional Coupler", Microwaves 1966 同族；精确等纹波 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `multisection_coupler`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 域首键：全仓 grep 注册键面此前零命中（R7 G5 余量）；synthesis.py synthesize_multisection_quarter_wave=λ/4 阻抗变换器匹配域（同名非耦合器）不并入。
  - docstring 逐字引文："- 全仓 grep（multisection|multi_section|levy|n_section.*coupl）注册键面"
- 边界防撞：bethe_hole_coupler=波导孔耦合单节综合、coupled_line_bpf_*=带通谐振器实现（交叉口开路端接非直通 4 口）——本族补多节级联直通四端口（单节=N=1 退化档互证）。
  - docstring 逐字引文："变换器**匹配**域（同名 multisection 非耦合器）；bethe_hole_coupler="
- 数值锚面（#118 独立来源）：精确级联 vs 一阶口径差如实并列报告（有限耦合二阶差 0.1–0.5dB 量级 @10dB 不隐藏）；能量守恒残差 ≤1e-12 全频轴；|S31(90°−δ)| 对称残差 ≤1e-12。
  - docstring 逐字引文："- 精确级联 vs 一阶：θ=90° |S31|−目标 ≤0.1dB（10dB/3 节档）；能量守恒"
- 过耦不可实现显式拒绝；response 键列表同长 ≥1、Z0e>Z0o>0、freq>0 且避开任一节 θ=kπ 奇异点（显式拒绝，coupled_line_bpf_response 同口径）。
  - docstring 逐字引文："守卫：n_sections 为正奇整数（≤15）；coupling_db∈(0,60]；逐节 c_i<0.99"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/multisection_coupler.py:multisection_coupler_binomial`
- `src/rfauto/core/calc_families/multisection_coupler.py:multisection_coupler_response`
- `src/rfauto/core/calc_families/multisection_coupler.py:multisection_coupler_equiripple`

src/rfauto/core/calc_families/multisection_coupler.py 公开符号 **3** 个（AST 机读）：

`multisection_coupler_binomial`、`multisection_coupler_response`、`multisection_coupler_equiripple`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_a6b_multisection_gysel.py`——引文："数值锚（#118 独立来源；锚树 tests/unit/test_a6b_multisection_gysel.py）"

测试面（tests/unit 引用扫描，机读；合计 **87** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a6b_multisection_gysel.py` | 21 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w4s14_core_edge.py` | 17 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

