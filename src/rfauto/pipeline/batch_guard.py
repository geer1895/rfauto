"""批处理（-BatchSolve）ansysedt 进程看门与守卫（batch 看门批，2026-10-08）。

背景：批处理模式下每次求解 spawn 独立 ``ansysedt -ng -BatchSolve`` 进程；
卡死进程会一直占许可席位（仓内实证：孤儿 ansysedt 曾占席位 5 小时，
#265）。本模块为 hfss_batch 席提供五类守卫 API：

- 进程枚举 / 孤儿发现：find_batch_processes / find_orphan_batch_processes；
- 命令行核对后点杀：kill_process_tree（#245 杀前核对命令行；#157 不用
  ``taskkill /T`` 防整树连坐 shim 嵌套的合法进程）；
- 许可证席位预检：assert_license_headroom（复用 infra.license_probe；
  缺省 fail-open——查不到=放行+warning，守卫绝不阻塞主路径，#105）；
- 发射前 RAM 预检：assert_ram_headroom（W10 批量战役事故形态守卫；
  psutil 优先 WMI 兜底；低于阈值=fail-skip（ok=False）由调用方延后
  发射，查不到=fail-open，#105）；
- 单次批求解看门：BatchSolveWatchdog（超时/存活探针；竞态完成接受真实
  结果，#145）。

分层：pipeline → infra（desktop_guard / license_probe 单源复用），不
import adapters / service（.importlinter layers 契约）。

纪律出处（任务书要求成文，勿删）：

- #245：杀前必须按命令行子串核对（先 Get-CimInstance 看命令行再动手）；
  枚举失败 / 进程不在表 / 核对不上一律**拒杀**返回 False（不盲杀）。
  交互式 git-bash 里 ``taskkill /PID`` 的 ``/PID`` 会被 MSYS 路径转换吃成
  ``C:/Program Files/Git/PID`` 静默不杀——须写 ``//PID``；本实现经
  Python subprocess 列表参数直达 powershell（不经 shell、无 MSYS 转换），
  并采用与 infra/desktop_guard 单源一致的 ``Stop-Process -Id`` 点杀形态。
- #157：``taskkill /T`` 会整树连坐 shim 嵌套的合法进程——本实现自枚举
  全表后按 ppid 收后代树、逐个核对命令行后**逐 pid 点杀**，不用 /T。
- #265：禁 ``Get-Process | Stop-Process -Force`` 管道无条件杀（误杀他轨
  合法桌面）——只点杀 ``-Id`` 参数化的明确 PID。
- E3-8：powershell 子进程一律带 timeout（枚举/存活/点杀上限对齐
  infra/desktop_guard 常量）；超时=未知态，按保守方向处置。
- W10：批解启动时物理内存可用率 ~10%（RAM 90% 占用）→ AEDT Com Engine
  non-responsive → 解无效 → 导出断链 → 连带 python 子进程 0xC0000142
  秒死（三件套判据）——assert_ram_headroom 发射前预检可用内存百分比；
  低于阈值=fail-skip（ok=False，调用方决定延后发射，守卫不原地等待），
  查询通道全挂=fail-open 放行+detail 注明（#105）。

注意：本模块**刻意不定义** ``__all__``——public_api 金快照按 ``__all__``
收录模块，新增登记属翻公开面评审动作（scripts/check_public_api.py 口径），
纯增量文件保持无 ``__all__`` 即不进快照。
"""

from __future__ import annotations

import logging
import math
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from typing import Any

from rfauto.infra import desktop_guard
from rfauto.infra.license_probe import probe_license

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据类型
# ---------------------------------------------------------------------------


@dataclass
class ProcessInfo:
    """一个批处理相关进程的枚举快照（pid/映像名/父 pid/完整命令行）。"""

    pid: int
    name: str = ""
    ppid: int | None = None
    cmdline: str | None = None


@dataclass
class GuardResult:
    """assert_license_headroom / assert_ram_headroom 共用的裁决结果。

    license 侧 ok=False 仅出现在"server 已配置且确认不可达"（继续发射
    必然在求解期失败的唯一硬信号）；RAM 侧 ok=False=可用内存已确证低于
    阈值（fail-skip：调用方决定延后发射）。其余一律 ok=True（fail-open），
    由 fail_open 标记"本次放行是因守卫无法确证"——调用方自行决定是否
    记录/等待（license 侧可配合 infra.license_probe.wait_for_license）。
    守卫本身永不抛、永不阻塞主路径（#105）。
    """

    ok: bool
    status: str  # license: reachable/no_server/unreachable/error;
    # ram: sufficient/insufficient/error
    fail_open: bool
    detail: str = ""
    min_free: int = 1
    elapsed_s: float = 0.0


@dataclass
class WatchResult:
    """BatchSolveWatchdog.watch 的结果。

    killed 的语义=「本守卫是否执行了击杀且根进程确认终止」；timed_out=
    True 且 killed=False 时须看 detail（可能是核对失败拒杀 / 进程已自行
    退出 / 枚举失败不盲杀）。
    """

    timed_out: bool
    killed: bool
    returncode: int | None = None
    elapsed_s: float = 0.0
    detail: str = ""
    killed_pids: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 进程枚举（形态对齐 infra/desktop_guard 单源：pid|ppid|name|cmdline 管道行）
# ---------------------------------------------------------------------------

# 伪 WQL LIKE 注入面：pattern 是开发者常量（"ansysedt"），引号直接剥掉，
# %/_ 按 WQL 通配符原样透传（文档化行为，不在此转义）。
def _sanitize_pattern(pattern: str) -> str:
    return pattern.replace("'", "").replace('"', "").strip() or "ansysedt"


def _enumerate(pattern: str | None) -> list[ProcessInfo]:
    """枚举进程（pattern=None 全表；否则按映像名 LIKE 过滤）。

    fail-closed：超时 / rc!=0 / 输出不可解析一律抛 RuntimeError（#245
    不核对命令行不杀——调用方 catch 后按"未知态"保守处置）。单行格式
    ``pid|ppid|name|cmdline``（maxsplit 保 cmdline 内的管道符）。
    """
    if pattern:
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name LIKE "
            f"'%{_sanitize_pattern(pattern)}%'\" | ForEach-Object {{ "
            "\"$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)|"
            "$($_.CommandLine)\" }"
        )
    else:
        script = (
            "Get-CimInstance Win32_Process | ForEach-Object { "
            "\"$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)|"
            "$($_.CommandLine)\" }"
        )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=desktop_guard.ENUM_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"批处理进程枚举超时（>{desktop_guard.ENUM_TIMEOUT_S:.0f}s，"
            f"fail-closed 不盲杀，E3-8）: {exc}") from exc
    if r.returncode != 0:
        raise RuntimeError(
            f"批处理进程枚举失败 rc={r.returncode}（fail-closed，#245 不盲杀）: "
            f"{(r.stderr or '').strip()[:200]}")
    procs: list[ProcessInfo] = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) != 4 or not parts[0].isdigit() or not parts[1].isdigit():
            raise RuntimeError(
                "批处理进程枚举输出不可解析（fail-closed，#245 不盲杀）: "
                f"{line[:120]}")
        procs.append(ProcessInfo(
            pid=int(parts[0]), name=parts[2], ppid=int(parts[1]),
            cmdline=parts[3] or None))
    return procs


def find_batch_processes(pattern: str = "ansysedt") -> list[ProcessInfo]:
    """枚举映像名含 pattern 的批处理进程（大小写不敏感，双端过滤）。

    WQL LIKE 预过滤 + Python 端复核（两层一致，测试 fake 也走同一过滤
    语义）。枚举失败抛 RuntimeError（fail-closed，#245）——调用方按未知
    态处置，勿当空列表吞掉。
    """
    procs = _enumerate(pattern)
    pat = pattern.lower()
    return [p for p in procs if pat in (p.name or "").lower()]


def find_orphan_batch_processes(pattern: str = "ansysedt") -> list[ProcessInfo]:
    """发现孤儿批处理进程（父进程已死仍在占许可席位，#265 痛点）。

    全表一枚举 + ppid 集合成员判定（比逐 pid 存活探针省 N-1 次 PS spawn；
    快照语义下误判方向安全：活父必在表内，不会误判成孤）。ppid 未知
    （解析缺失）保守不判孤；ppid==0 视为孤。pid 复用使死父的 pid 恰被
    新进程顶替时→漏判成非孤（方向安全：不杀）。判定纪律对齐
    infra/desktop_guard.kill_orphan_ansysedt_desktops（只动孤儿，活桌面
    绝不代杀）；击杀由调用方经 kill_process_tree 核对命令行后执行。
    """
    table = _enumerate(None)
    live_pids = {p.pid for p in table}
    pat = pattern.lower()
    orphans: list[ProcessInfo] = []
    for p in table:
        if pat not in (p.name or "").lower():
            continue
        if p.ppid is None:
            logger.warning(
                "孤儿判定：pid=%s ppid 未知，保守不判孤（E3-8 未知态）", p.pid)
            continue
        if p.ppid == 0 or p.ppid not in live_pids:
            orphans.append(p)
    return orphans


# ---------------------------------------------------------------------------
# 点杀原语（形态对齐 infra/desktop_guard：Stop-Process -Id 参数化 PID）
# ---------------------------------------------------------------------------


def _stop_pid(pid: int) -> bool:
    """点杀单 pid（Stop-Process -Id -Force，带 E3-8 上限）。

    True=命令成功；False=失败或超时（超时=未知态，不冒充结果）。
    """
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Stop-Process -Id {int(pid)} -Force"],
            capture_output=True, text=True, timeout=desktop_guard.KILL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        logger.error("点杀 pid=%s 超时（>%s，E3-8 未知态）", pid,
                     desktop_guard.KILL_TIMEOUT_S)
        return False
    if r.returncode != 0:
        logger.warning("点杀 pid=%s 失败 rc=%s: %s", pid, r.returncode,
                       (r.stderr or "").strip()[:200])
    return r.returncode == 0


def _cmdline_verified(info: ProcessInfo | None, token: str) -> bool:
    """#245 命令行子串核对（大小写不敏感，normcase 纪律显式 .lower()）。"""
    if info is None:
        return False
    return token.lower() in (info.cmdline or "").lower()


def kill_process_tree(pid: int, verify_cmdline_substr: str | None = None) -> bool:
    """核对命令行后点杀 pid 及其后代树（先叶后根）。

    安全纪律（返回 False 的全部情形，均**未发生击杀**或仅部分后代被跳过）：

    - 全表枚举失败 → 拒杀（#245 不盲杀）；
    - pid 不在 fresh 全表 → 目标已退出（席位已释放），无需杀；
    - verify_cmdline_substr 给定且目标/后代 cmdline 不含该子串 → 跳过
      （#157：防 pid 回收误杀 / shim 嵌套连坐；后代不匹配逐个跳过）。

    返回 True=根进程已终止（点杀成功，或点杀失败但复核确认已退出）。
    verify_cmdline_substr 传 None 表示调用方已凭他证（如 Popen.pid 归属）
    确立目标身份——仍会做"在 fresh 表中存在"核对。
    """
    pid = int(pid)
    if pid <= 0:
        return False
    try:
        table = _enumerate(None)
    except Exception as exc:
        logger.error("kill_process_tree: 枚举失败，拒杀（#245）: %s", exc)
        return False
    by_pid = {p.pid: p for p in table}
    target = by_pid.get(pid)
    if target is None:
        logger.warning(
            "kill_process_tree: pid=%s 不在进程表（已退出/被回收），未击杀",
            pid)
        return False
    token = (verify_cmdline_substr or "").strip() or None
    if token is not None and not _cmdline_verified(target, token):
        logger.error(
            "kill_process_tree: pid=%s cmdline 核对失败（token=%r 不在 "
            "cmdline=%r）——拒杀（#245 不盲杀）", pid, token, (target.cmdline or "")[:160])
        return False

    # 后代树：ppid 邻接 BFS（快照语义，与孤儿判定同一份表）
    children: dict[int, list[ProcessInfo]] = defaultdict(list)
    for p in table:
        if p.ppid is not None and p.pid != pid:
            children[p.ppid].append(p)
    descendants: list[ProcessInfo] = []
    stack = [pid]
    seen: set[int] = {pid}
    while stack:
        cur = stack.pop()
        for c in children.get(cur, ()):
            if c.pid in seen:
                continue
            seen.add(c.pid)
            descendants.append(c)
            stack.append(c.pid)

    killed_pids: list[int] = []
    for d in reversed(descendants):  # 先叶后根
        if token is not None and not _cmdline_verified(d, token):
            logger.warning(
                "kill_process_tree: 后代 pid=%s cmdline 不含核对串，跳过"
                "（防连坐 #157/#265）", d.pid)
            continue
        if _stop_pid(d.pid):
            killed_pids.append(d.pid)
            logger.info("kill_process_tree: 已终止后代 pid=%s (%s)", d.pid,
                        (d.cmdline or "")[:80])
    root_killed = _stop_pid(pid)
    if root_killed:
        killed_pids.append(pid)
        logger.info("kill_process_tree: 已终止根 pid=%s (%s)", pid,
                    (target.cmdline or "")[:80])
    else:
        try:
            alive = desktop_guard.process_alive(pid)
        except Exception as exc:
            logger.warning("kill_process_tree: pid=%s 存活复核失败: %s", pid, exc)
            alive = None
        if alive is False:
            # 已退出（自然结束或已被杀）——席位已释放，按成功口径
            root_killed = True
            logger.info("kill_process_tree: pid=%s 点杀失败但复核已退出", pid)
    if killed_pids:
        logger.info("kill_process_tree: 共终止 %s", killed_pids)
    return root_killed


# ---------------------------------------------------------------------------
# 许可证席位预检（复用 infra.license_probe 单源；缺省 fail-open #105）
# ---------------------------------------------------------------------------


def assert_license_headroom(min_free: int = 1) -> GuardResult:
    """发射批求解前的许可证席位预检。

    席位计数本仓无查询面（infra.license_probe 只有 server TCP 可达性），
    故席位维度恒为"无法确证"：server 可达/未配置/探测异常 → 一律
    fail-open 放行并记录（#105：守卫绝不阻塞主路径；min_free 记录进结果
    供未来席位计数面接入时启用）。唯一硬信号=server 已配置且确认不可达
    （ok=False，fail_open=False）——此时继续发射必然在求解期失败，调用方
    可据此跳过/转 wait_for_license。
    """
    t0 = time.monotonic()
    try:
        probe = probe_license()
    except Exception as exc:  # probe 异常也绝不进主路径（#105 双保险）
        logger.warning("assert_license_headroom: license 探测异常，fail-open: %s", exc)
        return GuardResult(ok=True, status="error", fail_open=True,
                           detail=f"license probe raised ({exc}); fail-open per #105",
                           min_free=min_free, elapsed_s=time.monotonic() - t0)
    server = probe.get("server")
    detail = str(probe.get("detail", ""))
    if not server:
        logger.warning(
            "assert_license_headroom: 无 license server 配置（本机/节点锁"
            "假设），fail-open 放行，席位余量未确证 (min_free=%s)", min_free)
        return GuardResult(ok=True, status="no_server", fail_open=True,
                           detail=detail or "no license server configured; "
                           "assuming local/node-locked license",
                           min_free=min_free, elapsed_s=time.monotonic() - t0)
    if probe.get("available"):
        logger.warning(
            "assert_license_headroom: license server %s 可达但席位计数不可查"
            "（仓内无席位查询面），fail-open 放行 (min_free=%s)", server, min_free)
        return GuardResult(ok=True, status="reachable", fail_open=True,
                           detail=f"{detail}; seat count not queryable via "
                           f"infra.license_probe, headroom unverifiable",
                           min_free=min_free, elapsed_s=time.monotonic() - t0)
    logger.error(
        "assert_license_headroom: license server %s 确认不可达（%s）——"
        "ok=False（继续发射必然求解期失败；可转 infra.license_probe."
        "wait_for_license 等待）", server, detail)
    return GuardResult(ok=False, status="unreachable", fail_open=False,
                       detail=detail, min_free=min_free,
                       elapsed_s=time.monotonic() - t0)


# ---------------------------------------------------------------------------
# 发射前 RAM 预检（W10 批量战役事故形态；psutil 优先、WMI 兜底、fail-open）
# ---------------------------------------------------------------------------


def _query_free_ram_pct_psutil() -> float | None:
    """psutil 通道：物理内存可用百分比（available/total*100）。

    psutil 惰性导入（非硬依赖，对齐 adapters/hfss_batch 的兜底口径）；
    导入失败 / 查询异常 / total<=0 一律返回 None（fail-open 由调用方
    处置，通道自身绝不抛）。
    """
    try:
        import psutil
    except ImportError:
        return None
    try:
        vm = psutil.virtual_memory()
    except Exception:
        return None
    total = float(vm.total)
    if total <= 0.0:
        return None
    return 100.0 * float(vm.available) / total


def _query_free_ram_pct_wmi() -> float | None:
    """WMI 兜底通道：Win32_OperatingSystem 物理内存可用百分比。

    FreePhysicalMemory/TotalVisibleMemorySize 单位均为 KiB（WMI 文档
    口径）；查询/解析任何环节失败一律返回 None（E3-8：powershell 子
    进程带 timeout，超时=未知态=不确证）。
    """
    script = (
        "Get-CimInstance Win32_OperatingSystem | ForEach-Object { "
        "\"$($_.TotalVisibleMemorySize)|$($_.FreePhysicalMemory)\" }"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True,
            timeout=desktop_guard.ENUM_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    if len(lines) != 1:
        return None
    parts = lines[0].split("|")
    if len(parts) != 2:
        return None
    try:
        total_kib = float(parts[0])
        free_kib = float(parts[1])
    except ValueError:
        return None
    if total_kib <= 0.0:
        return None
    return 100.0 * free_kib / total_kib


def _query_free_ram_pct() -> tuple[float | None, str]:
    """双通道顺序查询：psutil 优先、WMI 兜底；永不抛（异常折入原因串）。

    返回 ``(pct, channel)``：查到时 pct 非 None、channel="psutil"/"wmi"；
    两通道皆不可用时 pct=None、channel 注明逐通道原因（进 GuardResult
    detail 供 fail-open 留痕）。
    """
    reasons: list[str] = []
    for name, query in (("psutil", _query_free_ram_pct_psutil), ("wmi", _query_free_ram_pct_wmi)):
        try:
            pct = query()
        except Exception as exc:  # 防御：通道实现变更也不许炸守卫（#105）
            reasons.append(f"{name} raised ({exc})")
            continue
        if pct is not None:
            return pct, name
        reasons.append(f"{name} unavailable")
    return None, "; ".join(reasons)


def assert_ram_headroom(min_free_pct: float = 15.0) -> GuardResult:
    """发射批量战役（批解启动）前的 RAM 余量预检。

    背景（W10 批量战役实证新事故形态，三件套判据）：批解启动时物理内存
    可用率 ~10% → AEDT Com Engine non-responsive → 解无效 → 导出断链 →
    连带 python 子进程 0xC0000142 秒死。本守卫在发射前查可用内存百分比：

    - pct < min_free_pct → ok=False（fail-skip：已确证的不足是硬信号，
      调用方据此延后发射/转等待，守卫不原地 sleep/重试）；
    - 查询通道全挂 → ok=True + fail_open=True（fail-open 放行，detail
      注明原因，#105：守卫绝不阻塞主路径）；
    - pct >= min_free_pct → ok=True（fail_open=False，已确证充足；恰
      等于阈值=达标放行，严格小于才拦）。

    口径=物理内存 available 比例（含 standby 可回收页，psutil available
    语义 / WMI FreePhysicalMemory 同族），非 committed/虚拟内存——事故
    形态是整机物理内存挤压。阈值缺省 15%。

    阈值须为有限数：NaN/±inf 使比较失去"已确证"语义（NaN 侧
    ``pct < threshold`` 恒 False 会产出**假的 confirmed sufficient**），
    非有限阈值按"无法确证"走 fail-open（ok=True + fail_open=True +
    status="error"，#105 守卫不抛不阻塞）；有限越界值（负数/>100）比较
    语义仍良定义（恒放行/恒 fail-skip），detail 回显阈值自说明，不在此
    二次仲裁。
    """
    t0 = time.monotonic()
    threshold = float(min_free_pct)
    if not math.isfinite(threshold):
        logger.warning(
            "assert_ram_headroom: 阈值非有限（%r）——比较无法确证，fail-open "
            "放行（#105；NaN 会产出假 confirmed sufficient，故显式按 "
            "error/fail_open 落痕）", min_free_pct)
        return GuardResult(
            ok=True,
            status="error",
            fail_open=True,
            detail=(f"min_free_pct non-finite ({min_free_pct!r}); threshold "
                    "comparison unverifiable; fail-open per #105"),
            elapsed_s=time.monotonic() - t0,
        )
    pct, channel = _query_free_ram_pct()
    elapsed = time.monotonic() - t0
    if pct is None:
        logger.warning(
            "assert_ram_headroom: 可用内存不可查（%s），fail-open 放行 (min_free_pct=%s，#105)", channel, min_free_pct
        )
        return GuardResult(
            ok=True,
            status="error",
            fail_open=True,
            detail=(f"ram headroom unverifiable ({channel}); fail-open per #105"),
            elapsed_s=elapsed,
        )
    if pct < min_free_pct:
        logger.error(
            "assert_ram_headroom: 可用内存 %.2f%% < 阈值 %s%%——ok=False"
            "（fail-skip），调用方延后发射（W10 事故形态：RAM 挤压→Com "
            "Engine non-responsive→解无效→导出断链→0xC0000142）",
            pct,
            min_free_pct,
        )
        return GuardResult(
            ok=False,
            status="insufficient",
            fail_open=False,
            detail=(f"free ram {pct:.2f}% < min_free_pct {float(min_free_pct):.2f}% (channel={channel}); defer launch"),
            elapsed_s=elapsed,
        )
    logger.info("assert_ram_headroom: 可用内存 %.2f%% >= 阈值 %s%%（%s 通道）——放行", pct, min_free_pct, channel)
    return GuardResult(
        ok=True,
        status="sufficient",
        fail_open=False,
        detail=(f"free ram {pct:.2f}% >= min_free_pct {float(min_free_pct):.2f}% (channel={channel})"),
        elapsed_s=elapsed,
    )


# ---------------------------------------------------------------------------
# 单次批求解看门（超时/存活探针；#145 竞态完成接受真实结果）
# ---------------------------------------------------------------------------


def _verify_token_from_handle(process_handle: Any) -> str | None:
    """从 Popen 风格句柄提取 #245 核对串（args[0] 的映像名，小写）。

    取不到（简易 fake 句柄 / args 形态未知）返回 None——watch 会记 warning
    并按 None（不核对子串、仅核对新表存在性）降级击杀；Popen 句柄恒有
    .args，生产路径不受影响。
    """
    args = getattr(process_handle, "args", None)
    first: Any = None
    if isinstance(args, (list, tuple)) and args:
        first = args[0]
    elif isinstance(args, str) and args.strip():
        first = args.strip().split(" ", 1)[0].strip('"')
    if isinstance(first, str) and first.strip():
        return PureWindowsPath(first.strip()).name.lower() or None
    return None


class BatchSolveWatchdog:
    """包装单次批处理求解进程（Popen 风句柄）的超时/存活看门。

    用法（hfss_batch 席消费形态）::

        proc = subprocess.Popen(["ansysedt", "-ng", "-BatchSolve", ...])
        wd = BatchSolveWatchdog(timeout_s=21600, poll_interval_s=30.0)
        result = wd.watch(proc, on_timeout="kill")

    语义：
    - 每轮**先探完成、后判超时**——deadline 附近竞态完成接受真实结果
      （#145：watchdog 超时只在真打断时判废）；
    - on_timeout="kill"：经 kill_process_tree 做 #245 命令行核对后点杀
      （核对串自动取 handle.args[0] 映像名）；
    - on_timeout="record"：只记录不杀（调用方自持清理）。
    """

    def __init__(self, timeout_s: float, poll_interval_s: float = 30.0) -> None:
        if timeout_s <= 0:
            raise ValueError(f"timeout_s 必须 >0，收到 {timeout_s!r}")
        if poll_interval_s <= 0:
            raise ValueError(f"poll_interval_s 必须 >0，收到 {poll_interval_s!r}")
        self.timeout_s = float(timeout_s)
        self.poll_interval_s = float(poll_interval_s)

    def watch(self, process_handle: Any, on_timeout: str = "kill") -> WatchResult:
        """轮询 process_handle.poll() 直到返回码出现或超时。

        process_handle：鸭子类型 Popen——需 .poll() -> int|None 与 .pid；
        可选 .args（list/str）用于 #245 核对串提取。
        """
        if on_timeout not in ("kill", "record"):
            raise ValueError(
                f"on_timeout 只支持 'kill'/'record'，收到 {on_timeout!r}")
        t0 = time.monotonic()
        while True:
            rc = process_handle.poll()
            elapsed = time.monotonic() - t0
            if rc is not None:
                # 完成优先于超时判定（#145 竞态完成接受真实结果）
                return WatchResult(
                    timed_out=False, killed=False, returncode=int(rc),
                    elapsed_s=elapsed, detail="completed normally")
            if elapsed >= self.timeout_s:
                if on_timeout == "record":
                    logger.warning(
                        "BatchSolveWatchdog: pid=%s 超时（>%.0fs），仅记录"
                        "不杀（on_timeout=record）", process_handle.pid, elapsed)
                    return WatchResult(
                        timed_out=True, killed=False, returncode=None,
                        elapsed_s=elapsed,
                        detail="timeout recorded; no kill (caller owns cleanup)")
                token = _verify_token_from_handle(process_handle)
                if token is None:
                    logger.warning(
                        "BatchSolveWatchdog: pid=%s 无法从 handle.args 提取"
                        "核对串，降级为仅存在性核对击杀", process_handle.pid)
                killed = kill_process_tree(
                    process_handle.pid, verify_cmdline_substr=token)
                detail = ("timeout; kill_process_tree ok" if killed else
                          "timeout; kill refused or target already gone "
                          "(see logs; #245/#157)")
                logger.warning(
                    "BatchSolveWatchdog: pid=%s 超时（>%.0fs），击杀 %s",
                    process_handle.pid, elapsed, "成功" if killed else "未执行")
                return WatchResult(
                    timed_out=True, killed=killed, returncode=None,
                    elapsed_s=elapsed, detail=detail)
            time.sleep(min(self.poll_interval_s, self.timeout_s - elapsed))
