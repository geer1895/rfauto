"""核心工作流顶层命令：run/tune/sweep/autotune/tolerance/refine（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── run ──────────────────────────────────────────────────────────────────────

def _print_explain_summary(run_dir: str | None) -> None:
    """UX-A12（2026-10-05）：失败尾接 explain_run 根因候选摘要段。

    service/explain_run 的指纹引擎做确定性匹配（无 LLM），这里只渲染
    "根因候选"列表。best-effort（#105）：缺 run_dir / playbook 缺失 /
    采集或渲染抛任何异常都只降级为一行提示，绝不打断原错误报错路径、
    不改变退出码。
    """
    if not run_dir:
        return
    try:
        from rfauto.service.explain_run import explain_run
        report = explain_run(run_dir)
    except Exception as exc:  # #105：观测性面故障不阻塞原错误输出
        console.print(f"  [dim]根因候选摘要不可用（{type(exc).__name__}: {exc}）[/dim]")
        return
    if not report.get("ok") or report.get("overall") != "candidates":
        return  # 无命中不硬凑（explain_run #122 口径：no_hit 如实）
    console.print("  [yellow]根因候选（explain_run 指纹匹配，仅供参考）:[/yellow]")
    for rule in report.get("matched_rules", []):
        fps = ", ".join(rule.get("matched_fingerprints", []))
        console.print(f"    - {rule.get('root_cause_family')}（指纹: {fps}）")


@app.command()
def run(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
    detach: bool = typer.Option(False, "--detach", "-d",
                                 help="后台执行，立即返回 job_id（用 jobs status 轮询）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只验证不执行（输出执行计划）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """单次仿真（build → solve → post → 导出）。"""
    if dry_run:
        from rfauto.service.api import dry_run as _dry_run
        result = _dry_run(recipe, adapter_name=adapter)
        if json_output:
            _emit(result, "dry-run 校验失败", json_output=True)
            return
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
        if json_output:
            _emit(result, "后台启动失败", json_output=True)
            return
        console.print(f"[green]✓ 仿真已后台启动[/green]  job_id: {result['job_id']}")
        console.print(f"  轮询: rfauto jobs status {result['job_id']}")
        return

    from rfauto.service.api import run_once
    result = run_once(recipe, adapter_name=adapter)

    if json_output:
        # VI-5 W2-C：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "仿真失败", json_output=True)
        return

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
        _print_explain_summary(result.get("run_dir"))
        raise typer.Exit(code=1)


# ─── tune ─────────────────────────────────────────────────────────────────────


class _TrialWatchReporter:
    """SN-9（2026-10-05）：tune --watch 逐 trial 播报器（rich Live）。

    回调签名与 Optuna ``study.optimize(callbacks=...)`` 一致：``f(study, trial)``
    （每个 trial 完成即被调用，frozen trial）。播报三要素：trial#、cost、
    Δ（=cost−完成前 best，负值=改进）；同帧维护运行 best。终端下 Live 表格
    常驻刷新；非终端（测试/重定向）Live 不渲染，回调补一行直出播报保证
    输出可捕获（同一条数据两种出口，无双份终端输出）。

    用法::

        with _TrialWatchReporter(console) as reporter:
            start_tune(..., on_trial=reporter)
    """

    def __init__(self, console, max_rows: int = 12):
        from rich.live import Live

        self._console = console
        self._max_rows = max_rows
        self._rows: list[tuple[int, object, object, str]] = []  # (number, cost, delta, state)
        self.best: float | None = None
        self.best_trial: int | None = None
        self._live = Live(console=console, refresh_per_second=4)

    # ── 纯状态记账（渲染无关，供单测直接喂 synthetic trial） ──
    def record(self, number: int, value: object, state: str = "") -> None:
        prev_best = self.best
        delta = None
        if value is not None and prev_best is not None:
            delta = float(value) - prev_best
        if value is not None and (prev_best is None or float(value) < prev_best):
            self.best = float(value)
            self.best_trial = number
        self._rows.append((int(number), value, delta, state))

    def _render(self):
        from rich.table import Table

        table = Table(title="tune --watch 逐 trial 播报")
        table.add_column("trial", justify="right")
        table.add_column("cost", justify="right")
        table.add_column("Δ=cost−prev_best", justify="right")
        table.add_column("state")
        for n, v, d, s in self._rows[-self._max_rows:]:
            table.add_row(
                str(n),
                "—" if v is None else f"{float(v):.4f}",
                "—" if d is None else f"{d:+.4f}",
                s or "—",
            )
        best_str = "—" if self.best is None else f"{self.best:.4f}"
        table.caption = f"best cost: {best_str}" + (
            f"（trial {self.best_trial}）" if self.best_trial is not None else "")
        return table

    # ── Live 生命周期 ──
    def __enter__(self) -> _TrialWatchReporter:
        self._live.start()
        self._live.update(self._render())
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._live.stop()
        return False

    # ── optuna 回调入口 ──
    def __call__(self, study, trial) -> None:
        value = getattr(trial, "value", None)
        state = str(getattr(trial, "state", "") or "")
        number = int(getattr(trial, "number", -1))
        self.record(number, value, state)
        self._live.update(self._render())
        if not self._console.is_terminal:
            # 非终端出口（rich Live 不渲染）：一行直出，测试/重定向可捕获
            _, v, d, _ = self._rows[-1]
            cost_str = "—" if v is None else f"{float(v):.4f}"
            delta_str = "—" if d is None else f"{d:+.4f}"
            best_str = "—" if self.best is None else f"{self.best:.4f}"
            self._console.print(
                f"  trial {number}: cost={cost_str} Δ={delta_str} best={best_str}")


@app.command()
def tune(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    watch: bool = typer.Option(False, "--watch", "-w",
                                help="逐 trial 播报（trial#/best cost/Δ，rich Live；单目标路径）"),
    detach: bool = typer.Option(False, "--detach", "-d",
                                 help="后台执行，立即返回 job_id（用 jobs status 轮询；单目标路径）"),
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
    seed: int = typer.Option(None, "--seed", help="采样器随机种子（P2⑦；缺省沿用 optimizer.SAMPLER_SEED=42）"),
    pruner: str = typer.Option("none", "--pruner", help="多保真裁剪器（ME-13）: none | asha | hyperband——Phase1 低保真差配方早停"),
    warm_start_registry: bool | None = typer.Option(
        None, "--warm-start-registry/--no-warm-start-registry",
        help="代理模型注册表 warm-start（RB-ML-1）: 缺省读环境与配置，显式开关优先"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """启动优化外环（TPE / NSGA-II / --fidelity auto 多保真）。"""
    if not json_output:
        console.print(f"[cyan]开始优化: {recipe}[/cyan]")
        mode_str = '多保真' if fidelity == 'auto' else ('多目标 NSGA-II' if multi else '单目标 TPE')
        console.print(f"  适配器: {adapter}, 模式: {mode_str}")

    if dry_run:
        if watch or detach:
            # #122 不静默：dry-run 只验证不执行，--watch/--detach 无消费对象，
            # 显式提示而非无声忽略（--json 信封模式下随 envelope notes 键同行）。
            note = "--dry-run 下 --watch/--detach 不生效（无执行面可挂）；移除 --dry-run 后重试"
            if json_output:
                dry_run_note = note
            else:
                console.print(f"[yellow]注：{note}[/yellow]")
        from rfauto.service.api import dry_run as _dry_run
        result = _dry_run(recipe, adapter_name=adapter)
        if json_output:
            if watch or detach:
                result["notes"] = [dry_run_note]
            _emit(result, "dry-run 校验失败", json_output=True)
            return
        if not result.get("ok"):
            console.print("[red]✗ dry-run 校验失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        result = dict(result, planned_mode="multi-NSGAII" if multi else f"single-{sampler}")
        console.print("[cyan]dry-run 优化计划（未实际执行）：[/cyan]")
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    # SN-9（2026-10-05）：--detach/--watch 单目标路径实装（run_once_async 范式复用）。
    # 多保真/多目标/代理寻优不走本路径：detach 显式拒绝（不静默丢弃后台语义），
    # watch 如实降级一行提示后照常执行（#122 不静默）。
    single_objective = fidelity != "auto" and not multi and sampler != "sbo"

    # RB-ML-1：注册表 warm-start 三态开关只挂单目标路径（spec §6.2-4）；
    # 显式给出且走其他路径时如实提示，不静默丢弃（#122）。--json 下提示走
    # stderr，stdout 信封保持纯净（MCP/管道消费面零污染）。
    if warm_start_registry is not None and not single_objective:
        note = "--warm-start-registry 仅单目标路径生效，本次按未设置处理"
        if json_output:
            import sys as _sys

            print(note, file=_sys.stderr)
        else:
            console.print(f"[yellow]! {note}[/yellow]")

    if detach:
        if not single_objective:
            if json_output:
                # VI-5 W2-C：--json 下旗标组合拒绝也走信封（失败路径同构）
                _emit({"ok": False,
                       "errors": ["--detach 仅支持单目标路径（多保真/多目标/代理寻优后台化另立）"]},
                      "--detach 仅支持单目标路径", json_output=True)
                return  # 不可达（_emit 失败必 raise Exit(1)），守卫可读性
            console.print("[red]✗ --detach 仅支持单目标路径"
                          "（多保真/多目标/代理寻优后台化另立）[/red]")
            raise typer.Exit(code=1)
        from rfauto.service.api import start_tune_async
        result = start_tune_async(
            recipe, adapter_name=adapter, max_trials=max_trials,
            study_name=study_name, max_wall_s=max_wall_s,
            sampler=sampler, seed=seed, pruner=pruner)
        if json_output:
            _emit(result, "后台启动失败", json_output=True)
            return
        console.print(f"[green]✓ 优化已后台启动[/green]  job_id: {result['job_id']}")
        console.print(f"  轮询: rfauto jobs status {result['job_id']}")
        return

    watch_reporter = None
    if watch:
        if json_output:
            pass  # --json 信封模式：不挂 rich Live 播报（stdout 只留最终信封）
        elif not single_objective:
            console.print("[yellow]! --watch 仅单目标路径支持，本次按无 watch 执行[/yellow]")
        else:
            watch_reporter = _TrialWatchReporter(console)

    if fidelity == "auto":
        from rfauto.service.api import run_multifidelity_tune
        result = run_multifidelity_tune(recipe, adapter_low=adapter_low, adapter_high=adapter_high)
        if json_output:
            _emit(result, "多保真优化失败", json_output=True)
            return
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
        if json_output:
            _emit(result, "多目标优化失败", json_output=True)
            return
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
        if json_output:
            _emit(result, "代理寻优环失败", json_output=True)
            return
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

    tune_kw: dict = dict(
        recipe=recipe,
        adapter_name=adapter,
        max_trials=max_trials,
        study_name=study_name,
        max_wall_s=max_wall_s,
        sampler=sampler,
        seed=seed,
        pruner=pruner,
        warm_start_registry=warm_start_registry,
    )
    # SN-9：watch 播报经 on_trial 逐 trial 回调（None=行为不变）
    if watch_reporter is not None:
        with watch_reporter:
            result = start_tune(on_trial=watch_reporter, **tune_kw)
    else:
        result = start_tune(**tune_kw)

    if json_output:
        _emit(result, "优化失败", json_output=True)
        return

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
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="计划面（SN-18）：只实算组合数/方法/范围，不建适配器不求解不写盘"),
    resume_run_id: str = typer.Option(None, "--resume",
                                      help="断点续扫（SN-11）：从该 run 的 sweep checkpoint 续，命中组合不重跑"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """参数扫描（先粗扫缩小范围再交给精调）。

    SN-11（W6-A）：逐组合 checkpoint（sweep_results/checkpoint.jsonl 逐行
    落盘，中途死只丢在跑组合）+ --resume 续扫 + 逐组合进度打点；
    SN-18：--dry-run 计划预览。
    """
    if dry_run:
        from rfauto.optimization.sweep_backend import plan_sweep

        result = plan_sweep(recipe, method=method, coarse_samples=coarse,
                            max_combos=max_combos)
        if json_output:
            _emit(result, "扫描计划失败", json_output=True)
            return
        if not result.get("ok"):
            console.print("[red]✗ 扫描计划失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        console.print("[cyan]扫描计划（dry-run，零执行零写盘）[/cyan]")
        console.print(f"  模型: {result.get('model')}  方法: {result.get('method')}")
        console.print(f"  粗扫组合: {result.get('phase1_combos')}"
                      f"  精调: {result.get('phase2')}")
        for k, v in sorted((result.get("param_ranges") or {}).items()):
            console.print(f"    {k}: [{v[0]:g}, {v[1]:g}]", markup=False)
        return

    from rfauto.optimization.sweep_backend import run_sweep
    if not json_output:
        console.print(f"[cyan]开始扫描: {recipe}[/cyan]")
        console.print(f"  方法: {method}, 粗扫: {coarse}, 适配器: {adapter}, 上限: {max_combos}"
                      + (f", 续扫自: {resume_run_id}" if resume_run_id else ""))

    def _progress(done: int, total: int, tag: str) -> None:
        if not json_output:
            console.print(f"  [{tag} {done}/{total}]", markup=False)

    result = run_sweep(
        recipe,
        adapter_name=adapter,
        method=method,
        coarse_samples=coarse,
        max_combos=max_combos,
        progress_cb=_progress,
        resume_run_id=resume_run_id,
    )

    if json_output:
        # VI-5 W2-C：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "扫描失败", json_output=True)
        return

    if result.get("ok"):
        console.print("[green]✓ 扫描完成[/green]")
        console.print(f"  run_id:    {result.get('run_id', '?')}")
        console.print(f"  方法:      {result.get('method', '?')}")
        resumed = result.get("resumed_combos") or 0
        resumed_s = f" / 续扫携带 {resumed}" if resumed else ""
        console.print(f"  组合数:    {result.get('total_combos', 0)}（粗扫 {result.get('coarse_combos', 0)} / 精调 {result.get('fine_combos', 0)}{resumed_s}）")
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
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="计划面（SN-18）：配方校验+预算/旋钮预览，零执行"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """确定性 critique 自治调优环（无人在环；数值只在确定性内核）。

    --self-verify 切到 WP3.5 自验证环（0bq①）：粗→细双采样器、里程碑逐项
    验收（passed/failed/skipped 如实）、执行看板 runs/loop_boards/。
    """
    if dry_run:
        # SN-18：dry-run=配方全链前置校验（api.dry_run）+ 预算/旋钮回显。
        # 修正预算语义：自治环实跑每 budget 轮各一次求解，成本≈budget 次
        # run——如实换算，不臆造其它数字。
        from rfauto.service.api import dry_run as _api_dry_run

        result = _api_dry_run(recipe, adapter_name="fake")
        plan = {
            "ok": result.get("ok"),
            "mode": "dry-run",
            "domain": "autotune",
            "recipe": str(recipe),
            "budget_rounds": int(budget),
            "solve_estimate": f"≤{int(budget)} 次求解（critique 修正链上界）",
            "knobs": {
                "mesh_mm": mesh or "auto",
                "f0_tol": f0_tol, "rl_floor_db": rl_floor,
                "max_step": max_step,
                "self_verify": bool(self_verify),
                "mesh_fine_mm": mesh_fine if self_verify else None,
            },
        }
        if not result.get("ok"):
            plan["errors"] = list(result.get("errors") or [])
        if json_output:
            _emit(plan, "autotune 计划失败", json_output=True)
            return
        if not plan["ok"]:
            console.print("[red]✗ autotune 计划失败（配方校验未过）[/red]")
            for err in plan.get("errors") or []:
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        console.print("[cyan]autotune 计划（dry-run，零执行）[/cyan]")
        console.print(f"  配方: {recipe}  预算: {budget} 轮"
                      f"  self_verify={self_verify}")
        console.print(f"  旋钮: {plan['knobs']}")
        return
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
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="计划面（SN-18）：公差/规格/样本数实算预览，零执行零写盘"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """公差/良率分析（Monte Carlo，规格取自 objectives）。"""
    if dry_run:
        from rfauto.optimization.optimizer import plan_tolerance

        result = plan_tolerance(recipe, n_samples=samples)
        if json_output:
            _emit(result, "公差计划失败", json_output=True)
            return
        if not result.get("ok"):
            console.print("[red]✗ 公差计划失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        console.print("[cyan]公差分析计划（dry-run，零执行零写盘）[/cyan]")
        console.print(f"  模型: {result.get('model')}  样本数: {result.get('n_samples')}")
        for k, v in sorted((result.get("tolerances") or {}).items()):
            console.print(f"    {k}: ±{v:g}", markup=False)
        return

    from rfauto.service.api import run_tolerance

    if not json_output:
        console.print(f"[cyan]公差分析: {recipe}[/cyan]")
    result = run_tolerance(recipe, adapter_name=adapter, n_samples=samples)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "公差分析失败", json_output=True)
        return
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
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """热启动续调：以上轮 best 为起点，继续优化。

    使用相同的 study_name + SQLite storage，Optuna 自动加载已有 trial，
    从已有结果继续采样（TPE 利用历史数据）。
    """
    from rfauto.optimization.optimizer import run_refine
    if not json_output:
        console.print(f"[cyan]续调 run_id: {run_id}[/cyan]")

    result = run_refine(
        run_id,
        recipe,
        max_trials=max_trials,
        adapter_name=adapter,
    )

    if json_output:
        # VI-5 W2-C：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "续调失败", json_output=True)
        return

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
