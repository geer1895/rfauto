"""pdn_analyze/pdn_select/pdn_gate（F-B PI/PDN 三工具）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 38. F-B P2 电源完整性（PI/PDN）三工具（pdn_service 薄壳） ────────────────
# 零逻辑转发 service/pdn_service（规则 4）；数值只出确定性内核（规则 7，
# core/pdn 闭式族）；一切失败 ok=False 信封不抛出（不炸会话）。与 CLI
# `rfauto pdn analyze|select|gate` 同源同名 service 函数（JSON 进出）。

@mcp.tool
def pdn_analyze(payload: dict[str, Any]) -> dict[str, Any]:
    """PDN 阻抗谱分析（pdn 域）：decap+VRM → 并联合成谱+反谐振峰+腔模。

    F-B P2。无副作用只读面；不用于选型（走 pdn_select）。数值只在确定性
    内核（规则 7）：全部数字出自 core/pdn 闭式族（RLGC 阶梯口径，并联
    导纳求和）；库缺件 ok=False 列缺件，不静默跳过。

    Args:
        payload: JSON 进出 payload：decaps（条目=库 part_id 字符串 |
            {part_id, mount_l_h?, count?} 库引用 | {part?, c_f, esr_ohm?,
            esl_h?, mount_l_h?, cost?, dc_bias_curve?, count?, provenance?}
            内联规格）、bulk/vrm({r0,l0,r1,l1}) 可选、plane({a_m, b_m, er,
            m_max?, n_max?}) 可选（给出则输出腔模清单）、target({v_ripple_v,
            delta_i_a, profile: flat|smith, fc_hz?}) 可选（给出则输出逐频
            裕量+worst_margin）、f_axis 或 f_start/f_stop/n_points(+scale
            log|lin)、v_bias_v 可选（>0 时带曲线电容按 DC-bias 折减）、
            library_path 可选。

    Returns:
        dict: {ok, f_hz, z_re_ohm/z_im_ohm/z_mag_ohm/z_mag_db_ohm/
        z_phase_deg, z_target_ohm, margin_db, worst_margin, anti_resonances
        (峰频+Q 估计), cavity_modes, branch_details}；库缺件/形状非法
        → ok=False errors
    """
    from rfauto.service.pdn_service import pdn_analyze as _fn
    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def pdn_select(payload: dict[str, Any]) -> dict[str, Any]:
    """贪心 decap 选型（pdn 域）：candidates+budget+target → 选中明细。

    F-B P2。greedy_decap_select 薄封装（同输入同解，不改变语义）；每步
    选"超标频段改善/成本比"最大的电容；全加完仍超标 → infeasible=True
    如实透传（ok 仍为 True，不凑解）；v_bias_v 给出时带曲线候选先按
    DC-bias 折减。形状非法 → ok=False 如实。无副作用只读面，无时序约束。

    Args:
        payload: JSON 进出 payload：candidates（必给非空，条目形态同
            pdn_analyze.decaps；count>1 展开为多颗池槽位）、budget（必给
            ≥0）、target（必给）、频率轴（f_axis 或 f_start/f_stop/
            n_points）、vrm/bulk 基线可选、v_bias_v 可选、library_path 可选。

    Returns:
        dict: {ok, feasible, infeasible, n_selected, total_cost, budget,
        excess, selected[{slot, part_id, part, c_f, ..., derating}],
        margin_db, worst_margin, candidate_details}；形状非法 → ok=False
    """
    from rfauto.service.pdn_service import pdn_select as _fn
    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def pdn_gate(payload: dict[str, Any]) -> dict[str, Any]:
    """KiCad AC-PI 门（F-B P2）：平面腔模筛查+安装避让+可选 Z 谱裕量，三值 verdict。

    判据预声明（service 模块 docstring）：R1 任一腔模频率落入关注带 →
    违项 cavity_mode_in_band（保守筛查口径）；R2 安装位置距带内腔模波腹
    < threshold_frac·λ_eff → 违项 mount_too_close（λ_eff 在关注带上缘
    评估）；R3 payload.impedance 给出时复用 pdn_analyze，worst margin<0 →
    impedance_exceeds_target。plane 或 interest_band 缺失 → UNKNOWN 如实
    （plane 的 a_m/b_m 显式走参数；自动候选可用 pdn_power_pairs 服务从
    .kicad_pcb 电源对提取获得）。UNKNOWN 是如实结论非失败；不用于时域
    SSN 分析。只读无时序约束。

    Args:
        payload: JSON 进出 payload：plane({a_m, b_m, er, m_max?, n_max?})、
            interest_band({f_lo_hz, f_hi_hz})、mount_positions([{x_m, y_m},
            ...])、mount_threshold_frac（缺省 0.5）、impedance（可选，内嵌
            pdn_analyze 同款 schema）、library_path 可选。

    Returns:
        dict: {ok, gate: "pdn_ac_pi", verdict: PASS|FAIL|UNKNOWN,
        unknown_reason, violations, modes_in_band, cavity_modes,
        mount_clearances, impedance_gate}；形状非法 → ok=False
    """
    from rfauto.service.pdn_service import pdn_gate as _fn
    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)}
