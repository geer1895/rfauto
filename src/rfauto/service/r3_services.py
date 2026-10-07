"""Direction 6 R3 extension services (6g-6j).

Separated from api.py to avoid write-tool truncation (#108/#112).
Imported by api.py via: from rfauto.service.r3_services import *

6g: Solver visualization protocol
6h: Solver management (registry list + add/remove)
6i: Approval inbox (Gate pending items)
6j: LLM conversation (direct service layer)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from rfauto.infra.db import RegistryDB  # R2-D-02：审批流生产读写接 RegistryDB.approvals
from rfauto.service.envelope import error_envelope, ok_envelope

# ─── 6g: Solver Visualization Protocol ────────────────────────────────────────

def list_solver_visualizations(solver_name: str | None = None) -> dict[str, Any]:
    """List available visualizations from registered solvers.

    6g: Each adapter declares visualizations() -> [{kind, spec}].
    UI renders by kind; unknown kinds degrade to file download.
    """
    from rfauto.adapters import (  # noqa: F401 - 注册副作用
        comsol_adapter,
        elmer_adapter,
        openems_solver,
        palace_solver,
    )
    from rfauto.adapters.em_solver_base import get_global_registry
    registry = get_global_registry()

    results = []
    for stype, solver_cls in registry._solvers.items():
        if solver_name and stype.value if hasattr(stype, "value") else str(stype) != solver_name:
            continue
        # Instantiate with minimal config to query visualizations
        try:
            from rfauto.adapters.em_solver_base import EMSolverConfig
            config = EMSolverConfig(solver_type=stype)
            instance = solver_cls(config)
            viz = instance.visualizations()
            results.append({
                "solver": stype.value if hasattr(stype, "value") else str(stype),
                "visualizations": viz,
                "output_formats": instance.supported_output_formats(),
            })
        except Exception as e:
            results.append({
                "solver": stype.value if hasattr(stype, "value") else str(stype),
                "error": str(e),
                "visualizations": [],
            })

    return ok_envelope(solvers=results)


# ─── 6h: Solver Management ────────────────────────────────────────────────────

def list_registered_solvers() -> dict[str, Any]:
    """List all registered solvers with their status.

    6h: UI reads EMSolverRegistry + shows availability.
    """
    from rfauto.adapters import (  # noqa: F401 - 注册副作用
        comsol_adapter,
        elmer_adapter,
        openems_solver,
        palace_solver,
    )
    from rfauto.adapters.em_solver_base import EMSolverConfig, get_global_registry
    registry = get_global_registry()

    solvers = []
    for stype, solver_cls in registry._solvers.items():
        try:
            config = EMSolverConfig(solver_type=stype)
            instance = solver_cls(config)
            available = instance.is_available()
            viz = instance.visualizations()
        except Exception:
            available = False
            viz = []
        # gpl 子包（pypo/scuff）注册键为 str 字面（ge8c 席5 gpl 隔离设计），
        # 枚举键取 .value、str 键取自身——双形态防御（#105；终门八百一十九
        # 实证：全模块 import 冒烟后 str 键致 AttributeError 污染下游）。
        type_label = stype.value if hasattr(stype, "value") else str(stype)
        solvers.append({
            "type": type_label,
            "class": solver_cls.__name__,
            "available": available,
            "n_visualizations": len(viz),
        })

    return ok_envelope(solvers=solvers, total=len(solvers))


def add_solver_to_config(
    name: str,
    solver_type: str,
    exe_path: str | None = None,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a solver entry to configs/solvers.yaml.

    6h: UI wizard writes solver config; human can add CST/COMSOL etc.

    写入 schema 与 em_solver_base.load_solvers_config 的读取约定一致：
    `solvers:` 包裹 + 每条目 `solver_type` 字段（审查缺口 #7 修复——
    曾写顶层 {name: {type}}，运行时永远读不到）。
    """
    import yaml

    config_path = Path("configs") / "solvers.yaml"
    if not config_path.parent.exists():
        config_path.parent.mkdir(parents=True)

    data: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    # 注意：不能用 setdefault("solvers", {}) or {}——空 dict 为 falsy 时 or 会
    # 返回脱离 data 的新字典，后续写入全部丢失（本次修复的实测陷阱）
    solvers = data.get("solvers")
    if not isinstance(solvers, dict):
        solvers = {}
        data["solvers"] = solvers

    if name in solvers:
        return error_envelope([f"Solver '{name}' already exists"])

    entry: dict[str, Any] = {"solver_type": solver_type}
    if exe_path:
        entry["exe_path"] = exe_path
    if extra_params:
        entry.update(extra_params)
    solvers[name] = entry

    config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # 回读校验：确保写入的条目能被 load_solvers_config 读到（链路级验证）
    from rfauto.adapters.em_solver_base import load_solvers_config
    loaded = load_solvers_config(config_path)
    readable = name in loaded
    return ok_envelope(
        name=name,
        config_path=str(config_path),
        entry=entry,
        loadable=readable,
        errors=[] if readable else ["entry written but not loadable by load_solvers_config"],
    )


def remove_solver_from_config(name: str) -> dict[str, Any]:
    """Remove a solver entry from configs/solvers.yaml."""
    import yaml

    config_path = Path("configs") / "solvers.yaml"
    if not config_path.exists():
        return error_envelope(["configs/solvers.yaml not found"])

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    solvers = data.get("solvers") or {}

    if name not in solvers:
        return error_envelope([f"Solver '{name}' not found in config"])

    removed = solvers.pop(name)
    config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ok_envelope(name=name, removed=removed)


def spice_tool_status(path: str | Path | None = None) -> dict[str, Any]:
    """ngspice/Xyce 电路级参考通道探测（6h 管理页数据源，0ca followUp④）。

    读 configs/solvers.yaml 的 ``ngspice``/``xyce`` 节（管理页探测记录，
    非 EM 求解器——无 EMSolverAdapter，不进 EMSolverRegistry）并逐项调用
    adapters.spice_netlist 的探测钩子（resolve_*/available）。两项独立
    best-effort（观测性 #105）：单工具探测失败只入该工具的 error 字段，
    不阻塞另一项，也不影响 EM 求解器管理面。
    """
    from rfauto.adapters import spice_netlist as sn
    from rfauto.adapters.em_solver_base import load_solvers_config

    configs = load_solvers_config(path)
    tools: dict[str, Any] = {}
    probes = {
        "ngspice": (sn.resolve_ngspice_exe, sn.ngspice_available,
                    "RFAUTO_NGSPICE_BIN > tools/ngspice/Spice64/bin > PATH"),
        "xyce": (sn.resolve_xyce_exe, sn.xyce_available,
                 "RFAUTO_XYCE_BIN > PATH"),
    }
    for name, (resolve_fn, available_fn, chain) in probes.items():
        entry = configs.get(name)
        tool: dict[str, Any] = {
            "configured": entry is not None,
            "available": False,
            "exe": None,
            "resolve_chain": chain,
            "error": None,
        }
        try:
            tool["available"] = bool(available_fn())
            if tool["available"]:
                tool["exe"] = str(resolve_fn())
        except Exception as exc:  # 探测只报告不抛（#105）
            tool["error"] = str(exc)
        tools[name] = tool
    return ok_envelope(
        tools=tools,
        note="电路级 SPICE 通道（探测记录）；EM 求解器管理面见 "
                "list_registered_solvers（EMSolverRegistry）",
    )


# ─── 6i: Approval Inbox ───────────────────────────────────────────────────────

def _audit_path() -> Path:
    """审批审计日志（相对工作区解析，随 cwd 变化——测试用 tmp_path 隔离）。"""
    return Path("runs") / "agent_proposals" / "audit.jsonl"


# ─── R2-D-02：审批流生产路径接 RegistryDB.approvals ──────────────────────────
#
# 口径：runs/agent_proposals/audit.jsonl 仍是**产物事实源**（append-only，提案
# 文件原样保留）；RegistryDB.approvals 是它的物化读模型——DB 存状态/审计行，
# payload = 完整审计事件 + ``audit_file`` 外键指向审计文件。收件箱读路径
# （list_pending_approvals）与批准查原提案（approve_proposal）都走 DB；
# 历史记录走"首读回填"（幂等 upsert）而非一次性迁移函数——主键是确定性哈希
# （token_hash/change_id），audit.jsonl 随工作区走且可能被外部补写/改写
# （篡改检测用例即重写该文件），一次性迁移既要多一个入口又会漏掉迁移后的
# 写入，读路径回填自愈，代价只是把本来就要读的文件多消费一遍。DB 故障时
# 回落文件口径（#105：观测/索引面绝不阻塞审批主路径）。

#: 审计事件 → approvals.status 映射；ok=False 的事件不改状态（与文件口径一致：
#: 审批失败/重提被拒的提案仍在收件箱，批准/拒绝才是终态）
_STATUS_BY_EVENT = {
    "propose": "pending",
    "approve": "applied",
    "apply": "applied",
    "reject": "rejected",
}


def _approval_id(entry: dict[str, Any]) -> str:
    """审批行主键：B-32 变更类用 change_id，配方提案用 token_hash（确定性哈希）。"""
    return str(entry.get("change_id") or entry.get("token_hash") or "")


def _approval_kind(entry: dict[str, Any]) -> str:
    """审批类别：审计事件缺 kind（配方提案）视为 recipe（收件箱 kind 过滤同口径）。"""
    return str(entry.get("kind") or "recipe")


def _open_approval_db() -> RegistryDB:
    """打开审批读模型库（路径链：显式 > env RFAUTO_REGISTRY_DB > settings db.path
    > runs/registry.sqlite，由 default_registry_db_path 统一解析）。"""
    return RegistryDB()


def _approval_payload(entry: dict[str, Any], audit_path: Path) -> dict[str, Any]:
    """审计事件 → approvals.payload：原事件 + audit_file 外键（产物存储不动）。"""
    payload = dict(entry)
    payload["audit_file"] = str(audit_path)
    return payload


def _sync_approvals_to_db(audit_path: Path | None = None) -> bool:
    """首读回填：audit.jsonl 既有事件幂等 upsert 进 approvals 表。

    只落 ok=True 的事件；已有行只允许终态事件推进状态（pending 不降级终态）；
    仍处 pending 的行载荷随文件刷新（文件是事实源：外部补写/改写审计后，
    下次读收件箱/批准时 DB 视图随之——篡改检测语义与纯文件口径一致）。
    返回 True 表示 DB 可用（无论是否写入），False = DB 故障，调用方回落
    文件口径。
    """
    audit = audit_path or _audit_path()
    entries = _read_audit_entries(audit)
    if not entries:
        return True
    db = _open_approval_db()
    try:
        rows = {row["id"]: row for row in db.list_approvals(limit=1_000_000)}
        for entry in entries:
            aid = _approval_id(entry)
            status = _STATUS_BY_EVENT.get(str(entry.get("event") or ""))
            if not aid or status is None or not entry.get("ok"):
                continue
            row = rows.get(aid)
            if row is None:
                db.insert_approval(_approval_kind(entry),
                                   _approval_payload(entry, audit),
                                   approval_id=aid, status=status)
                rows[aid] = {"id": aid, "status": status}
            elif status != "pending":
                if row["status"] != status:
                    db.update_approval_status(aid, status)
                    row["status"] = status
            elif row["status"] == "pending":
                db.update_approval_payload(aid, _approval_payload(entry, audit),
                                           _approval_kind(entry))
        return True
    except Exception:
        return False  # #105：回填失败不阻塞审批主路径（audit.jsonl 仍是事实源）
    finally:
        db.close()


def _record_approval_event_in_db(event: dict[str, Any]) -> None:
    """把刚写入审计的单条事件即时推进 approvals 读模型（best-effort）。

    与 _sync_approvals_to_db 同一套状态映射，让"批准/拒绝后 DB 状态变更"
    在同一调用内可见；行缺失时按本事件建档（主键确定性哈希），已存在行只
    允许终态事件推进状态。任何 DB 故障静默吞掉（#105）。
    """
    aid = _approval_id(event)
    status = _STATUS_BY_EVENT.get(str(event.get("event") or ""))
    if not aid or status is None or not event.get("ok"):
        return
    try:
        db = _open_approval_db()
        try:
            if db.get_approval(aid) is None:
                db.insert_approval(_approval_kind(event),
                                   _approval_payload(event, _audit_path()),
                                   approval_id=aid, status=status)
            elif status != "pending":
                db.update_approval_status(aid, status)
        finally:
            db.close()
    except Exception:
        return


def _pending_from_db(kind: str | None) -> list[dict[str, Any]]:
    """收件箱 DB 口径：pending 行还原审计事件形状（去 audit_file 内部键），
    按创建时序（旧→新）返回，与文件口径的切片/反转约定对接。"""
    db = _open_approval_db()
    try:
        rows = db.list_approvals(status="pending", limit=1_000_000)
    finally:
        db.close()
    out: list[dict[str, Any]] = []
    for row in reversed(rows):  # list_approvals 新→旧；还原成文件时序
        payload = dict(row.get("payload") or {})
        payload.pop("audit_file", None)
        if kind is not None and _approval_kind(payload) != kind:
            continue
        out.append(payload)
    return out


def _pending_from_audit(audit_path: Path, kind: str | None) -> list[dict[str, Any]]:
    """收件箱文件口径（DB 故障兜底，#105）：原 audit.jsonl 推导逻辑原样保留。"""
    all_entries = _read_audit_entries(audit_path)
    # First pass: collect all apply events' token hashes
    applied_tokens = {e.get("token_hash", "") for e in all_entries
                      if e.get("event") == "apply" and e.get("ok")}
    # B-32：被拒绝的提案同样离开收件箱（拒绝为终态）
    rejected_tokens = {e.get("token_hash", "") for e in all_entries
                       if e.get("event") == "reject" and e.get("ok")}

    # Second pass: find proposes without matching applies/rejects
    entries = []
    for entry in all_entries:
        if entry.get("event") != "propose" or not entry.get("ok"):
            continue
        token_hash = entry.get("token_hash", "")
        if not token_hash or token_hash in applied_tokens or token_hash in rejected_tokens:
            continue
        # B-32：新变更类（solver_registration / resource_capacity）与配方提案
        # 共存于同一收件箱；kind 过滤可只看某一类（缺省 kind 视为 recipe）
        if kind is not None and str(entry.get("kind") or "recipe") != kind:
            continue
        entries.append(entry)
    return entries


def _find_proposal_in_db(token_hash_str: str) -> dict[str, Any] | None:
    """按 token_hash/change_id 前缀在 approvals 表找原提案（文件口径：保留
    最新一条匹配；只认 ok 的 propose 事件载荷）。"""
    needle = str(token_hash_str or "")
    if not needle:
        return None
    db = _open_approval_db()
    try:
        rows = db.list_approvals(limit=1_000_000)
    finally:
        db.close()
    original: dict[str, Any] | None = None
    for row in rows:
        payload = dict(row.get("payload") or {})
        if payload.get("event") != "propose" or not payload.get("ok"):
            continue
        th = str(payload.get("token_hash", ""))
        cid = str(payload.get("change_id", ""))
        # 配方提案按 token_hash 前缀匹配；B-32 新变更类按 change_id 前缀匹配
        if ((th and th.startswith(needle[:8]))
                or (cid and cid.startswith(needle[:16]))):
            original = payload
    return original


def _find_proposal_in_audit(audit_path: Path,
                            token_hash_str: str) -> dict[str, Any] | None:
    """文件口径的原提案查找（DB 故障兜底，#105）；逻辑与原实现逐字保留。"""
    original = None
    for entry in _read_audit_entries(audit_path):
        if entry.get("event") != "propose" or not entry.get("ok"):
            continue
        th = str(entry.get("token_hash", ""))
        cid = str(entry.get("change_id", ""))
        # 配方提案按 token_hash 前缀匹配；B-32 新变更类按 change_id 前缀匹配
        matched = ((th and th.startswith(token_hash_str[:8]))
                   or (cid and cid.startswith(token_hash_str[:16])))
        if matched:
            original = entry
    return original


def list_pending_approvals(limit: int = 20, kind: str | None = None) -> dict[str, Any]:
    """List pending approval items (R2-D-02：RegistryDB.approvals 读模型).

    6i: Gate pending items (propose without matching apply) shown in UI.

    读路径：先首读回填 audit.jsonl → approvals 表（幂等），再查 DB pending 行；
    DB 打开/回填/查询失败回落文件口径（#105）。返回形状与文件口径逐键一致。
    """
    audit_path = _audit_path()
    if not audit_path.exists():
        return ok_envelope(pending=[], total=0)

    entries: list[dict[str, Any]] | None = None
    if _sync_approvals_to_db(audit_path):
        try:
            entries = _pending_from_db(kind)
        except Exception:
            entries = None
    if entries is None:
        entries = _pending_from_audit(audit_path, kind)

    entries = entries[-limit:]
    entries.reverse()
    return ok_envelope(pending=entries, total=len(entries))


def approve_proposal(token_hash_str: str, recipe_path: str | None = None,
                     adapter: str = "fake") -> dict[str, Any]:
    """Approve a pending proposal (execute apply).

    6i: Click approve in UI = execute agent_apply with the stored params.

    L3 token 是 (L1, L2, params) 的确定性哈希——审计只存 token_hash（ADR-0025，
    原始 token 不可回取），因此批准路径是"用审计中的参数重新 propose 拿新 token，
    校验哈希与 propose 时一致后再 apply"（审查缺口 #6 修复——曾直接读
    original["token"]，恒为空串，apply 必被 L3 拒绝）。哈希一致同时证明
    存档参数与配方/Gate 状态未漂移。

    R2-D-02：原提案查找走 RegistryDB.approvals（首读回填后按前缀匹配），
    DB 故障回落 audit.jsonl 文件口径（#105）；批准成功后即时推进 DB 状态
    （applied），收件箱与 db_status 盘点同一调用内可见。
    """
    from rfauto.service.agent_safety import append_audit_log
    from rfauto.service.agent_safety import token_hash as compute_token_hash

    audit_path = Path("runs") / "agent_proposals" / "audit.jsonl"
    if not audit_path.exists():
        return error_envelope(["No audit log found"])

    original = None
    if _sync_approvals_to_db(audit_path):
        original = _find_proposal_in_db(token_hash_str)
    if not original:
        original = _find_proposal_in_audit(audit_path, token_hash_str)
    if not original:
        return error_envelope([f"No matching proposal found for token {token_hash_str[:8]}..."])

    # B-32：新变更类（A6 求解器注册 / G13 资源容量）走分派——同一审批入口，
    # 但落配置而不是重跑配方 Gate/apply
    if str(original.get("kind", "")).strip():
        return _approve_change(original.get("change_id") or original.get("token_hash"))

    params = original.get("params", {})
    from rfauto.service.api import agent_apply, agent_propose

    reproposal = agent_propose(recipe_path, params, adapter_name=adapter)
    if not reproposal.get("ok"):
        append_audit_log({
            "event": "approve", "ok": False, "stage": "re_propose",
            "token_hash": token_hash_str, "recipe": recipe_path,
            "reason": "re-propose rejected by gate",
        })
        return error_envelope(
            ["re-propose rejected by gate",
                           *(reproposal.get("errors") or [])],
        )

    if compute_token_hash(reproposal["token"]) != original.get("token_hash"):
        append_audit_log({
            "event": "approve", "ok": False, "stage": "token_mismatch",
            "token_hash": token_hash_str, "recipe": recipe_path,
            "reason": "re-propose token hash differs from original; recipe or gate state drifted",
        })
        return error_envelope(
            ["重 propose 的 token 哈希与 propose 时不一致："
                           "配方或 Gate 状态已变化，请重新走 propose 流程"],
        )

    result = agent_apply(recipe_path, reproposal["token"], params, adapter_name=adapter)

    approve_event = {
        "event": "approve",
        "ok": result.get("ok", False),
        "token_hash": token_hash_str,
        "recipe": recipe_path,
        "run_id": result.get("run_id"),
    }
    append_audit_log(approve_event)
    # R2-D-02：批准终态即时推进 approvals 读模型（ok=False 不改状态，
    # 提案留在收件箱——与文件口径一致）
    _record_approval_event_in_db(approve_event)

    return result


# ─── B-32: 审批流接入 A6 新求解器上线与 G13 资源容量变更 ───────────────────────
#
# 背景（方案 §10.23 补强第三批 B-32）：6i 收件箱此前只覆盖配方参数提案
# （agent_propose → approve_proposal → agent_apply）。A6 新求解器上线
# （COMSOL 等接入 configs/solvers.yaml）与 G13 资源容量变更（license 席位/
# FDTD 并发，喂 service/resource_scheduler.SchedulerConfig）此前是直接写配置
# 的旁路——无审批、不可审计。本段把二者并入同一条审批链（同一 audit.jsonl、
# 同一收件箱）：
#   * _propose_* 只写 audit propose 事件，**不碰任何配置文件**（未批准不生效）；
#   * 批准统一走已 re-export 的 approve_proposal（按事件 kind 分派落配置）；
#   * 拒绝写 reject 审计 → 收件箱移除、配置不动、拒绝为终态；
#   * 重复提交/重复批准/重复拒绝 → 幂等（duplicate=True），不产生第二次副作用。
#
# 命名以 "_" 开头是刻意的：tests/unit/test_api_reexport.py（B-34）要求
# r3_services 的**公开**函数全部在 api.py re-export，而本项文件面禁改
# api.py，故新增 API 一律私有，对外审批入口复用 approve_proposal。

_CHANGE_KINDS = ("solver_registration", "resource_capacity")
_RESOURCE_SCOPES = ("solver", "class")
_RESOURCE_CAPACITY_PATH = Path("configs") / "resource_capacity.yaml"


def _read_audit_entries(audit_path: Path | None = None) -> list[dict[str, Any]]:
    """容错读 JSONL 审计：坏行跳过，不做业务主路径故障点（#105）。"""
    audit = audit_path or _audit_path()
    if not audit.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in audit.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _change_id(kind: str, payload: dict[str, Any]) -> str:
    """变更标识 = (kind, payload) 的确定性哈希——同提案重复提交得同一 id。"""
    import hashlib

    blob = json.dumps({"kind": kind, "payload": payload},
                      sort_keys=True, ensure_ascii=False, default=str)
    return "chg_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _change_entries(entries: list[dict[str, Any]], *, kind: str | None = None) -> list[dict[str, Any]]:
    """待批的新变更类提案（不含已 apply / 已 reject；配方提案不在此列）。"""
    decided = {e.get("token_hash") for e in entries
               if e.get("event") in ("apply", "reject") and e.get("ok")}
    out = []
    for e in entries:
        if e.get("event") != "propose" or not e.get("ok"):
            continue
        if e.get("kind") not in _CHANGE_KINDS:
            continue
        if kind is not None and e.get("kind") != kind:
            continue
        if e.get("token_hash") in decided:
            continue
        out.append(e)
    return out


def _find_change(entries: list[dict[str, Any]], change_id_str: str) -> dict[str, Any] | None:
    """按 change_id（完整或前缀）定位新变更类提案；前缀不唯一时取最后一次提交。"""
    needle = str(change_id_str or "").strip()
    if not needle:
        return None
    candidates = [e for e in entries
                  if e.get("event") == "propose" and e.get("ok")
                  and e.get("kind") in _CHANGE_KINDS]
    exact = [e for e in candidates if str(e.get("change_id", "")) == needle]
    if exact:
        return exact[-1]
    prefixed = [e for e in candidates
                if str(e.get("change_id", "")).startswith(needle)]
    return prefixed[-1] if prefixed else None


def _change_decided(entries: list[dict[str, Any]], change_id_str: str, event: str) -> bool:
    return any(e.get("event") == event and e.get("ok")
               and e.get("change_id") == change_id_str for e in entries)


def _current_solver_names() -> set[str]:
    """已注册求解器名（读 configs/solvers.yaml 的写入 schema）。"""
    import yaml

    cfg = Path("configs") / "solvers.yaml"
    if not cfg.exists():
        return set()
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:  # 配置坏文件不阻塞提案（#105）
        return set()
    solvers = data.get("solvers")
    return set(solvers) if isinstance(solvers, dict) else set()


def _append_change_event(event: dict[str, Any]) -> None:
    from rfauto.service.agent_safety import append_audit_log

    append_audit_log(event)


def _load_resource_capacity_config() -> dict[str, Any]:
    """G13 资源容量配置的已批准内容（仅在批准时落盘；未批准返回空表）。"""
    import yaml

    out: dict[str, Any] = {"solver_capacity": {}, "class_capacity": {}}
    if not _RESOURCE_CAPACITY_PATH.exists():
        return out
    try:
        data = yaml.safe_load(_RESOURCE_CAPACITY_PATH.read_text(encoding="utf-8")) or {}
    except Exception:  # 坏配置按未配置处理（#105）
        return out
    for key in ("solver_capacity", "class_capacity"):
        bucket = data.get(key)
        if isinstance(bucket, dict):
            out[key] = {str(k): int(v) for k, v in bucket.items()}
    return out


def _propose_solver_registration(
    name: str,
    solver_type: str,
    exe_path: str | None = None,
    extra_params: dict[str, Any] | None = None,
    requested_by: str = "user",
) -> dict[str, Any]:
    """A6 新求解器上线提案（写入收件箱，不落 configs/solvers.yaml）。

    重复提交：同一 (name, type, exe_path, extra_params) 已有待批提案 →
    幂等返回同一 change_id（duplicate=True）；同名但内容不同的待批提案 →
    显式报错，要求先处理旧提案；名字已注册 → 报错。
    """
    clean_name = str(name or "").strip()
    clean_type = str(solver_type or "").strip()
    if not clean_name:
        return error_envelope(["solver name 不能为空"])
    if not clean_type:
        return error_envelope(["solver_type 不能为空"])
    payload = {
        "name": clean_name,
        "solver_type": clean_type,
        "exe_path": exe_path or None,
        "extra_params": dict(extra_params) if extra_params else None,
    }
    if clean_name in _current_solver_names():
        return error_envelope([f"Solver '{clean_name}' already registered"])

    entries = _read_audit_entries()
    change_id = _change_id("solver_registration", payload)
    pending = _change_entries(entries, kind="solver_registration")
    if any(e.get("change_id") == change_id for e in pending):
        return ok_envelope(
            duplicate=True,
            already_pending=True,
            change_id=change_id,
            kind="solver_registration",
            status="pending",
            name=clean_name,
            errors=[],
        )
    conflict = [e for e in pending
                if (e.get("payload") or {}).get("name") == clean_name]
    if conflict:
        return error_envelope(
            [
            f"Solver '{clean_name}' 已有待批提案 {conflict[-1].get('change_id')}；"
            "请先批准或拒绝该提案，再提交新提案"],
        )

    propose_event = {
        "event": "propose", "ok": True, "kind": "solver_registration",
        "change_id": change_id, "token_hash": change_id, "payload": payload,
        "summary": f"注册求解器 {clean_name}（{clean_type}）",
        "requested_by": requested_by,
    }
    _append_change_event(propose_event)
    _record_approval_event_in_db(propose_event)
    return ok_envelope(
        duplicate=False,
        change_id=change_id,
        kind="solver_registration",
        status="pending",
        name=clean_name,
        payload=payload,
        errors=[],
    )


def _propose_resource_change(
    scope: str,
    resource: str,
    capacity: int,
    note: str = "",
    requested_by: str = "user",
) -> dict[str, Any]:
    """G13 资源容量变更提案（写入收件箱，不落 configs/resource_capacity.yaml）。

    scope="solver" → solver_capacity（如 comsol 席位），
    scope="class" → class_capacity（fdtd/pure/research/gpu，口径对齐
    service/resource_scheduler 的默认配置）。
    重复提交语义同求解器注册：同提案幂等、同资源不同容量显式报错、
    容量与已批准值相同则标记 already_effective。
    """
    from rfauto.service.resource_scheduler import DEFAULT_CLASS_CAPACITY

    clean_scope = str(scope or "").strip().lower()
    clean_res = str(resource or "").strip().lower()
    if clean_scope not in _RESOURCE_SCOPES:
        return error_envelope([f"scope 必须是 {_RESOURCE_SCOPES} 之一"])
    if not clean_res:
        return error_envelope(["resource 不能为空"])
    try:
        cap = int(capacity)
    except (TypeError, ValueError):
        return error_envelope([f"capacity 必须是整数: {capacity!r}"])
    if cap < 0:
        return error_envelope(["capacity 不能为负"])
    if clean_scope == "class" and clean_res not in DEFAULT_CLASS_CAPACITY:
        return error_envelope(
            [
            f"未知资源类 '{clean_res}'（已知: {sorted(DEFAULT_CLASS_CAPACITY)}）"],
        )

    payload = {"scope": clean_scope, "resource": clean_res,
               "capacity": cap, "note": str(note or "")}
    change_id = _change_id("resource_capacity", payload)
    current = _load_resource_capacity_config().get(f"{clean_scope}_capacity", {})
    if current.get(clean_res) == cap:
        return ok_envelope(
            duplicate=True,
            already_effective=True,
            change_id=change_id,
            kind="resource_capacity",
            status="applied",
            payload=payload,
            errors=[],
        )

    entries = _read_audit_entries()
    pending = [e for e in _change_entries(entries, kind="resource_capacity")
               if (e.get("payload") or {}).get("scope") == clean_scope
               and (e.get("payload") or {}).get("resource") == clean_res]
    if any(e.get("change_id") == change_id for e in pending):
        return ok_envelope(
            duplicate=True,
            already_pending=True,
            change_id=change_id,
            kind="resource_capacity",
            status="pending",
            payload=payload,
            errors=[],
        )
    if pending:
        return error_envelope(
            [
            f"{clean_scope}:{clean_res} 已有待批容量提案 {pending[-1].get('change_id')}；"
            "请先批准或拒绝该提案，再提交新提案"],
        )

    propose_event = {
        "event": "propose", "ok": True, "kind": "resource_capacity",
        "change_id": change_id, "token_hash": change_id, "payload": payload,
        "summary": f"资源容量 {clean_scope}:{clean_res} → {cap}",
        "requested_by": requested_by,
    }
    _append_change_event(propose_event)
    _record_approval_event_in_db(propose_event)
    return ok_envelope(
        duplicate=False,
        change_id=change_id,
        kind="resource_capacity",
        status="pending",
        payload=payload,
        errors=[],
    )


def _apply_resource_capacity(payload: dict[str, Any]) -> dict[str, Any]:
    """批准后落盘 G13 资源容量（configs/resource_capacity.yaml）+ 回读校验。"""
    import yaml

    scope = str(payload.get("scope", "")).strip().lower()
    resource = str(payload.get("resource", "")).strip().lower()
    capacity = int(payload.get("capacity", 0))
    data: dict[str, Any] = {}
    if _RESOURCE_CAPACITY_PATH.exists():
        data = yaml.safe_load(_RESOURCE_CAPACITY_PATH.read_text(encoding="utf-8")) or {}
    key = f"{scope}_capacity"
    bucket = data.get(key)
    if not isinstance(bucket, dict):
        bucket = {}
        data[key] = bucket
    bucket[resource] = capacity
    _RESOURCE_CAPACITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESOURCE_CAPACITY_PATH.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    reloaded = _load_resource_capacity_config().get(key, {})
    ok = reloaded.get(resource) == capacity
    return {"ok": ok, "kind": "resource_capacity",
            "applied": {"scope": scope, "resource": resource, "capacity": capacity,
                        "config_path": str(_RESOURCE_CAPACITY_PATH)},
            "errors": [] if ok else ["resource capacity written but not readable"]}


def _apply_change(entry: dict[str, Any]) -> dict[str, Any]:
    """变更提案生效（唯一副作用入口；仅被 _approve_change 调用）。"""
    kind = str(entry.get("kind", ""))
    payload = entry.get("payload") or {}
    if kind == "solver_registration":
        result = add_solver_to_config(
            payload.get("name", ""), payload.get("solver_type", ""),
            exe_path=payload.get("exe_path"),
            extra_params=payload.get("extra_params"))
        if not result.get("ok"):
            return {"ok": False, "kind": kind,
                    "errors": result.get("errors") or ["solver registration failed"]}
        return ok_envelope(
            kind=kind,
            applied={"solver": payload.get("name"),
                            "config_path": result.get("config_path"),
                            "loadable": result.get("loadable")},
            errors=[],
        )
    if kind == "resource_capacity":
        return _apply_resource_capacity(payload)
    return {"ok": False, "kind": kind, "errors": [f"未知变更类型: {kind}"]}


def _approve_change(change_id_str: str, approved_by: str = "user",
                    note: str = "") -> dict[str, Any]:
    """批准新变更类提案并落配置；重复批准幂等，已拒绝为终态不可批准。"""
    entries = _read_audit_entries()
    entry = _find_change(entries, change_id_str)
    if not entry:
        return error_envelope([f"No matching pending change for {change_id_str!r}"])
    change_id = str(entry.get("change_id"))
    kind = str(entry.get("kind"))
    if _change_decided(entries, change_id, "apply"):
        return ok_envelope(duplicate=True, already_applied=True, change_id=change_id, kind=kind, status="applied", errors=[])
    if _change_decided(entries, change_id, "reject"):
        return {"ok": False, "change_id": change_id, "kind": kind,
                "status": "rejected",
                "errors": [f"变更 {change_id} 已被拒绝，不能批准（拒绝为终态）"]}

    outcome = _apply_change(entry)
    approve_event = {
        "event": "approve", "ok": bool(outcome.get("ok")), "kind": kind,
        "change_id": change_id, "token_hash": change_id,
        "approved_by": approved_by, "note": str(note or ""),
    }
    apply_event = {
        "event": "apply", "ok": bool(outcome.get("ok")), "kind": kind,
        "change_id": change_id, "token_hash": change_id,
        "detail": outcome.get("applied"),
        "errors": outcome.get("errors") or [],
    }
    _append_change_event(approve_event)
    _append_change_event(apply_event)
    # R2-D-02：终态即时推进 approvals 读模型（ok=False 不改状态，提案留在
    # 收件箱——apply 失败与文件口径一致，仍可重试或拒绝）
    _record_approval_event_in_db(apply_event)
    return {**outcome, "change_id": change_id, "duplicate": False,
            "status": "applied" if outcome.get("ok") else "failed"}


def _reject_change(change_id_str: str, reason: str = "",
                   rejected_by: str = "user") -> dict[str, Any]:
    """拒绝新变更类提案：只写 reject 审计，配置不动；重复拒绝幂等。"""
    entries = _read_audit_entries()
    entry = _find_change(entries, change_id_str)
    if not entry:
        return error_envelope([f"No matching pending change for {change_id_str!r}"])
    change_id = str(entry.get("change_id"))
    kind = str(entry.get("kind"))
    if _change_decided(entries, change_id, "reject"):
        return ok_envelope(duplicate=True, already_rejected=True, change_id=change_id, kind=kind, status="rejected", errors=[])
    if _change_decided(entries, change_id, "apply"):
        return {"ok": False, "change_id": change_id, "kind": kind,
                "status": "applied",
                "errors": [f"变更 {change_id} 已批准生效，不能拒绝（批准为终态）"]}

    reject_event = {
        "event": "reject", "ok": True, "kind": kind,
        "change_id": change_id, "token_hash": change_id,
        "reason": str(reason or ""), "rejected_by": rejected_by,
    }
    _append_change_event(reject_event)
    _record_approval_event_in_db(reject_event)
    return ok_envelope(duplicate=False, change_id=change_id, kind=kind, status="rejected", errors=[])


def _list_pending_changes(kind: str | None = None) -> dict[str, Any]:
    """便捷查看新变更类待批提案（收件箱的子视图，供 CLI/测试）。"""
    entries = _change_entries(_read_audit_entries(), kind=kind)
    return ok_envelope(pending=list(reversed(entries)), total=len(entries))


# ─── 6j: LLM Conversation ────────────────────────────────────────────────────

class AgentChat:
    """Self-built LLM conversation loop (direct service layer calls).

    6j: No external MCP needed. Each tool call = service function call.
    Supports dual channel: embedded (this class) or MCP client (external).
    """

    def __init__(self, model: str = "default"):
        import time as _time
        import uuid as _uuid

        from rfauto.pipeline.quota_guard import CostLedger

        self.model = model
        self.history: list[dict[str, str]] = []
        self.tool_calls: list[dict[str, Any]] = []
        # 会话级遥测（UI 统计条数据源；UI 进程内累计，重启清零）
        self.stats: dict[str, Any] = {
            "turns": 0, "llm_calls": 0, "llm_elapsed_s": 0.0,
            "tool_calls": 0, "tool_elapsed_s": 0.0,
            "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
        }
        # G14 成本账本：LLM token 记账（RuntimeUsage 经
        # agent_runtime.usage_to_cost_ledger 薄适配喂入；batch=session_id，
        # actor=模型名；rollup 可供 report/quota_guard 既有消费方使用）
        self.cost_ledger: CostLedger = CostLedger()
        # 工具预算耗尽时保留的对话现场（用户说"继续"则原样续跑，不重探索）
        self._pending_messages: list[dict[str, Any]] | None = None
        # AD-2 会话注入 memo（SK-V §2.1-2）：当轮任务词集键 → 已组装
        # extra_system（""=已组装但两段皆空）；同键多轮追问复用，不重复检索
        # 不重复占预算。键口径 knowledge_injection_service.injection_key。
        self._last_injection_key: str | None = None
        self._last_extra_system: str | None = None
        # Pi 式会话存档（schema 版本化 JSON，runs/chat_sessions）
        self.session_id = "chat_" + _time.strftime("%Y%m%d_%H%M%S") + "_" + _uuid.uuid4().hex[:6]
        self._session_doc: dict[str, Any] | None = None

    def chat(self, message: str) -> dict[str, Any]:
        """Process a user message and return response.

        工具循环在 AgentRuntime（默认 builtin，可经 RuntimeRegistry 换
        pydantic-ai 等实现）；未配置 LLM API 时回退关键词路由。
        """
        self.history.append({"role": "user", "content": message})
        self.stats["turns"] += 1

        cfg = get_chat_settings()
        if cfg.get("configured"):
            try:
                if (self._pending_messages
                        and message.strip().lower() in ("继续", "continue", "go", "接着分析")):
                    response = self._llm_turn("", pending= self._pending_messages)
                    self._pending_messages = None
                else:
                    self._pending_messages = None
                    response = self._llm_turn(message)
            except Exception as exc:  # LLM 故障回退关键词路由（#105 原则）
                fallback = self._route_message(message)
                fallback["text"] = f"[LLM 调用失败，已回退指令模式: {exc}]\n" + fallback["text"]
                response = fallback
        else:
            response = self._route_message(message)

        self.history.append({"role": "assistant", "content": response["text"]})
        response["stats"] = dict(self.stats)
        self._persist_session()
        return response

    def reset(self) -> dict[str, Any]:
        """清空会话（历史/工具记录/续跑现场/统计/成本账本），换新 session_id。"""
        import time as _time
        import uuid as _uuid

        from rfauto.pipeline.quota_guard import CostLedger

        self.history.clear()
        self.tool_calls.clear()
        self._pending_messages = None
        # AD-2 注入 memo 一并清空（新会话不继承上一会话注入缓存）
        self._last_injection_key = None
        self._last_extra_system = None
        self._session_doc = None
        self.cost_ledger = CostLedger()
        for key in self.stats:
            self.stats[key] = 0 if not isinstance(self.stats[key], float) else 0.0
        self.session_id = ("chat_" + _time.strftime("%Y%m%d_%H%M%S")
                           + "_" + _uuid.uuid4().hex[:6])
        return ok_envelope(session_id=self.session_id)

    def _persist_session(self) -> None:
        """Pi 式会话存档（观测路径 best-effort，不阻塞对话 #105）。"""
        try:
            from rfauto.service.agent_runtime import new_session_doc, persist_session
            if self._session_doc is None:
                self._session_doc = new_session_doc(self.session_id, {"model": self.model})
            self._session_doc["history"] = list(self.history)
            self._session_doc["tool_calls"] = list(self.tool_calls)
            self._session_doc["stats"] = dict(self.stats)
            persist_session(self._session_doc)
        except Exception:
            pass

    def _compose_extra_system(self, task_text: str) -> str | None:
        """AD-2+AD-3 注入组装（extra_system 单通道；缺省关=返回 None 零变化）。

        固定序 few_shot + knowledge（SK-V §2.1-2），共享 2400 chars 单账本：
        few-shot 整块截断 ≤900（clamp_few_shot_section），知识节预算=
        min(section, extra_system−len(few))。空命中两段皆空 → None（与不
        注入档逐字节一致）。会话级 memo 按当轮词集键复用（多轮追问不重复
        检索）。全链 best-effort #105：组装失败返回 None 不阻塞对话。
        """
        try:
            from rfauto.service.knowledge_injection_service import (
                EXTRA_SYSTEM_MAX,
                FEW_SHOT_MAX,
                KNOWLEDGE_INJECTION_SCHEMA,
                SECTION_MAX,
                clamp_few_shot_section,
                compose_knowledge_injection,
                injection_key,
                knowledge_injection_settings,
            )
            settings = knowledge_injection_settings()
            if not settings.get("enabled"):
                return None
        except Exception:  # 开关面故障=零注入，不阻塞对话（#105）
            return None
        key = injection_key(task_text)
        if key == self._last_injection_key:
            return self._last_extra_system or None
        budgets = dict(settings.get("budgets") or {})
        budgets.setdefault("few_shot", FEW_SHOT_MAX)
        budgets.setdefault("extra_system", EXTRA_SYSTEM_MAX)
        budgets.setdefault("section", SECTION_MAX)

        few_raw = ""
        few_dropped = 0
        try:
            from rfauto.service.few_shot_service import build_few_shot_system
            few_raw = str(build_few_shot_system(task_text).get("section") or "")
        except Exception:  # few-shot 源故障不阻塞知识注入（#105）
            few_raw = ""
        few, few_dropped = clamp_few_shot_section(
            few_raw, max_chars=int(budgets["few_shot"]))

        knowledge_usage: dict[str, Any] = {}
        entries: list[dict[str, Any]] = []
        know = ""
        try:
            remaining = int(budgets["extra_system"]) - len(few)
            result = compose_knowledge_injection(
                task_text,
                budgets={**budgets,
                         "section": min(int(budgets["section"]),
                                        max(remaining, 0))})
            if result.get("ok"):
                know = str(result.get("section") or "")
                entries = list(result.get("entries") or [])
                knowledge_usage = dict(result.get("usage") or {})
        except Exception:  # 知识源故障=零知识注入，不阻塞对话（#105）
            know = ""
        extra = few + know if (few or know) else ""
        extra = extra.strip("\n") or ""
        if not extra:
            self._last_injection_key = key
            self._last_extra_system = ""
            return None
        self._record_injections(KNOWLEDGE_INJECTION_SCHEMA, entries,
                                knowledge_usage, len(few), few_dropped)
        self._last_injection_key = key
        self._last_extra_system = extra
        return extra

    def _record_injections(self, schema: str, entries: list[dict[str, Any]],
                           usage: dict[str, Any], few_shot_chars: int,
                           few_shot_dropped: int) -> None:
        """注入留痕进会话档 meta.injections（best-effort，persist 不阻塞 #105）。"""
        try:
            from rfauto.service.agent_runtime import new_session_doc
            if self._session_doc is None:
                self._session_doc = new_session_doc(
                    self.session_id, {"model": self.model})
            meta = self._session_doc.setdefault("meta", {})
            meta["injections"] = {
                "schema": schema,
                "entries": [dict(e) for e in entries],
                "usage": {**usage, "few_shot_chars": int(few_shot_chars),
                          "few_shot_truncated_blocks": int(few_shot_dropped)},
            }
        except Exception:  # 观测留痕失败不阻塞对话主路径（#105）
            pass

    def _llm_turn(self, message: str, pending: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """一轮 LLM 对话：循环策略在 AgentRuntime（默认 builtin，可换实现）。"""
        import time as _time

        from rfauto.service.agent_runtime import (
            RuntimeRegistry,
            RuntimeRequest,
            default_tool_specs,
            usage_to_cost_ledger,
        )

        if pending is not None:
            messages = pending  # 续跑：沿用上次的完整工具现场（含中间结果）
            extra_system = None  # 现场 messages 已含已插入注入条，不重组（Q3）
        else:
            menu = list_recipes().get("recipes", [])
            menu_lines = "\n".join(f"- {r['path']}（{r['model']}）" for r in menu) or "-（无）"
            messages = [{"role": "system",
                         "content": get_system_prompt()
                         + "\n当前可用配方（propose_params 的 recipe 参数请用这些完整路径）：\n" + menu_lines}]
            messages += [{"role": m["role"], "content": m["content"]}
                         for m in self.history[-16:]]
            # AD-2 知识注入 + AD-3 few-shot：extra_system 单通道单账本
            # （SK-V §2.1-2；缺省关=逐字节不变；绝不进 get_system_prompt
            # 本体——AD-1 指纹门）。
            extra_system = self._compose_extra_system(message)
        try:
            raw = get_chat_settings_raw()
            max_rounds = max(4, int(raw.get("max_tool_rounds", 12)))
            runtime_name = str(raw.get("runtime", "builtin"))
            model_name = str(raw.get("model") or runtime_name)
        except Exception:
            max_rounds, runtime_name = 12, "builtin"
            model_name = runtime_name

        def _executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
            t1 = _time.perf_counter()
            try:
                result = _execute_tool(name, args)
            except Exception as exc:  # 工具异常回传给模型自行调整
                result = {"error": str(exc)}
            self.stats["tool_calls"] += 1
            self.stats["tool_elapsed_s"] += _time.perf_counter() - t1
            # DS-2 留痕：工具结果正文摘要随 tool_calls 落会话档（与运行时
            # 注入消息同渲染单源 agent_runtime.tool_context_content）——
            # "LLM 可见即留痕"的写入侧；比对侧见 _llm_turn 尾部挂点。
            entry: dict[str, Any] = {"action": name, "args": args}
            try:
                from rfauto.service.agent_runtime import tool_context_content
                from rfauto.service.session_audit_service import content_digest

                entry["result_digest"] = content_digest(
                    tool_context_content(result))
            except Exception:  # 留痕摘要属观测面，失败不阻塞工具执行（#105）
                pass
            self.tool_calls.append(entry)
            return result

        request = RuntimeRequest(messages=messages, tools=default_tool_specs(),
                                 max_rounds=max_rounds,
                                 extra_system=extra_system)
        out = RuntimeRegistry.create(runtime_name).submit(request, _executor)
        self.stats["llm_calls"] += out.usage.llm_calls
        self.stats["llm_elapsed_s"] += out.usage.llm_elapsed_s
        self.stats["prompt_tokens"] += out.usage.prompt_tokens
        self.stats["completion_tokens"] += out.usage.completion_tokens
        self.stats["cached_tokens"] += out.usage.cached_tokens
        # G14：RuntimeUsage → CostLedger token 记账（batch=session_id，
        # actor=模型名；薄适配与字段口径见 agent_runtime.usage_to_cost_ledger）
        usage_to_cost_ledger(out.usage, self.cost_ledger,
                             batch=self.session_id, actor=model_name)
        if out.finish_reason == "budget_exhausted":
            self._pending_messages = out.messages  # 保留工具现场，用户说"继续"即无损续跑
        # DS-2 "LLM 可见即留痕"比对挂点（best-effort，告警不阻断 #105）：
        # 本轮上下文的 role=tool 消息逐条对会话留痕（history+tool_calls
        # 摘要集）核可溯性，违例计数进 stats/response 注记，绝不 raise。
        response: dict[str, Any] = {"text": out.text,
                                    "action": out.action or "chat",
                                    "result": out.result,
                                    "tools": out.tools_used}
        audit = self._audit_turn(out.messages)
        if audit is not None:
            self.stats["audit_violates"] = (int(self.stats.get(
                "audit_violates") or 0) + int(audit.violate_count or 0))
            response["session_audit"] = audit.as_dict()
        return response

    def _audit_turn(self, turn_messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        """DS-2 不变量逐轮校验（缺省开、告警不阻断；chat_settings 可关）。

        会话留痕单源 = 本实例内存 trail（history+tool_calls，每轮经
        _persist_session 落 runs/chat_sessions）。校验层任何异常收敛为
        {ok: False, error: …} 回执（session_audit_service.audit_turn_
        best_effort，#105）；``session_audit_invariant: off`` 时返回
        None（不校验、response 无 session_audit 键）。
        """
        try:
            raw = get_chat_settings_raw()
            enabled = str(raw.get("session_audit_invariant", "on")) != "off"
        except Exception:
            enabled = True  # 配置读取故障不静默关不变量（缺省开）
        if not enabled:
            return None
        try:
            from rfauto.service.session_audit_service import audit_turn_best_effort
        except Exception as exc:  # #105：校验层自身故障不阻塞主对话路径
            return error_envelope(f"session_audit 导入失败: {exc}",
                                  source="session_audit")

        trail = {"history": list(self.history),
                 "tool_calls": list(self.tool_calls)}
        return audit_turn_best_effort(turn_messages, trail,
                                      session_id=self.session_id)

    def _route_message(self, message: str) -> dict[str, Any]:
        """Route message to appropriate service function."""
        msg_lower = message.lower().strip()

        if msg_lower.startswith("list solvers") or msg_lower == "solvers":
            from rfauto.service.r3_services import list_registered_solvers
            result = list_registered_solvers()
            return {"text": json.dumps(result, indent=2), "action": "list_solvers", "result": result}

        if msg_lower.startswith("list runs") or msg_lower == "runs":
            from rfauto.infra.run_store import list_runs
            runs = list_runs()
            return {"text": f"Found {len(runs)} runs", "action": "list_runs", "result": {"runs": runs}}

        if msg_lower.startswith("validate "):
            recipe_path = message[9:].strip()
            from rfauto.service.api import validate_recipe
            result = validate_recipe(recipe_path)
            return {"text": json.dumps(result, indent=2), "action": "validate", "result": result}

        if msg_lower.startswith("diagnose "):
            run_id = message[9:].strip()
            from rfauto.service.api import get_metrics
            result = get_metrics(run_id)
            if result.get("ok"):
                diagnosis = result["data"].get("diagnosis", {})
                return {"text": json.dumps(diagnosis, indent=2), "action": "diagnose", "result": diagnosis}
            return {"text": f"Run not found: {run_id}", "action": "error", "result": result}

        if msg_lower.startswith("propose "):
            parts = message[8:].strip().split(" ", 1)
            recipe_path = parts[0]
            params_str = parts[1] if len(parts) > 1 else "{}"
            try:
                params = json.loads(params_str)
            except json.JSONDecodeError:
                params = {}
            from rfauto.service.api import agent_propose
            result = agent_propose(recipe_path, params)
            self.tool_calls.append({"action": "propose", "params": params, "result": result})
            return {"text": json.dumps(result, indent=2), "action": "propose", "result": result}

        # Default: help message
        return {
            "text": "Available commands:\n"
                    "  solvers - List registered solvers\n"
                    "  runs - List recent runs\n"
                    "  validate <recipe> - Validate a recipe\n"
                    "  diagnose <run_id> - Diagnose a run\n"
                    "  propose <recipe> [params_json] - Propose parameter changes\n"
                    "  help - Show this message",
            "action": "help",
        }

    def get_history(self) -> list[dict[str, str]]:
        return self.history

    def get_tool_calls(self) -> list[dict[str, Any]]:
        return self.tool_calls


# ─── LLM 对话设置与真实模型接入（OpenAI 兼容 /chat/completions）──────────────

CHAT_SETTINGS_PATH = Path("configs") / "chat_settings.yaml"
_SYSTEM_PROMPT = (
    "你是 rfauto（HFSS/ADS 射频仿真调优框架）的助手。可用工具：\n"
    "list_solvers() 列出求解器；list_runs(limit) 列出 run；"
    "run_detail(run_id) 查看 run 指标与产物；validate_recipe(path) 校验配方；"
    "diagnose_run(run_id) 给出诊断；propose_params(recipe, params) 生成参数提案"
    "（走三层 Gate，需用户在收件箱批准）。\n"
    "改配方必须走沙箱：edit_recipe_draft(recipe, params) 把修改写入草稿副本"
    "（不触碰真实配方），diff_recipe_draft 查看差异，promote_recipe_draft 提交审批。"
    "你没有直接修改 recipes/ 目录的能力，也不要向用户声称已直接改了配方。\n"
    "工作规范：\n"
    "1. 探索要节制：每次任务最多先调 1-2 次只读工具（如 run_detail 看最新 run），"
    "不要重复调用同一工具，也不要逐个遍历所有 run。\n"
    "2. 用户要『提议/优化参数』时：读一次 run_detail 或 validate_recipe 后，"
    "**立即调用 propose_params**——参数键名用配方 optimization.params 里的参数名"
    "（如 arm_len_mm），数值必须落在其 low/high 范围内，通常给出 2-4 个参数的组合。\n"
    "3. 用户要『直接改配方』时：先 edit_recipe_draft 写草稿并 promote，"
    "向用户说明需在收件箱批准。\n"
    "4. 单轮任务尽量在 6 次工具调用内完成并给出最终答复。\n"
    "5. 回答用中文，简洁，结尾给出下一步建议。")


def get_system_prompt() -> str:
    """Agent 系统提示词的公开访问口（F-4；AD-1 §D-4 起单源=外置文件）。

    读 configs/prompts/system_prompt.md（frontmatter {schema,version,changelog}
    + 正文；写入约定正文末尾恰一个换行符收尾，读取时剥除，正文与内置版
    逐字节可比）。文件缺失/frontmatter 非法 → 回退内置 ``_SYSTEM_PROMPT``
    并 WARN 一次（进程级去重——回退必须可见但不刷屏；#105 观测路径不得
    阻塞对话主路径）。ui/server 等外部消费面不得穿透私有名
    （``r3_services._SYSTEM_PROMPT``），一律走本函数。
    """
    global _prompt_warn_emitted
    doc = _load_prompt_doc()
    if doc.get("ok"):
        return doc["prompt"]
    if not _prompt_warn_emitted:
        _prompt_warn_emitted = True
        try:
            import logging

            logging.getLogger(__name__).warning(
                "系统提示词外置文件不可用（%s），回退内置版：%s",
                doc.get("path"), "; ".join(doc.get("errors") or []))
        except Exception:
            pass
    return _SYSTEM_PROMPT


# AD-1 系统提示词版本化：外置单源（frontmatter {schema,version,changelog}+正文）。
# 锚仓库根（__file__ 推导，cwd 无关——相对 configs/ 读在 cd 后静默落空，#295 同族）。
SYSTEM_PROMPT_SCHEMA = "rfauto.system_prompt/1"
SYSTEM_PROMPT_PATH = (Path(__file__).resolve().parent.parent.parent.parent
                      / "configs" / "prompts" / "system_prompt.md")
_prompt_warn_emitted = False


def _load_prompt_doc() -> dict[str, Any]:
    """读取并解析外置系统提示词（内部：任何失败返回 ok=False+errors，不抛）。

    解析口径：须以 ``---\\n`` 起，第一个 ``\\n---\\n`` 收 frontmatter（yaml）；
    其后为正文，末尾恰一个换行符是写入约定、读取时剥除。
    """
    import yaml

    path = str(SYSTEM_PROMPT_PATH)
    try:
        raw = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "source": "builtin", "path": path,
                "errors": [f"读取失败: {exc}"]}
    try:
        if not raw.startswith("---\n"):
            raise ValueError("缺 frontmatter 开头（须以 '---' 行起）")
        close = raw.find("\n---\n", 4)
        if close < 0:
            raise ValueError("缺 frontmatter 收尾（'---' 行）")
        front = yaml.safe_load(raw[4:close]) or {}
        if not isinstance(front, dict):
            raise ValueError("frontmatter 必须是映射")
        schema = str(front.get("schema") or "")
        if schema != SYSTEM_PROMPT_SCHEMA:
            raise ValueError(
                f"schema 不识别: {schema!r}（期望 {SYSTEM_PROMPT_SCHEMA!r}）")
        body = raw[close + 5:]
        if body.endswith("\n"):
            body = body[:-1]  # 写入约定：正文末尾恰一个收尾换行
        if not body.strip():
            raise ValueError("提示词正文为空")
    except Exception as exc:
        return {"ok": False, "source": "builtin", "path": path,
                "errors": [f"{type(exc).__name__}: {exc}"]}
    return ok_envelope(
        source="file",
        path=path,
        errors=[],
        prompt=body,
        schema=schema,
        version=front.get("version"),
        changelog=str(front.get("changelog") or ""),
    )


def get_system_prompt_meta() -> dict[str, Any]:
    """系统提示词元数据与指纹（AD-1）：实际生效正文的 sha256 + 版本溯源。

    返回 {ok, source: "file"|"builtin", path, schema, version, changelog,
    sha256, errors}——source="builtin" 即已回退（errors 说明原因）；
    sha256 对**实际生效正文**计算（file/builtin 同文则同指纹，prompt 回归门
    可据此判"两版无差"）。
    """
    import hashlib

    doc = _load_prompt_doc()
    text = doc["prompt"] if doc.get("ok") else _SYSTEM_PROMPT
    return {"ok": bool(doc.get("ok")), "source": doc.get("source"),
            "path": doc.get("path"), "schema": doc.get("schema"),
            "version": doc.get("version"), "changelog": doc.get("changelog"),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "errors": list(doc.get("errors") or [])}


def get_chat_settings_raw() -> dict[str, Any]:
    """内部用：原始设置（含 api_key），不对外。"""
    import yaml

    if not CHAT_SETTINGS_PATH.exists():
        return {}
    return yaml.safe_load(CHAT_SETTINGS_PATH.read_text(encoding="utf-8")) or {}


def get_chat_settings() -> dict[str, Any]:
    """读取 LLM 对话设置；api_key 不回传明文。"""
    import yaml

    if not CHAT_SETTINGS_PATH.exists():
        return ok_envelope(configured=False, base_url="", model="", runtime="builtin", api_key_set=False)
    data = yaml.safe_load(CHAT_SETTINGS_PATH.read_text(encoding="utf-8")) or {}
    return ok_envelope(
        configured=bool(data.get("api_key")),
        base_url=data.get("base_url", ""),
        model=data.get("model", ""),
        runtime=data.get("runtime", "builtin"),
        api_key_set=bool(data.get("api_key")),
    )


def save_chat_settings(base_url: str, model: str, api_key: str = "") -> dict[str, Any]:
    """保存 LLM 对话设置（api_key 落本地 configs/，空串=不修改已存 key）。"""
    import yaml

    data = {}
    if CHAT_SETTINGS_PATH.exists():
        data = yaml.safe_load(CHAT_SETTINGS_PATH.read_text(encoding="utf-8")) or {}
    if base_url:
        data["base_url"] = base_url
    if model:
        data["model"] = model
    if api_key:
        data["api_key"] = api_key
    CHAT_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHAT_SETTINGS_PATH.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ok_envelope(base_url=data.get("base_url", ""), model=data.get("model", ""), api_key_set=bool(data.get("api_key")))


def _llm_chat_completion(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """兼容别名：传输层已移至 agent_runtime.openai_chat_completion。"""
    from rfauto.service.agent_runtime import default_tool_specs, openai_chat_completion
    return openai_chat_completion(messages, [t.to_schema() for t in default_tool_specs()])


def _execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """工具名 → service 函数（LLM function-calling 专用映射）。"""
    if name == "list_solvers":
        return list_registered_solvers()
    if name == "list_runs":
        from rfauto.infra.run_store import list_runs
        return {"runs": list_runs()}
    if name == "run_detail":
        from rfauto.service.api import get_metrics
        return get_metrics(args["run_id"])
    if name == "validate_recipe":
        from rfauto.service.api import validate_recipe
        return validate_recipe(args["path"])
    if name == "diagnose_run":
        from rfauto.service.api import get_metrics
        r = get_metrics(args["run_id"])
        return r.get("data", {}).get("diagnosis", r)
    if name == "propose_params":
        from rfauto.service.api import agent_propose
        return agent_propose(_resolve_recipe(args["recipe"]), args.get("params", {}))
    if name in ("edit_recipe_draft", "diff_recipe_draft", "promote_recipe_draft"):
        # 沙箱写面：只动 runs/recipe_sandbox/ 草稿，生效必须走 Gate（agent_sandbox）
        from rfauto.service.agent_sandbox import RecipeSandbox
        recipe = _resolve_recipe(args["recipe"])
        sandbox = RecipeSandbox()
        if name == "edit_recipe_draft":
            return sandbox.apply_param_edits(recipe, args.get("params") or {})
        if name == "diff_recipe_draft":
            return sandbox.diff(recipe)
        return sandbox.promote(recipe)
    return {"error": f"unknown tool {name}"}


def _resolve_recipe(recipe: str) -> str:
    """配方路径模糊解析：LLM 常传裸短名（"wilkinson"），按 recipes/ 目录
    匹配唯一/首个命中（路径或模型名包含即算）；无命中保持原样让下游报错。"""
    p_ = Path(recipe)
    if p_.exists():
        return str(p_)
    recipes = list_recipes().get("recipes", [])
    needle = recipe.lower().removesuffix(".yaml")
    hits = [r["path"] for r in recipes
            if needle in r["path"].lower() or needle in r.get("model", "").lower()]
    return hits[0] if hits else recipe


# ─── 文件浏览（工程导入选文件）与配方目录 ────────────────────────────────────

#: 敏感面单源（S-1/S-3，code_audit_slice6）：configs/ 目录承载凭据
#: （chat_settings.yaml 含 LLM API key、remote_machines.local.yaml 含远程
#: 主机凭据），*.local.yaml 是本机覆盖配置、同样不入暴露面。
FS_SENSITIVE_DIR_NAMES = frozenset({"configs"})
FS_SENSITIVE_FILE_NAMES = frozenset({"chat_settings.yaml"})


def fs_allowed_roots() -> list[Path]:
    """文件暴露面（fs_list / recipe_view）的允许根（单源）。

    允许根 = 当前工作目录 + 环境变量 ``RFAUTO_FS_ROOT``（``os.pathsep``
    分隔可设多个，如 Windows 下 ``D:\\proj;E:\\data``）。UI 的文件浏览与
    配方读都以这组根做围栏，越界一律显式报错（见 :func:`fs_read_fence`）。
    """
    roots = [Path.cwd().resolve()]
    for part in os.environ.get("RFAUTO_FS_ROOT", "").split(os.pathsep):
        part = part.strip()
        if part:
            roots.append(Path(part).resolve())
    return roots


def _fs_within_roots(target: Path, roots: list[Path]) -> bool:
    """target（应已 resolve）是否落在任一允许根内。

    #318 铁律：Windows 路径比较必须 os.path.normcase（大小写/分隔符不敏感）；
    根边界用"normcase 后 == 根 或 以 根+os.sep 为前缀"判定，防前缀串扰
    （如 C:\\ab 不算 C:\\a 的子路径）。
    """
    t = os.path.normcase(str(Path(target).resolve()))
    for r in roots:
        rt = os.path.normcase(str(r))
        if t == rt or t.startswith(rt.rstrip("\\/") + os.sep):
            return True
    return False


def _fs_sensitive_dir_hit(resolved: Path) -> bool:
    """路径任一分量（含自身）名为 configs 即命中凭据目录。"""
    return any(p.name.lower() in FS_SENSITIVE_DIR_NAMES
               for p in (resolved, *resolved.parents))


def fs_read_fence(
    path: str | Path, allow_outside_roots: bool = False
) -> str | None:
    """读路径围栏（S-1 列举 / S-3 单文件读共用）：拒绝返回错误消息，放行 None。

    三条规则（依次判定）：
    1. 敏感目录：路径任一分量名为 ``configs``（含 target 就是 configs 目录）
       ——凭据面不暴露，任何根内/根外、任何放行参数都拒；
    2. 敏感文件：文件名 ``*.local.yaml`` 或 ``chat_settings.yaml``——同上，
       ``allow_outside_roots`` 只放宽根围栏、不放宽敏感过滤；
    3. 根围栏（``allow_outside_roots=False`` 时）：resolve + normcase 后必须
       落在 :func:`fs_allowed_roots` 之一内。错误消息指明允许根与
       RFAUTO_FS_ROOT 出口，信封由调用方原样透传前端。
    """
    target = Path(path)
    resolved = target.resolve()
    if _fs_sensitive_dir_hit(resolved):
        return f"敏感目录（configs，凭据面）不可访问: {target}"
    low = resolved.name.lower()
    if low.endswith(".local.yaml") or low in FS_SENSITIVE_FILE_NAMES:
        return (f"敏感文件不可访问: {target}"
                "（*.local.yaml / chat_settings.yaml 为凭据面）")
    if not allow_outside_roots:
        roots = fs_allowed_roots()
        if not _fs_within_roots(resolved, roots):
            allowed = "; ".join(str(r) for r in roots)
            return (f"路径越界: {target}（允许根: {allowed}；"
                    "如需其他根可设 RFAUTO_FS_ROOT 环境变量）")
    return None


def fs_list(path: str = "") -> dict[str, Any]:
    """列出目录内容（目录 + 工程相关文件），供导入向导选文件。

    根围栏（S-1，code_audit_slice6 审查）：/api/fs/list 是 loopback HTTP
    暴露面，path 不设防时任意目录（系统盘/凭据目录）可被远程枚举。允许根
    见 :func:`fs_allowed_roots`（cwd + RFAUTO_FS_ROOT），经
    :func:`fs_read_fence` 判定（normcase 比较，#318），越界/敏感目录返回
    ``{"ok": False, "error": ...}``（ui/server 路由信封原样透传）。
    敏感条目过滤：名为 configs 的子目录、``*.local.yaml`` 与
    ``chat_settings.yaml`` 文件不进 entries；返回形状
    ok/path/parent/entries 与围栏前完全一致。
    """
    target = Path(path) if path else Path.cwd()
    fence_err = fs_read_fence(target)
    if fence_err is not None:
        return {"ok": False, "error": fence_err}
    if not target.exists() or not target.is_dir():
        return {"ok": False, "error": f"目录不存在: {target}"}
    entries = []
    try:
        for e in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            if e.name.startswith("."):
                continue
            low = e.name.lower()
            if e.is_dir() and low in FS_SENSITIVE_DIR_NAMES:
                continue  # 凭据目录（configs）不进暴露面
            if e.is_file() and (low.endswith(".local.yaml")
                                or low in FS_SENSITIVE_FILE_NAMES):
                continue  # 凭据文件（*.local.yaml / chat_settings.yaml）不进暴露面
            kind = "dir" if e.is_dir() else "file"
            # Touchstone（WP0.3/E8 S 参数页外部导入）与工程文件同列
            if e.is_file() and e.suffix.lower() not in (
                ".aedt", ".yaml", ".yml", ".wbpz",
                ".s1p", ".s2p", ".s3p", ".s4p",
            ):
                continue
            entries.append({"name": e.name, "path": str(e), "kind": kind})
    except PermissionError:
        return {"ok": False, "error": f"无权限读取: {target}"}
    return ok_envelope(path=str(target), parent=str(target.parent), entries=entries)


RECIPE_HELP = {
    "model": "仿真模型（插件名），如 wilkinson_power_divider / patch_antenna；决定参数集与 fake 解析模型",
    "params": "可调参数及当前值；HFSS 通道经 hfss_var_map 映射到工程变量名",
    "setup": "扫频范围（freq_range_ghz）与点数，决定 S 参数曲线覆盖的频段",
    "objectives": "目标（如 s11_db 带内 max_below -15）：定义'好'的标准，是优化与诊断的裁判",
    "optimization": "优化器配置：每个参数的 low/high 范围、trial 数、采样器（TPE/CMA-ES）",
    "fidelity": "多保真开关：fake 粗筛 → HFSS/openEMS 精算（P0 gate 校验排序一致性）",
}

#: 工作副本"人工审阅入库"提示（C22，TODO:417 followUp）。指向既有 promote/
#: 审批面（rfauto inbox 审批收件箱，propose→approve→apply 三层 Gate），
#: 不新增后端命令——工作副本按守卫设计不自动回写 recipes/ 原件。
WORKCOPY_REVIEW_HINT = (
    "本条是 runs/recipe_workcopy/ 工作副本，recipes/ 原件未被改动。"
    "人工审阅：先与原件 diff 对比确认改动；入库：经既有审批链"
    "（rfauto inbox 审批收件箱，propose→approve→apply 三层 Gate）"
    "或人工确认后显式写回原件并 git commit 留痕。"
)


def _workcopy_root() -> Path:
    """工作副本根（与 infra.recipe_guard.WORKCOPY_SUBDIR 同源单源）。"""
    from rfauto.infra.recipe_guard import WORKCOPY_SUBDIR

    return Path(*WORKCOPY_SUBDIR)


def _scan_recipe_dir(root: Path, kind: str) -> list[dict[str, Any]]:
    """扫描一个配方目录 -> 条目列表（kind: original|workcopy，#105 单文件不阻塞）。"""
    import yaml

    out: list[dict[str, Any]] = []
    if not root.exists():
        return out
    for p in sorted(root.rglob("*.yaml")):
        entry: dict[str, Any]
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            entry = {
                "path": str(p).replace("\\", "/"),
                "kind": kind,
                "model": data.get("model", "?"),
                "n_params": len(data.get("params", {})),
                "n_objectives": len(data.get("objectives", [])),
                "freq_range": (data.get("setup", {}) or {}).get("freq_range_ghz", []),
            }
        except Exception as exc:  # 单文件解析失败不阻塞目录（#105）
            entry = {"path": str(p).replace("\\", "/"), "kind": kind,
                     "model": f"<解析失败: {exc}>"}
        if kind == "workcopy":
            entry["source_recipe"] = "recipes/" + p.relative_to(root).as_posix()
            entry["review_hint"] = WORKCOPY_REVIEW_HINT
        out.append(entry)
    return out


def list_recipes() -> dict[str, Any]:
    """扫描 recipes/ 原件与 runs/recipe_workcopy/ 工作副本，分组返回（C22）。

    分组字段（JSON 进出，前端只渲染）：``recipes`` 键保持只含 recipes/
    原件（既有消费者零改动——LLM 配方菜单与模糊解析都消费它），工作副本
    单列 ``workcopies``（每条附 ``source_recipe`` 反查原件路径与
    ``review_hint`` 人工审阅入库提示），``groups`` 给分组计数；两列表的
    每条都带 ``kind``（original/workcopy）。
    """
    originals = _scan_recipe_dir(Path("recipes"), "original")
    workcopies = _scan_recipe_dir(_workcopy_root(), "workcopy")
    return ok_envelope(
        recipes=originals,
        workcopies=workcopies,
        groups={"originals": len(originals), "workcopies": len(workcopies)},
        help=RECIPE_HELP,
    )
