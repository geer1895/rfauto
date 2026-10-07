"""aging_simulate/aging_verdict/aging_report（F-C 器件老化漂移）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 39. F-C P2 器件老化漂移三工具（aging_service 薄壳） ──────────────────────
# 零逻辑转发 service/aging_service（规则 4）；数值只出确定性内核（规则 7，
# core/aging 三律+profile_integrate）；一切失败 ok=False 信封不抛出（不炸
# 会话）。与 CLI `rfauto aging simulate|verdict|report` 同源同名 service
# 函数（JSON 进出）。

@mcp.tool
def aging_simulate(payload: dict[str, Any]) -> dict[str, Any]:
    """老化漂移仿真（aging 域）：任务剖面→εr 漂移轨迹→名义/EOL 两点 S 参数+失谐量。

    F-C P2。数值只在确定性内核（规则 7）：漂移轨迹出自
    core.aging.profile_integrate（三律+Miner+Arrhenius 折算）；老化律参数
    出自 knowledge/aging_laws.yaml（awaiting_data 材料不产数字，诚实边界）；
    fake 通道为等效长度伸缩一阶重算（EOL 漂移上界估计），不用于寿命认证
    结论。材料 awaiting/引擎不支持/参数缺失 → ok=False 如实不产数字。
    只读无时序约束。

    Args:
        payload: JSON 进出 payload：template（模型注册名，v1 仅谐振族：
            wilkinson_power_divider/branchline_coupler/patch_antenna 等）、
            params（名义几何 dict，必含谐振长度变量）、mission_profile
            ([{t_s, t_c, delta_t_c?, j_density?}, ...])、lifetime_years 或
            t_total_s（二选一）、laws_material（aging_laws.yaml material_id）、
            er0（名义 εr）、t_use_c（使用温度 °C）、engine（缺省 "fake"，v1
            唯一合法值）、fill_fraction?（(0,1] 缺省 1.0 全填充上界）、
            freq_ghz?、n_ports?、f0_ghz?。

    Returns:
        dict: {ok, er_drift_curve, drift(er0/er_eol/drift_frac), eps_eff,
        s_params_nominal, s_params_eol, f_dip_ghz, detune_pct（实测）,
        detune_pct_predicted, damage, failed, mission_profile,
        laws_provenance}；材料 awaiting/引擎不支持/参数缺失 → ok=False
        errors（不产数字）
    """
    from rfauto.service.aging_service import aging_simulate as _fn
    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def aging_verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """EOL 失谐判据（aging 域）：|detune_pct| ≤ spec → PASS/FAIL（确定性）。

    F-C P2。恰等 spec 判 PASS（ge1③ 恰等容差口径）；spec 支持百分比
    （spec_pct）与 ppm（spec_ppm）两种频率容差口径（二选一）；纯判据面
    不用于漂移仿真（走 aging_simulate）。payload 缺键/非法 → ok=False
    如实。只读无时序约束。

    Args:
        payload: JSON 进出 payload：detune_pct（直接给失谐 %）或
            simulate/simulate_result（aging_simulate 结果 dict，取其
            detune_pct）、spec_pct 或 spec_ppm（二选一，>=0）。

    Returns:
        dict: {ok, verdict: PASS|FAIL, criterion, detune_pct, detune_ppm,
        spec_pct, spec_ppm, margin_pct}；payload 缺键/非法 → ok=False
    """
    from rfauto.service.aging_service import aging_eol_verdict as _fn
    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def aging_report(payload: dict[str, Any]) -> dict[str, Any]:
    """老化报告（F-C P2）：mission_profile 表/漂移轨迹/EOL 判据/法源 provenance 四节。

    附 disclaimer 措辞钉（EOL 漂移上界估计，非认证寿命结论；多机理耦合
    UNKNOWN）；provenance 含 aging_laws.yaml 出处与 awaiting 状态；未给
    spec 则判据节 verdict=UNKNOWN 如实不冒充。

    Args:
        payload: JSON 进出 payload：simulate_result（aging_simulate 结果
            dict 内嵌）或 simulate_payload（现场先跑 simulate）、spec_pct 或
            spec_ppm（可选，给出则产出 EOL 判据节）。

    Returns:
        dict: {ok, template, engine, disclaimer, sections: {mission_profile,
        drift_trajectory, eol_verdict, provenance}}；simulate 失败 → ok=False
    """
    from rfauto.service.aging_service import aging_report as _fn
    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)}
