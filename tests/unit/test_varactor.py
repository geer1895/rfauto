"""core/varactor.py 闭式综合内核单测（M-5 变容二极管调谐 BPF，首个半有源模板）。

判据纪律（任务书原文）：
- 合成回收（已知 C(V)→f0(V) 解析对照 rel 1e-9）：往返恒等式 + 独立手算解析锚；
- 插损单调性物理门：Q_v↓ ⇒ IL↑ 单调数组断言（精确 ABCD 电路上验证）；
- 能量份额闭式：独立代数锚（βL=3π/4 处 Q_u/Q_v = 1/2+3π/4，sin(3π/2)=−1）。

裁判口径：数值断言一律对计算函数（不匹配渲染文本）；解析锚独立于被测
实现推导（#118：小步长/独立来源，非自身推导自证）。
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from rfauto.core.varactor import (
    C0,
    abrupt_junction_capacitance_pf,
    bias_for_capacitance_v,
    capacitor_energy_fraction,
    loaded_line_f0_limits_ghz,
    midband_insertion_loss_db,
    resonator_qu_combined,
    tuning_bias_plan,
    varactor_box_geo_capacitance_pf,
    varactor_line_f0_ghz,
    varactor_load_capacitance_pf,
    varactor_q,
    varactor_resonator_qu,
    varactor_series_r_for_q,
    varactor_tap_frac_from_qe_loaded,
    varactor_tap_node_frac,
    varactor_tap_qe_loaded,
)

# 测试几何（非名义；固定值便于独立解析锚）：L=32mm、εeff=2.7862、Z0=50Ω
L_MM = 32.0
EREFF = 2.7862
Z0 = 50.0


def _folded_matrix() -> list:
    """N=3/FBW5%/RL20dB folded 耦合矩阵（与 fake/裁判同源综合链）。"""
    from rfauto.core.synthesis import synthesize_bpf_model

    synth = synthesize_bpf_model(order=3, f0_ghz=2.5, fbw=0.05, rl_db=20.0,
                                 topology="folded")
    assert synth["ok"], synth.get("errors")
    return synth["coupling_matrix"]


# ── 突变结 C-V ───────────────────────────────────────────────────────────────

def test_abrupt_junction_formula_matches_hand_computed():
    # C(V)=Cj0/√(1+V/φ)：V=3.6V、φ=0.9 → √(1+4)=√5；独立手算锚
    c = abrupt_junction_capacitance_pf(3.6, 1.2, 0.9)
    assert c == pytest.approx(1.2 / math.sqrt(5.0), rel=1e-12)


def test_abrupt_junction_zero_bias_is_cj0():
    assert abrupt_junction_capacitance_pf(0.0, 0.85, 0.75) == 0.85


def test_capacitance_bias_round_trip_exact():
    # 往返回收：C(V)→V(C) 逐位（rel 1e-9 判据口径，实测远严）
    for v in (0.0, 0.5, 1.7, 3.6, 5.0, 10.0, 30.0):
        c = abrupt_junction_capacitance_pf(v, 1.0, 0.9)
        v_rt = 0.0 if c == 1.0 else bias_for_capacitance_v(c, 1.0, 0.9)
        assert v_rt == pytest.approx(v, rel=1e-9, abs=0.0), v


def test_bias_for_capacitance_domain_guards():
    # c>cj0 需正偏（不在反偏闭式域）与非法入参显式报错
    with pytest.raises(ValueError, match="正偏"):
        bias_for_capacitance_v(1.01, 1.0, 0.9)
    with pytest.raises(ValueError):
        bias_for_capacitance_v(0.0, 1.0, 0.9)
    with pytest.raises(ValueError):
        abrupt_junction_capacitance_pf(-0.1, 1.0, 0.9)


# ── 变容管 Q ────────────────────────────────────────────────────────────────

def test_varactor_q_round_trip():
    # (f,Q,C)→Rs→Q 往返回收（rel 1e-9）
    rs = varactor_series_r_for_q(2.5, 120.0, 0.45)
    assert varactor_q(2.5, 0.45, rs) == pytest.approx(120.0, rel=1e-9)


def test_varactor_q_formula_anchor():
    # Q=1/(2πfCRs) 独立手算锚：f=2.5GHz、C=0.5pF、Rs=1Ω → 1/(2π·2.5e9·5e-13)
    q = varactor_q(2.5, 0.5, 1.0)
    assert q == pytest.approx(1.0 / (2.0 * math.pi * 2.5e9 * 5.0e-13), rel=1e-12)


# ── 主谐振方程 ──────────────────────────────────────────────────────────────

def test_load_capacitance_closed_form_anchor():
    # 独立解析锚：f = 0.9·f_λ/2 ⇒ βL = 0.9π，C = −tan(0.9π)/(ωZ0)
    f_hi = loaded_line_f0_limits_ghz(L_MM, EREFF)[1]
    f = 0.9 * f_hi
    beta_l = 0.9 * math.pi
    omega = 2.0 * math.pi * f * 1e9
    c_expect = -math.tan(beta_l) / (omega * Z0) * 1e12
    assert varactor_load_capacitance_pf(f, L_MM, Z0, EREFF) \
        == pytest.approx(c_expect, rel=1e-12)


def test_f0_capacitance_round_trip_exact():
    # 往回收判据（rel 1e-9）：f→C→f 逐位（brentq xtol=1e-12，实测 ~1e-15）
    for frac in (0.55, 0.7, 0.9, 0.97):
        _, f_hi = loaded_line_f0_limits_ghz(L_MM, EREFF)
        f = f_hi * frac
        c = varactor_load_capacitance_pf(f, L_MM, Z0, EREFF)
        f_rt = varactor_line_f0_ghz(c, L_MM, Z0, EREFF)
        assert f_rt == pytest.approx(f, rel=1e-9, abs=0.0), frac


def test_f0_monotone_decreasing_in_c():
    # 调谐方向物理：C↑ ⇒ f0↓（单调）
    cs = [0.05, 0.2, 0.45, 0.8, 1.5]
    fs = [varactor_line_f0_ghz(c, L_MM, Z0, EREFF) for c in cs]
    assert all(f2 < f1 for f1, f2 in pairwise(fs))


def test_f0_limits_recover_unloaded_and_quarter_wave():
    # C→0 ⇒ 无载 λ/2 锚（窗上沿）；C 大 ⇒ 逼近 λ/4 极限（窗下沿）
    f_lo, f_hi = loaded_line_f0_limits_ghz(L_MM, EREFF)
    assert f_hi == pytest.approx(C0 / (2.0 * L_MM * 1e-3 * math.sqrt(EREFF))
                                 / 1e9, rel=1e-12)
    assert f_lo * 2.0 == pytest.approx(f_hi, rel=1e-12)
    assert varactor_line_f0_ghz(0.0, L_MM, Z0, EREFF) == pytest.approx(
        f_hi, rel=1e-12)
    # C=100µF ⇒ ωCZ0≫1 ⇒ βL→π/2⁺（1e-4 内逼近窗下沿，O(1/ωCZ0²) 收敛）
    assert varactor_line_f0_ghz(1.0e5, L_MM, Z0, EREFF) == pytest.approx(
        f_lo, rel=1e-4)


def test_master_equation_window_guards():
    # 窗外目标显式报错（不低于 λ/4、不高于 λ/2——不外推不 clamp）
    f_lo, f_hi = loaded_line_f0_limits_ghz(L_MM, EREFF)
    with pytest.raises(ValueError, match="装载窗"):
        varactor_load_capacitance_pf(f_hi * 1.01, L_MM, Z0, EREFF)
    with pytest.raises(ValueError, match="装载窗"):
        varactor_load_capacitance_pf(f_lo * 0.99, L_MM, Z0, EREFF)


# ── 能量份额闭式与谐振器 Q ──────────────────────────────────────────────────

def test_qu_over_qv_independent_algebraic_anchor():
    # 独立代数锚：βL=3π/4 ⇒ sin(2βL)=sin(3π/2)=−1 ⇒ Q_u/Q_v = 1/2 + 3π/4
    beta_l = 0.75 * math.pi
    q_v = 55.0
    assert varactor_resonator_qu(q_v, beta_l) \
        == pytest.approx(q_v * (0.5 + 0.75 * math.pi), rel=1e-12)
    # 份额与 Q 互逆自洽
    eta = capacitor_energy_fraction(beta_l)
    assert eta * varactor_resonator_qu(q_v, beta_l) == pytest.approx(
        q_v, rel=1e-12)


def test_energy_fraction_vanishes_at_window_edges():
    # 两窗端 η_C→0（C→0：能量退不出电容；C→∞：电压节点在装载端）
    for beta_l in (math.pi / 2.0 * (1.0 + 1e-6), math.pi * (1.0 - 1e-6)):
        assert capacitor_energy_fraction(beta_l) < 1e-4


def test_combined_qu_harmonic_identity():
    q_l, q_v = 800.0, 300.0
    qu = resonator_qu_combined(q_l, q_v)
    assert qu == pytest.approx(1.0 / (1.0 / q_l + 1.0 / q_v), rel=1e-15)
    assert qu < min(q_l, q_v)


# ── 带心插损（Cameron 耦合矩阵 + 耗散对角扩展）───────────────────────────────

def test_midband_il_lossless_matches_public_evaluator():
    # 独立双路径（#118）：无耗（Q=inf）与 coupling_matrix_response 在 f0 处
    # 逐位一致（后者是 hairpin/coupled_bpf fake 的既有裁判公共接口）
    from rfauto.core.calculators import coupling_matrix_response

    matrix = _folded_matrix()
    il = midband_insertion_loss_db(matrix, [float("inf")] * 3)
    assert il == 0.0
    resp = coupling_matrix_response(freq_ghz=[2.5], f0_ghz=2.5, fbw=0.05,
                                    matrix=matrix)
    s21 = resp["s_matrix"][0][1][0]
    s21_cplx = complex(s21[0], s21[1])
    assert -20.0 * math.log10(abs(s21_cplx)) == pytest.approx(il, abs=1e-9)


def test_midband_il_positive_and_monotone_in_qv():
    # 插损单调性物理门（任务书判据）：Q_v↓ ⇒ Q_u↓ ⇒ IL↑ 单调数组
    beta_l = 0.75 * math.pi
    matrix = _folded_matrix()
    q_vs = [200.0, 100.0, 50.0, 25.0, 12.0]
    ils = [midband_insertion_loss_db(
        matrix, [varactor_resonator_qu(q, beta_l)] * 3) for q in q_vs]
    assert all(il > 0.0 for il in ils)
    assert all(il2 > il1 for il1, il2 in pairwise(ils))


# ── 调谐综合服务面 ──────────────────────────────────────────────────────────

def test_tuning_bias_plan_recovers_design_point():
    # 三档偏压计划：f 目标降序 ⇒ C 升序 ⇒ V 降序；回收判据 f(C(V))=f_target
    cj0, phi = 1.0, 0.9
    targets = [2.6, 2.5, 2.4]
    plan = tuning_bias_plan(targets, cj0, phi, L_MM, Z0, EREFF)
    assert [r["f_target_ghz"] for r in plan] == targets
    assert all(r["feasible"] for r in plan)
    cs = [r["c_req_pf"] for r in plan]
    vs = [r["v_bias_v"] for r in plan]
    assert all(c2 > c1 for c1, c2 in pairwise(cs))
    assert all(v2 < v1 for v1, v2 in pairwise(vs))
    for row in plan:
        f_rt = varactor_line_f0_ghz(row["c_req_pf"], L_MM, Z0, EREFF)
        assert f_rt == pytest.approx(row["f_target_ghz"], rel=1e-9)
        v_rt = bias_for_capacitance_v(row["c_req_pf"], cj0, phi)
        assert v_rt == pytest.approx(row["v_bias_v"], rel=1e-12)


def test_tuning_bias_plan_infeasible_reported_honestly():
    # 目标高于无载锚（无需电容）与 C 需求超 cj0（需正偏）都如实 infeasible
    _, f_hi = loaded_line_f0_limits_ghz(L_MM, EREFF)
    plan = tuning_bias_plan([f_hi * 1.01, 0.9 * f_hi], 0.01, 0.9,
                            L_MM, Z0, EREFF)
    assert plan[0]["feasible"] is False and plan[0]["c_req_pf"] is None
    # 0.9·f_hi 的 C 需求远大于 cj0=0.01pF → V 反解出域 = 不可行
    assert plan[1]["feasible"] is False and plan[1]["v_bias_v"] is None


def test_tuning_bias_plan_il_increases_as_bias_raises_c():
    # IL-调谐联动：低 V ⇒ 大 C ⇒ 深装载（η_C 大）⇒ 同 Q_v 下 Q_u 低 ⇒ IL 高
    plan = tuning_bias_plan([2.3, 2.5, 2.65], 1.0, 0.9, L_MM, Z0, EREFF,
                            rs_ohm=1.2, q_line=500.0, order=3)
    ils = [r["il_db"] for r in plan]
    assert all(r["feasible"] for r in plan)
    assert all(i is not None and i > 0.0 for i in ils)
    # 2.3GHz（低 V 大 C）与 2.65GHz（高 V 小 C）比较——方向单调
    assert ils[0] > ils[-1]


# ── 抽头外耦 loaded 廓线（P0 修复 2026-09-29；独立锚=审计表）────────────────

# 审计三档电长度与节点位（runs/varactor_smoke/model_audit_verdict.md 独立来源）
_AUDIT_BETA_L = (2.6112, 2.8050, 2.9115)
_AUDIT_NODE = (0.3984, 0.4400, 0.4605)


def test_tap_node_frac_matches_audit_table():
    # 节点位 τ_node=1−π/(2βL)：审计表三档逐值（独立来源锚，非实现自证）
    for bl, node in zip(_AUDIT_BETA_L, _AUDIT_NODE, strict=True):
        assert varactor_tap_node_frac(bl) == pytest.approx(node, abs=5e-5)


def test_tap_qe_loaded_round_trip_bitwise():
    # 正问题 τ→Qe 与反问题 Qe→τ 往返（任务书"逐位"口径=超越函数链 ≤2ulp，
    # 实测差 1.7e-16；hairpin 同族先例 rel 1e-9）；Qe 回收方向同精度
    for bl in (*_AUDIT_BETA_L, math.pi * 2.5 / 2.8):
        for tau in (0.10, 0.20, 0.280407, 0.330119, 0.354627, 0.39):
            qe = varactor_tap_qe_loaded(tau, bl)
            tau_back = varactor_tap_frac_from_qe_loaded(qe, bl)
            assert tau_back == pytest.approx(tau, rel=5e-15), (bl, tau)
        qe_target = 17.07
        tau0 = varactor_tap_frac_from_qe_loaded(qe_target, bl)
        assert varactor_tap_qe_loaded(tau0, bl) \
            == pytest.approx(qe_target, rel=5e-15)


def test_tap_qe_loaded_unloaded_degeneration_bitwise():
    # 无载退化钉：βL→π 时回 hairpin 原文 sec² 公式（cos 平移恒等；浮点余量
    # 1e-10，实测 ~1e-12——π 非精确浮点数的宗量位移）
    from rfauto.core.coupled_microstrip import hairpin_qe_from_tap_frac

    bl_pi = math.pi * (1.0 - 1e-12)
    for tau in (0.15, 0.30, 0.401892, 0.45):
        loaded = varactor_tap_qe_loaded(tau, bl_pi)
        assert loaded == pytest.approx(hairpin_qe_from_tap_frac(tau), rel=1e-10)


def test_tap_frac_three_tier_synthetic_referee():
    # 合成裁判（任务书钉式）：Qe=17.07 在审计三档 βL → 反推 τ=0.280/0.330/0.355
    for bl, expected in zip(_AUDIT_BETA_L, (0.280, 0.330, 0.355), strict=True):
        tau = varactor_tap_frac_from_qe_loaded(17.07, bl)
        assert tau == pytest.approx(expected, abs=5e-4), bl
    # 名义设计点自洽：βL=π·f0/f_unloaded（臂长=λg/2 恒等式）→ 设计链名义 τ
    tau_nom = varactor_tap_frac_from_qe_loaded(17.0689, math.pi * 2.5 / 2.8)
    assert round(tau_nom, 6) == 0.330119


def _qe_admittance_referee(tau: float, beta_l0: float,
                           df: float = 1e-6) -> float:
    """独立数值裁判（#118 同法，hairpin 无载版单测同构）：抽头结电纳
    B(f)/Yr = tan(βL(1−τ)) + (κ+tan(βLτ))/(1−κ·tan(βLτ))，κ=ωC·Zr=−tan(βL)
    （主谐振方程工作点），b=(f0/2)·dB/df，Qe=b·Z0。与闭式实现零共享路径。"""
    kap0 = -math.tan(beta_l0)

    def b_over_yr(s: float) -> float:
        u = beta_l0 * s
        kap = kap0 * s
        return (math.tan(u * (1.0 - tau))
                + (kap + math.tan(u * tau)) / (1.0 - kap * math.tan(u * tau)))

    dbds = (b_over_yr(1.0 + df) - b_over_yr(1.0 - df)) / (2.0 * df)
    # Qe=b·Z0，b=(f0/2)·dB/df，B=B_over_Yr/Zr（Z0=Zr=50 → Z0/Zr=1）
    return 0.5 * dbds * (50.0 / 50.0)


def test_tap_qe_loaded_vs_distributed_admittance_referee():
    # 独立分布参数裁判：廓线形状成立，π/2 前因子=预声明一阶替代——比值
    # （裁判/闭式）βL=π 处 →1（≤1e-6）、名义带内 0.970~0.997（实测逐档）、
    # 深装载 βL=2.0 放大至 0.757（审计 P0 行"prefactor 为一阶替代"定量钉）
    for bl, tau in ((2.0, 0.15),                       # 深装载：τ 须在节点前
                    (2.6112, 0.33), (2.8050, 0.33), (2.9115, 0.33)):
        num = _qe_admittance_referee(tau, bl)
        closed = varactor_tap_qe_loaded(tau, bl)
        ratio = num / closed
        if bl > 2.5:
            assert 0.96 < ratio <= 1.0 + 1e-9, bl
        else:
            assert 0.75 < ratio < 0.96, bl      # 深装载替代误差放大（预声明）
    bl_pi = math.pi * (1.0 - 1e-12)
    num = _qe_admittance_referee(0.33, bl_pi)
    closed = varactor_tap_qe_loaded(0.33, bl_pi)
    assert abs(num / closed - 1.0) <= 1e-6      # 无载极限前因子替代误差消失


def test_tap_qe_loaded_branch_and_domain_guards():
    # branch B 定义域守卫：τ 出节点/出 C 端、βL 出装载窗、Qe 过低反解 τ≤0
    for bl in (math.pi / 2.0, math.pi, 1.0):
        with pytest.raises(ValueError, match="π/2"):
            varactor_tap_qe_loaded(0.3, bl)
        with pytest.raises(ValueError, match="π/2"):
            varactor_tap_frac_from_qe_loaded(17.0, bl)
    bl = 2.805
    tau_node = varactor_tap_node_frac(bl)
    with pytest.raises(ValueError, match="branch B"):
        varactor_tap_qe_loaded(tau_node, bl)            # 节点上=无耦不可达
    with pytest.raises(ValueError, match="branch B"):
        varactor_tap_qe_loaded(-0.01, bl)               # C 端臂外
    with pytest.raises(ValueError, match="可达下限"):
        varactor_tap_frac_from_qe_loaded(0.5, bl)       # Qe<π/2 下限（acos 出域）
    with pytest.raises(ValueError, match="C 端臂外"):
        # Qe 高于下限但仍低到反解 τ≤0（βL=2.805 时 τ→0 阈 Qe≈1.763：
        # acos(√c2) ≤ π−βL=0.3366rad）
        varactor_tap_frac_from_qe_loaded(1.75, bl)


def test_box_geo_capacitance_pf_parallel_plate_anchor():
    # C_geo=ε0·εr·WF²/H_SUB 独立手算锚（审计 0.0788pF）：名义 WF=1.1117/
    # H=0.508/εr=3.66 → 0.078839（rel 1e-3 对审计四位小数）；守卫与量纲
    c_geo = varactor_box_geo_capacitance_pf(1.1117, 0.508, 3.66)
    assert c_geo == pytest.approx(8.8541878128e-12 * 3.66 * 1.1117e-3 ** 2
                                  / 0.508e-3 * 1e12, rel=1e-12)
    assert c_geo == pytest.approx(0.0788, abs=1e-3)     # 审计表锚
    # 三档 C_literal=C(V)−C_geo 全为正（v0.5/v3.6342/v10 设计 C）
    for c_design in (0.802, 0.4455, 0.2873):
        assert c_design - c_geo > 0.0
    with pytest.raises(ValueError):
        varactor_box_geo_capacitance_pf(0.0, 0.508, 3.66)
