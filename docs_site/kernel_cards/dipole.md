<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：dipole

> 线天线/环输入阻抗族（架构批 A3-B 席域 2，R7 第二梯队 T4）。

| 字段 | 值 |
|---|---|
| 内核 ID | `dipole` |
| 主模块 | `src/rfauto/core/calc_families/linear_antenna_zin.py`（`rfauto.core.calc_families.linear_antenna_zin`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/linear_antenna_zin.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

线天线/环输入阻抗族：有限长偶极辐射功率积分电阻+感应电动势法电抗经典闭式（谐振长度域内二分）、折合偶极两模并联（等粗谐振四倍阻抗恒等）与小环辐射电阻三式恒等+趋肤损耗/效率/Q——细线闭式档，矩量法曲线不在键面。

模块自述（docstring 首行，机读）：线天线/环输入阻抗族（架构批 A3-B 席域 2，R7 第二梯队 T4）。

## 公式与口径

### 偶极输入电阻（正弦电流辐射功率积分）

（docstring 原文转写）

```latex
R_{\mathrm{in}}=\frac{\eta}{2\pi\sin^2(kh)}\int_0^{\pi}\frac{\big(\cos(kh\cos\theta)-\cos kh\big)^2}{\sin\theta}\,d\theta
```

出处：模块 docstring「物理口径」节（对正弦电流分布假设精确的功率积分路线，定精度确定式；短偶极渐近与半波教科书常数双锚测试钉）。

docstring 逐字引文（防漂移钉）："R_in = η/(2π·sin²(kh))·∫₀^π [cos(kh·cosθ)−cos(kh)]²/sinθ dθ"

### 偶极输入电抗（感应电动势法经典闭式）

（docstring 原文转写）

```latex
X=\frac{\eta}{4\pi}\Big\{2\,\mathrm{Si}(kl)+\cos(kl)\big[2\,\mathrm{Si}(kl)-\mathrm{Si}(2kl)\big]-\sin(kl)\big[2\,\mathrm{Ci}(kl)-\mathrm{Ci}(2kl)-\mathrm{Ci}(2ka^2/l)\big]\Big\}
```

出处：模块 docstring（感应电动势法经典闭式，Balanis §8.4 印刷形；谐振长度 X=0 域内二分与细线锚带同节）。

docstring 逐字引文（防漂移钉）："X = (η/4π)·{2Si(kl) + cos(kl)·[2Si(kl)−Si(2kl)]" + "− sin(kl)·[2Ci(kl)−Ci(2kl)−Ci(2ka²/l)]}"

### 折合偶极两模并联（天线模+传输线模）

（docstring 原文转写）

```latex
Z_{\mathrm{in}}=\frac{4 Z_d\cdot 2j Z_t\tan(kl/2)}{4 Z_d+2j Z_t\tan(kl/2)},\quad Z_t=\frac{\eta}{\pi}\,\mathrm{acosh}\frac{s}{2a}
```

出处：模块 docstring「折合偶极」节（Balanis 传输线法两模分解；半波谐振处线模支路开路 → 阻抗为等效偶极四倍——等粗线径/间距在谐振点约去=恒等锚）。

docstring 逐字引文（防漂移钉）："Z_in = 4Z_d·(2jZ_t·tan(kl/2))/(4Z_d + 2jZ_t·tan(kl/2))"

### 小环输入阻抗分解（三式恒等+趋肤损耗）

（docstring 原文转写）

```latex
R_r=320\pi^4 N^2\big(A/\lambda^2\big)^2\equiv 20\pi^2 N^2(C/\lambda)^4,\quad L=\mu_0 b\big[\ln(8b/a)-2\big],\quad Q=\frac{X}{R_r+R_L}
```

出处：模块 docstring「小环」节（面积/周长/数值三式恒等测试钉；趋肤电阻损耗口径+Grover 单匝圆环电感闭式；Q 为输入阻抗分解副产品，与天线 Q 面语义不同）。

docstring 逐字引文（防漂移钉）："Rr = 320π⁴·N²·(A/λ²)²（A=πb²）≡ 20π²·N²·(C/λ)⁴（C=2πb）" + "L = μ0·b·[ln(8b/a) − 2]，X = 2πf·N²·L（密绕 N² 近似，匝间"

### KD-1 出处注册（`src/rfauto/core/calc_families/linear_antenna_zin.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/linear_antenna_zin:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `dipole`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 单瓣正弦电流假设域内有效；全波馈点电流节点阻抗发散属模型奇点显式拒绝——域外不外推。
  - docstring 逐字引文："守卫：length_mm ∈ (0, λ)（单瓣正弦电流假设域；l=λ 全波馈点电流节点"
- 电抗闭式在半波点与归一重合、远离谐振区为工程近似档（感应电动势法）——精度不及矩量法如实注记。
  - docstring 逐字引文："为工程近似档（感应电动势法），精度不及矩量法。"
- 细偶极 King 数值逼近/矩量法曲线属经验档，如实不做——电阻路线对正弦电流分布假设是精确积分（口径边界自明）。
  - docstring 逐字引文："细偶极 King 数值逼近/矩量法曲线档不在本键口径（Sin-King 曲线的"
- 折合偶极只做等线径档（谐振点线径/间距约去=恒等锚）；不等线径 Mushiake 步升比不在键面，如实不做。
  - docstring 逐字引文："不等线径 Mushiake 精确步升比不在本键口径"
- 小环电小判据守卫——超出电小假设如实拒绝，不外推。
  - docstring 逐字引文："守卫（超出电小假设如实拒绝）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/linear_antenna_zin.py:dipole_emf_zin`
- `src/rfauto/core/calc_families/linear_antenna_zin.py:folded_dipole_zin`
- `src/rfauto/core/calc_families/linear_antenna_zin.py:small_loop_zin`

src/rfauto/core/calc_families/linear_antenna_zin.py 公开符号 **3** 个（AST 机读）：

`dipole_emf_zin`、`folded_dipole_zin`、`small_loop_zin`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_a3b_stub_antenna.py`——引文："（架构批 A3-B 席域 2，R7 第二梯队 T4）"

测试面（tests/unit 引用扫描，机读；合计 **77** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a3b_stub_antenna.py` | 28 |
| `tests/unit/test_calculators.py` | 49 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

