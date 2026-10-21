<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：gysel_core

> Gysel 功分器 core 电气闭式族（架构批 A6-B 席域 2，R7_core_tier2 §② G6

| 字段 | 值 |
|---|---|
| 内核 ID | `gysel_core` |
| 主模块 | `src/rfauto/core/calc_families/gysel_core.py`（`rfauto.core.calc_families.gysel_core`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/gysel_core.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

Gysel 功分器 core 电气闭式族：六 λ/4 电气段拓扑（桥带 λ/2 中点=对称面真实节点）+偶/奇模半电路验证+五线六节点导纳网络精确频响——隔离负载外置可独立散热，是与内嵌电阻 Wilkinson 的族界。

模块自述（docstring 首行，机读）：Gysel 功分器 core 电气闭式族（架构批 A6-B 席域 2，R7_core_tier2 §② G6

## 公式与口径

### 六 λ/4 电气段拓扑（#206 定版）

（docstring 原文转写）

```latex
P_1\xrightarrow{\sqrt{2}Z_0}P_{2/3},\quad P_{2/3}\xrightarrow{Z_0}\Delta_{1/2},\quad \Delta_1\xrightarrow{Z_0\,\lambda/2}\\\Delta_2
```

出处：模块 docstring「物理口径」节（Δ1/Δ2 各端接 Z0 负载，可独立散热=大功率口径）。

docstring 逐字引文（防漂移钉）："拓扑（六 λ/4 电气段）：P1—[√2·Z0 臂]—P2 与 P1—[√2·Z0 臂]—P3；" + "P2—[Z0 隔离线]—Δ1 与 P3—[Z0 隔离线]—Δ2；Δ1—[Z0 λ/2 桥带，中点 M]—"

### 偶/奇模半电路验证（Γe=Γo=0）

（docstring 原文转写）

```latex
\Gamma_e=\Gamma_o=0,\quad S_{22}=S_{32}=0
```

出处：模块 docstring（对称面虚开路/虚地；f0 精确匹配+隔离闭式）。

docstring 逐字引文（防漂移钉）："偶模：臂 λ/4 把 2Z0 变换为 Z0（Γe=0）；桥带半段 λ/4 端接虚开路→短" + "奇模：P1/M=虚地，臂与桥带半段 λ/4 变开路；输出只见 λ/4 隔离线端接"

### 理想 f0 三口 S 矩阵

（docstring 原文转写）

```latex
S_{21}=S_{31}=-\tfrac{j}{\sqrt{2}},\quad S_{32}=0
```

出处：模块 docstring（−3.0103dB 恒等；互易非幺正如实注记）。

docstring 逐字引文（防漂移钉）："理想 f0 三口 S 矩阵：S21=S31=−j/√2（臂 −90°+均分 3.0103dB）、全对角" + "与 S32=0（互易 S=Sᵀ；内负载吸收→非无耗不幺正，如实注记）。"

### 五线六节点导纳网络精确频响

（docstring 原文转写）

```latex
Y_{\mathrm{self}}=-j\frac{\cot\theta}{Z_c},\quad Y_{\mathrm{mutual}}=\frac{j}{Z_c\sin\theta}
```

出处：模块 docstring（内节点消元得 3 口 Y_red；耗散守恒 |a1|²=Σ|b_k|²+|V_Δ1|²/Z0+|V_Δ2|²/Z0 残差字段构造恒成立）。

docstring 逐字引文（防漂移钉）："Y_self=−j·cotθ/Zc、Y_mutual=j/(Zc·sinθ)（λ/4 反解 Z_in=Zc²/ZL 由该"

### KD-1 出处注册（`src/rfauto/core/calc_families/gysel_core.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/gysel_core:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `gysel_core`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- λ/2 桥带是隔离的必要环节（判废对照字段在键，#206 同口径）。
  - docstring 逐字引文："判废锚（#206）：无桥带朴素拓扑带心 S21≈−6.5dB——λ/2 桥带"
- 频域奇异守卫：f=2k·f0 线节 θ=kπ 显式拒绝（桥带按 M 拆两段规避 f0 奇异）。
  - docstring 逐字引文："守卫：z0_ohm>0；freq_ghz/f0_ghz>0 且避开线节 θ=kπ 奇异点（f=2k·f0 显"
- 族界三层：模板级（synthesize_gysel_model 出几何）/裁判级（fake 理想 S）/本族=core 注册计算器级（纯电气+频响带宽面）。
  - docstring 逐字引文："（纯电气闭式，无叠层依赖；频响键补全 f0 以外的带宽行为，模板/裁判均"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/gysel_core.py:gysel_core_synthesize`
- `src/rfauto/core/calc_families/gysel_core.py:gysel_frequency_response`

src/rfauto/core/calc_families/gysel_core.py 公开符号 **2** 个（AST 机读）：

`gysel_core_synthesize`、`gysel_frequency_response`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_a6b_multisection_gysel.py`——引文："tests/unit/test_a6b_multisection_gysel.py"

测试面（tests/unit 引用扫描，机读；合计 **70** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a6b_multisection_gysel.py` | 21 |
| `tests/unit/test_calculators.py` | 49 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

