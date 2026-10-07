"""fab 子命令组——HFSS → 可机加交付包（T43，自 E:\\协助调研\\cad导出 原型吸收）.

薄壳层，零业务逻辑（军规 10）——全部转发 service/fab_export_service 的
JSON 信封函数：
  rfauto fab go        一键：变量 JSON / HFSS → 成品交付包（自动审计门禁）
  rfauto fab pipeline  离线端到端轻量链（无 AEDT）
  rfauto fab snapshot  变量 JSON → dims.json（尺寸真源快照）
  rfauto fab draw      dims.json → DXF 图纸（+PDF）
  rfauto fab audit     对交付目录跑 A1–A12 审计
  rfauto fab pack      组装交付目录
  rfauto fab rules     显示工艺公差规则库
  rfauto fab catalog   波导/法兰/配合标准库
  rfauto fab export    连接 HFSS 导出 x_t/step（需 pyAEDT+AEDT）

审计 FAIL = 退出码 1（禁止发图口径与原型一致）；export 等需 AEDT 的
命令在缺环境时以 ok=False 信封 + 退出码 2 如实报缺。

VI-5 W2-C --json 归一（2026-10-05）：九命令自始即 JSON 信封直出（本文件
_emit / typer.echo json.dumps），故 --json 为归一兼容旗标——接受但两形态
同输出（缺省路径逐字节不变铁纪律优先于纯切换形态）。
"""

from __future__ import annotations

import json

import typer

fab_app = typer.Typer(help="HFSS → 可机加交付包（STEP/x_t + DXF 图 + 审计门禁，T43）")

# VI-5 W2-C：归一兼容旗标（fab 九命令缺省即 JSON 信封，旗标两形态同输出）
_JSON_COMPAT_HELP = (
    "JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"
)


def _split_list(spec: str) -> list[str]:
    """逗号分隔串 → list（空串 → 空表）。"""
    return [t.strip() for t in spec.split(",") if t.strip()]


def _emit(result: dict, ok_code: int = 0) -> None:
    """JSON 信封直出 + 门色退出码（审计 FAIL=1、环境缺失=2 由 result 定）。"""
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise typer.Exit(code=2 if result.get("needs") else 1)
    raise typer.Exit(code=ok_code)


@fab_app.command("go")
def go_cmd(
    vars_path: str = typer.Option("", "--vars", help="变量 JSON（离线：{part_id,rev,variables:{name:raw}}）"),
    project: str = typer.Option("", "--project", help="HFSS .aedt 工程路径（真机链，需 AEDT）"),
    design: str = typer.Option("", "--design", help="HFSS 设计名"),
    out_dir: str = typer.Option("", "--out", help="交付目录（缺省 <work 同级>/fab_<part>_<rev>）"),
    work_dir: str = typer.Option("", "--work", help="工作目录（中间产物，缺省 <out>/_work）"),
    part_name: str = typer.Option("part", "--part-name", help="实体导出名（真机链）"),
    rules: str = typer.Option("", "--rules", help="规则库 YAML（缺省内置 xixia_rf_v0）"),
    material: str = typer.Option("AL6061-T6", "--material", help="材料标记"),
    heal: bool = typer.Option(False, "--heal", help="真机链启用保守 heal"),
    keep: str = typer.Option("", "--keep", help="真机链白名单对象（逗号分隔）"),
    drop: str = typer.Option("", "--drop", help="真机链剔除对象（逗号分隔）"),
    open_folder: bool = typer.Option(False, "--open", help="完成后打开交付目录"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """一键交付包：--vars 离线链 / --project 真机链（自动审计，FAIL 禁发图）."""
    from rfauto.service.fab_export_service import fab_go_from_hfss, fab_go_from_vars

    if vars_path:
        result = fab_go_from_vars(
            vars_path,
            out_dir or None,
            rules_path=rules or None,
            work_dir=work_dir or None,
            material=material,
            open_folder=open_folder,
        )
    elif project or design:
        result = fab_go_from_hfss(
            project or None,
            design or None,
            out_dir or "fab_out",
            part_name=part_name,
            rules_path=rules or None,
            material=material,
            keep=_split_list(keep) or None,
            drop=_split_list(drop) or None,
            do_heal=heal,
            open_folder=open_folder,
        )
    else:
        # VI-5 W2-C：--json 下入参缺失也走信封（退出码 2 语义保持）
        if json_output:
            typer.echo(json.dumps({"ok": False, "errors": ["需要 --vars 或 --project"]},
                                  ensure_ascii=False, indent=2))
        else:
            typer.echo("需要 --vars 或 --project", err=True)
        raise typer.Exit(code=2)
    _emit(result)


@fab_app.command("pipeline")
def pipeline_cmd(
    vars_path: str = typer.Option(..., "--vars", help="变量 JSON"),
    work_dir: str = typer.Option(..., "--work", help="工作目录（中间产物）"),
    out_dir: str = typer.Option("", "--out", help="交付目录（缺省 <work>/fab_<part>_<rev>）"),
    rules: str = typer.Option("", "--rules", help="规则库 YAML"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """离线端到端轻量链：vars → dims → 轮廓/图纸 DXF → 审计 → 打包."""
    from rfauto.service.fab_export_service import fab_pipeline

    _emit(fab_pipeline(vars_path, work_dir, out_dir or None, rules_path=rules or None))


@fab_app.command("snapshot")
def snapshot_cmd(
    vars_path: str = typer.Option(..., "--vars", help="变量 JSON"),
    out: str = typer.Option(..., "--out", help="输出 dims.json 路径"),
    part_id: str = typer.Option("", "--part-id", help="零件号（缺省取 JSON part_id 或文件名）"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """变量 JSON → dims.json（单位强制 mm，raw 字符串保真）."""
    from rfauto.service.fab_export_service import fab_snapshot

    _emit(fab_snapshot(vars_path, out, part_id=part_id or None))


@fab_app.command("draw")
def draw_cmd(
    dims: str = typer.Option(..., "--dims", help="dims.json 路径"),
    out: str = typer.Option(..., "--out", help="输出 DXF 路径"),
    rules: str = typer.Option("", "--rules", help="规则库 YAML"),
    name: str = typer.Option("", "--name", help="图样名称（缺省 part_id）"),
    material: str = typer.Option("AL6061-T6", "--material", help="材料标记"),
    pdf: bool = typer.Option(False, "--pdf", help="同时导出 PDF（需 matplotlib）"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """dims.json → GB 图框 DXF 图纸（标注值只取 dims，禁止测量回填）."""
    from rfauto.service.fab_export_service import fab_draw

    result = fab_draw(
        dims, out,
        rules_path=rules or None, part_name=name or None,
        material=material, with_pdf=pdf,
    )
    if result.get("pdf_skipped"):
        typer.echo("warn: pdf skipped (need matplotlib)", err=True)
    _emit(result)


@fab_app.command("audit")
def audit_cmd(
    package: str = typer.Option(..., "--package", help="交付目录（含 dims.json）"),
    rules: str = typer.Option("", "--rules", help="规则库 YAML"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """A1–A12 审计门禁（FAIL=退出码 1，禁止发图）."""
    from rfauto.service.fab_export_service import fab_audit

    result = fab_audit(package, rules_path=rules or None)
    if result.get("ok") and result.get("geometry_synthetic"):
        typer.echo("warn: geometry_summary.json missing — geometric checks synthetic", err=True)
    _emit(result)


@fab_app.command("pack")
def pack_cmd(
    dims: str = typer.Option(..., "--dims", help="dims.json 路径"),
    out: str = typer.Option(..., "--out", help="交付目录"),
    step: str = typer.Option("", "--step", help="STEP 源文件"),
    xt: str = typer.Option("", "--xt", help="x_t 源文件"),
    drawing: str = typer.Option("", "--drawing", help="DXF 图纸源文件"),
    chars: str = typer.Option("", "--chars", help="critical_chars.csv 源文件"),
    rules: str = typer.Option("", "--rules", help="规则库 YAML"),
    notes: bool = typer.Option(False, "--notes", help="写 drawing_notes.txt"),
    force_fail: bool = typer.Option(False, "--force-fail", help="强制审计 FAIL（演练禁止发图归档）"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """组装交付目录（manifest+哈希+审计报告；audit FAIL=退出码 1）."""
    from rfauto.service.fab_export_service import fab_pack

    _emit(fab_pack(
        dims, out,
        step=step or None, xt=xt or None, drawing=drawing or None,
        chars=chars or None, rules_path=rules or None,
        with_notes=notes, force_fail=force_fail,
    ))


@fab_app.command("rules")
def rules_cmd(
    file: str = typer.Option("", "--file", help="规则库 YAML（缺省内置 xixia_rf_v0）"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """显示工艺公差规则库（公差类/审计阈值/表面处理）."""
    from rfauto.service.fab_export_service import fab_rules

    result = fab_rules(file or None)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@fab_app.command("catalog")
def catalog_cmd(json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP)) -> None:
    """波导(WR/BJ)/法兰/嘉立创配合带/Kerr 规则标准库目录."""
    from rfauto.service.fab_export_service import fab_catalog

    result = fab_catalog()
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@fab_app.command("export")
def export_cmd(
    project: str = typer.Option("", "--project", help="HFSS .aedt 工程路径"),
    design: str = typer.Option("", "--design", help="HFSS 设计名"),
    out: str = typer.Option(..., "--out", help="输出目录"),
    part_name: str = typer.Option("part", "--part-name", help="实体导出名"),
    heal: bool = typer.Option(False, "--heal", help="启用保守 heal"),
    keep: str = typer.Option("", "--keep", help="白名单对象（逗号分隔）"),
    drop: str = typer.Option("", "--drop", help="剔除对象（逗号分隔）"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """连接 HFSS 导出 x_t/step + dims 快照（需 rfauto（hfss extra）+AEDT）."""
    from rfauto.service.fab_export_service import fab_export_geometry

    _emit(fab_export_geometry(
        out,
        project=project or None,
        design=design or None,
        part_name=part_name,
        do_heal=heal,
        keep=_split_list(keep) or None,
        drop=_split_list(drop) or None,
    ))
