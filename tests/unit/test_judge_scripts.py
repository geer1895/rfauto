"""W2⑥a 离线判读脚本的纯函数单测（scripts/judge_*.py）。

确定性、无真机、无网络：日志解析正则、细扫窗沿夹持判据、热阻导出、
gysel S 参数指标、branchline λ/4 闭式反推。数值锚取自真机日志/闭式。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import judge_branchline_nominal as jb
import judge_gysel_ljog as jg
import judge_icepak_run9 as ji

RUN9_SNIPPET = """\
=== attempt 1/2 ===
[HFSS@T0] f0=2.387687GHz (网格步长 0.25MHz)
[HFSS@T0] |S11|=0.9656 |S21|=0.0474 → P_diss=0.065434W
[Icepak field r1] T_ring=26.472C 底面出热=0.043961W vs P_diss=0.065434W → 守恒偏差=32.82%（门 5%）pass=False
[Icepak lumped] T_ring=29.120C → 场级 vs 集总温差=2.6477K（温升 1.4724K 的 179.82%，门 10%）pass=False
[HFSS@T1=26.472C] f0=2.362687GHz 漂移=-25000.0kHz (-10470.4ppm) vs 闭式 -57.4ppm → 偏差 18133.6%（门 20%）pass=False
attempt 1 FAIL: unhandled: type object 'HfssConstants' has no attribute 'default_solution'
"""


class TestIcepakLogParser:
    def test_parse_gate_lines_run9(self):
        g = ji.parse_gates(RUN9_SNIPPET)
        assert g["hfss_t0"][0] == {"f0_ghz": 2.387687, "grid_step_mhz": 0.25}
        c = g["conservation"][0]
        assert c["dev_pct"] == 32.82 and c["q_bottom_w"] == 0.043961
        assert c["p_diss_w"] == 0.065434 and c["t_ring_c"] == 26.472
        lu = g["lumped"][0]
        assert lu["t_lumped_c"] == 29.12 and lu["pct_of_rise"] == 179.82
        d = g["drift"][0]
        assert d["drift_khz"] == -25000.0 and d["closed_form_ppm"] == -57.4
        assert "default_solution" in g["attempt_fail"][0]

    def test_window_edge_clip(self):
        # 201 点 × 0.25MHz → 半跨 25MHz：run9 漂移 −25000kHz 恰为窗沿
        assert ji.sweep_span_mhz(201, 0.25) == (50.0, 25.0)
        assert ji.window_clip_check(-25000.0, 201, 0.25) is True
        # run5/7 的 +18670kHz 在 ±125MHz 窗内 → 非夹持
        assert ji.window_clip_check(18670.0, 201, 1.25) is False

    def test_thermal_resistances_from_gate_numbers(self):
        g = ji.parse_gates(RUN9_SNIPPET)
        r = ji.thermal_resistances(g["conservation"][0], g["lumped"][0])
        assert r["r_field_total_k_per_w"] == pytest.approx(1.472 / 0.065434, rel=1e-6)
        assert r["r_field_bottompath_k_per_w"] == pytest.approx(1.472 / 0.043961, rel=1e-6)
        assert r["r_lumped_k_per_w"] == pytest.approx(4.12 / 0.065434, rel=1e-6)
        # 集总/场级 ≈ 2.8×（真机 run7/run9 复现口径）
        assert r["r_lumped_k_per_w"] / r["r_field_total_k_per_w"] == pytest.approx(2.80, abs=0.01)

    def test_judge_handles_missing_logs(self, tmp_path):
        out = ji.judge(tmp_path)
        assert out["verdict"] == "FAIL" and out["gates_run9"]["conservation"] is None


class TestGyselMetrics:
    def _csv(self, tmp_path: Path, null_ghz: float) -> Path:
        f = np.linspace(2.25e9, 2.75e9, 401)
        s21 = np.full(f.size, 10 ** (-3.2 / 20) + 0j)
        s31 = s21.copy()
        # 隔离：以 null_ghz 为零点的洛伦兹谷；匹配：宽浅谷
        s23 = 10 ** (-25 / 20) * (1 - 0.98 * np.exp(-((f / 1e9 - null_ghz) / 0.05) ** 2)) + 0j
        s11 = 10 ** (-25 / 20) * np.ones(f.size) + 0j
        rows = np.column_stack([f, s11.real, s11.imag, s21.real, s21.imag,
                                s31.real, s31.imag, s23.real, s23.imag])
        p = tmp_path / "sparams.csv"
        np.savetxt(p, rows, delimiter=",",
                   header="freq_hz,re_S11,im_S11,re_S21,im_S21,re_S31,im_S31,re_S23,im_S23",
                   comments="")
        return p

    def test_metrics_null_offset_and_split(self, tmp_path):
        sp = jg.load_sparams(self._csv(tmp_path, 2.45))
        m = jg.metrics(sp, 2.5)
        assert m["at_f0"]["split_diff_db"] == pytest.approx(0.0, abs=1e-9)
        assert m["at_f0"]["phase_diff_deg"] == pytest.approx(0.0, abs=1e-9)
        assert m["iso_null"]["f_ghz"] == pytest.approx(2.45, abs=2e-3)
        assert m["iso_null"]["offset_pct"] == pytest.approx(-2.0, abs=0.1)
        assert m["at_f0"]["s21_db"] == pytest.approx(-3.2, abs=1e-6)

    def test_eps_eff_from_beta_closed_form(self, tmp_path):
        f = np.array([2.4e9, 2.5e9, 2.6e9])
        eps = 2.8797
        beta = 2 * np.pi * f / jg.C0 * np.sqrt(eps)
        p = tmp_path / "port_beta.csv"
        np.savetxt(p, np.column_stack([f, beta]), delimiter=",",
                   header="freq_hz,beta_rad_per_m", comments="")
        assert jg.eps_eff_from_beta(p, 2.5) == pytest.approx(eps, rel=1e-9)

    def test_bridge_dev_constant(self):
        assert pytest.approx(2.32, abs=0.01) == jg.BRIDGE_DEV_PCT


class TestBranchlineClosedForm:
    def test_implied_eps_eff_of_nominal_arm(self):
        # 20.5mm 当 λ/4@2.4GHz → εeff≈2.32≈(3.66+1)/2 薄线极限
        assert jb.implied_eps_eff(20.5, 2.4) == pytest.approx(2.3206, abs=1e-3)
        assert jb.implied_eps_eff(20.5, 2.4) == pytest.approx((3.66 + 1) / 2, abs=0.01)

    def test_quarter_wave_roundtrip(self):
        ee = 2.8523
        l4 = jb.quarter_wave_mm(2.4, ee)
        assert l4 == pytest.approx(18.49, abs=0.01)
        assert jb.f_quarter_wave_ghz(l4, ee) == pytest.approx(2.4, rel=1e-12)
        # 名义 20.5mm 在 50Ω 臂 εeff 下的 λ/4 频率 ≈2.165GHz（−9.8%）
        assert jb.f_quarter_wave_ghz(20.5, ee) == pytest.approx(2.1648, abs=1e-3)
