"""vna_offline_replay/vna_en_report/report_narrative（VNA 回放/En 报告/F9 叙述位）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 30. VNA 软侧离线回放（补强17，0bx② 透传薄壳） ──────────────────────────

@mcp.tool
def vna_offline_replay(
    measured_s2p: str,
    sim_s2p: str | None = None,
    threshold_db: float = 3.0,
    session_path: str | None = None,
) -> dict[str, Any]:
    """VNA 离线回放（vna 域）：历史 Touchstone → 采集→校准→相关全链。

    mock 仪表供数零硬件（补强17）；无硬件副作用，session_path 给定时
    best-effort 落会话 JSONL；不用于真机采集替代。测量文件缺失 →
    ok=False 如实。只读计算面（会话落盘除外），无时序约束。

    Args:
        measured_s2p: 历史测量 Touchstone（供 MockVNAInstrument）
        sim_s2p: 仿真 Touchstone（缺省=同 measured_s2p 自比对）
        threshold_db: 相关性 dB 偏差门
        session_path: 会话 JSONL 落盘路径（可选）

    Returns:
        dict: {ok, connect, calibrate, capture, calibration, correlation}
    """
    from rfauto.service.api import vna_offline_replay as _replay
    return _replay(measured_s2p, sim_s2p, threshold_db=threshold_db,
                   session_path=session_path)


# ─── 30b. DP-11 VNA 测量闭环：En 相关性报告（measurement/en_report 薄壳） ─────

@mcp.tool
def vna_en_report(
    lab_s2p: str,
    ref_s2p: str,
    traces: list[str] | None = None,
    delta_t_c: float | None = None,
    anchor_uncertainty_db: float | None = None,
    hfss_residual_db: float | None = None,
    markdown_path: str | None = None,
) -> dict[str, Any]:
    """En 计量学相关性报告（vna 域）：实测 vs 参考 → |En|≤1 判定（DP-11）。

    深谷自动切线性域（#370 口径）。U_meas=GUM 预算表
    （configs/uncertainty_budgets.yaml 默认模板），U_sim=锚 uncertainty→
    HFSS 仲裁残差→兜底（source=fallback 如实标注）；频轴对齐 argmin
    最近邻+ulp 容差（#287/#294）；不用于仪器检定替代。文件缺失/迹线
    缺失 → ok=False 如实。只读计算面（markdown 落盘除外），无时序约束。

    Args:
        lab_s2p: 实测 Touchstone
        ref_s2p: 仿真参考 Touchstone
        traces: 迹线名列表（缺省 ["S11","S21"]）
        delta_t_c: 温差覆盖（°C；缺省用预算表 delta_t_c）
        anchor_uncertainty_db: 锚不确定度（U_sim 第一优先）
        hfss_residual_db: HFSS 仲裁残差（U_sim 第二优先）
        markdown_path: Markdown 报告落盘路径（可选）

    Returns:
        dict: {ok, traces: {…}, summary, markdown}
    """
    from rfauto.service.vna_service import vna_en_report as _report
    return _report(
        lab_s2p, ref_s2p,
        traces=tuple(traces) if traces else ("S11", "S21"),
        delta_t_c=delta_t_c,
        anchor_uncertainty_db=anchor_uncertainty_db,
        hfss_residual_db=hfss_residual_db,
        markdown_path=markdown_path)


# ─── 31. F9 报告叙述位 / F11 经验记忆（0bj / 0z 薄壳） ────────────────────────

@mcp.tool
def report_narrative(
    run_id: str,
    narrative: str | None = None,
    on_unauthorized: str = "reject",
) -> dict[str, Any]:
    """报告叙述（vna 域）：run 白名单 → 确定性模板叙述/外来叙述审计。

    F9。无副作用；不触发任何 LLM 调用（LLM 只作 service 层可注入接口）；
    narrative 给定时返回 canonical 化文本 + violations（未授权数字定位），
    不用于免审数字注入。run 缺失 → ok=False 如实。只读无时序约束。

    Args:
        run_id: 已完成 run（runs/<run_id>/meta.json 须存在）
        narrative: 外来叙述文本；缺省=生成模板叙述
        on_unauthorized: reject | fallback（仅 LLM 路径生效）

    Returns:
        dict: {ok, run_id, mode, narrative, violations, provenance, ...}
    """
    from rfauto.service.report_narrative import report_narrative_for_run
    return report_narrative_for_run(run_id, narrative=narrative,
                                    on_unauthorized=on_unauthorized)
