"""pool-patrol 单叶——Z-11 池登记项新鲜度巡检薄壳（2026-10-08）。

零逻辑转发 service/pool_patrol_service.pool_patrol（规则 4 薄壳；双判据+
撞号消歧+五栏分级全在确定性 service 内核，铁律 7）：
  rfauto pool-patrol                 # 全池巡检（缺省 Rich 人类表）
  rfauto pool-patrol --json          # JSON 信封（Agent 消费面）
  rfauto pool-patrol --ids Z-16,SB22-MS-3
  rfauto pool-patrol --since 2026-10-04 --json
  rfauto pool-patrol --gold          # 金标校准（重审计账本口径），不一致退出 1

信封：ok_envelope（counts/items/假阳假阴双清单/可选 calibration）；
池文档不可读等输入错 → error_envelope 退出码 2。
"""

from __future__ import annotations

import json

import typer

from rfauto.cli.domains._core import app as app


@app.command("pool-patrol")
def pool_patrol_cmd(
    pool_doc: str = typer.Option(
        "docs/plan_expansion_pool_20260924.md", "--pool-doc",
        help="池登记文档路径（相对仓库根）"),
    since: str = typer.Option("", "--since", help="git log --since 新鲜度窗（缺省全史）"),
    ids: str = typer.Option("", "--ids", help="逗号分隔 ID 子集（SB22-MS-1 形态可）"),
    gold: bool | None = typer.Option(None, "--gold/--no-gold",
                                     help="金标校准（重审计账本口径）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（缺省人类可读表）"),
) -> None:
    """池登记项新鲜度巡检（Z-11）：commit-tag×代码面双判据+撞号二次消歧。"""
    from rfauto.cli.domains._core import console
    from rfauto.service.pool_patrol_service import pool_patrol

    config: dict = {"pool_doc": pool_doc}
    if since:
        config["since"] = since
    if ids.strip():
        config["ids"] = [x.strip() for x in ids.split(",") if x.strip()]
    if gold is not None:
        config["gold"] = gold

    result = pool_patrol(config)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
    else:
        counts = result.get("counts", {})
        console.print(
            f"[bold]池新鲜度巡检[/bold] 总 {result.get('total_items', 0)} 项："
            f"闭合 {counts.get('closed', 0)} / 开放 {counts.get('open', 0)} / "
            f"部分 {counts.get('partial', 0)} / 漂移 {counts.get('stale', 0)} / "
            f"不明 {counts.get('ambiguous', 0)} / 并档 {counts.get('merged_alias', 0)}"
        )
        from rich.table import Table

        table = Table(title="pool patrol（Z-11）")
        table.add_column("ID")
        table.add_column("状态")
        table.add_column("判据")
        table.add_column("登记行")
        for it in result.get("items", []):
            table.add_row(it["id"], str(it["status"]), str(it["reason"])[:40],
                          f"R{it['round']}:{it['line_no']}")
        console.print(table)
        cal = result.get("calibration")
        if cal is not None:
            console.print(
                f"金标校准：{cal['agree']}/{cal['rated']} 一致"
                f"（rate={cal['rate']}）门={result.get('calibration_gate')}"
            )
    if not result.get("ok", False):
        raise typer.Exit(code=2)
    if result.get("calibration_gate") == "FAIL":
        raise typer.Exit(code=1)
