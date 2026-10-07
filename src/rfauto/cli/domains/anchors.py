"""anchors 子应用（物理标定锚注册表：list/inspect/validate/stale/drift）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json

import typer
from rich.table import Table

from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── anchors (DP-3 物理标定锚注册表) ────────────────────────────────────────

anchors_app = typer.Typer(help="物理标定锚注册表（DP-3，JSON 进出薄壳）")
app.add_typer(anchors_app, name="anchors")


def _anchors_emit(result: dict, json_output: bool, render) -> None:
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error') or '未知错误'}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False))
        raise typer.Exit(code=0)
    render(result)


@anchors_app.command("list")
def anchors_list_cmd(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """列出全部已登记锚（DP-3 注册表 knowledge/anchors.yaml）。

    示例：rfauto anchors list
    """
    from rfauto.service.anchors_service import list_anchors

    _anchors_emit(list_anchors(), json_output, _render_anchors_list)


def _render_anchors_list(r: dict) -> None:
    table = Table(title=f"锚注册表（DP-3，{r['count']} 条）")
    table.add_column("anchor_id")
    table.add_column("kind")
    table.add_column("status")
    table.add_column("v", justify="right")
    table.add_column("value / expr / points")
    for row in r["anchors"]:
        summary = row.get("value")
        if row.get("expr"):
            summary = row["expr"]
        elif row.get("kind") == "curve":
            summary = f"points={len(row.get('points') or [])}"
        table.add_row(row["anchor_id"], str(row.get("kind")),
                      str(row.get("status")), str(row.get("version")),
                      str(summary))
    console.print(table)
    for e in r.get("load_errors") or []:
        console.print(f"[yellow]! load_error[/yellow] {e}")


@anchors_app.command("inspect")
def anchors_inspect_cmd(
    anchor_id: str = typer.Argument(..., help="锚 id（如 c3.l_via_h.openems-hfss-v1）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """单锚全量记录（含 provenance/uncertainty/domain/consumers）。"""
    from rfauto.service.anchors_service import inspect_anchor

    _anchors_emit(inspect_anchor(anchor_id), json_output,
                  _render_anchors_inspect)


def _render_anchors_inspect(r: dict) -> None:
    a = r["anchor"]
    console.print(f"[bold]{a['anchor_id']}[/bold]（v{a.get('version')}，"
                  f"{a.get('kind')}，{a.get('status')}）")
    q = a.get("quantity") or {}
    console.print(f"  量: {q.get('name')} [{q.get('unit')}]"
                  f"——{q.get('semantics')}")
    if a.get("value") is not None:
        console.print(f"  value: {a['value']}")
    if a.get("expr"):
        console.print(f"  expr: {a['expr']}  variables: {a.get('variables')}")
    if a.get("points") is not None:
        console.print(f"  points: {len(a['points'])}  interp: {a.get('interp')}")
    console.print(f"  uncertainty: {a.get('uncertainty')}")
    console.print(f"  domain: {a.get('domain')}")
    console.print(f"  engine_pair: {a.get('engine_pair')}"
                  f"  fallback: {a.get('fallback')}")
    prov = a.get("provenance") or {}
    console.print(f"  provenance: runs={prov.get('arbitration_runs')}"
                  f" commit={prov.get('commit')}")
    console.print(f"  consumers: {a.get('consumers')}")


@anchors_app.command("validate")
def anchors_validate_cmd(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """校验注册表：schema + provenance 可解析 + 单源计数核对（DP-3 判据 3）。"""
    from rfauto.service.anchors_service import validate_registry

    report = validate_registry()
    if not report.get("ok"):
        if json_output:
            console.print_json(json.dumps(report, ensure_ascii=False))
        else:
            for iss in report.get("issues") or []:
                console.print(f"[red]✗ {iss}[/red]")
        raise typer.Exit(code=1)
    _anchors_emit(report, json_output, _render_anchors_validate)


def _render_anchors_validate(r: dict) -> None:
    console.print(f"[bold]锚注册表校验（DP-3）[/bold]：{r['count']} 条"
                  f"（单源期望 {r['expected_count']}，匹配="
                  f"{r['expected_match']}），registry={r.get('registry_path')}")
    console.print("[green]✓ schema + provenance 全过[/green]")


@anchors_app.command("stale")
def anchors_stale_cmd(
    threshold: float = typer.Option(
        30.0, "--threshold",
        help="stale 阈值（天；last_verified 距今严格大于该值判 stale）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """锚新鲜度报告（QW-3）：last_verified 龄期 + stale 判定。

    无 last_verified 字段的锚如实标注 no_date 不算 stale（不虚构日期）。
    示例：rfauto anchors stale --threshold 60
    """
    from rfauto.service.anchors_service import anchors_stale_report

    _anchors_emit(anchors_stale_report(threshold), json_output,
                  _render_anchors_stale)


def _render_anchors_stale(r: dict) -> None:
    table = Table(title=f"锚新鲜度（QW-3，阈值 {r['threshold_days']} 天，"
                        f"stale {r['stale_count']}/no_date "
                        f"{r['no_date_count']}/{r['count']} 条）")
    table.add_column("anchor_id")
    table.add_column("status")
    table.add_column("last_verified")
    table.add_column("age_days", justify="right")
    table.add_column("residual", justify="right")
    table.add_column("stale")
    for row in r["anchors"]:
        age = ("-" if row.get("age_days") is None
               else f"{row['age_days']:.2f}")
        residual = ("-" if row.get("residual") is None
                    else str(row["residual"]))
        stale = ("no_date" if row.get("stale") is None
                 else ("stale" if row["stale"] else "fresh"))
        style = ("red" if row.get("stale") else
                 ("yellow" if row["stale"] is None else "green"))
        table.add_row(row["anchor_id"], str(row["status"]),
                      str(row.get("last_verified_at")), age, residual,
                      f"[{style}]{stale}[/{style}]")
    console.print(table)
    for e in r.get("load_errors") or []:
        console.print(f"[yellow]! load_error[/yellow] {e}")


@anchors_app.command("drift")
def anchors_drift_cmd(
    anchor_id: str = typer.Argument(..., help="锚 ID（如 cps.gamma_er.fdref-v1）"),
    history_file: str = typer.Option(
        None, "--history-file",
        help="残差历史 JSON 路径（序列/快照形态；缺省走快照库+注册表回退链）"),
    alpha: float = typer.Option(
        0.05, "--alpha", help="Mann-Kendall 显著性水平（缺省 0.05）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """锚漂移预警（QW-16）：Mann-Kendall 趋势 + 分布指纹差分。

    无序列数据时如实 empty_series（快照机制数据积累期，见
    anchors_service.record_anchor_drift_snapshot）。
    示例：rfauto anchors drift cps.gamma_er.fdref-v1
    """
    from rfauto.service.anchors_service import anchor_drift_status

    history = None
    if history_file is not None:
        try:
            with open(history_file, encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError) as exc:
            _anchors_emit({"ok": False,
                           "error": f"history_file 不可读/非 JSON: {exc}"},
                          json_output, _render_anchors_drift)
            return
        if isinstance(raw, dict) and "snapshots" in raw:
            history = raw["snapshots"]
        elif isinstance(raw, dict) and "values" in raw:
            history = raw["values"]
        elif isinstance(raw, list):
            history = raw
        else:
            _anchors_emit({"ok": False,
                           "error": "history_file 须为序列/快照数组或 "
                                    "{snapshots|values: [...]} 映射"},
                          json_output, _render_anchors_drift)
            return
    _anchors_emit(anchor_drift_status(anchor_id, history, alpha=alpha),
                  json_output, _render_anchors_drift)


def _render_anchors_drift(r: dict) -> None:
    if not r.get("ok"):
        console.print(f"[red]✗ {r.get('error')}[/red]")
        return
    rep = r["report"]
    console.print(f"锚漂移预警（QW-16）: {r['anchor_id']}  "
                  f"status={r['status']}")
    verdict = rep["verdict"]
    style = {"drifted": "red", "warning": "yellow", "stable": "green"}.get(
        verdict, "cyan")
    console.print(f"verdict=[{style}]{verdict}[/{style}]  "
                  f"mode={rep['mode']}  n_points={rep['n_points']}  "
                  f"source={r['history_source']}"
                  + (f"  n_snapshots={rep['n_snapshots']}"
                     if rep.get("n_snapshots") is not None else ""))
    trend = rep.get("trend")
    if trend:
        console.print(f"MK: trend={trend['trend']}  S={trend['S']}  "
                      f"z={trend['z']:.4g}  p={trend['p']:.4g}  "
                      f"alpha={trend['alpha']}")
    shift = rep.get("fingerprint_shift")
    if shift:
        console.print(f"指纹差分: mean_shift_rel={shift['mean_shift_rel']:.4g}"
                      f"  std_ratio={shift['std_ratio']:.4g}")
    for reason in rep.get("reasons") or []:
        console.print(f"  - {reason}")
