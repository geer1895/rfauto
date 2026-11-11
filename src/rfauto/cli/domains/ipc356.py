"""ipc356 子应用——IPC-D-356/356A 裸板电气测试网表 CLI 薄壳
（aurora_q 席位 Q-X65，2026-11-07）。

零逻辑转发 service/ipc356_service（Q-X65 单源；规则 4 薄壳）；356 词法、
坐标缩放与 net 拓扑全在 core/ipc356_parser 确定性内核（铁律 7）：
  rfauto ipc356 report --file <path.d356> [--json]
      [--check-gerber <path.gbr>] [--check-drill <path.drl>]

report 缺省紧凑输出（头部+统计+net 名录+单点 net 开路嫌疑清单）；配对
旗标（--check-gerber/--check-drill 至少其一）切换 pair check 形态（越界
焊盘列表+钻孔覆盖计数）；--json 恒全结构信封（成功/失败路径都走
print_json，#ge1㉙ 家法）。纯只读：不落盘、零网络、零真机。

**注册形态说明（合流契约——citi/gdsii/sdf 域同款）**：本模块自带独立
typer 根 ``ipc356_app``（**不**在模块级 add_typer 到共享 app——
tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli() 锚均为冻结面，Q-X65 禁改；先接线后重锚是主代理显式评审动
作）。合流接线两步：
  1. main.py 追加 re-export + add_typer（vendor_docs/citi/gdsii 同款）::
       from rfauto.cli.domains.ipc356 import ipc356_app as ipc356_app
       from rfauto.cli.domains._core import app as _ipc356_reg_app  # noqa
       _ipc356_reg_app.add_typer(ipc356_app, name="ipc356")
  2. 金快照重钉（+1 顶层 ipc356、+1 叶；与同批挂账叶 citi/gdsii/sdf/
     lefdef/spef 合流时以 live count_cli() 实测为准）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
     并同步 test_check_numbers.py 的 CLI 锚。
本席测试经 ``ipc356_app`` 直连（CliRunner），零共享 app 污染、零金快照
漂移（自证测试钉住 cli.main 不导入本域；顶层无同名 ``ipc356`` 域——
零撞名自查 2026-11-07：全 src 树零 ipc356/IPC-D-356 引用；单源=
core/ipc356_parser+service/ipc356_service）。接线前 domain_survey V2
将本模块列为孤儿域模块（citi/gdsii/sdf 挂账同态），第 1 步接线即清偿。
"""

from __future__ import annotations

from typing import Any

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

ipc356_app = typer.Typer(
    help="IPC-D-356/356A 裸板电气测试网表解析：头部/记录/net 测试点拓扑"
         "+统计+Gerber/Excellon 配对只读面")

#: parse 人读分支逐 net 行上限（全量走 --json）。
_MAX_NET_LINES = 20


def _fmt(value: Any) -> str:
    """人读值格式（None 如实连字符；escape 防 rich markup 误吞 ``[``）。"""
    return "-" if value is None else escape(str(value))


def _print_header(title: str, result: dict[str, Any]) -> None:
    console.print(
        f"[green]✓ {title}: {_fmt(result.get('path'))}[/green]"
        f"  version={_fmt(result.get('version'))}"
        f"  scale_factor={_fmt(result.get('scale_factor'))}"
        f"  user={_fmt(result.get('user_name'))}"
        f"  date={_fmt(result.get('date'))}")


def _print_warnings(result: dict[str, Any]) -> None:
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


def _print_report(result: dict[str, Any]) -> None:
    stats = result.get("stats") or {}
    _print_header("IPC-D-356 报告", result)
    console.print(
        f"  components={stats.get('n_components')}  pads={stats.get('n_pads')}"
        f"  vias={stats.get('n_vias')}  probes={stats.get('n_probes')}"
        f"  nets={stats.get('n_nets')}"
        f"  unassigned_pads={stats.get('n_unassigned_pads')}"
        f"  truncated={result.get('truncated')}")
    bbox = result.get("bbox_mm")
    if bbox is not None:
        console.print(
            f"  bbox_mm=[{bbox[0]}, {bbox[1]}] .. [{bbox[2]}, {bbox[3]}]")
    nets = result.get("nets") or []
    shown = nets[:_MAX_NET_LINES]
    if shown:
        console.print(f"  nets: {', '.join(shown)}"
                      + (f" …（其余 {len(nets) - len(shown)}，--json 看全量）"
                         if len(nets) > _MAX_NET_LINES else ""))
    single = result.get("single_point_nets") or []
    if single:
        console.print(
            f"  [yellow]单点 net（开路嫌疑）×{len(single)}: "
            f"{', '.join(single[:_MAX_NET_LINES])}[/yellow]")
    else:
        console.print("  单点 net（开路嫌疑）: 无")
    _print_warnings(result)


def _print_pair(result: dict[str, Any]) -> None:
    _print_header("IPC-D-356 配对校验", result)
    console.print(
        f"  pads={result.get('n_pads')}  known={result.get('n_pads_known')}"
        f"  gerber={_fmt(result.get('gerber_path'))}"
        f"  drill={_fmt(result.get('drill_path'))}")
    console.print(
        f"  越界焊盘={result.get('n_out_of_bounds')}"
        f"（skip={result.get('n_pads_skipped_bounds')}）"
        f"  钻孔覆盖={result.get('n_covered')}/{result.get('n_holes')}"
        f"（tol={_fmt(result.get('tol_mm'))}mm, skip={result.get('n_holes_skipped')}）")
    for row in result.get("out_of_bounds") or []:
        console.print(
            f"  [red]越界[/red] pad[{row.get('index')}] "
            f"{_fmt(row.get('net'))} {_fmt(row.get('refdes'))}-"
            f"{_fmt(row.get('pin'))}  axis={row.get('axis')}"
            f"  value={row.get('value_mm')}mm @ ({row.get('x_mm')}, {row.get('y_mm')})")
    for row in result.get("uncovered") or []:
        console.print(
            f"  [yellow]未覆盖[/yellow] hole[{row.get('index')}] "
            f"({_fmt(row.get('x_mm'))}, {_fmt(row.get('y_mm'))})"
            f"  最近焊盘={_fmt(row.get('nearest_pad_mm'))}mm"
            f" @ {_fmt(row.get('nearest_pad_xy'))}")
    for note in result.get("notes") or []:
        console.print(f"  [yellow]note: {escape(str(note))}[/yellow]")
    _print_warnings(result)


@ipc356_app.command("report")
def ipc356_report_cmd(
    file: str = typer.Option(..., "--file", help="IPC-D-356/356A (.d356/.356a) 文件路径"),
    check_gerber: str | None = typer.Option(
        None, "--check-gerber", help="配对校验：Gerber RS-274X 层文件路径（可选）"),
    check_drill: str | None = typer.Option(
        None, "--check-drill", help="配对校验：Excellon 钻孔文件路径（可选）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """报告：统计+单点 net 开路嫌疑清单；配对旗标切换 356×Gerber/Excellon
    只读校验（越界焊盘+钻孔覆盖）。"""
    from rfauto.service.ipc356_service import (  # lazy: 叶内延迟导入
        ipc356_fab_pair_check,
        ipc356_report,
    )

    if check_gerber is None and check_drill is None:
        result = ipc356_report(str(file))
        _emit(result, "IPC-D-356 报告失败", json_output=json_output)
        if json_output:
            return
        _print_report(result)
        return
    result = ipc356_fab_pair_check(
        str(file),
        str(check_gerber) if check_gerber is not None else None,
        str(check_drill) if check_drill is not None else None,
    )
    _emit(result, "IPC-D-356 配对校验失败", json_output=json_output)
    if json_output:
        return
    _print_pair(result)
