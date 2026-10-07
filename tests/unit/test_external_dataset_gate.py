"""KD-8 外部数据集接入面+许可门测试（round16，J 流）。

锚树：
- **NC 禁公开分发铁律**：RadioML 三数据集 publish 恒拒绝（无豁免）；
  research_eval 放行但附禁分发注记；
- 未注册数据集 UNKNOWN 拒入（不猜许可）；use 词表外拒绝；
- **数据本体不入仓**：plan_ingestion 仓内路径默认拒绝；豁免只认
  runs/external_datasets；零下载零网络（计划面，无 HTTP 面）；
- 接入器：schema_map 目标列白名单校验（DATASET_SCHEMA）/必填列覆盖/
  未映射列进 extra（数据零丢失）/确定性；
- 许可注册表锚：NC 锚存在且类别正确（防误改注册表放行 NC）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service.dataset_service import DATASET_SCHEMA
from rfauto.service.external_dataset_service import (
    EXTERNAL_DATASET_SCHEMA,
    LICENSE_PERMISSIVE,
    LICENSE_REGISTRY,
    LICENSE_RESEARCH_ONLY,
    USE_PUBLISH,
    USE_RESEARCH_EVAL,
    adapt_rows,
    check_license_gate,
    plan_ingestion,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

_NC_IDS = ("radioml2016.10a", "radioml2016.10b", "radioml2018.01a")


class TestLicenseGate:
    def test_nc_registry_entries_are_research_only(self):
        # NC 锚存在且类别正确（防注册表被误改放行）
        for did in _NC_IDS:
            entry = LICENSE_REGISTRY[did]
            assert entry["license"] == LICENSE_RESEARCH_ONLY, did
            assert "禁" in entry["notes"] or "NC" in entry["notes"], did

    def test_nc_publish_is_hard_denied(self):
        for did in _NC_IDS:
            r = check_license_gate(did, use=USE_PUBLISH)
            assert r["allowed"] is False, did
            assert r["gate"] == LICENSE_RESEARCH_ONLY
            assert any("禁公开分发" in s for s in r["reasons"])

    def test_nc_research_eval_allowed_with_note(self):
        r = check_license_gate("radioml2016.10a", use=USE_RESEARCH_EVAL)
        assert r["allowed"] is True
        assert any("禁公开分发" in s for s in r["reasons"])

    def test_permissive_publish_allowed_with_attribution(self):
        r = check_license_gate("ieee_dataport_microstrip_190k", use=USE_PUBLISH)
        assert r["allowed"] is True
        assert r["gate"] == LICENSE_PERMISSIVE
        assert any("CC-BY" in s or "署名" in s for s in r["reasons"])

    def test_unknown_dataset_is_honest_unknown_not_guess(self):
        r = check_license_gate("some-unregistered-set", use=USE_RESEARCH_EVAL)
        assert r["allowed"] is False and r["gate"] == "UNKNOWN"

    def test_unknown_use_rejected(self):
        r = check_license_gate("zenodo_14533762", use="training")  # 词表外
        assert r["allowed"] is False

    def test_schema_pinned(self):
        assert check_license_gate("zenodo_14533762")[
            "schema"] == EXTERNAL_DATASET_SCHEMA


class TestRepoGuard:
    def test_in_repo_target_denied_by_default(self, tmp_path, monkeypatch):
        target = _REPO_ROOT / "data_cache" / "radioml"
        r = plan_ingestion("radioml2016.10a", target)
        assert r["ok"] is False
        assert any("不入仓" in s for s in r["reasons"])

    def test_repo_exemption_only_runs_external_datasets(self):
        r_bad = plan_ingestion("ieee_dataport_microstrip_190k",
                               _REPO_ROOT / "data_cache" / "x",
                               allow_repo_gitignored=True)
        assert r_bad["ok"] is False
        r_good = plan_ingestion("ieee_dataport_microstrip_190k",
                                _REPO_ROOT / "runs" / "external_datasets" / "ieee",
                                allow_repo_gitignored=True)
        assert r_good["ok"] is True
        assert "external_datasets" in r_good["target_dir"]

    def test_outside_repo_target_allowed(self, tmp_path):
        r = plan_ingestion("ieee_dataport_microstrip_190k", tmp_path / "ext")
        assert r["ok"] is True
        assert r["license_gate"]["allowed"] is True

    def test_plan_is_zero_download_no_http_face(self, tmp_path):
        # 接入器零网络：计划即时返回（无抓取步骤），steps 全为人工动作
        r = plan_ingestion("zenodo_14533762", tmp_path / "ext")
        assert r["ok"] is True
        assert all("下载" in s or "补全" in s or "adapt_rows" in s
                   for s in r["steps"])

    def test_plan_carries_schema_columns(self, tmp_path):
        r = plan_ingestion("zenodo_14533762", tmp_path / "ext")
        assert r["dataset_schema_columns"] == [c for c, _t in DATASET_SCHEMA]

    def test_license_denied_blocks_plan_even_outside_repo(self, tmp_path):
        # 未注册数据集：许可 UNKNOWN → 计划拒绝（守卫双门）
        r = plan_ingestion("unregistered-set", tmp_path / "ext")
        assert r["ok"] is False


class TestAdapter:
    def test_valid_mapping_adapts_rows(self):
        smap = {"id": "run_id", "family": "model", "engine": "adapter",
                "objective": "cost"}
        rows = [{"id": "a1", "family": "mline", "engine": "hfss",
                 "objective": 0.1, "unused_col": 42}]
        r = adapt_rows(rows, smap, dataset_id="zenodo_14533762")
        assert r["ok"] and r["n_rows"] == 1
        row = r["rows"][0]
        assert row["run_id"] == "a1" and row["cost"] == 0.1
        assert row["extra"] == {"unused_col": 42}  # 数据零丢失

    def test_bad_target_column_rejected(self):
        r = adapt_rows([{"a": 1}], {"a": "not_in_schema"})
        assert not r["ok"] and "DATASET_SCHEMA" in r["errors"][0]

    def test_missing_required_mapping_rejected(self):
        r = adapt_rows([{"a": 1}], {"a": "cost"})
        assert not r["ok"] and "run_id" in r["errors"][0]

    def test_deterministic(self):
        smap = {"id": "run_id", "family": "model", "engine": "adapter"}
        rows = [{"id": "x", "family": "m", "engine": "e", "z": 1}]
        a = adapt_rows(rows, smap)
        b = adapt_rows(rows, smap)
        assert a == b
