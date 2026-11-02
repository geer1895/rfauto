"""al 子应用（主动学习采样提议面；aurora_n O4 接线席，2026-10-31）。

单叶 propose：service/active_learning 的 T-N9 宿主 propose_next_points
运行时门——zero_wiring REGISTRY O4 欠账清偿（此前宿主零运行时调用方，
仅测试+一次性探针脚本消费）。数据工厂闭环的"下一批测什么"回答者：
小样本标注预算下，读湖样本（samples.json / 物化数据集 / run trials）
提议下一批真机实验点。缺省=σ 求和旧路径（宿主逐字节转发）；
--acquisition 展开 T-N9 采集三族（lcb/ucb/ei/sigma，公式单源
acquisition_scores）+ registry σ 源 + conformal_fallback。
零数值逻辑转发 service/al_service（规则 4）；带 --json（信封契约）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

al_app = typer.Typer(
    help="主动学习（AL）：小样本标注预算下提议下一批实验点"
         "（σ×距离双重准则或 T-N9 采集三族）")
app.add_typer(al_app, name="al")


@al_app.command("propose")
def al_propose_cmd(
    samples: str = typer.Option(
        None, "--samples",
        help="samples.json 路径（bounds/samples schema，与 certify 公差盒"
             "同款；与 --dataset/--run 互斥，恰给一）"),
    dataset: str = typer.Option(
        None, "--dataset",
        help="物化数据集名（runs/datasets/，走 query_dataset 链读 "
             "params/metrics；bounds 由观测参数范围推导）"),
    run: str = typer.Option(
        None, "--run",
        help="run id（读 runs/<id>/trials/trial_*.json 的 params/metrics；"
             "bounds 由观测参数范围推导）"),
    k: int = typer.Option(5, "--k", help="提议点数（下一批预算 N，≥0）"),
    kind: str = typer.Option(
        "nn", "--kind",
        help="代理注册键（legacy σ 路径需支持 uncertainty 或开 "
             "--conformal-fallback；registry 来源=注册键）"),
    acquisition: str = typer.Option(
        None, "--acquisition",
        help="采集函数族（T-N9）：lcb|ucb|ei|sigma；缺省=σ 求和旧路径"
             "（propose_next_points 逐字节转发）"),
    source: str = typer.Option(
        "gp", "--source",
        help="不确定度来源（采集路径）：gp|bootstrap|nn|registry"
             "（registry 需 --kind=注册键）"),
    beta: float = typer.Option(
        2.0, "--beta", help="置信界系数（lcb/ucb 消费）"),
    xi: float = typer.Option(0.0, "--xi", help="EI 探索参数（ei 消费）"),
    n_candidates: int = typer.Option(
        500, "--n-candidates", help="LHS 候选池规模"),
    min_dist: float = typer.Option(
        0.12, "--min-dist",
        help="与既有样本的最小归一化距离（距离过滤阈值）"),
    seed: int = typer.Option(42, "--seed", help="确定性种子（同 seed 逐位复现）"),
    conformal_fallback: bool = typer.Option(
        None, "--conformal-fallback/--no-conformal-fallback",
        help="原生 σ 缺席时代理走 T-N1 共形区间包装（缺省=按路径："
             "legacy False / 采集 True，同各自内核缺省）"),
    max_rows: int = typer.Option(
        5000, "--max-rows", help="数据集装载行数上限（超出如实标注 truncated）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """提议下一批实验点：读湖样本 → 不确定度×距离（或采集族）→ top-k。

    示例：rfauto al propose --dataset datafactory_m1_mline_20260919 --k 8
    示例：rfauto al propose --samples runs/x/samples.json --acquisition ei
    确定性：同 seed 同输入两次运行逐位一致；数值全部来自确定性内核
    （active_learning，#7），本叶零数值逻辑（薄壳转发 service/al_service）。
    """
    from rfauto.service.al_service import al_propose

    result = al_propose(
        samples, dataset, run, k=k, kind=kind, acquisition=acquisition,
        source=source, beta=beta, xi=xi, n_candidates=n_candidates,
        min_dist=min_dist, seed=seed,
        conformal_fallback=conformal_fallback, max_rows=max_rows)
    if json_output:
        _emit(result, "AL 提议失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ AL 提议失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    proposed = result.get("proposed") or []
    label = result.get("source_label") or result.get("samples_path") or ""
    if result.get("mode") == "acquisition":
        console.print(
            f"[bold]AL 提议[/bold]（采集族 {result['acquisition']}，来源 "
            f"{result['uncertainty_source']}"
            f"{'/'+result['sigma_source'] if result.get('sigma_source') else ''}）"
            f"  样本 {result['n_existing']} 点  候选池 {result['n_candidates']}"
            f"  seed={result['seed']}")
    else:
        console.print(
            f"[bold]AL 提议[/bold]（σ 求和路径，代理 {result.get('surrogate_kind')}）"
            f"  样本 {result.get('n_existing')} 点  "
            f"候选池 {result.get('n_candidates')}")
    console.print(f"  样本来源: {label}")
    for i, item in enumerate(proposed, 1):
        score = item.get("uncertainty_score", item.get("score"))
        console.print(
            f"  #{i}  score={score:.6g}  params={item['params']}")
    console.print(
        f"[green]✓ 提议 {len(proposed)} 点[/green]（全量含 mean/sigma 见 "
        "--json；提议点需真机复验后方可并入样本集）")
