"""db 子应用（注册表数据库六命令）+ explain-run（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console
from rfauto.cli.domains.calc_vna import _coerce_param as _coerce_param

# ─── db（W1⑫ 注册表数据库薄壳：SQLite 事务型注册表 + DuckDB 分析直读） ────────
# 六命令零逻辑转发 service/db_service（规则 4）；路径参数一律 str 注解（#269
# B008）；query 走只读 SELECT 白名单（拒绝进信封，不抛出）。

db_app = typer.Typer(help="注册表数据库（SQLite 事务型注册表 + DuckDB 分析直读；零服务器）")
app.add_typer(db_app, name="db")

_DB_PATH_HELP = "注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）"


@db_app.command("init")
def db_init_cmd(
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """建库 + 幂等迁移（首次 applied=1，重放 applied=0）。"""
    from rfauto.service.db_service import db_init

    result = db_init(db_path)
    _emit(result, "注册表建库失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ 注册表就绪[/green] {result['path']}  "
                  f"schema_version={result['schema_version']}  applied={result['applied']}")


@db_app.command("migrate")
def db_migrate_cmd(
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="计划面（SN-18）：当前/目标 schema 版本与预计步数，零写入"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """执行幂等迁移（schema_version 表递增；重复执行零变更）。"""
    from rfauto.service.db_service import db_migrate

    result = db_migrate(db_path, dry_run=dry_run)
    _emit(result, "注册表迁移失败", json_output=json_output)
    if json_output:
        return
    if dry_run:
        console.print(f"[cyan]迁移计划（dry-run，零写入）[/cyan] {result['path']}")
        console.print(f"  schema_version={result['schema_version']} → "
                      f"{result['target_schema_version']}"
                      f"  would_apply={result['would_apply']}")
        return
    console.print(f"[green]✓ 迁移完成[/green] {result['path']}  "
                  f"schema_version={result['schema_version']}  applied={result['applied']}")


@db_app.command("status")
def db_status_cmd(
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """注册表状态：路径/存在性/schema 版本/各表行数（文件不存在不创建）。"""
    from rfauto.service.db_service import db_status

    result = db_status(db_path)
    _emit(result, "注册表状态读取失败", json_output=json_output)
    if json_output:
        return
    exists = "存在" if result.get("exists") else "不存在（rfauto db init 建库）"
    console.print(f"{result['path']}  [{exists}]  schema_version={result['schema_version']}")
    for table, count in (result.get("tables") or {}).items():
        console.print(f"  {table}: {count}")


@db_app.command("reindex-runs")
def db_reindex_runs_cmd(
    runs_dir: str = typer.Option("runs", "--runs-dir", help="runs 目录（扫 */meta.json）"),
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """扫 runs/*/meta.json 重建 runs 表（upsert 幂等；单文件失败不阻塞 #105）。"""
    from rfauto.service.db_service import reindex_runs

    result = reindex_runs(runs_dir, db_path=db_path)
    _emit(result, "runs 重建索引失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ reindexed={result['reindexed']}[/green]  "
                  f"failed={result['failed']}  db={result['db_path']}")
    if result.get("note"):
        console.print(f"  [dim]{result['note']}[/dim]")
    for err in result.get("errors") or []:
        console.print(f"  [yellow]- {err}[/yellow]")


@db_app.command("query")
def db_query_cmd(
    sql: str = typer.Argument(..., help="单条只读 SELECT（? 占位符）"),
    param: list[str] | None = typer.Option(None, "--param", "-p",  # noqa: B008
                                           help="占位符参数（可重复；JSON 标量或字符串）"),
    limit: int = typer.Option(200, "--limit", help="返回行数上限（最大 5000）"),
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """只读查询注册表（SELECT 白名单 + 参数绑定；拒绝原因进信封）。

    示例：rfauto db query "SELECT run_id, model FROM runs WHERE adapter = ?" -p hfss
    """
    from rfauto.service.db_service import db_query_safe

    params = [_coerce_param(p) for p in (param or [])]
    result = db_query_safe(sql, params, limit=limit, db_path=db_path)
    _emit(result, "注册表查询失败", json_output=json_output)
    if json_output:
        return
    columns = result.get("columns") or []
    console.print("  ".join(str(c) for c in columns))
    for row in result.get("rows") or []:
        console.print("  ".join(str(v) for v in row))
    console.print(f"[dim]{result['row_count']} 行"
                  f"{'（已截断）' if result.get('truncated') else ''}[/dim]")


@db_app.command("analytics-attach")
def db_analytics_attach_cmd(
    db_path: str | None = typer.Option(None, "--db", help=_DB_PATH_HELP),
    sample_limit: int = typer.Option(3, "--sample-limit", help="示例查询最近 runs 条数"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """DuckDB sqlite 扩展直读注册表（零拷贝分析面；不可用如实 ok=False）。"""
    from rfauto.service.db_service import analytics_attach

    result = analytics_attach(db_path, sample_limit=sample_limit)
    if not result.get("ok"):
        console.print(f"[red]✗ DuckDB 直读不可用: {result.get('reason')}[/red]")
        if json_output:
            console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        raise typer.Exit(code=1)
    _emit(result, "DuckDB 直读失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ duckdb {result['duckdb_version']}[/green] "
                  f"attached {result['path']} as {result['attached_as']}")
    for table, count in (result.get("tables") or {}).items():
        console.print(f"  {table}: {count}")
    for run in result.get("sample_runs") or []:
        console.print(f"  run {run.get('run_id')}  {run.get('model')}  "
                      f"{run.get('adapter')}  {run.get('status')}")

@db_app.command("league-rebuild")
def db_league_rebuild_cmd(
    runs_dir: str | None = typer.Option(None, "--runs-dir", help="runs 根目录（缺省仓内 runs）"),
    db_path: str | None = typer.Option(None, "--db", help="league.duckdb 路径（缺省 runs/league.duckdb）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """引擎联赛表重建（DP-17 W1：verdict 形态白名单抽取，幂等）。"""
    from rfauto.service.league_service import rebuild_league

    _emit(rebuild_league(runs_dir=runs_dir, db_path=db_path),
          "联赛表重建失败", json_output=json_output)


@db_app.command("league-report")
def db_league_report_cmd(
    family: str | None = typer.Option(None, "--family", help="模板族过滤"),
    quantity: str | None = typer.Option(None, "--quantity", help="量（带单位后缀）过滤"),
    db_path: str | None = typer.Option(None, "--db", help="league.duckdb 路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """联赛报告：按（族，量）出 |delta| 中位×wall_s 中位 Pareto 前沿（JSON+md 双出）。"""
    from rfauto.service.league_service import league_report

    _emit(league_report(template_family=family, quantity=quantity, db_path=db_path),
          "联赛报告失败", json_output=json_output)


@app.command("explain-run")
def explain_run_cmd(
    run_dir: str = typer.Argument(..., help="run 目录（runs/<id>）"),
    playbook: str | None = typer.Option(None, "--playbook", help="playbook.yaml 路径（缺省 knowledge/diagnostics/playbook.yaml）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """失败指纹解释（DP-17 W2：确定性指纹匹配→候选根因族+取证命令+坑号链，无 LLM）。"""
    from rfauto.service.explain_run import explain_run

    _emit(explain_run(run_dir, playbook=playbook),
          "run 解释失败", json_output=json_output)
