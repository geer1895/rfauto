"""doctor 体检 + models 子应用（模型管理薄壳）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── doctor ───────────────────────────────────────────────────────────────────

@app.command()
def doctor(
    env: bool = typer.Option(False, "--env", help="改查 RFAUTO_* 环境变量体检表（QW-12 清单面，信息性报告恒 exit 0）"),
    extras: bool = typer.Option(False, "--extras", help="改查可选依赖组安装状态+场景速查（UX-A1，信息性报告恒 exit 0）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """环境探测：AEDT/ADS 版本、license、路径、已测试版本组合核对。

    退出码：0=就绪；非0=缺项（CI/脚本可直接判断）；--env/--extras 信息性
    报告恒 0（extras 未装是正常态非问题态）。
    """
    if extras:
        from rfauto.service.env_service import doctor_extras as _doctor_extras
        result = _doctor_extras()
        if json_output:
            # VI-5 W6-B：--json 信封（信息性报告，退出码恒 0 语义保持）
            console.print_json(json.dumps(result, ensure_ascii=False, default=str))
            return
        table = Table(title="rfauto doctor --extras（可选依赖组，UX-A1）", show_lines=False)
        table.add_column("组", style="cyan")
        table.add_column("安装")
        table.add_column("缺")
        for g in result["groups"]:
            state = f"{g['n_installed']}/{g['n_reqs']}"
            style = "green" if not g["missing"] else "yellow"
            table.add_row(g["name"], f"[{style}]{state}[/{style}]", ", ".join(g["missing"]))
        console.print(table)
        console.print("\n[bold]场景速查[/bold]（ready=该场景组全装）：")
        for sc in result["scenes"]:
            mark = "[green]ready[/green]" if sc["ready"] else "[yellow]partial[/yellow]"
            console.print(f"  {sc['scene']}: {mark}  ← {', '.join(sc['groups'])}")
        summary = result["summary"]
        console.print(
            f"\n共 {summary['n_groups']} 组，全装 {summary['fully_installed']}；"
            "未装属正常态（按场景需要安装，见 pyproject.toml 注释）"
        )
        return
    if env:
        from rfauto.service.env_service import doctor_env as _doctor_env
        result = _doctor_env()
        if json_output:
            # VI-5 W6-B：--json 信封（信息性报告，退出码恒 0 语义保持）
            console.print_json(json.dumps(result, ensure_ascii=False, default=str))
            return
        table = Table(title="rfauto doctor --env（RFAUTO_* 环境变量）", show_lines=False)
        table.add_column("变量", style="cyan")
        table.add_column("类别")
        table.add_column("状态", style="bold")
        table.add_column("说明")
        for check in result["checks"]:
            state = str(check["state"])
            style = {"ok": "green", "missing": "red", "set": "green", "default": "yellow"}.get(state, "white")
            table.add_row(
                str(check["name"]),
                str(check["category"]),
                f"[{style}]{state}[/{style}]",
                f"{check['purpose']}｜{check['detail']}",
            )
        console.print(table)
        summary = result["summary"]
        console.print(
            f"\n共 {summary['total']} 项：set={summary['set']} "
            f"missing={summary['missing']} default={summary['default']}"
        )
        if summary["missing"]:
            console.print("[red]存在设了但路径不存在的变量（见 missing 行）。[/red]")
        return

    from rfauto.service.api import doctor as _doctor
    result = _doctor()

    if json_output:
        # VI-5 W6-B：--json 信封（缺项退出码 1 语义保持——逐 check status 判）
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
        if any(c.get("status") != "ok" for c in result.get("checks", [])):
            raise typer.Exit(code=1)
        return

    table = Table(title="rfauto doctor", show_lines=True)
    table.add_column("检查项", style="cyan")
    table.add_column("状态", style="bold")
    table.add_column("详情")

    checks = result.get("checks", [])
    all_ok = True
    for check in checks:
        name = check.get("name", "")
        status = check.get("status", "unknown")
        detail = check.get("detail", "")
        style = "green" if status == "ok" else "red"
        if status != "ok":
            all_ok = False
        table.add_row(name, f"[{style}]{status}[/{style}]", detail)

    console.print(table)

    if not all_ok:
        console.print("\n[red]部分检查未通过，请修复后重试。[/red]")
        raise typer.Exit(code=1)
    else:
        console.print("\n[green]环境就绪！[/green]")


# ─── models ───────────────────────────────────────────────────────────────────

models_app = typer.Typer(help="模型管理")
app.add_typer(models_app, name="models")


@models_app.command("list")
def models_list(
    schema: str = typer.Option(None, "--schema", "-s", help="导出指定模型的 JSON Schema"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """列出已注册模板 + 可选导出参数 JSON Schema。"""
    from rfauto.service.api import list_models as _list_models
    result = _list_models()

    if schema:
        from rfauto.models.registry import export_schema
        try:
            s = export_schema(schema)
        except KeyError:
            if json_output:
                # VI-5 W6-B：未知模型也信封（--json 下失败路径不许非 JSON）
                _emit({"ok": False, "errors": [f"未知模型: {schema}"]},
                      "未知模型", json_output=True)
            console.print(f"[red]未知模型: {schema}[/red]")
            raise typer.Exit(code=1) from None
        console.print_json(json.dumps(s, indent=2, ensure_ascii=False))
        return
    if json_output:
        # VI-5 W6-B：--json 信封（清单面）
        console.print_json(json.dumps(
            {"ok": True, "models": result.get("models", [])},
            ensure_ascii=False, default=str))
        return
    table = Table(title="已注册模型")
    table.add_column("模型名", style="cyan")
    for name in result.get("models", []):
        table.add_row(name)
    console.print(table)


@models_app.command("docs")
def models_docs(
    model: str = typer.Argument(None, help="模型名（不填则生成全部已注册模型）"),
    output: str = typer.Option(None, "--output", "-o", help="输出目录（默认 docs/models）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """生成模型参数文档（Markdown，pydantic schema 自动推导）。"""
    from rfauto.service.model_docs import generate_all_model_docs, generate_model_docs

    out_dir = output or "docs/models"
    if model:
        try:
            doc = generate_model_docs(model, out_dir)
        except KeyError:
            if json_output:
                # VI-5 W6-B：未知模型也信封（--json 下失败路径不许非 JSON）
                _emit({"ok": False, "errors": [f"未知模型: {model}"]},
                      "文档生成失败", json_output=True)
            console.print(f"[red]未知模型: {model}[/red]")
            raise typer.Exit(code=1) from None
        path = Path(out_dir) / f"{model}.md"
        if json_output:
            # VI-5 W6-B：--json 信封（落盘副作用保持，路径/行数并入信封）
            console.print_json(json.dumps(
                {"ok": True, "model": model, "path": str(path),
                 "n_lines": len(doc.splitlines())},
                ensure_ascii=False, default=str))
            return
        console.print(f"[green]✓ 文档已生成[/green]  {path}（{len(doc.splitlines())} 行）")
        return

    results = generate_all_model_docs(out_dir)
    if json_output:
        # VI-5 W6-B：--json 信封（全量生成；单模型 Error 逐名如实透传）
        console.print_json(json.dumps(
            {"ok": True, "out_dir": out_dir,
             "docs": {name: str(Path(out_dir) / (name + ".md")) for name in results}},
            ensure_ascii=False, default=str))
        return
    for name, doc in results.items():
        flag = "[green]✓[/green]" if not doc.startswith("Error") else "[red]✗[/red]"
        console.print(f"  {flag} {name}: {Path(out_dir) / (name + '.md')}")
