"""edb 子应用（EDB 快车道 CLI 出口，2026-10-08）——build/solve/status 三叶。

零逻辑转发 service/edb_lane_service（规则 4 薄壳；发射综合/建库/批解编排
全在 service 与 adapters 确定性内核，铁律 7——本模块零物理数值）：
  rfauto edb build --template edb_branchline -p f0_ghz=2.4 --workdir runs/edb_lane
  rfauto edb build --template edb_power_divider -p f0_ghz=2.4 --dry-run
  rfauto edb solve runs/edb_lane/edb_branchline.aedb
  rfauto edb status runs/edb_lane

registration：域内自注册 add_typer（stats/firmware/layout 同款惯例，
main.py 只 re-export 不二次注册）；顶层无同名 ``edb`` 命令（#df6① 冲突
检查 2026-10-08：全 CLI 树零撞名）。全叶带 ``--json``（W2-C 棘轮门惯例）。
"""

from __future__ import annotations

import json

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

edb_app = typer.Typer(help="EDB 快车道（PyEDB 建库+hfss_batch 批解，平面族发射器）")
app.add_typer(edb_app, name="edb")


def _coerce_param(raw: str):
    """"50"→50、"2.4"→2.4、嵌套 dict/JSON 字面量→对象，解析失败保留字符串
    （calc_vna._coerce_param 同款；stackup/sweep 嵌套 dict 靠此透传）。"""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _parse_params(items: list[str] | None, *,
                  json_output: bool = False) -> dict:
    """-p k=v（可多次）→ params dict；v 走 JSON 解析（失败保留字符串）。

    非法形态经 ``_emit_usage_error``（#ge1㉙：--json 下输出 JSON 信封，
    A5 P1-1 收编）。"""
    params: dict = {}
    for item in items or []:
        key, sep, raw = item.partition("=")
        if not sep or not key.strip():
            _emit_usage_error(f"--param 需要 k=v 形式: {item}",
                              json_output=json_output)
        params[key.strip()] = _coerce_param(raw.strip())
    return params


@edb_app.command("build")
def edb_build_cmd(
    template: str = typer.Option(
        "edb_branchline", "--template", "-t",
        help="发射器模板键：支持族清单与 lange 预留键拒绝语义见 rfauto "
             "edb status --json 信封 templates 节（与发射分派表单源同步，"
             "此处不复列族名防漂移；人类可读表不含该节，须带 --json）；"
             "未知键报错回显合法族名单"),
    param: list[str] = typer.Option(  # noqa: B008
        None, "--param", "-p",
        help="设计参数 k=v（可多次；v 支持 JSON 字面量，如嵌套 stackup/"
             "sweep dict）；f0_ghz 必填，尺寸综合在 core.synthesis 内核"),
    workdir: str = typer.Option(
        "runs/edb_lane", "--workdir", "-w",
        help="产物根目录（.aedb 工程与 config 存证落点）"),
    name: str = typer.Option(
        None, "--name", help="产物文件名主干（缺省=template 键；禁路径分隔符）"),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="只发射 spec+适配器契约双检并回显 config 预览（零写盘零 pyedb，"
             "无 license 冒烟/计划态）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """发射 spec + EDB 建库（pyedb configuration → .aedb 工程+存证）。"""
    from rfauto.service.edb_lane_service import edb_build

    result = edb_build(template, _parse_params(param, json_output=json_output),
                       workdir=workdir, name=name, dry_run=dry_run)
    _emit(result, "EDB 建库失败", json_output=json_output)
    if json_output:
        return
    if dry_run:
        console.print("[green]✓ dry-run 计划态（零写盘零 pyedb）[/green] "
                      f"template={template} workdir={workdir}")
        spec = result.get("spec") or {}
        console.print(f"  spec: traces={len(spec.get('traces') or [])} "
                      f"ports={len(spec.get('ports') or [])} "
                      f"resistors={len(spec.get('resistors') or [])}")
        console.print("  config 段: "
                      + ", ".join(sorted(result.get("config") or {})))
        return
    for w in result.get("warnings") or []:
        console.print(f"[yellow]! {w}[/yellow]")
    console.print(f"[green]✓ EDB 工程已建[/green] → "
                  f"[cyan]{result.get('aedb_path')}[/cyan]")
    console.print(f"  config 存证: {result.get('config_json_path')}")


@edb_app.command("solve")
def edb_solve_cmd(
    project: str = typer.Argument(..., help=".aedb 工程目录或 .aedt 工程路径"),
    timeout_s: float = typer.Option(
        3600.0, "--timeout-s", help="每段进程 watchdog 超时秒（<=0 不设超时）"),
    export: bool = typer.Option(
        True, "--export/--no-export",
        help="求解成功后批后导 Touchstone（-batchextract 第二段进程；"
             "失败只告警不推翻求解 ok）"),
    design: str = typer.Option(None, "--design", help="限定设计名（缺省自动枚举）"),
    setup: str = typer.Option(None, "--setup", help="限定 setup 名（缺省自动枚举）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """批处理求解（ansysedt -BatchSolve）+ 可选 Touchstone 批后导出。"""
    from rfauto.service.edb_lane_service import edb_solve

    result = edb_solve(project, timeout_s=timeout_s, export=export,
                       design=design, setup=setup)
    _emit(result, "批处理求解失败", json_output=json_output)
    if json_output:
        return
    solve = result.get("solve") or {}
    console.print(f"[green]✓ 批解完成[/green] rc={solve.get('rc')} "
                  f"elapsed={solve.get('elapsed_s')}s "
                  f"log={solve.get('logfile')}")
    for a in solve.get("artifacts") or []:
        console.print(f"  产物: {a}")
    exp = result.get("export")
    if exp is not None:
        if exp.get("ok"):
            console.print(f"[green]✓ Touchstone 导出[/green] → "
                          f"[cyan]{exp.get('out_file')}[/cyan] "
                          f"（n_ports={exp.get('n_ports')}）")
        else:
            for w in result.get("warnings") or []:
                console.print(f"[yellow]! {w}[/yellow]")


@edb_app.command("status")
def edb_status_cmd(
    root: str = typer.Option(
        "runs/edb_lane", "--root", "-r", help="产物根目录（缺省 runs/edb_lane）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """扫描产物根目录的快车道资产清单（工程/存证/日志/Touchstone）。"""
    from rfauto.service.edb_lane_service import edb_status

    result = edb_status(root)
    _emit(result, "产物目录扫描失败", json_output=json_output)
    if json_output:
        return
    if not result.get("n_projects"):
        console.print(f"[yellow]{root} 下无 EDB 快车道产物[/yellow]")
        return
    table = Table(title=f"EDB 快车道产物（{result['root']}，"
                        f"{result['n_projects']} 项）")
    for col in ("stem", "aedb", "config", "solved", "sNp", "spec"):
        table.add_column(col, style="cyan" if col == "stem" else None)
    for it in result.get("items") or []:
        table.add_row(
            str(it.get("stem", "")),
            "✓" if it.get("aedb") else "-",
            "✓" if it.get("config_json") else "-",
            "✓" if it.get("solved") else "-",
            "✓" if it.get("touchstone") else "-",
            "✓" if it.get("spec_json") else "-")
    console.print(table)
    raise typer.Exit(code=0)


# help 渲染安全（#305）：裸 % 会在 --help 时炸 format 扩展、方括号会被
# rich 当 markup 吞字——本域 help 文本（子应用描述+三叶命令 docstring）
# 禁含两者；子应用描述在下方导入期 assert 钉住，三叶 docstring 面由
# tests/unit/test_edb_cli_mcp.py TestCliHelpHygiene 的运行时 --help
# 断言覆盖（ge8e 审查批曾试验导入期叶子遍历 assert，发现在特定合批
# 组成下与无关测试产生排序型交互，撤回改由测试面承担——登记项）。
assert "%" not in (edb_app.info.help or "")
assert "[" not in (edb_app.info.help or "")
