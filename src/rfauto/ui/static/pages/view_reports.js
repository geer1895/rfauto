/* rfauto 报告中心页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   TOC+scrollspy + 双 run 对比（PR-4）；打印面在 index.html @media print。 */

import { THEME_COLORS, bodyIsLight, themePick } from "../theme.js";
import { S, T } from "./context.js";
import { esc, escAttr, help, mdReady, mdSanitize } from "./dom.js";
// i18n（aurora_h W4-S1 壳层迁移 + 发布令 S3 残量清）：壳静态标签
// data-i18n+首扫、help 块分段 t()、动态串（TOC aria/对比面/清单面/图缺失
// 占位）t() 烘焙——API 动态数据（报告正文/run_id/指标值）照旧 esc 不迁。
import { t, applyI18nRoot } from "./i18n.js";
// 三态收敛（aurora_f W2-S5，R1 #8 批1）：错误=kitErrorPanel、空态=kitEmptyState
import { bindClickRows, kitBadge, kitClickRowAttrs, kitEmptyState, kitErrorPanel, kitPanelHead, kitTable } from "./kit.js";
// 深链二批（aurora_f W2-S5）：#/reports/<path> 待选消费 + 打开 hash 回写
import { _syncRouteHash, consumeReportsPendingId } from "./router.js";
// P8-9（aurora_f W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 4 点）——
// 数据面（报告清单/内容/双 run 对比/run 下拉）接 viewSignal("reports") 切页
// 收束 + aborted 短路（在途拉取不再写隐藏区）。信封消费形态逐键不变。
import { apiFetch, viewSignal } from "./api.js";

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
  nav.setAttribute("aria-label", t("reports.toc_aria"));
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
  if (!a || !b || a === b) { out.innerHTML = "<span class='muted'>" + t("reports.diff_pick_two") + "</span>"; return; }
  out.innerHTML = "<span class='spin'></span>" + t("reports.diff_running");
  const d = await apiFetch("/api/runs/diff?a=" + encodeURIComponent(a) +
                        "&b=" + encodeURIComponent(b),
    { signal: viewSignal("reports") });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  if (!d.ok) {
    // 三态收敛（aurora_f W2-S5，R1 #8 批1）：对比失败=kitErrorPanel（原内联
    // err span；重触发=页底「对比」钮，不加重试钮防双发）
    out.innerHTML = kitErrorPanel((d.errors || [t("reports.diff_failed")]).join("; "));
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
      `${t("reports.warn_lead")}${esc(ma)} / b=${esc(mb)}${t("reports.warn_mid")}${esc(aa)} / b=${esc(ab)}` +
      `${t("reports.warn_tail")}</div>`;
  // C2 aurora_l（R1 #14/15）：freshness 对照行（A/B 各自 K4 状态；stale
  // 标红不硬拒——对比结论可读出"哪边是脏数据"；状态词=协议值透传，人话
  // 修饰走词表 reports.freshness_*；stale_kinds=API 数据 esc 拼接）
  const frBadge = (s) => s === "stale"
    ? `<span style="color:var(--err)">${t("reports.freshness_stale_badge")}</span>`
    : s === "legacy"
      ? `<span class="muted">${t("reports.freshness_legacy_badge")}</span>`
      : s === "unknown"
        ? `<span class="muted">${t("reports.freshness_unknown_badge")}</span>`
        : `<span style="color:var(--ok)">${t("reports.freshness_fresh_badge")}</span>`;
  const frKinds = (side) => side?.stale_kinds
    ? ` <span class="muted">（${esc(side.stale_kinds)}）</span>` : "";
  const fa = d.freshness?.a?.status, fb = d.freshness?.b?.status;
  if (fa || fb)
    html += `<div class="muted" style="margin-bottom:var(--space-2)">` +
      `${t("reports.freshness_row_label")}：a ${frBadge(fa)}${frKinds(d.freshness?.a)}` +
      ` · b ${frBadge(fb)}${frKinds(d.freshness?.b)}</div>`;
  html += `<div class="muted" style="margin-bottom:var(--space-2)">${hints}</div>`;
  // A7-A ui-kit 试点：两表壳单源（kitTable；空态行走原样覆盖串——原
  // colspan='4' 单引号形态逐字节保留）
  html += `<div class="grid2"><div><b class="muted">${t("reports.th_delta_title")}</b>` +
    kitTable({
      columns: [t("reports.col_metric"), "a", "b", "Δ"], rowsHtml: mrows,
      empty: "<tr><td colspan='4' class='muted'>" + t("reports.no_metrics") + "</td></tr>",
    }) + `</div>` +
    `<div><b class="muted">${t("reports.diff_count_lead")}${(d.params_recursive_diff || []).length}${t("reports.diff_count_tail")}</b>` +
    `<div style="max-height:260px;overflow:auto">` +
    kitTable({
      columns: [t("reports.col_path"), t("reports.col_kind"), "a", "b"], rowsHtml: prows,
      empty: "<tr><td colspan='4' class='muted'>" + t("reports.no_diff") + "</td></tr>",
    }) + `</div></div></div>`;
  html += `<b class="muted">${t("reports.sparam_overlay")}</b><div id='rd-chart'></div>`;
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
    chartEl.innerHTML = "<span class='muted'>" + t("reports.no_touchstone") + "</span>";
}

export async function pageReports() {
  const v = T.$("view-reports");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("reports.help_1")}</li>
      <li>${t("reports.help_2_lead")}<b>${t("reports.help_2_core")}</b>${t("reports.help_2_tail")}</li>
      <li><b>${t("reports.help_3_core")}</b>${t("reports.help_3_tail")}</li>
      <li>${t("reports.help_4")}</li>
      <li>${t("reports.help_5")}</li>`) +
    `<h2 class='page' data-i18n='reports.title'>${t("reports.title")}</h2>
     <div style='display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap'>
       <div class='panel' style='flex:1;min-width:330px'><div class='toolbar'><b data-i18n='reports.list_title'>${t("reports.list_title")}</b>
         <span id='rp-count' class='muted'></span></div>
         <table id='rp-table'><thead><tr><th scope="col">run</th><th scope="col">${t("reports.th_kind")}</th><th scope="col">${t("reports.th_model")}</th><th scope="col">${t("reports.th_size")}</th></tr></thead><tbody></tbody></table></div>
       <div class='panel' style='flex:1.4;min-width:420px'><div class='toolbar'><b id='rp-title'>${t("reports.pick_hint")}</b></div>
         <div id='rp-view' class='muted'>—</div></div>
     </div>
     ${kitPanelHead(t("reports.diff_title"), "", "style='margin-top:14px'")}
       <div class='toolbar'>A: <select id='rd-a' style='max-width:320px'></select>
         B: <select id='rd-b' style='max-width:320px'></select>
         <button class='act' id='rd-go' data-i18n='reports.diff_go'>${t("reports.diff_go")}</button>
         <span id='rd-info' class='muted'></span></div>
       <div id='rd-out' class='muted'>${t("reports.diff_hint")}</div></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W4-S1；幂等，动态容器走 t() 烘焙）
  const d = await apiFetch("/api/reports", { signal: viewSignal("reports") });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const list = d.reports || [];
  T.$("rp-count").textContent = `${list.length}${t("reports.count_suffix")}`;
  // A7-A ui-kit：报告类别→类映射单源（kitBadge 查 KIT_STATUS_CLS；未列类别
  // 一律 muted——run 报告/未知类别同键）。标签三元为三类各自文案（协议值
  // sim_ci/calibration 留码侧比较不变，发布令 S3 词表化展示面）。
  const kindBadge = (k) => kitBadge(k === "sim_ci" ? t("reports.kind_sim_ci") : k === "calibration" ? t("reports.kind_calibration") : t("reports.kind_run"), k);
  const tbody = T.$("rp-table").querySelector("tbody");
  // UI-R4：报告行键盘可达（tr 行 role:null 保 row/cell 语义；aria-label 行
  // 动作）——空态行（暂无报告）无 data-p 不入选择器，不伪装成可交互行。
  // 三态收敛（aurora_f W2-S5，R1 #8 批1）：空清单=kitEmptyState 整行三件式
  //（原 muted 空态行；div 入 td 合法，colspan 对齐 4 列表头）。
  tbody.innerHTML = list.length
    ? list.map((r) =>
      `<tr data-p='${escAttr(r.path)}' ${kitClickRowAttrs({ role: null, label: t("reports.row_open_aria") + (r.run_id || "") })} style='cursor:pointer'><td class='muted'>${esc(r.run_id)}</td>
     <td>${kindBadge(r.kind)}</td><td>${esc(r.model || "-")}</td>
     <td class='muted'>${(r.size_bytes / 1024).toFixed(1)} KB</td></tr>`).join("")
    : `<tr><td colspan='4'>${kitEmptyState(t("reports.empty_hint"))}</td></tr>`;
  /* 深链二批（aurora_f W2-S5）：行打开链路抽具名 openReport——点行/深链/
     错误重试三入口同一函数；hash 回写在内容就绪落地点（replaceState 不产
     历史条目不触 hashchange，刷新/分享保持所选报告）。 */
  const openReport = async (path) => {
    const c = await apiFetch("/api/reports/content?path=" + encodeURIComponent(path),
      { signal: viewSignal("reports") });
    if (c.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const view = T.$("rp-view");
    if (!c.ok) {
      // 三态收敛（R1 #8 批1）：内容读取失败=kitErrorPanel 带重试（重开同一报告）
      view.innerHTML = kitErrorPanel((c.errors || []).join("; "), "rp-retry");
      const rb = T.$("rp-retry");
      if (rb) rb.onclick = () => openReport(path);
      return;
    }
    _syncRouteHash("reports", path);
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
      || ((String(path).replace(/\\/g, "/").match(/runs\/([^/]+)\//) || [])[1]) || "";
    body.querySelectorAll("img").forEach((img) => {
      const src = (img.getAttribute("src") || "").replace(/\\/g, "/");
      if (!src || /^(https?:|data:|\/)/i.test(src)) return;
      img.src = "/api/runs/" + encodeURIComponent(rid) + "/figs/" + src;
      img.onerror = () => {
        const ph = document.createElement("div");
        ph.className = "muted";
        ph.style.cssText = "border:1px dashed var(--border);border-radius:var(--radius-xs);padding:var(--space-2);margin:6px 0";
        ph.textContent = `${t("reports.img_missing_lead")}${src}${t("reports.img_missing_tail")}`;
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
  };
  // UI-R4：click 与 Enter/Space 同一激活（bindClickRows 单源；点行/深链/
  // 重试三入口同一 openReport 链路）
  bindClickRows(tbody, (tr) => openReport(tr.dataset.p), "tr[data-p]");
  // 深链二批（aurora_f W2-S5）：#/reports/<path> 待选消费——清单命中才打开，
  // 未命中回落表头（campaign 深链同款待选纪律）；消费即清（router.js 单源写）。
  const pendingReport = consumeReportsPendingId();
  if (pendingReport && list.some((r) => r.path === pendingReport))
    openReport(pendingReport);
  // PR-4 ③：双 run 对比面板（run 清单 + 触发）
  const rd = await apiFetch("/api/runs?limit=200", { signal: viewSignal("reports") });
  if (rd.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const runList = rd.runs || [];
  const opts = runList.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.model || "?")} · ${esc(r.adapter || "?")}）</option>`).join("");
  T.$("rd-a").innerHTML = opts;
  T.$("rd-b").innerHTML = opts;
  if (S.currentRunId && runList.some((r) => r.run_id === S.currentRunId))
    T.$("rd-a").value = S.currentRunId;
  T.$("rd-go").onclick = () => renderRunDiff();
}

/* ═══ R-1（aurora_e W2-S7）：PageContext 增量钩子 reportsCtx ═══════════
   refresh=报告清单重拉（pageReports 幂等——壳判 innerHTML 已在即跳过、
   清单/对比面板 run 下拉重填、行绑定 bindClickRows 覆盖式幂等）。无轮询/
   定时器面，leave 不需要。 */
export const reportsCtx = {
  refresh: () => pageReports(),
};
