"""diagnose 子应用（耦合矩阵诊断三件套）+ correlate（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── diagnose (DP-2 耦合矩阵诊断三件套，薄壳转发 diagnosis_service) ───────────

diagnose_app = typer.Typer(help="耦合矩阵/Q 诊断三件套（DP-2，JSON 进出薄壳）")
app.add_typer(diagnose_app, name="diagnose")


def _load_json_value(path: str, what: str):
    """读 JSON 文件（矩阵/参数表），失败显式退出。"""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        console.print(f"[red]✗ {what} 文件不存在: {path}[/red]")
        raise typer.Exit(code=1) from None
    except (json.JSONDecodeError, OSError) as e:
        console.print(f"[red]✗ {what} 文件读取失败: {e}[/red]")
        raise typer.Exit(code=1) from None


def _diagnose_emit(result: dict, json_output: bool, render) -> None:
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error') or '未知错误'}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result["result"], ensure_ascii=False))
        raise typer.Exit(code=0)
    render(result["result"])
    raise typer.Exit(code=0)


@diagnose_app.command("q")
def diagnose_q_cmd(
    touchstone: str = typer.Argument(..., help="单腔反射 Touchstone（.s1p/.s2p）"),
    f0: float = typer.Option(None, "--f0", help="谐振频率提示 (GHz)"),
    qe: list[float] = typer.Option(None, "--qe", help="外部 Q（可多次给）"),  # noqa: B008
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """Q 双通道（VF 极点法 × Kajfez 圆拟合）互证 + skrf 第三方仲裁。

    互证 |ΔQu|/Qu≤10％ → AGREE，超阈 UNDECIDABLE（#122）；三方极差 ≤15％ 如实报。

    示例：rfauto diagnose q cavity.s1p --f0 2.5 --qe 250
    """
    from rfauto.service.diagnosis_service import run_diagnosis

    request: dict = {"mode": "q", "touchstone_path": touchstone}
    if f0 is not None:
        request["f0_hint_ghz"] = f0
    if qe:
        request["q_e"] = list(qe)
    _diagnose_emit(run_diagnosis(request), json_output, _render_diagnose_q)


def _render_diagnose_q(r: dict) -> None:
    vf, circ = r["vf"], r["circle"]
    table = Table(title="Q 双通道（DP-2）")
    table.add_column("通道")
    table.add_column("Qu", justify="right")
    table.add_column("QL", justify="right")
    table.add_column("f0 (GHz)", justify="right")
    table.add_row("vf 极点法", str(vf.get("q_unloaded")),
                  str(vf.get("q_loaded")), str(vf.get("f0_ghz")))
    table.add_row("Kajfez 圆拟合", str(circ.get("q_unloaded")),
                  str(circ.get("q_loaded")), str(circ.get("f0_ghz")))
    third = r.get("third_opinion")
    if third and not third.get("unavailable"):
        table.add_row("skrf.qfactor 仲裁", str(third.get("q_unloaded")),
                      str(third.get("q_loaded")), str(third.get("f_ghz")))
    console.print(table)
    console.print(f"互证 verdict: [cyan]{r['verdict']}[/cyan]"
                  f"（差 {r['cross_diff_pct']:.2%}，门 {r['cross_tol']:.0%}）")
    if vf.get("loss_degraded"):
        console.print("[yellow]! loss_degraded：|Re p|/|Im p| > 0.05，"
                      "Q 不确定度放大[/yellow]")
    if r.get("third_check"):
        console.print(f"三方极差: {r['third_check']['range_pct']:.2%}"
                      f"（≤15% 门: {r['third_check']['within_15pct']}）")


@diagnose_app.command("cm")
def diagnose_cm_cmd(
    touchstone: str = typer.Argument(..., help="滤波器 2 端口 Touchstone（.s2p）"),
    order: int = typer.Option(None, "--order", help="阶数（缺省=VF 自动判）"),
    f0: float = typer.Option(None, "--f0", help="中心频率提示 (GHz)"),
    fbw: float = typer.Option(None, "--fbw", help="相对带宽提示"),
    topology: str = typer.Option("folded", "--topology", help="folded|arrow"),
    target: str = typer.Option(None, "--target",
                               help="目标耦合矩阵 JSON 文件（[re,im] 对嵌套列表）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """CM 反向提取（VF 结构面 + LM 固定拓扑精化）+ 可选目标逐元素偏差表。

    示例：rfauto diagnose cm filter.s2p --f0 2.5 --fbw 0.1 --target m.json
    """
    from rfauto.service.diagnosis_service import run_diagnosis

    request: dict = {"mode": "cm", "touchstone_path": touchstone,
                     "topology": topology}
    if order is not None:
        request["order"] = order
    if f0 is not None:
        request["f0_ghz"] = f0
    if fbw is not None:
        request["fbw"] = fbw
    if target is not None:
        request["target_matrix"] = _load_json_value(target, "目标矩阵")
    _diagnose_emit(run_diagnosis(request), json_output, _render_diagnose_cm)


def _render_diagnose_cm(r: dict) -> None:
    ext, ref = r["extract"], r["refine"]
    console.print(f"[bold]CM 反提（DP-2）[/bold]：N={ext['order']} "
                  f"n_fz={ext['n_fz']} f0={ext['f0_ghz']}GHz fbw={ext['fbw']}")
    scan_txt = ", ".join(f"K={s['n_poles_cmplx']}:{s['rms']:.1e}"
                         for s in ext["vf_scan"])
    console.print(f"  VF 定阶扫: {scan_txt}")
    console.print(f"  精化: ok={ref['ok']} rms={ref['fit_rms']:.2e} "
                  f"max|ΔS|={ref['response_max_dev']:.2e} "
                  f"支撑集={ref['support_size']}元 "
                  f"同伦λ={ref['homotopy_lambda_final']}")
    chk = r.get("target_check")
    if chk:
        mark = "[green]PASS[/green]" if chk["pass"] else "[red]FAIL[/red]"
        console.print(f"  目标偏差: max={chk['max_rel_dev']:.2%} "
                      f"（门 5%: {mark}）")
        for d in chk["elements"]:
            console.print(f"    m[{d['i']},{d['j']}]: {d['rel_dev']:.2%}")


@diagnose_app.command("cat")
def diagnose_cat_cmd(
    touchstone: str = typer.Argument(..., help="透射 Touchstone（.s2p；单腔步）"),
    f0: float = typer.Option(..., "--f0", help="目标中心频率 (GHz)"),
    fbw: float = typer.Option(..., "--fbw", help="相对带宽"),
    target: str = typer.Option(..., "--target",
                               help="目标耦合矩阵 JSON 文件"),
    params: str = typer.Option(None, "--params",
                               help="当前可调参数 JSON {name: value}"),
    bounds: str = typer.Option(None, "--bounds",
                               help="参数界 JSON {name: [lo, hi]}"),
    tol: float = typer.Option(0.1, "--tol", help="相对容差"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """Dishal 顺序调谐 critique（τ 峰数指纹 + issues + typed fixes）。

    C 系数钉死：S21 透射泄漏 C=2 / S11 反射全通 C=4（合成回收裁决）。

    示例：rfauto diagnose cat step1.s2p --f0 2.5 --fbw 0.1 --target m.json
    """
    from rfauto.service.diagnosis_service import run_diagnosis

    request: dict = {"mode": "cat", "touchstone_path": touchstone,
                     "f0_ghz": f0, "fbw": fbw,
                     "target_matrix": _load_json_value(target, "目标矩阵"),
                     "tol": tol}
    if params is not None:
        request["current_params"] = _load_json_value(params, "参数表")
    if bounds is not None:
        request["bounds"] = _load_json_value(bounds, "参数界")
    _diagnose_emit(run_diagnosis(request), json_output, _render_diagnose_cat)


def _render_diagnose_cat(r: dict) -> None:
    console.print(f"[bold]Dishal critique[/bold]（{r['channel']} 口径，"
                  f"C={r['c_coef']}）：τ 峰数={r['n_peaks']} → "
                  f"verdict [cyan]{r['verdict']}[/cyan]")
    if r.get("qe_measured") is not None:
        console.print(f"  Qe: 实测 {r['qe_measured']:.4g} vs 目标 "
                      f"{r['qe1_target']:.4g}"
                      f"（偏 {r.get('qe_deviation') or 0:+.1%}）")
    if r.get("k_measured") is not None:
        console.print(f"  k12: 实测 {r['k_measured']:.4g} vs 目标 "
                      f"{r['k12_target']:.4g}")
    fp = r["fingerprint"]
    if fp.get("peak_offset_pct") is not None:
        console.print(f"  峰位偏: {fp['peak_offset_pct']:+.2f}%"
                      "（失谐方向指纹）")
    for iss in r["issues"]:
        console.print(f"  [yellow]issue[/yellow] {iss['kind']}: "
                      f"{iss.get('deviation')}")
    for fx in r["fixes"]:
        console.print(f"  [cyan]fix[/cyan] {fx['kind']} {fx['op']} "
                      f"{fx['param'] or '(coord_probe)'} → {fx['value']}")


# ─── correlate (E9c 相关性) ───────────────────────────────────────────────────

@app.command()
def correlate(
    sim_file: str = typer.Argument(..., help="仿真结果文件 (.s2p)"),
    measured_file: str = typer.Argument(..., help="测量数据文件 (.s2p)"),
    threshold_db: float = typer.Option(3.0, "--threshold", "-t", help="偏差阈值 (dB)"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """仿真 vs 测量相关性分析。"""
    from rfauto.service.api import correlate_files

    try:
        result = correlate_files(sim_file, measured_file, threshold_db=threshold_db)
    except FileNotFoundError as e:
        if json_output:
            # VI-5 W6-B：入参缺失也信封（--json 下失败路径不许非 JSON）
            _emit({"ok": False, "errors": [str(e)]}, "相关性分析失败", json_output=True)
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(code=1) from None
    except Exception as e:
        if json_output:
            _emit({"ok": False, "errors": [f"相关性分析失败: {e}"]},
                  "相关性分析失败", json_output=True)
        console.print(f"[red]✗ 相关性分析失败: {e}[/red]")
        raise typer.Exit(code=1) from None

    data = result["data"]
    if json_output:
        # VI-5 W6-B：--json 信封（不相关退出码 1 语义保持）
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
        if not data.get("is_correlated"):
            raise typer.Exit(code=1)
        return
    verdict = (
        "[green]相关[/green]" if data.get("is_correlated") else "[red]不相关[/red]"
    )
    console.print(f"\n[bold]相关性判定: {verdict}[/bold]（阈值 {threshold_db} dB）")
    for k, v in data.get("metrics", {}).items():
        console.print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    for w in data.get("warnings", []):
        console.print(f"  [yellow]! {w}[/yellow]")

    if not data.get("is_correlated"):
        raise typer.Exit(code=1)


# ─── deviation（SO-审查 §7 P4 测量闭环桥 W6-D：实测偏差→侦探叙事→提案）──
# service/measurement_loop_service 确定性编排（correlate/FSV/En → explain
# 形载荷 → data_detective 四段式），铁律 7 零新数值面，此处纯转发。


@diagnose_app.command("deviation")
def diagnose_deviation_cmd(
    sim_file: str = typer.Argument(..., help="仿真 Touchstone 文件 (.s2p)"),
    measured_file: str = typer.Argument(..., help="实测 Touchstone 文件 (.s2p)"),
    run_dir: str = typer.Option(None, "--run-dir",
                                help="关联仿真 run 目录（provenance 指针）"),
    threshold_db: float = typer.Option(3.0, "--threshold", "-t",
                                       help="相关性偏差门 (dB)"),
    en_report: bool = typer.Option(False, "--en",
                                   help="附 En 不确定度报告（GUM 预算缺省模板）"),
    markdown: str = typer.Option(None, "--markdown", "-m",
                                 help="侦探叙事 Markdown 落盘路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """实测↔仿真偏差归因桥（FSV/相关性→四段式侦探叙事）。

    实测偏差进诊断-提案环的第一段；参数提案接
    rfauto agent propose --params（偏差数字不臆造参数值）。

    示例：rfauto diagnose deviation sim.s2p meas.s2p --run-dir runs/x --json
    """
    from rfauto.service.measurement_loop_service import (
        measurement_deviation_report,
    )

    result = measurement_deviation_report(
        sim_file, measured_file, run_dir=run_dir, threshold_db=threshold_db,
        en_report=en_report, markdown_path=markdown)
    _emit(result, "偏差归因桥失败", json_output=json_output)
    if json_output:
        return
    det = result.get("detective") or {}
    console.print(f"[bold]实测↔仿真偏差报告[/bold]（schema "
                  f"{result.get('schema')}）")
    corr = (result.get("correlation") or {})
    console.print(
        "  相关性: [cyan]{verdict}[/cyan]（门 {th} dB）".format(
            verdict="相关" if corr.get("is_correlated") else "不相关",
            th=threshold_db))
    for trace, row in sorted((result.get("fsv") or {}).items()):
        if isinstance(row, dict) and row.get("ok"):
            console.print(
                f"  FSV {trace}: ADM={row.get('adm_grade')} "
                f"FDM={row.get('fdm_grade')} GDM={row.get('gdm_grade')}")
        else:
            console.print(f"  FSV {trace}: 不可评估（如实记录）")
    if result.get("markdown_path"):
        console.print(f"  叙事落盘: {result['markdown_path']}")
    from rich.markdown import Markdown

    console.print(Markdown(det.get("narrative") or ""))


# ─── detective（VI-1 孤儿接线批 W1-C 单元 12：数据侦探四段式，round19 口径）──
# explain 确定性结果 → 发现/根因假设/证据链/结论 四段报告；数字白名单与
# 叙述审计全在 service/data_detective 确定性内核（铁律 7），此处纯转发。


@diagnose_app.command("detective")
def diagnose_detective_cmd(
    run_dir: str = typer.Option(None, "--run-dir",
                                help="run 目录（现调 explain_run 指纹匹配出报告）"),
    ref: str = typer.Option(None, "--ref",
                            help="explain_run 结果 JSON 文件（直接消费，跳过现调）"),
    playbook: str = typer.Option(None, "--playbook",
                                 help="playbook JSON 路径覆盖（缺省仓内置）"),
    markdown: str = typer.Option(None, "--markdown", "-m",
                                 help="Markdown 报告落盘路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """数据侦探四段式报告（发现/根因假设/证据链/结论；--run-dir 或 --ref 二选一）。

    示例：rfauto diagnose detective --run-dir runs/20260905_032407_e643d139
          rfauto diagnose detective --ref explain.json --markdown report.md
    """
    from rfauto.service.data_detective import (
        data_detective_report,
        render_detective_markdown,
    )

    if not run_dir and not ref:
        _emit({"ok": False,
               "errors": ["--run-dir 与 --ref 至少给一个"
                          "（现调 explain 或直接消费既有结果）"]},
              "缺少输入", json_output=json_output)
        raise typer.Exit(code=1)
    explain_result = None
    if ref:
        explain_result = _load_json_value(ref, "explain 结果")
    result = data_detective_report(
        explain_result, run_dir=run_dir, playbook_path=playbook)
    if result.get("ok") and markdown:
        Path(markdown).write_text(render_detective_markdown(result),
                                  encoding="utf-8")
        result = dict(result)
        result["markdown_path"] = markdown
    _emit(result, "侦探报告失败", json_output=json_output)
    if not json_output and result.get("ok"):
        from rich.markdown import Markdown

        console.print(Markdown(render_detective_markdown(result)))
    if not result.get("ok"):
        raise typer.Exit(code=1)
