"""mo 子应用（多目标寻优 MO-BO 面；aurora_n O1 接线席，2026-10-31）。

单叶 run：内置合成族多目标 BO 环（T-N13 Noise-Aware EHVI 贪心内核
MultiObjectiveBO 的运行时门——zero_wiring REGISTRY O1 登记欠账清偿）。
零数值逻辑转发 service/mo_bo_service（规则 4）；目标函数只收内置合成族
（外部真函数不可 JSON 化，回调注册面=service 层 register_problem 仅
Python 编程入口）。带 --json（信封契约；Agent 消费面）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

mo_app = typer.Typer(
    help="多目标寻优（MO-BO）：内置合成族环跑，EHVI 采集 + 超体积裁判，"
         "mt_gp 联合后验驱动")
app.add_typer(mo_app, name="mo")


@mo_app.command("run")
def mo_run_cmd(
    kind: str = typer.Option(
        "zdt1", "--kind",
        help="内置合成问题：zdt1（缩配 ZDT1，恒 2 指标）| dtlz2（DTLZ2，"
             "指标数 --n-obj 可调，大于 2 走 MC 采集路径）"),
    n_eval: int = typer.Option(
        20, "--n-eval", help="总评估预算（初始 LHS+迭代真评估合计，≥2）"),
    n_obj: int = typer.Option(
        None, "--n-obj", help="目标数（仅 dtlz2 消费，≥2；=1 退化标量显式拒绝）"),
    n_params: int = typer.Option(
        None, "--n-params", help="决策变量数（缺省按问题缺省：zdt1=2/dtlz2=3）"),
    surrogate: str = typer.Option(
        "mt_gp", "--surrogate",
        help="代理：mt_gp（跨指标联合后验，缺省）| smt_kriging（逐指标独立）"),
    seed: int = typer.Option(0, "--seed", help="确定性种子（同 seed 逐位复现）"),
    ref_point: str = typer.Option(
        None, "--ref-point",
        help="超体积参考点（逗号分隔浮点，长度=指标数；缺省由初始前沿冻结）"),
    n_init: int = typer.Option(
        None, "--n-init", help="初始 LHS 点数（缺省按预算自动 n//3 截 2..10）"),
    batch_size: int = typer.Option(
        1, "--batch-size", help="每轮采集批量（大于 1 贪心+plug-in fantasy）"),
    n_candidates: int = typer.Option(
        256, "--n-candidates", help="每轮候选池规模（MC 路径大池显著变慢）"),
    mc_samples: int = typer.Option(
        128, "--mc-samples", help="指标数大于 2 时逐候选 MC 样本数"),
    no_fantasy: bool = typer.Option(
        False, "--no-fantasy", help="关闭批内 plug-in fantasy"),
    no_samples: bool = typer.Option(
        False, "--no-samples", help="JSON 信封不携带全评估 samples（大预算减载）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """跑内置合成族多目标 BO 环：HV 曲线 + 帕累托前沿 + 采集轨迹。

    目标函数只收内置合成族（外部真函数不可 JSON 化——Python 编程入口走
    service.mo_bo_service.register_problem 注册后经 kind 消费）。确定性：
    同 seed 同参数两次运行逐位一致。数值全部来自 mo_bo 确定性内核（本叶
    零数值逻辑，薄壳转发）。
    """
    from rfauto.service.mo_bo_service import run_mo_bo

    kwargs: dict = {}
    if n_obj is not None:
        kwargs["n_obj"] = n_obj
    if n_params is not None:
        kwargs["n_params"] = n_params
    if n_init is not None:
        kwargs["n_init"] = n_init
    if ref_point is not None:
        try:
            kwargs["ref_point"] = [
                float(v) for v in str(ref_point).split(",") if v.strip()]
        except ValueError:
            from rfauto.cli.domains._core import _emit_usage_error

            _emit_usage_error(
                f"--ref-point 必须是逗号分隔浮点，实际 {ref_point!r}",
                json_output=json_output)
            return
    if no_fantasy:
        kwargs["fantasy"] = False
    result = run_mo_bo(
        kind, n_eval=n_eval, surrogate_kind=surrogate, seed=seed,
        batch_size=batch_size, n_candidates=n_candidates,
        mc_samples=mc_samples, include_samples=not no_samples, **kwargs)
    if json_output:
        _emit(result, "多目标 BO 环失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 多目标 BO 环失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    hv = result["hv_curve"]
    hv_s = (f"{hv[0]:.4f} → … → {hv[-2]:.4f} → {hv[-1]:.4f}"
            if len(hv) > 4 else " → ".join(f"{v:.4f}" for v in hv))
    console.print(f"[bold]多目标 BO[/bold]  kind={result['kind']}"
                  f"（指标 {result['metrics']}，{result['n_params']} 变量）"
                  f"  代理={result['surrogate_kind']}  seed={result['seed']}")
    console.print(f"  评估: 预算 {result['n_eval_budget']}"
                  f"（n_init={result['n_init']} n_iter={result['n_iter']}"
                  f" batch={result['batch_size']}）→ 实际 {result['n_evaluations']}"
                  f"  耗时 {result['elapsed_s']:.2f}s")
    console.print(f"  参考点: {[round(v, 4) for v in result['ref_point']]}"
                  f"（{result['ref_source']}）")
    console.print(f"  HV 曲线: {hv_s}")
    front = result["front"]
    console.print(f"[green]✓ 帕累托前沿[/green] {len(front)} 点"
                  f"  HV={hv[-1]:.4f}"
                  f"（初始 {hv[0]:.4f}，增益 {hv[-1] - hv[0]:+.4f}）")
    from rich.table import Table

    cols = result["metrics"]
    table = Table(title="前沿目标值（最小化）")
    for c in cols:
        table.add_column(c, justify="right")
    for pt in front[:12]:
        table.add_row(*(f"{v:.4f}" for v in pt))
    if len(front) > 12:
        console.print(f"  （显示前 12 点，共 {len(front)}）", style="dim")
    console.print(table)
    console.print(f"  采集轨迹 {len(result['acquisitions'])} 点"
                  f"（全量见 --json 信封 front_params/acquisitions）")
