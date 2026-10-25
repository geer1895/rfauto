"""dataset_profile 数据集一键画像测试（aurora_g W8-S4，2026-10-19）。

钉四件事：规模/计数/参数范围画像、>3σ 异常值判定（含 std=0 全同值列
如实 0 异常）、错误路径信封、CLI --json 双路径冒烟。

自建局部夹具（不共享 runs_env——画像需要 ≥11 点才能出 >3σ 异常值：
总体 std 下单列最大可能 z=(n−1)/√n，n=13 点 12×1.0+1×100 实测 z≈3.46）；
chdir tmp 隔离（#144）；依赖缺失整文件 skip（dataset extra 惯例）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="数据集画像需要 dataset extra（duckdb）")
pytest.importorskip("pyarrow", reason="数据集画像需要 dataset extra（pyarrow）")

from rfauto.cli.main import app as root_app
from rfauto.service.dataset_service import dataset_profile, materialize_dataset

N_BASE = 12  # 基线点数（cost=1.0）；+1 个 cost=100 异常点


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def profile_env(tmp_path, monkeypatch):
    """tmp/runs 单 run 13 trials（12 基线 + 1 个 >3σ cost 异常点）→
    物化为 prof 数据集。params 逐点变化（去重指纹不折叠）。"""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs" / "run_p"
    _write_json(root / "meta.json", {
        "run_id": "run_p", "model": "mline", "adapter": "fake",
        "algorithm": "tune", "study_name": "s1", "seed": 42,
        "timestamp": "2026-10-19T00:00:00+00:00", "status": "done"})
    trials = root / "trials"
    for i in range(N_BASE):
        _write_json(trials / f"trial_{i}.json", {
            "trial_number": i,
            "params": {"w_mm": 1.0 + 0.1 * i},
            "metrics": {"s11_db_max_in_band": -10.0 - 0.1 * i,
                        "const_metric": 1.0},
            "cost": 1.0})
    _write_json(trials / f"trial_{N_BASE}.json", {
        "trial_number": N_BASE,
        "params": {"w_mm": 9.9},
        "metrics": {"s11_db_max_in_band": -30.0, "const_metric": 1.0},
        "cost": 100.0})
    r = materialize_dataset(None, name="prof")
    assert r.get("ok"), r.get("errors")
    return tmp_path


class TestDatasetProfile:
    def test_scale_models_param_ranges(self, profile_env):
        """规模画像：行/列/run/模型计数 + params 逐键范围 + 指标键计数。"""
        r = dataset_profile("prof")
        assert r["ok"], r.get("errors")
        assert r["dataset"] == "prof" and r["format"] == "parquet"
        assert r["n_rows"] == N_BASE + 1
        assert r["n_columns"] == 12  # DATASET_SCHEMA 全列
        assert r["n_runs"] == 1
        assert r["models"] == {"mline": N_BASE + 1}
        assert r["param_ranges"]["w_mm"]["kind"] == "numeric"
        assert r["param_ranges"]["w_mm"]["min"] == pytest.approx(1.0)
        assert r["param_ranges"]["w_mm"]["max"] == pytest.approx(9.9)
        assert r["metric_stats"]["const_metric"]["n"] == N_BASE + 1
        assert r["n_bad_json_rows"] == 0

    def test_outliers_and_constant_column(self, profile_env):
        """>3σ 异常值：cost 100 点命中（run_id/direction 归属）；
        全同值列 std=0 → 异常值如实 0（z 不定义不臆测）。"""
        r = dataset_profile("prof")
        assert r["ok"], r.get("errors")
        cost = r["cost_stats"]
        assert cost["n"] == N_BASE + 1
        assert cost["n_outliers"] == 1
        ex = cost["outliers"][0]
        assert ex["run_id"] == "run_p" and ex["direction"] == "high"
        assert ex["value"] == pytest.approx(100.0)
        assert ex["z"] > 3.0
        assert r["metric_stats"]["const_metric"]["n_outliers"] == 0
        assert r["metric_stats"]["s11_db_max_in_band"]["n_outliers"] == 1

    def test_gates_from_manifest(self, profile_env):
        """门通过率单源=manifest：health_verdicts tally/判定数/健康占比 +
        GT 行占比字段齐备（健康门判定语义归 health_service，此处只钉画像
        透传面——healthy_rate 为 None 或 [0,1] 内浮点）。"""
        r = dataset_profile("prof")
        assert r["ok"], r.get("errors")
        gates = r["gates"]
        assert isinstance(gates["n_runs_judged"], int)
        rate = gates["healthy_rate"]
        assert rate is None or (0.0 <= rate <= 1.0)
        assert "health_verdicts" in gates and "gt_row_rate" in gates

    def test_error_paths(self, profile_env):
        """缺失数据集/非法名 → ok=False 信封 errors 恒 list[str]。"""
        r = dataset_profile("no_such_ds_xyz")
        assert r["ok"] is False and isinstance(r["errors"], list)
        assert all(isinstance(e, str) for e in r["errors"])
        r2 = dataset_profile("../escape")
        assert r2["ok"] is False


class TestDatasetProfileCli:
    def test_json_dual_path_smoke(self, profile_env):
        """CLI --json 双路径冒烟：成功信封（画像键齐备）与失败信封同构。"""
        runner = CliRunner()
        ok = runner.invoke(root_app, ["datasets", "profile", "prof", "--json"])
        assert ok.exit_code == 0, ok.output
        payload = json.loads(ok.output)
        assert payload["ok"] is True
        assert payload["n_rows"] == N_BASE + 1
        assert payload["cost_stats"]["n_outliers"] == 1
        fail = runner.invoke(
            root_app, ["datasets", "profile", "no_such_ds_xyz", "--json"])
        assert fail.exit_code == 1
        payload_f = json.loads(fail.output)
        assert payload_f["ok"] is False
        assert isinstance(payload_f["errors"], list) and payload_f["errors"]
