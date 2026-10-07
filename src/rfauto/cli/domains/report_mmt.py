"""reports/mmt/nfmeas/nfc/sar/si 子应用（报告与 MMT/nf 测量族）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── report（DP-13 U1 双输出报告链：typst PDF + plotly 自包含 HTML 同源双出） ──

report_app = typer.Typer(help="双输出报告链（DP-13 U1：run → 同一报告模型双出 PDF+HTML）")
app.add_typer(report_app, name="reports")  # U1 双输出报告（复数名避开既有顶层 `report` 旧 docs/html 导出命令——同名遮蔽事故修复 2026-09-25）


@report_app.command("render")
def report_render_cmd(
    run_dir: str = typer.Argument(..., help="run 目录（meta/verdict/sparams 任一在场即可，缺如实降级）"),
    out_dir: str = typer.Option("", "--out-dir", help="输出目录（缺省 run_dir/_report）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """渲染 run 报告：同一报告模型（rfauto-report/v1）双出 typst PDF + plotly 自包含 HTML。

    四段式大纲：标识引用/方法配置/数据与判据（消费 knowledge/criteria/v2，
    无适用判据如实 none-provided）/结论与异常；全部数字带 provenance。

    示例：rfauto reports render runs/ratrace_03mm_sample --out-dir out/report
    """
    from rfauto.service.report_render import render_run_report

    result = render_run_report(run_dir, out_dir=out_dir or None)
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error') or '报告渲染失败'}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return
    console.print(f"[green]✓[/green] PDF : {result['pdf_path']}")
    console.print(f"[green]✓[/green] HTML: {result['html_path']}")
    console.print(
        f"  schema={result['schema']}  criteria={result['criteria_status']}  "
        f"verdict={result.get('verdict')}  异常 {result.get('n_anomalies')} 条")


# ─── mmt（DP-1：自研 RWG/SIW 解析模基 MMT（GSM）秒级求解）───────────────────

mmt_app = typer.Typer(
    help="RWG/SIW 模基 MMT 求解（DP-1：段表 mm + 频网 → 50Ω S 参数，秒级零外部进程）")
app.add_typer(mmt_app, name="mmt")


@mmt_app.command("solve")
def mmt_solve(
    sections: str = typer.Option("", "--sections", help="段表 JSON 内联串或 @文件路径（uniform/hstep/iris，mm 口径）"),
    freqs: str = typer.Option("", "--freqs-ghz", help="逗号分隔频点 GHz（与段表内 freqs_ghz 二选一）"),
    eps_r: float = typer.Option(1.0, "--eps-r", help="缺省相对介电常数（段内可覆盖）"),
    tan_d: float = typer.Option(0.0, "--tan-d", help="缺省损耗正切"),
    z0_ref: float = typer.Option(50.0, "--z0-ref", help="端口参考阻抗 Ω"),
    n_modes_ref: int = typer.Option(15, "--n-modes-ref", help="最窄侧基准模式数"),
    work_dir: str = typer.Option(None, "--work-dir", help="产物目录（缺省临时目录）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """MMT 段表求解（JSON 进出薄壳，零逻辑转发 mmt_service.solve_mmt）。

    示例：rfauto mmt solve --sections '@chain.json' --freqs-ghz 8,10,12
    """
    import json as _json

    from rfauto.service.mmt_service import solve_mmt, solve_mmt_from_file

    try:
        if sections.startswith("@"):
            result = solve_mmt_from_file(sections[1:], work_dir=work_dir)
        else:
            payload = _json.loads(sections) if sections else {}
            if freqs:
                payload["freqs_ghz"] = [float(x) for x in freqs.split(",") if x.strip()]
            payload.setdefault("eps_r", eps_r)
            payload.setdefault("tan_d", tan_d)
            payload.setdefault("z0_ref", z0_ref)
            if n_modes_ref != 15:
                payload.setdefault("mode_policy", {})["n_modes_ref"] = n_modes_ref
            result = solve_mmt(payload, work_dir=work_dir)
    except json.JSONDecodeError as exc:
        console.print(f"[red]✗ sections JSON 解析失败: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('errors', ['失败'])}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False))
        return
    color = "green" if result.get("converged") else "yellow"
    console.print(f"[{color}]● MMT 求解[/] converged={result.get('converged')} "
                  f"determined={result.get('n_determined')}/{result.get('n_determined', 0) + result.get('n_undetermined', 0)}")
    console.print(f"  产物: {result.get('work_dir')}")


@app.command("compose")
def compose_cmd(
    netlist_file: str = typer.Argument(..., help="netlist YAML 文件（rfauto-netlist-v1 三段式）"),
    out_dir: str = typer.Option(..., "--out-dir", "-o", help="产物目录（simulation.py + compose_meta.json + netlist.yaml）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """模板几何组合（DP-8）：netlist YAML → 单一 simulation.py（布局合并路线）。

    netlist 三段式：instances（模板+参数）/connections（pin 吸附摆位）/
    exposed_ports（FDTD 端口重编 1..M）+ band/substrate/global_params。
    首例模板：siw、msl_siw_taper（opt-in 注册）；守卫 P1-P5（位置共点/
    方向对向/阻抗/参考面/截面）+ D1-D6（域合并/结缝导体/网格衔接/端口重编/
    边界预算/一致性），失败显式 ValueError 报双 pin id+坐标+差值。

    示例：rfauto compose netlist.yaml --out-dir runs/compose_out
    """
    from rfauto.service.compose_service import compose_write_from_yaml_file

    result = compose_write_from_yaml_file(netlist_file, out_dir)
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error') or '组合失败'}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result["result"], ensure_ascii=False))
        raise typer.Exit(code=0)
    r = result["result"]
    console.print(f"[green]✓ 组合产物已落盘[/green] {r['out_dir']}")
    console.print(f"  simulation.py   {r['script_path']}")
    console.print(f"  compose_meta    {r['meta_path']}（render sha256={r['render_sha256'][:12]}…）")
    g = r.get("guards") or {}
    console.print("  守卫: " + " ".join(
        f"{k}={v}" for k, v in sorted(g.items())))


@app.command("compose-templates")
def compose_templates_cmd(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """列出已注册组合契约模板与 pin schema（DP-8 opt-in 台账）。"""
    from rfauto.service.compose_service import list_composable_templates

    result = list_composable_templates()
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error') or '未知错误'}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result["result"], ensure_ascii=False))
        raise typer.Exit(code=0)
    r = result["result"]
    table = Table(title=f"组合契约模板（{r['n_templates']} 个，DP-8 opt-in）")
    table.add_column("template", style="cyan")
    table.add_column("pin")
    table.add_column("port_type")
    table.add_column("z_ref_ohm")
    table.add_column("direction")
    for t in r["templates"]:
        pins = t.get("port_pins") or []
        first = True
        for p in pins:
            table.add_row(
                t["template"] if first else "",
                str(p.get("pin_id")),
                str(p.get("port_type")),
                repr(p.get("z_ref_ohm")),
                repr(p.get("direction")),
            )
            first = False
        if not pins:
            table.add_row(t["template"], "-", "-", "-", "-")
    console.print(table)


# ─────────────────────────────────────────────────────────────────────────────
# 附：tests 门用示例 netlist 可由
#   python -c "from rfauto.service.compose_service import load_golden_netlist as f; print(f('siw_chain')['result'])"
# 取得（GOLDEN_NETLISTS 单一事实源）。


# ─── nfmeas / nfc / sar（DP-18 C10 迷你件：近场变换/.ffs 视图、NFC 线圈闭式、SAR 后处理）──

nfmeas_app = typer.Typer(help="近场测量变换与 .ffs 视图（DP-18 C10a）")
app.add_typer(nfmeas_app, name="nfmeas")

@nfmeas_app.command("ffs-info")
def nfmeas_ffs_info_cmd(
    path: str = typer.Argument(..., help=".ffs ASCII 路径"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 直出，旗标为归一兼容位）"),
) -> None:
    """审计 .ffs 头（频率/三功率/网格规模），不落全量复矩阵。"""
    import json as _json

    from rfauto.service.nf_measurement_service import ffs_info
    typer.echo(_json.dumps(ffs_info(path), ensure_ascii=False, indent=2))

@nfmeas_app.command("nf2ff")
def nfmeas_nf2ff_cmd(
    grid_npz: str = typer.Argument(..., help="近场栅格 npz（x_m/y_m/freq_hz/ex/ey/z0_m）"),
    window: str = typer.Option("kaiser", help="kaiser/hann/none"),
    beta: float = typer.Option(3.0, help="Kaiser β"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 直出，旗标为归一兼容位）"),
) -> None:
    """平面近场 2D 复场 → 远场方向图（dB 归一 JSON）。"""
    import json as _json

    import numpy as np

    from rfauto.core.nf_transform import NearFieldGrid, planar_nf_to_farfield
    d = np.load(grid_npz)
    out = planar_nf_to_farfield(
        NearFieldGrid(x_m=d["x_m"], y_m=d["y_m"], freq_hz=float(d["freq_hz"]),
                      ex=d["ex"], ey=d["ey"], z0_m=float(d.get("z0_m", 0.0))),
        window=window, kaiser_beta=beta)
    typer.echo(_json.dumps({
        "theta_deg": out["theta_deg"].tolist(), "phi_deg": out["phi_deg"].tolist(),
        "pattern_db": [[None if v != v else round(float(v), 4) for v in row]
                       for row in out["pattern_db"]],
        "window": out["window"], "validity_max_deg": out["validity_max_deg"]},
        ensure_ascii=False, indent=2))

nfc_app = typer.Typer(help="NFC/WPC 平面螺旋线圈闭式（DP-18 C10b）")
app.add_typer(nfc_app, name="nfc")

@nfc_app.command("evaluate")
def nfc_evaluate_cmd(shape: str, n_turns: float, d_out_mm: float,
                     w_um: float, s_um: float,
                     json_output: bool = typer.Option(
                         False, "--json",
                         help="JSON 直出兼容位（本命令缺省即 JSON）")) -> None:
    """Mohan 三式电感评估（nH/μm 输入口径）。"""
    import json as _json

    from rfauto.service.nfc_coil_service import coil_evaluate
    typer.echo(_json.dumps(coil_evaluate(shape, n_turns, d_out_mm * 1e-3,
                                         w_um * 1e-6, s_um * 1e-6),
                           ensure_ascii=False, indent=2))

@nfc_app.command("synth")
def nfc_synth_cmd(target_l_nh: float, shape: str, n_turns: float,
                  w_um: float, s_um: float,
                  expression: str = typer.Option("current_sheet"),
                  json_output: bool = typer.Option(
                      False, "--json",
                      help="JSON 直出兼容位（本命令缺省即 JSON）")) -> None:
    """目标电感 → 外径反解（二分 + 回代自洽）。"""
    import json as _json

    from rfauto.service.nfc_coil_service import coil_synthesize
    typer.echo(_json.dumps(coil_synthesize(target_l_nh * 1e-9, shape, n_turns,
                                           w_um * 1e-6, s_um * 1e-6,
                                           expression=expression),
                           ensure_ascii=False, indent=2))

@nfc_app.command("q")
def nfc_q_cmd(f_mhz: float, l1_nh: float, r1_ohm: float,
              m_nh: float = typer.Option(0.0), l2_nh: float = typer.Option(0.0),
              r2_ohm: float = typer.Option(0.0),
              json_output: bool = typer.Option(
                  False, "--json",
                  help="JSON 直出兼容位（本命令缺省即 JSON）")) -> None:
    """有载/无载 Q 报告面（互感 T 模型精确式）。"""
    import json as _json

    from rfauto.service.nfc_coil_service import coil_q
    typer.echo(_json.dumps(coil_q(f_mhz * 1e6, l1_nh * 1e-9, r1_ohm,
                                  m_nh * 1e-9, l2_nh * 1e-9, r2_ohm),
                           ensure_ascii=False, indent=2))

sar_app = typer.Typer(help="SAR 合规后处理（DP-18 C10c）")
app.add_typer(sar_app, name="sar")

@sar_app.command("report")
def sar_report_cmd(
    # help 文本禁裸方括号：rich 把 [/x] 当关闭标记，--help 渲染直接
    # MarkupError（E2-1，#305 族"help 特殊字符炸 help"）；表述去括号取齐
    # 同文件其他 help 惯例。
    field_npz: str = typer.Argument(..., help="场网格 npz（e_re/e_im/rho，可选 sigma/voxel_m）"),
    mass_g: str = typer.Option("1,10", help="逗号分隔质量档（g）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 直出，旗标为归一兼容位）"),
) -> None:
    """1g/10g 立方平均 + 峰值定位 + 分布（62704-1 简化档，coverage 如实）。"""
    import json as _json

    from rfauto.service.sar_service import sar_load_field_npz
    typer.echo(_json.dumps(sar_load_field_npz(field_npz),
                           ensure_ascii=False, indent=2))


# ─── si（df7 T2 SI 通道报告：无源性/因果性/TDR/COM 一键通道报告薄壳） ─────────
# 零逻辑转发 service/si_channel_service（规则 4）；markdown 渲染在 service 层
# （前端只渲染原则 #90）；路径参数一律 str 注解（#269 B008）。

si_app = typer.Typer(help="SI 通道报告（df7 T2：无源性/因果性/TDR/COM，纯后处理）")
app.add_typer(si_app, name="si")


@si_app.command("report")
def si_report_cmd(
    source: str = typer.Argument(..., help="Touchstone 文件（.sNp）或 run 目录（sparams.csv/Touchstone 产物）"),
    output_format: str = typer.Option("json", "--format", "-f", help="输出格式: json|markdown"),
    passivity_tol: float = typer.Option(0.01, "--passivity-tol", help="无源性容差（max σmax ≤ 1+tol）"),
    causality_threshold: float = typer.Option(0.02, "--causality-threshold", help="负时间能量占比阈值"),
    pre_cursor_guard_ns: float = typer.Option(1.0, "--pre-cursor-guard-ns", help="因果性循环尾窗宽度 ns"),
    tdr_window_ns: float = typer.Option(2.0, "--tdr-window-ns", help="TDR 统计窗 ns"),
    fext: list[str] | None = typer.Option(None, "--fext", help="COM 远端串扰 4 端口文件（可重复）"),  # noqa: B008
    nxt: list[str] | None = typer.Option(None, "--next", help="COM 近端串扰 4 端口文件（可重复）"),  # noqa: B008
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；缺省 --format json 即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """SI 通道一键报告（JSON 进出薄壳；COM 段 4 端口文件可用，缺装如实降级）。"""
    from rfauto.service.si_channel_service import render_si_channel_markdown, si_channel_report

    fmt = (output_format or "json").strip().lower()
    if fmt not in ("json", "markdown"):
        console.print(f"[red]✗ --format 须为 json|markdown，实际 {output_format!r}[/red]")
        raise typer.Exit(code=2)
    result = si_channel_report(
        source,
        passivity_tol=passivity_tol,
        causality_threshold=causality_threshold,
        pre_cursor_guard_ns=pre_cursor_guard_ns,
        tdr_window_ns=tdr_window_ns,
        fext_paths=list(fext) if fext else None,
        next_paths=list(nxt) if nxt else None,
    )
    if fmt == "markdown":
        if not result.get("ok"):
            console.print("[red]✗ SI 通道报告失败[/red]")
            for err in result.get("errors") or []:
                console.print(f"  [red]- {err}[/red]")
            raise typer.Exit(code=1)
        typer.echo(render_si_channel_markdown(result))
        return
    # VI-5 W6-B：json 格式缺省即信封直出，--json 为归一兼容位（两形态同输出）。
    _emit(result, "SI 通道报告失败", json_output=True)


@si_app.command("mixed")
def si_mixed_cmd(
    source: str = typer.Argument(..., help="4 端口 Touchstone（.s4p）或 run 目录（sparams.csv/Touchstone）"),
    ports: str = typer.Option("1,2", "--ports", help="第一差分对（1 起物理口号 p+,p-；第二对缺省取余下两口升序）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """混合模 S 参数指标（QW-1：skrf se2gmm 薄封装；差分插损/回损/共模/模式转换）。

    示例：rfauto si mixed link.s4p --ports 1,2
    """
    from rfauto.service.si_channel_service import mixed_mode_metrics

    try:
        pair = tuple(int(v.strip()) for v in str(ports).split(",") if v.strip())
    except ValueError:
        console.print(f"[red]✗ --ports 须为逗号分隔整数，实际 {ports!r}[/red]")
        raise typer.Exit(code=2) from None
    # VI-5 W6-B：缺省即 _emit 信封直出，旗标为归一兼容位（两形态同输出）。
    _emit(mixed_mode_metrics(source, pair), "混合模指标失败", json_output=True)
