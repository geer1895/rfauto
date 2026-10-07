"""calc 子应用（计算器注册表面）+ sparams-compare + vna 子应用（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── calc (E4 微波计算器) ─────────────────────────────────────────────────────

calc_app = typer.Typer(help="微波闭式计算器（E4：mm/GHz/Ω/dB 口径）")
app.add_typer(calc_app, name="calc")


def _coerce_param(raw: str):
    """"50"→50、"3.66"→3.66、"true"→true，解析失败保留字符串。"""
    import json as _json

    try:
        return _json.loads(raw)
    except ValueError:
        return raw


@calc_app.command("list")
def calc_list(
    include_experimental: bool = typer.Option(
        True, "--experimental/--no-experimental",
        help="是否列出实验性公式（experimental=True 键，默认列出并打 [实验] 标签）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """列出全部计算器与参数表（实验键带【实验】标签，运行需 --allow-experimental）。"""
    from rfauto.service.calculator_service import list_calculators

    result = list_calculators(include_experimental=include_experimental)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False))
        raise typer.Exit(code=0)
    for calc in result["calculators"]:
        tag = "  [yellow][实验][/yellow]" if calc.get("experimental") else ""
        console.print(f"[bold cyan]{calc['name']}[/bold cyan]{tag}  {calc['description']}")
        for p in calc["params"]:
            tag = "必填" if p["required"] else "可选"
            console.print(f"    {p['name']}  [dim]{p['desc']}（{tag}）[/dim]")
    n_exp = int(result.get("n_experimental") or 0)
    if n_exp:
        shown = "已列出" if include_experimental else "已隐藏（--experimental 查看）"
        console.print(
            f"[dim]实验性公式 {n_exp} 个（{shown}）：默认拒跑，"
            f"rfauto calc run --allow-experimental 或配置 "
            f"calculators.allow_experimental: true 放行[/dim]")
    raise typer.Exit(code=0)


@calc_app.command("run")
def calc_run(
    name: str = typer.Argument(..., help="计算器名（rfauto calc list 查看）"),
    param: list[str] | None = typer.Option(None, "--param", "-p",  # noqa: B008
                                           help="参数 k=v（可重复）"),
    allow_experimental: bool | None = typer.Option(
        None, "--allow-experimental/--no-experimental",
        help="实验性公式放行开关：--allow-experimental 显式放行；"
             "--no-experimental 显式拒绝（优先于配置）；缺省读配置 "
             "calculators.allow_experimental / 环境变量 "
             "RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """执行计算器。

    示例：rfauto calc run microstrip_synthesis -p z0_ohm=50 -p freq_ghz=2.4
          -p epsilon_r=3.66 -p h_mm=0.508
    实验性公式（rfauto calc list 标【实验】）默认拒跑，需 --allow-experimental。
    """
    from rfauto.service.calculator_service import run_calculator

    params: dict = {}
    for item in param or []:
        key, sep, raw = item.partition("=")
        if not sep:
            console.print(f"[red]✗ --param 需要 k=v 形式: {item}[/red]")
            raise typer.Exit(code=1)
        params[key.strip()] = _coerce_param(raw.strip())

    result = run_calculator(name, params, allow_experimental=allow_experimental)
    if json_output:
        # JSON 信封统一走 _emit 出口：ok=False 失败信封 + 非零退出码（w1a followUp ①：
        # 脚本消费方靠 exit code 判成败而非解析信封；run_calculator 失败恒带 error，
        # 信封形状与直出完全一致，非 JSON 分支保持人读渲染）
        _emit(result, f"计算器 {name} 执行失败", json_output=True)
        raise typer.Exit(code=0)
    elif result["ok"]:
        exp_tag = "  [yellow][实验][/yellow]" if result.get("experimental") else ""
        console.print(f"\n[bold]{name}[/bold]{exp_tag}")
        for key, value in result["result"].items():
            console.print(f"  {key}: [cyan]{value}[/cyan]")
    else:
        console.print(f"[red]✗ {result['error']}[/red]")
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


# ─── sparams-compare (E8 Touchstone 导入对比) ────────────────────────────────


@app.command("sparams-compare")
def sparams_compare_cmd(
    run_id: str = typer.Argument(..., help="基准 run（其 results/*.sNp 为基准曲线）"),
    file: list[str] | None = typer.Option(None, "--file", "-f",  # noqa: B008
                                          help="外部 Touchstone 文件（可多次）"),
    out: str | None = typer.Option(None, "--out", "-o",
                                   help="输出 PNG 路径（默认 runs/sparams_compare/<时间戳>.png）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """run 与外部 .sNp 的 S 参数叠画对比（dB，WP0.3/E8）。

    示例：rfauto sparams-compare 20260905_032407_e643d139 -f demo_BP.s2p
    """
    from rfauto.service.ui_service import sparams_compare_png

    result = sparams_compare_png(run_id, list(file or []), out_path=out)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["ok"]:
        console.print(
            f"[green]✓ 对比图已生成[/green] → [cyan]{result['png']}[/cyan]"
            f"（{result['n_curves']} 条曲线 / {result['n_sources']} 个来源）")
    else:
        console.print(
            f"[red]✗ {'; '.join(result.get('errors') or ['未知错误'])}[/red]")
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


# ─── vna (DP-11 VNA 测量闭环：En 相关性报告 + 离线回放，JSON 进出薄壳) ────────
# [DP-11 P2 纯插入 hunk：位置=sparams-compare 之后、ui 命令之前；只新增行]

vna_app = typer.Typer(help="VNA 测量闭环（DP-11：En 相关性报告 + 离线回放）")
app.add_typer(vna_app, name="vna")


@vna_app.command("en-report")
def vna_en_report_cmd(
    lab_s2p: str = typer.Argument(..., help="实测 Touchstone 文件"),
    ref_s2p: str = typer.Argument(..., help="仿真参考 Touchstone 文件"),
    traces: str = typer.Option("S11,S21", "--traces", "-t",
                               help="迹线名（逗号分隔）"),
    delta_t_c: float = typer.Option(None, "--delta-t-c", help="温差覆盖（°C）"),
    anchor_u_db: float = typer.Option(None, "--anchor-u-db",
                                      help="锚不确定度（U_sim 第一优先）"),
    hfss_residual_db: float = typer.Option(None, "--hfss-residual-db",
                                           help="HFSS 仲裁残差（U_sim 第二优先）"),
    markdown: str | None = typer.Option(None, "--markdown", "-m",
                                        help="Markdown 报告输出路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """En 计量学相关性报告（|En|≤1 满意；深谷自动切线性域，#370/#371）。"""
    from rfauto.service.vna_service import vna_en_report

    trace_list = tuple(t.strip() for t in traces.split(",") if t.strip())
    result = vna_en_report(
        lab_s2p, ref_s2p, traces=trace_list, delta_t_c=delta_t_c,
        anchor_uncertainty_db=anchor_u_db,
        hfss_residual_db=hfss_residual_db, markdown_path=markdown)
    if json_output:
        console.print_json(json.dumps(
            {k: v for k, v in result.items() if k != "markdown"},
            indent=2, ensure_ascii=False, default=str))
        if not result.get("ok"):
            raise typer.Exit(code=1)
        return
    if not result.get("ok"):
        for err in result.get("errors") or ["En 报告失败"]:
            console.print(f"[red]✗ {err}[/red]")
        raise typer.Exit(code=1)
    if markdown:
        console.print(f"[green]✓ En 报告[/green] → [cyan]{markdown}[/cyan]")
    else:
        from rich.markdown import Markdown

        console.print(Markdown(result.get("markdown", "")))


@vna_app.command("replay")
def vna_replay_offline_cmd(
    measured_s2p: str = typer.Argument(..., help="历史测量 Touchstone 文件"),
    sim_s2p: str | None = typer.Argument(None, help="仿真 Touchstone（缺省=自比对）"),
    threshold_db: float = typer.Option(3.0, "--threshold-db",
                                       help="相关性 dB 偏差阈值"),
    session: str | None = typer.Option(None, "--session",
                                       help="会话 JSONL 落盘路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """VNA 离线回放回归（mock 仪表 采集→校准→相关 全链，零硬件）。

    与顶层 ``vna-replay`` 命令互为别名（同一 service 链路）；退出码同口径：
    调用失败或相关性判读未过门（is_correlated=False）均 exit 1（E2-3 统一）。
    """
    from rfauto.service.vna_service import vna_replay

    result = vna_replay(measured_s2p, sim_s2p, threshold_db=threshold_db,
                        session_path=session)
    console.print_json(json.dumps(result, indent=2, ensure_ascii=False,
                                  default=str))
    if not result.get("ok"):
        raise typer.Exit(code=1)
    corr = result.get("correlation") or {}
    if corr and not corr.get("is_correlated", True):
        raise typer.Exit(code=1)


# ─── vna measure / vna calibrate（VI-1 孤儿接线批 W1-C 单元 10/11）────────────
# 单元 10：run_vna_measure 采集链（connect→扫频→capture→校准→AFR→落 run）。
# 真机 opt-in 语义：无 --address → dry-run 计划态信封（零连接零 subprocess，
# 本薄壳内构造计划，不触碰 adapter）；给 --address 才进真采集。
# 单元 11：vna_calibrate_standalone 独立校准/去嵌（SOLT/TRL/multiline，
# measurement 层视同 core 叶，service 既有先例）。


def _parse_freq_range(raw: str) -> tuple[float, float]:
    """"LO,HI" GHz 串 → (lo, hi) 浮点对（解析失败显式退出码 2）。"""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != 2:
        console.print(f"[red]✗ --freq-range-ghz 需要 LO,HI 两段: {raw}[/red]")
        raise typer.Exit(code=2)
    try:
        lo, hi = float(parts[0]), float(parts[1])
    except ValueError:
        console.print(f"[red]✗ --freq-range-ghz 值不是数字: {raw}[/red]")
        raise typer.Exit(code=2) from None
    if not lo < hi:
        console.print(f"[red]✗ --freq-range-ghz 需要 LO 小于 HI: {raw}[/red]")
        raise typer.Exit(code=2)
    return lo, hi


@vna_app.command("measure")
def vna_measure_cmd(
    address: str = typer.Option("", "--address",
                                help="仪器 VISA 地址（缺省= dry-run 计划态，零连接）"),
    model: str = typer.Option("librevna", "--model", help="仪表驱动模型"),
    freq_range: str = typer.Option("1.0,3.0", "--freq-range-ghz",
                                   help="扫频范围 LO,HI（GHz，逗号分隔）"),
    n_points: int = typer.Option(201, "--n-points", help="扫频点数"),
    ifbw: float = typer.Option(1000.0, "--ifbw-hz", help="中频带宽（Hz）"),
    calkit: str = typer.Option("", "--calkit", help="校准套件 ID（meta 留痕）"),
    twoxthru: str = typer.Option("", "--twoxthru",
                                 help="2x-thru 实测件（给定时做 AFR 去嵌）"),
    visa_library: str = typer.Option("", "--visa-library",
                                     help="VISA 后端覆盖（pyvisa-sim 冒烟用）"),
    ref_s2p: str | None = typer.Option(None, "--ref",
                                       help="仿真参考 Touchstone（给定时附带 En 报告）"),
    runs_dir: str | None = typer.Option(None, "--runs-dir",
                                        help="run 落盘根目录（缺省 runs）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """VNA 测量采集 run（真机 opt-in：无 --address 时只出 dry-run 计划信封）。

    示例：rfauto vna measure --freq-range-ghz 1.0,3.0          （dry-run 计划态）
          rfauto vna measure --address TCPIP0::192.168.1.10::hislip0::INSTR
    """
    from rfauto.service.vna_service import run_vna_measure

    freq_range_ghz = _parse_freq_range(freq_range)
    if not address:
        # 真机 opt-in 门：缺地址=计划态（零连接零 subprocess，不触碰 adapter）
        plan = {
            "ok": True,
            "dry_run": True,
            "command": "vna measure",
            "plan": {
                "address": "",
                "model": model,
                "freq_range_ghz": list(freq_range_ghz),
                "n_points": int(n_points),
                "ifbw_hz": float(ifbw),
                "calkit_id": calkit,
                "twoxthru_path": twoxthru,
                "visa_library": visa_library,
                "ref_s2p": ref_s2p,
                "runs_dir": runs_dir,
                "note": "无 --address → dry-run 计划态（零连接零 subprocess）；"
                        "给 --address 即按此计划真机采集",
            },
        }
        if not json_output:
            console.print("[yellow]◇ dry-run 计划态（零连接）[/yellow] "
                          "给 --address 进真机采集；计划参数：")
            for k, v in plan["plan"].items():
                console.print(f"  {k}: [cyan]{v}[/cyan]")
            raise typer.Exit(code=0)
        _emit(plan, "dry-run 计划构造失败", json_output=True)
        raise typer.Exit(code=0)
    result = run_vna_measure(
        address=address, model=model, freq_range_ghz=freq_range_ghz,
        n_points=int(n_points), ifbw_hz=float(ifbw), calkit_id=calkit,
        twoxthru_path=twoxthru, visa_library=visa_library,
        ref_s2p=ref_s2p, runs_dir=runs_dir)
    if json_output:
        _emit(result, "VNA 测量失败", json_output=True)
        raise typer.Exit(code=0)
    if not result.get("ok"):
        _emit(result, "VNA 测量失败", json_output=False)
        raise typer.Exit(code=1)
    console.print(f"[green]✓ 测量 run 落盘[/green] → "
                  f"[cyan]{result.get('run_dir')}[/cyan]")
    raise typer.Exit(code=0)


@vna_app.command("calibrate")
def vna_calibrate_cmd(
    measurements: list[str] = typer.Option(  # noqa: B008
        None, "--measurements", "-m",
        help="标准件实测（类型=文件，可多次；顺序由方法契约自动排位）"),
    calkit: str = typer.Option(..., "--calkit",
                               help="校准套件 ID（knowledge/calkits/catalog.yaml 键）"),
    calkit_dir: str | None = typer.Option(None, "--calkit-dir",
                                          help="catalog 目录覆盖（缺省仓内置）"),
    dut: str | None = typer.Option(None, "--dut", help="待去嵌 DUT Touchstone"),
    out: str | None = typer.Option(None, "--out", help="校准后网络落盘 Touchstone 路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """独立软件校准/去嵌（SOLT/TRL/multiline 全方法，零硬件零连接）。

    示例：rfauto vna calibrate --calkit wl_2g5_solt_smoke -m short=s.s2p
          -m open=o.s2p -m load=l.s2p -m through=t.s2p --dut dut.s2p
    """
    from rfauto.service.vna_service import vna_calibrate_standalone

    if not measurements:
        _emit({"ok": False,
               "errors": ["--measurements 至少给一条（类型=文件，可多次）"]},
              "缺少 --measurements", json_output=json_output)
        raise typer.Exit(code=1)
    pairs: dict[str, str] = {}
    for item in measurements:
        key, sep, val = item.partition("=")
        if not sep or not key.strip() or not val.strip():
            _emit({"ok": False,
                   "errors": [f"--measurements 需 类型=文件 形式: {item}"]},
                  "参数形式错误", json_output=json_output)
            raise typer.Exit(code=1)
        pairs[key.strip()] = val.strip()
    result = vna_calibrate_standalone(
        pairs, calkit, calkit_dir=calkit_dir, dut=dut, out_path=out)
    _emit(result, "校准失败", json_output=json_output)
    if not json_output and result.get("ok"):
        cal = result.get("calibration") or {}
        console.print(f"[green]✓ 校准完成[/green] method={cal.get('method')} "
                      f"is_calibrated={cal.get('is_calibrated')}")
        if result.get("written"):
            console.print(f"  校准网络 → [cyan]{result['written']}[/cyan]")
    if not result.get("ok"):
        raise typer.Exit(code=1)
