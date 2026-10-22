"""失败诊断包服务（aurora_i W2-S3，服务器管控采纳 #3）。

战役/任务失败瞬间聚合"案发现场"快照落 run 目录 ``failure_context.json``
（hfss-dispatch failure_context 思想重实现，按 rfauto 分层/信封/测试钉
规范——只取语义不搬代码，R1_server_mgmt_adoption.md §4-3）：

- **结局面**（outcome）：campaign.plan.json verdict + 失败/中止 stage
  清单 + events.jsonl 终态事件（run_failed 在档时的 error 消息面）；
  ``exit_code``/``error`` 参数在档即录——v1 发射链 fire-and-forget 无
  退出回执，缺席如实（不伪造 0/非零）；
- **机器实况面**（machine）：remote_probe 摘要（可达性/端口探活；注入缝
  可 fake，零网络可测 #139）；
- **license 面**（license）：license_preflight 摘要（verdict/gate/reason）；
- **日志尾面**（logs）：queue_daemon_launch.log / events.jsonl 尾 N 行
  （超长行截断，行数对账）；
- **聚合判定**：采集自身 OK/PARTIAL/FAILED——逐面 try/except 单面失败
  不拖垮整包（diagnosis_service.run_diagnosis 同款聚合口径，R1 §3-2
  "复用聚合逻辑"指此范式），顶层 ``ok`` 只在全部采集面失败才 False。

触发：campaign_queue_daemon 在 ``launch_failed``/已发射战役终态回读为
ABORTED/PARTIAL 时经注入缝落包（失败瞬间语义）；先于守护的终态不触发
（非本守护经手的失败不越权写他人 run 目录，daemon docstring 口径）。
读面：:func:`read_failure_context` 经 ``/api/runs/<run_id>/failure_context``
供详情页"一键查看诊断"节；人工补采走 :func:`write_failure_context`
（幂等覆盖，原子写）。
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "FAILURE_CONTEXT_FILE",
    "FAILURE_CONTEXT_SCHEMA",
    "LOG_TAIL_LINES_DEFAULT",
    "build_failure_context",
    "failure_context_path",
    "read_failure_context",
    "write_failure_context",
]

#: 诊断包 schema 版本（不一致=整档弃用读侧如实报，防跨版本静默误读）。
FAILURE_CONTEXT_SCHEMA = "rfauto-failure-context-v1"

#: 落包文件名（``<run_dir>/failure_context.json``）。
FAILURE_CONTEXT_FILE = "failure_context.json"

#: 日志尾缺省行数。
LOG_TAIL_LINES_DEFAULT = 40

#: 尾部单行最大保留字符（超长截断——launch log 单行可能是整页 JSON）。
_TAIL_LINE_MAX_CHARS = 500

#: events.jsonl 终态事件扫描行窗（deque 尾窗，防大文件全读）。
_EVENT_SCAN_LINES = 200

#: 聚合判定子面（outcome/machine/license；logs 只记 exists 不进判定——
#: 日志缺席是合法形态（无守护的人工 run），不算采集失败）。
_VERDICT_SECTIONS = ("outcome", "machine", "license")


def failure_context_path(run_dir: str | Path) -> Path:
    """run 目录 → 诊断包路径（``<run_dir>/failure_context.json``）。"""
    return Path(run_dir) / FAILURE_CONTEXT_FILE


def _iso(ts: float) -> str:
    """epoch → ISO8601（UTC，带时区后缀；本机时刻换算零歧义）。"""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    """JSON 读兜底（缺文件/损坏/非 dict = None，#105 不猜）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _tail_file(path: Path, n_lines: int) -> dict[str, Any]:
    """日志尾 N 行（best-effort；缺文件 exists=False，读失败如实报错）。"""
    name = path.name
    try:
        if not path.is_file():
            return {"file": name, "path": str(path), "exists": False,
                    "n_lines_total": None, "tail": []}
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=max(1, int(n_lines)))
        tail = [ln.rstrip("\r\n")[:_TAIL_LINE_MAX_CHARS] for ln in lines]
        return {"file": name, "path": str(path), "exists": True,
                "n_lines_total": None, "tail": tail}
    except OSError as exc:
        return {"file": name, "path": str(path), "exists": False,
                "n_lines_total": None, "tail": [],
                "error": f"{type(exc).__name__}: {exc}"}


def _last_terminal_event(path: Path) -> dict[str, Any] | None:
    """events.jsonl 尾窗内最后一条终态事件（run_failed/run_completed；
    缺文件/无终态事件 = None，#105 不猜）。"""
    try:
        if not path.is_file():
            return None
        found: dict[str, Any] | None = None
        with open(path, encoding="utf-8", errors="replace") as f:
            for ln in deque(f, maxlen=_EVENT_SCAN_LINES):
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    ev = json.loads(ln)
                except ValueError:
                    continue  # 半行/损坏行跳过（read_run_events 同口径）
                if isinstance(ev, dict) and str(ev.get("event_type")) in (
                        "run_failed", "run_completed"):
                    found = ev
        if found is None:
            return None
        data = found.get("data")
        return {"event_type": str(found.get("event_type") or ""),
                "message": str(found.get("message") or ""),
                "error": str((data or {}).get("error") or "")
                if isinstance(data, dict) else "",
                "timestamp": found.get("timestamp")}
    except OSError:
        return None


def _outcome_section(run_dir: Path) -> dict[str, Any]:
    """结局面：plan verdict + 失败 stage 清单 + 终态事件。"""
    plan = _read_json(run_dir / "campaign.plan.json")
    stages_raw = (plan or {}).get("stages") or []
    stages = [{"stage": str(s.get("stage") or ""),
               "status": str(s.get("status") or "")}
              for s in stages_raw if isinstance(s, dict)]
    failed = [s["stage"] for s in stages
              if s["status"] in ("failed", "aborted")]
    verdict = str((plan or {}).get("verdict") or "")
    terminal = _last_terminal_event(run_dir / "events.jsonl")
    has_signal = bool(verdict or stages or terminal)
    return {"ok": has_signal,
            "verdict": verdict,
            "n_stages": len(stages),
            "n_done": sum(1 for s in stages if s["status"] == "done"),
            "failed_stages": failed,
            "terminal_event": terminal,
            "reason": "" if has_signal else
            "无 campaign.plan.json 且无 events.jsonl 终态事件（非战役 run "
            "目录或产物已清）"}


def _default_probe(machine: str | None) -> dict[str, Any]:
    """机器实况生产缝（remote_service.remote_probe 单源；#139）。"""
    from rfauto.service.remote_service import remote_probe

    return remote_probe(machine)


def _default_preflight(machine: str | None) -> dict[str, Any]:
    """license 预检生产缝（remote_service.license_preflight 单源；#139）。"""
    from rfauto.service.remote_service import license_preflight

    return license_preflight(machine)


def _machine_section(
    machine: str | None,
    probe_fn: Any,
) -> dict[str, Any]:
    """机器实况面：可达性 + 端口探活摘要（异常降级 ok=False 不抛）。"""
    try:
        res = probe_fn(machine)
    except Exception as exc:  # 采集面故障如实降级（#105）
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    machines = (res or {}).get("machines") or []
    if not machines:
        return {"ok": True, "skipped": True,
                "reason": "无登记机器（本地求解世界，无远程实况可采）"}
    m = machines[0] if isinstance(machines[0], dict) else {}
    return {"ok": True,
            "skipped": False,
            "name": m.get("name"),
            "host": m.get("host"),
            "reachable": m.get("reachable"),
            "ports": m.get("ports"),
            "probe_s": m.get("probe_s")}


def _license_section(
    machine: str | None,
    preflight_fn: Any,
) -> dict[str, Any]:
    """license 面：预检 verdict + gate 摘要（异常降级 ok=False 不抛）。"""
    try:
        pf = preflight_fn(machine)
    except Exception as exc:  # 采集面故障如实降级（#105）
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pf = pf if isinstance(pf, dict) else {}
    return {"ok": True,
            "skipped": bool(pf.get("skipped")),
            "verdict": pf.get("verdict"),
            "reason": pf.get("reason"),
            "gate": pf.get("gate"),
            "machine": pf.get("machine")}


def build_failure_context(
    run_dir: str | Path,
    *,
    machine: str | None = None,
    tail_lines: int = LOG_TAIL_LINES_DEFAULT,
    exit_code: int | None = None,
    error: str | None = None,
    probe_fn: Any = None,
    preflight_fn: Any = None,
    now_fn: Any = None,
) -> dict[str, Any]:
    """聚合失败诊断快照（JSON 进出；零写盘——落盘归
    :func:`write_failure_context` 单点）。

    全部采集面 best-effort（#105）：单面失败记 ``ok=False``+error 进包，
    不拖垮其余面；聚合判定 ``verdict`` ∈ OK/PARTIAL/FAILED（全败才
    ``ok=False``，run_diagnosis 同口径）。测试经 probe_fn/preflight_fn/
    now_fn 注入假件（零网络零真实时钟，#139）。
    """
    d = Path(run_dir)
    ts = float(now_fn() if now_fn is not None else time.time())
    outcome = _outcome_section(d)
    machine_sec = _machine_section(machine, probe_fn or _default_probe)
    license_sec = _license_section(machine, preflight_fn or _default_preflight)
    logs = {
        "tail_lines": int(tail_lines),
        "files": [
            _tail_file(d / "queue_daemon_launch.log", tail_lines),
            _tail_file(d / "events.jsonl", tail_lines),
        ],
    }
    sections = {"outcome": outcome, "machine": machine_sec,
                "license": license_sec}
    n_failed = sum(1 for k in _VERDICT_SECTIONS
                   if not sections[k].get("ok"))
    if n_failed == len(_VERDICT_SECTIONS):
        agg_ok, verdict = False, "FAILED"
    elif n_failed:
        agg_ok, verdict = True, "PARTIAL"
    else:
        agg_ok, verdict = True, "OK"
    return {
        "schema": FAILURE_CONTEXT_SCHEMA,
        "run_dir": str(d),
        "captured_at": _iso(ts),
        "captured_epoch": round(ts, 3),
        "exit": {"exit_code": exit_code, "error": str(error or ""),
                 "outcome": outcome},
        "machine": machine_sec,
        "license": license_sec,
        "logs": logs,
        "verdict": verdict,
        "ok": agg_ok,
    }


def write_failure_context(
    run_dir: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """构建+落包（幂等覆盖；原子写 tmp+os.replace，半写不落正式档）。

    kwargs 透传 :func:`build_failure_context`（machine/tail_lines/
    exit_code/error/probe_fn/preflight_fn/now_fn）。run 目录不存在=error
    信封（不虚构 run 目录，append_run_event 同纪律）。
    """
    d = Path(run_dir)
    if not d.is_dir():
        return error_envelope([f"run 目录不存在: {d}"], path=None)
    context = build_failure_context(d, **kwargs)
    out = failure_context_path(d)
    tmp = out.with_name(out.name + ".tmp")
    try:
        tmp.write_text(json.dumps(context, ensure_ascii=False, indent=1,
                                  sort_keys=True, default=str),
                       encoding="utf-8")
        os.replace(tmp, out)
    except OSError as exc:
        return error_envelope([f"诊断包落盘失败: {exc}"], path=str(out))
    return ok_envelope(path=str(out), verdict=context["verdict"],
                       ok=context["ok"], context=context)


def read_failure_context(
    run_id: str | None = None,
    *,
    run_dir: str | Path | None = None,
) -> dict[str, Any]:
    """读诊断包（详情页"一键查看诊断"读面；JSON 信封进出）。

    ``run_dir`` 显式给定时直读该目录；否则 ``run_id`` 走 runs 根单段守卫
    （safe_run_id，穿越/分隔符一律拒）。缺包=``ok=True, exists=False``
    （无诊断包不是错误——非守护失败战役如实无包）。
    """
    if run_dir is not None:
        d = Path(run_dir)
        rid = d.name
    else:
        from rfauto.service._helpers import safe_run_id

        rid = safe_run_id(run_id)
        if rid is None:
            return error_envelope([f"非法 run_id: {run_id!r}"],
                                  exists=False)
        from rfauto.infra.runs_paths import resolve_runs_dir

        d = resolve_runs_dir(Path("runs") / rid)
    if not d.is_dir():
        return error_envelope([f"run 不存在: {rid}"], exists=False)
    p = failure_context_path(d)
    if not p.is_file():
        return ok_envelope(exists=False, run_id=rid, run_dir=str(d),
                           path=str(p))
    try:
        context = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return error_envelope([f"诊断包读取失败: {exc}"], exists=True,
                              run_id=rid, run_dir=str(d), path=str(p))
    if not isinstance(context, dict) \
            or context.get("schema") != FAILURE_CONTEXT_SCHEMA:
        return error_envelope(
            [f"诊断包 schema 不符（期望 {FAILURE_CONTEXT_SCHEMA}）"],
            exists=True, run_id=rid, run_dir=str(d), path=str(p))
    return ok_envelope(exists=True, run_id=rid, run_dir=str(d),
                       path=str(p), context=context)
