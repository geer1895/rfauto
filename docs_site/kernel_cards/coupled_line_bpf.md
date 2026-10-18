<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格 XA-8）。
     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 docstring/AST；
     公式 LaTeX 与使用边界为人工转写段，每条带 docstring 逐字引文钉。
     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，
     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->

# 内核文档卡：coupled_line_bpf

> 平行耦合线带通滤波器（coupled-line BPF）综合族（aurora72 A3-C 席域 1，

| 字段 | 值 |
|---|---|
| 内核 ID | `coupled_line_bpf` |
| 主模块 | `src/rfauto/core/calc_families/coupled_line_bpf.py`（`rfauto.core.calc_families.coupled_line_bpf`） |
| 计算器注册表 | 已注册 @register_calculator |
| KD-1 出处注册 | 0 条（kernel_file=src/rfauto/core/calc_families/coupled_line_bpf.py） |
| XC-P 精度档案 | 见下方「精度域」节（机读判定） |
| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |

## 物理语义

平行耦合线带通滤波器实现族：全极点切比雪夫 g 值→J 倒置器→逐节 (Z0e,Z0o)→KJ 二维反解微带 (w,s)——耦合矩阵级（C13）之下的器件实现尺寸级，Pozar Example 8.7 阻抗表逐位锚。

模块自述（docstring 首行，机读）：平行耦合线带通滤波器（coupled-line BPF）综合族（aurora72 A3-C 席域 1，

## 公式与口径

### J 倒置器（Pozar §8.6，MYJ ch.8 同源）

（docstring 原文转写）

```latex
x_{01}=\sqrt{\frac{\pi\delta}{2g_0g_1}},\quad x_j=\frac{\pi\delta/2}{\sqrt{g_jg_{j+1}}},\quad x_n=\sqrt{\frac{\pi\delta}{2g_ng_{n+1}}}
```

出处：模块 docstring「物理口径」节（g 值走 core/matching.chebyshev_g_values，Pozar 表 8.4 递推）。

docstring 逐字引文（防漂移钉）："x_01 = J_01/Z0 = sqrt(π·δ/(2·g_0·g_1))          （端节）" + "x_j  = J_j,j+1/Z0 = (π·δ/2)/sqrt(g_j·g_{j+1})   （内节，j=1..n−1）"

### 逐节奇偶模阻抗（Pozar 式 8.13x 精确形）

（docstring 原文转写）

```latex
Z_{0e}=Z_0(1+x+x^2),\qquad Z_{0o}=Z_0(1-x+x^2)
```

出处：模块 docstring（反解恒等式 x=(Z0e−Z0o)/(2Z0) 测试钉；同步 TEM 极限下中心频率精确）。

docstring 逐字引文（防漂移钉）："Z0e = Z0·(1 + x + x²)，  Z0o = Z0·(1 − x + x²)"

### 段长/谐振器长（KJ 正向回代+开路端修正）

（docstring 原文转写）

```latex
L=\frac{\lambda_0}{4}\sqrt{\frac{2}{\varepsilon_e+\varepsilon_o}},\quad L_{\mathrm{res}}=\lambda_g/2-2\Delta l
```

出处：模块 docstring（(Z0e,Z0o)→(w,s) 稳健二维数值反解，正向=coupled_microstrip_even_odd_ohm KJ 1984 闭式）。

docstring 逐字引文（防漂移钉）："正向回代出 εeff_e/εeff_o → 段长 = λ0/4·sqrt(2/(εe+εo))；谐振器 =" + "λg/2（两邻段平均 εeff）− 2×Δl（Hammerstad 开路端修正，core"

### 频响（偶/奇模叠加 4 端口+交叉口压缩）

（口径示意（非 docstring 原式，读代码为准））

```latex
S^{(4\square)}=\tfrac{1}{2}(S^e+S^o)\xrightarrow{\Gamma=+1}S^{(2\square)}\xrightarrow{\mathrm{ABCD}}S
```

出处：模块 docstring「频响键口径」节（交叉口 Γ=+1 开路端接压缩2 端口，S→ABCD 按 Pozar Table 4.2）。

docstring 逐字引文（防漂移钉）："每节 = 偶/奇模各自 2 端口线 S 叠加构造 4 端口 S（构造恒满足无耗/互易），"

### KD-1 出处注册（`src/rfauto/core/calc_families/coupled_line_bpf.py`，knowledge/formula_provenance.yaml 过滤）

命中 **0 条**——该模块 docstring 无「出处见/出处（」收集标记命中或未逐式登记。出处以模块 docstring 为单源（上方公式引文即逐字出自 docstring）；登记缺口如实呈现，属 XA-6 出处断链巡检门的巡检范围，不在本卡掩饰。

## 精度域（XC-P 精度档案）

**未收录**：XC-P 首批建档内核共 **10** 个（bounds、conductor_loss、coupled_microstrip、dielectric_extract、etch_trapezoid、high_power、ridged_waveguide、shield_cavity_mode、synthesis.forward_z0、thermal_iteration），不含 `coupled_line_bpf`。因此：

- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何精度数字——铁律 7 / #122 如实标注）；
- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级（收集器=`tests/unit/test_precision_profiles.py` 逐条对照防漂移）；
- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ `KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + 重跑本生成器。

> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；本内核建档后此节自动展开为分档表（渲染支路已备）。

## 使用边界

- Pozar Example 8.7（p.435 4th ed）文献例逐位复现锚（εr/h 无关）；g 值 vs 教科书表 1.5963/1.0967。
  - docstring 逐字引文："f0=2 GHz、δ=10%、Z0=50 → (Z0e,Z0o) = (70.61,39.24)/(56.64,44.77)/"
- 倒置器 λ/4 实现的二阶修正是带内偏差来源——如实锚定 ~0.28dB。
  - docstring 逐字引文："（带缘倒置器频率依赖的二阶偏差，实测 ~0.28 dB）；带心 |S21|=0 dB、带内"
- 规格域守卫族；KJ 反解越域（极宽/极窄带不可实现）显式拒绝并附节序号。
  - docstring 逐字引文："order 为 ≥2 整数；0<fbw≤1；ripple_db>0；z0_ohm>0；epsilon_r≥1；"
- 族界：C13=耦合矩阵级（无物理尺寸）、模板渲染级=KJ 反解链绑定渲染管线——本族=core 注册键面的器件实现尺寸级（无 TZ、无折叠/箭头拓扑）。
  - docstring 逐字引文："（Mathaei-Pollard-Feit ch.8 / Pozar §8.6.2 口径）。"

## 代码入口

主入口（file:symbol，AST 校验存在）：

- `src/rfauto/core/calc_families/coupled_line_bpf.py:coupled_line_bpf_synthesize`
- `src/rfauto/core/calc_families/coupled_line_bpf.py:coupled_line_bpf_response`

src/rfauto/core/calc_families/coupled_line_bpf.py 公开符号 **2** 个（AST 机读）：

`coupled_line_bpf_synthesize`、`coupled_line_bpf_response`

## 锚与测试入口

analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——登记后重跑本生成器）。

判据书/规格指针（docstring 逐字引文钉）：

- `tests/unit/test_a3c_coupled_interdigital.py`——引文："tests/unit/test_a3c_coupled_interdigital.py"

测试面（tests/unit 引用扫描，机读；合计 **97** 个 test 函数）：

| 测试文件 | test 函数数 |
|---|---|
| `tests/unit/test_a3c_coupled_interdigital.py` | 20 |
| `tests/unit/test_calculators.py` | 50 |
| `tests/unit/test_physics_invariants.py` | 27 |

XC-P 精度档案收集器（防漂移对照面）：`tests/unit/test_precision_profiles.py`；本卡保鲜门：`tests/unit/test_kernel_cards.py`。

## 关联

- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)
- [分层架构](../explanation/layered-architecture.md)
- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表
- 同批内核卡：[macromodel](macromodel.md)、[rwg_mmt](rwg_mmt.md)、[pdn](pdn.md)、[pce](pce.md)、[cascade](cascade.md)、[mline](mline.md)、[wilkinson](wilkinson.md)、[branchline](branchline.md)、[ratrace](ratrace.md)、[patch](patch.md)、[hairpin](hairpin.md)、[cpw](cpw.md)、[slotline](slotline.md)、[coupled_microstrip](coupled_microstrip.md)、[finline](finline.md)、[wilkinson_unequal](wilkinson_unequal.md)、[atten_pi](atten_pi.md)、[atten_t](atten_t.md)、[qwt_multisection](qwt_multisection.md)、[nway_wilkinson](nway_wilkinson.md)、[schiffman](schiffman.md)、[bethe_hole_coupler](bethe_hole_coupler.md)、[gysel_core](gysel_core.md)

