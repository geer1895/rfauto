"""PR-9 调度队列页单测：/api/campaign_queue 端点 + 队列页装配面。"""

from __future__ import annotations

import json

import pytest

_PLAN_MIN = {
    "ok": True,
    "recipe": "recipes/demo.yaml",
    "model": "wilkinson",
    "stages": [
        {"stage": "calibrate", "kind": "calibrate", "adapter": "openems",
         "depends_on": [], "status": "done", "license_gated": False},
        {"stage": "final_verify", "kind": "tune", "adapter": "hfss",
         "depends_on": ["tolerance"], "status": "pending",
         "license_gated": True},
    ],
    "scheduling": {
        "ok": True, "n_jobs": 2, "predictor_used": False,
        "budget_gate_used": False,
        "decision_log": [
            {"job": "calibrate", "event": "dispatch", "seat": "openems"},
            {"job": "final_verify", "event": "queued", "seat": "hfss"},
        ],
    },
}


@pytest.fixture()
def runs_root(tmp_path, monkeypatch):
    """tmp runs/<id>/campaign.plan.json（chdir 隔离，#144）。"""
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "runs" / "camp_a"
    d.mkdir(parents=True)
    (d / "campaign.plan.json").write_text(
        json.dumps(_PLAN_MIN, ensure_ascii=False), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(runs_root):
    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app

    return TestClient(create_ui_app())


class TestQueueEndpoint:
    def test_lists_campaign_with_decision_log(self, client):
        r = client.get("/api/campaign_queue").json()
        assert r["ok"] and r["n_campaigns"] == 1
        c = r["campaigns"][0]
        assert c["model"] == "wilkinson"
        assert c["n_stages"] == 2
        assert c["scheduling"]["ok"] is True
        assert len(c["scheduling"]["decision_log"]) == 2
        stages = {s["stage"]: s for s in c["stages"]}
        assert stages["calibrate"]["status"] == "done"
        assert stages["final_verify"]["license_gated"] is True

    def test_without_machine_param_no_remote_key(self, client):
        r = client.get("/api/campaign_queue").json()
        assert all("remote" not in c for c in r["campaigns"])

    def test_empty_runs_root_is_ok_empty(self, client, runs_root):
        (runs_root / "runs" / "emptyroot").mkdir()
        r = client.get("/api/campaign_queue?root=runs/emptyroot").json()
        assert r["ok"] and r["n_campaigns"] == 0 and r["campaigns"] == []

    def test_corrupt_plan_file_skipped(self, client, runs_root):
        d = runs_root / "runs" / "camp_bad"
        d.mkdir()
        (d / "campaign.plan.json").write_text("{broken", encoding="utf-8")
        r = client.get("/api/campaign_queue").json()
        assert r["ok"] and r["n_campaigns"] == 1  # 坏文件跳过不拖垮清单（#105）


class TestRemoteBlock:
    def test_machine_param_attaches_remote_block(self, client, monkeypatch):
        def fake_config(machine):
            return {"ok": True, "remote": {"remote_machine": machine,
                                           "machine": "10.0.0.8", "port": 18000}}

        monkeypatch.setattr(
            "rfauto.service.remote_service.hfss_remote_session_config",
            fake_config)
        r = client.get("/api/campaign_queue?machine=sim_host").json()
        c = r["campaigns"][0]
        assert c["remote"]["ok"] is True
        assert c["remote"]["remote_machine"]["remote_machine"] == "sim_host"
        # 候选=license_gated 阶段（final_verify）
        assert c["remote"]["stage_candidates"] == ["final_verify"]
        # mTLS 条件项如实登记（不硬上）：状态字符串恒携带
        assert "mTLS" in c["remote"]["mtls"] and "insecure" in c["remote"]["mtls"]

    def test_remote_config_error_degrades_not_raises(self, client, monkeypatch):
        def boom(machine):
            raise RuntimeError("未登记机器")

        monkeypatch.setattr(
            "rfauto.service.remote_service.hfss_remote_session_config", boom)
        r = client.get("/api/campaign_queue?machine=ghost").json()
        assert r["ok"] is True  # 清单不阻塞（#105）
        c = r["campaigns"][0]
        assert c["remote"]["ok"] is False and "未登记机器" in c["remote"]["errors"][0]
        assert "mTLS" in c["remote"]["mtls"]


class TestQueuePage:
    def test_index_serves_queue_view(self, client):
        html = client.get("/").text
        assert 'id="view-queue"' in html and 'data-v="queue"' in html

    def test_pages_js_registers_queue(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2]
               / "src" / "rfauto" / "ui" / "static" / "pages.js"
               ).read_text(encoding="utf-8")
        assert "queue: pageQueue" in src
        assert "async function pageQueue()" in src
