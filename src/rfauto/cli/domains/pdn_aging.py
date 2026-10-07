"""pdn 子应用（F-B PI/PDN）+ aging 子应用（F-C 老化漂移）+ afs 子应用（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _load_json_file as _load_json_file
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── pdn（F-B P2：PI/PDN AC 阻抗域 analyze/select/gate 薄壳） ─────────────────
# 零逻辑转发 service/pdn_service（规则 4）；payload JSON 文件走 _load_json_file；
# 路径参数 str 注解（#269 B008）；数值只在确定性内核（铁律 7）；与 MCP 工具
# pdn_analyze/pdn_select/pdn_gate 同源同名 service 函数（JSON 进出）。

pdn_app = typer.Typer(help="PI/PDN AC 阻抗域分析（F-B：目标阻抗/去耦选型/平面腔模门）")
app.add_typer(pdn_app, name="pdn")


@pdn_app.command("analyze")
def pdn_analyze_cmd(
    payload_path: str = typer.Argument(
        ..., help="payload JSON 文件（键见 service.pdn_service.pdn_analyze）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """PDN 阻抗谱分析：Z 谱+逐频裕量+反谐振峰清单+腔模（JSON 进出薄壳）。"""
    from rfauto.service.pdn_service import pdn_analyze as _analyze

    payload = _load_json_file(payload_path, "payload")
    try:
        result = _analyze(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"payload 非法: {exc}"]}
    # VI-5 W6-B：缺省即 _emit 信封直出，旗标为归一兼容位（两形态同输出）。
    _emit(result, "PDN 分析失败", json_output=True)


@pdn_app.command("select")
def pdn_select_cmd(
    payload_path: str = typer.Argument(
        ..., help="payload JSON 文件（键见 service.pdn_service.pdn_select）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """贪心 decap 选型：candidates+budget+target → 选中明细+逐频裕量（infeasible 如实透传）。"""
    from rfauto.service.pdn_service import pdn_select as _select

    payload = _load_json_file(payload_path, "payload")
    try:
        result = _select(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"payload 非法: {exc}"]}
    _emit(result, "PDN 选型失败", json_output=True)


@pdn_app.command("gate")
def pdn_gate_cmd(
    payload_path: str = typer.Argument(
        ..., help="payload JSON 文件（键见 service.pdn_service.pdn_gate）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """KiCad AC-PI 门：平面腔模筛查+安装避让+（可选）Z 谱裕量门（verdict 三值）。"""
    from rfauto.service.pdn_service import pdn_gate as _gate

    payload = _load_json_file(payload_path, "payload")
    try:
        result = _gate(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"payload 非法: {exc}"]}
    _emit(result, "PI 门检查失败", json_output=True)


# ─── aging（F-C P2：器件老化漂移 simulate/verdict/report 薄壳） ───────────────
# 零逻辑转发 service/aging_service（规则 4）；payload JSON 文件走
# _load_json_file；路径参数 str 注解（#269 B008）；数值只在确定性内核
# （铁律 7，core/aging 三律+profile_integrate）；与 MCP 工具
# aging_simulate/aging_verdict/aging_report 同源同名 service 函数（JSON 进出）。

aging_app = typer.Typer(help="器件老化漂移（F-C：PoF 时间轴→εr 漂移→EOL 失谐判据，fake 通道）")
app.add_typer(aging_app, name="aging")


@aging_app.command("simulate")
def aging_simulate_cmd(
    payload_path: str = typer.Argument(
        ..., help="payload JSON 文件（键见 service.aging_service.aging_simulate）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """老化漂移仿真：任务剖面→εr 漂移轨迹→fake 名义/EOL 两点 S 参数+失谐量。"""
    from rfauto.service.aging_service import aging_simulate as _simulate

    payload = _load_json_file(payload_path, "payload")
    try:
        result = _simulate(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"payload 非法: {exc}"]}
    # VI-5 W6-B：同 pdn 三叶——缺省即信封直出，旗标为归一兼容位。
    _emit(result, "老化漂移仿真失败", json_output=True)


@aging_app.command("verdict")
def aging_verdict_cmd(
    payload_path: str = typer.Argument(
        ..., help="payload JSON 文件（键见 service.aging_service.aging_eol_verdict）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """EOL 失谐判据：|detune_pct| ≤ spec（恰等判 PASS）→ PASS/FAIL 纯确定性。"""
    from rfauto.service.aging_service import aging_eol_verdict as _verdict

    payload = _load_json_file(payload_path, "payload")
    try:
        result = _verdict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"payload 非法: {exc}"]}
    _emit(result, "EOL 判据失败", json_output=True)


@aging_app.command("report")
def aging_report_cmd(
    payload_path: str = typer.Argument(
        ..., help="payload JSON 文件（键见 service.aging_service.aging_report）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """老化报告：mission_profile 表/漂移轨迹/EOL 判据/法源 provenance 四节。"""
    from rfauto.service.aging_service import aging_report as _report

    payload = _load_json_file(payload_path, "payload")
    try:
        result = _report(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"payload 非法: {exc}"]}
    _emit(result, "老化报告失败", json_output=True)


# ─── afs（M-3：AFS 自适应频扫 plan/sweep 薄壳，--synthetic 合成演示零真机） ────
# exit code 语义：0=ok 且（sweep）收敛+验收过；1=sweep 跑完但未收敛或验收
# FAIL（未收敛是合法结果、如实标注，不进 error）；2=程序性错误（参数非法/
# 规格解析失败/回调契约违背）。

afs_app = typer.Typer(help="AFS 自适应频扫（M-3：向量拟合驱动选频点，收敛即停；JSON 进出薄壳）")
app.add_typer(afs_app, name="afs")


def _afs_band_from_ghz(f_min_ghz: float, f_max_ghz: float) -> list[float]:
    return [float(f_min_ghz) * 1e9, float(f_max_ghz) * 1e9]


def _afs_emit_summary(result: dict) -> None:
    plan = result["plan"]
    console.print("[bold]AFS 扫频计划[/bold]（纯计划面，未求解）")
    console.print(f"  band: {plan['band_hz'][0]:.6g} .. {plan['band_hz'][1]:.6g} Hz"
                  f"  tol={plan['tol']}  n_init={plan['n_init']}"
                  f"  max_points={plan['max_points']}  max_rounds={plan['max_rounds']}"
                  f"  n_dense={plan['n_dense']}")
    console.print(f"  初始频点({plan['n_init']}): "
                  + ", ".join(f"{f:.6g}" for f in plan["initial_frequencies_hz"]))
    console.print(f"  定阶阶梯: {plan['order_ladder']}  "
                  f"拟合 RMS 阈值: {plan['fit_rms_threshold_db']} dB")
    ac = plan["acceptance_criteria"]
    console.print(f"  验收判据: 缩减 >= {ac['reduction_ratio_min']} 且 FSV >= "
                  f"{ac['fsv_min_grade']}（§10.20 补强⑩）")


def _afs_sweep_summary(result: dict) -> None:
    s = result["result"]
    vs = s.get("vs_full") or {}
    console.print(f"[bold]AFS 自适应频扫[/bold]  status={s['status']}"
                  f"  converged={s['converged']}  rounds={s['rounds']}")
    console.print(f"  求解计费: n_solves={s['n_solves']}"
                  + (f"（全扫参考 {vs.get('n_full')} 点，缩减 "
                     f"{vs.get('reduction_ratio', 0.0):.1%}）" if vs else ""))
    fsv = vs.get("fsv") or {}
    if fsv:
        console.print(f"  FSV(vs 全扫): GDM={fsv.get('gdm_grade')}"
                      f"（gdm_mean={fsv.get('gdm_mean'):.4g}）"
                      f"  at_least_VG={fsv.get('at_least_vg')}")
    acc = s.get("acceptance")
    if acc is not None:
        mark = "[green]PASS[/green]" if acc["passed"] else "[red]FAIL[/red]"
        console.print(f"  验收门(§10.20 补强⑩): {mark}"
                      f"  reduction_ok={acc['reduction_ok']}"
                      f"  fsv_ok={acc['fsv_ok']}")
    fit = s.get("fit") or {}
    console.print(f"  拟合: poles(real={fit.get('n_poles_real')},"
                  f"cmplx={fit.get('n_poles_cmplx')})"
                  f"  样本点 RMS={fit.get('rms_db_at_samples')} dB"
                  f"  max_mid_err={s.get('max_midpoint_error')}")


@afs_app.command("plan")
def afs_plan_cmd(
    f_min_ghz: float = typer.Option(..., "--f-min-ghz", help="频带下端 (GHz)"),
    f_max_ghz: float = typer.Option(..., "--f-max-ghz", help="频带上端 (GHz)"),
    tol: float = typer.Option(1e-2, "--tol", help="中点收敛容差（线性复幅差）"),
    max_points: int = typer.Option(96, "--max-points", help="采样点上限（终止保护）"),
    n_init: int = typer.Option(7, "--n-init", help="初始均匀采样点数（>=3）"),
    max_rounds: int = typer.Option(12, "--max-rounds", help="加密轮数上限"),
    json_output: bool = typer.Option(False, "--json", "-j", help="输出完整 JSON"),
) -> None:
    """AFS 扫频计划（纯计划面：初始频点表+加密协议+验收判据，不求解）。

    示例：rfauto afs plan --f-min-ghz 1.0 --f-max-ghz 4.0 --json
    """
    from rfauto.service.afs_service import afs_sweep_plan

    result = afs_sweep_plan(
        _afs_band_from_ghz(f_min_ghz, f_max_ghz), tol, max_points,
        n_init=n_init, max_rounds=max_rounds)
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error')}[/red]")
        raise typer.Exit(code=2)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False))
    else:
        _afs_emit_summary(result)


@afs_app.command("sweep")
def afs_sweep_cmd(
    f_min_ghz: float = typer.Option(..., "--f-min-ghz", help="频带下端 (GHz)"),
    f_max_ghz: float = typer.Option(..., "--f-max-ghz", help="频带上端 (GHz)"),
    synthetic: str = typer.Option(
        ..., "--synthetic",
        help="合成多谐振演示响应规格 'f0_ghz:q_pole[:q_zero][;...][;ripple=amp]'"
             "（零真机端到端演示；生产 evaluate 注入走 service.afs_service.afs_sweep）"),
    tol: float = typer.Option(1e-2, "--tol", help="中点收敛容差（线性复幅差）"),
    max_iter: int = typer.Option(12, "--max-iter", help="加密轮数上限（透传内核 max_rounds）"),
    max_points: int = typer.Option(96, "--max-points", help="采样点上限（终止保护）"),
    n_init: int = typer.Option(7, "--n-init", help="初始均匀采样点数（>=3）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="输出完整 JSON"),
) -> None:
    """AFS 自适应频扫端到端演示（--synthetic 合成多谐振函数当真响应，零真机）。

    验收判据（§10.20 补强⑩，full_response=同函数密集全扫）：
    solve 数缩减 >= 50％ 且重建 vs 全扫 FSV >= VG。

    示例：rfauto afs sweep --f-min-ghz 1.0 --f-max-ghz 4.0 --synthetic "2.4:40;3.1:60;ripple=0.02"
    """
    import numpy as np

    from rfauto.service.afs_service import (
        afs_sweep,
        synthetic_multiresonance_response,
    )

    band = _afs_band_from_ghz(f_min_ghz, f_max_ghz)
    try:
        response, spec = synthetic_multiresonance_response(synthetic, band[0], band[1])
    except (TypeError, ValueError) as exc:
        console.print(f"[red]✗ synthetic 规格非法: {exc}[/red]")
        raise typer.Exit(code=2) from exc

    def evaluate(f_hz: float) -> dict:
        return {"s": complex(response(np.asarray([float(f_hz)]))[0])}

    result = afs_sweep(evaluate, band, tol, max_iter,
                       n_init=n_init, max_points=max_points,
                       full_response=response)
    result["synthetic_spec"] = spec
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error')}[/red]"
                      f"（中止前求解计费 n={result.get('n_solves_before_abort')}）")
        raise typer.Exit(code=2)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False))
    else:
        _afs_sweep_summary(result)
    s = result["result"]
    acc = s.get("acceptance") or {}
    if not s.get("converged") or not acc.get("passed", False):
        raise typer.Exit(code=1)
