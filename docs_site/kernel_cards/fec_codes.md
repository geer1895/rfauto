<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：fec_codes

> FEC 块码族（架构批 W1-S2 席域 C2，R2_core_tier4 §③ Top3 设计案）。

| 字段 | 值 |
|---|---|
| 内核 ID | `fec_codes` |
| 主模块 | `src/rfauto/core/calc_families/fec_codes.py`（`rfauto.core.calc_families.fec_codes`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/fec_codes.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

FEC 块码编码增益产生面：Hamming 完全码球填充界判定、RS MDS 纠错能力闭式与硬判 union bound 编码后 BER 反解的目标误码率净编码增益——coded_ber_estimate 输入参数（官方声明缺口）的产生面闭环。

模块自述（docstring 首行，机读）：FEC 块码族（架构批 W1-S2 席域 C2，R2_core_tier4 §③ Top3 设计案）。

## 公式与口径

### Hamming 码参数与完全码球填充界

（docstring 原文转写）

```latex
n=2^m-1,\ k=n-m,\ d_{\min}=3,\ t=1;\quad2^k\sum_{i=0}^{t}\binom{n}{i}\le 2^n
```

出处：模块 docstring「公式口径」节（Hamming BSTJ 1950；Lin & Costello 2nd ed. ch.3；n=2^m−1 全系完全码取等，perfect 判定逐位整数算术零浮点）。

docstring 逐字引文（防漂移钉）："n = 2^m − 1，k = n − m，d_min = 3，t = ⌊(d_min−1)/2⌋ = 1" + "Hamming bound（球填充界）2^k·Σ_{i=0}^{t}C(n,i) ≤ 2^n：t=1 时"

### RS MDS 纠错能力（Singleton 界取等）

（docstring 原文转写）

```latex
d_{\min}=n-k+1,\quad t=\left\lfloor\frac{n-k}{2}\right\rfloor,\quad 2e+f\le n-k
```

出处：模块 docstring（Reed & Solomon 1960；Singleton 1964 界取等=MDS；e 错+擦除 f 并行纠正与连续突发保证最坏对齐口径同节）。

docstring 逐字引文（防漂移钉）："d_min = n − k + 1（Singleton 恒等式 n−k ≥ d_min−1 取等=MDS）" + "锚：RS(255,223)（GF(256)，NASA/CCSDS 标准码）d=33 → t=16 逐位。"

### 编码增益产生面（硬判 union bound 反解）

（docstring 原文转写）

```latex
P_b\le\frac{1}{n}\sum_{i=t+1}^{n} i\binom{n}{i}p^i(1-p)^{n-i},\quadG=\gamma_b^{\mathrm{unc}}-\gamma_b^{\mathrm{coded}}(P_b{=}target)
```

出处：模块 docstring「编码增益产生面」节（Lin & Costello 2ed / Clark & Cain 1981 硬判 union bound 一阶口径；码率能量扩张后信道原始误码率 p 单源复用 modulation_ber BER 闭式；P_b 对 γ_b 单调降→dB 域二分反解）。

docstring 逐字引文（防漂移钉）："P_b ≤ (1/n)·Σ_{i=t+1}^{n} i·C(n,i)·p^i·(1−p)^(n−i)" + "G = γ_b^uncoded(target) − γ_b^coded(target)"

### KD-1 出处注册（`src/rfauto/core/calc_families/fec_codes.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/fec_codes:<module>:01 | <module> | source | — | - hamming_code_design：R. W. Hamming, Bell Syst. Tech. J. 1950；Lin &；- reed_solomon_capacity：Reed & Solomon 1960；MDS=Singleton 1964 界；2ed / Clark & Cain 1981 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `fec_codes`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- union bound 高估剩余误码→G 为保守下界估计（note+source 双写死）；瀑布区实际增益高于本口径，下界方向恒成立。
  - docstring 逐字引文："**诚实口径**：union bound 高估剩余误码 → G 为真增益的**保守下界估"
- 软判/迭代译码族如实不建模（UNVERIFIED 不凑）；d=1 恒等锚：k=n 退化档截断均值恒等还原二项均值→G≡0（精确到浮点）。
  - docstring 逐字引文："软判/打孔/交织/迭代译码（LDPC/Turbo 瀑布区）不在本面如实"
- 消费链握手：G 语义=码率扩张后信道上的增益——本键双口径显式分列（净增益与回灌面差=码率扩张记账项，防双计）；G 回灌 coded_ber_estimate 闭环复现 target（接线钉，物理量级由独立实现互证另钉）。
  - docstring 逐字引文："modulation_ber.coded_ber_estimate=G 的**消费面**（输入参数，docstring"
- 整数守卫 bool 显式拒收；block_n 上沿 1020（1021–1024 的 i·C(n,i) int→float 转换必 OverflowError，域收缩——W3-S1 审查 P2-1）；t_correct 超 (n−k)/2 必要条件显式拒绝（d_min≥2t+1 与 Singleton 上界联立）；反解端点不可解显式拒绝（同 required_ebn0 口径）。
  - docstring 逐字引文："守卫：parity_bits_m 整数 [2,16]；n_sym/k_sym 整数 0<k<n≤2^m−1；block_n"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/fec_codes.py:hamming_code_design`
- `src/rfauto/core/calc_families/fec_codes.py:reed_solomon_capacity`
- `src/rfauto/core/calc_families/fec_codes.py:coded_ebn0_requirement`

src/rfauto/core/calc_families/fec_codes.py 公开符号 **3** 个（AST 机读）：

`hamming_code_design`、`reed_solomon_capacity`、`coded_ebn0_requirement`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w1s2_link_fec.py`——引文："数值锚（#118 独立来源；锚树 tests/unit/test_w1s2_link_fec.py）"

测试面（tests/unit 引用扫描，机读；合计 **93** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w1s2_link_fec.py` | 24 |
| `tests/unit/test_w4s1_review_guards.py` | 20 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

