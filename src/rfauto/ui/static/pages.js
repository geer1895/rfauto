/* rfauto 工作台页面入口（架构批 UI-R2：pages.js 单体 ES module 化拆分）。
   本文件 = 薄入口，只做三件事：
   ① 按域组装 pages/ 各模块——视图注册表 VIEWS 逐键注入（键集与拆分前
     showPage 内联 views 表逐字节一致）；
   ② 初始化——initPages（工具集注入 + 轮询/SSE/导出桥/tools 深链四监听装配）
     与主题四态控制（setThemeMode/getThemeMode）；
   ③ 既有公开导出面全量 re-export（app.js/palette.js 的 import 路径
     "./pages.js" 不变；导出面 54 名逐名等价见等价性审计归档）。
   拆分域：context/dom/sortable/charts/polling/sse/kit/router/dashboard_util/
   filebrowser + view_*（按页面域，见各模块 docstring）。行为零变化纪律：
   页面代码逐字节搬移（含注释），仅 import 接线与跨模块状态访问器
   （_activeView→context.js、_campaignPendingId→router.js 消费函数）为接缝。
   零构建：原生 <script type="module"> 相对路径 import，浏览器直跑。
   ═══ UI-R12（架构批 前端深化席）任务1：路由懒加载 ═══
   视图注册从全量静态 import 改为原生 ESM 动态 import()（零构建形态保持，
   浏览器直跑）：首屏只装配基础设施 + view_tools（router opener 静态依赖）
   + view_dashboard（首屏落地页），其余 21 视图首次进入该页时按需拉取——
   VIEWS 注册表键集/字节与拆分前一致（绑定名别名保形），showPage 同步
   分发/回落语义不动；加载失败可见化（单页错误面板，#105）。 */
import { T } from "./pages/context.js";
// 主题判定/双档调色板单源在 theme.js（架构批 A5-B）——本入口消费四态
// 控制面并 re-export 常量/纯函数（palette.js 与 node 行为钉 import 自
// pages.js 的历史口径不变）。
import {
  THEME_KEY, THEME_MODES, THEME_LABEL,
  themeIsLight, applyThemeDom,
} from "./theme.js";
// initPages 四监听装配面（各自单源模块）
import { _bindVisibilityPolling } from "./pages/polling.js";
import { _bindVisibilitySSE } from "./pages/sse.js";
import { _bindExportChartEvent, _bindThemeRefresh } from "./pages/charts.js";
// 视图静态保留两件（UI-R12 任务1）：view_tools=router.js opener 的静态
// 依赖（toolsSelectKey 经 路由→视图→路由 环复用，见 router.js 头注），
// 本身已随路由加载；view_dashboard=首屏落地页（保 boot 首绘时序逐字节
// 等价——showPage("dashboard") 同步渲染，setTimeout(0) 补焦时标题已在
// DOM）。其余 21 个视图模块改原生 ESM 动态 import() 按需加载。
import { _bindToolsDeepLink, pageTools } from "./pages/view_tools.js";
import { pageDashboard, dashboardCtx } from "./pages/view_dashboard.js";
// 路由分发（VIEWS 注册表 + showPage 单源）+ R-1 PageContext 注册表
import { PAGE_CTX, VIEWS } from "./pages/router.js";
// i18n 骨架（架构批 W1-S2，R1 审计面2 规格）：静态壳首扫 + html lang 同步
import { applyI18nRoot, getLocale } from "./pages/i18n.js";
// esc 本模块内直接消费（懒加载失败面板转义）；dom.js 本就随门面 re-export
// 在静态依赖图内，此处补具名绑定（re-export 语法不产生本地绑定）。
import { esc } from "./pages/dom.js";

/* ═══ UI-R12 任务1（架构批 前端深化席）：懒加载视图包装器 ═════════
   路由从全量静态 import 改为原生 ESM 动态 import()（零构建：相对说明符
   浏览器直跑，无打包器）——首屏 JS 体积从"基础设施+全部 23 视图"降到
   "基础设施+view_tools+view_dashboard"，其余视图在首次进入该页时按需
   拉取（浏览器模块缓存命中后零开销）。
   行为零变化纪律：绑定名与拆分前静态 import 逐字一致（下方 VIEWS 注册
   表与既有注册序钉字节不变）；showPage 的同步分发/回落语义不动（包装器
   本身是异步函数，与各视图渲染器本就是 async 的 fire-and-forget 语义
   同构）。补焦接线：activate 的 setTimeout(0) 在模块在途时找不到
   h2.page → 挂起 T._lazyFocusPending，渲染完成后经 T.pageFocusAfterRender
   补焦+公告（app.js 单源面板；模块缓存命中路径不触发，行为与旧一致）。 */
function _lazyView(key, file, name) {
  return async (...args) => {
    try {
      const m = await import("./pages/" + file);
      const out = m[name](...args);
      // 补焦收尾：切页时标题未落 DOM（模块在途）→ activate 挂起，渲染后补
      if (T._lazyFocus && T._lazyFocus.pending === key) {
        T._lazyFocus.pending = null;
        try { T.pageFocusAfterRender(key); } catch { /* 公告面缺席静默 */ }
      }
      return out;
    } catch (e) {
      // 加载失败可见化（#105 best-effort）：此前静态 import 失败=整站白屏
      // 不可恢复；动态化后失败面收敛到单页——错误面板 + 全局 toast，
      // 不留未处理 rejection。
      if (T._lazyFocus) T._lazyFocus.pending = null;
      const m = "页面模块加载失败：" + (e && e.message ? e.message : e);
      try {
        const el = document.getElementById("view-" + key);
        if (el) el.innerHTML =
          `<div class='panel'><b class='title'>${esc(key)}</b><span class='muted'>${esc(m)}</span></div>`;
      } catch { /* DOM 缺席（node 行为钉环境）静默 */ }
      if (T.msg) try { T.msg(m, false); } catch { /* best-effort */ }
      return undefined;
    }
  };
}

/* ═══ R-1（架构批 W1-S3）：懒加载页的 PageContext 包装器 ═════════
   懒加载视图的钩子面：进过页后模块已在缓存，refresh/leave 动态 import
   命中缓存零网络；leave 仅在离页触发（此前必已进页）=恒缓存命中。未加载
   （页面从未进入）时理论不可达，仍按 #105 best-effort 静默兜底。 */
function _lazyCtx(file, name) {
  return {
    refresh: async () => {
      try {
        const m = await import("./pages/" + file);
        const c = m[name];
        if (c && typeof c.refresh === "function") await c.refresh();
      } catch { /* 刷新失败不抛未处理 rejection */ }
    },
    leave: async () => {
      try {
        const m = await import("./pages/" + file);
        const c = m[name];
        if (c && typeof c.leave === "function") await c.leave();
      } catch { /* 离页收束失败静默 */ }
    },
  };
}

/* 懒加载别名（键名=渲染函数历史绑定名，与拆分前 import 面逐字一致）。 */
const pageImport = _lazyView("import", "view_import.js", "pageImport");
const pageRecipe = _lazyView("recipe", "view_recipe.js", "pageRecipe");
const pageTune = _lazyView("tune", "view_tune.js", "pageTune");
const pageLoopBoard = _lazyView("loopboard", "view_loopboard.js", "pageLoopBoard");
const pageRuns = _lazyView("runs", "view_runs.js", "pageRuns");
const showRun = _lazyView("detail", "view_detail.js", "showRun");
const pageAgent = _lazyView("agent", "view_agent.js", "pageAgent");
const pageGuide = _lazyView("guide", "view_guide.js", "pageGuide");
const pageSolvers = _lazyView("solvers", "view_solvers.js", "pageSolvers");
const pageCalibration = _lazyView("calibration", "view_calibration.js", "pageCalibration");
const pageSparams = _lazyView("sparams", "view_sparams.js", "pageSparams");
const pageTimeline = _lazyView("timeline", "view_timeline.js", "pageTimeline");
const pageReports = _lazyView("reports", "view_reports.js", "pageReports");
const pagePlayground = _lazyView("playground", "view_playground.js", "pagePlayground");
const pageFarfield = _lazyView("farfield", "view_fieldviz.js", "pageFarfield");
const pageField = _lazyView("field", "view_fieldviz.js", "pageField");
const pageOptStack = _lazyView("optstack", "view_optstack.js", "pageOptStack");
const pageDatasets = _lazyView("datasets", "view_data.js", "pageDatasets");
const pageAnchors = _lazyView("anchors", "view_data.js", "pageAnchors");
const pageUq = _lazyView("uq", "view_data.js", "pageUq");
const pageGallery = _lazyView("gallery", "view_gallery.js", "pageGallery");
const pageCampaign = _lazyView("campaign", "view_campaign.js", "pageCampaign");
const pageProfile = _lazyView("profile", "view_profile.js", "pageProfile");
const pageQueue = _lazyView("queue", "view_queue.js", "pageQueue");

/* 视图注册表组装（router.js VIEWS 单源写入点）：键集/注释与拆分前
   showPage 内联 views 表逐键一致。 */
Object.assign(VIEWS, {
  dashboard: pageDashboard, import: pageImport, recipe: pageRecipe,
  tune: pageTune, loopboard: pageLoopBoard, runs: pageRuns, detail: showRun,
  agent: pageAgent, guide: pageGuide, solvers: pageSolvers,
  calibration: pageCalibration, sparams: pageSparams, timeline: pageTimeline,
  reports: pageReports, tools: pageTools, playground: pagePlayground,
  farfield: pageFarfield, field: pageField, optstack: pageOptStack,
  datasets: pageDatasets, anchors: pageAnchors, uq: pageUq,
  /* PR-5/6/8（ge8b Wave B 席B2）：画廊 / 战役仪表盘 / 剖析 */
  gallery: pageGallery, campaign: pageCampaign, profile: pageProfile,
  /* PR-9 调度队列页（ge8b Wave B 席B3）：战役队列+G13 决策日志 */
  queue: pageQueue,
});

/* R-1 PageContext 注册（架构批 W1-S3 协议在 router.js PAGE_CTX；
   架构批 W2-S7 波2 余页迁移 + W3-S12 波3 第二组 6 页 + W4-S17 波4 收尾）：
   - dashboard=静态导入直登记（widget 增删/拖拽/palette 刷新走局部重铺，
     view_dashboard.js refreshDashboard）；
   - 懒加载页经 _lazyCtx 包装：
     · loopboard：refresh=立即拉看板、leave=_pollStop 离页停表（W1 试点）
     · tune：refresh=立即拉状态+trials、leave=_pollStop 非终态停表
       （终态停仍走 tuneRefresh 内 _pollStop(name,true) 语义不变）
     · detail：refresh=当前 run 重渲（无轮询面，leave 不需要）
     · runs：refresh=run 清单重拉（壳与筛选态复用）
     · campaign：refresh=当前所选 run 立即拉看板（loadDash 闭包经模块级
       引用转发；SSE 收束由 router._sseLeavePage 单源管）
     · reports：refresh=报告清单重拉（行绑定覆盖式幂等）
     · sparams（W3-S12）：refresh=免全页重建直刷曲线（load 闭包经模块级
       引用转发——只重拉当前 run 曲线/Smith 数据换图区）
     · calibration：refresh=表数据重拉（runs 同模板，行点击详情区不整清）
     · queue：refresh=战役计划表重拉（runs 同模板）
     · gallery：refresh=模板卡数据重拉（过滤词与已开预览面保持）
     · optstack：refresh=Pareto 前沿图重拉（plotCard 壳 setOption 复用）
     · timeline：refresh=成本时间线两图重拉（同上 setOption 复用）
     · W4-S17 波4 收尾十一页（全 refresh-only，无轮询面=无 leave 需求）：
       solvers/profile/datasets/anchors/uq/playground/farfield/recipe/tools
       八页 refresh=各自 page 函数整体重拉（幂等：壳判 innerHTML 已在即跳过
       或整页重建无交互态；profile/recipe/playground/farfield/tools 编辑/
       选择态随壳保留）；field=load 闭包经模块级引用转发（sparams 同款——
       切片滑条索引与 run/dump 选择态保留）；agent=数据面板重拉闭包转发
       （对话浮窗与气泡历史不动——appendBubble 非幂等，整页重跑会重复追加）。
   其余 2 页未登记（渐进迁移收口，跳过理由）：
     · guide=纯静态说明书壳（零数据拉取/零轮询/零交互态）；
     · import=纯交互表单页（/api/hfss/import 等均为用户点击触发，无进页
       数据面——refresh 语义空，重进反而丢表单编辑态）。 */
Object.assign(PAGE_CTX, {
  dashboard: dashboardCtx,
  loopboard: _lazyCtx("view_loopboard.js", "loopboardCtx"),
  tune: _lazyCtx("view_tune.js", "tuneCtx"),
  detail: _lazyCtx("view_detail.js", "detailCtx"),
  runs: _lazyCtx("view_runs.js", "runsCtx"),
  campaign: _lazyCtx("view_campaign.js", "campaignCtx"),
  reports: _lazyCtx("view_reports.js", "reportsCtx"),
  /* W3-S12 波3 第二组（六页，全 refresh-only 无轮询面） */
  sparams: _lazyCtx("view_sparams.js", "sparamsCtx"),
  calibration: _lazyCtx("view_calibration.js", "calibrationCtx"),
  queue: _lazyCtx("view_queue.js", "queueCtx"),
  gallery: _lazyCtx("view_gallery.js", "galleryCtx"),
  optstack: _lazyCtx("view_optstack.js", "optstackCtx"),
  timeline: _lazyCtx("view_timeline.js", "timelineCtx"),
  /* W4-S17 波4 收尾（十一页，全 refresh-only 无轮询面） */
  solvers: _lazyCtx("view_solvers.js", "solversCtx"),
  profile: _lazyCtx("view_profile.js", "profileCtx"),
  datasets: _lazyCtx("view_data.js", "datasetsCtx"),
  anchors: _lazyCtx("view_data.js", "anchorsCtx"),
  uq: _lazyCtx("view_data.js", "uqCtx"),
  playground: _lazyCtx("view_playground.js", "playgroundCtx"),
  farfield: _lazyCtx("view_fieldviz.js", "farfieldCtx"),
  field: _lazyCtx("view_fieldviz.js", "fieldCtx"),
  agent: _lazyCtx("view_agent.js", "agentCtx"),
  recipe: _lazyCtx("view_recipe.js", "recipeCtx"),
  tools: _lazyCtx("view_tools.js", "toolsCtx"),
});

/* PR-1 主题 → v5.0 Aurora 四态（midnight|ocean|light|system）：localStorage
   键 rfauto-theme 延续；"dark" 为旧存量别名（读档/set 时映射到 midnight）。
   system 态用 matchMedia(prefers-color-scheme) 跟随并监听变化（仅 system 态
   生效）。主题变量挂在 html[data-theme]（v5.0 设计系统）；body.light 信号
   保留=echarts/图表消费面（浅色主题才置位，双暗主题下为 false）。
   ═══ 架构批 A5-B（R6 审计 R-4）═══ THEME_KEY/THEME_MODES/THEME_LABEL
   常量、themeIsLight 纯函数、applyThemeDom 双写单源全部迁入 theme.js；
   此处 re-export 保持既有公开面（palette.js 与 node 行为钉 import 自
   pages.js 的历史口径不变）。 */
export { THEME_KEY, THEME_MODES, THEME_LABEL, themeIsLight };
const _LEGACY_ALIAS = { dark: "midnight" };

let _themeCtl = null; // initPages 装配 {get, set}；未初始化时 setThemeMode 兜底直改 DOM

/* 供命令面板等外部调用的主题设置入口。 */
export function setThemeMode(mode) {
  mode = _LEGACY_ALIAS[mode] || mode;
  if (!THEME_MODES.includes(mode)) return false;
  if (_themeCtl) { _themeCtl.set(mode); return true; }
  applyThemeDom(mode); // 兜底双写单源（theme.js）
  try { localStorage.setItem(THEME_KEY, mode); } catch { /* 隐私模式等，best-effort */ }
  return true;
}
export function getThemeMode() {
  return _themeCtl ? _themeCtl.get() : (localStorage.getItem(THEME_KEY) || "system");
}

export function initPages(toolkit) {
  Object.assign(T, toolkit);
  // 架构批 W1-S2（R1 审计面2 规格）：i18n 静态壳首扫（index.html 的
  // nav/group/skip/palette/foot data-i18n* 三通道；试点页壳各自渲染后再扫）
  // + html lang 与语言档同步（读屏发音口径）。装配序在 app.js showPage 前，
  // navBtns onclick 绑 data-v 不受文本替换影响。
  applyI18nRoot(document);
  try { document.documentElement.setAttribute("lang", getLocale()); } catch { /* node 等 */ }
  _bindVisibilityPolling(); // 架构批 W2-B：轮询暂停/恢复监听（浏览器侧装配一次）
  _bindVisibilitySSE(); // 架构批 A6-A：SSE 连接隐藏收束/恢复重开监听（装配一次）
  _bindExportChartEvent(); // 架构批 W4-C：palette act-export-chart 事件桥（装配一次）
  _bindThemeRefresh(); // 架构批 UI-R5：主题联动——body.light 翻转时存活 plotCard 重放配色（装配一次）
  _bindToolsDeepLink(); // 架构批 A2-B：#/tools/<key> 深链自查（app.js 页级路由不认 key 段）
  // 主题四态：读档（旧 "dark" 别名→midnight）→ 应用 → system 态跟随系统
  // 变化 → 按钮四态循环切换。应用=v5.0 双写（html[data-theme] 设计系统
  // 变量面 + body.light 图表消费面信号）——单源在 theme.js applyThemeDom
  //（A5-B/R-4，旧内联 resolved()+apply 双写实现收编）。
  let mode = _LEGACY_ALIAS[localStorage.getItem(THEME_KEY)] || localStorage.getItem(THEME_KEY) || "system";
  if (!THEME_MODES.includes(mode)) mode = "system";
  const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;
  const apply = () => { applyThemeDom(mode); };
  const btn = T.$("theme-toggle");
  const paintBtn = () => {
    if (!btn) return;
    btn.textContent = THEME_LABEL[mode];
    btn.setAttribute("aria-label", `主题：${THEME_LABEL[mode]}（点击切换 Midnight→Ocean→浅色→跟随系统）`);
    btn.title = "点击切换主题：Midnight → Ocean → 浅色 → 跟随系统";
  };
  apply();
  paintBtn();
  // 仅 system 态消费系统主题变化（显式选定主题时不被系统抢走）
  const onSysChange = () => { if (mode === "system") apply(); };
  if (mq) {
    if (mq.addEventListener) mq.addEventListener("change", onSysChange);
    else mq.addListener(onSysChange); // 旧 Safari 降级
  }
  _themeCtl = {
    get: () => mode,
    set: (m) => {
      if (!THEME_MODES.includes(m)) return false;
      mode = m;
      try { localStorage.setItem(THEME_KEY, m); } catch { /* best-effort */ }
      apply();
      paintBtn();
      return true;
    },
  };
  if (btn) {
    btn.onclick = () => _themeCtl.set(THEME_MODES[(THEME_MODES.indexOf(mode) + 1) % THEME_MODES.length]);
  }
}


/* ── 既有公开导出面全量 re-export（facade：拆分后单源在各域模块）──────── */
export {
  esc, escAttr, fmtNum, renderMarkdown,
} from "./pages/dom.js";
export {
  columnIsNumeric, sortCellKey, sortCellCompare, makeSortable,
} from "./pages/sortable.js";
export {
  relTime, freshnessTier, freshnessRingSvg, statusBucket,
} from "./pages/dashboard_util.js";
export {
  sseStreamUrl, sseSubscribedTypes, sseFrameAction, sseEndMark,
  sseShouldGiveUp, sseSubscribeBlocked, ssePollSuppressed,
} from "./pages/sse.js";
export {
  kitTable, kitPanelHead, kitBadgeCls, kitBadge, kitVerdictBadge, kitBoolBadge,
  kitSkeleton, kitSkeletonRows, kitEmptyState, bindEmptyStates, kitErrorPanel,
  kitClickRowAttrs, kitApplyClickRowAttrs, bindClickRows,
} from "./pages/kit.js";
export {
  parseRoute, routeOpenerFor, routeOpen, openRun, openCampaign, showPage,
  pageContextFor,
} from "./pages/router.js";
export {
  calcGroup, groupCalcList, toolFilterMatch, toolsDeepLinkKey, toolsSelectKey,
  toolIsNumList, toolDetectCurves, toolDetectMatrix, toolPickSweepMetric,
  toolDescHasFormula, toolResultCellText,
} from "./pages/view_tools.js";
