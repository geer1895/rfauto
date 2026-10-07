"""env_reliability 子应用组（F-10 六服务 shell 接线 W3-D，Phase 3，2026-10-05）。

五子应用（fault-tree/datasheet/humidity/weave/cryo；pdn_aging.py 模板：
域内模块级 add_typer 自注册——cli/main.py 只 re-export，二次 add_typer
会双注册打红 zero-shadow 钉）。全部零逻辑转发 service（规则 4）：payload
JSON 文件走 _load_json_file；路径参数 str 注解（#269 B008）；数值只在
确定性内核（铁律 7）；与 MCP 工具 env_reliability 组同源同名 service
函数（JSON 进出）。

顶层无同名命令（#df6① 冲突检查 2026-10-05：fault-tree/datasheet/
humidity/weave/cryo 经 click 树实测全 CLI 树零撞名）。
"""

from __future__ import annotations

from pathlib import Path

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _load_json_file as _load_json_file
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── fault-tree（fault_tree_service 复合叶：build+MCS+mermaid 单次产出） ─────
# z3 为可选依赖（未装 service 如实 ok=False，不静默回退）；mermaid 不单独
# 成叶（--format 分支零增量，RA §一 1.1 备注）。

fault_tree_app = typer.Typer(
    help="故障树分析（QM-FTA：playbook→OR-of-AND 树+最小割集+Mermaid 图）")
app.add_typer(fault_tree_app, name="fault-tree")


@fault_tree_app.command("report")
def fault_tree_report_cmd(
    playbook: str = typer.Option(
        "", "--playbook",
        help="playbook YAML 路径（缺省 knowledge/diagnostics/playbook.yaml）"),
    engine: str = typer.Option(
        "enumerate", "--engine",
        help="最小割集引擎：enumerate（缺省恒可用）或 z3（可选依赖，未装如实报缺）"),
    out_format: str = typer.Option(
        "json", "--format", help="输出形态：json 信封（缺省）或 mermaid 图文本"),
    json_output: bool = typer.Option(
        False, "--json", "-j",
        help="强制 JSON 信封输出（--format mermaid 时信封内附 mermaid 文本节）"),
) -> None:
    """故障树报告（复合叶）：树构建+最小割集单次产出，--format mermaid 附图文本。

    示例：rfauto fault-tree report --engine enumerate --format mermaid
    """
    from rfauto.service.fault_tree_service import (
        build_fault_tree as _build,
    )
    from rfauto.service.fault_tree_service import (
        mermaid_fault_tree as _mermaid,
    )
    from rfauto.service.fault_tree_service import (
        minimal_cut_sets as _mcs,
    )

    if out_format not in ("json", "mermaid"):
        _emit({"ok": False,
               "errors": [f"--format 须为 json 或 mermaid，实际 {out_format!r}"]},
              "故障树报告失败")
        return
    built = _build(playbook or None)
    if not built.get("ok"):
        _emit(built, "故障树构建失败")
        return
    mcs = _mcs(tree=built.get("tree"), engine=engine)
    out: dict = {**built, **mcs}
    if out_format == "mermaid":
        mm = _mermaid(built["tree"])
        if not mm.get("ok"):
            _emit(mm, "Mermaid 渲染失败")
            return
        out["mermaid"] = mm.get("mermaid")
        out["n_mermaid_lines"] = mm.get("n_lines")
        if json_output:
            _emit(out, "故障树报告失败")
            return
        console.print(out["mermaid"])
        return
    _emit(out, "故障树报告失败")


# ─── datasheet（datasheet_service 复合叶：build+render 双格式 --out 分派） ───
# run 缺省=纯名义面（curves 如实 missing，不伪造）；run 目录不存在=正常
# 失败路径（ok=False 信封，RA §一 1.5 判据）。

datasheet_app = typer.Typer(
    help="器件 datasheet 生成（EP-4：run 报告/模板名义 → 规格书 md/HTML）")
app.add_typer(datasheet_app, name="datasheet")


@datasheet_app.command("build")
def datasheet_build_cmd(
    run_dir: str = typer.Option(
        "", "--run", help="run 目录（PR-4 报告模型数据源；缺省=无实测节）"),
    template: str = typer.Option(
        ..., "--template", "-t",
        help="模板注册名（docs/templates/<t>/meta.yaml 名义来源）"),
    part_number: str = typer.Option(
        "", "--part-number", help="器件型号（缺省=模板名）"),
    out_format: str = typer.Option(
        "md", "--format", help="渲染形态：md（缺省）或 html"),
    out: str = typer.Option(
        "", "--out", "-o", help="输出文件路径（缺省打印渲染文本到控制台）"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="JSON 信封输出（无 --out 时内嵌渲染全文）"),
) -> None:
    """构建器件规格书（复合叶）：build_datasheet+render_markdown/html 单次产出。

    示例：rfauto datasheet build --template mline --run runs/mline_x --out ds.md
    """
    from rfauto.service.datasheet_service import (
        build_datasheet as _build,
    )
    from rfauto.service.datasheet_service import (
        load_template_meta as _load_meta,
    )
    from rfauto.service.datasheet_service import (
        render_html as _render_html,
    )
    from rfauto.service.datasheet_service import (
        render_markdown as _render_md,
    )

    if out_format not in ("md", "html"):
        _emit({"ok": False,
               "errors": [f"--format 须为 md 或 html，实际 {out_format!r}"]},
              "datasheet 渲染失败")
        return
    report = None
    if run_dir:
        from rfauto.service.report_render import build_report_model as _report_model

        try:
            report = _report_model(run_dir)
        except (FileNotFoundError, OSError, ValueError) as exc:
            _emit({"ok": False, "errors": [f"run 报告模型构建失败: {exc}"]},
                  "datasheet 构建失败")
            return
    try:
        model = _build(
            part_number=part_number or template,
            template=template,
            meta=_load_meta(template),
            report=report,
        )
        content = _render_html(model) if out_format == "html" else _render_md(model)
    except (KeyError, TypeError, ValueError) as exc:
        _emit({"ok": False, "errors": [f"datasheet 构建失败: {exc}"]},
              "datasheet 构建失败")
        return
    envelope: dict = {
        "ok": True,
        "part_number": model["identification"]["part_number"],
        "template": template,
        "format": out_format,
        "n_electrical_rows": len(model["electrical"]["rows"]),
        "n_mechanical_rows": len(model["mechanical"]["rows"]),
        "curves_status": model["curves"]["status"],
        "out": out or None,
    }
    if out:
        p = Path(out)
        if p.parent and not p.parent.is_dir():
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        envelope["n_chars"] = len(content)
        if json_output:
            _emit(envelope, "datasheet 渲染失败")
            return
        console.print(f"[green]✓[/green] datasheet 已写出: {p}")
        console.print(
            f"  part={envelope['part_number']}  format={out_format}"
            f"  电气行 {envelope['n_electrical_rows']}"
            f"  机械行 {envelope['n_mechanical_rows']}"
            f"  曲线 {envelope['curves_status']}")
        return
    envelope["content"] = content
    if json_output:
        _emit(envelope, "datasheet 渲染失败")
        return
    console.print(content)


# ─── humidity（humidity_drift_service 双叶：uptake/msl，pdn 同款 payload 壳） ─

humidity_app = typer.Typer(
    help="湿度吸湿漂移（F-H.2：Fick 吸湿估计+MSL 车间寿命查询）")
app.add_typer(humidity_app, name="humidity")


@humidity_app.command("uptake")
def humidity_uptake_cmd(
    payload_path: str = typer.Argument(
        ..., help="payload JSON 文件（键见 service.humidity_drift_service."
                  "moisture_uptake_estimate）"),
    json_output: bool = typer.Option(
        True, "--json/--no-json",
        help="JSON 信封输出（缺省开=信封直出；--no-json 走富文本失败行）"),
) -> None:
    """湿度吸湿端到端估计：Fick 级数+短时 √t 律双路径+可选 εr(M) 混合节。"""
    from rfauto.service.humidity_drift_service import (
        moisture_uptake_estimate as _fn,
    )

    payload = _load_json_file(payload_path, "payload")
    try:
        result = _fn(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"payload 非法: {exc}"]}
    _emit(result, "吸湿估计失败", json_output=json_output)


@humidity_app.command("msl")
def humidity_msl_cmd(
    payload_path: str = typer.Argument(
        ..., help="payload JSON 文件（键见 service.humidity_drift_service."
                  "msl_floor_life_query）"),
    json_output: bool = typer.Option(
        True, "--json/--no-json",
        help="JSON 信封输出（缺省开=信封直出；--no-json 走富文本失败行）"),
) -> None:
    """MSL 车间寿命查询：J-STD-033 表+可选 exposure_h 耗尽判定。"""
    from rfauto.service.humidity_drift_service import (
        msl_floor_life_query as _fn,
    )

    payload = _load_json_file(payload_path, "payload")
    try:
        result = _fn(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"payload 非法: {exc}"]}
    _emit(result, "MSL 查询失败", json_output=json_output)


# ─── weave（glass_weave_skew_service 双叶：styles 零 payload 只读面/estimate） ─

weave_app = typer.Typer(
    help="玻纤编织 skew（HS-1：样式表查询+最坏/期望 skew 估计）")
app.add_typer(weave_app, name="weave")


@weave_app.command("styles")
def weave_styles_cmd(
    style: str = typer.Option(
        "", "--style", help="样式名（1067/1080/2116/7628；缺省=全表）"),
    json_output: bool = typer.Option(
        True, "--json/--no-json",
        help="JSON 信封输出（缺省开=信封直出；--no-json 走富文本失败行）"),
) -> None:
    """编织样式表查询（零 payload 只读面，preflight gates 先例）：参数+MIT 出处。"""
    from rfauto.service.glass_weave_skew_service import (
        weave_style_info as _fn,
    )

    payload = {"style": style} if style else None
    try:
        result = _fn(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"参数非法: {exc}"]}
    _emit(result, "样式表查询失败", json_output=json_output)


@weave_app.command("estimate")
def weave_estimate_cmd(
    payload_path: str = typer.Argument(
        ..., help="payload JSON 文件（键见 service.glass_weave_skew_service."
                  "weave_skew_estimate）"),
    json_output: bool = typer.Option(
        True, "--json/--no-json",
        help="JSON 信封输出（缺省开=信封直出；--no-json 走富文本失败行）"),
) -> None:
    """编织 skew 端到端估计：样式→εeff 界→最坏/期望 skew→zigzag 残余→UI verdict。"""
    from rfauto.service.glass_weave_skew_service import (
        weave_skew_estimate as _fn,
    )

    payload = _load_json_file(payload_path, "payload")
    try:
        result = _fn(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"payload 非法: {exc}"]}
    _emit(result, "skew 估计失败", json_output=json_output)


# ─── cryo（cryo_materials_service 单叶：surface，pdn 同款 payload 壳） ────────

cryo_app = typer.Typer(
    help="低温材料面（F-H.4：铜面全量+可选超导节/Q 分解估计）")
app.add_typer(cryo_app, name="cryo")


@cryo_app.command("surface")
def cryo_surface_cmd(
    payload_path: str = typer.Argument(
        ..., help="payload JSON 文件（键见 service.cryo_materials_service."
                  "cryo_surface_estimate）"),
    json_output: bool = typer.Option(
        True, "--json/--no-json",
        help="JSON 信封输出（缺省开=信封直出；--no-json 走富文本失败行）"),
) -> None:
    """低温材料面端到端估计：铜面必出；超导节/Q 节可选（键透传）。"""
    from rfauto.service.cryo_materials_service import (
        cryo_surface_estimate as _fn,
    )

    payload = _load_json_file(payload_path, "payload")
    try:
        result = _fn(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"payload 非法: {exc}"]}
    _emit(result, "低温材料面估计失败", json_output=json_output)
