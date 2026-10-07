"""explain_run/list_composable_templates（run 解释 + 组合模板清单）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp


@mcp.tool
def explain_run(run_dir: str, playbook_path: str | None = None) -> dict[str, Any]:
    """失败指纹解释（explain 域）：run 目录 → 确定性指纹匹配候选根因族。

    DP-17 W2。多证并击只出候选族（按命中数降序）不下黑箱结论，零 LLM；
    不用于自动修复（动作走 self_heal_run/三层 Gate）。run 目录缺失 →
    ok=False 如实。无副作用（只读 run 产物与 playbook），只读无时序约束。

    Args:
        run_dir: run 目录（runs/<id>）
        playbook_path: playbook.yaml 路径（缺省 knowledge/diagnostics/playbook.yaml）

    Returns:
        dict: {ok, run_dir, matches:[{root_cause_family, evidence, pit_refs}], ...}
    """
    from rfauto.service.explain_run import explain_run
    return explain_run(run_dir, playbook_path=playbook_path)


@mcp.tool
def list_composable_templates() -> dict[str, Any]:
    """列出已注册组合契约模板与 pin schema（DP-8 opt-in 台账）。

    只读台账零副作用；空注册如实 n_templates=0，不用于模板渲染执行。
    读取失败 → ok=False。只读无时序约束。

    Args:
        （无参数）

    Returns:
        dict: {ok, result: {templates: [{template, port_pins,
               schema_declared}], n_templates}}——port_pins 每 pin 含
               pin_id/position（局部坐标米）/direction（外法向）/
               z_ref_ohm（None=闭式同源注入）/ref_plane_offset_m/
               port_type（lumped|msl|waveguide|field）/n_modes（预留）/
               cross_section（截面指纹）
    """
    from rfauto.service.compose_service import list_composable_templates
    try:
        return list_composable_templates()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def error_hints_lookup(message: str) -> dict[str, Any]:
    """错误提示检索（explain 域）：错误消息文本 → 可行动 hint 表（零 LLM）。

    按仓库高频错误指纹（子串或正则）匹配，命中即返回 hint（可行动修复
    建议）、refs（坑号/docs 指针）与 severity，按 error 大于 warn 大于
    info 排序；未命中返回空表如实不编造。与 CLI --json 失败信封的
    hints 键同源同语义（error_hints_service 单源）。不用于异常捕获替身。
    无副作用可安全调用，只读无时序约束。

    Args:
        message: 错误消息文本（异常类型名与消息原文一并粘贴更佳）

    Returns:
        dict: {ok, hits: [{pattern, match, hint, refs, severity} 列表],
        n_hits, source}
    """
    from rfauto.service.error_hints_service import hint_for_message
    return hint_for_message(message)
