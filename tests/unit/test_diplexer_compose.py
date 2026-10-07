"""QW-9 core/diplexer_compose 合成回收钉（判据预声明见模块 docstring；全离线零真机）。

独立来源互证（#118：数值裁判必须独立来源）：
- 臂 standalone 响应 vs emi_filter ABCD 独立路径（Butterworth 律
  |S21|²=1/(1+(f/fc)^{2N})，Pozar §5.1 式 (5.10) 口径）逐位；
- 臂 standalone vs skrf.media 分立元件级联（库路径）互证；
- CR 一阶对闭式恒等式（本仓推导：Z 与 Z0²/Z 并联 Yin 和恒为 Y0）全带数值钉；
- 复合能量守恒=组装口径的代数恒等式（对任意臂成立），跨阶数跨频段（含
  谐振频点）数值验证。

判据口径（#122 先行）：s11_band_ok/complementarity 掩码=两侧通带（挖去
fc·(1±tol) 交越过渡带——T 结 diplexer 交越区回损地板是固有物理，3/3 对
实测 max|S11|≈−6.6 dB，测试如实钉不凑绿）；全带完美匹配仅一阶 CR 对。
"""

from __future__ import annotations

import numpy as np
import pytest
import skrf
from skrf.media import DefinedGammaZ0

from rfauto.core import diplexer_compose as dc
from rfauto.core import emi_filter as ef

FC = 1e9
Z0 = 50.0
F_GRID = np.logspace(6, 10.5, 801)  # 1 MHz – ~3.16 GHz


def _media(f: np.ndarray) -> DefinedGammaZ0:
    fr = skrf.Frequency.from_f(np.asarray(f, dtype=float), unit="Hz")
    return DefinedGammaZ0(frequency=fr, z0=Z0)


def _arm_s21_via_emi_filter(
    f: np.ndarray, elements: list[tuple[str, float]]
) -> np.ndarray:
    """独立路径：emi_filter ABCD 基本件级联 → abcd_to_s → |S21|²（50/50）。"""
    omega = 2.0 * np.pi * f
    abcd = np.ones((f.size, 2, 2), dtype=complex) * np.eye(2)
    for kind, val in elements:
        if kind == "series_L":
            step = ef.abcd_series(1j * omega * val)
        elif kind == "series_C":
            step = ef.abcd_series(1.0 / (1j * omega * val))
        elif kind == "shunt_C":
            step = ef.abcd_parallel(1j * omega * val)
        elif kind == "shunt_L":
            step = ef.abcd_parallel(1.0 / (1j * omega * val))
        else:
            raise AssertionError(f"未知元件 {kind}")
        abcd = ef.abcd_cascade(abcd, step)
    s_mat = ef.abcd_to_s(abcd, Z0, Z0)
    return np.abs(s_mat[:, 1, 0]) ** 2


# ── 原型 g 表 ────────────────────────────────────────────────────────────────


class TestPrototypeG:
    def test_closed_form_matches_textbook_table(self):
        """闭式 vs Pozar Table 5.1 四位小数表值（独立复核，#118）。"""
        for n, textbook in dc.BUTTERWORTH_G_TEXTBOOK.items():
            closed = dc.butterworth_g_values(n)
            assert len(closed) == n
            dev = max(
                abs(a - b) for a, b in zip(closed, textbook, strict=True)
            )
            assert dev <= 5e-4, (n, closed, textbook)

    def test_n3_n5_pinned_values(self):
        assert dc.BUTTERWORTH_G[3] == pytest.approx((1.0, 2.0, 1.0), abs=1e-12)
        assert dc.BUTTERWORTH_G[5] == pytest.approx(
            (0.618034, 1.618034, 2.0, 1.618034, 0.618034), abs=1e-6
        )

    @pytest.mark.parametrize("bad", [0, 6, -1, True, 2.5, "3", None])
    def test_invalid_order_raises(self, bad):
        with pytest.raises(ValueError, match=r"1\.\.5"):
            dc.butterworth_g_values(bad)


# ── CR 一阶对（全带精确锚）───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def cr():
    return dc.diplexer_lpf_hpf(F_GRID, FC, 1, 1)


class TestCrPairExact:

    def test_s11_identically_zero_full_band(self, cr):
        """常阻互补恒等式：Yin 和恒为 Y0 → S11≡0（实测 ~1e-32）。"""
        assert np.max(np.abs(cr["s11"])) <= 1e-12

    def test_energy_conservation_full_band(self, cr):
        p = (
            np.abs(cr["s11"]) ** 2
            + np.abs(cr["s21_lpf_arm"]) ** 2
            + np.abs(cr["s31_hpf_arm"]) ** 2
        )
        assert np.max(np.abs(p - 1.0)) <= 1e-12

    def test_closed_form_response_law(self, cr):
        """复合响应闭式：|S21|²=1/(1+x²)、|S31|²=x²/(1+x²)（x=f/fc）。"""
        x = F_GRID / FC
        p21 = np.abs(cr["s21_lpf_arm"]) ** 2
        p31 = np.abs(cr["s31_hpf_arm"]) ** 2
        assert np.max(np.abs(p21 - 1.0 / (1.0 + x**2))) <= 1e-12
        assert np.max(np.abs(p31 - x**2 / (1.0 + x**2))) <= 1e-12

    def test_crossover_locked_to_fc(self):
        f = np.linspace(0.99e9, 1.01e9, 4001)
        cr = dc.diplexer_lpf_hpf(f, FC, 1, 1)
        assert cr["crossover_ghz"] is not None
        assert abs(cr["crossover_ghz"] * 1e9 / FC - 1.0) <= 1e-9

    def test_minus_3db_exactly_at_fc(self):
        cr = dc.diplexer_lpf_hpf(np.array([0.999e9, FC, 1.001e9]), FC, 1, 1)
        p21 = np.abs(cr["s21_lpf_arm"][1]) ** 2
        p31 = np.abs(cr["s31_hpf_arm"][1]) ** 2
        assert p21 == pytest.approx(0.5, abs=1e-9)
        assert p31 == pytest.approx(0.5, abs=1e-9)

    def test_direction_low_band_s21_dominant(self, cr):
        i = int(np.argmin(np.abs(F_GRID - 0.1 * FC)))
        p21 = np.abs(cr["s21_lpf_arm"][i]) ** 2
        p31 = np.abs(cr["s31_hpf_arm"][i]) ** 2
        assert p21 > 0.98
        assert p21 > 50.0 * p31

    def test_direction_high_band_s31_dominant(self, cr):
        i = int(np.argmin(np.abs(F_GRID - 10.0 * FC)))
        p31 = np.abs(cr["s31_hpf_arm"][i]) ** 2
        p21 = np.abs(cr["s21_lpf_arm"][i]) ** 2
        assert p31 > 0.98
        assert p31 > 50.0 * p21

    def test_cr_element_values_crossover_locked(self, cr):
        """CR 定标回显：L=Z0/ωc（g_eff=1）、C=1/(ωc·Z0)=L/Z0²。"""
        wc = 2.0 * np.pi * FC
        assert cr["element_values"]["lpf"] == [("series_L", Z0 / wc)]
        assert cr["element_values"]["hpf"] == [("series_C", 1.0 / (wc * Z0))]
        assert cr["g_values"]["rule"] == "cr_crossover_locked"

    def test_mixed_order_uses_duality_not_cr(self):
        d = dc.diplexer_lpf_hpf(F_GRID, FC, 1, 3)
        assert d["g_values"]["rule"] == "lp_hp_duality"
        assert d["element_values"]["hpf"][0][0] == "series_C"
        # 标准 N=3 对偶首元件 C=1/(g1·ωc·Z0)，3 阶 g1=1 → 非 CR 值（差 g²倍）。
        wc = 2.0 * np.pi * FC
        g1 = dc.BUTTERWORTH_G[3][0]
        assert d["element_values"]["hpf"][0][1] == pytest.approx(
            1.0 / (g1 * wc * Z0), rel=1e-12
        )


# ── 标准对偶对（≥2 阶）物理 ──────────────────────────────────────────────────


class TestStandardPairPhysics:
    def test_energy_identity_multiple_orders_wide_band(self):
        """能量守恒=代数恒等式：跨阶数、跨频段（含臂内谐振频段）逐点成立。"""
        f = np.logspace(5, 12, 2001)
        for orders in ((2, 2), (3, 3), (4, 4), (5, 5), (2, 4)):
            d = dc.diplexer_lpf_hpf(f, FC, *orders)
            p = (
                np.abs(d["s11"]) ** 2
                + np.abs(d["s21_lpf_arm"]) ** 2
                + np.abs(d["s31_hpf_arm"]) ** 2
            )
            assert np.max(np.abs(p - 1.0)) <= 1e-12, orders

    @pytest.mark.parametrize("orders", [(3, 3), (5, 5)])
    def test_crossover_locked_to_fc_same_order(self, orders):
        f = np.linspace(0.99e9, 1.01e9, 4001)
        d = dc.diplexer_lpf_hpf(f, FC, *orders)
        assert d["crossover_ghz"] is not None
        assert abs(d["crossover_ghz"] * 1e9 / FC - 1.0) <= 1e-9

    def test_crossover_shifts_for_mixed_orders(self):
        """异阶对交越偏移（换臂对称性失效）：2/4 对实测 −15.6%，如实钉。"""
        f = np.logspace(np.log10(0.2e9), np.log10(5e9), 4001)
        d = dc.diplexer_lpf_hpf(f, FC, 2, 4)
        assert d["crossover_ghz"] is not None
        offset = d["crossover_ghz"] * 1e9 / FC - 1.0
        assert offset < -0.1

    def test_transition_return_loss_floor(self):
        """交越区回损地板是固有物理（3/3 对）。

        深通带（x≤0.2）|S11|≤−18 dB，全带最劣实测 ≈−6.6 dB——verdict 据此如实
        FAIL，不凑绿（判据口径=通带挖除交越过渡带，见模块 docstring）。
        """
        d = dc.diplexer_lpf_hpf(F_GRID, FC, 3, 3)
        p11 = np.abs(d["s11"]) ** 2
        deep = F_GRID <= 0.2 * FC
        assert 10.0 * np.log10(np.max(p11[deep])) <= -18.0
        worst_db = 10.0 * np.log10(np.max(p11))
        assert worst_db > -8.0  # 地板实测 −6.6 dB


# ── 独立路径互证（#118）──────────────────────────────────────────────────────


class TestArmIndependentPaths:
    @pytest.mark.parametrize("order", [2, 3, 5])
    def test_lpf_arm_butterworth_law_via_emi_filter(self, order):
        """臂 standalone |S21|² = 1/(1+(f/fc)^{2N})（emi_filter ABCD 独立路径）。"""
        d = dc.diplexer_lpf_hpf(F_GRID, FC, order, order)
        p21 = _arm_s21_via_emi_filter(F_GRID, d["element_values"]["lpf"])
        law = 1.0 / (1.0 + (F_GRID / FC) ** (2 * order))
        assert np.max(np.abs(p21 - law)) <= 1e-12

    def test_lpf_arm_matches_skrf_cascade(self):
        """臂 vs skrf.media 分立元件级联（库路径互证）。"""
        d = dc.diplexer_lpf_hpf(F_GRID, FC, 3, 3)
        p21_ref = _arm_s21_via_emi_filter(F_GRID, d["element_values"]["lpf"])
        m = _media(F_GRID)
        net = None
        for kind, val in d["element_values"]["lpf"]:
            seg = (
                m.inductor(L=val) if kind == "series_L" else m.shunt_capacitor(C=val)
            )
            net = seg if net is None else net ** seg
        p21_skrf = np.abs(net.s[:, 1, 0]) ** 2
        assert np.max(np.abs(p21_skrf - p21_ref)) <= 1e-10

    def test_hpf_arm_butterworth_law_via_emi_filter(self):
        """HPF 臂 standalone 响应=LP 原型经 ω→ωc²/ω 映射（|S21|²=x^{2N}/(1+x^{2N})，
        注意标准对偶对臂 standalone −3dB 在 fc；CR 臂才在 fc/2——口径见模块 docstring）。"""
        d = dc.diplexer_lpf_hpf(F_GRID, FC, 3, 3)
        p21 = _arm_s21_via_emi_filter(F_GRID, d["element_values"]["hpf"])
        x = F_GRID / FC
        law = x**6 / (1.0 + x**6)
        assert np.max(np.abs(p21 - law)) <= 1e-12


# ── verdict 判据 ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def cr_data():
    return dc.diplexer_lpf_hpf(F_GRID, FC, 1, 1)


@pytest.fixture(scope="module")
def std33_data():
    return dc.diplexer_lpf_hpf(F_GRID, FC, 3, 3)


class TestDiplexerVerdict:

    def test_pass_on_cr_pair(self, cr_data):
        v = dc.diplexer_verdict(cr_data, FC)
        assert v["overall"] == "pass"
        assert v["energy_conservation_ok"] is True
        assert v["crossover_at_fc"] is True
        assert v["s11_band_ok"] is True
        assert v["complementarity"] is True

    def test_crossover_fail_on_wrong_fc(self, cr_data):
        v = dc.diplexer_verdict(cr_data, 1.5 * FC)
        assert v["crossover_at_fc"] is False
        assert v["overall"] == "fail"

    def test_fail_on_energy_violating_input(self, cr_data):
        bad = dict(cr_data)
        # 放大主导分量 s21（CR 对 |S11|≈1e-16，放大它无效果）→ 能量守恒破坏。
        bad["s21_lpf_arm"] = np.asarray(cr_data["s21_lpf_arm"], dtype=complex) * 1.05
        v = dc.diplexer_verdict(bad, FC)
        assert v["energy_conservation_ok"] is False
        assert v["overall"] == "fail"

    def test_crossover_recomputed_not_trusted(self, cr_data):
        """verdict 从 S 数组重算交越，不信任携带字段（病态输入也如实判）。"""
        spoof = dict(cr_data)
        spoof["crossover_ghz"] = 5.0
        v = dc.diplexer_verdict(spoof, FC)
        assert v["crossover_at_fc"] is True
        assert v["overall"] == "pass"

    def test_standard_33_honest_s11_fail(self, std33_data):
        """3/3 标准对：能量/交越绿、通带回损门/互补如实 FAIL（固有地板）。"""
        v = dc.diplexer_verdict(std33_data, FC)
        assert v["energy_conservation_ok"] is True
        assert v["crossover_at_fc"] is True
        assert v["s11_band_ok"] is False
        assert v["complementarity"] is False
        assert v["overall"] == "fail"
        # 互补亏缺 ≡ |S11|²（能量守恒），实测最劣应与 S11 最劣一致量级。
        assert v["complementarity_worst_deficit"] > v["complementarity_rtol"]

    def test_unknown_when_band_mask_empty(self):
        f = np.linspace(0.95e9, 1.05e9, 21)  # 全部落在 fc±10% 过渡带内
        data = dc.diplexer_lpf_hpf(f, FC, 1, 1)
        v = dc.diplexer_verdict(data, FC)
        assert v["s11_band_ok"] is None
        assert v["complementarity"] is None
        assert v["energy_conservation_ok"] is True
        assert v["overall"] == "unknown"

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"s11_max_db": 0.0}, "s11_max_db"),
            ({"s11_max_db": 3.0}, "s11_max_db"),
            ({"s11_max_db": True}, "s11_max_db"),
            ({"crossover_tol_frac": 0.0}, "crossover_tol_frac"),
            ({"crossover_tol_frac": 1.0}, "crossover_tol_frac"),
            ({"crossover_tol_frac": True}, "crossover_tol_frac"),
        ],
    )
    def test_gate_validation(self, cr_data, kwargs, match):
        with pytest.raises(ValueError, match=match):
            dc.diplexer_verdict(cr_data, FC, **kwargs)

    def test_missing_key_raises(self, cr_data):
        bad = {k: v for k, v in cr_data.items() if k != "s11"}
        with pytest.raises(ValueError, match="s11"):
            dc.diplexer_verdict(bad, FC)

    def test_length_mismatch_raises(self, cr_data):
        bad = dict(cr_data)
        bad["s21_lpf_arm"] = np.asarray(cr_data["s21_lpf_arm"])[:-1]
        with pytest.raises(ValueError, match="长度不一致"):
            dc.diplexer_verdict(bad, FC)

    def test_non_mapping_raises(self):
        with pytest.raises(ValueError, match="Mapping"):
            dc.diplexer_verdict([1, 2, 3], FC)


# ── 入参守卫 ─────────────────────────────────────────────────────────────────


class TestInputGuards:
    @pytest.mark.parametrize(
        "fc", [0.0, -1e9, float("nan"), float("inf"), True, "1e9"]
    )
    def test_bad_fc_raises(self, fc):
        with pytest.raises(ValueError, match="fc_hz"):
            dc.diplexer_lpf_hpf(F_GRID, fc)

    @pytest.mark.parametrize("orders", [(0, 3), (3, 6), (True, 3), (2.5, 3), (3, "2")])
    def test_bad_order_raises(self, orders):
        with pytest.raises(ValueError, match=r"1\.\.5"):
            dc.diplexer_lpf_hpf(F_GRID, FC, *orders)

    @pytest.mark.parametrize("z0", [0.0, -50.0, float("nan"), True])
    def test_bad_z0_raises(self, z0):
        with pytest.raises(ValueError, match="z0"):
            dc.diplexer_lpf_hpf(F_GRID, FC, z0=z0)

    @pytest.mark.parametrize(
        "f_bad",
        [
            np.array([0.0, 1e9]),
            np.array([-1e9, 1e9]),
            np.array([1e9, np.nan]),
            np.array([1e9, np.inf]),
            np.zeros((2, 2)),
            np.array([]),
            True,
        ],
    )
    def test_bad_freq_axis_raises(self, f_bad):
        with pytest.raises(ValueError, match="f_axis_hz"):
            dc.diplexer_lpf_hpf(f_bad, FC)
