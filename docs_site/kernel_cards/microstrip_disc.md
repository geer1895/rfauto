<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：microstrip_disc

> 微带不连续寄生闭式族（aurora_g W6-S3 席，R3_domain_expansion 视角1 A1

| 字段 | 值 |
|---|---|
| 内核 ID | `microstrip_disc` |
| 主模块 | `src/rfauto/core/calc_families/microstrip_disc.py`（`rfauto.core.calc_families.microstrip_disc`） |
| 同族模块 | `src/rfauto/core/calc_families/microstrip_extra.py` |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/microstrip_disc.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

微带全族闭式十键：不连续寄生七件——直角弯（未切角/50% 切角双档 Kirschning）、T 接头（Hammerstad-Bekkadal）、宽度阶跃（Garg-Bahl）、最优切角百分式（Douville-James）、串联间隙（Garg-Bahl π 网络，W11-S4）、开路端效应（HB/KJK 双档，W11-S4）与十字结四口网络（W15-S2）+损耗/接地过渡三件——线衰减率（Hammerstad-Jensen，W15-S2）、接地过孔（Goldfarb-Pucel，W15-S2）与开路端辐射电导（Balanis 两极限，W15-S2）——PCB layout 节点的寄生参数实体与损耗面（fake 裁判面「弯角寄生零」的对拍锚）。

模块自述（docstring 首行，机读）：微带不连续寄生闭式族（aurora_g W6-S3 席，R3_domain_expansion 视角1 A1

## 公式与口径

### 未切角直角弯寄生 L/C（Kirschning 1983）

（docstring 原文转写）

```latex
C=W\left[(10.35\,\varepsilon_r+2.5)\tfrac{W}{h}+(2.6\,\varepsilon_r+5.64)\right]\ \mathrm{pF},\quad L=220h\left(1-1.35\,e^{-0.18(W/h)^{1.39}}\right)\ \mathrm{nH}
```

出处：Kirschning 1983 MTT-S 式(20)(21) 逐字（经 Poole-Darwazeh 2015 Lecture 3 与 TU/e van Meeteren thesis 双源）；W/h≲1.4 负值=拟合域外显式拒绝。

docstring 逐字引文（防漂移钉）："C = W·[(10.35·εr+2.5)·(W/h) + (2.6·εr+5.64)]    pF（W 取 m）" + "L = 220·h·(1 − 1.35·exp(−0.18·(W/h)^1.39))      nH（h 取 m）"

### 50% 切角直角弯（同源式(22)(23)，qucsator 同式）

（docstring 原文转写）

```latex
C=W\left[(3.93\,\varepsilon_r+0.62)\tfrac{W}{h}+(7.6\,\varepsilon_r+3.80)\right]\ \mathrm{pF},\quad L=440h\left(1-1.062\,e^{-0.177(W/h)^{0.947}}\right)\ \mathrm{nH}
```

出处：同源式(22)(23) 逐字（=qucsator msmbend.cpp 可执行同式）；Douville-James 1978 实测结论：50% 切角对全部宽度/高度/介电常数/频率均改善反射（Visser 2007 EuCAP 转述）。

docstring 逐字引文（防漂移钉）："C = W·[(3.93·εr+0.62)·(W/h) + (7.6·εr+3.80)]    pF（W 取 m）" + "L = 440·h·(1 − 1.062·exp(−0.177·(W/h)^0.947))   nH（h 取 m）"

### T 接头臂长修正与并联电纳（Hammerstad-Bekkadal）

（docstring 原文转写）

```latex
d_{a,db}=0.055\,D_3\tfrac{Z_{a,b}}{Z_3}\left(1-2\tfrac{Z_{a,b}}{Z_3}\tfrac{f^2}{f_p^2}\right),\quad L_{a,b}=\tfrac{W_3}{2}-d_{a,db}
```

出处：HB 1975 ELAB STF44 A74169（经 qucsator mstee.cpp 可执行逐字转录）；负长度修正=参考面伸入结区簿记值，放行并输出 reference_planes_crossed 标记位；da·db<0 显式拒绝。

docstring 逐字引文（防漂移钉）："da,db = 0.055·D_3·(Z_{a,b}/Z_3)·(1 − 2·(Z_{a,b}/Z_3)·(f/f_p)^2)"

### 宽度阶跃等效 L/C（Garg-Bahl，只收收窄阶跃）

（docstring 原文转写）

```latex
C_s=\sqrt{W_1W_2}\left[(10.1\lg\varepsilon_r+2.33)\tfrac{W_1}{W_2}-12.6\lg\varepsilon_r-3.17\right]\ \mathrm{pF}
```

出处：Garg-Bahl 1978（经 qucsator msstep.cpp 可执行逐字，Qucs 手册引 Gupta [38]）；W1≤W2 时 Cs 括号为负=拟合域外显式拒绝；W1=W2 时 Ls≡0 逐位（直通退化恒等经同文件双路径锚）。

docstring 逐字引文（防漂移钉）："Cs = √(W1·W2)·[(10.1·lg εr+2.33)·(W1/W2) − 12.6·lg εr − 3.17]  pF" + "Ls = h·[(r−1)·(40.5+0.2·(r−1)) − 75·lg r]（r=W1/W2）           nH"

### 串联间隙 π 网络电容（Garg-Bahl，W11-S4）

（docstring 原文转写）

```latex
C_s=5\!\times\!10^{-10}h\,e^{-1.86\,s/h}\,Q_1\left[1+4.19\left(1-e^{-0.785\sqrt{1/W_1'}W_2'}\right)\right]\ \mathrm{F}
```

出处：Garg-Bahl（经 qucsator msgap.cpp 可执行逐字转录，Qucs 手册 §Microstrip gap）；等宽特化与 Bahl《Microstrip Lines and Slotlines》口径第三方转写互证；宽比 >3 显式拒绝（validity 注释原文）。

docstring 逐字引文（防漂移钉）："Cs = 5e-10·h·e^(−1.86·s')·Q1·[1+4.19·(1−e^(−0.785·√(1/W1')·W2'))]"

### 开路端效应 Δl 双档与等效电容（HB/KJK，W11-S4）

（docstring 原文转写）

```latex
C_{end}=\frac{\Delta l\sqrt{\varepsilon_{eff}}}{Z_0c_0},\quad \frac{|\Delta l_K-\Delta l_{HB}|}{\Delta l_{HB}}\le 5\%\ (w/h\le 2;\ \varepsilon_r{\ge}9\ \text{full})
```

出处：HB 0.412 档=仓内单源 slotline_transitions 复用+Kirschning-Jansen-Koster 1981 档（经 qucsator msopen.cpp calcCend 逐字）；双档横向一致性带如实记带锚不凑逐位。

docstring 逐字引文（防漂移钉）："C_end = Δl·√εeff/(Z0·c0)" + "≤5% 一致带包络随 εr 渐宽——εr≤5 W/h≤2.0、εr 6–7 W/h≤2.5"

### 十字结臂并联电容与中心电感（HB 系拟合，W15-S2）

（docstring 原文转写）

```latex
C_i=10^{-12}W_i\left(0.25X\,W_{1h}^{-1/3}-60+\tfrac{0.5}{W_{2h}}-0.375W_{1h}(1-W_{2h})\right),\quad L_5\leftarrow 0.8\,L_5
```

出处：qucsator mscross.cpp 可执行逐字+Qucs 手册 §Microstrip cross 式(11.226)-(11.231) 双源（基准 εr=9.9、精度 5%）；L5<0=手册明示模型固有（标记位放行）；εr=9.9 时式(11.231) 修正恒 1.0 逐位。

docstring 逐字引文（防漂移钉）："C_i = 1e-12·W_i·(0.25·X·W1h^(−1/3) − 60 + 0.5/W2h" + "L5 ← L5·0.8（手册明示经验改进"

### 微带导体/介质衰减率（Hammerstad-Jensen，W15-S2）

（docstring 原文转写）

```latex
\alpha_c=\frac{R_s}{Z_0W}K_iK_r,\quad K_i=e^{-1.2(Z_0/\eta_0)^{0.7}},\quad \alpha_d=\tfrac{\pi}{\lambda_0}\tfrac{\varepsilon_r}{\sqrt{\varepsilon_{eff}}}\tfrac{\varepsilon_{eff}-1}{\varepsilon_r-1}\tan\delta
```

出处：qucsator msline.cpp analyseLoss 可执行逐字+Qucs 手册 式(11.79)-(11.83) 双源；αd 同式同仓双源=thermal_iteration（εeff 源不同如实注记）；Ki 档 t>3δ 越窗标记。

docstring 逐字引文（防漂移钉）："αc = Rs/(Z0·W)·Ki·Kr                 （导体衰减 Np/m，11.80）" + "αd = (π/λ0)·(εr/√εeff)·((εeff−1)/(εr−1))·tanδ"

### 接地过孔 L/R（Goldfarb-Pucel 1991，W15-S2）

（docstring 原文转写）

```latex
R_{dc}=\frac{\rho h}{\pi(r^2-(r-t)^2)},\quad R(f)=R_{dc}\sqrt{1+f/f_\delta},\quad L=\tfrac{\mu_0}{2\pi}\left[h\ln\tfrac{h+\sqrt{r^2+h^2}}{r}+\tfrac{3}{2}(r-\sqrt{r^2+h^2})\right]
```

出处：Qucs 手册 式(11.232)-(11.234)+finetune.co.jp 独立转录双源；qucsator msvia.cpp 电感漏除 2π 偏差如实注记（数值锤：2mil GaAs D/H=0.5 手册形态 ~9.4pH 与 Microwaves101 工程口径相合，qucsator 形态 ~66pH 矛盾）；h<0.03λ0 守卫。

docstring 逐字引文（防漂移钉）："R_dc = ρ·h/(π·(r²−(r−t)²))           （空心圆柱 DC 电阻）" + "L    = (μ0/2π)·[h·ln((h+√(r²+h²))/r) + 1.5·(r−√(r²+h²))]（11.232）"

### 开路端辐射电导分段式（Balanis 两极限，W15-S2）

（docstring 原文转写）

```latex
G_r=\begin{cases}\tfrac{1}{90}(W/\lambda_0)^2 & W/\lambda_0\le1\\[2pt]\tfrac{1}{120}(W/\lambda_0) & W/\lambda_0\ge2\end{cases},\quad \tan\delta_{open}=\frac{G_r}{\omega C_{end}}
```

出处：Balanis 4th Ch.14 槽辐射电导两极限（SDSMT 讲义逐字+AWR 教程引 Bahl-Bhartia 1980 p.51 同式）；1<x<2 线性内插=本键声明工程约定（Balanis 只给极限，如实记档）；宽槽档与 patch_rin_edge_balanis 积分式 k0h→0 同仓渐近对拍。

docstring 逐字引文（防漂移钉）："G_r = (1/90)·(W/λ0)²                 （W/λ0 ≤ 1）" + "G_r = (1/120)·(W/λ0)                 （W/λ0 ≥ 2）"

### KD-1 出处注册（`src/rfauto/core/calc_families/microstrip_disc.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/microstrip_disc:<module>:01 | <module> | source | — | 出处：Kirschning-Jansen-Koster 1983 MTT-S（弯角两档，经 Poole-Darwazeh；2015 Lecture 3 式(20)-(23) 与 TU/e van Meeteren thesis 双源逐字；50% 切；角档另有 qucsator msmbend.cpp 可执行同式）；Douville-James 1978 MTT-26(3；Bekkadal 1975 ELAB STF44 A74169（T 接头，经 qucsator mstee.cpp 可执行逐；字）；Garg-Bahl 1978（阶跃，经 qucsator msstep.cpp 可执行逐字，Qucs 手册；内部证据档 在案）；Kirschning-Jansen-Koster 1981 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `microstrip_disc`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- rf_line=均匀线正反解（本族 T 接/阶跃内部复用同源 Z_i/εeff_i 不另立口径）；pcell_dsl/rf_trace_geometry=切角几何基元；coupled_microstrip=HB ΔW 均匀线线宽修正；patch_fringing_delta_l=patch 每边缘 fringing（仍归 synthesis 单源）；fake_adapter=理想裁判面（寄生零）。
  - docstring 逐字引文："本族只做微带不连续寄生参数闭式（L/C/参考面修正/频响面）。"
- 负长度修正（规范几何下即出现）=参考面伸入结区的簿记值（qucsator 无守卫照常装配同构）；da·db<0（f 过近高阶模截止、√(da·db) 结构破裂）显式 ValueError。
  - docstring 逐字引文："本键放行并输出 reference_planes_crossed 标记位如实呈现；da·db<0"
- 间隙拟合式宽比域 1≤W2/W1≤3（注释原文），超域显式拒绝；g→∞ 时 Cs 指数归零、等宽 W1=W2 时 C1==C2 逐位（flip 恒等锚）。
  - docstring 逐字引文："validity（qucsator msgap.cpp 注释原文 "equations are valid for"
- 接地过孔电感：qucsator msvia.cpp `ind = MU0·(...)` 漏除 2π（手册 11.232=μ0/2π、finetune.co.jp 转录同式；constants.h 实测 MU0=4πe-7）——本键按手册/G-P 形态落地并注记偏差（数值锤 2mil GaAs ~9.4pH 相合）。
  - docstring 逐字引文："**qucsator 可执行偏差如实注记**：msvia.cpp"
- 开路端辐射电导：两极限为 Balanis 逐字、1<x<2 内插=本键声明工程约定档（Bahl 系通行形态）——约定面如实记档不冒充原文条款（#122）。
  - docstring 逐字引文："1<x<2 线性内插（工程惯例；Balanis 只给两极限不设内插条款，"
- 十字结中心电感 L5<0=手册明示模型固有（脱离外部微带线不物理）——qucsator 同构放行+center_inductance_negative 标记位；L 拟合域 [0.5,2] 越窗标记不硬拒。
  - docstring 逐字引文："不物理，qucsator 无守卫照常装配，本键放行并输出"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/microstrip_disc.py:microstrip_bend_parasitics`
- `src/rfauto/core/calc_families/microstrip_disc.py:microstrip_t_junction_parasitics`
- `src/rfauto/core/calc_families/microstrip_disc.py:microstrip_step_parasitics`
- `src/rfauto/core/calc_families/microstrip_disc.py:microstrip_optimal_miter`
- `src/rfauto/core/calc_families/microstrip_disc.py:microstrip_open_end_parasitics`
- `src/rfauto/core/calc_families/microstrip_disc.py:microstrip_gap_parasitics`
- `src/rfauto/core/calc_families/microstrip_extra.py:microstrip_cross_parasitics`
- `src/rfauto/core/calc_families/microstrip_extra.py:microstrip_attenuation`
- `src/rfauto/core/calc_families/microstrip_extra.py:microstrip_via_short`
- `src/rfauto/core/calc_families/microstrip_extra.py:microstrip_open_end_radiation`

src/rfauto/core/calc_families/microstrip_disc.py 公开符号 **6** 个（AST 机读）：

`microstrip_bend_parasitics`、`microstrip_t_junction_parasitics`、`microstrip_step_parasitics`、`microstrip_optimal_miter`、`microstrip_open_end_parasitics`、`microstrip_gap_parasitics`

src/rfauto/core/calc_families/microstrip_extra.py 公开符号 **4** 个（AST 机读）：

`microstrip_cross_parasitics`、`microstrip_attenuation`、`microstrip_via_short`、`microstrip_open_end_radiation`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w6s3_core_domains.py`——引文："微带不连续寄生闭式族（aurora_g W6-S3 席，R3_domain_expansion 视角1 A1"
- `tests/unit/test_w15s2_core_domains.py`——引文："微带全族扩展四键（aurora_g W15-S2 席，R3_domain_expansion §④ A1 余量"

测试面（tests/unit 引用扫描，机读；合计 **138** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w10s4_core_domains.py` | 24 |
| `tests/unit/test_w11s4_core_domains.py` | 15 |
| `tests/unit/test_w15s2_core_domains.py` | 29 |
| `tests/unit/test_w6s3_core_domains.py` | 21 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

