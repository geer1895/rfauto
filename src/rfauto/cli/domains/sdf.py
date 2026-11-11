"""sdf 子应用——SDF（IEEE 1497 标准延迟格式）时序标注结构化解析 CLI 薄壳
（aurora_q 席位 Q-X61，2026-11-07）。

零逻辑转发 service/sdf_service（Q-X61 单源；规则 4 薄壳）；S 表达式词法、
SDF 语义、TIMESCALE 换算与查询派生全在 core/sdf_parser 确定性内核（铁律 7）：
  rfauto sdf parse --file <path.sdf> [--json]
  rfauto sdf report --file <path.sdf> [--json]

parse 缺省紧凑输出（头部+统计+前 20 个 CELL 的非空桶计数）；report 缺省
紧凑输出（头部+逐 celltype 汇总+TIMINGCHECK 十二类计数与最坏值）；--json
恒全结构信封（成功/失败路径都走 print_json，#ge1㉙ 家法）。纯只读：不落
盘、零网络、零真机。

**注册形态说明（合流契约——citi/gdsii 域同款）**：本模块自带独立 typer
根 ``sdf_app``（**不**在模块级 add_typer 到共享 app——
tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli()==322 锚均为冻结面，Q-X61 禁改；先接线后重锚是主代理显式
评审动作）。合流接线两步：
  1. main.py 追加 re-export + add_typer（vendor_docs/citi/gdsii 同款）::
       from rfauto.cli.domains.sdf import sdf_app as sdf_app
       from rfauto.cli.domains._core import app as _sdf_reg_app  # noqa
       _sdf_reg_app.add_typer(sdf_app, name="sdf")
  2. 金快照重钉（+1 顶层 sdf、+2 叶；本席单独接线=322→324，与同批挂账
     叶 citi/gdsii/spef 合流时以 live count_cli() 实测为准）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
     并同步 test_check_numbers.py 的 CLI 锚。
本席测试经 ``sdf_app`` 直连（CliRunner），零共享 app 污染、零金快照漂移
（自证测试钉住 cli.main 不导入本域；顶层无同名 `sdf` 域——零撞名自查
2026-11-07：全 src 树零 sdf/SDF 引用；单源=core/sdf_parser+
service/sdf_service）。接线前 domain_survey V2 将本模块列为孤儿域模块
（citi/gdsii 挂账同态），第 1 步接线即清偿。
"""

from __future__ import annotations

from typing import Any

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

sdf_app = typer.Typer(
    help="SDF（IEEE 1497 标准延迟格式）时序标注解析：头部/CELL 段/"
         "IOPATH·INTERCONNECT·PORT 延迟+TIMINGCHECK 只读面")

#: parse 人读分支逐 CELL 行上限（全量走 --json）。
_MAX_CELL_LINES = 20


def _fmt(value: Any) -> str:
    """人读值格式（None 如实连字符；其余 escape 防 rich markup 误吞 ``[``）。"""
    return "-" if value is None else escape(str(value))


def _print_header(title: str, result: dict[str, Any]) -> None:
    header = result.get("header") or {}
    timescale = header.get("timescale") or {}
    console.print(
        f"[green]✓ {title}: {_fmt(result.get('path'))}[/green]"
        f"  version={_fmt(header.get('sdf_version'))}"
        f"  design={_fmt(header.get('design'))}"
        f"  timescale={_fmt(timescale.get('key'))}({_fmt(timescale.get('source'))})"
        f"  divider={_fmt(header.get('divider'))}")


def _print_warnings(result: dict[str, Any]) -> None:
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@sdf_app.command("parse")
def sdf_parse_cmd(
    file: str = typer.Option(..., "--file", help="SDF (.sdf) 文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 SDF 文件（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.sdf_service import parse_sdf_file  # lazy: 叶内延迟导入

    result = parse_sdf_file(str(file))
    _emit(result, "SDF 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    _print_header("SDF", result)
    console.print(
        f"  cells={stats.get('n_cells')}  celltypes={stats.get('n_celltypes')}"
        f"  top={stats.get('n_top_cells')}  wildcard={stats.get('n_wildcard_cells')}"
        f"  delays={stats.get('n_delay_entries')}"
        f"  timing_checks={stats.get('n_timing_checks')}"
        f"  unsupported={stats.get('n_unsupported')}"
        f"  warnings={stats.get('n_warnings')}")
    cells = result.get("cells") or []
    for cell in cells[:_MAX_CELL_LINES]:
        instance = "<top>" if cell.get("instance") is None else cell.get("instance")
        buckets = "  ".join(
            f"{kind}={len(entries)}"
            for kind, entries in (cell.get("delays") or {}).items() if entries)
        console.print(
            f"  [{cell.get('index')}] [bold]{_fmt(cell.get('celltype'))}[/bold]"
            f"  instance={_fmt(instance)}  {buckets or '(空)'}")
    if len(cells) > _MAX_CELL_LINES:
        console.print(
            f"  … 其余 {len(cells) - _MAX_CELL_LINES} 个 CELL（--json 看全量）")
    _print_warnings(result)


@sdf_app.command("report")
def sdf_report_cmd(
    file: str = typer.Option(..., "--file", help="SDF (.sdf) 文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """报告：头部+逐 celltype 计数+TIMINGCHECK 十二类计数与最坏值（只读）。"""
    from rfauto.service.sdf_service import sdf_report  # lazy: 叶内延迟导入

    result = sdf_report(str(file))
    _emit(result, "SDF 报告失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    _print_header("SDF 报告", result)
    console.print(
        f"  cells={stats.get('n_cells')}  celltypes={stats.get('n_celltypes')}"
        f"  delays={stats.get('n_delay_entries')}"
        f"  timing_checks={stats.get('n_timing_checks')}"
        f"  warnings={stats.get('n_warnings')}")
    for row in result.get("celltype_counts") or []:
        console.print(
            f"  [bold]{_fmt(row.get('celltype'))}[/bold]"
            f"  cells={row.get('n_cells')}  top={row.get('n_top')}"
            f"  wildcard={row.get('n_wildcard')}  instances={row.get('n_instances')}"
            f"  delays={row.get('n_delay_entries')}"
            f"  checks={row.get('n_timing_checks')}")
    summary = result.get("timing_check_summary") or {}
    console.print(f"  TIMINGCHECK 汇总: total={summary.get('n_timing_checks')}")
    by_type = summary.get("by_type") or {}
    for kind in summary.get("types_present") or []:
        body = by_type.get(kind) or {}
        where = body.get("worst_at") or {}
        console.print(
            f"    {kind}  count={body.get('count')}"
            f"  worst_max={_fmt(body.get('worst_max'))}"
            f"  worst_max_s={_fmt(body.get('worst_max_s'))}"
            f"  @ {_fmt(where.get('celltype'))}/{_fmt(where.get('instance'))}"
            f"  pin={_fmt(where.get('pin'))}")
    _print_warnings(result)
