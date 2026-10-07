"""agent 子应用（LLM 提案/应用）+ kicad 子应用（B6 stage-2）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── agent (E4b 提案/执行编排) ────────────────────────────────────────────────

agent_app = typer.Typer(help="Agent 提案/执行编排（E4b 三层 Gate）")
app.add_typer(agent_app, name="agent")


@app.command("hfss-import")
def hfss_import_cmd(
    project: str = typer.Argument(..., help="HFSS 工程文件路径（.aedt）"),
    design: str = typer.Option(None, "--design", "-d", help="设计名（缺省取第一个）"),
    version: str = typer.Option("2023.1", "--version", help="AEDT 版本（2026.1 受 PyAEDT issue #7410 阻塞，暂用 2023.1）"),
    out: str = typer.Option(None, "--out", "-o", help="配方草稿输出路径（YAML）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """HFSS 工程导入器：读变量/扫参范围/Setup-Sweep/端口 → 设计规格 + 配方草稿。"""
    from rfauto.service.v3_services import hfss_import_recipe

    result = hfss_import_recipe(project, design, version=version, out=out)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "导入失败", json_output=True)
        return
    if not result.get("ok"):
        console.print(f"[red]✗ 导入失败: {result.get('error')}[/red]")
        raise typer.Exit(code=1)
    console.print("[cyan]导入成功：设计规格[/cyan]")
    console.print_json(json.dumps(result["spec"], indent=2, ensure_ascii=False, default=str))
    console.print("[cyan]配方草稿：[/cyan]")
    console.print_json(json.dumps(result["recipe"], indent=2, ensure_ascii=False, default=str))
    if result.get("recipe_path"):
        console.print(f"[green]已写出: {result['recipe_path']}[/green]")
        if result.get("overwritten"):
            # R2-D-03：explicit 覆盖受保护 recipes/ 既有原件时明示，消除盲写
            console.print("[yellow]⚠ 已覆盖受保护 recipes/ 既有原件"
                          "（overwritten=true）[/yellow]")


@agent_app.command("propose")
def agent_propose_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    params: str = typer.Option("{}", "--params", "-p", help="参数覆盖 JSON"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
    from_diagnosis: str = typer.Option(None, "--from-diagnosis", help="从 run_id 诊断结果生成提案"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """提案模式：L1/L2 Gate 校验 + L3 确认 token（不执行）。

    --from-diagnosis: 读取指定 run 的诊断结果，自动生成参数调整提案。
    """
    from rfauto.service.api import agent_propose

    diagnoses_out: list | None = None
    if from_diagnosis:
        # Load diagnosis from run's metrics.json
        meta_path = Path("runs") / from_diagnosis / "results" / "metrics.json"
        if not meta_path.exists():
            if json_output:
                # VI-5 W6-B：入参缺失也信封（--json 下失败路径不许非 JSON）
                _emit({"ok": False, "errors": [f"未找到 run 指标: {from_diagnosis}"]},
                      "提案生成失败", json_output=True)
            console.print(f"[red]未找到 run 指标: {from_diagnosis}[/red]")
            raise typer.Exit(code=1)
        metrics_data = json.loads(meta_path.read_text(encoding="utf-8"))
        diagnosis = metrics_data.get("diagnosis", {})
        if not diagnosis or not diagnosis.get("diagnoses"):
            if json_output:
                # 无诊断触发是合法零提案态（ok=True 如实，退出码 0 语义保持）
                console.print_json(json.dumps(
                    {"ok": True, "proposed": False,
                     "note": "该 run 无诊断触发（所有规则通过）"},
                    ensure_ascii=False))
                raise typer.Exit(code=0)
            console.print("[yellow]该 run 无诊断触发（所有规则通过）[/yellow]")
            raise typer.Exit(code=0)
        # Generate params from diagnosis initial_values
        params_override = diagnosis.get("initial_values", {})
        diagnoses_out = diagnosis["diagnoses"]
        if not json_output:
            console.print(f"[cyan]从诊断结果生成提案（{len(diagnoses_out)} 条规则触发）[/cyan]")
            for d in diagnoses_out:
                console.print(f"  [{d.get('severity', '?')}] {d.get('rule_id', '?')}: {d.get('description', '')}")
                if d.get("hint"):
                    console.print(f"    建议: {d['hint']}")
        params = json.dumps(params_override)

    try:
        params_override = json.loads(params)
    except json.JSONDecodeError as e:
        if json_output:
            _emit({"ok": False, "errors": [f"--params 不是合法 JSON: {e}"]},
                  "提案参数非法", json_output=True)
        console.print(f"[red]✗ --params 不是合法 JSON: {e}[/red]")
        raise typer.Exit(code=1) from None

    result = agent_propose(recipe, params_override, adapter_name=adapter)
    if json_output:
        # VI-5 W6-B：--json 信封（诊断触发明细随信封一并透传）
        if diagnoses_out is not None:
            result = {**result, "diagnoses": diagnoses_out}
        _emit(result, "提案被拒", json_output=True)
        return
    if not result.get("ok"):
        console.print(f"[red]✗ 提案被拒（{result.get('stage', '?')}）[/red]")
        gate = result.get("gate", {})
        for v in gate.get("violations", []) + gate.get("issues", []):
            console.print(f"  [red]- {v}[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]✓ 提案通过三层 Gate[/green]")
    console.print(f"  token: [cyan]{result['token']}[/cyan]")
    console.print(f"  生效参数: {result['effective_params']}")
    console.print("  执行: rfauto agent apply <recipe> --token <token> --params '<json>'")


@agent_app.command("apply")
def agent_apply_cmd(
    recipe: str = typer.Argument(..., help="配方文件路径"),
    token: str = typer.Option(..., "--token", "-t", help="propose 返回的确认 token"),
    params: str = typer.Option("{}", "--params", "-p", help="参数覆盖 JSON（须与 propose 一致）"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="适配器名称"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """执行模式：校验 token 后真实运行（参数被篡改会被哈希校验拒绝）。"""
    from rfauto.service.api import agent_apply

    try:
        params_override = json.loads(params)
    except json.JSONDecodeError as e:
        if json_output:
            # VI-5 W6-B：入参非法也信封（--json 下失败路径不许非 JSON）
            _emit({"ok": False, "errors": [f"--params 不是合法 JSON: {e}"]},
                  "执行失败", json_output=True)
        console.print(f"[red]✗ --params 不是合法 JSON: {e}[/red]")
        raise typer.Exit(code=1) from None

    result = agent_apply(recipe, token, params_override, adapter_name=adapter)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "执行失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 执行失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ 执行完成[/green]  run_id: {result.get('run_id')}")
    for k, v in result.get("metrics", {}).items():
        console.print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")


# ─── kicad (E7a P-Cell 生成 + DRC gate) ──────────────────────────────────────

kicad_app = typer.Typer(help="KiCad 板级链路（E7a：P-Cell 生成 + DRC gate）")
app.add_typer(kicad_app, name="kicad")


@kicad_app.command("design-from-run")
def kicad_design_from_run_cmd(
    run_dir: str = typer.Argument(..., help="run 目录（含 meta.json 与 recipe.snapshot.yaml）"),
    kind: str = typer.Option(None, "--kind", help="显式版图生成器注册名（缺省按模型映射）"),
    output: str = typer.Option(None, "--output", "-o", help="design JSON 落盘路径（缺省只回信封）"),
    param: list[str] = typer.Option(None, "--param", "-p", help="生成器参数 名=值（可多次，补映射缺口）"),  # noqa: B008
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """run 最优参数→PCBDesign JSON 草稿桥（SO §6③ A8；接 kicad pcb→drc 链）。

    缺必需参数时如实报清单不臆造默认几何（铁律 7）。

    示例：rfauto kicad design-from-run runs/x --kind hairpin_bpf -o design.json
    """
    from rfauto.cli.domains._core import _kv_floats
    from rfauto.service.design_bridge_service import run_to_design_json

    overrides = _kv_floats(list(param) if param else [], "--param")
    result = run_to_design_json(
        run_dir, kind=kind or None, output=output or None,
        param_overrides=overrides)
    _emit(result, "design 桥失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ design JSON 草稿（model={result.get('model')}"
                  f" kind={result.get('kind')}）[/green]")
    design = result.get("design") or {}
    console.print(f"  board={design.get('board_size')} "
                  f"traces={len(design.get('traces') or [])} "
                  f"pads={len(design.get('pads') or [])}")
    if result.get("output"):
        console.print(f"  落盘: {result['output']}")
    for step in result.get("next_steps") or []:
        console.print(f"  下一步: {step}")


@kicad_app.command("pcb")
def kicad_pcb(
    design_json: str = typer.Argument(..., help="PCB 设计描述 JSON（PCBDesign schema）"),
    output: str = typer.Option(..., "--output", "-o", help="输出 .kicad_pcb 路径"),
) -> None:
    """从 JSON 设计描述生成 KiCad PCB（子进程调用 KiCad Python 3.11）。

    JSON 按 PCBDesign schema，最小示例（微带功分板）：board_size 为
    宽/高二元组（如 50×30 mm）；traces 列表各含 name/layer/width_mm
    与 points 折线点列（如 tl1：F.Cu、0.33mm、从（10,15）到（30,15）。
    """
    from rfauto.adapters.kicad_pcell import PCBDesign, generate_pcb

    try:
        design = PCBDesign.from_dict(json.loads(Path(design_json).read_text(encoding="utf-8")))
    except FileNotFoundError:
        console.print(f"[red]✗ 设计描述文件不存在: {design_json}[/red]")
        raise typer.Exit(code=1) from None
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        console.print(f"[red]✗ 设计描述解析失败: {e}[/red]")
        raise typer.Exit(code=1) from None

    result = generate_pcb(output, design)
    if result.success:
        console.print(f"[green]✓ PCB 已生成[/green]  {result.output_path}")
    else:
        console.print("[red]✗ PCB 生成失败[/red]")
        console.print(f"  {result.message}")
        raise typer.Exit(code=1)


@kicad_app.command("drc")
def kicad_drc_cmd(
    pcb: str = typer.Argument(..., help="要检查的 .kicad_pcb 文件"),
    report: str = typer.Option(None, "--report", "-r", help="DRC 报告输出路径"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """KiCad DRC/RF 规则门禁（errors 阻断，warnings 告警）。"""
    from rfauto.adapters.kicad_drc import generate_drc_report, run_drc_kicad

    result = run_drc_kicad(pcb)
    if report:
        generate_drc_report(result, report)
    if json_output:
        # VI-5 W6-B：--json 信封（报告落盘副作用保持；未通过 exit 1 语义保持；
        # 失败信封带 errors 摘要——与 _emit 失败信封 errors 键同构）
        envelope: dict = {
            "ok": result.passed, "pcb": pcb, "report": report,
            "n_errors": result.n_errors, "n_warnings": result.n_warnings,
            "violations": [{"severity": getattr(v, "severity", "?"),
                            "rule": getattr(v, "rule_name", "?"),
                            "message": getattr(v, "message", "")}
                           for v in result.violations],
        }
        if not result.passed:
            envelope["errors"] = [
                f"DRC 未通过（{result.n_errors} errors / "
                f"{result.n_warnings} warnings）"]
        console.print_json(json.dumps(envelope, ensure_ascii=False, default=str))
        if not result.passed:
            raise typer.Exit(code=1)
        return
    if report:
        console.print(f"  报告: {report}")

    status = (
        "[green]✓ DRC 通过[/green]" if result.passed
        else f"[red]✗ DRC 未通过（{result.n_errors} errors / {result.n_warnings} warnings）[/red]"
    )
    console.print(status)
    for v in result.violations:
        console.print(f"  [{v.severity}] {v.rule_name}: {v.message}")
    if not result.passed:
        raise typer.Exit(code=1)


@kicad_app.command("extract")
def kicad_extract_cmd(
    pcb: str = typer.Argument(..., help=".kicad_pcb 文件"),
    output: str = typer.Option(None, "--output", "-o", help="提取产物 JSON 输出路径（缺省打印）"),
    kicad_python: str = typer.Option(None, "--kicad-python",
                                     help="KiCad 自带 Python（缺省 E:\\KiCad\\bin\\python.exe）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """从 .kicad_pcb 提取叠层/走线/过孔/板框/zone/footprint（B6 stage-2，子进程 KiCad Python）。"""
    from rfauto.service.kicad_em_service import extract_pcb_facts

    result = extract_pcb_facts(pcb, kicad_python=kicad_python)
    if json_output:
        # VI-5 W6-B：--json 信封（--output 落盘副作用保持）
        if output:
            text = json.dumps(result, indent=2, ensure_ascii=False, default=str)
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(text, encoding="utf-8")
        _emit(result, "提取失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 提取失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    text = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text, encoding="utf-8")
        board = result.get("board") or {}
        console.print(f"[green]✓ 提取完成[/green] → {output}"
                      f"（走线 {len(result.get('traces') or [])} / zone {len(result.get('zones') or [])}"
                      f" / footprint {len(result.get('footprints') or [])}，"
                      f"{board.get('layer_count', '?')} 层）")
    else:
        console.print_json(text)


@kicad_app.command("gerber")
def kicad_gerber_cmd(
    pcb: str = typer.Argument(..., help=".kicad_pcb 板文件路径"),
    out_dir: str = typer.Option(..., "--out", "-o", help="Gerber 产物输出目录"),
    kicad_python: str = typer.Option(None, "--kicad-python",
                                     help="KiCad 自带 Python 显式路径（缺省走 env 与缺省位解析）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 信封输出（供门禁/脚本消费）"),
) -> None:
    """KiCad 板 → Gerber X2 + Excellon 制造交付包导出（LC-1，子进程 KiCad Python）。

    KiCad 缺失 → ok=False 信封报环境缺失（不静默 skip）；X2 FileFunction
    逐角色核验，gerbonara 可用时交叉读回。
    """
    from rfauto.service.pcb_export_service import export_pcb_gerber_x2

    result = export_pcb_gerber_x2(pcb, out_dir, kicad_python=kicad_python)
    _emit(result, "Gerber 导出失败", json_output=json_output)
    if json_output:
        return
    files = result.get("files") or {}
    console.print(f"[green]✓ Gerber 导出完成[/green]  文件 {len(files)} 个 → {result.get('out_dir')}")
    for role, path in files.items():
        console.print(f"  {role}: {path}")
    drills = result.get("drill_files") or []
    if drills:
        console.print(f"  钻孔: {len(drills)} 文件")
    if result.get("job_file"):
        console.print(f"  job: {result['job_file']}")
    missing = result.get("missing_x2") or []
    if missing:
        console.print(f"[yellow]⚠ X2 属性缺失角色: {', '.join(missing)}[/yellow]")


@kicad_app.command("optimize")
def kicad_optimize_cmd(
    pcb: str = typer.Argument(..., help=".kicad_pcb 文件"),
    target_z0: float = typer.Option(None, "--target-z0", help="目标阻抗 Ω（缺省 50）"),
    freq: float = typer.Option(None, "--freq", "-f", help="工作频率 GHz（缺省 2.5）"),
    tol: float = typer.Option(None, "--tol", help="判据容差 Ω（缺省 2）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """PCB 提取 → CPWG 闭式代理寻优环（|z0−target|≤tol 判据；FAIL 附确定性修正 w*）。"""
    from rfauto.service.kicad_em_service import optimize_cpw_from_pcb

    result = optimize_cpw_from_pcb(pcb, target_z0_ohm=target_z0, freq_ghz=freq,
                                   z0_tol_ohm=tol)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        raise typer.Exit(code=0 if result.get("ok") and result.get("verdict") == "PASS" else 1)
    if not result.get("ok"):
        console.print(f"[red]✗ 寻优失败（{result.get('stage', 'optimize')}）[/red]")
        for err in result.get("errors") or [result.get("error")]:
            if err:
                console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    d, a, o = result["design"], result["analysis"], result["optimization"]
    color = "green" if result["verdict"] == "PASS" else "red"
    console.print(f"[{color}]● CPWG 寻优 {result['verdict']}[/{color}]（容差 ±{result['z0_tol_ohm']} Ω）")
    console.print(f"  提取: w={d['w_mm']} mm  gap={d['gap_mm']} mm  h={d['h_mm']} mm  er={d['er']}")
    console.print(f"  z0_extracted={a['z0_extracted_ohm']} Ω  εeff={a['eps_eff_extracted']}")
    console.print(f"  w*={o['w_opt_mm']:.4f} mm → z0={o['z0_opt_ohm']} Ω  Δw={o['delta_w_mm']} mm")
    if result["verdict"] != "PASS":
        raise typer.Exit(code=1)
