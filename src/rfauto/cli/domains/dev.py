"""dev 子应用——维护者脚手架两叶（SO-审查 §7 P5 W6-D，2026-10-05）。

零逻辑转发 service/dev_scaffold_service（规则 4 薄壳；adapter_kit 先例）：
  rfauto dev new-template    新模板骨架包（meta 草稿+渲染/审计占位+消费钉清单）
  rfauto dev new-calculator  新计算器骨架（@register_calculator 占位+消费钉清单）

JSON 信封直出（ok=false → 退出码 1）；stats.py 同款域内自注册，
main.py 只 re-export（二次 add_typer 会双注册打红 zero-shadow 钉）。
"""

from __future__ import annotations

import json

import typer

from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

dev_app = typer.Typer(help="维护者脚手架（骨架生成+消费钉清单，SO §7 P5）")
app.add_typer(dev_app, name="dev")


def _emit_dev(result: dict, json_output: bool) -> None:
    """JSON 信封直出；ok=False → 退出码 1（stats._emit_stats 同款口径）。"""
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("ok"):
            raise typer.Exit(code=1)
        return
    if not result.get("ok"):
        for err in result.get("errors") or []:
            console.print(f"[red]✗ {err}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ 脚手架生成（{result.get('kind')}："
                  f"{result.get('name')}）[/green]")
    for path in result.get("created") or []:
        console.print(f"  新建: {path}")
    for path in result.get("skipped") or []:
        console.print(f"  [yellow]已存在跳过: {path}[/yellow]")
    for step in result.get("next_steps") or []:
        console.print(f"  下一步: {step}")


@dev_app.command("new-template")
def dev_new_template_cmd(
    name: str = typer.Argument(..., help="模板名（蛇形命名，如 my_bpf）"),
    out: str = typer.Option(None, "--out", "-o",
                            help="输出目录（缺省 docs/templates/<名>）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """新模板骨架包：meta 草稿+渲染/审计占位+消费钉清单（不覆盖既有）。"""
    from rfauto.service.dev_scaffold_service import scaffold_template

    _emit_dev(scaffold_template(name, out), json_output)


@dev_app.command("new-calculator")
def dev_new_calculator_cmd(
    name: str = typer.Argument(..., help="计算器键名（蛇形命名）"),
    out: str = typer.Option(None, "--out", "-o",
                            help="输出目录（缺省 scripts/scaffold）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """新计算器骨架：注册占位+消费钉清单（不覆盖既有；骨架文件不入库）。"""
    from rfauto.service.dev_scaffold_service import scaffold_calculator

    _emit_dev(scaffold_calculator(name, out), json_output)
