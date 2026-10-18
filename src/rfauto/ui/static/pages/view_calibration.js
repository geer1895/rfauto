/* rfauto 校准工作台页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   校准产物一览 + ρ 演化 + 详情（3.2 + 3.3 跨保真数据源同页）。 */

import { THEME_COLORS, bodyIsLight, themePick } from "../theme.js";
import { T } from "./context.js";
// UI-R12 任务2：统一 API 层（apiFetch + 视图作用域取消 signal）
import { apiFetch, viewSignal } from "./api.js";
import { esc, escAttr, help, mdReady, mdSanitize } from "./dom.js";
import { bindClickRows, kitClickRowAttrs, kitVerdictBadge } from "./kit.js";
import { makeSortable } from "./sortable.js";

/* ═══ 校准工作台（阶段 3.2）+ 跨保真演化（3.3 数据源同页）═══ */
export async function pageCalibration() {
  const v = T.$("view-calibration");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>校准产物一览：每次 calibrate/augment 的 gate 判定、LOOCV ρ、样本量与网格档。</li>
      <li>点击行看详情：参数空间散点（cost 着色）、验证点偏差、报告全文。</li>
      <li>演化图：ρ 随样本量的收敛轨迹 + 跨保真 gate 历史——校准数据是资产，逐次增广都会点亮一个点。</li>`) +
    `<h2 class='page'>校准工作台</h2>
     <div style='display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap'>
       <div class='panel' style='flex:1;min-width:340px'><div class='toolbar'><b>校准 run</b>
         <span id='cal-count' class='muted'></span></div>
         <table id='cal-table' data-sortable><caption class="sr-only">校准 run 清单：点行打开校准详情，点表头排序</caption><thead><tr><th scope="col">run_id</th><th scope="col">模型</th><th scope="col">判定</th><th scope="col">ρ</th><th scope="col">样本</th><th scope="col">mesh</th><th scope="col">代理</th></tr></thead><tbody></tbody></table></div>
       <div class='panel' style='flex:1;min-width:380px'><b>ρ 演化（样本量 ↔ 代理/跨保真 gate）</b>
         <div id='cal-evolution'></div>
         <div id='cal-gates' class='muted' style='margin-top:6px'></div></div>
     </div>
     <div id='cal-detail'></div>`;
  const [runs, evo] = await Promise.all([
    apiFetch("/api/calibration", { signal: viewSignal("calibration") }),
    apiFetch("/api/cross_fidelity", { signal: viewSignal("calibration") })]);
  if (runs.aborted || evo.aborted) return; // UI-R12：切页取消——不写隐藏区
  const list = runs.runs || [];
  T.$("cal-count").textContent = `${list.length} 个`;
  const tbody = T.$("cal-table").querySelector("tbody");
  tbody.innerHTML = list.map((r) => {
    const b = kitVerdictBadge(r.verdict); // A7-A ui-kit：PASS→ok，其余一律 FAIL/err 单源
    // UI-R4：键盘可达（tr 行 role:null 保 row/cell 语义；aria-label 行动作）
    return `<tr data-rid='${escAttr(r.run_id)}' ${kitClickRowAttrs({ role: null, label: "查看校准详情：" + (r.run_id || "") })} style='cursor:pointer'>
      <td class='muted'>${esc(r.run_id)}</td><td>${esc(r.model || "?")}</td><td>${b}</td>
      <td>${r.rho == null ? "-" : (+r.rho).toFixed(3)}</td>
      <td>${esc(r.n_samples ?? "-")}</td>
      <td>${esc(r.mesh_resolution_mm == null ? "-" : r.mesh_resolution_mm)}</td>
      <td class='muted'>${esc(r.surrogate_kind || "-")}</td></tr>`;
  }).join("");
  for (const tr of tbody.querySelectorAll("tr")) {
    tr.title = tr.dataset.rid || ""; // W7-C：run_id 列截断后悬停见全名
  }
  // UI-R4：click 与 Enter/Space 同一激活（bindClickRows 单源）
  bindClickRows(tbody, (tr) => loadCalibration(tr.dataset.rid), "tr[data-rid]");
  // aurora36 W3-B（P1-7）：校准表可排序（ρ/样本列数值序最有用）；重进页
  // tbody 重建后重放当前排序保持列头状态一致
  const scal = makeSortable(T.$("cal-table"));
  if (scal) scal.refresh();

  const sur = (evo.surrogate_evolution || []).filter((e) => e.rho != null);
  const cro = (evo.cross_evolution || []).filter((e) => e.rho != null);
  // PR-1 对比度：显式系列色按主题分档（浅色档白底 ≥3:1，深色档不变）
  const light = bodyIsLight();
  // PR-3 PlotCard 换壳：option 与迁移前等价（base 路径，scatter+xvalue+markline）
  T.plotCard(T.$("cal-evolution"), {
    series: [
      { name: "代理 LOOCV ρ", type: "scatter", color: themePick(light, THEME_COLORS.seriesTeal),
        data: sur.map((e) => [e.n_samples, +e.rho]) },
      { name: "跨保真 gate ρ", type: "scatter", color: themePick(light, THEME_COLORS.seriesBlue),
        data: cro.map((e) => [e.n_evaluated, +e.rho]) },
    ],
    xvalue: true, xlabel: "样本量", ylabel: "ρ", zoom: false, height: "300px",
    markline: [{ yAxis: 0.8 }], exportName: "cal-evolution", exportCsv: false,
  });
  T.$("cal-gates").textContent = cro.length
    ? cro.map((e) => `${e.run_id}: ρ=${e.rho == null ? "-" : (+e.rho).toFixed(3)} ${e.verdict || ""}`).join(" · ")
    : "暂无跨保真 gate 记录";
}

async function loadCalibration(runId) {
  const d = await apiFetch("/api/calibration/" + encodeURIComponent(runId),
    { signal: viewSignal("calibration") });
  if (d.aborted) return; // UI-R12：切页取消——不写隐藏区
  const v = T.$("cal-detail");
  if (!d.ok) { v.innerHTML = `<div class='panel'>${esc((d.errors || []).join("; "))}</div>`; return; }
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
    name: "样本点", type: "scatter", symbolSize: 12,
    color: themePick(bodyIsLight(), THEME_COLORS.seriesBlue),
    data: d.points.map((p) => ({
      value: [p[xy[0]], xy[1] ? p[xy[1]] : p.cost],
      itemStyle: { color: costColor(p.cost) },
    })),
  };
  const valRows = (d.validation || []).map((val) => {
    if (val.error) return `<tr><td colspan='2' class='muted'>验证点失败: ${esc(val.error)}</td></tr>`;
    const deltas = Object.entries(val.abs_delta || {})
      .map(([k, x]) => `${esc(k)}=${(+x).toFixed(3)}`).join(" · ");
    return `<tr><td class='muted'>${esc(Object.values(val.params).map((x) => (+x).toFixed(2)).join(", "))}</td>
      <td>${esc(deltas)}</td></tr>`;
  }).join("");
  const report = d.report_md
    ? (window.marked && mdReady() ? mdSanitize(window.marked.parse(d.report_md))
      : `<pre>${esc(d.report_md)}</pre>`)
    : "<span class='muted'>无报告</span>";
  v.innerHTML = `
    <div class='panel'>
      <div class='toolbar'><b>校准详情 ${escAttr(runId)}</b>
        ${kitVerdictBadge(g.verdict)}
        <span class='muted'>ρ=${loocv.rho == null ? "-" : (+loocv.rho).toFixed(3)} ·
          样本 ${d.points.length}${d.seed_sample_count ? `（种子 ${d.seed_sample_count}）` : ""} ·
          mesh ${d.mesh_resolution_mm == null ? "-" : d.mesh_resolution_mm}mm</span></div>
      <div style='display:flex;gap:14px;flex-wrap:wrap'>
        <div style='flex:1;min-width:360px'><b>参数空间（${esc(xy[0])}${xy[1] ? " × " + esc(xy[1]) : ""}，颜色=cost 好→差）</b>
          <div id='cal-scatter'></div></div>
        <div style='flex:1;min-width:320px'><b>验证点偏差（预测 vs 实际）</b>
          <table><thead><tr><th scope="col">参数</th><th scope="col">|Δ| 指标</th></tr></thead><tbody>${valRows || "<tr><td class=muted>无</td></tr>"}</tbody></table></div>
      </div>
      <details><summary class='muted'>校准报告全文</summary><div class='muted'>${report}</div></details>
    </div>`;
  // PR-3 PlotCard 换壳：option 与迁移前等价（scatter+xvalue）
  T.plotCard(T.$("cal-scatter"), {
    series: [scatter],
    xvalue: true, xlabel: xy[0],
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
