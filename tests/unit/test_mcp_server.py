"""MCP Server 单元测试（P4）—— 验证 6 个核心工具的输入输出格式与错误处理。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """create_run 等工具走完整 run_once 链，run 目录按 cwd 落盘——
    不隔离会把 fake run 写进工作区真实 runs/（#173，污染孤例第二源头）。"""
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def mcp_server():
    """返回 MCP Server 实例。"""
    from rfauto.mcp_server import mcp
    return mcp


@pytest.fixture()
def sample_recipe(tmp_path: Path) -> Path:
    """创建一个最小可用的配方文件。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {
            "arm_len_mm": {"value": 20.5, "unit": "mm"},
        },
        "setup": {
            "freq_range_ghz": [1.5, 3.5],
            "points": 11,
        },
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
    }
    path = tmp_path / "test_recipe.yaml"
    import yaml
    path.write_text(yaml.dump(recipe, allow_unicode=True), encoding="utf-8")
    return path


def _extract_result(tool_result):
    """从 ToolResult 提取 dict 数据。"""
    # fastmcp 3.x ToolResult 有 structured_content 属性
    if hasattr(tool_result, 'structured_content') and tool_result.structured_content is not None:
        return tool_result.structured_content
    # fallback: 从 content[0].text 解析
    if hasattr(tool_result, 'content') and tool_result.content:
        return json.loads(tool_result.content[0].text)
    return json.loads(str(tool_result))


class TestMCPToolsRegistered:
    """验证 7 个核心工具全部注册（C3 新增 create_run_async）。"""

    def test_tools_count(self, mcp_server):
        import asyncio
        tools = asyncio.run(mcp_server.list_tools())
        # WP0.2 +2：list_calculators/run_calculator；E11 +1：warm_start_optimize；
        # C13 +1：synthesize_bpf；WP4.7 +1：export_report_pdf；
        # WP3.3 +17：模板库 2 + 战役 3 + 数据集 2 + bands 10（D9 归口）
        # shell-bundle +26（2026-09-15）：回归门 2 + 多 Agent 5 + 自验证环 1 +
        #   uq 3 + farfield 2 + kicad 2 + 电热/寄生 2 + topology 1 + dataset 4 +
        #   vna 回放 1 + F9 叙述 1 + F11 经验 2
        # +2（rag_query/rag_explain，只读词法 BM25 检索薄壳）
        # 接线层 +3（self_heal_run/log_digest/dispersion_report）
        # +6（db_init/db_migrate/db_status/db_reindex_runs/
        #   db_query/db_analytics_attach，注册表薄壳，2026-09-18）
        # +5（slotline_analysis/slotline_synthesis/
        #   msl_slot_transition_design/marchand_balun_design/
        #   marchand_two_section_synthesis，槽线与过渡薄壳）
        # 增量史：导入器+2 → cascade+3 → cm 诊断+3 → vna en+1 → mmt+1 →
        # anchors+2 → si 通道报告+1 → lake+2（index/verify/restore 属本地
        # 运维面不进 MCP 最小面）→ render_constraint_check+1 = 106
        assert len(tools) == 106

    def test_tool_names(self, mcp_server):
        import asyncio
        tools = asyncio.run(mcp_server.list_tools())
        names = {t.name for t in tools}
        expected = {
            "doctor", "list_models", "validate_recipe",
            "create_run", "create_run_async", "poll_job", "get_metrics",
            "synthesize", "budget_analysis", "correlate_measurement", "diagnose",
            "compare_runs", "get_run_artifacts", "get_model_3d",
            "list_calculators", "run_calculator",
            "warm_start_optimize",
            "synthesize_bpf",
            "export_report_pdf",
            # WP3.3 模板库/战役状态/数据集查询/bands 薄壳
            "list_template_specs", "draft_recipe_from_spec",
            "plan_campaign", "save_campaign_plan", "get_campaign_status",
            "list_datasets", "query_dataset",
            "bands_list", "bands_get", "bands_find", "bands_spec_bounds",
            "bands_env_list", "bands_env_get", "bands_env_find",
            "bands_env_delta_t", "bands_env_uq_axis", "bands_env_points",
            # cli-mcp-api-shell-bundle（2026-09-15）scattered 薄壳
            "goldset_regression", "agentbench_regression",
            "rf_propose_params", "rf_run_sampler", "rf_critique_point",
            "rf_spec_cost", "multi_agent_run",
            "autotune_self_verify",
            "uq_yield_at", "uq_design_center",
        "robustness_report", "uq_temperature_zone",
            "farfield_runs", "farfield_view",
            "kicad_extract", "kicad_optimize_cpw",
            "electrothermal_chain", "parasitic_extract_rlc",
            "topology_propose",
            "dataset_coverage", "dataset_annotate_ground_truth",
            "dataset_set_visibility", "dataset_export_hf",
            "vna_offline_replay",
            "vna_en_report",
        "compose_netlist",
        "list_composable_templates",
        "explain_run",
        "nfmeas_ffs_info",
        "nfmeas_cut_view",
        "nfc_coil_evaluate",
        "nfc_coil_synthesize",
        "nfc_coil_q",
        "sar_analytic_plane_wave",
        "cancel_job",
        "wait_job",
            "report_narrative", "rationale_recall", "rationale_checklist",
            "rag_query", "rag_explain",
            # 接线层（内核能力接入生产路径）
            "self_heal_run", "log_digest", "dispersion_report",
            # 注册表数据库薄壳
            "db_init", "db_migrate", "db_status", "db_reindex_runs",
            "db_query", "db_analytics_attach",
            # 槽线与过渡薄壳
            "slotline_analysis", "slotline_synthesis",
            "msl_slot_transition_design", "marchand_balun_design",
            "marchand_two_section_synthesis",
            # 工作目录形态真机产物导入器薄壳
            "discover_workdir_runs", "import_workdir_runs",
            # DP-5 系统级预算引擎+杂散搜索薄壳（df6_dp5cascade）
            "cascade_budget", "spur_search", "if_plan_sweep",
            # df6_dp2diag DP-2 耦合矩阵诊断三件套薄壳（2026-09-24）
            "cm_diagnose_q", "cm_extract_refine", "cm_cat_critique",
            # DP-1 MMT 秒级段表求解薄壳（df6_dp1p2，2026-09-24）
            "mmt_solve",
            # DP-3 物理标定锚注册表薄壳（df6_dp3anchors，2026-09-24）
            "anchors_list", "anchors_inspect",
            # df7 T2 SI 通道报告薄壳（df7_t2，2026-09-25）
            "si_channel_report",
            # df7 F3 runs 湖薄壳（df7_f3lake，2026-09-25；index/verify/restore
            # 本地运维面不进 MCP）
            "lake_query_runs", "lake_pack_campaign",
            # df7wire R4 渲染前声明式几何约束一次求解薄壳（2026-09-26）
            "render_constraint_check",
        }
        assert names == expected


class TestMCPResources:
    """E4c 版本化只读 resources（v2 尾巴）。"""

    def test_resources_registered(self, mcp_server):
        import asyncio
        resources = asyncio.run(mcp_server.list_resources())
        uris = {str(r.uri) for r in resources}
        assert uris == {
            "rfauto://runs/index",
            "rfauto://knowledge/materials",
            "rfauto://knowledge/compat_matrix",
        }

    def test_read_compat_matrix_resource(self, mcp_server, monkeypatch):
        from pathlib import Path

        import anyio
        repo_root = Path(__file__).resolve().parents[2]
        monkeypatch.chdir(repo_root)  # 资源按相对路径读 knowledge/
        content = anyio.run(
            lambda: mcp_server.read_resource("rfauto://knowledge/compat_matrix")
        )
        text = content[0].text if isinstance(content, list) else str(content)
        assert "openems" in text
        assert "verified" in text


class TestDoctor:
    """doctor 工具测试。"""

    def test_doctor_returns_ok(self, mcp_server):
        import asyncio
        result = asyncio.run(mcp_server.call_tool("doctor", {}))
        data = _extract_result(result)
        assert "ok" in data
        assert "checks" in data

    def test_doctor_checks_structure(self, mcp_server):
        import asyncio
        result = asyncio.run(mcp_server.call_tool("doctor", {}))
        data = _extract_result(result)
        for check in data["checks"]:
            assert "name" in check
            assert "status" in check


class TestListModels:
    """list_models 工具测试。"""

    def test_list_models_returns_ok(self, mcp_server):
        import asyncio
        result = asyncio.run(mcp_server.call_tool("list_models", {}))
        data = _extract_result(result)
        assert data["ok"] is True
        assert isinstance(data["models"], list)

    def test_list_models_contains_wilkinson(self, mcp_server):
        import asyncio
        result = asyncio.run(mcp_server.call_tool("list_models", {}))
        data = _extract_result(result)
        assert "wilkinson_power_divider" in data["models"]


class TestValidateRecipe:
    """validate_recipe 工具测试。"""

    def test_valid_recipe(self, mcp_server, sample_recipe):
        import asyncio
        result = asyncio.run(mcp_server.call_tool("validate_recipe", {"recipe_path": str(sample_recipe)}))
        data = _extract_result(result)
        assert data["ok"] is True

    def test_invalid_path(self, mcp_server):
        import asyncio
        result = asyncio.run(mcp_server.call_tool("validate_recipe", {"recipe_path": "/nonexistent/path.yaml"}))
        data = _extract_result(result)
        assert data["ok"] is False
        assert len(data["errors"]) > 0


class TestPollJob:
    """poll_job 工具测试。"""

    def test_poll_nonexistent_job(self, mcp_server):
        import asyncio
        result = asyncio.run(mcp_server.call_tool("poll_job", {"job_id": "nonexistent_id_12345"}))
        data = _extract_result(result)
        assert data["ok"] is True
        assert data["state"] == "unknown"


class TestGetMetrics:
    """get_metrics 工具测试。"""

    def test_get_nonexistent_metrics(self, mcp_server):
        import asyncio
        result = asyncio.run(mcp_server.call_tool("get_metrics", {"run_id": "nonexistent_id_12345"}))
        data = _extract_result(result)
        assert data["ok"] is False
        assert len(data["errors"]) > 0
class TestCreateRun:
    """create_run 工具测试。"""

    def test_create_run_fake_adapter(self, mcp_server, sample_recipe):
        """用 FakeAdapter 跑一次完整仿真。"""
        import asyncio
        result = asyncio.run(mcp_server.call_tool("create_run", {
            "recipe_path": str(sample_recipe),
            "adapter": "fake"
        }))
        data = _extract_result(result)
        assert data["ok"] is True
        assert "run_id" in data
        assert "metrics" in data
        assert "cost" in data
        # 验证 poll_job 可以读到同一份状态
        poll_result = asyncio.run(mcp_server.call_tool("poll_job", {"job_id": data["run_id"]}))
        poll_data = _extract_result(poll_result)
        assert poll_data["ok"] is True
        assert poll_data["state"] == "done"

    def test_create_run_invalid_recipe(self, mcp_server):
        """无效配方应返回错误。"""
        import asyncio
        result = asyncio.run(mcp_server.call_tool("create_run", {
            "recipe_path": "/nonexistent/recipe.yaml",
            "adapter": "fake"
        }))
        data = _extract_result(result)
        assert data["ok"] is False
        assert len(data["errors"]) > 0


class TestExportReportPdf:
    """export_report_pdf 工具（WP4.7）测试。"""

    @staticmethod
    def _make_fake_run(tmp_path: Path) -> str:
        """隔离 cwd 下手工搭最小 run 目录（get_metrics 只读 metrics.json）。"""
        run_id = "20260912_120100_mcp_pdf_smoke"
        results = tmp_path / "runs" / run_id / "results"
        results.mkdir(parents=True, exist_ok=True)
        (results / "metrics.json").write_text(
            json.dumps({"metrics": {"s11_db": -22.5, "cost": 0.42}}),
            encoding="utf-8",
        )
        return run_id

    def test_export_report_pdf_writes_file(self, mcp_server, tmp_path):
        import asyncio
        run_id = self._make_fake_run(tmp_path)
        result = asyncio.run(mcp_server.call_tool(
            "export_report_pdf", {"run_id": run_id}))
        data = _extract_result(result)
        assert data["ok"] is True, data
        assert data["run_id"] == run_id
        pdf_path = Path(data["report"])
        assert pdf_path.exists() and pdf_path.stat().st_size > 0
        assert data["metrics"]["s11_db"] == -22.5

    def test_export_report_pdf_missing_run(self, mcp_server):
        import asyncio
        result = asyncio.run(mcp_server.call_tool(
            "export_report_pdf", {"run_id": "no_such_run_000"}))
        data = _extract_result(result)
        assert data["ok"] is False
        assert len(data["errors"]) > 0


class TestBudgetAnalysisIp3:
    """P2 IP3 级联：MCP budget_analysis 透传 spec.oip3_dbm（手算例对拍）。"""

    @staticmethod
    def _catalog(tmp_path: Path) -> str:
        catalog = {"devices": {
            "amp_a": {"type": "active", "ports": ["in", "out"],
                      "gain_db": 10.0, "nf_db": 3.0, "oip3_dbm": 20.0},
            "amp_b": {"type": "active", "ports": ["in", "out"],
                      "gain_db": 20.0, "nf_db": 6.0, "oip3_dbm": 30.0},
        }}
        path = tmp_path / "catalog_ip3.yaml"
        path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
        return str(path)

    def test_cascade_ip3_present(self, mcp_server, tmp_path):
        import asyncio
        result = asyncio.run(mcp_server.call_tool(
            "budget_analysis",
            {"chain": ["amp_a", "amp_b"], "catalog": self._catalog(tmp_path)}))
        data = _extract_result(result)
        assert data["ok"] is True, data
        body = data["data"]
        assert body["cascade_iip3_dbm"] == pytest.approx(-0.41, abs=0.01)
        assert body["cascade_oip3_dbm"] == pytest.approx(29.59, abs=0.01)
        assert body["stages"][0]["oip3_dbm"] == 20.0


def _rag_corpus(tmp_path: Path) -> Path:
    """rag 工具端到端离线小语料：docs/*.md + runs/<id>/meta.json（零网络）。"""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "note.md").write_text(
        "# Resonator Note\n\nresonator tuning stub design.\n", encoding="utf-8")
    runs = tmp_path / "runs"
    run_a = runs / "20260915_000000_ragmcp"
    run_a.mkdir(parents=True)
    (run_a / "meta.json").write_text(json.dumps({
        "run_id": run_a.name,
        "model": "wilkinson_power_divider",
        "adapter": "hfss",
        "status": "done",
    }), encoding="utf-8")
    return tmp_path


class TestRagTools:
    """rag_query/rag_explain 端到端（fastmcp call_tool，tmp 语料，零网络）。"""

    def test_rag_query_hits_doc_with_traceable_citation(self, mcp_server, tmp_path):
        import asyncio
        _rag_corpus(tmp_path)
        result = asyncio.run(mcp_server.call_tool("rag_query", {
            "text": "resonator", "docs_dir": str(tmp_path / "docs"),
            "runs_dir": str(tmp_path / "runs")}))
        data = _extract_result(result)
        assert data["ok"] is True, data
        assert data["n_indexed"] >= 2
        assert data["n_hits"] >= 1
        hit = data["hits"][0]
        assert hit["citation"]["kind"] == "doc"
        assert (tmp_path / hit["citation"]["path"]).is_file()
        assert "resonator" in hit["snippet"]

    def test_rag_query_null_dirs_skips_sources(self, mcp_server, tmp_path):
        """docs_dir/runs_dir 传 null → 双来源全跳过 → 空索引显式 n_indexed=0。"""
        import asyncio
        _rag_corpus(tmp_path)
        result = asyncio.run(mcp_server.call_tool("rag_query", {
            "text": "resonator", "docs_dir": None, "runs_dir": None}))
        data = _extract_result(result)
        assert data["ok"] is True
        assert data["n_indexed"] == 0
        assert data["hits"] == []

    def test_rag_explain_carries_score_breakdown(self, mcp_server, tmp_path):
        import asyncio
        _rag_corpus(tmp_path)
        result = asyncio.run(mcp_server.call_tool("rag_explain", {
            "text": "resonator", "docs_dir": str(tmp_path / "docs"),
            "runs_dir": None}))
        data = _extract_result(result)
        assert data["ok"] is True, data
        hit = data["hits"][0]
        breakdown = hit["score_breakdown"]
        assert breakdown and breakdown[0]["term"] == "resonator"
        assert breakdown[0]["contribution"] == pytest.approx(hit["score"])

    def test_rag_query_empty_text_error_envelope(self, mcp_server, tmp_path):
        import asyncio
        _rag_corpus(tmp_path)
        result = asyncio.run(mcp_server.call_tool("rag_query", {
            "text": "   ", "docs_dir": str(tmp_path / "docs"),
            "runs_dir": None}))
        data = _extract_result(result)
        assert data["ok"] is False
        assert data["errors"]

    def test_rag_query_missing_dir_error_envelope(self, mcp_server, tmp_path):
        import asyncio
        result = asyncio.run(mcp_server.call_tool("rag_query", {
            "text": "resonator", "docs_dir": str(tmp_path / "no_such_docs"),
            "runs_dir": None}))
        data = _extract_result(result)
        assert data["ok"] is False
        assert data["errors"]
        assert "索引构建失败" in data["errors"][0]


# ─── 实验计算器透传 / db 六工具 / 接线层三工具归位（2026-09-18）──────────────


def _call(mcp_server, tool_name: str, arguments: dict) -> dict:
    """经 fastmcp call_tool 真调用（#270：死壳只在调用期才炸）。"""
    import asyncio

    return _extract_result(asyncio.run(mcp_server.call_tool(tool_name, arguments)))


_EXPERIMENTAL_KEY = "patch_f0_symbolic_e13"


class TestCalculatorExperimentalPassthrough:
    """list_calculators/run_calculator 的 experimental 标签与 allow_experimental
    三态透传（默认不参与、显式开关才启用）。"""

    def test_list_default_includes_experimental_with_label(self, mcp_server):
        data = _call(mcp_server, "list_calculators", {})
        assert data["ok"] is True
        by_name = {c["name"]: c for c in data["calculators"]}
        assert by_name[_EXPERIMENTAL_KEY]["experimental"] is True
        assert data["n_experimental"] >= 1
        assert _EXPERIMENTAL_KEY in data["experimental"]
        assert data["include_experimental"] is True
        # 正式键无实验标签
        assert by_name["patch_length"]["experimental"] is False

    def test_list_exclude_experimental_keeps_ledger(self, mcp_server):
        full = _call(mcp_server, "list_calculators", {})
        data = _call(mcp_server, "list_calculators", {"include_experimental": False})
        names = {c["name"] for c in data["calculators"]}
        assert _EXPERIMENTAL_KEY not in names
        assert len(data["calculators"]) == len(full["calculators"]) - full["n_experimental"]
        # 剔除后名单/计数仍如实报告（可见可审计）
        assert data["n_experimental"] == full["n_experimental"]
        assert data["experimental"] == full["experimental"]

    def test_run_experimental_default_rejected(self, mcp_server, monkeypatch):
        monkeypatch.delenv("RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL", raising=False)
        data = _call(mcp_server, "run_calculator",
                     {"name": _EXPERIMENTAL_KEY, "params": {"l_mm": 40.0, "w_mm": 50.0}})
        assert data["ok"] is False
        assert data["experimental"] is True
        assert "allow_experimental" in data["error"]

    def test_run_experimental_explicit_allow(self, mcp_server):
        data = _call(mcp_server, "run_calculator", {
            "name": _EXPERIMENTAL_KEY, "params": {"l_mm": 40.0, "w_mm": 50.0},
            "allow_experimental": True})
        assert data["ok"] is True
        assert data["experimental"] is True
        # 三点核对之一：(40,50)=1.918754 GHz（内核数值，非壳层产出）
        assert data["result"]["f0_ghz"] == pytest.approx(1.918754, abs=2e-6)

    def test_run_explicit_false_beats_env(self, mcp_server, monkeypatch):
        monkeypatch.setenv("RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL", "1")
        data = _call(mcp_server, "run_calculator", {
            "name": _EXPERIMENTAL_KEY, "params": {"l_mm": 40.0, "w_mm": 50.0},
            "allow_experimental": False})
        assert data["ok"] is False
        assert data["experimental"] is True

    def test_run_env_switch_passes_when_arg_absent(self, mcp_server, monkeypatch):
        """缺省（无 allow_experimental 实参）读 env：env=1 放行——壳层不得
        把缺省当显式 False（#277 三态）。"""
        monkeypatch.setenv("RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL", "1")
        data = _call(mcp_server, "run_calculator",
                     {"name": _EXPERIMENTAL_KEY, "params": {"l_mm": 40.0, "w_mm": 50.0}})
        assert data["ok"] is True
        assert data["experimental"] is True

    def test_regular_calculator_tagged_not_experimental(self, mcp_server):
        data = _call(mcp_server, "run_calculator", {
            "name": "patch_length",
            "params": {"f0_ghz": 2.4, "epsilon_r": 3.66, "h_mm": 0.508}})
        assert data["ok"] is True
        assert data["experimental"] is False


def _seed_runs(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    for run_id, adapter in (("r_hfss", "hfss"), ("r_fake", "fake")):
        run_dir = runs / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text(json.dumps({
            "run_id": run_id, "model": "patch_antenna", "adapter": adapter,
            "status": "done", "timestamp": f"2026-09-18T00:00:0{len(run_id)}",
        }), encoding="utf-8")


class TestDbTools:
    """注册表六工具：零逻辑转发 db_service；隔离 cwd + 显式 db_path。"""

    def test_status_missing_file_not_created(self, mcp_server, tmp_path):
        target = tmp_path / "reg.sqlite"
        data = _call(mcp_server, "db_status", {"db_path": str(target)})
        assert data["ok"] is True
        assert data["exists"] is False
        assert data["schema_version"] == 0
        assert not target.exists(), "status 不得隐式建库"

    def test_init_then_migrate_idempotent(self, mcp_server, tmp_path):
        target = str(tmp_path / "reg.sqlite")
        first = _call(mcp_server, "db_init", {"db_path": target})
        assert first["ok"] is True
        assert first["schema_version"] >= 1
        assert first["applied"] >= 1
        second = _call(mcp_server, "db_migrate", {"db_path": target})
        assert second["ok"] is True
        assert second["applied"] == 0
        status = _call(mcp_server, "db_status", {"db_path": target})
        assert status["exists"] is True
        assert set(status["tables"]) >= {"runs", "jobs", "approvals", "datasets"}

    def test_reindex_then_query_with_params(self, mcp_server, tmp_path):
        _seed_runs(tmp_path)
        target = str(tmp_path / "reg.sqlite")
        reindexed = _call(mcp_server, "db_reindex_runs",
                          {"runs_dir": "runs", "db_path": target})
        assert reindexed["ok"] is True
        assert reindexed["reindexed"] == 2
        assert reindexed["failed"] == 0
        data = _call(mcp_server, "db_query", {
            "sql": "SELECT run_id FROM runs WHERE adapter = ? ORDER BY run_id",
            "params": ["hfss"], "db_path": target})
        assert data["ok"] is True
        assert data["columns"] == ["run_id"]
        assert data["rows"] == [["r_hfss"]]
        assert data["truncated"] is False

    def test_query_limit_truncation_flag(self, mcp_server, tmp_path):
        _seed_runs(tmp_path)
        target = str(tmp_path / "reg.sqlite")
        _call(mcp_server, "db_reindex_runs", {"runs_dir": "runs", "db_path": target})
        data = _call(mcp_server, "db_query",
                     {"sql": "SELECT run_id FROM runs", "limit": 1, "db_path": target})
        assert data["ok"] is True
        assert data["row_count"] == 1
        assert data["truncated"] is True

    @pytest.mark.parametrize("bad_sql", [
        "DELETE FROM runs",
        "SELECT 1; DROP TABLE runs",
        "SELECT * FROM runs -- comment",
        "PRAGMA table_info(runs)",
    ])
    def test_query_whitelist_rejection_is_envelope_not_raise(self, mcp_server, tmp_path, bad_sql):
        target = str(tmp_path / "reg.sqlite")
        _call(mcp_server, "db_init", {"db_path": target})
        data = _call(mcp_server, "db_query", {"sql": bad_sql, "db_path": target})
        assert data["ok"] is False
        assert data["errors"]
        assert "查询被拒绝" in data["errors"][0]

    def test_query_execution_error_is_envelope(self, mcp_server, tmp_path):
        target = str(tmp_path / "reg.sqlite")
        _call(mcp_server, "db_init", {"db_path": target})
        data = _call(mcp_server, "db_query",
                     {"sql": "SELECT x FROM no_such_table", "db_path": target})
        assert data["ok"] is False
        assert "查询执行失败" in data["errors"][0]

    def test_reindex_missing_runs_dir_reports_zero(self, mcp_server, tmp_path):
        data = _call(mcp_server, "db_reindex_runs", {
            "runs_dir": str(tmp_path / "no_runs"), "db_path": str(tmp_path / "reg.sqlite")})
        assert data["ok"] is True
        assert data["reindexed"] == 0
        assert "note" in data

    def test_analytics_attach_missing_file_is_honest(self, mcp_server, tmp_path):
        data = _call(mcp_server, "db_analytics_attach",
                     {"db_path": str(tmp_path / "nope.sqlite")})
        assert data["ok"] is False
        assert "不存在" in data["reason"]

    def test_analytics_attach_available_or_honest_reason(self, mcp_server, tmp_path):
        """DuckDB 直读：可用时逐表计数正确；不可用时 ok=False + reason（不 raise）。"""
        _seed_runs(tmp_path)
        target = str(tmp_path / "reg.sqlite")
        _call(mcp_server, "db_reindex_runs", {"runs_dir": "runs", "db_path": target})
        data = _call(mcp_server, "db_analytics_attach", {"db_path": target, "sample_limit": 1})
        if data["ok"]:
            assert data["attached_as"] == "reg"
            assert data["tables"]["runs"] == 2
            assert len(data["sample_runs"]) == 1
        else:
            assert data["reason"]


# openEMS 网格守卫失守的真实指纹（#152）：timestep 塌缩 + CalcPort IndexError
_TIMESTEP_COLLAPSE_LOG = (
    "[INFO] openEMS v0.6.35 -- start\n"
    "time step: 1.2e-13 s\n"
    "CalcPort: port_index out of range\n"
    "Traceback (most recent call last):\n"
    "IndexError: calcport index error\n"
    "return code: 1\n"
)

_WIRING_TOOLS = ("self_heal_run", "log_digest", "dispersion_report")
_DB_TOOLS = ("db_init", "db_migrate", "db_status", "db_reindex_runs",
             "db_query", "db_analytics_attach")
_SLOTLINE_TOOLS = ("slotline_analysis", "slotline_synthesis",
                   "msl_slot_transition_design", "marchand_balun_design",
                   "marchand_two_section_synthesis")


class TestWiringToolsConsistency:
    """自愈环/日志蒸馏/材料色散三类工具归位本文件：#270 可调用性
    双检（dis LOAD_GLOBAL 对 globals∪builtins + AST 惰性 import 目标 hasattr）
    + 逐工具 call_tool 烟测；db 六工具同批纳入双检；槽线/过渡五工具同法。"""

    @staticmethod
    def _tools_by_name(mcp_server) -> dict:
        import asyncio

        return {t.name: t for t in asyncio.run(mcp_server.list_tools())}

    @pytest.mark.parametrize("tool_name", [*_WIRING_TOOLS, *_DB_TOOLS, *_SLOTLINE_TOOLS])
    def test_callability_double_check(self, mcp_server, tool_name):
        """#270 双检：函数体全局名可解析 + 惰性 import 目标真实存在。"""
        import ast

        from tests.unit.test_mcp_tool_consistency import (
            MCP_SERVER_PY,
            _callability_issues,
            _unresolved_load_globals,
        )

        tool = self._tools_by_name(mcp_server)[tool_name]
        assert _unresolved_load_globals(tool.fn) == []
        tree = ast.parse(MCP_SERVER_PY.read_text(encoding="utf-8"))
        assert _callability_issues(tool, tree) == []

    @pytest.mark.parametrize("tool_name", [*_WIRING_TOOLS, *_DB_TOOLS, *_SLOTLINE_TOOLS])
    def test_docstring_args_match_signature(self, mcp_server, tool_name):
        """描述/签名对齐：docstring Args 段无幽灵参数，且覆盖全部真实参数。"""
        from tests.unit.test_mcp_tool_consistency import _documented_args, _schema_params

        tool = self._tools_by_name(mcp_server)[tool_name]
        documented = set(_documented_args(tool.fn))
        assert documented == _schema_params(tool), (tool_name, documented)

    def test_self_heal_run_smoke(self, mcp_server, tmp_path):
        run_dir = tmp_path / "runs" / "r_heal"
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text(json.dumps({
            "run_id": "r_heal", "model": "wilkinson_power_divider",
            "adapter": "openems", "status": "failed"}), encoding="utf-8")
        (run_dir / "solver.log").write_text(_TIMESTEP_COLLAPSE_LOG, encoding="utf-8")

        data = _call(mcp_server, "self_heal_run", {"run_id": "r_heal"})
        assert data["ok"] is True
        assert data["verdict"] == "diagnosed"
        assert data["lesson_ref"] == "#152"
        assert data["llm_used"] is False
        assert data["advisory_only"] is True
        assert data["actions"]

        missing = _call(mcp_server, "self_heal_run", {"run_id": "no_such_run"})
        assert missing["ok"] is False
        assert missing["errors"]

    def test_log_digest_smoke(self, mcp_server, tmp_path):
        log_path = tmp_path / "openems_stdout.log"
        log_path.write_text(_TIMESTEP_COLLAPSE_LOG, encoding="utf-8")

        data = _call(mcp_server, "log_digest", {"path": str(log_path)})
        assert data["ok"] is True
        assert data["digest"]["rc"] == 1
        assert "calcport_index_error" in data["digest"]["signatures"]
        assert data["digest"]["metrics"]["timestep_s"] == pytest.approx(1.2e-13)

        missing = _call(mcp_server, "log_digest", {"path": str(tmp_path / "nope.log")})
        assert missing["ok"] is False
        assert missing["errors"]

    def test_dispersion_report_smoke(self, mcp_server, monkeypatch):
        # 只读 configs/materials.yaml（按 cwd 相对路径）→ 切回仓库根
        monkeypatch.chdir(Path(__file__).resolve().parents[2])
        data = _call(mcp_server, "dispersion_report", {
            "material": "rogers4350b_h0.508_dispersion", "band_ghz": [1.0, 10.0]})
        assert data["ok"] is True
        assert data["gate"]["passed"] is True
        assert data["gate"]["verdict"] == "constant_eps_r_ok"
        assert data["eps_r_at_meas"] == pytest.approx(3.66)

        unknown = _call(mcp_server, "dispersion_report",
                        {"material": "no_such_material", "band_ghz": [1.0, 10.0]})
        assert unknown["ok"] is False
        assert unknown["errors"]


_SLOT_SUB = {"h_mm": 1.524, "epsilon_r": 3.66, "freq_ghz": 2.5}


class TestSlotlineTransitionTools:
    """槽线/过渡五工具 call_tool 烟测：零逻辑转发 slotline_service，数值只出
    确定性内核（锚 core/slotline_transitions 设计点：w=1.0/h=1.524/εr=3.66@2.5GHz →
    Z0=110.92Ω、εeff=1.6462、λ'=93.462mm；名义两节 Marchand (w,s,ℓ)=
    (1.7616,0.1016,18.467)mm）；越域/不可达如实进信封不抛出。"""

    def test_slotline_analysis_anchor(self, mcp_server):
        data = _call(mcp_server, "slotline_analysis", {"w_mm": 1.0, **_SLOT_SUB})
        assert data["ok"] is True
        r = data["result"]
        assert r["segment"] == "low"
        assert r["z0_ohm"] == pytest.approx(110.92, abs=0.01)
        assert r["eps_eff"] == pytest.approx(1.6462, abs=1e-4)
        assert r["lambda_g_mm"] == pytest.approx(93.462, abs=1e-3)

    def test_slotline_analysis_out_of_domain_is_envelope(self, mcp_server):
        # 仓库缺省叠层 h=0.508@2.5GHz：d/λ0=0.0042<0.006 落域外 → 拒绝不外推
        data = _call(mcp_server, "slotline_analysis",
                     {"w_mm": 1.0, "h_mm": 0.508, "epsilon_r": 3.66, "freq_ghz": 2.5})
        assert data["ok"] is False
        assert "d/λ0" in data["error"]

    def test_slotline_synthesis_roundtrip(self, mcp_server):
        data = _call(mcp_server, "slotline_synthesis", {"z0_ohm": 110.92, **_SLOT_SUB})
        assert data["ok"] is True
        assert data["realizable"] is True
        assert data["result"]["w_mm"] == pytest.approx(1.0, abs=2e-3)
        unreachable = _call(mcp_server, "slotline_synthesis",
                            {"z0_ohm": 500.0, **_SLOT_SUB})
        # D5 语义统一：超可达区间=合法结果（ok=True + realizable=False + reason）
        assert unreachable["ok"] is True
        assert unreachable["realizable"] is False
        assert "可达范围" in unreachable["reason"]

    def test_msl_slot_transition_design_anchor(self, mcp_server):
        data = _call(mcp_server, "msl_slot_transition_design",
                     {"f0_ghz": 2.5, "h_mm": 1.524, "er": 3.66, "w_slot_mm": 1.0})
        assert data["ok"] is True
        d = data["design"]
        assert d["w_msl_mm"] == pytest.approx(3.3439, abs=1e-3)
        assert d["l_stub_mm"] == pytest.approx(17.1253, abs=1e-3)  # C6 符号修正（λg/4−Δl）
        assert d["l_short_mm"] == pytest.approx(23.3656, abs=1e-3)
        assert set(data["gates"]) == {"band_max_s11_db_le", "excess_loss_db_f0_le"}

    def test_marchand_balun_design_geometry_identities(self, mcp_server):
        data = _call(mcp_server, "marchand_balun_design",
                     {"f0_ghz": 2.5, "h_mm": 1.524, "er": 3.66, "w_slot_mm": 1.0})
        assert data["ok"] is True
        d = data["design"]
        assert d["d_center_mm"] == pytest.approx(d["w_msl_mm"] + d["w_slot_mm"], abs=1e-3)
        assert d["a2_mm"] - d["a1_mm"] == pytest.approx(d["w_slot_mm"], abs=1e-3)

    def test_marchand_two_section_nominal_and_unrealizable(self, mcp_server):
        nominal = _call(mcp_server, "marchand_two_section_synthesis", {})
        assert nominal["ok"] is True
        assert nominal["design"]["realizable"] is True
        assert nominal["design"]["model_metrics"]["all_gates_pass"] is True
        assert nominal["nominal_params"]["w_mm"] == pytest.approx(1.7616, abs=1e-3)
        assert nominal["nominal_params"]["s_mm"] == pytest.approx(0.1016, abs=1e-3)
        assert nominal["nominal_params"]["r_bal_se_ohm"] == pytest.approx(140.0)
        # 常规 50→100Ω 差分：边耦合微带不可达 → 合法结果 realizable=False，非 error
        conv = _call(mcp_server, "marchand_two_section_synthesis",
                     {"z_bal_diff_ohm": 100.0})
        assert conv["ok"] is True
        assert conv["design"]["realizable"] is False
        bad = _call(mcp_server, "marchand_two_section_synthesis",
                    {"band_ghz": [3.0, 2.0]})
        assert bad["ok"] is False
        assert "band_ghz" in bad["error"]


class TestMainEntry:
    """rfauto-mcp console script（F4）：pyproject [project.scripts] → mcp_server.main。"""

    def test_main_is_callable_and_runs_stdio(self, monkeypatch):
        import rfauto.mcp_server as module

        assert callable(module.main)
        calls: list = []
        monkeypatch.setattr(module.mcp, "run", lambda **kw: calls.append(kw))
        module.main()
        assert calls == [{"transport": "stdio"}]

    def test_pyproject_console_script_points_to_main(self):
        import tomllib

        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        scripts = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]
        assert scripts["rfauto-mcp"] == "rfauto.mcp_server:main"
        assert scripts["rfauto"] == "rfauto.cli.main:app"

    def test_dunder_main_dispatches_to_main(self):
        """`python -m rfauto.mcp_server` 与 console script 同源（都走 main()）。"""
        import ast

        source = (Path(__file__).resolve().parents[2] / "src" / "rfauto" / "mcp_server.py"
                  ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        guard_calls: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.If) and "__main__" in ast.dump(node.test):
                guard_calls.extend(
                    n.func.id for n in ast.walk(node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name))
        assert guard_calls == ["main"]


class TestLakeTools:
    """lake_query_runs/lake_pack_campaign（df7 F3 薄壳）透传冒烟。

    index/verify/restore 属本地运维面不进 MCP（最小面注记，mcp_server.py）；
    查询面用例先经 service build_runs_index 备好索引库（测试自备前置），
    工具本身只透传 service 信封。autouse chdir 隔离（#144，零触真实 runs/）。
    """

    @pytest.fixture(autouse=True)
    def _require_extras(self):
        pytest.importorskip("duckdb", reason="湖索引需要 dataset extra（duckdb）")
        pytest.importorskip("zstandard", reason="冷层压实需要 zstandard（tar.zst）")

    @staticmethod
    def _call(mcp_server, tool_name: str, arguments: dict) -> dict:
        import asyncio
        result = asyncio.run(mcp_server.call_tool(tool_name, arguments))
        return _extract_result(result)

    def test_lake_pack_campaign_then_query_runs(self, mcp_server, tmp_path):
        """pack 透传（pack+manifest 落盘）→ service 建索引 → query 透传过滤。"""
        campaign = tmp_path / "runs" / "campaign_x"
        (campaign / "pt1").mkdir(parents=True)
        (campaign / "pt1" / "meta.json").write_text(json.dumps({
            "run_id": "x", "model": "mline", "adapter": "fake",
            "study_name": "s1", "status": "done",
            "timestamp": "2026-09-01T00:00:00+00:00",
        }), encoding="utf-8")
        (campaign / "pt1" / "sparams.csv").write_text(
            "freq_hz,s11_db\n2.0e9,-10.5\n", encoding="utf-8")
        out = tmp_path / "packs" / "campaign_x.tar.zst"

        packed = self._call(mcp_server, "lake_pack_campaign", {
            "campaign_dir": str(campaign), "out_path": str(out)})
        assert packed["ok"] is True, packed.get("errors")
        assert packed["n_files"] == 2
        assert packed["pack_sha256"]
        assert Path(packed["pack_path"]).is_file()
        assert Path(packed["manifest_path"]).is_file()

        from rfauto.service.lake_service import build_runs_index
        db = tmp_path / "lake.duckdb"
        built = build_runs_index(tmp_path / "runs", db_path=db)
        assert built["ok"], built.get("errors")

        queried = self._call(mcp_server, "lake_query_runs", {
            "db_path": str(db), "template": "mline"})
        assert queried["ok"] is True, queried.get("errors")
        assert queried["n_rows"] == 1
        assert queried["rows"][0]["path"] == "campaign_x/pt1"
        assert queried["rows"][0]["adapter"] == "fake"
        # 信封单源字段（table/db_path）随透传带出
        assert queried["table"] == "runs_lake_index"

    def test_lake_query_runs_missing_db_honest(self, mcp_server, tmp_path):
        """库不存在 → ok=False 信封（service 口径透传，不抛出）。"""
        data = self._call(mcp_server, "lake_query_runs", {
            "db_path": str(tmp_path / "nope.duckdb")})
        assert data["ok"] is False
        assert data["errors"] and "不存在" in data["errors"][0]

    def test_lake_pack_campaign_missing_dir_honest(self, mcp_server, tmp_path):
        data = self._call(mcp_server, "lake_pack_campaign", {
            "campaign_dir": str(tmp_path / "nope"),
            "out_path": str(tmp_path / "x.tar.zst")})
        assert data["ok"] is False
        assert data["errors"] and "不存在" in data["errors"][0]


class TestRenderConstraintCheckTool:
    """render_constraint_check（df7wire R4 薄壳）透传冒烟。

    stub 调用钉零逻辑转发；真实 SAT 用例（z3 importorskip）钉端到端
    verdict 面。autouse chdir 隔离（#144，零触真实 runs/）。
    """

    @staticmethod
    def _call(mcp_server, arguments: dict) -> dict:
        import asyncio
        result = asyncio.run(mcp_server.call_tool("render_constraint_check",
                                                  arguments))
        return _extract_result(result)

    def test_passthrough_stub(self, mcp_server, monkeypatch):
        canned = {"ok": True, "status": "sat", "conflict_rule_ids": [],
                  "witness": {"mesh_resolution_mm": 0.5, "near_mm": 0.125}}
        monkeypatch.setattr(
            "rfauto.service.render_constraint_service.evaluate_render_constraints",
            lambda config: canned)
        assert self._call(mcp_server, {"config": {"mesh_resolution_mm": 0.5}}) == canned

    def test_bad_config_honest_envelope(self, mcp_server):
        """config 形状非法（dict 内容违约）→ service ValueError 收进
        ok=False 信封（不炸会话）；非 dict 入参在 fastmcp schema 校验层
        即拒（transport 契约，不经本工具函数体）。"""
        data = self._call(mcp_server, {"config": {"min_line_spacing_mm": -1.0}})
        assert data["ok"] is False
        assert data["error"] and "min_line_spacing_mm" in data["error"]

    def test_real_sat_verdict_end_to_end(self, mcp_server):
        """真实求解（z3 可用时）：可行域内钉值 → ok=True/status=sat+witness。"""
        pytest.importorskip("z3", reason="R4 求解需要 z3-solver")
        data = self._call(mcp_server, {"config": {
            "mesh_resolution_mm": 0.5, "near_ratio": 4.0,
            "min_gap_mm": 0.5}})
        assert data["ok"] is True
        assert data["status"] == "sat"
        assert data["witness"], data
        assert data["assembled"]["rules"]
