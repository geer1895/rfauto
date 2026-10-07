"""QW-4 模板画廊静态页导出器：TEMPLATE_META 全模板能力卡 lite 单 HTML。

数据面（全只读、全离线）：
- 模板元数据：src/rfauto/adapters/openems_templates.py 的 TEMPLATE_META
  （键数以 test_gallery_export 的 meta.yaml 交叉校验钉为准，不在
  docstring 钉死——#97 数字随代码实测）；
- 名义参数：同模块 TEMPLATE_NOMINAL（与 docs/templates/<t>/meta.yaml 的
  nominal_params 逐键一致——一致性由 test_gallery_export 的 meta.yaml
  交叉校验钉全量扫描；列表值按 JSON 渲染）；
- 锚覆盖：core/anchors.AnchorRecord.template_family（"锚→模板"映射在
  core 模型层存在，直接消费；通配 "*" 计入全部模板；经
  infra/anchors_store.load_anchors 装载，6 锚实测）；
- 文档链接：docs/models/<t>.md 存在才生成相对链接（当前不存在则如实无链接）；
- 模板族分类（PR-5 X1）：service/gallery_service.TEMPLATE_FAMILIES（单一
  事实源，显式策展映射；未登记名如实 "other"）。

产物：单文件自包含 HTML（内联 CSS/JS、零外链零框架，离线可开；内联脚本
为渐进增强筛选——搜索/模板族/锚覆盖，卡面数据走 data-* 属性，禁用 JS 时
全部卡片照常可见=零 JS 现态）；排序字母序；全部插值经 html.escape。
确定性：同输入两次生成逐字节一致
（时间戳不进产物，--stamp 显式开启才写入生成时刻）。

用法：
    python scripts/gallery_export.py                    # 缺省 runs/gallery.html
    python scripts/gallery_export.py --out docs/gallery.html
    python scripts/gallery_export.py --template patch   # 单模板调试
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "runs" / "gallery.html"
DOCS_REL = ("docs", "models")  # model_docs 落点（generate_model_docs 默认输出目录）


def _fmt(value: Any) -> str:
    """标量原值字符串化；None→"-"；list/dict 按 JSON 紧凑渲染（键序确定）。"""
    if value is None:
        return "-"
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    return str(value)


def match_anchor_ids(template: str, anchor_records: list[Any]) -> list[str]:
    """锚→模板匹配：template_family 含通配 "*" 或显式含模板名即覆盖。"""
    return sorted(
        str(r.anchor_id) for r in anchor_records
        if "*" in r.template_family or template in r.template_family)


def collect_cards(*, templates: dict[str, dict[str, Any]] | None = None,
                  nominal: dict[str, dict[str, Any]] | None = None,
                  anchor_records: list[Any] | None = None,
                  repo_root: Path | None = None) -> list[dict[str, Any]]:
    """组装每模板能力卡（字母序；数据源可注入以便离线测试）。"""
    if templates is None:
        from rfauto.adapters.openems_templates import TEMPLATE_META
        templates = TEMPLATE_META
    if nominal is None:
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
        nominal = TEMPLATE_NOMINAL
    if anchor_records is None:
        from rfauto.infra.anchors_store import load_anchors
        anchor_records = load_anchors().records
    # 模板族分类（PR-5 X1）：单一事实源在 service/gallery_service（服务层
    # 家法：数据解释放服务层）；未登记名如实回退 "other"，注入 fixture 安全。
    from rfauto.service.gallery_service import FAMILY_LABELS, template_family
    root = Path(repo_root) if repo_root else REPO_ROOT

    cards: list[dict[str, Any]] = []
    for name in sorted(templates):
        meta = templates[name]
        anchor_ids = match_anchor_ids(name, anchor_records)
        specific = sorted(
            str(r.anchor_id) for r in anchor_records
            if "*" not in r.template_family and name in r.template_family)
        doc_path = root.joinpath(*DOCS_REL, f"{name}.md")
        fam = template_family(name)
        fam_label = FAMILY_LABELS.get(fam, fam)
        cards.append({
            "name": name,
            "topology": meta.get("topology"),  # 描述面；52/55 有，缺如实 None
            "f0_ghz": meta.get("f0_ghz"),
            "n_ports": meta.get("n_ports"),
            "max_time_ns": meta.get("max_time_ns"),
            "extraction": meta.get("extraction"),
            "params": list(meta.get("params") or []),
            "param_semantics": meta.get("param_semantics"),
            "mesh_note": meta.get("mesh_note"),
            "nominal_params": nominal.get(name),  # meta.yaml 同源（实测一致）
            "anchor_ids": anchor_ids,
            "anchor_specific_ids": specific,
            "doc_path": doc_path if doc_path.is_file() else None,
            "doc_rel": "/".join((*DOCS_REL, f"{name}.md")),
            # UX-A7 画廊深链（VI-3 W2-B 并档）：模板 meta.yaml 仓库相对路径
            # （与 service/gallery_service.gallery_cards docs_link 同式同源）
            "docs_link": f"docs/templates/{name}/meta.yaml",
            # PR-5 X1 交互化字段：族键 + 搜索文本（名+族标签+拓扑，卡内字段）
            "family": fam,
            "family_label": fam_label,
            "search_text": " ".join(
                s for s in (name, fam_label, _fmt(meta.get("topology")))
                if s and s != "-"),
        })
    return cards


# ── PR-5 X1 交互化：工具栏 + 渐进增强内联脚本（零依赖零外链）────────────────

INTERACTIVE_JS = """<script>
(function () {
  "use strict";
  var bar = document.getElementById("gf-toolbar");
  if (!bar) { return; }
  bar.hidden = false;
  var cards = Array.prototype.slice.call(document.querySelectorAll("[data-tpl]"));
  var q = document.getElementById("gf-q");
  var st = document.getElementById("gf-status");
  var empty = document.getElementById("gf-empty");
  var fam = "all";
  var anc = "all";
  function apply() {
    var toks = ((q && q.value) || "").toLowerCase().split(/\\s+/).filter(Boolean);
    var shown = 0;
    cards.forEach(function (c) {
      var ok = true;
      if (fam !== "all" && c.getAttribute("data-family") !== fam) { ok = false; }
      if (ok && anc !== "all" && c.getAttribute("data-coverage") !== anc) { ok = false; }
      if (ok && toks.length) {
        var hay = (c.getAttribute("data-search") || "").toLowerCase();
        for (var i = 0; i < toks.length; i++) {
          if (hay.indexOf(toks[i]) < 0) { ok = false; break; }
        }
      }
      c.style.display = ok ? "" : "none";
      if (ok) { shown += 1; }
    });
    if (st) { st.textContent = "显示 " + shown + " / " + cards.length + " 张"; }
    if (empty) { empty.hidden = shown !== 0; }
  }
  function wire(box, attr, set) {
    if (!box) { return; }
    box.addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-" + attr + "]");
      if (!b) { return; }
      set(b.getAttribute("data-" + attr));
      Array.prototype.forEach.call(box.querySelectorAll("button"),
        function (x) {
          x.setAttribute("aria-pressed", x === b ? "true" : "false");
        });
      apply();
    });
  }
  wire(document.getElementById("gf-families"), "fam", function (v) { fam = v; });
  wire(document.getElementById("gf-anchor"), "anc", function (v) { anc = v; });
  if (q) { q.addEventListener("input", apply); }
  apply();
})();
</script>"""


def render_filter_toolbar(cards: list[dict[str, Any]]) -> str:
    """筛选工具栏（hidden 起步=零 JS 现态；chips 计数/标签由导出器单源渲染）。"""
    e = html.escape
    fam_counts: dict[str, int] = {}
    for c in cards:
        fam_counts[c["family"]] = fam_counts.get(c["family"], 0) + 1
    n_covered = sum(1 for c in cards if c["anchor_ids"])
    n_none = len(cards) - n_covered
    from rfauto.service.gallery_service import FAMILY_LABELS
    chips = [f"<button type=\"button\" data-fam=\"all\" aria-pressed=\"true\">"
             f"全部 {e(str(len(cards)))}</button>"]
    for key in sorted(fam_counts):
        label = FAMILY_LABELS.get(key, key)
        chips.append(
            f"<button type=\"button\" data-fam=\"{e(key)}\" "
            f"aria-pressed=\"false\">{e(label)} {e(str(fam_counts[key]))}</button>")
    return (
        "<div id=\"gf-toolbar\" hidden>"
        "<label for=\"gf-q\">搜索：</label>"
        "<input id=\"gf-q\" type=\"search\" autocomplete=\"off\" "
        "placeholder=\"模板名 / 拓扑关键字（空格分隔取交集）\"> "
        "<span id=\"gf-families\" role=\"group\" aria-label=\"按模板族筛选\">"
        + "".join(chips) + "</span> "
        "<span id=\"gf-anchor\" role=\"group\" aria-label=\"按锚覆盖筛选\">"
        "<button type=\"button\" data-anc=\"all\" aria-pressed=\"true\">锚全部</button>"
        f"<button type=\"button\" data-anc=\"covered\" aria-pressed=\"false\">"
        f"有锚 {e(str(n_covered))}</button>"
        f"<button type=\"button\" data-anc=\"none\" aria-pressed=\"false\">"
        f"无锚 {e(str(n_none))}</button></span> "
        "<span id=\"gf-status\" role=\"status\"></span></div>")


def render_html(cards: list[dict[str, Any]], *, total_in_registry: int,
                out_dir: Path, n_anchors: int,
                stamp: str | None = None) -> str:
    """渲染单文件自包含 HTML（全插值 escape；无时间戳即确定性）。"""
    e = html.escape
    n_specific = sum(1 for c in cards if c["anchor_specific_ids"])
    n_wildcard_only = sum(1 for c in cards if not c["anchor_specific_ids"]
                          and c["anchor_ids"])
    n_uncovered = sum(1 for c in cards if not c["anchor_ids"])
    n_doclink = sum(1 for c in cards if c["doc_path"] is not None)

    parts: list[str] = [
        "<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "<title>rfauto 模板画廊（静态离线页）</title>",
        "<style>",
        "body{font-family:sans-serif;margin:1.5rem;max-width:110rem;color:#222}",
        "h1{font-size:1.4rem}h3{margin:0 0 .4rem;font-size:1.05rem}",
        ".summary{background:#f4f6f8;border:1px solid #ccd;padding:.5rem .8rem;"
        "font-size:.9rem}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(25rem,1fr));"
        "gap:.8rem;margin-top:1rem}",
        ".card{border:1px solid #bbb;border-radius:6px;padding:.6rem .8rem;"
        "font-size:.85rem}",
        ".meta{color:#555;margin:.2rem 0}",
        ".desc{margin:.3rem 0}",
        ".chips{margin:.3rem 0}.chip{display:inline-block;background:#eef;"
        "border:1px solid #99c;border-radius:3px;padding:0 .35rem;margin:1px;"
        "font-size:.78rem}",
        "table{border-collapse:collapse;margin:.3rem 0}",
        "th,td{border:1px solid #ccc;padding:1px 6px;text-align:left;"
        "font-size:.78rem}th{background:#f0f0f0}",
        ".sem{color:#444;margin:.3rem 0}",
        ".anchors{margin:.3rem 0;color:#262}",
        ".none{color:#a66}",
        ".note{color:#666;font-size:.8rem}",
        # PR-5 X1 交互化工具栏（渐进增强：JS 禁用时 #gf-toolbar 保持 hidden）
        "#gf-toolbar{margin:.6rem 0;padding:.5rem .7rem;background:#f4f6f8;"
        "border:1px solid #ccd;font-size:.88rem}",
        "#gf-toolbar button{cursor:pointer;font:inherit;margin:1px 2px;"
        "padding:0 .45rem;background:#fff;border:1px solid #99c;"
        "border-radius:3px}",
        "#gf-toolbar button[aria-pressed=\"true\"]{background:#345;"
        "color:#fff;border-color:#345}",
        "#gf-toolbar input{font:inherit;padding:2px 6px;min-width:16rem}",
        "#gf-status{margin-left:.5rem;color:#555}",
        "#gf-empty{color:#a66}",
        "button:focus-visible,input:focus-visible{outline:2px solid #b60;"
        "outline-offset:1px}",
        "</style></head><body>",
        "<h1>rfauto 模板画廊（EMSolver 模板能力卡 lite）</h1>",
        f"<p class=\"summary\">模板总数 <b>{e(str(total_in_registry))}</b>"
        f"（本页显示 {e(str(len(cards)))}）；锚注册表共 {e(str(n_anchors))} 条——"
        f"有专属锚覆盖 {e(str(n_specific))} 模板，仅通配锚覆盖"
        f" {e(str(n_wildcard_only))} 模板，无锚覆盖 {e(str(n_uncovered))} 模板；"
        f"文档链接 {e(str(n_doclink))} 卡。</p>",
        render_filter_toolbar(cards),
        "<p class=\"note\">锚覆盖口径：core/anchors.AnchorRecord.template_family"
        "（通配 &quot;*&quot; 计入全部模板）；本页由 scripts/gallery_export.py "
        "离线生成，零外链零框架，可整页离线打开；内联脚本为渐进增强筛选"
        "（搜索/模板族/锚覆盖），禁用 JS 时全部卡片照常可见。</p>",
        "<p id=\"gf-empty\" hidden>无匹配卡片——调整搜索词或筛选条件。</p>",
        "<main class=\"grid\">",
    ]
    for c in cards:
        coverage = "covered" if c["anchor_ids"] else "none"
        parts.append(
            f"<section class=\"card\" id=\"tpl-{e(c['name'])}\" "
            f"data-tpl=\"{e(c['name'])}\" data-family=\"{e(c['family'])}\" "
            f"data-anchors=\"{e(str(len(c['anchor_ids'])))}\" "
            f"data-coverage=\"{coverage}\" "
            f"data-search=\"{e(c['search_text'])}\">")
        parts.append(f"<h3>{e(c['name'])}</h3>")
        parts.append(
            f"<p class=\"meta\">f0 {e(_fmt(c['f0_ghz']))} GHz · "
            f"端口 {e(_fmt(c['n_ports']))} · 时长 ≤{e(_fmt(c['max_time_ns']))} ns</p>")
        parts.append(f"<p class=\"meta\">提取：{e(_fmt(c['extraction']))}</p>")
        parts.append(f"<p class=\"desc\">{e(_fmt(c['topology']))}</p>")
        chips = "".join(f"<span class=\"chip\">{e(p)}</span>"
                        for p in c["params"]) or "<span class=\"none\">-</span>"
        parts.append(f"<div class=\"chips\">{chips}</div>")
        np_ = c["nominal_params"]
        if np_:
            rows = "".join(
                f"<tr><th>{e(str(k))}</th><td>{e(_fmt(v))}</td></tr>"
                for k, v in sorted(np_.items()))
            parts.append(f"<table><tbody>{rows}</tbody></table>")
        else:
            parts.append("<p class=\"none\">名义参数：-</p>")
        parts.append(f"<p class=\"sem\">参数语义：{e(_fmt(c['param_semantics']))}</p>")
        parts.append(f"<p class=\"note\">网格：{e(_fmt(c['mesh_note']))}</p>")
        if c["anchor_ids"]:
            parts.append(
                f"<p class=\"anchors\">锚覆盖 {e(str(len(c['anchor_ids'])))}："
                f"{e('，'.join(c['anchor_ids']))}</p>")
        else:
            parts.append("<p class=\"anchors none\">锚覆盖 0（无覆盖）</p>")
        if c["doc_path"] is not None:
            href = Path(os.path.relpath(c["doc_path"], out_dir)).as_posix()
            parts.append(f"<p class=\"doclink\">文档：<a href=\"{e(href)}\">"
                         f"{e(c['doc_rel'])}</a></p>")
        parts.append("</section>")
    footer = "本页由 scripts/gallery_export.py 生成（确定性输出，无时间戳）。"
    if stamp:
        footer = f"生成时刻 {e(stamp)}（--stamp 显式开启）。"
    parts.append(f"</main><p class=\"note\">{footer}</p>{INTERACTIVE_JS}"
                 "</body></html>")
    return "\n".join(parts)


def write_gallery(out: str | Path, *, template_filter: str | None = None,
                  repo_root: Path | None = None, stamp: str | None = None,
                  templates: dict[str, dict[str, Any]] | None = None,
                  nominal: dict[str, dict[str, Any]] | None = None,
                  anchor_records: list[Any] | None = None) -> Path:
    """组装+渲染+落盘（UTF-8、LF；数据源可注入，缺省读注册表实况）。"""
    root = Path(repo_root) if repo_root else REPO_ROOT
    if templates is None or nominal is None:
        from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL
        templates = templates if templates is not None else TEMPLATE_META
        nominal = nominal if nominal is not None else TEMPLATE_NOMINAL
    total = len(templates)
    if template_filter is not None and template_filter not in templates:
        known = "，".join(sorted(templates))
        raise SystemExit(f"--template {template_filter!r} 不在注册表；可用：{known}")
    if anchor_records is None:
        from rfauto.infra.anchors_store import load_anchors
        anchor_records = load_anchors().records
    sel = ({template_filter: templates[template_filter]}
           if template_filter is not None else templates)
    cards = collect_cards(templates=sel, nominal=nominal,
                          anchor_records=anchor_records, repo_root=root)
    out_path = Path(out).absolute()
    html_text = render_html(cards, total_in_registry=total,
                            out_dir=out_path.parent, n_anchors=len(anchor_records),
                            stamp=stamp)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html_text)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gallery_export",
        description="QW-4：TEMPLATE_META 全模板能力卡 lite 单 HTML 静态导出")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help=f"输出 HTML 路径（缺省 {DEFAULT_OUT}）")
    parser.add_argument("--template", default=None,
                        help="过滤单模板（精确名，调试用）")
    parser.add_argument("--stamp", action="store_true",
                        help="写入生成时刻（缺省确定性输出，无时间戳）")
    args = parser.parse_args(argv)
    stamp = None
    if args.stamp:
        import datetime
        stamp = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    out_path = write_gallery(args.out, template_filter=args.template, stamp=stamp)
    print(f"gallery written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
