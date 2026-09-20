"""WP4.4a 电-热链 service 单测（JSON 进出，纯离线确定性）。"""

from __future__ import annotations

import pytest

from rfauto.service.electrothermal_service import (
    derive_r_th_from_field,
    run_electrothermal_fixed_point,
    run_wilkinson_electrothermal,
)

_BASE = {
    "case": {"scenario": "isolation_injection", "injected_power_w": 1.0},
    "thermal": {"ambient_c": 25.0, "r_th_k_per_w": 50.0},
    "material": {"t_ref_c": 25.0, "cte_ppm_per_k": 14.0, "tcdk_ppm_per_k": 50.0},
    "resonator": {"f0_hz": 2.4e9},
    "band": {"low_hz": 2.3e9, "high_hz": 2.5e9},
}


class TestHappyPath:
    def test_full_chain_hand_values(self):
        """1W 隔离注入 → P_res=0.5W → ΔT=25K → df/f=-1.95e-4 → 出带。"""
        out = run_wilkinson_electrothermal(_BASE)
        assert out["ok"] is True
        chain = out["chain"]
        assert chain["power"]["resistor_w"] == pytest.approx(0.5)
        assert chain["thermal"]["t_hot_c"] == pytest.approx(50.0)
        assert chain["thermal"]["rise_k"] == pytest.approx(25.0)
        assert chain["thermal"]["source"] == "r_th_closed_form"
        assert chain["material"]["delta_t_c"] == pytest.approx(25.0)
        drift = chain["drift"]
        # df/f = -(14 + 25)*1e-6*25 = -9.75e-4
        assert drift["drift_ratio"] == pytest.approx(-9.75e-4)
        assert drift["df_hz"] == pytest.approx(-2.34e6)
        assert drift["f0_shifted_hz"] == pytest.approx(2.4e9 - 2.34e6)
        # 仍在带内（2.39766 GHz ∈ [2.3, 2.5]），距下带缘 97.66 MHz
        assert chain["band"]["in_band"] is True
        assert chain["band"]["margin_hz"] == pytest.approx(2.4e9 - 2.34e6 - 2.3e9)

    def test_injected_temperature_branch(self):
        """Icepak/实测温度注入路径：t_hot_c 直通，source=injected。"""
        payload = {
            "case": {"scenario": "combiner_imbalance", "p2_w": 1.0, "p3_w": 1.0,
                     "phase_diff_deg": 90.0},
            "thermal": {"ambient_c": 25.0, "t_hot_c": 61.25},
            "material": {"cte_ppm_per_k": 14.0, "tcdk_ppm_per_k": 50.0},
            "resonator": {"f0_hz": 2.4e9},
        }
        out = run_wilkinson_electrothermal(payload)
        assert out["ok"] is True
        chain = out["chain"]
        # φ=90° → P_res = 0.5*(1+1-0) = 1.0W
        assert chain["power"]["resistor_w"] == pytest.approx(1.0)
        assert chain["thermal"]["source"] == "injected"
        assert chain["thermal"]["t_hot_c"] == pytest.approx(61.25)
        # t_ref 默认 25 → ΔT=36.25K
        assert chain["material"]["delta_t_c"] == pytest.approx(36.25)
        assert chain["drift"]["drift_ratio"] == pytest.approx(-39e-6 * 36.25)
        assert chain["band"] is None

    def test_divider_through_zero_detune(self):
        payload = dict(_BASE)
        payload["case"] = {"scenario": "divider_through", "input_power_w": 4.0}
        out = run_wilkinson_electrothermal(payload)
        chain = out["chain"]
        assert chain["power"]["resistor_w"] == 0.0
        assert chain["thermal"]["rise_k"] == 0.0
        assert chain["drift"]["df_hz"] == 0.0
        assert chain["band"]["in_band"] is True


class TestValidation:
    @pytest.mark.parametrize("mutate,fragment", [
        (lambda p: p.pop("case"), "case"),
        (lambda p: p.pop("thermal"), "thermal"),
        (lambda p: p["case"].__setitem__("scenario", "bogus"), "scenario"),
        (lambda p: p["case"].pop("injected_power_w"), "injected_power_w"),
        (lambda p: p["thermal"].pop("r_th_k_per_w"), "r_th_k_per_w"),
        (lambda p: p["material"].pop("tcdk_ppm_per_k"), "tcdk_ppm_per_k"),
        (lambda p: p["resonator"].pop("f0_hz"), "f0_hz"),
        (lambda p: p.__setitem__("unknown_key", 1), "unknown_key"),
        (lambda p: p["band"].__setitem__("high_hz", 2.1e9), "band_low_hz"),
        (lambda p: p["thermal"].__setitem__("t_hot_c", "hot"), "t_hot_c"),
    ])
    def test_invalid_payloads_return_ok_false(self, mutate, fragment):
        payload = {k: dict(v) if isinstance(v, dict) else v for k, v in _BASE.items()}
        mutate(payload)
        out = run_wilkinson_electrothermal(payload)
        assert out["ok"] is False
        assert fragment in out["error"]

    def test_payload_not_a_dict(self):
        assert run_wilkinson_electrothermal([1, 2])["ok"] is False

    def test_nested_not_a_dict(self):
        out = run_wilkinson_electrothermal({"case": 3})
        assert out["ok"] is False
        assert "case" in out["error"]


# ─── WP4.4a ③：场解 R_th 推导（Icepak t_hot/power → R_th = ΔT/P）──────────────


class TestDeriveRThFromField:
    def test_hand_values(self):
        out = derive_r_th_from_field(
            {"t_hot_c": 61.3, "power_w": 0.5, "ambient_c": 25.0})
        assert out["ok"] is True
        assert out["r_th_k_per_w"] == pytest.approx((61.3 - 25.0) / 0.5)
        assert out["rise_k"] == pytest.approx(36.3)
        assert out["source"] == "icepak_field"

    def test_default_ambient_and_explicit_source(self):
        out = derive_r_th_from_field(
            {"t_hot_c": 125.0, "power_w": 2.0, "source": "实测"})
        assert out["ok"] is True
        assert out["ambient_c"] == 25.0
        assert out["r_th_k_per_w"] == pytest.approx(50.0)
        assert out["source"] == "实测"

    @pytest.mark.parametrize("mutate,fragment", [
        (lambda p: p.pop("t_hot_c"), "t_hot_c"),
        (lambda p: p.pop("power_w"), "power_w"),
        (lambda p: p.__setitem__("power_w", 0.0), "power_w 必须 >0"),
        (lambda p: p.__setitem__("power_w", -1.0), "power_w 必须 >0"),
        (lambda p: p.__setitem__("t_hot_c", 20.0), "温升非物理"),
        (lambda p: p.__setitem__("t_hot_c", "hot"), "t_hot_c"),
        (lambda p: p.__setitem__("ambient_c", float("nan")), "ambient_c"),
        (lambda p: p.__setitem__("nope", 1), "nope"),
    ])
    def test_invalid_payloads_return_ok_false(self, mutate, fragment):
        payload = {"t_hot_c": 61.3, "power_w": 0.5}
        mutate(payload)
        out = derive_r_th_from_field(payload)
        assert out["ok"] is False
        assert fragment in out["error"]

    def test_not_a_dict(self):
        assert derive_r_th_from_field(42)["ok"] is False


# ─── WP4.4a ③：双向定点编排（material ↔ loss ↔ temperature，core 注入）────────

_FIXED_MATERIAL = {
    "eps_r_ref": 10.2, "sigma_ref": 5.8e7, "tan_delta_ref": 1e-3,
    "tcdk_ppm_per_k": 50.0, "cte_ppm_per_k": 17.0, "t_ref_c": 25.0,
}
_FIXED_GEOMETRY = {"length_m": 0.024, "width_m": 0.0012, "height_m": 0.00127}


class TestRunElectrothermalFixedPoint:
    def _payload(self, thermal: dict) -> dict:
        return {
            "material": dict(_FIXED_MATERIAL),
            "config": {"geometry": dict(_FIXED_GEOMETRY),
                       "input_power_w": 0.5,
                       "freq_tolerance_hz": 1.0e3,
                       "max_iterations": 60},
            "thermal": thermal,
        }

    def test_explicit_r_th_converges_with_default_microstrip_chain(self):
        """闭式热阻分支：core 默认微带解析链（确定性，零网络）收敛。"""
        out = run_electrothermal_fixed_point(
            self._payload({"ambient_c": 25.0, "r_th_k_per_w": 50.0}))
        assert out["ok"] is True
        assert out["thermal"]["r_th_k_per_w"] == pytest.approx(50.0)
        assert out["thermal"]["source"] == "explicit"
        result = out["result"]
        assert result["status"] == "converged"
        assert result["final_temperature_c"] > 25.0  # 自发热升温
        assert result["final_f0_hz"] < result["f0_reference_hz"]  # TCDk>0 失谐向下

    def test_field_derived_r_th_matches_direct_derivation(self):
        """场解分支：R_th 与 derive_r_th_from_field 直算一致。"""
        out = run_electrothermal_fixed_point(
            self._payload({"t_hot_c": 61.3, "power_w": 0.5, "ambient_c": 25.0}))
        assert out["ok"] is True
        assert out["thermal"]["r_th_k_per_w"] == pytest.approx((61.3 - 25.0) / 0.5)
        assert out["thermal"]["source"] == "icepak_field"
        assert out["result"]["status"] == "converged"

    def test_fake_evaluators_converge_in_two_rounds(self):
        """离线收敛判据：fake em/loss 评估器注入（#139 钉通道），
        f0 常数 → 第 2 轮残差归零收敛（≤2 轮口径）。"""
        from rfauto.core.thermal_iteration import EMEvaluation

        def _const_em(state, temperature_c):
            return EMEvaluation(f0_hz=2.4e9, q_unloaded=100.0)

        def _const_loss(em, temperature_c):
            return 0.25

        out = run_electrothermal_fixed_point(
            self._payload({"ambient_c": 25.0, "r_th_k_per_w": 40.0}),
            em_evaluator=_const_em, loss_evaluator=_const_loss)
        assert out["ok"] is True
        result = out["result"]
        assert result["status"] == "converged"
        assert result["iterations"] == 2
        assert result["final_temperature_c"] == pytest.approx(25.0 + 40.0 * 0.25)
        assert result["final_f0_hz"] == pytest.approx(2.4e9)
        assert result["dissipated_power_w"] == pytest.approx(0.25)

    @pytest.mark.parametrize("mutate,fragment", [
        (lambda p: p.pop("material"), "material"),
        (lambda p: p.pop("config"), "config"),
        (lambda p: p.pop("thermal"), "thermal"),
        (lambda p: p["config"].__setitem__("thermal_resistance_k_per_w", 50.0),
         "不得在 config 中重复给出"),
        (lambda p: p["config"].__setitem__("nope", 1), "nope"),
        (lambda p: p["thermal"].__setitem__("r_th_k_per_w", -1.0), ">=0"),
        (lambda p: p["thermal"].__setitem__("t_hot_c", 61.3), "含未知字段"),
        (lambda p: _field_case(p), "power_w 必须 >0"),
        (lambda p: p["material"].__setitem__("eps_r_ref", 0.0), "eps_r_ref"),
    ])
    def test_invalid_payloads_return_ok_false(self, mutate, fragment):
        payload = self._payload({"ambient_c": 25.0, "r_th_k_per_w": 50.0})
        mutate(payload)
        out = run_electrothermal_fixed_point(payload)
        assert out["ok"] is False
        assert fragment in out["error"]

    def test_payload_not_a_dict(self):
        assert run_electrothermal_fixed_point("x")["ok"] is False


def _field_case(payload: dict) -> None:
    """切到场解分支并给负功率（校验 derive_r_th 的功率门）。"""
    thermal = payload["thermal"]
    thermal.pop("r_th_k_per_w")
    thermal["t_hot_c"] = 61.3
    thermal["power_w"] = -1.0
