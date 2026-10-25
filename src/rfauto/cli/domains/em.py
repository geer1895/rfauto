"""em 子应用（自定义 EM 模型语义检查面；aurora_k K5 席，2026-10-23）。

v1 单叶：doctor——模型清单（YAML/JSON inventory）驱动的 pre-solve 几何/
端口语义体检（反馈 P12/F8：HFSS ValidateDesign 只查语法不查端口语义，
aperture 不含金属照样解出 L≈0.135 nH 假结果）。零逻辑转发
service/em_doctor_service（规则 4）；清单 schema 与 16 项检查归属表见该
模块 docstring。带 --json（信封契约；Agent 消费面）。

aurora_k K8 两叶（反馈 F6/P14）：deembed（THRU 对称半拆双边去嵌——参考
面从引线外端移回 pad 边缘）/ metrics（串联/并联器件 C/R/Q 指标——Z12
传输阻抗主口径+简化式强失配拒绝）。零逻辑薄壳**直连 core/deembed 纯函数
面**（A-11 裁定=只读出口，calc_vna oracle 叶同款先例——本席文件面不含
service/，读 Touchstone+装配在叶内完成即薄 I/O）。全叶带 --json。

aurora_k K10 一叶（反馈 P16/F9）：sweep——DOE/矩阵编排器（cases.yaml
笛卡尔全积展开 → 逐 case 串行执行[内存闸+janitor 资源防线] →
summary.csv/json 汇总）。零逻辑转发 service/em_sweep_service。带 --json。

aurora_k K16（反馈 P14/P6）：metrics 增 --run 入口（run 目录双路读数
metrics.json+Touchstone → K8 提取 → core.metric_groups 同族绑定——
series 族 Q 在场自动附 C/R/S21 并提示"Q 随 C 变，不是纯损耗"）与
--converged-with 两档网格收敛对比（service.convergence_check，偏差
>rel_tol 判 not_converged——默认网格能解≠数值可用）。零逻辑转发
service/em_metrics_service。带 --json。

aurora_k K18 一叶（反馈 P17/F13）：diff——run 目录级四面对比（meta
params 逐键/K5 模型清单按 name 逐项[对象/端口/叠层/keepout 增删改，
aperture z 0–190→0–295.2 正是验收靶]/Touchstone S 参数同栅对拍
[#287/#294 家法]+K4 新鲜度交叉），替代用户手工 diff .aedt 文本。
零逻辑转发 service/em_diff_service。带 --json。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

em_app = typer.Typer(
    help="自定义 EM 模型语义面：清单驱动的 pre-solve 体检、THRU 去嵌与指标"
         "提取（零 AEDT 依赖）、DOE/矩阵 sweep 编排（串行真机+资源闸）、"
         "run 目录级 diff 四面对比")
app.add_typer(em_app, name="em")

_STATUS_STYLE = {
    "PASS": "green",
    "FAIL": "red",
    "WARN": "yellow",
    "SKIP": "dim",
}


@em_app.command("doctor")
def em_doctor_cmd(
    manifest: str = typer.Argument(
        ...,
        help="模型清单文件（.yaml/.yml/.json；schema 见 "
             "service/em_doctor_service.py docstring）"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="JSON 信封输出（供脚本/Agent 消费）"),
) -> None:
    """EM 模型清单体检（16 项检查表中清单可判定的子集）。

    输出逐项 PASS/FAIL/WARN/SKIP(v2) 清单 + 总判定；有 FAIL → 退出码 1
    （把"aperture 不含金属/植球短信号/薄层竖墙"在建模阶段拦下，而不是
    解出假结果后再人肉追查）。
    """
    from rfauto.service.em_doctor_service import doctor_from_file  # lazy: cli 注册根轻载

    result = doctor_from_file(manifest)
    if json_output:
        _emit(result, "EM 模型清单体检失败", json_output=True)
        return
    if not result.get("ok") and "checks" not in result:
        # 装载失败（清单不存在/不可解析）——error 信封的人类面
        errs = result.get("errors") or ["清单装载失败"]
        for err in errs:
            console.print(f"[red]✗ {err}[/red]")
        raise typer.Exit(code=1)
    from rich.table import Table

    verdict = str(result.get("verdict", "FAIL"))
    style = "red" if verdict == "FAIL" else "green"
    summary = result.get("summary", {})
    console.print(
        f"[bold]EM 模型清单体检[/bold]  {manifest}  "
        f"verdict: [{style}]{verdict}[/{style}]"
        f"（PASS {summary.get('n_pass', 0)} / FAIL {summary.get('n_fail', 0)}"
        f" / WARN {summary.get('n_warn', 0)} / SKIP {summary.get('n_skip', 0)}"
        f"，其中 v2 待登记 {summary.get('n_skip_v2', 0)}）")
    table = Table(title="em doctor（16 项检查清单）")
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("检查", no_wrap=True)
    table.add_column("状态", no_wrap=True)
    table.add_column("结论（会抓到的真实问题见 catches 字段）")
    for check in result.get("checks", []):
        status = str(check.get("status", "SKIP"))
        st_style = _STATUS_STYLE.get(status, "white")
        table.add_row(
            str(check.get("table_ref", "")),
            str(check.get("title", check.get("check", ""))),
            f"[{st_style}]{status}[/{st_style}]"
            + ("(v2)" if check.get("reason_tag") == "v2" else ""),
            str(check.get("detail", "")))
    console.print(table)
    for err in result.get("errors", []):
        console.print(f"[red]- {err}[/red]")
    if not result.get("ok"):
        raise typer.Exit(code=1)


def _load_network(path: str, json_output: bool, what: str):
    """读 Touchstone 网络（薄 I/O；不存在/不可读 → 统一失败信封）。"""
    from pathlib import Path

    from rfauto.service.envelope import error_envelope

    p = Path(path)
    try:
        import skrf

        net = skrf.Network(p)
    except Exception as exc:  # FileNotFoundError/解析错误统一信封
        _emit(error_envelope(f"{what}不可读（{p}）: {exc}"),
              f"{what}不可读", json_output=json_output)
        raise
    return net


def _print_series_report(result: dict, title: str) -> None:
    """串联指标人读面（rich 表 + notes/拒绝建议红字）。"""
    from rich.table import Table

    console.print(f"[bold]{title}[/bold]  "
                  f"f_eval={result['f_eval_hz'] / 1e9:.4g} GHz  "
                  f"参考面: {result['reference_plane']}"
                  f"{'（已去嵌）' if result['deembedded'] else ''}")
    series = result.get("series")
    if series:
        table = Table(title="串联指标（2 端口）")
        table.add_column("提取方法")
        table.add_column("R Ω", justify="right")
        table.add_column("X Ω", justify="right")
        table.add_column("C fF / L nH", justify="right")
        table.add_column("Q", justify="right")
        for tag, block in (("Z12 主方法", series),
                           ("−1/Y21（π 并联免疫）", result.get("series_y21"))):
            if block is None:
                continue
            cl = (f"{block['c_series_f']:.4g} fF"
                  if block["c_series_f"] is not None
                  else (f"{block['l_series_h'] * 1e9:.4g} nH"
                        if block["l_series_h"] is not None else "—"))
            table.add_row(
                tag, f"{block['r_series_ohm']:.4g}", f"{block['x_series_ohm']:.4g}",
                cl, "—" if block["q_series"] is None else f"{block['q_series']:.4g}")
        console.print(table)
    shunt = result.get("shunt")
    if shunt:
        cl = (f"{shunt['c_shunt_f']:.4g} fF"
              if shunt["c_shunt_f"] is not None
              else (f"{shunt['l_shunt_h'] * 1e9:.4g} nH"
                    if shunt["l_shunt_h"] is not None else "—"))
        console.print(
            f"并联指标（1 端口 Y11）: G={shunt['g_shunt_s']:.4g} S  "
            f"B={shunt['b_shunt_s']:.4g} S  {cl}  "
            f"Q={'—' if shunt['q_shunt'] is None else format(shunt['q_shunt'], '.4g')}")
    srf = result.get("srf_hz")
    if srf is not None:
        console.print(f"SRF = {srf / 1e9:.6g} GHz")
    simp = result.get("simplified_formula")
    if simp and simp.get("rejected"):
        console.print(f"[red]✗ 简化式 2Z0(1/S21−1) 已拒绝"
                      f"（|S11|={simp['s11_mag']:.3f} > {simp['threshold']}）"
                      f"——假值 R={simp['r_series_ohm']:.4g} Ω[/red]")
        console.print(f"  [cyan]→ {simp['advice']}[/cyan]")
    for note in result.get("notes", []):
        console.print(f"  [yellow]注[/yellow] {note}")


@em_app.command("deembed")
def em_deembed_cmd(
    dut: str = typer.Option(..., "--dut", help="DUT 2 端口 Touchstone（.s2p，含引线/pad 的实测）"),
    thru: str = typer.Option(..., "--thru", help="2x-thru 标准 2 端口 Touchstone（.s2p，与 DUT 同截面）"),
    half: bool = typer.Option(True, "--half/--no-half", help="半拆双边（夹具镜像同件，缺省）/全长单边"),
    side: str = typer.Option("output", "--side", help="no-half 时的单边侧 input/output"),
    f_eval_ghz: float = typer.Option(None, "--f-eval-ghz", help="指标评估频率 GHz（缺省=带内几何中心）"),
    reject_threshold: float = typer.Option(0.9, "--reject-simplified-threshold",
                                           help="简化式拒绝 |S11| 阈值（缺省 0.9）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 信封输出（供脚本/Agent 消费）"),
) -> None:
    """THRU 对称半拆双边去嵌 + 串联指标提取（参考面从引线外端移回 pad 边缘）。

    测量模型 measured = F ** DUT ** F、thru = F ** F（左右夹具镜像同件）；
    半拆把 2x-thru 平方根出单侧夹具后双边剥除。去嵌后按 Z12 主方法+
    −1/Y21 副方法提取 C/R/Q（|S11|>阈值时简化式显式拒绝并附建议）。
    """
    from rfauto.core.deembed import deembed_thru, z12_series_metrics

    dut_net = _load_network(dut, json_output, "DUT Touchstone")
    thru_net = _load_network(thru, json_output, "THRU Touchstone")
    try:
        deembedded = deembed_thru(dut_net, thru_net, half=half, side=side)
        result = z12_series_metrics(
            deembedded,
            f_hz=None if f_eval_ghz is None else float(f_eval_ghz) * 1e9,
            topology="series",
            simplified_reject_threshold=float(reject_threshold),
            deembedded=True,
            reference_plane=("thru-deembedded(half-split)" if half
                             else f"thru-deembedded(full,{side})"))
        result["deembed"] = {"mode": "half-split" if half else f"full-{side}",
                             "n_points": len(dut_net.f)}
        result["command"] = "em deembed"
        result["dut"] = dut
        result["thru"] = thru
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        from rfauto.service.envelope import error_envelope

        _emit(error_envelope(f"THRU 去嵌失败: {exc}"), "THRU 去嵌失败",
              json_output=json_output)
        return
    if json_output:
        _emit(result, "THRU 去嵌失败", json_output=True)
        return
    _print_series_report(result, f"em deembed  {dut} × {thru}")


@em_app.command("metrics")
def em_metrics_cmd(
    s2p: str = typer.Option(None, "--s2p", help="Touchstone 文件（.s2p 串联拓扑/.s1p 并联拓扑；与 --run 二选一）"),
    run: str = typer.Option(None, "--run", help="run 目录（results/metrics.json + Touchstone 双路读数 → 同族绑定；与 --s2p 二选一）"),
    converged_with: str = typer.Option(None, "--converged-with", help="第二个 run 目录（两档网格收敛对比；需 --run）"),
    rel_tol: float = typer.Option(0.10, "--rel-tol", help="收敛判定相对偏差容限（缺省 0.10；偏差恰等容限判 converged）"),
    convergence_metric: str = typer.Option("Q", "--convergence-metric", help="收敛判定指标（Q/SRF/C/R 别名或直接键名）"),
    topology: str = typer.Option("series", "--topology", help="series（2 端口串联，缺省）/shunt（1 端口并联）"),
    f_eval_ghz: float = typer.Option(None, "--f-eval-ghz", help="评估频率 GHz（缺省=带内几何中心栅格点）"),
    reject_threshold: float = typer.Option(0.9, "--reject-simplified-threshold",
                                           help="简化式拒绝 |S11| 阈值（缺省 0.9；仅 --s2p 路）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 信封输出（供脚本/Agent 消费）"),
) -> None:
    """串联/并联器件 C/R/Q 指标（强失配下拒绝简化式，用 Z12 传输阻抗）。

    series=Z12 主方法（R=Re(Z12)、C=−1/(ω·Im(Z12))、Q=|X|/R）+−1/Y21
    副方法（π 端并联寄生免疫，去嵌后逐位回收）；shunt=1 端口 Y11 的
    L/C/Q/SRF。|S11|>阈值（缺省 0.9）时简化式 2Z0(1/S21−1) 显式拒绝
    并附建议（实测：R=1.4Ω 误算成 50Ω 量级）。

    --run 入口：run 目录双路读数（metrics.json 主读数 +
    Touchstone 家族键补充）→ 同族绑定输出——Q 在场自动附同族其余键
    （在盘就附、不在盘如实标 missing），series 族附"Q 随 C 变，不是纯
    损耗"提示。--converged-with：与第二个 run 目录出两档
    网格收敛判定，偏差 >rel_tol 判 not_converged（默认网格能解≠数值
    可用）。
    """
    from rfauto.cli.domains._core import _emit_usage_error

    if (s2p is None) == (run is None):
        _emit_usage_error("--s2p 与 --run 必须二选一（文件入口 / run 目录入口）",
                          json_output=json_output)
    if converged_with is not None and run is None:
        _emit_usage_error("--converged-with 需要 --run（run 目录对比形态）",
                          json_output=json_output)

    if run is not None:
        from rfauto.service.em_metrics_service import (
            convergence_check,
            em_metrics_from_run,
        )

        result = em_metrics_from_run(run, f_eval_ghz=f_eval_ghz)
        if result.get("ok") and converged_with is not None:
            result["convergence"] = convergence_check(
                run, converged_with, metric=convergence_metric,
                rel_tol=rel_tol)
        if json_output or not result.get("ok"):
            _emit(result, "run 指标读取失败", json_output=json_output)
            return
        _print_run_metrics_report(result)
        return

    from rfauto.core.deembed import z12_series_metrics

    net = _load_network(s2p, json_output, "Touchstone")
    try:
        result = z12_series_metrics(
            net,
            f_hz=None if f_eval_ghz is None else float(f_eval_ghz) * 1e9,
            topology=topology,
            simplified_reject_threshold=float(reject_threshold))
        result["command"] = "em metrics"
        result["s2p"] = s2p
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        from rfauto.service.envelope import error_envelope

        _emit(error_envelope(f"指标提取失败: {exc}"), "指标提取失败",
              json_output=json_output)
        return
    if json_output:
        _emit(result, "指标提取失败", json_output=True)
        return
    _print_series_report(result, f"em metrics  {s2p}")


def _fmt_val(value: object) -> str:
    """人读值格式化（有限数值 .6g；其余 str；None=—）。"""
    import math

    if value is None:
        return "—"
    if isinstance(value, (int, float)) and not isinstance(value, bool) \
            and math.isfinite(float(value)):
        return format(float(value), ".6g")
    return str(value)


def _print_convergence_block(conv: dict) -> None:
    """--converged-with 收敛判定人读块（P6：not_converged 显式提示）。"""
    verdict = str(conv.get("verdict"))
    metric = str(conv.get("metric"))
    rel_tol = conv.get("rel_tol")
    rel_dev = conv.get("rel_dev")
    dev_s = "—" if rel_dev is None else f"{rel_dev:.1%}"
    tol_s = "—" if rel_tol is None else f"{float(rel_tol):.0%}"
    if verdict == "converged":
        line = (f"[green]✓ converged[/green] {metric} 偏差 {dev_s} ≤ {tol_s}"
                "（两档网格一致性可接受）")
    elif verdict == "not_converged":
        line = (f"[red]✗ not_converged[/red] {metric} 偏差 {dev_s} > {tol_s}"
                "——默认网格能解≠数值可用，加密网格后重跑再采信")
    else:
        line = f"[yellow]insufficient_data[/yellow] {metric}（缺数据如实，不判收敛）"
    console.print(f"  收敛对比（--converged-with, rel_tol={tol_s}）: {line}")
    for side in ("m1", "m2"):
        v = conv.get("values", {}).get(side) or {}
        bits = [f"{side}: {v.get('source')}",
                f"{metric}键={v.get('key')}",
                f"值={_fmt_val(v.get('value'))}"]
        mesh = v.get("mesh") or {}
        if mesh:
            import json as _json

            bits.append("mesh=" + _json.dumps(mesh, ensure_ascii=False,
                                              sort_keys=True, default=str))
        console.print("    " + "  ".join(bits))
    for note in conv.get("notes") or []:
        console.print(f"    [yellow]注[/yellow] {note}")


def _print_run_metrics_report(result: dict) -> None:
    """--run 人读面：来源账 + 同族绑定表 + 提示行 + 收敛块。"""
    console.print(f"[bold]em metrics --run[/bold]  {result.get('run_dir')}")
    sources = result.get("sources") or {}
    bits = [
        "metrics.json ✓" if sources.get("metrics_json") else "metrics.json ✗",
        "Touchstone ✓" if sources.get("touchstone") else "Touchstone ✗",
    ]
    console.print(f"  来源: {' / '.join(bits)}")
    binding = result.get("binding") or {}
    metrics = result.get("metrics") or {}
    if binding.get("group"):
        detected = "自动判出" if binding.get("detected") else "显式指定"
        console.print(f"  族绑定: [cyan]{binding['group']}[/cyan]（{detected}）")
        from rich.table import Table

        table = Table(title="同族指标（Q 输出位自动附带同族其余键）")
        table.add_column("槽", no_wrap=True)
        table.add_column("键", no_wrap=True)
        table.add_column("值", justify="right")
        table.add_column("状态", no_wrap=True)
        for slot, member in (binding.get("members") or {}).items():
            ok = member.get("status") == "ok"
            st = "[green]ok[/green]" if ok else "[red]missing[/red]"
            table.add_row(slot, str(member.get("key")),
                          _fmt_val(member.get("value")), st)
        console.print(table)
    family_keys = set(binding.get("attached") or {}) | set(binding.get("missing") or [])
    others = sorted(k for k in metrics if k not in family_keys)
    if others:
        console.print("  其他读数: "
                      + ", ".join(f"{k}={_fmt_val(metrics[k])}" for k in others))
    for err in result.get("errors") or []:
        console.print(f"  [yellow]注[/yellow] {err}")
    for note in result.get("notes") or []:
        console.print(f"  [yellow]注[/yellow] {note}")
    conv = result.get("convergence")
    if conv:
        _print_convergence_block(conv)


@em_app.command("sweep")
def em_sweep_cmd(
    cases_yaml: str = typer.Argument(
        ..., help="cases.yaml（device × version × thickness 类矩阵描述；"
                  "schema 见 service/em_sweep_service.py docstring）"),
    adapter: str = typer.Option(
        None, "--adapter", help="覆盖 cases.yaml 的 adapter（hfss/fake；冒烟用 fake）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只打印执行计划（零执行零副作用）"),
    resume: bool = typer.Option(False, "--resume", help="跳过已完成 case（run 目录产物复核通过才算完成）"),
    max_aedt: int = typer.Option(1, "--max-aedt", help="并发 AEDT 实例上限（当前恒串行=1，>1 显式拒绝）"),
    min_free_gb: float = typer.Option(8.0, "--min-free-gb", help="内存闸：可用内存低于该 GB 数时该 case 阻塞（不硬跑）"),
    janitor: bool = typer.Option(False, "--janitor", help="启动前资源卫生清理（击杀疑似孤儿 ansysedt + 删 AEDT 工程锁）"),
    summary: bool = typer.Option(True, "--summary/--no-summary",
                                 help="跑完自动汇总 summary.csv/json（提取不到的指标如实列 missing）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 信封输出（供脚本/Agent 消费）"),
) -> None:
    """DOE/矩阵编排（16 组=2 器件 × 2 版本 × 4 厚度一条命令跑完）。

    矩阵全积展开每 case 一个 run 目录 → 逐 case 串行执行（--max-aedt
    恒 1；每 case 前过内存闸，低于阈值该 case 阻塞如实失败不硬跑；可选
    启动前 janitor 清孤儿 AEDT）→ 自动汇总 summary.csv/json（L/Q/SRF/C/R/
    S21 类指标；对比图暂未提供）。--resume 跳过已完成 case。
    """
    import contextlib

    from rfauto.service.em_sweep_service import plan_sweep, run_sweep, summarize_sweep

    plan = plan_sweep(cases_yaml, resume=resume, adapter_override=adapter)
    if not plan.get("ok"):
        _emit(plan, "sweep 计划装载失败", json_output=json_output)
        return
    result = run_sweep(plan, max_aedt=max_aedt, min_free_gb=min_free_gb,
                       janitor=janitor, dry_run=dry_run)
    if summary and not dry_run and result.get("ok"):
        with contextlib.suppress(Exception):
            # 汇总失败不翻转 run 结果（观测面 #105；missing 已在 summarize 如实列）
            result["summary"] = summarize_sweep(plan)
    if json_output:
        _emit(result, "sweep 执行失败", json_output=True)
        return
    from rich.table import Table

    state = "DRY_RUN" if dry_run else str(result.get("verdict", ""))
    n_cases = int(result.get("n_cases", plan.get("n_cases", 0)))
    console.print(
        f"[bold]em sweep[/bold]  {cases_yaml}  sweep_{plan.get('sweep_id')}"
        f"  adapter={plan.get('adapter')}  cases={n_cases}"
        + (f"  [{state}]" if state else ""))
    console.print(f"  sweep_root: {plan.get('sweep_root')}")
    if dry_run:
        console.print(f"  计划: max_aedt=1 min_free_gb={result.get('min_free_gb')}"
                      f" janitor={result.get('janitor')}（零执行预览）")
    else:
        console.print(
            f"  done={result.get('n_done', 0)}  failed={result.get('n_failed', 0)}"
            f"  blocked={result.get('n_blocked', 0)}"
            f"  skipped_resume={result.get('n_skipped_resume', 0)}")
    table = Table(title="em sweep（逐 case）")
    table.add_column("case", style="cyan", no_wrap=True)
    for axis in (plan.get("cases") or [{}])[0].get("axes", {}):
        table.add_column(axis, no_wrap=True)
    table.add_column("状态", no_wrap=True)
    table.add_column("run_dir")
    record_by_id = {str(c.get("case_id")): c for c in (result.get("cases") or [])}
    for case in plan.get("cases") or []:
        rec = record_by_id.get(str(case.get("case_id")), {})
        status = str(rec.get("status", case.get("status", "pending")))
        st_style = {"done": "green", "skipped_resume": "dim",
                    "failed": "red", "blocked_memory": "red",
                    "not_run": "yellow"}.get(status, "yellow")
        row = [str(case.get("case_id")),
               *[str(v) for v in (case.get("axes") or {}).values()],
               f"[{st_style}]{status}[/{st_style}]",
               str(rec.get("run_dir") or "")]
        table.add_row(*row)
    console.print(table)
    summary_env = result.get("summary") or {}
    if summary_env.get("ok"):
        console.print(
            f"  [green]✓[/green] 汇总: {summary_env.get('summary_csv')}"
            f" / {summary_env.get('summary_json')}"
            f"（rows={summary_env.get('n_rows')}"
            f" missing={len(summary_env.get('missing') or [])}；"
            "对比图暂未提供）")
        conv_axis = summary_env.get("convergence_axis")
        if conv_axis:
            pairs = summary_env.get("convergence_pairs") or []
            n_not_conv = sum(1 for p in pairs
                             if str(p.get("verdict")) == "not_converged")
            style = "red" if n_not_conv else "green"
            console.print(
                f"  收敛对比: 轴={conv_axis} {len(pairs)} 对"
                f"（[{style}]not_converged {n_not_conv}[/{style}]；"
                "明细见 summary.json convergence_pairs）")
    if not result.get("ok"):
        raise typer.Exit(code=1)


@em_app.command("diff")
def em_diff_cmd(
    run_a: str = typer.Argument(..., help="run 目录 A（旧）"),
    run_b: str = typer.Argument(..., help="run 目录 B（新）"),
    sections: str = typer.Option(
        "params,manifest,sparams", "--sections",
        help="对比节（逗号分隔：params/manifest/sparams；freshness 恒出）"),
    at_ghz: str = typer.Option(
        None, "--at-ghz",
        help="S 参数定点读数频率 GHz（逗号分隔多点，如 2.4,2.45）"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="JSON 信封输出（供脚本/Agent 消费）"),
) -> None:
    """run 目录级四面对比（替代手工 diff .aedt 文本）。

    params=meta.json params 逐键（新增/删除/变更，旧→新）；manifest=em
    doctor 模型清单按 name 逐项（对象/端口/叠层/keepout 增删改+关键数值
    字段，bbox 变化按轴紧凑渲染——aperture z 变化直接可见）；sparams=两 run
    Touchstone 同栅对拍（差异最大频点+--at-ghz 定点 S11/S21 dB 差表）；
    freshness=runs verify 两侧状态行。缺节如实 skip 不伪造空 diff。
    """
    from rfauto.cli.domains._core import _emit_usage_error
    from rfauto.service.em_diff_service import (
        DIFF_SECTIONS,
        diff_runs,
        to_text,
    )

    requested = [s.strip() for s in str(sections).split(",") if s.strip()]
    unknown = [s for s in requested if s not in DIFF_SECTIONS]
    if unknown:
        _emit_usage_error(
            f"未知对比节: {', '.join(unknown)}"
            f"（可选：{', '.join(DIFF_SECTIONS)}）",
            json_output=json_output)
    at_ghz_vals: list[float] = []
    if at_ghz is not None:
        try:
            at_ghz_vals = [float(g) for g in str(at_ghz).split(",") if g.strip()]
        except ValueError:
            _emit_usage_error(
                f"--at-ghz 必须是数字（GHz），可逗号分隔多点，实际 {at_ghz!r}",
                json_output=json_output)
    result = diff_runs(run_a, run_b, sections=requested, at_ghz=at_ghz_vals)
    if json_output:
        _emit(result, "em diff 失败", json_output=True)
        return
    if not result.get("ok"):
        _emit(result, "em diff 失败", json_output=False)
        return
    console.print(to_text(result))
