"""A4 战役级 skill 自动沉淀接线测试（ge8e W2 批，campaign_manager）。

出处链：F8 已在 api.run_once 单 run 收官点接线 auto_deposit_hook（ge8e
J1-1）；本批把同款钩子接进战役收官分支（campaign_manager.apply_event
判定 verdict=COMPLETE 的同位分支——批次全部阶段终态 done 的落档点）。
钩子通道 monkeypatch 钉死（零网络/零真实 runs/ 依赖，#139 同族纪律）；
best-effort 语义（#105）与幂等（钩子内 _DEPOSITED_RUN_IDS，J1-1）的
行为钉见 test_skill_autopilot.py。
"""

from __future__ import annotations

from typing import Any

from rfauto.service import campaign_manager
from rfauto.service.campaign_manager import apply_event


def _two_stage_plan() -> dict[str, Any]:
    """最小战役计划（a→b 两阶段，恰好覆盖 COMPLETE 判定所需字段）。"""
    return {"stages": [
        {"stage": "a", "depends_on": [], "status": "pending"},
        {"stage": "b", "depends_on": ["a"], "status": "pending"},
    ]}


class TestCampaignCompleteDepositHook:
    def test_campaign_complete_calls_auto_deposit_hook(self, monkeypatch):
        """回归钉①：战役收官（全阶段 done）→ 钩子被调（campaign 级
        run_id + 沉淀目录原样透传）。"""
        calls: list[dict[str, Any]] = []

        def fake_hook(**kwargs):
            calls.append(kwargs)
            return {"ok": True, "deposited": True}

        monkeypatch.setattr(
            "rfauto.service.skill_autopilot.auto_deposit_hook", fake_hook)
        plan = _two_stage_plan()
        r1 = apply_event(plan, "a", "stage_done", run_id="camp_a4",
                         skill_output_dir="runs/camp_a4/skills")
        assert r1["ok"] and r1["verdict"] == "RUNNING"
        assert calls == []  # 未收官不触发
        r2 = apply_event(plan, "b", "stage_done", run_id="camp_a4",
                         skill_output_dir="runs/camp_a4/skills")
        assert r2["ok"] and r2["verdict"] == "COMPLETE"
        assert len(calls) == 1
        assert calls[0]["run_id"] == "camp_a4"
        assert str(calls[0]["output_dir"]).replace("\\", "/") == \
            "runs/camp_a4/skills"

    def test_hook_exception_does_not_affect_campaign_result(self, monkeypatch):
        """回归钉②：钩子抛错 → 战役结果不受影响（#105 best-effort）。"""

        def boom(**kwargs):
            raise RuntimeError("deposit exploded")

        monkeypatch.setattr(
            "rfauto.service.skill_autopilot.auto_deposit_hook", boom)
        plan = _two_stage_plan()
        apply_event(plan, "a", "stage_done")
        r = apply_event(plan, "b", "stage_done", run_id="camp_boom",
                        skill_output_dir="x")
        assert r["ok"] is True
        assert r["verdict"] == "COMPLETE"
        assert r["plan"]["n_done"] == 2

    def test_no_run_id_hook_not_called(self, monkeypatch):
        """run_id 缺省 None（既有调用方）→ 钩子零触发（零感知兼容钉）。"""
        called = []

        def fake_hook(**kwargs):
            called.append(kwargs)
            return {"ok": True, "deposited": False}

        monkeypatch.setattr(
            "rfauto.service.skill_autopilot.auto_deposit_hook", fake_hook)
        plan = _two_stage_plan()
        apply_event(plan, "a", "stage_done")
        r = apply_event(plan, "b", "stage_done")
        assert r["verdict"] == "COMPLETE"
        assert called == []

    def test_dead_campaign_never_calls_hook(self, monkeypatch):
        """失败/放弃终态（ABORTED/PARTIAL）不在沉淀白名单路径上。"""
        called = []

        def fake_hook(**kwargs):
            called.append(kwargs)
            return {"ok": True, "deposited": False}

        monkeypatch.setattr(
            "rfauto.service.skill_autopilot.auto_deposit_hook", fake_hook)
        plan = _two_stage_plan()
        r = apply_event(plan, "a", "stage_failed", run_id="camp_dead",
                        skill_output_dir="x")
        assert r["verdict"] in ("ABORTED", "PARTIAL")
        apply_event(plan, "b", "stage_done", run_id="camp_dead",
                    skill_output_dir="x")
        assert called == []

    def test_helper_module_level_entrypoint(self, monkeypatch):
        """_deposit_skill_on_complete 是钩子的唯一注入面（出处链锚）。"""
        assert hasattr(campaign_manager, "_deposit_skill_on_complete")
        called = []

        def fake_hook(**kwargs):
            called.append(kwargs)
            return {"ok": True, "deposited": False}

        monkeypatch.setattr(
            "rfauto.service.skill_autopilot.auto_deposit_hook", fake_hook)
        campaign_manager._deposit_skill_on_complete("rid", None)
        assert called and called[0]["run_id"] == "rid"
        assert str(called[0]["output_dir"]) == "skills"  # 缺省仓根 skills 惯例
