"""数据工厂 M1 采集管线单测（合成数据钉死，零真机零长跑）。

被测对象：scripts/factory_m1_collect.py 的纯逻辑
（build_sampling_plan / compute_point_metrics / judge_m1 / w_fingerprint）
与标准 run 产物落盘接线（write_run_products → dataset_service 成行契约）。
真跑面不在单测范围——真机批量按判据文件独立执行。

数值口径（#118 合成注入→回收）：合成无损线网络（已知 εeff）验证
SpecEvaluator.eps_eff_band_average 内核经 compute_point_metrics 精确回收；
驻波污染网络验证 #255 守卫如实跳过（键缺省 + note），不凑数。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

from factory_m1_collect import (
    beta_metrics_from_port_beta,
    build_sampling_plan,
    compute_point_metrics,
    judge_m1,
    w_fingerprint,
    write_run_products,
)


def _line_network(eps_eff: float = 2.9, line_len_mm: float = 40.0,
                  s11_mag: float = 0.05, n_f: int = 41):
    """合成均匀线网络：S21 相位斜率 = 已知 εeff，S11 恒定小幅（匹配态）。"""
    import skrf

    c0 = 299792458.0
    tau = (eps_eff ** 0.5) * (line_len_mm * 1e-3) / c0
    f_ghz = np.linspace(2.0, 3.0, n_f)
    f_hz = f_ghz * 1e9
    phase = -2.0 * np.pi * f_hz * tau
    s21 = np.exp(1j * phase)
    s = np.zeros((n_f, 2, 2), dtype=complex)
    s[:, 0, 0] = s11_mag
    s[:, 1, 0] = s21
    s[:, 0, 1] = s21
    s[:, 1, 1] = s11_mag
    return skrf.Network(
        frequency=skrf.Frequency(float(f_ghz[0]), float(f_ghz[-1]), n_f, unit="ghz"),
        s=s, z0=50.0)


class TestBuildSamplingPlan:
    def test_deterministic_and_anchors(self):
        p1 = build_sampling_plan([], seed=42)
        p2 = build_sampling_plan([], seed=42)
        assert p1["points"] == p2["points"]
        assert p1["stats"]["n_plan_total"] == 120
        anchor_ws = sorted(
            p["w_mm"] for p in p1["points"] if p["is_anchor"])
        assert anchor_ws == [0.5, 0.745, 1.113, 1.182, 2.0]
        for pt in p1["points"]:
            assert 0.5 <= pt["w_mm"] <= 2.0
            assert pt["line_len_mm"] == 40.0

    def test_no_duplicate_w(self):
        plan = build_sampling_plan([], seed=42)
        keys = [w_fingerprint(p["w_mm"]) for p in plan["points"]]
        assert len(keys) == len(set(keys))

    def test_point_ids_unique(self):
        plan = build_sampling_plan([], seed=42)
        ids = [p["point_id"] for p in plan["points"]]
        assert len(ids) == len(set(ids))
        assert ids[0] == "m1_w0500"

    def test_dedup_drops_existing_and_refills(self):
        plan0 = build_sampling_plan([], seed=42)
        lhs_ws = [p["w_mm"] for p in plan0["points"] if not p["is_anchor"]]
        drop = lhs_ws[:3]
        plan = build_sampling_plan(drop, seed=42)
        got = {w_fingerprint(p["w_mm"]) for p in plan["points"]}
        for w in drop:
            assert w_fingerprint(w) not in got
        assert plan["stats"]["n_plan_total"] == 120
        assert plan["stats"]["n_dedup_dropped"] == 3

    def test_w_fingerprint_stable(self):
        assert w_fingerprint(1.113) == 1113000
        assert w_fingerprint(0.7) == w_fingerprint(0.7)


class TestComputePointMetrics:
    def test_eps_eff_recovered_from_synthetic_line(self):
        net = _line_network(eps_eff=2.9)
        metrics, notes = compute_point_metrics(net)
        eps = metrics.get("eps_eff_mean_in_band")
        assert eps is not None
        assert eps == pytest.approx(2.9, rel=1e-9)
        assert metrics["s11_db_max_in_band"] == pytest.approx(-26.0206, abs=0.01)
        assert notes == []

    def test_standing_wave_skips_eps_eff(self):
        net = _line_network(s11_mag=0.5)  # -6dB：带内 max|S11| > -10dB
        metrics, notes = compute_point_metrics(net)
        assert "eps_eff_mean_in_band" not in metrics
        assert len(notes) == 1 and "eps_eff_skipped" in notes[0]

    def test_s21_mean_in_band_present(self):
        net = _line_network()
        metrics, _ = compute_point_metrics(net)
        assert metrics["s21_db_mean_in_band"] == pytest.approx(0.0, abs=1e-6)


class TestJudgeM1:
    def test_pass_all_gates(self):
        j = judge_m1(attempted=120, n_rows=120,
                     walls_s=[35.0, 36.0, 40.0, 45.0])
        assert j["pass"] and j["verdict"] == "PASS"
        assert j["gates"]["G1_row_rate_100pct"]["row_rate"] == 1.0
        assert j["gates"]["G2_median_wall_le_50s"]["median_wall_s"] == 38.0

    def test_fail_unhealthy_breaks_row_rate(self):
        j = judge_m1(attempted=120, n_rows=119, walls_s=[35.0, 36.0],
                     n_unhealthy=1)
        assert not j["pass"]
        assert "G1_row_rate_100pct" in j["verdict"]

    def test_fail_slow_median(self):
        j = judge_m1(attempted=10, n_rows=10, walls_s=[60.0, 70.0])
        assert not j["pass"] and "G2_median_wall_le_50s" in j["verdict"]

    def test_fail_small_scale(self):
        j = judge_m1(attempted=50, n_rows=50, walls_s=[30.0])
        assert not j["pass"] and "G3_rows_ge_100" in j["verdict"]

    def test_zero_attempted_fails(self):
        j = judge_m1(attempted=0, n_rows=0, walls_s=[])
        assert not j["pass"]


class TestBetaMetricsFromPortBeta:
    """β 口径指标（参考面无关口径）合成回收钉。"""

    def _write_csv(self, path, rows):
        import csv as _csv
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    def test_eps_eff_beta_exact_recovery(self, tmp_path):
        # #118 合成注入→回收：β=69.73047888771784 @2.0GHz（M1 eval_0001 w=0.5 实测值）
        beta = 69.73047888771784
        f_hz = 2.0e9
        rows = [{"freq_hz": f_hz, "beta_rad_per_m": beta,
                 "beta2_rad_per_m": beta,
                 "re_zl1_ohm": 64.3, "im_zl1_ohm": 0.06,
                 "re_zl2_ohm": 64.3, "im_zl2_ohm": 0.07}]
        csv_path = tmp_path / "port_beta.csv"
        self._write_csv(csv_path, rows)
        out = beta_metrics_from_port_beta(csv_path, band=(2.0, 2.0 + 1e-9))
        assert out is not None
        import math
        expected = (beta * 299792458.0 / (2 * math.pi * f_hz)) ** 2
        assert out["eps_eff_beta_mean_in_band"] == pytest.approx(expected, rel=1e-12)
        assert out["zl1_re_ohm_med_in_band"] == 64.3

    def test_missing_file_returns_none(self, tmp_path):
        assert beta_metrics_from_port_beta(tmp_path / "nope.csv") is None

    def test_band_outside_returns_none(self, tmp_path):
        rows = [{"freq_hz": 1.0e9, "beta_rad_per_m": 50.0,
                 "beta2_rad_per_m": 50.0, "re_zl1_ohm": 50.0,
                 "im_zl1_ohm": 0.0, "re_zl2_ohm": 50.0, "im_zl2_ohm": 0.0}]
        csv_path = tmp_path / "port_beta.csv"
        self._write_csv(csv_path, rows)
        assert beta_metrics_from_port_beta(csv_path) is None  # 缺省带 2.4-2.6

    def test_compute_point_metrics_wires_beta_columns(self, tmp_path):
        beta = 69.73047888771784
        rows = [{"freq_hz": 2.5e9, "beta_rad_per_m": beta,
                 "beta2_rad_per_m": beta,
                 "re_zl1_ohm": 64.3, "im_zl1_ohm": 0.0,
                 "re_zl2_ohm": 64.3, "im_zl2_ohm": 0.0}]
        csv_path = tmp_path / "port_beta.csv"
        self._write_csv(csv_path, rows)
        net = _line_network(eps_eff=2.9)
        metrics, notes = compute_point_metrics(net, port_beta_csv=csv_path)
        # S21 斜率口径与 β 口径并列；β 为首选消费列（期望值按公式算，不硬编码）
        import math
        expected = (beta * 299792458.0 / (2 * math.pi * 2.5e9)) ** 2
        assert "eps_eff_beta_mean_in_band" in metrics
        assert "zl1_re_ohm_med_in_band" in metrics
        assert metrics["eps_eff_beta_mean_in_band"] == pytest.approx(expected, rel=1e-12)
        assert any("β" in n for n in notes)


class TestWriteRunProducts:
    def test_products_satisfy_run_once_collect_contract(self, tmp_path):
        from rfauto.service.dataset_service import _collect_run_points

        w = 1.113
        net = _line_network()
        run_dir = tmp_path / "runs" / "20260919_000000_probe01"
        (run_dir / "results").mkdir(parents=True)
        write_run_products(run_dir, w, net, wall_s=36.0, eval_dir="evals/eval_0001",
                           metrics={"s11_db_max_in_band": -26.0}, notes=[])
        assert (run_dir / "recipe.snapshot.yaml").exists()
        assert (run_dir / "results" / "params.s2p").exists()
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["status"] == "done"
        assert meta["model"] == "mline" and meta["adapter"] == "openems"
        mj = json.loads(
            (run_dir / "results" / "metrics.json").read_text(encoding="utf-8"))
        assert mj["metrics"]["s11_db_max_in_band"] == -26.0

        points, errors, n_nf = _collect_run_points(run_dir)
        assert n_nf == 0
        assert len(points) == 1, errors
        pt = points[0]
        assert pt["params"] == {"w_mm": w}
        assert pt["source"] == "run_once"
        assert pt["provenance_extra"]["n_ports"] == 2
        assert pt["provenance_extra"]["run_id"] == run_dir.name
        assert pt["provenance_extra"]["touchstone_path"].endswith("params.s2p")

    def test_snapshot_params_only_w_is_variable(self, tmp_path):
        import yaml

        net = _line_network()
        run_dir = tmp_path / "runs" / "20260920_000000_probe02"
        (run_dir / "results").mkdir(parents=True)
        write_run_products(run_dir, 0.9, net, 30.0, "e", {}, [])
        snap = yaml.safe_load(
            (run_dir / "recipe.snapshot.yaml").read_text(encoding="utf-8"))
        assert set(snap["optimization"]["params"]) == {"w_mm"}
        assert snap["params"]["w_mm"]["value"] == 0.9
        assert snap["params"]["line_len_mm"]["value"] == 40.0

    def test_2d_opt_params_makes_second_dim_a_variable(self, tmp_path):
        # 扩 2D 须显式声明第二维，否则静默不入行
        import yaml

        from rfauto.service.dataset_service import _collect_run_points

        net = _line_network()
        run_dir = tmp_path / "runs" / "20260920_000000_probe03"
        (run_dir / "results").mkdir(parents=True)
        write_run_products(
            run_dir, 0.9, net, 30.0, "e", {}, [],
            opt_params={"w_mm": {"low": 0.5, "high": 2.0},
                        "line_len_mm": {"low": 20.0, "high": 60.0}})
        snap = yaml.safe_load(
            (run_dir / "recipe.snapshot.yaml").read_text(encoding="utf-8"))
        assert set(snap["optimization"]["params"]) == {"w_mm", "line_len_mm"}
        points, errors, _ = _collect_run_points(run_dir)
        assert len(points) == 1, errors
        assert points[0]["params"] == {"w_mm": 0.9, "line_len_mm": 40.0}
