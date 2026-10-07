"""W6-A 席位定向门——SN 平台余件 13（SN-3/6/7/8/10/11/13/14/15/16/17/18/19）。

全部零网络（#139：LLM/外部通道一律 monkeypatch 钉住）；真机通道零触碰；
chdir 隔离（#144：优化循环类测试不污染真实 runs）。逐件对应 SN 席报告
§二行级规格（runs/research_seats_20261004/sn_platform_deepen/REPORT.md）。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.cli.main import app as cli_app

runner = CliRunner()


def _invoke(args: list[str]):
    return runner.invoke(cli_app, args)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_json(path: Path, data: dict) -> Path:
    return _write(path, json.dumps(data, ensure_ascii=False, default=str))


def _mline_recipe(path: Path) -> str:
    """最小合法 mline 配方（validate/propose/tolerance 计划面共用）。"""
    recipe = {
        "model": "mline",
        "params": {"w_mm": {"value": 0.7}, "L_mm": 20.0, "f0_ghz": 10.0},
        "setup": {"freq_range_ghz": [8.0, 12.0], "points": 21},
        "objectives": [
            {"metric": "s11_db", "band": [9.5, 10.5], "op": "max_below",
             "value": -15},
        ],
    }
    _write(path, yaml.safe_dump(recipe, allow_unicode=True))
    return str(path)


def _fab_metric_run(runs_root: Path, run_id: str, *, cost: float,
                    metrics: dict, model: str = "mline",
                    timestamp: str = "2026-10-05 10:00:00",
                    snapshot_params: dict | None = None) -> Path:
    """fabricated run：meta.json（含 metrics，runs_diff 读取优先面）+
    results/metrics.json（+可选配方快照）。"""
    run_dir = runs_root / run_id
    _write_json(run_dir / "meta.json", {
        "run_id": run_id, "model": model, "adapter": "fake",
        "status": "done", "timestamp": timestamp, "seed": 42,
        "metrics": dict(metrics),
    })
    _write_json(run_dir / "results" / "metrics.json", {
        "run_id": run_id, "model": model,
        "params": {}, "metrics": metrics, "cost": cost,
    })
    if snapshot_params is not None:
        _write(run_dir / "recipe.snapshot.yaml", yaml.safe_dump({
            "model": model, "params": snapshot_params,
        }, allow_unicode=True))
    return run_dir


# ---------------------------------------------------------------------------
# SN-10：progress_pct 实化（job registry 阶段进度 + poll 透传）
# ---------------------------------------------------------------------------

class TestSn10Progress:
    def test_registry_set_progress_clamp_and_monotone(self):
        from rfauto.service.job_registry import JobRegistry

        reg = JobRegistry()
        reg.create("job_p1")
        assert reg.set_progress("job_p1", 30.0, "solve") is True
        assert reg.set_progress("job_p1", 999.0) is True  # 钳位 100
        snap = reg.get("job_p1")
        assert snap["progress_pct"] == 100.0
        assert snap["stage"] == "solve"
        # 单调不回退
        assert reg.set_progress("job_p1", 5.0) is True
        assert reg.get("job_p1")["progress_pct"] == 100.0
        # pct 非法
        assert reg.set_progress("job_p1", "nan") is False

    def test_registry_set_progress_unknown_and_terminal(self):
        from rfauto.service.job_registry import JobRegistry

        reg = JobRegistry()
        assert reg.set_progress("job_none", 10.0) is False
        reg.create("job_p2")
        reg.finish("job_p2", run_id="r", result={"ok": True})
        assert reg.set_progress("job_p2", 50.0) is False  # 终态即封账

    def test_run_once_async_carries_progress(self, tmp_path, monkeypatch):
        """run_once_async 阶段回调直写注册表；poll_job 透传真实 pct/stage。"""
        monkeypatch.chdir(tmp_path)
        from rfauto.service import api as api_mod
        from rfauto.service.api import poll_job, run_once_async
        from rfauto.service.job_registry import reset_job_registry

        reset_job_registry()

        def fake_run_once(recipe_path, *, adapter_name="fake",
                          progress_cb=None, **kw):
            assert progress_cb is not None
            progress_cb(5.0, "prepared")
            progress_cb(60.0, "solve")
            progress_cb(100.0, "done")
            return {"ok": True, "run_id": "r_async", "metrics": {"a": 1.0},
                    "cost": 0.5}

        monkeypatch.setattr(api_mod, "run_once", fake_run_once)
        out = run_once_async("recipe.yaml", adapter_name="fake")
        assert out["ok"] and out["job_id"].startswith("job_")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            snap = poll_job(out["job_id"])
            if snap.get("state") in ("done", "failed"):
                break
            time.sleep(0.02)
        assert snap["state"] == "done", snap
        assert snap["progress_pct"] == 100.0
        assert snap["stage"] == "done"

    def test_poll_job_binary_fallback_unchanged(self):
        """无进度信息（注册表冷启动路径）保持 0/100 二值缺省，不臆造。"""
        from rfauto.service.api import poll_job
        from rfauto.service.job_registry import get_job_registry, reset_job_registry

        reset_job_registry()
        reg = get_job_registry()
        reg.create("job_cold")
        snap = poll_job("job_cold")
        assert snap["ok"] is True and snap["progress_pct"] == 0.0
        assert snap["stage"] == ""


# ---------------------------------------------------------------------------
# SN-11：sweep checkpoint + resume + 进度（SN-18 sweep --dry-run 同类）
# ---------------------------------------------------------------------------

_SWEEP_RECIPE = {
    "model": "wilkinson_power_divider",
    "params": {
        "arm_len_mm": {"value": 20.5},
        "series_w_mm": {"value": 0.33},
        "shunt_w_mm": {"value": 1.10},
    },
    "setup": {"freq_range_ghz": [1.5, 3.5], "points": 21},
    "objectives": [
        {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
    ],
    "optimization": {
        "params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
        },
    },
}


@pytest.fixture
def sweep_recipe(tmp_path):
    path = tmp_path / "recipe.yaml"
    _write(path, yaml.safe_dump(_SWEEP_RECIPE, allow_unicode=True))
    return str(path)


class TestSn11SweepResume:
    def test_checkpoint_and_progress(self, sweep_recipe, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.sweep_backend import run_sweep

        ticks: list[tuple[int, int, str]] = []
        result = run_sweep(
            sweep_recipe, adapter_name="fake", method="grid",
            coarse_samples=4, max_combos=16,
            adapter_kwargs={"n_ports": 3},
            progress_cb=lambda d, t, tag: ticks.append((d, t, tag)),
        )
        assert result["ok"]
        assert result["resumed_combos"] == 0
        run_dir = tmp_path / "runs" / result["run_id"] / "sweep_results"
        lines = [ln for ln in
                 (run_dir / "checkpoint.jsonl").read_text(encoding="utf-8").splitlines()
                 if ln.strip()]
        assert len(lines) == result["total_combos"] > 0
        first = json.loads(lines[0])
        assert {"params", "cost", "metrics"} <= set(first)
        # 逐组合进度：末 tick 达到本 phase 总数
        assert ticks and ticks[-1][0] == ticks[-1][1]

    def test_resume_skips_done_and_carries_results(
            self, sweep_recipe, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.sweep_backend import run_sweep

        first = run_sweep(sweep_recipe, adapter_name="fake", method="grid",
                          coarse_samples=4, max_combos=16,
                          adapter_kwargs={"n_ports": 3})
        assert first["ok"]
        calls: list[int] = []

        import rfauto.optimization.sweep_backend as sb

        real_run_combos = sb._run_combos

        def counting_run_combos(*a, **kw):
            calls.append(1)
            return real_run_combos(*a, **kw)

        monkeypatch.setattr(sb, "_run_combos", counting_run_combos)
        second = run_sweep(sweep_recipe, adapter_name="fake", method="grid",
                           coarse_samples=4, max_combos=16,
                           adapter_kwargs={"n_ports": 3},
                           resume_run_id=first["run_id"])
        assert second["ok"]
        # 命中组合零重跑：结果全量携带自 checkpoint
        assert second["resumed_combos"] == first["total_combos"]
        assert second["total_combos"] == first["total_combos"]
        assert second["best"]["params"] == first["best"]["params"]
        # 新 run checkpoint 自包含全部历史（可再续）
        cp = (tmp_path / "runs" / second["run_id"] / "sweep_results"
              / "checkpoint.jsonl")
        n_lines = len([ln for ln in cp.read_text(encoding="utf-8").splitlines()
                       if ln.strip()])
        assert n_lines == first["total_combos"]

    def test_resume_missing_source_fails(self, sweep_recipe, tmp_path,
                                         monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.sweep_backend import run_sweep

        result = run_sweep(sweep_recipe, adapter_name="fake",
                           resume_run_id="no_such_run")
        assert not result["ok"]
        assert any("checkpoint" in e for e in result["errors"])

    def test_plan_sweep_zero_write(self, sweep_recipe, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.sweep_backend import plan_sweep

        result = plan_sweep(sweep_recipe, method="grid", coarse_samples=2)
        assert result["ok"] and result["mode"] == "dry-run"
        assert result["phase1_combos"] == 4  # grid 2 维 × 每维 2 点
        assert result["phase2"] == 0
        assert not (tmp_path / "runs").exists()  # 零写盘


# ---------------------------------------------------------------------------
# SN-18：dry-run 扩面（tolerance / db migrate / datasets materialize）
# ---------------------------------------------------------------------------

class TestSn18DryRun:
    def test_plan_tolerance(self, tmp_path):
        from rfauto.optimization.optimizer import plan_tolerance

        recipe = {
            "model": "mline",
            "params": {"w_mm": {"value": 0.7}, "L_mm": 20.0},
            "objectives": [{"metric": "s11_db", "band": [9.5, 10.5],
                            "op": "max_below", "value": -15}],
            "tolerance": {"tolerances": {"w_mm": 0.05}},
        }
        path = tmp_path / "tol.yaml"
        _write(path, yaml.safe_dump(recipe, allow_unicode=True))
        plan = plan_tolerance(str(path))
        assert plan["ok"] and plan["mode"] == "dry-run"
        assert plan["tolerances"] == {"w_mm": 0.05}
        # 公差参数不在 params → 如实报错
        bad = dict(recipe)
        bad["tolerance"] = {"tolerances": {"ghost_mm": 0.1}}
        path_bad = tmp_path / "tol_bad.yaml"
        _write(path_bad, yaml.safe_dump(bad, allow_unicode=True))
        out = plan_tolerance(str(path_bad))
        assert not out["ok"] and any("ghost_mm" in e for e in out["errors"])

    def test_db_migrate_dry_run(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.infra.db import LATEST_SCHEMA_VERSION
        from rfauto.service.db_service import db_init, db_migrate

        # 库不存在：计划面如实 not_exists 且零建库
        target = tmp_path / "registry.sqlite"
        plan = db_migrate(str(target), dry_run=True)
        assert plan["ok"] and plan["exists"] is False
        assert plan["target_schema_version"] == int(LATEST_SCHEMA_VERSION)
        assert not target.exists()
        # 真建库后再 dry-run：幂等 would_apply=0
        db_init(str(target))
        plan2 = db_migrate(str(target), dry_run=True)
        assert plan2["exists"] is True and plan2["would_apply"] == 0

    def test_materialize_dry_run_no_write(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.dataset_service import materialize_dataset

        _fab_metric_run(tmp_path / "runs", "pt_dry", cost=0.1,
                        metrics={"s11_db": -10.0})
        plan = materialize_dataset(["pt_dry"], name="dryset", dry_run=True)
        assert plan["ok"] and plan["mode"] == "dry-run"
        assert plan["would_materialize"] == ["pt_dry"]
        assert plan["health_gate_note"].startswith("not_evaluated")
        assert not (tmp_path / "runs" / "datasets").exists()


# ---------------------------------------------------------------------------
# SN-13：datasets query order/分页/导出/total_rows
# ---------------------------------------------------------------------------

@pytest.fixture
def tiny_dataset(tmp_path, monkeypatch):
    """裸目录形态数据集（无 manifest 也可查，test_rest_api 惯例）。"""
    monkeypatch.chdir(tmp_path)
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = {
        "cost": [0.5, 0.1, 0.9, 0.3, 0.7],
        "model": ["mline"] * 5,
        "seed": [1, 2, 3, 4, 5],
    }
    ddir = tmp_path / "runs" / "datasets" / "tiny"
    ddir.mkdir(parents=True)
    pq.write_table(pa.table(rows), str(ddir / "points.parquet"))
    return ddir


class TestSn13DatasetsQuery:
    def test_order_offset_total(self, tiny_dataset):
        from rfauto.service.dataset_service import query_dataset

        r = query_dataset("tiny", limit=2, order_by="cost", order="asc",
                          offset=1)
        assert r["ok"], r.get("errors")
        assert [row["cost"] for row in r["rows"]] == [0.3, 0.5]
        assert r["total_rows"] == 5  # 过滤后 LIMIT/OFFSET 前总数（#369 治理）
        assert r["offset"] == 1 and r["order_by"] == "cost"
        # 信封 format 键保持存储格式语义
        assert r["format"] == "parquet"

    def test_csv_format(self, tiny_dataset):
        from rfauto.service.dataset_service import query_dataset

        r = query_dataset("tiny", columns=["cost"], limit=2,
                          order_by="cost", order="desc", out_fmt="csv")
        assert r["ok"]
        lines = r["csv"].strip().splitlines()
        assert lines[0] == "cost"
        assert [float(x) for x in lines[1:]] == [0.9, 0.7]
        assert r["n_rows"] == 2  # rows 仍带（双消费）

    def test_invalid_params(self, tiny_dataset):
        from rfauto.service.dataset_service import query_dataset

        assert not query_dataset("tiny", order_by="cost; drop")["ok"]
        assert not query_dataset("tiny", order="sideways")["ok"]
        assert not query_dataset("tiny", offset=-1)["ok"]
        assert not query_dataset("tiny", out_fmt="xlsx")["ok"]

    def test_cli_query_flags(self, tiny_dataset):
        r = _invoke(["datasets", "query", "tiny", "--order-by", "cost",
                     "--order", "asc", "--limit", "2", "--offset", "1",
                     "--json"])
        assert r.exit_code == 0, r.output[:400]
        payload = json.loads(r.output)
        assert payload["ok"] and payload["total_rows"] == 5
        r_csv = _invoke(["datasets", "query", "tiny", "--format", "csv",
                         "--limit", "1"])
        assert r_csv.exit_code == 0
        assert "cost" in r_csv.output


# ---------------------------------------------------------------------------
# SN-14：lake query order-by
# ---------------------------------------------------------------------------

@pytest.fixture
def lake_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from rfauto.service.lake_service import build_runs_index

    for name, ts in (("b_run", "2026-09-02T10:00:00+00:00"),
                     ("a_run", "2026-09-01T10:00:00+00:00")):
        _write_json(tmp_path / "runs" / name / "meta.json", {
            "run_id": name, "model": "mline", "adapter": "fake",
            "status": "done", "timestamp": ts, "seed": 1,
        })
    db = tmp_path / "lake.duckdb"
    r = build_runs_index(tmp_path / "runs", db_path=db)
    assert r["ok"], r.get("errors")
    return db


class TestSn14LakeOrderBy:
    def test_order_by_created_ts(self, lake_env):
        from rfauto.service.lake_service import query_runs_index

        asc = query_runs_index(lake_env, order_by="created_ts", order="asc")
        desc = query_runs_index(lake_env, order_by="created_ts", order="desc")
        assert asc["ok"] and desc["ok"]
        a_names = [row["run_id"] for row in asc["rows"]]
        d_names = [row["run_id"] for row in desc["rows"]]
        assert a_names == list(reversed(d_names))
        # 缺省（不传 order_by）保持 path 排序零行为变化
        dflt = query_runs_index(lake_env)
        assert [row["run_id"] for row in dflt["rows"]] == sorted(d_names)

    def test_invalid_order_by(self, lake_env):
        from rfauto.service.lake_service import query_runs_index

        out = query_runs_index(lake_env, order_by="secret_col")
        assert not out["ok"] and any("order_by" in e for e in out["errors"])

    def test_cli_order_flag(self, lake_env):
        r = _invoke(["lake", "query", "--db", str(lake_env),
                     "--order-by", "created_ts", "--json"])
        assert r.exit_code == 0, r.output[:400]
        payload = json.loads(r.output)
        assert payload["ok"] and payload["n_rows"] == 2


# ---------------------------------------------------------------------------
# SN-15：recipe diff / runs diff CLI 对等（service 唯一事实源）
# ---------------------------------------------------------------------------

class TestSn15Diff:
    def test_runs_diff_service_and_ui_shim(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.runs_diff_service import runs_diff
        from rfauto.ui.runs_diff import runs_diff as ui_runs_diff

        assert ui_runs_diff is runs_diff  # 薄 re-export（#116 零副本）
        _fab_metric_run(tmp_path / "runs", "da", cost=0.1,
                        metrics={"s11_db_max_in_band": -12.0},
                        snapshot_params={"w_mm": {"value": 0.7}})
        _fab_metric_run(tmp_path / "runs", "db", cost=0.2,
                        metrics={"s11_db_max_in_band": -18.0},
                        snapshot_params={"w_mm": {"value": 0.9}})
        r = runs_diff("da", "db")
        assert r["ok"], r.get("errors")
        changed = [e for e in r["params_recursive_diff"]
                   if e["path"].endswith("w_mm.value")]
        assert len(changed) == 1 and changed[0]["kind"] == "changed"
        assert r["metrics_delta"]["s11_db_max_in_band"]["delta"] == \
            pytest.approx(-6.0)
        assert any("带内 S11" in h for h in r["verdict_hints"])
        # 非法/缺失 run_id 如实报错
        assert not runs_diff("../evil", "da")["ok"]
        assert not runs_diff("ghost", "da")["ok"]

    def test_cli_runs_diff(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _fab_metric_run(tmp_path / "runs", "ca", cost=0.1,
                        metrics={"s11_db": -12.0},
                        snapshot_params={"w_mm": {"value": 0.7}})
        _fab_metric_run(tmp_path / "runs", "cb", cost=0.2,
                        metrics={"s11_db": -18.0},
                        snapshot_params={"w_mm": {"value": 0.7}})
        r = _invoke(["runs", "diff", "ca", "cb", "--json"])
        assert r.exit_code == 0, r.output[:400]
        assert json.loads(r.output)["ok"] is True

    def test_recipe_diff_files_and_cli(self, tmp_path):
        from rfauto.service.design_diff_service import design_version_diff_from_files

        a = _write(tmp_path / "a.yaml",
                   yaml.safe_dump({"params": {"w_mm": 0.7, "L_mm": 20.0}}))
        b = _write(tmp_path / "b.yaml",
                   yaml.safe_dump({"params": {"w_mm": 0.9, "L_mm": 20.0}}))
        r = design_version_diff_from_files(a, b)
        assert r["ok"] and r["verdict"] == "changed"
        kinds = {c["path"]: c["kind"] for c in r["changes"]}
        assert kinds.get("params.w_mm") == "numeric"
        # CLI：rich 路径 verdict=changed 退出码 0；structural 退出码 1
        r_ok = _invoke(["recipe", "diff", str(a), str(b)])
        assert r_ok.exit_code == 0
        c = _write(tmp_path / "c.yaml",
                   yaml.safe_dump({"params": {"w_mm": 0.7, "new_key": 1}}))
        r_st = _invoke(["recipe", "diff", str(a), str(c)])
        assert r_st.exit_code == 1  # 结构性差异门禁语义


# ---------------------------------------------------------------------------
# SN-3：design kickoff/close 两叶（零 LLM 缺省路径）
# ---------------------------------------------------------------------------

class TestSn3DesignChain:
    def test_kickoff_zero_llm(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.level2_design import design_kickoff

        r = design_kickoff("设计一个 2.4GHz Wilkinson 功分器，50 欧")
        assert r["ok"], r.get("errors")
        assert r["family"] == "wilkinson"
        assert r["bounds"] and r["objectives"]
        draft = yaml.safe_load(
            Path(r["recipe_path"]).read_text(encoding="utf-8"))
        assert draft["model"] == "wilkinson"
        for _k, spec in draft["params"].items():
            assert "value" in spec and "bounds" in spec  # kickoff 搜索域入草稿
        record = json.loads(
            Path(r["record_path"]).read_text(encoding="utf-8"))
        assert record["family"] == "wilkinson"

    def test_kickoff_unroutable_prompt(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.level2_design import design_kickoff

        r = design_kickoff("量子隧穿咖啡机")
        assert not r["ok"]

    def test_close_on_record(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.level2_design import design_close, design_kickoff

        k = design_kickoff("设计一个 2.4GHz Wilkinson 功分器，50 欧")
        assert k["ok"]
        c = design_close(k["record_path"])
        assert c["ok"] is not None  # 三步链信封（单步失败不拖垮，逐步留账）
        for step in ("certify", "anchor_writeback", "replan"):
            assert step in c
        assert not design_close(tmp_path / "ghost.json")["ok"]

    def test_cli_kickoff_and_close(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        r = _invoke(["design", "kickoff",
                     "设计一个 10GHz 微带线，50 欧", "--json"])
        assert r.exit_code == 0, r.output[:600]
        payload = json.loads(r.output)
        assert payload["ok"] and payload["family"] == "mline"
        r_close = _invoke(["design", "close", payload["record_path"], "--json"])
        assert r_close.exit_code in (0, 1)  # 闭环逐步留账；信封必有
        c = json.loads(r_close.output)
        assert c["ok"] is not None and "certify" in c


# ---------------------------------------------------------------------------
# SN-6：runs health 批量化
# ---------------------------------------------------------------------------

class TestSn6HealthBatch:
    def test_batch_filters_and_counts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.health_service import health_check_batch

        root = tmp_path / "runs"
        _write_json(root / "m1" / "meta.json", {
            "run_id": "m1", "model": "mline", "adapter": "fake",
            "status": "done", "timestamp": "2026-10-01 10:00:00"})
        _write_json(root / "m2" / "meta.json", {
            "run_id": "m2", "model": "patch_antenna", "adapter": "fake",
            "status": "done", "timestamp": "2026-10-04 10:00:00"})
        (root / "nometa").mkdir(parents=True)  # 无 meta 不入扫描域
        r = health_check_batch(runs_dir=str(root))
        assert r["ok"]
        assert r["n_checked"] == 2
        assert set(r["verdicts"]) == {"m1", "m2"}
        # suspect-by-absence 放行留档（不拦）
        assert r["unhealthy"] == [] and len(r["suspect"]) == 2
        flt = health_check_batch(runs_dir=str(root), template="mline")
        assert flt["n_checked"] == 1 and "m1" in flt["verdicts"]
        flt2 = health_check_batch(runs_dir=str(root), since="2026-10-03")
        assert flt2["n_checked"] == 1 and "m2" in flt2["verdicts"]
        bad = health_check_batch(runs_dir=str(root), since="not-a-date")
        assert not bad["ok"] or bad["errors"]

    def test_batch_nonexistent_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.health_service import health_check_batch

        r = health_check_batch(runs_dir=str(tmp_path / "ghost"))
        assert r["ok"] and r["n_checked"] == 0 and r["errors"]

    def test_cli_batch_exit_semantics(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        _write_json(root / "s1" / "meta.json", {
            "run_id": "s1", "model": "mline", "adapter": "fake",
            "status": "done", "timestamp": "2026-10-01 10:00:00"})
        r = _invoke(["runs", "health", "--all", "--runs-root", str(root),
                     "--json"])
        # suspect 不拦（与数据集物化 health_gate 同口径）→ 退出码 0
        assert r.exit_code == 0, r.output[:400]
        payload = json.loads(r.output)
        assert payload["ok"] and payload["n_checked"] == 1


# ---------------------------------------------------------------------------
# SN-7：N-way runs compare
# ---------------------------------------------------------------------------

class TestSn7NwayCompare:
    def test_nway_service(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.batch_ops_service import compare_runs_nway

        root = tmp_path / "runs"
        for rid, s11 in (("r1", -10.0), ("r2", -20.0), ("r3", -30.0)):
            _fab_metric_run(root, rid, cost=abs(s11) / 100,
                            metrics={"s11_db": s11, "tag": "x"})
        r = compare_runs_nway(["r1", "r2", "r3"])
        assert r["ok"], r.get("errors")
        assert r["n_runs"] == 3 and len(r["pairwise"]) == 3
        pm = {row["metric"]: row for row in r["per_metric"]}
        assert pm["s11_db"]["spread"] == pytest.approx(20.0)
        assert pm["tag"]["spread"] is None  # 非数值键不臆造
        # 经典双参语义核对：pairwise[0] == compare_runs(r1, r2) delta
        from rfauto.service.api import compare_runs

        classic = compare_runs("r1", "r2")
        pw = r["pairwise"][0]
        assert pw["delta"]["s11_db"]["delta"] == \
            classic["data"]["metrics"]["s11_db"]["delta"]

    def test_nway_errors(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.batch_ops_service import compare_runs_nway

        assert not compare_runs_nway(["only_one"])["ok"]
        assert not compare_runs_nway(["a", "a"])["ok"]
        _fab_metric_run(tmp_path / "runs", "a", cost=0.1, metrics={})
        out = compare_runs_nway(["a", "ghost"])
        assert not out["ok"] and any("ghost" in e for e in out["errors"])

    def test_cli_nway_and_classic(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        for rid, s11 in (("c1", -10.0), ("c2", -20.0), ("c3", -30.0)):
            _fab_metric_run(root, rid, cost=0.1, metrics={"s11_db": s11})
        r2 = _invoke(["runs", "compare", "c1", "c2", "--json"])
        assert r2.exit_code == 0
        assert json.loads(r2.output)["ok"]  # 经典 2 参路径不变
        r3 = _invoke(["runs", "compare", "c1", "c2", "c3", "--json"])
        assert r3.exit_code == 0, r3.output[:400]
        payload = json.loads(r3.output)
        assert payload["ok"] and payload["n_runs"] == 3


# ---------------------------------------------------------------------------
# SN-8：批量 validate/report
# ---------------------------------------------------------------------------

class TestSn8BatchValidateReport:
    def test_validate_batch(self, tmp_path):
        from rfauto.service.batch_ops_service import validate_recipes_batch

        good = _mline_recipe(tmp_path / "good.yaml")
        _write(tmp_path / "bad.yaml", "model: ghost_model\nparams: {}\n")
        r = validate_recipes_batch(str(tmp_path))
        assert r["ok"] and r["n_files"] == 2
        assert r["ok_all"] is False
        assert Path(good).name in " ".join(r["passed"])
        assert r["failed"] and any("ghost_model" in e
                                   for f in r["results"] for e in f["errors"])
        # 目录无 YAML 如实报错
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        assert not validate_recipes_batch(str(empty))["ok"]

    def test_report_batch_and_discover(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.batch_ops_service import discover_run_ids, report_runs_batch

        root = tmp_path / "runs"
        _fab_metric_run(root, "rr1", cost=0.1, metrics={"s11_db": -10.0})
        _fab_metric_run(root, "rr2", cost=0.3, metrics={"s11_db": -20.0})
        disc = discover_run_ids(str(root))
        assert disc["ok"] and set(disc["run_ids"]) == {"rr1", "rr2"}
        r = report_runs_batch(["rr1", "rr2", "ghost"],
                              out_dir=str(tmp_path / "batch_out"))
        assert r["ok"] and r["n_ok"] == 2 and r["n_failed"] == 1
        index = Path(r["index"]).read_text(encoding="utf-8")
        assert "rr1" in index and "ghost" in index
        for rep in r["reports"]:
            assert Path(rep).exists()

    def test_cli_validate_dir(self, tmp_path):
        _mline_recipe(tmp_path / "g.yaml")
        r = _invoke(["validate", "--dir", str(tmp_path)])
        assert r.exit_code == 0, r.output[:400]
        r_bad = tmp_path / "bad.yaml"
        _write(r_bad, "params: {}\n")
        r2 = _invoke(["validate", "--dir", str(tmp_path)])
        assert r2.exit_code == 1  # 任一失败 → 1


# ---------------------------------------------------------------------------
# SN-16：MCP tune/sweep 主入口
# ---------------------------------------------------------------------------

class TestSn16McpEntry:
    def test_registered(self):
        import asyncio

        from rfauto.mcp_server import mcp

        names = {t.name for t in asyncio.run(mcp.list_tools())}
        assert {"start_tune", "run_sweep"} <= names

    def test_start_tune_wiring(self, tmp_path, monkeypatch):
        from rfauto.mcp_tools.optim import start_tune

        captured: dict = {}

        def fake_async(recipe_path, **kw):
            captured.update(kw)
            captured["recipe_path"] = recipe_path
            return {"ok": True, "job_id": "job_x", "state": "running"}

        import rfauto.service.api as api_mod

        monkeypatch.setattr(api_mod, "start_tune_async", fake_async)
        out = start_tune("r.yaml", adapter="fake", max_trials=7,
                         study_name="s1", sampler="tpe", seed=3)
        assert out["ok"] and out["job_id"] == "job_x"
        assert captured["max_trials"] == 7 and captured["seed"] == 3
        assert captured["adapter_name"] == "fake"

    def test_run_sweep_wiring(self, monkeypatch):
        import rfauto.optimization.sweep_backend as sb
        from rfauto.mcp_tools.optim import run_sweep

        captured: dict = {}

        def fake_run_sweep(recipe_path, **kw):
            captured.update(kw)
            return {"ok": True, "run_id": "r", "total_combos": 0}

        monkeypatch.setattr(sb, "run_sweep", fake_run_sweep)
        out = run_sweep("r.yaml", method="grid", max_combos=9,
                        resume_run_id="prev")
        assert out["ok"]
        assert captured["method"] == "grid" and captured["max_combos"] == 9
        assert captured["resume_run_id"] == "prev"


# ---------------------------------------------------------------------------
# SN-17：沙箱三件套 CLI
# ---------------------------------------------------------------------------

class TestSn17SandboxCli:
    def test_list_diff_promote_flow(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.agent_sandbox import RecipeSandbox

        recipe = _mline_recipe(tmp_path / "recipes" / "a.yaml")
        sb = RecipeSandbox()
        sb.stage(recipe)
        # list：草稿反查来源配方
        r_list = _invoke(["sandbox", "list", "--json"])
        assert r_list.exit_code == 0, r_list.output[:400]
        items = json.loads(r_list.output)["drafts"]
        assert len(items) == 1 and items[0]["recipe"].endswith("a.yaml")
        assert items[0]["params_changed"] == {}
        # diff：无差异→有差异
        r_diff0 = _invoke(["sandbox", "diff", recipe])
        assert r_diff0.exit_code == 0
        sb.apply_param_edits(recipe, {"w_mm": 0.8})
        r_diff = _invoke(["sandbox", "diff", recipe, "--json"])
        payload = json.loads(r_diff.output)
        assert payload["ok"] and "w_mm" in payload["params_changed"]
        # promote：差异送三层 Gate（fake 通道，离线）→ 提案 token
        r_promote = _invoke(["sandbox", "promote", recipe, "--json"])
        assert r_promote.exit_code == 0, r_promote.output[:600]
        promo = json.loads(r_promote.output)
        assert promo["ok"] is True
        assert promo.get("params_proposed", {}).get("w_mm") == 0.8

    def test_promote_no_draft_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        recipe = _mline_recipe(tmp_path / "recipes" / "none.yaml")
        r = _invoke(["sandbox", "promote", recipe])
        assert r.exit_code == 1  # 尚无草稿 → 如实失败


# ---------------------------------------------------------------------------
# SN-19：--watch 泛化（jobs watch / runs watch）
# ---------------------------------------------------------------------------

class TestSn19Watch:
    def test_watch_terminal_done(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.cli.domains._core import _watch_poll
        from rfauto.service.api import poll_job
        from rfauto.service.job_registry import get_job_registry, reset_job_registry

        reset_job_registry()
        reg = get_job_registry()
        reg.create("job_w1")
        reg.finish("job_w1", run_id="r1", result={"ok": True})
        assert poll_job("job_w1")["state"] == "done"
        _watch_poll("job_w1", interval_s=0.01, timeout_s=5.0,
                    json_output=False, label="job")  # 不抛即过

    def test_watch_failed_exits_1(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import typer

        from rfauto.cli.domains._core import _watch_poll
        from rfauto.service.job_registry import get_job_registry, reset_job_registry

        reset_job_registry()
        reg = get_job_registry()
        reg.create("job_w2")
        reg.fail("job_w2", error="boom")
        with pytest.raises(typer.Exit) as ei:
            _watch_poll("job_w2", interval_s=0.01, timeout_s=5.0,
                        json_output=True, label="job")
        assert ei.value.exit_code == 1

    def test_watch_timeout_exits_1(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import typer

        from rfauto.cli.domains._core import _watch_poll
        from rfauto.service.job_registry import reset_job_registry

        reset_job_registry()
        with pytest.raises(typer.Exit) as ei:
            _watch_poll("job_never", interval_s=0.05, timeout_s=0.2,
                        json_output=False, label="job")
        assert ei.value.exit_code == 1

    def test_cli_jobs_watch_done(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.job_registry import get_job_registry, reset_job_registry

        reset_job_registry()
        reg = get_job_registry()
        reg.create("job_w3")
        reg.finish("job_w3", run_id="r3", result={"ok": True})
        r = _invoke(["jobs", "watch", "job_w3", "--interval", "0.01",
                     "--timeout", "5", "--json"])
        assert r.exit_code == 0, r.output[:400]
        r_runs = _invoke(["runs", "watch", "job_w3", "--interval", "0.01",
                          "--timeout", "5"])
        assert r_runs.exit_code == 0
