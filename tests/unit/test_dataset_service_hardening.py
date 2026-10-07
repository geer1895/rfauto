"""E1 数据集注册表 v2 测试（加固域）。

本文件承载：TestReviewHardening（数据栈审查 P1/P2 回归：注入拒绝、
非有限 cost、trial_number null、指纹含 model、路径穿越）与
TestNonfiniteRootCure（E11 未尽②：params/metrics 非有限值整点拦截
与规范 JSON 兜底）。

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

from tests.unit._dataset_service_helpers import (
    _materialize_all,
    _write_json,
)


class TestReviewHardening:
    """审查补强回归（数据栈审查 P1-1/P1-3 + P2-3/P2-4）。"""

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

        # 键存在但为 null：不再炸穿整个物化（审查 P1-3）
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

        # 同泛型参数键、不同 model 的两个 run 不得互删（审查 P2-3）
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
