"""材料表征内核（MA-1/MA-2/MA-3 + MA-4 登记级，研究扩充 round17 §六）。

纯算法零 IO 零外部进程（铁律 7 合规）；参照同域先例 core/dielectric_extract.py
**不进 @register_calculator 注册表**（免 #231/#304 注册表消费者三表连动），
导出函数供 service 层直调。判据以 round17 规格为准（先写后跑，#122），
测试=tests/unit/test_material_characterization.py。

方法面（round17 §六 MA-1/MA-2/MA-3 三条；出处=[E5] docs/research_expansion_
20260926.md 引文区：分裂圆柱 Janezic-Baker-Jarvis 1999；SPDR Krupka 2001
（精度数字单源待证）；Hakki-Coleman 1960 / Courtney 1970）
------------------------------------------------------
- MA-1 ``split_cylinder_*``：分裂圆柱谐振器 TE011 提取（全波口径：两半腔
  各长 ℓ、样品厚 d 居中，径向波数 k_r=x01/R，x01=J₁ 第一零点 3.8317…）。
  特征方程由 z=±d/2 界面切向场连续（E_φ∝Z 连续、H_r∝Z′ 连续，Z 为 H_z 的
  z 向因子）直接推导::

      β_s·tan(β_s·d/2) = β_a·cot(β_a·ℓ)
      β_s=√(k0²εr−k_r²)，β_a=√(k0²−k_r²)

  εr 反演=固定 f0 对 εr 求根（LHS 对 εr 单调、RHS 与 εr 无关 → 唯一根，
  基模支要求 β_s·d/2<π/2）；损耗按谐振腔能量分解 1/Q_u = p_e·tanδ + 1/Q_c，
  p_e（样品电能量占比）与 Q_c（端板 |H_r|² + 侧壁 |H_z|²）均由同一场解
  闭式积分。SPDR（Krupka 2001）按规格**只登记边界不实现**（
  :func:`spdr_extract`）。
- MA-2 ``courtney_*``：Hakki-Coleman/Courtney 平行板介质谐振器 TE01p 提取
  （confined 模型：场限于棒内，端板 z=0,L，径向 k_r=x0n/R，轴向 β=pπ/L）::

      εr = [(x0n/R)² + (pπ/L)²]/k0²      （Courtney 闭式，教科书标准式）

  tanδ 走 1/Q_u = p_e·tanδ + 1/Q_c（confined 缺省 p_e=1；端板损耗严格修
  正需 Kobayashi-Katoh 类泄漏场模型，P2/S 边界不做臆造系数——Q_c 由标定/
  外模型显式注入）。扰动口径（规格题名"TE01n 扰动"）：一阶微扰定理
  (f0−fs)/f0 = (εr′−1)·ξ/2、Δ(1/Q) = εr′·tanδ·ξ，ξ 为样品电填充因子
  （TE01p 模场闭式积分，:func:`te01p_sample_filling_factor`）。
- MA-4 ``fpor_*``（ge8b Wave B 席 B9 追加，**登记级**）：分裂柱谐振器
  （FPOR，薄样品夹于两介质柱端面间隙）微扰闭式——均匀场串联层精确口径
  ε_eff=1+x(εr−1)、f_s=f0/√ε_eff 及精确反演；一阶 k 形 k=2/x 为**可推导**
  均匀场极限（与 :func:`spdr_extract` 的"k 需标定"边界相容）；损耗面
  p_e 必填标定量。**真机 no-go 维持**（无仪器；非均匀场修正/标定曲线
  归独立立项面）。
- MA-3 ``free_space_*``：自由空间法 = **NRW 复用**（dielectric_extract.
  nrw_extract，零重复实现）+ **时域门衔接**（core/time_gating.gate_network，
  清洗天线间多径/边缘绕射后再提取）+ **LRR 口径**（Line(Thru 空测) +
  Reflect×2 金属板：对称夹具 Thru T 矩阵平方根去嵌——8 项误差模型对称
  特例 T_meas=T_F·T_x·T_F、T_F=√T_thru 无源分支——加反射板参考面核验
  |Γ|≈1 与平面偏移）。域守卫：厚度谐振点（d≈n·λg/2 时 S11→0、NRW K1 式
  发散失稳——以 er_guess 预报拒绝，:func:`thickness_resonance_guard`）；
  样品保持器语义（横向尺寸必须覆盖光斑，平面波照明前提，
  :func:`lateral_coverage_guard`）。

独立裁判锚（#118：不信单源推导，测试钉死）
------------------------------------------
- ℓ→0 极限：分裂圆柱特征方程退化为全填充 TE011，f0 必须回收 Courtney
  闭式（两独立推导在同一物理极限重合）。
- εr→1 空腔极限：f0 回收空腔 TE011 闭式 c/(2π)·√(k_r²+(π/(2ℓ+d))²)。
- 能量恒等式：特征方程+幅值连续解出的场解在谐振点满足
  k0²(εr·I_s+I_a) = k_r²(I_s+I_a)+β_s²J_s+A²β_a²J_a（即 W_e=W_m），
  对 E_φ/H_r 常数组构成独立自洽钉。
- MA-3 合成回收消费既有 tem_slab_sparams 正向（其自身已独立验证）。

边界（round17 no-go 与登记项，如实不越界）
------------------------------------------
- SPDR/FPOR/圆柱腔**真机 no-go**（无仪器）——本模块只做闭式与合成回收。
- SPDR 只登记公式引用+'需标定曲线'（精度数字单源待证）。
- LRR 完整三标准超定解（未知 Reflect 双解消歧）与非对称夹具超出 P2/M
  收口面：本口径为对称夹具特例，非对称留登记。
- Courtney 端板损耗严格修正（Kobayashi-Katoh 泄漏场模型）留登记，Q_c
  显式注入承载，不臆造系数。

时谐约定：与 dielectric_extract 同口径 e^{+jωt}，有耗 Im(εr)<0
（tanδ = −Im/Re > 0）；长度一律 SI 米（``*_m`` 后缀），频率 Hz。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from rfauto.core.dielectric_extract import C0, nrw_extract

__all__ = [
    "CourtneyResult",
    "FreeSpaceResult",
    "LRRDeembedResult",
    "PerturbationResult",
    "SplitCylinderLossResult",
    "SplitCylinderResult",
    "cavity_perturbation_extract",
    "courtney_er_from_f0",
    "courtney_extract",
    "courtney_f0_of_er",
    "courtney_tand_from_q",
    "fpor_er_first_order",
    "fpor_er_from_fshift",
    "fpor_fill_factor",
    "fpor_fshift",
    "fpor_pe_uniform_field",
    "fpor_tand_from_q",
    "free_space_extract",
    "free_space_extract_network",
    "lateral_coverage_guard",
    "lrr_deembed",
    "spdr_extract",
    "split_cylinder_er_from_f0",
    "split_cylinder_extract",
    "split_cylinder_f0_of_er",
    "split_cylinder_tand_from_q",
    "te01p_sample_filling_factor",
    "thickness_resonance_guard",
]


def _j1_zero(n_radial: int) -> float:
    """J₁ 第 n 零点 x0n（TE0 模径向条件 J₁(x0n)=0；scipy 惰性求值免硬编码）。"""
    from scipy.special import jn_zeros

    n = int(n_radial)
    if n < 1:
        raise ValueError(f"n_radial 必须 ≥1，实际 {n_radial}")
    return float(jn_zeros(1, n)[-1])


def _positive(value: float, label: str) -> float:
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{label} 必须为正有限数，实际 {value!r}")
    return v


# ═══ MA-1：分裂圆柱谐振器（Janezic-Baker-Jarvis 1999 全波 TE011）══════════════


@dataclass(frozen=True)
class _SCFieldSolution:
    """分裂圆柱 TE011 场解（特征方程给定 (f0, εr) 下的闭式积分中间量）。

    场表达式（H_z = H0·J₀(k_r r)·Z(z)，样品区 Z=cos(β_s z)，空气区
    Z=A·sin(β_a(ℓ+d/2−z))）：
      E_φ = (jωμ0H0/k_r)·J₁(k_r r)·Z(z)，H_r = (H0/k_r)·J₁(k_r r)·Z′(z)；
      ∫∫J₁²(k_r r) r dr dφ = πR²·J₀²(x01)（J₁(x01)=0）。
    i_s/i_a=∫|Z|²dz（电能量核），j_s/j_a=∫|Z′|²dz/β²（磁能量核）。
    """

    f_hz: float
    er: float
    k_r: float
    beta_s: float
    beta_a: float
    amp_a: float
    i_s: float
    i_a: float
    j_s: float
    j_a: float
    p_e: float


def _sc_betas(f_hz: float, er: float, r_m: float) -> tuple[float, float, float]:
    """特征方程波数三元组 (k_r, β_s, β_a)，含基模支守卫（β_s·d/2<π/2 另查）。"""
    k_r = _j1_zero(1) / r_m
    k0 = 2.0 * math.pi * f_hz / C0
    beta_a_sq = k0 * k0 - k_r * k_r
    if beta_a_sq <= 0.0:
        raise ValueError(
            f"f={f_hz:.6g} Hz 低于空气半腔 TE01 径向截止 c·x01/(2πR)="
            f"{C0 * _j1_zero(1) / (2.0 * math.pi * r_m):.6g} Hz：β_a 虚数，模式不存在"
        )
    beta_s_sq = k0 * k0 * er - k_r * k_r
    if beta_s_sq <= 0.0:
        raise ValueError(f"样品内 β_s 虚数（k0²εr ≤ k_r²）：εr={er} 与频率不相容")
    return k_r, math.sqrt(beta_s_sq), math.sqrt(beta_a_sq)


def _sc_residual_in_er(
    er: float, f_hz: float, r_m: float, ell_m: float, d_m: float
) -> float:
    """特征方程残差 F(εr; f0) = β_s·tan(β_s·d/2) − β_a·cot(β_a·ℓ)。"""
    _k_r, beta_s, beta_a = _sc_betas(f_hz, er, r_m)
    half = beta_s * d_m / 2.0
    if half >= math.pi / 2.0:
        # 求根括号上端探到基模支渐近线之外：给 brentq 一个正向大数（括号
        # 语义仍成立——F 越过 +∞ 渐近线前单调升）。
        return 1e18
    return beta_s * math.tan(half) - beta_a / math.tan(beta_a * ell_m)


def _sc_solution(
    f_hz: float, er: float, r_m: float, ell_m: float, d_m: float
) -> _SCFieldSolution:
    """特征方程场解：给 (f, εr) 解 β_s/β_a/幅值并闭式积分能量核。

    要求 (f, εr) 已在特征方程根上（基模支），否则 p_e/能量核无物理意义。
    """
    k_r, beta_s, beta_a = _sc_betas(f_hz, er, r_m)
    half = beta_s * d_m / 2.0
    if half >= math.pi / 2.0:
        er_max = ((math.pi / d_m) ** 2 + k_r * k_r) / (
            2.0 * math.pi * f_hz / C0
        ) ** 2
        raise ValueError(
            f"β_s·d/2={half:.4f} ≥ π/2：超出 TE011 基模支（样品过厚或 εr 过高），"
            f"εr 上限≈((π/d)²+k_r²)/k0²={er_max:.4f}"
        )
    residual = beta_s * math.tan(half) - beta_a / math.tan(beta_a * ell_m)
    if abs(residual) > 1e-6 * max(1.0, beta_s):
        raise ValueError(
            f"(f, εr) 不在特征方程根上（|F|={abs(residual):.3g}）：场解无意义，"
            "先用 split_cylinder_er_from_f0 / split_cylinder_f0_of_er 求根"
        )
    amp_a = math.cos(half) / math.sin(beta_a * ell_m)
    i_s = d_m / 2.0 + math.sin(beta_s * d_m) / (2.0 * beta_s)
    i_a = amp_a**2 * (ell_m - math.sin(2.0 * beta_a * ell_m) / (2.0 * beta_a))
    j_s = d_m / 2.0 - math.sin(beta_s * d_m) / (2.0 * beta_s)
    j_a = amp_a**2 * (ell_m + math.sin(2.0 * beta_a * ell_m) / (2.0 * beta_a))
    p_e = er * i_s / (er * i_s + i_a)
    return _SCFieldSolution(
        f_hz=f_hz,
        er=er,
        k_r=k_r,
        beta_s=beta_s,
        beta_a=beta_a,
        amp_a=amp_a,
        i_s=i_s,
        i_a=i_a,
        j_s=j_s,
        j_a=j_a,
        p_e=p_e,
    )


def _sc_empty_f0(r_m: float, ell_m: float, d_m: float) -> float:
    """空腔（εr=1）TE011 闭式 f0 = c/(2π)·√(k_r² + (π/(2ℓ+d))²)（独立锚）。"""
    k_r = _j1_zero(1) / r_m
    h_total = 2.0 * ell_m + d_m
    return C0 / (2.0 * math.pi) * math.sqrt(k_r * k_r + (math.pi / h_total) ** 2)


def split_cylinder_f0_of_er(er: float, r_m: float, ell_m: float, d_m: float) -> float:
    """MA-1 正向：给定 εr 解 TE011 谐振频率 f0（特征方程对 f 求根，brentq）。

    F(f; εr) 在 (f_cut, f_empty) 内严格单调（LHS 随 f 增、RHS 随 f 减：
    d/dx[x·cot x]<0）→ 唯一根；f_cut=c·x01/(2πR)（径向截止）处 cot→+∞ 使
    F→−∞，εr>1 时 F(f_empty)>0（β_s>β_a）→ 括号天然成立。εr→1 时解析
    给出空腔闭式（跳过求根）。
    """
    from scipy.optimize import brentq

    er = _positive(er, "er")
    r_m = _positive(r_m, "r_m")
    ell_m = _positive(ell_m, "ell_m")
    d_m = _positive(d_m, "d_m")
    if er <= 1.0 + 1e-9:
        return _sc_empty_f0(r_m, ell_m, d_m)
    f_cut = C0 * _j1_zero(1) / (2.0 * math.pi * r_m)
    f_empty = _sc_empty_f0(r_m, ell_m, d_m)
    f_lo = f_cut * (1.0 + 1e-9)
    f_hi = f_empty * 1.5  # 上探到空腔解之外：εr>1 时 F(f_empty) 已 >0，单调保唯根
    try:
        return float(
            brentq(
                lambda f: _sc_residual_in_er(er, f, r_m, ell_m, d_m),
                f_lo,
                f_hi,
                xtol=1e-9,
                rtol=1e-14,
            )
        )
    except ValueError as exc:
        raise ValueError(
            f"正向求根失败（εr={er}，R={r_m}，ℓ={ell_m}，d={d_m}）：基模支无根——"
            "εr 超出基模可承载上限或几何病态"
        ) from exc


def split_cylinder_er_from_f0(
    f0_hz: float,
    r_m: float,
    ell_m: float,
    d_m: float,
) -> float:
    """MA-1 反演：TE011 谐振频率 f0 → εr（特征方程对 εr 求根，brentq）。

    括号 = (1, ((π/d)²+k_r²)/k0²)：下端 F(1)<0（f0<f_empty 时 tan(βd/2)<
    cot(βℓ)），上端 β_s·d/2→π/2⁻ 使 LHS→+∞。f0 ≥ f_empty（空腔解）时无
    物理根（介质只能降频）→ 显式报错（模式误指/测量异常语义）。
    """
    from scipy.optimize import brentq

    f0 = _positive(f0_hz, "f0_hz")
    r_m = _positive(r_m, "r_m")
    ell_m = _positive(ell_m, "ell_m")
    d_m = _positive(d_m, "d_m")
    f_empty = _sc_empty_f0(r_m, ell_m, d_m)
    if f0 >= f_empty * (1.0 - 1e-12):
        raise ValueError(
            f"f0={f0:.6g} ≥ 空腔 TE011 解 {f_empty:.6g} Hz：介质样品只能使谐振"
            "频率低于空腔值——模式误指（非 TE011）或测量异常"
        )
    k_r = _j1_zero(1) / r_m
    k0 = 2.0 * math.pi * f0 / C0
    if k0 <= k_r:
        raise ValueError(
            f"f0={f0:.6g} Hz 低于空气半腔 TE01 径向截止 "
            f"c·x01/(2πR)={C0 * k_r / (2.0 * math.pi * r_m):.6g} Hz：β_a 虚数，"
            "模式不存在"
        )
    er_hi = (1.0 - 1e-9) * ((math.pi / d_m) ** 2 + k_r * k_r) / (k0 * k0)
    try:
        return float(
            brentq(
                lambda e: _sc_residual_in_er(e, f0, r_m, ell_m, d_m),
                1.0 + 1e-12,
                er_hi,
                xtol=1e-13,
                rtol=8.9e-16,
            )
        )
    except ValueError as exc:
        raise ValueError(
            f"反演无根（f0={f0:.6g} Hz，R={r_m}，ℓ={ell_m}，d={d_m}）：频率落在"
            "基模支可达域之外或几何病态"
        ) from exc


@dataclass(frozen=True)
class SplitCylinderLossResult:
    """分裂圆柱损耗提取结果（1/Q_u = p_e·tanδ + 1/Q_c 分解）。"""

    tan_d: float
    er: float
    p_e: float                 # 样品电能量填充因子 ∈ (0,1]
    q_u: float                 # 输入无载 Q
    q_c: float | None          # 导体损耗 Q（未提供修正时 None → 1/Q_c=0 口径）
    metadata: dict[str, Any] = field(default_factory=dict)


def split_cylinder_tand_from_q(
    f0_hz: float,
    q_u: float,
    r_m: float,
    ell_m: float,
    d_m: float,
    *,
    er: float | None = None,
    surface_resistance_ohm: float | None = None,
    q_c: float | None = None,
) -> SplitCylinderLossResult:
    """MA-1 损耗：f0+Q_u → (εr, tanδ)，损耗按场解闭式能量分解。

        1/Q_u = p_e·tanδ + 1/Q_c；p_e = εr·I_s/(εr·I_s+I_a)（电能量样品占比，
    闭式积分见 :func:`_sc_solution`；j_s/j_a 定义已含空气区 A² 因子）。
    导体损耗 1/Q_c 三选一：
    (a) surface_resistance_ohm 给定 → 闭式积分：端板 |H_r|²（H_z=0 于壁，
        H_r ∝ A·β_a）+ 侧壁 |H_z|²（H_r=0 于 r=R，H_z ∝ J₀(x01)·Z(z)）::

            1/Q_c = (R_s/2)·P_norm/(ω·W_norm)
            W_norm = (I_s+I_a) + (β_s²J_s+β_a²J_a)/k_r²   ∝ W/(μ0H0²πR²J₀²/4)
            P_norm = 2(A β_a/k_r)² + (2/R)(I_s+I_a)       ∝ ∮|H_t|²/(H0²πR²J₀²)

    (b) q_c 给定 → 直采（标定/外模型注入口径）；
    (c) 都不给 → 1/Q_c=0（无导体修正口径，metadata 如实标注）。
    1/Q_u < 1/Q_c 时无物理解 → 显式报错（测量或修正模型不自洽）。
    """
    f0 = _positive(f0_hz, "f0_hz")
    q_u = _positive(q_u, "q_u")
    r_m = _positive(r_m, "r_m")
    ell_m = _positive(ell_m, "ell_m")
    d_m = _positive(d_m, "d_m")
    er_val = (
        split_cylinder_er_from_f0(f0, r_m, ell_m, d_m) if er is None else _positive(er, "er")
    )
    sol = _sc_solution(f0, er_val, r_m, ell_m, d_m)
    if q_c is not None and surface_resistance_ohm is not None:
        raise ValueError("q_c 与 surface_resistance_ohm 只能给一个（避免双修正口径）")
    inv_qc = 0.0
    q_c_out: float | None = None
    if q_c is not None:
        q_c_out = _positive(q_c, "q_c")
        inv_qc = 1.0 / q_c_out
    elif surface_resistance_ohm is not None:
        rs = _positive(surface_resistance_ohm, "surface_resistance_ohm")
        # 注：j_a 定义已含 A²（∫|Z_a'|²dz/β_a² = A²·(ℓ+sin2β_aℓ/2β_a)），不再另乘。
        w_norm = (sol.i_s + sol.i_a) + (
            sol.beta_s**2 * sol.j_s + sol.beta_a**2 * sol.j_a
        ) / (sol.k_r * sol.k_r)
        p_norm = 2.0 * (sol.amp_a * sol.beta_a / sol.k_r) ** 2 + 2.0 * (
            sol.i_s + sol.i_a
        ) / r_m
        inv_qc = (rs / 2.0) * p_norm / (2.0 * math.pi * f0 * w_norm)
        q_c_out = math.inf if inv_qc <= 0.0 else 1.0 / inv_qc
    inv_qu = 1.0 / q_u
    if inv_qu < inv_qc:
        raise ValueError(
            f"1/Q_u={inv_qu:.3e} < 1/Q_c={inv_qc:.3e}：无载 Q 高于导体损耗极限，"
            "测量或导体修正模型不自洽"
        )
    tan_d = (inv_qu - inv_qc) / sol.p_e
    if surface_resistance_ohm is not None:
        note = "surface_resistance_ohm 闭式（端板|H_r|²+侧壁|H_z|²）"
    elif q_c is not None:
        note = "q_c 直采（标定/外模型注入）"
    else:
        note = "1/Q_c=0（无导体修正口径）"
    return SplitCylinderLossResult(
        tan_d=tan_d,
        er=er_val,
        p_e=sol.p_e,
        q_u=q_u,
        q_c=q_c_out,
        metadata={
            "conductor_model": note,
            "beta_s": sol.beta_s,
            "beta_a": sol.beta_a,
            "amp_a": sol.amp_a,
        },
    )


@dataclass(frozen=True)
class SplitCylinderResult:
    """MA-1 分裂圆柱组合提取结果（f0+Q_u → εr+tanδ 一步口径）。"""

    er: float
    tan_d: float
    f0_hz: float
    p_e: float
    q_u: float
    q_c: float | None
    metadata: dict[str, Any] = field(default_factory=dict)


def split_cylinder_extract(
    f0_hz: float,
    q_u: float,
    r_m: float,
    ell_m: float,
    d_m: float,
    *,
    surface_resistance_ohm: float | None = None,
    q_c: float | None = None,
) -> SplitCylinderResult:
    """MA-1 一站口径：谐振频率+无载 Q → (εr, tanδ)（Janezic-Baker-Jarvis 场解）。"""
    loss = split_cylinder_tand_from_q(
        f0_hz,
        q_u,
        r_m,
        ell_m,
        d_m,
        surface_resistance_ohm=surface_resistance_ohm,
        q_c=q_c,
    )
    return SplitCylinderResult(
        er=loss.er,
        tan_d=loss.tan_d,
        f0_hz=f0_hz,
        p_e=loss.p_e,
        q_u=q_u,
        q_c=loss.q_c,
        metadata=loss.metadata,
    )


def spdr_extract(*args: Any, **kwargs: Any) -> None:
    """SPDR（分裂柱介质谐振器，Krupka 2001，[E5]）——round17 §六 明文**只登记不实现**。

    边界：SPDR 提取式 εr′≈1+Δf/f0·k、tanδ=Δ(1/Q)/p_e 中的 k（有效介质
    系数）与 p_e 均需**夹具标定曲线**（无标定数据的闭式回收不可信；精度
    数字在档标记"单源待证"）。真机亦属 round17 no-go（无仪器）。需要接入
    时先补 Krupka 2001 标定面与双源精度核验，再实现于本模块并同步测试锚。
    """
    raise NotImplementedError(
        "SPDR 按 round17 §六 边界只登记公式引用+'需标定曲线'，未实现"
        "（Krupka 2001，[E5]；精度数字单源待证；真机 no-go）"
    )


# ═══ MA-2：Hakki-Coleman/Courtney TE01p + 圆柱腔一阶微扰 ═════════════════════


@dataclass(frozen=True)
class CourtneyResult:
    """MA-2 Courtney 提取结果（confined 模型口径）。"""

    er: float
    tan_d: float
    f0_hz: float
    n_radial: int
    p_axial: int
    q_u: float
    q_c: float | None
    metadata: dict[str, Any] = field(default_factory=dict)


def courtney_f0_of_er(
    er: float, r_m: float, l_m: float, *, n_radial: int = 1, p_axial: int = 1
) -> float:
    """MA-2 正向（Courtney 闭式）：f0 = c/(2π)·√((x0n/R)²+(pπ/L)²)/√εr。"""
    er = _positive(er, "er")
    r_m = _positive(r_m, "r_m")
    l_m = _positive(l_m, "l_m")
    x0n = _j1_zero(n_radial)
    k_sq = (x0n / r_m) ** 2 + (p_axial * math.pi / l_m) ** 2
    return C0 / (2.0 * math.pi) * math.sqrt(k_sq / er)


def courtney_er_from_f0(
    f0_hz: float, r_m: float, l_m: float, *, n_radial: int = 1, p_axial: int = 1
) -> float:
    """MA-2 反演（Courtney 闭式）：εr = [(x0n/R)²+(pπ/L)²]/k0²。

    模式语义守卫：公式按**假定模式**反演——模式误指（把 TE021 当 TE011
    等）会得到系统性偏高的 εr；调用方应先用多模谐振谱定模式再调用
    （:func:`courtney_extract` 的 er_prior 提供 sanity 警告面）。
    """
    f0 = _positive(f0_hz, "f0_hz")
    r_m = _positive(r_m, "r_m")
    l_m = _positive(l_m, "l_m")
    if int(p_axial) < 1 or int(n_radial) < 1:
        raise ValueError("n_radial/p_axial 必须 ≥1（TE0mn 语义）")
    x0n = _j1_zero(n_radial)
    k0 = 2.0 * math.pi * f0 / C0
    return ((x0n / r_m) ** 2 + (p_axial * math.pi / l_m) ** 2) / (k0 * k0)


def courtney_tand_from_q(
    q_u: float, *, q_c: float | None = None, p_e: float = 1.0
) -> float:
    """MA-2 损耗：tanδ = (1/Q_u − 1/Q_c)/p_e（confined 缺省 p_e=1）。

    边界（如实登记）：confined 模型中理想端板 H_t=0（H_r ∝ sin(pπz/L) 在
    z=0,L 为零）→ 无臆造端板修正系数；真实端板损耗由 q_c 显式注入
    （标定或 Kobayashi-Katoh 类外模型，严格修正超出 P2/S 收口面）。
    """
    q_u = _positive(q_u, "q_u")
    p_e = _positive(p_e, "p_e")
    if not 0.0 < p_e <= 1.0:
        raise ValueError(f"p_e 必须在 (0,1]，实际 {p_e}")
    inv_qc = 0.0 if q_c is None else 1.0 / _positive(q_c, "q_c")
    inv_qu = 1.0 / q_u
    if inv_qu < inv_qc:
        raise ValueError(
            f"1/Q_u={inv_qu:.3e} < 1/Q_c={inv_qc:.3e}：测量或导体修正不自洽"
        )
    return (inv_qu - inv_qc) / p_e


def courtney_extract(
    f0_hz: float,
    q_u: float,
    r_m: float,
    l_m: float,
    *,
    n_radial: int = 1,
    p_axial: int = 1,
    q_c: float | None = None,
    er_prior: float | None = None,
) -> CourtneyResult:
    """MA-2 一站口径：TE01p 谐振频率+Q → (εr, tanδ)（Hakki-Coleman/Courtney）。

    er_prior 给定时做模式误指 sanity 检查（偏离 >30% 记入 metadata 警告，
    不阻断——先验本身可能错，判定权在调用方）。
    """
    er = courtney_er_from_f0(f0_hz, r_m, l_m, n_radial=n_radial, p_axial=p_axial)
    tan_d = courtney_tand_from_q(q_u, q_c=q_c)
    meta: dict[str, Any] = {
        "model": "courtney_confined_te01p",
        "p_e": 1.0,
        "q_c_injected": q_c is not None,
    }
    if er_prior is not None:
        prior = _positive(er_prior, "er_prior")
        dev = abs(er - prior) / prior
        meta["er_prior"] = prior
        meta["er_prior_dev"] = dev
        if dev > 0.30:
            meta["mode_misassignment_warning"] = (
                f"提取 εr={er:.4f} 偏离先验 {prior:.4f} 达 {dev:.0%}："
                "疑似 TE01p 模式误指（高次模当基模系统性偏高）"
            )
    return CourtneyResult(
        er=er,
        tan_d=tan_d,
        f0_hz=f0_hz,
        n_radial=int(n_radial),
        p_axial=int(p_axial),
        q_u=q_u,
        q_c=q_c,
        metadata=meta,
    )


def te01p_sample_filling_factor(
    r_m: float,
    l_m: float,
    v_sample_m3: float,
    r0_m: float,
    *,
    z0_m: float | None = None,
    spans_full_height: bool = False,
    n_radial: int = 1,
    p_axial: int = 1,
) -> float:
    """TE01p 圆柱腔样品电填充因子 ξ = ∫s ε0|E0|²dV / ∫c ε0|E0|²dV。

    TE01p 场：E_φ = E0·J₁(k_r r)·cos(pπz/L)，k_r = x0n/R；
    ∫c ε0|E|²dV = ε0E0²·(πR²L/2)·J₀(x0n)²（∫J₁²(k_r r)r dr = (R²/2)J₀²，
    J₁(x0n)=0、J₂(x0n)=−J₀(x0n)）。
    - 局域样品（默认）：ξ = J₁²(k_r r0)·cos²(pπ z0/L)·V_s / (πR²L·J₀²/2)；
    - 贯通全高棒（spans_full_height）：轴向平均 cos²=1/2。
    微扰有效性守卫：ξ ≤ 0.1（一阶定理要求样品电能量占比小；超限显式拒绝
    而非静默失真）。
    """
    from scipy.special import j0, j1

    r_m = _positive(r_m, "r_m")
    l_m = _positive(l_m, "l_m")
    v_s = _positive(v_sample_m3, "v_sample_m3")
    r0 = _positive(r0_m, "r0_m")
    if r0 >= r_m:
        raise ValueError(f"r0={r0} ≥ 腔半径 R={r_m}：样品在腔外")
    if v_s >= math.pi * r_m * r_m * l_m:
        raise ValueError("样品体积 ≥ 腔体积：微扰定理失效（不是'小样品'）")
    x0n = _j1_zero(n_radial)
    k_r = x0n / r_m
    num = float(j1(k_r * r0)) ** 2 * v_s
    if spans_full_height:
        num *= 0.5
    else:
        z0 = 0.5 * l_m if z0_m is None else float(z0_m)
        if not 0.0 <= z0 <= l_m:
            raise ValueError(f"z0={z0} 在 [0,L={l_m}] 之外")
        num *= math.cos(p_axial * math.pi * z0 / l_m) ** 2
    xi = num / (math.pi * r_m * r_m * l_m * float(j0(x0n)) ** 2 / 2.0)
    if not 0.0 < xi <= 0.1:
        raise ValueError(
            f"ξ={xi:.4g} 超出 (0, 0.1]：一阶微扰定理失效域（样品过大/位置场过弱）"
        )
    return xi


@dataclass(frozen=True)
class PerturbationResult:
    """MA-2 扰动口径提取结果（空腔 vs 载样腔一阶微扰）。"""

    er: float
    tan_d: float
    df_ratio: float          # (f0−fs)/f0 > 0
    d_inv_q: float           # 1/Qs − 1/Q0 > 0
    xi: float
    metadata: dict[str, Any] = field(default_factory=dict)


def cavity_perturbation_extract(
    f0_empty_hz: float,
    q_empty: float,
    f_loaded_hz: float,
    q_loaded: float,
    xi: float,
    *,
    mu_sample_rel: float = 1.0,
) -> PerturbationResult:
    """MA-2 扰动口径：一阶腔微扰定理（Waldron/Harrington 标准式）::

        (f0−fs)/f0 = (εr′−1)·ξ/2      → εr′ = 1 + 2(f0−fs)/(f0·ξ)
        Δ(1/Q) = εr′·tanδ·ξ           → tanδ = Δ(1/Q)/(εr′·ξ)

    ξ 见 :func:`te01p_sample_filling_factor`；μ 样品非 1 时 Δμ 项混入 εr′
    （mu_sample_rel≠1 仅登记警告——磁/介电分离需 TE/TM 双模联合反演，
    超出口径）。守卫：介质降频（fs<f0）、加损（1/Qs>1/Q0）、ξ∈(0,0.1]。
    """
    f0 = _positive(f0_empty_hz, "f0_empty_hz")
    q0 = _positive(q_empty, "q_empty")
    fs = _positive(f_loaded_hz, "f_loaded_hz")
    qs = _positive(q_loaded, "q_loaded")
    xi = float(xi)
    if not 0.0 < xi <= 0.1:
        raise ValueError(f"ξ={xi} 超出 (0,0.1]：一阶微扰定理失效域")
    if fs >= f0:
        raise ValueError(
            f"载样频率 fs={fs:.6g} ≥ 空腔 f0={f0:.6g}：介质样品必降频，"
            "响应非介质或模式跳变"
        )
    df_ratio = (f0 - fs) / f0
    if df_ratio <= 1e-12:
        raise ValueError(
            f"频移比 (f0−fs)/f0={df_ratio:.3e} ≈ 0：样品落在 E 节面（ξ 名义非零"
            "而场为零，如 p=1 时 z0=L/2）或样品过小——微扰信号不可测，"
            "检查样品位置/体积"
        )
    er = 1.0 + 2.0 * df_ratio / xi
    d_inv_q = 1.0 / qs - 1.0 / q0
    if d_inv_q <= 0.0:
        raise ValueError(
            f"1/Qs−1/Q0={d_inv_q:.3e} ≤ 0：有耗介质样品必加损，测量不自洽"
        )
    tan_d = d_inv_q / (er * xi)
    meta: dict[str, Any] = {
        "model": "cavity_perturbation_first_order",
        "mu_sample_rel": mu_sample_rel,
    }
    if abs(float(mu_sample_rel) - 1.0) > 1e-12:
        meta["mu_mixing_warning"] = (
            "mu_sample_rel≠1：εr′ 混入 Δμ 微扰项，磁/介电分离需 TE/TM 双模"
            "联合反演，本口径结果不可单独采信"
        )
    return PerturbationResult(
        er=er,
        tan_d=tan_d,
        df_ratio=df_ratio,
        d_inv_q=d_inv_q,
        xi=xi,
        metadata=meta,
    )


# ═══ MA-3：自由空间法（NRW 复用 + 时域门衔接 + LRR 口径 + 域守卫）═══════════


@dataclass(frozen=True)
class LRRDeembedResult:
    """LRR 口径去嵌结果（对称夹具 Thru 平方根 + 反射板核验）。"""

    s11: complex
    s21: complex
    fixture_s11: float           # 去嵌夹具端口失配 max|S_ii|（分支选择合理性）
    refl1_gamma: complex | None
    refl2_gamma: complex | None
    refl_ok: bool | None         # 反射板核验 |Γ|≈1（未提供反射板时 None）
    metadata: dict[str, Any] = field(default_factory=dict)


def _s_to_t(s: np.ndarray) -> np.ndarray:
    """S→T（波级联参数，约定 [b1;a1] = T·[a2;b2]，要求 S21≠0）。

    级联序：物理顺序 F1→X 的复合 T = T_F1 @ T_X（连接面 b2_F1=a1_X、
    a2_F1=b1_X 逐波代换可验）；T→S 逆变换 S11=B/D、S21=1/D、S22=−C/D、
    S12=det/D。
    """
    s11, s12 = s[0, 0], s[0, 1]
    s21, s22 = s[1, 0], s[1, 1]
    if abs(s21) < 1e-12:
        raise ValueError("S21≈0：T 参数（级联）表示不可用（截止/全反射网络）")
    inv = 1.0 / s21
    return np.array(
        [
            [s12 - s11 * s22 * inv, s11 * inv],
            [-s22 * inv, inv],
        ],
        dtype=complex,
    )


def _t_to_s(t: np.ndarray) -> np.ndarray:
    """T→S（:func:`_s_to_t` 的逆，要求 T22≠0 即 S21≠0）。"""
    a, b = t[0, 0], t[0, 1]
    c, d = t[1, 0], t[1, 1]
    if abs(d) < 1e-12:
        raise ValueError("T22≈0：S 表示不可用（级联参数病态）")
    det = a * d - b * c
    return np.array(
        [
            [b / d, det / d],
            [1.0 / d, -c / d],
        ],
        dtype=complex,
    )


def _fixture_from_thru(s_thru: np.ndarray) -> np.ndarray:
    """对称夹具分解：T_thru = T_F² → 取无源分支的夹具 S 矩阵。

    矩阵平方根经特征分解；特征值符号 ± 组合中选夹具端口失配最小者
    （整体取负不改变 S——标量在 S=B/D 型比值中消去，故只有相对符号两种
    候选）。无无源分支（Thru 等效半波类简并）显式报错——缩短夹具电长度
    或引入损耗后再测。
    """
    t_thru = _s_to_t(s_thru)
    eigval, eigvec = np.linalg.eig(t_thru)
    if float(np.min(np.abs(eigval))) < 1e-12:
        raise ValueError("Thru 矩阵有近零特征值：夹具级联病态，LRR 去嵌不可解")
    cands = []
    for sign in (1.0, -1.0):
        t_f = (
            eigvec
            @ np.diag(np.sqrt(eigval.astype(complex)) * sign)
            @ np.linalg.inv(eigvec)
        )
        s_f = _t_to_s(t_f)
        score = max(abs(s_f[0, 0]), abs(s_f[1, 1]), abs(s_f[1, 0]))
        cands.append((score, s_f))
    cands.sort(key=lambda item: item[0])
    score, s_f = cands[0]
    if score > 1.0 + 1e-6:
        raise ValueError(
            f"Thru 平方根无无源夹具分支（最小端口失配 |S|={score:.4f}）："
            "半波类简并或测量异常——缩短夹具电长度或加损耗后重测"
        )
    return s_f


def lrr_deembed(
    s_sample: np.ndarray,
    s_thru: np.ndarray,
    *,
    s_refl1: np.ndarray | None = None,
    s_refl2: np.ndarray | None = None,
    f_hz: float | None = None,
) -> LRRDeembedResult:
    """MA-3 LRR 口径去嵌：Line(Thru 空测)+Reflect×2（金属板）→ 样品真 S。

    8 项误差模型对称特例：M_T = F1·F2、F1=F2 ⇒ T_F = √T_thru（无源分支）；
    样品 T_x = T_F⁻¹·T_M·T_F⁻¹。反射板核验（Reflect 标准）：按误差模型
    m = e00 + e10e01·Γ/(1−e11·Γ) 反演 Γ（e00=S11_F、e11=S22_F、
    e10e01=S12_F·S21_F 互易积），|Γ|≈1（PEC 板）为口径自洽钉；平面偏移
    ΔL = (−arg Γ − π)/(2k0)（mod λ/2，f_hz 给定时报告，卷绕未消歧）。
    """
    s_sample = np.asarray(s_sample, dtype=complex)
    s_thru = np.asarray(s_thru, dtype=complex)
    for name, arr in (("s_sample", s_sample), ("s_thru", s_thru)):
        if arr.shape != (2, 2):
            raise ValueError(f"{name} 必须是 2×2 S 矩阵，实际 {arr.shape}")
    s_f = _fixture_from_thru(s_thru)
    t_f_inv = np.linalg.inv(_s_to_t(s_f))
    s_x = _t_to_s(t_f_inv @ _s_to_t(s_sample) @ t_f_inv)
    gamma1: complex | None = None
    gamma2: complex | None = None
    offsets: list[float] = []
    e00 = s_f[0, 0]
    e11 = s_f[1, 1]
    e_tr = s_f[1, 0] * s_f[0, 1]  # e10·e01（互易夹具）
    for idx, s_refl in enumerate((s_refl1, s_refl2)):
        if s_refl is None:
            continue
        m = np.asarray(s_refl, dtype=complex)[0, 0]
        denom = e_tr + e11 * (m - e00)
        if abs(denom) < 1e-12:
            raise ValueError("反射板反演分母≈0：夹具参数与反射测量不自洽")
        g = (m - e00) / denom
        if idx == 0:
            gamma1 = g
        else:
            gamma2 = g
        if f_hz is not None:
            k0 = 2.0 * math.pi * float(f_hz) / C0
            offsets.append((-float(np.angle(g)) - math.pi) / (2.0 * k0))
    gammas = [g for g in (gamma1, gamma2) if g is not None]
    refl_ok: bool | None = all(0.95 <= abs(g) <= 1.05 for g in gammas) if gammas else None
    meta: dict[str, Any] = {
        "fixture_s_matrix": s_f.tolist(),
        "model": "lrr_symmetric_thru_sqrt",
    }
    if gammas and f_hz is not None:
        meta["refl_plane_offset_m"] = offsets
        meta["refl_plane_note"] = "偏移按 mod λ/2 口径（相位卷绕未消歧）"
    return LRRDeembedResult(
        s11=complex(s_x[0, 0]),
        s21=complex(s_x[1, 0]),
        fixture_s11=float(max(abs(s_f[0, 0]), abs(s_f[1, 1]))),
        refl1_gamma=gamma1,
        refl2_gamma=gamma2,
        refl_ok=refl_ok,
        metadata=meta,
    )


def thickness_resonance_guard(
    d_m: float,
    f_hz: float,
    er_guess: float,
    *,
    tol_rad: float = 0.15,
) -> int:
    """MA-3 域守卫：厚度谐振点 d≈n·λg/2 预报拒绝（NRW S11→0 失稳带）。

    k0·√εr·d 距 nπ（n≥1）不足 tol_rad 时 NRW 的 K1=(S11²−S21²+1)/(2S11)
    以 1/S11 发散——以 er_guess **先验预报**并在提取前拒绝（既有
    nrw_extract 只在 S11 实测≈0 时被动抛错，此处是互补的前置守卫）。
    n=0（薄样品）不设限。返回最近谐振阶 n（仅供测试/日志），触发时抛
    ValueError。
    """
    d = _positive(d_m, "d_m")
    f = _positive(f_hz, "f_hz")
    er = _positive(er_guess, "er_guess")
    k0 = 2.0 * math.pi * f / C0
    x = k0 * math.sqrt(er) * d
    n_near = round(x / math.pi)
    if n_near < 1:
        return 0
    dist = abs(x - n_near * math.pi)
    if dist < tol_rad:
        raise ValueError(
            f"厚度谐振点：k0·√εr·d={x:.4f} 距 {n_near}π 仅 {dist:.4f} rad "
            f"(<{tol_rad})——d≈{n_near}·λg/2，S11→0 使 NRW K1 式发散失稳；"
            "改样品厚度或用 Baker-Jarvis/多厚度联合法"
        )
    return n_near


def lateral_coverage_guard(lateral_m: float, beam_diameter_m: float) -> None:
    """MA-3 样品保持器语义守卫：样品横向尺寸必须覆盖光斑（平面波照明前提）。

    自由空间法的 NRW 反演以平面波照射无限大平板为前提；样品小于光斑时
    边缘绕射污染 S 参数（提取系统性失真而非报错）——显式拒绝。
    """
    lat = _positive(lateral_m, "lateral_m")
    beam = _positive(beam_diameter_m, "beam_diameter_m")
    if lat < beam:
        raise ValueError(
            f"样品横向尺寸 {lat * 1e3:.2f} mm < 光斑直径 {beam * 1e3:.2f} mm："
            "平面波照明前提不成立（边缘绕射污染），加大样品或收紧聚焦"
        )


@dataclass(frozen=True)
class FreeSpaceResult:
    """MA-3 自由空间提取结果（NRW 复用 + 可选 LRR 去嵌/门控）。"""

    er: complex
    tan_d: float
    mu_r: complex
    branch_n: int
    refl: complex
    t_coef: complex
    deembedded: bool          # 是否经 LRR 口径去嵌
    metadata: dict[str, Any] = field(default_factory=dict)


def _slab_symmetric_matrix(s11: complex, s21: complex) -> np.ndarray:
    """单方向 (S11, S21) 测量对 → 2×2 矩阵（NRW 平板对称性补全）。

    NRW 模型对象=均匀各向同性平板（TEM 夹具），其 S 本征对称：
    S22=S11、S12=S21——补全与提取模型自洽，非信息臆造。
    """
    return np.array([[s11, s21], [s21, s11]], dtype=complex)


def free_space_extract(
    s11: complex,
    s21: complex,
    d_m: float,
    f_hz: float,
    *,
    er_guess: float = 1.0,
    s_thru: np.ndarray | None = None,
    s_refl1: np.ndarray | None = None,
    s_refl2: np.ndarray | None = None,
    lateral_m: float | None = None,
    beam_diameter_m: float | None = None,
    resonance_tol_rad: float = 0.15,
) -> FreeSpaceResult:
    """MA-3 一站口径：样品 S 参数 → (εr, tanδ)（NRW 复用 + LRR/守卫编排）。

    流程：域守卫（厚度谐振预报拒绝 + 样品/光斑覆盖）→ [s_thru 给定时 LRR
    对称去嵌（反射板核验入 metadata）] → dielectric_extract.nrw_extract
    复用（分支解析/无源性检查随其口径）→ tanδ = −Im(εr)/Re(εr)。
    """
    n_near = thickness_resonance_guard(d_m, f_hz, er_guess, tol_rad=resonance_tol_rad)
    if lateral_m is not None and beam_diameter_m is not None:
        lateral_coverage_guard(lateral_m, beam_diameter_m)
    s11_v = complex(s11)
    s21_v = complex(s21)
    deembedded = False
    meta: dict[str, Any] = {"resonance_guard_nearest_n": n_near}
    if s_thru is not None:
        lrr = lrr_deembed(
            _slab_symmetric_matrix(s11_v, s21_v),
            np.asarray(s_thru, dtype=complex),
            s_refl1=s_refl1,
            s_refl2=s_refl2,
            f_hz=f_hz,
        )
        s11_v = lrr.s11
        s21_v = lrr.s21
        deembedded = True
        meta["lrr"] = {"refl_ok": lrr.refl_ok, "fixture_s11": lrr.fixture_s11}
    nrw = nrw_extract(s11_v, s21_v, d_m, f_hz, er_guess=er_guess)
    er_c = complex(nrw.er)
    if abs(er_c.real) < 1e-15:
        raise ValueError("提取 εr 实部≈0：tanδ = −Im/Re 无定义（非物理解，检查测量）")
    if lateral_m is not None and beam_diameter_m is None:
        meta["holder_note"] = "给了样品横向尺寸但未给光斑直径：平面波覆盖性未核"
    return FreeSpaceResult(
        er=er_c,
        tan_d=-er_c.imag / er_c.real,
        mu_r=complex(nrw.mu_r),
        branch_n=nrw.branch_n,
        refl=nrw.refl,
        t_coef=nrw.t_coef,
        deembedded=deembedded,
        metadata=meta,
    )


def free_space_extract_network(
    net: Any,
    d_m: float,
    *,
    gate: Any | None = None,
    thru_net: Any | None = None,
    er_guess: float = 1.0,
    resonance_tol_rad: float = 0.15,
) -> FreeSpaceResult:
    """MA-3 网络口径：skrf.Network（2 端口）→ 门控（衔接 time_gating）→ 提取。

    gate 给定时先经 core/time_gating.gate_network 全元素门控（清洗天线间
    多径/边缘绕射——自由空间测量的标准清理步），再逐频点走
    :func:`free_space_extract`（NRW 逐点口径，分支随 er_guess 群延迟先验；
    聚合取各频点中位数，全剖面入 metadata——与 dielectric_extract 的
    逐点-中位口径一致）。thru_net 为空测（Line 标准）网络时走 LRR 口径
    去嵌（要求与样品网络同频率栅格）。
    """
    from rfauto.core.time_gating import gate_network

    nports = getattr(net, "nports", 0)
    if nports != 2:
        raise ValueError(f"net 必须是 2 端口，实际 nports={nports!r}")
    if gate is not None:
        net = gate_network(net, gate)
    f_hz = np.asarray(net.frequency.f, dtype=float)
    s11_arr = np.asarray(net.s[:, 0, 0], dtype=complex)
    s21_arr = np.asarray(net.s[:, 1, 0], dtype=complex)
    if f_hz.size == 0:
        raise ValueError("net 无频点")
    s_thru_list: list[np.ndarray] | None = None
    if thru_net is not None:
        if thru_net.frequency.f.shape != f_hz.shape or not np.allclose(
            np.asarray(thru_net.frequency.f, dtype=float), f_hz, rtol=0.0, atol=1e-6
        ):
            raise ValueError("thru_net 与样品网络频率栅格不一致（对拍前提）")
        s_thru_list = [np.asarray(thru_net.s[i], dtype=complex) for i in range(f_hz.size)]
    ers: list[complex] = []
    tds: list[float] = []
    branches: list[int] = []
    skipped: list[dict[str, Any]] = []
    for i in range(f_hz.size):
        try:
            res = free_space_extract(
                s11_arr[i],
                s21_arr[i],
                d_m,
                float(f_hz[i]),
                er_guess=er_guess,
                s_thru=None if s_thru_list is None else s_thru_list[i],
                resonance_tol_rad=resonance_tol_rad,
            )
        except ValueError as exc:
            # 带缘剔点口径（实测标准做法）：门控/变换的带缘伪影使少数频点
            # 违反无源性/守卫——逐点跳过并全量留痕，不静默（幸存率门在尾部）。
            skipped.append(
                {"index": i, "freq_hz": float(f_hz[i]), "error": str(exc)[:160]}
            )
            continue
        ers.append(res.er)
        tds.append(res.tan_d)
        branches.append(res.branch_n)
    if len(ers) * 2 < f_hz.size:
        raise ValueError(
            f"可提取频点 {len(ers)}/{f_hz.size} 不足一半：数据或守卫面大面积失败，"
            "拒绝中位数聚合（skipped 明细见 metadata 口径）"
        )
    er_arr = np.asarray(ers)
    meta_out: dict[str, Any] = {
        "er_profile_real": er_arr.real.tolist(),
        "er_profile_imag": er_arr.imag.tolist(),
        "tan_d_profile": tds,
        "branch_profile": branches,
        "gated": gate is not None,
        "aggregation": "median_over_frequency",
    }
    if skipped:
        meta_out["skipped_points"] = skipped
        meta_out["skipped_note"] = (
            "带缘/守卫跳过频点全量留痕（实测带缘剔点标准做法，非静默剔除）"
        )
    return FreeSpaceResult(
        er=complex(float(np.median(er_arr.real)), float(np.median(er_arr.imag))),
        tan_d=float(np.median(tds)),
        mu_r=complex(1.0, 0.0),
        branch_n=int(np.median(branches)),
        refl=0j,
        t_coef=0j,
        deembedded=s_thru_list is not None,
        metadata=meta_out,
    )


# ═══ MA-4：FPOR 分裂柱谐振器（薄样品微扰闭式，登记级；ge8b Wave B 席 B9）═══
#
# 规格：研究扩充 round17 §六 :186「MA-4 FPOR
# （P3/登记）：confocal 高斯束公式面；真机 no-go」+ 席 B9 任务书「分裂柱
# 谐振器微扰闭式+登记边界声明（真机面 no-go 维持）」。
#
# 模型（均匀场串联层精确口径；出处=一阶谐振腔微扰定理的均匀场极限，
# 与本模块头部 MA-2 扰动口径 (f0−fs)/f0=(εr′−1)·ξ/2 同族——ξ=x、
# 均匀场下该式为**精确**串联层结果而非一阶近似）：
#
#     ε_eff(x, εr) = 1 + x·(εr − 1)，  x = t_sample/gap（样品填充因子）
#     f_s = f_0/√ε_eff                                        （精确，模型内）
#     εr = 1 + ((f0/f_s)² − 1)/x                              （精确反演）
#
# 一阶 k 形（SPDR/FPOR 文献通称 εr′≈1+k·Δf/f₀，Krupka 2001 口径）：
# 均匀场极限下 k = 2/x **可推导**（√ 泰勒展开），非臆造系数——与
# :func:`spdr_extract` 的"k 需夹具标定"边界相容：真实夹具场非均匀，
# k 偏离 2/x 由标定曲线承担，本模块只交付均匀场极限的**可推导值**。
#
# 边界（如实，#122）：真机 no-go 维持（无仪器）；p_e 非均匀场修正需夹具
# 标定（无标定数据的闭式回收不可信，:func:`spdr_extract` 同口径）——
# 损耗面 p_e 为**必填**标定量，均匀场模型值仅作参考输出。


def fpor_fill_factor(t_sample_m: float, gap_m: float) -> float:
    """样品填充因子 x = t/gap ∈ (0,1)（两分裂柱端面间隙内的薄片）。"""
    t = _positive(t_sample_m, "t_sample_m")
    g = _positive(gap_m, "gap_m")
    if t >= g:
        raise ValueError(
            f"样品厚 {t:.4g}m 必须 < 柱间隙 {g:.4g}m（薄样品口径）")
    return t / g


def fpor_fshift(f0_hz: float, er: float, t_sample_m: float,
                gap_m: float) -> float:
    """MA-4 正向：空腔谐振 f0 + 样品 (εr, t) → 载样谐振 f_s（均匀场精确）。

    f_s = f0/√(1+x(εr−1))；εr>1 恒有 f_s<f0（介质加载降频，单调守卫）。
    """
    f0 = _positive(f0_hz, "f0_hz")
    er = _positive(er, "er")
    x = fpor_fill_factor(t_sample_m, gap_m)
    eps_eff = 1.0 + x * (er - 1.0)
    return f0 / math.sqrt(eps_eff)


def fpor_er_from_fshift(f0_hz: float, f_s_hz: float, t_sample_m: float,
                        gap_m: float) -> float:
    """MA-4 反演：f0/f_s → εr（均匀场精确；f_s≥f0 即模式误指/测量异常）。"""
    f0 = _positive(f0_hz, "f0_hz")
    f_s = _positive(f_s_hz, "f_s_hz")
    x = fpor_fill_factor(t_sample_m, gap_m)
    if f_s >= f0:
        raise ValueError(
            f"f_s={f_s:.6g} ≥ f0={f0:.6g}：介质样品只能降频（εr>1）——"
            "模式误指或测量异常")
    return 1.0 + ((f0 / f_s) ** 2 - 1.0) / x


def fpor_er_first_order(f0_hz: float, f_s_hz: float, t_sample_m: float,
                        gap_m: float) -> float:
    """一阶 k 形：εr ≈ 1 + 2(f0−f_s)/(f0·x)（均匀场极限 k=2/x，可推导）。

    与 :func:`fpor_er_from_fshift` 精确式的偏差 = O(x(εr−1)) 二阶项；
    测试钉二者一致性随 x(εr−1)→0 收敛（SPDR 边界"k 需标定"的均匀场
    极限锚）。
    """
    f0 = _positive(f0_hz, "f0_hz")
    f_s = _positive(f_s_hz, "f_s_hz")
    x = fpor_fill_factor(t_sample_m, gap_m)
    if f_s >= f0:
        raise ValueError(f"f_s={f_s:.6g} ≥ f0={f0:.6g}：非物理（εr>1 降频）")
    return 1.0 + 2.0 * (f0 - f_s) / (f0 * x)


def fpor_pe_uniform_field(er: float, t_sample_m: float, gap_m: float) -> float:
    """均匀场模型电能量占比 p_e = x·εr/ε_eff（参考输出；真实夹具 p_e
    须标定，非均匀场修正不在本口径）。"""
    er = _positive(er, "er")
    x = fpor_fill_factor(t_sample_m, gap_m)
    eps_eff = 1.0 + x * (er - 1.0)
    return x * er / eps_eff


def fpor_tand_from_q(q_s: float, q_0: float, p_e: float) -> float:
    """MA-4 损耗：tanδ = (1/Q_s − 1/Q_0)/p_e（p_e 必填标定量，无臆造缺省）。

    q_s=载样有载 Q、q_0=空腔参考 Q；p_e∈(0,1]（真实夹具由标定给出；
    均匀场模型参考值见 :func:`fpor_pe_uniform_field`）。
    """
    qs = _positive(q_s, "q_s")
    q0 = _positive(q_0, "q_0")
    pe = _positive(p_e, "p_e")
    if not 0.0 < pe <= 1.0:
        raise ValueError(f"p_e 必须在 (0,1]，实际 {pe}")
    inv_qs, inv_q0 = 1.0 / qs, 1.0 / q0
    if inv_qs < inv_q0:
        raise ValueError(
            f"1/Q_s={inv_qs:.3e} < 1/Q_0={inv_q0:.3e}：载样损耗低于空腔参考"
            "不自洽（测量异常）")
    return (inv_qs - inv_q0) / pe
