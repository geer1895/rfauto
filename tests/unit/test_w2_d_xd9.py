"""W2-D XD-9：lake audit-stale（湖陈旧审计）。

判据（sa_specs2 §八 §8.3 对应）：
- 注入对拍（判据 1）：旧 engine_version 指纹的合成 run → 清单必含且原因
  =engine_version；空 diff 输入 → 清单为空（双态钉）；
- 单点一致（判据 2）：有 dag 缓存的 run，audit-stale 失效判定与
  dag_cache.why_miss 同判据不漂移；
- 只读钉（判据 3）：运行前后 runs/ 与 .rfauto_cache/ mtime 零变化；
- 真数据审计行 + --json 信封 + 退出码语义（CLI 节）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.infra.dag_cache import DagCasIndex
from rfauto.service.lake_service import audit_stale_runs

runner = CliRunner()


def _run_point(root: Path, rel: str, meta: dict | None = None,
               markers: tuple[str, ...] = ()) -> Path:
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    if meta is not None:
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for m in markers:
        (d / m).write_text("x", encoding="utf-8")
    return d


def _meta(git_sha="aaa111", **extra):
    base = {"run_id": "r", "model": "mline", "adapter": "openems",
            "status": "done", "git_sha": git_sha,
            "timestamp": "2026-10-01T00:00:00+00:00"}
    base.update(extra)
    return base


def _store_dag_index(cache_dir: Path, run_dir: Path, components: dict):
    idx = DagCasIndex(cache_dir=cache_dir)
    key = "k" * 63 + str(len(components))
    idx.store_index(key, run_dir=str(run_dir), node_kind="render",
                    components=components)
    return key


class TestInjectionDoubleState:
    """判据 1：engine 注入双态 + 空 diff 清单为空。"""

    def test_stale_engine_flagged_with_reason(self, tmp_path):
        runs = tmp_path / "runs"
        rp = _run_point(runs, "pt1", _meta())
        _store_dag_index(tmp_path / "cache", rp,
                         {"engine_version": "oe-v1"})
        r = audit_stale_runs(runs, render_commit="aaa111",
                             engine_version="oe-v2",
                             cache_dir=tmp_path / "cache")
        assert r["ok"]
        hits = [row for row in r["stale"] if row["path"] == "pt1"]
        assert len(hits) == 1, r["stale"]
        assert "engine" in hits[0]["classes"]
        assert any("engine_version" in s for s in hits[0]["reasons"])

    def test_same_engine_not_flagged(self, tmp_path):
        runs = tmp_path / "runs"
        rp = _run_point(runs, "pt1", _meta())
        _store_dag_index(tmp_path / "cache", rp,
                         {"engine_version": "oe-v1"})
        r = audit_stale_runs(runs, render_commit="aaa111",
                             engine_version="oe-v1",
                             cache_dir=tmp_path / "cache")
        assert r["ok"] and r["n_stale"] == 0

    def test_empty_diff_yields_empty_stale_list(self, tmp_path):
        """双态钉：空 diff 输入（各选择器中性）→ 清单为空。"""
        runs = tmp_path / "runs"
        _run_point(runs, "pt1", _meta())
        r = audit_stale_runs(runs, render_commit="aaa111",
                             config_diff={})
        assert r["ok"] and r["n_stale"] == 0 and r["stale"] == []
        r2 = audit_stale_runs(runs, render_commit="aaa111",
                              config_diff={"keys": []})
        assert r2["ok"] and r2["n_stale"] == 0

    def test_code_class_git_sha_mismatch(self, tmp_path):
        runs = tmp_path / "runs"
        _run_point(runs, "pt1", _meta(git_sha="deadbee"))
        r = audit_stale_runs(runs, render_commit="aaa111")
        assert r["n_stale"] == 1
        assert r["class_counts"]["code"] == 1
        assert "deadbee" in r["stale"][0]["reasons"][0]

    def test_default_render_commit_is_git_head(self, tmp_path):
        runs = tmp_path / "runs"
        _run_point(runs, "pt1", _meta(git_sha="older01"))
        # tmp 非 git 环境 → head 为空串 → 不比 code（选择器不可用如实降级）
        r = audit_stale_runs(runs)
        assert r["ok"]
        assert r["selectors"]["render_commit_source"] in ("git-head",
                                                          "unavailable")


class TestConfigDiffClasses:
    """config-diff 三形 + params/budget 分类 + unmatched 如实计数。"""

    def test_flat_mapping_params_class(self, tmp_path):
        runs = tmp_path / "runs"
        _run_point(runs, "pt1", _meta(w_mm=1.0))
        r = audit_stale_runs(runs, render_commit="aaa111",
                             config_diff={"w_mm": 2.0})
        assert r["class_counts"]["params"] == 1

    def test_old_new_form_and_keys_form(self, tmp_path):
        runs = tmp_path / "runs"
        _run_point(runs, "pt1", _meta(w_mm=1.0))
        r = audit_stale_runs(runs, render_commit="aaa111",
                             config_diff={"keys": {"w_mm": {"old": 1.0,
                                                            "new": 3.0}}})
        assert r["class_counts"]["params"] == 1
        r2 = audit_stale_runs(runs, render_commit="aaa111",
                              config_diff={"keys": ["w_mm"]})
        # 只声明键变化未给新值：不可比 → 不计失效，如实不 inflate
        assert r2["n_stale"] == 0

    def test_budget_keys_and_unmatched(self, tmp_path):
        runs = tmp_path / "runs"
        _run_point(runs, "pt1", _meta(mesh_resolution_mm=0.5))
        r = audit_stale_runs(runs, render_commit="aaa111",
                             config_diff={"mesh_resolution_mm": 0.25,
                                          "nonexistent_key": 1})
        assert r["class_counts"]["budget"] == 1
        assert r["n_config_key_unmatched"] == 1
        assert r["stale"][0]["classes"] == ["budget"]

    def test_bad_config_diff_is_error(self, tmp_path):
        runs = tmp_path / "runs"
        _run_point(runs, "pt1", _meta())
        r = audit_stale_runs(runs, config_diff=[1, 2])
        assert not r["ok"]


class TestDagConsistency:
    """判据 2：audit-stale 与 dag_cache.why_miss 同判据双入口不漂移。"""

    def test_engine_mismatch_agrees_with_why_miss(self, tmp_path):
        runs = tmp_path / "runs"
        rp = _run_point(runs, "pt1", _meta())
        cache = tmp_path / "cache"
        _store_dag_index(cache, rp, {"engine_version": "oe-v1",
                                     "params_canonical_json": "{}"})

        # 单点：dag_cache 面请求新引擎 → why_miss 提 engine_version 成分
        idx = DagCasIndex(cache_dir=cache)
        requested = {"engine_version": "oe-v2",
                     "params_canonical_json": "{}"}
        result = idx.lookup(
            "0" * 64, node_kind="render", components=requested)
        assert not result["hit"]
        assert any("engine_version" in s for s in result["why_miss"])

        # 湖级：audit-stale 同判据 → 同一 run 进清单且原因同源
        r = audit_stale_runs(runs, render_commit="aaa111",
                             engine_version="oe-v2", cache_dir=cache)
        hits = [row for row in r["stale"] if row["path"] == "pt1"]
        assert len(hits) == 1
        assert "engine" in hits[0]["classes"]


class TestUnknownAndReadonly:
    """unknown 类（缺 meta 半途形态）+ 只读钉（判据 3）。"""

    def test_missing_meta_with_markers_is_unknown(self, tmp_path):
        runs = tmp_path / "runs"
        _run_point(runs, "pt_running", None, markers=("sparams.csv",))
        _run_point(runs, "pt_campaign/inner", None)
        r = audit_stale_runs(runs, render_commit="aaa111")
        assert r["ok"]
        assert r["n_unknown_meta"] == 1
        assert r["unknown"][0]["path"] == "pt_running"

    def test_corrupt_meta_is_unknown(self, tmp_path):
        runs = tmp_path / "runs"
        d = runs / "pt_bad"
        d.mkdir(parents=True)
        (d / "meta.json").write_text("{not json", encoding="utf-8")
        r = audit_stale_runs(runs, render_commit="aaa111")
        assert r["n_unknown_meta"] == 1
        assert "不可解析" in r["unknown"][0]["reason"]

    def test_readonly_mtime_and_no_new_files(self, tmp_path):
        runs = tmp_path / "runs"
        rp = _run_point(runs, "pt1", _meta())
        cache = tmp_path / "cache"
        _store_dag_index(cache, rp, {"engine_version": "oe-v1"})

        def snapshot(base: Path) -> dict[str, int]:
            out = {}
            for p in base.rglob("*"):
                if p.is_file():
                    st = p.stat()
                    out[str(p)] = st.st_mtime_ns
            return out

        before_runs = snapshot(runs)
        before_cache = snapshot(cache)
        audit_stale_runs(runs, render_commit="aaa111",
                         engine_version="oe-v9", cache_dir=cache)
        assert snapshot(runs) == before_runs
        assert snapshot(cache) == before_cache
        n_files = sum(1 for p in runs.rglob("*") if p.is_file())
        assert n_files == len(before_runs)
        assert os.listdir(cache)  # 缓存目录仍在（零删除）


class TestRealLakeSmoke:
    """真数据审计行（判据：对 runs/ 湖现有数据真跑出审计行）。"""

    def test_real_repo_lake_audit_rows(self):
        repo_runs = Path(__file__).resolve().parents[2] / "runs"
        if not repo_runs.is_dir() or not any(repo_runs.iterdir()):
            pytest.skip("本环境无真实 runs/ 湖（公开分发视图证据缺席）")
        _probe = audit_stale_runs(repo_runs, max_detail=1)
        if _probe.get("n_checked", 0) < 50:
            pytest.skip("runs/ 湖规模不足真湖量级（公开分发视图），如实 skip")
        import time

        t0 = time.monotonic()
        r = audit_stale_runs(repo_runs, max_detail=5)
        wall = time.monotonic() - t0
        assert r["ok"]
        assert r["n_checked"] > 1000  # 真湖 run 点规模
        assert isinstance(r["n_stale"], int)
        assert wall < 300  # 判据 7：全湖 <5min
        if r["stale"]:
            row = r["stale"][0]
            assert row["path"] and row["classes"]


class TestW2DXd9Cli:
    """CLI 叶：--help 真跑 + --json 双路径 + 退出码语义（0/1/2）。"""

    def test_help_runs(self):
        from rfauto.cli.domains.lake import app

        result = runner.invoke(app, ["lake", "audit-stale", "--help"])
        assert result.exit_code == 0
        assert "audit-stale" in result.output or "陈旧" in result.output

    def test_json_envelope_and_exit_codes(self, tmp_path):
        from rfauto.cli.domains.lake import app

        runs = tmp_path / "runs"
        _run_point(runs, "pt1", _meta(git_sha="aaa111"))
        _run_point(runs, "pt2", _meta(git_sha="aaa111"))
        args = ["lake", "audit-stale", "--runs-root", str(runs),
                "--render-commit", "aaa111", "--json"]
        r_fresh = runner.invoke(app, args, catch_exceptions=False)
        assert r_fresh.exit_code == 0
        payload = json.loads(r_fresh.output)
        assert payload["ok"] and payload["n_stale"] == 0

        # 注入陈旧 run（只读审计可复跑，幂等）
        _run_point(runs, "pt3", _meta(git_sha="old999"))
        r_stale = runner.invoke(app, args, catch_exceptions=False)
        assert r_stale.exit_code == 1
        payload_rerun = json.loads(r_stale.output)
        assert payload_rerun["ok"] and payload_rerun["n_stale"] == 1

        runs2 = tmp_path / "runs_all_stale"
        _run_point(runs2, "pt1", _meta(git_sha="old999"))
        r2 = runner.invoke(
            app, ["lake", "audit-stale", "--runs-root", str(runs2),
                  "--render-commit", "aaa111", "--json"],
            catch_exceptions=False)
        assert r2.exit_code == 1
        payload2 = json.loads(r2.output)
        assert payload2["ok"] and payload2["n_stale"] == 1

    def test_missing_runs_root_exit_2(self, tmp_path):
        from rfauto.cli.domains.lake import app

        result = runner.invoke(
            app, ["lake", "audit-stale", "--runs-root",
                  str(tmp_path / "nope"), "--json"],
            catch_exceptions=False)
        assert result.exit_code == 2
        assert not json.loads(result.output)["ok"]

    def test_config_diff_file_path(self, tmp_path):
        from rfauto.cli.domains.lake import app

        runs = tmp_path / "runs"
        _run_point(runs, "pt1", _meta(git_sha="aaa111", w_mm=1.0))
        diff = tmp_path / "diff.json"
        diff.write_text(json.dumps({"w_mm": 2.0}), encoding="utf-8")
        result = runner.invoke(
            app, ["lake", "audit-stale", "--runs-root", str(runs),
                  "--render-commit", "aaa111", "--config-diff", str(diff),
                  "--json"], catch_exceptions=False)
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["class_counts"]["params"] == 1

    def test_text_path_prints_audit_lines(self, tmp_path):
        from rfauto.cli.domains.lake import app

        runs = tmp_path / "runs"
        _run_point(runs, "pt1", _meta(git_sha="old999"))
        result = runner.invoke(
            app, ["lake", "audit-stale", "--runs-root", str(runs),
                  "--render-commit", "aaa111"], catch_exceptions=False)
        assert result.exit_code == 1
        assert "pt1" in result.output
        assert "code" in result.output
