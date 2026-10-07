"""XN-2 需求工程前端（round19 P2，ge8c 席C6）——需求分层+冲突检测+可测性检查。

定位（round19 口径"需求分层（must/should/want）+冲突检测（Z3）+可测性检查
（需求↔判据映射，接 EP-2 成环）；level2 NL→DesignIntent 的上游延伸"）：

- **分层**：MoSCoW 三档（must/should/want），纯声明对象（pydantic 校验）；
- **冲突检测**：双层——
  1. 规则层（确定性，零依赖）：同一 quantity 的边界约束互相矛盾
     （``>=v1`` 与 ``<=v0`` 且 ``v0<v1``；``==v`` 与 ``excludes v`` 等）逐对
     判 conflict（must×must）/tension（跨档）；
  2. Z3 层（可选依赖，惰性 import，render_constraints 降级先例）：把全部
     must 约束编码为线性算术一次求解，UNSAT 即整体不可行（规则层逐对检查
     抓不住的三条互约束可由 UNSAT core 报出）。z3 缺装 → status=
     "unavailable"，规则层结果照常返回（#105：增强件不得成为主路径故障点）；
- **可测性检查**：需求↔判据映射（criteria_ref 非空即"有判据"）。must 无
  判据 = untestable（error 档）；should 无判据 = warn 档；want 不强制。

服务层薄壳与 CLI 接线非本件范围（登记/原型级交付：内核+schema+测试）。
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "REQ_SCHEMA",
    "Z3_INSTALL_HINT",
    "ConstraintOp",
    "Requirement",
    "RequirementSet",
    "requirements_review",
]

#: 需求集 schema 标识（JSON 消费面稳定钉）。
REQ_SCHEMA = "rfauto-requirements-v1"

#: z3 缺装降级 reason（render_constraints 同款口径）。
Z3_INSTALL_HINT = "pip install rfauto[z3]（或 pip install z3-solver）"


class ConstraintOp(str, Enum):
    """约束算子词表（收敛最小集；新算子=显式扩枚举）。"""

    GTE = ">="
    LTE = "<="
    EQ = "=="
    IN = "in"
    EXCLUDES = "excludes"


class Requirement(BaseModel):
    """一条需求（MoSCoW 分层 + 可选量化约束 + 判据映射）。"""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1)
    level: str = Field(pattern="^(must|should|want)$")
    #: 量化约束（同一需求内同 quantity 多条 = AND）；数值型 op 用 float 值，
    #: 集合型 op（in/excludes）用 str/数值列表。
    constraints: dict[str, list[tuple[str, Any]]] = Field(default_factory=dict)
    #: 需求↔判据映射（EP-2 判据 id/名；空 = 无判据 → 可测性检查裁决）
    criteria_ref: str = ""
    note: str = ""

    @field_validator("constraints")
    @classmethod
    def _validate_constraints(
        cls, v: dict[str, list[tuple[str, Any]]]
    ) -> dict[str, list[tuple[str, Any]]]:
        for qty, pairs in v.items():
            if not qty or not isinstance(qty, str):
                raise ValueError(f"constraint quantity 非法: {qty!r}")
            for op, value in pairs:
                try:
                    ConstraintOp(op)
                except ValueError as exc:
                    raise ValueError(
                        f"约束算子非法: {op!r}（quantity={qty}）") from exc
                if op in (ConstraintOp.GTE, ConstraintOp.LTE, ConstraintOp.EQ):
                    if isinstance(value, bool):
                        raise ValueError(
                            f"数值算子 {op} 的值不可为 bool: {value!r}")
                    if isinstance(value, str):
                        # 仅 == 允许字符串等值（工艺/封装等名义量）；z3 层跳过
                        if op != ConstraintOp.EQ:
                            raise ValueError(
                                f"{op} 不可作用于字符串: {value!r}")
                        if not value.strip():
                            raise ValueError("字符串等值不可为空")
                    elif not isinstance(value, (int, float)):
                        raise ValueError(
                            f"算子 {op} 的值必须是有限数或非空 str: {value!r}")
                    elif value != value or value in (float("inf"), float("-inf")):
                        raise ValueError("约束值必须有限")
                else:  # in / excludes
                    if not isinstance(value, (list, tuple)) or not value:
                        raise ValueError(
                            f"集合算子 {op} 的值必须非空列表: {value!r}")
        return v

    @property
    def is_must(self) -> bool:
        return self.level == "must"


class RequirementSet(BaseModel):
    """需求集合（id 唯一性在此收敛）。"""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    requirements: list[Requirement] = Field(min_length=1)

    @field_validator("requirements")
    @classmethod
    def _unique_ids(cls, v: list[Requirement]) -> list[Requirement]:
        ids = [r.id for r in v]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"需求 id 重复: {dupes}")
        return v


# ---------------------------------------------------------------------------
# 规则层冲突检测（确定性逐对；零 z3 依赖）
# ---------------------------------------------------------------------------

#: 档位冲突语义：(must×must)=conflict；跨档=tension；同档非 must=tension。
_SEVERITY_RANK = {"must": 2, "should": 1, "want": 0}


def _pair_severity(a: Requirement, b: Requirement) -> str | None:
    """两需求冲突的严重档：conflict（must×must）/ tension（其余）/ None（不算冲突）。"""
    if a.is_must and b.is_must:
        return "conflict"
    if _SEVERITY_RANK[a.level] or _SEVERITY_RANK[b.level]:
        return "tension"
    return None


def _numeric_conflict(pairs_a: list[tuple[str, Any]],
                      pairs_b: list[tuple[str, Any]]) -> str | None:
    """同一 quantity 两组约束的矛盾判定；返回矛盾描述或 None。

    覆盖：``>=``×``<=`` 交叉越界；数值 ``==``×``==`` 不等；数值 ``==``
    与 ``>=/<=`` 越界；``==``×``excludes``（数值/字符串等值皆覆盖）；
    字符串 ``==``×``==`` 不等；``in``×``in`` 交集空。
    """
    lo_a = max((float(v) for op, v in pairs_a if op == ConstraintOp.GTE),
               default=-math.inf)
    hi_a = min((float(v) for op, v in pairs_a if op == ConstraintOp.LTE),
               default=math.inf)
    lo_b = max((float(v) for op, v in pairs_b if op == ConstraintOp.GTE),
               default=-math.inf)
    hi_b = min((float(v) for op, v in pairs_b if op == ConstraintOp.LTE),
               default=math.inf)
    if lo_a > hi_b or lo_b > hi_a:
        return f"区间不相交：[{lo_a:g}, {hi_a:g}] ∩ [{lo_b:g}, {hi_b:g}] = ∅"

    def eqs(pairs: list[tuple[str, Any]]) -> set[float]:
        return {float(v) for op, v in pairs
                if op == ConstraintOp.EQ and isinstance(v, (int, float))
                and not isinstance(v, bool)}

    def seqs(pairs: list[tuple[str, Any]]) -> set[str]:
        return {str(v) for op, v in pairs
                if op == ConstraintOp.EQ and isinstance(v, str)}

    eq_a, eq_b = eqs(pairs_a), eqs(pairs_b)
    if eq_a and eq_b and eq_a != eq_b:
        return f"等值约束冲突：{sorted(eq_a)} vs {sorted(eq_b)}"
    str_eq_a, str_eq_b = seqs(pairs_a), seqs(pairs_b)
    if str_eq_a and str_eq_b and str_eq_a != str_eq_b:
        return f"字符串等值冲突：{sorted(str_eq_a)} vs {sorted(str_eq_b)}"
    for eq_set, other_pairs, tag in ((eq_a, pairs_b, "a=="), (eq_b, pairs_a, "b==")):
        for v in eq_set:
            for op, w in other_pairs:
                if op == ConstraintOp.GTE and float(w) > v:
                    return f"等值 {v:g} 与 >= {float(w):g} 矛盾（{tag}）"
                if op == ConstraintOp.LTE and float(w) < v:
                    return f"等值 {v:g} 与 <= {float(w):g} 矛盾（{tag}）"
    # == × excludes：对方 excludes 列表覆盖本方 == 值（数值/字符串等值皆查）
    for own_pairs, other_pairs, tag in ((pairs_a, pairs_b, "a"),
                                        (pairs_b, pairs_a, "b")):
        own_eq_vals = [v for op, v in own_pairs if op == ConstraintOp.EQ]
        if not own_eq_vals:
            continue
        for op, v in other_pairs:
            if op != ConstraintOp.EXCLUDES:
                continue
            excluded = list(v) if isinstance(v, (list, tuple)) else [v]
            for w in own_eq_vals:
                if any(_same_scalar(w, x) for x in excluded) or (
                        isinstance(w, str)
                        and w in {str(x) for x in excluded}):
                    return f"{tag} 的 == 值 {w!r} 被对方 excludes 覆盖"
    # in × in 交集空（集合型）
    ins_a = [set(map(str, v)) for op, v in pairs_a if op == ConstraintOp.IN]
    ins_b = [set(map(str, v)) for op, v in pairs_b if op == ConstraintOp.IN]
    for sa in ins_a:
        for sb in ins_b:
            if sa and sb and not (sa & sb):
                return f"枚举交集为空：{sorted(sa)} ∩ {sorted(sb)} = ∅"
    return None


def _same_scalar(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        try:
            return float(a) == float(b)
        except (TypeError, ValueError):
            return False
    return str(a) == str(b)


def _rule_conflicts(reqs: list[Requirement]) -> list[dict[str, Any]]:
    """逐对规则冲突（确定性；i<j 序去重）。"""
    out: list[dict[str, Any]] = []
    for i in range(len(reqs)):
        for j in range(i + 1, len(reqs)):
            a, b = reqs[i], reqs[j]
            shared = sorted(set(a.constraints) & set(b.constraints))
            for qty in shared:
                desc = _numeric_conflict(a.constraints[qty],
                                         b.constraints[qty])
                if desc is None:
                    continue
                sev = _pair_severity(a, b)
                if sev is None:
                    continue
                out.append({
                    "kind": "constraint_contradiction",
                    "quantity": qty,
                    "severity": sev,
                    "a": {"id": a.id, "level": a.level},
                    "b": {"id": b.id, "level": b.level},
                    "detail": desc,
                })
    return out


# ---------------------------------------------------------------------------
# Z3 层（可选依赖；全 must 约束联合可行性）
# ---------------------------------------------------------------------------


def _import_z3() -> Any:
    """返回 z3 模块；缺装抛 ImportError（render_constraints 单点先例）。"""
    import z3

    return z3


def _z3_joint_feasibility(reqs: list[Requirement]) -> dict[str, Any]:
    """全部 must 数值约束的联合可行性（一次求解；UNSAT 报整体不可行）。

    只编码**数值型** op（>=/<=/==）为线性 Real 断言（字符串等值/集合型
    不进 z3，规则层已覆盖其逐对语义）。返回
    {status: sat|unsat|unavailable|not_needed, reason?, quantities?}。
    """
    try:
        z3 = _import_z3()
    except ImportError as exc:
        return {"status": "unavailable", "reason": f"{exc}; {Z3_INSTALL_HINT}"}
    syms: dict[str, Any] = {}
    solver = z3.Solver()
    n_assert = 0
    for r in reqs:
        if not r.is_must:
            continue
        for qty, pairs in r.constraints.items():
            sym = syms.get(qty)
            if sym is None:
                sym = z3.Real(qty)
                syms[qty] = sym
            for op, v in pairs:
                if isinstance(v, str):
                    continue  # 字符串等值不进 z3
                fv = float(v)
                if op == ConstraintOp.GTE:
                    solver.add(sym >= fv)
                elif op == ConstraintOp.LTE:
                    solver.add(sym <= fv)
                elif op == ConstraintOp.EQ:
                    solver.add(sym == fv)
                n_assert += 1
    if n_assert == 0:
        return {"status": "not_needed", "reason": "无 must 数值约束"}
    res = solver.check()
    if res == z3.unsat:
        # UNSAT core 需要 assumption 标签才可回读；原型级如实报整体不可行 +
        # 参与量清单（core 细化留 followUp）。
        return {"status": "unsat",
                "reason": "must 约束联合不可行",
                "quantities": sorted(syms)}
    return {"status": "sat", "quantities": sorted(syms)}


# ---------------------------------------------------------------------------
# 可测性检查（需求↔判据映射）
# ---------------------------------------------------------------------------


def _testability_findings(reqs: list[Requirement]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in reqs:
        if r.criteria_ref.strip():
            continue
        if r.is_must:
            out.append({"id": r.id, "level": r.level, "severity": "error",
                        "detail": "must 需求无判据映射（criteria_ref 空）"})
        elif r.level == "should":
            out.append({"id": r.id, "level": r.level, "severity": "warn",
                        "detail": "should 需求无判据映射（验收口径未闭环）"})
        # want 不强制（探索性需求允许无判据，如实不判）
    return out


# ---------------------------------------------------------------------------
# 汇总入口
# ---------------------------------------------------------------------------


def requirements_review(reqset: RequirementSet, *,
                        use_z3: bool = True) -> dict[str, Any]:
    """需求集合 → 分层清单+冲突+可测性报告（JSON 进出）。

    use_z3=False 或 z3 缺装时 z3 层如实降级，规则层结果不受影响。
    """
    reqs = list(reqset.requirements)
    by_level = {lv: sum(1 for r in reqs if r.level == lv)
                for lv in ("must", "should", "want")}
    conflicts = _rule_conflicts(reqs)
    z3_res = (_z3_joint_feasibility(reqs) if use_z3
              else {"status": "disabled", "reason": "use_z3=False"})
    if z3_res.get("status") == "unsat":
        if conflicts:
            # 规则层已定位逐对矛盾：z3 UNSAT 作**独立复核一致**记（#118
            # 双通道互证语义），不重复计冲突条目。
            z3_res = dict(z3_res, corroboration="rule_conflicts_confirmed")
        else:
            # 逐对全可行但联合不可行（z3 独有检出，如未来 schema 扩展
            # 跨量线性组合时）：作为独立冲突条目入账。
            conflicts.append({
                "kind": "joint_infeasibility",
                "severity": "conflict",
                "quantity": None,
                "detail": z3_res.get("reason", ""),
                "quantities": z3_res.get("quantities", []),
            })
    untestable = _testability_findings(reqs)
    n_conflict = sum(1 for c in conflicts if c["severity"] == "conflict")
    verdict = ("blocked" if n_conflict else
               "attention" if conflicts or
               any(u["severity"] == "error" for u in untestable) else "clean")
    return {
        "ok": True,
        "schema": REQ_SCHEMA,
        "name": reqset.name,
        "n_requirements": len(reqs),
        "by_level": by_level,
        "conflicts": conflicts,
        "untestable": untestable,
        "z3": z3_res,
        "n_conflicts": n_conflict,
        "n_tensions": sum(1 for c in conflicts if c["severity"] == "tension"),
        "verdict": verdict,
    }



