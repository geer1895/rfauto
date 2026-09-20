"""D1 色散材料库单测（§10.4 D1）。

裁判口径（不得自证）：Djordjevic-Sarkar 解析式（文献 [1]）与 openEMS 官方
参考实现 vendor/openEMS/install/share/CSXCAD/matlab/CalcDjordjevicSarkarApprox.m。
全部测试确定性、无网络、无求解器（真机冒烟只在 scripts 侧，可跳过）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from rfauto.core.dispersion import (
    DebyeModel,
    DebyePole,
    DjordjevicSarkar,
    epsilon_analytic_ds,
    fit_djordjevic_sarkar,
    kramers_kronig_residual,
    load_dispersion_material,
)

REPO = Path(__file__).resolve().parents[2]
MATERIALS_YAML = REPO / "configs" / "materials.yaml"
DISPERSION_MATERIAL = "rogers4350b_h0.508_dispersion"

# openEMS CalcDjordjevicSarkarApprox.m（lowFreqEvalType=0）单点拟合口径的参考值，
# 由 D-S 反解闭式独立算出，用于交叉验证 from_single_point 实现。
_OPENEMS_REFERENCE = {
    (4.2, 0.02, 1.0e9, 1.0e6, 2.0e11): {
        "eps_inf": 3.915579818785070,
        "delta_eps": 0.655235481543564,
        "m1": 6.798179868358115,
        "m2": 12.099209864022097,
    },
    (3.66, 0.0037, 10.0e9, 1.0e6, 2.0e11): {
        "eps_inf": 3.633312224330500,
        "delta_eps": 0.108693702174648,
        "m1": 6.798179868358115,
        "m2": 12.099209864022097,
    },
}

#: microwave 频段扫描点（1-40 GHz）
MICROWAVE_FREQS_HZ = np.array([1.0e9, 2.4e9, 5.0e9, 10.0e9, 20.0e9, 40.0e9])


def _microstrip_eps_eff(width_mm, h_mm, freq_hz, eps_r, tand):
    """用 skrf MLine（HJ）算微带有效介电常数 eta_eff(f)（确定性，零求解）。"""
    import skrf

    freq = skrf.Frequency(freq_hz[0] / 1e9, freq_hz[-1] / 1e9, len(freq_hz), unit="GHz")
    mline = skrf.media.MLine(
        frequency=freq,
        w=width_mm * 1e-3,
        h=h_mm * 1e-3,
        ep_r=eps_r,
        tand=tand,
        rho=1.724e-8,
        rough=0.5e-6,
        model="hammerstadjensen",
    )
    eps_eff = getattr(mline, "ep_reff", None)
    if eps_eff is None:
        eps_eff = mline.er_eff
    return np.real(np.asarray(eps_eff))


# ─── Debye 弛豫模型 ───────────────────────────────────────────────────────────

class TestDebyeModel:
    """Debye 单极/多极行为。"""

    def test_single_pole_static_and_high_frequency_limits(self):
        """f→0 收敛到 ε∞+Δε；f→∞ 收敛到 ε∞。"""
        model = DebyeModel(eps_inf=2.0, poles=[DebyePole(3.0, 1.0e9)])
        assert float(model.epsilon_r(1.0)) == pytest.approx(5.0, rel=1e-6)
        assert float(model.epsilon_r(1.0e15)) == pytest.approx(2.0, rel=1e-4)

    def test_imaginary_part_peaks_at_relaxation_frequency(self):
        """ε'' 峰值恰在弛豫频率 f_relax。"""
        pole = DebyePole(3.0, 1.0e9)
        model = DebyeModel(2.0, [pole])
        freqs = np.logspace(6.0, 12.0, 4001)
        eps_imag = -np.asarray(model.epsilon(freqs)).imag
        assert freqs[int(np.argmax(eps_imag))] == pytest.approx(pole.f_relax_hz, rel=1e-3)

    def test_tan_delta_peak_matches_analytic_shift(self):
        """tanδ 峰值在 f_relax·sqrt((ε∞+Δε)/ε∞)（解析式对照）。"""
        eps_inf, delta_eps, f_relax = 2.0, 3.0, 1.0e9
        model = DebyeModel(eps_inf, [DebyePole(delta_eps, f_relax)])
        freqs = np.logspace(6.0, 13.0, 7001)
        tan_delta = np.asarray(model.loss_tangent(freqs))
        expected = f_relax * np.sqrt((eps_inf + delta_eps) / eps_inf)
        assert freqs[int(np.argmax(tan_delta))] == pytest.approx(expected, rel=5e-3)

    def test_multipole_equals_sum_of_single_poles(self):
        """多极模型 = 各单极之和（线性叠加）。"""
        poles = [DebyePole(1.0, 1.0e9), DebyePole(2.0, 1.0e10)]
        combined = DebyeModel(1.5, poles)
        freqs = np.logspace(6.0, 13.0, 51)
        manual = 1.5
        for pole in poles:
            manual = manual + (np.asarray(DebyeModel(1.0, [pole]).epsilon(freqs)) - 1.0)
        np.testing.assert_allclose(np.asarray(combined.epsilon(freqs)), manual, rtol=1e-12)

    def test_to_openems_debye_encoding(self):
        """openEMS Debye 导出字段与弛豫时间口径正确。"""
        model = DebyeModel(2.5, [DebyePole(1.5, 5.0e9)])
        payload = model.to_openems()
        assert payload["model"] == "debye"
        assert payload["epsilon"] == pytest.approx(2.5)
        assert payload["kappa"] == pytest.approx(0.0)
        assert len(payload["poles"]) == 1
        assert payload["poles"][0]["delta_eps"] == pytest.approx(1.5)
        assert payload["poles"][0]["relax_time_s"] == pytest.approx(1.0 / (2.0 * np.pi * 5.0e9))

    def test_kramers_kronig_holds_for_debye_poles(self):
        """每个 Debye 极点满足 K-K，叠加后仍满足。"""
        model = DebyeModel(2.0, [DebyePole(1.0, 1.0e9), DebyePole(0.5, 1.0e11)])
        residual = kramers_kronig_residual(model, np.array([1.0e8, 1.0e9, 1.0e10]))
        assert np.all(np.asarray(residual) < 1e-9)


# ─── Djordjevic-Sarkar ────────────────────────────────────────────────────────

class TestDjordjevicSarkar:
    """D-S 模型：拟合、求值、因果性、openEMS 导出。"""

    def test_low_and_high_frequency_limits(self):
        """f→0 为 ε∞+Δε；f→∞ 为 ε∞。"""
        model = DjordjevicSarkar(3.6333122243305, 0.108693702174648, 1.0e6, 2.0e11)
        assert float(model.epsilon_r(1.0e-3)) == pytest.approx(model.static_eps_r(), rel=1e-6)
        assert float(model.epsilon_r(1.0e18)) == pytest.approx(model.eps_inf, rel=1e-6)

    @pytest.mark.parametrize(
        ("eps_r", "tand", "f_meas", "f1", "f2"),
        [
            (3.66, 0.0037, 10.0e9, 1.0e6, 2.0e11),
            (4.2, 0.02, 1.0e9, 1.0e6, 2.0e11),
            (3.38, 0.0027, 10.0e9, 1.0e6, 1.0e11),
        ],
    )
    def test_single_point_round_trip_is_exact(self, eps_r, tand, f_meas, f1, f2):
        """单点回代：模型在 f_meas 处精确给出 εr 与 tanδ。"""
        model = fit_djordjevic_sarkar(eps_r, tand, f_meas, f1, f2)
        assert float(model.epsilon_r(f_meas)) == pytest.approx(eps_r, rel=1e-9)
        assert float(model.loss_tangent(f_meas)) == pytest.approx(tand, rel=1e-9)

    def test_matches_independent_analytic_closed_form(self):
        """复对数路径与实/虚部独立闭式逐点一致。"""
        model = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        freqs = np.logspace(3.0, 14.0, 401)
        got = np.asarray(model.epsilon(freqs))
        ref = np.asarray(
            epsilon_analytic_ds(model.eps_inf, model.delta_eps, model.f1_hz, model.f2_hz, freqs)
        )
        np.testing.assert_allclose(got, ref, rtol=1e-12, atol=1e-14)

    @pytest.mark.parametrize(
        ("args", "expected"),
        list(_OPENEMS_REFERENCE.items()),
    )
    def test_matches_openems_reference_fit(self, args, expected):
        """与 openEMS 官方参考实现拟合口径逐参数一致。"""
        model = fit_djordjevic_sarkar(*args)
        assert model.eps_inf == pytest.approx(expected["eps_inf"], rel=1e-12)
        assert model.delta_eps == pytest.approx(expected["delta_eps"], rel=1e-12)
        assert model.m1 == pytest.approx(expected["m1"], rel=1e-12)
        assert model.m2 == pytest.approx(expected["m2"], rel=1e-12)

    def test_kramers_kronig_residual_is_tiny(self):
        """数值 K-K 自检：microwave 频段相对残差 < 1e-9（实测 ~1e-14）。"""
        model = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        residual = kramers_kronig_residual(model, MICROWAVE_FREQS_HZ)
        assert np.all(np.asarray(residual) < 1e-9)

    def test_equivalent_debye_structure_and_accuracy(self):
        """多极 Debye 等价结构：极点数 >= 2，实部偏差 < 0.2%。"""
        model = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        debye = model.equivalent_debye()
        assert len(debye.poles) >= 2
        got = np.real(np.asarray(model.epsilon_r(MICROWAVE_FREQS_HZ)))
        approx = np.real(np.asarray(debye.epsilon_r(MICROWAVE_FREQS_HZ)))
        np.testing.assert_allclose(approx, got, rtol=2e-3)

    def test_to_openems_export_contract(self):
        """openEMS 导出契约：多极 Debye 字段 + sarkar 原始参数。"""
        model = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        payload = model.to_openems()
        assert payload["model"] == "djordjevic_sarkar"
        assert payload["sarkar"]["eps_inf"] == pytest.approx(model.eps_inf)
        assert payload["sarkar"]["delta_eps"] == pytest.approx(model.delta_eps)
        assert len(payload["poles"]) >= 2
        for pole in payload["poles"]:
            assert pole["delta_eps"] > 0.0
            assert pole["relax_time_s"] > 0.0
        kwargs = model.to_openems_sarkar_kwargs()
        assert kwargs["f1"] == pytest.approx(1.0e6)
        assert kwargs["f2"] == pytest.approx(2.0e11)
        assert kwargs["epsRMeas"] == pytest.approx(3.66, rel=1e-9)
        assert kwargs["tandMeas"] == pytest.approx(0.0037, rel=1e-9)


# ─── D1 验收：RO4350B 宽带 εeff(f) ───────────────────────────────────────────

class TestAcceptanceRO4350B:
    """§10.4 D1 验收：εeff(f) 单调缓变；10 GHz 与 D-S 理论偏差 <= 2%。"""

    def test_substrate_eps_r_monotonic_and_slow_microwave_scan(self):
        """基板 ε'(f) 在 1-40 GHz 单调非增且总变化 < 2%（实测 ~0.9%）。"""
        model = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        freqs = np.linspace(1.0e9, 40.0e9, 201)
        eps_r = np.real(np.asarray(model.epsilon_r(freqs)))
        assert np.all(np.diff(eps_r) <= 0.0)
        assert (eps_r[0] - eps_r[-1]) / eps_r[0] < 0.02

    def test_microstrip_eps_eff_monotonic_and_slow(self):
        """微带线 εeff(f) 随 D-S 基板单调缓变（skrf HJ 口径，零求解）。"""
        model = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        freqs = np.linspace(1.0e9, 40.0e9, 201)
        eps_eff = _microstrip_eps_eff(
            1.113,
            0.508,
            freqs,
            np.asarray(model.epsilon_r(freqs)),
            np.asarray(model.loss_tangent(freqs)),
        )
        assert np.all(np.diff(eps_eff) <= 0.0)
        assert (eps_eff[0] - eps_eff[-1]) / eps_eff[0] < 0.02

    def test_10ghz_within_2pct_of_ds_theory(self):
        """10 GHz 处：实现 vs 独立 D-S 解析闭式、vs datasheet 单点，偏差 <= 2%。"""
        model = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        f0 = 10.0e9
        measured = float(model.epsilon_r(f0))
        theory = float(
            np.real(epsilon_analytic_ds(model.eps_inf, model.delta_eps, model.f1_hz, model.f2_hz, f0))
        )
        assert abs(measured - theory) / theory <= 0.02
        assert abs(measured - 3.66) / 3.66 <= 0.02

    def test_10ghz_microstrip_eps_eff_matches_single_frequency_ds(self):
        """微带 εeff(10 GHz)：全带色散基板口径 vs 单频 D-S 理论口径，偏差 <= 2%。"""
        model = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        freqs = np.linspace(1.0e9, 40.0e9, 201)
        dispersive = _microstrip_eps_eff(
            1.113,
            0.508,
            freqs,
            np.asarray(model.epsilon_r(freqs)),
            np.asarray(model.loss_tangent(freqs)),
        )
        idx = int(np.argmin(np.abs(freqs - 10.0e9)))
        f0 = freqs[idx]
        eps_r0 = float(np.real(epsilon_analytic_ds(
            model.eps_inf, model.delta_eps, model.f1_hz, model.f2_hz, f0
        )))
        tand0 = float(-np.imag(epsilon_analytic_ds(
            model.eps_inf, model.delta_eps, model.f1_hz, model.f2_hz, f0
        )) / eps_r0)
        reference = _microstrip_eps_eff(
            1.113, 0.508, np.array([f0]), np.array([eps_r0]), np.array([tand0])
        )
        assert abs(dispersive[idx] - reference[0]) / reference[0] <= 0.02


# ─── 输入校验 / 确定性 / 配置一致性 ──────────────────────────────────────────

class TestValidationAndConfig:
    """非法输入、确定性、materials.yaml 一致性。"""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"eps_inf": 0.0, "delta_eps": 0.1, "f1_hz": 1.0e6, "f2_hz": 1.0e11},
            {"eps_inf": 3.0, "delta_eps": -0.1, "f1_hz": 1.0e6, "f2_hz": 1.0e11},
            {"eps_inf": 3.0, "delta_eps": 0.1, "f1_hz": 1.0e11, "f2_hz": 1.0e6},
            {"eps_inf": 3.0, "delta_eps": 0.1, "f1_hz": 0.0, "f2_hz": 1.0e11},
            {"eps_inf": 3.0, "delta_eps": 0.1, "f1_hz": 1.0e6, "f2_hz": 1.0e11, "sigma_dc": -1.0},
        ],
    )
    def test_bad_ds_params_raise(self, kwargs):
        """非法 D-S 参数抛 ValueError。"""
        with pytest.raises(ValueError):
            DjordjevicSarkar(**kwargs)

    def test_bad_frequency_raises(self):
        """非正/非有限频率抛 ValueError。"""
        model = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        for bad in (0.0, -1.0e9, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                model.epsilon_r(bad)

    def test_from_single_point_bad_inputs_raise(self):
        """单点拟合的非法入参抛 ValueError。"""
        with pytest.raises(ValueError):
            fit_djordjevic_sarkar(-3.66, 0.0037, 10.0e9, 1.0e6, 2.0e11)
        with pytest.raises(ValueError):
            fit_djordjevic_sarkar(3.66, -0.01, 10.0e9, 1.0e6, 2.0e11)
        with pytest.raises(ValueError):
            fit_djordjevic_sarkar(3.66, 0.0037, 10.0e9, 2.0e11, 1.0e6)

    def test_bad_debye_inputs_raise(self):
        """非法 Debye 极点/模型抛 ValueError / TypeError。"""
        with pytest.raises(ValueError):
            DebyePole(0.0, 1.0e9)
        with pytest.raises(ValueError):
            DebyePole(1.0, -1.0)
        with pytest.raises(TypeError):
            DebyeModel(1.0, ["not-a-pole"])
        with pytest.raises(ValueError):
            DebyeModel(0.0, [])  # eps_inf 非法

    def test_kramers_kronig_rejects_conductive_model(self):
        """含 σ_DC 的模型暂不支持 K-K 自检（应显式报错而非静默）。"""
        model = DjordjevicSarkar(3.0, 0.1, 1.0e6, 1.0e11, sigma_dc=1.0e-3)
        with pytest.raises(ValueError):
            kramers_kronig_residual(model, 1.0e9)

    def test_same_input_yields_identical_results(self):
        """同输入两次构造完全一致（确定性）。"""
        a = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        b = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        np.testing.assert_array_equal(np.asarray(a.epsilon(MICROWAVE_FREQS_HZ)),
                                      np.asarray(b.epsilon(MICROWAVE_FREQS_HZ)))
        assert a.sarkar_parameters() == b.sarkar_parameters()
        assert a.to_openems()["poles"] == b.to_openems()["poles"]

    def test_config_entry_matches_loaded_model(self):
        """materials.yaml 色散条目与加载出的模型逐字段一致。"""
        with open(MATERIALS_YAML, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        block = data["materials"][DISPERSION_MATERIAL]["dispersion"]
        model = load_dispersion_material(DISPERSION_MATERIAL, MATERIALS_YAML)
        assert block["model"] == "djordjevic_sarkar"
        assert model.f_meas_hz == pytest.approx(block["f_meas_hz"])
        assert model.f1_hz == pytest.approx(block["f1_hz"])
        assert model.f2_hz == pytest.approx(block["f2_hz"])
        assert float(model.epsilon_r(block["f_meas_hz"])) == pytest.approx(block["eps_r_meas"], rel=1e-9)
        assert float(model.loss_tangent(block["f_meas_hz"])) == pytest.approx(block["tan_delta_meas"], rel=1e-9)

    def test_load_unknown_or_nondispersion_material_raises(self):
        """未知材料 / 无 dispersion 子段 → KeyError；缺文件 → FileNotFoundError。"""
        with pytest.raises(KeyError):
            load_dispersion_material("does_not_exist", MATERIALS_YAML)
        with pytest.raises(KeyError):
            load_dispersion_material("copper", MATERIALS_YAML)
        with pytest.raises(FileNotFoundError):
            load_dispersion_material(DISPERSION_MATERIAL, REPO / "configs" / "no_such.yaml")
