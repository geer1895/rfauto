"""remote 子应用（多机协同 v0 探活/状态薄壳）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

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
        None, help="机器注册表名（缺省=唯一登记机器；未登记=空面如实）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """并发求解面资源视图（本机 openEMS/HFSS 进程互斥态+服务器可达/在跑/磁盘）。"""
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
        None, help="机器注册表名（缺省=唯一登记机器；未登记=空面如实）"),
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
