"""anim 子应用——动图渲染 CLI 薄壳（T-Q3 接线席 Q-W5-2R，aurora_q 方向 B）。

零逻辑转发 service/anim_render_service（规则 4 薄壳；铁律 7：spec 解析/
渲染/自检全在 service/animation 内核，本模块只搬运信封与文件路径）：
  rfauto anim render <spec.json> [--out <svg 路径>] [--self-check] [--json]

spec = 声明式 JSON（chart_type + source(s) + canvas/style/animation）；
同 spec 两跑逐字节同（sha256 钉）。缺省落点=spec 同目录同名 ``.svg``；
``--out -`` 不落盘（SVG 原文进信封 ``svg_str``，管道/Agent 文本信道消费）。
教程章：docs/tutorials/rf-animation.md（spec schema+16 图型+11 数据源
kind 词表权威出口）。

注册=域内自注册（dag/loop 同款：模块级 add_typer，main.py 只 re-export，
二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名 `anim` 域
（#df6① 冲突检查 2026-11-04：全 CLI 树零撞名）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

anim_app = typer.Typer(
    help="动图渲染（typed spec JSON→SVG 动画；service.animation 内核）")
app.add_typer(anim_app, name="anim")


@anim_app.command("render")
def anim_render_cmd(
    spec: str = typer.Argument(
        ..., help="动图 spec JSON 文件路径（chart_type+source(s) 声明式 spec）"),
    out: str = typer.Option(
        "", "--out",
        help="SVG 输出路径（缺省=spec 同目录同名 .svg；'-'=不落盘改信封 svg_str）"),
    self_check: bool = typer.Option(
        False, "--self-check",
        help="渲染后附自动化体检（结构/帧序/文字挤压 warn 级；信封 self_check 字段）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """渲染动图 SVG（确定性：同 spec 两跑逐字节同，sha256 钉）。"""
    from rfauto.service.anim_render_service import anim_render

    result = anim_render(spec, out=(out or None), self_check=self_check)
    _emit(result, "动图渲染失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓ 动图完成[/green]  chart_type={result.get('chart_type')}"
        f"  frames={result.get('frame_count')}"
        f"  sha256={str(result.get('sha256'))[:12]}")
    console.print(f"  SVG: {result.get('svg_path')}")
    warnings = result.get("warnings") or []
    if warnings:
        console.print(f"  [yellow]warnings({len(warnings)}):[/yellow]")
        for w in warnings[:5]:
            console.print(f"    - {w}")
    raise typer.Exit(code=0)
