"""ME-17b 接线批后半 + 批 B1 平台薄壳单测（wf:batch-b1-wiring，2026-09-28）。

覆盖面（方案 gap 盘点 §二批 B1 五件，2026-09-28）：
- ME-17b 后半接线：repro-manifest/repro-verify（CLI）、chain lna/loadpull
  （CLI）、even-odd（CLI）与 even_odd_report/mcts_search/inverse_prefilter
  （MCP 三工具）——薄壳透传断言（monkeypatch 钉住通道 #139）+离线真报告；
- QW-13 lake sweep：runs/ 只读清点分类（complete/incomplete/empty/
  unannotated，#144 在跑形态="有 trials/无 meta"）+ CLI 薄壳；
- P-5 DuckDB 防御性配置：configure_duckdb_connection PRAGMA 封装
  （best-effort 单条失败不阻塞）+ export_index_parquet 冷层 COPY 往返；
- P-1 SSE 桥读面：ui_service.read_run_events 增量/终态/路径穿越拒收 +
  ui/server SSE 端点事件帧（终端事件收束，TestClient 消费整流）。

纪律：chdir 隔离零污染（#144）；duckdb 依赖诚实 skip（dataset extra，
CI unit 门不装——同 test_lake_service 口径）；零真机零网络。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.service import lake_service, ui_service

runner = CliRunner()


# ─── ME-17b 后半：repro manifest/verify CLI ──────────────────────────────────

class TestReproManifestCLI:
    def test_manifest_and_verify_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "artifact_dir"
        target.mkdir()
        (target / "data.txt").write_text("payload-v1", encoding="utf-8")
        manifest_path = tmp_path / "m.json"

        r1 = runner.invoke(app, ["repro-manifest", str(target),
                                 "--out", str(manifest_path), "--no-git"])
        assert r1.exit_code == 0, r1.output
        assert manifest_path.is_file()

        r2 = runner.invoke(app, ["repro-verify", str(manifest_path),
                                 str(target)])
        assert r2.exit_code == 0, r2.output
        assert "missing=0" in r2.output and "changed=0" in r2.output

    def test_verify_detects_tamper(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "artifact_dir"
        target.mkdir()
        (target / "data.txt").write_text("payload-v1", encoding="utf-8")
        manifest_path = tmp_path / "m.json"
        assert runner.invoke(app, ["repro-manifest", str(target),
                                   "--out", str(manifest_path),
                                   "--no-git"]).exit_code == 0
        (target / "data.txt").write_text("tampered", encoding="utf-8")
        r = runner.invoke(app, ["repro-verify", str(manifest_path),
                                str(target)])
        assert r.exit_code == 1
        assert "changed:" in r.output and "data.txt" in r.output

    def test_verify_missing_manifest_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        r = runner.invoke(app, ["repro-verify", str(tmp_path / "nope.json")])
        assert r.exit_code == 1

    def test_manifest_json_output(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        r = runner.invoke(app, ["repro-manifest", "--out",
                                str(tmp_path / "m2.json"), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True


# ─── ME-17b 后半：chain lna/loadpull CLI（薄壳透传，#139 monkeypatch 钉通道）──

class TestChainCLI:
    def test_loadpull_forwards_and_renders(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service import active_chain_service as svc

        captured: dict = {}

        def fake_loadpull(*args, **kwargs):
            captured.update(kwargs)
            return {"status": "ok", "optimum": {"r_max": 0.9},
                    "verdict": {"loadpull_plausible": True, "n_contours": 3}}

        monkeypatch.setattr(svc, "run_pa_loadpull", fake_loadpull)
        r = runner.invoke(app, [
            "chain", "loadpull", "--vdd-v", "28", "--imax-a", "1.0",
            "--cout-pf", "2.0", "--f0-ghz", "2.4"])
        assert r.exit_code == 0, r.output
        assert captured["vknee_v"] == pytest.approx(0.3)
        assert captured["n_grid"] == 81
        assert "n_contours=3" in r.output

    def test_loadpull_failure_exits_1(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service import active_chain_service as svc

        monkeypatch.setattr(svc, "run_pa_loadpull",
                            lambda *a, **k: {"status": "error",
                                             "error": "器件参数非法"})
        r = runner.invoke(app, [
            "chain", "loadpull", "--vdd-v", "28", "--imax-a", "1.0",
            "--cout-pf", "2.0", "--f0-ghz", "2.4"])
        assert r.exit_code == 1
        assert "器件参数非法" in r.output

    def test_loadpull_real_offline_run(self, tmp_path, monkeypatch):
        """零仿真真透传：不注入桩，Cripps 解析圈直接跑（秒级零 license）。"""
        monkeypatch.chdir(tmp_path)
        r = runner.invoke(app, [
            "chain", "loadpull", "--vdd-v", "28", "--imax-a", "1.0",
            "--cout-pf", "2.0", "--f0-ghz", "2.4", "--n-grid", "21",
            "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["verdict"]["n_contours"] >= 1

    def test_lna_forwards(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service import active_chain_service as svc

        captured: dict = {}

        def fake_lna(match, device, f0, **kwargs):
            captured["match"] = match
            captured["f0"] = f0
            captured["noise_params"] = kwargs.get("noise_params")
            return {"status": "ok", "manual": {"f0_hz": 2.4e9,
                                               "chain_s21_db": -0.5},
                    "verdict": {"device_unconditionally_stable": True,
                                "chain_unconditionally_stable": True}}

        monkeypatch.setattr(svc, "run_lna_chain", fake_lna)
        r = runner.invoke(app, [
            "chain", "lna", "match.s2p", "device.s2p", "--f0-ghz", "2.4",
            "--noise", '{"fmin_db": 0.7}'])
        assert r.exit_code == 0, r.output
        assert captured["match"] == "match.s2p"
        assert captured["f0"] == pytest.approx(2.4)
        assert captured["noise_params"] == {"fmin_db": 0.7}


# ─── ME-17b 后半：even-odd CLI ────────────────────────────────────────────────

class TestEvenOddCLI:
    def test_list_templates(self):
        r = runner.invoke(app, ["even-odd", "--list"])
        assert r.exit_code == 0, r.output
        assert "cline_coupler" in r.output

    def test_report_offline(self):
        from rfauto.service.even_odd_service import EVEN_ODD_TEMPLATES

        template = EVEN_ODD_TEMPLATES[0]
        r = runner.invoke(app, ["even-odd", template, "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["template"] == template
        assert set(payload["half_models"]) == {"even", "odd"}

    def test_unknown_template_fails(self):
        r = runner.invoke(app, ["even-odd", "no_such_template", "--json"])
        assert r.exit_code == 1

    def test_no_args_fails(self):
        r = runner.invoke(app, ["even-odd"])
        assert r.exit_code == 1


# ─── ME-17b 后半：MCP 三工具（typed tool call 面）────────────────────────────

def _extract_result(tool_result):
    if hasattr(tool_result, "structured_content") and \
            tool_result.structured_content is not None:
        return tool_result.structured_content
    if hasattr(tool_result, "content") and tool_result.content:
        return json.loads(tool_result.content[0].text)
    return json.loads(str(tool_result))


class TestMcpB1Tools:
    @pytest.fixture()
    def mcp(self):
        from rfauto.mcp_server import mcp
        return mcp

    def test_even_odd_report(self, mcp, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.even_odd_service import EVEN_ODD_TEMPLATES

        result = _extract_result(asyncio.run(mcp.call_tool(
            "even_odd_report",
            {"template": EVEN_ODD_TEMPLATES[0], "params": None,
             "freq_ghz": None})))
        assert result["ok"] is True
        assert set(result["half_models"]) == {"even", "odd"}

    def test_mcts_search(self, mcp, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bounds = {"arm_len_mm": [10.0, 30.0], "gap_mm": [0.1, 1.0]}
        samples = [{"params": {"arm_len_mm": 20.0 + 0.1 * i,
                               "gap_mm": 0.5 + 0.01 * i},
                    "cost": 1.0 - 0.01 * i} for i in range(8)]
        (tmp_path / "samples.json").write_text(json.dumps(
            {"samples": samples, "bounds": bounds}), encoding="utf-8")
        result = _extract_result(asyncio.run(mcp.call_tool(
            "mcts_search",
            {"samples_path": str(tmp_path / "samples.json"),
             "n_simulations": 30, "seed": 42})))
        assert result["ok"] is True
        assert result["best_cost_pred"] <= result["root_cost_pred"]
        # 种子确定性
        again = _extract_result(asyncio.run(mcp.call_tool(
            "mcts_search",
            {"samples_path": str(tmp_path / "samples.json"),
             "n_simulations": 30, "seed": 42})))
        assert again["best_params"] == result["best_params"]

    def test_inverse_prefilter(self, mcp, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service import inverse_prefilter as mod

        monkeypatch.setattr(
            mod, "_fake_metrics",
            lambda recipe, params: {"s11_db": -20.0 + params["arm_len_mm"],
                                    "cost": 20.0 - params["arm_len_mm"]})
        recipe = {
            "model": "wilkinson_power_divider",
            "optimization": {"params": {
                "arm_len_mm": {"low": 10.0, "high": 30.0},
                "gap_mm": {"low": 0.1, "high": 1.0}}},
        }
        import yaml

        recipe_path = tmp_path / "recipe.yaml"
        recipe_path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        result = _extract_result(asyncio.run(mcp.call_tool(
            "inverse_prefilter",
            {"recipe_path": str(recipe_path),
             "target_metrics": {"s11_db": -40.0},
             "n_corpus": 12, "k": 3, "seed": 42})))
        assert result["ok"] is True
        assert len(result["candidates"]) == 3
        assert result["generator"] == "fake_corpus_nn_invert_v1"


# ─── QW-13 lake sweep ─────────────────────────────────────────────────────────

def _make_sweep_tree(root: Path) -> None:
    """四形态目录：complete/incomplete（在跑形态 #144）/empty/unannotated。"""
    complete = root / "camp" / "run_ok"
    complete.mkdir(parents=True)
    (complete / "meta.json").write_text(
        json.dumps({"model": "wilkinson_power_divider", "adapter": "fake"}),
        encoding="utf-8")
    running = root / "camp" / "run_running"
    running.mkdir(parents=True)
    (running / "trials").mkdir()
    (running / "trials" / "t1.json").write_text("{}", encoding="utf-8")
    (root / "camp" / "run_empty").mkdir(parents=True)
    misc = root / "camp" / "run_misc"
    misc.mkdir(parents=True)
    (misc / "note.txt").write_text("nothing known", encoding="utf-8")


class TestLakeSweep:
    def test_classification(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _make_sweep_tree(runs)
        result = lake_service.sweep_runs(runs)
        assert result["ok"] is True
        assert result["n_dirs"] == 5          # camp 容器+4 个 run 点
        assert result["n_containers"] == 1    # camp 本身（无 meta 属正常）
        assert result["n_complete"] == 1
        assert result["n_incomplete"] == 1
        assert result["n_empty"] == 1
        assert result["n_unannotated"] == 1
        row = result["incomplete"][0]
        assert row["path"].endswith("run_running")
        assert row["markers"] == ["trials"]
        assert any("trials" in r for r in row["reasons"])

    def test_missing_dir_ok_zero(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = lake_service.sweep_runs(tmp_path / "no_runs")
        assert result["ok"] is True and result["n_dirs"] == 0

    def test_cli_sweep(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_sweep_tree(tmp_path / "runs")
        r = runner.invoke(app, ["lake", "sweep", "--runs-dir", "runs"])
        assert r.exit_code == 0, r.output
        assert "complete=1" in r.output and "incomplete=1" in r.output

    def test_readonly_guarantee(self, tmp_path, monkeypatch):
        """只读红线：sweep 前后目录树字节面零变化。"""
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _make_sweep_tree(runs)
        before = sorted((p.relative_to(runs), p.stat().st_size)
                        for p in runs.rglob("*") if p.is_file())
        lake_service.sweep_runs(runs)
        after = sorted((p.relative_to(runs), p.stat().st_size)
                       for p in runs.rglob("*") if p.is_file())
        assert before == after


# ─── P-5 DuckDB 防御性配置 + 冷层 COPY ────────────────────────────────────────

class TestDuckDBDefensiveConfig:
    @pytest.fixture(autouse=True)
    def _needs_duckdb(self):
        pytest.importorskip("duckdb",
                            reason="P-5 面 duckdb（dataset extra，诚实 skip）")

    def test_pragmas_applied(self):
        duckdb = lake_service._import_duckdb()
        con = duckdb.connect(":memory:")
        try:
            report = lake_service.configure_duckdb_connection(con)
            # duckdb 会把 2GB 规格化为 '1.8 GiB' 显示——断言 applied 旗标即可
            assert report["applied"] == {"memory_limit": True, "threads": True}
            assert report["errors"] == []
        finally:
            con.close()

    def test_bad_pragma_degrades_not_raises(self):
        duckdb = lake_service._import_duckdb()
        con = duckdb.connect(":memory:")
        try:
            report = lake_service.configure_duckdb_connection(
                con, memory_limit="not-a-size")
            assert report["applied"]["memory_limit"] is False
            assert report["errors"]
            assert report["applied"]["threads"] is True  # 其余 PRAGMA 照常
        finally:
            con.close()

    def test_export_index_parquet_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _make_sweep_tree(runs)
        built = lake_service.build_runs_index(runs, db_path=tmp_path / "i.duckdb")
        assert built["ok"] is True and built["n_rows"] == 5  # 两层全入索引（camp 容器+4 点）
        out = tmp_path / "cold"
        exported = lake_service.export_index_parquet(
            tmp_path / "i.duckdb", out, partition_by="campaign")
        assert exported["ok"] is True, exported.get("errors")
        assert exported["n_rows"] == 5
        assert len(exported["files"]) >= 1
        # 读回：分区列 hive 目录形态，行数一致
        duckdb = lake_service._import_duckdb()
        con = duckdb.connect()
        try:
            n = con.execute(
                f"SELECT count(*) FROM read_parquet("
                f"'{(out / '**').as_posix()}/*.parquet',"
                f" hive_partitioning=true)").fetchone()[0]
        finally:
            con.close()
        assert n == 5

    def test_export_overwrite(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _make_sweep_tree(runs)
        lake_service.build_runs_index(runs, db_path=tmp_path / "i.duckdb")
        out = tmp_path / "cold"
        first = lake_service.export_index_parquet(tmp_path / "i.duckdb", out)
        assert first["ok"] is True
        again = lake_service.export_index_parquet(tmp_path / "i.duckdb", out,
                                                  overwrite=True)
        assert again["ok"] is True, again.get("errors")

    def test_export_existing_dir_without_overwrite_fails(self, tmp_path,
                                                         monkeypatch):
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _make_sweep_tree(runs)
        lake_service.build_runs_index(runs, db_path=tmp_path / "i.duckdb")
        out = tmp_path / "cold"
        out.mkdir()
        result = lake_service.export_index_parquet(tmp_path / "i.duckdb", out)
        assert result["ok"] is False

    def test_cli_export_parquet(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _make_sweep_tree(runs)
        assert runner.invoke(app, ["lake", "index", "--runs-dir", "runs",
                                   "--db", str(tmp_path / "i.duckdb"),
                                   "--json"]).exit_code == 0
        r = runner.invoke(app, ["lake", "export-parquet",
                                "--db", str(tmp_path / "i.duckdb"),
                                "--out-dir", str(tmp_path / "cold2"),
                                "--partition-by", "campaign", "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True and payload["n_rows"] == 5


# ─── P-1 SSE 桥读面 + 端点 ────────────────────────────────────────────────────

def _write_events(run_dir: Path, events: list[dict]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(ev, ensure_ascii=False) for ev in events]
    (run_dir / "events.jsonl").write_text("\n".join(lines) + "\n",
                                          encoding="utf-8")


def _event(kind: str, run_id: str = "r1") -> dict:
    return {"event_type": kind, "run_id": run_id, "job_id": "",
            "message": kind, "data": {}, "timestamp": 1.0, "event_id": kind}


class TestReadRunEvents:
    def test_incremental_and_terminal(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_events(tmp_path / "runs" / "r1",
                      [_event("run_started"), _event("progress"),
                       _event("run_completed")])
        first = ui_service.read_run_events("r1", 0)
        assert first["ok"] is True and first["exists"] is True
        assert len(first["events"]) == 3
        assert first["terminal"] is True
        tail = ui_service.read_run_events("r1", first["offset"])
        # terminal=本增量内见到终态（SSE 桥口径）——续读无新事件则 False
        assert tail["events"] == [] and tail["terminal"] is False

    def test_missing_file_is_empty_stream(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = ui_service.read_run_events("ghost", 0)
        assert result["ok"] is True and result["exists"] is False

    def test_corrupt_line_skipped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run_dir = tmp_path / "runs" / "r1"
        run_dir.mkdir(parents=True)
        (run_dir / "events.jsonl").write_text(
            json.dumps(_event("run_started")) + "\n{broken\n",
            encoding="utf-8")
        result = ui_service.read_run_events("r1", 0)
        assert len(result["events"]) == 1

    def test_traversal_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for bad in ("../other", "a/b", "..", "."):
            result = ui_service.read_run_events(bad, 0)
            assert result["ok"] is False


class TestSseEndpoint:
    def _client(self, tmp_path, monkeypatch):
        pytest.importorskip("httpx", reason="TestClient 需要 httpx")
        pytest.importorskip("sse_starlette",
                            reason="P-1 SSE 需要 sse-starlette（ui extra）")
        monkeypatch.chdir(tmp_path)
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app
        return TestClient(create_ui_app(include_runs_mount=False))

    def test_stream_emits_events_and_ends(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        _write_events(tmp_path / "runs" / "r1",
                      [_event("run_started"), _event("run_completed")])
        with client.stream("GET", "/api/runs/r1/events/stream") as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())
        assert "event: run_started" in body
        assert "event: run_completed" in body
        assert "event: end" in body

    def test_stream_unknown_run_ends_immediately(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        with client.stream("GET", "/api/runs/ghost/events/stream") as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())
        assert "exists" in body and "event: end" in body

    def test_incremental_offset_never_replays(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_events(tmp_path / "runs" / "r1", [_event("run_started")])
        first = ui_service.read_run_events("r1", 0)
        _write_events(tmp_path / "runs" / "r1",
                      [_event("run_started"), _event("run_failed")])
        second = ui_service.read_run_events("r1", first["offset"])
        assert [e["event_type"] for e in second["events"]] == ["run_failed"]
        assert second["terminal"] is True
