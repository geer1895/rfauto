"""CLI 集成测试—— typer CliRunner 驱动真实命令入口。

背景：cli/main.py 曾长期零覆盖（13 个命令无任何测试），本文件覆盖
只读命令与关键写路径的最小集。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from rfauto.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


def _recipe(tmp_path: Path) -> Path:
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestReadOnlyCommands:
    def test_doctor_exits_zero(self, tmp_path, monkeypatch):
        # 注入存在的路径使 AEDT/ADS 检查通过（无 EDA 环境的 CI 也能跑）
        monkeypatch.setenv("RFAUTO_AEDT_PATH", str(tmp_path))
        monkeypatch.setenv("RFAUTO_HPEESOF_DIR", str(tmp_path))
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0, result.output
        assert "rfauto doctor" in result.output

    def test_doctor_missing_env_exits_nonzero(self):
        """缺 AEDT/ADS 配置时退出码非零（CI/脚本可直接判断）。"""
        result = runner.invoke(app, ["doctor"])
        if "未配置" in result.output:
            assert result.exit_code == 1

    def test_models_list_contains_three_plugins(self):
        result = runner.invoke(app, ["models", "list"])
        assert result.exit_code == 0
        for name in ("wilkinson_power_divider", "branchline_coupler", "patch_antenna"):
            assert name in result.output

    def test_models_schema_export(self):
        result = runner.invoke(app, ["models", "list", "--schema", "branchline_coupler"])
        assert result.exit_code == 0
        assert "arm_len_mm" in result.output

    def test_models_schema_unknown_model_fails(self):
        result = runner.invoke(app, ["models", "list", "--schema", "no_such_model"])
        assert result.exit_code == 1

    def test_jobs_status_unknown_id(self):
        result = runner.invoke(app, ["jobs", "status", "job_unknown_000"])
        assert result.exit_code == 0
        assert "unknown" in result.output


class TestValidateCommand:
    def test_validate_ok(self, tmp_path):
        result = runner.invoke(app, ["validate", str(_recipe(tmp_path))])
        assert result.exit_code == 0
        assert "校验通过" in result.output

    def test_validate_missing_file_fails(self):
        result = runner.invoke(app, ["validate", "no_such.yaml"])
        assert result.exit_code == 1

    def test_validate_empty_file_reports_error(self, tmp_path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        result = runner.invoke(app, ["validate", str(empty)])
        assert result.exit_code == 1
        assert "为空" in result.output


class TestRunCommand:
    def test_run_fake_sync(self, tmp_path):
        result = runner.invoke(app, ["run", str(_recipe(tmp_path))])
        assert result.exit_code == 0, result.output
        assert "仿真完成" in result.output
        assert "run_id" in result.output

    def test_run_fake_detach_returns_job_id(self, tmp_path):
        from rfauto.service.job_registry import get_job_registry, reset_job_registry

        reset_job_registry()
        result = runner.invoke(app, ["run", str(_recipe(tmp_path)), "--detach"])
        assert result.exit_code == 0, result.output
        assert "job_" in result.output, "应打印 job_id"
        # 必须等后台 job 跑完：否则线程在 monkeypatch 还原 cwd 之后才执行，
        # run 产物落进真实 runs/（#144 类污染的真凶，2026-09-05 定位）
        job_id = next(
            line.split()[-1] for line in result.output.splitlines()
            if line.startswith("  轮询")
        ).strip()
        final = get_job_registry().wait(job_id, timeout_s=60)
        assert final is not None and final["state"] == "done", final
        reset_job_registry()

    def test_run_invalid_recipe_fails(self):
        result = runner.invoke(app, ["run", "no_such.yaml"])
        assert result.exit_code == 1


class TestCacheCommand:
    def test_cache_clear(self):
        result = runner.invoke(app, ["cache", "clear"])
        assert result.exit_code == 0
        assert "条目" in result.output

    def test_cache_clear_by_model(self):
        result = runner.invoke(app, ["cache", "clear", "--model", "wilkinson_power_divider"])
        assert result.exit_code == 0


class TestCommandRegistryCount:
    """CLI 叶子命令计数断言（#97：数字必须代码实测，不沿用文档）。"""

    def test_leaf_command_count(self):
        # 53（09-12 基线）+1（WP4.7 export-report-pdf）= 54
        # +37（2026-09-15 shell 工具批量：bench 2 + bands 10 +
        #   campaign 4 + template-spec 2 + uq 3 + farfield 2 + kicad extract/
        #   optimize 2 + electrothermal/parasitic 2 + topology 1 + datasets 4 +
        #   vna-replay 1 + report-narrative 1 + rationale 3）= 91
        # +1（level2：bench level2 薄壳，cli/bench_app.py；此前漏同步本消费者
        #   经合流门抓出后补计，#231 同族）= 92
        # +3（RAG 薄壳：rag index/query/explain，rag_service 一步式包装）
        #   = 95
        # +3（接线层装车：self-heal run / logs digest /
        #   materials dispersion-report，零逻辑转发 service 信封）= 98
        # +6（2026-09-18：db init/migrate/status/reindex-runs/
        #   query/analytics-attach，注册表薄壳零逻辑转发 db_service）= 104
        # +5（2026-09-18：slotline analyze/synth + transitions
        #   msl-slot/marchand-balun/marchand2，槽线与过渡薄壳零逻辑转发
        #   slotline_service）= 109
        # +2（2026-09-18：datasets discover-workdir/import-workdir，
        #   工作目录形态真机产物导入器薄壳零逻辑转发 dataset_service）= 111
        total = len(app.registered_commands)
        for info in app.registered_groups:
            total += len(info.typer_instance.registered_commands)
        assert total == 111

    def test_export_report_pdf_registered(self):
        names = {cmd.name for cmd in app.registered_commands}
        assert "export-report-pdf" in names


def _fake_run_metrics(tmp_path: Path) -> str:
    """在隔离 cwd 下手工搭一个最小 run 目录（get_metrics 只读 metrics.json）。"""
    run_id = "20260912_120000_cli_pdf_smoke"
    results = tmp_path / "runs" / run_id / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "metrics.json").write_text(
        json.dumps({"metrics": {"s11_db": -22.5, "cost": 0.42}}), encoding="utf-8")
    return run_id


class TestExportReportPdfCommand:
    def test_export_report_pdf_writes_file(self, tmp_path):
        run_id = _fake_run_metrics(tmp_path)
        result = runner.invoke(app, ["export-report-pdf", run_id])
        assert result.exit_code == 0, result.output
        pdf_path = tmp_path / "runs" / run_id / "report.pdf"
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0
        assert "20260912_120000_cli_pdf_smoke" in result.output
        assert "report.pdf" in result.output

    def test_export_report_pdf_output_path(self, tmp_path):
        run_id = _fake_run_metrics(tmp_path)
        out = tmp_path / "elsewhere" / "out.pdf"
        result = runner.invoke(app, ["export-report-pdf", run_id, "-o", str(out)])
        assert result.exit_code == 0, result.output
        assert out.exists() and out.stat().st_size > 0

    def test_export_report_pdf_missing_run_fails(self):
        result = runner.invoke(app, ["export-report-pdf", "no_such_run_000"])
        assert result.exit_code == 1
        assert "PDF 报告导出失败" in result.output


class TestDetachEndToEnd:
    def test_detach_then_poll_via_registry(self, tmp_path):
        """--detach 提交后通过 poll_job 能查到 done（进程内注册表）。"""

        from rfauto.service.api import poll_job
        from rfauto.service.job_registry import get_job_registry, reset_job_registry

        reset_job_registry()
        result = runner.invoke(app, ["run", str(_recipe(tmp_path)), "--detach"])
        assert result.exit_code == 0
        # 从输出解析 job_id
        job_id = next(
            line.split()[-1] for line in result.output.splitlines() if line.startswith("  轮询")
        ).strip()
        final = get_job_registry().wait(job_id, timeout_s=60)
        assert final is not None and final["state"] == "done", final
        polled = poll_job(job_id)
        assert polled["state"] == "done"
        reset_job_registry()


def _ip3_catalog(tmp_path: Path) -> Path:
    """两级有源目录（oip3_dbm 均给出）——P2 IP3 级联透传冒烟。"""
    catalog = {"devices": {
        "amp_a": {"type": "active", "ports": ["in", "out"],
                  "gain_db": 10.0, "nf_db": 3.0, "oip3_dbm": 20.0},
        "amp_b": {"type": "active", "ports": ["in", "out"],
                  "gain_db": 20.0, "nf_db": 6.0, "oip3_dbm": 30.0},
    }}
    path = tmp_path / "catalog_ip3.yaml"
    path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
    return path


class TestBudgetIp3Passthrough:
    """P2 IP3 级联：CLI 薄壳透传 spec.oip3_dbm（手算例 IIP3≈−0.41dBm/OIP3≈29.59dBm）。"""

    def test_budget_run_json_carries_cascade_ip3(self, tmp_path):
        result = runner.invoke(app, [
            "budget", "run", "amp_a", "amp_b",
            "--catalog", str(_ip3_catalog(tmp_path)), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["cascade_iip3_dbm"] == pytest.approx(-0.41, abs=0.01)
        assert data["cascade_oip3_dbm"] == pytest.approx(29.59, abs=0.01)
        assert data["stages"][0]["oip3_dbm"] == 20.0

    def test_budget_run_text_prints_cascade_ip3(self, tmp_path):
        result = runner.invoke(app, [
            "budget", "run", "amp_a", "amp_b",
            "--catalog", str(_ip3_catalog(tmp_path))])
        assert result.exit_code == 0, result.output
        assert "级联 IIP3" in result.output
        assert "级联 OIP3" in result.output


def _rag_corpus(tmp_path: Path) -> Path:
    """rag 命令离线小语料：docs/*.md + runs/<id>/meta.json（零网络）。"""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "note.md").write_text(
        "# Resonator Note\n\nresonator tuning stub design.\n", encoding="utf-8")
    runs = tmp_path / "runs"
    run_a = runs / "20260915_000000_ragcli"
    run_a.mkdir(parents=True)
    (run_a / "meta.json").write_text(json.dumps({
        "run_id": run_a.name,
        "model": "wilkinson_power_divider",
        "adapter": "hfss",
        "status": "done",
    }), encoding="utf-8")
    return tmp_path


class TestRagCommands:
    """RAG 词法检索薄壳（rag index/query/explain，离线 tmp 语料）。"""

    def test_rag_help_lists_three_commands(self):
        result = runner.invoke(app, ["rag", "--help"])
        assert result.exit_code == 0, result.output
        for name in ("index", "query", "explain"):
            assert name in result.output

    def test_rag_index_reports_stats(self, tmp_path):
        _rag_corpus(tmp_path)
        result = runner.invoke(app, [
            "rag", "index", "--docs", str(tmp_path / "docs"),
            "--runs", str(tmp_path / "runs")])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["n_chunks"] >= 2
        assert set(data["source_kinds"]) == {"doc", "run"}

    def test_rag_query_scope_docs_hit_with_traceable_citation(self, tmp_path):
        _rag_corpus(tmp_path)
        result = runner.invoke(app, [
            "rag", "query", "resonator",
            "--docs", str(tmp_path / "docs"), "--scope", "docs"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["n_hits"] >= 1
        hit = data["hits"][0]
        assert hit["citation"]["kind"] == "doc"
        # citation 可溯：相对路径回解析后真实存在
        assert (tmp_path / hit["citation"]["path"]).is_file()

    def test_rag_query_scope_runs_hits_meta_entry(self, tmp_path):
        _rag_corpus(tmp_path)
        result = runner.invoke(app, [
            "rag", "query", "wilkinson hfss",
            "--runs", str(tmp_path / "runs"), "--scope", "runs"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["n_indexed"] == 1
        assert any(h["citation"]["kind"] == "run" for h in data["hits"])

    def test_rag_explain_carries_score_breakdown(self, tmp_path):
        _rag_corpus(tmp_path)
        result = runner.invoke(app, [
            "rag", "explain", "resonator", "--top-k", "1",
            "--docs", str(tmp_path / "docs"), "--scope", "docs"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["top_k"] == 1
        breakdown = data["hits"][0]["score_breakdown"]
        assert breakdown and breakdown[0]["term"] == "resonator"

    def test_rag_query_empty_text_fails_with_errors(self, tmp_path):
        _rag_corpus(tmp_path)
        result = runner.invoke(app, [
            "rag", "query", "   ", "--docs", str(tmp_path / "docs"),
            "--scope", "docs"])
        assert result.exit_code == 1
        assert "RAG 检索失败" in result.output
        assert "query 为空" in result.output

    def test_rag_query_missing_docs_dir_fails(self, tmp_path):
        result = runner.invoke(app, [
            "rag", "query", "resonator", "--docs", str(tmp_path / "nope"),
            "--scope", "docs"])
        assert result.exit_code == 1
        assert "索引构建失败" in result.output

    def test_rag_invalid_scope_rejected(self):
        result = runner.invoke(app, ["rag", "query", "x", "--scope", "bogus"])
        assert result.exit_code != 0
        assert "docs|runs|all" in result.output


# ─── calc 实验开关透传 + db 六命令薄壳（2026-09-18）─────────────────────────

_EXPERIMENTAL_KEY = "patch_f0_symbolic_e13"
_EXP_PARAMS = ["-p", "l_mm=40", "-p", "w_mm=50"]


class TestCalcExperimentalPassthrough:
    """calc list 标签 / calc run --allow-experimental 三态透传（默认拒跑）。"""

    @pytest.fixture(autouse=True)
    def _no_env_switch(self, monkeypatch):
        monkeypatch.delenv("RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL", raising=False)

    def test_list_labels_experimental_and_summarises(self):
        result = runner.invoke(app, ["calc", "list"])
        assert result.exit_code == 0, result.output
        assert _EXPERIMENTAL_KEY in result.output
        assert "[实验]" in result.output
        assert "实验性公式 1 个" in result.output

    def test_list_no_experimental_hides_but_reports(self):
        result = runner.invoke(app, ["calc", "list", "--no-experimental"])
        assert result.exit_code == 0, result.output
        assert _EXPERIMENTAL_KEY not in result.output
        assert "已隐藏" in result.output

    def test_list_json_carries_ledger(self):
        result = runner.invoke(app, ["calc", "list", "--json", "--no-experimental"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["include_experimental"] is False
        assert data["experimental"] == [_EXPERIMENTAL_KEY]
        assert all(not c["experimental"] for c in data["calculators"])

    def test_run_experimental_default_rejected(self):
        result = runner.invoke(app, ["calc", "run", _EXPERIMENTAL_KEY, *_EXP_PARAMS])
        assert result.exit_code == 1
        assert "allow_experimental" in result.output

    def test_run_allow_experimental_flag_passes(self):
        result = runner.invoke(app, [
            "calc", "run", _EXPERIMENTAL_KEY, *_EXP_PARAMS, "--allow-experimental", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["experimental"] is True
        assert data["result"]["f0_ghz"] == pytest.approx(1.918754, abs=2e-6)

    def test_run_env_switch_passes_when_flag_absent(self, monkeypatch):
        """缺省（无 flag）读配置/env：env=1 放行——壳层不得把缺省当显式 False。"""
        monkeypatch.setenv("RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL", "1")
        result = runner.invoke(app, ["calc", "run", _EXPERIMENTAL_KEY, *_EXP_PARAMS])
        assert result.exit_code == 0, result.output
        assert "[实验]" in result.output

    def test_run_no_experimental_beats_env(self, monkeypatch):
        monkeypatch.setenv("RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL", "1")
        result = runner.invoke(app, [
            "calc", "run", _EXPERIMENTAL_KEY, *_EXP_PARAMS, "--no-experimental"])
        assert result.exit_code == 1
        assert "allow_experimental" in result.output

    def test_regular_calculator_unaffected(self):
        result = runner.invoke(app, [
            "calc", "run", "patch_length", "-p", "f0_ghz=2.4", "-p", "epsilon_r=3.66",
            "-p", "h_mm=0.508", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["experimental"] is False

    def test_run_json_ok_false_exits_nonzero_with_full_envelope(self):
        """--json 下 ok=False 信封仍完整输出，但退出码非零
        （与 _emit 口径一致；脚本消费方靠 exit code 判成败）。"""
        result = runner.invoke(app, [
            "calc", "run", _EXPERIMENTAL_KEY, *_EXP_PARAMS, "--json"])
        assert result.exit_code != 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "allow_experimental" in data["error"]

    def test_run_json_ok_true_exits_zero(self):
        """--json 下 ok=True 退出码 0（行为不变钉）。"""
        result = runner.invoke(app, [
            "calc", "run", _EXPERIMENTAL_KEY, *_EXP_PARAMS,
            "--allow-experimental", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True


def _seed_registry_runs(tmp_path: Path) -> None:
    for run_id, adapter in (("r_hfss", "hfss"), ("r_fake", "fake")):
        run_dir = tmp_path / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text(json.dumps({
            "run_id": run_id, "model": "patch_antenna", "adapter": adapter,
            "status": "done", "timestamp": "2026-09-18T00:00:00",
        }), encoding="utf-8")


class TestDbCommands:
    """rfauto db 六命令：零逻辑转发 db_service，--db 显式路径隔离。"""

    def test_help_lists_six_commands(self):
        result = runner.invoke(app, ["db", "--help"])
        assert result.exit_code == 0
        for name in ("init", "migrate", "status", "reindex-runs", "query", "analytics-attach"):
            assert name in result.output

    def test_status_missing_then_init_then_migrate(self, tmp_path):
        db = str(tmp_path / "reg.sqlite")
        status = runner.invoke(app, ["db", "status", "--db", db, "--json"])
        assert status.exit_code == 0, status.output
        assert json.loads(status.output)["exists"] is False
        assert not Path(db).exists()

        init = runner.invoke(app, ["db", "init", "--db", db, "--json"])
        assert init.exit_code == 0, init.output
        assert json.loads(init.output)["applied"] >= 1

        migrate = runner.invoke(app, ["db", "migrate", "--db", db, "--json"])
        assert migrate.exit_code == 0, migrate.output
        assert json.loads(migrate.output)["applied"] == 0

        text = runner.invoke(app, ["db", "status", "--db", db])
        assert text.exit_code == 0, text.output
        assert "schema_version=1" in text.output
        assert "runs: 0" in text.output

    def test_reindex_runs_and_query_with_param(self, tmp_path):
        _seed_registry_runs(tmp_path)
        db = str(tmp_path / "reg.sqlite")
        reindex = runner.invoke(app, ["db", "reindex-runs", "--db", db, "--json"])
        assert reindex.exit_code == 0, reindex.output
        assert json.loads(reindex.output)["reindexed"] == 2

        query = runner.invoke(app, [
            "db", "query", "SELECT run_id FROM runs WHERE adapter = ?",
            "-p", "hfss", "--db", db, "--json"])
        assert query.exit_code == 0, query.output
        data = json.loads(query.output)
        assert data["rows"] == [["r_hfss"]]

        text = runner.invoke(app, [
            "db", "query", "SELECT run_id FROM runs ORDER BY run_id", "--db", db])
        assert text.exit_code == 0, text.output
        assert "r_fake" in text.output and "r_hfss" in text.output
        assert "2 行" in text.output

    def test_query_rejection_exits_one_with_reason(self, tmp_path):
        db = str(tmp_path / "reg.sqlite")
        runner.invoke(app, ["db", "init", "--db", db])
        result = runner.invoke(app, ["db", "query", "DROP TABLE runs", "--db", db])
        assert result.exit_code == 1
        assert "查询被拒绝" in result.output

    def test_reindex_missing_runs_dir_is_honest(self, tmp_path):
        result = runner.invoke(app, [
            "db", "reindex-runs", "--runs-dir", str(tmp_path / "no_runs"),
            "--db", str(tmp_path / "reg.sqlite"), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["reindexed"] == 0
        assert "note" in data

    def test_analytics_attach_missing_file_exits_one(self, tmp_path):
        result = runner.invoke(app, [
            "db", "analytics-attach", "--db", str(tmp_path / "nope.sqlite")])
        assert result.exit_code == 1
        assert "不存在" in result.output

    def test_analytics_attach_available_or_honest(self, tmp_path):
        _seed_registry_runs(tmp_path)
        db = str(tmp_path / "reg.sqlite")
        runner.invoke(app, ["db", "reindex-runs", "--db", db])
        result = runner.invoke(app, ["db", "analytics-attach", "--db", db, "--json"])
        if result.exit_code == 0:
            data = json.loads(result.output)
            assert data["attached_as"] == "reg"
            assert data["tables"]["runs"] == 2
        else:
            assert result.exit_code == 1
            assert "DuckDB 直读不可用" in result.output


_SLOT_SUB = ["--h-mm", "1.524", "--eps-r", "3.66", "--freq-ghz", "2.5"]


class TestSlotlineTransitionsCommands:
    """rfauto slotline（2）/ transitions（3）薄壳：零逻辑转发 slotline_service，
    --json 直出信封；越域红字 exit 1；synth 不可达=退 0+realizable=False（D5
    语义，同文件 :578-588 钉）。数值只出
    内核，壳层不复算）。"""

    def test_help_lists_commands(self):
        slot = runner.invoke(app, ["slotline", "--help"])
        assert slot.exit_code == 0
        for name in ("analyze", "synth"):
            assert name in slot.output
        trans = runner.invoke(app, ["transitions", "--help"])
        assert trans.exit_code == 0
        for name in ("msl-slot", "marchand-balun", "marchand2"):
            assert name in trans.output

    def test_analyze_json_and_text(self):
        result = runner.invoke(app, ["slotline", "analyze", "--w-mm", "1.0", *_SLOT_SUB, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["result"]["z0_ohm"] == pytest.approx(110.92, abs=0.01)
        assert data["result"]["segment"] == "low"
        text = runner.invoke(app, ["slotline", "analyze", "--w-mm", "1.0", *_SLOT_SUB])
        assert text.exit_code == 0, text.output
        assert "Z0=110.92" in text.output

    def test_analyze_out_of_domain_exits_one(self):
        result = runner.invoke(app, [
            "slotline", "analyze", "--w-mm", "1.0", "--h-mm", "0.508",
            "--eps-r", "3.66", "--freq-ghz", "2.5"])
        assert result.exit_code == 1
        assert "槽线分析失败" in result.output
        assert "不外推" in result.output

    def test_synth_json_roundtrip_and_unreachable(self):
        result = runner.invoke(app, ["slotline", "synth", "--z0-ohm", "110.92", *_SLOT_SUB, "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["result"]["w_mm"] == pytest.approx(1.0, abs=2e-3)
        # D5 语义对齐（与 marchand-two-section 同形）：超可达区间→
        # ok=True + realizable=False + reason（退 0），非 ok=False 退 1。
        bad = runner.invoke(app, ["slotline", "synth", "--z0-ohm", "500", *_SLOT_SUB])
        assert bad.exit_code == 0
        assert "不可达" in bad.output
        assert "realizable=False" in bad.output
        assert "超出窄槽段可达范围" in bad.output

    def test_msl_slot_and_marchand_balun_json(self):
        args = ["--f0-ghz", "2.5", "--h-mm", "1.524", "--er", "3.66", "--w-slot-mm", "1.0"]
        trans = runner.invoke(app, ["transitions", "msl-slot", *args, "--json"])
        assert trans.exit_code == 0, trans.output
        design = json.loads(trans.output)["design"]
        assert design["l_stub_mm"] == pytest.approx(17.1253, abs=1e-3)  # C6 符号修正（λg/4−Δl）
        assert design["l_short_mm"] == pytest.approx(23.3656, abs=1e-3)
        balun = runner.invoke(app, ["transitions", "marchand-balun", *args, "--json"])
        assert balun.exit_code == 0, balun.output
        bd = json.loads(balun.output)["design"]
        assert bd["d_center_mm"] == pytest.approx(bd["w_msl_mm"] + bd["w_slot_mm"], abs=1e-3)
        text = runner.invoke(app, ["transitions", "marchand-balun", *args])
        assert text.exit_code == 0, text.output
        assert "d_c=" in text.output

    def test_marchand2_defaults_json_and_band_pairing(self):
        result = runner.invoke(app, ["transitions", "marchand2", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["design"]["realizable"] is True
        assert data["design"]["model_metrics"]["all_gates_pass"] is True
        assert data["nominal_params"]["l_sect_mm"] == pytest.approx(18.467, abs=1e-3)
        text = runner.invoke(app, ["transitions", "marchand2"])
        assert text.exit_code == 0, text.output
        assert "PASS" in text.output and "严格可达" in text.output
        # 带沿须成对给出（壳层参数形态守卫，非物理逻辑）
        half = runner.invoke(app, ["transitions", "marchand2", "--band-lo-ghz", "2.3"])
        assert half.exit_code == 1
        assert "成对" in half.output
        bad = runner.invoke(app, ["transitions", "marchand2",
                                  "--band-lo-ghz", "3.0", "--band-hi-ghz", "2.0"])
        assert bad.exit_code == 1
        assert "Marchand 两节综合失败" in bad.output
