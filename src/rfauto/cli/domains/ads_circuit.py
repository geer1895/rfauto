"""ads-circuit 子应用（ADS 前仿链人机回路 CLI 出口；aurora_o T-O4，2026-11-01）。

用户核心需求（PLAN_DRAFT §〇 第 3 条）："绘制好的图带入 ADS 仿真调参——
不只是展示示意图，而是人工参与并调整前仿真的过程"。三叶构成完整回路
（runs/aurora_o/design_specs/T-O4_ADS_UX_SPEC.md §3.1）：

- 叶 diagram（J1 出图）：族+SnP → 参数化电路图 .drawio（UserObject 三件组
  p_<key>/unit_<key>/src_<key>；draw.io 右键 Edit Data 改值=J2 唯一交互形态，
  rfauto 侧 v1 零 UI 代码）；
- 叶 run（J3+J4 一条龙）：读图→三态合参（--params > 图值 > 族缺省）→
  渲染网表→hpeesofsim→解析→系统指标→对拍→反标注（annot_sim 层上图）；
  求解只走 ads_netlist 正规 env 入口（#272 裸调 exe 静默无输出；真机仓根
  执行或显式 RFAUTO_HPEESOF_DIR，#295；真机 solo，#246）；
- 叶 annotate（离线重放）：原图+circuit_result.json → 只反标注不重跑。

零数值逻辑转发 service/circuit_sim_service（规则 4）；全叶带 --json
（信封契约）。四族 wilkinson_snp/branchline_cascade/active_chain_sparam/
loadpull_hb（前两族=T-O4 MVP 用户令钉死；后两族=aurora_p 席 A2 按
M3 增补规格落位，规格见 runs/aurora_p/a2/M3_DESIGN.md——有源两族出图
需 --params 显式给必给参数，见 diagram 叶 --family help）。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

ads_circuit_app = typer.Typer(
    help="ADS 前仿链：参数化电路图 .drawio 出图/运行/反标注回路"
         "（draw.io Edit Data 改值 → hpeesofsim 前仿 → 指标反标注上图）")
app.add_typer(ads_circuit_app, name="ads-circuit")


def _load_params(params: str | None, json_output: bool) -> dict | None:
    """--params 值归一：@file 读文件，否则内联 JSON；None 原样。"""
    if params is None:
        return None
    if params.startswith("@"):
        p = Path(params[1:])
        if not p.exists():
            _emit_usage_error(f"params 文件不存在: {p}", json_output=json_output)
            raise typer.Exit(code=2)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            _emit_usage_error(f"params 文件不可读: {exc}", json_output=json_output)
            raise typer.Exit(code=2) from exc
    else:
        text = params
    try:
        payload = json.loads(text)
    except ValueError as exc:
        _emit_usage_error(f"--params 不是合法 JSON: {exc}", json_output=json_output)
        raise typer.Exit(code=2) from exc
    if not isinstance(payload, dict):
        _emit_usage_error("--params 必须是 JSON 对象（flat dotted 键或嵌套 sweep）",
                          json_output=json_output)
        raise typer.Exit(code=2)
    return payload


def _print_envelope_result(result: dict, title: str) -> None:
    """失败信封统一 rich 打印（exit 1——service 失败与 usage 分离）。"""
    console.print(f"[red]✗ {title}[/red]")
    for err in result.get("errors", []):
        console.print(f"  [red]- {err}[/red]")
    raise typer.Exit(code=1)


@ads_circuit_app.command("diagram")
def ads_circuit_diagram_cmd(
    family: str = typer.Option(
        ..., "--family",
        help="模板族名，四族：wilkinson_snp / branchline_cascade / "
             "active_chain_sparam / loadpull_hb（T-O4 MVP 两族+aurora_p "
             "A2 有源两族；cascade 须 4 端口 SnP，有源两族须 2 端口且 "
             "--params 显式给必给参数）"),
    snp: str = typer.Option(
        ..., "--snp", help="Touchstone 路径（wilkinson 任意 N 端口；"
                           "cascade 须 4 端口；端口卡按实读 N 生成）"),
    out: str = typer.Option(
        ..., "--out", help="输出 .drawio 路径（父目录须已存在）"),
    params: str = typer.Option(
        None, "--params",
        help="参数覆盖 JSON 串或 @文件（flat dotted 键如 "
             '{"theta_in_deg": 55}，或嵌套 {"sweep": {"fstart": 1.6}}；'
             "缺省=族缺省值，sweep 频带三项留空上图=随 SnP 频带语义）"),
    title: str = typer.Option(
        None, "--title", help="图标题文本（缺省用内核缺省标题）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """J1 出图：族+SnP → 参数化电路图 .drawio（UserObject 三件组）。

    示例：rfauto ads-circuit diagram --family branchline_cascade
    --snp bl.s4p --out ckt.drawio --params @p.json

    出图后在 draw.io 桌面/VS Code 插件打开，右键元件卡 Edit Data 改
    p_* 属性值（如 theta_in_deg 45→55）保存——改属性后重开图看标签
    刷新（placeholders 渲染时点）。本叶零数值逻辑（薄壳转发
    service/circuit_sim_service）。确定性：同输入两次运行文件逐字节相同。
    """
    from rfauto.service.circuit_sim_service import generate_circuit_diagram

    params_payload = _load_params(params, json_output)
    result = generate_circuit_diagram(family, snp, out, params=params_payload,
                                      title=title)
    if json_output:
        _emit(result, "电路图生成失败", json_output=True)
        return
    if not result.get("ok"):
        _print_envelope_result(result, "电路图生成失败")
        return
    # markup 纪律（diagram stackup 叶同款）：人读分支动态段（key/来源/路径
    # 可含 "[...]"）一律 rich.markup.escape——"[default]"/"[diagram]"/
    # "[input-json]" 会被 rich 当样式标签吞掉，来源标签整段丢失
    # （aurora_o o_ads 件1）。
    from rich.markup import escape

    console.print(
        f"[bold]ADS 电路图[/bold]  family={escape(str(result['family']))}  "
        f"SnP {result['n_ports']} 端口  参数 {result['n_params']} 键"
        "（UserObject 三件组：右键卡 Edit Data 改 p_* 值）")
    for key, item in sorted((result.get("values") or {}).items()):
        val = item.get("value")
        shown = "（空=随 SnP 频带）" if val is None else str(val)
        console.print(escape(f"  {key} = {shown}  [{item.get('source')}]"))
    console.print(f"[green]✓ 已写出[/green] {escape(result['out_path'])}"
                  "（draw.io 打开 → 右键元件卡 Edit Data 改值 → ads-circuit run）")


@ads_circuit_app.command("run")
def ads_circuit_run_cmd(
    diagram: str = typer.Option(
        ..., "--diagram", help="电路图 .drawio 路径（只读——反标注产物落 "
                               "--out-dir，原稿是模板不动）"),
    snp: str = typer.Option(
        ..., "--snp", help="Touchstone 路径（网表 File 来源；须纯 ASCII 路径"
                           "——非 ASCII 复制数据到 ASCII 路径后重跑）"),
    out_dir: str = typer.Option(
        ..., "--out-dir", help="工作目录（必填——缺省拒跑防 cwd 相对落真实 "
                               "runs/ 湖，#144 家法）"),
    params: str = typer.Option(
        None, "--params", help="参数覆盖 JSON 串或 @文件（三态最高优先："
                               "--params > 图值 > 族缺省）"),
    family: str = typer.Option(
        None, "--family", help="显式族名核对（与图内 family 不一致显式报错，"
                               "#154 防张冠李戴；缺省=信图内标注）"),
    ads_dir: str = typer.Option(
        None, "--ads-dir", help="ADS 安装根（缺省 env RFAUTO_HPEESOF_DIR → "
                                "settings.hpeesof_dir；真机须仓根执行或显式 "
                                "RFAUTO_HPEESOF_DIR）"),
    no_compare: bool = typer.Option(
        False, "--no-compare", help="关闭对拍（缺省开启：SnP 直通/级联闭式参考）"),
    gate: float = typer.Option(
        None, "--gate",
        help="对拍门上限（线性族=max|ΔS| 缺省 1e-3；有源/HB 族=dB 域，"
             "缺省容差走 linkage 单源）"),
    curves: bool = typer.Option(
        False, "--curves", help="opt-in S 参数曲线卡（B4）：|S|dB 曲线 PNG "
                                "内嵌 annot_sim 层 sim_g 卡（data URI 无 "
                                ";base64 形态单文件可携）；payload 无 S "
                                "参数如实跳过；缺省关（行为同既有）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """J3+J4 一条龙：读图→合参→渲染→hpeesofsim→解析→指标→对拍→反标注。

    示例：rfauto ads-circuit run --diagram ckt.drawio --snp bl.s4p
    --out-dir runs/adsckt/ckt01 --json

    反标注自动上图（annot_sim 层：指标卡+对拍卡，每数值卡带
    source/sim_ref/unit 三件组）；--curves 时另嵌 sim_g 曲线卡（|S|dB
    曲线=parse payload 单源）。产物在 --out-dir：网表/.ds/求解日志/
    <family>_circuit_result.json/<family>_circuit.drawio。draw.io 重开
    反标注图即见最新指标（J5 迭代：再改值→再 run）。
    """
    from rfauto.service.circuit_sim_service import circuit_sim_run

    params_payload = _load_params(params, json_output)
    result = circuit_sim_run(
        diagram, snp_path=snp, out_dir=out_dir, params_override=params_payload,
        family=family, ads_dir=ads_dir, compare=not no_compare, gate=gate,
        curves=curves)
    if json_output:
        _emit(result, "ADS 前仿链运行失败", json_output=True)
        return
    if not result.get("ok"):
        _print_envelope_result(result, "ADS 前仿链运行失败")
        return
    # markup 纪律（diagram stackup 叶同款）：来源/warnings/路径动态段一律
    # escape——"[input-json]"/"[diagram]"/"[default]" 会被 rich 当样式标签
    # 吞掉，来源标签整段丢失（aurora_o o_ads 件1）。
    from rich.markup import escape

    console.print(
        f"[bold]ADS 前仿[/bold]  family={escape(str(result['family']))}  "
        f"网表 {escape(result['netlist_path'])}")
    for key, item in sorted((result.get("effective") or {}).items()):
        val = item.get("value")
        shown = "（缺省=随 SnP 频带）" if val is None else str(val)
        console.print(escape(f"  {key} = {shown}  [{item.get('source')}]"))
    for w in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(w)}[/yellow]")
    metrics = result.get("metrics") or {}
    for name in sorted(metrics):
        console.print(f"  {escape(name)} = {metrics[name]:.6g}")
    cmp = result.get("compare") or {}
    if "gate_ok" in cmp:
        console.print(
            f"  对拍 max|ΔS|={cmp['max_abs_delta_s']:.6g}  "
            f"门={cmp['gate_max_abs_delta_s']:.6g}  gate_ok={cmp['gate_ok']}")
    console.print(f"[green]✓ 反标注图[/green] {escape(result['annotated_diagram_path'])}"
                  "（draw.io 重开即见 annot_sim 指标层）")
    if curves:
        cc = bool(result.get("curves_card"))
        console.print(
            "  曲线卡 sim_g：" + ("已嵌入（|S|dB 曲线内嵌单文件可携）" if cc
                                  else "未产出（payload 无 S 参数，如实跳过）"))


@ads_circuit_app.command("annotate")
def ads_circuit_annotate_cmd(
    diagram: str = typer.Option(
        ..., "--diagram", help="原图 .drawio（只读；可为已反标注图——annot_sim "
                               "层幂等替换不堆积）"),
    result: str = typer.Option(
        ..., "--result", help="ads-circuit run 产物 <family>_circuit_result.json"
                              "（离线指标源；裸 <family>_result.json 无指标不消费）"),
    out: str = typer.Option(
        ..., "--out", help="输出 .drawio 路径（父目录须已存在；禁与 --diagram "
                           "同路径——覆盖原稿显式报错语义见下）"),
    curves: bool = typer.Option(
        False, "--curves", help="opt-in S 参数曲线卡（B4）：result 含 "
                                "circuit.curves 节时嵌入 sim_g 曲线卡（data "
                                "URI 无 ;base64 形态）；节点缺失如实 warnings "
                                "跳过；缺省关（行为同既有）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """离线反标注：原图+circuit_result.json → 指标上图（不重跑仿真）。

    示例：rfauto ads-circuit annotate --diagram ckt.drawio
    --result runs/adsckt/ckt01/branchline_cascade_circuit_result.json
    --out ckt_annotated.drawio

    幂等：同图同 result 两次反标注逐字节同文件（sim_ref=文件路径非时间
    戳）；旧 annot_sim 层被替换不堆积。ADS 段失败的 result 只装 error
    头卡（如实不虚构指标）。本叶零数值逻辑（薄壳转发
    service/circuit_sim_service）。确定性：同输入两次运行文件逐字节相同。
    """
    from rfauto.service.circuit_sim_service import annotate_circuit_diagram

    if Path(diagram).resolve() == Path(out).resolve():
        _emit_usage_error(
            "--out 与 --diagram 同路径（反标注产物禁覆盖原稿）",
            json_output=json_output)
        return
    result_env = annotate_circuit_diagram(diagram, result, out,
                                          with_curves=curves)
    if json_output:
        _emit(result_env, "离线反标注失败", json_output=True)
        return
    if not result_env.get("ok"):
        _print_envelope_result(result_env, "离线反标注失败")
        return
    # markup 纪律（run/diagram 叶同款）：warnings/路径动态段（含 "[...]"
    # 形态可能性）一律 escape——"[...]" 会被 rich 当样式标签吞掉
    # （aurora_p 席 B1 遗留②核验补齐：out_path 此前未 escape，路径含
    # "[...]" 形态段时回显行会被 rich 吞段）。
    from rich.markup import escape

    console.print(
        f"[bold]离线反标注[/bold]  指标卡 {result_env['n_cards']} 张  "
        f"层 {escape(str(result_env['annot_layer']))}（幂等替换不堆积）")
    if curves:
        cc = bool(result_env.get("curves_card"))
        console.print(
            "  曲线卡 sim_g：" + ("已嵌入（|S|dB 曲线内嵌单文件可携）" if cc
                                  else "未产出（result 无 curves 节，如实跳过）"))
        for w in result_env.get("warnings") or []:
            console.print(f"  [yellow]! {escape(w)}[/yellow]")
    # soft_wrap=True：路径行禁 rich 自动折行——80 列下长路径的文件名
    # 段（如 annot[demo].drawio）会跨行断开，子串断言/复制粘贴面全坏
    # （run 43069995504 shard3 实证折行形态 annot[d\nemo]；非吞段是
    # 折行，TTY_COMPATIBLE 守卫管不住 soft_wrap 维度）
    console.print(f"[green]✓ 已写出[/green] {escape(str(result_env['out_path']))}", soft_wrap=True)
