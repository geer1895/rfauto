/* rfauto 优化洞察页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   Pareto 前沿 + 可行性热图（E9/E10，数据解释全在 service，前端只渲染）。
   i18n（发布前软编码批 S2 全清）：壳/help 块分段 t()、画布文字/悬停 title/
   aria/状态行/空态全迁词表（optstack.* 键域，zh 与旧字面逐字节同、en 新增）
   ——拼接数据段（参数名/来源/目标名）照旧 esc 外拼或 textContent 直写，
   词表值零 HTML；API 字符串数据不进 t() params（t() 头注契约，数字/格式化
   数值与 t() 产出可作 params——agent stats 前例）。 */

import {
  CANVAS_FONT, CANVAS_FONT_SMALL, CANVAS_HEAT_LAYOUT, THEME_COLORS, bodyIsLight, themePick,
} from "../theme.js";
import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
// i18n（发布前软编码批 S2）：壳静态标签 data-i18n+首扫；动态容器文案 t()
// 渲染期烘焙（canvas fillText/aria/title 同为绘制期定格当前档）。
import { t, applyI18nRoot } from "./i18n.js";
// P8-9（aurora_f W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 3 点）——
// 数据面全页（run 清单/Pareto 前沿/可行性热图）接 viewSignal("optstack") 切页
// 收束 + aborted 短路（在途拉取不再写隐藏区）。信封消费形态逐键不变。
import { apiFetch, viewSignal } from "./api.js";

/* 优化 run 选中记忆（W6-S2 S 状态收编：原 S.osRunId 单模块私有键降级
   模块级——属主=本模块，契约表见 context.js；会话级记忆语义不变）。 */
let _osRunId = null;

/* ═══ 优化洞察（E9 Pareto 前沿 / E10 可行性热图）═══
   数据解释全在 service（ui_service.pareto_view / feasibility_heatmap）；
   前端只渲染：前沿散点（echarts）+ 可行率网格（canvas，复用场页热图的
   单元格按真实坐标绘制画法，无新前端依赖）。 */
function drawFeasibilityGrid(el, d) {
  el.innerHTML = "";
  const light = bodyIsLight();
  const fg = themePick(light, THEME_COLORS.fg);
  const canvas = document.createElement("canvas");
  canvas.style.width = "100%"; canvas.style.height = "340px";
  el.appendChild(canvas);
  const info = document.createElement("div");
  info.className = "muted"; info.style.marginTop = "6px";
  el.appendChild(info);
  const W = canvas.width = canvas.clientWidth || 700, H = canvas.height = 340;
  // W3-S12（P-5）：边距常量收 theme.js 单源（值冻结 60/90/12/40，渲染不变）
  const { left: L, right: R, top: Tp, bottom: B } = CANVAS_HEAT_LAYOUT;
  const ctx = canvas.getContext("2d");
  const xe = d.x_edges, ye = d.y_edges, n = d.grid_n;
  const xmin = xe[0], xmax = xe[xe.length - 1], ymin = ye[0], ymax = ye[ye.length - 1];
  const px = (x) => L + ((x - xmin) / (xmax - xmin || 1)) * (W - L - R);
  const py = (y) => H - B - ((y - ymin) / (ymax - ymin || 1)) * (H - Tp - B);
  // 可行率色标：红（0）→ 黄（0.5）→ 绿（1）；空格灰
  const color = (r) => {
    if (r === null || r === undefined) return themePick(light, THEME_COLORS.emptyCell);
    const g = Math.round(r <= 0.5 ? 80 + 300 * r : 230), rr = Math.round(r <= 0.5 ? 235 : 235 - 350 * (r - 0.5));
    return `rgb(${Math.max(0, Math.min(235, rr))},${Math.max(0, Math.min(230, g))},70)`;
  };
  const byCell = {};
  for (const c of d.cells) byCell[`${c.i},${c.j}`] = c;
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++) {
      const c = byCell[`${i},${j}`];
      ctx.fillStyle = color(c ? c.feasible_rate : null);
      const x0 = px(xe[i]), x1 = px(xe[i + 1]), y0 = py(ye[j + 1]), y1 = py(ye[j]);
      ctx.fillRect(x0, y0, Math.max(1, x1 - x0 - 0.5), Math.max(1, y1 - y0 - 0.5));
      if (c) {
        ctx.fillStyle = fg; ctx.font = CANVAS_FONT_SMALL; ctx.textAlign = "center";
        ctx.fillText(String(c.n), (x0 + x1) / 2, (y0 + y1) / 2 + 3);
      }
    }
  // 轴与色标
  ctx.fillStyle = fg; ctx.font = CANVAS_FONT; ctx.textAlign = "center";
  ctx.fillText(`${d.x_param}  [${xmin.toPrecision(4)} … ${xmax.toPrecision(4)}]`, (L + W - R) / 2, H - 10);
  ctx.save(); ctx.translate(14, (Tp + H - B) / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText(`${d.y_param}  [${ymin.toPrecision(4)} … ${ymax.toPrecision(4)}]`, 0, 0); ctx.restore();
  const cx = W - R + 20, ch = H - Tp - B;
  for (let k = 0; k < ch; k++) {
    ctx.fillStyle = color(1 - k / ch);
    ctx.fillRect(cx, Tp + k, 14, 1);
  }
  ctx.fillStyle = fg; ctx.textAlign = "left";
  ctx.fillText(t("optstack.legend_feas_1"), cx + 18, Tp + 10);
  ctx.fillText("0", cx + 18, Tp + ch);
  // UI-R4 a11y：canvas 图像语义（PR-1 图表容器口径补齐本自研管线——
  // 参数名经 String 拼接，XSS 反向扫描口径零新增）
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", t("optstack.heat_aria_lead") + d.x_param + " × " + d.y_param +
    t("optstack.heat_aria_tail"));
  info.textContent = t("optstack.heat_info_a_tpl",
    { used: d.n_trials_used, total: d.n_trials_total, feas: d.n_feasible_total }) +
    t("optstack.heat_info_b_tpl", { cells: d.cells.length, total: n * n });
  canvas.onmousemove = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const mx = (ev.clientX - rect.left) * (W / rect.width), my = (ev.clientY - rect.top) * (H / rect.height);
    const xv = xmin + ((mx - L) / (W - L - R)) * (xmax - xmin);
    const yv = ymin + ((H - B - my) / (H - Tp - B)) * (ymax - ymin);
    const i = Math.min(n - 1, Math.max(0, Math.floor(((xv - xmin) / (xmax - xmin || 1)) * n)));
    const j = Math.min(n - 1, Math.max(0, Math.floor(((yv - ymin) / (ymax - ymin || 1)) * n)));
    const c = byCell[`${i},${j}`];
    canvas.title = c
      ? `${d.x_param}∈[${xe[i].toPrecision(4)},${xe[i + 1].toPrecision(4)}] ${d.y_param}∈[${ye[j].toPrecision(4)},${ye[j + 1].toPrecision(4)}]\n` +
        t("optstack.hover_cell_tpl", { n: c.n, feas: c.n_feasible,
          rate: (c.feasible_rate * 100).toFixed(0), viol: c.mean_total_violation.toFixed(4) })
      : t("optstack.hover_empty");
  };
}

export async function pageOptStack() {
  const v = T.$("view-optstack");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("optstack.help_1")}</li>
      <li>${t("optstack.help_2")}</li>
      <li>${t("optstack.help_3")}</li>`) +
    `<h2 class='page'><span data-i18n='optstack.title'>${t("optstack.title")}</span><small data-i18n='optstack.subtitle'>${t("optstack.subtitle")}</small></h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b>
         <select id='os-run' style='max-width:340px'></select>
         <button class='minor' id='os-reload' data-i18n='optstack.reload'>${t("optstack.reload")}</button>
         <span id='os-src' class='muted'></span></div>
       <div id='os-pareto'></div>
       <div id='os-hv' class='muted' style='margin-top:6px'></div>
     </div>
     <div class='panel'>
       <div class='toolbar'><b data-i18n='optstack.x_param'>${t("optstack.x_param")}</b><select id='os-x' style='max-width:200px'></select>
         <b data-i18n='optstack.y_param'>${t("optstack.y_param")}</b><select id='os-y' style='max-width:200px'></select>
         <b data-i18n='optstack.grid'>${t("optstack.grid")}</b><input id='os-n' value='12' style='width:56px'>
         <button class='minor' id='os-heat-btn' data-i18n='optstack.heat_btn'>${t("optstack.heat_btn")}</button>
         <span id='os-info' class='muted'></span></div>
       <div id='os-heat'></div>
     </div>`;
  applyI18nRoot(v); // 壳静态标签首扫（幂等，动态容器走 t() 烘焙）
  const listing = await apiFetch("/api/pareto_runs",
    { signal: viewSignal("optstack") });
  if (listing.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const runs = listing.runs || [];
  const sel = T.$("os-run");
  if (!runs.length) {
    sel.innerHTML = "<option>" + t("optstack.no_runs") + "</option>";
    T.$("os-src").textContent = t("optstack.src_hint");
    return;
  }
  // 分组下拉（项 3）：优化 run 排前，单点仿真 run 标注排后（仍可选，选中给人话空态）
  const tierLabel = { front: t("optstack.tier_front"),
                      trials: t("optstack.tier_trials"),
                      single: t("optstack.tier_single") };
  const tierClass = { front: "", trials: "", single: "muted" };
  const byTier = { front: [], trials: [], single: [] };
  for (const r of runs) (byTier[r.tier] = byTier[r.tier] || []).push(r);
  // 归参 tier（原 t）：t() 词表函数入域后循环变量不得再遮蔽（#116 家族）
  sel.innerHTML = ["front", "trials", "single"]
    .filter((tier) => byTier[tier].length)
    .map((tier) => `<optgroup label='${escAttr(tierLabel[tier])}'>` + byTier[tier].map((r) =>
      `<option value='${escAttr(r.run_id)}' class='${tierClass[tier]}'>${esc(r.run_id)}（${esc(r.model || r.adapter || "?")}${tier === "trials" ? " · " + esc(r.n_trials) + " trials" : ""}${tier === "single" ? t("optstack.single_suffix") : ""}）</option>`).join("") + "</optgroup>")
    .join("");
  if (_osRunId && runs.some((r) => r.run_id === _osRunId)) sel.value = _osRunId;

  const fillParams = (names) => {
    const opts = names.map((n) => `<option value='${escAttr(n)}'>${esc(n)}</option>`).join("")
      || "<option value=''>" + t("optstack.no_run_selected") + "</option>";
    T.$("os-x").innerHTML = opts; T.$("os-y").innerHTML = opts;
    if (names.length > 1) T.$("os-y").value = names[1];
  };

  async function loadPareto() {
    _osRunId = sel.value;
    const d = await apiFetch(`/api/runs/${encodeURIComponent(sel.value)}/pareto`,
      { signal: viewSignal("optstack") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const el = T.$("os-pareto"), hv = T.$("os-hv");
    hv.textContent = "";
    if (!d.ok) {
      // 人话空态（项 3）：单点仿真 run 没有优化轨迹是预期，不是故障
      const meta = runs.find((r) => r.run_id === sel.value) || {};
      const human = meta.tier === "single"
        ? t("optstack.empty_single")
        : t("optstack.empty_no_front");
      el.innerHTML = `<div class='muted'>${human}<br><small>${esc((d.errors || []).join("; "))}</small></div>`;
      T.$("os-src").textContent = "";
      fillParams([]);
      return;
    }
    fillParams(d.param_names || []);
    const names = d.objective_names || [];
    const pts = d.points || [];
    T.$("os-src").textContent = t("optstack.src_lead") + d.source + " · " +
      t("optstack.src_points_tpl", { n: d.n_pareto }) +
      (d.constraint_names && d.constraint_names.length
        ? t("optstack.constraints_lead") + d.constraint_names.join(",") : "");
    if (!pts.length || names.length < 2) {
      el.innerHTML = "<div class='muted'>" + t("optstack.front_empty") + "</div>";
      return;
    }
    const feas = pts.filter((p) => p.feasible !== false);
    const infeas = pts.filter((p) => p.feasible === false);
    const toXY = (p) => [+p.objectives[names[0]], +p.objectives[names[1]]];
    const series = [{ name: infeas.length ? t("optstack.series_front_feas") : t("optstack.series_front"),
                      type: "scatter",
                      data: feas.map(toXY),
                      color: themePick(bodyIsLight(), THEME_COLORS.seriesTeal),
                      symbolSize: 11 }];
    if (infeas.length)
      series.push({ name: t("optstack.series_infeasible"), type: "scatter", data: infeas.map(toXY),
        color: themePick(bodyIsLight(), THEME_COLORS.seriesRed), symbolSize: 9 });
    // PR-3 PlotCard 换壳：option 与迁移前等价（scatter+xvalue，zoom off）
    T.plotCard(el, {
      series,
      xvalue: true, xlabel: names[0] + t("optstack.violation_axis_suffix"),
      ylabel: names[1] + t("optstack.violation_axis_suffix"),
      height: "300px", zoom: false,
      exportName: "pareto-front", exportCsv: false,
    });
    if (names.length > 2)
      hv.textContent = t("optstack.hv_dims_lead", { n: names.length }) +
        names.slice(2).join(", ") + t("optstack.hv_dims_tail");
    if (d.hv_convergence && d.hv_convergence.length) {
      const h = d.hv_convergence;
      const mono = h.every((x, i) => i === 0 || x >= h[i - 1] - 1e-12);
      hv.textContent += t("optstack.hv_conv_tpl",
        { n: h.length, a: h[0].toFixed(4), b: h[h.length - 1].toFixed(4) }) +
        t("optstack.hv_archive_tpl",
          { v: mono ? t("optstack.hv_mono_ok") : t("optstack.hv_mono_bad") });
    }
  }

  async function loadHeat() {
    const x = T.$("os-x").value, y = T.$("os-y").value;
    const q = new URLSearchParams({ x_param: x, y_param: y, grid_n: T.$("os-n").value || "12" });
    const d = await apiFetch(`/api/runs/${encodeURIComponent(sel.value)}/feasibility?${q}`,
      { signal: viewSignal("optstack") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const info = T.$("os-info"), el = T.$("os-heat");
    if (!d.ok) { info.textContent = (d.errors || []).join("; "); el.innerHTML = ""; return; }
    info.textContent = "";
    drawFeasibilityGrid(el, d);
  }
  sel.onchange = () => { loadPareto(); T.$("os-heat").innerHTML = ""; T.$("os-info").textContent = ""; };
  T.$("os-reload").onclick = loadPareto;
  T.$("os-heat-btn").onclick = loadHeat;
  await loadPareto();
}

/* ═══ R-1（aurora_e W3-S12）：PageContext 增量钩子 optstackCtx ══════════
   refresh=图表数据重拉（pageOptStack 幂等：壳判 innerHTML 已在即跳过，
   pareto_runs 清单与当前 run 的前沿图重拉重渲——plotCard 壳 setOption
   复用零重建；可行性热图按需点钮重算不随刷新）。无轮询面，leave 不需要。 */
export const optstackCtx = {
  refresh: () => pageOptStack(),
};
