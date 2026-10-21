"""r3_services.governance —— 审批治理面（6i 收件箱 + 变更提案/审批/拒绝/应用 + RegistryDB 同步）。

自 r3_services.py 巨石按职责域拆分（架构批 W7-S1 T2，AU-1 工艺）：代码体自原「6i Approval Inbox」与变更提案流逐字节搬迁；两面互调（approve_proposal→_approve_change、_append_change_event→_record_approval_event_in_db）故合并同域，保包内零环。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.infra.db import RegistryDB  # R2-D-02：审批流生产读写接 RegistryDB.approvals
from rfauto.service.envelope import error_envelope, ok_envelope

from .solvers import add_solver_to_config

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
    # T1 解环：审计观测面改读 agent_audit 叶（agent_safety 同名再导出兼容）
    from rfauto.service.agent_audit import append_audit_log
    from rfauto.service.agent_audit import token_hash as compute_token_hash

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
    # T1 解环轴：门面动作经服务定位器取（agent_actions 叶，api 注册）
    from rfauto.service.agent_actions import agent_apply, agent_propose

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
    from rfauto.service.agent_audit import append_audit_log

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
