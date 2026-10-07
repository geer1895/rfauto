"""goal 域（DS-3，宏图 v3.2 §十）：用户 Goal 工作模式第一方支持。

dsh packages/goal 四件组的模式移植（**采纳模式与不变量，不锁框架**）：
每会话一个**持久完成目标**（跨重启/续跑存续）+ **goal-round-driver 自动
续轮**（未达判据则推进一轮并给出下一轮动作建议）+ `/goal` 人工命令
（CLI 薄壳，零模型轮——判据评估与状态机全部确定性，铁律 7）。

与 campaign 的关系（升级线约束：**不重构 campaign 本体**）：goal 域以
**适配层**消费 campaign plan——``done_when`` 可引用 campaign verdict
（``{"kind": "campaign_verdict", "value": "COMPLETE"}``），证据由
``campaign_evidence`` 只读读取 campaign.plan.json 既有字段（verdict/
n_done/n_dead），**零新状态机、零回写**（campaign_executor 的
dag.state.json 权威账本语义原样不动，不双写）。

判据双形态（铁律 7：数值只由确定性内核产出，goal 域自身零数值面）：
- **声明式 spec**（可持久化，JSON 安全）：``done_when = {"kind": ...}``，
  词表见 ``CRITERIA_KINDS``——评估器只比较调用方供给的 evidence，绝不
  产生物理数字；
- **函数注入**（进程内）：``criteria_fn(goal, evidence) -> bool`` 由
  调用方/测试注入（不可持久化，存续面只落 spec）。

状态机三态（advance_goal 单一出口，确定性轮转）：
- ``done``      ：判据满足（幂等——已 done 再 advance 原样返回）；
- ``advancing`` ：判据未满足且存在下一步动作（注入 planner 给出或
  缺省"续推一轮"建议），rounds += 1；
- ``blocked``   ：判据未满足且无可执行下一步（planner 返回空 或
  ``max_rounds`` 轮次预算用尽）——如实堵住，不空转。

持久化形态：``runs/goals/<goal_id>.json``（schema=rfauto-goal-v1，原子
替换落盘）；目录根解析＝显式 ``root`` > 环境变量 ``RFAUTO_GOALS_DIR``
> cwd 相对 ``runs/goals``（仓内 runs 惯例；测试显式传 tmp 根隔离）。
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "CRITERIA_KINDS",
    "GOALS_DIR_ENV",
    "GOAL_SCHEMA",
    "GOAL_STATUSES",
    "campaign_evidence",
    "criteria_met",
    "evaluate_criteria",
    "get_goal",
    "goal_path",
    "goals_root",
    "list_goals",
    "set_goal",
    "update_goal",
]

#: 持久目标文件 schema 版本（形态变更升位；消费方按此分派读法）。
GOAL_SCHEMA = "rfauto-goal-v1"

#: goals 目录根的环境变量覆盖名（显式 root 参数优先于此）。
GOALS_DIR_ENV = "RFAUTO_GOALS_DIR"

#: goal 状态机词表（单一出口 advance_goal；词表外状态零入口）。
GOAL_STATUSES: tuple[str, ...] = ("advancing", "blocked", "done")

#: done_when 声明式判据词表（kind → 评估器；全部确定性、零数值面）。
CRITERIA_KINDS: dict[str, Callable[[dict[str, Any], dict[str, Any]], tuple[bool, str]]] = {}


def _register(kind: str):
    """判据词表注册器（模块级确定性评估器收集口）。"""

    def deco(fn):
        CRITERIA_KINDS[kind] = fn
        return fn

    return deco


# ─── 目录根与持久化（原子替换；跨进程存续）───────────────────────────────────

def goals_root(root: str | Path | None = None) -> Path:
    """goals 目录根解析：显式 > 环境变量 > cwd 相对 runs/goals。"""
    if root is not None:
        return Path(root)
    env = os.environ.get(GOALS_DIR_ENV, "").strip()
    if env:
        return Path(env)
    return Path("runs") / "goals"


def goal_path(goal_id: str, root: str | Path | None = None) -> Path:
    """goal_id → 持久化文件路径（goals_root/<goal_id>.json）。"""
    return goals_root(root) / f"{goal_id}.json"


def _atomic_write_json(path: Path, record: dict[str, Any]) -> None:
    """原子替换落盘（campaign_manager._atomic_write_text 同款，防 kill 截断）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True,
                   default=str),
        encoding="utf-8")
    os.replace(tmp, path)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_goal_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"goal_{ts}_{uuid.uuid4().hex[:8]}"


def _validate_goal_id(goal_id: str) -> str | None:
    """goal_id 白名单校验（防路径穿越/非法文件名字符）。"""
    gid = str(goal_id or "").strip()
    if not gid or len(gid) > 120:
        return None
    if any(ch in gid for ch in "\\/:*?\"<>|"):
        return None
    if gid in (".", "..") or gid.startswith("."):
        return None
    return gid


def _load_record(goal_id: str, root: str | Path | None) -> dict[str, Any] | None:
    path = goal_path(goal_id, root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _dump_record_error(path: Path) -> dict[str, Any]:
    return error_envelope([f"goal 文件形态非法（非 JSON 对象）: {path}"])


# ─── done_when 判据词表（声明式 spec；评估器确定性零数值面）──────────────────

@_register("flag_equal")
def _crit_flag_equal(spec: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, str]:
    """evidence[spec.key] == spec.value（通用确定性比较器；字符串/布尔语义）。"""
    key = str(spec.get("key") or "")
    if not key:
        return False, "flag_equal 判据缺 key 字段"
    expected = spec.get("value")
    actual = evidence.get(key)
    # 布尔语义显式类型守卫（1 == True 的跨型相等不算达标）
    met = isinstance(actual, bool) and actual == expected \
        if isinstance(expected, bool) else actual == expected
    return bool(met), f"evidence[{key}]={actual!r} vs 期望 {expected!r}"


@_register("rounds_at_least")
def _crit_rounds_at_least(spec: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, str]:
    """轮次计数达标（evidence.rounds 或 goal.rounds 之一在即可判）。"""
    target = spec.get("value")
    if not isinstance(target, int) or isinstance(target, bool) or target < 1:
        return False, "rounds_at_least 判据 value 必须为正整数"
    rounds = evidence.get("rounds")
    if not isinstance(rounds, int):
        return False, f"evidence.rounds 缺失（目标 ≥{target} 轮）"
    met = rounds >= target
    return met, f"rounds={rounds} vs 目标 ≥{target}"


@_register("campaign_verdict")
def _crit_campaign_verdict(spec: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, str]:
    """campaign verdict 达到期望值（适配层证据键=campaign_verdict）。

    这是 goal 域消费 campaign plan 的**唯一判据面**：campaign_manager 的
    verdict 词表（COMPLETE/PARTIAL/ABORTED/RUNNING/DRY_RUN）原样引用，
    零新状态机。
    """
    expected = str(spec.get("value") or "")
    if not expected:
        return False, "campaign_verdict 判据缺 value 字段"
    actual = evidence.get("campaign_verdict")
    met = str(actual or "") == expected
    return met, f"campaign_verdict={actual!r} vs 期望 {expected!r}"


def criteria_met(goal: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, str]:
    """按 goal.done_when 声明式 spec 评估判据（确定性；未知 kind 如实 False）。"""
    spec = goal.get("done_when")
    if not isinstance(spec, dict) or not str(spec.get("kind") or ""):
        return False, "done_when 缺声明式判据（kind 未声明）"
    kind = str(spec["kind"])
    evaluator = CRITERIA_KINDS.get(kind)
    if evaluator is None:
        return False, f"未知判据 kind: {kind}（词表 {sorted(CRITERIA_KINDS)}）"
    return evaluator(spec, evidence if isinstance(evidence, dict) else {})


def evaluate_criteria(
    goal: dict[str, Any],
    evidence: dict[str, Any],
    criteria_fn: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
) -> tuple[bool, str]:
    """判据统一入口：注入 criteria_fn 优先（进程内），否则走声明式 spec。

    criteria_fn 契约：``(goal, evidence) -> bool``（调用方/测试注入的
    确定性函数；不可持久化——存续面只落 spec，跨进程一律 spec 评估）。
    """
    if criteria_fn is not None:
        try:
            return bool(criteria_fn(goal, evidence)), "注入判据函数裁决"
        except Exception as exc:  # 判据函数异常=未达标（如实降级，不猜）
            return False, f"判据函数异常（按未达标处理）: {exc}"
    return criteria_met(goal, evidence)


# ─── campaign 适配层（只读消费 plan 既有字段；零回写零双账本）────────────────

def campaign_evidence(plan_path: str | Path) -> dict[str, Any]:
    """campaign.plan.json → 适配层证据 dict（verdict/n_done/n_dead 只读映射）。

    读不到/不可读时如实返回空 campaign 字段（evidence 落空 → 判据未达、
    不猜测）；绝不写回 plan（campaign_executor 账本语义原样不动）。
    """
    from rfauto.service.campaign_manager import load_plan

    loaded = load_plan(plan_path)
    if not loaded.get("ok"):
        return {"campaign_verdict": None, "campaign_plan_path": str(plan_path),
                "campaign_plan_readable": False}
    plan = loaded.get("plan") or {}
    return {
        "campaign_verdict": plan.get("verdict"),
        "n_done": plan.get("n_done"),
        "n_dead": plan.get("n_dead"),
        "campaign_plan_path": str(loaded.get("path") or plan_path),
        "campaign_plan_readable": True,
    }


def _default_evidence_fn(
        goal: dict[str, Any]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """缺省证据供给器：goal 声明 campaign_plan 时走适配层，否则空证据。"""

    def _provide(_goal: dict[str, Any]) -> dict[str, Any]:
        plan_path = goal.get("campaign_plan")
        if plan_path:
            return campaign_evidence(plan_path)
        return {}

    return _provide


# ─── 持久目标 CRUD（JSON 进出；信封构造器）───────────────────────────────────

def set_goal(
    objective: str,
    done_when: dict[str, Any] | None = None,
    *,
    campaign_plan: str | None = None,
    goal_id: str | None = None,
    max_rounds: int | None = None,
    note: str = "",
    root: str | Path | None = None,
) -> dict[str, Any]:
    """立持久目标（runs/goals/<goal_id>.json；幂等——同 goal_id 覆盖）。

    - ``objective``：人读目标陈述（必给，空串拒收）；
    - ``done_when``：声明式判据 spec（``{"kind": ..., ...}``，kind 必在
      ``CRITERIA_KINDS`` 词表）；None 允许先立目标后补判据（此形态
      advance 恒 blocked——如实"无判据不判达"）；
    - ``campaign_plan``：可选，goal.done_when 引用 campaign verdict 的
      适配层指针（plan 文件或其所在目录，load_plan 双形态兼容）；
    - ``max_rounds``：可选轮次预算（advance 用尽即 blocked）。
    """
    text = str(objective or "").strip()
    if not text:
        return error_envelope(["objective 必给（空串拒收）"])
    # 显式 goal_id（含空串/空白）一律走白名单校验，不再回退自动生成
    gid = _new_goal_id() if goal_id is None else _validate_goal_id(goal_id)
    if gid is None:
        return error_envelope(
            [f"goal_id 非法（禁路径分隔符/点前缀，长度≤120）: {goal_id!r}"])
    if done_when is not None:
        if not isinstance(done_when, dict):
            return error_envelope(["done_when 必须是 JSON 对象判据 spec"])
        kind = str(done_when.get("kind") or "")
        if kind not in CRITERIA_KINDS:
            return error_envelope(
                [f"done_when.kind 未知: {kind or '（缺）'}（词表 "
                 f"{sorted(CRITERIA_KINDS)}）"])
    if max_rounds is not None and (not isinstance(max_rounds, int)
                                   or isinstance(max_rounds, bool)
                                   or max_rounds < 1):
        return error_envelope(["max_rounds 必须为正整数（None=不限）"])
    now = _now_iso()
    record: dict[str, Any] = {
        "schema": GOAL_SCHEMA,
        "goal_id": gid,
        "objective": text,
        "done_when": dict(done_when) if done_when else None,
        "campaign_plan": str(campaign_plan) if campaign_plan else None,
        "max_rounds": int(max_rounds) if max_rounds else None,
        "status": "advancing",
        "rounds": 0,
        "note": str(note or ""),
        "created_at": now,
        "updated_at": now,
        "history": [],
    }
    path = goal_path(gid, root)
    _atomic_write_json(path, record)
    return ok_envelope(goal_id=gid, path=str(path), status=record["status"],
                       goal=record)


def get_goal(goal_id: str, root: str | Path | None = None) -> dict[str, Any]:
    """读持久目标（跨进程存续查询口；不存在/损坏如实 ok=False）。"""
    gid = _validate_goal_id(goal_id)
    if gid is None:
        return error_envelope([f"goal_id 非法: {goal_id!r}"])
    path = goal_path(gid, root)
    if not path.is_file():
        return error_envelope([f"goal 不存在: {path}（先 goal set 落盘）"])
    data = _load_record(gid, root)
    if data is None:
        return _dump_record_error(path)
    if data.get("schema") != GOAL_SCHEMA or not isinstance(
            data.get("goal_id"), str):
        return error_envelope(
            [f"goal 文件 schema 不符: {path}（期望 {GOAL_SCHEMA}）"])
    return ok_envelope(goal_id=gid, path=str(path), goal=data)


def update_goal(goal: dict[str, Any], root: str | Path | None = None) -> dict[str, Any]:
    """回写 goal 记录（driver 内部落账出口；updated_at 刷新+原子替换）。"""
    gid = _validate_goal_id(str(goal.get("goal_id") or ""))
    if gid is None:
        return error_envelope(["goal 记录缺合法 goal_id，拒收回写"])
    record = dict(goal)
    record["schema"] = GOAL_SCHEMA
    record["goal_id"] = gid
    status = str(record.get("status") or "")
    if status not in GOAL_STATUSES:
        return error_envelope(
            [f"status 非法: {status!r}（词表 {list(GOAL_STATUSES)}）"])
    record["updated_at"] = _now_iso()
    path = goal_path(gid, root)
    _atomic_write_json(path, record)
    return ok_envelope(goal_id=gid, path=str(path), goal=record)


def list_goals(root: str | Path | None = None) -> dict[str, Any]:
    """清点 goals 目录（只读；损坏文件逐条如实注记不静默丢弃）。"""
    base = goals_root(root)
    if not base.is_dir():
        return ok_envelope(root=str(base), n_goals=0, goals=[],
                           unreadable=[])
    goals: list[dict[str, Any]] = []
    unreadable: list[str] = []
    for path in sorted(base.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unreadable.append(path.name)
            continue
        if isinstance(data, dict) and data.get("schema") == GOAL_SCHEMA:
            goals.append({
                "goal_id": str(data.get("goal_id") or path.stem),
                "objective": str(data.get("objective") or ""),
                "status": str(data.get("status") or ""),
                "rounds": data.get("rounds"),
                "updated_at": str(data.get("updated_at") or ""),
            })
        else:
            unreadable.append(path.name)
    return ok_envelope(root=str(base), n_goals=len(goals), goals=goals,
                       unreadable=unreadable)


# ─── goal-round-driver（自动续轮：读→判→推→状态机；dry 轮转零执行）──────────

def advance_goal(
    goal_id: str,
    *,
    root: str | Path | None = None,
    criteria_fn: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
    evidence_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    action_planner: Callable[[dict[str, Any], str], dict[str, Any] | None]
    | None = None,
) -> dict[str, Any]:
    """推进一轮（goal-round-driver 单一出口；确定性状态机，零模型轮）。

    轮转语义（dry——只动状态与建议，不执行任何求解/编排动作）：
    1. 读 goal（不存在如实失败）；
    2. 已 ``done`` → 幂等原样返回（advanced=False）；
    3. 证据 = ``evidence_fn(goal)``（缺省：声明了 campaign_plan 走适配层
       ``campaign_evidence``；否则空证据）；
    4. 判据 = 注入 ``criteria_fn`` 优先（异常=不可判），否则声明式 spec；
       **spec 亦未声明 → 不可判**（无判据不判达，blocked 不空转）；
    5. 达标 → ``status=done``（rounds 不增，历史落 done 条目）；
    6. 未达标 → ``rounds += 1``；下一步动作 = ``action_planner(goal,
       reason)``（注入）或缺省"续推一轮"建议；**blocked 三路**：判据面
       不可判 / planner 显式给空动作 / 轮次预算（max_rounds）用尽——
       如实堵住，不空转；否则 ``status=advancing``；
    7. 回写持久文件并返回信封（新 status/rounds/suggestion/history 尾条）。
    """
    loaded = get_goal(goal_id, root)
    if not loaded.get("ok"):
        return loaded
    goal = loaded["goal"]
    if str(goal.get("status")) == "done":
        return ok_envelope(goal_id=goal["goal_id"], status="done",
                           advanced=False, rounds=goal.get("rounds"),
                           suggestion=None, criteria_met=True,
                           reason="已达标（幂等返回）", goal=goal)
    provider = evidence_fn if evidence_fn is not None \
        else _default_evidence_fn(goal)
    try:
        evidence = provider(goal) or {}
    except Exception as exc:  # 证据供给失败=无证据可判（如实降级不猜）
        evidence = {"evidence_error": str(exc)}
    if not isinstance(evidence, dict):
        evidence = {"evidence_error": f"evidence_fn 返回非 dict: {type(evidence)}"}
    # 判据面解析：注入 fn 优先（异常=不可判）→ 声明式 spec → 均无=不可判
    undeterminable = False
    if criteria_fn is not None:
        try:
            met = bool(criteria_fn(goal, evidence))
            reason = "注入判据函数裁决：达标" if met else "注入判据函数裁决：未达标"
        except Exception as exc:  # 判据函数异常=不可判（如实堵住不猜）
            met, reason, undeterminable = False, f"判据函数异常: {exc}", True
    elif isinstance(goal.get("done_when"), dict):
        met, reason = criteria_met(goal, evidence)
    else:
        met = False
        reason = "done_when 未声明判据（无判据不判达）"
        undeterminable = True
    history = list(goal.get("history") or [])
    rounds = int(goal.get("rounds") or 0)
    if met:
        goal["status"] = "done"
        goal["last_reason"] = reason
        history.append({"round": rounds, "result": "done", "reason": reason,
                        "at": _now_iso()})
        goal["history"] = history
        saved = update_goal(goal, root)
        if not saved.get("ok"):
            return saved
        return ok_envelope(goal_id=goal["goal_id"], status="done",
                           advanced=True, rounds=rounds, suggestion=None,
                           criteria_met=True, reason=reason,
                           goal=saved.get("goal") or goal)
    rounds += 1
    suggestion: dict[str, Any] | None = None
    planner_declined = False
    if action_planner is not None:
        try:
            suggestion = action_planner(goal, reason)
        except Exception as exc:  # planner 异常=无建议（如实降级）
            suggestion = None
            planner_declined = True
            reason = f"{reason}（planner 异常: {exc}）"
        else:
            if suggestion is not None and not isinstance(suggestion, dict):
                suggestion = None
                planner_declined = True
                reason = f"{reason}（planner 返回非 dict，按无建议处理）"
            elif suggestion is None:
                planner_declined = True
    max_rounds = goal.get("max_rounds")
    budget_exhausted = (isinstance(max_rounds, int)
                        and not isinstance(max_rounds, bool)
                        and rounds >= max_rounds)
    # blocked 三路：判据面不可判 / planner 显式给空动作 / 轮次预算用尽
    if budget_exhausted:
        goal["status"] = "blocked"
        reason = f"轮次预算用尽（{rounds}/{max_rounds}），判据未达"
        suggestion = {"action": "blocked", "round": rounds, "reason": reason}
    elif planner_declined or (undeterminable and suggestion is None):
        goal["status"] = "blocked"
        suggestion = {"action": "blocked", "round": rounds, "reason": reason}
    elif suggestion is None:
        # 缺省建议=自动续推一轮（dsh goal-round-driver 缺省语义）
        suggestion = {"action": "advance_round", "round": rounds,
                      "reason": reason}
        goal["status"] = "advancing"
    elif str(suggestion.get("action") or "") in ("", "blocked"):
        goal["status"] = "blocked"
        suggestion.setdefault("round", rounds)
        suggestion.setdefault("reason", reason)
        suggestion["action"] = "blocked"
    else:
        goal["status"] = "advancing"
    goal["rounds"] = rounds
    goal["last_reason"] = reason
    goal["suggestion"] = suggestion
    history.append({"round": rounds, "result": str(goal["status"]),
                    "reason": reason, "at": _now_iso()})
    goal["history"] = history
    saved = update_goal(goal, root)
    if not saved.get("ok"):
        return saved
    return ok_envelope(goal_id=goal["goal_id"], status=str(goal["status"]),
                       advanced=True, rounds=rounds, suggestion=suggestion,
                       criteria_met=False, reason=reason,
                       goal=saved.get("goal") or goal)
