"""拓扑变异原型（P6）—— 几何操作序列(AST)变异算子。

对 recipe 的 ops 序列进行变异，生成新的拓扑结构。
配合人工审批 gate，实现半自动拓扑探索。
"""

from __future__ import annotations

import copy
import logging
import random
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class TopologyMutator:
    """拓扑变异器。

    对 recipe 的 ops 序列进行变异，生成新的拓扑结构。
    """

    # 支持的变异操作
    MUTATION_OPS: ClassVar[list[str]] = [
        "add_stub",      # 添加枝节
        "add_slot",      # 添加槽
        "add_via",       # 添加过孔
        "remove_op",     # 移除操作
        "modify_param",  # 修改参数
    ]

    def __init__(self, seed: int = 42) -> None:
        self.rng = random.Random(seed)

    def mutate(
        self,
        recipe: dict[str, Any],
        n_mutations: int = 1,
        mutation_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """对配方进行变异。

        Args:
            recipe: 原始配方
            n_mutations: 变异次数
            mutation_types: 允许的变异类型（默认全部）

        Returns:
            list of mutated recipes
        """
        mutation_types = mutation_types or self.MUTATION_OPS
        mutated_recipes = []

        for _ in range(n_mutations):
            mutated = copy.deepcopy(recipe)
            mutation_type = self.rng.choice(mutation_types)

            if mutation_type == "add_stub":
                mutated = self._add_stub(mutated)
            elif mutation_type == "add_slot":
                mutated = self._add_slot(mutated)
            elif mutation_type == "add_via":
                mutated = self._add_via(mutated)
            elif mutation_type == "remove_op":
                mutated = self._remove_op(mutated)
            elif mutation_type == "modify_param":
                mutated = self._modify_param(mutated)

            mutated_recipes.append(mutated)

        return mutated_recipes

    def _add_stub(self, recipe: dict[str, Any]) -> dict[str, Any]:
        """添加枝节操作。"""
        ops = recipe.get("ops", [])
        new_op = {
            "op": "add_stub",
            "target": "trace_main",
            "params": {
                "length_mm": round(self.rng.uniform(1.0, 10.0), 2),
                "width_mm": round(self.rng.uniform(0.1, 2.0), 2),
                "position": round(self.rng.uniform(0.2, 0.8), 2),
            },
        }
        ops.append(new_op)
        recipe["ops"] = ops
        return recipe

    def _add_slot(self, recipe: dict[str, Any]) -> dict[str, Any]:
        """添加槽操作。"""
        ops = recipe.get("ops", [])
        new_op = {
            "op": "add_slot",
            "target": "substrate",
            "params": {
                "length_mm": round(self.rng.uniform(2.0, 15.0), 2),
                "width_mm": round(self.rng.uniform(0.1, 1.0), 2),
                "position_x": round(self.rng.uniform(-5.0, 5.0), 2),
                "position_y": round(self.rng.uniform(-10.0, 10.0), 2),
            },
        }
        ops.append(new_op)
        recipe["ops"] = ops
        return recipe

    def _add_via(self, recipe: dict[str, Any]) -> dict[str, Any]:
        """添加过孔操作。"""
        ops = recipe.get("ops", [])
        new_op = {
            "op": "add_via",
            "target": "ground",
            "params": {
                "radius_mm": round(self.rng.uniform(0.2, 0.5), 2),
                "position_x": round(self.rng.uniform(-5.0, 5.0), 2),
                "position_y": round(self.rng.uniform(-10.0, 10.0), 2),
            },
        }
        ops.append(new_op)
        recipe["ops"] = ops
        return recipe

    def _remove_op(self, recipe: dict[str, Any]) -> dict[str, Any]:
        """移除操作。"""
        ops = recipe.get("ops", [])
        if ops:
            idx = self.rng.randint(0, len(ops) - 1)
            ops.pop(idx)
            recipe["ops"] = ops
        return recipe

    def _modify_param(self, recipe: dict[str, Any]) -> dict[str, Any]:
        """修改参数。"""
        params = recipe.get("params", {})
        if params:
            key = self.rng.choice(list(params.keys()))
            if isinstance(params[key], dict) and "value" in params[key]:
                old_value = params[key]["value"]
                # 随机变化 ±20%
                new_value = old_value * self.rng.uniform(0.8, 1.2)
                params[key]["value"] = round(new_value, 4)
        return recipe


class MutationReviewer:
    """变异审批器。

    人工审批 gate：变异后的配方需要人工确认才能执行。
    """

    def __init__(self) -> None:
        self.pending: list[dict[str, Any]] = []
        self.approved: list[dict[str, Any]] = []
        self.rejected: list[dict[str, Any]] = []

    def submit(self, recipe: dict[str, Any], mutation_type: str) -> None:
        """提交变异配方等待审批。"""
        self.pending.append({
            "recipe": recipe,
            "mutation_type": mutation_type,
            "status": "pending",
        })

    def approve(self, index: int) -> dict[str, Any] | None:
        """审批通过。"""
        if 0 <= index < len(self.pending):
            item = self.pending.pop(index)
            item["status"] = "approved"
            self.approved.append(item)
            return item["recipe"]
        return None

    def reject(self, index: int) -> None:
        """拒绝。"""
        if 0 <= index < len(self.pending):
            item = self.pending.pop(index)
            item["status"] = "rejected"
            self.rejected.append(item)

    def get_pending(self) -> list[dict[str, Any]]:
        """获取待审批列表。"""
        return self.pending.copy()
