"""design-report 顶层连字叶（设计回放与总结报告出口；aurora_o T-O5，2026-11-01）。

单叶 design-report：run → ``rfauto-design-report/v1`` 模型 → md 单文件
（缺省落 ``runs/<run_id>/design_report.md``）——"设计回放和总结：设计完
之后出具一个简单的设计报告"（用户需求原文，PLAN_DRAFT §〇 第 5 条）。
优化族 run（tune/refine 族，无 results/metrics.json）此前无任何报告出口
（既有 ``rfauto report`` 硬依赖 results/metrics.json），本叶补主缺口；
单评族用户仍走 ``rfauto report``（增量面，不替换）。

顶层名撞名自查（2026-11-01）：``design`` 顶层名已被 level2 design 链占用
（cli/domains/design.py：design kickoff/close），故取连字叶形态
``design-report``（同 ``export-report-pdf`` 先例）；全 CLI 树无
design-report/design_report 前缀命令或组。freshness gate 同款 K4 语义：
stale 拒出（stage="freshness_gate"）；legacy 放行带注记。零数值逻辑
转发 service/design_replay_report（规则 4）；带 --json（信封契约，
成功+失败同构）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console


@app.command("design-report")
def design_report_cmd(
    run_id: str = typer.Argument(
        ..., help="run_id（runs/ 下目录名）或 run 目录路径"),
    base_run_id: str = typer.Argument(
        "", help="对比 run_id 或 run 目录路径（可选；给定时报告追加 ⑤c 版本"
                 "对账节：从该 run 到本 run 的最终设计参数/指标差异表）"),
    out: str = typer.Option(
        "", "--out", help="输出 md 路径（缺省 runs/<run_id>/design_report.md）"),
    no_diagrams: bool = typer.Option(
        False, "--no-diagrams",
        help="禁用 §④ 图产物落盘（缺省在链路级数据在场时生成 diagrams/ 附件）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """生成设计回放与总结报告（六节+扩展节 md 单文件，全数字带 provenance）。

    六节=设计目标摘要/优化轨迹回放/最终设计与 verdict 门表/电路图总结/
    敏感性摘要/复现命令附录；扩展节=⑤b Pareto 前沿（多目标 run，单目标
    如实 N/A）与 ⑤c 版本对账（给定位置参数 BASE_RUN_ID 时追加：从对比
    run 到本 run 的最终设计参数/指标差异表，design_diff_service 单源）；
    对比 run 缺失/不可解析时 ⑤c 节如实降级注记（不报错不凑节）；零 LLM
    零网络（确定性模板，同输入逐字节同输出）。

    示例：rfauto design-report 20260830_213813_1510dee6 --json
    示例：rfauto design-report <run_id> <base_run_id> --json（版本对账）

    门表判定=单目标拆分调 core/objectives（cost 语义单源）；缺键目标
    UNKNOWN 不凑 PASS；stale run 拒出（freshness gate）。
    """
    from rfauto.service.design_replay_report import generate_design_report

    result = generate_design_report(
        run_id, output=out or None, with_diagrams=not no_diagrams,
        diff_run_id=base_run_id or None)
    if not result.get("ok"):
        _emit(result, "设计报告生成失败", json_output=json_output)
        return
    if json_output:
        _emit(result, "设计报告生成失败", json_output=True)
        return
    fresh = result.get("freshness") or {}
    console.print(
        f"[bold]设计回放报告[/bold]  run={result.get('run_id')}  "
        f"design_verdict={result.get('design_verdict')}  "
        f"门 PASS {result.get('n_gates_pass', 0)}/"
        f"FAIL {result.get('n_gates_fail', 0)}  "
        f"freshness={fresh.get('status')}")
    diagrams = result.get("diagrams") or {}
    if diagrams.get("status") == "ok":
        for att in diagrams.get("attachments") or []:
            console.print(f"  附件: {att.get('path')}")
    console.print(f"[green]✓ 已写出[/green] {result.get('report')}")
