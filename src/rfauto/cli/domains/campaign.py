"""campaign 战役状态机子应用（UX-B6 自 cli/domains/bands_uq.py 机械拆分，2026-10-08；函数体逐字节未动）。

注册序守卫：``app.add_typer(campaign_app, name="campaign")`` 留在
bands_uq.py 原位置执行（click 树 top_level 注册序金快照
tests/gold/cli_registration_order.json 零漂移），本模块只定义不注册；
bands_uq.py 顶部薄壳 re-export 六个命令面名（main.py 既有消费方零破坏）。
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _kv_floats as _kv_floats
from rfauto.cli.domains._core import console as console

campaign_app = typer.Typer(help="战役状态机（calibrate→prefilter→tune→tolerance→report→final_verify）")


@campaign_app.command("plan")
def campaign_plan_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    high_adapter: str = typer.Option("hfss", "--high-adapter", help="终验适配器（none=不加终验）"),
    mid_adapter: str = typer.Option("openems", "--mid-adapter", help="中保真精算适配器"),
    calibrate_samples: int = typer.Option(9, "--calibrate-samples", help="校准阶段样本预算"),
    tune_budget: int = typer.Option(None, "--tune-budget", help="tune 预算（缺省取配方 limits.max_trials/30）"),
    tolerances: list[str] = typer.Option(  # noqa: B008
        None, "--tolerances",
        help="公差剖面 参数名=σ（可多次，如 --tolerances arm_len_mm=0.05）；"
             "键须在配方 optimization.params 空间。缺省不写（tolerance 阶段如实失败，v1 不猜剖面）"),
    out_dir: str = typer.Option(None, "--out-dir", "-o", help="落盘目录（写 campaign.plan.json）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """配方 → 确定性战役阶段队列（含依赖/预算/license 门槛）；--out-dir 落盘。"""
    from rfauto.service.campaign_manager import plan_campaign, save_plan

    # ge9 审查 P1-2：公差剖面的 CLI 形态复用 _kv_floats 单源解析器
    # （k=参数名 v=σ，与 _exec_tolerance 消费的 stage_extra.tolerances 同形；
    # Windows 壳层 JSON 内联引号炼狱不引入——k=v 可多次即等价表达）。
    tol = _kv_floats(tolerances, "--tolerances") if tolerances else None
    plan = plan_campaign(recipe, high_adapter=high_adapter, mid_adapter=mid_adapter,
                         calibrate_samples=calibrate_samples, tune_budget=tune_budget,
                         tolerances=tol)
    if not plan.get("ok"):
        # 失败面自始即 _emit 信封（json_output 缺省 True）——缺省路径逐字节不动，
        # --json 只切换成功面（信封 vs 表格）。
        _emit(plan, "立战役失败")
    if json_output:
        # VI-5 W6-B：--json 信封（--out-dir 落盘副作用保持，路径并入信封）
        if out_dir:
            path = save_plan(plan, out_dir)
            console.print_json(json.dumps(
                {**plan, "plan_path": str(path)},
                ensure_ascii=False, default=str))
        else:
            console.print_json(json.dumps(plan, ensure_ascii=False, default=str))
        return
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
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """推进战役状态机（stage_failed 时依赖它的未完成阶段递归 aborted）并回写落盘。"""
    from rfauto.service.campaign_manager import apply_event, load_plan, save_plan

    loaded = load_plan(plan_path)
    if not loaded.get("ok"):
        # 失败面自始即 _emit 信封（缺省路径逐字节不动）；--json 只切换成功面。
        _emit(loaded, "读取战役计划失败")
    # A4 战役级 skill 自动沉淀（ge8e W2）：campaign run_id = 计划所在目录名
    # （runs/<campaign_id>/ 惯例），沉淀产物落该目录 skills/ 子目录（同 F8
    # 单 run 口径：不污染仓根技能库）；钩子内部 best-effort（#105）。
    campaign_dir = Path(loaded["path"]).parent
    result = apply_event(loaded["plan"], stage, event, detail=detail,
                         run_id=campaign_dir.name,
                         skill_output_dir=campaign_dir / "skills")
    if not result.get("ok"):
        # 同上：失败面自始即信封，缺省路径逐字节不动。
        _emit(result, "事件应用失败")
    plan = result.get("plan", loaded["plan"])
    save_plan(plan, campaign_dir)
    if json_output:
        # VI-5 W6-B：--json 信封（回写落盘副作用保持）
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
        return
    console.print(f"[green]✓ {stage} ← {event}[/green]  verdict={plan.get('verdict')}  "
                  f"done={plan.get('n_done')}  dead={plan.get('n_dead')}")


@campaign_app.command("list")
def campaign_list_cmd(
    root: str = typer.Option("runs", "--root", help="扫描根目录"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """扫 root 下全部已落盘战役计划（总览）。"""
    from rfauto.service.campaign_manager import list_campaign_plans

    result = list_campaign_plans(root)
    if json_output:
        # VI-5 W6-B：--json 信封（空表如实 ok=True campaigns=[]）
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
        return
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


@campaign_app.command("run")
def campaign_run_cmd(
    plan_path: str = typer.Argument(..., help="campaign.plan.json 或其所在目录"),
    run_dir: str = typer.Option(None, "--run-dir",
                                help="运行目录（缺省=计划所在目录；期刊/锁/报告落点）"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="只打印拓扑序+阶段预算+互斥预览，零执行"),
    detach: bool = typer.Option(False, "--detach",
                                help="后台执行（v1 如实 skipped 登记，未接线）"),
    resume: bool = typer.Option(False, "--resume",
                                help="断点续跑重调同参（续跑语义由期刊承担）"),
    remote: str = typer.Option(
        None, "--remote",
        help="plan 级远程路由旗标（E-06 拆批件，2026-10-08）：战役级缺省路由到"
             "注册表机器（发射前 license 预检 fail-skip+资源日历窗判定；stage 级 "
             "\"remote\" 键在场时逐 stage 声明优先；缺座位载荷=如实 SKIP 不假绿，"
             "recipe-loop 远跑为拆批余件）。值=机器名或 true（缺省登记机器）；"
             "缺省（不带 --remote）=本机路径零变化"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """一键闭环执行战役计划（calibrate→…→report→final_verify；断点续跑内嵌）。"""
    from rfauto.service.campaign_executor import run_campaign

    result = run_campaign(plan_path, run_dir=run_dir, dry_run=dry_run,
                          detach=detach, resume=resume,
                          remote=(remote if remote else None))
    _emit(result, "战役执行失败", json_output=json_output)
    if json_output:
        return
    if result.get("skipped"):
        console.print(f"[yellow]! skipped：{result.get('reason')}[/yellow]")
        raise typer.Exit(code=0)
    if result.get("dry_run"):
        console.print("[cyan]dry-run 执行计划（零执行）：[/cyan]")
        console.print(f"  拓扑序: {' → '.join(result.get('order') or [])}")
        for s in result.get("stages") or []:
            console.print(f"  - {s.get('stage'):<14} kind={s.get('kind'):<12}"
                          f" adapter={s.get('adapter'):<10}"
                          f" budget={s.get('budget')}"
                          f" depends={','.join(s.get('depends_on') or []) or '-'}")
        preview = result.get("mutex_preview") or {}
        console.print(f"  互斥预览: run 锁={preview.get('run_instance_lock')}"
                      f"｜solve 机器锁={preview.get('solve_machine_lock')}")
        if result.get("license_gated_stages"):
            console.print(f"  license 门槛阶段: "
                          f"{','.join(result['license_gated_stages'])}")
        raise typer.Exit(code=0)
    console.print(f"[green]✓ 战役完成[/green]  verdict={result.get('verdict')}"
                  f"  done={result.get('n_done')}  dead={result.get('n_dead')}"
                  f"  hit={result.get('n_hit')}"
                  f"  recompute={result.get('n_recompute')}")
    for s in result.get("stage_view") or []:
        color = {"done": "green", "failed": "red", "aborted": "red",
                 "skipped": "dim"}.get(str(s.get("status")), "yellow")
        console.print(f"  [{color}]{s.get('status'):<8}[/{color}] "
                      f"{s.get('stage')}（节点态 {s.get('node_status')}）")
    console.print(f"  权威账本: {result.get('state_path')}")
    raise typer.Exit(code=0)


@campaign_app.command("digest")
def campaign_digest_cmd(
    root: str = typer.Option("runs", "--root", help="战役计划扫描根目录（直属子目录 campaign.plan.json，与 campaign list 同口径）"),
    out_dir: str = typer.Option(None, "--out-dir", help="digest 产物落盘目录（缺省 runs/campaign_digest/）"),
    since_h: float = typer.Option(None, "--since-h", help="时间窗：只统计计划文件距今 N 小时内的战役（24=昨晚口径；缺省不过滤）"),
    include_running: bool = typer.Option(False, "--include-running", help="把 RUNNING 等非终态战役也计入摘要（如实标注进行中）"),
    no_write: bool = typer.Option(False, "--no-write", help="只打印摘要不落盘"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """扫描战役终态（COMPLETE/PARTIAL/ABORTED）聚合成 zh 人读摘要，JSON+文本产物落 runs/ 下。"""
    from rfauto.service.campaign_digest_service import campaign_digest

    result = campaign_digest(
        root, out_dir=(out_dir if out_dir else None), since_h=since_h,
        include_running=include_running, write=not no_write)
    _emit(result, "战役摘要生成失败", json_output=json_output)
    if json_output:
        return
    console.print(result["summary_text"], markup=False, soft_wrap=True)
    artifacts = result.get("artifacts") or {}
    if artifacts:
        console.print(f"  产物: {artifacts.get('json')}")
        console.print(f"        {artifacts.get('txt')}")


@campaign_app.command("queue-daemon")
def campaign_queue_daemon_cmd(
    root: str = typer.Option("runs", "--root", help="队列扫描根目录（直属子目录的 campaign.plan.json=队列项，与队列页同口径）"),
    once: bool = typer.Option(False, "--once", help="单步模式：执行一个 tick 即退出（测试/cron 拉起）"),
    interval_s: float = typer.Option(60.0, "--interval-s", help="常驻轮询间隔（秒）"),
    machine: str = typer.Option(None, "--machine", help="license 预检指名机器（缺省=注册表缺省机器）"),
    license_gate: bool | None = typer.Option(
        None, "--license-gate/--no-license-gate",
        help="license 预检门三态（#277 惯例）：缺省=仅对声明 license 消耗面"
             "（stage license_gated/adapter=hfss）的计划预检；--license-gate="
             "全部强制预检；--no-license-gate=一律不预检"),
    state_path: str = typer.Option(None, "--state-path", help="队列状态 JSON 落盘路径（缺省 runs/campaign_queue/queue_state.json，崩溃重启可续）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出（--once=信封；常驻=逐 tick JSON 行流）"),
) -> None:
    """campaign 排队常驻执行体（UX-B7）：轮询队列→日历窗→license 预检→逐项发射（发射后不等）。"""
    from rfauto.service.campaign_queue_daemon import run_queue_daemon

    def _tick_line(payload: dict) -> None:
        # 常驻逐 tick 输出：--json=单行 JSON 流（机器可读可 grep）；
        # 缺省=rich 单行（tick 序号+动作词表）。观测面抛错不拆循环（#105，
        # 服务侧已兜底），此处自身也 suppress 兜底。
        # markup 纪律（ge8e 审查批）：payload 动态内容禁走 rich markup
        # 解析——plan/reason 等字符串含 "[...]" 形态（如 runs/[debug]x）
        # 会被当样式标签整段吞掉，JSON 行流被静默截改；故 JSON 分支
        # markup=False（保单行机器可读），人读分支动态段 rich.markup.escape。
        with contextlib.suppress(Exception):
            if json_output:
                console.print(json.dumps(payload, ensure_ascii=False,
                                         default=str),
                              markup=False, soft_wrap=True)
            else:
                from rich.markup import escape

                actions = [str(a.get("action") or "")
                           for a in payload.get("actions") or []
                           if isinstance(a, dict)]
                console.print("[cyan]\\[queue-daemon][/cyan] "
                              f"tick={payload.get('tick')} "
                              f"actions={escape(str(actions))}",
                              soft_wrap=True)

    result = run_queue_daemon(
        root=root, machine=(machine if machine else None),
        license_gate=license_gate, interval_s=interval_s, once=once,
        state_path=state_path,
        log=(None if once else _tick_line))
    _emit(result, "queue-daemon 启动失败", json_output=json_output)
    if json_output:
        return
    status = result.get("items") or {}
    console.print(
        f"[green]✓ queue-daemon 退出[/green]  ticks={result.get('ticks')}  "
        f"items={status.get('n_items', 0)}  "
        f"in_flight={status.get('in_flight', 0)}  "
        f"状态档: {result.get('state_path')}")
    final = result.get("final") or {}
    for a in final.get("actions") or []:
        kind = str(a.get("action") or "")
        detail = f" pid={a['pid']}" if a.get("pid") is not None else ""
        console.print(f"  - {kind}: {a.get('plan') or a.get('reason', '')}"
                      f"{detail}")

