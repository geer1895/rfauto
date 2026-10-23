/* rfauto 战役仪表盘页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移，
   PR-6）：座位状态 + 成本热图 + trial 虚拟列表；进度刷新=SSE 订阅
   （A6-A）。R-1（aurora_e W2-S7）：PageContext 增量钩子 campaignCtx
   （refresh=当前所选 run 立即拉一次看板；leave 不需要——SSE 收束由
   router._sseLeavePage 单源管，无轮询定时器面）。 */

import {
  CANVAS_FONT, CANVAS_FONT_SMALL, CANVAS_HEAT_LAYOUT, THEME_COLORS, bodyIsLight, themePick,
} from "../theme.js";
import { T } from "./context.js";
import { esc, escAttr, fmtNum, help } from "./dom.js";
// i18n（aurora_h W4-S1 壳层迁移 + 发布令 S3 残量清）：壳静态标签
// data-i18n+首扫、help 块分段 t()、动态串（座位表/进度/best 行/热图 aria/
// 虚拟列表空态）t() 烘焙——API 动态数据（run_id/数字/params_source）照旧
// esc 插值不迁。
import { t, applyI18nRoot } from "./i18n.js";
// R3 人性化三批：看板首拉骨架屏（kitSkeleton 单件；dashboard widget 首拉
// A8-A 同款形态——本页此前无任何加载占位）。
import { kitSkeleton } from "./kit.js";
import { _syncRouteHash, consumeCampaignPendingId } from "./router.js";
import { _sseSubscribe } from "./sse.js";
// P8-9（aurora_f W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 2 点）——
// 数据面全页（run 清单/看板拉取，含 SSE 事件与 ctx.refresh 的重拉）接
// viewSignal("campaign") 切页收束 + aborted 短路（在途拉取不再写隐藏区）。
// 信封消费形态逐键不变。
import { apiFetch, viewSignal } from "./api.js";

/* R-1（W2-S7）：当前看板加载器引用——loadDash 是 pageCampaign 闭包
   （依赖 sel/heatEl），模块级存"最近一次进页的加载器"供 ctx.refresh 调；
   换页重进覆盖式更新，未进过页为 null（palette 刷新对未进页不可达，
   仍按 #105 守卫静默）。 */
let _campaignReload = null;

/* 当前战役 run 记录（W6-S2 S 状态收编：原 S.cpRunId 单模块私有键降级
   模块级——属主=本模块，契约表见 context.js；会话级记忆语义不变）。 */
let _cpRunId = null;

/* ═══ PR-6 战役仪表盘（ge8b Wave B 席B2）：成本热图 + trial 虚拟列表 ═══
   热图=确定性分箱快照（service 端）；进度刷新=选中 run 后订阅 SSE 流
   （P-1 桥，aurora72 A6-A 接通前端消费；流不可用/无事件流时回退「刷新」
   手动）。虚拟列表=窗口化渲染（只画可视行，千行 60fps 零框架）。 */
export async function pageCampaign() {
  const v = T.$("view-campaign");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("campaign.help_1_lead")}<b>${t("campaign.help_1_core")}</b>${t("campaign.help_1_tail")}</li>
      <li><b>${t("campaign.help_2_core")}</b>${t("campaign.help_2_tail")}</li>
      <li><b>${t("campaign.help_3_core")}</b>${t("campaign.help_3_tail")}</li>
      <li>${t("campaign.help_4")}</li>`) +
    `<h2 class='page'><span data-i18n='campaign.title'>${t("campaign.title")}</span> <small data-i18n='campaign.subtitle'>${t("campaign.subtitle")}</small></h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b><select id='cp-run' style='max-width:340px'></select>
         <b>x</b><select id='cp-x' style='max-width:170px'></select>
         <b>y</b><select id='cp-y' style='max-width:170px'></select>
         <b data-i18n='campaign.label_grid'>${t("campaign.label_grid")}</b><input id='cp-n' value='12' style='width:52px'>
         <button class='minor' id='cp-reload' data-i18n='campaign.reload'>${t("campaign.reload")}</button>
         <span id='cp-info' class='muted'></span></div>
       <div id='cp-seats' style='margin-top:6px'></div>
       <div id='cp-heat'></div>
       <div id='cp-best' class='muted' style='margin-top:6px'></div>
     </div>
     <div class='panel' style='margin-top:var(--space-3)'>
       <b class='title'>Trials <span id='cp-tmeta' class='muted' style='font-weight:normal'></span></b>
       <div id='cp-table' style='margin-top:6px'></div>
     </div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W4-S1；幂等，动态容器走 t() 烘焙）
  // R3 人性化三批：看板三容器首拉骨架屏（座位表/成本热图/trials——数据到
  // 后 loadDash() 整体替换；清单空分支显式清场防骨架滞留，见下）。
  for (const id of ["cp-seats", "cp-heat", "cp-table"]) {
    const el = T.$(id);
    if (el) el.innerHTML =
      `<div class="skeleton-wrap" role="status" aria-label="${t("campaign.loading_aria")}">${kitSkeleton(3)}</div>`;
  }
  const listing = await apiFetch("/api/pareto_runs",
    { signal: viewSignal("campaign") });
  if (listing.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const runs = (listing.runs || []).filter((r) => r.tier !== "single");
  const sel = T.$("cp-run");
  if (!runs.length) {
    sel.innerHTML = "<option>" + t("campaign.no_runs_opt") + "</option>";
    T.$("cp-info").textContent = t("campaign.no_runs_hint");
    // R3 同笔：无战役可看——骨架清场（留占位=假加载）
    for (const id of ["cp-seats", "cp-heat", "cp-table"]) {
      const el = T.$(id);
      if (el) el.innerHTML = "";
    }
    return;
  }
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.model || r.adapter || "?")} · ${esc(r.n_trials)} trials）</option>`).join("");
  // aurora72 A4-C：#/campaign/<run_id> 深链消费——列表命中才选，未命中回落
  // 表头（tools 深链同款待选纪律）；消费即清（不残留到下次进页）。
  const _campaignPendingId = consumeCampaignPendingId(); // 读取并清零（router.js 单源写）
  if (_campaignPendingId && runs.some((r) => r.run_id === _campaignPendingId))
    sel.value = _campaignPendingId;
  const syncCampaignHash = () => _syncRouteHash("campaign", sel.value || "");
  const heatEl = T.$("cp-heat");
  async function loadDash() {
    const runId = sel.value;
    if (!runId) return;
    _cpRunId = runId;
    _sseSubscribe("campaign", runId, loadDash, "campaign"); // A6-A：选 run 即订阅进度流（有事件即自动刷新，终态 end 帧收束+末次刷新）
    const q = new URLSearchParams({ x_param: T.$("cp-x").value || "", y_param: T.$("cp-y").value || "", grid_n: T.$("cp-n").value || "12" });
    const d = await apiFetch(`/api/runs/${encodeURIComponent(runId)}/dashboard?${q}`,
      { signal: viewSignal("campaign") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const seatsEl = T.$("cp-seats");
    if (!d.ok) {
      // FAIL 态也走同款真 <table>（X2 座位状态表口径：分色+错误串 esc）
      // UI-R4（A6 P2-9 清零）：座位表表头挂 scope=col（与 kitTable 口径齐；
      // 原裸表头字面钉随本笔更新）
      seatsEl.innerHTML = `<table><thead><tr><th scope="col">${t("campaign.th_seat")}</th><th scope="col">${t("campaign.th_n")}</th><th scope="col">${t("campaign.th_sem")}</th></tr></thead><tbody>` +
        `<tr><td>${T.badge("FAIL", "err")}</td><td>—</td><td>${esc((d.errors || []).join("; "))}</td></tr>` +
        `</tbody></table>`;
      T.$("cp-info").textContent = "";
      heatEl.innerHTML = ""; T.$("cp-table").innerHTML = ""; T.$("cp-best").textContent = "";
      return;
    }
    const skipped = Math.max(0, (d.n_trials_total || 0) - (d.n_trials_used || 0));
    const pct = d.n_trials_total ? Math.round(100 * d.n_trials_used / d.n_trials_total) : 0;
    const bars = Math.max(0, Math.min(20, Math.round(pct / 5)));
    T.$("cp-info").textContent = `${t("campaign.prog_lead")}${"█".repeat(bars)}${"░".repeat(20 - bars)} ${pct}${t("campaign.prog_pct")}${d.n_trials_used}/${d.n_trials_total}${t("campaign.prog_src")}${d.params_source}`;
    // 座位状态表（X2 v1）：PASS=已评入盘（有限 cost）/ SKIP=审计行被剔除
    // （cost 非有限或参数坏，service 端如实剔除）/ FAIL=端点错误态（上方 !d.ok 分支）。
    // 全部数字经 esc 再插值（AU-4）；进度条走 textContent 天然无插值面。
    // UI-R4（A6 P2-9 清零）：表头挂 scope=col（与 kitTable 口径齐）。
    seatsEl.innerHTML = `<table><thead><tr><th scope="col">${t("campaign.th_seat")}</th><th scope="col">${t("campaign.th_n")}</th><th scope="col">${t("campaign.th_sem")}</th></tr></thead><tbody>` +
      `<tr><td>${T.badge("PASS", "ok")}</td><td>${esc(d.n_trials_used)}</td><td class="muted">${t("campaign.seat_pass")}</td></tr>` +
      `<tr><td>${T.badge("SKIP", skipped ? "warn" : "muted")}</td><td>${esc(skipped)}</td><td class="muted">${t("campaign.seat_skip")}</td></tr>` +
      `<tr><td>${T.badge("FAIL", "muted")}</td><td>0</td><td class="muted">${t("campaign.seat_fail")}</td></tr>` +
      `</tbody></table>`;
    const opts = d.params_numeric.map((n) => `<option value='${escAttr(n)}'>${esc(n)}</option>`).join("");
    T.$("cp-x").innerHTML = opts; T.$("cp-y").innerHTML = opts;
    T.$("cp-x").value = d.x_param; T.$("cp-y").value = d.y_param;
    drawCostHeat(heatEl, d);
    T.$("cp-best").textContent = `${t("campaign.best_lead")}${d.best.trial_number} cost=${d.best.cost}${t("campaign.best_mid")}${Object.entries(d.best.params).map(([k, x]) => k + "=" + (+x).toPrecision(6)).join(", ")}${t("campaign.best_tail")}${d.cost_mean}`;
    renderVirtualList(T.$("cp-table"), d.trials,
      (row) => `<td>${fmtNum(row.cost, 4)}</td><td class='muted'>${esc(Object.entries(row.params).map(([k, x]) => k + "=" + (+x).toPrecision(6)).join(" · "))}</td>`,
      "<tr><th scope='col' style='width:70px'>trial</th><th scope='col'>cost</th><th scope='col'>params</th></tr>");
    T.$("cp-tmeta").textContent = `${d.table_rows}${t("campaign.rows_suffix")}${d.table_truncated ? t("campaign.truncated") : ""}`;
  }
  sel.onchange = () => { syncCampaignHash(); loadDash(); }; // A4-C：选择即深链（replaceState 不触 hashchange）
  T.$("cp-reload").onclick = loadDash;
  T.$("cp-x").onchange = loadDash; T.$("cp-y").onchange = loadDash; T.$("cp-n").onchange = loadDash;
  _campaignReload = loadDash; // R-1：登记当前加载器（campaignCtx.refresh 消费）
  await loadDash();
  syncCampaignHash(); // A4-C：初载/深链消费后 hash 对齐（刷新/分享保持所选 run）
}

/* R-1（W2-S7）PageContext：refresh=当前所选 run 立即拉一次看板（与「刷新」
   钮同一 loadDash，palette 刷新不再整页重进）；leave 不需要（无轮询定时器；
   SSE 连接收束由 router._sseLeavePage 单源处理）。 */
export const campaignCtx = {
  refresh: () => { const f = _campaignReload; if (f) f(); },
};

/* 成本热图（canvas，feasibility 网格姊妹面）：格色=格内平均 cost 相对
   [cost_min, cost_max] 的位置（绿低红高）；空格灰。 */
function drawCostHeat(el, d) {
  el.innerHTML = "";
  const light = bodyIsLight();
  const fg = themePick(light, THEME_COLORS.fg);
  const canvas = document.createElement("canvas");
  canvas.style.width = "100%"; canvas.style.height = "340px";
  el.appendChild(canvas);
  const W = canvas.width = canvas.clientWidth || 700, H = canvas.height = 340;
  // W3-S12（P-5）：边距常量收 theme.js 单源（值冻结 60/90/12/40，渲染不变）
  const { left: L, right: R, top: Tp, bottom: B } = CANVAS_HEAT_LAYOUT;
  const ctx = canvas.getContext("2d");
  const xe = d.x_edges, ye = d.y_edges, n = d.grid_n;
  const xmin = xe[0], xmax = xe[xe.length - 1], ymin = ye[0], ymax = ye[ye.length - 1];
  const px = (x) => L + ((x - xmin) / (xmax - xmin || 1)) * (W - L - R);
  const py = (y) => H - B - ((y - ymin) / (ymax - ymin || 1)) * (H - Tp - B);
  const cmin = Math.min(...d.cells.map((c) => c.cost_mean));
  const cmax = Math.max(...d.cells.map((c) => c.cost_mean));
  const color = (r) => {
    if (r === null || r === undefined) return themePick(light, THEME_COLORS.emptyCell);
    const rr = Math.round(80 + 155 * r), gg = Math.round(235 - 155 * r);
    return `rgb(${rr},${gg},70)`;
  };
  const byCell = {};
  for (const c of d.cells) byCell[`${c.i},${c.j}`] = c;
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++) {
      const c = byCell[`${i},${j}`];
      const rel = c ? (cmax > cmin ? (c.cost_mean - cmin) / (cmax - cmin) : 0) : null;
      ctx.fillStyle = color(rel);
      const x0 = px(xe[i]), x1 = px(xe[i + 1]), y0 = py(ye[j + 1]), y1 = py(ye[j]);
      ctx.fillRect(x0, y0, Math.max(1, x1 - x0 - 0.5), Math.max(1, y1 - y0 - 0.5));
      if (c) {
        ctx.fillStyle = fg; ctx.font = CANVAS_FONT_SMALL; ctx.textAlign = "center";
        ctx.fillText(String(c.n), (x0 + x1) / 2, (y0 + y1) / 2 + 3);
      }
    }
  ctx.fillStyle = fg; ctx.font = CANVAS_FONT; ctx.textAlign = "center";
  ctx.fillText(`${d.x_param}  [${xmin.toPrecision(4)} … ${xmax.toPrecision(4)}]`, (L + W - R) / 2, H - 10);
  ctx.save(); ctx.translate(14, (Tp + H - B) / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText(`${d.y_param}  [${ymin.toPrecision(4)} … ${ymax.toPrecision(4)}]`, 0, 0); ctx.restore();
  const cx = W - R + 20, ch = H - Tp - B;
  for (let k = 0; k < ch; k++) {
    ctx.fillStyle = color(k / ch);
    ctx.fillRect(cx, Tp + k, 14, 1);
  }
  ctx.fillStyle = fg; ctx.textAlign = "left";
  ctx.fillText(`cost ${cmax.toPrecision(4)}`, cx + 18, Tp + 10);
  ctx.fillText(`${cmin.toPrecision(4)}`, cx + 18, Tp + ch);
  // UI-R4 a11y：canvas 图像语义（PR-1 图表容器口径补齐本自研管线——
  // 参数名/格数经 String 拼接，不用模板插值直引 d 的字段——XSS 反向扫描口径零新增）
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", t("campaign.heat_aria_lead") + d.x_param + " × " + d.y_param +
    t("campaign.heat_aria_mid") + n + "×" + n + t("campaign.heat_aria_cells"));
  canvas.title = t("campaign.heat_title");
}

/* trial 虚拟列表：窗口化渲染（只画可视行 + 上下缓冲），行高恒定 28px。
   千行级滚动只重绘可视窗（~30 行 DOM），60fps 预算内；零框架 vanilla。
   renderRow 返回行内 <td> 串（首列 trial 号由本函数统一渲染）。 */
function renderVirtualList(el, rows, renderRow, headerHtml) {
  const ROW_H = 28, BUFFER = 8;
  const total = rows.length;
  el.innerHTML = "";
  const head = document.createElement("table");
  head.innerHTML = `<thead>${headerHtml}</thead>`;
  head.style.width = "100%";
  el.appendChild(head);
  const viewport = document.createElement("div");
  viewport.style.cssText = "overflow:auto;max-height:420px;position:relative";
  el.appendChild(viewport);
  if (!total) {
    viewport.innerHTML = "<div class='muted' style='padding:var(--space-2)'>" + t("campaign.no_trial_rows") + "</div>";
    return;
  }
  const spacer = document.createElement("div");
  spacer.style.cssText = `height:${total * ROW_H}px;position:relative`;
  viewport.appendChild(spacer);
  const layer = document.createElement("table");
  layer.style.cssText = "position:absolute;left:0;top:0;width:100%;table-layout:fixed";
  spacer.appendChild(layer);
  let first = -1, last = -1;
  const paint = () => {
    const scrollTop = viewport.scrollTop;
    const visible = Math.ceil(viewport.clientHeight / ROW_H);
    const f = Math.max(0, Math.floor(scrollTop / ROW_H) - BUFFER);
    const l = Math.min(total, f + visible + 2 * BUFFER);
    if (f === first && l === last) return;
    first = f; last = l;
    const body = [];
    for (let i = f; i < l; i++) {
      // trial_number 出自 runs/ trials 审计（#320 导入面外来数据可达）——
      // 与行内 renderRow 同 AU-4 口径一律 esc（X2 补：此前裸插值是 XSS 面）
      body.push(`<tr style='height:${ROW_H}px'><td class='muted'>${esc(rows[i].trial_number)}</td>${renderRow(rows[i])}</tr>`);
    }
    layer.innerHTML = `<tbody>${body.join("")}</tbody>`;
  };
  viewport.onscroll = paint;
  paint();
}
