"""F-L 第 3 步振荡器综合内核单测（研究扩充 round6 §二 F-L 第 3 步判据）。

裁判口径（#118，双路径/独立来源，不自证）：
- 频率回收：正问题解析回收（测试内独立公式，与内核共享常量不共享表达
  序）+ 反设计回路恒等（f→元件值→f，rel 1e-12）；
- 起振恒等式：gm·R_p=2 恰临界 margin==0.0（逐位，取浮点精确对
  (gm,r_p)=(2.0,1.0)/(0.5,4.0)）；R_in=−R_res 恰临界 margin==0.0（逐位）；
- Leeson 双路径：①Δf→∞ 浮点极限下 lin==floor_lin（逐位）+ 有限远
  rel 1e-9；②Δf=f0/(2Q_L) 处 1/f² 括号=2.0（逐位）；③渐近段链 vs
  clock_noise.build_power_law_segments（独立实现路径）同网格 rel 1e-9；
  ④精确积分 vs scipy.integrate.quad 数值求积（第三方路径）rel 1e-6；
  ⑤dB 线性插值高密度网格经 clock_noise 积分器闭环（收敛级精度）。
- DRO：β=0→Q_L==Q_0、β=1→Q_L==Q_0/2（逐位）。

Leeson 段链与精确式的差异属渐近模型固有误差（内核诚实边界②），测试
只钉拐角衔接点与 clock_noise 路径一致性，不钉过渡带内数值。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import clock_noise
from rfauto.core import oscillator_synthesis as osc
from rfauto.service import oscillator_synthesis_service as svc

# ─── 共用参数（Leeson 族，测试内独立写出供各判据复用）────────────────────────
F0 = 2.4e9
Q_L = 25.0
FLICK = 1.0e5
NF = 2.0
P_S = 1.0e-3
T0 = 290.0
K_B = 1.380649e-23  # SI 精确定义值（CODATA 2018）
F_HALF = F0 / (2.0 * Q_L)  # 4.8e7（与内核同算式 → 同 float）
F_FLICK = FLICK / 2.0  # 5.0e4


# ─── 1. Colpitts ─────────────────────────────────────────────────────────────


def test_colpitts_frequency_analytic_recycle():
    l_h, c1, c2 = 10e-9, 10e-12, 40e-12
    c_eq_ref = c1 * c2 / (c1 + c2)  # 测试独立乘积式（内核走串联口径）
    f_ref = 1.0 / (2.0 * math.pi * math.sqrt(l_h * c_eq_ref))
    assert osc.colpitts_frequency(l_h, c1, c2) == pytest.approx(f_ref, rel=1e-12)


def test_colpitts_round_trip_design():
    l_h, c1, c2 = 10e-9, 10e-12, 40e-12
    f0 = osc.colpitts_frequency(l_h, c1, c2)
    design = osc.colpitts_design(f0, l_h, c_ratio=4.0)
    assert design.c1_f == pytest.approx(c1, rel=1e-12)
    assert design.c2_f == pytest.approx(c2, rel=1e-12)
    assert design.c_eq_f == pytest.approx(8e-12, rel=1e-12)
    assert design.c_ratio == 4.0
    assert design.to_dict()["c1_f"] == pytest.approx(c1, rel=1e-12)


def test_colpitts_guards():
    with pytest.raises(ValueError):
        osc.colpitts_frequency(10e-9, -10e-12, 40e-12)  # 负值元件
    with pytest.raises(ValueError):
        osc.colpitts_frequency(0.0, 10e-12, 40e-12)  # 零电感
    with pytest.raises(ValueError):
        osc.colpitts_design(1e9, 10e-9, 0.0)  # 比值必须 >0
    with pytest.raises(ValueError):
        osc.colpitts_design(1e9, 10e-9, float("nan"))


# ─── 2. Hartley ──────────────────────────────────────────────────────────────


def test_hartley_frequency_analytic_recycle():
    c_f, f_target, l_ratio, k = 20e-12, 25e6, 0.5, 0.3
    l_eq_ref = 1.0 / ((2.0 * math.pi * f_target) ** 2 * c_f)
    denom = 1.0 + l_ratio + 2.0 * k * math.sqrt(l_ratio)  # 测试独立展开
    l1 = l_eq_ref / denom
    l2 = l_ratio * l1
    m = k * math.sqrt(l1 * l2)
    # 独立路径：L1+L2+2M 应还原 L_eq_ref
    assert l1 + l2 + 2.0 * m == pytest.approx(l_eq_ref, rel=1e-12)
    assert osc.hartley_frequency(l1, l2, m, c_f) == pytest.approx(f_target, rel=1e-12)


def test_hartley_round_trip_design():
    c_f, f_target, l_ratio, k = 20e-12, 25e6, 0.5, 0.3
    design = osc.hartley_design(f_target, c_f, l_ratio=l_ratio, k_coupling=k)
    f_back = osc.hartley_frequency(design.l1_h, design.l2_h, design.m_h, design.c_f)
    assert f_back == pytest.approx(f_target, rel=1e-12)
    assert design.l_eq_h == pytest.approx(
        1.0 / ((2.0 * math.pi * f_target) ** 2 * c_f), rel=1e-12
    )
    assert design.k_coupling == 0.3
    assert design.l_ratio == 0.5


def test_hartley_guards():
    with pytest.raises(ValueError):
        osc.hartley_design(25e6, 20e-12, l_ratio=0.5, k_coupling=1.5)  # |k|>1
    with pytest.raises(ValueError):
        osc.hartley_design(25e6, 20e-12, l_ratio=1.0, k_coupling=-1.0)  # 分母 0 退化
    with pytest.raises(ValueError):
        osc.hartley_frequency(1e-6, 1e-6, 1e-6, -20e-12)  # 负电容
    with pytest.raises(ValueError):
        osc.hartley_frequency(1e-6, 1e-6, -1e-6, 20e-12)  # L_eq=0（全反绕退化）


# ─── 3. Clapp ────────────────────────────────────────────────────────────────


CL_L, CL_F, CL_RATIO, CL_C3 = 1e-6, 10e6, 4.0, 300e-12


def test_clapp_frequency_analytic_recycle():
    design = osc.clapp_design(CL_F, CL_L, c_ratio=CL_RATIO, c3_f=CL_C3)
    # 测试独立串联公式（连乘积形态）：C_eq = C1·C2·C3/(C1·C2+C2·C3+C1·C3)
    c1, c2, c3 = design.c1_f, design.c2_f, CL_C3
    c_eq_ref = c1 * c2 * c3 / (c1 * c2 + c2 * c3 + c1 * c3)
    f_ref = 1.0 / (2.0 * math.pi * math.sqrt(CL_L * c_eq_ref))
    assert osc.clapp_frequency(CL_L, c1, c2, c3) == pytest.approx(f_ref, rel=1e-12)
    # C3 主导惯例：C3 最小时 C_eq → C3 附近（此处 C3 略大于 C_eq 目标）
    assert design.c_eq_f == pytest.approx(1.0 / ((2.0 * math.pi * CL_F) ** 2 * CL_L), rel=1e-12)


def test_clapp_round_trip_design():
    f0 = osc.clapp_frequency(CL_L, 2.0e-9, 8.0e-9, CL_C3)
    design = osc.clapp_design(f0, CL_L, c_ratio=CL_RATIO, c3_f=CL_C3)
    f_back = osc.clapp_frequency(CL_L, design.c1_f, design.c2_f, design.c3_f)
    assert f_back == pytest.approx(f0, rel=1e-12)
    assert design.c1_f == pytest.approx(2.0e-9, rel=1e-9)
    assert design.c2_f == pytest.approx(8.0e-9, rel=1e-9)


def test_clapp_guard_c3_le_eq():
    # C3 ≤ 目标 C_eq → 三电容串联达不到目标 → ValueError
    c_eq_target = 1.0 / ((2.0 * math.pi * CL_F) ** 2 * CL_L)
    with pytest.raises(ValueError):
        osc.clapp_design(CL_F, CL_L, c_ratio=CL_RATIO, c3_f=c_eq_target * 0.5)
    with pytest.raises(ValueError):
        osc.clapp_design(CL_F, CL_L, c_ratio=CL_RATIO, c3_f=c_eq_target)


# ─── 4. 交叉耦合 ─────────────────────────────────────────────────────────────


def test_cross_coupled_frequency_and_design_round_trip():
    l_h, c_f = 2e-9, 1e-12
    f_ref = 1.0 / (2.0 * math.pi * math.sqrt(l_h * c_f))
    assert osc.cross_coupled_frequency(l_h, c_f) == pytest.approx(f_ref, rel=1e-12)
    c_back = osc.cross_coupled_design(f_ref, l_h)
    assert c_back == pytest.approx(c_f, rel=1e-12)
    f_back = osc.cross_coupled_frequency(l_h, c_back)
    assert f_back == pytest.approx(f_ref, rel=1e-12)


def test_cross_coupled_negative_resistance_identity():
    for gm in (0.002, 0.01, 0.05):
        assert osc.cross_coupled_negative_resistance(gm) == pytest.approx(-2.0 / gm, rel=1e-15)
    with pytest.raises(ValueError):
        osc.cross_coupled_negative_resistance(0.0)
    with pytest.raises(ValueError):
        osc.cross_coupled_negative_resistance(-0.01)
    with pytest.raises(ValueError):
        osc.cross_coupled_negative_resistance(True)  # bool 显式拒收


def test_cross_coupled_startup_critical_margin_bitexact():
    # gm·R_p=2 恰临界 → margin==0.0 逐位（浮点精确对）
    for gm, r_p in ((2.0, 1.0), (0.5, 4.0)):
        res = osc.cross_coupled_startup(gm, r_p)
        assert res.margin == 0.0
        assert res.oscillates is False  # 严格判据：恰临界不起振
        assert res.critical_gm_s == pytest.approx(2.0 / r_p, rel=1e-15)
    res_k = osc.cross_coupled_startup(0.004, 1000.0)
    assert res_k.margin == pytest.approx(1.0, rel=1e-12)
    assert res_k.oscillates is True


def test_cross_coupled_startup_rp_doubling_starts():
    # R_p 加倍 → 从不起振翻转为起振
    below = osc.cross_coupled_startup(0.003, 500.0)  # gm·R_p=1.5 < 2
    above = osc.cross_coupled_startup(0.003, 1000.0)  # gm·R_p=3 > 2
    assert below.oscillates is False
    assert above.oscillates is True


def test_cross_coupled_parallel_identity_grid():
    # 恒等式：|R_n|=2/gm < R_p ⇔ margin>0（并联口径，与串联口径拓扑不同、
    # 方向相反，不与 negative_resistance_startup 交叉断言）
    for gm in (0.0025, 0.004, 0.01):
        for r_p in (50.0, 800.0):
            res = osc.cross_coupled_startup(gm, r_p)
            assert res.oscillates == (2.0 / gm < r_p)


def test_margin_sweep_properties():
    gm = [0.0, 0.001, 0.002, 0.004]
    sweep = osc.cross_coupled_margin_sweep(gm, 1000.0)
    assert sweep.critical_gm_s == pytest.approx(0.002, rel=1e-15)
    for g, m in zip(gm, sweep.margin, strict=True):
        scalar = osc.cross_coupled_startup(g, 1000.0)
        assert m == pytest.approx(scalar.margin, abs=1e-12)
    assert sweep.oscillates == [m > 0.0 for m in sweep.margin]
    assert sweep.oscillates[0] is False
    assert sweep.oscillates[-1] is True
    # 单调性：margin 随 gm 单调增
    diffs = np.diff(np.asarray(sweep.margin))
    assert bool(np.all(diffs > 0.0))
    with pytest.raises(ValueError):
        osc.cross_coupled_margin_sweep([0.001, -0.1], 1000.0)  # 负跨导
    with pytest.raises(ValueError):
        osc.cross_coupled_margin_sweep([True, False], 1000.0)  # bool 数组拒收
    with pytest.raises(ValueError):
        osc.cross_coupled_margin_sweep([0.001, float("nan")], 1000.0)


# ─── 5. 负阻起振（串联 + 大信号 + 反射系数）──────────────────────────────────


def test_negative_resistance_startup_margins():
    res = osc.negative_resistance_startup(-200.0, 50.0)
    assert res.oscillates is True
    assert res.margin == 3.0  # (200−50)/50，逐位
    crit = osc.negative_resistance_startup(-50.0, 50.0)
    assert crit.margin == 0.0  # 恰临界逐位
    assert crit.oscillates is False
    pos = osc.negative_resistance_startup(10.0, 50.0)
    assert pos.oscillates is False
    assert pos.margin == pytest.approx(-1.2, rel=1e-15)
    for r_in, r_res in ((float("nan"), 50.0), (-200.0, 0.0), (-200.0, -1.0), (True, 50.0)):
        with pytest.raises(ValueError):
            osc.negative_resistance_startup(r_in, r_res)


def test_operating_point_stable_crossing():
    amps = [0.0, 0.1, 0.2, 0.3, 0.4]
    r_in = [-200.0, -150.0, -100.0, -50.0, -20.0]
    res = osc.negative_resistance_operating_point(amps, r_in, 50.0)
    assert res.small_signal_starts is True
    assert res.stable_point_exists is True
    assert res.n_crossings == 1
    assert res.n_stable_crossings == 1
    assert res.amplitude == pytest.approx(0.3, rel=1e-12)  # R_in(0.3)=−50 恰交点
    assert res.r_in_at_point == pytest.approx(-50.0, rel=1e-12)


def test_operating_point_mixed_and_no_start():
    # 先稳定上穿（k=0 处）再不稳定下穿（k=1 处）：取首个稳定交点，计数诚实
    res = osc.negative_resistance_operating_point(
        [0.0, 0.1, 0.2, 0.3], [-200.0, -30.0, -80.0, -150.0], 50.0
    )
    assert res.stable_point_exists is True
    assert res.n_crossings == 2
    assert res.n_stable_crossings == 1
    assert res.amplitude == pytest.approx(150.0 / 170.0 * 0.1, rel=1e-12)
    assert res.r_in_at_point == pytest.approx(-50.0, rel=1e-12)
    # 小信号即不起振（residual[0]≥0）：下行过零只计数、不判稳定点
    res2 = osc.negative_resistance_operating_point([0.0, 0.1, 0.2], [-40.0, -45.0, -60.0], 50.0)
    assert res2.small_signal_starts is False
    assert res2.stable_point_exists is False
    assert res2.n_crossings == 1
    assert res2.amplitude is None
    with pytest.raises(ValueError):
        osc.negative_resistance_operating_point([0.1, 0.05], [-100.0, -20.0], 50.0)  # 非递增
    with pytest.raises(ValueError):
        osc.negative_resistance_operating_point([0.0, 0.1], [-100.0], 50.0)  # 长度不符


def _reflection_inputs(scale: float, n: int = 901):
    freqs = np.linspace(1e9, 1e10, n)
    phi = (freqs - 5.0e9) * (2.0 * math.pi / 1e10)
    gamma_a = scale * 0.8 * np.exp(0.5j * phi)
    gamma_r = scale * 1.3 * np.exp(0.5j * phi)
    return gamma_a, gamma_r, freqs


def test_reflection_startup_oscillates():
    ga, gr, freqs = _reflection_inputs(1.0)
    res = osc.reflection_startup(ga, gr, freqs)
    assert res.oscillates is True
    assert res.freq_hz == pytest.approx(5.0e9, rel=1e-12)  # 相位条件 ∠Γa+∠Γr=0
    assert res.product_mag == pytest.approx(1.04, rel=1e-9)  # |Γa|·|Γr|=0.8·1.3
    assert res.margin == pytest.approx(0.04, rel=1e-9)
    assert res.n_candidates == 1


def test_reflection_startup_subcritical_and_no_candidate():
    ga, gr, freqs = _reflection_inputs(0.9)  # |Γa·Γr|=0.9²·1.04 < 1
    res = osc.reflection_startup(ga, gr, freqs)
    assert res.oscillates is False
    assert res.freq_hz == pytest.approx(5.0e9, rel=1e-12)
    assert res.margin < 0.0
    # 相位恒定（无过零）→ 无候选点，诚实回告 None
    phi = (freqs - 5.0e9) * (2.0 * math.pi / 1e10)
    ga2 = 0.5 * np.exp(0.5j * phi)
    gr2 = 0.5 * np.exp(-0.5j * phi) * (-1.0 + 0.0j)  # 乘积相位恒 π
    res2 = osc.reflection_startup(ga2, gr2, freqs)
    assert res2.n_candidates == 0
    assert res2.oscillates is False
    assert res2.freq_hz is None
    assert res2.margin is None


def test_reflection_startup_guards():
    ga, gr, freqs = _reflection_inputs(1.0, n=64)
    with pytest.raises(ValueError):
        osc.reflection_startup(ga, gr[:-1], freqs)  # 长度不符
    with pytest.raises(ValueError):
        osc.reflection_startup(ga, gr, freqs[::-1])  # 频率非递增
    with pytest.raises(ValueError):
        osc.reflection_startup(ga, gr.astype(bool), freqs)  # bool 数组拒收
    with pytest.raises(ValueError):
        osc.reflection_startup(ga, gr * float("nan"), freqs)  # 非有限


# ─── 6. Leeson 相噪 ──────────────────────────────────────────────────────────


_LEESON_KW: dict = dict(
    f0_hz=F0,
    q_l=Q_L,
    flicker_corner_hz=FLICK,
    noise_figure_lin=NF,
    p_s_w=P_S,
    t0_k=T0,
)


def test_leeson_floor_analytic():
    floor_lin = osc.leeson_floor_lin(NF, P_S, T0)
    floor_ref = NF * K_B * T0 / (2.0 * P_S)  # 测试独立展开
    assert floor_lin == pytest.approx(floor_ref, rel=1e-12)
    assert osc.leeson_floor_dbc(NF, P_S, T0) == pytest.approx(10.0 * math.log10(floor_ref), rel=1e-12)
    assert osc.leeson_floor_dbc(NF, P_S) == pytest.approx(10.0 * math.log10(floor_ref), rel=1e-12)
    for nf, ps in ((0.0, P_S), (NF, 0.0), (NF, -1.0), (float("nan"), P_S), (True, P_S)):
        with pytest.raises(ValueError):
            osc.leeson_floor_lin(nf, ps, T0)


def test_leeson_asymptote_and_bracket_identity():
    floor_lin = osc.leeson_floor_lin(NF, P_S, T0)
    # Δf→∞ 浮点极限：两括号舍入为 1 → lin==floor 逐位
    huge = 1.0e30 * F_HALF
    assert osc.leeson_lin(huge, **_LEESON_KW) == floor_lin
    # 有限远（1e9×半带宽）：rel 1e-9 收敛判据
    near = osc.leeson_lin(1.0e9 * F_HALF, **_LEESON_KW)
    assert near == pytest.approx(floor_lin, rel=1e-9)
    # Δf=f0/(2Q_L)：1/f² 括号恰=2（逐位）
    y = floor_lin * (1.0 + F_FLICK / F_HALF)
    assert osc.leeson_lin(F_HALF, **_LEESON_KW) / y == 2.0


def test_leeson_l_dbc_analytic_recycle():
    df = 1.0e6
    lin_ref = (
        NF
        * K_B
        * T0
        / (2.0 * P_S)
        * (1.0 + FLICK / (2.0 * df))
        * (1.0 + (F0 / (2.0 * Q_L) / df) ** 2)
    )
    assert osc.leeson_l_dbc(df, **_LEESON_KW) == pytest.approx(10.0 * math.log10(lin_ref), rel=1e-12)
    with pytest.raises(ValueError):
        osc.leeson_l_dbc(0.0, **_LEESON_KW)  # 偏移频率 >0
    with pytest.raises(ValueError):
        osc.leeson_lin(1e6, **{**_LEESON_KW, "q_l": 0.0})  # Q≤0
    with pytest.raises(ValueError):
        osc.leeson_lin(1e6, **{**_LEESON_KW, "flicker_corner_hz": -1.0})  # 负拐角


def test_leeson_segments_match_clock_noise_normal_order():
    res = osc.leeson_model(f_min_hz=1e2, f_max_hz=1e8, **_LEESON_KW)
    assert [seg["slope"] for seg in res.segments] == [-3.0, -2.0, 0.0]
    assert res.f_half_bw_hz == F_HALF
    assert res.f_flicker_hz == F_FLICK
    # 双路径：clock_noise 独立实现链（#118），同输入应逐位一致
    cn_segs = clock_noise.build_power_law_segments(
        res.floor_dbc_hz, [(F_FLICK, -3.0), (F_HALF, -2.0)], 1e2, 1e8
    )
    grid = np.logspace(2, 8, 601)
    mine = clock_noise.power_law_l_dbc(grid, res.segments)  # 同时验证段 dict 契约
    theirs = clock_noise.power_law_l_dbc(grid, cn_segs)
    rel = np.max(np.abs(mine - theirs) / np.maximum(np.abs(theirs), 1e-300))
    assert float(rel) <= 1e-9


def test_leeson_segments_match_clock_noise_reversed_order():
    kw = {**_LEESON_KW, "flicker_corner_hz": 1.0e9}  # 闪烁拐角 5e8 > 半带宽 4.8e7
    res = osc.leeson_model(f_min_hz=1e2, f_max_hz=1e9, **kw)
    assert [seg["slope"] for seg in res.segments] == [-3.0, -1.0, 0.0]  # 中段 1/f
    cn_segs = clock_noise.build_power_law_segments(
        res.floor_dbc_hz, [(F_HALF, -3.0), (5.0e8, -1.0)], 1e2, 1e9
    )
    grid = np.logspace(2, 9, 601)
    mine = clock_noise.power_law_l_dbc(grid, res.segments)
    theirs = clock_noise.power_law_l_dbc(grid, cn_segs)
    rel = np.max(np.abs(mine - theirs) / np.maximum(np.abs(theirs), 1e-300))
    assert float(rel) <= 1e-9


def test_leeson_segments_flicker_zero_and_collapsed():
    # f_c=0 → 退化两段（1/f² + 平坦）
    kw0 = {**_LEESON_KW, "flicker_corner_hz": 0.0}
    res0 = osc.leeson_model(f_min_hz=1e2, f_max_hz=1e8, **kw0)
    assert [seg["slope"] for seg in res0.segments] == [-2.0, 0.0]
    cn0 = clock_noise.build_power_law_segments(res0.floor_dbc_hz, [(F_HALF, -2.0)], 1e2, 1e8)
    grid = np.logspace(2, 8, 201)
    rel0 = np.max(
        np.abs(
            clock_noise.power_law_l_dbc(grid, res0.segments)
            - clock_noise.power_law_l_dbc(grid, cn0)
        )
        / np.maximum(np.abs(clock_noise.power_law_l_dbc(grid, cn0)), 1e-300)
    )
    assert float(rel0) <= 1e-9
    # 两拐角重合 → 塌缩单拐角（−3 + 平坦）
    kw_c = {**_LEESON_KW, "flicker_corner_hz": 2.0 * F_HALF}  # f_c/2 == f0/(2Q_L)
    res_c = osc.leeson_model(f_min_hz=1e2, f_max_hz=1e8, **kw_c)
    assert [seg["slope"] for seg in res_c.segments] == [-3.0, 0.0]


def test_leeson_segments_corner_values_exact():
    res = osc.leeson_model(f_min_hz=1e2, f_max_hz=1e8, **_LEESON_KW)
    floor_db = res.floor_dbc_hz
    # 白地板拐角处段链值 == floor（log10(1)=0 直通，逐位）
    assert float(clock_noise.power_law_l_dbc(F_HALF, res.segments)) == floor_db
    # 低拐角处段链值 == floor+10·(−2)·log10(c_flick/c_half)（渐近衔接，逐位口径）
    expect_flick = floor_db + 10.0 * (-2.0) * math.log10(F_FLICK / F_HALF)
    assert float(clock_noise.power_law_l_dbc(F_FLICK, res.segments)) == pytest.approx(
        expect_flick, rel=1e-12
    )


def test_leeson_sigma_phi2_exact_vs_quad():
    scipy_quad = pytest.importorskip("scipy.integrate")
    f1, f2 = 1.0e3, 1.0e7
    exact = osc.leeson_sigma_phi2_exact(f1, f2, **_LEESON_KW)
    val, _ = scipy_quad.quad(
        lambda f: osc.leeson_lin(f, **_LEESON_KW), f1, f2, limit=500
    )
    assert exact / 2.0 == pytest.approx(val, rel=1e-6)  # exact=2·∫（MT-008 口径）


def test_leeson_jitter_closed_loop_clock_noise():
    # 闭环：Leeson 闭式 → dB 网格 → clock_noise 积分器 → rms 抖动
    grid = np.logspace(3, 7, 4001)
    l_vals = np.array([osc.leeson_l_dbc(f, **_LEESON_KW) for f in grid])
    pj = clock_noise.phase_jitter_from_l(grid, l_vals, interp="db_linear", f_carrier=F0)
    sigma_exact = math.sqrt(osc.leeson_sigma_phi2_exact(1e3, 1e7, **_LEESON_KW))
    assert pj.sigma_phi_rad == pytest.approx(sigma_exact, rel=2e-3)  # 网格离散收敛级
    assert pj.jitter_s == pytest.approx(sigma_exact / (2.0 * math.pi * F0), rel=2e-3)


def test_leeson_sigma_phi2_exact_zero_width_and_reversed():
    assert osc.leeson_sigma_phi2_exact(1e6, 1e6, **_LEESON_KW) == 0.0  # 逐位
    with pytest.raises(ValueError):
        osc.leeson_sigma_phi2_exact(1e7, 1e6, **_LEESON_KW)
    with pytest.raises(ValueError):
        osc.leeson_sigma_phi2_exact(0.0, 1e6, **_LEESON_KW)


def test_leeson_model_span_guards():
    with pytest.raises(ValueError):
        osc.leeson_model(f_min_hz=1e9, f_max_hz=1e8, **_LEESON_KW)  # f_max ≤ f_min
    with pytest.raises(ValueError):
        osc.leeson_model(f_min_hz=F_HALF, f_max_hz=1e8, **_LEESON_KW)  # f_min ≥ 最低拐角
    with pytest.raises(ValueError):
        osc.leeson_model(f_min_hz=1e2, f_max_hz=F_HALF, **_LEESON_KW)  # f_max ≤ 最高拐角


def test_to_dict_json_serializable():
    payloads = [
        osc.leeson_model(f_min_hz=1e2, f_max_hz=1e8, **_LEESON_KW).to_dict(),
        osc.negative_resistance_startup(-200.0, 50.0).to_dict(),
        osc.negative_resistance_operating_point(
            [0.0, 0.1, 0.2], [-200.0, -150.0, -30.0], 50.0
        ).to_dict(),
        osc.reflection_startup(*_reflection_inputs(1.0, n=16)).to_dict(),
        osc.colpitts_design(1e9, 10e-9, 4.0).to_dict(),
        osc.hartley_design(25e6, 20e-12, 0.5, 0.3).to_dict(),
        osc.clapp_design(CL_F, CL_L, CL_RATIO, CL_C3).to_dict(),
        osc.cross_coupled_startup(0.01, 500.0).to_dict(),
        osc.cross_coupled_margin_sweep([0.0, 0.01], 500.0).to_dict(),
    ]
    for payload in payloads:
        assert isinstance(json.loads(json.dumps(payload)), dict)


# ─── 7. DRO 耦合 ─────────────────────────────────────────────────────────────


def test_dro_loaded_q_identities():
    q0 = 10000.0
    assert osc.dro_loaded_q(q0, 0.0) == q0  # β=0 → Q_L==Q_0 逐位
    assert osc.dro_loaded_q(q0, 1.0) == q0 / 2.0  # β=1 → Q_0/2 逐位
    assert osc.dro_loaded_q(q0, 3.0) == 2500.0
    for q0_bad, beta_bad in ((0.0, 1.0), (-1.0, 1.0), (q0, -0.5), (q0, float("nan")), (q0, True)):
        with pytest.raises(ValueError):
            osc.dro_loaded_q(q0_bad, beta_bad)


def test_dro_coupling_power_fractions():
    crit = osc.dro_coupling_power(1.0)
    assert crit["external_frac"] == 0.5
    assert crit["internal_frac"] == 0.5
    assert crit["critical_coupled"] is True
    assert crit["external_frac"] + crit["internal_frac"] == 1.0
    over = osc.dro_coupling_power(3.0)
    assert over["external_frac"] == pytest.approx(0.75, rel=1e-15)
    assert over["internal_frac"] == pytest.approx(0.25, rel=1e-15)
    assert over["critical_coupled"] is False
    assert over["external_frac"] + over["internal_frac"] == pytest.approx(1.0, rel=1e-15)
    under = osc.dro_coupling_power(0.0)
    assert under["external_frac"] == 0.0
    assert under["critical_coupled"] is False
    with pytest.raises(ValueError):
        osc.dro_coupling_power(-1.0)


def test_dro_to_leeson_pipeline():
    q_l = osc.dro_loaded_q(5000.0, 2.0)
    res = osc.leeson_model(
        f0_hz=F0,
        q_l=q_l,
        flicker_corner_hz=FLICK,
        noise_figure_lin=NF,
        p_s_w=P_S,
        f_min_hz=1e2,
        f_max_hz=1e8,
    )
    assert res.q_l == pytest.approx(5000.0 / 3.0, rel=1e-15)
    assert res.f_half_bw_hz == pytest.approx(F0 / (2.0 * q_l), rel=1e-15)


# ─── 8. service 面（JSON 信封 + clock_noise 闭环）────────────────────────────


def test_service_oscillator_frequency_and_startup_envelope():
    out = svc.oscillator_frequency({"kind": "colpitts", "l_h": 10e-9, "c1_f": 10e-12, "c2_f": 40e-12})
    assert out["ok"] is True
    assert out["result"]["f_hz"] == pytest.approx(osc.colpitts_frequency(10e-9, 10e-12, 40e-12))
    assert out["schema_version"] == svc.SCHEMA_VERSION
    bad = svc.oscillator_frequency({"kind": "bogus", "l_h": 1.0})
    assert bad["ok"] is False
    assert "kind" in bad["error"]
    missing = svc.oscillator_frequency({"kind": "colpitts", "l_h": 10e-9})
    assert missing["ok"] is False  # 缺必填 → ok=False 不抛
    design = svc.oscillator_design({"kind": "cross_coupled", "f_hz": 3.5588e9, "l_h": 2e-9})
    assert design["ok"] is True
    assert design["result"]["c_f"] == pytest.approx(
        osc.cross_coupled_design(3.5588e9, 2e-9), rel=1e-12
    )
    start = svc.oscillator_startup_report(
        {
            "mode": "series",
            "r_in_ohm": -200.0,
            "r_res_ohm": 50.0,
            "amplitudes": [0.0, 0.1, 0.2, 0.3],
            "r_in_curve": [-200.0, -150.0, -100.0, -50.0],
        }
    )
    assert start["ok"] is True
    assert start["result"]["startup"]["oscillates"] is True
    assert start["result"]["operating_point"]["stable_point_exists"] is True
    cc = svc.oscillator_startup_report({"mode": "cross_coupled", "gm_s": 0.01, "r_p_ohm": 500.0})
    assert cc["ok"] is True
    assert cc["result"]["startup"]["margin"] == pytest.approx(1.5, rel=1e-12)
    invalid = svc.oscillator_startup_report({"mode": "series", "r_in_ohm": -1.0, "r_res_ohm": 0.0})
    assert invalid["ok"] is False


def test_service_leeson_report_closed_loop():
    payload = {
        "f0_hz": F0,
        "dro_q0": 25.0,
        "dro_beta": 0.0,  # β=0 → q_l=Q_0 直通（DRO 路由）
        "flicker_corner_hz": FLICK,
        "noise_figure_lin": NF,
        "p_s_w": P_S,
        "f_min_hz": 1e2,
        "f_max_hz": 1e8,
        "jitter_f1_hz": 1e6,
        "jitter_f2_hz": 1e7,
        "f_carrier_hz": F0,
    }
    out = svc.leeson_noise_report(payload)
    assert out["ok"] is True
    result = out["result"]
    assert result["q_route"] == "dro"
    assert result["q_l"] == 25.0
    jit = result["jitter"]
    assert jit["sigma_phi2_chain_rad2"] > 0.0
    assert jit["sigma_phi2_exact_rad2"] > 0.0
    # 过渡带贡献小的区间：段链渐近口径 vs 精确式差有界（实测 ~3.1%，
    # 来源=1/f² 区低端闪烁残差 (1+f_c/2f)≈1.05 被渐近链略去——模型固有
    # 误差非代码缺陷，内核边界②；断言只钉"有界非退化"）
    assert 0.0 < abs(jit["chain_exact_rel_delta"]) <= 0.05
    assert jit["jitter_s"] == pytest.approx(jit["sigma_phi_rad"] / (2.0 * math.pi * F0), rel=1e-15)
    direct = svc.leeson_noise_report({**payload, "dro_q0": None, "q_l": 25.0, "dro_beta": None})
    assert direct["ok"] is True
    assert direct["result"]["q_route"] == "direct"
    assert direct["result"]["q_l"] == 25.0
    bad_ps = svc.leeson_noise_report({**payload, "p_s_w": -1.0})
    assert bad_ps["ok"] is False  # P_s≤0 → ok=False 不抛
    no_q = svc.leeson_noise_report({k: v for k, v in payload.items() if k != "dro_q0"})
    assert no_q["ok"] is False
    # 深入 1/f³ 区的宽区间：差如实回告且有限（渐近模型固有误差，内核边界②）
    wide = svc.leeson_noise_report({**payload, "jitter_f1_hz": 1e3})
    assert wide["ok"] is True
    assert math.isfinite(wide["result"]["jitter"]["chain_exact_rel_delta"])


def test_service_reflection_mode_json_complex():
    ga, gr, freqs = _reflection_inputs(1.0, n=64)
    payload = {
        "mode": "reflection",
        "gamma_amp": np.stack([ga.real, ga.imag], axis=1).tolist(),
        "gamma_res": np.stack([gr.real, gr.imag], axis=1).tolist(),
        "freq_hz": freqs.tolist(),
    }
    out = svc.oscillator_startup_report(payload)
    assert out["ok"] is True
    startup = out["result"]["startup"]
    assert startup["oscillates"] is True
    assert startup["freq_hz"] == pytest.approx(5.0e9, rel=1e-9)
    bad_pair = svc.oscillator_startup_report({**payload, "gamma_amp": [[0.8, 0.0, 1.0]]})
    assert bad_pair["ok"] is False
