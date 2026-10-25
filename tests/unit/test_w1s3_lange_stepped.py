"""aurora_f W1-S3 锚树：Lange 电桥 core 提升（F1）+ 阶梯阻抗 LPF 综合（F2）。

锚面（#118 独立来源/#122 如实口径，逐测试注明）
- F1 字节级对拍钉：render_c4→core 提升式重构前后同参输出**逐位一致**
  （字面量=重构前 runs/aurora_f/w1s3_lange_parity_baseline.json 实测捕获，
  提升提交前落档）；再导出单对象断言（#116 不留遮蔽副本的结构性铁证）。
- F1 回代恒等式：C=(Ze4−Zo4)/(Ze4+Zo4)、Z0=√(Ze4·Zo4)（render_c4 §C4
  口径 3 写死）；KJ (w,s) 正向回代 ≤0.5Ω（inverse_width 同款自洽阈）。
- F1 文献锚：3dB → 相邻对 (176.216, 52.609)Ω → (Ze4,Zo4)=(120.71,20.71)Ω
  （Pozar §7.6 Lange 节教科书常引值，render_c4 段首 3 同源）。
- F1 双路线裁判：core lange_response（本模块独立实现 (Se+So)/2 构造）vs
  adapters coupled_line_coupler_sparams（_coupled_section_s4 路线）逐位
  ≤1e-12。
- F2 g 值双源：binomial 精确闭式 2sin((2k−1)π/2N) 恒等（N=3→[1,2,1]、
  N=5→Pozar Table 8.3 同值）；chebyshev 与同仓
  core/synthesis.chebyshev_lpf_g_values（MYJ 表单源）逐位对照。
- F2 Pozar Example 8.2 设计式口径（N=5 最平坦、fc=2GHz、50Ω、Z_high=150Ω、
  Z_low=10Ω）：测试侧用**教科书表值 g**（0.618/1.618/2.000，三位舍入）
  独立重算 θ=arctan(g·Z0/Z) 与键输出对照 rtol 1e-3——印刷数值未回原文
  逐位核对不硬钉（#122），设计式本身由闭式恒等钉住。
- F2 渐近锚：Z_high/Z_low→∞ 渐近集总梯（带内 |S21|dB 偏差 R10→R100 单调
  收敛 0.87→0.16dB，本席实测）；fc−3dB 回收偏差=离散段化固有量（实测
  +6.1%@比 15、门 ≤8% 如实）。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.calc_families.lange import (
    lange_design,
    lange_equivalent_zee_zoo,
    lange_pair_zee_zoo,
)
from rfauto.core.calc_families.stepped_impedance import (
    stepped_impedance_lpf_synthesize,
    stepped_impedance_response,
)
from rfauto.service.calculator_service import run_calculator

# ── F1 提升前基线（runs/aurora_f/w1s3_lange_parity_baseline.json 字面量，
#    2026-10-18 重构前 render_c4.lange_design 实测捕获；notes 不入对拍）──
_LANGE_BASELINE_DEFAULT = {
    "coupling_db": 3.0103, "z0_ohm": 50.0, "f0_ghz": 2.5,
    "zee_pair_ohm": 176.21567863119589, "zoo_pair_ohm": 52.60888198502657,
    "ze4_ohm": 120.71067726646262, "zo4_ohm": 20.710678264867816,
    "c": 0.707106777656652, "w_mm": 0.16721717814818207,
    "s_mm": 0.03858305645674591, "ere_e": 2.651379639307545,
    "ere_o": 2.3429851485513873, "finger_len_mm": 18.971233558890226,
    "w_feed_mm": 1.1116902209539834,
}
_LANGE_BASELINE_6DB = {
    "coupling_db": 6.0, "z0_ohm": 50.0, "f0_ghz": 2.0,
    "zee_pair_ohm": 142.669446440003, "zoo_pair_ohm": 67.88122767457834,
    "ze4_ohm": 86.73984774995989, "zo4_ohm": 28.821816787211915,
    "c": 0.5011872336272722, "w_mm": 0.2288701940587474,
    "s_mm": 0.1543874267262208, "ere_e": 2.719148277566254,
    "ere_o": 2.363511087068893, "finger_len_mm": 23.507162604383957,
    "w_feed_mm": 1.1117884788480208,
}


# ═══ F1：Lange core 提升（字节对拍/恒等式/文献锚/双路线）═════════════════════

def test_lange_promotion_byte_parity_and_single_object() -> None:
    """提升零漂移：core 函数输出与重构前基线逐位一致 + 再导出单对象。"""
    for kwargs, baseline in (
            ({}, _LANGE_BASELINE_DEFAULT),
            ({"f0_ghz": 2.0, "coupling_db": 6.0}, _LANGE_BASELINE_6DB)):
        out = lange_design(**kwargs)
        for key, expected in baseline.items():
            assert out[key] == expected, (
                f"lange 提升漂移：{key} {out[key]!r} != 基线 {expected!r}")
    # 单一事实源的结构性证据：adapters 三个入口 = core 同一函数对象（#116）
    from rfauto.adapters.oe_templates import render_c4
    from rfauto.adapters.openems_templates import (
        lange_design as ot_lange_design,
    )

    assert render_c4.lange_design is lange_design
    assert ot_lange_design is lange_design


def test_lange_synthesize_backsubstitution_identity() -> None:
    """回代恒等式：C=(Ze4−Zo4)/(Ze4+Zo4)、Z0=√(Ze4·Zo4)（写死口径）。"""
    out = lange_design(2.5, 50.0, 3.0103)
    c_back = (out["ze4_ohm"] - out["zo4_ohm"]) / (out["ze4_ohm"]
                                                  + out["zo4_ohm"])
    z0_back = math.sqrt(out["ze4_ohm"] * out["zo4_ohm"])
    assert c_back == pytest.approx(out["c"], rel=1e-12)
    assert z0_back == pytest.approx(50.0, rel=1e-12)
    # 相邻对与四线等效链一致性：pair → equivalent（正向函数独立再算）
    ze4, zo4 = lange_equivalent_zee_zoo(out["zee_pair_ohm"],
                                        out["zoo_pair_ohm"])
    assert (ze4, zo4) == (out["ze4_ohm"], out["zo4_ohm"])


def test_lange_textbook_closure_3db_and_kj_roundtrip() -> None:
    """文献锚（Pozar §7.6 Lange 节）：3dB 闭合链 + KJ (w,s) 正向回代。"""
    zee, zoo = lange_pair_zee_zoo(1.0 / math.sqrt(2.0), 50.0)
    assert zee == pytest.approx(176.216, abs=1e-2)
    assert zoo == pytest.approx(52.609, abs=1e-2)
    ze4, zo4 = lange_equivalent_zee_zoo(zee, zoo)
    assert ze4 == pytest.approx(120.71, abs=1e-2)
    assert zo4 == pytest.approx(20.71, abs=1e-2)
    # KJ 正向回代：(w,s) → (Z0e,Z0o) 回到相邻对目标（inverse_width 同款 0.5Ω 阈）
    from rfauto.core.coupled_microstrip import (
        coupled_bpf_width_gap_from_zee_zoo,
        coupled_microstrip_even_odd_ohm,
    )

    w_mm, s_mm = coupled_bpf_width_gap_from_zee_zoo(zee, zoo, 2.5, 3.66,
                                                    0.508)
    ze_kj, zo_kj, _ere_e, _ere_o = coupled_microstrip_even_odd_ohm(
        w_mm, s_mm, 2.5, 3.66, 0.508)
    assert ze_kj == pytest.approx(zee, abs=0.5)
    assert zo_kj == pytest.approx(zoo, abs=0.5)
    # 提升前后 KJ 反解同位（基线 w/s 逐位已在字节对拍钉内覆盖）


def test_lange_response_dual_path_vs_adapters() -> None:
    """双路线裁判（#118）：core (Se+So)/2 构造 vs adapters _coupled_section_s4
    路线，幅度逐位 ≤1e-12；f0 理想 3dB 值 + 守恒/互易残差。"""
    from rfauto.adapters.openems_templates import coupled_line_coupler_sparams

    freqs = [2.0 + 0.05 * i for i in range(21)]
    design = lange_design(2.5, 50.0, 3.0103)
    core = run_calculator("lange_response", {
        "ze4_ohm": design["ze4_ohm"], "zo4_ohm": design["zo4_ohm"],
        "finger_len_mm": design["finger_len_mm"],
        "ere_e": design["ere_e"], "ere_o": design["ere_o"],
        "freq_ghz": freqs})
    assert core["ok"], core
    res = core["result"]
    s4 = coupled_line_coupler_sparams(
        freqs, design["ze4_ohm"], design["zo4_ohm"], design["finger_len_mm"],
        design["ere_e"], design["ere_o"], synchronous_tem=True, z_ref=50.0)
    for k in range(len(freqs)):
        for p, got in enumerate((res["s11_db"][k], res["s21_db"][k],
                                 res["s31_db"][k], res["s41_db"][k])):
            want = 20.0 * math.log10(max(abs(s4[k, 0, p]), 1e-300))
            # dB 地板（−300dB 量级）处绝对差被对数放大——线性域幅度 1e-12
            assert 10.0 ** (got / 20.0) == pytest.approx(
                10.0 ** (want / 20.0), abs=1e-12), (k, p, got, want)
    # f0=2.5（轴内第 11 点）：理想 3dB 配对 + 匹配/隔离地板
    i_f0 = freqs.index(2.5)
    assert res["s21_db"][i_f0] == pytest.approx(-3.0103, abs=1e-4)
    assert res["s31_db"][i_f0] == pytest.approx(-3.0103, abs=1e-4)
    assert res["s11_db"][i_f0] < -300.0
    assert res["s41_db"][i_f0] < -300.0
    assert res["energy_residual_max"] <= 1e-12
    assert res["reciprocity_residual_max"] <= 1e-12


def test_lange_guards_explicit() -> None:
    """守卫：耦合域/response 阻抗序，全部显式 ValueError。
    （8C²<9 可达域分支对 c∈(0,1) 恒不触发（须 c≥1.06）——防御式保留，
    域守卫以 (0,1) 分支为准。）"""
    with pytest.raises(ValueError, match="0,1"):
        lange_pair_zee_zoo(1.5, 50.0)
    with pytest.raises(ValueError, match="0,1"):
        lange_pair_zee_zoo(0.0, 50.0)
    with pytest.raises(ValueError, match="Z0e > Z0o"):
        lange_equivalent_zee_zoo(30.0, 60.0)
    for key, params in (
            ("lange_synthesize", {"coupling_db": 0.0}),
            ("lange_response", {"ze4_ohm": 10.0, "zo4_ohm": 40.0,
                                "finger_len_mm": 18.0, "ere_e": 2.5,
                                "ere_o": 2.3, "freq_ghz": [2.5]}),
            ("lange_response", {"ze4_ohm": 120.0, "zo4_ohm": 20.0,
                                "finger_len_mm": 0.0, "ere_e": 2.5,
                                "ere_o": 2.3, "freq_ghz": [2.5]})):
        out = run_calculator(key, params)
        assert out["ok"] is False and out.get("error"), (key, out)


# ═══ F2：阶梯阻抗 LPF（g 双源/文献设计式/渐近/回收/回代）═════════════════════

def test_si_binomial_g_values_closed_form_identity() -> None:
    """binomial 精确闭式恒等：N=3 → [1,2,1]、N=5 → Pozar Table 8.3 同值、
    对称 g_k=g_{N+1−k}（最平坦原型性质）。"""
    out3 = stepped_impedance_lpf_synthesize(3, 2.0)
    assert out3["g_values"] == pytest.approx([1.0, 2.0, 1.0], rel=1e-12)
    out5 = stepped_impedance_lpf_synthesize(5, 2.0)
    assert out5["g_values"] == pytest.approx(
        [0.618, 1.618, 2.000, 1.618, 0.618], abs=1e-3)
    n = 7
    g7 = stepped_impedance_lpf_synthesize(n, 2.0)["g_values"]
    assert all(a == pytest.approx(b, rel=1e-12)
               for a, b in zip(g7, reversed(g7), strict=True))


def test_si_chebyshev_g_values_same_repo_bitexact() -> None:
    """chebyshev 单源：键输出 g 与 core/synthesis.chebyshev_lpf_g_values
    （MYJ 表）逐位一致；even-N/缺 ripple 显式拒绝。"""
    from rfauto.core.synthesis import chebyshev_lpf_g_values

    out = stepped_impedance_lpf_synthesize(3, 2.0, prototype="chebyshev",
                                           ripple_db=-20.0)
    ref = chebyshev_lpf_g_values(3, -20.0)
    assert out["g_values"] == ref["g_values"]
    assert out["ripple_db"] == ref["ripple_db_requested"]
    assert out["passband_ripple_db"] == ref["passband_ripple_db"]
    with pytest.raises(ValueError, match="偶数节"):
        stepped_impedance_lpf_synthesize(2, 2.0, prototype="chebyshev",
                                         ripple_db=-20.0)
    with pytest.raises(ValueError, match="ripple_db"):
        stepped_impedance_lpf_synthesize(3, 2.0, prototype="chebyshev")


def test_si_pozar_example_design_rule() -> None:
    """Pozar Example 8.2 设计式口径（N=5 最平坦、fc=2GHz、50Ω、150/10Ω）：
    测试侧用教科书表值 g（三位舍入）独立重算 θ=arctan(g·Z0/Z)，与键输出
    rtol 1e-3 对照（印刷值未回原文不硬钉，#122）；段型 L 起交替。"""
    out = stepped_impedance_lpf_synthesize(5, 2.0, z_high_ohm=150.0,
                                           z_low_ohm=10.0)
    assert out["section_types"] == ["L", "C", "L", "C", "L"]
    g_textbook = [0.618, 1.618, 2.000, 1.618, 0.618]
    for k, (g, theta) in enumerate(zip(g_textbook, out["theta_deg"],
                                       strict=True)):
        # L（感性高阻段）θ=arctan(g·Z0/Z_high)；C（容性低阻段）θ=arctan(g·Z_low/Z0)
        want = (math.degrees(math.atan(g * 50.0 / 150.0)) if k % 2 == 0
                else math.degrees(math.atan(g * 10.0 / 50.0)))
        assert theta == pytest.approx(want, rel=1e-3), (k, theta, want)


def test_si_response_lumped_limit_monotone() -> None:
    """渐近锚：Z_high/Z_low→∞ → 集总梯频率响应（带内 |S21|dB 偏差随比单调
    收敛；集总梯 ABCD 测试侧独立构造）。"""
    fc = 2.0
    z0 = 50.0
    wc = 2.0 * math.pi * fc * 1e9
    freqs = [0.02 * i for i in range(10, 111)]     # 0.2..2.2GHz 带内
    # 集总 N=3 binomial 梯（g=[1,2,1]）：串联 L / 并联 C / 串联 L，
    # ABCD 测试侧独立构造（L=[[1,jwL],[0,1]]、C=[[1,0],[jwC,1]]）。
    l1 = 1.0 * z0 / wc
    c2 = 2.0 / (z0 * wc)

    def _mm(a_mat: list, b_mat: list) -> list:
        return [[sum(a_mat[i][k] * b_mat[k][j] for k in range(2))
                 for j in range(2)] for i in range(2)]

    lumped_db = []
    for f in freqs:
        w = 2.0 * math.pi * f * 1e9
        m = _mm([[1.0 + 0j, 1j * w * l1], [0j, 1.0 + 0j]],
                [[1.0 + 0j, 0j], [1j * w * c2, 1.0 + 0j]])
        m = _mm(m, [[1.0 + 0j, 1j * w * l1], [0j, 1.0 + 0j]])
        den = m[0][0] + m[0][1] / z0 + m[1][0] * z0 + m[1][1]
        lumped_db.append(20.0 * math.log10(abs(2.0 / den)))

    def _passband_dev(zh: float, zl: float) -> float:
        res = stepped_impedance_lpf_synthesize(3, fc, z_high_ohm=zh,
                                               z_low_ohm=zl)
        resp = stepped_impedance_response(
            zh, zl, res["ereff_high"], res["ereff_low"], res["lengths_mm"],
            freqs)
        assert resp["energy_residual_max"] <= 1e-12
        return max(abs(a - b) for a, b in zip(resp["s21_db"], lumped_db,
                                              strict=True))

    dev_r10 = _passband_dev(100.0, 10.0)
    dev_r100 = _passband_dev(500.0, 5.0)
    assert dev_r10 < 1.0            # 本席实测 0.874dB
    assert dev_r100 < dev_r10       # 单调收敛（实测 0.164dB，5.3× 改善）
    assert dev_r100 < 0.3


def test_si_response_fc_recovery_and_hj_backsubstitution() -> None:
    """综合→响应闭环：fc−3dB 回收（离散段化固有偏差实测 +6.1%，门 ≤8%
    如实）+ HJ 线宽正反解回代 ≤0.5Ω + 模板名义锚（0.3/3.0mm→96.9/24.8Ω）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    out = stepped_impedance_lpf_synthesize(5, 2.0, z_high_ohm=150.0,
                                           z_low_ohm=10.0)
    freqs = [0.05 * i for i in range(10, 160)]
    resp = stepped_impedance_response(
        150.0, 10.0, out["ereff_high"], out["ereff_low"], out["lengths_mm"],
        freqs)
    assert resp["fc_3db_ghz"] is not None
    assert resp["fc_3db_ghz"] == pytest.approx(2.0, rel=0.08)
    assert 0.0 < resp["rl_worst_inband_db"] < 10.0
    stackup = Stackup(name="stepped_impedance_lpf", epsilon_r=3.66,
                      thickness_mm=0.508)
    zh_act, _ = forward_z0(out["w_high_mm"], 2.0, stackup)
    zl_act, _ = forward_z0(out["w_low_mm"], 2.0, stackup)
    assert zh_act == pytest.approx(150.0, abs=0.5)
    assert zl_act == pytest.approx(10.0, abs=0.5)
    # 模板名义锚（oe_templates/registry param_semantics：0.3/3.0mm→96.9/24.8Ω
    # @2.4GHz）——模板名义值与 HJ 阻抗链同源的接线评估锚
    z1, _ = forward_z0(0.3, 2.4, stackup)
    z2, _ = forward_z0(3.0, 2.4, stackup)
    assert z1 == pytest.approx(96.9, abs=0.1)
    assert z2 == pytest.approx(24.8, abs=0.1)


def test_si_guards_explicit() -> None:
    """守卫：fc/Z 序/prototype 枚举/response 序，全部显式 ValueError。"""
    with pytest.raises(ValueError, match="fc_ghz"):
        stepped_impedance_lpf_synthesize(3, 0.0)
    with pytest.raises(ValueError, match="z_high_ohm > z0_ohm"):
        stepped_impedance_lpf_synthesize(3, 2.0, z_low_ohm=60.0,
                                         z_high_ohm=40.0)
    with pytest.raises(ValueError, match="prototype"):
        stepped_impedance_lpf_synthesize(3, 2.0, prototype="bessel")
    with pytest.raises(ValueError, match="z_high_ohm > z_low_ohm"):
        stepped_impedance_response(10.0, 150.0, 2.5, 3.3,
                                   [1.0, 2.0, 1.0], [2.0])
    with pytest.raises(ValueError, match="freq_ghz"):
        stepped_impedance_response(150.0, 10.0, 2.5, 3.3, [1.0], [])
