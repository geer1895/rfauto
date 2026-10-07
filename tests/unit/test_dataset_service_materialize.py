"""E1 数据集注册表 v2 测试（物化域）。

本文件承载：TestMaterialize（Parquet 物化主路径/去重/边界拒绝）、
TestCli（datasets materialize/query CLI 薄壳冒烟）、TestHdf5Format
（E1 收口①：HDF5 物化格式与 Parquet 往返一致性）。

本文件自 tests/unit/test_dataset_service.py 按被测域拆分而得
（W9 席，ge8e 后续批 P3，G1-4 登记伴生件）：纯搬运重构，类名/测试名/断言
逐字节保持，零语义变化。跨域共享基建抽至 tests/unit/_dataset_service_helpers.py
（同 _geometry_audit_helpers 包内导入惯例）；runs_env fixture 经
tests/unit/conftest.py re-export 供 pytest 解析（模块级导入会与测试参数
同名遮蔽触发 F401/F811，conftest 发现是 pytest 的正规机制）。

原模块头注释（拆分前原文，对本文件同样成立）：
构造临时 runs/（假 run：meta.json + trials/*.json + calibration/samples.json），
chdir 隔离零污染（#144）。依赖 duckdb/pyarrow（dataset extra），缺失时整文件
skip（fresh env 下的优雅降级）；缺依赖的显式报错分支用 monkeypatch sys.modules
钉住（#139 教训：不真打外部通道）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="数据集注册表 v2 需要 dataset extra（duckdb）")
pytest.importorskip("pyarrow", reason="数据集注册表 v2 需要 dataset extra（pyarrow）")

import yaml

from tests.unit._dataset_service_helpers import (
    _materialize_all,
    _meta,
    _write_json,
)


class TestMaterialize:
    def test_manifest_parquet_and_dedup(self, runs_env):
        """全量物化：manifest/Parquet 存在、行数正确、同 study/seed/params 只留一份。"""
        from rfauto.service.dataset_service import (
            MANIFEST_NAME,
            PARQUET_NAME,
        )

        r = _materialize_all("demo")
        assert r["ok"], r.get("errors")
        ddir = runs_env / "runs" / "datasets" / "demo"
        assert (ddir / PARQUET_NAME).exists()
        assert (ddir / MANIFEST_NAME).exists()
        # 点总数 2+2+2=6；run_b.trial_0 与 run_a.trial_0 同指纹 → 去重 1 条
        assert r["n_points"] == 6
        assert r["n_dup"] == 1
        assert r["n_rows"] == 5
        # 无产物 run 记入 skipped 而非报错
        assert r["skipped_runs"] == ["run_empty"]
        # manifest 内容核对
        manifest = yaml.safe_load((ddir / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert manifest["schema_version"] == "2.0"
        assert manifest["n_points"] == 6 and manifest["n_rows"] == 5
        assert manifest["n_dup"] == 1
        assert {s["run_id"] for s in manifest["source_runs"]} == {"run_a", "run_b", "run_c"}
        # 参数空间 bounds 聚合（w_mm 跨 run_a/b，h_mm 来自校准样本）
        assert manifest["bounds"]["w_mm"] == [1.0, 3.0]
        assert manifest["bounds"]["h_mm"] == [1.2, 2.0]

    def test_parquet_rows_schema(self, runs_env):
        """Parquet 行式 schema 契约：12 列齐备、calibration 样本 cost 为 NULL。"""
        import pyarrow.parquet as pq

        from rfauto.service.dataset_service import DATASET_SCHEMA

        r = _materialize_all("demo")
        assert r["ok"]
        table = pq.read_table(r["parquet"])
        assert table.column_names == [c for c, _t in DATASET_SCHEMA]
        df = table.to_pydict()
        calib_idx = [i for i, s in enumerate(df["source"])
                     if s == "calibration_samples"]
        assert len(calib_idx) == 2
        assert all(df["cost"][i] is None for i in calib_idx)
        # 去重保留首个出现的行（run_a.trial_0，cost=0.05）
        costs = sorted(c for c in df["cost"] if c is not None)
        assert 0.05 in costs and 0.06 not in costs

    def test_explicit_run_ids_and_missing(self, runs_env):
        """显式 run_ids：只物化指定 run；不存在的 run_id 记入 missing_runs。"""
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(["run_a", "ghost_run"], name="only_a")
        assert r["ok"], r.get("errors")
        assert r["n_rows"] == 2 and r["n_points"] == 2
        assert r["missing_runs"] == ["ghost_run"]

    def test_params_key_order_dedup(self, tmp_path, monkeypatch):
        """同参数点键序不同也应去重（canonical json 键排序）。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        _write_json(root / "r1" / "meta.json", _meta("r1", model="mline"))
        _write_json(root / "r1" / "trials" / "trial_0.json", {
            "trial_number": 0, "params": {"a": 1.0, "b": 2.0},
            "metrics": {}, "cost": 0.1})
        _write_json(root / "r2" / "meta.json", _meta("r2", model="mline"))
        _write_json(root / "r2" / "trials" / "trial_0.json", {
            "trial_number": 0, "params": {"b": 2.0, "a": 1.0},
            "metrics": {}, "cost": 0.2})
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(None, name="order_ds")
        assert r["ok"]
        assert r["n_points"] == 2 and r["n_dup"] == 1 and r["n_rows"] == 1

    def test_no_points_graceful(self, tmp_path, monkeypatch):
        """只有无产物 run 时不写文件、ok=False，不抛裸异常。"""
        monkeypatch.chdir(tmp_path)
        _write_json(tmp_path / "runs" / "r0" / "meta.json",
                    _meta("r0", model="mline"))
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(["r0"], name="empty_ds")
        assert not r["ok"]
        assert r["errors"]
        assert not (tmp_path / "runs" / "datasets" / "empty_ds").exists()

    def test_bad_name_rejected(self, runs_env):
        """数据集名即目录名：路径穿越/非法字符直接拒绝。"""
        from rfauto.service.dataset_service import materialize_dataset

        for bad in ("../evil", "a/b", "", ".hidden"):
            r = materialize_dataset(["run_a"], name=bad)
            assert not r["ok"], bad
            assert "非法数据集名" in r["errors"][0]

    def test_missing_pyarrow_explicit_error(self, runs_env, monkeypatch):
        """缺 pyarrow 时显式报错（monkeypatch import 失败，不依赖真实缺装）。"""
        monkeypatch.setitem(sys.modules, "pyarrow", None)
        monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(["run_a"], name="noarrow")
        assert not r["ok"]
        assert "rfauto[dataset]" in r["errors"][0]


class TestCli:
    """CLI 薄壳冒烟：materialize/query 命令组直连 service。"""

    def test_materialize_and_query(self, runs_env):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        r1 = runner.invoke(app, ["datasets", "materialize", "--name", "cli_ds"])
        assert r1.exit_code == 0, r1.output
        assert "数据集已物化" in r1.output
        assert "无产物跳过: run_empty" in r1.output

        r2 = runner.invoke(app, [
            "datasets", "query", "cli_ds",
            "--where", "cost < 0.1 and model = 'mline'",
            "--columns", "run_id,cost"])
        assert r2.exit_code == 0, r2.output
        assert "run_a" in r2.output

    def test_query_failure_exit_code(self, runs_env):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        r = runner.invoke(app, ["datasets", "query", "nope"])
        assert r.exit_code == 1
        assert "查询失败" in r.output


# ---------------------------------------------------------------------------
# E1 收口①：HF（HDF5）物化格式与 Parquet 并列可选——往返一致性
# ---------------------------------------------------------------------------

def _strip_materialized_at(rows: list[dict]) -> list[dict]:
    """provenance_json.materialized_at 随每次物化时刻变化，比对前归一。"""
    out = []
    for row in rows:
        r = dict(row)
        prov = json.loads(r["provenance_json"])
        prov.pop("materialized_at", None)
        r["provenance_json"] = json.dumps(prov, sort_keys=True)
        out.append(r)
    return out


class TestHdf5Format:
    def test_hdf5_roundtrip_rows_equal_parquet_twin(self, runs_env):
        """同一 runs/ 分别物化 hdf5 与 parquet：查询结果逐行逐列相等
        （含可空列 seed=None/cost=None、JSON 字符串列），manifest 记录格式。"""
        pytest.importorskip("h5py", reason="HDF5 物化需要 h5py（openems extra）")
        from rfauto.service.dataset_service import (
            HDF5_NAME,
            MANIFEST_NAME,
            materialize_dataset,
            query_dataset,
        )

        rp = materialize_dataset(None, name="pq")
        rh = materialize_dataset(None, name="h5", fmt="hdf5")
        assert rp["ok"] and rh["ok"], (rp.get("errors"), rh.get("errors"))
        assert rh["format"] == "hdf5" and rp["format"] == "parquet"
        assert "parquet" in rp and "hdf5" in rh and "parquet" not in rh
        ddir = runs_env / "runs" / "datasets" / "h5"
        assert (ddir / HDF5_NAME).exists()
        assert not (ddir / "points.parquet").exists()
        manifest = yaml.safe_load((ddir / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert manifest["format"] == "hdf5" and manifest["points_file"] == HDF5_NAME
        assert manifest["n_rows"] == rp["n_rows"] == 5

        qp = query_dataset("pq", limit=100)
        qh = query_dataset("h5", limit=100)
        assert qp["ok"] and qh["ok"], (qp.get("errors"), qh.get("errors"))
        assert qh["format"] == "hdf5" and qp["format"] == "parquet"
        assert qh["columns"] == qp["columns"] and len(qh["columns"]) == 12
        assert _strip_materialized_at(qh["rows"]) == _strip_materialized_at(qp["rows"])
        # 可空列往返：run_c（seed=None、校准样本 cost=None）两格式一致
        calib = [r for r in qh["rows"] if r["source"] == "calibration_samples"]
        assert len(calib) == 2
        assert all(r["seed"] is None and r["cost"] is None for r in calib)
        assert all(isinstance(r["seed"], int) for r in qh["rows"]
                   if r["source"] == "trials")

    def test_hdf5_raw_layout_has_validity_masks(self, runs_env):
        """HDF5 文件级契约：12 列各一数据集 + 可空列 seed/cost 的 __valid__ 掩码；
        掩码与 NULL 语义严格对应。"""
        h5py = pytest.importorskip("h5py")
        from rfauto.service.dataset_service import DATASET_SCHEMA, materialize_dataset

        r = materialize_dataset(None, name="h5", fmt="hdf5")
        assert r["ok"], r.get("errors")
        with h5py.File(r["hdf5"], "r") as f:
            for col, _t in DATASET_SCHEMA:
                assert col in f, col
            assert "__valid__seed" in f and "__valid__cost" in f
            assert "__valid__model" not in f  # string 列无掩码
            sources = [s.decode() if isinstance(s, bytes) else s
                       for s in f["source"][:].tolist()]
            cost_valid = f["__valid__cost"][:].tolist()
            for src, ok in zip(sources, cost_valid, strict=True):
                assert (ok == 0) == (src == "calibration_samples"), (src, ok)

    def test_hdf5_query_where_filters_and_columns(self, runs_env):
        """hdf5 走同一 SQL 管线：where 白名单 + 参数绑定过滤 + 列裁剪 + 注入拒绝。"""
        pytest.importorskip("h5py")
        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        assert materialize_dataset(None, name="h5", fmt="hdf5")["ok"]
        r = query_dataset("h5", where="cost < 0.3", model="mline",
                          columns=["run_id", "cost"])
        assert r["ok"], r.get("errors")
        assert r["columns"] == ["run_id", "cost"]
        assert sorted(row["cost"] for row in r["rows"]) == [0.05, 0.2]
        bad = query_dataset("h5", where="cost < 1; drop table x")
        assert not bad["ok"]
        study = query_dataset("h5", study_name="calib_c")
        assert study["ok"] and study["n_rows"] == 2

    def test_invalid_fmt_rejected_before_any_write(self, runs_env):
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(None, name="bad_fmt", fmt="csv")
        assert not r["ok"] and "fmt" in r["errors"][0]
        assert not (runs_env / "runs" / "datasets" / "bad_fmt").exists()

    def test_missing_h5py_explicit_error(self, runs_env, monkeypatch):
        """缺 h5py 时显式报错并指向 openems extra，不半写目录产物（#139 打桩，
        不真卸包）。"""
        import builtins

        from rfauto.service.dataset_service import materialize_dataset

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "h5py":
                raise ImportError("no h5py")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        r = materialize_dataset(None, name="h5_missing", fmt="hdf5")
        assert not r["ok"]
        assert "h5py" in r["errors"][0] and "openems" in r["errors"][0]
        assert not (runs_env / "runs" / "datasets" / "h5_missing" / "points.h5").exists()

    def test_old_manifest_without_format_reads_parquet(self, runs_env):
        """向后兼容：既有资产 manifest 无 format 键 → 读取侧回退 parquet
        （GT 121 行既有注册表零迁移）。"""
        from rfauto.service.dataset_service import (
            MANIFEST_NAME,
            materialize_dataset,
            query_dataset,
        )

        assert materialize_dataset(None, name="legacy")["ok"]
        mpath = runs_env / "runs" / "datasets" / "legacy" / MANIFEST_NAME
        manifest = yaml.safe_load(mpath.read_text(encoding="utf-8"))
        manifest.pop("format")
        manifest.pop("points_file")
        mpath.write_text(yaml.safe_dump(manifest), encoding="utf-8")
        r = query_dataset("legacy", limit=100)
        assert r["ok"] and r["format"] == "parquet" and r["n_rows"] == 5
