"""remote_oe_service —— openEMS 远程执行通道（多机协同 v1，ge5 Wave2）。

``fd_oe_campaign --remote`` 的执行通道（此前「license 预检+如实 SKIP」的
未接线分支由此接上）。调用权威=docs/rfauto_openEMS_服务器安装与调用说明.md
§五（姿势 B：任务书+任务目录九步 SOP）/§六红线——本模块不发明新发射形态。

执行模型取舍（playbook G7 连坐/G8 缺省 shell/G5 零双引号，2026-09-30 定案）：

- **同步（sync）=缺省**：SSH ``run_command`` 阻塞等待
  ``cmd /c <task>\\run_task.bat``（说明书 §5.4 第 6 步直指形态）。openEMS
  座位分钟-小时级（fd_oe_campaign 缺省 timeout 2400s），引擎侧硬边界=
  点驱动 subprocess timeout（到点杀引擎 rc=124），SSH 通道无进程级超时
  （bat 引擎终了即返回）。G7（Win32-OpenSSH 会话 job object 连坐）只威胁
  "通道关闭后还要活"的进程——同步等待期内通道必然存活、进程自然结束，
  与 remote_ads_service 同一边界论证；代价=本地会话墙钟=座位墙钟。
- **轮询（poll）=长座位可选档**：``Start-Process cmd.exe``（新 console
  进程=0b-2 的 console 直指族，**非** schtasks 隐藏/wscript/
  -WindowStyle Hidden 禁用族）发射后立即返回；通道按 ``poll_interval_s``
  轮询三证据：rc 文件（``launch_rc.txt``，bat 模板增量行落盘）→ 完成；
  ``#261`` 命令行指纹进程查（含本批次 uuid，天然自排除 #261 自锁教训）
  → 存活；``port_ut_*`` 末行时间轴（#268 进度唯一可信口径）→ 前进旁证。
  发射后 60s/120s 双 CPU 采样存活复核（0b-2 红线：静默击杀钉到 2 分钟窗；
  连续 2 次"无 rc+无进程"才判静默消失——防完成竞态窗误判）。超时不代杀：
  PIDs 落信封交人工按 §5.6 处置。残险（如实）：会话级 job object 连坐
  可能仍波及分离进程（sshd 重启等）——v2 schtasks-console/常驻 runner
  备选，playbook §6 登记不落。

座位内容物（§5.5/C5 形态，本地只上传四件轻量文件）：``simulation.py``
（G1 本地渲染产物，服务器零渲染面：参数/网格/NrTS 与本地
render_input_sha256 逐字节同源）、``driver.py``（点驱动，生成产物自
描述：_rfauto_runner 引导+子进程执行，OpenEMSSolver.solve 同款形态）、
``criteria.md``（#122 判据先行，发射前必落盘，缺失 fail-closed）、
``run_task.bat``（§5.4 发射模板照抄+**CRLF**；增量=launch_rc.txt 落盘行，
poll 档 rc 判读用）。判据/健康门/nrts 门全在回拉后本地消费——产物回拉
镜像本地 ``runs/<campaign>/<template>/`` 布局（说明书 §5.5），判读器
零改动直读。

服务器侧约束（说明书 §六红线/ 0b）：工作根=注册表
``hfss.project_root``（E:\\rfauto_remote 语义，禁 D:\\CloudDrive）；任务
目录 ``tasks\\oe_<uuid8>`` 唯一化（并发批次不互踩）；发射前互斥预检
（#261 服务器侧进程指纹直查=权威判据 + §5.4 第 3 步 run_server_probe.ps1
mutex 行=旁证；非零命中=候跑 SKIP，rc≠0=验不了不发射 fail-closed，
**禁止代杀**）；02:50–05:35 备份窗发射=信封 ``backup_window_risk`` 如实
登记不阻断（overnight 队列合法用例，操作方自负）；任务毕清理
（Remove-Item+Test-Path 复核，清理失败翻 FAIL）+ cleanup_after_task.ps1
清点旁证（§5.6 清点形态，**绝不 -KillPids**——非本指纹实例不代杀）。

真机 opt-in 门：env ``RFAUTO_REMOTE_SMOKE=1``（与 remote_service 同门
单源 import；unit 门内一律拒绝，#139/df4⑥ 零真机零连网）。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.core.errors import RFAutoError
from rfauto.infra.remote_machines import (
    ENV_REMOTE_SSH_PASSWORD,
    ENV_REMOTE_SSH_USER,
    RemoteConfigError,
    SshTransport,
    load_remote_machines,
    probe_machine,
    resolve_machine,
)
from rfauto.service.envelope import skipped_envelope
from rfauto.service.remote_service import (
    REMOTE_SMOKE_ENV,
    remote_mutex_command,
    remote_mutex_precheck,
)

__all__ = [
    "REMOTE_OE_ENV",
    "RemoteOeError",
    "build_driver_py",
    "build_mutex_command",
    "build_run_task_bat",
    "remote_oe_run",
]

#: 真机 opt-in 门 env 名（与 remote_service.REMOTE_SMOKE_ENV 同值单源）。
REMOTE_OE_ENV = REMOTE_SMOKE_ENV

_BATCH_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
#: 0b-2 存活复核双采样时点（秒）——静默击杀钉到 2 分钟窗。
_SURVIVAL_SAMPLE_DELAYS_S = (60.0, 120.0)
#: 连续 N 次「无 rc+无进程」才判静默消失（防 bat 收尾竞态窗误判）。
_DEATH_CONFIRMATIONS = 2
#: 轮询档超时附加余量（座位 timeout 之外，§5.4 bat 收尾/清理余量）。
_POLL_GRACE_S = 600.0
#: 02:50–05:35 服务器备份窗（说明书 §六.3）——分钟数闭区间。
_BACKUP_WINDOW_MIN = (2 * 60 + 50, 5 * 60 + 35)
#: #261 互斥指纹（服务器侧 OE 家族 python 命令行；宁枉勿纵=候跑 SKIP）。
_MUTEX_FINGERPRINT = "_rfauto_runner|simulation\\.py|driver\\.py|fd_oe_campaign"


class RemoteOeError(RFAutoError):
    """openEMS 远程执行通道前置检查失败（座位内容物/路径安全/判据缺失）。"""


# ─── 纯函数构建器（零 SSH，可独立单测） ───────────────────────────────────


def _check_remote_safe(label: str, value: str) -> str:
    """远端命令注入面守卫：路径禁单引号、空白与 cmd 元字符（ge5 审查 F7）。

    远端命令形态=PS 原生单引号+cmd 裸路径（G5 零双引号纪律），含单引号/
    空白的路径无法安全引用；``& | < > ^ %`` 为 cmd/PS 元字符或变量展开
    前缀（合法路径不含），fail-closed 显式拒绝。
    """
    v = value.replace("/", "\\")
    bad = "'" if "'" in v else next(
        (ch for ch in v if ch.isspace() or ch in "&|<>^%"), None)
    if bad is not None:
        raise RemoteOeError(
            f"{label} 含单引号/空白/cmd 元字符 {bad!r}"
            "（远端命令零双引号纪律，无法安全引用）",
            details={"label": label, "value": value[:80]},
        )
    return v


def build_run_task_bat(task_dir: str, env_bat: str) -> bytes:
    """发射 bat（§5.4 模板照抄，**CRLF** 字节；增量行=launch_rc.txt 落盘）。

    模板要点（说明书 §5.4 第 5 步）：console 可见直指 / ``-u`` 防缓冲
    （#157）/ stdout·stderr 分文件落盘（#242）/ 结尾 ``exit /b %RC%`` 留痕。
    增量：``(echo rc=%RC%)> launch_rc.txt``——poll 档 rc 判读用（同步档 rc
    由 SSH 通道直得，两路互为旁证）；括号包 echo 防 ``rc=0>`` 被解析成
    句柄重定向（cmd 数字句柄陷阱）。
    """
    lines = [
        "@echo off",
        "rem openEMS 任务发射 sanctioned 形态"
        "（console 可见 / 0b-2 反杀毒静默击杀纪律）",
        "rem 生成器=remote_oe_service.build_run_task_bat；"
        "delta vs tools\\run_task_TEMPLATE.bat：",
        "rem   +launch_rc.txt 落盘行（poll 档 rc 判读用；同步档两路互为旁证）",
        f"call {env_bat}",
        f'set "TASK_DIR={task_dir}"',
        'if not exist "%TASK_DIR%" mkdir "%TASK_DIR%"',
        "cd /d %RFAUTO_REPO%",
        "",
        "echo [launch] %date% %time% task=%TASK_DIR%",
        '"%RFAUTO_PY%" -u "%TASK_DIR%\\driver.py" '
        '> "%TASK_DIR%\\driver.log" 2> "%TASK_DIR%\\driver.err"',
        "set RC=%errorlevel%",
        "echo [launch done] rc=%RC% at %date% %time%",
        '(echo rc=%RC%)> "%TASK_DIR%\\launch_rc.txt"',
        "echo product-census:",
        'dir /b "%TASK_DIR%"',
        "exit /b %RC%",
        "",
    ]
    return "\r\n".join(lines).encode("utf-8")


_DRIVER_TEMPLATE = '''# -*- coding: utf-8 -*-
"""openEMS 远程点驱动（remote_oe_service 生成产物，自描述留档）。

执行形态=adapters/openems_solver.OpenEMSSolver.solve 同款：
_rfauto_runner 引导（os.add_dll_directory 接线引擎 bin DLL，Py3.8+ 不走
PATH 解析扩展模块 DLL）+ 子进程执行 simulation.py（cwd=本目录），
stdout/stderr 分文件落 _last_stdout.log/_last_stderr.log（nrts 收敛门
证据面，#266）。rc 透传引擎退出码（timeout 到点=124）；"产物优先于
退出码"的判读在回拉后由本地判读面执行——本驱动不做产物判读。
"""
import os
import subprocess
import sys

TASK_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.environ.get("RFAUTO_OPENEMS_BIN", "")
TIMEOUT_S = __TIMEOUT_S__


def _as_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _write_runner():
    lines = ["import os", "import runpy", "import sys"]
    if BIN_DIR:
        lines.append("os.add_dll_directory(%r)" % BIN_DIR)
        lines.append("os.environ['PATH'] = %r + os.pathsep + "
                     "os.environ.get('PATH', '')" % BIN_DIR)
    lines.append("runpy.run_path(sys.argv[1], run_name='__main__')")
    path = os.path.join(TASK_DIR, "_rfauto_runner.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\\n".join(lines) + "\\n")
    return path


def main():
    runner = _write_runner()
    cmd = [sys.executable, runner, os.path.join(TASK_DIR, "simulation.py")]
    try:
        proc = subprocess.run(cmd, cwd=TASK_DIR, capture_output=True,
                              text=True, timeout=TIMEOUT_S)
        rc = proc.returncode
        out, err = proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        rc = 124
        out = _as_text(getattr(exc, "stdout", None))
        err = _as_text(getattr(exc, "stderr", None))
        err += "\\ndriver: engine timeout (solve_timeout_s=%s)" % TIMEOUT_S
    for name, text in (("_last_stdout.log", out), ("_last_stderr.log", err)):
        with open(os.path.join(TASK_DIR, name), "w", encoding="utf-8",
                  errors="replace") as fh:
            fh.write(text)
    print("driver done rc=", rc, flush=True)
    return rc if isinstance(rc, int) and rc != 0 else 0


if __name__ == "__main__":
    sys.exit(main())
'''


def build_driver_py(timeout_s: float) -> str:
    """服务器侧点驱动（OpenEMSSolver.solve 同款形态，生成产物自描述）。

    超时经 ``__TIMEOUT_S__`` token 注入（repr 数值字面量；不用 str.format
    ——模板内含大量字面花括号形态代码，token 替换零转义负担）。
    """
    return _DRIVER_TEMPLATE.replace("__TIMEOUT_S__", repr(float(timeout_s)))


def build_mutex_command(fingerprint: str = _MUTEX_FINGERPRINT) -> str:
    """#261 服务器侧互斥探针命令（PS 原生零双引号；命中行=pid|commandline）。

    X4 批起为共享单源 :func:`remote_service.remote_mutex_command` 的 OE
    通道薄委托（进程域钉 python.exe、指纹缺省 `_MUTEX_FINGERPRINT`——
    本模块公开面签名/产出逐字节不变）；G5 纪律：``$_`` 管道经 paramiko
    直达远端 PS（无本地 shell 层展开），全程单引号零双引号；指纹为正则
    （``simulation\\.py`` 点号转义）。
    """
    return remote_mutex_command("python.exe", fingerprint)


def _in_backup_window(tm: time.struct_time) -> bool:
    """发射时刻是否落在 02:50–05:35 服务器备份窗（说明书 §六.3）。

    时钟归属假设（ge5 审查 F6 登记）：入参取本机 ``time.localtime()``，
    语义归属服务器侧时钟——同 lab 同 TZ 假设下无实害；跨 TZ 部署时
    调用方应改喂服务器侧时间。
    """
    minutes = tm.tm_hour * 60 + tm.tm_min
    return _BACKUP_WINDOW_MIN[0] <= minutes <= _BACKUP_WINDOW_MIN[1]


# ─── 服务器侧查询（SshTransport 消费面，FakeTransport 可钉） ──────────────


def _parse_pid_cpu_lines(out: str) -> list[dict[str, Any]]:
    """``pid|cpu`` 行解析（cpu 空/非数=登记 None，不影响在场判定）。"""
    procs: list[dict[str, Any]] = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln or "|" not in ln:
            continue
        pid_s, _, cpu_s = ln.partition("|")
        try:
            cpu: float | None = float(cpu_s) if cpu_s.strip() else None
        except ValueError:
            cpu = None
        procs.append({"pid": pid_s.strip(), "cpu_s": cpu})
    return procs


def _remote_mutex(transport: SshTransport, work_root: str) -> dict[str, Any]:
    """互斥预检（#261 服务器侧）：共享单源
    :func:`remote_service.remote_mutex_precheck` 的 OE 通道薄委托（进程域
    python.exe + 指纹 `_MUTEX_FINGERPRINT`）——进程指纹直查=权威判据 +
    §5.4 第 3 步 run_server_probe.ps1 mutex 行=旁证。直查 rc≠0（验不了）
    → busy=True fail-closed。命中=候跑，**禁止代杀**（本模块无任何杀
    进程命令）。语义与解析细节见共享单源 docstring。"""
    return remote_mutex_precheck(
        transport, work_root,
        process_name="python.exe", fingerprint=_MUTEX_FINGERPRINT,
    )


def _read_launch_rc(transport: SshTransport,
                    task_dir: str) -> tuple[bool, int | None]:
    """读 launch_rc.txt（poll 档完成判据）→ (存在, rc 或 None)。"""
    rc_file = f"{task_dir}\\launch_rc.txt"
    rc, out, _e = transport.run_command(
        f"Test-Path -LiteralPath '{rc_file}'", timeout_s=20.0)
    if rc != 0 or out.strip() != "True":
        return False, None
    _rc2, out2, _e2 = transport.run_command(
        f"Get-Content -LiteralPath '{rc_file}' -TotalCount 1", timeout_s=20.0)
    text = out2.strip()
    try:
        return True, int(text.split("=")[-1])
    except (ValueError, IndexError):
        return True, None


def _remote_batch_procs(transport: SshTransport,
                        batch: str) -> list[dict[str, Any]]:
    """按批次 uuid 指纹查存活进程（pid|cpu 行；批次 uuid 天然自排除）。"""
    cmd = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -match '" + batch + "' } | "
        "ForEach-Object { $p = Get-Process -Id $_.ProcessId "
        "-ErrorAction SilentlyContinue; "
        "'{0}|{1}' -f $_.ProcessId, $p.CPU }"
    )
    rc, out, _e = transport.run_command(cmd, timeout_s=30.0)
    if rc != 0:
        return []
    return _parse_pid_cpu_lines(out)


def _port_ut_tails(transport: SshTransport,
                   task_dir: str) -> dict[str, float | None]:
    """port_ut_* 末行时间轴（#268：轮询期进度唯一可信口径，best-effort）。"""
    cmd = (
        "Get-ChildItem -LiteralPath '" + task_dir + "\\fdtd' "
        "-Filter 'port_ut_*' -ErrorAction SilentlyContinue | "
        "ForEach-Object { $t = Get-Content -LiteralPath $_.FullName "
        "-Tail 1 -ErrorAction SilentlyContinue; "
        "'{0}|{1}' -f $_.Name, $t }"
    )
    rc, out, _e = transport.run_command(cmd, timeout_s=30.0)
    tails: dict[str, float | None] = {}
    if rc != 0:
        return tails
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln or "|" not in ln:
            continue
        name, _, tail = ln.partition("|")
        last = tail.strip().split()[-1] if tail.strip() else ""
        try:
            tails[name.strip()] = float(last)
        except ValueError:
            tails[name.strip()] = None
    return tails


def _survival_check(transport: SshTransport, batch: str, task_dir: str,
                    sleep_fn: Callable[[float], None]) -> dict[str, Any]:
    """0b-2 存活复核：发射后 60s/120s 双采样（进程在场+CPU 增量）。

    任一采样点 rc 文件已落=座位提前完成（短座位合法，复核让位完成证据）；
    双采样零进程且无 rc=静默击杀嫌疑（最终判定仍由轮询环连续确认兜底）。
    """
    samples: list[dict[str, Any]] = []
    last_delay = 0.0
    rc_early: int | None = None
    rc_early_seen = False
    for delay in _SURVIVAL_SAMPLE_DELAYS_S:
        sleep_fn(max(0.0, delay - last_delay))
        last_delay = delay
        seen, val = _read_launch_rc(transport, task_dir)
        if seen:
            rc_early_seen = True
            rc_early = val
            break
        procs = _remote_batch_procs(transport, batch)
        samples.append({
            "delay_s": delay,
            "n_procs": len(procs),
            "pids": [p["pid"] for p in procs],
            "cpu_sum_s": round(sum(p["cpu_s"] or 0.0 for p in procs), 2),
        })
    alive = any(s["n_procs"] > 0 for s in samples)
    progress = (
        len(samples) == 2
        and samples[1]["cpu_sum_s"] > samples[0]["cpu_sum_s"]
    )
    return {"samples": samples, "alive": alive, "cpu_progress": progress,
            "rc_early_seen": rc_early_seen, "rc_early": rc_early}


def _poll_wait(transport: SshTransport, batch: str, task_dir: str,
               *, poll_interval_s: float, poll_timeout_s: float,
               sleep_fn: Callable[[float], None],
               now_fn: Callable[[], float]) -> dict[str, Any]:
    """轮询等待环（长座位档）：rc 文件→完成；指纹进程→存活；
    port_ut 时间轴→前进旁证；连续无进程无 rc→静默消失；超时不代杀。
    rc 文件在档但内容不可解析（非 ``rc=<int>`` 形态）→ ``rc_parse_failed``
    显式置位（ge5 审查 F1：信封层据实降档 PARTIAL，非静默假 PASS）。"""
    t0 = now_fn()
    history: list[dict[str, Any]] = []
    dead_streak = 0
    while True:
        seen, rc_val = _read_launch_rc(transport, task_dir)
        if seen:
            return {"done": True, "exec_rc": rc_val, "silent_death": False,
                    "timeout": False, "history": history,
                    "rc_parse_failed": rc_val is None}
        procs = _remote_batch_procs(transport, batch)
        tails = _port_ut_tails(transport, task_dir)
        history.append({"t_s": round(now_fn() - t0, 1),
                        "n_procs": len(procs),
                        "port_ut_tails": dict(sorted(tails.items()))})
        if not procs:
            dead_streak += 1
            if dead_streak >= _DEATH_CONFIRMATIONS:
                return {"done": False, "exec_rc": None,
                        "silent_death": True, "timeout": False,
                        "history": history}
        else:
            dead_streak = 0
        if now_fn() - t0 > poll_timeout_s:
            return {"done": False, "exec_rc": None,
                    "silent_death": False, "timeout": True,
                    "pids": [p["pid"] for p in procs],
                    "history": history}
        sleep_fn(max(0.0, poll_interval_s))


# ─── 回拉/清理（与 remote_ads_service 同构面） ────────────────────────────


def _fetch_task_dir(transport: SshTransport, task_dir: str,
                    out_path: Path) -> dict[str, Any]:
    """枚举任务目录全文件 → sftp 逐文件回拉本地镜像（§5.5 布局）。

    枚举命令 rc≠0（非静默失败）→ 显式报错 fail-closed（缺证据可见，
    不冒充空产物）。
    """
    rc, listing, err = transport.run_command(
        f"Get-ChildItem -LiteralPath '{task_dir}' -Recurse -File "
        "-ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }",
        timeout_s=120.0,
    )
    if rc != 0:
        raise RemoteOeError(
            f"任务目录枚举失败 rc={rc}（fail-closed）{err[:120]}",
            details={"task_dir": task_dir},
        )
    remote_files = [
        ln.strip().replace("/", "\\")
        for ln in listing.splitlines() if ln.strip()
    ]
    prefix = task_dir.lower() + "\\"
    fetch: dict[str, Any] = {"files": 0, "bytes": 0, "items": [],
                             "listed": len(remote_files)}
    for f_win in remote_files:
        if not f_win.lower().startswith(prefix):
            raise RemoteOeError(
                f"任务目录枚举路径越出任务目录: {f_win[:120]}")
        rel = f_win[len(task_dir):].lstrip("\\/").replace("\\", "/")
        f_local = out_path / rel
        f_local.parent.mkdir(parents=True, exist_ok=True)
        transport.download_file(f_win.replace("\\", "/"), f_local)
        fetch["bytes"] += f_local.stat().st_size
        fetch["files"] += 1
        fetch["items"].append({"remote": f_win.replace("\\", "/"),
                               "local": str(f_local)})
    return fetch


def _cleanup_census(transport: SshTransport, work_root: str) -> dict[str, Any]:
    """§5.6 清点旁证（只列不杀；脚本缺席=如实登记不致命）。"""
    ps1 = f"{work_root}\\kit\\06_tools\\cleanup_after_task.ps1"
    rc, out, err = transport.run_command(
        "powershell -NoProfile -ExecutionPolicy Bypass -File " + ps1,
        timeout_s=180.0,
    )
    return {"rc": rc, "output_tail": out[-800:], "stderr_head": err[:200]}


def _cleanup_remote_taskdir(
    transport: SshTransport, task_dir: str,
) -> dict[str, Any]:
    """删除服务器侧任务目录并 Test-Path 复核（任务毕必须清理， 0b）。"""
    rc, _out, err = transport.run_command(
        f"Remove-Item -LiteralPath '{task_dir}' -Recurse -Force "
        "-ErrorAction SilentlyContinue",
        timeout_s=120.0,
    )
    _rc2, out2, _e2 = transport.run_command(
        f"Test-Path -LiteralPath '{task_dir}'", timeout_s=20.0)
    verified = out2.strip() == "False"
    return {
        "ok": bool(rc == 0 and verified),
        "task_dir": task_dir,
        "rc": rc,
        "verified_gone": verified,
        "stderr_head": err[:200],
    }


# ─── 主编排（JSON 信封进出，fail-closed） ─────────────────────────────────


def _validate_seat_spec(seat_spec: dict[str, Any]) -> tuple[str, str, str]:
    """座位内容物校验（纯本地）→ (template, campaign, timeout_s 文本)。"""
    if not isinstance(seat_spec, dict):
        raise RemoteOeError("seat_spec 必须是 dict")
    template = str(seat_spec.get("template") or "")
    if not _BATCH_RE.fullmatch(template):
        raise RemoteOeError(
            "seat_spec.template 缺失或含非法字符（只允许字母/数字/_/-）",
            details={"template": template[:40]},
        )
    if not str(seat_spec.get("simulation_py") or "").strip():
        raise RemoteOeError(
            "seat_spec.simulation_py 缺失（G1 渲染产物文本必须由本地提供，"
            "服务器零渲染面）")
    if not str(seat_spec.get("criteria_md") or "").strip():
        raise RemoteOeError(
            "seat_spec.criteria_md 缺失（#122 判据先行：发射前判据必须落盘，"
            "fail-closed 不发射）")
    try:
        timeout_s = float(seat_spec.get("timeout_s") or 0.0)
    except (TypeError, ValueError):
        raise RemoteOeError("seat_spec.timeout_s 非数值") from None
    if timeout_s <= 0:
        raise RemoteOeError("seat_spec.timeout_s 必须 > 0（引擎 subprocess "
                            "硬边界）")
    campaign = str(seat_spec.get("campaign") or "")
    if not _BATCH_RE.fullmatch(campaign):
        raise RemoteOeError(
            "seat_spec.campaign 缺失或含非法字符（回拉镜像目录名）",
            details={"campaign": campaign[:40]},
        )
    return template, campaign, timeout_s


def remote_oe_run(
    machine: str | None,
    seat_spec: dict[str, Any],
    *,
    out_dir: str | Path | None = None,
    wait_mode: str = "sync",
    exec_timeout_s: float = 0.0,
    poll_interval_s: float = 60.0,
    keep_remote: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """openEMS 远程执行通道五步编排（**真机 opt-in**：``RFAUTO_REMOTE_SMOKE=1``）。

    编排：探活 → 座位校验 → 互斥预检（#261，命中=候跑 SKIP 不发射）→
    建任务目录+上传四件轻量文件（simulation.py/driver.py/criteria.md/
    run_task.bat，bat CRLF 字节核验）→ 发射（sync=阻塞直指 / poll=分离+
    存活复核+轮询）→ 产物回拉镜像 ``out_dir``（缺省
    ``runs/<campaign>/<template>/``）→ finally 清理+census 旁证（清理失败
    翻 FAIL；``keep_remote=True`` 调试留档如实落账）。

    Parameters
    ----------
    machine :
        注册表机器名（None=唯一登记机器）。
    seat_spec :
        ``{template, simulation_py, criteria_md, timeout_s, campaign[,
        render_sha256]}``——见模块 docstring 座位内容物。
    out_dir :
        回拉镜像目录（缺省 ``runs/<campaign>/<template>/``）。
    wait_mode :
        ``"sync"``（缺省，阻塞直指）/ ``"poll"``（长座位，分离+轮询）——
        取舍论证见模块 docstring。
    exec_timeout_s :
        同步档 SSH 等待上限/轮询档超时基线；0=座位 timeout+余量。
    poll_interval_s :
        轮询间隔（可配）。
    keep_remote :
        True=跳过服务器侧清理（调试留档，任务毕须人工清理）。
    sleep_fn :
        等待注入点（单测零真睡）。
    now_fn :
        时钟注入点（轮询超时判定的单测可 advancing 假钟）。

    Returns
    -------
    dict
        ``{"ok", "verdict": "PASS"/"PARTIAL"/"FAIL", "skipped", "launched",
        "reason", "machine", "batch", "task_dir_remote", "out_dir_local",
        "exec_rc", "wait_mode", "render_sha256", "backup_window_risk",
        "criteria": {c1_mutex_clear, c2_products_fetched,
        c3_workdir_cleaned}, "steps": {probe/mutex/ssh/upload/launch/wait/
        fetch/cleanup}}``。ok=链路走通（发射+回拉≥1 文件+清理过）——rc≠0
        但产物在=ok 且 verdict=PARTIAL（判读交回拉后本地判读面，rc 随信封
        落账）；skipped=True=前置不满足未发射（互斥候跑/凭据缺/env 门）。
    """
    # ── env 门（真机 opt-in） ──
    if os.environ.get(REMOTE_OE_ENV) != "1":
        return skipped_envelope(
            f"真机远跑需显式 opt-in：{REMOTE_OE_ENV}=1（unit 门零真机）",
            ok=False,
        )
    try:
        template, campaign, timeout_s = _validate_seat_spec(seat_spec)
    except RemoteOeError as exc:
        return {"ok": False, "verdict": "FAIL", "skipped": False,
                "launched": False, "reason": str(exc)[:240],
                "criteria": {}, "steps": {}}
    if wait_mode not in ("sync", "poll"):
        return {"ok": False, "verdict": "FAIL", "skipped": False,
                "launched": False, "reason": f"wait_mode 非法: {wait_mode}",
                "criteria": {}, "steps": {}}

    machines = load_remote_machines()
    if machine is None and not machines:
        return skipped_envelope("无登记机器", ok=False)
    try:
        cfg = resolve_machine(machine, machines)
    except RemoteConfigError as exc:
        # 机器名未登记/多机未指名（ge5 审查 F3）：裸抛改 fail-closed 信封
        # （与 remote_ads_service 同批同构，避免直连消费面通道分叉）。
        return skipped_envelope(
            f"机器解析失败（注册表无此名或多机未指名）: {exc}", ok=False)
    steps: dict[str, Any] = {"probe": probe_machine(cfg)}

    has_user = bool(cfg.ssh_user or os.environ.get(ENV_REMOTE_SSH_USER))
    has_secret = bool(
        cfg.ssh_key_path or cfg.ssh_password
        or os.environ.get(ENV_REMOTE_SSH_PASSWORD)
    )
    if not (has_user and has_secret):
        steps["ssh"] = {"auth": "missing_credentials"}
        return skipped_envelope(
            "SSH 凭据缺失（RFAUTO_REMOTE_SSH_USER/PASSWORD 或 local 覆盖）",
            ok=False, steps=steps,
        )
    if not cfg.hfss_project_root:
        return skipped_envelope(
            "机器未登记 hfss.project_root（服务器侧工作根，"
            "禁 D:\\CloudDrive 语义靠此钉）",
            ok=False, steps=steps,
        )
    try:
        work_root = _check_remote_safe("hfss.project_root", cfg.hfss_project_root)
        # 纵深防御（ge5 审查 F5）：登记正确性之外显式拒绝生产云盘前缀
        #
        if work_root.replace("/", "\\").lower().startswith("d:\\clouddrive"):
            raise RemoteOeError(
                "hfss.project_root 禁写生产云盘 D:\\CloudDrive"
                "（中间文件只落服务器本机工作根， 规则 0b）",
                details={"work_root": work_root[:80]},
            )
        env_bat = _check_remote_safe(
            "oe_env_bat", str(cfg.extra.get("oe_env_bat")
                              or f"{work_root}\\rfauto_env.bat"))
    except RemoteOeError as exc:
        return {"ok": False, "verdict": "FAIL", "skipped": False,
                "launched": False, "reason": str(exc)[:240],
                "criteria": {}, "steps": steps}

    batch = f"oe_{uuid.uuid4().hex[:8]}"
    task_dir = f"{work_root}\\tasks\\{batch}"
    out_path = (
        Path(out_dir) if out_dir is not None
        else Path("runs") / campaign / template
    )
    exec_timeout = float(exec_timeout_s) if exec_timeout_s > 0 else (
        timeout_s + _POLL_GRACE_S)

    envelope: dict[str, Any] = {
        "ok": False,
        "verdict": "FAIL",
        "skipped": False,
        "launched": False,
        "reason": None,
        "errors": [],
        "machine": cfg.name,
        "batch": batch,
        "task_dir_remote": task_dir,
        "out_dir_local": str(out_path),
        "exec_rc": None,
        "wait_mode": wait_mode,
        "render_sha256": seat_spec.get("render_sha256"),
        "backup_window_risk": _in_backup_window(time.localtime()),
        "criteria": {"c1_mutex_clear": None, "c2_products_fetched": None,
                     "c3_workdir_cleaned": None},
        "steps": steps,
    }

    transport = SshTransport(cfg)
    wait_result: dict[str, Any] | None = None
    try:
        transport.connect()
        steps["ssh"] = {"auth": "ok"}

        # ① 互斥预检（#261 服务器侧；命中=候跑 SKIP，绝不代杀不抢席位）
        mutex = _remote_mutex(transport, work_root)
        steps["mutex"] = mutex
        envelope["criteria"]["c1_mutex_clear"] = not mutex["busy"]
        if mutex["busy"]:
            envelope["skipped"] = True
            envelope["reason"] = mutex.get("reason") or "互斥命中=候跑"
            return envelope

        # ② 任务目录+上传（§5.4 第 2 步建目录、判据先行落盘；sftp 二进制
        #    安全——本地 CRLF 字节=远端字节，本地核验即远端核验）
        rc, _out, err = transport.run_command(
            f"New-Item -ItemType Directory -Force -Path '{task_dir}' "
            "| Out-Null",
            timeout_s=30.0,
        )
        if rc != 0:
            envelope["reason"] = f"服务器侧任务目录创建失败: {err[:120]}"
            return envelope
        stage = Path(tempfile.mkdtemp(prefix=f"rfauto_oe_{batch}_"))
        try:
            sim_local = stage / "simulation.py"
            sim_local.write_text(str(seat_spec["simulation_py"]),
                                 encoding="utf-8")
            crit_local = stage / "criteria.md"
            crit_local.write_text(str(seat_spec["criteria_md"]),
                                  encoding="utf-8")
            drv_local = stage / "driver.py"
            drv_local.write_text(build_driver_py(timeout_s), encoding="utf-8")
            bat_bytes = build_run_task_bat(task_dir, env_bat)
            bat_local = stage / "run_task.bat"
            bat_local.write_bytes(bat_bytes)
            bat_crlf_ok = (
                bat_bytes.count(b"\r\n") == bat_bytes.count(b"\n")
                and bat_bytes.count(b"\n") > 0
            )
            if not bat_crlf_ok:
                envelope["reason"] = "run_task.bat CRLF 核验失败（写侧缺陷）"
                return envelope
            task_sftp = task_dir.replace("\\", "/")
            upload_rec: dict[str, Any] = {"n_files": 0, "bytes": 0,
                                          "bat_crlf_ok": True,
                                          "bat_sha256": hashlib.sha256(
                                              bat_bytes).hexdigest(),
                                          "files": []}
            for local_p in (sim_local, crit_local, drv_local, bat_local):
                transport.upload_file(local_p, f"{task_sftp}/{local_p.name}")
                upload_rec["files"].append(local_p.name)
                upload_rec["n_files"] += 1
                upload_rec["bytes"] += local_p.stat().st_size
            steps["upload"] = upload_rec
        finally:
            shutil.rmtree(stage, ignore_errors=True)

        # ③ 发射+等待（sync=阻塞直指 / poll=分离+存活复核+轮询）
        if wait_mode == "sync":
            launch_cmd = f"cmd /c {task_dir}\\run_task.bat"
            t0 = time.monotonic()
            lrc, out, err = transport.run_command(
                launch_cmd, timeout_s=exec_timeout)
            wall = time.monotonic() - t0
            envelope["launched"] = True
            envelope["exec_rc"] = lrc
            rc_cross = _read_launch_rc(transport, task_dir)
            steps["launch"] = {"mode": "sync", "command": launch_cmd,
                               "rc": lrc, "wall_s": round(wall, 1),
                               "stdout_tail": out[-2000:],
                               "stderr_head": err[:500]}
            steps["wait"] = {
                "mode": "sync", "wall_s": round(wall, 1),
                "rc_file_crosscheck": {"seen": rc_cross[0],
                                       "rc": rc_cross[1]},
            }
            wait_result = {"done": True, "exec_rc": lrc,
                           "silent_death": False, "timeout": False}
        else:
            launch_cmd = (
                "Start-Process -FilePath 'cmd.exe' "
                f"-ArgumentList '/c','{task_dir}\\run_task.bat' "
                f"-WorkingDirectory '{task_dir}'")
            lrc, out, err = transport.run_command(launch_cmd, timeout_s=60.0)
            if lrc != 0:
                envelope["launched"] = True
                envelope["reason"] = (
                    f"poll 发射命令失败 rc={lrc}（Start-Process 直指形态）"
                    f"{err[:160]}")
                return envelope
            envelope["launched"] = True
            survival = _survival_check(transport, batch, task_dir, sleep_fn)
            if survival["rc_early_seen"]:
                # 短座位在存活采样期即完成：rc 早到=完成证据。rc 在档但
                # 不可解析（rc_early=None）同样显式置位（F1 信封传播语义
                # 与 poll 环统一，不静默假 PASS）。
                wait_result = {"done": True, "exec_rc": survival["rc_early"],
                               "silent_death": False, "timeout": False,
                               "rc_parse_failed":
                                   survival["rc_early"] is None,
                               "survival": survival}
            elif not survival["alive"]:
                # 双采样零进程且无 rc：静默击杀嫌疑，交轮询环连续确认兜底
                wait_result = _poll_wait(
                    transport, batch, task_dir,
                    poll_interval_s=poll_interval_s,
                    poll_timeout_s=min(300.0, exec_timeout),
                    sleep_fn=sleep_fn, now_fn=now_fn)
                wait_result["survival"] = survival
            else:
                poll_timeout = exec_timeout + _POLL_GRACE_S
                wait_result = _poll_wait(
                    transport, batch, task_dir,
                    poll_interval_s=poll_interval_s,
                    poll_timeout_s=poll_timeout, sleep_fn=sleep_fn,
                    now_fn=now_fn)
                wait_result["survival"] = survival
            envelope["exec_rc"] = wait_result.get("exec_rc")
            steps["launch"] = {"mode": "poll", "command": launch_cmd,
                               "rc": lrc}
            steps["wait"] = {
                "mode": "poll",
                "survival": survival,
                "done": wait_result.get("done"),
                "silent_death": wait_result.get("silent_death"),
                "timeout": wait_result.get("timeout"),
                "rc_parse_failed": bool(wait_result.get("rc_parse_failed")),
                "polls": len(wait_result.get("history", [])),
                "history_tail": (wait_result.get("history") or [])[-3:],
            }

        # ④ 回拉（无论引擎 rc/等待结局——证据面缺位要可见，#105）
        out_path.mkdir(parents=True, exist_ok=True)
        fetch = _fetch_task_dir(transport, task_dir, out_path)
        steps["fetch"] = fetch
        envelope["criteria"]["c2_products_fetched"] = fetch["files"] >= 1
        if wait_result is not None and not wait_result.get("done"):
            if wait_result.get("timeout"):
                envelope["reason"] = (
                    "轮询超时（不代杀，PIDs 已登记人工处置: "
                    f"{wait_result.get('pids')}）")
            elif wait_result.get("silent_death"):
                envelope["reason"] = (
                    "进程静默消失（发射后无 rc 无进程，0b-2 静默击杀嫌疑；"
                    "部分产物已回拉为证据）")
        elif fetch["files"] < 1:
            envelope["reason"] = (
                f"服务器侧任务目录无可回拉产物（exec_rc="
                f"{envelope['exec_rc']}）——核对 driver.log/_last_stderr 与"
                "判据")
        elif wait_result is not None and wait_result.get("rc_parse_failed"):
            # poll 档 rc 文件不可解析（ge5 审查 F1）：launch_rc.txt 在档但
            # 内容非 rc=<int> 形态——引擎退出码不可证，信封显式降档 PARTIAL
            # （campaign 层 solve_success=(exec_rc==0)=False 同步降档），
            # 非静默假 PASS。
            envelope["ok"] = True
            envelope["verdict"] = "PARTIAL"
            envelope["errors"].append(
                "rc_parse_failed: launch_rc.txt 在档但内容不可解析"
                "（非 rc=<int> 形态），引擎退出码不可证")
            envelope["reason"] = (
                "poll 档 rc 文件不可解析（launch_rc.txt 非 rc=<int> 形态）"
                f"——退出码不可证，产物已回拉 {fetch['files']} 文件交本地"
                "判读面（seat 判读按 solve_success=False 降档）")
            return envelope
        elif envelope["exec_rc"] is not None and envelope["exec_rc"] < 0:
            # 通道死亡语义（ge5 审查 F2）：paramiko transport 死亡返回 rc=-1，
            # 非引擎退出码——归因文案单列，verdict 仍 PARTIAL+solve_success
            # False 降档（G7 论证下引擎随通道终止、清理时序安全）
            envelope["ok"] = True
            envelope["verdict"] = "PARTIAL"
            envelope["reason"] = (
                f"SSH 通道异常 rc={envelope['exec_rc']}（transport 死亡语义"
                f"非引擎退出码，产物已回拉 {fetch['files']} 文件）——判读交"
                "本地判读面（产物优先于退出码口径），seat 判读按 "
                "solve_success=False 降档")
            return envelope
        elif envelope["exec_rc"] not in (0, None):
            envelope["ok"] = True
            envelope["verdict"] = "PARTIAL"
            envelope["reason"] = (
                f"引擎 rc={envelope['exec_rc']} 非零但产物已回拉"
                f"（{fetch['files']} 文件）——判读交本地判读面（产物优先于"
                "退出码口径），seat 判读按 solve_success=False 降档")
            return envelope
        else:
            envelope["ok"] = True
            envelope["verdict"] = "PASS"
            return envelope
        return envelope
    except Exception as exc:  # fail-closed：链路裸抛也落失败信封（L2 同构）
        envelope["ok"] = False
        envelope["verdict"] = "FAIL"
        envelope["reason"] = (
            f"OE 远跑链路异常: {type(exc).__name__}: {str(exc)[:160]}"
        )
        return envelope
    finally:
        # 任务毕必须清理：census 旁证（只列不杀）→ Remove-Item
        # + Test-Path 复核；清理失败翻 FAIL（数据已回拉仍不许留远端垃圾）。
        try:
            if keep_remote:
                cleanup: dict[str, Any] = skipped_envelope(
                    "keep_remote=True（调试留档，任务毕须人工清理）",
                    task_dir=task_dir,
                )
            else:
                census = _cleanup_census(transport, work_root)
                cleanup = _cleanup_remote_taskdir(transport, task_dir)
                cleanup["census"] = census
        except Exception as exc:
            cleanup = {
                "ok": False,
                "reason": f"清理异常: {type(exc).__name__}",
                "task_dir": task_dir,
            }
        steps["cleanup"] = cleanup
        if (
            envelope.get("ok")
            and not cleanup.get("ok", False)
            and not cleanup.get("skipped", False)
        ):
            envelope["ok"] = False
            envelope["verdict"] = "FAIL"
            envelope["reason"] = (
                "服务器侧任务目录清理未通过（任务毕必须清理， 0b）"
            )
        envelope["criteria"]["c3_workdir_cleaned"] = bool(
            cleanup.get("skipped") or cleanup.get("verified_gone")
        )
        transport.close()
