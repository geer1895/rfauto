"""odbpp 子应用——ODB++ 目录结构与制造库存 CLI 薄壳
（aurora_q 席位 Q-X68，2026-11-08）。

零逻辑转发 service/odbpp_service（Q-X68 单源；规则 4 薄壳）；matrix/
step/netlist 词法、net 库存与 stack 对齐全在 core/odbpp_parser 确定性
内核（铁律 7）：
  rfauto odbpp report --dir <odbpp目录> [--json]

report 缺省紧凑输出（matrix 层数+逐 step 统计+stack 对齐+悬空 pad/空
net 双清单）；--json 恒全结构信封（成功/失败路径都走 print_json，
#ge1㉙ 家法）。纯只读：不落盘、零网络、零真机。

**注册形态说明（合流契约——ipc356/citi/gdsii/sdf 域同款）**：本模块
自带独立 typer 根 ``odbpp_app``（**不**在模块级 add_typer 到共享
app——tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli() 锚均为冻结面，Q-X68 禁改；先接线后重锚是主代理显式评审动
作）。合流接线两步：
  1. main.py 追加 re-export + add_typer（ipc356/citi/gdsii 同款）::
       from rfauto.cli.domains.odbpp import odbpp_app as odbpp_app
       from rfauto.cli.domains._core import app as _odbpp_reg_app  # noqa
       _odbpp_reg_app.add_typer(odbpp_app, name="odbpp")
  2. 金快照重钉（+1 顶层 odbpp、+1 叶；与同批挂账叶 citi/gdsii/sdf/
     lefdef/touchstone/vcd/skill_parse 合流时以 live count_cli() 实测
     为准）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
     并同步 test_check_numbers.py 的 CLI 锚。
本席测试经 ``odbpp_app`` 直连（CliRunner），零共享 app 污染、零金快照
漂移（自证测试钉住 cli.main 不导入本域；顶层无同名 ``odbpp`` 域——
零撞名自查 2026-11-08：全 src 树零 odbpp_app 引用；既有 odbpp 字样面
=layout_interchange/format_overview（几何/速览面，非 CLI 域），单源=
core/odbpp_parser+service/odbpp_service）。接线前 domain_survey V2
将本模块列为孤儿域模块（ipc356/citi/gdsii/sdf 挂账同态），第 1 步接线
即清偿。
"""

from __future__ import annotations

from typing import Any

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

odbpp_app = typer.Typer(
    help="ODB++ 目录结构与制造库存解析：matrix 层清单/step 特征统计/"
         "cadnet 网表/net 库存（悬空 pad+空 net）/层叠对齐校验")

#: 逐 step 行上限（全量走 --json）。
_MAX_STEPS = 8


def _fmt(value: Any) -> str:
    """人读值格式（None 如实连字符；escape 防 rich markup 误吞 ``[``）。"""
    return "-" if value is None else escape(str(value))


def _print_report(result: dict[str, Any]) -> None:
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓ ODB++ 报告: {_fmt(result.get('root'))}[/green]"
        f"  matrix={_fmt(result.get('matrix_kind'))}"
        f"  units={_fmt(result.get('model_units'))}")
    console.print(
        f"  layers_declared={_fmt(result.get('n_layers_declared'))}"
        f"  layers_on_disk={_fmt(result.get('n_layers_on_disk'))}"
        f"  features={_fmt(stats.get('n_features_records'))}"
        f"  pad_refs={_fmt(stats.get('n_pad_refs'))}"
        f"  steps={_fmt(result.get('n_steps'))}")
    steps = result.get("steps") or []
    for step in steps[:_MAX_STEPS]:
        name = _fmt(step.get("name"))
        align = "对齐" if step.get("stack_aligned") else (
            f"缺失×{len(step.get('stack_missing') or [])}"
            f"/多余×{len(step.get('stack_extra') or [])}")
        console.print(
            f"  step {name}: layers={_fmt(step.get('n_layers_on_disk'))}"
            f"  features={_fmt(step.get('n_feature_records'))}"
            f"  pads={_fmt(step.get('n_pad_refs'))}"
            f"  nets={_fmt(step.get('n_nets'))}"
            f"  points={_fmt(step.get('n_net_points'))}"
            f"  stack=[{align}]")
    empty = result.get("empty_nets") or []
    if empty:
        console.print(
            f"  [yellow]空 net（零连接）×{len(empty)}: "
            f"{', '.join(str(n) for n in empty[:_MAX_STEPS])}[/yellow]")
    else:
        console.print("  空 net（零连接）: 无")
    dangling = result.get("dangling_pads") or []
    if dangling:
        console.print(
            f"  [yellow]悬空 pad 层×{len(dangling)}: "
            f"{', '.join(_fmt(d.get('layer')) for d in dangling[:_MAX_STEPS])}"
            "[/yellow]")
    else:
        console.print("  悬空 pad 层: 无")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@odbpp_app.command("report")
def odbpp_report_cmd(
    dir: str = typer.Option(..., "--dir", help="ODB++ 目录根（matrix/ 所在）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """报告：matrix 层清单+逐 step 统计+stack 对齐+悬空 pad/空 net 双清单。"""
    from rfauto.service.odbpp_service import odbpp_report  # lazy: 叶内延迟导入

    result = odbpp_report(str(dir))
    _emit(result, "ODB++ 报告失败", json_output=json_output)
    if json_output:
        return
    _print_report(result)
