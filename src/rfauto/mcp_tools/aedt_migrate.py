"""aedt_migrate 批量迁移通道 MCP 两薄壳（aurora_r AM-S4，2026-11-10）。

S1 service docstring 挂账处方原文落位：aedt_migrate_run /
aedt_migrate_report 零逻辑转发 service/aedt_migrate_service 单源（规则
4；信封进出在 service，本文件只做参数透传+异常兜底），与 CLI
``rfauto aedt-migrate run``/``status``/``report`` 同源（run→migrate_
batch；report→read_migration_report 全文——CLI status 的有损摘要投影
不进 agent 面，agent 消费全文自行裁剪）。

注解分类（_annotations.py 单源表同笔补条目）：
- aedt_migrate_run = mutating_non_destructive（migrate_batch 落
  inventory.json+reports/ 写 work_root；原 .aedt 只读铁律由 service
  全链保证，零删除既有产物）；
- aedt_migrate_report = read_only（报告文件纯读）。

零 stdout 红线（#278）：本文件禁止 print——stdio 传输把 stdout 当
JSON-RPC 协议信道。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "aedt_migrate_report",
    "aedt_migrate_run",
]


@mcp.tool
def aedt_migrate_run(inputs: list[str],
                     work_root: str | None = None) -> dict[str, Any]:
    """批量迁移老版本 .aedt 工程到 AEDT 2025 R1（五阶段决策树）。

    什么时候用：合作者遗留的老版本 .aedt 批量迁移——逐工程五阶段
    （S0 盘点备份规划 → S1 直开 → S2 体检 → S3 新旧结果对比 → S4 桥接
    （2023 R2 未配置如实 BLOCKED）→ S5 抢救），每工程出结构化迁移报告。
    原 .aedt 只读铁律：全链零写原件。幂等：MIGRATED_* 重跑跳过；
    FAILED_*/BLOCKED_* 允许重跑；verdict 9 枚举诚实终态零凑绿；执行器
    未注入时逐工程 error 行响亮报（不伪造 verdict）；单工程故障不炸
    整批。

    Args:
        inputs: .aedt 文件或目录路径列表（目录递归收集 *.aedt）。
        work_root: 产物根覆盖；None=读配置缺省（configs/settings.
            local.yaml aedt_migrate 块，缺省 runs/aedt_migrate）。

    Returns:
        dict: ok=True 时 {ok, work_root, inventory_path, total, results,
        counts}——results 逐工程行（迁移行/幂等跳过行/error 行），
        counts=verdict 直方图+skipped/error 计数；失败 → ok=False
        errors（恒 list[str]）。
    """
    from rfauto.service.aedt_migrate_service import migrate_batch

    try:
        return migrate_batch(inputs, work_root=work_root)
    except Exception as e:  # 观测面兜底（#105）：异常进信封不炸会话
        return error_envelope(str(e))


@mcp.tool
def aedt_migrate_report(report_path: str) -> dict[str, Any]:
    """读单份迁移报告 JSON 全文（结构化审计面）。

    什么时候用：aedt_migrate_run 之后要读某工程的迁移报告全文——
    schema/project/source_sha256/stage_reached/verdict/checks/messages/
    engine_identity/comparison/rescue/timestamps 逐键原文（verdict 9
    枚举语义见 aedt_migrate_run 描述）。与 CLI
    ``rfauto aedt-migrate report`` 同源（service.read_migration_report）。
    只读零副作用，可安全调用。文件不存在/非 JSON/非迁移报告（缺
    verdict 键）→ ok=False errors 信封零静默。只读无时序约束。

    Args:
        report_path: 迁移报告 JSON 路径（work_root/reports/ 下）。

    Returns:
        dict: ok=True 时 {ok, report=报告全文 dict}；失败 → ok=False
        errors。
    """
    from rfauto.service.aedt_migrate_service import read_migration_report

    try:
        report = read_migration_report(report_path)
        if not isinstance(report, dict):
            return error_envelope(
                f"迁移报告必须是 JSON 对象: {report_path}")
        if "verdict" not in report:
            return error_envelope(
                f"文件可读但不是迁移报告（缺 verdict 键）: {report_path}")
        return ok_envelope(report=report)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))
