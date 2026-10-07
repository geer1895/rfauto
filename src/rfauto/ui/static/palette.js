/* rfauto 命令面板（PR-2，规格 §D-8）：零构建 vanilla ES module。
   数据源：22 页注册表（#nav button[data-v]，DOM 单源）+ /api/runs?limit=200
   + /api/recipes（两个端点均已存在，本模块零新增 /api 面）。
   键位：Ctrl/Cmd+K 开关、Esc 关、↑↓ 选、Enter 执行；`>` 前缀命令、
   `#` 前缀 run（v1 子串匹配，大小写不敏感）；焦点陷阱：打开时存
   activeElement、Tab 在面板内首尾回绕、关闭时还焦。 */
import { showPage, openRun, setThemeMode, getThemeMode } from "./pages.js";

const $ = (id) => document.getElementById(id);

const api = async (url, opts) => (await fetch(url, opts)).json();

/* 查询模式：`>` 前缀=命令、`#` 前缀=run、其余=页面/配方（纯函数，node 可测）。 */
export function modeOf(query) {
  const s = String(query ?? "");
  if (s.startsWith(">")) return "cmd";
  if (s.startsWith("#")) return "run";
  return "nav";
}

/* v1 子串匹配：按模式过滤 + 大小写不敏感子串（纯函数，node 可测）。
   item 契约：{ id, mode, title, subtitle, hint, haystack, run() }。 */
export function filterItems(items, query) {
  const mode = modeOf(query);
  let needle = String(query ?? "").trim().toLowerCase();
  if (mode !== "nav") needle = needle.slice(1).trim();
  const pool = items.filter((it) => it && it.mode === mode);
  if (!needle) return pool;
  return pool.filter((it) =>
    String(it.haystack ?? `${it.title} ${it.subtitle ?? ""}`).toLowerCase().includes(needle));
}

/* 命令注册表（`>` 前缀）：主题三态 PR-1 的外部入口演示面。 */
function commandItems() {
  let cur = "";
  try { cur = getThemeMode(); } catch { /* 模块未就绪时忽略 */ }
  const mk = (id, title, kw, fn) => ({
    id, mode: "cmd", title, subtitle: "命令",
    haystack: `${title} ${kw}`,
    hint: cur === id.slice(6) ? "当前" : "",
    run: fn,
  });
  return [
    mk("theme-dark", "主题：深色", "theme dark 深色 夜间", () => setThemeMode("dark")),
    mk("theme-light", "主题：浅色", "theme light 浅色 亮色 日间", () => setThemeMode("light")),
    mk("theme-system", "主题：跟随系统", "theme system 跟随 自动 auto", () => setThemeMode("system")),
  ];
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
