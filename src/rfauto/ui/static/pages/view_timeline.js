/* rfauto 成本时间线页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）。
   W8-S32 i18n 批 3：本页接入壳扫描（第 9 页）——壳静态标签 data-i18n+
   首扫；状态行/空态/图表系列名与 aria 走 t() 渲染期烘焙（run_id/adapter
   等 API 数据仍走拼接直出，不进 t() params——i18n.js 头注纪律）。 */

import { THEME_COLORS, bodyIsLight, chartPalette, themePick } from "../theme.js";
import { T } from "./context.js";
import { help } from "./dom.js";
// i18n（W8-S32 批 3）
import { t, applyI18nRoot } from "./i18n.js";
// 三态收敛（aurora_f W2-S5，R1 #8 批1）：错误=kitErrorPanel、空态=kitEmptyState
import { kitEmptyState, kitErrorPanel } from "./kit.js";
// P8-9（aurora_f W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 1 点）——
// 数据面全页（成本时间线）接 viewSignal("timeline") 切页收束 + aborted 短路
//（在途拉取不再写隐藏区）。信封消费形态逐键不变。
import { apiFetch, viewSignal } from "./api.js";

/* ═══ 成本时间线（阶段 3.4）═══ */
export async function pageTimeline() {
  const v = T.$("view-timeline");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("timeline.help_1")}</li>
      <li>${t("timeline.help_2")}</li>
      <li>${t("timeline.help_3")}</li>`) +
    `<h2 class='page' data-i18n='timeline.title'>${t("timeline.title")}</h2>
     <div class='panel'><b data-i18n='timeline.panel_cost'>${t("timeline.panel_cost")}</b><div id='tl-cost'></div>
       <div id='tl-info' class='muted' style='margin-top:6px'></div></div>
     <div class='panel' style='margin-top:14px'><b data-i18n='timeline.panel_tune'>${t("timeline.panel_tune")}</b>
       <div id='tl-tune'></div></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W8-S32 i18n 批 3：本页接入壳扫描）
  const d = await apiFetch("/api/cost_timeline", { signal: viewSignal("timeline") });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  if (!d.ok) {
    // 三态收敛（aurora_f W2-S5，R1 #8 批1）：加载失败=kitErrorPanel 带重试
    //（重试=整页重进，pageTimeline 幂等：壳判 innerHTML 已在即跳过）
    T.$("tl-cost").innerHTML = kitErrorPanel((d.errors || []).join("; "), "tl-retry");
    const rb = T.$("tl-retry");
    if (rb) rb.onclick = () => pageTimeline();
    return;
  }
  const pts = d.points || [];
  const labels = pts.map((p) => p.timestamp.slice(5, 16).replace("T", " "));
  const byAdapter = {};
  pts.forEach((p) => (byAdapter[p.adapter] = byAdapter[p.adapter] || []).push(p));
  // 调色板=chartPalette（theme.js 单源，A5-B/R-4 收编旧整档镜像）
  const colors = chartPalette(bodyIsLight());
  // PR-3 PlotCard 换壳：option 与迁移前等价（base 路径）
  // W8-S32 i18n 批 3：横轴 t() 烘焙（系列名=adapter 通道值，API 数据不进词表）
  // W3-S9：数值读数类开十字线（category 轴 trigger=axis，cross 双轴读数=原生标准组合）
  T.plotCard(T.$("tl-cost"), {
    series: Object.keys(byAdapter).map((a, i) => ({
      name: a, x: labels,
      y: byAdapter[a].map((p) => +p.cost.toFixed(4)),
      color: colors[i % colors.length],
    })),
    xlabel: t("timeline.xlabel_cost"), ylabel: "cost", height: "300px",
    crosshair: true,
    exportName: "cost-timeline",
  });
  // W8-S32 i18n 批 3：状态行分段 t() 烘焙（计数走 {n} 占位=开发侧数值；
  // run_id/adapter=API 数据，保持拼接直出——禁止进 t() params）
  const lastPt = pts.length ? pts[pts.length - 1] : null;
  T.$("tl-info").textContent =
    t("timeline.info_cost_tpl", { n: pts.length }) +
    (d.n_without_cost ? t("timeline.info_nocost_tpl", { n: d.n_without_cost }) : "") +
    (lastPt ? t("timeline.info_latest_lead") + lastPt.run_id + "（" + lastPt.adapter + "）" : "");
  const tr = d.latest_tune_trials || [];
  if (tr.length)
    // PR-3 PlotCard 换壳 + convergence（声明增量：best-so-far 阶梯+末点）
    // W8-S32 i18n 批 3：系列名/横轴/aria t() 烘焙
    // W3-S9：数值读数类开十字线（xvalue 值轴 trigger=item，收敛末点读数面）
    T.plotCard(T.$("tl-tune"), {
      series: [{
        name: t("timeline.series_trial_cost"), x: tr.map((x) => x.trial_number),
        y: tr.map((x) => x.cost),
        color: themePick(bodyIsLight(), THEME_COLORS.seriesOrange),
      }],
      mode: "convergence",
      xvalue: true, crosshair: true, xlabel: "trial", ylabel: "cost", height: "260px",
      exportName: "tune-trial-convergence",
      ariaLabel: t("timeline.aria_tune"),
    });
  else
    // 三态收敛（R1 #8 批1）：无调参 run=kitEmptyState（原 muted 单行）
    T.$("tl-tune").innerHTML = kitEmptyState(t("timeline.empty_tune"));
}

/* ═══ R-1（aurora_e W3-S12）：PageContext 增量钩子 timelineCtx ══════════
   refresh=图表数据重拉（pageTimeline 幂等：壳判 innerHTML 已在即跳过，
   cost_timeline 重拉后 T.plotCard 同容器 setOption 复用刷新两张图）。
   无轮询面，leave 不需要。 */
export const timelineCtx = {
  refresh: () => pageTimeline(),
};
