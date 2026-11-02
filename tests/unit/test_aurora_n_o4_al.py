"""aurora_n O4 active_learning 运行时入口接线回归钉（2026-10-31）。

O4（runs/aurora_n/zero_wiring/REGISTRY.md 第二节）：service/active_learning
的 T-N9 宿主 propose_next_points 零运行时调用方（旧面存量欠账——仅测试+
一次性探针脚本消费）。本席落持久 JSON 门 service/al_service.py + CLI 叶
``rfauto al propose``，本件钉其上：

- 缺省等价钉（红线"既有路径零改动"）：legacy 模式（acquisition=None）=
  宿主 propose_next_points 整体转发，samples_path 形态信封逐位一致；
- 三族旋钮 e2e：--acquisition lcb/ucb/ei/sigma（置信界族/EI/纯 σ 三族
  四档）各端到端一跑，提议点落界内、分数降序；
- registry σ 源 + conformal_fallback：native/共形包装两档 sigma_source
  如实标注 + 原生 σ 缺席不开 fallback 的显式负例（T-N9 AL-2 契约）；
- 确定性钉：同 seed 两次调用（service 与 CLI --json 两面）逐位一致；
- 负例：来源未给/多给/不存在、空样本、零数值指标（数据集缺 metric）、
  run 缺 trials、未知采集名/来源——全部 error_envelope 显式报错；
- CLI 薄壳钉：--json 成功+失败同构信封（#24 棘轮家法）+ 人读面渲染。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.service.al_service import (
    _bounds_from_samples,
    al_propose,
    load_al_samples,
)

SAMPLES_N = 25
BOUNDS = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}


def _synthetic_samples(n: int = SAMPLES_N, seed: int = 3) -> list[dict]:
    """合成 2 参数 1 指标样本集（同 test_active_learning 词典结构）。"""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        p = {"arm_len_mm": float(rng.uniform(*BOUNDS["arm_len_mm"])),
             "series_w_mm": float(rng.uniform(*BOUNDS["series_w_mm"]))}
        s11 = (-20.0 + 5.0 * (p["arm_len_mm"] - 20.0) ** 2
               + 10.0 * (p["series_w_mm"] - 0.35) ** 2)
        out.append({"params": p,
                    "metrics": {"s11_db_max_in_band": float(s11)}})
    return out


@pytest.fixture
def samples_file(tmp_path):
    """samples.json（bounds/samples schema，与 certify 公差盒同款）。"""
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(
        {"bounds": BOUNDS, "objectives": [], "samples": _synthetic_samples()}),
        encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """cwd 隔离单源委托（tests/conftest.py::isolated，#144 家法）。"""
    yield


def _make_dataset(tmp_path: Path, name: str, rows: list[dict]) -> Path:
    """裸目录物化数据集（points.parquet，无 manifest——query_dataset 裸目录
    惯例可查；列集 params_json/metrics_json/run_id 为 al_service 消费面）。"""
    import duckdb

    ds_dir = tmp_path / "datasets" / name
    ds_dir.mkdir(parents=True)
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE t(run_id VARCHAR, params_json VARCHAR, "
                    "metrics_json VARCHAR)")
        for row in rows:
            con.execute("INSERT INTO t VALUES (?, ?, ?)",
                        [row["run_id"],
                         json.dumps(row.get("params") or {}),
                         json.dumps(row.get("metrics") or {})])
        con.execute(f"COPY t TO '{(ds_dir / 'points.parquet').as_posix()}' "
                    "(FORMAT PARQUET)")
    finally:
        con.close()
    return ds_dir


# ── 缺省等价（legacy 转发宿主，逐位） ────────────────────────────────────────


class TestLegacyEquivalence:
    def test_samples_path_mode_bitwise_host_equivalence(self, samples_file):
        from rfauto.service.active_learning import propose_next_points

        host = propose_next_points(samples_file, k=4, n_candidates=300)
        svc = al_propose(samples_file, k=4, n_candidates=300)
        assert svc["ok"] and host["ok"]
        assert json.dumps(svc, sort_keys=True) == json.dumps(
            host, sort_keys=True), "legacy 模式必须逐位等价宿主信封"

    def test_conformal_fallback_default_false_matches_host(self, samples_file):
        from rfauto.service.active_learning import propose_next_points

        host = propose_next_points(samples_file, k=3, kind="poly_ridge",
                                   n_candidates=200)
        svc = al_propose(samples_file, k=3, kind="poly_ridge",
                         n_candidates=200)
        assert json.dumps(svc, sort_keys=True) == json.dumps(
            host, sort_keys=True)
        # poly_ridge 无原生 σ 且缺省不开 fallback → 提议空但 ok（宿主历史行为）
        assert svc["proposed"] == []

    def test_legacy_conformal_fallback_flag_reaches_host(self, samples_file):
        svc = al_propose(samples_file, k=3, kind="poly_ridge",
                         n_candidates=200, conformal_fallback=True)
        assert svc["ok"]
        assert len(svc["proposed"]) == 3

    def test_dataset_mode_legacy_shape(self, tmp_path):
        rows = [{"run_id": f"r{i}", "params": s["params"],
                 "metrics": s["metrics"]}
                for i, s in enumerate(_synthetic_samples())]
        _make_dataset(tmp_path, "al_o4_ds", rows)
        # 数据集形态 bounds=观测范围推导——等价对照 samples.json 用同款
        # 推导 bounds（同样本同域同 seed → 提议逐位一致）
        derived = _bounds_from_samples(_synthetic_samples())
        twin = tmp_path / "twin_samples.json"
        twin.write_text(json.dumps(
            {"bounds": derived, "objectives": [],
             "samples": _synthetic_samples()}), encoding="utf-8")
        host = al_propose(str(twin), k=3, n_candidates=300)
        svc = al_propose(dataset="al_o4_ds", out_dir=tmp_path / "datasets",
                         k=3, n_candidates=300)
        assert svc["ok"]
        assert svc["sample_source"] == "dataset"
        assert svc["samples_path"] == "dataset:al_o4_ds"
        assert svc["bounds"] == derived
        assert svc["proposed"] == host["proposed"]

    def test_run_mode_legacy(self, tmp_path):
        trials = tmp_path / "runs" / "20261031_000000_o4run" / "trials"
        trials.mkdir(parents=True)
        for i, s in enumerate(_synthetic_samples()):
            (trials / f"trial_{i}.json").write_text(json.dumps(
                {"trial_number": i, "params": s["params"],
                 "metrics": s["metrics"], "cost": None}), encoding="utf-8")
        derived = _bounds_from_samples(_synthetic_samples())
        twin = tmp_path / "twin_samples.json"
        twin.write_text(json.dumps(
            {"bounds": derived, "objectives": [],
             "samples": _synthetic_samples()}), encoding="utf-8")
        host = al_propose(str(twin), k=3, n_candidates=300)
        svc = al_propose(
            run="20261031_000000_o4run", runs_root=tmp_path / "runs",
            k=3, n_candidates=300)
        assert svc["ok"]
        assert svc["sample_source"] == "run"
        assert svc["samples_path"] == "run:20261031_000000_o4run"
        assert svc["proposed"] == host["proposed"]


# ── 三族旋钮端到端（T-N9 采集三族四档） ─────────────────────────────────────


class TestAcquisitionFamilies:
    @pytest.mark.parametrize("acquisition", ["lcb", "ucb", "ei", "sigma"])
    def test_family_end_to_end(self, samples_file, acquisition):
        r = al_propose(samples_file, k=4, acquisition=acquisition,
                       n_candidates=300)
        assert r["ok"], r.get("errors")
        assert r["mode"] == "acquisition"
        assert r["acquisition"] == acquisition
        assert len(r["proposed"]) == 4
        for item in r["proposed"]:
            p = item["params"]
            assert 18.0 <= p["arm_len_mm"] <= 23.0
            assert 0.25 <= p["series_w_mm"] <= 0.45
            assert "mean" in item and "sigma" in item
        scores = [i["score"] for i in r["proposed"]]
        assert scores == sorted(scores, reverse=True)

    def test_registry_source_native_sigma(self, samples_file):
        r = al_propose(samples_file, k=3, acquisition="sigma",
                       source="registry", kind="nn", n_candidates=200)
        assert r["ok"], r.get("errors")
        assert r["sigma_source"] == "native"

    def test_registry_conformal_fallback_labeled(self, samples_file):
        """poly_ridge 无原生 σ → 共形包装回退 + sigma_source 如实标注。"""
        r = al_propose(samples_file, k=3, acquisition="sigma",
                       source="registry", kind="poly_ridge",
                       conformal_fallback=True, n_candidates=200)
        assert r["ok"], r.get("errors")
        assert r["sigma_source"] == "conformal_interval"
        assert len(r["proposed"]) == 3

    def test_acquisition_deterministic_bitwise(self, samples_file):
        a = al_propose(samples_file, k=4, acquisition="ucb", n_candidates=300)
        b = al_propose(samples_file, k=4, acquisition="ucb", n_candidates=300)
        assert json.dumps(a, sort_keys=True) == json.dumps(
            b, sort_keys=True)

    def test_sigma_family_matches_legacy_semantics(self, samples_file):
        """sigma 采集 + registry nn 来源 ≡ legacy σ 求和（同模型同候选池）。"""
        legacy = al_propose(samples_file, k=3, n_candidates=300)
        sigma = al_propose(samples_file, k=3, n_candidates=300,
                           acquisition="sigma", source="registry", kind="nn")
        assert legacy["ok"] and sigma["ok"]
        assert [p["params"] for p in legacy["proposed"]] \
            == [p["params"] for p in sigma["proposed"]]


# ── 负例（显式 error_envelope，不抛裸 traceback） ───────────────────────────


class TestNegatives:
    def test_no_source_given(self):
        r = al_propose()
        assert not r["ok"] and r["errors"]

    def test_two_sources_given(self, samples_file, tmp_path):
        r = al_propose(samples_file, dataset="whatever",
                       out_dir=tmp_path / "datasets")
        assert not r["ok"] and "互斥" in r["errors"][0]

    def test_samples_file_missing(self, tmp_path):
        r = al_propose(str(tmp_path / "nope.json"))
        assert not r["ok"]

    def test_legacy_insufficient_samples(self, tmp_path):
        path = tmp_path / "small.json"
        path.write_text(json.dumps(
            {"bounds": {"a": [0, 1]}, "samples": [
                {"params": {"a": 0.5}, "metrics": {"f": 1.0}}]}),
            encoding="utf-8")
        r = al_propose(str(path))
        assert not r["ok"] and any("≥5" in e for e in r["errors"])

    def test_dataset_missing(self, tmp_path):
        r = al_propose(dataset="al_o4_absent", out_dir=tmp_path / "datasets")
        assert not r["ok"] and r["errors"]

    def test_dataset_rows_without_metrics(self, tmp_path):
        """数据集缺 metric（metrics_json 空）→ 显式零数值指标负例。"""
        rows = [{"run_id": f"r{i}", "params": {"w_mm": 0.5 + i * 0.05},
                 "metrics": {}} for i in range(12)]
        _make_dataset(tmp_path, "al_o4_no_metric", rows)
        r = al_propose(dataset="al_o4_no_metric",
                       out_dir=tmp_path / "datasets")
        assert not r["ok"]
        assert any("无可用数值指标" in e for e in r["errors"])

    def test_run_without_trials(self, tmp_path):
        (tmp_path / "runs" / "20261031_000000_bare").mkdir(parents=True)
        r = al_propose(run="20261031_000000_bare",
                       runs_root=tmp_path / "runs")
        assert not r["ok"] and r["errors"]

    def test_unknown_acquisition(self, samples_file):
        r = al_propose(samples_file, acquisition="nope")
        assert not r["ok"] and any("采集函数" in e for e in r["errors"])

    def test_unknown_source(self, samples_file):
        r = al_propose(samples_file, acquisition="sigma", source="nope")
        assert not r["ok"] and any("来源" in e for e in r["errors"])

    def test_registry_unregistered_kind(self, samples_file):
        r = al_propose(samples_file, acquisition="sigma", source="registry",
                       kind="no_such_kind", conformal_fallback=True)
        assert not r["ok"] and any("未注册" in e for e in r["errors"])


# ── 装载面（load_al_samples 公开契约） ──────────────────────────────────────


class TestLoadSamples:
    def test_load_dataset_bounds_derived(self, tmp_path):
        rows = [{"run_id": f"r{i}", "params": {"w_mm": 0.5 + i * 0.1},
                 "metrics": {"cost": float(i)}} for i in range(10)]
        _make_dataset(tmp_path, "al_o4_bounds", rows)
        r = load_al_samples(dataset="al_o4_bounds",
                            out_dir=tmp_path / "datasets")
        assert r["ok"]
        assert r["bounds"] == {"w_mm": [0.5, 1.4]}
        assert len(r["samples"]) == 10

    def test_load_rejects_empty(self, tmp_path):
        _make_dataset(tmp_path, "al_o4_empty", [])
        r = load_al_samples(dataset="al_o4_empty",
                            out_dir=tmp_path / "datasets")
        assert not r["ok"] and any("样本为空" in e for e in r["errors"])


# ── CLI 薄壳（成功+失败同构信封；#24 棘轮家法） ─────────────────────────────


class TestCliAlPropose:
    @staticmethod
    def _invoke_json(args: list[str]) -> tuple[int, dict | None, str]:
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        result = CliRunner().invoke(app, args)
        out = result.output or ""
        start = out.find("{")
        payload = json.loads(out[start:]) if start >= 0 else None
        return result.exit_code, payload, out

    def test_cli_legacy_json_success(self, samples_file):
        rc, payload, out = self._invoke_json(
            ["al", "propose", "--samples", samples_file, "--k", "3",
             "--json"])
        assert rc == 0, out
        assert payload is not None and payload["ok"] is True
        assert len(payload["proposed"]) == 3
        assert payload["surrogate_kind"] == "nn"

    def test_cli_acquisition_json_success(self, samples_file):
        rc, payload, out = self._invoke_json(
            ["al", "propose", "--samples", samples_file, "--k", "3",
             "--acquisition", "lcb", "--json"])
        assert rc == 0, out
        assert payload is not None and payload["ok"] is True
        assert payload["mode"] == "acquisition"
        assert payload["acquisition"] == "lcb"

    def test_cli_failure_same_shape(self):
        rc, payload, _ = self._invoke_json(["al", "propose", "--json"])
        assert rc == 1
        assert payload is not None and payload["ok"] is False
        assert isinstance(payload["errors"], list) and payload["errors"]

    def test_cli_deterministic_bitwise(self, samples_file):
        args = ["al", "propose", "--samples", samples_file, "--k", "3",
                "--acquisition", "sigma", "--json"]
        _, a, out_a = self._invoke_json(args)
        _, b, out_b = self._invoke_json(args)
        assert a == b and out_a == out_b

    def test_cli_conformal_fallback_tri_state_flag(self, samples_file):
        """#277 三态开关：显式 --conformal-fallback 透传 service（poly_ridge
        无原生 σ，关 fallback=提议空；开=共形包装出点）。"""
        rc, payload, _ = self._invoke_json(
            ["al", "propose", "--samples", samples_file, "--k", "2",
             "--kind", "poly_ridge", "--no-conformal-fallback", "--json"])
        assert rc == 0
        assert payload["ok"] is True and payload["proposed"] == []
        rc, payload, _ = self._invoke_json(
            ["al", "propose", "--samples", samples_file, "--k", "2",
             "--kind", "poly_ridge", "--conformal-fallback", "--json"])
        assert rc == 0
        assert payload["ok"] is True and len(payload["proposed"]) == 2

    def test_cli_human_renders(self, samples_file):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        result = CliRunner().invoke(
            app, ["al", "propose", "--samples", samples_file, "--k", "2"])
        assert result.exit_code == 0, result.output
        assert "AL 提议" in result.output
        assert "提议 2 点" in result.output

    def test_cli_help_no_crash(self):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        result = CliRunner().invoke(app, ["al", "--help"])
        assert result.exit_code == 0
        assert "propose" in result.output
