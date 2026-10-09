"""remote_scheduler_service —— v1 调度面拆批切片：多机资源可见性 + 队列视图。

立项出处：2026-10-08 储备池评审（调度面拆批）；本模块
= 调度面在「多机资源可见性+队列视图」切片上的 v1 落地——**纯只读聚合**
（零发射、零写入、零杀进程；发射侧路由/资源日历全版/campaign --remote
仍是拆批余件，不在本切片）。

能力（规则 4：JSON 进出，CLI 是薄壳）：

- ``resources_view``：并发求解面资源视图——本机 openEMS/HFSS 进程互斥态
  （#261 进程指纹计数）+ 登记机器（缺省 sim_host）可达性/在跑进程数/
  磁盘余量。
- ``queue_view``：任务队列视图——job_registry 在途作业 + 单写锁
  （owner/FIFO 队长）+ 席位占用表 + 服务器在途态合并。
- ``calendar_launch_view``/``calendar_view``：资源日历机读化
  （2026-10-08）——``configs/resource_calendar.yaml``（备份窗/
  维护窗/许可席位峰谷/单机内存帽）装载 + 「当前是否可发」三态判定
  （open/risk/blocked）；缺文件=恒可发不阻塞（#105 fail-open 观测面）。

诚实边界（#122 家法，随信封落账）：

- **在跑任务数 = 进程 census 计数**（OE python 家族指纹 + ansysedt
  grpcsrv），不是 license 席位数（G6 教训：端口 OPEN≠席位可用；lmstat
  席位级查询仍未接线，见 remote_service.license_preflight 同款口径）；
- **best-effort（#105）**：本机枚举失败/服务器不可达/SSH 凭据缺失/查询
  失败，对应子面降级 ``state="unknown"``（reason 留痕），信封恒
  ``ok=True``——观测面绝不阻塞；
- **凭据与主机名/IP 不落信封**：机器只以注册表键名出现（cfg.host /
  ssh_password 恒不出现在返回 dict）；
- SSH 凭据缺失 = ``ssh.auth="missing_credentials"`` 如实（不猜不试，
  remote_status 同款口径）；机器不可达时 SSH 不发起。
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.infra.desktop_guard import list_ansysedt_processes
from rfauto.infra.remote_machines import (
    ENV_REMOTE_SSH_PASSWORD,
    ENV_REMOTE_SSH_USER,
    RemoteMachineConfig,
    SshTransport,
    load_remote_machines,
    probe_machine,
    resolve_machine,
)
from rfauto.service.envelope import ok_envelope
from rfauto.service.job_registry import get_job_registry, get_write_lock
from rfauto.service.remote_service import remote_mutex_command

__all__ = [
    "CALENDAR_SCHEMA",
    "HFSS_MUTEX_FINGERPRINT",
    "OE_MUTEX_FINGERPRINT",
    "QUEUE_ACTIVE_STATES",
    "RESOURCE_CALENDAR_FILE",
    "calendar_launch_view",
    "calendar_view",
    "default_resource_calendar_path",
    "local_hfss_view",
    "local_openems_view",
    "queue_view",
    "remote_resources",
    "resources_view",
]

# ─── #261 通道互斥指纹（视图侧常量） ─────────────────────────────────────────
# OE 语义同源 remote_oe_service._MUTEX_FINGERPRINT（进程内 FDTD.Run 的
# python 家族；#261：本仓 openEMS 非 openEMS.exe，进程域钉 python.exe）——
# 视图侧独立常量，避免跨席共享文件 hunk 耦合；命令构造单源复用
# remote_service.remote_mutex_command（G5 全程单引号零双引号）。
#: 语义自排除（#261 自锁红线）：指纹词元均非本 CLI 调用链命令行词元
#（``rfauto remote resources`` 不含 _rfauto_runner/simulation.py/…）。
OE_MUTEX_FINGERPRINT = "_rfauto_runner|simulation\\.py|driver\\.py|fd_oe_campaign"
#: HFSS 通道：ansysedt 的 grpcsrv 实例（视图口径=任意端口 grpcsrv；
# per-seat 精确指纹仅在发射互斥面使用，见 remote_service.remote_hfss_smoke）。
HFSS_MUTEX_FINGERPRINT = "grpcsrv"

#: 队列在途态口径（queue_view.active 统计域；终态不在内）。
QUEUE_ACTIVE_STATES = ("running", "cancel_requested")

#: remote_mutex_command 命中行协议形态（``pid|commandline``，同源正则）。
_HIT_LINE_RE = re.compile(r"^\d+\|")

_GB = 1024.0**3

# ─── 资源日历（机读化：备份窗/维护窗/许可席位峰谷转机读） ────────────────
#: 日历缺省文件名（``configs/resource_calendar.yaml``，仓根锚定；schema 与
#: 窗语义见该文件头注）。
RESOURCE_CALENDAR_FILE = "resource_calendar.yaml"
#: 日历 schema 版本串（文件 ``schema`` 键；不一致只告警不拒载——前向兼容）。
CALENDAR_SCHEMA = "rfauto-resource-calendar-v1"

#: 日历三态（launchable 语义：open/risk=True 可发；blocked=False 不可发）。
#: - ``open``：窗外地带（或缺省未配置日历=恒可发，#105 fail-open 观测面）；
#: - ``risk``：备份窗内——可发但风险如实落账（remote_oe_service
#:   ``backup_window_risk`` 同口径：overnight 队列合法用例，操作方自负）；
#: - ``blocked``：维护窗内——不可发射（fail-closed 门，不硬打）。
_CALENDAR_STATE_OPEN = "open"
_CALENDAR_STATE_RISK = "risk"
_CALENDAR_STATE_BLOCKED = "blocked"


def _count_hits(out: str) -> int:
    """协议行计数（``数字|`` 前缀；探针 stdout 杂行不误计）。"""
    return sum(1 for ln in out.splitlines() if _HIT_LINE_RE.match(ln.strip()))


def _unknown(reason: str) -> dict[str, Any]:
    """子面降级形态（#105：宁 unknown 不阻塞；reason 必给留痕）。"""
    return {"state": "unknown", "busy": None, "n_procs": None,
            "reason": reason}


# ─── 本机进程互斥态（#261 本机侧） ───────────────────────────────────────────

def _ps_capture(command: str, timeout_s: float = 30.0) -> tuple[bool, str]:
    """本机 PowerShell 只读探针：rc==0 → (True, stdout)；异常/超时 →
    (False, "")（best-effort，#105——枚举失败由调用方降级 unknown）。"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return r.returncode == 0, r.stdout or ""


def local_openems_view() -> dict[str, Any]:
    """本机 openEMS 通道互斥态（python 家族指纹进程计数，#261）。

    Returns
    -------
    dict
        ``{"state": "ok"/"unknown", "busy": bool|None,
        "n_procs": int|None, "reason": str|None}``。
    """
    ok, out = _ps_capture(remote_mutex_command("python.exe", OE_MUTEX_FINGERPRINT))
    if not ok:
        return _unknown(
            f"本机 python 进程枚举失败/超时: {out[:80]}" if out
            else "本机 python 进程枚举失败/超时（#105 降级 unknown）")
    n = _count_hits(out)
    return {"state": "ok", "busy": n > 0, "n_procs": n, "reason": None}


def local_hfss_view() -> dict[str, Any]:
    """本机 HFSS 通道互斥态（ansysedt 进程计数；desktop_guard 枚举单源）。

    进程计数口径含他轨合法 GUI 桌面（可见性视图≠license 视图，诚实边界）。
    """
    try:
        procs = list_ansysedt_processes()
    except Exception as exc:  # #105：枚举失败降级 unknown 不阻塞
        return _unknown(f"ansysedt 枚举失败: {type(exc).__name__}")
    grpc = sum(1 for p in procs
               if "grpcsrv" in str(p.get("cmdline", "")).lower())
    return {"state": "ok", "busy": len(procs) > 0, "n_procs": len(procs),
            "n_grpcsrv": grpc, "reason": None}


# ─── 登记机器资源面（可达性/在跑进程数/磁盘余量） ─────────────────────────────

def _drive_letter_of(work_root: str) -> str | None:
    """服务器侧工作根 → 盘符（``E:\\rfauto_remote`` → ``E:``；无盘符 None）。"""
    m = re.match(r"^([A-Za-z]):", str(work_root or ""))
    return m.group(1).upper() + ":" if m else None


def _disk_free_view(transport: Any, work_root: str) -> dict[str, Any]:
    """服务器侧工作根盘符磁盘余量（只读 Win32_LogicalDisk；G5 单引号）。"""
    drive = _drive_letter_of(work_root)
    if drive is None:
        return {"state": "unknown", "free_gb": None, "drive": None,
                "reason": "机器未登记 hfss.project_root（盘符无从推导）"}
    cmd = (
        "Get-CimInstance Win32_LogicalDisk | "
        f"Where-Object {{ $_.DeviceID -eq '{drive}' }} | "
        "ForEach-Object { '{0}|{1}' -f $_.DeviceID, $_.FreeSpace }"
    )
    rc, out, err = transport.run_command(cmd, timeout_s=20.0)
    if rc != 0:
        return {"state": "unknown", "free_gb": None, "drive": drive,
                "reason": f"磁盘查询失败 rc={rc}: {err[:80]}"}
    for ln in out.splitlines():
        ln = ln.strip()
        if "|" not in ln:
            continue
        dev, _, raw = ln.partition("|")
        if dev.strip().upper() != drive:
            continue
        try:
            return {"state": "ok", "free_gb": round(float(raw.strip()) / _GB, 1),
                    "drive": drive, "reason": None}
        except ValueError:
            break
    return {"state": "unknown", "free_gb": None, "drive": drive,
            "reason": "磁盘余量输出不可解析（协议行 E:|<bytes> 缺失）"}


def _remote_channel_view(
    transport: Any, process_name: str, fingerprint: str, label: str,
) -> dict[str, Any]:
    """服务器侧单通道在跑进程计数（remote_mutex_command 单源命令）。"""
    rc, out, err = transport.run_command(
        remote_mutex_command(process_name, fingerprint), timeout_s=30.0)
    if rc != 0:
        return _unknown(f"服务器 {label} 进程查询失败 rc={rc}: {err[:80]}")
    n = _count_hits(out)
    return {"state": "ok", "busy": n > 0, "n_procs": n, "reason": None}


def _has_ssh_credentials(cfg: RemoteMachineConfig) -> bool:
    """凭据判定（remote_service._ssh_status 同款口径，不猜不试）。"""
    has_user = bool(cfg.ssh_user or os.environ.get(ENV_REMOTE_SSH_USER))
    has_secret = bool(
        cfg.ssh_key_path or cfg.ssh_password
        or os.environ.get(ENV_REMOTE_SSH_PASSWORD)
    )
    return has_user and has_secret


def remote_resources(machine: str | None = None) -> dict[str, Any]:
    """登记机器资源面（可达性/在跑进程数/磁盘余量；best-effort 纯只读）。

    机器不可达/凭据缺失/SSH 链路失败 → 对应子面 ``state="unknown"``（#105），
    信封恒成立（本函数不抛；未知机器名仍按注册表语义抛 RemoteConfigError）。

    Returns
    -------
    dict
        ``{"machine": 注册表键名|None, "state", "reason", "reachable",
        "ports": {语义名: {open, latency_ms}}, "ssh", "openems", "hfss",
        "disk", "n_tasks"}``。**主机名/IP 与凭据恒不落信封**。
        ``state``：ok（三子面全 ok）/ partial（部分降级）/ unknown（全降级
        或无 SSH 面）。``n_tasks`` = OE+HFSS 两通道在跑进程数合计（census
        口径，非 license 席位；任一**通道** unknown 时为 None——半边 census
        不凑数，#122；磁盘面降级不影响 n_tasks）。
    """
    machines = load_remote_machines()
    if machine is None and not machines:
        return {
            "machine": None, "state": "no_machine",
            "reason": "无登记机器（本地模式）", "reachable": None,
            "ports": {}, "ssh": None,
            "openems": _unknown("无登记机器"),
            "hfss": _unknown("无登记机器"),
            "disk": {"state": "unknown", "free_gb": None, "drive": None,
                     "reason": "无登记机器"},
            "n_tasks": None,
        }
    cfg = resolve_machine(machine, machines)

    view: dict[str, Any] = {
        "machine": cfg.name, "reachable": None, "ports": {}, "ssh": None,
        "openems": _unknown("未探测"), "hfss": _unknown("未探测"),
        "disk": {"state": "unknown", "free_gb": None, "drive": None,
                 "reason": "未探测"},
        "n_tasks": None, "state": "unknown", "reason": None,
    }
    try:
        probe = probe_machine(cfg)
    except Exception as exc:  # #105：探活异常按不可达降级
        probe = {"reachable": None, "ports": {},
                 "probe_error": type(exc).__name__}
    reachable = probe.get("reachable")
    view["reachable"] = bool(reachable) if reachable is not None else None
    view["ports"] = {
        str(label): {"open": bool(row.get("open")),
                     "latency_ms": row.get("latency_ms")}
        for label, row in (probe.get("ports") or {}).items()
    }

    def _all_unknown(reason: str) -> None:
        view["openems"] = _unknown(reason)
        view["hfss"] = _unknown(reason)
        view["disk"] = {"state": "unknown", "free_gb": None, "drive": None,
                        "reason": reason}
        view["state"] = "unknown"
        view["reason"] = reason

    if not _has_ssh_credentials(cfg):
        view["ssh"] = {"auth": "missing_credentials"}
        _all_unknown("SSH 凭据缺失（RFAUTO_REMOTE_SSH_USER/PASSWORD 或 "
                     "local 覆盖）——在跑/磁盘面如实 unknown 不猜不试")
        return view
    view["ssh"] = {"auth": "registered"}
    if reachable is not True:
        reason = "机器不可达（TCP 探活不通）——SSH 不发起，子面 unknown"
        _all_unknown(reason)
        return view

    transport = None
    try:
        transport = SshTransport(cfg)
        transport.connect()
        view["ssh"] = {"auth": "ok"}
        oe = _remote_channel_view(
            transport, "python.exe", OE_MUTEX_FINGERPRINT, "openEMS")
        hfss = _remote_channel_view(
            transport, "ansysedt.exe", HFSS_MUTEX_FINGERPRINT, "HFSS")
        disk = _disk_free_view(transport, cfg.hfss_project_root)
        view["openems"], view["hfss"], view["disk"] = oe, hfss, disk
        # n_tasks=两通道进程 census 合计（与磁盘面无关）；任一通道 unknown
        # → 合计 None 不凑数（#122：半边 census 不冒充全量）。
        counts = [f.get("n_procs") for f in (oe, hfss) if f["state"] == "ok"]
        view["n_tasks"] = int(sum(counts)) if len(counts) == 2 else None
        states = [f["state"] for f in (oe, hfss, disk)]
        if all(s == "ok" for s in states):
            view["state"] = "ok"
        elif all(s != "ok" for s in states):
            view["state"] = "unknown"
        else:
            view["state"] = "partial"
            bad = [k for k, f in (("openems", oe), ("hfss", hfss), ("disk", disk))
                   if f["state"] != "ok"]
            view["reason"] = f"子面降级 unknown: {','.join(bad)}"
    except Exception as exc:  # #105：SSH 链路裸抛整面降级
        _all_unknown(f"SSH 链路失败: {type(exc).__name__}")
        view["ssh"] = {"auth": "failed", "error": type(exc).__name__}
    finally:
        if transport is not None:
            with contextlib.suppress(Exception):
                transport.close()  # #105：关闭失败不影响视图主路径
    return view


# ─── 聚合视图（resources / queue） ───────────────────────────────────────────

def resources_view(machine: str | None = None) -> dict[str, Any]:
    """并发求解面资源视图（本机进程互斥态 + 登记机器资源面 + 资源日历，
    纯只读）。

    Returns
    -------
    dict
        ``{"ok": True, "local": {"openems", "hfss"},
        "remote": remote_resources(...), "calendar": calendar_launch_view(...)}``
        ——子面降级不翻 ok（#105）；``calendar.launchable`` =「当前是否可发」
        状态字段（缺省未配置日历=恒可发，机读化消费口）。
    """
    return ok_envelope(
        local={
            "openems": local_openems_view(),
            "hfss": local_hfss_view(),
        },
        remote=remote_resources(machine),
        calendar=calendar_launch_view(),
    )


def _queue_job_row(snapshot: dict[str, Any]) -> dict[str, Any]:
    """job 快照 → 队列行（瘦形：去 result 载荷，error 截头——视图不搬运结果）。"""
    return {
        "job_id": snapshot.get("job_id"),
        "state": snapshot.get("state"),
        "run_id": snapshot.get("run_id") or "",
        "seats": list(snapshot.get("seats") or []),
        "progress_pct": snapshot.get("progress_pct"),
        "stage": snapshot.get("stage") or "",
        "created_at": snapshot.get("created_at"),
        "finished_at": snapshot.get("finished_at"),
        "error": str(snapshot.get("error") or "")[:120],
    }


def queue_view(machine: str | None = None) -> dict[str, Any]:
    """任务队列视图（job_registry 在途作业 × 单写锁 × 席位 × 服务器在途态）。

    合并口径（全部进程内/只读）：

    - ``jobs``：job_registry 全体在册快照瘦形（注册序；跨进程历史 run 走
      ``jobs status``/meta.json 磁盘回落链，不在本视图）；
    - ``write_lock``：单写锁 owner + FIFO 队长（并发 hfss job 的排队面）；
    - ``seat_occupancy``：席位 → 占用 job 列表（记账实时快照）；
    - ``remote``：:func:`remote_resources` 同源服务器在途态（unknown 降级
      原样透传）。
    """
    registry = get_job_registry()
    rows = [_queue_job_row(s) for s in registry.snapshots()]
    active = [r for r in rows if r["state"] in QUEUE_ACTIVE_STATES]
    lock = get_write_lock()
    return ok_envelope(
        jobs=rows,
        counts={
            "n_jobs": len(rows),
            "n_active": len(active),
            "n_waiting": int(lock.queue_length),
        },
        write_lock={"owner": lock.owner, "queue_length": int(lock.queue_length)},
        seat_occupancy=registry.seat_occupancy(),
        remote=remote_resources(machine),
    )


# ─── 资源日历（configs/resource_calendar.yaml 机读化） ─────────────────

def default_resource_calendar_path() -> Path:
    """日历缺省路径：``configs/resource_calendar.yaml``（仓根锚定，
    remote_machines.default_remote_config_path 同款锚法，随 cwd 漂移免疫）。"""
    return Path(__file__).resolve().parents[3] / "configs" / RESOURCE_CALENDAR_FILE


def _parse_hhmm(value: Any) -> int | None:
    """``"HH:MM"`` → 当日分钟数（``"02:50"`` → 170）；非法如实 None。"""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value or ""))
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 24 or mm > 59 or (hh == 24 and mm > 0):
        return None
    return hh * 60 + mm


def _window_bounds(win: Any) -> tuple[int, int] | None:
    """窗条目（``{start, end}``）→ (起始分钟, 结束分钟)；非法 None。

    ``start > end`` = 跨午夜窗（如 ``23:00–02:00``），判定按环绕语义。
    """
    if not isinstance(win, dict):
        return None
    start = _parse_hhmm(win.get("start"))
    end = _parse_hhmm(win.get("end"))
    if start is None or end is None:
        return None
    return start, end


def _window_contains(bounds: tuple[int, int], now_min: int) -> bool:
    """时刻是否落在窗内（闭区间；start>end=跨午夜环绕判定）。"""
    start, end = bounds
    if start <= end:
        return start <= now_min <= end
    return now_min >= start or now_min <= end


def _window_label(kind: str, index: int, bounds: tuple[int, int]) -> str:
    def _fmt(minutes: int) -> str:
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    return (f"{kind}[{index}] {_fmt(bounds[0])}-{_fmt(bounds[1])}")


def load_resource_calendar(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """加载资源日历（纯只读；**缺文件/不可读/非法 YAML = 恒可发降级**，
    #105 fail-open 观测面——日历绝不阻塞发射主路径）。

    Returns
    -------
    dict
        ``{"ok": True, "loaded": bool, "calendar_path": str|None,
        "schema": str|None, "reason": str|None,
        "backup_windows": [(start, end)], "maintenance_windows": [...],
        "license_peaks": {solver: bounds}, "machine_caps": {machine: {...}},
        "warnings": [str]}``——窗为分钟数二元组（解析失败的条目跳过并
        记 warning，不整文件拒载）。
    """
    p = Path(path) if path is not None else default_resource_calendar_path()
    # 信封构造器单源（契约 §4：新面禁裸 ok dict——AST 守卫冻结增长）
    out: dict[str, Any] = ok_envelope(
        loaded=False, calendar_path=str(p), schema=None, reason=None,
        backup_windows=[], maintenance_windows=[], license_peaks={},
        machine_caps={}, warnings=[])
    if not p.is_file():
        out["reason"] = (
            f"资源日历缺省未配置（{p} 不存在）——恒可发不阻塞"
            "（#105 fail-open 观测面）")
        return out
    import yaml

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        out["reason"] = (f"资源日历不可读/非法 YAML（{type(exc).__name__}）"
                         "——降级恒可发不阻塞")
        return out
    if not isinstance(data, dict):
        out["reason"] = "资源日历顶层必须是映射——降级恒可发不阻塞"
        return out
    out["loaded"] = True
    out["schema"] = str(data.get("schema") or "") or None
    if out["schema"] != CALENDAR_SCHEMA:
        out["warnings"].append(
            f"schema={out['schema']!r} 非 {CALENDAR_SCHEMA}（前向兼容照载）")

    def _windows(key: str) -> list[tuple[int, int]]:
        got: list[tuple[int, int]] = []
        for i, win in enumerate(data.get(key) or []):
            bounds = _window_bounds(win)
            if bounds is None:
                out["warnings"].append(f"{key}[{i}] 条目非法已跳过: {win!r}")
                continue
            got.append(bounds)
        return got

    out["backup_windows"] = _windows("backup_windows")
    out["maintenance_windows"] = _windows("maintenance_windows")
    peaks = data.get("license_seats") or {}
    if isinstance(peaks, dict):
        for solver, row in peaks.items():
            row = row if isinstance(row, dict) else {}
            raw = row.get("peak")
            bounds = (_window_bounds(raw) if isinstance(raw, dict)
                      else _peak_span(raw))
            if bounds is None:
                if raw:
                    out["warnings"].append(
                        f"license_seats.{solver}.peak 非法已忽略: {raw!r}")
                continue
            out["license_peaks"][str(solver)] = bounds
    caps = data.get("machine_caps") or {}
    if isinstance(caps, dict):
        out["machine_caps"] = {str(k): (v if isinstance(v, dict) else {})
                               for k, v in caps.items()}
    return out


def _peak_span(value: Any) -> tuple[int, int] | None:
    """``"HH:MM-HH:MM"`` 峰谷串 → (起始, 结束) 分钟二元组；非法 None。"""
    m = re.fullmatch(r"\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*",
                     str(value or ""))
    if not m:
        return None
    start = _parse_hhmm(m.group(1))
    end = _parse_hhmm(m.group(2))
    if start is None or end is None:
        return None
    return start, end


def calendar_launch_view(
    now_fn: Callable[[], time.struct_time] | None = None,
    path: str | Path | None = None,
    calendar: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """「当前是否可发」判定（资源日历消费面；纯函数，零网络零写入）。

    判定序（先 blocked 后 risk，维护窗优先级高于备份窗）：

    1. 日历缺省未配置/不可读/非法（``loaded=False``）→ ``open`` 恒可发
       （#105 fail-open：观测面绝不阻塞发射主路径）；
    2. 维护窗命中 → ``blocked`` 不可发射（fail-closed 门）；
    3. 备份窗命中 → ``risk`` 可发但风险随信封落账（remote_oe_service
       ``backup_window_risk`` 同口径；许可席位峰谷为标注面不进门——G6
       教训：时段≠席位可用）；
    4. 其余 → ``open``。

    ``calendar`` 可注入已加载日历（:func:`load_resource_calendar` 产物，
    调用方复用装载结果时免二次读盘）。
    """
    tm = (now_fn or time.localtime)()
    now_min = tm.tm_hour * 60 + tm.tm_min
    cal = calendar if calendar is not None else load_resource_calendar(path)
    # 信封构造器单源（契约 §4）
    base: dict[str, Any] = ok_envelope(
        loaded=bool(cal.get("loaded")),
        calendar_path=cal.get("calendar_path"),
        state=_CALENDAR_STATE_OPEN,
        launchable=True,
        reason=None,
        windows_hit=[],
        backup_risk=False,
        now_hhmm=f"{now_min // 60:02d}:{now_min % 60:02d}")
    if not cal.get("loaded"):
        base["reason"] = cal.get("reason")
        return base
    for i, bounds in enumerate(cal.get("maintenance_windows") or []):
        if _window_contains(bounds, now_min):
            base["windows_hit"].append(
                _window_label("maintenance_windows", i, bounds))
    if base["windows_hit"]:
        base["state"] = _CALENDAR_STATE_BLOCKED
        base["launchable"] = False
        base["reason"] = ("维护窗内不可发射（fail-closed 门，不硬打）: "
                          + ", ".join(base["windows_hit"]))
        return base
    for i, bounds in enumerate(cal.get("backup_windows") or []):
        if _window_contains(bounds, now_min):
            base["windows_hit"].append(
                _window_label("backup_windows", i, bounds))
    if base["windows_hit"]:
        base["state"] = _CALENDAR_STATE_RISK
        base["backup_risk"] = True
        base["reason"] = ("备份窗内发射（可发，风险如实落账——overnight "
                          "队列合法用例）: " + ", ".join(base["windows_hit"]))
    return base


def calendar_view(
    now_fn: Callable[[], time.struct_time] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """资源日历视图信封（发射窗判定 + 机读日历内容回显；纯只读）。

    Returns
    -------
    dict
        ``{"ok": True, "launch": calendar_launch_view(...),
        "calendar": load_resource_calendar(...)}``——缺文件不翻 ok（#105）。
    """
    cal = load_resource_calendar(path)
    launch = calendar_launch_view(now_fn=now_fn, calendar=cal)
    return ok_envelope(
        launch=launch,
        calendar={
            "loaded": cal.get("loaded"),
            "schema": cal.get("schema"),
            "reason": cal.get("reason"),
            "warnings": cal.get("warnings") or [],
            "backup_windows": [
                {"start": f"{s // 60:02d}:{s % 60:02d}",
                 "end": f"{e // 60:02d}:{e % 60:02d}"}
                for s, e in (cal.get("backup_windows") or [])],
            "maintenance_windows": [
                {"start": f"{s // 60:02d}:{s % 60:02d}",
                 "end": f"{e // 60:02d}:{e % 60:02d}"}
                for s, e in (cal.get("maintenance_windows") or [])],
            "license_peaks": {
                k: {"start": f"{s // 60:02d}:{s % 60:02d}",
                    "end": f"{e // 60:02d}:{e % 60:02d}"}
                for k, (s, e) in (cal.get("license_peaks") or {}).items()},
            "machine_caps": cal.get("machine_caps") or {},
        },
    )
