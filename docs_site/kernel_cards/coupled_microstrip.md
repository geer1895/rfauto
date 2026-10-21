<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：coupled_microstrip

> 耦合微带 / 抽头谐振器闭式内核（core 叶层；WP2.3 hairpin 收口 ⑦ 升格，2026-09-16）。

| 字段 | 值 |
|---|---|
| 内核 ID | `coupled_microstrip` |
| 主模块 | `src/rfauto/core/coupled_microstrip.py`（`rfauto.core.coupled_microstrip`） |
| 计算器注册表 | 未注册（AST 无 @register_calculator 装饰器——service 直调型内核，免 #231 注册表消费者三表同步） |
| KD-1 出处注册 | 0 条（kernel_file=src/rfauto/core/coupled_microstrip.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

耦合微带闭式内核：Kirschning-Jansen 1984 准静态偶/奇模阻抗与频变 εeff 色散层（Getsinger 型）+ hairpin 结构经验修正 c(gap)（显式 opt-in）——闭式部分零经验常数，经验常数真机溯源、域外不外推。

模块自述（docstring 首行，机读）：耦合微带 / 抽头谐振器闭式内核（core 叶层；WP2.3 hairpin 收口 ⑦ 升格，2026-09-16）。

## 公式与口径

### KJ 1984 准静态偶/奇模阻抗

（docstring 原文转写）

```latex
Z_{0e},\,Z_{0o}=f_{\mathrm{KJ}}(u,g,\varepsilon_r),\qquad u=\frac{w}{h},\; g=\frac{s}{h}
```

出处：coupled_microstrip_even_odd_ohm docstring；单线量取 skrf HJ 正向（core/synthesis.forward_z0），与 Qucs/transcalc c_microstrip.cpp 零厚无盖分支逐式对应。

docstring 逐字引文（防漂移钉）："耦合微带准静态偶/奇模阻抗（Kirschning-Jansen 1984 闭式；零厚/无盖）。"

### 频变偶/奇 εeff（Getsinger 型色散层，W4-A/P1）

（docstring 原文转写）

```latex
\varepsilon_{\mathrm{eff},e/o}(f)=\varepsilon_r-\frac{\varepsilon_r-\varepsilon_{\mathrm{eff},e/o}(0)}{1+F_{e/o}}
```

出处：模块 docstring W4-A/P1 节（KJ 1984 论文式 (2)-(7)）；式面与三独立源逐式核对（Wcalc/Qucs 技术文档/qucs-core），P1 加式形态以论文原文影印定谳。

docstring 逐字引文（防漂移钉）："Getsinger 型 εeff,e/o(f)=εr−(εr−εeff,e/o(0))/(1+F_e/o)、P1-P15 色散系数），"

### 耦合系数与缝反解

（口径示意（非 docstring 原式，读代码为准））

```latex
k=\frac{Z_{0e}-Z_{0o}}{Z_{0e}+Z_{0o}}\;\xrightarrow[\;\mathrm{brentq}\;]{}\; s
```

出处：模块 docstring；hairpin_gap_mm_from_k 单调性单测钉住，xtol=1e-12mm。

docstring 逐字引文（防漂移钉）："- 平行耦合半波谐振器耦合系数 k=(Z0e−Z0o)/(Z0e+Z0o)（Hong §5.4）及 brentq 反解；"

### 抽头外部 Q（本仓派生，独立校核）

（docstring 原文转写）

```latex
Q_e=\frac{\pi}{2}\frac{Z_0}{Z_r}\sec^2(\pi\tau),\qquad \tau=\frac{1}{\pi}\arccos\sqrt{\frac{(\pi/2)(Z_0/Z_r)}{Q_e}}
```

出处：模块 docstring（#118 独立校核：单测以精确分布参数 Y_res(ω) 数值微分对拍）。

docstring 逐字引文（防漂移钉）："- 抽头外部 Q：Q_e=(π/2)(Z0/Z_r)sec²(πτ)（本仓派生，单测以精确分布参数 Y_res(ω)"

### KD-1 出处注册（`src/rfauto/core/coupled_microstrip.py`，knowledge/formula_provenance.yaml 过滤）

命中 **0 条**——该模块 docstring 无「出处见/出处（」收集标记命中或未逐式登记。出处以模块 docstring 为单源（上方公式引文即逐字出自 docstring）；登记缺口如实呈现，属 XA-6 出处断链巡检门的巡检范围，不在本卡掩饰。

## 精度域（XC-P 精度档案）

XC-P 已建档（knowledge/precision_profiles.yaml#coupled_microstrip），out_of_domain_behavior=`REFUSE`、last_verified=2026-09-17。

| quantity | band | direction | unverified | condition |
|---|---|---|---|---|
| coupling_k | k_NG/k_KJ=1.003/1.018/1.049 @gap 0.8/1.1328/1.6mm（KJ 平行线口径低估 k 约 0.3~4.9%） | underestimate | False | 独立 NGSolve 2D 准静态对照（runs/hairpin_kgap/offline_kj_vs_ngsolve.json）；闭式本身独立来源核实无误。 |
| hairpin_kgap_correction | 单口径真机标定表（4 点分段线性内插，表点逐位精确）；跨口径外推 UNVERIFIED | unknown | False | 本战役 openEMS N=2 弱抽头双谐振器真机（scripts/hairpin_q_extract.py --kgap-analyze 可复算，铁律 7）；域外缺省 ValueError（clamp 仅限 fake 前向裁判显式假设）。 |
| qe_tap_frac | Q_e=(π/2)(Z0/Z_r)sec²(πτ) 本仓派生闭式，精确分布参数 Y_res(ω) 数值微分独立校核（#118） | none | False | 独立裁判口径（单测钉）。 |

域声明 note：KJ 1984 准静态闭式适用条件：零厚、无盖、s/h≥0.1（规格预声明准静态适用下界）；hairpin 结构经验修正 c(gap) 限同口径几何（rogers4350b h=0.508/er=3.66、w=1.1117、f0=2.5GHz、τ=0.43、N=2、openEMS 0.4mm 网格）且标定域 gap∈[0.5, 1.1328]mm（域外缺省 raise 不外推）。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- wcalc 与 qucs-core 在 Q18 常数上互斥且原文不可达——#1c/#122 如实登记不解锁。
  - docstring 逐字引文："阻抗色散（论文式 (10)/(11)）**不实现**——"
- KJ 域盒（u/g/εr/fn）域外显式拒绝——论文精度声明仅覆盖域内。
  - docstring 逐字引文："有效域（论文式 (1)+p.85，域外显式 ValueError 不外推）：0.1≤u≤10、"
- c(gap) 结构修正是 hairpin 专属经验层——闭式本体已由 NGSolve 2D 独立核实（k_NG/k_KJ 比值在档），修正不污染平行线口径。
  - docstring 逐字引文："故修正只作用于 hairpin 通道、显式 opt-in"
- 经验修正域外两通道不同语义显式分道：设计反解 raise、fake 前向显式 clamp。
  - docstring 逐字引文："适用域见 HAIRPIN_KGAP_CALIB，域外不外推（设计反解 raise；fake 前向可显式 clamp）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/coupled_microstrip.py:coupled_microstrip_even_odd_ohm`
- `src/rfauto/core/coupled_microstrip.py:coupled_microstrip_eps_disp`
- `src/rfauto/core/coupled_microstrip.py:hairpin_gap_mm_from_k`
- `src/rfauto/core/coupled_microstrip.py:hairpin_kgap_correction`
- `src/rfauto/core/coupled_microstrip.py:hairpin_arm_len_mm`
- `src/rfauto/core/coupled_microstrip.py:hairpin_tap_frac_from_qe`

src/rfauto/core/coupled_microstrip.py 公开符号 **11** 个（AST 机读）：

`hairpin_kgap_domain_mm`、`hairpin_kgap_correction`、`hairpin_arm_len_mm`、`coupled_microstrip_even_odd_ohm`、`coupled_microstrip_eps_disp`、`hairpin_kgap_design_branch_mm`、`hairpin_k_from_gap_mm`、`hairpin_gap_mm_from_k`、`hairpin_qe_from_tap_frac`、`hairpin_tap_frac_from_qe`、`coupled_bpf_width_gap_from_zee_zoo`

消费面（service/adapters 引用扫描，机读）：

- service：`src/rfauto/service/anchor_family_service.py`
- service：`src/rfauto/service/even_odd_service.py`
- adapters：`src/rfauto/adapters/fake_adapter/adapter.py`
- adapters：`src/rfauto/adapters/oe_templates/closedform.py`
- adapters：`src/rfauto/adapters/oe_templates/render_hairpin.py`
- adapters：`src/rfauto/adapters/oe_templates/render_ta_wave_b.py`

## 锚与测试入口

analytic-anchor（knowledge/anchors.yaml 机读命中）：

| anchor_id | quantity |
|---|---|
| `coupled_microstrip.kj_even_domain.lit-v1` | kj_even_domain_dev_pct |

判据书/规格指针（docstring 逐字引文钉）：

- `runs/hairpin_kgap/offline_kj_vs_ngsolve.json`（仓内档，公开分发视图不随附，存在性不作测试断言）——引文："偶/奇模 k_NG/k_KJ=1.003/1.018/1.049 @gap 0.8/1.1328/1.6，runs/hairpin_kgap/"

测试面（tests/unit 引用扫描，机读；合计 **264** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a3c_coupled_interdigital.py` | 20 |
| `tests/unit/test_edb_templates_ext.py` | 38 |
| `tests/unit/test_hairpin_alt_template.py` | 26 |
| `tests/unit/test_hairpin_kgap_correction.py` | 16 |
| `tests/unit/test_hairpin_q_extract.py` | 11 |
| `tests/unit/test_hairpin_template.py` | 37 |
| `tests/unit/test_marchand_two_section.py` | 22 |
| `tests/unit/test_qw10_qw11.py` | 14 |
| `tests/unit/test_sensanc_analytic_anchors.py` | 11 |
| `tests/unit/test_varactor.py` | 26 |
| `tests/unit/test_w1s3_lange_stepped.py` | 11 |
| `tests/unit/test_w4_a_sm_core.py` | 21 |
| `tests/unit/test_width_single_source.py` | 11 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

