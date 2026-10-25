<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：analog_modulation

> 模拟调制域闭式族（aurora_g W4-S4 席，R2 边际池外本席 grep 新发现）。

| 字段 | 值 |
|---|---|
| 内核 ID | `analog_modulation` |
| 主模块 | `src/rfauto/core/calc_families/analog_modulation.py`（`rfauto.core.calc_families.analog_modulation`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/analog_modulation.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

模拟调制域三闭式：FM/PM Carson 带宽规则、FM 处理增益 3β²(β+1) 与捕获门限三态标记、AM DSB-LC 功率分配与 PEP——数字链既有面（modulation BER/rx_impairments）的模拟姊妹面。

模块自述（docstring 首行，机读）：模拟调制域闭式族（aurora_g W4-S4 席，R2 边际池外本席 grep 新发现）。

## 公式与口径

### Carson 带宽规则（FM/PM）

（docstring 原文转写）

```latex
B\approx 2(\Delta f+f_m)=2(\beta+1)f_m,\quad\beta=\Delta f/f_m;\quadB_{PM}\approx 2(\Delta\phi+1)f_m
```

出处：模块 docstring（Carson 1922；Rappaport 2nd ed §5.3.1 承载；98% 功率容纳口径经验规则非精确边界——FM 广播 β=5→B=180kHz 教科书点逐位锚）。

docstring 逐字引文（防漂移钉）："FM：B ≈ 2·(Δf + f_m) = 2·(β + 1)·f_m，β = Δf/f_m" + "PM：B ≈ 2·(Δφ + 1)·f_m（Δφ = 峰值相偏 rad，等效 Δf = Δφ·f_m）"

### FM 处理增益（鉴频器抛物线噪声积分）

（docstring 原文转写）

```latex
G=\frac{\mathrm{SNR}_{out}}{\mathrm{CNR}_{RF}}=3\beta^2(\beta+1)
```

出处：模块 docstring（Rappaport §5.3.2 FM improvement factor；(3/2)β²·C/(N₀W) 形见 Haykin/Couch 标准推导；多步独立算术路径数值代回收 G=450@β=5，非同一公式两次抄写）。

docstring 逐字引文（防漂移钉）："SNR_out = (3/2)·β²·C/(N₀·W)         （鉴频器抛物线噪声积分）" + "出处：Rappaport §5.3.2 "FM improvement factor" I=3β²(β+1)；"

### AM DSB-LC 功率分配与 PEP

（docstring 原文转写）

```latex
P_{sb}=\frac{P_c m^2}{2},\quad\eta=\frac{m^2}{2+m^2},\quad\mathrm{PEP}=P_c(1+m)^2
```

出处：模块 docstring（任何模拟通信教科书/Rappaport §5.2 同族；m=1 → η=1/3 最大效率逐位、PEP=4P_c）。

docstring 逐字引文（防漂移钉）："载波 P_c；边带 P_sb = P_c·m²/2；总 P = P_c·(1 + m²/2)" + "功率效率 η = P_sb/P = m²/(2 + m²)；PEP = P_c·(1 + m)²"

### KD-1 出处注册（`src/rfauto/core/calc_families/analog_modulation.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/analog_modulation:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `analog_modulation`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- Carson 规则是 98% 功率容纳的经验规则非精确边界；β→0 退化 B→2f_m（窄带 FM 与 AM DSB 同宽——结构恒等式锚），PM 与 FM 在 Δφ≡β 数值同构。
  - docstring 逐字引文："98% 功率容纳口径的经验规则（非精确边界）；β→0 退化 B→2f_m（窄带"
- 门限效应：CNR 低于 ~10dB 时处理增益式失效（FM 捕获门限，工程惯例 7–12dB 区间）——本键取 10dB 标记位如实三态，门限本体的统计模型不做（UNVERIFIED 如实，#122）。
  - docstring 逐字引文："10dB 标记位如实三态——门限本体的统计模型不做，UNVERIFIED 如实）。"
- 边界防撞（#222 triple-grep）：modulation_ber=数字 BER 面、rx_impairments.phase_noise_evm=EVM 损伤面、pll_budget=锁相环相噪、fading=衰落统计、link_limits=链路极限——本族只做模拟调制三闭式。
  - docstring 逐字引文："- modulation_ber=数字调制 BER/编码增益面（本族只做模拟 FM/PM/AM）；"
- 域盒守卫：deviation/mod_freq/Δφ/β 正、cnr_db 有限、m∈(0,1]（m>1 过调制包络失真域外显式拒绝）——越界一律 ValueError。
  - docstring 逐字引文："守卫：deviation/mod_freq>0、Δφ>0、β>0、cnr_db 有限、m∈(0,1]——全部"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/analog_modulation.py:carson_bandwidth`
- `src/rfauto/core/calc_families/analog_modulation.py:fm_processing_gain`
- `src/rfauto/core/calc_families/analog_modulation.py:am_power_split`

src/rfauto/core/calc_families/analog_modulation.py 公开符号 **3** 个（AST 机读）：

`carson_bandwidth`、`fm_processing_gain`、`am_power_split`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w4s4_core_margin.py`——引文："数值锚（#118 独立来源；锚树 tests/unit/test_w4s4_core_margin.py）"

测试面（tests/unit 引用扫描，机读；合计 **73** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w4s4_core_margin.py` | 24 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

