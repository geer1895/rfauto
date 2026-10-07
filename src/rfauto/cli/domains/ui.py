"""ui serve + warm-start 顶层命令（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── ui (人工核验台) ─────────────────────────────────────────────────────────

@app.command("ui")
def ui_cmd(
    port: int = typer.Option(8642, "--port", "-p", help="监听端口"),
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址（默认仅本机）"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="启动后打开浏览器"),
    expose_runs: bool | None = typer.Option(
        None,
        "--expose-runs/--no-expose-runs",
        help=(
            "runs/ 目录静态服务三态开关：缺省=回环绑定开、非回环绑定关"
            "（开源默认安全）；非回环显式 --expose-runs 才整目录暴露"
        ),
    ),
) -> None:
    """启动人工核验 UI（浏览器查看/修改配方、3D 模型、S 参数与中间产物）。"""
    import threading
    import webbrowser

    from rfauto.ui.server import serve

    url = f"http://{host}:{port}/"
    console.print(f"[green]rfauto UI[/green] → [cyan]{url}[/cyan]（Ctrl+C 退出）")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    serve(host=host, port=port, expose_runs=expose_runs)


# ─── warm-start (E11 stage-2 数据面：数据集历史样本 → 先验注入) ───────────────

@app.command("warm-start")
def warm_start_cmd(
    dataset: str = typer.Argument(..., help="数据集名（datasets materialize 产物）"),
    recipe: str = typer.Argument(..., help="配方文件路径（YAML）"),
    model: str = typer.Option(None, "--model", help="按模板族过滤（model 列精确匹配）"),
    source_study: str = typer.Option(None, "--source-study", help="按来源 study 名过滤（study_name 列）"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
    max_trials: int = typer.Option(60, "--max-trials", help="最大 trial 数"),
    study_name: str = typer.Option(None, "--study-name", help="Optuna study 名（缺省由配方推导）"),
    limit: int = typer.Option(1000, "--limit", help="数据集扫描行数上限（过滤前截断）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """数据集历史样本 → warm-start 先验注入优化（相似度门在 warm_start 内）。"""
    from rfauto.service.warm_start_data import run_optimization_warm_start_from_dataset

    result = run_optimization_warm_start_from_dataset(
        recipe, dataset, model=model, source_study=source_study, limit=limit,
        adapter_name=adapter, max_trials=max_trials, study_name=study_name,
    )
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "warm-start 优化失败", json_output=True)
        return
    stats = result.get("warm_start_data") or {}
    if stats:
        console.print(
            f"[cyan]warm-start 喂料[/cyan]：样本 {stats.get('n_samples', 0)}"
            f" / 扫描 {stats.get('n_rows_scanned', 0)} 行"
            f"（无效跳过 {stats.get('n_skipped_invalid', 0)}"
            f"，族过滤 {stats.get('n_filtered_by_model', 0)}"
            f"，study 过滤 {stats.get('n_filtered_by_study', 0)}）")
        for ex in stats.get("skip_examples") or []:
            console.print(f"  [yellow]- {ex}[/yellow]")
    if not result.get("ok"):
        console.print("[red]✗ warm-start 优化失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print(
        f"[green]✓ 完成[/green]：warm_start_n={result.get('warm_start_n')}  "
        f"trials={result.get('trials_completed')}  "
        f"best_cost={result.get('best_cost')}")
    bp = result.get("best_params") or {}
    if bp:
        console.print(f"  best_params: {bp}")
