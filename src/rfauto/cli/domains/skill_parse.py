"""skill_parse 子应用——SKILL/OCEAN 源码 S-expression 解析 CLI 薄壳
（aurora_q 席位 Q-X62，2026-11-08）。

零逻辑转发 service/skill_service（Q-X62 加性节三函数；规则 4 薄壳）；SKILL
词法（``;``/``/* */`` 注释、字符串转义、数字/符号/``|...|`` 转义符号）、
``f(`` 函数调用糖（f(x) ≡ (f x)，SKILL 读取器口径）、S 表达式栈式解析与
结构提取（define/defun 盘点/API 前缀桶/全局赋值面/静态调用边/受限字面量
求值）全在 core/skill_parser 确定性内核（铁律 7；只读静态分析，永不执行
被解析代码）：
  rfauto skill-parse parse --file <path.il> [--json]
  rfauto skill-parse report --file <path.il> [--json]

parse 缺省紧凑输出（顶层形态数/节点计数/定义名录）；report 缺省紧凑输出
（定义+重复+API 四桶+全局变量）。--json 恒全结构失败同构信封（成功/失败
路径都走 print_json，#ge1㉙ 家法）。纯只读：不落盘、零网络、零真机。
本域无 #277 三态开关面（仅 --json 单向旗标，无"缺省读配置/env"语义）；
路径参数一律 str 注解（B008 家法）；help 无裸 ``%``（#305 家法）。

**注册形态说明（合流契约——citi/gdsii/sdf 孤儿域同款）**：本模块自带独立
typer 根 ``skill_parse_app``（**不**在模块级 add_typer 到共享 app——
tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli()==322 锚均为冻结面，Q-X62 禁改；先接线后重锚是主代理显式评审
动作）。合流接线两步：
  1. main.py 追加 re-export + add_typer（vendor_docs/citi/gdsii/sdf 同款）::
       from rfauto.cli.domains.skill_parse import skill_parse_app as skill_parse_app
       from rfauto.cli.domains._core import app as _skill_parse_reg_app  # noqa
       _skill_parse_reg_app.add_typer(skill_parse_app, name="skill_parse")
     **顶层接线名必须≠"skill"**——零撞名自查（2026-11-08）：顶层 `skill`
     域已被 Q-X32 cli/domains/skill.py（SKILL 代码模板生成 list/render/
     lint，模块级 add_typer 已接线）占用，同顶名二次 add_typer 会双注册
     打红 zero-shadow 钉；故本域顶层名=skill_parse（``rfauto skill-parse
     parse …``）。备选形态（主代理评审裁量）：把本模块两叶迁入既有 skill
     域（cli/domains/skill.py 追加两个 @skill_app.command 叶 + 金快照
     +2 叶重钉），迁移后删除本模块并同步改 test_skill_parser.py 的导入根。
  2. 金快照重钉（+1 顶层 skill_parse、+2 叶 =322→325；与同批挂账叶
     citi/gdsii/sdf/spef 合流时以 live count_cli() 实测为准）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
     并同步 test_check_numbers.py 的 CLI 锚。
本席测试经 ``skill_parse_app`` 直连（CliRunner），零共享 app 污染、零金快
照漂移（自证测试钉住 cli.main 不导入本域；顶层无同名 `skill_parse` 域
——零撞名自查 2026-11-08：全 CLI 树近名仅 `skill`（Q-X32 域，语义=模板
生成，本域=源码解析，正交无撞）；单源=core/skill_parser+
service/skill_service Q-X62 节）。接线前 domain_survey 将本模块列为孤儿
域模块（citi/gdsii/sdf 挂账同态），第 1 步接线即清偿。
"""

from __future__ import annotations

from typing import Any

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

skill_parse_app = typer.Typer(
    help="SKILL/OCEAN 源码 S-expression 解析（只读静态面：define/defun "
         "盘点/API 前缀桶/全局赋值/静态调用图；零执行零 Virtuoso 依赖）")


def _fmt(value: Any) -> str:
    """人读值格式（None 如实连字符；escape 防 rich markup 误吞 ``[``）。"""
    return "-" if value is None else escape(str(value))


@skill_parse_app.command("parse")
def skill_parse_parse_cmd(
    file: str = typer.Option(..., "--file", help="SKILL/OCEAN 源文件路径"
                                             "（.il/.ocs 等纯文本）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 SKILL/OCEAN 文件（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.skill_service import parse_skill_file  # lazy: 叶内延迟导入

    result = parse_skill_file(str(file))
    _emit(result, "SKILL 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓ SKILL: {_fmt(result.get('path'))}[/green]"
        f"  schema={_fmt(result.get('schema'))}"
        f"  top={stats.get('n_top_level')}  nodes={stats.get('n_nodes')}"
        f"  lists={stats.get('n_lists')}  vectors={stats.get('n_vectors')}"
        f"  max_depth={stats.get('max_depth')}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@skill_parse_app.command("report")
def skill_parse_report_cmd(
    file: str = typer.Option(..., "--file", help="SKILL/OCEAN 源文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """报告：define/defun 盘点+API 前缀四桶+全局赋值面（只读静态分析）。"""
    from rfauto.service.skill_service import skill_report  # lazy: 叶内延迟导入

    result = skill_report(str(file))
    _emit(result, "SKILL 报告失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓ SKILL 报告: {_fmt(result.get('path'))}[/green]"
        f"  top={stats.get('n_top_level')}"
        f"  definitions={stats.get('n_definitions')}"
        f"  unique={stats.get('n_unique_names')}"
        f"  duplicates={stats.get('n_duplicates')}"
        f"  calls={stats.get('n_calls')}")
    for entry in result.get("definitions") or []:
        args = ",".join(entry.get("args") or [])
        console.print(
            f"  [bold]{_fmt(entry.get('name'))}[/bold]"
            f"  form={entry.get('form')}  style={entry.get('style')}"
            f"  arity={_fmt(entry.get('arity'))}"
            f"  args=({args})  line={entry.get('line')}"
            f"{'  [yellow]DUPLICATE[/yellow]' if entry.get('dup') else ''}")
    api = result.get("api") or {}
    by_bucket = api.get("by_bucket") or {}
    console.print(
        "  api 桶: " + "  ".join(
            f"{bucket}={by_bucket.get(bucket, 0)}"
            for bucket in (api.get("buckets")
                           or ("ocean", "virtuoso", "generic", "unknown"))))
    console.print(
        f"  全局赋值: {stats.get('n_globals')} 处 / 目标 "
        f"{stats.get('n_unique_targets')} 个: "
        f"{', '.join(result.get('targets') or []) or '-'}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")
