"""chain 子应用（lna/loadpull/even-odd/p0）+ study 子应用（inject/sensitivity/tuning-report/audit）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── chain（ME-17b 后半：有源链路 C14 service 接线薄壳）─────────────────────────
# 零逻辑转发 service/active_chain_service（规则 4）：lna=ADS 联合+手工口径
# 双裁判（ads_runner 缺省真机链——真机面，用户显式给 Touchstone 才跑）；
# loadpull=Cripps 等功率圈全离线零仿真。路径参数 str 注解（#269 B008）。

chain_app = typer.Typer(help="有源链路分析（C14：LNA 匹配链 / PA load-pull 口径）")
app.add_typer(chain_app, name="chain")


@chain_app.command("lna")
def chain_lna_cmd(
    match_snp: str = typer.Argument(..., help="匹配网络 Touchstone（2 端口）"),
    device_snp: str = typer.Argument(..., help="器件 S2P（2 端口）"),
    f0_ghz: float = typer.Option(..., "--f0-ghz", help="中心频率（GHz）"),
    noise: str = typer.Option(None, "--noise",
                              help="噪声参数 JSON（fmin_db/gamma_opt_re/"
                                   "gamma_opt_im/rn_norm；可选）"),
    out_dir: str = typer.Option(None, "--out-dir",
                                help="网表/报告落盘目录（缺省不落盘）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """LNA 匹配链端到端：ADS 联合 vs 手工口径+稳定性+噪声（真机面）。"""
    import json as _json

    from rfauto.service.active_chain_service import run_lna_chain

    noise_params = _json.loads(noise) if noise else None
    result = run_lna_chain(match_snp, device_snp, f0_ghz,
                           noise_params=noise_params,
                           out_dir=out_dir if out_dir else None)
    # service 信封是 status 口径——薄壳归一化成 _emit 的 ok 口径
    result = {"ok": result.get("status") == "ok", **result}
    _emit(result, "LNA 链分析失败", json_output=json_output)
    if json_output:
        return
    manual = result.get("manual") or {}
    verdict = result.get("verdict") or {}
    console.print(f"[green]✓ f0={manual.get('f0_hz')}Hz[/green]  "
                  f"S21={manual.get('chain_s21_db')}dB")
    console.print(f"  器件无条件稳定: {verdict.get('device_unconditionally_stable')}"
                  f"  链无条件稳定: {verdict.get('chain_unconditionally_stable')}")
    if result.get("summary_path"):
        console.print(f"  摘要: {result['summary_path']}")


@chain_app.command("loadpull")
def chain_loadpull_cmd(
    vdd_v: float = typer.Option(..., "--vdd-v", help="漏极电压（V）"),
    imax_a: float = typer.Option(..., "--imax-a", help="最大电流（A）"),
    cout_pf: float = typer.Option(..., "--cout-pf", help="输出电容（pF）"),
    f0_ghz: float = typer.Option(..., "--f0-ghz", help="基波频率（GHz）"),
    vknee_v: float = typer.Option(0.3, "--vknee-v", help="膝点电压（V）"),
    n_grid: int = typer.Option(81, "--n-grid", help="ΓL 极坐标网格分辨率"),
    device_snp: str = typer.Option(None, "--device-snp",
                                   help="可选器件 S2P（叠加恒增益面）"),
    out_dir: str = typer.Option(None, "--out-dir", help="摘要落盘目录"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """PA load-pull 口径：Cripps 等功率圈全离线分析（零仿真零 license）。"""
    from rfauto.service.active_chain_service import run_pa_loadpull

    result = run_pa_loadpull(vdd_v, imax_a, cout_pf, f0_ghz,
                             vknee_v=vknee_v, n_grid=n_grid,
                             device_snp=device_snp if device_snp else None,
                             out_dir=out_dir if out_dir else None)
    # service 信封是 status 口径——薄壳归一化成 _emit 的 ok 口径
    result = {"ok": result.get("status") == "ok", **result}
    _emit(result, "load-pull 分析失败", json_output=json_output)
    if json_output:
        return
    opt = result.get("optimum") or {}
    verdict = result.get("verdict") or {}
    console.print(f"[green]✓ n_contours={verdict.get('n_contours')}[/green]  "
                  f"plausible={verdict.get('loadpull_plausible')}")
    console.print(f"  optimum: {opt}")
    if result.get("summary_path"):
        console.print(f"  摘要: {result['summary_path']}")


# ─── even-odd（ME-17b 后半：奇偶模分解 service 接线薄壳）───────────────────────
# 零逻辑转发 service/even_odd_service（规则 4）；report 口径不抛对称性异常
# （ok=false+细节进 JSON），严格口径留给内核单测。路径参数 str 注解（#269）。


@app.command("even-odd")
def even_odd_cmd(
    template: str = typer.Argument(None, help="模板名（cline_coupler|"
                                              "branchline_2sect）"),
    param: list[str] = typer.Option(None, "--param",  # noqa: B008
                                    help="参数覆盖 名=值（可多次）"),
    freq_ghz: float = typer.Option(None, "--freq-ghz",
                                   help="频率（GHz；缺省模板 f0）"),
    list_templates: bool = typer.Option(False, "--list",
                                        help="列出已接入奇偶模分解的模板与元数据"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """奇偶模分解报告（对称性检查+半模型切割+端口改写表+守卫，只读）。"""
    from rfauto.service import even_odd_service

    if list_templates:
        result = {"ok": True, "templates": [
            {"template": t, **even_odd_service.template_even_odd_meta(t)}
            for t in even_odd_service.EVEN_ODD_TEMPLATES]}
        _emit(result, "模板列表失败", json_output=json_output)
        if not json_output:
            for ent in result["templates"]:
                console.print(f"  {ent['template']}: axis={ent['axis']}  "
                              f"plane={ent['plane']}")
        return
    if not template:
        console.print("[red]✗ 需给模板名或 --list[/red]")
        raise typer.Exit(code=1)
    params: dict = {}
    for item in param or []:
        name, _sep, raw = item.partition("=")
        if not _sep:
            console.print(f"[red]✗ --param 需 名=值 形式: {item}[/red]")
            raise typer.Exit(code=1)
        try:
            params[name.strip()] = float(raw)
        except ValueError:
            params[name.strip()] = raw
    result = even_odd_service.even_odd_split_report(
        template, params or None, freq_ghz=freq_ghz)
    _emit(result, "奇偶模分解未通过", json_output=json_output)
    if json_output:
        return
    console.print(f"template={result['template']}  axis={result['axis']}  "
                  f"plane={result['plane']}  ok={result['ok']}")
    if not result["ok"]:
        console.print(f"  [red]{result.get('error')}[/red]")
        raise typer.Exit(code=1)
    for mode, half in (result.get("half_models") or {}).items():
        console.print(f"  {mode}: bc={half.get('bc')}  "
                      f"ports={[p.get('nr') for p in half.get('ports') or []]}")


# ─── p0 (方向 1 前置实验) ───────────────────────────────────────────────────────

@app.command("p0")
def p0_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    seed: int = typer.Option(42, "--seed", help="Optuna seed"),
    coarse: int = typer.Option(40, "--coarse", help="低保真粗筛试验数"),
    fine: int = typer.Option(15, "--fine", help="高保真精算试验数"),
    baseline: int = typer.Option(30, "--baseline", help="纯 fake 基线试验数"),
    edge: int = typer.Option(20, "--edge-samples", help="边缘采样数"),
    high_adapter: str = typer.Option("fake", "--high-adapter",
                                     help="跨保真 gate 的高保真适配器（fake|openems|hfss）。"
                                          "fake=自比较，gate 关闭，verdict=INCONCLUSIVE"),
    cross: int = typer.Option(15, "--cross-samples", help="跨保真对照采样数"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """方向 1 P0 实验：多保真验证（fake 先行）。

    硬门槛（跨保真 gate）：同一组参数在低/高保真下的排序一致性
    Spearman rho >= 0.8 且 top-5 recall >= 80％；不达标则方向 1 回退 fake-only。
    """
    from rfauto.service.api import run_p0_experiment

    if not json_output:
        console.print(f"[cyan]P0 实验: {recipe}[/cyan]")
        console.print(f"  基线: {baseline} trials | 粗筛: {coarse} + 精算: {fine}")
        console.print(f"  跨保真 gate: fake vs {high_adapter}（{cross} 样本）")

    result = run_p0_experiment(
        recipe,
        seed=seed,
        coarse_trials=coarse,
        fine_trials=fine,
        baseline_trials=baseline,
        edge_samples=edge,
        high_adapter=high_adapter,
        cross_samples=cross,
    )
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "P0 实验失败", json_output=True)
        return

    if not result.get("ok"):
        console.print("[red]P0 实验失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    corr = result.get("correlation", {})
    verdict = result.get("verdict", "UNKNOWN")
    verdict_color = {"PASS": "green", "FAIL": "red"}.get(verdict, "yellow")

    console.print(f"\n[bold {verdict_color}]Verdict: {verdict}[/bold {verdict_color}]")
    rho_v = corr.get("spearman_rho")
    rho_str = f"{rho_v:.4f}" if rho_v is not None else "N/A"
    console.print(f"  [self] Spearman rho: {rho_str}")
    cross_r = result.get("cross_fidelity", {})
    # P2⑧：自比较/gate 关闭时 rho/recall 为 None——渲染 N/A 而非裸 "None"
    cross_rho = cross_r.get("spearman_rho")
    cross_recall = cross_r.get("top5_recall")
    console.print(f"  [cross vs {cross_r.get('high_adapter')}] "
                  f"rho={cross_rho if cross_rho is not None else 'N/A'}, "
                  f"recall={cross_recall if cross_recall is not None else 'N/A'}, "
                  f"n={cross_r.get('n_evaluated')}, "
                  f"gate={result.get('gate')}")
    console.print(f"  耗时: {result.get('elapsed_s', 0)}s")
    if verdict == "FAIL":
        console.print("[yellow]方向 1 应回退为 fake-only[/yellow]")
    if verdict == "INCONCLUSIVE":
        console.print("[yellow]自比较不产出跨保真证据——用 --high-adapter openems|hfss 重跑[/yellow]")


# ─── study (方向 6a/4d: 人机参数注入) ──────────────────────────────────────

study_app = typer.Typer(help="人机参数注入研究（方向 6a/4d）")
app.add_typer(study_app, name="study")


@study_app.command("inject")
def study_inject_cmd(
    study: str = typer.Argument(..., help="Optuna study 名称"),
    params: str = typer.Argument(..., help="参数 JSON，如 '{\"arm_len_mm\": 20.5}'"),
    source: str = typer.Option("human", "--source", "-s", help="来源标签: human|llm|tpe"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """向 Optuna study 注入人工参数（ask-and-tell）。

    方向 6a/4d：trial_source 标签写入 user_attrs，审计落盘。
    """
    import json as _json

    from rfauto.service.api import study_inject

    try:
        params_dict = _json.loads(params)
    except _json.JSONDecodeError as e:
        if json_output:
            # VI-5 W6-B：入参非法也信封（--json 下失败路径不许非 JSON）
            _emit({"ok": False, "errors": [f"params 不是合法 JSON: {e}"]},
                  "注入失败", json_output=True)
        console.print(f"[red]params 不是合法 JSON: {e}[/red]")
        raise typer.Exit(code=1) from None

    result = study_inject(study, params_dict, source=source)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "注入失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]注入失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]参数已注入 study '{result['study_name']}'[/green]")
    console.print(f"  trial #{result['trial_number']}")
    console.print(f"  来源: {result['source']}")

# ─── sensitivity (方向 8b: 灵敏度分析) ────────────────────────────────────────────────

@app.command("sensitivity")
def sensitivity_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    method: str = typer.Option("sobol", "--method", "-m", help="方法: sobol | morris"),
    samples: int = typer.Option(100, "--samples", "-n", help="采样数"),
    seed: int = typer.Option(42, "--seed", help="随机种子"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """灵敏度分析：Sobol/Morris 参数重要度排序（方向 8b）。

    输出一阶/总阶灵敏度索引，top 候选进调优报告。
    """
    from rfauto.service.api import run_sensitivity

    if not json_output:
        console.print(f"[cyan]灵敏度分析: {recipe}[/cyan]")
        console.print(f"  方法: {method}, 采样: {samples}, seed: {seed}")

    result = run_sensitivity(recipe, method=method, n_samples=samples, seed=seed, adapter_name=adapter)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "灵敏度分析失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]灵敏度分析失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    sens = result.get("sensitivity", {})
    console.print(f"\n[bold]灵敏度分析结果[/bold] ({result.get('method', '?')}, {result.get('n_samples', '?')} samples)")

    table = Table(title="Parameter Sensitivity")
    table.add_column("参数", style="cyan")
    if result.get("method") == "morris":
        table.add_column("mu*", justify="right")
        table.add_column("sigma", justify="right")
        for name, vals in sorted(sens.items(), key=lambda x: -x[1].get("mu_star", 0)):
            table.add_row(name, f"{vals['mu_star']:.4f}", f"{vals['sigma']:.4f}")
    else:
        table.add_column("S1 (first-order)", justify="right")
        table.add_column("ST (total-order)", justify="right")
        for name, vals in sorted(sens.items(), key=lambda x: -x[1].get("S1", 0)):
            table.add_row(name, f"{vals['S1']:.4f}", f"{vals['ST']:.4f}")
    console.print(table)


# ─── enhanced-report (方向 8c: 调优报告增强) ───────────────────────────────────────

@app.command("tuning-report")
def tuning_report_cmd(
    run_id: str = typer.Argument(..., help="run_id"),
    output: str = typer.Option(None, "--output", "-o", help="输出文件路径"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """生成增强调优报告（方向 8c）：指标摘要 + 诊断 + 可复现信息。"""
    from rfauto.service.api import generate_enhanced_report

    result = generate_enhanced_report(run_id, output=output)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "报告生成失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]报告生成失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    if output:
        console.print(f"[green]报告已生成: {result['report']}[/green]")
    else:
        console.print(result.get("report_text", ""))


# ─── audit (方向 6f: 审计日志查看) ───────────────────────────────────────────────────────

@app.command("audit")
def audit_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="显示条数"),
    event: str = typer.Option(None, "--event", "-e", help="过滤事件类型: propose|apply|study_inject"),
    quality: bool = typer.Option(False, "--quality", "-q", help="输出 4b 提议质量指标（接受率/改进率/否决原因）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """查看 Agent 审计日志（audit.jsonl）。

    方向 6f 验收口径：UI 里浏览 audit.jsonl（propose/apply 全链、token 哈希、来源标签）。
    """
    audit_path = Path("runs") / "agent_proposals" / "audit.jsonl"
    if quality:
        from rfauto.service.api import agent_quality_summary
        summary = agent_quality_summary()
        if json_output:
            # VI-5 W6-B：--json 信封（质量指标键集原样透传）
            console.print_json(json.dumps(
                {"ok": True, **summary}, ensure_ascii=False, default=str))
            return
        console.print("[cyan]4b 提议质量指标[/cyan]")
        console.print(f"  总 propose 数: {summary['total_proposes']}")
        console.print(f"  接受（apply/approve 成功）: {summary['accepted']}  "
                      f"接受率: {summary['accept_rate'] if summary['accept_rate'] is not None else 'N/A'}")
        console.print(f"  平均改进率: {summary['avg_improvement'] if summary['avg_improvement'] is not None else 'N/A'}"
                      f"（样本 {summary.get('n_improvement_samples', 0)}，仅 fake 档）")
        if summary["rejections"]:
            console.print("  否决原因分类:")
            for stage, n in sorted(summary["rejections"].items()):
                console.print(f"    {stage}: {n}")
        else:
            console.print("  否决: 无")
        return

    if not audit_path.exists():
        if json_output:
            # VI-5 W6-B：空日志是合法零记录态（ok=True entries=[] 如实）
            console.print_json(json.dumps(
                {"ok": True, "entries": [], "total": 0}, ensure_ascii=False))
            return
        console.print("[yellow]审计日志不存在（尚无 Agent 操作记录）[/yellow]")
        return

    entries = []
    for line in audit_path.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if event and entry.get("event") != event:
                continue
            entries.append(entry)
        except json.JSONDecodeError:
            continue

    if not entries:
        if json_output:
            console.print_json(json.dumps(
                {"ok": True, "entries": [], "total": 0}, ensure_ascii=False))
            return
        console.print("[yellow]无匹配的审计记录[/yellow]")
        return

    if json_output:
        # VI-5 W6-B：--json 信封（最近优先口径与表格一致）
        recent = entries[-limit:]
        recent.reverse()
        console.print_json(json.dumps(
            {"ok": True, "total": len(recent), "entries": recent},
            ensure_ascii=False, default=str))
        return

    # Show most recent first
    entries = entries[-limit:]
    entries.reverse()

    table = Table(title=f"审计日志 (最近 {len(entries)} 条)")
    table.add_column("时间", style="dim")
    table.add_column("事件", style="cyan")
    table.add_column("状态")
    table.add_column("详情")

    for e in entries:
        ts = e.get("timestamp", "?")
        evt = e.get("event", "?")
        ok = e.get("ok", False)
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        detail_parts = []
        if e.get("recipe"):
            detail_parts.append(f"recipe={Path(e['recipe']).name}")
        if e.get("token_hash"):
            detail_parts.append(f"token={e['token_hash'][:8]}...")
        if e.get("source"):
            detail_parts.append(f"source={e['source']}")
        if e.get("run_id"):
            detail_parts.append(f"run={e['run_id']}")
        if e.get("reason"):
            detail_parts.append(f"reason={e['reason'][:40]}")
        detail = " | ".join(detail_parts) if detail_parts else "-"
        table.add_row(str(ts)[:19], evt, status, detail)

    console.print(table)
