"""F-K.A 物理极限守卫四件单元测试。

判据 = 方案书 F-K.A「合成已知负载回收（构造达界/超界例）」+ #118 独立解析钉：
每个手算例在注释里给出独立算式（与实现不同的算术路径），数值断言显式
rtol/atol；负数/零参数显式 ValueError；参数不足判 undefined 不炸不虚构。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.bounds import (
    SPEED_OF_LIGHT_M_S,
    BoundVerdict,
    bbox_to_ka,
    bode_fano_rc,
    chu_q_bound,
    cohn_il_lower_bound,
    directivity_bounds,
)


def _parallel_rc_impedance(r: float, c: float, f_hz: np.ndarray) -> np.ndarray:
    """并联 RC 精确模型 Z = R/(1+jωRC)（合成已知负载的货源）。"""
    omega = 2.0 * np.pi * f_hz
    return r / (1.0 + 1j * omega * r * c)


class TestBodeFanoRc:
    """Bode-Fano 匹配可行性门：达界/超界回收 + 双输入路径同解。"""

    def test_at_boundary_margin_zero(self):
        """达界例：Γm 按 Δω·ln(1/Γm)=π/RC 反解 → margin≈0（逐位级）。

        手算：R=50, C=1pF → τ=5e-11 s，π/τ=6.283185307e10 rad/s；
        Δf=2 GHz → Δω=1.2566370614e10；ln(1/Γm)=π/(τ·Δω)=5.0 → Γm=e⁻⁵。
        """
        r, c, bw = 50.0, 1e-12, 2e9
        tau = r * c
        gamma_m = math.exp(-1.0 / (2.0 * tau * bw))
        v = bode_fano_rc((r, c), None, gamma_target=gamma_m, bandwidth=bw)
        assert v.limit_value == pytest.approx(math.pi / tau, rel=1e-12)
        assert v.margin is not None
        # margin = π/τ − Δω·ln(1/Γm)，构造上恒等，残差只允许浮点舍入
        assert abs(v.margin) <= 1e-12 * v.limit_value
        assert abs(v.margin_ratio) <= 1e-12
        # 贴界（裕度比 ≤5%）按 marginal 判——Fano 等式需无穷阶网络
        assert v.verdict == "marginal"
        assert v.load_kind == "explicit_rc"
        assert v.tau_s == pytest.approx(5e-11, rel=1e-15)

    def test_wider_band_same_gamma_unreachable(self):
        """超界例：同 Γm 加宽带宽 → 实际积分超界 → unreachable。

        手算：Γm=e⁻⁵ 不变，Δf=3 GHz → 实际=1.8849555922e10·5=9.4248e10
        > π/τ=6.2832e10，margin=−3.1416e10 <0。
        """
        r, c = 50.0, 1e-12
        tau = r * c
        gamma_m = math.exp(-1.0 / (2.0 * tau * 2e9))
        v = bode_fano_rc((r, c), None, gamma_target=gamma_m, bandwidth=3e9)
        assert v.verdict == "unreachable"
        assert v.margin is not None and v.margin < 0.0
        assert v.margin == pytest.approx(-math.pi / tau / 2.0, rel=1e-9)

    def test_relaxed_target_reachable(self):
        """宽裕量例：Γm=0.5、Δf=2 GHz → 裕度比 0.8614 >5% → reachable。

        手算：实际占用=1.2566370614e10·ln2=8.7103e9，占用比=8.7103/62.832
        =0.1386；margin_ratio 是裕度口径 (limit−actual)/limit=1−0.1386
        =0.8614（首版断言误把占用比当裕度比——已按独立重算纠正）。
        """
        v = bode_fano_rc((50.0, 1e-12), None, gamma_target=0.5, bandwidth=2e9)
        assert v.verdict == "reachable"
        assert v.margin is not None and v.margin > 0.0
        assert v.margin_ratio == pytest.approx(0.8614, abs=5e-4)
        # 互逆自洽：占用比 + 裕度比 = 1
        assert 1.0 - v.margin_ratio == pytest.approx(0.1386, abs=5e-4)

    def test_explicit_and_fitted_paths_agree(self):
        """显式 (R,C) 与阻抗数组拟合两输入路径同解（精确模型数据回收）。

        手算：R=50, C=2pF 的精确 Z 采样经 Y=1/R+jωC 线性最小二乘应精确
        还原 R、C（无噪数据 → G=1/R 常数、Im(Y)=ωC 严格线性）。
        """
        r, c = 50.0, 2e-12
        f = np.linspace(0.1e9, 5e9, 201)
        z = _parallel_rc_impedance(r, c, f)
        v_exp = bode_fano_rc((r, c), None, gamma_target=0.5, bandwidth=1e9)
        v_fit = bode_fano_rc(z, f, gamma_target=0.5, bandwidth=1e9)
        assert v_fit.load_kind == "fitted_rc"
        assert v_fit.r_ohm == pytest.approx(r, rel=1e-9)
        assert v_fit.c_farad == pytest.approx(c, rel=1e-9)
        assert v_fit.verdict == v_exp.verdict
        assert v_fit.limit_value == pytest.approx(v_exp.limit_value, rel=1e-9)
        assert v_fit.margin == pytest.approx(v_exp.margin, rel=1e-9)

    def test_fitted_without_f_raises(self):
        """阻抗数组口径缺配频 f → ValueError。"""
        z = _parallel_rc_impedance(50.0, 2e-12, np.linspace(1e9, 2e9, 8))
        with pytest.raises(ValueError, match="f"):
            bode_fano_rc(z, None, gamma_target=0.5, bandwidth=1e9)

    def test_fitted_length_mismatch_raises(self):
        """f 与阻抗数组不等长 → ValueError。"""
        z = _parallel_rc_impedance(50.0, 2e-12, np.linspace(1e9, 2e9, 3))
        with pytest.raises(ValueError, match="等长"):
            bode_fano_rc(z, np.linspace(1e9, 2e9, 4), gamma_target=0.5, bandwidth=1e9)

    def test_fitted_single_point_raises(self):
        """单点采样不可拟合 → ValueError。"""
        with pytest.raises(ValueError):
            bode_fano_rc(np.array([50.0 + 0j]), np.array([1e9]), gamma_target=0.5, bandwidth=1e9)

    def test_fitted_non_passive_load_raises(self):
        """负实部阻抗（有源/串联口径）→ 拟合电导 ≤0 → ValueError。"""
        z = np.full(16, -50.0 + 10j)
        f = np.linspace(1e9, 2e9, 16)
        with pytest.raises(ValueError, match="并联 RC"):
            bode_fano_rc(z, f, gamma_target=0.5, bandwidth=1e9)

    def test_fitted_zero_impedance_sample_raises(self):
        """阻抗含 0（1/Z 除零）→ ValueError。"""
        z = _parallel_rc_impedance(50.0, 2e-12, np.linspace(1e9, 2e9, 8))
        z[3] = 0.0
        with pytest.raises(ValueError):
            bode_fano_rc(z, np.linspace(1e9, 2e9, 8), gamma_target=0.5, bandwidth=1e9)

    @pytest.mark.parametrize("gamma", [0.0, -0.3, 1.0, 1.2, True])
    def test_invalid_gamma_target_raises(self, gamma):
        """Γm∉(0,1) 及布尔值 → ValueError（0 使 ln(1/Γm)=∞；bool 静默转数拒收）。"""
        with pytest.raises(ValueError):
            bode_fano_rc((50.0, 1e-12), None, gamma_target=gamma, bandwidth=1e9)

    @pytest.mark.parametrize("bw", [0.0, -1e6])
    def test_invalid_bandwidth_raises(self, bw):
        """带宽 ≤0 → ValueError。"""
        with pytest.raises(ValueError):
            bode_fano_rc((50.0, 1e-12), None, gamma_target=0.5, bandwidth=bw)

    @pytest.mark.parametrize("load", [(0.0, 1e-12), (50.0, 0.0), (-50.0, 1e-12)])
    def test_nonpositive_rc_raises(self, load):
        """R/C ≤0 → ValueError。"""
        with pytest.raises(ValueError):
            bode_fano_rc(load, None, gamma_target=0.5, bandwidth=1e9)

    def test_to_dict_roundtrip(self):
        """to_dict 含负载溯源字段且 JSON 友好。"""
        v = bode_fano_rc((50.0, 1e-12), None, gamma_target=0.5, bandwidth=1e9)
        d = v.to_dict()
        assert d["name"] == "bode_fano_parallel_rc"
        assert d["r_ohm"] == 50.0
        assert d["c_farad"] == 1e-12
        assert d["verdict"] == v.verdict

    def test_bode_fano_cross_budget_consistency(self):
        """C16（core/budget）与 F-K.A（本模块）Bode-Fano 闭式同源交叉钉。

        followUp"core/budget+bounds Bode-Fano 合流"闭合载体（薄合流=交叉钉，
        内核各自不动）：同一负载两面闭式必须逐式互证——
        ① 积分界同式：bode_fano_rc.limit == budget.bode_fano_integral_bound(τ)；
        ② Γm↔RL_dB 换算互逆：budget.gamma_from_return_loss(RL)=10^(-RL/20)；
        ③ 界面等价：budget.bode_fano_max_bandwidth(τ,RL) 恰为 bode_fano_rc
          的 margin=0 带宽（Δf_max 满足 Δω·ln(1/Γm)=π/τ）——两面任一改式
          即红。
        """
        from rfauto.core import budget as cb

        r, c = 50.0, 1e-12
        tau = r * c
        # ① 积分界同式
        v = bode_fano_rc((r, c), None, gamma_target=0.5, bandwidth=1e9)
        assert v.limit_value == pytest.approx(
            cb.bode_fano_integral_bound(tau), rel=1e-12)
        # ② Γm↔RL_dB 互逆（独立算术路径：指数式 vs 幂式）
        for rl_db in (3.0, 9.542425099397003, 20.0):
            g = cb.gamma_from_return_loss(rl_db)
            assert g == pytest.approx(10.0 ** (-rl_db / 20.0), rel=1e-12)
            assert -20.0 * math.log10(g) == pytest.approx(rl_db, rel=1e-12)
        # ③ 界面等价：budget 极限带宽处 bounds 门 margin=0。
        # RL 独立算术路径现算 20·log10(3)（kernel 走 rl·ln(10)/20，异路同值；
        # 禁硬编码截断小数——首版常量第 9 位错被本钉当场抓出）
        rl2 = 20.0 * math.log10(3.0)  # VSWR=2，|Γ|=1/3
        g2 = 1.0 / 3.0
        bw_max = cb.bode_fano_max_bandwidth(tau, rl2)
        assert bw_max == pytest.approx(1.0 / (2.0 * tau * math.log(3.0)), rel=1e-12)
        v2 = bode_fano_rc((r, c), None, gamma_target=g2, bandwidth=bw_max)
        assert v2.margin is not None
        assert abs(v2.margin) <= 1e-9 * v2.limit_value
        # 互逆面：budget 对同 (τ, RL) 的极限带宽判定与 bounds 裁决一致
        bfl = cb.bode_fano_limit(
            "parallel_rc", r, rl2, capacitance_f=c)
        assert bfl.max_bandwidth_hz == pytest.approx(bw_max, rel=1e-12)
        assert bfl.gamma_max == pytest.approx(g2, rel=1e-12)
        assert not bfl.within_limit(bw_max * 1.01)  # 1.01× 极限带宽必超界


class TestChuQBound:
    """Chu-Harrington Q 界：McLean 1996 手算逐位回收。"""

    def test_ka1_linear_is_exactly_two(self):
        """ka=1 手算：1/1³+1/1=2（逐位）。"""
        v = chu_q_bound(1.0)
        assert v.limit_value == 2.0
        assert v.polarization == "linear"
        assert v.verdict == "undefined"
        assert v.actual_value is None and v.margin is None

    def test_ka1_circular_halved(self):
        """圆极化减半口径：Q=1（逐位）。"""
        assert chu_q_bound(1.0, polarization="circular").limit_value == 1.0

    def test_ka05_hand(self):
        """ka=0.5 手算：1/0.125+1/0.5=8+2=10（逐位）。"""
        assert chu_q_bound(0.5).limit_value == 10.0
        assert chu_q_bound(0.5, polarization="circular").limit_value == 5.0

    def test_array_vectorized(self):
        """ka 数组向量化：[0.5, 1, 2] → [10, 2, 0.625]（1/8+1/2=0.625）。"""
        v = chu_q_bound(np.array([0.5, 1.0, 2.0]))
        assert isinstance(v.limit_value, np.ndarray)
        np.testing.assert_allclose(v.limit_value, [10.0, 2.0, 0.625], rtol=1e-14)
        v_circ = chu_q_bound(np.array([0.5, 1.0, 2.0]), polarization="circular")
        np.testing.assert_allclose(v_circ.limit_value, [5.0, 1.0, 0.3125], rtol=1e-14)

    def test_monotone_decreasing_in_ka(self):
        """Q_min 随 ka 单调降（物理事实）。"""
        ka = np.linspace(0.2, 3.0, 50)
        q = chu_q_bound(ka).limit_value
        assert np.all(np.diff(q) < 0.0)

    def test_invalid_polarization_raises(self):
        with pytest.raises(ValueError, match="polarization"):
            chu_q_bound(1.0, polarization="elliptical")

    @pytest.mark.parametrize("ka", [0.0, -1.0, float("nan"), float("inf")])
    def test_nonpositive_or_nonfinite_ka_raises(self, ka):
        with pytest.raises(ValueError):
            chu_q_bound(ka)

    def test_ka_array_with_zero_raises(self):
        with pytest.raises(ValueError):
            chu_q_bound(np.array([0.5, 0.0]))

    def test_empty_ka_array_raises(self):
        with pytest.raises(ValueError):
            chu_q_bound(np.array([]))

    def test_to_dict_array_jsonable(self):
        d = chu_q_bound(np.array([0.5, 1.0])).to_dict()
        assert isinstance(d["limit_value"], list)
        assert d["polarization"] == "linear"


class TestBboxToKa:
    """bbox→ka 口径换算：a=最大维度之半，k=2πf/c。"""

    def test_hand_aperture_example(self):
        """2.4 GHz、D_max=40mm：ka=π·D/λ，λ=c/f=124.9135mm → ka≈1.0060。

        独立路径：expected 走 π·D_max/λ（λ=c/f），实现走 2πf/c·D_max/2。
        """
        ka = bbox_to_ka((0.04, 0.03, 0.01), 2.4e9)
        lam = SPEED_OF_LIGHT_M_S / 2.4e9
        assert ka == pytest.approx(math.pi * 0.04 / lam, rel=1e-12)
        assert abs(ka - 1.006) < 1e-3

    def test_dimension_order_irrelevant(self):
        """最大维度选择与维度顺序无关。"""
        assert bbox_to_ka((0.01, 0.04, 0.03), 2.4e9) == pytest.approx(
            bbox_to_ka((0.04, 0.03, 0.01), 2.4e9), rel=1e-15
        )

    @pytest.mark.parametrize("bbox", [(0.0, 0.04), (-0.01, 0.04), (0.04,), (float("nan"), 0.04)])
    def test_invalid_bbox_raises(self, bbox):
        with pytest.raises(ValueError):
            bbox_to_ka(bbox, 2.4e9)

    def test_empty_bbox_raises(self):
        with pytest.raises(ValueError):
            bbox_to_ka([], 2.4e9)

    def test_invalid_frequency_raises(self):
        with pytest.raises(ValueError):
            bbox_to_ka((0.04, 0.03), 0.0)


class TestCohnIlLowerBound:
    """Cohn 插损下限：独立手算钉 + Qu 影响单调。"""

    def test_hand_calculation_against_literal_constant(self):
        """手算：f0=2.4, BW=0.1, g=[1,1.5,1], Qu=1000。

        独立来源（教材字面常数 4.343）：4.343·(2.4/0.1)·3.5/1000
        = 4.343·24·0.0035 = 0.364812 dB。实现用精确常数 10/ln10，
        与字面 4.343 差 ~1.3e-5 相对——rtol=1e-4 内互证。
        """
        il = cohn_il_lower_bound(2.4, 0.1, np.array([1.0, 1.5, 1.0]), 1000.0)
        assert il == pytest.approx(4.343 * 24.0 * 3.5 / 1000.0, rel=1e-4)
        # 同口径精确常数镜像（回程一致，仅作回归钉）
        assert il == pytest.approx((10.0 / math.log(10.0)) * 24.0 * 3.5 / 1000.0, rel=1e-12)

    def test_qu_scaling_is_inverse(self):
        """Qu↑→IL↓ 且严格成反比：IL(Qu/2)=2·IL(Qu)（线性式，逐位级）。"""
        il_1000 = cohn_il_lower_bound(2.4, 0.1, np.array([1.0, 1.5, 1.0]), 1000.0)
        il_500 = cohn_il_lower_bound(2.4, 0.1, np.array([1.0, 1.5, 1.0]), 500.0)
        assert il_500 == pytest.approx(2.0 * il_1000, rel=1e-12)
        assert il_500 > il_1000 > 0.0

    def test_very_high_qu_almost_lossless(self):
        """Qu→∞ 极限：IL 趋 0（仍 >0）。"""
        il = cohn_il_lower_bound(2.4, 0.1, np.array([1.0, 1.5, 1.0]), 1e12)
        assert 0.0 < il < 1e-6

    def test_empty_g_raises(self):
        with pytest.raises(ValueError, match="不能为空"):
            cohn_il_lower_bound(2.4, 0.1, np.array([]), 1000.0)

    @pytest.mark.parametrize(
        "args",
        [
            (0.0, 0.1, [1.0], 1000.0),   # f0=0
            (2.4, -0.1, [1.0], 1000.0),  # BW<0
            (2.4, 0.1, [1.0, 0.0], 1000.0),  # g 含 0
            (2.4, 0.1, [-1.0], 1000.0),  # g<0
            (2.4, 0.1, [1.0, float("nan")], 1000.0),  # g 非有限
            (2.4, 0.1, [1.0], 0.0),      # Qu=0
            (2.4, 0.1, [1.0], True),     # bool 拒收
        ],
    )
    def test_invalid_params_raise(self, args):
        with pytest.raises(ValueError):
            cohn_il_lower_bound(*args)


class TestDirectivityBounds:
    """方向性界：三独立口径手算 + 参数不足 undefined 不炸。"""

    def test_aperture_hand(self):
        """口径面：4πA/λ²，A=0.01 m²、λ=0.125 m → 8.0424772（独立字面钉）。"""
        v = directivity_bounds(area_m2=0.01, wavelength_m=0.125)["aperture_directivity"]
        assert v.limit_value == pytest.approx(8.0424772, abs=1e-6)
        assert v.limit_value == pytest.approx(4.0 * math.pi * 0.01 / 0.125**2, rel=1e-12)
        assert v.verdict == "undefined"  # 信息性界：无目标 D 不判可达

    def test_sphere_hand(self):
        """球包络：(ka)²+2ka，ka=1 → 3（逐位）；ka=1.5 → 2.25+3=5.25（逐位）。"""
        assert directivity_bounds(ka=1.0)["sphere_directivity"].limit_value == 3.0
        assert directivity_bounds(ka=1.5)["sphere_directivity"].limit_value == 5.25

    def test_mimo_min_dof(self):
        """MIMO 自由度：min(4,16)=4；标量 8 按 Nt=Nr → 8。"""
        assert directivity_bounds(n_elements=(4, 16))["mimo_dof"].limit_value == 4.0
        assert directivity_bounds(n_elements=(16, 4))["mimo_dof"].limit_value == 4.0
        assert directivity_bounds(n_elements=8)["mimo_dof"].limit_value == 8.0

    def test_all_keys_always_present(self):
        """三个键恒在，缺参条目=undefined 且 limit=None（不虚构不炸）。"""
        b = directivity_bounds()
        assert set(b) == {"aperture_directivity", "sphere_directivity", "mimo_dof"}
        for key, v in b.items():
            assert v.name == key
            assert v.verdict == "undefined"
            assert v.limit_value is None
            assert v.actual_value is None and v.margin is None

    def test_partial_params_mixed(self):
        """只给 ka：球包络已算、其余 undefined。"""
        b = directivity_bounds(ka=2.0)
        assert b["sphere_directivity"].limit_value == 8.0  # 4+4
        assert b["aperture_directivity"].limit_value is None
        assert b["mimo_dof"].limit_value is None

    def test_all_params_provided(self):
        """三界同时给出且互不影响。"""
        b = directivity_bounds(area_m2=0.01, ka=1.0, n_elements=(2, 8), wavelength_m=0.125)
        assert b["aperture_directivity"].limit_value == pytest.approx(8.0424772, abs=1e-6)
        assert b["sphere_directivity"].limit_value == 3.0
        assert b["mimo_dof"].limit_value == 2.0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"area_m2": 0.0},
            {"area_m2": -0.01},
            {"wavelength_m": -0.125},
            {"wavelength_m": 0.0},
            {"ka": 0.0},
            {"ka": -1.0},
            {"n_elements": 0},
            {"n_elements": (0, 4)},
            {"n_elements": (3.5, 4)},  # 非整数计数
            {"n_elements": (1, 2, 3)},  # 非 (Nt, Nr) 二元组
            {"area_m2": True},  # bool 拒收
        ],
    )
    def test_invalid_params_raise(self, kwargs):
        """已提供但非法（≤0/非有限/非整数）→ 显式 ValueError。"""
        with pytest.raises(ValueError):
            directivity_bounds(**kwargs)


class TestBoundVerdictContract:
    """BoundVerdict 共同接口契约。"""

    def test_invalid_verdict_string_raises(self):
        with pytest.raises(ValueError, match="verdict"):
            BoundVerdict(
                name="x", limit_value=1.0, actual_value=None, margin=None, verdict="pass"
            )

    def test_margin_ratio_none_cases(self):
        """margin 缺失 / limit 非标量 / limit=0 → margin_ratio=None。"""
        v1 = BoundVerdict(name="x", limit_value=1.0, actual_value=0.5, margin=None, verdict="undefined")
        assert v1.margin_ratio is None
        v2 = BoundVerdict(
            name="x", limit_value=np.array([1.0, 2.0]), actual_value=None, margin=None, verdict="undefined"
        )
        assert v2.margin_ratio is None
        v3 = BoundVerdict(name="x", limit_value=0.0, actual_value=0.5, margin=0.5, verdict="unreachable")
        assert v3.margin_ratio is None
