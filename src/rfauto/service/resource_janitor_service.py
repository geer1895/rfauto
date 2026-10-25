"""资源卫生服务（进程 janitor + 内存闸，doctor --janitor 的 service 面）。

来自真实用户实战反馈：异常退出后 release_desktop 声称成功但 ansysedt.exe
进程仍在（单机实测最多 17 个孤儿 × ~800MB，把 31GB 机器推到提交量上限，
后续 HFSS 无法再启动）。本模块提供三个 JSON 进出面：

- janitor_scan ：清点 ansysedt 族进程（含父进程链证据）+ 工作根内 AEDT
  工程锁文件。"疑似孤儿"只给证据不下结论——suspect 仅为启发式标记
  （父进程已退出/父进程是系统会话进程），是否击杀由用户判断。
- janitor_clean：白名单式清理。只接受当次扫描（内部重扫，不信任调用方
  自报）出现过的 PID/路径；白名单外入参=整单拒绝零副作用（全有或全无）。
  缺省 dry_run=True 只报不动手。
- memory_gate  ：系统可用内存阈值闸（psutil 优先、Windows ctypes 兜底），
  供"启动前可用内存不足即拒绝求解"的脚本门使用。
- lock_owner_verdict：AEDT 工程锁属主判定（aurora_l A2 席，K20/R4 P2）。
  锁格式实测（runs/ 真实样例 4 份，ASCII 文本）：内嵌
  ``DesktopProcessID=<pid>``/``DesktopProcessPath='…ansysedt.exe'`` 与
  持锁机网卡 IP（无 Host/UserName 字段）——PID 可解析即属主可判：存活
  且 ansysedt 族=owner_alive（保留锁）；已退出/被别的进程复用=owner_dead
  （可清）；判不了（目录锁/无 PID/窗内锁龄+疑似远程锁/存活通道不可用）
  一律 undetermined 保守跳过。供 em sweep ``--janitor`` 自动路径防误删
  活会话工程锁；doctor ``--janitor-clean`` 显式路径（人工闸）不经此判定。

锁文件识别口径：AEDT 工程锁是 ``<工程名>.lock``（文件或目录，与
``<工程名>.aedt`` 同目录伴生）或 ``<工程名>.aedt.lock``；不伴生 .aedt
工程的 ``*.lock``（如 runs/ 自身的收集锁）不是 AEDT 锁，不收录。
扫描只走仓内约定工作根（runs/ 双根收敛），不扫全盘。

psutil 为惰性可选依赖（对齐 adapters/hfss_batch 树杀与
pipeline/batch_guard RAM 预检的兜底口径，不在 pyproject 硬声明）：
导入失败/查询异常一律降级为如实注明通道不可用，绝不阻塞 doctor 主路径。
"""

from __future__ import annotations

import contextlib
import ctypes
import ipaddress
import os
import re
import shutil
import sys
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from rfauto.infra.runs_paths import runs_root
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["janitor_clean", "janitor_scan", "lock_owner_verdict", "memory_gate"]

# ─── 常量 ─────────────────────────────────────────────────────────────────────

#: ansysedt 进程族名前缀（ansysedt.exe 主进程及同族变体，报告原样带 name）
_AEDT_NAME_PREFIX = "ansysedt"
_AEDT_PROJ_SUFFIX = ".aedt"
_LOCK_SUFFIX = ".lock"
#: 单根锁条目上限（超即截断并如实标注，防超大 runs/ 拖垮 doctor）
_MAX_LOCK_ENTRIES = 200
#: 属主判定读锁文本上限（真实 AEDT 锁 ~1KB；超限截断只影响解析→保守跳过，
#: 不影响删除面）
_LOCK_TEXT_READ_LIMIT = 64 * 1024
#: 远程锁防线的锁龄窗：锁龄超窗（本机实测有 8-9 月旧锁、本机网卡 IP 已换
#: 一轮的漂移面）则 IP 零交集不再当作"疑似远程活会话"证据——月级旧锁还
#: 被远程活会话持有近乎不可能，判 dead 放行清理（P4 孤儿锁积累防线）；
#: 窗内锁龄 + IP 零交集 = 近期新建且非本机网卡 → 疑似远程活会话，保守跳过。
_LOCK_REMOTE_GUARD_HORIZON_S = 48 * 3600.0
#: 击杀两段（terminate→kill）各段等待秒数
_KILL_TIMEOUT_S = 10.0
#: 父进程是这些系统会话进程 = 子进程被系统收养（孤儿证据之一）
_SYSTEM_SESSION_PARENTS = {"services.exe", "wininit.exe", "smss.exe", "lsass.exe"}

_GB = float(1024**3)


# ─── 内存查询通道（psutil 优先、Windows ctypes 兜底；通道自身绝不抛）─────────


def _query_available_bytes_psutil() -> float | None:
    """psutil 通道：物理内存可用字节数（virtual_memory.available）。"""
    try:
        import psutil
    except ImportError:
        return None
    try:
        return float(psutil.virtual_memory().available)
    except Exception:  # #105：通道异常折 None，由调用方降级
        return None


def _query_available_bytes_ctypes() -> float | None:
    """Windows ctypes 兜底通道：GlobalMemoryStatusEx 的 ullAvailPhys。"""
    if sys.platform != "win32":
        return None

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_uint32),
            ("dwMemoryLoad", ctypes.c_uint32),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return None
        return float(stat.ullAvailPhys)
    except Exception:  # #105：兜底通道异常折 None
        return None


def _query_available_bytes() -> tuple[float | None, str | None]:
    """双通道顺序查询：返回 ``(可用字节, 通道名)``；两通道皆不可用→(None, None)。"""
    for name, query in (
        ("psutil", _query_available_bytes_psutil),
        ("ctypes", _query_available_bytes_ctypes),
    ):
        with contextlib.suppress(Exception):  # 通道实现变更也不许炸闸门（#105）
            value = query()
            if value is not None:
                return value, name
    return None, None


def memory_gate(min_free_gb: float) -> dict[str, Any]:
    """内存闸：系统可用内存 ≥ ``min_free_gb`` GB 才放行。

    ``ok`` 语义 = 闸放行判定（非信封调用成败）：达标 True；不达标或
    两通道都读不到可用内存（available_gb=None）都 False——后者的
    ``errors`` 非空给出通道原因，供脚本门如实拒绝而非凑绿放行。
    输出：{ok, available_gb, threshold_gb, message, channel, errors}。
    """
    threshold_gb = float(min_free_gb)
    available_bytes, channel = _query_available_bytes()
    if available_bytes is None:
        return error_envelope(
            "无法读取系统可用内存（psutil 与系统调用两通道均不可用）——闸不放行，"
            "请人工确认内存状态后重试",
            available_gb=None,
            threshold_gb=threshold_gb,
            message="未知态不放行（读不到内存）",
            channel=None,
        )
    available_gb = available_bytes / _GB
    ok = available_gb >= threshold_gb
    if ok:
        message = f"可用内存 {available_gb:.2f} GB ≥ 阈值 {threshold_gb:.2f} GB，闸放行"
    else:
        message = (
            f"可用内存 {available_gb:.2f} GB < 阈值 {threshold_gb:.2f} GB，"
            "闸不放行：先清理孤儿进程/等待释放，或下调阈值"
        )
    result = ok_envelope(
        available_gb=available_gb,
        threshold_gb=threshold_gb,
        message=message,
        channel=channel,
    )
    result["ok"] = ok  # ok 语义=闸放行判定（信封其余字段保持成功形态）
    return result


# ─── 进程清点（证据链：父进程链/内存/启动时间/CPU 累计；suspect 只标证据）─────


def _is_aedt_family(name: str | None) -> bool:
    return bool(name) and str(name).lower().startswith(_AEDT_NAME_PREFIX)


def _safe_call(fn: Any, *args: Any) -> Any:
    """逐字段 best-effort 取值（#105：权限不足/竞态退出的字段如实折 None）。"""
    try:
        return fn(*args)
    except Exception:
        return None


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    with contextlib.suppress(Exception):
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    return None


def _collect_process(p: Any) -> dict[str, Any] | None:
    """单个进程 → 证据 dict；名字不是 ansysedt 族返回 None。"""
    pid = getattr(p, "pid", None)
    name = _safe_call(p.name)
    if pid is None or not _is_aedt_family(name if isinstance(name, str) else None):
        return None

    parent = _safe_call(p.parent)
    parent_alive = parent is not None
    parent_pid = getattr(parent, "pid", None) if parent is not None else None
    parent_name = _safe_call(parent.name) if parent is not None else None

    mem = _safe_call(p.memory_info)
    rss_gb = (float(mem.rss) / _GB) if mem is not None else None
    cpu_t = _safe_call(p.cpu_times)
    cpu_time_s = (
        float(cpu_t.user + cpu_t.system + getattr(cpu_t, "children_user", 0.0)
              + getattr(cpu_t, "children_system", 0.0))
        if cpu_t is not None
        else None
    )
    create_ts = _safe_call(p.create_time)
    cmd_list = _safe_call(p.cmdline)
    cmdline = " ".join(cmd_list)[:200] if isinstance(cmd_list, list) and cmd_list else None

    # 疑似孤儿启发式：只列证据，不下结论（是否击杀由用户/显式入参决定）
    reasons: list[str] = []
    if not parent_alive:
        reasons.append("parent_exited（父进程已退出，进程被收养）")
    elif isinstance(parent_name, str) and parent_name.lower() in _SYSTEM_SESSION_PARENTS:
        reasons.append(f"parent_is_system_session（父进程为系统会话进程 {parent_name}）")

    return {
        "pid": int(pid),
        "name": name,
        "ppid": parent_pid,
        "parent_alive": parent_alive,
        "parent_name": parent_name,
        "create_time": _iso(create_ts),
        "rss_gb": rss_gb,
        "cpu_time_s": cpu_time_s,
        "cmdline": cmdline,
        "suspect": bool(reasons),
        "suspect_reasons": reasons,
    }


def _scan_processes() -> tuple[list[dict[str, Any]], str]:
    """清点 ansysedt 族进程。返回 ``(进程列表, 通道说明)``；psutil 缺失=空表+如实注记。"""
    try:
        import psutil
    except ImportError:
        return [], "psutil 不可用（未安装），进程面未清点；可 pip install psutil 后重试"
    procs: list[dict[str, Any]] = []
    try:
        for p in psutil.process_iter():
            entry = None
            with contextlib.suppress(Exception):  # 竞态退出的进程逐个跳过
                entry = _collect_process(p)
            if entry is not None:
                procs.append(entry)
    except Exception as exc:  # #105：枚举面故障不炸 doctor
        return procs, f"进程枚举中途异常（已收集 {len(procs)} 条）：{exc}"
    return procs, "psutil"


# ─── AEDT 工程锁清点（只扫仓内约定工作根，不扫全盘）──────────────────────────


def _is_aedt_lock(path: Path) -> bool:
    """``*.aedt.lock`` 命名，或与同名 ``*.aedt`` 工程文件伴生的 ``*.lock``。"""
    if path.suffix.lower() != _LOCK_SUFFIX:
        return False
    if path.name.lower().endswith(_AEDT_PROJ_SUFFIX + _LOCK_SUFFIX):
        return True
    return path.with_suffix(_AEDT_PROJ_SUFFIX).is_file()


def _scan_locks(roots: Iterable[Path]) -> tuple[list[dict[str, Any]], bool]:
    """扫工作根内 AEDT 工程锁；返回 ``(锁列表, 是否截断)``。"""
    locks: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # 剪枝：锁不会藏在 .git/内部缓存里，少走深树
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".pytest_cache"}]
            for entry_name in [*dirnames, *filenames]:
                if not entry_name.lower().endswith(_LOCK_SUFFIX):
                    continue
                path = Path(dirpath) / entry_name
                if not _is_aedt_lock(path):
                    continue
                mtime_ts = _safe_call(lambda p=path: p.stat().st_mtime)
                locks.append({
                    "path": str(path),
                    "is_dir": path.is_dir(),
                    "mtime": _iso(mtime_ts),
                    "paired_project": path.with_suffix(_AEDT_PROJ_SUFFIX).is_file(),
                })
                if len(locks) >= _MAX_LOCK_ENTRIES:
                    return locks, True
    return locks, False


def _default_scan_roots() -> list[Path]:
    """缺省扫描根：runs/ 双根收敛单源（infra.runs_paths）。"""
    return [runs_root()]


# ─── AEDT 锁属主判定（sweep --janitor 自动路径防误删闸；doctor 显式路径不经此）──

#: 锁文本属主字段（实测格式：顶层 ``DesktopProcessID=<pid>`` 一行 + Marshall
#: 块内 ``ProcID=`` 同值；只取顶层行防未来格式分叉时误取）。
_RE_LOCK_DESKTOP_PID = re.compile(r"^\s*DesktopProcessID=(\d+)\s*$", re.MULTILINE)
_RE_LOCK_DESKTOP_PATH = re.compile(r"^\s*DesktopProcessPath='([^']*)'\s*$", re.MULTILINE)
_RE_LOCK_IP_SINGLE = re.compile(r"IPAddress='([^']+)'")
_RE_LOCK_IP_VECTOR = re.compile(r"IPAddressVector\[\d+:\s*([^\]]*)\]")


def _norm_ip(value: str) -> str | None:
    """IP 归一（ipaddress 压缩形；带 zone-id 的 IPv6/垃圾串折 None）。"""
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def _read_lock_text(lock_path: str) -> str | None:
    """读锁文本（目录锁/不可读/解码全败→None=属主不可判）。"""
    path = Path(lock_path)
    if path.is_dir():
        return None
    try:
        raw = path.read_bytes()[:_LOCK_TEXT_READ_LIMIT]
    except OSError:
        return None
    try:
        return raw.decode("utf-8")
    except ValueError:
        with contextlib.suppress(Exception):  # latin-1 逐字节无损兜底
            return raw.decode("latin-1")
        return None


def _parse_lock_ips(text: str) -> list[str]:
    """锁文本内持锁机 IP（IPAddress= 单值 + IPAddressVector[n: 'a', 'b'] 向量）。"""
    ips = [m.group(1) for m in _RE_LOCK_IP_SINGLE.finditer(text)]
    for m in _RE_LOCK_IP_VECTOR.finditer(text):
        ips.extend(re.findall(r"'([^']+)'", m.group(1)))
    return ips


def _local_ips() -> set[str] | None:
    """本机网卡 IP 集合（psutil.net_if_addrs best-effort；不可得=None）。"""
    try:
        import psutil

        addrs = psutil.net_if_addrs()
    except Exception:  # psutil 缺失/接口变更：探测面故障折 None（#105）
        return None
    ips: set[str] = set()
    for addr_list in (addrs or {}).values():
        for addr in addr_list or []:
            norm = _norm_ip(str(getattr(addr, "address", "")))
            if norm:
                ips.add(norm)
    return ips or None


def _process_liveness(pid: int) -> str:
    """属主进程存活三态：``alive`` / ``dead`` / ``unknown``（不可判定）。

    dead 含"PID 已被非 ansysedt 进程复用"——锁属主特定是 ansysedt
    （DesktopProcessPath 佐证），现 PID 挂着别的进程=原属主已退出。
    """
    try:
        import psutil
    except ImportError:
        return "unknown"
    try:
        name = psutil.Process(int(pid)).name()
    except psutil.Error:  # NoSuchProcess 等=已退出
        return "dead"
    except Exception:  # 权限/竞态类：判不了就如实说（保守跳过）
        return "unknown"
    if not isinstance(name, str) or not name:
        return "unknown"
    return "alive" if _is_aedt_family(name) else "dead"


def lock_owner_verdict(
    lock_path: str | Path,
    *,
    local_ips: Collection[str] | None = None,
) -> dict[str, Any]:
    """AEDT 工程锁属主判定：内嵌 ``DesktopProcessID`` 对应进程是否存活。

    返回普通 dict（非信封）：``{verdict, pid, process_path, reason}``，
    verdict ∈ ``owner_alive``（属主活会话，锁必须保留）/ ``owner_dead``
    （属主已退出或 PID 被复用，可清）/ ``undetermined``（判不了，保守
    跳过）。判定链：

    1. 目录锁/不可读/解码全败 → undetermined；
    2. 文本无 ``DesktopProcessID`` → undetermined（无 PID 内嵌不可推断）；
    3. **远程锁防线（仅窗内锁龄）**：锁龄 < ``_LOCK_REMOTE_GUARD_HORIZON_S``
       且锁内 IP 与本机网卡 IP 皆有解析值且零交集 → undetermined（近期
       新建锁疑似远程会话，本机 PID 查证无意义）；锁龄超窗则跳过此防线
       （月级旧锁仍被远程活会话持有近乎不可能，IP 还会随网卡漂移误伤
       陈旧本机锁——runs/ 实测 8-9 月旧锁的本机 IP 已换一轮）；
    4. 属主 PID 存活且 ansysedt 族 → owner_alive（无论锁龄，活 PID 必留）；
    5. PID 已退出/被复用 → owner_dead；
    6. 存活通道不可用（psutil 缺失/查询异常）→ undetermined。

    ``local_ips``：None=内部 psutil 探测（best-effort）；传集合=直接采用
    （测试/调用方已有探测结果的注入缝）；空集合=视作探测不可得（跳过
    IP 防线）。
    """
    text = _read_lock_text(str(lock_path))
    if text is None:
        return {"verdict": "undetermined", "pid": None, "process_path": None,
                "reason": "锁不可读或是目录锁（无属主文本可解析），保守跳过"}
    pid_match = _RE_LOCK_DESKTOP_PID.search(text)
    if pid_match is None:
        return {"verdict": "undetermined", "pid": None, "process_path": None,
                "reason": "锁文本无 DesktopProcessID（属主不可推断），保守跳过"}
    pid = int(pid_match.group(1))
    path_match = _RE_LOCK_DESKTOP_PATH.search(text)
    process_path = path_match.group(1) if path_match else None
    lock_age_s = _lock_age_seconds(str(lock_path))
    lock_ips = {v for v in (_norm_ip(ip) for ip in _parse_lock_ips(text)) if v}
    probe = _local_ips() if local_ips is None else {v for v in (_norm_ip(str(i)) for i in local_ips) if v}
    guard_active = lock_age_s is None or lock_age_s < _LOCK_REMOTE_GUARD_HORIZON_S
    if guard_active and lock_ips and probe and not (lock_ips & probe):
        age_txt = (f"{lock_age_s / 3600:.1f}h" if lock_age_s is not None else "不可测")
        return {
            "verdict": "undetermined", "pid": pid, "process_path": process_path,
            "reason": f"锁内 IP {sorted(lock_ips)} 与本机网卡零交集且锁龄 "
                      f"{age_txt}（近期新建疑似远程会话锁，"
                      "本机 PID 查证无意义），保守跳过",
        }
    liveness = _process_liveness(pid)
    if liveness == "alive":
        return {"verdict": "owner_alive", "pid": pid,
                "process_path": process_path, "reason": "属主 ansysedt 进程仍存活"}
    if liveness == "dead":
        detail = "属主 PID 已退出或已被非 ansysedt 进程复用"
        if not guard_active:
            detail += f"（锁龄 {lock_age_s / 3600:.1f}h 超远程锁防线窗，陈旧锁放行清理）"
        return {"verdict": "owner_dead", "pid": pid,
                "process_path": process_path, "reason": detail}
    return {"verdict": "undetermined", "pid": pid, "process_path": process_path,
            "reason": "进程存活通道不可用（psutil 缺失或查询异常），保守跳过"}


def _lock_age_seconds(lock_path: str) -> float | None:
    """锁 mtime 距今秒数（best-effort；取不到=None=按窗内保守处理）。"""
    mtime = _safe_call(lambda: Path(lock_path).stat().st_mtime)
    if mtime is None:
        return None
    now = _safe_call(lambda: datetime.now().timestamp())
    if now is None:
        return None
    return max(float(now) - float(mtime), 0.0)


def janitor_scan(*, scan_roots: Sequence[str | Path] | None = None) -> dict[str, Any]:
    """资源卫生扫描面板（只报不动手）。

    输出信封：{ok, processes:[证据链 dict], locks:[…], summary:{…}}。
    ``processes[].suspect`` 是启发式证据标记（父进程已退出/父进程为系统
    会话进程），不是"必为孤儿"的结论；击杀决策在 janitor_clean 的显式
    白名单入参侧。
    """
    roots = [Path(r) for r in scan_roots] if scan_roots is not None else _default_scan_roots()
    processes, channel = _scan_processes()
    locks, truncated = _scan_locks(roots)
    total_rss_gb = sum(p["rss_gb"] or 0.0 for p in processes)
    return ok_envelope(
        processes=processes,
        locks=locks,
        summary={
            "n_processes": len(processes),
            "n_suspect": sum(1 for p in processes if p["suspect"]),
            "total_rss_gb": round(total_rss_gb, 3),
            "n_locks": len(locks),
            "locks_truncated": truncated,
            "scan_roots": [str(r) for r in roots],
            "process_channel": channel,
        },
    )


# ─── 白名单式清理（缺省 dry_run；全有或全无；击杀前复核进程名防 PID 复用）─────


def _normcase(path_str: str) -> str:
    return os.path.normcase(str(Path(path_str)))


def _process_name(pid: int) -> str | None:
    """击杀前复核当前进程名（防白名单后 PID 被复用）。不可得=None（拒绝击杀）。"""
    try:
        import psutil
    except ImportError:
        return None
    try:
        return psutil.Process(int(pid)).name()
    except Exception:
        return None


def _terminate_pid(pid: int, timeout_s: float = _KILL_TIMEOUT_S) -> str:
    """terminate→wait→kill 两段击杀（hfss_batch._kill_process_tree 同款口径）。

    返回 ``"killed"`` / ``"already_gone"`` / ``"failed: <原因>"``。
    """
    try:
        import psutil
    except ImportError:
        return "failed: psutil 不可用，拒绝盲杀（可用系统工具按 PID 人工处理）"
    try:
        proc = psutil.Process(int(pid))
    except psutil.Error:
        return "already_gone"
    try:
        proc.terminate()
        try:
            proc.wait(timeout=max(timeout_s / 2, 0.5))
            return "killed"
        except psutil.TimeoutExpired:
            pass
        proc.kill()
        proc.wait(timeout=max(timeout_s / 2, 0.5))
        return "killed"
    except psutil.NoSuchProcess:
        return "already_gone"
    except Exception as exc:
        return f"failed: {exc}"


def _remove_lock(path_str: str) -> str:
    """删锁文件/锁目录。返回 ``"removed"`` / ``"already_gone"`` / ``"failed: <原因>"``。"""
    path = Path(path_str)
    if not path.exists() and not path.is_dir():
        return "already_gone"
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return "removed"
    except OSError as exc:
        return f"failed: {exc}"


def janitor_clean(
    *,
    kill_pids: Sequence[int],
    locks: Sequence[str],
    dry_run: bool = True,
    scan_roots: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    """白名单式清理：只动当次扫描出现过的 PID/路径，缺省只报不动手。

    防误杀三道闸：
    1. **白名单重扫**——内部重跑一次扫描重建白名单（不信任调用方自报），
       任何入参不在白名单 → 整单拒绝零副作用（全有或全无）；
    2. **PID 复用复核**——执行击杀前复核该 PID 当前进程名仍为 ansysedt
       族，名字变了/读不到 → 该项拒杀并如实记录；
    3. **dry_run 缺省 True**——只产出 would_* 动作清单，不触进程/文件。

    白名单违反返回 error 信封（rejected 列表）；成功返回 ok 信封
    （actions 逐项结果 + summary 计数）。
    """
    roots = [Path(r) for r in scan_roots] if scan_roots is not None else _default_scan_roots()
    procs, _channel = _scan_processes()
    scan_locks, _trunc = _scan_locks(roots)
    allowed_pids = {p["pid"] for p in procs}
    allowed_locks = {_normcase(lk["path"]) for lk in scan_locks}

    pids = sorted({int(p) for p in kill_pids})
    lock_paths = list(dict.fromkeys(str(lk) for lk in locks))

    rejected: list[str] = []
    rejected += [str(p) for p in pids if p not in allowed_pids]
    rejected += [lk for lk in lock_paths if _normcase(lk) not in allowed_locks]
    if rejected:
        return error_envelope(
            [f"白名单外入参，整单拒绝（只接受当次扫描输出过的 PID/路径）: {r}" for r in rejected],
            rejected=rejected,
            actions=[],
            summary={"dry_run": bool(dry_run), "n_actions": 0},
        )

    actions: list[dict[str, Any]] = []
    n_killed = n_lock_removed = n_already_gone = n_failed = 0
    for pid in pids:
        if dry_run:
            actions.append({"kind": "process", "pid": pid, "result": "would_kill"})
            continue
        name = _process_name(pid)
        if not _is_aedt_family(name):
            actions.append({
                "kind": "process", "pid": pid,
                "result": "skipped_pid_reuse_or_unknown",
                "detail": f"击杀前复核进程名={name!r} 非 ansysedt 族，拒杀",
            })
            n_failed += 1
            continue
        result = _terminate_pid(pid)
        actions.append({"kind": "process", "pid": pid, "result": result, "name": name})
        if result == "killed":
            n_killed += 1
        elif result == "already_gone":
            n_already_gone += 1
        else:
            n_failed += 1
    for lock_path in lock_paths:
        if dry_run:
            actions.append({"kind": "lock", "path": lock_path, "result": "would_remove"})
            continue
        result = _remove_lock(lock_path)
        actions.append({"kind": "lock", "path": lock_path, "result": result})
        if result == "removed":
            n_lock_removed += 1
        elif result == "already_gone":
            n_already_gone += 1
        else:
            n_failed += 1

    return ok_envelope(
        actions=actions,
        summary={
            "dry_run": bool(dry_run),
            "n_actions": len(actions),
            "n_killed": n_killed,
            "n_lock_removed": n_lock_removed,
            "n_already_gone": n_already_gone,
            "n_failed": n_failed,
        },
    )
