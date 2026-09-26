"""ansysedt 桌面进程治理单源（桌面治理批；fail-closed 范式）。

范式（scripts/factory_mf_hfss_anchors.py 原型 + hfss_interdigital_check.py
预检/看门狗口径，坑账 #245/#265/#145/#105）：

- 枚举（pid/ppid/命令行）失败 → **不杀**：strict 抛错 / 非 strict 记录
  （#245 杀前必须核对命令行，不盲杀）。
- 活桌面（父进程存活）→ **绝不代杀**：strict 抛"活桌面"交人工裁决；
  非 strict（收尾扫尾/attempt 间清理）记录跳过——防误杀他轨合法桌面。
- 孤儿（父进程已死）→ 点杀该 PID + 退出窗 + 复核；绝不
  ``Get-Process|Stop-Process -Force`` 无条件代杀（#265 族连坐他轨长求解）。

脚本侧一律委托本模块；杀进程原语单点存在于本文件，scripts/ 域禁止本地
复制（汇总静态钉 tests/unit/test_desktop_governance_static.py）。
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

RELEASE_DESKTOP_CAP_S = 150.0  # hfss_interdigital_check 口径：超时候实测阻塞 3.6h

LogFn = Callable[[str], None]


def list_ansysedt_processes() -> list[dict[str, Any]]:
    """枚举 ansysedt 进程（pid/ppid/命令行）；枚举失败抛错（fail-closed，
    #245：不核对命令行不杀）。"""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='ansysedt.exe'\" "
         "| ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|"
         "$($_.CommandLine)\" }"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"ansysedt 进程枚举失败 rc={r.returncode}（fail-closed，"
            f"#245 不盲杀）: {(r.stderr or '').strip()[:200]}")
    procs: list[dict[str, Any]] = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
            raise RuntimeError(
                "ansysedt 进程枚举输出不可解析（fail-closed，#245 不盲杀）: "
                f"{line[:120]}")
        procs.append({"pid": int(parts[0]), "ppid": int(parts[1]),
                      "cmdline": parts[2]})
    return procs


def process_alive(pid: int) -> bool:
    """进程存活判定；查询失败/输出不可解析抛错（fail-closed，按活桌面
    处理不杀——#245 杀前核对立规）。"""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"if (Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue) "
         "{'alive'} else {'dead'}"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"pid {pid} 存活查询失败（fail-closed，按活桌面处理不杀）: "
            f"{(r.stderr or '').strip()[:200]}")
    out = (r.stdout or "").strip().lower()
    if out not in ("alive", "dead"):
        raise RuntimeError(
            f"pid {pid} 存活查询输出不可解析（fail-closed，按活桌面处理"
            f"不杀）: {out[:120]}")
    return out == "alive"


def kill_orphan_ansysedt_desktops(
        *, log: LogFn = print, strict: bool = True,
        exit_wait_s: float = 3.0) -> None:
    """ansysedt 清场（#245/#265 合规）：只杀**父进程已死**的孤儿。

    strict=True（发射前/重试轮内，try 内承接）：活桌面与枚举/查询/终止
    失败一律 fail-closed 抛错不代杀，调用方决策（factory_mf 口径）。
    strict=False（attempt 间 try 外清理/收尾扫尾）：失败与活桌面只记录
    不抛——收尾清扫绝不连坐已完成战役（#105 best-effort）。
    旧实现 Get-Process|Stop-Process -Force 代杀全部 ansysedt——会误杀
    他轨合法桌面（#265 族长求解连坐），已废弃。
    """
    try:
        procs = list_ansysedt_processes()
    except Exception as exc:
        if strict:
            raise
        log(f"[desktop_guard][warn] ansysedt 枚举失败，本次不清理：{exc}")
        return
    if not procs:
        return
    orphans: list[dict[str, Any]] = []
    for p in procs:
        try:
            parent_alive = process_alive(p["ppid"])
        except Exception as exc:
            if strict:
                raise
            log(f"[desktop_guard][warn] pid={p['pid']} 父进程查询失败，"
                f"跳过不杀（按活桌面处理）：{exc}")
            continue
        if parent_alive:
            msg = (f"检测到活桌面 ansysedt pid={p['pid']}（父进程 "
                   f"{p['ppid']} 存活，cmdline={p['cmdline'][:120]}）——"
                   f"按 #245/#265 纪律不代杀，先人工核对命令行处置"
                   f"（防误杀他轨合法桌面）")
            if strict:
                raise RuntimeError(msg)
            log(f"[desktop_guard][warn] {msg}")
            continue
        orphans.append(p)

    killed: list[int] = []
    for p in orphans:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Stop-Process -Id {p['pid']} -Force"],
            capture_output=True, text=True)
        if r.returncode != 0:
            msg = (f"孤儿 ansysedt pid={p['pid']} 终止失败（fail-closed）: "
                   f"{(r.stderr or '').strip()[:200]}")
            if strict:
                raise RuntimeError(msg)
            log(f"[desktop_guard][warn] {msg}")
            continue
        killed.append(p["pid"])
        log(f"[desktop_guard] 已终止孤儿 ansysedt pid={p['pid']}（父进程 "
            f"{p['ppid']} 已死，cmdline={p['cmdline'][:80]}）")
    if not killed:
        return
    time.sleep(exit_wait_s)  # 退出窗，再复核后才允许开新会话
    try:
        procs_after = list_ansysedt_processes()
    except Exception as exc:
        # 复核枚举与首枚举同义务（round6 C-M1：瞬态失败不得穿透
        # strict=False 的"只记录不抛"契约；strict=True 仍 fail-closed 抛）。
        if strict:
            raise
        log(f"[desktop_guard][warn] 孤儿终止后复核枚举失败，本次无法确认 "
            f"清场（已杀 pid={killed}，留 #265/#245 人工核对）: {exc}")
        return
    leftover = [p for p in procs_after if p["pid"] in killed]
    if leftover:
        msg = (f"孤儿终止后仍有 {len(leftover)} 个 ansysedt（fail-closed "
               f"不开新会话）: {[p['pid'] for p in leftover]}")
        if strict:
            raise RuntimeError(msg)
        log(f"[desktop_guard][warn] {msg}")


def kill_ansysedt_by_ppid(ppid: int, *, log: LogFn = print) -> list[int]:
    """终止指定父进程（ppid）名下的 ansysedt 桌面（df6 HFSS 轨：脚本自身
    发射的桌面在失败轮泄漏时自清——parent 是本 python，可安全点杀，不涉
    他轨桌面；杀原语保持单源本文件）。

    返回已终止的 pid 列表；无匹配返回空。枚举/终止失败抛错（fail-closed）。
    """
    procs = list_ansysedt_processes()
    mine = [q for q in procs if q["ppid"] == ppid]
    killed: list[int] = []
    for q in mine:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Stop-Process -Id {q['pid']} -Force"],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                f"ansysedt pid={q['pid']} 终止失败: "
                f"{(r.stderr or '').strip()[:200]}")
        killed.append(q["pid"])
        log(f"[desktop_guard] 已终止本轨泄漏桌面 ansysedt pid={q['pid']} "
            f"(ppid={ppid})")
    if killed:
        time.sleep(3)
    return killed


def run_with_watchdog(fn: Callable[[], None], *, timeout_s: float,
                      what: str, log: LogFn = print) -> None:
    """fn 在守护线程执行并限时；超时抛 RuntimeError（fail-closed）。

    超时**不打断**执行线程（#145：只有真打断才判废，这里只不再等待，
    线程留守后台，桌面释放按 release_desktop_capped 上限处置）；
    fn 的异常原样透传，不冒充超时（hfss_interdigital_check 原型中
    done/err 合流把线程异常误报成超时——本实现分离两态）。
    """
    box: dict[str, Any] = {"done": False, "err": None}

    def _go() -> None:
        try:
            fn()
        except Exception as exc:  # 原样透传给调用方重试架
            box["err"] = exc
        finally:
            box["done"] = True

    th = threading.Thread(target=_go, daemon=True)
    th.start()
    th.join(timeout=timeout_s)
    if not box["done"]:
        raise RuntimeError(
            f"{what} 看门狗超时（>{timeout_s:.0f}s，fail-closed 不再等待；"
            f"桌面释放按 {RELEASE_DESKTOP_CAP_S:.0f}s 上限处置，孤儿风险"
            f"留 #265/#245 人工核对）")
    if box["err"] is not None:
        raise box["err"]


def release_desktop_capped(release_fn: Callable[[], None], *,
                           timeout_s: float = RELEASE_DESKTOP_CAP_S,
                           log: LogFn = print) -> bool:
    """release_desktop 带上限（hfss_interdigital_check 口径）：看门狗超时
    后 release 会对求解中的桌面阻塞到求解自然结束（attempt1 实测阻塞
    3.6h）——超时不候，如实记孤儿风险交人工按 #265/#245 处置。

    永不抛（finally best-effort，#105：观测/收尾不得成为主路径故障点）。
    返回 True=release 已返回，False=超时未返回。
    """
    box: dict[str, Any] = {"done": False}

    def _rel() -> None:
        try:
            release_fn()
        except Exception as exc:  # #265：释放失败必须透出
            log(f"[desktop_guard][warn] release_desktop 失败（孤儿 ansysedt "
                f"风险，#265）：{exc}")
        box["done"] = True

    th = threading.Thread(target=_rel, daemon=True)
    th.start()
    th.join(timeout=timeout_s)
    if not box["done"]:
        log(f"[desktop_guard][warn] release_desktop >{timeout_s:.0f}s 未返回"
            f"（桌面疑似仍在求解）——不再等待，孤儿 ansysedt 留待 #265/#245 "
            f"人工核对命令行后处置")
        return False
    return True
