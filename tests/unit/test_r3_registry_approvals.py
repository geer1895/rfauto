"""审批流接入钉：生产路径必须真接 RegistryDB.approvals。

背景（同类历史缺陷）：内核表+CRUD+单测全绿，但生产函数仍读旧路径
（audit.jsonl），表零生产消费——"单测绿而主路径不接"。本文件两层钉：

1. 源码级：r3_services.py 必须引用 RegistryDB（grep 级断言）；
2. 行为级：propose/approve/reject 后，直接开 RegistryDB 查 approvals 表
   能看到状态变更（生产函数写的是 DB，不是只写文件）。

口径：audit.jsonl 仍是产物事实源，DB 是物化读模型；首读回填幂等，历史
审计行重建后收件箱口径不变（迁移钉）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.infra.db import ENV_REGISTRY_DB, RegistryDB

_WILKINSON_RECIPE = {
    "model": "wilkinson_power_divider",
    "schema_version": 1,
    "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
    "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
    "objectives": [
        {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
    ],
    "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """cwd + env 双隔离（#144）：审批读写现在会建 runs/registry.sqlite。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_REGISTRY_DB, raising=False)
    yield


# ---------------------------------------------------------------------------
# 钉 1：源码级接入（grep 级）——防"单测绿而主路径不接"回退
# ---------------------------------------------------------------------------

class TestSourceWiringNail:
    def test_r3_services_references_registrydb(self):
        src = (Path(__file__).resolve().parents[2] / "src" / "rfauto" / "service"
               / "r3_services.py").read_text(encoding="utf-8")
        # 模块级导入（生产读写走 infra.db 门面）
        assert "from rfauto.infra.db import RegistryDB" in src
        # 读路径与批准路径确实消费 DB（而非仅 import 摆设）
        for needle in ("_sync_approvals_to_db", "_pending_from_db",
                       "_find_proposal_in_db", "_record_approval_event_in_db"):
            assert needle in src, f"接入函数缺失: {needle}"
        # list_pending_approvals / approve_proposal 函数体内有 DB 调用
        for fn in ("def list_pending_approvals", "def approve_proposal"):
            head = src.index(fn)
            body = src[head:head + 4000]
            assert "_sync_approvals_to_db(" in body, f"{fn} 未接 DB"

    def test_import_surface_exposes_registrydb(self):
        import rfauto.service.r3_services as m

        assert m.RegistryDB is RegistryDB


# ---------------------------------------------------------------------------
# 钉 2：行为级——生产函数写的是 DB（开新连接直接查表可见）
# ---------------------------------------------------------------------------

class TestProductionFunctionsWriteDb:
    def test_propose_change_inserts_pending_row(self):
        from rfauto.service.r3_services import _propose_solver_registration

        r = _propose_solver_registration("comsol_rf", "comsol",
                                         exe_path="C:/COMSOL/bin")
        assert r["ok"]
        db = RegistryDB()
        try:
            row = db.get_approval(r["change_id"])
            assert row is not None
            assert row["status"] == "pending"
            assert row["kind"] == "solver_registration"
            # payload = 完整审计事件 + audit_file 外键（文件路径作产物外键）
            assert row["payload"]["change_id"] == r["change_id"]
            assert row["payload"]["audit_file"].endswith("audit.jsonl")
            # 提案文件/审计产物原样保留
            assert (Path("runs") / "agent_proposals" / "audit.jsonl").exists()
        finally:
            db.close()

    def test_approve_change_flips_db_status_to_applied(self):
        from rfauto.service.r3_services import (
            _propose_solver_registration,
            approve_proposal,
        )

        r = _propose_solver_registration("comsol_rf", "comsol")
        assert approve_proposal(r["change_id"])["ok"]
        db = RegistryDB()
        try:
            assert db.get_approval(r["change_id"])["status"] == "applied"
        finally:
            db.close()
        # 收件箱与 DB 状态一致（同一读模型）
        assert list(approvals_pending_ids()) == []

    def test_reject_change_flips_db_status_to_rejected(self):
        from rfauto.service.r3_services import (
            _propose_resource_change,
            _reject_change,
        )

        r = _propose_resource_change("class", "fdtd", 5)
        assert _reject_change(r["change_id"], reason="席位")["ok"]
        db = RegistryDB()
        try:
            assert db.get_approval(r["change_id"])["status"] == "rejected"
        finally:
            db.close()

    def test_recipe_approve_flips_db_status_by_token_hash(self):
        """配方提案（api 层 propose，无 change_id）：DB 主键 = token_hash，
        首读收件箱回填建档，批准成功后同键状态翻 applied。"""
        import yaml

        from rfauto.service.agent_safety import token_hash
        from rfauto.service.api import agent_propose
        from rfauto.service.r3_services import approve_proposal, list_pending_approvals

        recipe = Path("recipe.yaml")
        recipe.write_text(yaml.safe_dump(_WILKINSON_RECIPE), encoding="utf-8")
        proposed = agent_propose(recipe, {"arm_len_mm": 21.0})
        assert proposed["ok"], proposed.get("errors")
        th = token_hash(proposed["token"])

        # 首读收件箱（生产读路径）→ 回填建档
        assert list_pending_approvals()["total"] == 1
        db = RegistryDB()
        try:
            row = db.get_approval(th)
            assert row is not None and row["status"] == "pending"
            assert row["kind"] == "recipe"  # 缺 kind 事件按 recipe 入库
        finally:
            db.close()

        result = approve_proposal(th, str(recipe))
        assert result["ok"], result.get("errors")
        db = RegistryDB()
        try:
            assert db.get_approval(th)["status"] == "applied"
        finally:
            db.close()


def approvals_pending_ids() -> list[str]:
    db = RegistryDB()
    try:
        return [row["id"] for row in db.list_approvals(status="pending")]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 迁移钉：audit.jsonl 既有记录首读回填（幂等），历史口径不变
# ---------------------------------------------------------------------------

class TestBackfillMigration:
    def _audit(self, entries: list[dict]) -> None:
        audit_dir = Path("runs") / "agent_proposals"
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / "audit.jsonl").write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

    def test_first_read_backfills_history_into_approvals(self):
        from rfauto.service.r3_services import list_pending_approvals

        self._audit([
            {"event": "propose", "ok": True, "token_hash": "abc123",
             "recipe": "r.yaml", "params": {"a": 1}},
            {"event": "apply", "ok": True, "token_hash": "abc123",
             "run_id": "run_1"},
            {"event": "propose", "ok": True, "token_hash": "bbb999",
             "recipe": "r.yaml", "params": {"b": 2}},
            # ok=False 的历史事件不进读模型（与文件口径一致）
            {"event": "approve", "ok": False, "token_hash": "ccc777"},
        ])
        out = list_pending_approvals()
        assert out["total"] == 1
        assert out["pending"][0]["token_hash"] == "bbb999"
        # 返回形状 = 审计事件原样（无 audit_file 内部键）
        assert "audit_file" not in out["pending"][0]

        db = RegistryDB()
        try:
            assert db.get_approval("abc123")["status"] == "applied"
            assert db.get_approval("bbb999")["status"] == "pending"
            assert db.get_approval("ccc777") is None
            # audit_file 外键入库
            assert db.get_approval("bbb999")["payload"]["audit_file"].endswith(
                "audit.jsonl")
        finally:
            db.close()

    def test_backfill_rebuilds_after_db_loss(self):
        """DB 文件丢失（跨工作区/清理后）：首读从 audit.jsonl 完整重建。"""
        from rfauto.service.r3_services import (
            _propose_solver_registration,
            list_pending_approvals,
        )

        r = _propose_solver_registration("palace_x", "palace")
        assert list_pending_approvals()["total"] == 1
        db = RegistryDB()
        db_file = db.path
        db.close()
        for suffix in ("", "-wal", "-shm"):
            f = db_file.parent / (db_file.name + suffix)
            if f.exists():
                f.unlink()

        assert list_pending_approvals()["total"] == 1
        db = RegistryDB()
        try:
            row = db.get_approval(r["change_id"])
            assert row is not None and row["status"] == "pending"
        finally:
            db.close()

    def test_backfill_idempotent_no_status_downgrade(self):
        from rfauto.service.r3_services import (
            _propose_solver_registration,
            approve_proposal,
            list_pending_approvals,
        )

        r = _propose_solver_registration("cst_y", "cst_studio")
        assert approve_proposal(r["change_id"])["ok"]
        assert list_pending_approvals()["total"] == 0
        # 重复读（回填重放）：终态不被历史 pending 事件降级
        assert list_pending_approvals()["total"] == 0
        db = RegistryDB()
        try:
            assert db.get_approval(r["change_id"])["status"] == "applied"
            assert db.table_count("approvals") == 1  # 不产生重复行
        finally:
            db.close()

    def test_pending_payload_follows_rewritten_audit_file(self):
        """audit.jsonl 被外部改写（篡改检测用例的手法）：pending 行载荷随
        文件刷新——文件是事实源，DB 是视图，语义与纯文件口径一致。"""
        from rfauto.service.r3_services import list_pending_approvals

        self._audit([
            {"event": "propose", "ok": True, "token_hash": "ffff0000",
             "recipe": "z.yaml", "params": {"arm_len_mm": 21.0}},
        ])
        assert list_pending_approvals()["total"] == 1

        audit = Path("runs") / "agent_proposals" / "audit.jsonl"
        entry = json.loads(audit.read_text(encoding="utf-8").strip())
        entry["params"] = {"bogus_param": 99.0}
        audit.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        out = list_pending_approvals()
        assert out["pending"][0]["params"] == {"bogus_param": 99.0}
        db = RegistryDB()
        try:
            payload = db.get_approval("ffff0000")["payload"]
            assert payload["params"] == {"bogus_param": 99.0}
        finally:
            db.close()
