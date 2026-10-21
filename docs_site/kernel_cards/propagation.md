<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：propagation

> propagation 族（AP-5 传播基础闭式包，§A-7，2026-10-02，追加尾位）。

| 字段 | 值 |
|---|---|
| 内核 ID | `propagation` |
| 主模块 | `src/rfauto/core/calc_families/propagation.py`（`rfauto.core.calc_families.propagation`） |
| 同族模块 | `src/rfauto/core/propagation.py` |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/propagation.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

传播基础闭式包：双径干涉（Fresnel 反射系数+断点距离）、刃形绕射 exact/approx/lee 三档（J(0) 勘误如实并存）、Hata+COST-231 统一域盒路损、COST-231 Walfisch-Ikegami 视距/非视距三分量——注册薄壳+纯函数内核双模块。

模块自述（docstring 首行，机读）：propagation 族（AP-5 传播基础闭式包，§A-7，2026-10-02，追加尾位）。

## 公式与口径

### 双径干涉路损（镜反射相干和+断点距离）

（docstring 原文转写）

```latex
L=\mathrm{FSPL}(d_{los})-20\log_{10}\!\left|1+\Gamma e^{j\Delta\phi}\right|,\quadd_{break}=\frac{4 h_{tx} h_{rx}}{\lambda}
```

出处：模块 docstring（Rappaport 2nd ed §4.6 口径：Fresnel 平面波反射系数 Γ_v/Γ_h、σ=0 纯介电 eps_r 单参数；d>>d_break 后包络 −40dB/dec 渐近）。

docstring 逐字引文（防漂移钉）："L=FSPL(d_los)−20log10|1+Γe^{jΔφ}|；附断点距离 d_break=4·h_tx·h_rx/λ、" + "d_break = 4·h_tx·h_rx/λ（第一菲涅尔半径明区判据，§4.6 惯例），"

### 刃形绕射三档（exact/approx/lee 并存互检）

（docstring 原文转写）

```latex
J(v)=6.9+20\log_{10}\!\left(\sqrt{(v-0.1)^2+1}+v-0.1\right),\quad v>-0.78
```

出处：模块 docstring（ITU-R P.526-15 §4 Fresnel-Kirchhoff 参数 v；exact=Fresnel 积分 scipy.special、approx=P.526 闭式、lee=Rappaport §4.11 分段式三档并存互检）。

docstring 逐字引文（防漂移钉）："J(v) = 6.9 + 20·log10(√((v−0.1)²+1) + v − 0.1)（P.526-15 式(60)族，" + "精确 J(0) = 6.02dB（经典"擦顶 6dB"），闭式 J(0) = 6.03dB（6.9 是"

### Hata+COST-231 统一域盒路损（频段分段）

（docstring 原文转写）

```latex
150\!-\!1500\,\mathrm{MHz}:\ \mathrm{Okumura\!-\!Hata};\quad 1500\!-\!2000\,\mathrm{MHz}:\ \mathrm{COST\!-\!231}
```

出处：模块 docstring（域盒 150–2000MHz/1–20km/30–200m/1–10m；两段接缝模型级不连续实测 urban=4.33dB/suburban=1.33dB、test 锚 hata_seam；COST 段城郊修正外推档如实 UNVERIFIED）。

docstring 逐字引文（防漂移钉）："- Hata/COST-231：Rappaport §4.10 承载——150–1500MHz 走 Okumura-Hata" + "ValueError。两段在 f=1500MHz 接缝存在模型级不连续（两套拟合常数"

### Walfisch-Ikegami 视距/非视距（COST 231 ch.4.4）

（docstring 原文转写）

```latex
L_{LOS}=42.6+26\lg d_{km}+20\lg f_{MHz};\quadL_{NLOS}=L_f+L_{rts}+L_{msd}
```

出处：模块 docstring（COST 231 final report ch.4.4 式(27)/ITU-R P.1411 同式承载；NLOS 三分量逐项分列、h_bs≤h_roof 档k_a=54/k_d=18−15·Δh_b/h_roof；h_bs>h_roof 内插档原文未复读不做显式拒绝——#1c 禁凭记忆写常数）。

docstring 逐字引文（防漂移钉）："教科书点 2000MHz/1km=108.62dB" + "metropolitan=−4+0.7(f/925−1)、medium=−4+1.5(f/925−1)，f=925MHz 时 "

### KD-1 出处注册（`src/rfauto/core/calc_families/propagation.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/propagation:<module>:01 | <module> | source | — | ITU-R P.526-15；ITU-R P.1411 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `propagation`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 实测勘误纪律（#118 裁判=独立来源）：任务书把闭式归 「Lee 近似」且记 J(0)=−6.9dB——实现后实测精确 J(0)=6.02dB/闭式 6.03dB（6.9 是电平偏置常数不是 J(0) 值）；Lee 分段式另立第三档，三档并存互检。
  - docstring 逐字引文："knife_edge_loss_lee_db（v>2.4 档 20log(0.225/v)），三档并存互检。"
- 菲涅尔区半径与净空：F_n 几何光学定义式+0.6·F1 净空判据（链路工程惯例 ITU-R P.530 系列口径）——辅助纯函数不注册，链路预算组合面 sat_link AP-9 消费。
  - docstring 逐字引文："F_n = √(n·λ·d1·d2/(d1+d2))（几何光学定义式）；"
- 薄壳分层：calc_families/propagation=注册薄壳（同 link/exposure_limits 惯例）、core/propagation.py=纯函数零 IO 内核；零求解器依赖（§A 包跨件裁决）、返回 JSON 可序列化值。
  - docstring 逐字引文："（链路预算组合面，sat_link AP-9 消费）。"
- 再分发口径（PV-011 ITU CC BY-NC-SA）：本件只用手算闭式与公式常数（事实性数值+出处标注），零 ITU 数据文件捆绑；域盒外显式 ValueError（Hata/WI 两式域盒各自显式）。
  - docstring 逐字引文："零 ITU 数据文件捆绑，无再分发阻碍。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/propagation.py:two_ray_loss`
- `src/rfauto/core/calc_families/propagation.py:knife_edge_loss`
- `src/rfauto/core/calc_families/propagation.py:hata_cost231`
- `src/rfauto/core/calc_families/propagation.py:walfisch_ikegami_los`
- `src/rfauto/core/calc_families/propagation.py:walfisch_ikegami_nlos`

src/rfauto/core/calc_families/propagation.py 公开符号 **5** 个（AST 机读）：

`two_ray_loss`、`knife_edge_loss`、`hata_cost231`、`walfisch_ikegami_los`、`walfisch_ikegami_nlos`

src/rfauto/core/propagation.py 公开符号 **11** 个（AST 机读）：

`reflection_coefficient`、`two_ray_breakpoint_m`、`two_ray_loss_db`、`knife_edge_loss_db`、`knife_edge_loss_approx_db`、`knife_edge_loss_lee_db`、`fresnel_zone_radius_m`、`clearance_ok`、`hata_cost231_db`、`walfisch_ikegami_los_db`、`walfisch_ikegami_nlos_parts`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_propagation.py`——引文："tests/unit/test_propagation.py（断点干涉峰 +6dB/远场斜率回归/"

测试面（tests/unit 引用扫描，机读；合计 **97** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_propagation.py` | 24 |
| `tests/unit/test_w4s4_core_margin.py` | 24 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

