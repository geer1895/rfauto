<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：link_limits

> 链路极限面（aurora_g W1-S2 席域 C1，R2_core_tier4 §③ Top1 设计案）。

| 字段 | 值 |
|---|---|
| 内核 ID | `link_limits` |
| 主模块 | `src/rfauto/core/calc_families/link_limits.py`（`rfauto.core.calc_families.link_limits`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/link_limits.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

链路极限面：Shannon 容量与频谱效率恒等式、FSPL 真空基准闭式、Friis dB 形逐项可加链路账与余量——容量口径物理下界（极限 Eb/N0 面）的独立键位，环境统计路损模型显式端口化不并入本族。

模块自述（docstring 首行，机读）：链路极限面（aurora_g W1-S2 席域 C1，R2_core_tier4 §③ Top1 设计案）。

## 公式与口径

### Shannon 容量与频谱效率恒等式（AWGN 带限信道）

（docstring 原文转写）

```latex
C=B\,\log_2(1+\mathrm{SNR})\ [\mathrm{bps}],\quad \eta=\frac{C}{B}=\log_2(1+\mathrm{SNR})\ [\mathrm{bit/s/Hz}]
```

出处：模块 docstring「公式口径」节（Cover & Thomas *Elements of Information Theory* 2nd ed. ch.5；Shannon 1948/1949 原文口径；SNR 线性/dB 双口径互斥显式择一同节）。

docstring 逐字引文（防漂移钉）："C = B·log2(1 + SNR)" + "η = C/B = log2(1 + SNR)"

### 容量极限 Eb/N0 反演面（Shannon 极限）

（docstring 原文转写）

```latex
\mathrm{Eb/N0}_{\min}=\frac{2^{\eta}-1}{\eta},\quad \lim_{\eta\to 0}\mathrm{Eb/N0}_{\min}=\ln 2\approx -1.5918\ \mathrm{dB}
```

出处：模块 docstring（η=2 → 1.76091 dB 教科书点同段；输出物理下界——实现调制需求面走 required_ebn0，margin=需求−极限由调用方相减）。

docstring 逐字引文（防漂移钉）："Eb/N0_min = (2^η − 1)/η" + "η→0 极限 = ln2 = −1.59175 dB（Shannon 极限，逐位锚）；η=1 → 0 dB、"

### 自由空间路损（Friis 1946 / ITU-R P.525 dB 形）

（docstring 原文转写）

```latex
\mathrm{FSPL}=\left(\frac{4\pi d}{\lambda}\right)^2,\ \lambda=\frac{c}{f},\quad\mathrm{FSPL}_{dB}=20\lg(4\pi d f/c)
```

出处：模块 docstring（1km@1GHz=92.4478 dB、1m@1GHz=32.4478 dB 精确 SI 光速锚；教科书 32.44 常数形=c≈3e8 圆化口径差 6.0mdB 如实；真空恒等式 20lg(d/λ)+20lg(4π) 随 identity 残差字段自检）。

docstring 逐字引文（防漂移钉）："FSPL = (4πd/λ)²，λ = c/f" + "FSPL_dB = 20·lg(4πd·f/c)"

### Friis dB 形逐项可加链路账与余量

（docstring 原文转写）

```latex
P_r=P_t+G_t+G_r-\mathrm{FSPL}_{dB}-L_{misc}\ [\mathrm{dBm}],\quad\mathrm{margin}=P_r-P_{sensitivity}\ [\mathrm{dB}]
```

出处：模块 docstring（与 Friis 线性式 P_r/P_t=G_t·G_r·(λ/4πd)² 逐位等价，10lg 换算恒等非近似；margin 恒等式随残差字段自检；rfid_forward_link 前向链内嵌式同仓双源对拍钉）。

docstring 逐字引文（防漂移钉）："P_r = P_t + G_t + G_r − FSPL_dB − L_misc" + "margin = P_r − P_sensitivity"

### KD-1 出处注册（`src/rfauto/core/calc_families/link_limits.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/link_limits:<module>:01 | <module> | source | — | ITU-R   P.525；Elements of Information Theory 2nd ed. ch.5；Shannon 1948/1949 原文；- free_space_path_loss：FSPL=(4πd/λ)²（Friis 1946 传输公式；ITU-R |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `link_limits`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 环境（城市/室内）损耗以 excess_loss_db 显式加性端口透传，不预设经验档——统计环境模型本体走 propagation.hata_cost231/tr38901（边界防撞节）。
  - docstring 逐字引文："随输出 identity 残差字段自检。**环境修正不做预设档**（#1c 禁凭记忆"
- 边界防撞：mimo=矩阵容量+注水（本族只做标量链）、required_ebn0=实现调制需求面（本族输出容量极限面，margin 判读=需求−极限由调用方相减）、satellite/itu_link=卫星与气象细项、gt_ratio=G/T 优值——互指不互代。
  - docstring 逐字引文："mimo.mimo_channel_capacity=矩阵容量 log₂det(I+γHH†)（本族只做标量"
- 数值锚面（#118 独立来源）：d/f 加倍恒 +6.0205999 dB、dB 双口径同参一致（<1e-12）、对 rfid_forward_link 同参对拍 p_tag=P_r——锚树 tests/unit/test_w1s2_link_fec.py。
  - docstring 逐字引文："- 链路账：d 加倍 → margin 精确 −6.0206 dB；灵敏度 +X dB → margin −X"
- 全部越界显式 ValueError（距离/频率>0、损耗/功率/增益/灵敏度有限）；SNR 双口径同给=口径歧义显式拒绝；snr_db 上限=10**(db/10) 双精度溢出面收缩（W3-S1 审查 P3-3）。
  - docstring 逐字引文："守卫：bandwidth_hz>0、SNR 线性值>0、snr_db ∈ (−∞, 3000]"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/link_limits.py:shannon_capacity`
- `src/rfauto/core/calc_families/link_limits.py:free_space_path_loss`
- `src/rfauto/core/calc_families/link_limits.py:link_margin_calc`

src/rfauto/core/calc_families/link_limits.py 公开符号 **3** 个（AST 机读）：

`shannon_capacity`、`free_space_path_loss`、`link_margin_calc`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w1s2_link_fec.py`——引文："数值锚（#118 独立来源；锚树 tests/unit/test_w1s2_link_fec.py）"

测试面（tests/unit 引用扫描，机读；合计 **129** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calc_sympy_oracle.py` | 12 |
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w1s2_link_fec.py` | 24 |
| `tests/unit/test_w4s1_review_guards.py` | 20 |
| `tests/unit/test_w4s4_core_margin.py` | 24 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

