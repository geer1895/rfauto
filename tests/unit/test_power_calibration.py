"""SB22-MS-1 功率校准补偿链内核定向门（MS12 储备池席，2026-10-08）。

四类钉：极限（匹配恒等）/单调（补偿方向性）/文献数值例（失配界
SWR1.5×1.25→0.19 dB 双源 + GUM §4.3.7/§4.3.9 分布系数 + K_b 定义算术）/
守卫（域外显式拒绝）+ 回收钉（正向合成→反向补偿恢复真值，#118）。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.power_calibration import (
    cable_loss_compensation_dbm,
    cal_factor_compensation_dbm,
    cal_verification,
    calibrate_power_chain,
    calibration_factor,
    mismatch_phase_term_db,
    mismatch_uncertainty_db,
    model_meter_reading_dbm,
    power_cal_uncertainty,
    source_match_correction_db,
    type_b_standard_u,
)
from rfauto.service.calculator_service import run_calculator

# 名义设计点（与 test_physics_invariants._calculator_inputs 同一设计点）
_NOMINAL = {
    "p_read_dbm": -10.0, "k_cal_lin": 0.9405, "cable_loss_db": 3.5,
    "gamma_source": [0.17320508, 0.1],
    "gamma_load": [0.07856605, -0.07856605],
    "mismatch_mode": "exact",
    "u_components": [
        {"name": "sensor_cal", "half_width_db": 0.2,
         "distribution": "rectangular"},
        {"name": "repeatability", "u_db": 0.05},
    ],
}


# ─── 文献数值例（双源）───────────────────────────────────────────────────────


class TestLiteratureAnchors:
    def test_calibration_factor_definition_arithmetic(self):
        """K_b = η(1−|Γl|²)（Keysight AN 64-1A 定义）：η=0.95/|Γl|=0.1
        → 0.9405（纯算术恒等）。"""
        assert calibration_factor(0.95, 0.1) == pytest.approx(0.9405)
        # 补偿量 −10lg(0.9405) = +0.26675 dB（恒等换算）
        comp = cal_factor_compensation_dbm(0.0, 0.9405)
        assert comp == pytest.approx(-10.0 * math.log10(0.9405), abs=1e-12)
        assert comp > 0.0  # K<1 → 正补偿（方向性）

    def test_mismatch_uncertainty_vendor_table(self):
        """失配界文献例：源 SWR 1.5（|Γ|=0.2）× 传感器 SWR 1.25
        （|Γ|=0.1111）→ MU = 20lg(1+0.02222) ≈ 0.19091 dB。
        Keysight AN 1449-3 与 R&S《Voltage and Power Measurements》
        失配不确定度表双源同印 ±0.19 dB。"""
        mu = mismatch_uncertainty_db(0.2, (1.25 - 1.0) / (1.25 + 1.0))
        assert mu == pytest.approx(
            20.0 * math.log10(1.0 + 0.2 * (0.25 / 2.25)), rel=1e-12)
        assert mu == pytest.approx(0.19, abs=0.005)  # 厂商表印值（两位小数）

    def test_gum_type_b_distribution_coefficients(self):
        """JCGM 100:2008：矩形 u=a/√3（§4.3.7）、U 形 u=a/√2（§4.3.9）；
        同半宽 U 形 > 矩形（√3/√2 比值精确）。"""
        a = 0.4
        u_rect = type_b_standard_u(a, "rectangular")
        u_ush = type_b_standard_u(a, "ushaped")
        assert u_rect == pytest.approx(a / math.sqrt(3.0), rel=1e-14)
        assert u_ush == pytest.approx(a / math.sqrt(2.0), rel=1e-14)
        assert u_ush / u_rect == pytest.approx(math.sqrt(3.0 / 2.0), rel=1e-14)

    def test_source_match_correction_identity(self):
        """源匹配校正恒等式：|Γs|=0.2 → −10lg(0.96)=0.177788 dB；
        相位项在 ΓsΓl=1−j·0 同幅正交时 |1−ΓsΓl|=√(1+x²) 精确。"""
        assert source_match_correction_db(0.2) == pytest.approx(
            -10.0 * math.log10(1.0 - 0.04), rel=1e-12)
        # ΓsΓl = j·0.1 → |1−j·0.1| = √1.01
        assert mismatch_phase_term_db(0.2, 0.5j) == pytest.approx(
            10.0 * math.log10(1.01), rel=1e-12)


# ─── 极限与恒等 ──────────────────────────────────────────────────────────────


class TestLimits:
    def test_matched_identity_limit(self):
        """匹配极限：K=1/L=0/Γ=0 → 全链零修正，输出逐位=输入。"""
        out = calibrate_power_chain(-7.3, 1.0)
        assert out["p_incident_sensor_dbm"] == pytest.approx(-7.3, abs=1e-14)
        assert out["p_ref_far_dbm"] == pytest.approx(-7.3, abs=1e-14)
        assert out["p_available_dbm"] == pytest.approx(-7.3, abs=1e-14)
        assert out["mismatch_half_width_db"] == 0.0
        assert out["u_combined_db"] == 0.0
        assert out["budget"] == []

    def test_recycle_synthetic_known_truth(self):
        """回收钉（#118）：正向合成已知真值 → 反向补偿恢复，残差 ≤1e-10 dB。"""
        truth = -4.7
        gs, gl = complex(0.17320508, 0.1), complex(0.07856605, -0.07856605)
        reading = model_meter_reading_dbm(
            truth, k_cal_lin=0.9405, cable_loss_db=3.5,
            gamma_source=gs, gamma_load=gl)
        out = calibrate_power_chain(
            reading, 0.9405, 3.5, gamma_source=gs, gamma_load=gl,
            mismatch_mode="exact")
        assert out["p_available_dbm"] == pytest.approx(truth, abs=1e-10)

    def test_band_mode_brackets_exact_truth(self):
        """band 模式：点值不修正，真值必落在 ±MU 带内（界一致性）。"""
        truth = -4.7
        gs, gl = 0.2, 0.111111
        reading = model_meter_reading_dbm(
            truth, 1.0, 0.0, gamma_source=gs, gamma_load=gl)
        out = calibrate_power_chain(
            reading, 1.0, 0.0, gamma_source=gs, gamma_load=gl,
            mismatch_mode="band")
        lo, hi = out["mismatch_band_db"]
        exact = calibrate_power_chain(
            reading, 1.0, 0.0, gamma_source=gs, gamma_load=gl,
            mismatch_mode="exact")
        assert lo <= exact["p_available_dbm"] <= hi
        assert (hi - lo) / 2.0 == pytest.approx(
            mismatch_uncertainty_db(gs, gl), rel=1e-12)


# ─── 单调性 ──────────────────────────────────────────────────────────────────


class TestMonotonicity:
    def test_cable_and_cal_monotone(self):
        """缆损耗越大/校准因子越小 → 补偿后功率越大（补偿方向性）。"""
        base = calibrate_power_chain(-10.0, 0.9405, 0.0)
        with_loss = calibrate_power_chain(-10.0, 0.9405, 3.5)
        better_k = calibrate_power_chain(-10.0, 0.80, 0.0)
        assert with_loss["p_ref_far_dbm"] > base["p_ref_far_dbm"]
        assert better_k["p_incident_sensor_dbm"] > base[
            "p_incident_sensor_dbm"]
        assert cable_loss_compensation_dbm(-10.0, 2.0) == -8.0

    def test_mismatch_bounds_grow_with_gamma(self):
        """|Γ| 越大失配界越宽（单调），严格 <1 内有限。"""
        m_small = mismatch_uncertainty_db(0.05, 0.05)
        m_mid = mismatch_uncertainty_db(0.2, 0.2)
        m_big = mismatch_uncertainty_db(0.5, 0.5)
        assert 0.0 < m_small < m_mid < m_big

    def test_uncertainty_never_decreases_with_more_components(self):
        """加组件 u_c 不减（RSS 单调）；等幅两矩形 u_c=√2·(a/√3)。"""
        one = power_cal_uncertainty(
            [{"name": "a", "half_width_db": 0.3, "distribution":
              "rectangular"}])
        two = power_cal_uncertainty(
            [{"name": "a", "half_width_db": 0.3,
              "distribution": "rectangular"},
             {"name": "b", "u_db": 0.1}])
        u1 = one["u_combined_db"]
        assert two["u_combined_db"] >= u1
        assert one["u_combined_db"] == pytest.approx(
            0.3 / math.sqrt(3.0), rel=1e-14)
        assert two["u_expanded_db_k2"] == pytest.approx(
            2.0 * two["u_combined_db"], rel=1e-14)
        # 贡献占比守恒
        total = sum(row["contribution_pct"] for row in two["budget"])
        assert total == pytest.approx(100.0, rel=1e-9)


# ─── 守卫 ────────────────────────────────────────────────────────────────────


class TestGuards:
    @pytest.mark.parametrize("kwargs", [
        {"k_cal_lin": 0.0},        # K=0 非法
        {"k_cal_lin": 1.5},        # K>1 出无源传感器口径
        {"k_cal_lin": -0.9},       # 负 K
        {"cable_loss_db": -1.0},   # 负损耗
        {"gamma_source": [1.0, 0.0]},   # |Γ|=1 非无源
        {"gamma_load": [0.5, 0.9]},     # |Γ|>1
        {"mismatch_mode": "bogus"},     # 未知模式
        {"u_components": [{"name": "x", "half_width_db": 0.1,
                           "distribution": "triangle"}]},  # 未知分布
        {"u_components": [{"name": "x", "half_width_db": 0.1,
                           "u_db": 0.1}]},  # 二选一同时给
        {"u_components": [{"name": "x"}]},  # 二选一都不给
        {"u_components": [{"name": "x", "u_db": 0.1},
                          {"name": "x", "u_db": 0.2}]},  # 重复名
    ])
    def test_domain_guards_reject(self, kwargs):
        base = {"p_read_dbm": -10.0, "k_cal_lin": 0.9405}
        base.update(kwargs)
        with pytest.raises(ValueError):
            calibrate_power_chain(**base)

    def test_verification_verdicts(self):
        """cal-heat 回读判定：容差内 PASS/超差 FAIL 如实；边界恰容差=PASS。"""
        ok = cal_verification(-20.0, -19.95, 0.1)
        assert ok["verdict"] == "PASS"
        assert ok["margin_db"] == pytest.approx(0.05, abs=1e-12)
        bad = cal_verification(-20.0, -19.95, 0.04)
        assert bad["verdict"] == "FAIL"
        assert bad["margin_db"] < 0
        edge = cal_verification(0.0, 0.1, 0.1)
        assert edge["verdict"] == "PASS"  # |dev|<=tol 口径
        with pytest.raises(ValueError):
            cal_verification(0.0, 0.0, 0.0)  # 非正容差


# ─── 注册键面 ────────────────────────────────────────────────────────────────


class TestRegistryKey:
    def test_key_run_ok_and_deterministic(self):
        import json

        first = run_calculator("power_cal_chain", _NOMINAL)
        assert first["ok"] is True
        second = run_calculator("power_cal_chain", _NOMINAL)
        assert json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(
            second, sort_keys=True, allow_nan=False)

    def test_key_json_roundtrip(self):
        import json

        out = run_calculator("power_cal_chain", _NOMINAL)
        payload = json.loads(json.dumps(out, allow_nan=False))  # 不抛即过
        assert payload["result"]["k_cal_lin"] == 0.9405

    def test_key_exact_matches_core_chain(self):
        """薄壳无漂移：注册键 exact 结果与 core 直调逐位一致。"""
        via_key = run_calculator("power_cal_chain", _NOMINAL)["result"]
        via_core = calibrate_power_chain(
            p_read_dbm=_NOMINAL["p_read_dbm"],
            k_cal_lin=_NOMINAL["k_cal_lin"],
            cable_loss_db=_NOMINAL["cable_loss_db"],
            gamma_source=complex(*_NOMINAL["gamma_source"]),
            gamma_load=complex(*_NOMINAL["gamma_load"]),
            mismatch_mode="exact",
            u_components=_NOMINAL["u_components"])
        assert via_key["p_available_dbm"] == via_core["p_available_dbm"]
