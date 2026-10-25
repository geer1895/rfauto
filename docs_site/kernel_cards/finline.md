<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：finline

> 鳍线渐变过渡族两键（aurora_e W2-S9，K2 残差面，2026-10-18）。

| 字段 | 值 |
|---|---|
| 内核 ID | `finline` |
| 主模块 | `src/rfauto/core/calc_families/finline.py`（`rfauto.core.calc_families.finline`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/finline.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

鳍线渐变过渡（波导内 E 面结构）：TE10 导波 β 口径（声明近似档）+ 小反射剖面反射闭式（指数 sinc/线性 Ei，与 taper_classic 单源共享）——基模等效经验档因系数原文不可达如实放弃。

模块自述（docstring 首行，机读）：鳍线渐变过渡族两键（aurora_e W2-S9，K2 残差面，2026-10-18）。

## 公式与口径

### 导波相位常数（TE10 截止口径，声明近似档）

（docstring 原文转写）

```latex
\beta=k_0\sqrt{\varepsilon_{\mathrm{eff}}}\,\sqrt{1-\bigl(f_{c10}/f\bigr)^2},\qquad f_{c10}=\frac{c_0}{2a}
```

出处：模块 docstring「物理口径」节（empirical 级近似如实声明；εeff 缺省 1.0=未加载 TE10 导波口径，调用方可传精化）。

docstring 逐字引文（防漂移钉）："β = k0·sqrt(εeff)·" + "sqrt(1−(fc10/f)²)，fc10 = c0/(2a)（TE10 截止恒等式，与 core/rwg_mmt"

### 小反射剖面反射闭式（精确，共享单源）

（docstring 原文转写）

```latex
\Gamma=\frac{1}{2}\int\frac{d(\ln Z)}{dx}\,e^{-2j\beta x}\,dx
```

出处：模块 docstring；_gamma_closed/_gamma_quadrature 经 taper_classic 单源复用不复制公式（闭式 vs 剖面核数值积分双路线残差 1e-15 量级）。

docstring 逐字引文（防漂移钉）："Γ = ∫½·d(lnZ)/dx·e^(−2jβx)dx（Pozar 4th ed §5.9）——指数剖面 sinc 闭"

### KD-1 出处注册（`src/rfauto/core/calc_families/finline.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/finline:<module>:01 | <module> | source | — | 文献引用与图例（OUADI 2007 MoL 全波、Yassin 2008 过渡设计），系数原文 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `finline`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 近截止病态带显式拒绝——与 rwg_mmt 近截止降级同哲学。
  - docstring 逐字引文："f/fc10 < 1.05 显式拒绝（截止附近 β→0、λg 发散，bethe_hole_coupler 同"
- Meier 1974/Sharma-Hoefer 1983 基模等效档未落地——系数原文非公开可达，留待拿到原文系数表再立键。
  - docstring 逐字引文："非公开可达——硬编码记忆系数即伪造（#122 如实原则），该档如实放弃，"
- epsilon_eff 精化参数是半经验输入，不是闭式输出——性质显式声明。
  - docstring 逐字引文："——该参数属半经验输入，empirical 性质如实声明。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/finline.py:finline_taper_response`
- `src/rfauto/core/calc_families/finline.py:finline_taper_length`

src/rfauto/core/calc_families/finline.py 公开符号 **2** 个（AST 机读）：

`finline_taper_response`、`finline_taper_length`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `src/rfauto/core/calc_families/taper_classic.py`——引文："式 / 线性剖面 Ei 指数积分闭式，经 core/calc_families/taper_classic 的"

测试面（tests/unit 引用扫描，机读；合计 **72** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_aurora_e_s9_finline.py` | 23 |
| `tests/unit/test_calculators.py` | 49 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

