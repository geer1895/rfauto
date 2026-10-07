"""实测↔仿真偏差闭环桥（SO-审查 §7 P4 / B4 归因器 mini，2026-10-05）。

把测量残差接进既有诊断-提案环，补齐 SO 走查 B5 断的桥
（"实测数据进不了这个环"）：FSV/相关性（measurement.correlate）与
可选 En 不确定度（vna_service.vna_en_report）的确定性输出 → explain
形载荷 → data_detective 四段式叙事（发现/根因假设/证据链/结论）→
可选 agent_propose 三层 Gate 参数提案——"实测偏差→根因假设→参数提案"
一条命令链。

铁律 7：本模块零新数值面——全部数字来自确定性内核（correlate/FSV/En/
agent Gate），本层只做载荷编排与转发；matched_rules 如实为空（实测链
暂无 playbook 指纹规则，不冒充仿真 run 指纹命中）。#139：本模块零网络、
零 LLM 通道（llm_fn 恒 None，走确定性模板叙述）。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

#: 桥报告 schema 标识（JSON 消费面稳定钉）。
MEASUREMENT_LOOP_SCHEMA = "rfauto-measurement-loop-v1"

#: 缺省 FSV 评估迹线（与 correlate.compute_fsv_assessment 缺省一致）。
_FSV_TRACES: tuple[str, ...] = ("s11", "s21")

#: 结论段 typed 下一步建议（确定性字符串，只含既有入口指针，零新数值）。
_NEXT_STEP_CANDIDATES: tuple[str, ...] = (
    "rfauto diagnose cm <实测.s2p> --f0 <f0_ghz> --fbw <fbw>"
    "（耦合矩阵反提，对照设计目标）",
    "rfauto diagnose q <单腔实测.s1p> --f0 <f0_ghz> --qe <q_e>"
    "（Q 双通道互证）",
    "rfauto vna en-report <实测.s2p> <仿真.s2p>（GUM 不确定度预算）",
    "rfauto agent propose <配方.yaml> --params <JSON>"
    "（偏差定向参数提案，L1/L2 Gate + L3 token）",
)


def _fsv_worst_grade(fsv_rows: Mapping[str, Mapping[str, Any]]) -> str:
    """FSV 各迹线最差 GDM 评级（短码比较走 core/fsv 单源词表，零重复）。"""
    from rfauto.core.fsv import GRADE_CODES

    worst_idx = -1
    for row in fsv_rows.values():
        if not isinstance(row, Mapping) or not row.get("ok"):
            continue
        try:
            idx = GRADE_CODES.index(str(row.get("gdm_grade") or ""))
        except ValueError:
            continue  # 词表外语级如实跳过（不硬塞进六级序）
        if idx > worst_idx:
            worst_idx = idx
    return GRADE_CODES[worst_idx] if worst_idx >= 0 else "no_data"


def measurement_deviation_report(
    sim_file: str | Path,
    measured_file: str | Path,
    *,
    run_dir: str | Path | None = None,
    threshold_db: float = 3.0,
    fsv_traces: tuple[str, ...] = _FSV_TRACES,
    en_report: bool = False,
    markdown_path: str | Path | None = None,
) -> dict[str, Any]:
    """实测↔仿真偏差报告（JSON 进出；信封契约）。

    Args:
        sim_file: 仿真 Touchstone（.s2p）。
        measured_file: 实测 Touchstone（.s2p）。
        run_dir: 关联仿真 run 目录（可选，只作 provenance 指针透传）。
        threshold_db: 相关性偏差门（dB，透传 compute_correlation）。
        fsv_traces: FSV 评估迹线名（白名单 s11/s21，见 correlate S-1 C-06①）。
        en_report: 是否附 En 不确定度报告（GUM 预算缺省模板）。
        markdown_path: 侦探叙事 Markdown 落盘路径（可选）。

    Returns:
        ok 信封：{schema, sim_file, measured_file, run_dir, correlation,
        fsv, en_report?, detective, markdown_path?}；输入缺失/解析失败走
        error_envelope。
    """
    sim_p, meas_p = Path(sim_file), Path(measured_file)
    for label, path in (("仿真", sim_p), ("实测", meas_p)):
        if not path.exists():
            return error_envelope([f"{label}文件不存在: {path}"])

    from rfauto.measurement.correlate import (
        compute_correlation,
        compute_fsv_assessment,
    )
    from rfauto.measurement.import_data import import_touchstone

    try:
        sim = import_touchstone(str(sim_p))
        measured = import_touchstone(str(meas_p))
    except Exception as exc:
        return error_envelope([f"Touchstone 导入失败: {exc}"])

    try:
        corr = compute_correlation(sim, measured, threshold_db).to_dict()
    except Exception as exc:
        return error_envelope([f"相关性计算失败: {exc}"])
    fsv_rows = compute_fsv_assessment(
        sim, measured, traces=tuple(fsv_traces))

    # ── explain 形载荷（实测偏差口径；matched_rules 如实空） ──
    fingerprints: dict[str, Any] = {}
    for trace, row in fsv_rows.items():
        if isinstance(row, Mapping) and row.get("ok"):
            fingerprints[f"fsv:{trace}:gdm_{row.get('gdm_grade')}"] = {
                "trace": trace,
                "adm_grade": row.get("adm_grade"),
                "gdm_grade": row.get("gdm_grade"),
                "gdm_mean": row.get("gdm_mean"),
                "n_points": row.get("n_points"),
            }
        else:
            fingerprints[f"fsv:{trace}:unavailable"] = {
                "trace": trace,
                "error": (row.get("error") if isinstance(row, Mapping)
                          else str(row)),
            }
    fingerprints["correlation:verdict"] = {
        "is_correlated": bool(corr.get("is_correlated")),
        "threshold_db": threshold_db,
    }
    explain_payload: dict[str, Any] = {
        "ok": True,
        "run_dir": str(run_dir) if run_dir else str(sim_p),
        "overall": f"measured_deviation:gdm_{_fsv_worst_grade(fsv_rows)}",
        "fingerprints": fingerprints,
        "matched_rules": [],  # 实测链暂无 playbook 规则——如实空，不冒充
        "candidates": list(_NEXT_STEP_CANDIDATES),
    }

    from rfauto.service.data_detective import (
        data_detective_report,
        render_detective_markdown,
    )

    detective = data_detective_report(explain_payload)
    if not detective.get("ok"):
        return error_envelope(
            [f"侦探叙事失败: {detective.get('errors')}"], stage="detective")

    sections: dict[str, Any] = {
        "schema": MEASUREMENT_LOOP_SCHEMA,
        "sim_file": str(sim_p),
        "measured_file": str(meas_p),
        "run_dir": str(run_dir) if run_dir else None,
        "correlation": corr,
        "fsv": {k: v for k, v in fsv_rows.items()},
        "detective": detective,
    }
    if en_report:
        from rfauto.service.vna_service import vna_en_report

        en = vna_en_report(meas_p, sim_p)
        sections["en_report"] = en
    if markdown_path:
        Path(markdown_path).write_text(
            render_detective_markdown(detective), encoding="utf-8")
        sections["markdown_path"] = str(markdown_path)
    return ok_envelope(**sections)


def measurement_loop_propose(
    report: Mapping[str, Any],
    recipe_path: str | Path,
    params_override: Mapping[str, Any] | None = None,
    *,
    adapter_name: str = "fake",
) -> dict[str, Any]:
    """偏差报告 → 参数提案（agent_propose 三层 Gate；只 propose 不 apply）。

    report 须为 measurement_deviation_report 的 ok 信封（实测偏差→提案
    链的第二段）。params_override 必须由调用方/确定性内核给出——本函数
    不从偏差数字臆造参数值（铁律 7）。
    """
    if not isinstance(report, Mapping) or not report.get("ok"):
        return error_envelope(["report 须为 measurement_deviation_report 的 ok 信封"])
    from rfauto.service.api import agent_propose

    proposal = agent_propose(
        recipe_path, dict(params_override or {}), adapter_name=adapter_name)
    return ok_envelope(
        schema=MEASUREMENT_LOOP_SCHEMA,
        run_dir=report.get("run_dir"),
        proposal=proposal,
    )
