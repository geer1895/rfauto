"""competition 子应用（单目标优化器族竞赛持久门；aurora_n O5 席，2026-10-31）。

单叶 run：T-N5 标量竞赛架（competition_scalar）运行时门——zero_wiring
REGISTRY O5 欠账清偿（此前仅测试+一次性探针脚本驱动）。同预算同 seed 组
竞赛：最优值 AUC 两阶段（半程/全程共享轨迹）+ 达标评估次数三套排名。
零数值逻辑转发 service/competition_service（规则 4）；内置合成 4 族与
首榜（runs/aurora_n/wave1_d）同源；带 --json（信封契约；Agent 消费面）。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

competition_app = typer.Typer(
    help="单目标优化器族竞赛（T-N5 标量架）：多引擎同预算同 seed 组竞赛，"
         "最优值 AUC 两阶段排名 + 达标评估次数，报表落 md+json")
app.add_typer(competition_app, name="competition")


def _csv(raw: str | None) -> list[str] | None:
    """逗号分隔串 → 名单（None/空白=缺省语义由服务层定）。"""
    if raw is None:
        return None
    items = [v.strip() for v in raw.split(",")]
    items = [v for v in items if v]
    return items or None


@competition_app.command("run")
def competition_run_cmd(
    engines: str = typer.Option(
        None, "--engines",
        help="参赛引擎逗号分隔名单（缺省=全部已注册；botorch_ei 显式点名"
             "走 opt-in 注册，未装 rfauto【botorch】extra 报安装指引）"),
    problems: str = typer.Option(
        None, "--problems",
        help="问题族逗号分隔名单（缺省=内置 4 族全跑：concave2d 凹/"
             "rastrigin2d 多谷/rosenbrock2d 窄谷/noisysphere4d 噪声）"),
    n_eval: int = typer.Option(
        60, "--n-eval",
        help="每引擎×族×seed 评估预算（两阶段截点=半程与全程，共享轨迹）"),
    seeds: str = typer.Option(
        "0,1,2", "--seeds", help="确定性种子逗号分隔名单（同 seed 重跑逐位）"),
    out: str = typer.Option(
        None, "--out",
        help="报表输出目录（写 report.md+report.json；缺省 runs/competition）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """跑单目标优化器族竞赛：三套排名 + 逐 run 明细，报表落 md+json。

    同预算同 seed 组竞赛（judge 只消费评估序目标值轨迹记分，#118 裁判/
    被测非共享代码路径）：阶段一=预算半程最优值 AUC（谁收敛快），阶段二=
    全程 AUC（谁终值好），达标评估次数（best 首次不超过 target 的序号）。
    确定性：同 seed 同参数重跑，报表剥离耗时字段后逐位一致。数值全部来自
    competition_scalar 确定性内核（本叶零数值逻辑，薄壳转发）。
    """
    from rfauto.service.competition_service import run_competition

    engine_list = _csv(engines)
    problem_list = _csv(problems)
    try:
        seed_list = [int(v) for v in _csv(seeds) or []]
    except ValueError:
        from rfauto.cli.domains._core import _emit_usage_error

        _emit_usage_error(
            f"--seeds 必须是逗号分隔整数，实际 {seeds!r}",
            json_output=json_output)
        return

    result = run_competition(
        engine_list, problem_list, n_eval=n_eval, seeds=seed_list)
    if not result.get("ok"):
        if json_output:
            _emit(result, "竞赛运行失败", json_output=True)
            return
        console.print("[red]✗ 竞赛运行失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    # ── 报表落盘（持久门本体：md 人读 + json 机读全量；--json/人读两模式
    # 同写。best-effort 观测面不阻塞——写盘失败不吞竞赛结果，只提示）──────
    out_dir = Path(out) if out is not None else Path("runs") / "competition"
    md_path = json_path = None
    write_note = ""
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / "report.md"
        json_path = out_dir / "report.json"
        md_path.write_text(result["report_md"], encoding="utf-8")
        json_path.write_text(
            json.dumps(result["result"], ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError as exc:
        write_note = f"（报表写盘失败: {exc}）"
        md_path = json_path = None

    if json_output:
        _emit(result, "竞赛运行失败", json_output=True)
        return

    kernel = result["result"]
    console.print(
        f"[bold]标量竞赛[/bold]  引擎 {len(kernel['engines'])} 臂 × "
        f"族 {len(kernel['problems'])} × seed {len(kernel['seeds'])}"
        f"  n_eval={kernel['n_eval']}"
        f"（阶段截点 {kernel['stages']['stage1_horizon']}/"
        f"{kernel['stages']['stage2_horizon']}）"
        f"  共 {result['n_runs']} run  耗时 {result['elapsed_s']:.1f}s")
    for stage_key, stage_name in (
            ("ranking_stage1", "阶段一·AUC@半程"),
            ("ranking_stage2", "阶段二·AUC@全程"),
            ("ranking_target", "达标评估次数")):
        rows = kernel[stage_key]
        head = "  ".join(
            f"{i}. {r['engine']}({r['mean_rank']:.2f})"
            for i, r in enumerate(rows, start=1))
        console.print(f"  [cyan]{stage_name}[/cyan]: {head}")
    if md_path is not None:
        console.print(f"[green]✓ 报表已落盘[/green] {md_path}")
        console.print(f"  机读全量: {json_path}")
    else:
        console.print(f"  [yellow]报表未落盘{write_note}[/yellow]"
                      f"（排名与人读明细见上；--json 信封含全量）")
