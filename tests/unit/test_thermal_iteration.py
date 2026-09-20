"""D3-3 双向定点迭代温漂内核单测（core/thermal_iteration.py）。

裁判口径（#118：裁判 = 外部独立来源，不是被测实现的自我推导）：
  * 一阶温漂闭式：Pozar《Microwave Engineering》谐振器温漂
    df0/f0 = -CTE dT - (1/2) TCDk dT。本模块另给独立实现
    closed_form_drift_ratio，且与 core/calculators.py 的
    resonator_thermal_drift 逐值互证（两条独立代码路径）。
  * 微带 eps_eff/Z0：skrf MLine（Hammerstad-Jensen）独立实现对照。
  * 表面电阻：Rs = 1/(sigma*delta)（趋肤深度闭式，Pozar §1.7.1）。
  * 单端口谐振器吸收率：beta=1 临界耦合全吸收、beta<1 的
    4beta/(1+beta)^2 代数闭式（Pozar §6.4）。
  * 合成线性定点映射 T_{n+1} = a + b T_n 的解析不动点 a/(1-b)，
    以及对 b>1 的发散判据——映射与不动点由测试独立构造。

确定性：无网络、无真机、无随机、无文件 IO。
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import thermal_iteration as ti

# ─── 合成算例常量（测试独立定义，不取自被测模块）───────────────────────────
F0_SYNTH_HZ = 1.0e9
K_F_PER_K = 1.0e-4  # 合成 f0 线性温度系数 [1/K]
Q_SYNTH = 100.0
T_REF = 25.0
# 微带参考算例：eps_r=10.2、h=1.27 mm、w=1.2 mm（w/h<1）、L=24 mm -> ~2.39 GHz
EPS_R_REF = 10.2
TCDK_PPM = 50.0
CTE_PPM = 17.0
H_M = 0.00127
W_M = 0.0012
L_M = 0.024


# ─── 助手 ────────────────────────────────────────────────────────────────────

def _standard_geometry() -> ti.ResonatorGeometry:
    return ti.ResonatorGeometry(length_m=L_M, width_m=W_M, height_m=H_M)


def _standard_model(**overrides) -> ti.MaterialTemperatureModel:
    params: dict = {
        "eps_r_ref": EPS_R_REF,
        "sigma_ref": 5.8e7,
        "tan_delta_ref": 1e-3,
        "tcdk_ppm_per_k": TCDK_PPM,
        "cte_ppm_per_k": CTE_PPM,
    }
    params.update(overrides)
    return ti.MaterialTemperatureModel(**params)


def _linear_em(state: ti.MaterialState, temperature_c: float) -> ti.EMEvaluation:
    """合成 EM：f0 关于 T 严格线性，Qu 常数。"""
    return ti.EMEvaluation(
        f0_hz=F0_SYNTH_HZ * (1.0 + K_F_PER_K * (temperature_c - T_REF)),
        q_unloaded=Q_SYNTH,
    )


def _linear_loss(c0: float, c1: float):
    """合成损耗：P_diss(T) = c0 + c1*(T - T_REF)，闭式不动点可解析。"""
    def loss(em: ti.EMEvaluation, temperature_c: float) -> float:
        return c0 + c1 * (temperature_c - T_REF)

    return loss


def _analytic_fixed_point(c0: float, c1: float, rth: float, ambient_c: float) -> float:
    """T* = (T_amb + R_th (c0 - c1 T_ref)) / (1 - R_th c1)。"""
    return (ambient_c + rth * (c0 - c1 * T_REF)) / (1.0 - rth * c1)


# ─── 1. 温度相关材料模型 ─────────────────────────────────────────────────────

class TestMaterialTemperatureModel:
    def test_linear_temperature_law_exact(self):
        model = ti.MaterialTemperatureModel(
            eps_r_ref=10.0, sigma_ref=5.8e7, tan_delta_ref=1e-3,
            tcdk_ppm_per_k=100.0, tan_delta_tempco_ppm_per_k=2000.0,
            sigma_tempco_per_k=-0.004, cte_ppm_per_k=17.0, t_ref_c=25.0)
        state = model.evaluate(85.0)  # dT = 60 K
        assert state.eps_r == pytest.approx(10.0 * (1.0 + 100e-6 * 60.0))
        assert state.tan_delta == pytest.approx(1e-3 * (1.0 + 2000e-6 * 60.0))
        assert state.sigma_s_per_m == pytest.approx(5.8e7 * (1.0 - 0.004 * 60.0))
        assert state.length_scale == pytest.approx(1.0 + 17e-6 * 60.0)

    def test_quadratic_coefficient_changes_state(self):
        quad = ti.MaterialTemperatureModel(
            eps_r_ref=10.0, tcdk_ppm_per_k=100.0, tcdk2_ppm_per_k2=10.0)
        linear = ti.MaterialTemperatureModel(eps_r_ref=10.0)
        state = quad.evaluate(85.0)  # dT = 60 K
        assert state.eps_r == pytest.approx(10.0 * (1.0 + 100e-6 * 60.0 + 10e-6 * 60.0 ** 2))
        assert state.eps_r != linear.evaluate(85.0).eps_r

    def test_polynomial_extrapolation_out_of_physics_raises(self):
        model = ti.MaterialTemperatureModel(eps_r_ref=3.0, tcdk_ppm_per_k=1.0e6)
        with pytest.raises(ValueError):
            model.evaluate(0.0)  # dT=-25 -> 因子 1-25 < 0，非物理，显式报错

    def test_reference_temperature_state_is_identity(self):
        model = _standard_model()
        state = model.evaluate(T_REF)
        assert state.eps_r == pytest.approx(EPS_R_REF)
        assert state.length_scale == pytest.approx(1.0)
        assert state.temperature_c == pytest.approx(T_REF)


# ─── 2. 微带准静态闭式：skrf 独立实现对照 ────────────────────────────────────

class TestMicrostripClosedForms:
    def test_effective_permittivity_matches_skrf_mlines(self):
        import skrf

        media = skrf.media.MLine(
            frequency=skrf.Frequency(2.4, 2.4, 1, unit="GHz"),
            w=W_M, h=H_M, ep_r=EPS_R_REF, tand=0.0, model="hammerstadjensen")
        skrf_eps_eff = float(media.ep_reff[0].real)
        kernel = ti.microstrip_effective_permittivity(EPS_R_REF, W_M / H_M)
        assert kernel == pytest.approx(skrf_eps_eff, rel=0.02)

    def test_characteristic_impedance_matches_skrf_mlines(self):
        import skrf

        media = skrf.media.MLine(
            frequency=skrf.Frequency(2.4, 2.4, 1, unit="GHz"),
            w=W_M, h=H_M, ep_r=EPS_R_REF, tand=0.0, model="hammerstadjensen")
        skrf_z0 = float(media.z0[0].real)
        eps_eff = ti.microstrip_effective_permittivity(EPS_R_REF, W_M / H_M)
        kernel = ti.microstrip_characteristic_impedance(eps_eff, W_M / H_M)
        assert kernel == pytest.approx(skrf_z0, rel=0.02)

    def test_surface_resistance_matches_skin_depth_identity(self):
        freq_hz, sigma = 2.4e9, 5.8e7
        delta = math.sqrt(2.0 / (2.0 * math.pi * freq_hz * ti.MU0_H_PER_M * sigma))
        assert ti.surface_resistance(freq_hz, sigma) == pytest.approx(
            1.0 / (sigma * delta), rel=1e-12)

    def test_microstrip_f0_decreases_with_temperature(self):
        model = _standard_model()
        geometry = _standard_geometry()
        assert ti.evaluate_resonator_f0(model, geometry, 85.0) < ti.evaluate_resonator_f0(
            model, geometry, -40.0)

    def test_lossless_resonator_has_no_qu(self):
        state = ti.MaterialState(temperature_c=25.0, eps_r=EPS_R_REF, tan_delta=0.0,
                                 sigma_s_per_m=0.0, length_scale=1.0)
        with pytest.raises(ValueError):
            ti.microstrip_resonator_em(state, _standard_geometry())


# ─── 3. 单端口损耗/失谐吸收模型 ──────────────────────────────────────────────

class TestOnePortLossModel:
    def test_critical_coupling_absorbs_all_at_resonance(self):
        cfg = ti.ThermalIterationConfig(
            geometry=_standard_geometry(), ambient_c=25.0, input_power_w=10.0,
            thermal_resistance_k_per_w=0.0, coupling_beta=1.0)
        em = ti.EMEvaluation(f0_hz=2.4e9, q_unloaded=200.0)
        assert ti.one_port_dissipated_power(em, 25.0, config=cfg) == pytest.approx(10.0)

    def test_coupling_algebra_matches_pozar_formula(self):
        cfg = ti.ThermalIterationConfig(
            geometry=_standard_geometry(), ambient_c=25.0, input_power_w=10.0,
            thermal_resistance_k_per_w=0.0, coupling_beta=0.5)
        em = ti.EMEvaluation(f0_hz=2.4e9, q_unloaded=200.0)
        expected = 10.0 * 4.0 * 0.5 / (1.5 ** 2)  # Pozar §6.4 谐振点吸收率
        assert ti.one_port_dissipated_power(em, 25.0, config=cfg) == pytest.approx(expected)

    def test_detuning_reduces_absorbed_power(self):
        base = {"geometry": _standard_geometry(), "ambient_c": 25.0,
                "input_power_w": 10.0, "thermal_resistance_k_per_w": 0.0,
                "coupling_beta": 1.0}
        em = ti.EMEvaluation(f0_hz=2.4e9, q_unloaded=200.0)
        on_resonance = ti.one_port_dissipated_power(
            em, 25.0, config=ti.ThermalIterationConfig(**base))
        detuned = ti.ThermalIterationConfig(**base, drive_frequency_hz=2.4e9 * 1.1)
        assert ti.one_port_dissipated_power(em, 25.0, config=detuned) < 0.01 * on_resonance


# ─── 4. 合成已知温度依赖 -> 闭式不动点 ───────────────────────────────────────

class TestSyntheticFixedPoint:
    def test_linear_map_converges_to_analytic_fixed_point(self):
        c0, c1, rth, ambient = 1.0, 0.1, 4.0, 25.0
        t_star = _analytic_fixed_point(c0, c1, rth, ambient)
        cfg = ti.ThermalIterationConfig(
            geometry=_standard_geometry(), ambient_c=ambient, input_power_w=1.0,
            thermal_resistance_k_per_w=rth, freq_tolerance_hz=1e-3, max_iterations=60)
        res = ti.solve_thermal_fixed_point(
            _standard_model(), cfg, em_evaluator=_linear_em,
            loss_evaluator=_linear_loss(c0, c1))
        assert res.converged
        assert res.status == ti.STATUS_CONVERGED
        assert res.final_temperature_c == pytest.approx(t_star, rel=1e-9)
        f0_star = F0_SYNTH_HZ * (1.0 + K_F_PER_K * (t_star - T_REF))
        assert res.final_f0_hz == pytest.approx(f0_star, rel=1e-9)

    def test_monotone_history_and_shrinking_residual(self):
        c0, c1, rth = 1.0, 0.1, 4.0
        cfg = ti.ThermalIterationConfig(
            geometry=_standard_geometry(), ambient_c=25.0, input_power_w=1.0,
            thermal_resistance_k_per_w=rth, freq_tolerance_hz=1e-3, max_iterations=60)
        res = ti.solve_thermal_fixed_point(
            _standard_model(), cfg, em_evaluator=_linear_em,
            loss_evaluator=_linear_loss(c0, c1))
        temps = [step.temperature_c for step in res.steps]
        assert all(b >= a for a, b in itertools.pairwise(temps))  # 单调升温
        residuals = [s.residual_hz for s in res.steps if s.residual_hz is not None]
        assert all(b < a for a, b in itertools.pairwise(residuals))  # 残差单调收缩

    def test_relaxation_preserves_fixed_point_but_slows_convergence(self):
        c0, c1, rth = 1.0, 0.1, 4.0
        t_star = _analytic_fixed_point(c0, c1, rth, 25.0)
        base = {"geometry": _standard_geometry(), "ambient_c": 25.0,
                "input_power_w": 1.0, "thermal_resistance_k_per_w": rth,
                "freq_tolerance_hz": 1e-3, "max_iterations": 90}
        fast = ti.solve_thermal_fixed_point(
            _standard_model(), ti.ThermalIterationConfig(**base),
            em_evaluator=_linear_em, loss_evaluator=_linear_loss(c0, c1))
        slow = ti.solve_thermal_fixed_point(
            _standard_model(), ti.ThermalIterationConfig(**base, relaxation=0.5),
            em_evaluator=_linear_em, loss_evaluator=_linear_loss(c0, c1))
        assert fast.final_temperature_c == pytest.approx(t_star, rel=1e-9)
        assert slow.final_temperature_c == pytest.approx(t_star, rel=1e-6)
        assert slow.iterations > fast.iterations


# ─── 5. 收敛判据 / 发散 / 护栏 ───────────────────────────────────────────────

class TestConvergenceControl:
    def test_residual_below_tolerance_when_converged(self):
        cfg = ti.ThermalIterationConfig(
            geometry=_standard_geometry(), ambient_c=25.0, input_power_w=0.0,
            thermal_resistance_k_per_w=0.0, freq_tolerance_hz=1.0, max_iterations=5)
        res = ti.solve_thermal_fixed_point(_standard_model(), cfg)
        assert res.converged and res.status == ti.STATUS_CONVERGED
        assert res.residual_hz is not None and res.residual_hz < 1.0

    def test_insufficient_iterations_reports_max_iterations(self):
        cfg = ti.ThermalIterationConfig(
            geometry=_standard_geometry(), ambient_c=25.0, input_power_w=0.0,
            thermal_resistance_k_per_w=0.0, freq_tolerance_hz=1e-12, max_iterations=1)
        res = ti.solve_thermal_fixed_point(_standard_model(), cfg)
        assert res.status == ti.STATUS_MAX_ITERATIONS
        assert res.converged is False
        assert res.iterations == 1
        assert res.residual_hz is None

    def test_divergent_map_is_detected_not_raised(self):
        c1, rth = 1.0, 4.0  # 合成映射 b = R_th*c1 = 4 > 1 -> 发散
        cfg = ti.ThermalIterationConfig(
            geometry=_standard_geometry(), ambient_c=25.0, input_power_w=1.0,
            thermal_resistance_k_per_w=rth, freq_tolerance_hz=1.0, max_iterations=10)
        res = ti.solve_thermal_fixed_point(
            _standard_model(), cfg, em_evaluator=_linear_em,
            loss_evaluator=_linear_loss(1.0, c1))
        assert res.status == ti.STATUS_DIVERGED
        assert res.converged is False
        assert all(math.isfinite(step.f0_hz) for step in res.steps)

    def test_temperature_bounds_reported_before_runaway(self):
        cfg = ti.ThermalIterationConfig(
            geometry=_standard_geometry(), ambient_c=25.0, input_power_w=1.0,
            thermal_resistance_k_per_w=4.0, temperature_bounds_c=(-100.0, 200.0),
            divergence_patience=10, freq_tolerance_hz=1.0, max_iterations=10)
        res = ti.solve_thermal_fixed_point(
            _standard_model(), cfg, em_evaluator=_linear_em,
            loss_evaluator=_linear_loss(1.0, 1.0))
        assert res.status == ti.STATUS_OUT_OF_BOUNDS
        assert res.converged is False


# ─── 6. D3-3 验收：微带谐振器 -40~85 C ──────────────────────────────────────

_AMBIENTS = [-40.0, -20.0, 0.0, 25.0, 50.0, 85.0]


def _microstrip_config(ambient_c: float, **overrides) -> ti.ThermalIterationConfig:
    model = _standard_model()
    geometry = _standard_geometry()
    f0_ref = ti.evaluate_resonator_f0(model, geometry, 25.0)
    params = {"geometry": geometry, "ambient_c": ambient_c, "input_power_w": 1.0,
              "thermal_resistance_k_per_w": 5.0,
              "drive_frequency_hz": f0_ref * 1.001, "max_iterations": 10}
    params.update(overrides)
    return ti.ThermalIterationConfig(**params)


class TestMicrostripAcceptance:
    @pytest.mark.parametrize("ambient_c", _AMBIENTS)
    def test_self_heating_converges_within_five_iterations(self, ambient_c):
        """§10.3 D3-3 验收：-40~85 C 场景迭代 <=5 轮收敛。"""
        model = _standard_model()
        cfg = _microstrip_config(ambient_c, max_iterations=5)
        res = ti.solve_thermal_fixed_point(model, cfg)
        assert res.converged, res.status
        assert res.iterations <= 5

    @pytest.mark.parametrize("ambient_c", _AMBIENTS)
    def test_f0_drift_vs_closed_form_within_20pct(self, ambient_c):
        """§10.3 D3-3 验收：微带谐振器 f0 温漂 vs 闭式 <=20%。

        闭式 = -CTE*dT - 0.5*TCDk*dT（材料 TCDk，Pozar）；迭代 = 精确
        微带 eps_eff 色散 + CTE 几何缩放（未做 TCDk_eff 折算），两者
        差异即"材料 TCDk vs 有效 eps_eff 敏感度"的物理残差。
        """
        model = _standard_model()
        res = ti.solve_thermal_fixed_point(model, _microstrip_config(ambient_c))
        delta_t = res.final_temperature_c - model.t_ref_c
        closed = ti.closed_form_drift_ratio(
            model.cte_ppm_per_k, model.tcdk_ppm_per_k, delta_t)
        iterated = (res.final_f0_hz - res.f0_reference_hz) / res.f0_reference_hz
        assert closed != 0.0
        assert abs(iterated - closed) / abs(closed) <= 0.20

    def test_drift_sign_matches_positive_tcdk_plus_cte(self):
        """TCDk>0 且 CTE>0 时 f0 随温度下降（两项同向为负）。"""
        model = _standard_model()
        res = ti.solve_thermal_fixed_point(model, _microstrip_config(85.0))
        assert res.f0_drift_ppm < 0.0
        assert res.final_f0_hz < res.f0_reference_hz

    def test_closed_form_matches_calculator(self):
        """内核闭式与 core/calculators.py 独立实现逐值互证。"""
        from rfauto.core.calculators import resonator_thermal_drift

        for cte, tcdk, delta_t in [(17.0, 50.0, 60.0), (-10.0, -30.0, -65.0),
                                   (8.0, 0.0, 120.0)]:
            expected = resonator_thermal_drift(2.4, delta_t, cte, tcdk)["df_over_f"]
            assert ti.closed_form_drift_ratio(cte, tcdk, delta_t) == pytest.approx(
                expected, abs=1e-18)


# ─── 7. JSON 接口（to_dict/from_dict/run_thermal_iteration）──────────────────

class TestJsonInterface:
    def test_dataclass_round_trip(self):
        model = _standard_model()
        assert ti.MaterialTemperatureModel.from_dict(model.to_dict()) == model
        geometry = _standard_geometry()
        assert ti.ResonatorGeometry.from_dict(geometry.to_dict()) == geometry
        state = model.evaluate(60.0)
        assert ti.MaterialState.from_dict(state.to_dict()) == state
        em = ti.EMEvaluation(f0_hz=2.4e9, q_unloaded=200.0)
        assert ti.EMEvaluation.from_dict(em.to_dict()) == em
        cfg = ti.ThermalIterationConfig(
            geometry=geometry, ambient_c=25.0, input_power_w=1.0,
            thermal_resistance_k_per_w=5.0, temperature_bounds_c=(-100.0, 200.0))
        assert ti.ThermalIterationConfig.from_dict(cfg.to_dict()) == cfg

    def test_result_is_json_serializable(self):
        res = ti.solve_thermal_fixed_point(_standard_model(), _microstrip_config(85.0))
        payload = res.to_dict()
        text = json.dumps(payload, allow_nan=False)
        assert json.loads(text)["iterations"] == res.iterations
        assert len(payload["steps"]) == res.iterations

    def test_run_thermal_iteration_json_shell(self):
        model = _standard_model()
        cfg = _microstrip_config(85.0)
        out = ti.run_thermal_iteration({"material": model.to_dict(), "config": cfg.to_dict()})
        assert out["ok"] is True
        json.dumps(out, allow_nan=False)
        assert out["result"]["converged"] is True

    def test_run_thermal_iteration_reports_invalid_payload(self):
        missing = ti.run_thermal_iteration({"config": {}})
        assert missing["ok"] is False
        assert "material" in missing["error"]
        unknown = ti.run_thermal_iteration(
            {"material": {"eps_r_ref": 10.0, "bogus": 1}, "config": {}})
        assert unknown["ok"] is False
        assert "未知字段" in unknown["error"]
        assert json.dumps(unknown, allow_nan=False)

    def test_from_dict_rejects_unknown_fields(self):
        with pytest.raises(ValueError):
            ti.MaterialTemperatureModel.from_dict({"eps_r_ref": 10.0, "bogus": 1})
        with pytest.raises(ValueError):
            ti.ResonatorGeometry.from_dict(
                {"length_m": 0.024, "width_m": 0.001, "height_m": 0.001, "bogus": 1})
        with pytest.raises(ValueError):
            ti.MaterialState.from_dict(
                {"temperature_c": 25.0, "eps_r": 3.0, "tan_delta": 0.0,
                 "sigma_s_per_m": 1.0, "length_scale": 1.0, "bogus": 1})
        with pytest.raises(ValueError):
            ti.ThermalIterationConfig.from_dict(
                {"geometry": _standard_geometry().to_dict(), "ambient_c": 25.0,
                 "input_power_w": 1.0, "thermal_resistance_k_per_w": 1.0, "bogus": 1})


# ─── 8. 非法输入显式报错 ─────────────────────────────────────────────────────

def _bad_material_factories():
    return [
        lambda: ti.MaterialTemperatureModel(eps_r_ref=0.0),
        lambda: ti.MaterialTemperatureModel(eps_r_ref=3.0, sigma_ref=-1.0),
        lambda: ti.MaterialTemperatureModel(eps_r_ref=3.0, tan_delta_ref=-0.1),
        lambda: ti.MaterialTemperatureModel(eps_r_ref=3.0, tcdk_ppm_per_k=float("nan")),
        lambda: ti.MaterialState(temperature_c=25.0, eps_r=0.0, tan_delta=0.0,
                                 sigma_s_per_m=1.0, length_scale=1.0),
        lambda: ti.MaterialState(temperature_c=25.0, eps_r=3.0, tan_delta=-1.0,
                                 sigma_s_per_m=1.0, length_scale=1.0),
        lambda: ti.MaterialState(temperature_c=25.0, eps_r=3.0, tan_delta=0.0,
                                 sigma_s_per_m=-1.0, length_scale=1.0),
        lambda: ti.MaterialState(temperature_c=25.0, eps_r=3.0, tan_delta=0.0,
                                 sigma_s_per_m=1.0, length_scale=0.0),
        lambda: ti.ResonatorGeometry(length_m=0.0, width_m=1e-3, height_m=1e-3),
        lambda: ti.ResonatorGeometry(length_m=1e-2, width_m=-1e-3, height_m=1e-3),
        lambda: ti.EMEvaluation(f0_hz=0.0, q_unloaded=10.0),
        lambda: ti.EMEvaluation(f0_hz=1e9, q_unloaded=0.0),
    ]


@pytest.mark.parametrize("factory", _bad_material_factories())
def test_invalid_material_inputs_raise(factory):
    with pytest.raises(ValueError):
        factory()


def _bad_config_factories():
    geometry = _standard_geometry()
    base = {"geometry": geometry, "ambient_c": 25.0, "input_power_w": 1.0,
            "thermal_resistance_k_per_w": 5.0}

    def make(**overrides):
        params = dict(base)
        params.update(overrides)
        return ti.ThermalIterationConfig(**params)

    return [
        lambda: make(input_power_w=-1.0),
        lambda: make(thermal_resistance_k_per_w=-1.0),
        lambda: make(coupling_beta=0.0),
        lambda: make(freq_tolerance_hz=0.0),
        lambda: make(max_iterations=0),
        lambda: make(max_iterations=101),
        lambda: make(max_iterations=1.5),
        lambda: make(relaxation=0.0),
        lambda: make(relaxation=2.5),
        lambda: make(temperature_bounds_c=(100.0, 50.0)),
        lambda: make(divergence_patience=0),
        lambda: make(drive_frequency_hz=0.0),
        lambda: make(ambient_c=float("nan")),
    ]


@pytest.mark.parametrize("factory", _bad_config_factories())
def test_invalid_config_inputs_raise(factory):
    with pytest.raises(ValueError):
        factory()


def _bad_formula_factories():
    return [
        lambda: ti.microstrip_effective_permittivity(0.0, 1.0),
        lambda: ti.microstrip_effective_permittivity(3.0, 0.0),
        lambda: ti.microstrip_characteristic_impedance(0.0, 1.0),
        lambda: ti.microstrip_characteristic_impedance(2.0, 0.0),
        lambda: ti.surface_resistance(0.0, 1e7),
        lambda: ti.surface_resistance(1e9, 0.0),
        lambda: ti.closed_form_drift_ratio(0.0, 0.0, float("nan")),
        lambda: ti.evaluate_resonator_f0(
            _standard_model(), _standard_geometry(), float("nan")),
    ]


@pytest.mark.parametrize("factory", _bad_formula_factories())
def test_invalid_formula_inputs_raise(factory):
    with pytest.raises(ValueError):
        factory()


def test_negative_loss_evaluator_power_raises():
    cfg = ti.ThermalIterationConfig(
        geometry=_standard_geometry(), ambient_c=25.0, input_power_w=1.0,
        thermal_resistance_k_per_w=5.0, max_iterations=3)
    with pytest.raises(ValueError):
        ti.solve_thermal_fixed_point(
            _standard_model(), cfg, em_evaluator=_linear_em,
            loss_evaluator=lambda em, temperature_c: -1.0)
