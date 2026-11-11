"""layer-3d 子应用——KiCad .kicad_pcb 逐层 3D 渲染导出 CLI 薄壳（aurora_q
Q-X39，2026-11-07）。

零逻辑转发 service/layer_3d_render_service（规则 4 薄壳；铁律 7：渲染
坐标=s-expr 直出，pad 装配坐标=刚体旋转变换（oracle 互证口径），视图
参数（相机角/盒子比例/explode）全部显式声明随信封 view 键落档）::

    rfauto layer-3d render <board.kicad_pcb> [--layers F.Cu,B.Cu]
        [--out-dir <dir>] [--no-composite] [--no-svg]
        [--export-format png|svg|glb|step] [--explode 0.0] [--json]

- 逐层 PNG：铜层/阻焊层/丝印层/钻孔（Edge.Cuts）每层一张独立 3D 场景
  （mplot3d Agg OO，零 GUI 零真机零 license，纯文本 s-expr 直读——连
  KiCad 安装都不需要，AGENTS 规则 2 子进程形态的反向强化）；
- 叠层合成预览：PNG+SVG 双出（SVG 逐 collection gid=layer3d-<层名>，
  下游可按层挑组）；
- glb/step=接口预留（任务书第 5 项）：请求即 skipped 信封如实声明，
  零 silently-wrong 产物。

注册=域内自注册（anim/cal-wizard/exploded-view 同款：模块级 add_typer，
main.py 只 re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；
顶层无同名 ``layer-3d`` 域（#df6① 冲突检查 2026-11-07：全 CLI 树零撞
名，唯一近名 exploded-view 域语义=爆炸视图单场景渲染非逐层导出、
layout 域语义=GDSII/DXF/ODB++ 互格式面）。带 ``--json``（信封契约：
成功+失败同构——usage 错走 _emit_usage_error exit 2，service 信封失败
exit 1，_emit 单源出口）。
"""

from __future__ import annotations

import math

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

layer_3d_app = typer.Typer(
    help="KiCad .kicad_pcb 逐层 3D 渲染导出（铜/阻焊/丝印/钻孔逐层 PNG"
         "+叠层合成预览 PNG/SVG；service/layer_3d_render_service 薄壳）")
app.add_typer(layer_3d_app, name="layer-3d")


@layer_3d_app.command("render")
def layer_3d_render_cmd(
    pcb: str = typer.Argument(
        ..., help=".kicad_pcb 板文件路径（纯文本 s-expr 直读，零 pcbnew）"),
    layers: str = typer.Option(
        "F.Cu,B.Cu", "--layers",
        help="渲染层清单（逗号分隔；缺省 F.Cu,B.Cu；常见：F.Cu,B.Cu,"
             "F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,F.SilkS,B.SilkS,"
             "Edge.Cuts——双名都收；请求层不在板文件按空场景如实渲染）"),
    out_dir: str = typer.Option(
        None, "--out-dir",
        help="产物目录（逐层 PNG+合成 PNG/SVG 固定名落盘：<板名>_layer_<层>"
             ".png / <板名>_composite.png/.svg；缺省=只出信封零落盘）"),
    composite: bool = typer.Option(
        True, "--composite/--no-composite",
        help="叠层合成预览 PNG（全部请求层同场景按 z 叠放+介质体半透明）"),
    svg_composite: bool = typer.Option(
        True, "--svg/--no-svg",
        help="叠层合成预览 SVG（逐 collection gid=layer3d-<层名>）"),
    export_format: str = typer.Option(
        "png", "--export-format",
        help="png|svg|glb|step（glb/step=接口预留，skipped 信封如实）"),
    explode: float = typer.Option(
        0.0, "--explode",
        help="爆炸间距系数（≥0，层距=序号×系数×板厚；0=实叠层；呈现参数"
             "随信封 view 键落档，不影响几何坐标）"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """KiCad 板逐层 3D 渲染导出（逐层 PNG+合成预览；零 pcbnew 零 license）。

    示例：
        rfauto layer-3d render board.kicad_pcb --out-dir render_out
        rfauto layer-3d render board.kicad_pcb --layers F.Cu,B.Cu,F.Silkscreen --json
        rfauto layer-3d render board.kicad_pcb --export-format glb   # 预留面

    几何忠实（铁律 7）：走线/焊盘/过孔/板框/层厚全部 s-expr 原文毫米直读；
    pad 装配坐标=刚体旋转（pcbnew oracle 33 pad 互证 ≤3e-14 mm）；通配层
    名 `*.Cu`/`*.Mask` 按 pcbnew LSET 口径展开；stackup 缺厚度用声明式
    缺省+warning 如实（缺失不编造）。同输入两跑逐字节（SVG 盐固定）。
    """
    if export_format not in ("png", "svg", "glb", "step"):
        _emit_usage_error(
            f"未知 --export-format {export_format!r}"
            "（可用 png|svg|glb|step，glb/step=接口预留）",
            json_output=json_output)
        return
    if not math.isfinite(explode) or explode < 0.0:
        _emit_usage_error(
            f"--explode 必须为 ≥0 的有限数，得到 {explode!r}",
            json_output=json_output)
        return
    layer_list = [x.strip() for x in str(layers).split(",") if x.strip()]
    if not layer_list:
        _emit_usage_error(
            "--layers 清单为空——至少给一个层名（如 F.Cu,B.Cu）",
            json_output=json_output)
        return

    from rfauto.service.layer_3d_render_service import render_pcb_layers  # lazy: run-path（Q-X36 补标注）

    result = render_pcb_layers(
        pcb, out_dir=out_dir, layers=layer_list, composite=composite,
        svg_composite=svg_composite, export_format=export_format,
        explode=explode)
    _emit(result, "逐层 3D 渲染失败", json_output=json_output)
    if json_output:
        return
    # ---- 人读分支（动态段一律 escape——markup 纪律）----
    if result.get("skipped"):
        console.print(
            f"[yellow]○ 接口预留[/yellow] {escape(str(result.get('reason')))}")
        raise typer.Exit(code=0)
    console.print(
        f"[bold]逐层渲染[/bold]  source=[cyan]{escape(str(result.get('source')))}[/cyan]"
        f"  layers={escape(str(result.get('layers')))}")
    # soft_wrap=True：产物路径行禁 rich 自动折行（80 列下长路径文件名
    # 段跨行断开——run 43069995504 shard3 实测 minimal_board_layer_F_Cu.png
    # 被折；路径回显行禁折是复制粘贴/断言双友好，annotate 行同款先例）
    for p in result.get("png_paths") or []:
        console.print(f"  [green]✓[/green] {escape(str(p))}", soft_wrap=True)
    for p in result.get("svg_paths") or []:
        console.print(f"  [green]✓[/green] {escape(str(p))}", soft_wrap=True)
    comp = result.get("composite") or {}
    for key in ("png", "svg"):
        if comp.get(key):
            console.print(f"  [green]✓[/green] composite {key} → "
                          f"{escape(str(comp[key]))}", soft_wrap=True)
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")
