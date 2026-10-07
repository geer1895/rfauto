"""zenodo 子应用——CITATION.cff 导出与校验两叶（VI-1 孤儿接线批 W1-C 单元 15c）。

零逻辑转发 service/zenodo_service（PR-11 元数据面；**零网络铁律**——
本子应用只做本地文件解析与组装，永不真实上传，上传动作由用户在
release 面显式执行）：
  rfauto zenodo export     CITATION.cff → Zenodo deposit 元数据（可落盘）
  rfauto zenodo validate   必填字段+pyproject 版本同步校验（warnings 如实）

注册=域内自注册（stats/firmware 同款：模块级 add_typer，main.py 只
re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
`zenodo` 命令（#df6① 冲突检查 2026-10-05：全 CLI 树零撞名）。
JSON 信封经 _emit 单点出口。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

zenodo_app = typer.Typer(help="Zenodo 元数据导出与 CITATION.cff 校验（PR-11，零网络）")
app.add_typer(zenodo_app, name="zenodo")


@zenodo_app.command("export")
def zenodo_export_cmd(
    citation: str = typer.Option(None, "--cff",
                                 help="CITATION.cff 路径（缺省=仓根）"),
    out: str = typer.Option(None, "--out",
                            help="元数据 JSON 落盘路径（缺省=只组装不落盘）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """CITATION.cff → Zenodo deposit 元数据（纯本地组装，零网络）。

    示例：rfauto zenodo export --out .zenodo.json
    """
    from rfauto.service.zenodo_service import export_zenodo_metadata

    result = export_zenodo_metadata(citation, out_path=out)
    _emit(result, "Zenodo 元数据导出失败", json_output=json_output)
    if not json_output and result.get("ok"):
        meta = result.get("metadata") or {}
        console.print(f"[green]✓ 元数据组装[/green] title={meta.get('title')!r} "
                      f"creators={len(meta.get('creators') or [])} "
                      f"written={result.get('written')}")
        if result.get("written"):
            console.print(f"  落盘 → [cyan]{result.get('out_path')}[/cyan]")
    raise typer.Exit(code=0)


@zenodo_app.command("validate")
def zenodo_validate_cmd(
    citation: str = typer.Option(None, "--cff",
                                 help="CITATION.cff 路径（缺省=仓根）"),
    pyproject: str = typer.Option(None, "--pyproject",
                                  help="对照 pyproject 路径（缺省=仓根）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """CITATION.cff 校验（必填字段+pyproject 版本同步；warnings 不判失败）。

    示例：rfauto zenodo validate
    """
    from rfauto.service.zenodo_service import validate_citation_metadata

    result = validate_citation_metadata(citation, pyproject_path=pyproject)
    _emit(result, "CITATION.cff 校验失败", json_output=json_output)
    if not json_output and result.get("ok"):
        console.print("[green]✓ CITATION.cff 校验通过[/green] "
                      f"checked={result.get('checked')}")
        for warn in result.get("warnings") or []:
            console.print(f"  [yellow]warning[/yellow] {warn}")
    raise typer.Exit(code=0)
