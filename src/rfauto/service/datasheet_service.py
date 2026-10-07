"""EP-4 Datasheet/应用笔记生成器（模板卡/run 报告 → 器件 datasheet 渲染面）。

规格 研究扩充 round18 §二 EP-4：datasheet 节型
（电气表/S 参图/典型应用/机械尺寸）+ 强制标注"工程规格书非厂商 datasheet"。

**复用而非重写（任务书纪律 3）**：

- 数据源=PR-4 报告器全链：run 目录在场时 ``build_report_model``（PR-4
  报告模型 rfauto-report/v1）是唯一实测数据入口——电气表实测行、判据行、
  S 参曲线节点（curves）与 verdict 全部**原节点透传**（零二次采数，同
  PR-4"渲染器零二次采数"纪律）；
- provenance 判定复用：模型自检 ``bare_number_fields``（PR-4 的数字
  100% provenance 判定式）=0 才算构建成功；
- 数值格式化复用 ``fmt_value``；
- **PDF 出口不重写**：PDF 走 PR-4 链（同一 run 的 render_pdf），本模块
  出 markdown/HTML 双渲染；datasheet 独立 typ 模板挂 report_domains 域
  注册表属归属面批次（该文件本席禁改）——如实登记，不假造第二 PDF 管线。

**强制免责声明**（规格原文）：模型 ``disclaimer`` 节恒在——"工程规格书
（engineering specification），非厂商 datasheet；全部数值来源见逐条
source 标注"。缺 source 的数值行构建即 ValueError（不静默，#316 方向）。

接口纪律：dict/JSON 进出；零网络零真机；数值只在输入透传（铁律 7）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.service.report_render import bare_number_fields, fmt_value

__all__ = [
    "DATASHEET_DISCLAIMER",
    "build_datasheet",
    "load_template_meta",
    "render_html",
    "render_markdown",
]

DATASHEET_SCHEMA = "rfauto-datasheet/v1"
DATASHEET_DISCLAIMER = (
    "工程规格书（engineering specification）——非厂商 datasheet；"
    "全部数值来源见逐条 source 标注，未经批量生产验证。"
)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须为非空字符串")
    return value


def _row(param: str, value: Any, unit: str, source: str) -> dict[str, Any]:
    """规格表一行（数值行必须带 source——构建期强制，不靠渲染期补救）。

    unit 允许空串（无量纲量如 er）。
    """
    return {
        "param": _text(param, "param"),
        "value": value,
        "unit": unit if isinstance(unit, str) else str(unit),
        "source": _text(source, "source"),
    }


def _unit_of_key(key: str) -> str:
    """meta.yaml 键名 → 单位（键尾语义：_mm→mm、_ghz→GHz、er 无量纲）。"""
    if key.endswith("_mm"):
        return "mm"
    if key.endswith("_ghz"):
        return "GHz"
    return ""


def _meta_rows(template: str, meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """docs meta.yaml 形态（nominal_params/substrate）→ 名义规格行。"""
    rows: list[dict[str, Any]] = []
    if not meta:
        return rows
    src = f"docs/templates/{template}/meta.yaml"
    # 顶层电气标量（f0_ghz/n_ports 是 datasheet 电气表标准行）
    for key in ("f0_ghz", "n_ports"):
        if meta.get(key) is not None:
            rows.append(_row(key, meta[key], _unit_of_key(key), src))
    nominal = meta.get("nominal_params")
    if isinstance(nominal, dict):
        for key in sorted(nominal):
            val = nominal[key]
            if val is None:
                continue
            rows.append(_row(key, val, _unit_of_key(key), src))
    substrate = meta.get("substrate")
    if isinstance(substrate, dict):
        for key in ("er", "h_mm", "tan_d"):
            if substrate.get(key) is not None:
                rows.append(
                    _row(f"substrate.{key}", substrate[key], _unit_of_key(key), src)
                )
    return rows


def _report_rows(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    """PR-4 报告模型 method.fields（每行自带 source）→ 实测/方法规格行。"""
    rows: list[dict[str, Any]] = []
    if not isinstance(report, dict):
        return rows
    fields = report.get("method", {}).get("fields")
    if isinstance(fields, list):
        for f in fields:
            if not isinstance(f, dict) or f.get("value") is None:
                continue  # 缺值行如实跳过（缺数据=缺行，不放 None 凑表）
            rows.append(_row(str(f.get("name")), f.get("value"),
                             str(f.get("unit") or ""), str(f.get("source"))))
    verdict = report.get("conclusion", {}).get("verdict")
    if isinstance(verdict, str) and verdict:
        rows.append(_row("run_verdict", verdict, "", "rfauto-report/v1:conclusion.verdict"))
    return rows


def load_template_meta(template: str, *,
                       templates_dir: str | Path | None = None) -> dict[str, Any] | None:
    """docs/templates/<t>/meta.yaml → 名义 dict（F-10 W3-D 接线壳共用数据源）。

    CLI/MCP 薄壳按 ``--template T`` 取名义节喂 :func:`build_datasheet` 的
    ``meta``；缺文件/非映射/空 template 一律 None（调用方按"无名义节"如实
    构建，不伪造不报错）。``templates_dir`` 显式给定时优先（测试注入用）；
    缺省锚仓根 docs/templates（service 目录向上三级，explain_run 同款走法）。
    """
    if not isinstance(template, str) or not template.strip():
        return None
    if templates_dir is not None:
        base = Path(templates_dir)
    else:
        base = Path(__file__).resolve().parents[3] / "docs" / "templates"
    p = base / template / "meta.yaml"
    if not p.is_file():
        return None
    import yaml

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def build_datasheet(
    *,
    part_number: str,
    template: str,
    meta: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
    typical_application: dict[str, Any] | None = None,
    field_plot_refs: Any = None,
    notes: Any = None,
) -> dict[str, Any]:
    """构建 rfauto-datasheet/v1 模型（纯 dict，可 json.dumps）。

    - meta：docs/templates/<t>/meta.yaml 形态（nominal_params/substrate/
      topology）→ 名义电气行 + 机械尺寸行；
    - report：``build_report_model`` 输出 → 实测行 + S 参曲线节点透传；
    - typical_application：{"text", "source"}（来源强制）；
    - field_plot_refs：场图产物路径清单 [{"name", "path"}]（只登记引用，
      不内嵌图像数据）；
    - notes：随行注记（字符串列表）。
    """
    part = _text(part_number, "part_number")
    tmpl = _text(template, "template")
    rows = _meta_rows(tmpl, meta) + _report_rows(report)

    mech_rows = [
        r for r in _meta_rows(tmpl, meta)
        if r["unit"] == "mm"
    ]

    ta: dict[str, Any] | None = None
    if typical_application is not None:
        if not isinstance(typical_application, dict):
            raise ValueError("typical_application 必须为 dict")
        ta = {
            "text": _text(typical_application.get("text"), "typical_application.text"),
            "source": _text(typical_application.get("source"), "typical_application.source"),
        }

    fp_refs: list[dict[str, Any]] = []
    if field_plot_refs is not None:
        if not isinstance(field_plot_refs, (list, tuple)):
            raise ValueError("field_plot_refs 必须为列表")
        for raw in field_plot_refs:
            if not isinstance(raw, dict):
                raise ValueError("field_plot_refs 条目必须为 dict")
            fp_refs.append({
                "name": _text(raw.get("name"), "field_plot_refs.name"),
                "path": _text(raw.get("path"), "field_plot_refs.path"),
            })

    note_list = [_text(n, "notes") for n in notes] if notes else []

    curves: dict[str, Any] = {
        "source": "none:no-run-provided",
        "status": "missing",
        "freq_ghz": [],
        "traces": [],
        "n_points": 0,
        "n_traces": 0,
        "note": "未提供 run 报告——S 参图如实缺（不伪造）",
    }
    if isinstance(report, dict):
        rc = report.get("curves")
        if isinstance(rc, dict):
            curves = rc

    sources = sorted({
        r["source"] for r in rows
    } | ({"report:" + str(report.get("identification", {}).get("run_dir", "unknown"))}
         if isinstance(report, dict) else set()))

    model: dict[str, Any] = {
        "schema": DATASHEET_SCHEMA,
        "disclaimer": DATASHEET_DISCLAIMER,
        "identification": {
            "part_number": part,
            "template": tmpl,
            "topology": str(meta.get("topology")) if isinstance(meta, dict) and meta.get("topology") else None,
        },
        "electrical": {"rows": rows},
        "curves": curves,
        "typical_application": ta,
        "mechanical": {"rows": mech_rows},
        "field_plot_refs": fp_refs,
        "notes": note_list,
        "sources": sources,
    }
    bare = bare_number_fields(model)
    if bare:
        # 构建期自检（PR-4 规则 2 复用）：裸数字=0 才放行
        raise ValueError(f"datasheet 模型存在裸数字节点（缺 source）：{bare[:5]}")
    return model


def render_markdown(model: dict[str, Any]) -> str:
    """datasheet 模型 → markdown（确定性；数值统一 fmt_value）。"""
    lines: list[str] = []
    lines.append(f"# 规格书：{model['identification']['part_number']}")
    lines.append("")
    lines.append(f"> **{model['disclaimer']}**")
    lines.append("")
    ident = model["identification"]
    meta_bits = [f"template：{ident['template']}"]
    if ident.get("topology"):
        meta_bits.append(f"拓扑：{ident['topology']}")
    lines.append("- " + " ｜ ".join(meta_bits))
    lines.append("")
    lines.append("## 电气规格")
    lines.append("")
    lines.append("| 参数 | 值 | 单位 | 出处 |")
    lines.append("|---|---|---|---|")
    for r in model["electrical"]["rows"]:
        lines.append(
            f"| {r['param']} | {fmt_value(r['value'])} | {r['unit']} | {r['source']} |"
        )
    lines.append("")
    lines.append("## S 参数曲线")
    lines.append("")
    c = model["curves"]
    lines.append(f"- status：{c['status']} ｜ 采点 {c['n_points']} ｜ trace {c['n_traces']} ｜ 出处：{c['source']}")
    for t in c.get("traces", []):
        lines.append(f"  - {t['label']}（{t['source']}）")
    lines.append("")
    if model.get("typical_application"):
        ta = model["typical_application"]
        lines.append("## 典型应用")
        lines.append("")
        lines.append(ta["text"])
        lines.append("")
        lines.append(f"出处：{ta['source']}")
        lines.append("")
    lines.append("## 机械尺寸")
    lines.append("")
    lines.append("| 参数 | 值 | 单位 | 出处 |")
    lines.append("|---|---|---|---|")
    for r in model["mechanical"]["rows"]:
        lines.append(
            f"| {r['param']} | {fmt_value(r['value'])} | {r['unit']} | {r['source']} |"
        )
    lines.append("")
    if model.get("field_plot_refs"):
        lines.append("## 场图引用")
        lines.append("")
        for ref in model["field_plot_refs"]:
            lines.append(f"- {ref['name']}：`{ref['path']}`")
        lines.append("")
    for n in model.get("notes", []):
        lines.append(f"> 注：{n}")
        lines.append("")
    lines.append("## 来源清单")
    lines.append("")
    for s in model["sources"]:
        lines.append(f"- {s}")
    return "\n".join(lines)


def render_html(model: dict[str, Any]) -> str:
    """datasheet 模型 → 自包含 HTML（S 参图经 plotly 内联，零外网 CDN）。

    plotly 不可用（未装）时曲线节降级为表列注记——渲染不炸（#105 缺产物
    如实降级同源）。
    """
    from html import escape as esc

    ident = model["identification"]
    parts = [
        "<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"utf-8\">",
        f"<title>规格书 {esc(ident['part_number'])}</title>",
        "<style>body{font-family:\"Microsoft YaHei\",sans-serif;margin:24px auto;"
        "max-width:960px}h1{border-bottom:2px solid #334}h2{border-bottom:1px solid #99a}"
        "table{border-collapse:collapse;margin:8px 0}th,td{border:1px solid #bbb;"
        "padding:3px 8px;text-align:left}th{background:#eef}"
        ".disclaimer{background:#fff3cd;padding:8px 12px;border:1px solid #e0c860}</style></head><body>",
        f"<h1>规格书：{esc(ident['part_number'])}</h1>",
        f"<p class=\"disclaimer\"><strong>{esc(model['disclaimer'])}</strong></p>",
        f"<p class=\"meta\">template：{esc(ident['template'])}"
        + (f" ｜ 拓扑：{esc(str(ident['topology']))}" if ident.get("topology") else "")
        + "</p>",
        "<h2>电气规格</h2><table><tr><th>参数</th><th>值</th><th>单位</th><th>出处</th></tr>",
    ]
    for r in model["electrical"]["rows"]:
        parts.append(
            f"<tr><td>{esc(r['param'])}</td><td>{esc(fmt_value(r['value']))}</td>"
            f"<td>{esc(r['unit'])}</td><td>{esc(r['source'])}</td></tr>"
        )
    parts.append("</table>")
    c = model["curves"]
    parts.append(
        f"<h2>S 参数曲线</h2><p class=\"meta\">status：{esc(c['status'])} ｜ "
        f"采点 {c['n_points']} ｜ trace {c['n_traces']} ｜ 出处：{esc(c['source'])}</p>"
    )
    if c.get("status") == "ok" and c.get("freq_ghz") and c.get("traces"):
        try:
            import plotly.graph_objects as go

            fig = go.Figure()
            for t in c["traces"]:
                fig.add_trace(go.Scatter(x=c["freq_ghz"], y=t["values_db"],
                                         mode="lines", name=str(t["label"])))
            fig.update_layout(
                title="S 参数（dB）", xaxis_title="freq (GHz)", yaxis_title="dB",
                template="plotly_white",
            )
            parts.append(fig.to_html(full_html=False, include_plotlyjs=True))
        except Exception as exc:
            parts.append(f"<p class=\"meta\">plotly 渲染不可用（{esc(str(exc))}）——曲线数据在模型 curves 节</p>")
    else:
        parts.append("<p class=\"meta\">曲线缺失（如实，不伪造）</p>")
    if model.get("typical_application"):
        ta = model["typical_application"]
        parts.append(f"<h2>典型应用</h2><p>{esc(ta['text'])}</p>"
                     f"<p class=\"meta\">出处：{esc(ta['source'])}</p>")
    parts.append("<h2>机械尺寸</h2><table><tr><th>参数</th><th>值</th><th>单位</th><th>出处</th></tr>")
    for r in model["mechanical"]["rows"]:
        parts.append(
            f"<tr><td>{esc(r['param'])}</td><td>{esc(fmt_value(r['value']))}</td>"
            f"<td>{esc(r['unit'])}</td><td>{esc(r['source'])}</td></tr>"
        )
    parts.append("</table>")
    for ref in model.get("field_plot_refs", []):
        parts.append(f"<p class=\"meta\">场图 {esc(ref['name'])}：`{esc(ref['path'])}`</p>")
    for n in model.get("notes", []):
        parts.append(f"<p class=\"meta\">注：{esc(n)}</p>")
    parts.append("<h2>来源清单</h2><ul>")
    for s in model["sources"]:
        parts.append(f"<li>{esc(s)}</li>")
    parts.append("</ul></body></html>")
    return "".join(parts)
