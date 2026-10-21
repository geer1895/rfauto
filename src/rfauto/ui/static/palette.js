/* rfauto 命令面板（PR-2，规格 §D-8）：零构建 vanilla ES module。
   数据源：nav 页注册表（#nav button[data-v]，DOM 单源）+ /api/runs?limit=200
   + /api/recipes（两个端点均已存在，本模块零新增 /api 面）。
   W3-D（架构批）：命令面扩展——`>` 命令目录抽纯函数 commandCatalog
   （node 可测，动作面注入）：主题四态 + 页面跳转组（go-*，与 showPage 的
   data-v 对齐，出口复用 pages.js 单源）+ 动作命令（刷新当前页/导出当前
   页图表/面板用法提示）。行图标消费 index.html 的 SVG sprite
   （<use href="#icon-*">，aria-hidden 装饰性，stroke=currentColor 随主题）。
   键位：Ctrl/Cmd+K 开关、Esc 关、↑↓ 选、Enter 执行；`>` 前缀命令、
   `#` 前缀 run（v1 子串匹配，大小写不敏感）；焦点陷阱：打开时存
   activeElement、Tab 在面板内首尾回绕、关闭时还焦。
   W2-C：本三件套与 app.js 灯箱（lightboxClose/keydown）是同一模式的两处
   实现——不抽共享模块：app.js 顶层跑 DOM 初始化（three 已改 3D 调用点
   动态 import，W3-S9），本文件若 import 它仍会连带炸掉 node 行为测试
   （无 DOM 环境）的 import 链。两处改动须成对审视，语义保持一致
   （开=存焦点+焦点入层、Tab=回绕、关=Esc/点遮罩+还焦）。 */
import { showPage, openRun, openCampaign, setThemeMode, getThemeMode, pageContextFor } from "./pages.js";
// i18n（架构批 W2-S5，S2 偏差申报收账）：语言切换命令接线——t()/setLocale
// 单源在 pages/i18n.js（零依赖，无 import 环）；读档走 getLocale（与主题
// cur 同款"参数注入"口径：commandCatalog 保持纯函数零 DOM）。
import { getLocale, setLocale } from "./pages/i18n.js";
// P8-9（架构批 W3-S9，R1 §面4）：第三形态裸 fetch 收敛——apiFetch 单源
// （统一错误信封/token 透传/超时与 abort 组合，缺省参数与旧裸 fetch 等价
// 路径）。失败语义保持：loadDynamic 检出错误信封显式 throw → open() 既有
// .catch 静默降级（面板仍可用）+ 错误响应**不入 TTL 缓存**（旧形态 fetch
// 抛错同样不落缓存——apiFetch 永不抛，必须在此翻回抛出）。
// 审查波 2 P3-7 收账：信封失败在 throw 前出 toast（对齐"失败可见"口径
// ——apiFetch notifier 只覆盖网络层失败，服务端错误信封此前被 open() 的
// 静默降级吞掉）。toast 走 #msg 最小镜像（err 类，showPaletteHelp 同款
// 惯例——app.js 禁 import，见文件头）；网络失败双写同一 #msg 同文案，
// 视觉幂等无害；#msg 缺席静默（#105 best-effort）。
import { apiFetch } from "./pages/api.js";
// errorText 回退链单源（dom.js 零顶层 DOM，node 可 import）——信封文案
// 与全站同款（errors join → error → reason → 兜底），不再裸读单数 error。
import { errorText } from "./pages/dom.js";

const $ = (id) => document.getElementById(id);

const _SVG_NS = "http://www.w3.org/2000/svg";

/* W3-D：行装饰图标（index.html sprite 的 <use> 引用，aria-hidden 不进读屏，
   stroke=currentColor 随行文字/选中态变色；CSS 尺寸在 index.html .pico）。 */
function iconSvg(doc, name) {
  const svg = doc.createElementNS(_SVG_NS, "svg");
  svg.setAttribute("class", "pico");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const use = doc.createElementNS(_SVG_NS, "use");
  use.setAttribute("href", `#icon-${name}`);
  svg.appendChild(use);
  return svg;
}

/* P8-3（架构批 R1 §面1，W7 走查 P3-6 收账）：runs+recipes 数据源 TTL
   缓存（60s）——palette 每开必重拉收账（runs/ 现存 3255 条目，本地无感
   但 run 增长与远程部署时线性恶化）。模块级缓存跨开关复用；`#` 前缀命中
   （显式搜 run）时本开启会话强制刷新一次；拉取失败静默降级为仅页面/命令
   （既有 open() catch 语义不变；不加锁，并发过期回源=幂等重拉无害）。
   P8-9（W3-S9）：数据源拉取换 apiFetch 单源；错误信封在此显式翻回 throw
   ——旧行为 fetch 抛错 → 调用方 .catch 降级 + 不落缓存；apiFetch 把网络
   失败折进 {ok:false} 信封（永不抛），若不翻回抛出会把错误信封缓存 60s
   且丢掉"失败必须可见"的 toast 呈现（成功响应无 ok 字段，ok===false
   精确判失败、不误伤无 ok 的成功体）。 */
const _DYN_TTL_MS = 60000;
let _dynCache = null; // { runs, recipes } 原始响应
let _dynCacheAt = 0;
let _runForceDone = false; // 本次开启会话 `#` 强刷已做过一次

/* 信封失败 toast（审查波 2 P3-7）：#msg 最小镜像 err 类（app.js msg 单源
   禁 import，见文件头；#msg 缺席静默，#105 best-effort 不阻主路径）。 */
function showEnvelopeToast(text) {
  try {
    const el = document.getElementById("msg");
    if (!el) return;
    el.textContent = String(text || "命令面板数据源失败");
    el.className = "msg err";
    setTimeout(() => { el.className = "msg"; }, 6000);
  } catch { /* 提示面缺席不阻主路径 */ }
}

async function loadDynamic(force) {
  if (!force && _dynCache && Date.now() - _dynCacheAt < _DYN_TTL_MS)
    return _dynCache;
  const [runs, recipes] = await Promise.all([
    apiFetch("/api/runs?limit=200"), apiFetch("/api/recipes")]);
  if (runs.ok === false || recipes.ok === false) {
    const bad = runs.ok === false ? runs : recipes;
    showEnvelopeToast(errorText(bad, "命令面板数据源失败"));
    throw new Error(errorText(bad, "命令面板数据源失败"));
  }
  _dynCache = { runs, recipes };
  _dynCacheAt = Date.now();
  return _dynCache;
}

/* 查询模式：`>` 前缀=命令、`#` 前缀=run、其余=页面/配方（纯函数，node 可测）。 */
export function modeOf(query) {
  const s = String(query ?? "");
  if (s.startsWith(">")) return "cmd";
  if (s.startsWith("#")) return "run";
  return "nav";
}

/* v1 子串匹配：按模式过滤 + 大小写不敏感子串（纯函数，node 可测）。
   item 契约：{ id, mode, title, subtitle, hint, haystack, icon?, run() }。 */
export function filterItems(items, query) {
  const mode = modeOf(query);
  let needle = String(query ?? "").trim().toLowerCase();
  if (mode !== "nav") needle = needle.slice(1).trim();
  const pool = items.filter((it) => it && it.mode === mode);
  if (!needle) return pool;
  return pool.filter((it) =>
    String(it.haystack ?? `${it.title} ${it.subtitle ?? ""}`).toLowerCase().includes(needle));
}

/* W3-D：视图→sprite symbol 名映射（index.html icon-* 基座的消费索引）。
   sprite 无对应 symbol 的视图不配图（iconForView 返回 "" → 行内不渲染）。 */
const _ICON_BY_VIEW = {
  dashboard: "dashboard", runs: "runs", campaign: "campaign", tune: "tune",
  recipe: "recipe", tools: "tools", gallery: "gallery", profile: "profile",
};
export function iconForView(v) {
  return _ICON_BY_VIEW[v] || "";
}

/* 命令目录（W3-D，纯函数 node 可测）：`>` 前缀命令全集。
   cur=当前主题模式（"当前"提示）；loc=当前语言档（act-locale 提示与切换
   目标；缺省 zh——test_ui_palette_cmds 旧两参调用兼容）；act=注入的动作面
   （生产=下方 commandItems 装配 pages.js 单源出口；node 测试=spy），本函数
   零 DOM。命令总数 20（主题 4 + 跳转 7 + 动作 9；架构批 W5-S17 动作扩充
   同笔 15→20）——总数钉在 tests/unit/test_ui_palette_cmds.py 与
   test_ui_perf_loading.py，增删命令须同笔同步。
   W5-S17（R1 §面3 palette 补全 watch 激活）动作扩充 5 件：
   - act-run-search：`#` run 检索的显式入口（面板转 run 模式——`#` 前缀
     此前只藏在帮助文案里，发现性差）；
   - act-run-latest/2nd/3rd：最近 run top3 直达（rank 1..3 → openRun）；
     run id 经 act.recentRunAt 现取进 hint+检索面（数据未就绪=空串降级为
     静态标题，缺 act 方法=空串——node 旧两参 spy 兼容）；
   - act-latest-campaign：最近战役直达（pareto_runs 首项 → openCampaign
     深链；无战役 run 回落裸战役页）。 */
export function commandCatalog(cur, act, loc) {
  const locale = loc || "zh";
  const mk = (id, title, kw, hint, icon, fn) => ({
    id, mode: "cmd", title, subtitle: "命令",
    haystack: `${title} ${kw}`,
    hint: hint || "",
    icon: icon || "",
    run: fn,
  });
  return [
    /* 主题四态（PR-1 的外部入口演示面，沿用原名原关键词） */
    mk("theme-midnight", "主题：Midnight 深蓝", "theme midnight 深蓝 午夜 夜间 dark",
      cur === "midnight" ? "当前" : "", "", () => act.setTheme("midnight")),
    mk("theme-ocean", "主题：Ocean 青绿", "theme ocean 青绿 海洋",
      cur === "ocean" ? "当前" : "", "", () => act.setTheme("ocean")),
    mk("theme-light", "主题：浅色", "theme light 浅色 亮色 日间",
      cur === "light" ? "当前" : "", "", () => act.setTheme("light")),
    mk("theme-system", "主题：跟随系统", "theme system 跟随 自动 auto",
      cur === "system" ? "当前" : "", "", () => act.setTheme("system")),
    /* 页面跳转命令组（W3-D）：目标与 showPage 的 data-v 对齐（对齐钉
       test_ui_palette_cmds 跨文件核对 nav data-v 全集，防死命令）。 */
    mk("go-runs", "跳转：Run 历史", "go runs run 历史 跳转", "跳转",
      iconForView("runs"), () => act.showPage("runs")),
    mk("go-campaign", "跳转：战役仪表盘", "go campaign 战役 仪表盘 跳转", "跳转",
      iconForView("campaign"), () => act.showPage("campaign")),
    mk("go-tune", "跳转：优化调参", "go tune 调参 优化 跳转", "跳转",
      iconForView("tune"), () => act.showPage("tune")),
    mk("go-recipe", "跳转：配方编辑", "go recipe 配方 编辑 跳转", "跳转",
      iconForView("recipe"), () => act.showPage("recipe")),
    mk("go-tools", "跳转：微波工具箱", "go tools 工具箱 计算器 跳转", "跳转",
      iconForView("tools"), () => act.showPage("tools")),
    mk("go-gallery", "跳转：模板画廊", "go gallery 画廊 模板 跳转", "跳转",
      iconForView("gallery"), () => act.showPage("gallery")),
    mk("go-profile", "跳转：剖析", "go profile 剖析 性能 py-spy 跳转", "跳转",
      iconForView("profile"), () => act.showPage("profile")),
    /* 动作命令（W3-D；导出图表=W4-D） */
    mk("act-refresh", "刷新当前页数据", "refresh 刷新 当前页 reload", "动作",
      "refresh", () => act.refresh()),
    /* 导出当前页图表（W4-D）：事件桥发射端——监听端在 pages.js 侧消费
       （并行席在制），契约=事件名恒 rfauto:export-chart、无 payload。 */
    mk("act-export-chart", "导出当前页图表", "export chart 导出 图表 下载", "动作",
      "", () => act.exportChart()),
    mk("act-palette-help", "帮助：命令面板用法", "help palette 帮助 提示 用法 快捷键",
      "帮助", "", () => act.help()),
    /* 语言切换（架构批 W2-S5，S2 偏差申报收账）：词表 t()/setLocale 已
       随 W1-S2 落地，此处只接命令出口——zh↔en 翻面切换（setLocale 写档+
       全壳重扫，i18n.js 单源）；提示随档翻转（当前档→目标档）。 */
    mk("act-locale", "语言 / Language", "language locale i18n 语言 英文 中文 english 切换",
      locale === "en" ? "切换到中文" : "切换到 English", "",
      () => act.setLocale(locale === "en" ? "zh" : "en")),
    /* 动作扩充（W5-S17，R1 §面3）：run 直达三连——run id 经 act.recentRunAt
       现取（生产=_dynCache 快照；node 旧 spy 无此方法=空串降级，hint 回落
       "直达"）。id 进 haystack → 命令模式下可直接按 run id 检索直达。 */
    mk("act-run-search", "打开 run 详情（输入 id）",
      "open run 打开 run 详情 输入 id 检索 #", "转 # 检索",
      iconForView("runs"), () => act.enterRunSearch()),
    mk("act-run-latest", "打开最近 run ①",
      "latest recent 最近 run 新 直达 打开 " + _recentId(act, 1),
      _recentId(act, 1) || "直达", iconForView("runs"),
      () => act.openRecentRun(1)),
    mk("act-run-2nd", "打开最近 run ②",
      "second 次新 最近 run 直达 打开 " + _recentId(act, 2),
      _recentId(act, 2) || "直达", iconForView("runs"),
      () => act.openRecentRun(2)),
    mk("act-run-3rd", "打开最近 run ③",
      "third 第三新 最近 run 直达 打开 " + _recentId(act, 3),
      _recentId(act, 3) || "直达", iconForView("runs"),
      () => act.openRecentRun(3)),
    mk("act-latest-campaign", "打开最近战役",
      "campaign 战役 最优 调参 优化 最近 直达 trials", "直达",
      iconForView("campaign"), () => act.openLatestCampaign()),
  ];
}

/* W5-S17：最近 run id 现取（命令目录构建期读 act.recentRunAt 快照）。
   act 缺方法（node 旧两参调用）或缺数据（TTL 缓存未就绪）→ 空串，
   hint 回落静态文案、haystack 少一词——零抛降级。 */
function _recentId(act, rank) {
  try {
    return String((act && typeof act.recentRunAt === "function"
      ? act.recentRunAt(rank) : "") || "");
  } catch { return ""; }
}

/* 当前页视图名（W3-D 动作命令的取数面）：app.js activate 写
   aria-current="page"（PR-1），DOM 单源读取、不新增跨模块状态。 */
function currentView() {
  const b = document.querySelector("#nav button[aria-current='page']");
  return b && b.dataset ? b.dataset.v : "";
}

/* 刷新当前页数据（R-1 架构批 W1-S3）：登记了 PageContext.refresh 的页走
   局部刷新（数据拉取与壳渲染分离——dashboard 重铺组件面不重拉 /api/runs、
   loopboard 立即拉一次看板）；未登记页回退 showPage 整页重进（旧行为），
   回退路径 detail 页由 pages.js 内部 currentRunId 重渲染当前 run。 */
function refreshCurrentPage() {
  const v = currentView();
  if (!v) return;
  const ctx = pageContextFor(v);
  if (ctx && typeof ctx.refresh === "function") { ctx.refresh(); return; }
  showPage(v);
}

/* 导出当前页图表（W4-D）：事件桥发射端。window 级 CustomEvent
   "rfauto:export-chart"、无 payload；监听端由 pages.js 侧注册（并行席在
   制），本文件只管发射。export 供 node 行为钉（test_ui_perf_loading）
   直接验证守卫与事件契约。node 无 window：缺席环境静默返回（#105
   best-effort——导出面不得成为业务主路径故障点）。 */
export function fireExportChart() {
  try {
    if (typeof window === "undefined" ||
        typeof window.dispatchEvent !== "function")
      return;
    window.dispatchEvent(new CustomEvent("rfauto:export-chart"));
  } catch { /* 事件桥异常不阻主路径 */ }
}

/* 命令面板用法提示：全局 toast 单源是 app.js msg，但本文件禁 import
   app.js（见文件头——会连带炸 node 行为测试的 import 链），故按同契约
   最小镜像（textContent + msg ok 类 + 定时消退）；#msg 缺席时静默
   （#105 best-effort：提示面不得成为业务主路径故障点）。 */
function showPaletteHelp() {
  try {
    const el = document.getElementById("msg");
    if (!el) return;
    el.textContent = "命令面板：Ctrl/Cmd+K 开关 · 直接输入搜页面与配方 · # 搜 run · > 命令 · ↑↓ 选择 · Enter 执行 · Esc 关闭";
    el.className = "msg ok";
    setTimeout(() => { el.className = "msg"; }, 6000);
  } catch { /* 提示面缺席不阻主路径 */ }
}

/* 命令注册表（`>` 前缀）：生产动作面装配——主题/页面出口均为 pages.js
   单源（既有 import），刷新/导出图表/提示为本文件最小实现（见上）；语言
   出口=i18n.js setLocale 单源（W2-S5 接线）；W5-S17 动作扩充五件出口见
   下方各工厂（recentRunAt/openRecentRun/enterRunSearch/openLatestCampaign）。 */
function commandItems() {
  let cur = "";
  try { cur = getThemeMode(); } catch { /* 模块未就绪时忽略 */ }
  let loc = "zh";
  try { loc = getLocale(); } catch { /* 模块未就绪时忽略 */ }
  return commandCatalog(cur, {
    setTheme: setThemeMode,
    showPage,
    refresh: refreshCurrentPage,
    exportChart: fireExportChart,
    help: showPaletteHelp,
    setLocale,
    /* W5-S17：最近 run id 现取（TTL 缓存快照；未就绪=空串，hint 回落
       "直达"——目录构建期消费，随 applyDynamic→refresh 换代刷新）。 */
    recentRunAt: (rank) => {
      const runs = (((_dynCache || {}).runs || {}).runs) || [];
      return runs[rank - 1] ? String(runs[rank - 1].run_id || "") : "";
    },
    /* 最近 run 直达（rank 1..3）：懒取走 60s TTL 缓存（面板已开时几乎
       零网络）；取不到（空库/数据源失败）静默零动作（#105 best-effort）。 */
    openRecentRun: (rank) => {
      loadDynamic(false).then((d) => {
        const runs = ((d.runs || {}).runs) || [];
        const r = runs[rank - 1];
        if (r && r.run_id) openRun(r.run_id);
      }).catch(() => { /* 数据源失败静默（open() 既有降级语义同源） */ });
    },
    /* `#` 检索模式入口：面板闭包进入器（initPalette 装配单源），未装配
       （异常时序）静默。 */
    enterRunSearch: () => { if (_enterRunSearch) _enterRunSearch(); },
    openLatestCampaign,
  }, loc);
}

/* W5-S17：最近战役直达——pareto_runs 首项（最新带 trials 的 run）→
   openCampaign 深链（待选消费纪律，router.js 单源）；无战役 run/请求失败
   回落裸战役页（showPage 单源），零抛（#105 best-effort）。 */
function openLatestCampaign() {
  apiFetch("/api/pareto_runs").then((d) => {
    const r = (d.runs || [])[0];
    if (r && r.run_id) openCampaign(r.run_id);
    else showPage("campaign");
  }).catch(() => showPage("campaign"));
}

/* W5-S17：`#` 检索模式进入器（面板闭包单源，initPalette 装配）。exec 的
   时序=先 close（还焦 savedFocus）再 run()——本进入器重开面板（open 复位
   输入+焦点入 input）后切 `#` 前缀并重过滤，用户直接键入 run id。 */
let _enterRunSearch = null;

/* 页面项：从导航注册表派生（index.html #nav button[data-v] 单源，无第二份清单）。 */
function pageItems() {
  return [...document.querySelectorAll("#nav button[data-v]")].map((b) => {
    const title = b.textContent.trim().replace(/\s+/g, " ");
    return {
      id: `page-${b.dataset.v}`, mode: "nav", title, subtitle: "页面",
      haystack: `${title} ${b.dataset.v}`,
      hint: "跳转",
      run: () => showPage(b.dataset.v),
    };
  });
}

/* run 项（`#` 前缀）：/api/runs?limit=200。 */
function runItems(runs) {
  return (runs || []).map((r) => {
    const m11 = r.metrics?.s11_db_max_in_band;
    const sub = [r.adapter, r.timestamp || r.ts,
      typeof m11 === "number" ? `S11 ${m11.toFixed(2)}dB` : ""]
      .filter(Boolean).join(" · ");
    return {
      id: `run-${r.run_id}`, mode: "run", title: r.run_id || "(无 id)",
      subtitle: sub, haystack: `${r.run_id} ${r.adapter ?? ""} ${r.model ?? ""}`,
      hint: "打开详情",
      run: () => openRun(r.run_id),
    };
  });
}

/* 配方项：进默认（页面）模式，Enter → 打开配方编辑页并加载该配方。 */
function recipeItems(recipes) {
  return (recipes || []).map((r) => {
    const name = String(r.path || "").split(/[\\/]/).pop();
    return {
      id: `recipe-${r.path}`, mode: "nav", title: name,
      subtitle: `配方 · ${r.model ?? "?"}${r.is_workcopy ? " · 工作副本" : ""}`,
      haystack: `${name} ${r.path ?? ""} ${r.model ?? ""} 配方 recipe`,
      hint: "加载",
      run: () => openRecipe(r.path),
    };
  });
}

/* 配方页首次渲染是同步的（innerHTML+事件绑定先于异步 loadCatalog），
   一个宏任务后设路径并触发既有「加载」按钮——不绕过页面自身链路。 */
function openRecipe(path) {
  showPage("recipe");
  setTimeout(() => {
    const inp = $("recipe-path"), btn = $("recipe-load");
    if (inp) inp.value = path;
    if (btn) btn.click();
  }, 0);
}

export function initPalette(doc = document) {
  const overlay = doc.getElementById("palette-overlay");
  const input = doc.getElementById("palette-in");
  const list = doc.getElementById("palette-list");
  if (!overlay || !input || !list) return null; // 缺骨架（异常部署）时静默不绑

  let items = [];          // 全量索引（页面+命令即时；run/配方懒取）
  let view = [];           // 当前过滤结果
  let sel = 0;             // 当前选中下标
  let savedFocus = null;   // 焦点陷阱：打开前的 activeElement
  let isOpen = false;

  function baseItems() {
    return [...pageItems(), ...commandItems(), ...items.filter((it) => it.mode !== "cmd")];
  }

  function refresh() {
    view = filterItems(baseItems(), input.value);
    if (sel >= view.length) sel = Math.max(0, view.length - 1);
    render();
  }

  function render() {
    list.innerHTML = "";
    if (!view.length) {
      const li = doc.createElement("li");
      li.className = "muted";
      li.textContent = input.value.trim() ? "无匹配结果" : "输入以搜索；# 搜 run，> 命令";
      list.appendChild(li);
      input.removeAttribute("aria-activedescendant");
      return;
    }
    view.forEach((it, i) => {
      const li = doc.createElement("li");
      li.id = `palette-opt-${i}`;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", i === sel ? "true" : "false");
      li.className = i === sel ? "sel" : "";
      if (it.icon) li.appendChild(iconSvg(doc, it.icon));
      const t = doc.createElement("span");
      t.className = "pt";
      t.textContent = it.title;
      li.appendChild(t);
      if (it.subtitle) {
        const s = doc.createElement("span");
        s.className = "pk";
        s.textContent = it.subtitle;
        li.appendChild(s);
      }
      if (it.hint) {
        const h = doc.createElement("span");
        h.className = "pk";
        h.textContent = it.hint;
        li.appendChild(h);
      }
      li.onclick = () => exec(i);
      li.onmousemove = () => { if (sel !== i) { sel = i; paint(); } };
      list.appendChild(li);
    });
    input.setAttribute("aria-activedescendant", `palette-opt-${sel}`);
    const el = list.children[sel];
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
  }

  function paint() {
    [...list.children].forEach((li, i) => {
      li.className = i === sel ? "sel" : "";
      if (li.hasAttribute("role")) li.setAttribute("aria-selected", i === sel ? "true" : "false");
    });
    if (view.length) input.setAttribute("aria-activedescendant", `palette-opt-${sel}`);
  }

  function exec(i) {
    const it = view[i];
    close();
    if (it && typeof it.run === "function") it.run();
  }

  function applyDynamic(d) {
    const dyn = [...runItems(d.runs && d.runs.runs),
                 ...recipeItems([...((d.recipes && d.recipes.recipes) || []),
                   ...(((d.recipes && d.recipes.workcopies) || []).map((w) =>
                     ({ ...w, is_workcopy: true })))])];
    items = dyn;
    if (isOpen) refresh();
  }

  function open() {
    if (isOpen) return;
    isOpen = true;
    savedFocus = doc.activeElement; // 焦点陷阱①：记住来处
    input.value = "";
    sel = 0;
    _runForceDone = false; // P8-3：新开启会话重置 `#` 强刷额度
    overlay.classList.add("show");
    refresh();
    input.focus();
    // 数据源懒取：runs + recipes（P8-3：60s TTL 缓存命中零网络；失败静默
    // 降级为仅页面/命令——面板仍可用）
    loadDynamic(false)
      .then(applyDynamic)
      .catch(() => { /* 面板仍可用（页面+命令） */ });
  }

  function close() {
    if (!isOpen) return;
    isOpen = false;
    overlay.classList.remove("show");
    if (savedFocus && doc.contains(savedFocus) && typeof savedFocus.focus === "function") {
      savedFocus.focus(); // 焦点陷阱③：关闭还焦
    }
    savedFocus = null;
  }

  function toggle() { isOpen ? close() : open(); }

  function move(delta) {
    if (!view.length) return;
    sel = (sel + delta + view.length) % view.length;
    paint();
  }

  input.addEventListener("input", () => {
    sel = 0; refresh();
    // P8-3：`#` 前缀命中（显式搜 run）→ 本会话强制刷新一次绕过 TTL
    // （会话内只刷一次防连键打点；闭包态未就绪静默，#105 best-effort）
    if (modeOf(input.value) === "run" && !_runForceDone) {
      _runForceDone = true;
      loadDynamic(true).then(applyDynamic).catch(() => { /* 降级保旧数据 */ });
    }
  });
  // W5-S17：`#` 检索模式进入器装配（act-run-search 消费单源）——open 复位
  // 输入/焦点后切 `#` 前缀重过滤；触发一次 run 模式强刷额度重置语义由
  // open() 自带（_runForceDone=false），用户未键入时不打点。
  _enterRunSearch = () => {
    open();
    input.value = "#";
    refresh();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Enter") { e.preventDefault(); exec(sel); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "Tab") {
      // 焦点陷阱②：Tab 首尾回绕（面板内可聚焦元素循环，不逃出模态）
      e.preventDefault();
      const focusables = [...overlay.querySelectorAll("input, button, [href], [tabindex]:not([tabindex='-1'])")]
        .filter((el) => !el.disabled && el.offsetParent !== null);
      if (focusables.length) {
        const idx = focusables.indexOf(doc.activeElement);
        const next = e.shiftKey
          ? focusables[(idx - 1 + focusables.length) % focusables.length]
          : focusables[(idx + 1) % focusables.length];
        next.focus();
      }
    }
  });
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  const openBtn = doc.getElementById("palette-open");
  if (openBtn) openBtn.addEventListener("click", open);
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === "k") {
      e.preventDefault();
      toggle();
    }
  });
  return { open, close, toggle, refresh };
}

/* 浏览器引导；node 静态/行为测试 import 时无 DOM 不启动。 */
export function boot() {
  if (typeof document === "undefined") return null;
  return initPalette(document);
}
if (typeof document !== "undefined" && document.getElementById("palette-overlay")) {
  boot();
}
