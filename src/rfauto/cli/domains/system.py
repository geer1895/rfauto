"""doctor 体检 + models 子应用（模型管理薄壳）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console
from rfauto.service.envelope import error_envelope, ok_envelope

# ─── doctor ───────────────────────────────────────────────────────────────────

@app.command()
def doctor(
    env: bool = typer.Option(False, "--env", help="改查 RFAUTO_* 环境变量体检表（QW-12 清单面，信息性报告恒 exit 0）"),
    extras: bool = typer.Option(False, "--extras", help="改查可选依赖组安装状态+场景速查（UX-A1，信息性报告恒 exit 0）"),
    janitor: bool = typer.Option(False, "--janitor", help="改查资源卫生面板：ansysedt 族进程（含父进程链证据，疑似孤儿仅标记）+ 工作根内 AEDT 工程锁（只扫描不动手）"),
    janitor_clean: bool = typer.Option(False, "--janitor-clean", help="随 --janitor 扫描执行清理：击杀疑似孤儿进程+删除 AEDT 工程锁（不给本旗标绝不动手；须与 --janitor 同用）"),
    min_free_gb: float = typer.Option(None, "--min-free-gb", help="内存闸：系统可用内存低于该 GB 数时判定不放行（可脱离 --janitor 单独使用）"),
    enforce: bool = typer.Option(False, "--enforce", help="与 --min-free-gb 同用：闸不放行时以非 0 退出码结束（供脚本判断）；无 --min-free-gb 时忽略"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """环境探测：AEDT/ADS 版本、license、路径、已测试版本组合核对。

    退出码：0=就绪；非0=缺项（CI/脚本可直接判断）；--env/--extras 信息性
    报告恒 0（extras 未装是正常态非问题态）；--janitor/--min-free-gb 信息性
    恒 0，仅 --enforce 且内存闸不放行时非 0。
    """
    if janitor_clean and not janitor:
        _emit_usage_error("--janitor-clean 需与 --janitor 同用（先扫描盘点、后动手清理）",
                          json_output=json_output)
    if janitor or min_free_gb is not None:
        from rfauto.service import resource_janitor_service as _rj

        scan_result: dict[str, Any] | None = None
        clean_result: dict[str, Any] | None = None
        if janitor:
            try:
                scan_result = _rj.janitor_scan()
            except Exception as exc:  # --json 下失败路径也要信封（#105 主路径不炸）
                scan_result = error_envelope(f"资源卫生扫描失败: {exc}")
            if janitor_clean:
                if scan_result.get("ok"):
                    kill_pids = sorted(p["pid"] for p in scan_result.get("processes", []) if p.get("suspect"))
                    lock_paths = [str(lk["path"]) for lk in scan_result.get("locks", [])]
                    try:
                        clean_result = _rj.janitor_clean(kill_pids=kill_pids, locks=lock_paths, dry_run=False)
                    except Exception as exc:
                        clean_result = error_envelope(f"资源卫生清理失败: {exc}")
                else:
                    clean_result = error_envelope("扫描未成功，跳过清理（先看 scan.errors）")
        gate_result = _rj.memory_gate(min_free_gb) if min_free_gb is not None else None

        payload = ok_envelope()
        if scan_result is not None:
            payload["scan"] = scan_result
        if clean_result is not None:
            payload["clean"] = clean_result
        if gate_result is not None:
            payload["memory_gate"] = gate_result

        if json_output:
            console.print_json(json.dumps(payload, ensure_ascii=False, default=str))
        else:
            _print_janitor_report(scan_result, clean_result, gate_result)

        if enforce and gate_result is not None and not gate_result.get("ok"):
            raise typer.Exit(code=1)
        return

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


def _print_janitor_report(
    scan_result: dict[str, Any] | None,
    clean_result: dict[str, Any] | None,
    gate_result: dict[str, Any] | None,
) -> None:
    """doctor 资源卫生分支的人类可读渲染（--json 走信封直出，不经此）。"""
    if scan_result is not None:
        if not scan_result.get("ok"):
            console.print("[red]资源卫生扫描失败：[/red]")
            for err in scan_result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
        else:
            s = scan_result["summary"]
            console.print(
                f"\n[bold]进程清点[/bold]（通道: {s['process_channel']}）："
                f"ansysedt 族共 {s['n_processes']} 个，疑似孤儿 {s['n_suspect']} 个，"
                f"合计内存 {s['total_rss_gb']:.2f} GB"
            )
            if scan_result["processes"]:
                table = Table(title="ansysedt 族进程（疑似=启发式证据，是否击杀自行判断）", show_lines=False)
                table.add_column("PID", style="cyan")
                table.add_column("名称")
                table.add_column("内存GB")
                table.add_column("启动时间")
                table.add_column("父进程")
                table.add_column("疑似", style="bold")
                for p in scan_result["processes"]:
                    parent_cell = f"{p['ppid']}（{p['parent_name']}）" if p["parent_alive"] else "已退出"
                    suspect_cell = "[red]疑似孤儿[/red]" if p["suspect"] else "否"
                    rss_cell = f"{p['rss_gb']:.2f}" if p["rss_gb"] is not None else "?"
                    table.add_row(
                        str(p["pid"]), str(p["name"]), rss_cell,
                        str(p["create_time"] or "?"), parent_cell, suspect_cell,
                    )
                console.print(table)
            else:
                console.print("  （无 ansysedt 族进程）")
            console.print(
                f"\n[bold]AEDT 工程锁[/bold]（扫描根: {', '.join(s['scan_roots'])}）："
                f"共 {s['n_locks']} 处{'（已达上限截断）' if s['locks_truncated'] else ''}"
            )
            for lock in scan_result["locks"]:
                kind = "目录" if lock["is_dir"] else "文件"
                console.print(f"  - {lock['path']}（{kind}，工程伴生={lock['paired_project']}）")
            console.print("[dim]清理姿势：复核上表后加 --janitor-clean 执行（只动疑似孤儿与上列锁）。[/dim]")
    if clean_result is not None:
        if not clean_result.get("ok"):
            console.print("[red]清理被拒绝（白名单外入参整单拒绝，零副作用）：[/red]")
            for err in clean_result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
        else:
            cs = clean_result["summary"]
            console.print(
                f"\n[bold]清理结果[/bold]：动作 {cs['n_actions']} 项，"
                f"击杀 {cs['n_killed']}，删锁 {cs['n_lock_removed']}，"
                f"先消失 {cs['n_already_gone']}，失败 {cs['n_failed']}"
            )
            for a in clean_result["actions"]:
                mark = "[green]✓[/green]" if a["result"] in {"killed", "removed"} else (
                    "[yellow]~[/yellow]" if str(a["result"]).startswith(("would_", "already", "skipped")) else "[red]✗[/red]"
                )
                target = a.get("pid", a.get("path", "?"))
                detail = f"—— {a['detail']}" if a.get("detail") else ""
                console.print(f"  {mark} [{a['kind']}] {target}: {a['result']}{detail}")
    if gate_result is not None:
        style = "green" if gate_result.get("ok") else "red"
        console.print(f"\n[bold]内存闸[/bold]：[{style}]{gate_result.get('message', '')}[/{style}]")


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
        # T8 越级收口（aurora_g W11-S3）：schema 导出经 service 单源
        # （template_spec_service.export_model_schema，KeyError→失败信封
        # 同构翻译）；cli 零逻辑直渲染，输出逐字节不变。
        from rfauto.service.template_spec_service import export_model_schema
        result_schema = export_model_schema(schema)
        if not result_schema.get("ok"):
            if json_output:
                # VI-5 W6-B：未知模型也信封（--json 下失败路径不许非 JSON）
                _emit(result_schema, "未知模型", json_output=True)
            console.print(f"[red]未知模型: {schema}[/red]")
            raise typer.Exit(code=1) from None
        console.print_json(json.dumps(result_schema["schema"], indent=2, ensure_ascii=False))
        return
    if json_output:
        # VI-5 W6-B：--json 信封（清单面）
        console.print_json(json.dumps(
            ok_envelope(models=result.get("models", [])),
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
                _emit(error_envelope(f"未知模型: {model}"),
                      "文档生成失败", json_output=True)
            console.print(f"[red]未知模型: {model}[/red]")
            raise typer.Exit(code=1) from None
        path = Path(out_dir) / f"{model}.md"
        if json_output:
            # VI-5 W6-B：--json 信封（落盘副作用保持，路径/行数并入信封）
            console.print_json(json.dumps(
                ok_envelope(model=model, path=str(path),
                            n_lines=len(doc.splitlines())),
                ensure_ascii=False, default=str))
            return
        console.print(f"[green]✓ 文档已生成[/green]  {path}（{len(doc.splitlines())} 行）")
        return

    results = generate_all_model_docs(out_dir)
    if json_output:
        # VI-5 W6-B：--json 信封（全量生成；单模型 Error 逐名如实透传）
        console.print_json(json.dumps(
            ok_envelope(
                out_dir=out_dir,
                docs={name: str(Path(out_dir) / (name + ".md")) for name in results}),
            ensure_ascii=False, default=str))
        return
    for name, doc in results.items():
        flag = "[green]✓[/green]" if not doc.startswith("Error") else "[red]✗[/red]"
        console.print(f"  {flag} {name}: {Path(out_dir) / (name + '.md')}")
