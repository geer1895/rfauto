"""teaching 子应用——模板教学卡两叶（VI-1 孤儿接线批 W1-C 单元 14）。

零逻辑转发 service/teaching_service（规则 4 薄壳；推导/排序/索引全在
确定性内核，铁律 7）：
  rfauto teaching show <template>   教学卡全文（物理与推导+敏感性排序）
  rfauto teaching index             教科书反向索引（模板↔章节对照表）

注册=域内自注册（stats/firmware 同款：模块级 add_typer，main.py 只
re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
`teaching` 命令（#df6① 冲突检查 2026-10-05：全 CLI 树零撞名）。
JSON 信封经 _emit 单点出口。
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

teaching_app = typer.Typer(help="模板教学卡（物理推导+敏感性排序+教科书索引）")
app.add_typer(teaching_app, name="teaching")


@teaching_app.command("show")
def teaching_show_cmd(
    template: str = typer.Argument(..., help="模板名（docs/templates 子目录名）"),
    markdown: str = typer.Option(None, "--markdown", "-m",
                                 help="Markdown 落盘路径（缺省只渲染）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """教学卡全文：物理与推导 + 敏感性排序（缺卡/缺块显式报错不硬凑）。

    示例：rfauto teaching show mline --markdown mline_teaching.md
    """
    from rfauto.service.teaching_service import (
        load_teaching,
        render_teaching_markdown,
    )

    try:
        teaching = load_teaching(template)
        md = render_teaching_markdown(template)
    except ValueError as exc:
        _emit({"ok": False, "errors": [str(exc)]},
              "教学卡加载失败", json_output=json_output)
        raise typer.Exit(code=1) from None
    result: dict = {"ok": True, "template": template, "teaching": teaching,
                    "markdown": md}
    if markdown:
        Path(markdown).write_text(md, encoding="utf-8")
        result["markdown_path"] = markdown
    _emit(result, "教学卡渲染失败", json_output=json_output)
    if not json_output:
        from rich.markdown import Markdown

        if markdown:
            console.print(f"[green]✓ 教学卡[/green] → [cyan]{markdown}[/cyan]")
        else:
            console.print(Markdown(md))
    raise typer.Exit(code=0)


@teaching_app.command("index")
def teaching_index_cmd(
    textbook: str = typer.Option(None, "--textbook",
                                 help="教科书名子串过滤（大小写不敏；缺省全表）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """教科书反向索引：章节↔模板↔内核模块对照（零过滤命中=空表如实）。

    示例：rfauto teaching index --textbook Pozar
    """
    from rfauto.service.teaching_service import textbook_index

    result = textbook_index(textbook)
    if result.get("ok") is False:
        # 防御面（判据 e：失败也走 _emit 信封退出码 1；现行 textbook_index
        # 恒 ok 无失败分支，此处只兜 service 面语义演进，不吞错）
        _emit(result, "教科书索引查询失败", json_output=json_output)
        raise typer.Exit(code=1)
    _emit({"ok": True, "schema": result["schema"],
           "n_rows": result["n_rows"], "rows": result["rows"]},
          "教科书索引查询失败", json_output=json_output)
    if not json_output:
        table = Table(title="教科书反向索引（teaching index）")
        table.add_column("教科书")
        table.add_column("章节")
        table.add_column("模板")
        for row in result["rows"]:
            table.add_row(str(row.get("textbook") or ""),
                          str(row.get("chapter") or ""),
                          "、".join(str(t) for t in (row.get("templates") or [])))
        console.print(table)
    raise typer.Exit(code=0)
