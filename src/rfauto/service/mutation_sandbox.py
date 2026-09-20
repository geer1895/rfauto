"""拓扑变异 → 沙箱 → 三层 Gate 的 service 层接线。

optimization/mutation.py 的 TopologyMutator/MutationReviewer 只产出变异提案
（纯数据，无写面）；本模块是变异提案接沙箱的唯一通道：

    TopologyMutator.mutate() → RecipeSandbox 草稿 → AgentGate 三层协议
    → RecipeSandbox.promote()（既有 propose/promote 审批链，与人工提案同权）

分层约束：optimization 不能 import service（import-linter 强制），故接线只能
落在本层。核心不变量：
- 变异结果只写 runs/recipe_sandbox/ 草稿，真实 recipes/ 文件永不被本模块写；
- 越界草稿名/非法后缀由沙箱守卫拒绝（SandboxViolation）；
- promote 只经既有 agent_propose（L1 白名单 / L2 dry-run / L3 token），
  非 params 改动与越界参数都如实返回拒绝，不绕过 Gate。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from rfauto.optimization.mutation import TopologyMutator
from rfauto.service.agent_gate import AgentGate
from rfauto.service.agent_sandbox import RecipeSandbox


def _effective(entry: Any) -> Any:
    """取参数的生效标量值（{"value": x} → x，标量原样）。"""
    return entry.get("value") if isinstance(entry, dict) else entry


def _param_deltas(original: dict[str, Any],
                  proposal: dict[str, Any]) -> dict[str, Any]:
    """原始配方与变异提案的 params 生效值差异（只保留变化项）。"""
    orig = {k: _effective(v) for k, v in (original.get("params") or {}).items()}
    new = {k: _effective(v) for k, v in (proposal.get("params") or {}).items()}
    return {k: new.get(k) for k in set(orig) | set(new)
            if orig.get(k) != new.get(k)}


def write_sandbox_draft(sandbox: RecipeSandbox, draft_name: str,
                        content: str) -> Path:
    """服务层唯一草稿写入口：显式草稿名先过沙箱守卫再落盘。

    守卫拒绝越界路径（../、绝对外部路径）与非法后缀（非 .yaml/.yml）时
    抛 SandboxViolation——变异提案没有任何绕过沙箱直写工作区的通道。
    """
    target = sandbox._guard(draft_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _run_gate(params: dict[str, Any],
              recipe: dict[str, Any]) -> dict[str, Any]:
    """跑 AgentGate 三层协议（L1/L2/L3），返回 JSON 友好的完整结果。"""
    gate = AgentGate()
    l1 = gate.check_l1(params, recipe)
    l2 = gate.check_l2(params, recipe)
    l3 = gate.check_l3(l1, l2, params)
    return {
        "passed": bool(l1.passed and l2.passed and l3.passed),
        "L1": l1.to_dict(),
        "L2": l2.to_dict(),
        "L3": l3.to_dict(),
    }


def stage_mutation(
    recipe_path: str | Path,
    *,
    seed: int = 42,
    n_mutations: int = 1,
    mutation_types: list[str] | None = None,
    sandbox: RecipeSandbox | None = None,
    adapter_name: str = "fake",
    promote: bool = False,
) -> dict[str, Any]:
    """对配方跑拓扑变异，落沙箱草稿，再过三层 Gate（可选 promote）。

    Args:
        recipe_path: 待变异配方（只读；本函数从不写它）。
        seed: TopologyMutator 随机种子（确定性可复现）。
        n_mutations: 变异次数（取首个提案接线，其余仅计数）。
        mutation_types: 允许的变异类型；None = TopologyMutator.MUTATION_OPS。
        sandbox: 沙箱实例（默认 runs/recipe_sandbox/）。
        adapter_name: promote 时 dry-run 的适配器（默认 fake）。
        promote: True 时草稿差异继续走 RecipeSandbox.promote（既有审批链）。

    Returns:
        JSON 友好 dict：status / proposal / sandbox_path / gate / promote_result。
        status 取值：
        - "error"：配方缺失/损坏；
        - "no_proposal"：变异器未产出提案；
        - "gate_rejected"：L1/L2 未过，未进 promote；
        - "staged"：已落沙箱且 Gate 通过（未请求 promote）；
        - "promoted"：promote 成功（拿回 L3 token）；
        - "promote_rejected"：Gate 通过但 promote 被既有审批链拒绝。
    """
    path = Path(recipe_path)
    sb = sandbox or RecipeSandbox()
    try:
        original_text = path.read_text(encoding="utf-8")
        original = yaml.safe_load(original_text)
        if not isinstance(original, dict):
            raise ValueError(f"配方顶层必须是映射: {path}")
    except (OSError, yaml.YAMLError, ValueError) as exc:
        return {"ok": False, "status": "error", "recipe": str(path),
                "errors": [str(exc)]}

    proposals = TopologyMutator(seed=seed).mutate(
        original, n_mutations=n_mutations, mutation_types=mutation_types)
    if not proposals:
        return {"ok": False, "status": "no_proposal", "recipe": str(path),
                "sandbox_root": str(sb.root), "sandbox_path": None,
                "proposal": None, "gate": None, "promote_result": None}

    proposal = proposals[0]
    deltas = _param_deltas(original, proposal)

    # 1) 先落沙箱草稿（唯一写面；沙箱守卫拒绝越界名）
    draft = write_sandbox_draft(
        sb, sb.draft_path(path).name,
        yaml.safe_dump(proposal, allow_unicode=True, sort_keys=False))

    # 2) 三层 Gate（L1 白名单 / L2 dry-run 范围 / L3 token）
    gate = _run_gate(deltas, original)

    result: dict[str, Any] = {
        "ok": False,
        "status": "staged",
        "recipe": str(path),
        "sandbox_root": str(sb.root),
        "sandbox_path": str(draft),
        "staged": True,
        "workspace_recipe_untouched": (
            path.read_text(encoding="utf-8") == original_text),
        "proposal": proposal,
        "param_deltas": deltas,
        "n_proposals": len(proposals),
        "gate": gate,
        "promote_result": None,
    }

    if not gate["passed"]:
        result["status"] = "gate_rejected"
        result["message"] = "三层 Gate 拒绝：L1/L2 未过，未进入 promote"
        return result

    if not promote:
        result["ok"] = True
        result["message"] = "变异提案已落沙箱草稿，三层 Gate 通过（未请求 promote）"
        return result

    # 3) promote 走既有审批链（agent_propose → AgentGate → apply）
    promo = sb.promote(path, adapter_name=adapter_name)
    result["promote_result"] = promo
    if promo.get("ok"):
        result["ok"] = True
        result["status"] = "promoted"
        result["message"] = "变异提案经沙箱 promote 通过三层 Gate"
    else:
        result["status"] = "promote_rejected"
        result["message"] = f"promote 被拒绝（stage={promo.get('stage')}）：{promo.get('error')}"
    return result
