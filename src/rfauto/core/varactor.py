"""M-5 变容二极管（varactor）调谐 BPF 闭式综合内核（首个半有源模板族）。

消费面：`adapters/openems_templates.py` 的 `varactor_bpf` 模板渲染（C(V) 字面量）、
`adapters/fake_adapter.py` 派发分支（谷位随 C(V) 等效伸缩）、模板名义参数设计链
（铁律 #1c：全部数值综合精算，无手抄毫米数）。数值只在确定性内核（规则 7）。

物理口径（全部推导自无损传输线驻波边界条件，单测钉住）：

1. **突变结 C-V 闭式**：C(V) = Cj0/√(1+V/φ)（V=反偏电压 ≥0，φ=内建电位，
   Si 突变结典型 0.7-0.9 V）。反解 V(C) = φ·((Cj0/C)²−1)（0<C≤Cj0）。

2. **主谐振方程（开路端装载 λ/2 臂）**：谐振臂（hairpin U 展开长 L）一端开路、
   开路端对地并联 C(V)。驻波 V(z)=V_A·cos βz、I(z)=−j(V_A/Z0)·sin βz（开路端
   z=0，I(0)=0）；装载端 z=L 处 I(L)/V(L) = jωC 与线方程联立：

       tan(βL) = −ω·C·Z0 ，  βL ∈ (π/2, π)

   闭式逆：C(f) = −tan(βL)/(ω·Z0)。极限自检（单测钉住）：C→0 ⇒ βL=π
   （λ/2 开开谐振 = hairpin 无载锚）；C→∞ ⇒ βL→π/2（λ/4 开短极限）。
   f 随 C 单调下降（调谐方向）。正解方向无闭式，brentq 在
   (f_λ/4, f_λ/2) 内求根（单调，括号天然）。

3. **静态电容口径（FDTD 无时变 C，写进模板 meta/docstring）**：openEMS FDTD
   的 LumpedElement 电容是每 run 常数（CSXCAD `CSPropLumpedElement.SetCapacity`，
   .pyx 逐行核实：`C` kwarg→SetCapacity（法拉）、`ny` 经 CheckNyDir 收方向索引
   （0/1/2=x/y/z，ny=2 即 z 向 shunt 对地惯用法，#282 审计结论）、`LEtype`
   缺省 LE_PARALLEL（R/L/C 并联）、`caps=True` 两端 PEC 端板接连接线）。
   **三档偏压=三次静态 run**：各档 C(V_i) 为常数，调谐曲线由多点静态解组成，
   不是单 run 内时变电容（openEMS unreleased v0.37 之前的引擎无时变集总元件）。

4. **变容管 Q 与谐振器能量份额**：元件级 Q_v = 1/(2πf·C·R_s)（串联 R_s 模型，
   datasheet 口径）。谐振器（线无耗、仅变容管损耗）的 unloaded Q 由能量份额
   闭式给出：η_C(βL) = 1/(1/2 − βL/sin 2βL)（储存在 C 中的电能份额），
   Q_u = Q_v/η_C = Q_v·(1/2 − βL/sin 2βL)。
   推导：W_e = ¼C|V_L|² + ¼(β/ωZ0)V_A²∫₀ᴸcos²βz dz（线单位长电容 C′₀=β/ωZ0）、
   谐振时 W=2W_e（W_e=W_m）；P = ½R_s·ω²C²|V_L|²；代入 ωC=−tanβL/Z0 与
   ∫₀ᴸcos²βz dz = L/2 + sin 2βL/(4β) 即得。自检（单测钉住）：C→0⁺（βL→π⁻）
   与 C→∞（βL→π/2⁺）两极限 η_C→0（谐振 Q→∞，能量退不出 C/电压节点在装载端）；
   带内极大约 η_C≈0.35（Q_u ≈ 2.9·Q_v——变容管元件 Q 低估其在谐振器中的
   Q 贡献，设计时不得直接拿 Q_v 当 Q_u）。线损另计：总
   Q_u = (1/Q_line + η_C/Q_v)⁻¹。

5. **带心插损（精确电路求值，非经验公式）**：N 谐振器 J 倒置器链在 f̂=1 的
   归一化耦合矩阵电路（单位斜率口径，Cameron 耦合矩阵法）：
   节点导纳 G_i = 1/Q_u,i，倒置器 x_j = J_j/Z0（与 coupled_bpf_design_from_order
   同式：Chebyshev g 值，core/matching 单源），源/负载导纳 1。f0 处每个并联
   谐振器退化成纯电导，全链 ABCD 精确级联 ⇒ |S21| 精确。无耗（Q→∞）恒等式
   |S21|=1 由构造保证（单测钉住）；Q_v↓ ⇒ Q_u↓ ⇒ G_i↑ ⇒ IL↑ 单调
   （插损单调性物理门）。

6. **抽头外耦（loaded 廓线，branch B 自 C 端计；2026-09-29 P0 修复）**：抽头馈线
   与装载臂的外部 Q 闭式**依赖驻波廓线**（#154 族口径：同名几何参数跨廓线语义
   不同）。hairpin 无载族（βL=π）用 coupled_microstrip.hairpin_qe_from_tap_frac
   （廓线 cos(πz/L)，节点在 τ=0.5）；本族装载臂（βL∈(π/2,π)）廓线为
   V(z)=V_A·cos(βz)（z 自真开路端），自 C 端距离 s=τL 处
   |V|=|V_A·cos(βL(1−τ))|。branch B=抽头位于 C 端与电压节点之间
   （βL(1−τ)∈(π/2,βL)，cos<0，|cos(βL(1−τ))|=−cos(βL(1−τ))），廓线形状与
   无载式同形：

       Q_e = (π/2)·(Z0/Z_r)·sec²(βL(1−τ))            （正问题）
       τ   = 1 − (π − acos(√((π/2)(Z0/Z_r)/Q_e)))/βL （反解 branch B）

   反解代数：|V(τ)|=√((π/2)(Z0/Z_r)/Q_e) ⇒ cos(βL(1−τ))=−√(...)（branch B 取
   负枝）⇒ βL(1−τ)=π−acos(√(...))（acos(−x)=π−acos(x)）。独立验证（单测钉）：
   ① 正反往返逐位；② 无载退化 βL=π 时 sec²(π(1−τ))=sec²(πτ) 逐位回 hairpin
   原式；③ Q_e→∞ 退化为电压节点 τ_node=1−π/(2βL)；④ 分布参数导纳斜率数值
   裁判（抽头结电纳 B=Y_C枝+Y_开路枝，b=(f0/2)·dB/df，Q_e=b·Z0——与 hairpin
   无载 #118 校核同法）证实**廓线形状正确、π/2 前因子是一阶替代**（审计预
   声明）：精确比值=数值裁判/闭式 在 βL=π 处 →1（≤1e-6）、名义工作带
   βL∈[2.6,2.91] 内 −0.25%~−3.2%（实测逐档 0.970~0.997，review-slice10 P2-2
   勘误——初版 −0.8%~−1% 系目测带；深装载 βL=2.0 处 −24%）——prefactor 误差随装载
   加深放大，精确 Q_e 留本族真机标定（runs/varactor_smoke/model_audit_verdict.md
   P0 行）。**在臂守卫**（几何层）：τ ≤ l_arm/L=(L−b)/(2L)（抽头须落在装载臂
   内），由设计链/布局显式校验（_hairpin_layout y_tap≥y1 同款守卫）；kernel
   层守卫 τ∈(0, τ_node)（branch B 定义域）。tap_frac 语义**自 C 端计**
   （#154 收口：输出抽头在无 C 臂、自真开路端锚定，与输入不等价——P1 交决策，
   暂同 τ 值复用）。

层序：本文件属 core（被 adapters 消费），不 import adapters（import-linter）。
"""

from __future__ import annotations

import math
from typing import Any

#: 真空光速（m/s；全仓闭式同一常数口径）
C0 = 299792458.0

#: 突变结内建电位缺省（V，Si 突变结文献典型带中值；模型选型常数，非实测）
PHI_DEFAULT_V = 0.9

#: 零偏电容缺省（pF，典型调谐变容管量级；模型选型常数，非实测）
CJ0_DEFAULT_PF = 1.0


# ── 突变结 C-V 闭式 ──────────────────────────────────────────────────────────

def abrupt_junction_capacitance_pf(v_v: float, cj0_pf: float,
                                   phi_v: float) -> float:
    """突变结 C(V) = Cj0/√(1+V/φ)（pF；V=反偏电压 ≥0，C(0)=Cj0）。

    V<0 或 V≤−φ 无物理意义（正偏导通/雪崩区外推）——显式 ValueError，
    不静默 clamp（调谐计划可行性由调用方判定，不造假数）。
    """
    v = float(v_v)
    cj0 = float(cj0_pf)
    phi = float(phi_v)
    if cj0 <= 0.0:
        raise ValueError(f"cj0_pf={cj0_pf} 须 >0")
    if phi <= 0.0:
        raise ValueError(f"phi_v={phi_v} 须 >0")
    if v < 0.0:
        raise ValueError(f"v_v={v_v} 须 ≥0（反偏口径；正偏导通不在闭式域）")
    return cj0 / math.sqrt(1.0 + v / phi)


def bias_for_capacitance_v(c_pf: float, cj0_pf: float, phi_v: float) -> float:
    """C(V) 精确逆：V = φ·((Cj0/C)²−1)（V；0<C≤Cj0 ⇒ V≥0）。

    c=cj0 ⇔ V=0（零偏）；c>cj0 需正偏（不在反偏闭式域）→ ValueError。
    """
    c = float(c_pf)
    cj0 = float(cj0_pf)
    phi = float(phi_v)
    if cj0 <= 0.0 or phi <= 0.0:
        raise ValueError("cj0_pf/phi_v 须 >0")
    if not 0.0 < c <= cj0:
        raise ValueError(
            f"c_pf={c_pf} 须在 (0, cj0]={cj0}（c>cj0 需正偏，不在反偏域）")
    return phi * ((cj0 / c) ** 2 - 1.0)


# ── 变容管 Q（串联 R_s 模型）────────────────────────────────────────────────

def varactor_series_r_for_q(f_ghz: float, q_ref: float, c_pf: float) -> float:
    """由参考点 (f, Q, C) 反解串联电阻 R_s = 1/(2πf·Q·C)（Ω）。"""
    f = float(f_ghz)
    q = float(q_ref)
    c = float(c_pf)
    if f <= 0.0 or q <= 0.0 or c <= 0.0:
        raise ValueError(f"f/q/c 须 >0，得 ({f_ghz}, {q_ref}, {c_pf})")
    return 1.0 / (2.0 * math.pi * f * 1e9 * q * c * 1e-12)


def varactor_q(f_ghz: float, c_pf: float, rs_ohm: float) -> float:
    """变容管元件级 Q_v = 1/(2πf·C·R_s)（datasheet 口径；非谐振器 Q_u）。"""
    f = float(f_ghz)
    c = float(c_pf)
    rs = float(rs_ohm)
    if f <= 0.0 or c <= 0.0 or rs <= 0.0:
        raise ValueError(f"f/c/rs 须 >0，得 ({f_ghz}, {c_pf}, {rs_ohm})")
    return 1.0 / (2.0 * math.pi * f * 1e9 * c * 1e-12 * rs)


# ── 主谐振方程（开路端装载 λ/2 臂）──────────────────────────────────────────

def loaded_line_f0_limits_ghz(line_len_mm: float,
                              ereff: float) -> tuple[float, float]:
    """装载臂谐振窗 (f_λ/4, f_λ/2)（GHz）：C→∞ 与 C→0 的极限频率。

    f_λ/2 = c0/(2·L·√εeff)（C=0 无载锚）、f_λ/4 = c0/(4·L·√εeff)（C→∞ 极限，
    不可达）。目标调谐频率必须严格落在窗内。
    """
    l_m = float(line_len_mm) * 1e-3
    er = float(ereff)
    if l_m <= 0.0 or er <= 0.0:
        raise ValueError(f"line_len_mm/ereff 须 >0，得 ({line_len_mm}, {ereff})")
    f_half = C0 / (2.0 * l_m * math.sqrt(er)) / 1e9
    return f_half / 2.0, f_half


def varactor_load_capacitance_pf(f_ghz: float, line_len_mm: float,
                                 z0_ohm: float, ereff: float) -> float:
    """主谐振方程闭式逆：给定 f 解装载电容 C = −tan(βL)/(ω·Z0)（pF）。

    f 须严格在 (f_λ/4, f_λ/2) 窗内（βL ∈ (π/2, π)，tan<0 ⇒ C>0）；窗外
    （无载之上不需要 C、窗下之下 C→∞ 才可达）显式 ValueError。
    """
    f = float(f_ghz) * 1e9
    l_m = float(line_len_mm) * 1e-3
    z0 = float(z0_ohm)
    er = float(ereff)
    if z0 <= 0.0:
        raise ValueError(f"z0_ohm={z0_ohm} 须 >0")
    f_lo, f_hi = loaded_line_f0_limits_ghz(line_len_mm, ereff)
    if not f_lo < float(f_ghz) < f_hi:
        raise ValueError(
            f"f={f_ghz}GHz 须在装载窗 ({f_lo:.6g}, {f_hi:.6g})GHz 内"
            f"（βL∈(π/2,π)；窗外无正电容解）")
    beta_l = 2.0 * math.pi * f * math.sqrt(er) * l_m / C0
    omega = 2.0 * math.pi * f
    return -math.tan(beta_l) / (omega * z0) * 1e12


def varactor_line_f0_ghz(c_pf: float, line_len_mm: float, z0_ohm: float,
                         ereff: float) -> float:
    """主谐振方程正解：给定 C 解 f（GHz）——brentq 于 (f_λ/4, f_λ/2)。

    残差 g(f) = tan(βL) + ω·C·Z0 在窗内单调增（βL↑ ⇒ tan 从 −∞ 单调增到 0、
    ωCZ0 单调增），brentq 括号天然成立。C=0 退化为无载锚（窗上沿）。
    """
    from scipy.optimize import brentq

    c = float(c_pf)
    if c < 0.0:
        raise ValueError(f"c_pf={c_pf} 须 ≥0")
    if c == 0.0:
        f_lo, f_hi = loaded_line_f0_limits_ghz(line_len_mm, ereff)
        return f_hi
    l_m = float(line_len_mm) * 1e-3
    z0 = float(z0_ohm)
    er = float(ereff)

    def _g(f_ghz: float) -> float:
        f = f_ghz * 1e9
        beta_l = 2.0 * math.pi * f * math.sqrt(er) * l_m / C0
        return math.tan(beta_l) + 2.0 * math.pi * f * c * 1e-12 * z0

    # 括号收缩避端点奇异（tan 在窗两端发散）：取窗的 1e-9 相对内缩
    f_lo, f_hi = loaded_line_f0_limits_ghz(line_len_mm, ereff)
    eps = 1e-9
    a = f_lo + (f_hi - f_lo) * eps
    b = f_hi - (f_hi - f_lo) * eps
    return float(brentq(_g, a, b, xtol=1e-12, rtol=8.9e-16, maxiter=200))


# ── 谐振器 Q（能量份额闭式）────────────────────────────────────────────────

def capacitor_energy_fraction(beta_l: float) -> float:
    """装载电容储存电能份额 η_C(βL) = 1/(1/2 − βL/sin 2βL)（βL∈(π/2,π)）。

    推导见模块 docstring §4。两窗端 η_C→0（单测钉住）。
    """
    x = float(beta_l)
    if not math.pi / 2.0 < x < math.pi:
        raise ValueError(f"beta_l={beta_l} 须在 (π/2, π)（主谐振方程定义域）")
    return 1.0 / (0.5 - x / math.sin(2.0 * x))


def varactor_resonator_qu(q_v: float, beta_l: float) -> float:
    """仅变容管损耗的谐振器 unloaded Q：Q_u = Q_v/η_C = Q_v·(1/2−βL/sin 2βL)。"""
    q = float(q_v)
    if q <= 0.0:
        raise ValueError(f"q_v={q_v} 须 >0")
    return q / capacitor_energy_fraction(beta_l)


def resonator_qu_combined(q_line: float, qu_varactor: float) -> float:
    """线损与变容管损耗并联：Q_u = (1/Q_line + 1/Q_u,var)⁻¹（各损耗通道
    倒数可加；Q_line=inf（无耗线）时退化为变容管项）。"""
    ql = float(q_line)
    qv = float(qu_varactor)
    if ql <= 0.0 or qv <= 0.0:
        raise ValueError(f"q_line/qu_varactor 须 >0，得 ({q_line}, {qu_varactor})")
    return 1.0 / (1.0 / ql + 1.0 / qv)


# ── 抽头外耦（loaded 廓线 branch B 自 C 端计；2026-09-29 P0 修复）────────────

def varactor_tap_node_frac(beta_l: float) -> float:
    """装载臂电压节点位置（自 C 端计）：τ_node = 1 − π/(2βL)（βL∈(π/2,π)）。

    独立锚（审计表 runs/varactor_smoke/model_audit_verdict.md）：βL=2.6112/
    2.8050/2.9115 → 0.3984/0.4400/0.4605（节点随 C 递增向 C 端移动，恰扫过
    旧无载设计 τ=0.401892 = P0 根因）。
    """
    x = float(beta_l)
    if not math.pi / 2.0 < x < math.pi:
        raise ValueError(f"beta_l={beta_l} 须在 (π/2, π)（主谐振方程定义域）")
    return 1.0 - math.pi / (2.0 * x)


def varactor_tap_qe_loaded(tap_frac: float, beta_l: float,
                           z0_ohm: float = 50.0,
                           z_line_ohm: float = 50.0) -> float:
    """loaded 廓线抽头外耦正问题：Q_e=(π/2)(Z0/Z_r)·sec²(βL(1−τ))。

    τ 自 C 端计（branch B：C 端与电压节点之间，τ∈(0, τ_node)）；βL=主谐振方程
    工作点电长度 ∈(π/2,π)。廓线推导与 prefactor 替代口径见模块 docstring §6
    （π/2 前因子为一阶替代，精确 Q_e 留本族真机标定——审计 P0 行预声明）。
    无载退化：βL=π 时逐位回 coupled_microstrip.hairpin_qe_from_tap_frac
    （sec² 平移恒等，单测钉）。
    """
    tau = float(tap_frac)
    x = float(beta_l)
    if not math.pi / 2.0 < x < math.pi:
        raise ValueError(f"beta_l={beta_l} 须在 (π/2, π)（主谐振方程定义域）")
    tau_node = 1.0 - math.pi / (2.0 * x)
    if not 0.0 < tau < tau_node:
        raise ValueError(
            f"tap_frac={tau} 须在 (0, τ_node={tau_node:.6f})（branch B：C 端与"
            "电压节点之间；τ≥τ_node 在节点/开路侧=branch A，另一支反解）")
    return ((math.pi / 2.0) * (float(z0_ohm) / float(z_line_ohm))
            / math.cos(x * (1.0 - tau)) ** 2)


def varactor_tap_frac_from_qe_loaded(qe: float, beta_l: float,
                                     z0_ohm: float = 50.0,
                                     z_line_ohm: float = 50.0) -> float:
    """loaded 廓线抽头外耦反解（branch B 自 C 端计）：
    τ = 1 − (π − acos(√((π/2)(Z0/Z_r)/Q_e)))/βL。

    审计三档预声明值：Q_e=17.07 在 βL=2.6112/2.8050/2.9115 →
    τ=0.280407/0.330124/0.354627（≈0.280/0.330/0.355，合成裁判单测钉）。
    Q_e 过低（acos→0，τ≤0：抽头落 C 端臂外）显式 ValueError；Q_e→∞（τ→τ_node
    电压节点）自然退化。在臂守卫 τ ≤ l_arm/L=(L−b)/(2L) 属几何层（设计链/
    _hairpin_layout 显式校验），本函数只管 branch B 电学定义域。
    """
    q_e = float(qe)
    x = float(beta_l)
    if not math.pi / 2.0 < x < math.pi:
        raise ValueError(f"beta_l={beta_l} 须在 (π/2, π)（主谐振方程定义域）")
    if q_e <= 0.0:
        raise ValueError("Q_e 须 >0")
    ratio = (math.pi / 2.0) * (float(z0_ohm) / float(z_line_ohm))
    c2 = ratio / q_e
    if not 0.0 < c2 <= 1.0:
        raise ValueError(
            f"Q_e={q_e} 低于抽头可达下限 {ratio:.4f}（τ→0 极限，acos 出域；"
            "hairpin 无载式同款守卫）")
    tau = 1.0 - (math.pi - math.acos(math.sqrt(c2))) / x
    if not tau > 0.0:
        raise ValueError(
            f"Q_e={q_e} 过低：反解 τ={tau:.6f} ≤ 0（抽头落 C 端臂外，branch B"
            f" 不可达；本工作点 βL={x:.4f} 的 Q_e 下限在 τ→0）")
    return tau


def varactor_box_geo_capacitance_pf(wf_mm: float, h_sub_mm: float,
                                    er: float) -> float:
    """变容管装载盒几何寄生电容（平行板项，pF）：C_geo=ε0·εr·WF²/H_SUB。

    口径（审计三 runs/varactor_smoke/model_audit_verdict.md）：LumpedElement
    全隙盒 WF×WF×z 0→H_SUB（ny=2 z 向 shunt，caps=True 端板）——引擎 lumped
    更新与盒区背景位移电流**并联**，实感 C=C_literal+C_geo > 设计 C(V)（#252
    族语义稀释）；渲染链 C_literal=C(V)−C_geo 扣除后实感=设计 C(V)。本函数取
    **平行板精确项**（盒区均匀场口径）：名义 WF=1.1117/H=0.508/εr=3.66 →
    0.078839 pF（审计 0.0788 ✓）。边缘项未纳入（审计带 0.095~0.110 pF 含边缘
    估计，无独立来源核验的边缘系数不入内核——#118/#134 纪律）：扣除份额欠估
    ≤31%（v10 档）如实预声明，方向（降 C_literal）不受影响。
    """
    wf = float(wf_mm)
    h = float(h_sub_mm)
    e_r = float(er)
    if wf <= 0.0 or h <= 0.0 or e_r <= 0.0:
        raise ValueError(f"wf_mm/h_sub_mm/er 须 >0，得 ({wf_mm}, {h_sub_mm}, {er})")
    return 8.8541878128e-12 * e_r * (wf * 1e-3) ** 2 / (h * 1e-3) * 1e12


# ── 带心插损（Cameron 耦合矩阵精确求值 + 耗散对角扩展）───────────────────────

def midband_insertion_loss_db(matrix: Any, qu_list: list[float],
                              qe_in: float = 1.0,
                              qe_out: float = 1.0) -> float:
    """N 谐振器耦合矩阵滤波器带心插损（dB；Cameron N+2 矩阵精确求值）。

    评测式与 core/calculators._cm_response_raw 同构（Cameron 经典 −jM 口径）：
    Y[0,0]=qe_in、Y[L,L]=qe_out（源/负载实对角）、内节点
    Y[i,i]=j(ω̂−m_ii)、非对角 −j·m_ij，ω̂=0（带心）。**耗散扩展**
    （Cameron ch.4 有限 unloaded Q 的标准对角项）：内节点对角加 +1/Q_u,i
    （并联谐振器损耗电导，单位斜率归一口径）。本仓归一口径 external_q=
    [1,1]（外部耦合在 m_0i/m_iL 内，coupling_matrix_response 缺省同），
    缺省 1.0/1.0 即同口径。无耗（Q=inf）与 coupling_matrix_response 在
    f0 处逐位一致（独立双路径，test_varactor 钉住）；损耗 ⇒ |S21|<1
    ⇒ IL>0，对任一 Q_u 递减单调（插损单调性物理门）。
    """
    import numpy as _np

    m = _np.asarray(matrix, dtype=float)
    if m.ndim == 3 and m.shape[-1] == 2:          # [re, im] 对（复元素）
        m = _np.hypot(m[..., 0], m[..., 1])
    n2 = m.shape[0]
    qs = [float(v) for v in qu_list]
    if len(qs) != n2 - 2:
        raise ValueError(
            f"qu_list 长度须为阶数 N={n2 - 2}，得 {len(qs)}")
    if any(q <= 0.0 for q in qs):
        raise ValueError(f"qu_list 须全 >0，得 {qu_list}")
    if float(qe_in) <= 0.0 or float(qe_out) <= 0.0:
        raise ValueError("qe_in/qe_out 须 >0")
    y = _np.zeros((n2, n2), dtype=complex)
    for i in range(n2):
        for j in range(n2):
            if i == j:
                if i == 0:
                    y[i, i] = float(qe_in)
                elif i == n2 - 1:
                    y[i, i] = float(qe_out)
                else:
                    loss = (float("inf") if qs[i - 1] == float("inf")
                            else qs[i - 1])
                    y[i, i] = (0.0 if loss == float("inf")
                               else 1.0 / loss)          # ω̂=0 − m_ii + 1/Q
            else:
                y[i, j] = -1j * m[i, j]
    b = _np.zeros(n2, dtype=complex)
    b[0] = 1.0
    v = _np.linalg.solve(y, b)
    s21 = 2.0 * v[n2 - 1] / math.sqrt(float(qe_in) * float(qe_out))
    return float(-20.0 * math.log10(abs(s21)))


# ── 调谐综合服务面（f0 目标序列 → C 需求 → V 反解）─────────────────────────

def tuning_bias_plan(
    f_targets_ghz: list[float], cj0_pf: float, phi_v: float,
    line_len_mm: float, z0_ohm: float, ereff: float,
    *, rs_ohm: float | None = None, q_line: float = float("inf"),
    order: int = 1, fbw: float = 0.05, rl_db: float = 20.0,
) -> list[dict[str, Any]]:
    """调谐曲线综合：f0 目标序列 → 每谐振器 C 需求 → V 偏置反解（M-5 规格）。

    每目标返回 {f_target_ghz, c_req_pf, v_bias_v, feasible, beta_l, q_v, qu,
    il_db}；feasible=False 时 v_bias_v/q_v/qu/il_db 为 None（C 需求超出
    (0, cj0] 反偏域或目标在装载窗外——如实不可行，不外推不 clamp）。
    rs_ohm 缺省 None=无耗（q_v/qu=inf、il_db=0）；IL-调谐范围 Pareto 扫描走
    显式 rs_ohm（q_line 缺省 inf=线无耗上界口径）。il_db 为 N=order 个同
    Q_u 谐振器的带心插损（midband_insertion_loss_db，q_line/Q_v 同参数）。
    """
    rs = None if rs_ohm is None else float(rs_ohm)
    import numpy as _np

    from rfauto.core.synthesis import synthesize_bpf_model

    synth = synthesize_bpf_model(order=int(order), f0_ghz=1.0,
                                 fbw=float(fbw), rl_db=float(rl_db),
                                 topology="folded")
    if not synth.get("ok"):
        raise ValueError(f"folded C13 综合失败: {synth.get('errors')}")
    m = _np.asarray(synth["coupling_matrix"], dtype=float)
    if m.ndim == 3:
        m = _np.hypot(m[..., 0], m[..., 1])
    out: list[dict[str, Any]] = []
    for f_t in f_targets_ghz:
        row: dict[str, Any] = {"f_target_ghz": float(f_t)}
        try:
            c_req = varactor_load_capacitance_pf(float(f_t), line_len_mm,
                                                 z0_ohm, ereff)
        except ValueError:
            row.update({"c_req_pf": None, "v_bias_v": None, "feasible": False,
                        "beta_l": None, "q_v": None, "qu": None, "il_db": None})
            out.append(row)
            continue
        row["c_req_pf"] = c_req
        beta_l = 2.0 * math.pi * float(f_t) * 1e9 * math.sqrt(
            float(ereff)) * float(line_len_mm) * 1e-3 / C0
        row["beta_l"] = beta_l
        if not 0.0 < c_req <= float(cj0_pf):
            row.update({"v_bias_v": None, "feasible": False, "q_v": None,
                        "qu": None, "il_db": None})
            out.append(row)
            continue
        row["v_bias_v"] = bias_for_capacitance_v(c_req, cj0_pf, phi_v)
        row["feasible"] = True
        if rs is None:
            row.update({"q_v": float("inf"), "qu": float("inf"), "il_db": 0.0})
        else:
            q_v = varactor_q(float(f_t), c_req, rs)
            qu = resonator_qu_combined(float(q_line),
                                       varactor_resonator_qu(q_v, beta_l))
            row.update({"q_v": q_v, "qu": qu,
                        "il_db": midband_insertion_loss_db(
                            m, [qu] * int(order))})
        out.append(row)
    return out


# ── 模板名义设计链（铁律 #1c：全部综合精算）────────────────────────────────

def varactor_bpf_design(
    f0_ghz: float = 2.5, f_unloaded_ghz: float = 2.8,
    cj0_pf: float = CJ0_DEFAULT_PF, phi_v: float = PHI_DEFAULT_V,
    order: int = 3, fbw: float = 0.05, rl_db: float = 20.0,
    *, er: float = 3.66, h_mm: float = 0.508,
    arm_gap_mm: float = 3.0,
) -> dict[str, Any]:
    """varactor_bpf 名义设计链（确定性映射；渲染/ fake/审计三方单源）。

    口径：
    1. w_mm = inverse_width(50Ω @ f0)（HJ，同 hairpin 链）；
    2. εeff = forward_z0(w_mm @ f_unloaded)（臂长设置频率处评估）；
    3. arm_len_mm = λg/2(f_unloaded) = c0/(2·f_unloaded·√εeff)——无载谐振置于
       调谐带上沿 f_unloaded（C→0 极限），留下调谐余量；
    4. c_mid_pf = 主谐振方程闭式逆 C(f0)——名义偏置点的电容需求；
    5. bias_v = 突变结反解 V(c_mid)（0≤V≤V_max 域内检查交调用方）；
    6. 耦合链：hairpin_design_from_order(order, f0, fbw, rl, kgap_corrected=
       False) 纯 KJ——同向 U 的 c(gap) 结构修正表是 hairpin 真机标定
       （W4④），对变容管装载的新族**预声明不转移**（无本族真机标定前
       fake/名义一律纯 KJ 口径，与 hairpin_alt 同制度）；
    7. 抽头 τ（2026-09-29 P0 修复）：loaded 廓线 branch B 反解
       varactor_tap_frac_from_qe_loaded(Q_e, βL@f0)，**自 C 端计**（#154 收口）
       ——修复前沿用 hairpin 无载廓线闭式（βL=π），loaded 族电压节点恰扫过
       旧设计值致外耦失配 3-1139×（审计 P0）；名义点 βL=π·f0/f_unloaded（臂长
       =λg/2(f_unloaded) 的恒等式），在臂守卫 τ ≤ l_arm/L=(L−b)/(2L) 显式校验；
    8. 调谐窗报告：f(cj0)（V=0 上沿）与 f(√(1+10/φ)⁻¹·cj0)（V=10 V 下沿，
       演示口径）。

    返回 dict（w_mm/arm_len_mm/arm_gap_mm/gap_mm/tap_frac/tap_frac_ref/
    cj0_pf/phi_v/bias_v + c_mid_pf/f_unloaded_ghz/f_v0_ghz/f_v10_ghz/ereff +
    notes）。
    名义参数 = 本函数输出按 hairpin 同规则舍入（w/gap/arm_len 4 位、τ 6 位）。
    """
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    n = int(order)
    if n < 1:
        raise ValueError(f"order={order} 须 ≥1")
    if float(f_unloaded_ghz) <= 0.0:
        raise ValueError("f_unloaded_ghz 须 >0")
    if float(f_unloaded_ghz) <= float(f0_ghz):
        raise ValueError(
            f"f_unloaded={f_unloaded_ghz} 须 > f0={f0_ghz}"
            "（无载谐振在调谐带上沿，C 装载向下调谐）")
    stackup = Stackup(name="varactor_bpf", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    w_mm = float(inverse_width(50.0, float(f0_ghz), stackup)[0])
    _, ereff = forward_z0(w_mm, float(f_unloaded_ghz), stackup)
    arm_len_mm = C0 / (2.0 * float(f_unloaded_ghz) * 1e9
                       * math.sqrt(ereff)) * 1e3
    c_mid_pf = varactor_load_capacitance_pf(float(f0_ghz), arm_len_mm, 50.0,
                                            ereff)
    bias_v = bias_for_capacitance_v(c_mid_pf, float(cj0_pf), float(phi_v))
    # 耦合链（纯 KJ；同 hairpin 链口径，预声明不转移 hairpin 结构修正）
    from rfauto.core.synthesis import hairpin_design_from_order

    coup = hairpin_design_from_order(n, float(f0_ghz), float(fbw),
                                     float(rl_db), er=float(er), h_mm=float(h_mm),
                                     w_mm=w_mm, arm_gap_mm=float(arm_gap_mm),
                                     kgap_corrected=False)
    f_v0 = varactor_line_f0_ghz(float(cj0_pf), arm_len_mm, 50.0, ereff)
    c_v10 = abrupt_junction_capacitance_pf(10.0, float(cj0_pf), float(phi_v))
    f_v10 = varactor_line_f0_ghz(c_v10, arm_len_mm, 50.0, ereff)
    # 抽头 τ（P0 修复）：loaded 廓线 branch B 自 C 端计——无载廓线闭式的节点
    # （τ=0.5）与 loaded 族节点（1−π/(2βL)∈(0.4,0.5)）不等位，同名 τ 语义
    # 不同（#154 族）；旧值 0.401892 恰落 loaded 节点扫过带内=外耦失配根因。
    beta_l_nom = (2.0 * math.pi * float(f0_ghz) * 1e9 * math.sqrt(ereff)
                  * arm_len_mm * 1e-3 / C0)
    tau_loaded = varactor_tap_frac_from_qe_loaded(coup["qe"], beta_l_nom)
    b_mm = w_mm + float(arm_gap_mm)            # U 内两臂中心距（布局同式）
    tau_on_arm_max = (arm_len_mm - b_mm) / (2.0 * arm_len_mm)
    if not tau_loaded <= tau_on_arm_max:
        raise ValueError(
            f"loaded 抽头 τ={tau_loaded:.6f} 超出装载臂（在臂上限 "
            f"l_arm/L={tau_on_arm_max:.6f}，L={arm_len_mm:.4f}mm b={b_mm:.4f}mm）"
            "——增大 Q_e/调整 f_unloaded 或如实不可行")
    notes = [s for s in coup["notes"] if not s.startswith("抽头 τ")]
    notes += [
        f"臂长=λg/2({f_unloaded_ghz}GHz, εeff={ereff:.4f} HJ)={arm_len_mm:.4f}mm"
        f"（无载上沿；C 装载向下调谐）",
        f"名义偏置点：C({f0_ghz}GHz)={c_mid_pf:.4f}pF → V={bias_v:.4f}V"
        f"（cj0={cj0_pf}pF/φ={phi_v}V 突变结）",
        f"抽头 τ={tau_loaded:.6f}（loaded 廓线 branch B，自 C 端计；βL@"
        f"{f0_ghz}GHz={beta_l_nom:.4f}、Q_e={coup['qe']:.4f}、在臂上限 "
        f"{tau_on_arm_max:.4f}；旧无载廓线值 0.401892 已废——P0 修复）",
        f"调谐窗（静态三点口径）：f(V=0)={f_v0:.4f}GHz、"
        f"f(V=10V)={f_v10:.4f}GHz（FDTD 无时变 C，三档偏压=三次静态 run）",
    ]
    return {"order": n, "f0_ghz": float(f0_ghz),
            "f_unloaded_ghz": float(f_unloaded_ghz), "er": float(er),
            "h_mm": float(h_mm), "ereff": ereff, "w_mm": w_mm,
            "arm_len_mm": arm_len_mm, "arm_gap_mm": float(arm_gap_mm),
            "gap_mm": coup["gap_mm"], "gaps_mm": coup["gaps_mm"],
            "tap_frac": tau_loaded,
            "tap_frac_ref": "c_end_loaded_branchB",
            "k_list": coup["k_list"], "qe": coup["qe"], "cj0_pf": float(cj0_pf),
            "phi_v": float(phi_v), "c_mid_pf": c_mid_pf,
            "bias_v": bias_v, "f_v0_ghz": f_v0, "f_v10_ghz": f_v10,
            "notes": notes}
