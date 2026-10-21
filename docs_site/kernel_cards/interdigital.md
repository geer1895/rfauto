<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：interdigital

> 交指/梳状杆滤波器实现族（interdigital/combline bars，aurora72 A3-C 席

| 字段 | 值 |
|---|---|
| 内核 ID | `interdigital` |
| 主模块 | `src/rfauto/core/calc_families/interdigital_bpf.py`（`rfauto.core.calc_families.interdigital_bpf`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/interdigital_bpf.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

交指/梳状杆滤波器实现族：零厚度耦合杆条带线偶/奇模电容共形映射精确闭式、Getsinger 等效网络综合（g 值→倒置器→逐节电容目标→杆宽缝反解→四分之一波长杆长）与 combline 耦合缝半边（归一化耦合↔缝宽闭环、装载斜率双档）——与 combline_resonator 谐振器级键面语义互补不重复。

模块自述（docstring 首行，机读）：交指/梳状杆滤波器实现族（interdigital/combline bars，aurora72 A3-C 席

## 公式与口径

### 零厚度耦合杆条带线共形映射（偶/奇模）

（docstring 原文转写）

```latex
k_e=\tanh x\,\tanh y,\quad k_o=\frac{\tanh x}{\tanh y},\quad Z_{0m}=\frac{30\pi}{\sqrt{\varepsilon_r}\,r_m},\quad r_m=\frac{K(k_m)}{K'(k_m)}=\frac{\mathrm{AGM}(1,k_m)}{\mathrm{AGM}(1,k_m')}
```

出处：模块 docstring「物理口径」节（Getsinger IRE Trans. MTT-10(1) 1962 薄条极限；Gupta 耦合带状线同式；k' 平方根消相消稳定形与 AGM 恒等式，s→∞/s→0 双极限锚跨键钉）。

docstring 逐字引文（防漂移钉）："k_e = tanh(x)·tanh(y)，  k_e' = sqrt(cosh²y + sinh²x)/(cosh x·cosh y)" + "Z0m = 30π/(√εr·r_m)，r_m = K(k_m)/K'(k_m) = AGM(1,k_m)/AGM(1,k_m')"

### 倒置器与耦合系数（TEM 恒等）

（docstring 原文转写）

```latex
J_{m,m+1}=\frac{v}{2}\,(C_o-C_e),\quad k_{\mathrm{phys}}=\frac{C_o-C_e}{C_o+C_e}\equiv\frac{Z_{0e}-Z_{0o}}{Z_{0e}+Z_{0o}}
```

出处：模块 docstring（Getsinger 等效网络，MYJ ch.10 口径；电容口径与阻抗口径恒等逐位测试钉）。

docstring 逐字引文（防漂移钉）："J_m,m+1 = v·(C_o − C_e)/2   [S]（v=c₀/√εr）" + "k_phys = (C_o − C_e)/(C_o + C_e) ≡ (Z0e − Z0o)/(Z0e + Z0o)（TEM 恒等）"

### 逐节电容目标（几何均值约束，闭式精确）

（docstring 原文转写）

```latex
C_{e,o}=\frac{\sqrt{\Delta C^2+4C_0^2}\mp\Delta C}{2},\quad \Delta C=\frac{2J}{v},\quad C_0=\frac{1}{v Z_r}
```

出处：模块 docstring（几何均值约束 sqrt(C_e·C_o)=1/(v·Z_r) ⇔ Z0e·Z0o=Z_r²；(C_e,C_o)→(w,s) 嵌套 brentq 二维反解，杆长=λ/4@√εr 均匀介质 TEM 精确）。

docstring 逐字引文（防漂移钉）："C_e,o = (√(ΔC² + 4C_0²) ∓ ΔC)/2，ΔC = 2J/v，C_0 = 1/(v·Z_r)"

### combline 半边（k↔缝闭环与装载斜率双档）

（docstring 原文转写）

```latex
J_{ij}=b_s k_{ij},\quad b_s=\frac{\cot\theta_0+\theta_0\csc^2\theta_0}{2 Z_r},\quad \theta_0=\arctan\frac{1}{\omega_0 C Z_r}
```

出处：模块 docstring「combline 半边」节（装载斜率为本仓 MYJ ch.8 等效电路第一性推导，实现前独立复算在档；θ₀→90° 退化=空载档恒等锚树钉、与 combline_resonance 跨键同解）。

docstring 逐字引文（防漂移钉）："J_ij = b_s·k_ij（窄带倒置器-耦合关系，MYJ ch.8/10）" + "b_s = [cotθ₀ + θ₀·csc²θ₀]/(2·Z_r)，  θ₀=arctan(1/(ω₀C·Z_r))"

### KD-1 出处注册（`src/rfauto/core/calc_families/interdigital_bpf.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/interdigital_bpf:<module>:01 | <module> | source | — | 出处（剖面电容：Getsinger, IRE Trans. MTT-10(1) 1962 薄条极限—— |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `interdigital`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 零厚度极限档：有限杆厚/端电容修正不在 v1 口径，如实注记不做。
  - docstring 逐字引文："有限杆厚/端电容（Getsinger 有限厚度修正）不在 v1 口径（零厚度极限，如实"
- 缝反解越域（极强耦合达缝下限/极弱耦合越上限）显式拒绝，附节序号与残差——不静默夹持。
  - docstring 逐字引文："限 / 极弱耦合越上限）显式拒绝（附节序号与残差）"
- 弱耦合上限=数值饱和阈（超界等价无穷远）显式拒绝——饱和域不是物理无穷远（#334 同族纪律）。
  - docstring 逐字引文："s 上限 12b（tanh 饱和阈 y=πs/2b≲19，#334 同族——超界=数值上等价无"
- 装载斜率双档互斥语义：给装载电容与频率成对参数走 combline 装载档，否则空载档——单给显式拒绝。
  - docstring 逐字引文："cap_ff/f0_ghz 成对给（单给显式拒绝）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/interdigital_bpf.py:interdigital_bars_capacitance`
- `src/rfauto/core/calc_families/interdigital_bpf.py:interdigital_bpf_synthesize`
- `src/rfauto/core/calc_families/interdigital_bpf.py:combline_coupling_gap`

src/rfauto/core/calc_families/interdigital_bpf.py 公开符号 **3** 个（AST 机读）：

`interdigital_bars_capacitance`、`interdigital_bpf_synthesize`、`combline_coupling_gap`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_a3c_coupled_interdigital.py`——引文："锚树 tests/unit/test_a3c_coupled_interdigital.py 与"
- `tests/unit/test_aurora_d_core7.py`——引文："tests/unit/test_aurora_d_core7.py）。"
- `内部证据目录`（仓内档，公开分发视图不随附，存在性不作测试断言）——引文："前独立复算：k roundtrip ≤1e-15、k↔J 代数互逆恒等式、跨键结构锚（同参"

测试面（tests/unit 引用扫描，机读；合计 **91** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a3c_coupled_interdigital.py` | 20 |
| `tests/unit/test_aurora_d_core7.py` | 22 |
| `tests/unit/test_calculators.py` | 49 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

