"""touchstone 子应用——Touchstone（.sNp）结构化解析 CLI 薄壳
（aurora_q 席位 Q-X64，2026-11-08）。

零逻辑转发 service/touchstone_service（Q-X64 单源；规则 4 薄壳）；格式
嗅探、rank 三规则推断、RI/MA/DB 三格式解码、频轴对齐与矩阵健康统计全在
core/touchstone_parser 确定性内核（铁律 7）：
  rfauto touchstone info --file <path.s2p> [--json]

info 缺省紧凑输出（格式四元组+端口 rank 共识+频段+三规则结果+冲突报告）；
--json 恒全结构信封（成功/失败路径都走 _emit print_json，#ge1㉙ 家法）。
纯只读：不落盘、零网络、零真机、run 湖零写入。

**注册形态说明（合流契约——citi/gdsii/sdf 域同款）**：本模块自带独立
typer 根 ``touchstone_app``（**不**在模块级 add_typer 到共享 app——
tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli()==322 锚均为冻结面，Q-X64 禁改；先接线后重锚是主代理显式
评审动作）。合流接线两步：
  1. main.py 追加 re-export + add_typer（citi/gdsii/sdf 同款）::
       from rfauto.cli.domains.touchstone import touchstone_app as touchstone_app
       from rfauto.cli.domains._core import app as _touchstone_reg_app  # noqa
       _touchstone_reg_app.add_typer(touchstone_app, name="touchstone")
  2. 金快照重钉（+1 顶层 touchstone、+1 叶；本席单独接线=322→323，与
     同批挂账叶 sdf/citi/gdsii 合流时以 live count_cli() 实测为准）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
     并同步 test_check_numbers.py 的 CLI 锚。
本席测试经 ``touchstone_app`` 直连（CliRunner），零共享 app 污染、零金
快照漂移（自证测试钉住 cli.main 不导入本域；顶层无同名 `touchstone`
域——零撞名自查 2026-11-08：全 src 树零 touchstone 域引用，diagnose 域
的 touchstone 形参名与本域无关；单源=core/touchstone_parser+
service/touchstone_service）。接线前 domain_survey V2 将本模块列为孤儿
域模块（citi/gdsii/sdf 挂账同态），第 1 步接线即清偿。
"""

from __future__ import annotations

from typing import Any

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

touchstone_app = typer.Typer(
    help="Touchstone（.sNp）结构化解析：格式嗅探/rank 三规则推断/"
         "RI·MA·DB 解码只读面")


@touchstone_app.callback()
def _touchstone_callback() -> None:
    """单叶域显式 callback——防 typer 单命令 app 被 flatten 成裸命令
    （直连 CliRunner 时 `info` 变多余参数；有 callback 恒为 Group）。"""


def _fmt(value: Any) -> str:
    """人读值格式（None 如实连字符；其余 escape 防 rich markup 误吞 ``[``）。"""
    return "-" if value is None else escape(str(value))


def _print_rank(rank: dict[str, Any]) -> None:
    """rank 三规则结果+冲突报告（人读分支）。"""
    rule_first = rank.get("rule_first_line") or {}
    rule_block = rank.get("rule_block") or {}
    console.print(
        f"  规则① 文件名: .s{_fmt(rank.get('rule_filename'))}p"
        f"（可信={_fmt(rank.get('rule_filename_trusted'))}）")
    console.print(
        f"  规则② 首行值数: {_fmt(rule_first.get('value_count'))}"
        f"  候选={_fmt(rule_first.get('candidates'))}")
    console.print(
        f"  规则③ 块结构: block={_fmt(rule_block.get('block'))}"
        f"  候选={_fmt(rule_block.get('candidates'))}")
    declared = rank.get("declared_keyword")
    if declared is not None:
        console.print(f"  v2.0 [Number of Ports] 声明: {_fmt(declared)}")
    console.print(
        f"  共识: n_ports={_fmt(rank.get('n_ports'))}"
        f"  resolution={_fmt(rank.get('resolution'))}")
    for item in rank.get("disagreements") or []:
        console.print(f"  [yellow]! 冲突: {escape(str(item))}[/yellow]")


@touchstone_app.command("info")
def touchstone_info_cmd(
    file: str = typer.Option(..., "--file", help="Touchstone (.sNp) 文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """格式嗅探+rank 三规则结果+冲突报告（缺省紧凑；--json 恒全结构信封）。"""
    from rfauto.service.touchstone_service import touchstone_info  # lazy: 叶内延迟导入

    result = touchstone_info(str(file))
    _emit(result, "Touchstone 解析失败", json_output=json_output)
    if json_output:
        return
    fmt = result.get("format") or {}
    console.print(
        f"[green]✓ Touchstone: {_fmt(result.get('path'))}[/green]"
        f"  version={_fmt(fmt.get('version'))}({_fmt(fmt.get('version_source'))})"
        f"  option={_fmt(fmt.get('option_line_raw'))}")
    console.print(
        f"  格式: freq_unit={_fmt(fmt.get('freq_unit'))}"
        f"  param={_fmt(fmt.get('param_type'))}"
        f"  data_format={_fmt(fmt.get('data_format'))}"
        f"  R={_fmt(fmt.get('r_ref'))}")
    console.print(
        f"  端口: n_ports={_fmt(result.get('n_ports'))}"
        f"  频点: {_fmt(result.get('n_freqs'))}"
        f"  频段: [{_fmt((result.get('band') or {}).get('f_min_hz'))},"
        f" {_fmt((result.get('band') or {}).get('f_max_hz'))}] Hz")
    _print_rank(result.get("rank") or {})
    if result.get("parse_error"):
        console.print(f"  [yellow]! 数据解析失败: "
                      f"{escape(str(result['parse_error']))}[/yellow]")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")
