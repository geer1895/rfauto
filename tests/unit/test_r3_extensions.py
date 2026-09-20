"""Direction 6 R3 extension tests (6g-6j).

6g: Solver visualization protocol
6h: Solver management (registry + config)
6i: Approval inbox
6j: LLM conversation (AgentChat)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    # 审批读写接 RegistryDB 后，清掉注册表 DB 路径 env，
    # 防止本机 set 的 RFAUTO_REGISTRY_DB 把测试写入写到 tmp 之外（#144）
    monkeypatch.delenv("RFAUTO_REGISTRY_DB", raising=False)
    yield


class TestSolverVisualization:
    def test_list_solvers(self):
        from rfauto.service.r3_services import list_registered_solvers
        result = list_registered_solvers()
        assert result["ok"]
        assert isinstance(result["solvers"], list)

    def test_list_visualizations(self):
        from rfauto.service.r3_services import list_solver_visualizations
        result = list_solver_visualizations()
        assert result["ok"]
        assert isinstance(result["solvers"], list)

    def test_visualizations_filter_by_solver(self):
        from rfauto.service.r3_services import list_solver_visualizations
        result = list_solver_visualizations("fake")
        assert result["ok"]


class TestSolverManagement:
    def test_add_and_remove_solver(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "configs").mkdir()
        from rfauto.service.r3_services import add_solver_to_config, remove_solver_from_config

        # Add
        result = add_solver_to_config("test_solver", "palace", exe_path="/usr/bin/palace")
        assert result["ok"]
        assert result["loadable"], result["errors"]

        # 写入 schema 必须与 load_solvers_config 读取约定一致
        # （曾写顶层 {name: {type}}，运行时读不到）
        from rfauto.adapters.em_solver_base import load_solvers_config
        loaded = load_solvers_config(tmp_path / "configs" / "solvers.yaml")
        assert "test_solver" in loaded
        assert str(loaded["test_solver"].solver_type.value) == "palace"
        assert loaded["test_solver"].exe_path == "/usr/bin/palace"

        # Remove
        result = remove_solver_from_config("test_solver")
        assert result["ok"]
        assert "test_solver" not in load_solvers_config(tmp_path / "configs" / "solvers.yaml")

    def test_add_custom_eda_type_loadable(self, tmp_path, monkeypatch):
        # 6h 目标：人工接入 CST/COMSOL 等任意 EDA——自定义类型写入后
        # load_solvers_config 必须可读（值保留原始字符串，注册 adapter 前不可 create）
        monkeypatch.chdir(tmp_path)
        (tmp_path / "configs").mkdir()
        from rfauto.adapters.em_solver_base import load_solvers_config
        from rfauto.service.r3_services import add_solver_to_config
        result = add_solver_to_config("my_cst", "cst_studio", exe_path="C:/CST/cst.exe")
        assert result["ok"] and result["loadable"]
        loaded = load_solvers_config(tmp_path / "configs" / "solvers.yaml")
        assert loaded["my_cst"].solver_type == "cst_studio"

    def test_add_duplicate_solver_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "configs").mkdir()
        from rfauto.service.r3_services import add_solver_to_config
        add_solver_to_config("dup", "fake")
        result = add_solver_to_config("dup", "fake")
        assert not result["ok"]

    def test_remove_nonexistent_solver_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "configs").mkdir()
        (tmp_path / "configs" / "solvers.yaml").write_text("{}", encoding="utf-8")
        from rfauto.service.r3_services import remove_solver_from_config
        result = remove_solver_from_config("ghost")
        assert not result["ok"]


class TestApprovalInbox:
    def test_empty_inbox(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.r3_services import list_pending_approvals
        result = list_pending_approvals()
        assert result["ok"]
        assert result["pending"] == []

    def test_inbox_with_proposals(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.r3_services import list_pending_approvals
        # Create mock audit log with propose but no apply
        audit_dir = Path("runs") / "agent_proposals"
        audit_dir.mkdir(parents=True)
        entries = [
            {"event": "propose", "ok": True, "token_hash": "abc123def", "recipe": "test.yaml",
             "params": {"arm_len_mm": 20.5}, "timestamp": "2026-09-02T00:00:00"},
        ]
        (audit_dir / "audit.jsonl").write_text(
            "\n".join(json.dumps(e) for e in entries), encoding="utf-8"
        )
        result = list_pending_approvals()
        assert result["ok"]
        assert len(result["pending"]) == 1

    def test_inbox_filters_applied(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.r3_services import list_pending_approvals
        audit_dir = Path("runs") / "agent_proposals"
        audit_dir.mkdir(parents=True)
        entries = [
            {"event": "propose", "ok": True, "token_hash": "abc123", "recipe": "r.yaml", "params": {}},
            {"event": "apply", "ok": True, "token_hash": "abc123", "run_id": "run_001"},
        ]
        (audit_dir / "audit.jsonl").write_text(
            "\n".join(json.dumps(e) for e in entries), encoding="utf-8"
        )
        result = list_pending_approvals()
        assert result["ok"]
        assert len(result["pending"]) == 0  # already applied


class TestApprovalFullChain:
    """6i 全链验收（R3 口径）：propose → inbox → approve → apply → audit。"""

    def _recipe(self, tmp_path: Path) -> Path:
        import yaml
        recipe = {
            "model": "wilkinson_power_divider",
            "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
            "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
        }
        path = tmp_path / "recipe.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        return path

    def test_approve_executes_proposal_end_to_end(self, tmp_path):

        from rfauto.service.api import agent_propose
        from rfauto.service.r3_services import (
            approve_proposal,
            list_pending_approvals,
        )

        recipe = self._recipe(tmp_path)
        params = {"arm_len_mm": 21.0}

        # 1) propose（审计只存 token 哈希）
        proposed = agent_propose(recipe, params)
        assert proposed["ok"]
        from rfauto.service.agent_safety import token_hash
        token_hash = token_hash(proposed["token"])

        # 2) 收件箱可见
        pending = list_pending_approvals()
        assert pending["ok"] and pending["total"] == 1
        assert pending["pending"][0]["token_hash"] == token_hash

        # 3) 批准 → 真实 apply（fake 仿真跑通，产 run_id）
        result = approve_proposal(token_hash, str(recipe))
        assert result["ok"], result.get("errors")
        assert result.get("run_id")

        # 4) apply 后收件箱清空
        assert list_pending_approvals()["total"] == 0

        # 5) audit 全链可查：propose + approve + apply
        events = [json.loads(line) for line in
                  (Path("runs") / "agent_proposals" / "audit.jsonl")
                  .read_text(encoding="utf-8").strip().split("\n")]
        kinds = [e["event"] for e in events]
        assert "approve" in kinds
        assert kinds.count("apply") >= 1

    def test_approve_with_unknown_token_fails(self, tmp_path):
        from rfauto.service.r3_services import approve_proposal
        recipe = self._recipe(tmp_path)
        from rfauto.service.api import agent_propose
        assert agent_propose(recipe, {"arm_len_mm": 21.0})["ok"]
        result = approve_proposal("ffffffff00000000", str(recipe))
        assert not result["ok"]

    def test_approve_after_recipe_drift_fails(self, tmp_path):
        # 配方在 propose 后被改动，使存档参数越界（L2 拒绝）→ 批准链拒绝。
        # 注：token 是 (L1,L2,params) 的哈希而非配方快照——不改变 Gate 判定的小改动
        # 不会被哈希抓到，但 apply 始终用当前配方重新过 L1/L2，执行仍受保护。
        import yaml

        from rfauto.service.api import agent_propose
        from rfauto.service.r3_services import approve_proposal

        recipe = self._recipe(tmp_path)
        proposed = agent_propose(recipe, {"arm_len_mm": 21.0})
        assert proposed["ok"]

        data = yaml.safe_load(recipe.read_text(encoding="utf-8"))
        data["optimization"]["params"]["arm_len_mm"] = {"low": 18.0, "high": 20.0}
        recipe.write_text(yaml.safe_dump(data), encoding="utf-8")

        result = approve_proposal(proposed["token"][:16], str(recipe))
        assert not result["ok"]

    def test_approve_rejects_param_mismatch_drift(self, tmp_path):
        # 若审计参数与配方白名单不符（如 propose 后参数被外部篡改进审计），
        # 重 propose 必须 L1/L2 拒绝，approve 落 re_propose 审计事件

        from rfauto.service.api import agent_propose
        from rfauto.service.r3_services import approve_proposal

        recipe = self._recipe(tmp_path)
        proposed = agent_propose(recipe, {"arm_len_mm": 21.0})
        assert proposed["ok"]

        audit = Path("runs") / "agent_proposals" / "audit.jsonl"
        entries = [json.loads(line) for line in audit.read_text(encoding="utf-8").strip().split("\n")]
        for e in entries:
            if e.get("event") == "propose":
                e["params"] = {"bogus_param": 99.0}  # 篡改审计参数
        audit.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        result = approve_proposal(proposed["token"][:16], str(recipe))
        assert not result["ok"]


class TestAgentChat:
    @pytest.fixture(autouse=True)
    def _no_llm(self, monkeypatch):
        # 单测对象是关键词路由；不隔离的话本机配了 API key（chat_settings.yaml）
        # 会真打外部 LLM（实测 22s/次且断言随模型回复漂移）
        from rfauto.service import r3_services
        monkeypatch.setattr(r3_services, "get_chat_settings",
                            lambda: {"ok": True, "configured": False})

    def test_chat_help(self):
        from rfauto.service.r3_services import AgentChat
        chat = AgentChat()
        result = chat.chat("help")
        assert result["action"] == "help"
        assert "solvers" in result["text"].lower()

    def test_chat_solvers(self):
        from rfauto.service.r3_services import AgentChat
        chat = AgentChat()
        result = chat.chat("solvers")
        assert result["action"] == "list_solvers"

    def test_chat_runs(self):
        from rfauto.service.r3_services import AgentChat
        chat = AgentChat()
        result = chat.chat("runs")
        assert result["action"] == "list_runs"

    def test_chat_unknown(self):
        from rfauto.service.r3_services import AgentChat
        chat = AgentChat()
        result = chat.chat("xyzzy unknown command")
        assert result["action"] == "help"

    def test_chat_history(self):
        from rfauto.service.r3_services import AgentChat
        chat = AgentChat()
        chat.chat("hello")
        chat.chat("solvers")
        assert len(chat.get_history()) == 4  # 2 user + 2 assistant

    def test_chat_validate(self, tmp_path):
        import yaml

        from rfauto.service.r3_services import AgentChat
        recipe = tmp_path / "r.yaml"
        recipe.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider", "params": {"arm_len_mm": {"value": 20.5}},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15}],
        }), encoding="utf-8")
        chat = AgentChat()
        result = chat.chat(f"validate {recipe}")
        assert result["action"] == "validate"


class TestEMSolverVisualizations:
    def test_base_class_returns_empty(self):
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType

        # Use a concrete subclass (palace skeleton)
        from rfauto.adapters.palace_solver import PalaceSolver
        config = EMSolverConfig(solver_type=EMSolverType.PALACE)
        solver = PalaceSolver(config)
        viz = solver.visualizations()
        assert isinstance(viz, list)
        formats = solver.supported_output_formats()
        assert "touchstone" in formats

    def test_palace_registered_in_global_registry(self):
        # palace_solver 曾从未注册（死代码，solvers list 不可见）
        import rfauto.adapters  # noqa: F401 - 触发注册
        from rfauto.adapters.em_solver_base import EMSolverType, get_global_registry
        registry = get_global_registry()
        assert registry.is_registered(EMSolverType.PALACE)
        assert EMSolverType.OPENEMS in registry.list_available()

# ─── B-32：审批流接入 A6 新求解器上线与 G13 资源容量变更 ───────────────────────

def _wilkinson_recipe(path: Path) -> Path:
    """最小可过三层 Gate 的 wilkinson 配方（B-32 混合收件箱用例）。"""
    import yaml
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
        "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
    }
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestSolverRegistrationApproval:
    """B-32：A6 新求解器上线必须走 pending_approvals，未批准不生效。"""

    @staticmethod
    def _cfg() -> Path:
        return Path("configs") / "solvers.yaml"

    def test_propose_pending_without_side_effect(self):
        from rfauto.service.r3_services import (
            _propose_solver_registration,
            list_pending_approvals,
        )
        r = _propose_solver_registration("comsol_rf", "comsol", exe_path="C:/COMSOL/bin")
        assert r["ok"] and r["status"] == "pending" and not r["duplicate"]
        assert not self._cfg().exists()  # 未批准不得生效
        inbox = list_pending_approvals()
        assert inbox["total"] == 1
        assert inbox["pending"][0]["change_id"] == r["change_id"]
        assert inbox["pending"][0]["kind"] == "solver_registration"
        # kind 过滤：两类变更共用一个收件箱但可分开看
        assert list_pending_approvals(kind="resource_capacity")["total"] == 0
        assert list_pending_approvals(kind="solver_registration")["total"] == 1

    def test_approve_registers_solver_and_clears_inbox(self):
        from rfauto.adapters.em_solver_base import load_solvers_config
        from rfauto.service.r3_services import (
            _propose_solver_registration,
            approve_proposal,
            list_pending_approvals,
        )
        r = _propose_solver_registration("comsol_rf", "comsol", exe_path="C:/COMSOL/bin")
        result = approve_proposal(r["change_id"][:12])  # 支持 change_id 前缀（UI 口径）
        assert result["ok"], result.get("errors")
        assert result["status"] == "applied"
        assert result["applied"]["loadable"] is True
        loaded = load_solvers_config(self._cfg())
        assert "comsol_rf" in loaded
        assert str(loaded["comsol_rf"].solver_type.value) == "comsol"
        assert loaded["comsol_rf"].exe_path == "C:/COMSOL/bin"
        assert list_pending_approvals()["total"] == 0

    def test_reject_not_effective_and_terminal(self):
        from rfauto.service.r3_services import (
            _propose_solver_registration,
            _reject_change,
            approve_proposal,
            list_pending_approvals,
        )
        r = _propose_solver_registration("comsol_rf", "comsol")
        rejected = _reject_change(r["change_id"], reason="暂不上线")
        assert rejected["ok"] and rejected["status"] == "rejected"
        assert not self._cfg().exists()  # 拒绝不生效
        assert list_pending_approvals()["total"] == 0
        # 重复拒绝幂等
        again = _reject_change(r["change_id"], reason="again")
        assert again["ok"] and again["duplicate"] and again["already_rejected"]
        # 已拒绝不可再批准（拒绝为终态）
        assert not approve_proposal(r["change_id"])["ok"]

    def test_duplicate_propose_is_idempotent(self):
        from rfauto.service.r3_services import (
            _propose_solver_registration,
            _read_audit_entries,
        )
        r1 = _propose_solver_registration("comsol_rf", "comsol", exe_path="X")
        r2 = _propose_solver_registration("comsol_rf", "comsol", exe_path="X")
        assert r1["change_id"] == r2["change_id"]
        assert r2["ok"] and r2["duplicate"] and r2["already_pending"]
        proposes = [e for e in _read_audit_entries() if e.get("event") == "propose"]
        assert len(proposes) == 1  # 重复提交未产生第二条审计

    def test_conflicting_propose_for_same_name_rejected(self):
        from rfauto.service.r3_services import _propose_solver_registration
        assert _propose_solver_registration("comsol_rf", "comsol")["ok"]
        conflict = _propose_solver_registration("comsol_rf", "openems")
        assert not conflict["ok"]

    def test_propose_already_registered_solver_rejected(self):
        from rfauto.service.r3_services import (
            _propose_solver_registration,
            add_solver_to_config,
        )
        assert add_solver_to_config("existing", "palace")["ok"]
        assert not _propose_solver_registration("existing", "palace")["ok"]

    def test_reapprove_is_idempotent(self):
        from rfauto.service.r3_services import (
            _propose_solver_registration,
            _read_audit_entries,
            approve_proposal,
        )
        r = _propose_solver_registration("comsol_rf", "comsol")
        first = approve_proposal(r["change_id"])
        assert first["ok"] and not first["duplicate"]
        second = approve_proposal(r["change_id"])
        assert second["ok"] and second["duplicate"] and second["already_applied"]
        applies = [e for e in _read_audit_entries()
                   if e.get("event") == "apply" and e.get("change_id") == r["change_id"]]
        assert len(applies) == 1  # 只有一次副作用

    def test_approve_unknown_change_fails(self):
        from rfauto.service.r3_services import approve_proposal
        assert not approve_proposal("chg_deadbeefdeadbeef")["ok"]


class TestResourceCapacityApproval:
    """B-32：G13 资源容量变更走 pending_approvals，批准后才落盘。"""

    @staticmethod
    def _cfg() -> Path:
        return Path("configs") / "resource_capacity.yaml"

    def test_propose_pending_without_side_effect(self):
        from rfauto.service.r3_services import (
            _load_resource_capacity_config,
            _propose_resource_change,
            list_pending_approvals,
        )
        r = _propose_resource_change("class", "fdtd", 5, note="FDTD 并发上限提升")
        assert r["ok"] and r["status"] == "pending"
        assert not self._cfg().exists()  # 未批准不落盘
        assert _load_resource_capacity_config() == {"solver_capacity": {}, "class_capacity": {}}
        inbox = list_pending_approvals()
        assert inbox["total"] == 1
        assert inbox["pending"][0]["kind"] == "resource_capacity"

    def test_approve_writes_capacity_feeding_scheduler(self):
        from rfauto.service.r3_services import (
            _load_resource_capacity_config,
            _propose_resource_change,
            approve_proposal,
            list_pending_approvals,
        )
        from rfauto.service.resource_scheduler import (
            ResourceJob,
            SchedulerConfig,
            required_resources,
        )
        r = _propose_resource_change("class", "fdtd", 5)
        result = approve_proposal(r["change_id"])
        assert result["ok"] and result["applied"]["capacity"] == 5
        assert self._cfg().exists()
        cfg = _load_resource_capacity_config()
        assert cfg["class_capacity"]["fdtd"] == 5
        # 已批准容量直接喂 G13 内核的 SchedulerConfig（默认 fdtd=3 → 5 生效）
        sc = SchedulerConfig(**cfg)
        assert sc.class_capacity["fdtd"] == 5
        reqs = required_resources(ResourceJob(job_id="j1", solver="openems"), sc)
        assert ("class:fdtd", 5) in reqs
        assert list_pending_approvals()["total"] == 0

    def test_reject_keeps_capacity_untouched(self):
        from rfauto.service.r3_services import (
            _load_resource_capacity_config,
            _propose_resource_change,
            _reject_change,
        )
        r = _propose_resource_change("solver", "comsol", 2)
        rejected = _reject_change(r["change_id"], reason="席位有限")
        assert rejected["ok"] and rejected["status"] == "rejected"
        assert not self._cfg().exists()
        assert _load_resource_capacity_config()["solver_capacity"] == {}

    def test_repropose_approved_value_is_noop(self):
        from rfauto.service.r3_services import _propose_resource_change, approve_proposal
        r = _propose_resource_change("solver", "hfss", 2)
        assert approve_proposal(r["change_id"])["ok"]
        again = _propose_resource_change("solver", "hfss", 2)
        assert again["ok"] and again["duplicate"] and again["already_effective"]

    def test_conflicting_capacity_proposal_rejected(self):
        from rfauto.service.r3_services import _propose_resource_change
        assert _propose_resource_change("solver", "hfss", 2)["ok"]
        assert not _propose_resource_change("solver", "hfss", 3)["ok"]

    def test_invalid_inputs_rejected(self):
        from rfauto.service.r3_services import _propose_resource_change
        assert not _propose_resource_change("bogus", "x", 1)["ok"]
        assert not _propose_resource_change("class", "bogus", 1)["ok"]
        assert not _propose_resource_change("solver", "hfss", -1)["ok"]
        assert not _propose_resource_change("solver", "hfss", "many")["ok"]


class TestApprovalInboxMixedKinds:
    """B-32：配方提案与配置变更提案共用一个收件箱，互不干扰。"""

    def test_solver_and_recipe_proposals_coexist(self):
        from rfauto.service.agent_safety import token_hash
        from rfauto.service.api import agent_propose
        from rfauto.service.r3_services import (
            _propose_solver_registration,
            approve_proposal,
            list_pending_approvals,
        )
        recipe = _wilkinson_recipe(Path("recipe.yaml"))
        proposed = agent_propose(recipe, {"arm_len_mm": 21.0})
        assert proposed["ok"], proposed.get("errors")
        r = _propose_solver_registration("comsol_rf", "comsol")
        assert list_pending_approvals()["total"] == 2
        # 批准求解器注册不影响配方提案
        assert approve_proposal(r["change_id"])["ok"]
        remaining = list_pending_approvals()
        assert remaining["total"] == 1
        assert remaining["pending"][0]["token_hash"] == token_hash(proposed["token"])


class TestAgentChatApprovalChannel:
    """B-32：AgentChat 通道回归——LLM 通道 monkeypatch 钉住，绝不触网（#139）。"""

    @pytest.fixture(autouse=True)
    def _pin_channel(self, monkeypatch):
        from rfauto.service import r3_services

        calls: list[tuple[str, object]] = []

        def fake_turn(self, message, pending=None):
            calls.append((message, pending))
            return {"text": f"STUB:{message}", "action": "chat", "result": None, "tools": []}

        monkeypatch.setattr(r3_services, "get_chat_settings",
                            lambda: {"ok": True, "configured": True})
        monkeypatch.setattr(r3_services.AgentChat, "_llm_turn", fake_turn)
        self.calls = calls
        yield

    def test_configured_chat_uses_pinned_channel(self):
        from rfauto.service.r3_services import AgentChat
        chat = AgentChat()
        out = chat.chat("solvers")
        assert out["text"] == "STUB:solvers"
        assert self.calls == [("solvers", None)]
        assert out["stats"]["turns"] == 1

    def test_keyword_route_without_llm(self, monkeypatch):
        from rfauto.service import r3_services
        monkeypatch.setattr(r3_services, "get_chat_settings",
                            lambda: {"ok": True, "configured": False})
        chat = r3_services.AgentChat()
        assert chat.chat("solvers")["action"] == "list_solvers"

    def test_agent_cannot_self_approve_config_changes(self):
        from rfauto.service.r3_services import _execute_tool
        # agent 工具面不暴露审批/注册工具：配置变更只能人工批准
        assert "error" in _execute_tool("propose_solver_registration", {})
        assert "error" in _execute_tool("approve_change", {"change_id": "chg_x"})

