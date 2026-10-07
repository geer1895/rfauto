"""layout 子应用——SO-1 孤儿接线批 W1-B（VI-1 表行 2-8，2026-10-05）。

零逻辑转发 service/layout_*_service 八模块（规则 4 薄壳；数值只在确定性
内核，铁律 7；stats/firmware 同款域内自注册——main.py 只 re-export）：

  rfauto layout build      版图生成与互操作四模式（生成/导出/读入/往返报告）
  rfauto layout assemble   KiCad 子进程装配导出（放置表 .pos + 聚合 BOM）
  rfauto layout diff       两份版图载荷三面语义 diff（层/图元/端口）
  rfauto layout lvs        几何网表对照参考连接表（flag 级）
  rfauto layout panelize   拼板闭式（板阵列/V 槽或邮票孔/利用率/基准标记）
  rfauto layout simulate   版图 openEMS 渲染脚本离线组装（零求解）
  rfauto layout stencil    钢网开孔 IPC-7525 双判据批量评估
  rfauto layout step       KiCad 板级 STEP 导出子进程面

全部 _emit 信封进出；lvs 判定 LVS_FLAG 退出码 1（拦截语义）。
互操作格式枚举以 service 为准：gdsii、dxf、ipc2581、odbpp。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _kv_floats as _kv_floats
from rfauto.cli.domains._core import _load_json_file as _load_json_file
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

layout_app = typer.Typer(
    help="版图家族（生成与互操作、装配、diff、LVS、拼板、仿真组装、钢网、STEP）")
app.add_typer(layout_app, name="layout")


def _fail(message: str) -> dict:
    """程序性错误 → 失败信封（与 service envelope 同构，_emit 出口统一）。"""
    return {"ok": False, "errors": [message]}


def _fmt_choices() -> tuple[str, ...]:
    """互操作格式全集（service 单源；CLI 不复制枚举）。"""
    from rfauto.adapters.layout_interchange import LAYOUT_INTERCHANGE_FORMATS

    return tuple(LAYOUT_INTERCHANGE_FORMATS)


# ─── 1/8 build：layout_service 四模式（生成/导出/读入/往返报告） ──────────────


@layout_app.command("build")
def layout_build_cmd(
    kind: str = typer.Option(
        "", "--kind",
        help="生成模式：版图生成器注册名（microstrip、patch_antenna、via_fence、pad_array、hairpin_bpf）"),
    param: list[str] = typer.Option(  # noqa: B008
        None, "--param", "-p", help="生成参数 名=值（可多次，值必须为数字）"),
    from_payload: str = typer.Option(
        "", "--from-payload", help="导出模式：版图载荷 JSON 文件（配 --fmt 与 --output）"),
    import_file: str = typer.Option(
        "", "--import-file", help="读入模式：互操作文件（配 --fmt）"),
    laymap: str = typer.Option(
        "", "--laymap", help="读入模式：层名映射文件（仅 gdsii 语义）"),
    round_trip_file: str = typer.Option(
        "", "--round-trip", help="往返报告模式：版图载荷 JSON 文件（配 --workdir）"),
    workdir: str = typer.Option(
        "", "--workdir", help="往返报告工作目录"),
    fmt_list: str = typer.Option(
        "", "--fmt-list", help="往返报告格式逗号串（缺省全格式）"),
    fmt: str = typer.Option(
        "", "--fmt", help="互操作格式：gdsii、dxf、ipc2581、odbpp"),
    output: str = typer.Option(
        "", "--output", "-o", help="导出文件路径（--fmt 必配）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """版图生成与互操作四模式：生成（--kind）、导出（--from-payload）、读入（--import-file）、往返报告（--round-trip）。

    模式判优顺序：往返报告、读入、导出、生成。生成模式可追加 --fmt 与
    --output 在生成后直接导出（service 契约要求两者成对给出）。
    """
    from rfauto.service.envelope import ok_envelope
    from rfauto.service.layout_service import (
        export_layout_payload,
        generate_layout_payload,
        import_layout_payload,
        round_trip_report,
    )

    mode = ("round-trip" if round_trip_file
            else "import" if import_file
            else "export" if from_payload
            else "generate" if kind else "")
    try:
        if mode == "round-trip":
            if not workdir:
                raise ValueError("--round-trip 模式需要 --workdir")
            payload = _load_json_file(round_trip_file, "版图载荷 JSON 文件")
            formats = ([f.strip() for f in fmt_list.split(",") if f.strip()]
                       if fmt_list else None)
            # layout_service 契约=裸载荷 JSON（非信封）——薄壳统一套 ok 信封
            result = ok_envelope(**round_trip_report(payload, workdir, formats))
        elif mode == "import":
            if not fmt:
                raise ValueError("--import-file 模式需要 --fmt")
            result = ok_envelope(
                layout=import_layout_payload(import_file, fmt,
                                             laymap_path=laymap or None))
        elif mode == "export":
            if not fmt or not output:
                raise ValueError("--from-payload 模式需要 --fmt 与 --output")
            payload = _load_json_file(from_payload, "版图载荷 JSON 文件")
            result = ok_envelope(**export_layout_payload(payload, output, fmt))
        elif mode == "generate":
            params = _kv_floats(list(param) if param else [], "--param")
            result = ok_envelope(**generate_layout_payload(
                kind, params, fmt=fmt or None, output_path=output or None))
        else:
            raise ValueError(
                "未指定模式：--kind、--from-payload、--import-file、"
                "--round-trip 四选一")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result = _fail(f"{type(exc).__name__}: {exc}")
    _emit(result, "layout build 失败", json_output=json_output)
    if json_output:
        return
    if mode == "round-trip":
        console.print(
            f"[green]✓[/green] {result['name']}: n_items={result['n_items']}  "
            f"all_lossless={result['all_lossless']}")
    else:
        console.print(
            f"[green]✓[/green] {mode} 完成（互操作格式全集："
            f"{'、'.join(_fmt_choices())}）")


# ─── 2/8 assemble：layout_assembly_service（KiCad 子进程装配导出） ────────────


@layout_app.command("assemble")
def layout_assemble_cmd(
    board: str = typer.Argument(..., help="PCB 文件路径（.kicad_pcb）"),
    out_dir: str = typer.Option(..., "--out-dir", help="产物目录（.pos 与 BOM CSV 落盘）"),
    kicad_python: str = typer.Option(
        "", "--kicad-python", help="显式 KiCad 自带 Python 路径（缺省走探测）"),
    timeout_s: float = typer.Option(
        None, "--timeout-s", help="子进程超时秒数（缺省走 service 缺省值）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """KiCad 子进程装配导出：放置表 .pos 与聚合 BOM CSV（铁律 2 子进程域）。"""
    from rfauto.service.layout_assembly_service import assembly_payload

    kwargs = {}
    if kicad_python:
        kwargs["kicad_python"] = kicad_python
    if timeout_s is not None:
        kwargs["timeout_s"] = timeout_s
    result = assembly_payload(board, out_dir, **kwargs)
    _emit(result, "装配导出失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓[/green] n_placed={result.get('n_placed')}  "
        f"pos={result.get('pos_path')}  bom={result.get('bom_path')}")


# ─── 3/8 diff：layout_diff_service（三面语义 diff） ───────────────────────────


@layout_app.command("diff")
def layout_diff_cmd(
    a: str = typer.Argument(..., help="版图载荷 A JSON 文件（基线）"),
    b: str = typer.Argument(..., help="版图载荷 B JSON 文件（新）"),
    marker_layer: str = typer.Option(
        "", "--marker-layer", help="端口面 opt-in：标记层名（缺省跳过端口面）"),
    tol_nm: float = typer.Option(
        None, "--tol-nm", help="量化栅格 nm（缺省走 service 缺省值；只吸收浮点表示噪声）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """两份版图载荷三面语义 diff：层、图元、端口（端口面 opt-in）。"""
    from rfauto.service.layout_diff_service import diff_layout_payload

    a_payload = _load_json_file(a, "版图载荷 A JSON 文件")
    b_payload = _load_json_file(b, "版图载荷 B JSON 文件")
    port_kwargs = {"marker_layer": marker_layer} if marker_layer else None
    kwargs = {"tol_nm": tol_nm} if tol_nm is not None else {}
    result = diff_layout_payload(
        a_payload, b_payload, port_kwargs=port_kwargs, **kwargs)
    _emit(result, "layout diff 失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓[/green] identical={result['identical']}  "
        f"layers: +{len(result['layers']['added'])}"
        f"/-{len(result['layers']['removed'])}"
        f"/~{len(result['layers']['changed'])}  "
        f"items: +{len(result['items']['added'])}"
        f"/-{len(result['items']['removed'])}")


# ─── 4/8 lvs：layout_lvs_service（flag 级对照；LVS_FLAG 退出码 1） ─────────────


@layout_app.command("lvs")
def layout_lvs_cmd(
    layout_file: str = typer.Argument(..., help="版图载荷 JSON 文件"),
    netlist_file: str = typer.Argument(..., help="netlist JSON 文件"),
    netlist_fmt: str = typer.Option(
        "compose", "--netlist-fmt",
        help="netlist 形态：compose（rfauto-netlist-v1 折叠，缺省）或 pin（pin 级参考直传）"),
    ports_file: str = typer.Option(
        "", "--ports-file", help="显式端口记录 JSON 文件（对象带 ports 列表键；与 --marker-layer 二选一）"),
    marker_layer: str = typer.Option(
        "", "--marker-layer", help="端口三来源解析（标记层通道；与 --ports-file 二选一）"),
    layer: str = typer.Option(
        "", "--layer", help="导电层过滤（严格单层口径必须显式给）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """几何网表对照参考连接表（flag 级）；判定 LVS_FLAG 时退出码 1。"""
    from rfauto.service.layout_lvs_service import (
        expected_from_compose_netlist,
        lvs_check,
    )

    layout_payload = _load_json_file(layout_file, "版图载荷 JSON 文件")
    netlist = _load_json_file(netlist_file, "netlist JSON 文件")
    try:
        if netlist_fmt == "compose":
            expected = expected_from_compose_netlist(netlist)
        elif netlist_fmt == "pin":
            expected = netlist
        else:
            raise ValueError(f"--netlist-fmt 须 compose 或 pin，实际 {netlist_fmt!r}")
    except (ValueError, KeyError, TypeError) as exc:
        _emit(_fail(f"netlist 折叠失败: {exc}"), "netlist 折叠失败",
              json_output=json_output)
        return
    ports = None
    if ports_file:
        ports = _load_json_file(ports_file, "端口记录 JSON 文件").get("ports")
    port_kwargs = {"marker_layer": marker_layer} if marker_layer else None
    result = lvs_check(
        layout_payload, expected,
        ports=ports, port_kwargs=port_kwargs,
        layer=layer or None)
    _emit(result, "LVS 检查失败", json_output=json_output)
    if result.get("verdict") != "LVS_MATCH":
        if not json_output:
            console.print(f"[red]✗ LVS_FLAG[/red] verdict={result.get('verdict')}")
        raise typer.Exit(code=1)
    if not json_output:
        console.print(
            f"[green]✓ LVS_MATCH[/green] nets={len(result.get('nets') or [])}")


# ─── 5/8 panelize：layout_panel_service（拼板闭式） ───────────────────────────


@layout_app.command("panelize")
def layout_panelize_cmd(
    board_w_mm: float = typer.Option(..., "--board-w-mm", help="单板宽 mm"),
    board_h_mm: float = typer.Option(..., "--board-h-mm", help="单板高 mm"),
    cols: int = typer.Option(1, "--cols", help="列数"),
    rows: int = typer.Option(1, "--rows", help="行数"),
    separation: str = typer.Option(
        "vcut", "--separation", help="分板方式：vcut 或 tab"),
    edge_rail_mm: float = typer.Option(
        None, "--edge-rail-mm", help="工艺边宽度 mm（四边同宽；缺省走 service 缺省值）"),
    board_gap_mm: float = typer.Option(
        None, "--board-gap-mm", help="板间隙 mm（tab 方式为铣削通道宽，必须大于 0；缺省走 service 缺省值）"),
    board_thickness_mm: float = typer.Option(
        None, "--board-thickness-mm", help="板厚 mm（V 槽几何用；缺省走 service 缺省值）"),
    web_ratio: float = typer.Option(
        None, "--web-ratio", help="V 槽剩余 web 占板厚比（缺省走 service 缺省值）"),
    vcut_angle_deg: float = typer.Option(
        None, "--vcut-angle-deg", help="V 槽含角 deg（缺省走 service 缺省值）"),
    tab_hole_dia_mm: float = typer.Option(
        None, "--tab-hole-dia-mm", help="邮票孔孔径 mm（缺省走 service 缺省值）"),
    tab_holes: int = typer.Option(
        None, "--tab-holes", help="每桥邮票孔数（缺省走 service 缺省值）"),
    tab_len_mm: float = typer.Option(
        None, "--tab-len-mm", help="桥长 mm（缺省走 service 缺省值）"),
    tabs_per_edge: int = typer.Option(
        None, "--tabs-per-edge", help="每边桥数（缺省走 service 缺省值）"),
    fiducials: bool | None = typer.Option(
        None, "--fiducials/--no-fiducials", help="是否输出基准标记三点（缺省走 service 缺省值）"),
    fiducial_inset_mm: float = typer.Option(
        None, "--fiducial-inset-mm", help="基准标记中心距面板边 mm（缺省走 service 缺省值）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """拼板闭式：板阵列尺寸、V 槽或邮票孔分板规格、利用率、基准标记。"""
    from rfauto.service.layout_panel_service import panelize

    kwargs = {
        "cols": cols, "rows": rows, "separation": separation,
        "edge_rail_mm": edge_rail_mm, "board_gap_mm": board_gap_mm,
        "board_thickness_mm": board_thickness_mm, "web_ratio": web_ratio,
        "vcut_angle_deg": vcut_angle_deg,
        "tab_hole_dia_mm": tab_hole_dia_mm, "tab_holes": tab_holes,
        "tab_len_mm": tab_len_mm, "tabs_per_edge": tabs_per_edge,
        "fiducials": fiducials, "fiducial_inset_mm": fiducial_inset_mm,
    }
    result = panelize(board_w_mm, board_h_mm,
                      **{k: v for k, v in kwargs.items() if v is not None})
    _emit(result, "拼板计算失败", json_output=json_output)
    if json_output:
        return
    panel = result.get("panel") or {}
    console.print(
        f"[green]✓[/green] panel {panel.get('w_mm')}×{panel.get('h_mm')} mm  "
        f"n_boards={result.get('n_boards')}  "
        f"utilization={result.get('utilization')}")


# ─── 6/8 simulate：layout_sim_service（渲染脚本离线组装，零求解） ──────────────


@layout_app.command("simulate")
def layout_simulate_cmd(
    payload_file: str = typer.Option(
        ..., "--payload",
        help="组装载荷 JSON 文件（stackup、material_props、layout 或 primitives、ports、sim）"),
    out_dir: str = typer.Option(
        "", "--out-dir", help="渲染脚本落盘目录（写 simulation.py；缺省只进信封）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """版图 openEMS 渲染脚本离线组装（零求解；产物=渲染脚本，--out-dir 落盘）。"""
    from rfauto.service.layout_sim_service import layout_sim_prepare

    payload = _load_json_file(payload_file, "组装载荷 JSON 文件")
    result = layout_sim_prepare(payload)
    if result.get("ok") and out_dir:
        from pathlib import Path

        target = Path(out_dir)
        target.mkdir(parents=True, exist_ok=True)
        script_path = target / "simulation.py"
        script_path.write_text(result["render_script"], encoding="utf-8")
        result = dict(result)
        result["script_path"] = str(script_path)
    _emit(result, "渲染脚本组装失败", json_output=json_output)
    if json_output:
        return
    provenance = result.get("provenance") or {}
    ports = result.get("ports") or {}
    console.print(
        f"[green]✓[/green] zero_solve={result.get('zero_solve')}  "
        f"script_sha256={str(provenance.get('script_sha256'))[:12]}  "
        f"n_ports={ports.get('n_ports')}")


# ─── 7/8 stencil：layout_stencil_service（IPC-7525 双判据） ───────────────────


@layout_app.command("stencil")
def layout_stencil_cmd(
    apertures_file: str = typer.Option(
        ..., "--apertures", help="开孔清单 JSON 文件（列表，或对象带 apertures 列表键）"),
    foil_thickness_mm: float = typer.Option(
        ..., "--foil-thickness-mm", help="钢片厚度 mm"),
    ar_min: float = typer.Option(
        None, "--ar-min", help="面积比下限（IPC-7525 经验推荐阈值；缺省走 service 缺省值）"),
    aspect_min: float = typer.Option(
        None, "--aspect-min", help="宽厚比下限（开孔宽与钢片厚之比；缺省走 service 缺省值）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """钢网开孔 IPC-7525 双判据批量评估：面积比与宽厚比逐孔加汇总。"""
    from rfauto.service.layout_stencil_service import evaluate_apertures

    data = _load_json_file(apertures_file, "开孔清单 JSON 文件")
    apertures = data.get("apertures") if isinstance(data, dict) else None
    if apertures is None:
        _emit(_fail("开孔清单须为对象带 apertures 列表键"),
              "开孔清单非法", json_output=json_output)
        return
    kwargs = {}
    if ar_min is not None:
        kwargs["ar_min"] = ar_min
    if aspect_min is not None:
        kwargs["aspect_min"] = aspect_min
    result = evaluate_apertures(apertures, foil_thickness_mm, **kwargs)
    _emit(result, "钢网开孔评估失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓[/green] n_pass={result.get('n_pass')}/{result.get('n_total')}  "
        f"all_pass={result.get('all_pass')}")


# ─── 8/8 step：layout_step_service（KiCad 板级 STEP 导出） ────────────────────


@layout_app.command("step")
def layout_step_cmd(
    board: str = typer.Argument(..., help="PCB 文件路径（.kicad_pcb）"),
    output: str = typer.Option(
        "", "--output", "-o", help="输出 .step 路径（缺省与板同目录同名换后缀）"),
    cli_path: str = typer.Option(
        "", "--cli-path", help="显式 kicad-cli 路径（缺省走探测：显式参、env、缺省位、PATH）"),
    timeout_s: float = typer.Option(
        None, "--timeout-s", help="子进程超时秒数（缺省走 service 缺省值）"),
    extra_arg: list[str] = typer.Option(  # noqa: B008
        None, "--extra-arg", help="透传 kicad-cli 附加参数（可多次）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """KiCad 板级 STEP 导出子进程面；缺 kicad-cli 走 skipped 信封（不报错）。"""
    from rfauto.service.layout_step_service import export_step

    kwargs = {}
    if output:
        kwargs["out_path"] = output
    if cli_path:
        kwargs["cli_path"] = cli_path
    if timeout_s is not None:
        kwargs["timeout_s"] = timeout_s
    if extra_arg:
        kwargs["extra_args"] = list(extra_arg)
    result = export_step(board, **kwargs)
    _emit(result, "STEP 导出失败", json_output=json_output)
    if json_output:
        return
    if result.get("out_path"):
        console.print(
            f"[green]✓[/green] out={result['out_path']}  "
            f"size_bytes={result.get('size_bytes')}")
    else:
        console.print(f"skipped: {result.get('reason')}")
