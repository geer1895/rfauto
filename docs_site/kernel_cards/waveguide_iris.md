<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：waveguide_iris

> 矩形波导薄膜片/谐振窗匹配闭式族（架构批 A7-B 席域 1，任务书候补

| 字段 | 值 |
|---|---|
| 内核 ID | `waveguide_iris` |
| 主模块 | `src/rfauto/core/calc_families/waveguide_iris.py`（`rfauto.core.calc_families.waveguide_iris`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/waveguide_iris.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

矩形波导薄膜片面：感性/容性膜片归一化电纳正反解、感容组合谐振窗全传输条件与单膜片匹配双分支闭式——工程薄膜片近似档，数值模匹配为真机仲裁路径。

模块自述（docstring 首行，机读）：矩形波导薄膜片/谐振窗匹配闭式族（架构批 A7-B 席域 1，任务书候补

## 公式与口径

### 对称感性/容性薄膜片归一化电纳

（docstring 原文转写）

```latex
\frac{B_i}{Y_0}=-\frac{\lambda_g}{a}\cot^2\!\left(\frac{\pi d}{2a}\right),\quad\frac{B_c}{Y_0}=\frac{4b}{\lambda_0}\ln\csc\!\left(\frac{\pi d}{2b}\right)
```

出处：模块 docstring「物理口径」节（感性式用 λg、容性式用 λ0——两式 λ 依赖不同是通行工程式的真实不对称如实照录；极限自检 d→a 电纳趋零、d→0 感性 −∞/容性 +∞ 方向符号自洽）。

docstring 逐字引文（防漂移钉）："B/Y0 = −(λg/a)·cot²(πd/(2a))" + "B/Y0 = (4b/λ0)·ln csc(πd/(2b))，"

### 谐振窗全传输条件（感容组合总电纳归零）

（docstring 原文转写）

```latex
\ln\csc\!\left(\frac{\pi d_c}{2b}\right)=\frac{\lambda_g b}{4a\lambda_0}\cot^2\!\left(\frac{\pi d_i}{2a}\right)
```

出处：模块 docstring（cot²≥0 → sin(πd_c/2b)=exp(−·)∈(0,1] 恒可解；指数下溢（感性开口过小所需容性电纳超出闭式可达）显式拒绝）。

docstring 逐字引文（防漂移钉）："谐振窗：感性+容性膜片组合总电纳 B/Y0=0（f0 处全传输），给定感性开口" + "d_i 反解容性开口 d_c：ln csc(πd_c/2b) = (λg·b)/(4aλ0)·cot²(πd_i/2a)，"

### 单膜片匹配（并联电纳调配的波导实现）

（docstring 原文转写）

```latex
y(\ell)=\frac{y_L+jt}{1+jy_L t},\ t=\tan(\beta\ell);\quad(b^2+g^2-g)t^2-2bt+(1-g)=0
```

出处：模块 docstring「单膜片匹配」节（b_i=−Im{y(ℓ)}；感性分支标工程优先（功率容量/易实现惯例）双分支如实并列；匹配解 ABCD 回代 |Γin|≈0 构造级残差锚）。

docstring 逐字引文（防漂移钉）："(b²+g²−g)t² − 2b·t + (1−g) = 0（判别式 g[b²+(1−g)²]≥0 恒两实根，g>0" + "口反解 d=(2a/π)·arctan√(−a/(b_iλg))、b_i>0 → 容性反解"

### KD-1 出处注册（`src/rfauto/core/calc_families/waveguide_iris.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/waveguide_iris:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `waveguide_iris`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 出处分级（#122）：Marcuvitz Waveguide Handbook 闭式首阶形、经 Rizzi《Microwave Engineering: Passive Circuits》 ch.4 二级文献通行式转引——原文页码未逐位复读如实登记；厚膜片/有限厚度修正项不在本族口径。
  - docstring 逐字引文："级文献通行式转引——原文页码未逐位复读，如实登记；厚膜片/有限厚度修"
- 语义分层：rwg_mmt=数值模匹配（真机窗仲裁路径）、rw_tables=EIA 尺寸表、hybrid_junction=结器件 S 矩阵、stub_tuner=通用传输线支节调配——本族=工程薄膜片电纳闭式（膜片近似档）；λg 抽键与 slot_array 内嵌式/microstrip 准 TEM 三层不撞。
  - docstring 逐字引文："- core/rwg_mmt.py=**数值模匹配**工具（H 面阶梯/膜片=阶梯构件级联的广义"
- 数值锚面（#118 独立路线）：开口=全波导电纳 0 极限恒等；匹配解 ABCD 回代 |Γin|≈0、谐振窗回代 |B总|≈0 构造级残差；λg 对 fc 标度恒等式测试侧独立重解——锚树判据书。
  - docstring 逐字引文："数值锚（#118 独立路线）：极限恒等（开口=全波导 → 电纳 0）；匹配解"
- 截止以下无传播显式拒绝（膜片电纳语义失效）；d_mm 与 b_norm 恰给其一（正解/反解互斥双给拒绝）；|Γ|≥1 非物理拒绝——越界一律显式 ValueError。
  - docstring 逐字引文："守卫：a_mm/b_mm>0 且 b_mm≤a_mm（标准矩形波导口径）；f_ghz>0 且>fc10；"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/waveguide_iris.py:wg_iris_susceptance`
- `src/rfauto/core/calc_families/waveguide_iris.py:wg_resonant_window`
- `src/rfauto/core/calc_families/waveguide_iris.py:wg_iris_match`
- `src/rfauto/core/calc_families/waveguide_iris.py:waveguide_lambda_g`

src/rfauto/core/calc_families/waveguide_iris.py 公开符号 **4** 个（AST 机读）：

`wg_iris_susceptance`、`wg_resonant_window`、`wg_iris_match`、`waveguide_lambda_g`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_a7b_iris_guanella.py`——引文："tests/unit/test_a7b_iris_guanella.py 与 tests/unit/test_aurora_d_core8.py）"

测试面（tests/unit 引用扫描，机读；合计 **123** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a7b_iris_guanella.py` | 24 |
| `tests/unit/test_aurora_d_core8.py` | 26 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w10s4_core_domains.py` | 24 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

