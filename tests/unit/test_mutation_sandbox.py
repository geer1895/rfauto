"""B-31：E6 拓扑变异接沙箱（三层 Gate）定向测试。

覆盖：
- 变异提案只落 RecipeSandbox 草稿，真实配方文件零改动（未直接写工作区）；
- 越权直写（../、绝对外部路径、非法后缀）抛 SandboxViolation；
- promote 走既有 AgentGate 三层链——通过时拿回 L3 token，拒绝时如实返回
  （越界参数 L2 拒 / 非 params 改动 promote 拒），不静默放行。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rfauto.service.agent_sandbox import RecipeSandbox, SandboxViolation
from rfauto.service.mutation_sandbox import stage_mutation, write_sandbox_draft


def _recipe_dict(*, low: float, high: float, value: float = 20.5) -> dict:
    """最小合法配方（单一 params 标量条目，变异目标确定）。"""
    return {
        "model": "wilkinson_power_divider",
        "recipe_version": 1,
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": value, "unit": "mm"}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
        "optimization": {"params": {"arm_len_mm": {"low": low, "high": high}}},
    }


@pytest.fixture
def recipe_path(tmp_path) -> Path:
    """宽范围配方：modify_param 的 ±20% 变异必定留在 L2 范围内。"""
    p = tmp_path / "recipe.yaml"
    p.write_text(yaml.safe_dump(_recipe_dict(low=1.0, high=100.0)),
                 encoding="utf-8")
    return p


@pytest.fixture
def sandbox(tmp_path) -> RecipeSandbox:
    return RecipeSandbox(root=tmp_path / "sb")


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """审计日志/草稿相对路径隔离（#144 惯例）。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestStageMutationGoesThroughSandbox:
    def test_param_mutation_staged_into_sandbox_not_workspace(
            self, recipe_path, sandbox):
        original = recipe_path.read_text(encoding="utf-8")
        out = stage_mutation(recipe_path, seed=1,
                             mutation_types=["modify_param"], sandbox=sandbox)

        assert out["staged"] is True
        assert out["status"] == "staged"
        assert out["ok"] is True
        # 草稿确实落在沙箱根内，且不在真实配方目录
        draft = Path(out["sandbox_path"])
        assert draft.exists()
        assert sandbox.root in draft.parents
        assert draft.parent != recipe_path.parent
        # 变异确有 params 差异
        assert out["param_deltas"] == {"arm_len_mm": out["proposal"]["params"]["arm_len_mm"]["value"]}
        # 真实配方零改动（未直接写工作区）
        assert recipe_path.read_text(encoding="utf-8") == original
        assert out["workspace_recipe_untouched"] is True
        # 三层 Gate 全过（未请求 promote）
        assert out["gate"]["L1"]["passed"] is True
        assert out["gate"]["L2"]["passed"] is True
        assert out["gate"]["L3"]["passed"] is True

    def test_ops_mutation_staged_but_promote_rejected_honestly(
            self, recipe_path, sandbox):
        original = recipe_path.read_text(encoding="utf-8")
        out = stage_mutation(recipe_path, seed=3, mutation_types=["add_stub"],
                             sandbox=sandbox, promote=True)

        assert out["staged"] is True
        assert out["status"] == "promote_rejected"
        assert out["ok"] is False
        assert out["promote_result"]["ok"] is False
        assert out["promote_result"]["stage"] == "promote"
        assert "params 之外" in out["promote_result"]["error"]
        # 草稿仍落盘（先沙箱后 Gate），真实配方仍零改动
        assert Path(out["sandbox_path"]).exists()
        assert recipe_path.read_text(encoding="utf-8") == original
        assert any(op.get("op") == "add_stub" for op in out["proposal"]["ops"])

    def test_param_mutation_promotes_through_three_layer_gate(
            self, recipe_path, sandbox):
        out = stage_mutation(recipe_path, seed=5,
                             mutation_types=["modify_param"], sandbox=sandbox,
                             promote=True)

        assert out["status"] == "promoted"
        assert out["ok"] is True
        promo = out["promote_result"]
        assert promo["ok"] is True
        assert promo["stage"] == "L3"
        assert promo["sandbox_promote"] is True
        assert set(promo["params_proposed"]) == {"arm_len_mm"}
        # L3 token 是 16 位派生哈希（AgentGate.check_l3 口径）
        assert isinstance(promo["token"], str) and len(promo["token"]) == 16

    def test_gate_rejects_out_of_bounds_mutation_honestly(
            self, tmp_path, sandbox):
        narrow = tmp_path / "narrow.yaml"
        narrow.write_text(
            yaml.safe_dump(_recipe_dict(low=100.0, high=200.0)),
            encoding="utf-8")
        original = narrow.read_text(encoding="utf-8")

        out = stage_mutation(narrow, seed=7, mutation_types=["modify_param"],
                             sandbox=sandbox, promote=True)

        assert out["status"] == "gate_rejected"
        assert out["ok"] is False
        assert out["gate"]["L2"]["passed"] is False
        assert out["gate"]["L2"]["details"]["issues"]
        # Gate 拒绝后不再走 promote（不绕过 Gate）
        assert out["promote_result"] is None
        # 草稿仍在沙箱内，真实配方零改动
        assert Path(out["sandbox_path"]).exists()
        assert narrow.read_text(encoding="utf-8") == original

    def test_missing_recipe_returns_error_json(self, tmp_path, sandbox):
        out = stage_mutation(tmp_path / "ghost.yaml", sandbox=sandbox)
        assert out["status"] == "error"
        assert out["ok"] is False
        assert out["errors"]


class TestSandboxWriteGuard:
    def test_direct_write_outside_sandbox_raises(self, tmp_path, sandbox):
        with pytest.raises(SandboxViolation):
            write_sandbox_draft(sandbox, "../escape.yaml", "x: 1\n")
        with pytest.raises(SandboxViolation):
            write_sandbox_draft(sandbox, str(tmp_path / "outside.yaml"), "x: 1\n")
        # 非法后缀借沙箱写脚本同样拒绝
        with pytest.raises(SandboxViolation):
            write_sandbox_draft(sandbox, "evil.py", "print(1)\n")
        # 越权目标从未落盘
        assert not (tmp_path / "escape.yaml").exists()
        assert not (tmp_path / "outside.yaml").exists()

    def test_legit_draft_name_writes_inside_root(self, tmp_path, sandbox):
        written = write_sandbox_draft(sandbox, "ok_draft.yaml", "x: 1\n")
        assert written.exists()
        assert sandbox.root in written.parents
        assert written.read_text(encoding="utf-8") == "x: 1\n"
