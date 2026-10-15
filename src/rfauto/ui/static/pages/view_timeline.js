/* rfauto 成本时间线页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）。 */

import { THEME_COLORS, bodyIsLight, chartPalette, themePick } from "../theme.js";
import { T } from "./context.js";
import { esc, help } from "./dom.js";

/* ═══ 成本时间线（阶段 3.4）═══ */
export async function pageTimeline() {
  const v = T.$("view-timeline");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>上图：每个 run 的目标成本（快照 objectives 确定性重算，越低越好）按时间排列——战役/调参的整体进步一目了然，颜色按 adapter 分通道。</li>
      <li>下图：最近一次调参 run 的 trial 级 cost 收敛曲线（数据来自 trials 产物）。</li>
      <li>无配方快照或无指标的 run 不画点（计数见状态行）。</li>`) +
    `<h2 class='page'>成本时间线</h2>
     <div class='panel'><b>Run 目标成本时间线（低=好）</b><div id='tl-cost'></div>
       <div id='tl-info' class='muted' style='margin-top:6px'></div></div>
     <div class='panel' style='margin-top:14px'><b>调参收敛（最近 tune run）</b>
       <div id='tl-tune'></div></div>`;
  const d = await T.api("/api/cost_timeline");
  if (!d.ok) {
    T.$("tl-cost").innerHTML = `<span class='muted'>${esc((d.errors || []).join("; "))}</span>`;
    return;
  }
  const pts = d.points || [];
  const labels = pts.map((p) => p.timestamp.slice(5, 16).replace("T", " "));
  const byAdapter = {};
  pts.forEach((p) => (byAdapter[p.adapter] = byAdapter[p.adapter] || []).push(p));
  // 调色板=chartPalette（theme.js 单源，A5-B/R-4 收编旧整档镜像）
  const colors = chartPalette(bodyIsLight());
  // PR-3 PlotCard 换壳：option 与迁移前等价（base 路径）
  T.plotCard(T.$("tl-cost"), {
    series: Object.keys(byAdapter).map((a, i) => ({
      name: a, x: labels,
      y: byAdapter[a].map((p) => +p.cost.toFixed(4)),
      color: colors[i % colors.length],
    })),
    xlabel: "run 时间（旧→新）", ylabel: "cost", height: "300px",
    exportName: "cost-timeline",
  });
  T.$("tl-info").textContent =
    `${pts.length} 个 run 有成本` +
    (d.n_without_cost ? ` · ${d.n_without_cost} 个无快照/指标未画` : "") +
    (pts.length ? ` · 最新 ${pts[pts.length - 1].run_id}（${pts[pts.length - 1].adapter}）` : "");
  const tr = d.latest_tune_trials || [];
  if (tr.length)
    // PR-3 PlotCard 换壳 + convergence（声明增量：best-so-far 阶梯+末点）
    T.plotCard(T.$("tl-tune"), {
      series: [{
        name: "trial cost", x: tr.map((t) => t.trial_number),
        y: tr.map((t) => t.cost),
        color: themePick(bodyIsLight(), THEME_COLORS.seriesOrange),
      }],
      mode: "convergence",
      xvalue: true, xlabel: "trial", ylabel: "cost", height: "260px",
      exportName: "tune-trial-convergence",
      ariaLabel: "图表：trial cost，纵轴 cost，横轴 trial（含 best-so-far 阶梯）",
    });
  else
    T.$("tl-tune").innerHTML = "<span class='muted'>暂无调参 run（到「优化调参」页启动一次）</span>";
}
