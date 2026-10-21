<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：helix

> G17 helical（轴向模螺旋）CALC 注册面薄包装族（批 B Wave3 W3-G17G9，2026-10-13）。

| 字段 | 值 |
|---|---|
| 内核 ID | `helix` |
| 主模块 | `src/rfauto/core/calc_families/helix_axial_reg.py`（`rfauto.core.calc_families.helix_axial_reg`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/helix_axial_reg.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

轴向模螺旋天线 Kraus 经验闭式注册面：性能/反设计/带宽三键薄包装（物理公式单源在内核根模块，本模块只注册不实现零复制）——经验域判定与失效域 verdict 由内核单一语义源透传。

模块自述（docstring 首行，机读）：G17 helical（轴向模螺旋）CALC 注册面薄包装族（批 B Wave3 W3-G17G9，2026-10-13）。

## 公式与口径

### Kraus 经验闭式（性能面）

（口径示意（非 docstring 原式，读代码为准））

```latex
\mathrm{HPBW}=\frac{52}{C_\lambda\sqrt{N S_\lambda}},\quad \mathrm{FNBW}=\frac{115}{C_\lambda\sqrt{N S_\lambda}},\quad Z_{\mathrm{in}}\approx 140\,C_\lambda\ \Omega
```

出处：薄注册包装：公式零复制——Kraus 闭式常数（Balanis §10.3.1 转引）单源在 rfauto.core.helix_axial；锚值与阻抗/轴比恒等式见本模块 docstring（Balanis 工作例）。

docstring 逐字引文（防漂移钉）："物理公式单源在 ``rfauto.core.helix_axial``（B2 器件族批交付的 Kraus 闭式" + "（=140·C_λ 恒等）；AR(N=8)=1.0625（=1+1/2N）。"

### 薄度守卫（wrapper 恒等）

（口径示意（非 docstring 原式，读代码为准））

```latex
\mathrm{wrapper}(x)\equiv \mathrm{core}(x)\ \text{（逐字段逐位）}
```

出处：模块 docstring「薄注册纪律」节（wrapper 纯委托：参数单位换算+字段映射，不做任何数值变换、不 round——逐字段相等测试钉）。

docstring 逐字引文（防漂移钉）："薄度守卫 = wrapper 输出与 core 直调逐位一致**"

### KD-1 出处注册（`src/rfauto/core/calc_families/helix_axial_reg.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/helix_axial_reg:<module>:01 | <module> | pointer | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `helix`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 薄注册纪律：本模块只注册不实现、零公式复制（#116 死副本教训——本地副本遮蔽 re-export 即死代码）。
  - docstring 逐字引文："本模块**只注册不实现**，零公式复制（#116 死副本"
- Kraus 经验域严格判定（周长波长比/螺距角/圈数三条件）由内核侧透传——失效域内仍可计算但 verdict 带失效标记。
  - docstring 逐字引文："§10.3.1 转引；有效域 0.75<C_λ<4/3、12°<α<14°、N>3 严格；锚树"
- 域判定/失效域警告/恰等出域 verdict 全部由内核侧原样透传（单一语义源），本包装模块不自行判域。
  - docstring 逐字引文："不自行判域。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/helix_axial_reg.py:helix_axial_performance`
- `src/rfauto/core/calc_families/helix_axial_reg.py:helix_axial_design`
- `src/rfauto/core/calc_families/helix_axial_reg.py:helix_axial_bandwidth`

src/rfauto/core/calc_families/helix_axial_reg.py 公开符号 **3** 个（AST 机读）：

`helix_axial_performance`、`helix_axial_design`、`helix_axial_bandwidth`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_b_wave3_helix_reg.py`——引文："（tests/unit/test_b_wave3_helix_reg.py 逐字段 ``==`` 钉）"
- `tests/unit/test_helix_axial.py`——引文："tests/unit/test_helix_axial.py H1-H6 已 #118 合规在库——本席不重造"
- `None`（仓内档，公开分发视图不随附，存在性不作测试断言）——引文："薄注册纪律（规格包（内部档））"

测试面（tests/unit 引用扫描，机读；合计 **60** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_b_wave3_helix_reg.py` | 11 |
| `tests/unit/test_calculators.py` | 49 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

