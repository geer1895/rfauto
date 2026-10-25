<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：ruthroff_balun

> Ruthroff 传输线巴伦/不等阻抗变换器族（aurora_f W2-S7 立项；aurora_f

| 字段 | 值 |
|---|---|
| 内核 ID | `ruthroff_balun` |
| 主模块 | `src/rfauto/core/calc_families/ruthroff_balun.py`（`rfauto.core.calc_families.ruthroff_balun`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/ruthroff_balun.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

Ruthroff 直通+延迟求和传输线巴伦：单磁芯 n²:1 阻抗比设计（每线最优 Z0=√(r_in·r_out) 一阶带宽定理、电短线设计口径=匹配带缘 |S11|≤0.1 判据）与 4 端子差分导纳精确解（W7-S25 P1-1 物理修正体）——guanella_tlt 拒绝注记指向的等延迟族缺口补全。

模块自述（docstring 首行，机读）：Ruthroff 传输线巴伦/不等阻抗变换器族（aurora_f W2-S7 立项；aurora_f

## 公式与口径

### Z_in 闭式与低电长区匹配（Ranzani 式(3) 锚）

（docstring 原文转写）

```latex
Z_{in}(\theta)=Z_0\,\frac{2\rho(1+\cos\theta)+j\sin\theta}{\cos\theta+j\rho\sin\theta},\ \rho=\tfrac{R_{out}}{Z_0};\quad Z_{in}(\theta\to 0)=4R_{out}
```

出处：模块 docstring「闭式恒等式」节（W7-S25 P1-1 修正后重导；等价半角形式 (4R_out+2jZ0·tan(θ/2))/(1−tan²(θ/2)+2jρ·tan(θ/2))；θ=π 处 Z_in→0 传输零点）。

docstring 逐字引文（防漂移钉）："Z_in(θ) = Z0·[2ρ(1+cosθ) + j·sinθ]/[cosθ + jρ·sinθ]（高阻口视入阻抗" + "低电长匹配锚：θ→0 处 Z_in→4R_out=R_in（Ranzani 式(3) 低频极限"

### 变换增益闭式与 θ=π 传输零点

（docstring 原文转写）

```latex
G(\theta)=\frac{16\rho^2(1+\cos\theta)^2}{(1+4\rho^2)^2\sin^2\theta+4\rho^2(1+3\cos\theta)^2},\quad G\to 1\ (\theta\to 0),\ G\to 0\ (\theta\to\pi)
```

出处：模块 docstring「闭式恒等式」节（θ=π 零点=NIST Ranzani 2012 "the transformation ratio goes to zero" 实证口径；G 关于 θ 单调下降——旧 θ↔π−θ 单峰对称系错误模型产物已废）。

docstring 逐字引文（防漂移钉）："G(θ)=|S21|² = 16ρ²(1+cosθ)²/[(1+4ρ²)²·sin²θ+4ρ²(1+3cosθ)²]；" + "θ=π 传输零点：Z_in→0、G→0（NIST 文"

### 最优 Z0 一阶带宽定理与匹配带缘判据（设计口径）

（docstring 原文转写）

```latex
Z_0=\sqrt{R_{in}R_{out}}=2R_{out}\ (4{:}1),\quad Z_{in}\approx 4R_{out}+R_{out}\theta^2+jZ_0\theta(1-4\rho^2);\quad |S_{11}|^2=\frac{(1-\cos\theta)^2}{(1+3\cos\theta)^2+4\sin^2\theta}
```

出处：模块 docstring「闭式恒等式」「设计口径」节（ρ=1/2 唯一消去 O(θ) 虚部=匹配带一阶最优；带缘判据 |S11|≤0.1 精确二次根 (1−5γ²)u²+16γ²u−16γ²=0 → θ_bd≈48.30° 定 l_max；θ=90° 非匹配反向锚 |S11|=√0.2——旧「λ/4 匹配点」口径已弃用）。

docstring 逐字引文（防漂移钉）："最优 Z0=√(R_in·R_out)=2R_out（ρ=1/2）**一阶带宽定理**：小电长展开" + "ρ=1/2 档 |S11|² = (1−cosθ)²/[(1+3cosθ)² + 4sin²θ]；"

### 4 端子差分盖章与不等参考标度（W7-S25 修正体）

（docstring 原文转写）

```latex
Y_{self}=-j\cot\theta/Z_0,\ Y_{mut}=j\csc\theta/Z_0;\quad \mathbf Y_{2p}=\begin{bmatrix}Y_s&Y_m-Y_s\\Y_m-Y_s&2(Y_s-Y_m)\end{bmatrix};\quad \mathbf S=(\mathbf I-\mathbf DY\mathbf D)(\mathbf I+\mathbf DY\mathbf D)^{-1}
```

出处：模块 docstring「盖章」节（Yd=Ys−Ym=−j·cot(θ/2)/Z0 半角项=互耦机构本体；旧 [[Ys,Ym],[Ym,2Ys]] 无互耦已废；锚树 KCL/congruence 真双路线互证）。

docstring 逐字引文（防漂移钉）："Y₂ₚ=[[Ys, Ym−Ys],[Ym−Ys, 2(Ys−Ym)]]，" + "S=(I−D·Y·D)(I+D·Y·D)⁻¹、D=diag(√R_in,√R_out)（guanella"

### KD-1 出处注册（`src/rfauto/core/calc_families/ruthroff_balun.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/ruthroff_balun:<module>:01 | <module> | source | — | 出处（NIST Ranzani et al. IEEE Trans. Appl. Supercond. 22(5) 2012；不平衡变换器盖章模型（Ranzani 2012 Fig.1 无电容 C 口径；式(3) 低频 |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `ruthroff_balun`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 纯差分 TL 模型在模型内低频保持 4:1（θ→0 精确匹配，Ranzani 式(3)）；真实器件低频拐角由有限磁化电感承载——无磁芯数据不虚构频响（UNVERIFIED 如实登记）。
  - docstring 逐字引文："低频磁化电感拐角依赖磁芯 L_m 数据，本族**不冒充**"
- 9:1=四线双对 NIST 扩展口径（设计键 n∈{2,3}）；频响键 n=2 单对精确解——9:1 双对复合不在解析口径如实拒绝。
  - docstring 逐字引文："≥16:1 复合拓扑无权威"
- 族界：guanella_tlt=等比族（比值随线数 n² 增长）、Marchand=模板级双槽臂、quarter_wave/taper=单线匹配、t_match/rf_match=集总——均非直通+延迟求和拓扑不并入。
  - docstring 逐字引文："**Ruthroff 等延迟族**（单磁芯单线对，输出电压=直通电压+延迟电压相量和"
- θ=kπ（含 f→0）线 Y 参量 cscθ 奇异显式拒绝；数值 0.0 合法（判缺失 is not None，#364④）。
  - docstring 逐字引文："线 Y 参量奇异显式拒绝（扫频域避开）"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/ruthroff_balun.py:ruthroff_balun_design`
- `src/rfauto/core/calc_families/ruthroff_balun.py:ruthroff_balun_response`

src/rfauto/core/calc_families/ruthroff_balun.py 公开符号 **2** 个（AST 机读）：

`ruthroff_balun_design`、`ruthroff_balun_response`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_w2s7_ruthroff_gd_drift.py`——引文："tests/unit/test_w2s7_ruthroff_gd_drift.py"

测试面（tests/unit 引用扫描，机读；合计 **77** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_calculators.py` | 49 |
| `tests/unit/test_w2s7_ruthroff_gd_drift.py` | 28 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[si_ctle](si_ctle.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

