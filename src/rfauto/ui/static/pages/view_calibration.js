/* rfauto 校准工作台页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   校准产物一览 + ρ 演化 + 详情（3.2 + 3.3 跨保真数据源同页）。
   i18n（发布前置软编码批 S1 全清）：壳/help 块分段 t()、表头/图系列名/
   空态/详情面板/aria 全迁词表（calibration.* 键域，zh 与旧字面逐字节同、
   en 新增）——拼接数据段（run_id/verdict/误差串）照旧 esc 后拼模板，词表
   值零 HTML；壳静态标签 data-i18n+applyI18nRoot 首扫；行 aria 标签走
   t() 前缀+数据拼接（kit escAttr 出口单点转义，runs.open_detail_aria
   同款先例）。run_id/ρ/mesh 等协议列名保留原文。

   aurora_n wave_ui_wizard：校准三步向导（P2 引导面）。#cal-wizard 新增
   引导层块（h2 后、产物面板前）——**既有表单/按钮/表格零改动**，向导
   只做三件事：①stepper 三步卡（组 B 快速开始四步卡 data-go 家法：
   guide-flow/guide-step clickable + kitClickRowAttrs 三件套 + bindClickRows
   click 与 Enter/Space 同一激活 → showPage 跳对应页）；②每步守卫行
   （role="status"，异步填充：/api/recipes 目录在档数 + /api/fs/list 只读
   探测 recipes/ 在盘配方数（journeyB recipeFileExists 家法）+ 本页已拉
   校准产物数（同步零新请求）；#105 best-effort——探测失败=unknown 放行
   文案，永不拦主路径）；③产物预告一行。面板头右侧 guide 锚形态
   （a[data-goto] 委托 + 文档绝对坐标直设 scrollTop，不写 location.hash
   ——hash 是两级路由信道）直跳下方产物清单。 */

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
// wave_ui_wizard：showPage=向导步卡跳页单源（dashboard wQuickLinks 同款）。
import { _syncRouteHash, consumeCalibrationPendingId, showPage } from "./router.js";

/* ═══ 校准工作台（阶段 3.2）+ 跨保真演化（3.3 数据源同页）═══ */
export async function pageCalibration() {
  const v = T.$("view-calibration");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("calibration.help_1")}</li>
      <li>${t("calibration.help_2")}</li>
      <li>${t("calibration.help_3")}</li>`) +
    `<h2 class='page' data-i18n='calibration.title'>${t("calibration.title")}</h2>
     <div class='panel' id='cal-wizard'><a class='muted' style='float:right;font-size:12px' href='#cal-table' data-goto='cal-table'><span aria-hidden='true'>↓</span> <span data-i18n='calibration.wiz_jump_table'>${t("calibration.wiz_jump_table")}</span></a>
       <b class='title' data-i18n='calibration.wiz_title'>${t("calibration.wiz_title")}</b>
       <div class='muted' style='font-size:12px;margin:var(--space-1) 0 var(--space-2)' data-i18n='calibration.wiz_lead'>${t("calibration.wiz_lead")}</div>
       <div class='guide-flow' id='cal-wiz-flow'>
         <div class='guide-step clickable' data-go='recipe' ${kitClickRowAttrs({ label: t("calibration.wiz_step_aria_tpl", { n: 1, name: t("calibration.wiz_s1_t") }) })}><span class='n'>1</span><b data-i18n='calibration.wiz_s1_t'>${t("calibration.wiz_s1_t")}</b><div data-i18n='calibration.wiz_s1_d'>${t("calibration.wiz_s1_d")}</div><div id='cal-wiz-g1' role='status' class='muted' style='margin-top:6px'></div><div style='font-size:12px' data-i18n='calibration.wiz_s1_out'>${t("calibration.wiz_s1_out")}</div></div>
         <div class='guide-step clickable' data-go='solvers' ${kitClickRowAttrs({ label: t("calibration.wiz_step_aria_tpl", { n: 2, name: t("calibration.wiz_s2_t") }) })}><span class='n'>2</span><b data-i18n='calibration.wiz_s2_t'>${t("calibration.wiz_s2_t")}</b><div data-i18n='calibration.wiz_s2_d'>${t("calibration.wiz_s2_d")}</div><div id='cal-wiz-g2' role='status' class='muted' style='margin-top:6px'></div><div style='font-size:12px' data-i18n='calibration.wiz_s2_out'>${t("calibration.wiz_s2_out")}</div></div>
         <div class='guide-step clickable' data-go='guide' ${kitClickRowAttrs({ label: t("calibration.wiz_step_aria_tpl", { n: 3, name: t("calibration.wiz_s3_t") }) })}><span class='n'>3</span><b data-i18n='calibration.wiz_s3_t'>${t("calibration.wiz_s3_t")}</b><div data-i18n='calibration.wiz_s3_d'>${t("calibration.wiz_s3_d")}</div><div id='cal-wiz-g3' role='status' class='muted' style='margin-top:6px'></div><div style='font-size:12px' data-i18n='calibration.wiz_s3_out'>${t("calibration.wiz_s3_out")}</div></div>
       </div></div>
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

  // aurora_n wave_ui_wizard：校准三步向导接线（引导层增量——步卡跳页 +
  // 锚跳转委托 + 守卫行填充；刷新幂等：bindClickRows 覆盖式重绑、锚委托
  // dataset 去重、守卫行重填）。list=本页已拉校准产物（步 3 守卫零新请求）。
  mountCalWizard(v, list);

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

/* ═══ aurora_n wave_ui_wizard：校准三步向导（引导层）══════════════════
   三件（全部纯串/纯探测，零顶层 DOM——node 行为钉可测）：
   ①countYamlEntries——在盘配方文件计数纯函数（kind!=="dir" 且 .yaml/.yml
     后缀，大小写不敏感；恶输入返 0 不炸）；
   ②probeRecipesCatalog/probeRecipesDir——只读探测（/api/recipes 目录
     在档数；/api/fs/list?path=recipes 在盘 .yaml 数——journeyB
     recipeFileExists 家法：同一只读探测面 + #105 best-effort，探测失败/
     超时/切页取消=unknown，守卫行永不拦主路径）；timeoutMs 5000 与
     tune.recipeFileExists 同款；viewSignal("calibration") 切页收束。
   ③wizGuardText——守卫行三态文本（ok/empty/unknown × 三步键域）；
   mountCalWizard——DOM 接线（步卡 bindClickRows 跳页 + a[data-goto]
   锚委托绝对坐标滚动 + 守卫行填充；幂等：重绑覆盖式、锚委托 dataset
   去重、守卫行重填）。 */
export function countYamlEntries(entries) {
  if (!Array.isArray(entries)) return 0;
  let n = 0;
  for (const e of entries) {
    if (!e || e.kind === "dir") continue;
    const nm = String(e.name || "").toLowerCase();
    if (nm.endsWith(".yaml") || nm.endsWith(".yml")) n++;
  }
  return n;
}

export async function probeRecipesCatalog() {
  try {
    const d = await apiFetch("/api/recipes",
      { signal: viewSignal("calibration"), timeoutMs: 5000 });
    if (d && d.aborted) return { state: "unknown", n: 0, aborted: true };
    const list = d && d.ok === true && Array.isArray(d.recipes) ? d.recipes : null;
    if (list == null) return { state: "unknown", n: 0 };
    return { state: list.length ? "ok" : "empty", n: list.length };
  } catch { return { state: "unknown", n: 0 }; }
}

export async function probeRecipesDir() {
  try {
    const d = await apiFetch("/api/fs/list?path=" + encodeURIComponent("recipes"),
      { signal: viewSignal("calibration"), timeoutMs: 5000 });
    if (d && d.aborted) return { state: "unknown", n: 0, aborted: true };
    if (!d || d.ok !== true || !Array.isArray(d.entries))
      return { state: "unknown", n: 0 };
    const n = countYamlEntries(d.entries);
    return { state: n ? "ok" : "empty", n };
  } catch { return { state: "unknown", n: 0 }; }
}

/* 守卫行三态文本（kind→整字面键域单源——i18n 悬空/死键双向棘轮只认
   整键字面量，动态拼键面会被 _t_refs 摘成假悬空；probe 缺席/畸形=
   unknown 中性）。 */
const _WIZ_GUARD_KEYS = {
  catalog: { ok: "calibration.wiz_g1_ok_tpl", empty: "calibration.wiz_g1_empty" },
  disk: { ok: "calibration.wiz_g2_ok_tpl", empty: "calibration.wiz_g2_empty" },
  runs: { ok: "calibration.wiz_g3_ok_tpl", empty: "calibration.wiz_g3_empty" },
};
export function wizGuardText(kind, probe) {
  const p = probe && probe.state ? probe : { state: "unknown", n: 0 };
  const keys = _WIZ_GUARD_KEYS[kind];
  if (!keys || p.state === "unknown") return t("calibration.wiz_g_unknown");
  return t(p.state === "ok" ? keys.ok : keys.empty,
    { n: p.n == null ? 0 : p.n });
}

function fillCalWizardGuards(runsList) {
  // 步 3 守卫零新请求：消费本页已拉清单（空=empty 如实，不 unknown）。
  const g3 = T.$("cal-wiz-g3");
  if (g3) g3.textContent = wizGuardText("runs",
    { state: runsList && runsList.length ? "ok" : "empty",
      n: runsList ? runsList.length : 0 });
  Promise.all([probeRecipesCatalog(), probeRecipesDir()])
    .then(([cat, dir]) => {
      if (cat.aborted || dir.aborted) return; // 切页取消——不写隐藏区
      const g1 = T.$("cal-wiz-g1");
      const g2 = T.$("cal-wiz-g2");
      if (g1) g1.textContent = wizGuardText("catalog", cat);
      if (g2) g2.textContent = wizGuardText("disk", dir);
    })
    .catch(() => { /* #105：守卫探测故障静默——行保持原状，不阻主路径 */ });
}

function mountCalWizard(v, runsList) {
  // 步卡跳页（组 B 家法：data-go + bindClickRows click/Enter/Space 同一激活）
  const flow = v.querySelector("#cal-wiz-flow");
  if (flow) bindClickRows(flow, (row) => showPage(row.dataset.go), "[data-go]");
  // 面板头锚（guide _bindToc 同款）：a[data-goto] 委托 + 文档绝对坐标直设
  // scrollTop（scrollIntoView smooth 不可靠先例）；不写 location.hash——
  // hash 是两级路由信道；dataset 去重防重渲叠加（容器跨渲染复用）。
  const wiz = T.$("cal-wizard");
  if (wiz && !wiz.dataset.wizBound) {
    wiz.dataset.wizBound = "1";
    wiz.addEventListener("click", (ev) => {
      const tgt = ev.target;
      const a = tgt && tgt.closest ? tgt.closest("a[data-goto]") : null;
      if (!a) return;
      const el = document.getElementById(a.getAttribute("data-goto"));
      if (!el) return;
      ev.preventDefault();
      const top = el.getBoundingClientRect().top +
        (window.scrollY || window.pageYOffset || 0) - 12; // 12px 顶部留白
      try { window.scrollTo({ top, left: 0, behavior: "instant" }); }
      catch { window.scrollTo(0, top); }
    });
  }
  fillCalWizardGuards(runsList);
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
