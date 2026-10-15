"""XC 时域套件标准化锚树（rfauto-td-v1 schema + CFL/截断闭式内核）。

判据（#118 独立来源）：
- CFL 手算：dt_max = Δ/(c√3)——Δ=1mm → 1e-3/(299792458·√3)
  =1.9245e-12 s（6 位有效手算复核）；εr=4.4 → ÷√4.4=9.1747e-13 s；
- 脉宽手算：f0=2.4GHz、fc_window=0.2 → fc=0.48GHz →
  τ(5 cycles)=5/0.48e9=1.04167e-8 s（时宽与带宽成反比）；
- 换算往返：nrts=ceil(window/dt) 显式模式；双声明自洽守卫
  （|nrts·dt−max_time|>1e-9 相对 → ValueError）；
- 未知键/正 end_criteria/坏 fc_window 显式拒（标准化面不吞别名）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.time_domain_suite import (
    DEFAULT_TRUNCATION_MARGIN,
    TD_SCHEMA,
    cfl_dt_s,
    excite_duration_s,
    normalize_td_spec,
    nrts_for_window,
)
from rfauto.service import time_domain_suite_service as tds


class TestCfl:
    def test_vacuum_hand_value(self):
        # 1e-3/(299792458·sqrt(3))：手算 =1.92447e-12
        assert cfl_dt_s(1e-3) == pytest.approx(1.92447e-12, rel=1e-5)

    def test_er_shortens(self):
        vac = cfl_dt_s(1e-3)
        assert cfl_dt_s(1e-3, 4.4) == pytest.approx(vac / math.sqrt(4.4),
                                                    rel=1e-12)

    def test_bad_args(self):
        with pytest.raises(ValueError):
            cfl_dt_s(0.0)
        with pytest.raises(ValueError, match="er_max"):
            cfl_dt_s(1e-3, 0.5)


class TestPulse:
    def test_duration_hand_value(self):
        assert excite_duration_s(2.4, 0.2) == pytest.approx(5 / 0.48e9,
                                                            rel=1e-12)

    def test_narrower_window_longer_pulse(self):
        assert excite_duration_s(2.4, 0.05) > excite_duration_s(2.4, 0.4)

    def test_nrts_modes(self):
        assert nrts_for_window(2.5e-9, 1e-12) == 2500
        assert nrts_for_window(2.5e-9, 1e-12, mode="floor") == 2500
        assert nrts_for_window(2.5463e-9, 1e-12) == 2547  # ceil 盖满
        with pytest.raises(ValueError, match="mode"):
            nrts_for_window(1.0, 1.0, mode="round")


class TestNormalize:
    def test_minimal_spec(self):
        out = normalize_td_spec({"f0_ghz": 2.4})
        assert out["schema"] == TD_SCHEMA
        assert out["fc_window"] == 0.2
        assert out["window_ns"] is None
        assert out["excite_duration_ns"] == pytest.approx(10.4167,
                                                          rel=1e-4)

    def test_window_from_nrts_dt(self):
        out = normalize_td_spec({"f0_ghz": 2.4, "nrts": 1000, "dt_s": 1e-12})
        assert out["window_ns"] == pytest.approx(1.0)

    def test_consistent_double_declaration_ok(self):
        out = normalize_td_spec({"f0_ghz": 2.4, "nrts": 1000, "dt_s": 1e-12,
                                 "max_time_ns": 1.0})
        assert out["window_ns"] == pytest.approx(1.0)

    def test_inconsistent_double_declaration_rejected(self):
        with pytest.raises(ValueError, match="不自洽"):
            normalize_td_spec({"f0_ghz": 2.4, "nrts": 1000, "dt_s": 1e-12,
                               "max_time_ns": 2.0})

    def test_unknown_key_rejected(self):
        with pytest.raises(ValueError, match="未知键"):
            normalize_td_spec({"f0_ghz": 2.4, "nr_ts": 100})

    def test_truncation_flag(self):
        ok = normalize_td_spec({"f0_ghz": 2.4, "max_time_ns": 30.0})
        assert ok["truncation"]["ok"] is True
        tight = normalize_td_spec({"f0_ghz": 2.4, "max_time_ns": 2.0,
                                   "k_cycles": 5.0})
        # 窗 2.0ns < 1.1×2.3148ns → 截断预警
        assert tight["truncation"]["ok"] is False
        assert tight["truncation"]["margin"] == DEFAULT_TRUNCATION_MARGIN

    def test_cfl_fields_when_cell_declared(self):
        out = normalize_td_spec({"f0_ghz": 2.4, "dt_s": 4.5907e-13,
                                 "min_cell_mm": 0.5, "er_max": 4.4})
        assert out["cfl_dt_limit_s"] == pytest.approx(
            cfl_dt_s(0.5e-3, 4.4), rel=1e-12)
        assert out["dt_over_cfl"] == pytest.approx(1.0, rel=1e-3)

    def test_bad_end_criteria(self):
        with pytest.raises(ValueError, match="负 dB"):
            normalize_td_spec({"f0_ghz": 2.4, "end_criteria_db": 0.5})


class TestService:
    def test_standardize_envelope(self):
        out = tds.time_domain_spec_standardize({"f0_ghz": 2.4})
        assert out["ok"] is True and out["spec"]["schema"] == TD_SCHEMA
        bad = tds.time_domain_spec_standardize({"f0_ghz": -1})
        assert bad["ok"] is False and bad["errors"]

    def test_window_plan_hand_numbers(self):
        out = tds.td_window_plan({"f0_ghz": 2.4, "fc_window": 0.2,
                                  "dt_s": 1e-12})
        assert out["ok"] is True
        assert out["excite_duration_s"] == pytest.approx(5 / 0.48e9,
                                                         rel=1e-12)
        need = math.ceil(1.1 * (5 / 0.48e9) / 1e-12)
        assert out["nrts_needed"] == need
        assert out["window_ns"] == pytest.approx(need * 1e-3, rel=1e-9)
        assert out["dt_is_cfl_limit"] is False

    def test_window_plan_cfl_route(self):
        out = tds.td_window_plan({"f0_ghz": 10.0, "min_cell_mm": 0.5,
                                  "er_max": 4.4})
        assert out["ok"] is True
        assert out["dt_is_cfl_limit"] is True
        assert out["dt_s"] == pytest.approx(cfl_dt_s(0.5e-3, 4.4), rel=1e-12)

    def test_window_plan_margin_below_one_rejected(self):
        out = tds.td_window_plan({"f0_ghz": 2.4, "dt_s": 1e-12,
                                  "margin": 0.5})
        assert out["ok"] is False


class TestWindowPlanDirectW2:
    """W2-TEST 直测补强：td_window_plan 守卫三态与闭式链（#118 独立期望值）。"""

    def test_dt_guards_positive_finite(self):
        # dt_s=0/负值 → 内核正性守卫 ValueError → service ok=False（不抛穿）
        # 回归钉（W2-TEST）：修复前闭式链在 try 块外，dt_s≤0 的 ValueError
        # 从 service 裸抛（违约"不抛穿"信封契约）；f0≤0 同源逃逸一并钉。
        for bad_dt in (0, 0.0, -1e-12):
            out = tds.td_window_plan({"f0_ghz": 2.4, "dt_s": bad_dt})
            assert out["ok"] is False, bad_dt
            assert out["errors"]
            assert "dt_s" in out["errors"][0]
        # f0_ghz=0/负值 → excite_duration_s 正性守卫入信封（同源逃逸回归钉）
        for bad_f0 in (0, -2.4):
            out = tds.td_window_plan({"f0_ghz": bad_f0, "dt_s": 1e-12})
            assert out["ok"] is False, bad_f0
            assert "f0_ghz" in out["errors"][0]
        # 非 dt 路线同样守卫：min_cell_mm=0 → CFL 闭式 ValueError
        out = tds.td_window_plan({"f0_ghz": 2.4, "min_cell_mm": 0.0})
        assert out["ok"] is False and out["errors"]

    def test_missing_route_and_none_payload(self):
        # dt_s 与 min_cell_mm 双缺 → 二选一必给；None payload → f0 KeyError 入信封
        out = tds.td_window_plan({"f0_ghz": 2.4})
        assert out["ok"] is False
        assert any("二选一" in e for e in out["errors"])
        out2 = tds.td_window_plan(None)
        assert out2["ok"] is False
        assert any("f0_ghz" in e for e in out2["errors"])

    def test_k_cycles_and_margin_closed_chain(self):
        """k_cycles/margin 透传：τ=k/fc 手算、窗=margin·τ、nrts=ceil(窗/dt)。"""
        f0, fcw, dt = 2.4, 0.2, 1e-12
        out = tds.td_window_plan({"f0_ghz": f0, "fc_window": fcw, "dt_s": dt,
                                  "k_cycles": 10.0, "margin": 2.0})
        assert out["ok"] is True
        # 独立手算（#118）：fc=f0·fcw=0.48GHz → τ=10/0.48e9；窗=2·τ
        tau = 10.0 / (f0 * fcw * 1e9)
        assert out["excite_duration_s"] == pytest.approx(tau, rel=1e-12)
        assert out["required_window_s"] == pytest.approx(2.0 * tau, rel=1e-12)
        assert out["margin"] == 2.0
        need = math.ceil(2.0 * tau / dt)
        assert out["nrts_needed"] == need
        # 恒等链：window_ns = nrts·dt·1e9（自洽，规划期零引擎依赖）
        assert out["window_ns"] == pytest.approx(need * dt * 1e9, rel=1e-12)
        assert out["dt_is_cfl_limit"] is False
