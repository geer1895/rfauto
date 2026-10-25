<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：si_ctle

> CTLE 连续时间线性均衡器独立面（aurora_g W4-S4 席，R2 边际池点名件）。

| 字段 | 值 |
|---|---|
| 内核 ID | `si_ctle` |
| 主模块 | `src/rfauto/core/calc_families/si_ctle.py`（`rfauto.core.calc_families.si_ctle`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 1 条（kernel_file=src/rfauto/core/calc_families/si_ctle.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

CTLE 连续时间线性均衡器独立面：1 零 2 极传输函数的 Nyquist 增益/内禀峰值闭式、目标增益反解主极点（独立综合档）、任意频点复增益评估——通用零极点代数，规格档位产生不做（com_pam4 消费面语义防撞）。

模块自述（docstring 首行，机读）：CTLE 连续时间线性均衡器独立面（aurora_g W4-S4 席，R2 边际池点名件）。

## 公式与口径

### CTLE 一阶形态传输函数（1 零 2 极+直流增益）

（docstring 原文转写）

```latex
H(f)=\frac{g(1+jf/f_z)}{(1+jf/f_{p1})(1+jf/f_{p2})}
```

出处：模块 docstring（802.3 COM 的 CTLE 每级拓扑同构，本族按通用零极点代数实现、规格常数不进键面；f_p2 缺省 None=单极档单调升至渐近台无内禀峰）。

docstring 逐字引文（防漂移钉）："H(f) = g·(1 + j·f/f_z) / [(1 + j·f/f_p1)(1 + j·f/f_p2)]" + "|H(f)|² = g²·(1+(f/f_z)²) / [(1+(f/f_p1)²)(1+(f/f_p2)²)]"

### 内禀峰值（|H|² 对 u=f² 求导闭式）

（docstring 原文转写）

```latex
u^*=\sqrt{(p_1^2-z^2)(p_2^2-z^2)}-z^2,\quadf_{peak}=\sqrt{u^*}
```

出处：模块 docstring（驻点方程 u²+2z²u+z²(p1²+p2²)−p1²p2²=0 正根；重极对退化 p1=p2=p → f_peak=√(p²−2z²) 闭式代入档逐位锚）。

docstring 逐字引文（防漂移钉）："u* = √((p1²−z²)(p2²−z²)) − z²，f_peak = √(u*)" + "u* > 0 才有内禀峰（z 深低于 p1 时成立）；u* ≤ 0 → 单调降，峰值=DC。"

### 反解主极点（目标 Nyquist 增益综合档）

（docstring 原文转写）

```latex
f_{p1}=\frac{f}{\sqrt{RHS-1}},\quadRHS=\frac{(1+(f/z)^2)\,g^2}{b^2 K},\ K=1\ \text{或}\ 1+(f/p_2)^2
```

出处：模块 docstring（RHS≤1 → 目标超纯零点增益上限显式拒绝；解得 f_p1<f_z → 低于 boost 域下限显式拒绝；achievability 区间由域盒自然导出）。

docstring 逐字引文（防漂移钉）："1+(f/p1)² = (1+(f/z)²)·g² / (b²·K)，K = 1（单极）或 1+(f/p2)²" + "f_p1 = f / √(RHS − 1)"

### KD-1 出处注册（`src/rfauto/core/calc_families/si_ctle.py`，knowledge/formula_provenance.yaml 过滤）

命中 **1** 条：

| formula_id | symbol | kind | source_doi | refs |
|---|---|---|---|---|
| calc_families/si_ctle:<module>:01 | <module> | source | — | — |

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `si_ctle`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- 域约定：0 < f_z ≤ f_p1 ≤ f_p2（boost CTLE 零在极点前）；f_p2 缺省 None=单极档（增益单调升至渐近台 g·f_p1/f_z，无内禀峰）。
  - docstring 逐字引文："域约定：0 < f_z ≤ f_p1 ≤ f_p2（boost CTLE：零在极点前）；f_p2 缺省"
- 立项判据（#222 triple-grep）：R2 方向 4 判据原文「独立 CTLE 双二阶零极点→Nyquist 峰值增益闭式综合零命中」——R2「数据源薄」风险经口径选择消解：只做传输函数代数与反解，不做 802.3 规格档位产生。
  - docstring 逐字引文："**独立零极点闭式评估/综合键面零**（R2_core_tier4 §② 方向 4 判据原文"
- 边界防撞：com_pam4=COM 规格档位扫描（pychopmarg 数值权威）、si_channel.preemphasis_taps=Tx FFE 时域抽头、gd_equalizer=群时延全通（幅度平坦）、stepped_impedance/coupled_line_bpf=微波滤波器面——本族=Rx CTLE 频域零极点搁架面。
  - docstring 逐字引文："- com_pam4=COM 规格包裹（pychopmarg 数值权威，g_DC 档位扫描——本族不"
- 域盒守卫：f_z>f_p1 违序、非正频率、RHS≤1（目标超上限）、f_p1<f_z（低于 boost 域下限）显式拒绝——越界一律 ValueError。
  - docstring 逐字引文："- 守卫族：f_z>f_p1、非正频率、RHS≤1（超上限）、f_p1<f_z（低于下限）"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/si_ctle.py:ctle_nyquist_gain`
- `src/rfauto/core/calc_families/si_ctle.py:ctle_pole_from_boost`
- `src/rfauto/core/calc_families/si_ctle.py:ctle_gain_at`

src/rfauto/core/calc_families/si_ctle.py 公开符号 **3** 个（AST 机读）：

`ctle_nyquist_gain`、`ctle_pole_from_boost`、`ctle_gain_at`

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
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)、[coupled_line_bpf](coupled_line_bpf.md)、[lange](lange.md)、[stepped_impedance](stepped_impedance.md)、[ring_resonator](ring_resonator.md)、[mixer_conversion](mixer_conversion.md)、[ruthroff_balun](ruthroff_balun.md)、[gd_equalizer](gd_equalizer.md)、[measurement_drift](measurement_drift.md)、[agc_loop](agc_loop.md)、[cal_kit_verify](cal_kit_verify.md)、[six_port](six_port.md)、[iss_on_wafer](iss_on_wafer.md)、[source_power_cal](source_power_cal.md)、[combline](combline.md)、[cps](cps.md)、[interdigital](interdigital.md)、[siw](siw.md)、[slot](slot.md)、[stripline](stripline.md)、[suspended_stripline](suspended_stripline.md)、[dipole](dipole.md)、[helix](helix.md)、[link_limits](link_limits.md)、[fec_codes](fec_codes.md)、[directional_bridge](directional_bridge.md)、[rf_switch](rf_switch.md)、[kuroda_identities](kuroda_identities.md)、[pll_lock_time](pll_lock_time.md)、[multisection_coupler](multisection_coupler.md)、[itu_link](itu_link.md)、[link](link.md)、[dgs](dgs.md)、[if_digitizer](if_digitizer.md)、[wg_dielectric_window](wg_dielectric_window.md)、[waveguide_closed_form](waveguide_closed_form.md)、[waveguide_iris](waveguide_iris.md)、[hybrid_junction](hybrid_junction.md)、[radar_eq](radar_eq.md)、[modulation_ber](modulation_ber.md)、[coax_line](coax_line.md)、[analog_modulation](analog_modulation.md)、[propagation](propagation.md)、[hf_skywave](hf_skywave.md)、[fmcw_radar](fmcw_radar.md)、[sar_geometry](sar_geometry.md)、[gnss_geometry](gnss_geometry.md)、[radar_clutter](radar_clutter.md)、[microstrip_disc](microstrip_disc.md)、[open_wire_line](open_wire_line.md)、[wg_cavity_bpf](wg_cavity_bpf.md)

