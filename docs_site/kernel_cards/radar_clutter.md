<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：radar_clutter

> 雷达杂波与 MTI 滤波族（aurora_g W6-S3 席立族，R3_domain_expansion 视角4

| 字段 | 值 |
|---|---|
| 内核 ID | `radar_clutter` |
| 主模块 | `src/rfauto/core/calc_families/radar_clutter.py`（`rfauto.core.calc_families.radar_clutter`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/radar_clutter.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

雷达杂波环境与 MTI 滤波五键：双脉冲对消器频响+盲速、Gaussian 杂波谱改善因子（闭式+数值积分双路径）、面杂波 σ0 常数/γ 双档+杂波单元 RCS、Weibull 杂波幅度分布参数化与 CA-CFAR 滑窗检测链——雷达场景第五件（方程/起伏/RCS/波形指标之后的杂波面）。

模块自述（docstring 首行，机读）：雷达杂波与 MTI 滤波族（aurora_g W6-S3 席立族，R3_domain_expansion 视角4

## 公式与口径

### 双脉冲对消器频响与盲速

（docstring 原文转写）

```latex
|H(f)|=2\left|\sin(\pi f T_r)\right|,\quad v_n=\frac{n\lambda\,\mathrm{PRF}}{2}
```

出处：Skolnik IRS ch.15 MTI/Richards FRSP ch.2 教科书口径；凹口 f=k·PRF 逐位、峰值 |H|=2 于 f=(k+1/2)·PRF 逐位、周期恒等 H(f+PRF)=H(f)。

docstring 逐字引文（防漂移钉）："H(f) = 1 − e^{−j2πfTr} = 2j·sin(πfTr)·e^{−jπfTr}" + "v_n = f_D·λ/2 = n·λ/(2Tr) = n·λ·PRF/2（多普勒"

### Gaussian 杂波谱改善因子

（docstring 原文转写）

```latex
P_{out}=2P_c(1-\rho),\quad \rho=e^{-2\pi^2\sigma_f^2T_r^2},\quad I=\frac{1}{1-\rho}
```

出处：Skolnik MTI 章口径；本键同文件数值积分独立复算 P_out（#118 双路径：闭式 vs 复化梯形积分）；SCV=I−所需输出 SCNR（Richards 口径）。

docstring 逐字引文（防漂移钉）："P_out = ∫|H(f)|²·S(f)df = 2·P_c·(1−ρ)，  ρ = exp(−2π²·σ_f²·Tr²)" + "⇒ **I = 1/(1−ρ)**"

### 面杂波 σ0 双档与杂波单元 RCS

（docstring 原文转写）

```latex
\sigma^0=\gamma\sin\psi,\quad A_c=R\,\rho_R\,\theta_{az}\sec\psi,\quad \sigma_c=\sigma^0A_c
```

出处：constant-γ 低角地杂波通用模型（ψ→0⁺ ⇒ σ0→0、ψ=90° ⇒ σ0=γ 逐位）；杂波 RCS 恒等式 σc=σ0·Ac。

docstring 逐字引文（防漂移钉）："σ0 = γ·sin(ψ)（Skolnik/Richards/Nathanson 通用" + "Ac = R·ρ_R·θ_az·sec(ψ)（Greco 讲义 slide 7"

### Weibull 杂波幅度分布（2 参参数化）

（docstring 原文转写）

```latex
f(x)=\frac{k}{\lambda}\left(\frac{x}{\lambda}\right)^{k-1}e^{-(x/\lambda)^k},\quad \mathrm{mean}=\lambda\,\Gamma(1+1/k)
```

出处：Fay-Clarke-Peters 1977 海杂波 Weibull 首提+Skolnik/Richards 教科书口径；k=1 退化指数、k=2 退化 Rayleigh 逐位锚。

docstring 逐字引文（防漂移钉）："f(x) = (k/λ)·(x/λ)^{k−1}·exp(−(x/λ)^k)，  F(x) = 1−exp(−(x/λ)^k)" + "mean=λ·Γ(1+1/k)、var=λ²·[Γ(1+2/k)−Γ²(1+1/k)]；"

### CA-CFAR 滑窗门限（参考窗+保护带）

（docstring 原文转写）

```latex
T=\alpha\,\mathrm{mean}(Z)=\beta\Sigma Z,\quad \beta=\mathrm{Pfa}^{-1/N}-1,\quad \alpha=N\beta
```

出处：Richards FRSP 2ed ch.6 指数噪声单元标准结果；与 radar_eq.ca_cfar_threshold 同式双源（#118 同仓双锚：彼键=纯因子/Pd 闭式、本键=实测窗+保护带几何+判决链）。

docstring 逐字引文（防漂移钉）："T = α·mean(Z) = β·ΣZ，  β = Pfa^{−1/N} − 1，  α = N·β"

### KD-1 出处注册（`src/rfauto/core/calc_families/radar_clutter.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/radar_clutter:<module>:01 | <module> | source | — | Weibull 杂波模型=Fay-Clarke-Peters 1977（海杂波 Weibull 首提）+Skolnik/ |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `radar_clutter`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 改善因子闭式与数值积分双路径互证（非同一公式的两次抄写）。
  - docstring 逐字引文："本键同文件数值积分独立复算 P_out（#118 双路径：闭式 vs 复化梯形积分，"
- GIT 海杂波档缺席如实声明（多区域插值系数表原表不可达，#122 不凑）；本键不做表插值——表数字化属数据面。
  - docstring 逐字引文："（Greco 讲义只给结构不给逐字系数表）——按 finline"
- core/aging、core/probability_paper、alt_planning 的 Weibull=可靠性寿命/作图回归域（同名异域不撞）。
  - docstring 逐字引文："本键只做杂波幅度统计参数化。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/radar_clutter.py:mti_frequency_response`
- `src/rfauto/core/calc_families/radar_clutter.py:mti_improvement_factor`
- `src/rfauto/core/calc_families/radar_clutter.py:clutter_sigma0_model`
- `src/rfauto/core/calc_families/radar_clutter.py:weibull_clutter_model`
- `src/rfauto/core/calc_families/radar_clutter.py:cell_averaging_cfar`

src/rfauto/core/calc_families/radar_clutter.py 公开符号 **5** 个（AST 机读）：

`mti_frequency_response`、`mti_improvement_factor`、`clutter_sigma0_model`、`weibull_clutter_model`、`cell_averaging_cfar`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w6s3_core_domains.py`——引文："雷达杂波与 MTI 滤波族（aurora_g W6-S3 席立族，R3_domain_expansion 视角4"

测试面（tests/unit 引用扫描，机读；合计 **88** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w6s3_core_domains.py` | 21 |
| `tests/unit/test_w9s2_core_domains.py` | 18 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

