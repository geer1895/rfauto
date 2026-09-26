"""WP3.3 MCP 工具面全量开放单测（方案 §4 WP3.3 行）。

四域薄壳工具的 MCP 端到端（call_tool 走 fastmcp 全链，零真机零网络）：
- 模板库：list_template_specs / draft_recipe_from_spec（注册表 describe 自动清单）
- 战役状态：plan_campaign / save_campaign_plan / get_campaign_status
- 数据集查询：list_datasets / query_dataset（duckdb 可用时）
- bands 十接口（D9 行归口 WP3.3 的 MCP 薄壳）

口径：清单由 service 注册表自动生成（无手工静态名单）；数值只在确定性
内核（铁律 7）——本文件断言的全部数字都来自 core 层标准常量/闭式综合。
chdir 隔离零污染（#144）：campaign/dataset 产物都落 tmp_path。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """战役落盘/数据集物化按 cwd 相对路径落盘——不隔离会污染真实 runs/（#144）。"""
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def mcp_server():
    from rfauto.mcp_server import mcp
    return mcp


@pytest.fixture()
def sample_recipe(tmp_path: Path) -> Path:
    """最小可用配方（有 objectives，plan_campaign 可立战役）。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
    }
    path = tmp_path / "recipe_wp33.yaml"
    path.write_text(yaml.dump(recipe, allow_unicode=True), encoding="utf-8")
    return path


def _call(mcp_server, name: str, args: dict) -> dict:
    result = asyncio.run(mcp_server.call_tool(name, args))
    if hasattr(result, "structured_content") and result.structured_content is not None:
        return result.structured_content
    if hasattr(result, "content") and result.content:
        return json.loads(result.content[0].text)
    return json.loads(str(result))


# ── 模板库（E2 TemplateSpec 注册表） ──────────────────────────────────────────

class TestTemplateSpecTools:
    def test_list_template_specs_registry_generated(self, mcp_server):
        data = _call(mcp_server, "list_template_specs", {})
        assert data["ok"] is True
        names = {t["name"] for t in data["templates"]}
        # 清单由 TEMPLATE_SPECS.describe() 自动生成：锚模板必须在列
        assert {"mline", "wilkinson"} <= names
        for t in data["templates"]:
            assert set(t["components"]) == {
                "render_script", "synthesizer", "fake_model", "hfss_plugin"}
            assert isinstance(t["physics_roles"], dict)

    def test_draft_recipe_from_spec_mline(self, mcp_server):
        data = _call(mcp_server, "draft_recipe_from_spec",
                     {"name": "mline", "params": {"z0_ohm": 50, "freq_ghz": 2.5}})
        assert data["ok"] is True, data
        assert data["template"] == "mline"
        draft = data["recipe_draft"]
        # 线宽由 skrf HJ 精算（非文档毫米数）：draft 必须含参数化结果
        assert draft, "配方草稿不应为空"

    def test_draft_recipe_unknown_template(self, mcp_server):
        data = _call(mcp_server, "draft_recipe_from_spec",
                     {"name": "no_such_template"})
        assert data["ok"] is False
        assert "no_such_template" in data["error"]


# ── 战役状态（campaign_manager 确定性状态机） ─────────────────────────────────

class TestCampaignTools:
    def test_plan_campaign_deterministic_stages(self, mcp_server, sample_recipe):
        data = _call(mcp_server, "plan_campaign", {"recipe_path": str(sample_recipe)})
        assert data["ok"] is True, data
        stage_names = [s["stage"] for s in data["stages"]]
        assert stage_names[:5] == ["calibrate", "prefilter", "tune",
                                   "tolerance", "report"]
        assert "final_verify" in stage_names  # high_adapter 默认 hfss
        verify = next(s for s in data["stages"] if s["stage"] == "final_verify")
        assert verify["license_gated"] is True
        assert data["campaign_schema"] == "rfauto-campaign-plan-v1.1"

    def test_plan_campaign_high_adapter_none(self, mcp_server, sample_recipe):
        data = _call(mcp_server, "plan_campaign",
                     {"recipe_path": str(sample_recipe), "high_adapter": "none"})
        assert data["ok"] is True
        assert "final_verify" not in [s["stage"] for s in data["stages"]]

    def test_plan_campaign_missing_recipe(self, mcp_server):
        data = _call(mcp_server, "plan_campaign",
                     {"recipe_path": "/nonexistent/recipe.yaml"})
        assert data["ok"] is False
        assert data["errors"]

    def test_save_then_status_roundtrip(self, mcp_server, sample_recipe, tmp_path):
        plan_result = _call(mcp_server, "plan_campaign",
                            {"recipe_path": str(sample_recipe)})
        out_dir = tmp_path / "runs" / "camp_001"
        saved = _call(mcp_server, "save_campaign_plan",
                      {"plan": plan_result, "out_dir": str(out_dir)})
        assert saved["ok"] is True, saved
        assert (out_dir / "campaign.plan.json").exists()

        # 目录形态与文件形态都可查询
        by_dir = _call(mcp_server, "get_campaign_status", {"plan_path": str(out_dir)})
        assert by_dir["ok"] is True
        assert by_dir["plan"]["campaign_schema"] == "rfauto-campaign-plan-v1.1"
        by_file = _call(mcp_server, "get_campaign_status",
                        {"plan_path": str(out_dir / "campaign.plan.json")})
        assert by_file["ok"] is True
        assert by_file["plan"]["stages"] == plan_result["stages"]

    def test_status_missing_plan(self, mcp_server, tmp_path):
        data = _call(mcp_server, "get_campaign_status",
                     {"plan_path": str(tmp_path / "ghost")})
        assert data["ok"] is False
        assert "战役计划不存在" in data["errors"][0]

    def test_status_corrupt_json(self, mcp_server, tmp_path):
        bad = tmp_path / "bad_plan"
        bad.mkdir()
        (bad / "campaign.plan.json").write_text("{not json", encoding="utf-8")
        data = _call(mcp_server, "get_campaign_status", {"plan_path": str(bad)})
        assert data["ok"] is False

    def test_list_campaign_plans_overview(self, mcp_server, sample_recipe, tmp_path):
        plan_result = _call(mcp_server, "plan_campaign",
                            {"recipe_path": str(sample_recipe)})
        _call(mcp_server, "save_campaign_plan",
              {"plan": plan_result, "out_dir": str(tmp_path / "runs" / "camp_001")})
        from rfauto.service.campaign_manager import list_campaign_plans
        overview = list_campaign_plans("runs")
        assert overview["ok"] is True
        assert overview["n_campaigns"] == 1
        item = overview["campaigns"][0]
        assert item["model"] == "wilkinson_power_divider"
        assert item["n_stages"] == len(plan_result["stages"])


# ── 数据集查询（E11 数据面） ──────────────────────────────────────────────────

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _seed_one_run(root: Path) -> None:
    """1 个 mline run × 2 trials（照 test_dataset_service runs_env 口径）。"""
    _write_json(root / "run_a" / "meta.json", {
        "run_id": "run_a", "model": "mline", "adapter": "fake",
        "algorithm": "tune", "study_name": "s1", "seed": 42,
        "aedt_version": "fake", "ads_version": "", "git_sha": "abc1234",
        "timestamp": "2026-09-13T00:00:00+00:00", "status": "done"})
    _write_json(root / "run_a" / "trials" / "trial_0.json", {
        "trial_number": 0, "params": {"w_mm": 1.0},
        "metrics": {"s11_db_max_in_band": -10.0}, "cost": 0.05})
    _write_json(root / "run_a" / "trials" / "trial_1.json", {
        "trial_number": 1, "params": {"w_mm": 2.0},
        "metrics": {"s11_db_max_in_band": -20.0}, "cost": 0.5})


class TestDatasetTools:
    def test_list_datasets_empty_root_is_ok(self, mcp_server):
        data = _call(mcp_server, "list_datasets", {})
        assert data["ok"] is True
        assert data["n_datasets"] == 0

    def test_list_and_query_roundtrip(self, mcp_server):
        pytest.importorskip("duckdb", reason="query 需要 dataset extra（duckdb）")
        pytest.importorskip("pyarrow", reason="query 需要 dataset extra（pyarrow）")
        _seed_one_run(Path("runs"))
        from rfauto.service.dataset_service import materialize_dataset
        mat = materialize_dataset(None, name="wp33_demo")
        assert mat["ok"] is True, mat

        listed = _call(mcp_server, "list_datasets", {})
        assert listed["ok"] is True
        assert listed["n_datasets"] == 1
        assert listed["datasets"][0]["name"] == "wp33_demo"
        assert listed["datasets"][0]["n_points"] == 2

        rows = _call(mcp_server, "query_dataset", {"name": "wp33_demo"})
        assert rows["ok"] is True
        assert rows["n_rows"] == 2
        # 宽表 schema（dataset_service.DATASET_SCHEMA）：w_mm 在 params_json 内
        w_vals = {json.loads(r["params_json"])["w_mm"] for r in rows["rows"]}
        assert w_vals == {1.0, 2.0}

    def test_query_where_columns_limit(self, mcp_server):
        pytest.importorskip("duckdb", reason="query 需要 dataset extra（duckdb）")
        pytest.importorskip("pyarrow", reason="query 需要 dataset extra（pyarrow）")
        _seed_one_run(Path("runs"))
        from rfauto.service.dataset_service import materialize_dataset
        assert materialize_dataset(None, name="wp33_demo")["ok"]

        filtered = _call(mcp_server, "query_dataset",
                         {"name": "wp33_demo", "where": "cost < 0.1"})
        assert filtered["ok"] is True
        assert filtered["n_rows"] == 1
        assert filtered["rows"][0]["cost"] == 0.05

        cols = _call(mcp_server, "query_dataset",
                     {"name": "wp33_demo",
                      "columns": ["run_id", "cost"], "limit": 1})
        assert cols["ok"] is True
        assert cols["columns"] == ["run_id", "cost"]
        assert cols["n_rows"] == 1

        by_model = _call(mcp_server, "query_dataset",
                         {"name": "wp33_demo", "model": "mline"})
        assert by_model["ok"] is True and by_model["n_rows"] == 2

    def test_query_rejects_injection_and_missing_dataset(self, mcp_server):
        pytest.importorskip("duckdb", reason="query 需要 dataset extra（duckdb）")
        bad_where = _call(mcp_server, "query_dataset",
                          {"name": "wp33_demo", "where": "1=1; DROP TABLE x"})
        assert bad_where["ok"] is False

        missing = _call(mcp_server, "query_dataset", {"name": "ghost_ds"})
        assert missing["ok"] is False
        assert "数据集不存在" in missing["errors"][0]


# ── bands 十接口（D9 归口 WP3.3 的 MCP 薄壳） ─────────────────────────────────

class TestBandsTools:
    def test_bands_list_registry_generated(self, mcp_server):
        data = _call(mcp_server, "bands_list", {})
        assert data["ok"] is True
        assert data["count"] > 0 and data["count"] == data["total"]
        filtered = _call(mcp_server, "bands_list", {"standard": "3GPP"})
        assert filtered["ok"] is True
        assert {b["key"] for b in filtered["bands"]} >= {"gpp_n41", "gpp_n78"}

    def test_bands_get_n78(self, mcp_server):
        data = _call(mcp_server, "bands_get", {"key": "gpp_n78"})
        assert data["ok"] is True
        assert data["band"]["key"] == "gpp_n78"
        assert data["band"]["f_low_ghz"] == 3.3
        assert data["band"]["f_high_ghz"] == 3.8

    def test_bands_get_unknown_key(self, mcp_server):
        data = _call(mcp_server, "bands_get", {"key": "no_such_band"})
        assert data["ok"] is False
        assert "gpp_n78" in data["error"]  # 报错带可用键列表

    def test_bands_find_3g5(self, mcp_server):
        data = _call(mcp_server, "bands_find", {"freq_ghz": 3.5})
        assert data["ok"] is True
        assert {"gpp_n78", "cn_5g_3g3_3g6"} <= {b["key"] for b in data["bands"]}

    def test_bands_spec_bounds_n78(self, mcp_server):
        data = _call(mcp_server, "bands_spec_bounds", {"key": "gpp_n78"})
        assert data["ok"] is True
        assert data["spec_bounds"] == {"band": [3.3, 3.8]}


class TestBandsEnvTools:
    def test_env_list_and_get(self, mcp_server):
        listed = _call(mcp_server, "bands_env_list", {})
        assert listed["ok"] is True
        assert listed["count"] > 0
        got = _call(mcp_server, "bands_env_get",
                    {"key": "industrial_grade_40_85"})
        assert got["ok"] is True
        assert got["environment"]["key"] == "industrial_grade_40_85"

    def test_env_get_unknown_key(self, mcp_server):
        data = _call(mcp_server, "bands_env_get", {"key": "no_such_env"})
        assert data["ok"] is False

    def test_env_find_85c(self, mcp_server):
        data = _call(mcp_server, "bands_env_find", {"t_c": 85.0})
        assert data["ok"] is True
        assert "industrial_grade_40_85" in {e["key"] for e in data["environments"]}

    def test_env_delta_t_uq_axis_points(self, mcp_server):
        key = "industrial_grade_40_85"
        dt = _call(mcp_server, "bands_env_delta_t", {"key": key})
        assert dt["ok"] is True
        uq = _call(mcp_server, "bands_env_uq_axis",
                   {"key": key, "k_sigma": 3.0})
        assert uq["ok"] is True
        pts = _call(mcp_server, "bands_env_points", {"key": key, "n": 5})
        assert pts["ok"] is True
        assert pts["count"] == 5
        # 温区两端必采：-40 与 85（core/bands.py 标准常量）
        assert pts["temperatures_c"][0] == -40.0
        assert pts["temperatures_c"][-1] == 85.0
