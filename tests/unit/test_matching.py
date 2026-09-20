"""E6b 匹配网络与滤波器综合单元测试。

验收标准：
① L-section 闭式解正确性
② Chebyshev g 值对拍
③ Commensurate line 结构完整性
④ L/π/T 匹配网络闭式解 vs skrf 对拍（C14 锚，±0.1dB）
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.matching import (
    LCElement,
    MatchNetworkResult,
    chebyshev_g_values,
    synthesize_chebyshev_filter,
    synthesize_commensurate_line,
    synthesize_l_match,
    synthesize_l_section,
    synthesize_match_network,
    synthesize_pi_match,
    synthesize_t_match,
    to_skrf_network,
)


class TestLSection:
    """L-section 匹配网络测试。"""

    def test_high_pass_topology(self):
        """Z_load > Z_source: 高通型。"""
        r = synthesize_l_section(50, 200, 2.4)
        assert r.topology == "high_pass"
        assert r.z1 > 0
        assert r.z2 > 0

    def test_low_pass_topology(self):
        """Z_load < Z_source: 低通型。"""
        r = synthesize_l_section(50, 25, 2.4)
        assert r.topology == "low_pass"

    def test_equal_impedance(self):
        """Z_source = Z_load: bypass。"""
        r = synthesize_l_section(50, 50, 2.4)
        assert r.topology == "bypass"

    def test_element_values_positive(self):
        """元件值应为正。"""
        r = synthesize_l_section(50, 100, 2.4)
        assert r.l_series_nh > 0
        assert r.c_shunt_pf > 0

    def test_to_dict(self):
        r = synthesize_l_section(50, 100, 2.4)
        d = r.to_dict()
        assert "topology" in d
        assert "z_source" in d


class TestLSectionLegacyLabel0bf:
    """0bf：legacy synthesize_l_section 的 topology 标签处置（标注不改行为）。

    标签是历史工况记号（RL>Rs→"high_pass"、RL<Rs→"low_pass"），与元件的
    实际响应型相反：RL>Rs = 串联电感+并联电容（低通梯形）、RL<Rs = 串联
    电容+并联电感（高通梯形）。行为兼容约束：标签字符串与闭式元件值逐字节
    不变（上面 TestLSection 钉住）；本类钉住"标签↔元件"映射与闭式解的
    共轭匹配物理（独立裁判 #118），防后续"顺手改名"破坏既有消费方。
    """

    @staticmethod
    def _input_impedance_shunt_at_load(z_load: float, series_reactance: float,
                                       shunt_reactance: float) -> complex:
        """并联支路跨负载侧：Z_in = jXs + (RL ∥ jB)。"""
        parallel = (z_load * complex(0.0, shunt_reactance)) / (
            z_load + complex(0.0, shunt_reactance))
        return complex(0.0, series_reactance) + parallel

    @staticmethod
    def _input_impedance_shunt_at_source(z_load: float, series_reactance: float,
                                         shunt_reactance: float) -> complex:
        """并联支路跨源侧：Z_in = jB ∥ (RL + jXs)（大电阻侧挂并联的排布）。"""
        series_total = z_load + complex(0.0, series_reactance)
        return (complex(0.0, shunt_reactance) * series_total) / (
            complex(0.0, shunt_reactance) + series_total)

    def test_high_load_label_maps_to_series_l_shunt_c(self):
        """RL>Rs（标签 "high_pass"）：真实元件 = l_series_nh + c_shunt_pf（跨负载），f0 精确共轭匹配。"""
        from rfauto.core.matching import synthesize_l_section

        rs, rl, f0 = 50.0, 200.0, 2.4
        r = synthesize_l_section(rs, rl, f0)
        assert r.topology == "high_pass"  # 遗留字符串，行为兼容不动
        omega = 2.0 * math.pi * f0 * 1e9
        x_series = omega * r.l_series_nh * 1e-9          # 串联电感电抗 = +z1
        b_shunt = -1.0 / (omega * r.c_shunt_pf * 1e-12)  # 并联电容电纳 = -z2
        z_in = self._input_impedance_shunt_at_load(rl, x_series, b_shunt)
        assert abs(z_in - rs) < 1e-6 * rs, z_in

    def test_low_load_label_maps_to_series_c_shunt_l(self):
        """RL<Rs（标签 "low_pass"）：真实元件 = 串 C(z2，靠负载) + 并 L(z1，跨源)，f0 精确共轭匹配。"""
        from rfauto.core.matching import synthesize_l_section

        rs, rl = 50.0, 25.0
        r = synthesize_l_section(rs, rl, 2.4)
        assert r.topology == "low_pass"  # 遗留字符串，行为兼容不动
        # 正确排布（docstring 0bf 注记）：串联电容模值 = z2（c_series_pf 取 z1，
        # 故经 1/(ω·C) 反推须用 z2 对应容值），并联电感模值 = z1
        x_series = -r.z2                       # 串联电容电抗 = -z2
        b_shunt = r.z1                          # 并联电感电抗 = +z1
        z_in = self._input_impedance_shunt_at_source(rl, x_series, b_shunt)
        assert abs(z_in - rs) < 1e-6 * rs, z_in

    def test_low_load_property_name_mapping_is_swapped(self):
        """0bf 歧义核心钉：RL<Rs 按 c_series_pf(z1)/l_shunt_nh(z2) 属性名画网络
        （两种标准排布都试）均**得不到**共轭匹配——属性↔位置映射在本分支相反
        （行为兼容不改值，只如实标注，本测试防歧义被静默"顺手修正"）。"""
        from rfauto.core.matching import synthesize_l_section

        rs, rl, f0 = 50.0, 25.0, 2.4
        r = synthesize_l_section(rs, rl, f0)
        # 按属性名的字面排布：串联模值 z1、并联模值 z2
        x_series, b_shunt = -r.z1, r.z2
        z_at_load = self._input_impedance_shunt_at_load(rl, x_series, b_shunt)
        z_at_source = self._input_impedance_shunt_at_source(rl, x_series, b_shunt)
        assert abs(z_at_load - rs) > 0.1 * rs, z_at_load
        assert abs(z_at_source - rs) > 0.1 * rs, z_at_source

    def test_labels_are_case_markers_not_responses(self):
        """标注本身：标签与响应型相反（RL>Rs 的"high_pass"实为低通梯形元件）。"""
        from rfauto.core.matching import synthesize_l_section

        high = synthesize_l_section(50.0, 200.0, 2.4)
        low = synthesize_l_section(50.0, 25.0, 2.4)
        # RL>Rs："high_pass" 标签 ↔ 串联电感+并联电容（低通梯形结构）
        assert high.l_series_nh > 0 and high.c_shunt_pf > 0
        # RL<Rs："low_pass" 标签 ↔ 串联电容+并联电感（高通梯形结构）
        assert low.c_series_pf > 0 and low.l_shunt_nh > 0
        # 新代码的正确口径：synthesize_l_match 的 response 显式且语义无歧义
        ref = synthesize_l_match(50.0, 200.0, 2.4, response="low_pass")
        assert ref.elements[0].kind == "C" and ref.elements[1].kind == "L"


class TestChebyshevFilter:
    """Chebyshev 滤波器综合测试。"""

    def test_g_values_length(self):
        """g 值长度 = order + 2。"""
        g = chebyshev_g_values(5, 0.5)
        assert len(g) == 7  # g0..g5 + g_load

    def test_g0_is_1(self):
        """g0 = 1（源阻抗归一化）。"""
        g = chebyshev_g_values(3, 0.5)
        assert g[0] == 1.0

    def test_odd_order_load_is_1(self):
        """奇数阶：负载 g = 1。"""
        g = chebyshev_g_values(3, 0.5)
        assert g[-1] == 1.0

    def test_even_order_load_not_1(self):
        """偶数阶：负载 g != 1。"""
        g = chebyshev_g_values(4, 0.5)
        assert g[-1] != 1.0

    def test_synthesize(self):
        """综合入口。"""
        r = synthesize_chebyshev_filter(5, 0.5, 2.0)
        assert r.order == 5
        assert r.cutoff_ghz == 2.0
        assert len(r.element_values) == 7

    def test_to_dict(self):
        r = synthesize_chebyshev_filter(3, 0.5, 2.4)
        d = r.to_dict()
        assert d["type"] == "chebyshev"
        assert d["order"] == 3


class TestCommensurateLine:
    """Commensurate line 滤波器测试。"""

    def test_structure(self):
        """结构完整性。"""
        r = synthesize_commensurate_line(5, 2.0)
        assert r.order == 5
        assert len(r.impedances) == 5
        assert all(deg == 90.0 for deg in r.line_lengths_deg)

    def test_impedances_positive(self):
        """阻抗应为正。"""
        r = synthesize_commensurate_line(3, 2.4)
        assert all(z > 0 for z in r.impedances)

    def test_to_dict(self):
        r = synthesize_commensurate_line(3, 2.4)
        d = r.to_dict()
        assert d["type"] == "commensurate_line"


# ─── C14 锚：L/π/T 匹配闭式解 vs skrf（§10.22 #24）────────────────────────────

def _skrf_s11(result: MatchNetworkResult, freqs_ghz) -> np.ndarray:
    """闭式解 → skrf 集总网络 → S11 数组（源端参考阻抗 = Rs）。"""
    network = to_skrf_network(result, freqs_ghz)
    return np.asarray(network.s[:, 0, 0])


def _skrf_depth_db(result: MatchNetworkResult, f_ghz: float) -> float:
    s11 = complex(_skrf_s11(result, [f_ghz])[0])
    magnitude = abs(s11)
    return math.inf if magnitude == 0.0 else -20.0 * math.log10(magnitude)


class TestLMatchClosedForm:
    """L 型匹配闭式解（Pozar §5.1 Q 匹配：Q = sqrt(R_big/R_small − 1)）。"""

    def test_textbook_reference_values(self):
        """手算文献锚：50→100Ω @1GHz（L=7.9577nH/C=1.5915pF）、50→200Ω @2.45GHz。"""
        omega1 = 2.0 * math.pi * 1.0e9
        first = synthesize_l_match(50.0, 100.0, 1.0)
        assert first.q == pytest.approx(1.0, rel=1e-12)
        assert first.elements[1].value_nh == pytest.approx(7.9577, rel=1e-4)   # 串联 L
        assert first.elements[0].value_pf == pytest.approx(1.5915, rel=1e-4)   # 并联 C
        assert first.elements[1].value == pytest.approx(50.0 / omega1, rel=1e-12)

        second = synthesize_l_match(50.0, 200.0, 2.45)
        assert second.q == pytest.approx(math.sqrt(3.0), rel=1e-12)
        assert second.elements[1].value_nh == pytest.approx(5.6258, rel=1e-4)
        assert second.elements[0].value_pf == pytest.approx(0.5626, rel=1e-4)

    def test_resistance_branches_placement(self):
        """Rs>RL 与 Rs<RL 两支：并联支路跨接较大电阻、串联支路串较小电阻。"""
        omega = 2.0 * math.pi * 2.4e9
        high = synthesize_l_match(50.0, 200.0, 2.4)   # RL > Rs
        assert [(e.role, e.kind) for e in high.elements] == [("shunt", "C"), ("series", "L")]
        assert high.elements[0].value == pytest.approx(high.q / (omega * 200.0), rel=1e-12)
        assert high.elements[1].value == pytest.approx(high.q * 50.0 / omega, rel=1e-12)

        low = synthesize_l_match(200.0, 50.0, 2.4)    # RL < Rs
        assert [(e.role, e.kind) for e in low.elements] == [("series", "L"), ("shunt", "C")]
        assert low.q == pytest.approx(high.q, rel=1e-12)
        assert low.elements[0].value == pytest.approx(low.q * 50.0 / omega, rel=1e-12)
        assert low.elements[1].value == pytest.approx(low.q / (omega * 200.0), rel=1e-12)
        assert high.match_depth_db() > 200.0
        assert low.match_depth_db() > 200.0

    def test_high_pass_is_reactance_dual(self):
        """high_pass 与 low_pass 在同 f0 的电抗/电纳量值相同、符号相反。"""
        omega = 2.0 * math.pi * 2.4e9
        low = synthesize_l_match(50.0, 200.0, 2.4, response="low_pass")
        high = synthesize_l_match(50.0, 200.0, 2.4, response="high_pass")
        assert low.q == pytest.approx(high.q, rel=1e-12)
        assert [(e.role, e.kind) for e in high.elements] == [("shunt", "L"), ("series", "C")]
        assert abs(high.elements[1].impedance(omega)) == pytest.approx(
            abs(low.elements[1].impedance(omega)), rel=1e-12
        )
        assert abs(1.0 / high.elements[0].impedance(omega)) == pytest.approx(
            abs(1.0 / low.elements[0].impedance(omega)), rel=1e-12
        )
        assert high.match_depth_db() > 200.0

    def test_equal_resistance_is_bypass(self):
        """Rs == RL：Q=0、无元件、输入阻抗等于 Rs。"""
        result = synthesize_l_match(50.0, 50.0, 2.4)
        assert result.q == 0.0
        assert result.elements == []
        assert result.input_impedance() == pytest.approx(50.0 + 0j)
        assert result.to_dict()["elements"] == []

    def test_bandwidth_is_inverse_q(self):
        result = synthesize_l_match(50.0, 200.0, 2.4)
        assert result.bandwidth_frac == pytest.approx(1.0 / math.sqrt(3.0), rel=1e-12)


class TestPiTClosedForm:
    """π/T 型匹配闭式解（虚拟电阻 Rv，Q = Q1 + Q2）。"""

    def test_pi_equal_resistance_closed_form(self):
        """Rs=RL=100、Q=4：Rv=R/(1+Q²/4)=20Ω，串联 L=80/ω、并联 C=0.02/ω。"""
        omega = 2.0 * math.pi * 2.0e9
        result = synthesize_pi_match(100.0, 100.0, 2.0, q=4.0)
        assert result.topology == "pi"
        assert result.q == pytest.approx(4.0, rel=1e-12)
        assert result.virtual_resistance == pytest.approx(20.0, rel=1e-9)
        assert (result.elements[1].kind, result.elements[1].role) == ("L", "series")
        assert result.elements[1].value == pytest.approx(80.0 / omega, rel=1e-9)
        for shunt in (result.elements[0], result.elements[2]):
            assert (shunt.kind, shunt.role) == ("C", "shunt")
            assert shunt.value == pytest.approx(0.02 / omega, rel=1e-9)
        assert result.match_depth_db() > 200.0

    def test_t_equal_resistance_closed_form(self):
        """Rs=RL=100、Q=4：Rv=R(1+Q²/4)=500Ω，串联 L 各 200/ω、中间并联 C=0.008/ω。"""
        omega = 2.0 * math.pi * 2.0e9
        result = synthesize_t_match(100.0, 100.0, 2.0, q=4.0)
        assert result.topology == "T"
        assert result.virtual_resistance == pytest.approx(500.0, rel=1e-9)
        assert [e.role for e in result.elements] == ["series", "shunt", "series"]
        assert result.elements[0].value == pytest.approx(200.0 / omega, rel=1e-9)
        assert result.elements[2].value == pytest.approx(200.0 / omega, rel=1e-9)
        assert result.elements[1].value == pytest.approx((4.0 / 500.0) / omega, rel=1e-9)
        assert result.match_depth_db() > 200.0

    def test_q_decomposition_and_virtual_resistance_bounds(self):
        """q = Q1 + Q2；π 的 Rv < min(Rs,RL)，T 的 Rv > max(Rs,RL)。"""
        pi = synthesize_pi_match(50.0, 200.0, 2.4, q=3.0)
        assert pi.virtual_resistance is not None
        rv_pi = pi.virtual_resistance
        assert rv_pi < 50.0
        assert math.sqrt(50.0 / rv_pi - 1.0) + math.sqrt(200.0 / rv_pi - 1.0) == pytest.approx(3.0, rel=1e-9)

        tee = synthesize_t_match(50.0, 200.0, 2.4, q=3.0)
        assert tee.virtual_resistance is not None
        rv_t = tee.virtual_resistance
        assert rv_t > 200.0
        assert math.sqrt(rv_t / 50.0 - 1.0) + math.sqrt(rv_t / 200.0 - 1.0) == pytest.approx(3.0, rel=1e-9)

    def test_bandwidth_input_matches_q_input(self):
        """bandwidth_frac=1/q 与直接给 q 的元件值完全一致（high_pass 亦同）。"""
        by_q = synthesize_pi_match(50.0, 200.0, 2.4, q=5.0, response="high_pass")
        by_bw = synthesize_pi_match(50.0, 200.0, 2.4, bandwidth_frac=0.2, response="high_pass")
        assert by_bw.q == pytest.approx(by_q.q, rel=1e-12)
        assert by_bw.virtual_resistance == pytest.approx(by_q.virtual_resistance, rel=1e-12)
        for left, right in zip(by_q.elements, by_bw.elements, strict=True):
            assert left == right

    def test_higher_q_narrows_matching_bandwidth(self):
        """更高 Q → -10dB 匹配带宽单调收窄。"""

        def offset_at_10db(q_value: float) -> float:
            result = synthesize_pi_match(50.0, 200.0, 2.4, q=q_value)
            for offset in np.linspace(0.0, 0.9, 901):
                if result.match_depth_db(2.4 * (1.0 + float(offset))) < 10.0:
                    return float(offset)
            return 1.0

        assert offset_at_10db(6.0) < offset_at_10db(3.0) < offset_at_10db(2.0)


class TestSkrfCrossCheck:
    """闭式元件值 → skrf 网络 → |S11|@f0 与理论匹配深度一致（±0.1dB）。"""

    @pytest.mark.parametrize("response", ["low_pass", "high_pass"])
    @pytest.mark.parametrize("z_source,z_load", [(50.0, 200.0), (50.0, 25.0), (200.0, 50.0)])
    @pytest.mark.parametrize("topology", ["L", "pi", "T"])
    def test_match_depth_at_f0(self, topology, z_source, z_load, response):
        kwargs = {} if topology == "L" else {"q": 3.0}
        result = synthesize_match_network(topology, z_source, z_load, 2.4, response=response, **kwargs)
        assert result.match_depth_db() >= 60.0
        assert _skrf_depth_db(result, 2.4) >= 60.0
        assert abs(result.s11() - complex(_skrf_s11(result, [2.4])[0])) < 1e-9

    @pytest.mark.parametrize("topology", ["L", "pi", "T"])
    def test_closed_form_vs_skrf_across_band_within_0p1db(self, topology):
        """0.7~1.3·f0 扫频：闭式回波损耗 vs skrf 逐点 |Δ| < 0.1dB（排除零点邻域）。"""
        kwargs = {} if topology == "L" else {"q": 3.0}
        result = synthesize_match_network(topology, 50.0, 200.0, 2.4, **kwargs)
        freqs = np.linspace(0.7 * 2.4, 1.3 * 2.4, 61)
        simulated = _skrf_s11(result, freqs)
        checked = 0
        for freq, s11 in zip(freqs, simulated, strict=True):
            magnitude = abs(complex(s11))
            sim_db = math.inf if magnitude == 0.0 else -20.0 * math.log10(magnitude)
            if sim_db > 60.0:   # 零点邻域两侧都趋于 -inf，无有效 dB 比较
                continue
            assert abs(result.match_depth_db(float(freq)) - sim_db) < 0.1
            checked += 1
        assert checked >= 55

    def test_high_pass_skrf_match_at_other_frequency(self):
        result = synthesize_l_match(50.0, 25.0, 5.8, response="high_pass")
        assert _skrf_depth_db(result, 5.8) >= 60.0


class TestMatchValidation:
    """非法输入必须显式报错（不静默产出错误元件值）。"""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"z_source": 0.0, "z_load": 50.0, "f0_ghz": 2.4},
            {"z_source": -50.0, "z_load": 50.0, "f0_ghz": 2.4},
            {"z_source": float("nan"), "z_load": 50.0, "f0_ghz": 2.4},
            {"z_source": float("inf"), "z_load": 50.0, "f0_ghz": 2.4},
            {"z_source": 50.0, "z_load": 0.0, "f0_ghz": 2.4},
            {"z_source": 50.0, "z_load": -1.0, "f0_ghz": 2.4},
            {"z_source": 50.0, "z_load": 50.0, "f0_ghz": 0.0},
            {"z_source": 50.0, "z_load": 50.0, "f0_ghz": -2.4},
        ],
    )
    def test_rejects_invalid_scalars(self, kwargs):
        with pytest.raises(ValueError):
            synthesize_l_match(**kwargs)
        with pytest.raises(ValueError):
            synthesize_pi_match(**kwargs, q=3.0)

    def test_rejects_unknown_response(self):
        with pytest.raises(ValueError):
            synthesize_l_match(50.0, 200.0, 2.4, response="band_pass")

    @pytest.mark.parametrize("topology", ["pi", "T"])
    def test_pi_t_reject_q_at_l_limit(self, topology):
        q_min = math.sqrt(200.0 / 50.0 - 1.0)
        with pytest.raises(ValueError):
            synthesize_match_network(topology, 50.0, 200.0, 2.4, q=q_min)
        with pytest.raises(ValueError):
            synthesize_match_network(topology, 50.0, 200.0, 2.4, q=q_min / 2.0)

    @pytest.mark.parametrize("topology", ["pi", "T"])
    def test_pi_t_require_exactly_one_q_source(self, topology):
        with pytest.raises(ValueError):
            synthesize_match_network(topology, 50.0, 200.0, 2.4)
        with pytest.raises(ValueError):
            synthesize_match_network(topology, 50.0, 200.0, 2.4, q=3.0, bandwidth_frac=0.25)
        with pytest.raises(ValueError):
            synthesize_match_network(topology, 50.0, 200.0, 2.4, bandwidth_frac=0.0)

    def test_rejects_unknown_topology(self):
        with pytest.raises(ValueError):
            synthesize_match_network("gamma", 50.0, 200.0, 2.4)

    def test_l_match_dispatcher_rejects_explicit_q(self):
        with pytest.raises(ValueError):
            synthesize_match_network("L", 50.0, 200.0, 2.4, q=3.0)

    def test_skrf_network_rejects_bypass(self):
        """Rs == RL（无元件）时构造 skrf 网络应显式报错。"""
        with pytest.raises(ValueError):
            to_skrf_network(synthesize_l_match(50.0, 50.0, 2.4), [2.4])


class TestFrequencyScalingAndDeterminism:
    """三次频率一致性、确定性、结果辅助接口。"""

    def test_element_values_scale_with_inverse_frequency(self):
        """L、C 均 ∝ 1/f：三次不同频率下 f·L、f·C 恒定，且各自匹配。"""
        frequencies = (0.9, 2.4, 5.8)
        results = [synthesize_l_match(50.0, 200.0, f0) for f0 in frequencies]
        for result in results:
            assert result.match_depth_db() > 200.0
        for index in range(2):
            products = [r.elements[index].value * f0 for r, f0 in zip(results, frequencies, strict=True)]
            assert products[0] == pytest.approx(products[1], rel=1e-12)
            assert products[1] == pytest.approx(products[2], rel=1e-12)

    def test_synthesis_is_deterministic(self):
        first = synthesize_pi_match(50.0, 200.0, 2.4, q=3.5)
        second = synthesize_pi_match(50.0, 200.0, 2.4, q=3.5)
        assert first == second
        assert first.to_dict() == second.to_dict()
        third = synthesize_t_match(50.0, 25.0, 1.8, bandwidth_frac=0.1)
        fourth = synthesize_t_match(50.0, 25.0, 1.8, bandwidth_frac=0.1)
        assert third == fourth
        assert third.virtual_resistance == fourth.virtual_resistance

    def test_result_helpers_and_skrf_input_guard(self):
        result = synthesize_pi_match(50.0, 200.0, 2.4, q=3.0)
        assert result.input_impedance() == pytest.approx(50.0 + 0j, abs=1e-6)
        assert result.s11_db() < -200.0
        assert result.s11(2.4, z_ref=100.0) != result.s11(2.4)
        payload = result.to_dict()
        assert payload["type"] == "match_network"
        assert payload["topology"] == "pi"
        assert payload["virtual_resistance_ohm"] is not None
        assert len(payload["elements"]) == 3
        assert isinstance(result.elements[0], LCElement)
        assert MatchNetworkResult.__name__ == "MatchNetworkResult"
        with pytest.raises(ValueError):
            to_skrf_network(result, freqs_ghz=[])
        with pytest.raises(ValueError):
            to_skrf_network(result, freqs_ghz=[2.4, -1.0])

    def test_lc_element_accessors(self):
        inductor = LCElement("L", "series", 5e-9)
        capacitor = LCElement("C", "shunt", 2e-12)
        assert inductor.value_nh == pytest.approx(5.0)
        assert inductor.value_pf == pytest.approx(5000.0)
        assert "series" in inductor.display
        assert capacitor.value_pf == pytest.approx(2.0)
        assert capacitor.to_dict()["role"] == "shunt"
        with pytest.raises(AttributeError):   # frozen dataclass
            inductor.value = 2e-9
