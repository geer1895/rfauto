"""aedt-migrate 子应用——老版本 .aedt 工程批量迁移 CLI 薄壳
（aurora_r AM-S4，2026-11-10；设计稿 aedt_migrate_design_handoff §1/§2）。

零逻辑转发 service/aedt_migrate_service（规则 4 薄壳；铁律 7 不涉——
决策树路由/对比判读全在 service+executor 确定性内核）：
  rfauto aedt-migrate run --input <file|dir>（可多次）[--work-root DIR] [--json]
  rfauto aedt-migrate status --report <path> [--json]
  rfauto aedt-migrate report --report <path> [--json]

三叶全部带 --json（合流期"新面必红清单"①：新 CLI 叶必须带 --json 旗
标）；路径参数 str 注解（#269，B008 家法 noqa 同 citi segments --name
先例）；信封走 service.envelope ok_envelope/error_envelope 构造器
（AU-2 单源，S1 service 挂账处方原文）；usage 类错误（--input 缺失/
报告文件不存在·不可读·非迁移报告）走 _emit_usage_error（exit 2，
#ge1㉙：--json 下失败路径禁红字裸文本）。

verdict 枚举 9 值（S1 单源 MIGRATION_VERDICTS，--json 原样透传）：\
MIGRATED_DIRECT_PASS / MIGRATED_DIRECT_FAIL_COMPARISON /
MIGRATED_VIA_BRIDGE_PASS / NEEDS_CAD_REEXPORT / NO_BASELINE /
FAILED_OPEN / FAILED_HEALTH / FAILED_BRIDGE / BLOCKED_NO_BRIDGE_HOST
——诚实终态全展示，CLI 层零重试零凑绿（#122）。

run 面如实边界：本席只接编排薄壳（S1 处方"run 消费 migrate_batch"
原文），阶段执行器（direct_open/health/compare）由真机通道注入——
CLI 直跑时 migrate_batch 按必注入校验逐工程记 error 行（响亮
ValueError 入行，S1 service 契约），不伪造 verdict；真机执行器接线
归后续席位（设计稿 §5 表 S3/S5）。原 .aedt 只读铁律由 service 全链
保证（S0 纯读+一切产物落 work_root）。

注册形态（AM-S4 本席即接线席）：独立根 ``aedt_migrate_app``，cli/main.py
re-export + ``app.add_typer(aedt_migrate_app, name="aedt-migrate")``
（citi 同款两步式；注册名连字符）。零撞名自查 2026-11-10：全 CLI 树
无 aedt-migrate/aedt_migrate 前缀组或命令，唯一近名 hfss-import=工程
导入器（读变量/扫参→设计规格）语义≠版本迁移通道。HELP_PANEL_OF 归
属"运维与开发"（AEDT 版本迁移=工具链/环境维护动作，remote/solvers
同域；非器件设计非数据解析面）。
"""

from __future__ import annotations

import json
from typing import Any

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import console as console
from rfauto.service.envelope import ok_envelope as ok_envelope

aedt_migrate_app = typer.Typer(
    help="老版本 .aedt 工程批量迁移：五阶段决策树+迁移报告（help 明细见各叶）")


def _load_migration_report(report: str, *, json_output: bool) -> dict[str, Any]:
    """读迁移报告文件并做迁移报告身份核验（status/report 两叶共用）。

    IO 类问题（不存在/不可读/非 JSON 对象）走 _load_json_file（exit 2，
    #ge1㉙ 同族）；可读但无 verdict 键=不是迁移报告（拿错文件），同
    usage 类错误 exit 2 如实报——两叶对"读到了什么"不凑不猜（#122）。
    """
    from rfauto.cli.domains._core import _load_json_file  # lazy: 叶内延迟导入（棘轮口径）

    data = _load_json_file(report, "迁移报告", json_output=json_output)
    if "verdict" not in data:
        _emit_usage_error(
            f"文件可读但不是迁移报告（缺 verdict 键）: {report}",
            json_output=json_output)
    return data


def _verdict_color(verdict: str) -> str:
    """人读分支 verdict 着色（诚实语义：PASS 绿/失败终态红/前提不满足黄）。"""
    if verdict.startswith("MIGRATED_") and not verdict.endswith("FAIL_COMPARISON"):
        return "green"
    if verdict.startswith("FAILED_") or verdict.endswith("FAIL_COMPARISON"):
        return "red"
    return "yellow"


@aedt_migrate_app.command("run")
def aedt_migrate_run_cmd(
    inputs: list[str] = typer.Option(  # noqa: B008
        None, "--input", help=".aedt 文件或目录（递归收集 *.aedt，可多次）"),
    work_root: str | None = typer.Option(
        None, "--work-root", help="产物根覆盖（缺省读配置 work_root）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """批量迁移编排：收集→S0 盘点→逐工程决策树→报告落 reports。"""
    from rfauto.service.aedt_migrate_service import migrate_batch  # lazy: 叶内延迟导入（棘轮口径）

    if not inputs:
        _emit_usage_error(
            "--input 至少提供一个 .aedt 文件或目录", json_output=json_output)
    result = migrate_batch(inputs, work_root=work_root)
    _emit(result, "aedt-migrate 批量迁移失败", json_output=json_output)
    if json_output:
        return
    counts = result.get("counts") or {}
    console.print(
        f"[green]✓[/green] 批量完成 {result.get('total')} 工程，"
        f"产物根 {result.get('work_root')}")
    console.print(f"  盘点: {result.get('inventory_path')}")
    if counts:
        console.print(f"  counts: {counts}")
    for row in result.get("results") or []:
        if row.get("skipped"):
            console.print(
                f"  [cyan]skipped[/cyan] {row.get('project')} 幂等跳过"
                f"（prior={row.get('prior_verdict')}）")
        elif row.get("ok"):
            console.print(
                f"  [{_verdict_color(str(row.get('verdict')))}]"
                f"{row.get('verdict')}[/] {row.get('project')}"
                f" @ {row.get('stage_reached')}")
        else:
            console.print(
                f"  [red]✗[/red] {row.get('project')} "
                f"{'; '.join(str(e) for e in row.get('errors') or [])}")


def _report_summary(report: dict[str, Any], report_path: str) -> dict[str, Any]:
    """status 叶结构化摘要信封字段（报告 mandated 键集的有损投影——
    全文消费走 report 叶/--json 原样，不在此复制全文）。"""
    return ok_envelope(
        report_path=report_path,
        schema=report.get("schema"),
        project=report.get("project"),
        project_path=report.get("project_path"),
        source_sha256=report.get("source_sha256"),
        backup_path=report.get("backup_path"),
        source_version_best_effort=report.get("source_version_best_effort"),
        stage_reached=report.get("stage_reached"),
        verdict=report.get("verdict"),
        checks=report.get("checks"),
        engine_identity=report.get("engine_identity"),
        comparison=report.get("comparison"),
        rescue=report.get("rescue"),
        n_messages=len(report.get("messages") or []),
    )


@aedt_migrate_app.command("status")
def aedt_migrate_status_cmd(
    report: str = typer.Option(
        ..., "--report", help="迁移报告 JSON 路径（work_root/reports/ 下）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """迁移报告结构化摘要（verdict/阶段链/体检/对比/引擎指纹）。"""
    data = _load_migration_report(report, json_output=json_output)
    envelope = _report_summary(data, report)
    _emit(envelope, "迁移报告读取失败", json_output=json_output)
    if json_output:
        return
    verdict = str(envelope.get("verdict"))
    console.print(
        f"[{_verdict_color(verdict)}]{verdict}[/] {envelope.get('project')}"
        f"  stage={envelope.get('stage_reached')}")
    console.print(f"  报告: {report}")
    console.print(f"  原件: {envelope.get('project_path')}")
    console.print(f"  体检: {envelope.get('checks')}")
    comparison = envelope.get("comparison")
    console.print(
        f"  对比: {'(无基线面)' if not comparison else comparison.get('deltas')}")


@aedt_migrate_app.command("report")
def aedt_migrate_report_cmd(
    report: str = typer.Option(
        ..., "--report", help="迁移报告 JSON 路径（work_root/reports/ 下）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """迁移报告人读全文（分节 rich 面；--json=报告原文逐键透传）。"""
    data = _load_migration_report(report, json_output=json_output)
    # --json 下原文逐键透传（报告 schema mandated 键集在 service 单源，
    # CLI 不裁面不加工——审计消费面要全文）；人读分支分节渲染。
    if json_output:
        console.print_json(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return
    verdict = str(data.get("verdict"))
    console.print(f"[bold]迁移报告：{data.get('project')}[/bold]")
    console.print(
        f"  verdict: [{_verdict_color(verdict)}]{verdict}[/]"
        f"   stage_reached: {data.get('stage_reached')}")
    console.print(f"  schema: {data.get('schema')}")
    console.print(f"  原件（只读）: {data.get('project_path')}")
    console.print(f"  sha256: {data.get('source_sha256')}")
    console.print(f"  备份规划: {data.get('backup_path')}")
    console.print(f"  版本指纹（尽力读）: {data.get('source_version_best_effort')}")
    engine = data.get("engine_identity") or {}
    console.print(f"  引擎指纹: {engine}")
    console.print(f"  体检: {data.get('checks')}")
    comparison = data.get("comparison")
    if comparison is None:
        console.print("  对比: —（未达对比阶段或无基线，见 verdict/messages）")
    else:
        console.print(f"  对比: {json.dumps(comparison, ensure_ascii=False)}")
    rescue = data.get("rescue")
    if rescue is not None:
        console.print(f"  抢救: {json.dumps(rescue, ensure_ascii=False)}")
    messages = data.get("messages") or []
    if messages:
        console.print(f"  消息（{len(messages)} 条）:")
        for m in messages:
            console.print(f"    - {m}")
