<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：link

> link 族（LT-1 G/T 组合键，round18 :129，追加尾位 2026-10-02）。

| 字段 | 值 |
|---|---|
| 内核 ID | `link` |
| 主模块 | `src/rfauto/core/calc_families/link.py`（`rfauto.core.calc_families.link`） |
| 同族模块 | `src/rfauto/core/gt_link.py` |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/link.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

G/T 组合优值（ITU-R S.733-2 定义口径）：T_sys 三路径显式择一（直接给定/级联总 NF 换算/y 因子链等效输入噪声温度）——cascade_budget 输出字段同名直连的接收优值键。

模块自述（docstring 首行，机读）：link 族（LT-1 G/T 组合键，round18 :129，追加尾位 2026-10-02）。

## 公式与口径

### G/T 定义（ITU-R S.733-2 口径）

（docstring 原文转写）

```latex
G/T=G_{\mathrm{dB}}-10\lg(T_{\mathrm{sys}})\ [\mathrm{dB/K}]
```

出处：模块 docstring（ITU-R S.733-2 定义级引用；T0=290K IEEE 噪声温度基准与 nf_measurement.T0_K 同源同值）。

docstring 逐字引文（防漂移钉）："（ITU-R S.733-2 定义口径）：G/T = G_dB − " + "10·log10(T_sys) [dB/K]。T_sys 三路径显式择一：t_sys_k 直接给定 /"

### T_sys 三路径（显式互斥择一）

（docstring 原文转写）

```latex
T_{\mathrm{sys}}=t_{\mathrm{ant}}+T_e,\quadT_e=T_0(F-1)\ (NF\ \text{路径}),\quadT_{\mathrm{sys}}=t_{\mathrm{ant}}\ (\mathrm{antenna\_only})
```

出处：模块 docstring「三条 T_sys 路径」节（直接给定/级联总 NF 换算/y 因子链等效输入噪声温度显式互斥选择；同给按优先级取用并如实报告冗余）。

docstring 逐字引文（防漂移钉）："nf_db（=cascade_budget.nf_total_db 直连，Te=T0·(F−1)）/ t_e_k" + "温度，三者全缺省时退化为 antenna_only（T_sys=t_ant_k，如实标注）。"

### 消费面同名直连（级联输出即输入）

（docstring 原文转写）

```latex
G/T\leftarrow\mathrm{cascade\_budget}.(gain\_total\_db,\ nf\_total\_db)
```

出处：模块 docstring（消费面设计：级联输出直接喂本键；Te 亦可取自 nf_measurement.y_factor→te_from_y 链）。

docstring 逐字引文（防漂移钉）："（gain_total_db/nf_total_db）同名直连——级联面输出即本键输入。"

### KD-1 出处注册（`src/rfauto/core/calc_families/link.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/link:<module>:01 | <module> | source | — | ITU-R S.733-2 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `link`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- T_sys>0 域守卫（≤0 显式 ValueError）；数值合法性检查 bool 显式拒收、有限数（0.0 合法）。
  - docstring 逐字引文："边界语义：G/T 分母 T_sys>0 域守卫（T_sys≤0 显式 ValueError）；数值"
- 薄注册纪律：内核在 core/gt_link（纯函数零 IO），本模块只注册不实现、零公式复制（同 exposure_limits/t_match 惯例）。
  - docstring 逐字引文："内核在 core/gt_link.py（纯函数零 IO），本模块只做注册薄壳"
- 数值锚=恒等式回收（T_sys 路径往返/G−10lgT 恒等），非文献转引数值——定义级引用如实标注，锚树见判据书指针。
  - docstring 逐字引文："（定义级引用；数值锚=恒等式回收，见 tests/unit/test_gt_link_calculators.py）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/link.py:gt_ratio`

src/rfauto/core/calc_families/link.py 公开符号 **1** 个（AST 机读）：

`gt_ratio`

src/rfauto/core/gt_link.py 公开符号 **1** 个（AST 机读）：

`gt_ratio`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_gt_link_calculators.py`——引文："（定义级引用；数值锚=恒等式回收，见 tests/unit/test_gt_link_calculators.py）。"

测试面（tests/unit 引用扫描，机读；合计 **120** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_gt_link_calculators.py` | 9 |
| `tests/unit/test_sat_link.py` | 27 |
| `tests/unit/test_w1k2_core_domains.py` | 35 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

