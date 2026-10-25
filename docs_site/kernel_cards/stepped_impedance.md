<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：stepped_impedance

> 阶梯阻抗低通滤波器（stepped-impedance LPF）综合内核（aurora_f W1-S3 席域，

| 字段 | 值 |
|---|---|
| 内核 ID | `stepped_impedance` |
| 主模块 | `src/rfauto/core/calc_families/stepped_impedance.py`（`rfauto.core.calc_families.stepped_impedance`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/stepped_impedance.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

阶梯阻抗低通滤波器综合：原型 g_k 阶梯→感性高阻/容性低阻短线电长（fc 等电抗 arctan 设计式）→HJ 逐段线宽/εeff 精算——模板名义值手设留缺的补口，附 ABCD 级联频响与 fc−3dB 回收。

模块自述（docstring 首行，机读）：阶梯阻抗低通滤波器（stepped-impedance LPF）综合内核（aurora_f W1-S3 席域，

## 公式与口径

### 原型 g 值（双源：精确闭式 + 同仓表单源）

（docstring 原文转写）

```latex
g_k=2\sin\frac{(2k-1)\pi}{2N}\ (\text{binomial}),\qquad g^{\mathrm{Cheb}}_k=\text{MYJ Table 4.05-1}
```

出处：模块 docstring「原型 g 值」行（chebyshev 透传同仓 MYJ 表，本面零公式复制 #116；N≤4 奇数=表域+等端接约束）。

docstring 逐字引文（防漂移钉）："binomial（最平坦）：g_k = 2·sin((2k−1)π/(2N))（精确闭式，Pozar 4th ed." + "chebyshev（等纹波）：**单源复用** core/synthesis.chebyshev_lpf_g_values"

### 阶梯实现（Pozar §8.3 fc 等电抗设计式）

（docstring 原文转写）

```latex
\theta_L=\arctan\frac{g_k Z_0}{Z_{\mathrm{high}}},\qquad \theta_C=\arctan\frac{g_k Z_{\mathrm{low}}}{Z_0}
```

出处：模块 docstring「阶梯实现」行（Pozar Example 8.2 设计式口径：N=5 最平坦、fc=2GHz、50Ω、150/10Ω——印刷值未回原文不硬钉，闭式直算锚在测试侧 #122）。

docstring 逐字引文（防漂移钉）："Z_high·tanθ_L = g_k·Z0 → θ_L = arctan(g_k·Z0/Z_high)；并联电容（偶位）" + "tanθ_C = g_k·Z_low/Z0 → θ_C = arctan(g_k·Z_low/Z0)。"

### 物理长（各段自身 εeff 独立精算）

（docstring 原文转写）

```latex
l_i=\frac{\theta_i\,c}{2\pi f_c\sqrt{\varepsilon_{\mathrm{eff},i}}}
```

出处：模块 docstring「物理长」行（skrf HJ 唯一介质口径，铁律 1c；XA-3 迭代序同款——各段按自身线宽 εeff 独立精算）。

docstring 逐字引文（防漂移钉）："l_i = θ_i·λ_g,i/(2π) = θ_i·c/(2π·fc·√εeff_i)，εeff_i 取该段"

### 响应（ABCD 级联+fc−3dB 回收）

（docstring 原文转写）

```latex
|S_{11}|^2+|S_{21}|^2=1,\quad f_{c,3\mathrm{dB}}=\text{首次穿越}(-3\mathrm{dB})\text{线性插值}
```

出处：模块 docstring「响应键」行（离散段化固有偏差如实并列：实测 +6.1%@阻抗比 15、随比单调收敛）。

docstring 逐字引文（防漂移钉）："无耗互易由构造保证（|S11|²+|S21|²=1 残差随值报告）。fc−3dB=自低频段"

### KD-1 出处注册（`src/rfauto/core/calc_families/stepped_impedance.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/stepped_impedance:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `stepped_impedance`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- chebyshev 偶数节与等 Z0 端接实现语义冲突——显式拒绝（binomial 任意 N 放行，g_{N+1}=1 恒成立）。
  - docstring 逐字引文："等端接约束：chebyshev 偶数节原型 g_{N+1}≠1（不等端接），与两端口等"
- 阶梯近似是 Z_high/Z_low→∞ 的渐近等价——βL>π/4 劣化如实记 note 不拦截；带内 vs 集总梯偏差随比单调收敛（实测锚）。
  - docstring 逐字引文："阶梯近似精度随 Z_high/Z_low 比值增大而改善（段长趋短），βL > π/4 时"
- fc 回收偏差是离散段化固有量：+15%/+6.1%/+1.7%/+0.4% @阻抗比 5/15/60/240（本席实测，如实并列不冒充精确）。
  - docstring 逐字引文："fc−3dB=自低频段   首次穿越 −3dB 的插值回收；离散段化固有偏差（arctan 等电抗近似+色散）"
- 族界：lc/mask=集总与规格级、matching.synthesize_commensurate_line=Richards 全 λ/4 变换（同名阶梯异域）、stepped_impedance 模板=实现级渲染通道——本族=综合两键。
  - docstring 逐字引文："lc_filter/mask_filter=集总/规格级、synthesize_commensurate_line（core/"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/stepped_impedance.py:stepped_impedance_lpf_synthesize`
- `src/rfauto/core/calc_families/stepped_impedance.py:stepped_impedance_response`

src/rfauto/core/calc_families/stepped_impedance.py 公开符号 **2** 个（AST 机读）：

`stepped_impedance_lpf_synthesize`、`stepped_impedance_response`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w1s3_lange_stepped.py`——引文："口径参照：N=5 最平坦、fc=2GHz、50Ω、Z_high=150Ω、"

测试面（tests/unit 引用扫描，机读；合计 **60** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w1s3_lange_stepped.py` | 11 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

