"""seat 粒度三证判活 service（T-O12，aurora_o）——watchdog 方法论形式化。

把存活探针方法论（#157 家法"先看命令行"/#323 watcher/#177 心跳/#261 census）
从"散落脚本+踩坑条目"收敛为服务层确定性函数（规则 4 JSON 进出，信封构造器
家法）。三证判定表（纯函数 :func:`judge_liveness`，同采样两次判定逐位一致）：

===================  ===================  ====================  =========
进程存活 e1           CPU 增长 e2          产物 mtime e3         判定
===================  ===================  ====================  =========
False                —                    —                     dead
None（无法验证）      —                    —                     unknown
True                 任一 True            （另一证任意）         alive
True                 全 False（实测）      （含 e3 缺席）         stalled
True                 None                 False（实测停滞）      stalled
True                 None                 None                  unknown
===================  ===================  ====================  =========

证据缺失=unknown **不凑判**（#122 家法：无对如实 UNKNOWN）——"未配置产物
glob"与"glob 零命中"都不是 False，是 None；CPU 采样失败同样 None。

CPU 两次采样（#157 整树消失的早期形态=进程在而 CPU 零增长）：Windows 用
ctypes ``GetProcessTimes``（纯 stdlib，无 psutil 依赖）/POSIX 读
``/proc/<pid>/stat``；采样失败 → None。产物 mtime 新鲜度（#268 stdio 缓冲
伪象案例语义）：进程 CPU 低但产物在写 → alive。

信封契约：观测面判定恒 ``ok=True``（unknown 态也是——观测成功且如实）；
error 信封只留给调用方误用（target 形态不识别）。

``watch_loop`` 为**可调用生成器函数、非线程**（#105 best-effort）：默认无人
调用=零后台行为零文件写（行为逐字节同现状）；显式调用时每轮采样一行 jsonl
落 **白名单单根** ``runs/watchdog/<seat>/``（写面守卫同 T-O11 湖隔离家法），
写失败降级如实标注不抛（sink_write_ok=False）。

消费面预留：W5 席收割/长跑判读将消费本模块（席位任务书"发射后存活复核"）；
CLI 不落——service 层先行（任务书口径）；remote_scheduler_service.resources_view
是机器粒度，本模块是 seat 粒度，互不替代。
"""

from __future__ import annotations

import glob as _globmod
import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.remote_service.mutex import remote_mutex_command

__all__ = [
    "DEFAULT_RUN_DIR_GLOBS",
    "DEFAULT_STALL_WINDOW_S",
    "WATCHDOG_ROOT_REL",
    "campaign_liveness_summary",
    "census_command",
    "judge_artifact_only",
    "judge_liveness",
    "sample_cpu_seconds",
    "seat_liveness_view",
    "validate_watch_root",
    "watch_loop",
]

#: watch_loop jsonl 白名单单根（相对仓根；湖隔离守卫同 T-O11 家法）。
WATCHDOG_ROOT_REL = "runs/watchdog"
#: 产物新鲜度缺省窗（s）：距今超过该窗视为停滞。
DEFAULT_STALL_WINDOW_S = 900.0
#: run 目录批视图缺省产物 glob（目录一层非递归；消费面按 campaign 覆写）。
DEFAULT_RUN_DIR_GLOBS = ("*.log", "*.json", "*.jsonl", "*.csv", "*.yaml")

_CENSUS_TIMEOUT_S = 30.0
_HIT_LINE_RE = re.compile(r"^\d+\|")
_CPU_STATE = ("alive", "stalled", "dead", "unknown")


def _norm_key(p: Path) -> str:
    r"""路径比较键：normcase + 斜杠归一 + 显式 lower（Windows normcase 会把
    ``/`` 转 ``\``——前缀比较必须先换回斜杠；POSIX normcase 恒等，故显式
    lower 兜底，AGENTS 安全比较家法）。"""
    return os.path.normcase(p.as_posix()).replace("\\", "/").lower()


def repo_root() -> Path:
    """仓根（editable 安装下 src/rfauto/service 的 parents[3]）。"""
    return Path(__file__).resolve().parents[3]


# ── 三证判定表（纯函数——确定性③的单源） ─────────────────────────────────────


def judge_liveness(
    alive: bool | None, cpu_growing: bool | None, artifact_fresh: bool | None
) -> tuple[str, str | None]:
    """三证 → (state, reason)。state ∈ alive/stalled/dead/unknown（不凑判，
    #122）。任一正证（CPU 增长/产物新鲜）→ alive；全负证（实测零增长/实测
    停滞）且无正证 → stalled；两证全缺 → unknown；进程死 → dead。"""
    if alive is False:
        return "dead", "进程不存在/已退出"
    if alive is None:
        return "unknown", "进程存活无法验证（census 不可用）——不凑判"
    positive = cpu_growing is True or artifact_fresh is True
    if positive:
        return "alive", None
    negative = cpu_growing is False or artifact_fresh is False
    if negative:
        return "stalled", "进程在而 CPU 零增长且/或产物 mtime 停滞（两证数字见 evidence）"
    return "unknown", "进程在但 CPU 与产物两证均无法取证——不凑判"


def judge_artifact_only(artifact_fresh: bool | None) -> tuple[str, str | None]:
    """无进程证 target（run 目录行）的产物单证判定：新鲜→alive、停滞→
    stalled、证据缺失→unknown 不凑判（#122）。进程证缺席在 reason 如实
    注明，不冒充三证齐。"""
    if artifact_fresh is True:
        return "alive", "仅产物证（进程证缺席）：产物 mtime 在窗内"
    if artifact_fresh is False:
        return "stalled", "仅产物证（进程证缺席）：产物 mtime 停滞超窗"
    return "unknown", "无进程证且产物证据缺失——不凑判"


# ── 证据采样 ─────────────────────────────────────────────────────────────────


def sample_cpu_seconds(pid: int) -> float | None:
    """进程累计 CPU 时间（kernel+user，秒；纯 stdlib）。Windows=ctypes
    ``GetProcessTimes``；POSIX=``/proc/<pid>/stat`` utime+stime。取样失败
    （pid 无效/已退/无权限）→ None（证据缺失，不凑 0——0 与缺失语义不同）。"""
    try:
        pid_i = int(pid)
    except (TypeError, ValueError):
        return None
    if pid_i <= 0:
        return None
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid_i)
        if not handle:
            return None
        try:
            create_t = ctypes.c_ulonglong()
            exit_t = ctypes.c_ulonglong()
            kernel_t = ctypes.c_ulonglong()
            user_t = ctypes.c_ulonglong()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(create_t),
                ctypes.byref(exit_t),
                ctypes.byref(kernel_t),
                ctypes.byref(user_t),
            ):
                return None
            return (kernel_t.value + user_t.value) / 1e7
        finally:
            kernel32.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid_i}/stat").read_text(encoding="utf-8", errors="replace")
        parts = stat.rsplit(")", 1)[1].split()
        utime, stime = int(parts[11]), int(parts[12])
        return (utime + stime) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError):
        return None


def census_command(process_name: str | None, fingerprint: str) -> str:
    """#261 census 探针命令（单源复用 remote_service.mutex 的
    ``pid|commandline`` 协议命令；process_name=None 时本地派生无进程名过滤
    变体，协议行形态一致）。"""
    if process_name:
        return remote_mutex_command(str(process_name), str(fingerprint))
    return (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.CommandLine -match '{fingerprint}' }} | "
        "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }"
    )


def default_census(process_name: str | None, fingerprint: str) -> list[str] | None:
    """本机 census 缺省实现：跑探针命令返回命中行；失败 → None（调用方
    按 unknown 处理，不凑判）。"""
    try:
        run = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", census_command(process_name, fingerprint)],
            capture_output=True, text=True, timeout=_CENSUS_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if run.returncode != 0:
        return None
    return (run.stdout or "").splitlines()


def _census_alive(
    spec: Mapping[str, Any], census_fn: Callable[[str | None, str], list[str] | None]
) -> tuple[bool | None, int | None, str | None]:
    """census 证 → (alive, matched_pid, reason)。None=不可验证（unknown）。"""
    fingerprint = str(spec.get("fingerprint") or "")
    if not fingerprint:
        return None, None, "census 指纹缺失"
    try:
        re.compile(fingerprint)
    except re.error as exc:
        return None, None, f"census 指纹非法正则：{exc}"
    lines = census_fn(spec.get("process_name"), fingerprint)
    if lines is None:
        return None, None, "census 进程查询失败——证据缺失不凑判"
    hits = [ln.strip() for ln in lines if _HIT_LINE_RE.match(ln.strip())]
    if not hits:
        return False, None, None
    try:
        pid = int(hits[0].split("|", 1)[0])
    except ValueError:
        return None, None, "census 命中行 pid 解析失败"
    return True, pid, None


def _cpu_evidence(
    pid: int,
    sample_fn: Callable[[int], float | None],
    interval_s: float,
    sleep_fn: Callable[[float], None],
    min_delta_s: float,
) -> tuple[bool | None, dict[str, Any]]:
    """两次采样 CPU 增长证 → (growing|None, info)。任一次取样失败 → None。"""
    first = sample_fn(pid)
    sleep_fn(max(float(interval_s), 0.0))
    second = sample_fn(pid)
    info: dict[str, Any] = {"first_s": first, "second_s": second,
                            "delta_s": None, "min_delta_s": float(min_delta_s)}
    if first is None or second is None:
        info["reason"] = "CPU 采样失败（进程不可查询/已退）——证据缺失不凑判"
        return None, info
    delta = float(second) - float(first)
    info["delta_s"] = delta
    return delta > float(min_delta_s), info


def _artifact_evidence(
    artifact_globs: Sequence[str],
    now: float,
    window_s: float,
    glob_fn: Callable[[str], list[str]],
) -> tuple[bool | None, dict[str, Any]]:
    """产物 mtime 新鲜度证 → (fresh|None, info)。未配置 glob 或零命中都不是
    False——是 None（#122：无对如实 UNKNOWN，不凑"停滞"）。"""
    patterns = [str(g) for g in artifact_globs if str(g)]
    if not patterns:
        return None, {"matches": 0, "reason": "未配置产物 glob——本证缺席（非停滞）"}
    files: list[str] = []
    for pattern in patterns:
        try:
            files.extend(glob_fn(pattern))
        except (OSError, ValueError, IndexError):
            return None, {"matches": 0, "reason": f"产物 glob 执行失败：{pattern}"}
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        return None, {"matches": 0, "reason": "产物 glob 零命中——无证据不凑判"}
    newest = max(os.path.getmtime(f) for f in files)
    age = float(now) - float(newest)
    info = {
        "matches": len(files),
        "newest_mtime": newest,
        "age_s": round(age, 3),
        "window_s": float(window_s),
    }
    return age <= float(window_s), info


def _pid_alive_default(pid: object) -> bool:
    """跨平台进程存活探测（campaign_wait_launch.pid_alive 同款模式——scripts
    不可被 src 导入，模式复用）。Windows=OpenProcess+GetExitCodeProcess。"""
    try:
        pid_i = int(pid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if pid_i <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid_i)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == still_active
            return False
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid_i, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


# ── 单席三证视图 ──────────────────────────────────────────────────────────────


def seat_liveness_view(
    target: int | float | str | Mapping[str, Any] | None,
    *,
    artifact_globs: Sequence[str] = (),
    stall_window_s: float = DEFAULT_STALL_WINDOW_S,
    cpu_sample_interval_s: float = 1.0,
    cpu_min_delta_s: float = 0.05,
    census_fn: Callable[[str | None, str], list[str] | None] | None = None,
    cpu_sample_fn: Callable[[int], float | None] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    pid_alive_fn: Callable[[object], bool] | None = None,
    glob_fn: Callable[[str], list[str]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """单 seat 三证判活视图（信封）。target 形态：

    - ``int``：pid 直查（存活证=pid 存活）；
    - ``str``/``dict``：#261 命令行指纹 census 证（str=全进程域指纹；
      dict=``{"process_name":…, "fingerprint":…}`` 收窄进程域——命中行
      ``pid|commandline`` 首行 pid 作 CPU 采样对象）；
    - ``None``：纯产物证视图（无进程证据，批量 run 目录行复用）。

    返回 ``ok_envelope(state=alive|stalled|dead|unknown, evidence=…, cpu=…,
    artifacts=…, reason=…)``；unknown 恒 ok=True（观测成功且如实，#105/#122）。
    同采样两次调用判定逐位一致（判定表纯函数单源）。"""
    now_ts = time.time() if now is None else float(now)
    alive_fn = pid_alive_fn or _pid_alive_default
    sample_fn = cpu_sample_fn or sample_cpu_seconds
    census = census_fn or default_census
    globber = glob_fn or (lambda pattern: _globmod.glob(pattern, recursive=True))

    census_reason: str | None = None
    if isinstance(target, bool) or target is Ellipsis:
        return error_envelope(
            f"target 形态不识别：{target!r}（bool 不是 pid——isinstance(int) 陷阱）"
        )
    if target is None:
        spec: dict[str, Any] = {"kind": "artifact_only", "pid": None}
        alive: bool | None = None
        matched_pid: int | None = None
    elif isinstance(target, (int, float)):
        spec = {"kind": "pid", "pid": int(target)}
        alive = bool(alive_fn(int(target)))
        matched_pid = int(target)
    elif isinstance(target, str):
        spec = {"kind": "census", "fingerprint": str(target), "process_name": None}
        alive, matched_pid, census_reason = _census_alive(spec, census)
    elif isinstance(target, Mapping):
        spec = {
            "kind": "census",
            "fingerprint": str(target.get("fingerprint") or ""),
            "process_name": target.get("process_name"),
        }
        alive, matched_pid, census_reason = _census_alive(spec, census)
    else:
        return error_envelope(
            f"target 形态不识别：{type(target).__name__}（int pid / str·dict census 指纹 / None）"
        )

    cpu_info: dict[str, Any] | None = None
    cpu_growing: bool | None = None
    art_fresh, art_info = _artifact_evidence(
        artifact_globs, now_ts, stall_window_s, globber
    )
    if alive is False:
        cpu_info = {"reason": "进程已死——跳过 CPU 采样", "first_s": None,
                    "second_s": None, "delta_s": None}
        cpu_growing = None
    elif alive is True and matched_pid is not None:
        cpu_growing, cpu_info = _cpu_evidence(
            matched_pid, sample_fn, cpu_sample_interval_s, sleep_fn, cpu_min_delta_s
        )
    elif alive is True and matched_pid is None:  # pragma: no cover - census 命中必带 pid
        cpu_info = {"reason": "命中行缺 pid——CPU 证缺席", "first_s": None,
                    "second_s": None, "delta_s": None}
        cpu_growing = None
    else:
        cpu_info = {"reason": "进程证据缺席/未知——CPU 证不采样",
                    "first_s": None, "second_s": None, "delta_s": None}
        cpu_growing = None

    if spec["kind"] == "artifact_only":
        state, reason = judge_artifact_only(art_fresh)
    else:
        state, reason = judge_liveness(alive, cpu_growing, art_fresh)
    notes = [r for r in (census_reason,) if r]
    if reason:
        notes.insert(0, reason)
    return ok_envelope(
        state=state,
        target=spec,
        evidence={"process_alive": alive, "cpu_growing": cpu_growing,
                  "artifact_fresh": art_fresh},
        cpu=cpu_info,
        artifacts=art_info,
        reason="；".join(notes) if notes else None,
    )


# ── 批量视图（campaign run 目录） ─────────────────────────────────────────────


def campaign_liveness_summary(
    run_dirs: Sequence[str | os.PathLike[str]],
    *,
    artifact_globs: Sequence[str] = DEFAULT_RUN_DIR_GLOBS,
    stall_window_s: float = DEFAULT_STALL_WINDOW_S,
    pids: Mapping[str, int] | None = None,
    cpu_sample_interval_s: float = 0.0,
    cpu_min_delta_s: float = 0.05,
    cpu_sample_fn: Callable[[int], float | None] | None = None,
    sleep_fn: Callable[[float], None] = lambda _s: None,
    pid_alive_fn: Callable[[object], bool] | None = None,
    glob_fn: Callable[[str], list[str]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """批量 seat 判活视图（W5 收割/长跑判读消费面）：对每个 run 目录产出
    一行信封（同 :func:`seat_liveness_view` 词汇）。提供 ``pids[dir]=pid``
    的行走全三证；未提供 pid 的行=纯产物证（process_alive=None，reason 注明
    "未提供 pid"）——产物新鲜→alive（仅产物证）、停滞→stalled、无证据→
    unknown 不凑判。目录缺失/为空=unknown。"""
    now_ts = time.time() if now is None else float(now)
    pid_map = {str(k): int(v) for k, v in (pids or {}).items()}
    rows: list[dict[str, Any]] = []
    for d in run_dirs:
        dir_str = str(d)
        patterns = [
            f"{Path(dir_str).as_posix().rstrip('/')}/{g}" for g in artifact_globs if str(g)
        ]
        pid = pid_map.get(dir_str)
        if pid is not None:
            row = seat_liveness_view(
                pid,
                artifact_globs=patterns,
                stall_window_s=stall_window_s,
                cpu_sample_interval_s=cpu_sample_interval_s,
                cpu_min_delta_s=cpu_min_delta_s,
                cpu_sample_fn=cpu_sample_fn,
                sleep_fn=sleep_fn,
                pid_alive_fn=pid_alive_fn,
                glob_fn=glob_fn,
                now=now_ts,
            )
        else:
            row = seat_liveness_view(
                None,
                artifact_globs=patterns,
                stall_window_s=stall_window_s,
                glob_fn=glob_fn,
                now=now_ts,
            )
        row = {"run_dir": dir_str, "pid": pid, **row}
        rows.append(row)
    counts: dict[str, int] = {s: 0 for s in _CPU_STATE}
    for row in rows:
        state = row.get("state")
        if state in counts:
            counts[state] += 1
    return ok_envelope(rows=rows, counts=counts, n_dirs=len(rows))


# ── watch_loop（可调用生成器，默认关——无线程零后台） ─────────────────────────


def validate_watch_root(whitelist_root: str | os.PathLike[str] | None = None) -> Path:
    """watchdog 白名单单根校验：解析后必须以 ``runs/watchdog`` 结尾
    （normcase+显式 lower，安全比较家法）。"""
    root = (
        repo_root() / WATCHDOG_ROOT_REL
        if whitelist_root is None
        else Path(os.path.abspath(str(whitelist_root)))
    )
    tail = _norm_key(root)
    if not tail.endswith("/" + WATCHDOG_ROOT_REL):
        raise ValueError(
            f"watchdog sink 白名单越界：根必须为 {WATCHDOG_ROOT_REL}（收到 {root}）"
        )
    return root


def _append_jsonl(path: Path, payload: dict[str, Any]) -> bool:
    """best-effort 追加一行 jsonl（#105：观测面写失败不阻塞主路径）。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return True
    except OSError:
        return False


def watch_loop(
    target: int | float | str | Mapping[str, Any] | None,
    *,
    sink: str | os.PathLike[str],
    rounds: int = 1,
    interval_s: float = 30.0,
    whitelist_root: str | os.PathLike[str] | None = None,
    clock: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
    **view_kwargs: Any,
) -> Iterator[dict[str, Any]]:
    """周期采样（**默认关**：无人调用=零线程零文件写；显式调用才生效）。

    每轮 :func:`seat_liveness_view` 采样一行 jsonl 追加到 ``sink``（必须落
    白名单单根 ``runs/watchdog/<seat>/``，越界 ValueError——湖隔离守卫同
    T-O11 家法），每轮 yield 该轮视图（附 watch_round/sink_write_ok）。
    sink 写失败降级如实标注（sink_write_ok=False）不抛（#105）。白名单/
    越界校验在调用期**急切**执行（误用当场报，不等首轮迭代）。"""
    root = validate_watch_root(whitelist_root)
    sink_path = Path(os.path.abspath(str(sink)))
    head = _norm_key(root).rstrip("/")
    tail = _norm_key(sink_path)
    if tail != head and not tail.startswith(head + "/"):
        raise ValueError(f"watchdog sink {sink_path} 越出白名单单根 {root}")
    return _watch_iter(target, sink_path, rounds, interval_s, clock, sleep_fn, view_kwargs)


def _watch_iter(
    target: Any,
    sink_path: Path,
    rounds: int,
    interval_s: float,
    clock: Callable[[], float],
    sleep_fn: Callable[[float], None],
    view_kwargs: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    """watch_loop 迭代体（独立生成器函数：白名单校验保持在调用期急切执行）。"""
    for i in range(max(int(rounds), 0)):
        view = {**seat_liveness_view(target, now=clock(), **view_kwargs), "watch_round": i + 1}
        ok_write = _append_jsonl(sink_path, {"ts": clock(), "view": view})
        yield {**view, "sink_write_ok": ok_write}
        if i + 1 < int(rounds):
            sleep_fn(max(float(interval_s), 0.0))
