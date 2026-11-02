"""#261 openEMS 单飞互斥守卫内核（全进程表父链爬升自排除）。

背景（runs/dp10_j2j3/j3_chain/_recovery_note.md 披露，2026-09-30 修复）：
旧式祖先自排除只在「命中互斥模式的进程子集」里爬父链——分离发射形态
（Start-Process 发射器命令行含互斥模式串、driver 本体命令行不命中）下
driver 不在该子集→父链第一步即断→发射器被误判他席→rc=1 自锁拒射
（实证：runs/dp10_j2j3/j3_chain/chain_coarse_launch.log 首段）。

修法（_recovery_note 修法建议原文）：先取**全进程表** PID→PPID 映射，
从当前进程沿父链爬升得祖先集（含自身），再对命中互斥模式的行做
「pid ∈ 祖先集 → 自排除」。driver 是否命中模式不再影响父链认领。

消费者：runs/dp10_j2j3/j3_chain/j3_chain.py::_oe_mutex_processes（薄包装：
query_process_table() + filter_mutex_busy()）；行为钉
tests/unit/test_oe_mutex_guard.py（合成进程表，零 PowerShell/零真机依赖）。

匹配语义：互斥模式一律 re.IGNORECASE——与旧 PowerShell ``-match``（大小写
不敏感）逐位对齐，修复只动祖先认领、不收窄/放宽匹配面（模式串中
``simulation\\.py`` 命中他席 pytest 测试文件名的定性=保留现状，理由见
测试模块 docstring）。
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

__all__ = ["filter_mutex_busy", "query_process_table"]

#: 父链爬升步数帽（环链已由「祖先重复即停」兜底，帽只防超长链空转）
_MAX_ANCESTRY_HOPS = 64


def filter_mutex_busy(
    rows: list[dict[str, Any]],
    current_pid: int,
    pattern: str | re.Pattern[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """全进程表父链爬升自排除（纯函数，合成进程表可钉）。

    rows：全进程表行（ProcessId/ParentProcessId/Name/CommandLine；缺键/
    非整型容忍——系统进程 CommandLine 可为 None）。current_pid：当前进程。
    pattern：互斥模式（str 按 re.IGNORECASE 编译；Pattern 原样使用）。

    返回 (busy, matched)：matched=命中模式行（归一为
    ``{"pid","name","cmdline"}``）；busy=matched 中 pid 不在 current_pid
    祖先集（含自身）的行=真他席。父链爬升用全表映射（不限于命中子集，
    _recovery_note bug① 修复点），环链/≤0 PID/自指父即停。
    """
    regex = (re.compile(pattern, re.IGNORECASE) if isinstance(pattern, str)
             else pattern)
    matched: list[dict[str, Any]] = []
    parent_of: dict[int, int] = {}
    for d in rows:
        try:
            pid = int(d.get("ProcessId"))
        except (TypeError, ValueError):
            continue
        try:
            parent_of[pid] = int(d.get("ParentProcessId") or 0)
        except (TypeError, ValueError):
            parent_of[pid] = 0
        cmdline = str(d.get("CommandLine") or "")
        if regex.search(cmdline):
            matched.append({"pid": pid, "name": str(d.get("Name") or ""),
                            "cmdline": cmdline})
    ancestry: set[int] = set()
    pid = int(current_pid)
    for _ in range(_MAX_ANCESTRY_HOPS):
        if pid <= 0 or pid in ancestry:
            break
        ancestry.add(pid)
        nxt = parent_of.get(pid, 0)
        if nxt == pid:
            break
        pid = nxt
    busy = [m for m in matched if m["pid"] not in ancestry]
    return busy, matched


def query_process_table(timeout_s: int = 60) -> list[dict[str, Any]]:
    """全进程表快照（ProcessId/ParentProcessId/Name/CommandLine 行）。

    #289：内联 ``powershell -Command`` 的 ``$_`` 会被 shell 层展开/引号
    嵌套不可过——临时 .ps1 落盘 + ``-NoProfile -ExecutionPolicy Bypass
    -File``。rc≠0 显式 RuntimeError（fail-closed：验不了不发射，同旧口径）。
    """
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False,
                                     encoding="utf-8") as fh:
        fh.write("Get-CimInstance Win32_Process | "
                 "Select-Object ProcessId,ParentProcessId,Name,CommandLine"
                 " | ConvertTo-Json -Compress\n")
        ps1 = Path(fh.name)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1)],
            capture_output=True, text=True, timeout=timeout_s)
    finally:
        ps1.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"互斥探测失败 rc={proc.returncode}: "
                           f"{proc.stderr}")
    txt = proc.stdout.strip()
    if not txt:
        return []
    data = json.loads(txt)
    if isinstance(data, dict):
        data = [data]
    return [dict(d) for d in data]
