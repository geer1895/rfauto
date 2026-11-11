"""exploded-view 子应用——版图 3D 爆炸视图渲染 CLI 薄壳（T-Q37 席位 Q-X37，
aurora_q 方向 CAD 3D）。

零逻辑转发 service/exploded_view_service（规则 4 薄壳；铁律 7：渲染坐标
=layered_stack_spec 分层围合布局单源/KiCad s-expr 解析直通，explode_factor
为显式声明参数随信封 explode 键落档）::

    rfauto exploded-view render <spec.json> [--format svg|json|png|all]
        [--explode-factor 1.5] [--json]

spec = 声明式 JSON::

    {"source": "layered_stack", "spec": {...LayeredStackSpec 字段，缺省 {}=名义}}
    {"source": "kicad", "pcb_path": "板.kicad_pcb",
     "copper_kinds"?: {"层名": "signal|ground"}, "require_epsilon_r"?: bool,
     "scene_name"?: "..."}

pcb_path 相对路径按 spec 文件同目录解析（#144 同族：零 cwd 依赖）；
缺省输出=spec 同目录 ``<scene_name>.svg/.json/.png`` +
``<scene_name>_lint.json``。geometry_lint 闭环（Q-X37 验收核心口径）：
渲染前 lint 全六检查，零 ERROR 才渲染（ERROR=拦截渲染 ok=False，渲染
产物零落盘）；WARN 不拦截，报告随信封 lint 键与 ``_lint.json`` 同落。

注册=域内自注册（anim/cal-wizard 同款：模块级 add_typer，main.py 只
re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
``exploded-view`` 域（#df6① 冲突检查 2026-11-07：全 CLI 树零撞名，
唯一近名 diagram 域语义=工程图绘制非 3D 渲染）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import _load_json_file as _load_json_file
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

exploded_view_app = typer.Typer(
    help="版图 3D 爆炸视图（layered_stack/KiCad→SVG/JSON/PNG+lint 闭环）")
app.add_typer(exploded_view_app, name="exploded-view")

_FORMATS_HELP = "输出形态 svg|json|png|all（all=三形态+lint 报告 JSON）"


@exploded_view_app.command("render")
def exploded_view_render_cmd(
    spec: str = typer.Argument(
        ..., help="爆炸视图 spec JSON 文件路径（source=layered_stack|kicad）"),
    format: str = typer.Option(
        "all", "--format", help=_FORMATS_HELP),
    explode_factor: float = typer.Option(
        1.5, "--explode-factor",
        help="爆炸系数（层距放大倍数，≥0；0=收拢回名义叠放）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """渲染 3D 爆炸视图（lint 零 ERROR 才渲染；确定性 sha256 落档）。"""
    if format not in ("svg", "json", "png", "all"):
        _emit_usage_error(
            f"未知 --format {format!r}（可用 svg|json|png|all）",
            json_output=json_output)
    import math

    if (not math.isfinite(explode_factor) or explode_factor < 0.0):
        _emit_usage_error(
            f"--explode-factor 必须为 ≥0 的有限数，得到 {explode_factor!r}",
            json_output=json_output)
    spec_data = _load_json_file(spec, "spec", json_output=json_output)

    from rfauto.service.exploded_view_service import render_exploded_view  # lazy: run-path（Q-X36 补标注）

    result = render_exploded_view(
        spec_data, explode_factor=explode_factor, formats=format,
        spec_path=spec)
    _emit(result, "爆炸视图渲染失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓ 爆炸视图完成[/green]  scene={result.get('scene_name')}"
        f"  source={result.get('source_kind')}"
        f"  lint_pass={result.get('lint_pass')}")
    lint_counts = (result.get("lint") or {}).get("counts") or {}
    console.print(
        f"  lint: error={lint_counts.get('error')} warn={lint_counts.get('warn')}")
    for key, item in (result.get("outputs") or {}).items():
        console.print(f"  {key}: {item.get('path')}（sha256={str(item.get('sha256'))[:12]}）")
    warnings = result.get("warnings") or []
    if warnings:
        console.print(f"  [yellow]warnings({len(warnings)}):[/yellow]")
        for w in warnings[:5]:
            console.print(f"    - {w}")
    raise typer.Exit(code=0)
