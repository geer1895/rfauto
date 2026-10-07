"""E1 数据集注册表 v2 测试（查询域）。

本文件承载：TestQuery（where 白名单/列裁剪/注入拒绝）、TestPerf
（100k/百万行性能预算；百万行带 solo 标记，被
test_gate_parallel_solo.py 引用）、TestPredicatePushdown（model/
study_name 等值谓词安全下推）。

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

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="数据集注册表 v2 需要 dataset extra（duckdb）")
pytest.importorskip("pyarrow", reason="数据集注册表 v2 需要 dataset extra（pyarrow）")

from tests.unit._dataset_service_helpers import (
    _materialize_all,
    _meta,
    _write_json,
)


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

    @pytest.mark.solo  # xdist+coverage 争用假红（r4 实证）；串行终门/CI 仍执行
    def test_million_rows_materialize_query_budget(self, tmp_path, monkeypatch):
        """100 万行合成集走 materialize/query 主路径计时（E1/薄弱项 4 判据载体）。

        判据口径（续跑计划 §E1/薄弱项 4）：百万行 SQL 查询 <1s——
        round2 审查（R2-B-08 A 类①）确证此前零测试零产物（最大注册集仅
        582 行）。

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
