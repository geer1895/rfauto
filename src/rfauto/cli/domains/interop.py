"""interop 子应用（ME-10' ts21-write/hfss-comments）+ lint 统一门面（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json

import typer

from rfauto.cli.domains._core import _load_json_file as _load_json_file
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── interop（ME-10'：Touchstone 2.1 写出 + HFSS 注释块读取，JSON 进出薄壳） ───

interop_app = typer.Typer(help="Touchstone 互操作（ME-10'：TS 2.1 写出 + HFSS 注释块直读）")
app.add_typer(interop_app, name="interop")


@interop_app.command("ts21-write")
def interop_ts21_write_cmd(
    input_path: str = typer.Argument(..., help="输入 Touchstone（1.0/2.0/2.1，skrf 读入）"),
    output_path: str = typer.Argument(..., help="输出文件路径（扩展名建议按端口数 .sNp）"),
    run_id: str = typer.Option(None, "--run-id", help="关联 run 标识（写 provenance 行）"),
    comment: list[str] = typer.Option(None, "--comment", "-c", help="追加注释行（可多次）"),  # noqa: B008
    form: str = typer.Option("ri", "--form", help="数据档：ri（无损，缺省）/ma/db"),
    keep_z0: bool = typer.Option(True, "--keep-z0/--no-z0", help="是否写出参考阻抗"),
    json_output: bool = typer.Option(False, "--json", "-j", help="输出完整 JSON"),
) -> None:
    """Touchstone 2.1 写出：skrf 原生 2.1 关键字 + provenance 注释块 + 读回对拍。

    示例：rfauto interop ts21-write in.s2p out.s2p --run-id wf_x --comment "仲裁档"
    """
    from rfauto.service.interop_service import ts21_write

    result = ts21_write(
        input_path, output_path, run_id=run_id,
        comments=list(comment) if comment else None,
        form=form, write_z0=keep_z0)
    if not result.get("ok"):
        if json_output:
            console.print_json(json.dumps(result, ensure_ascii=False))
        else:
            console.print(f"[red]✗ {result.get('error')}[/red]")
        raise typer.Exit(code=2)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False))
        return
    d = result["data"]
    console.print(f"[green]✓[/green] {d['path']}"
                  f"（n_ports={d['n_ports']} n_freqs={d['n_freqs']} form={d['form']}）")
    console.print(f"  version_key: {d['version_key']}"
                  f"  roundtrip_max_abs_err={d['roundtrip_max_abs_err']:.3g}")


@interop_app.command("hfss-comments")
def interop_hfss_comments_cmd(
    path: str = typer.Argument(..., help="HFSS 导出的 .sNp 文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="输出完整 JSON"),
) -> None:
    """HFSS Touchstone 注释块直读：Gamma 传播常数 + Zpi 端口阻抗（模态基）。

    注意：! Port Impedance 恒为 Zpi 口径不按 CharImp 写出（#254）；Gamma 是
    传播常数 γ=α+jβ，不是反射系数（真实 corpus 数值互证）。

    示例：rfauto interop hfss-comments hfss_export.s4p --json
    """
    from rfauto.service.interop_service import hfss_touchstone_comments

    result = hfss_touchstone_comments(path)
    if not result.get("ok"):
        if json_output:
            console.print_json(json.dumps(result, ensure_ascii=False))
        else:
            console.print(f"[red]✗ {result.get('error')}[/red]")
        raise typer.Exit(code=2)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False))
        return
    d = result["data"]
    console.print(f"[bold]{d['path']}[/bold]"
                  f"（n_ports={d['n_ports']} n_freqs={d['n_freqs']}）")
    console.print(f"  renormalized: {d['renormalized']}"
                  f"  renormalize_ohm: {d['renormalize_ohm']}")
    if d.get("port_names"):
        console.print(f"  port_names: {d['port_names']}")
    if d.get("header"):
        for key, value in d["header"].items():
            console.print(f"  {key}: {value}")
    for label, key in (("gamma (α+jβ)", "gamma"), ("port_zpi", "port_zpi")):
        rows = d.get(key)
        if rows:
            first, last = rows[0], rows[-1]
            console.print(f"  {label}: {len(rows)} 频点，首点 "
                          + " ".join(f"[{p[0]:.6g}, {p[1]:.6g}]" for p in first)
                          + " … 末点 "
                          + " ".join(f"[{p[0]:.6g}, {p[1]:.6g}]" for p in last))
    console.print(f"  raw 注释行: {len(d.get('raw') or [])} 条（--json 取全量）")


# ─── lint（W4：design-lint 统一门面） ────────────────────────────────────────
# lint=聚合器不是新判据：只汇总既有 service/core 检查面（Z3 渲染约束/fab
# DFM/bounds 信息界/pdn 门/stub 谐振），统一 {checks, summary, verdict}
# JSON 契约；子检查注册表自持于 service/design_lint_service.py（仿
# BUDGET_REGISTRY 惯例）。MCP 暴露留后续批次登记（本批独占 cli/main.py）。
# exit code 语义：0=无 fail 检出（clean/attention）；1=检出 fail>0（issues）；
# 2=payload 程序性错误（文件不可读/形状非法/未知子检查名）。


def _render_lint_table(result: dict) -> None:
    """Rich 表格渲染 checks+summary（人读面；--json 走完整 JSON）。

    单元格内容一律 escape：detail 是各 service 的自由文本，可能含
    ``[...]``（如参数名列表），不转义会被 Rich 当 markup 标签解析，
    ``[/xx]`` 形态直接 MarkupError（实测 exit 1）。
    """
    from rich.markup import escape
    from rich.table import Table

    style = {"pass": "green", "fail": "red", "warn": "yellow",
             "unknown": "dim", "info": "blue"}
    table = Table(title="design lint（W4 统一门面：聚合既有检查，不新增判据）")
    table.add_column("check", style="cyan", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("detail", overflow="fold")
    table.add_column("source", style="dim", overflow="fold")
    for row in result["checks"]:
        st = str(row["status"])
        table.add_row(escape(str(row["name"])),
                      f"[{style.get(st, 'white')}]{st}[/]",
                      escape(str(row["detail"])),
                      escape(str(row["source"])))
    console.print(table)
    s = result["summary"]
    console.print(
        f"verdict=[bold]{result['verdict']}[/]  "
        f"pass={s.get('pass', 0)} fail={s.get('fail', 0)} "
        f"warn={s.get('warn', 0)} unknown={s.get('unknown', 0)} "
        f"info={s.get('info', 0)}")


@app.command("lint")
def lint_cmd(
    payload_path: str | None = typer.Argument(
        None,
        help="payload JSON 文件（可选；缺省=空 payload，各子检查按参数充足度"
             "自行判 unknown 并给明细）"),
    json_output: bool = typer.Option(
        False, "--json", help="输出完整 JSON（缺省 Rich 表格+摘要行）"),
) -> None:
    """设计体检一次查：约束/bounds/DFM/PDN/stub 聚合面（JSON 进出薄壳）。

    示例：rfauto lint / rfauto lint payload.json --json
    payload 键（全部可选，见 service.design_lint_service.design_lint）：
    checks（子集过滤）/template+params+fab（DFM）/constraints（Z3 约束）/
    bounds（bbox_m+f_hz 信息界）/pdn（腔模门）/stub（残桩谐振）。
    """
    from rfauto.service.design_lint_service import design_lint

    payload: dict = {}
    if payload_path is not None:
        payload = _load_json_file(payload_path, "payload")
    try:
        result = design_lint(payload)
    except (KeyError, TypeError, ValueError) as exc:
        console.print(f"[red]✗ payload 非法: {exc}[/red]")
        raise typer.Exit(code=2) from exc
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False,
                                      default=str))
    else:
        _render_lint_table(result)
    if result["summary"].get("fail", 0) > 0:
        raise typer.Exit(code=1)
