<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：hf_skywave

> HF 电离层天波族（aurora_g W7-S3 席，R3_domain_expansion 视角3 D1

| 字段 | 值 |
|---|---|
| 内核 ID | `hf_skywave` |
| 主模块 | `src/rfauto/core/calc_families/hf_skywave.py`（`rfauto.core.calc_families.hf_skywave`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/hf_skywave.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

HF 3-30MHz 电离层传播机理三键：等离子体频率/临界频率恒等式、割线定律 MUF（平地单跳几何档）、冷等离子体折射指数标度——全频段维度唯一整段空白的补口件（传播机理面，不做处理链）。

模块自述（docstring 首行，机读）：HF 电离层天波族（aurora_g W7-S3 席，R3_domain_expansion 视角3 D1

## 公式与口径

### 等离子体频率/临界频率（冷等离子体无磁场极限）

（docstring 原文转写）

```latex
f_p=\frac{1}{2\pi}\sqrt{\frac{N_e e^2}{m_e\,\varepsilon_0}}=8.978663\sqrt{N_e}
```

出处：Davies《Ionospheric Radio》(IEE 1990) ch.1/ITU-R P.531 通用口径（SI 2019+CODATA 2018 常数；系数开工日数值锤 8.978662820487434 Hz·m^1.5，教科书 9√Ne [kHz, cm⁻³] 同值圆化）。

docstring 逐字引文（防漂移钉）："f_p = (1/2π)·√(N_e·e²/(m_e·ε₀)) = 8.978663·√(N_e)  [Hz，N_e m⁻³]"

### 割线定律 MUF+平地单跳几何档

（docstring 原文转写）

```latex
MUF=f_o\sec i,\quad \sin i=\frac{d/2}{\sqrt{h^2+(d/2)^2}}
```

出处：Davies ch.5/Skolnik HF 天波章通用口径；i→0 退化 MUF=f_o 逐位、i≥90° cos≤0 显式拒绝（发散守卫）；hop_km+virtual_height_km 同给走平地几何档。

docstring 逐字引文（防漂移钉）："MUF = f_o·sec(i) = f_o/cos(i)" + "sin(i) = (d/2) / √(h² + (d/2)²)"

### 冷等离子体折射指数标度（Appleton-Hartree 单轴极限）

（docstring 原文转写）

```latex
n^2=1-\left(\frac{f_p}{f}\right)^2,\quad v_{ph}=\frac{c}{n},\ v_g=c\,n
```

出处：Davies ch.1 同式；v_ph·v_g=c² 逐位恒等（相速超光速为色散介质正常属性非违例——数值锤实测 v_ph·v_g/c²=1.0）。

docstring 逐字引文（防漂移钉）："n² = 1 − (f_p/f)²" + "f>f_p 传播档（n 实；相速 v_ph=c/n、群速 v_g=c·n、v_ph·v_g=c² 恒等"

### KD-1 出处注册（`src/rfauto/core/calc_families/hf_skywave.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/hf_skywave:<module>:01 | <module> | source | — | ITU-R P.531；1990) ch.1/ch.5 教科书恒等式+ITU-R P.531 同口径（零新引源，R3 报告 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `hf_skywave`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- incidence_deg 直给档与 hop_km+virtual_height_km 平地几何档二选一（部分给显式拒绝）；球形地球 M(3000)F2 曲线修正不在本键口径如实声明。
  - docstring 逐字引文："i 直给档与几何档互斥（双给/缺省显式拒绝）。"
- f=f_p 截止档 n=0、f<f_p 渐消档 n=None——不产出 NaN 假数；法拉第旋转/O-X 波双折射（磁场项）不在本键口径。
  - docstring 逐字引文："如实）；f<f_p 渐消档（n²<0，n=None 不出 NaN——#122 如实）"
- NVIS 档/M(3000)F2 因子曲线/P.368 场强/P.372 噪声带等半经验表原文本次环境不可达，如实缺席不凑卡。
  - docstring 逐字引文："半经验表，本次环境不可达不 ship（#122 如实缺席）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/hf_skywave.py:critical_frequency`
- `src/rfauto/core/calc_families/hf_skywave.py:secant_law_muf`
- `src/rfauto/core/calc_families/hf_skywave.py:ionospheric_plasma_frequency`

src/rfauto/core/calc_families/hf_skywave.py 公开符号 **3** 个（AST 机读）：

`critical_frequency`、`secant_law_muf`、`ionospheric_plasma_frequency`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w7s3_core_domains.py`——引文："物理口径（#1c/#300 出处纪律；教科书恒等式，2026-10-19 数值锤独立实测）"

测试面（tests/unit 引用扫描，机读；合计 **77** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calc_cross_validation.py` | 5 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w7s3_core_domains.py` | 23 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

