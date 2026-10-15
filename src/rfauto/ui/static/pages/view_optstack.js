/* rfauto 优化洞察页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   Pareto 前沿 + 可行性热图（E9/E10，数据解释全在 service，前端只渲染）。 */

import { THEME_COLORS, bodyIsLight, themePick } from "../theme.js";
import { S, T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";

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
  const L = 60, R = 90, Tp = 12, B = 40;
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
        ctx.fillStyle = fg; ctx.font = "10px sans-serif"; ctx.textAlign = "center";
        ctx.fillText(String(c.n), (x0 + x1) / 2, (y0 + y1) / 2 + 3);
      }
    }
  // 轴与色标
  ctx.fillStyle = fg; ctx.font = "11px sans-serif"; ctx.textAlign = "center";
  ctx.fillText(`${d.x_param}  [${xmin.toPrecision(4)} … ${xmax.toPrecision(4)}]`, (L + W - R) / 2, H - 10);
  ctx.save(); ctx.translate(14, (Tp + H - B) / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText(`${d.y_param}  [${ymin.toPrecision(4)} … ${ymax.toPrecision(4)}]`, 0, 0); ctx.restore();
  const cx = W - R + 20, ch = H - Tp - B;
  for (let k = 0; k < ch; k++) {
    ctx.fillStyle = color(1 - k / ch);
    ctx.fillRect(cx, Tp + k, 14, 1);
  }
  ctx.fillStyle = fg; ctx.textAlign = "left";
  ctx.fillText("可行率 1", cx + 18, Tp + 10);
  ctx.fillText("0", cx + 18, Tp + ch);
  // UI-R4 a11y：canvas 图像语义（PR-1 图表容器口径补齐本自研管线——
  // 参数名经 String 拼接，XSS 反向扫描口径零新增）
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "图表：可行性热图（" + d.x_param + " × " + d.y_param +
    "，格色=可行率 红（0）→黄（0.5）→绿（1），灰=无样本，格内数字=样本数）");
  info.textContent = `${d.n_trials_used}/${d.n_trials_total} 条 trial 参与分箱 · 可行 ${d.n_feasible_total} · ` +
    `${d.cells.length}/${n * n} 格有样本（格内数字=样本数；灰=无样本）`;
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
        `n=${c.n} 可行 ${c.n_feasible} 可行率 ${(c.feasible_rate * 100).toFixed(0)}% 平均总违约 ${c.mean_total_violation.toFixed(4)}`
      : "（无样本）";
  };
}

export async function pageOptStack() {
  const v = T.$("view-optstack");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>Pareto 前沿：nsga2 run 直读 results/pareto_front.json（E9 起落盘，含逐代精英存档超体积 hv_convergence）；旧 run / TPE run 由服务层从 trials 审计现算约束 Pareto（Deb 可行优先支配：可行支配不可行、不可行间总违约量小者优）。</li>
      <li>可行性热图：读 trials/*.json 的 params + constraint_values（≤0=可行），对所选两参数做确定性等宽分箱——格色=可行率、格内数字=样本数、悬停看平均总违约量；无约束 run 如实报"不可算"。</li>
      <li>数值全部出自确定性内核（SpecEvaluator 违约量 / pareto_tools），前端只渲染。</li>`) +
    `<h2 class='page'>优化洞察<small>Pareto 前沿 · 可行性热图（E9/E10）</small></h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b>
         <select id='os-run' style='max-width:340px'></select>
         <button class='minor' id='os-reload'>刷新</button>
         <span id='os-src' class='muted'></span></div>
       <div id='os-pareto'></div>
       <div id='os-hv' class='muted' style='margin-top:6px'></div>
     </div>
     <div class='panel'>
       <div class='toolbar'><b>x 参数</b><select id='os-x' style='max-width:200px'></select>
         <b>y 参数</b><select id='os-y' style='max-width:200px'></select>
         <b>网格</b><input id='os-n' value='12' style='width:56px'>
         <button class='minor' id='os-heat-btn'>可行性热图</button>
         <span id='os-info' class='muted'></span></div>
       <div id='os-heat'></div>
     </div>`;
  const listing = await T.api("/api/pareto_runs");
  const runs = listing.runs || [];
  const sel = T.$("os-run");
  if (!runs.length) {
    sel.innerHTML = "<option>（无 run）</option>";
    T.$("os-src").textContent = "先跑一次 tune --multi（nsga2）或带 optimization.constraints 的 tune";
    return;
  }
  // 分组下拉（项 3）：优化 run 排前，单点仿真 run 标注排后（仍可选，选中给人话空态）
  const tierLabel = { front: "有 Pareto 前沿（pareto_front.json）",
                      trials: "有调参轨迹（可由 trials 现算前沿）",
                      single: "单点仿真（无优化轨迹）" };
  const tierClass = { front: "", trials: "", single: "muted" };
  const byTier = { front: [], trials: [], single: [] };
  for (const r of runs) (byTier[r.tier] = byTier[r.tier] || []).push(r);
  sel.innerHTML = ["front", "trials", "single"]
    .filter((t) => byTier[t].length)
    .map((t) => `<optgroup label='${escAttr(tierLabel[t])}'>` + byTier[t].map((r) =>
      `<option value='${escAttr(r.run_id)}' class='${tierClass[t]}'>${esc(r.run_id)}（${esc(r.model || r.adapter || "?")}${t === "trials" ? " · " + esc(r.n_trials) + " trials" : ""}${t === "single" ? " · 单点" : ""}）</option>`).join("") + "</optgroup>")
    .join("");
  if (S.osRunId && runs.some((r) => r.run_id === S.osRunId)) sel.value = S.osRunId;

  const fillParams = (names) => {
    const opts = names.map((n) => `<option value='${escAttr(n)}'>${esc(n)}</option>`).join("")
      || "<option value=''>（先选一个优化 run）</option>";
    T.$("os-x").innerHTML = opts; T.$("os-y").innerHTML = opts;
    if (names.length > 1) T.$("os-y").value = names[1];
  };

  async function loadPareto() {
    S.osRunId = sel.value;
    const d = await T.api(`/api/runs/${encodeURIComponent(sel.value)}/pareto`);
    const el = T.$("os-pareto"), hv = T.$("os-hv");
    hv.textContent = "";
    if (!d.ok) {
      // 人话空态（项 3）：单点仿真 run 没有优化轨迹是预期，不是故障
      const meta = runs.find((r) => r.run_id === sel.value) || {};
      const human = meta.tier === "single"
        ? "该 run 是单点仿真，没有优化轨迹——请在下拉里选择带 pareto_front.json 的优化 run（或带 trials 的调参 run，可由 trials 现算前沿）。"
        : "该 run 暂无可画的 Pareto 前沿。";
      el.innerHTML = `<div class='muted'>${human}<br><small>${esc((d.errors || []).join("; "))}</small></div>`;
      T.$("os-src").textContent = "";
      fillParams([]);
      return;
    }
    fillParams(d.param_names || []);
    const names = d.objective_names || [];
    const pts = d.points || [];
    T.$("os-src").textContent = `来源 ${d.source} · ${d.n_pareto} 点` +
      (d.constraint_names && d.constraint_names.length ? ` · 约束 ${d.constraint_names.join(",")}` : "");
    if (!pts.length || names.length < 2) {
      el.innerHTML = "<div class='muted'>前沿为空或目标数不足 2</div>";
      return;
    }
    const feas = pts.filter((p) => p.feasible !== false);
    const infeas = pts.filter((p) => p.feasible === false);
    const toXY = (p) => [+p.objectives[names[0]], +p.objectives[names[1]]];
    const series = [{ name: `前沿${infeas.length ? "（可行）" : ""}`, type: "scatter",
                      data: feas.map(toXY),
                      color: themePick(bodyIsLight(), THEME_COLORS.seriesTeal),
                      symbolSize: 11 }];
    if (infeas.length)
      series.push({ name: "不可行", type: "scatter", data: infeas.map(toXY),
        color: themePick(bodyIsLight(), THEME_COLORS.seriesRed), symbolSize: 9 });
    // PR-3 PlotCard 换壳：option 与迁移前等价（scatter+xvalue，zoom off）
    T.plotCard(el, {
      series,
      xvalue: true, xlabel: `${names[0]} 违约量`, ylabel: `${names[1]} 违约量`,
      height: "300px", zoom: false,
      exportName: "pareto-front", exportCsv: false,
    });
    if (names.length > 2)
      hv.textContent = `目标 ${names.length} 维，散点取前两维（${names.slice(2).join(", ")} 未画）。`;
    if (d.hv_convergence && d.hv_convergence.length) {
      const h = d.hv_convergence;
      const mono = h.every((x, i) => i === 0 || x >= h[i - 1] - 1e-12);
      hv.textContent += ` 超体积收敛：${h.length} 代，${h[0].toFixed(4)} → ${h[h.length - 1].toFixed(4)}` +
        `（精英存档${mono ? "弱单调 ✓" : "非单调 ✗"}）`;
    }
  }

  async function loadHeat() {
    const x = T.$("os-x").value, y = T.$("os-y").value;
    const q = new URLSearchParams({ x_param: x, y_param: y, grid_n: T.$("os-n").value || "12" });
    const d = await T.api(`/api/runs/${encodeURIComponent(sel.value)}/feasibility?${q}`);
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
