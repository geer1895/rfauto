"""campaign_digest：战役终态人读摘要聚合器（aurora_e W3-S4，服务器管控采纳 #7）。

背景：多战役过夜（queue-daemon 排队发射）后，逐战役 campaign status 人工
巡检刷屏——本模块把扫描窗内的战役终态（COMPLETE/PARTIAL/ABORTED）聚合成
**一条** zh 人读摘要（含逐战役行），JSON+文本双产物落 runs/ 下 digest 目录。
思想借鉴 E:\\服务器管控\\hfss-dispatch 的 plugins/notify/digest.py
（聚合防刷屏、逐行列出+截断注记；只读借鉴，未引其代码——本项目无
webhook 通道，推送面留 followUp 登记，本模块只做本地聚合落盘）。

语义与边界：
- 扫描口径与 ``campaign list`` 同源（campaign_manager.list_campaign_plans：
  root 直属子目录的 campaign.plan.json，损坏文件被读面逐条跳过不拖垮
  整表，#105）；
- verdict 语义复用 campaign_manager.apply_event 词表（COMPLETE/PARTIAL/
  ABORTED/RUNNING），零新态；终态=前三者，RUNNING/无 verdict 缺省不计入
  （``include_running=True`` 时计入并在文案如实标注"进行中"）；
- 失败原因摘自失败/放弃阶段的 note 中 apply_event 写入的 "failed: detail"
  显式标记尾段（无标记的规划描述不作数——不把计划描述冒充失败原因），
  逐战役取第一条、超长截断——摘要是人读导览，权威细节仍在
  campaign.plan.json 本体（产物里逐战役带路径）；
- ``since_h`` 可选时间窗（计划文件 mtime 距今 N 小时内，"昨晚"口径），
  缺省不过滤；非法值（≤0/非数）ok=False 如实报错；
- 产物：``<out_dir>/digest_<时间戳>.json``（结构化全量）+ 同名 ``.txt``
  （zh 摘要文本）；out_dir 缺省 runs/campaign_digest/（经 infra.
  runs_paths 双根收敛，#295 族）；写盘原子替换（同 campaign_manager
  save_plan 口径）。零终态战役不是错误：ok=True + 空清单 + "无终态战役"
  文案（如实空，不假绿也不报错）。

数字出处：全部来自已落盘 campaign.plan.json（n_done/n_dead/verdict 均
状态机回写值），本模块零物理数字产生、零状态机重算（AGENTS #7）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

# 有意不声明 __all__（同 campaign_manager.py 口径）：check_public_api 金快照
# 不收私有模块——并发席位共用该金快照文件，本席零共享金样 churn（aurora_e
# W3-S4 并发纪律，#228 门作用域限本项文件）。

#: 终态词表（campaign_manager.apply_event 同源，零新态）。
TERMINAL_VERDICTS = ("COMPLETE", "PARTIAL", "ABORTED")

#: verdict → zh 人读词（既有 verdict 语义复用）。
VERDICT_ZH = {
    "COMPLETE": "完成",
    "PARTIAL": "部分完成",
    "ABORTED": "已中止",
    "RUNNING": "进行中",
}

#: verdict → 摘要符号（✓/⚠/✗ 沿任务书示例；未知 verdict 用 ?）。
VERDICT_MARK = {
    "COMPLETE": "✓",
    "PARTIAL": "⚠",
    "ABORTED": "✗",
    "RUNNING": "…",
}

#: digest 产物缺省落点（runs/ 下 digest 目录；runs_paths 双根收敛）。
DIGEST_DIR_DEFAULT = "runs/campaign_digest"

#: 逐战役原因截断长度（人读导览，权威细节在 plan 本体）。
_REASON_MAX = 60


def failure_reason(plan: dict[str, Any]) -> str:
    """失败原因摘要（确定性）：第一条带 ``failed:`` 标记的阶段 note 尾段。

    apply_event 的 stage_failed 写法为 ``note + " | failed: detail"``——
    取最后一个 "failed:" 之后的尾段作为原因；无标记的 note（阶段规划
    描述/手工 aborted 面）**不作数**（不把计划描述冒充失败原因，如实
    缺省）。截断到 ``_REASON_MAX`` 字符并注省略号；无失败记录（COMPLETE/
    手工 aborted）返回 ""。
    """
    for s in plan.get("stages") or []:
        if not isinstance(s, dict) or s.get("status") not in ("failed", "aborted"):
            continue
        note = str(s.get("note") or "")
        if "failed:" not in note:
            continue  # 无失败标记的 note（规划描述）：不作失败原因
        reason = note.rsplit("failed:", 1)[1].strip()
        reason = reason.split(" | ", 1)[0].strip()
        if reason:
            if len(reason) > _REASON_MAX:
                reason = reason[:_REASON_MAX] + "…"
            return reason
    return ""


def _display_name(it: dict[str, Any]) -> str:
    """摘要行展示名：model 优先（战役目录多为时间戳名，人读导览用 model）。"""
    return str(it.get("model") or "") or str(it.get("name") or "")


def render_digest_text(items: list[dict[str, Any]], *, root: str,
                       generated_at: str) -> str:
    """zh 摘要文本（人读正文，CLI 缺省面与 .txt 产物同源单份）。

    形态（任务书示例口径）::

        [rfauto 战役摘要] 扫描 runs（2026-10-19 08:00:00）：共 3 战役终态——
        2 完成、1 部分完成、0 已中止
        - wilkinson ✓ 完成（6/6 阶段）
        - vivaldi ⚠ 部分完成（4/6 阶段；原因: tune: NrTS 触顶）

    零终态时首行如实 "无终态战役"；include_running 计入的非终态战役
    尾注 "进行中"（按 verdict_zh 词表，不冒充终态）。
    """
    if not items:
        return (f"[rfauto 战役摘要] 扫描 {root}（{generated_at}）："
                "无终态战役（COMPLETE/PARTIAL/ABORTED）")
    counts = {"COMPLETE": 0, "PARTIAL": 0, "ABORTED": 0}
    for it in items:
        if it["verdict"] in counts:
            counts[it["verdict"]] += 1
    stat = "、".join(f"{counts[v]} {VERDICT_ZH[v]}" for v in TERMINAL_VERDICTS)
    n_other = len(items) - sum(counts.values())
    head = (f"[rfauto 战役摘要] 扫描 {root}（{generated_at}）："
            f"共 {len(items)} 战役终态——{stat}")
    if n_other:
        head += f"（另 {n_other} 个非终态计入）"
    lines = [head]
    for it in items:
        mark = VERDICT_MARK.get(it["verdict"], "?")
        zh = VERDICT_ZH.get(it["verdict"], it["verdict"] or "未知")
        line = f"- {_display_name(it)} {mark} {zh}（{it['n_done']}/{it['n_stages']} 阶段"
        if it.get("reason"):
            line += f"；原因: {it['reason']}"
        line += "）"
        lines.append(line)
    return "\n".join(lines)


def _headline(items: list[dict[str, Any]]) -> str:
    """单行导语（信封字段；示例口径"3 战役：2 完成 1 部分完成——逐列"）。"""
    if not items:
        return "无终态战役（COMPLETE/PARTIAL/ABORTED）"
    counts = {"COMPLETE": 0, "PARTIAL": 0, "ABORTED": 0}
    for it in items:
        if it["verdict"] in counts:
            counts[it["verdict"]] += 1
    stat = "、".join(f"{counts[v]} {VERDICT_ZH[v]}" for v in TERMINAL_VERDICTS
                     if counts[v])
    if not stat:
        stat = "无终态"
    inline = "、".join(
        f"{_display_name(it)} {VERDICT_MARK.get(it['verdict'], '?')} "
        f"{VERDICT_ZH.get(it['verdict'], it['verdict'])}"
        + (f"（{it['reason']}）" if it.get("reason") else "")
        for it in items)
    return f"共 {len(items)} 战役终态：{stat}——{inline}"


def _atomic_write_text(target: Path, text: str) -> None:
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def _notify_note(result: dict[str, Any]) -> str:
    """notify 结果 → 单行人读注记（信封 notes 用；skipped 不入 notes）。"""
    if result.get("skipped"):
        return str(result.get("reason") or "skipped")
    errs = [str((r or {}).get("error") or "?")
            for r in (result.get("results") or {}).values()
            if isinstance(r, dict) and not r.get("ok")]
    return "; ".join(errs) or "unknown"


def _notify_tail(out: dict[str, Any], summary_text: str,
                 notify: bool | None) -> dict[str, Any]:
    """产物落盘后的 best-effort webhook 推送尾（aurora_j W2-S6）。

    - ``notify=False``：显式关（service 显式 False 优先于 env 配置，#277
      三态惯例），零网络；
    - 其余（None=读 env 配置决定 / True=配置了就推）：调
      campaign_notify_service.notify_digest，结果记 ``out["notify"]``；
      推送失败只在信封 notes 加一行（#105：通知失败不回滚 digest 主
      产物，任何异常兜底不抛）。
    """
    if notify is False:
        out["notify"] = skipped_envelope(
            "disabled：显式 --no-notify（service 显式 False 优先于 env 配置）")
        return out
    from rfauto.service.campaign_notify_service import notify_digest

    try:
        result = notify_digest(out, summary_text)
    except Exception as exc:  # #105：观测面兜底，通知异常不拆主路径
        result = error_envelope(f"notify 未捕获异常: {exc}")
    out["notify"] = result
    if not result.get("ok"):
        out["notes"] = [f"notify 推送未成功: {_notify_note(result)}"]
    return out


def campaign_digest(
    root: str | Path = "runs",
    *,
    out_dir: str | Path | None = None,
    since_h: float | None = None,
    include_running: bool = False,
    write: bool = True,
    notify: bool | None = None,
) -> dict[str, Any]:
    """扫描战役终态聚合成人读摘要（服务层 JSON 进出，规则 4）。

    参数：
    - root：扫描根（直属子目录 campaign.plan.json，与 campaign list 同口径）；
    - out_dir：产物目录；None → runs/campaign_digest/（双根收敛）；
    - since_h：时间窗（计划文件 mtime 距今 N 小时内；None=不过滤；≤0/非数
      如实报错）；
    - include_running：非终态战役也计入（文案如实标"进行中"）；
    - write：落 JSON+文本双产物（CLI 缺省 True；测试/预览可 False）；
    - notify：webhook 推送三态（W2-S6，#277 惯例）：None=读 env 配置决定
      （RFAUTO_NOTIFY_WEBHOOK_URL/RFAUTO_NOTIFY_FEISHU_WEBHOOK 均未设即
      skipped 零网络零行为）；False=显式不推；True=配置了就推。仅
      write=True（产物已落盘）时生效；结果记返回信封 "notify" 字段，
      推送失败不回滚主产物（#105 best-effort）。

    返回信封：n_campaigns（计入数）/ counts / campaigns（逐战役明细含
    plan 路径）/ headline / summary_text / artifacts（write=True 时）/
    notify（write=True 时，推送结果信封）。
    """
    from rfauto.service.campaign_manager import list_campaign_plans, load_plan

    if since_h is not None:
        try:
            since_h_f = float(since_h)
        except (TypeError, ValueError):
            return error_envelope([f"since_h 非法: {since_h!r}（须为正小时数）"])
        if since_h_f <= 0:
            return error_envelope(
                [f"since_h 非法: {since_h_f}（须 >0，单位小时）"])
    else:
        since_h_f = None

    listed = list_campaign_plans(root)
    now = datetime.now()
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    cutoff = (now.timestamp() - since_h_f * 3600.0) if since_h_f else None

    items: list[dict[str, Any]] = []
    for c in listed.get("campaigns") or []:
        # 空 verdict（立计划未推进）按 RUNNING 展示（词表归一，零新态——
        # 展示层面口径；plan 本体不被改写）。
        verdict = str(c.get("verdict") or "") or "RUNNING"
        if verdict not in TERMINAL_VERDICTS and not include_running:
            continue  # 非终态缺省不计入（include_running 时显式计入并如实标注）
        if cutoff is not None:
            try:
                if Path(c["path"]).stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue  # 计划文件已消失：如实不计入（读面 best-effort #105）
        reason = ""
        if verdict in ("PARTIAL", "ABORTED"):
            detail = load_plan(c["path"])
            if detail.get("ok"):
                reason = failure_reason(detail["plan"])
        items.append({
            "name": Path(c["path"]).parent.name,
            "model": str(c.get("model") or ""),
            "verdict": verdict,
            "verdict_zh": VERDICT_ZH.get(verdict, verdict or "未知"),
            "mark": VERDICT_MARK.get(verdict, "?"),
            "n_done": c.get("n_done"),
            "n_dead": c.get("n_dead"),
            "n_stages": c.get("n_stages"),
            "path": c["path"],
            "reason": reason,
        })

    counts = {v: sum(1 for it in items if it["verdict"] == v)
              for v in TERMINAL_VERDICTS}
    summary_text = render_digest_text(items, root=str(root),
                                      generated_at=generated_at)
    headline = _headline(items)

    out: dict[str, Any] = ok_envelope(
        root=str(root),
        generated_at=generated_at,
        n_campaigns=len(items),
        counts=counts,
        campaigns=items,
        headline=headline,
        summary_text=summary_text,
        include_running=bool(include_running),
        since_h=since_h_f,
    )
    if not write:
        return out

    out_path = Path(out_dir) if out_dir is not None else None
    if out_path is None:
        from rfauto.infra.runs_paths import resolve_runs_dir

        out_path = resolve_runs_dir(DIGEST_DIR_DEFAULT)
    out_path.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    base = out_path / f"digest_{stamp}"
    if base.with_suffix(".json").exists():
        base = out_path / f"digest_{stamp}_{now.strftime('%f')}"
    json_path = base.with_suffix(".json")
    txt_path = base.with_suffix(".txt")
    payload = {**out, "schema": "rfauto-campaign-digest-v1"}
    _atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False,
                                            indent=1, default=str))
    _atomic_write_text(txt_path, summary_text + "\n")
    out["artifacts"] = {"json": str(json_path), "txt": str(txt_path)}
    return _notify_tail(out, summary_text, notify)
