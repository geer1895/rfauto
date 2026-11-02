"""recast 子应用（RECAST 判据重放 CLI 出口，2026-10-11 aurora36 W2-D）——
status/replay 两只读叶。

零逻辑转发 service/recast_service（规则 4 薄壳；重放数值全部在
core.recast 确定性内核，铁律 7——本模块零物理数值）：
  rfauto recast status
  rfauto recast status --criteria-dir knowledge/criteria/v2
  rfauto recast replay -a runs/df5_c3fix/sentinel_verdict.json
  rfauto recast replay -a verdict.json --evidence-path df6_dp10_scan=four_gates.span_db
  rfauto recast replay -a verdict.json --archived-verdict-path none

registration：域内自注册 add_typer（stats/firmware/edb 同款惯例，
main.py 只 re-export 不二次注册）；顶层无同名 ``recast`` 命令（#df6①
冲突检查 2026-10-11：全 CLI 树零撞名）。全叶带 ``--json``（W2-C 棘轮
门惯例）。教程互链：docs/tutorials/recast-walkthrough.md。
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console
from rfauto.service.recast_service import DEFAULT_CRITERIA_DIR

recast_app = typer.Typer(help="RECAST 判据重放（归档判读×现行判据确定性复算，只读）")
app.add_typer(recast_app, name="recast")

#: 三向标注的终端配色（same 绿 / flip 红 / not_judged 黄——flip 必显眼）
_DIRECTION_STYLES = {"same": "green", "flip": "bold red",
                     "not_judged": "yellow"}


def _parse_evidence_paths(items: list[str] | None, *,
                          json_output: bool = False) -> dict[str, str]:
    """--evidence-path criteria_id=点路径（可多次）→ dict；非法形态报错。

    非法形态经 ``_emit_usage_error``（#ge1㉙：--json 下输出 JSON 信封，
    A5 P1-1 收编）。"""
    out: dict[str, str] = {}
    for item in items or []:
        key, sep, raw = item.partition("=")
        if not sep or not key.strip() or not raw.strip():
            _emit_usage_error(f"--evidence-path 需要 criteria_id=点路径 "
                              f"形态: {item}", json_output=json_output)
        out[key.strip()] = raw.strip()
    return out


def _artifact_paths(items: list[str] | None) -> dict[str, str]:
    """--artifact 文件路径（可多次）→ {重放名: 路径}；重放名=文件主干，
    同名主干按出现序追加序号消歧。"""
    out: dict[str, str] = {}
    for item in items or []:
        p = Path(item)
        name = p.stem
        if name in out:
            name = f"{name}#{len([k for k in out if k.startswith(name)])}"
        out[name] = str(p)
    return out


@recast_app.command("status")
def recast_status_cmd(
    criteria_dir: str = typer.Option(
        DEFAULT_CRITERIA_DIR, "--criteria-dir",
        help="判据目录（criteria/v2 schema YAML 集；缺省仓内注册源）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """判据注册面清单（每条 id/规则形态/装载状态；坏条目如实登记）。"""
    from rfauto.service.recast_service import recast_status as _status

    result = _status(criteria_dir)
    _emit(result, "判据目录装载失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ 判据 {result['n_criteria_ok']}/"
                  f"{result['n_criteria']} 条装载合格[/green] "
                  f"← {result['criteria_dir']}")
    table = Table(title="criteria/v2 注册面")
    for col in ("criteria_id", "form", "ok", "errors"):
        table.add_column(col, style="cyan" if col == "criteria_id" else None)
    for c in result.get("criteria") or []:
        table.add_row(
            str(c.get("criteria_id") or c.get("name") or ""),
            str(c.get("decision_rule_form") or ""),
            "✓" if c.get("ok") else "✗",
            "; ".join(c.get("errors") or []))
    console.print(table)


@recast_app.command("replay")
def recast_replay_cmd(
    artifact: list[str] = typer.Option(  # noqa: B008
        None, "--artifact", "-a",
        help="归档证据 JSON 文件路径（可多次；重放名=文件主干；只读）"),
    criteria_dir: str = typer.Option(
        DEFAULT_CRITERIA_DIR, "--criteria-dir",
        help="判据目录（criteria/v2 schema YAML 集）"),
    evidence_path: list[str] = typer.Option(  # noqa: B008
        None, "--evidence-path",
        help="threshold_gate 判据的证据绑定 criteria_id=点路径（可多次）"),
    archived_verdict_path: str = typer.Option(
        "verdict", "--archived-verdict-path",
        help="归档 verdict 在证据 JSON 内的点路径；传 none 表示不比归档侧"
             "（方向恒 not_judged）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """批量重放（全部已注册判据×全部证据，三向标注 same/flip/not_judged）。"""
    from rfauto.service.recast_service import recast_replay as _replay

    arch = archived_verdict_path.strip()
    result = _replay(
        _artifact_paths(artifact),
        criteria_dir=criteria_dir,
        evidence_paths=_parse_evidence_paths(evidence_path,
                                             json_output=json_output),
        archived_verdict_path=None if arch.lower() == "none" else arch,
    )
    _emit(result, "重放失败", json_output=json_output)
    if json_output:
        return
    summary = result.get("summary") or {}
    console.print(f"[green]✓ 重放完成[/green] 对数={summary.get('n_pairs')} "
                  f"判据={summary.get('n_criteria')}"
                  f"（坏 {summary.get('n_criteria_error')}）")
    for w in result.get("warnings") or []:
        console.print(f"[yellow]! {w}[/yellow]")
    console.print(f"  same={summary.get('n_same')} "
                  f"flip={summary.get('n_flip')} "
                  f"not_judged={summary.get('n_not_judged')}")
    flips = [p for p in result.get("pairs") or []
             if p.get("direction") == "flip"]
    if flips:
        console.print("[bold red]  flip（翻案必须显式浮出——人工仲裁复查，"
                      "不改归档）:[/bold red]")
        for p in flips:
            console.print(
                f"    [bold red]{p.get('artifact')} × {p.get('criteria_id')}"
                f": 归档 {p.get('archived_verdict')!r} vs 重放 "
                f"{p.get('replay_verdict')!r}[/bold red]")
    nj = [p for p in result.get("pairs") or []
          if p.get("direction") == "not_judged"]
    if nj:
        console.print(f"[yellow]  not_judged {len(nj)} 对（证据缺失/非机器"
                      "直放——如实不判，明细见 --json）[/yellow]")


# help 渲染安全（#305/#146 家族）：子应用描述与两叶 docstring 禁含裸 % 与
# 方括号（edb.py 同款导入期 assert 钉子应用描述；叶面由 help 卫生常驻门覆盖）。
assert "%" not in (recast_app.info.help or "")
assert "[" not in (recast_app.info.help or "")
