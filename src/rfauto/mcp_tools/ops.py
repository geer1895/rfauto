"""self_heal_run/log_digest/dispersion_report（F5 自愈/WP3.6 日志/D1 色散）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 33. 接线层装车（审查 D 分片 M1/M5 + C 分片 D1：自愈环/LogDistiller/色散） ──
# 三个"造了零件没装上车"的内核接进只读生产路径；全部零逻辑转发 service
# 信封（规则 4），数值/判定只在确定性内核（铁律 7），不打印 stdout（#242）。

@mcp.tool
def self_heal_run(run_id: str, retries: int = 0) -> dict[str, Any]:
    """run 只读自愈环（ops 域）：日志面蒸馏 → 确定性 critique → 根因+建议。

    F5/WP3.5（11 失败签名根因目录）。无副作用（只读 runs/<run_id>；
    attempt=重读日志面，零真机、零网络）。**只诊断+建议**：不自动修改
    配方——落地动作走既有三层 Gate/沙箱（agent propose/apply）。
    llm_used 恒为 False（铁律 7，LLM 不判定）。run 缺失/无 meta →
    ok=False errors 如实。只读无时序约束。

    Args:
        run_id: 已落盘 run（runs/<run_id>/meta.json 须存在）
        retries: 自愈环重试次数（只读模式下 attempt 确定性重读，默认 0）

    Returns:
        dict: {ok, run_id, verdict: clean|diagnosed|unknown_failure,
               root_cause_id, root_cause, lesson_ref, severity, causes,
               actions, signatures, digest, history, attempts, llm_used,
               advisory_only, note} 或 {ok: False, errors}
    """
    from rfauto.service.self_heal_service import self_heal_run_for_run
    return self_heal_run_for_run(run_id, retries=retries)


@mcp.tool
def log_digest(path: str, source: str = "auto") -> dict[str, Any]:
    """日志文件 / 审计 JSON / run 目录 → 结构化 digest（WP3.6 LogDistiller）。

    无副作用（只读，不落文件；run 收尾自动落的 runs/<id>/log_digest.json
    由 create_run 主路径 best-effort 产出）。纯规则确定性：rc/errors/
    warnings/关键指标/失败签名，数值只取自日志原文不做物理推断。

    Args:
        path: 日志文件（openEMS stdout / PyAEDT 日志 / 审计 JSON）或 run 目录
        source: 数据源标识（auto|openems|hfss|audit_json|generic；auto 按内容判定）

    Returns:
        dict: {ok, path, digest: {ok, source, rc, errors, warnings, metrics,
               signatures, n_lines, truncated, notes}} 或 {ok: False, errors}
    """
    from rfauto.service.self_heal_service import log_digest_for_path
    return log_digest_for_path(path, source=source)


@mcp.tool
def dispersion_report(
    material: str,
    band_ghz: list[float] | None = None,
    max_eps_r_drift: float = 0.02,
) -> dict[str, Any]:
    """材料色散报告（ops 域）：Djordjevic-Sarkar 带内 εr/tanδ 漂移判据。

    D1。判"常数 εr 近似是否成立"（默认 ≤2% 门），不成立给 openEMS/HFSS
    修正参数。无副作用（只读 configs/materials.yaml，零求解器）；**不改
    任何模板/适配器渲染行为**——模板接色散渲染属语义变更需锚重跑
    （followUp）。已配 RO4350B 色散条目 rogers4350b_h0.508_dispersion
    （Dk=3.66/Df=0.0037 @10GHz）。材料无色散条目 → ok=False errors+
    available_dispersion_materials 如实。只读无时序约束。

    Args:
        material: materials.yaml 材料键（须含 dispersion 条目）
        band_ghz: [f_low, f_high]（GHz）；缺省用该材料 D-S 拟合频带端点
        max_eps_r_drift: 常数 εr 近似门（相对漂移，默认 0.02）

    Returns:
        dict: {ok, material, band_ghz, f_meas_ghz, eps_r_at_meas,
               tan_delta_at_meas, samples, eps_r_drift_pct, tan_delta_drift_pct,
               gate: {passed, verdict, ...}, correction?, config_note,
               follow_up_note} 或 {ok: False, errors, available_dispersion_materials}
    """
    from rfauto.service.dispersion_service import dispersion_fitness_report
    return dispersion_fitness_report(
        material, band_ghz, max_eps_r_drift=max_eps_r_drift)
