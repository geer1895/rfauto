"""campaign_queue_daemon：campaign 排队执行的后台常驻进程面（2026-10-08）。

登记语义（多机协同尾程项 11，排队执行第三块）：**发射后不等**——
常驻轮询队列、按资源日历窗与许可预检逐项发射、状态可查。本模块承担：

- **tick 单步纯函数**（:func:`queue_tick`）：读队列→日历窗判定→license
  预检→发射→状态回写（新状态由返回值交付，落盘归调用方单点承担）；
  时钟/日历/预检/队列扫描/发射器全部注入缝（全 fake 可测，#139）；
- **队列形态单源复用**：队列=扫描根下战役计划（``campaign.plan.json``，
  与 ui ``api_campaign_queue``/``list_campaign_plans`` 同一口径），零新
  队列格式；item 身份=计划绝对路径指纹（跨重启稳定）；
- **发射单源复用**：executor 既有发射入口
  :func:`rfauto.service.campaign_executor.run_campaign` 的**进程级薄包装**
  （子进程 ``python -m rfauto.cli.main campaign run <plan> --resume
  --json``，发射后不等；verdict 回读以 campaign.plan.json 为准——计划
  文件自带的 plan 级 ``"remote"``/``"hfss_batch"`` 声明经既有路由缝照常
  生效，本面不重复实现任何 stage 路由）。被发射的是**真注册 CLI 命令**
  ``campaign run``，非 plan stage 的纸面 entry——executor"禁 shell 出
  entry"红线（其 kind 无对应 CLI 命令）不适用；
- **判定门序**（逐项发射、不硬打）：
  1. 日历窗（remote_scheduler_service.calendar_launch_view 三态
     open/risk/blocked）：blocked=本 tick 不发射（fail-skip，下 tick 重探，
     项**不**记永久 skip——SKIP=inconclusive 续跑重探同源）；risk=
     照发但风险落账（overnight 队列合法用例）；
  2. license 预检（remote_service.license_preflight）：仅对声明了
     license 消耗面（stage ``license_gated``/``adapter=="hfss"``）的计划
     咨询——verdict=PASS 照发；SKIP（无登记机器=本地求解世界，守卫自身
     契约"本地路径不受影响"）照发 fail-open；其余（FAIL=license 端口
     不通）本 tick 不发射下 tick 重探（fail-skip 同款）；
  3. 单飞约束：同刻至多一个本守护发射的在途战役（#261 机器互斥意识，
     v1 不做并发名额面）——在途未收尾则本 tick 只观察不发射。

**幂等与崩溃续跑**：状态 JSON 原子落盘（:func:`save_queue_state`，同目录
临时文件+os.replace，半写崩溃态不落正式档；:func:`default_queue_state_path`，
runs 双根收敛惯例）；item 按 id 记账，status ∈ launched/终态**永不重发**；
已发射项的终态回读自 campaign.plan.json verdict（COMPLETE/PARTIAL/
ABORTED 词表与 campaign_manager.apply_event 同源）。Popen→落账之间崩溃
的极小窗口可能重发同一战役——run_campaign 的 run 实例锁（同 run_dir
占即拒）兜底第二实例，v1 如实注记不做事务化。**单飞不逃逸**：在途
（launched）账目的计划文件瞬时不可读/被移走时，该陈账照常阻塞本 tick
发射（否则在途项隐身一瞬第二项上位=双战役并发；保守代价=计划永久消失
时单飞停摆，状态档可见人工处置）。

诚实边界（#122 家法）：verdict=RUNNING 但非本守护发射的战役记
``external_running`` 只观察不接管（人工在跑的面不劫持）；子进程死亡而
plan verdict 停留 RUNNING 的孤儿态 v1 不做 pid 存活探测（如实留档，
followUp）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "DEFAULT_INTERVAL_S",
    "ITEM_EXTERNAL",
    "ITEM_LAUNCHED",
    "QUEUE_DAEMON_SCHEMA",
    "QUEUE_STATE_DIRNAME",
    "QUEUE_STATE_FILE",
    "default_queue_state_path",
    "item_id_of",
    "load_queue_state",
    "queue_status_view",
    "queue_tick",
    "run_queue_daemon",
    "save_queue_state",
    "scan_queue",
]

#: 状态文件 schema 版本（不一致=整档弃用重新起步，防跨版本静默误读）。
QUEUE_DAEMON_SCHEMA = "rfauto-campaign-queue-daemon-v1"

#: 状态目录/文件名（runs/campaign_queue/queue_state.json，双根收敛）。
QUEUE_STATE_DIRNAME = "campaign_queue"
QUEUE_STATE_FILE = "queue_state.json"

#: 常驻轮询缺省间隔（秒）。
DEFAULT_INTERVAL_S = 60.0

#: item 记账态（词表）。launched=本守护已发射在途；external_running=他人
#: 在跑（只观察不接管）；done/partial/aborted/launch_failed=终态不重发。
ITEM_QUEUED = "queued"
ITEM_LAUNCHED = "launched"
ITEM_EXTERNAL = "external_running"
ITEM_DONE = "done"
ITEM_PARTIAL = "partial"
ITEM_ABORTED = "aborted"
ITEM_LAUNCH_FAILED = "launch_failed"

#: 终态集合（永不重发）。
ITEM_TERMINAL = (ITEM_DONE, ITEM_PARTIAL, ITEM_ABORTED, ITEM_LAUNCH_FAILED)

#: plan verdict → item 记账态（campaign_manager.apply_event/run_campaign
#: 词表同源：COMPLETE 全done；PARTIAL=死胡同全aborted 无 failed；
#: ABORTED=含 failed。verdict=RUNNING 不在此表——按记账态分派）。
_VERDICT_TERMINAL: dict[str, str] = {
    "COMPLETE": ITEM_DONE,
    "PARTIAL": ITEM_PARTIAL,
    "ABORTED": ITEM_ABORTED,
}


def default_queue_state_path() -> Path:
    """状态缺省路径：``runs/campaign_queue/queue_state.json``（runs 双根
    收敛惯例——infra.runs_paths.resolve_runs_dir，chdir 子目录不分叉）。"""
    from rfauto.infra.runs_paths import resolve_runs_dir

    return resolve_runs_dir(
        Path("runs") / QUEUE_STATE_DIRNAME / QUEUE_STATE_FILE)


def item_id_of(plan_path: str | Path) -> str:
    """计划路径 → item 身份（normcase 绝对路径 sha1 前 12 位；跨重启稳定
    ——幂等记账键。normcase=Windows 大小写/分隔符免疫，POSIX 恒等无害）。"""
    normalized = os.path.normcase(os.path.abspath(str(plan_path)))
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _plan_license_gated(plan: dict[str, Any]) -> bool:
    """计划是否声明 license 消耗面（stage license_gated/adapter==hfss；
    ui ``_campaign_remote_block`` 候选口径同源）。"""
    for stage in plan.get("stages") or []:
        stage = stage if isinstance(stage, dict) else {}
        if stage.get("license_gated") or str(stage.get("adapter") or "") == "hfss":
            return True
    return False


def scan_queue(root: str | Path = "runs") -> list[dict[str, Any]]:
    """扫描根 → 队列条目（只读；list_campaign_plans+load_plan 单源复用）。

    条目形态：``{"item_id", "plan_path", "model", "verdict", "n_stages",
    "license_gated"}``；损坏计划逐条跳过（list_campaign_plans #105 口径），
    plan 读回失败同样跳过不猜。零发射零写入。
    """
    from rfauto.service.campaign_manager import list_campaign_plans, load_plan

    listing = list_campaign_plans(root)
    entries: list[dict[str, Any]] = []
    for item in listing.get("campaigns") or []:
        loaded = load_plan(item.get("path") or "")
        if not loaded.get("ok"):
            continue
        plan = loaded.get("plan") or {}
        plan_path = str(loaded.get("path") or item.get("path") or "")
        entries.append({
            "item_id": item_id_of(plan_path),
            "plan_path": plan_path,
            "model": str(plan.get("model") or ""),
            "verdict": str(plan.get("verdict") or ""),
            "n_stages": len(plan.get("stages") or []),
            "license_gated": _plan_license_gated(plan),
        })
    return entries


# ─── 生产适配薄包装（模块级，便于单测钉通道，#139）────────────────────────────

def _calendar_launch_view() -> dict[str, Any]:
    """资源日历发射窗判定薄包装（remote_scheduler_service 单源；#139）。"""
    from rfauto.service.remote_scheduler_service import calendar_launch_view

    return calendar_launch_view()


def _license_preflight(machine: str | None) -> dict[str, Any]:
    """license 预检薄包装（remote_service 单源；#139）。"""
    from rfauto.service.remote_service import license_preflight

    return license_preflight(machine)


def _launch_cmd(plan_path: str, python_exe: str | None = None) -> list[str]:
    """发射命令构造（纯函数）：``python -m rfauto.cli.main campaign run
    <plan> --resume --json``（--resume=断点续跑语义期刊内建）。"""
    return [python_exe or sys.executable, "-m", "rfauto.cli.main",
            "campaign", "run", str(plan_path), "--resume", "--json"]


def _launch_campaign_subprocess(plan_path: str) -> dict[str, Any]:
    """发射薄包装：run_campaign 的进程级形态（**发射后不等**）。

    命令构造单源 :func:`_launch_cmd`；stdout/stderr 追加落
    ``<campaign 目录>/queue_daemon_launch.log``。
    返回 ``dict(ok, pid, cmdline, log_path)`` / ``dict(ok=False, error)``。
    """
    plan = Path(plan_path)
    log_path = plan.parent / "queue_daemon_launch.log"
    cmd = _launch_cmd(plan_path)
    try:
        # 句柄移交子进程后 finally 显式关（Popen 句柄传递惯例，非泄漏）
        log_fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    except OSError as exc:
        return dict(ok=False, error=f"发射日志不可写: {exc}")
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                   | subprocess.DETACHED_PROCESS)
    try:
        proc = subprocess.Popen(
            cmd, stdout=log_fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, **kwargs)
    except OSError as exc:
        return dict(ok=False, error=f"子进程发射失败: {exc}")
    finally:
        # 父进程不持句柄（子进程继承句柄后即可关；发射后不等）
        with contextlib.suppress(OSError):
            log_fh.close()
    return dict(ok=True, pid=int(proc.pid), cmdline=cmd, log_path=str(log_path))


# ─── 状态落盘（崩溃续跑载体）─────────────────────────────────────────────────

def default_state(root: str = "runs", machine: str | None = None) -> dict[str, Any]:
    """空白状态档（schema 版本化；items 空、无 tick 历史）。"""
    return {
        "schema": QUEUE_DAEMON_SCHEMA,
        "root": str(root),
        "machine": machine,
        "items": {},
        "last_tick_at": None,
        "last_actions": [],
        "updated_at": None,
    }


def load_queue_state(path: str | Path) -> dict[str, Any]:
    """读状态档（缺文件/损坏/schema 不符=空白档重新起步，#105 不炸不误读）。"""
    p = Path(path)
    if not p.is_file():
        return default_state()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default_state()
    if not isinstance(data, dict) or data.get("schema") != QUEUE_DAEMON_SCHEMA:
        return default_state()
    if not isinstance(data.get("items"), dict):
        data["items"] = {}
    return data


def save_queue_state(state: dict[str, Any], path: str | Path) -> str:
    """状态档落盘（原子写：同目录临时文件 + ``os.replace``——半写崩溃态
    不会落在正式状态档上；load 侧损坏=空白档重新起步的兜底仍是最后一
    道，但记账载体自身不再制造撕裂面）。返回路径文本。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1,
                              sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, p)
    return str(p)


def queue_status_view(state: dict[str, Any]) -> dict[str, Any]:
    """状态档 → 人读摘要（计数按记账态；状态可查面，零额外 I/O）。"""
    items = state.get("items") or {}
    by_status: dict[str, int] = {}
    for rec in items.values():
        key = str((rec or {}).get("status") or "?")
        by_status[key] = by_status.get(key, 0) + 1
    in_flight = sum(1 for rec in items.values()
                    if (rec or {}).get("status") == ITEM_LAUNCHED)
    return {"schema": str(state.get("schema") or ""),
            "n_items": len(items), "by_status": by_status,
            "in_flight": in_flight,
            "last_tick_at": state.get("last_tick_at")}


# ─── tick 单步纯函数 ─────────────────────────────────────────────────────────

def _new_record(entry: dict[str, Any], status: str, now: float, **extra: Any
                ) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "item_id": entry.get("item_id"),
        "plan_path": entry.get("plan_path"),
        "model": entry.get("model"),
        "status": status,
        "launched_at": None,
        "pid": None,
        "log_path": None,
        "verdict_seen": entry.get("verdict") or "",
        "reason": "",
        "updated_at": now,
    }
    rec.update(extra)
    return rec


def queue_tick(
    state: dict[str, Any] | None,
    *,
    now_fn: Callable[[], float] | None = None,
    calendar_fn: Callable[[], dict[str, Any]] | None = None,
    preflight_fn: Callable[[str | None], dict[str, Any]] | None = None,
    queue_fn: Callable[[str], list[dict[str, Any]]] | None = None,
    launcher_fn: Callable[[str], dict[str, Any]] | None = None,
    license_gate: bool | None = None,
    root: str = "runs",
    machine: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """tick 单步：读队列→日历窗→license 预检→发射→状态回写（纯函数）。

    全部副作用经注入缝（now_fn/calendar_fn/preflight_fn/queue_fn/
    launcher_fn，缺省=生产适配薄包装）；输入 state 不改性，新状态由返回
    值交付（落盘归调用方——:func:`run_queue_daemon` 每 tick 单点写）。

    Returns
    -------
    (actions, new_state)
    actions=本 tick 动作清单（词表：scan/launch/launch_failed/
    in_flight_wait/calendar_blocked/calendar_risk/license_pass/
    license_skip_open/license_skip/record_terminal/observe_external/
    refresh_terminal/tick_error/state_save_error）；
    new_state=回写后的完整状态档（同 :func:`default_state` 形态）。
    """
    now = float((now_fn or time.time)())
    cal_fn = calendar_fn or _calendar_launch_view
    pre_fn = preflight_fn or _license_preflight
    q_fn = queue_fn or scan_queue
    l_fn = launcher_fn or _launch_campaign_subprocess

    new_state = default_state(root=root, machine=machine)
    prev_items = dict((state or {}).get("items") or {})
    items: dict[str, Any] = {}
    actions: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    in_flight: dict[str, Any] | None = None
    in_flight_unseen = False  # 在途账目本 tick 扫描未命中（计划瞬时不可读）

    entries = list(q_fn(root))
    for entry in entries:
        iid = str(entry.get("item_id") or "")
        verdict = str(entry.get("verdict") or "")
        prev = prev_items.get(iid)
        terminal_status = _VERDICT_TERMINAL.get(verdict)
        if prev is None:
            if terminal_status is not None:
                rec = _new_record(entry, terminal_status, now,
                                  reason=f"plan verdict={verdict}（先于守护的终态，只记账不发射）")
                items[iid] = rec
                actions.append({"action": "record_terminal", "item_id": iid,
                                "status": terminal_status,
                                "plan": entry.get("plan_path")})
            elif verdict == "RUNNING":
                rec = _new_record(entry, ITEM_EXTERNAL, now,
                                  reason="verdict=RUNNING 但非本守护发射（只观察不接管）")
                items[iid] = rec
                actions.append({"action": "observe_external", "item_id": iid,
                                "plan": entry.get("plan_path")})
            else:
                candidates.append(entry)  # 未记账无终态=排队候选
            continue
        prev = dict(prev if isinstance(prev, dict) else {})
        if prev.get("status") == ITEM_LAUNCHED:
            if terminal_status is not None:
                prev["status"] = terminal_status
                prev["verdict_seen"] = verdict
                prev["reason"] = f"verdict={verdict}（发射后终态回读）"
                prev["updated_at"] = now
                items[iid] = prev
                actions.append({"action": "refresh_terminal", "item_id": iid,
                                "status": terminal_status,
                                "plan": entry.get("plan_path")})
                continue
            prev["verdict_seen"] = verdict
            prev["updated_at"] = now
            items[iid] = prev
            in_flight = in_flight or prev  # 单飞约束：在途未收尾不发射下一项
            continue
        items[iid] = prev  # 终态/external 记账保留（永不重发）
        if terminal_status is not None and prev.get("status") != terminal_status:
            # 人工路径的终态与记账不一致（如 launch_failed 后人工跑完）——
            # 以 plan verdict 权威收口（防陈账）。
            prev["status"] = terminal_status
            prev["verdict_seen"] = verdict
            prev["reason"] = f"plan verdict={verdict}（权威收口）"
            prev["updated_at"] = now
            actions.append({"action": "refresh_terminal", "item_id": iid,
                            "status": terminal_status,
                            "plan": entry.get("plan_path")})

    actions.insert(0, {"action": "scan", "root": str(root),
                       "n_campaigns": len(entries),
                       "n_candidates": len(candidates)})

    # 单飞不逃逸（#261 机器互斥意识）：本 tick 扫描未命中的陈账里若有
    # 在途（launched）记录——计划文件瞬时不可读/被移走——同样阻塞本 tick
    # 发射（否则在途项隐身的一瞬第二项上位=双战役并发）。保守代价：计划
    # 永久消失时单飞停摆（不发射新项），v1 认为比双发射安全（陈账可见
    # 于状态档，人工处置面）。
    survivors = prev_items_survivors(prev_items, entries)
    if in_flight is None:
        for rec_s in survivors.values():
            if isinstance(rec_s, dict) and rec_s.get("status") == ITEM_LAUNCHED:
                in_flight = rec_s
                in_flight_unseen = True
                break

    if in_flight is not None:
        actions.append({"action": "in_flight_wait",
                        "item_id": in_flight.get("item_id"),
                        "plan": in_flight.get("plan_path"),
                        "reason": "单飞约束：在途战役未收尾，本 tick 不发射"
                                  + ("（计划本 tick 扫描未命中——在途陈账"
                                     "照常阻塞，单飞不逃逸）"
                                     if in_flight_unseen else "")})
    elif candidates:
        entry = candidates[0]
        # 门 1：资源日历窗（blocked=本 tick 不发射，项不记永久 skip——
        # SKIP=inconclusive 续跑重探同源；risk=照发风险落账）
        try:
            calendar = cal_fn()
        except Exception as exc:  # #105：日历观测面异常降级恒可发不阻塞
            calendar = {"loaded": False, "state": "open", "launchable": True,
                        "reason": f"日历视图异常降级恒可发: {type(exc).__name__}"}
        cal_state = str(calendar.get("state") or "open")
        if cal_state == "blocked":
            actions.append({"action": "calendar_blocked",
                            "item_id": entry.get("item_id"),
                            "windows_hit": calendar.get("windows_hit"),
                            "reason": str(calendar.get("reason") or "")})
        else:
            if cal_state == "risk":
                actions.append({"action": "calendar_risk",
                                "item_id": entry.get("item_id"),
                                "windows_hit": calendar.get("windows_hit"),
                                "reason": str(calendar.get("reason") or "")})
            # 门 2：license 预检（仅 license 消耗面计划咨询，或显式
            # license_gate=True 强制；PASS 照发 / SKIP fail-open 照发 /
            # FAIL fail-skip 下 tick 重探——同款不硬打）
            gate_open = True
            applicable = (license_gate if license_gate is not None
                          else bool(entry.get("license_gated")))
            if applicable:
                try:
                    pf = pre_fn(machine)
                except Exception as exc:  # #105：预检异常降级照发不阻塞
                    pf = {"verdict": "SKIP",
                          "reason": f"预检异常降级（{type(exc).__name__}）"}
                verdict_pf = str(pf.get("verdict") or "")
                if verdict_pf == "PASS":
                    actions.append({"action": "license_pass",
                                    "item_id": entry.get("item_id"),
                                    "verdict": verdict_pf})
                elif verdict_pf == "SKIP":
                    # 守卫自身契约：无登记机器=本地路径不受影响 → fail-open
                    actions.append({"action": "license_skip_open",
                                    "item_id": entry.get("item_id"),
                                    "verdict": verdict_pf,
                                    "reason": str(pf.get("reason") or "")})
                else:
                    gate_open = False
                    actions.append({"action": "license_skip",
                                    "item_id": entry.get("item_id"),
                                    "verdict": verdict_pf,
                                    "reason": str(pf.get("reason") or "")})
            if gate_open:
                # 门 3：发射（fire-and-forget；记账 launched 永不重发）
                launched = l_fn(str(entry.get("plan_path") or ""))
                iid = str(entry.get("item_id") or "")
                if launched.get("ok"):
                    items[iid] = _new_record(
                        entry, ITEM_LAUNCHED, now,
                        launched_at=now,
                        pid=launched.get("pid"),
                        log_path=launched.get("log_path"),
                        reason="queue-daemon 发射（子进程 campaign run --resume）")
                    actions.append({"action": "launch", "item_id": iid,
                                    "plan": entry.get("plan_path"),
                                    "pid": launched.get("pid")})
                else:
                    items[iid] = _new_record(
                        entry, ITEM_LAUNCH_FAILED, now,
                        reason=f"发射失败: {launched.get('error')}")
                    actions.append({"action": "launch_failed", "item_id": iid,
                                    "plan": entry.get("plan_path"),
                                    "error": str(launched.get("error") or "")})

    new_state["items"] = {**survivors, **items}
    new_state["last_tick_at"] = now
    new_state["last_actions"] = actions
    new_state["updated_at"] = now
    return actions, new_state


def prev_items_survivors(prev_items: dict[str, Any],
                         entries: list[dict[str, Any]]) -> dict[str, Any]:
    """本 tick 扫描未命中（计划目录被移走）的陈账保留（零伪造零删除）。"""
    seen = {str(e.get("item_id") or "") for e in entries}
    return {iid: rec for iid, rec in prev_items.items()
            if iid not in seen and isinstance(rec, dict)}


# ─── 常驻执行体（CLI 拉起面；tick 落盘/单例锁/优雅退出在此）───────────────────

_DAEMON_LOCK_SUFFIX = ".lock"


def run_queue_daemon(
    *,
    root: str = "runs",
    machine: str | None = None,
    license_gate: bool | None = None,
    interval_s: float = DEFAULT_INTERVAL_S,
    once: bool = False,
    state_path: str | Path | None = None,
    log: Callable[[dict[str, Any]], None] | None = None,
    now_fn: Callable[[], float] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
    calendar_fn: Callable[[], dict[str, Any]] | None = None,
    preflight_fn: Callable[[str | None], dict[str, Any]] | None = None,
    queue_fn: Callable[[str], list[dict[str, Any]]] | None = None,
    launcher_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """常驻执行体：while 循环逐 tick（读队列→门→发射→状态落盘）+优雅退出。

    - ``once=True``：单步模式（测试/cron），一 tick 即返；
    - 单例锁：状态路径旁 ``.lock``（dag_runner.acquire_lock O_CREAT|O_EXCL
      +陈锁接管式样，max_wait_s=0 占即拒）——第二实例如实 error 信封；
    - 优雅退出：SIGTERM 处理器置停旗（注册失败平台 best-effort #105）+
      KeyboardInterrupt 捕获——当前 tick 完成并落账后退出；
    - 注入缝同 :func:`queue_tick`（sleep_fn/stop_check 供测试免真睡）。
    """
    sp = Path(state_path) if state_path is not None else default_queue_state_path()
    from rfauto.pipeline.dag_runner import acquire_lock

    lock_path = sp.parent / (sp.name + _DAEMON_LOCK_SUFFIX)
    holder = acquire_lock("campaign_queue_daemon", lock_path, max_wait_s=0)
    if holder is None:
        return error_envelope(
            [f"另一 campaign queue-daemon 实例持有锁: {lock_path}"
             "（单例约束，防双发射）"])
    released = False

    def _release() -> None:
        nonlocal released
        if not released:
            released = True
            with contextlib.suppress(OSError):
                lock_path.unlink()

    stop = {"requested": False}

    def _on_term(signum: int, frame: Any) -> None:
        stop["requested"] = True

    with contextlib.suppress(ValueError, OSError):
        signal.signal(signal.SIGTERM, _on_term)

    emitted: dict[str, Any] = {}
    n_ticks = 0
    try:
        state = load_queue_state(sp)
        sleeper = sleep_fn or time.sleep
        while True:
            try:
                actions, state = queue_tick(
                    state, now_fn=now_fn, calendar_fn=calendar_fn,
                    preflight_fn=preflight_fn, queue_fn=queue_fn,
                    launcher_fn=launcher_fn, license_gate=license_gate,
                    root=root, machine=machine)
            except Exception as exc:  # #105：单 tick 异常不拆循环，留痕降级
                actions = [{"action": "tick_error",
                            "error": f"{type(exc).__name__}: {exc}"}]
                state = state if isinstance(state, dict) else load_queue_state(sp)
            state["last_actions"] = actions
            try:
                save_queue_state(state, sp)
            except OSError as exc:  # 落账失败留痕续转（幂等账本带缺口如实）
                actions.append({"action": "state_save_error",
                                "error": f"{type(exc).__name__}: {exc}"})
                state["last_actions"] = actions
            n_ticks += 1
            emitted = {"tick": n_ticks, "actions": actions,
                       "status": queue_status_view(state),
                       "state_path": str(sp)}
            if log is not None:
                # 结构化 tick 流（dict 载荷：渲染归调用方——前端只
                # 渲染口径；log 抛异常不拆循环，#105 观测面不阻塞主路径）
                with contextlib.suppress(Exception):
                    log(dict(emitted))
            if once:
                break
            if stop["requested"] or (stop_check is not None and stop_check()):
                emitted["stopped_gracefully"] = True
                break
            try:
                sleeper(max(0.1, float(interval_s)))
            except (KeyboardInterrupt, InterruptedError):
                emitted["stopped_gracefully"] = True
                break
    except KeyboardInterrupt:
        emitted["stopped_gracefully"] = True
    finally:
        _release()
    return ok_envelope(once=once, ticks=n_ticks,
                       root=str(root), state_path=str(sp),
                       final=emitted, items=queue_status_view(state))
