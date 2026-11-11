"""remote 子应用（多机协同 v0 探活/状态薄壳）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。

board 叶（aurora_p G2 队列看板，2026-11-02）：四源（probe/status/queue/
mutex）聚合读面单快照——单叶双形态（F2 watchdog watch 家法）：缺省=
一次性快照即退（零循环零落盘）；``--refresh N`` 显式开启循环刷新
（Ctrl+C 优雅停；间隔下限复用 speculative_watch_service.MIN_INTERVAL_S
单源）；``--json-out`` 用户显式路径快照导出。零逻辑转发
service/remote_board_service（纯聚合零新探测；#105 单源失败降级行不炸板）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.markup import escape
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console
from rfauto.service.envelope import ok_envelope

# ─── remote（多机协同 v0：机器注册表探活/状态薄壳；规则 4 零逻辑转发） ──
# probe/status 零逻辑转发 service/remote_service（JSON 进出走 service）；
# 真机冒烟（remote_hfss_smoke）是 env 门 opt-in 运维面，不进 CLI/MCP
# 缺省面——冒烟走脚本驱动（与 fd_oe_campaign 同构，登记 scripts 后批）。

remote_app = typer.Typer(
    help="多机协同仿真资源（探活/状态；v0：HFSS gRPC 远程会话+SSH 通道）")
app.add_typer(remote_app, name="remote")


@remote_app.command("probe")
def remote_probe_cmd(
    machine: str | None = typer.Argument(
        None, help="机器注册表名（缺省=唯一登记机器；未登记=空表如实）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """TCP 探活登记机器（SSH/许可/RDP 端口连通性+时延，零副作用零凭据）。"""
    from rfauto.service.remote_service import remote_probe

    result = remote_probe(machine)
    _emit(result, "远程探活失败", json_output=json_output)
    if json_output:
        return
    if not result["machines"]:
        console.print("[dim]无登记机器（configs/remote_machines.yaml）——本地模式[/dim]")
        return
    for m in result["machines"]:
        console.print(
            f"[green]✓ {m['name']}[/green] {m['host']}  "
            f"reachable={m['reachable']}  probe={m['probe_s']}s")
        for label, p in (m.get("ports") or {}).items():
            mark = "[green]OPEN[/green]" if p["open"] else "[red]CLOSED[/red]"
            console.print(f"  {label:<16}:{p['port']:<6} {mark}  {p['latency_ms']}ms")


@remote_app.command("status")
def remote_status_cmd(
    machine: str | None = typer.Argument(
        None, help="机器注册表名（缺省=唯一登记机器；未登记=空表如实）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """探活 + SSH 认证可达性（凭据缺失如实 missing_credentials 不猜不试）。"""
    from rfauto.service.remote_service import remote_status

    result = remote_status(machine)
    _emit(result, "远程状态失败", json_output=json_output)
    if json_output:
        return
    if not result["machines"]:
        console.print("[dim]无登记机器（configs/remote_machines.yaml）——本地模式[/dim]")
        return
    for m in result["machines"]:
        ssh = m.get("ssh") or {}
        console.print(
            f"[green]✓ {m['name']}[/green] {m['host']}  "
            f"reachable={m['reachable']}  ssh_auth={ssh.get('auth')}")
        if ssh.get("hint"):
            console.print(f"  [dim]{ssh['hint']}[/dim]")
        for label, p in (m.get("ports") or {}).items():
            mark = "[green]OPEN[/green]" if p["open"] else "[red]CLOSED[/red]"
            console.print(f"  {label:<16}:{p['port']:<6} {mark}  {p['latency_ms']}ms")


# ─── remote resources/queue（E-06/PR-15 调度面 v1 切片，2026-10-08） ──────────
# 多机资源可见性 + 队列视图（纯只读聚合，#105 best-effort 降级 unknown 不阻塞；
# 凭据/主机名不落信封——机器只以注册表键名出现）。零逻辑转发
# remote_scheduler_service（规则 4）；发射侧路由/资源日历全版仍是拆批余件。

@remote_app.command("resources")
def remote_resources_cmd(
    machine: str | None = typer.Argument(
        None, help="机器注册表名（缺省=唯一登记机器；未登记时显示为空）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """并发求解面资源视图（本机 openEMS/HFSS 进程互斥态+服务器可达/在跑/磁盘）。

    --json 输出里的 recommend 字段是选机推荐块（eligible/score/reasons，
    纯只读参考，不改变任务去向；人读表格不含此块）。写法见
    docs/how-to/campaign-queue-and-notify.md。
    """
    from rfauto.service.remote_scheduler_service import resources_view

    result = resources_view(machine)
    _emit(result, "资源视图聚合失败", json_output=json_output)
    if json_output:
        return
    table = Table(title="并发求解面资源视图（只读；unknown=探测降级非故障）")
    table.add_column("面")
    table.add_column("通道/项")
    table.add_column("状态")
    table.add_column("数值 / 降级原因")
    for channel in ("openems", "hfss"):
        label = "openEMS" if channel == "openems" else "HFSS"
        ch = (result.get("local") or {}).get(channel) or {}
        if ch.get("state") == "ok":
            mark = ("[yellow]BUSY[/yellow]" if ch.get("busy")
                    else "[green]IDLE[/green]")
            detail = f"n_procs={ch.get('n_procs')}"
            if channel == "hfss" and ch.get("n_grpcsrv") is not None:
                detail += f"  grpcsrv={ch['n_grpcsrv']}"
            table.add_row("本机", label, mark, detail)
        else:
            table.add_row("本机", label, "[dim]unknown[/dim]",
                          str(ch.get("reason") or ""))
    remote = result.get("remote") or {}
    if not remote.get("machine"):
        table.add_row("服务器", "—", "[dim]no_machine[/dim]",
                      str(remote.get("reason") or "无登记机器"))
    else:
        reach = remote.get("reachable")
        rmark = "[green]reachable[/green]" if reach else "[red]unreachable[/red]"
        if reach is None:
            rmark = "[dim]unknown[/dim]"
        table.add_row("服务器", remote["machine"], rmark,
                      f"n_tasks={remote.get('n_tasks')}")
        for label, key in (("在跑 openEMS", "openems"), ("在跑 HFSS", "hfss")):
            ch = remote.get(key) or {}
            if ch.get("state") == "ok":
                table.add_row("服务器", label,
                              "[yellow]BUSY[/yellow]" if ch.get("busy")
                              else "[green]IDLE[/green]",
                              f"n_procs={ch.get('n_procs')}")
            else:
                table.add_row("服务器", label, "[dim]unknown[/dim]",
                              str(ch.get("reason") or ""))
        disk = remote.get("disk") or {}
        if disk.get("state") == "ok":
            table.add_row("服务器", "磁盘余量", "[green]ok[/green]",
                          f"{disk.get('drive')} {disk.get('free_gb')} GB")
        else:
            table.add_row("服务器", "磁盘余量", "[dim]unknown[/dim]",
                          str(disk.get("reason") or ""))
    console.print(table)


@remote_app.command("queue")
def remote_queue_cmd(
    machine: str | None = typer.Argument(
        None, help="机器注册表名（缺省=唯一登记机器；未登记时显示为空）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """任务队列视图（job_registry 在途作业+单写锁排队+席位占用+服务器在跑态）。"""
    from rfauto.service.remote_scheduler_service import queue_view

    result = queue_view(machine)
    _emit(result, "队列视图聚合失败", json_output=json_output)
    if json_output:
        return
    counts = result.get("counts") or {}
    console.print(
        f"[bold]任务队列[/bold]  在册 {counts.get('n_jobs', 0)}"
        f"  在途 {counts.get('n_active', 0)}"
        f"  写锁排队 {counts.get('n_waiting', 0)}")
    lock = result.get("write_lock") or {}
    console.print(
        f"  单写锁 owner: {lock.get('owner') or '[dim]无（空闲）[/dim]'}")
    seats = result.get("seat_occupancy") or {}
    if seats:
        console.print("  席位占用: " + "  ".join(
            f"{k}={','.join(v)}" for k, v in seats.items()))
    rows = result.get("jobs") or []
    if rows:
        table = Table(title="在册作业（进程内注册表；历史 run 走 jobs status）")
        table.add_column("job_id", style="cyan")
        table.add_column("state")
        table.add_column("run_id")
        table.add_column("seats")
        table.add_column("progress")
        table.add_column("stage")
        for r in rows:
            pct = r.get("progress_pct")
            pct_s = f"{pct:.0f}%" if isinstance(pct, (int, float)) else "-"
            table.add_row(
                str(r.get("job_id")), str(r.get("state")),
                str(r.get("run_id") or ""), ",".join(r.get("seats") or []),
                pct_s, str(r.get("stage") or ""))
        console.print(table)
    else:
        console.print("[dim]在册作业为空（进程内注册表无任务）[/dim]")
    remote = result.get("remote") or {}
    if remote.get("machine"):
        n_tasks = remote.get("n_tasks")
        console.print(
            f"  服务器 {remote['machine']}: reachable={remote.get('reachable')}"
            f"  n_tasks={'unknown' if n_tasks is None else n_tasks}"
            f"（进程 census 口径，非 license 席位）")
    else:
        console.print(f"  服务器: [dim]{remote.get('reason') or '无登记机器'}[/dim]")


# ─── remote board（aurora_p G2 服务器队列看板，2026-11-02） ──────────────────
# 四源（probe/status/queue/mutex）聚合 → 单快照：机器表+队列任务表+互斥
# 状态+异常降级行 rich 渲染。单叶双形态（watchdog watch 先例）：缺省=
# 一次性快照零循环零写；--refresh N 显式开启循环（Ctrl+C 优雅停，interval
# 下限单源 speculative MIN_INTERVAL_S）；--json-out 用户显式路径导出。
# 零逻辑转发 remote_board_service（对齐用户 directive：lab_server 并行
# 求解可见性；凭据/主机名不落信封——机器只以注册表键名出现）。

#: --refresh 无界轮数上限（range 惰性非线程——watchdog 家法；实际由
#: Ctrl+C 终止，取值足够大以等效长驻，非语义承诺）。
_BOARD_REFRESH_ROUNDS_UNBOUNDED = 10 ** 9


def _board_face_mark(face: dict) -> str:
    """通道/磁盘子面 → rich 状态标记（BUSY 黄/IDLE·ok 绿/unknown 暗淡；
    unknown=探测降级非故障，#105）。"""
    if not isinstance(face, dict) or face.get("state") != "ok":
        return "[dim]unknown[/dim]"
    if "busy" in face:
        return "[yellow]BUSY[/yellow]" if face.get("busy") else "[green]IDLE[/green]"
    return "[green]ok[/green]"


def _render_board_human(snap: dict, round_no: int | None) -> None:
    """看板人读分支（三面板+降级行；动态段一律 escape——markup 纪律）。"""
    suffix = (f"（第 {round_no} 轮）" if round_no is not None
              else "（一次性快照）")
    machines = snap.get("machines") or []
    if not machines:
        console.print(
            f"[bold]remote 队列看板[/bold]{suffix}  "
            "[dim]无登记机器（configs/remote_machines.yaml）——本地模式[/dim]")
    else:
        console.print(f"[bold]remote 队列看板[/bold]{suffix}")

    # ── 面板一：机器表（名/可达/SSH/在飞/磁盘） ──────────────────────────
    if machines:
        mtable = Table(title="机器（在飞 n_tasks=进程 census 口径非 license 席位）")
        mtable.add_column("机器", style="cyan")
        mtable.add_column("可达")
        mtable.add_column("SSH")
        mtable.add_column("在飞 n_tasks")
        mtable.add_column("磁盘余量")
        mtable.add_column("状态")
        for m in machines:
            reach = m.get("reachable")
            if reach is True:
                rmark = "[green]reachable[/green]"
            elif reach is False:
                rmark = "[red]unreachable[/red]"
            else:
                rmark = "[dim]unknown[/dim]"
            ssh = (m.get("ssh") or {}).get("auth")
            disk = m.get("disk") or {}
            disk_s = (f"{disk.get('drive')} {disk.get('free_gb')} GB"
                      if disk.get("state") == "ok" else "unknown")
            n_tasks = ("unknown" if m.get("n_tasks") is None
                       else str(m.get("n_tasks")))
            mtable.add_row(
                escape(str(m.get("machine"))), rmark,
                escape(str(ssh)), n_tasks, disk_s,
                escape(str(m.get("state") or "")))
        console.print(mtable)

    # ── 面板二：队列任务表（在册作业+计数+写锁摘要） ─────────────────────
    counts = snap.get("counts") or {}
    console.print(
        f"[bold]任务队列[/bold]  在册 {counts.get('n_jobs', 0)}"
        f"  在途 {counts.get('n_active', 0)}"
        f"  写锁排队 {counts.get('n_waiting', 0)}")
    rows = snap.get("jobs") or []
    if rows:
        jtable = Table(title="在册作业（进程内注册表；历史 run 走 jobs status）")
        jtable.add_column("job_id", style="cyan")
        jtable.add_column("state")
        jtable.add_column("run_id")
        jtable.add_column("seats")
        jtable.add_column("progress")
        jtable.add_column("stage")
        for r in rows:
            pct = r.get("progress_pct")
            pct_s = f"{pct:.0f}%" if isinstance(pct, (int, float)) else "-"
            jtable.add_row(
                str(r.get("job_id")), str(r.get("state")),
                str(r.get("run_id") or ""), ",".join(r.get("seats") or []),
                pct_s, str(r.get("stage") or ""))
        console.print(jtable)
    else:
        console.print("[dim]在册作业为空（进程内注册表无任务）[/dim]")

    # ── 面板三：互斥状态（单写锁+席位占用+本机/服务器双通道） ────────────
    lock = snap.get("write_lock") or {}
    console.print(
        f"  单写锁 owner: {lock.get('owner') or '[dim]无（空闲）[/dim]'}"
        f"（FIFO 队长 {lock.get('queue_length', 0)}）")
    seats = snap.get("seat_occupancy") or {}
    if seats:
        console.print("  席位占用: " + "  ".join(
            f"{escape(str(k))}={','.join(v)}" for k, v in seats.items()))
    mutex_table = Table(title="#261 互斥态（unknown=探测降级非故障）")
    mutex_table.add_column("面")
    mutex_table.add_column("通道")
    mutex_table.add_column("状态")
    mutex_table.add_column("n_procs")
    local_mutex = snap.get("local_mutex") or {}
    for key, label in (("openems", "openEMS"), ("hfss", "HFSS")):
        mutex_table.add_row(
            "本机", label, _board_face_mark(local_mutex.get(key) or {}),
            str((local_mutex.get(key) or {}).get("n_procs")))
    if machines:
        m = machines[0]
        for key, label in (("openems", "openEMS"), ("hfss", "HFSS")):
            mutex_table.add_row(
                escape(str(m.get("machine"))), label,
                _board_face_mark(m.get(key) or {}),
                str((m.get(key) or {}).get("n_procs")))
    console.print(mutex_table)

    # ── 降级行（#105：单源失败留痕不炸板） ────────────────────────────────
    degradations = snap.get("degradations") or []
    if degradations:
        console.print(f"[yellow]降级 {len(degradations)} 项[/yellow]")
        for d in degradations:
            console.print(
                f"  [dim]- {escape(str(d.get('source')))}"
                f"/{escape(str(d.get('face')))}: "
                f"{escape(str(d.get('reason')))}[/dim]")


@remote_app.command("board")
def remote_board_cmd(
    machine: str | None = typer.Argument(
        None, help="机器注册表名（缺省=唯一登记机器；未登记=空表如实）"),
    refresh: float = typer.Option(
        None, "--refresh",
        help="自动刷新循环（显式开启）：间隔秒（下限=speculative_watch_service."
             "MIN_INTERVAL_S 单源，更小值被抬到下限）；无本旗标=一次性快照即退"
             "（零循环零落盘），Ctrl+C 优雅停"),
    json_out: str = typer.Option(
        None, "--json-out",
        help="快照 JSON 导出路径（每次快照后覆写最新值；仅用户显式指定才落盘）"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """服务器队列看板：机器表+队列任务表+互斥状态+异常降级行单快照。

    一次性快照（缺省）：rfauto remote board
    自动刷新（显式开启，Ctrl+C 优雅停）：rfauto remote board --refresh 10
    快照导出（用户指定路径，覆写最新）：rfauto remote board --json-out runs/board.json

    四源=probe/status/queue/mutex 既有 service 读面纯聚合（零新探测逻辑，
    service/remote_board_service 单源）；单机探测失败=降级行 unknown 留痕
    不炸板（#105）；凭据/主机名不落信封（机器只以注册表键名出现）。本
    命令零落盘（除 --json-out 显式路径）；--refresh 逐轮追加输出不清屏
    （管道/重定向友好）；--json 刷新形态逐轮 JSONL+收束汇总信封。
    """
    from rfauto.service import remote_board_service as rbs  # lazy: run-path（执行面按需取用）
    from rfauto.service.speculative_watch_service import MIN_INTERVAL_S  # lazy: run-path（执行面按需取用）

    if refresh is not None and float(refresh) < 0:
        _emit_usage_error("--refresh 须为非负秒数", json_output=json_output)
        return

    def _take_and_export() -> dict:
        snap = rbs.board_snapshot(machine)
        if json_out:
            p = Path(os.path.abspath(str(json_out)))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(snap, ensure_ascii=False, indent=2,
                           default=str) + "\n",
                encoding="utf-8")
        return snap

    # ── 缺省形态：一次性快照（零循环零落盘，逐字节同 service 直调） ──────
    if refresh is None:
        snap = _take_and_export()
        _emit(snap, "队列看板聚合失败", json_output=json_output)
        if json_output:
            return
        _render_board_human(snap, round_no=None)
        return

    # ── 循环形态（显式 --refresh）：逐轮快照渲染，Ctrl+C 优雅停 ──────────
    interval_s = max(float(refresh), float(MIN_INTERVAL_S))
    import time  # lazy: run-path（仅 --refresh 循环态消费）

    rounds_done = 0
    interrupted = False
    try:
        for _round in range(1, _BOARD_REFRESH_ROUNDS_UNBOUNDED + 1):
            snap = _take_and_export()
            rounds_done += 1
            if not snap.get("ok"):
                # 注册表解析类错误信封：用户输入错误即停不空转（与一次性
                # 形态同走 _emit 失败出口；降级类照常循环——#105 观测面）
                _emit(snap, "队列看板聚合失败", json_output=json_output)
                return
            if json_output:
                # 逐轮 JSONL 行（管道友好，watchdog --watch 同款口径）
                console.print_json(json.dumps(
                    snap, ensure_ascii=False, default=str))
            else:
                _render_board_human(snap, round_no=rounds_done)
            time.sleep(interval_s)
    except KeyboardInterrupt:
        # Ctrl+C 优雅停：已收轮数如实带出（观测面采样中断不是故障，#105）
        interrupted = True

    summary = ok_envelope(
        mode="board-refresh",
        rounds_done=rounds_done,
        rounds_planned=_BOARD_REFRESH_ROUNDS_UNBOUNDED,
        interrupted=interrupted,
        interval_s=interval_s,
        machine=machine,
        json_out=str(Path(os.path.abspath(str(json_out)))) if json_out else None,
    )
    if json_output:
        _emit(summary, "board 刷新失败", json_output=True)
        return
    tail = "（Ctrl+C 优雅停）" if interrupted else ""
    console.print(
        f"[green]✓ board 刷新结束[/green]  轮数 {rounds_done}{tail}"
        f"  interval={interval_s}s")
