/* rfauto S 参数交互视图（架构批 UI-R2 自 pages.js 拆出，逐字节搬移）：
   dB/相位/Smith 三模式 + 外部 .sNp 叠加（Smith 圆图管线在
   view_fieldviz.js drawSmith 单源复用）。 */

import { S, T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
import { fileBrowser } from "./filebrowser.js";
// i18n（架构批 W6-S21 扩面页 4；W8-S32 批 3 补相位模式纵轴）：壳静态标签
// data-i18n+首扫；空态/叠加标题/深链占位/图表纵轴随 load() 重建，文案
// t() 渲染期烘焙（i18n.js 头注纪律；API 警示数据走 esc 拼接，不进词表值）。
import { t, applyI18nRoot } from "./i18n.js";
// 三态收敛（架构批 W2-S5，R1 #8 批1）：错误=kitErrorPanel、无产物=kitEmptyState
import { kitEmptyState, kitErrorPanel } from "./kit.js";
// 深链二批（架构批 W2-S5）：#/sparams/<run_id> 待选消费 + 选中回写 hash
import { _syncRouteHash, consumeSparamsPendingId } from "./router.js";
// P8-9（架构批 W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 4 点）——
// 数据面（run 下拉/Smith 圆图/S 参数曲线）接 viewSignal("sparams") 切页收束
// + aborted 短路（在途拉取不再写隐藏区）；动作面（+外部 .sNp 导入 POST）
// 保持无 signal（用户动作不被切页取消）。信封消费形态逐键不变。
import { apiFetch, viewSignal } from "./api.js";
import { drawSmith } from "./view_fieldviz.js";

/* 页私有状态（W6-S2 S 状态收编：原 S.spMode/S.spRunId/S.spOverlay 单模块
   私有键降级模块级——属主=本模块，契约表见 context.js；S 仍只读共享的
   currentRunId（深链优先级链）。null 初值与原"键缺席"语义逐位等价：
   `null || "db"`、`null || []` 与 `undefined || …` 同值）。 */
let _spMode = null;
let _spRunId = null;
let _spOverlay = null;

/* ═══ S 参数交互视图（阶段 3.1）═══ */
export async function pageSparams() {
  const v = T.$("view-sparams");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("sparams.help_1")}</li>
      <li>${t("sparams.help_2")}</li>
      <li>${t("sparams.help_3")}</li>
      <li>${t("sparams.help_4")}</li>
      <li>${t("sparams.help_5")}</li>`) +
    `<h2 class='page' data-i18n='sparams.title'>${t("sparams.title")}</h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b>
         <select id='sp-run' style='max-width:340px'></select>
         <button class='minor' id='sp-mode-db'>dB</button>
         <button class='minor' id='sp-mode-deg' data-i18n='sparams.mode_deg'>${t("sparams.mode_deg")}</button>
         <button class='minor' id='sp-mode-smith'>Smith</button>
         <button class='minor' id='sp-add-ext' data-i18n='sparams.add_external'>${t("sparams.add_external")}</button>
         <button class='minor' id='sp-clear-ext' data-i18n='sparams.clear_overlay'>${t("sparams.clear_overlay")}</button>
         <span id='sp-info' class='muted'></span></div>
       <div id='sp-charts'></div>
     </div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W6-S21 扩面）
  let mode = _spMode || "db";
  // W7-S35 走查 P2-1：run 下拉此前裸调 /api/runs——服务端缺省 limit=50
  // 只回最近 50 条，带 Touchstone 的较老 run 无法经下拉到达（绕道外部
  // 导入）。显式取大 limit（服务端无上限封顶；500 与全库规模同量级的
  // 安全值，dashboard/palette 的 200 同族口径）。
  const runsResp = await apiFetch("/api/runs?limit=500",
    { signal: viewSignal("sparams") });
  if (runsResp.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const runs = runsResp.runs || [];
  const sel = T.$("sp-run");
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.model || "?")} · ${esc(r.adapter || "?")}）</option>`).join("");
  // 同走查 P2-1 后半：深链 run 不在选项集时 sel.value 赋值静默失败回退
  // 首项——缺项先注入占位选项再赋值，选中态恢复恒可达。
  // 深链二批（架构批 W2-S5）：#/sparams/<run_id> 待选消费（读取并清零，
  // router.js 单源写）——进 _spRunId 单源后走同一占位选项通道，深链 run
  // 不在清单内也恒可达（优先级高于 currentRunId：后赋值胜出）。
  const pendingRun = consumeSparamsPendingId();
  if (pendingRun) _spRunId = pendingRun;
  const hasOpt = (id) => Array.from(sel.options).some((o) => o.value === id);
  for (const want of [S.currentRunId, _spRunId]) {
    if (want && !hasOpt(want)) {
      const o = document.createElement("option");
      o.value = want;
      // W6-S21：占位文案=原始 id 前缀+词表后缀段（run_id 是 API 数据，
      // 不进 t() params——i18n.js 头注纪律）
      o.textContent = want + t("sparams.deeplink_suffix");
      sel.appendChild(o);
    }
  }
  if (S.currentRunId) sel.value = S.currentRunId;
  if (_spRunId) sel.value = _spRunId;

  async function load() {
    _spRunId = sel.value;
    const box = T.$("sp-charts");
    T.$("sp-info").textContent = "";
    if (mode === "smith") {
      // Smith 圆图（G9）：run 各文件 S_ii 轨迹 + 外部叠加轨迹，一张图
      const d = await apiFetch(`/api/smith/${encodeURIComponent(sel.value)}`,
        { signal: viewSignal("sparams") });
      if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
      const overlays = (_spOverlay || []).filter((o) => o.mode === "smith");
      const traces = (d.ok ? d.traces || [] : []).map((t) => ({ ...t, label: `${t.file}·${t.name}` }));
      for (const o of overlays)
        for (const t of o.traces || []) traces.push({ ...t, label: `ext:${o.file}·${t.name}` });
      if (!traces.length) {
        // 三态收敛（R1 #8 批1）：读取失败=kitErrorPanel 带重试；无产物=
        // kitEmptyState（原 muted 单行混两态，拆开如实各表其态）。
        // W6-S21：文案=词表段+esc 警示段拼接（API 数据不进词表值）。
        box.innerHTML = d.ok
          ? kitEmptyState(t("sparams.empty_lead") +
              (d.warning ? "（" + esc(d.warning) + "）" : "") +
              t("sparams.empty_smith_tail"))
          : kitErrorPanel((d.errors || []).join("; "), "sp-retry");
        const rb = T.$("sp-retry");
        if (rb) rb.onclick = load;
        return;
      }
      if (d.warning) T.$("sp-info").textContent = t("sparams.partial_fail") + d.warning;
      box.innerHTML = `<div id='sp-smith'></div>`;
      const grid = d.ok ? d.grid : (overlays[0] && overlays[0].grid);
      drawSmith(T.$("sp-smith"), traces, grid, d.ok ? d.z0 : (overlays[0] && overlays[0].z0));
      return;
    }
    const d = await apiFetch(`/api/sparams/${encodeURIComponent(sel.value)}?mode=${mode}`,
      { signal: viewSignal("sparams") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    // 外部叠加（WP0.3/E8）：只保留与当前模式同量纲的叠加曲线
    const overlays = (_spOverlay || []).filter((o) => o.mode === mode);
    const runCurves = d.ok ? (d.curves || []) : [];
    if (!d.ok && !overlays.length) {
      // 三态收敛（R1 #8 批1）：kitErrorPanel 带重试（原 muted 单行）
      box.innerHTML = kitErrorPanel((d.errors || []).join("; "), "sp-retry");
      const rb = T.$("sp-retry");
      if (rb) rb.onclick = load;
      return;
    }
    if (!runCurves.length && !overlays.length) {
      // 三态收敛（R1 #8 批1）：kitEmptyState（原 muted 单行）。
      // W6-S21：文案=词表段+esc 警示段拼接（同 Smith 分支口径）。
      box.innerHTML = kitEmptyState(t("sparams.empty_lead") +
        (d.warning ? "（" + esc(d.warning) + "）" : "") +
        t("sparams.empty_db_tail"));
      return;
    }
    if (d.warning) T.$("sp-info").textContent = t("sparams.partial_fail") + d.warning;
    // 同文件同频网成组；多文件时各画一张图（文件名标注在标题）
    const groups = {};
    for (const c of runCurves) (groups[c.file] = groups[c.file] || []).push(c);
    const multi = Object.keys(groups).length > 1;
    let html = overlays.length
      ? `<b class='muted'>${t("sparams.overlay_title")}</b><div id='sp-chart-overlay' style='margin-bottom:var(--space-3)'></div>`
      : "";
    html += Object.keys(groups).map((f) =>
      `<div style='margin-bottom:var(--space-3)'>${multi ? `<b class='muted'>${esc(f)}</b>` : ""}<div id='sp-chart-${f.replace(/\W/g, "")}'></div></div>`).join("");
    if (!runCurves.length && overlays.length)
      html = `<b class='muted'>${t("sparams.overlay_only_title")}</b><div id='sp-chart-overlay' style='margin-bottom:var(--space-3)'></div>`;
    box.innerHTML = html;
    for (const [f, curves] of Object.entries(groups)) {
      const id = `sp-chart-${f.replace(/\W/g, "")}`;
      // PR-3 PlotCard 换壳 + crosshair（声明增量：axisPointer cross）
      // W5-S17（R1 §面3 联动 watch 激活）：多文件卡+下方叠加卡同挂
      // connectGroup="sparams"——十字线/dataZoom 跨卡同步（echarts 原生
      // connect，零新依赖；同频段对照工作流，单卡时组同步无副作用）。
      T.plotCard(T.$(id), {
        series: curves.map((c) => ({
          name: c.name, x: c.freq_ghz, y: c.y,
        })),
        xlabel: "GHz", ylabel: mode === "db" ? "dB" : t("sparams.ylabel_deg"),
        height: "340px", zoom: true,
        crosshair: true, exportName: "sparams-" + f.replace(/\W/g, "-"),
        connectGroup: "sparams",
      });
    }
    if (overlays.length) {
      const series = [];
      for (const [f, curves] of Object.entries(groups))
        for (const c of curves) series.push({ name: `${f}·${c.name}`, x: c.freq_ghz, y: c.y });
      for (const o of overlays)
        for (const c of o.curves) series.push({ name: `ext:${o.file}·${c.name}`, x: c.freq_ghz, y: c.y });
      // PR-3 PlotCard 换壳 + crosshair（声明增量：axisPointer cross）
      // W5-S17：叠加对比卡同入 sparams 联动组（与上方 run 产物卡跨卡同步）
      T.plotCard(T.$("sp-chart-overlay"), {
        series,
        xlabel: "GHz", ylabel: mode === "db" ? "dB" : t("sparams.ylabel_deg"),
        height: "360px", zoom: true,
        crosshair: true, exportName: "sparams-overlay",
        connectGroup: "sparams",
      });
    }
  }
  T.$("sp-mode-db").onclick = () => { _spMode = "db"; pageSparams(); };
  T.$("sp-mode-deg").onclick = () => { _spMode = "deg"; pageSparams(); };
  T.$("sp-mode-smith").onclick = () => { _spMode = "smith"; pageSparams(); };
  // UI-R4 a11y：三模式=互斥切换钮，aria-pressed 标注当前态（读屏可知；
  // 本页重入经 onclick→pageSparams() 重建后重同步）
  const syncModePressed = () => {
    for (const [id, m] of [["sp-mode-db", "db"], ["sp-mode-deg", "deg"], ["sp-mode-smith", "smith"]])
      T.$(id).setAttribute("aria-pressed", String(mode === m));
  };
  syncModePressed();
  T.$("sp-add-ext").onclick = () => fileBrowser("", async (p) => {
    const smith = mode === "smith";
    const r = await apiFetch(smith ? "/api/smith/external" : "/api/sparams/external", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(smith ? { path: p } : { path: p, mode }),
    });
    if (!r.ok) { T.msg((r.errors || [t("sparams.import_failed")]).join("; "), false); return; }
    const rmode = smith ? "smith" : r.mode;
    _spOverlay = _spOverlay || [];
    if (_spOverlay.some((o) => o.path === r.path && o.mode === rmode)) {
      T.msg(t("sparams.already_overlay"), false);
      return;
    }
    _spOverlay.push({ path: r.path, file: r.file, mode: rmode, curves: r.curves,
                      traces: r.traces, grid: r.grid, z0: r.z0 });
    T.msg(t("sparams.overlayed") + r.file, true);
    load();
  });
  T.$("sp-clear-ext").onclick = () => { _spOverlay = []; load(); };
  // 深链二批（架构批 W2-S5）：选中回写 hash（replaceState 不触 hashchange，
  // campaign syncCampaignHash 同款纪律）
  const syncSparamsHash = () => { if (sel.value) _syncRouteHash("sparams", sel.value); };
  sel.onchange = () => { syncSparamsHash(); load(); };
  _sparamsReload = load; // R-1：refresh 局部刷新转发登记（sparamsCtx 消费）
  await load();
  syncSparamsHash(); // 深链二批：初载/深链消费后 hash 对齐（刷新/分享保持所选 run）
}

/* ═══ R-1（架构批 W3-S12）：PageContext 增量钩子 sparamsCtx ═══════════
   refresh=免全页重建直刷曲线——load() 闭包经模块级引用转发（campaignCtx
   同款模式）：只重拉当前 run 的曲线/Smith 数据并整换图区（壳/模式钮/run
   下拉不动，叠加清单与模式在模块级状态保持）。无轮询面，leave 不需要。 */
let _sparamsReload = null;
export const sparamsCtx = {
  refresh: () => { const f = _sparamsReload; if (f) f(); },
};
