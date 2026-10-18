/* rfauto S 参数交互视图（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   dB/相位/Smith 三模式 + 外部 .sNp 叠加（Smith 圆图管线在
   view_fieldviz.js drawSmith 单源复用）。 */

import { S, T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
import { fileBrowser } from "./filebrowser.js";
import { drawSmith } from "./view_fieldviz.js";

/* ═══ S 参数交互视图（阶段 3.1）═══ */
export async function pageSparams() {
  const v = T.$("view-sparams");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>选一个 run，交互查看全部 S 参数曲线：图例点选隐藏/显示、滚轮+滑块缩放、悬停读数。</li>
      <li>dB 模式看匹配/损耗谷位；相位模式（解缠绕）看电长度/谐振行为。</li>
      <li>「+外部 .sNp」= 导入本机 Touchstone 文件与 run 产物叠加对比（WP0.3/E8，只读）；相位模式下叠加会清空以防量纲混淆。</li>
      <li>「Smith」= 各端口反射系数 S_ii 的 Smith 圆图（G9）：恒 r 圆/恒 x 弧为纯几何网格，悬停读频率与 Z=Z0(1+Γ)/(1−Γ)；|Γ|→1 时阻抗读数置 N/A。</li>
      <li>数据源 = run 产物 Touchstone；fake 通道无 Touchstone 时到「Run 详情」看 PNG 曲线。</li>`) +
    `<h2 class='page'>S 参数分析</h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b>
         <select id='sp-run' style='max-width:340px'></select>
         <button class='minor' id='sp-mode-db'>dB</button>
         <button class='minor' id='sp-mode-deg'>相位</button>
         <button class='minor' id='sp-mode-smith'>Smith</button>
         <button class='minor' id='sp-add-ext'>+外部 .sNp</button>
         <button class='minor' id='sp-clear-ext'>清除叠加</button>
         <span id='sp-info' class='muted'></span></div>
       <div id='sp-charts'></div>
     </div>`;
  let mode = S.spMode || "db";
  // W7-S35 走查 P2-1：run 下拉此前裸调 /api/runs——服务端缺省 limit=50
  // 只回最近 50 条，带 Touchstone 的较老 run 无法经下拉到达（绕道外部
  // 导入）。显式取大 limit（服务端无上限封顶；500 与全库规模同量级的
  // 安全值，dashboard/palette 的 200 同族口径）。
  const runs = (await T.api("/api/runs?limit=500")).runs || [];
  const sel = T.$("sp-run");
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.model || "?")} · ${esc(r.adapter || "?")}）</option>`).join("");
  // 同走查 P2-1 后半：深链 run 不在选项集时 sel.value 赋值静默失败回退
  // 首项——缺项先注入占位选项再赋值，选中态恢复恒可达。
  const hasOpt = (id) => Array.from(sel.options).some((o) => o.value === id);
  for (const want of [S.currentRunId, S.spRunId]) {
    if (want && !hasOpt(want)) {
      const o = document.createElement("option");
      o.value = want;
      o.textContent = `${want}（深链 run，不在最近清单内）`;
      sel.appendChild(o);
    }
  }
  if (S.currentRunId) sel.value = S.currentRunId;
  if (S.spRunId) sel.value = S.spRunId;

  async function load() {
    S.spRunId = sel.value;
    const box = T.$("sp-charts");
    T.$("sp-info").textContent = "";
    if (mode === "smith") {
      // Smith 圆图（G9）：run 各文件 S_ii 轨迹 + 外部叠加轨迹，一张图
      const d = await T.api(`/api/smith/${encodeURIComponent(sel.value)}`);
      const overlays = (S.spOverlay || []).filter((o) => o.mode === "smith");
      const traces = (d.ok ? d.traces || [] : []).map((t) => ({ ...t, label: `${t.file}·${t.name}` }));
      for (const o of overlays)
        for (const t of o.traces || []) traces.push({ ...t, label: `ext:${o.file}·${t.name}` });
      if (!traces.length) {
        box.innerHTML = `<span class='muted'>${d.ok ? "该 run 无 Touchstone 产物" + (d.warning ? "（" + esc(d.warning) + "）" : "") : esc((d.errors || []).join("; "))}——可用「+外部 .sNp」导入</span>`;
        return;
      }
      if (d.warning) T.$("sp-info").textContent = `部分文件解析失败: ${d.warning}`;
      box.innerHTML = `<div id='sp-smith'></div>`;
      const grid = d.ok ? d.grid : (overlays[0] && overlays[0].grid);
      drawSmith(T.$("sp-smith"), traces, grid, d.ok ? d.z0 : (overlays[0] && overlays[0].z0));
      return;
    }
    const d = await T.api(`/api/sparams/${encodeURIComponent(sel.value)}?mode=${mode}`);
    // 外部叠加（WP0.3/E8）：只保留与当前模式同量纲的叠加曲线
    const overlays = (S.spOverlay || []).filter((o) => o.mode === mode);
    const runCurves = d.ok ? (d.curves || []) : [];
    if (!d.ok && !overlays.length) {
      box.innerHTML = `<span class='muted'>${esc((d.errors || []).join("; "))}</span>`;
      return;
    }
    if (!runCurves.length && !overlays.length) {
      box.innerHTML = `<span class='muted'>该 run 无 Touchstone 产物${d.warning ? "（" + esc(d.warning) + "）" : ""}——fake 通道请到 Run 详情页看 PNG 曲线，或用「+外部 .sNp」直接导入文件</span>`;
      return;
    }
    if (d.warning) T.$("sp-info").textContent = `部分文件解析失败: ${d.warning}`;
    // 同文件同频网成组；多文件时各画一张图（文件名标注在标题）
    const groups = {};
    for (const c of runCurves) (groups[c.file] = groups[c.file] || []).push(c);
    const multi = Object.keys(groups).length > 1;
    let html = overlays.length
      ? `<b class='muted'>对比图（run 产物 + 外部叠加）</b><div id='sp-chart-overlay' style='margin-bottom:var(--space-3)'></div>`
      : "";
    html += Object.keys(groups).map((f) =>
      `<div style='margin-bottom:var(--space-3)'>${multi ? `<b class='muted'>${esc(f)}</b>` : ""}<div id='sp-chart-${f.replace(/\W/g, "")}'></div></div>`).join("");
    if (!runCurves.length && overlays.length)
      html = `<b class='muted'>外部叠加（该 run 无 Touchstone 产物）</b><div id='sp-chart-overlay' style='margin-bottom:var(--space-3)'></div>`;
    box.innerHTML = html;
    for (const [f, curves] of Object.entries(groups)) {
      const id = `sp-chart-${f.replace(/\W/g, "")}`;
      // PR-3 PlotCard 换壳 + crosshair（声明增量：axisPointer cross）
      T.plotCard(T.$(id), {
        series: curves.map((c) => ({
          name: c.name, x: c.freq_ghz, y: c.y,
        })),
        xlabel: "GHz", ylabel: mode === "db" ? "dB" : "相位（deg）",
        height: "340px", zoom: true,
        crosshair: true, exportName: "sparams-" + f.replace(/\W/g, "-"),
      });
    }
    if (overlays.length) {
      const series = [];
      for (const [f, curves] of Object.entries(groups))
        for (const c of curves) series.push({ name: `${f}·${c.name}`, x: c.freq_ghz, y: c.y });
      for (const o of overlays)
        for (const c of o.curves) series.push({ name: `ext:${o.file}·${c.name}`, x: c.freq_ghz, y: c.y });
      // PR-3 PlotCard 换壳 + crosshair（声明增量：axisPointer cross）
      T.plotCard(T.$("sp-chart-overlay"), {
        series,
        xlabel: "GHz", ylabel: mode === "db" ? "dB" : "相位（deg）",
        height: "360px", zoom: true,
        crosshair: true, exportName: "sparams-overlay",
      });
    }
  }
  T.$("sp-mode-db").onclick = () => { S.spMode = "db"; pageSparams(); };
  T.$("sp-mode-deg").onclick = () => { S.spMode = "deg"; pageSparams(); };
  T.$("sp-mode-smith").onclick = () => { S.spMode = "smith"; pageSparams(); };
  // UI-R4 a11y：三模式=互斥切换钮，aria-pressed 标注当前态（读屏可知；
  // 本页重入经 onclick→pageSparams() 重建后重同步）
  const syncModePressed = () => {
    for (const [id, m] of [["sp-mode-db", "db"], ["sp-mode-deg", "deg"], ["sp-mode-smith", "smith"]])
      T.$(id).setAttribute("aria-pressed", String(mode === m));
  };
  syncModePressed();
  T.$("sp-add-ext").onclick = () => fileBrowser("", async (p) => {
    const smith = mode === "smith";
    const r = await T.api(smith ? "/api/smith/external" : "/api/sparams/external", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(smith ? { path: p } : { path: p, mode }),
    });
    if (!r.ok) { T.msg((r.errors || ["导入失败"]).join("; "), false); return; }
    const rmode = smith ? "smith" : r.mode;
    S.spOverlay = S.spOverlay || [];
    if (S.spOverlay.some((o) => o.path === r.path && o.mode === rmode)) {
      T.msg("该文件已叠加", false);
      return;
    }
    S.spOverlay.push({ path: r.path, file: r.file, mode: rmode, curves: r.curves,
                       traces: r.traces, grid: r.grid, z0: r.z0 });
    T.msg("已叠加: " + r.file, true);
    load();
  });
  T.$("sp-clear-ext").onclick = () => { S.spOverlay = []; load(); };
  sel.onchange = load;
  _sparamsReload = load; // R-1：refresh 局部刷新转发登记（sparamsCtx 消费）
  await load();
}

/* ═══ R-1（aurora_e W3-S12）：PageContext 增量钩子 sparamsCtx ═══════════
   refresh=免全页重建直刷曲线——load() 闭包经模块级引用转发（campaignCtx
   同款模式）：只重拉当前 run 的曲线/Smith 数据并整换图区（壳/模式钮/run
   下拉不动，叠加清单与模式在 S 单源保持）。无轮询面，leave 不需要。 */
let _sparamsReload = null;
export const sparamsCtx = {
  refresh: () => { const f = _sparamsReload; if (f) f(); },
};
