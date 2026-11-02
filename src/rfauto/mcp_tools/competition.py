"""competition_run —— 单目标优化器族竞赛面（aurora_n MCP 接线补齐席，2026-10-31）。

zero_wiring 登记欠账清偿：T-N5 标量竞赛架（competition_scalar）运行时
门（O5 席此前仅落 CLI 持久门 ``rfauto competition run``）。同预算同
seed 组竞赛：最优值 AUC 两阶段（半程/全程共享轨迹）+ 达标评估次数
三套排名。零逻辑转发 service/competition_service（规则 4：JSON 信封
进出；铁律 7：数值全部来自 competition_scalar 确定性内核，本层零新
数值）。

耗时口径（如实标注）：全矩阵（7 内置引擎×4 内置族×3 seed×n_eval=60
=84 run）分钟级；MCP 同步面建议小档起步（单族+单 seed+n_eval≤20，
秒级）再按需扩。持久落盘面（report.md+report.json 写盘）留 CLI 叶
（--out）——本工具零写盘（runs/ 湖 cwd 相对写污染防线，#144 家族），
全量 result 与 report_md 随信封返回。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def competition_run(
    engines: str = "",
    problems: str = "",
    n_eval: int = 60,
    seeds: str = "0,1,2",
) -> dict[str, Any]:
    """跑单目标优化器族竞赛（同预算同 seed 组，三套排名信封返回）。

    judge 只消费评估序目标值轨迹记分（#118：裁判/被测非共享代码路径）；
    同 seed 同参数重跑，报表剥离 elapsed_s 后逐位一致（确定性内核）。
    内置族：concave2d（凹）/ rastrigin2d（多谷）/ rosenbrock2d（窄谷）/
    noisysphere4d（噪声）；内置引擎：tpe/gp/cmaes/turbo/turbo_multi/eipu/sbo
    （botorch_ei 显式点名走 opt-in 注册，未装 rfauto【botorch】extra
    报安装指引）。报表 md/json 落盘走 CLI ``rfauto competition run
    --out``（本工具零写盘）。

    Args:
        engines: 参赛引擎逗号分隔名单（空串=全部已注册；未知名显式
            拒绝并列可用面）
        problems: 问题族逗号分隔名单（空串=内置 4 族全跑；未知名显式
            拒绝）
        n_eval: 每引擎×族×seed 评估预算（>0；两阶段截点=半程与全程，
            共享轨迹不重跑。缺省 60——全矩阵分钟级，同步面建议小档
            n_eval≤20 先行）
        seeds: 确定性种子逗号分隔整数名单（缺省 "0,1,2"；同 seed 组
            重跑剥离耗时逐位一致）

    Returns:
        dict: ok=True {ok, schema, engines, problems, n_eval, seeds,
        n_runs, result（内核报表全量 dict，schema
        competition-scalar-v1，含 runs 与三套 ranking）, report_md,
        elapsed_s}；失败 {ok: False, errors: [...]}（入参校验/未知
        引擎/未知族/常数目标 #195/band 退化均信封化）
    """
    from rfauto.service.competition_service import run_competition
    from rfauto.service.envelope import error_envelope

    def _csv(raw: str) -> list[str] | None:
        items = [v.strip() for v in str(raw).split(",")]
        items = [v for v in items if v]
        return items or None

    engine_list = _csv(engines)
    problem_list = _csv(problems)
    seed_raw = _csv(seeds) or []
    try:
        seed_list = [int(v) for v in seed_raw]
    except (TypeError, ValueError):
        return error_envelope(
            f"seeds 必须是逗号分隔整数，实际 {seeds!r}")
    return run_competition(
        engine_list, problem_list, n_eval=n_eval, seeds=seed_list)
