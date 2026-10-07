"""remote 子应用（多机协同 v0 探活/状态薄壳）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import typer

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
