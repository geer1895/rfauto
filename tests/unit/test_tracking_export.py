"""G10 实验追踪互操作单测（方案 §10.7 G10）。

覆盖：字段映射完整性（每个 trial 字段都有去处，缺一即失败）、MLflow/W&B
产物可被简单读取器读回并字段对齐、导出幂等（逐字节）、空/单 trial、非法输入
报错、缺失字段不补假数字。

确定性、无网络、无真机：只读写 tmp_path；不断言任何编造值。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service.tracking_export import (
    KNOWN_TRIAL_FIELDS,
    TRIAL_FIELD_MAP,
    TrackingExportError,
    check_field_coverage,
    export_run_tracking,
    export_run_tracking_safe,
    read_mlflow_run,
    read_mlflow_store,
    read_wandb_history,
)

_RID = "20260101_000000_ab12cd34"
_TS = "2026-01-01T00:00:00+00:00"
_TS_MS = int(datetime.fromisoformat(_TS).timestamp() * 1000)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_run(
    root: Path,
    *,
    run_id: str = _RID,
    trials: list[dict] | None = None,
    meta_extra: dict | None = None,
    timestamp: str = _TS,
) -> Path:
    rdir = root / run_id
    meta = {
        "run_id": run_id,
        "model": "mline",
        "adapter": "fake",
        "algorithm": "tune",
        "study_name": "study_x",
        "seed": 7,
        "git_sha": "abc1234",
        "aedt_version": "fake",
        "ads_version": "",
        "timestamp": timestamp,
        "status": "done",
    }
    if meta_extra:
        meta.update(meta_extra)
    _write_json(rdir / "meta.json", meta)
    for trial in trials or []:
        _write_json(rdir / "trials" / f"trial_{trial['trial_number']}.json", trial)
    return rdir


def _trial(n: int, **overrides) -> dict:
    data = {
        "trial_number": n,
        "params": {"w_mm": 1.0 + n, "flag": True},
        "metrics": {"s11_db_max_in_band": -10.0 - n},
        "cost": 0.1 * (n + 1),
    }
    data.update(overrides)
    return data


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ---------------------------------------------------------------------------
# 字段映射完整性
# ---------------------------------------------------------------------------

def test_field_mapping_covers_all_known_trial_fields():
    assert set(TRIAL_FIELD_MAP) == set(KNOWN_TRIAL_FIELDS)
    assert {"trial_number", "params", "metrics", "cost"} <= set(TRIAL_FIELD_MAP)
    for field, rule in TRIAL_FIELD_MAP.items():
        assert rule["kind"] in {"param", "metric", "tag"}, field
        assert rule["family"] in {"scalar", "map", "list"}, field
        assert rule["key"], field


def test_check_field_coverage_flags_unmapped_field():
    full = {
        "trial_number": 0, "params": {}, "metrics": {}, "cost": 1.0,
        "cache_hit": True, "feasible": True, "constraint_values": [0.0],
    }
    assert check_field_coverage(full) == []
    assert check_field_coverage({**full, "bogus": 1}) == ["bogus"]


def test_every_mapped_field_has_a_realized_destination(tmp_path):
    full = {
        "trial_number": 0,
        "params": {"w_mm": 2.5},
        "metrics": {"s11_db_max_in_band": -11.0},
        "cost": 0.5,
        "cache_hit": True,
        "feasible": False,
        "constraint_values": [0.25, -0.1],
    }
    root = tmp_path / "runs"
    _make_run(root, trials=[full])
    res = export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")
    rdir = Path(res["mlflow_run_dirs"][0])
    assert (rdir / "params" / "w_mm").is_file()
    assert (rdir / "metrics" / "s11_db_max_in_band").is_file()
    assert (rdir / "metrics" / "cost").is_file()
    assert (rdir / "metrics" / "constraint_0").is_file()
    assert (rdir / "metrics" / "constraint_1").is_file()
    assert (rdir / "tags" / "trial_number").read_text(encoding="utf-8") == "0"
    assert (rdir / "tags" / "cache_hit").read_text(encoding="utf-8") == "true"
    assert (rdir / "tags" / "feasible").read_text(encoding="utf-8") == "false"


def test_export_unknown_trial_field_raises(tmp_path):
    root = tmp_path / "runs"
    _make_run(root, trials=[{**_trial(0), "mystery": 3}])
    with pytest.raises(TrackingExportError, match="mystery"):
        export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")


# ---------------------------------------------------------------------------
# MLflow 产物 + 读取器往返
# ---------------------------------------------------------------------------

def test_export_creates_mlflow_layout_and_manifest(tmp_path):
    root = tmp_path / "runs"
    _make_run(root, trials=[_trial(0), _trial(1)])
    out = tmp_path / "tr"
    res = export_run_tracking(_RID, runs_root=root, out_dir=out)
    assert res["ok"] is True
    assert res["n_trials"] == 2
    exp_dir = out / "mlruns" / res["experiment_id"]
    assert (exp_dir / "meta.yaml").is_file()
    for rdir_str in res["mlflow_run_dirs"]:
        rdir = Path(rdir_str)
        assert (rdir / "meta.yaml").is_file()
        assert (rdir / "params" / "w_mm").is_file()
        assert (rdir / "metrics" / "cost").is_file()
        assert (rdir / "tags" / "source_run_id").read_text(encoding="utf-8") == _RID
    manifest = json.loads(Path(res["manifest"]).read_text(encoding="utf-8"))
    assert manifest["source_run_id"] == _RID
    assert manifest["n_trials"] == 2
    assert manifest["source_timestamp_known"] is True
    assert manifest["source_timestamp_ms"] == _TS_MS
    assert manifest["field_mapping"]["trial"] == TRIAL_FIELD_MAP
    assert manifest["experiment"]["id"] == res["experiment_id"]


def test_mlflow_roundtrip_fields_aligned(tmp_path):
    root = tmp_path / "runs"
    src = [
        _trial(0),
        _trial(1, params={"w_mm": 2.5, "note": "hi"},
               metrics={"s11_db_max_in_band": -12.0}),
    ]
    _make_run(root, trials=src)
    res = export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")
    recs = {r["trial_number"]: r for r in read_mlflow_store(Path(res["mlflow_store"]))}
    assert set(recs) == {0, 1}
    for trial in src:
        rec = recs[trial["trial_number"]]
        assert rec["source_run_id"] == _RID
        assert rec["params"] == trial["params"]
        assert rec["metrics"] == trial["metrics"]
        assert rec["cost"] == trial["cost"]


def test_param_types_roundtrip_exactly(tmp_path):
    root = tmp_path / "runs"
    trial = _trial(0, params={"w_mm": 2.5, "n": 3, "flag": False, "note": "hello"})
    _make_run(root, trials=[trial])
    res = export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")
    rec = read_mlflow_run(res["mlflow_run_dirs"][0])
    assert rec["params"] == trial["params"]


def test_metric_file_is_mlflow_line_format(tmp_path):
    root = tmp_path / "runs"
    trial = _trial(0, metrics={"s11_db_max_in_band": -11.25}, cost=0.5)
    _make_run(root, trials=[trial])
    res = export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")
    rdir = Path(res["mlflow_run_dirs"][0])
    parts = (rdir / "metrics" / "cost").read_text(encoding="utf-8").split()
    assert len(parts) == 3
    assert json.loads(parts[0]) == 0.5
    assert parts[1] == str(_TS_MS)
    assert parts[2] == "0"


def test_wandb_jsonl_roundtrip(tmp_path):
    root = tmp_path / "runs"
    src = [_trial(0), _trial(1)]
    _make_run(root, trials=src)
    res = export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")
    rows = read_wandb_history(res["wandb_jsonl"])
    assert [r["run"] for r in rows] == [_RID, _RID]
    assert [r["step"] for r in rows] == [0, 1]
    for trial, row in zip(src, rows, strict=True):
        assert row["params"] == trial["params"]
        assert row["metrics"]["s11_db_max_in_band"] == trial["metrics"]["s11_db_max_in_band"]
        assert row["metrics"]["cost"] == trial["cost"]
        assert row["tags"]["source_run_id"] == _RID


def test_missing_cost_is_not_fabricated(tmp_path):
    root = tmp_path / "runs"
    trial = _trial(0)
    trial.pop("cost")
    _make_run(root, trials=[trial])
    res = export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")
    rdir = Path(res["mlflow_run_dirs"][0])
    assert not (rdir / "metrics" / "cost").exists()
    rec = read_mlflow_run(rdir)
    assert rec["cost"] is None
    assert rec["metrics"] == trial["metrics"]
    row = read_wandb_history(res["wandb_jsonl"])[0]
    assert "cost" not in row["metrics"]


# ---------------------------------------------------------------------------
# 幂等 / 空 / 单 trial
# ---------------------------------------------------------------------------

def test_export_is_idempotent_byte_identical(tmp_path):
    root = tmp_path / "runs"
    _make_run(root, trials=[_trial(0), _trial(1)])
    out = tmp_path / "tr"
    export_run_tracking(_RID, runs_root=root, out_dir=out)
    first = _snapshot(out)
    assert first
    export_run_tracking(_RID, runs_root=root, out_dir=out)
    assert _snapshot(out) == first


def test_empty_trials_exports_zero(tmp_path):
    root = tmp_path / "runs"
    _make_run(root, trials=[])
    res = export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")
    assert res["n_trials"] == 0
    assert res["mlflow_run_dirs"] == []
    assert read_mlflow_store(Path(res["mlflow_store"])) == []
    assert Path(res["wandb_jsonl"]).read_text(encoding="utf-8") == ""
    manifest = json.loads(Path(res["manifest"]).read_text(encoding="utf-8"))
    assert manifest["n_trials"] == 0


def test_single_trial_export(tmp_path):
    root = tmp_path / "runs"
    _make_run(root, trials=[_trial(4)])
    res = export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")
    assert res["n_trials"] == 1
    recs = read_mlflow_store(Path(res["mlflow_store"]))
    assert len(recs) == 1
    assert recs[0]["trial_number"] == 4


def test_trials_share_one_experiment_with_distinct_runs(tmp_path):
    root = tmp_path / "runs"
    _make_run(root, trials=[_trial(0), _trial(1), _trial(2)])
    res = export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")
    exp_dir = Path(res["mlflow_store"]) / res["experiment_id"]
    run_dirs = [p for p in exp_dir.iterdir() if p.is_dir() and (p / "meta.yaml").is_file()]
    assert len(run_dirs) == 3
    assert len({p.name for p in run_dirs}) == 3
    assert len({r["experiment_id"] for r in read_mlflow_store(Path(res["mlflow_store"]))}) == 1


# ---------------------------------------------------------------------------
# 非法输入报错
# ---------------------------------------------------------------------------

def test_missing_run_dir_raises(tmp_path):
    with pytest.raises(TrackingExportError, match="不存在"):
        export_run_tracking("nope", runs_root=tmp_path / "runs", out_dir=tmp_path / "tr")


def test_missing_meta_raises(tmp_path):
    rdir = tmp_path / "runs" / "r1"
    (rdir / "trials").mkdir(parents=True)
    _write_json(rdir / "trials" / "trial_0.json", _trial(0))
    with pytest.raises(TrackingExportError, match="非 rfauto"):
        export_run_tracking("r1", runs_root=tmp_path / "runs", out_dir=tmp_path / "tr")


def test_malformed_trial_json_raises(tmp_path):
    root = tmp_path / "runs"
    _make_run(root, trials=[_trial(0)])
    (root / _RID / "trials" / "trial_2.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(TrackingExportError, match="解析失败"):
        export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")


def test_nonfinite_metric_raises_and_writes_nothing(tmp_path):
    root = tmp_path / "runs"
    _make_run(root, trials=[_trial(0, metrics={"s11": float("nan")})])
    out = tmp_path / "tr"
    with pytest.raises(TrackingExportError, match="有限数值"):
        export_run_tracking(_RID, runs_root=root, out_dir=out)
    assert not out.exists()


def test_duplicate_trial_number_raises(tmp_path):
    root = tmp_path / "runs"
    _make_run(root, trials=[_trial(0)])
    _write_json(root / _RID / "trials" / "trial_9.json", _trial(0))
    with pytest.raises(TrackingExportError, match="重复"):
        export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")


def test_bad_params_type_raises(tmp_path):
    root = tmp_path / "runs"
    _make_run(root, trials=[_trial(0, params=["not", "a", "dict"])])
    with pytest.raises(TrackingExportError, match="params"):
        export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")


def test_safe_wrapper_returns_error_dict(tmp_path):
    res = export_run_tracking_safe("nope", runs_root=tmp_path / "runs", out_dir=tmp_path / "tr")
    assert res["ok"] is False
    assert res["errors"]


def test_missing_timestamp_marked_unknown_not_fabricated(tmp_path):
    root = tmp_path / "runs"
    _make_run(root, trials=[_trial(0)], timestamp="")
    res = export_run_tracking(_RID, runs_root=root, out_dir=tmp_path / "tr")
    manifest = json.loads(Path(res["manifest"]).read_text(encoding="utf-8"))
    assert manifest["source_timestamp_known"] is False
    assert manifest["source_timestamp_ms"] is None
