/* rfauto 校准工作台页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   校准产物一览 + ρ 演化 + 详情（3.2 + 3.3 跨保真数据源同页）。
   i18n（发布前置软编码批 S1 全清）：壳/help 块分段 t()、表头/图系列名/
   空态/详情面板/aria 全迁词表（calibration.* 键域，zh 与旧字面逐字节同、
   en 新增）——拼接数据段（run_id/verdict/误差串）照旧 esc 后拼模板，词表
   值零 HTML；壳静态标签 data-i18n+applyI18nRoot 首扫；行 aria 标签走
   t() 前缀+数据拼接（kit escAttr 出口单点转义，runs.open_detail_aria
   同款先例）。run_id/ρ/mesh 等协议列名保留原文。 */

import { THEME_COLORS, bodyIsLight, themePick } from "../theme.js";
import { T } from "./context.js";
// UI-R12 任务2：统一 API 层（apiFetch + 视图作用域取消 signal）
import { apiFetch, viewSignal } from "./api.js";
import { esc, escAttr, help, mdReady, mdSanitize } from "./dom.js";
// i18n（S1 全清）：壳静态标签 data-i18n+首扫；动态容器文案 t() 渲染期烘焙。
import { t, applyI18nRoot } from "./i18n.js";
// 三态收敛（aurora_f W2-S5，R1 #8 批1）：空态=kitEmptyState、错误=kitErrorPanel
import { bindClickRows, kitClickRowAttrs, kitEmptyState, kitErrorPanel, kitVerdictBadge } from "./kit.js";
import { makeSortable } from "./sortable.js";
// 深链二批（aurora_f W2-S5）：#/calibration/<run_id> 待选消费 + 详情 hash 回写
import { _syncRouteHash, consumeCalibrationPendingId } from "./router.js";

/* ═══ 校准工作台（阶段 3.2）+ 跨保真演化（3.3 数据源同页）═══ */
export async function pageCalibration() {
  const v = T.$("view-calibration");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("calibration.help_1")}</li>
      <li>${t("calibration.help_2")}</li>
      <li>${t("calibration.help_3")}</li>`) +
    `<h2 class='page' data-i18n='calibration.title'>${t("calibration.title")}</h2>
     <div style='display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap'>
       <div class='panel' style='flex:1;min-width:340px'><div class='toolbar'><b>${t("calibration.run_label")}</b>
         <span id='cal-count' class='muted'></span></div>
         <table id='cal-table' data-sortable><caption class="sr-only">${t("calibration.caption")}</caption><thead><tr><th scope="col">run_id</th><th scope="col">${t("calibration.th_model")}</th><th scope="col">${t("calibration.th_verdict")}</th><th scope="col">ρ</th><th scope="col">${t("calibration.th_samples")}</th><th scope="col">mesh</th><th scope="col">${t("calibration.th_surrogate")}</th></tr></thead><tbody></tbody></table></div>
       <div class='panel' style='flex:1;min-width:380px'><b>${t("calibration.evo_title")}</b>
         <div id='cal-evolution'></div>
         <div id='cal-gates' class='muted' style='margin-top:6px'></div></div>
     </div>
     <div id='cal-detail'></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（S1 全清；幂等，动态容器走 t() 烘焙）
  const [runs, evo] = await Promise.all([
    apiFetch("/api/calibration", { signal: viewSignal("calibration") }),
    apiFetch("/api/cross_fidelity", { signal: viewSignal("calibration") })]);
  if (runs.aborted || evo.aborted) return; // UI-R12：切页取消——不写隐藏区
  const list = runs.runs || [];
  T.$("cal-count").textContent = list.length + t("calibration.count_unit");
  const tbody = T.$("cal-table").querySelector("tbody");
  // 三态收敛（aurora_f W2-S5，R1 #8 批1）：空清单=kitEmptyState 整行三件式
  // （原静默空 tbody；colspan 对齐 7 列表头）
  tbody.innerHTML = list.length
    ? list.map((r) => {
      const b = kitVerdictBadge(r.verdict); // A7-A ui-kit：PASS→ok，其余一律 FAIL/err 单源
      // UI-R4：键盘可达（tr 行 role:null 保 row/cell 语义；aria-label 行动作）
      return `<tr data-rid='${escAttr(r.run_id)}' ${kitClickRowAttrs({ role: null, label: t("calibration.open_detail_aria") + (r.run_id || "") })} style='cursor:pointer'>
      <td class='muted'>${esc(r.run_id)}</td><td>${esc(r.model || "?")}</td><td>${b}</td>
      <td>${r.rho == null ? "-" : (+r.rho).toFixed(3)}</td>
      <td>${esc(r.n_samples ?? "-")}</td>
      <td>${esc(r.mesh_resolution_mm == null ? "-" : r.mesh_resolution_mm)}</td>
      <td class='muted'>${esc(r.surrogate_kind || "-")}</td></tr>`;
    }).join("")
    : `<tr><td colspan="7">${kitEmptyState(t("calibration.empty"))}</td></tr>`;
  for (const tr of tbody.querySelectorAll("tr")) {
    tr.title = tr.dataset.rid || ""; // W7-C：run_id 列截断后悬停见全名
  }
  // UI-R4：click 与 Enter/Space 同一激活（bindClickRows 单源）
  bindClickRows(tbody, (tr) => loadCalibration(tr.dataset.rid), "tr[data-rid]");
  // aurora36 W3-B（P1-7）：校准表可排序（ρ/样本列数值序最有用）；重进页
  // tbody 重建后重放当前排序保持列头状态一致
  const scal = makeSortable(T.$("cal-table"));
  if (scal) scal.refresh();

  // 深链二批（aurora_f W2-S5）：#/calibration/<run_id> 待选消费——清单命中
  // 才打开详情，未命中回落表头（campaign 深链同款待选纪律）；消费即清
  // （router.js 单源写）；hash 回写在 loadCalibration 落地点（点行同一口径）。
  const pendingCal = consumeCalibrationPendingId();
  if (pendingCal && list.some((r) => r.run_id === pendingCal))
    loadCalibration(pendingCal);

  const sur = (evo.surrogate_evolution || []).filter((e) => e.rho != null);
  const cro = (evo.cross_evolution || []).filter((e) => e.rho != null);
  // PR-1 对比度：显式系列色按主题分档（浅色档白底 ≥3:1，深色档不变）
  const light = bodyIsLight();
  // PR-3 PlotCard 换壳：option 与迁移前等价（base 路径，scatter+xvalue+markline）
  // W3-S9：数值读数类开十字线（xvalue 值轴 trigger=item，ρ 散点读数面）
  T.plotCard(T.$("cal-evolution"), {
    series: [
      { name: t("calibration.series_sur"), type: "scatter", color: themePick(light, THEME_COLORS.seriesTeal),
        data: sur.map((e) => [e.n_samples, +e.rho]) },
      { name: t("calibration.series_cross"), type: "scatter", color: themePick(light, THEME_COLORS.seriesBlue),
        data: cro.map((e) => [e.n_evaluated, +e.rho]) },
    ],
    xvalue: true, crosshair: true, xlabel: t("calibration.xlabel"), ylabel: "ρ", zoom: false, height: "300px",
    markline: [{ yAxis: 0.8 }], exportName: "cal-evolution", exportCsv: false,
  });
  T.$("cal-gates").textContent = cro.length
    ? cro.map((e) => `${e.run_id}: ρ=${e.rho == null ? "-" : (+e.rho).toFixed(3)} ${e.verdict || ""}`).join(" · ")
    : t("calibration.no_cross");
}

async function loadCalibration(runId) {
  // 深链二批（aurora_f W2-S5）：点行/深链打开同一 hash 口径（replaceState
  // 不产历史条目不触 hashchange；刷新/分享保持所选校准详情）
  _syncRouteHash("calibration", runId);
  const d = await apiFetch("/api/calibration/" + encodeURIComponent(runId),
    { signal: viewSignal("calibration") });
  if (d.aborted) return; // UI-R12：切页取消——不写隐藏区
  const v = T.$("cal-detail");
  if (!d.ok) {
    // 三态收敛（aurora_f W2-S5，R1 #8 批1 形态⑤原点）：内联 muted 面板 →
    // kitErrorPanel 带重试（重开同一校准详情）
    v.innerHTML = `<div class='panel'>` +
      kitErrorPanel((d.errors || []).join("; "), "cal-retry") + `</div>`;
    const rb = T.$("cal-retry");
    if (rb) rb.onclick = () => loadCalibration(runId);
    return;
  }
  const g = d.gate || {};
  const loocv = g.loocv || {};
  const keys = Object.keys(d.bounds || {}).sort();
  const costColor = (c) => {
    if (c == null) return themePick(bodyIsLight(), THEME_COLORS.calibNullCost); // UI-R12 任务3：单源收编（原内联 #8391a7 冻结迁移）
    const cs = d.points.map((p) => p.cost).filter((x) => x != null);
    const lo = Math.min(...cs), hi = Math.max(...cs);
    const t = hi > lo ? (c - lo) / (hi - lo) : 0;
    return `rgb(${Math.round(40 + 200 * t)},${Math.round(190 - 130 * t)},${Math.round(120 - 60 * t)})`;
  };
  const xy = keys.length >= 2 ? keys.slice(0, 2) : [keys[0], null];
  const scatter = {
    name: t("calibration.series_points"), type: "scatter", symbolSize: 12,
    color: themePick(bodyIsLight(), THEME_COLORS.seriesBlue),
    data: d.points.map((p) => ({
      value: [p[xy[0]], xy[1] ? p[xy[1]] : p.cost],
      itemStyle: { color: costColor(p.cost) },
    })),
  };
  const valRows = (d.validation || []).map((val) => {
    if (val.error) return `<tr><td colspan='2' class='muted'>${t("calibration.val_fail")}${esc(val.error)}</td></tr>`;
    const deltas = Object.entries(val.abs_delta || {})
      .map(([k, x]) => `${esc(k)}=${(+x).toFixed(3)}`).join(" · ");
    return `<tr><td class='muted'>${esc(Object.values(val.params).map((x) => (+x).toFixed(2)).join(", "))}</td>
      <td>${esc(deltas)}</td></tr>`;
  }).join("");
  const report = d.report_md
    ? (window.marked && mdReady() ? mdSanitize(window.marked.parse(d.report_md))
      : `<pre>${esc(d.report_md)}</pre>`)
    : `<span class='muted'>${t("calibration.no_report")}</span>`;
  v.innerHTML = `
    <div class='panel'>
      <div class='toolbar'><b>${t("calibration.detail_title")} ${escAttr(runId)}</b>
        ${kitVerdictBadge(g.verdict)}
        <span class='muted'>ρ=${loocv.rho == null ? "-" : (+loocv.rho).toFixed(3)} ·
          ${t("calibration.sum_samples")}${d.points.length}${d.seed_sample_count ? t("calibration.sum_seed_pre") + d.seed_sample_count + t("calibration.sum_seed_suf") : ""} ·
          mesh ${d.mesh_resolution_mm == null ? "-" : d.mesh_resolution_mm}mm</span></div>
      <div style='display:flex;gap:14px;flex-wrap:wrap'>
        <div style='flex:1;min-width:360px'><b>${t("calibration.param_space")}${esc(xy[0])}${xy[1] ? " × " + esc(xy[1]) : ""}${t("calibration.param_space_tail")}</b>
          <div id='cal-scatter'></div></div>
        <div style='flex:1;min-width:320px'><b>${t("calibration.val_title")}</b>
          <table><thead><tr><th scope="col">${t("calibration.th_param")}</th><th scope="col">${t("calibration.th_delta")}</th></tr></thead><tbody>${valRows || `<tr><td class=muted>${t("calibration.none")}</td></tr>`}</tbody></table></div>
      </div>
      <details><summary class='muted'>${t("calibration.report_summary")}</summary><div class='muted'>${report}</div></details>
    </div>`;
  // PR-3 PlotCard 换壳：option 与迁移前等价（scatter+xvalue）
  // W3-S9：数值读数类开十字线（xvalue 值轴 trigger=item，参数空间散点读数面）
  T.plotCard(T.$("cal-scatter"), {
    series: [scatter],
    xvalue: true, crosshair: true, xlabel: xy[0],
    ylabel: xy[1] || "cost", zoom: false, height: "320px",
    exportName: "cal-scatter", exportCsv: false,
  });
}

/* ═══ R-1（aurora_e W3-S12）：PageContext 增量钩子 calibrationCtx ═══════
   refresh=表数据重拉（runs 同模板——pageCalibration 幂等：壳判 innerHTML
   已在即跳过、清单/ρ 演化图重渲染，行点击详情区不整清）；apiFetch 带
   viewSignal("calibration") 切页取消语义随行。无轮询面，leave 不需要。 */
export const calibrationCtx = {
  refresh: () => pageCalibration(),
};
