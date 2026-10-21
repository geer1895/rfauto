<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：modulation_ber

> 数字调制理论 BER/Eb-N0 族（架构批 W4-A 席，R2 空白域 G3）。

| 字段 | 值 |
|---|---|
| 内核 ID | `modulation_ber` |
| 主模块 | `src/rfauto/core/calc_families/modulation_ber.py`（`rfauto.core.calc_families.modulation_ber`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/modulation_ber.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

数字调制理论误码率面：BPSK/QPSK 闭式与 square M-QAM 精确和式、目标 BER→所需 Eb/N0 单调二分反解、级联编码一阶粗估——通信链「调制→编码」数字面与 fec_codes 编码增益产生面互为消费。

模块自述（docstring 首行，机读）：数字调制理论 BER/Eb-N0 族（架构批 W4-A 席，R2 空白域 G3）。

## 公式与口径

### BPSK/QPSK 相干解调 BER（Gray 映射、比特能量口径）

（docstring 原文转写）

```latex
P_b=Q\!\left(\sqrt{2\gamma_b}\right)
```

出处：模块 docstring（相干 AWGN；QPSK≡BPSK 物理恒等——Es/N0=2·Eb/N0，全 γ 扫描逐位测试钉；Q 函数单源 _qfunc 全族唯一实现）。

docstring 逐字引文（防漂移钉）："Pb = Q(√(2·γb))" + "QPSK 与 BPSK 在同比特能量口径下 BER 逐位相等（QPSK 每支路即 BPSK、"

### square M-QAM 精确和式（M=16/64）

（docstring 原文转写）

```latex
P_b=\frac{4(1-1/\sqrt{M})}{k}\sum_{i=1}^{\sqrt{M}/2}Q\!\left((2i-1)\sqrt{\tfrac{3k\gamma_b}{M-1}}\right),\quad k=\log_2 M
```

出处：模块 docstring（Proakis 5ed QAM 节/Cho & Kim IEEE Comm. Lett. 2005 同形逐项式；M=4 退化回 BPSK 闭式）。

docstring 逐字引文（防漂移钉）："Pb = 4(1−1/√M)/k · Σ_{i=1}^{√M/2} Q((2i−1)·√(3k·γb/(M−1)))，" + "（Proakis, *Digital Communications* 5th ed. QAM 节；Cho & Kim,"

### 级联编码一阶粗估（码率扩张+固定净增益偏移）

（docstring 原文转写）

```latex
\gamma_{b,\mathrm{eff}}=\gamma_b+10\lg R_c+G_{\mathrm{coding}}\ \Rightarrow\ P_b=\mathrm{BER}_{\mathrm{theory}}(\gamma_{b,\mathrm{eff}})
```

出处：模块 docstring（一阶粗估口径 docstring 与输出 note 双写死；G_coding 输入由 fec_codes 编码增益族产生——同仓消费链 #122 不冒充精确）。

docstring 逐字引文（防漂移钉）："γb_eff = γb + 10·lg(R_c) + G_coding    →  Pb = BER_theory(γb_eff)" + "不建模打孔/交织/迭代译码瀑布区（G_coding 必须取目标 BER 点的净"

### KD-1 出处注册（`src/rfauto/core/calc_families/modulation_ber.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/modulation_ber:<module>:01 | <module> | source | — | Cho & Kim, IEEE Comm. Lett. 2005 square-QAM 同形逐项式 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `modulation_ber`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- Q 函数单源纪律：全族唯一实现 _qfunc=0.5·erfc(x/√2)，禁止第二份 erfc/Q 形态（双实现漂移防线）。
  - docstring 逐字引文："- Q 函数单源：Q(x) = 0.5·erfc(x/√2)（本模块 _qfunc，全族唯一实现，"
- 反解口径：单调性成立（Q 单调+正系数和式），dB 域二分 200 轮（区间收敛 ~1e-60，纯 math 零依赖，同 bethe_hole 反解惯例）。
  - docstring 逐字引文："反解：γb→Pb 在域内严格单调降（Q 单调 + 正系数和式），dB 域二分"
- 数值域界：双精度 BER 有效下限 1e-15（erfc 深尾下溢地板之上），target_ber 低于此显式拒绝；target_ber>0.1 给 low_confidence 标注不拒绝（#122 如实三分）。
  - docstring 逐字引文："双精度下 BER 有效下限 1e-15（erfc 深尾下溢地板之上），target_ber"
- 域盒守卫：ebn0_db 有限（标量/列表逐点）、target_ber∈[1e-15, 0.5)、scheme 未知名显式拒绝、code_rate∈(0,1]、coding_gain_db 有限——越界一律 ValueError。
  - docstring 逐字引文："守卫：ebn0_db 必须有限（标量或非空列表逐点校验）；target_ber ∈"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/modulation_ber.py:modulation_ber_curve`
- `src/rfauto/core/calc_families/modulation_ber.py:required_ebn0`
- `src/rfauto/core/calc_families/modulation_ber.py:coded_ber_estimate`

src/rfauto/core/calc_families/modulation_ber.py 公开符号 **3** 个（AST 机读）：

`modulation_ber_curve`、`required_ebn0`、`coded_ber_estimate`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w4a_mod_radar.py`——引文："数值锚（#118 独立来源；锚树 tests/unit/test_w4a_mod_radar.py）"

测试面（tests/unit 引用扫描，机读；合计 **138** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_ui_tools_page.py` | 41 |
| `tests/unit/test_w1s2_link_fec.py` | 24 |
| `tests/unit/test_w4a_mod_radar.py` | 24 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

