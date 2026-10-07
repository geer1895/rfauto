"""nominal_regen_service：名义值闭式再生巡检编排（XC-N 的 service 面）。

编排 core/nominal_regen 再生产 + adapters TEMPLATE_NOMINAL 注册名义 +
docs/templates/<t>/meta.yaml 文档卡名义（三方一致性），输出逐模板
巡检行与汇总 verdict。round15 原文口径："审计断言 nominal 可由 core
链 round 再现（先清 patch/coil_nfc）"。

汇总 verdict 语义（#122 判据先行，诚实分区）：
- ``clean``：全部有链模板 MATCH 且无 NOT_RUN/ERROR；
- ``attention``：存在 NOT_COVERED/NOT_RUN（豁免名单如实暴露）但无
  MISMATCH；
- ``issues``：存在 MISMATCH（注册名义与 core 链再生不一致=巡检命中，
  双值随行待人工/锚仲裁，本面不代裁）。

真机首个预声明事实（2026-10-03 实测）：patch 注册名义 34.9/50.0/10.0
vs 当前链再生 32.08/40.92/10.43——XA-1（0.824→0.412×2 单源化）与
XA-2（inset 闭式替换魔数）落地后链已前进、名义未随动，巡检门按设计
命中 MISMATCH。**本面不改名义值**（adapters/docs 名义修复走单独裁决
+同 commit，本席禁改 adapters）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.core.nominal_regen import (
    NOMINAL_REGEN_CHAINS,
    compare_nominal,
    regenerate_nominal,
)
from rfauto.service.envelope import ok_envelope

_SOURCE = "rfauto.service.nominal_regen_service"


def _docs_nominal(template: str, templates_dir: Path) -> dict[str, Any] | None:
    """docs 模板卡 nominal_params（读不到返回 None，不炸——best-effort）。"""
    meta = templates_dir / template / "meta.yaml"
    if not meta.exists():
        return None
    import yaml

    try:
        data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return None
    nominal = data.get("nominal_params")
    return nominal if isinstance(nominal, dict) else None


def _design_inputs(template: str, templates_dir: Path | None,
                   registered: dict[str, Any]) -> dict[str, Any]:
    """链设计输入合成：docs 卡 f0_ghz/substrate + 注册名义表自身键。

    链输入（如 patch 的 f0_ghz/er/h_mm）不在 nominal_params 里而分散在
    docs 卡顶层（f0_ghz、substrate.{er,h_mm}）——单源读 docs 卡；注册
    表同名键已存在时不被 docs 覆盖（调用方显式键最优先）。卡缺失→只剩
    注册表键（缺输入的链如实 NOT_RUN）。
    """
    inputs = {k: v for k, v in registered.items()}
    if templates_dir is not None:
        meta = templates_dir / template / "meta.yaml"
        if meta.exists():
            import yaml

            try:
                data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                data = {}
            if isinstance(data.get("f0_ghz"), (int, float)):
                inputs.setdefault("f0_ghz", data["f0_ghz"])
            sub = data.get("substrate")
            if isinstance(sub, dict):
                if isinstance(sub.get("er"), (int, float)):
                    inputs.setdefault("er", sub["er"])
                if isinstance(sub.get("h_mm"), (int, float)):
                    inputs.setdefault("h_mm", sub["h_mm"])
    return inputs


def nominal_regen_audit(templates: list[str] | None = None, *,
                        chains: dict[str, dict[str, Any]] | None = None,
                        templates_dir: str | Path | None = None,
                        ) -> dict[str, Any]:
    """名义再生巡检：逐模板 {regen, compare, docs_agree} 三方账。

    templates 缺省=注册表有再生链的模板（首件阶段即 ["patch"]）；
    传全量名单时无链模板如实 NOT_COVERED。docs 侧比较只在
    templates_dir 可解析时进行（缺目录/docs 缺卡 → docs_agree=None）。
    """
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    table = chains if chains is not None else NOMINAL_REGEN_CHAINS
    names = list(templates) if templates is not None else sorted(table)
    if templates_dir is None:
        tdir = Path(__file__).resolve().parents[3] / "docs" / "templates"
        if not tdir.exists():
            tdir = None
    else:
        tdir = Path(templates_dir)
    rows: list[dict[str, Any]] = []
    n_mismatch = n_match = n_skip = 0
    for name in names:
        registered = TEMPLATE_NOMINAL.get(str(name))
        if registered is None:
            rows.append({"template": str(name), "verdict": "NOT_IN_REGISTRY",
                         "detail": "模板不在 adapters TEMPLATE_NOMINAL 注册表"})
            n_skip += 1
            continue
        merged = _design_inputs(str(name), tdir, dict(registered))
        regen = regenerate_nominal(str(name), merged, chains=table)
        cmp_row = compare_nominal(str(name), dict(registered),
                                  regen["regenerated"])
        verdict = regen["verdict"] if regen["verdict"] != "OK" \
            else cmp_row["verdict"]
        docs_agree: bool | None = None
        if tdir is not None and cmp_row["verdict"] in ("MATCH", "MISMATCH"):
            docs_nominal = _docs_nominal(str(name), tdir)
            if docs_nominal is not None:
                docs_agree = all(
                    docs_nominal.get(k) is not None
                    and float(docs_nominal[k]) == float(registered[k])
                    for k in cmp_row["keys"])
        if verdict == "MISMATCH":
            n_mismatch += 1
        elif verdict == "MATCH":
            n_match += 1
        else:
            n_skip += 1
        rows.append({
            "template": str(name), "verdict": verdict,
            "registered": {k: registered.get(k) for k in cmp_row["keys"]},
            "regenerated": regen["regenerated"],
            "mismatches": cmp_row["mismatches"],
            "missing_inputs": regen["missing_inputs"],
            "error": regen["error"],
            "docs_agree": docs_agree,
        })
    if n_mismatch:
        summary = "issues"
    elif n_match:
        summary = "clean" if n_skip == 0 else "attention"
    else:
        summary = "attention"
    return ok_envelope(
        rows=rows,
        summary={"match": n_match, "mismatch": n_mismatch,
                    "skipped_or_uncovered": n_skip},
        verdict=summary,
        chain_registry=sorted(table),
        source=_SOURCE,
    )


def render_nominal_regen_report(audit: dict[str, Any]) -> str:
    """巡检账 → 人读 markdown 报告（逐模板双值对照行）。"""
    lines = ["# XC-N 名义值闭式再生巡检报告", ""]
    s = audit["summary"]
    lines.append(f"- verdict: **{audit['verdict']}**（match={s['match']}, "
                 f"mismatch={s['mismatch']}, "
                 f"skipped/uncovered={s['skipped_or_uncovered']}）")
    lines.append(f"- 再生链注册表: {', '.join(audit['chain_registry'])}")
    lines.append("")
    for row in audit["rows"]:
        lines.append(f"## {row['template']} — {row['verdict']}")
        for mis in row.get("mismatches") or []:
            lines.append(f"- {mis['key']}: registered={mis.get('registered')!r} "
                         f"vs regenerated={mis.get('regenerated')!r}")
        if row.get("missing_inputs"):
            lines.append(f"- 缺链输入: {row['missing_inputs']}")
        if row.get("error"):
            lines.append(f"- 链错误: {row['error']}")
        if row.get("docs_agree") is False:
            lines.append("- docs meta.yaml nominal 与注册名义不一致")
        lines.append("")
    return "\n".join(lines)


def audit_to_json(audit: dict[str, Any]) -> str:
    """巡检账 → JSON 文本（确定性键序）。"""
    return json.dumps(audit, ensure_ascii=False, indent=1, sort_keys=True,
                      default=str)
