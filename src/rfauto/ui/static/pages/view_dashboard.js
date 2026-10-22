/* rfauto 总览页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   组件化仪表盘（可增删 widget 注册表 + 拖拽排序 + 宽度记忆）。 */

import { THEME_COLORS, bodyIsLight, chartPalette, themePick } from "../theme.js";
// UI-R12 任务2：统一 API 层（apiFetch 错误信封与 T.api 同形；viewSignal=
// 视图作用域取消，切页由 app.js activate 收束在途请求）
import { apiFetch, viewSignal } from "./api.js";
import { bindChartResize, chartExportTools, echartsInitCached } from "./charts.js";
// W3.5-K1：getActiveView=可信度 KPI 跳画廊代点的"用户已离开画廊"守卫读面
import { T, getActiveView } from "./context.js";
// i18n（aurora_f W6-S21 扩面页 1；W8-S32 批 3 深化）：壳静态标签 data-i18n+
// 首扫；widget 标题经注册表 tk 字段、控件钮/aria 前缀/KPI/activity/空态/
// 图表系列名与 help 块富 HTML 分段全走 t() 渲染期烘焙（i18n.js 头注纪律：
// 随数据重建的动态容器不挂 data-i18n，防语言切换重扫覆写动态状态；富 HTML
// 分段=结构留模板、纯文本段进词表，W1-S2 hint 芯片先例）。
import { t, applyI18nRoot } from "./i18n.js";
import { freshnessRingSvg, relTime, statusBucket } from "./dashboard_util.js";
import { esc, escAttr, help } from "./dom.js";
import {
  bindClickRows,
  bindEmptyStates,
  kitBadgeCls,
  kitBoolBadge,
  kitClickRowAttrs,
  kitEmptyState,
  // W3.5-K1：可信度 KPI 清单定局失败=kitErrorPanel（A8-A 三态收敛同款）
  kitErrorPanel,
  kitSkeleton,
  kitTable,
} from "./kit.js";
import { openRun, showPage } from "./router.js";

/* ═══ 总览（组件化仪表盘：可增删的 widget 注册表）═══ */

// 组件注册表：新增可视化 = 加一个 render 函数 + 在 renderers 注册（解耦、可挑选）
// tk=词表键（i18n.js LOCALES，W6-S21 扩面）——标题渲染期 t(tk) 烘焙，注册表
// 不存字面（语言切换经 setLocale 全壳重扫+下一拍渲染生效）。
const WIDGETS = {
  kpi:         { tk: "dashboard.w_kpi",         span: 12 },
  recent_runs: { tk: "dashboard.w_recent_runs", span: 6  },
  activity:    { tk: "dashboard.w_activity",    span: 6  },
  s11_trend:   { tk: "dashboard.w_s11_trend",   span: 6  },
  solvers:     { tk: "dashboard.w_solvers",     span: 4  },
  tune_status: { tk: "dashboard.w_tune_status", span: 4  },
  status_mix:  { tk: "dashboard.w_status_mix",  span: 4  },
  // aurora_i W3.5-K1（R3 设计 M7 前端半）：可信度 KPI 卡进缺省面（既有
  // 用户 localStorage 记忆优先——W4-C 同款口径，点「＋ 添加组件」自取）。
  credibility: { tk: "dashboard.w_credibility", span: 4  },
  adapter_mix: { tk: "dashboard.w_adapter_mix", span: 4  },
  quick_links: { tk: "dashboard.w_quick_links", span: 12 },
};
// aurora36 W4-C：activity/status_mix 进缺省面（既有用户 localStorage 记忆
// 优先——存过自定义清单的看不到新组件，点「＋ 添加组件」自取）。
const WIDGET_DEFAULTS = ["kpi", "recent_runs", "activity", "s11_trend",
  "solvers", "tune_status", "status_mix", "credibility", "quick_links"];

/* 页私有状态（W6-S2 S 状态收编，R2 审计 §面2：原 S.dashData/S.widgetSet/
   S.widgetSpan/S.kpiPrev 单模块私有键降级模块级——属主=本模块，契约表见
   context.js。_dashData/_kpiPrev null 初值与原"键缺席"逐位等价（!x 与
   x || {...} 同值）；_widgetSet/_widgetSpan 首用必先经 renderDashboardGrid
   赋值，localStorage 持久语义不变）。 */
let _dashData = null;
let _widgetSet = new Set();
let _widgetSpan = {};
let _kpiPrev = null;
/* ═══ aurora_i W3.5-K1（R3 设计 M7 前端半）模块级缓存（属主=本模块；
   context.js 键契约表登记面禁改（他文件），属主/生命周期注记随本块）═══
   _credSummary=仲裁锚摘要行（/api/anchors 过滤 engine_pair.referee=hfss，
   会话级缓存——重进页/局部刷新即渲不重发）；_credLoadFail=清单定局失败
   （诚实降级一行，不重试风暴——gallery _anchorLoadFailed 同款纪律）；
   _credVerdicts=anchor_id→verdict_state 串（详情 /api/anchors/{id} 既有
   端点逐锚补拉，Map 缓存，失败也缓存空串）；_credVerdictsDone/_credVerdicts
   InFlight=补拉定局/在途旗（切页 abort 不定局不缓存，回页重拉）。 */
let _credSummary = null;
let _credLoadFail = false;
const _credVerdicts = new Map();
let _credVerdictsDone = false;
let _credVerdictsInFlight = false;
/* 首访导览 localStorage 键（rfauto- 家族命名；context.js 登记表禁改同上，
   键登记注记随本块头注）。 */
const ONBOARD_KEY = "rfauto-onboard-v1";

export async function pageDashboard() {
  const v = T.$("view-dashboard");
  // W3.5-K1：首访导览（键缺席=首访弹三步引导卡；已读 localStorage 记忆
  // 不再弹——onboardSeen/markOnboardSeen，store 注入=node 行为钉入口）。
  const showOnboard = !onboardSeen();
  // W8-S32 i18n 批 3：help 块富 HTML 分段 t() 烘焙（zh 输出逐字节不变）：
  // <b>/结构留模板、纯文本段进词表（值零 HTML 纪律），跨段标点归前段键尾。
  v.innerHTML = help(`
    <li>${t("dashboard.help_1_lead")}<b>${t("dashboard.help_1_core")}</b>${t("dashboard.help_1_tail")}</li>
    <li><b>${t("dashboard.help_2_core1")}</b>${t("dashboard.help_2_mid")}<b>${t("dashboard.help_2_core2")}</b>${t("dashboard.help_2_tail")}</li>
    <li><b>${t("dashboard.help_3_core")}</b>${t("dashboard.help_3_tail")}</li>
    <li><b>${t("dashboard.help_4_core1")}</b>${t("dashboard.help_4_mid")}<b>${t("dashboard.help_4_core2")}</b>${t("dashboard.help_4_tail1")}<b>${t("dashboard.help_4_core3")}</b>${t("dashboard.help_4_tail2")}</li>
    <li>${t("dashboard.help_5")}</li>`) +
    `<div class='pagehead'><h2 class='page' data-i18n='dashboard.title'>${t("dashboard.title")}</h2><span class='spacer'></span>
      <span class='muted' style="font-size:12px" data-i18n='dashboard.add_widget_label'>${t("dashboard.add_widget_label")}</span><span id='w-add'></span></div>
      ` + (showOnboard ? onboardCardHtml() : "") +
      // 导览卡在场时格网上面留一档间距（margin-bottom:var(--space-3) 已是
      // r12 CSS 同值替换钉的冻结计数面——间距挂格网侧不增该计数）
      `<div id='widget-grid'${showOnboard ? " style='margin-top:var(--space-3)'" : ""}></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W6-S21 扩面；导览卡=静态壳可挂 data-i18n）
  if (showOnboard) bindOnboard(v); // W3.5-K1：导览步骤跳页+dismiss 接线
  // A8-A（R6 审计 P-2）：首拉骨架屏——数据未到先按组件清单铺占位壳（shimmer
  // 条，reduced-motion 降级静态灰块）；下方 Promise.all 数据到达后 grid 重建
  // 整体替换。清单读 localStorage 与真实渲染同源（自定义清单用户看到自己清单
  // 的占位；span 用缺省档——占位期宽度近似即可，不提前读 widget-span）。
  const skGrid = T.$("widget-grid");
  if (skGrid) {
    let skSaved = null;
    try { skSaved = JSON.parse(localStorage.getItem("rfauto-widgets") || "null"); } catch { /* 隐私模式等 */ }
    const skIds = (Array.isArray(skSaved) && skSaved.length ? skSaved : WIDGET_DEFAULTS)
      .filter((k) => WIDGETS[k]);
    skGrid.innerHTML = skIds.map((k) =>
      `<div class="widget w${WIDGETS[k].span}"><div class='panel' style='height:100%'>` +
      `<b class='title'>${t(WIDGETS[k].tk)}</b>` +
      `<div class="skeleton-wrap" role="status" aria-label="${t("dashboard.loading_aria")}">${kitSkeleton(3)}</div></div></div>`
    ).join("");
  }
  // P8-4（aurora_f R1 §面1）：渐进首绘——/api/solvers 冷端点实测 8.3s
  // （服务端 TTL 缓存过期后再冷 3.7s），此前 Promise.all 把 KPI/最近 Run/
  // 活动流全押在最慢端点上，首屏白骨架窗最长秒级。两请求同时起飞，
  // runs 先到即整格首绘（solvers 槽位骨架占位）；solvers 后到只直写该
  // widget 面板体（不重铺网格——图表零重建、count-up 不重放）。
  const runsP = apiFetch("/api/runs?limit=200", { signal: viewSignal("dashboard") });
  const solversP = apiFetch("/api/solvers", { signal: viewSignal("dashboard") });
  const runs = await runsP;
  if (runs.aborted) return; // UI-R12：切页取消——不写隐藏区
  _dashData = { runs: runs.runs || [], solvers: null };
  await renderDashboardGrid();
  const solvers = await solversP;
  if (solvers.aborted) return; // UI-R12：切页取消——不写隐藏区
  _dashData.solvers = solvers.solvers || [];
  const grid = T.$("widget-grid");
  const body = grid && grid.querySelector('.widget[data-id="solvers"] .wbody');
  if (body) body.innerHTML = solversBodyHtml(_dashData.solvers); // 后补直写
}

/* ═══ R-1 局部刷新试点（aurora72 W1-S3，R6 审计 R-1）══════════════════
   refreshDashboard：widget 增删/拖拽与 palette「刷新当前页数据」走本入口
   ——只重铺组件面（renderDashboardGrid），不再全量 refetch /api/runs?limit=200
   + /api/solvers（复用进页时已拉取的 _dashData）。壳或数据未就绪（直调
   无壳/首拉在途）回退 pageDashboard 全量路径=旧行为。 */
export async function refreshDashboard() {
  if (!_dashData || !T.$("widget-grid")) return pageDashboard();
  await renderDashboardGrid();
}

/* R-1 PageContext（增量钩子，注册在 pages.js → router.js PAGE_CTX）：
   refresh=palette 局部刷新入口。enter 面即 pageDashboard（VIEWS 既有渲染
   函数，签名兼容零迁移）；本页无常驻轮询，leave 无需登记。 */
export const dashboardCtx = { refresh: () => refreshDashboard() };

/* ═══ W5-S23（深审 c 面真机实证）：组件增删后焦点保持 ═════════════════
   「移除组件」/添加菜单 chipbtn 触发 refreshDashboard() 整格重建——触发钮
   随旧 DOM 销毁，键盘/读屏焦点坠落到 body（真机实测 BODY(lost)）。
   本助手在刷新完成后把焦点还到目标面板首个 wclose 钮：删除=退到同位次
   面板（调用方传入删前位次；无余面板退到添加菜单容器），添加=新面板本体。
   目标缺席静默（#105 best-effort：还焦面不阻业务主路径）。 */
async function refreshGridKeepingFocus(widgetId, action, prevIdx) {
  await refreshDashboard();
  try {
    const grid = T.$("widget-grid");
    if (!grid) return;
    const panels = [...grid.querySelectorAll(".widget[data-id]")];
    let target = null;
    if (action === "add") target = panels.find((p) => p.dataset.id === widgetId);
    else target = panels[Math.max(0, Math.min(prevIdx, panels.length - 1))];
    const btn = target && target.querySelector(".wclose");
    if (btn) { btn.focus({ preventScroll: true }); return; }
    const add = T.$("w-add");
    if (add && add.firstChild && typeof add.firstChild.focus === "function")
      add.firstChild.focus({ preventScroll: true });
  } catch { /* 还焦失败静默 */ }
}

/* ═══ W5-S23（深审 e 面，W6 P-6 遗留清偿）：KPI 数字滚动 count-up ══════
   rAF 300ms easeOutCubic 补间；prefers-reduced-motion（或环境无 rAF）直出
   终值。easeOutCubic/countUpText 纯函数导出（node 行为钉可测）；DOM 驱动
   animateKpiValue 的 env 参数注入 reduced/raf/now（node 桩可测，缺省取
   浏览器全局）。首绘从 0 起、局部刷新从上一拍值起（_kpiPrev 记忆）。 */
export function easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3);
}
export function countUpText(from, to, t01, fmt) {
  const k = easeOutCubic(Math.max(0, Math.min(1, Number(t01) || 0)));
  return fmt(from + (to - from) * k);
}
export function animateKpiValue(el, from, to, fmt, env) {
  if (!el) return;
  const e = env || {};
  const reduced = typeof e.reduced === "boolean" ? e.reduced : _prefersReducedMotion();
  const raf = e.raf || (typeof requestAnimationFrame === "function"
    ? requestAnimationFrame : null);
  if (reduced || !raf || !Number.isFinite(from) || !Number.isFinite(to) || from === to) {
    el.textContent = fmt(to); // 直出终值（reduced-motion 纪律）
    return;
  }
  // 时基单源：帧戳（rAF 回调参数）与 performance.now() 同一原点——不得混
  // Date.now()（墙钟），否则 t01 恒负钳零=数字钉 0 + rAF 死循环（真机复验
  // 实证后修正）；node 测试经 env.now 注入。
  const nowFn = e.now || (() => performance.now());
  const t0 = nowFn();
  const DUR = 300;
  const step = () => {
    const t01 = Math.min(1, (nowFn() - t0) / DUR);
    el.textContent = countUpText(from, to, t01, fmt);
    if (t01 < 1) raf(step);
  };
  raf(step);
}
function _prefersReducedMotion() {
  try {
    return !!(window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  } catch { return false; }
}

/* P8-4：solvers 面板体渲染单源（widget 渲染器与 pageDashboard 渐进后补
   路径共用；模块级——后补直写在 pageDashboard 作用域调用）。插值纪律与
   原 wSolvers 逐字节同（esc(s.type) 文本语境+kitBoolBadge 内部转义）。 */
function solversBodyHtml(solvers) {
  // W8-S32 i18n 批 3：可用性徽章/版本注记 t() 烘焙；两行注记=两键 +
  // 模板 <br> 连接（词表值零 HTML 纪律，<br> 留模板）。
  return (solvers || []).map((s) =>
    `<div style="margin-bottom:var(--space-2)"><b>${esc(s.type)}</b> — ${kitBoolBadge(s.available, t("dashboard.solvers_available"), t("dashboard.solvers_unavailable"))}</div>`).join("")
    + `<div class="muted" style="margin-top:var(--space-2);font-size:12px">${t("dashboard.solvers_note_hfss")}<br>${t("dashboard.solvers_note_ads")}</div>`;
}

/* 组件面渲染单源：添加菜单 + widget 网格（enter 全量路径与局部刷新共用）。
   增删/拖拽三类变更就地 persistWidgets 后重铺本面——此前三类变更点各自
   递归整页渲染函数（连壳带数据全量重拉，R6 审计旧单体 pages.js:696/724/746
   三处），现收敛到本函数（数据面零 fetch）。 */
async function renderDashboardGrid() {
  const saved = JSON.parse(localStorage.getItem("rfauto-widgets") || "null") || WIDGET_DEFAULTS;
  _widgetSet = new Set(saved.filter((k) => WIDGETS[k]));
  // 添加组件菜单
  const addEl = T.$("w-add");
  const renderAddMenu = () => {
    addEl.innerHTML = "";
    for (const [id, w] of Object.entries(WIDGETS)) {
      if (_widgetSet.has(id)) continue;
      const b = document.createElement("button");
      b.className = "chipbtn";
      b.textContent = "＋ " + t(w.tk);
      // W5-S23：添加后焦点保持（chip 随 renderAddMenu 重建销毁——还焦新面板）
      b.onclick = () => { _widgetSet.add(id); persistWidgets(); refreshGridKeepingFocus(id, "add"); };
      addEl.appendChild(b);
    }
    if (!addEl.children.length)
      addEl.innerHTML = "<span class='muted'>" + t("dashboard.all_added") + "</span>";
  };
  renderAddMenu();
  const grid = T.$("widget-grid");
  grid.innerHTML = "";
  const renderers = { kpi: wKpi, recent_runs: wRecentRuns, s11_trend: wS11Trend,
                      solvers: wSolvers, tune_status: wTuneStatus,
                      adapter_mix: wAdapterMix, quick_links: wQuickLinks,
                      activity: wActivity, status_mix: wStatusMix,
                      credibility: wCredibility };
  // 宽度记忆（每组件 4/6/12 栅格列循环）
  _widgetSpan = JSON.parse(localStorage.getItem("rfauto-widget-span") || "{}");
  const order = [..._widgetSet];
  for (const id of order) {
    const w = WIDGETS[id];
    if (!w || !renderers[id]) continue;
    const span = _widgetSpan[id] || w.span;
    const panel = document.createElement("div");
    panel.className = `widget w${span}`;
    panel.dataset.id = id;
    panel.draggable = true;
    // A7-A ui-kit 试点如实不迁：按钮在 <b class='title'> 元素内闭合（title 与
    // 控件同在 b 内），与 kitPanelHead 的 "</b>" 后置 actions 形态字节不等——
    // 保持原内联（迁移纪律：结构不变才能迁，差异记录见席位报告）。
    // W5-S23：两 wclose 补 aria-label（icon 字符 ⤢/× 不进读屏可达名——
    // title 只悬浮不播报；深审 b 面缺口清偿）。
    // W8-S32 i18n 批 3：控件钮 title/aria 前缀迁词表 t() 烘焙——aria 走
    // {name} 占位整句键（en 语序自由），t(w.tk) 为开发侧可信文本，整值
    // escAttr 属性语境出口（zh 输出逐字节不变）。
    panel.innerHTML = `<div class='panel' style='height:100%'><b class='title'>${t(w.tk)}` +
      `<button class='wclose' title="${t("dashboard.btn_span")}" aria-label="${escAttr(t("dashboard.aria_span_tpl", { name: t(w.tk) }))}" data-act="span" style="margin-right:6px">⤢</button>` +
      `<button class='wclose' title="${t("dashboard.btn_remove")}" aria-label="${escAttr(t("dashboard.aria_remove_tpl", { name: t(w.tk) }))}" data-act="close">×</button></b><div class='wbody'></div></div>`;
    // W5-S23：删除/添加后焦点保持（refreshGridKeepingFocus——删传删前位次，
    // 增传 "add" 找新面板）；拖拽 drop 为指针驱动不还焦。
    panel.querySelector('[data-act="close"]').onclick = () => {
      const prevIdx = [...grid.querySelectorAll(".widget[data-id]")].indexOf(panel);
      _widgetSet.delete(id); persistWidgets(); refreshGridKeepingFocus(id, "remove", prevIdx);
    };
    panel.querySelector('[data-act="span"]').onclick = () => {
      const seq = [4, 6, 12];
      const cur = seq.indexOf(_widgetSpan[id] || w.span);
      _widgetSpan[id] = seq[(cur + 1) % seq.length];
      localStorage.setItem("rfauto-widget-span", JSON.stringify(_widgetSpan));
      panel.className = `widget w${_widgetSpan[id]}`;
    };
    // 拖拽排序（HTML5 DnD：拖到其它组件上交换位置）
    panel.ondragstart = (e) => { e.dataTransfer.setData("text/plain", id); };
    panel.ondragover = (e) => { e.preventDefault(); panel.style.outline = "1px dashed var(--accent)"; };
    panel.ondragleave = () => { panel.style.outline = ""; };
    panel.ondrop = (e) => {
      e.preventDefault(); panel.style.outline = "";
      const src = e.dataTransfer.getData("text/plain");
      if (!src || src === id) return;
      const arr = [..._widgetSet];
      arr.splice(arr.indexOf(src), 1);
      arr.splice(arr.indexOf(id), 0, src);
      _widgetSet = new Set(arr);
      persistWidgets();
      refreshDashboard();
    };
    grid.appendChild(panel);
    await renderers[id](panel.querySelector(".wbody"));
  }

  function persistWidgets() {
    localStorage.setItem("rfauto-widgets", JSON.stringify([..._widgetSet]));
  }

  async function wKpi(el) {
    const list = _dashData.runs;
    const s11s = list.map((r) => r.metrics?.s11_db_max_in_band).filter((c) => typeof c === "number");
    const best = s11s.length ? Math.max(...s11s) : null;
    const adapters = new Set(list.map((r) => r.adapter)).size;
    // aurora36 W4-C：数据新鲜度环挂首卡右上角（runs=新→旧序，list[0] 即最近
    // run 的 timestamp；零定时器，随本 widget 渲染重绘——进页/增删组件/拖拽）。
    const ring = freshnessRingSvg(list.length ? list[0].timestamp : null, Date.now());
    // W5-S23 count-up（W6 P-6）：初值占位，下方 animateKpiValue 同步补间/
    // 直出（reduced-motion 纪律）；无 JS 数字渲染路径不存在（本应用=JS 壳）。
    el.innerHTML = `<div class='cards' style="margin:0">` +
      `<div class='card' style="position:relative"><div class='k'>${t("dashboard.kpi_runs")}</div><div class='v'>0</div>` +
      `<span style="position:absolute;top:8px;right:10px">${ring}</span></div>` +
      `<div class='card'><div class='k'>${t("dashboard.kpi_best_s11")}</div><div class='v ${best != null ? "ok" : ""}'>-</div></div>` +
      `<div class='card'><div class='k'>${t("dashboard.kpi_adapters")}</div><div class='v'>0</div></div></div>`;
    // 补间面：首绘自 0 起、局部刷新自上一拍值起（_kpiPrev 记忆）；
    // best 首拍无前值=直出（0→负 dB 反向滚动反直觉，不做）。
    const prev = _kpiPrev || { runs: 0, best: null, adapters: 0 };
    const vs = el.querySelectorAll(".v");
    animateKpiValue(vs[0], prev.runs || 0, list.length, (n) => String(Math.round(n)));
    if (best != null)
      animateKpiValue(vs[1], prev.best == null ? best : prev.best, best,
        (n) => n.toFixed(2) + " dB");
    else vs[1].textContent = "-";
    animateKpiValue(vs[2], prev.adapters || 0, adapters, (n) => String(Math.round(n)));
    _kpiPrev = { runs: list.length, best, adapters };
  }
  async function wActivity(el) {
    // aurora36 W4-C（R1 §1.3 活动日志）：数据源=本页已拉取的 /api/runs
    // （_dashData.runs，零新增后端端点）；渲染最近 10 条（run 名/状态徽章/
    // 相对时间），点击复用 openRun 跳详情（palette 同款单入口，showPage("detail")
    // 形态的既有封装）。UI-R4：行可达形态收编 kitClickRow 单源（本组件为
    // R1 P1-2 试点原位点——role=link/tabindex/Enter 手写三件套换 kit 形态，
    // role 升 button：Space 激活键随 button 惯例一并生效）。
    const list = _dashData.runs.slice(0, 10);
    if (!list.length) {
      // A8-A（R6 审计 P-3）：空态三件式（图标+一句话+下一步动作钮）
      // W8-S32 i18n 批 3：文案单源迁词表 t() 烘焙（queue/runs 空态先例同口径）
      el.innerHTML = kitEmptyState(t("dashboard.activity_empty"),
        { icon: "☰", label: t("dashboard.activity_go_import"), view: "import" });
      bindEmptyStates(el);
      return;
    }
    const now = Date.now();
    el.innerHTML = "<div>" + list.map((r) => {
      const b = statusBucket(r.status);
      const cls = kitBadgeCls(b); // A7-A ui-kit：状态→类单源（pass/fail/other→ok/err/muted）
      // W8-S32 i18n 批 3：状态徽章文案 t() 烘焙（兜底状态值仍走 API 数据直显）
      const label = b === "pass" ? t("dashboard.activity_done")
        : b === "fail" ? t("dashboard.activity_fail")
        : String(r.status || t("dashboard.activity_unknown"));
      return `<div class="clickable" data-id="${escAttr(r.run_id)}" ` +
        kitClickRowAttrs({ label: t("runs.open_detail_aria") + (r.run_id || "") }) + " " +
        `style="display:flex;align-items:center;gap:var(--space-2);padding:var(--space-1) 0">` +
        `<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.run_id || "")}</span>` +
        T.badge(label, cls) +
        `<span class="muted" style="font-size:var(--text-xs)">${esc(relTime(r.timestamp, now))}</span></div>`;
    }).join("") + "</div>";
    // UI-R4：click 与 Enter/Space 同一激活（bindClickRows 单源；aria-label
    // 里 run_id 经 kit escAttr 出口转义——XSS 反向扫描口径零新增）
    bindClickRows(el, (row) => openRun(row.dataset.id), "[data-id]");
  }
  async function wStatusMix(el) {
    // aurora36 W4-C（R1 §1.3 甜甜圈图）：pass/fail 分布环形图——数据源=本页
    // 已拉取的 /api/runs status 字段（零新增端点）；走 W2-B 缓存基建
    // （echartsInitCached 实例守卫 + bindChartResize 监听去重）与 W3-B
    // chartExportTools 导出面（CSV/PNG，并顺带成为事件桥"最近装配"目标）。
    const list = _dashData.runs;
    if (!list.length) {
      el.innerHTML = "<span class='muted'>" + t("dashboard.mix_empty") + "</span>";
      return;
    }
    const n = { pass: 0, fail: 0, other: 0 };
    for (const r of list) n[statusBucket(r.status)]++;
    const holder = document.createElement("div");
    holder.style.height = "200px";
    el.appendChild(holder);
    const light = bodyIsLight();
    const fg = themePick(light, THEME_COLORS.fg);
    // 调色板=chartPalette（theme.js 单源，A5-B/R-4 镜像纪律已拆）：CHART_COLORS
    // 对应位取值——PASS=绿档[2] / FAIL=红档[3] / 其他=紫档[4]。
    const _pal = chartPalette(light);
    const pal = { pass: _pal[2], fail: _pal[3], other: _pal[4] };
    const data = [
      { name: "PASS", value: n.pass, itemStyle: { color: pal.pass } },
      { name: "FAIL", value: n.fail, itemStyle: { color: pal.fail } },
      { name: t("dashboard.mix_other"), value: n.other, itemStyle: { color: pal.other } },
    ].filter((d) => d.value > 0);
    const chart = echartsInitCached(holder); // P0-5 同源守卫（W2-B 基建）
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "item", formatter: "{b}: {c}（{d}%）" },
      legend: { bottom: 0, textStyle: { color: fg } },
      series: [{
        type: "pie", radius: ["52%", "78%"], center: ["50%", "44%"],
        data, label: { show: false }, animation: false,
      }],
    }, true); // notMerge：复用路径整体替换旧 option
    // PR-1 a11y：图表容器图像语义（读屏可闻）；计数经 String 拼接（不用
    // 模板插值直引 n 的字段——XSS 反向扫描口径零新增）；W8-S32 i18n 批 3：
    // aria 前缀/CSV 系列名 t() 烘焙（"其他"段与计数拼接保持既有字面形态）
    const cnt = "PASS " + n.pass + "、FAIL " + n.fail + "、" + t("dashboard.mix_other") + " " + n.other;
    holder.setAttribute("role", "img");
    holder.setAttribute("aria-label", t("dashboard.mix_aria_prefix") + cnt + "）");
    bindChartResize(holder); // W4-C：resize 去重（W2-B 基建）
    // refEl=null=append 到 widget 面板底（不插图表前，布局与四管线同构：
    // 工具条在上——widget 面板里放底部更贴近图）；传 null 亦保持既有四
    // 挂接点的跨席计数钉字面不被扰动。
    chartExportTools(el.parentElement, null, {
      name: "dashboard-status-mix",
      getChart: () => chart,
      getCsvSeries: () =>
        [{ name: t("dashboard.mix_csv_name"), x: ["PASS", "FAIL", t("dashboard.mix_other")], y: [n.pass, n.fail, n.other] }],
    });
  }
  async function wRecentRuns(el) {
    const list = _dashData.runs.slice(0, 8);
    // A7-A ui-kit 试点：表壳/列头 scope 单源（kitTable）。UI-R4：行键盘可达
    // 收编 kitClickRow（tr 行 role:null 保 row/cell 语义；aria-label 读屏
    // 可闻行动作）；路由钉 openRun(tr.dataset.id) 与 w7c 悬停钉不动；
    // empty:"" 显式保持空 tbody——与原实现逐字节等价。
    el.innerHTML = kitTable({
      columns: ["run_id", "adapter", t("runs.th_inband_s11")], rows: list, empty: "",
      // W5-S23：表格读屏命名（caption 全站为零的收账起步——kitTable 可选
      // caption 参数，sr-only 视觉隐藏）；W8-S32 i18n 批 3：caption/列头
      // t() 烘焙（列头复用 runs 域既有键，zh 值同笔）
      caption: t("dashboard.recent_caption"),
      rowHtml: (r) => {
        const m11 = r.metrics?.s11_db_max_in_band;
        return `<tr class="clickable" data-id="${escAttr(r.run_id)}" ${kitClickRowAttrs({ role: null, label: t("runs.open_detail_aria") + (r.run_id || "") })}><td>${esc(r.run_id || "")}</td><td>${esc(r.adapter || "")}</td><td>${esc(typeof m11 === "number" ? m11.toFixed(2) + " dB" : "-")}</td></tr>`;
      },
    });
    el.querySelectorAll("tr.clickable").forEach((tr) => {
      tr.title = tr.dataset.id || ""; // W7-C：run_id 列截断后悬停见全名
    });
    bindClickRows(el, (tr) => openRun(tr.dataset.id), "tr.clickable"); // A4-C：单入口收编（hash 深链同步）+ UI-R4 键盘可达
  }
  async function wS11Trend(el) {
    const list = _dashData.runs.filter((r) => typeof r.metrics?.s11_db_max_in_band === "number")
      .slice(0, 40).reverse();
    if (list.length < 2) { el.innerHTML = "<span class='muted'>" + t("dashboard.trend_empty") + "</span>"; return; }
    const holder = document.createElement("div");
    el.appendChild(holder);
    // PR-3 PlotCard 换壳：option 与迁移前 drawEChart 等价（base 路径）
    // W8-S32 i18n 批 3：图表系列名/横轴/aria 走 t() 烘焙（plotcard props 面）
    T.plotCard(holder, {
      series: [{
        x: list.map((r) => r.run_id.slice(5, 13)),
        y: list.map((r) => r.metrics.s11_db_max_in_band),
        name: t("dashboard.trend_series"),
      }],
      height: "240px", xlabel: t("dashboard.trend_xlabel"), ylabel: "dB",
      exportName: "s11-trend", ariaLabel: t("dashboard.trend_aria"),
    });
    const cap = document.createElement("div");
    cap.className = "muted";
    cap.style.cssText = "font-size:var(--text-xs);margin-top:var(--space-1)";
    // W8-S32 i18n 批 3：图注富 HTML 分段 t() 烘焙（<b>/<a> 留模板；链接文字
    // 复用 nav.sparams/nav.reports 既有键；zh 输出逐字节不变）
    cap.innerHTML = t("dashboard.trend_cap_a") + "<b>" + t("dashboard.trend_cap_notfreq") + "</b>" + t("dashboard.trend_cap_b") +
      "<a href='#' data-go='sparams' style='color:var(--accent)'>" + t("nav.sparams") + "</a>" + t("dashboard.trend_cap_or") +
      "<a href='#' data-go='reports' style='color:var(--accent)'>" + t("nav.reports") + "</a>";
    cap.querySelectorAll("a[data-go]").forEach((a) => {
      a.onclick = (e) => { e.preventDefault(); showPage(a.dataset.go); };
    });
    el.appendChild(cap);
  }
  async function wSolvers(el) {
    if (_dashData.solvers == null) {
      // P8-4：solvers 冷窗期间骨架占位（数据到达由 pageDashboard 后补
      // 路径直写面板体；refreshDashboard 若在此窗触发，重铺仍是骨架——
      // 数据面 null≠空清单，语义不混淆）
      el.innerHTML = `<div class="skeleton-wrap" role="status" aria-label="${t("dashboard.loading_aria")}">${kitSkeleton(3)}</div>`;
      return;
    }
    el.innerHTML = solversBodyHtml(_dashData.solvers);
  }
  async function wTuneStatus(el) {
    const st = await apiFetch("/api/tune/status", { signal: viewSignal("dashboard") });
    if (st.aborted) return; // UI-R12：切页取消——不写隐藏区
    el.innerHTML = st.running
      ? "<span class='spin'></span> " + t("dashboard.tune_running")
      : (st.error ? T.badge(t("dashboard.tune_error"), "err")
        : st.result ? T.badge(t("dashboard.tune_done"), "ok") + `<div class="muted" style="margin-top:6px">best_cost=${esc(st.result?.best_cost ?? "-")}</div>`
        : "<span class='muted'>" + t("dashboard.tune_never") + "</span>");
  }
  async function wAdapterMix(el) {
    const counts = {};
    for (const r of _dashData.runs)
      counts[r.adapter] = (counts[r.adapter] || 0) + 1;
    const total = _dashData.runs.length || 1;
    el.innerHTML = Object.entries(counts).map(([a, n]) =>
      `<div style="margin-bottom:var(--space-2)"><b>${esc(a)}</b> <span class="muted">${t("dashboard.adapter_count_tpl", { n, p: Math.round(n / total * 100) })}</span>
       <div style="height:8px;border-radius:4px;background:var(--panel2);margin-top:3px">
       <div style="height:8px;border-radius:4px;width:${n / total * 100}%;background:var(--accent)"></div></div></div>`).join("");
  }
  async function wQuickLinks(el) {
    // W8-S32 i18n 批 3：步骤标题复用 nav.* 既有键（单源不重立），说明文案
    // 走词表（quick links 四步）。
    const steps = [
      [t("nav.import"), t("dashboard.ql_import_d")],
      [t("nav.recipe"), t("dashboard.ql_recipe_d")],
      [t("nav.tune"), t("dashboard.ql_tune_d")],
      [t("nav.runs"), t("dashboard.ql_runs_d")],
    ];
    // 解构名 label/desc：不遮蔽外层 i18n t()（审查波 2 P3-7 纯风格收账
    // ——未来 steps 行内一旦要用 t()，遮蔽名会静默取到步骤文本）。
    el.innerHTML = "<div class='guide-flow'>" + steps.map(([label, desc], i) =>
      `<div class='guide-step'><span class='n'>${i + 1}</span><b>${label}</b><div>${desc}</div></div>`).join("") + "</div>";
  }
  /* ═══ 可信度 KPI widget（aurora_i W3.5-K1，R3 设计 M7 前端半）═══════
     三数：HFSS 仲裁锚数 / AGREE 判定占比（分数形态） / 覆盖模板族数。
     数据源零新端点：/api/anchors 摘要（engine_pair.referee=hfss 过滤，
     现役 17 条）+ /api/anchors/{id} 详情既有字段（verdict_state 只在
     详情——画廊 W2-S1 同款两段取数）。呈现红线（#122 家族）：分歧/待判/
     其他如实进注记行，不折百分比凑绿。点卡跳画廊抽屉 credibility 节
     （openGalleryCredibility，禁改他页通路=代点既有 data-gal 钮）。 */
  async function wCredibility(el) {
    if (_credLoadFail) {
      el.innerHTML = kitErrorPanel(t("dashboard.cred_load_fail"));
      return;
    }
    if (_credSummary) { credRenderBody(el); ensureCredVerdicts(el); return; }
    // 首拉骨架占位（P8-4 渐进首绘同款：取数不阻塞后续 widget 渲染）
    el.innerHTML = `<div class="skeleton-wrap" role="status" aria-label="${escAttr(t("dashboard.loading_aria"))}">${kitSkeleton(3)}</div>`;
    apiFetch("/api/anchors", { signal: viewSignal("dashboard") }).then((d) => {
      if ((d && d.aborted) || !el.isConnected) return; // 切页取消/面板离场
      if (d && d.ok) {
        _credSummary = (d.anchors || []).filter((a) => a && a.engine_pair &&
          a.engine_pair.referee === "hfss"); // 仲裁口径单源：裁判=HFSS
        credRenderBody(el);
        ensureCredVerdicts(el);
      } else {
        _credLoadFail = true; // 定局失败：诚实降级（不重试风暴，gallery 同款）
        el.innerHTML = kitErrorPanel(((d && d.errors) || []).join("; ") ||
          t("dashboard.cred_load_fail"));
      }
    }).catch(() => {
      _credLoadFail = true;
      if (el.isConnected) el.innerHTML = kitErrorPanel(t("dashboard.cred_load_fail"));
    });
  }
}

/* ═══ aurora_i W3.5-K1：可信度 KPI 纯函数（node 行为钉可测导出面）══════
   verdict 态三分类（画廊 anchorVerdictOf 同款纪律复述——DISAGREE 先于
   AGREE 判：长串态内可能并列"AGREE_JUDGE 单项不救总态"字样，先红后绿
   防误绿；空态=pending；其余 token（REJUDGE_PASS/BRANCH_A_* 等）原样归
   other 不猜测。#122 家族呈现红线：pending/other 照实进注记行，不并入
   AGREE 凑占比）。 */
export function credVerdictClass(state) {
  const s = state == null ? "" : String(state).trim();
  if (!s) return "pending";
  // W4-R2 P3-1：先剥全角括注（ms_cross 的 BRANCH_A_…（…一致…）注记
  // 语义是中性观测非总态——括注内的一致判定不应落绿）
  const tok = s.split("（")[0];
  if (/DISAGREE/i.test(tok)) return "disagree";
  if (/AGREE/i.test(tok)) return "agree";
  return "other";
}

/* 仲裁锚摘要行→KPI 统计：nArb=referee=hfss 条数；fams=覆盖模板族
   （template_family 数组/标量/缺席三形态收敛；"*" 通配=全局锚不落族）；
   agree/disagree/other 取 verdicts Map（anchor_id→态串），缺席=待判。 */
export function credStats(arb, verdicts) {
  const list = Array.isArray(arb) ? arb : [];
  const fams = new Set();
  let agree = 0, disagree = 0, other = 0, pending = 0;
  for (const a of list) {
    const tf = a && Array.isArray(a.template_family) ? a.template_family
      : (a && a.template_family != null ? [a.template_family] : []);
    for (const f of tf) {
      const k = String(f || "").trim();
      if (k && k !== "*") fams.add(k);
    }
    const cls = credVerdictClass(verdicts ? verdicts.get(String(a.anchor_id)) : undefined);
    if (cls === "agree") agree++;
    else if (cls === "disagree") disagree++;
    else if (cls === "other") other++;
    else pending++;
  }
  return { nArb: list.length, fams: [...fams].sort(), agree, disagree, other, pending };
}

/* ═══ aurora_i W3.5-K1：首访导览（localStorage 记忆已读不再弹）════════
   键缺席=首访（弹三步引导卡）；写档失败（隐私模式等）→ dismiss 仅本会话
   生效（下次再弹=诚实降级，#105 best-effort）。store 参数注入=node 行为
   钉入口（缺省读浏览器 localStorage，typeof 守卫零 DOM 依赖——node 裸
   import 惯例）。 */
export function onboardSeen(store) {
  const ls = store || (typeof localStorage === "undefined" ? null : localStorage);
  if (!ls || typeof ls.getItem !== "function") return false;
  try { return ls.getItem(ONBOARD_KEY) != null; } catch { return false; }
}
export function markOnboardSeen(store) {
  const ls = store || (typeof localStorage === "undefined" ? null : localStorage);
  if (!ls || typeof ls.setItem !== "function") return;
  try { ls.setItem(ONBOARD_KEY, "seen"); } catch { /* 隐私模式等 */ }
}

/* 导览卡 HTML（静态壳：data-i18n 三通道合法面——文案随 setLocale 重扫
   自更新；步骤行 data-go 由 bindOnboard 经 bindClickRows 接 showPage，
   键盘可达同 kitClickRow 单源；键字面逐一落模板防动态拼键逃逸
   _PAGE_KEY_LIT 扫描）。 */
function onboardCardHtml() {
  return `<div class='panel' id='onboard-card' role='region' aria-label="${escAttr(t("dashboard.onboard_aria"))}">` +
    `<div style='display:flex;align-items:baseline;gap:8px;flex-wrap:wrap'>` +
    `<b data-i18n='dashboard.onboard_title'>${t("dashboard.onboard_title")}</b>` +
    `<span style='flex:1'></span>` +
    `<button class='minor' data-onboard-dismiss>${t("dashboard.onboard_dismiss")}</button></div>` +
    `<div class='guide-flow' style='margin-top:var(--space-2)'>` +
    `<div class='guide-step' data-go='tune' ${kitClickRowAttrs({ label: t("dashboard.onboard_s1_desc") })}>` +
    `<span class='n'>1</span><b data-i18n='nav.tune'>${t("nav.tune")}</b>` +
    `<div data-i18n='dashboard.onboard_s1_desc'>${t("dashboard.onboard_s1_desc")}</div></div>` +
    `<div class='guide-step' data-go='runs' ${kitClickRowAttrs({ label: t("dashboard.onboard_s2_desc") })}>` +
    `<span class='n'>2</span><b data-i18n='nav.runs'>${t("nav.runs")}</b>` +
    `<div data-i18n='dashboard.onboard_s2_desc'>${t("dashboard.onboard_s2_desc")}</div></div>` +
    `<div class='guide-step' data-go='gallery' ${kitClickRowAttrs({ label: t("dashboard.onboard_s3_desc") })}>` +
    `<span class='n'>3</span><b data-i18n='nav.gallery'>${t("nav.gallery")}</b>` +
    `<div data-i18n='dashboard.onboard_s3_desc'>${t("dashboard.onboard_s3_desc")}</div></div>` +
    `</div></div>`;
}

/* 导览接线（幂等：card 缺席静默）：三步=点击/Enter/Space 跳对应页
   （bindClickRows 单源，与活动流同款）；dismiss=写 localStorage + 摘卡。 */
function bindOnboard(v) {
  const card = v.querySelector("#onboard-card");
  if (!card) return;
  bindClickRows(card, (row) => showPage(row.dataset.go), "[data-go]");
  const btn = card.querySelector("[data-onboard-dismiss]");
  if (btn) btn.onclick = () => { markOnboardSeen(); card.remove(); };
}

/* 可信度卡体渲染（摘要就绪与 verdict 补拉定局两路径共用单点；数据全部
   出自 _credSummary/_credVerdicts 模块缓存+词表，零 API 数据插值——无
   esc 面）。AGREE 占比=x/总数 分数形态；verdict 补拉在途="…"占位。 */
function credRenderBody(el) {
  const s = credStats(_credSummary || [], _credVerdicts);
  const agreeTxt = _credVerdictsDone ? s.agree + "/" + s.nArb : "…";
  el.innerHTML =
    `<div class="cards" style="margin:0;cursor:pointer" data-cred-open ` +
    kitClickRowAttrs({ label: t("dashboard.cred_stats_aria") }) + `>` +
    `<div class='card'><div class='k'>${t("dashboard.cred_k_anchors")}</div><div class='v'>${s.nArb}</div></div>` +
    `<div class='card'><div class='k'>${t("dashboard.cred_k_agree")}</div><div class='v'>${agreeTxt}</div></div>` +
    `<div class='card'><div class='k'>${t("dashboard.cred_k_fams")}</div><div class='v'>${s.fams.length}</div></div></div>` +
    `<div class="muted" style="margin-top:var(--space-1)">${t("dashboard.cred_note_tpl", { d: s.disagree, p: s.pending, o: s.other })}</div>` +
    `<div style="margin-top:var(--space-2)"><button class="minor" data-cred-btn>${t("dashboard.cred_open")}</button></div>`;
  const open = () => openGalleryCredibility();
  bindClickRows(el, open, "[data-cred-open]");
  const btn = el.querySelector("[data-cred-btn]");
  if (btn) btn.onclick = open;
}

/* 逐锚详情补拉（既有端点 /api/anchors/{id}：verdict_state 在 provenance、
   只在详情面——画廊 W2-S1 同款两段取数）。全部定局才写缓存旗；切页 abort
   不定局不缓存（回页重拉）；单锚失败按空串=pending 如实进注记（失败也
   缓存不重试风暴）。定局后只重铺本 widget 体（AGREE 数到位，零全格重建）。 */
function ensureCredVerdicts(el) {
  if (_credVerdictsInFlight || _credVerdictsDone || !_credSummary ||
    !_credSummary.length) return;
  _credVerdictsInFlight = true;
  const ids = _credSummary.map((a) => String(a.anchor_id));
  Promise.all(ids.map((id) =>
    apiFetch("/api/anchors/" + encodeURIComponent(id),
      { signal: viewSignal("dashboard") })
      .then((d) => ({ id, aborted: !!(d && d.aborted),
        st: d && d.ok && d.anchor
          ? String(((d.anchor.provenance || {}).verdict_state) || "") : "" }))
      .catch(() => ({ id, aborted: false, st: "" }))
  )).then((rs) => {
    _credVerdictsInFlight = false;
    if (rs.some((r) => r.aborted)) return; // 切页取消：不定局（回页重拉）
    for (const r of rs) _credVerdicts.set(r.id, r.st);
    _credVerdictsDone = true;
    if (el.isConnected) credRenderBody(el);
  });
}

/* 点卡跳画廊抽屉 credibility 节（禁改他页通路）：view_gallery 的抽屉开函
   私有，唯一不动他页的通路=showPage("gallery") 后代点既有 data-gal 详情
   钮（openDrawer 同步铺节），再把抽屉滚到可信度节标题。目标模板=覆盖族
   优先（wilkinson 恒首选——仲裁锚+对照曲线双面样板）；画廊网格未到则
   100ms 轮询上限 ~6s；期间用户离开画廊（activeView≠gallery）即放弃；
   目标缺席静默降级=停在画廊页（#105 best-effort：导览链路不阻业务主
   路径）。 */
function openGalleryCredibility() {
  showPage("gallery");
  const fams = credStats(_credSummary || [], _credVerdicts).fams;
  let tries = 0;
  const tick = () => {
    if (getActiveView() !== "gallery") return; // 用户已离开画廊：放弃代点
    const grid = T.$("gal-grid");
    const btns = grid ? [...grid.querySelectorAll("[data-gal]")] : [];
    let target = null;
    for (const name of ["wilkinson", ...fams]) {
      target = btns.find((b) => b.getAttribute("data-gal") === name);
      if (target) break;
    }
    if (!target && btns.length) target = btns[0];
    if (target) {
      target.click(); // 抽屉同步铺节（openDrawer 私有——代点是唯一通路）
      const slot = document.querySelector(".kit-confirm [data-slot=credibility]");
      const h = slot && slot.previousElementSibling;
      if (h && typeof h.scrollIntoView === "function")
        h.scrollIntoView({ block: "start" });
      return;
    }
    if (++tries < 60) setTimeout(tick, 100); // 网格未到：~6s 上限
  };
  setTimeout(tick, 100);
}
