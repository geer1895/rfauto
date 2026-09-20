"""WP3.4 patch 族 HFSS ground-truth 战役脚本单测（合成数据钉死，零真机零长跑）。

被测对象：scripts/wp34_patch_gt_campaign.py 的纯函数面与可恢复主循环：
- LHS 计划确定性（同 seed 同点集、N=36、边界内）；
- 参数名对齐（注册表 hfss 行键并集 == 配方 bounds 键集合，否则显式报错）；
- progress 恢复（done 跳过、失败用尽跳过、失败未用尽重试、口径漂移拒绝混跑）；
- HFSS 不可用显式报错（拒绝降级 fake）；
- 主循环（monkeypatch run_once：成功/失败/异常/重试计数/日志/配方副本值）；
- ingest 收尾（monkeypatch materialize/readiness：run_ids = 旧 ∪ 新，readiness.json 落盘）。
真机求解入口全程 monkeypatch，不触 AEDT。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import wp34_patch_gt_campaign as wp34

BOUNDS = {
    "feed_offset_mm": (3.0, 20.0),
    "patch_len_mm": (35.0, 45.0),
    "patch_w_mm": (40.0, 60.0),
}

TEMPLATE_YAML = """\
model: patch_antenna
recipe_version: 1
schema_version: 1
notes: "synthetic patch template"
params:
  f0_ghz:         {value: 2.4,  unit: GHz}
  z0_ohm:         {value: 50,   unit: ohm}
  substrate:      rogers4350b_h0.508
  patch_len_mm:   {value: 40.0}
  patch_w_mm:     {value: 50.0}
  feed_offset_mm: {value: 10.0}
setup:
  solver: DrivenModal
  freq_range_ghz: [2.3, 2.5]
  points: 11
objectives:
  - {metric: s11_db, band: [2.3, 2.5], op: max_below, value: -10}
optimization:
  params:
    patch_len_mm:   {low: 35.0, high: 45.0}
    feed_offset_mm: {low: 3.0,  high: 20.0}
    patch_w_mm:     {low: 40.0, high: 60.0}
"""


def _row(adapter: str, params: dict, run_id: str = "r0") -> dict:
    return {"run_id": run_id, "model": "patch_antenna", "adapter": adapter,
            "params_json": json.dumps(params)}


def _synthetic_rows() -> list[dict]:
    # 复刻旧注册表实测形态：hfss 三参数 15 行 + hfss 两参数 8 行 + openEMS 两参数
    # + fake 行（不参与定空间）
    return [
        _row("hfss", {"feed_offset_mm": 9.3, "patch_len_mm": 44.5, "patch_w_mm": 54.6}, "hfss3"),
        _row("hfss", {"feed_offset_mm": 8.7, "patch_len_mm": 44.5}, "hfss2"),
        _row("calibration:openems", {"patch_len_mm": 40.0, "patch_w_mm": 50.0}, "oe"),
        _row("fake", {"feed_offset_mm": 1.0, "patch_len_mm": 1.0, "patch_w_mm": 1.0,
                      "bogus_mm": 9.9}, "fk"),
        _row("mf:fake+hfss", {"another_bogus": 1.0}, "mf"),
    ]


# ---------------------------------------------------------------------------
# LHS 计划
# ---------------------------------------------------------------------------

class TestBuildPlan:
    def test_deterministic_same_seed_same_points(self):
        a = wp34.build_plan(BOUNDS, 36, seed=20260916)
        b = wp34.build_plan(BOUNDS, 36, seed=20260916)
        assert [p["params"] for p in a] == [p["params"] for p in b]

    def test_n_points_and_within_bounds(self):
        plan = wp34.build_plan(BOUNDS, 36, seed=20260916)
        assert len(plan) == 36
        assert [p["index"] for p in plan] == list(range(36))
        for p in plan:
            assert set(p["params"]) == set(BOUNDS)
            for name, (lo, hi) in BOUNDS.items():
                assert lo <= p["params"][name] <= hi
            assert p["status"] == "pending" and p["attempts"] == 0

    def test_different_seed_differs(self):
        a = wp34.build_plan(BOUNDS, 36, seed=1)
        b = wp34.build_plan(BOUNDS, 36, seed=2)
        assert [p["params"] for p in a] != [p["params"] for p in b]

    def test_lhs_stratification_each_axis_covers_all_bins(self):
        # LHS 性质：36 点在每维等分 36 格，每格恰一点
        plan = wp34.build_plan(BOUNDS, 36, seed=20260916)
        for name, (lo, hi) in BOUNDS.items():
            bins = sorted(int((p["params"][name] - lo) / (hi - lo) * 36) for p in plan)
            bins = [min(b, 35) for b in bins]
            assert bins == list(range(36))

    def test_rejects_zero_points(self):
        with pytest.raises(ValueError):
            wp34.build_plan(BOUNDS, 0, seed=1)


# ---------------------------------------------------------------------------
# 参数名对齐
# ---------------------------------------------------------------------------

class TestParamSpaceAlignment:
    def test_hfss_union_ignores_fake_and_openems(self):
        names = wp34.hfss_param_union(_synthetic_rows())
        assert names == {"feed_offset_mm", "patch_len_mm", "patch_w_mm"}

    def test_derive_param_space_aligned(self):
        space = wp34.derive_param_space(_synthetic_rows(), BOUNDS)
        assert space == {k: BOUNDS[k] for k in sorted(BOUNDS)}
        assert list(space) == sorted(BOUNDS)

    def test_recipe_has_extra_param_rejected(self):
        bounds = dict(BOUNDS, extra_mm=(0.0, 1.0))
        with pytest.raises(ValueError, match="仅配方有"):
            wp34.derive_param_space(_synthetic_rows(), bounds)

    def test_registry_has_extra_param_rejected(self):
        rows = [*_synthetic_rows(), _row("hfss", {"gap_mm": 0.3, "patch_len_mm": 40.0}, "x")]
        with pytest.raises(ValueError, match="仅注册表有"):
            wp34.derive_param_space(rows, BOUNDS)

    def test_no_hfss_rows_rejected(self):
        rows = [_row("calibration:openems", {"patch_len_mm": 40.0}), _row("fake", {"patch_len_mm": 1.0})]
        with pytest.raises(ValueError, match="无 patch 族 hfss"):
            wp34.derive_param_space(rows, BOUNDS)

    def test_recipe_bounds_from_template(self):
        assert wp34.recipe_bounds(yaml.safe_load(TEMPLATE_YAML)) == BOUNDS

    def test_recipe_bounds_missing_high_rejected(self):
        data = yaml.safe_load(TEMPLATE_YAML)
        del data["optimization"]["params"]["patch_w_mm"]["high"]
        with pytest.raises(ValueError, match="缺 low/high"):
            wp34.recipe_bounds(data)


# ---------------------------------------------------------------------------
# 配方副本
# ---------------------------------------------------------------------------

class TestRecipeCopy:
    def test_values_replaced_and_rest_intact(self):
        params = {"feed_offset_mm": 7.25, "patch_len_mm": 41.5, "patch_w_mm": 58.0}
        data = yaml.safe_load(wp34.render_recipe_copy(TEMPLATE_YAML, params))
        assert data["params"]["feed_offset_mm"]["value"] == 7.25
        assert data["params"]["patch_len_mm"]["value"] == 41.5
        assert data["params"]["patch_w_mm"]["value"] == 58.0
        assert data["params"]["f0_ghz"] == {"value": 2.4, "unit": "GHz"}
        assert data["params"]["substrate"] == "rogers4350b_h0.508"
        assert data["model"] == "patch_antenna"
        assert data["optimization"]["params"]["patch_len_mm"] == {"low": 35.0, "high": 45.0}
        assert "wp34" in data["notes"]


# ---------------------------------------------------------------------------
# progress 恢复
# ---------------------------------------------------------------------------

def _progress(points: list[dict]) -> dict:
    return {"campaign": wp34.CAMPAIGN_STUDY, "param_space": {k: list(v) for k, v in BOUNDS.items()},
            "seed": 20260916, "n_points": len(points), "points": points}


class TestProgressResume:
    def test_pending_skips_done_and_exhausted(self):
        pts = [
            {"index": 0, "status": "done", "attempts": 1},
            {"index": 1, "status": "failed", "attempts": 3},   # 用尽
            {"index": 2, "status": "failed", "attempts": 1},   # 可重试
            {"index": 3, "status": "pending", "attempts": 0},
            {"index": 4, "status": "done", "attempts": 2},
        ]
        assert wp34.pending_indices(_progress(pts), max_attempts=3) == [2, 3]

    def test_matches_plan_requires_same_space_seed_n(self):
        pts = [{"index": i, "status": "pending", "attempts": 0} for i in range(3)]
        prog = _progress(pts)
        assert wp34.progress_matches_plan(prog, BOUNDS, seed=20260916, n_points=3)
        assert not wp34.progress_matches_plan(prog, BOUNDS, seed=1, n_points=3)
        assert not wp34.progress_matches_plan(prog, BOUNDS, seed=20260916, n_points=4)
        other = dict(BOUNDS, patch_w_mm=(40.0, 61.0))
        assert not wp34.progress_matches_plan(prog, other, seed=20260916, n_points=3)

    def test_summarize(self):
        pts = [
            {"index": 0, "status": "done", "attempts": 1, "run_id": "a", "elapsed_s": 100.0},
            {"index": 1, "status": "done", "attempts": 2, "run_id": "b", "elapsed_s": 300.0},
            {"index": 2, "status": "failed", "attempts": 3, "run_id": "", "elapsed_s": 5.0},
            {"index": 3, "status": "pending", "attempts": 0, "run_id": "", "elapsed_s": None},
        ]
        s = wp34.summarize(_progress(pts))
        assert (s["n_done"], s["n_failed"], s["n_pending"]) == (2, 1, 1)
        assert s["mean_elapsed_s"] == pytest.approx(200.0)
        assert s["done_run_ids"] == ["a", "b"]


# ---------------------------------------------------------------------------
# HFSS 预检
# ---------------------------------------------------------------------------

class TestPreflight:
    def test_unavailable_raises_explicit(self, monkeypatch):
        monkeypatch.setattr(wp34, "_resolve_aedt_install", lambda: None)
        with pytest.raises(RuntimeError, match="HFSS 不可用"):
            wp34.preflight_hfss()

    def test_available_returns_version(self, monkeypatch):
        monkeypatch.setattr(wp34, "_resolve_aedt_install",
                            lambda: {"aedt_version": "2025.1", "path": "E:/x/v251"})
        assert wp34.preflight_hfss()["aedt_version"] == "2025.1"


# ---------------------------------------------------------------------------
# 主循环（monkeypatch 求解入口）
# ---------------------------------------------------------------------------

@pytest.fixture
def campaign_env(tmp_path, monkeypatch):
    """合成模板配方 + 合成注册表 parquet 读取 + HFSS 预检钉住。"""
    template = tmp_path / "patch_tune_light.yaml"
    template.write_text(TEMPLATE_YAML, encoding="utf-8")
    monkeypatch.setattr(wp34, "load_registry_rows", lambda path, model=wp34.MODEL_NAME: _synthetic_rows())
    preflight = lambda: {"aedt_version": "2025.1", "path": "E:/x/v251"}  # noqa: E731
    work = tmp_path / "wp34"
    return {"template": template, "work": work, "preflight": preflight,
            "registry": tmp_path / "unused.parquet"}


class TestRunCampaign:
    def test_plan_only_writes_progress_without_preflight(self, campaign_env):
        def boom():
            raise AssertionError("plan_only 不得预检 HFSS")
        out = wp34.run_campaign(template_recipe=campaign_env["template"],
                                registry_parquet=campaign_env["registry"],
                                work_dir=campaign_env["work"], n_points=5, seed=7,
                                preflight_fn=boom, plan_only=True)
        assert out["ok"] and out["n_pending"] == 5 and out["resumed"] is False
        prog = json.loads((campaign_env["work"] / "progress.json").read_text(encoding="utf-8"))
        assert prog["n_points"] == 5 and prog["seed"] == 7
        assert prog["param_space"] == {k: list(v) for k, v in BOUNDS.items()}

    def test_success_failure_retry_and_resume(self, campaign_env):
        calls: list[tuple[str, dict]] = []
        sleeps: list[float] = []

        def fake_run_once(recipe_path, *, adapter_name, study, seed):
            assert adapter_name == "hfss" and study == wp34.CAMPAIGN_STUDY
            data = yaml.safe_load(Path(recipe_path).read_text(encoding="utf-8"))
            calls.append((Path(recipe_path).name, {k: data["params"][k]["value"] for k in BOUNDS}))
            idx = int(Path(recipe_path).stem[-2:])
            if idx == 1:  # 第 2 点永远失败（solve_failed 形态）
                return {"ok": False, "run_id": f"rid{idx}_{len(calls)}", "errors": ["求解失败: gRPC"]}
            if idx == 2 and sum(1 for c in calls if c[0].endswith("pt02.yaml")) == 1:
                # 第 3 点抛异常一次后成功（#191 随机失败自愈）
                raise ConnectionError("grpc unavailable")
            return {"ok": True, "run_id": f"rid{idx}", "from_cache": False,
                    "metrics": {"s11_db_max_in_band": -12.5}}

        out = wp34.run_campaign(template_recipe=campaign_env["template"],
                                registry_parquet=campaign_env["registry"],
                                work_dir=campaign_env["work"], n_points=3, seed=3,
                                run_once_fn=fake_run_once, preflight_fn=campaign_env["preflight"],
                                max_attempts=3, backoff_s=10.0, sleep_fn=sleeps.append)
        assert out["ok"] and out["ran_indices"] == [0, 1, 2]
        assert (out["n_done"], out["n_failed"], out["n_pending"]) == (2, 1, 0)
        assert out["done_run_ids"] == ["rid0", "rid2"]
        # 重试计数：pt1 三次尝试 + pt2 两次；退避 10/20（pt1）+10（pt2）
        assert sleeps == [10.0, 20.0, 10.0]
        prog = json.loads((campaign_env["work"] / "progress.json").read_text(encoding="utf-8"))
        by = {p["index"]: p for p in prog["points"]}
        assert by[0]["status"] == "done" and by[0]["attempts"] == 1 and by[0]["metrics"] == {"s11_db_max_in_band": -12.5}
        assert by[1]["status"] == "failed" and by[1]["attempts"] == 3 and "gRPC" in by[1]["error"]
        assert by[2]["status"] == "done" and by[2]["attempts"] == 2 and by[2]["run_id"] == "rid2"
        assert all(p["elapsed_s"] is not None for p in prog["points"])
        # 配方副本值 = 计划参数值（float 预计算）
        plan_params = {p["index"]: p["params"] for p in prog["points"]}
        for name, vals in calls:
            assert vals == plan_params[int(name[-7:-5])]
        assert sorted((campaign_env["work"] / "recipes").iterdir()) == [
            campaign_env["work"] / "recipes" / f"recipe_pt0{i}.yaml" for i in range(3)]
        log = (campaign_env["work"] / "campaign.log").read_text(encoding="utf-8")
        assert log.count("status=done") == 2 and log.count("status=failed") == 4
        assert "retry in 10s" in log and "retry in 20s" in log
        assert "campaign start resumed=False" in log and "campaign stop" in log

        # 恢复：done 跳过、pt1 已用尽跳过 → 无待跑点，求解入口不得再被调用
        def must_not_call(*a, **k):
            raise AssertionError("已完成/用尽点不得重跑")
        out2 = wp34.run_campaign(template_recipe=campaign_env["template"],
                                 registry_parquet=campaign_env["registry"],
                                 work_dir=campaign_env["work"], n_points=3, seed=3,
                                 run_once_fn=must_not_call, preflight_fn=campaign_env["preflight"])
        assert out2["resumed"] is True and out2["ran_indices"] == []
        assert (out2["n_done"], out2["n_failed"]) == (2, 1)

    def test_max_points_limits_batch_and_resume_continues(self, campaign_env):
        def ok_run(recipe_path, **kw):
            return {"ok": True, "run_id": Path(recipe_path).stem, "metrics": {}}
        kw = dict(template_recipe=campaign_env["template"], registry_parquet=campaign_env["registry"],
                  work_dir=campaign_env["work"], n_points=4, seed=5, run_once_fn=ok_run,
                  preflight_fn=campaign_env["preflight"])
        first = wp34.run_campaign(max_points=1, **kw)
        assert first["ran_indices"] == [0] and first["n_done"] == 1 and first["n_pending"] == 3
        rest = wp34.run_campaign(**kw)
        assert rest["resumed"] is True and rest["ran_indices"] == [1, 2, 3] and rest["n_done"] == 4

    def test_plan_drift_refuses_mixed_run(self, campaign_env):
        kw = dict(template_recipe=campaign_env["template"], registry_parquet=campaign_env["registry"],
                  work_dir=campaign_env["work"], preflight_fn=campaign_env["preflight"], plan_only=True)
        wp34.run_campaign(n_points=3, seed=3, **kw)
        with pytest.raises(RuntimeError, match="口径不一致"):
            wp34.run_campaign(n_points=3, seed=4, **kw)

    def test_hfss_unavailable_aborts_before_any_point(self, campaign_env, monkeypatch):
        monkeypatch.setattr(wp34, "_resolve_aedt_install", lambda: None)

        def must_not_call(*a, **k):
            raise AssertionError("预检失败不得调求解")
        with pytest.raises(RuntimeError, match="HFSS 不可用"):
            wp34.run_campaign(template_recipe=campaign_env["template"],
                              registry_parquet=campaign_env["registry"],
                              work_dir=campaign_env["work"], n_points=2, seed=1,
                              run_once_fn=must_not_call)


# ---------------------------------------------------------------------------
# ingest 收尾
# ---------------------------------------------------------------------------

class TestIngest:
    def test_union_of_source_and_campaign_runs(self, tmp_path):
        prog = _progress([
            {"index": 0, "status": "done", "attempts": 1, "run_id": "new1", "elapsed_s": 1.0},
            {"index": 1, "status": "failed", "attempts": 3, "run_id": "bad", "elapsed_s": 1.0},
            {"index": 2, "status": "done", "attempts": 1, "run_id": "old2", "elapsed_s": 1.0},
        ])
        progress_path = tmp_path / "progress.json"
        progress_path.write_text(json.dumps(prog), encoding="utf-8")
        manifest = tmp_path / "dataset_manifest.yaml"
        manifest.write_text(yaml.safe_dump({"name": "src", "source_runs": [
            {"run_id": "old1", "n_points": 3}, {"run_id": "old2", "n_points": 5}]}), encoding="utf-8")
        seen: dict = {}

        def fake_mat(run_ids, *, name, fmt):
            seen["run_ids"], seen["name"], seen["fmt"] = run_ids, name, fmt
            return {"ok": True, "name": name, "n_points": 9, "n_rows": 9, "skipped_runs": [],
                    "missing_runs": [], "unhealthy_runs": [], "parquet": "p", "manifest": "m"}

        def fake_ready(name):
            seen["ready_name"] = name
            return {"ok": True, "unlocked": False, "per_model": {"patch_antenna": {"n_gt": 70}}}

        out = wp34.ingest(progress_path=progress_path, source_manifest=manifest,
                          new_name="wp34_registry_test", readiness_path=tmp_path / "readiness.json",
                          materialize_fn=fake_mat, readiness_fn=fake_ready)
        assert seen["run_ids"] == ["new1", "old1", "old2"]  # 去重排序，failed run 不入
        assert seen["name"] == "wp34_registry_test" and seen["fmt"] == "parquet"
        assert seen["ready_name"] == "wp34_registry_test"
        assert out["n_source_runs"] == 2 and out["n_campaign_runs"] == 2
        assert out["readiness"]["per_model"]["patch_antenna"]["n_gt"] == 70
        written = json.loads((tmp_path / "readiness.json").read_text(encoding="utf-8"))
        assert written["new_registry"] == "wp34_registry_test"
        assert written["materialize"]["n_points"] == 9

    def test_materialize_failure_propagates_not_readiness(self, tmp_path):
        prog = _progress([{"index": 0, "status": "done", "attempts": 1, "run_id": "n", "elapsed_s": 1.0}])
        (tmp_path / "progress.json").write_text(json.dumps(prog), encoding="utf-8")
        (tmp_path / "m.yaml").write_text(yaml.safe_dump({"source_runs": [{"run_id": "o"}]}), encoding="utf-8")

        def never(name):
            raise AssertionError("物化失败不得跑 readiness")
        out = wp34.ingest(progress_path=tmp_path / "progress.json", source_manifest=tmp_path / "m.yaml",
                          new_name="x", readiness_path=tmp_path / "r.json",
                          materialize_fn=lambda *a, **k: {"ok": False, "errors": ["缺 pyarrow"]},
                          readiness_fn=never)
        assert out["readiness"] == {"ok": False, "errors": ["缺 pyarrow"]}

    def test_missing_progress_explicit(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="先跑战役"):
            wp34.ingest(progress_path=tmp_path / "nope.json", source_manifest=tmp_path / "m.yaml",
                        new_name="x", readiness_path=tmp_path / "r.json",
                        materialize_fn=lambda *a, **k: {}, readiness_fn=lambda n: {})
