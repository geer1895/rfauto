"""R2 模型档案（收窄版）服务测试：registry/lake 双源卡 + QW-16 联动。

全部确定性、零网络；lake 面用 tmp runs 目录（真实 runs/ 只读不写）；
锚联动走真实注册表 knowledge/anchors.yaml（cps.gamma_er 的 * 通配覆盖
任意模型族，verdict 如实 no_data——快照机制数据积累期）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.service.model_card_service import (
    build_model_card,
    list_model_cards,
    registry_model_ids,
)


def _make_run(runs_dir: Path, campaign: str, run_id: str, model: str | None,
              *, timestamp: str = "2026-09-26T10:00:00",
              status: str = "done", with_criteria: bool = False) -> Path:
    run_dir = runs_dir / campaign / run_id
    run_dir.mkdir(parents=True)
    meta: dict[str, object] = {"adapter": "fake", "status": status,
                               "timestamp": timestamp}
    if model is not None:
        meta["model"] = model
    (run_dir / "meta.json").write_text(
        json.dumps(meta), encoding="utf-8")
    if with_criteria:
        (run_dir / "criteria.md").write_text("# gates\n", encoding="utf-8")
    return run_dir


class TestRegistryCards:
    def test_surrogate_card_poly_ridge(self):
        card = build_model_card("poly_ridge", "registry")
        assert card["ok"] is True
        assert card["kind"] == "surrogate"
        assert card["source"] == "registry"
        assert card["created"] is None
        assert isinstance(card["params_schema"], list)
        assert any(row["name"] == "config" for row in card["params_schema"])
        assert card["criteria_refs"] == []
        assert card["drift_status"]["verdict"] == "no_data"
        assert card["drift_status"]["available"] is False

    def test_closed_form_card_microstrip(self):
        card = build_model_card("microstrip_analysis", "registry")
        assert card["ok"] is True
        assert card["kind"] == "closed_form"
        names = {row["name"] for row in card["params_schema"]}
        assert "width_mm" in names  # 微带分析口径：线宽 → (Z0, εeff)

    def test_unknown_registry_model_lists_available(self):
        out = build_model_card("no_such_model", "registry")
        assert out["ok"] is False
        assert "poly_ridge" in out["available"]["surrogate"]
        assert "microstrip_analysis" in out["available"]["closed_form"]

    def test_registry_model_ids_shape(self):
        ids = registry_model_ids()
        assert set(ids) == {"surrogate", "closed_form"}
        assert len(ids["surrogate"]) >= 10
        assert len(ids["closed_form"]) >= 50

    def test_unknown_source_rejected(self):
        assert build_model_card("poly_ridge", "wat")["ok"] is False


class TestLakeCards:
    def test_lake_card_run_history(self, tmp_path: Path):
        _make_run(tmp_path, "smoke_wilkinson", "20260926_000000_aaaa",
                  "wilkinson", timestamp="2026-09-26T10:00:00",
                  with_criteria=True)
        _make_run(tmp_path, "smoke_wilkinson", "20260926_010000_bbbb",
                  "wilkinson", timestamp="2026-09-26T11:00:00")
        card = build_model_card("wilkinson", "lake", runs_dir=tmp_path)
        assert card["ok"] is True
        assert card["kind"] == "run_history"
        assert card["created"] == "2026-09-26T10:00:00"  # 最早 ts
        assert card["n_matched_runs"] == 2
        assert card["criteria_refs"] == [
            "smoke_wilkinson/20260926_000000_aaaa/criteria.md"]
        # last_runs 按 created_ts 降序
        assert [r["run_id"] for r in card["last_runs"]] == [
            "20260926_010000_bbbb", "20260926_000000_aaaa"]
        # QW-16 联动：cps.gamma_er 的 * 通配覆盖 wilkinson → available。
        # 行序=anchor_id 字典序（core/anchors.AnchorSet.records 排序口径），
        # 不钉位次——coupled_microstrip.kj_even_domain.lit-v1（2026-09-30
        # 首登记，同为 * 通配）字典序在前，按 id 取行（2026-10-01 月终门 C2）
        drift = card["drift_status"]
        assert drift["available"] is True
        cps_row = next(a for a in drift["anchors"]
                       if a["anchor_id"] == "cps.gamma_er.fdref-v1")
        assert cps_row["verdict"] == "no_data"  # 积累期如实

    def test_lake_card_campaign_name_fallback(self, tmp_path: Path):
        # meta 缺 model 字段 → 按战役目录名回退匹配
        _make_run(tmp_path, "hairpin_calib", "run_x", None)
        card = build_model_card("hairpin_calib", "lake", runs_dir=tmp_path)
        assert card["ok"] is True
        assert card["n_matched_runs"] == 1

    def test_lake_unknown_family_lists_available(self, tmp_path: Path):
        _make_run(tmp_path, "camp", "r1", "wilkinson")
        out = build_model_card("ghost", "lake", runs_dir=tmp_path)
        assert out["ok"] is False
        assert out["available"] == ["wilkinson"]

    def test_lake_missing_runs_dir_honest(self, tmp_path: Path):
        out = build_model_card("wilkinson", "lake", runs_dir=tmp_path / "nope")
        assert out["ok"] is False
        assert out["available"] == []


class TestListCards:
    def test_list_contains_registry_and_lake(self, tmp_path: Path):
        _make_run(tmp_path, "camp", "r1", "wilkinson")
        listing = list_model_cards(runs_dir=tmp_path)
        assert listing["ok"] is True
        assert listing["counts"]["surrogate"] >= 10
        assert listing["counts"]["closed_form"] >= 50
        assert listing["counts"]["run_history"] == 1
        slim = {(c["model_id"], c["source"]) for c in listing["cards"]}
        assert ("poly_ridge", "registry") in slim
        assert ("microstrip_analysis", "registry") in slim
        assert ("wilkinson", "lake") in slim

    def test_list_missing_runs_dir_zero_lake(self, tmp_path: Path):
        listing = list_model_cards(runs_dir=tmp_path / "nope")
        assert listing["ok"] is True
        assert listing["counts"]["run_history"] == 0

    def test_corrupt_meta_skipped_not_fatal(self, tmp_path: Path):
        bad = tmp_path / "camp" / "r_bad"
        bad.mkdir(parents=True)
        (bad / "meta.json").write_text("{not json", encoding="utf-8")
        _make_run(tmp_path, "camp", "r_good", "wilkinson")
        listing = list_model_cards(runs_dir=tmp_path)
        assert listing["ok"] is True
        assert listing["counts"]["run_history"] == 1


class TestQw16LinkageWithSnapshots:
    def test_snapshot_history_flows_into_lake_card(self, tmp_path: Path):
        # 快照库两快照阶梯（均值 0→10）→ lake 卡 drift verdict=warning
        # （两快照仅指纹差分线可用，单线上限 warning）
        from rfauto.service.anchors_service import record_anchor_drift_snapshot
        _make_run(tmp_path, "camp", "r1", "wilkinson")
        store = tmp_path / "snapshots.json"
        assert record_anchor_drift_snapshot(
            "cps.gamma_er.fdref-v1", [0.0, 0.0, 0.0, 0.0], at="t0",
            store_path=store)["ok"] is True
        assert record_anchor_drift_snapshot(
            "cps.gamma_er.fdref-v1", [10.0, 10.0, 10.0, 10.0], at="t1",
            store_path=store)["ok"] is True
        card = build_model_card("wilkinson", "lake", runs_dir=tmp_path,
                                store_path=store)
        drift = card["drift_status"]
        assert drift["available"] is True
        # 卡级 verdict=最劣聚合仍为 warning（insufficient rank 2 < warning 3，
        # 其余 * 通配锚无快照 no_data/insufficient 不顶劣化序）
        assert drift["verdict"] == "warning"
        # 行序=anchor_id 字典序不钉位次（coupled_microstrip * 通配 2026-09-30
        # 起字典序在前）——按 id 取 cps.gamma_er 行断言快照阶梯传导
        cps_row = next(a for a in drift["anchors"]
                       if a["anchor_id"] == "cps.gamma_er.fdref-v1")
        assert cps_row["verdict"] == "warning"


@pytest.mark.parametrize("model_id", ["poly_ridge", "gbdt", "pod_rom"])
def test_parametrized_surrogate_cards_buildable(model_id: str):
    card = build_model_card(model_id, "registry")
    assert card["ok"] is True
    assert card["kind"] == "surrogate"
