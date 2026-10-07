"""jobs/cache 子应用 + link/report/export-report-pdf/replay/validate（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── jobs ─────────────────────────────────────────────────────────────────────

jobs_app = typer.Typer(help="任务管理")
app.add_typer(jobs_app, name="jobs")


@jobs_app.command("status")
def jobs_status(
    job_id: str = typer.Argument(None, help="任务 ID（不填则列出全部）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """查询任务状态 / 列出最近的 runs（SQLite 索引）。"""
    from rfauto.service.api import poll_job
    if job_id:
        result = poll_job(job_id)
        if json_output:
            # VI-5 W6-B：--json 信封（--json 形态经 _emit 同构；缺省 raw JSON 不动）
            _emit(result, "任务查询失败", json_output=True)
            return
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False))
        return
    from rfauto.infra.run_store import list_runs
    rows = list_runs()
    if json_output:
        # VI-5 W6-B：清单信封（空表如实 runs=[]）
        console.print_json(json.dumps(
            {"ok": True, "n_runs": len(rows), "runs": rows},
            ensure_ascii=False, default=str))
        return
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
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """取消任务。

    排队中（未开始执行）→ 直接取消；已开始执行 → 标记取消请求，
    AEDT 求解不可安全中断，当前 run 跑完后结果被丢弃。
    """
    from rfauto.service.job_registry import get_job_registry

    snapshot = get_job_registry().cancel(job_id)
    if json_output:
        # VI-5 W6-B：失败/成功同构信封（state 三态原样透传；_emit 失败即 Exit）
        if snapshot is None:
            _emit({"ok": False, "errors": [
                f"未找到任务: {job_id}（进程内注册表无此 job；"
                f"跨进程历史 run 请直接用 jobs status 查看）"]},
                "任务取消失败", json_output=True)
        else:
            _emit({"ok": True, "job_id": job_id, "state": snapshot["state"]},
                  "任务取消失败", json_output=True)
        return
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


@jobs_app.command("watch")
def jobs_watch(
    job_id: str = typer.Argument(..., help="任务 ID（job_ 前缀异步任务；run_id 亦可）"),
    interval: float = typer.Option(5.0, "--interval",
                                   help="轮询间隔秒（缺省 5）"),
    timeout: float = typer.Option(3600.0, "--timeout",
                                  help="最长等待秒（缺省 3600，超时退出码 1）"),
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="逐 tick JSONL 打点（管道友好）"),
) -> None:
    """跟踪任务至终态（SN-19 --watch 泛化：CLI 轮询打点，零写入）。

    与 MCP wait_job 同源数据链（poll_job：进程内注册表 → meta.json 磁盘
    回落，SN-10 阶段进度逐 tick 透传）；终态 done=0，
    failed/cancelled/solve_failed/超时=1。
    """
    from rfauto.cli.domains._core import _watch_poll

    _watch_poll(job_id, interval_s=interval, timeout_s=timeout,
                json_output=json_output, label="job")


# ─── cache ────────────────────────────────────────────────────────────────────

cache_app = typer.Typer(help="缓存管理")
app.add_typer(cache_app, name="cache")


@cache_app.command("clear")
def cache_clear(
    model: str = typer.Option(None, "--model", "-m", help="只清除指定模型的缓存"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """手动清理结果缓存。"""
    from rfauto.infra.result_cache import ResultCache
    rc = ResultCache()
    removed = rc.clear(model_name=model)
    if json_output:
        # VI-5 W6-B：--json 信封（清理为无失败面操作，ok=True 如实）
        console.print_json(json.dumps(
            {"ok": True, "removed": removed, "model": model},
            ensure_ascii=False, default=str))
        return
    scope = f"（模型: {model}）" if model else ""
    console.print(f"[green]✓ 缓存已清除{scope}：移除 {removed} 个条目[/green]")


# ─── link ─────────────────────────────────────────────────────────────────────

@app.command()
def link(
    run_id: str = typer.Argument(..., help="run_id"),
    to_ads: bool = typer.Option(False, "--to-ads",
                                help="执行 ADS 联动链路（缺省不联动，只定位结果——E2-2 接线）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """把某次 HFSS 结果送进 ADS 联动链路（P3, N=2 往返；--to-ads 才执行）。"""
    from rfauto.service.api import run_link

    result = run_link(run_id, rounds=2, to_ads=to_ads)
    if json_output:
        # VI-5 W6-B：--json 信封（skipped 是合法零动作态，ok=True 如实）
        if result.get("skipped"):
            console.print_json(json.dumps(
                {"ok": True, "skipped": True, "reason": result.get("reason", "")},
                ensure_ascii=False, default=str))
            return
        _emit(result, "link 失败", json_output=True)
        return
    if result.get("skipped"):
        console.print("[yellow]○ 未执行 ADS 联动[/yellow]")
        console.print(f"  {result.get('reason', '')}")
        console.print("  （加 --to-ads 执行联动）")
        return
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
    run_id: str = typer.Argument(None, help="run_id（批量面可省，用 --dir 或 --all）"),
    output: str = typer.Option(None, "--output", "-o", help="输出文件路径"),
    fmt: str = typer.Option("markdown", "--format", "-f", help="报告格式: markdown | html"),
    batch_dir: str = typer.Option(None, "--dir",
                                  help="批量面（SN-8）：runs 根目录 → 最近 run 逐个出报告+汇总索引页"),
    batch_all: bool = typer.Option(False, "--all",
                                   help="批量面（SN-8）：run_id... 之外的等价开关（配 --limit）"),
    run_ids: list[str] = typer.Option(None, "--run-id", help="批量面：点名 run_id（可多次）"),  # noqa: B008
    limit: int = typer.Option(50, "--limit", help="批量面扫描上限（最近优先）"),
    index_dir: str = typer.Option(None, "--index-dir",
                                  help="汇总索引页落点（缺省 runs/report_batch）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """按已完成的 run 重建报告（markdown / html）。

    批量面（SN-8，W6-A）：--dir 传 runs 根目录（按 results/metrics.json
    存在性枚举、mtime 最近优先）或 --run-id 多次点名 → 逐 run 出报告 +
    汇总索引页 index.md（simci 是回归 diff 语义，与本批量并存不同用途）。
    """
    if batch_dir or batch_all or run_ids:
        from rfauto.service.batch_ops_service import discover_run_ids, report_runs_batch

        ids = list(run_ids or [])
        if batch_dir and not ids:
            disc = discover_run_ids(batch_dir, limit=limit)
            if not disc.get("ok"):
                _emit(disc, "批量扫描失败", json_output=json_output)
                return
            ids = list(disc.get("run_ids") or [])
        if not ids:
            _emit({"ok": False, "errors": [
                "批量面未发现可报告的 run（--dir 下无 results/metrics.json，"
                "或未给 --run-id）"]}, "批量报告失败", json_output=json_output)
            return
        result = report_runs_batch(ids, fmt=fmt,
                                   out_dir=index_dir or (Path("runs") / "report_batch"))
        _emit(result, "批量报告失败", json_output=json_output)
        if json_output:
            return
        console.print(f"[green]✓ 批量报告完成[/green]  ok {result.get('n_ok')}"
                      f" / failed {result.get('n_failed')}"
                      f"  索引: {result.get('index')}")
        return

    if not run_id:
        _emit({"ok": False, "errors": ["单 run 报告需要 run_id（批量面请加 --dir/--run-id）"]},
              "报告生成失败", json_output=json_output)
        return
    from rfauto.service.api import generate_report_for_run

    result = generate_report_for_run(run_id, fmt=fmt, output=output)
    if json_output:
        # VI-5 W2-C：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "报告生成失败", json_output=True)
        return
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
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """把已完成 run 的指标导出为多页 PDF 报告（WP4.7）。"""
    from rfauto.infra.report import export_report_pdf as _export_pdf
    from rfauto.service.api import get_metrics

    result = get_metrics(run_id)
    if json_output:
        # VI-5 W6-B：失败信封（--json 下 get_metrics 失败同构）
        if not result["ok"]:
            _emit(result, "PDF 报告导出失败", json_output=True)
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
        console.print_json(json.dumps(
            {"ok": True, "report_path": str(report_path),
             "metrics": data.get("metrics") or {}},
            ensure_ascii=False, default=str))
        return
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
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """复现：用该 run 的 recipe 快照重跑，并核对 plugin/schema 版本。"""
    from rfauto.service.api import replay_run

    result = replay_run(run_id)
    if json_output:
        # VI-5 W2-C：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "replay 失败", json_output=True)
        return

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
    recipe: str = typer.Argument(None, help="配方文件路径（批量面可省，用 --dir）"),
    batch_dir: str = typer.Option(None, "--dir",
                                  help="批量面（SN-8）：目录 → 逐个校验目录下全部 YAML 配方"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """校验配方文件（不执行仿真）。

    批量面（SN-8，W6-A）：--dir 传目录 → 逐文件校验并聚合 passed/failed
    名单；任一失败退出码 1（单文件失败不传染，逐文件 errors 留账）。
    """
    if batch_dir:
        from rfauto.service.batch_ops_service import validate_recipes_batch

        result = validate_recipes_batch(batch_dir)
        if json_output:
            _emit(result, "批量校验失败", json_output=True)
            return
        if not result.get("ok"):
            console.print("[red]✗ 批量校验失败[/red]")
            for err in result.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        console.print(f"[bold]批量配方校验[/bold]（{result.get('n_files')} 个）  "
                      f"通过 {len(result.get('passed') or [])}"
                      f"  失败 {len(result.get('failed') or [])}")
        for entry in result.get("results") or []:
            mark = "[green]✓[/green]" if entry.get("ok") else "[red]✗[/red]"
            console.print(f"  {mark} {entry.get('recipe')}", markup=False)
            for err in entry.get("errors") or []:
                console.print(f"      [red]- {err}[/red]")
        if not result.get("ok_all"):
            raise typer.Exit(code=1)
        return

    if not recipe:
        _emit({"ok": False, "errors": ["单文件校验需要配方路径（批量面请加 --dir）"]},
              "配方校验失败", json_output=json_output)
        return
    from rfauto.service.api import validate_recipe
    result = validate_recipe(recipe)

    if json_output:
        # VI-5 W2-C：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "配方校验失败", json_output=True)
        return

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
