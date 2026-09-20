"""E4b Agent 编排单元测试。"""

from __future__ import annotations

from rfauto.service.agent_gate import (
    AgentCapability,
    AgentGate,
    GateResult,
)


class TestAgentGate:
    def test_l1_pass(self):
        gate = AgentGate()
        recipe = {
            "params": {"arm_len_mm": {"value": 20.5}},
            "optimization": {"params": {"arm_len_mm": {"low": 17, "high": 21}}},
        }
        result = gate.check_l1({"arm_len_mm": 20.0}, recipe)
        assert result.passed
        assert result.level == "L1"

    def test_l1_fail_unknown_param(self):
        gate = AgentGate()
        recipe = {"params": {"arm_len_mm": {"value": 20.5}}}
        result = gate.check_l1({"unknown_param": 1.0}, recipe)
        assert not result.passed
        assert len(result.details["violations"]) > 0

    def test_l2_pass(self):
        gate = AgentGate()
        recipe = {
            "params": {
                "arm_len_mm": {"value": 20.5, "bounds": [17, 21]},
            }
        }
        result = gate.check_l2({"arm_len_mm": 20.0}, recipe)
        assert result.passed

    def test_l2_fail_out_of_range(self):
        gate = AgentGate()
        recipe = {
            "params": {
                "arm_len_mm": {"value": 20.5, "bounds": [17, 21]},
            }
        }
        result = gate.check_l2({"arm_len_mm": 25.0}, recipe)
        assert not result.passed

    def test_l3_token_generation(self):
        gate = AgentGate()
        l1 = GateResult(level="L1", passed=True, details={})
        l2 = GateResult(level="L2", passed=True, details={})
        l3 = gate.check_l3(l1, l2)
        assert l3.passed
        assert l3.token is not None
        assert len(l3.token) == 16

    def test_l3_fail_if_l1_or_l2_fail(self):
        gate = AgentGate()
        l1 = GateResult(level="L1", passed=False, details={})
        l2 = GateResult(level="L2", passed=True, details={})
        l3 = gate.check_l3(l1, l2)
        assert not l3.passed
        assert l3.token is None

    def test_validate_token(self):
        gate = AgentGate()
        l1 = GateResult(level="L1", passed=True, details={"a": 1})
        l2 = GateResult(level="L2", passed=True, details={"b": 2})
        l3 = gate.check_l3(l1, l2)
        assert gate.validate_token(l3.token, l1, l2)

    def test_validate_invalid_token(self):
        gate = AgentGate()
        l1 = GateResult(level="L1", passed=True, details={"a": 1})
        l2 = GateResult(level="L2", passed=True, details={"b": 2})
        assert not gate.validate_token("invalid_token", l1, l2)


class TestAgentCapability:
    def test_capabilities(self):
        assert AgentCapability.PROPOSE.value == "propose"
        assert AgentCapability.APPLY.value == "apply"
