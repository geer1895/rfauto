"""内存守望战役启动器（阶段 1.3 patch 战役的纪律化发射）。

铁律背景：真机求解内存门槛自查（仓内纪律；calibration_campaign.py 内置
--min-free-kb 门）。本启动器在内存不足时不压门槛，而是周期探测、
门开即射：
- 默认目标 workers=2（需 4GB+1.5GB/worker ≈ 5.5GB 可用）；
- --fallback-hours 后（默认 6h）降级为串行门（4GB）；
- --max-wait-hours（默认 24h）超时未达标则退出（exit 2），交还人。
门开后直接 exec calibration_campaign.py（其内部自带同款门，双保险）。

守望者纪律（#177/#360 族）：
- 自身心跳：每个探测周期原子写心跳文件（缺省 runs/.wait_launch_heartbeat.json：
  pid/start_ts/last_poll_ts/门状态/已等时长），供新会话清点"无主守望进程"
  （#177：守望进程随会话死；消费面=按 pid 存活 + last_poll_ts 新鲜度判归属）；
- 心跳自尽：心跳写连续失败 --heartbeat-max-write-failures 次（默认 3）
  → exit 3 不发射（观测面故障不得转为无人监督发射，#105 不阻塞业务在此
  反向成立：业务发射不能没有观测面背书）；
- 父会话心跳：--parent-heartbeat <path> 提供时，父会话应周期 touch 该文件；
  launcher 发现超时（--parent-heartbeat-timeout-s，默认 900s）→ exit 4 不发射
  ——防"会话死了守望者半夜无人监督发射"。文件尚未出现以 launcher 启动时刻
  为基准计时（父会话死了从未 touch 同样会超时，不会永久空等）；
- 单实例守卫：启动时发现其他活跃 launcher 心跳（last_poll_ts 距今
  < 2×轮询周期——取新 launcher 与心跳自报 poll_s 的较大者——且 pid 存活）
  → exit 5 拒绝启动，防双发；过期/死 pid 心跳是无主遗痕（#177 清点面），
  不阻塞新实例。

退出码：0=子进程码透传（发射并跑完）；2=内存门超时；3=心跳写连续失败；
4=父会话心跳超时；5=检测到活跃同实例拒绝双发。

用法：
  .venv\\Scripts\\python.exe scripts\\campaign_wait_launch.py ^
      --recipe recipes/patch_antenna_v1.yaml --mesh 0 --n-new 16
  # 无人监督防半夜发射（父会话每轮询周期 touch 父心跳文件，如 PowerShell：
  # (Get-Item runs\\.wait_launch_parent.touch).LastWriteTime = Get-Date）：
  .venv\\Scripts\\python.exe scripts\\campaign_wait_launch.py ^
      --recipe ... --parent-heartbeat runs\\.wait_launch_parent.touch
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE_GATE_KB = 4 * 1024 * 1024
PER_WORKER_KB = 1500 * 1024
HEARTBEAT_PATH_DEFAULT = REPO / "runs" / ".wait_launch_heartbeat.json"


def _parse_free_kb(out: str) -> int:
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("FreePhysicalMemory="):
            return int(line.split("=", 1)[1].strip())
        if line.isdigit():
            return int(line)
    return 0


def free_physical_memory_kb() -> int:
    # wmic 在 Win11 24H2+ 已移除，回退 PowerShell CIM（#182）
    for cmd in (
        ["wmic", "OS", "get", "FreePhysicalMemory", "/Value"],
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
    ):
        try:
            kb = _parse_free_kb(subprocess.check_output(
                cmd, text=True, stderr=subprocess.DEVNULL))
        except (OSError, subprocess.CalledProcessError):
            continue
        if kb:
            return kb
    return 0


def pid_alive(pid: object) -> bool:
    """跨平台进程存活探测（零副作用）：Windows 走 kernel32
    OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)+GetExitCodeProcess，
    POSIX 走 os.kill(pid, 0)。pid 无效/不存在 → False；
    存在但无权查询（POSIX PermissionError）→ True。"""
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
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, pid_i)
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


def write_heartbeat(path: str | os.PathLike[str], payload: dict) -> bool:
    """原子写心跳：同目录临时文件 json.dump → os.replace。任何 OSError
    都不抛（观测面 best-effort，#105），返回 True/False 供调用方计连续失败。"""
    p = Path(path)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, p)
        return True
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return False


def read_heartbeat(path: str | os.PathLike[str]) -> dict | None:
    """读心跳 JSON；缺失/损坏 → None（损坏视为无主，不构成单实例阻塞）。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _num(v: object) -> float | None:
    """数值守卫：bool 不是数（isinstance(True, int) 陷阱）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def heartbeat_stale(hb: object, now: float, max_age_s: float) -> bool:
    """True=心跳缺失/非 dict/last_poll_ts 缺失或非数/距今超龄 → 无主。"""
    if not isinstance(hb, dict):
        return True
    ts = _num(hb.get("last_poll_ts"))
    if ts is None:
        return True
    return (now - ts) > max_age_s


def single_instance_conflict(
    hb: object, now: float, poll_s: float,
) -> tuple[bool, str]:
    """单实例判定（纯函数）：其他活跃 launcher 心跳（last_poll_ts 距今
    < 2×轮询周期——取本实例与心跳自报 poll_s 较大者——且 pid 存活）
    → (True, 原因)；否则 (False, "")。"""
    if not isinstance(hb, dict):
        return False, ""
    hb_poll = _num(hb.get("poll_s")) or 0.0
    window_s = 2.0 * max(_num(poll_s) or 0.0, hb_poll)
    if heartbeat_stale(hb, now, window_s):
        return False, ""
    if not pid_alive(hb.get("pid")):
        return False, ""
    return True, (f"活跃 launcher pid={hb.get('pid')} "
                  f"last_poll_ts={hb.get('last_poll_ts')}")


def heartbeat_self_terminate(failures: int, max_failures: int) -> bool:
    """心跳写连续失败自尽判定：failures ≥ max_failures → True。
    max_failures<=0 视为关闭（永不因心跳自尽）。"""
    return max_failures > 0 and failures >= max_failures


def parent_heartbeat_timed_out(
    path: str | os.PathLike[str], now: float, timeout_s: float,
    start_ts: float,
) -> bool:
    """父会话心跳超时判定（纯函数）：文件 mtime 距今 > timeout_s → True；
    文件尚未出现以 launcher 启动时刻 start_ts 为基准（父死了从未 touch
    同样超时）。mtime 读取失败按"以 start_ts 计"同口径处理——宁可误退
    重来，不无人监督盲发。"""
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        mtime = start_ts
    return (now - mtime) > timeout_s


def main() -> int:
    ap = argparse.ArgumentParser(description="内存门开后发射校准战役")
    ap.add_argument("--recipe", default="recipes/patch_antenna_v1.yaml")
    ap.add_argument("--mesh", type=float, default=0.0)
    ap.add_argument("--n-new", type=int, default=16)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--poll-s", type=int, default=600)
    ap.add_argument("--fallback-hours", type=float, default=6.0)
    ap.add_argument("--max-wait-hours", type=float, default=24.0)
    ap.add_argument("--heartbeat", default=str(HEARTBEAT_PATH_DEFAULT),
                    help="自身心跳文件（缺省 runs/.wait_launch_heartbeat.json；"
                         "传空串关闭心跳写入）")
    ap.add_argument("--heartbeat-max-write-failures", type=int, default=3,
                    help="心跳连续写失败自尽阈值（exit 3；0=关闭该路自尽）")
    ap.add_argument("--parent-heartbeat", default=None,
                    help="父会话心跳文件（父会话周期 touch；超时 exit 4 不发射）")
    ap.add_argument("--parent-heartbeat-timeout-s", type=float, default=900.0,
                    help="父会话心跳超时秒数（缺省 900）")
    args = ap.parse_args()

    # 单实例守卫（exit 5，防双发）：只拦"活跃"心跳（新鲜 + pid 存活）；
    # 过期/死 pid 心跳是无主遗痕（#177 清点消费面），不阻塞新实例。
    now = time.time()
    conflict, reason = single_instance_conflict(
        read_heartbeat(args.heartbeat), now, args.poll_s)
    if conflict:
        print(f"ALREADY_RUNNING: {reason}——拒绝双发（exit 5）", flush=True)
        return 5

    started = time.time()
    hb_failures = 0
    while True:
        now = time.time()
        waited_h = (now - started) / 3600.0
        if waited_h >= args.max_wait_hours:
            print(f"WAIT_TIMEOUT: {waited_h:.1f}h 未达内存门——交还人",
                  flush=True)
            return 2
        workers = args.workers
        need = BASE_GATE_KB + (workers - 1) * PER_WORKER_KB
        free = free_physical_memory_kb()
        if free < need and waited_h >= args.fallback_hours and args.workers > 1:
            workers = 1
            need = BASE_GATE_KB
        gate_open = free >= need
        # 自身心跳（先写后决策：发射/自尽/父亡三路的证据都在心跳里）
        if args.heartbeat:
            payload = {
                "pid": os.getpid(),
                "start_ts": started,
                "last_poll_ts": now,
                "waited_h": round(waited_h, 4),
                "poll_s": args.poll_s,
                "gate": {"free_kb": free, "need_kb": need,
                         "workers": workers, "open": gate_open},
                "parent_heartbeat": args.parent_heartbeat or "",
            }
            if write_heartbeat(args.heartbeat, payload):
                hb_failures = 0
            else:
                hb_failures += 1
                print(f"HEARTBEAT_WRITE_FAIL: 连续 {hb_failures} 次"
                      f"（阈值 {args.heartbeat_max_write_failures}）", flush=True)
                if heartbeat_self_terminate(
                        hb_failures, args.heartbeat_max_write_failures):
                    print("HEARTBEAT_SELF_TERMINATE: 心跳写连续失败——"
                          "自尽退出不发射（exit 3）", flush=True)
                    return 3
        # 父会话心跳超时 → 自尽不发射（先于发射决策：门开也不许盲发）
        if args.parent_heartbeat and parent_heartbeat_timed_out(
                args.parent_heartbeat, now,
                args.parent_heartbeat_timeout_s, started):
            print(f"PARENT_HEARTBEAT_TIMEOUT: 父心跳超时 "
                  f">{args.parent_heartbeat_timeout_s}s——自尽退出不发射"
                  "（exit 4）", flush=True)
            return 4
        if gate_open:
            print(f"LAUNCH: 可用 {free / 1e6:.2f}GB ≥ 门 "
                  f"{need / 1e6:.2f}GB，workers={workers}，"
                  f"等待 {waited_h:.1f}h 后发射", flush=True)
            cmd = [str(REPO / ".venv" / "Scripts" / "python.exe"),
                   str(REPO / "scripts" / "calibration_campaign.py"),
                   "--recipe", args.recipe, "--mesh", str(args.mesh),
                   "--n-new", str(args.n_new), "--n-workers", str(workers)]
            return subprocess.call(cmd)
        print(f"[wait {waited_h:.1f}h] 可用 {free / 1e6:.2f}GB < "
              f"{need / 1e6:.2f}GB（workers={workers}）——"
              f"{args.poll_s}s 后复测", flush=True)
        time.sleep(args.poll_s)


if __name__ == "__main__":
    sys.exit(main())
