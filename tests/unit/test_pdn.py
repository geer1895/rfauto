"""F-B.1 core/pdn.py 单测：判据 = research_expansion §F-B 第 4 节第 1-5 条（先写后跑，#122）。

覆盖（第 6 条真机面 P3 不在本批）：
① 合成回收钉：单电容/两电容并联/VRM+散装+3 decap 阶梯 Z(f) vs 手算闭式
   （≤1e-12 相对）；反谐振峰频率 vs LC 解析式逐位；
② 口径钉：恒定 vs 频率依赖（smith）两口径差带显式报告（拐点两侧分段断言）；
③ 优化钉：贪心选型可行（全带 Z≤Z_target）+成本单调（增预算不劣化）+
   不可行需求如实 infeasible 不凑解+确定性；
④ DC-bias 钉：带曲线查表插值逐位；无曲线 no_derating；端点夹持；
⑤ 腔模钉：矩形板腔模频率 vs 闭式；避让判据正反例；
附加：yaml 库加载+schema 校验全条目合法；DecapSpec 往返与 provenance 门。
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.pdn import (
    MU0,
    CavityMode,
    DecapSpec,
    GreedyResult,
    VrmModel,
    dc_bias_effective_c,
    decap_impedance,
    greedy_decap_select,
    load_decap_library,
    mount_inductance,
    mount_position_clearance,
    pdn_impedance_profile,
    plane_cavity_modes,
    target_impedance,
    target_impedance_freq,
    vrm_model,
)

REPO = Path(__file__).resolve().parents[2]

CURVE_V = (0.0, 2.0, 4.0)
CURVE_C = (16.0e-6, 8.0e-6, 4.0e-6)


# ─── 判据 1：合成回收钉 ──────────────────────────────────────────────────────


class TestSyntheticRecovery:
    def test_target_impedance_constant_closed_form(self) -> None:
        # 恒定口径 Z=V_ripple/ΔI 手算回收（0.05V/0.2A=0.25Ω）
        assert target_impedance(0.05, 0.2) == 0.05 / 0.2
        assert target_impedance(1.0, 4.0) == 0.25
        with pytest.raises(ValueError, match="v_ripple_v"):
            target_impedance(0.0, 1.0)
        with pytest.raises(ValueError, match="delta_i_a"):
            target_impedance(0.05, -1.0)

    def test_decap_impedance_closed_form_bitwise(self) -> None:
        f = np.array([1.0e6, 1.0e7, 5.0e7, 1.0e8])
        c, esr, esl, lm = 1.0e-7, 0.02, 4.0e-10, 4.0e-10
        z = decap_impedance(c, esr, esl, lm, f)
        expected = esr + 1j * (2.0 * np.pi * f * (esl + lm) - 1.0 / (2.0 * np.pi * f * c))
        np.testing.assert_array_equal(z, expected)  # 逐位
        assert np.all(z.real == esr)
        # SRF 处虚部过零：SRF=1/(2π√(L_tot·C))，密网格 argmin|Z| 落在解析值邻点
        l_tot = esl + lm
        srf = 1.0 / (2.0 * math.pi * math.sqrt(l_tot * c))
        f_dense = np.linspace(0.5 * srf, 1.5 * srf, 100001)
        z_dense = decap_impedance(c, esr, esl, lm, f_dense)
        f_min = f_dense[int(np.argmin(np.abs(z_dense)))]
        assert f_min == pytest.approx(srf, rel=1.0e-6)
        with pytest.raises(ValueError, match="c_f"):
            decap_impedance(0.0, esr, esl, lm, f)

    def test_vrm_model_parallel_branch_closed_form(self) -> None:
        f = np.array([1.0e5, 1.0e6, 1.0e7, 1.0e8, 1.0e9])
        r0, l0, r1, l1 = 2.0e-3, 50.0e-9, 0.05, 1.0e-9
        z = vrm_model(f, r0, l0, r1, l1)
        w = 2.0 * np.pi * f
        z_low = r0 + 1j * w * l0
        z_high = r1 + 1j * w * l1
        expected = z_low * z_high / (z_low + z_high)
        np.testing.assert_allclose(z, expected, rtol=1.0e-12, atol=0.0)
        # 口径行为钉：DC 渐近（1kHz 处 |Z|≈R0∥R1，两支路感性均未起）+全程
        # 单调上升+高频段由 R1+jωL1 接管（|Z|/(ω·L1)→1）
        f_dc = np.array([1.0e3])
        z_dc = vrm_model(f_dc, r0, l0, r1, l1)[0]
        r_parallel_dc = r0 * r1 / (r0 + r1)
        assert abs(abs(z_dc) - r_parallel_dc) / r_parallel_dc < 0.02
        f_scan = np.geomspace(1.0e3, 1.0e9, 200)
        mag = np.abs(vrm_model(f_scan, r0, l0, r1, l1))
        assert np.all(np.diff(mag) > 0.0)  # 全程单调上升（两支路口径无凹谷）
        z_hi = vrm_model(np.array([1.0e9]), r0, l0, r1, l1)[0]
        # 高频渐近=两支路电感并联 ω·(L0∥L1)（感性极限，非裸 L1——收敛比率 l1/l0）
        l_parallel = l0 * l1 / (l0 + l1)
        assert abs(abs(z_hi) / (2.0 * math.pi * 1.0e9 * l_parallel) - 1.0) < 0.01
        with pytest.raises(ValueError, match="全零"):
            vrm_model(f, 0.0, 0.0, 0.0, 0.0)

    def test_mount_inductance_closed_form_exact(self) -> None:
        h, r, s, gap, spread = 1.6e-3, 0.15e-3, 1.0e-3, 0.1e-3, 0.8e-3
        got = mount_inductance(h, r, s, plane_gap_m=gap, spread_radius_m=spread)
        term_via = (MU0 / math.pi) * h * math.acosh(s / (2.0 * r))
        term_spread = (MU0 * gap / (2.0 * math.pi)) * math.log(spread / r)
        assert got == term_via + term_spread  # 逐位
        # 缺省只给过孔对回路项
        assert mount_inductance(h, r, s) == term_via
        # 典型量级：0402 双过孔 1.6mm 板 → 亚 nH
        assert 0.1e-9 < mount_inductance(1.6e-3, 0.15e-3, 1.0e-3) < 5.0e-9
        with pytest.raises(ValueError, match="arcosh"):
            mount_inductance(h, r, 2.0 * r)
        with pytest.raises(ValueError, match="board_thickness_m"):
            mount_inductance(0.0, r, s)

    def test_pdn_profile_vrm_bulk_3decap_ladder_closed_form(self) -> None:
        f = np.array([1.0e5, 1.0e6, 3.0e6, 1.0e7, 3.0e7, 1.0e8, 3.0e8])
        vrm = VrmModel(r0=2.0e-3, l0=50.0e-9, r1=0.05, l1=1.0e-9)
        bulk = [(4.7e-4, 0.08, 1.0e-8, 5.0e-9)]
        decaps = [(1.0e-5, 0.010, 4.5e-10, 4.0e-10), (1.0e-6, 0.015, 4.0e-10, 4.0e-10), (1.0e-7, 0.020, 4.0e-10, 4.0e-10)]
        z = pdn_impedance_profile(vrm, bulk, decaps, f)
        # 手算闭式：VRM 两支路并联 + 全部电容串联 RLC 的导纳求和
        w = 2.0 * np.pi * f
        z_vrm = (vrm.r0 + 1j * w * vrm.l0) * (vrm.r1 + 1j * w * vrm.l1) / ((vrm.r0 + 1j * w * vrm.l0) + (vrm.r1 + 1j * w * vrm.l1))
        y = 1.0 / z_vrm
        for c_f, esr, esl, lm in [*bulk, *decaps]:
            y += 1.0 / (esr + 1j * (w * (esl + lm) - 1.0 / (w * c_f)))
        expected = 1.0 / y
        np.testing.assert_allclose(z, expected, rtol=1.0e-12, atol=0.0)
        # DecapSpec 路径与元组路径逐位同值（同一 _branch_impedance 归一）
        specs_bulk = [DecapSpec(part="bulk470", c_f=4.7e-4, esr_ohm=0.08, esl_h=1.0e-8, mount_l_h=5.0e-9, provenance="typical_engineering_value: 待 vendor 实测替换")]
        specs_dec = [
            DecapSpec(part="d10u", c_f=1.0e-5, esr_ohm=0.010, esl_h=4.5e-10, mount_l_h=4.0e-10, provenance="typical_engineering_value: 待 vendor 实测替换"),
            DecapSpec(part="d1u", c_f=1.0e-6, esr_ohm=0.015, esl_h=4.0e-10, mount_l_h=4.0e-10, provenance="typical_engineering_value: 待 vendor 实测替换"),
            DecapSpec(part="d100n", c_f=1.0e-7, esr_ohm=0.020, esl_h=4.0e-10, mount_l_h=4.0e-10, provenance="typical_engineering_value: 待 vendor 实测替换"),
        ]
        np.testing.assert_array_equal(pdn_impedance_profile(vrm, specs_bulk, specs_dec, f), z)

    def test_pdn_profile_empty_network_explicit_infinite(self) -> None:
        f = np.array([1.0e6, 1.0e7])
        z = pdn_impedance_profile(None, None, None, f)
        assert np.all(np.isinf(z.real))
        assert np.all(z.imag == 0.0)

    def test_antiresonance_peak_vs_lc_analytic_bitwise(self) -> None:
        # 理想无损双电容：Y=1/Z1+1/Z2=0 ⇒ Z1+Z2=0 ⇒ ω²=(1/C1+1/C2)/(L1+L2)
        # 即 f_peak=1/(2π√(L_eff·C_eff))，L_eff=L1+L2、C_eff=C1C2/(C1+C2)
        c1, l1 = 1.0e-7, 4.0e-10
        c2, l2 = 1.0e-5, 2.0e-9
        f_peak = math.sqrt((c1 + c2) / (c1 * c2 * (l1 + l2))) / (2.0 * math.pi)
        c_eff = c1 * c2 / (c1 + c2)
        f_analytic_alt = 1.0 / (2.0 * math.pi * math.sqrt((l1 + l2) * c_eff))
        assert f_peak == pytest.approx(f_analytic_alt, rel=1.0e-12)
        f_grid = np.concatenate([
            np.geomspace(1.0e6, f_peak / 2.0, 40),
            np.array([f_peak]),  # 解析峰位作为栅格点（逐位）
            np.geomspace(f_peak * 2.0, 1.0e8, 40),
        ])
        z = pdn_impedance_profile(None, None, [(c1, 0.0, l1, 0.0), (c2, 0.0, l2, 0.0)], f_grid)
        f_argmax = f_grid[int(np.argmax(np.abs(z)))]
        assert f_argmax == f_peak  # 逐位：回收峰=解析峰
        # 峰位夹在两支路自谐振频率之间（反谐振物理形态：一支呈感性、另一支呈容性）
        srf1 = 1.0 / (2.0 * math.pi * math.sqrt(l1 * c1))
        srf2 = 1.0 / (2.0 * math.pi * math.sqrt(l2 * c2))
        assert min(srf1, srf2) < f_peak < max(srf1, srf2)
        # 峰阻抗远超两支路端口量级（反谐振尖峰形态，非平缓并联）
        z_at_peak = np.abs(z[int(np.argmax(np.abs(z)))])
        z_neighbor = np.abs(z[int(np.argmax(np.abs(z))) - 1])
        assert z_at_peak > 100.0 * z_neighbor


# ─── 判据 2：口径钉 ──────────────────────────────────────────────────────────


class TestTargetImpedanceProfiles:
    def test_flat_vs_smith_profile_delta_band(self) -> None:
        f = np.geomspace(1.0e5, 1.0e9, 500)
        fc = 1.0e7
        z_flat = target_impedance_freq(f, 0.05, 2.0, "flat")
        z_smith = target_impedance_freq(f, 0.05, 2.0, "smith", corner_freq_hz=fc)
        z0 = 0.05 / 2.0
        # flat：全带恒定（逐位）
        assert np.all(z_flat == z0)
        # smith：拐点前平坦（逐位）、拐点后 −20dB/dec 即 z0·fc/f（逐位）
        below = f <= fc
        assert np.all(z_smith[below] == z0)
        assert np.all(z_smith[~below] == z0 * fc / f[~below])
        # 差带显式报告：两口径对同一 profile 的差只在拐点以上出现，=20log10(f/fc)
        # （z0/(z0·fc/f) 与 f/fc 有 ulp 级舍入差，用 1e-12 相对容差断言形态）
        diff_db = 20.0 * np.log10(z_flat / z_smith)
        assert np.all(diff_db[below] == 0.0)
        np.testing.assert_allclose(diff_db[~below], 20.0 * np.log10(f[~below] / fc), rtol=1.0e-12, atol=0.0)
        max_diff_db = float(diff_db.max())
        # 500× 频带（1e5→1e9）smith 口径在带缘收紧 20log10(1e9/1e7)=40dB
        assert max_diff_db == pytest.approx(40.0, rel=1.0e-9)
        assert max_diff_db > 0.0  # 频率依赖口径比恒定口径更严（收紧方向正确）

    def test_target_impedance_freq_input_validation(self) -> None:
        f = np.array([1.0e6, 1.0e7])
        with pytest.raises(ValueError, match="corner_freq_hz"):
            target_impedance_freq(f, 0.05, 2.0, "smith")
        with pytest.raises(ValueError, match="flat"):
            target_impedance_freq(f, 0.05, 2.0, "flat", corner_freq_hz=1.0e7)
        with pytest.raises(ValueError, match="profile"):
            target_impedance_freq(f, 0.05, 2.0, "novak", corner_freq_hz=1.0e7)
        with pytest.raises(ValueError, match="corner_freq_hz"):
            target_impedance_freq(f, 0.05, 2.0, "smith", corner_freq_hz=0.0)


# ─── 判据 3：优化钉 ──────────────────────────────────────────────────────────


def _greedy_pool() -> list[DecapSpec]:
    """同质 cost=1 候选池（整数预算=贪心路径前缀包含，单调性成立的前提）。"""
    pool: list[DecapSpec] = []
    for _ in range(3):
        pool.append(DecapSpec(part="10uF", c_f=1.0e-5, esr_ohm=0.010, esl_h=4.5e-10, mount_l_h=4.0e-10, provenance="typical_engineering_value: 待 vendor 实测替换"))
    for _ in range(3):
        pool.append(DecapSpec(part="1uF", c_f=1.0e-6, esr_ohm=0.015, esl_h=4.0e-10, mount_l_h=4.0e-10, provenance="typical_engineering_value: 待 vendor 实测替换"))
    for _ in range(6):
        pool.append(DecapSpec(part="100nF", c_f=1.0e-7, esr_ohm=0.020, esl_h=4.0e-10, mount_l_h=4.0e-10, provenance="typical_engineering_value: 待 vendor 实测替换"))
    return pool


_GREEDY_F = np.geomspace(1.0e5, 1.0e8, 200)
_GREEDY_BASELINE_VRM = VrmModel(r0=5.0e-3, l0=20.0e-9, r1=0.02, l1=1.0e-9)
_GREEDY_BASELINE_BULK = [(1.0e-4, 0.01, 2.0e-9, 1.0e-9)]


class TestGreedySelect:
    def test_greedy_feasible_synthetic_demand(self) -> None:
        zt = target_impedance_freq(_GREEDY_F, 0.1, 1.0, "flat")  # 0.1Ω 全带
        result = greedy_decap_select(
            _greedy_pool(), zt, _GREEDY_F, budget=12,
            baseline_vrm=_GREEDY_BASELINE_VRM, baseline_caps=_GREEDY_BASELINE_BULK,
        )
        assert isinstance(result, GreedyResult)
        assert result.feasible and not result.infeasible
        assert result.excess == 0.0
        assert result.total_cost <= 12.0
        # 全带 Z ≤ Z_target（判据 3 可行性口径，线性域逐频）
        assert np.all(np.abs(result.z_profile) <= result.z_target)
        assert np.all(result.margin_db >= 0.0)
        assert 0 < result.n_selected <= 12

    def test_greedy_budget_monotone(self) -> None:
        # 成本单调（同等条件下加预算不劣化）：同质 cost 池、整数预算 → 路径前缀
        zt = target_impedance_freq(_GREEDY_F, 0.1, 1.0, "flat")
        r_small = greedy_decap_select(
            _greedy_pool(), zt, _GREEDY_F, budget=4,
            baseline_vrm=_GREEDY_BASELINE_VRM, baseline_caps=_GREEDY_BASELINE_BULK,
        )
        r_big = greedy_decap_select(
            _greedy_pool(), zt, _GREEDY_F, budget=12,
            baseline_vrm=_GREEDY_BASELINE_VRM, baseline_caps=_GREEDY_BASELINE_BULK,
        )
        assert r_small.n_selected <= r_big.n_selected
        assert r_small.total_cost <= r_big.total_cost
        assert r_big.excess <= r_small.excess  # 增预算不劣化
        max_excess_small = float(np.max(np.abs(r_small.z_profile) - r_small.z_target))
        max_excess_big = float(np.max(np.abs(r_big.z_profile) - r_big.z_target))
        assert max_excess_big <= max_excess_small

    def test_greedy_infeasible_honest(self) -> None:
        # 不可行需求（1mΩ 全带）：候选全加完仍超标 → 显式 infeasible，不凑解
        zt = np.full(_GREEDY_F.shape, 1.0e-3)
        result = greedy_decap_select(
            _greedy_pool(), zt, _GREEDY_F, budget=99,
            baseline_vrm=_GREEDY_BASELINE_VRM, baseline_caps=_GREEDY_BASELINE_BULK,
        )
        assert result.infeasible and not result.feasible
        assert result.excess > 0.0
        # 预算 99 足够吞下全池：不凑解=把改善用尽后如实报 infeasible
        assert result.n_selected == len(_greedy_pool())
        assert result.total_cost == float(len(_greedy_pool()))

    def test_greedy_deterministic(self) -> None:
        zt = target_impedance_freq(_GREEDY_F, 0.1, 1.0, "flat")
        kw: dict[str, object] = {"baseline_vrm": _GREEDY_BASELINE_VRM, "baseline_caps": _GREEDY_BASELINE_BULK}
        r1 = greedy_decap_select(_greedy_pool(), zt, _GREEDY_F, budget=8, **kw)  # type: ignore[arg-type]
        r2 = greedy_decap_select(_greedy_pool(), zt, _GREEDY_F, budget=8, **kw)  # type: ignore[arg-type]
        assert r1.selected_indices == r2.selected_indices
        assert r1.total_cost == r2.total_cost
        np.testing.assert_array_equal(r1.z_profile, r2.z_profile)

    def test_greedy_input_validation(self) -> None:
        # 标量 target 合法广播；数组长度不符才报错
        ok = greedy_decap_select(_greedy_pool(), 0.1, _GREEDY_F[:10], budget=1)
        assert ok.z_target.shape == (10,)
        with pytest.raises(ValueError, match="z_target"):
            greedy_decap_select(_greedy_pool(), np.full(5, 0.1), _GREEDY_F, budget=1)
        with pytest.raises(ValueError, match="budget"):
            greedy_decap_select(_greedy_pool(), 0.1, _GREEDY_F, budget=-1.0)


# ─── 判据 4：DC-bias 钉 ──────────────────────────────────────────────────────


class TestDcBias:
    def test_lookup_on_grid_bitwise(self) -> None:
        # 栅格点查表逐位（np.interp 节点与端点返回精确值）
        c, status = dc_bias_effective_c(16.0e-6, 4.0, CURVE_V, CURVE_C)
        assert status == "derated"
        assert c == 4.0e-6
        c, status = dc_bias_effective_c(16.0e-6, 2.0, CURVE_V, CURVE_C)
        assert status == "derated"
        assert c == 8.0e-6

    def test_interpolation_linear(self) -> None:
        # 线性插值：v=1.0 → (16+8)/2=12µF（中点，rtol 1e-15 内=逐位至 ulp）
        c, status = dc_bias_effective_c(16.0e-6, 1.0, CURVE_V, CURVE_C)
        assert status == "derated"
        assert c == pytest.approx(12.0e-6, rel=1.0e-15)
        # 端点外夹持不外推（v=10V → 夹到末点 4µF，如实不虚构外推段）
        c, status = dc_bias_effective_c(16.0e-6, 10.0, CURVE_V, CURVE_C)
        assert status == "derated"
        assert c == 4.0e-6

    def test_no_curve_marker_and_no_bias(self) -> None:
        c, status = dc_bias_effective_c(1.0e-7, 3.3, None, None)
        assert (c, status) == (1.0e-7, "no_derating")  # 无曲线如实标记，不虚构
        c, status = dc_bias_effective_c(1.0e-7, 0.0, CURVE_V, CURVE_C)
        assert (c, status) == (1.0e-7, "no_bias")
        with pytest.raises(ValueError):
            dc_bias_effective_c(1.0e-7, 1.0, [4.0, 2.0], [1e-6, 1e-6])  # 电压非升序
        with pytest.raises(ValueError):
            dc_bias_effective_c(1.0e-7, 1.0, [0.0, 2.0], [1e-6])  # 长度不符

    def test_decap_spec_effective_c_path(self) -> None:
        with_curve = DecapSpec(
            part="10uF_x5r", c_f=1.0e-5, esr_ohm=0.01, esl_h=4.5e-10,
            provenance="typical_engineering_value: 待 vendor 实测替换",
            dc_bias_curve=((0.0, 1.0e-5), (3.3, 5.9e-6), (5.0, 4.8e-6)),
        )
        c, status = with_curve.effective_c(5.0)
        assert status == "derated" and c == 4.8e-6
        without = DecapSpec(part="100n", c_f=1.0e-7, esr_ohm=0.02, esl_h=4.0e-10, provenance="typical_engineering_value: 待 vendor 实测替换")
        assert without.effective_c(5.0) == (1.0e-7, "no_derating")


# ─── 判据 5：腔模钉 ──────────────────────────────────────────────────────────


class TestCavityModes:
    def test_cavity_mode_frequencies_closed_form(self) -> None:
        a, b, er = 0.05, 0.04, 4.4
        modes = plane_cavity_modes(a, b, er, 3, 3)
        assert len(modes) == (3 + 1) * (3 + 1) - 1  # (0,0) 直流模排除
        assert all(isinstance(mode, CavityMode) for mode in modes)
        freqs = [mode.f_hz for mode in modes]
        assert freqs == sorted(freqs)  # 升序
        # 逐模式独立闭式回收（测试侧按 hypot 独立书写，非照抄实现式）
        for mode in modes:
            expected = (299792458.0 / (2.0 * math.sqrt(er))) * math.hypot(mode.m / a, mode.n / b)
            assert mode.f_hz == pytest.approx(expected, rel=1.0e-12)
        # 手算锚：(1,0) 模 = c0/(2√εr·a)
        f10 = next(mode.f_hz for mode in modes if (mode.m, mode.n) == (1, 0))
        assert f10 == pytest.approx(299792458.0 / (2.0 * math.sqrt(4.4) * 0.05), rel=1.0e-15)
        with pytest.raises(ValueError):
            plane_cavity_modes(0.05, 0.04, 4.4, -1, 2)
        with pytest.raises(ValueError):
            plane_cavity_modes(0.05, 0.0, 4.4, 1, 2)

    def test_mount_position_clearance_negative_example(self) -> None:
        a = b = 0.05
        er = 4.4
        # 反例一：位置正落波腹（角点 (0,0) 是一切模的波腹）→ too_close，余量为负
        verdict = mount_position_clearance(0.0, 0.0, a, b, er, 1, 0)
        assert verdict.verdict == "too_close"
        assert verdict.distance_m == 0.0
        assert verdict.margin_m < 0.0
        assert verdict.antinode_x_m == 0.0
        # 反例二：模自身谐振频率下缺省半波长口径=波腹间距，任何位置必然违约
        # （如实声明判据退化面，见 mount_position_clearance docstring）
        center = mount_position_clearance(0.025, 0.025, a, b, er, 1, 0)
        assert center.verdict == "too_close"
        assert center.distance_m == pytest.approx(0.025, rel=1.0e-12)
        assert center.required_m == pytest.approx(center.wavelength_m / 2.0)

    def test_mount_position_clearance_positive_example(self) -> None:
        a = b = 0.05
        er = 4.4
        f10 = 299792458.0 / (2.0 * math.sqrt(er) * a)
        # 正例：λ 在 8×f10 处评估（关心扰动频率为时钟谐波类场景），板中心远离波腹
        verdict = mount_position_clearance(0.025, 0.025, a, b, er, 1, 0, f_hz=8.0 * f10)
        assert verdict.verdict == "clear"
        assert verdict.distance_m == pytest.approx(0.025, rel=1.0e-12)
        assert verdict.margin_m > 0.0
        assert verdict.required_m == pytest.approx(0.5 * 299792458.0 / (8.0 * f10 * math.sqrt(er)))
        # threshold_frac 口径参数生效：收紧到 0.05 后更容易 clear
        relaxed = mount_position_clearance(0.025, 0.025, a, b, er, 1, 0, threshold_frac=0.05)
        assert relaxed.verdict == "clear"
        assert relaxed.required_m == pytest.approx(0.05 * relaxed.wavelength_m)


# ─── decap 库 schema + yaml 加载 ─────────────────────────────────────────────


class TestDecapLibrary:
    def test_default_library_loads_and_validates(self) -> None:
        lib = load_decap_library()
        assert len(lib) >= 6  # 首批 6-10 条目
        curve_count = 0
        for part_id, spec in lib.items():
            assert isinstance(spec, DecapSpec)
            assert part_id
            assert spec.c_f > 0.0
            assert spec.esr_ohm >= 0.0
            assert spec.esl_h >= 0.0
            assert spec.provenance.startswith("typical_engineering_value")
            assert "待 vendor 实测替换" in spec.provenance
            if spec.dc_bias_curve is not None:
                curve_count += 1
                vs = spec.curve_v or ()
                assert list(vs) == sorted(vs)
        assert curve_count >= 1  # 至少一条带 DC-bias 曲线
        assert curve_count < len(lib)  # 且存在无曲线条目（no_derating 路径有实体）

    def test_default_library_path_points_at_configs(self) -> None:
        from rfauto.core.pdn import DEFAULT_LIBRARY_PATH

        assert DEFAULT_LIBRARY_PATH == REPO / "configs" / "decap_library.yaml"
        assert DEFAULT_LIBRARY_PATH.exists()

    def test_missing_provenance_rejected(self) -> None:
        with pytest.raises(ValueError, match="provenance"):
            DecapSpec(part="x", c_f=1.0e-7, esr_ohm=0.02, esl_h=4.0e-10, provenance="  ")
        with pytest.raises(ValueError, match="provenance"):
            DecapSpec.from_dict("bad", {"part": "x", "c_f": 1e-7, "esr_ohm": 0.02, "esl_h": 4e-10})

    def test_from_dict_validation_and_roundtrip(self) -> None:
        with pytest.raises(ValueError, match="c_f"):
            DecapSpec(part="x", c_f=-1.0, esr_ohm=0.02, esl_h=4.0e-10, provenance="p")
        with pytest.raises(ValueError, match="esr_ohm"):
            DecapSpec(part="x", c_f=1e-7, esr_ohm=float("nan"), esl_h=4.0e-10, provenance="p")
        with pytest.raises(ValueError, match="dc_bias_curve"):
            DecapSpec(part="x", c_f=1e-7, esr_ohm=0.02, esl_h=4.0e-10, provenance="p", dc_bias_curve=((0.0, 1e-6),))
        with pytest.raises(ValueError, match="严格升序"):
            DecapSpec(part="x", c_f=1e-7, esr_ohm=0.02, esl_h=4.0e-10, provenance="p", dc_bias_curve=((2.0, 1e-6), (1.0, 9e-7)))
        with pytest.raises(ValueError, match="必须是映射"):
            DecapSpec.from_dict("bad", "not-a-mapping")  # type: ignore[arg-type]
        spec = DecapSpec(
            part="demo 10uF", c_f=1.0e-5, esr_ohm=0.01, esl_h=4.5e-10, provenance="typical p",
            mount_l_h=4.0e-10, dc_bias_curve=((0.0, 1.0e-5), (5.0, 4.8e-6)), cost=2.5, notes="n",
        )
        restored = DecapSpec.from_dict("demo_10uf", spec.to_dict())
        assert restored.part == spec.part
        assert restored.c_f == spec.c_f
        assert restored.mount_l_h == spec.mount_l_h
        assert restored.dc_bias_curve == spec.dc_bias_curve
        assert restored.cost == spec.cost
        assert restored.notes == spec.notes
        # 缺省字段往返：mount/cost/notes 不落 dict 时取缺省
        minimal = DecapSpec(part="m", c_f=1e-7, esr_ohm=0.02, esl_h=4.0e-10, provenance="p")
        re_min = DecapSpec.from_dict("m", minimal.to_dict())
        assert re_min.mount_l_h == 0.0 and re_min.cost == 1.0 and re_min.notes == ""

    def test_library_yaml_inline_comment_discipline(self) -> None:
        # #324：yaml 值内禁止半角空格+'#' 的行内引注（会被当注释截断）——全库
        # 扫描条目字符串值，'#' 只允许出现在整行注释行首
        text = (REPO / "configs" / "decap_library.yaml").read_text(encoding="utf-8")
        assert not re.search(r": .+ #", text.replace("http://", "").replace("https://", ""))
