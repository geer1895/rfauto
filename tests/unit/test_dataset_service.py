"""E1 数据集注册表 v2 测试：Parquet 物化 + DuckDB 直查 + service 查询接口。

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


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _meta(run_id: str, *, model: str, adapter: str = "fake",
          algorithm: str = "tune", study_name: str = "s1",
          seed: int | None = 42, status: str = "done") -> dict:
    return {
        "run_id": run_id, "model": model, "adapter": adapter,
        "algorithm": algorithm, "study_name": study_name, "seed": seed,
        "aedt_version": "fake", "ads_version": "", "git_sha": "abc1234",
        "timestamp": "2026-09-09T00:00:00+00:00", "status": status,
    }


@pytest.fixture
def runs_env(tmp_path, monkeypatch):
    """3+1 个假 run：run_a/run_b 同 study/seed 共享一个相同参数点（验证去重），
    run_c 是 calibration 产物（样本无逐点 cost），run_empty 无任何点级产物。"""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs"
    # run_a：mline，两个 trial
    _write_json(root / "run_a" / "meta.json", _meta("run_a", model="mline"))
    _write_json(root / "run_a" / "trials" / "trial_0.json", {
        "trial_number": 0, "params": {"w_mm": 1.0},
        "metrics": {"s11_db_max_in_band": -10.0}, "cost": 0.05})
    _write_json(root / "run_a" / "trials" / "trial_1.json", {
        "trial_number": 1, "params": {"w_mm": 2.0},
        "metrics": {"s11_db_max_in_band": -20.0}, "cost": 0.5})
    # run_b：同 study/seed；trial_0 与 run_a.trial_0 同参点（应被去重），
    # trial_1 是新点
    _write_json(root / "run_b" / "meta.json", _meta("run_b", model="mline"))
    _write_json(root / "run_b" / "trials" / "trial_0.json", {
        "trial_number": 0, "params": {"w_mm": 1.0},
        "metrics": {"s11_db_max_in_band": -11.0}, "cost": 0.06})
    _write_json(root / "run_b" / "trials" / "trial_1.json", {
        "trial_number": 1, "params": {"w_mm": 3.0},
        "metrics": {"s11_db_max_in_band": -15.0}, "cost": 0.2})
    # run_c：patch_antenna，校准样本（真跑点，无逐点 cost）
    _write_json(root / "run_c" / "meta.json", _meta(
        "run_c", model="patch_antenna", adapter="calibration:openems",
        algorithm="calibration", study_name="calib_c", seed=None))
    _write_json(root / "run_c" / "calibration" / "samples.json", {
        "bounds": {"h_mm": [0.5, 2.5]}, "objectives": [],
        "samples": [
            {"params": {"h_mm": 1.2}, "metrics": {"gain_db": 5.0}},
            {"params": {"h_mm": 2.0}, "metrics": {"gain_db": 6.0}},
        ]})
    # run_empty：只有 meta，无任何点级产物（无产物 run 优雅处理）
    _write_json(root / "run_empty" / "meta.json", _meta("run_empty", model="mline"))
    return tmp_path


def _materialize_all(name: str = "demo"):
    from rfauto.service.dataset_service import materialize_dataset
    return materialize_dataset(None, name=name)


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


class TestQuery:
    def test_filter_and_column_prune(self, runs_env):
        """where 过滤 + 列裁剪：只回 mline 且 cost<0.1 的子集。"""
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        r = query_dataset("demo", where="cost < 0.1 and model = 'mline'",
                          columns=["run_id", "cost", "params_json"])
        assert r["ok"], r.get("errors")
        assert r["n_rows"] == 1 and len(r["rows"]) == 1
        assert r["columns"] == ["run_id", "cost", "params_json"]
        assert r["rows"][0]["run_id"] == "run_a"
        assert r["rows"][0]["cost"] == pytest.approx(0.05)

    def test_no_where_and_limit(self, runs_env):
        """无 where 全量扫 + limit 截断。"""
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        r = query_dataset("demo", limit=3)
        assert r["ok"] and r["n_rows"] == 3
        assert len(r["columns"]) == 12  # DATASET_SCHEMA 全列

    def test_json_extract_on_params(self, runs_env):
        """params_json 保持 JSON 串契约：DuckDB json_extract 可按需展开。"""
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        r = query_dataset(
            "demo",
            where="json_extract_string(params_json, '$.w_mm') = '3.0'")
        assert r["ok"], r.get("errors")
        assert r["n_rows"] == 1 and r["rows"][0]["run_id"] == "run_b"

    def test_illegal_where_rejected(self, runs_env):
        """分号/注释符/反引号/白名单外字符一律拒绝（防注入）。"""
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        for bad in ("cost < 0.1; drop table points",
                    "cost < 0.1 -- evil",
                    "cost /*x*/ < 0.1",
                    "cost < `x`",
                    "cost < 0.1 || model = 'x'",
                    "cost < 0.1\x00",
                    "  "):
            r = query_dataset("demo", where=bad)
            assert not r["ok"], bad
            assert r["errors"], bad

    def test_illegal_columns_rejected(self, runs_env):
        """列名走标识符白名单，逗号注入不进 SQL。"""
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        r = query_dataset("demo", columns=["cost; drop table x"])
        assert not r["ok"]
        r2 = query_dataset("demo", columns=["cost", "model"])
        assert r2["ok"] and r2["columns"] == ["cost", "model"]

    def test_nonexistent_dataset(self, runs_env):
        """查不存在的数据集：ok=False 而非裸异常。"""
        from rfauto.service.dataset_service import query_dataset

        r = query_dataset("nope", where="cost < 0.1")
        assert not r["ok"]
        assert "数据集不存在" in r["errors"][0]

    def test_bad_sql_where_graceful(self, runs_env):
        """白名单内但语义非法的 where（缺列/语法错）：ok=False，统一文案
        且不带引擎原始消息（防存在性 oracle）。"""
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        r = query_dataset("demo", where="nonexistent_col < 1")
        assert not r["ok"]
        assert "查询执行失败" in r["errors"][0]
        assert "where 表达式被拒绝" in r["errors"][0]
        # DuckDB 原始错误以 "Binder Error"/"Catalog Error" 等开头，不得透出
        assert "Error" not in r["errors"][0]

    def test_missing_duckdb_explicit_error(self, runs_env, monkeypatch):
        """缺 duckdb 时显式报错（monkeypatch import 失败，依赖装好也要测此分支）。"""
        monkeypatch.setitem(sys.modules, "duckdb", None)
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        r = query_dataset("demo", where="cost < 0.1")
        assert not r["ok"]
        assert "rfauto[dataset]" in r["errors"][0]


class TestPerf:
    def test_100k_rows_query_under_30s(self, tmp_path, monkeypatch):
        """10 万行合成数据：DataFrame 写 Parquet + DuckDB 过滤查询防退化。

        实测参考（2026-09-09，本地 NVMe + duckdb 1.5.5/pyarrow 25）：写 Parquet
        约 0.06s，谓词查询全流程约 0.02s——阈值 30s 只防数量级退化，不做精确
        断言（CI 抖动规避）。
        """
        import time

        import numpy as np
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq

        monkeypatch.chdir(tmp_path)
        n = 100_000
        rng = np.random.default_rng(7)
        df = pd.DataFrame({
            "run_id": ["perf_run"] * n,
            "model": ["mline"] * n,
            "adapter": ["fake"] * n,
            "algorithm": ["tune"] * n,
            "study_name": ["perf_study"] * n,
            "seed": np.full(n, 42, dtype="int64"),
            "params_json": ['{"w_mm": 1.0}'] * n,
            "metrics_json": ['{"s11_db_max_in_band": -10.0}'] * n,
            "cost": rng.random(n),
            "point_index": np.arange(n, dtype="int64"),
            "source": ["trials"] * n,
            "provenance_json": ['{"git_sha": "perf"}'] * n,
        })
        ds_dir = tmp_path / "runs" / "datasets" / "perf_ds"
        ds_dir.mkdir(parents=True)
        t0 = time.perf_counter()
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                       ds_dir / "points.parquet")
        write_s = time.perf_counter() - t0

        from rfauto.service.dataset_service import query_dataset

        t1 = time.perf_counter()
        r = query_dataset("perf_ds", where="cost < 0.01", columns=["cost"],
                          limit=n)
        elapsed = time.perf_counter() - t1
        assert r["ok"], r.get("errors")
        expected = int((df["cost"] < 0.01).sum())
        assert r["n_rows"] == expected
        assert elapsed < 30.0  # 只防数量级退化；实测 << 1s
        print(f"\n[perf] 100k 行物化写盘 {write_s:.2f}s，"
              f"谓词查询（含 service 校验/JSON 化 {expected} 行）{elapsed:.3f}s")

    def test_million_rows_materialize_query_budget(self, tmp_path, monkeypatch):
        """100 万行合成集走 materialize/query 主路径计时（百万行判据载体）。

        判据口径：百万行 SQL 查询 <1s——
        此前零测试零产物（最大注册集仅 582 行）。

        实测基准（2026-09-18 本机 NVMe，duckdb 1.5.5/pyarrow 25.0.1）：
        materialize 15.9s（单 calibration run 100 万样本过健康门 → 收集 →
        去重 → bounds → Parquet 全主路径）、query 0.055s（谓词 cost<0.01
        全表扫 + ~1 万行 JSON 化）。判据归属查询面：<1s 达标即按方案口径
        写死（18× 余量）；materialize 方案无口径，按实测 ×3 写死 48s
        （#122：口径差异如实注明）。总耗时 ~17s，低于 30s 慢测阈值
        （F-R2-4 口径），留在常态单测门。

        合成方式：单个 calibration run 的 samples.json 承载 100 万样本
        （避免百万 trial 文件的 I/O 放大；samples 列表逐点物化走
        materialize 真实主路径，非 Parquet 直写绕行）。cost 取确定性
        模乘均匀网格，期望匹配数闭式可复算，无随机种子依赖。
        """
        import time

        monkeypatch.chdir(tmp_path)
        n = 1_000_000
        run_dir = tmp_path / "runs" / "perf_big_run"
        calib = run_dir / "calibration"
        calib.mkdir(parents=True)
        _write_json(run_dir / "meta.json", _meta(
            "perf_big_run", model="mline", adapter="calibration:fake",
            algorithm="calibration", study_name="perf_study", seed=42))
        # 97MB 文本一次 join 落盘（逐 dict json.dumps 更慢且内存翻倍）
        parts = [
            f'{{"params": {{"w_mm": {0.5 + i * 1e-6:.9f}}}, "metrics": '
            f'{{"s11_db_max_in_band": {-10.0 - (i % 50) * 0.1:.1f}}}, '
            f'"cost": {(i * 7919 % 100_000) / 100_000:.9f}}}'
            for i in range(n)
        ]
        (calib / "samples.json").write_text(
            '{"bounds": {"w_mm": [0.5, 1.5]}, "objectives": [], '
            '"samples": [' + ",".join(parts) + "]}",
            encoding="utf-8")

        from rfauto.service.dataset_service import (
            materialize_dataset,
            query_dataset,
        )

        t0 = time.perf_counter()
        r = materialize_dataset(None, name="perf_big_ds")
        materialize_s = time.perf_counter() - t0
        assert r["ok"], r.get("errors")
        # w_mm 逐点不同 → 去重指纹零碰撞
        assert r["n_points"] == n and r["n_rows"] == n

        t0 = time.perf_counter()
        q = query_dataset("perf_big_ds", where="cost < 0.01", columns=["cost"],
                          limit=n)
        query_s = time.perf_counter() - t0
        assert q["ok"], q.get("errors")
        # gcd(7919, 1e5)=1 → i*7919 mod 1e5 在 [0,1e6) 恰好铺满 10 个整周期，
        # 每周期 <0.01 的残差恰 1000 个 → 命中行数恒等 10_000（闭式，非统计）
        assert q["n_rows"] == 10_000
        assert query_s < 1.0  # 方案口径「百万行 <1s」；实测 0.055s（18× 余量）
        assert materialize_s < 48.0  # 方案无口径；实测 15.9s ×3（#122 如实）
        print(f"\n[perf] 100 万行 materialize 主路径 {materialize_s:.2f}s，"
              f"谓词查询（含 1 万行 JSON 化）{query_s:.3f}s")


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


class TestHealthGate:
    """G11 门禁接线：unhealthy/suspect run 禁入注册表（§10.17）。"""

    def test_unhealthy_run_excluded(self, runs_env):
        # run_a 塞进无源性违例 S 参数（|S|>1）→ 体检 FAIL → 被拦
        import numpy as np
        import skrf

        from rfauto.service.dataset_service import materialize_dataset

        freq = skrf.Frequency(2.0, 3.0, 5, unit="GHz")
        s = np.full((5, 2, 2), 1.1) + 0.3j   # max|S| ≈ 1.14 > 1.01 无源性违例
        run_dir = runs_env / "runs" / "run_a" / "results"
        run_dir.mkdir(parents=True, exist_ok=True)
        skrf.Network(frequency=freq, s=s, z0=50.0).write_touchstone(
            str(run_dir / "params.s2p"))
        res = materialize_dataset(["run_a", "run_b"], name="gate_ds")
        assert res["ok"]
        assert "run_a" in res["unhealthy_runs"]
        assert res["health_verdicts"]["run_a"] == "unhealthy"
        # run_b（仅 trials，cost 正常）不受牵连
        assert res["health_verdicts"].get("run_b") in ("healthy", "unknown")
        manifest = yaml.safe_load(
            Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["n_unhealthy_skipped"] == 1

    def test_gate_off_includes_everything(self, runs_env):
        import numpy as np
        import skrf

        from rfauto.service.dataset_service import materialize_dataset

        freq = skrf.Frequency(2.0, 3.0, 5, unit="GHz")
        s = np.full((5, 2, 2), 0.9) + 0.2j
        s2p = runs_env / "runs" / "run_a" / "results" / "params.s2p"
        s2p.parent.mkdir(parents=True, exist_ok=True)
        skrf.Network(frequency=freq, s=s, z0=50.0).write_touchstone(str(s2p))
        res = materialize_dataset(["run_a", "run_b"], name="nogate_ds",
                                  health_gate=False)
        assert res["ok"]
        assert res["unhealthy_runs"] == []
        manifest = yaml.safe_load(
            Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["health_gate"] is False

    def test_healthy_run_passes(self, runs_env):
        from rfauto.service.dataset_service import materialize_dataset

        res = materialize_dataset(["run_b"], name="healthy_ds")
        assert res["ok"]
        assert res["health_verdicts"].get("run_b") == "healthy"
        assert res["unhealthy_runs"] == []


# ---------------------------------------------------------------------------
# G11 部分 S 矩阵互易假阳性回归（历史真机案例：6 个 openEMS
# wilkinson/branchline 校准真机 run 被拦：单激励 sparams.csv 只测
# S11/S21/S31/S23 四个元素，S12/S13 置零，旧口径按全矩阵比 |S12−S21|=|S21|≈0.7
# ≥0.01 判互易违背）。修法：解析器给已测掩码，互易性只校两向都独立已测的
# 端口对，一对都没有 → UNKNOWN 不拦；Touchstone 全矩阵不带掩码，真互易破坏
# 仍按 0.01 拦（阈值语义不改）。
# ---------------------------------------------------------------------------

def _write_partial_sparams_csv(run_dir: Path, header: str, rows: list[str],
                               rel: str = "fdtd") -> Path:
    """按 openEMS sparams.csv schema 写部分矩阵产物（模板在 fdtd/ 子目录落盘）。"""
    target = run_dir / rel
    target.mkdir(parents=True, exist_ok=True)
    path = target / "sparams.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def _calib_run_with_samples(root: Path, run_id: str, model: str) -> Path:
    """校准形态 run（meta + calibration/samples.json 两个真跑点）——门放行后
    必须真的成行入库，而不是只在 unhealthy_runs 之外却因无产物被 skipped。"""
    run_dir = root / run_id
    _write_json(run_dir / "meta.json", _meta(
        run_id, model=model, adapter="calibration:openems",
        algorithm="calibration", study_name=f"calib_{run_id}", seed=None))
    _write_json(run_dir / "calibration" / "samples.json", {
        "bounds": {"series_w_mm": [0.5, 2.5]}, "objectives": [],
        "samples": [
            {"params": {"series_w_mm": 1.0}, "metrics": {"s21_db": -3.1}},
            {"params": {"series_w_mm": 1.5}, "metrics": {"s21_db": -3.0}},
        ]})
    return run_dir


# 9 列 = freq + 已测 4 元素（S11/S21/S31/S23）re/im：此前被拦的真机形态
_NINE_COL_HEADER = "freq_hz,re_S11,im_S11,re_S21,im_S21,re_S31,im_S31,re_S23,im_S23"
# 5 列 = freq + 已测 2 元素（S11/S21）re/im：patch 单馈校准形态
_FIVE_COL_HEADER = "freq_hz,re_S11,im_S11,re_S21,im_S21"


def _wilkinson_like_rows(n: int = 5) -> list[str]:
    """wilkinson 量级：|S11|≈0.05、|S21|=|S31|≈0.7（−3dB）、|S23|≈0.03（隔离）。"""
    return [
        f"{2.0e9 + k * 0.25e9:.1f},0.05,0.0,0.7,0.1,0.7,-0.1,0.03,0.0"
        for k in range(n)
    ]


class TestHealthGatePartialMatrixReciprocity:
    """G11 门禁：部分 S 矩阵不构成互易证据（UNKNOWN 放行），全矩阵真破坏仍拦。"""

    def test_nine_col_single_excitation_csv_is_previously_blocked_shape(self, runs_env):
        """自证样本形态：同一部分矩阵不带掩码（旧口径）确实判 FAIL，
        |S12−S21| = |0 − S21| ≈ 0.71 ≥ 0.01——这正是 6 个真机 run 被拦的机制。"""
        import numpy as np

        from rfauto.core.solve_health import solve_health_check
        from rfauto.service.health_service import _parse_sparams_csv_masked

        run_dir = _calib_run_with_samples(runs_env / "runs", "run_wilk", "wilkinson_power_divider")
        path = _write_partial_sparams_csv(run_dir, _NINE_COL_HEADER, _wilkinson_like_rows())
        parsed = _parse_sparams_csv_masked(path)
        assert parsed is not None
        freq_hz, s, mask = parsed
        assert s.shape == (5, 3, 3)
        # 已测掩码只标 csv 列直接来源的 4 个元素；S32:=S23 的互易补齐不算独立测量
        expected_mask = np.zeros((3, 3), dtype=bool)
        expected_mask[0, 0] = expected_mask[1, 0] = expected_mask[2, 0] = expected_mask[1, 2] = True
        assert np.array_equal(mask, expected_mask)
        # 旧口径（无掩码 = 全矩阵已测）：置零 S12 对已测 S21 → 假阳性 FAIL
        old = solve_health_check(freq_hz=freq_hz, s_matrix=s)
        old_rec = next(f for f in old["factors"] if f["factor"] == "reciprocity")
        assert old_rec["status"] == "FAIL"
        assert abs(old_rec["evidence"]["max_asym"] - abs(0.7 + 0.1j)) < 1e-9
        assert old["verdict"] == "unhealthy"
        # 新口径（带掩码）：0/3 对独立已测 → UNKNOWN，不拦
        new = solve_health_check(freq_hz=freq_hz, s_matrix=s, s_measured_mask=mask)
        new_rec = next(f for f in new["factors"] if f["factor"] == "reciprocity")
        assert new_rec["status"] == "UNKNOWN"
        assert new_rec["evidence"]["partial_matrix"] is True
        assert new_rec["evidence"]["n_measured_pairs"] == 0
        assert new_rec["evidence"]["n_pairs_total"] == 3
        assert new["verdict"] == "healthy"

    def test_nine_col_single_excitation_run_passes_gate_and_lands_rows(self, runs_env):
        """端到端：此前被拦形态的校准 run 经 materialize 门 → 放行且真的成行。"""
        from rfauto.service.dataset_service import materialize_dataset
        from rfauto.service.health_service import health_check_run

        run_dir = _calib_run_with_samples(runs_env / "runs", "run_wilk", "wilkinson_power_divider")
        _write_partial_sparams_csv(run_dir, _NINE_COL_HEADER, _wilkinson_like_rows())

        hc = health_check_run("run_wilk")
        statuses = {f["factor"]: f["status"] for f in hc["factors"]}
        assert statuses["reciprocity"] == "UNKNOWN"
        assert statuses["excitation"] == "PASS"
        assert statuses["passivity"] == "PASS"
        assert hc["verdict"] == "healthy"

        res = materialize_dataset(["run_wilk", "run_b"], name="partial_ok")
        assert res["ok"], res.get("errors")
        assert "run_wilk" not in res["unhealthy_runs"]
        assert "run_wilk" not in res["skipped_runs"]
        assert res["health_verdicts"]["run_wilk"] == "healthy"
        manifest = yaml.safe_load(Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["n_unhealthy_skipped"] == 0
        assert {s["run_id"] for s in manifest["source_runs"]} >= {"run_wilk"}
        # run_wilk 两个校准样本 + run_b 两个 trial = 4 点，无重复
        assert res["n_points"] == 4 and res["n_rows"] == 4

    def test_five_col_single_feed_csv_reciprocity_unknown_not_blocked(self, runs_env):
        """2 端口单激励（patch 单馈形态，5 列）：S12/S22 全是补齐值，0/1 对独立已测
        → UNKNOWN 如实（不凑 PASS），门放行。"""
        from rfauto.service.dataset_service import materialize_dataset
        from rfauto.service.health_service import health_check_run

        run_dir = _calib_run_with_samples(runs_env / "runs", "run_patch", "patch_antenna")
        rows = [f"{1.8e9 + k * 0.1e9:.1f},0.3,0.2,0.05,0.01" for k in range(5)]
        _write_partial_sparams_csv(run_dir, _FIVE_COL_HEADER, rows)

        hc = health_check_run("run_patch")
        rec = next(f for f in hc["factors"] if f["factor"] == "reciprocity")
        assert rec["status"] == "UNKNOWN"
        assert rec["evidence"]["n_measured_pairs"] == 0
        assert rec["evidence"]["n_pairs_total"] == 1
        assert hc["verdict"] == "healthy"

        res = materialize_dataset(["run_patch"], name="patch_ok")
        assert res["ok"], res.get("errors")
        assert res["unhealthy_runs"] == []
        assert res["health_verdicts"]["run_patch"] == "healthy"
        assert res["n_rows"] == 2

    def test_full_matrix_reciprocity_violation_still_blocked(self, runs_env):
        """阈值语义不改：Touchstone 全矩阵（HFSS/ADS 导出形态）S12≠S21 差 0.1 ≥ 0.01
        → 互易性 FAIL → unhealthy → 仍拦在注册表之外，即便它带校准样本。"""
        import numpy as np
        import skrf

        from rfauto.service.dataset_service import materialize_dataset
        from rfauto.service.health_service import health_check_run

        run_dir = _calib_run_with_samples(runs_env / "runs", "run_asym", "wilkinson_power_divider")
        freq = skrf.Frequency(2.0, 3.0, 5, unit="GHz")
        s = np.zeros((5, 2, 2), dtype=complex)
        s[:, 0, 0] = s[:, 1, 1] = 0.05
        s[:, 1, 0] = 0.7
        s[:, 0, 1] = 0.6  # |S12−S21| = 0.1 ≥ 0.01：真互易破坏
        (run_dir / "results").mkdir(parents=True, exist_ok=True)
        skrf.Network(frequency=freq, s=s, z0=50.0).write_touchstone(
            str(run_dir / "results" / "params.s2p"))

        hc = health_check_run("run_asym")
        rec = next(f for f in hc["factors"] if f["factor"] == "reciprocity")
        assert rec["status"] == "FAIL"
        assert abs(rec["evidence"]["max_asym"] - 0.1) < 1e-6
        assert "partial_matrix" not in rec["evidence"]  # 全矩阵路径不带掩码
        assert hc["verdict"] == "unhealthy"

        res = materialize_dataset(["run_asym", "run_b"], name="asym_blocked")
        assert res["ok"], res.get("errors")
        assert res["unhealthy_runs"] == ["run_asym"]
        assert res["health_verdicts"]["run_asym"] == "unhealthy"
        manifest = yaml.safe_load(Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["n_unhealthy_skipped"] == 1
        assert {s["run_id"] for s in manifest["source_runs"]} == {"run_b"}

    def test_partial_matrix_measured_pair_violation_still_fails(self, runs_env):
        """掩码只放行未测对；两向都独立已测且违背的对仍 FAIL（阈值 0.01 原样）。
        合成掩码把 (1,2)/(2,1) 都标已测并注入 0.4 非对称——不能因矩阵
        "部分"就放过真破坏。"""
        import numpy as np

        from rfauto.core.solve_health import solve_health_check

        n = 5
        s = np.zeros((n, 3, 3), dtype=complex)
        s[:, 0, 0] = 0.05
        s[:, 1, 0] = s[:, 2, 0] = 0.7
        s[:, 1, 2] = 0.5
        s[:, 2, 1] = 0.9  # |S32−S23| = 0.4
        mask = np.zeros((3, 3), dtype=bool)
        mask[0, 0] = mask[1, 0] = mask[2, 0] = mask[1, 2] = mask[2, 1] = True
        report = solve_health_check(
            freq_hz=np.linspace(2e9, 3e9, n), s_matrix=s, s_measured_mask=mask)
        rec = next(f for f in report["factors"] if f["factor"] == "reciprocity")
        assert rec["status"] == "FAIL"
        assert abs(rec["evidence"]["max_asym"] - 0.4) < 1e-9
        assert rec["evidence"]["n_measured_pairs"] == 1  # 只有 (1,2) 对参与
        assert rec["evidence"]["unmeasured_pairs"] == [[0, 1], [0, 2]]
        assert report["verdict"] == "unhealthy"
        # 同掩码、把 (1,2) 对修成互易 → PASS 且证据标明 1/3 对已校
        s[:, 2, 1] = 0.5
        ok = solve_health_check(
            freq_hz=np.linspace(2e9, 3e9, n), s_matrix=s, s_measured_mask=mask)
        rec_ok = next(f for f in ok["factors"] if f["factor"] == "reciprocity")
        assert rec_ok["status"] == "PASS"
        assert rec_ok["evidence"]["n_measured_pairs"] == 1
        assert rec_ok["evidence"]["n_pairs_total"] == 3

    def test_malformed_mask_falls_back_to_full_matrix_rule(self, runs_env):
        """形状不符的掩码宁可回退全矩阵口径（最多多报 FAIL 让人来看），
        不得静默按"全未测"放过真破坏。"""
        import numpy as np

        from rfauto.core.solve_health import solve_health_check

        s = np.zeros((4, 2, 2), dtype=complex)
        s[:, 1, 0] = 0.7
        s[:, 0, 1] = 0.6  # 真破坏 0.1
        bad_mask = np.zeros((3, 3), dtype=bool)  # 2 端口给了 3×3
        report = solve_health_check(
            freq_hz=np.linspace(2e9, 3e9, 4), s_matrix=s, s_measured_mask=bad_mask)
        rec = next(f for f in report["factors"] if f["factor"] == "reciprocity")
        assert rec["status"] == "FAIL"
        assert "partial_matrix" not in rec["evidence"]

    def test_legacy_parse_sparams_csv_keeps_two_tuple_contract(self, runs_env):
        """calibration 侧（fsv 曲线复算等）按 2 元组解包 _parse_sparams_csv，契约不变。"""
        from rfauto.service.health_service import _parse_sparams_csv

        run_dir = runs_env / "runs" / "legacy"
        path = _write_partial_sparams_csv(run_dir, _NINE_COL_HEADER, _wilkinson_like_rows())
        parsed = _parse_sparams_csv(path)
        assert parsed is not None
        assert len(parsed) == 2
        freq_hz, s = parsed
        assert freq_hz.shape == (5,) and s.shape == (5, 3, 3)


class TestReviewHardening:
    """补强回归（where 注入拒绝 / null 键防御 / 同键不同 model 防互删）。"""

    def test_where_union_injection_rejected(self, runs_env):
        from rfauto.service.dataset_service import _validate_where

        for bad in (
            "1=1) union all select content from read_text('x') where (1=1",
            "cost < 0.1 UNION select 1",
            "cost < 0.1 or read_csv('x')",
            "copy 'x' to 'y'",
        ):
            try:
                _validate_where(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"注入未拦截: {bad}")

    def test_where_from_first_injection_rejected(self, runs_env):
        """复审 P1-2（FROM-first 变体）：无 union/select 的表函数注入
        `1=1) AND EXISTS (FROM glob('../../runs**'))` 曾完整绕过旧黑名单
        ——from/exists/glob/scan 入黑名单后必须拒绝（纵深：scan/glob/
        exists 单独出现同样拒绝）。"""
        from rfauto.service.dataset_service import _validate_where, query_dataset

        payloads = (
            "1=1) AND EXISTS (FROM glob('../../runs**'))",
            "cost < 0.1 AND EXISTS (FROM parquet_scan('../../x.parquet'))",
        )
        for bad in payloads:
            try:
                _validate_where(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"FROM-first 注入未拦截: {bad}")
        # 查询入口同样拒绝（含 payload 片段的错误回执不回传原文）
        _materialize_all("demo")
        for bad in payloads:
            r = query_dataset("demo", where=bad)
            assert not r["ok"], bad
            assert "禁用关键词" in r["errors"][0], bad

    def test_nonfinite_cost_point_skipped_and_counted(self, tmp_path, monkeypatch):
        """cost 非有限（NaN/±Inf）与 params/metrics 同口径：整点拦截并计数，
        不落盘——DuckDB read_parquet 统计路径下 `cost < 0.1` 对 NaN 行求值
        TRUE，落盘会挤占 warm-start collect 的 LIMIT 窗口（实证 P1）。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs" / "run_cost"
        (root / "trials").mkdir(parents=True)
        (root / "meta.json").write_text(json.dumps(
            {"run_id": "run_cost", "model": "mline"}), encoding="utf-8")
        cases = [
            # 0：cost NaN → 整点拦截
            {"trial_number": 0, "params": {"w_mm": 1.0},
             "metrics": {}, "cost": float("nan")},
            # 1：cost +Inf → 整点拦截
            {"trial_number": 1, "params": {"w_mm": 1.5},
             "metrics": {}, "cost": float("inf")},
            # 2：cost 缺失（合法 NULL，校准样本口径）→ 留存
            {"trial_number": 2, "params": {"w_mm": 2.0}, "metrics": {}},
            # 3：合法点 → 留存
            {"trial_number": 3, "params": {"w_mm": 3.0},
             "metrics": {"s11_db_max_in_band": -12.0}, "cost": 0.2},
        ]
        for i, case in enumerate(cases):
            _write_json(root / "trials" / f"trial_{i}.json", case)

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        r = materialize_dataset(["run_cost"], name="cost_ds", health_gate=False)
        assert r["ok"], r.get("errors")
        assert r["n_nonfinite_skipped"] == 2   # NaN + Inf 各计一次
        assert r["n_points"] == 2 and r["n_rows"] == 2
        assert any("cost 非有限" in w for w in r.get("warnings", []))

        q = query_dataset("cost_ds", where="cost < 0.5",
                          columns=["point_index", "cost"])
        assert q["ok"], q.get("errors")
        # `cost < 0.5` 只命中合法点 3——NaN/Inf 行不在盘上，无占位挤占
        assert q["n_rows"] == 1 and q["rows"][0]["point_index"] == 3

        allq = query_dataset("cost_ds", columns=["point_index", "cost"])
        by_idx = {row["point_index"]: row for row in allq["rows"]}
        assert set(by_idx) == {2, 3}
        assert by_idx[2]["cost"] is None       # cost 缺失 → NULL（合法）
        assert by_idx[3]["cost"] == pytest.approx(0.2)

    def test_query_failure_no_engine_message_passthrough(self, runs_env):
        """查询期错误不再透传 DuckDB 原始消息（parquet_scan 变体的
        IO Error 可当存在性 oracle）——统一文案"where 表达式被拒绝"。"""
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        r = query_dataset("demo", where="nonexistent_col < 1")
        assert not r["ok"]
        assert "where 表达式被拒绝" in r["errors"][0]
        assert "sql" in r  # 调用方自身输入的回显保留供归因

    def test_trial_number_none_tolerated(self, runs_env):
        from rfauto.service.dataset_service import materialize_dataset

        # 键存在但为 null：不再炸穿整个物化
        bad = runs_env / "runs" / "run_bad"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "meta.json").write_text(
            json.dumps({"run_id": "run_bad", "model": "mline"}),
            encoding="utf-8")
        (bad / "trials").mkdir(exist_ok=True)
        (bad / "trials" / "trial_0.json").write_text(
            json.dumps({"trial_number": None, "params": {"w_mm": 1.0},
                        "metrics": {}, "cost": 0.1}), encoding="utf-8")
        res = materialize_dataset(["run_bad"], name="nulltrial_ds")
        assert res["ok"]
        assert res["n_rows"] == 1

    def test_fingerprint_includes_model(self, runs_env):
        from rfauto.service.dataset_service import materialize_dataset

        # 同泛型参数键、不同 model 的两个 run 不得互删
        a = runs_env / "runs" / "fp_a"
        b = runs_env / "runs" / "fp_b"
        for d, model in ((a, "mline"), (b, "cpw")):
            d.mkdir(parents=True, exist_ok=True)
            (d / "meta.json").write_text(
                json.dumps({"run_id": d.name, "model": model}),
                encoding="utf-8")
            (d / "trials").mkdir(exist_ok=True)
            (d / "trials" / "trial_0.json").write_text(
                json.dumps({"trial_number": 0, "params": {"h_mm": 0.5},
                            "metrics": {}, "cost": 0.2}), encoding="utf-8")
        res = materialize_dataset(["fp_a", "fp_b"], name="fp_ds")
        assert res["ok"]
        assert res["n_rows"] == 2  # 无去重：model 进指纹

    def test_run_ids_path_traversal_rejected(self, runs_env):
        from rfauto.service.dataset_service import materialize_dataset

        res = materialize_dataset(["../outside"], name="trav_ds")
        assert not res["ok"]


class TestNonfiniteRootCure:
    """E11 未尽②根治：params/metrics 含非有限值（NaN/±Inf）的点在收集侧
    整点拦截并计数，规范外 "NaN"/"Infinity" JSON 字面量不再落盘。"""

    def test_nonfinite_points_skipped_counted_and_never_written(self, tmp_path, monkeypatch):
        """实读 query_dataset 证明：NaN 参数点 / Inf 指标点不在 Parquet，
        计数透出 manifest 与返回值；剩余行 params_json 全部是规范 JSON。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs" / "run_nf"
        (root / "trials").mkdir(parents=True)
        (root / "meta.json").write_text(json.dumps(
            {"run_id": "run_nf", "model": "mline"}), encoding="utf-8")
        cases = [
            # 0：NaN 参数 → 整点拦截
            {"trial_number": 0, "params": {"w_mm": float("nan")},
             "metrics": {}, "cost": 0.1},
            # 1：Infinity 指标 → 整点拦截（含 Inf，不只 NaN）
            {"trial_number": 1, "params": {"w_mm": 1.0},
             "metrics": {"gain_db": float("inf")}, "cost": 0.1},
            # 2：-Infinity 指标 → 整点拦截
            {"trial_number": 2, "params": {"w_mm": 1.5},
             "metrics": {"s11_db": float("-inf")}, "cost": 0.1},
            # 3：合法点 → 留存
            {"trial_number": 3, "params": {"w_mm": 3.0},
             "metrics": {"s11_db_max_in_band": -12.0}, "cost": 0.2},
        ]
        for i, case in enumerate(cases):
            # json.dumps 默认 allow_nan=True → 产出规范外 NaN/Infinity 字面量
            _write_json(root / "trials" / f"trial_{i}.json", case)

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        r = materialize_dataset(["run_nf"], name="nf_ds", health_gate=False)
        assert r["ok"], r.get("errors")
        assert r["n_nonfinite_skipped"] == 3
        assert r["n_points"] == 1 and r["n_rows"] == 1 and r["n_dup"] == 0
        # 跳过原因可归因（warnings 逐点带 tag）
        assert any("非有限值" in w for w in r.get("warnings", []))

        q = query_dataset("nf_ds", columns=[
            "point_index", "params_json", "metrics_json", "cost"])
        assert q["ok"], q.get("errors")
        assert q["n_rows"] == 1
        row = q["rows"][0]
        assert row["point_index"] == 3
        assert row["params_json"] == '{"w_mm":3.0}'

        # 决定性证明：落盘的全部 params_json/metrics_json 都是规范 JSON——
        # 严格解码器遇到 NaN/Infinity/-Infinity 字面量即抛错
        def _reject_const(token: str) -> float:
            raise AssertionError(f"规范外 JSON 字面量落盘: {token}")

        allq = query_dataset("nf_ds", columns=["params_json", "metrics_json"])
        for rr in allq["rows"]:
            json.loads(rr["params_json"], parse_constant=_reject_const)
            json.loads(rr["metrics_json"], parse_constant=_reject_const)

    def test_manifest_records_nonfinite_count(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs" / "run_m"
        (root / "trials").mkdir(parents=True)
        (root / "meta.json").write_text(json.dumps(
            {"run_id": "run_m", "model": "mline"}), encoding="utf-8")
        _write_json(root / "trials" / "trial_0.json", {
            "trial_number": 0, "params": {"w_mm": float("nan")},
            "metrics": {}, "cost": 0.1})
        _write_json(root / "trials" / "trial_1.json", {
            "trial_number": 1, "params": {"w_mm": 1.0},
            "metrics": {}, "cost": 0.2})

        import yaml as _yaml

        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(["run_m"], name="nf_manifest", health_gate=False)
        assert r["ok"]
        manifest = _yaml.safe_load(Path(r["manifest"]).read_text(encoding="utf-8"))
        assert manifest["n_nonfinite_skipped"] == 1
        assert manifest["n_points"] == 1

    def test_dedup_fingerprint_no_nan_collision(self, tmp_path, monkeypatch):
        """旧缺陷回归：两个 NaN 参数点 canonical json 同为 '{"w_mm":NaN}'，
        指纹互撞；根治后 NaN 点在去重前已被整点拦截，不再产生伪去重。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs" / "run_dup"
        (root / "trials").mkdir(parents=True)
        (root / "meta.json").write_text(json.dumps(
            {"run_id": "run_dup", "model": "mline"}), encoding="utf-8")
        for i in range(2):
            _write_json(root / "trials" / f"trial_{i}.json", {
                "trial_number": i, "params": {"w_mm": float("nan")},
                "metrics": {}, "cost": 0.1 + i})
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(["run_dup"], name="nf_dup", health_gate=False)
        assert not r["ok"]  # 无有效点 → 如实 ok=False，不写文件
        assert r["n_points"] == 0 and r["n_nonfinite_skipped"] == 2

    def test_canonical_json_strict_backstop(self):
        """allow_nan=False 兜底：绕过收集拦截的非有限值在序列化处被拒。"""
        from rfauto.service.dataset_service import _canonical_json

        assert _canonical_json({"w_mm": 1.0}) == '{"w_mm":1.0}'
        with pytest.raises(ValueError):
            _canonical_json({"w_mm": float("nan")})
        with pytest.raises(ValueError):
            _canonical_json({"w_mm": float("inf")})


class TestPredicatePushdown:
    """E11 未尽③：model/study_name 等值谓词安全下推 DuckDB（``?`` 值参数
    绑定，值永不拼 SQL），limit 在过滤之后生效。"""

    def test_pushdown_no_missing_samples_with_small_limit(self, tmp_path, monkeypatch):
        """多族数据集：目标族行排在末尾、limit=3 小于总行数 6——
        修复前 LIMIT 先截断 → 目标族 0 样本（漏样本）；修复后全部返回。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        _write_json(root / "r_first" / "meta.json",
                    _meta("r_first", model="patch_antenna"))
        for i in range(4):
            _write_json(root / "r_first" / "trials" / f"trial_{i}.json", {
                "trial_number": i, "params": {"h_mm": float(i)},
                "metrics": {}, "cost": 0.1 + i})
        _write_json(root / "r_last" / "meta.json", _meta("r_last", model="mline"))
        for i in range(2):
            _write_json(root / "r_last" / "trials" / f"trial_{i}.json", {
                "trial_number": i, "params": {"w_mm": float(i)},
                "metrics": {}, "cost": 0.5 + i})

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        m = materialize_dataset(["r_first", "r_last"], name="push_ds",
                                health_gate=False)
        assert m["ok"], m.get("errors")
        assert m["n_rows"] == 6

        r = query_dataset("push_ds", model="mline", limit=3)
        assert r["ok"], r.get("errors")
        assert r["filters"] == {"model": "mline"}
        # 不漏样本：目标族 2 行在 limit=3 内全数返回
        assert r["n_rows"] == 2
        assert {row["run_id"] for row in r["rows"]} == {"r_last"}

    def test_pushdown_model_and_study_combined_and_where(self, runs_env):
        """model+study 双谓词下推，与用户 where 片段 AND 组合。"""
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        r = query_dataset("demo", model="mline", study_name="s1", limit=100)
        assert r["ok"], r.get("errors")
        assert r["filters"] == {"model": "mline", "study_name": "s1"}
        assert r["n_rows"] == 3  # run_a t0/t1 + run_b t1（去重后）
        assert {row["model"] for row in r["rows"]} == {"mline"}

        r2 = query_dataset("demo", model="mline", where="cost < 0.1")
        assert r2["ok"], r2.get("errors")
        assert r2["n_rows"] == 1 and r2["rows"][0]["run_id"] == "run_a"

        r3 = query_dataset("demo", study_name="calib_c")
        assert r3["ok"] and r3["n_rows"] == 2
        assert {row["run_id"] for row in r3["rows"]} == {"run_c"}

    def test_pushdown_value_parameterized_no_injection(self, runs_env):
        """值含 SQL 语法字符：``?`` 参数绑定后按字面量比较——不注入、
        不报错、0 命中（"值不拼 SQL"防御不倒退）。"""
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        for evil in ("x' OR model = 'mline", "mline'; --", "' OR '1'='1"):
            r = query_dataset("demo", model=evil)
            assert r["ok"], (evil, r.get("errors"))
            assert r["n_rows"] == 0, evil
            assert r["filters"] == {"model": evil}

    def test_pushdown_rejects_non_str(self, runs_env):
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        r = query_dataset("demo", model=42)
        assert not r["ok"]
        assert "model" in r["errors"][0]
        r2 = query_dataset("demo", study_name=["s1"])
        assert not r2["ok"]
        assert "study_name" in r2["errors"][0]

    def test_no_filter_kwarg_unchanged(self, runs_env):
        """未传 model/study_name 时行为与旧契约完全一致（无 filters、全列）。"""
        from rfauto.service.dataset_service import query_dataset

        _materialize_all("demo")
        r = query_dataset("demo", limit=3)
        assert r["ok"] and r["n_rows"] == 3
        assert r["filters"] == {}
        assert len(r["columns"]) == 12


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


# ---------------------------------------------------------------------------
# ⑤ 单次 run 产物分支（api.run_once 通道，WP3.4 patch HFSS GT 战役）
# ---------------------------------------------------------------------------

def _write_touchstone(path: Path, n_ports: int) -> None:
    """合成 n 端口无源 Touchstone（skrf 写盘，健康门可读不误拦）：对角
    |S|=0.3，非对角均分 0.5——任一端口数下最大奇异值 0.8 < 1 无源。"""
    import numpy as np
    import skrf

    freq = skrf.Frequency(2.0, 3.0, 5, unit="GHz")
    s = np.zeros((5, n_ports, n_ports), dtype=complex)
    for i in range(n_ports):
        s[:, i, i] = 0.3
    if n_ports > 1:
        off = 0.5 / (n_ports - 1)
        for i in range(n_ports):
            for j in range(n_ports):
                if i != j:
                    s[:, i, j] = off
    path.parent.mkdir(parents=True, exist_ok=True)
    skrf.Network(frequency=freq, s=s, z0=50.0).write_touchstone(str(path))


def _write_run_once_run(
    root: Path,
    run_id: str,
    *,
    status: str = "done",
    with_metrics: bool = True,
    with_snapshot: bool = True,
    with_trials: bool = False,
    touchstone_ports: int | None = None,
) -> None:
    """合成一个 run_once 风格 run：meta + results/metrics.json +
    recipe.snapshot.yaml（含 3 个设计变量与标量元参数），可选再挂 trials；
    ``touchstone_ports=N`` 时再落 results/params.sNp（曲线级关联用例）。"""
    run_dir = root / "runs" / run_id
    _write_json(run_dir / "meta.json", _meta(
        run_id, model="patch_antenna", adapter="hfss", algorithm="",
        study_name="", seed=None, status=status))
    if with_snapshot:
        (run_dir / "recipe.snapshot.yaml").write_text(yaml.safe_dump({
            "model": "patch_antenna", "recipe_version": 1, "schema_version": 1,
            "params": {
                "f0_ghz": {"value": 2.4, "unit": "GHz"},
                "z0_ohm": {"value": 50, "unit": "ohm"},
                "substrate": "rogers4350b_h0.508",
                "patch_len_mm": {"value": 41.5744},
                "patch_w_mm": {"value": 51.3874},
                "feed_offset_mm": {"value": 15.2078},
            },
            "optimization": {"params": {
                "patch_len_mm": {"low": 35.0, "high": 45.0},
                "feed_offset_mm": {"low": 3.0, "high": 20.0},
                "patch_w_mm": {"low": 40.0, "high": 60.0},
            }},
        }, sort_keys=False), encoding="utf-8")
    if with_metrics:
        _write_json(run_dir / "results" / "metrics.json", {
            "run_id": run_id, "schema_version": 1,
            "params": {
                "f0_ghz": 2.4, "z0_ohm": 50,
                "substrate": "rogers4350b_h0.508",
                "patch_len_mm": 41.5744, "patch_w_mm": 51.3874,
                "feed_offset_mm": 15.2078,
            },
            "metrics": {"s11_db_max_in_band": -2.3681,
                        "s11_db_min_in_band": -3.1109},
            "cost": 7.6319,
            "checks": {"passivity_ok": True},
        })
    if with_trials:
        _write_json(run_dir / "trials" / "trial_0.json", {
            "trial_number": 0, "params": {"patch_len_mm": 40.0},
            "metrics": {"s11_db_max_in_band": -9.0}, "cost": 0.1})
    if touchstone_ports is not None:
        _write_touchstone(
            run_dir / "results" / f"params.s{touchstone_ports}p",
            touchstone_ports)


class TestRunOncePoints:
    """⑤ 分支：无 ①—④ 产物的单次 run（status=done + results/metrics.json）
    物化为恰一个点（WP3.4 HFSS GT 战役 36 run 成行的通道）。"""

    def test_run_once_dir_yields_single_gt_point(self, tmp_path, monkeypatch):
        """恰 1 点：adapter/model/params（仅设计变量键）/metrics 正确，
        cost NULL、provenance 带 run_id、健康门不拦、GT 标注计数 +1。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_once")

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        res = materialize_dataset(["ro_once"], name="ro_ds")  # 默认健康门
        assert res["ok"], res.get("errors")
        assert res["n_points"] == 1 and res["n_rows"] == 1 and res["n_dup"] == 0
        assert res["skipped_runs"] == [] and res["unhealthy_runs"] == []

        q = query_dataset("ro_ds")
        assert q["ok"] and q["n_rows"] == 1
        row = q["rows"][0]
        assert row["run_id"] == "ro_once"
        assert row["model"] == "patch_antenna" and row["adapter"] == "hfss"
        assert row["source"] == "run_once" and row["algorithm"] == "run_once"
        assert row["study_name"] == "" and row["seed"] is None
        assert row["cost"] is None  # 可空列契约：单次 run 无统一 cost 语义
        # params 只含 optimization.params 设计变量键（f0_ghz/z0_ohm/substrate
        # 元参数不进 params_json，与注册表既有 GT 行参数列同口径）
        assert row["params_json"] == (
            '{"feed_offset_mm":15.2078,"patch_len_mm":41.5744,'
            '"patch_w_mm":51.3874}')
        assert json.loads(row["metrics_json"]) == {
            "s11_db_max_in_band": -2.3681, "s11_db_min_in_band": -3.1109}
        prov = json.loads(row["provenance_json"])
        assert prov["run_id"] == "ro_once"      # ⑤ 分支 provenance 补带 run_id
        assert prov["git_sha"] == "abc1234"     # 既有 provenance 字段保留
        # 无 Touchstone 产物：曲线级两键不出现（provenance 逐字节不变）
        assert "touchstone_path" not in prov and "n_ports" not in prov

        import yaml as _yaml

        manifest = _yaml.safe_load(
            Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["ground_truth"]["n_gt_rows"] == 1
        assert manifest["ground_truth"]["per_model"] == {"patch_antenna": 1}

    def test_run_once_missing_metrics_skipped_not_blocking(self, tmp_path, monkeypatch):
        """缺 results/metrics.json：跳过并记 collect_errors 透出（#105
        best-effort 不阻塞），同批健康 run 照常成行。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_good")
        _write_run_once_run(tmp_path, "ro_nometrics", with_metrics=False)

        from rfauto.service.dataset_service import materialize_dataset

        res = materialize_dataset(["ro_good", "ro_nometrics"], name="ro_ds2",
                                  health_gate=False)
        assert res["ok"], res.get("errors")
        assert res["n_points"] == 1 and res["n_rows"] == 1
        assert res["skipped_runs"] == ["ro_nometrics"]
        assert any("results/metrics.json" in w
                   for w in res.get("warnings", []))

    def test_run_once_with_trials_not_double_counted(self, tmp_path, monkeypatch):
        """既有 trials 产物时走 ① 不触发 ⑤：同 run 有 metrics.json 也不双计。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_both", with_trials=True)

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        res = materialize_dataset(["ro_both"], name="ro_ds3", health_gate=False)
        assert res["ok"], res.get("errors")
        assert res["n_points"] == 1 and res["n_rows"] == 1
        q = query_dataset("ro_ds3")
        row = q["rows"][0]
        assert row["source"] == "trials" and row["algorithm"] == "tune"
        assert row["params_json"] == '{"patch_len_mm":40.0}'
        assert row["cost"] == pytest.approx(0.1)

    def test_run_once_status_not_done_silently_skipped(self, tmp_path, monkeypatch):
        """status != done（在跑/失败）：即使 metrics.json 在也不收点，
        且不产生警告（非 done run 静默跳过维持旧口径）。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_nr", status="running")

        from rfauto.service.dataset_service import materialize_dataset

        res = materialize_dataset(["ro_nr"], name="ro_ds4", health_gate=False)
        assert not res["ok"]  # 零点：如实 ok=False（既有 no_points 契约）
        assert res["skipped_runs"] == ["ro_nr"]
        # 非 done run 静默跳过：collect_errors 里不出现该 run 的指责
        assert all("ro_nr" not in e for e in res["errors"])

    def test_run_once_missing_snapshot_errors_but_no_crash(self, tmp_path, monkeypatch):
        """recipe.snapshot.yaml 缺失：解析失败记 error 不抛（#105），
        该 run 零点，不阻塞同批其他 run。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_good")
        _write_run_once_run(tmp_path, "ro_nosnap", with_snapshot=False)

        from rfauto.service.dataset_service import materialize_dataset

        res = materialize_dataset(["ro_good", "ro_nosnap"], name="ro_ds5",
                                  health_gate=False)
        assert res["ok"], res.get("errors")
        assert res["n_points"] == 1 and res["n_rows"] == 1
        assert res["skipped_runs"] == ["ro_nosnap"]
        assert any("recipe.snapshot.yaml" in w
                   for w in res.get("warnings", []))


# ---------------------------------------------------------------------------
# ⑤ 分支曲线级关联：provenance 带 touchstone_path / n_ports（数据工厂第一步，
# 曲线级神经算子 A/B 铺路——消费侧不再写死 results/params.s1p）
# ---------------------------------------------------------------------------

class TestRunOnceTouchstoneProvenance:
    """results/params.sNp 在时 ⑤ 点 provenance 多带 touchstone_path（相对
    run 目录 posix 路径）与 n_ports（int）；不在时两键缺席。①—④ 分支不动。"""

    def test_s1p_present_provenance_has_path_and_ports(self, tmp_path, monkeypatch):
        """带 params.s1p 的 run_once（WP3.4 HFSS patch 口径）：默认健康门
        放行（合成网络无源），provenance 带 touchstone_path='results/params.s1p'
        与 n_ports=1（JSON 里是整数不是字符串）。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_s1p", touchstone_ports=1)

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        res = materialize_dataset(["ro_s1p"], name="ts_ds1")  # 默认健康门
        assert res["ok"], res.get("errors")
        assert res["n_rows"] == 1 and res["unhealthy_runs"] == []
        row = query_dataset("ts_ds1")["rows"][0]
        prov = json.loads(row["provenance_json"])
        assert prov["run_id"] == "ro_s1p"
        assert prov["touchstone_path"] == "results/params.s1p"
        assert prov["n_ports"] == 1 and isinstance(prov["n_ports"], int)
        # 相对路径可直接拼回 run 目录命中真实文件（消费侧契约）
        assert (tmp_path / "runs" / "ro_s1p" / prov["touchstone_path"]).is_file()
        # 曲线级键不进 params/metrics 列（只在 provenance）
        assert "touchstone_path" not in row["params_json"]
        assert "touchstone_path" not in row["metrics_json"]

    def test_no_touchstone_keys_absent(self, tmp_path, monkeypatch):
        """不带 sNp 的 run_once：provenance 只有 run_id 等既有键，两个曲线级
        键缺席（与 WP3.4 收尾口径逐字节一致）；同批带 s1p 的 run 不受牵连。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_plain")
        _write_run_once_run(tmp_path, "ro_curve", touchstone_ports=1)

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        res = materialize_dataset(["ro_plain", "ro_curve"], name="ts_ds2",
                                  health_gate=False)
        assert res["ok"], res.get("errors")
        # 两 run 参数点相同（同合成快照）→ 指纹去重只留首个（ro_curve 排序
        # 在前）；用 run_ids 分别物化避免去重干扰逐 run 断言
        by_run: dict[str, dict] = {}
        for rid in ("ro_plain", "ro_curve"):
            r = materialize_dataset([rid], name=f"ts_{rid}", health_gate=False)
            assert r["ok"], r.get("errors")
            by_run[rid] = json.loads(
                query_dataset(f"ts_{rid}")["rows"][0]["provenance_json"])
        assert "touchstone_path" not in by_run["ro_plain"]
        assert "n_ports" not in by_run["ro_plain"]
        assert by_run["ro_plain"]["run_id"] == "ro_plain"
        assert by_run["ro_curve"]["touchstone_path"] == "results/params.s1p"
        assert by_run["ro_curve"]["n_ports"] == 1

    def test_multiport_s2p_s3p_ports_parsed(self, tmp_path, monkeypatch):
        """多端口：params.s2p → n_ports=2、params.s3p → n_ports=3（wilkinson
        3 端口/branchline 4 端口同路径），路径后缀随端口数变。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_2p", touchstone_ports=2)
        _write_run_once_run(tmp_path, "ro_3p", touchstone_ports=3)
        _write_run_once_run(tmp_path, "ro_4p", touchstone_ports=4)

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        for rid, n in (("ro_2p", 2), ("ro_3p", 3), ("ro_4p", 4)):
            r = materialize_dataset([rid], name=f"mp_{rid}", health_gate=False)
            assert r["ok"], r.get("errors")
            prov = json.loads(
                query_dataset(f"mp_{rid}")["rows"][0]["provenance_json"])
            assert prov["touchstone_path"] == f"results/params.s{n}p", rid
            assert prov["n_ports"] == n and isinstance(prov["n_ports"], int)

    def test_run_touchstone_helper_edge_cases(self, tmp_path):
        """helper 直测：大小写不敏感（.S4P）、非 params.* 前缀/带后缀名不认、
        缺 results 目录 → None、多候选按文件名排序取首个（确定性）。"""
        from rfauto.service.dataset_service import _run_touchstone

        # 缺 results 目录
        assert _run_touchstone(tmp_path / "nope") is None
        run = tmp_path / "r"
        (run / "results").mkdir(parents=True)
        # 只有不认的名字：other.s2p / params.s2p.bak / params.sp / 目录同名
        (run / "results" / "other.s2p").write_text("! x", encoding="utf-8")
        (run / "results" / "params.s2p.bak").write_text("! x", encoding="utf-8")
        (run / "results" / "params.sp").write_text("! x", encoding="utf-8")
        (run / "results" / "params.s0p").write_text("! x", encoding="utf-8")
        assert _run_touchstone(run) is None
        # 大小写不敏感：params.S4P → n_ports=4，路径保留原文件名
        (run / "results" / "params.S4P").write_text("! x", encoding="utf-8")
        got = _run_touchstone(run)
        assert got is not None and got[1] == 4
        assert got[0].lower() == "results/params.s4p"
        # 多候选按小写名排序：s0p（端口数 0 不认，跳过）< s1p < s4p → 取 s1p
        # （若按原始名排序 'S'(0x53) 会排在 's'(0x73) 前而错取 S4P）
        (run / "results" / "params.s1p").write_text("! x", encoding="utf-8")
        assert _run_touchstone(run) == ("results/params.s1p", 1)


# ---------------------------------------------------------------------------
# 工作目录形态真机产物导入器（"造了零件没装上车"收口）
# 样本按真机 runs/ 文件构成裁剪：hairpin_calib/kgap2_g0500（calib.json 双参数
# 段）、helix_arbitration（根级多 s1p + 仲裁 JSON s1p 键引用）、
# hfss_marchand_anchor（根级 s4p/s3p + .aedt）、mline_smoke/pt1、
# slotline_port_a/pt1（参数在根级 results JSON design 段）。chdir 隔离（#144）。
# ---------------------------------------------------------------------------

_CSV_HEADER_2P = "freq_hz,re_S11,im_S11,re_S21,im_S21"
_CSV_HEADER_3P = ("freq_hz,re_S11,im_S11,re_S21,im_S21,"
                  "re_S31,im_S31,re_S23,im_S23")


def _write_sparams_csv(path: Path, header: str = _CSV_HEADER_2P,
                       n: int = 5) -> None:
    """合成 openEMS 单激励 sparams.csv：|S11|=0.3、|S21|=0.5（3 端口再补
    S31/S23=0.4）无源，健康门可读不误拦；列数由 header 决定。"""
    n_cols = len(header.split(",")) - 1
    rows = []
    for i in range(n):
        f = 2.0e9 + i * 0.25e9
        vals = [0.3, 0.0, 0.5, 0.0, 0.4, 0.0, 0.4, 0.0][:n_cols]
        rows.append(",".join([f"{f:.1f}", *(f"{v:.6f}" for v in vals)]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _openems_point(point_dir: Path, header: str = _CSV_HEADER_2P) -> None:
    """openEMS 点目录最小构成（真机 pt1/ 形态）：sparams.csv + simulation.py +
    _rfauto_runner.py + fdtd/（空）。"""
    _write_sparams_csv(point_dir / "sparams.csv", header)
    (point_dir / "simulation.py").write_text("# rendered\n", encoding="utf-8")
    (point_dir / "_rfauto_runner.py").write_text("# runner\n", encoding="utf-8")
    (point_dir / "fdtd").mkdir(exist_ok=True)


def _write_hairpin_calib_point(root: Path, workdir: str, pt: str, gap_mm: float,
                               arm_len_mm: float = 36.7799) -> None:
    p = root / workdir / pt
    _openems_point(p)
    _write_json(p / "calib.json", {
        "pt": pt, "f0_ghz": 2.5, "fbw": 0.05, "mesh_mm": 0.4,
        "window_ghz": [2.0, 3.2],
        "design_params": {"order": 2, "w_mm": 1.1117, "arm_len_mm": 35.4676,
                          "arm_gap_mm": 3.0, "gap_mm": 0.7539,
                          "tap_frac": 0.388478},
        "calib_params": {"order": 2, "w_mm": 1.1117, "arm_len_mm": arm_len_mm,
                         "arm_gap_mm": 3.0, "gap_mm": gap_mm, "tap_frac": 0.43},
        "changed": {"gap_mm": [0.7539, gap_mm]},
    })


def _workdir_fixtures(root: Path) -> None:
    """五族工作目录形态最小样本 + 两个反例（有 meta 的标准 run / 无族无曲线目录）。"""
    # hairpin：kgap2_g0500/{calib.json（design_params 校准前 + calib_params 实跑）,
    # sparams.csv}
    _write_hairpin_calib_point(root, "hairpin_calib", "kgap2_g0500", 0.5)
    # helix：根级多曲线，仲裁 JSON 以 s1p 键（绝对路径）显式引用主曲线，
    # geom.nominal 是设计参数；attempt2 无引用 → 跳过
    h = root / "helix_arbitration"
    _write_touchstone(h / "hfss_helix.s1p", 1)
    _write_touchstone(h / "hfss_helix_attempt2_coarse.s1p", 1)
    (h / "hfss_project").mkdir()
    _write_json(h / "hfss_arbitration.json", {
        "stage": "hfss", "ok": True, "solve_s": 123.4, "verdict": "AGREE",
        "geom": {"source": "_ant2_layout('helix')",
                 "nominal": {"helix_d_mm": 3.0, "helix_turns": 2,
                             "helix_pitch_mm": 3.6142, "helix_w_mm": 0.6,
                             "feed_gap_mm": 2.0}},
        "s1p": str(h / "hfss_helix.s1p"),
    })
    # marchand：根级 s4p/s3p + .aedt；同名 stem JSON 带 geometry；b 无归属 → 跳过
    m = root / "hfss_marchand_anchor"
    _write_touchstone(m / "hfss_marchand_anchor_a.s4p", 4)
    _write_touchstone(m / "hfss_marchand_anchor_b.s3p", 3)
    (m / "hfss_marchand_anchor_a.aedt").write_text("", encoding="utf-8")
    _write_json(m / "hfss_marchand_anchor_a.json", {
        "anchor": "a", "verdict": "AGREE",
        "geometry": {"w_mm": 0.62, "s_mm": 0.15, "len_mm": 18.4, "er": 3.66},
    })
    # mline：pt1/ 单曲线目录 + 点级 JSON params
    q = root / "mline_smoke" / "pt1"
    _openems_point(q)
    (q / "port_beta.csv").write_text("freq_hz,beta\n2.0e9,60.0\n",
                                     encoding="utf-8")
    _write_json(q / "mline_point.json",
                {"params": {"w_mm": 1.113, "L_mm": 40.0}, "mesh_mm": 0.4})
    # slotline：pt1/ 摘要无参数段，参数在根级 results JSON 的 design 段（上溯）
    s = root / "slotline_port_a" / "pt1"
    _openems_point(s)
    _write_json(s / "slotline_summary.json",
                {"ok": True, "excite_port": 1, "f0_hz": 2.5e9,
                 "z_mode_ohm": 107.38})
    _write_json(root / "slotline_port_a" / "slotline_port_a_results.json", {
        "route": "A",
        "design": {"f0_ghz": 2.5, "band_ghz": [2.25, 2.75], "w_mm": 1.0,
                   "h_mm": 1.524, "er": 3.66, "line_len_mm_1lambda": 93.4624,
                   "section": {"y_half_mm": 60.0}},
    })
    # 反例①：有 meta.json 的标准 run（走 materialize，不是候选）
    _write_json(root / "20260901_000000_deadbeef" / "meta.json",
                _meta("20260901_000000_deadbeef", model="mline"))
    # 反例②：无族标签且无曲线的目录（runs/datasets 类）——不列
    (root / "datasets").mkdir()
    (root / "datasets" / "readme.txt").write_text("x", encoding="utf-8")


@pytest.fixture
def workdir_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs"
    root.mkdir()
    _workdir_fixtures(root)
    return root


class TestWorkdirDiscover:
    """discover_workdir_candidates：五族入口逐一可发现，反例不列。"""

    def test_five_families_each_discoverable(self, workdir_env):
        from rfauto.service.dataset_service import (
            WORKDIR_FAMILIES,
            discover_workdir_candidates,
        )

        disc = discover_workdir_candidates()
        assert disc["ok"], disc.get("errors")
        assert disc["families"] == list(WORKDIR_FAMILIES)
        assert disc["per_family"] == {
            "hairpin": 1, "helix": 1, "marchand": 1, "mline": 1, "slotline": 1}
        assert disc["n_candidates"] == 5
        assert disc["n_with_meta"] == 1   # 标准 run 不是候选
        by_id = {c["run_id"]: c for c in disc["candidates"]}
        assert set(by_id) == {"hairpin_calib", "helix_arbitration",
                              "hfss_marchand_anchor", "mline_smoke",
                              "slotline_port_a"}
        assert "datasets" not in by_id and "20260901_000000_deadbeef" not in by_id
        # 逐族：族标签/曲线数/引擎/端口数
        assert by_id["hairpin_calib"]["family"] == "hairpin"
        assert by_id["hairpin_calib"]["n_curves"] == 1
        assert by_id["hairpin_calib"]["adapters"] == ["openems"]
        c = by_id["hairpin_calib"]["curves"][0]
        assert c["path"] == "kgap2_g0500/sparams.csv"
        assert c["kind"] == "sparams_csv" and c["n_ports"] == 2
        assert c["source_dir"] == "hairpin_calib/kgap2_g0500"
        assert c["mtime"]  # ISO 时间戳非空
        assert by_id["helix_arbitration"]["family"] == "helix"
        assert by_id["helix_arbitration"]["n_curves"] == 2
        assert by_id["helix_arbitration"]["adapters"] == ["hfss"]
        assert by_id["hfss_marchand_anchor"]["family"] == "marchand"
        kinds = {c["path"]: (c["kind"], c["n_ports"])
                 for c in by_id["hfss_marchand_anchor"]["curves"]}
        assert kinds == {"hfss_marchand_anchor_a.s4p": ("touchstone", 4),
                         "hfss_marchand_anchor_b.s3p": ("touchstone", 3)}
        assert by_id["mline_smoke"]["family"] == "mline"
        assert by_id["slotline_port_a"]["family"] == "slotline"
        assert by_id["slotline_port_a"]["curves"][0]["adapter"] == "openems"

    def test_models_filter_and_invalid_family(self, workdir_env):
        from rfauto.service.dataset_service import discover_workdir_candidates

        disc = discover_workdir_candidates(models=["slotline", "HELIX"])
        assert disc["ok"] and disc["n_candidates"] == 2
        assert {c["run_id"] for c in disc["candidates"]} == {
            "slotline_port_a", "helix_arbitration"}
        bad = discover_workdir_candidates(models=["patch"])
        assert not bad["ok"] and "未知器件族" in bad["errors"][0]
        nodir = discover_workdir_candidates("nope_root")
        assert not nodir["ok"] and "不存在" in nodir["errors"][0]

    def test_unclassified_curve_dir_listed_only_without_filter(self, workdir_env):
        """无族标签但有曲线的目录：models=None 列出（family=""），过滤时不列；
        导入默认五族不收它。"""
        from rfauto.service.dataset_service import (
            WORKDIR_FAMILIES,
            discover_workdir_candidates,
        )

        _openems_point(workdir_env / "misc_probe" / "pt1")
        disc = discover_workdir_candidates()
        by_id = {c["run_id"]: c for c in disc["candidates"]}
        assert by_id["misc_probe"]["family"] == ""
        assert disc["per_family"]["other"] == 1
        disc5 = discover_workdir_candidates(models=list(WORKDIR_FAMILIES))
        assert "misc_probe" not in {c["run_id"] for c in disc5["candidates"]}

    def test_curve_walk_bounded_and_skips_engine_dirs(self, tmp_path):
        """曲线扫描：fdtd/ 内 sparams.csv 收（p0_cross_fidelity 形态）、
        .aedtresults/__pycache__/hfss_project 不下钻、深度 >3 不收、
        端口数 0 不认、大小写不敏感。"""
        from rfauto.service.dataset_service import _scan_workdir_curves

        w = tmp_path / "w"
        _write_sparams_csv(w / "ems_0" / "fdtd" / "sparams.csv")
        (w / "proj.aedtresults").mkdir(parents=True)
        (w / "proj.aedtresults" / "x.s2p").write_text("! x", encoding="utf-8")
        (w / "hfss_project").mkdir()
        (w / "hfss_project" / "y.s2p").write_text("! x", encoding="utf-8")
        (w / "a" / "b" / "c" / "d").mkdir(parents=True)
        (w / "a" / "b" / "c" / "d" / "deep.s2p").write_text("! x", encoding="utf-8")
        (w / "a" / "b" / "c" / "ok.S3P").write_text("! x", encoding="utf-8")
        (w / "zero.s0p").write_text("! x", encoding="utf-8")
        got = [(c["rel"], c["kind"], c["n_ports"]) for c in _scan_workdir_curves(w)]
        assert got == [("a/b/c/ok.S3P", "touchstone", 3),
                       ("ems_0/fdtd/sparams.csv", "sparams_csv", 2)]

    def test_sparams_csv_ports_helper(self, tmp_path):
        from rfauto.service.dataset_service import _sparams_csv_ports

        _write_sparams_csv(tmp_path / "two.csv", _CSV_HEADER_2P)
        _write_sparams_csv(tmp_path / "three.csv", _CSV_HEADER_3P)
        (tmp_path / "junk.csv").write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        assert _sparams_csv_ports(tmp_path / "two.csv") == 2
        assert _sparams_csv_ports(tmp_path / "three.csv") == 3
        assert _sparams_csv_ports(tmp_path / "junk.csv") is None
        assert _sparams_csv_ports(tmp_path / "missing.csv") is None


class TestWorkdirImport:
    """import_workdir_runs：导入后注册表行数增加 + provenance 可查
    （来源目录/时间戳/touchstone 路径/n_ports）。"""

    def test_import_all_five_families_rows_and_provenance(self, workdir_env):
        from rfauto.service.dataset_service import (
            WORKDIR_SOURCE,
            import_workdir_runs,
            query_dataset,
        )

        res = import_workdir_runs(name="wd_all")   # 默认健康门
        assert res["ok"], res.get("errors")
        assert res["importer"] == "workdir"
        assert res["n_candidates"] == 5 and res["n_curves"] == 7
        # helix attempt2（无引用）+ marchand b（无 JSON）无可归属参数 → 跳过如实
        assert res["n_points_skipped"] == 2
        assert res["n_points"] == 5 and res["n_rows"] == 5 and res["n_dup"] == 0
        assert res["unhealthy_points"] == []   # 合成无源曲线不被 G11 误拦
        assert res["skipped_runs"] == [] and res["missing_runs"] == []
        assert res["per_family_rows"] == {
            "hairpin": 1, "helix": 1, "marchand": 1, "mline": 1, "slotline": 1}
        # 全部 openems/hfss 真机引擎 → GT 标注 5/5
        assert res["ground_truth"]["n_gt_rows"] == 5
        assert res["ground_truth"]["per_model"] == res["per_family_rows"]
        skipped_labels = " ".join(res["warnings"])
        assert "helix_arbitration/hfss_helix_attempt2_coarse.s1p" in skipped_labels
        assert "hfss_marchand_anchor/hfss_marchand_anchor_b.s3p" in skipped_labels
        # 单曲线目录健康门 verdict 落 manifest，多曲线根目录 unknown 不拦
        assert res["health_verdicts"]["hairpin_calib/kgap2_g0500"] != "unhealthy"
        assert res["health_verdicts"]["helix_arbitration"] == "unknown"

        q = query_dataset("wd_all", limit=50)
        assert q["ok"] and q["n_rows"] == 5
        rows = {r["run_id"]: r for r in q["rows"]}
        for r in rows.values():
            assert r["source"] == WORKDIR_SOURCE and r["algorithm"] == WORKDIR_SOURCE
            assert r["study_name"] == r["run_id"]   # 战役即 study
            assert r["seed"] is None and r["cost"] is None
            prov = json.loads(r["provenance_json"])
            assert prov["importer"] == "workdir" and prov["run_id"] == r["run_id"]
            assert prov["run_timestamp"].endswith("+00:00")   # 曲线 mtime UTC ISO
            assert prov["materialized_at"] and isinstance(prov["materialized_at"], str)
            assert prov["source_dir"].startswith(r["run_id"])
            assert isinstance(prov["n_ports"], int)
            # 相对路径可直接拼回：runs/<run_id>/<curve_path> 命中真实文件
            assert (workdir_env / r["run_id"] / prov["curve_path"]).is_file()
            assert (workdir_env / r["run_id"] / prov["params_source"]).is_file()

        # hairpin：calib_params（实跑几何）优先于 design_params（校准前设计）
        hp = rows["hairpin_calib"]
        assert hp["model"] == "hairpin" and hp["adapter"] == "openems"
        assert json.loads(hp["params_json"])["gap_mm"] == 0.5
        assert json.loads(hp["params_json"])["arm_len_mm"] == 36.7799
        assert json.loads(hp["metrics_json"]) == {
            "pt": "kgap2_g0500", "f0_ghz": 2.5, "fbw": 0.05, "mesh_mm": 0.4}
        hp_prov = json.loads(hp["provenance_json"])
        assert hp_prov["source_dir"] == "hairpin_calib/kgap2_g0500"
        assert hp_prov["curve_path"] == "kgap2_g0500/sparams.csv"
        assert hp_prov["curve_kind"] == "sparams_csv" and hp_prov["n_ports"] == 2
        assert hp_prov["params_source"] == "kgap2_g0500/calib.json"
        assert hp_prov["params_key"] == "calib_params"
        assert "touchstone_path" not in hp_prov   # csv 曲线无 Touchstone 键

        # helix：多曲线根目录靠仲裁 JSON s1p 键显式引用归属，geom.nominal 参数
        hx = rows["helix_arbitration"]
        assert hx["model"] == "helix" and hx["adapter"] == "hfss"
        assert json.loads(hx["params_json"]) == {
            "feed_gap_mm": 2.0, "helix_d_mm": 3.0, "helix_pitch_mm": 3.6142,
            "helix_turns": 2, "helix_w_mm": 0.6}
        hx_prov = json.loads(hx["provenance_json"])
        assert hx_prov["touchstone_path"] == "hfss_helix.s1p"
        assert hx_prov["curve_kind"] == "touchstone" and hx_prov["n_ports"] == 1
        assert hx_prov["source_dir"] == "helix_arbitration"
        assert hx_prov["params_key"] == "geom.nominal"
        assert json.loads(hx["metrics_json"])["verdict"] == "AGREE"

        # marchand：同名 stem JSON 归属 + .aedt → hfss，s4p → n_ports 4
        mc = rows["hfss_marchand_anchor"]
        assert mc["model"] == "marchand" and mc["adapter"] == "hfss"
        mc_prov = json.loads(mc["provenance_json"])
        assert mc_prov["touchstone_path"] == "hfss_marchand_anchor_a.s4p"
        assert mc_prov["n_ports"] == 4 and mc_prov["params_key"] == "geometry"
        assert json.loads(mc["params_json"])["len_mm"] == 18.4

        # mline：点级 JSON params 键
        ml = rows["mline_smoke"]
        assert ml["model"] == "mline" and ml["adapter"] == "openems"
        assert json.loads(ml["params_json"]) == {"L_mm": 40.0, "w_mm": 1.113}
        assert json.loads(ml["provenance_json"])["params_key"] == "params"

        # slotline：pt1 无参数段 → 上溯到根级 results JSON design 段（只收标量）
        sl = rows["slotline_port_a"]
        assert sl["model"] == "slotline"
        assert json.loads(sl["params_json"]) == {
            "er": 3.66, "f0_ghz": 2.5, "h_mm": 1.524,
            "line_len_mm_1lambda": 93.4624, "w_mm": 1.0}
        sl_prov = json.loads(sl["provenance_json"])
        assert sl_prov["params_source"] == "slotline_port_a_results.json"
        assert sl_prov["params_key"] == "design"
        assert sl_prov["source_dir"] == "slotline_port_a/pt1"

        # manifest：导入器键 + 既有注册表键（list_datasets 可见 = 入口可发现）
        manifest = yaml.safe_load(Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["importer"] == "workdir" and manifest["n_rows"] == 5
        assert manifest["families"] == ["slotline", "hairpin", "marchand",
                                        "mline", "helix"]
        assert manifest["health_gate"] is True
        assert manifest["ground_truth"]["n_gt_rows"] == 5
        from rfauto.service.dataset_insights import list_datasets

        listed = list_datasets(out_dir="runs/datasets")
        assert listed["ok"]
        assert "wd_all" in {d["name"] for d in listed["datasets"]}

    def test_progressive_reimport_grows_rows(self, workdir_env):
        """渐进收集：新战役落盘后重跑同名，注册表行数增加（旧行仍在）。"""
        from rfauto.service.dataset_service import import_workdir_runs, query_dataset

        r1 = import_workdir_runs(name="wd_grow", models=["hairpin"],
                                 health_gate=False)
        assert r1["ok"] and r1["n_rows"] == 1
        _write_hairpin_calib_point(workdir_env, "hairpin_calib", "kgap2_g0800", 0.8)
        _write_hairpin_calib_point(workdir_env, "hairpin_calib2", "pt1", 1.1328)
        r2 = import_workdir_runs(name="wd_grow", models=["hairpin"],
                                 health_gate=False)
        assert r2["ok"] and r2["n_rows"] == 3 and r2["n_candidates"] == 2
        q = query_dataset("wd_grow", limit=50, columns=["run_id", "params_json"])
        gaps = sorted(json.loads(r["params_json"])["gap_mm"] for r in q["rows"])
        assert gaps == [0.5, 0.8, 1.1328]
        manifest = yaml.safe_load(Path(r2["manifest"]).read_text(encoding="utf-8"))
        assert manifest["n_rows"] == 3
        assert [s["run_id"] for s in manifest["source_runs"]] == [
            "hairpin_calib", "hairpin_calib2"]

    def test_dedup_within_workdir_only(self, workdir_env):
        """指纹 (model, study_name=工作目录, seed, params)：同战役内同设计点折叠
        计 n_dup，跨战役同设计各留一行。"""
        from rfauto.service.dataset_service import import_workdir_runs

        _write_hairpin_calib_point(workdir_env, "hairpin_calib", "kgap2_dup", 0.5)
        _write_hairpin_calib_point(workdir_env, "hairpin_other", "pt1", 0.5)
        res = import_workdir_runs(name="wd_dedup", models=["hairpin"],
                                  health_gate=False)
        assert res["ok"]
        assert res["n_points"] == 3 and res["n_rows"] == 2 and res["n_dup"] == 1

    def test_run_ids_filter_missing_and_all_missing(self, workdir_env):
        from rfauto.service.dataset_service import import_workdir_runs

        res = import_workdir_runs(["mline_smoke", "nope", "20260901_000000_deadbeef"],
                                  name="wd_ids", health_gate=False)
        assert res["ok"] and res["n_rows"] == 1
        assert res["missing_runs"] == ["20260901_000000_deadbeef", "nope"]
        bad = import_workdir_runs(["nope"], name="wd_none", health_gate=False)
        assert not bad["ok"] and bad["missing_runs"] == ["nope"]
        none_fam = import_workdir_runs(name="wd_fam", models=["patch"])
        assert not none_fam["ok"] and "未知器件族" in none_fam["errors"][0]
        assert not import_workdir_runs(name="bad name")["ok"]
        assert not import_workdir_runs(name="wd_fmt", fmt="csv")["ok"]

    def test_health_gate_blocks_unhealthy_point(self, workdir_env, monkeypatch):
        """G11 目录级门：verdict=unhealthy 的单曲线目录禁入（同 materialize
        口径），health_gate=False 放行；体检器异常如实降级不拦。"""
        import rfauto.service.health_service as hs
        from rfauto.service.dataset_service import import_workdir_runs

        seen: list[tuple[str, str]] = []

        def fake_hc(run_id, *, runs_dir=None):
            seen.append((run_id, Path(runs_dir).name))
            if run_id == "kgap2_g0500":
                return {"ok": False, "verdict": "unhealthy", "factors": []}
            if run_id == "pt1" and Path(runs_dir).name == "mline_smoke":
                raise RuntimeError("体检器故障")
            return {"ok": True, "verdict": "healthy", "factors": []}

        monkeypatch.setattr(hs, "health_check_run", fake_hc)
        res = import_workdir_runs(name="wd_gate")
        assert res["ok"]
        assert res["unhealthy_points"] == ["hairpin_calib/kgap2_g0500/sparams.csv"]
        assert res["health_verdicts"]["hairpin_calib/kgap2_g0500"] == "unhealthy"
        assert res["health_verdicts"]["mline_smoke/pt1"] == "unknown"
        assert any("health_gate" in w and "体检器故障" in w
                   for w in res["warnings"])
        assert res["n_rows"] == 4 and "hairpin" not in res["per_family_rows"]
        # 体检按单曲线目录调用（run_id=目录名, runs_dir=父目录）；多曲线根目录不调
        assert ("kgap2_g0500", "hairpin_calib") in seen
        assert all(rid not in ("helix_arbitration", "hfss_marchand_anchor")
                   for rid, _ in seen)
        off = import_workdir_runs(name="wd_nogate", health_gate=False)
        assert off["ok"] and off["n_rows"] == 5 and off["health_verdicts"] == {}

    def test_ambiguous_multi_curve_dir_skipped_not_guessed(self, tmp_path, monkeypatch):
        """多曲线目录无引用/同名 JSON → 不猜归属（#122）；祖先级引用按"相对该级
        目录的路径"精确匹配，pt1 的引用不会漏给 pt2。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        w = root / "mline_multi"
        _write_sparams_csv(w / "pt1" / "sparams.csv")
        _write_sparams_csv(w / "pt2" / "sparams.csv")
        _write_touchstone(w / "var_a.s2p", 2)
        _write_touchstone(w / "var_b.s2p", 2)
        _write_json(w / "summary.json", {
            "params": {"w_mm": 1.0},
            "curves": ["pt1/sparams.csv"],   # 只引用 pt1
        })
        from rfauto.service.dataset_service import import_workdir_runs, query_dataset

        res = import_workdir_runs(name="wd_amb", health_gate=False)
        assert res["ok"], res.get("errors")
        # pt1：祖先 summary.json 以 "pt1/sparams.csv" 显式引用 → 成行；
        # pt2：单曲线目录上溯认无引用 JSON（同 summary.json params）→ 与 pt1 同参
        #   指纹折叠 n_dup=1（引用匹配按相对该级目录的路径，pt1 的引用不漏给 pt2，
        #   pt2 成行走的是单曲线规则而非误匹配）；
        # 根级 var_a/var_b：多曲线目录无引用/同名 JSON → 不猜，跳过 2
        assert res["n_points_skipped"] == 2 and res["n_points"] == 2
        assert res["n_rows"] == 1 and res["n_dup"] == 1
        row = query_dataset("wd_amb")["rows"][0]
        assert json.loads(row["provenance_json"])["curve_path"] == "pt1/sparams.csv"
        assert any("var_a.s2p" in w for w in res["warnings"])
        assert any("var_b.s2p" in w for w in res["warnings"])

    def test_nonfinite_params_skipped_metrics_key_dropped(self, tmp_path, monkeypatch):
        """params 非有限 → 整点跳过计数；metrics 非有限 → 只剔键、点保留。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        p_bad = root / "hairpin_nan" / "pt_bad"
        _openems_point(p_bad)
        (p_bad / "pt.json").write_text(
            '{"params": {"w_mm": NaN, "gap_mm": 0.5}, "f0_ghz": 2.5}',
            encoding="utf-8")
        p_ok = root / "hairpin_nan" / "pt_ok"
        _openems_point(p_ok)
        (p_ok / "pt.json").write_text(
            '{"params": {"w_mm": 1.0, "gap_mm": 0.5}, "solve_s": Infinity, "f0_ghz": 2.5}',
            encoding="utf-8")
        from rfauto.service.dataset_service import import_workdir_runs, query_dataset

        res = import_workdir_runs(name="wd_nan", health_gate=False)
        assert res["ok"], res.get("errors")
        assert res["n_nonfinite_skipped"] == 1 and res["n_rows"] == 1
        assert any("pt_bad" in w and "非有限" in w for w in res["warnings"])
        assert any("pt_ok" in w and "solve_s" in w for w in res["warnings"])
        row = query_dataset("wd_nan")["rows"][0]
        assert json.loads(row["metrics_json"]) == {"f0_ghz": 2.5}
        assert "NaN" not in row["params_json"] and "Infinity" not in row["metrics_json"]

    def test_hdf5_format_roundtrip(self, workdir_env):
        pytest.importorskip("h5py", reason="hdf5 格式需要 h5py")
        from rfauto.service.dataset_service import import_workdir_runs, query_dataset

        res = import_workdir_runs(name="wd_h5", models=["mline"], fmt="hdf5",
                                  health_gate=False)
        assert res["ok"] and res["format"] == "hdf5" and res["hdf5"].endswith("points.h5")
        q = query_dataset("wd_h5")
        assert q["ok"] and q["n_rows"] == 1 and q["format"] == "hdf5"
        assert json.loads(q["rows"][0]["provenance_json"])["n_ports"] == 2

    def test_empty_root_and_no_rows_envelopes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs").mkdir()
        from rfauto.service.dataset_service import import_workdir_runs

        res = import_workdir_runs(name="wd_empty")
        assert not res["ok"] and "工作目录形态产物" in res["errors"][0]
        # 有候选但零可归属点：ok=False + 计数字段齐全
        _write_sparams_csv(tmp_path / "runs" / "mline_bare" / "pt1" / "sparams.csv")
        res2 = import_workdir_runs(name="wd_zero", health_gate=False)
        assert not res2["ok"] and res2["n_candidates"] == 1
        assert res2["n_points_skipped"] == 1 and res2["skipped_runs"] == ["mline_bare"]


class TestWorkdirShells:
    """CLI 薄壳冒烟：datasets discover-workdir / import-workdir 直连 service。"""

    def test_cli_discover_and_import(self, workdir_env):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        r1 = runner.invoke(app, ["datasets", "discover-workdir", "--models", "hairpin,helix"])
        assert r1.exit_code == 0, r1.output
        assert '"n_candidates": 2' in r1.output
        r2 = runner.invoke(app, ["datasets", "import-workdir", "--name", "cli_wd",
                                 "--no-health-gate"])
        assert r2.exit_code == 0, r2.output
        assert "工作目录产物已导入: cli_wd" in r2.output
        assert "无可归属参数跳过: 2" in r2.output
        r3 = runner.invoke(app, ["datasets", "query", "cli_wd",
                                 "--where", "model = 'helix'",
                                 "--columns", "run_id,model"])
        assert r3.exit_code == 0, r3.output
        assert "helix_arbitration" in r3.output
        bad = runner.invoke(app, ["datasets", "import-workdir", "--name", "x",
                                  "--models", "patch"])
        assert bad.exit_code == 1 and "导入失败" in bad.output
        bad2 = runner.invoke(app, ["datasets", "discover-workdir", "--runs-root", "nope"])
        assert bad2.exit_code == 1 and "发现失败" in bad2.output


class TestRegistrySync:
    """R2-D-03 ⑤：数据集物化回写注册表（默认关零行为变化，best-effort #105）。

    autouse chdir + 清双 env（#144，同 test_registry_db 模板）；开关解析链
    =显式实参 > settings db.dataset_registry_sync > False。
    """

    @pytest.fixture(autouse=True)
    def _isolated_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("RFAUTO_REGISTRY_DB", raising=False)
        monkeypatch.delenv("RFAUTO_JOB_REGISTRY_DB", raising=False)
        yield

    @staticmethod
    def _seed_one_run(tmp_path: Path) -> None:
        _write_json(tmp_path / "runs" / "r1" / "meta.json",
                    _meta("r1", model="mline"))
        _write_json(tmp_path / "runs" / "r1" / "trials" / "trial_0.json", {
            "trial_number": 0, "params": {"w_mm": 1.0},
            "metrics": {"s11_db_max_in_band": -10.0}, "cost": 0.05})

    # -- materialize_dataset ------------------------------------------------

    def test_materialize_default_off_no_db_file(self, tmp_path):
        self._seed_one_run(tmp_path)
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(None, name="sync_off")
        assert r["ok"] is True
        assert r["registry_sync"] is False
        assert not (tmp_path / "runs" / "registry.sqlite").exists()

    def test_materialize_explicit_on_row_queryable(self, tmp_path):
        self._seed_one_run(tmp_path)
        from rfauto.service import db_service
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(None, name="sync_on", registry_sync=True)
        assert r["ok"] is True and r["registry_sync"] is True
        out = db_service.db_query(
            "SELECT name, n_rows, visibility, format FROM datasets ORDER BY name")
        assert out["ok"] is True
        assert out["rows"] == [["sync_on", 1, "private", "parquet"]]

    def test_materialize_settings_yaml_enables_without_explicit(self, tmp_path):
        self._seed_one_run(tmp_path)
        (tmp_path / "configs").mkdir()
        (tmp_path / "configs" / "settings.yaml").write_text(
            "db:\n  dataset_registry_sync: true\n", encoding="utf-8")
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(None, name="sync_yaml")
        assert r["ok"] is True and r["registry_sync"] is True

    def test_materialize_upsert_failure_does_not_block(self, tmp_path, monkeypatch):
        self._seed_one_run(tmp_path)
        from rfauto.infra import db as db_mod
        from rfauto.service.dataset_service import materialize_dataset

        def _boom(self, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(db_mod.RegistryDB, "upsert_dataset", _boom)
        r = materialize_dataset(None, name="sync_fail", registry_sync=True)
        assert r["ok"] is True
        assert r["registry_sync"] is False
        assert any("注册表回写失败" in w for w in r.get("warnings", []))
        # 物化产物不受影响
        assert (tmp_path / "runs" / "datasets" / "sync_fail"
                / "points.parquet").exists()

    def test_visibility_flip_syncs_registry_and_manifest(self, tmp_path):
        self._seed_one_run(tmp_path)
        # visibility 回写无显式实参入口，开关走 settings 键
        (tmp_path / "configs").mkdir()
        (tmp_path / "configs" / "settings.yaml").write_text(
            "db:\n  dataset_registry_sync: true\n", encoding="utf-8")
        from rfauto.infra.db import RegistryDB
        from rfauto.service.dataset_insights import set_dataset_visibility
        from rfauto.service.dataset_service import materialize_dataset

        assert materialize_dataset(None, name="sync_vis", registry_sync=True)["ok"]
        r = set_dataset_visibility("sync_vis", "public")
        assert r["ok"] is True and r["registry_sync"] is True
        db = RegistryDB()
        try:
            assert db.get_dataset("sync_vis")["visibility"] == "public"
        finally:
            db.close()
        manifest = yaml.safe_load(
            (tmp_path / "runs" / "datasets" / "sync_vis" / "dataset_manifest.yaml")
            .read_text(encoding="utf-8"))
        assert manifest["visibility"] == "public"

    def test_visibility_default_off_no_db_file(self, tmp_path):
        self._seed_one_run(tmp_path)
        from rfauto.service.dataset_insights import set_dataset_visibility
        from rfauto.service.dataset_service import materialize_dataset

        assert materialize_dataset(None, name="vis_off")["ok"]
        r = set_dataset_visibility("vis_off", "public")
        assert r["ok"] is True and r["registry_sync"] is False
        assert not (tmp_path / "runs" / "registry.sqlite").exists()

    # -- import_workdir_runs（同型四例） ------------------------------------

    def test_import_default_off_no_db_file(self, workdir_env, tmp_path):
        from rfauto.service.dataset_service import import_workdir_runs

        r = import_workdir_runs(name="wd_off", health_gate=False)
        assert r["ok"] is True
        assert r["registry_sync"] is False
        assert not (tmp_path / "runs" / "registry.sqlite").exists()

    def test_import_explicit_on_row_queryable(self, workdir_env):
        from rfauto.service import db_service
        from rfauto.service.dataset_service import import_workdir_runs

        r = import_workdir_runs(name="wd_on", health_gate=False, registry_sync=True)
        assert r["ok"] is True and r["registry_sync"] is True
        out = db_service.db_query("SELECT name, visibility FROM datasets")
        assert out["ok"] is True
        assert out["rows"] == [["wd_on", "private"]]

    def test_import_settings_yaml_enables_without_explicit(self, workdir_env, tmp_path):
        (tmp_path / "configs").mkdir()
        (tmp_path / "configs" / "settings.yaml").write_text(
            "db:\n  dataset_registry_sync: true\n", encoding="utf-8")
        from rfauto.service.dataset_service import import_workdir_runs

        r = import_workdir_runs(name="wd_yaml", health_gate=False)
        assert r["ok"] is True and r["registry_sync"] is True

    def test_import_upsert_failure_does_not_block(self, workdir_env, monkeypatch):
        from rfauto.infra import db as db_mod
        from rfauto.service.dataset_service import import_workdir_runs

        def _boom(self, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(db_mod.RegistryDB, "upsert_dataset", _boom)
        r = import_workdir_runs(name="wd_fail", health_gate=False, registry_sync=True)
        assert r["ok"] is True
        assert r["registry_sync"] is False
        assert any("注册表回写失败" in w for w in r.get("warnings", []))

    # -- CLI 三态（#277：bool|None 选项，缺省不得被当显式 False 压掉配置） --

    def test_cli_registry_sync_three_states(self, tmp_path):
        self._seed_one_run(tmp_path)
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        from rfauto.service import db_service

        runner = CliRunner()
        # 显式 --registry-sync：默认关配置下也入库
        r1 = runner.invoke(app, ["datasets", "materialize",
                                 "--name", "cli_sync_on", "--registry-sync"])
        assert r1.exit_code == 0, r1.output
        out = db_service.db_query("SELECT name, visibility FROM datasets")
        assert out["rows"] == [["cli_sync_on", "private"]]

        # 配置开 + 显式 --no-registry-sync：压过配置不入库
        (tmp_path / "configs").mkdir()
        (tmp_path / "configs" / "settings.yaml").write_text(
            "db:\n  dataset_registry_sync: true\n", encoding="utf-8")
        r2 = runner.invoke(app, ["datasets", "materialize",
                                 "--name", "cli_sync_off", "--no-registry-sync"])
        assert r2.exit_code == 0, r2.output
        out2 = db_service.db_query("SELECT name FROM datasets ORDER BY name")
        assert [row[0] for row in out2["rows"]] == ["cli_sync_on"]

        # 缺省（无 flag）读配置 true → 入库（三态关键档）
        r3 = runner.invoke(app, ["datasets", "materialize",
                                 "--name", "cli_sync_yaml"])
        assert r3.exit_code == 0, r3.output
        out3 = db_service.db_query("SELECT name FROM datasets ORDER BY name")
        assert [row[0] for row in out3["rows"]] == ["cli_sync_on", "cli_sync_yaml"]
