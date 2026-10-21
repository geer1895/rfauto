<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：slotline

> 槽线（slotline）闭式：Janaswamy–Schaubert 曲线拟合式（W3⑧a 路线 A 闭式裁判面）。

| 字段 | 值 |
|---|---|
| 内核 ID | `slotline` |
| 主模块 | `src/rfauto/core/slotline.py`（`rfauto.core.slotline`） |
| 计算器注册表 | 未注册（AST 无 @register_calculator 装饰器——service 直调型内核，免 #231 注册表消费者三表同步） |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/slotline.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

槽线闭式裁判面：Janaswamy–Schaubert 1986 曲线拟合式分段落地（常数三源逐位互证），段界外显式 ValueError 不外推——转录未闭环的分段如实登记不解锁，禁止凭记忆补常数。

模块自述（docstring 首行，机读）：槽线（slotline）闭式：Janaswamy–Schaubert 曲线拟合式（W3⑧a 路线 A 闭式裁判面）。

## 公式与口径

### 窄槽段 λ'/λ0（式 (8)，低 εr 段）

（docstring 原文转写）

```latex
\frac{\lambda'}{\lambda_0}=1.045-0.365\ln\varepsilon_r+\frac{6.3\,(W/d)\,\varepsilon_r^{0.945}}{238.64+100\,W/d}-\Bigl[0.148-\frac{8.81(\varepsilon_r+0.95)}{100\,\varepsilon_r}\Bigr]\ln\frac{d}{\lambda_0}
```

出处：_lambda_ratio_low docstring（Janaswamy–Schaubert MTT-34(8):900-902 式 (8)；原文拟合误差 Av 0.37% / Max 2.2% 同节照录）。

docstring 逐字引文（防漂移钉）："λ'/λ0 = 1.045 − 0.365 ln εr + 6.3 (W/d) εr^0.945 / (238.64 + 100 W/d)" + "− [0.148 − 8.81 (εr + 0.95) / (100 εr)] ln(d/λ0)"

### 窄槽段 Z0（式 (9)，低 εr 段）

（docstring 原文转写）

```latex
Z_0=60+3.69\sin\frac{(\varepsilon_r-2.22)\pi}{2.36}+133.5\ln(10\,\varepsilon_r)\sqrt{W/\lambda_0}+\cdots
```

出处：_z0_low docstring（式 (9)；常数三源核对——NTRS OCR/Majumdar-Verma/NJIT FORTRAN 逐位闭合，见模块头）。

docstring 逐字引文（防漂移钉）："Z0 = 60 + 3.69 sin[(εr − 2.22)π/2.36] + 133.5 ln(10 εr) √(W/λ0)"

### εeff / β / Z0 口径（功率-电压定义）

（docstring 原文转写）

```latex
\varepsilon_{\mathrm{eff}}=\Bigl(\frac{\lambda_0}{\lambda'}\Bigr)^{\!2},\quad \beta=k_0\sqrt{\varepsilon_{\mathrm{eff}}},\quad Z_0=\frac{|V_0|^2}{2P}
```

出处：模块 docstring「几何/记号」节。

docstring 逐字引文（防漂移钉）："输出：λ'/λ0（槽波长比）、εeff=(λ0/λ')²、β=k0·√εeff、Z0（功率-电压定义" + "Z0=|V0|²/(2P)，Janaswamy 式 (1)，与 NGSolve 模场后处理口径一致）。"

### KD-1 出处注册（`src/rfauto/core/slotline.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| slotline:<module>:01 | <module> | source | — | on Low-Permittivity Substrates," IEEE Trans. MTT-34(8), pp. 900–902, Aug. 1986；Slot Antenna"（UMass 1986，NASA NTRS 19870016815）§3.3 式 (3.9)–(3.16；IJMOT 4(2) 2009 pp.83-89 的重排式（其 0.0599/8.3695 = −0.148+0.0881 与；0.083695 = 0.0881×0.95 等展开系数逐位闭合）+ NJIT 论文 (Tumialan 1996) 附录；p.532, 1976（Cohn/Mariani 等效波导模型曲线拟合）——**本模块仍未实现**（原文；19870016815）§3.3 式 (3.10)；② S. Chakraborty 等, JSIR 64(7):482-486；2005（排版干净转录，归引 J-S MTT-34(8):900-902）；③ UMass 报告附录 A |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `slotline`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 有效域三条件（d/λ0、W/λ0 段、εr 段）同时满足，任一越界 ValueError 不外推。
  - docstring 逐字引文："- 0.006 ≤ d/λ0 ≤ 0.06（全部式子共同前提）"
- 高 εr 段（Garg–Gupta 1976 式）未实现——各通道不可达即维持显式拒绝（#122）。
  - docstring 逐字引文："系数未取得可双源核对的文本，禁止凭记忆写常数；2026-10-05 W4-B 复查：O'Reilly/"
- 宽槽 Z0 式 (11)/(14)/(15) 三个独立转录源互相冲突、段界连续性裁判无法闭环——如实未实现，不凑闭环。
  - docstring 逐字引文："证据状态记档不凭记忆补常数（#122 如实）。"
- 宽槽低 εr 档已落地：系数三源逐位一致 + 与窄槽式 (8) 段界对拍的独立判据（#118）在档。
  - docstring 逐字引文："式 (10)（2.22 ≤ εr ≤ 3.8 宽槽 λ'/λ0）**已实现**（`slotline_wide_low`）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/slotline.py:slotline_closed_form`
- `src/rfauto/core/slotline.py:slotline_segment`
- `src/rfauto/core/slotline.py:slotline_wide_low`
- `src/rfauto/core/slotline.py:slotline_z0`
- `src/rfauto/core/slotline.py:slotline_beta`
- `src/rfauto/core/slotline.py:slotline_eps_eff`

src/rfauto/core/slotline.py 公开符号 **13** 个（AST 机读）：

`SlotlineResult`、`slotline_segment`、`slotline_closed_form`、`slotline_lambda_ratio`、`slotline_eps_eff`、`slotline_z0`、`slotline_beta`、`slotline_guide_wavelength_mm`、`SlotlineWideLowResult`、`slotline_wide_low`、`slotline_wide_lambda_ratio`、`slotline_wide_eps_eff`、`slotline_wide_beta`

消费面（service/adapters 引用扫描，机读）：

- service：`src/rfauto/service/slotline_service.py`
- adapters：`src/rfauto/adapters/fake_adapter/slotline_family.py`
- adapters：`src/rfauto/adapters/ngsolve_modes.py`
- adapters：`src/rfauto/adapters/oe_templates/render_slotline.py`
- adapters：`src/rfauto/adapters/slotline_transitions_template.py`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w4_b_p3_slotline_wide.py`——引文："tests/unit/test_w4_b_p3_slotline_wide.py 钉）。"

测试面（tests/unit 引用扫描，机读；合计 **213** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_c6_stub_sign_and_c7_gysel_miter.py` | 11 |
| `tests/unit/test_hfss_marchand_anchor.py` | 9 |
| `tests/unit/test_marchand_two_section.py` | 22 |
| `tests/unit/test_marchand_via_ab.py` | 18 |
| `tests/unit/test_ngsolve_modes.py` | 13 |
| `tests/unit/test_slotline_closed_form.py` | 14 |
| `tests/unit/test_slotline_family_registration.py` | 15 |
| `tests/unit/test_slotline_route_b.py` | 23 |
| `tests/unit/test_slotline_service.py` | 12 |
| `tests/unit/test_slotline_transitions.py` | 33 |
| `tests/unit/test_w11s4_core_domains.py` | 15 |
| `tests/unit/test_w4_b_p3_slotline_wide.py` | 15 |
| `tests/unit/test_x5_analytic_anchors.py` | 13 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

