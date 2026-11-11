"""skill 子应用——SKILL 代码模板生成 CLI 薄壳（T-Q27 席 Q-X32，aurora_q）。

零逻辑转发 service/skill_template_service（规则 4 薄壳；铁律 7：模板
渲染/lint 守卫全在 core/skill_template_engine 内核纯函数，本模块只搬运
信封与文件路径；零 Virtuoso 依赖零真机调用——产物 .il 由用户在本地
Virtuoso 加载执行）：

  rfauto skill list                                   [--json]
  rfauto skill render <template> [--var k=v ...]      [--out <path>] [--force] [--json]
  rfauto skill lint <file.il>                         [--json]

--var 值解析：先按 JSON 字面量（数字/bool/list）解析，失败回退原样
字符串（shell 引号面用户自理）；键名须为标识符。lint 有 error 级 issue
时退出码 1（CI 面裁定；warning 级不翻退出码）。

注册=域内自注册（anim/watchdog 同款：模块级 add_typer，main.py 只
re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
`skill` 域（#df6① 冲突检查 2026-11-07：全 CLI 树唯一近名 `recipe skill`
为组内叶语义=配方→SKILL.md agent 格式导出，非 Cadence SKILL 代码生成；
顶层命名空间零撞名）。
"""

from __future__ import annotations

import json as _json

import typer
from rich.markup import escape as _escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

skill_app = typer.Typer(
    help="SKILL 代码模板生成（Python→.il 脚手架；零 Virtuoso 依赖，"
         "执行侧在用户本地 Virtuoso）")
app.add_typer(skill_app, name="skill")


def _parse_var(spec: str, json_output: bool) -> tuple[str, object]:
    """``k=v`` → (键, 值)——值先按 JSON 字面量解析，失败回退原样字符串。

    解析形态错（无 '=' / 键非标识符）→ usage 错误退出码 2（#ge1㉙：
    --json 下失败路径必须输出 JSON 信封）。
    """
    key, sep, raw = spec.partition("=")
    key = key.strip()
    if not sep or not key.replace("_", "").isalnum() or key[0].isdigit():
        _emit_usage_error(
            f"--var 形态非法 {spec!r}（要求 k=v，k 为标识符）",
            json_output=json_output)
    try:
        return key, _json.loads(raw)
    except ValueError:
        return key, raw


@skill_app.command("list")
def skill_list_cmd(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """SKILL 模板目录（注册表只读视图：名称/分类/变量面/函数面）。"""
    from rfauto.service.skill_template_service import list_skill_templates  # lazy: run-path（Q-X36 补标注）

    result = list_skill_templates()
    _emit(result, "模板目录读取失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ SKILL 模板 {result['count']} 个[/green]")
    for t in result["templates"]:
        console.print(_escape(
            f"  {t['name']}  [{t['category']}]  {t['title']}"))
        console.print(_escape(
            f"    required: {t['required_vars']}"
            f"  optional: {t['optional_vars']}"))
        console.print(_escape(f"    {t['description']}"))
    raise typer.Exit(code=0)


@skill_app.command("render")
def skill_render_cmd(
    template: str = typer.Argument(..., help="模板名（rfauto skill list 查看）"),
    var: list[str] = typer.Option(  # noqa: B008
        [], "--var", help="模板变量 k=v（可多次；值按 JSON 字面量解析、"
        "失败回退原样字符串）"),
    out: str = typer.Option(
        "", "--out", help="落盘路径（缺省不落盘，代码走信封 skill_code/"
        "终端直出）"),
    force: bool = typer.Option(
        False, "--force", help="--out 已存在时覆写（防覆盖守卫缺省即红）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """渲染 SKILL 代码（模板+变量直出，零手拍电路数值；含语法守卫）。"""
    from rfauto.service.skill_template_service import render_skill_template  # lazy: run-path（Q-X36 补标注）

    variables: dict[str, object] = {}
    for spec in var:
        key, value = _parse_var(spec, json_output=json_output)
        variables[key] = value
    result = render_skill_template(
        template, variables, out_path=(out or None), overwrite=force)
    _emit(result, "SKILL 渲染失败", json_output=json_output)
    if json_output:
        return
    code = result.get("skill_code") or ""
    if result.get("file_path"):
        console.print(
            f"[green]✓ SKILL 渲染完成[/green]  template={template}"
            f"  sha256={str(result.get('sha256'))[:12]}")
        console.print(_escape(f"  文件: {result['file_path']}"))
    else:
        console.print(f"[green]✓ SKILL 渲染完成[/green]  template={template}")
        console.print(code, markup=False)
    lint = result.get("lint") or {}
    if lint.get("n_errors") or lint.get("n_warnings"):
        console.print(
            f"  lint: {lint.get('n_errors')} error / "
            f"{lint.get('n_warnings')} warning")
    for w in result.get("warnings") or []:
        console.print(f"  [yellow]- {_escape(str(w))}[/yellow]")
    raise typer.Exit(code=0)


@skill_app.command("lint")
def skill_lint_cmd(
    file: str = typer.Argument(..., help="SKILL .il 文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """SKILL 语法守卫（括号/引号/let 绑定/函数名白名单/赋值目标）；有
    error 级 issue 退出码 1。"""
    from pathlib import Path

    from rfauto.service.skill_template_service import lint_skill_code  # lazy: run-path（Q-X36 补标注）

    path = Path(file)
    if not path.is_file():
        _emit_usage_error(f"SKILL 文件不存在: {path}", json_output=json_output)
    try:
        code = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        from rfauto.service.envelope import error_envelope  # lazy: run-path（Q-X36 补标注）

        _emit(error_envelope([f"文件读取失败: {path}（{exc}）"]),
              "SKILL lint 失败", json_output=json_output)
    result = lint_skill_code(code)
    _emit(result, "SKILL lint 失败", json_output=json_output)
    if json_output:
        if result.get("n_errors"):
            raise typer.Exit(code=1)
        return
    n_err = result.get("n_errors") or 0
    n_warn = result.get("n_warnings") or 0
    if n_err or n_warn:
        console.print(
            f"[green]✓ lint 完成[/green]  {n_err} error / {n_warn} warning"
            f"  file={path}")
        for issue in result.get("issues") or []:
            sev = issue["severity"]
            color = "red" if sev == "error" else "yellow"
            console.print(
                f"  [{color}]{sev}[/{color}] L{issue['line']} "
                f"{issue['code']}: {_escape(str(issue['message']))}")
        if n_err:
            raise typer.Exit(code=1)
        raise typer.Exit(code=0)
    console.print(f"[green]✓ lint 通过（零 issue）[/green]  file={path}")
    raise typer.Exit(code=0)
