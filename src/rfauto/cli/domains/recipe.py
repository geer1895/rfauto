"""recipe 子应用 + repro 三命令（配方迁移/技能/复现）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from pathlib import Path

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── recipe（方向 7：配方版本管理）──────────────────────────────────────────────

recipe_app = typer.Typer(help="配方版本管理（方向 7）")
app.add_typer(recipe_app, name="recipe")


@recipe_app.command("migrate")
def recipe_migrate_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """迁移配方到当前版本（添加 recipe_version 字段）。

    方向 7 可复现基建：确保所有配方有版本标记，支持后续 schema 演进。
    """
    from rfauto.service.api import recipe_migrate

    result = recipe_migrate(recipe)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "迁移失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 迁移失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    if result.get("changed"):
        console.print(f"[green]✓ {result['message']}[/green]")
        console.print(f"  配方: {result['recipe_path']}")
        console.print(f"  版本: v{result['from_version']} → v{result['to_version']}")
    else:
        console.print(f"[cyan]{result['message']}[/cyan]")


@recipe_app.command("skill")
def recipe_skill_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    output: str = typer.Option(None, "--output", "-o", help="输出目录（默认与配方同目录）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """配方 → agent skill（SKILL.md + frontmatter，阶段 2.4）。"""
    from rfauto.service.skill_service import write_skill

    result = write_skill(recipe, output_dir=output)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "生成失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 生成失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]✓ SKILL.md 已生成[/green]")
    console.print(f"  skill: {result['skill_name']}")
    console.print(f"  参数: {result['n_params']} 个 / 目标: {result['n_objectives']} 项")
    console.print(f"  路径: {result['output_path']}")


# ─── repro（方向 7：可复现包导出）──────────────────────────────────────────────

@app.command("repro")
def repro_cmd(
    run_id: str = typer.Argument(..., help="run_id"),
    output: str = typer.Option(None, "--output", "-o", help="输出目录（默认 runs/repro）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """导出可复现包（配方快照 + 求解器输入 + S 参数 + reproduce.py）。

    方向 7 验收口径：任一历史 run 的 repro 包在干净 venv 中可重建并跑通 fake 档。
    """
    from rfauto.service.api import repro_export

    result = repro_export(run_id, output_dir=output)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "导出失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 导出失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]✓ {result['message']}[/green]")
    console.print(f"  文件清单 ({len(result['files'])} 个):")
    for f in result["files"]:
        console.print(f"    {f}")
    console.print(f"  复现命令: python {result['output_dir']}/reproduce.py")


# ─── repro manifest / verify（ME-17b 后半：复现清单组装+校验薄壳）──────────────
# 零逻辑转发 service/reproducibility_service（规则 4，JSON 进出走 service）；
# 路径参数 str 注解（#269 B008）。与上方 `repro`（可复现包导出）互补：
# repro=包导出链，repro-manifest/verify=环境+产物清单的独立校验链。


@app.command("repro-manifest")
def repro_manifest_cmd(
    target: str = typer.Argument(None, help="产物目标目录（可选；缺省只组环境段）"),
    out: str = typer.Option(None, "--out", "-o",
                            help="清单落盘路径（缺省 runs/repro_manifest.json）"),
    ignore: list[str] = typer.Option(None, "--ignore",  # noqa: B008
                                     help="产物段忽略 glob（可多次）"),
    no_git: bool = typer.Option(False, "--no-git", help="跳过 git 段（非仓环境）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """组装复现清单（环境段+可选产物段）并落盘（reproducibility_service）。"""
    from rfauto.service.reproducibility_service import (
        build_reproducibility_manifest,
        write_manifest,
    )

    out_path = out if out is not None else str(Path("runs") / "repro_manifest.json")
    manifest = build_reproducibility_manifest(
        target if target else None,
        ignore=tuple(ignore) if ignore else (),
        include_git=not no_git,
    )
    result = write_manifest(manifest, out_path)
    if not manifest.get("ok"):
        _emit(manifest, "复现清单组装未通过", json_output=json_output)
        return
    _emit(result, "复现清单落盘失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ manifest={result['path']}[/green]  "
                  f"digest={result['digest'][:16]}…")
    if target:
        n_files = len((manifest.get("artifacts") or {}).get("files") or {})
        console.print(f"  artifacts: {n_files} 文件  target={target}")


@app.command("repro-verify")
def repro_verify_cmd(
    manifest_path: str = typer.Argument(..., help="清单 JSON 路径"),
    target: str = typer.Argument(None, help="产物目标目录（清单含 artifacts 段时必填）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """校验复现清单（产物三态差异+环境 packages/lock 差异，如实报告）。"""
    from rfauto.service.reproducibility_service import (
        read_manifest,
        verify_reproducibility_manifest,
    )

    manifest_env = read_manifest(manifest_path)
    if not manifest_env.get("ok"):
        _emit(manifest_env, "清单读取失败", json_output=json_output)
        return
    result = verify_reproducibility_manifest(
        manifest_env["manifest"], target if target else None)
    if not result.get("ok"):
        # 程序性 errors + 三态差异并入错误面（verify 的差异在 artifacts/
        # environment 子报告里，不并会被 _emit 静默吞掉只剩空 exit 1）
        errs = [str(e) for e in result.get("errors") or []]
        art = result.get("artifacts") or {}
        errs += [f"missing: {p}" for p in art.get("missing") or []]
        errs += [f"changed: {p}" for p in art.get("changed") or []]
        errs += [f"extra: {p}" for p in art.get("extra") or []]
        env = result.get("environment") or {}
        errs += [f"environment: {e}" for e in env.get("errors") or []]
        _emit({"ok": False, "errors": errs},
              "复现清单校验未通过", json_output=json_output)
        return
    _emit(result, "复现清单校验未通过", json_output=json_output)
    if json_output:
        return
    art = result.get("artifacts") or {}
    env = result.get("environment") or {}
    console.print(
        f"artifacts: ok={art.get('ok')}  "
        f"missing={len(art.get('missing') or [])} "
        f"changed={len(art.get('changed') or [])} "
        f"extra={len(art.get('extra') or [])}")
    console.print(f"environment: ok={env.get('ok')}")
    for err in result.get("errors") or []:
        console.print(f"  [yellow]- {err}[/yellow]")


@recipe_app.command("diff")
def recipe_diff_cmd(
    recipe_a: str = typer.Argument(..., help="配方/声明 A（YAML 或 JSON 文件路径）"),
    recipe_b: str = typer.Argument(..., help="配方/声明 B（YAML 或 JSON 文件路径）"),
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """两版配方/设计声明的逐键差异（SN-15；数值键带相对变化，铁律 7 零新数值）。

    业务本体 = service/design_diff_service.design_version_diff_from_files
    （方向 7 版本管理的自然续：migrate 之后，diff 是共享面的读半边）。
    """
    from rfauto.service.design_diff_service import (
        design_version_diff_from_files,
        render_design_diff_markdown,
    )

    result = design_version_diff_from_files(recipe_a, recipe_b)
    if json_output:
        _emit(result, "配方 diff 失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 配方 diff 失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print(render_design_diff_markdown(result), markup=False)
    if result.get("verdict") == "structural":
        raise typer.Exit(code=1)
