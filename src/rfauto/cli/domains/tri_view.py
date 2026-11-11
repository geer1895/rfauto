"""tri-view 子应用——原理图↔版图↔3D 三视图联动 CLI 薄壳（aurora_q 席位 Q-X38）。

零逻辑转发 service/tri_view_service（规则 4 薄壳；铁律 7：映射/坐标/高亮/
lint 标注全在 service 确定性面，本模块只搬运文件路径与信封）::

  rfauto tri-view link <sch.json> <pcb.json> [--out-dir D] [--lint R | --self-lint]
                       [--bodies B] [--copper-thickness-mm T] [--json]

sch.json=SchSpec（schema rfauto-sch-spec-v1）；pcb.json=kicad_extract.extract_pcb
契约 JSON（mm）；缺省落点=sch 同目录 ``<stem>.tri_view.svg`` /
``<stem>.tri_view.json``，``--out-dir -`` 不落盘（SVG 原文进信封 svg_str）。
叶带 --json（合流期"新面必红清单"①）。

**注册形态说明（合流契约，主代理接线时照此一步到位；Q-X35 citi 同款）**：
本模块自带独立 typer 根 ``tri_view_app``，**不**在模块级 add_typer 到共享
app——注册序金快照（tests/gold/cli_registration_order.json）与 CLI 计数字面
钉对本席冻结（禁改清单），先接线后重锚是合流笔的显式评审动作。合流接线：

  1. main.py 注册序尾追加（facade re-export + 显式挂载）::

       from rfauto.cli.domains.tri_view import tri_view_app as tri_view_app
       from rfauto.cli.domains.tri_view import tri_view_link_cmd as tri_view_link_cmd
       app.add_typer(tri_view_app, name="tri-view")  # tri_view 域不自注册（合流契约）

  2. 计数链（+1 顶层组 tri-view、+1 叶）：check_numbers.count_cli() 实测值回填
     test_check_numbers/test_cli/test_cli_registration_order/test_anim_cli/
     test_vendor_docs_cli 字面钉 + ``tests/unit/test_cli_registration_order.py
     --write-gold`` 重钉注册序金快照 + cli/help_groups.HELP_PANEL_OF 补
     ``"tri-view": "综合与设计"``（test_aurora_n_wave_ui_c 键集==顶层名集）+
     docs_site 机读页再生（build_docs_pages）+ README/AGENT_HANDOFF/docs 数字
     同笔；接线后 domain_survey V2 孤儿域模块告警随之消除。

本席测试经 ``tri_view_app`` 挂测试局部父 Typer 直连（CliRunner），零共享 app
污染、零金快照漂移；顶层无同名 ``tri-view`` 域（零撞名自查 2026-11-07：全
CLI 树零 tri-view/tri_view 前缀组/命令）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

tri_view_app = typer.Typer(
    help="原理图↔版图↔3D 三视图联动（位号 ref 为键 1:1 映射+交叉高亮+联动 SVG 三联）")


@tri_view_app.command("link")
def tri_view_link_cmd(
    sch: str = typer.Argument(..., help="原理图 SchSpec JSON 路径（schema=rfauto-sch-spec-v1）"),
    pcb: str = typer.Argument(..., help="版图 JSON 路径（kicad_extract.extract_pcb 契约，mm）"),
    out_dir: str = typer.Option(
        "", "--out-dir", help="输出目录（缺省=sch 同目录；'-'=不落盘，SVG 原文进信封 svg_str）"),
    lint: str = typer.Option(
        "", "--lint", help="geometry_lint 报告 JSON 路径：问题对象标注到三视图位置"),
    self_lint: bool = typer.Option(
        False, "--self-lint", help="对 3D 面投影自跑 geometry_lint 并标注（与 --lint 互斥）"),
    bodies: str = typer.Option(
        "", "--bodies",
        help="3D 体 JSON（schema=rfauto-tri-view-bodies-v1：外部体表或 layered_stack 声明；"
             "缺省=版图焊盘×叠层派生）"),
    copper_thickness_mm: float | None = typer.Option(
        None, "--copper-thickness-mm",
        help="声明铜厚 mm（extract 契约无铜厚；缺省=零厚 sheet，lint 不判 sheet 相交）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """三视图联动：位号键 1:1 映射+交叉高亮数据+联动 SVG 三联（同输入逐字节同）。"""
    from rfauto.service.tri_view_service import tri_view_link  # lazy: startup-cost（cli 注册根轻载）

    result = tri_view_link(
        sch, pcb, out_dir=(out_dir or None), lint_path=(lint or None), self_lint=self_lint,
        bodies_path=(bodies or None), copper_thickness_mm=copper_thickness_mm)
    _emit(result, "三视图联动失败", json_output=json_output)
    if json_output:
        return
    counts = result.get("counts") or {}
    console.print(
        f"[green]✓ 三视图联动完成[/green]  refs={counts.get('refs')}"
        f"  linked={counts.get('linked')}  one_to_one={result.get('one_to_one')}"
        f"  issues E{counts.get('issues_error')}/W{counts.get('issues_warn')}")
    if result.get("svg_path"):
        console.print(f"  SVG: {result.get('svg_path')}", markup=False)
        console.print(f"  映射: {result.get('map_path')}", markup=False)
    lint_ann = result.get("lint") or {}
    if lint_ann:
        lc = lint_ann.get("counts") or {}
        console.print(
            f"  lint: {lc.get('issues', 0)} 条 → flagged refs {lc.get('flagged_refs', 0)}"
            f"（unresolved {lc.get('unresolved', 0)}）", markup=False)
    for it in (result.get("issues") or [])[:5]:
        console.print(f"  - {it.get('level')} {it.get('kind')}: {it.get('message')}", markup=False)
