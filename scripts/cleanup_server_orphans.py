"""服务器侧 rfauto 孤儿清理（ge8d 固化：用户 2026-10-03 反馈僵尸进程侵占 CPU）。

清理范围（白名单点杀，非通配兜底）：
1. 清点：ansysedt.exe 全量 + 命令行含 rfauto_remote 的 python.exe（含 PPID）；
2. ansysedt/python 孤儿：命令行含本仓任务指纹（blslope/dk78r/oe_ 任务目录/
   wheeler/hfss_side_remote）**且父进程已死**的实例；
3. 端口终态复核：收尾打印 50051（HFSS gRPC）监听状态。

E3-1（ge8e 审查批 F4 修复）要点：
- **孤儿判定落实**：原实现采集了 PPID 却从不核对（注释声称"父已死才算
  孤儿"），命中指纹即 taskkill——父存活的合法桌面同样被杀。现命中指纹后
  逐个查父进程存活（Win32_Process ParentProcessId → Get-Process -Id 存在
  性）：父死才进点杀名单；父存活=跳过留痕"父存活在飞"；查询失败=按存活
  保守处理（fail-safe 不杀，#245 杀前核对/#265 不代杀同纪律）。
- **在飞白名单去硬编码**：原 oe_1a417ed4 写死在代码里，批次轮换必腐烂。
  现从机器登记 configs/remote_machines*.yaml 的 ``orphan_whitelist`` 键
  （机器条目级，落入 RemoteMachineConfig.extra）和/或命令行
  ``--whitelist TOKEN``（可多次）读取；缺省空=无白名单。在飞批次必须
  显式声明（K 队列登记的批次号）。
- **--explain**：打印每行判定链（白名单/指纹/父存活 → 处置）。

用法：
  python cleanup_server_orphans.py --dry-run   # 只清点报告
  python cleanup_server_orphans.py --kill      # 点杀命中项（父已死孤儿）
  python cleanup_server_orphans.py --kill --whitelist oe_1a417ed4 --explain
纪律：#261 候跑不代杀——K 队列登记的在飞任务（K-7 终跑等）绝不清理，
  经 --whitelist 或登记文件 orphan_whitelist 声明在飞批次；
每席真机任务退出后应执行本脚本（RUNBOOK 收尾段固化）。
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from rfauto.infra.remote_machines import (  # noqa: E402
    RemoteMachineConfig,
    SshTransport,
    load_remote_machines,
    resolve_machine,
)

ORPHAN_FINGERPRINT = re.compile(
    r"blslope|dk78r|hfss_side_remote|tasks\\oe_|tasks/oe_|wheeler", re.I)

CENSUS_TIMEOUT_S = 90
PARENT_PROBE_TIMEOUT_S = 30
KILL_TIMEOUT_S = 60

CENSUS_CMD = (
    'powershell -NoProfile -Command "Get-CimInstance Win32_Process | '
    'Where-Object { $_.Name -eq \'ansysedt.exe\' -or '
    '($_.Name -eq \'python.exe\' -and $_.CommandLine -match \'rfauto_remote\') } | '
    'ForEach-Object { \'PID=\' + $_.ProcessId + \' NAME=\' + $_.Name + '
    '\' PPID=\' + $_.ParentProcessId + \' CMD=\' + $_.CommandLine }"'
)


@dataclass
class CensusRow:
    """清点单行（pid/ppid/name/cmdline + 原始行留痕）。"""

    pid: int
    ppid: int
    name: str
    cmdline: str
    raw: str


def parse_census_rows(out: str | None) -> list[CensusRow]:
    """解析 census PowerShell 输出（PID=.. NAME=.. PPID=.. CMD=.. 行）。"""
    rows: list[CensusRow] = []
    for ln in (out or "").splitlines():
        stripped = ln.strip()
        if not stripped.startswith("PID="):
            continue
        pid_m = re.search(r"\bPID=(\d+)", stripped)
        ppid_m = re.search(r"\bPPID=(\d+)", stripped)
        if pid_m is None or ppid_m is None:
            continue
        name_m = re.search(r"NAME=(\S+)", stripped)
        cmd_m = re.search(r"CMD=(.*)$", stripped)
        rows.append(CensusRow(
            pid=int(pid_m.group(1)),
            ppid=int(ppid_m.group(1)),
            name=name_m.group(1) if name_m else "",
            cmdline=cmd_m.group(1) if cmd_m else "",
            raw=stripped,
        ))
    return rows


def classify_cmdline(cmdline: str, whitelist: tuple[str, ...]) -> str:
    """行级三态判定（E3-1 可测纯函数）：

    - ``keep``：命中在飞白名单（cmdline 含白名单子串）——绝不清理；
    - ``candidate``：命中任务指纹——待父进程核对；
    - ``skip``：非任务指纹——旁观。
    """
    for token in whitelist:
        if token and token in cmdline:
            return "keep"
    if ORPHAN_FINGERPRINT.search(cmdline):
        return "candidate"
    return "skip"


def collect_whitelist(
    cfg: RemoteMachineConfig | None,
    cli_tokens: list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    """在飞白名单汇总（去空去重保序）：登记文件 orphan_whitelist + CLI。

    登记面：configs/remote_machines*.yaml 机器条目 ``orphan_whitelist``
    （字符串或字符串列表，落入 ``RemoteMachineConfig.extra``）；
    CLI：``--whitelist TOKEN``（可多次）。缺省空=无白名单（E3-1：
    硬编码批次号必腐烂，在飞批次必须显式声明）。
    """
    tokens: list[str] = []
    raw = cfg.extra.get("orphan_whitelist") if cfg is not None else None
    if isinstance(raw, str):
        tokens.append(raw)
    elif isinstance(raw, (list, tuple)):
        tokens.extend(str(item) for item in raw)
    tokens.extend(str(tok) for tok in cli_tokens or ())
    seen: dict[str, None] = {}
    for tok in tokens:
        if tok and tok not in seen:
            seen[tok] = None
    return tuple(seen)


def decide_orphans(
    candidates: list[CensusRow],
    parent_alive: Callable[[int], bool | None],
) -> tuple[list[CensusRow], list[tuple[CensusRow, str]]]:
    """E3-1 核心判定：**父已死才算孤儿**（原实现缺失的核对）。

    ``parent_alive(ppid)`` 返回 True（存活）/ False（已死）/ None（查询
    失败=未知）。返回 ``(orphans, spared)``；orphans=可点杀名单，
    spared=[(row, reason)] 留痕——父存活在飞 / 查询失败按存活保守处理。
    """
    orphans: list[CensusRow] = []
    spared: list[tuple[CensusRow, str]] = []
    for row in candidates:
        alive = parent_alive(row.ppid)
        if alive is False:
            orphans.append(row)
        elif alive is True:
            spared.append((row, f"父 {row.ppid} 存活在飞"))
        else:
            spared.append((row, f"父 {row.ppid} 存活查询失败，按存活保守"
                                f"处理不杀"))
    return orphans, spared


def parent_alive_cmd(ppid: int) -> str:
    """父进程存活查询命令（Get-Process -Id 存在性；远程 PowerShell）。"""
    return (
        f"powershell -NoProfile -Command \"if (Get-Process -Id {int(ppid)} "
        f"-ErrorAction SilentlyContinue) {{'alive'}} else {{'dead'}}\""
    )


def _make_parent_probe(t: SshTransport) -> Callable[[int], bool | None]:
    """SSH 侧父存活探针：True/False；rc≠0/输出不可解析/异常=None（未知）。"""

    def probe(ppid: int) -> bool | None:
        try:
            rc, out, _err = t.run_command(
                parent_alive_cmd(ppid), timeout_s=PARENT_PROBE_TIMEOUT_S)
        except Exception:
            return None
        text = (out or "").strip().lower()
        if rc != 0 or text not in ("alive", "dead"):
            return None
        return text == "alive"

    return probe


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="服务器侧 rfauto 孤儿清理（父已死才算孤儿，E3-1）")
    ap.add_argument("--dry-run", action="store_true", help="只清点报告")
    ap.add_argument("--kill", action="store_true",
                    help="点杀命中项（命中指纹且父已死的孤儿）")
    ap.add_argument("--explain", action="store_true",
                    help="打印每行判定链（白名单/指纹/父存活→处置）")
    ap.add_argument("--whitelist", action="append", default=[],
                    metavar="TOKEN",
                    help="在飞批次白名单（cmdline 子串，可多次；另读登记"
                         "文件 orphan_whitelist；缺省空=无白名单）")
    args = ap.parse_args(argv)

    machines = load_remote_machines()
    cfg = resolve_machine("sim_host", machines)
    whitelist = collect_whitelist(cfg, args.whitelist)
    if args.explain:
        print(f"[config] whitelist={list(whitelist) or '（空=无白名单）'}")
    t = SshTransport(cfg)
    t.connect()
    try:
        # ① 全量 ansysedt/python 实例（含命令行与 PPID）
        _rc, out, _err = t.run_command(CENSUS_CMD, timeout_s=CENSUS_TIMEOUT_S)
        rows = parse_census_rows(out)
        print(f"[census] rfauto 侧候选 {len(rows)} 项")
        candidates: list[CensusRow] = []
        for row in rows:
            verdict = classify_cmdline(row.cmdline, whitelist)
            if args.explain:
                hit = [w for w in whitelist if w in row.cmdline]
                fingerprint = bool(ORPHAN_FINGERPRINT.search(row.cmdline))
                print(f"[chain ] pid={row.pid} whitelist_hit={hit or '-'} "
                      f"fingerprint={fingerprint} verdict={verdict}")
            if verdict == "keep":
                print(f"[keep ] {row.raw[:150]}（白名单在飞登记）")
            elif verdict == "skip":
                print(f"[skip ] 非任务指纹: {row.raw[:140]}")
            else:
                candidates.append(row)
        # ② 母进程核对（E3-1：父已死才算孤儿——原实现缺此步）
        probe = _make_parent_probe(t)
        orphans, spared = decide_orphans(candidates, probe)
        for row, reason in spared:
            print(f"[alive] {row.raw[:150]}（{reason}）")
        for row in orphans:
            print(f"[orphan] {row.raw[:160]}（父 {row.ppid} 已死）")
        # ③ 点杀（仅父已死孤儿）
        if args.kill:
            for row in orphans:
                rc2, o2, e2 = t.run_command(
                    f"taskkill /PID {row.pid} /F", timeout_s=KILL_TIMEOUT_S)
                print(f"  kill rc={rc2} {(o2 or e2).strip()[:60]}")
        # ④ 端口终态
        time.sleep(2)
        _rc3, o3, _e3 = t.run_command(
            "netstat -ano | findstr :50051 | findstr LISTENING", timeout_s=30)
        port = (o3 or "").strip()
        print(f"[port 50051] {'CLEAR' if not port else port[:120]}")
        if not args.dry_run and not args.kill:
            print("(默认清点模式——加 --kill 执行点杀；在飞批次先 "
                  "--whitelist 声明)")
        return 0
    finally:
        t.close()


if __name__ == "__main__":
    sys.exit(main())
