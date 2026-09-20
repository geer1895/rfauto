"""Agent 编排。

Gate 三层协议（ADR-0020）：
- L1 参数白名单（params_model 校验，越界拒绝）
- L2 dry-run（service.dry_run 已有，执行计划不落地）
- L3 确认 token（由 L1/L2 结果哈希派生，防 LLM 篡改重放）

设计决策：
- Agent 能力分级 propose/dry_run/apply/audit
- 只 propose 不 apply（除非审批）
- CI 验收用 mock agent（确定性）
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class AgentCapability(str, Enum):
    """Agent 能力级别。"""
    PROPOSE = "propose"      # 只提建议
    DRY_RUN = "dry_run"      # 可执行 dry-run
    APPLY = "apply"          # 可执行实际操作
    AUDIT = "audit"          # 可审计历史


@dataclass
class GateResult:
    """Gate 检查结果。"""
    level: str  # "L1" | "L2" | "L3"
    passed: bool
    details: dict[str, Any]
    token: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "passed": self.passed,
            "details": self.details,
            "token": self.token,
        }


class AgentGate:
    """Agent 三层协议 Gate。

    用法：
        gate = AgentGate()
        # L1: 参数白名单校验
        l1 = gate.check_l1(params, recipe)
        # L2: dry-run
        l2 = gate.check_l2(params, recipe)
        # L3: 确认 token
        l3 = gate.check_l3(l1, l2)
    """

    def __init__(self, allowed_params: set[str] | None = None):
        self._allowed_params = allowed_params or set()

    def check_l1(
        self,
        params: dict[str, Any],
        recipe: dict[str, Any],
    ) -> GateResult:
        """L1: 参数白名单校验。

        检查所有参数是否在配方定义范围内。
        """
        recipe_params = set(recipe.get("params", {}).keys())
        opt_params = set(recipe.get("optimization", {}).get("params", {}).keys())
        all_allowed = recipe_params | opt_params | self._allowed_params

        violations = []
        for key in params:
            if key not in all_allowed:
                violations.append(f"未知参数: {key}")

        return GateResult(
            level="L1",
            passed=len(violations) == 0,
            details={"violations": violations, "allowed": sorted(all_allowed)},
        )

    def check_l2(
        self,
        params: dict[str, Any],
        recipe: dict[str, Any],
    ) -> GateResult:
        """L2: dry-run 检查。

        验证参数值是否在合法范围内。边界来源两种（任一命中即校验）：
        - recipe.params[key].bounds = [low, high]
        - recipe.optimization.params[key].low/high（Optuna 搜索空间格式）
        """
        issues = []
        recipe_params = recipe.get("params", {})
        opt_params = recipe.get("optimization", {}).get("params", {})
        for key, value in params.items():
            recipe_param = recipe_params.get(key, {})
            if isinstance(recipe_param, dict) and "bounds" in recipe_param:
                low, high = recipe_param["bounds"]
            elif key in opt_params and isinstance(opt_params[key], dict):
                low = opt_params[key].get("low")
                high = opt_params[key].get("high")
                if low is None or high is None:
                    continue
            else:
                continue
            if not (low <= value <= high):
                issues.append(f"{key}={value} 超出范围 [{low}, {high}]")

        return GateResult(
            level="L2",
            passed=len(issues) == 0,
            details={"issues": issues},
        )

    def check_l3(
        self,
        l1_result: GateResult,
        l2_result: GateResult,
        params: dict[str, Any] | None = None,
    ) -> GateResult:
        """L3: 确认 token 生成。

        由 L1/L2 结果哈希派生，防 LLM 篡改重放。params 传入时一并纳入哈希——
        否则超界内的参数篡改（L1/L2 结果不变）会拿到同一个 token。
        """
        if not l1_result.passed or not l2_result.passed:
            return GateResult(
                level="L3",
                passed=False,
                details={"reason": "L1 或 L2 未通过"},
                token=None,
            )

        # 生成 token
        content = json.dumps({
            "l1": l1_result.details,
            "l2": l2_result.details,
            "params": params or {},
        }, sort_keys=True, default=str)
        token = hashlib.sha256(content.encode()).hexdigest()[:16]

        return GateResult(
            level="L3",
            passed=True,
            details={"token_source": "L1+L2+params hash"},
            token=token,
        )

    def validate_token(
        self,
        token: str,
        l1_result: GateResult,
        l2_result: GateResult,
        params: dict[str, Any] | None = None,
    ) -> bool:
        """验证 token 是否有效（params 须与签发时一致）。"""
        expected = self.check_l3(l1_result, l2_result, params)
        return expected.token == token
