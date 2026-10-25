<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：slot

> G16 矩形波导缝隙阵 Stevenson 族（批 B Wave3 W3-G15G16，2026-10-13）。

| 字段 | 值 |
|---|---|
| 内核 ID | `slot` |
| 主模块 | `src/rfauto/core/calc_families/slot_array.py`（`rfauto.core.calc_families.slot_array`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 2 条（kernel_file=src/rfauto/core/calc_families/slot_array.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

矩形波导宽壁纵向缝 Stevenson 族：谐振缝并联相对电导正反解（含波导尺寸比与驻波因子两修正）与谐振（驻波）阵综合（导电率阶梯→逐缝偏置/交替换边/短路位）——行波阵与有限壁厚修正不在键面，理想化偏差方向注记在档。

模块自述（docstring 首行，机读）：G16 矩形波导缝隙阵 Stevenson 族（批 B Wave3 W3-G15G16，2026-10-13）。

## 公式与口径

### Stevenson 谐振缝并联相对电导

（docstring 原文转写）

```latex
g(x)=\frac{G}{G_0}=2.09\,\frac{a}{b}\,\frac{\lambda_g}{\lambda_0}\cos^2\!\Big(\frac{\pi\lambda_0}{2\lambda_g}\Big)\sin^2\!\Big(\frac{\pi x}{a}\Big)
```

出处：模块 docstring「物理口径」节（法源 Stevenson 1948 J. Appl. Phys. 19——原文 closed 式号不可考禁编造，式形态经四路独立二手源逐字互证+WR90 数值逐位复算，RESOLVED 裁决与勘误表在档）。

docstring 逐字引文（防漂移钉）："g(x) = G/G0 = 2.09·(a/b)·(λg/λ0)·cos²(π·λ0/(2·λg))·sin²(π·x/a)"

### 偏置反解与可达上限

（docstring 原文转写）

```latex
x=\frac{a}{\pi}\arcsin\sqrt{\frac{g}{g_{\max}}},\quad g_{\max}(f)=2.09\,\frac{a}{b}\,\frac{\lambda_g}{\lambda_0}\cos^2\!\Big(\frac{\pi\lambda_0}{2\lambda_g}\Big)
```

出处：模块 docstring（与 PIER C 56 (2015) 式 (4) 同形态；g 超可达上限显式拒绝——高频端单缝匹配不可达是公式行为非缺陷，边界频率同节在档）。

docstring 逐字引文（防漂移钉）："x = (a/π)·arcsin(sqrt(g/g_max))，其中" + "g_max(f) = 2.09·(a/b)·(λg/λ0)·cos²(πλ0/(2λg))。g > g_max 显式拒绝"

### 谐振（驻波）阵综合口径

（docstring 原文转写）

```latex
g_n=g_{\mathrm{total}}\frac{w_n^2}{\sum_i w_i^2},\quad d=\frac{\lambda_g}{2},\quad l_{\mathrm{res}}\approx\frac{\lambda_0}{2}
```

出处：模块 docstring「谐振（驻波）阵综合」节（缝间距半导波波长相邻交替换边保证同相、末缝后四分之一导波波长短路；理想缝长口径的 kl≈π 假设显式化，实测缩短文献带附注）。

docstring 逐字引文（防漂移钉）："各缝同相功率叠加口径 gn = g_total·wn²/Σw²"

### KD-1 出处注册（`src/rfauto/core/calc_families/slot_array.py`，knowledge/formula_provenance.yaml 过滤）

命中 **2** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/slot_array:<module>:01 | <module> | source | — | — |
| calc_families/slot_array:<module>:02 | <module> | source | 10.1063/1.1697868 | 10.1063/1.1697868；arXiv:2608.21231；- 法源：Stevenson 1948, J. Appl. Phys. 19, 24-38, DOI 10.1063/1.1697868 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `slot`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 族界：行波（非谐振）阵 Elliott 迭代综合、有限壁厚/缝宽修正（实测曲线数字化不可自证）、窄壁斜缝表不在键面——如实登记续作，不冒充已实现。
  - docstring 逐字引文："行波（非谐振）阵的"
- 理想化偏差方向注记：有限壁厚使电导恒定高估（WR90 全波标定在档，方向与 Oliner 变分处理一致）——修正不在键面。
  - docstring 逐字引文："有限壁厚使 Stevenson 式**高估**电导——"
- 偏置域两恰值端点接受（零偏置退化缝/缝缘上限）；公式对 偏置偶函数，负偏置取绝对值、相位符号由交替换边承担。
  - docstring 逐字引文："0 ≤ x ≤ a/2（x=0 恰值接受输出 g=0 缝退化无扰动；x=a/2 恰值接受"
- 单缝电导超可达上限显式拒绝并给出可行出路提示——不静默裁剪。
  - docstring 逐字引文："gn ≤ g_max（超限显式拒绝并提示降 g_total/收窄幅度锥度）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/slot_array.py:slot_stevenson_conductance`
- `src/rfauto/core/calc_families/slot_array.py:slot_array_synthesis_resonant`

src/rfauto/core/calc_families/slot_array.py 公开符号 **2** 个（AST 机读）：

`slot_stevenson_conductance`、`slot_array_synthesis_resonant`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `runs/aurora_c/batch_b_wave3_specs/G16_slot_array_stevenson_RESOLVED.md`（runs/ 证据面，gitignored，存在性不作测试断言）——引文："边界防撞（R7 §③ 三重搜索证据沿用规格包）"
- `tests/unit/test_b_wave3_yagi_slot.py`——引文："（锚树 tests/unit/test_b_wave3_yagi_slot.py）。"

测试面（tests/unit 引用扫描，机读；合计 **119** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_aurora_d_core8.py` | 26 |
| `tests/unit/test_b_wave3_yagi_slot.py` | 32 |
| `tests/unit/test_calc_sympy_oracle.py` | 12 |
| `tests/unit/test_calculators.py` | 49 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

