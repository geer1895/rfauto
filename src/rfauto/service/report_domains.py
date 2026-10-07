"""报告四新节（aging/PI/OTA/EMC）——垂直域摘要渲染进 U1 报告链。

月计划 G 流"报告增强：aging/PI/OTA/EMC 四新节进 U1 报告链"（B3 批，
docs/audit/plan_gap_inventory_20260928.md §二 B3）。U1 链现状=
service/report_render.py 四段式（identification/method/criteria/conclusion），
垂直域报告此前只有 CLI 薄壳（aging report 等）各自为政——本模块补"节"层：

- 每节=既有确定性内核输出的**摘要渲染**（铁律 7：数字全部来自内核输出，
  本模块零计算零换算，只挑键+带单位标注+如实 None；来源键逐条标注）；
- 形态=JSON 友好 dict（``build_report_model(domain_results=...)`` 挂进
  报告模型 ``model["domains"]``，typ/HTML 渲染器按在场与否增量渲染——
  缺省不传时报告输出与既有逐字节一致，零行为变化）；
- ``status="empty"``：输入缺关键节/非 ok 时如实留空（UNKNOWN 不冒充，
  #122/#314 判读纪律同源）。

四种节（内核一一对应）：
- ``aging``：service/aging_service.aging_report 输出（mission_profile/
  drift_trajectory/eol_verdict）；
- ``pi``：service/pdn_service.pdn_gate 输出（R1 腔模带内/R2 安装避让/
  R3 阻抗裕量三判据；pdn_analyze 输出亦可消费，verdict 如实 UNKNOWN）；
- ``ota``：core/ota_metrics.ota_report_card 输出（TRP/EIRP/方向性/波束
  效率四卡+网格质量）；
- ``emc``：core/emc_radiated.radiated_margin 输出（ME-1 margin_report
  同构：限值裕量+首违频点+verdict）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: 域名 → 节构建器（assemble_domain_sections 消费；新域在此注册）
DOMAIN_ORDER: tuple[str, ...] = ("aging", "pi", "ota", "emc")


def _metric(name: str, value: Any, unit: str, source: str) -> dict[str, Any]:
    """一行指标（value 原样透传内核值；None=内核未产出，渲染层如实 '-'）。"""
    return {"metric": name, "value": value, "unit": unit, "source": source}


def _ok(result: Mapping[str, Any]) -> bool:
    return bool(result.get("ok"))


def _first(result: Mapping[str, Any], *keys: str) -> Any:
    """按序取第一个非 None 键值（全缺 → None 如实）。"""
    for k in keys:
        v = result.get(k)
        if v is not None:
            return v
    return None


def aging_section(result: Mapping[str, Any]) -> dict[str, Any]:
    """老化节：aging_report 输出 → {mission_profile/drift/EOL 判据摘要}。"""
    base: dict[str, Any] = {
        "domain": "aging",
        "title": "老化漂移（F-C：PoF 时间轴→εr 漂移→EOL 失谐）",
        "kernel": "service/aging_service.aging_report",
        "status": "empty",
        "verdict": None,
        "metrics": [],
        "notes": [],
    }
    if not isinstance(result, Mapping) or not _ok(result):
        base["notes"].append(
            "aging 输入非 ok/缺失——本节如实留空（不冒充判读）")
        if isinstance(result, Mapping):
            base["notes"].extend(str(e) for e in result.get("errors") or [])
        return base
    sections = result.get("sections")
    if not isinstance(sections, Mapping):
        base["notes"].append("aging 输出缺 sections——如实留空")
        return base
    drift = sections.get("drift_trajectory")
    profile = sections.get("mission_profile")
    eol = sections.get("eol_verdict")
    metrics: list[dict[str, Any]] = []
    if isinstance(profile, Mapping):
        metrics.append(_metric("t_total_s", profile.get("t_total_s"),
                               "s", "sections.mission_profile.t_total_s"))
        metrics.append(_metric("t_equivalent_s", profile.get("t_equivalent_s"),
                               "s", "sections.mission_profile.t_equivalent_s"))
    if isinstance(drift, Mapping):
        metrics.append(_metric("er0", drift.get("er0"), "-",
                               "sections.drift_trajectory.er0"))
        metrics.append(_metric("er_eol", drift.get("er_eol"), "-",
                               "sections.drift_trajectory.er_eol"))
        metrics.append(_metric("detune_pct", drift.get("detune_pct"),
                               "%", "sections.drift_trajectory.detune_pct"))
        metrics.append(_metric(
            "detune_pct_predicted", drift.get("detune_pct_predicted"),
            "%", "sections.drift_trajectory.detune_pct_predicted"))
    base["status"] = "ok"
    base["metrics"] = metrics
    if isinstance(eol, Mapping):
        base["verdict"] = eol.get("verdict")
        reason = eol.get("reason")
        if reason:
            base["notes"].append(f"EOL 判据：{reason}")
    disclaimer = result.get("disclaimer")
    if disclaimer:
        base["notes"].append(str(disclaimer))
    return base


def pi_section(result: Mapping[str, Any]) -> dict[str, Any]:
    """PI/PDN 节：pdn_gate（优先）或 pdn_analyze 输出摘要。"""
    base: dict[str, Any] = {
        "domain": "pi",
        "title": "PI/PDN（F-B：目标阻抗/去耦/平面腔模 AC-PI 门）",
        "kernel": "service/pdn_service.pdn_gate|pdn_analyze",
        "status": "empty",
        "verdict": None,
        "metrics": [],
        "notes": [],
    }
    if not isinstance(result, Mapping) or not _ok(result):
        base["notes"].append("pdn 输入非 ok/缺失——本节如实留空")
        if isinstance(result, Mapping):
            base["notes"].extend(str(e) for e in result.get("errors") or [])
        return base
    metrics: list[dict[str, Any]] = []
    is_gate = "gate" in result
    if is_gate:
        base["kernel"] = "service/pdn_service.pdn_gate"
        base["verdict"] = result.get("verdict")
        modes_in_band = result.get("modes_in_band")
        n_modes = len(modes_in_band) if isinstance(modes_in_band,
                                                   (list, tuple)) else None
        metrics.append(_metric("n_modes_in_band", n_modes, "个",
                               "pdn_gate.modes_in_band"))
        violations = result.get("violations")
        n_viol = len(violations) if isinstance(violations,
                                               (list, tuple)) else None
        metrics.append(_metric("n_violations", n_viol, "条",
                               "pdn_gate.violations"))
        unknown_reason = result.get("unknown_reason")
        if unknown_reason:
            base["notes"].append(f"UNKNOWN 依据：{unknown_reason}")
    else:
        base["kernel"] = "service/pdn_service.pdn_analyze"
        base["notes"].append(
            "输入为 analyze 面（无门 verdict）——verdict 如实 UNKNOWN")
    # 两面共有的阻抗裕量键（有才渲染，None 如实）
    metrics.append(_metric("margin_db", _first(result, "margin_db"),
                           "dB", "margin_db"))
    metrics.append(_metric("worst_margin", _first(result, "worst_margin"),
                           "dB", "worst_margin"))
    base["status"] = "ok"
    base["metrics"] = metrics
    return base


def ota_section(result: Mapping[str, Any]) -> dict[str, Any]:
    """OTA 节：ota_report_card 输出 → TRP/EIRP/方向性/波束效率四卡摘要。"""
    base: dict[str, Any] = {
        "domain": "ota",
        "title": "OTA（TRP/EIRP/方向性/波束效率四卡）",
        "kernel": "core/ota_metrics.ota_report_card",
        "status": "empty",
        "verdict": None,
        "metrics": [],
        "notes": [],
    }
    if not isinstance(result, Mapping) or not result:
        base["notes"].append("OTA 输入缺失——本节如实留空")
        return base
    trp = result.get("trp")
    eirp = result.get("eirp")
    directivity = result.get("directivity")
    beam = result.get("beam_efficiency")
    metrics: list[dict[str, Any]] = []
    if isinstance(trp, Mapping):
        metrics.append(_metric("trp_dbm", trp.get("trp_dbm"), "dBm",
                               "ota_report_card.trp.trp_dbm"))
    if isinstance(eirp, Mapping):
        metrics.append(_metric("eirp_peak_dbm", eirp.get("eirp_peak_dbm"),
                               "dBm", "ota_report_card.eirp.eirp_peak_dbm"))
    if isinstance(directivity, Mapping):
        metrics.append(_metric("directivity_dbi", directivity.get("d_db"),
                               "dB", "ota_report_card.directivity.d_db"))
    if isinstance(beam, Mapping):
        metrics.append(_metric("beam_efficiency",
                               _first(beam, "efficiency", "eta", "value"),
                               "-", "ota_report_card.beam_efficiency"))
    quality = result.get("grid_quality")
    if isinstance(quality, Mapping):
        cov = quality.get("coverage_fraction")
        metrics.append(_metric("grid_coverage_fraction", cov, "-",
                               "ota_report_card.grid_quality"))
        for w in quality.get("warnings") or []:
            base["notes"].append(f"网格质量警告：{w}")
    statuses = [c.get("status") for c in (trp, eirp, directivity, beam)
                if isinstance(c, Mapping) and c.get("status") is not None]
    base["verdict"] = ("ok" if statuses and all(s == "ok" for s in statuses)
                       else None)
    if not metrics:
        base["notes"].append("OTA 输出无可摘要卡（键缺失）——如实留空")
        return base
    base["status"] = "ok"
    base["metrics"] = metrics
    return base


def emc_section(result: Mapping[str, Any]) -> dict[str, Any]:
    """EMC 节：radiated_margin 输出（限值裕量+首违频点+verdict）。"""
    base: dict[str, Any] = {
        "domain": "emc",
        "title": "EMC 辐射发射（ME-2：限值裕量报告）",
        "kernel": "core/emc_radiated.radiated_margin",
        "status": "empty",
        "verdict": None,
        "metrics": [],
        "notes": [],
    }
    if not isinstance(result, Mapping) or not result:
        base["notes"].append("EMC 输入缺失——本节如实留空")
        return base
    base["status"] = "ok"
    base["verdict"] = result.get("verdict")
    base["metrics"] = [
        _metric("min_margin_db", result.get("min_margin_db"), "dB",
                "margin_report.min_margin_db"),
        _metric("min_margin_f_hz", result.get("min_margin_f_hz"), "Hz",
                "margin_report.min_margin_f_hz"),
        _metric("first_violation_f_hz", result.get("first_violation_f_hz"),
                "Hz", "margin_report.first_violation_f_hz"),
        _metric("n_violations", result.get("n_violations"), "个",
                "margin_report.n_violations"),
        _metric("n_out_of_band", result.get("n_out_of_band"), "点",
                "margin_report.n_out_of_band（带外 NaN 不判读语义）"),
    ]
    return base


#: 域名 → 构建器（公开映射；assemble 消费）
DOMAIN_BUILDERS: Mapping[str, Any] = {
    "aging": aging_section,
    "pi": pi_section,
    "ota": ota_section,
    "emc": emc_section,
}


def assemble_domain_sections(
    results: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """{域名: 内核输出} → {ok, sections, n_domains, unknown_keys}。

    - 四域全集齐且全部 status=ok 才 ok=True；缺域如实缺（sections 里不
      伪造空卡，只记 n_missing）；未知域名进 unknown_keys 如实回显
      （不静默丢弃，消费方可核对拼写）。
    - results=None/空 → {ok: False, sections: [], ...}（调用方据此不挂
      domains 节，报告输出与既有逐字节一致）。
    """
    if not results:
        return {"ok": False, "sections": [], "n_domains": 0,
                "n_missing": len(DOMAIN_ORDER), "unknown_keys": [],
                "note": "无垂直域输入——报告不含 domains 节"}
    sections: list[dict[str, Any]] = []
    unknown = [str(k) for k in results if k not in DOMAIN_BUILDERS]
    for domain in DOMAIN_ORDER:
        if domain in results:
            sections.append(DOMAIN_BUILDERS[domain](results[domain] or {}))
    n_ok = sum(1 for s in sections if s["status"] == "ok")
    return {
        "ok": bool(sections) and n_ok == len(sections)
        and len(sections) == len(DOMAIN_ORDER),
        "sections": sections,
        "n_domains": len(sections),
        "n_missing": len(DOMAIN_ORDER) - len(sections),
        "unknown_keys": sorted(unknown),
        "note": "每节数字全部来自对应内核输出（铁律 7）；缺节如实留空",
        # U1 链规则 2：节点持数值叶（n_domains/n_missing）必须带 source 键
        "source": "service/report_domains.assemble_domain_sections（域计数）",
    }


def render_domains_html(domains: Mapping[str, Any]) -> str:
    """domains 节 → HTML 片段（消费 assemble_domain_sections 输出）。

    全插值经 html.escape；verdict 复用报告链 judge-* 配色；无节时返回
    空串（渲染器零增量）。
    """
    from html import escape as esc

    sections = domains.get("sections")
    if not isinstance(sections, (list, tuple)):
        sections = []
    if not sections:
        return ""
    parts: list[str] = ["<h2 id=\"sec-domains\">垂直域摘要（aging/PI/OTA/EMC）</h2>"]
    parts.append(f"<p class=\"meta\">{esc(str(domains.get('note') or ''))}</p>")
    for s in sections:
        if not isinstance(s, Mapping):
            continue
        verdict = s.get("verdict")
        v_html = ""
        if verdict is not None:
            cls = (f" class=\"judge-{esc(str(verdict))}\""
                   if str(verdict) in ("PASS", "FAIL", "UNKNOWN", "ok")
                   else "")
            v_html = f" ｜ verdict：<b{cls}>{esc(str(verdict))}</b>"
        parts.append(f"<h3>{esc(str(s.get('title') or s.get('domain')))}"
                     f"{v_html}</h3>")
        rows = [
            [esc(str(m.get("metric"))),
             "-" if m.get("value") is None else esc(str(m.get("value"))),
             esc(str(m.get("unit") or "")),
             esc(str(m.get("source") or ""))]
            for m in (s.get("metrics") or []) if isinstance(m, Mapping)
        ]
        if rows:
            parts.append("<table><tr><th>指标</th><th>值</th>"
                         "<th>单位</th><th>来源键</th></tr>")
            for r in rows:
                parts.append("<tr>" + "".join(
                    f"<td>{c}</td>" for c in r) + "</tr>")
            parts.append("</table>")
        else:
            parts.append("<p>无指标（status："
                         f"{esc(str(s.get('status') or '-'))}）</p>")
        notes = s.get("notes") or []
        if notes:
            parts.append("<ul>")
            for note in notes:
                parts.append(f"<li>{esc(str(note))}</li>")
            parts.append("</ul>")
    return "".join(parts)


#: typst 模板的 domains 条件块（_TYP_TEMPLATE 拼接用；jinja+tc/fv 过滤器
#: 约定与 report_render._TYP_TEMPLATE 同源）
DOMAINS_TYP_BLOCK = """{% if model.domains and model.domains.sections %}
== 垂直域摘要（aging／PI／OTA／EMC）

{{ model.domains.note | tc }}

{% for s in model.domains.sections %}=== {{ s.title | tc }}{% if s.verdict is not none %}（verdict：{{ s.verdict | tc }}）{% endif %}

#table(
  columns: (auto, auto, auto, auto),
  table.header([ 指标 ], [ 值 ], [ 单位 ], [ 来源键 ]),
{% for m in s.metrics %}  {{ m.metric | tc }}, {{ (m.value | fv) | tc }}, {{ (m.unit or "") | tc }}, {{ (m.source or "") | tc }},
{% endfor %})
{% for note in s.notes %}注记：{{ note | tc }}
{% else %}（无注记）
{% endfor %}
{% endfor %}
{% endif %}
"""
