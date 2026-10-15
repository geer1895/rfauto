/* rfauto 报告中心页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   TOC+scrollspy + 双 run 对比（PR-4）；打印面在 index.html @media print。 */

import { THEME_COLORS, bodyIsLight, themePick } from "../theme.js";
import { S, T } from "./context.js";
import { esc, escAttr, help, mdReady, mdSanitize } from "./dom.js";
import { bindClickRows, kitBadge, kitClickRowAttrs, kitPanelHead, kitTable } from "./kit.js";

/* ═══ 报告中心（阶段 3.5；PR-4 深化：①TOC+scrollspy ③双 run 对比；
   ②打印面=@media print 在 index.html，浏览器"打印为 PDF"不自研）═══ */

/* PR-4 ①：报告 TOC——marked 渲染后给 h2/h3 稳定 id（slug 去重 + 序号兜底），
   >3 节出左侧栏 + scrollspy（window scroll 被动监听；nav 摘除时自清理）。 */
function buildReportToc(body) {
  const heads = [...body.querySelectorAll("h2, h3")];
  const used = new Set();
  heads.forEach((h, i) => {
    const base = "sec-" + (h.textContent || "").trim().toLowerCase()
      .replace(/[^\w\u4e00-\u9fff]+/g, "-").replace(/^-+|-+$/g, "");
    let id = base || "sec-" + i;
    let n = 2;
    while (used.has(id) || document.getElementById(id)) id = `${base}-${n++}`;
    used.add(id);
    h.id = id;
  });
  if (heads.length <= 3) return null; // 短报告不出目录（规格口径）
  const nav = document.createElement("nav");
  nav.className = "report-toc";
  nav.setAttribute("aria-label", "报告目录");
  nav.innerHTML = heads.map((h) => {
    const lvl = h.tagName === "H3" ? "toc-h3" : "toc-h2";
    return `<a href="#${escAttr(h.id)}" data-t="${escAttr(h.id)}" class="${lvl}">${esc(h.textContent || "")}</a>`;
  }).join("");
  const links = {};
  nav.querySelectorAll("a").forEach((a) => { links[a.dataset.t] = a; });
  const spy = () => {
    let cur = heads[0];
    for (const h of heads) if (h.getBoundingClientRect().top <= 120) cur = h;
    for (const h of heads) {
      const a = links[h.id];
      if (a) a.classList.toggle("active", h === cur);
    }
  };
  const onScroll = () => {
    if (!nav.isConnected) { window.removeEventListener("scroll", onScroll); return; }
    spy();
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  nav.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a) return;
    e.preventDefault();
    const h = document.getElementById(a.dataset.t);
    if (h) h.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  spy();
  return nav;
}

/* PR-4 ③：双 run 对比（只读）：GET /api/runs/diff 服务面 +
   两栏 diff 表 + 单 PlotCard 叠图；跨模型显式警示"口径不同"。 */
async function renderRunDiff() {
  const out = T.$("rd-out");
  if (!out) return;
  const a = T.$("rd-a").value, b = T.$("rd-b").value;
  if (!a || !b || a === b) { out.innerHTML = "<span class='muted'>选两个不同的 run</span>"; return; }
  out.innerHTML = "<span class='spin'></span> 对比中...";
  const d = await T.api("/api/runs/diff?a=" + encodeURIComponent(a) +
                        "&b=" + encodeURIComponent(b));
  if (!d.ok) {
    out.innerHTML = `<span style="color:var(--err)">${esc((d.errors || ["对比失败"]).join("; "))}</span>`;
    return;
  }
  const fmt = (x) => (x == null || typeof x !== "number") ? "-" : (+x).toFixed(4);
  const j = (x) => esc(JSON.stringify(x ?? null));
  const crossModel = !d.same_model || !d.same_adapter;
  const ma = d.a?.model || "?", mb = d.b?.model || "?";
  const aa = d.a?.adapter || "?", ab = d.b?.adapter || "?";
  const mrows = Object.entries(d.metrics_delta || {}).map(([k, v]) =>
    `<tr><td><b>${esc(k)}</b></td><td class="muted">${esc(fmt(v.a))}</td>` +
    `<td class="muted">${esc(fmt(v.b))}</td><td>${esc(fmt(v.delta))}</td></tr>`).join("");
  const prows = (d.params_recursive_diff || []).map((e) =>
    `<tr><td class="muted">${esc(e.path)}</td><td>${esc(e.kind)}</td>` +
    `<td class="muted">${j(e.a)}</td><td class="muted">${j(e.b)}</td></tr>`).join("");
  const hints = (d.verdict_hints || []).map((h) => `· ${esc(h)}`).join("<br>");
  let html = "";
  if (crossModel)
    html += `<div style="color:var(--warn);border:1px dashed var(--warn);border-radius:var(--radius-sm);padding:var(--space-2) var(--space-3);margin-bottom:10px">` +
      `⚠ 口径不同：模型 a=${esc(ma)} / b=${esc(mb)}，通道 a=${esc(aa)} / b=${esc(ab)}` +
      `——指标与曲线不可直接比较，仅作形态参考。</div>`;
  html += `<div class="muted" style="margin-bottom:var(--space-2)">${hints}</div>`;
  // A7-A ui-kit 试点：两表壳单源（kitTable；空态行走原样覆盖串——原
  // colspan='4' 单引号形态逐字节保留）
  html += `<div class="grid2"><div><b class="muted">指标 Δ（b − a）</b>` +
    kitTable({
      columns: ["指标", "a", "b", "Δ"], rowsHtml: mrows,
      empty: "<tr><td colspan='4' class='muted'>两侧均无指标</td></tr>",
    }) + `</div>` +
    `<div><b class="muted">配方快照递归 diff（${(d.params_recursive_diff || []).length} 处）</b>` +
    `<div style="max-height:260px;overflow:auto">` +
    kitTable({
      columns: ["路径", "类型", "a", "b"], rowsHtml: prows,
      empty: "<tr><td colspan='4' class='muted'>快照无差异</td></tr>",
    }) + `</div></div></div>`;
  html += `<b class="muted">S 参数叠图（a 前 5 色蓝系 / b 橙系，dB）</b><div id='rd-chart'></div>`;
  out.innerHTML = html;
  const series = [];
  const ca = themePick(bodyIsLight(), THEME_COLORS.seriesBlue);
  const cb = themePick(bodyIsLight(), THEME_COLORS.seriesOrange);
  for (const c of (d.sparams_a?.curves || []))
    series.push({ name: "a·" + (c.file || "") + "·" + c.name, x: c.freq_ghz, y: c.y, color: ca });
  for (const c of (d.sparams_b?.curves || []))
    series.push({ name: "b·" + (c.file || "") + "·" + c.name, x: c.freq_ghz, y: c.y, color: cb });
  const chartEl = T.$("rd-chart");
  if (series.length)
    T.plotCard(chartEl, {
      series, height: "340px", xlabel: "GHz", ylabel: "dB",
      crosshair: true, exportName: "run-diff-overlay",
    });
  else
    chartEl.innerHTML = "<span class='muted'>两侧均无 Touchstone 产物（fake 通道无曲线可叠）</span>";
}

export async function pageReports() {
  const v = T.$("view-reports");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>汇总 runs/ 下全部人读报告：run 五要素报告（report.md）、夜间回归（sim_ci_report.md）、校准报告（calibration/report.md）。</li>
      <li>点行在右侧渲染；长报告（&gt;3 个 h2/h3 节）自动出<b>左侧目录</b>，点击跳转、滚动高亮当前节。</li>
      <li><b>双 run 对比</b>（页底）：选 A/B 两个 run 出参数递归 diff、指标 Δ 与 S 参数叠图；跨模型对比会显式警示「口径不同」。</li>
      <li>打印/存 PDF：浏览器「打印 → 另存为 PDF」，导航/工具条/按钮自动隐藏、强制白底。</li>
      <li>原文可折叠展开。报告是产物，中心只读不写。</li>`) +
    `<h2 class='page'>报告中心</h2>
     <div style='display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap'>
       <div class='panel' style='flex:1;min-width:330px'><div class='toolbar'><b>报告清单</b>
         <span id='rp-count' class='muted'></span></div>
         <table id='rp-table'><thead><tr><th scope="col">run</th><th scope="col">类型</th><th scope="col">模型</th><th scope="col">大小</th></tr></thead><tbody></tbody></table></div>
       <div class='panel' style='flex:1.4;min-width:420px'><div class='toolbar'><b id='rp-title'>选择左侧报告查看</b></div>
         <div id='rp-view' class='muted'>—</div></div>
     </div>
     ${kitPanelHead("双 run 对比（只读 diff + S 参数叠图）", "", "style='margin-top:14px'")}
       <div class='toolbar'>A: <select id='rd-a' style='max-width:320px'></select>
         B: <select id='rd-b' style='max-width:320px'></select>
         <button class='act' id='rd-go'>对比</button>
         <span id='rd-info' class='muted'></span></div>
       <div id='rd-out' class='muted'>选择两个 run 后点「对比」</div></div>`;
  const d = await T.api("/api/reports");
  const list = d.reports || [];
  T.$("rp-count").textContent = `${list.length} 份`;
  // A7-A ui-kit：报告类别→类映射单源（kitBadge 查 KIT_STATUS_CLS；未列类别
  // 一律 muted——run 报告/未知类别同串）。标签三元为三类各自的中文文案，保留。
  const kindBadge = (k) => kitBadge(k === "sim_ci" ? "夜间回归" : k === "calibration" ? "校准" : "run 报告", k);
  const tbody = T.$("rp-table").querySelector("tbody");
  // UI-R4：报告行键盘可达（tr 行 role:null 保 row/cell 语义；aria-label 行
  // 动作）——空态行（暂无报告）无 data-p 不入选择器，不伪装成可交互行
  tbody.innerHTML = list.map((r) =>
    `<tr data-p='${escAttr(r.path)}' ${kitClickRowAttrs({ role: null, label: "查看报告：" + (r.run_id || "") })} style='cursor:pointer'><td class='muted'>${esc(r.run_id)}</td>
     <td>${kindBadge(r.kind)}</td><td>${esc(r.model || "-")}</td>
     <td class='muted'>${(r.size_bytes / 1024).toFixed(1)} KB</td></tr>`).join("")
    || "<tr><td colspan='4' class='muted'>暂无报告</td></tr>";
  // UI-R4：click 与 Enter/Space 同一激活（bindClickRows 单源）
  bindClickRows(tbody, async (tr) => {
    const c = await T.api("/api/reports/content?path=" + encodeURIComponent(tr.dataset.p));
    const view = T.$("rp-view");
    if (!c.ok) { view.textContent = (c.errors || []).join("; "); return; }
    T.$("rp-title").textContent = c.path;
    const body = document.createElement("div");
    body.className = "report-body";
    // D-05：净化器不可用 → esc() 转义纯文本分支（内容永不作为 HTML 解释，
    // 与 textContent 兜底同保证；模板拼接语境用 esc 单点，见 mdReady 注）
    body.innerHTML = window.marked && mdReady()
      ? mdSanitize(window.marked.parse(c.content))
      : `<pre>${esc(c.content)}</pre>`;
    // 图片相对引用重写（项 2 裂图修复）：report.md 里 results/figs/x.png
    // 相对页面 URL 会 404，改指向白名单路由 /api/runs/<run_id>/figs/...；
    // 图缺失（404）时显示"该 run 无此图"占位而非裂图。
    const rid = c.run_id
      || ((String(tr.dataset.p).replace(/\\/g, "/").match(/runs\/([^/]+)\//) || [])[1]) || "";
    body.querySelectorAll("img").forEach((img) => {
      const src = (img.getAttribute("src") || "").replace(/\\/g, "/");
      if (!src || /^(https?:|data:|\/)/i.test(src)) return;
      img.src = "/api/runs/" + encodeURIComponent(rid) + "/figs/" + src;
      img.onerror = () => {
        const ph = document.createElement("div");
        ph.className = "muted";
        ph.style.cssText = "border:1px dashed var(--border);border-radius:var(--radius-xs);padding:var(--space-2);margin:6px 0";
        ph.textContent = `该 run 无此图：${src}（未生成或已清理）`;
        img.replaceWith(ph);
      };
    });
    view.innerHTML = "";
    view.style.display = "flex";
    view.style.gap = "14px";
    view.appendChild(body);
    // PR-4 ①：TOC（>3 节出左侧栏 + scrollspy；短报告保持单栏）
    const toc = buildReportToc(body);
    if (!toc) view.style.display = "";
    else view.prepend(toc);
  }, "tr[data-p]");
  // PR-4 ③：双 run 对比面板（run 清单 + 触发）
  const rd = await T.api("/api/runs?limit=200");
  const runList = rd.runs || [];
  const opts = runList.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.model || "?")} · ${esc(r.adapter || "?")}）</option>`).join("");
  T.$("rd-a").innerHTML = opts;
  T.$("rd-b").innerHTML = opts;
  if (S.currentRunId && runList.some((r) => r.run_id === S.currentRunId))
    T.$("rd-a").value = S.currentRunId;
  T.$("rd-go").onclick = () => renderRunDiff();
}
