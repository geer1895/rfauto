"""AD-N4 数据侦探叙事（round19 P2，ge8c 席C6）——explain_run 结果 → 四段式侦探报告。

定位（round19 口径"四段式：异常检测 detector_vocab 命中→根因假设 playbook
候选族→证据链 forensic_commands+工件引用→结论，数字只出白名单"）：

1. **发现**（findings）：explain_run（DP-17 确定性指纹检测器）输出的
   detector_vocab 指纹命中清单——本模块不发明新检测器，只做叙事编排；
2. **根因假设**（hypotheses）：playbook 候选根因族列表（按命中指纹数降序，
   含坑号链）——多证并击只出候选族（explain_run 语义原样透传）；
3. **证据链**（evidence）：逐命中规则的 forensic_commands + 工件引用
   （et/日志/verdict 工件路径，全程只读 runs/ 证据面）；
4. **结论**（conclusion）：overall=candidates/no_hit 如实口径 + 叙述。

数字纪律：叙述里的一切数字
必须来自 :func:`report_narrative.build_whitelist` 对 explain 确定性数据的
白名单；模板路径逐数字走 canonical 化；注入 ``llm_fn`` 时产出未授权数字按
``on_unauthorized`` reject/fallback 处置（#139：本模块不发起任何网络调用，
LLM 只是可注入接口）。

服务层 JSON 进出（规则 4）；负例（explain 结果不 ok / 输入类型非法）转
ok=False+errors，不抛穿。与 explain_run 零相互 import 依赖其输出形状
（dict 注入，同 warm_start 数据注入先例——测试以构造结果钉契约）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.report_narrative import (
    NumberWhitelist,
    audit_narrative,
    build_whitelist,
    generate_narrative,
)

__all__ = [
    "DATA_DETECTIVE_SCHEMA",
    "data_detective_report",
    "render_detective_markdown",
]

#: 侦探报告 schema 标识（JSON 消费面稳定钉）。
DATA_DETECTIVE_SCHEMA = "rfauto-data-detective-v1"

#: 四段式段名（固定序；消费方按序渲染）。
DETECTIVE_SECTIONS = ("findings", "hypotheses", "evidence", "conclusion")


def _fingerprint_refs(fp_payload: Any) -> list[str]:
    """从指纹证据里抽工件引用（字符串值 best-effort；非 str 跳过）。"""
    refs: list[str] = []
    if isinstance(fp_payload, Mapping):
        for v in fp_payload.values():
            if isinstance(v, str) and v.strip():
                refs.append(v)
            elif isinstance(v, Mapping):
                refs.extend(_fingerprint_refs(v))
    return refs


def data_detective_report(
    explain_result: Mapping[str, Any] | None = None,
    *,
    run_dir: str | None = None,
    playbook_path: str | None = None,
    llm_fn: Any = None,
    on_unauthorized: str = "fallback",
) -> dict[str, Any]:
    """explain 确定性结果 → 四段式侦探报告（JSON 进出）。

    - ``explain_result`` 给定：直接消费（契约见 explain_run 输出形状；
      ``ok`` 非 True → ok=False+errors 如实转负例）；
    - 未给定：按 ``run_dir`` 现调 explain_run（懒 import，防环）；
    - ``llm_fn``：结论段可注入叙述器（缺省确定性模板；#139 通道只经此参数）；
    - ``on_unauthorized``：注入叙述出现未授权数字时 "fallback"（回模板，
      violations 保留）/"reject"（ok=False）。

    返回 {ok, schema, run_dir, overall, sections{findings,hypotheses,
    evidence,conclusion}, narrative, audit, n_candidates, n_findings}。
    """
    if on_unauthorized not in ("fallback", "reject"):
        raise ValueError("on_unauthorized must be 'fallback' or 'reject'")

    if explain_result is None:
        if not run_dir:
            return error_envelope(
                "run_dir required when explain_result is None")
        from rfauto.service.explain_run import explain_run

        explain_result = explain_run(run_dir, playbook_path)
    if not isinstance(explain_result, Mapping):
        return error_envelope("explain_result must be a mapping")
    if not explain_result.get("ok"):
        reason = str(explain_result.get("reason") or "explain_result not ok")
        return error_envelope(f"explain failed: {reason}")

    run = str(explain_result.get("run_dir") or run_dir or "")
    fingerprints: dict[str, Any] = dict(
        explain_result.get("fingerprints") or {})
    matched: list[dict[str, Any]] = [
        dict(r) for r in (explain_result.get("matched_rules") or [])
        if isinstance(r, Mapping)]
    overall = str(explain_result.get("overall") or "no_hit")
    candidates = [str(c) for c in (explain_result.get("candidates") or [])]

    # ── 数字白名单：来自 explain 确定性数据（唯一授权数字来源） ──
    whitelist: NumberWhitelist = build_whitelist(
        explain_result, source=f"runs/{run}:explain")

    # ── 段一：发现（detector_vocab 命中；工件引用就地收集） ──
    finding_items: list[dict[str, Any]] = []
    for fp_id in sorted(fingerprints):
        refs = _fingerprint_refs(fingerprints[fp_id])
        finding_items.append({"fingerprint": fp_id, "artifact_refs": refs})
    # ── 段二：根因假设（候选族降序 + 坑号链，原样透传不下结论） ──
    hypothesis_items = [
        {
            "rule_id": str(r.get("id") or "?"),
            "root_cause_family": str(r.get("root_cause_family") or "?"),
            "matched_fingerprints": [str(f) for f in
                                     (r.get("matched_fingerprints") or [])],
            "pit_refs": [str(p) for p in (r.get("pit_refs") or [])],
            "notes": r.get("notes"),
        }
        for r in matched
    ]
    # ── 段三：证据链（forensic_commands + 工件引用；命令只读证据面） ──
    evidence_items = [
        {
            "rule_id": str(r.get("id") or "?"),
            "forensic_commands": [str(c) for c in
                                  (r.get("forensic_commands") or [])],
            "evidence": r.get("evidence") if isinstance(
                r.get("evidence"), Mapping) else {},
        }
        for r in matched
    ]

    # ── 段四：结论（数字只出白名单；llm_fn 可注入） ──
    deterministic = {
        "overall": overall,
        "run_dir": run,
        "n_findings": len(finding_items),
        "n_candidates": len(candidates),
        "candidates": candidates,
    }
    # 结论段的派生计数（确定性内核产出：len 排序集）同样入白名单
    whitelist = whitelist.merge(build_whitelist(
        deterministic, source=f"runs/{run}:detective-conclusion"))
    conclusion = generate_narrative(
        deterministic,
        llm_fn=llm_fn,
        source=f"runs/{run}:explain",
        whitelist=whitelist,
        on_unauthorized=on_unauthorized,
    )
    if not conclusion.ok and on_unauthorized == "reject":
        # reject 语义：结论被拒 → 报告不完整，如实转负例（不冒充成立）
        return error_envelope(
            [f"unauthorized number: {v.text}@{v.start} ({v.reason})"
             for v in conclusion.violations],
            stage="conclusion_rejected",
        )
    audit = audit_narrative(conclusion.narrative, whitelist)

    sections = {
        "findings": finding_items,
        "hypotheses": hypothesis_items,
        "evidence": evidence_items,
        "conclusion": conclusion.to_dict(),
    }
    return ok_envelope(
        schema=DATA_DETECTIVE_SCHEMA,
        run_dir=run,
        overall=overall,
        sections=sections,
        narrative=conclusion.narrative,
        audit=audit,
        n_findings=len(finding_items),
        n_candidates=len(candidates),
    )


def render_detective_markdown(result: Mapping[str, Any]) -> str:
    """侦探报告 → Markdown（只渲染，不新造数字；非 ok 输入如实记失败）。"""
    if not result.get("ok"):
        return f"# 数据侦探报告\n\n- 报告生成失败：{result.get('errors')}\n"
    run = str(result.get("run_dir") or "")
    lines = [f"# 数据侦探报告（{run}）", ""]

    lines += ["## 一、发现（检测器命中）"]
    findings = result["sections"]["findings"]
    if findings:
        for f in findings:
            refs = "；".join(f["artifact_refs"]) or "（无工件引用）"
            lines.append(f"- 指纹 `{f['fingerprint']}` 命中（工件：{refs}）")
    else:
        lines.append("- 无检测器命中（overall=no_hit 一致口径，不硬凑）。")

    lines += ["", "## 二、根因假设（候选族，按命中指纹数降序）"]
    hyps = result["sections"]["hypotheses"]
    if hyps:
        for h in hyps:
            pits = "、".join(h["pit_refs"]) or "无坑号链"
            lines.append(f"- `{h['root_cause_family']}`（规则 "
                         f"`{h['rule_id']}`；坑号：{pits}）")
    else:
        lines.append("- 无候选根因族。")

    lines += ["", "## 三、证据链（取证命令+工件引用）"]
    evs = result["sections"]["evidence"]
    if evs:
        for e in evs:
            lines.append(f"- 规则 `{e['rule_id']}`：")
            for c in e["forensic_commands"]:
                lines.append(f"  - 取证：{c}")
    else:
        lines.append("- 无取证命令（无命中规则一致口径）。")

    lines += ["", "## 四、结论"]
    lines.append(f"- overall：`{result.get('overall')}`；候选族 "
                 f"`{result.get('n_candidates')}` 项（数字出处：确定性指纹检测）。")
    lines.append("")
    lines.append("### 结论叙述（数字白名单强制）")
    lines.append("")
    lines.append(str(result.get("narrative") or ""))
    return "\n".join(lines) + "\n"
