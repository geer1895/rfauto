"""CLI 入口（§6）—— typer 子命令。薄壳层，零业务逻辑（军规 10）。

用法：
    rfauto doctor
    rfauto models list [--schema NAME]
    rfauto run <recipe.yaml>
    rfauto sweep <recipe.yaml>
    rfauto tune <recipe.yaml> [--watch|--detach]
    rfauto refine <run_id>
    rfauto jobs [status|cancel] JOB_ID
    rfauto cache clear [--model NAME]
    rfauto link <run_id> --to-ads
    rfauto report <run_id> [-o out.html]
    rfauto export-report-pdf <run_id> [-o out.pdf]
    rfauto replay <run_id>
    rfauto datasets materialize --name X [--runs id1,id2]
    rfauto datasets discover-workdir|import-workdir --name X          (工作目录形态导入器)
    rfauto datasets query <name> [--where "..."] [--columns a,b]
    rfauto datasets coverage|annotate|visibility|export-hf <name>   (WP2.4 余量)
    rfauto bands list|get|find|spec-bounds|env-*                    (D9 十接口)
    rfauto campaign plan|status|event|list                          (战役状态机)
    rfauto template-spec list|draft <name> [-p k=v]                 (E2 模板库)
    rfauto uq yield-at|design-center|temp-zone <samples.json>       (WP4.2 良率)
    rfauto autotune <recipe.yaml> --self-verify                     (WP3.5 自验证环)
    rfauto bench goldset|agentbench                                 (WP3.7 回归门)
    rfauto farfield list|view <run_id>                              (WP4.1 nf2ff)
    rfauto kicad extract|optimize <board.kicad_pcb>                 (B6 stage-2)
    rfauto electrothermal|parasitic <payload.json>                  (WP4.4a/b)
    rfauto topology --f0 2.5 --fbw 0.05 [--campaign]                (WP4.6 E10)
    rfauto vna-replay <measured.s2p> [--sim sim.s2p]                (离线回放)
    rfauto report-narrative <run_id> [--text "..."]                 (F9 叙述位)
    rfauto rationale recall|checklist|search                        (F11/F2 经验记忆)
    rfauto self-heal run <run_id>                                   (F5 自愈环只读诊断)
    rfauto logs digest <path>                                       (WP3.6 LogDistiller)
    rfauto materials dispersion-report <material> [f_lo f_hi]       (D1 色散适应性)
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from rfauto.cli.bench_app import bench_app

app = typer.Typer(
    name="rfauto",
    help="HFSS ↔ ADS 自动化仿真调优框架",
    no_args_is_help=True,
)
def _force_utf8_stdio() -> None:
    """Windows GBK 控制台下 rich 打印 '✓' 等字符会 UnicodeEncodeError 崩溃，
    统一将 stdio 重配为 UTF-8（防再犯：P0 验收审计发现，2026-08-28）。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # 已重定向的管道可能不支持，保持原样
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8")


_force_utf8_stdio()


def _setup_logging_from_env() -> None:
    """按 RFAUTO_LOG_LEVEL 启用 loguru（孤岛接线，缺口 8 顺手项）。

    未设置环境变量时保持静默（零开销，不抢 typer/rich 的输出）；
    设置为 debug/info/warning/error 之一才初始化 sink。
    在 app 回调中执行（每次命令运行时检查，而非模块导入时一次）。
    """
    import os

    level = os.environ.get("RFAUTO_LOG_LEVEL", "").strip().upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        return
    from rfauto.infra.logging import setup_logging

    setup_logging(level=level)


@app.callback()
def _main_callback() -> None:
    """全局入口：每次命令执行前应用环境配置。"""
    _setup_logging_from_env()

console = Console()


# ─── doctor ───────────────────────────────────────────────────────────────────

@app.command()
def doctor() -> None:
    """环境探测：AEDT/ADS 版本、license、路径、已测试版本组合核对。

    退出码：0=就绪；非0=缺项（CI/脚本可直接判断）。
    """
    from rfauto.service.api import doctor as _doctor
    result = _doctor()

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
) -> None:
    """列出已注册模板 + 可选导出参数 JSON Schema。"""
    from rfauto.service.api import list_models as _list_models
    result = _list_models()

    if schema:
        from rfauto.models.registry import export_schema
        try:
            s = export_schema(schema)
            console.print_json(json.dumps(s, indent=2, ensure_ascii=False))
        except KeyError:
            console.print(f"[red]未知模型: {schema}[/red]")
            raise typer.Exit(code=1) from None
    else:
        table = Table(title="已注册模型")
        table.add_column("模型名", style="cyan")
        for name in result.get("models", []):
            table.add_row(name)
        console.print(table)


@models_app.command("docs")
def models_docs(
    model: str = typer.Argument(None, help="模型名（不填则生成全部已注册模型）"),
    output: str = typer.Option(None, "--output", "-o", help="输出目录（默认 docs/models）"),
) -> None:
    """生成模型参数文档（Markdown，pydantic schema 自动推导）。"""
    from rfauto.service.model_docs import generate_all_model_docs, generate_model_docs

    out_dir = output or "docs/models"
    if model:
        try:
            doc = generate_model_docs(model, out_dir)
        except KeyError:
            console.print(f"[red]未知模型: {model}[/red]")
            raise typer.Exit(code=1) from None
        path = Path(out_dir) / f"{model}.md"
        console.print(f"[green]✓ 文档已生成[/green]  {path}（{len(doc.splitlines())} 行）")
        return

    results = generate_all_model_docs(out_dir)
    for name, doc in results.items():
        flag = "[green]✓[/green]" if not doc.startswith("Error") else "[red]✗[/red]"
        console.print(f"  {flag} {name}: {Path(out_dir) / (name + '.md')}")


# ─── run ──────────────────────────────────────────────────────────────────────

@app.command()
def run(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
    detach: bool = typer.Option(False, "--detach", "-d",
                                 help="后台执行，立即返回 job_id（用 jobs status 轮询）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只验证不执行（输出执行计划）"),
) -> None:
    """单次仿真（build → solve → post → 导出）。"""
    if dry_run:
        from rfauto.service.api import dry_run as _dry_run
        result = _dry_run(recipe, adapter_name=adapter)
        if not result.get("ok"):
            console.print("[red]✗ dry-run 校验失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        console.print("[cyan]dry-run 执行计划（未实际执行）：[/cyan]")
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    if detach:
        from rfauto.service.api import run_once_async
        result = run_once_async(recipe, adapter_name=adapter)
        console.print(f"[green]✓ 仿真已后台启动[/green]  job_id: {result['job_id']}")
        console.print(f"  轮询: rfauto jobs status {result['job_id']}")
        return

    from rfauto.service.api import run_once
    result = run_once(recipe, adapter_name=adapter)

    if result.get("ok"):
        console.print(f"[green]✓ 仿真完成[/green]  run_id: {result['run_id']}")
        console.print(f"  run 目录: {result.get('run_dir', '?')}")
        console.print(f"  cost: {result.get('cost', '?')}")
        console.print("  指标:")
        for k, v in result.get("metrics", {}).items():
            console.print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")
    else:
        console.print("[red]✗ 仿真失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)


# ─── tune ─────────────────────────────────────────────────────────────────────

@app.command()
def tune(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    watch: bool = typer.Option(False, "--watch", "-w", help="前台等待并显示进度"),
    max_trials: int = typer.Option(60, "--max-trials", help="最大试验次数"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
    study_name: str = typer.Option(None, "--study-name", help="自定义 study 名称"),
    max_wall_s: float = typer.Option(None, "--max-wall-s", help="总超时秒数"),
    multi: bool = typer.Option(False, "--multi", help="多目标模式（NSGA-II 出 Pareto 前沿）"),
    n_gen: int = typer.Option(20, "--n-gen", help="多目标模式：迭代代数"),
    pop_size: int = typer.Option(12, "--pop-size", help="多目标模式：种群大小"),
    sampler: str = typer.Option("tpe", "--sampler", help="单目标采样器: tpe | cmaes | sbo（代理寻优环 WP3.2）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只验证不执行（输出优化计划）"),
    fidelity: str = typer.Option("single", "--fidelity", help="single (default) | auto (multi-fidelity)"),
    adapter_low: str = typer.Option("fake", "--adapter-low", help="multi-fidelity low-fidelity adapter"),
    adapter_high: str = typer.Option("fake", "--adapter-high", help="multi-fidelity high-fidelity adapter"),
    seed: int = typer.Option(None, "--seed", help="采样器随机种子（缺省沿用 optimizer.SAMPLER_SEED=42）"),
) -> None:
    """启动优化外环（TPE / NSGA-II / --fidelity auto 多保真）。"""
    console.print(f"[cyan]开始优化: {recipe}[/cyan]")
    mode_str = '多保真' if fidelity == 'auto' else ('多目标 NSGA-II' if multi else '单目标 TPE')
    console.print(f"  适配器: {adapter}, 模式: {mode_str}")

    if dry_run:
        from rfauto.service.api import dry_run as _dry_run
        result = _dry_run(recipe, adapter_name=adapter)
        if not result.get("ok"):
            console.print("[red]✗ dry-run 校验失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        result = dict(result, planned_mode="multi-NSGAII" if multi else f"single-{sampler}")
        console.print("[cyan]dry-run 优化计划（未实际执行）：[/cyan]")
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    if fidelity == "auto":
        from rfauto.service.api import run_multifidelity_tune
        result = run_multifidelity_tune(recipe, adapter_low=adapter_low, adapter_high=adapter_high)
        if not result.get("ok"):
            console.print("[red]多保真优化失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        console.print("[green]多保真优化完成[/green]")
        console.print(f"  run_id:     {result.get('run_id', '?')}")
        console.print(f"  Phase 1:    {result.get('phase1', {}).get('trials_completed', '?')} trials")
        console.print(f"  Phase 2:    {result.get('hfss_count', '?')} HFSS trials")
        delta = result.get("fidelity_delta", {})
        console.print(f"  rank flips: {delta.get('rank_flip_count', '?')}")
        if delta.get("mean_abs_delta_db") is not None:
            console.print(f"  mean |DS11|: {delta['mean_abs_delta_db']:.2f} dB")
        console.print(f"  耗时: {result.get('elapsed_s', 0)}s")
        return

    if multi:
        from rfauto.service.api import start_tune_multi
        result = start_tune_multi(
            recipe,
            adapter_name=adapter,
            n_gen=n_gen,
            pop_size=pop_size,
        )
        if not result.get("ok"):
            console.print("[red]✗ 多目标优化失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        console.print("[green]✓ 多目标优化完成[/green]")
        console.print(f"  run_id:      {result.get('run_id', '?')}")
        console.print(f"  目标:        {', '.join(result.get('objective_names', []))}")
        console.print(f"  Pareto 解数: {result.get('n_pareto', 0)}（{result.get('n_evaluations', 0)} 次评估）")
        console.print(f"  耗时:        {result.get('elapsed_s', 0)}s")
        for i, pt in enumerate(result.get("pareto_points", [])[:10]):
            params_str = ", ".join(f"{k}={v:.3f}" for k, v in pt["params"].items())
            objs_str = ", ".join(f"{k}={v:.3f}" for k, v in pt["objectives"].items())
            console.print(f"  [{i + 1}] {params_str}  |  {objs_str}")
        return

    if sampler == "sbo":
        from rfauto.service.surrogate_optimize_service import surrogate_optimize

        result = surrogate_optimize(
            recipe,
            adapter_name=adapter,
            max_real=max_trials,
        )
        if result.get("ok"):
            best = result.get("best") or {}
            console.print("[green]✓ 代理寻优环完成[/green]")
            console.print(f"  run_id:       {result.get('run_id', '?')}")
            console.print(f"  代理:         {result.get('surrogate_kind', '?')}")
            console.print(f"  真跑次数:     {result.get('n_real_used', 0)}"
                          f"（初始 {result.get('n_init', 0)} + top-K 迭代）")
            console.print(f"  停止原因:     {result.get('stop_reason', '?')}")
            console.print(f"  真跑失败:     {result.get('n_failures', 0)}")
            console.print(f"  耗时:         {result.get('elapsed_s', 0)}s")
            best_cost = best.get("cost")
            if best_cost is not None:
                console.print(f"  best cost:    {best_cost:.4f}")
            for k, v in (best.get("params") or {}).items():
                console.print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")
        else:
            console.print("[red]✗ 代理寻优环失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        return

    from rfauto.service.api import start_tune

    result = start_tune(
        recipe,
        adapter_name=adapter,
        max_trials=max_trials,
        study_name=study_name,
        max_wall_s=max_wall_s,
        sampler=sampler,
        seed=seed,
    )

    if result.get("ok"):
        console.print("[green]✓ 优化完成[/green]")
        console.print(f"  study_name: {result.get('study_name', '?')}")
        console.print(f"  run_id:     {result.get('run_id', '?')}")
        console.print(f"  总试验:     {result.get('trials_total', 0)}")
        console.print(f"  完成:       {result.get('trials_completed', 0)}")
        console.print(f"  剪枝:       {result.get('trials_pruned', 0)}")
        if result.get("existing_trials", 0) > 0:
            console.print(f"  恢复已有:   {result.get('existing_trials', 0)} 个 trial")
        console.print(f"  耗时:       {result.get('elapsed_s', 0)}s")
        best_cost = result.get("best_cost")
        if best_cost is not None:
            console.print(f"  best cost:  {best_cost:.4f}")
        best_params = result.get("best_params", {})
        if best_params:
            console.print("  best params:")
            for k, v in best_params.items():
                console.print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")
        best_metrics = result.get("best_metrics", {})
        if best_metrics:
            console.print("  best metrics:")
            for k, v in best_metrics.items():
                console.print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")
    else:
        console.print("[red]✗ 优化失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)


# ─── sweep ────────────────────────────────────────────────────────────────────

@app.command()
def sweep(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    method: str = typer.Option("auto", "--method", "-m",
                               help="auto(粗扫+精调)|grid|random|lhs|fine_only"),
    coarse: int = typer.Option(15, "--coarse", help="粗扫采样数（auto/lhs/random/grid 用）"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
    max_combos: int = typer.Option(60, "--max-combos", help="最大组合数（安全上限）"),
) -> None:
    """参数扫描（先粗扫缩小范围再交给精调）。"""
    from rfauto.optimization.sweep_backend import run_sweep
    console.print(f"[cyan]开始扫描: {recipe}[/cyan]")
    console.print(f"  方法: {method}, 粗扫: {coarse}, 适配器: {adapter}, 上限: {max_combos}")

    result = run_sweep(
        recipe,
        adapter_name=adapter,
        method=method,
        coarse_samples=coarse,
        max_combos=max_combos,
    )

    if result.get("ok"):
        console.print("[green]✓ 扫描完成[/green]")
        console.print(f"  run_id:    {result.get('run_id', '?')}")
        console.print(f"  方法:      {result.get('method', '?')}")
        console.print(f"  组合数:    {result.get('total_combos', 0)}（粗扫 {result.get('coarse_combos', 0)} / 精调 {result.get('fine_combos', 0)}）")
        console.print(f"  耗时:      {result.get('elapsed_s', 0)}s")

        best = result.get("best")
        if best:
            console.print(f"[bold]最佳组合[/bold] cost={best.get('cost', float('inf')):.4f}")
            for k, v in best.get("params", {}).items():
                console.print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")
            for k, v in best.get("metrics", {}).items():
                console.print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")

        # 表格展示前 10 个结果
        results = result.get("results", [])
        if results:
            table = Table(title="扫描结果 Top 10")
            table.add_column("#", style="dim")
            table.add_column("cost", justify="right")
            table.add_column("params", style="cyan")
            for i, r in enumerate(results[:10]):
                cost_v = r.get("cost", float("inf"))
                cost_str = "inf" if cost_v == float("inf") else f"{cost_v:.4f}"
                params_str = ", ".join(f"{k}={v:.3f}" for k, v in r.get("params", {}).items())
                table.add_row(str(i + 1), cost_str, params_str)
            console.print(table)
    else:
        console.print("[red]✗ 扫描失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)


# ─── autotune（阶段 2.1：确定性 critique 自治环）─────────────────────────────

@app.command()
def autotune(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    budget: int = typer.Option(3, "--budget", "-b", help="最大轮数（求解→评判→修正）"),
    mesh: float = typer.Option(0.0, "--mesh", help="openEMS 网格 base 覆盖 mm（0=自动 λ_sub/50）"),
    f0_tol: float = typer.Option(0.15, "--f0-tol", help="谷位/带中心 容差"),
    rl_floor: float = typer.Option(-8.0, "--rl-floor", help="回损地板 dB"),
    max_step: float = typer.Option(0.2, "--max-step", help="单轮修正步长上限（比例）"),
    self_verify: bool = typer.Option(False, "--self-verify",
                                     help="WP3.5 自验证环：propose→verify→fix + 里程碑 M1..M5 + 执行看板"),
    mesh_fine: float = typer.Option(0.5, "--mesh-fine",
                                    help="[self-verify] 细网格 base mm（M4 跨网格复验；0 或=--mesh 关闭）"),
    fine_epsilon: float = typer.Option(0.2, "--fine-epsilon",
                                       help="[self-verify] M4 细网格 cost 容许劣化比例"),
    sandbox: bool = typer.Option(True, "--sandbox/--no-sandbox",
                                 help="[self-verify] best 落沙箱草稿（M5）"),
    board: bool = typer.Option(True, "--board/--no-board",
                               help="[self-verify] 创建执行看板（UI 可暂停/接管）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """确定性 critique 自治调优环（无人在环；数值只在确定性内核）。

    --self-verify 切到 WP3.5 自验证环：粗→细双采样器、里程碑逐项
    验收（passed/failed/skipped 如实）、执行看板 runs/loop_boards/。
    """
    if self_verify:
        from rfauto.service.autotune_service import self_verify_loop
        from rfauto.service.contracts import annotate_contract

        coarse_mm = mesh if mesh > 0 else 1.0
        console.print(f"[cyan]自验证环: {recipe}（budget_coarse={budget}，"
                      f"mesh {coarse_mm}→{mesh_fine} mm）[/cyan]")
        sv = self_verify_loop(
            recipe, budget_coarse=budget, mesh_coarse_mm=coarse_mm,
            mesh_fine_mm=mesh_fine, f0_tolerance=f0_tol, rl_floor_db=rl_floor,
            max_step_pct=max_step, fine_epsilon=fine_epsilon,
            sandbox=sandbox, board=board)
        if not sv.get("ok"):
            console.print("[red]✗ 自验证环失败[/red]")
            for err in sv.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        sv = annotate_contract("self_verify", sv)
        if json_output:
            console.print_json(json.dumps(sv, indent=2, ensure_ascii=False, default=str))
            raise typer.Exit(code=0 if sv["verdict"] == "PASS" else 1)
        color = {"PASS": "green", "TAKEN_OVER": "yellow"}.get(sv["verdict"], "red")
        console.print(f"[{color}]● 自验证环结束：{sv['verdict']}"
                      f"（{sv['rounds_used']} 轮 / 粗预算 {sv['budget_coarse']}）[/{color}]")
        console.print(f"  run_id: {sv.get('run_id', '?')}  board_id: {sv.get('board_id')}")
        for m in sv.get("milestones", []):
            mcolor = {"passed": "green", "skipped": "dim", "failed": "red"}.get(m["status"], "yellow")
            console.print(f"  [{mcolor}]{m['id']} {m['status']:<8}[/{mcolor}] {m['name']}"
                          f"{'：' + str(m['detail']) if m.get('detail') else ''}")
        best = sv.get("best") or {}
        if best:
            console.print(f"  best cost: {best.get('cost'):.4f}（第 {best.get('round')} 轮 {best.get('phase')}）")
        if sv.get("sandbox") and sv["sandbox"].get("draft"):
            console.print(f"  沙箱草稿: {sv['sandbox']['draft']}")
        cc = sv.get("contract_check") or {}
        if cc and not cc.get("ok"):
            console.print(f"  [yellow]! 契约注记: {cc.get('errors')}[/yellow]")
        raise typer.Exit(code=0 if sv["verdict"] == "PASS" else 1)

    from rfauto.service.autotune_service import autotune_loop

    console.print(f"[cyan]自治调优环: {recipe}（budget={budget}）[/cyan]")
    result = autotune_loop(
        recipe, budget=budget, mesh_resolution_mm=mesh,
        f0_tolerance=f0_tol, rl_floor_db=rl_floor, max_step_pct=max_step)
    if not result.get("ok"):
        console.print("[red]✗ 自治环失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    verdict = result["verdict"]
    color = "green" if verdict == "PASS" else "yellow"
    console.print(f"[{color}]● 自治环结束：{verdict}"
                  f"（{result['rounds_used']} 轮 / 预算 {result['budget']}）[/{color}]")
    console.print(f"  run_id: {result.get('run_id', '?')}")
    best = result.get("best") or {}
    if best:
        console.print(f"  best cost: {best.get('cost'):.4f}（第 {best.get('round')} 轮）")
        for k, v in (best.get("params") or {}).items():
            console.print(f"    {k}: {v:.4f}")
    for h in result.get("history", []):
        issues = "; ".join(i.get("kind", "?") for i in h.get("issues", [])) or "-"
        console.print(f"  第{h['round']}轮: cost={h.get('cost', 0):.4f} 评判={h['verdict']} 议题[{issues}]")


# ─── tolerance ────────────────────────────────────────────────────────────────

@app.command()
def tolerance(
    recipe: str = typer.Argument(..., help="配方文件路径（含 tolerance.tolerances 段）"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
    samples: int = typer.Option(200, "--samples", "-n", help="Monte Carlo 样本数"),
) -> None:
    """公差/良率分析（Monte Carlo，规格取自 objectives）。"""
    from rfauto.service.api import run_tolerance

    console.print(f"[cyan]公差分析: {recipe}[/cyan]")
    result = run_tolerance(recipe, adapter_name=adapter, n_samples=samples)
    if not result.get("ok"):
        console.print("[red]✗ 公差分析失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]✓ 公差分析完成[/green]")
    console.print(f"  run_id:   {result.get('run_id', '?')}")
    console.print(f"  样本数:   {result.get('n_samples', 0)}")
    console.print(
        f"  良率:     [bold]{result.get('yield_rate', 0) * 100:.1f}%[/bold]"
        f"（通过 {result.get('n_pass', 0)} / 失败 {result.get('n_fail', 0)}）"
    )
    stats = result.get("stats", {})
    for metric, s in stats.items():
        console.print(
            f"  {metric}: mean={s['mean']:.3f} std={s['std']:.3f} "
            f"min={s['min']:.3f} max={s['max']:.3f}"
        )
    worst = result.get("worst_case")
    if worst:
        console.print(f"  最差样本参数: {worst.get('params', {})}")


# ─── refine ───────────────────────────────────────────────────────────────────

@app.command()
def refine(
    run_id: str = typer.Argument(..., help="要续调的 run_id"),
    recipe: str = typer.Argument(..., help="配方文件路径"),
    max_trials: int = typer.Option(30, "--max-trials", help="本次新增试验次数"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
) -> None:
    """热启动续调：以上轮 best 为起点，继续优化。

    使用相同的 study_name + SQLite storage，Optuna 自动加载已有 trial，
    从已有结果继续采样（TPE 利用历史数据）。
    """
    from rfauto.optimization.optimizer import run_refine
    console.print(f"[cyan]续调 run_id: {run_id}[/cyan]")

    result = run_refine(
        run_id,
        recipe,
        max_trials=max_trials,
        adapter_name=adapter,
    )

    if result.get("ok"):
        console.print("[green]✓ 续调完成[/green]")
        console.print(f"  study_name: {result.get('study_name', '?')}")
        console.print(f"  run_id:     {result.get('run_id', '?')}")
        console.print(f"  总试验:     {result.get('trials_total', 0)}")
        console.print(f"  完成:       {result.get('trials_completed', 0)}")
        if result.get("existing_trials", 0) > 0:
            console.print(f"  恢复已有:   {result.get('existing_trials', 0)} 个 trial")
        best_cost = result.get("best_cost")
        if best_cost is not None:
            console.print(f"  best cost:  {best_cost:.4f}")
        best_params = result.get("best_params", {})
        if best_params:
            console.print("  best params:")
            for k, v in best_params.items():
                console.print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")
    else:
        console.print("[red]✗ 续调失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)


# ─── jobs ─────────────────────────────────────────────────────────────────────

jobs_app = typer.Typer(help="任务管理")
app.add_typer(jobs_app, name="jobs")


@jobs_app.command("status")
def jobs_status(
    job_id: str = typer.Argument(None, help="任务 ID（不填则列出全部）"),
) -> None:
    """查询任务状态 / 列出最近的 runs（SQLite 索引）。"""
    from rfauto.service.api import poll_job
    if job_id:
        result = poll_job(job_id)
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        from rfauto.infra.run_store import list_runs
        rows = list_runs()
        if not rows:
            console.print("[yellow]暂无 run 记录（注册表 runs/registry.sqlite 不存在或为空，"
                          "可用 rfauto db reindex-runs 回填）。[/yellow]")
            return
        table = Table(title="最近 runs")
        table.add_column("run_id", style="cyan")
        table.add_column("model")
        table.add_column("adapter")
        table.add_column("status")
        table.add_column("timestamp")
        table.add_column("s11_db_max_in_band")
        for r in rows:
            s11 = r.get("metrics", {}).get("s11_db_max_in_band", "")
            table.add_row(
                r["run_id"], r.get("model", ""), r.get("adapter", ""),
                r.get("status", ""), str(r.get("timestamp", "")),
                f"{s11:.2f}" if isinstance(s11, float) else str(s11),
            )
        console.print(table)


@jobs_app.command("cancel")
def jobs_cancel(
    job_id: str = typer.Argument(..., help="要取消的任务 ID"),
) -> None:
    """取消任务。

    排队中（未开始执行）→ 直接取消；已开始执行 → 标记取消请求，
    AEDT 求解不可安全中断，当前 run 跑完后结果被丢弃。
    """
    from rfauto.service.job_registry import get_job_registry

    snapshot = get_job_registry().cancel(job_id)
    if snapshot is None:
        console.print(f"[red]✗ 未找到任务: {job_id}（进程内注册表无此 job；"
                      f"跨进程历史 run 请直接用 jobs status 查看）[/red]")
        raise typer.Exit(code=1)
    state = snapshot["state"]
    if state == "cancelled":
        console.print(f"[green]✓ 任务已取消: {job_id}[/green]")
    elif state == "cancel_requested":
        console.print(f"[yellow]✓ 已发送取消请求: {job_id}[/yellow]")
        console.print("  当前 run 不可安全中断（强杀会泄漏 license），跑完后结果将被丢弃")
    else:
        console.print(f"任务状态: {state}（取消请求未生效或已结束）")


# ─── cache ────────────────────────────────────────────────────────────────────

cache_app = typer.Typer(help="缓存管理")
app.add_typer(cache_app, name="cache")


@cache_app.command("clear")
def cache_clear(
    model: str = typer.Option(None, "--model", "-m", help="只清除指定模型的缓存"),
) -> None:
    """手动清理结果缓存。"""
    from rfauto.infra.result_cache import ResultCache
    rc = ResultCache()
    removed = rc.clear(model_name=model)
    scope = f"（模型: {model}）" if model else ""
    console.print(f"[green]✓ 缓存已清除{scope}：移除 {removed} 个条目[/green]")


# ─── link ─────────────────────────────────────────────────────────────────────

@app.command()
def link(
    run_id: str = typer.Argument(..., help="run_id"),
    to_ads: bool = typer.Option(False, "--to-ads", help="送入 ADS 联动链路"),
) -> None:
    """把某次 HFSS 结果送进 ADS 联动链路（P3, N=2 往返）。"""
    from rfauto.service.api import run_link

    result = run_link(run_id, rounds=2)
    if not result["ok"]:
        console.print("[red]✗ link 失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]✓ ADS 联动完成[/green]")
    console.print(f"  源 sNp: {result['snp_path']}")
    console.print(f"  往返次数: {result['rounds_completed']}")
    summary = result.get("summary", {})
    for r in summary.get("results", []):
        p2 = r.get("phase2", {})
        m = p2.get("metrics") or {}
        status = p2.get("status", "?")
        console.print(f"  轮 {r['round']}: {status}")
        for k, v in m.items():
            console.print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")
        if status == "c_fallback":
            console.print(f"    [yellow]! B 档受阻, 已落 C 档保底: {p2.get('reason', '')[:60]}[/yellow]")


# ─── report ───────────────────────────────────────────────────────────────────

@app.command()
def report(
    run_id: str = typer.Argument(..., help="run_id"),
    output: str = typer.Option(None, "--output", "-o", help="输出文件路径"),
    fmt: str = typer.Option("markdown", "--format", "-f", help="报告格式: markdown | html"),
) -> None:
    """按已完成的 run 重建报告（markdown / html）。"""
    from rfauto.service.api import generate_report_for_run

    result = generate_report_for_run(run_id, fmt=fmt, output=output)
    if not result["ok"]:
        console.print("[red]✗ 报告生成失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print("[green]✓ 报告已生成[/green]")
    console.print(f"  文件: {result['report']}")
    for k, v in result.get("metrics", {}).items():
        console.print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")


@app.command("export-report-pdf")
def export_report_pdf_cmd(
    run_id: str = typer.Argument(..., help="run_id（runs/<run_id>/results/metrics.json 须存在）"),
    filename: str = typer.Option("report.pdf", "--filename", help="输出文件名（写入 run 目录）"),
    output: str = typer.Option(None, "--output", "-o", help="输出 PDF 完整路径（缺省 run 目录/<filename>）"),
    narrative: str = typer.Option(None, "--narrative", help="叙述文本（F9 位；不触发任何 LLM 调用）"),
) -> None:
    """把已完成 run 的指标导出为多页 PDF 报告（WP4.7）。"""
    from rfauto.infra.report import export_report_pdf as _export_pdf
    from rfauto.service.api import get_metrics

    result = get_metrics(run_id)
    if not result["ok"]:
        console.print("[red]✗ PDF 报告导出失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    data = result.get("data") or {}
    report_path = _export_pdf(
        Path("runs") / run_id,
        metrics=data.get("metrics", {}),
        narrative=narrative,
        filename=filename,
    )
    if output and Path(report_path) != Path(output):
        dest = Path(output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).replace(dest)
        report_path = dest
    console.print("[green]✓ PDF 报告已导出[/green]")
    console.print(f"  文件: {report_path}")
    for k, v in (data.get("metrics") or {}).items():
        console.print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")


# ─── replay ───────────────────────────────────────────────────────────────────

@app.command()
def replay(
    run_id: str = typer.Argument(..., help="要复现的 run_id"),
) -> None:
    """复现：用该 run 的 recipe 快照重跑，并核对 plugin/schema 版本。"""
    from rfauto.service.api import replay_run

    result = replay_run(run_id)
    if not result["ok"]:
        console.print("[red]✗ replay 失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    for warn in result.get("version_warnings", []):
        console.print(f"  [yellow]! {warn}[/yellow]")
    console.print("[green]✓ replay 完成[/green]")
    console.print(f"  源 run:   {run_id}")
    console.print(f"  复现 run: {result.get('replay_run_id', '?')}")
    metrics = (result.get("result") or {}).get("metrics") or {}
    console.print("  指标:")
    for k, v in metrics.items():
        console.print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")


# ─── validate ─────────────────────────────────────────────────────────────────

@app.command()
def validate(
    recipe: str = typer.Argument(..., help="配方文件路径"),
) -> None:
    """校验配方文件（不执行仿真）。"""
    from rfauto.service.api import validate_recipe
    result = validate_recipe(recipe)

    if result["ok"]:
        console.print("[green]✓ 配方校验通过[/green]")
    else:
        console.print("[red]✗ 配方校验失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")

    for warn in result.get("warnings", []):
        console.print(f"  [yellow]- {warn}[/yellow]")

    if not result["ok"]:
        raise typer.Exit(code=1)



# ─── syn (E6a 微带综合) ───────────────────────────────────────────────────────

syn_app = typer.Typer(help="微带线综合（E6a）")
app.add_typer(syn_app, name="syn")


@syn_app.command("mline")
def syn_mline(
    z0: float = typer.Argument(..., help="目标特性阻抗 (Ω)"),
    freq: float = typer.Option(2.4, "--freq", "-f", help="频率 (GHz)"),
    stackup: str = typer.Option(
        "rogers4350b_h0.508", "--stackup", "-s", help="层叠名称 (materials.yaml 键)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """微带线综合：目标阻抗 → 线宽（Hammerstad-Jensen + brentq 反解）。

    示例：rfauto syn mline 35.35 --freq 2.4 --stackup rogers4350b_h0.508
    """
    from rfauto.core.synthesis import synthesize_mline

    try:
        result = synthesize_mline(z0, freq, stackup)
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(code=1) from None
    except KeyError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(code=1) from None

    if json_output:
        console.print_json(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        status_color = "green" if result.status == "ok" else "yellow"
        console.print(f"\n[bold]微带线综合结果[/bold] ({result.stackup_name} @ {result.freq_ghz} GHz)")
        console.print(f"  目标阻抗: {result.z0_target:.2f} Ω")
        console.print(f"  线宽:     [cyan]{result.width_mm:.4f} mm[/cyan]")
        console.print(f"  实际阻抗: {result.z0_actual:.2f} Ω")
        console.print(f"  εeff:     {result.epsilon_eff:.4f}")
        console.print(f"  ΔZ0:      {result.delta_z0:.4f} Ω")
        console.print(f"  状态:     [{status_color}]{result.status}[/{status_color}]")

        if result.status == "needs_calibration":
            console.print("\n[yellow]⚠ 回代偏差>0.5Ω，建议校准。[/yellow]")

    raise typer.Exit(code=0)


@syn_app.command("wilkinson")
def syn_wilkinson(
    f0: float = typer.Option(2.4, "--f0", help="中心频率 (GHz)"),
    z0: float = typer.Option(50.0, "--z0", help="特性阻抗 (ohm)"),
    stackup: str = typer.Option("rogers4350b_h0.508", "--stackup", "-s", help="层叠名称"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """Wilkinson 功分器综合：f0 + Z0 → arm_len + series_w + shunt_w + 配方草稿。

    方向 8a 验收口径：闭式初值与人工设计值偏差 <10%。
    """
    from rfauto.core.synthesis import synthesize_wilkinson
    result = synthesize_wilkinson(f0_ghz=f0, z0_ohm=z0, stackup_name=stackup)
    if json_output:
        import dataclasses
        console.print_json(json.dumps(dataclasses.asdict(result), indent=2, ensure_ascii=False, default=str))
    else:
        console.print(f"[bold]Wilkinson 综合结果[/bold] (f0={f0}GHz, Z0={z0}ohm)")
        console.print(f"  arm_len:   [cyan]{result.params['arm_len_mm']:.2f} mm[/cyan]")
        console.print(f"  series_w:  [cyan]{result.params['series_w_mm']:.3f} mm[/cyan]")
        console.print(f"  shunt_w:   [cyan]{result.params['shunt_w_mm']:.3f} mm[/cyan]")
        for note in result.notes:
            console.print(f"  {note}")


@syn_app.command("branchline")
def syn_branchline(
    f0: float = typer.Option(2.4, "--f0", help="中心频率 (GHz)"),
    z0: float = typer.Option(50.0, "--z0", help="特性阻抗 (ohm)"),
    stackup: str = typer.Option("rogers4350b_h0.508", "--stackup", "-s", help="层叠名称"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """Branchline coupler 综合：f0 + Z0 → arm_len + series_w + shunt_w + 配方草稿。"""
    from rfauto.core.synthesis import synthesize_branchline
    result = synthesize_branchline(f0_ghz=f0, z0_ohm=z0, stackup_name=stackup)
    if json_output:
        import dataclasses
        console.print_json(json.dumps(dataclasses.asdict(result), indent=2, ensure_ascii=False, default=str))
    else:
        console.print(f"[bold]Branchline 综合结果[/bold] (f0={f0}GHz)")
        console.print(f"  arm_len:   [cyan]{result.params['arm_len_mm']:.2f} mm[/cyan]")
        console.print(f"  series_w:  [cyan]{result.params['series_w_mm']:.3f} mm[/cyan] (35.35ohm)")
        console.print(f"  shunt_w:   [cyan]{result.params['shunt_w_mm']:.3f} mm[/cyan] (50ohm)")
        for note in result.notes:
            console.print(f"  {note}")


@syn_app.command("patch")
def syn_patch(
    f0: float = typer.Option(2.4, "--f0", help="中心频率 (GHz)"),
    er: float = typer.Option(3.66, "--er", help="介电常数"),
    h: float = typer.Option(0.508, "--h", help="基板厚度 (mm)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """矩形贴片天线综合（Hammerstad 模型）：f0 + er + h → patch_len + patch_w + feed_offset。"""
    from rfauto.core.synthesis import synthesize_patch
    result = synthesize_patch(f0_ghz=f0, er=er, h_mm=h)
    if json_output:
        import dataclasses
        console.print_json(json.dumps(dataclasses.asdict(result), indent=2, ensure_ascii=False, default=str))
    else:
        console.print(f"[bold]Patch 综合结果[/bold] (f0={f0}GHz, er={er}, h={h}mm)")
        console.print(f"  patch_len:    [cyan]{result.params['patch_len_mm']:.2f} mm[/cyan]")
        console.print(f"  patch_w:      [cyan]{result.params['patch_w_mm']:.2f} mm[/cyan]")
        console.print(f"  feed_offset:  [cyan]{result.params['feed_offset_mm']:.2f} mm[/cyan]")
        for note in result.notes:
            console.print(f"  {note}")


@syn_app.command("bpf")
def syn_bpf(
    order: int = typer.Option(..., "--order", "-n", help="阶数 N（≥1）"),
    f0: float = typer.Option(2.4, "--f0", help="中心频率 (GHz)"),
    fbw: float = typer.Option(0.1, "--fbw", help="相对带宽 (0,1]"),
    rl: float = typer.Option(20.0, "--rl", help="带内回波损耗 (dB)"),
    tz: list[float] | None = typer.Option(None, "--tz",  # noqa: B008
                                          help="传输零点频率 GHz（可重复；须在阻带，±对口径）"),
    topology: str = typer.Option("folded", "--topology", "-t", help="folded | arrow"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """C13 带通滤波器综合：广义切比雪夫 → Cameron N+2 耦合矩阵 → folded/arrow。

    示例：rfauto syn bpf --order 5 --f0 2.4 --fbw 0.1 --rl 22 --tz 2.59 --json
    """
    from rfauto.core.synthesis import synthesize_bpf_model

    result = synthesize_bpf_model(order=order, f0_ghz=f0, fbw=fbw, rl_db=rl,
                                  transmission_zeros_ghz=list(tz or []),
                                  topology=topology)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["ok"]:
        console.print(f"[bold]BPF 综合结果[/bold] (N={order}, f0={f0}GHz, fbw={fbw}, "
                      f"RL={rl}dB, {topology})")
        console.print(f"  频响最大偏差: [cyan]{result['response_max_err']:.2e}[/cyan]"
                      f"  模式残留: {result['pattern_residual']:.2e}"
                      f"  交叉耦合族: {result['cross_family']}")
        for key, value in result["nominal"].items():
            if isinstance(value, list) or value != 0:
                console.print(f"  {key}: [cyan]{value}[/cyan]")
        for note in result["notes"]:
            console.print(f"  {note}")
    else:
        console.print(f"[red]✗ {'; '.join(result.get('errors') or ['未知错误'])}[/red]")
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


# ─── budget (E8c 链路预算) ─────────────────────────────────────────────────────

budget_app = typer.Typer(help="链路预算（E8c）")
app.add_typer(budget_app, name="budget")


@budget_app.command("run")
def budget_run(
    catalog: str = typer.Option("parts/catalog.yaml", "--catalog", "-c", help="器件目录"),
    chain: list[str] = typer.Argument(..., help="级联器件名（空格分隔）"),  # noqa: B008
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """链路预算：Friis 噪声级联 + 增益/P1dB 预算。

    示例：rfauto budget run lna_2ghz lowpass_filter_2ghz mixer_2ghz
    """
    from rfauto.core.block_spec import DeviceCatalog
    from rfauto.core.budget import LinkBudget

    try:
        dev_catalog = DeviceCatalog.from_yaml(catalog)
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(code=1) from None

    budget = LinkBudget()
    for name in chain:
        try:
            spec = dev_catalog.get(name)
        except KeyError as e:
            console.print(f"[red]✗ {e}[/red]")
            raise typer.Exit(code=1) from None
        budget.add_stage(
            name=name,
            gain_db=spec.gain_db or -(spec.conversion_loss_db or 0),
            nf_db=spec.nf_db or spec.conversion_loss_db or 0,
            p1db_dbm=spec.p1db_dbm,
            oip3_dbm=spec.oip3_dbm,
        )

    result = budget.compute()

    if json_output:
        console.print_json(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        console.print("\n[bold]链路预算结果[/bold]")
        table = Table(title="逐级预算")
        table.add_column("级", style="cyan")
        table.add_column("增益(dB)", justify="right")
        table.add_column("NF(dB)", justify="right")
        table.add_column("累积增益(dB)", justify="right")
        table.add_column("累积NF(dB)", justify="right")
        for s in result.stages:
            table.add_row(
                s.name,
                f"{s.gain_db:.1f}",
                f"{s.nf_db:.1f}",
                f"{s.cumulative_gain_db:.1f}",
                f"{s.cumulative_nf_db:.1f}",
            )
        console.print(table)
        console.print(f"\n级联增益: [cyan]{result.cascade_gain_db:.1f} dB[/cyan]")
        console.print(f"级联 NF:  [cyan]{result.cascade_nf_db:.1f} dB[/cyan]")
        if result.cascade_p1db_dbm is not None:
            console.print(f"级联 P1dB: [cyan]{result.cascade_p1db_dbm:.1f} dBm[/cyan]")
        if result.cascade_iip3_dbm is not None:
            console.print(f"级联 IIP3: [cyan]{result.cascade_iip3_dbm:.1f} dBm[/cyan]")
        if result.cascade_oip3_dbm is not None:
            console.print(f"级联 OIP3: [cyan]{result.cascade_oip3_dbm:.1f} dBm[/cyan]")

    raise typer.Exit(code=0)


# ─── correlate (E9c 相关性) ───────────────────────────────────────────────────

@app.command()
def correlate(
    sim_file: str = typer.Argument(..., help="仿真结果文件 (.s2p)"),
    measured_file: str = typer.Argument(..., help="测量数据文件 (.s2p)"),
    threshold_db: float = typer.Option(3.0, "--threshold", "-t", help="偏差阈值 (dB)"),
) -> None:
    """仿真 vs 测量相关性分析。"""
    from rfauto.service.api import correlate_files

    try:
        result = correlate_files(sim_file, measured_file, threshold_db=threshold_db)
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(code=1) from None
    except Exception as e:
        console.print(f"[red]✗ 相关性分析失败: {e}[/red]")
        raise typer.Exit(code=1) from None

    data = result["data"]
    verdict = (
        "[green]相关[/green]" if data.get("is_correlated") else "[red]不相关[/red]"
    )
    console.print(f"\n[bold]相关性判定: {verdict}[/bold]（阈值 {threshold_db} dB）")
    for k, v in data.get("metrics", {}).items():
        console.print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    for w in data.get("warnings", []):
        console.print(f"  [yellow]! {w}[/yellow]")

    if not data.get("is_correlated"):
        raise typer.Exit(code=1)


# ─── surrogate (E3 代理模型离线分析) ─────────────────────────────────────────

surrogate_app = typer.Typer(help="代理模型离线分析（E3）")
app.add_typer(surrogate_app, name="surrogate")


@surrogate_app.command("analyze")
def surrogate_analyze(
    run_id: str = typer.Argument(None, help="run_id（从其 meta 反查 study）"),
    study: str = typer.Option(None, "--study", "-s", help="Optuna study 名称"),
) -> None:
    """离线 GP 代理模型分析：参数重要度 + 拟合误差（不进在线调优路径）。"""
    from rfauto.service.api import analyze_surrogate

    result = analyze_surrogate(run_id, study_name=study)
    if not result.get("ok"):
        console.print("[red]✗ 分析失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    data = result["data"]
    console.print(f"\n[bold]代理模型分析[/bold]（{data['n_samples']} 个 trial, "
                  f"{data['n_params']} 个参数）")
    console.print(f"  best cost:  {data['best_cost']:.4f}")
    console.print(f"  best params: {data['best_params']}")
    console.print(f"  拟合误差 (RMSE): {data['prediction_error']}")
    console.print("  参数重要度:")
    for k, v in sorted(data["param_importance"].items(), key=lambda x: -x[1]):
        bar = "█" * max(1, int(v * 30))
        console.print(f"    {k:<20} {v:.3f} {bar}")


@surrogate_app.command("uq")
def surrogate_uq(
    samples: str = typer.Argument(..., help="校准样本集 samples.json 路径"),
    tol: list[str] = typer.Option(None, "--tol", help="公差 σ：--tol 参数名=值（可多次）"),  # noqa: B008
    n: int = typer.Option(10000, "--n", help="蒙特卡洛抽样数"),
    seed: int = typer.Option(42, "--seed", help="随机种子"),
    kind: str = typer.Option("poly_ridge", "--kind", help="代理类型 poly_ridge|nn"),
) -> None:
    """代理免费蒙特卡洛 UQ：良率 + 指标分布 + 敏感性排序（阶段 6.4）。"""
    from rfauto.service.uq_service import surrogate_yield

    tolerances: dict[str, float] = {}
    for item in (tol or []):
        if "=" not in item:
            console.print(f"[red]✗ --tol 格式应为 参数名=σ：{item}[/red]")
            raise typer.Exit(code=1)
        name, _, val = item.partition("=")
        tolerances[name.strip()] = float(val)

    result = surrogate_yield(samples, tolerances, n=n, seed=seed, kind=kind)
    if not result.get("ok"):
        console.print("[red]✗ UQ 失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    color = "green" if result["yield_rate"] >= 0.9 else (
        "yellow" if result["yield_rate"] >= 0.7 else "red")
    console.print(f"[bold]代理蒙特卡洛 UQ[/bold]（{result['n_draws']} 点，"
                  f"代理 {result['surrogate_kind']}）")
    console.print(f"  名义点: {result['nominal_params']}")
    console.print(f"  良率:   [{color}]{result['yield_rate']:.1%}[/{color}]")
    for m, s in result.get("metric_stats", {}).items():
        console.print(f"  {m}: mean={s['mean']:.3f} std={s['std']:.3f} "
                      f"q05={s['q05']:.3f} q95={s['q95']:.3f}")
    console.print(f"  敏感性排序: {' > '.join(result['sensitivity_ranking'])}")


# ─── runs (对比) ─────────────────────────────────────────────────────────────

runs_app = typer.Typer(help="run 历史对比")
app.add_typer(runs_app, name="runs")


@runs_app.command("compare")
def runs_compare(
    run_id_a: str = typer.Argument(..., help="run_id A"),
    run_id_b: str = typer.Argument(..., help="run_id B"),
    provenance: bool = typer.Option(False, "--provenance", "-p",
                                     help="输出可引用的实验复现块（方向 7）"),
) -> None:
    """对比两次 run 的指标与 cost。--provenance 输出环境指纹复现块。"""
    if provenance:
        from rfauto.service.api import compare_runs_provenance
        result = compare_runs_provenance([run_id_a, run_id_b])
        if not result.get("ok"):
            console.print("[red]✗ 查询失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    from rfauto.service.api import compare_runs

    result = compare_runs(run_id_a, run_id_b)
    if not result.get("ok"):
        console.print("[red]✗ 对比失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    data = result["data"]
    table = Table(title=f"run 对比: {data['run_a']} vs {data['run_b']}")
    table.add_column("指标", style="cyan")
    table.add_column("A", justify="right")
    table.add_column("B", justify="right")
    table.add_column("Δ (B-A)", justify="right")
    for k, d in data["metrics"].items():
        fmt = lambda x: f"{x:.4f}" if isinstance(x, float) else str(x)  # noqa: E731
        delta = d["delta"]
        table.add_row(k, fmt(d["a"]), fmt(d["b"]),
                      fmt(delta) if delta is not None else "-")
    console.print(table)
    console.print(f"  cost A: {data['cost_a']}, cost B: {data['cost_b']}")


@runs_app.command("health")
def runs_health(
    run_id: str = typer.Argument(..., help="run_id（runs/ 下的目录名）"),
    json_out: bool = typer.Option(False, "--json", help="输出原始 JSON（供门禁/脚本消费）"),
) -> None:
    """对单次 run 做求解健康度体检（G11：历史踩坑教训内核化）。

    检查项：激励体积死(#174)/cost 退化(#195)/CFL 时间步塌缩(#152)/
    1.0491 探针窗/无源性/互易性/非物理增益。退出码：healthy=0；
    suspect/unhealthy 或 run 目录不存在=1（与 ok 字段/注册表门禁口径一致）。
    """
    from rfauto.service.health_service import health_check_run

    result = health_check_run(run_id)
    if json_out:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        if not result.get("factors"):
            console.print(f"[red]✗ 无法体检 run {run_id}[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        status_color = {"PASS": "green", "WARN": "yellow", "FAIL": "red", "UNKNOWN": "dim"}
        table = Table(title=f"run 健康度体检: {run_id}")
        table.add_column("检查项", style="cyan")
        table.add_column("状态")
        table.add_column("依据", style="dim")
        table.add_column("说明")
        for f in result["factors"]:
            color = status_color.get(f["status"], "white")
            table.add_row(f["factor"], f"[{color}]{f['status']}[/{color}]",
                          f["lesson_ref"], f["detail"])
        console.print(table)
        verdict = result.get("verdict", "unknown")
        verdict_color = {"healthy": "green", "suspect": "yellow", "unhealthy": "red"}.get(verdict, "white")
        console.print(f"  verdict: [{verdict_color}]{verdict}[/{verdict_color}]  ok={result.get('ok')}")
        for err in result.get("errors", []):
            console.print(f"  [yellow]- {err}[/yellow]")
    if not result.get("ok"):
        raise typer.Exit(code=1)


# ─── datasets (数据集注册表 v2：Parquet 物化 + DuckDB 直查) ──────────────────

datasets_app = typer.Typer(help="数据集注册表 v2（runs 点级数据 → Parquet + SQL 查询）")
app.add_typer(datasets_app, name="datasets")


@datasets_app.command("materialize")
def datasets_materialize(
    name: str = typer.Option(..., "--name", "-n", help="数据集名（目录名，字母数字-_）"),
    runs: str = typer.Option(None, "--runs", help="逗号分隔 run_id（缺省=全部有 meta 的 run）"),
    out_dir: Path = typer.Option(Path("runs/datasets"), "--out-dir", help="数据集输出根目录"),  # noqa: B008
    registry_sync: bool | None = typer.Option(
        None, "--registry-sync/--no-registry-sync",
        help="登记进注册表 datasets 表：缺省读配置 db.dataset_registry_sync"),
) -> None:
    """把 runs/ 点级数据物化为 Parquet 数据集（指纹去重 + manifest 落盘）。"""
    from rfauto.service.dataset_service import materialize_dataset

    run_ids = [r.strip() for r in runs.split(",") if r.strip()] if runs else None
    result = materialize_dataset(run_ids, name=name, out_dir=out_dir,
                                 registry_sync=registry_sync)
    if not result.get("ok"):
        console.print("[red]✗ 物化失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ 数据集已物化: {result['name']}[/green]")
    console.print(f"  目录: {result['dataset_dir']}")
    console.print(f"  点数: {result['n_points']}  去重删除: {result['n_dup']}  行数: {result['n_rows']}")
    if result.get("skipped_runs"):
        console.print(f"  [yellow]无产物跳过: {', '.join(result['skipped_runs'])}[/yellow]")
    if result.get("missing_runs"):
        console.print(f"  [red]run 不存在: {', '.join(result['missing_runs'])}[/red]")
    bounds = result.get("bounds") or {}
    if bounds:
        console.print("  参数空间 bounds 聚合:")
        for k in sorted(bounds):
            lo, hi = bounds[k]
            console.print(f"    {k}: [{lo:g}, {hi:g}]")


@datasets_app.command("query")
def datasets_query(
    name: str = typer.Argument(..., help="数据集名（materialize 生成的目录名）"),
    where: str = typer.Option(None, "--where", "-w",
                              help="SQL WHERE 片段，如 \"cost < 0.1 and model = 'mline'\""),
    columns: str = typer.Option(None, "--columns", help="逗号分隔列名（缺省全部列）"),
    limit: int = typer.Option(100, "--limit", help="最大返回行数"),
    out_dir: Path = typer.Option(Path("runs/datasets"), "--out-dir", help="数据集根目录"),  # noqa: B008
) -> None:
    """DuckDB 直查 Parquet 数据集（谓词下推/列裁剪，where 经白名单校验）。"""
    from rfauto.service.dataset_service import query_dataset

    cols = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
    result = query_dataset(name, where=where, columns=cols, limit=limit, out_dir=out_dir)
    if not result.get("ok"):
        console.print("[red]✗ 查询失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    table = Table(title=f"数据集 {result['dataset']}（{result['n_rows']} 行"
                        f"{'，where: ' + result['where'] if result['where'] else ''}）")
    for col in result["columns"]:
        table.add_column(col, style="cyan", overflow="fold")
    for row in result["rows"]:
        # 星号解包必须包住完整生成器表达式：裸 *expr for c in ... 是
        # SyntaxError（"iterable unpacking cannot be used in comprehension"），
        # 会使整个 cli.main 模块不可 import（G11 联调时发现）
        table.add_row(*(
            ("" if row.get(c) is None else str(row.get(c))) for c in result["columns"]
        ))
    console.print(table)


def _datasets_json(result: dict, fail_msg: str) -> None:
    """数据集余量命令共用出口：ok=False 红 + 退出码 1；否则 JSON 直出。"""
    if not result.get("ok"):
        console.print(f"[red]✗ {fail_msg}[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def _datasets_families(models: str | None) -> list[str] | None:
    """--models 逗号分隔器件族 → list[str] | None（service 层做合法性校验）。"""
    return ([m.strip() for m in models.split(",") if m.strip()]
            if models else None)


@datasets_app.command("discover-workdir")
def datasets_discover_workdir(
    runs_root: str = typer.Option("runs", "--runs-root", help="runs 根目录"),
    models: str = typer.Option(None, "--models",
                               help="逗号分隔器件族过滤（slotline/hairpin/"
                                    "marchand/mline/helix；缺省全部）"),
) -> None:
    """发现工作目录形态真机产物（无 meta.json 的 runs 子目录，只读）。"""
    from rfauto.service.dataset_service import discover_workdir_candidates

    result = discover_workdir_candidates(runs_root, models=_datasets_families(models))
    _datasets_json(result, "工作目录产物发现失败")


@datasets_app.command("import-workdir")
def datasets_import_workdir(
    name: str = typer.Option(..., "--name", "-n", help="数据集名（目录名，字母数字-_）"),
    runs: str = typer.Option(None, "--runs", help="逗号分隔工作目录名（缺省=所选族全部）"),
    runs_root: str = typer.Option("runs", "--runs-root", help="runs 根目录"),
    out_dir: Path = typer.Option(Path("runs/datasets"), "--out-dir", help="数据集输出根目录"),  # noqa: B008
    models: str = typer.Option(None, "--models", help="逗号分隔器件族过滤（缺省五族）"),
    no_health_gate: bool = typer.Option(False, "--no-health-gate", help="跳过 G11 目录级健康门"),
    fmt: str = typer.Option("parquet", "--fmt", help="物化格式（parquet/hdf5）"),
    registry_sync: bool | None = typer.Option(
        None, "--registry-sync/--no-registry-sync",
        help="登记进注册表 datasets 表：缺省读配置 db.dataset_registry_sync"),
) -> None:
    """工作目录形态真机产物导入数据集注册表（无 meta.json 的漏数口）。"""
    from rfauto.service.dataset_service import import_workdir_runs

    run_ids = [r.strip() for r in runs.split(",") if r.strip()] if runs else None
    result = import_workdir_runs(
        run_ids, name=name, runs_root=runs_root, out_dir=out_dir,
        models=_datasets_families(models), health_gate=not no_health_gate, fmt=fmt,
        registry_sync=registry_sync)
    if not result.get("ok"):
        console.print("[red]✗ 工作目录导入失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ 工作目录产物已导入: {result['name']}[/green]")
    console.print(f"  目录: {result['dataset_dir']}")
    console.print(f"  候选: {result['n_candidates']}  曲线: {result['n_curves']}  "
                  f"点: {result['n_points']}  去重删除: {result['n_dup']}  "
                  f"行数: {result['n_rows']}")
    if result.get("n_points_skipped"):
        console.print(f"  [yellow]无可归属参数跳过: {result['n_points_skipped']}[/yellow]")
    if result.get("unhealthy_points"):
        console.print(f"  [red]健康门拦截: {len(result['unhealthy_points'])}[/red]")
    if result.get("warnings"):
        console.print(f"  [yellow]警告 {len(result['warnings'])} 条（详见 manifest/JSON）[/yellow]")


@datasets_app.command("coverage")
def datasets_coverage(
    name: str = typer.Argument(..., help="数据集名"),
    bins: int = typer.Option(10, "--bins", help="等宽分箱数（>=2）"),
    out_dir: Path = typer.Option(Path("runs/datasets"), "--out-dir"),  # noqa: B008
) -> None:
    """数据集覆盖度：点数分布 + 参数空间逐维占用率/最弱维（WP2.4）。"""
    from rfauto.service.dataset_insights import dataset_coverage

    result = dataset_coverage(name, out_dir=out_dir, bins=bins)
    if not result.get("ok"):
        console.print("[red]✗ 覆盖度统计失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    cov = result.get("coverage") or {}
    console.print(f"[green]✓ {result.get('name', name)}[/green]"
                  f"（{result.get('n_rows', '?')} 行）")
    console.print(f"  mean occupancy: {cov.get('mean_occupancy')}  "
                  f"min: {cov.get('min_occupancy')}  最弱维: {cov.get('weakest_key')}")
    for dim, stat in (cov.get("dims") or {}).items():
        console.print(f"    {dim}: distinct={stat.get('distinct')} "
                      f"[{stat.get('min')}, {stat.get('max')}] "
                      f"occupied {stat.get('occupied_bins')}/{stat.get('bins')}")
    if cov.get("n_constant_dims"):
        console.print(f"  常数维: {cov['n_constant_dims']}（不虚报占用率）")


@datasets_app.command("annotate")
def datasets_annotate(
    name: str = typer.Argument(..., help="数据集名"),
    threshold: int = typer.Option(100, "--threshold", help="神经算子族级解锁门槛（点数）"),
    out_dir: Path = typer.Option(Path("runs/datasets"), "--out-dir"),  # noqa: B008
) -> None:
    """ground truth 标注（白名单通道）+ 6.3 解锁进度（幂等回写 manifest）。"""
    from rfauto.service.dataset_insights import annotate_ground_truth

    result = annotate_ground_truth(name, threshold=threshold, out_dir=out_dir)
    if not result.get("ok"):
        console.print("[red]✗ 标注失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    gt = result.get("ground_truth") or {}
    console.print(f"[green]✓ GT 标注完成[/green]（threshold={gt.get('threshold')}）")
    for model, info in (gt.get("per_model") or {}).items():
        n = info.get("n") if isinstance(info, dict) else info
        unlocked = info.get("unlocked") if isinstance(info, dict) else None
        suffix = f"  unlocked={unlocked}" if unlocked is not None else ""
        console.print(f"  {model}: {n}{suffix}")


@datasets_app.command("visibility")
def datasets_visibility(
    name: str = typer.Argument(..., help="数据集名"),
    set_to: str = typer.Argument(..., help="public | private"),
    out_dir: Path = typer.Option(Path("runs/datasets"), "--out-dir"),  # noqa: B008
) -> None:
    """公开/私有双集切换（public 是 HF 导出放行前提；manifest 回写）。"""
    from rfauto.service.dataset_insights import set_dataset_visibility

    _datasets_json(set_dataset_visibility(name, set_to, out_dir=out_dir),
                   "可见性切换失败")


@datasets_app.command("export-hf")
def datasets_export_hf(
    name: str = typer.Argument(..., help="数据集名"),
    license: str = typer.Option("", "--license", help="数据卡 license 字段"),
    allow_private: bool = typer.Option(False, "--allow-private",
                                       help="显式允许导出 private 数据集"),
    out_dir: Path = typer.Option(Path("runs/datasets"), "--out-dir"),  # noqa: B008
) -> None:
    """HF datasets 本地目录布局导出（parquet 分片 + README 数据卡，确定性逐字节一致）。"""
    from rfauto.service.dataset_insights import export_hf_dataset

    result = export_hf_dataset(name, out_dir=out_dir, license=license,
                               allow_private=allow_private)
    if not result.get("ok"):
        console.print("[red]✗ 导出失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ HF 导出完成[/green] → {result.get('hf_dir')}")
    for f in result.get("files") or []:
        console.print(f"  {f}")


# ─── agent (E4b 提案/执行编排) ────────────────────────────────────────────────

agent_app = typer.Typer(help="Agent 提案/执行编排（E4b 三层 Gate）")
app.add_typer(agent_app, name="agent")


@app.command("hfss-import")
def hfss_import_cmd(
    project: str = typer.Argument(..., help="HFSS 工程文件路径（.aedt）"),
    design: str = typer.Option(None, "--design", "-d", help="设计名（缺省取第一个）"),
    version: str = typer.Option("2023.1", "--version", help="AEDT 版本（2026.1 受 PyAEDT issue #7410 阻塞，暂用 2023.1）"),
    out: str = typer.Option(None, "--out", "-o", help="配方草稿输出路径（YAML）"),
) -> None:
    """HFSS 工程导入器：读变量/扫参范围/Setup-Sweep/端口 → 设计规格 + 配方草稿。"""
    from rfauto.service.v3_services import hfss_import_recipe

    result = hfss_import_recipe(project, design, version=version, out=out)
    if not result.get("ok"):
        console.print(f"[red]✗ 导入失败: {result.get('error')}[/red]")
        raise typer.Exit(code=1)
    console.print("[cyan]导入成功：设计规格[/cyan]")
    console.print_json(json.dumps(result["spec"], indent=2, ensure_ascii=False, default=str))
    console.print("[cyan]配方草稿：[/cyan]")
    console.print_json(json.dumps(result["recipe"], indent=2, ensure_ascii=False, default=str))
    if result.get("recipe_path"):
        console.print(f"[green]已写出: {result['recipe_path']}[/green]")
        if result.get("overwritten"):
            # R2-D-03：explicit 覆盖受保护 recipes/ 既有原件时明示，消除盲写
            console.print("[yellow]⚠ 已覆盖受保护 recipes/ 既有原件"
                          "（overwritten=true）[/yellow]")


@agent_app.command("propose")
def agent_propose_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    params: str = typer.Option("{}", "--params", "-p", help="参数覆盖 JSON"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
    from_diagnosis: str = typer.Option(None, "--from-diagnosis", help="从 run_id 诊断结果生成提案"),
) -> None:
    """提案模式：L1/L2 Gate 校验 + L3 确认 token（不执行）。

    --from-diagnosis: 读取指定 run 的诊断结果，自动生成参数调整提案。
    """
    from rfauto.service.api import agent_propose

    if from_diagnosis:
        # Load diagnosis from run's metrics.json
        meta_path = Path("runs") / from_diagnosis / "results" / "metrics.json"
        if not meta_path.exists():
            console.print(f"[red]未找到 run 指标: {from_diagnosis}[/red]")
            raise typer.Exit(code=1)
        metrics_data = json.loads(meta_path.read_text(encoding="utf-8"))
        diagnosis = metrics_data.get("diagnosis", {})
        if not diagnosis or not diagnosis.get("diagnoses"):
            console.print("[yellow]该 run 无诊断触发（所有规则通过）[/yellow]")
            raise typer.Exit(code=0)
        # Generate params from diagnosis initial_values
        params_override = diagnosis.get("initial_values", {})
        console.print(f"[cyan]从诊断结果生成提案（{len(diagnosis['diagnoses'])} 条规则触发）[/cyan]")
        for d in diagnosis["diagnoses"]:
            console.print(f"  [{d.get('severity', '?')}] {d.get('rule_id', '?')}: {d.get('description', '')}")
            if d.get("hint"):
                console.print(f"    建议: {d['hint']}")
        params = json.dumps(params_override)

    try:
        params_override = json.loads(params)
    except json.JSONDecodeError as e:
        console.print(f"[red]✗ --params 不是合法 JSON: {e}[/red]")
        raise typer.Exit(code=1) from None

    result = agent_propose(recipe, params_override, adapter_name=adapter)
    if not result.get("ok"):
        console.print(f"[red]✗ 提案被拒（{result.get('stage', '?')}）[/red]")
        gate = result.get("gate", {})
        for v in gate.get("violations", []) + gate.get("issues", []):
            console.print(f"  [red]- {v}[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]✓ 提案通过三层 Gate[/green]")
    console.print(f"  token: [cyan]{result['token']}[/cyan]")
    console.print(f"  生效参数: {result['effective_params']}")
    console.print("  执行: rfauto agent apply <recipe> --token <token> --params '<json>'")


@agent_app.command("apply")
def agent_apply_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    token: str = typer.Option(..., "--token", "-t", help="propose 返回的确认 token"),
    params: str = typer.Option("{}", "--params", "-p", help="参数覆盖 JSON（须与 propose 一致）"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
) -> None:
    """执行模式：校验 token 后真实运行（参数被篡改会被哈希校验拒绝）。"""
    from rfauto.service.api import agent_apply

    try:
        params_override = json.loads(params)
    except json.JSONDecodeError as e:
        console.print(f"[red]✗ --params 不是合法 JSON: {e}[/red]")
        raise typer.Exit(code=1) from None

    result = agent_apply(recipe, token, params_override, adapter_name=adapter)
    if not result.get("ok"):
        console.print("[red]✗ 执行失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ 执行完成[/green]  run_id: {result.get('run_id')}")
    for k, v in result.get("metrics", {}).items():
        console.print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")


# ─── kicad (E7a P-Cell 生成 + DRC gate) ──────────────────────────────────────

kicad_app = typer.Typer(help="KiCad 板级链路（E7a：P-Cell 生成 + DRC gate）")
app.add_typer(kicad_app, name="kicad")


@kicad_app.command("pcb")
def kicad_pcb(
    design_json: str = typer.Argument(..., help="PCB 设计描述 JSON（PCBDesign schema）"),
    output: str = typer.Option(..., "--output", "-o", help="输出 .kicad_pcb 路径"),
) -> None:
    """从 JSON 设计描述生成 KiCad PCB（子进程调用 KiCad Python 3.11）。

    JSON 最小示例（微带功分板）：
    {"board_size": [50, 30], "traces": [{"name":"tl1","layer":"F.Cu",
      "width_mm":0.33,"points":[[10,15],[30,15]]}]}
    """
    from rfauto.adapters.kicad_pcell import PCBDesign, generate_pcb

    try:
        design = PCBDesign.from_dict(json.loads(Path(design_json).read_text(encoding="utf-8")))
    except FileNotFoundError:
        console.print(f"[red]✗ 设计描述文件不存在: {design_json}[/red]")
        raise typer.Exit(code=1) from None
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        console.print(f"[red]✗ 设计描述解析失败: {e}[/red]")
        raise typer.Exit(code=1) from None

    result = generate_pcb(output, design)
    if result.success:
        console.print(f"[green]✓ PCB 已生成[/green]  {result.output_path}")
    else:
        console.print("[red]✗ PCB 生成失败[/red]")
        console.print(f"  {result.message}")
        raise typer.Exit(code=1)


@kicad_app.command("drc")
def kicad_drc_cmd(
    pcb: str = typer.Argument(..., help="要检查的 .kicad_pcb 文件"),
    report: str = typer.Option(None, "--report", "-r", help="DRC 报告输出路径"),
) -> None:
    """KiCad DRC/RF 规则门禁（errors 阻断，warnings 告警）。"""
    from rfauto.adapters.kicad_drc import generate_drc_report, run_drc_kicad

    result = run_drc_kicad(pcb)
    if report:
        generate_drc_report(result, report)
        console.print(f"  报告: {report}")

    status = (
        "[green]✓ DRC 通过[/green]" if result.passed
        else f"[red]✗ DRC 未通过（{result.n_errors} errors / {result.n_warnings} warnings）[/red]"
    )
    console.print(status)
    for v in result.violations:
        console.print(f"  [{v.severity}] {v.rule_name}: {v.message}")
    if not result.passed:
        raise typer.Exit(code=1)


@kicad_app.command("extract")
def kicad_extract_cmd(
    pcb: str = typer.Argument(..., help=".kicad_pcb 文件"),
    output: str = typer.Option(None, "--output", "-o", help="提取产物 JSON 输出路径（缺省打印）"),
    kicad_python: str = typer.Option(None, "--kicad-python",
                                     help="KiCad 自带 Python（缺省取模块内置常量路径）"),
) -> None:
    """从 .kicad_pcb 提取叠层/走线/过孔/板框/zone/footprint（B6 stage-2，子进程 KiCad Python）。"""
    from rfauto.service.kicad_em_service import extract_pcb_facts

    result = extract_pcb_facts(pcb, kicad_python=kicad_python)
    if not result.get("ok"):
        console.print("[red]✗ 提取失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    text = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text, encoding="utf-8")
        board = result.get("board") or {}
        console.print(f"[green]✓ 提取完成[/green] → {output}"
                      f"（走线 {len(result.get('traces') or [])} / zone {len(result.get('zones') or [])}"
                      f" / footprint {len(result.get('footprints') or [])}，"
                      f"{board.get('layer_count', '?')} 层）")
    else:
        console.print_json(text)


@kicad_app.command("optimize")
def kicad_optimize_cmd(
    pcb: str = typer.Argument(..., help=".kicad_pcb 文件"),
    target_z0: float = typer.Option(None, "--target-z0", help="目标阻抗 Ω（缺省 50）"),
    freq: float = typer.Option(None, "--freq", "-f", help="工作频率 GHz（缺省 2.5）"),
    tol: float = typer.Option(None, "--tol", help="判据容差 Ω（缺省 2）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """PCB 提取 → CPWG 闭式代理寻优环（|z0−target|≤tol 判据；FAIL 附确定性修正 w*）。"""
    from rfauto.service.kicad_em_service import optimize_cpw_from_pcb

    result = optimize_cpw_from_pcb(pcb, target_z0_ohm=target_z0, freq_ghz=freq,
                                   z0_tol_ohm=tol)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        raise typer.Exit(code=0 if result.get("ok") and result.get("verdict") == "PASS" else 1)
    if not result.get("ok"):
        console.print(f"[red]✗ 寻优失败（{result.get('stage', 'optimize')}）[/red]")
        for err in result.get("errors") or [result.get("error")]:
            if err:
                console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    d, a, o = result["design"], result["analysis"], result["optimization"]
    color = "green" if result["verdict"] == "PASS" else "red"
    console.print(f"[{color}]● CPWG 寻优 {result['verdict']}[/{color}]（容差 ±{result['z0_tol_ohm']} Ω）")
    console.print(f"  提取: w={d['w_mm']} mm  gap={d['gap_mm']} mm  h={d['h_mm']} mm  er={d['er']}")
    console.print(f"  z0_extracted={a['z0_extracted_ohm']} Ω  εeff={a['eps_eff_extracted']}")
    console.print(f"  w*={o['w_opt_mm']:.4f} mm → z0={o['z0_opt_ohm']} Ω  Δw={o['delta_w_mm']} mm")
    if result["verdict"] != "PASS":
        raise typer.Exit(code=1)


# ─── recipe（方向 7：配方版本管理）──────────────────────────────────────────────

recipe_app = typer.Typer(help="配方版本管理（方向 7）")
app.add_typer(recipe_app, name="recipe")


@recipe_app.command("migrate")
def recipe_migrate_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
) -> None:
    """迁移配方到当前版本（添加 recipe_version 字段）。

    方向 7 可复现基建：确保所有配方有版本标记，支持后续 schema 演进。
    """
    from rfauto.service.api import recipe_migrate

    result = recipe_migrate(recipe)
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
) -> None:
    """配方 → agent skill（SKILL.md + frontmatter，阶段 2.4）。"""
    from rfauto.service.skill_service import write_skill

    result = write_skill(recipe, output_dir=output)
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
) -> None:
    """导出可复现包（配方快照 + 求解器输入 + S 参数 + reproduce.py）。

    方向 7 验收口径：任一历史 run 的 repro 包在干净 venv 中可重建并跑通 fake 档。
    """
    from rfauto.service.api import repro_export

    result = repro_export(run_id, output_dir=output)
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


# ─── p0 (方向 1 前置实验) ───────────────────────────────────────────────────────

@app.command("p0")
def p0_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    seed: int = typer.Option(42, "--seed", help="Optuna seed"),
    coarse: int = typer.Option(40, "--coarse", help="低保真粗筛试验数"),
    fine: int = typer.Option(15, "--fine", help="高保真精算试验数"),
    baseline: int = typer.Option(30, "--baseline", help="纯 fake 基线试验数"),
    edge: int = typer.Option(20, "--edge-samples", help="边缘采样数"),
    high_adapter: str = typer.Option("fake", "--high-adapter",
                                     help="跨保真 gate 的高保真适配器（fake|openems|hfss）。"
                                          "fake=自比较，gate 关闭，verdict=INCONCLUSIVE"),
    cross: int = typer.Option(15, "--cross-samples", help="跨保真对照采样数"),
) -> None:
    """方向 1 P0 实验：多保真验证（fake 先行）。

    硬门槛（跨保真 gate）：同一组参数在低/高保真下的排序一致性
    Spearman rho >= 0.8 且 top-5 recall >= 80%；不达标则方向 1 回退 fake-only。
    """
    from rfauto.service.api import run_p0_experiment

    console.print(f"[cyan]P0 实验: {recipe}[/cyan]")
    console.print(f"  基线: {baseline} trials | 粗筛: {coarse} + 精算: {fine}")
    console.print(f"  跨保真 gate: fake vs {high_adapter}（{cross} 样本）")

    result = run_p0_experiment(
        recipe,
        seed=seed,
        coarse_trials=coarse,
        fine_trials=fine,
        baseline_trials=baseline,
        edge_samples=edge,
        high_adapter=high_adapter,
        cross_samples=cross,
    )

    if not result.get("ok"):
        console.print("[red]P0 实验失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    corr = result.get("correlation", {})
    verdict = result.get("verdict", "UNKNOWN")
    verdict_color = {"PASS": "green", "FAIL": "red"}.get(verdict, "yellow")

    console.print(f"\n[bold {verdict_color}]Verdict: {verdict}[/bold {verdict_color}]")
    rho_v = corr.get("spearman_rho")
    rho_str = f"{rho_v:.4f}" if rho_v is not None else "N/A"
    console.print(f"  [self] Spearman rho: {rho_str}")
    cross_r = result.get("cross_fidelity", {})
    # 自比较/gate 关闭时 rho/recall 为 None——渲染 N/A 而非裸 "None"
    cross_rho = cross_r.get("spearman_rho")
    cross_recall = cross_r.get("top5_recall")
    console.print(f"  [cross vs {cross_r.get('high_adapter')}] "
                  f"rho={cross_rho if cross_rho is not None else 'N/A'}, "
                  f"recall={cross_recall if cross_recall is not None else 'N/A'}, "
                  f"n={cross_r.get('n_evaluated')}, "
                  f"gate={result.get('gate')}")
    console.print(f"  耗时: {result.get('elapsed_s', 0)}s")
    if verdict == "FAIL":
        console.print("[yellow]方向 1 应回退为 fake-only[/yellow]")
    if verdict == "INCONCLUSIVE":
        console.print("[yellow]自比较不产出跨保真证据——用 --high-adapter openems|hfss 重跑[/yellow]")


# ─── study (方向 6a/4d: 人机参数注入) ──────────────────────────────────────

study_app = typer.Typer(help="人机参数注入研究（方向 6a/4d）")
app.add_typer(study_app, name="study")


@study_app.command("inject")
def study_inject_cmd(
    study: str = typer.Argument(..., help="Optuna study 名称"),
    params: str = typer.Argument(..., help="参数 JSON，如 '{\"arm_len_mm\": 20.5}'"),
    source: str = typer.Option("human", "--source", "-s", help="来源标签: human|llm|tpe"),
) -> None:
    """向 Optuna study 注入人工参数（ask-and-tell）。

    方向 6a/4d：trial_source 标签写入 user_attrs，审计落盘。
    """
    import json as _json

    from rfauto.service.api import study_inject

    try:
        params_dict = _json.loads(params)
    except _json.JSONDecodeError as e:
        console.print(f"[red]params 不是合法 JSON: {e}[/red]")
        raise typer.Exit(code=1) from None

    result = study_inject(study, params_dict, source=source)
    if not result.get("ok"):
        console.print("[red]注入失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]参数已注入 study '{result['study_name']}'[/green]")
    console.print(f"  trial #{result['trial_number']}")
    console.print(f"  来源: {result['source']}")

# ─── sensitivity (方向 8b: 灵敏度分析) ────────────────────────────────────────────────

@app.command("sensitivity")
def sensitivity_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    method: str = typer.Option("sobol", "--method", "-m", help="方法: sobol | morris"),
    samples: int = typer.Option(100, "--samples", "-n", help="采样数"),
    seed: int = typer.Option(42, "--seed", help="随机种子"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
) -> None:
    """灵敏度分析：Sobol/Morris 参数重要度排序（方向 8b）。

    输出一阶/总阶灵敏度索引，top 候选进调优报告。
    """
    from rfauto.service.api import run_sensitivity

    console.print(f"[cyan]灵敏度分析: {recipe}[/cyan]")
    console.print(f"  方法: {method}, 采样: {samples}, seed: {seed}")

    result = run_sensitivity(recipe, method=method, n_samples=samples, seed=seed, adapter_name=adapter)
    if not result.get("ok"):
        console.print("[red]灵敏度分析失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    sens = result.get("sensitivity", {})
    console.print(f"\n[bold]灵敏度分析结果[/bold] ({result.get('method', '?')}, {result.get('n_samples', '?')} samples)")

    table = Table(title="Parameter Sensitivity")
    table.add_column("参数", style="cyan")
    if result.get("method") == "morris":
        table.add_column("mu*", justify="right")
        table.add_column("sigma", justify="right")
        for name, vals in sorted(sens.items(), key=lambda x: -x[1].get("mu_star", 0)):
            table.add_row(name, f"{vals['mu_star']:.4f}", f"{vals['sigma']:.4f}")
    else:
        table.add_column("S1 (first-order)", justify="right")
        table.add_column("ST (total-order)", justify="right")
        for name, vals in sorted(sens.items(), key=lambda x: -x[1].get("S1", 0)):
            table.add_row(name, f"{vals['S1']:.4f}", f"{vals['ST']:.4f}")
    console.print(table)


# ─── enhanced-report (方向 8c: 调优报告增强) ───────────────────────────────────────

@app.command("tuning-report")
def tuning_report_cmd(
    run_id: str = typer.Argument(..., help="run_id"),
    output: str = typer.Option(None, "--output", "-o", help="输出文件路径"),
) -> None:
    """生成增强调优报告（方向 8c）：指标摘要 + 诊断 + 可复现信息。"""
    from rfauto.service.api import generate_enhanced_report

    result = generate_enhanced_report(run_id, output=output)
    if not result.get("ok"):
        console.print("[red]报告生成失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    if output:
        console.print(f"[green]报告已生成: {result['report']}[/green]")
    else:
        console.print(result.get("report_text", ""))


# ─── audit (方向 6f: 审计日志查看) ───────────────────────────────────────────────────────

@app.command("audit")
def audit_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="显示条数"),
    event: str = typer.Option(None, "--event", "-e", help="过滤事件类型: propose|apply|study_inject"),
    quality: bool = typer.Option(False, "--quality", "-q", help="输出 4b 提议质量指标（接受率/改进率/否决原因）"),
) -> None:
    """查看 Agent 审计日志（audit.jsonl）。

    方向 6f 验收口径：UI 里浏览 audit.jsonl（propose/apply 全链、token 哈希、来源标签）。
    """
    audit_path = Path("runs") / "agent_proposals" / "audit.jsonl"
    if quality:
        from rfauto.service.api import agent_quality_summary
        summary = agent_quality_summary()
        console.print("[cyan]4b 提议质量指标[/cyan]")
        console.print(f"  总 propose 数: {summary['total_proposes']}")
        console.print(f"  接受（apply/approve 成功）: {summary['accepted']}  "
                      f"接受率: {summary['accept_rate'] if summary['accept_rate'] is not None else 'N/A'}")
        console.print(f"  平均改进率: {summary['avg_improvement'] if summary['avg_improvement'] is not None else 'N/A'}"
                      f"（样本 {summary.get('n_improvement_samples', 0)}，仅 fake 档）")
        if summary["rejections"]:
            console.print("  否决原因分类:")
            for stage, n in sorted(summary["rejections"].items()):
                console.print(f"    {stage}: {n}")
        else:
            console.print("  否决: 无")
        return

    if not audit_path.exists():
        console.print("[yellow]审计日志不存在（尚无 Agent 操作记录）[/yellow]")
        return

    entries = []
    for line in audit_path.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if event and entry.get("event") != event:
                continue
            entries.append(entry)
        except json.JSONDecodeError:
            continue

    if not entries:
        console.print("[yellow]无匹配的审计记录[/yellow]")
        return

    # Show most recent first
    entries = entries[-limit:]
    entries.reverse()

    table = Table(title=f"审计日志 (最近 {len(entries)} 条)")
    table.add_column("时间", style="dim")
    table.add_column("事件", style="cyan")
    table.add_column("状态")
    table.add_column("详情")

    for e in entries:
        ts = e.get("timestamp", "?")
        evt = e.get("event", "?")
        ok = e.get("ok", False)
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        detail_parts = []
        if e.get("recipe"):
            detail_parts.append(f"recipe={Path(e['recipe']).name}")
        if e.get("token_hash"):
            detail_parts.append(f"token={e['token_hash'][:8]}...")
        if e.get("source"):
            detail_parts.append(f"source={e['source']}")
        if e.get("run_id"):
            detail_parts.append(f"run={e['run_id']}")
        if e.get("reason"):
            detail_parts.append(f"reason={e['reason'][:40]}")
        detail = " | ".join(detail_parts) if detail_parts else "-"
        table.add_row(str(ts)[:19], evt, status, detail)

    console.print(table)


# ─── solvers (方向 6g/6h: 求解器可视化+管理) ────────────────────────────────────────────────

solvers_app = typer.Typer(help="求解器管理（方向 6g/6h）")
app.add_typer(solvers_app, name="solvers")


@solvers_app.command("list")
def solvers_list() -> None:
    """列出已注册求解器及其可视化能力（方向 6g/6h）。"""
    from rfauto.service.r3_services import list_registered_solvers
    result = list_registered_solvers()
    if not result.get("ok"):
        console.print("[red]✗ 查询失败[/red]")
        raise typer.Exit(code=1)

    table = Table(title="已注册求解器")
    table.add_column("名称", style="cyan")
    table.add_column("类")
    table.add_column("可用")
    table.add_column("可视化")
    for s in result["solvers"]:
        avail = "[green]✓[/green]" if s["available"] else "[red]✗[/red]"
        table.add_row(s["type"], s["class"], avail, str(s["n_visualizations"]))
    console.print(table)


@solvers_app.command("viz")
def solvers_viz(
    solver: str = typer.Option(None, "--solver", "-s", help="指定求解器"),
) -> None:
    """列出求解器可视化产物声明（方向 6g 产物视图协议）。"""
    from rfauto.service.r3_services import list_solver_visualizations
    result = list_solver_visualizations(solver)
    if not result.get("ok"):
        console.print("[red]✗ 查询失败[/red]")
        raise typer.Exit(code=1)
    console.print_json(json.dumps(result, indent=2, ensure_ascii=False))


@solvers_app.command("add")
def solvers_add(
    name: str = typer.Argument(..., help="求解器名称"),
    type_: str = typer.Option(..., "--type", "-t", help="求解器类型 (openems/hfss/fake/palace/...)"),
    exe: str = typer.Option(None, "--exe", help="可执文件路径"),
) -> None:
    """添加求解器到 configs/solvers.yaml（方向 6h）。"""
    from rfauto.service.r3_services import add_solver_to_config
    result = add_solver_to_config(name, type_, exe_path=exe)
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('errors', ['失败'])}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ 求解器 '{name}' 已添加[/green]")


# ─── simci（阶段 7.5：仿真 CI 夜间回归）─────────────────────────────────────

@app.command("simci")
def simci_cmd(
    recipes_dir: str = typer.Argument("recipes", help="配方目录"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="回归通道（fake 零成本）"),
    tolerance: float = typer.Option(1.0, "--tolerance", help="指标劣化容差 dB"),
) -> None:
    """全配方夜间回归：validate+run → 对照 runs 索引历史基线 → diff 报告。"""
    from rfauto.service.sim_ci_service import nightly_regression

    console.print(f"[cyan]仿真 CI 回归: {recipes_dir}（{adapter} 通道）[/cyan]")
    result = nightly_regression(recipes_dir, adapter=adapter,
                                tolerance_db=tolerance)
    if not result.get("ok"):
        console.print("[red]✗ 回归失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    color = "green" if result["n_regressions"] == 0 else "red"
    console.print(f"[{color}]● 回归完成：{result['n_done']}/{result['n_recipes']} 配方，"
                  f"{result['n_regressions']} 个劣化[/{color}]")
    console.print(f"  run_id: {result['run_id']}")
    for reg in result.get("regressions", []):
        console.print(f"  [red]劣化 {reg['recipe']}: {reg['metric']} "
                      f"{reg['baseline']}→{reg['current']}（{reg['delta_db']:+.2f}dB）[/red]")
    console.print(f"  报告: {result['run_dir']}\\sim_ci_report.md")


# ─── inbox (方向 6i: 审批收件箱) ───────────────────────────────────────────────────

@app.command("inbox")
def inbox_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="显示条数"),
    approve: str = typer.Option(None, "--approve", "-a", help="批准指定 token 的提案"),
    recipe: str = typer.Option(None, "--recipe", "-r", help="配方路径（approve 时必填）"),
) -> None:
    """审批收件箱：查看/批准待确认的 Agent 提案（方向 6i）。"""
    from rfauto.service.r3_services import approve_proposal, list_pending_approvals

    if approve:
        if not recipe:
            console.print("[red]✗ --approve 需要 --recipe 指定配方路径[/red]")
            raise typer.Exit(code=1)
        result = approve_proposal(approve, recipe)
        if result.get("ok"):
            console.print(f"[green]✓ 提案已批准执行[/green]  run_id: {result.get('run_id', '?')}")
        else:
            console.print(f"[red]✗ 批准失败: {result.get('errors', [])}[/red]")
            raise typer.Exit(code=1)
        return

    result = list_pending_approvals(limit=limit)
    if not result["pending"]:
        console.print("[green]无待审批项[/green]")
        return

    table = Table(title=f"审批收件箱 ({result['total']} 待处理)")
    table.add_column("时间", style="dim")
    table.add_column("Token", style="cyan")
    table.add_column("配方")
    table.add_column("参数")
    table.add_column("操作")

    for e in result["pending"]:
        ts = str(e.get("timestamp", "?"))[:19]
        token = e.get("token_hash", "?")[:12] + "..."
        recipe_name = Path(e.get("recipe", "?")).name
        params = json.dumps(e.get("params", {}), ensure_ascii=False)[:40]
        table.add_row(ts, token, recipe_name, params, f"inbox --approve {e.get('token_hash','')[:8]} --recipe {e.get('recipe','')}")

    console.print(table)


# ─── chat (方向 6j: LLM 对话窗) ─────────────────────────────────────────────────────

@app.command("chat")
def chat_cmd(
    message: str = typer.Argument(..., help="消息内容"),
    channel: str = typer.Option("service", "--channel", "-c",
                                help="通道选择（6j 双通道）: service（内嵌，默认）| mcp（MCP 客户端）"),
) -> None:
    """LLM 对话窗（方向 6j 双通道可选）：内嵌 service 直调 或 MCP 客户端。

    两路同源（同一批 service 函数）、同审计（audit.jsonl）。默认内嵌通道；
    习惯 Claude/Codex 的用户或外部编排可选 mcp 通道。
    """
    if channel == "mcp":
        from rfauto.cli.mcp_chat import MCPAgentChat
        chat = MCPAgentChat()
    elif channel == "service":
        from rfauto.service.r3_services import AgentChat
        chat = AgentChat()
    else:
        console.print(f"[red]未知通道: {channel}（可选 service | mcp）[/red]")
        raise typer.Exit(code=1)
    result = chat.chat(message)
    console.print(result["text"])
    if result.get("action") != "help":
        console.print(f"[dim]动作: {result.get('action', '?')}（通道: {channel}）[/dim]")


# ─── calc (E4 微波计算器) ─────────────────────────────────────────────────────

calc_app = typer.Typer(help="微波闭式计算器（E4：mm/GHz/Ω/dB 口径）")
app.add_typer(calc_app, name="calc")


def _coerce_param(raw: str):
    """"50"→50、"3.66"→3.66、"true"→true，解析失败保留字符串。"""
    import json as _json

    try:
        return _json.loads(raw)
    except ValueError:
        return raw


@calc_app.command("list")
def calc_list(
    include_experimental: bool = typer.Option(
        True, "--experimental/--no-experimental",
        help="是否列出实验性公式（experimental=True 键，默认列出并打 [实验] 标签）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """列出全部计算器与参数表（实验键带 [实验] 标签，运行需 --allow-experimental）。"""
    from rfauto.service.calculator_service import list_calculators

    result = list_calculators(include_experimental=include_experimental)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False))
        raise typer.Exit(code=0)
    for calc in result["calculators"]:
        tag = "  [yellow][实验][/yellow]" if calc.get("experimental") else ""
        console.print(f"[bold cyan]{calc['name']}[/bold cyan]{tag}  {calc['description']}")
        for p in calc["params"]:
            tag = "必填" if p["required"] else "可选"
            console.print(f"    {p['name']}  [dim]{p['desc']}（{tag}）[/dim]")
    n_exp = int(result.get("n_experimental") or 0)
    if n_exp:
        shown = "已列出" if include_experimental else "已隐藏（--experimental 查看）"
        console.print(
            f"[dim]实验性公式 {n_exp} 个（{shown}）：默认拒跑，"
            f"rfauto calc run --allow-experimental 或配置 "
            f"calculators.allow_experimental: true 放行[/dim]")
    raise typer.Exit(code=0)


@calc_app.command("run")
def calc_run(
    name: str = typer.Argument(..., help="计算器名（rfauto calc list 查看）"),
    param: list[str] | None = typer.Option(None, "--param", "-p",  # noqa: B008
                                           help="参数 k=v（可重复）"),
    allow_experimental: bool | None = typer.Option(
        None, "--allow-experimental/--no-experimental",
        help="实验性公式放行开关：--allow-experimental 显式放行；"
             "--no-experimental 显式拒绝（优先于配置）；缺省读配置 "
             "calculators.allow_experimental / 环境变量 "
             "RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """执行计算器。

    示例：rfauto calc run microstrip_synthesis -p z0_ohm=50 -p freq_ghz=2.4
          -p epsilon_r=3.66 -p h_mm=0.508
    实验性公式（rfauto calc list 标 [实验]）默认拒跑，需 --allow-experimental。
    """
    from rfauto.service.calculator_service import run_calculator

    params: dict = {}
    for item in param or []:
        key, sep, raw = item.partition("=")
        if not sep:
            console.print(f"[red]✗ --param 需要 k=v 形式: {item}[/red]")
            raise typer.Exit(code=1)
        params[key.strip()] = _coerce_param(raw.strip())

    result = run_calculator(name, params, allow_experimental=allow_experimental)
    if json_output:
        # JSON 信封完整输出后，ok=False 仍以非零退出码报败（与 _emit 口径一致，
        # 脚本消费方靠 exit code 判成败而非解析信封）
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False))
        if not result["ok"]:
            raise typer.Exit(code=1)
    elif result["ok"]:
        exp_tag = "  [yellow][实验][/yellow]" if result.get("experimental") else ""
        console.print(f"\n[bold]{name}[/bold]{exp_tag}")
        for key, value in result["result"].items():
            console.print(f"  {key}: [cyan]{value}[/cyan]")
    else:
        console.print(f"[red]✗ {result['error']}[/red]")
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


# ─── sparams-compare (E8 Touchstone 导入对比) ────────────────────────────────


@app.command("sparams-compare")
def sparams_compare_cmd(
    run_id: str = typer.Argument(..., help="基准 run（其 results/*.sNp 为基准曲线）"),
    file: list[str] | None = typer.Option(None, "--file", "-f",  # noqa: B008
                                          help="外部 Touchstone 文件（可多次）"),
    out: str | None = typer.Option(None, "--out", "-o",
                                   help="输出 PNG 路径（默认 runs/sparams_compare/<时间戳>.png）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """run 与外部 .sNp 的 S 参数叠画对比（dB，WP0.3/E8）。

    示例：rfauto sparams-compare 20260905_032407_e643d139 -f demo_BP.s2p
    """
    from rfauto.service.ui_service import sparams_compare_png

    result = sparams_compare_png(run_id, list(file or []), out_path=out)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["ok"]:
        console.print(
            f"[green]✓ 对比图已生成[/green] → [cyan]{result['png']}[/cyan]"
            f"（{result['n_curves']} 条曲线 / {result['n_sources']} 个来源）")
    else:
        console.print(
            f"[red]✗ {'; '.join(result.get('errors') or ['未知错误'])}[/red]")
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


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


# ─── warm-start (数据面：数据集历史样本 → 先验注入) ───────────────

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
) -> None:
    """数据集历史样本 → warm-start 先验注入优化（相似度门在 warm_start 内）。"""
    from rfauto.service.warm_start_data import run_optimization_warm_start_from_dataset

    result = run_optimization_warm_start_from_dataset(
        recipe, dataset, model=model, source_study=source_study, limit=limit,
        adapter_name=adapter, max_trials=max_trials, study_name=study_name,
    )
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


# ═══ WP3.3 CLI 半边 + 全仓 scattered 薄壳（cli-mcp-api-shell-bundle）═══════════
# 全部零逻辑转发 service（规则 4）；数值只在确定性内核（铁律 7）。
# 与 mcp_server.py 同源同名 service 函数，JSON 进出。


def _emit(result: dict, fail_msg: str, *, json_output: bool = True) -> None:
    """薄壳共用出口：ok=False → 红字 errors/error + 退出码 1；否则 JSON 直出。"""
    if not result.get("ok"):
        console.print(f"[red]✗ {fail_msg}[/red]")
        errs = result.get("errors") or ([result["error"]] if result.get("error") else [])
        for err in errs:
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def _load_json_file(path: str, what: str) -> dict:
    """读 JSON 对象文件（payload 型命令共用；不存在/非对象 → 退出码 2）。"""
    p = Path(path)
    if not p.exists():
        console.print(f"[red]✗ {what}不存在: {p}[/red]")
        raise typer.Exit(code=2)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        console.print(f"[red]✗ {what}不可读: {exc}[/red]")
        raise typer.Exit(code=2) from None
    if not isinstance(data, dict):
        console.print(f"[red]✗ {what}必须是 JSON 对象[/red]")
        raise typer.Exit(code=2)
    return data


def _kv_floats(items: list[str] | None, flag: str) -> dict[str, float]:
    """--flag 名=值（可多次）→ {名: float}。"""
    out: dict[str, float] = {}
    for item in items or []:
        if "=" not in item:
            console.print(f"[red]✗ {flag} 格式应为 参数名=值：{item}[/red]")
            raise typer.Exit(code=2)
        name, _, val = item.partition("=")
        try:
            out[name.strip()] = float(val)
        except ValueError:
            console.print(f"[red]✗ {flag} 值不是数字：{item}[/red]")
            raise typer.Exit(code=2) from None
    return out


# ─── bench（WP3.7/F6 回归门；bench_app 在文件头导入） ─────
app.add_typer(bench_app, name="bench")


# ─── bands（D9 频段/环境包络注册表十接口；WP3.3 CLI 半边） ───────────────

bands_app = typer.Typer(help="标准频段/环境包络注册表（D9，十接口；数值只出自 core/bands 常量表）")
app.add_typer(bands_app, name="bands")


@bands_app.command("list")
def bands_list_cmd(
    standard: str = typer.Option(None, "--standard", help="按 standard 子串过滤（如 3GPP）"),
    kind: str = typer.Option(None, "--kind", help="按类型过滤（cellular/ism/...）"),
    region: str = typer.Option(None, "--region", help="按区域过滤"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """列出标准频段注册表（3GPP/Wi-Fi/UWB/ISM/EMC 等，自动生成清单）。"""
    from rfauto.service.bands_service import bands_list

    result = bands_list(standard=standard, kind=kind, region=region)
    _emit(result, "频段查询失败", json_output=json_output)
    if json_output:
        return
    table = Table(title=f"频段注册表（{result['count']}/{result['total']}）")
    for col in ("key", "standard", "kind", "f_low_ghz", "f_high_ghz", "region"):
        table.add_column(col, style="cyan" if col == "key" else None)
    for b in result["bands"]:
        table.add_row(*(str(b.get(c, "")) for c in
                        ("key", "standard", "kind", "f_low_ghz", "f_high_ghz", "region")))
    console.print(table)


@bands_app.command("get")
def bands_get_cmd(key: str = typer.Argument(..., help="频段键（如 gpp_n78）")) -> None:
    """按 key 取单条频段详情（边界/出处/区域）。"""
    from rfauto.service.bands_service import bands_get

    _emit(bands_get(key), f"未知频段 {key}")


@bands_app.command("find")
def bands_find_cmd(freq_ghz: float = typer.Argument(..., help="频率 GHz")) -> None:
    """查包含给定频率的全部频段条目。"""
    from rfauto.service.bands_service import bands_find

    _emit(bands_find(freq_ghz), "频率查询失败")


@bands_app.command("spec-bounds")
def bands_spec_bounds_cmd(key: str = typer.Argument(..., help="频段键")) -> None:
    """频段键 → SpecEvaluator band 结构 {"band": [f_low, f_high]}（喂 objectives）。"""
    from rfauto.service.bands_service import bands_spec_bounds

    _emit(bands_spec_bounds(key), f"未知频段 {key}")


@bands_app.command("env-list")
def bands_env_list_cmd(
    standard: str = typer.Option(None, "--standard", help="按 standard 子串过滤"),
    kind: str = typer.Option(None, "--kind", help="按类型过滤"),
) -> None:
    """列出环境包络注册表（工业/AEC-Q100/ECSS/IEC 60068 温区等级）。"""
    from rfauto.service.bands_service import bands_env_list

    _emit(bands_env_list(standard=standard, kind=kind), "环境包络查询失败")


@bands_app.command("env-get")
def bands_env_get_cmd(key: str = typer.Argument(..., help="环境包络键（如 aec_q100_grade1）")) -> None:
    """按 key 取单条环境包络详情（温区/等级/出处）。"""
    from rfauto.service.bands_service import bands_env_get

    _emit(bands_env_get(key), f"未知环境包络 {key}")


@bands_app.command("env-find")
def bands_env_find_cmd(t_c: float = typer.Argument(..., help="温度 °C")) -> None:
    """查温区覆盖给定温度的全部环境包络。"""
    from rfauto.service.bands_service import bands_env_find

    _emit(bands_env_find(t_c), "温度查询失败")


@bands_app.command("env-delta-t")
def bands_env_delta_t_cmd(
    key: str = typer.Argument(..., help="环境包络键"),
    t_ref_c: float = typer.Option(None, "--t-ref", help="参考温度 °C（缺省用条目自身）"),
) -> None:
    """环境包络 → ΔT 上下限（D3 温区扫描 / D8 UQ / WP4.2 良率消费）。"""
    from rfauto.service.bands_service import bands_env_delta_t

    _emit(bands_env_delta_t(key, t_ref_c), f"未知环境包络 {key}")


@bands_app.command("env-uq-axis")
def bands_env_uq_axis_cmd(
    key: str = typer.Argument(..., help="环境包络键"),
    t_ref_c: float = typer.Option(None, "--t-ref", help="参考温度 °C（缺省用条目自身）"),
    k_sigma: float = typer.Option(3.0, "--k-sigma", help="σ 倍数"),
) -> None:
    """环境包络 → UQ/良率温度轴（名义点 + σ + ΔT 上下限）。"""
    from rfauto.service.bands_service import bands_env_uq_axis

    _emit(bands_env_uq_axis(key, t_ref_c, k_sigma), f"未知环境包络 {key}")


@bands_app.command("env-points")
def bands_env_points_cmd(
    key: str = typer.Argument(..., help="环境包络键"),
    n: int = typer.Option(5, "--n", help="采样点数（含两端）"),
) -> None:
    """环境包络温区等距采样点（供 D3 温区扫描）。"""
    from rfauto.service.bands_service import bands_env_points

    _emit(bands_env_points(key, n), f"未知环境包络 {key}")


# ─── campaign（战役状态机：plan/status/event/list；WP3.3 CLI 半边） ───────────

campaign_app = typer.Typer(help="战役状态机（calibrate→prefilter→tune→tolerance→report→final_verify）")
app.add_typer(campaign_app, name="campaign")


@campaign_app.command("plan")
def campaign_plan_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    high_adapter: str = typer.Option("hfss", "--high-adapter", help="终验适配器（none=不加终验）"),
    mid_adapter: str = typer.Option("openems", "--mid-adapter", help="中保真精算适配器"),
    calibrate_samples: int = typer.Option(9, "--calibrate-samples", help="校准阶段样本预算"),
    tune_budget: int = typer.Option(None, "--tune-budget", help="tune 预算（缺省取配方 limits.max_trials/30）"),
    out_dir: str = typer.Option(None, "--out-dir", "-o", help="落盘目录（写 campaign.plan.json）"),
) -> None:
    """配方 → 确定性战役阶段队列（含依赖/预算/license 门槛）；--out-dir 落盘。"""
    from rfauto.service.campaign_manager import plan_campaign, save_plan

    plan = plan_campaign(recipe, high_adapter=high_adapter, mid_adapter=mid_adapter,
                         calibrate_samples=calibrate_samples, tune_budget=tune_budget)
    if not plan.get("ok"):
        _emit(plan, "立战役失败")
    if out_dir:
        path = save_plan(plan, out_dir)
        console.print(f"[green]✓ 战役计划已落盘[/green] → {path}")
    table = Table(title=f"战役阶段队列：{plan.get('model', '?')}（终验 {plan.get('high_adapter')}）")
    for col in ("stage", "kind", "adapter", "depends_on", "budget", "status"):
        table.add_column(col, style="cyan" if col == "stage" else None)
    for s in plan.get("stages", []):
        table.add_row(str(s.get("stage", "")), str(s.get("kind", "")), str(s.get("adapter", "")),
                      ",".join(s.get("depends_on") or []), str(s.get("budget", "")),
                      str(s.get("status", "")))
    console.print(table)


@campaign_app.command("status")
def campaign_status_cmd(
    plan_path: str = typer.Argument(..., help="campaign.plan.json 或其所在目录"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """读回已落盘战役计划的状态（verdict/各阶段 status/n_done/n_dead）。"""
    from rfauto.service.campaign_manager import load_plan

    result = load_plan(plan_path)
    _emit(result, "读取战役计划失败", json_output=json_output)
    if json_output:
        return
    plan = result["plan"]
    console.print(f"[bold]{result['path']}[/bold]  verdict={plan.get('verdict')}  "
                  f"done={plan.get('n_done')}  dead={plan.get('n_dead')}")
    for s in plan.get("stages", []):
        color = {"done": "green", "failed": "red", "aborted": "red",
                 "skipped": "dim"}.get(str(s.get("status")), "yellow")
        console.print(f"  [{color}]{s.get('status', '?'):<8}[/{color}] {s.get('stage')}"
                      f"{'  — ' + str(s['note']) if s.get('note') else ''}")


@campaign_app.command("event")
def campaign_event_cmd(
    plan_path: str = typer.Argument(..., help="campaign.plan.json 或其所在目录"),
    stage: str = typer.Argument(..., help="阶段名（calibrate/prefilter/tune/...）"),
    event: str = typer.Argument(..., help="stage_done | stage_failed | skip"),
    detail: str = typer.Option("", "--detail", help="事件说明"),
) -> None:
    """推进战役状态机（stage_failed 时依赖它的未完成阶段递归 aborted）并回写落盘。"""
    from rfauto.service.campaign_manager import apply_event, load_plan, save_plan

    loaded = load_plan(plan_path)
    if not loaded.get("ok"):
        _emit(loaded, "读取战役计划失败")
    result = apply_event(loaded["plan"], stage, event, detail=detail)
    if not result.get("ok"):
        _emit(result, "事件应用失败")
    plan = result.get("plan", loaded["plan"])
    save_plan(plan, Path(loaded["path"]).parent)
    console.print(f"[green]✓ {stage} ← {event}[/green]  verdict={plan.get('verdict')}  "
                  f"done={plan.get('n_done')}  dead={plan.get('n_dead')}")


@campaign_app.command("list")
def campaign_list_cmd(
    root: str = typer.Option("runs", "--root", help="扫描根目录"),
) -> None:
    """扫 root 下全部已落盘战役计划（总览）。"""
    from rfauto.service.campaign_manager import list_campaign_plans

    result = list_campaign_plans(root)
    if not result["campaigns"]:
        console.print(f"[yellow]{root} 下无战役计划[/yellow]")
        return
    table = Table(title=f"战役总览（{result['n_campaigns']}）")
    for col in ("path", "model", "verdict", "n_done", "n_dead", "n_stages"):
        table.add_column(col, style="cyan" if col == "path" else None)
    for c in result["campaigns"]:
        table.add_row(*(str(c.get(k, "")) for k in
                        ("path", "model", "verdict", "n_done", "n_dead", "n_stages")))
    console.print(table)


# ─── template-spec（E2 模板库注册表；WP3.3 CLI 半边） ─────────────────────────

template_spec_app = typer.Typer(help="模板库 TemplateSpec 注册表（E2：清单 + 综合草稿）")
app.add_typer(template_spec_app, name="template-spec")


@template_spec_app.command("list")
def template_spec_list_cmd(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """列出全部模板 spec（组件齐备性 render_script/synthesizer/fake_model/hfss_plugin）。"""
    from rfauto.service.template_spec_service import list_template_specs

    result = list_template_specs()
    _emit(result, "模板库查询失败", json_output=json_output)
    if json_output:
        return
    table = Table(title=f"模板库（{len(result['templates'])}）")
    table.add_column("name", style="cyan")
    for comp in ("render_script", "synthesizer", "fake_model", "hfss_plugin"):
        table.add_column(comp)
    table.add_column("physics_roles")
    for t in result["templates"]:
        comps = t.get("components") or {}
        table.add_row(t["name"],
                      *("[green]✓[/green]" if comps.get(c) else "[red]✗[/red]"
                        for c in ("render_script", "synthesizer", "fake_model", "hfss_plugin")),
                      ", ".join(sorted((t.get("physics_roles") or {}).keys())))
    console.print(table)


@template_spec_app.command("draft")
def template_spec_draft_cmd(
    name: str = typer.Argument(..., help="模板名（template-spec list 查看）"),
    param: list[str] | None = typer.Option(None, "--param", "-p",  # noqa: B008
                                           help="综合入口参数 k=v（可重复）"),
    output: str = typer.Option(None, "--output", "-o", help="配方草稿写出 YAML 路径"),
) -> None:
    """按模板 spec 的综合入口产出配方草稿（零求解、零 license；线宽等由综合内核精算）。"""
    from rfauto.service.template_spec_service import draft_recipe_from_spec

    params: dict = {}
    for item in param or []:
        key, sep, raw = item.partition("=")
        if not sep:
            console.print(f"[red]✗ --param 需要 k=v 形式: {item}[/red]")
            raise typer.Exit(code=2)
        params[key.strip()] = _coerce_param(raw.strip())
    result = draft_recipe_from_spec(name, params)
    if not result.get("ok"):
        _emit(result, f"模板 {name} 草稿生成失败")
    if output:
        # --output 由用户显式指定 → 显式保存入口；序列化/落盘走守卫统一出口
        from rfauto.infra.recipe_guard import write_recipe_yaml

        written = write_recipe_yaml(output, result["recipe_draft"], explicit=True)
        console.print(f"[green]✓ 配方草稿已写出[/green] → {written}")
        if getattr(written, "overwritten", False):
            # R2-D-03：explicit 覆盖受保护 recipes/ 既有原件时明示，消除盲写
            console.print("[yellow]⚠ 已覆盖受保护 recipes/ 既有原件"
                          "（overwritten=true）[/yellow]")
    else:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))


# ─── uq（WP4.2 良率收口三接口） ───────────────────────────────────────

uq_app = typer.Typer(help="公差/良率收口（WP4.2：名义点良率 / 设计中心化 / D9 温区良率）")
app.add_typer(uq_app, name="uq")


@uq_app.command("yield-at")
def uq_yield_at_cmd(
    samples: str = typer.Argument(..., help="校准样本集 samples.json"),
    tol: list[str] | None = typer.Option(None, "--tol", help="公差 σ 参数名=值（可多次）"),  # noqa: B008
    at: list[str] | None = typer.Option(None, "--at", help="名义点 参数名=值（可多次，须覆盖公差参数）"),  # noqa: B008
    n: int = typer.Option(10000, "--n", help="蒙特卡洛抽样数"),
    seed: int = typer.Option(42, "--seed", help="随机种子"),
    kind: str = typer.Option("poly_ridge", "--kind", help="代理类型 poly_ridge|nn"),
) -> None:
    """显式名义点的代理蒙特卡洛良率（良率目标函数点值形式）。"""
    from rfauto.service.uq_service import surrogate_yield_at

    _emit(surrogate_yield_at(samples, _kv_floats(tol, "--tol"), _kv_floats(at, "--at"),
                             n=n, seed=seed, kind=kind), "良率求值失败")


@uq_app.command("design-center")
def uq_design_center_cmd(
    samples: str = typer.Argument(..., help="校准样本集 samples.json"),
    tol: list[str] | None = typer.Option(None, "--tol", help="公差 σ 参数名=值（可多次）"),  # noqa: B008
    k_sigma: float = typer.Option(3.0, "--k-sigma", help="容差盒半宽 = k_sigma·σ"),
    n_levels: int = typer.Option(3, "--n-levels", help="每维网格层数"),
    max_iter: int = typer.Option(40, "--max-iter", help="坐标搜索最大迭代"),
    n_mc: int = typer.Option(2000, "--n-mc", help="前后认证 MC 抽样数"),
    seed: int = typer.Option(42, "--seed", help="随机种子"),
    kind: str = typer.Option("poly_ridge", "--kind", help="代理类型 poly_ridge|nn"),
) -> None:
    """良率目标函数 + 设计中心化（容差盒网格违约 cost≤0 良率，坐标搜索；MC 只做前后认证）。"""
    from rfauto.service.contracts import annotate_contract
    from rfauto.service.uq_service import yield_design_center

    _emit(annotate_contract("yield_design_center", yield_design_center(
        samples, _kv_floats(tol, "--tol"), k_sigma=k_sigma, n_levels=n_levels,
        max_iter=max_iter, n_mc=n_mc, seed=seed, kind=kind)), "设计中心化失败")


@uq_app.command("temp-zone")
def uq_temp_zone_cmd(
    samples: str = typer.Argument(..., help="校准样本集 samples.json（含 t_c 维）"),
    env_key: str = typer.Argument(..., help="环境包络键（bands env-list 查询）"),
    tol: list[str] | None = typer.Option(None, "--tol", help="几何公差 σ 参数名=值（可多次，可空）"),  # noqa: B008
    t_ref_c: float = typer.Option(None, "--t-ref", help="参考温度 °C（缺省用包络自身）"),
    k_sigma: float = typer.Option(3.0, "--k-sigma", help="σ_c = 包络半宽/k_sigma"),
    n: int = typer.Option(10000, "--n", help="蒙特卡洛抽样数"),
    seed: int = typer.Option(42, "--seed", help="随机种子"),
    kind: str = typer.Option("poly_ridge", "--kind", help="代理类型 poly_ridge|nn"),
) -> None:
    """温区良率（D9 环境包络 → 温度轴 σ 并入 MC + 温区两端角点确定性评估，FAIL 如实）。"""
    from rfauto.service.contracts import annotate_contract
    from rfauto.service.uq_service import temperature_zone_yield

    _emit(annotate_contract("temperature_zone_yield", temperature_zone_yield(
        samples, _kv_floats(tol, "--tol"), env_key, t_ref_c=t_ref_c, k_sigma=k_sigma,
        n=n, seed=seed, kind=kind)), "温区良率失败")


# ─── farfield（WP4.1 nf2ff 远场） ──────────────────────────────────────

farfield_app = typer.Typer(help="远场方向图/增益/效率/SAR（WP4.1 nf2ff 产物视图）")
app.add_typer(farfield_app, name="farfield")


@farfield_app.command("list")
def farfield_list_cmd(
    limit: int = typer.Option(50, "--limit", "-n", help="返回条数上限"),
) -> None:
    """含远场/SAR 产物的 run 清单。"""
    from rfauto.service.nf2ff_service import farfield_runs

    _emit(farfield_runs(limit=limit), "远场 run 清单失败")


@farfield_app.command("view")
def farfield_view_cmd(
    run_id: str = typer.Argument(..., help="含 nf2ff 产物的 run ID"),
) -> None:
    """单 run 远场视图：φ 切面 θ-dB 序列 + Dmax/效率/HPBW/F/B + SAR（core/farfield 确定性解析）。"""
    from rfauto.service.nf2ff_service import farfield_view

    _emit(farfield_view(run_id), f"远场视图失败 {run_id}")


# ─── electrothermal / parasitic（WP4.4a/4.4b 链路） ───────────────

@app.command("electrothermal")
def electrothermal_cmd(
    payload: str = typer.Argument(..., help="电-热链输入 JSON（case/thermal/material/resonator/band）"),
) -> None:
    """Wilkinson 隔离电阻损耗 → 温升 → 材料温漂 → S 参数失谐（+带内判据），纯闭式。"""
    from rfauto.service.electrothermal_service import run_wilkinson_electrothermal

    _emit(run_wilkinson_electrothermal(_load_json_file(payload, "payload")), "电-热链失败")


@app.command("parasitic")
def parasitic_cmd(
    payload: str = typer.Argument(..., help="寄生提取链输入 JSON（pcb/substrate/...）"),
) -> None:
    """PCB 互连 RLC 提取链：pcell 几何 → RF-DRC 门 → 闭式锚 →（Q3D 注入对比 ≤5% 门）。"""
    from rfauto.service.parasitic_service import extract_interconnect_rlc

    result = extract_interconnect_rlc(_load_json_file(payload, "payload"))
    if not result.get("ok") and result.get("stage") == "drc":
        console.print("[red]✗ RF-DRC 门不过（不进提取）[/red]")
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        raise typer.Exit(code=1)
    _emit(result, "寄生提取失败")


# ─── topology（WP4.6 生成式综合 E10） ──────────────────────────────────

@app.command("topology")
def topology_cmd(
    f0: float = typer.Option(..., "--f0", help="中心频率 GHz"),
    fbw: float = typer.Option(..., "--fbw", help="相对带宽 (0,1]"),
    rl: float = typer.Option(20.0, "--rl", help="带内回损目标 dB"),
    stop_rejection: float = typer.Option(None, "--stop-rejection", help="阻带抑制要求 dB（选阶用）"),
    stop_fbw_mult: float = typer.Option(2.0, "--stop-fbw-mult", help="阻带边 = f0·(1±mult·fbw/2)"),
    order: int = typer.Option(None, "--order", "-n", help="显式阶数（否则规则选阶/默认 3）"),
    family: str = typer.Option(None, "--family", help="家族提示（coupled_bpf/hairpin）"),
    proposer: str = typer.Option("rule_based", "--proposer", help="提议器注册名"),
    campaign: bool = typer.Option(False, "--campaign", help="跑小战役精算（电路裁判，离线秒级）"),
    n_trials: int = typer.Option(80, "--n-trials", help="战役 TPE 试验数"),
    seed: int = typer.Option(20260914, "--seed", help="战役随机种子"),
    sandbox_name: str = typer.Option(None, "--sandbox-name", help="落沙箱草稿名（不 promote）"),
    promote: bool = typer.Option(False, "--promote", help="草稿走 L1/L2/L3 准入链迁 promoted/（需 --sandbox-name）"),
) -> None:
    """滤波器拓扑提议（typed，禁数值字段）→ 综合初值 →（--campaign）小战役精算。"""
    from rfauto.service.topology_service import propose_topology

    spec: dict = {"f0_ghz": f0, "fbw": fbw, "rl_db": rl, "stop_fbw_mult": stop_fbw_mult}
    if stop_rejection is not None:
        spec["stop_rejection_db"] = stop_rejection
    if order is not None:
        spec["order_hint"] = order
    if family is not None:
        spec["family_hint"] = family
    _emit(propose_topology(spec, proposer=proposer, campaign=campaign,
                           n_trials=n_trials, seed=seed, sandbox_name=sandbox_name,
                           promote=promote),
          "拓扑提议失败")


# ─── vna-replay（VNA 软侧离线回放；透传） ─────────────────────────

@app.command("vna-replay")
def vna_replay_cmd(
    measured: str = typer.Argument(..., help="历史测量 Touchstone（供 MockVNAInstrument）"),
    sim: str = typer.Option(None, "--sim", help="仿真 Touchstone（缺省=同文件自比对）"),
    threshold_db: float = typer.Option(3.0, "--threshold", "-t", help="相关性 dB 偏差门"),
    session: str = typer.Option(None, "--session", help="会话 JSONL 落盘路径"),
) -> None:
    """mock 仪表采集→校准→相关全链回放（零硬件；硬件阻塞下的回归入口）。"""
    from rfauto.service.api import vna_offline_replay

    result = vna_offline_replay(measured, sim, threshold_db=threshold_db,
                                session_path=session)
    if not result.get("ok"):
        console.print("[red]✗ 离线回放失败[/red]")
        for err in result.get("errors") or ([result["error"]] if result.get("error") else []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    corr = result.get("correlation") or {}
    if corr and not corr.get("is_correlated", True):
        raise typer.Exit(code=1)


# ─── report-narrative（F9 报告叙述位；0bj） ───────────────────────────────────

@app.command("report-narrative")
def report_narrative_cmd(
    run_id: str = typer.Argument(..., help="已完成 run（runs/<run_id>/meta.json 须存在）"),
    text: str = typer.Option(None, "--text", help="外来叙述文本：审计其数字（缺省=生成模板叙述）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """F9 叙述位：run 白名单 → 确定性模板叙述，或审计外来叙述（未授权数字定位；不调 LLM）。"""
    from rfauto.service.report_narrative import report_narrative_for_run

    result = report_narrative_for_run(run_id, narrative=text)
    if result.get("errors"):
        _emit(result, "叙述生成失败")
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        console.print(result.get("narrative", ""))
        for v in result.get("violations") or []:
            console.print(f"  [red]! 未授权数字 {v.get('text')} @{v.get('start')}: {v.get('reason')}[/red]")
    raise typer.Exit(code=0 if result.get("ok") else 1)


# ─── rationale（F11 经验记忆 / F2 理由检索；0z） ──────────────────────────────

rationale_app = typer.Typer(help="设计理由/经验记忆（F11 typed 经验检索 + F2 runs 理由语料 TF-IDF）")
app.add_typer(rationale_app, name="rationale")


@rationale_app.command("recall")
def rationale_recall_cmd(
    task: str = typer.Argument(..., help="任务描述（模板名/场景关键词）"),
    memory: str = typer.Option(None, "--memory", "-m", help="外部经验记忆 JSON（save_entries 产物）"),
    top_k: int = typer.Option(5, "--top-k", help="命中数上限"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """任务描述 → 命中历史坑/核对表/动作（确定性关键词匹配，无 embedding/网络）。"""
    from rfauto.service.rationale_memory import recall_with_memory

    result = recall_with_memory(task, memory_path=memory, top_k=top_k)
    _emit(result, "经验检索失败", json_output=json_output)
    if json_output:
        return
    if not result["hits"]:
        console.print("[green]无命中历史经验[/green]")
        return
    gate = "[red]先离线审计[/red]" if result["require_offline_audit"] else "[dim]无门禁[/dim]"
    console.print(f"[bold]命中 {len(result['hits'])} 条[/bold]（{result['n_entries']} 池）  {gate}")
    for h in result["hits"]:
        console.print(f"  [cyan]{h['lesson_id']}[/cyan] {h['checklist']} ← {', '.join(h['matched'])}")
        console.print(f"    结论：{h['conclusion']}")
        console.print(f"    动作：{h['action']}")


@rationale_app.command("checklist")
def rationale_checklist_cmd(
    template: str = typer.Argument(..., help="模板名（如 patch、cyl_grid）"),
    extras: str = typer.Option(None, "--extras", help="场景补充关键词"),
    memory: str = typer.Option(None, "--memory", "-m", help="外部经验记忆 JSON"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """冒烟前核对表门禁：模板名 → 核对表 + gate（命中即要求先离线审计），可嵌入设计任务描述。"""
    from rfauto.service.rationale_memory import checklist_with_memory

    result = checklist_with_memory(template, extras=extras, memory_path=memory)
    _emit(result, "核对表生成失败", json_output=json_output)
    if json_output:
        return
    if result.get("gate"):
        console.print(f"[red]{result['gate']}[/red]")
    console.print(result.get("markdown") or "[green]无命中历史经验，无门禁[/green]")


@rationale_app.command("search")
def rationale_search_cmd(
    query: str = typer.Argument(..., help="查询文本"),
    runs_dir: str = typer.Option("runs", "--runs-dir", help="理由语料根目录"),
    top_k: int = typer.Option(5, "--top-k", help="返回条数"),
) -> None:
    """runs/ 产物理由语料 TF-IDF 余弦检索（为什么这么做：autotune issues/fixes/meta）。"""
    from rfauto.service.rationale_memory import search_runs_rationale

    _emit(search_runs_rationale(query, runs_dir=runs_dir, top_k=top_k), "理由检索失败")


# ─── rag (RAG 知识库检索，只读薄壳) ──────────────────────────────────────

rag_app = typer.Typer(help="RAG 知识库词法检索（BM25，只读、citation 可溯）")
app.add_typer(rag_app, name="rag")


def _rag_scope_dirs(docs: str, runs: str, scope: str) -> tuple[str | None, str | None]:
    """--scope → (docs_dir, runs_dir)；None=跳过该来源（壳层参数装配）。"""
    if scope == "docs":
        return docs, None
    if scope == "runs":
        return None, runs
    if scope == "all":
        return docs, runs
    raise typer.BadParameter(f"--scope 仅支持 docs|runs|all，收到: {scope}")


@rag_app.command("index")
def rag_index_cmd(
    docs: str = typer.Option("docs", "--docs", help="文档目录"),
    runs: str = typer.Option("runs", "--runs", help="runs 历史目录"),
    scope: str = typer.Option("all", "--scope", help="索引范围: docs|runs|all"),
    runs_limit: int = typer.Option(None, "--runs-limit", help="最多索引 N 个 run 目录"),
) -> None:
    """构建 RAG 索引并输出统计快照（JSON 直出，零写副作用）。"""
    from rfauto.service.rag_service import index_corpus

    docs_dir, runs_dir = _rag_scope_dirs(docs, runs, scope)
    _emit(index_corpus(docs_dir=docs_dir, runs_dir=runs_dir,
                       base_dir=".", runs_limit=runs_limit), "RAG 索引构建失败")


@rag_app.command("query")
def rag_query_cmd(
    text: str = typer.Argument(..., help="查询文本（词法 BM25，中英文皆可）"),
    top_k: int = typer.Option(5, "--top-k", min=1, help="返回命中数上限"),
    docs: str = typer.Option("docs", "--docs", help="文档目录"),
    runs: str = typer.Option("runs", "--runs", help="runs 历史目录"),
    scope: str = typer.Option("all", "--scope", help="检索范围: docs|runs|all"),
    runs_limit: int = typer.Option(None, "--runs-limit", help="最多索引 N 个 run 目录"),
) -> None:
    """RAG 词法检索（JSON 直出：hits + citation + snippet，只读）。"""
    from rfauto.service.rag_service import query_corpus

    docs_dir, runs_dir = _rag_scope_dirs(docs, runs, scope)
    _emit(query_corpus(text, top_k=top_k, docs_dir=docs_dir, runs_dir=runs_dir,
                       base_dir=".", runs_limit=runs_limit), "RAG 检索失败")


@rag_app.command("explain")
def rag_explain_cmd(
    text: str = typer.Argument(..., help="查询文本"),
    top_k: int = typer.Option(5, "--top-k", min=1, help="返回命中数上限"),
    docs: str = typer.Option("docs", "--docs", help="文档目录"),
    runs: str = typer.Option("runs", "--runs", help="runs 历史目录"),
    scope: str = typer.Option("all", "--scope", help="检索范围: docs|runs|all"),
    runs_limit: int = typer.Option(None, "--runs-limit", help="最多索引 N 个 run 目录"),
) -> None:
    """RAG 检索 + 逐词 BM25 分数明细（tf/df/idf/contribution，打分可溯）。"""
    from rfauto.service.rag_service import explain_corpus

    docs_dir, runs_dir = _rag_scope_dirs(docs, runs, scope)
    _emit(explain_corpus(text, top_k=top_k, docs_dir=docs_dir, runs_dir=runs_dir,
                         base_dir=".", runs_limit=runs_limit), "RAG 检索失败")


# ─── self-heal（WP3.5 F5 自愈环只读诊断；审查 D 分片 M1 装车） ────────────────

self_heal_app = typer.Typer(help="自愈环只读诊断（F5：日志面→确定性 critique→根因/建议）")
app.add_typer(self_heal_app, name="self-heal")


@self_heal_app.command("run")
def self_heal_run_cmd(
    run_id: str = typer.Argument(..., help="已落盘 run（runs/<run_id>/meta.json 须存在）"),
    retries: int = typer.Option(0, "--retries", help="自愈环重试次数（只读模式 attempt 确定性重读）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """对既有 run 跑一次只读自愈环（零真机；只诊断+建议，不自动改配方）。"""
    from rfauto.service.self_heal_service import self_heal_run_for_run

    result = self_heal_run_for_run(run_id, retries=retries)
    _emit(result, f"自愈环诊断失败（{run_id}）", json_output=json_output)
    if json_output:
        return
    color = {"clean": "green", "diagnosed": "red", "unknown_failure": "yellow"}.get(
        str(result.get("verdict")), "yellow")
    console.print(f"[{color}]verdict={result.get('verdict')}[/{color}]  "
                  f"root_cause_id={result.get('root_cause_id')}  "
                  f"lesson_ref={result.get('lesson_ref')}  attempts={result.get('attempts')}")
    for action in result.get("actions") or []:
        console.print(f"  - {action}")
    console.print(f"[dim]{result.get('note')}[/dim]")


# ─── logs（WP3.6 LogDistiller 消费端装车；审查 D 分片 M5） ────────────────────

logs_app = typer.Typer(help="日志语义蒸馏（LogDistiller：stdout/审计 JSON→结构化 digest）")
app.add_typer(logs_app, name="logs")


@logs_app.command("digest")
def logs_digest_cmd(
    path: str = typer.Argument(..., help="日志文件 / 审计 JSON / run 目录"),
    source: str = typer.Option("auto", "--source", help="数据源: auto|openems|hfss|audit_json|generic"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """日志 → 结构化 digest（rc/errors/warnings/指标/失败签名；只读不落文件）。"""
    from rfauto.service.self_heal_service import log_digest_for_path

    result = log_digest_for_path(path, source=source)
    _emit(result, f"日志蒸馏失败（{path}）", json_output=json_output)
    if json_output:
        return
    digest = result.get("digest") or {}
    console.print(
        f"source={digest.get('source')}  rc={digest.get('rc')}  "
        f"n_lines={digest.get('n_lines')}  "
        f"errors={len(digest.get('errors') or [])}  "
        f"warnings={len(digest.get('warnings') or [])}  "
        f"signatures={digest.get('signatures') or []}")
    for key, val in (digest.get("metrics") or {}).items():
        console.print(f"  metric {key} = {val}")


# ─── materials（D1 色散材料库装车；审查 C 分片 D1 最小安全口径） ──────────────

materials_app = typer.Typer(help="材料库工具（D1 色散适应性报告；只读）")
app.add_typer(materials_app, name="materials")


@materials_app.command("dispersion-report")
def materials_dispersion_report_cmd(
    material: str = typer.Argument(..., help="materials.yaml 材料键（须含 dispersion 条目）"),
    f_low_ghz: float = typer.Argument(None, help="频带下沿 GHz（缺省用 D-S 拟合频带）"),
    f_high_ghz: float = typer.Argument(None, help="频带上沿 GHz（缺省用 D-S 拟合频带）"),
    max_eps_r_drift: float = typer.Option(0.02, "--max-drift", help="常数 εr 近似门（相对漂移）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """材料在频带内的色散适应性报告（εr/tanδ 漂移 + 常数近似判定 + 修正建议）。"""
    from rfauto.service.dispersion_service import dispersion_fitness_report

    band = None if (f_low_ghz is None and f_high_ghz is None) else [f_low_ghz, f_high_ghz]
    result = dispersion_fitness_report(
        material, band, max_eps_r_drift=max_eps_r_drift)
    _emit(result, f"色散报告失败（{material}）", json_output=json_output)
    if json_output:
        return
    gate = result.get("gate") or {}
    color = "green" if gate.get("passed") else "red"
    console.print(
        f"[{color}]{gate.get('verdict')}[/{color}]  "
        f"εr 漂移 {result.get('eps_r_drift_pct', 0):.3f}%  "
        f"tanδ 漂移 {result.get('tan_delta_drift_pct', 0):.3f}%  "
        f"（带 {result.get('band_ghz')} GHz，测量点 {result.get('f_meas_ghz')} GHz）")
    console.print(f"  {gate.get('message')}")
    if result.get("correction"):
        console.print("  [yellow]建议：模板改用 Djordjevic-Sarkar/多极 Debye 色散渲染"
                      "（correction 段含 openEMS AddDjordjevicSarkarMaterial 参数，--json 查看）[/yellow]")


# ─── db（注册表数据库薄壳：SQLite 事务型注册表 + DuckDB 分析直读） ────────
# 六命令零逻辑转发 service/db_service（规则 4）；路径参数一律 str 注解（#269
# B008）；query 走只读 SELECT 白名单（拒绝进信封，不抛出）。

db_app = typer.Typer(help="注册表数据库（SQLite 事务型注册表 + DuckDB 分析直读；零服务器）")
app.add_typer(db_app, name="db")

_DB_PATH_HELP = "注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）"


@db_app.command("init")
def db_init_cmd(
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """建库 + 幂等迁移（首次 applied=1，重放 applied=0）。"""
    from rfauto.service.db_service import db_init

    result = db_init(db_path)
    _emit(result, "注册表建库失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ 注册表就绪[/green] {result['path']}  "
                  f"schema_version={result['schema_version']}  applied={result['applied']}")


@db_app.command("migrate")
def db_migrate_cmd(
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """执行幂等迁移（schema_version 表递增；重复执行零变更）。"""
    from rfauto.service.db_service import db_migrate

    result = db_migrate(db_path)
    _emit(result, "注册表迁移失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ 迁移完成[/green] {result['path']}  "
                  f"schema_version={result['schema_version']}  applied={result['applied']}")


@db_app.command("status")
def db_status_cmd(
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """注册表状态：路径/存在性/schema 版本/各表行数（文件不存在不创建）。"""
    from rfauto.service.db_service import db_status

    result = db_status(db_path)
    _emit(result, "注册表状态读取失败", json_output=json_output)
    if json_output:
        return
    exists = "存在" if result.get("exists") else "不存在（rfauto db init 建库）"
    console.print(f"{result['path']}  [{exists}]  schema_version={result['schema_version']}")
    for table, count in (result.get("tables") or {}).items():
        console.print(f"  {table}: {count}")


@db_app.command("reindex-runs")
def db_reindex_runs_cmd(
    runs_dir: str = typer.Option("runs", "--runs-dir", help="runs 目录（扫 */meta.json）"),
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """扫 runs/*/meta.json 重建 runs 表（upsert 幂等；单文件失败不阻塞 #105）。"""
    from rfauto.service.db_service import reindex_runs

    result = reindex_runs(runs_dir, db_path=db_path)
    _emit(result, "runs 重建索引失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ reindexed={result['reindexed']}[/green]  "
                  f"failed={result['failed']}  db={result['db_path']}")
    if result.get("note"):
        console.print(f"  [dim]{result['note']}[/dim]")
    for err in result.get("errors") or []:
        console.print(f"  [yellow]- {err}[/yellow]")


@db_app.command("query")
def db_query_cmd(
    sql: str = typer.Argument(..., help="单条只读 SELECT（? 占位符）"),
    param: list[str] | None = typer.Option(None, "--param", "-p",  # noqa: B008
                                           help="占位符参数（可重复；JSON 标量或字符串）"),
    limit: int = typer.Option(200, "--limit", help="返回行数上限（最大 5000）"),
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """只读查询注册表（SELECT 白名单 + 参数绑定；拒绝原因进信封）。

    示例：rfauto db query "SELECT run_id, model FROM runs WHERE adapter = ?" -p hfss
    """
    from rfauto.service.db_service import db_query_safe

    params = [_coerce_param(p) for p in (param or [])]
    result = db_query_safe(sql, params, limit=limit, db_path=db_path)
    _emit(result, "注册表查询失败", json_output=json_output)
    if json_output:
        return
    columns = result.get("columns") or []
    console.print("  ".join(str(c) for c in columns))
    for row in result.get("rows") or []:
        console.print("  ".join(str(v) for v in row))
    console.print(f"[dim]{result['row_count']} 行"
                  f"{'（已截断）' if result.get('truncated') else ''}[/dim]")


@db_app.command("analytics-attach")
def db_analytics_attach_cmd(
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    sample_limit: int = typer.Option(3, "--sample-limit", help="示例查询最近 runs 条数"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """DuckDB sqlite 扩展直读注册表（零拷贝分析面；不可用如实 ok=False）。"""
    from rfauto.service.db_service import analytics_attach

    result = analytics_attach(db_path, sample_limit=sample_limit)
    if not result.get("ok"):
        console.print(f"[red]✗ DuckDB 直读不可用: {result.get('reason')}[/red]")
        if json_output:
            console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        raise typer.Exit(code=1)
    _emit(result, "DuckDB 直读失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ duckdb {result['duckdb_version']}[/green] "
                  f"attached {result['path']} as {result['attached_as']}")
    for table, count in (result.get("tables") or {}).items():
        console.print(f"  {table}: {count}")
    for run in result.get("sample_runs") or []:
        console.print(f"  run {run.get('run_id')}  {run.get('model')}  "
                      f"{run.get('adapter')}  {run.get('status')}")


# ─── slotline / transitions（槽线与过渡薄壳：闭式分析/综合 + 过渡/巴伦设计） ──
# 五命令零逻辑转发 service/slotline_service（规则 4）；数值只出确定性内核
# （铁律 7：core/slotline Janaswamy–Schaubert 闭式 + core/slotline_transitions
# Roberts/Knorr 过渡、Marchand 两节耦合段电路级综合）；越有效域拒绝进信封不外推。
# 数值参数一律 float 注解，无 Path 选项（#269 同族）。

slotline_app = typer.Typer(
    help="槽线闭式（Janaswamy–Schaubert 1986：分析/综合；越有效域拒绝不外推）")
app.add_typer(slotline_app, name="slotline")

transitions_app = typer.Typer(
    help="MSL↔槽线过渡与 Marchand 巴伦设计（微带 HJ 综合 + 槽线闭式精算）")
app.add_typer(transitions_app, name="transitions")

_SLOT_H_HELP = "基板厚 mm（单面金属、基板下空气；有效域 0.006≤d/λ0≤0.06）"
_SLOT_ER_HELP = "基板相对介电常数（2.22–3.8 / 3.8–9.8 两段拟合）"


@slotline_app.command("analyze")
def slotline_analyze_cmd(
    w_mm: float = typer.Option(..., "--w-mm", help="槽宽 mm（金属面上的缝）"),
    h_mm: float = typer.Option(..., "--h-mm", help=_SLOT_H_HELP),
    eps_r: float = typer.Option(..., "--eps-r", help=_SLOT_ER_HELP),
    freq_ghz: float = typer.Option(..., "--freq-ghz", help="频率 GHz（进入拟合式，必需）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """槽线闭式分析：(w, h, εr, f) → Z0、εeff、β、λ'（越有效域拒绝不外推）。

    示例：rfauto slotline analyze --w-mm 1.0 --h-mm 1.524 --eps-r 3.66 --freq-ghz 2.5
    """
    from rfauto.service.slotline_service import slotline_analysis

    result = slotline_analysis(w_mm, h_mm, eps_r, freq_ghz)
    _emit(result, "槽线分析失败", json_output=json_output)
    if json_output:
        return
    r = result["result"]
    console.print(
        f"[green]✓ 槽线 segment={r['segment']}[/green]  Z0={r['z0_ohm']}Ω  "
        f"εeff={r['eps_eff']}  β={r['beta_rad_m']} rad/m  λ'={r['lambda_g_mm']}mm")
    console.print(f"  W/λ0={r['w_over_lambda0']}  d/λ0={r['d_over_lambda0']}  "
                  f"λ'/λ0={r['lambda_ratio']}")


@slotline_app.command("synth")
def slotline_synth_cmd(
    z0_ohm: float = typer.Option(..., "--z0-ohm", help="目标特性阻抗 Ω（功率-电压定义）"),
    h_mm: float = typer.Option(..., "--h-mm", help=_SLOT_H_HELP),
    eps_r: float = typer.Option(..., "--eps-r", help=_SLOT_ER_HELP),
    freq_ghz: float = typer.Option(..., "--freq-ghz", help="频率 GHz"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """槽线综合：目标 Z0 → 槽宽 w（窄槽段括号反解；不可达如实 realizable=False）。

    示例：rfauto slotline synth --z0-ohm 110 --h-mm 1.524 --eps-r 3.66 --freq-ghz 2.5
    """
    from rfauto.service.slotline_service import slotline_synthesis

    result = slotline_synthesis(z0_ohm, h_mm, eps_r, freq_ghz)
    _emit(result, "槽线综合失败", json_output=json_output)
    if json_output:
        return
    if not result.get("realizable", True):
        # 不可达=合法结果非错误（D5 与 marchand 两节语义统一；#122 不凑绿）
        console.print(
            f"[yellow]○ 不可达（realizable=False）[/yellow]  {result.get('reason')}")
        return
    r = result["result"]
    console.print(
        f"[green]✓ w={r['w_mm']}mm[/green]  Z0={r['z0_actual_ohm']}Ω  "
        f"εeff={r['eps_eff']}  λ'={r['lambda_g_mm']}mm  segment={r['segment']}")


def _print_transition_design(design: dict) -> None:
    console.print(
        f"  槽线: Z0={design['z_slot_ohm']}Ω  εeff={design['eps_eff_slot']}  "
        f"λ'={design['lambda_slot_mm']}mm  短路臂 l_short={design['l_short_mm']}mm")
    console.print(
        f"  微带: w={design['w_msl_mm']}mm  Z0={design['z_msl_ohm']}Ω  "
        f"εeff={design['eps_eff_msl']}  开路支节 l_stub={design['l_stub_mm']}mm"
        f"（Δl_open={design['dl_open_mm']}mm）")


@transitions_app.command("msl-slot")
def transitions_msl_slot_cmd(
    f0_ghz: float = typer.Option(..., "--f0-ghz", help="设计中心频率 GHz"),
    h_mm: float = typer.Option(..., "--h-mm", help=_SLOT_H_HELP),
    er: float = typer.Option(..., "--er", help=_SLOT_ER_HELP),
    w_slot_mm: float = typer.Option(..., "--w-slot-mm", help="槽宽 mm"),
    tan_d: float = typer.Option(0.0037, "--tan-d", help="基板损耗角正切"),
    z_msl_ohm: float = typer.Option(50.0, "--z-msl-ohm", help="微带馈线目标阻抗 Ω"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """Roberts/Knorr MSL↔槽线过渡设计参数（开路支节 λg/4+Δl、槽线短路臂 λg'/4）。

    示例：rfauto transitions msl-slot --f0-ghz 2.5 --h-mm 1.524 --er 3.66 --w-slot-mm 1.0
    """
    from rfauto.service.slotline_service import msl_slot_transition_design

    result = msl_slot_transition_design(f0_ghz, h_mm, er, w_slot_mm, tan_d, z_msl_ohm)
    _emit(result, "过渡设计失败", json_output=json_output)
    if json_output:
        return
    design = result["design"]
    console.print(f"[green]✓ MSL↔槽线过渡 @ {design['f0_ghz']}GHz[/green]")
    _print_transition_design(design)


@transitions_app.command("marchand-balun")
def transitions_marchand_balun_cmd(
    f0_ghz: float = typer.Option(..., "--f0-ghz", help="设计中心频率 GHz"),
    h_mm: float = typer.Option(..., "--h-mm", help=_SLOT_H_HELP),
    er: float = typer.Option(..., "--er", help=_SLOT_ER_HELP),
    w_slot_mm: float = typer.Option(..., "--w-slot-mm", help="槽宽 mm"),
    tan_d: float = typer.Option(0.0037, "--tan-d", help="基板损耗角正切"),
    z_msl_ohm: float = typer.Option(50.0, "--z-msl-ohm", help="微带馈线目标阻抗 Ω"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """双槽臂 Marchand 巴伦设计参数（d_c=w_msl+s_slot；在过渡参数上补槽距与 a1/a2）。"""
    from rfauto.service.slotline_service import marchand_balun_design

    result = marchand_balun_design(f0_ghz, h_mm, er, w_slot_mm, tan_d, z_msl_ohm)
    _emit(result, "Marchand 巴伦设计失败", json_output=json_output)
    if json_output:
        return
    design = result["design"]
    console.print(f"[green]✓ 双槽臂 Marchand 巴伦 @ {design['f0_ghz']}GHz[/green]")
    _print_transition_design(design)
    console.print(f"  槽距 d_c={design['d_center_mm']}mm  a1={design['a1_mm']}mm  "
                  f"a2={design['a2_mm']}mm")


@transitions_app.command("marchand2")
def transitions_marchand2_cmd(
    f0_ghz: float = typer.Option(2.5, "--f0-ghz", help="设计中心频率 GHz"),
    z_unbal_ohm: float = typer.Option(50.0, "--z-unbal-ohm", help="不平衡端阻抗 Ω"),
    z_bal_diff_ohm: float = typer.Option(280.0, "--z-bal-diff-ohm",
                                         help="平衡端差分阻抗 Ω（单端参考 Z_L/2）"),
    er: float = typer.Option(3.66, "--er", help="基板相对介电常数"),
    h_mm: float = typer.Option(1.524, "--h-mm", help="基板厚 mm"),
    tan_d: float = typer.Option(0.0037, "--tan-d", help="基板损耗角正切"),
    s_min_mm: float = typer.Option(0.1, "--s-min-mm", help="可制造最小耦合缝 mm"),
    w_max_mm: float = typer.Option(6.0, "--w-max-mm", help="耦合段线宽上限 mm"),
    z_c_ohm: float | None = typer.Option(None, "--z-c-ohm",
                                         help="耦合段 Z_c=√(Z0e·Z0o) Ω（缺省自动扫描）"),
    band_lo_ghz: float | None = typer.Option(None, "--band-lo-ghz",
                                             help="自检带下沿 GHz（缺省 0.9·f0）"),
    band_hi_ghz: float | None = typer.Option(None, "--band-hi-ghz",
                                             help="自检带上沿 GHz（缺省 1.1·f0）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """两节对称 Marchand 电路级综合（KJ 几何反解 + 电路级自检门；不可达如实 realizable=False）。

    示例：rfauto transitions marchand2 --z-bal-diff-ohm 280 --h-mm 1.524 --er 3.66
    """
    from rfauto.service.slotline_service import marchand_two_section_synthesis

    if (band_lo_ghz is None) != (band_hi_ghz is None):
        console.print("[red]✗ --band-lo-ghz 与 --band-hi-ghz 须成对给出[/red]")
        raise typer.Exit(code=1)
    band = [band_lo_ghz, band_hi_ghz] if band_lo_ghz is not None else None
    result = marchand_two_section_synthesis(
        f0_ghz, z_unbal_ohm, z_bal_diff_ohm, er, h_mm, tan_d, s_min_mm, w_max_mm,
        z_c_ohm, band)
    _emit(result, "Marchand 两节综合失败", json_output=json_output)
    if json_output:
        return
    design = result["design"]
    metrics = design["model_metrics"]
    tag = "[green]严格可达[/green]" if design["realizable"] else "[yellow]不可达→钳位最近点[/yellow]"
    console.print(
        f"✓ 两节 Marchand @ {design['f0_ghz']}GHz  {tag}  "
        f"C={design['coupling_db']:.2f}dB  Z_c={design['z_c_ohm']:.3f}Ω  "
        f"(Z0e,Z0o)=({design['z0e_realized_ohm']:.3f},{design['z0o_realized_ohm']:.3f})Ω")
    nominal = result["nominal_params"]
    console.print(
        f"  几何: w={nominal['w_mm']}  s={nominal['s_mm']}  l_sect={nominal['l_sect_mm']}  "
        f"w_feed={nominal['w_feed_mm']}  w_bal={nominal['w_bal_line_mm']} mm  "
        f"r_bal_se={nominal['r_bal_se_ohm']}Ω")
    verdict = "[green]PASS[/green]" if metrics["all_gates_pass"] else "[red]FAIL[/red]"
    console.print(
        f"  电路级自检门 {verdict}  max|S11|={metrics['band_max_s11_db']:.2f}dB  "
        f"min|S21|/|S31|={metrics['band_min_s21_db']:.3f}/{metrics['band_min_s31_db']:.3f}dB  "
        f"不平衡 {metrics['band_max_abs_imbalance_db']:.3f}dB  "
        f"相位误差 {metrics['band_max_phase_error_deg']:.2f}°")
    for note in design.get("notes") or []:
        console.print(f"  [dim]{note}[/dim]")


if __name__ == "__main__":
    app()
