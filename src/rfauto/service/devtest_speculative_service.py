"""devtest 投机执行档（T-O11，aurora_o）——src 变更后台预跑 + 指纹缓存秒回。

Super-agent"后台投机执行"思想化用（runs/aurora_o/superagent_absorb/ABSORB.md
§三 T-O11；思想吸收非对照实现）：src/rfauto 变更落树后**预先**后台跑一轮受
影响测试，用户/主代理显式查询时按变更面指纹查缓存秒回红绿。

分层与单源（规则 3/4）：
- 本模块是 service 层纯逻辑 + 子进程编排面，JSON 信封进出（envelope 构造器）；
  git diff 变更检测与 impact_map 选择**不在此复制**——由薄驱动
  ``scripts/devtest.py``/``scripts/devtest_speculative.py`` 消费
  ``devtest._changed_src``/``_ensure_map``/``_get_selection`` 单源后把结果
  （changed_src/tests/head/map_digest）作为显式入参传入（scripts 不可被
  src 导入，分层家法）；
- 缓存**白名单单根** ``runs/devtest_speculative/``（#144 家族反向钉）：全部
  写面经 :func:`guard_cache_path` 前缀校验（根必须以 runs/devtest_speculative
  结尾 + 目标必须落于根内 + 禁 ``..``/绝对路径/通配），越界即拒——本机制是
  后台件中唯一允许写 runs/ 的写面，且不落会话档/不进 chat_sessions
  （few-shot 消费面隔离）。

红线（任务书口径，永不放松）：
1. **投机预跑永不真机**：真机测试（路径含 real_edt 标记）在触发面显式剔除
   （:func:`strip_real_machine_tests`）+ pytest 命令带 ``-m "not real_edt"``
   双保险；#261 census 有在跑 pytest/rfauto_runner/HFSS/ADS 求解进程时拒绝
   启动（fail-closed：census 不可验证同样拒绝）；
2. **永不写 runs/ 湖根**：白名单单根外零写（守卫见上）；
3. **资源上限**：xdist worker 硬顶 4（探底不探顶）、单轮墙钟上限缺省 600s
   超时 kill 进程树（taskkill /T）、触发防抖（min_trigger_interval_s）。

观测面 best-effort（#105）：预跑失败/环境异常 → 缓存记 ``state=failed`` 留
reason，不阻塞任何前台路径；查询时 stale/missing/interrupted 如实报不凑判
（#122）。单实例守卫沿 campaign_wait_launch 心跳先例（心跳文件+pid 存活；
含本批次 owner_pid 自排除——#261 自锁教训同款）。

消费面：scripts/devtest_speculative.py（触发/查询/child 三模式薄驱动）；
W5 席收割/长跑判读可复用本服务的 status 信封。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "CACHE_ROOT_REL",
    "DEFAULT_TIMEOUT_S",
    "REAL_MACHINE_TOKENS",
    "SPECULATIVE_CACHE_SCHEMA",
    "SPECULATIVE_SUMMARY_SCHEMA",
    "WORKERS_CAP",
    "SpeculativeGuardError",
    "classify_census_hits",
    "compute_fingerprint",
    "default_local_census",
    "finish_run",
    "guard_cache_path",
    "local_census_command",
    "map_fingerprint_digest",
    "parse_pytest_summary",
    "pid_alive",
    "read_heartbeat",
    "resolve_cache_root",
    "run_speculative_child",
    "speculative_run",
    "speculative_status",
    "strip_real_machine_tests",
    "validate_cache_root",
    "write_heartbeat",
]

#: 缓存白名单单根（相对仓根；#144 反向钉——全部写面必须落于此前缀内）。
CACHE_ROOT_REL = "runs/devtest_speculative"
FINGERPRINT_NAME = "fingerprint.json"
SUMMARY_NAME = "summary.json"
HEARTBEAT_NAME = ".heartbeat.json"
LOGS_DIR = "logs"

SPECULATIVE_CACHE_SCHEMA = "rfauto-devtest-speculative-v1"
SPECULATIVE_SUMMARY_SCHEMA = "rfauto-devtest-speculative-summary-v1"
_FINGERPRINT_VERSION = 1

#: 资源上限（任务书红线 3）：xdist worker 硬顶 4、单轮墙钟缺省 600s。
WORKERS_CAP = 4
DEFAULT_TIMEOUT_S = 600.0

#: 真机面标记：路径含任一 token 的测试一律剔除（投机预跑永不真机）。
REAL_MACHINE_TOKENS = ("real_edt",)

#: 触发防抖缺省窗口（s）：同根上一轮记录落成后 60s 内的新指纹触发拒绝，
#: 防触发循环失控（ABSORB 守卫③"触发间隔最小间隔防抖"）。
DEFAULT_MIN_TRIGGER_INTERVAL_S = 60.0

_CENSUS_TIMEOUT_S = 30.0
#: #261 本机互斥指纹：python 家族命令行命中即忙（pytest/全量门/rfauto_runner
#: 家族——openEMS 是进程内 FDTD，按 #261 口径查 python 命令行而非进程名）。
_PYTHON_MUTEX_FP = re.compile(
    r"pytest|_rfauto_runner|simulation\.py|fd_oe_campaign|driver\.py"
)
_PYTHON_PROCESS_NAMES = frozenset({"python.exe", "pythonw.exe"})
#: 真机求解器进程名（HFSS/ADS 引擎本体；命中即忙——触发判据排除真机在跑）。
_SOLVER_PROCESS_NAMES = frozenset({"ansysedt.exe", "hpeesofsim.exe", "openems.exe"})

_CENSUS_LINE_RE = re.compile(r"^\d+\|")
_FAILED_LINE_RE = re.compile(r"^FAILED\s+(\S+)")
_COUNT_RE = re.compile(r"(\d+)\s+(failed|passed|error|errors|skipped|deselected|xpassed|xfailed)")
_HAS_COUNTS_RE = re.compile(
    r"\d+\s+(?:failed|passed|error|errors|skipped|deselected|xpassed|xfailed)"
)
#: 汇总行时长尾（``in 7.48s`` / 长跑去秒位 ``in 1:05:10.3s``）
_HAS_DURATION_RE = re.compile(r"\bin\s+[\d.,:hms]+s\b")


class SpeculativeGuardError(ValueError):
    """白名单守卫拒绝（缓存根/写路径越界）——调用方契约违约，非观测失败。"""


def repo_root() -> Path:
    """仓根（editable 安装下 src/rfauto/service 的 parents[3]）。"""
    return Path(__file__).resolve().parents[3]


# ── 缓存白名单单根守卫（#144 反向钉） ─────────────────────────────────────────


def _norm_key(p: Path) -> str:
    r"""路径比较键：normcase + 斜杠归一 + 显式 lower（Windows normcase 会把
    ``/`` 转 ``\``——endswith 前缀比较必须先换回斜杠；POSIX normcase 恒等，
    故显式 lower 兜底，AGENTS 安全比较家法）。"""
    return os.path.normcase(p.as_posix()).replace("\\", "/").lower()


def resolve_cache_root(cache_root: str | os.PathLike[str] | None = None) -> Path:
    """缓存根解析：缺省 = 仓根/runs/devtest_speculative（不依赖 cwd，#144 教训）。"""
    if cache_root is None:
        return repo_root() / CACHE_ROOT_REL
    return Path(os.path.abspath(str(cache_root)))


def validate_cache_root(cache_root: str | os.PathLike[str]) -> Path:
    """缓存根白名单校验：解析后 posix（normcase+显式 lower，AGENTS 安全比较家法）
    必须以 ``runs/devtest_speculative`` 结尾——runs/ 湖其他任何位置拒绝。"""
    root = Path(os.path.abspath(str(cache_root)))
    tail = _norm_key(root)
    if not tail.endswith("/" + CACHE_ROOT_REL):
        raise SpeculativeGuardError(
            f"缓存根越出白名单单根 {CACHE_ROOT_REL}（收到 {root}）——"
            "本服务禁写 runs/ 湖根其他位置（#144 反向钉）"
        )
    return root


def guard_cache_path(cache_root: str | os.PathLike[str], name: str) -> Path:
    """写面守卫：根白名单校验 + 目标名禁绝对路径/``..``/空段 + 落根内复核。"""
    root = validate_cache_root(cache_root)
    raw = str(name).replace("\\", "/")
    if not raw or os.path.isabs(raw):
        raise SpeculativeGuardError(f"缓存写面非法名：{name!r}（空/绝对路径）")
    parts = PurePosixPath(raw).parts
    if any(p in ("..", "") for p in parts):
        raise SpeculativeGuardError(f"缓存写面越界：{name!r}（含 .. 或空段）——禁越出单根")
    target = root.joinpath(*parts)
    resolved_root = Path(os.path.abspath(root))
    resolved_target = Path(os.path.abspath(target))
    key_root = _norm_key(resolved_root).rstrip("/")
    key_target = _norm_key(resolved_target)
    if key_target != key_root and not key_target.startswith(key_root + "/"):
        raise SpeculativeGuardError(f"缓存写面越出单根：{target} 不在 {root} 内")
    return target


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """原子写 JSON：同目录临时文件 → os.replace（campaign_wait_launch 心跳同款）。"""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, sort_keys=True, indent=1)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


# ── 指纹（变更文件集 + HEAD + map 指纹 + 派生测试面 pin） ─────────────────────


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_fingerprint(
    changed_src: Sequence[str],
    *,
    head: str | None,
    map_digest: str | None,
    tests: Sequence[str],
    content_digest: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """变更面指纹（纯函数）：(fp_hex, fields)。同 tree 同输入 → 同 fp（确定性⑤）。

    fields = 变更文件集（排序去重 POSIX 化）+ 其 sha256 + git HEAD + map 指纹
    文件摘要 + 派生测试面 sha256（测试面由 changed+map 确定性导出，入指纹是
    派生负载 pin——map 再生导致同变更面不同测试集时缓存正确过期）。

    content_digest（F1-deep watch 档挂钩，缺省 None）：变更文件**内容**摘要。
    None=键缺席，fields/指纹与 T-O11 原口径逐位同（显式触发/查询档零变化）；
    给定时入 fields——同名文件二次编辑即换指纹（watch 档内容感知口径，见
    service/speculative_watch_service.py）。"""
    changed = sorted({str(c).replace("\\", "/") for c in changed_src})
    test_list = sorted({str(t).replace("\\", "/") for t in tests})
    fields: dict[str, Any] = {
        "version": _FINGERPRINT_VERSION,
        "changed_src": changed,
        "changed_src_sha256": _sha256_text("\n".join(changed)),
        "head": str(head or ""),
        "map_digest": str(map_digest or "missing"),
        "tests": test_list,
        "tests_sha256": _sha256_text("\n".join(test_list)),
    }
    if content_digest is not None:
        fields["content_digest"] = str(content_digest)
    blob = json.dumps(fields, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest(), fields


def map_fingerprint_digest(map_fingerprint_path: str | os.PathLike[str]) -> str | None:
    """impact_map 指纹文件内容摘要（map 再生即变化 → 旧缓存过期）；缺失 → None。"""
    p = Path(map_fingerprint_path)
    if not p.exists():
        return None
    try:
        return _sha256_text(p.read_bytes().hex())
    except OSError:
        return None


# ── 真机面剔除（红线 1：投机预跑永不真机） ────────────────────────────────────


def strip_real_machine_tests(tests: Sequence[str]) -> tuple[list[str], list[str]]:
    """受影响测试清单 → (kept, dropped)：路径含真机 token（real_edt）一律剔除。"""
    kept: list[str] = []
    dropped: list[str] = []
    for t in tests:
        s = str(t).replace("\\", "/")
        (dropped if any(tok in s for tok in REAL_MACHINE_TOKENS) else kept).append(s)
    return kept, dropped


# ── #261 本机 census（互斥：无在跑 pytest/rfauto_runner/求解进程才可触发） ────


def local_census_command() -> str:
    """本机 #261 census 探针命令（PS 原生；命中行协议=``pid|name|commandline``，
    与 remote_service.mutex 的 ``pid|commandline`` 家法同形，多一列进程名供
    本机分名分类——python 家族按命令行指纹判忙，求解器按进程名判忙）。"""
    names = ", ".join(f"'{n}'" for n in sorted(_PYTHON_PROCESS_NAMES | _SOLVER_PROCESS_NAMES))
    return (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.Name -in @({names}) }} | "
        "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId, $_.Name, $_.CommandLine }"
    )


def classify_census_hits(lines: Iterable[str]) -> list[dict[str, Any]]:
    """census 输出行 → 忙命中清单（纯函数）。python 家族命令行命中
    :data:`_PYTHON_MUTEX_FP`（pytest/_rfauto_runner 家族）或进程名为求解器
    （ansysedt/hpeesofsim/openems）即忙；非协议行不误判。"""
    hits: list[dict[str, Any]] = []
    for ln in lines:
        s = ln.strip()
        if not _CENSUS_LINE_RE.match(s):
            continue
        parts = s.split("|", 2)
        if len(parts) != 3:
            continue
        pid_s, name, cmdline = parts
        low = name.strip().lower()
        if low in _SOLVER_PROCESS_NAMES:
            kind = "solver"
        elif low in _PYTHON_PROCESS_NAMES and _PYTHON_MUTEX_FP.search(cmdline or ""):
            kind = "pytest_or_runner"
        else:
            continue
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        hits.append({"pid": pid, "name": name.strip(), "kind": kind, "cmdline": cmdline[:200]})
    return hits


def default_local_census() -> list[dict[str, Any]] | None:
    """本机 census 缺省实现：跑探针命令并分类；查询失败 → None（调用方
    fail-closed 拒绝启动——验不了不发射，与 remote_mutex_precheck 同判）。"""
    try:
        run = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", local_census_command()],
            capture_output=True, text=True, timeout=_CENSUS_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if run.returncode != 0:
        return None
    return classify_census_hits((run.stdout or "").splitlines())


# ── 心跳/存活（campaign_wait_launch 先例的模式复用：scripts 不可被 src 导入） ──


def write_heartbeat(path: str | os.PathLike[str], payload: dict[str, Any]) -> bool:
    """原子写心跳（同目录临时文件 → os.replace）；OSError 不抛，返回 False
    （观测面 best-effort，#105）。"""
    p = Path(path)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, p)
        return True
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return False


def read_heartbeat(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    """读心跳 JSON；缺失/损坏 → None（不构成阻塞，按无主处理）。"""
    return _read_json(Path(path))


def pid_alive(pid: object) -> bool:
    """跨平台进程存活探测（零副作用；campaign_wait_launch.pid_alive 同款模式）：
    Windows 走 OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)+GetExitCodeProcess，
    POSIX 走 os.kill(pid, 0)。无效 pid → False。"""
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


def _runner_conflict(
    hb: object, alive_fn: Callable[[object], bool], current_pid: int
) -> tuple[bool, str]:
    """单实例判定：心跳里 child_pid 存活、或 owner_pid 存活且≠本进程 → 冲突。
    owner_pid==current 的自排除=本批次心跳（#261 自锁教训同款）。"""
    if not isinstance(hb, dict):
        return False, ""
    child = hb.get("child_pid")
    if child is not None and alive_fn(child):
        return True, f"预跑子进程 pid={child} 仍在跑（指纹 {hb.get('fingerprint')}）"
    owner = hb.get("owner_pid")
    if owner is not None and owner != current_pid and alive_fn(owner):
        return True, f"上一触发者 pid={owner} 仍在跑（指纹 {hb.get('fingerprint')}）"
    return False, ""


# ── 触发（后台预跑发射） ──────────────────────────────────────────────────────


def _spawn_detached(cmd: list[str], log_path: Path) -> int:
    """分离发射子进程（#157 家法：后台长任务分离+日志文件）。注意：句柄继承
    无 CRT 追加语义（Windows 坑，见 run_speculative_child 内注）——child 侧
    启动即把自身 stdout 重绑为日志追加模式，此句柄仅作崩溃前兜底宿主。"""
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
    with open(log_path, "a", encoding="utf-8") as fh:
        proc = subprocess.Popen(
            cmd, cwd=str(repo_root()), stdout=fh, stderr=subprocess.STDOUT, **kwargs
        )
    return proc.pid


def _default_driver_script() -> Path:
    return repo_root() / "scripts" / "devtest_speculative.py"


def speculative_run(
    changed_src: Sequence[str],
    *,
    tests: Sequence[str],
    head: str | None,
    map_digest: str | None,
    cache_root: str | os.PathLike[str] | None = None,
    workers: int = WORKERS_CAP,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    min_trigger_interval_s: float = DEFAULT_MIN_TRIGGER_INTERVAL_S,
    census_fn: Callable[[], list[dict[str, Any]] | None] | None = None,
    pid_alive_fn: Callable[[object], bool] | None = None,
    spawn_fn: Callable[[list[str], Path], int] | None = None,
    driver_script: str | os.PathLike[str] | None = None,
    owner_pid: int | None = None,
    now: float | None = None,
    content_digest: str | None = None,
) -> dict[str, Any]:
    """投机预跑触发：守卫全过 → 落 pending 记录+心跳 → 分离发射 child 子进程。

    changed_src/tests/head/map_digest 由薄驱动消费 devtest 单源后显式传入
    （本模块零复制 git/map 逻辑）。返回信封 state：
    launched / cached（同指纹幂等命中） / already_running / declined
    （guard=mutex|mutex_unverified|single_instance|debounce|real_machine_only）/
    nothing_to_do（空变更——验收负例⑥）。content_digest 透传
    :func:`compute_fingerprint`（缺省 None=T-O11 原口径逐位不变）。"""
    now_ts = time.time() if now is None else float(now)
    changed = sorted({str(c).replace("\\", "/") for c in changed_src if str(c)})
    if not changed:
        return ok_envelope(
            state="nothing_to_do",
            fingerprint=None,
            reason="git diff 无 src/rfauto 变更——无事可做（验收负例⑥）",
        )
    try:
        root = validate_cache_root(resolve_cache_root(cache_root))
    except SpeculativeGuardError as exc:
        return error_envelope(f"缓存根白名单校验拒绝：{exc}")

    kept, dropped = strip_real_machine_tests(tests)
    if not kept:
        return ok_envelope(
            state="declined",
            guard="real_machine_only",
            fingerprint=None,
            reason="受影响测试全部命中真机面（real_edt）——投机预跑永不真机，拒绝启动",
            real_machine_dropped=dropped,
        )

    fp, fields = compute_fingerprint(
        changed, head=head, map_digest=map_digest, tests=kept, content_digest=content_digest
    )
    alive_fn = pid_alive_fn or pid_alive
    current_pid = int(owner_pid) if owner_pid is not None else os.getpid()

    record = _read_json(root / FINGERPRINT_NAME)
    if isinstance(record, dict) and record.get("fingerprint") == fp:
        state = record.get("state")
        if state == "done":
            summary = _read_json(root / SUMMARY_NAME)
            if isinstance(summary, dict) and summary.get("fingerprint") == fp:
                return ok_envelope(
                    state="cached",
                    fingerprint=fp,
                    summary=summary,
                    reason="同指纹缓存命中——幂等不重跑（同 tree 同指纹两次预跑结果一致⑤）",
                )
        if state == "running":
            child = record.get("child_pid")
            if child is not None and alive_fn(child):
                return ok_envelope(
                    state="already_running",
                    guard="single_instance",
                    fingerprint=fp,
                    child_pid=child,
                    reason="同指纹预跑子进程仍在跑——拒绝双发（单实例守卫）",
                )

    conflict, why = _runner_conflict(
        read_heartbeat(root / HEARTBEAT_NAME), alive_fn, current_pid
    )
    if conflict:
        return ok_envelope(
            state="declined",
            guard="single_instance",
            fingerprint=fp,
            reason=f"单实例守卫：{why}——拒绝双发",
        )

    if min_trigger_interval_s > 0 and isinstance(record, dict) and record.get("fingerprint") != fp:
        last_ts = record.get("finished_ts") or record.get("started_ts")
        if isinstance(last_ts, (int, float)) and (now_ts - float(last_ts)) < float(
            min_trigger_interval_s
        ):
            return ok_envelope(
                state="declined",
                guard="debounce",
                fingerprint=fp,
                reason=(
                    f"上一轮记录距今 {now_ts - float(last_ts):.1f}s < 防抖窗 "
                    f"{float(min_trigger_interval_s):.0f}s——拒绝连发"
                ),
            )

    hits = (census_fn or default_local_census)()
    if hits is None:
        return ok_envelope(
            state="declined",
            guard="mutex_unverified",
            fingerprint=fp,
            reason="#261 census 不可验证（进程查询失败）——fail-closed 拒绝启动",
        )
    if hits:
        return ok_envelope(
            state="declined",
            guard="mutex",
            fingerprint=fp,
            census_hits=hits,
            reason=f"#261 互斥命中 {len(hits)} 例（在跑 pytest/rfauto_runner/求解进程）——拒绝启动",
        )

    workers_eff = min(max(int(workers), 1), WORKERS_CAP)
    timeout_eff = max(float(timeout_s), 1.0)
    log_rel = f"{LOGS_DIR}/{fp[:12]}.log"
    try:
        log_path = guard_cache_path(root, log_rel)
    except SpeculativeGuardError as exc:
        return error_envelope(f"日志路径守卫拒绝：{exc}", fingerprint=fp)

    new_record: dict[str, Any] = {
        "schema": SPECULATIVE_CACHE_SCHEMA,
        "fingerprint": fp,
        "fields": fields,
        "state": "running",
        "started_ts": now_ts,
        "finished_ts": None,
        "owner_pid": current_pid,
        "child_pid": None,
        "workers": workers_eff,
        "timeout_s": timeout_eff,
        "log_rel": log_rel,
        "real_machine_dropped": dropped,
    }
    try:
        _atomic_write_json(root / FINGERPRINT_NAME, new_record)
    except OSError as exc:
        return error_envelope(f"缓存记录写失败：{exc}", fingerprint=fp)
    write_heartbeat(
        root / HEARTBEAT_NAME,
        {
            "role": "speculative_trigger",
            "owner_pid": current_pid,
            "child_pid": None,
            "fingerprint": fp,
            "last_poll_ts": now_ts,
        },
    )

    cmd = [
        sys.executable,
        str(Path(driver_script) if driver_script is not None else _default_driver_script()),
        "--child",
        "--fingerprint", fp,
        "--cache-root", str(root),
        "--log", str(log_path),
        "--workers", str(workers_eff),
        "--timeout-s", str(timeout_eff),
        "--",
        *kept,
    ]
    spawn = spawn_fn or _spawn_detached
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)  # logs/ 目录先建（分离发射的日志宿主）
        child_pid = spawn(cmd, log_path)
    except Exception as exc:
        new_record.update(
            {"state": "failed", "finished_ts": time.time(), "reason": f"子进程发射失败：{exc}"}
        )
        with contextlib.suppress(OSError):
            _atomic_write_json(root / FINGERPRINT_NAME, new_record)
        return error_envelope(f"投机预跑子进程发射失败：{exc}", fingerprint=fp, state="failed")

    new_record["child_pid"] = int(child_pid)
    with contextlib.suppress(OSError):
        _atomic_write_json(root / FINGERPRINT_NAME, new_record)
    write_heartbeat(
        root / HEARTBEAT_NAME,
        {
            "role": "speculative_child",
            "owner_pid": current_pid,
            "child_pid": int(child_pid),
            "fingerprint": fp,
            "last_poll_ts": time.time(),
        },
    )
    return ok_envelope(
        state="launched",
        fingerprint=fp,
        child_pid=int(child_pid),
        tests_count=len(kept),
        workers=workers_eff,
        timeout_s=timeout_eff,
        log_path=str(log_path),
        cache_root=str(root),
        real_machine_dropped=dropped,
        reason="后台预跑已发射（xdist 探底不探顶；结果落缓存后 status 秒回）",
    )


# ── 查询（指纹命中秒回 / stale 如实） ─────────────────────────────────────────


def speculative_status(
    changed_src: Sequence[str],
    *,
    tests: Sequence[str],
    head: str | None,
    map_digest: str | None,
    cache_root: str | os.PathLike[str] | None = None,
    pid_alive_fn: Callable[[object], bool] | None = None,
    now: float | None = None,
    content_digest: str | None = None,
) -> dict[str, Any]:
    """按当前变更面指纹查缓存：hit（秒回 summary）/ stale（指纹不符如实标注，
    不冒充有效）/ missing / running / interrupted / failed / corrupt /
    nothing_to_do。纯文件读零子进程（<1s）。content_digest 同
    :func:`speculative_run`（缺省 None=原口径；watch 档传内容摘要）。"""
    now_ts = time.time() if now is None else float(now)
    changed = sorted({str(c).replace("\\", "/") for c in changed_src if str(c)})
    if not changed:
        return ok_envelope(
            state="nothing_to_do", fingerprint=None, reason="当前无 src/rfauto 变更——无事可查"
        )
    try:
        root = validate_cache_root(resolve_cache_root(cache_root))
    except SpeculativeGuardError as exc:
        return error_envelope(f"缓存根白名单校验拒绝：{exc}")
    fp, _fields = compute_fingerprint(
        changed, head=head, map_digest=map_digest, tests=tests, content_digest=content_digest
    )
    base: dict[str, Any] = {"fingerprint": fp, "cache_root": str(root)}
    record = _read_json(root / FINGERPRINT_NAME)
    if not isinstance(record, dict):
        return ok_envelope(
            state="missing", reason="缓存无记录（该根未预跑过）——如实报告不冒充", **base
        )
    if record.get("fingerprint") != fp:
        return ok_envelope(
            state="stale",
            reason="当前变更面指纹与缓存指纹不符——旧结果如实标注过期，不返回旧 summary 冒充有效",
            cached_fingerprint=record.get("fingerprint"),
            cached_state=record.get("state"),
            **base,
        )
    state = record.get("state")
    alive_fn = pid_alive_fn or pid_alive
    if state == "running":
        child = record.get("child_pid")
        if child is not None and alive_fn(child):
            started = record.get("started_ts")
            return ok_envelope(
                state="running",
                child_pid=child,
                started_ts=started,
                elapsed_s=(now_ts - float(started)) if isinstance(started, (int, float)) else None,
                reason="预跑子进程在跑——等待落缓存",
                **base,
            )
        return ok_envelope(
            state="interrupted",
            reason="running 记录但子进程已不在且无 summary——如实报告（观测面不凑判）",
            **base,
        )
    summary = _read_json(root / SUMMARY_NAME)
    if state == "failed":
        if isinstance(summary, dict) and summary.get("fingerprint") == fp:
            return ok_envelope(
                state="failed", summary=summary, reason=summary.get("reason"), **base
            )
        return ok_envelope(state="corrupt", reason="failed 记录但 summary 缺失/损坏", **base)
    if state == "done":
        if isinstance(summary, dict) and summary.get("fingerprint") == fp:
            return ok_envelope(state="hit", summary=summary, **base)
        return ok_envelope(state="corrupt", reason="done 记录但 summary 缺失/指纹不符", **base)
    return ok_envelope(state="corrupt", reason=f"缓存记录状态不识别：{state!r}", **base)


# ── child 执行面（驱动 --child 模式调用；日志全落文件，#242 禁裸 stdout） ──────


def parse_pytest_summary(log_text: str) -> dict[str, Any]:
    """pytest 日志文本 → {passed, failed, failed_ids, summary_line}（纯函数、
    确定性）。failed_ids 取 short summary（-rf）``FAILED <testid>`` 行的排序
    去重集；计数取最后一行"计数+时长"汇总行——``-q`` 口径下末行是无 ``====``
    带的裸 ``N passed in Xs``（E2E 实测），故判据=含计数词+含 ``in …s`` 时长
    （两形态同盖）。有效汇总行内缺计数词=0（pytest 只报非零计数——全绿行
    没有 ``N failed`` 段）；无有效汇总行 → None 如实，不凑 0。"""
    failed_ids: list[str] = []
    candidates: list[str] = []
    for ln in log_text.splitlines():
        s = ln.strip()
        m = _FAILED_LINE_RE.match(s)
        if m:
            failed_ids.append(m.group(1))
        if _HAS_COUNTS_RE.search(s) and _HAS_DURATION_RE.search(s):
            candidates.append(s)
    counts: dict[str, int] = {}
    summary_line = candidates[-1] if candidates else None
    if summary_line:
        for n, word in _COUNT_RE.findall(summary_line):
            key = "error" if word.startswith("error") else word
            counts[key] = counts.get(key, 0) + int(n)
    return {
        "passed": counts.get("passed", 0) if summary_line else None,
        "failed": counts.get("failed", 0) if summary_line else None,
        "failed_ids": sorted(set(failed_ids)),
        "summary_line": summary_line,
    }


def _kill_tree(pid: int) -> bool:
    """杀进程树（xdist worker 连坐；taskkill 由 python 直调，非 bash 无 /PID 转换坑）。"""
    try:
        run = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, text=True, timeout=30,
        )
        return run.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ensure_under_root(root: Path, path: Path) -> Path:
    resolved_root = Path(os.path.abspath(root))
    resolved = Path(os.path.abspath(path))
    head = _norm_key(resolved_root).rstrip("/")
    tail = _norm_key(resolved)
    if tail != head and not tail.startswith(head + "/"):
        raise SpeculativeGuardError(f"路径 {resolved} 越出缓存单根 {resolved_root}")
    return resolved


def finish_run(
    root: Path, fingerprint: str, summary: dict[str, Any], state: str
) -> None:
    """child 收尾：原子写 summary.json + 指纹记录置终态（guarded 写面）。"""
    _atomic_write_json(guard_cache_path(root, SUMMARY_NAME), summary)
    record = _read_json(root / FINGERPRINT_NAME)
    if isinstance(record, dict) and record.get("fingerprint") == fingerprint:
        record["state"] = state
        record["finished_ts"] = summary.get("ts")
        _atomic_write_json(root / FINGERPRINT_NAME, record)


def run_speculative_child(
    *,
    fingerprint: str,
    tests: Sequence[str],
    log_path: str | os.PathLike[str],
    cache_root: str | os.PathLike[str] | None = None,
    workers: int = WORKERS_CAP,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    repo: str | os.PathLike[str] | None = None,
    start_ts: float | None = None,
    popen_fn: Callable[..., Any] | None = None,
    kill_tree_fn: Callable[[int], bool] | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """child 执行体：跑 pytest（xdist、真机 marker 双保险剔除、缓存隔离）→
    解析日志 → 落 summary + 置指纹终态。墙钟超时 kill 进程树（资源上限红线）。"""
    root = validate_cache_root(resolve_cache_root(cache_root))
    log = _ensure_under_root(root, Path(log_path))
    test_list = sorted({str(t).replace("\\", "/") for t in tests})
    repo_path = Path(repo) if repo is not None else repo_root()
    started = clock() if start_ts is None else float(start_ts)
    workers_eff = min(max(int(workers), 1), WORKERS_CAP)
    timeout_eff = max(float(timeout_s), 1.0)

    write_heartbeat(
        root / HEARTBEAT_NAME,
        {
            "role": "speculative_child",
            "owner_pid": os.getpid(),
            "child_pid": os.getpid(),
            "fingerprint": fingerprint,
            "last_poll_ts": started,
        },
    )
    pytest_cache_dir = guard_cache_path(root, ".pytest_cache")
    args = [
        sys.executable, "-m", "pytest", *test_list,
        "-n", str(workers_eff),
        "-q", "--tb=no", "-rf",
        "-m", "not real_edt",  # 真机双保险：路径剔除之外的 marker 层剔除
        "-o", f"cache_dir={pytest_cache_dir}",
    ]
    # 日志单写者纪律（Windows 句柄继承坑：CRT "a" 追加语义不随句柄继承/复制
    # 传播——各进程按自己句柄位写互踩，实测 grandchild 输出截断覆写）。故
    # pytest 走 PIPE+communicate 由本进程统一追加落日志，杜绝跨进程句柄竞争。
    log.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError), open(log, "a", encoding="utf-8"):
        pass  # touch：运行期日志文件先存在
    timed_out = False
    rc: int | None = None
    popen = popen_fn if popen_fn is not None else subprocess.Popen
    child_env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = popen(args, cwd=str(repo_path), stdout=subprocess.PIPE,
                 stderr=subprocess.STDOUT, env=child_env)
    try:
        out_bytes, _err = proc.communicate(timeout=timeout_eff)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        kill = kill_tree_fn if kill_tree_fn is not None else _kill_tree
        kill(proc.pid)
        with contextlib.suppress(Exception):
            out_bytes, _err = proc.communicate(timeout=30)
        rc = proc.returncode
    text = (out_bytes or b"").decode("utf-8", errors="replace")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(text)
    duration = clock() - started
    parsed = parse_pytest_summary(text)
    if timed_out:
        state, reason = "failed", f"墙钟超时 {timeout_eff:.0f}s → kill 进程树（资源上限红线）"
    elif rc == 0:
        state, reason = "done", None
    elif rc == 1:
        state, reason = "done", None  # 红测=正常完成（failed>0 由 summary 如实承载）
    elif rc in (4, 5):
        state, reason = "failed", f"pytest exit {rc}（用法错/未收集到用例）"
    else:
        state, reason = "failed", f"pytest exit {rc}（中断/内部错误）"
    summary: dict[str, Any] = {
        "schema": SPECULATIVE_SUMMARY_SCHEMA,
        "fingerprint": fingerprint,
        "state": state,
        "pytest_rc": rc,
        "timed_out": timed_out,
        "passed": parsed["passed"],
        "failed": parsed["failed"],
        "failed_ids": parsed["failed_ids"],
        "summary_line": parsed["summary_line"],
        "log_path": str(log),
        "duration_s": round(duration, 3),
        "ts": clock(),
        "reason": reason,
    }
    finish_run(root, fingerprint, summary, state)
    write_heartbeat(
        root / HEARTBEAT_NAME,
        {
            "role": "speculative_child",
            "owner_pid": os.getpid(),
            "child_pid": os.getpid(),
            "fingerprint": fingerprint,
            "last_poll_ts": clock(),
            "finished": True,
            "state": state,
        },
    )
    return summary
