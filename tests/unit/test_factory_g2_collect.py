"""数据工厂二期 B 批 cpw 采集驱动单测（合成数据钉死，零真机零长跑）。

被测对象：scripts/factory_g2_collect.py 的纯逻辑（build_g2_plan /
judge_batch / g2_fingerprint / pending_points / is_cached_run）与 cpw 2D
标准 run 产物落盘接线（write_run_products_g2 → dataset_service 成行契约）。
真跑面不在单测范围——真机批量由主控按 criteria.md 独立执行（主代理排程）。

数值口径（#118 合成注入→回收）：合成无损线网络（已知 εeff、已知线长 40mm）
验证 compute_point_metrics 的 β 口径接线（port_beta.csv → eps_eff_beta_
mean_in_band）；β=(2πf√εeff/c0) 由闭式真值生成，回收须逐位一致量级。

新驱动决策（criteria §4）：factory_a2d_collect.py 零改动——本文件不 import
a2d，防在制批驱动漂移。
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

import factory_g2_collect as g2
import factory_m1_collect as m1
from factory_g2_collect import (
    build_g2_plan,
    g2_fingerprint,
    is_cached_run,
    judge_batch,
    latest_eval_dir,
    pending_points,
    write_run_products_g2,
)


def _cpw_line_network(eps_eff: float = 2.5673, line_len_mm: float = 40.0,
                      z0: float = 50.0, n_f: int = 41):
    """合成均匀线网络：S21 相位斜率=已知 εeff×线长，S11=|Γ(Z0,50)| 匹配态。"""
    import skrf

    c0 = 299792458.0
    tau = (eps_eff ** 0.5) * (line_len_mm * 1e-3) / c0
    f_ghz = np.linspace(2.0, 3.0, n_f)
    f_hz = f_ghz * 1e9
    phase = -2.0 * np.pi * f_hz * tau
    gamma = (z0 - 50.0) / (z0 + 50.0)
    s21 = np.exp(1j * phase) * np.sqrt(1.0 - gamma**2)
    s = np.zeros((n_f, 2, 2), dtype=complex)
    s[:, 0, 0] = gamma
    s[:, 1, 0] = s21
    s[:, 0, 1] = s21
    s[:, 1, 1] = gamma
    return skrf.Network(
        frequency=skrf.Frequency(float(f_ghz[0]), float(f_ghz[-1]), n_f, unit="ghz"),
        s=s, z0=50.0)


def _write_port_beta_csv(path: Path, eps_eff: float = 2.5673, n_f: int = 41):
    """cpw else 分支列契约 [freq_hz, beta_rad_per_m]（无 ZL 列，criteria §4）。"""
    c0 = 299792458.0
    f_ghz = np.linspace(2.0, 3.0, n_f)
    beta = 2.0 * np.pi * (f_ghz * 1e9) * (eps_eff**0.5) / c0
    lines = ["freq_hz,beta_rad_per_m"]
    lines += [f"{f * 1e9:.1f},{b:.12e}" for f, b in zip(f_ghz, beta, strict=True)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestNamingContract:
    """criteria 预声明命名/常量契约（防静默漂移）。"""

    def test_names_and_quota(self):
        assert g2.TEMPLATE == "cpw"
        assert g2.STUDY == "datafactory_g2_cpw"
        assert g2.DATASET_NAME == "datafactory_g2_cpw_20260922"
        assert g2.PROBE_DATASET == "datafactory_g2_cpw_ingest_probe"
        assert g2.QUOTA_TRIALS == 120 and g2.QUOTA_WALL_H == 6.0
        assert g2.MEDIAN_WALL_GATE_S == 180.0
        assert g2.MAX_WALL_GATE_S == 1795.0
        assert g2.SOLVE_TIMEOUT_S == 1800.0
        assert g2.MIN_ROWS_GATE == 100
        assert g2.LHS_SEED == 20260922
        assert g2.LHS_MIN_DIST == 0.02
        assert g2.N_LHS == 111
        assert g2.LINE_LEN_MM == 40.0

    def test_paths(self):
        assert g2.JUDGMENT_PATH == (
            g2.REPO / "runs" / "datafactory_g2_cpw_20260922" / "judgment.json")
        assert g2.ROOT == g2.REPO / "runs" / "datafactory_g2_cpw"
        assert g2.LOCK_PATH == g2.REPO / "runs" / ".oe_collect.lock"
        assert g2.CRITERIA_REL == (
            "runs/datafactory_g2_cpw_20260922/criteria.md")

    def test_opt_params_double_key_w_gap(self):
        # C-05 契约面：opt_params 必须显式双键（w+gap），line_len 不入行
        assert set(g2.OPT_PARAMS_2D) == {"w_mm", "gap_mm"}
        assert g2.OPT_PARAMS_2D["w_mm"] == {"low": 0.5, "high": 1.6}
        assert g2.OPT_PARAMS_2D["gap_mm"] == {"low": 0.15, "high": 0.5}

    def test_nine_anchors_declared(self):
        got = [(w, gap) for _r, w, gap in g2.ANCHORS]
        assert got == [(0.5, 0.15), (0.5, 0.5), (1.6, 0.15), (1.6, 0.5),
                       (0.849, 0.2), (0.7687, 0.15), (1.0465, 0.5),
                       (0.849, 0.15), (0.849, 0.5)]
        roles = [r for r, _w, _g in g2.ANCHORS]
        assert roles == ["corner"] * 4 + ["nominal"] + ["z50_contour"] * 2 \
            + ["gap_endpoint"] * 2

    def test_nominal_is_50ohm_per_closed_form(self):
        # 名义锚 (0.849,0.2) 对 _cpwg_ri = 50Ω（zconv 报告同源对账，criteria §0）
        from rfauto.core.calculators import _cpwg_ri

        eps, z0 = _cpwg_ri(0.849, 0.2, 0.508, 3.66)
        assert z0 == pytest.approx(50.0, abs=1e-3)
        assert eps == pytest.approx(2.5672930681609403, rel=1e-12)

    def test_a2d_driver_untouched_contract(self):
        # 新驱动决策（criteria §4）：a2d 常量不被本批改写（不同值即隔离证据）
        import factory_a2d_collect as a2d

        assert a2d.STUDY == "datafactory_a2d"
        assert a2d.DATASET_NAME == "datafactory_a2d_mline_20260921"
        assert g2.STUDY != a2d.STUDY


class TestBuildG2Plan:
    def test_exactly_120_with_9_double_key_anchors(self):
        plan = build_g2_plan()
        assert plan["stats"]["n_plan_total"] == 120
        assert len(plan["points"]) == 120
        anchors = [p for p in plan["points"] if p["kind"] == "anchor"]
        assert len(anchors) == 9
        for p in anchors:
            assert set(p) >= {"point_id", "w_mm", "gap_mm",
                              "kind", "anchor_role"}
            assert 0.5 <= p["w_mm"] <= 1.6
            assert 0.15 <= p["gap_mm"] <= 0.5
        lhs = [p for p in plan["points"] if p["kind"] == "lhs"]
        assert len(lhs) == 111

    def test_deterministic(self):
        assert build_g2_plan()["points"] == build_g2_plan()["points"]

    def test_no_duplicate_fingerprints(self):
        plan = build_g2_plan()
        keys = [g2_fingerprint(p["w_mm"], p["gap_mm"]) for p in plan["points"]]
        assert len(keys) == len(set(keys))

    def test_point_ids_unique_with_double_param_segments(self):
        plan = build_g2_plan()
        ids = [p["point_id"] for p in plan["points"]]
        assert len(ids) == len(set(ids))
        for pid in ids:
            assert pid.startswith("g2_w")
            assert "_g" in pid  # 双参数段（w-only 会撞名，criteria 契约）
        assert ids[0] == "g2_w0500_g0150"

    def test_lhs_within_bounds(self):
        plan = build_g2_plan()
        for p in plan["points"]:
            assert 0.5 <= p["w_mm"] <= 1.6
            assert 0.15 <= p["gap_mm"] <= 0.5

    def test_point_id_collision_guard(self):
        used: set[str] = set()
        p1 = g2._point_id(0.849, 0.2, used)
        used.add(p1)
        p2 = g2._point_id(0.849, 0.2, used)
        assert p1 != p2 and p2.startswith(p1)

    def test_fingerprint_stable(self):
        assert g2_fingerprint(0.849, 0.2) == (849000, 200000)
        assert g2_fingerprint(0.5, 0.15) == g2_fingerprint(0.5, 0.15)


class TestResume:
    def test_pending_points_skips_done_and_idempotent(self):
        plan = build_g2_plan()
        index = {}
        first = pending_points(plan, index)
        assert len(first) == 120
        pid0 = str(plan["points"][0]["point_id"])
        pid5 = str(plan["points"][5]["point_id"])
        index[pid0] = {"status": "done", "rid": "r0"}
        index[pid5] = {"status": "failed", "rid": "r5"}  # failed 不跳过（可重试）
        second = pending_points(plan, index)
        assert len(second) == 119
        assert pid0 not in {str(p["point_id"]) for p in second}
        third = pending_points(plan, index)
        assert second == third  # 幂等

    def test_done_run_ids_sorted_and_filtered(self):
        index = {
            "b": {"status": "done", "rid": "rid_b"},
            "a": {"status": "done", "rid": "rid_a"},
            "c": {"status": "failed", "rid": "rid_c"},
        }
        assert g2.done_run_ids(index) == ["rid_a", "rid_b"]


class TestJudgeBatch:
    def test_pass_all_gates_cached_excluded_from_wall_stats(self):
        # 真跑点 wall [100,140] 中位 120≤180；cached 点不计时长（criteria G2）
        j = judge_batch(attempted=120, n_rows=120,
                        walls_real_s=[100.0, 140.0], n_cached=1)
        assert j["pass"] and j["verdict"] == "PASS"
        g2gate = j["gates"]["G2_real_wall_median_le_180s_and_max_le_1795s"]
        assert g2gate["median_wall_s"] == 120.0
        assert g2gate["n_real_points"] == 2 and g2gate["n_cached_excluded"] == 1
        assert j["gates"]["G1_row_rate_100pct"]["n_cached_rows"] == 1

    def test_fail_median_over_180(self):
        j = judge_batch(attempted=10, n_rows=10, walls_real_s=[181.0, 181.0, 182.0])
        assert not j["pass"]
        assert "G2_real_wall_median_le_180s_and_max_le_1795s" in j["verdict"]

    def test_fail_single_point_over_1795_even_if_median_ok(self):
        # 单点 ≤1795s 门：中位 100 达标但 max 2000 超单点门 → FAIL
        j = judge_batch(attempted=4, n_rows=4,
                        walls_real_s=[80.0, 100.0, 120.0, 2000.0])
        g2gate = j["gates"]["G2_real_wall_median_le_180s_and_max_le_1795s"]
        assert not g2gate["pass"] and g2gate["max_wall_s"] == 2000.0
        assert not j["pass"]

    def test_fail_row_rate(self):
        j = judge_batch(attempted=120, n_rows=119, walls_real_s=[100.0])
        assert not j["pass"] and "G1_row_rate_100pct" in j["verdict"]

    def test_fail_rows_under_100(self):
        j = judge_batch(attempted=99, n_rows=99, walls_real_s=[100.0])
        assert not j["pass"] and "G3_rows_ge_100" in j["verdict"]
        j100 = judge_batch(attempted=100, n_rows=100, walls_real_s=[100.0])
        assert j100["gates"]["G3_rows_ge_100"]["pass"]

    def test_zero_real_walls_fails_closed(self):
        # 零真跑样本=异常态，G2 如实 FAIL 不冒充 PASS（criteria fail-closed）
        j = judge_batch(attempted=5, n_rows=5, walls_real_s=[], n_cached=5)
        assert not j["gates"]["G2_real_wall_median_le_180s_and_max_le_1795s"]["pass"]
        assert not j["pass"]

    def test_zero_attempted_fails(self):
        j = judge_batch(attempted=0, n_rows=0, walls_real_s=[])
        assert not j["pass"]


class TestCachedDetection:
    def test_no_eval_dir_is_cached(self):
        assert is_cached_run(None) is True

    def test_eval_dir_without_engine_output_is_cached(self, tmp_path):
        d = tmp_path / "eval_0001"
        d.mkdir()
        (d / "simulation.py").write_text("# render only", encoding="utf-8")
        assert is_cached_run(d) is True

    def test_eval_dir_with_sparams_is_real_run(self, tmp_path):
        d = tmp_path / "eval_0002"
        d.mkdir()
        (d / "sparams.csv").write_text("freq,s11\n", encoding="utf-8")
        assert is_cached_run(d) is False

    def test_latest_eval_dir_mtime_attribution(self, tmp_path):
        import os

        old = tmp_path / "eval_0001"
        new = tmp_path / "eval_0002"
        old.mkdir()
        new.mkdir()
        os.utime(old, (1e9, 1e9))
        t_new = 2e9
        os.utime(new, (t_new, t_new))
        assert latest_eval_dir(tmp_path, t_new - 10) == new
        # 起点晚于全部目录 → 无归属（None）
        assert latest_eval_dir(tmp_path, t_new + 1e6) is None


class TestWriteRunProductsG2:
    def test_products_carry_w_gap_line_len_constant(self, tmp_path):
        # criteria 契约：数据集行 params={w_mm,gap_mm}（C-05 双键），
        # line_len=40 常量留 meta/metrics setup 元数据
        from rfauto.service.dataset_service import _collect_run_points

        w, gap = 0.9, 0.3
        net = _cpw_line_network()
        run_dir = tmp_path / "runs" / "20260922_000000_g2001"
        (run_dir / "results").mkdir(parents=True)
        write_run_products_g2(run_dir, w, gap, net, wall_s=95.0,
                              eval_dir="evals/eval_0001",
                              metrics={"s11_db_max_in_band": -25.0}, notes=[])
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["w_mm"] == w and meta["gap_mm"] == gap
        assert meta["line_len_mm"] == 40.0
        assert meta["model"] == "cpw" and meta["study_name"] == "datafactory_g2_cpw"
        assert meta["source"] == "factory_g2_collect"
        mj = json.loads(
            (run_dir / "results" / "metrics.json").read_text(encoding="utf-8"))
        assert mj["gap_mm"] == gap and mj["line_len_mm"] == 40.0
        import yaml

        snap = yaml.safe_load(
            (run_dir / "recipe.snapshot.yaml").read_text(encoding="utf-8"))
        assert set(snap["optimization"]["params"]) == {"w_mm", "gap_mm"}
        assert set(snap["params"]) == {"w_mm", "gap_mm", "line_len_mm"}
        assert snap["params"]["gap_mm"]["value"] == gap
        points, errors, n_nf = _collect_run_points(run_dir)
        assert n_nf == 0
        assert len(points) == 1, errors
        assert points[0]["params"] == {"w_mm": w, "gap_mm": gap}

    def test_m1_global_constant_untouched(self, tmp_path):
        # 本写入器无 a2d 式全局 patch 面：m1.LINE_LEN_MM 不被触碰
        net = _cpw_line_network()
        run_dir = tmp_path / "runs" / "20260922_000000_g2002"
        (run_dir / "results").mkdir(parents=True)
        sentinel = m1.LINE_LEN_MM
        write_run_products_g2(run_dir, 1.0, 0.25, net, 1.0, "e", {}, [])
        assert m1.LINE_LEN_MM is sentinel

    def test_touchstone_is_2port_s2p(self, tmp_path):
        # #248 扩展名契约：cpw 2 端口 → params.s2p，skrf 读回 rank=2
        import skrf

        net = _cpw_line_network()
        run_dir = tmp_path / "runs" / "20260922_000000_g2003"
        (run_dir / "results").mkdir(parents=True)
        write_run_products_g2(run_dir, 0.849, 0.2, net, 1.0, "e", {}, [])
        back = skrf.Network(str(run_dir / "results" / "params.s2p"))
        assert back.s.shape[1:] == (2, 2)


class TestPerPointMetricsCpwCompat:
    def test_beta_eps_recovery_from_port_beta_csv(self, tmp_path):
        # β 口径 eps 回收（cpw else 分支列契约）：β=(2πf√ε/c0) 注入 →
        # eps_eff_beta_mean_in_band 回收 = 真值（criteria cpw metrics 兼容性）
        csv = tmp_path / "port_beta.csv"
        _write_port_beta_csv(csv, eps_eff=2.5673)
        net = _cpw_line_network(eps_eff=2.5673)
        metrics, notes = m1.compute_point_metrics(
            net, line_len_mm=40.0, port_beta_csv=csv)
        assert metrics["eps_eff_beta_mean_in_band"] == pytest.approx(
            2.5673, rel=1e-9)
        assert any("eps_eff 口径=β" in n for n in notes)
        # cpw else 分支无 ZL 列 → metrics 无 zl 键（如实缺省，criteria §4）
        assert "zl1_re_ohm_med_in_band" not in metrics
        assert "zl2_re_ohm_med_in_band" not in metrics

    def test_s11_s21_metrics_two_port(self):
        net = _cpw_line_network(eps_eff=2.5673, z0=50.0)
        metrics, _ = m1.compute_point_metrics(net, line_len_mm=40.0)
        assert metrics["s11_db_max_in_band"] < -100.0  # 50Ω 名义近零反射
        assert metrics["s21_db_mean_in_band"] == pytest.approx(0.0, abs=1e-6)
        # S21 斜率口径（#255 守卫满足时产出，留档非消费）
        assert metrics["eps_eff_mean_in_band"] == pytest.approx(2.5673, rel=1e-6)
