"""surrogate/runs/datasets 子应用（代理建模与数据工厂薄壳）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── surrogate (E3 代理模型离线分析) ─────────────────────────────────────────

surrogate_app = typer.Typer(help="代理模型离线分析（E3）")
app.add_typer(surrogate_app, name="surrogate")


@surrogate_app.command("analyze")
def surrogate_analyze(
    run_id: str = typer.Argument(None, help="run_id（从其 meta 反查 study）"),
    study: str = typer.Option(None, "--study", "-s", help="Optuna study 名称"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """离线 GP 代理模型分析：参数重要度 + 拟合误差（不进在线调优路径）。"""
    from rfauto.service.api import analyze_surrogate

    result = analyze_surrogate(run_id, study_name=study)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "分析失败", json_output=True)
        return
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
    importance: dict = data.get("param_importance") or {}
    if any(v is None for v in importance.values()):
        # D1-1（审查批 2026-10-04）：isotropic RBF 下逐参数重要性不可辨识，
        # 服务层已降级 None——渲染 N/A，绝不画 1/n 假排行条形图
        console.print("  参数重要度: N/A（不可辨识，不渲染假排行）")
        note = data.get("param_importance_note") or ""
        if note:
            console.print(f"    {note}")
        for k in importance:
            console.print(f"    {k:<20} N/A")
    else:
        console.print("  参数重要度:")
        for k, v in sorted(importance.items(), key=lambda x: -x[1]):
            bar = "█" * max(1, int(v * 30))
            console.print(f"    {k:<20} {v:.3f} {bar}")


@surrogate_app.command("uq")
def surrogate_uq(
    samples: str = typer.Argument(..., help="校准样本集 samples.json 路径"),
    tol: list[str] = typer.Option(None, "--tol", help="公差 σ：--tol 参数名=值（可多次）"),  # noqa: B008
    n: int = typer.Option(10000, "--n", help="蒙特卡洛抽样数"),
    seed: int = typer.Option(42, "--seed", help="随机种子"),
    kind: str = typer.Option("poly_ridge", "--kind", help="代理类型 poly_ridge|nn"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """代理免费蒙特卡洛 UQ：良率 + 指标分布 + 敏感性排序（阶段 6.4）。"""
    from rfauto.service.uq_service import surrogate_yield

    tolerances: dict[str, float] = {}
    for item in (tol or []):
        if "=" not in item:
            if json_output:
                # VI-5 W6-B：入参非法也信封（--json 下失败路径不许非 JSON）
                _emit({"ok": False, "errors": [f"--tol 格式应为 参数名=σ：{item}"]},
                      "UQ 失败", json_output=True)
            console.print(f"[red]✗ --tol 格式应为 参数名=σ：{item}[/red]")
            raise typer.Exit(code=1)
        name, _, val = item.partition("=")
        tolerances[name.strip()] = float(val)

    result = surrogate_yield(samples, tolerances, n=n, seed=seed, kind=kind)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "UQ 失败", json_output=True)
        return
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
    run_ids: list[str] = typer.Argument(..., help="run_id 清单（2 个=经典 A/B 对比；N>2=SN-7 N-way 矩阵）"),  # noqa: B008
    provenance: bool = typer.Option(False, "--provenance", "-p",
                                     help="输出可引用的实验复现块（方向 7）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """对比多次 run 的指标与 cost。--provenance 输出环境指纹复现块。

    恰好 2 个 run_id 时走经典 A/B 路径（行为不变）；N>2 走 SN-7 N-way
    （逐对 delta + 指标并集行表）；--provenance 收任意 N（service 原生
    list 语义）。
    """
    if provenance:
        from rfauto.service.api import compare_runs_provenance
        result = compare_runs_provenance(list(run_ids))
        if json_output:
            _emit(result, "查询失败", json_output=True)
            return
        if not result.get("ok"):
            console.print("[red]✗ 查询失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    if len(run_ids) > 2:
        # SN-7（W6-A）：N-way 对比矩阵（service 层原生 list 语义，壳层
        # 此前砍到 2——N>2 时不再需要逐对手工两两调）
        from rfauto.service.batch_ops_service import compare_runs_nway

        result = compare_runs_nway(list(run_ids))
        if json_output:
            _emit(result, "对比失败", json_output=True)
            return
        if not result.get("ok"):
            console.print("[red]✗ 对比失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        table = Table(title=f"run N-way 对比（{result['n_runs']} 个）")
        table.add_column("指标", style="cyan")
        for r in result["runs"]:
            table.add_column(str(r["run_id"]), justify="right", overflow="fold")
        table.add_column("spread", justify="right")
        for row in result["per_metric"]:
            cells = []
            for r in result["runs"]:
                v = row.get(r["run_id"])
                cells.append(f"{v:.4f}" if isinstance(v, float) else str(v))
            spread = row.get("spread")
            table.add_row(str(row["metric"]), *cells,
                          "-" if spread is None else f"{spread:.4f}")
        console.print(table)
        return

    run_id_a, run_id_b = run_ids[0], run_ids[1]
    from rfauto.service.api import compare_runs

    result = compare_runs(run_id_a, run_id_b)
    if json_output:
        # VI-5 W2-C：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "对比失败", json_output=True)
        return

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
    run_id: str = typer.Argument(None, help="run_id（runs/ 下的目录名；批量模式可省）"),
    batch_all: bool = typer.Option(False, "--all",
                                   help="批量面（SN-6）：扫 runs 根全部有 meta 的 run 逐个体检并聚合红绿账"),
    runs_root: str = typer.Option("runs", "--runs-root", help="runs 根目录（批量面扫描域）"),
    since: str = typer.Option(None, "--since",
                              help="批量面起始日期 YYYY-MM-DD（meta.timestamp 闭区间）"),
    template: str = typer.Option(None, "--template",
                                 help="批量面模板过滤（meta.model 等值）"),
    campaign: str = typer.Option(None, "--campaign",
                                 help="批量面战役目录（扫 runs-root 下该二级目录）"),
    limit: int = typer.Option(500, "--limit", help="批量面上限数（防误扫全湖）"),
    json_out: bool = typer.Option(False, "--json", help="输出原始 JSON（供门禁/脚本消费）"),
) -> None:
    """对单次 run 做求解健康度体检（G11：历史踩坑教训内核化）。

    检查项：激励体积死(#174)/cost 退化(#195)/CFL 时间步塌缩(#152)/
    1.0491 探针窗/无源性/互易性/非物理增益。退出码：healthy=0；
    suspect/unhealthy 或 run 目录不存在=1（与 ok 字段/注册表门禁口径一致）。

    --all 批量面（SN-6，W6-A）：G11 门从"手工逐点"变周批门——逐 run
    health_check_run 聚合红绿账；退出码 unhealthy 名单非空=1（与数据集
    物化 health_gate 同口径：仅真实 FAIL 拦，suspect 放行留档）。
    """
    if batch_all:
        from rfauto.service.health_service import health_check_batch

        result = health_check_batch(
            runs_dir=runs_root, since=since, template=template,
            campaign=campaign, limit=limit)
        if json_out:
            console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            console.print(f"[bold]run 健康度批量体检[/bold]（root={result.get('runs_root')}"
                          f"{'/' + campaign if campaign else ''}）")
            console.print(f"  体检 {result.get('n_checked', 0)} 个"
                          f"  green {len(result.get('healthy') or [])}"
                          f"  yellow {len(result.get('suspect') or [])}"
                          f"  red {len(result.get('unhealthy') or [])}"
                          f"  failed {len(result.get('failed') or [])}"
                          f"{'  （截断于 --limit）' if result.get('truncated') else ''}")
            for name in result.get("unhealthy") or []:
                console.print(f"  [red]- {name}[/red]")
            for name, msg in (result.get("failed") or {}).items():
                console.print(f"  [yellow]- {name}: {msg}[/yellow]", markup=False)
        if result.get("unhealthy") or result.get("failed"):
            raise typer.Exit(code=1)
        return

    if not run_id:
        console.print("[red]✗ 单 run 体检需要 run_id（批量面请加 --all）[/red]")
        raise typer.Exit(code=2)
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


# ─── runs diff / runs watch（SN-15 / SN-19，W6-A 2026-10-06）────────────────

@runs_app.command("diff")
def runs_diff_cmd(
    run_id_a: str = typer.Argument(..., help="run_id A"),
    run_id_b: str = typer.Argument(..., help="run_id B"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """双 run 深度只读对比（配置递归 diff+指标 Δ+S 曲线+判读提示）。

    UI /api/runs/diff 同源能力（service/runs_diff_service 唯一事实源）的
    CLI 对等叶（SN-15）；只读不写盘不触发求解。
    """
    from rfauto.service.runs_diff_service import runs_diff

    result = runs_diff(run_id_a, run_id_b)
    if json_output:
        _emit(result, "run 对比失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ run 对比失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    a, b = result.get("a") or {}, result.get("b") or {}
    console.print(f"[bold]run diff[/bold]  {a.get('run_id')} vs {b.get('run_id')}"
                  f"  （model {a.get('model')} vs {b.get('model')}，"
                  f"adapter {a.get('adapter')} vs {b.get('adapter')}）")
    params_diff = result.get("params_recursive_diff") or []
    console.print(f"  配方快照差异 {len(params_diff)} 处")
    for e in params_diff[:20]:
        console.print(f"    {e.get('kind')}: {e.get('path')}"
                      f"  {e.get('a')!r} → {e.get('b')!r}", markup=False)
    delta = result.get("metrics_delta") or {}
    if delta:
        table = Table(title="指标 Δ（b−a）")
        table.add_column("指标", style="cyan")
        table.add_column("a", justify="right")
        table.add_column("b", justify="right")
        table.add_column("Δ", justify="right")
        for k, d in sorted(delta.items()):
            fmt = lambda x: f"{x:.4f}" if isinstance(x, float) else str(x)  # noqa: E731
            dlt = d.get("delta")
            table.add_row(k, fmt(d.get("a")), fmt(d.get("b")),
                          "-" if dlt is None else f"{dlt:.4f}")
        console.print(table)
    for h in result.get("verdict_hints") or []:
        console.print(f"  [cyan]*[/cyan] {h}", markup=False)


@runs_app.command("watch")
def runs_watch_cmd(
    run_id: str = typer.Argument(..., help="run_id（runs/ 目录名；job_id 亦可）"),
    interval: float = typer.Option(5.0, "--interval",
                                   help="轮询间隔秒（缺省 5）"),
    timeout: float = typer.Option(3600.0, "--timeout",
                                  help="最长等待秒（缺省 3600，超时退出码 1）"),
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="逐 tick JSONL 打点（管道友好）"),
) -> None:
    """跟踪 run 至终态（SN-19 --watch 泛化：CLI 轮询打点，零写入）。

    与 MCP wait_job 同源数据链（poll_job：注册表 → meta.json 磁盘回落）；
    终态 done=0，failed/cancelled/solve_failed/超时=1。
    """
    from rfauto.cli.domains._core import _watch_poll

    _watch_poll(run_id, interval_s=interval, timeout_s=timeout,
                json_output=json_output, label="run")


# ─── runs monitor / retrieve-similar（W1-A 孤儿接线单元 15a/15b）─────────────
# 15a：runtime_monitor_service 周期体检（G11 门周批化；#268 进度/#262 截断/
# NrTS 触顶/#323 能量停滞四类时序判据）；15b：meta_retrieval_service 检索式
# warm-start 先验（DA-2 k-NN 元特征，确定性零学习）。全部薄壳直通 _emit；
# 历史库/查询元特征零计算透传（铁律 7：数值只由内核产出）。


@runs_app.command("monitor")
def runs_monitor_cmd(
    run_dir: str = typer.Argument(..., help="run 目录（--cycle 时为 runs 根目录）"),
    cycle: bool = typer.Option(False, "--cycle",
                               help="周期面：对目录下全部 run 逐个体检并聚合红绿名单"),
    nr_ts: int = typer.Option(None, "--nr-ts",
                              help="引擎 NrTS 上限（给了才做触顶判据，取自 meta/config）"),
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="JSON 信封输出（供门禁/脚本消费）"),
) -> None:
    """run 目录周期体检（进度/截断嫌疑/NrTS 触顶/能量停滞四类时序判据）。

    退出码门禁语义：envelope ok=False 或 verdict=red（--cycle 时红名单
    非空）→ 1；其余 0。目录无时域产物 → verdict=unknown 如实回显。
    """
    from rfauto.service.runtime_monitor_service import monitor_cycle, monitor_run_dir

    if cycle:
        result = monitor_cycle(run_dir, nr_ts=nr_ts)
        red = bool(result.get("red"))
    else:
        result = monitor_run_dir(run_dir, nr_ts=nr_ts)
        red = result.get("verdict") == "red"
    _emit(result, "run 体检失败", json_output=json_output)
    if json_output:
        if red:
            raise typer.Exit(code=1)
        return
    if cycle:
        console.print(f"[green]✓ 周期体检[/green]  监测 {result.get('n_monitored', 0)} 个 run"
                      f"  红 {len(result.get('red') or [])}"
                      f"  黄 {len(result.get('yellow') or [])}"
                      f"  unknown {len(result.get('unknown') or [])}")
        for name, verdict in (result.get("verdicts") or {}).items():
            console.print(f"  {name}: {verdict}", markup=False)
        for name, msg in (result.get("failed") or {}).items():
            console.print(f"  {name}: 体检失败 {msg}", markup=False, style="red")
    else:
        verdict = str(result.get("verdict", "unknown"))
        console.print(f"  run: {result.get('run_id', run_dir)}  verdict: {verdict}")
        for reason in result.get("reasons") or []:
            console.print(f"  - {reason}", markup=False)
    if red:
        console.print("[red]✗ 红 verdict（触顶/越界判据命中，门禁退出码 1）[/red]")
        raise typer.Exit(code=1)


@runs_app.command("retrieve-similar")
def runs_retrieve_similar_cmd(
    recipe: str = typer.Option(..., "--recipe",
                               help="新战役配方 YAML 路径（提取 model 与 params 数值字段作查询元特征，直通零计算）"),
    top: int = typer.Option(5, "--top", "-k",
                            help="检索近邻数 K（历史库小于 K 时返回全部有效条目）"),
    library: str = typer.Option(None, "--library",
                                help="历史库条目 JSON 文件路径（core meta_retrieval schema 条目数组；缺省空库降级）"),
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="JSON 信封输出（供脚本消费）"),
) -> None:
    """检索式 warm-start 先验（DA-2 k-NN 元特征相似检索，确定性零学习）。

    查询元特征从配方直通提取（model/dim/params 内 f0_ghz 与 bw_frac 数值
    原样透传，缺项由内核显式报错不臆造）；历史库由 --library 显式供给
    （服务层零 IO 契约）。输出 warm_start_samples 与既有 warm-start 通道
    入参形态对齐，可直接喂优化器。
    """
    from rfauto.service.meta_retrieval_service import retrieve_meta_warm_start

    loaded = _load_retrieval_inputs(recipe, library)
    if not loaded.get("ok"):
        _emit(loaded, "检索输入读取失败", json_output=json_output)
        return
    result = retrieve_meta_warm_start(loaded["query"], loaded["library"], k=top)
    _emit(result, "相似检索失败", json_output=json_output)
    if json_output:
        return
    neighbors = result.get("neighbors") or []
    console.print(f"[green]✓ 检索完成[/green]  库 {result.get('n_library', 0)} 条"
                  f"（有效 {result.get('n_valid', 0)}）  返回近邻 {len(neighbors)} 个"
                  f"  口径 {result.get('metric')}")
    for nb in neighbors:
        console.print(f"  {nb.get('rank')}. {nb.get('entry_id')}"
                      f"  相似度 {nb.get('similarity')}"
                      f"  cost {nb.get('cost')}", markup=False)
    n_ws = len(result.get("warm_start_samples") or [])
    if n_ws:
        console.print(f"  warm_start_samples {n_ws} 点（可直接喂优化器 warm_start 通道）")


def _load_retrieval_inputs(recipe_path: str, library_path: str | None) -> dict:
    """读配方 YAML 与可选历史库 JSON，提取查询元特征（直通零计算）。

    元特征提取只做结构与命名透传：model 字符串、dim=params 键数（int）、
    params 内 f0_ghz 与 bw_frac 数值原样透传（{value: x} 包装自动剥壳）；
    缺项不臆造，交内核显式 ValueError → ok=False 信封。文件级失败返回
    ok=False 形（_emit 兜底 fail_msg），不抛裸 traceback。

    Returns:
        dict: 成功 ``{"ok": True, "query": 元特征, "library": 条目列表}``；
        失败 ``{"ok": False, "errors": [...]}``。
    """
    import yaml

    try:
        data = yaml.safe_load(Path(recipe_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {"ok": False, "errors": [f"配方不可读: {exc}"]}
    if not isinstance(data, dict):
        return {"ok": False, "errors": [f"配方根节点需为映射: {recipe_path}"]}
    params = data.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    query: dict = {"model": str(data.get("model", "")), "dim": len(params)}
    for key in ("f0_ghz", "bw_frac"):
        val = params.get(key)
        if isinstance(val, dict):
            val = val.get("value")
        if val is not None:
            query[key] = val

    lib: list = []
    if library_path:
        try:
            lib_data = json.loads(Path(library_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"ok": False, "errors": [f"历史库不可读: {exc}"]}
        if not isinstance(lib_data, list):
            return {"ok": False,
                    "errors": ["历史库必须是 JSON 条目数组（core meta_retrieval schema）"]}
        lib = lib_data
    return {"ok": True, "query": query, "library": lib}


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
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="计划面（SN-18）：枚举将物化的 run 清单，零写入"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """把 runs/ 点级数据物化为 Parquet 数据集（指纹去重 + manifest 落盘）。"""
    from rfauto.service.dataset_service import materialize_dataset

    run_ids = [r.strip() for r in runs.split(",") if r.strip()] if runs else None
    result = materialize_dataset(run_ids, name=name, out_dir=out_dir,
                                 registry_sync=registry_sync, dry_run=dry_run)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "物化失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 物化失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    if result.get("mode") == "dry-run":
        planned = result.get("would_materialize") or []
        console.print(f"[cyan]物化计划（dry-run，零写入）[/cyan] name={result.get('name')}"
                      f"  格式: {result.get('fmt')}")
        console.print(f"  将物化 {len(planned)} 个 run"
                      f"（健康门 not evaluated）")
        for rid in planned[:20]:
            console.print(f"    {rid}", markup=False)
        if len(planned) > 20:
            console.print(f"    … 共 {len(planned)} 个")
        if result.get("missing_runs"):
            console.print(f"  [red]run 不存在: {', '.join(result['missing_runs'])}[/red]")
        return
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
    order_by: str = typer.Option(None, "--order-by",
                                 help="排序列名（SN-13；如 cost）"),
    order: str = typer.Option("desc", "--order", help="排序方向 asc 或 desc（缺省 desc）"),
    offset: int = typer.Option(0, "--offset", help="分页偏移（SN-13，在 limit 前生效）"),
    fmt: str = typer.Option("json", "--format",
                            help="输出格式 json 或 csv（SN-13；csv 为 RFC4180 文本）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """DuckDB 直查 Parquet 数据集（谓词下推/列裁剪，where 经白名单校验）。

    SN-13 增量：--order-by/--order/--offset/--format 与信封 total_rows
    （过滤后 LIMIT/OFFSET 前总行数，治 #369 截断误当总数复发）。
    """
    from rfauto.service.dataset_service import query_dataset

    cols = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
    result = query_dataset(name, where=where, columns=cols, limit=limit,
                           out_dir=out_dir, order_by=order_by, order=order,
                           offset=offset, out_fmt="csv" if fmt == "csv" else "json")
    if json_output:
        # VI-5 W2-C：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "查询失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 查询失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    if result.get("csv"):
        # --format csv：文本直出（管道/落文件），不叠 rich 表
        console.print(result["csv"], markup=False)
        return
    total = result.get("total_rows")
    total_s = f"，过滤后共 {total} 行" if isinstance(total, int) else ""
    table = Table(title=f"数据集 {result['dataset']}（{result['n_rows']} 行{total_s}"
                        f"{'，where: ' + result['where'] if result['where'] else ''}）")
    for col in result["columns"]:
        table.add_column(col, style="cyan", overflow="fold")
    for row in result["rows"]:
        # 星号解包必须包住完整生成器表达式：裸 *expr for c in ... 是
        # SyntaxError（"iterable unpacking cannot be used in comprehension"），
        # 会使整个 cli.main 模块不可 import（G11 联调时发现，2026-09-09）
        table.add_row(*(
            ("" if row.get(c) is None else str(row.get(c))) for c in result["columns"]
        ))
    console.print(table)


def _datasets_json(result: dict, fail_msg: str,
                   json_output: bool = False) -> None:
    """数据集余量命令共用出口：失败 → --json 信封（缺省红字既有形态逐字节不动
    + 退出码 1）；成功恒 JSON 直出。

    VI-5 W6-B：成功面缺省即 JSON（命令侧 --json 为归一兼容位）；失败面经
    --json 升级为 _emit 信封（成功+失败同构），缺省红字不动。
    """
    if not result.get("ok"):
        if json_output:
            _emit(result, fail_msg, json_output=True)
            return
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
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功恒 JSON 直出；失败面 --json 升级为信封）"),
) -> None:
    """发现工作目录形态真机产物（无 meta.json 的 runs 子目录，只读）。"""
    from rfauto.service.dataset_service import discover_workdir_candidates

    result = discover_workdir_candidates(runs_root, models=_datasets_families(models))
    _datasets_json(result, "工作目录产物发现失败", json_output=json_output)


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
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """工作目录形态真机产物导入数据集注册表（无 meta.json 的漏数口）。"""
    from rfauto.service.dataset_service import import_workdir_runs

    run_ids = [r.strip() for r in runs.split(",") if r.strip()] if runs else None
    result = import_workdir_runs(
        run_ids, name=name, runs_root=runs_root, out_dir=out_dir,
        models=_datasets_families(models), health_gate=not no_health_gate, fmt=fmt,
        registry_sync=registry_sync)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "工作目录导入失败", json_output=True)
        return
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
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """数据集覆盖度：点数分布 + 参数空间逐维占用率/最弱维（WP2.4①）。"""
    from rfauto.service.dataset_insights import dataset_coverage

    result = dataset_coverage(name, out_dir=out_dir, bins=bins)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "覆盖度统计失败", json_output=True)
        return
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
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """ground truth 标注（白名单通道）+ 6.3 解锁进度（幂等回写 manifest）。"""
    from rfauto.service.dataset_insights import annotate_ground_truth

    result = annotate_ground_truth(name, threshold=threshold, out_dir=out_dir)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "标注失败", json_output=True)
        return
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
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功恒 JSON 直出；失败面 --json 升级为信封）"),
) -> None:
    """公开/私有双集切换（public 是 HF 导出放行前提；manifest 回写）。"""
    from rfauto.service.dataset_insights import set_dataset_visibility

    _datasets_json(set_dataset_visibility(name, set_to, out_dir=out_dir),
                   "可见性切换失败", json_output=json_output)


@datasets_app.command("export-hf")
def datasets_export_hf(
    name: str = typer.Argument(..., help="数据集名"),
    license: str = typer.Option("", "--license", help="数据卡 license 字段"),
    allow_private: bool = typer.Option(False, "--allow-private",
                                       help="显式允许导出 private 数据集"),
    out_dir: Path = typer.Option(Path("runs/datasets"), "--out-dir"),  # noqa: B008
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """HF datasets 本地目录布局导出（parquet 分片 + README 数据卡，确定性逐字节一致）。"""
    from rfauto.service.dataset_insights import export_hf_dataset

    result = export_hf_dataset(name, out_dir=out_dir, license=license,
                               allow_private=allow_private)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "导出失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 导出失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ HF 导出完成[/green] → {result.get('hf_dir')}")
    for f in result.get("files") or []:
        console.print(f"  {f}")
