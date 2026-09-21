"""数据工厂二期 A 批 2D 采集驱动单测（合成数据钉死，零真机零长跑）。

被测对象：scripts/factory_a2d_collect.py 的纯逻辑（build_a2d_plan /
judge_batch / a2d_fingerprint / pending_points / is_cached_run）与 2D 标准
run 产物落盘接线（write_run_products_2d → dataset_service 成行契约）。
真跑面不在单测范围——真机批量由主控按 criteria.md 独立执行。

数值口径（#118 合成注入→回收）：合成无损线网络（已知 εeff、已知线长）验证
compute_point_metrics 的逐点 line_len 接线——S21 斜率口径 eps_eff 依赖线长，
传错=40mm 常量污染（criteria 实现契约）。
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

import factory_a2d_collect as a2d
import factory_m1_collect as m1
from factory_a2d_collect import (
    a2d_fingerprint,
    build_a2d_plan,
    is_cached_run,
    judge_batch,
    latest_eval_dir,
    pending_points,
    write_run_products_2d,
)


def _line_network(eps_eff: float = 2.9, line_len_mm: float = 40.0,
                  s11_mag: float = 0.05, n_f: int = 41):
    """合成均匀线网络：S21 相位斜率 = 已知 εeff×线长，S11 恒定小幅（匹配态）。"""
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


class TestNamingContract:
    """criteria 预声明命名/常量契约（防静默漂移）。"""

    def test_names_and_quota(self):
        assert a2d.STUDY == "datafactory_a2d"
        assert a2d.DATASET_NAME == "datafactory_a2d_mline_20260921"
        assert a2d.PROBE_DATASET == "datafactory_a2d_ingest_probe"
        assert a2d.QUOTA_TRIALS == 120 and a2d.QUOTA_WALL_H == 3.0
        assert a2d.MEDIAN_WALL_GATE_S == 60.0
        assert a2d.MAX_WALL_GATE_S == 120.0
        assert a2d.MIN_ROWS_GATE == 100
        assert a2d.LHS_SEED == 20260921
        assert a2d.LHS_MIN_DIST == 0.02
        assert a2d.N_LHS == 111

    def test_judgment_path_in_m2d_dir(self):
        assert a2d.JUDGMENT_PATH == (
            a2d.REPO / "runs" / "datafactory_m2d_20260921" / "judgment.json")
        assert a2d.ROOT == a2d.REPO / "runs" / "datafactory_a2d"
        assert a2d.LOCK_PATH == a2d.REPO / "runs" / ".oe_collect.lock"

    def test_opt_params_double_key(self):
        # C-05 契约面：opt_params 必须显式双键，否则第二维静默不入数据集行
        assert set(a2d.OPT_PARAMS_2D) == {"w_mm", "line_len_mm"}
        assert a2d.OPT_PARAMS_2D["w_mm"] == {"low": 0.5, "high": 2.0}
        assert a2d.OPT_PARAMS_2D["line_len_mm"] == {"low": 20.0, "high": 60.0}

    def test_nine_anchors_declared(self):
        got = [(w, len_mm) for _r, w, len_mm in a2d.ANCHORS]
        assert got == [(0.5, 20.0), (0.5, 60.0), (2.0, 20.0), (2.0, 60.0),
                       (1.113, 40.0), (0.745, 40.0), (1.182, 40.0),
                       (1.113, 20.0), (1.113, 60.0)]


class TestBuildA2DPlan:
    def test_exactly_120_with_9_double_key_anchors(self):
        plan = build_a2d_plan()
        assert plan["stats"]["n_plan_total"] == 120
        assert len(plan["points"]) == 120
        anchors = [p for p in plan["points"] if p["kind"] == "anchor"]
        assert len(anchors) == 9
        for p in anchors:
            assert set(p) >= {"point_id", "w_mm", "line_len_mm",
                              "kind", "anchor_role"}
            assert 0.5 <= p["w_mm"] <= 2.0
            assert 20.0 <= p["line_len_mm"] <= 60.0
        lhs = [p for p in plan["points"] if p["kind"] == "lhs"]
        assert len(lhs) == 111

    def test_deterministic(self):
        assert build_a2d_plan()["points"] == build_a2d_plan()["points"]

    def test_no_duplicate_fingerprints(self):
        plan = build_a2d_plan()
        keys = [a2d_fingerprint(p["w_mm"], p["line_len_mm"])
                for p in plan["points"]]
        assert len(keys) == len(set(keys))

    def test_point_ids_unique_with_double_param_segments(self):
        plan = build_a2d_plan()
        ids = [p["point_id"] for p in plan["points"]]
        assert len(ids) == len(set(ids))
        for pid in ids:
            assert pid.startswith("a2d_w")
            assert "_l" in pid  # 双参数段（w-only 会撞名，criteria 契约）
        assert ids[0] == "a2d_w0500_l20000"

    def test_lhs_within_bounds(self):
        plan = build_a2d_plan()
        for p in plan["points"]:
            assert 0.5 <= p["w_mm"] <= 2.0
            assert 20.0 <= p["line_len_mm"] <= 60.0

    def test_point_id_collision_guard(self):
        used: set[str] = set()
        p1 = a2d._point_id(1.113, 40.0, used)
        used.add(p1)
        p2 = a2d._point_id(1.113, 40.0, used)
        assert p1 != p2 and p2.startswith(p1)

    def test_fingerprint_stable(self):
        assert a2d_fingerprint(1.113, 40.0) == (1113000, 40000000)
        assert a2d_fingerprint(0.5, 20.0) == a2d_fingerprint(0.5, 20.0)


class TestResume:
    def test_pending_points_skips_done_and_idempotent(self):
        plan = build_a2d_plan()
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
        assert a2d.done_run_ids(index) == ["rid_a", "rid_b"]


class TestJudgeBatch:
    def test_pass_all_gates_cached_excluded_from_wall_stats(self):
        # 真跑点 wall [40,50] 中位 45≤60；cached 9 点不计时长（criteria G2）
        j = judge_batch(attempted=120, n_rows=120,
                        walls_real_s=[40.0, 50.0], n_cached=9)
        assert j["pass"] and j["verdict"] == "PASS"
        g2 = j["gates"]["G2_real_wall_median_le_60s_and_max_le_120s"]
        assert g2["median_wall_s"] == 45.0
        assert g2["n_real_points"] == 2 and g2["n_cached_excluded"] == 9
        assert j["gates"]["G1_row_rate_100pct"]["n_cached_rows"] == 9

    def test_cached_slow_wall_never_enters_stats(self):
        # cached 点墙钟再大也不进统计——只有 walls_real_s 进门（契约面：
        # 调用方从 index 取 done 且非 cached 的 wall）
        j = judge_batch(attempted=120, n_rows=120,
                        walls_real_s=[40.0, 50.0], n_cached=9)
        assert j["gates"]["G2_real_wall_median_le_60s_and_max_le_120s"]["pass"]

    def test_fail_median_over_60(self):
        j = judge_batch(attempted=10, n_rows=10, walls_real_s=[61.0, 61.0, 62.0])
        assert not j["pass"]
        assert "G2_real_wall_median_le_60s_and_max_le_120s" in j["verdict"]

    def test_fail_single_point_over_120_even_if_median_ok(self):
        # 单点 ≤120s 门：中位 25 达标但 max 300 超单点门 → FAIL
        j = judge_batch(attempted=4, n_rows=4,
                        walls_real_s=[10.0, 20.0, 30.0, 300.0])
        g2 = j["gates"]["G2_real_wall_median_le_60s_and_max_le_120s"]
        assert not g2["pass"] and g2["max_wall_s"] == 300.0
        assert not j["pass"]

    def test_fail_row_rate(self):
        j = judge_batch(attempted=120, n_rows=119, walls_real_s=[40.0])
        assert not j["pass"] and "G1_row_rate_100pct" in j["verdict"]

    def test_fail_rows_under_100(self):
        j = judge_batch(attempted=99, n_rows=99, walls_real_s=[40.0])
        assert not j["pass"] and "G3_rows_ge_100" in j["verdict"]
        j100 = judge_batch(attempted=100, n_rows=100, walls_real_s=[40.0])
        assert j100["gates"]["G3_rows_ge_100"]["pass"]

    def test_zero_real_walls_fails_closed(self):
        # 零真跑样本=异常态，G2 如实 FAIL 不冒充 PASS（criteria fail-closed）
        j = judge_batch(attempted=5, n_rows=5, walls_real_s=[], n_cached=5)
        assert not j["gates"]["G2_real_wall_median_le_60s_and_max_le_120s"]["pass"]
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


class TestWriteRunProducts2D:
    def test_products_carry_per_point_line_len_everywhere(self, tmp_path):
        # criteria 契约：meta.json/metrics 的 line_len 写参数值不写常量
        # （m1.write_run_products 两处读模块全局，本写入器临时置值还原）
        from rfauto.service.dataset_service import _collect_run_points

        w, len_mm = 0.9, 55.0
        net = _line_network(line_len_mm=len_mm)
        run_dir = tmp_path / "runs" / "20260921_000000_a2d01"
        (run_dir / "results").mkdir(parents=True)
        write_run_products_2d(run_dir, w, len_mm, net, wall_s=36.0,
                              eval_dir="evals/eval_0001",
                              metrics={"s11_db_max_in_band": -26.0}, notes=[])
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["line_len_mm"] == len_mm and meta["w_mm"] == w
        mj = json.loads(
            (run_dir / "results" / "metrics.json").read_text(encoding="utf-8"))
        assert mj["line_len_mm"] == len_mm
        import yaml

        snap = yaml.safe_load(
            (run_dir / "recipe.snapshot.yaml").read_text(encoding="utf-8"))
        assert set(snap["optimization"]["params"]) == {"w_mm", "line_len_mm"}
        assert snap["params"]["line_len_mm"]["value"] == len_mm
        points, errors, n_nf = _collect_run_points(run_dir)
        assert n_nf == 0
        assert len(points) == 1, errors
        assert points[0]["params"] == {"w_mm": w, "line_len_mm": len_mm}

    def test_global_constant_restored_after_write(self, tmp_path):
        net = _line_network(line_len_mm=33.0)
        run_dir = tmp_path / "runs" / "20260921_000000_a2d02"
        (run_dir / "results").mkdir(parents=True)
        sentinel = m1.LINE_LEN_MM
        write_run_products_2d(run_dir, 1.0, 33.0, net, 1.0, "e", {}, [])
        assert m1.LINE_LEN_MM is sentinel  # try/finally 还原，不泄漏

    def test_collect_contract_second_dim_is_variable(self, tmp_path):
        # C-05 反例钉：走 m1 默认 opt_params（w-only）时第二维不入行——
        # 2D 写入器必须显式双键（对照面）
        import yaml

        from rfauto.service.dataset_service import _collect_run_points

        net = _line_network()
        run_dir = tmp_path / "runs" / "20260921_000000_a2d03"
        (run_dir / "results").mkdir(parents=True)
        m1.write_run_products(run_dir, 1.0, net, 1.0, "e", {}, [],
                              line_len_mm=50.0)  # 未传 opt_params
        snap = yaml.safe_load(
            (run_dir / "recipe.snapshot.yaml").read_text(encoding="utf-8"))
        assert set(snap["optimization"]["params"]) == {"w_mm"}
        points, _errors, _ = _collect_run_points(run_dir)
        assert points[0]["params"] == {"w_mm": 1.0}


class TestPerPointLineLenMetrics:
    def test_eps_eff_uses_per_point_line_len(self):
        # S21 斜率口径 eps_eff 依赖 line_len：逐点 55mm 合成线按 55 回收、
        # 按常量 40 回收即污染（criteria 实现契约）
        net = _line_network(eps_eff=2.9, line_len_mm=55.0)
        metrics_ok, notes_ok = m1.compute_point_metrics(net, line_len_mm=55.0)
        assert metrics_ok["eps_eff_mean_in_band"] == pytest.approx(2.9, rel=1e-9)
        assert notes_ok == []
        metrics_bad, _ = m1.compute_point_metrics(net, line_len_mm=40.0)
        assert metrics_bad["eps_eff_mean_in_band"] != pytest.approx(2.9, rel=1e-3)
