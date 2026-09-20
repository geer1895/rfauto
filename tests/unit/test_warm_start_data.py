"""E11 stage-2 数据面测试：数据集历史样本 → warm-start 喂料 → 先验注入。

覆盖（四态）：
- 正常组装：params_json 解析、样本 {"params","cost"} 结构、溯源字段
- 模板族/study 过滤：``?`` 参数化下推 DuckDB（E11 未尽③，limit 在过滤
  后生效不漏样本），Python 侧精确相等保留为纵深防御
- 非法 params_json 跳过并计数：截断 JSON / None / 非对象 / params NaN /
  cost 缺失 / cost NaN —— 全部显式计数上报，不静默（物化侧已在源头整点
  拦截 params/metrics/cost 非有限值——E11 未尽②根治 + NaN cost 实证
  P1 收口；本面拦截保留为纵深防御，直写 Parquet 的坏行照样拦）
- 空数据集/全无效样本：run 包装层如实 ok=False 报错，不偷偷降级冷启动

外部通道钉住（#139）：run 包装层单测 monkeypatch
rfauto.optimization.optimizer.run_optimization（warm_start_data 惰性导入
在调用时取属性，patch 生效）；端到端冒烟走进程内 fake 适配器（同
test_warm_start.py 先例），chdir 隔离不污染真实 runs/（#144）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="数据面查询需要 dataset extra（duckdb）")
pytest.importorskip("pyarrow", reason="数据面测试构造 Parquet 需要 pyarrow")

import optuna
import yaml

from rfauto.service.warm_start_data import (
    collect_warm_start_samples,
    run_optimization_warm_start_from_dataset,
)

optuna.logging.set_verbosity(optuna.logging.WARNING)


# ─── 数据集构造（手工 Parquet：坏行是物化侧造不出的，直写绕过 materialize） ──

def _write_dataset(tmp_path: Path, name: str, rows: list[dict]) -> None:
    """按 DATASET_SCHEMA 直写 Parquet 数据集（run_id/params_json/cost 可注入坏值）。"""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from rfauto.service.dataset_service import DATASET_SCHEMA

    type_map = {"string": pa.string(), "int64": pa.int64(), "float64": pa.float64()}
    schema = pa.schema([(c, type_map[t]) for c, t in DATASET_SCHEMA])
    full_rows = []
    for i, r in enumerate(rows):
        row = {c: None for c, _t in DATASET_SCHEMA}
        row.update({
            "run_id": r.get("run_id", f"row_{i}"),
            "model": "mline",
            "adapter": "fake",
            "algorithm": "tune",
            "study_name": "s1",
            "seed": 42,
            "metrics_json": "{}",
            "point_index": i,
            "source": "trials",
            "provenance_json": "{}",
        })
        row.update(r)
        full_rows.append(row)
    ddir = tmp_path / "runs" / "datasets" / name
    ddir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(full_rows, schema=schema), ddir / "points.parquet")


def _std_rows() -> list[dict]:
    """2 条合法同族 + 1 条异族 + 5 条坏行（覆盖全部跳过原因分类）。"""
    return [
        {"run_id": "ok_0", "params_json": json.dumps({"w_mm": 1.0, "l_mm": 20.0}),
         "cost": 0.05},
        {"run_id": "ok_1", "params_json": json.dumps({"w_mm": 2.0, "l_mm": 21.0}),
         "cost": 0.5},
        # 异族键：数据面照常透传，由 stage-1 相似度门拒绝（不重复设门）
        {"run_id": "alien", "params_json": json.dumps({"a_mm": 1.0, "b_mm": 2.0}),
         "cost": 0.001},
        # 坏行 5 条
        {"run_id": "bad_trunc", "params_json": '{"w_mm": 1.0', "cost": 0.1},
        {"run_id": "bad_none", "params_json": None, "cost": 0.1},
        {"run_id": "bad_nan_param", "params_json": '{"w_mm": NaN}', "cost": 0.1},
        {"run_id": "bad_cost_none", "params_json": json.dumps({"w_mm": 1.5}), "cost": None},
        {"run_id": "bad_cost_nan", "params_json": json.dumps({"w_mm": 1.6}),
         "cost": float("nan")},
    ]


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """chdir 隔离：数据集落在 tmp runs/datasets，优化产物不污染真实 runs/（#144）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    return tmp_path


# ─── collect_warm_start_samples（纯数据面） ──────────────────────────────────

class TestCollectWarmStartSamples:
    def test_normal_assembly_with_skip_counts(self, tmp_path):
        """合法行组装成 {"params","cost"} 样本；坏行逐一跳过并按原因计数。"""
        _write_dataset(tmp_path, "ws_ds", _std_rows())
        r = collect_warm_start_samples("ws_ds")
        assert r["ok"], r.get("errors")
        assert r["n_rows_scanned"] == 8
        assert r["n_samples"] == 3
        assert r["n_skipped_invalid"] == 5
        # 喂料格式：params 是 dict、cost 是有限 float，附溯源字段
        by_rid = {s["run_id"]: s for s in r["samples"]}
        assert set(by_rid) == {"ok_0", "ok_1", "alien"}
        s0 = by_rid["ok_0"]
        assert s0["params"] == {"w_mm": 1.0, "l_mm": 20.0}
        assert isinstance(s0["cost"], float) and math.isfinite(s0["cost"])
        assert s0["cost"] == pytest.approx(0.05)
        # NaN/非法逐类计数，可归因
        assert r["skip_reasons"] == {
            "params_json 非法 JSON": 1,
            "params_json 缺失": 1,
            "params 含 NaN/Inf": 1,
            "cost 缺失或非数值": 1,
            "cost 含 NaN/Inf": 1,
        }
        assert r["n_filtered_by_model"] == 0
        assert len(r["skip_examples"]) == 3

    def test_model_and_study_filter_pushdown(self, tmp_path):
        """模板族/study 过滤已下推 DuckDB（``?`` 值参数绑定，E11 未尽③）：
        命中样本精确；Python 侧过滤保留为纵深防御（正常计数归零）。"""
        rows = [
            {"run_id": "m1", "model": "mline", "study_name": "s1",
             "params_json": json.dumps({"w_mm": 1.0}), "cost": 0.1},
            {"run_id": "m2", "model": "patch_antenna", "study_name": "s1",
             "params_json": json.dumps({"h_mm": 1.0}), "cost": 0.2},
            {"run_id": "m3", "model": "mline", "study_name": "s9",
             "params_json": json.dumps({"w_mm": 3.0}), "cost": 0.3},
        ]
        _write_dataset(tmp_path, "fam_ds", rows)
        r = collect_warm_start_samples("fam_ds", model="mline", source_study="s1")
        assert r["ok"]
        assert [s["run_id"] for s in r["samples"]] == ["m1"]
        # 下推回执：两谓词都进了 SQL 侧
        assert r["filters"] == {"model": "mline", "study_name": "s1"}
        # SQL 已过滤 → Python 侧纵深计数为 0
        assert r["n_filtered_by_model"] == 0
        assert r["n_filtered_by_study"] == 0
        assert r["n_skipped_invalid"] == 0

    def test_limit_applies_after_model_filter_no_missing(self, tmp_path):
        """E11 未尽③根治实证：多族数据集（目标族行排末尾）+ limit=3 小于
        总行数 6——修复前 LIMIT 先截断，目标族样本全漏；修复后过滤后
        截断，不漏样本。"""
        rows = [
            {"run_id": f"other_{i}", "model": "patch_antenna", "study_name": "s1",
             "params_json": json.dumps({"h_mm": float(i)}), "cost": 0.1}
            for i in range(4)
        ] + [
            {"run_id": f"want_{i}", "model": "mline", "study_name": "s1",
             "params_json": json.dumps({"w_mm": float(i)}), "cost": 0.2}
            for i in range(2)
        ]
        _write_dataset(tmp_path, "bigfam_ds", rows)
        r = collect_warm_start_samples("bigfam_ds", model="mline", limit=3)
        assert r["ok"], r.get("errors")
        # 2 条目标族样本全数返回（修复前为 0）
        assert [s["run_id"] for s in r["samples"]] == ["want_0", "want_1"]
        assert r["n_rows_scanned"] == 2
        assert r["filters"] == {"model": "mline"}

    def test_model_filter_value_injection_safe(self, tmp_path):
        """model 值含 SQL 语法字符：参数化绑定按字面量比较，不注入、
        不报错、0 命中（"值不拼 SQL"防御不倒退）。"""
        _write_dataset(tmp_path, "inj_ds", _std_rows())
        r = collect_warm_start_samples(
            "inj_ds", model="x' OR model = 'mline")
        assert r["ok"], r.get("errors")
        assert r["samples"] == []
        assert r["n_rows_scanned"] == 0

    def test_nonexistent_dataset_reports_error(self, tmp_path):
        """空数据集（不存在）：ok=False 如实报错，不静默返回空列表。"""
        r = collect_warm_start_samples("nope")
        assert not r["ok"]
        assert r["errors"] and "数据集不存在" in r["errors"][0]

    def test_zero_row_dataset_ok_but_empty(self, tmp_path):
        """0 行数据集：查询 ok 但 samples=[]，是否报错由 run 包装层决定。"""
        _write_dataset(tmp_path, "zero_ds", [])
        r = collect_warm_start_samples("zero_ds")
        assert r["ok"]
        assert r["samples"] == [] and r["n_rows_scanned"] == 0

    def test_materialize_root_cures_nan_and_data_plane_still_guards(self, tmp_path):
        """根治后行为（E11 未尽②收口 + NaN cost 实证 P1）：物化侧在收集
        源头整点拦截 params/metrics/cost 非有限值并计数——cost NaN 行不再
        落盘（DuckDB read_parquet 统计路径下 `cost < 0.1` 对 NaN 行求值
        TRUE，落盘会挤占 warm-start collect 的 LIMIT 窗口）；数据面拦截
        保留为纵深防御（直写 Parquet/外部数据集的坏行照样拦）。"""
        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        root = tmp_path / "runs" / "run_nan"
        (root / "trials").mkdir(parents=True)
        (root / "meta.json").write_text(json.dumps({
            "run_id": "run_nan", "model": "mline", "adapter": "fake",
            "algorithm": "tune", "study_name": "s1", "seed": 1}), encoding="utf-8")
        # json.dumps 默认 allow_nan=True → 产出规范外 NaN 字面量
        (root / "trials" / "trial_0.json").write_text(json.dumps({
            "trial_number": 0, "params": {"w_mm": float("nan")},
            "metrics": {}, "cost": 0.1}), encoding="utf-8")
        (root / "trials" / "trial_1.json").write_text(json.dumps({
            "trial_number": 1, "params": {"w_mm": 1.0},
            "metrics": {}, "cost": float("nan")}), encoding="utf-8")
        (root / "trials" / "trial_2.json").write_text(json.dumps({
            "trial_number": 2, "params": {"w_mm": 2.0},
            "metrics": {}, "cost": 0.2}), encoding="utf-8")
        m = materialize_dataset(["run_nan"], name="nan_ds", health_gate=False)
        assert m["ok"], m.get("errors")
        assert m["n_nonfinite_skipped"] == 2  # NaN 参数点 + NaN cost 点均源头拦截
        assert m["n_rows"] == 1               # 只有合法点 2 落盘
        raw = query_dataset("nan_ds", columns=["point_index", "params_json", "cost"])
        assert raw["ok"], raw.get("errors")
        assert len(raw["rows"]) == 1
        row = raw["rows"][0]
        assert row["point_index"] == 2        # NaN 参数点/cost 点均不落盘
        assert row["params_json"] == '{"w_mm":2.0}'   # 规范 JSON，无 "NaN"
        assert row["cost"] == pytest.approx(0.2)
        # `cost < 0.1` 谓词在盘上没有 NaN 行可被误判 TRUE（LIMIT 窗口不被挤占）
        pred = query_dataset("nan_ds", where="cost < 0.1")
        assert pred["ok"] and pred["n_rows"] == 0

        # 数据面（纵深防御）：直写 Parquet 注入的 cost NaN 行仍被拦
        _write_dataset(tmp_path, "inj_nan", [
            {"run_id": "good", "params_json": json.dumps({"w_mm": 1.0}),
             "cost": 0.1},
            {"run_id": "bad", "params_json": json.dumps({"w_mm": 9.0}),
             "cost": float("nan")},
        ])
        r = collect_warm_start_samples("inj_nan", model="mline")
        assert r["ok"]
        assert [s["params"] for s in r["samples"]] == [{"w_mm": 1.0}]
        assert r["skip_reasons"] == {"cost 含 NaN/Inf": 1}


# ─── run 包装层（monkeypatch 钉 run_optimization 通道，#139） ─────────────────

class TestRunWrapper:
    def _patch_run(self, monkeypatch, calls, response):
        def fake_run(recipe_path, **kwargs):
            calls["recipe_path"] = recipe_path
            calls["kwargs"] = kwargs
            return dict(response)

        monkeypatch.setattr(
            "rfauto.optimization.optimizer.run_optimization", fake_run)

    def test_feeds_all_samples_without_gate(self, tmp_path, monkeypatch):
        """数据面只喂料不重复设门：异族样本同样透传给 run_optimization，
        相似度门在 warm_start 内（stage-1）。"""
        _write_dataset(tmp_path, "ws_ds", _std_rows())
        calls: dict = {}
        self._patch_run(monkeypatch, calls, {"ok": True, "warm_start_n": 2})
        result = run_optimization_warm_start_from_dataset("r.yaml", "ws_ds")
        assert result["ok"]
        assert calls["recipe_path"] == "r.yaml"
        kw = calls["kwargs"]
        assert kw["adapter_name"] == "fake"
        assert kw["max_trials"] == 60
        assert kw["study_name"] is None
        # 3 条有效样本（含异族）全部透传；顺序保持扫描序（排序/裁剪在门内）
        fed = kw["warm_start"]
        assert [s["run_id"] for s in fed] == ["ok_0", "ok_1", "alien"]
        assert fed[0]["params"] == {"w_mm": 1.0, "l_mm": 20.0}
        assert fed[0]["cost"] == pytest.approx(0.05)
        # 数据面统计随结果透出（不含 samples 本体）
        assert result["warm_start_data"]["n_samples"] == 3
        assert result["warm_start_data"]["n_skipped_invalid"] == 5
        assert "samples" not in result["warm_start_data"]

    def test_model_filter_forwarded(self, tmp_path, monkeypatch):
        _write_dataset(tmp_path, "ws_ds", _std_rows())
        calls: dict = {}
        self._patch_run(monkeypatch, calls, {"ok": True})
        run_optimization_warm_start_from_dataset(
            "r.yaml", "ws_ds", model="mline", source_study="s1",
            adapter_name="hfss", max_trials=7, study_name="st1")
        kw = calls["kwargs"]
        assert kw["adapter_name"] == "hfss"
        assert kw["max_trials"] == 7
        assert kw["study_name"] == "st1"
        assert all(s["run_id"] != "m2" for s in kw["warm_start"])

    def test_nonexistent_dataset_error_stub_not_called(self, tmp_path, monkeypatch):
        """空数据集如实报错：不偷偷降级冷启动，优化通道零调用。"""
        calls: dict = {}
        self._patch_run(monkeypatch, calls, {"ok": True})
        result = run_optimization_warm_start_from_dataset("r.yaml", "nope")
        assert not result["ok"]
        assert "数据集不可用" in result["errors"][-1]
        assert calls == {}

    def test_all_invalid_samples_error_stub_not_called(self, tmp_path, monkeypatch):
        """全部样本无效（可统计归因）→ 如实 ok=False，不硬凑冷启动。"""
        rows = [
            {"run_id": "b1", "params_json": "{oops", "cost": 0.1},
            {"run_id": "b2", "params_json": json.dumps({"w_mm": 1.0}), "cost": None},
        ]
        _write_dataset(tmp_path, "bad_ds", rows)
        calls: dict = {}
        self._patch_run(monkeypatch, calls, {"ok": True})
        result = run_optimization_warm_start_from_dataset("r.yaml", "bad_ds")
        assert not result["ok"]
        assert "无可用历史样本" in result["errors"][0]
        assert "无效 2" in result["errors"][0]
        assert calls == {}

    def test_optimization_failure_passthrough(self, tmp_path, monkeypatch):
        """run_optimization 失败（如配方缺失）原样透传 ok=False，附数据面统计。"""
        _write_dataset(tmp_path, "ws_ds", _std_rows())
        calls: dict = {}
        self._patch_run(monkeypatch, calls,
                        {"ok": False, "errors": ["配方文件不存在: r.yaml"]})
        result = run_optimization_warm_start_from_dataset("r.yaml", "ws_ds")
        assert not result["ok"]
        assert result["errors"] == ["配方文件不存在: r.yaml"]
        assert result["warm_start_data"]["n_samples"] == 3


# ─── 端到端（进程内 fake 通道：喂料 → stage-1 门 → 注入） ────────────────────

class TestEndToEndFake:
    @pytest.fixture(autouse=True)
    def _clean_optuna_db(self, tmp_path, monkeypatch):
        db_dir = tmp_path / "runs" / ".optuna"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            "rfauto.optimization.optimizer.get_storage_path",
            lambda: f"sqlite:///{(db_dir / 'optuna.db').as_posix()}",
        )

    def _write_recipe(self, tmp_path: Path) -> str:
        """wilkinson fake 配方（同 test_warm_start.py 基线）。"""
        recipe = {
            "model": "wilkinson_power_divider",
            "params": {
                "f0_ghz": {"value": 2.4, "unit": "GHz"},
                "z0_ohm": {"value": 50, "unit": "ohm"},
                "substrate": "rogers4350b_h0.508",
                "division": "1:1",
                "arm_len_mm": {"value": 20.5},
                "series_w_mm": {"value": 0.33},
                "shunt_w_mm": {"value": 1.10},
            },
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 101},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
                {"metric": "s21_db", "band": [2.3, 2.5], "op": "mean_within", "value": [-3.6, -3.1]},
            ],
            "optimization": {
                "params": {
                    "arm_len_mm": {"low": 18.0, "high": 23.0},
                    "series_w_mm": {"low": 0.25, "high": 0.45},
                },
            },
        }
        path = tmp_path / "ws_data.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        return str(path)

    def test_dataset_samples_injected_and_alien_gate_rejected(self, tmp_path):
        """数据集同族样本注入（先跑）+ 异族样本被 stage-1 门拒绝
        （warm_start_n 只数同族）+ 坏行不进优化通道。"""
        rows = [
            {"run_id": "w0", "model": "wilkinson_power_divider",
             "params_json": json.dumps({"arm_len_mm": 19.5, "series_w_mm": 0.35}),
             "cost": 0.05},
            {"run_id": "w1", "model": "wilkinson_power_divider",
             "params_json": json.dumps({"arm_len_mm": 22.5, "series_w_mm": 0.40}),
             "cost": 0.50},
            {"run_id": "w_alien", "model": "wilkinson_power_divider",
             "params_json": json.dumps({"l_mm": 1.0, "w_mm": 2.0}),
             "cost": 0.001},
            {"run_id": "w_bad", "model": "wilkinson_power_divider",
             "params_json": '{"arm_len_mm": ', "cost": 0.1},
        ]
        _write_dataset(tmp_path, "wilk_ds", rows)
        recipe = self._write_recipe(tmp_path)
        result = run_optimization_warm_start_from_dataset(
            recipe, "wilk_ds", model="wilkinson_power_divider",
            adapter_name="fake", max_trials=4, study_name="e11_data_e2e",
            adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"], result.get("errors")
        # 喂料 3 条（含异族），门只放行 2 条同族
        assert result["warm_start_data"]["n_samples"] == 3
        assert result["warm_start_data"]["n_skipped_invalid"] == 1
        assert result["warm_start_n"] == 2
        assert result["trials_completed"] == 4


# ─── CLI / MCP 薄壳（直连 service，run_optimization 通道钉住） ───────────────

def _stub_run(monkeypatch, calls: dict, response: dict) -> None:
    def fake_run(recipe_path, **kwargs):
        calls["recipe_path"] = recipe_path
        calls["kwargs"] = kwargs
        return dict(response)

    monkeypatch.setattr("rfauto.optimization.optimizer.run_optimization", fake_run)


class TestCliThinShell:
    def test_warm_start_success_prints_stats(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        _write_dataset(tmp_path, "ws_ds", _std_rows())
        calls: dict = {}
        _stub_run(monkeypatch, calls, {
            "ok": True, "warm_start_n": 2, "trials_completed": 5,
            "best_cost": 0.01, "best_params": {"w_mm": 1.0}})
        r = CliRunner().invoke(app, [
            "warm-start", "ws_ds", "r.yaml", "--model", "mline",
            "--max-trials", "5", "--adapter", "fake"])
        assert r.exit_code == 0, r.output
        assert "warm-start 喂料" in r.output
        assert "样本 3" in r.output and "无效跳过 5" in r.output
        assert "warm_start_n=2" in r.output
        assert calls["kwargs"]["max_trials"] == 5
        assert len(calls["kwargs"]["warm_start"]) == 3

    def test_warm_start_limit_forwarded(self, tmp_path, monkeypatch):
        """--limit 透传到数据面：查询截断到 2 行 → 扫描 2 行、样本 2。"""
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        _write_dataset(tmp_path, "ws_ds", _std_rows())
        calls: dict = {}
        _stub_run(monkeypatch, calls, {"ok": True, "warm_start_n": 2})
        r = CliRunner().invoke(app, ["warm-start", "ws_ds", "r.yaml", "--limit", "2"])
        assert r.exit_code == 0, r.output
        assert "扫描 2 行" in r.output
        assert len(calls["kwargs"]["warm_start"]) == 2

    def test_warm_start_missing_dataset_exit_code(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        calls: dict = {}
        _stub_run(monkeypatch, calls, {"ok": True})
        r = CliRunner().invoke(app, ["warm-start", "nope", "r.yaml"])
        assert r.exit_code == 1
        assert "warm-start 优化失败" in r.output
        assert calls == {}


class TestMcpThinShell:
    def test_warm_start_optimize_tool(self, tmp_path, monkeypatch):
        import asyncio

        from rfauto.mcp_server import mcp

        _write_dataset(tmp_path, "ws_ds", _std_rows())
        calls: dict = {}
        _stub_run(monkeypatch, calls, {"ok": True, "warm_start_n": 2})
        tr = asyncio.run(mcp.call_tool("warm_start_optimize", {
            "recipe_path": "r.yaml", "dataset": "ws_ds", "model": "mline",
            "max_trials": 3}))
        data = tr.structured_content if getattr(tr, "structured_content", None) else \
            json.loads(tr.content[0].text)
        assert data["ok"] is True
        assert data["warm_start_data"]["n_samples"] == 3
        assert calls["kwargs"]["max_trials"] == 3
        assert calls["kwargs"]["adapter_name"] == "fake"

    def test_warm_start_optimize_missing_dataset(self, tmp_path, monkeypatch):
        import asyncio

        from rfauto.mcp_server import mcp

        calls: dict = {}
        _stub_run(monkeypatch, calls, {"ok": True})
        tr = asyncio.run(mcp.call_tool("warm_start_optimize", {
            "recipe_path": "r.yaml", "dataset": "nope"}))
        data = tr.structured_content if getattr(tr, "structured_content", None) else \
            json.loads(tr.content[0].text)
        assert data["ok"] is False
        assert calls == {}
