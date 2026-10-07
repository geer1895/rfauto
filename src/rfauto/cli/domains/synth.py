"""syn/budget/cascade/array 子应用（综合与系统级预算薄壳）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.table import Table

from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── syn (E6a 微带综合) ───────────────────────────────────────────────────────

syn_app = typer.Typer(help="微带线综合（E6a）")
app.add_typer(syn_app, name="syn")


@syn_app.command("mline")
def syn_mline(
    z0: float = typer.Argument(..., help="目标特性阻抗 (Ω)"),
    freq: float = typer.Option(2.4, "--freq", "-f", help="频率 (GHz)"),
    stackup: str = typer.Option(
        "rogers4350b_h0.508", "--stackup", "-s", help="层叠名称 (materials.yaml 键)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """微带线综合：目标阻抗 → 线宽（Hammerstad-Jensen + brentq 反解）。

    示例：rfauto syn mline 35.35 --freq 2.4 --stackup rogers4350b_h0.508
    """
    from rfauto.core.synthesis import synthesize_mline

    try:
        result = synthesize_mline(z0, freq, stackup)
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(code=1) from None
    except KeyError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(code=1) from None

    if json_output:
        console.print_json(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        status_color = "green" if result.status == "ok" else "yellow"
        console.print(f"\n[bold]微带线综合结果[/bold] ({result.stackup_name} @ {result.freq_ghz} GHz)")
        console.print(f"  目标阻抗: {result.z0_target:.2f} Ω")
        console.print(f"  线宽:     [cyan]{result.width_mm:.4f} mm[/cyan]")
        console.print(f"  实际阻抗: {result.z0_actual:.2f} Ω")
        console.print(f"  εeff:     {result.epsilon_eff:.4f}"
                      f"（来源 {result.er_eff_source}，skrf {result.skrf_version}）")
        console.print(f"  ΔZ0:      {result.delta_z0:.4f} Ω")
        console.print(f"  状态:     [{status_color}]{result.status}[/{status_color}]")

        if result.status == "needs_calibration":
            console.print("\n[yellow]⚠ 回代偏差>0.5Ω，建议校准。[/yellow]")
        if result.status == "er_eff_fallback":
            console.print("\n[yellow]⚠ εeff 走体介电常数兜底（skrf 属性缺失），"
                          "λ 系长度不可信，建议核对 skrf 版本。[/yellow]")

    raise typer.Exit(code=0)


@syn_app.command("wilkinson")
def syn_wilkinson(
    f0: float = typer.Option(2.4, "--f0", help="中心频率 (GHz)"),
    z0: float = typer.Option(50.0, "--z0", help="特性阻抗 (ohm)"),
    stackup: str = typer.Option("rogers4350b_h0.508", "--stackup", "-s", help="层叠名称"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """Wilkinson 功分器综合：f0 + Z0 → arm_len + series_w + shunt_w + 配方草稿。

    方向 8a 验收口径：闭式初值与人工设计值偏差 <10％。
    """
    from rfauto.core.synthesis import synthesize_wilkinson
    result = synthesize_wilkinson(f0_ghz=f0, z0_ohm=z0, stackup_name=stackup)
    if json_output:
        import dataclasses
        console.print_json(json.dumps(dataclasses.asdict(result), indent=2, ensure_ascii=False, default=str))
    else:
        console.print(f"[bold]Wilkinson 综合结果[/bold] (f0={f0}GHz, Z0={z0}ohm)")
        console.print(f"  arm_len:   [cyan]{result.params['arm_len_mm']:.2f} mm[/cyan]")
        console.print(f"  series_w:  [cyan]{result.params['series_w_mm']:.3f} mm[/cyan]")
        console.print(f"  shunt_w:   [cyan]{result.params['shunt_w_mm']:.3f} mm[/cyan]")
        for note in result.notes:
            console.print(f"  {note}")


@syn_app.command("branchline")
def syn_branchline(
    f0: float = typer.Option(2.4, "--f0", help="中心频率 (GHz)"),
    z0: float = typer.Option(50.0, "--z0", help="特性阻抗 (ohm)"),
    stackup: str = typer.Option("rogers4350b_h0.508", "--stackup", "-s", help="层叠名称"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """Branchline coupler 综合：f0 + Z0 → arm_len + series_w + shunt_w + 配方草稿。"""
    from rfauto.core.synthesis import synthesize_branchline
    result = synthesize_branchline(f0_ghz=f0, z0_ohm=z0, stackup_name=stackup)
    if json_output:
        import dataclasses
        console.print_json(json.dumps(dataclasses.asdict(result), indent=2, ensure_ascii=False, default=str))
    else:
        console.print(f"[bold]Branchline 综合结果[/bold] (f0={f0}GHz)")
        console.print(f"  arm_len:   [cyan]{result.params['arm_len_mm']:.2f} mm[/cyan]")
        console.print(f"  series_w:  [cyan]{result.params['series_w_mm']:.3f} mm[/cyan] (35.35ohm)")
        console.print(f"  shunt_w:   [cyan]{result.params['shunt_w_mm']:.3f} mm[/cyan] (50ohm)")
        for note in result.notes:
            console.print(f"  {note}")


@syn_app.command("patch")
def syn_patch(
    f0: float = typer.Option(2.4, "--f0", help="中心频率 (GHz)"),
    er: float = typer.Option(3.66, "--er", help="介电常数"),
    h: float = typer.Option(0.508, "--h", help="基板厚度 (mm)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """矩形贴片天线综合（Hammerstad 模型）：f0 + er + h → patch_len + patch_w + feed_offset。"""
    from rfauto.core.synthesis import synthesize_patch
    result = synthesize_patch(f0_ghz=f0, er=er, h_mm=h)
    if json_output:
        import dataclasses
        console.print_json(json.dumps(dataclasses.asdict(result), indent=2, ensure_ascii=False, default=str))
    else:
        console.print(f"[bold]Patch 综合结果[/bold] (f0={f0}GHz, er={er}, h={h}mm)")
        console.print(f"  patch_len:    [cyan]{result.params['patch_len_mm']:.2f} mm[/cyan]")
        console.print(f"  patch_w:      [cyan]{result.params['patch_w_mm']:.2f} mm[/cyan]")
        console.print(f"  feed_offset:  [cyan]{result.params['feed_offset_mm']:.2f} mm[/cyan]")
        for note in result.notes:
            console.print(f"  {note}")


@syn_app.command("bpf")
def syn_bpf(
    order: int = typer.Option(..., "--order", "-n", help="阶数 N（≥1）"),
    f0: float = typer.Option(2.4, "--f0", help="中心频率 (GHz)"),
    fbw: float = typer.Option(0.1, "--fbw", help="相对带宽 (0,1]"),
    rl: float = typer.Option(20.0, "--rl", help="带内回波损耗 (dB)"),
    tz: list[float] | None = typer.Option(None, "--tz",  # noqa: B008
                                          help="传输零点频率 GHz（可重复；须在阻带，±对口径）"),
    topology: str = typer.Option("folded", "--topology", "-t", help="folded | arrow"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """C13 带通滤波器综合：广义切比雪夫 → Cameron N+2 耦合矩阵 → folded/arrow。

    示例：rfauto syn bpf --order 5 --f0 2.4 --fbw 0.1 --rl 22 --tz 2.59 --json
    """
    from rfauto.core.synthesis import synthesize_bpf_model

    result = synthesize_bpf_model(order=order, f0_ghz=f0, fbw=fbw, rl_db=rl,
                                  transmission_zeros_ghz=list(tz or []),
                                  topology=topology)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["ok"]:
        console.print(f"[bold]BPF 综合结果[/bold] (N={order}, f0={f0}GHz, fbw={fbw}, "
                      f"RL={rl}dB, {topology})")
        console.print(f"  频响最大偏差: [cyan]{result['response_max_err']:.2e}[/cyan]"
                      f"  模式残留: {result['pattern_residual']:.2e}"
                      f"  交叉耦合族: {result['cross_family']}")
        for key, value in result["nominal"].items():
            if isinstance(value, list) or value != 0:
                console.print(f"  {key}: [cyan]{value}[/cyan]")
        for note in result["notes"]:
            console.print(f"  {note}")
    else:
        console.print(f"[red]✗ {'; '.join(result.get('errors') or ['未知错误'])}[/red]")
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


# ─── budget (E8c 链路预算) ─────────────────────────────────────────────────────

budget_app = typer.Typer(help="链路预算（E8c）")
app.add_typer(budget_app, name="budget")


@budget_app.command("run")
def budget_run(
    catalog: str = typer.Option("parts/catalog.yaml", "--catalog", "-c", help="器件目录"),
    chain: list[str] = typer.Argument(..., help="级联器件名（空格分隔）"),  # noqa: B008
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """链路预算：Friis 噪声级联 + 增益/P1dB 预算。

    示例：rfauto budget run lna_2ghz lowpass_filter_2ghz mixer_2ghz
    """
    from rfauto.core.block_spec import DeviceCatalog
    from rfauto.core.budget import LinkBudget

    try:
        dev_catalog = DeviceCatalog.from_yaml(catalog)
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(code=1) from None

    budget = LinkBudget()
    for name in chain:
        try:
            spec = dev_catalog.get(name)
        except KeyError as e:
            console.print(f"[red]✗ {e}[/red]")
            raise typer.Exit(code=1) from None
        budget.add_stage(
            name=name,
            gain_db=spec.gain_db or -(spec.conversion_loss_db or 0),
            nf_db=spec.nf_db or spec.conversion_loss_db or 0,
            p1db_dbm=spec.p1db_dbm,
            oip3_dbm=spec.oip3_dbm,
        )

    result = budget.compute()

    if json_output:
        console.print_json(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        console.print("\n[bold]链路预算结果[/bold]")
        table = Table(title="逐级预算")
        table.add_column("级", style="cyan")
        table.add_column("增益(dB)", justify="right")
        table.add_column("NF(dB)", justify="right")
        table.add_column("累积增益(dB)", justify="right")
        table.add_column("累积NF(dB)", justify="right")
        for s in result.stages:
            table.add_row(
                s.name,
                f"{s.gain_db:.1f}",
                f"{s.nf_db:.1f}",
                f"{s.cumulative_gain_db:.1f}",
                f"{s.cumulative_nf_db:.1f}",
            )
        console.print(table)
        console.print(f"\n级联增益: [cyan]{result.cascade_gain_db:.1f} dB[/cyan]")
        console.print(f"级联 NF:  [cyan]{result.cascade_nf_db:.1f} dB[/cyan]")
        if result.cascade_p1db_dbm is not None:
            console.print(f"级联 P1dB: [cyan]{result.cascade_p1db_dbm:.1f} dBm[/cyan]")
        if result.cascade_iip3_dbm is not None:
            console.print(f"级联 IIP3: [cyan]{result.cascade_iip3_dbm:.1f} dBm[/cyan]")
        if result.cascade_oip3_dbm is not None:
            console.print(f"级联 OIP3: [cyan]{result.cascade_oip3_dbm:.1f} dBm[/cyan]")

    raise typer.Exit(code=0)


# ─── cascade (DP-5 系统级预算引擎 + 杂散搜索) ──────────────────────────────

cascade_app = typer.Typer(help="系统级级联预算+混频杂散搜索（DP-5）")
app.add_typer(cascade_app, name="cascade")


def _load_stage_list(stages_file: str) -> list[dict]:
    """读 stage 列表 JSON（文件或 '-'=stdin），失败显式退出。"""
    try:
        text = sys.stdin.read() if stages_file == "-" else Path(stages_file).read_text(
            encoding="utf-8")
        stages = json.loads(text)
    except FileNotFoundError:
        console.print(f"[red]✗ stage 文件不存在: {stages_file}[/red]")
        raise typer.Exit(code=1) from None
    except (json.JSONDecodeError, OSError) as e:
        console.print(f"[red]✗ stage 文件读取失败: {e}[/red]")
        raise typer.Exit(code=1) from None
    if not isinstance(stages, list) or not stages:
        console.print("[red]✗ stage 文件须为非空 JSON 数组（按信号流向排序）[/red]")
        raise typer.Exit(code=1)
    return stages


@cascade_app.command("budget")
def cascade_budget_cmd(
    stages_file: str = typer.Argument(..., help="stage 列表 JSON 文件（'-'=stdin）"),
    snr_min_db: float = typer.Option(10.0, "--snr-min", help="解调最小 SNR (dB)"),
    rx_power_dbm: float = typer.Option(None, "--rx-power",
                                       help="接收功率 (dBm)，给定时输出链路裕量"),
    bw_hz: float = typer.Option(None, "--bw-hz",
                                help="系统噪声带宽 (Hz)，缺省取末级 bw_hz"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """级联预算：增益/Friis NF/IIP3·OIP3 级联/P1dB(经验幂和)/噪声底/SFDR/灵敏度。

    stage schema：{"type": "amp|mixer|filter|atten|cable", "gain_db": ..,
    "nf_db": .., "iip3_dbm": .., "p1db_dbm": .., "bw_hz": ..,
    "network_path": "..s2p"?, "il_freq_hz": ..?, "il_db": ..?}；
    filter/atten 插损来源=network_path（skrf 实取 S21）或常数 il_db，显式二选一。

    示例：rfauto cascade budget stages.json --rx-power -90 --bw-hz 1e6
    """
    from rfauto.service.cascade_service import cascade_budget_report

    stages = _load_stage_list(stages_file)
    result = cascade_budget_report(
        stages, snr_min_db=snr_min_db, rx_power_dbm=rx_power_dbm,
        bw_hz=bw_hz)
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error') or '未知错误'}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result["result"], ensure_ascii=False))
        raise typer.Exit(code=0)

    r = result["result"]
    table = Table(title=f"级联预算（{r['n_stages']} 级，DP-5）")
    table.add_column("#", justify="right", style="cyan")
    table.add_column("type")
    table.add_column("增益(dB)", justify="right")
    table.add_column("NF(dB)", justify="right")
    table.add_column("累积增益(dB)", justify="right")
    table.add_column("累积NF(dB)", justify="right")
    table.add_column("插损来源")
    for s in r["stages"]:
        table.add_row(
            str(s["index"] + 1), str(s["type"]),
            f"{s['gain_db']:.2f}", f"{s['nf_db']:.2f}",
            f"{s['cum_gain_db']:.2f}", f"{s['cum_nf_db']:.2f}",
            str(s.get("il_source", "-")))
    console.print(table)
    console.print(f"总增益: [cyan]{r['gain_total_db']:.2f} dB[/cyan]   "
                  f"总 NF: [cyan]{r['nf_total_db']:.2f} dB[/cyan]")
    if r["iip3_total_dbm"] is not None:
        console.print(f"IIP3: [cyan]{r['iip3_total_dbm']:.2f} dBm[/cyan]   "
                      f"OIP3: [cyan]{r['oip3_total_dbm']:.2f} dBm[/cyan]   "
                      f"SFDR: [cyan]{r['sfdr_db']:.2f} dB[/cyan]")
    if r["p1db_out_dbm"] is not None:
        console.print(f"P1dB(经验幂和): [cyan]{r['p1db_out_dbm']:.2f} dBm[/cyan] (输出参考)")
    console.print(f"噪声底: [cyan]{r['noise_floor_dbm']:.2f} dBm[/cyan]   "
                  f"灵敏度: [cyan]{r['sensitivity_dbm']:.2f} dBm[/cyan]   "
                  f"(B={r['bw_hz']:.3g} Hz, T={r['t_kelvin']:.0f} K)")
    if r["link_margin_db"] is not None:
        console.print(f"链路裕量: [cyan]{r['link_margin_db']:.2f} dB[/cyan]")
    raise typer.Exit(code=0)


@cascade_app.command("spur")
def cascade_spur_cmd(
    f_rf_hz: float = typer.Option(..., "--rf", help="RF 中心频率 (Hz)"),
    f_lo_hz: float = typer.Option(..., "--lo", help="本振频率 (Hz)"),
    if_center_hz: float = typer.Option(None, "--if-center", help="IF 中心 (Hz)，缺省 |f_RF−f_LO|"),
    if_bw_hz: float = typer.Option(0.0, "--if-bw", help="目标带宽 (Hz)"),
    rf_bw_hz: float = typer.Option(0.0, "--rf-bw", help="RF 信号带宽 (Hz)"),
    max_order: int = typer.Option(7, "--max-order", help="最大阶数 m+n"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """混频杂散落带搜索：f_spur=|m·f_RF±n·f_LO| 枚举 + 矩形卷积落带判定。

    示例：rfauto cascade spur --rf 2.4e9 --lo 2.1e9 --if-bw 1e5
    """
    from rfauto.service.cascade_service import spur_search_report

    result = spur_search_report(
        f_rf_hz, f_lo_hz, if_center_hz=if_center_hz, if_bw_hz=if_bw_hz,
        rf_bw_hz=rf_bw_hz, max_order=max_order)
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error') or '未知错误'}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result["result"], ensure_ascii=False))
        raise typer.Exit(code=0)

    r = result["result"]
    in_band = [s for s in r["spurs"] if s["in_band"]]
    console.print(f"\n[bold]杂散产物表[/bold]（m+n≤{r['max_order']}，"
                  f"共 {r['n_products']} 产物，落带 {r['n_spurs_in_band']}）")
    table = Table(title=f"落带产物（IF 中心 {r['if_center_hz']:.6g} Hz）")
    table.add_column("m", justify="right", style="cyan")
    table.add_column("n", justify="right", style="cyan")
    table.add_column("边带", justify="center")
    table.add_column("阶", justify="right")
    table.add_column("f_spur (Hz)", justify="right")
    table.add_column("偏离 IF (Hz)", justify="right")
    table.add_column("危险")
    for s in in_band:
        table.add_row(str(s["m"]), str(s["n"]), s["side"], str(s["order"]),
                      f"{s['f_spur_hz']:.10g}", f"{s['offset_from_if_hz']:.6g}",
                      str(s["hazard"]))
    console.print(table)
    if not in_band:
        console.print("[green]无落带杂散产物[/green]")
    raise typer.Exit(code=0)


@cascade_app.command("plan")
def cascade_plan_cmd(
    f_rf_hz: float = typer.Option(..., "--rf", help="RF 中心频率 (Hz)"),
    if_lo_hz: float = typer.Option(..., "--if-lo", help="IF 扫掠下限 (Hz)"),
    if_hi_hz: float = typer.Option(..., "--if-hi", help="IF 扫掠上限 (Hz)"),
    side: str = typer.Option("low", "--side", help="注入侧 low|high"),
    n_points: int = typer.Option(201, "--points", help="网格点数"),
    if_bw_hz: float = typer.Option(0.0, "--if-bw", help="目标带宽 (Hz)"),
    max_order: int = typer.Option(7, "--max-order", help="最大阶数 m+n"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """IF 频率规划扫掠：候选 IF 逐点杂散判定 → spurious-free 窗口表。

    示例：rfauto cascade plan --rf 2.4e9 --if-lo 1e8 --if-hi 1e9 --points 401
    """
    from rfauto.service.cascade_service import if_plan_report

    result = if_plan_report(f_rf_hz, if_lo_hz=if_lo_hz, if_hi_hz=if_hi_hz,
                            side=side, n_points=n_points, if_bw_hz=if_bw_hz,
                            max_order=max_order)
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error') or '未知错误'}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result["result"], ensure_ascii=False))
        raise typer.Exit(code=0)

    r = result["result"]
    console.print(f"\n[bold]IF 规划扫掠[/bold]（{side} 侧注入，"
                  f"{r['n_points']} 点，spur-free {r['n_points_free']} 点）")
    table = Table(title="spurious-free 窗口（网格分辨率内）")
    table.add_column("起 (Hz)", justify="right", style="cyan")
    table.add_column("止 (Hz)", justify="right", style="cyan")
    table.add_column("点数", justify="right")
    for w in r["windows"]:
        table.add_row(f"{w['start_hz']:.10g}", f"{w['end_hz']:.10g}",
                      str(w["n_points"]))
    console.print(table)
    raise typer.Exit(code=0)


# ─── array (DP-4 阵列两档 AF 引擎，薄壳转发 array_service) ────────────────────

array_app = typer.Typer(help="阵列/相控阵两档方向图引擎（DP-4：快速档单元×AF；互耦档 P3 接口预留）")
app.add_typer(array_app, name="array")


def _load_array_request(request_file: str, label: str) -> dict:
    """读请求 JSON 对象（文件或 '-'=stdin），失败显式退出（薄壳专用）。"""
    try:
        text = sys.stdin.read() if request_file == "-" else Path(
            request_file).read_text(encoding="utf-8")
        payload = json.loads(text)
    except FileNotFoundError:
        console.print(f"[red]✗ {label} 文件不存在: {request_file}[/red]")
        raise typer.Exit(code=1) from None
    except (json.JSONDecodeError, OSError) as e:
        console.print(f"[red]✗ {label} 文件读取失败: {e}[/red]")
        raise typer.Exit(code=1) from None
    if not isinstance(payload, dict):
        console.print(f"[red]✗ {label} 须为 JSON 对象（见 service/array_service "
                      "模块 docstring 的请求 schema）[/red]")
        raise typer.Exit(code=1)
    return payload


@array_app.command("synthesize")
def array_synthesize_cmd(
    n: int = typer.Option(4, "--n", help="单元数（ula）"),
    law: str = typer.Option("uniform", "--law",
                            help="uniform|chebyshev|taylor|binomial|custom"),
    sll_db: float = typer.Option(-30.0, "--sll-db",
                                 help="chebyshev/taylor 副瓣目标（负 dB）"),
    spacing: float = typer.Option(0.5, "--spacing", help="单元间距 d/λ"),
    scan_deg: float = typer.Option(90.0, "--scan-deg", help="扫描角（z 轴 90=侧射）"),
    axis: str = typer.Option("z", "--axis", help="阵轴 z|x|y"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """闭式加权综合 + 快速档放行门（tier_gate：间距/扫描/栅瓣/耦合）。

    示例：rfauto array synthesize --n 4 --law chebyshev --sll-db -30
    """
    from rfauto.service.array_service import synthesize_array_weights

    result = synthesize_array_weights({
        "layout": "ula", "n_elements": n, "amplitude_law": law,
        "sidelobe_level_db": sll_db, "spacing_lambda": spacing,
        "scan_deg": scan_deg, "axis": axis,
    })
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error') or '未知错误'}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result["result"], ensure_ascii=False))
        raise typer.Exit(code=0)

    r = result["result"]
    table = Table(title=f"阵列加权综合（{r['law']}，N={r['n_elements']}，DP-4）")
    table.add_column("k", justify="right", style="cyan")
    table.add_column("幅度 w")
    for k, w in enumerate(r["weights"]):
        table.add_row(str(k), f"{w:.6f}")
    console.print(table)
    g = r["gates"]
    verdict = "[green]fast（放行）[/green]" if g["allowed"] else \
        "[red]coupled（invalid_fast_tier）[/red]"
    console.print(f"tier: {verdict}   口径: {r['aperture_lambda']:.2f}λ   "
                  f"侧射 HPBW 渐近: {r['broadside_hpbw_deg']:.2f}°")
    for reason in g["reasons"]:
        console.print(f"[yellow]· {reason}[/yellow]")
    raise typer.Exit(code=0)


@array_app.command("pattern")
def array_pattern_cmd(
    request_file: str = typer.Argument(
        ..., help="请求 JSON 文件（'-'=stdin；schema 见 service/array_service docstring）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """单扫描角阵列方向图（快速档=单元×AF 复域逐点乘 + Γ_act/Z_scan/盲点）。

    请求示例：{"n_elements": 4, "spacing_lambda": 0.5, "element": "isotropic",
    "amplitude_law": "chebyshev", "sidelobe_level_db": -30, "scan_deg": 90,
    "s_matrix": "...复数 NxN 可选...", "slab": {"eps_r": 2.2,
    "thickness_m": 1.575e-3}, "freq_hz": 1e10}
    """
    from rfauto.service.array_service import NotImplementedPhase, array_pattern

    request = _load_array_request(request_file, "pattern 请求")
    try:
        result = array_pattern(request)
    except NotImplementedPhase as exc:
        # F-9/S3：阶段边界（tier=coupled 且无注入求解器）显式文案 + exit 2
        # ——与通用失败（exit 1）区分：功能属后续阶段，非本次调用错误。
        console.print(
            f"[yellow]✗ 阶段未实现（P3 互耦档未接入，不发射真机）: {exc}[/yellow]")
        raise typer.Exit(code=2) from None
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error') or '未知错误'}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result["result"], ensure_ascii=False))
        raise typer.Exit(code=0)

    r = result["result"]
    tier = (f"[red]{r['tier']}（invalid_fast_tier）[/red]"
            if r["invalid_fast_tier"] else f"[green]{r['tier']}[/green]")
    console.print(f"tier: {tier}   layout: {r['layout']}   N={r['n_elements']}   "
                  f"scan={r['scan_deg']:.2f}°")
    if r.get("sll_db") is not None:
        console.print(f"SLL: [cyan]{r['sll_db']:.2f} dB[/cyan]   "
                      f"HPBW: [cyan]{r['hpbw_deg']:.2f}°[/cyan]" if r.get("hpbw_deg") is not None else
                      f"SLL: [cyan]{r['sll_db']:.2f} dB[/cyan]")
    if r.get("dmax_fast_dbi") is not None:
        console.print(f"Dmax_elem: {r['dmax_elem_dbi']:.2f} dBi   "
                      f"Dmax_fast: {r['dmax_fast_dbi']:.2f} dBi   "
                      f"Dmax_grid(数值): {r['dmax_grid_dbi']:.2f} dBi")
    if r.get("gamma_act") is not None:
        gmax = max(abs(complex(*g)) for g in r["gamma_act"])
        console.print(f"max|Γ_act|: {gmax:.4f}")
    if r.get("blind_spot") is not None:
        bs = r["blind_spot"]
        if bs.get("skipped"):
            console.print(f"[yellow]盲点筛查跳过: {bs.get('reason')}[/yellow]")
        else:
            console.print(f"盲点: {'[red]YES[/red]' if bs['blind'][0] else '[green]no[/green]'}"
                          f"（|k∥−β_sw|/k0 min={bs['min_dist_over_k0'][0]:.4f}，"
                          f"最近阶 (m,n)=({bs['nearest_order_m'][0]},{bs['nearest_order_n'][0]})）")
    for reason in r["gates"]["reasons"]:
        console.print(f"[yellow]· {reason}[/yellow]")
    if r.get("coupled_tier") is not None:
        console.print(f"[yellow]互耦档: {r['coupled_tier']['message']}[/yellow]")
    raise typer.Exit(code=0)


@array_app.command("scan")
def array_scan_cmd(
    request_file: str = typer.Argument(
        ..., help="请求 JSON 文件（'-'=stdin；scan_grid 可在文件内给 start/stop/step）"),
    start: float = typer.Option(None, "--start", help="扫描起始角（覆盖文件 scan_grid）"),
    stop: float = typer.Option(None, "--stop", help="扫描终止角"),
    step: float = typer.Option(None, "--step", help="扫描步长"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """θ 扫描扫掠：逐点 tier 门 + Γ_act + 盲点旗（盲点筛查主口径）。

    示例：rfauto array scan request.json --start 0 --stop 80 --step 1
    """
    from rfauto.service.array_service import array_scan_sweep

    request = _load_array_request(request_file, "scan 请求")
    overrides = {k: v for k, v in (("start", start), ("stop", stop),
                                   ("step", step)) if v is not None}
    if overrides:
        merged = dict(request.get("scan_grid") or {})
        merged.update(overrides)
        request["scan_grid"] = merged
    result = array_scan_sweep(request)
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('error') or '未知错误'}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result["result"], ensure_ascii=False))
        raise typer.Exit(code=0)

    r = result["result"]
    table = Table(title=f"阵列扫描扫掠（{r['n_angles']} 点，盲点 {r['n_blind']}，DP-4）")
    table.add_column("扫描角", justify="right", style="cyan")
    table.add_column("tier")
    table.add_column("max|Γ_act|", justify="right")
    table.add_column("|k∥−βsw|/k0", justify="right")
    table.add_column("最近阶", justify="right")
    table.add_column("盲点")
    for row in r["rows"]:
        blind = row.get("blind")
        blind_txt = ("-" if blind is None else
                     ("[red]YES[/red]" if blind else "no"))
        table.add_row(
            f"{row['scan_deg']:.1f}",
            row["tier"] if not row["invalid_fast_tier"]
            else f"[red]{row['tier']}[/red]",
            (f"{row['gamma_act_max']:.3f}"
             if row.get("gamma_act_max") is not None else "-"),
            (f"{row['min_dist_over_k0']:.4f}"
             if row.get("min_dist_over_k0") is not None else "-"),
            (f"({row['nearest_order'][0]},{row['nearest_order'][1]})"
             if row.get("nearest_order") else "-"),
            blind_txt,
        )
    console.print(table)
    raise typer.Exit(code=0)
