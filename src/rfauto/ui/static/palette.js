/* rfauto 命令面板（PR-2，规格 §D-8）：零构建 vanilla ES module。
   数据源：nav 页注册表（#nav button[data-v]，DOM 单源）+ /api/runs?limit=200
   + /api/recipes（两个端点均已存在，本模块零新增 /api 面）。
   W3-D（aurora36）：命令面扩展——`>` 命令目录抽纯函数 commandCatalog
   （node 可测，动作面注入）：主题四态 + 页面跳转组（go-*，与 showPage 的
   data-v 对齐，出口复用 pages.js 单源）+ 动作命令（刷新当前页/导出当前
   页图表/面板用法提示）。行图标消费 index.html 的 SVG sprite
   （<use href="#icon-*">，aria-hidden 装饰性，stroke=currentColor 随主题）。
   键位：Ctrl/Cmd+K 开关、Esc 关、↑↓ 选、Enter 执行；`>` 前缀命令、
   `#` 前缀 run（v1 子串匹配，大小写不敏感）；焦点陷阱：打开时存
   activeElement、Tab 在面板内首尾回绕、关闭时还焦。
   W2-C：本三件套与 app.js 灯箱（lightboxClose/keydown）是同一模式的两处
   实现——不抽共享模块：app.js 顶层跑 DOM/three 初始化，本文件若 import
   它会连带炸掉 node 行为测试（无 DOM 环境）的 import 链。两处改动须
   成对审视，语义保持一致（开=存焦点+焦点入层、Tab=回绕、关=Esc/点遮罩
   +还焦）。 */
import { showPage, openRun, setThemeMode, getThemeMode, pageContextFor } from "./pages.js";

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

const api = async (url, opts) => (await fetch(url, opts)).json();

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
   cur=当前主题模式（"当前"提示）；act=注入的动作面（生产=下方
   commandItems 装配 pages.js 单源出口；node 测试=spy），本函数零 DOM。
   命令总数 14（主题 4 + 跳转 7 + 动作 3）——总数钉在
   tests/unit/test_ui_palette_cmds.py，增删命令须同笔同步。 */
export function commandCatalog(cur, act) {
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
  ];
}

/* 当前页视图名（W3-D 动作命令的取数面）：app.js activate 写
   aria-current="page"（PR-1），DOM 单源读取、不新增跨模块状态。 */
function currentView() {
  const b = document.querySelector("#nav button[aria-current='page']");
  return b && b.dataset ? b.dataset.v : "";
}

/* 刷新当前页数据（R-1 aurora72 W1-S3）：登记了 PageContext.refresh 的页走
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
   单源（既有 import），刷新/导出图表/提示为本文件最小实现（见上）。 */
function commandItems() {
  let cur = "";
  try { cur = getThemeMode(); } catch { /* 模块未就绪时忽略 */ }
  return commandCatalog(cur, {
    setTheme: setThemeMode,
    showPage,
    refresh: refreshCurrentPage,
    exportChart: fireExportChart,
    help: showPaletteHelp,
  });
}

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

  function open() {
    if (isOpen) return;
    isOpen = true;
    savedFocus = doc.activeElement; // 焦点陷阱①：记住来处
    input.value = "";
    sel = 0;
    overlay.classList.add("show");
    refresh();
    input.focus();
    // 数据源懒取：runs + recipes（失败静默降级为仅页面/命令）
    Promise.all([api("/api/runs?limit=200"), api("/api/recipes")])
      .then(([runs, recipes]) => {
        const dyn = [...runItems(runs && runs.runs),
                     ...recipeItems([...((recipes && recipes.recipes) || []),
                       ...(((recipes && recipes.workcopies) || []).map((w) =>
                         ({ ...w, is_workcopy: true })))])];
        items = dyn;
        if (isOpen) refresh();
      })
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

  input.addEventListener("input", () => { sel = 0; refresh(); });
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
