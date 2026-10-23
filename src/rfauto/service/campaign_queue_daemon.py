"""campaign_queue_daemon：campaign 排队执行的后台常驻进程面（UX-B7，2026-10-08）。

登记语义（交接书尾程项 11，UX-B6/E62 之上的第三块）：**发射后不等**——
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
- **判定门序**（E62 同款语义，逐项发射、不硬打）：
  0. 依赖门（aurora_j W2-S5）：计划级 ``depends_on`` 前置未全终态=本
     tick 不发射（pass-over——就绪候选照常上位，坏账降级阻塞不拆
     tick，详见文末"队列依赖门控"段）；
  1. 日历窗（remote_scheduler_service.calendar_launch_view 三态
     open/risk/blocked）：blocked=本 tick 不发射（fail-skip，下 tick 重探，
     项**不**记永久 skip——E62 SKIP=inconclusive 续跑重探同源）；risk=
     照发但风险落账（overnight 队列合法用例）；
  2. license 预检（remote_service.license_preflight）：仅对声明了
     license 消耗面（stage ``license_gated``/``adapter=="hfss"``）的计划
     咨询——verdict=PASS 照发；SKIP（无登记机器=本地求解世界，守卫自身
     契约"本地路径不受影响"）照发 fail-open；其余（FAIL=license 端口
     不通）本 tick 不发射下 tick 重探（E62 fail-skip 同款）；
  3. 单飞约束：同刻至多一个本守护发射的在途战役（#261 机器互斥意识，
     v1 不做并发名额面）——在途未收尾则本 tick 只观察不发射。

**幂等与崩溃续跑**：状态 JSON 原子落盘（:func:`save_queue_state`，同目录
临时文件+os.replace，半写崩溃态不落正式档；:func:`default_queue_state_path`，
runs 双根收敛惯例）；item 按 id 记账，status ∈ queued/launched/终态**永不
重发**（queued=排队候选预登记，审查 A3 P2-2①：状态可查面看得见排队项，
``queue_status_view.by_status`` 含 queued）；已发射项的终态回读自
campaign.plan.json verdict（COMPLETE/PARTIAL/ABORTED 词表与
campaign_manager.apply_event 同源）。Popen→落账之间崩溃的极小窗口可能重发
同一战役——run_campaign 的 run 实例锁（同 run_dir 占即拒）兜底第二实例，
v1 如实注记不做事务化。**单飞不逃逸**：在途（launched）账目的计划文件瞬时
不可读/被移走时，该陈账照常阻塞本 tick 发射（否则在途项隐身一瞬第二项上位
=双战役并发；保守代价=计划永久消失时单飞停摆，状态档可见人工处置）。

**陈账生命周期**（审查 A3 P2-2②）：扫描未命中的陈账（计划目录被人工删除/
移走）按态分派——launched 无条件保留（单飞阻塞语义，人工处置面）；其余态
（external/queued/终态）按账龄 TTL 回收（:data:`SURVIVOR_TTL_S_DEFAULT`），
防常驻月级运行状态档无界增长；回收经 ``recycle_stale`` 动作留痕不静默。

诚实边界（#122 家法）：verdict=RUNNING 但非本守护发射的战役记
``external_running`` 只观察不接管（人工在跑的面不劫持）；子进程死亡而
plan verdict 停留 RUNNING 的孤儿态 v1 不做 pid 存活探测（如实留档，
followUp）。

**队列阻塞原因人读透出（aurora_i W2-S3，采纳 #2；hfssq blocked_reason
"仅变化落账"范式的思想重实现）**：排队项每 tick 经 :func:`merge_blocked_reason`
携带结构化阻塞块 ``rec["blocked"] = {code, detail, since, updated_at}``——
code ∈ :data:`BLOCK_SOLO`/:data:`BLOCK_CALENDAR`/:data:`BLOCK_LICENSE`/
:data:`BLOCK_AHEAD`；**变化才落账**：同 (code, detail) 不改写不刷新
（``since`` 保持首次阻塞时刻，等待时长由读侧按 ``now - since`` 即时计算，
人读一句话经 :func:`blocked_text_of` 组装——"等 license：…（已等 12
分钟）"形态）；换因/解除才写账。读侧 :func:`queue_blocks_index` 供
``/api/campaign_queue`` 合流透出（前端 i18n 按 code 另有 en 对照，
服务层 ``text`` 为 zh 单源兜底）。

**队列依赖门控（aurora_j W2-S5；b3 的 depends_on 由 v2 落地）**：计划级
可选键 ``depends_on``（前置任务 item_id 列表，同队列内引用）经
:func:`scan_queue` 入条目；候选发射前先过依赖门——任一前置未达终态
（:data:`ITEM_TERMINAL`）→ 本 tick 不发射（新码 :data:`BLOCK_DEPS`，
"变化才落账"同 W2-S3 范式，detail=首个未满足前置 ``<id>（<状态>）``,
状态变化换因保 ``since``）；前置全终态即放行。**失败如实传播不自动
取消**（#122）：前置 launch_failed/aborted 也是终态，依赖方照常获得
发射资格、成败由自身战役判定（v1 记账词表无 skip 态，不新增）。入队
校验 :func:`validate_depends_on`（写侧契约：引用不存在/依赖环 →
ValueError，环路径进文案）；守护 tick 内坏账项（环/无账引用）降级为
BLOCK_DEPS 阻塞账不拆 tick（#105，单条坏计划不瘫痪全队列）。依赖未
满足候选**不阻塞队头**（pass-over）：就绪候选照常上位发射，与
:data:`BLOCK_AHEAD` 的排队序互补。缺字段=零行为变化（硬验收）。

**失败诊断包触发（aurora_i W2-S3，采纳 #3）**：``launch_failed`` 或本守护
已发射战役终态回读为 ABORTED/PARTIAL 时，经 ``failure_context_fn`` 注入缝
落失败快照（:mod:`rfauto.service.failure_context_service` 单源，案发现场
语义）；纯函数缺省 ``None``=零副作用，生产执行体
:func:`run_queue_daemon` 缺省接真包。先于守护的终态（record_terminal/
排队期他人代跑收口）不触发——非本守护经手的失败不越权写他人 run 目录。

**长跑防卡死对冲（aurora_i W3-S3，服务器管控采纳 #1；hfss-dispatch
ADR-0007 hedged scheduling 的思想轻量改写——不搬其"多副本赛马"形态）**：
W2-S3 失败诊断只盖终态（ABORTED/PARTIAL）与发射失败，**"卡死但未死"
（子进程在、plan verdict 停留 RUNNING、无任何进展）零覆盖**——单飞位被
无限占用、队列停摆、无人知晓。对冲=在途项经 :func:`default_progress_ts`
进展探针（计划文件+发射日志的最新 mtime，注入缝 ``progress_fn`` 可换
心跳档）判"无进展时长 ≥ 阈值"，触发时**缺省只告警**：hedge 账
（``rec["hedge"]``，变化才落账同 W2-S3 范式）+ ``hedge_alert`` 动作落
tick 事件流 + 读侧 :func:`queue_hedge_index` 经 ``/api/campaign_queue``
透出（``queue_hedge`` 字段）。**配置全走 env、缺省关闭=零行为变化**
（硬验收）：``RFAUTO_QUEUE_HEDGE_STALL_S``（秒，未设/非法/≤0=关）启监测；
``RFAUTO_QUEUE_HEDGE_RELAUNCH``（"1/true/yes/on"）才开自动重发——#261
互斥红线下自动重发有双跑风险，故做成显式开关且每项硬帽至多一次
（:data:`_HEDGE_RELAUNCH_CAP`；发射走同一 ``launcher_fn`` 缝 ``--resume``
续跑，原进程若仍持 run 实例锁则新实例占即拒速败=安全侧失败，不杀原
进程树——#157 家族远杀 hazard 不引入）。探针读不到证据（文件全缺/异常）
=unknown 保守不告警（#105/#122：宁缺勿判）；本 tick 扫描未命中的在途
陈账同样不判（计划不可读分不清"移走"与"卡死"）。进展恢复（无进展时长
回落阈值下）摘账落 ``hedge_recovered``；终态随态清扫。
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
    "BLOCK_AHEAD",
    "BLOCK_CALENDAR",
    "BLOCK_DEPS",
    "BLOCK_LICENSE",
    "BLOCK_NONE",
    "BLOCK_SOLO",
    "DEFAULT_INTERVAL_S",
    "HEDGE_CODE_STALL",
    "HEDGE_RELAUNCH_ENV",
    "HEDGE_STALL_S_ENV",
    "ITEM_EXTERNAL",
    "ITEM_LAUNCHED",
    "QUEUE_DAEMON_SCHEMA",
    "QUEUE_STATE_DIRNAME",
    "QUEUE_STATE_FILE",
    "blocked_text_of",
    "default_progress_ts",
    "default_queue_state_path",
    "env_hedge_relaunch",
    "env_hedge_stall_s",
    "hedge_text_of",
    "item_id_of",
    "load_queue_state",
    "merge_blocked_reason",
    "queue_blocks_index",
    "queue_hedge_index",
    "queue_status_view",
    "queue_tick",
    "run_queue_daemon",
    "save_queue_state",
    "scan_queue",
    "validate_depends_on",
]

#: 状态文件 schema 版本（不一致=整档弃用重新起步，防跨版本静默误读）。
QUEUE_DAEMON_SCHEMA = "rfauto-campaign-queue-daemon-v1"

#: 状态目录/文件名（runs/campaign_queue/queue_state.json，双根收敛）。
QUEUE_STATE_DIRNAME = "campaign_queue"
QUEUE_STATE_FILE = "queue_state.json"

#: 常驻轮询缺省间隔（秒）。
DEFAULT_INTERVAL_S = 60.0

#: 扫描未命中陈账（计划目录被移走）的回收账龄缺省（秒，7 天）。仅作用于
#: 非 launched 态（external/queued/终态）；launched 陈账永久保留（单飞
#: 阻塞语义+人工处置面，见模块 docstring"陈账生命周期"）。
SURVIVOR_TTL_S_DEFAULT = 7 * 86400.0

#: item 记账态（词表）。queued=排队候选（已登记待发射）；launched=本守护
#: 已发射在途；external_running=他人在跑（只观察不接管）；
#: done/partial/aborted/launch_failed=终态不重发。
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

# ─── 队列阻塞原因（aurora_i W2-S3 采纳 #2；人读透出+变化才落账）───────────────

#: 阻塞码词表（机读；"" = 未阻塞/已解除）。
BLOCK_NONE = ""
BLOCK_SOLO = "solo_wait"            # 单飞互斥：在途战役未收尾（#261 意识）
BLOCK_CALENDAR = "calendar_blocked"  # 资源日历窗 blocked（本 tick 不发射）
BLOCK_LICENSE = "license_wait"      # license 预检未过（fail-skip 下 tick 重探）
BLOCK_AHEAD = "queued_ahead"        # 前序候选未发射（排队等轮次）
BLOCK_DEPS = "deps_blocked"         # 依赖门：前置任务未达终态（W2-S5）

#: 服务层 zh 人读模板单源（前端 i18n 按 code 另有 en 对照；detail/n_ahead
#: 为占位参数——detail 是 API 动态数据，消费方照旧 esc，禁拼进壳文案）。
_BLOCK_TEXT_TEMPLATES: dict[str, str] = {
    BLOCK_SOLO: "等单飞位：在途战役未收尾（{detail}）",
    BLOCK_CALENDAR: "等日历窗：{detail}",
    BLOCK_LICENSE: "等 license：{detail}",
    BLOCK_AHEAD: "排队中：前面还有 {n_ahead} 个候选",
    BLOCK_DEPS: "等依赖：{detail}",
}

#: 前置记账态 → zh 短语（依赖等待 detail 用；终态不进 detail——终态=放行）。
_DEP_STATUS_TEXT: dict[str, str] = {
    ITEM_QUEUED: "排队中",
    ITEM_LAUNCHED: "在途",
    ITEM_EXTERNAL: "他人在跑",
}

#: 等待时长人读换算秒界（<此值报秒，否则报分钟）。
_BLOCK_WAIT_SEC_LIMIT = 90.0


def _format_waited(waited_s: float, *, label: str = "已等") -> str:
    """等待秒数 → zh 人读时长（<90s 报秒，否则报分钟；负值按 0）。

    ``label`` 换语义头词（对冲面用"已停滞"，缺省"已等"保持既有文案逐
    字节不变——W2-S3 消费方零感知）。
    """
    w = max(0.0, float(waited_s))
    if w < _BLOCK_WAIT_SEC_LIMIT:
        return f"{label} {round(w)} 秒"
    return f"{label} {round(w / 60.0)} 分钟"


def blocked_text_of(
    code: str,
    *,
    detail: str = "",
    waited_s: float | None = None,
    n_ahead: int = 0,
) -> str:
    """阻塞码+细节+等待时长 → 人读一句话（纯函数；zh 单源）。

    形态："等 license：HFSS 许可端口不可达（已等 12 分钟）"；waited_s
    缺省 None=不附等待段（code 未知=返回空串——调用方按 API data 透传
    原文，不猜）。
    """
    tpl = _BLOCK_TEXT_TEMPLATES.get(str(code or ""))
    if tpl is None:
        return ""
    base = tpl.format(detail=str(detail or ""), n_ahead=int(n_ahead))
    if waited_s is None:
        return base
    return f"{base}（{_format_waited(waited_s)}）"


def merge_blocked_reason(
    rec: dict[str, Any],
    code: str,
    *,
    detail: str = "",
    n_ahead: int = 0,
    now: float,
) -> tuple[dict[str, Any], bool]:
    """阻塞块"变化才落账"合并（纯函数，copy-on-write 不改性入参）。

    - 同 (code, detail) 不变 → 原账原样返回（``since`` 保持首次阻塞时刻，
      ``updated_at`` 不推进——同因不刷屏；调用方也就不重写整条记录）；
    - 换因（同码异 detail 或异码）→ 写新 detail，``since`` 保留（同码同
      一段等待期）或重置（异码=新一段阻塞）；``updated_at=now``；
    - 解除（code=BLOCK_NONE）→ 摘除 ``blocked`` 键（终态/发射换账时调）。

    Returns
    -------
    (new_rec, changed)
    changed=True 表示阻塞账面确有变化（调用方可留痕；本守护的状态档
    每 tick 整档重写，"落账"语义收敛在账面字段不空转+读侧等待时长稳定）。
    """
    new_rec = dict(rec)
    prev = new_rec.get("blocked")
    prev = prev if isinstance(prev, dict) else None
    code = str(code or BLOCK_NONE)
    if code == BLOCK_NONE:
        if prev is None:
            return new_rec, False
        new_rec.pop("blocked", None)
        return new_rec, True
    detail = str(detail or "")
    if prev is not None and prev.get("code") == code \
            and prev.get("detail") == detail:
        return new_rec, False  # 同因不刷屏（since/updated_at 原样）
    since = now if (prev is None or prev.get("code") != code) \
        else prev.get("since")
    new_rec["blocked"] = {
        "code": code, "detail": detail, "n_ahead": int(n_ahead),
        "since": since, "updated_at": now,
    }
    return new_rec, True


def queue_blocks_index(
    state: dict[str, Any],
    *,
    now: float | None = None,
) -> dict[str, dict[str, Any]]:
    """状态档 → {item_id: 阻塞块}（读侧人话渲染；``waited_s``/``text``
    即时计算，状态档零冗余存储）。仅 ``status=queued`` 且带阻塞账的项
    入索引——终态/在途项的陈账自动隐身。"""
    ts = time.time() if now is None else float(now)
    out: dict[str, dict[str, Any]] = {}
    for iid, rec in (state.get("items") or {}).items():
        if not isinstance(rec, dict):
            continue
        if rec.get("status") != ITEM_QUEUED:
            continue
        blk = rec.get("blocked")
        if not isinstance(blk, dict) or not blk.get("code"):
            continue
        code = str(blk.get("code") or "")
        try:
            waited = ts - float(blk.get("since") or ts)
        except (TypeError, ValueError):
            waited = 0.0
        detail = str(blk.get("detail") or "")
        n_ahead = int(blk.get("n_ahead") or 0)
        out[str(iid)] = {
            "item_id": str(iid),
            "plan_path": rec.get("plan_path"),
            "code": code,
            "detail": detail,
            "n_ahead": n_ahead,
            "since": blk.get("since"),
            "waited_s": round(max(0.0, waited), 3),
            "text": blocked_text_of(code, detail=detail,
                                    waited_s=max(0.0, waited),
                                    n_ahead=n_ahead),
        }
    return out


# ─── 队列依赖门控（aurora_j W2-S5；depends_on 校验+评估，纯函数）──────────────

def _norm_deps(raw: Any) -> list[str]:
    """``depends_on`` 原始值 → 规范 id 列表（str+strip、去空、去重保序；
    非列表形态=[]。防御面不抛——坏形态按无依赖读，#105 观测不炸主路径）。"""
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for d in raw:
        s = str(d or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def _deps_cycle_texts(entries: list[dict[str, Any]]) -> dict[str, str]:
    """条目集 → {item_id: 依赖环文案}（纯函数；无环=空表）。

    Kahn 剥叶：反复摘除"前置已全解"节点，剩余=卡死集（环成员及其下游
    依赖——两者同样永不满足，共享同一条环路径文案）；DFS 在卡死集内取
    一条实环路径入文案（卡死集每节点必有卡死前置，环必可达）。环路径
    形如 ``a → b → a``（含自身环 ``a → a``）。
    """
    ids = {str(e.get("item_id") or "") for e in entries}
    adj: dict[str, list[str]] = {}
    for e in entries:
        iid = str(e.get("item_id") or "")
        deps = [d for d in _norm_deps(e.get("depends_on")) if d in ids]
        if deps:
            adj[iid] = deps
    removed = ids - set(adj)  # 无依赖条目=天然已解（叶）
    remaining = set(adj)
    changed = True
    while changed and remaining - removed:
        changed = False
        for iid in sorted(remaining - removed):
            if all(d in removed for d in adj.get(iid, ())):
                removed.add(iid)
                changed = True
    stuck = remaining - removed
    if not stuck:
        return {}
    seen_at: dict[str, int] = {}
    path: list[str] = []
    node = sorted(stuck)[0]
    while node not in seen_at:
        seen_at[node] = len(path)
        path.append(node)
        node = next(d for d in adj.get(node, ()) if d in stuck)
    cycle = [*path[seen_at[node]:], node]
    text = f"依赖环 {' → '.join(cycle)}（永不满足）"
    return {iid: text for iid in stuck}


def validate_depends_on(entries: list[dict[str, Any]]) -> None:
    """入队校验（写侧契约，纯函数）：``depends_on`` 引用必须在本队列
    条目集内存在、依赖图无环——违规抛 :class:`ValueError`（逐项明细+
    环路径进文案）。**如实声明：当前 src 内无强制调用点**（写侧 opt-in
    实用函数，计划落盘/UI 入队等写面可先经此校验拒绝，测试面直接
    调用）；守护 tick **不**调用本函数——坏计划在 tick 内降级为
    :data:`BLOCK_DEPS` 阻塞账兜底（见 :func:`queue_tick`，单条坏计划
    不瘫痪整个 tick，#105）。"""
    ids = {str(e.get("item_id") or "") for e in entries}
    problems: list[str] = []
    for e in entries:
        iid = str(e.get("item_id") or "") or "?"
        for dep in _norm_deps(e.get("depends_on")):
            if dep not in ids:
                problems.append(f"{iid}：前置 {dep} 不在当前队列（未知 id）")
    for iid, text in sorted(_deps_cycle_texts(entries).items()):
        problems.append(f"{iid}：{text}")
    if problems:
        raise ValueError(
            "depends_on 校验失败（" + "；".join(problems) + "）")


def _dep_block_detail(
    entry: dict[str, Any],
    *,
    items: dict[str, Any],
    survivors: dict[str, Any],
    entry_ids: set[str],
    cycle_texts: dict[str, str],
) -> str:
    """候选条目 → 依赖门阻塞 detail（""=放行；纯函数）。

    依赖环成员直接给环文案（:func:`_deps_cycle_texts`）；否则逐前置按
    列出序取**首个未满足**（文案随首个未满足者走——同码换因保 ``since``，
    列出序固定故逐 tick 稳定）：前置账在本 tick 扫描面 ``items`` ∪ 陈账
    ``survivors`` 查——终态（:data:`ITEM_TERMINAL`）即满足（失败态也
    放行：失败如实传播不自动取消，#122；v1 无 skip 态不新增）；非终态
    给 ``<id>（<状态>）``；账面全无且不在本条目集=引用无账
    ``<id>（不在当前队列）``；账面缺而条目在=防御兜底 ``状态未知``
    （多报不放过，#316）。
    """
    iid = str(entry.get("item_id") or "")
    if iid in cycle_texts:
        return cycle_texts[iid]
    for dep in _norm_deps(entry.get("depends_on")):
        rec = items.get(dep) or survivors.get(dep)
        rec = rec if isinstance(rec, dict) else None
        if rec is None:
            if dep not in entry_ids:
                return f"{dep}（不在当前队列）"
            return f"{dep}（状态未知）"
        st = str(rec.get("status") or "")
        if st in ITEM_TERMINAL:
            continue
        return f"{dep}（{_DEP_STATUS_TEXT.get(st, st or '状态未知')}）"
    return ""


# ─── 长跑防卡死对冲（aurora_i W3-S3，服务器管控采纳 #1；缺省关=零行为变化）──

#: 对冲监测阈值 env（秒）。未设/空/非法/≤0 = 关闭（缺省=零行为变化，硬验收）；
#: >0 = 对在途项做"无进展时长 ≥ 阈值"监测。显式参数 > env > 缺省关。
HEDGE_STALL_S_ENV = "RFAUTO_QUEUE_HEDGE_STALL_S"

#: 自动重发显式开关 env（"1"/"true"/"yes"/"on" 大小写不敏感=开）。
#: **缺省关=只告警不重发**——#261 互斥红线下自动重发有双跑风险
#: （原进程可能仍存活并持 run 实例锁）；开启后每项硬帽至多重发一次。
HEDGE_RELAUNCH_ENV = "RFAUTO_QUEUE_HEDGE_RELAUNCH"

#: 对冲告警码（``rec["hedge"]["code"]`` 词表；v1 单码——停滞疑似）。
HEDGE_CODE_STALL = "stall_suspected"

#: 每项对冲重发硬帽（v1=1：防停滞+锁拒循环里无界拉子进程；再停滞只告警
#: 人工处置）。
_HEDGE_RELAUNCH_CAP = 1

#: 缺省进展探针覆盖面：计划文件（阶段事件 apply_event→save_plan 每次重写
#: =mtime 推进）+ 发射日志（子进程 stdout 追加）。两者皆陈旧=无进展证据。
_HEDGE_PROBE_NAMES = ("campaign.plan.json", "queue_daemon_launch.log")

#: 对冲告警 zh 人读模板单源（前端 i18n 另有 en 对照；同 W2-S3 纪律）。
_HEDGE_TEXT_TEMPLATES: dict[str, str] = {
    HEDGE_CODE_STALL: "疑似停滞：在途战役无进展",
}


def env_hedge_stall_s() -> float | None:
    """读 :data:`HEDGE_STALL_S_ENV` → 阈值秒数（未设/空/非法/≤0=None=关）。"""
    raw = os.environ.get(HEDGE_STALL_S_ENV)
    raw = str(raw or "").strip()
    if not raw:
        return None
    with contextlib.suppress(ValueError):
        v = float(raw)
        if v > 0:
            return v
    return None


def env_hedge_relaunch() -> bool:
    """读 :data:`HEDGE_RELAUNCH_ENV` → 自动重发开关（缺省 False=只告警）。"""
    return str(os.environ.get(HEDGE_RELAUNCH_ENV, "")).strip().lower() \
        in ("1", "true", "yes", "on")


def default_progress_ts(plan_path: str | Path) -> float | None:
    """缺省进展探针（纯读）：计划文件与发射日志的最新 mtime。

    ``plan_path`` 文件/目录两形态都接（生产记账面存文件路径，目录形态
    兜底 load_plan 同款宽容）：证据面=两探针名（计划文件+发射日志），
    目录形态按目录内解析；**目录本体 mtime 不作证据**（随目录内条目
    增删/改名变化，不代表战役求解进展——放个文件就洗白停滞钟的噪声
    证据面）。返回 None=无任何证据（全缺）——调用方按 unknown 保守
    不告警；探针异常同样按 unknown 处置（调用方兜，#105 观测面不阻塞
    主路径）。
    """
    p = Path(plan_path)
    base = p if p.is_dir() else p.parent
    cands = [base / name for name in _HEDGE_PROBE_NAMES]
    if p.is_file():
        cands.append(p)
    best: float | None = None
    for f in cands:
        with contextlib.suppress(OSError):
            mt = f.stat().st_mtime
            best = mt if best is None else max(best, mt)
    return best


def hedge_text_of(
    code: str,
    *,
    detail: str = "",
    stalled_s: float | None = None,
    attempts: int = 0,
) -> str:
    """对冲码+停滞时长 → zh 人读一句话（纯函数；同 :func:`blocked_text_of`
    口径——未知码返回空串，调用方回退 API 原文不猜）。"""
    tpl = _HEDGE_TEXT_TEMPLATES.get(str(code or ""))
    if tpl is None:
        return ""
    base = tpl.format(detail=str(detail or ""))
    if stalled_s is not None:
        base += f"（{_format_waited(stalled_s, label='已停滞')}）"
    if attempts:
        base += f"（已对冲重发 {int(attempts)} 次）"
    return base


def queue_hedge_index(
    state: dict[str, Any],
    *,
    now: float | None = None,
) -> dict[str, dict[str, Any]]:
    """状态档 → {item_id: 对冲账}（读侧人话渲染；同
    :func:`queue_blocks_index` 口径——``stalled_s``/``text`` 即时计算，
    状态档零冗余存储）。仅 ``status=launched`` 且带对冲账的项入索引——
    终态/排队项的陈账自动隐身（终态随态清扫+此处双保险）。"""
    ts = time.time() if now is None else float(now)
    out: dict[str, dict[str, Any]] = {}
    for iid, rec in (state.get("items") or {}).items():
        if not isinstance(rec, dict):
            continue
        if rec.get("status") != ITEM_LAUNCHED:
            continue
        hedge = rec.get("hedge")
        if not isinstance(hedge, dict) or not hedge.get("code"):
            continue
        code = str(hedge.get("code") or "")
        try:
            stalled = ts - float(hedge.get("since") or ts)
        except (TypeError, ValueError):
            stalled = 0.0
        stalled = max(0.0, stalled)
        attempts = int(hedge.get("attempts") or 0)
        out[str(iid)] = {
            "item_id": str(iid),
            "plan_path": rec.get("plan_path"),
            "code": code,
            "detail": str(hedge.get("detail") or ""),
            "since": hedge.get("since"),
            "stalled_s": round(stalled, 3),
            "attempts": attempts,
            "text": hedge_text_of(code, stalled_s=stalled, attempts=attempts),
        }
    return out


def _resolve_hedge_cfg(
    stall_s: float | None,
    relaunch: bool | None,
) -> tuple[float | None, bool]:
    """对冲配置解析（显式参数 > env > 缺省关；纯函数不读 env 当参数给定）。"""
    threshold = (env_hedge_stall_s() if stall_s is None
                 else (float(stall_s) if float(stall_s) > 0 else None))
    relaunch_on = env_hedge_relaunch() if relaunch is None else bool(relaunch)
    return threshold, relaunch_on


def _hedge_check(
    rec: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    now: float,
    threshold_s: float,
    relaunch: bool,
    progress_fn: Callable[[str], float | None],
    launcher_fn: Callable[[str], dict[str, Any]],
) -> None:
    """在途项停滞判定+处置（就地改性 ``rec``——本 tick 新建副本，非入参
    state；动作落 ``actions``，变化才落账同 W2-S3 范式）。

    - 探针无证据（None）/异常 → unknown 保守不动账不告警（#105/#122）；
    - 无进展 < 阈值：有账则摘账落 ``hedge_recovered``（进展恢复），无账不动；
    - 无进展 ≥ 阈值：无账=建账+``hedge_alert``；有账=同因不刷屏原样返回；
      重发开关开且未触帽 → 同 ``launcher_fn`` 缝 ``--resume`` 重发一次
      （``hedge_relaunch``/``hedge_relaunch_failed``；``hedge_attempts``
      尝试即计数落账防锁拒循环重发轰炸；不杀原进程树）。
    """
    plan_path = str(rec.get("plan_path") or "")
    iid = str(rec.get("item_id") or "")
    try:
        last = progress_fn(plan_path)
    except Exception:  # #105：探针异常=证据不可得，不判停滞不告警
        return
    if last is None:
        return
    stalled = now - float(last)
    hedge = rec.get("hedge")
    hedge = hedge if isinstance(hedge, dict) else None
    if stalled < threshold_s:
        if hedge is not None:
            rec.pop("hedge", None)
            actions.append({"action": "hedge_recovered", "item_id": iid,
                            "plan": plan_path})
        return
    if hedge is not None and hedge.get("code") == HEDGE_CODE_STALL:
        return  # 同因不刷屏（since/attempts 原样，读侧时长即时算）
    attempts = int(rec.get("hedge_attempts") or 0)
    rec["hedge"] = {"code": HEDGE_CODE_STALL, "since": now, "updated_at": now,
                    "last_progress": float(last), "attempts": attempts}
    actions.append({"action": "hedge_alert", "item_id": iid, "plan": plan_path,
                    "stalled_s": round(max(0.0, stalled), 3),
                    "threshold_s": float(threshold_s),
                    "reason": hedge_text_of(HEDGE_CODE_STALL,
                                            stalled_s=max(0.0, stalled),
                                            attempts=attempts)})
    if not relaunch or attempts >= _HEDGE_RELAUNCH_CAP:
        return
    attempts += 1
    rec["hedge_attempts"] = attempts  # 尝试即计数千账（锁拒也烧帽，防循环拉起）
    rec["hedge"]["attempts"] = attempts
    res = launcher_fn(plan_path)
    if res.get("ok"):
        rec["pid"] = res.get("pid")
        rec["launched_at"] = now
        rec["log_path"] = res.get("log_path")
        rec["hedge"]["relaunched_at"] = now
        rec["reason"] = ("对冲重发（停滞超阈疑似卡死；原进程不杀，"
                         "若仍持 run 实例锁则新实例占即拒=安全侧失败）")
        actions.append({"action": "hedge_relaunch", "item_id": iid,
                        "plan": plan_path, "pid": res.get("pid"),
                        "attempt": attempts})
    else:
        actions.append({"action": "hedge_relaunch_failed", "item_id": iid,
                        "plan": plan_path,
                        "error": str(res.get("error") or "")})


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
    "license_gated", "depends_on"}``；``depends_on``=计划级可选键（前置
    任务 item_id 列表，W2-S5 依赖门）规范化（str+strip、去空、去重保序，
    缺键/坏形态=[]）；损坏计划逐条跳过（list_campaign_plans #105 口径），
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
            "depends_on": _norm_deps(plan.get("depends_on")),
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


def _write_failure_context(plan_path: str) -> dict[str, Any]:
    """失败诊断包落包薄包装（failure_context_service 单源；#139）。

    案发现场目录=计划文件父目录（战役 run 目录）；失败瞬间采集机器
    实况/license 态含 TCP 探活（生产语义），测试经注入缝替换。
    """
    from pathlib import Path as _Path

    from rfauto.service.failure_context_service import write_failure_context

    return write_failure_context(_Path(plan_path).parent)


def _snapshot_failure_context(
    fn: Callable[[str], Any] | None, plan_path: str, iid: str,
    actions: list[dict[str, Any]],
) -> None:
    """失败诊断包触发（best-effort #105：采集面异常留痕不拆 tick）。"""
    if fn is None:
        return
    try:
        res = fn(plan_path)
    except Exception as exc:
        actions.append({"action": "failure_context_error", "item_id": iid,
                        "plan": plan_path,
                        "error": f"{type(exc).__name__}: {exc}"})
        return
    actions.append({"action": "failure_context", "item_id": iid,
                    "plan": plan_path,
                    "path": (res or {}).get("path") if isinstance(res, dict)
                    else None})


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
    """状态档 → 人读摘要（计数按记账态；状态可查面，零额外 I/O）。

    ``blocked``=排队项按阻塞码计数（W2-S3 采纳 #2；无阻塞账则键缺席
    ——消费方按缺键=无阻塞读，不加空壳键）。
    """
    items = state.get("items") or {}
    by_status: dict[str, int] = {}
    blocked: dict[str, int] = {}
    for rec in items.values():
        rec = rec if isinstance(rec, dict) else {}
        key = str(rec.get("status") or "?")
        by_status[key] = by_status.get(key, 0) + 1
        blk = rec.get("blocked")
        if isinstance(blk, dict) and blk.get("code") \
                and rec.get("status") == ITEM_QUEUED:
            code = str(blk.get("code"))
            blocked[code] = blocked.get(code, 0) + 1
    in_flight = sum(1 for rec in items.values()
                    if (rec or {}).get("status") == ITEM_LAUNCHED)
    out = {"schema": str(state.get("schema") or ""),
           "n_items": len(items), "by_status": by_status,
           "in_flight": in_flight,
           "last_tick_at": state.get("last_tick_at")}
    if blocked:
        out["blocked"] = blocked
    return out


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
    survivor_ttl_s: float | None = None,
    failure_context_fn: Callable[[str], Any] | None = None,
    hedge_stall_s: float | None = None,
    hedge_relaunch: bool | None = None,
    progress_fn: Callable[[str], float | None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """tick 单步：读队列→依赖门→单飞/日历窗→license 预检→发射→状态
    回写（纯函数）。

    依赖门（aurora_j W2-S5）：候选按计划级 ``depends_on`` 分流——任一
    前置未达终态（:data:`ITEM_TERMINAL`，失败态也放行=失败如实传播不
    自动取消）或依赖环/无账引用 → :data:`BLOCK_DEPS` 阻塞账本 tick 不
    发射；就绪候选照常走单飞/日历/许可门（pass-over，依赖未满足不阻塞
    队头）。坏账项降级阻塞不拆 tick（#105）；缺字段=零行为变化。

    全部副作用经注入缝（now_fn/calendar_fn/preflight_fn/queue_fn/
    launcher_fn/failure_context_fn/progress_fn，缺省=生产适配薄包装；唯
    ``failure_context_fn`` 缺省 ``None``=纯函数零副作用——落失败快照是
    写他目录的实质副作用，只在生产执行体 :func:`run_queue_daemon` 缺省
    接真包，测试显式注入假件）；输入 state 不改性，新状态由返回值交付
    （落盘归调用方——:func:`run_queue_daemon` 每 tick 单点写）。

    对冲配置（W3-S3）：``hedge_stall_s``/``hedge_relaunch`` 显式参数 >
    env（:data:`HEDGE_STALL_S_ENV`/:data:`HEDGE_RELAUNCH_ENV`）> 缺省关
    （阈值 None=对冲代码路径整体不进：零探针调用、零新动作、零新字段
    ——缺省路径零行为变化硬验收）。``hedge_stall_s`` 显式 ≤0=显式关
    （压过 env）；``progress_fn`` 缺省=:func:`default_progress_ts`
    （mtime 探针，仅阈值开启后才被调用）。

    Returns
    -------
    (actions, new_state)
    actions=本 tick 动作清单（词表：scan/enqueue/launch/launch_failed/
    in_flight_wait/calendar_blocked/calendar_risk/license_pass/
    license_skip_open/license_skip/record_terminal/observe_external/
    refresh_terminal/recycle_stale/failure_context/failure_context_error/
    hedge_alert/hedge_relaunch/hedge_relaunch_failed/hedge_recovered/
    tick_error/state_save_error）；
    new_state=回写后的完整状态档（同 :func:`default_state` 形态）。
    """
    now = float((now_fn or time.time)())
    cal_fn = calendar_fn or _calendar_launch_view
    pre_fn = preflight_fn or _license_preflight
    q_fn = queue_fn or scan_queue
    l_fn = launcher_fn or _launch_campaign_subprocess
    fc_fn = failure_context_fn  # None=不落失败快照（纯函数缺省零副作用）
    hedge_threshold, hedge_relaunch_on = _resolve_hedge_cfg(
        hedge_stall_s, hedge_relaunch)
    probe_fn = progress_fn or default_progress_ts

    new_state = default_state(root=root, machine=machine)
    prev_items = dict((state or {}).get("items") or {})
    items: dict[str, Any] = {}
    actions: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    tick_blocks: dict[str, tuple[str, str, int]] = {}  # iid → (code, detail, n_ahead)
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
                # 排队候选预登记 ITEM_QUEUED（审查 A3 P2-2①：状态可查面
                # 看得见排队项——此前只在 launch/launch_failed 时才落账，
                # by_status 恒无 queued；词表死常量就此接上）
                candidates.append(entry)
                items[iid] = _new_record(entry, ITEM_QUEUED, now,
                                         reason="排队候选（待单飞位/日历/许可门）")
                actions.append({"action": "enqueue", "item_id": iid,
                                "plan": entry.get("plan_path")})
            continue
        prev = dict(prev if isinstance(prev, dict) else {})
        if prev.get("status") == ITEM_QUEUED:
            if terminal_status is not None:
                # 排队期被他人跑完——plan verdict 权威收口（不发射，#122）
                prev.pop("blocked", None)  # 阻塞账随态清除（W2-S3）
                prev["status"] = terminal_status
                prev["verdict_seen"] = verdict
                prev["reason"] = f"verdict={verdict}（排队期权威收口）"
                prev["updated_at"] = now
                items[iid] = prev
                actions.append({"action": "refresh_terminal", "item_id": iid,
                                "status": terminal_status,
                                "plan": entry.get("plan_path")})
                continue
            if verdict == "RUNNING":
                prev.pop("blocked", None)  # 阻塞账随态清除（W2-S3）
                prev["status"] = ITEM_EXTERNAL
                prev["verdict_seen"] = verdict
                prev["reason"] = "verdict=RUNNING 但非本守护发射（只观察不接管）"
                prev["updated_at"] = now
                items[iid] = prev
                actions.append({"action": "observe_external", "item_id": iid,
                                "plan": entry.get("plan_path")})
                continue
            # 仍在排队：刷新账目继续参队（单飞位/门未过，下 tick 重探）
            prev["verdict_seen"] = verdict
            prev["updated_at"] = now
            items[iid] = prev
            candidates.append(entry)
            continue
        if prev.get("status") == ITEM_LAUNCHED:
            if terminal_status is not None:
                prev.pop("blocked", None)  # 阻塞账随态清除（防御，launched 不带账）
                prev.pop("hedge", None)  # 对冲账随态清除（W3-S3）
                prev["status"] = terminal_status
                prev["verdict_seen"] = verdict
                prev["reason"] = f"verdict={verdict}（发射后终态回读）"
                prev["updated_at"] = now
                items[iid] = prev
                actions.append({"action": "refresh_terminal", "item_id": iid,
                                "status": terminal_status,
                                "plan": entry.get("plan_path")})
                if terminal_status in (ITEM_ABORTED, ITEM_PARTIAL):
                    # 失败诊断包触发（W2-S3 采纳 #3）：本守护发射的战役
                    # 终态回读为失败态——案发现场快照落计划目录。
                    _snapshot_failure_context(
                        fc_fn, str(entry.get("plan_path") or ""), iid, actions)
                continue
            prev["verdict_seen"] = verdict
            prev["updated_at"] = now
            items[iid] = prev
            in_flight = in_flight or prev  # 单飞约束：在途未收尾不发射下一项
            if hedge_threshold is not None:
                # 长跑防卡死对冲（W3-S3）：仅本 tick 扫描命中的在途项判定
                # ——陈账（计划不可读）分不清"移走"与"卡死"，保守不判。
                _hedge_check(prev, actions, now=now,
                             threshold_s=hedge_threshold,
                             relaunch=hedge_relaunch_on,
                             progress_fn=probe_fn, launcher_fn=l_fn)
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
    survivors, recycled = prev_items_survivors(
        prev_items, entries, now=now, ttl_s=survivor_ttl_s)
    for info in recycled:  # 回收留痕不静默（审查 A3 P2-2②）
        actions.append({"action": "recycle_stale", **info})
    if in_flight is None:
        for rec_s in survivors.values():
            if isinstance(rec_s, dict) and rec_s.get("status") == ITEM_LAUNCHED:
                in_flight = rec_s
                in_flight_unseen = True
                break

    # 依赖门（aurora_j W2-S5）：候选按 depends_on 分流——存在未达终态
    # 前置或依赖环/无账引用的候选本 tick 不发射（BLOCK_DEPS，"变化才落
    # 账"同 W2-S3 范式），其余候选（ready）保持既有单飞/日历/许可门序。
    # 依赖未满足**不阻塞队头**（pass-over）：就绪候选照常上位，坏账项
    # 只挡自身。对全体候选评估明细：单飞挡住的 tick 里依赖码覆写 solo
    # 码（依赖是更持久的原因——单飞解除后依赖未必解除）。
    deps_cycle = _deps_cycle_texts(entries)
    entry_ids_all = {str(e.get("item_id") or "") for e in entries}
    deps_detail: dict[str, str] = {}
    ready: list[dict[str, Any]] = []
    for c in candidates:
        _iid = str(c.get("item_id") or "")
        _det = _dep_block_detail(c, items=items, survivors=survivors,
                                 entry_ids=entry_ids_all,
                                 cycle_texts=deps_cycle)
        if _det:
            deps_detail[_iid] = _det
        else:
            ready.append(c)

    if in_flight is not None:
        _m = str((in_flight or {}).get("model") or "")
        if not _m:
            _pp = str((in_flight or {}).get("plan_path") or "")
            _m = _pp.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        actions.append({"action": "in_flight_wait",
                        "item_id": in_flight.get("item_id"),
                        "plan": in_flight.get("plan_path"),
                        "reason": "单飞约束：在途战役未收尾，本 tick 不发射"
                                  + ("（计划本 tick 扫描未命中——在途陈账"
                                     "照常阻塞，单飞不逃逸）"
                                     if in_flight_unseen else "")})
        # 单飞互斥=全体候选的共同阻塞因（W2-S3 采纳 #2）
        for c in candidates:
            _iid = str(c.get("item_id") or "")
            if _iid:
                tick_blocks[_iid] = (BLOCK_SOLO, _m, 0)
    elif ready:
        entry = ready[0]
        # 后位候选：前序未发射即其阻塞因（依赖已就绪者内的排队序）
        for _idx, c in enumerate(ready[1:], start=1):
            _iid = str(c.get("item_id") or "")
            if _iid:
                tick_blocks[_iid] = (BLOCK_AHEAD, "", _idx)
        # 门 1：资源日历窗（blocked=本 tick 不发射，项不记永久 skip——
        # E62 SKIP=inconclusive 续跑重探同源；risk=照发风险落账）
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
            _iid0 = str(entry.get("item_id") or "")
            if _iid0:
                tick_blocks[_iid0] = (BLOCK_CALENDAR,
                                      str(calendar.get("reason") or ""), 0)
        else:
            if cal_state == "risk":
                actions.append({"action": "calendar_risk",
                                "item_id": entry.get("item_id"),
                                "windows_hit": calendar.get("windows_hit"),
                                "reason": str(calendar.get("reason") or "")})
            # 门 2：license 预检（仅 license 消耗面计划咨询，或显式
            # license_gate=True 强制；PASS 照发 / SKIP fail-open 照发 /
            # FAIL fail-skip 下 tick 重探——E62 同款不硬打）
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
                    _iid0 = str(entry.get("item_id") or "")
                    if _iid0:
                        tick_blocks[_iid0] = (BLOCK_LICENSE,
                                              str(pf.get("reason") or ""), 0)
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
                    # 发射失败=本守护经手的失败——失败诊断包触发（W2-S3）
                    _snapshot_failure_context(
                        fc_fn, str(entry.get("plan_path") or ""), iid, actions)

    # 依赖门阻塞账（W2-S5）：整段门序之后统一落账——单飞码之上覆写
    # （同真时报依赖，更持久的原因）；elif-ready 分支里被依赖门挡下的
    # 候选（未进 ready）也在此入账。
    for _iid, _det in deps_detail.items():
        if _iid:
            tick_blocks[_iid] = (BLOCK_DEPS, _det, 0)

    # 阻塞账合并（W2-S3 采纳 #2）：变化才落账——同 (code, detail) 原账
    # 不动（since 保持首次阻塞时刻，读侧等待时长连续）；换因/解除才写。
    for _iid, (_code, _detail, _n) in tick_blocks.items():
        rec = items.get(_iid)
        if not isinstance(rec, dict) or rec.get("status") != ITEM_QUEUED:
            continue
        items[_iid], _changed = merge_blocked_reason(
            rec, _code, detail=_detail, n_ahead=_n, now=now)

    # 对冲账随态清扫（W3-S3）：对冲账只属于在途（launched）——记录换成
    # 其他态（终态/external/queued）时残留的陈账摘除。copy-on-write
    # （survivors 是入参 state 的原对象，就地 pop 会破"输入 state 不改性"）。
    _merged_items: dict[str, Any] = {**survivors, **items}
    for _iid, rec in list(_merged_items.items()):
        if isinstance(rec, dict) and rec.get("status") != ITEM_LAUNCHED \
                and "hedge" in rec:
            rec = dict(rec)
            rec.pop("hedge", None)
            _merged_items[_iid] = rec

    new_state["items"] = _merged_items
    new_state["last_tick_at"] = now
    new_state["last_actions"] = actions
    new_state["updated_at"] = now
    return actions, new_state


def prev_items_survivors(
    prev_items: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    now: float | None = None,
    ttl_s: float | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """本 tick 扫描未命中（计划目录被移走）的陈账处置 + 回收清单。

    - 在途（launched）陈账**无条件保留**——单飞不逃逸（#261）依赖它阻塞
      发射；计划永久消失时单飞停摆、状态档可见人工处置（docstring 口径）；
    - 其余态（external/queued/终态）陈账按账龄回收：``updated_at`` 距今
      超过 ``ttl_s``（缺省 :data:`SURVIVOR_TTL_S_DEFAULT`=7 天）即进回收
      清单（调用方以 recycle_stale 动作留痕），防常驻月级运行状态档无界
      增长（审查 A3 P2-2②）。

    Returns
    -------
    (survivors, recycled)
    survivors=保留的陈账（并入新状态档 items）；recycled=[{item_id,
    status, age_s}]（updated_at 缺失按最老计回收，非法值保守保留）。
    """
    seen = {str(e.get("item_id") or "") for e in entries}
    ts = time.time() if now is None else float(now)
    ttl = SURVIVOR_TTL_S_DEFAULT if ttl_s is None else float(ttl_s)
    keep: dict[str, Any] = {}
    recycled: list[dict[str, Any]] = []
    for iid, rec in prev_items.items():
        if not isinstance(rec, dict) or iid in seen:
            continue
        if rec.get("status") == ITEM_LAUNCHED:
            keep[iid] = rec
            continue
        try:
            age = ts - float(rec.get("updated_at") or 0.0)
        except (TypeError, ValueError):
            keep[iid] = rec  # 账面损坏保守保留（零伪造零误删）
            continue
        if age > ttl:
            recycled.append({"item_id": iid, "status": rec.get("status"),
                             "age_s": round(age, 3)})
        else:
            keep[iid] = rec
    return keep, recycled


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
    failure_context_fn: Callable[[str], Any] | None = None,
    hedge_stall_s: float | None = None,
    hedge_relaunch: bool | None = None,
    progress_fn: Callable[[str], float | None] | None = None,
) -> dict[str, Any]:
    """常驻执行体：while 循环逐 tick（读队列→门→发射→状态落盘）+优雅退出。

    - ``once=True``：单步模式（测试/cron），一 tick 即返；
    - 单例锁：状态路径旁 ``.lock``（dag_runner.acquire_lock O_CREAT|O_EXCL
      +陈锁接管式样，max_wait_s=0 占即拒）——第二实例如实 error 信封；
      释放同走 dag_runner.release_lock 单源（删前校验 pid=自身，A7 P2-6
      防误释他人/接管期锁）；
    - 优雅退出：SIGTERM 处理器置停旗（注册失败平台 best-effort #105）+
      KeyboardInterrupt 捕获——当前 tick 完成并落账后退出；
    - 注入缝同 :func:`queue_tick`（sleep_fn/stop_check 供测试免真睡）；
      ``failure_context_fn`` 缺省接生产真包（失败诊断包自动触发，W2-S3
      采纳 #3——与 :func:`queue_tick` 纯函数缺省 None 相区别）；
    - 对冲参数（W3-S3）透传 :func:`queue_tick`（显式参数 > env > 缺省关；
      配置通道=env，CLI 不加旗标零面变化）。
    """
    sp = Path(state_path) if state_path is not None else default_queue_state_path()
    from rfauto.pipeline.dag_runner import acquire_lock, release_lock

    lock_path = sp.parent / (sp.name + _DAEMON_LOCK_SUFFIX)
    holder = acquire_lock("campaign_queue_daemon", lock_path, max_wait_s=0)
    if holder is None:
        return error_envelope(
            [f"另一 campaign queue-daemon 实例持有锁: {lock_path}"
             "（单例约束，防双发射）"])
    released = False

    def _release() -> None:
        # A7 P2-6：释放复用 dag_runner.release_lock 单源（删前读锁内容
        # 校验 pid=自身持有者）——裸 unlink 无持有者校验，误删接管期/
        # 他实例的锁会打开双发射窗口。release_lock 自身 best-effort
        # （#105：读不到/已消失一律静默放过）。
        nonlocal released
        if not released:
            released = True
            release_lock(holder, lock_path)

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
                    root=root, machine=machine,
                    failure_context_fn=(failure_context_fn
                                        if failure_context_fn is not None
                                        else _write_failure_context),
                    hedge_stall_s=hedge_stall_s,
                    hedge_relaunch=hedge_relaunch,
                    progress_fn=progress_fn)
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
                # 结构化 tick 流（dict 载荷：渲染归调用方——AGENTS 前端只
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
